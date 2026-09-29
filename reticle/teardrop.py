r"""The self icon read as a teardrop: where the player's viewcone starts and which way it faces.

Owns [owns:self-cone-origin].

The player's minimap icon is a pale yellow ring round the agent portrait plus
a filled lobe whose two edges are tangent to the ring's outer circle and meet
at the apex. `minimap.self_icons` fits a CIRCLE to the thresholded yellow key,
and the lobe pulls that circle's centre toward the apex: a median 4.4 px on
e78e75b2d191 and 2.8 px on 5822b6646448 (docs/STATISTICAL_ADJUDICATOR.md, E3
and E4). The rays of the drawn light start at the teardrop's centre with no
offset, and the half-angle stays `cone.CONE_HALF_ANGLE_DEG`
[domain:minimap/cone-origin-near-centre]. The circle fit's facing is the lobe
seen through a threshold, and flips on half of the Lotus frames the player
labelled; the teardrop points one way and needs no lobe resolution. So
`team_vision` casts the self cone from this reader's centre along its facing.

**The fit** (promoted from `prototypes/teardrop_tip.py`, `teardrop-tip-0.1.0`,
its model and search unchanged; the grid correlates by `cv2.matchTemplate`).
It renders the silhouette -- the teardrop of outer radius `R_OUT` and apex
distance `L`, less the portrait disc of radius `R_IN` -- with a soft edge, and
scores it by normalised correlation against a continuous yellowness (no
threshold) over a window round the detector's centre. A grid over centre and
facing, then a compass search to a twentieth of a pixel and a quarter degree.
Below `MIN_NCC` the shape is not read.

**The facing against the player.** On 28 blind labels of 5822b6646448 the
teardrop's facing errs a median 2.2 degrees and flips on 7%; the ring fit's
errs 105.5 and flips on half; the eight Ascent controls err 1.8 with no flip
(docs/STATISTICAL_ADJUDICATOR.md, "The labels", which cites the run).

**An unread teardrop is a reason, never a guess.** `fit_teardrop` returns
`read: False` with `no_yellow` or `low_ncc`; on 5822b6646448 a fifth of the
self detections are a yellow ability icon in a teammate stack, which the shape
rightly refuses. `SelfConeReader` then returns the ring fit's centre and no
facing, says why, and the caller keeps its own bearing.

**Scale.** The constants were fitted on e78e75b2d191 at `widget_scale` 1.0
(the bigmap profile at 1080p) and scale linearly with the widget. A widget
drawn at another scale has not been measured.

**Teammates and enemies** (owns [owns:icon-pose], `ICON_TEARDROP_VERSION`).
They wear the same teardrop in other colours, and `fit_icon` reads it with
the class's key, radii and refusal gates (`ICON_CLASSES`), promoted from
`prototypes/icon_teardrop.py` (`icon-teardrop-0.1.0`) with its model
unchanged. On the player's blind labels of 5822b6646448 and a06f04a0059f
its facing errs a median 2.5 degrees on allies and 1.7 on enemies, with no
flip, where the ring fit flips on about half
(docs/STATISTICAL_ADJUDICATOR.md, E6, which cites the run). Its constants
were fitted on 465 px widgets; 0.2.0 scales them by `minimap.widget_scale`
as the self teardrop's are, so on a 331 px widget the centre lands on the
portrait instead of about 6 px off it. `IconPoseReader` returns an ally's
centre and facing per frame, or the ring fit's centre and no facing with
the reason. The ring fit still FINDS the icon; where the teardrop reads,
it supplies neither centre nor facing.

**On a turned widget** the facing needs no correction: the icons' facing
arrows turn with the map [domain:minimap/upright-icons-on-turned-map], and
the fit reads the arrow as drawn in the crop, which is the frame every cone
is cast in.

It reads one crop and decides nothing about identity or position.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .version import ICON_TEARDROP_VERSION, TEARDROP_VERSION  # noqa: F401  (the stamps callers store)

# Fitted by `prototypes/teardrop_tip.py --calibrate` on 24 held-out frames of
# e78e75b2d191 at widget scale 1.0: mean correlation 0.846, on a plateau over
# L 18-19 px and ring width 1.5-2 px.
R_IN, R_OUT, L = 9.5, 11.0, 18.0
EDGE = 1.5            # soft edge width, px: chroma is subsampled 2x2
WINDOW = 4.0          # the scoring window reaches this far past the apex
SEARCH_PX = 4         # centre grid half-width round the detector's centre
GRID_DEG = 10.0
MIN_NCC = 0.5         # below this the shape is not read


def yellowness(crop: np.ndarray) -> np.ndarray:
    """How yellow each pixel is, in [0, 1]: min(G, R) - B, ramped over 10..60.

    Continuous, so the fit sees the anti-aliased and chroma-blurred edge rather
    than a threshold's staircase. Lit floor sits near 10, the ring near 70-90.
    """
    c = crop.astype(np.float32)
    y = np.minimum(c[..., 1], c[..., 2]) - c[..., 0]
    return np.clip((y - 10.0) / 50.0, 0.0, 1.0)


def render(dx, dy, th, r_in=R_IN, r_out=R_OUT, L_=L, edge=EDGE):
    """Soft yellow silhouette at offsets (dx, dy) from the centre, facing `th` radians.

    Broadcasts: `dx`, `dy` shaped (..., P) and `th` shaped (..., 1).
    """
    c, s = np.cos(th), np.sin(th)
    u = dx * c + dy * s
    v = -dx * s + dy * c
    rho = np.hypot(dx, dy)
    ca = r_out / L_
    sa = math.sqrt(max(0.0, 1.0 - ca * ca))
    d_wedge = u * ca + np.abs(v) * sa - r_out
    d_tri = np.maximum(d_wedge, np.maximum(r_out * ca - u, u - L_))
    d_tear = np.minimum(rho - r_out, d_tri)
    d = np.maximum(d_tear, r_in - rho)
    return np.clip(0.5 - d / edge, 0.0, 1.0)


def _correlation(obs, model):
    """Normalised correlation of `obs` (P,) with each model row (..., P)."""
    o = obs - obs.mean()
    m = model - model.mean(axis=-1, keepdims=True)
    den = np.sqrt((o * o).sum() * (m * m).sum(axis=-1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (m * o).sum(axis=-1) / den, -1.0)


def fit_teardrop(crop: np.ndarray, cx0: float, cy0: float, *, scale: float = 1.0,
                 r_in: float | None = None, r_out: float | None = None,
                 L_: float | None = None, yel: np.ndarray | None = None) -> dict:
    """The teardrop nearest the detector's centre `(cx0, cy0)`.

    Returns `x`, `y` (the teardrop's centre, the cone's origin), `deg` (its
    facing, image degrees, y down; an unconsumed observation), `tip_x`,
    `tip_y`, `ncc`, and `read` (False with a `reason` below MIN_NCC).
    `r_in`, `r_out` and `L_` override the scaled constants, in px, for
    `prototypes/teardrop_tip.py --calibrate`.
    """
    r_in = R_IN * scale if r_in is None else r_in
    r_out = R_OUT * scale if r_out is None else r_out
    L_ = L * scale if L_ is None else L_
    edge, search = EDGE * scale, max(1, int(round(SEARCH_PX * scale)))
    yel = yellowness(crop) if yel is None else yel
    h, w = yel.shape
    rad = L_ + WINDOW * scale + search
    x0, x1 = max(0, int(cx0 - rad)), min(w, int(cx0 + rad) + 1)
    y0, y1 = max(0, int(cy0 - rad)), min(h, int(cy0 + rad) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    keep = np.hypot(xx - cx0, yy - cy0) <= rad
    px, py = xx[keep].astype(np.float32), yy[keep].astype(np.float32)
    obs = yel[py.astype(int), px.astype(int)]
    if obs.size == 0 or obs.max() <= 0:
        return {"read": False, "reason": "no_yellow"}

    # The grid: for each facing, one render on the lattice the window slides
    # over, correlated with the window at every integer centre offset
    # (`cv2.matchTemplate`), which is the prototype's per-offset render to
    # float rounding and a tenth of its time.
    sc, x, y, t = _grid(obs, keep, x0, y0, cx0, cy0, search, r_in, r_out, L_, edge)

    def score(x, y, t):
        return float(_correlation(obs, render(px - x, py - y, t, r_in, r_out, L_, edge)))

    step_p, step_t = 0.5, math.radians(3.0)
    while step_p >= 0.05:
        moved = False
        for ddx, ddy, ddt in ((step_p, 0, 0), (-step_p, 0, 0), (0, step_p, 0), (0, -step_p, 0),
                              (0, 0, step_t), (0, 0, -step_t)):
            s2 = score(x + ddx, y + ddy, t + ddt)
            if s2 > sc:
                sc, x, y, t, moved = s2, x + ddx, y + ddy, t + ddt, True
                break
        if not moved:
            step_p, step_t = step_p / 2, step_t / 2
    deg = (math.degrees(t) + 180.0) % 360.0 - 180.0
    out = {"x": x, "y": y, "deg": deg, "ncc": sc,
           "tip_x": x + L_ * math.cos(t), "tip_y": y + L_ * math.sin(t),
           "read": sc >= MIN_NCC}
    if not out["read"]:
        out["reason"] = "low_ncc"
    return out


def _grid(obs, keep, x0, y0, cx0, cy0, search, r_in, r_out, L_, edge):
    """Best `(ncc, x, y, th)` over integer centre offsets within `search` and GRID_DEG facings."""
    import cv2

    h, w = keep.shape
    k = keep.astype(np.float32)
    o = np.zeros((h, w), np.float32)
    o[keep] = obs - obs.mean()
    oo = float((o * o).sum())
    n = float(keep.sum())
    # Lattice index j maps to pixel x0 + j - search, so offset `off` reads
    # j = i - off + search for window index i.
    jy, jx = np.mgrid[0:h + 2 * search, 0:w + 2 * search].astype(np.float32)
    dx = (x0 - search - cx0) + jx
    dy = (y0 - search - cy0) + jy
    best = (-2.0, 0.0, 0.0, 0.0)
    for th in np.radians(np.arange(0.0, 360.0, GRID_DEG, dtype=np.float32)):
        m = render(dx, dy, np.float32(th), r_in, r_out, L_, edge).astype(np.float32)
        s_mo = cv2.matchTemplate(m, o, cv2.TM_CCORR)
        s_m = cv2.matchTemplate(m, k, cv2.TM_CCORR)
        s_mm = cv2.matchTemplate(m * m, k, cv2.TM_CCORR)
        var = s_mm - s_m * s_m / n
        with np.errstate(invalid="ignore", divide="ignore"):
            sc = np.where(var > 1e-9, s_mo / np.sqrt(np.maximum(var, 0) * oo), -1.0)
        u = np.unravel_index(int(np.argmax(sc)), sc.shape)
        if sc[u] > best[0]:
            best = (float(sc[u]), float(cx0 + search - u[1]), float(cy0 + search - u[0]), float(th))
    return best


class SelfConeReader:
    """The self cone's origin and facing per frame, from the teardrop.

    The minimap repeats one image across several cached frames, so the reader
    keeps the last fit keyed by the pixels it scored and the seed; a repeat
    returns the same fit without recomputing it, and the answer is the one a
    fresh fit gives.
    """

    def __init__(self, scale: float = 1.0):
        self.scale = scale
        self._last: tuple | None = None

    def read(self, crop: np.ndarray, cx: float, cy: float) -> dict:
        """`{"x", "y", "deg", "origin", "ncc", ...}` for a self fit centred at `(cx, cy)`.

        Where the shape reads, `origin` is `teardrop` and `x`, `y`, `deg` are
        its centre and facing (image degrees, y down). Otherwise `origin` is
        `ring_fit`: `x`, `y` are the detector's own centre, `deg` is None and
        `reason` says why the teardrop was not read.
        """
        rad = (L + WINDOW + SEARCH_PX) * self.scale + 1
        h, w = crop.shape[:2]
        win = crop[max(0, int(cy - rad)):min(h, int(cy + rad) + 2),
                   max(0, int(cx - rad)):min(w, int(cx + rad) + 2)]
        key = (hashlib.blake2b(np.ascontiguousarray(win).tobytes(), digest_size=16).digest(),
               win.shape, float(cx), float(cy))
        if self._last is not None and self._last[0] == key:
            tf = self._last[1]
        else:
            tf = fit_teardrop(crop, cx, cy, scale=self.scale)
            self._last = (key, tf)
        if tf.get("read"):
            return {"x": float(tf["x"]), "y": float(tf["y"]), "deg": float(tf["deg"]),
                    "origin": "teardrop", "ncc": float(tf["ncc"])}
        return {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                "ncc": _num(tf.get("ncc")), "reason": tf.get("reason")}


def _num(v):
    return None if v is None else float(v)


# ------------------------------------------------------------ teammates, enemies

def tealness(crop: np.ndarray) -> np.ndarray:
    """How teal each pixel is, in [0, 1]: min(G, B) - R, ramped over 10..60,
    faded out where B exceeds G by more than 10 (the blue death X, the blue
    ability glyphs). Keyed ally pixels sit at G - B of 20 to 50."""
    c = crop.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    y = np.clip((np.minimum(g, b) - r - 10.0) / 50.0, 0.0, 1.0)
    return y * np.clip((g - b + 30.0) / 20.0, 0.0, 1.0)


def redness(crop: np.ndarray) -> np.ndarray:
    """How red each pixel is, in [0, 1]: R - max(G, B), ramped over 15..65."""
    c = crop.astype(np.float32)
    y = c[..., 2] - np.maximum(c[..., 0], c[..., 1])
    return np.clip((y - 15.0) / 50.0, 0.0, 1.0)


@dataclass(frozen=True)
class IconClass:
    """One class's key, radii at widget scale 1.0, and refusal gates."""

    name: str
    key: Callable[[np.ndarray], np.ndarray]
    r_in: float
    r_out: float
    L: float
    min_ncc: float
    min_margin: float
    min_ring: float


#: Fitted by `prototypes/icon_teardrop.py --calibrate` on held-out minutes
#: (every fourth) of 5822b6646448 and a06f04a0059f, both 465 px widgets.
ICON_CLASSES = {
    # 100 read detections: mean NCC 0.766, a plateau over ring width 1.5-2
    # and L 18-20 at r_out 10.5. The ally ring turns pale away from the lobe,
    # so a ring-coverage gate refused real teammates; the ally class has none.
    "ally": IconClass("ally", tealness, 8.5, 10.5, 19.0, 0.5, 0.05, 0.0),
    # 53 read detections: mean NCC 0.741, a ridge along r_in 7-7.5 for r_out
    # 10.5-11 and L 18-19. The ring gate refuses spawn barriers and red map
    # fills, which the enemy ring fit takes for icons.
    "enemy": IconClass("enemy", redness, 7.5, 10.5, 18.0, 0.5, 0.05, 0.4),
}
MARGIN_DEG = 5.0      # facing grid for the ambiguity margin


def _signed_deg(a):
    return (np.asarray(a, dtype=float) + 180.0) % 360.0 - 180.0


def _window(key: np.ndarray, cx0: float, cy0: float, reach: float):
    h, w = key.shape
    x0, x1 = max(0, int(cx0 - reach)), min(w, int(cx0 + reach) + 1)
    y0, y1 = max(0, int(cy0 - reach)), min(h, int(cy0 + reach) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    keep = np.hypot(xx - cx0, yy - cy0) <= reach
    px, py = xx[keep].astype(np.float32), yy[keep].astype(np.float32)
    return px, py, key[py.astype(int), px.astype(int)]


def fit_icon(crop: np.ndarray | None, cls: "str | IconClass", cx0: float, cy0: float, *,
             scale: float = 1.0, key: np.ndarray | None = None,
             r_in: float | None = None, r_out: float | None = None,
             L_: float | None = None) -> dict:
    """The `cls` teardrop (`ally`, `enemy`, or an `IconClass`) nearest the detector's centre `(cx0, cy0)`.

    Returns `fit_teardrop`'s fields (`x`, `y`, `deg`, `tip_x`, `tip_y`,
    `ncc`) plus `margin` (the best NCC less the best at any facing 90 degrees
    or more away, at the fitted centre), `ring_cover`, `cls` and `read`. An
    unread fit carries `reason` and no `deg` a caller may use:

        low_ncc           the silhouette explains too little of the colour
        no_ring           under `min_ring` of the ring away from the lobe is
                          keyed: a spawn barrier or a red map fill
        ambiguous_facing  a facing 90 degrees or more away scores within
                          `min_margin`, so the lobe is not seen
        no_key            no keyed pixel near the detector's centre

    The radii scale by `scale` (`minimap.widget_scale`) unless given in px;
    `key` is the class's key over `crop`, computed once per frame by a caller
    fitting several icons.
    """
    c = cls if isinstance(cls, IconClass) else ICON_CLASSES[cls]
    cls = c.name
    r_in = c.r_in * scale if r_in is None else r_in
    r_out = c.r_out * scale if r_out is None else r_out
    L_ = c.L * scale if L_ is None else L_
    edge = EDGE * scale
    key = c.key(crop) if key is None else key
    f = fit_teardrop(None, cx0, cy0, scale=scale, r_in=r_in, r_out=r_out, L_=L_, yel=key)
    f["cls"] = cls
    if "x" not in f:
        return {"cls": cls, "read": False, "reason": "no_key"}
    px, py, obs = _window(key, f["x"], f["y"], L_ + WINDOW * scale)
    ths = np.radians(np.arange(0.0, 360.0, MARGIN_DEG, dtype=np.float32))
    sc = _correlation(obs, render(px[None, :] - f["x"], py[None, :] - f["y"], ths[:, None],
                                  r_in, r_out, L_, edge))
    far = np.abs(_signed_deg(np.degrees(ths) - f["deg"])) >= 90.0
    f["margin"] = float(f["ncc"] - sc[far].max())
    f["ring_cover"] = ring_cover(key, f["x"], f["y"], f["deg"], r_in, r_out, pad=0.5 * scale)
    f["read"] = True
    f.pop("reason", None)
    if f["ncc"] < c.min_ncc:
        f.update(read=False, reason="low_ncc")
    elif f["ring_cover"] < c.min_ring:
        f.update(read=False, reason="no_ring")
    elif f["margin"] < c.min_margin:
        f.update(read=False, reason="ambiguous_facing")
    return f


def ring_cover(key: np.ndarray, x: float, y: float, deg: float, r_in: float, r_out: float,
               n_bins: int = 36, away_deg: float = 60.0, min_key: float = 0.5,
               pad: float = 0.5) -> float:
    """Share of the ring's angular bins, away from the lobe, whose annulus is keyed.

    The ring is what a spawn barrier, a map fill or a stray glyph lacks: a
    straight red bar crosses the annulus twice and scores the lobe's NCC
    well enough. Bins within `away_deg` of the facing hold the lobe and are
    skipped; a bin is covered when the brightest key in the annulus
    `[r_in - pad, r_out + pad]` within it reaches `min_key`. The brightest,
    not the mean: the teal ring is 1-2 px of a 3 px band whose inner edge is
    the portrait's dark rim.
    """
    h, w = key.shape
    R = int(math.ceil(r_out + 2 * pad))
    x0, x1 = max(0, int(x) - R), min(w, int(x) + R + 2)
    y0, y1 = max(0, int(y) - R), min(h, int(y) + R + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rho = np.hypot(xx - x, yy - y)
    ang = np.degrees(np.arctan2(yy - y, xx - x))
    band = (rho >= r_in - pad) & (rho <= r_out + pad)
    rel = np.abs(_signed_deg(ang - deg))
    keep = band & (rel >= away_deg)
    if not keep.any():
        return 0.0
    b = ((ang[keep] + 180.0) / 360.0 * n_bins).astype(int) % n_bins
    v = key[y0:y1, x0:x1][keep]
    peak = np.full(n_bins, -1.0)
    np.maximum.at(peak, b, v)
    used = peak >= 0
    return float(np.mean(peak[used] >= min_key))


class IconPoseReader:
    """A teammate's or an enemy's centre and facing per frame, from the teardrop.

    The class's key is computed once per image and the image's fits are
    memoised by its pixels, so the minimap's repeated images (several cached
    frames hold one image) and the same icon asked twice return the fit a
    fresh one gives without recomputing it.
    """

    def __init__(self, cls: str = "ally", scale: float = 1.0):
        self.cls, self.scale = cls, scale
        self._digest: bytes | None = None
        self._key: np.ndarray | None = None
        self._fits: dict = {}

    def read(self, crop: np.ndarray, cx: float, cy: float) -> dict:
        """`{"x", "y", "deg", "origin", "ncc", ...}` for a detection centred at `(cx, cy)`.

        Where the shape reads, `origin` is `teardrop` and `x`, `y`, `deg` are
        its centre and facing (image degrees, y down). Otherwise `origin` is
        `ring_fit`: `x`, `y` are the detector's own centre, `deg` is None and
        `reason` says why the teardrop was not read.
        """
        digest = hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=16).digest()
        if digest != self._digest:
            self._digest, self._key, self._fits = digest, None, {}
        k = (float(cx), float(cy))
        tf = self._fits.get(k)
        if tf is None:
            if self._key is None:
                self._key = ICON_CLASSES[self.cls].key(crop)
            tf = self._fits[k] = fit_icon(None, self.cls, cx, cy, scale=self.scale, key=self._key)
        if tf.get("read"):
            return {"x": float(tf["x"]), "y": float(tf["y"]), "deg": float(tf["deg"]),
                    "origin": "teardrop", "ncc": float(tf["ncc"]),
                    "margin": float(tf["margin"])}
        return {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                "ncc": _num(tf.get("ncc")), "reason": tf.get("reason")}
