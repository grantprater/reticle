"""PROTOTYPE, not wired into the pipeline: player position off the minimap.

Run it directly; it writes nothing to the store.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_position.py <session> <from_s> <to_s> <hz> [out.png]

Measured on 9acf02f98283, 60 s at 10 Hz: 86% of frames yield a position, 92%
coverage after filtering and interpolation, 1.5% of steps physically
implausible. Earlier variants are recorded at the bottom -- every one of them
traded recall against jumps without beating this, and knowing which ones failed
is most of the value here.

Why this shape
--------------
The widget is semi-transparent *only over the void*. The walkable floor slab is
opaque, and icons only ever stand on floor, so masking to the floor removes the
churn that defeats every content-based approach: when the player turns, the
world behind the void moves and the whole widget changes.

Per-frame detection does not have to be good, because movement is physically
bounded. A step implying more than RUN_PX px/s is a misdetection whatever the
blob looked like, and gaps shorter than GAP_MS interpolate cleanly. Filtering
the trajectory is worth more than any amount of per-frame tuning.

The static map falls out for free as a per-pixel median across the session --
icons move, map furniture does not. That same image is the occlusion grid a
visibility metric needs, so one extraction serves both.

Known limits
------------
* No elevation. The floorplan is a 2D silhouette, so a bridge and the floor
  beneath it are one region. This is the standing limit on any geometry work.
* Enemies are not on the minimap at all, only red X last-known marks.
* Scale is roughly 0.2 m per pixel, from map extent rather than calibration.
* Map identity is unknown. Geometry should be shared between sessions on the
  same map rather than re-derived, which needs a label at ingest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.profiles import get_profile           # noqa: E402

STORE = Path.home() / "reticle-store"
# Top speed of a real track, px/s, measured rather than derived: every filtered
# track sits under it and every misdetection blew far past it.
RUN_PX = 45.0
GAP_MS = 1000.0
# The pale yellow-green the game rings the local player with -- the same colour
# scoreboard.py keys the player's own row on, and it transfers unchanged.
SELF_G_MIN, SELF_R_MIN, SELF_B_UNDER_G = 200, 140, 45
ALLY_H, ALLY_S_MIN, ALLY_V_MIN = (75, 100), 90, 140
MIN_ICON_AREA = 10


def _roi_px(prof, w, h):
    return next(r for r in prof.rois if r.name == "minimap").pixels(w, h)


def static_map(cap, fps, spans, box, n=120):
    """The map with every icon removed, as a per-pixel median."""
    x0, y0, x1, y1 = box
    total = sum(b - a for a, b in spans)
    stride = total / n
    frames = []
    for a, b in spans:
        t = a
        while t < b:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
            ok, fr = cap.read()
            if ok:
                frames.append(fr[y0:y1, x0:x1])
            t += stride
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def floor_mask(med):
    """The opaque walkable slab. Everything else is see-through and churns."""
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 110)
    return cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0


def _rings(mask, floor):
    m = cv2.morphologyEx((mask & floor).astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((3, 3), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    return [(int(st[i, 4]), float(cen[i][0]), float(cen[i][1]))
            for i in range(1, n) if st[i, 4] >= MIN_ICON_AREA]


def self_rings(crop, floor):
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    return _rings((g > SELF_G_MIN) & (r > SELF_R_MIN)
                  & ((g - b) > SELF_B_UNDER_G), floor)


def ally_rings(crop, floor):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))
    return _rings((hh > ALLY_H[0]) & (hh < ALLY_H[1])
                  & (ss > ALLY_S_MIN) & (vv > ALLY_V_MIN), floor)


def filter_track(found, step):
    """Drop impossible steps, then interpolate the short gaps they leave."""
    keep = []
    for p in found:
        if keep:
            dt = (p[0] - keep[-1][0]) / 1000.0
            if dt > 0 and np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]) / dt > RUN_PX * 1.6:
                continue
        keep.append(p)
    out = []
    for a, b in zip(keep, keep[1:]):
        out.append(a)
        gap = b[0] - a[0]
        if step < gap <= GAP_MS:
            k = int(round(gap / step)) - 1
            for j in range(1, k + 1):
                f = j / (k + 1)
                out.append((a[0] + gap * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
    if keep:
        out.append(keep[-1])
    return out


def main() -> int:
    sid, t0, t1, hz = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    box = _roi_px(prof, w, h)
    x0, y0, x1, y1 = box

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]

    cap = cv2.VideoCapture(str(src["path"]))
    med = static_map(cap, fps, spans, box)
    floor = floor_mask(med)
    print(f"walkable floor {floor.mean() * 100:.1f}% of the widget")

    step = 1000.0 / hz
    raw, prev, base = [], None, None
    t = t0 * 1000
    while t <= t1 * 1000:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            break
        crop = fr[y0:y1, x0:x1]
        if base is None:
            base = crop.copy()
        cands = self_rings(crop, floor)
        pick = None
        if cands:
            if prev is not None:
                lim = RUN_PX * (step / 1000.0) * 2.0
                near = [c for c in cands if np.hypot(c[1] - prev[0], c[2] - prev[1]) <= lim]
                pick = max(near, key=lambda c: c[0]) if near else None
            if pick is None:
                pick = max(cands, key=lambda c: c[0])
        if pick:
            prev = (pick[1], pick[2])
        raw.append((t, pick[1], pick[2]) if pick else (t, None, None))
        t += step
    cap.release()

    found = [p for p in raw if p[1] is not None]
    track = filter_track(found, step)
    print(f"raw    {len(found)}/{len(raw)} ({len(found) / len(raw) * 100:.1f}%)")
    print(f"filter {len(track)} points ({len(track) / len(raw) * 100:.1f}% coverage)")
    sp = np.array([np.hypot(b[1] - a[1], b[2] - a[2]) / ((b[0] - a[0]) / 1000.0)
                   for a, b in zip(track, track[1:]) if 0 < b[0] - a[0] <= 1.5 * step])
    if sp.size:
        print(f"       px/s median {np.median(sp):.1f}  p95 {np.percentile(sp, 95):.1f}  "
              f"max {sp.max():.1f}   jumps>60: {(sp > 60).mean() * 100:.1f}%")

    if len(sys.argv) > 5:
        vis = cv2.resize(base, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        for a, b in zip(track, track[1:]):
            cv2.line(vis, (int(a[1] * 3), int(a[2] * 3)), (int(b[1] * 3), int(b[2] * 3)),
                     (0, 255, 255), 2, cv2.LINE_AA)
        for p in track:
            cv2.circle(vis, (int(p[1] * 3), int(p[2] * 3)), 2, (0, 0, 255), -1)
        cv2.imwrite(sys.argv[5], vis)
        print("wrote", sys.argv[5])
    return 0


# What was tried and rejected, measured on the same 60 s window
# -------------------------------------------------------------
#   colour, largest blob             90% found, many jumps -- the A/B site
#                                    boxes are the *same* pale yellow-green as
#                                    the player's ring and are far larger.
#   + size gate                      68%. The ring fragments under the widget's
#                                    transparency, so real icons fail it too.
#   + centroid hole test             18%. A ring has a hole and a site box does
#                                    not, but at 10 px a partial arc's centroid
#                                    lands on ink and the test rejects it.
#   + interior-fill test             31%. Same defect, relaxed and still wrong.
#   persistence mask                 0.0% of the widget marked static. The trick
#                                    that finds the killfeed's overlay boxes
#                                    fails here: transparency makes the site
#                                    boxes' colour swim with the world behind.
#   background differencing          4-7%. The blobs it finds are median BGR
#                                    (40,40,50) -- the world moving behind the
#                                    void, not icons. Fatal for the same reason.
if __name__ == "__main__":
    raise SystemExit(main())
