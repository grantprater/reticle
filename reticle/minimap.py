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


def static_map(cap, fps: float, spans: list[tuple[float, float]],
                box: tuple[int, int, int, int], n: int = 120) -> np.ndarray:
    """The map with every icon removed, as a per-pixel median."""
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
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def floor_mask(med: np.ndarray) -> np.ndarray:
    """The opaque walkable slab. Everything else is see-through and churns."""
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 110)
    # The 9 px dilation is a LENGTH -- it exists so a ring overhanging the slab
    # edge is still scored -- so it scales linearly. Left fixed it would close
    # proportionally wider cracks on a smaller widget and quietly admit void.
    k = _odd(9 * widget_scale(med.shape[1]))
    return cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


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
                  step_ms: float, scale: float = 1.0) -> list[tuple[float, float, float]]:
    """Drop impossible steps, then interpolate the short gaps they leave.

    Pure function of the raw (t_ms, x, y) stream -- callers can run this
    on-demand over stored L1 without touching video, the same way `segment`
    recomputes spans from L1. Filtering is not stored: it is cheap, and
    storing raw reads lets a later change to RUN_PX or GAP_MS be replayed
    without a re-decode.
    """
    keep = []
    for p in found:
        if keep:
            dt = (p[0] - keep[-1][0]) / 1000.0
            if dt > 0 and (np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]) / dt
                           > RUN_PX * scale * 1.6):
                continue
        keep.append(p)
    out = []
    for a, b in zip(keep, keep[1:]):
        out.append(a)
        gap = b[0] - a[0]
        if step_ms < gap <= GAP_MS:
            k = int(round(gap / step_ms)) - 1
            for j in range(1, k + 1):
                f = j / (k + 1)
                out.append((a[0] + gap * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
    if keep:
        out.append(keep[-1])
    return out
