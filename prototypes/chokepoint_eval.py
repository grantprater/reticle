"""Do location-banner transitions land on the map's physical chokepoints?

    .\\.venv\\Scripts\\python.exe prototypes\\chokepoint_eval.py <session> [--dump]

Validates `minimap_position.py`'s self-tracking without painting anything by
hand -- Grant's objection to hand-painting region boundaries (2026-09-01) was
right: there's nothing on the map to paint against, so a guessed boundary
would just be new unverified labels wearing a costume.

What this uses instead: named regions almost always meet at a physical
doorway, and a doorway is a purely geometric fact -- the walkable floor gets
locally NARROW there. That's derivable straight from `floor_mask`, using
nothing semantic and nothing hand-labelled.

Method
------
1. Chokepoints: distance-transform the floor mask (distance to nearest wall),
   keep local-maximum ("ridge"/medial-axis) pixels, then keep the ridge
   pixels whose distance is small relative to the rest of the ridge -- a
   narrow point on the walkable spine. Cluster into discrete points.
2. Coarse-bracket every banner-text transition (mask IoU drop against the
   last non-blank reading) to within one sample stride.
3. Around each bracket, sample `self_rings()` at a finer stride and take the
   CLOSEST sampled position to any chokepoint -- same "closest of several
   candidates" shape as the X-mark check, so it carries the same caveat and
   the same fix: a null baseline of matched-size windows at times NOT near
   any transition. If transition windows land closer to chokepoints than the
   baseline does, that's real evidence, not an artefact of having several
   candidates to pick from.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import decode                                        # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
import minimap_position as mp                                     # noqa: E402
from location_banner_probe import banner_box, text_mask, iou      # noqa: E402

STORE = Path.home() / "reticle-store"
COARSE_STRIDE_S = 2.0
FINE_STRIDE_S = 0.3
BRACKET_PAD_S = 1.0
RIDGE_MIN_DT = 2.0        # ignore ridge noise this close to a wall
CHOKE_PCTL = 30           # bottom Nth percentile of ridge width = a chokepoint
MIN_BLOB_PX = 2


RIM_ERODE_PX = 10  # `floor_mask` picks up noise at the widget's circular edge
TOP_MARGIN_PX = 16  # the location banner bleeds into the top rows of the minimap ROI itself


def find_chokepoints(floor):
    floor = floor.copy()
    floor[:TOP_MARGIN_PX, :] = False
    eroded = cv2.erode(floor.astype(np.uint8),
                        np.ones((RIM_ERODE_PX, RIM_ERODE_PX), np.uint8)) > 0
    dt = cv2.distanceTransform(eroded.astype(np.uint8), cv2.DIST_L2, 5)
    dil = cv2.dilate(dt, np.ones((5, 5), np.float32))
    ridge = (dt >= dil - 1e-3) & eroded & (dt > RIDGE_MIN_DT)
    ridge_vals = dt[ridge]
    if ridge_vals.size == 0:
        return [], dt
    cut = np.percentile(ridge_vals, CHOKE_PCTL)
    choke = ridge & (dt <= cut)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(choke.astype(np.uint8), 8)
    pts = [(float(cen[i][0]), float(cen[i][1])) for i in range(1, n) if st[i, 4] >= MIN_BLOB_PX]
    return pts, dt


def nearest_choke(p, chokes):
    return min(np.hypot(p[0] - c[0], p[1] - c[1]) for c in chokes)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--dump", action="store_true", help="write a chokepoint-overlay PNG")
    a = ap.parse_args()
    sid = a.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    mm_box = next(r for r in prof.rois if r.name == "minimap").pixels(w, h)
    mx0, my0, mx1, my1 = mm_box
    bx0, by0, bx1, by1 = banner_box(mm_box, w, h)

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(s0, s1) for s0, s1, s in zip(tbl.column("t_start_ms").to_pylist(),
                                           tbl.column("t_end_ms").to_pylist(),
                                           tbl.column("state").to_pylist()) if s == "active"]

    cap = cv2.VideoCapture(str(src["path"]))
    med = mp.static_map(cap, fps, spans, mm_box)
    cap.release()  # everything below uses decode.sample_at(), which opens its own
    floor = mp.floor_mask(med)
    chokes, dt = find_chokepoints(floor)
    print(f"{len(chokes)} chokepoints found "
          f"(ridge cut at p{CHOKE_PCTL} = {np.percentile(dt[floor & (dt > RIDGE_MIN_DT)], CHOKE_PCTL):.1f}px)")

    if a.dump:
        vis = cv2.resize(med, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        for cx, cy in chokes:
            cv2.circle(vis, (int(cx * 3), int(cy * 3)), 5, (0, 0, 255), -1)
        out = Path.cwd() / f"chokepoints_{sid}.png"
        cv2.imwrite(str(out), vis)
        print(f"wrote {out}")

    # -- coarse transitions ---------------------------------------------------
    # A single-sample IoU drop fires on lighting noise, not just real text
    # changes (445 "transitions" in one 40 min match, before this fix). Require
    # the new mask to repeat on the NEXT sample too before calling it real.
    #
    # One sequential decode.sample_at() pass over every coarse timestamp,
    # instead of one cap.set() seek per sample -- this and the fine pass below
    # are what pinned every core for ~50 minutes running three sessions back
    # to back (measured directly, 2026-09-02). See reticle/decode.py.
    coarse_stride_ms = COARSE_STRIDE_S * 1000.0
    coarse_targets = []
    for s0, s1 in spans:
        t = s0
        while t < s1:
            coarse_targets.append(t)
            t += coarse_stride_ms

    masks_seq = []
    for target_t, sample in zip(coarse_targets, decode.sample_at(str(src["path"]), coarse_targets, fps)):
        crop = sample.frame[by0:by1, bx0:bx1]
        m = text_mask(crop)
        masks_seq.append(m if m.sum() >= 15 else None)

    last_stable_mask, last_stable_t = None, None
    pending_mask, pending_t = None, None
    brackets = []
    for t, m in zip(coarse_targets, masks_seq):
        if m is None:
            continue
        if last_stable_mask is None:
            last_stable_mask, last_stable_t = m, t
        elif iou(m, last_stable_mask) >= 0.55:
            pending_mask, pending_t = None, None  # back to the stable reading
        elif pending_mask is not None and iou(m, pending_mask) >= 0.55:
            brackets.append((last_stable_t, pending_t))
            last_stable_mask, last_stable_t = m, t
            pending_mask, pending_t = None, None
        else:
            pending_mask, pending_t = m, t
    print(f"{len(brackets)} coarse transition brackets")

    # -- fine self-position sampling: transitions + null baseline, ONE pass --
    fine_ms = BRACKET_PAD_S * 1000.0
    fine_step_ms = FINE_STRIDE_S * 1000.0
    tagged = []  # (t_target, ('t', bracket_idx) | ('b', baseline_idx))
    for i, (t_lo, t_hi) in enumerate(brackets):
        t = t_lo - fine_ms
        while t <= t_hi + fine_ms:
            tagged.append((t, ("t", i)))
            t += fine_step_ms

    # baseline window TIME RANGES only -- pure arithmetic, no decoding yet
    rng = random.Random(7)
    span_total = sum(b - a_ for a_, b in spans)
    win = 2 * fine_ms + coarse_stride_ms
    baseline_windows = []
    attempts = 0
    while len(baseline_windows) < len(brackets) * 3 and attempts < len(brackets) * 30:
        attempts += 1
        pick = rng.uniform(0, span_total)
        acc, tm = 0.0, None
        for s0, s1 in spans:
            if acc + (s1 - s0) >= pick:
                tm = s0 + (pick - acc)
                break
            acc += (s1 - s0)
        if tm is None or any(abs(tm - (lo + hi) / 2) < win for lo, hi in brackets):
            continue
        baseline_windows.append((tm - win / 2, tm + win / 2))
    for j, (t_lo, t_hi) in enumerate(baseline_windows):
        t = t_lo
        while t <= t_hi:
            tagged.append((t, ("b", j)))
            t += fine_step_ms

    tagged.sort(key=lambda x: x[0])
    fine_targets = [t for t, _tag in tagged]
    trans_positions = [[] for _ in brackets]
    baseline_positions = [[] for _ in baseline_windows]
    for (_t, tag), sample in zip(tagged, decode.sample_at(str(src["path"]), fine_targets, fps)):
        crop = sample.frame[my0:my1, mx0:mx1]
        pos = [(cx, cy) for _area, cx, cy in mp.self_rings(crop, floor)]
        kind, i = tag
        (trans_positions if kind == "t" else baseline_positions)[i].extend(pos)

    trans_dists = [min(nearest_choke(p, chokes) for p in pos)
                   for pos in trans_positions if pos and chokes]
    baseline_dists = [min(nearest_choke(p, chokes) for p in pos)
                      for pos in baseline_positions if pos and chokes]

    print(f"scored {len(trans_dists)}/{len(brackets)} transitions, "
          f"{len(baseline_dists)} baseline windows")
    if trans_dists:
        td = np.array(trans_dists)
        print(f"transition -> nearest chokepoint, px: median {np.median(td):.1f}  "
              f"p75 {np.percentile(td, 75):.1f}  (~0.2 m/px)")
    if baseline_dists:
        bd = np.array(baseline_dists)
        print(f"baseline   -> nearest chokepoint, px: median {np.median(bd):.1f}  "
              f"p75 {np.percentile(bd, 75):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
