r"""Touching minimap icons fitted jointly: render every icon of a stack, composite, compare.

    .\.venv\Scripts\python.exe prototypes\scene_stack.py --census
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --check [--record] [--recalibrate]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py [--record] [--sheet] [--parts 465-ally,...] [--space keys]

The first stage of `docs/SCENE_MODEL.md`: the render-and-compare minimap
model, on the case every single-icon reader fails (E11, E12 in
docs/STATISTICAL_ADJUDICATOR.md): two or three icons that touch. A
single-icon teardrop (`reticle.teardrop.fit_icon`, the owner of
[owns:icon-pose]) sees a neighbour's rim as its own colour and turns its lobe
toward it; here each pixel is explained by at most one icon, the one drawn on
top of it, so a neighbour's rim is the neighbour's evidence.

**The prior** (`neighbourhood`) says which icons exist near the labelled one
and roughly where, never which way they face:

- team icons (self and ally) from the stored `team_vision` product
  (`events/team_vision/<sid>.jsonl`): the tracked icons of the last stored
  frame before the labelled instant (within `PRIOR_MS`), else of the same
  frame. Positions only; the stored facings are not read;
- the class detectors at the labelled frame (`icon_teardrop.detections`) add
  an icon the stored tracks lack (the surprise path, flagged `detector`);
  enemies come only from here, since no enemy track is stored;
- the labelled icon starts at its detector's centre from the label set's
  manifest, as the teardrop does; the player's clicks never enter a fit.

Neighbours are the icons whose footprint can touch the labelled one (centres
within the two apex reaches plus `TOUCH_PAD`), at most `MAX_NEIGHBOURS`.

**The RGB renderer (0.2.0, `RGBScene`)** predicts the crop's pixels. The
background is the baked static for `(map, profile)` in two floor states
(`backgrounds`): the static is the unlit state, and on the lighting
reference's known floor the lit state is its colour scaled to `hi_gray`; per
pixel the cheaper state wins, so the drawn light is marginalised, not used.
Each icon is the same silhouette with a ring colour, a lobe colour ramped
from base to tip [domain:minimap/icon-tip-highlight] and a mean portrait
colour, all fixed per class and widget scale; enemy ring and lobe are
translucent [domain:minimap/enemy-lobe-translucent]
[domain:minimap/enemy-rim-faint-at-small-widget]. The colours, the enemy
alphas, one blur per widget scale and the noise are CALIBRATED (`calibrate`)
on unlabelled frames of the labelled sessions, at least `CAL_AWAY_MS` from
every labelled instant, from isolated owner teardrops; the file is the
store's `analysis/scene-stack-v2-20260929/calibration.json`. No gain is free.
The portrait disc is OWNED by its icon and left out of the comparison at a
constant cost (`PORTRAIT = "mask"`): no art is rendered, since identity is
not plumbed into this stage. The residual is RGB over a per-pixel noise
(calibrated noise and the reference's state noise), truncated at `TAU_SIG`.
`--check` measures the renderer alone before any fit: the labelled facing
against the reversed one at the player's clicked centre, and the renderer's
own best pose over the solo search, for the RGB renderer with the portrait
masked, with it drawn as the mean colour, and for 0.1.0's keys.

**The key renderer (0.1.0, `Scene`, `--space keys`)** works in the owners' continuous class keys, one channel each
(`teardrop.tealness`, `teardrop.yellowness`, `teardrop.redness`), which
ignore the grey floor's lighting. The background is the keys of the baked
static (`team_vision.load_inputs`' `static`, keyed by `(map, profile)`),
never the session's pixels. Each icon is `teardrop.render`'s silhouette at
the class radii times `minimap.widget_scale`: a ring and a lobe in its class
channel, each with its own gain (solved by least squares per hypothesis,
clamped to `GAIN`), and an opaque portrait disc predicted key-neutral (its
art is not rendered: no identity enters). Ally and self lobes are opaque;
an enemy lobe is a tint of opacity `ENEMY_LOBE_ALPHA` over what lies beneath
[domain:minimap/enemy-lobe-translucent]. Icons composite bottom to top in a
draw order the fit chooses; a pixel's prediction is what the order leaves on
top, so no pixel is evidence for two icons. The loss is a truncated square
(`TAU`) summed over the three keys on every pixel within reach of any icon.
The drawn light is not modelled (stage 2 of the design).

**The fit** (`fit_scene`). Each icon alone first (`solo`): centre within
`SOLO_SEARCH_PX` of its prior on a 1 px then 0.25 px grid, facing every
`GRID_DEG`. Its best pose and its best pose with the lobe on the far side
(over 90 degrees away) seed the joint fit. For every combination of seeds,
the draw order is chosen by trying every order with the poses fixed, then
each icon's pose is searched with the others held (centre within
`JOINT_SEARCH_PX` on a 0.5 px grid, every facing), twice round; the lowest
loss wins, and a last pass refines each pose (0.25 px, 1 degree). `margin`
is the loss the target's best far-half pose adds, others held.

**Arms**, each scored against the player's labels only: `teardrop` (the
owner recomputed from the crop cache at the detector's centre), `solo` (this
renderer, the labelled icon alone: the control that separates the joint
fit's gain from the renderer's) and `joint`. `fixed`/`broken` count flips
(error over 90 degrees) against the teardrop. Sets: E6's ally and enemy
labels (465 px), the Lotus self labels with the Ascent controls, and the
331 px ally, self and enemy sets. Each item is `stacked` when a neighbour's
centre lies within `STACK_PX` (scaled) of the labelled icon's detector
centre, the label tools' own rule.

GPU first (torch on CUDA; numpy is not implemented). Crop cache only, no
decode, no store stream writes. `--record` writes `metrics` series
`scene_stack_eval_v2` (0.1.0 wrote `scene_stack_eval`) and, with `--check`,
`scene_stack_check`; `--sheet` writes the store's
`analysis/scene-stack-v2-20260929/`. Not wired: nothing in `reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402
import facing_fusion as ff  # noqa: E402
import icon_facing_eval as ife  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import label_icon_facing as lif  # noqa: E402
import label_self_facing as lsf  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import tip_highlight as th  # noqa: E402
from reticle import teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "scene-stack-0.2.0"
OUT = sem.STORE / "analysis" / "scene-stack-v2-20260929"
#: "rgb" (0.2.0, the default) predicts the crop's RGB; "keys" is 0.1.0's class-key renderer, kept as the control.
SPACE = "rgb"
#: 0.1.0 recorded `scene_stack_eval`; 0.2.0 records its own series so neither run's cited values move.
SERIES = "scene_stack_eval_v2"
CHECK_SERIES = "scene_stack_check"

# ---- constants, set before any label was scored (logged with the predictions)
GRID_DEG = 5.0
SOLO_SEARCH_PX = 3.0      # at widget scale 1.0; the prior may be a ring-fit centre, 2.8-4.4 px off (E3, E4)
JOINT_SEARCH_PX = 2.0     # about each icon's current centre, each sweep
SWEEPS = 2
TAU = 0.35                # key units: a residual beyond this counts as this (clutter, pings, portrait skin)
GAIN = (0.2, 1.3)         # ring and lobe key gains, clamped
#: 0.1.0 solves the ring's and the lobe's gains apart ("split"). Post hoc, after
#: the 331 px sets failed: "shared" solves one gain for the whole silhouette, as
#: the teardrop's single template does, so a misplaced lobe cannot be dimmed away.
GAIN_MODE = "split"
ENEMY_LOBE_ALPHA = 0.5    # unmeasured; the enemy lobe is a tint [domain:minimap/enemy-lobe-translucent]
REACH_PAD = 4.0           # scored pixels reach this far past an icon's apex (scale 1.0), as `teardrop.WINDOW`
TOUCH_PAD = 2.0           # px at scale 1.0: neighbours whose footprints can touch
STACK_PX = lif.STACK_PX   # 22 px at scale 1.0: the label tools' stacked rule
MAX_NEIGHBOURS = 3
PRIOR_MS = 200.0
SAME_PX = 7.0             # scale 1.0: a prior or detector icon this near the target's centre is the target
CHUNK = 2048

CLASS_RADII = {"self": (td.R_IN, td.R_OUT, td.L),
               "ally": (td.ICON_CLASSES["ally"].r_in, td.ICON_CLASSES["ally"].r_out, td.ICON_CLASSES["ally"].L),
               "enemy": (td.ICON_CLASSES["enemy"].r_in, td.ICON_CLASSES["enemy"].r_out,
                         td.ICON_CLASSES["enemy"].L)}
CHANNEL = {"ally": 0, "self": 1, "enemy": 2}
ARMS = ("teardrop", "solo", "joint")


def _torch():
    import torch
    if not torch.cuda.is_available():
        raise SystemExit("scene_stack needs CUDA (GPU first); no CPU path is implemented")
    torch.set_num_threads(1)
    return torch, torch.device("cuda")


torch, DEV = _torch()


def keys(img: np.ndarray) -> np.ndarray:
    """The three class keys, (3, H, W) float32: teal, yellow, red (the owners' functions)."""
    return np.stack([td.tealness(img), td.yellowness(img), td.redness(img)]).astype(np.float32)


# ---------------------------------------------------------------- the renderer

def layers(cls: str, sc: float, px, py, x, y, th):
    """Opacity, ring and lobe of `cls` icons at poses `(x, y, th)` (each (N, 1)) over pixels `px, py` (P,).

    Returns `(O, ring, lobe)`, each (N, P): the icon hides `O` of what lies
    beneath and adds `g_r * ring + g_l * lobe` in its class channel.
    """
    r_in, r_out, L_ = (v * sc for v in CLASS_RADII[cls])
    edge = td.EDGE * sc
    dx, dy = px[None, :] - x, py[None, :] - y
    c, s = torch.cos(th), torch.sin(th)
    u = dx * c + dy * s
    v = -dx * s + dy * c
    rho = torch.sqrt(dx * dx + dy * dy)
    ca = r_out / L_
    sa = math.sqrt(max(0.0, 1.0 - ca * ca))
    d_wedge = u * ca + v.abs() * sa - r_out
    d_tri = torch.maximum(d_wedge, torch.maximum(r_out * ca - u, u - L_))
    d_tear = torch.minimum(rho - r_out, d_tri)
    A = (0.5 - d_tear / edge).clamp(0.0, 1.0)
    S = (0.5 - torch.maximum(d_tear, r_in - rho) / edge).clamp(0.0, 1.0)
    outside = (rho > r_out).float()
    lobe = S * outside
    ring = S - lobe
    O = A - (1.0 - ENEMY_LOBE_ALPHA) * lobe if cls == "enemy" else A
    return O, ring, lobe


class Scene:
    """One neighbourhood: observed keys and background keys over the scored pixels, and the icons."""

    def __init__(self, obs_keys: np.ndarray, bg_keys: np.ndarray, icons: list[dict], sc: float):
        self.sc = sc
        self.icons = icons
        h, w = obs_keys.shape[1:]
        yy, xx = np.mgrid[0:h, 0:w]
        keep = np.zeros((h, w), bool)
        for ic in icons:
            reach = (CLASS_RADII[ic["cls"]][2] + REACH_PAD + SOLO_SEARCH_PX) * sc
            keep |= np.hypot(xx - ic["x0"], yy - ic["y0"]) <= reach
        self.mask = keep
        self.px = torch.tensor(xx[keep], dtype=torch.float32, device=DEV)
        self.py = torch.tensor(yy[keep], dtype=torch.float32, device=DEV)
        self.obs = torch.tensor(obs_keys[:, keep], dtype=torch.float32, device=DEV)   # (3, P)
        self.bg = torch.tensor(bg_keys[:, keep], dtype=torch.float32, device=DEV)

    # A pose is (x, y, deg, g_ring, g_lobe).
    def _one(self, i: int, pose):
        ic = self.icons[i]
        x, y, deg = (torch.tensor([[v]], dtype=torch.float32, device=DEV) for v in pose[:3])
        O, ring, lobe = layers(ic["cls"], self.sc, self.px, self.py, x, y, torch.deg2rad(deg))
        E = torch.zeros(3, self.px.shape[0], device=DEV)
        E[CHANNEL[ic["cls"]]] = pose[3] * ring[0] + pose[4] * lobe[0]
        return O[0], E

    def stack(self, order, poses, skip=None):
        """Composite `order` (bottom to top) of fixed `poses` over the background.

        With `skip`, returns `(K_below, T_above, C_above)` about icon `skip`:
        the final keys are `T_above * K_mid + C_above`, where `K_mid` is that
        icon composited over `K_below`.
        """
        K = self.bg.clone()
        if skip is None:
            for i in order:
                O, E = self._one(i, poses[i])
                K = (1.0 - O)[None] * K + E
            return K
        k = order.index(skip)
        for i in order[:k]:
            O, E = self._one(i, poses[i])
            K = (1.0 - O)[None] * K + E
        T = torch.ones(self.px.shape[0], device=DEV)
        C = torch.zeros_like(K)
        for i in order[k + 1:]:
            O, E = self._one(i, poses[i])
            T = (1.0 - O) * T
            C = (1.0 - O)[None] * C + E
        return K, T, C

    def loss_of(self, K) -> float:
        r = (self.obs - K).clamp(-TAU, TAU)
        return float((r * r).sum())

    def search(self, i: int, order, poses, cands: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Loss and LS gains of icon `i` at every candidate `(x, y, deg)` row, the others held.

        Returns `(loss (N,), gains (N, 2))`.
        """
        ic = self.icons[i]
        c = CHANNEL[ic["cls"]]
        Kb, T, C = self.stack(order, poses, skip=i)
        out_l, out_g = [], []
        for a in range(0, len(cands), CHUNK):
            cc = torch.tensor(cands[a:a + CHUNK], dtype=torch.float32, device=DEV)
            O, ring, lobe = layers(ic["cls"], self.sc, self.px, self.py, cc[:, :1], cc[:, 1:2],
                                   torch.deg2rad(cc[:, 2:3]))
            base = T[None, None, :] * (1.0 - O)[:, None, :] * Kb[None] + C[None]      # (N, 3, P)
            r0 = self.obs[None] - base
            br, bl = T[None] * ring, T[None] * lobe
            if GAIN_MODE == "shared":
                bs = br + bl
                gr = ((r0[:, c] * bs).sum(1) / (bs * bs).sum(1).clamp_min(1e-6)).clamp(*GAIN)
                gl = gr
            else:
                gr = ((r0[:, c] * br).sum(1) / (br * br).sum(1).clamp_min(1e-6)).clamp(*GAIN)
                gl = ((r0[:, c] * bl).sum(1) / (bl * bl).sum(1).clamp_min(1e-6)).clamp(*GAIN)
            r0[:, c] -= gr[:, None] * br + gl[:, None] * bl
            r = r0.clamp(-TAU, TAU)
            out_l.append((r * r).sum((1, 2)))
            out_g.append(torch.stack([gr, gl], 1))
        return torch.cat(out_l).cpu().numpy(), torch.cat(out_g).cpu().numpy()


# ---------------------------------------------------------------- the RGB renderer (0.2.0)

TAU_SIG = 3.0          # residuals beyond 3 noise sigmas count as 3 (clutter, pings, the drawn light)
OWN_COST = 1.0         # sigma^2 units: a pixel the portrait owns costs what a well-explained pixel does
OWN_PAD = 0.5          # px at scale 1.0 inside r_in: the portrait's owned disc
#: "mask": the portrait disc is owned by its icon and left out of the comparison (0.2.0);
#: "disc": it is predicted as the class's calibrated mean portrait colour (the P3 ablation).
PORTRAIT = "mask"
CAL_SIGMAS = (0.0, 0.4, 0.7, 1.0, 1.4)         # Gaussian blur of the composite, px
CAL_ALPHA_RING = (0.25, 0.5, 0.75, 1.0)        # enemy only; team icons are opaque
CAL_ALPHA_LOBE = (0.25, 0.4, 0.55, 0.7, 0.85, 1.0)
CAL_FRAMES = 90        # unlabelled frames per session
CAL_MAX_ICONS = 80     # per (class, widget scale)
CAL_AWAY_MS = 3000.0   # a calibration frame is this far from every labelled instant
CAL_MIN_NCC = 0.75
CAL_MIN_NCC_SMALL = 0.6    # the 331 px widget: the owner's own self gate there is 0.55
CAL_FRAMES_SMALL_MULT = 4  # the 331 px sessions yield few isolated confident icons per frame
CAL_MIN_MARGIN = 0.1
CAL_SIGMA0 = 0.06      # noise sigma for choosing blur and alphas (RGB in 0..1)


def _kernel(sigma: float):
    if sigma <= 0:
        return None
    r = max(1, int(math.ceil(3 * sigma)))
    x = torch.arange(-r, r + 1, dtype=torch.float32, device=DEV)
    k = torch.exp(-x * x / (2 * sigma * sigma))
    return k / k.sum()


def blur(img, k):
    """Separable Gaussian over (N, C, H, W), replicate border."""
    if k is None:
        return img
    import torch.nn.functional as F
    C, r = img.shape[1], (len(k) - 1) // 2
    img = F.pad(img, (r, r, r, r), mode="replicate")
    img = F.conv2d(img, k.view(1, 1, 1, -1).repeat(C, 1, 1, 1), groups=C)
    return F.conv2d(img, k.view(1, 1, -1, 1).repeat(C, 1, 1, 1), groups=C)


def geometry(cls: str, sc: float, px, py, x, y, th):
    """Ring, lobe, portrait disc, tip ramp and radius of `cls` icons at poses (N, 1) over pixels (P,)."""
    r_in, r_out, L_ = (v * sc for v in CLASS_RADII[cls])
    edge = td.EDGE * sc
    dx, dy = px[None, :] - x, py[None, :] - y
    c, s = torch.cos(th), torch.sin(th)
    u = dx * c + dy * s
    v = -dx * s + dy * c
    rho = torch.sqrt(dx * dx + dy * dy)
    ca = r_out / L_
    sa = math.sqrt(max(0.0, 1.0 - ca * ca))
    d_wedge = u * ca + v.abs() * sa - r_out
    d_tri = torch.maximum(d_wedge, torch.maximum(r_out * ca - u, u - L_))
    d_tear = torch.minimum(rho - r_out, d_tri)
    A = (0.5 - d_tear / edge).clamp(0.0, 1.0)
    S = (0.5 - torch.maximum(d_tear, r_in - rho) / edge).clamp(0.0, 1.0)
    lobe = S * (rho > r_out).float()
    ring = S - lobe
    disc = (A - S).clamp_min(0.0)
    u0 = r_out * ca
    t = ((u - u0) / (L_ - u0)).clamp(0.0, 1.0)
    own = (rho < r_in - OWN_PAD * sc).float()
    return ring, lobe, disc, t, own


def rgb_layers(cls: str, sc: float, cal: dict, px, py, x, y, th):
    """Opacity `O` (N, P), premultiplied colour `C` (N, 3, P) and portrait ownership `own` (N, P)."""
    ring, lobe, disc, t, own = geometry(cls, sc, px, py, x, y, th)
    cc = cal["colours"]
    col = {k: torch.tensor(cc[k], dtype=torch.float32, device=DEV)[None, :, None]
           for k in ("ring", "base", "tip", "disc")}
    a_r, a_l = cal["alpha_ring"], cal["alpha_lobe"]
    O = a_r * ring + a_l * lobe + disc
    C = ((a_r * ring)[:, None] * col["ring"] + (a_l * lobe * (1 - t))[:, None] * col["base"]
         + (a_l * lobe * t)[:, None] * col["tip"] + disc[:, None] * col["disc"])
    if PORTRAIT != "mask":
        own = torch.zeros_like(own)
    return O, C, own


def _scene_window(icons, sc, shape, pad_px):
    h, w = shape
    reach = [(CLASS_RADII[ic["cls"]][2] + REACH_PAD + SOLO_SEARCH_PX) * sc for ic in icons]
    x0 = max(0, int(math.floor(min(ic["x0"] - r for ic, r in zip(icons, reach)))) - pad_px)
    y0 = max(0, int(math.floor(min(ic["y0"] - r for ic, r in zip(icons, reach)))) - pad_px)
    x1 = min(w, int(math.ceil(max(ic["x0"] + r for ic, r in zip(icons, reach)))) + pad_px + 1)
    y1 = min(h, int(math.ceil(max(ic["y0"] + r for ic, r in zip(icons, reach)))) + pad_px + 1)
    return x0, y0, x1, y1, reach


def backgrounds(s):
    """The baked background in two floor states, `(bg (2, H, W, 3) in 0..1, sd (H, W) in 0..1)`.

    The baked static is the UNLIT state: its grey matches the lighting
    reference's `lo_gray` (median difference under a grey level) and sits
    about 55-60 below `hi_gray`. On the reference's known floor the lit state
    is the static's colour scaled to `hi_gray`, the unlit one scaled to
    `lo_gray`; elsewhere both are the static. The drawn light is a nuisance
    here, marginalised per pixel (the cheaper state wins); stage 2 makes it
    evidence. `sd` is the reference's per-state noise, zero off the floor.
    Every value comes from baked (map, profile) geometry, none from a session.
    """
    got = getattr(s, "_scene_bg", None)
    if got is not None:
        return got
    st = s.inputs.static.astype(np.float32)
    ref = s.inputs.light
    bg = np.stack([st, st]) / 255.0
    sd = np.zeros(st.shape[:2], np.float32)
    if ref is not None:
        g = np.maximum(cv2.cvtColor(s.inputs.static, cv2.COLOR_BGR2GRAY).astype(np.float32), 1.0)
        k = ref.known
        for j, lvl in enumerate((ref.lo, ref.hi)):
            bg[j][k] = np.clip(st[k] * (lvl[k].astype(np.float32) / g[k])[:, None], 0, 255) / 255.0
        sd[k] = np.minimum(ref.sd_lo, ref.sd_hi)[k].astype(np.float32) / 255.0
    s._scene_bg = (bg, sd)
    return s._scene_bg


class RGBScene:
    """One neighbourhood in RGB: the crop and the two-state baked background over a window, and the icons.

    Poses are `(x, y, deg, 0, 0)`: no gains, so a misplaced lobe cannot be dimmed away.
    """

    def __init__(self, crop: np.ndarray, s, icons: list[dict], sc: float, cal: dict):
        self.sc, self.icons, self.cal = sc, icons, cal
        scal = cal["scales"][_skey(sc)]
        self.k = _kernel(scal["sigma_blur"])
        pad = 0 if self.k is None else (len(self.k) - 1) // 2
        x0, y0, x1, y1, reach = _scene_window(icons, sc, crop.shape[:2], pad + 1)
        self.win = (x0, y0, x1, y1)
        self.H, self.W = y1 - y0, x1 - x0
        yy, xx = np.mgrid[y0:y1, x0:x1]
        keep = np.zeros(yy.shape, bool)
        for ic, r in zip(icons, reach):
            keep |= np.hypot(xx - ic["x0"], yy - ic["y0"]) <= r
        self.keep_np = keep
        self.keep = torch.tensor(keep.ravel(), dtype=torch.float32, device=DEV)
        self.px = torch.tensor(xx.ravel(), dtype=torch.float32, device=DEV)
        self.py = torch.tensor(yy.ravel(), dtype=torch.float32, device=DEV)
        bg, sd = backgrounds(s)
        self.obs = torch.tensor(crop[y0:y1, x0:x1].reshape(-1, 3).T / 255.0, dtype=torch.float32, device=DEV)
        self.bg = torch.tensor(bg[:, y0:y1, x0:x1].reshape(2, -1, 3).transpose(0, 2, 1).copy(),
                               dtype=torch.float32, device=DEV)                              # (2, 3, P)
        sdw = torch.tensor(sd[y0:y1, x0:x1].ravel(), dtype=torch.float32, device=DEV)
        self.sig = torch.sqrt(scal["sigma_noise"] ** 2 + sdw ** 2)                           # (P,)
        self.cls_cal = {c: scal["classes"][c] for c in {ic["cls"] for ic in icons}}

    def _one(self, i: int, pose):
        ic = self.icons[i]
        x, y, deg = (torch.tensor([[v]], dtype=torch.float32, device=DEV) for v in pose[:3])
        O, C, own = rgb_layers(ic["cls"], self.sc, self.cls_cal[ic["cls"]], self.px, self.py, x, y,
                               torch.deg2rad(deg))
        return O[0], C[0], own[0]

    def stack(self, order, poses, skip=None):
        """`(K, Wn)`: the composite (2, 3, P), one per floor state, and the compared weight (P,).
        With `skip`, the layers below and above icon `skip`: `(Kb, Wb, T, Ca, Wa)`."""
        K, Wn = self.bg.clone(), torch.ones(self.px.shape[0], device=DEV)
        if skip is None:
            for i in order:
                O, C, own = self._one(i, poses[i])
                K = (1 - O)[None, None] * K + C[None]
                Wn = (1 - O) * Wn + O * (1 - own)
            return K, Wn
        k = order.index(skip)
        for i in order[:k]:
            O, C, own = self._one(i, poses[i])
            K = (1 - O)[None, None] * K + C[None]
            Wn = (1 - O) * Wn + O * (1 - own)
        T = torch.ones_like(Wn)
        Ca, Wa = torch.zeros_like(K[0]), torch.zeros_like(Wn)
        for i in order[k + 1:]:
            O, C, own = self._one(i, poses[i])
            T = (1 - O) * T
            Ca = (1 - O)[None] * Ca + C
            Wa = (1 - O) * Wa + O * (1 - own)
        return K, Wn, T, Ca, Wa

    def predict(self, K):
        """Blurred prediction (N, 2, 3, P) of composites (N, 2, 3, P)."""
        N = K.shape[0]
        return blur(K.reshape(N * 2, 3, self.H, self.W), self.k).reshape(N, 2, 3, -1)

    def _err(self, K):
        """Per-pixel error (N, P) in sigma^2, the cheaper floor state, before truncation."""
        e = (((self.obs[None, None] - self.predict(K)) / self.sig) ** 2).sum(2)
        return e.min(1).values

    def _loss(self, K, Wn):
        e = self._err(K).clamp(max=TAU_SIG ** 2)
        return (self.keep[None] * (Wn * e + (1 - Wn) * OWN_COST)).sum(-1)

    def loss_of(self, KW) -> float:
        K, Wn = KW
        return float(self._loss(K[None], Wn[None])[0])

    def search(self, i: int, order, poses, cands: np.ndarray):
        ic = self.icons[i]
        Kb, Wb, T, Ca, Wa = self.stack(order, poses, skip=i)
        out = []
        for a in range(0, len(cands), CHUNK // 4):
            cc = torch.tensor(cands[a:a + CHUNK // 4], dtype=torch.float32, device=DEV)
            O, C, own = rgb_layers(ic["cls"], self.sc, self.cls_cal[ic["cls"]], self.px, self.py,
                                   cc[:, :1], cc[:, 1:2], torch.deg2rad(cc[:, 2:3]))
            K = T[None, None, None] * ((1 - O)[:, None, None] * Kb[None] + C[:, None]) + Ca[None, None]
            Wn = T[None] * ((1 - O) * Wb[None] + O * (1 - own)) + Wa[None]
            out.append(self._loss(K, Wn))
        return torch.cat(out).cpu().numpy(), np.zeros((len(cands), 2), np.float32)

    def full_images(self, order, poses, shape):
        """Prediction (the cheaper state per pixel), weight and residual magnitude as crop-sized arrays."""
        K, Wn = self.stack(order, poses)
        pred = self.predict(K[None])[0]                                      # (2, 3, P)
        e = (((self.obs[None] - pred) / self.sig) ** 2).sum(1)               # (2, P)
        j = e.argmin(0)
        best = torch.where(j[None] == 0, pred[0], pred[1])
        res = e.min(0).values.clamp(max=TAU_SIG ** 2).sqrt()
        x0, y0, x1, y1 = self.win
        h, w = shape
        P = np.zeros((h, w, 3), np.uint8)
        R = np.zeros((h, w), np.float32)
        Wimg = np.zeros((h, w), np.float32)
        P[y0:y1, x0:x1] = np.clip(best.T.reshape(self.H, self.W, 3).cpu().numpy() * 255, 0, 255).astype(np.uint8)
        R[y0:y1, x0:x1] = (res * self.keep).reshape(self.H, self.W).cpu().numpy()
        Wimg[y0:y1, x0:x1] = (Wn * self.keep).reshape(self.H, self.W).cpu().numpy()
        return P, R, Wimg


def _skey(sc: float) -> str:
    return f"{sc:.3f}"


# ---------------------------------------------------------------- calibration (unlabelled frames)

def calibration_icons(sess, label_times: dict) -> dict:
    """Isolated, confidently read teardrops on unlabelled frames: `{(cls, skey): [icon]}`.

    Frames are spread evenly over each labelled session's crop cache, at least
    `CAL_AWAY_MS` from every labelled instant; poses come from the owner
    (`facing_fusion.fit`, i.e. `teardrop.fit_icon`), never from a label.
    """
    out = defaultdict(list)
    for sid, lts in sorted(label_times.items()):
        s = sess(sid)
        lts = np.asarray(sorted(lts))
        ts = [t for t in s.cache_t if np.min(np.abs(lts - t)) >= CAL_AWAY_MS]
        n_fr = CAL_FRAMES * (1 if widget_scale(s.inputs.static.shape[1]) >= 0.99 else CAL_FRAMES_SMALL_MULT)
        pick = [ts[int(k)] for k in np.linspace(0, len(ts) - 1, n_fr)] if len(ts) > n_fr else ts
        n0 = sum(len(v) for v in out.values())
        why = defaultdict(int)
        for t, crop in s.crops(pick):
            sc = widget_scale(crop.shape[1])
            min_ncc = CAL_MIN_NCC if sc >= 0.99 else CAL_MIN_NCC_SMALL
            dets = [(c, d) for c in ("self", "ally", "enemy") for d in it_.detections(crop, c, s)]
            for c, d in dets:
                why["det_" + c] += 1
                others = [e for c2, e in dets if e is not d]
                if any(math.hypot(e["cx"] - d["cx"], e["cy"] - d["cy"]) <= (2 * td.L + 4) * sc for e in others):
                    why["not_isolated"] += 1
                    continue
                f = ff.fit(crop, c, float(d["cx"]), float(d["cy"]), sc)
                if not f.get("read") or f.get("ncc", 0) < min_ncc or f.get("margin", 1.0) < CAL_MIN_MARGIN:
                    why["unread" if not f.get("read") else ("low_ncc" if f.get("ncc", 0) < min_ncc
                                                            else "low_margin")] += 1
                    continue
                key = (c, _skey(sc))
                if len(out[key]) < CAL_MAX_ICONS * 3:
                    out[key].append({"sid": sid, "t_ms": float(t), "cls": c, "x": float(f["x"]), "y": float(f["y"]),
                                     "deg": float(f["deg"]), "sc": sc, "_crop": crop, "_s": s})
        print(f"  calibration {sid}: {sum(len(v) for v in out.values()) - n0} icons from {len(pick)} frames; "
              f"{dict(why)}", flush=True)
    rng = np.random.default_rng(0)
    for key, v in out.items():
        if len(v) > CAL_MAX_ICONS:
            out[key] = [v[i] for i in sorted(rng.choice(len(v), CAL_MAX_ICONS, replace=False))]
    return out


def _design(icon, sigma, a_r, a_l):
    """Per icon: the observed pixels y (3, P), the fixed term b (3, P), the colour bases X (4, P), the mask."""
    sc = icon["sc"]
    k = _kernel(sigma)
    pad = 0 if k is None else (len(k) - 1) // 2
    ic = {"cls": icon["cls"], "x0": icon["x"], "y0": icon["y"]}
    x0, y0, x1, y1, reach = _scene_window([ic], sc, icon["_crop"].shape[:2], pad + 1)
    H, W = y1 - y0, x1 - x0
    yy, xx = np.mgrid[y0:y1, x0:x1]
    px = torch.tensor(xx.ravel(), dtype=torch.float32, device=DEV)
    py = torch.tensor(yy.ravel(), dtype=torch.float32, device=DEV)
    t1 = lambda v: torch.tensor([[v]], dtype=torch.float32, device=DEV)  # noqa: E731
    ring, lobe, disc, t, own = (z[0] for z in geometry(icon["cls"], sc, px, py, t1(icon["x"]), t1(icon["y"]),
                                                       t1(math.radians(icon["deg"]))))
    O = a_r * ring + a_l * lobe + disc
    obs = torch.tensor(icon["_crop"][y0:y1, x0:x1].reshape(-1, 3).T / 255.0, dtype=torch.float32, device=DEV)
    # The floor state nearest the observed grey, per pixel (no pose enters the choice).
    bgs, _sd = backgrounds(icon["_s"])
    g = cv2.cvtColor(icon["_crop"][y0:y1, x0:x1], cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
    gl = [cv2.cvtColor((bgs[j, y0:y1, x0:x1] * 255).astype(np.uint8), cv2.COLOR_BGR2GRAY).astype(np.float32) / 255.0
          for j in (0, 1)]
    pick = (np.abs(g - gl[1]) < np.abs(g - gl[0]))[..., None]
    bg_np = np.where(pick, bgs[1, y0:y1, x0:x1], bgs[0, y0:y1, x0:x1])
    bg = torch.tensor(bg_np.reshape(-1, 3).T.copy(), dtype=torch.float32, device=DEV)
    b = blur(((1 - O)[None] * bg)[None].view(1, 3, H, W), k).reshape(3, -1)
    bases = torch.stack([a_r * ring, a_l * lobe * (1 - t), a_l * lobe * t, disc])       # (4, P)
    X = blur(bases.view(1, 4, H, W), k).reshape(4, -1)
    keep = (np.hypot(xx - icon["x"], yy - icon["y"]) <= (CLASS_RADII[icon["cls"]][2] + REACH_PAD) * sc).ravel()
    m = torch.tensor(keep, device=DEV) & (own < 0.5)
    return obs[:, m], b[:, m], X[:, m]


def _solve(designs, sigma0=CAL_SIGMA0, rounds=3):
    """Colours (4, 3) by robust least squares over every icon's pixels, and the truncated loss."""
    Y = torch.cat([d[0] - d[1] for d in designs], 1)                  # (3, P)
    X = torch.cat([d[2] for d in designs], 1)                         # (4, P)
    w = torch.ones(Y.shape[1], device=DEV)
    for _ in range(rounds):
        Xw = X * w[None]
        A = Xw @ X.T + 1e-4 * torch.eye(4, device=DEV)
        col = torch.linalg.solve(A, Xw @ Y.T)                         # (4, 3)
        r = Y - col.T @ X
        e = (r * r).sum(0)
        w = (e <= (TAU_SIG * sigma0) ** 2).float()
    col = col.clamp(0.0, 1.0)
    r = Y - col.T @ X
    e = (r * r).sum(0) / sigma0 ** 2
    mad = float(torch.median(r.abs().flatten()[w.repeat(3) > 0]) * 1.4826) if w.sum() > 0 else sigma0
    return col.cpu().numpy(), float(e.clamp(max=TAU_SIG ** 2).mean()), mad


def calibrate(sess, label_times: dict) -> dict:
    """Class colours, enemy alphas, blur and noise per widget scale, from unlabelled frames."""
    icons = calibration_icons(sess, label_times)
    out = {"version": VERSION, "made_from": "unlabelled frames of the labelled sessions, >= "
           f"{CAL_AWAY_MS:.0f} ms from any labelled instant; owner teardrop poses (ncc >= {CAL_MIN_NCC}, margin >= "
           f"{CAL_MIN_MARGIN}), isolated; colours BGR in 0..1; one blur per widget scale", "scales": {}}
    by_scale = defaultdict(dict)
    for (cls, skey), v in sorted(icons.items()):
        if len(v) < 8:
            print(f"  calibration {cls} {skey}: only {len(v)} icons; skipped", flush=True)
            continue
        by_scale[skey][cls] = v
    for skey, classes in sorted(by_scale.items()):
        best_s = None
        for sg in CAL_SIGMAS:
            per = {}
            for cls, v in classes.items():
                ars = CAL_ALPHA_RING if cls == "enemy" else (1.0,)
                als = CAL_ALPHA_LOBE if cls == "enemy" else (1.0,)
                for a_r in ars:
                    for a_l in als:
                        col, lo, mad = _solve([_design(ic, sg, a_r, a_l) for ic in v])
                        if cls not in per or lo < per[cls][0]:
                            per[cls] = (lo, a_r, a_l, col, mad)
            tot = float(np.mean([p[0] for p in per.values()]))
            print(f"  calibration {skey} blur {sg}: mean loss {tot:.3f}", flush=True)
            if best_s is None or tot < best_s[0]:
                best_s = (tot, sg, per)
        tot, sg, per = best_s
        cl = {}
        for cls, (lo, a_r, a_l, col, mad) in per.items():
            cl[cls] = {"alpha_ring": a_r, "alpha_lobe": a_l,
                       "colours": {k: [round(float(x), 4) for x in col[j]]
                                   for j, k in enumerate(("ring", "base", "tip", "disc"))},
                       "noise_mad": round(mad, 4), "loss": round(lo, 4), "n_icons": len(classes[cls]),
                       "sessions": sorted({ic["sid"] for ic in classes[cls]})}
            print(f"  calibration {cls} {skey}: n {len(classes[cls])} alphas {a_r}/{a_l} loss {lo:.3f} "
                  f"mad {mad:.3f} BGR ring {np.round(col[0] * 255)} base {np.round(col[1] * 255)} "
                  f"tip {np.round(col[2] * 255)} disc {np.round(col[3] * 255)}", flush=True)
        out["scales"][skey] = {"classes": cl, "sigma_blur": sg,
                               "sigma_noise": float(np.median([c["noise_mad"] for c in cl.values()]))}
    return out


def _pose_grid(x, y, half, step, degs):
    offs = np.arange(-half, half + 1e-6, step)
    gx, gy, gd = np.meshgrid(x + offs, y + offs, degs, indexing="ij")
    return np.stack([gx.ravel(), gy.ravel(), gd.ravel()], 1).astype(np.float32)


def _far(a, b) -> bool:
    return abs(float(td._signed_deg(a - b))) > 90.0


DEGS = np.arange(0.0, 360.0, GRID_DEG)


def solo(scene: Scene, i: int) -> dict:
    """Icon `i` alone over the background: its best pose and its best far-half pose."""
    ic = scene.icons[i]
    sc = scene.sc
    poses = {i: None}
    order = [i]
    cands = _pose_grid(ic["x0"], ic["y0"], round(SOLO_SEARCH_PX * sc), 1.0, DEGS)
    loss, g = scene.search(i, order, poses, cands)
    b = int(np.argmin(loss))
    cands = _pose_grid(cands[b, 0], cands[b, 1], 1.0, 0.25, DEGS)
    loss, g = scene.search(i, order, poses, cands)
    b = int(np.argmin(loss))
    far = np.array([_far(d, cands[b, 2]) for d in cands[:, 2]])
    bf = int(np.argmin(np.where(far, loss, np.inf)))
    best = _refine(scene, i, order, poses, (*cands[b], *g[b]))
    return {"best": best, "far": (*cands[bf], *g[bf]), "loss": float(loss[b]), "far_loss": float(loss[bf])}


def _refine(scene, i, order, poses, pose):
    cands = _pose_grid(pose[0], pose[1], 0.5, 0.25, pose[2] + np.arange(-4.0, 4.01, 1.0))
    loss, g = scene.search(i, order, poses, cands)
    b = int(np.argmin(loss))
    return (*map(float, cands[b]), *map(float, g[b]))


def best_order(scene, poses, n):
    best, bo = math.inf, None
    for order in itertools.permutations(range(n)):
        lo = scene.loss_of(scene.stack(list(order), poses))
        if lo < best:
            best, bo = lo, list(order)
    return bo, best


def fit_scene(scene: Scene) -> dict:
    """The joint fit of every icon in the scene; icon 0 is the labelled one."""
    n = len(scene.icons)
    solos = [solo(scene, i) for i in range(n)]
    if n == 1:
        s = solos[0]
        return {"poses": {0: s["best"]}, "order": [0], "loss": s["loss"], "solos": solos,
                "margin": s["far_loss"] - s["loss"], "starts": 1}
    best = None
    starts = 0
    for seeds in itertools.product((0, 1), repeat=n):
        poses = {i: solos[i]["best" if k == 0 else "far"] for i, k in enumerate(seeds)}
        starts += 1
        for _sweep in range(SWEEPS):
            order, _ = best_order(scene, poses, n)
            for i in range(n):
                p = poses[i]
                cands = _pose_grid(p[0], p[1], JOINT_SEARCH_PX * scene.sc, 0.5, DEGS)
                loss, g = scene.search(i, order, poses, cands)
                b = int(np.argmin(loss))
                poses[i] = (*map(float, cands[b]), *map(float, g[b]))
        order, lo = best_order(scene, poses, n)
        if best is None or lo < best["loss"]:
            best = {"poses": dict(poses), "order": order, "loss": lo}
    poses, order = best["poses"], best["order"]
    for i in range(n):
        poses[i] = _refine(scene, i, order, poses, poses[i])
    K = scene.stack(order, poses)
    best["loss"] = scene.loss_of(K)
    # The target's best pose with its lobe on the far side, the others held.
    p = poses[0]
    cands = _pose_grid(p[0], p[1], JOINT_SEARCH_PX * scene.sc, 0.5, DEGS)
    loss, _g = scene.search(0, order, poses, cands)
    far = np.array([_far(d, p[2]) for d in cands[:, 2]])
    best.update(solos=solos, margin=float(np.min(loss[far]) - best["loss"]), starts=starts)
    return best


# ---------------------------------------------------------------- the prior

class TrackIndex:
    """The stored `team_vision` frames of one session: `t_ms -> [(role, x, y)]` (positions only)."""

    def __init__(self, sid: str, wanted: list[float]):
        self.rows = {}
        p = sem.STORE / "events" / "team_vision" / f"{sid}.jsonl"
        self.version = None
        if not p.is_file():
            return
        lo = [(t - PRIOR_MS - 1.0, t + 1.0) for t in wanted]
        with p.open(encoding="utf-8") as f:
            for line in f:
                i = line.find('"t_ms":')
                if i < 0:
                    continue
                j = line.find(",", i)
                t = float(line[i + 7:j])
                if not any(a <= t <= b for a, b in lo):
                    continue
                d = json.loads(line)
                if d.get("kind") != "frame":
                    continue
                self.version = d.get("team_vision_version")
                self.rows[t] = [(ic["role"], float(ic["x"]), float(ic["y"]), ic.get("track_id"))
                                for ic in d.get("icons", []) if ic.get("x") is not None]

    def prior(self, t_ms: float):
        before = [t for t in self.rows if t < t_ms - 1.0]
        if before:
            t = max(before)
            return t, self.rows[t]
        same = [t for t in self.rows if abs(t - t_ms) <= 1.0]
        return (same[0], self.rows[same[0]]) if same else (None, [])


def neighbourhood(s, crop, row: dict, cls: str, tracks: TrackIndex | None, sc: float) -> dict:
    """The labelled icon and the icons that can touch it, each `{"cls", "x0", "y0", "source"}`."""
    tx, ty = float(row["det_cx"]), float(row["det_cy"])
    cands = []
    t_prior, prior = (tracks.prior(float(row["t_ms"])) if tracks else (None, []))
    for role, x, y, tid in prior:
        cands.append({"cls": "self" if role == "self" else "ally", "x0": x, "y0": y, "source": "track",
                      "track_id": tid})
    for c in ("self", "ally", "enemy"):
        for d in it_.detections(crop, c, s):
            near = [q for q in cands if q["cls"] == c and math.hypot(q["x0"] - d["cx"], q["y0"] - d["cy"])
                    <= SAME_PX * sc * 1.5]
            if not near:
                cands.append({"cls": c, "x0": float(d["cx"]), "y0": float(d["cy"]), "source": "detector"})
    target = {"cls": cls, "x0": tx, "y0": ty, "source": "label_set_detector"}
    # One self icon a frame: a self target has no self neighbour.
    others = [q for q in cands if not (q["cls"] == cls and (cls == "self" or
                                                            math.hypot(q["x0"] - tx, q["y0"] - ty) <= SAME_PX * sc))]
    L_t = CLASS_RADII[cls][2]
    near = []
    for q in others:
        d = math.hypot(q["x0"] - tx, q["y0"] - ty)
        q["dist"] = d
        if d <= (L_t + CLASS_RADII[q["cls"]][2] + TOUCH_PAD) * sc:
            near.append(q)
    near.sort(key=lambda q: q["dist"])
    near = near[:MAX_NEIGHBOURS]
    stacked = any(q["dist"] <= STACK_PX * sc for q in others)
    return {"icons": [target] + near, "stacked": stacked, "n_touch": len(near),
            "prior_t_ms": t_prior, "prior_n": len(prior),
            "sources": sorted({q["source"] for q in near}),
            "neighbour_classes": [q["cls"] for q in near]}


# ---------------------------------------------------------------- the label sets

def e6_rows(store):
    rows = th.e6_scored(th.e6_rows(store))
    for r in rows:
        r["set"] = "465-" + r["cls"]
    return rows


def self_rows(store):
    rows = th.self_scored(th.self_rows(store))
    for r in rows:
        r["set"] = "self-lotus" if r["session"] == lsf.LOTUS else "self-control"
    return rows


def rows_331(store):
    rows = th.scored_331(th.rows_331(store)[0])
    for r in rows:
        r["set"] = "331-ally"
    return rows


def _manifest_rows(store, name, loader, cls, centre=("det_x", "det_y")):
    idir = lif.items_dir(store, name)
    manifest = json.loads((idir / "manifest.json").read_text(encoding="utf-8"))["items"]
    answers = lif.load_answers(lif.labels_path(store, name))
    rows = loader(manifest, answers)
    by = {m["key"]: m for m in manifest}
    rows = [r for r in rows if r["answer"] == "facing" and r.get("centre_off_px", 0.0) <= ife.ELSEWHERE_331_PX]
    crops = th._crops(rows)
    for r in rows:
        m = by[r["key"]]
        r["det_cx"], r["det_cy"] = float(m[centre[0]]), float(m[centre[1]])
        r["cls"] = cls
        r["manifest_stacked"] = m.get("stacked", m.get("others"))
        r["_crop"] = crops[(r["session"], float(r["t_ms"]))]
    return rows


def s331_rows(store):
    rows = _manifest_rows(store, lif.SET_S331, ife.rows_s331, "self")
    for r in rows:
        r["set"] = "331-self"
    return rows


def e331_rows(store):
    rows = _manifest_rows(store, lif.SET_E331, ife.rows_e331, "enemy")
    for r in rows:
        r["set"] = "331-enemy"
    return rows


LOADERS = {"465": e6_rows, "self": self_rows, "331": rows_331, "s331": s331_rows, "e331": e331_rows}


# ---------------------------------------------------------------- one item

def label_centre(r):
    a = r.get("label_cx"), r.get("label_cy")
    return None if a[0] is None else a


def run_item(s, r: dict, tracks, do_fit: bool = True) -> dict:
    crop = r["_crop"]
    sc = widget_scale(crop.shape[1])
    cls = r["cls"]
    nb = neighbourhood(s, crop, r, cls, tracks, sc)
    out = {"scale": sc, "stacked": nb["stacked"], "n_touch": nb["n_touch"], "prior_n": nb["prior_n"],
           "prior_t_ms": nb["prior_t_ms"], "sources": nb["sources"], "neighbour_classes": nb["neighbour_classes"],
           "_icons": nb["icons"]}
    f = ff.fit(crop, cls, r["det_cx"], r["det_cy"], sc)
    out["teardrop"] = float(f["deg"]) if f.get("read") else None
    out["teardrop_reason"] = None if f.get("read") else f.get("reason", "no_fit")
    out["td_xy"] = (float(f["x"]), float(f["y"])) if "x" in f else None
    if not do_fit:
        return out
    t0 = time.perf_counter()
    scene = (RGBScene(crop, s, nb["icons"], sc, CAL) if SPACE == "rgb"
             else Scene(keys(crop), keys(s.inputs.static), nb["icons"], sc))
    got = fit_scene(scene)
    out["fit_s"] = time.perf_counter() - t0
    p = got["poses"][0]
    out["joint"] = float(td._signed_deg(p[2]))
    out["joint_xy"] = (p[0], p[1])
    out["joint_gains"] = (p[3], p[4])
    sp = got["solos"][0]["best"]
    out["solo"] = float(td._signed_deg(sp[2]))
    out["solo_xy"] = (sp[0], sp[1])
    out["margin"] = got["margin"]
    out["solo_margin"] = got["solos"][0]["far_loss"] - got["solos"][0]["loss"]
    out["order"] = got["order"]
    out["starts"] = got["starts"]
    out["neighbour_poses"] = [got["poses"][i] for i in range(1, len(scene.icons))]
    out["rests_on"] = [("baked static RGB (map, profile)" if SPACE == "rgb" else "baked static keys (map, profile)")] + (
        ["team_vision stored track positions"] if "track" in nb["sources"] else []) + (
        ["class detectors at this frame"] if "detector" in nb["sources"] else []) + ["label set's detector centre"]
    out["_scene"] = scene
    out["_fit"] = got
    return out


# ---------------------------------------------------------------- scoring

def err(r, name):
    if r.get(name) is None or r.get("label_deg") is None:
        return None
    return float(td._signed_deg(r[name] - r["label_deg"]))


def summarise(rows):
    out = {"n": len(rows)}
    for name in ARMS:
        e = [x for x in (err(r, name) for r in rows) if x is not None]
        out[f"{name}_n"] = len(e)
        out[f"{name}_median_abs_deg"] = round(float(np.median(np.abs(e))), 4) if e else None
        out[f"{name}_flips"] = int(sum(abs(x) > 90 for x in e))
        out[f"{name}_unread"] = sum(r.get(name) is None for r in rows)
    both = [r for r in rows if err(r, "teardrop") is not None and err(r, "joint") is not None]
    out["both_n"] = len(both)
    for name in ("solo", "joint"):
        b2 = [r for r in rows if err(r, "teardrop") is not None and err(r, name) is not None]
        out[f"{name}_fixed"] = sum(abs(err(r, "teardrop")) > 90 and abs(err(r, name)) <= 90 for r in b2)
        out[f"{name}_broken"] = sum(abs(err(r, "teardrop")) <= 90 and abs(err(r, name)) > 90 for r in b2)
        eb = [abs(err(r, name)) for r in b2]
        out[f"{name}_median_abs_deg_on_td_read"] = round(float(np.median(eb)), 4) if eb else None
    et = [abs(err(r, "teardrop")) for r in both]
    out["teardrop_median_abs_deg_on_td_read"] = round(float(np.median(et)), 4) if et else None
    js = [r for r in rows if err(r, "joint") is not None and err(r, "solo") is not None]
    out["joint_vs_solo_fixed"] = sum(abs(err(r, "solo")) > 90 and abs(err(r, "joint")) <= 90 for r in js)
    out["joint_vs_solo_broken"] = sum(abs(err(r, "solo")) <= 90 and abs(err(r, "joint")) > 90 for r in js)
    unread = [r for r in rows if r.get("teardrop") is None and err(r, "joint") is not None]
    out["joint_on_td_unread_n"] = len(unread)
    out["joint_on_td_unread_flips"] = sum(abs(err(r, "joint")) > 90 for r in unread)
    return out


def _print(title, res):
    print(f"\n== {title}: n {res['n']}")
    for name in ARMS:
        print(f"  {name:9s} n {res[f'{name}_n']:3d} unread {res[f'{name}_unread']:3d} "
              f"med {res[f'{name}_median_abs_deg'] if res[f'{name}_median_abs_deg'] is not None else '-':>7} "
              f"flips {res[f'{name}_flips']}")
    print(f"  on teardrop reads (n {res['both_n']}): med td {res['teardrop_median_abs_deg_on_td_read']} "
          f"solo {res['solo_median_abs_deg_on_td_read']} joint {res['joint_median_abs_deg_on_td_read']}; "
          f"solo fixed/broken {res['solo_fixed']}/{res['solo_broken']}, joint {res['joint_fixed']}/{res['joint_broken']}; "
          f"joint vs solo {res['joint_vs_solo_fixed']}/{res['joint_vs_solo_broken']}; "
          f"td unread: joint reads {res['joint_on_td_unread_n']} flips {res['joint_on_td_unread_flips']}")


# ---------------------------------------------------------------- the sheet

def _false(k: np.ndarray) -> np.ndarray:
    """Keys (3, h, w) as BGR: teal, yellow, red."""
    t, y, r = (np.clip(k[i], 0, 1) for i in range(3))
    img = np.stack([255 * t, 255 * np.maximum(t, y), 255 * np.maximum(y, r)], -1)
    return np.clip(img, 0, 255).astype(np.uint8)


def tile(r: dict, zoom: int = 6) -> np.ndarray:
    """Crop, rendered keys, observed keys and |residual| round the labelled icon; arrows: label green,
    teardrop blue, solo magenta, joint white; neighbours' joint facings orange."""
    crop = r["_crop"]
    sc = r["scale"]
    half = int(round((td.L + 8) * sc))
    cx, cy = r["det_cx"], r["det_cy"]
    ix, iy = int(round(cx)), int(round(cy))
    x0, y0 = ix - half, iy - half

    def sub(img):
        pad = cv2.copyMakeBorder(img, half, half, half, half, cv2.BORDER_CONSTANT)
        return pad[iy:iy + 2 * half + 1, ix:ix + 2 * half + 1]
    panels = [sub(crop)]
    scene, got = r.get("_scene"), r.get("_fit")
    if isinstance(scene, RGBScene):
        P, R, Wimg = scene.full_images(got["order"], got["poses"], crop.shape[:2])
        keep = np.zeros(crop.shape[:2], bool)
        x0w, y0w, x1w, y1w = scene.win
        keep[y0w:y1w, x0w:x1w] = scene.keep_np
        owned = keep & (Wimg < 0.5)
        Pv = P.copy()
        Pv[owned] = (0.5 * Pv[owned] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)   # owned portrait: magenta
        rimg = cv2.applyColorMap(np.clip(R / TAU_SIG * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        rimg[~keep] = 0
        panels += [sub(Pv), sub(rimg)]
    elif scene is not None:
        K = scene.stack(got["order"], got["poses"]).cpu().numpy()
        h, w = crop.shape[:2]
        full = np.zeros((3, h, w), np.float32)
        full[:, scene.mask] = K
        obs = np.zeros((3, h, w), np.float32)
        obs[:, scene.mask] = scene.obs.cpu().numpy()
        res = np.abs(obs - full).sum(0)
        rimg = np.clip(res / (3 * TAU) * 255, 0, 255).astype(np.uint8)
        rimg = cv2.applyColorMap(rimg, cv2.COLORMAP_INFERNO)
        rimg[~scene.mask] = 0
        panels += [sub(_false(full)), sub(_false(obs)), sub(rimg)]
    big = [cv2.resize(p, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST) for p in panels]

    def to(x, y):
        return int((x - x0 + 0.5) * zoom), int((y - y0 + 0.5) * zoom)
    ln = half * zoom * 0.75
    arrows = [("label_deg", (0, 255, 0), 3, (cx, cy)), ("teardrop", (255, 128, 0), 2, r.get("td_xy") or (cx, cy)),
              ("solo", (255, 0, 255), 1, r.get("solo_xy") or (cx, cy)), ("joint", (255, 255, 255), 2,
                                                                          r.get("joint_xy") or (cx, cy))]
    for k, b in enumerate(big):
        for name, col, wd, (ox, oy) in arrows:
            deg = r.get(name)
            if deg is None:
                continue
            a = math.radians(deg)
            o = to(ox, oy)
            cv2.arrowedLine(b, o, (int(o[0] + ln * math.cos(a)), int(o[1] + ln * math.sin(a))), col, wd,
                            tipLength=0.1)
        for p in r.get("neighbour_poses", []):
            a = math.radians(p[2])
            o = to(p[0], p[1])
            cv2.arrowedLine(b, o, (int(o[0] + 0.5 * ln * math.cos(a)), int(o[1] + 0.5 * ln * math.sin(a))),
                            (0, 140, 255), 1, tipLength=0.15)
    row = np.hstack([np.pad(b, ((0, 0), (0, 3), (0, 0))) for b in big])
    et, es, ej = err(r, "teardrop"), err(r, "solo"), err(r, "joint")
    f = lambda e: "-" if e is None else f"{e:+.0f}"  # noqa: E731
    lines = [f"{r['set']} {r['session'][:4]} {r['t_ms'] / 1000:.1f}s {'STACK' if r.get('stacked') else ''} "
             f"touch {r.get('n_touch')} {','.join(r.get('neighbour_classes', []))} order {r.get('order')}",
             f"err td {f(et)} solo {f(es)} joint {f(ej)}  margin {r.get('margin', 0):.2f}"]
    bar = np.zeros((40, row.shape[1], 3), np.uint8)
    for k, s_ in enumerate(lines):
        bad = ej is not None and abs(ej) > 90
        cv2.putText(bar, s_, (4, 15 + 17 * k), 0, 0.45, (0, 0, 255) if (bad and k == 1) else (255, 255, 255), 1)
    return np.vstack([bar, row])


def sheet(rows, path: Path, per_page: int = 12) -> list[Path]:
    tiles = [tile(r) for r in rows]
    if not tiles:
        return []
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 4, 0, W - t.shape[1], cv2.BORDER_CONSTANT, value=(40, 40, 40)) for t in tiles]
    paths = []
    for k in range(0, len(tiles), per_page):
        p = path.with_name(f"{path.stem}_{k // per_page}{path.suffix}")
        p.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(p), np.vstack(tiles[k:k + per_page]))
        paths.append(p)
    return paths


# ---------------------------------------------------------------- the renderer alone, at the labelled pose

LABEL_FILES = {"465": lambda st: lif.labels_path(st), "self": lambda st: lsf.labels_path(st),
               "331": lambda st: lif.labels_path(st, lif.SET_331), "s331": lambda st: lif.labels_path(st, lif.SET_S331),
               "e331": lambda st: lif.labels_path(st, lif.SET_E331)}
CHECK_VARIANTS = ("rgb-mask", "rgb-disc", "keys")
CHECK_CENTRE_PX = 1.0     # scale 1.0: the centre is re-optimised this far round the player's click at each facing


def attach_clicks(k: str, rows: list[dict], store) -> None:
    ans = lsf.load_answers(LABEL_FILES[k](store))
    for r in rows:
        a = ans.get(r["key"], {})
        r["click"] = (float(a["centre_x"]), float(a["centre_y"])) if a.get("centre_x") is not None else None


def check_item(s, r: dict, variant: str) -> dict:
    """The labelled icon alone: loss at the labelled facing against the reversed one (centre re-optimised
    within `CHECK_CENTRE_PX` of the click at each), and the renderer's own best pose over the solo search."""
    global PORTRAIT
    crop = r["_crop"]
    sc = widget_scale(crop.shape[1])
    icons = [{"cls": r["cls"], "x0": float(r["det_cx"]), "y0": float(r["det_cy"])}]
    if variant == "keys":
        scene = Scene(keys(crop), keys(s.inputs.static), icons, sc)
    else:
        PORTRAIT = "mask" if variant == "rgb-mask" else "disc"
        scene = RGBScene(crop, s, icons, sc, CAL)
    cx, cy = r["click"] or (r["det_cx"], r["det_cy"])
    out = {}
    for name, deg in (("lab", r["label_deg"]), ("rev", r["label_deg"] + 180.0)):
        cands = _pose_grid(cx, cy, CHECK_CENTRE_PX * sc, 0.25, np.array([deg], np.float32))
        loss, _ = scene.search(0, [0], {0: None}, cands)
        out[name] = float(loss.min())
    sol = solo(scene, 0)
    out["global_err"] = float(td._signed_deg(sol["best"][2] - r["label_deg"]))
    PORTRAIT = "mask"
    return out


def check(all_rows: dict, sess, store) -> dict:
    res = {}
    for k, rows in all_rows.items():
        attach_clicks(k, rows, store)
        for r in rows:
            r["check"] = {v: check_item(sess(r["session"]), r, v) for v in CHECK_VARIANTS}
    for k, rows in all_rows.items():
        for name in sorted({r["set"] for r in rows}):
            sub = [r for r in rows if r["set"] == name]
            vals = {}
            for part, pick in (("all", sub), ("stacked", [r for r in sub if r["stacked"]]),
                               ("isolated", [r for r in sub if not r["n_touch"]])):
                vals[f"{part}_n"] = len(pick)
                tdr = [r for r in pick if err(r, "teardrop") is not None]
                vals[f"{part}_teardrop_flips"] = sum(abs(err(r, "teardrop")) > 90 for r in tdr)
                for v in CHECK_VARIANTS:
                    tag = v.replace("-", "_")
                    vals[f"{part}_{tag}_lab_beats_rev"] = sum(r["check"][v]["lab"] < r["check"][v]["rev"] for r in pick)
                    vals[f"{part}_{tag}_global_flips"] = sum(abs(r["check"][v]["global_err"]) > 90 for r in pick)
            res[name] = ("+".join(sorted({r["session"] for r in sub})), vals)
            print(f"\n== check {name}: n {vals['all_n']} (stacked {vals['stacked_n']}, isolated {vals['isolated_n']}),"
                  f" teardrop flips {vals['all_teardrop_flips']}")
            for v in CHECK_VARIANTS:
                tag = v.replace("-", "_")
                print(f"  {v:9s} label beats reversed {vals[f'all_{tag}_lab_beats_rev']}/{vals['all_n']} "
                      f"(stacked {vals[f'stacked_{tag}_lab_beats_rev']}/{vals['stacked_n']}, isolated "
                      f"{vals[f'isolated_{tag}_lab_beats_rev']}/{vals['isolated_n']}); global flips "
                      f"{vals[f'all_{tag}_global_flips']}")
    return res


# ---------------------------------------------------------------- main

CAL: dict = {}


def _idle():
    th._idle()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sets", default="465,self,331,s331,e331")
    ap.add_argument("--census", action="store_true", help="count stacked labelled items; fit nothing")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N items per set (a smoke run; never recorded)")
    ap.add_argument("--parts", default="", help="fit only these set names (those whose renderer check passed)")
    ap.add_argument("--shared-gain", action="store_true",
                    help="0.1.0 post hoc: one gain per silhouette (with --space keys)")
    ap.add_argument("--space", choices=("rgb", "keys"), default="rgb",
                    help="rgb: 0.2.0's renderer; keys: 0.1.0's, the control")
    ap.add_argument("--check", action="store_true",
                    help="the renderer alone at the labelled pose against the reversed one; fit nothing")
    ap.add_argument("--recalibrate", action="store_true", help="refit the RGB calibration on unlabelled frames")
    args = ap.parse_args(argv)
    global GAIN_MODE, OUT, SPACE, CAL
    SPACE = args.space
    posthoc = ""
    if args.shared_gain:
        GAIN_MODE, posthoc = "shared", "-posthoc-shared"
        OUT = OUT / "posthoc-shared"
    if SPACE == "keys" and not args.check:
        posthoc += "-keys"
        OUT = OUT / "keys"
    _idle()
    store = sem.STORE
    sess = ff._sessions()
    all_rows = {}
    for k in args.sets.split(","):
        rows = LOADERS[k](store)
        if args.limit:
            rows = rows[:args.limit]
        all_rows[k] = rows
        print(f"{k}: {len(rows)} scored labelled items", flush=True)
    need = defaultdict(list)
    for rows in all_rows.values():
        for r in rows:
            need[r["session"]].append(float(r["t_ms"]))
    if args.parts:
        # Fit only the sets whose renderer check passed; `need` above still spans every loaded set.
        keep = set(args.parts.split(","))
        all_rows = {k: [r for r in rows if r["set"] in keep] for k, rows in all_rows.items()}
        all_rows = {k: v for k, v in all_rows.items() if v}
    cal_path = sem.STORE / "analysis" / "scene-stack-v2-20260929" / "calibration.json"
    if args.recalibrate or not cal_path.is_file():
        if args.sets != ap.get_default("sets") or args.limit:
            raise SystemExit("calibrate with every label set loaded, so every labelled instant is excluded")
        print("calibrating on unlabelled frames", flush=True)
        CAL = calibrate(sess, {sid: ts for sid, ts in need.items()})
        cal_path.parent.mkdir(parents=True, exist_ok=True)
        cal_path.write_text(json.dumps(CAL, indent=1), encoding="utf-8")
        print("wrote", cal_path)
    CAL = json.loads(cal_path.read_text(encoding="utf-8"))
    tracks = {sid: TrackIndex(sid, ts) for sid, ts in need.items()}
    for sid, tr in tracks.items():
        print(f"  prior {sid}: {len(tr.rows)} stored frames ({tr.version})", flush=True)
    t0 = time.perf_counter()
    for k, rows in all_rows.items():
        for i, r in enumerate(rows):
            got = run_item(sess(r["session"]), r, tracks.get(r["session"]), do_fit=not (args.census or args.check))
            r.update(got)
            if (i + 1) % 10 == 0:
                print(f"  {k} {i + 1}/{len(rows)} {time.perf_counter() - t0:.0f}s", flush=True)
    if args.check:
        from reticle import metrics
        res = check(all_rows, sess, store)
        if args.record and not args.limit:
            deps = {"prototype": VERSION, "calibration": str(cal_path), "check_centre_px": CHECK_CENTRE_PX,
                    "variants": list(CHECK_VARIANTS), "tau_sig": TAU_SIG, "own_cost": OWN_COST}
            for name, (session, vals) in res.items():
                metrics.record(CHECK_SERIES, part=name, session=session, values=vals, deps=deps)
                print("recorded check", name)
        return 0
    if args.census:
        for k, rows in all_rows.items():
            st = [r for r in rows if r["stacked"]]
            tch = [r for r in rows if r["n_touch"]]
            print(f"{k}: {len(rows)} items, stacked {len(st)}, touching {len(tch)}, "
                  f"teardrop unread {sum(r['teardrop'] is None for r in rows)}, stacked+unread "
                  f"{sum(r['teardrop'] is None for r in st)}; neighbour classes "
                  f"{dict((c, sum(c in r['neighbour_classes'] for r in tch)) for c in ('self', 'ally', 'enemy'))}; "
                  f"manifest stacked {sum(bool(r.get('manifest_stacked')) for r in rows)}")
        return 0

    from reticle import metrics
    deps = {"prototype": VERSION, "teardrop": td.ICON_TEARDROP_VERSION, "grid_deg": GRID_DEG, "tau": TAU,
            "gain": list(GAIN), "enemy_lobe_alpha": ENEMY_LOBE_ALPHA, "solo_search_px": SOLO_SEARCH_PX,
            "joint_search_px": JOINT_SEARCH_PX, "sweeps": SWEEPS, "touch_pad": TOUCH_PAD, "stack_px": STACK_PX,
            "max_neighbours": MAX_NEIGHBOURS, "gain_mode": GAIN_MODE, "prior": "team_vision stored tracks + class detectors",
            "space": SPACE, "portrait": PORTRAIT, "tau_sig": TAU_SIG, "own_cost": OWN_COST,
            "calibration": str(cal_path)}
    records = []
    pooled = defaultdict(list)
    for k, rows in all_rows.items():
        for name in sorted({r["set"] for r in rows}):
            sub = [r for r in rows if r["set"] == name]
            vals = {}
            for part, pick in (("all", sub), ("stacked", [r for r in sub if r["stacked"]]),
                               ("touching", [r for r in sub if r["n_touch"]]),
                               ("isolated", [r for r in sub if not r["n_touch"]])):
                res = summarise(pick)
                _print(f"{name} {part}", res)
                vals |= {f"{part}_{kk}": v for kk, v in res.items()}
                pooled[part] += pick
            vals["fit_s_median"] = round(float(np.median([r["fit_s"] for r in sub])), 3)
            records.append((name, "+".join(sorted({r["session"] for r in sub})), vals))
    vals = {}
    for part, pick in pooled.items():
        res = summarise(pick)
        _print(f"POOLED {part}", res)
        vals |= {f"{part}_{kk}": v for kk, v in res.items()}
    records.append(("pooled", "+".join(sorted(need)), vals))
    if args.record and not args.limit:
        for part, session, v in records:
            metrics.record(SERIES, part=part + posthoc, session=session, values=v, deps=deps)
            print("recorded", part)
    OUT.mkdir(parents=True, exist_ok=True)
    clean = {k: [{kk: vv for kk, vv in r.items() if not kk.startswith("_")} for r in v] for k, v in all_rows.items()}
    (OUT / "items.json").write_text(json.dumps({"version": VERSION, "deps": deps, "sets": clean}, indent=1,
                                               default=str), encoding="utf-8")
    print("wrote", OUT / "items.json")
    if args.sheet:
        for k, rows in all_rows.items():
            pick = [r for r in rows if r["n_touch"]] + [r for r in rows if not r["n_touch"] and (
                (err(r, "joint") is not None and abs(err(r, "joint")) > 90)
                or (err(r, "teardrop") is not None and abs(err(r, "teardrop")) > 90))]
            for p in sheet(pick, OUT / f"sheet_{k}.png"):
                print("wrote", p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
