"""The static map, classified: floor, holes, borders, box edges, plant zones.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_geometry.py <session> [--sheet out.png]

the proposal, and it earns its place twice over.

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

the palette, which is what this reads
-----------------------------------------
The player named these off footage, and had never noticed the elevated shade before:

* standard grey -- the floor;
* **lighter grey -- a VIEWCONE**, which is what your team can currently see.
  Dynamic, so it is not in the static map at all, and that is a feature: it
  means differencing isolates it. Measured as a per-frame brightness lift of
  p90 +51 on Split against a p50 of 0;
* a **different lighter shade** for elevated areas -- Split heaven over A and B;
* **white or off-white for borders and box boundaries**;
* **yellow for plantable regions** on the sites.

Border versus box edge, which is the test
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

The holes are real -- the map simply has them. An earlier version of
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
from reticle import geometry as G
from reticle.profiles import get_profile                          # noqa: E402
from reticle import metrics                                       # noqa: E402
from reticle import minimap as mm                                 # noqa: E402
from minimap_icons import floor_mask, static_map                  # noqa: E402

STORE = Path.home() / "reticle-store"

# Class ids, in the order they are resolved. Later ones do not overwrite
# earlier ones, so the order is the priority. RE-EXPORTED from
# `reticle/minimap.py`, not defined here: shipped code needs them too (the cone
# passes a ray through a BOXEDGE without lighting it), and two copies of a
# number is a fork that agrees until it does not.
from reticle.minimap import (BORDER, BOXEDGE, FLOOR, HOLE,        # noqa: E402,F401
                             LABEL_NAMES as NAMES, PLANT, VOID)
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
# PROMOTED 2026-09-06 to `reticle/minimap.py` as SITE_*, because `floor_mask`
# needs the same rule -- a site is FLOOR, so the slab gate alone was dropping
# ground the position reader is read on. **The TEST followed them on
# 2026-09-07**: aliasing the thresholds while keeping a second copy of the loop
# around them is a fork with the numbers hidden, and it drifted within the day
# -- see `classify()`. `classify` now calls `mm.site_mask` and declares nothing.
# How far to look either side of a white pixel when asking whether the grey cuts
# off. Lines are 1-2 px, so this has to clear the line itself and land on what
# is beyond it.
PROBE = 4
# Bridges the same kind of single-frame dropout `minimap_icons.floor_mask`
# already closes for the floor slab, applied here to the white-line mask
# before border/box-edge classification -- see the note at that call site.
LINE_CLOSE = 5
LINE_MIN_AREA = 20


def two_state_gray(gray_stack, trim=0.05, band=48):
    """Per pixel, the two colours it actually rests at -- not one median.

    the model, checked against real footage before building this: **a
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
    like today's single reference.

    Also returns the WITHIN-STATE standard deviation of each side
    -------------------------------------------------------------
    Added 2026-09-04 as Phase 0 of `docs/ability-temporal.html`, which needs a
    per-pixel noise scale to divide by. NOTES has named that divisor for a
    fortnight -- the ability classes differ ~8x in contrast (median `dark` 105 /
    102 / 95 for the sonic sensor, trapwire and barrier mesh against **13** for
    Brimstone's Orbital Strike), so any global floor that keeps the strong three
    deletes the faint one at 17% recall. That is CLAUDE.md's *never test an
    absolute level against this HUD* arriving in the ability channel, and the
    fix it always wants is to compare relatively.

    **It must be per-state, and this is the whole subtlety.** The obvious
    measurement -- SD over all frames at a pixel -- is not a noise scale at all
    on this widget. A pixel the cone sweeps is BIMODAL by construction, so its
    overall SD measures the distance between unlit and lit, which is the
    largest number available and is largest exactly on the swept floor where
    every interesting candidate sits. Dividing by it would suppress the signal
    hardest where the signal is. `sd_lo` and `sd_hi` are the spread WITHIN each
    resting state, which is the quantity "how much does this pixel wobble when
    nothing is happening to it" actually means. They come from the same trimmed,
    split frames as `lo`/`hi`, so they describe the same two states rather than
    a separately-sampled approximation of them.

    Two properties a consumer has to handle rather than discover:

    * **a state of ONE frame has SD 0 by definition** -- a pixel that is almost
      always lit puts one sample in the low group. Zero is honest (there is no
      spread in one observation) and is a division hazard, so anything using
      these as a divisor must floor them. It must NOT be read as "this pixel is
      perfectly quiet";
    * they are only as good as the frames they were built from, and for every
      session sharing a key that is the reference session's frames rather than
      its own. That is correct -- the lighting model is a property of the map,
      not the match, measured at mean |d| 2.3-3.7 grey levels between different
      accounts, days and encodes -- and it means the noise scale is the
      reference recording's. Do NOT read the stored `lo_gray`/`hi_gray` of two
      builds as a measure of that transferability: they are cluster centres
      from different frame counts in different runs and differ three times as
      much for reasons that have nothing to do with the recordings.

    Chunked over row bands rather than vectorised over the whole widget
    -------------------------------------------------------------------
    The single-shot version allocated a full (K, H, W) int cumulative sum --
    ~650 MB at 400 frames on the enlarged widget -- and the squares needed for a
    variance would have doubled it. Banding costs nothing (this is a one-time
    per-session build step, not something running per detected frame) and the
    per-band arithmetic is bit-identical to the whole-array form, because
    `argmax` and the cumulative sums are per-pixel independent. Verified
    bit-identical for `lo`/`hi` against the pre-2026-09-04 implementation before
    this replaced it, on real frames -- the "confirm a known number comes back"
    check, run on the values rather than on a parse.
    """
    K, H, W = gray_stack.shape
    lo_i, hi_i = int(K * trim), max(int(K * (1 - trim)), int(K * trim) + 2)
    lo = np.empty((H, W), np.float32)
    hi = np.empty((H, W), np.float32)
    sd_lo = np.empty((H, W), np.float32)
    sd_hi = np.empty((H, W), np.float32)

    for y0 in range(0, H, band):
        y1 = min(y0 + band, H)
        s = np.sort(gray_stack[:, y0:y1].astype(np.int16), axis=0)[lo_i:hi_i]
        K2 = s.shape[0]
        # (h,w): index of the last element of the LOW group. `np.diff` is one
        # shorter than `s`, so this is always in [0, K2-2] and BOTH groups are
        # non-empty -- which is why no zero-count guard is needed below.
        split = np.argmax(np.diff(s, axis=0), axis=0)
        sel = split[None, :, :]

        cumsum = np.cumsum(s, axis=0).astype(np.float32)
        low_sum = np.take_along_axis(cumsum, sel, axis=0)[0]
        low_count = (split + 1).astype(np.float32)
        high_count = K2 - low_count
        m_lo = low_sum / low_count
        m_hi = (cumsum[-1] - low_sum) / high_count

        # float64 for the squares: 360 frames of 255**2 overflows float32's
        # exact-integer range (2**24), and E[x2]-E[x]2 is the unstable form.
        cumsq = np.cumsum(s.astype(np.int32) ** 2, axis=0).astype(np.float64)
        low_sq = np.take_along_axis(cumsq, sel, axis=0)[0]
        v_lo = low_sq / low_count - np.float64(m_lo) ** 2
        v_hi = (cumsq[-1] - low_sq) / high_count - np.float64(m_hi) ** 2

        lo[y0:y1] = m_lo
        hi[y0:y1] = m_hi
        sd_lo[y0:y1] = np.sqrt(np.maximum(v_lo, 0.0))
        sd_hi[y0:y1] = np.sqrt(np.maximum(v_hi, 0.0))

    return lo, hi, sd_lo, sd_hi


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

    **WIDENED 2026-09-06, and the gap it closes is the one this stamp exists
    for.** Hashing this file alone was correct only while every input to
    `classify()` lived in it. `floor_mask` and the plant tint were promoted to
    `reticle/minimap.py` that day, so from then on the shipped slab rule could
    have moved with every npz still reporting fresh -- the ARTEFACT versioned
    and the CODE PATH not, which is the exact failure `floor_mask`'s ten-day
    fork already cost once. The promoted definitions are fingerprinted in.

    `metrics.fingerprint` hashes function SOURCE, so this tracks behaviour and
    ignores edits elsewhere in that module -- the same granularity, and the
    same over-declaring trade, that `metrics` already took on purpose.
    """
    return hashlib.sha256(
        Path(__file__).read_bytes()
        + metrics.fingerprint(mm.floor_mask, mm.site_mask, mm.median_widget,
                              site_h=mm.SITE_H, site_s=mm.SITE_S,
                              site_v=mm.SITE_V, site_area=mm.SITE_MIN_AREA,
                              floor_s=mm.FLOOR_S_MAX, floor_v=mm.FLOOR_V_MIN,
                              bridge=mm.BRIDGE).encode()
    ).hexdigest()


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
    # The yellow plantable zones, from the ONE implementation of that test.
    #
    # This was an inline copy until 2026-09-07 and the copy had drifted: it
    # imported `SITE_MIN_AREA` but applied it unscaled, where `site_mask`
    # scales by the widget's AREA. On the 331 px widget that is 500 px against
    # 253, and Lotus's B and C sites are 407 and 369 px -- so this file labelled
    # ZERO of two real bomb sites on `lotus__valorant-16x9` while the shipped
    # function, on the same static, kept all three. The close and dilate
    # kernels had drifted the same way, 15 and 5 fixed against `_odd(5 * scale)`.
    # The letter-fill that used to live here moved into `site_mask` with it.
    #
    # A fork that agrees on the widget it was written for is the failure this
    # repo has now paid for twice, and `doctor`'s DUPLICATE check cannot see
    # this one: an inline copy shares no NAME with what it copies.
    plant = mm.site_mask(med, floor)

    # the test -- does the grey cut off? -- asked against the EXTERIOR the
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
    # the player caught "small squares scattered all over the map" in the rendered
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



def had_shade(out: Path) -> bool:
    """Did the npz about to be overwritten already carry the art's shade?

    Read this BEFORE the write. `reattach_shade` runs after, so by then the
    arrays it is meant to protect are already gone and their absence is
    indistinguishable from never having had them.
    """
    if not out.is_file():
        return False
    try:
        with np.load(out, allow_pickle=False) as z:
            return "shade" in z.files
    except Exception:                            # noqa: BLE001 -- never fatal
        return False


def reattach_shade(gkey: str, before: bool = False) -> None:
    """Put the art's terrain levels back after this file rewrites the npz.

    **This exists because the alternative is a standing chore, and a standing
    chore is a thing somebody has to be asked about twice.** `map_shade.py`
    writes `shade`/`shade_kind`/`shade_step`/`shade_purity` beside `labels`,
    and every write in this file replaces the npz wholesale -- so a rebuild
    silently drops them and the next read gets a geometry that lost half its
    content with nothing saying so.

    It costs nothing to do here: the arrays are a COPY of
    `reference/shade/<map>__<profile>.npz`, which is permanent and already
    built, so this is a file read rather than a fit.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import map_shade
        got = map_shade.write_shade(gkey, quiet=True)
    except Exception as e:                       # noqa: BLE001 -- never fatal
        print(f"  NOTE: could not re-attach the shade ({type(e).__name__}: {e})"
              f" -- run: map_shade.py build {gkey}")
        return
    # `write_shade` returns None WITHOUT raising when the art for this map is
    # not fetched -- so the best-effort path above cannot see the case that
    # actually costs something. Measured 2026-09-07, under the old per-session
    # layout: a rebuild dropped shade two npz already had and `doctor`'s SHADE
    # finding went 1 -> 3 with nothing in the rebuild output saying so. Losing
    # arrays that were there is a different event from never having had them,
    # and only this one deserves a line.
    if got is None and before:
        print(f"  LOST THE SHADE: {gkey} carried the art's terrain levels and no "
              f"longer does -- `map_shade.write_shade` declined, usually a map "
              f"whose art is not fetched. Then run: map_shade.py build {gkey}")


def build_key(gkey: str, n: int = 180, source: str | None = None,
          sheet: str | None = None) -> int:
    """Build one (map, profile) geometry from its reference session's frames.

    `source` overrides the reference session, which is the longest recording on
    that key. Nothing else in this file writes an npz: there is one geometry per
    key and one way to make it, so a short clip can no longer hold a private
    answer about a map it shares with a 39-minute match.
    """
    src_sid = source or G.reference_session(gkey, STORE)
    if not src_sid:
        print(f"{gkey}: no ingested session reads this key -- nothing to build from")
        return 1
    if G.key_of(src_sid, STORE) != gkey:
        print(f"{gkey}: {src_sid} reads {G.key_of(src_sid, STORE)}, not this key "
              f"-- refusing, the ROI would not line up")
        return 1

    man = json.loads((STORE / "manifests" / f"{src_sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)

    frames, _ = sample_frames(src_sid, n, (x0, y0, x1, y1))
    if not frames:
        print(f"{gkey}: no frames decoded from {src_sid}")
        return 1

    # DROP THE FRAMES WITH NO WIDGET BEFORE FITTING ANYTHING, and do it in two
    # passes because the test needs a static map to compare against.
    #
    # **This is the defect that made the whole viewcone channel meaningless on
    # one map, and it is in the fit rather than in any detector.** Round
    # transitions, buy-phase fades and death screens black the widget out, and
    # an even sample over a 37-minute match lands on some: measured 2026-09-07,
    # 16 of 180 on `5822b6646448` and 6 of 180 on `a06f04a0059f`. Their floor
    # grey is 61 against 118-123 when the widget is drawn.
    #
    # `static_map` is a per-pixel MEDIAN and shrugs that off. `two_state_gray`
    # cannot: it splits each pixel's samples at the LARGEST GAP, and a 58-level
    # gap between blacked-out frames and normal ones is the largest gap there
    # is. So `lo_gray` became *widget absent* and `hi_gray` became *widget
    # present*, and every ordinary frame then read as `hi` -- which the two-
    # state reader calls LIT. On Lotus that made 33.7% of the usable floor
    # permanently "an ally can see this", including the entire enemy half.
    # The signature is a giveaway once you know it: sd_hi 1.7 against sd_lo 9.9,
    # a tight bright cluster against a broad dark one.
    #
    # `widget_drawn` already existed and answers exactly this question. The fit
    # simply never asked it.
    med = static_map(frames)                      # robust to the outliers
    floor0 = floor_mask(med)
    sg0 = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)
    drawn = [f for f in frames if mm.widget_drawn(f, sg0, floor0)]
    if len(drawn) < max(30, len(frames) // 4):
        print(f"{gkey}: only {len(drawn)} of {len(frames)} frames have the widget "
              f"drawn -- refusing rather than fitting a lighting reference on "
              f"blacked-out frames")
        return 1
    if len(drawn) < len(frames):
        print(f"  dropped {len(frames) - len(drawn)} of {len(frames)} frames with "
              f"no widget drawn before fitting")
    frames = drawn
    med = static_map(frames)                      # again, on clean frames only
    lab = classify(med)
    others = [s for s in G.sessions_for(gkey, STORE) if s != src_sid]
    summarise(lab, f"{gkey}  (from {src_sid}, {len(frames)} frames"
                   f"{f'; read by {len(others)} other session(s)' if others else ''})")

    gray_stack = np.stack([cv2.cvtColor(f, cv2.COLOR_BGR2GRAY) for f in frames])
    lo_gray, hi_gray, sd_lo, sd_hi = two_state_gray(gray_stack)

    out = G.path(gkey, STORE)
    out.parent.mkdir(parents=True, exist_ok=True)
    was_shaded = had_shade(out)
    np.savez_compressed(out, labels=lab, static=med, roi=np.array([x0, y0, x1, y1]),
                        lo_gray=lo_gray, hi_gray=hi_gray,
                        sd_lo=sd_lo, sd_hi=sd_hi,
                        built_from=np.array(src_sid),
                        built_by=np.array(source_stamp()))
    reattach_shade(gkey, was_shaded)
    print(f"  wrote {out}  (stamp {source_stamp()[:8]})")
    if sheet:
        cv2.imwrite(sheet, render(med, lab))
        print(f"  wrote {sheet}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Build the static map geometry for a (map, profile) key.")
    ap.add_argument("key", nargs="?",
                    help="a geometry key, `<map>__<profile>`; or a session id, "
                         "which is resolved to the key that session reads")
    ap.add_argument("--all", action="store_true",
                    help="rebuild every key at least one ingested session reads")
    ap.add_argument("--n", type=int, default=180, help="frames to median over")
    ap.add_argument("--from", dest="source", default=None,
                    help="build from THIS session rather than the longest "
                         "recording on the key. The default is deliberate -- "
                         "the static map is a per-pixel median, so a short clip "
                         "built around one deliberate cast bakes the cast in.")
    ap.add_argument("--sheet")
    args = ap.parse_args(argv)

    if args.all:
        if args.key or args.source or args.sheet:
            print("--all takes no key, --from or --sheet")
            return 2
        keys = G.keys_in_store(STORE)
        loose = G.untagged(STORE)
        print(f"{len(keys)} geometry key(s) from "
              f"{len(list((STORE / 'manifests').glob('*.json')))} sessions")
        if loose:
            print(f"  {len(loose)} session(s) resolve to NO key and will read no "
                  f"geometry -- tag them `map:<name>`: {', '.join(loose)}")
        rc = 0
        for k in keys:
            rc |= build_key(k, args.n)
        return rc

    if not args.key:
        print("give a key (`<map>__<profile>`), a session id, or --all")
        return 2
    gkey = args.key if G.SEP in args.key else G.key_of(args.key, STORE)
    if gkey is None:
        print(f"{args.key} has no `map:` tag, so it reads no geometry -- tag it, "
              f"or name a key directly")
        return 1
    if gkey != args.key:
        print(f"{args.key} reads {gkey}")
    return build_key(gkey, args.n, args.source, args.sheet)


if __name__ == "__main__":
    raise SystemExit(main())
