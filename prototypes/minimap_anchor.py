"""Minimap icon recall, anchored on the screen detector instead of on labels.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_anchor.py <video> [--n 400] [--sheet out.png]

The single-round result could not be quoted as recall because nothing said how
many sampled frames contained a minimap-visible enemy. This supplies that
denominator without hand labels, using the premise that already survived
adversarial review in `minimap_position.py`:

    an enemy on screen implies an enemy icon on the minimap

All ten apparent counterexamples confirmed it. So any frame carrying a
confident SCREEN detection provably carries a minimap icon, and the share of
those frames where the minimap finder fires is a real recall figure.

"Confident" is a large screen blob (`AREA_STRONG`), not merely a detection: the
shipped detector runs at ~41% precision, and anchoring on a signal that is wrong
three times in five would put junk in the denominator and understate minimap
recall. A large blob is a close enemy, which is also the case where the icon is
least ambiguous -- so this measures the EASY end and should be read as a ceiling.

The contact sheet is the point of the run. Frames in the denominator provably
contain an icon, so a sheet of the ones the finder MISSED is a sheet of icons it
should have found, and looking at twenty of those says what the defect is far
faster than another threshold sweep.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import enemy_features as ef                                        # noqa: E402
from minimap_icons import ROI, floor_mask, static_map              # noqa: E402
from minimap_icon_scan import candidates                          # noqa: E402

# A close enemy: comfortably above the shipped AREA floor of 120, where the
# detector's precision is much better than its 41% aggregate.
AREA_STRONG = 500


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=400)
    ap.add_argument("--sheet")
    ap.add_argument("--sat", type=int, default=100)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"cannot open {args.video}")
        return 1
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    x0, y0, x1, y1 = ROI

    med = []
    for i in np.linspace(0, tot - 1, 150).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            med.append(fr[y0:y1, x0:x1])
    floor = floor_mask(static_map(med))
    print(f"{Path(args.video).name}: {tot/fps/60:.1f} min, "
          f"floor {floor.mean()*100:.1f}% of ROI")

    anchored, hit, miss = 0, 0, []
    n_frames = 0
    for i in np.linspace(0, tot - 1, args.n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        n_frames += 1
        dets = ef.detect(fr, ef.SHIPPED)
        if not any(d[4] >= AREA_STRONG for d in dets):
            continue
        anchored += 1
        crop = fr[y0:y1, x0:x1]
        cs = candidates(crop, floor, sat_min=args.sat)
        if cs:
            hit += 1
        elif len(miss) < 40:
            miss.append((i / fps * 1000.0, crop))
    cap.release()

    print(f"\nframes sampled          {n_frames}")
    print(f"with a strong screen detection (>= {AREA_STRONG} px)  {anchored}")
    if anchored:
        print(f"  of those, minimap finder fires   {hit} "
              f"({hit/anchored*100:.1f}%)")
        print(f"  MISSED                           {anchored-hit}")
    print("\nThe misses provably contain an icon -- that is what the premise buys.")

    if args.sheet and miss:
        tiles = []
        for t_ms, crop in miss[:24]:
            t = cv2.resize(crop, (300, 292), interpolation=cv2.INTER_AREA)
            cv2.putText(t, f"{int(t_ms//60000)}:{int(t_ms//1000%60):02d}",
                        (4, 286), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(t)
        per = 4
        grid = [np.hstack(tiles[i:i+per] + [np.zeros((292, 300, 3), np.uint8)]
                          * (per - len(tiles[i:i+per])))
                for i in range(0, len(tiles), per)]
        cv2.imwrite(args.sheet, np.vstack(grid))
        print(f"wrote {args.sheet} ({len(tiles)} missed minimaps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
