r"""Fit the minimap shape of an ability whose drawn form is known.

    .\.venv\Scripts\python.exe -m reticle ability-shapes <session>

Owns [owns:ability-shape].

What is drawn. Three abilities draw a fixed parametric shape in the ally teal:
Skye's Regrowth a ring round Skye [domain:abilities/skye-regrowth-minimap-ring],
Sova's Recon Bolt a ring round where the bolt lands
[domain:abilities/sova-recon-bolt-minimap-ring], and Hunter's Fury a straight
line from Sova while the ultimate is up
[domain:abilities/sova-hunters-fury-minimap-beam]. The
player traced all three in the tray-object pass (`label_tray_objects.py`).

The models. Both come from prototypes that fitted them on demo video:
`prototypes/entity_mining_statistical.py` searched a circle round a seed and
`prototypes/beam_mining_statistical.py` swept a beam's angle round the caster.
Here they read one minimap crop, and `prototypes/ability_shape_eval.py` scores
them against the player's marks.

- colour: the beam prototype's teal, hue 75-105 and saturation >= 70 (OpenCV
  scale), weighted by value. The icon key `minimap.ally_mask` (saturation > 90,
  value > 140) loses the translucent rings: it finds Regrowth on
  [metric:ability_shapes/marks@tray-object-marks#ally_mask_regrowth_found=4] of
  16 marked panels.
- ring: the centre and radius that maximise mean teal on a 3 px annulus minus
  the brighter of the bands 3-6 px inside and outside it, for radii between
  0.1R and 0.45R of the widget radius R. Taking the brighter band rejects a
  filled disc's edge and an icon's small ring.
- beam: from an origin, the angle that maximises mean teal in a strip minus a
  collar either side, with the prototype's lengths rescaled by R (strip
  half-width and collar 0.037R each, reach 1.116R, the first 15 px skipped for
  the caster's icon). The beam ends where the strip's teal falls below half its
  peak.
- the map: teal counts over the whole widget, because the shapes are drawn
  over the void too (a Regrowth ring half off the map at `b7d24102a6f6`
  1726.0 s). Masking the void cost the rings their outside band, which is what
  rejects a cluster of teal icons at the map's edge. The map's art footprint
  (`geometry.footprint`, grown SUPPORT_DILATE px) instead places a beam: at
  least BEAM_ON_MAP of its drawn run lies on it, because Sova fires across the
  map, while straight teal scenery seen through the widget lies in the void.
  The marked blasts lie 0.60-1.00 on it and three scenery lines 0.00-0.17, so
  the fraction is fitted to them.

The prior, then the surprise. Regrowth and Hunter's Fury start at the caster,
so their search starts at the seed the caller gives (the stored self
position): a ring centre within 0.1R of it, a beam from it. Where that fit
scores below its acceptance, or there is no seed, the search widens to the
whole widget (every ring centre; the longest straight teal segment on the map
for a beam) and the result says `path="widened"`, keeping the seeded score beside it. A
Recon Bolt lands wherever it flies, so its ring is searched over the whole
widget from the start. The stored self position can sit on another icon
(`3694746e4e54` 1609.5 s), and a beam's origin that disagrees with it is a
witness against it.

Acceptance, from a null sample: 130 live-phase crops of the Sova and Skye
sessions at least 10 s from the player's casts (`ability_shape_eval.py
--null`). A beam is found at 0.23, the null's maximum
[metric:ability_shapes/null@sova-skye-null#beam_max=0.228] rounded up; the
prototype's 0.35 missed 9 of 21 marked blasts. A ring is found at 0.2, set
between the first run's pre-cast and post-cast panels; every null ring stayed
below [metric:ability_shapes/null@sova-skye-null#ring_max_other=0.182] except
two genuine Recon Bolt rings of casts the tray gate missed. On the player's
marks this finds
[metric:ability_shapes/marks@tray-object-marks#fury_found=21] of 21 blasts,
[metric:ability_shapes/marks@tray-object-marks#regrowth_found=14] of 16
Regrowth and [metric:ability_shapes/marks@tray-object-marks#recon_found=8] of
8 Recon Bolt panels, and [metric:ability_shapes/marks@tray-object-marks#pre_found=0]
of the 10 panels a second before the cast. A blast's angle is within 3 deg of
the marks on [metric:ability_shapes/marks@tray-object-marks#fury_angle_3deg=19]
of 21, within 4.1 deg on [metric:ability_shapes/marks@tray-object-marks#fury_angle_4deg=19]; a seeded blast starts at the stored self position,
the nearest within SEED_TOL_MS of the crop. The
marks are a centre and angle truth, not a radius truth: the player traced the
ring's inner edge, 0-15 px inside it.

On every session the stored rows at the marks reproduce these counts. The Fury
line shows on [metric:ability_shapes/production@all-sessions#fury_found=220]
of [metric:ability_shapes/production@all-sessions#fury_crops=221] crops after the ult's drop, turning between crops, so a found beam dates
the ult, not a blast.

Not for. Naming the caster (`ability-owner` is unowned); deciding onset or
expiry (each call reads one crop); telling a blast from the line between
blasts; choosing when to look. The command looks
after the player's casts, the stored `tray_drop` rows that
`ability_timeline.player_tray_casts` passes when the command asks it, for the
agent the arbiter names in the player's slot.
"""
from __future__ import annotations

import cv2
import numpy as np

from .version import ABILITY_SHAPE_VERSION

#: How far, in ms, a seed may be taken from a stored self position. The
#: refreshed self track (`minimap-0.7.0`, 2026-09-27) stores single-frame
#: gaps: on the shape crops of 13 sessions the nearest row within 100 ms had
#: no position on a third of them while a row beside it did (the median null
#: run is one row at 15 Hz). The track runs at most `minimap.RUN_PX` widget
#: px/s, so a seed a quarter second off errs by about 11 px, inside the
#: seeded ring's 0.1R search.
SEED_TOL_MS = 250.0

#: The shape each ability draws, and where its search starts.
SHAPES = {"Regrowth": ("ring", "caster"),
          "Recon Bolt": ("ring", "free"),
          "Hunter's Fury": ("beam", "caster")}
ACCEPT = {"ring": 0.2, "beam": 0.23}
TEAL_H, TEAL_S_MIN = (75, 105), 70
#: Ring radii and the seeded centre window, as fractions of the widget radius.
RING_R, RING_SEED_HALF = (0.1, 0.45), 0.1
#: Beam geometry, as fractions of the widget radius, and the icon cut in px.
BEAM_HALF, BEAM_COLLAR, BEAM_REACH, BEAM_NEAR_PX = 0.037, 0.037, 1.116, 15.0
#: The widened beam search: teal above this, segments at least this long.
SEGMENT_TEAL, SEGMENT_MIN = 0.35, 0.3
#: The map's art footprint grown by this many px is where a shape may lie
#: (`minimap.art_floor`'s own search dilation).
SUPPORT_DILATE = 9
#: A beam is fired across the map: at least this fraction of its drawn run lies
#: on the support, or it is teal scenery seen through the widget.
BEAM_ON_MAP = 0.35


def seed_from_track(t_ms, sx, sy, t: float,
                    tol_ms: float = SEED_TOL_MS) -> tuple[float, float] | None:
    """The stored self position nearest `t`, or None.

    `t_ms`, `sx`, `sy` are the minimap table's columns. A row without a
    position is skipped and the nearest row that has one within `tol_ms` wins,
    so a single-frame gap in the track leaves no crop unseeded, while a span
    where the reader refused, or nobody was looking, still returns None. Every
    caller that seeds a shape from the track uses this, so the tolerance is
    one number.
    """
    t_ms = np.asarray(t_ms, float)
    if not len(t_ms):
        return None
    dist = np.abs(t_ms - t)
    near = np.flatnonzero(dist <= tol_ms)
    for i in near[np.argsort(dist[near], kind="stable")]:
        if sx[i] is not None and sy[i] is not None:
            return float(sx[i]), float(sy[i])
    return None


def teal(crop: np.ndarray) -> np.ndarray:
    """Per-pixel teal weight in [0, 1]: in hue and saturation, scaled by value."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    return (((h >= TEAL_H[0]) & (h <= TEAL_H[1]) & (s >= TEAL_S_MIN))
            .astype(np.float32) * (v / np.float32(255.0)))


def widget(shape) -> tuple[float, np.ndarray]:
    """The widget radius and its disc, from the crop's size alone."""
    h, w = shape[:2]
    cx, cy, R = (w - 1) / 2.0, (h - 1) / 2.0, min(h, w) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    return R, np.hypot(xx - cx, yy - cy) <= R


# ------------------------------------------------------------------- ring

class _Radial:
    """Half-pixel radial sums round any centre of one crop, padded once."""

    def __init__(self, tl: np.ndarray, mask: np.ndarray, radii: np.ndarray):
        self.W = W = int(np.ceil(radii.max() + 7))
        self.t = np.pad(tl * mask, W)
        self.m = np.pad(mask.astype(np.float32), W)
        yy, xx = np.mgrid[-W:W + 1, -W:W + 1]
        self.d = np.floor(np.hypot(xx, yy) * 2).astype(int).ravel()
        self.n = int(self.d.max()) + 2
        self.radii = radii
        self.i = [np.clip(np.round(a * 2).astype(int), 0, self.n)
                  for a in (radii - 1.5, radii - 6, radii + 3)]
        self.j = [np.clip(np.round(b * 2).astype(int), 0, self.n)
                  for b in (radii + 1.5, radii - 3, radii + 6)]

    def scores(self, x: int, y: int) -> np.ndarray:
        """The ring score at centre (x, y) for every radius."""
        W, n = self.W, self.n
        t = self.t[y:y + 2 * W + 1, x:x + 2 * W + 1].ravel()
        m = self.m[y:y + 2 * W + 1, x:x + 2 * W + 1].ravel()
        T = np.concatenate([[0.0], np.cumsum(np.bincount(self.d, weights=t, minlength=n))])
        M = np.concatenate([[0.0], np.cumsum(np.bincount(self.d, weights=m, minlength=n))])

        def band(k):
            cnt = M[self.j[k]] - M[self.i[k]]
            return np.where(cnt >= 8, (T[self.j[k]] - T[self.i[k]]) / np.maximum(cnt, 1), np.nan)

        out = band(0) - np.fmax(band(1), band(2))
        return np.where(np.isnan(out), -1.0, out)


def fit_ring(tl: np.ndarray, mask: np.ndarray, R: float,
             centre: tuple[float, float] | None = None, half: float | None = None,
             step: int = 1, _radial: _Radial | None = None) -> dict:
    """The best ring, searched round `centre` (within `half`) or everywhere:
    the score is mean teal on the annulus [r-1.5, r+1.5) minus the brighter of
    [r-6, r-3) and [r+3, r+6)."""
    h, w = tl.shape
    rad = _radial or _Radial(tl, mask, np.arange(RING_R[0] * R, RING_R[1] * R + 0.01, 0.5))
    if centre is None:
        xs, ys = range(0, w, step), range(0, h, step)
    else:
        xs = range(max(0, int(centre[0] - half)), min(w, int(centre[0] + half) + 1), step)
        ys = range(max(0, int(centre[1] - half)), min(h, int(centre[1] + half) + 1), step)
    best = (-2.0, None, None, None)
    for x in xs:
        for y in ys:
            if not mask[y, x]:
                continue
            sc = rad.scores(x, y)
            k = int(np.argmax(sc))
            if sc[k] > best[0]:
                best = (float(sc[k]), x, y, float(rad.radii[k]))
    if step > 1 and best[1] is not None:
        return fit_ring(tl, mask, R, (best[1], best[2]), step, 1, rad)
    return {"score": best[0], "cx": best[1], "cy": best[2], "r": best[3]}


# ------------------------------------------------------------------- beam

def _beam(tl, mask, vx, vy, th, R):
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    lp, dp = vx * c + vy * s, np.abs(-vx * s + vy * c)
    hw, col = BEAM_HALF * R, BEAM_COLLAR * R
    along = (lp >= BEAM_NEAR_PX) & (lp <= BEAM_REACH * R) & mask
    strip, collar = along & (dp <= hw), along & (dp > hw) & (dp <= hw + col)
    if strip.sum() < 20 or collar.sum() < 20:
        return -1.0, lp, strip
    return float(tl[strip].mean() - tl[collar].mean()), lp, strip


def fit_beam(tl: np.ndarray, mask: np.ndarray, ox: float, oy: float, R: float,
             around: float | None = None) -> dict:
    """The best beam from (ox, oy): a 2 deg sweep (or 1 deg within 6 deg of
    `around`), refined in 0.2 deg steps. The score is mean teal in the strip
    minus mean teal in the collars either side."""
    h, w = tl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    vx, vy = xx - ox, yy - oy
    grid = (np.arange(0, 360, 2.0) if around is None
            else np.arange(around - 6, around + 6.1, 1.0))
    sc, th = max((_beam(tl, mask, vx, vy, t, R)[0], t) for t in grid)
    for t in np.arange(th - 2.0, th + 2.05, 0.2):
        s2 = _beam(tl, mask, vx, vy, t, R)[0]
        if s2 > sc:
            sc, th = s2, t
    _, lp, strip = _beam(tl, mask, vx, vy, th, R)
    bins = np.floor(lp[strip] / 2.0).astype(int)
    prof = np.bincount(bins, weights=tl[strip]) / np.maximum(np.bincount(bins), 1)
    l0 = l1 = BEAM_NEAR_PX
    on = np.nonzero(prof >= 0.5 * prof.max())[0] if prof.size and prof.max() > 0 else []
    if len(on):
        run = [on[0]]
        for b in on[1:]:
            if b - run[-1] <= 3:
                run.append(b)
            elif len(run) < 5:
                run = [b]
            else:
                break
        l0, l1 = run[0] * 2.0, run[-1] * 2.0 + 2.0
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    return {"score": sc, "theta_deg": float(th % 360),
            "x0": float(ox + l0 * c), "y0": float(oy + l0 * s),
            "x1": float(ox + l1 * c), "y1": float(oy + l1 * s), "length": l1 - l0}


def on_map(f: dict, support: np.ndarray, n: int = 40) -> float:
    """The fraction of a beam's drawn run, (x0, y0) to (x1, y1), on `support`."""
    h, w = support.shape
    xi = np.clip(np.round(np.linspace(f["x0"], f["x1"], n)).astype(int), 0, w - 1)
    yi = np.clip(np.round(np.linspace(f["y0"], f["y1"], n)).astype(int), 0, h - 1)
    return float(support[yi, xi].mean())


def longest_segment(tl: np.ndarray, mask: np.ndarray, R: float,
                    support: np.ndarray | None = None):
    """The longest straight teal segment in the widget that lies BEAM_ON_MAP on
    `support` (any segment without one), or None."""
    b = ((tl >= SEGMENT_TEAL) & mask).astype(np.uint8) * 255
    segs = cv2.HoughLinesP(b, 1, np.pi / 360, 30,
                           minLineLength=int(SEGMENT_MIN * R), maxLineGap=6)
    if segs is None:
        return None
    segs = [s for s in segs.reshape(-1, 4) if support is None or on_map(
        {"x0": s[0], "y0": s[1], "x1": s[2], "y1": s[3]}, support) >= BEAM_ON_MAP]
    if not segs:
        return None
    x0, y0, x1, y1 = max(segs, key=lambda s: np.hypot(s[2] - s[0], s[3] - s[1]))
    return (float(x0), float(y0)), (float(x1), float(y1))


# ------------------------------------------------------------------- fit

def fit_shape(crop: np.ndarray | None, ability: str,
        seed: tuple[float, float] | None, support: np.ndarray | None = None) -> dict:
    """One observation of `ability`'s drawn shape in one minimap crop.

    `seed` is where the caster is believed to be (widget pixels), or None.
    `support` is the map's footprint (`geometry.footprint` at SUPPORT_DILATE).
    Teal counts over the whole widget, because the shapes are drawn over the
    void too; the support only places a beam, which must lie BEAM_ON_MAP on
    the map. Without it no beam is placed, and the row's `support` is None.
    The row always carries `found` and `reason`; an unread shape has
    `found=None` and says why.
    """
    base = {"ability": ability, "ability_shape_version": ABILITY_SHAPE_VERSION,
            "support": None if support is None else "art_footprint"}
    if ability not in SHAPES:
        return {**base, "shape": None, "found": None, "reason": "no_shape_model"}
    shape, prior = SHAPES[ability]
    base["shape"] = shape
    if crop is None:
        return {**base, "found": None, "reason": "no_crop"}
    tl = teal(crop)
    R, mask = widget(crop.shape)
    if support is not None and support.shape != mask.shape:
        return {**base, "found": None, "reason": "support_shape"}

    def placed(f: dict) -> dict:
        if shape == "beam" and support is not None:
            f["on_map"] = on_map(f, support)
        return f

    def clears(f: dict | None) -> bool:
        return (f is not None and f["score"] >= ACCEPT[shape]
                and f.get("on_map", 1.0) >= BEAM_ON_MAP)

    def why(f: dict) -> str:
        return "off_map" if f["score"] >= ACCEPT[shape] else "below_accept"

    out = None
    if prior == "caster" and seed is not None:
        out = placed(dict(fit_ring(tl, mask, R, seed, RING_SEED_HALF * R) if shape == "ring"
                          else fit_beam(tl, mask, seed[0], seed[1], R), path="seeded"))
        if clears(out):
            return {**base, **out, "found": True, "reason": None}
    prior_fit = out
    if shape == "ring":
        out = dict(fit_ring(tl, mask, R, step=3),
                   path="free" if prior == "free" else "widened")
    else:
        seg = longest_segment(tl, mask, R, support)
        if seg is None:
            out = None
        else:
            (ax, ay), (bx, by) = seg
            # The end nearer the seed is the caster's; without one it is unknown.
            if seed is not None and (np.hypot(bx - seed[0], by - seed[1])
                                     < np.hypot(ax - seed[0], ay - seed[1])):
                (ax, ay), (bx, by) = (bx, by), (ax, ay)
            # The caster's icon sits before the drawn blast, as in the seeded
            # geometry, so the origin goes BEAM_NEAR_PX behind the segment's end.
            th = float(np.degrees(np.arctan2(by - ay, bx - ax)))
            ox = ax - BEAM_NEAR_PX * np.cos(np.radians(th))
            oy = ay - BEAM_NEAR_PX * np.sin(np.radians(th))
            out = placed(dict(fit_beam(tl, mask, ox, oy, R, around=th),
                              path="widened", oriented=seed is not None))
    if clears(out):
        seeded = None if prior_fit is None else {"score": prior_fit["score"]}
        return {**base, **out, "seeded": seeded, "found": True, "reason": None}
    # Neither clears: the prior's fit stands, and the widened one is kept beside
    # it. A widened fit is a surprise only when it clears; below acceptance it
    # has no claim over the place the caster was believed to be.
    if prior_fit is not None:
        return {**base, **prior_fit, "widened": None if out is None else
                {k: out[k] for k in ("score", "path", "on_map") if k in out},
                "found": False, "reason": why(prior_fit)}
    if out is None:
        return {**base, "path": "widened", "found": False, "reason": "no_teal_segment"}
    return {**base, **out, "found": False, "reason": why(out)}
