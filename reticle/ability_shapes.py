r"""Fit the minimap shape a candidate descriptor describes.

    .\.venv\Scripts\python.exe -m reticle ability-shapes <session>

Owns [owns:ability-shape].

Finders fed by descriptors (0.4.0). Each finder is a parameterised function:
`fit_shape(crop, desc, seed, support, ms)` reads one descriptor from
`ability_candidates` -- the shape, the prior, the drawn sizes in px and the
colour model -- and holds no ability's values. A descriptor that refuses (no
appearance fact for that ability, side or map) makes the row refuse with its
reason. Four shapes: a ring (`fit_ring`, searched RING_R_TOL round the drawn
radius), a beam from the caster (`fit_beam`, its strip from the drawn
width), a straight wall of up to four segments (`fit_segments`) and a smooth
curve (`fit_curve`). What remains here is the pipeline's tolerance for each
shape, each cited to the run that set it. The whole-range search of 0.3.0
(`ring_candidates`, `widened_beam` without a descriptor, SURPRISE_COLOUR) is
the surprise path, which names no ability.

What is drawn. Regrowth is a ring round Skye
[domain:abilities/skye-regrowth-minimap-ring], Recon Bolt a ring round where
the bolt lands [domain:abilities/sova-recon-bolt-minimap-ring], Hunter's Fury
a straight line from Sova while the ultimate is up
[domain:abilities/sova-hunters-fury-minimap-beam], Barrier Orb a wall of four
segments [domain:abilities/sage-barrier-orb-segments], drawn whole before it
breaks [domain:abilities/sage-barrier-orb-whole-before-break] and shown to
both teams [domain:abilities/sage-barrier-orb-global-minimap], and Blaze a
smooth curve [domain:abilities/phoenix-blaze]. Colour follows the side
[domain:minimap/ability-drawing-colour-by-side]; every measured model is the
ally's. The player traced the first three in the tray-object pass
(`label_tray_objects.py`) and every drawing of block 1
(`labels/ability_recall_20260930`).

The history below describes 0.1.0-0.3.0, which searched every ring radius and
one teal for every ability.

The models. Both come from prototypes that fitted them on demo video:
`prototypes/entity_mining_statistical.py` searched a circle round a seed and
`prototypes/beam_mining_statistical.py` swept a beam's angle round the caster.
Here they read one minimap crop, and `prototypes/ability_shape_eval.py` scores
them against the player's marks.

- colour (0.1.0-0.3.0; now the surprise path's): the beam prototype's teal,
  hue 75-105 and saturation >= 70 (OpenCV scale), weighted by value. The icon key `minimap.ally_mask` (saturation > 90,
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

The fast search (0.2.0). The scores above are unchanged; only their search
is. 0.1.0 scored every third ring centre exactly (about 1.6 s a 331 px
crop). Now a coarse FFT surface of the same score (`RingSurface`, the teal
weight averaged 2x2) proposes its REFINE_K best centres, and the exact score
is maximised on a 7x7 window round each. The beam is swept over every angle
at once (`beam_sweep`). A ring's centre must lie on the map's footprint,
which removes the false rings centred over the void that a whole-match scan
found. `prototypes/ability_shape_eval.py` on 2026-09-30 still finds
[metric:ability_shapes/marks-020@tray-object-marks#fury_found=21] of 21
blasts, [metric:ability_shapes/marks-020@tray-object-marks#regrowth_found=14]
of 16 Regrowth and
[metric:ability_shapes/marks-020@tray-object-marks#recon_found=8] of 8 Recon
Bolt panels, and [metric:ability_shapes/marks-020@tray-object-marks#pre_found=0]
pre-cast panels. Its null ring maximum is
[metric:ability_shapes/null-020@sova-skye-null#ring_max=0.182], and fit_shape
takes a median [metric:ability_shapes/marks-020@tray-object-marks#s_median=0.052]
s and at most [metric:ability_shapes/marks-020@tray-object-marks#s_max=0.138] s
per crop (`docs/ABILITY_DETECTION.md`, stage 1).
`ring_candidates` is the whole-widget ring search that `ability_scan` stores
for every caster.

On every session the stored rows at the marks reproduce these counts. The Fury
line shows on [metric:ability_shapes/production@all-sessions#fury_found=233]
of [metric:ability_shapes/production@all-sessions#fury_crops=234] crops after the ult's drop, turning between crops, so a found beam dates
the ult, not a blast.

With descriptors (0.4.0), on the same marks: Fury
[metric:ability_shapes/marks-040@tray-object-marks#fury_found=21] of 21,
Regrowth [metric:ability_shapes/marks-040@tray-object-marks#regrowth_found=12]
of 16, Recon Bolt [metric:ability_shapes/marks-040@tray-object-marks#recon_found=8]
of 8, pre-cast [metric:ability_shapes/marks-040@tray-object-marks#pre_found=0]
of 10; a blast's angle within 3 deg on
[metric:ability_shapes/marks-040@tray-object-marks#fury_angle_3deg=17] of 21.
The two Regrowth panels lost (`b7d24102a6f6` 1726.0 s, panels 1 and 3) and
the Fury angles lost are the measured colour models': with the surprise teal
in the same descriptors all three return. The Regrowth fact's saturation
floor (57) was measured on rim pixels already selected at saturation 50, so
it is truncated; a remeasure is open, not tuned here. The radius window moves
one Regrowth centre onto the marks (`b7d24102a6f6` 343.6 s). On the null
sample, block 2 excluded, the candidate ring's maximum is
[metric:ability_shapes/null-040@sova-skye-null#cand_ring_max=0.0862] and the
candidate beam's [metric:ability_shapes/null-040@sova-skye-null#cand_beam_max=0.0695],
against the surprise path's
[metric:ability_shapes/null-040@sova-skye-null#ring_max=0.1825] and
[metric:ability_shapes/null-040@sova-skye-null#beam_max=0.0779].

Walls. A Barrier Orb wall is accepted on one crop only whole; a lone piece
is stored with `piece` for a tracker. A piece must be a straight bar
(WALL_BAND_W): the team icons' teal rims and lobes otherwise read as pieces on
106 of 120 null crops. On the null crops a whole wall is found on
[metric:ability_shapes/wall-null@null-crops#sage_found=6] of 120, each a real
wall in a session whose lineup fields Sage
([metric:ability_shapes/wall-null@null-crops#sage_found_not_offered=0] where
the supply offers no Sage), and Blaze on
[metric:ability_shapes/wall-null@null-crops#blaze_found=0].

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

from .geometry import MapScale
from .version import ABILITY_SHAPE_VERSION

# ------------------------------------------------------------------ scale
#
# One set of base values, one transform (0.3.0). Every length below is a base
# value: px at `geometry.SCALE_REF_KEY` (the 465 px widget at the largest map
# scaling). A reader turns it into widget px with the key's
# `geometry.map_scale` (`ms.px(base)`), the widget scale times the map's zoom,
# both from baked geometry. There is no per-size table.
#
# The values were set on 331 px keys (the tray-object marks and the null
# sample are all 331 px), whose scale is 0.632-0.639; SET_AT_SCALE is their
# median, and `_b` turns a value set there into a base value. The values that
# were a share of the widget radius R were set at R = 164.5 px (the 329x331
# crop's half height).
#
# Not lengths, and so not transformed: colour keys, angles, the score
# acceptances, and the search's sampling grid (half-pixel radii, the coarse
# surface's 2x2 average, REFINE_HALF's exact window round a coarse peak, the
# beam profile's 2 px bins), which follow the pixel grid, not the map.

#: The scale of the keys these values were set on, and their widget radius.
SET_AT_SCALE, SET_AT_R = 0.636, 164.5


def _b(px_at_331: float) -> float:
    """A base value from a length set on the 331 px keys."""
    return px_at_331 / SET_AT_SCALE


def _ba(px2_at_331: float) -> float:
    """A base area (or pixel count) from one set on the 331 px keys."""
    return px2_at_331 / SET_AT_SCALE ** 2


#: The transform a caller that names no geometry gets: the values exactly as
#: set (synthetic crops and tests). Production readers pass the key's own.
SET_AT = MapScale(None, SET_AT_SCALE, 1.0, "the scale the base values were set at")

#: How far, in ms, a seed may be taken from a stored self position. The
#: refreshed self track (`minimap-0.7.0`, 2026-09-27) stores single-frame
#: gaps: on the shape crops of 13 sessions the nearest row within 100 ms had
#: no position on a third of them while a row beside it did (the median null
#: run is one row at 15 Hz). The track runs at most `minimap.RUN_PX` widget
#: px/s, so a seed a quarter second off errs by about 11 px, inside the
#: seeded ring's 0.1R search.
SEED_TOL_MS = 250.0

#: The finders' acceptance per shape: a fit is found at this score. Ring and
#: beam: the null maxima of the module docstring. Segments and curves: their
#: contrast, set below the measured walls' least
#: ([metric:ability_models/measure@block1-c62c2b06bcfb#wall_contrast_min=0.74]) and
#: checked against the null crops (`docs/ABILITY_DETECTION.md`, section 9).
ACCEPT = {"ring": 0.2, "beam": 0.23, "segments": 0.3, "curve": 0.3}
#: The surprise path's colour: the generic teal of the whole-widget search,
#: which names no ability (the beam prototype's teal). A candidate's own colour
#: model comes with its descriptor (`ability_candidates`).
TEAL_H, TEAL_S_MIN = (75, 105), 70
SURPRISE_COLOUR = {"hue": TEAL_H, "s_min": TEAL_S_MIN}
#: The surprise path's ring radii and the seeded centre window (set at
#: 0.1-0.45 R and 0.1 R). A candidate searches RING_R_TOL round its own radius.
RING_R_BASE = (_b(0.1 * SET_AT_R), _b(0.45 * SET_AT_R))
#: A candidate ring's radius window, relative: one map's drawn radius holds
#: within half a pixel of its median on the tray-object marks
#: ([metric:ability_models/measure@tray-object-marks#regrowth_within_map_px=0.5]),
#: plus the half-pixel radius grid. The spread BETWEEN maps (7-8%) is not
#: covered: a map with no measured radius has no candidate ring.
RING_R_TOL = 0.04
RING_SEED_HALF_BASE = _b(0.1 * SET_AT_R)
#: The ring score's bands: the annulus is r +- RING_BAND[0], the side bands
#: run RING_BAND[1]-RING_BAND[2] inside and outside it (set at 1.5, 3, 6 px),
#: and a band needs RING_BAND_MIN pixels (set at 8).
RING_BAND = (_b(1.5), _b(3.0), _b(6.0))
RING_BAND_MIN = _ba(8)
#: The surprise path's beam geometry: strip half-width and collar (set at
#: 0.037 R each), reach (1.116 R), the icon cut (15 px), and the pixels a strip
#: and a collar need (20). A candidate beam's strip comes from its drawn width
#: (`beam_geometry`); reach, icon cut and pixel floor are the search's own.
BEAM_HALF_BASE = BEAM_COLLAR_BASE = _b(0.037 * SET_AT_R)
BEAM_REACH_BASE, BEAM_NEAR_BASE = _b(1.116 * SET_AT_R), _b(15.0)
BEAM_MIN_PIXELS = _ba(20)
#: A candidate beam's strip half-width over its drawn half-width: the
#: prototype's strip (0.037 R at 331 px, 6.1 px) over the drawn Hunter's Fury
#: half-width there (4.2 px; [metric:ability_models/measure@tray-object-marks#fury_width_base=13.3]
#: base), which leaves room for the 0.2 deg angle grid at the reach.
BEAM_STRIP_RATIO = 1.44
#: The beam's drawn run: profile gaps up to BEAM_RUN_GAP close, and a run
#: shorter than BEAM_RUN_MIN is skipped (set at 6 and 10 px: 3 and 5 bins).
BEAM_RUN_GAP, BEAM_RUN_MIN = _b(6.0), _b(10.0)
#: The widened beam search: teal above SEGMENT_TEAL, segments at least
#: SEGMENT_MIN_BASE long (set at 0.3 R), Hough votes and gap (set at 30, 6 px).
SEGMENT_TEAL, SEGMENT_MIN_BASE = 0.35, _b(0.3 * SET_AT_R)
SEGMENT_VOTES, SEGMENT_GAP = _b(30.0), _b(6.0)
#: The map's art footprint grown by this much is where a shape may lie
#: (`minimap.art_floor`'s own search dilation, set at 9 px).
SUPPORT_DILATE_BASE = _b(9.0)


def support_dilate(ms: MapScale) -> float:
    """The footprint dilation `geometry.footprint` takes for this key."""
    return ms.px(SUPPORT_DILATE_BASE)
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


def colour_weight(crop: np.ndarray, colour: dict) -> np.ndarray:
    """Per-pixel weight in [0, 1] of one colour model (`{"hue": (lo, hi),
    "s_min": s}`, OpenCV scale): in hue and saturation, scaled by value."""
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    lo, hi = colour["hue"]
    return (((h >= lo) & (h <= hi) & (s >= colour["s_min"]))
            .astype(np.float32) * (v / np.float32(255.0)))


def teal(crop: np.ndarray) -> np.ndarray:
    """The surprise path's teal weight (SURPRISE_COLOUR)."""
    return colour_weight(crop, SURPRISE_COLOUR)


#: A candidate's hue band runs this far (OpenCV hue units) outside its drawn
#: pixels' median 5th and 95th percentiles: the 90th percentile, over the
#: tray-object panels of every measured ability, of one panel's p5 below the
#: median p5 or p95 above the median p95
#: ([metric:ability_models/measure@tray-object-marks#hue_p5_spread=7]). The
#: largest, 64, is a Regrowth rim crossing another colour; one panel in ten
#: may.
COLOUR_HUE_TOL = 7


def colour_model(hue: list, sat_p10: list) -> dict:
    """A candidate's colour model from its fact's measured drawn pixels:
    `hue` their (p5, p50, p95) and `sat_p10` the range of their 10th-percentile
    saturation over the measured panels. The band takes COLOUR_HUE_TOL past the
    percentiles and the least panel's saturation, so at most one drawn pixel
    in ten of the worst measured panel falls outside it."""
    return {"hue": (float(hue[0]) - COLOUR_HUE_TOL, float(hue[-1]) + COLOUR_HUE_TOL),
            "s_min": float(min(sat_p10))}


def widget(shape) -> tuple[float, np.ndarray]:
    """The widget radius and its disc, from the crop's size alone."""
    h, w = shape[:2]
    cx, cy, R = (w - 1) / 2.0, (h - 1) / 2.0, min(h, w) / 2.0
    yy, xx = np.mgrid[0:h, 0:w]
    return R, np.hypot(xx - cx, yy - cy) <= R


# ------------------------------------------------------------------- ring

#: The coarse surface's scale, how many of its peaks are rescored, and the
#: exact window round each, in px (`prototypes/ability_shape_fast.py`'s
#: coarse-to-fine variant, measured there against the exhaustive search).
COARSE_SCALE, REFINE_K, REFINE_HALF = 0.5, 5, 3


def _smooth_len(n: int) -> int:
    """The smallest 5-smooth integer >= n (pocketfft is fastest on those)."""
    while True:
        m = n
        for p in (2, 3, 5):
            while m % p == 0:
                m //= p
        if m == 1:
            return n
        n += 1


class _Radial:
    """Half-pixel radial sums round any centre of one crop, padded once."""

    def __init__(self, tl: np.ndarray, mask: np.ndarray, radii: np.ndarray,
                 ms: MapScale = SET_AT):
        a, b0, b1 = (ms.px(v) for v in RING_BAND)
        self.band_min = ms.area(RING_BAND_MIN)
        self.W = W = int(np.ceil(radii.max() + b1 + 1))
        self.t = np.pad(tl * mask, W)
        self.m = np.pad(mask.astype(np.float32), W)
        yy, xx = np.mgrid[-W:W + 1, -W:W + 1]
        self.d = np.floor(np.hypot(xx, yy) * 2).astype(int).ravel()
        self.n = int(self.d.max()) + 2
        self.radii = radii
        self.i = [np.clip(np.round(v * 2).astype(int), 0, self.n)
                  for v in (radii - a, radii - b1, radii + b0)]
        self.j = [np.clip(np.round(v * 2).astype(int), 0, self.n)
                  for v in (radii + a, radii - b0, radii + b1)]

    def scores(self, x: int, y: int) -> np.ndarray:
        """The ring score at centre (x, y) for every radius."""
        W, n = self.W, self.n
        t = self.t[y:y + 2 * W + 1, x:x + 2 * W + 1].ravel()
        m = self.m[y:y + 2 * W + 1, x:x + 2 * W + 1].ravel()
        T = np.concatenate([[0.0], np.cumsum(np.bincount(self.d, weights=t, minlength=n))])
        M = np.concatenate([[0.0], np.cumsum(np.bincount(self.d, weights=m, minlength=n))])

        def band(k):
            cnt = M[self.j[k]] - M[self.i[k]]
            return np.where(cnt >= self.band_min,
                            (T[self.j[k]] - T[self.i[k]]) / np.maximum(cnt, 1), np.nan)

        out = band(0) - np.fmax(band(1), band(2))
        return np.where(np.isnan(out), -1.0, out)


def ring_radii(ms: MapScale = SET_AT) -> np.ndarray:
    """The searched ring radii, RING_R_BASE transformed, in half pixels."""
    lo, hi = ms.px(RING_R_BASE[0]), ms.px(RING_R_BASE[1])
    return np.arange(lo, hi + 0.01, 0.5)


def candidate_radii(radius_px: float) -> np.ndarray:
    """A candidate ring's searched radii: RING_R_TOL round its drawn radius,
    in half pixels."""
    return np.arange(radius_px * (1 - RING_R_TOL), radius_px * (1 + RING_R_TOL) + 0.01, 0.5)


class _Kernels:
    """Disc-kernel FFTs and the widget's band counts for one crop size,
    scale and radius set. They depend on those alone, so they are built once."""

    _cache: dict = {}

    @classmethod
    def of(cls, shape, ms: MapScale, scale: float, radii: np.ndarray | None = None) -> "_Kernels":
        key = (tuple(shape), round(ms.scale, 6), scale,
               None if radii is None else (round(float(radii[0]), 3), len(radii)))
        if key not in cls._cache:
            cls._cache[key] = cls(tuple(shape), ms, scale, radii)
        return cls._cache[key]

    def __init__(self, shape, ms: MapScale, scale: float, radii: np.ndarray | None = None):
        h, w = shape
        full = ring_radii(ms) if radii is None else radii
        self.radii = full if scale == 1.0 else full[::2]
        r, s = self.radii * scale, scale
        a, b0, b1 = (ms.px(v) for v in RING_BAND)
        self.band_min = ms.area(RING_BAND_MIN)
        i = [np.clip(np.round(v * 2).astype(int), 0, None)
             for v in (r - a * s, r - b1 * s, r + b0 * s)]
        j = [np.clip(np.round(v * 2).astype(int), 0, None)
             for v in (r + a * s, r - b0 * s, r + b1 * s)]
        self.ks = np.unique(np.concatenate(i + j))
        pos = {int(k): n for n, k in enumerate(self.ks)}
        self.jn = [np.array([pos[int(k)] for k in a]) for a in j]
        self.im = [np.array([pos[int(k)] for k in a]) for a in i]
        W = int(np.ceil(r.max() + (b1 + 1) * s))
        self.P = (_smooth_len(h + W + 1), _smooth_len(w + W + 1))
        yy, xx = np.mgrid[-W:W + 1, -W:W + 1]
        d2 = np.floor(np.hypot(xx, yy) * 2).astype(int)
        self.KF = np.empty((len(self.ks), self.P[0], self.P[1] // 2 + 1), np.complex64)
        for n, k in enumerate(self.ks):
            kp = np.zeros(self.P, np.float32)
            kp[yy % self.P[0], xx % self.P[1]] = (d2 < k).astype(np.float32)
            self.KF[n] = np.fft.rfft2(kp)
        _, self.mask = widget(shape)
        self.M = np.rint(self.conv(self.mask.astype(np.float32), shape))

    def conv(self, img: np.ndarray, shape) -> np.ndarray:
        """`img`'s sum over every disc kernel, at every centre."""
        h, w = shape
        F = np.fft.rfft2(img, s=self.P).astype(np.complex64)
        out = np.empty((len(self.ks), h, w), np.float32)
        for n in range(len(self.ks)):
            out[n] = np.fft.irfft2(F * self.KF[n], s=self.P)[:h, :w]
        return out


class RingSurface:
    """The `fit_ring` score's best radius at every centre of one crop at once.

    A band sum round a centre is a disc sum at its outer edge minus one at
    its inner edge, and a disc sum at every centre is a convolution of the
    teal weight with that disc: one FFT of the crop and one inverse FFT per
    half-pixel radius give every band. At `scale` < 1 the teal weight is
    averaged first, and the surface only proposes centres for the exact
    rescoring in `fit_ring`."""

    def __init__(self, tl: np.ndarray, ms: MapScale = SET_AT, scale: float = COARSE_SCALE,
                 radii: np.ndarray | None = None):
        self.scale, self.ms = scale, ms
        small = (tl if scale == 1.0 else
                 cv2.resize(tl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))
        K = self.K = _Kernels.of(small.shape, ms, scale, radii)
        T, M = K.conv((small * K.mask).astype(np.float32), small.shape), K.M
        best = np.full(small.shape, -2.0, np.float32)
        arg = np.zeros(small.shape, np.int32)
        for q in range(len(K.radii)):
            vals = []
            for b in range(3):
                jn, im = K.jn[b][q], K.im[b][q]
                cnt = M[jn] - M[im]
                with np.errstate(invalid="ignore", divide="ignore"):
                    vals.append(np.where(cnt >= K.band_min, (T[jn] - T[im]) / np.maximum(cnt, 1),
                                         np.nan))
            out = vals[0] - np.fmax(vals[1], vals[2])
            out = np.where(np.isnan(out), -1.0, out).astype(np.float32)
            better = out > best
            best[better] = out[better]
            arg[better] = q
        best[~K.mask] = -2.0
        self.best, self.arg = best, arg

    def peaks(self, k: int = REFINE_K, centre=None, half=None,
              allowed: np.ndarray | None = None) -> list:
        """The `k` best local maxima at least RING_SEED_HALF_BASE apart, as (score,
        x, y) in full-resolution pixels: inside the window round `centre`
        when given, and on `allowed` (a full-resolution mask) when given."""
        s = self.scale
        b = self.best.copy()
        if centre is not None:
            m = np.full(b.shape, -2.0, np.float32)
            x0 = max(0, int((centre[0] - half) * s))
            x1 = min(b.shape[1], int((centre[0] + half) * s) + 1)
            y0 = max(0, int((centre[1] - half) * s))
            y1 = min(b.shape[0], int((centre[1] + half) * s) + 1)
            m[y0:y1, x0:x1] = b[y0:y1, x0:x1]
            b = m
        if allowed is not None:
            h, w = allowed.shape
            yy, xx = np.mgrid[0:b.shape[0], 0:b.shape[1]]
            ok = allowed[np.clip(np.round(yy / s).astype(int), 0, h - 1),
                         np.clip(np.round(xx / s).astype(int), 0, w - 1)]
            b[~ok] = -2.0
        sep = max(1, int(round(self.ms.px(RING_SEED_HALF_BASE) * s)))
        out = []
        for _ in range(k):
            yi, xi = np.unravel_index(int(np.argmax(b)), b.shape)
            if b[yi, xi] <= -1.0:
                break
            out.append((float(b[yi, xi]), xi / s, yi / s))
            b[max(0, yi - sep):yi + sep + 1, max(0, xi - sep):xi + sep + 1] = -2.0
        return out


def _ring_window(rad: _Radial, mask: np.ndarray, centre, half: float,
                 allowed: np.ndarray | None = None) -> tuple:
    """The exact score's best (score, x, y, r) over every centre within `half`."""
    h, w = mask.shape
    best = (-2.0, None, None, None)
    for x in range(max(0, int(centre[0] - half)), min(w, int(centre[0] + half) + 1)):
        for y in range(max(0, int(centre[1] - half)), min(h, int(centre[1] + half) + 1)):
            if not mask[y, x] or (allowed is not None and not allowed[y, x]):
                continue
            sc = rad.scores(x, y)
            k = int(np.argmax(sc))
            if sc[k] > best[0]:
                best = (float(sc[k]), x, y, float(rad.radii[k]))
    return best


def fit_ring(tl: np.ndarray, mask: np.ndarray, ms: MapScale = SET_AT,
             centre: tuple[float, float] | None = None, half: float | None = None,
             step: int | None = None, _radial: _Radial | None = None,
             support: np.ndarray | None = None,
             _surface: RingSurface | None = None, radii: np.ndarray | None = None) -> dict:
    """The best ring, searched round `centre` (within `half`) or everywhere:
    the score is mean teal on the annulus r +- RING_BAND[0] minus the brighter
    of the bands RING_BAND[1]-RING_BAND[2] inside and outside it.

    Coarse to fine (0.2.0): the coarse `RingSurface` proposes its REFINE_K
    best centres, and the exact score is maximised on a window of
    REFINE_HALF px round each. With `support`, a centre must lie on it (the
    centre-on-footprint gate): a ring centred over the void is a false ring,
    while teal still counts wherever it is drawn. `step` was 0.1.0's stride
    and is no longer read. `radii` is a candidate's window
    (`candidate_radii`); without it the surprise path's whole range.
    """
    radii = ring_radii(ms) if radii is None else radii
    rad = _radial or _Radial(tl, mask, radii, ms)
    surf = _surface or RingSurface(tl, ms, radii=radii)
    allowed = None if support is None else (support & mask)
    cands = surf.peaks(centre=centre, half=half, allowed=allowed)
    if centre is not None:
        # The seeded window stays the prior's own.
        cands = [c for c in cands if abs(c[1] - centre[0]) <= half + 1
                 and abs(c[2] - centre[1]) <= half + 1] or [(0.0, centre[0], centre[1])]
    best = (-2.0, None, None, None)
    for c in cands:
        got = _ring_window(rad, mask, (c[1], c[2]), REFINE_HALF, allowed)
        if got[0] > best[0]:
            best = got
    return {"score": best[0], "cx": best[1], "cy": best[2], "r": best[3]}


def ring_candidates(tl: np.ndarray, mask: np.ndarray, ms: MapScale = SET_AT,
                    support: np.ndarray | None = None, min_coarse: float = 0.10,
                    _surface: RingSurface | None = None) -> list[dict]:
    """The whole-widget ring search a scan of every caster stores: each
    coarse peak scoring at least `min_coarse`, refined as `fit_ring` refines
    its best, best first. `accepted` is ACCEPT's verdict on each."""
    rad = _Radial(tl, mask, ring_radii(ms), ms)
    surf = _surface or RingSurface(tl, ms)
    allowed = None if support is None else (support & mask)
    out = []
    for c in surf.peaks(allowed=allowed):
        if c[0] < min_coarse:
            continue
        s, x, y, r = _ring_window(rad, mask, (c[1], c[2]), REFINE_HALF, allowed)
        if x is None:
            continue
        out.append({"score": s, "cx": x, "cy": y, "r": r, "coarse": c[0],
                    "accepted": s >= ACCEPT["ring"]})
    return sorted(out, key=lambda f: -f["score"])


# ------------------------------------------------------------------- beam

#: The swept beam's angle grid and the window round a widened segment's own
#: angle, in degrees.
BEAM_STEP_DEG, BEAM_AROUND_DEG = 0.2, 8.0


def surprise_beam(ms: MapScale = SET_AT) -> dict:
    """The surprise path's beam geometry in this key's px."""
    return {"half_px": ms.px(BEAM_HALF_BASE), "collar_px": ms.px(BEAM_COLLAR_BASE),
            "near_px": ms.px(BEAM_NEAR_BASE), "reach_px": ms.px(BEAM_REACH_BASE)}


def beam_geometry(width_px: float, ms: MapScale = SET_AT) -> dict:
    """A candidate beam's geometry from its drawn width (px): the strip and
    its collar BEAM_STRIP_RATIO of the drawn half-width; the reach and the
    caster's icon cut are the search's own."""
    half = 0.5 * width_px * BEAM_STRIP_RATIO
    return {"half_px": half, "collar_px": half,
            "near_px": ms.px(BEAM_NEAR_BASE), "reach_px": ms.px(BEAM_REACH_BASE)}


def _beam(tl, mask, vx, vy, th, ms: MapScale, geo: dict | None = None):
    geo = geo or surprise_beam(ms)
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    lp, dp = vx * c + vy * s, np.abs(-vx * s + vy * c)
    hw, col = geo["half_px"], geo["collar_px"]
    along = (lp >= geo["near_px"]) & (lp <= geo["reach_px"]) & mask
    strip, collar = along & (dp <= hw), along & (dp > hw) & (dp <= hw + col)
    nmin = ms.area(BEAM_MIN_PIXELS)
    if strip.sum() < nmin or collar.sum() < nmin:
        return -1.0, lp, strip
    return float(tl[strip].mean() - tl[collar].mean()), lp, strip


def beam_sweep(tl: np.ndarray, mask: np.ndarray, ox: float, oy: float, ms: MapScale = SET_AT,
               step: float = BEAM_STEP_DEG, geo: dict | None = None) -> tuple[np.ndarray, np.ndarray]:
    """The beam score (strip minus collar) at every angle of a `step` grid.

    A pixel at distance rho and bearing phi from the origin lies in the
    strip of angle theta when |theta - phi| <= asin(half / rho), so each
    pixel adds its teal to one interval of the angle grid, and a difference
    array sums every interval in one pass. `geo` is a candidate's geometry
    (`beam_geometry`); without it the surprise path's."""
    geo = geo or surprise_beam(ms)
    ys, xs = np.nonzero(mask)
    vx, vy = xs - ox, ys - oy
    rho = np.hypot(vx, vy)
    sel = (rho >= geo["near_px"]) & (rho <= geo["reach_px"])
    rho, phi = rho[sel], np.degrees(np.arctan2(vy[sel], vx[sel])) % 360.0
    t = tl[ys[sel], xs[sel]].astype(np.float64)
    hw, col = geo["half_px"], geo["collar_px"]
    nmin = ms.area(BEAM_MIN_PIXELS)
    nb = int(round(360.0 / step))

    def interval(alpha, wts):
        lo = np.ceil((phi - alpha) / step - 1e-9).astype(int) + nb
        hi = np.floor((phi + alpha) / step + 1e-9).astype(int) + nb + 1
        d = np.bincount(lo, wts, 3 * nb + 2) - np.bincount(hi, wts, 3 * nb + 2)
        c = np.cumsum(d)[:3 * nb]
        return c[:nb] + c[nb:2 * nb] + c[2 * nb:]

    a1 = np.degrees(np.arcsin(np.clip(hw / rho, 0, 1)))
    a2 = np.degrees(np.arcsin(np.clip((hw + col) / rho, 0, 1)))
    one = np.ones_like(t)
    s1, n1 = interval(a1, t), interval(a1, one)
    s2, n2 = interval(a2, t) - s1, interval(a2, one) - n1
    with np.errstate(invalid="ignore", divide="ignore"):
        sc = np.where((n1 >= nmin) & (n2 >= nmin), s1 / n1 - s2 / n2, -1.0)
    return np.arange(nb) * step, sc


def fit_beam(tl: np.ndarray, mask: np.ndarray, ox: float, oy: float, ms: MapScale = SET_AT,
             around: float | None = None, geo: dict | None = None) -> dict:
    """The best beam from (ox, oy), swept over every angle at BEAM_STEP_DEG
    (0.2.0), or within BEAM_AROUND_DEG of `around`. The score is mean teal in
    the strip minus mean teal in the collars either side; the beam ends where
    the strip's teal falls below half its peak."""
    geo = geo or surprise_beam(ms)
    th, sc = beam_sweep(tl, mask, ox, oy, ms, geo=geo)
    if around is not None:
        d = np.abs((th - around + 180) % 360 - 180)
        sc = np.where(d <= BEAM_AROUND_DEG, sc, -2.0)
    k = int(np.argmax(sc))
    best, thb = float(sc[k]), float(th[k])
    h, w = tl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    _, lp, strip = _beam(tl, mask, xx - ox, yy - oy, thb, ms, geo)
    bins = np.floor(lp[strip] / 2.0).astype(int)
    prof = np.bincount(bins, weights=tl[strip]) / np.maximum(np.bincount(bins), 1)
    l0 = l1 = geo["near_px"]
    gap, least = round(ms.px(BEAM_RUN_GAP) / 2.0), round(ms.px(BEAM_RUN_MIN) / 2.0)
    on = np.nonzero(prof >= 0.5 * prof.max())[0] if prof.size and prof.max() > 0 else []
    if len(on):
        run = [on[0]]
        for b in on[1:]:
            if b - run[-1] <= gap:
                run.append(b)
            elif len(run) < least:
                run = [b]
            else:
                break
        l0, l1 = run[0] * 2.0, run[-1] * 2.0 + 2.0
    c, s = np.cos(np.radians(thb)), np.sin(np.radians(thb))
    return {"score": best, "theta_deg": float(thb % 360),
            "x0": float(ox + l0 * c), "y0": float(oy + l0 * s),
            "x1": float(ox + l1 * c), "y1": float(oy + l1 * s), "length": l1 - l0}


def on_map(f: dict, support: np.ndarray, n: int = 40) -> float:
    """The fraction of a beam's drawn run, (x0, y0) to (x1, y1), on `support`."""
    h, w = support.shape
    xi = np.clip(np.round(np.linspace(f["x0"], f["x1"], n)).astype(int), 0, w - 1)
    yi = np.clip(np.round(np.linspace(f["y0"], f["y1"], n)).astype(int), 0, h - 1)
    return float(support[yi, xi].mean())


def longest_segment(tl: np.ndarray, mask: np.ndarray, ms: MapScale = SET_AT,
                    support: np.ndarray | None = None):
    """The longest straight teal segment in the widget that lies BEAM_ON_MAP on
    `support` (any segment without one), or None."""
    b = ((tl >= SEGMENT_TEAL) & mask).astype(np.uint8) * 255
    segs = cv2.HoughLinesP(b, 1, np.pi / 360, int(round(ms.px(SEGMENT_VOTES))),
                           minLineLength=int(ms.px(SEGMENT_MIN_BASE)),
                           maxLineGap=int(round(ms.px(SEGMENT_GAP))))
    if segs is None:
        return None
    segs = [s for s in segs.reshape(-1, 4) if support is None or on_map(
        {"x0": s[0], "y0": s[1], "x1": s[2], "y1": s[3]}, support) >= BEAM_ON_MAP]
    if not segs:
        return None
    x0, y0, x1, y1 = max(segs, key=lambda s: np.hypot(s[2] - s[0], s[3] - s[1]))
    return (float(x0), float(y0)), (float(x1), float(y1))


def widened_beam(tl: np.ndarray, mask: np.ndarray, ms: MapScale = SET_AT,
                 support: np.ndarray | None = None,
                 seed: tuple[float, float] | None = None, geo: dict | None = None) -> dict | None:
    """The beam along the longest straight teal segment on the map, or None
    where there is none: the widened search of `fit_shape`, and the whole
    beam search of a scan of every caster (no seed).

    The end nearer `seed` is the caster's, and the row says `oriented`;
    without a seed the end is unknown. The caster's icon sits before the
    drawn blast, as in the seeded geometry, so the origin goes BEAM_NEAR_BASE
    behind the segment's end."""
    seg = longest_segment(tl, mask, ms, support)
    if seg is None:
        return None
    (ax, ay), (bx, by) = seg
    if seed is not None and (np.hypot(bx - seed[0], by - seed[1])
                             < np.hypot(ax - seed[0], ay - seed[1])):
        (ax, ay), (bx, by) = (bx, by), (ax, ay)
    th = float(np.degrees(np.arctan2(by - ay, bx - ax)))
    geo = geo or surprise_beam(ms)
    near = geo["near_px"]
    ox = ax - near * np.cos(np.radians(th))
    oy = ay - near * np.sin(np.radians(th))
    out = dict(fit_beam(tl, mask, ox, oy, ms, around=th, geo=geo), path="widened",
               oriented=seed is not None)
    if support is not None:
        out["on_map"] = on_map(out, support)
    return out


def beam_accepted(f: dict | None) -> bool:
    """ACCEPT's verdict on a beam: its score, and BEAM_ON_MAP of its run on
    the map where a support placed it."""
    return (f is not None and f["score"] >= ACCEPT["beam"]
            and f.get("on_map", 1.0) >= BEAM_ON_MAP)


# ------------------------------------------------------------- segments, curves
#
# Pipeline tolerances of the wall finders. The drawn sizes come with the
# descriptor; these say how far a component may stray from them and still be
# scored, each set from the measured walls of block 1
# ([metric:ability_models/measure@block1-c62c2b06bcfb#sage_width_min=3.94]-
# [metric:ability_models/measure@block1-c62c2b06bcfb#sage_width_max=5.97] px wide
# against a drawn 4.9, whole walls within
# [metric:ability_models/measure@block1-c62c2b06bcfb#sage_whole_spread=0.035] of
# their length; Blaze [metric:ability_models/measure@block1-c62c2b06bcfb#blaze_width_min=5.47]-
# [metric:ability_models/measure@block1-c62c2b06bcfb#blaze_width_max=7.51] px wide
# against a drawn 5.9).

#: A wall pixel's least colour weight (the widened beam's SEGMENT_TEAL).
WALL_W = SEGMENT_TEAL
#: A component's width (pixels / length) over the drawn width.
WALL_WIDTH_TOL = (0.6, 1.5)
#: A whole wall's span over its drawn length, at most.
WALL_SPAN_TOL = 1.1
#: A piece at least this share of the one-segment piece (the least measured
#: piece is 0.74 of it).
WALL_PIECE_MIN = 0.7
#: Pieces of one wall: at most this many degrees apart and this many drawn
#: widths off one line.
WALL_ANGLE_DEG, WALL_OFFSET_W = 15.0, 1.0
#: A component's length over its width, at least: a disc is not a wall.
WALL_ELONGATION = 1.8
#: A wall piece is a straight bar: its band round its own axis (twice the
#: 90th-percentile perpendicular residual, plus one) over its width, at most.
#: Block 1's wall pieces reach
#: [metric:ability_models/measure@block1-c62c2b06bcfb#sage_band_max=1.47];
#: a team icon's teal rim or lobe, curved, is wider (the null's false pieces,
#: median [metric:ability_models/measure@block1-c62c2b06bcfb#null_band_median=1.92]).
WALL_BAND_W = 1.5
#: A curve's length outside its drawn range by at most this share.
CURVE_LEN_TOL = 0.15
#: Pieces of one curve join across a gap of at most this many drawn widths.
CURVE_JOIN_W = 3.0
#: A curve's band round its quadratic axis (twice the 90th-percentile
#: residual, plus one) over its drawn width, at most.
CURVE_RESIDUAL_W = 1.6
#: A curve's length over its width, at least.
CURVE_ELONGATION = 3.0


def _components(w: np.ndarray, mask: np.ndarray, width_px: float, elongation: float) -> list[dict]:
    """The colour components whose width (pixels per unit length) lies within
    WALL_WIDTH_TOL of `width_px` and whose length is at least `elongation`
    widths, measured along their principal axis."""
    b = ((w >= WALL_W) & mask).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    out = []
    for k in range(1, n):
        if st[k, cv2.CC_STAT_AREA] < 4:
            continue
        x, y, ww, hh = st[k, :4]
        sub = lab[y:y + hh, x:x + ww] == k
        ys, xs = np.nonzero(sub)
        P = np.stack([xs + x, ys + y], 1).astype(float)
        c = P.mean(0)
        _, _, vt = np.linalg.svd(P - c, full_matrices=False)
        a = (P - c) @ vt[0]
        L = float(a.max() - a.min() + 1)
        width = len(P) / L
        if not (WALL_WIDTH_TOL[0] * width_px <= width <= WALL_WIDTH_TOL[1] * width_px):
            continue
        if L < elongation * width:
            continue
        u = vt[0] if vt[0][0] >= 0 else -vt[0]
        out.append({"pts": P, "c": c, "u": u, "L": L, "width": width,
                    "theta": float(np.degrees(np.arctan2(u[1], u[0])) % 180.0)})
    return out


def _straight(c: dict) -> bool:
    """Whether a component lies within WALL_BAND_W of its width round its axis."""
    n = np.array([-c["u"][1], c["u"][0]])
    band = 2 * np.percentile(np.abs((c["pts"] - c["c"]) @ n), 90) + 1
    return bool(band <= WALL_BAND_W * c["width"])


def _contrast(w: np.ndarray, mask: np.ndarray, pts: np.ndarray) -> float:
    """Mean colour weight on a component's pixels minus that of a 2 px collar."""
    h, wd = w.shape
    on = np.zeros((h, wd), np.uint8)
    on[pts[:, 1].astype(int), pts[:, 0].astype(int)] = 1
    ring = cv2.dilate(on, np.ones((5, 5), np.uint8)).astype(bool) & ~on.astype(bool) & mask
    inner = w[on.astype(bool)]
    return float(inner.mean() - (w[ring].mean() if ring.any() else 0.0))


def _ends(pts: np.ndarray, u: np.ndarray) -> tuple:
    c = pts.mean(0)
    a = (pts - c) @ u
    return c + u * a.min(), c + u * a.max(), float(a.max() - a.min() + 1)


def _wall_groups(comps: list[dict], join) -> list[list[int]]:
    """Union of the components `join(i, j)` links."""
    parent = list(range(len(comps)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(comps)):
        for j in range(i + 1, len(comps)):
            if join(comps[i], comps[j]):
                parent[find(i)] = find(j)
    by: dict[int, list[int]] = {}
    for i in range(len(comps)):
        by.setdefault(find(i), []).append(i)
    return list(by.values())


def _on_support(support, x, y) -> bool:
    if support is None:
        return True
    h, w = support.shape
    return bool(support[int(np.clip(round(y), 0, h - 1)), int(np.clip(round(x), 0, w - 1))])


def fit_segments(w: np.ndarray, mask: np.ndarray, desc: dict,
                 support: np.ndarray | None = None) -> list[dict]:
    """A straight wall of up to four pieces on one line, best first.

    `desc` carries the drawn sizes in px: `length_px` (the whole wall),
    `pieces_px` (one, two and three segments) and `width_px`. A piece is a
    colour component of the drawn width and at most the whole length; pieces
    within WALL_ANGLE_DEG and WALL_OFFSET_W widths of one line join, while
    their span stays within WALL_SPAN_TOL of the whole length. The score is
    the pieces' pixel-weighted contrast; `coverage` is their summed length over
    the whole length, so a whole wall reads about 1 and one segment about 0.3.
    A wall whose midpoint lies off `support` is not one.

    A group is `whole` when its span is at least the drawn length over
    WALL_SPAN_TOL. Only a whole wall is accepted on one crop: the orb draws
    the wall whole before it breaks
    [domain:abilities/sage-barrier-orb-whole-before-break], so a lone piece
    is a broken wall only after a whole one stood there, which a tracker over
    crops decides. Pieces stay in the list, `accepted` False, `piece` True."""
    L, pw, width = desc["length_px"], desc["pieces_px"][0], desc["width_px"]
    comps = [c for c in _components(w, mask, width, WALL_ELONGATION)
             if WALL_PIECE_MIN * pw <= c["L"] <= WALL_SPAN_TOL * L and _straight(c)]

    def join(a, b):
        d = abs(a["theta"] - b["theta"]) % 180.0
        if min(d, 180.0 - d) > WALL_ANGLE_DEG:
            return False
        n = np.array([-a["u"][1], a["u"][0]])
        if abs(float((b["c"] - a["c"]) @ n)) > WALL_OFFSET_W * width:
            return False
        _, _, span = _ends(np.vstack([a["pts"], b["pts"]]), a["u"])
        return span <= WALL_SPAN_TOL * L
    out = []
    for g in _wall_groups(comps, join):
        pts = np.vstack([comps[i]["pts"] for i in g])
        big = max(g, key=lambda i: comps[i]["L"])
        p0, p1, span = _ends(pts, comps[big]["u"])
        if span > WALL_SPAN_TOL * L:
            continue
        mid = (p0 + p1) / 2
        if not _on_support(support, mid[0], mid[1]):
            continue
        sc = _contrast(w, mask, pts)
        whole = span >= L / WALL_SPAN_TOL
        out.append({"score": sc, "x0": float(p0[0]), "y0": float(p0[1]),
                    "x1": float(p1[0]), "y1": float(p1[1]), "span": span, "pieces": len(g),
                    "coverage": float(sum(comps[i]["L"] for i in g) / L),
                    "width": float(np.mean([comps[i]["width"] for i in g])),
                    "theta_deg": comps[big]["theta"], "whole": bool(whole), "piece": not whole,
                    "accepted": bool(whole and sc >= ACCEPT["segments"])})
    return sorted(out, key=lambda f: (not f["accepted"], -f["score"]))


def fit_curve(w: np.ndarray, mask: np.ndarray, desc: dict,
              support: np.ndarray | None = None) -> list[dict]:
    """A smooth curve of the drawn width, best first.

    `desc` carries `width_px` and `length_px` (the drawn range, low and high).
    Components of the drawn width join across gaps of CURVE_JOIN_W widths; a
    group's pixels are fitted by a quadratic along their principal axis, and a
    curve stays within CURVE_RESIDUAL_W widths of it and within CURVE_LEN_TOL
    of the drawn range. `points` is the fitted axis, five places along it."""
    width, (lo, hi) = desc["width_px"], desc["length_px"]
    comps = _components(w, mask, width, CURVE_ELONGATION)

    def join(a, b):
        da = np.hypot(*(a["pts"][:, None, :] - b["pts"][None, ::4, :]).T)
        return float(da.min()) <= CURVE_JOIN_W * width
    out = []
    for g in _wall_groups(comps, join):
        pts = np.vstack([comps[i]["pts"] for i in g])
        c = pts.mean(0)
        _, _, vt = np.linalg.svd(pts - c, full_matrices=False)
        a, b = (pts - c) @ vt[0], (pts - c) @ vt[1]
        length = float(a.max() - a.min() + 1)
        if not ((1 - CURVE_LEN_TOL) * lo <= length <= (1 + CURVE_LEN_TOL) * hi):
            continue
        co = np.polyfit(a, b, 2)
        band = float(2 * np.percentile(np.abs(b - np.polyval(co, a)), 90) + 1)
        if band > CURVE_RESIDUAL_W * width:
            continue
        s = np.linspace(a.min(), a.max(), 5)
        axis = [c + vt[0] * t + vt[1] * float(np.polyval(co, t)) for t in s]
        mid = axis[2]
        if not _on_support(support, mid[0], mid[1]):
            continue
        sc = _contrast(w, mask, pts)
        out.append({"score": sc, "points": [[round(float(p[0]), 1), round(float(p[1]), 1)] for p in axis],
                    "x0": float(axis[0][0]), "y0": float(axis[0][1]),
                    "x1": float(axis[-1][0]), "y1": float(axis[-1][1]),
                    "length": length, "band": band, "pieces": len(g), "bend": float(co[0]),
                    "width": float(len(pts) / length), "accepted": sc >= ACCEPT["curve"]})
    return sorted(out, key=lambda f: -f["score"])


# ------------------------------------------------------------------- fit

def descriptor_ref(desc: dict) -> dict:
    """What a row records of the descriptor it was scored against."""
    keep = ("id", "ability", "agent", "side", "shape", "prior", "radius_px", "length_px",
            "pieces_px", "width_px", "colour", "facts", "rests_on")
    return {k: desc[k] for k in keep if k in desc}


def fit_shape(crop: np.ndarray | None, desc: dict,
        seed: tuple[float, float] | None, support: np.ndarray | None = None,
        ms: MapScale = SET_AT) -> dict:
    """One observation of a candidate's drawn shape in one minimap crop.

    `desc` is the candidate's descriptor in px (`ability_candidates`): its
    shape, prior, drawn sizes and colour model. A descriptor with `refused`
    is a field without a fact, and the row refuses with that reason; the
    finder never falls back to another ability's values.
    `seed` is where the caster is believed to be (widget pixels), or None.
    `support` is the map's footprint (`geometry.footprint` at `support_dilate`).
    `ms` is the key's `geometry.map_scale`; SET_AT, the values as set, when
    the caller names no geometry.
    Colour counts over the whole widget, because the shapes are drawn over the
    void too; the support only places a shape: a ring's centre lies on it
    (0.2.0), a beam lies BEAM_ON_MAP on it, a wall's midpoint lies on it.
    Without it nothing is placed, and the row's `support` is None.
    The row always carries `found` and `reason`; an unread shape has
    `found=None` and says why.
    """
    base = {"ability": desc.get("ability"), "side": desc.get("side"),
            "ability_shape_version": ABILITY_SHAPE_VERSION,
            "support": None if support is None else "art_footprint",
            "map_scale": ms.provenance(), "descriptor": descriptor_ref(desc),
            "shape": desc.get("shape")}
    if desc.get("refused"):
        return {**base, "found": None, "reason": desc["refused"]}
    shape, prior = desc["shape"], desc.get("prior", "free")
    if crop is None:
        return {**base, "found": None, "reason": "no_crop"}
    tl = colour_weight(crop, desc["colour"])
    R, mask = widget(crop.shape)
    if support is not None and support.shape != mask.shape:
        return {**base, "found": None, "reason": "support_shape"}

    if shape in ("segments", "curve"):
        fits = (fit_segments if shape == "segments" else fit_curve)(tl, mask, desc, support)
        if not fits:
            return {**base, "found": False, "reason": "no_component", "alternatives": []}
        best = fits[0]
        alts = [{k: f[k] for k in ("score", "x0", "y0", "x1", "y1", "piece") if k in f}
                for f in fits[1:4]]
        why = (None if best["accepted"] else "piece_only" if best.get("piece")
               and best["score"] >= ACCEPT[shape] else "below_accept")
        return {**base, **best, "path": "free", "found": bool(best["accepted"]),
                "reason": why, "alternatives": alts}

    geo = desc.get("geo")
    radii = candidate_radii(desc["radius_px"]) if shape == "ring" else None

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
    # One coarse surface and one exact scorer serve the seeded and the
    # widened ring.
    surf = RingSurface(tl, ms, radii=radii) if shape == "ring" else None
    rad = _Radial(tl, mask, radii, ms) if shape == "ring" else None
    if prior == "caster" and seed is not None:
        out = placed(dict(fit_ring(tl, mask, ms, seed, ms.px(RING_SEED_HALF_BASE), _radial=rad,
                                   support=support, _surface=surf, radii=radii) if shape == "ring"
                          else fit_beam(tl, mask, seed[0], seed[1], ms, geo=geo), path="seeded"))
        if clears(out):
            return {**base, **out, "found": True, "reason": None}
    prior_fit = out
    if shape == "ring":
        out = dict(fit_ring(tl, mask, ms, _radial=rad, support=support, _surface=surf,
                            radii=radii),
                   path="free" if prior == "free" else "widened")
    else:
        out = widened_beam(tl, mask, ms, support, seed, geo=geo)
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
