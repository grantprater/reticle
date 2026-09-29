r"""The self icon read as a teardrop: its centre, where the player's viewcone starts.

Owns [owns:self-cone-origin].

The player's minimap icon is a pale yellow ring round the agent portrait plus
a filled lobe whose two edges are tangent to the ring's outer circle and meet
at the apex. `minimap.self_icons` fits a CIRCLE to the thresholded yellow key,
and the lobe pulls that circle's centre toward the apex: a median 4.4 px on
e78e75b2d191 and 2.8 px on 5822b6646448 (docs/STATISTICAL_ADJUDICATOR.md, E3
and E4). The rays of the drawn light start at the teardrop's centre with no
offset, and the half-angle stays `cone.CONE_HALF_ANGLE_DEG`
[domain:minimap/cone-origin-near-centre]. So `team_vision` casts the self cone
from this reader's centre.

**The fit** (promoted from `prototypes/teardrop_tip.py`, `teardrop-tip-0.1.0`,
its model and search unchanged; the grid correlates by `cv2.matchTemplate`). It renders the silhouette -- the teardrop of
outer radius `R_OUT` and apex distance `L`, less the portrait disc of radius
`R_IN` -- with a soft edge, and scores it by normalised correlation against a
continuous yellowness (no threshold) over a window round the detector's
centre. A grid over centre and facing, then a compass search to a twentieth of
a pixel and a quarter degree. Below `MIN_NCC` the shape is not read.

**What it answers and what it does not.** `fit_teardrop` returns the centre and also the
teardrop's facing. The centre is the product. The FACING is a raw observation
here and nothing consumes it: on Lotus it agrees with the drawn light to a
median 10.8 degrees against 1.9 on Ascent, and no light witness separates the
reader from the walls there, so it waits on the player's labels. The cone's
bearing stays `track.Track.resolved_facing`.

**An unread teardrop is a reason, never a guess.** `fit_teardrop` returns
`read: False` with `no_yellow` or `low_ncc`; on 5822b6646448 a fifth of the
self detections are a yellow ability icon in a teammate stack, which the shape
rightly refuses. The caller falls back to the ring fit's centre and records
which origin it used.

**Scale.** The constants were fitted on e78e75b2d191 at `widget_scale` 1.0
(the bigmap profile at 1080p) and scale linearly with the widget. A widget
drawn at another scale has not been measured.

It reads one crop and decides nothing about identity or position.
"""
from __future__ import annotations

import hashlib
import math

import numpy as np

from .version import TEARDROP_VERSION  # noqa: F401  (the stamp callers store)

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


class OriginReader:
    """The self cone's origin per frame: the teardrop's centre, or the ring fit's.

    The minimap repeats one image across several cached frames, so the reader
    keeps the last fit keyed by the pixels it scored and the seed; a repeat
    returns the same fit without recomputing it, and the answer is the one a
    fresh fit gives.
    """

    def __init__(self, scale: float = 1.0):
        self.scale = scale
        self._last: tuple | None = None

    def origin(self, crop: np.ndarray, cx: float, cy: float) -> dict:
        """`{"x", "y", "source", ...}` for a self fit centred at `(cx, cy)`.

        `source` is `teardrop` where the shape reads; otherwise `ring_fit`,
        the detector's own centre, with the teardrop's `reason`.
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
            return {"x": float(tf["x"]), "y": float(tf["y"]), "source": "teardrop",
                    "ncc": float(tf["ncc"]), "teardrop_deg": float(tf["deg"])}
        return {"x": float(cx), "y": float(cy), "source": "ring_fit",
                "ncc": _num(tf.get("ncc")), "reason": tf.get("reason")}


def _num(v):
    return None if v is None else float(v)
