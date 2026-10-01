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


def ring_radii(R: float) -> np.ndarray:
    """The searched ring radii: RING_R of the widget radius, in half pixels."""
    return np.arange(RING_R[0] * R, RING_R[1] * R + 0.01, 0.5)


class _Kernels:
    """Disc-kernel FFTs and the widget's band counts for one crop size and
    scale. They depend on the size alone, so they are built once a size."""

    _cache: dict = {}

    @classmethod
    def of(cls, shape, R: float, scale: float) -> "_Kernels":
        key = (tuple(shape), round(R, 3), scale)
        if key not in cls._cache:
            cls._cache[key] = cls(tuple(shape), R, scale)
        return cls._cache[key]

    def __init__(self, shape, R: float, scale: float):
        h, w = shape
        full = ring_radii(R)
        self.radii = full if scale == 1.0 else full[::2]
        r, s = self.radii * scale, scale
        i = [np.clip(np.round(a * 2).astype(int), 0, None)
             for a in (r - 1.5 * s, r - 6 * s, r + 3 * s)]
        j = [np.clip(np.round(b * 2).astype(int), 0, None)
             for b in (r + 1.5 * s, r - 3 * s, r + 6 * s)]
        self.ks = np.unique(np.concatenate(i + j))
        pos = {int(k): n for n, k in enumerate(self.ks)}
        self.jn = [np.array([pos[int(k)] for k in a]) for a in j]
        self.im = [np.array([pos[int(k)] for k in a]) for a in i]
        W = int(np.ceil(r.max() + 7 * s))
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

    def __init__(self, tl: np.ndarray, R: float, scale: float = COARSE_SCALE):
        self.scale = scale
        small = (tl if scale == 1.0 else
                 cv2.resize(tl, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA))
        K = self.K = _Kernels.of(small.shape, R, scale)
        T, M = K.conv((small * K.mask).astype(np.float32), small.shape), K.M
        best = np.full(small.shape, -2.0, np.float32)
        arg = np.zeros(small.shape, np.int32)
        for q in range(len(K.radii)):
            vals = []
            for b in range(3):
                jn, im = K.jn[b][q], K.im[b][q]
                cnt = M[jn] - M[im]
                with np.errstate(invalid="ignore", divide="ignore"):
                    vals.append(np.where(cnt >= 8, (T[jn] - T[im]) / np.maximum(cnt, 1), np.nan))
            out = vals[0] - np.fmax(vals[1], vals[2])
            out = np.where(np.isnan(out), -1.0, out).astype(np.float32)
            better = out > best
            best[better] = out[better]
            arg[better] = q
        best[~K.mask] = -2.0
        self.best, self.arg = best, arg

    def peaks(self, R: float, k: int = REFINE_K, sep_frac: float = 0.1,
              centre=None, half=None, allowed: np.ndarray | None = None) -> list:
        """The `k` best local maxima at least `sep_frac` R apart, as (score,
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
        sep = max(1, int(round(sep_frac * R * s)))
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


def fit_ring(tl: np.ndarray, mask: np.ndarray, R: float,
             centre: tuple[float, float] | None = None, half: float | None = None,
             step: int | None = None, _radial: _Radial | None = None,
             support: np.ndarray | None = None,
             _surface: RingSurface | None = None) -> dict:
    """The best ring, searched round `centre` (within `half`) or everywhere:
    the score is mean teal on the annulus [r-1.5, r+1.5) minus the brighter of
    [r-6, r-3) and [r+3, r+6).

    Coarse to fine (0.2.0): the coarse `RingSurface` proposes its REFINE_K
    best centres, and the exact score is maximised on a window of
    REFINE_HALF px round each. With `support`, a centre must lie on it (the
    centre-on-footprint gate): a ring centred over the void is a false ring,
    while teal still counts wherever it is drawn. `step` was 0.1.0's stride
    and is no longer read.
    """
    rad = _radial or _Radial(tl, mask, ring_radii(R))
    surf = _surface or RingSurface(tl, R)
    allowed = None if support is None else (support & mask)
    cands = surf.peaks(R, centre=centre, half=half, allowed=allowed)
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


def ring_candidates(tl: np.ndarray, mask: np.ndarray, R: float,
                    support: np.ndarray | None = None, min_coarse: float = 0.10,
                    _surface: RingSurface | None = None) -> list[dict]:
    """The whole-widget ring search a scan of every caster stores: each
    coarse peak scoring at least `min_coarse`, refined as `fit_ring` refines
    its best, best first. `accepted` is ACCEPT's verdict on each."""
    rad = _Radial(tl, mask, ring_radii(R))
    surf = _surface or RingSurface(tl, R)
    allowed = None if support is None else (support & mask)
    out = []
    for c in surf.peaks(R, allowed=allowed):
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


def _beam(tl, mask, vx, vy, th, R):
    c, s = np.cos(np.radians(th)), np.sin(np.radians(th))
    lp, dp = vx * c + vy * s, np.abs(-vx * s + vy * c)
    hw, col = BEAM_HALF * R, BEAM_COLLAR * R
    along = (lp >= BEAM_NEAR_PX) & (lp <= BEAM_REACH * R) & mask
    strip, collar = along & (dp <= hw), along & (dp > hw) & (dp <= hw + col)
    if strip.sum() < 20 or collar.sum() < 20:
        return -1.0, lp, strip
    return float(tl[strip].mean() - tl[collar].mean()), lp, strip


def beam_sweep(tl: np.ndarray, mask: np.ndarray, ox: float, oy: float, R: float,
               step: float = BEAM_STEP_DEG) -> tuple[np.ndarray, np.ndarray]:
    """The beam score (strip minus collar) at every angle of a `step` grid.

    A pixel at distance rho and bearing phi from the origin lies in the
    strip of angle theta when |theta - phi| <= asin(half / rho), so each
    pixel adds its teal to one interval of the angle grid, and a difference
    array sums every interval in one pass."""
    ys, xs = np.nonzero(mask)
    vx, vy = xs - ox, ys - oy
    rho = np.hypot(vx, vy)
    sel = (rho >= BEAM_NEAR_PX) & (rho <= BEAM_REACH * R)
    rho, phi = rho[sel], np.degrees(np.arctan2(vy[sel], vx[sel])) % 360.0
    t = tl[ys[sel], xs[sel]].astype(np.float64)
    hw, col = BEAM_HALF * R, BEAM_COLLAR * R
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
        sc = np.where((n1 >= 20) & (n2 >= 20), s1 / n1 - s2 / n2, -1.0)
    return np.arange(nb) * step, sc


def fit_beam(tl: np.ndarray, mask: np.ndarray, ox: float, oy: float, R: float,
             around: float | None = None) -> dict:
    """The best beam from (ox, oy), swept over every angle at BEAM_STEP_DEG
    (0.2.0), or within BEAM_AROUND_DEG of `around`. The score is mean teal in
    the strip minus mean teal in the collars either side; the beam ends where
    the strip's teal falls below half its peak."""
    th, sc = beam_sweep(tl, mask, ox, oy, R)
    if around is not None:
        d = np.abs((th - around + 180) % 360 - 180)
        sc = np.where(d <= BEAM_AROUND_DEG, sc, -2.0)
    k = int(np.argmax(sc))
    best, thb = float(sc[k]), float(th[k])
    h, w = tl.shape
    yy, xx = np.mgrid[0:h, 0:w]
    _, lp, strip = _beam(tl, mask, xx - ox, yy - oy, thb, R)
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


def widened_beam(tl: np.ndarray, mask: np.ndarray, R: float,
                 support: np.ndarray | None = None,
                 seed: tuple[float, float] | None = None) -> dict | None:
    """The beam along the longest straight teal segment on the map, or None
    where there is none: the widened search of `fit_shape`, and the whole
    beam search of a scan of every caster (no seed).

    The end nearer `seed` is the caster's, and the row says `oriented`;
    without a seed the end is unknown. The caster's icon sits before the
    drawn blast, as in the seeded geometry, so the origin goes BEAM_NEAR_PX
    behind the segment's end."""
    seg = longest_segment(tl, mask, R, support)
    if seg is None:
        return None
    (ax, ay), (bx, by) = seg
    if seed is not None and (np.hypot(bx - seed[0], by - seed[1])
                             < np.hypot(ax - seed[0], ay - seed[1])):
        (ax, ay), (bx, by) = (bx, by), (ax, ay)
    th = float(np.degrees(np.arctan2(by - ay, bx - ax)))
    ox = ax - BEAM_NEAR_PX * np.cos(np.radians(th))
    oy = ay - BEAM_NEAR_PX * np.sin(np.radians(th))
    out = dict(fit_beam(tl, mask, ox, oy, R, around=th), path="widened",
               oriented=seed is not None)
    if support is not None:
        out["on_map"] = on_map(out, support)
    return out


def beam_accepted(f: dict | None) -> bool:
    """ACCEPT's verdict on a beam: its score, and BEAM_ON_MAP of its run on
    the map where a support placed it."""
    return (f is not None and f["score"] >= ACCEPT["beam"]
            and f.get("on_map", 1.0) >= BEAM_ON_MAP)


# ------------------------------------------------------------------- fit

def fit_shape(crop: np.ndarray | None, ability: str,
        seed: tuple[float, float] | None, support: np.ndarray | None = None) -> dict:
    """One observation of `ability`'s drawn shape in one minimap crop.

    `seed` is where the caster is believed to be (widget pixels), or None.
    `support` is the map's footprint (`geometry.footprint` at SUPPORT_DILATE).
    Teal counts over the whole widget, because the shapes are drawn over the
    void too; the support only places a shape: a ring's centre lies on it
    (0.2.0) and a beam lies BEAM_ON_MAP on it. Without it nothing is placed,
    and the row's `support` is None.
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
    # One coarse surface and one exact scorer serve the seeded and the
    # widened ring.
    surf = RingSurface(tl, R) if shape == "ring" else None
    rad = _Radial(tl, mask, ring_radii(R)) if shape == "ring" else None
    if prior == "caster" and seed is not None:
        out = placed(dict(fit_ring(tl, mask, R, seed, RING_SEED_HALF * R, _radial=rad,
                                   support=support, _surface=surf) if shape == "ring"
                          else fit_beam(tl, mask, seed[0], seed[1], R), path="seeded"))
        if clears(out):
            return {**base, **out, "found": True, "reason": None}
    prior_fit = out
    if shape == "ring":
        out = dict(fit_ring(tl, mask, R, _radial=rad, support=support, _surface=surf),
                   path="free" if prior == "free" else "widened")
    else:
        out = widened_beam(tl, mask, R, support, seed)
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
