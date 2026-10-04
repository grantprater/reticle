r"""Propose Deadlock's Sonic Sensor squares on the minimap by a soft parametric fit.

    .\.venv\Scripts\python.exe prototypes\sonic_square.py frame SID T_S [--png]
    .\.venv\Scripts\python.exe prototypes\sonic_square.py score [--record]
    .\.venv\Scripts\python.exe prototypes\sonic_square.py heldout [--record]

The sensor draws a square about 26 px a side at scale 1, a flat white tint of
alpha about 0.17 with no brighter rim, its icon on the midpoint of one side; a
dim sensor draws none [domain:abilities/deadlock-sonic-sensor-minimap-white-area].
The translucent part is a square, not a disc: the player corrected a relay on
2026-10-04. `drawn_areas.py` measured the squares with a hard box filter round
a known icon; this script proposes squares with no icon given, fits each one
softly, and only then links it to the icon on its side. A sensor sits normal
to its wall at any angle, so its square turns with the wall
[domain:abilities/deadlock-sonic-sensor-square-follows-wall]; since 0.2.0 the
fit turns the square to the wall the baked static draws under the icon.

**Background.** The baked static of the session's `(map, profile)` key
(`geometry.reference_static`) and the key's two-state lighting reference
(`lighting.Lighting`: unlit `B`, lit `H` where known). Crops come from the
crop cache in the baked widget frame (`widget_frame.normalise`, linear, for a
variant placement). No session median [domain:capture/session-pixels-are-not-the-map].
The widget scale is `minimap.widget_scale` of the baked static's width; every
px constant below is at scale 1 and multiplied by it.

**Model.** Over the opaque slab only [domain:minimap/transparency] (the void
shows the scene behind, so the baked void is no background): per pixel,
`g = bg + (255 - bg) * (c + a * S)`, with `bg` the unlit `B` or the lit `H`
as a two-component mixture (weight `P_LIT`), each component a Cauchy of scale
`NOISE` grey levels. `g` is BT.601 luma, `a` the tint alpha, `c` a local tint
offset, `S` the square's coverage: per axis a box integrated over each pixel
and blurred by a Gaussian of sigma `sig` (`erf` edges, sub-pixel), in
coordinates turned by the angle `theta`. Seven parameters (centre, width,
height, sigma, alpha, offset) at a fixed angle minimise the mixture's
negative log-likelihood (L-BFGS-B); the linked icon's disc is masked out of the
refit. Modelling the lit state, not a threshold, keeps vision cones (lit alpha
about 0.46 over unlit floor) from ranking above the squares.

**Proposer.** The per-pixel log-likelihood ratio of an `ALPHA0` tint against
none, under the same mixture, averaged inside a `SIDE0` square minus its band
outside; the `TOP_K` best local maxima per frame seed the fits. No threshold.

**Angle (0.2.0).** Continue the prior: the first fit is axis-aligned, as in
0.1.0, and links the icon. The icon's sub-pixel centre (the icon-contrast
peak near the link, parabola-refined) then names the wall it sits on: lines
through the icon disc in the baked static's gradient (`wall_at`, sampled with
`cv2.remap` INTER_LINEAR), every degree, scored by the gradient energy along
each line's normal, read mod 90 deg. The axis is always a candidate (0.1.0's
prior); up to two walls off the axis join it where the static draws them
clearly (`WALL_MIN_CONTRAST`; a chamfer offers its own direction and its
neighbours'). The refit with the icon masked runs at each candidate's angle,
fixed, and the larger likelihood gain over no square picks. Only where that
refit fails the cut while its icon and significance memberships pass AND the
icon's glyph names the sensor does a free-angle refit run (+-`FREE_SPAN` deg
round the prior); each run is stored as a `surprise` with its reason,
adopted only if it passes. The model is analytic; no image is warped.

**Link.** For each side of the fitted square, the icon contrast (a soft dark
share over a disc of radius 0.8 `ICON_R` minus the same over the annulus
1.15-1.6 `ICON_R`, so void and dark walls read near zero) at the best centre
within `LINK_NORMAL` px of the side's midpoint along its normal and
`LINK_LATERAL` px along it, both in the square's turned frame; the best side's
centre is the linked icon.

**Decision.** One soft score, cut once at `CUT`: the product of memberships for
the alpha's closeness to `ALPHA0`, the sides' closeness to `SIDE0`, the fit's
log-likelihood gain over no square, the edge sharpness, the icon contrast, and
the linked icon's game-art glyph: its correlation with Deadlock's Q glyph by
`minimap_glyph_eval.classify` over Deadlock's kit (the square names the
ability, so the kit is the candidate set). The glyph runs only where the rest
of the product reaches `CUT`, which changes no decision.

**Dev.** Constants come from the domain facts and dev data only: the named
instances (5822b6646448 at 1901.083 s, the player; a06f04a0059f at 513.5 s,
seen), the positioned `deadlock:sonic sensor` labels in `labels/ability` of
those two sessions, split live/dim by the patch-contrast rule of
`device_deactivation.py` (contrast <= 203 is dim), other abilities' labels on
the same frames, and 30 frames each of four sessions with no Deadlock in the
stored lineup (4f207c0c4e39 is refused: its widget placement clips the crop).
Frozen at `sonic-square-0.1.0`: named
[metric:sonic_square/dev_named@a06f04a0059f+5822b6646448#found=4] of 4, live
[metric:sonic_square/dev_live@a06f04a0059f+5822b6646448#found=42] of
[metric:sonic_square/dev_live@a06f04a0059f+5822b6646448#n=44], dim
[metric:sonic_square/dev_dim@a06f04a0059f+5822b6646448#found=0] of
[metric:sonic_square/dev_dim@a06f04a0059f+5822b6646448#n=24], other
abilities [metric:sonic_square/dev_other@a06f04a0059f+5822b6646448#found=0];
[metric:sonic_square/dev_negatives@3694746e4e54+4f207c0c4e39+75a55a296d3b+b3b9defb6fd7#squares=0]
squares on the 90 negative frames (5 without the glyph membership, all on the
331 px widgets, glyph naming Deadlock:C). Found squares fit alpha median
[metric:sonic_square/dev_live@a06f04a0059f+5822b6646448#alpha_median=0.167]
and side median
[metric:sonic_square/dev_live@a06f04a0059f+5822b6646448#side_median=26.31] px.

**Held-out.** `heldout` scored the frozen method once on
`labels/minimap_glyph_heldout` (232 sure frames over 33 sessions; every sure
`Deadlock:Q` mark is on 29eff6920e8f): live marks
[metric:sonic_square/heldout_live@minimap_glyph_heldout#found=5] of
[metric:sonic_square/heldout_live@minimap_glyph_heldout#n=12], and
[metric:sonic_square/heldout_unexplained@minimap_glyph_heldout#squares_near_no_q_mark=0]
squares away from a mark. Five misses are one sensor whose square is turned
with its wall; two lie under Deadlock's own icon and cone. That session found
the rotation, so it is not blind for a rotated-square method.

**0.2.0 dev.** 29eff6920e8f's turned sensor joins dev (`ROTATED`: the cached
frame nearest each whole second 35-48 s, icon position from the domain fact;
the held-out labels are not reread). Found
[metric:sonic_square/dev_rotated@29eff6920e8f#found=14] of
[metric:sonic_square/dev_rotated@29eff6920e8f#n=14], at a prior angle of median
[metric:sonic_square/dev_rotated@29eff6920e8f#theta_median=-32.66] deg; a
free-angle refit, for diagnosis only, lands a median
[metric:sonic_square/dev_rotated@29eff6920e8f#abs_free_minus_prior_median=1.82]
deg from the prior. The 0.1.0 floors hold value for value (named, live, dim,
other and negatives above, recorded again at 0.2.0), every found dev square
on the axis sensors fits at 0 deg, and the free angle ran
[metric:sonic_square/dev_surprises@a06f04a0059f+5822b6646448+29eff6920e8f+negatives#surprises=5]
times, adopted
[metric:sonic_square/dev_surprises@a06f04a0059f+5822b6646448+29eff6920e8f+negatives#adopted=0].
Two of the 14 turned frames passed weakly: at 42.0 s and 43.0 s the icon
centre landed off the sensor's wall, the prior picked another wall (44.98 and
-42.02 deg against about -33 deg on the other twelve; the free-angle refit
read 55.97 and -33.98, 11.0 and 8.0 deg from the prior, about 9-12 deg from
the session's wall), and the icon share read 0.23 and 0.29 against 0.48-0.53
elsewhere (icon membership 0.42 and 0.66); both were accepted (scores 0.37
and 0.62). Recall 14/14 overstates the angle prior's hold on this sensor
(`<store>/analysis/sonic-square-20261004/sonic-square-0.2.0/eval.json`,
`rows` and `rotated_diagnosis`).
The fresh held-out set is `label_minimap_glyph_heldout.py --pass sonic`
(queue `sonic-square-heldout-queue-0.2.0`, 26 frames at fixed offsets from
each round's cache start, 1 s before `gametime`'s barrier drop, over three
match sessions, unlabelled on
2026-10-04); 0.2.0 has no held-out score.

**Outputs.** The top-level `eval.json` and `eval_*.png` of
`<store>/analysis/sonic-square-20261004/` are rev1's run (named 3/4, live
38/44, 126 surprises), though stamped sonic-square-0.2.0: two 0.2.0 runs
wrote there and overwrote 0.1.0's top-level files. `sonic-square-0.2.0/`
holds rev3, the frozen 0.2.0, which overwrote rev2 there. The store's
`notes/predictions.jsonl` carries the correction; write each run to a new
directory.

Wire: no. A square is a shape the `ability-shape` owner does not fit yet; the
owner of minimap ability icons is unassigned (`reticle ownership`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy.optimize import minimize  # noqa: E402
from scipy.special import erf  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, minimap, team_vision, widget_frame  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

cv2.setNumThreads(1)
VERSION = "sonic-square-0.2.0"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "sonic-square-20261004" / VERSION
SERIES = "sonic_square"

# --- the shape, px at widget scale 1 [domain:abilities/deadlock-sonic-sensor-minimap-white-area]
SIDE0 = 26.0
SIDE_RANGE = (18.0, 36.0)
ALPHA0 = 0.17
#: The icon disc is 24 px across [domain:minimap/icon-extent-by-family].
ICON_R = 12.0

# --- proposer
BAND = 4.0
TOP_K = 12
WIN_PAD = 8.0
#: Unused since the mixture proposer replaced the winsorised tint; kept because 0.1.0's recorded deps carry it.
A_CLIP = (-0.1, 0.4)

# --- fit
#: Cauchy f_scale in grey levels: the capture's noise on flat floor.
NOISE = 6.0
#: The prior share of floor drawn lit, the mixture weight of the lighting reference's lit state.
P_LIT = 0.2
SIG0, SIG_RANGE = 0.7, (0.25, 3.0)

# --- link
DARK = 60.0
DARK_SOFT = 6.0
VOID_DARKER = 12.0
LINK_NORMAL = 4
LINK_LATERAL = 3

# --- decision: soft memberships, multiplied, cut once
ALPHA_SD = 0.04
SIDE_SD = 4.5
#: The fit's NLL drop over the no-square model, per px^2 of widget scale, as a logistic membership.
DNLL_MID, DNLL_SOFT = 150.0, 40.0
SIG_MID, SIG_SOFT = 1.8, 0.25
SHARE_MID, SHARE_SOFT = 0.25, 0.06
#: The annulus the icon disc is compared with, in icon radii.
ICON_R_IN, ICON_R_OUT = 1.15, 1.6
#: The linked icon's game-art correlation with the Sonic Sensor glyph, as a logistic membership.
GLYPH_MID, GLYPH_SOFT = 0.6, 0.05
CUT = 0.25

# --- rotation [domain:abilities/deadlock-sonic-sensor-square-follows-wall]
#: The wall under the icon: a line through the icon disc, its centre within WALL_OFFSET px (x scale)
#: of the icon's, WALL_HALF icon radii long either way, searched every WALL_STEP deg.
WALL_OFFSET, WALL_HALF, WALL_STEP = 2.0, 1.0, 1.0
#: A second wall direction is a candidate when its line holds this share of the best line's energy
#: and lies this many deg (mod 90) from it; at most this many candidates.
WALL_SECOND, WALL_APART, WALL_CANDIDATES = 0.5, 10.0, 2
#: A wall joins the axis as a candidate only when its line's energy is this many times the median
#: direction's: the drawn walls through dev icons read 7-30, open floor 1.8-2.3.
WALL_MIN_CONTRAST = 4.0
#: The free-angle refit, run only when the prior-angle fit fails the cut while its icon and
#: significance memberships pass, searches this many degrees either side of the prior, started
#: from each of these offsets.
FREE_SPAN = 45.0
FREE_STARTS = (0.0, -30.0, 30.0)
FREE_GATE = 0.5

#: Hard limits that refuse a fit outright, by name, before scoring.
MIN_SLAB_SHARE = 0.35

#: Sessions whose stored lineup holds no Deadlock on either side (drawn_areas.NEGATIVE_SESSIONS).
NEGATIVE_SESSIONS = ("3694746e4e54", "4f207c0c4e39", "75a55a296d3b", "b3b9defb6fd7")
NEG_FRAMES = 30
#: The player's named sensors (2026-09-30) and two seen beside them, icon hints on the widget crop.
NAMED = [("5822b6646448", 1901.083, 86, 293, "player"), ("5822b6646448", 1901.083, 214, 259, "player"),
         ("a06f04a0059f", 513.5, 94, 182, "seen"), ("a06f04a0059f", 513.5, 137, 169, "seen")]
DEV_LABEL_SESSIONS = ("a06f04a0059f", "5822b6646448")
#: The turned sensor of [domain:abilities/deadlock-sonic-sensor-square-follows-wall], dev since
#: 0.2.0: its icon on the widget crop and the cached frame nearest each whole second of a cadence
#: fixed before the run. Its position comes from the domain fact, never from the held-out labels.
ROTATED = ("29eff6920e8f", 343, 164, tuple(range(35, 49)))
#: The patch-contrast rule of device_deactivation.py: a 9x9 patch's max - min at the label.
DIM_CONTRAST_MAX, PATCH_R = 203.0, 4
#: A linked icon within this many px (x scale) of a label is that label's: a label is a click
#: anywhere on the icon's disc.
MATCH_PX = ICON_R
#: Cached frames further than this from a label's time are not that label's frame.
T_TOL_MS = 70.0


def below_normal() -> None:
    k = ctypes.windll.kernel32
    k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)


def sigmoid(x):
    return 1.0 / (1.0 + np.exp(-np.asarray(x, np.float64)))


def luma(img: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float32)


class Sess:
    """One session's baked static, slab, widget scale and crop cache."""

    def __init__(self, sid: str):
        self.sid = sid
        man = geometry.manifest(sid, STORE)
        if man is None:
            raise SystemExit(f"{sid}: no manifest")
        self.capture = man["source"]["path"]
        prof = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        inp, why = team_vision.load_inputs(STORE, sid, prof, w, h)
        if inp is None:
            raise SystemExit(f"{sid}: no inputs ({why})")
        self.box, self.key = inp.box, inp.geometry_key
        self.B = luma(inp.static)
        self.slab = inp.slab.astype(bool)
        # the floor's lit state from the baked two-state lighting reference; B where it is unknown
        ref = inp.light
        if ref is not None and ref.hi.shape == self.B.shape:
            kn = ref.known.astype(bool) if ref.known is not None else ref.usable.astype(bool)
            self.H = np.where(kn & inp.floor.astype(bool), ref.hi, self.B).astype(np.float32)
            self.lighting = ref.version
        else:
            self.H, self.lighting = self.B.copy(), None
        self.ws = minimap.widget_scale(inp.static.shape[1])
        self.cache, why = RoiCache.load(STORE, man, prof, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.wf = widget_frame.for_session(man, self.box, STORE)
        if self.wf is not None and self.wf.refusal:
            raise SystemExit(f"{sid}: {widget_frame.refusal_text(self.wf.refusal)}")
        self.cache_t = np.unique(np.asarray(self.cache.t_ms, dtype=float))
        self.wall = wall_field(self.B, self.ws)

    def snap(self, t_ms: float) -> float:
        return float(self.cache_t[int(np.argmin(np.abs(self.cache_t - t_ms)))])

    def crops(self, times_ms):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples([float(t) for t in times_ms], rois=["minimap"]):
            fr = smp.frame if self.wf is None else self.wf.normalise(smp.frame, smp.t_ms)
            yield float(smp.t_ms), fr[y0:y1, x0:x1]


_SESS: dict = {}


def sess(sid: str) -> Sess:
    if sid not in _SESS:
        _SESS[sid] = Sess(sid)
    return _SESS[sid]


# ------------------------------------------------------------------ the floor's two states

def mix_ll(g, B, H, a, c, S=1.0):
    """Per-pixel log-likelihood of `g` under the tint model over a floor that is unlit (B) or
    lit (H), each a Cauchy of scale NOISE grey levels: a mixture, never a choice of state."""
    out = 0.0
    for bg, pi in ((B, 1.0 - P_LIT), (H, P_LIT)):
        z = (g - (bg + (255.0 - bg) * (c + a * S))) / NOISE
        out = out + pi / (1.0 + z * z)
    return np.log(out)


# ------------------------------------------------------------------ proposer

def propose(g: np.ndarray, B: np.ndarray, H: np.ndarray, slab: np.ndarray, ws: float) -> list[tuple[float, float, float]]:
    """Up to TOP_K (cx, cy, evidence) seeds: local maxima of the per-pixel log-likelihood ratio of
    an ALPHA0 tint against none, its mean inside a SIDE0 square minus its mean in the band round it."""
    e = np.where(slab, mix_ll(g, B, H, ALPHA0, 0.0) - mix_ll(g, B, H, 0.0, 0.0), 0.0).astype(np.float32)
    w = slab.astype(np.float32)
    s = int(round(SIDE0 * ws)) | 1
    o = s + 2 * (int(round(BAND * ws)) or 1)
    box = lambda im, k: cv2.boxFilter(im, -1, (k, k), normalize=False,  # noqa: E731
                                      borderType=cv2.BORDER_CONSTANT)
    Si, Wi = box(e, s), box(w, s)
    So, Wo = box(e, o), box(w, o)
    ok = (Wi > MIN_SLAB_SHARE * s * s) & (Wo - Wi > MIN_SLAB_SHARE * (o * o - s * s))
    D = np.where(ok, Si / np.maximum(Wi, 1e-6) - (So - Si) / np.maximum(Wo - Wi, 1e-6), -1e3).astype(np.float32)
    k = s // 2 | 1
    peak = (D >= cv2.dilate(D, np.ones((k, k), np.uint8))) & ok
    ys, xs = np.nonzero(peak)
    order = np.argsort(-D[ys, xs])[:TOP_K]
    return [(float(xs[i]), float(ys[i]), float(D[ys[i], xs[i]])) for i in order]


# ------------------------------------------------------------------ fit

def wall_field(B: np.ndarray, ws: float) -> tuple[np.ndarray, np.ndarray]:
    """The baked static's Sobel gradient (x, y): a fixed map of the `(map, profile)` key, no capture
    pixels. `wall_at` reads the wall under an icon from it."""
    return (cv2.Sobel(B, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(B, cv2.CV_32F, 0, 1, ksize=3))


def wall_at(wall: tuple, x: float, y: float, ws: float = 1.0) -> list[tuple[float, float]]:
    """The walls the icon at (x, y) may sit on: straight lines through the icon disc (within
    WALL_OFFSET px of its centre, WALL_HALF icon radii either way along it) whose normal carries
    gradient energy of the baked static, over every direction at WALL_STEP deg. Each local maximum
    of that energy over direction, refined by a parabola through it and its neighbours, holding at
    least WALL_SECOND of the best one's energy and WALL_APART deg (mod 90) from a stronger one, is
    a candidate; at most WALL_CANDIDATES, strongest first. Each is the square's prior angle (deg,
    the wall's direction mod 90, in [-45, 45)) and the line's contrast: its mean energy over the
    median direction's, so a lone wall reads high and open floor near 1. A chamfer between two
    parallel walls (29eff6920e8f's sensor) offers both its own direction and theirs.

    The icon sits on its wall [domain:abilities/deadlock-sonic-sensor-square-follows-wall], so the
    wall is sought through the icon, not averaged round it: a Gaussian-weighted orientation tensor
    there let the axis walls of a corner pull a slanted wall's angle by 14 deg on 29eff6920e8f.
    Samples are read by linear interpolation (cv2.remap, INTER_LINEAR)."""
    gx, gy = wall
    a = np.radians(np.arange(0.0, 180.0, WALL_STEP))
    dx, dy = np.cos(a), np.sin(a)
    o = np.arange(-WALL_OFFSET * ws, WALL_OFFSET * ws + 1e-6, 0.5)
    t = np.arange(-WALL_HALF * ICON_R * ws, WALL_HALF * ICON_R * ws + 1e-6, 0.5)
    # points (angle, offset, along): along the wall (dx, dy), offset along its normal (-dy, dx)
    px = x + t[None, None, :] * dx[:, None, None] - o[None, :, None] * dy[:, None, None]
    py = y + t[None, None, :] * dy[:, None, None] + o[None, :, None] * dx[:, None, None]
    shp = px.shape
    mx, my = px.reshape(-1, shp[2]).astype(np.float32), py.reshape(-1, shp[2]).astype(np.float32)
    sx = cv2.remap(gx, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(shp)
    sy = cv2.remap(gy, mx, my, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).reshape(shp)
    en = ((-sx * dy[:, None, None] + sy * dx[:, None, None]) ** 2).mean(axis=2).max(axis=1)
    prev, nxt = np.roll(en, 1), np.roll(en, -1)
    peaks = np.nonzero((en >= prev) & (en >= nxt) & (en >= WALL_SECOND * en.max()))[0]
    med = max(float(np.median(en)), 1e-6)
    out: list[tuple[float, float]] = []
    for k in peaks[np.argsort(-en[peaks])]:
        den = prev[k] - 2 * en[k] + nxt[k]
        frac = float(np.clip(0.5 * (prev[k] - nxt[k]) / den, -0.5, 0.5)) if den < 0 else 0.0
        th = wrap45((k + frac) * WALL_STEP)
        if all(abs(wrap45(th - o_)) >= WALL_APART for o_, _ in out):
            out.append((th, float(en[k]) / med))
        if len(out) == WALL_CANDIDATES:
            break
    return out


def icon_centre(share: np.ndarray, x: int, y: int, ws: float) -> tuple[float, float]:
    """The icon's sub-pixel centre: the icon-contrast peak within half an icon radius of a linked
    point, refined by a parabola through it and its neighbours on each axis."""
    r = max(1, int(round(0.5 * ICON_R * ws)))
    h, w = share.shape
    x0, y0, x1, y1 = max(1, x - r), max(1, y - r), min(w - 1, x + r + 1), min(h - 1, y + r + 1)
    win = share[y0:y1, x0:x1]
    j, i = np.unravel_index(int(np.argmax(win)), win.shape)
    px, py = x0 + i, y0 + j

    def para(m, c, p):
        den = m - 2 * c + p
        return float(np.clip(0.5 * (m - p) / den, -0.5, 0.5)) if den < 0 else 0.0
    return (px + para(share[py, px - 1], share[py, px], share[py, px + 1]),
            py + para(share[py - 1, px], share[py, px], share[py + 1, px]))


def wrap45(d: float) -> float:
    """An angle difference mod 90 deg, in [-45, 45)."""
    return float((d + 45.0) % 90.0 - 45.0)


def box_coverage(x: np.ndarray, lo: float, hi: float, sig: float) -> np.ndarray:
    """A box [lo, hi] integrated over unit pixels centred at x, blurred by a Gaussian of sigma sig."""
    s = math.sqrt(sig * sig + 1.0 / 12.0) * math.sqrt(2.0)
    return 0.5 * (erf((x - lo) / s) - erf((x - hi) / s))


def icon_contrast_map(g: np.ndarray, B: np.ndarray, ws: float) -> np.ndarray:
    """At each pixel, the soft dark share of an icon disc (radius 0.8 ICON_R) centred there minus
    that of the annulus round it (1.15-1.6 ICON_R): an icon is a dark disc on lighter ground, so
    void, a dark wall or a dark smoke, dark inside and out, scores near zero."""
    d = (sigmoid((DARK - g) / DARK_SOFT) * sigmoid((B - g - VOID_DARKER) / DARK_SOFT)).astype(np.float32)
    n = int(math.ceil(ICON_R_OUT * ICON_R * ws))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1]
    rr = np.hypot(xx, yy) / (ICON_R * ws)
    disc = (rr <= 0.8).astype(np.float32)
    ring = ((rr >= ICON_R_IN) & (rr <= ICON_R_OUT)).astype(np.float32)
    f = lambda k: cv2.filter2D(d, -1, k / k.sum(), borderType=cv2.BORDER_REPLICATE)  # noqa: E731
    return f(disc) - f(ring)


def link_icon(share: np.ndarray, f: dict, ws: float) -> dict:
    """The side whose midpoint best holds a dark icon disc: its centre, share and direction
    (`dir` points from the icon into the square, in the square's own frame turned by `theta`)."""
    cx, cy, hw, hh = f["cx"], f["cy"], f["w"] / 2, f["h"] / 2
    t = math.radians(f.get("theta", 0.0))
    ux, uy, vx, vy = math.cos(t), math.sin(t), -math.sin(t), math.cos(t)
    # (midpoint, inward normal, lateral); at theta 0 the lateral order is 0.1.0's
    sides = {"down": (cx - hh * vx, cy - hh * vy, vx, vy, ux, uy),
             "up": (cx + hh * vx, cy + hh * vy, -vx, -vy, -ux, -uy),
             "right": (cx - hw * ux, cy - hw * uy, ux, uy, vx, vy),
             "left": (cx + hw * ux, cy + hw * uy, -ux, -uy, -vx, -vy)}
    h, w = share.shape
    nr, lr = int(round(LINK_NORMAL * ws)), int(round(LINK_LATERAL * ws))
    a_, b_ = np.meshgrid(np.arange(-nr, nr + 1), np.arange(-lr, lr + 1), indexing="ij")
    best = None
    for d, (px, py, nx, ny, lx, ly) in sides.items():
        x = np.rint(px + a_ * nx + b_ * lx).astype(int).ravel()
        y = np.rint(py + a_ * ny + b_ * ly).astype(int).ravel()
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        if not ok.any():
            continue
        v = share[y[ok], x[ok]]
        i = int(np.argmax(v))
        if best is None or v[i] > best["share"]:
            best = {"x": int(x[ok][i]), "y": int(y[ok][i]), "share": float(v[i]), "dir": d}
    return best or {"x": None, "y": None, "share": 0.0, "dir": None}


def fit_square(g: np.ndarray, B: np.ndarray, H: np.ndarray, slab: np.ndarray, seed: tuple, ws: float,
               icon: tuple | None = None, theta: float = 0.0, free: tuple | None = None) -> dict:
    """The seven-parameter soft fit round one seed (minimum negative log-likelihood of the
    two-state Cauchy mixture, L-BFGS-B), or a refusal dict. The square is turned by `theta` deg,
    fixed; with `free` = (lo, hi) deg the angle is an eighth parameter started at `theta`."""
    cx0, cy0 = seed[0], seed[1]
    # the window holds the square at any angle it may take
    tr = math.radians(theta)
    turn = math.sqrt(2.0) if free is not None else abs(math.cos(tr)) + abs(math.sin(tr))
    half = SIDE_RANGE[1] * ws / 2 * turn + WIN_PAD * ws
    X0, Y0 = int(max(0, math.floor(cx0 - half))), int(max(0, math.floor(cy0 - half)))
    X1, Y1 = int(min(g.shape[1], math.ceil(cx0 + half) + 1)), int(min(g.shape[0], math.ceil(cy0 + half) + 1))
    yy, xx = np.mgrid[Y0:Y1, X0:X1].astype(np.float64)
    use = slab[Y0:Y1, X0:X1].copy()
    if icon is not None:
        use &= np.hypot(xx - icon[0], yy - icon[1]) > ICON_R * ws + 1.0
    if use.mean() < MIN_SLAB_SHARE:
        return {"refused": "too_little_slab", "slab_share": round(float(use.mean()), 3)}
    iy, ix = np.nonzero(use)
    xs, ys = xx[0], yy[:, 0]
    xv, yv = xx[iy, ix], yy[iy, ix]
    axis = free is None and theta == 0.0
    gv = g[Y0:Y1, X0:X1].astype(np.float64)[iy, ix]
    Bv = B[Y0:Y1, X0:X1].astype(np.float64)[iy, ix]
    Hv = H[Y0:Y1, X0:X1].astype(np.float64)[iy, ix]

    def cover(p):
        cx, cy, wd, ht, sig = p[:5]
        if axis:
            # 0.1.0's separable product, value for value: L-BFGS-B follows rounding into other optima
            Sx = box_coverage(xs, cx - wd / 2, cx + wd / 2, sig)
            Sy = box_coverage(ys, cy - ht / 2, cy + ht / 2, sig)
            return (Sy[:, None] * Sx[None, :])[iy, ix]
        t = math.radians(p[7] if free is not None else theta)
        ct, st = math.cos(t), math.sin(t)
        dx, dy = xv - cx, yv - cy
        u, v = dx * ct + dy * st, -dx * st + dy * ct
        return box_coverage(u, -wd / 2, wd / 2, sig) * box_coverage(v, -ht / 2, ht / 2, sig)

    def nll(p):
        return -float(mix_ll(gv, Bv, Hv, p[5], p[6], cover(p)).sum())

    s0 = SIDE0 * ws
    lo = [cx0 - 6 * ws, cy0 - 6 * ws, SIDE_RANGE[0] * ws, SIDE_RANGE[0] * ws, SIG_RANGE[0], -0.5, -0.3]
    hi = [cx0 + 6 * ws, cy0 + 6 * ws, SIDE_RANGE[1] * ws, SIDE_RANGE[1] * ws, SIG_RANGE[1], 1.0, 0.3]
    x0 = [cx0, cy0, s0, s0, SIG0, ALPHA0, 0.0]
    if free is not None:
        lo, hi, x0 = lo + [free[0]], hi + [free[1]], x0 + [theta]
    lo, hi = np.array(lo), np.array(hi)
    p0 = np.clip(np.array(x0), lo + 1e-6, hi - 1e-6)
    r = minimize(nll, p0, method="L-BFGS-B", bounds=list(zip(lo, hi)),
                 options={"maxiter": 200, "eps": 1e-4})
    p = r.x
    # the alpha's significance: the NLL rise when the square is removed (a = 0, offset refitted)
    r0 = minimize(lambda q: -float(mix_ll(gv, Bv, Hv, 0.0, q[0]).sum()), [p[6]], method="L-BFGS-B",
                  bounds=[(-0.3, 0.3)])
    d_nll = float(r0.fun - r.fun)
    # its curvature in alpha alone gives a conditional standard error
    h_ = 1e-3
    f0 = r.fun
    pa, pb = p.copy(), p.copy()
    pa[5] += h_
    pb[5] -= h_
    fp, fm = nll(pa), nll(pb)
    curv = (fp - 2 * f0 + fm) / (h_ * h_)
    se_a = 1.0 / math.sqrt(curv) if curv > 0 else float("inf")
    cx, cy, wd, ht, sig, a, c = (float(v) for v in p[:7])
    th = float(p[7]) if free is not None else float(theta)
    t = math.radians(th)
    ct, st = math.cos(t), math.sin(t)
    corners = [(cx + sx * wd / 2 * ct - sy * ht / 2 * st, cy + sx * wd / 2 * st + sy * ht / 2 * ct)
               for sx, sy in ((-1, -1), (1, -1), (1, 1), (-1, 1))]
    return {"cx": cx, "cy": cy, "w": wd, "h": ht, "sig": sig, "alpha": a, "offset": c, "theta": th,
            "se_alpha": se_a, "d_nll": d_nll, "nll": float(r.fun), "n_px": int(use.sum()), "nit": int(r.nit),
            "at_bound": [k for k, (v, l_, h2) in enumerate(zip(p, lo, hi)) if v - l_ < 1e-3 or h2 - v < 1e-3],
            "rect": (min(q[0] for q in corners), min(q[1] for q in corners),
                     max(q[0] for q in corners), max(q[1] for q in corners)),
            "corners": corners}


def soft_score(f: dict, share: float, ws: float) -> dict:
    """The memberships and their product."""
    m = {"alpha": math.exp(-0.5 * ((f["alpha"] - ALPHA0) / ALPHA_SD) ** 2),
         "side": math.exp(-0.5 * ((f["w"] / ws - SIDE0) / SIDE_SD) ** 2 - 0.5 * ((f["h"] / ws - SIDE0) / SIDE_SD) ** 2),
         "signif": float(sigmoid((f["d_nll"] / (ws * ws) - DNLL_MID) / DNLL_SOFT)),
         "sharp": float(sigmoid((SIG_MID - f["sig"]) / SIG_SOFT)),
         "icon": float(sigmoid((share - SHARE_MID) / SHARE_SOFT))}
    m["score"] = float(np.prod(list(m.values())))
    return {k: round(v, 4) for k, v in m.items()}


def detect_frame(g: np.ndarray, B: np.ndarray, H: np.ndarray, slab: np.ndarray, ws: float, use_glyph: bool = True,
                 keep_all: bool = False, wall: tuple | None = None) -> list[dict]:
    """Every square on one frame: seeds, an axis-aligned first fit, the icon link, a refit with the
    icon masked at the prior angle (the baked wall under the icon), the soft score; a free-angle
    refit only where the prior's fit fails, stored as a surprise. Duplicates (centres within half a
    side) keep the best score."""
    share = icon_contrast_map(g, B, ws)
    if wall is None:
        wall = wall_field(B, ws)
    out = []
    for seed in propose(g, B, H, slab, ws):
        f = fit_square(g, B, H, slab, seed, ws)
        if "refused" in f:
            if keep_all:
                out.append({"seed": seed, **f})
            continue
        ln = link_icon(share, f, ws)
        prior = {"theta": None, "contrast": None, "source": "none: no icon linked"}
        surprise = None
        if ln["x"] is not None:
            # the mask stays on the link, as in 0.1.0; the sub-pixel centre only reads the wall
            icon = (ln["x"], ln["y"])
            ctr = icon_centre(share, ln["x"], ln["y"], ws)
            walls = wall_at(wall, ctr[0], ctr[1], ws)
            # the axis stays a candidate (every square measured before 2026-10-04 lay on an axis wall);
            # a wall through the icon joins it only where the static draws one clearly
            cands = [(0.0, None)] + [(a_, c_) for a_, c_ in walls
                                     if c_ >= WALL_MIN_CONTRAST and abs(wrap45(a_)) >= WALL_APART]
            # one fit per candidate; the likelihood gain over no square (each on its own window,
            # which grows with the angle, so raw NLLs are not comparable) picks among them
            fits = [(fit_square(g, B, H, slab, (f["cx"], f["cy"]), ws, icon=icon, theta=th_), th_, c_)
                    for th_, c_ in cands]
            fits = [q for q in fits if "refused" not in q[0]]
            f2, th, coh = max(fits, key=lambda q: q[0]["d_nll"]) if fits else ({"refused": "all"}, cands[0][0], cands[0][1])
            prior = {"theta": round(th, 2), "contrast": None if coh is None else round(coh, 2),
                     "source": "axis" if coh is None else "baked wall under the icon",
                     "icon": [round(ctr[0], 2), round(ctr[1], 2)],
                     "walls": [[round(a_, 2), round(b_, 2)] for a_, b_ in walls],
                     "candidates": [round(a_, 2) for a_, _ in cands]}
            if "refused" not in f2:
                f = f2
                ln = link_icon(share, f, ws)
                sc0 = soft_score(f, ln["share"], ws)
                # cross-reference before widening: the free angle runs only where the icon's glyph
                # names the Sonic Sensor and the prior's square still fails
                gate = (use_glyph and sc0["score"] < CUT and sc0["icon"] >= FREE_GATE
                        and sc0["signif"] >= FREE_GATE)
                q0 = None
                if gate:
                    gl0 = glyph_rank(g, ln["x"], ln["y"], ws)
                    q0 = (gl0 or {}).get("scores", {}).get("Deadlock:Q", -1.0)
                    gate = float(sigmoid((q0 - GLYPH_MID) / GLYPH_SOFT)) >= FREE_GATE
                if gate:
                    surprise = free_angle(g, B, H, slab, f, icon, th, ws, share, sc0)
                    surprise["glyph_q"] = round(q0, 3)
                    if surprise["adopted"]:
                        f, ln = surprise.pop("fit"), surprise.pop("link")
                    else:
                        surprise.pop("fit"), surprise.pop("link")
        sc = soft_score(f, ln["share"], ws)
        # the glyph membership multiplies the product, so a square scoring under CUT without it
        # cannot pass with it: the matcher runs only where it can change the decision
        gl = None
        sc["square"] = sc["score"]
        if use_glyph and sc["score"] >= CUT:
            gl = glyph_rank(g, ln["x"], ln["y"], ws)
            q = (gl or {}).get("scores", {}).get("Deadlock:Q", -1.0)
            sc["glyph"] = round(float(sigmoid((q - GLYPH_MID) / GLYPH_SOFT)), 4)
            sc["score"] = round(sc["square"] * sc["glyph"], 4)
        out.append({"seed": [round(v, 3) for v in seed], **{k: (round(v, 3) if isinstance(v, float) else v)
                                                            for k, v in f.items() if k not in ("rect", "corners")},
                    "rect": [round(v, 2) for v in f["rect"]],
                    "corners": [[round(a_, 2), round(b_, 2)] for a_, b_ in f["corners"]],
                    "prior": prior, "angle_source": "free" if surprise and surprise["adopted"] else
                    ("prior" if prior["theta"] is not None else "axis"),
                    "surprise": surprise, "icon": ln, "m": sc, "score": sc["score"],
                    "glyph": gl, "accepted": sc["score"] >= CUT})
    keep = []
    for d in sorted([d for d in out if "score" in d], key=lambda d: -d["score"]):
        if all(math.hypot(d["cx"] - k["cx"], d["cy"] - k["cy"]) > SIDE0 * ws / 2 for k in keep):
            keep.append(d)
    if keep_all:
        return keep + [d for d in out if "score" not in d]
    return keep


def free_angle(g, B, H, slab, f: dict, icon: tuple, th: float, ws: float, share: np.ndarray, sc0: dict) -> dict:
    """The surprise path: the prior-angle fit failed the cut although an icon and a significant tint
    are there. Refit with the angle free (FREE_SPAN either side of the prior, from each FREE_STARTS
    offset), keep the lowest NLL, and say why it ran and what it found."""
    best = None
    for off in FREE_STARTS:
        fr = fit_square(g, B, H, slab, (f["cx"], f["cy"]), ws, icon=icon, theta=th + off,
                        free=(th - FREE_SPAN, th + FREE_SPAN))
        if "refused" not in fr and (best is None or fr["nll"] < best["nll"]):
            best = fr
    out = {"reason": f"prior angle {th:.1f} deg scored {sc0['score']:.3f} < CUT with icon {sc0['icon']:.2f}, "
                     f"signif {sc0['signif']:.2f} and the glyph naming the sensor; failing memberships: "
                     + (", ".join(k for k in ("alpha", "side", "sharp") if sc0[k] < 0.5) or "none below 0.5"),
           "prior_theta": round(th, 2), "prior_score": sc0["score"], "adopted": False, "fit": None, "link": None}
    if best is None:
        out["free"] = "refused"
        return out
    ln = link_icon(share, best, ws)
    sc = soft_score(best, ln["share"], ws)
    out.update(free_theta=round(best["theta"], 2), free_score=sc["score"],
               off_prior=round(wrap45(best["theta"] - th), 2), adopted=sc["score"] >= CUT, fit=best, link=ln)
    return out


# ------------------------------------------------------------------ glyph (reported only)

_GLYPH = {}


def glyph_rank(Y: np.ndarray, x: float, y: float, ws: float) -> dict | None:
    """The linked icon's glyph classified over Deadlock's kit by the game-art matcher."""
    if "mod" not in _GLYPH:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import minimap_glyph_eval as mge  # noqa: PLC0415
        mge.build_extra(mge.PROBE_STATES, answers=True)
        _GLYPH["mod"] = mge
        _GLYPH["keys"] = list(mge.kit("Deadlock"))
    mge = _GLYPH["mod"]
    r = mge.classify(Y, x, y, _GLYPH["keys"], scale=ws)
    if not r:
        return None
    return {"pred": f"{r['pred'][0]}:{r['pred'][1]}", "score": round(r["score"], 3),
            "q_rot": (r.get("fits") or {}).get("Deadlock:Q", [None, None])[1],
            "margin": round(r["margin"], 3), "scores": {k: round(v, 3) for k, v in r["scores"].items()}}


# ------------------------------------------------------------------ evaluation

def labels(sid: str) -> list[dict]:
    p = STORE / "labels" / "ability" / f"{sid}.jsonl"
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("category_id") and not r.get("not_ability"):
                rows.append(r)
    return rows


def contrast_at(g: np.ndarray, x: float, y: float) -> float:
    xi, yi = int(x), int(y)
    p = g[max(0, yi - PATCH_R):yi + PATCH_R + 1, max(0, xi - PATCH_R):xi + PATCH_R + 1]
    return float(p.max() - p.min()) if p.size else float("nan")


def overlay(c: np.ndarray, dets: list[dict], marks: list[tuple], z: int = 3) -> np.ndarray:
    """Display only: nearest-neighbour enlargement, fitted squares (green accepted, grey not, orange
    when the free angle was adopted),
    linked icons (magenta), label marks (cyan live, yellow dim, white other)."""
    im = cv2.resize(c, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    for d in dets:
        if "rect" not in d:
            continue
        x0, y0, x1, y1 = d["rect"]
        col = (0, 220, 0) if d["accepted"] else (140, 140, 140)
        if d.get("angle_source") == "free":
            col = (0, 140, 255) if d["accepted"] else (0, 70, 130)
        pts = np.array([[(qx + 0.5) * z - 0.5, (qy + 0.5) * z - 0.5] for qx, qy in d["corners"]], np.int32)
        cv2.polylines(im, [pts], True, col, 1)
        if d["accepted"] and d["icon"]["x"] is not None:
            cv2.circle(im, (int(d["icon"]["x"] * z), int(d["icon"]["y"] * z)), int(ICON_R * z), (255, 0, 255), 1)
            cv2.putText(im, f"{d['alpha']:.2f} {d['score']:.2f}", (int(x0 * z), int(y0 * z) - 3),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 220, 0), 1)
    for x, y, kind in marks:
        col = {"live": (255, 255, 0), "rotated": (255, 255, 0), "dim": (0, 255, 255)}.get(kind, (255, 255, 255))
        cv2.drawMarker(im, (int(x * z), int(y * z)), col, cv2.MARKER_CROSS, 10, 1)
    return im


def score_frames(s: Sess, frames: dict) -> list[dict]:
    """frames: t_ms -> list of label dicts (x, y, category_id, kind). Returns one row per label
    plus the accepted squares that match no sensor label on that frame."""
    rows = []
    want = sorted(frames)
    for tt, c in s.crops(want):
        labs = frames.get(tt, [])
        g = luma(c)
        dets = detect_frame(g, s.B, s.H, s.slab, s.ws, wall=s.wall)
        acc = [d for d in dets if d["accepted"]]
        used = set()
        for lab in labs:
            near = [(math.hypot(d["icon"]["x"] - lab["x"], d["icon"]["y"] - lab["y"]), i)
                    for i, d in enumerate(acc) if d["icon"]["x"] is not None]
            near = [p for p in near if p[0] <= MATCH_PX * s.ws]
            hit = min(near) if near else None
            if hit is not None:
                used.add(hit[1])
            best_any = max([d for d in dets
                            if d["icon"]["x"] is not None
                            and math.hypot(d["icon"]["x"] - lab["x"], d["icon"]["y"] - lab["y"]) <= MATCH_PX * s.ws],
                           key=lambda d: d["score"], default=None)
            sq = [d for d in dets if d["icon"]["x"] is not None and d["m"]["square"] >= CUT
                  and math.hypot(d["icon"]["x"] - lab["x"], d["icon"]["y"] - lab["y"]) <= MATCH_PX * s.ws]
            rows.append({"session": s.sid, "t_ms": tt, "label": lab, "found": hit is not None,
                         "found_square_only": bool(sq),
                         "link_px": round(hit[0], 2) if hit else None,
                         "det": acc[hit[1]] if hit else None,
                         "best_unaccepted": None if hit or best_any is None else
                         {k: best_any[k] for k in ("score", "m", "alpha", "w", "h", "sig", "d_nll", "icon")}})
        sensor_here = any(lab.get("category_id") == "deadlock:sonic sensor" for lab in labs)
        for i, d in enumerate(acc):
            if i not in used:
                rows.append({"session": s.sid, "t_ms": tt, "label": None, "unmatched_square": d,
                             "sensor_labelled_frame": sensor_here})
        frames[tt] = (c, dets)
    return rows


def rotation_diagnosis(s: Sess, c: np.ndarray, d: dict, tt: float) -> dict:
    """For diagnosis only, never the decision: refit a found square with its angle free round the
    prior and report how far the data put the side from the baked wall."""
    g = luma(c)
    out = {"t_ms": tt, "prior_theta": (d.get("prior") or {}).get("theta"), "theta": d["theta"],
           "accepted": d["accepted"], "angle_source": d.get("angle_source"),
           "glyph_q_rot": (d.get("glyph") or {}).get("q_rot")}
    th = out["prior_theta"]
    if th is None:
        return out
    best = None
    for off in FREE_STARTS:
        fr = fit_square(g, s.B, s.H, s.slab, (d["cx"], d["cy"]), s.ws, icon=(d["icon"]["x"], d["icon"]["y"]),
                        theta=th + off, free=(th - FREE_SPAN, th + FREE_SPAN))
        if "refused" not in fr and (best is None or fr["nll"] < best["nll"]):
            best = fr
    if best is not None:
        out.update(free_theta=round(best["theta"], 2), free_minus_prior=round(wrap45(best["theta"] - th), 2),
                   free_nll_gain=round(d["nll"] - best["nll"], 2) if "nll" in d else None)
    return out


def cmd_frame(a) -> int:
    below_normal()
    s = sess(a.sid)
    (tt, c), = list(s.crops([s.snap(a.t * 1000)]))
    g = luma(c)
    dets = detect_frame(g, s.B, s.H, s.slab, s.ws, keep_all=True, wall=s.wall)
    for d in dets:
        print(json.dumps(d))
    if a.png:
        OUT.mkdir(parents=True, exist_ok=True)
        p = OUT / f"frame_{a.sid}_{int(tt)}.png"
        cv2.imwrite(str(p), overlay(c, dets, []))
        print(p)
    return 0


def summarise(rows: list[dict], ws_of: dict) -> dict:
    lab = [r for r in rows if r.get("label")]
    out = {}
    for kind in ("named", "live", "dim", "other", "rotated"):
        rr = [r for r in lab if r["label"]["kind"] == kind]
        if not rr:
            continue
        f = [r for r in rr if r["found"]]
        out[kind] = {"n": len(rr), "found": len(f), "rate": round(len(f) / len(rr), 3),
                     "found_square_only": sum(1 for r in rr if r.get("found_square_only"))}
        if kind in ("named", "live", "rotated") and f:
            al = [r["det"]["alpha"] for r in f]
            sd = [v / ws_of[r["session"]] for r in f for v in (r["det"]["w"], r["det"]["h"])]
            out[kind].update(alpha_median=round(float(np.median(al)), 3),
                             alpha_range=[round(min(al), 3), round(max(al), 3)],
                             side_median=round(float(np.median(sd)), 2),
                             side_range=[round(min(sd), 2), round(max(sd), 2)],
                             sig_median=round(float(np.median([r["det"]["sig"] for r in f])), 3),
                             link_px_median=round(float(np.median([r["link_px"] for r in f])), 2),
                             glyph_q_top=sum(1 for r in f if (r["det"].get("glyph") or {}).get("pred", "").endswith(":Q")),
                             glyph_scored=sum(1 for r in f if r["det"].get("glyph")),
                             theta_median=round(float(np.median([r["det"]["theta"] for r in f])), 2),
                             theta_off_axis_max=round(float(max(abs(wrap45(r["det"]["theta"])) for r in f)), 2),
                             near_axis_share=round(sum(abs(wrap45(r["det"]["theta"])) <= 5.0 for r in f) / len(f), 3),
                             free_adopted=sum(1 for r in f if r["det"].get("angle_source") == "free"))
    un = [r for r in rows if r.get("unmatched_square")]
    out["unmatched_squares_on_labelled_frames"] = len(un)
    return out


def cmd_eval(a) -> int:
    below_normal()
    OUT.mkdir(parents=True, exist_ok=True)
    rows, ws_of, neg, diag, surprises = [], {}, [], [], []
    # named instances and labelled positions, one pass per session
    for sid in DEV_LABEL_SESSIONS:
        s = sess(sid)
        ws_of[sid] = s.ws
        frames: dict = {}
        for (nsid, t, hx, hy, who) in NAMED:
            if nsid == sid:
                tt = s.snap(t * 1000)
                frames.setdefault(tt, []).append({"x": hx, "y": hy, "category_id": "deadlock:sonic sensor",
                                                  "kind": "named", "by": who, "t_label_ms": t * 1000})
        labs = labels(sid)
        sens_t = {r["t_ms"] for r in labs if r["category_id"] == "deadlock:sonic sensor"}
        for r in labs:
            if r["t_ms"] not in sens_t:
                continue
            tt = s.snap(r["t_ms"])
            if abs(tt - r["t_ms"]) > T_TOL_MS:
                rows.append({"session": sid, "t_ms": r["t_ms"], "label": {**r, "kind": "no_frame"}, "found": False})
                continue
            frames.setdefault(tt, []).append({"x": r["x"], "y": r["y"], "category_id": r["category_id"],
                                              "kind": "sensor?" if r["category_id"] == "deadlock:sonic sensor"
                                              else "other", "t_label_ms": r["t_ms"]})
        # live / dim by the patch-contrast rule, read on the cached frame
        for tt, c in s.crops(sorted(frames)):
            g = luma(c)
            for lab in frames[tt]:
                if lab["kind"] == "sensor?":
                    lab["contrast"] = contrast_at(g, lab["x"], lab["y"])
                    lab["kind"] = "dim" if lab["contrast"] <= DIM_CONTRAST_MAX else "live"
        fr = {k: list(v) for k, v in frames.items()}
        got = score_frames(s, fr)
        rows += got
        for tt, v in fr.items():
            if isinstance(v, tuple):
                c, dets = v
                surprises += [{"session": sid, "t_ms": tt, **d["surprise"]} for d in dets if d.get("surprise")]
                marks = [(lab["x"], lab["y"], lab["kind"]) for lab in frames[tt]]
                if any(lab["kind"] in ("named", "live", "dim") for lab in frames[tt]):
                    cv2.imwrite(str(OUT / f"eval_{sid}_{int(tt)}.png"), overlay(c, dets, marks))
        print(sid, "frames", len(frames), flush=True)
    # the turned sensor
    rsid, rx, ry, secs = ROTATED
    s = sess(rsid)
    ws_of[rsid] = s.ws
    fr = {}
    for sec in secs:
        fr.setdefault(s.snap(sec * 1000.0), []).append({"x": rx, "y": ry, "category_id": "deadlock:sonic sensor",
                                                        "kind": "rotated", "t_label_ms": sec * 1000.0})
    marks_of = {k: [(lab["x"], lab["y"], lab["kind"]) for lab in v] for k, v in fr.items()}
    rows += score_frames(s, fr)
    for tt, v in fr.items():
        if isinstance(v, tuple):
            cv2.imwrite(str(OUT / f"eval_{rsid}_{int(tt)}.png"), overlay(v[0], v[1], marks_of[tt]))
            near = [d for d in v[1] if d["icon"]["x"] is not None
                    and math.hypot(d["icon"]["x"] - rx, d["icon"]["y"] - ry) <= MATCH_PX * s.ws]
            if near:
                diag.append(rotation_diagnosis(s, v[0], max(near, key=lambda d: d["score"]), tt))
            surprises += [{"session": rsid, "t_ms": tt, **d["surprise"]} for d in v[1] if d.get("surprise")]
    print(rsid, "rotated frames", len(fr), flush=True)
    # negatives
    for sid in NEGATIVE_SESSIONS:
        try:
            s = sess(sid)
        except SystemExit as e:
            neg.append({"session": sid, "skipped": str(e)})
            continue
        idx = np.linspace(0, len(s.cache_t) - 1, NEG_FRAMES).astype(int)
        for tt, c in s.crops(s.cache_t[idx]):
            g = luma(c)
            all_ = detect_frame(g, s.B, s.H, s.slab, s.ws, wall=s.wall)
            dets = [d for d in all_ if d["accepted"]]
            surprises += [{"session": sid, "t_ms": tt, **d["surprise"]} for d in all_ if d.get("surprise")]
            neg.append({"session": sid, "t_ms": tt, "ws": s.ws, "squares": dets,
                        "squares_square_only": [d for d in all_ if d["m"]["square"] >= CUT]})
            if dets:
                cv2.imwrite(str(OUT / f"neg_{sid}_{int(tt)}.png"), overlay(c, dets, []))
        print(sid, "negatives done", flush=True)
    summ = summarise(rows, ws_of)
    nf = [n for n in neg if "squares" in n]
    summ["negative_frames"] = len(nf)
    summ["negative_squares"] = sum(len(n["squares"]) for n in nf)
    summ["negative_frames_with_square"] = sum(1 for n in nf if n["squares"])
    summ["negative_squares_square_only"] = sum(len(n["squares_square_only"]) for n in nf)
    summ["negative_skipped"] = [n for n in neg if "skipped" in n]
    summ["surprises"] = len(surprises)
    summ["surprises_adopted"] = sum(1 for x in surprises if x["adopted"])
    if diag:
        dd = [abs(x["free_minus_prior"]) for x in diag if x.get("free_minus_prior") is not None]
        summ["rotated_diagnosis"] = {"n": len(diag), "prior_theta_median": round(float(np.median([x["prior_theta"] for x in diag])), 2),
                                     "free_theta_median": round(float(np.median([x["free_theta"] for x in diag if x.get("free_theta") is not None])), 2) if dd else None,
                                     "abs_free_minus_prior_median": round(float(np.median(dd)), 2) if dd else None,
                                     "abs_free_minus_prior_max": round(float(max(dd)), 2) if dd else None}
    print(json.dumps(summ, indent=1))
    for r in rows:
        if r.get("label") and r["label"]["kind"] in ("named", "live") and not r["found"]:
            print("MISS", r["session"], r["t_ms"], r["label"]["x"], r["label"]["y"], json.dumps(r.get("best_unaccepted")))
        if r.get("label") and r["label"]["kind"] in ("dim", "other") and r["found"]:
            print("FALSE_LINK", r["session"], r["t_ms"], r["label"]["kind"], r["label"].get("category_id"),
                  r["det"]["score"], r["det"]["alpha"])
    for n in nf:
        for d in n["squares"]:
            print("NEG", n["session"], n["t_ms"], d["score"], d["alpha"], d["w"], d["h"], d["icon"], "ws", n["ws"], "glyph", (d.get("glyph") or {}).get("pred"), (d.get("glyph") or {}).get("scores"))
    for x in surprises:
        print("SURPRISE", json.dumps(x))
    for x in diag:
        print("ROT", json.dumps(x))
    (OUT / "eval.json").write_text(json.dumps({"version": VERSION, "summary": summ, "rows": rows, "negatives": neg,
                                               "surprises": surprises, "rotated_diagnosis": diag},
                                              indent=1, default=str), encoding="utf-8")
    if a.record:
        from reticle import metrics
        deps = constants()
        for kind in ("named", "live", "dim", "other"):
            if kind in summ:
                metrics.record(SERIES, part=f"dev_{kind}", session="a06f04a0059f+5822b6646448",
                               values={k: v for k, v in summ[kind].items() if isinstance(v, (int, float))},
                               deps=deps, context={"labels": "labels/ability", "named": NAMED},
                               note="crop cache only; baked static background; slab pixels only")
        metrics.record(SERIES, part="dev_negatives", session="+".join(NEGATIVE_SESSIONS),
                       values={"frames": summ["negative_frames"], "squares": summ["negative_squares"],
                               "frames_with_square": summ["negative_frames_with_square"]},
                       deps=deps, context={"neg_frames_per_session": NEG_FRAMES},
                       note="sessions with no Deadlock in the stored lineup; every accepted square is false")
    return 0


HELDOUT_DIR = STORE / "labels" / "minimap_glyph_heldout"
SENSOR_KEY = "Deadlock:Q"


def heldout_rows() -> dict:
    """The held-out labelling pass, last row per item key (as label_minimap_glyph_heldout.answered)."""
    last = {}
    for f in sorted(HELDOUT_DIR.glob("*.jsonl")):
        for ln in f.read_text(encoding="utf-8").splitlines():
            if ln.strip():
                r = json.loads(ln)
                last[r["key"]] = r
    return last


def cmd_heldout(a) -> int:
    """Score the frozen method once on the held-out pass: every sure item frame of every session. A sure
    Deadlock:Q mark is a sensor, split live/dim by the same patch-contrast rule; an accepted square linked
    within ICON_R of it finds it. Accepted squares near no Q mark are listed, with the frame's marks."""
    below_normal()
    out_dir = OUT / "heldout"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = [r for r in heldout_rows().values() if not r.get("unsure")]
    by: dict = {}
    for r in rows:
        by.setdefault(r["session_id"], []).append(r)
    marks_out, frames_out = [], []
    for sid, its in sorted(by.items()):
        try:
            s = sess(sid)
        except SystemExit as e:
            frames_out += [{"item": r["key"], "session": sid, "refused": str(e)} for r in its]
            continue
        held = {r["key"]: s.snap(r["t_ms"]) for r in its}
        got = dict(s.crops(sorted(set(held.values()))))
        for r in its:
            th = held[r["key"]]
            fr = {"item": r["key"], "session": sid, "agent": r.get("agent"), "kind": r.get("kind"),
                  "t_ms": r["t_ms"], "t_held": th, "nothing": r.get("nothing")}
            if th not in got or abs(th - r["t_ms"]) > T_TOL_MS:
                fr["refused"] = "no_frame"
                frames_out.append(fr)
                continue
            c = got[th]
            g = luma(c)
            dets = detect_frame(g, s.B, s.H, s.slab, s.ws, wall=s.wall)
            acc = [d for d in dets if d["accepted"]]
            roi = r.get("roi") or s.box
            pts = []
            for i, m in enumerate(r.get("marks") or []):
                x, y = m["x"] + roi[0] - s.box[0], m["y"] + roi[1] - s.box[1]
                pts.append((x, y, m.get("ability")))
                if m.get("ability") != SENSOR_KEY:
                    continue
                con = contrast_at(g, x, y)
                near = sorted((math.hypot(d["icon"]["x"] - x, d["icon"]["y"] - y), j) for j, d in enumerate(acc)
                              if d["icon"]["x"] is not None)
                hit = near[0] if near and near[0][0] <= MATCH_PX * s.ws else None
                sq = [d for d in dets if d["icon"]["x"] is not None and d["m"]["square"] >= CUT
                      and math.hypot(d["icon"]["x"] - x, d["icon"]["y"] - y) <= MATCH_PX * s.ws]
                marks_out.append({"item": r["key"], "session": sid, "t_ms": r["t_ms"], "i": i, "x": round(x, 1),
                                  "y": round(y, 1), "view": m.get("view"), "contrast": con,
                                  "state": "dim" if con <= DIM_CONTRAST_MAX else "live",
                                  "found": hit is not None, "found_square_only": bool(sq),
                                  "det": acc[hit[1]] if hit else None})
            q_pts = [(x, y) for x, y, ab in pts if ab == SENSOR_KEY]
            fr["squares"] = [d for d in acc if not any(math.hypot(d["icon"]["x"] - x, d["icon"]["y"] - y)
                                                       <= MATCH_PX * s.ws for x, y in q_pts)]
            fr["squares_marks_near"] = [[(ab, round(math.hypot(d["icon"]["x"] - x, d["icon"]["y"] - y), 1))
                                         for x, y, ab in pts
                                         if math.hypot(d["icon"]["x"] - x, d["icon"]["y"] - y) <= 2 * ICON_R * s.ws]
                                        for d in fr["squares"]]
            fr["n_q_marks"] = len(q_pts)
            frames_out.append(fr)
            if q_pts or fr["squares"]:
                cv2.imwrite(str(out_dir / f"heldout_{sid}_{int(th)}.png"),
                            overlay(c, dets, [(x, y, "live" if ab == SENSOR_KEY else "other") for x, y, ab in pts]))
        print(sid, len(its), "items", flush=True)
    summ = {}
    for st in ("live", "dim"):
        mm = [m for m in marks_out if m["state"] == st]
        summ[st] = {"n": len(mm), "found": sum(m["found"] for m in mm),
                    "found_square_only": sum(m["found_square_only"] for m in mm)}
    ok = [f for f in frames_out if "refused" not in f]
    summ["frames"] = len(ok)
    summ["frames_refused"] = len(frames_out) - len(ok)
    summ["sessions_refused"] = sorted({f["session"] for f in frames_out if "refused" in f and f["refused"] != "no_frame"})
    summ["frames_with_q_marks"] = sum(1 for f in ok if f["n_q_marks"])
    summ["squares_near_no_q_mark"] = sum(len(f["squares"]) for f in ok)
    summ["squares_near_no_q_mark_frames_without_q"] = sum(len(f["squares"]) for f in ok if not f["n_q_marks"])
    print(json.dumps(summ, indent=1))
    for m in marks_out:
        if not m["found"]:
            print("MISS", m["session"], m["t_ms"], m["state"], round(m["contrast"]), m["x"], m["y"], m["view"])
    for f in ok:
        for d, near in zip(f["squares"], f["squares_marks_near"]):
            print("UNEXPLAINED", f["session"], f["t_ms"], f["agent"], d["score"], d["alpha"], d["w"], d["h"],
                  d["icon"]["x"], d["icon"]["y"], (d.get("glyph") or {}).get("pred"), near)
    (out_dir / "heldout.json").write_text(json.dumps({"version": VERSION, "constants": constants(), "summary": summ,
                                                     "marks": marks_out, "frames": frames_out},
                                                    indent=1, default=str), encoding="utf-8")
    if a.record:
        from reticle import metrics
        for st in ("live", "dim"):
            metrics.record(SERIES, part=f"heldout_{st}", session="minimap_glyph_heldout", values=summ[st],
                           deps=constants(), context={"labels": "labels/minimap_glyph_heldout"},
                           note="scored once, method frozen on dev; crop cache only")
        metrics.record(SERIES, part="heldout_unexplained", session="minimap_glyph_heldout",
                       values={k: summ[k] for k in ("frames", "frames_with_q_marks", "squares_near_no_q_mark",
                                                    "squares_near_no_q_mark_frames_without_q")},
                       deps=constants(), context={"labels": "labels/minimap_glyph_heldout"},
                       note="accepted squares linked near no sure Deadlock:Q mark")
    return 0


def constants() -> dict:
    return {"version": VERSION, "side0": SIDE0, "side_range": SIDE_RANGE, "alpha0": ALPHA0, "icon_r": ICON_R,
            "band": BAND, "top_k": TOP_K, "a_clip": A_CLIP, "noise": NOISE, "sig0": SIG0, "dark": DARK,
            "link": [LINK_NORMAL, LINK_LATERAL], "alpha_sd": ALPHA_SD, "side_sd": SIDE_SD,
            "glyph": [GLYPH_MID, GLYPH_SOFT], "p_lit": P_LIT, "dnll": [DNLL_MID, DNLL_SOFT], "sig": [SIG_MID, SIG_SOFT], "share": [SHARE_MID, SHARE_SOFT], "cut": CUT,
            "wall": [WALL_OFFSET, WALL_HALF, WALL_STEP, WALL_SECOND, WALL_APART, WALL_CANDIDATES, WALL_MIN_CONTRAST],
            "free": [FREE_SPAN, list(FREE_STARTS), FREE_GATE]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("frame")
    p.add_argument("sid")
    p.add_argument("t", type=float)
    p.add_argument("--png", action="store_true")
    p = sub.add_parser("score")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("heldout")
    p.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    return {"frame": cmd_frame, "score": cmd_eval, "heldout": cmd_heldout}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
