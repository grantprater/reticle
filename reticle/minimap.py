"""Stage 02: player position off the minimap.

Promoted from `prototypes/minimap_position.py` on 2026-09-02, after two
independent ground-truth checks -- the blue X a death leaves (`xmark_eval.py`,
against scoreboard-verified killfeed deaths) and the map's physical
chokepoints (`chokepoint_eval.py`, against location-banner transitions) --
both landed within ~1-1.5m of ground truth across Ascent, Lotus and Haven.
See `prototypes/CLAUDE.md` for the full arc, including five rejected
approaches: every content-based method drowned in the world moving behind the
minimap's semi-transparent void. Masking to the opaque floor slab is the fix,
and it is the whole reason this module exists in this shape.

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
# The pale yellow-green the game rings the local player with -- the same
# colour scoreboard.py keys the player's own row on, and it transfers
# unchanged.
SELF_G_MIN, SELF_R_MIN, SELF_B_UNDER_G = 200, 140, 45
ALLY_H, ALLY_S_MIN, ALLY_V_MIN = (75, 100), 90, 140
MIN_ICON_AREA = 10
MAX_ALLIES = 4  # a 5-stack has at most four teammates to show


def minimap_roi_px(profile: Profile, w: int, h: int) -> tuple[int, int, int, int]:
    return next(r for r in profile.rois if r.name == "minimap").pixels(w, h)


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


def static_map(cap, fps: float, spans: list[tuple[float, float]],
                box: tuple[int, int, int, int], n: int = 120) -> np.ndarray:
    """The map with every icon removed, sampled off active spans."""
    x0, y0, x1, y1 = box
    total = sum(b - a for a, b in spans)
    stride = total / n if total > 0 else 1.0
    frames = []
    for a, b in spans:
        t = a
        while t < b:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
            ok, fr = cap.read()
            if ok:
                frames.append(fr[y0:y1, x0:x1])
            t += stride
    if not frames:
        raise SystemExit("no active-span frames decoded -- cannot build a static map")
    return median_widget(frames)


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
#: **A site is FLOOR.** the player, 2026-09-06, on a version of `floor_mask` that had
#: just started excluding them: *why would floor mask exclude bomb sites? Those
#: are part of the floor.* Exactly right, and it names the error: the tint is
#: PAINT ON the floor, a rendering property, not a different surface. Measured
#: consequence of getting it wrong -- 9.6% of stored self positions and 4.4-6.7%
#: of ally positions on `a06f04a0059f` sit inside a site, so a slab-only mask
#: blinds the position reader on exactly the ground a round is decided on.
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


def floor_mask(med: np.ndarray, dilate: float = 9) -> np.ndarray:
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
    for i in range(1, n):
        if i != big_id and (lbl == i)[near].any():
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
    min_area = SITE_MIN_AREA * scale * scale
    for i in range(1, n):
        comp = lbl == i
        if st[i, 4] >= min_area and (comp & near).any():
            out |= comp
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
      round, as often as he presses it.

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


def self_rings(crop: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    return _rings((g > SELF_G_MIN) & (r > SELF_R_MIN)
                  & ((g - b) > SELF_B_UNDER_G), floor)


def ally_rings(crop: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))
    return _rings((hh > ALLY_H[0]) & (hh < ALLY_H[1])
                  & (ss > ALLY_S_MIN) & (vv > ALLY_V_MIN), floor)


def pick_self(cands: list[tuple[int, float, float]],
              prev: tuple[float, float] | None,
              step_ms: float, scale: float = 1.0) -> tuple[float, float] | None:
    """Nearest-to-previous when there is a previous point, else largest blob.

    Nearest-to-previous is what gives this a track rather than a per-frame
    guess: it is what survives a frame where an ally or a wall boundary also
    passes the colour test, as long as the real self-ring is still closest to
    where it was a moment ago.
    """
    if not cands:
        return None
    if prev is not None:
        # RUN_PX is widget px/s, so the gate scales with the widget. `scale`
        # defaults to 1.0 rather than being derived, because this is the one
        # function here that is handed candidates instead of a crop -- the
        # caller has the width and passes it.
        lim = RUN_PX * scale * (step_ms / 1000.0) * 2.0
        near = [c for c in cands if np.hypot(c[1] - prev[0], c[2] - prev[1]) <= lim]
        if near:
            return max(near, key=lambda c: c[0])[1:]
    return max(cands, key=lambda c: c[0])[1:]


def filter_track(found: list[tuple[float, float, float]],
                  step_ms: float, scale: float = 1.0,
                  motion=None) -> list[tuple[float, float, float]]:
    """Drop impossible steps, then interpolate the short gaps they leave.

    **`motion` selects the law.** `None` -- the default -- keeps the fixed
    `RUN_PX * 1.6` gate this has always used, so no stored number moves until a
    caller opts in. Pass a `track.CLASSES` key (or a `track.Motion`) and the
    gate becomes `track.admits`, which is per-identity: a teleport is legal for
    Omen, Chamber, Veto, Waylay and Yoru and for nobody else.

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
    holes = sorted(p[0] for p in found if p[1] is None or p[2] is None)
    found = [p for p in found if p[1] is not None and p[2] is not None]

    def spans_hole(t0: float, t1: float) -> bool:
        i = int(np.searchsorted(holes, t0, side="right"))
        return i < len(holes) and holes[i] < t1

    # Deferred: `track` imports RUN_PX from here, so a module-level import
    # would be circular. Nothing is imported at all on the default path.
    mot = None
    if motion is not None:
        from . import track as _track
        mot = motion if isinstance(motion, _track.Motion) else _track.CLASSES[motion]

    keep: list = []
    jumps: set[int] = set()          # keep[i] -> keep[i+1] is a legal teleport
    for p in found:
        if keep:
            dt = (p[0] - keep[-1][0]) / 1000.0
            dist = float(np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]))
            if mot is None:
                if dt > 0 and dist / dt > RUN_PX * scale * 1.6:
                    continue
            else:
                from . import track as _track
                ok, why = _track.admits(mot, dist, dt, scale)
                if not ok:
                    continue
                if why == "teleport":
                    jumps.add(len(keep) - 1)
        keep.append(p)
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
