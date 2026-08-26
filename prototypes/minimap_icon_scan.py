"""Scan a capture for enemy minimap icons and contact-sheet what was found.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_icon_scan.py <video> [--n 600] [--sheet out.png]

The shape being matched, from Grant: **a red-circled player icon with a red
triangle showing their facing.** Both halves matter and they fail differently.

* The **ring** is what separates an enemy from a red X death marker -- measured
  side by side on the enlarged widget, the icon seals with hole_frac 0.69 and
  the X does not seal at all. Colour cannot do this: both are hue 177.
* The **triangle** is what separates an enemy icon from every other red round
  thing on the widget -- Reyna blinds, Cypher cameras, warning pings. That is
  the correction recorded in `minimap_position.py`: earlier work tested "is this
  a ring" and concluded there was no signal, when the real feature was ring
  PLUS triangle and the comparison had never measured it.

The triangle merges with the ring into one connected component, so it is not a
second blob to find -- it is a solid lobe attached outside an otherwise thin
annulus. This measures it as the mass sitting outside the ring's own radius,
which needs no orientation search and gives the facing for free as the angle of
that mass.

Verification here is a CONTACT SHEET, not a number. The project's own tool for
"which of these are actually X" is one tall image, one row per candidate,
because twenty rows fit in a glance and a rate computed against no ground truth
is uninterpretable -- which is exactly how the single-round result had to be
reported.
"""
import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from minimap_icons import ROI, floor_mask, red_mask, static_map    # noqa: E402


def icon_features(sub, cx, cy):
    """Ring/triangle structure of one red blob.

    `sub` is the blob's own mask, `cx, cy` its centroid within that patch.
    Returns the enclosed-hole fraction, the share of mass lying outside the
    ring, and the direction of that outside mass.
    """
    pad = cv2.copyMakeBorder(sub, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy()
    cv2.floodFill(ff, np.zeros((pad.shape[0] + 2, pad.shape[1] + 2), np.uint8),
                  (0, 0), 1)
    hole = ((ff == 0) & (pad == 0))[1:-1, 1:-1]
    n_hole = int(hole.sum())
    area = int(sub.sum())
    if not n_hole:
        return {"hole": 0, "hole_frac": 0.0, "lobe": 0.0, "facing": None}
    # The ring's radius is set by the portrait it encloses, so take it from the
    # HOLE rather than from the blob -- the triangle inflates the blob's own
    # extent in one direction and would bias any radius measured off it.
    hy, hx = np.nonzero(hole)
    r_hole = np.hypot(hx - cx, hy - cy).max()
    ys, xs = np.nonzero(sub)
    d = np.hypot(xs - cx, ys - cy)
    # 1.35x the portrait radius clears the ring band itself; anything past that
    # is the triangle.
    out = d > r_hole * 1.35
    facing = None
    if out.any():
        facing = float(np.degrees(np.arctan2((ys[out] - cy).mean(),
                                             (xs[out] - cx).mean())))
    return {"hole": n_hole, "hole_frac": n_hole / (area + n_hole),
            "lobe": float(out.mean()), "facing": facing}


def candidates(crop, floor, sat_min=100, min_area=40):
    m = (red_mask(crop, sat_min) & floor).astype(np.uint8)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if area < min_area or not (16 <= max(w, h) <= 40):
            continue
        sub = (lbl[y:y + h, x:x + w] == i).astype(np.uint8)
        f = icon_features(sub, cen[i][0] - x, cen[i][1] - y)
        if f["hole_frac"] < 0.30:
            continue
        out.append({"box": (int(x), int(y), int(w), int(h)),
                    "xy": (float(cen[i][0]), float(cen[i][1])),
                    "area": int(area), **f})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--n", type=int, default=600)
    ap.add_argument("--sheet")
    ap.add_argument("--max-rows", type=int, default=40)
    args = ap.parse_args()

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"cannot open {args.video}")
        return 1
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    x0, y0, x1, y1 = ROI

    # Static map from a coarse pass first: icons move, furniture does not.
    med_src = []
    for i in np.linspace(0, tot - 1, 150).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            med_src.append(fr[y0:y1, x0:x1])
    floor = floor_mask(static_map(med_src))
    print(f"{Path(args.video).name}: {tot} frames, {tot/fps/60:.1f} min")
    print(f"walkable floor {floor.mean()*100:.1f}% of the ROI")

    hits, n_frames = [], 0
    for i in np.linspace(0, tot - 1, args.n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if not ok:
            continue
        n_frames += 1
        crop = fr[y0:y1, x0:x1]
        for c in candidates(crop, floor):
            c["t_ms"] = i / fps * 1000.0
            c["crop"] = crop
            hits.append(c)
    cap.release()

    fr_with = len({h["t_ms"] for h in hits})
    print(f"\n{len(hits)} candidates in {fr_with}/{n_frames} frames "
          f"({fr_with/max(n_frames,1)*100:.1f}%)")
    if hits:
        for k in ("area", "hole", "hole_frac", "lobe"):
            v = np.array([h[k] for h in hits], float)
            print(f"  {k:10s} p25 {np.percentile(v,25):7.2f}  med "
                  f"{np.median(v):7.2f}  p75 {np.percentile(v,75):7.2f}")
        withlobe = sum(1 for h in hits if h["lobe"] > 0.05)
        print(f"  carrying a triangle lobe (>5% of mass): {withlobe}/{len(hits)}")

    if args.sheet and hits:
        rows = sorted(hits, key=lambda h: -h["hole_frac"])[:args.max_rows]
        tiles = []
        for h in rows:
            x, y, w, hh = h["box"]
            p = 10
            sub = h["crop"][max(0, y-p):y+hh+p, max(0, x-p):x+w+p]
            t = cv2.resize(sub, (128, 128), interpolation=cv2.INTER_NEAREST)
            cv2.putText(t, f"{h['hole_frac']:.2f}/{h['lobe']:.2f}", (2, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1)
            cv2.putText(t, f"{int(h['t_ms']//60000)}:{int(h['t_ms']//1000%60):02d}",
                        (2, 124), cv2.FONT_HERSHEY_SIMPLEX, 0.34, (255, 255, 255), 1)
            tiles.append(t)
        per = 8
        grid = [np.hstack(tiles[i:i+per] + [np.zeros((128, 128, 3), np.uint8)]
                          * (per - len(tiles[i:i+per])))
                for i in range(0, len(tiles), per)]
        cv2.imwrite(args.sheet, np.vstack(grid))
        print(f"wrote {args.sheet} ({len(tiles)} tiles, label is hole_frac/lobe)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
