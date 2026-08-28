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

   Most of those 107 hug the WHITE BORDERS, and the obvious reading of that --
   that the line itself flickers -- is WRONG. Measured 2026-08-26: a white line
   is the quietest thing on the widget, temporal SD 7.4 against the lit slab's
   17.1. What moves is the see-through void on the other side of it. The lesson
   survives, with the cause corrected: this map is what the detector needs, but
   for locating the OPAQUE SLAB and the bomb sites, not for guarding lines.
   See `minimap_dynamic.searchable`.

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
    class        Split    Ascent    Lotus
    floor        39.1%     31.9%     35.6%
    hole          8.8%      6.0%      5.1%     15.1% / 13.9% / 11.3% of footprint
    border        0.9%      1.2%      0.8%
    box edge      2.1%      1.7%      1.7%
    plantable     2.2%      2.6%      2.2%

(`plantable` read 0.09% / 0.10% before 2026-08-26, when the hue test was fitted
to the saturated core of the paint and found 3% of each zone.)

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
import hashlib
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
# is tinted.
#
# Widened to hue 15-40 with a size floor so stray yellow specks (a dropped
# spike, the plant timer) cannot become a site -- but the FIRST widening went
# too far the other way, `sat > 25, val > 90`, and Split grew a third "site":
# a 102x257 blob of brown void at the map's left edge, 10921 px, which reached
# the floor and so passed the adjacency test too. Caught only by rebuilding
# Split's geometry, which is the argument for rebuilding all of them whenever
# this file changes.
#
# The real paint has a tight signature across every zone measured -- hue 32-33,
# sat 43-58, val 153-171 on five zones over three maps -- against that blob's
# hue 19, sat 28, val 90. Swept, with the correct answer being Split 2, Lotus 3
# (A, B and C), Ascent 2:
#
#     sat>25 val>90    Split 3 <- the blob      Lotus 3      Ascent 2
#     sat>35 val>110   Split 2                  Lotus 3      Ascent 2
#     sat>40 val>120   Split 2                  Lotus 3      Ascent 2
#     sat>45 val>130   Split 2                  Lotus 3, C shrinks 1375->602
#     sat>50 val>140   Split 2                  Lotus 2 <- C lost
#
# 40/120 sits in the middle of the plateau rather than on either edge, and the
# zones it finds are within 10% of the loosest setting's.
PLANT_H = (15, 40)
PLANT_S, PLANT_V = 40, 120
PLANT_MIN_AREA = 500
# How far to look either side of a white pixel when asking whether the grey cuts
# off. Lines are 1-2 px, so this has to clear the line itself and land on what
# is beyond it.
PROBE = 4
# Bridges the same kind of single-frame dropout `minimap_icons.floor_mask`
# already closes for the floor slab, applied here to the white-line mask
# before border/box-edge classification -- see the note at that call site.
LINE_CLOSE = 5
LINE_MIN_AREA = 20


def two_state_gray(gray_stack, trim=0.05):
    """Per pixel, the two colours it actually rests at -- not one median.

    Grant's model, checked against real footage before building this: **a
    geometry pixel has exactly two legitimate colours, unlit and lit by a
    viewcone** -- everything else at that pixel is something real drawn over
    it. Measured on `a06f04a0059f` at genuine interior border/box-edge points
    (at least 25px clear of the widget's own outer rim, which is a different,
    noisier thing -- it borders void by definition): 81-91% of 400 samples at
    one value, most of the rest at a single adjacent second value, and a small
    scatter that is almost certainly real events (a ping, an X mark, a player)
    passing over that exact pixel across a 44-minute match, not a third
    lighting state. The single-median `static` this module already builds
    collapses both legitimate states into one reference, so a pixel simply
    switching from unlit to lit reads as "dynamic" -- which is the mechanism
    behind the border/box-edge false positives `scan_ability_clip.py` kept
    finding: the detector was never wrong that the pixel changed, it was
    wrong that a known, legitimate change means something is there.

    Per pixel: sort its value across sampled frames, trim the extreme `trim`
    fraction off each end (a real object passing over reads as an outlier
    excursion, not a resting state), then split the remainder at its single
    biggest gap and return each side's mean. A pixel with no real two-state
    structure -- never lit all match, or always lit -- still gets a split,
    typically a small one, so `lo` and `hi` end up close together and behave
    like today's single reference. Fully vectorised: this is a one-time,
    per-session build step, not something running per detected frame.
    """
    K = gray_stack.shape[0]
    s = np.sort(gray_stack.astype(np.int16), axis=0)
    lo_i, hi_i = int(K * trim), max(int(K * (1 - trim)), int(K * trim) + 2)
    s = s[lo_i:hi_i]
    K2 = s.shape[0]
    gaps = np.diff(s, axis=0)
    split = np.argmax(gaps, axis=0)                      # (H,W): last LOW-group index
    cumsum = np.cumsum(s, axis=0).astype(np.float32)
    total = cumsum[-1]
    low_sum = np.take_along_axis(cumsum, split[None, :, :], axis=0)[0]
    low_count = (split + 1).astype(np.float32)
    lo = low_sum / low_count
    high_count = K2 - low_count
    hi = np.where(high_count > 0, (total - low_sum) / np.maximum(high_count, 1), lo)
    return lo.astype(np.float32), hi.astype(np.float32)


def source_stamp():
    """A hash of THIS FILE, stamped into every npz it writes.

    A cached derived artefact that does not say what made it hides a regression
    until someone happens to run the input that exposes it. Measured cost of not
    having this, 2026-08-26: widening the plant test grew a third "bomb site" on
    Split -- a 10921 px blob of brown void -- and nothing noticed, because
    Split's npz was months stale and the two maps anyone was looking at were
    fine. It surfaced only because the file got rebuilt for unrelated reasons.

    Hashing the whole module is deliberately blunt: it will report stale after a
    comment change, which costs one rebuild, and it can never report fresh after
    a threshold change, which is the failure that matters.
    """
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


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

    # `white` is used RAW above nowhere else, but border/box-edge must not be:
    # Grant caught "small squares scattered all over the map" in the rendered
    # sheet, 2026-08-27, and it is not noise filtered by a size floor alone --
    # a real wall is exactly as prone to fragmenting as an artefact is, because
    # neither the border/box-edge split above nor this raw threshold has ever
    # closed the line first the way `minimap_icons.floor_mask` closes its own
    # slab. A 1-2 px line has zero redundancy: one pixel dipping under
    # WHITE_V for one frame's contribution to the median breaks it in two, real
    # wall or not. Closing first, THEN filtering size, fixes that: a
    # genuinely continuous wall reassembles across the small gap and survives
    # any area floor; an isolated artefact -- measured here as a small
    # permanent floor decal near (256,82) whose antialiased rim crosses
    # WHITE_V at only a few points around its circumference -- does not grow
    # by closing and stays small. Checked before picking numbers: with a 5x5
    # close, 3 of 4 previously-fragmented corner pieces merge into the map's
    # single connected wall network (3512 px), and every remaining small
    # (<=20 px) piece is either that decal or sits at x>=434 -- the ally-roster
    # HUD-bleed zone this ROI already clips into, not the floor plan at all.
    white_closed = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_CLOSE,
                                    np.ones((LINE_CLOSE, LINE_CLOSE), np.uint8)) > 0
    nl, lbl, st, _ = cv2.connectedComponentsWithStats(white_closed.astype(np.uint8), 8)
    line = np.zeros_like(white_closed)
    for i in range(1, nl):
        if st[i, 4] > LINE_MIN_AREA:
            line |= (lbl == i)

    out[line & both] = BOXEDGE
    out[line & ~both] = BORDER
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


def sample_frames(session, n, roi):
    """`n` BGR crops evenly spread over the middle 70% of a session's video.

    Shared between the geometry classify() pass and the two-state reference
    build -- both want "ordinary play", not the pre-match lobby or the
    post-match screen at either end.
    """
    man = json.loads((STORE / "manifests" / f"{session}.json").read_text())
    src = man["source"]
    x0, y0, x1, y1 = roi
    cap = cv2.VideoCapture(src["path"])
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    frames = []
    for i in np.linspace(tot * 0.15, tot * 0.85, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            frames.append(fr[y0:y1, x0:x1])
    cap.release()
    return frames, man


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=180, help="frames to median over")
    ap.add_argument("--sheet")
    ap.add_argument("--two-state-from",
                    help="build the lo/hi lighting reference from a DIFFERENT, "
                         "longer session on the same map/profile instead of this "
                         "one's own frames. Use this for a short controlled clip: "
                         "the two-state split assumes real content is a small "
                         "minority of the sampling window, which a demo clip "
                         "built around one deliberate event violates by design "
                         "-- a 2.4s ability in a 37s clip is ~9%% of the window, "
                         "not negligible. The lighting model is a property of "
                         "the MAP, not the match, so any full match on the same "
                         "map/profile is a valid, uncontaminated source.")
    ap.add_argument("--two-state-n", type=int, default=400,
                    help="frames to sample from the two-state reference source")
    ap.add_argument("--geometry-from",
                    help="borrow the ENTIRE geometry -- floor plan, walls, bomb "
                         "sites, and the lighting reference -- from a different, "
                         "already-built session on the same map/profile, rather "
                         "than deriving any of it from this session's own frames. "
                         "Supersedes --two-state-from. Use this for a short "
                         "controlled clip: the floor plan and bomb sites are a "
                         "property of the MAP, not the recording, and deriving "
                         "them from a clip built around one deliberate event "
                         "risks the same contamination as --two-state-from, "
                         "just hitting classify() instead of the lighting "
                         "reference. Measured 2026-08-27: Brimstone's orange "
                         "ultimate overlay bled into a few of the 180 sampled "
                         "frames and the plant-zone hue test misfired, labelling "
                         "a strip of VOID a 'bomb site' right next to it.")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    roi = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    x0, y0, x1, y1 = roi

    if args.geometry_from:
        ref_man = json.loads((STORE / "manifests" / f"{args.geometry_from}.json").read_text())
        if ref_man["source_profile"] != man["source_profile"]:
            print(f"  WARNING: --geometry-from {args.geometry_from} uses profile "
                  f"{ref_man['source_profile']!r}, this session uses "
                  f"{man['source_profile']!r} -- the ROI will not line up, refusing")
            return 1
        ref_path = STORE / "geometry" / f"{args.geometry_from}.npz"
        if not ref_path.is_file():
            print(f"no geometry for {args.geometry_from} -- build it first")
            return 1
        z = np.load(ref_path)
        if "lo_gray" not in z.files:
            print(f"{args.geometry_from}'s geometry predates the two-state "
                  f"reference -- rebuild it first")
            return 1
        out = STORE / "geometry" / f"{args.session}.npz"
        out.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(out, labels=z["labels"], static=z["static"],
                            roi=np.array([x0, y0, x1, y1]),
                            lo_gray=z["lo_gray"], hi_gray=z["hi_gray"],
                            built_by=z["built_by"])
        summarise(z["labels"], f"{args.session}  (borrowed wholesale from "
                                f"{args.geometry_from}, {', '.join(man.get('tags', []))})")
        print(f"  wrote {out}  (entirely {args.geometry_from}'s geometry -- "
              f"nothing derived from this session's own frames)")
        if args.sheet:
            cv2.imwrite(args.sheet, render(z["static"], z["labels"]))
            print(f"  wrote {args.sheet}")
        return 0

    frames, _ = sample_frames(args.session, args.n, roi)
    if not frames:
        print("no frames decoded")
        return 1
    med = static_map(frames)
    lab = classify(med)
    summarise(lab, f"{args.session}  ({', '.join(man.get('tags', []))})")

    if args.two_state_from:
        ref_man = json.loads((STORE / "manifests" / f"{args.two_state_from}.json").read_text())
        if ref_man["source_profile"] != man["source_profile"]:
            print(f"  WARNING: --two-state-from {args.two_state_from} uses profile "
                  f"{ref_man['source_profile']!r}, this session uses "
                  f"{man['source_profile']!r} -- the ROI will not line up, refusing")
            return 1
        ref_frames, _ = sample_frames(args.two_state_from, args.two_state_n, roi)
        if not ref_frames:
            print(f"no frames decoded from --two-state-from {args.two_state_from}")
            return 1
        print(f"  two-state reference: {len(ref_frames)} frames from "
              f"{args.two_state_from} (not this session's own footage)")
        gray_stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in ref_frames])
    else:
        gray_stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames])
    lo_gray, hi_gray = two_state_gray(gray_stack)

    out = STORE / "geometry" / f"{args.session}.npz"
    out.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out, labels=lab, static=med, roi=np.array([x0, y0, x1, y1]),
                        lo_gray=lo_gray, hi_gray=hi_gray,
                        built_by=np.array(source_stamp()))
    print(f"  wrote {out}  (stamp {source_stamp()[:8]})")
    if args.sheet:
        cv2.imwrite(args.sheet, render(med, lab))
        print(f"  wrote {args.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
