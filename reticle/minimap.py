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

# Top speed of a real track, px/s, measured rather than derived: every
# filtered track sits under it and every misdetection blew far past it.
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
    return cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0


def _rings(mask: np.ndarray, floor: np.ndarray) -> list[tuple[int, float, float]]:
    m = cv2.morphologyEx((mask & floor).astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((3, 3), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    return [(int(st[i, 4]), float(cen[i][0]), float(cen[i][1]))
            for i in range(1, n) if st[i, 4] >= MIN_ICON_AREA]


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
              step_ms: float) -> tuple[float, float] | None:
    """Nearest-to-previous when there is a previous point, else largest blob.

    Nearest-to-previous is what gives this a track rather than a per-frame
    guess: it is what survives a frame where an ally or a wall boundary also
    passes the colour test, as long as the real self-ring is still closest to
    where it was a moment ago.
    """
    if not cands:
        return None
    if prev is not None:
        lim = RUN_PX * (step_ms / 1000.0) * 2.0
        near = [c for c in cands if np.hypot(c[1] - prev[0], c[2] - prev[1]) <= lim]
        if near:
            return max(near, key=lambda c: c[0])[1:]
    return max(cands, key=lambda c: c[0])[1:]


def filter_track(found: list[tuple[float, float, float]],
                  step_ms: float) -> list[tuple[float, float, float]]:
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
            if dt > 0 and np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]) / dt > RUN_PX * 1.6:
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
