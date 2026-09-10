r"""Propose OBJECTS with no colour key, from the map's own lighting band.

    .\.venv\Scripts\python.exe prototypes\object_proposals.py c40d950031bb \
        --at 413.983 308.233 780.467 507.233 --sheet out.png

Why this exists
---------------
The appearance plan says to mine exemplars and never said how, and the reason
is visible in one line of `minimap_occlusion.py`: `foreign_fraction` asks, per
pixel, whether the grey leaves the map's measured `[lo_gray, hi_gray]` band --
*something is drawn here*, naming no colour and no class -- and then reduces
that to a scalar and throws the mask away. **The mask is the object proposer.**
Every prototype here was built to answer one detector's question, so none of
them ever enumerated objects.

This keeps the mask. It runs strictly inside the OPAQUE SLAB, because outside
it the widget is see-through and the live world bleeds in, which is the
documented cause of reading scenery as icons; inside it the stored static map
is a valid background.

What it is allowed to be bad at
-------------------------------
The proposal count exceeds the five or six real icons on a frame, and much of
the excess is map furniture -- which `doctor` already reports as a standing
finding and which is removable precisely because it is STATIC. That is
acceptable HERE and would not be in a reader. A detector needs per-frame
precision; a miner needs RECURRENCE, because artwork repeats across thousands
of frames with a consistent appearance and speckle does not, so junk never
forms a cluster. This is the one place a loose proposer is the right
instrument, and it is why mining must not be built out of the readers.

Diagnostic only. It labels nothing, changes no reader, and selects no
threshold; the margins are swept rather than chosen.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (ally_mask, minimap_roi_px, self_mask,  # noqa: E402
                             slab_mask, widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

#: Icon areas in reference px, scaled by the widget. The upper bound keeps a
#: smoke region from being proposed as an icon; regions are their own family.
ICON_AREA_REF = (10, 400)
MARGINS = (6.0, 10.0, 14.0)


def foreign(grey: np.ndarray, lo: np.ndarray, hi: np.ndarray,
            slab: np.ndarray, margin: float) -> np.ndarray:
    """Pixels the map's two lighting states do not explain, inside the slab."""
    return ((grey < lo - margin) | (grey > hi + margin)) & slab


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--at", type=float, nargs="+", required=True,
                    help="instants in seconds")
    ap.add_argument("--sheet", default=None, help="render proposals here")
    args = ap.parse_args(argv)

    store = Store(args.store)
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{args.session}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    med = store.read_static_map(args.session)
    if med is None:
        raise SystemExit("no cached static map; run `reticle minimap` first")
    sd = geometry.stability(args.session, store.root, med.shape[:2])
    slab = slab_mask(med, sd=sd)
    with np.load(geometry.require(args.session, store.root)) as z:
        lo, hi = z["lo_gray"].astype(np.float32), z["hi_gray"].astype(np.float32)

    want = [t * 1000.0 for t in args.at]
    spans = [(t - 60.0, t + 60.0) for t in want]
    got: dict[float, np.ndarray] = {}
    for _who, smp in sample_windows(src["path"], float(src["fps"]),
                                    {"native": (float(src["fps"]), spans)}):
        for t in want:
            if abs(smp.t_ms - t) < 30.0 and t not in got:
                got[t] = smp.frame[y0:y1, x0:x1].copy()

    sc = widget_scale(med.shape[1])
    lo_a = max(4, int(round(ICON_AREA_REF[0] * sc * sc)))
    hi_a = int(round(ICON_AREA_REF[1] * sc * sc))
    print(f"{args.session}: slab {int(slab.sum())} px, icon band {lo_a}-{hi_a} px "
          f"at scale {sc:.3f}")
    panels = []
    for t in want:
        if t not in got:
            print(f"{t/1000:8.2f}s  NOT RECOVERED")
            continue
        crop = got[t]
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        print(f"\n{t/1000:8.2f}s")
        for m in MARGINS:
            f = foreign(grey, lo, hi, slab, m)
            n, lbl, st, _c = cv2.connectedComponentsWithStats(f.astype(np.uint8), 8)
            areas = st[1:, 4]
            in_band = int(((areas >= lo_a) & (areas <= hi_a)).sum())
            print(f"    margin {m:4.1f}   foreign {int(f.sum()):5d} px "
                  f"({f.sum() / slab.sum() * 100:5.2f}% of slab)   "
                  f"{n - 1:4d} components, {in_band:3d} in the icon band")
            if args.sheet and m == MARGINS[1]:
                panels.append(_render(crop, lbl, st, n, lo_a, hi_a, t))
    if args.sheet and panels:
        w = max(p.shape[1] for p in panels)
        panels = [cv2.copyMakeBorder(p, 2, 2, 2, w - p.shape[1] + 2,
                                     cv2.BORDER_CONSTANT, value=(35, 35, 35))
                  for p in panels]
        rows = [np.hstack(panels[i:i + 2]) for i in range(0, len(panels), 2)]
        rows = [r for r in rows if r.shape[1] == rows[0].shape[1]] or rows[:1]
        cv2.imwrite(args.sheet, np.vstack(rows))
        print(f"\n{args.sheet}")
    return 0


def _render(crop, lbl, st, n, lo_a, hi_a, t_ms):
    """Proposals tinted; blue means NO existing colour key would find it."""
    vis = crop.copy()
    keyed = (self_mask(crop) > 0) | (ally_mask(crop) > 0)
    for i in range(1, n):
        if not (lo_a <= st[i, 4] <= hi_a):
            continue
        col = (60, 220, 255) if keyed[lbl == i].any() else (255, 120, 60)
        vis[lbl == i] = (0.45 * vis[lbl == i] + 0.55 * np.array(col)).astype(np.uint8)
    bar = np.full((20, vis.shape[1], 3), 25, np.uint8)
    cv2.putText(bar, f"{t_ms/1000:.1f}s   blue = no colour key", (4, 14),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (225, 225, 225), 1)
    return np.vstack([bar, vis])


if __name__ == "__main__":
    raise SystemExit(main())
