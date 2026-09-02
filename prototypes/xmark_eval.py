"""Does `minimap_position.ally_rings()` actually land where a death later marks?

    .\\.venv\\Scripts\\python.exe prototypes\\xmark_eval.py <session>

First accuracy check against real ground truth for ally position tracking,
rather than the self-consistency numbers (coverage, physical plausibility)
`minimap_position.py` already reports. The X mark is independent of the ring
detector -- different colour channel, different code path, anchored to a
killfeed death that's already verified against the scoreboard -- so a close
match is real evidence, not circularity.

Method, and its one real caveat
--------------------------------
For each verified ally-teammate death (see `xmark_probe.py`'s derivation):
run `ally_rings()` over the 2 s before the death and keep every candidate
position seen; detect the blue X blob 1.5 s after the death; report the
distance from the CLOSEST pre-death candidate to the X.

The caveat: with up to ~4 allies on screen, "closest of several" will always
look better than a single detector's true accuracy, since a nearby candidate
can win by chance rather than by tracking the dying player specifically. To
size that effect, this also reports the median distance BETWEEN all same-frame
ally candidates, as a scale reference -- if closest-to-X distances are much
smaller than that, the match is doing real work, not just picking the nearest
of a spread-out crowd.
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import decode                                        # noqa: E402
from reticle.checks import track_entries                          # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
import minimap_position as mp                                     # noqa: E402

STORE = Path.home() / "reticle-store"
COINCIDE_MS = 500.0

# Measured off two real X marks on 9acf02f98283 (xmark_probe.py):
# mean HSV (106.9, 175.3, 192.1) and (106.3, 171.0, 177.8) -- tight agreement.
XMARK_H, XMARK_S_MIN, XMARK_V_MIN = (95, 118), 100, 100
XMARK_AREA = (15, 120)  # native-res px^2; measured blobs were ~39 and ~53


def teammate_deaths(hud):
    t = hud.column("t_ms").to_pylist()
    dividers = hud.column("kf_entry_wx").to_pylist() if "kf_entry_wx" in hud.column_names else None
    death_dividers = hud.column("kf_death_wx").to_pylist() if "kf_death_wx" in hud.column_names else None
    self_deaths = [a for a in track_entries(t, hud.column("kf_death_mask").to_pylist(), death_dividers)
                   if a["counted"]]
    ally_tracks = [a for a in track_entries(t, hud.column("kf_ally_mask").to_pylist(), dividers)
                   if a["counted"]]

    def is_self(a):
        return any(abs(a["t_first"] - s["t_first"]) <= COINCIDE_MS for s in self_deaths)

    return [a for a in ally_tracks if not is_self(a)]


def xmark_blob(crop, floor):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))
    mask = ((hh > XMARK_H[0]) & (hh < XMARK_H[1]) & (ss > XMARK_S_MIN) & (vv > XMARK_V_MIN)
            & floor)
    n, _lab, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    cands = [(int(st[i, 4]), float(cen[i][0]), float(cen[i][1])) for i in range(1, n)
             if XMARK_AREA[0] <= st[i, 4] <= XMARK_AREA[1]]
    return max(cands, key=lambda c: c[0]) if cands else None


def main() -> int:
    sid = sys.argv[1]
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    box = mp._roi_px(prof, w, h)
    x0, y0, x1, y1 = box

    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    deaths = teammate_deaths(hud)
    print(f"{len(deaths)} teammate (non-self) deaths")

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]

    cap = cv2.VideoCapture(str(src["path"]))
    med = mp.static_map(cap, fps, spans, box)
    cap.release()  # everything below uses decode.sample_at(), which opens its own
    floor = mp.floor_mask(med)

    # One sequential decode.sample_at() pass over every pre-death and X-search
    # target, instead of one cap.set() seek per sample -- this was one of the
    # scripts that pinned every core for ~50 min running three sessions back
    # to back (measured 2026-09-02). See reticle/decode.py and chokepoint_eval.py.
    tagged = []  # (t_abs, "pre" | "x", death_idx)
    for i, a in enumerate(deaths):
        td = a["t_first"]
        tm = td - 2000.0
        while tm < td:
            tagged.append((tm, "pre", i))
            tm += 200.0
        # Scan for the X rather than trust one fixed offset -- xmark_diag.py
        # found it can show up anywhere from 0.3s to 3.0s after the death.
        dt = 300.0
        while dt <= 3300.0:
            tagged.append((td + dt, "x", i))
            dt += 300.0
    tagged.sort(key=lambda item: item[0])
    targets = [t for t, _kind, _i in tagged]

    pre_positions = [[] for _ in deaths]
    x_hits = [[] for _ in deaths]  # appended in increasing dt order by construction
    for (_t, kind, i), sample in zip(tagged, decode.sample_at(str(src["path"]), targets, fps)):
        crop = sample.frame[y0:y1, x0:x1]
        if kind == "pre":
            pre_positions[i].extend((cx, cy) for _area, cx, cy in mp.ally_rings(crop, floor))
        else:
            x_hits[i].append(xmark_blob(crop, floor))

    close_dists, spread_dists, n_no_x, n_no_ally = [], [], 0, 0
    for i in range(len(deaths)):
        xb = next((b for b in x_hits[i] if b is not None), None)
        if xb is None:
            n_no_x += 1
            continue
        pre = pre_positions[i]
        if not pre:
            n_no_ally += 1
            continue
        _area, xx, xy = xb
        d = min(np.hypot(px - xx, py - xy) for px, py in pre)
        close_dists.append(d)
        if len(pre) > 1:
            spread_dists.extend(np.hypot(p1[0] - p2[0], p1[1] - p2[1])
                                 for p1, p2 in itertools.combinations(pre, 2))

    print(f"no X detected 1.5s after: {n_no_x}/{len(deaths)}")
    print(f"X detected but no ally candidate in the 2s before: {n_no_ally}/{len(deaths)}")
    print(f"scored: {len(close_dists)}/{len(deaths)}")
    if close_dists:
        cd = np.array(close_dists)
        print(f"closest-pre-death-candidate to X, px: median {np.median(cd):.1f}  "
              f"p95 {np.percentile(cd, 95):.1f}  max {cd.max():.1f}")
        print(f"  (~0.2 m/px per minimap_position.py, so median ~{np.median(cd)*0.2:.1f} m)")
    if spread_dists:
        sd = np.array(spread_dists)
        print(f"scale ref -- same-frame ally-to-ally spread, px: median {np.median(sd):.1f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
