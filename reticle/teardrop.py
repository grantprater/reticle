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
(the bigmap profile at 1080p) and scale linearly with the widget. On the
331 px widget the player's labels set the facing gate at NCC 0.55
(`SELF_FACING_GATES`); a widget drawn at another scale has not been
measured and takes `SELF_FACING_MIN_NCC`.

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
it supplies neither centre nor facing. Given a frame index, the reader
continues each icon's fit on the previous image with a local search, runs
the full grid on surprise, and audits the prior on a fixed frame cadence
(`IconPoseReader`, ICON_POSE_PRIOR_VERSION); `SelfConeReader` given a frame
index continues the self icon's fit under the same rule.

**On a turned widget** the facing needs no correction: the icons' facing
arrows turn with the map [domain:minimap/upright-icons-on-turned-map], and
the fit reads the arrow as drawn in the crop, which is the frame every cone
is cast in.

It reads one crop and decides nothing about identity or position.
"""
from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Callable

import numpy as np

from .usage import step
# The stamps callers store.
from .version import ICON_POSE_PRIOR_VERSION, ICON_TEARDROP_VERSION, TEARDROP_VERSION  # noqa: F401

# Fitted by `prototypes/teardrop_tip.py --calibrate` on 24 held-out frames of
# e78e75b2d191 at widget scale 1.0: mean correlation 0.846, on a plateau over
# L 18-19 px and ring width 1.5-2 px.
R_IN, R_OUT, L = 9.5, 11.0, 18.0
EDGE = 1.5            # soft edge width, px: chroma is subsampled 2x2
WINDOW = 4.0          # the scoring window reaches this far past the apex
SEARCH_PX = 4         # centre grid half-width round the detector's centre
GRID_DEG = 10.0
MIN_NCC = 0.5         # below this the shape is not read

# The prior (`IconPoseReader` given a frame index): an icon continues its fit
# on the previous image. Measured on the stored ally-icon-0.6.0 streams of
# 587c15b07779, 5822b6646448 (465 px) and 223d636bf8d2 (331 px), between
# teardrop reads 4-5 frames apart (15 Hz) whose ring fits lie within 12 px:
# the teardrop's centre moves a median 0.4-0.9 px and stays within 3 px on
# 98.6-99.5% of pairs; the ring fit's centre stays within 6 px on 99.0-99.7%;
# the facing turns within 30 degrees on 97.2-98.0%; the NCC drops by more
# than 0.1 on 0.4-0.6%. The prior's centre predicts the new centre better
# than the prior moved by the ring fit's displacement (within 2 px on 95-96%
# of pairs against 86-92%).
PRIOR_PX = 6.0        # a detection's ring centre within this of a prior's (x scale)
PRIOR_GAP_MS = 200.0  # a prior seen longer ago than this is no prior (three 15 Hz samples)
LOCAL_PX = 3          # local centre half-width at scale 1.0 (`local_px`)
LOCAL_DEG = 30.0      # local facings: the prior's +- this, in GRID_DEG steps
NCC_DROP = 0.10       # a local fit this far under its prior's NCC is a surprise
AUDIT_FRAMES = 40     # the first new image in each block of this many frames is audited
# The self icon's prior is continued only from a fit at this NCC or above. On
# 5822b6646448 473-573 s and a06f04a0059f 600-760 s (465 px) the self prior
# path, read beside the full search, left it (centre > 1 px or facing > 10
# degrees) on 24 of 165 reads continuing a prior under 0.65 and on 2 of 2,182
# from 0.65 up. Under 0.65 the local fit's NCC was the higher on 8 of the 24,
# so the full grid is no truth there either; the gate keeps the self channel's
# answers where the full search puts them.
SELF_PRIOR_MIN_NCC = 0.65
# Prior-searched refusals in a row before the full grid runs again. Unbounded,
# over the seven test windows (ally channel), a refusal searched round a
# refusal was one the full grid read on 2 of 436 reads at chain 1, 9 of 687 at
# chains 2-10 and 0 of 127 past 10: the rate does not climb with the chain
# through 10, and past 10 too few reads remain to show it does not. The bound
# stops a chain where the measurement stops vouching for it.
REFUSAL_CHAIN = 10
# The compass's first step (px; facing in proportion) where the local grid's
# best is the prior's own pose, which the prior's refinement already placed.
# Against a 0.5 px start over the seven test windows it changed no published
# icon count or ally-count error, moved the full search's disagreement within
# noise (facing > 10 degrees 192 -> 197 of ~16,360 reads, Fisher p = 0.8) and
# cut the refinement's time 5-15% on every window; a 0.25 px start saved
# nothing measurable.
PRIOR_REFINE_STEP = 0.125


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
                 L_: float | None = None, yel: np.ndarray | None = None,
                 prior: tuple[float, float, float] | None = None) -> dict:
    """The teardrop nearest the detector's centre `(cx0, cy0)`.

    Returns `x`, `y` (the teardrop's centre, the cone's origin), `deg` (its
    facing, image degrees, y down; an unconsumed observation), `tip_x`,
    `tip_y`, `ncc`, and `read` (False with a `reason` below MIN_NCC).
    `r_in`, `r_out` and `L_` override the scaled constants, in px, for
    `prototypes/teardrop_tip.py --calibrate`.

    `prior` `(x, y, deg)` is the same icon's fit on an earlier image: the
    grid then searches `local_px(scale)` round its centre and `LOCAL_DEG`
    round its facing instead of the full grid, over the same window and
    score, and the same refinement follows, from `PRIOR_REFINE_STEP` where
    the local grid kept the prior's own pose. `on_edge` says the local grid's
    best lay on its boundary, so the pose may lie outside it.
    """
    r_in = R_IN * scale if r_in is None else r_in
    r_out = R_OUT * scale if r_out is None else r_out
    L_ = L * scale if L_ is None else L_
    edge, search = EDGE * scale, max(1, int(round(SEARCH_PX * scale)))
    h, w = (crop if yel is None else yel).shape[:2]
    rad = L_ + WINDOW * scale + search
    x0, x1 = max(0, int(cx0 - rad)), min(w, int(cx0 + rad) + 1)
    y0, y1 = max(0, int(cy0 - rad)), min(h, int(cy0 + rad) + 1)
    if yel is None:
        # Only the window is scored, so only the window is keyed.
        with step("key"):
            yel, ox, oy = yellowness(crop[y0:y1, x0:x1]), x0, y0
    else:
        ox = oy = 0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    keep = np.hypot(xx - cx0, yy - cy0) <= rad
    px, py = xx[keep].astype(np.float32), yy[keep].astype(np.float32)
    obs = yel[py.astype(int) - oy, px.astype(int) - ox]
    if obs.size == 0 or obs.max() <= 0:
        return {"read": False, "reason": "no_yellow"}

    # The grid: for each facing, one render on the lattice the window slides
    # over, correlated with the window at every integer centre offset
    # (`cv2.matchTemplate`), which is the prototype's per-offset render to
    # float rounding and a tenth of its time.
    # Named steps (`usage.step`): the grid's renders and correlations, then
    # the refinement's. The local grid round a prior is its own step.
    if prior is None:
        with step("grid"):
            sc, x, y, t, _ = _grid(obs, keep, x0, y0, cx0, cy0, search, r_in, r_out, L_, edge,
                                   _FULL_FACINGS)
    else:
        k = int(LOCAL_DEG // GRID_DEG)
        ths = np.radians(prior[2] + GRID_DEG * np.arange(-k, k + 1, dtype=np.float32))
        with step("prior"):
            sc, x, y, t, on_edge = _grid(obs, keep, x0, y0, prior[0], prior[1],
                                         local_px(scale), r_in, r_out, L_, edge, ths)

    # The compass: six probes scored in one broadcast render, the first
    # improving one in probe order taken. Each row is the render a single
    # probe gets (centre cast to float32 as `px - x` casts it, facing kept
    # float64), so the scores and the move match a probe-at-a-time search.
    step_p, step_t = 0.5, math.radians(3.0)
    if (prior is not None and abs(x - prior[0]) < 1e-6 and abs(y - prior[1]) < 1e-6
            and abs(t - math.radians(prior[2])) < 1e-6):
        # The local grid kept the prior's refined pose: start the compass finer.
        step_p, step_t = PRIOR_REFINE_STEP, math.radians(3.0) * PRIOR_REFINE_STEP / 0.5
    with step("refine"):
        while step_p >= 0.05:
            cand = ((x + step_p, y, t), (x - step_p, y, t), (x, y + step_p, t),
                    (x, y - step_p, t), (x, y, t + step_t), (x, y, t - step_t))
            cx = np.array([c[0] for c in cand], np.float32)[:, None]
            cy = np.array([c[1] for c in cand], np.float32)[:, None]
            ct = np.array([c[2] for c in cand], np.float64)[:, None]
            s2 = _correlation(obs, render(px[None, :] - cx, py[None, :] - cy, ct,
                                          r_in, r_out, L_, edge))
            better = np.flatnonzero(s2 > sc)
            if better.size:
                j = int(better[0])
                sc, (x, y, t) = float(s2[j]), cand[j]
            else:
                step_p, step_t = step_p / 2, step_t / 2
    deg = (math.degrees(t) + 180.0) % 360.0 - 180.0
    out = {"x": x, "y": y, "deg": deg, "ncc": sc,
           "tip_x": x + L_ * math.cos(t), "tip_y": y + L_ * math.sin(t),
           "read": sc >= MIN_NCC}
    if prior is not None:
        out["on_edge"] = on_edge
    if not out["read"]:
        out["reason"] = "low_ncc"
    return out


def _grid(obs, keep, x0, y0, cx0, cy0, search, r_in, r_out, L_, edge, facings):
    """Best `(ncc, x, y, th, on_edge)` over integer centre offsets within
    `search` of `(cx0, cy0)` and the `facings` (radians, in order).

    `on_edge`: the best lies on the outer ring of offsets or at the first or
    last facing, which only a local search's caller reads.
    """
    import cv2

    h, w = keep.shape
    o = np.zeros((h, w), np.float32)
    o[keep] = obs - obs.mean()
    oo = float((o * o).sum())
    best = (-2.0, 0.0, 0.0, 0.0, False)
    last = len(facings) - 1
    models = _models(keep, x0 - search - cx0, y0 - search - cy0, search, r_in, r_out, L_, edge,
                     facings)
    for i, (th, (m, var)) in enumerate(zip(facings, models)):
        s_mo = cv2.matchTemplate(m, o, cv2.TM_CCORR)
        with np.errstate(invalid="ignore", divide="ignore"):
            sc = np.where(var > 1e-9, s_mo / np.sqrt(np.maximum(var, 0) * oo), -1.0)
        u = np.unravel_index(int(np.argmax(sc)), sc.shape)
        if sc[u] > best[0]:
            on_edge = i in (0, last) or u[0] in (0, 2 * search) or u[1] in (0, 2 * search)
            best = (float(sc[u]), float(cx0 + search - u[1]), float(cy0 + search - u[0]),
                    float(th), bool(on_edge))
    return best


def _models(keep, ox, oy, search, r_in, r_out, L_, edge, facings) -> list:
    """Each facing's `(model, variance)` for `_grid`: the silhouette rendered
    on the lattice the window slides over, and its variance under the window
    at every offset. Neither reads the observation, so both are memoised by
    every input they read (`_MODELS`): an icon at an integer ring centre
    renders the same lattice on every image. Types are keyed with values,
    since a numpy scalar and a float promote a float32 lattice differently.
    """
    import cv2

    tv = lambda v: (type(v).__name__, float(v))
    fa = np.asarray(facings)
    key = (keep.shape, np.packbits(keep).tobytes(), tv(ox), tv(oy), int(search), tv(r_in),
           tv(r_out), tv(L_), tv(edge), fa.dtype.str, fa.tobytes())
    with _MODELS_LOCK:
        ent = _MODELS.get(key)
        if ent is not None:
            _MODELS.move_to_end(key)
            return ent
    h, w = keep.shape
    k = keep.astype(np.float32)
    n = float(keep.sum())
    # Lattice index j maps to pixel x0 + j - search, so offset `off` reads
    # j = i - off + search for window index i.
    jy, jx = np.mgrid[0:h + 2 * search, 0:w + 2 * search].astype(np.float32)
    dx = ox + jx
    dy = oy + jy
    ent = []
    for th in facings:
        m = render(dx, dy, np.float32(th), r_in, r_out, L_, edge).astype(np.float32)
        s_m = cv2.matchTemplate(m, k, cv2.TM_CCORR)
        s_mm = cv2.matchTemplate(m * m, k, cv2.TM_CCORR)
        ent.append((m, s_mm - s_m * s_m / n))
    with _MODELS_LOCK:
        _MODELS[key] = ent
        if len(_MODELS) > _MODELS_MAX:
            _MODELS.popitem(last=False)
    return ent


#: `_models`' memo, least recently used first. A full grid's entry holds
#: 36 renders of about 63 px square at widget scale 1.0 (about 0.6 MB).
#: The lock serves `pipeline`'s reader threads; an entry is never mutated.
_MODELS: "OrderedDict[tuple, list]" = OrderedDict()
_MODELS_MAX = 64
_MODELS_LOCK = threading.Lock()

_FULL_FACINGS = np.radians(np.arange(0.0, 360.0, GRID_DEG, dtype=np.float32))


def local_px(scale: float) -> int:
    """The local search's centre half-width at `scale`: `LOCAL_PX` scaled, rounded up.

    Rounded up, not to nearest: on the 331 px widget (scale 0.71) a 2 px
    half-width put the local best on its edge for 8% of ally fits on
    223d636bf8d2, where the icon's centre moves more than 2 px between
    samples on 5% of pairs."""
    return max(1, int(math.ceil(LOCAL_PX * scale - 1e-9)))


class SelfConeReader:
    """The self cone's origin and facing per frame, from the teardrop.

    The minimap repeats one image across several cached frames, so the reader
    keeps the last fit keyed by the pixels it scored and the seed; a repeat
    returns the same fit without recomputing it, and the answer is the one a
    fresh fit gives.

    **The prior** (a caller that passes `frame_idx` and `t_ms`). The self
    icon continues its fit on the previous image under `IconPoseReader`'s
    rule, unchanged: the same association, local search, surprises and
    audit cadence, over `fit_self` (`_SelfFits`), and the read carries the
    same `search`, `surprise`, `rests_on` and `audit`, except that a prior
    under `SELF_PRIOR_MIN_NCC` runs the full grid (`weak_prior`). The facing gate
    applies to the answer either search gives. Without a frame index the
    reader searches every image in full and adds none of these fields.
    """

    def __init__(self, scale: float = 1.0):
        self.scale = scale
        self._last: tuple | None = None
        self._fits: _SelfFits | None = None

    def read(self, crop: np.ndarray, cx: float, cy: float, *, frame_idx: int | None = None,
             t_ms: float | None = None, ref: str | None = None,
             digest: bytes | None = None) -> dict:
        """`{"x", "y", "deg", "origin", "ncc", ...}` for a self fit centred at `(cx, cy)`.

        Where the shape reads, `origin` is `teardrop` and `x`, `y`, `deg` are
        its centre and facing (image degrees, y down). Otherwise `origin` is
        `ring_fit`: `x`, `y` are the detector's own centre, `deg` is None and
        `reason` says why the teardrop was not read. With `frame_idx` the
        read continues the prior (`IconPoseReader.read`'s `t_ms`, `ref` and
        `digest`) and adds its search fields.
        """
        if frame_idx is not None:
            if self._fits is None:
                self._fits = _SelfFits(self.scale)
            got = self._fits.read(crop, cx, cy, frame_idx=frame_idx, t_ms=t_ms, ref=ref,
                                  digest=digest)
            tf = ({"read": True, **got} if got["origin"] == "teardrop" else
                  {"read": False, "ncc": got["ncc"], "reason": got["reason"]})
            search = {k: got[k] for k in ("search", "surprise", "rests_on", "audit") if k in got}
        else:
            rad = (L + WINDOW + SEARCH_PX) * self.scale + 1
            h, w = crop.shape[:2]
            win = crop[max(0, int(cy - rad)):min(h, int(cy + rad) + 2),
                       max(0, int(cx - rad)):min(w, int(cx + rad) + 2)]
            with step("memo"):
                key = (hashlib.blake2b(np.ascontiguousarray(win).tobytes(),
                                       digest_size=16).digest(),
                       win.shape, float(cx), float(cy))
            if self._last is not None and self._last[0] == key:
                tf = self._last[1]
            else:
                tf = fit_teardrop(crop, cx, cy, scale=self.scale)
                self._last = (key, tf)
            search = {}
        if tf.get("read"):
            out = {"x": float(tf["x"]), "y": float(tf["y"]), "deg": float(tf["deg"]),
                   "origin": "teardrop", "ncc": float(tf["ncc"])}
            gate, why = self_facing_gate(self.scale)
            if gate is not None and tf["ncc"] < gate:
                out.update(deg=None, facing_reason=why)
        else:
            out = {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                   "ncc": _num(tf.get("ncc")), "reason": tf.get("reason")}
        out.update(search)
        return out


def fit_self(crop: np.ndarray, cx0: float, cy0: float, *, scale: float = 1.0,
             yel: np.ndarray | None = None,
             prior: tuple[float, float, float] | None = None) -> dict:
    """`fit_teardrop` for the self icon, with the field a prior's surprise reads.

    Without `prior` it is `fit_teardrop` unchanged. With `prior` it adds
    `outside_ncc`, as `fit_icon` does: the best NCC more than `LOCAL_DEG`
    from the fit's facing, on the `MARGIN_DEG` sweep at the fitted centre,
    so a lobe the local grid could not reach is a surprise
    (`facing_elsewhere`) for the self icon as for a teammate.
    """
    f = fit_teardrop(crop, cx0, cy0, scale=scale, yel=yel, prior=prior)
    if prior is not None and "x" in f:
        key = yellowness(crop) if yel is None else yel
        with step("margin"):
            sc, rel = _facing_sweep(key, f["x"], f["y"], f["deg"], R_IN * scale,
                                    R_OUT * scale, L * scale, scale)
            f["outside_ncc"] = float(sc[rel > LOCAL_DEG].max())
    return f


#: On a widget size the player's facing labels do not cover, a self read
#: under this NCC gives the icon's centre but no facing (`facing_reason`
#: `low_ncc_unlabelled_scale`), and a consumer casts no cone from it. Against
#: the ring fit's facing after the light resolves its lobe, self reads at
#: 0.5-0.6 point more than 90 degrees away on about a third of frames on
#: 5822b6646448 (465 px), 223d636bf8d2 and c40d950031bb (331 px)
#: (`prototypes/team_vision_eval.py --pose-check`); E7 found those facings
#: cast much of c40d950031bb's false light.
SELF_FACING_MIN_NCC = 0.6
#: The widget scales whose self facing the player labelled, each with the NCC
#: gate its labels support (None: no gate); a read under it gives the centre
#: and no facing (`facing_reason` `low_ncc_labelled_gate`).
#: - 465 px (1.0): 5822b6646448 and the e78e75b2d191 controls (`reticle
#:   verify` lotus/self-facing). Of the two labelled reads under 0.6 one is
#:   right (an Ascent control) and one flipped, so no gate.
#: - 331 px: 37 blind labels on four sessions (`self_facing_331_20260929`,
#:   docs/STATISTICAL_ADJUDICATOR.md E13). Reads at NCC 0.50-0.55 flip on
#:   almost half; from 0.55 up they flip on one in 26 and err a median of
#:   about 4 degrees, and a 0.55 gate keeps 0.7 of the labelled reads where
#:   0.6 keeps 0.4.
SELF_FACING_GATES = ((1.0, None), (331 / 465, 0.55))
#: The widget scales at which the player's portrait is cut at the self
#: teardrop's centre (`self_portrait_pose`): E10's portrait fit at 465 px
#: (5822b6646448); at 331 px it fit better on two sessions and worse on two.
LABELLED_SCALES = (1.0,)


def labelled_scale(scale: float) -> bool:
    """True for a widget scale where the self portrait takes the teardrop's centre (`LABELLED_SCALES`)."""
    return any(abs(scale - s) < 0.02 for s in LABELLED_SCALES)


def self_facing_gate(scale: float) -> tuple[float | None, str]:
    """`(gate, facing_reason)`: the NCC under which a self read at `scale` gives
    no facing, and the reason it then carries. A labelled scale takes its
    labels' gate (`SELF_FACING_GATES`, None for none); any other scale takes
    `SELF_FACING_MIN_NCC`."""
    for s, gate in SELF_FACING_GATES:
        if abs(scale - s) < 0.02:
            return gate, "low_ncc_labelled_gate"
    return SELF_FACING_MIN_NCC, "low_ncc_unlabelled_scale"


def self_portrait_pose(pose: dict | None, scale: float, cx: float, cy: float) -> dict:
    """Where to cut the player's portrait: `pose` (`SelfConeReader.read` at the
    ring fit's `cx`, `cy`) on a labelled widget size, the ring fit's centre
    elsewhere (`reason` `unlabelled_scale`).

    At 465 px the portrait aligned at the self teardrop's centre fits its
    art far better than at the ring fit's (E6's rule B'; `prototypes/
    icon_teardrop.py --centre-check --centre-class self` on 5822b6646448);
    on four 331 px sessions it fit better on two and worse on two, so the
    ring fit's centre stays there. A teammate's portrait has no such limit.

    Elsewhere the answer reads nothing of the teardrop but its NCC, so a
    caller that needs only the portrait's centre may skip the fit there
    (`labelled_scale` False) and pass `pose` None: the answer is the same
    centre, no facing, `ncc` None and `reason` `unlabelled_scale`.
    """
    if pose is None:
        if labelled_scale(scale):
            raise ValueError("a labelled scale cuts the portrait at the teardrop: fit it")
        return {"origin": "ring_fit", "x": float(cx), "y": float(cy), "deg": None,
                "ncc": None, "reason": "unlabelled_scale"}
    if pose["origin"] != "teardrop" or labelled_scale(scale):
        return pose
    return {"origin": "ring_fit", "x": float(cx), "y": float(cy), "deg": None,
            "ncc": pose.get("ncc"), "reason": "unlabelled_scale"}


def _num(v):
    return None if v is None else float(v)


def posed(d: dict, pose: dict, *, ring_facing: bool = True) -> dict:
    """The ring fit's detection `d` with the teardrop's centre and facing where `pose` reads.

    `pose` is `SelfConeReader.read` or `IconPoseReader.read` at `d`'s centre.
    The ring fit FINDS the icon; the teardrop, where it reads, supplies `cx`
    and `cy`, and its facing where the reader gives one (`facing_source`
    `teardrop`). The ring fit's own values stay under `ring`, and `pose`
    keeps the `origin`, NCC, refusal `reason` and `facing_reason`, and the
    prior's `search`, `surprise`, `rests_on` and `audit` where the read
    carries them. Where the
    teardrop gives no facing the detection keeps, with `ring_facing`, the
    ring fit's facing (`facing_source` `ring_fit`), and otherwise carries
    none (`facing_source` None).
    """
    out = dict(d)
    out["ring"] = {"cx": d["cx"], "cy": d["cy"], "facing": d.get("facing")}
    out["pose"] = {"origin": pose["origin"], "ncc": pose.get("ncc"), "reason": pose.get("reason"),
                   "facing_reason": pose.get("facing_reason")}
    # How a prior-driven read searched (`IconPoseReader`), where it did.
    for k in ("search", "surprise", "rests_on", "audit"):
        if k in pose:
            out["pose"][k] = pose[k]
    if pose["origin"] == "teardrop":
        out["cx"], out["cy"] = pose["x"], pose["y"]
    if pose.get("deg") is not None:
        out["facing"], out["facing_source"] = pose["deg"] % 360.0, "teardrop"
    elif ring_facing and d.get("facing") is not None:
        out["facing_source"] = "ring_fit"
    else:
        out["facing"], out["facing_source"] = None, None
    return out


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


def _facing_sweep(key: np.ndarray, x: float, y: float, deg: float, r_in: float,
                  r_out: float, L_: float, scale: float):
    """The silhouette's NCC at centre `(x, y)` at every `MARGIN_DEG` facing,
    over the window the fit scores round it, and each facing's distance in
    degrees from `deg`: the sweep `fit_icon`'s margin and a prior's
    `outside_ncc` read."""
    px, py, obs = _window(key, x, y, L_ + WINDOW * scale)
    ths = np.radians(np.arange(0.0, 360.0, MARGIN_DEG, dtype=np.float32))
    sc = _correlation(obs, render(px[None, :] - x, py[None, :] - y, ths[:, None],
                                  r_in, r_out, L_, EDGE * scale))
    return sc, np.abs(_signed_deg(np.degrees(ths) - deg))


def fit_icon(crop: np.ndarray | None, cls: "str | IconClass", cx0: float, cy0: float, *,
             scale: float = 1.0, key: np.ndarray | None = None,
             r_in: float | None = None, r_out: float | None = None,
             L_: float | None = None,
             prior: tuple[float, float, float] | None = None) -> dict:
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
    fitting several icons. `prior` is `fit_teardrop`'s: a local search round
    an earlier fit, which adds `on_edge` and `outside_ncc` (the best NCC on
    the margin's sweep more than `LOCAL_DEG` from the fit's facing, which
    the local grid could not reach). The margin and the ring cover are
    measured at the fitted centre whichever grid found it, so they mean the
    same under either search.
    """
    c = cls if isinstance(cls, IconClass) else ICON_CLASSES[cls]
    cls = c.name
    r_in = c.r_in * scale if r_in is None else r_in
    r_out = c.r_out * scale if r_out is None else r_out
    L_ = c.L * scale if L_ is None else L_
    key = c.key(crop) if key is None else key
    f = fit_teardrop(None, cx0, cy0, scale=scale, r_in=r_in, r_out=r_out, L_=L_, yel=key,
                     prior=prior)
    f["cls"] = cls
    if "x" not in f:
        return {"cls": cls, "read": False, "reason": "no_key"}
    with step("margin"):
        sc, rel = _facing_sweep(key, f["x"], f["y"], f["deg"], r_in, r_out, L_, scale)
        f["margin"] = float(f["ncc"] - sc[rel >= 90.0].max())
        if prior is not None:
            # The best facing the local grid could not reach, scored on the
            # same sweep at the fitted centre: above the fit, the lobe lies
            # outside the window the prior allowed.
            f["outside_ncc"] = float(sc[rel > LOCAL_DEG].max())
    with step("ring_cover"):
        f["ring_cover"] = ring_cover(key, f["x"], f["y"], f["deg"], r_in, r_out,
                                     pad=0.5 * scale)
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


def crop_digest(crop: np.ndarray) -> bytes:
    """The digest `IconPoseReader` keys an image's fits by."""
    with step("memo"):
        return hashlib.blake2b(np.ascontiguousarray(crop).tobytes(), digest_size=16).digest()


class IconPoseReader:
    """A teammate's or an enemy's centre and facing per frame, from the teardrop.

    The class's key is computed once per image and the image's fits are
    memoised by its pixels, so the minimap's repeated images (several cached
    frames hold one image) and the same icon asked twice return the fit a
    fresh one gives without recomputing it.

    **The prior** (a caller that passes `frame_idx` and `t_ms`). An icon
    continues its fit on the previous distinct image: a detection whose ring
    centre lies within `PRIOR_PX` (scaled) of a fit's on that image, last
    shown at most `PRIOR_GAP_MS` earlier, is searched round that fit
    (`fit_icon(prior=)`), and its pose names the prior's detection under
    `rests_on` (`search` `prior`). The nearest read fit is the prior; where
    none lies within reach, the nearest refused one (a fit with a centre and
    facing: `low_ncc`, `no_ring` or `ambiguous_facing`). The full grid runs
    instead on surprise (`search` `full`, `surprise` saying which):
    `no_prior`, `gap`, `edge` (the local best on the local grid's boundary),
    `facing_elsewhere` (a facing outside the local window outscores the fit
    on the margin's sweep), `ncc_drop` (NCC more than `NCC_DROP` under the
    prior's), or a change of state: a read prior whose local fit a gate
    refuses (`low_ncc`, `no_ring`, `ambiguous_facing`), a refused prior
    whose local fit reads (`refusal_ended`) or is refused for another reason
    (that reason). A margin always means the same thing: the best NCC less
    the best 90 degrees or more away, at the fitted centre.

    **A refusal continues as a read does** (icon-pose-prior-0.3.0). A
    refused prior whose local fit is refused again for the same reason, with
    no other surprise, publishes that local refusal: `origin` `ring_fit`, the
    local fit's `ncc` and `reason`, `search` `prior` and the refused prior
    under `rests_on`. A refusal from the full search says `search` `full`,
    so the two stay apart. Such a chain is bounded: after `REFUSAL_CHAIN`
    consecutive prior-searched refusals the next image runs the full grid
    (`surprise` `refusal_chain`), so a teardrop the local window misses
    cannot stay refused for long, and the full search re-anchors the chain.
    The self icon's `SELF_PRIOR_MIN_NCC` gate applies to a refused prior as
    to a read one, so a self refusal under it runs the full grid.

    **The audit.** The first new image in each block of `AUDIT_FRAMES`
    frames, fixed by frame index before any fit, runs the full search beside
    the local one for every detection with a prior, read or refused, and
    stores both under `audit` (`prior`, `full`), apart from the published
    answer, which stays the one the prior rule gives. A surprise's full
    search is no audit sample; on an audit image it is reused as the audit's
    `full`. Without a frame index the reader searches every image in full
    and adds none of these fields.
    """

    #: A prior whose NCC lies under this runs the full grid (`surprise`
    #: `weak_prior`); None: every prior is continued. The ally rule has none.
    prior_min_ncc: float | None = None

    def __init__(self, cls: str = "ally", scale: float = 1.0):
        self.cls, self.scale = cls, scale
        self._digest: bytes | None = None
        self._key: np.ndarray | None = None
        self._fits: dict = {}
        self._t: float | None = None
        self._prev: tuple[float | None, list[dict]] | None = None
        self._bucket: int | None = None
        self._audit_due = False

    def read(self, crop: np.ndarray, cx: float, cy: float, *, frame_idx: int | None = None,
             t_ms: float | None = None, ref: str | None = None,
             digest: bytes | None = None) -> dict:
        """`{"x", "y", "deg", "origin", "ncc", ...}` for a detection centred at `(cx, cy)`.

        Where the shape reads, `origin` is `teardrop` and `x`, `y`, `deg` are
        its centre and facing (image degrees, y down). Otherwise `origin` is
        `ring_fit`: `x`, `y` are the detector's own centre, `deg` is None and
        `reason` says why the teardrop was not read. With `frame_idx` the
        read continues the prior and adds `search`, `surprise`, `rests_on`
        (the prior's `ref`, the caller's name for that detection) and, on an
        audit image, `audit`. `digest` is `crop_digest(crop)`, for a caller
        reading several icons of one crop to hash it once.
        """
        if digest is None:
            digest = crop_digest(crop)
        if digest != self._digest:
            if self._fits:
                # The prior's age runs from the last frame that showed its image.
                # A fit with a centre and facing may be a prior, read or refused.
                self._prev = (self._t, [e for e in self._fits.values() if "x" in e["fit"]])
            self._digest, self._key, self._fits = digest, None, {}
            if frame_idx is not None:
                bucket = int(frame_idx) // AUDIT_FRAMES
                self._audit_due, self._bucket = bucket != self._bucket, bucket
        self._t = t_ms
        k = (float(cx), float(cy))
        entry = self._fits.get(k)
        if entry is None:
            if self._key is None:
                with step("key"):
                    self._key = self._key_of(crop)
            entry = self._fits[k] = self._fit(cx, cy, frame_idx, t_ms, ref)
        tf = entry["fit"]
        if tf.get("read"):
            out = {"x": float(tf["x"]), "y": float(tf["y"]), "deg": float(tf["deg"]),
                   "origin": "teardrop", "ncc": float(tf["ncc"])}
            if "margin" in tf:
                out["margin"] = float(tf["margin"])
        else:
            out = {"x": float(cx), "y": float(cy), "deg": None, "origin": "ring_fit",
                   "ncc": _num(tf.get("ncc")), "reason": tf.get("reason")}
        out.update(entry["search"])
        return out

    def _key_of(self, crop: np.ndarray) -> np.ndarray:
        """The class's key over the image, computed once per image."""
        return ICON_CLASSES[self.cls].key(crop)

    def _fit_one(self, cx: float, cy: float, prior=None) -> dict:
        """One fit at the detection's centre: the full grid, or with `prior`
        `(x, y, deg)` the local search round it."""
        return fit_icon(None, self.cls, cx, cy, scale=self.scale, key=self._key, prior=prior)

    def _fit(self, cx: float, cy: float, frame_idx, t_ms, ref) -> dict:
        """One detection's memo entry: the fit, how it was searched, and what
        the next image's prior needs (`ring`, `ref`)."""
        full = lambda: self._fit_one(cx, cy)
        entry = {"ring": (float(cx), float(cy)), "ref": ref, "search": {}, "chain": 0}
        if frame_idx is None:
            entry["fit"] = full()
            return entry
        prior, surprise = self._prior(cx, cy, t_ms)
        local = None
        if prior is not None:
            p = prior["fit"]
            if self.prior_min_ncc is not None and (p.get("ncc") or 0.0) < self.prior_min_ncc:
                surprise = "weak_prior"
            elif not p.get("read") and prior["chain"] >= REFUSAL_CHAIN:
                surprise = "refusal_chain"
            else:
                local = self._fit_one(cx, cy, prior=(p["x"], p["y"], p["deg"]))
                surprise = _surprise(local, p)
        if surprise is None:
            entry["fit"] = local
            entry["search"] = {"search": "prior", "surprise": None, "rests_on": prior["ref"]}
            if not local.get("read"):
                # One more refusal searched round a refusal.
                entry["chain"] = prior["chain"] + 1
        else:
            entry["fit"] = full()
            entry["search"] = {"search": "full", "surprise": surprise, "rests_on": None}
        if prior is not None and self._audit_due:
            # Chosen by frame index and the prior's presence, before either
            # fit; a surprise's full search is the same computation.
            if surprise is None:
                with step("audit"):
                    audit_full = full()
            else:
                audit_full = entry["fit"]
            entry["search"]["audit"] = {"prior": _audit_view(local),
                                        "full": _audit_view(audit_full)}
        return entry

    def _prior(self, cx: float, cy: float, t_ms) -> tuple[dict | None, str | None]:
        """The previous image's read fit whose ring centre lies nearest
        `(cx, cy)` within `PRIOR_PX`, else its nearest refused fit there, or
        None and the surprise (`no_prior`, `gap`). Two detections may
        continue one prior: nearness alone binds them, so the answer does not
        depend on the order they are asked in."""
        if self._prev is None:
            return None, "no_prior"
        t_prev, fits = self._prev
        if t_prev is None or t_ms is None or t_ms - t_prev > PRIOR_GAP_MS:
            return None, "gap"
        for read in (True, False):
            best, d_best = None, PRIOR_PX * self.scale
            for e in fits:
                if bool(e["fit"].get("read")) != read:
                    continue
                d = math.hypot(e["ring"][0] - cx, e["ring"][1] - cy)
                if d <= d_best:
                    best, d_best = e, d
            if best is not None:
                return best, None
        return None, "no_prior"


class _SelfFits(IconPoseReader):
    """`IconPoseReader`'s memo, prior and audit over the self teardrop
    (`fit_self`), for `SelfConeReader` given a frame index.

    Only the windows the fits score are keyed, as `fit_teardrop` keys only
    its own: the yellowness of a pixel reads that pixel alone, so a window
    keyed into a blank image gives every fit the values a whole-image key
    gives.

    A self prior under `SELF_PRIOR_MIN_NCC` is not continued (`weak_prior`).
    """

    prior_min_ncc = SELF_PRIOR_MIN_NCC

    def __init__(self, scale: float = 1.0):
        super().__init__("self", scale)
        self._crop: np.ndarray | None = None

    def read(self, crop, cx, cy, **kw) -> dict:
        self._crop = crop
        return super().read(crop, cx, cy, **kw)

    def _key_of(self, crop: np.ndarray) -> np.ndarray:
        return np.zeros(crop.shape[:2], np.float32)

    def _fit_one(self, cx: float, cy: float, prior=None) -> dict:
        # Every pixel a fit reads: the window round the detection's centre
        # both grids score, and with a prior the facing sweep's window round
        # the fit, which lies within the local reach of the prior's centre.
        self._key_window(cx, cy, (L + WINDOW + SEARCH_PX) * self.scale)
        if prior is not None:
            self._key_window(prior[0], prior[1], (L + WINDOW + LOCAL_PX + 1) * self.scale)
        return fit_self(None, cx, cy, scale=self.scale, yel=self._key, prior=prior)

    def _key_window(self, x: float, y: float, reach: float) -> None:
        r = int(math.ceil(reach)) + 3
        h, w = self._key.shape
        ys = slice(max(0, int(y) - r), min(h, int(y) + r + 1))
        xs = slice(max(0, int(x) - r), min(w, int(x) + r + 1))
        self._key[ys, xs] = yellowness(self._crop[ys, xs])


def _surprise(local: dict, prior: dict) -> str | None:
    """Why a local fit round `prior` cannot stand, or None. A read prior
    must read again; a refused one must be refused again for its reason."""
    if "x" not in local:
        return local.get("reason", "no_key")
    if local.get("on_edge"):
        return "edge"
    if prior.get("read", True):
        if not local.get("read"):
            return local["reason"]
    elif local.get("read"):
        return "refusal_ended"
    elif local["reason"] != prior["reason"]:
        return local["reason"]
    if local.get("outside_ncc", -2.0) > local["ncc"]:
        return "facing_elsewhere"
    if local["ncc"] < prior["ncc"] - NCC_DROP:
        return "ncc_drop"
    return None


def _audit_view(f: dict | None) -> dict | None:
    """The fields an audit compares, from one `fit_icon`."""
    if f is None:
        return None
    return {k: (f.get(k) if k in ("read", "reason") else _num(f.get(k)))
            for k in ("x", "y", "deg", "ncc", "margin", "read", "reason")}
