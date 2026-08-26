"""Does the enlarged minimap's enemy icon SEAL into a ring?

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_icons.py <video> [--n 120]

Everything about minimap icon extraction was blocked by one thing, measured five
ways in `minimap_position.py`: **the ring does not seal, and the closing radius
that would seal it merges adjacent icons.** At the old widget size the ring was
~12 px across and shattered -- median blob 7 px, 58% under 10 px -- so the
ceiling across every approach was 77-79% of frames that provably contain a
visible enemy, where a proof gate needs ~100%. The conclusion recorded there was
that the fix is capture-side, not algorithmic.

Grant enlarged the widget on 2026-08-26. The ring now measures ~21 px across
with a 2-3 px band. This asks the one question that decides whether the whole
minimap line reopens: **does it seal now?**

Two conditions, and the second is the one that matters
------------------------------------------------------
The only capture with the enlarged minimap is also LOSSLESS, so it changes two
things at once and cannot answer the question on its own. 4:2:0 chroma
subsampling was just measured to destroy 34% of the *screen* rim, which is the
same 1-4 px scale as this ring and defined the same way -- by colour. So the
enlarged minimap surviving in lossless says nothing about whether it survives in
an ordinary capture.

Subsampling the lossless frames gives both conditions from one file, and the
4:2:0 column is a direct prediction for the full-length captures recorded at
standard settings.

What is measured
----------------
Per red blob on the widget: area, whether it encloses a hole at all (the seal),
how much of it is hole, and how bright that hole is. An enemy icon rings a
bright agent portrait; an X mark -- the same red, hue 177 either way, so colour
cannot separate them -- is solid throughout. That is the hollowness signal that
already separated 0.76 against 0.92 at the old size, now asked of a ring twice
the diameter.

Not a detector. This characterises the signal so the decision to build one is
made on measurement rather than on a promising-looking screenshot.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from chroma_test import to_420                                 # noqa: E402

# Measured off the enlarged widget on 2026-08-26: the enemy ring sits at hue
# 177, sat 152, val 197, and the X mark at hue 177, sat 156, val 196 -- the same
# red, which is exactly why hollowness rather than colour has to do the work.
#
# SAT_MIN is load-bearing and 120 is WRONG. At 120 the enemy ring does not seal
# at all; at 100 the same icon encloses a 259 px hole -- a portrait-sized
# interior. The outer half of the ring is anti-aliased against the map and its
# saturation falls between the two, so a cut 20 points too tight opens the ring
# and destroys the only feature that identifies it. This is the "never test an
# absolute level against this HUD" convention biting on the minimap: the ring is
# composited over live scenery, so the level that separates it is not constant.
HUE_LO, HUE_HI, SAT_MIN, VAL_MIN = 8, 168, 100, 90
# Generous box around the enlarged widget, in pixels at 1920x1080. Deliberately
# not a profile fraction: the profile's `minimap` ROI is still the OLD size and
# must be re-measured with `probe` before anything is ingested.
ROI = (0, 0, 530, 515)


def red_mask(bgr, sat_min=SAT_MIN):
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    return (((h < HUE_LO) | (h > HUE_HI)) & (s > sat_min) & (v > VAL_MIN))


def static_map(frames):
    """The widget with every icon removed, as a per-pixel median.

    Icons move, map furniture does not. One round is almost entirely active
    play, so this takes the sampled frames directly rather than reading spans
    out of the store -- the lossless capture is not ingested.
    """
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def floor_mask(med, dilate=9):
    """The opaque walkable slab. Everything else is see-through and churns.

    This is the fix `minimap_position.py` already carried and the one thing that
    every failed content-based approach was missing: the widget is
    semi-transparent over the void, so a red mask taken over the whole ROI
    measures the wall the player happens to be facing. Skipping it here first
    time round reproduced exactly that -- median "icon" area 956 px and diameter
    59, which is scenery, not an icon.

    `dilate` was 9 at the old widget size, to admit icons standing at a floor
    edge. It is exposed because the widget is now ~1.5x larger and this radius
    has not been re-measured against it.

    Two changes from the version in `minimap_position.py`, both measured on the
    enlarged widget rather than assumed:

    * **`sat < 20`, not `sat < 60`.** The map slab is pure grey (S=0, V=118);
      the scenery hazing through the transparent part of the widget sits at
      S 36-58, V 97-140. At `sat < 60` the mask took 83% of the ROI -- it was
      admitting the background wholesale. Value cannot do this job here: the
      background is BRIGHTER than the floor, not darker, so the old `val > 110`
      passes it.
    * **the largest connected component only.** That drops the HUD in the
      top-right corner and the scenery specks at the edges by derivation rather
      than by a hand-drawn box, which is the same argument that made the screen
      detector locate the combat report from its own structure.
    """
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 1] < 20) & (hsv[:, :, 2] > 100)).astype(np.uint8)
    # Join the floorplan's own thin corridors before taking a component, or the
    # slab arrives as several pieces and the largest is one wing of the map.
    j = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(j, 8)
    if n <= 1:
        return np.zeros(m.shape, bool)
    big = (lbl == 1 + int(np.argmax(st[1:, 4])))
    return cv2.dilate(big.astype(np.uint8), np.ones((dilate, dilate), np.uint8)) > 0


def blobs(crop, floor=None, min_area=25, sat_min=SAT_MIN):
    """Red blobs with their seal statistics.

    The hole test floodfills from a padded border, so an enclosed interior is
    whatever the flood cannot reach. No closing is applied: the question is
    whether the ring seals ON ITS OWN, and a closing radius large enough to seal
    a broken ring is the same radius that merges adjacent icons -- which is the
    trap every earlier attempt fell into.
    """
    m = red_mask(crop, sat_min)
    if floor is not None:
        m = m & floor
    m = m.astype(np.uint8)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, 8)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area < min_area:
            continue
        sub = (lbl[y:y + h, x:x + w] == i).astype(np.uint8)
        pad = cv2.copyMakeBorder(sub, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
        ff = pad.copy()
        cv2.floodFill(ff, np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8),
                      (0, 0), 1)
        hole = ((ff == 0) & (pad == 0))
        n_hole = int(hole.sum())
        inner = grey[y:y + h, x:x + w][hole[1:-1, 1:-1]] if n_hole else np.array([])
        out.append({
            "xy": (int(cen[i][0]), int(cen[i][1])), "area": int(area),
            "w": int(w), "h": int(h),
            "sealed": n_hole > 0, "hole": n_hole,
            "hole_frac": n_hole / (area + n_hole),
            "inner_v": float(inner.mean()) if n_hole else 0.0,
        })
    return out


def _iconish(b):
    """A ring around a portrait, not a nick in a solid mark.

    Bounds come from the one icon verified by hand on the enlarged widget rather
    than from the old size's numbers. Measured on the same frame, side by side:

        enemy icon   27x21, area 119, SEALED, hole 261, hole_frac 0.69
        red X mark   13x13, area  74, open,   hole   0, hole_frac 0.00

    `hole_frac` is what separates them and it separates them completely, which
    is the whole result -- at the old size this was a soft 0.76-against-0.92
    overlap. Diameter is bounded above as well as below, because two touching
    icons merge into one larger blob and that has to read as a merge, not as an
    icon.
    """
    return b["sealed"] and b["hole_frac"] >= 0.35 and 18 <= max(b["w"], b["h"]) <= 34


def summarise(label, per_frame):
    allb = [b for bs in per_frame for b in bs]
    if not allb:
        print(f"  {label:14s} no blobs")
        return
    sealed = [b for b in allb if b["sealed"]]
    iconish = [b for b in sealed if _iconish(b)]
    fr_any = sum(1 for bs in per_frame if bs)
    fr_icon = sum(1 for bs in per_frame if any(_iconish(b) for b in bs))
    print(f"  {label:14s} blobs {len(allb):5d}  sealed {len(sealed):5d} "
          f"({len(sealed)/len(allb)*100:5.1f}%)  icon-shaped {len(iconish):4d}")
    print(f"  {'':14s} frames with any red {fr_any:3d}/{len(per_frame)}, "
          f"with an icon-shaped seal {fr_icon:3d}/{len(per_frame)} "
          f"({fr_icon/max(len(per_frame),1)*100:.1f}%)")
    # Calibrate from the data rather than from the old size's numbers: print
    # what the blobs actually are before deciding what an icon looks like.
    for name, pool in (("all", allb), ("sealed", sealed), ("icon-shaped", iconish)):
        if not pool:
            continue
        a = np.array([b["area"] for b in pool], float)
        d = np.array([max(b["w"], b["h"]) for b in pool], float)
        hl = np.array([b["hole"] for b in pool], float)
        print(f"  {'':14s} {name:11s} area {np.percentile(a,25):5.0f}/"
              f"{np.median(a):5.0f}/{np.percentile(a,75):6.0f}  "
              f"diam {np.percentile(d,25):4.0f}/{np.median(d):4.0f}/"
              f"{np.percentile(d,75):5.0f}  hole {np.median(hl):5.0f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=120)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"cannot open {args.video}")
        return 1
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    x0, y0, x1, y1 = ROI
    crops_lo, crops_sub = [], []
    for i in np.linspace(0, max(tot - 1, 0), args.n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        crops_lo.append(fr[y0:y1, x0:x1])
        crops_sub.append(to_420(fr)[y0:y1, x0:x1])
    cap.release()
    if not crops_lo:
        print("no frames read")
        return 1

    floor = floor_mask(static_map(crops_lo))
    print(f"{Path(args.video).name}: {len(crops_lo)} frames, ROI {ROI}")
    print(f"walkable floor {floor.mean()*100:.1f}% of the ROI")
    print("\nDoes the enemy ring seal on its own?  (no closing applied)")
    for sm in (80, 90, 100, 110, 120):
        print(f"\n  sat > {sm}")
        summarise("lossless", [blobs(c, floor, sat_min=sm) for c in crops_lo])
        summarise("4:2:0", [blobs(c, floor, sat_min=sm) for c in crops_sub])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
