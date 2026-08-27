"""The static map, classified: floor, holes, borders, box edges, plant zones.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_geometry.py <session> [--sheet out.png]

Grant's proposal, and it earns its place twice over.

**What it is.** The minimap widget is mostly unchanging: the floor plan, the
holes in it, the white lines that bound them and the yellow plantable zones are
the same in every frame of a match. A per-pixel median over sampled frames
already removes every icon -- that is how `minimap_icons.static_map` works --
so the geometry is sitting there waiting to be read once per map and reused for
the whole session.

**Why it matters more than it looks.** Two things need it that are not about
geometry at all:

1. **It is what makes a colour-free detector viable.** Everything that matters
   on the widget -- players, abilities, viewcones -- is by definition what
   DIFFERS from the static map, and differencing needs no colour assumption. It
   therefore sees the ability glyphs that are pure black and white, which the
   red mask cannot see at all and never could. Measured on `c62c2b06bcfb`:
   107 dynamic blobs against 7 from the red mask over the same six frames,
   including a B/W circular ability icon at Mid Vent.

   But most of those 107 are artefacts hugging the WHITE BORDERS, because a
   1 px line between two very different levels moves a little frame to frame
   and lights up under any difference threshold. Borders are static and white,
   so this map locates them exactly -- which removes the dominant artefact
   class BY CONSTRUCTION rather than by another threshold. The detector needs
   this map and this map is what fixes the detector.

2. **It is the occlusion grid.** `minimap_position.py` already noted the static
   map falls out as a per-pixel median and is also what the visibility work
   needs. Nothing here is speculative about that -- the holes and the borders
   ARE the walls.

Grant's palette, which is what this reads
-----------------------------------------
He named these off footage, and had never noticed the elevated shade before:

* standard grey -- the floor;
* **lighter grey -- a VIEWCONE**, which is what your team can currently see.
  Dynamic, so it is not in the static map at all, and that is a feature: it
  means differencing isolates it. Measured as a per-frame brightness lift of
  p90 +51 on Split against a p50 of 0;
* a **different lighter shade** for elevated areas -- Split heaven over A and B;
* **white or off-white for borders and box boundaries**;
* **yellow for plantable regions** on the sites.

Border versus box edge, which is Grant's own test
-------------------------------------------------
Both are white lines, and telling them apart is: **does the grey cut off?** A
map BORDER has floor on one side and void on the other. A BOX EDGE -- geometry
inside the playable area -- has floor on both sides. That is a local question
about each white pixel's neighbourhood, and it is the distinction that matters
downstream, because a border is a wall and a box edge is something you can
stand on or behind.

Measured, both maps
-------------------
    class        Split    Ascent
    floor        39.9%     32.4%
    hole          9.2%      6.0%      17.5% / 14.5% of the footprint
    border        1.0%      1.3%
    box edge      2.1%      1.7%
    plantable     0.09%     0.10%

The holes are real -- Grant: the map simply has them. An earlier version of
this file put them at 33.9% and 33.3%, from taking the floor's CONVEX HULL as
the footprint; on a deeply concave floor plan the gaps between the map's arms
fall inside the hull and count as interior. I took the two maps agreeing to
within half a point as confirmation, when the agreement was an artefact of both
being about equally convex. A spurious agreement is not a check.

A dark low-saturation band is the VOID, not elevated ground. Split's static map
is 73% low-saturation against Ascent's 29%, with 55% of it at V 60-90 where
Ascent sits at V115. I read that as elevated walkable area being wrongly
excluded; overlaying the mask showed it is the transparent region OUTSIDE the
map, and Split's void is darker only because of what renders behind it.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
from minimap_icons import floor_mask, static_map                  # noqa: E402

STORE = Path.home() / "reticle-store"

# Class ids, in the order they are resolved. Later ones do not overwrite
# earlier ones, so the order is the priority.
VOID, FLOOR, HOLE, BORDER, BOXEDGE, PLANT = 0, 1, 2, 3, 4, 5
NAMES = {VOID: "void", FLOOR: "floor", HOLE: "hole", BORDER: "border",
         BOXEDGE: "box edge", PLANT: "plantable"}
COLOURS = {VOID: (40, 40, 40), FLOOR: (90, 90, 90), HOLE: (20, 20, 110),
           BORDER: (255, 255, 255), BOXEDGE: (60, 200, 255), PLANT: (40, 220, 220)}

# White lines. Deliberately a level test rather than a top-hat: this runs on the
# STATIC map, where the lines are the brightest thing present and nothing is
# moving to confuse a level. That is the one place in this project where an
# absolute level is safe, and it is safe precisely because the median removed
# everything transient.
WHITE_V, WHITE_S = 170, 60
# Yellow plant zones. The first version -- hue 20-35, sat > 60 -- was fitted to
# the SATURATED CORE of the paint and caught 3% of the zone; the other 97% fell
# through to VOID, so the two bomb sites were 93% unsearchable. That is the
# worst place on the map to be blind: 19 of 254 hand-marked icons stand inside
# one, and a site is where utility gets thrown. The zone is opaque map, not
# transparency -- its temporal SD is 17.9 against the lit slab's 16.6 and the
# exterior void's 42.5 -- it simply fails `floor_mask`'s `sat < 20` because it
# is tinted. Widened to the hue alone, with a size floor so stray yellow specks
# (a dropped spike, the plant timer) cannot become a site.
PLANT_H = (15, 40)
PLANT_S, PLANT_V = 25, 90
PLANT_MIN_AREA = 500
# How far to look either side of a white pixel when asking whether the grey cuts
# off. Lines are 1-2 px, so this has to clear the line itself and land on what
# is beyond it.
PROBE = 4


def classify(med):
    """Label every pixel of a static minimap into the geometry classes."""
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    out = np.full(med.shape[:2], VOID, np.uint8)

    floor = floor_mask(med)
    out[floor] = FLOOR

    # The footprint: what the floor ENCLOSES, found by flooding the exterior
    # inward from the frame edge. A hole is then non-floor the flood cannot
    # reach -- the same topological argument `minimap_icons.blobs` uses for the
    # ring seal, and for the same reason: it needs no shape assumption.
    #
    # The first version took the floor's CONVEX HULL as the footprint and called
    # everything inside it a hole. That is wrong on a floor plan, which is
    # deeply concave: the gaps BETWEEN the map's arms fell inside the hull and
    # were counted as interior holes. It reported 33.9% and 33.3% on Split and
    # Ascent, and I read two maps agreeing to within half a point as
    # confirmation when it was really two maps being equally convex-ish.
    fl8 = floor.astype(np.uint8)
    ff = fl8.copy()
    mask = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
    cv2.floodFill(ff, mask, (0, 0), 1)          # 1 marks everything reachable
    exterior = (ff == 1) & ~floor
    out[~floor & ~exterior] = HOLE

    white = (v >= WHITE_V) & (s < WHITE_S)
    plant = (h >= PLANT_H[0]) & (h <= PLANT_H[1]) & (s > PLANT_S) & (v > PLANT_V)
    # Close and keep only the large components, then fill what they enclose:
    # Grant, on what is inside a zone -- the site letters are a very dark grey,
    # almost black, always against the yellow. They are opaque map like the
    # paint around them, and they are holes in the hue mask, so filling the
    # zone is what keeps A, B (and C, on a three-site map) searchable.
    #
    # A component must also TOUCH THE FLOOR, which is not a formality: widening
    # the hue caught the agent HUD in the top-right corner as a third "site",
    # 34x68 over the churning void at a temporal SD of 42.5, and it alone
    # produced 102 of the 116 colour-free blobs the three zones contributed.
    # The two real sites gave 9 and 5, at SD 13.8 and 17.8. Same corner and the
    # same fix as `minimap_icons.floor_mask`, which drops that HUD by taking the
    # largest component: a bomb site is part of the map, so it adjoins the map.
    near_floor = cv2.dilate(fl8, np.ones((5, 5), np.uint8)) > 0
    pz = cv2.morphologyEx(plant.astype(np.uint8), cv2.MORPH_CLOSE,
                          np.ones((15, 15), np.uint8))
    nz, zl, zst, _ = cv2.connectedComponentsWithStats(pz, 8)
    plant = np.zeros_like(plant)
    for i in range(1, nz):
        comp = (zl == i)
        if zst[i, 4] < PLANT_MIN_AREA or not (comp & near_floor).any():
            continue
        c8 = comp.astype(np.uint8)
        ff = c8.copy()
        m2 = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
        cv2.floodFill(ff, m2, (0, 0), 1)
        plant |= comp | (ff == 0)                   # the paint, plus its letter

    # Grant's test -- does the grey cut off? -- asked against the EXTERIOR the
    # flood fill already found, rather than by probing for floor on both sides.
    #
    # The probe version put 2.98% of the widget in "box edge" and 0.13% in
    # "border", classifying the map's own outer boundary as interior geometry.
    # On a floor plan this dense, a 4 px probe perpendicular to one wall often
    # lands on a different arm of the map, so "floor on both sides" was true
    # nearly everywhere. The distinction that actually matters is not whether
    # floor is nearby, it is whether the VOID is: a border has the outside on
    # one side of it, and a box edge has playable space on both.
    # Dilated by 13, not 5, and the reason is a trap worth naming:
    # `minimap_icons.floor_mask` DILATES its result by 9, deliberately, so that
    # an icon standing at a floor edge is still inside the mask. That dilation
    # swallows the white border lines and about 4 px of void beyond them, so
    # the exterior found by flooding starts well outside the border it is
    # supposed to be adjacent to. A 5 px probe never reached back across it and
    # the classification did not move at all -- two runs identical to two
    # decimal places, which is what gave it away.
    ext = cv2.dilate(exterior.astype(np.uint8), np.ones((13, 13), np.uint8)) > 0
    both = ~ext
    out[white & both] = BOXEDGE
    out[white & ~both] = BORDER
    out[plant] = PLANT
    return out


def summarise(lab, name=""):
    tot = lab.size
    print(f"{name}")
    for k in (VOID, FLOOR, HOLE, BORDER, BOXEDGE, PLANT):
        n = int((lab == k).sum())
        print(f"    {NAMES[k]:>10s}  {n/tot*100:6.2f}%")
    inside = (lab != VOID).sum()
    if inside:
        print(f"    holes as a share of the footprint: "
              f"{(lab == HOLE).sum()/inside*100:.1f}%")


def render(med, lab):
    vis = np.zeros_like(med)
    for k, c in COLOURS.items():
        vis[lab == k] = c
    return np.hstack([med, vis])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=180, help="frames to median over")
    ap.add_argument("--sheet")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)

    cap = cv2.VideoCapture(src["path"])
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in np.linspace(tot * 0.15, tot * 0.85, args.n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            frames.append(fr[y0:y1, x0:x1])
    cap.release()
    if not frames:
        print("no frames decoded")
        return 1
    med = static_map(frames)
    lab = classify(med)
    summarise(lab, f"{args.session}  ({', '.join(man.get('tags', []))})")

    out = STORE / "geometry" / f"{args.session}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, labels=lab, static=med, roi=np.array([x0, y0, x1, y1]))
    print(f"  wrote {out}")
    if args.sheet:
        cv2.imwrite(args.sheet, render(med, lab))
        print(f"  wrote {args.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
