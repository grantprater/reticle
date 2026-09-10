"""Stage 02: player position off the minimap.

Promoted from `prototypes/minimap_position.py` on 2026-09-02, after two
independent ground-truth checks -- the blue X a death leaves (`xmark_eval.py`,
against scoreboard-verified killfeed deaths) and the map's physical
chokepoints (`chokepoint_eval.py`, against location-banner transitions) --
both landed within ~1-1.5m of ground truth across Ascent, Lotus and Haven.
See `prototypes/CLAUDE.md` for the full arc, including five rejected
approaches: every content-based method drowned in the world moving behind the
minimap's semi-transparent void [domain:minimap/transparency]. Masking to the
opaque floor slab is the fix, and it is the whole reason this module exists in
this shape.

What is promoted and what is not
---------------------------------
**Self position is a real track**: per frame, the candidate nearest the
previous point wins, so occlusion and momentary noise do not break identity.
`filter_track()` then drops physically-impossible steps and interpolates the
short gaps they leave. This is what "wraps up" -- it is validated and stored.

**Ally rings are still per-frame candidates, not tracks.** Up to four
teammates can be on screen and nothing here assigns identity across frames --
the X-mark check only needed "was ANY ally candidate near the death", never
"was it teammate #3 specifically". `write_minimap()` stores up to
`MAX_ALLIES` candidates per frame, sorted by blob area (largest first), with
no claim that slot 0 is the same player between frames. Building real ally
identity is future work, not silently assumed here.

Known limits carried from the prototype, unresolved:
* No elevation -- the floorplan is a 2D silhouette.
* Enemy icons are deliberately out of scope here (see `minimap_ring_fit.py` /
  `minimap_portrait.py`) -- this module only reads the player's own team,
  which needs no icon-population filtering because self/ally colour keys are
  exact and exclusive.
* Scale is roughly 0.2 m/px, from map extent rather than calibration.
* The fixed, non-rotating, non-side-swapping minimap is a per-session SETTING
  (see the pre-ingest checklist in the root CLAUDE.md), not a game default --
  a capture recorded with Valorant's defaults breaks every position here
  silently, returning rotated or mirrored positions rather than an error.
"""

from __future__ import annotations

import cv2
import numpy as np

from .profiles import Profile

# ---------------------------------------------------------------- widget scale
#
# **Every constant below is in WIDGET PIXELS, and the widget has two sizes.**
# `valorant-16x9-bigmap` is ~1.4x `valorant-16x9` linearly, and the pre-ingest
# checklist has said since 2026-08-26 that "geometry and icon thresholds both
# scale with it" while nothing in the code did. All four sessions with minimap
# L1 are bigmap; SIXTEEN sessions in the store are the small widget and none has
# been read, so this was prospective rather than wrong -- but the failure modes
# differ in loudness, which is the reason to fix it before those are read.
# `MIN_ICON_AREA` fails LOUDLY on a smaller widget (the self rate collapses).
# The `floor_mask` dilation fails SILENTLY and in the dangerous direction: a
# fixed 9 px closes proportionally wider cracks on a smaller widget, admitting
# more of the semi-transparent void, which is the documented cause of reading
# non-minimap content as icons.
#
# The derivation needs no plumbing, which is why it is worth doing rather than
# discussing: **every function here is already handed a crop whose width IS the
# widget width.** So the scale is available in place, at each call, with no
# argument threading and no per-session state to keep in sync.
#
# The reference is the widget these constants were measured on.
REF_WIDGET_W = 465.0        # valorant-16x9-bigmap at 1920x1080: x 15..480


def widget_scale(width_px: float) -> float:
    """Linear scale of this widget against the one the constants were measured on.

    Exactly 1.0 for `valorant-16x9-bigmap` at 1080p, so nothing that has ever
    been read moves -- which is the check this change is verified by, not an
    argument that it is safe.
    """
    return float(width_px) / REF_WIDGET_W


def _odd(n: float, lo: int = 3) -> int:
    """Nearest odd kernel size, floored -- an even structuring element is off-centre."""
    k = max(lo, int(round(n)))
    return k if k % 2 else k + 1


# Top speed of a real track, px/s, measured rather than derived: every
# filtered track sits under it and every misdetection blew far past it.
# A SPEED in widget pixels, so it scales linearly with the widget.
RUN_PX = 45.0
GAP_MS = 1000.0

#: Per-observation centre error of an icon fit, widget px at scale 1.0.
#:
#: **Measured from FORCED CORRESPONDENCES**, which need no tracker and no
#: labels: in the 2 s 60 Hz Ascent and Lotus windows the self icon is detected
#: in every one of the 120 frames, exactly once, so consecutive detections are
#: the same entity by construction. Physical motion can contribute at most
#: `RUN_PX * 1/60 = 0.75 px` at that rate, so the rest of each step is fit
#: error, whatever the player was doing:
#:
#:     residual after the walk allowance, 238 self pairs over the two maps
#:     p50 0.25 / -0.75   p90 1.49 / 2.08   p99 2.86 / 3.25   max 3.25 / 3.72
#:
#: An independent measurement agrees on the magnitude: `prototypes/CLAUDE.md`
#: recorded the fitted centre moving 1.0 px per frame on stable frames and 3.2
#: on flip frames (p90 5.0 and 8.5) at 15 Hz -- taken to diagnose the bearing
#: flip, with nothing to do with association.
#:
#: 2.0 px is not knife-edge: every value from 2.0 to 10.0 holds the self track
#: at ONE id across both windows, and the ceiling is icon separation -- two
#: icons closer than ~2r = 20 px are not separately detectable anyway, so 2e
#: spends 4 of a 20 px budget. Below 2.0 the track fragments: at the old
#: sqrt(0.5) (quantization only, which is a floor rather than a measurement)
#: the same 120 frames became 13 and 10 ids.
#:
#: It lives here rather than in `track`, where it was measured, because
#: `pick_self` needs it too and `track` already imports `RUN_PX` from this
#: module -- the other direction is a cycle. `track.FIT_ERR_PX` still resolves.
FIT_ERR_PX = 2.0

# The pale yellow-green the game rings the local player with -- the same
# colour scoreboard.py keys the player's own row on, and it transfers
# unchanged.
SELF_G_MIN, SELF_R_MIN, SELF_B_UNDER_G = 200, 140, 45
ALLY_H, ALLY_S_MIN, ALLY_V_MIN = (75, 100), 90, 140
MIN_ICON_AREA = 10
MAX_ALLIES = 4  # a 5-stack has at most four teammates to show


def minimap_roi_px(profile: Profile, w: int, h: int) -> tuple[int, int, int, int]:
    return next(r for r in profile.rois if r.name == "minimap").pixels(w, h)


# BUILDER-ONLY COMPATIBILITY HOOK. `minimap_geometry.source_stamp` fingerprints
# this exact function, so deleting/moving it would invalidate all 12 baked maps.
# No reader, eval, or ordinary prototype may call it; `doctor` enforces that.
def median_widget(frames) -> np.ndarray:
    """The widget with every icon removed, as a per-pixel median.

    Icons move, map furniture does not. Split out of `static_map` on
    2026-09-06: this half was the whole of `prototypes/minimap_icons.static_map`
    for ten days, which is the same fork `floor_mask` had -- one name, two
    definitions, in the two files that already disagreed about the slab.

    The two callers differ only in where the frames come from. A clip takes
    them directly, because a short lossless capture is never ingested and has
    no spans; a session samples them off active spans below.
    """
    if len(frames) == 0:
        raise SystemExit("no frames -- cannot build a static map")
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


#: The slab gate. Measured on the enlarged widget 2026-08-26: the map slab is
#: pure grey (S=0, V=118) and the scenery hazing through the transparent part
#: sits at S 36-58, V 97-140. **Value cannot do this job** -- the background is
#: BRIGHTER than the floor, not darker -- so saturation is the discriminator
#: and the level is tight on purpose.
FLOOR_S_MAX, FLOOR_V_MIN = 20, 100

#: The yellow plant zones, PROMOTED from `prototypes/minimap_geometry.py` on
#: 2026-09-06 so the tint rule exists once. That module keys its `PLANT` class
#: on these and adds the letter fill, which is a LABELLING concern; walkability
#: is this.
#:
#: **A site is FLOOR.** Recorded 2026-09-06, on a version of `floor_mask` that had
#: just started excluding them: *why would floor mask exclude bomb sites? Those
#: are part of the floor.* Exactly right, and it names the error: the tint is
#: PAINT ON the floor, a rendering property, not a different surface. Measured
#: consequence of getting it wrong -- 9.6% of stored self positions and 4.4-6.7%
#: of ally positions on `a06f04a0059f` sit inside a site, so a slab-only mask
#: blinds the position reader on exactly the ground a round is decided on.
# Geometry class ids, in the order `minimap_geometry.classify` resolves them --
# later ones do not overwrite earlier ones, so the order is the priority. They
# live here rather than in the prototype because SHIPPED code needs them: the
# cone passes a ray through a BOXEDGE without lighting it, and `overlay` and
# `cone` were each about to hardcode `4`, which is a fork with no name.
VOID, FLOOR, HOLE, BORDER, BOXEDGE, PLANT = 0, 1, 2, 3, 4, 5
LABEL_NAMES = {VOID: "void", FLOOR: "floor", HOLE: "hole", BORDER: "border",
               BOXEDGE: "box edge", PLANT: "plantable"}


SITE_H = (15, 40)
SITE_S, SITE_V = 40, 120
#: A site is a painted REGION. This floors out warm specks and, with the
#: touches-the-slab test, the agent HUD in the corner -- which a first widening
#: of the hue test turned into a third "bomb site" of 10921 px of brown void.
SITE_MIN_AREA = 500
#: How close another component may sit to the main slab and still count as part
#: of it -- a real room cut off by one narrow doorway, not a HUD element or an
#: edge-scenery speck. the player caught Ascent's Boathouse being thrown away whole
#: by a largest-component-only rule; the five closest unclaimed components on
#: `a06f04a0059f` are 6.2-24.0 px away and all visibly real interior rooms,
#: and the next jumps to 31 px and is a 5 px speck. 25 sits in that gap.
#: A LENGTH, so it scales with the widget.
BRIDGE = 25
#: Which percentile of the map body's own `sd_lo` a bridged component must sit
#: inside to be map. Not fitted: the body is the reference for what a stable
#: pixel looks like, and 95 leaves the body's own noisiest twentieth out of the
#: comparison. See `floor_mask` for the twelve-geometry separation it rests on.
STABLE_PCT = 95


def floor_mask(med: np.ndarray, dilate: float = 9,
               sd: np.ndarray | None = None) -> np.ndarray:
    """The opaque walkable slab. Everything else is see-through and churns.

    **Reconciled 2026-09-06.** This function existed twice with different
    behaviour -- here on `sat < 60 & val > 110` with a bare dilation, and in
    `prototypes/minimap_icons.py` on `sat < 20 & val > 100` plus the component
    rule below. They had been diverging since 2026-08-27, when the prototype
    was improved and this copy was not; the promotion on 2026-09-02 took the
    older branch. `CLAUDE.md` recorded the fork as byte-identical and harmless,
    and by then it was neither.

    Arbitrated against the two unseeded painted map masks
    (`prototypes/floor_mask_eval.py`), which is the version kept:

        a06f04a0059f  Ascent   sat<60  IoU 57.8%   sat<20  IoU 74.8%
        5822b6646448  Lotus    sat<60  IoU 74.0%   sat<20  IoU 75.5%

    The loose gate is a near-strict SUPERSET -- so it scores 100% recall on
    both, which is what a superset of the answer always scores and is not a
    result. What it adds on Ascent is 15.2% of the widget, **90.1% of it
    outside the painting**: the semi-transparent void, which is the documented
    cause of reading non-minimap content as icons.

    **THE SITES ARE FLOOR, and the slab gate alone drops them.** A tight gate
    lost 5.1% of the painting on Ascent as two compact blobs and three on
    Lotus -- each map's site count exactly, all five at saturation ~58 where
    the slab is S=0. the player, shown that: *why would floor mask exclude bomb
    sites? Those are part of the floor.* The tint is paint ON the floor, so
    `site_mask` joins them back and the union is what this returns.

    Scored against the two paintings, which is the whole arbitration:

        gate                       Ascent IoU   Lotus IoU   recall
        sat<60, bare dilation         57.8%       74.0%      100%  (superset)
        sat<20 slab only              74.8%       75.5%     94.9% / 96.8%
        sat<20 slab | sites           78.8%       77.9%      100% / 100%

    The old threshold caught the sites for the right reason and the void for
    the wrong one with a single number, which is why it could not be tightened.
    Separating slab from tint is what lets the void go without losing ground a
    player actually stands on -- measured, 9.6% of stored self positions on
    `a06f04a0059f` are inside a site.

    That the union reproduces `minimap_geometry`'s independently-fitted `PLANT`
    class exactly, on both maps, is the check on `site_mask` rather than a
    coincidence -- `prototypes/floor_mask_eval.py` scores both and they agree
    to the pixel.

    Every length here scales with the widget, for the reason the dilation
    already did: left fixed, a 9 px close eats proportionally wider cracks on a
    smaller widget and quietly admits void. `widget_scale` is exactly 1.0 on
    every capture read so far, so nothing measured moves -- which is how this
    was verified, not an argument that it is safe.

    `dilate` is exposed because the widget grew ~1.5x on 2026-08-26 and this
    radius was measured before that. **`dilate=1` means no dilation at all**
    and several ability callers rely on it, so it is preserved exactly rather
    than rounded up to the minimum odd kernel.

    **`sd` is the geometry npz's `sd_lo`, and it decides what BRIDGE may
    re-attach.** The bridge is a proximity rule, and proximity cannot tell a
    room from the widget's own furniture: the location-name banner is drawn
    9 px above Sunset's map body, so 25 px of dilation swallowed it and the
    round pipeline reported the text as map. Measured on
    `sunset__valorant-16x9-bigmap`, that island was **57 entity hypotheses
    over 1410 observations** in one 79 s round -- persistent `ability? 307`
    and `enemy 68` boxes sitting on the words `B Market`.

    The channel that already knows is the one the brightness test does not
    read: **map structure is what does not change.** A bridged component is
    admitted only when its median `sd_lo` is inside the body's own 95th
    percentile, so the reference is the map rather than a fitted number. Over
    the twelve baked geometries the two are cleanly separated -- every real
    component sits at 0.00-0.87 of the body's p95 and the two offenders at
    2.90 (Split's rim) and 7.46 (Sunset's banner):

        component                                   median sd_lo / body p95
        ascent bigmap (42,129,29,47)   1362 px       0.00   room, kept
        abyss (21,255,45,48)             94 px       0.42   island, kept
        summit crop75 (243,403,16,13)    79 px       0.87   kept
        split 16x9 (200,49,124,280)     485 px       2.90   REFUSED
        sunset bigmap (193,8,81,14)     486 px       7.46   REFUSED, the banner

    Ascent's 1362 px component is the check that matters: it is the shape of
    the Boathouse this bridge exists for, and a stability gate keeps it while
    a convex-hull rule -- the other threshold-free candidate measured here --
    threw it away.

    **Omitting `sd` keeps the pure-`med` behaviour exactly**, because most
    callers hold a static map and no variability map. `doctor`'s BANNER check
    scores every baked geometry both ways, so a call site that could pass it
    and does not stays visible instead of quietly keeping the defect.
    """
    scale = widget_scale(med.shape[1])
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    m = ((hsv[:, :, 1] < FLOOR_S_MAX) & (hsv[:, :, 2] > FLOOR_V_MIN)).astype(np.uint8)
    # Join the floorplan's own thin corridors before taking a component, or the
    # slab arrives as several pieces and the largest is one wing of the map.
    c = _odd(5 * scale)
    j = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(j, 8)
    if n <= 1:
        return np.zeros(m.shape, bool)
    # Largest component drops the corner HUD and the edge-scenery specks by
    # derivation rather than by a hand-drawn box. Then recover the rooms a
    # narrow doorway cut off -- see BRIDGE.
    big_id = 1 + int(np.argmax(st[1:, 4]))
    big = (lbl == big_id).astype(np.uint8)
    b = _odd(BRIDGE * scale)
    near = cv2.dilate(big, np.ones((b, b), np.uint8)) > 0
    ceiling = (float(np.percentile(sd[lbl == big_id], STABLE_PCT))
               if sd is not None else None)
    for i in range(1, n):
        if i == big_id or not (lbl == i)[near].any():
            continue
        if ceiling is not None and float(np.median(sd[lbl == i])) > ceiling:
            continue                              # near the map, but not OF it
        big[lbl == i] = 1
    # The sites are floor too, and they join BEFORE the dilation so a site's
    # edge gets the same overhang margin the slab's does.
    big |= site_mask(med, big > 0).astype(np.uint8)
    d = int(round(dilate * scale))
    if d > 1:
        d = _odd(d)
        big = cv2.dilate(big, np.ones((d, d), np.uint8))
    return big > 0


def site_mask(med: np.ndarray, slab: np.ndarray) -> np.ndarray:
    """The yellow plantable zones -- painted floor, and floor is what they are.

    Separate from the slab gate because they are separable in the pixels and
    NOT separable in the old `sat < 60` threshold, which caught the sites and
    the semi-transparent void with one number and could not be tightened
    without losing the sites. Splitting them is what lets the void go.

    `slab` is required rather than optional: a site is recognised as tinted
    paint **that touches walkable ground**, which is what stops the agent HUD
    in the corner becoming a third bomb site. That failure is on record -- a
    first widening of the hue test grew one out of 10921 px of brown void on
    Split, and nothing noticed because the npz was stale.

    **A kept component is FILLED, so the site letter comes with the paint.**
    The A/B/C glyphs are a near-black grey drawn on the tint, so they are holes
    in the hue mask and a hole in the middle of a bomb site is not a thing the
    map has. This lived in `minimap_geometry.classify` until 2026-09-07, beside
    a second copy of everything else here -- see the note on the scaling below
    for what that fork cost. Moving it changes nothing for `floor_mask`, which
    is the caller that could have been surprised: measured on three keys, the
    fill recovers 404, 131 and 0 px and **every one of them is already in the
    slab**, because a dark glyph on painted ground is desaturated enough to
    pass the slab test on its own.
    """
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    tint = ((h >= SITE_H[0]) & (h <= SITE_H[1]) & (s > SITE_S) & (v > SITE_V))
    scale = widget_scale(med.shape[1])
    c = _odd(5 * scale)
    tint = cv2.morphologyEx(tint.astype(np.uint8), cv2.MORPH_CLOSE,
                            np.ones((c, c), np.uint8))
    near = cv2.dilate(slab.astype(np.uint8), np.ones((c, c), np.uint8)) > 0
    n, lbl, st, _ = cv2.connectedComponentsWithStats(tint, 8)
    out = np.zeros(tint.shape, bool)
    # Area is in PIXELS, so it scales with the widget's AREA, not its length.
    #
    # **The scaling is the whole reason this function has one home.** An
    # unscaled copy of this loop lived in `minimap_geometry.classify` and
    # imported `SITE_MIN_AREA` without the `scale * scale`, so on the 331 px
    # widget it demanded 500 px where this demands 253. Lotus has the smallest
    # bomb sites in the store -- B and C measure 407 and 369 px there -- so
    # `lotus__valorant-16x9` labelled ZERO of two sites while this function,
    # run on the same static, kept all three. It scored 35.4% against the art
    # where every other key scored 72-88%, and nothing downstream noticed,
    # because an unlabelled site reads as ordinary floor rather than as an
    # error. Found 2026-09-07 by scoring every key at once.
    min_area = SITE_MIN_AREA * scale * scale
    for i in range(1, n):
        comp = lbl == i
        if st[i, 4] < min_area or not (comp & near).any():
            continue
        ff = comp.astype(np.uint8)
        m2 = np.zeros((ff.shape[0] + 2, ff.shape[1] + 2), np.uint8)
        cv2.floodFill(ff, m2, (0, 0), 1)
        out |= comp | (ff == 0)                  # the paint, plus its letter
    return out


#: Floor-slab mean brightness below which the widget is unreadable. The gap it
#: sits in is 39 (p01) to 110 (p05), so this is not a tuned edge. Kept for
#: callers that predate `widget_drawn`; it answers a WEAKER question -- see below.
USABLE_MIN = 70.0

#: `widget_drawn` separates cleanly at this: measured on 120 sampled Lotus
#: frames, widget-absent tops out at 0.135 and widget-present bottoms out at
#: 0.45. Re-confirmed 2026-09-05 on the M-key clip: -0.03..+0.09 against
#: +0.80..+0.89.
DRAWN_MIN_CORR = 0.30


def usable(crop: np.ndarray, floor: np.ndarray) -> bool:
    """Is the widget bright enough to read? A brightness floor, nothing more.

    Catches Omen's ultimate and round fades. **It does not answer whether the
    widget is there at all** -- see `widget_drawn`, which is the test almost
    every caller actually wants.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(g[floor].mean()) >= USABLE_MIN


def widget_drawn(crop: np.ndarray, sgray: np.ndarray, floor: np.ndarray,
                 min_corr: float = DRAWN_MIN_CORR) -> bool:
    """Is the widget RENDERED AT ALL, or are we looking at the world through it?

    **`usable()` does not answer this**, and finding that out cost 16% of a
    labelling pass. Two unrelated things remove the corner minimap and leave
    ordinary world pixels in the ROI -- bright, high-contrast, and sailing
    straight through a brightness floor built for Omen's ult:

    * **the DEATH SCREEN**, where Valorant draws the full map centre-screen
      instead. On Lotus, 6 of 119 sampled frames (5%) were widget-absent and
      produced 16% of all candidates;
    * **the M KEY**, found by the player 2026-09-05 and recorded on purpose. Opening
      the full-size map takes the widget away the same way -- and unlike the
      death screen this is PLAYER-INITIATED and can happen at any moment in a
      round, as often as the player presses it.

    The test is scale-free rather than a fitted magnitude: correlate the crop
    against the static map over the floor mask. When the widget is drawn the
    static map IS most of what is there, so the correlation is high whatever the
    brightness; when it is absent there is no relationship at all.

        widget absent   0.001  0.009  0.039  0.067  0.070  0.135   (Lotus)
        widget drawn    >= 0.45 (n=113, median 0.92)
        M key held     -0.026  0.012  0.032  0.066  0.073  0.085   (2026-09-05)
        same clip, drawn  +0.80 .. +0.89

    A mean-absolute-difference threshold also separates these, but only just
    (42 against a p90 of 20) and it moves with scene brightness. The first cut
    of this used one and put the boundary 0.003 apart, because two absent frames
    had been miscounted as present -- rendering all six settled it in one look.

    Promoted here from `prototypes/minimap_temporal.drawn` on 2026-09-05, when
    the shipped position reader adopted it. That module now delegates rather
    than keeping a copy: two implementations of a gate that decides which frames
    exist is exactly the kind of divergence nothing would report.

    **One circularity, stated because it is real and unfixed.** `sgray` comes
    from `static_map`, a median over active-span frames -- which may themselves
    include widget-absent ones. So the reference used to detect them is built
    partly from them. At the rates measured (5.0% on a06f04a0059f) a per-pixel
    median is entirely robust to it, and the M-key clip separates by an order
    of magnitude, so this is not affecting any number here. But it degrades in
    the direction that HIDES the problem: a session where the full-size map was
    open for a large share of active play would pull the median toward the
    world behind the widget, raising the correlation of exactly the frames this
    is meant to refuse. Check the reported absent rate before trusting a
    session where it is unusually high -- a LOW rate is the ambiguous reading,
    not a high one.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)[floor]
    sg = np.asarray(sgray, dtype=np.float64)[floor]
    g = g - g.mean()
    sg = sg - sg.mean()
    den = float(np.sqrt((g * g).sum() * (sg * sg).sum()))
    return den > 0 and float((g * sg).sum() / den) >= min_corr


# --------------------------------------------------------------- ring fitting
# Promoted from `prototypes/minimap_ring_fit.py` on 2026-09-06 by DELETION plus
# re-export there, not by copy. It fits a circle to a fragmented colour ring by
# CIRCUMFERENCE COVERAGE [domain:minimap/fit-not-repair], which is what
# tolerates an arc broken by chroma subsampling [domain:capture/chroma-420] or
# by another icon drawn over it, and it reads the facing triangle by how far
# colour reaches past that circle.
#
# It is here rather than in `cone.py` because it is icon geometry on this
# widget, the same subject as `_rings` below, and because the enemy channel
# uses it too. The prototype keeps the argument for WHY the fit has this shape.

# Radii to try, in pixels. Kept NARROW on purpose. Coverage is a fraction of
# circumference, so a small circle threaded through one surviving fragment
# scores better than a correctly-sized circle that is mostly gap -- with the
# range open to 6 the fit collapsed to r=6 on nearly every 4:2:0 miss and the
# coverage it reported meant nothing. The widget size is fixed, so the icon
# radius is very nearly a constant (measured ~9-10 on the enlarged widget) and
# letting it float was giving away the strongest prior available.
#
# This is per-widget-size and must be re-measured if the player changes the slider.
R_MIN, R_MAX = 8, 13
#: Two same-role fits closer than this are two fits of ONE icon, not two
#: icons: the widget cannot draw two of them overlapping and leave two rings
#: to find. `2 * R_MIN` is the smallest diameter this detector will fit, and
#: it lands in a measured empty gap -- over the 2 s Ascent window every
#: same-frame ally pair is either 8.1-9.1 px apart (four of them, and all four
#: are the same signature: one r=8 fit of area ~100 beside one r=12-13 fit of
#: area ~20) or at least 45 px apart (77 of them). Nothing at all sits between
#: 10 and 45 px, so the threshold is not being placed on a slope.
MIN_ICON_SEPARATION_PX = 2 * R_MIN
# How far the true centre may sit from the blob's centroid. The triangle drags
# the centroid toward itself by several pixels, which is the same effect that
# reported the facing 180 degrees out before it was measured from the hole.
SEARCH = 5
N_THETA = 48


def _circle_offsets(r_min: int = None, r_max: int = None):
    """Precomputed integer ring offsets per radius, and the disc per radius.

    The range is a parameter rather than the module constants because the icon
    radius is a WIDGET-SIZE constant, not a game constant: 8-13 was measured on
    the enlarged widget, and a session at `widget_scale` 0.71 wants 6-9. The
    default is the measured pair, so every existing caller is unmoved.
    """
    ring, disc = {}, {}
    th = np.arange(N_THETA) / N_THETA * 2 * np.pi
    for r in range(R_MIN if r_min is None else r_min,
                   (R_MAX if r_max is None else r_max) + 1):
        pts = np.unique(np.stack([np.round(r * np.cos(th)),
                                  np.round(r * np.sin(th))], 1).astype(int), axis=0)
        ring[r] = pts
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        inner = (yy ** 2 + xx ** 2) <= (r * 0.62) ** 2
        disc[r] = np.stack([xx[inner], yy[inner]], 1)
    return ring, disc


RING, DISC = _circle_offsets()


def _offsets(r: int):
    """Ring and disc offsets for one radius, memoised into RING/DISC."""
    if r not in RING:
        ring, disc = _circle_offsets(r, r)
        RING.update(ring)
        DISC.update(disc)
    return RING[r], DISC[r]

# Rays for reading the facing triangle: for each angle, how far past the ring
# does red reach. The triangle is the only thing outside the circle, so the
# angle where red reaches furthest IS the facing.
N_FACE = 32
_FACE_TH = np.arange(N_FACE) / N_FACE * 2 * np.pi


def _best_circle(red, cx, cy, r_min, r_max):
    """The (cov, x0, y0, r) with the most red circumference. Vectorised.

    The search is 11x11 centre offsets by ~6 radii, and the loop version did
    726 separate `.mean()` calls over ~40 points each -- 8 ms per blob, which
    made `ally_icons` 114x the cost of `ally_rings` and 58 min for one session
    at 15 Hz. All 121 centres for one radius are one gather instead.

    **Tie-breaking is preserved exactly.** The loop kept the FIRST best (it
    tested `cov > best[0]`, strictly) and iterated dy, then dx, then r; the
    array is built in that order and `argmax` also returns the first maximum.
    `_fit_ring_loop` is kept as the reference and `--self-test` checks them.
    """
    h, w = red.shape
    offs = np.arange(-SEARCH, SEARCH + 1)
    # `rint(c + off)`, NOT `rint(c) + off`. Those are not the same under
    # banker's rounding when the centroid lands on a half-integer, which real
    # centroids do constantly: at cy=76.5 the loop's eleven offsets come out
    # 72,72,74,74,76,76,78,78,80,80,82 -- duplicated and SKIPPING, so the
    # search is neither centred nor +/-5. That is an artefact rather than a
    # design, but it is the SHIPPED behaviour and every number on record was
    # measured with it, so this reproduces it exactly. Widening the search to
    # a real +/-5 is a detector change and needs its own measurement; doing it
    # inside a speedup is the unversioned edit `metrics` BROKEN exists to
    # catch. Recorded as a defect in NOTES.md.
    y0s = np.rint(cy + offs).astype(int)[:, None]        # (11, 1)  dy outer
    x0s = np.rint(cx + offs).astype(int)[None, :]        # (1, 11)  dx inner
    n_off = len(offs)
    radii = list(range(r_min, r_max + 1))

    cov = np.full((n_off, n_off, len(radii)), -1.0)
    for k, r in enumerate(radii):
        pts, _ = _offsets(r)
        xs = x0s[..., None] + pts[None, None, :, 0]      # (11, 11, P)
        ys = y0s[..., None] + pts[None, None, :, 1]
        ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
        n_ok = ok.sum(-1)
        hit = red[np.clip(ys, 0, h - 1), np.clip(xs, 0, w - 1)] & ok
        with np.errstate(invalid="ignore", divide="ignore"):
            c = hit.sum(-1) / n_ok
        # The loop SKIPPED a candidate with too few in-bounds points, which is
        # not the same as scoring it zero: a skipped candidate can never win.
        cov[:, :, k] = np.where(n_ok >= len(pts) * 0.75, np.nan_to_num(c, nan=-1.0), -1.0)

    if not (cov >= 0).any():
        return None
    i = int(np.argmax(cov))
    iy, ix, ir = np.unravel_index(i, cov.shape)
    return (float(cov[iy, ix, ir]), int(x0s[0, ix]), int(y0s[iy, 0]), radii[ir])


def _best_circle_loop(red, cx, cy, r_min, r_max):
    """The reference `_best_circle`. Only `--self-test` should call this."""
    h, w = red.shape
    best = None
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            y0, x0 = int(round(cy + dy)), int(round(cx + dx))
            for r in range(r_min, r_max + 1):
                pts, _ = _offsets(r)
                xs, ys = x0 + pts[:, 0], y0 + pts[:, 1]
                ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
                if ok.sum() < len(pts) * 0.75:
                    continue
                cov = float(red[ys[ok], xs[ok]].mean())
                if best is None or cov > best[0]:
                    best = (cov, x0, y0, r)
    return best


def _reach(red, cx, cy, r):
    """How far past `r` the key reaches, per angle. ONE ray march, two readers.

    `_facing` and `_lobe` each computed this identically and independently --
    the same 32 angles, the same radii, the same test -- which is a duplicated
    definition of the sort this repo has paid for elsewhere. They now share it.
    """
    h, w = red.shape
    reach = np.zeros(N_FACE)
    for k, th in enumerate(_FACE_TH):
        dx, dy = np.cos(th), np.sin(th)
        for rr in np.arange(r + 1, r * 1.9, 0.7):
            x, y = int(round(cx + dx * rr)), int(round(cy + dy * rr))
            if not (0 <= x < w and 0 <= y < h):
                break
            if red[y, x]:
                reach[k] = rr - r
    return reach


def fit_ring(red, grey, cx, cy, r_min: int = None, r_max: int = None):
    """Best (coverage, cx, cy, r, interior stats) over centres and radii.

    Coverage is the share of the circle's circumference that is red. A whole
    icon scores high even with the arc broken in several places, which is the
    entire point -- unlike a hole test, it does not care whether the breaks
    happen to disconnect the ring.

    `red` is any binary ring mask, not necessarily the enemy red: the self key
    works here unchanged, which is what `self_agent.py` uses it for, and the
    ALLY key works here too, which is what `icons` uses it for. `r_min` and
    `r_max` default to the measured enlarged-widget pair and must be scaled by
    the caller for the small widget.
    """
    r_min = R_MIN if r_min is None else r_min
    r_max = R_MAX if r_max is None else r_max
    h, w = red.shape
    best = _best_circle(red, cx, cy, r_min, r_max)
    if best is None:
        return None
    cov, x0, y0, r = best
    _, d = _offsets(r)
    xs, ys = x0 + d[:, 0], y0 + d[:, 1]
    ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
    if not ok.any():
        return None
    inner_red = float(red[ys[ok], xs[ok]].mean())
    inner_v = float(grey[ys[ok], xs[ok]].mean())
    reach = _reach(red, x0, y0, r)
    return {"cov": cov, "cx": x0, "cy": y0, "r": r,
            "inner_red": inner_red, "inner_v": inner_v,
            "facing": _facing_from(reach, r),
            "lobe": _lobe_from(reach, r)}


def _lobe_from(reach, r):
    """How far the largest lobe reaches past the ring, as a fraction of r.

    Reported separately from `facing` because it answers a different question:
    `facing` is WHERE the triangle points, `lobe` is WHETHER there is one. A
    Cypher cam is a perfect circle, so a lobe near zero is evidence against a
    player independent of any rotation measurement.
    """
    return float(reach.max() / r) if r else 0.0


def _lobe(red, cx, cy, r):
    """`_lobe_from` over a freshly marched `reach`. See `_reach`."""
    return _lobe_from(_reach(red, cx, cy, r), r)


# Minimum lobe height, as a fraction of the fitted radius, for a facing to be
# reported at all. Below this the "triangle" is ring roughness and the angle it
# produces is noise -- which matters because a Cypher cam is a PERFECT CIRCLE and
# would otherwise yield a confident, meaningless bearing.
LOBE_MIN_FRAC = 0.22


def _facing(red, cx, cy, r):
    """`_facing_from` over a freshly marched `reach`. See `_reach`."""
    return _facing_from(_reach(red, cx, cy, r), r)


def _facing_from(reach, r):
    """Bearing of the facing triangle, or None if no real lobe stands out.

    correcting an earlier claim of mine that a placed ability never
    turns: **a Cypher cam rotates.** It is a perfect circle that never
    translates, and it is the only other moving icon on the widget -- its
    rotation is shown by the camera glyph turning INSIDE the ring, with no lobe
    at all.

    Two consequences, pulling opposite ways:

    * a cam's real rotation is INVISIBLE to this function, because this reads
      the lobe and a cam has none. So rotation measured here cannot be trusted
      to reject a cam -- any value it returns for one is ring roughness. The
      discriminator that does hold against a cam is TRANSLATION;
    * but the absence of a lobe is itself a positive discriminator: a player
      icon has a triangle and a cam does not.

    So `LOBE_MIN_FRAC` is load-bearing, not cosmetic. Without it a perfect
    circle yields a confident bearing from noise, and the motion filter's
    rotation branch would pass exactly the object it most needs to reject.

    Read by rays rather than from the blob's shape: the triangle is the only
    part of the icon outside the fitted circle, so "how far past r does red
    reach at this angle" isolates it without needing the ring to be connected
    to it.
    """
    if reach.max() < LOBE_MIN_FRAC * r:
        return None
    # Weighted mean over the contiguous peak, so the answer is not quantised to
    # one of 32 bins -- rotation is the signal, and a bin width of 11 degrees
    # would swallow most of it.
    k = int(np.argmax(reach))
    ws, xs_, ys_ = 0.0, 0.0, 0.0
    for d in (-2, -1, 0, 1, 2):
        kk = (k + d) % N_FACE
        wgt = reach[kk]
        if wgt <= 0:
            continue
        ws += wgt
        xs_ += wgt * np.cos(_FACE_TH[kk])
        ys_ += wgt * np.sin(_FACE_TH[kk])
    if ws == 0:
        return None
    return float(np.degrees(np.arctan2(ys_, xs_)))


def _rings(mask: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    # AREA scales as the SQUARE of the linear scale; the closing kernel is a
    # length and scales linearly. Getting those two the same way round is the
    # whole content of this change.
    sc = widget_scale(mask.shape[1])
    m = cv2.morphologyEx((mask & floor).astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((_odd(3 * sc), _odd(3 * sc)), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    min_area = max(4, int(round(MIN_ICON_AREA * sc * sc)))
    return [(int(st[i, 4]), float(cen[i][0]), float(cen[i][1]))
            for i in range(1, n) if st[i, 4] >= min_area]


def self_mask(crop: np.ndarray) -> np.ndarray:
    """The local player's yellow key. One definition, two consumers."""
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    return ((g > SELF_G_MIN) & (r > SELF_R_MIN) & ((g - b) > SELF_B_UNDER_G))


def ally_mask(crop: np.ndarray) -> np.ndarray:
    """The teammate teal key. Note it is ONE key for all four allies -- the
    game does not colour teammates individually, so identity can never come
    from colour here and has to come from tracking. See `track.assign`.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))
    return ((hh > ALLY_H[0]) & (hh < ALLY_H[1])
            & (ss > ALLY_S_MIN) & (vv > ALLY_V_MIN))


def self_rings(crop: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    return _rings(self_mask(crop), floor)


def ally_rings(crop: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    return _rings(ally_mask(crop), floor)


# ------------------------------------------------------- icons, not just blobs
# A BLOB of the right colour is not an icon, and on the ally key the gap between
# those two is enormous. Measured by eye on a06f04a0059f: at 32:45 every
# teammate is dead -- four blue X marks on the widget, zero living allies -- and
# `l1/minimap` records `n_allies = 4`. At 4:59 exactly one ally is alive and it
# records 4 again. Three false-positive classes are confirmed by rendering:
# the teal SPAWN BARRIERS drawn across doorways in buy phase, the blue X marks
# a teammate death leaves, and green scenery reaching the key through the
# semi-transparent widget.
#
# So the ally channel cannot feed a vision cone as blobs. What promotes a blob
# to an icon is the same structure `fit_ring` was built to read on the enemy:
#
#   cov     the fitted circle's circumference is covered by the key. A barrier
#           is a rectangle and a stray scenery patch is neither
#   inner   the interior is NOT the key colour, because an icon is a coloured
#           surround around a PORTRAIT. This is what rejects a solid teal
#           rectangle, which scores well on coverage precisely by being solid
#   facing  the key reaches past the circle in ONE direction -- the teardrop.
#           `_facing` returns None below LOBE_MIN_FRAC, so a compact glyph with
#           no lobe (a standard ping, which is a cyan blob of icon size and has
#           already been confused with an ally icon 13 times in 31) is refused
#
# **The third gate is the one that makes this worth doing, and it is why the
# ally channel and the cone channel are one problem rather than two:** the test
# for "is this a teammate" and the measurement of "where is that teammate
# looking" are the same computation. Neither is available without the other.
#
# Thresholds are PARAMETERS, not constants baked in, because they were swept on
# one session -- see `prototypes/ally_cone.py`, which is where the numbers below
# come from and where they get re-swept.
# Swept against the ROSTER over 3302 in-round frames of a06f04a0059f
# (`prototypes/ally_cone.py --sweep`), scoring `n_icons` vs `alive_ally - 1`:
#
#     cov>=    exact   mean residual   |residual|<=1
#     raw      50.5%       +0.99            73.1%   <- a phantom teammate/frame
#     0.20     52.6%       +0.24            82.4%
#     0.25     53.0%       -0.15            82.7%   <- shipped
#     0.30     45.1%       -0.70            75.7%   <- the enemy channel's value
#     0.40     27.9%       -1.55            48.6%
#
# 0.25 rather than the enemy ring's 0.30 because it is a DIFFERENT KEY: the
# ally surround is a filled teardrop, not a 1-2 px rim, and it fragments
# differently. Requiring a FACING as well costs 0.6 points of exact agreement,
# which is what makes the bearing very nearly free.
ALLY_COV_MIN = 0.25
ALLY_INNER_MAX = 0.25


def icons(mask: np.ndarray, crop: np.ndarray, floor: np.ndarray, *,
          cov_min: float = ALLY_COV_MIN, inner_max: float = ALLY_INNER_MAX,
          require_facing: bool = True, min_area: int | None = None,
          support: np.ndarray | None = None,
          separation_px: float | None = None) -> list[dict]:
    """Ring-fit every blob of `mask` and keep the ones shaped like an icon.

    Returns a dict per icon: `cx`, `cy`, `r`, `cov`, `inner`, `facing` (degrees
    or None), `lobe`, `area`. Facing is in the same convention as
    `cone.raycast` -- 0 is +x and +90 is DOWN the image -- so it can be handed
    straight to it.

    `require_facing=False` keeps a positionally-good icon whose bearing was
    refused, which is what the interpolation pass needs: a lobe the fit could
    not read is a missing OBSERVATION, not a missing entity, and dropping the
    row entirely would hide the gap from whatever fills it in.

    **`support` is the OPAQUE SLAB, and a blob that never touches it is not an
    icon.** `floor` arrives dilated -- 9 px, so an icon at the slab's edge is
    not clipped -- and that margin lies over the see-through part of the
    widget, where the game world behind it shows through. On Ascent the world
    is a green glass wall, which keys as ally teal: at 299.6 s the ally mask
    holds 7,855 px against 153 a second earlier, and the extra blobs sit
    entirely in the margin. Measured over both contiguous windows, both roles:

        detections with at least one keyed pixel on the slab
          real (adjudicated eligible)    452 / 452
          the quarantined burst            0 /  51

    A total separation, and not a threshold -- the rule is *any* support at
    all, which is the repo's standing constraint that the search happens
    inside the opaque structure. Left out, this is the documented cause of
    reading non-minimap content as icons; `floor_mask`'s own docstring names
    the margin as 90.1% outside the painting on this map.
    """
    sc = widget_scale(crop.shape[1])
    r_min, r_max = max(3, int(round(R_MIN * sc))), max(4, int(round(R_MAX * sc)))
    if min_area is None:
        min_area = max(4, int(round(MIN_ICON_AREA * sc * sc)))
    keyed = mask & floor
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    m = cv2.morphologyEx(keyed.astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((_odd(3 * sc), _odd(3 * sc)), np.uint8))
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, 8)
    supported = None if support is None else set(np.unique(lbl[(m > 0) & support]))
    found: list[dict] = []
    for i in range(1, n):
        if st[i, 4] < min_area:
            continue
        if supported is not None and i not in supported:
            continue
        f = fit_ring(keyed, grey, cen[i][0], cen[i][1], r_min, r_max)
        if f is None:
            continue
        if f["cov"] < cov_min or f["inner_red"] > inner_max:
            continue
        if require_facing and f["facing"] is None:
            continue
        found.append({"cx": float(f["cx"]), "cy": float(f["cy"]), "r": int(f["r"]),
                      "cov": float(f["cov"]), "inner": float(f["inner_red"]),
                      # `inner_v` is the interior's GREY, where `inner` is the
                      # interior's KEYED fraction, and the two answer different
                      # questions. Both the player's icon and the spike glyph
                      # are a keyed annulus around an un-keyed middle -- the
                      # portrait for one, the spike's black circle for the
                      # other -- so `inner` cannot tell them apart and does not
                      # (0.000 against 0.156, both under a 0.25 gate). What
                      # differs is what the middle LOOKS like. `fit_ring` has
                      # always computed this and this function dropped it on
                      # the floor, so no caller could ask.
                      "inner_v": float(f["inner_v"]),
                      "facing": f["facing"], "lobe": float(f["lobe"]),
                      "area": int(st[i, 4])})
    # Fragments of one broken surround fit the SAME icon, and the widget cannot
    # draw two icons closer than one across -- so anything inside
    # `MIN_ICON_SEPARATION_PX` is one of them, and the fit KEPT is the one with
    # the best arc coverage rather than whichever component came first. This
    # rule was here at 8 px, which is under the 8.1-9.1 px the duplicate pairs
    # actually sit at, so every one of them leaked through as a second
    # teammate; the constant is shared now rather than restated.
    #
    # `separation_px=0` keeps every fragment instead, which is what a joint
    # appearance fit wants: the survivor here is the best ARC, and on a broken
    # self ring that is not always the fragment nearest the true centre. A
    # caller asking for PROPOSALS to score is not asking how many icons there
    # are, so it must be able to decline the answer this rule gives.
    sep = MIN_ICON_SEPARATION_PX * sc if separation_px is None else float(separation_px)
    if sep <= 0:
        return sorted(found, key=lambda d: -d["cov"])
    out: list[dict] = []
    for f in sorted(found, key=lambda d: -d["cov"]):
        if any(np.hypot(f["cx"] - o["cx"], f["cy"] - o["cy"]) < sep for o in out):
            continue
        out.append(f)
    return out


def ally_icons(crop: np.ndarray, floor: np.ndarray, **kw) -> list[dict]:
    """Teammate icons, each carrying its own bearing. See `icons`."""
    return icons(ally_mask(crop), crop, floor, **kw)


def art_floor(shade_kind: np.ndarray, dilate: float = 1) -> np.ndarray:
    """The map's own footprint, from the OFFICIAL ART. Prefer this to `floor_mask`.

    `prototypes/map_shade.py` warps the published minimap art into the widget's
    pixels and stores the result in the geometry npz, so `shade_kind > 0` is the
    map's drawn footprint with no fitting at read time. The art's alpha channel
    is exactly binary, so the boundary is STATED rather than thresholded.

    **Scored on the same painted referee `floor_mask` is arbitrated against**
    (`prototypes/floor_mask_eval.py`, both unseeded paintings):

        session                 area   recall    prec     IoU
        Ascent  derived        37.8%   100.0%   78.8%   78.8%
                ART            30.4%    97.2%   95.2%   92.7%
        Lotus   derived        40.1%   100.0%   77.9%   77.9%
                ART            32.8%    99.4%   94.7%   94.2%

    `derived & ART` reproduces ART and `derived | ART` reproduces derived, so
    the derived rule's extra ~7% of the widget is almost all false positive --
    the location-name banner, the widget's circular rim, the 5 px close skirt
    and the churn at barrier doorways, each of which had to be found and
    patched separately while the exact answer sat unused in the same file.

    **This is the SUPPORT mask.** `dilate` defaults to 1 (no dilation) because
    the art boundary needs no overhang: the reason `floor_mask` grew by 9 px
    was to cover a boundary it could not place. A caller wanting the SEARCH
    area still dilates, so an icon centred at the map's edge is not clipped --
    and at `dilate=9` the art scores 79.6% / 78.3%, i.e. the search area does
    not move. What moves is the test a detection must PASS.

    The promotion is `BACKLOG.md`'s, recorded 2026-09-06: geometry comes from
    the art, photometry (`static`, `lo_gray`, `hi_gray`, `sd_lo`, `sd_hi`)
    cannot, because the widget is semi-transparent over live world and the
    whole point of those is to difference against these pixels.
    """
    m = (shade_kind > 0).astype(np.uint8)
    d = int(round(dilate))
    if d > 1:
        d = _odd(d)
        m = cv2.dilate(m, np.ones((d, d), np.uint8))
    return m > 0


def slab_mask(med: np.ndarray, sd: np.ndarray | None = None) -> np.ndarray:
    """The opaque slab with no overhang margin -- `icons`' `support`.

    Named rather than written as `floor_mask(med, dilate=1)` at each call site,
    because what it means (*the structure a detection must be supported by*) is
    not obvious from the argument. `sd` carries through for the same reason it
    exists there: this is the mask a detection must be SUPPORTED by, so widget
    furniture inside it is licence for a phantom, not merely extra area.
    """
    return floor_mask(med, dilate=1, sd=sd)


def self_icons(crop: np.ndarray, floor: np.ndarray, **kw) -> list[dict]:
    """The local player's icon. There is at most one, and the entity model
    says its ABSENCE with the widget drawn is a detection failure rather than
    information -- so a caller wanting a single answer should take the best
    by coverage rather than treating an empty list as "not there".
    """
    return icons(self_mask(crop), crop, floor, **kw)


def pick_self(cands: list[tuple[float, float, float] | dict],
              prev: tuple[float, float] | None,
              dt_ms: float, scale: float = 1.0) -> tuple[float, float] | None:
    """Pick a fitted icon or legacy blob without changing its centre estimator.

    A fitted-icon dict is ranked by arc coverage and supplies its fitted
    ``cx, cy``. A legacy ``(area, cx, cy)`` tuple is ranked by area. Accepting
    both keeps stored-data experiments and older prototype callers working;
    the shipped reader supplies only fitted icons and never falls back to blob
    centroids.

    Nearest-to-previous is what gives this a track rather than a per-frame
    guess: it is what survives a frame where an ally or a wall boundary also
    passes the colour test, as long as the real self-ring is still closest to
    where it was a moment ago.

    `dt_ms` is the time since `prev` was READ, not the sampler's nominal
    period. They differ whenever a frame is dropped, the capture stalls, or the
    widget is not drawn -- and the nominal period says the player had 1/60 s to
    move when they in fact had five seconds behind a death screen.

    **The gate is floored at the fit error, and that is the whole point of it
    being a floor.** `RUN_PX * scale * dt * 2` is how far a player can run in
    the elapsed time, which at 60 Hz is 1.50 px -- below the icon fit's own
    p90 of ~1.5 px, so the gate refused the player's own icon and the pick fell
    through to the largest blob. Over the frozen P3 windows that abandoned the
    track on 9.4% of consecutive steps at 60 Hz against 1.9% at 2 Hz: the
    highest rate scored WORST, which no rate-selection gate can be built on. A
    step has fit error at both ends, so the floor is the pair budget `2e` --
    the same 4 px `minimap_lifecycle` spends, and the same reasoning.

    Past `GAP_MS` the previous point constrains nothing -- a player crosses the
    whole widget in a second -- so it is dropped rather than used with a gate
    so wide it admits everything.
    """
    if not cands:
        return None
    norm = [(float(c["cov"]), float(c["cx"]), float(c["cy"]))
            if isinstance(c, dict)
            else (float(c[0]), float(c[1]), float(c[2]))
            for c in cands]
    if prev is not None and dt_ms <= GAP_MS:
        # RUN_PX is widget px/s, so the gate scales with the widget. `scale`
        # defaults to 1.0 rather than being derived, because this is the one
        # function here that is handed candidates instead of a crop -- the
        # caller has the width and passes it.
        lim = max(2.0 * FIT_ERR_PX * scale,
                  RUN_PX * scale * (dt_ms / 1000.0) * 2.0)
        near = [c for c in norm if np.hypot(c[1] - prev[0], c[2] - prev[1]) <= lim]
        if near:
            return max(near, key=lambda c: c[0])[1:]
    return max(norm, key=lambda c: c[0])[1:]


def crosses(instants: list[float], t0: float, t1: float) -> bool:
    """Does a listed instant fall strictly inside `(t0, t1)`.

    `instants` must be sorted. Shared with `belief.resolve`, which asks it of
    widget-absent instants and of round boundaries alike.
    """
    i = int(np.searchsorted(instants, t0, side="right"))
    return i < len(instants) and instants[i] < t1


def admit_steps(found: list[tuple[float, float, float]], scale: float,
                motion) -> tuple[list, set[int], list[float]]:
    """Keep the physically reachable steps. See `filter_track` for the law.

    Public because `belief.resolve` reads the same answer: the filtered track
    and the model's belief must not disagree about which observations the
    motion law admitted.
    """
    holes = sorted(p[0] for p in found if p[1] is None or p[2] is None)
    found = [p for p in found if p[1] is not None and p[2] is not None]

    # Deferred: `track` imports RUN_PX from here, so a module-level import
    # would be circular. Nothing is imported at all on the default path.
    mot, spans = None, None
    evidence = None
    if motion is not None:
        from . import track as _track

        def _ev(e):
            # A stored event row is a dict; anything else is already a
            # `track.Corroboration`. Keyed on the dict rather than on the
            # class because `python -m reticle.track --self-test` runs this
            # module's `track` and its own `__main__` copy side by side.
            return _track.Corroboration.of(e) if isinstance(e, dict) else e

        if isinstance(motion, (list, tuple)):
            spans = [(float(s[0]), float(s[1]),
                      s[2] if isinstance(s[2], _track.Motion) else _track.CLASSES[s[2]],
                      _ev(s[3] if len(s) > 3 else None))
                     for s in motion]
        elif isinstance(motion, _track.Motion):
            mot = motion
        else:
            mot = _track.CLASSES[motion]

    def law(t_ms):
        """The class and evidence governing a step arriving at `t_ms`.

        `(None, None)` means no class was selected here, so the fixed gate
        applies.
        """
        if spans is None:
            return mot, evidence
        for t0, t1, m, ev in spans:
            if t0 <= t_ms <= t1:
                return m, ev
        return None, None

    keep: list = []
    jumps: set[int] = set()          # keep[i] -> keep[i+1] is a legal teleport
    for p in found:
        if keep:
            dt = (p[0] - keep[-1][0]) / 1000.0
            dist = float(np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]))
            m, ev = law(p[0])
            if m is None:
                if dt > 0 and dist / dt > RUN_PX * scale * 1.6:
                    continue
            else:
                from . import track as _track
                ok, why = _track.admits(m, dist, dt, scale, evidence=ev)
                if not ok:
                    continue
                if _track.is_teleport(why):
                    jumps.add(len(keep) - 1)
        keep.append(p)
    return keep, jumps, holes


def filter_track(found: list[tuple[float, float, float]],
                  step_ms: float, scale: float = 1.0,
                  motion=None) -> list[tuple[float, float, float]]:
    """Drop impossible steps, then interpolate the short gaps they leave.

    **`motion` selects the law**, and takes three shapes:

        None                        the fixed `RUN_PX * 1.6` gate, unchanged
        "walker_teleport"           `track.admits` for the WHOLE track
        [(t0, t1, "walker_teleport"), ...]   that class inside each span in
                                    ms, the default gate everywhere else
        [(t0, t1, "walker_teleport", corroboration), ...]   the same, with the
                                    evidence licensing a discontinuity inside
                                    that span -- a `track.Corroboration`, or a
                                    stored origin event dict

    **The fourth element is what makes a real teleport survive.** Without it a
    jump is only admitted past `track.TELEPORT_PX`, and the measured teleports
    are 4.6-65 px, so the branch almost never fires on the events it is for
    (`prototypes/cast_motion.py`, and the reviewed ~52 px Lotus relocation).
    A cast selects the CLASS; the corroboration -- icon and viewcone relocated,
    tied to a predecessor by audio or an observed destination -- is what
    licenses the jump itself.

    The third is the one to reach for, and the measurement says why. Applying a
    class to a whole session is net **+835 observations and NEGATIVE on three
    of five sessions** (`jump_census.py --motion`), because `admits` gives up
    this gate's 1.6x slack everywhere to buy jumps in a few places. A span is
    how the permissiveness gets spent only where something licensed it -- a
    cast on the ability tray, which `prototypes/cast_motion.py` reads.

    Spans need not be sorted and may overlap; the first one containing the
    step's arrival time wins.

    Why the parameter exists, from `prototypes/jump_census.py` over 102,239
    steps: of the 11,599 observations the fixed gate drops, **54.7% sit at
    teleport distance** from the last kept point. A fixed threshold cannot
    separate a teleport from a phantom, and a refusal here is a HARD BREAK, so
    a destroyed teleport does not lose one point -- it ends the run and starts
    another, which is the identity discontinuity tracking exists to avoid.

    **A teleport is kept but never interpolated across.** It is a legal
    discontinuity, so inventing a path through it would be `GAP_MS`
    interpolation drawing the player walking a route they did not walk -- the
    same fault the widget-absent hole break was added for, and *never guess a
    value* says the same thing about both.

    Two things the caller should know before opting in:

    * **`admits` is STRICTER than the default for a plain walker.** The gate
      here carries a 1.6x slack that the law does not; `admits` allows
      `RUN_PX * dt` exactly. So `motion="walker"` is not today's behaviour
      written a second way, and the difference is measurable rather than
      assumed -- `jump_census.py --motion` reports it;
    * **a step admitted only because the class MAY DASH is WEAK.** `DASH_PX_S`
      is a bound, not a measurement -- there is no bimodality in the speed
      distribution to put a threshold in -- so `motion="walker_dash"` admits
      steps on an unvalidated ceiling. That is the caller's assertion, not this
      function's finding.

    Pure function of the raw (t_ms, x, y) stream -- callers can run this
    on-demand over stored L1 without touching video, the same way `segment`
    recomputes spans from L1. Filtering is not stored: it is cheap, and
    storing raw reads lets a later change to RUN_PX or GAP_MS be replayed
    without a re-decode.

    **Pass `(t, None, None)` for a frame where the widget was not drawn, and
    this will not interpolate across it.** That is what the NULL rows in
    `l1/minimap` are for, and until 2026-09-05 the only caller stripped them
    before calling -- so `cmd_minimap`'s own comment ("the track keeps its time
    axis and gap interpolation sees the hole for what it is") described
    behaviour the code did not have. A hole and a detection miss arrived here
    as the same thing: an absent timestamp. With `GAP_MS = 1000` that is up to
    **fourteen invented positions** across a one-second map glance at 15 Hz,
    indistinguishable in the output from measured ones -- *never guess a value*
    violated in the module that had just been fixed for the same class of
    fault.

    A refusal is a HARD BREAK: the run ends and a new one begins after it.
    Interpolating a gap the widget was absent for would be inventing a path
    through the only frames that state outright that nobody was looking.
    """
    keep, jumps, holes = admit_steps(found, scale, motion)

    def spans_hole(t0: float, t1: float) -> bool:
        return crosses(holes, t0, t1)

    out = []
    for i, (a, b) in enumerate(zip(keep, keep[1:])):
        out.append(a)
        gap = b[0] - a[0]
        if (step_ms < gap <= GAP_MS and not spans_hole(a[0], b[0])
                and i not in jumps):
            k = int(round(gap / step_ms)) - 1
            for j in range(1, k + 1):
                f = j / (k + 1)
                out.append((a[0] + gap * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
    if keep:
        out.append(keep[-1])
    return out
