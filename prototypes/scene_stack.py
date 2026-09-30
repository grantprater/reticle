r"""Touching minimap icons fitted jointly: render every icon of a stack, composite, compare.

    .\.venv\Scripts\python.exe prototypes\scene_stack.py --census
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --light-cal [--record]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --check [--record] [--sheet] [--recalibrate]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py [--record] [--sheet] [--parts 465-ally,...] [--space keys]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --no-sources [--record]    # the 0.3.0 control
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --disc              # the 0.4.0 control, unrecorded
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --tint-cal [--record]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --fit-agree [--record]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --v5                # 0.5.0 exactly, unrecorded
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --only cast|regions|boxes [--record]
    .\.venv\Scripts\python.exe prototypes\scene_stack.py --compare [--record]

**0.6.0 casts the light as a binary raycast (`CHANGES`).** The light
diagnosis (`light_diagnosis.py`) split 0.5.0's unexplained light into
per-pixel read noise, light inside teammates' cones the scene did not cast,
and light past occluders, boxes most of all. The player's model is a
raycast with no reflections, binary, uniform and unlimited in range
[domain:minimap/vision-light-binary]. Four additive changes, each switchable,
so `--v5` reproduces 0.5.0 and `--only` runs one alone:

- **cast** (`team_casters`): every teammate the stored team_vision frame
  places at the instant casts, at full range. A scene icon casts from the
  joint fit; a visible outside icon from its teardrop; a hidden one (tracked,
  no icon read there) from the teardrop of its last visible isolated read
  within `CAST_BACK_MS` in the crop cache, declared as `depends_on`; the
  stored track facing is the last resort. Each caster's source is stored per
  item (`casters`). An enemy casts nothing.
- **regions** (`Light.region_err`): the compared floor splits into regions
  bounded by the cone edges and the baked walls (4-connected, one predicted
  state), and each region takes one state from a binomial likelihood with
  the instrument's per-pixel read rates (`INSTRUMENT_PATH`) and the cone
  prediction as the prior. No morphology.
- **boxes**: a caster whose cone crosses a baked box is standing (every box
  blocks) or jumping (every crossed box passes, at `BOX_JUMP_COST`), one
  state per caster [domain:minimap/boxes-block-unless-raised]. The winning
  state is stored per caster; per box, the item records whether the light
  past it reads lit, which is what a box's unknown height class must explain.
- **dark** (`minimap_darkened`): a frame whose known floor sits
  `DARK_MEDIAN` below the baked static is refused, reason
  `minimap-darkened`; the teardrop still reads, the fit is not scored.

`--record` writes `scene_stack_eval_v6` (`--only X`: `scene_stack_eval_v6_only_X`),
`--compare` `scene_stack_compare_v6` over the items every arm reads; outputs go
to the store's `analysis/scene-raycast-20260930/`. The colour, tint and light
calibrations are 0.5.0's, read from `analysis/scene-tint-20260930/`.

**0.5.0 renders the sources as tints (`SOURCE_STATE = "tint"`).** 0.4.0 freed
the floor inside each drawn disc, which removed that floor from the
comparison instead of explaining it. Here a drawn source's pixels are
predicted `(1 - a) bg + a W` over either floor state (`tint_maps`), with the
radial opacity profile `a(dr)` and the tint colour `W` measured by
`--tint-cal` on unlabelled frames where the circle turns on or off in place
(the off frame shows the floor under it). The cones still predict the floor's
state inside the circle. The fits change too:

- the self audio circle is audio_circle's per-frame fit (`frame_fit`,
  `audio_fit`), not 0.4.0's thin wrapper `_ring_fit` (`--fit-agree` compares
  them on a probe set), and it counts only centred within
  `AUDIO_CENTRE_TOL_PX` of the stored self, since the circle follows the self
  icon [domain:minimap/self-audio-circle], and at the session's footstep or
  reload size (`session_sizes`, measured by `--tint-cal`, because the drawn
  size follows the map scaling [domain:capture/minimap-size-settings]);
- a dead ally Clove's circle is sought round the death point
  (`clove_death_points`: the stored death data gives the time, the stored ally
  track ending then gives the place), not over the whole widget; the free
  search stays as the flagged surprise path when no track ends there.

`--record` writes `scene_stack_eval_v5`, `--tint-cal` `scene_stack_tint_cal_v5`,
`--fit-agree` `scene_stack_fit_agree_v5`, `--light-cal` `scene_stack_light_cal_v5`;
outputs go to the store's `analysis/scene-tint-20260930/`, with
`sheet_tint_331_*.png` the 331 px items with a source, a dead ally Clove or
e37fdeca944f 1795.08 s. `_idle` now sets and checks Below Normal priority.

**0.4.0 draws the non-cone light sources (`find_sources`).** Each is a
circle fitted on the frame's own static-subtracted grey (audio_circle's
`Session.diff`, the baked static as background). Its disc explains the floor
inside it: either floor state costs nothing there (`SOURCE_STATE = "free"`),
so cone light carries evidence only on floor no other source explains. The
first design predicted the disc lit; the instrument check refuted it before
any labelled score (the disc tints either state white).

- the self audio circle [domain:minimap/self-audio-circle]: fitted round the
  stored self position (`AUDIO_REACH_PX`), radius per frame, no constant
  (the player saw it vary); a fit counts only when its ring clears
  audio_circle's cuts, the exact fit (`clove_circle.fit_circle`) is good and
  the rim is white (`AUDIO_WHITE_MIN`). `_ring_fit` is a thin wrapper to
  reconcile with audio_circle's own per-frame fit, which another branch adds;
- a dead Clove's smoke-range circle
  [domain:abilities/clove-dead-smoke-range-circle]: sought only while the
  stored death data (`death_identity`, named by the identity arbiter) holds
  an ally Clove dead in the round, anywhere in the widget, never the audio
  circle;
- the ability areas the player named (Chamber's Trademark, Veto's
  Chokehold, Deadlock's Sonic Sensor): only round a stored observation (the
  player's label of the icon within `ABILITY_WINDOW_MS`), never by analogy
  [domain:abilities/ability-rules-are-unique].

`light_stats` reports the unexplained light with and without the sources;
`--light-cal` remeasures the costs with them and the floor-colour error of
the two-state background on unlabelled frames. `--record` writes
`scene_stack_eval_v4` (`--no-sources`: `scene_stack_eval_v3_allsets`),
`--light-cal` `scene_stack_light_cal_v4`, `--check` `scene_stack_check_v4`;
`--sheet` writes the store's `analysis/scene-sources-20260930/`, with
`sheet_sources_331.png` showing the drawn sources over the 331 px crops.

**0.3.0 lights the floor from the pose (`Light`, `LIGHT = "pose"`).** 0.2.0
chose the lit or unlit floor state per pixel, so any lobe could explain the
drawn light and a wrong lobe cost nothing. Here a known-floor pixel is
predicted lit iff a team icon's cone reaches it: the owner's raycast
(`cone.raycast`, [owns:viewcone]) from the icon's centre
[domain:minimap/cone-origin-near-centre] with its half-angle, its origin snap
and `team_vision.load_inputs`' `passable` and `floor` (walls and boxes from
the baked `(map, profile)` geometry). A scene icon casts from the pose being
fitted, so pose and light are one hypothesis; a team icon of the frame
outside the scene (`facing_fusion.team_icons`) casts from its teardrop pose,
held; an enemy casts nothing [domain:minimap/vision-gate]. Light no visible
icon casts (a dead ally's vision, abilities, a spectated view) is the explicit
UNEXPLAINED-LIGHT term: the lit state where no cone reaches costs `c_u`, the
unlit state inside a cone (a smoke, a box the raycast misses) costs `c_m`,
each `2 ln((1-q)/q)` of the disagreement rate `q` measured at confident
owner teardrop poses on unlabelled frames (`--light-cal`, the store's
`analysis/scene-light-20260929/light_calibration.json`). Pixels nearer a team
icon with no pose (an unread outside icon, a scene neighbour not yet posed
in the solo search) than to any posed icon choose freely, as E12's fusion
excluded unattributable light. For speed each candidate origin is cast once
over 360 degrees and cut to each facing's wedge; `--light-cal` measures that
cut against the owner's own cast. The sprites, colours and noise are
0.2.0's, from 0.2.0's calibration file.

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
reference's known floor the lit state is its colour scaled to `hi_gray`; in
0.2.0 (`LIGHT = "free"`) the cheaper state wins per pixel, so the drawn light
is marginalised, not used; 0.3.0 predicts it from the poses (above).
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
decode, no store stream writes. 0.3.0's `--record` wrote `metrics` series
`scene_stack_eval_v3` (0.1.0 wrote `scene_stack_eval`, 0.2.0
`scene_stack_eval_v2`), with `--check` `scene_stack_check_v3` (0.2.0:
`scene_stack_check`), with `--light-cal` `scene_stack_light_cal`; `--sheet`
writes the store's `analysis/scene-light-20260929/`. Not wired: nothing in
`reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "4"          # at most four threads (the machine's rule while no user job runs)

import argparse  # noqa: E402
import itertools  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
import warnings  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402
import audio_circle as ac  # noqa: E402
import clove_circle as cc  # noqa: E402
import cone_origin as co  # noqa: E402
import facing_fusion as ff  # noqa: E402
import icon_facing_eval as ife  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import label_icon_facing as lif  # noqa: E402
import label_self_facing as lsf  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import tip_highlight as th  # noqa: E402
from reticle import cone  # noqa: E402
from reticle import lighting  # noqa: E402
from reticle import teardrop as td  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "scene-stack-0.6.0"
OUT = sem.STORE / "analysis" / "scene-raycast-20260930"
#: 0.5.0's outputs: its tint and light calibrations, which 0.6.0 reads unchanged, and its items.
OUT_V5 = sem.STORE / "analysis" / "scene-tint-20260930"
#: 0.4.0's outputs, read by `--disc` (the 0.4.0 control) and by the 0.5.0 sheet's pick rule.
OUT_V4 = sem.STORE / "analysis" / "scene-sources-20260930"
#: 0.2.0's colour calibration: 0.3.0 to 0.6.0 change only the floor's light, so their sprites are 0.2.0's.
CAL_PATH = sem.STORE / "analysis" / "scene-stack-v2-20260929" / "calibration.json"
#: 0.5.0's light costs, measured with the tinted sources (0.6.0 reads them unchanged); `--disc` reads
#: 0.4.0's, `--no-sources` 0.3.0's.
LIGHT_CAL_PATH = OUT_V5 / "light_calibration.json"
LIGHT_CAL_PATH_V4 = OUT_V4 / "light_calibration.json"
LIGHT_CAL_PATH_V3 = sem.STORE / "analysis" / "scene-light-20260929" / "light_calibration.json"
#: "rgb" (the default) predicts the crop's RGB; "keys" is 0.1.0's class-key renderer, kept as the control.
SPACE = "rgb"
#: Each version records its own series so no earlier run's cited values move. The 0.3.0 control rerun
#: on every set (`--no-sources`) records `scene_stack_eval_v3_allsets`, never `scene_stack_eval_v3`.
SERIES = "scene_stack_eval_v6"
CHECK_SERIES = "scene_stack_check_v5"
LIGHT_CAL_SERIES = "scene_stack_light_cal_v5"
TINT_CAL_SERIES = "scene_stack_tint_cal_v5"
FIT_AGREE_SERIES = "scene_stack_fit_agree_v5"
COMPARE_SERIES = "scene_stack_compare_v6"

#: 0.6.0's changes, each additive, so an empty set is 0.5.0 (`--v5`) and one change alone is an
#: ablation (`--only cast|regions|boxes`):
#: - "cast": every teammate the stored team_vision tracks place at the instant casts, at full range,
#:   an icon hidden under another included (`team_casters`);
#: - "regions": the compared floor's state is decided per region, bounded by the cone edges and the
#:   baked walls, by a binomial likelihood with the instrument's per-pixel error rates (`region_err`);
#: - "boxes": each team caster whose cone crosses a baked box keeps two states, standing (every box
#:   blocks, the default) and jumping (every crossed box passes) at `BOX_JUMP_COST`, one state per
#:   caster per frame, never a pass per box (`Light.cones(jump=True)`);
#: - "dark": a frame whose whole minimap is darkened against the baked static is refused with the
#:   reason `minimap-darkened` (`minimap_darkened`). A refusal, not a model change, so every 0.6.0
#:   variant keeps it.
CHANGES_ALL = ("cast", "regions", "boxes", "dark")
CHANGES: set = set(CHANGES_ALL)
#: The per-pixel read rates of the instrument (light-diagnosis-0.1.0): the rule `e2[1] + c_u < e2[0]`
#: reads lit on this share of truly lit and of truly unlit pixels, per widget scale.
INSTRUMENT_PATH = sem.STORE / "analysis" / "light-diagnosis-20260930" / "instrument.json"
#: A caster's jumping state costs this much (chi-square units, -2 ln prior odds): a stated belief that
#: a caster is in the air on about one frame in ten, 2 ln 9. Unmeasured and never tuned on labels.
BOX_JUMP_COST = 2.0 * math.log(0.9 / 0.1)
#: A hidden teammate keeps the teardrop facing of its last visible, isolated read this far back.
CAST_BACK_MS = 2000.0
#: A stored team_vision frame this near the instant places the teammates.
CAST_FRAME_MS = 70.0
#: The whole minimap is darkened (an enemy Reyna's blind [domain:abilities/reyna-leer-darkens-minimap])
#: when the median grey of the known floor sits this far below the baked static. Normal frames sit at
#: 0 +/- 2; c40d950031bb's blinded frames at -104. Set from those two readings, before any rescore.
DARK_MEDIAN = -40.0
#: Row-and-column passes of the region labelling; a region still split after these stays split (a finer
#: partition, never a merged one).
REGION_PASSES = 64

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


# ---------------------------------------------------------------- the team light (0.3.0)

#: "pose" (0.3.0): a known-floor pixel is predicted lit iff a team icon's cone reaches it, the other
#: state at a calibrated cost; "free" (0.2.0): the cheaper state per pixel, the light marginalised.
LIGHT = "pose"
LIGHT_RAYS = 1440          # the 360-degree visibility cast: 0.25 degrees a ray (the owner casts 240 over 103)
LIGHT_FIRE_PX = 5          # compared pixels: an item's unexplained (or missing) light fires at this many
LIGHT_COST_MAX = TAU_SIG ** 2   # a cost this large forbids the other state: the coupling made hard


class Light:
    """The team's drawn light over one scene window, predicted from poses.

    `cones(cands)` is the light each candidate pose `(x, y, deg)` casts, (N, P)
    bool on the window's pixels; `held(poses, skip)` is the light and the
    free (unattributable) pixels with every posed team icon but `skip`.
    `outside` are the frame's team icons the scene does not fit
    (`{"x", "y", "deg"|None}`, teardrop poses): a posed one casts, held; an
    unposed one frees the pixels nearer it than any scene icon.
    """

    def __init__(self, s, win, scene_icons: list[dict], outside: list[dict], sc: float, costs: dict,
                 src: np.ndarray | None = None):
        self.s, self.sc, self.win = s, sc, win
        x0, y0, x1, y1 = win
        yy, xx = np.mgrid[y0:y1, x0:x1]
        self.xx, self.yy = xx.ravel().astype(np.float32), yy.ravel().astype(np.float32)
        self.px = torch.tensor(self.xx, device=DEV)
        self.py = torch.tensor(self.yy, device=DEV)
        self.max_r = int(math.ceil(math.hypot(x1 - x0, y1 - y0))) + 2
        self.known_np = s.ref.known[y0:y1, x0:x1].ravel().astype(bool)
        self.known = torch.tensor(self.known_np, device=DEV)
        self.c_u, self.c_m = float(costs["c_u"]), float(costs["c_m"])
        self._v, self._pc = {}, {}
        self.team = [ic["cls"] != "enemy" for ic in scene_icons]
        self.dist = np.stack([np.hypot(self.xx - ic["x0"], self.yy - ic["y0"]) for ic in scene_icons])
        d_scene = self.dist.min(0)
        self.out = torch.zeros(len(self.xx), dtype=torch.bool, device=DEV)
        self.free_out = np.zeros(len(self.xx), bool)
        self.n_outside_cast = self.n_outside_free = 0
        self.H, self.W = y1 - y0, x1 - x0
        self.boxes = "boxes" in CHANGES
        self.regions = "regions" in CHANGES
        self._bey = {}
        # 0.6.0 "boxes": outside casters start standing; `decide_outside_jumps` may flip them after the fit.
        self.outside = [dict(o) for o in outside]
        self.out_jump = np.zeros(len(self.outside), bool)
        for o in self.outside:
            if o.get("deg") is None:
                self.free_out |= np.hypot(self.xx - o["x"], self.yy - o["y"]) < d_scene
                self.n_outside_free += 1
            else:
                o["_cone"] = self.cones(np.array([[o["x"], o["y"], o["deg"]]], np.float32),
                                        full=bool(o.get("full")))[0]
                self.out |= o["_cone"]
                self.n_outside_cast += 1
        if self.regions:
            self.rates = instrument_rates(sc)
        # 0.4.0: floor inside a drawn non-cone source is explained by it, so a cone carries evidence
        # only on floor no other source explains. SOURCE_STATE says how: "free" (either floor state at
        # no cost) or "lit" (predicted lit whatever the cones do).
        self.src = torch.zeros(len(self.xx), dtype=torch.bool, device=DEV)
        self.src_np = np.zeros(len(self.xx), bool)
        self.out_cones = self.out.clone()
        if src is not None:
            self.src_np = src[y0:y1, x0:x1].ravel().astype(bool)
            self.src = torch.tensor(self.src_np, device=DEV)
            if SOURCE_STATE == "lit":
                self.out |= self.src

    def _vis(self, ox: float, oy: float, full: bool = False):
        """Pixels of the window a ray from the (snapped) origin reaches in any direction: the owner's cast.
        `full` (0.6.0 "cast"): unlimited range, for a caster outside the window; else the window's diagonal."""
        key = (round(ox, 3), round(oy, 3)) if not full else (round(ox, 3), round(oy, 3), "full")
        v = self._v.get(key)
        if v is None:
            x0, y0, x1, y1 = self.win
            m = cone.raycast(self.s.passable, ox, oy, 0.0, half_angle_deg=180.0, visible=self.s.floor,
                             n_rays=LIGHT_RAYS, max_r=None if full else self.max_r, snap_px=0)
            v = torch.tensor(m[y0:y1, x0:x1].ravel(), device=DEV)
            self._v[key] = v
        return v

    def _beyond(self, ox: float, oy: float, full: bool = False):
        """0.6.0 "boxes": `(union, {box_id: mask})`, (P,) bool on the window, the pixels the 360-degree
        cast from the (snapped) origin reaches only through a box (`cone.box_crossings` over the walls
        with the boxes open). A box under the origin is not crossed."""
        key = (round(ox, 3), round(oy, 3), full)
        got = self._bey.get(key)
        if got is None:
            x0, y0, x1, y1 = self.win
            inp = self.s.inputs
            _b, bey = cone.box_crossings(inp.open_boxes, inp.box_id, ox, oy, 0.0, half_angle_deg=180.0,
                                         visible=self.s.floor, n_rays=LIGHT_RAYS,
                                         max_r=None if full else self.max_r, snap_px=0)
            per = {}
            for b, m in bey.items():
                w = m[y0:y1, x0:x1].ravel()
                if w.any():
                    per[int(b)] = torch.tensor(w, device=DEV)
            u = torch.zeros(len(self.xx), dtype=torch.bool, device=DEV)
            for m in per.values():
                u |= m
            got = (u, per)
            self._bey[key] = got
        return got

    def cones(self, cands: np.ndarray, full: bool = False, jump: bool = False, _meta: dict | None = None):
        """(N, P) bool: the cone each `(x, y, deg)` row casts over the window. `full`: unlimited range;
        `jump` (0.6.0 "boxes"): the caster is jumping, so the rays go on through every box they cross.
        `_meta`, when given, receives the snapped origin key of each row (`vid`, `keys`)."""
        cands = np.asarray(cands, np.float64)
        N = len(cands)
        ox, oy = cands[:, 0].copy(), cands[:, 1].copy()
        ok = np.ones(N, bool)
        vid = np.zeros(N, np.int64)
        keys: dict = {}
        pas = self.s.passable
        h, w = pas.shape
        uniq, inv = np.unique(cands[:, :2], axis=0, return_inverse=True)
        inv = np.asarray(inv).ravel()
        for u, (x, y) in enumerate(uniq):
            rows = np.nonzero(inv == u)[0]
            xi, yi = int(round(x)), int(round(y))
            if 0 <= xi < w and 0 <= yi < h and pas[yi, xi]:
                snaps = {(float(x), float(y)): rows}      # `cone.snap_origin` keeps a passable origin
            else:
                snaps = defaultdict(list)
                for r in rows:
                    sn = cone.snap_origin(pas, float(x), float(y), float(cands[r, 2]))
                    if sn is None:
                        ok[r] = False
                    else:
                        snaps[sn].append(r)
            for (sx, sy), rr in snaps.items():
                rr = np.asarray(rr)
                ox[rr], oy[rr] = sx, sy
                vid[rr] = keys.setdefault((sx, sy), len(keys))
        if _meta is not None:
            _meta.update(vid=vid, keys=list(keys), ok=ok)
        if not keys:
            return torch.zeros(N, len(self.xx), dtype=torch.bool, device=DEV)
        if jump:
            V = torch.stack([self._vis(*k, full=full) | self._beyond(*k, full=full)[0] for k in keys])
        else:
            V = torch.stack([self._vis(*k, full=full) for k in keys])        # (U, P)
        oxt = torch.tensor(ox, dtype=torch.float32, device=DEV)[:, None]
        oyt = torch.tensor(oy, dtype=torch.float32, device=DEV)[:, None]
        deg = torch.tensor(cands[:, 2], dtype=torch.float32, device=DEV)[:, None]
        dx, dy = self.px[None] - oxt, self.py[None] - oyt
        diff = torch.remainder(torch.rad2deg(torch.atan2(dy, dx)) - deg + 180.0, 360.0) - 180.0
        wedge = (diff.abs() <= cone.CONE_HALF_ANGLE_DEG) | (dx * dx + dy * dy < 0.25)
        okt = torch.tensor(ok, device=DEV)[:, None]
        return V[torch.tensor(vid, device=DEV)] & wedge & okt

    @staticmethod
    def jumping(pose) -> bool:
        """0.6.0 "boxes": a pose's jump state rides in slot 3 (0.2.0's ring gain, always 0 in RGB)."""
        return "boxes" in CHANGES and pose is not None and len(pose) > 3 and float(pose[3]) > 0.5

    def pose_cone(self, pose):
        jump = self.jumping(pose)
        key = tuple(round(float(v), 3) for v in pose[:3]) + ((1,) if jump else ())
        got = self._pc.get(key)
        if got is None:
            got = self.cones(np.array([pose[:3]], np.float64), jump=jump)[0]
            self._pc[key] = got
        return got

    def crosses(self, cands: np.ndarray, full: bool = False) -> np.ndarray:
        """(N,) bool: whether jumping changes the cone of each `(x, y, deg)` row over the window."""
        meta = {}
        J = self.cones(cands, full=full, jump=True, _meta=meta)
        if not meta.get("keys"):
            return np.zeros(len(cands), bool)
        V = self.cones(cands, full=full)
        return (J & ~V).any(1).cpu().numpy()

    def held(self, poses: dict, skip=None, sources: bool = True):
        """`(L, free)`, each (P,) bool: the light of the posed team icons but `skip` (and of the drawn
        sources unless `sources` is False), and the free pixels."""
        L = (self.out if sources else self.out_cones).clone()
        present = [j for j, p in poses.items() if p is not None and j != skip]
        for j in present:
            if self.team[j]:
                L |= self.pose_cone(poses[j])
        if skip is not None:
            present.append(skip)
        free = self.free_out.copy()
        absent = [j for j in range(len(self.team)) if self.team[j] and j not in present]
        if absent and present:
            free |= self.dist[absent].min(0) < self.dist[present].min(0)
        if sources and SOURCE_STATE == "free":
            free |= self.src_np
        return L, torch.tensor(free, device=DEV)

    def held_standing(self, poses: dict):
        """(P,) bool: the cone light with every caster standing, scene and outside (no source)."""
        L = torch.zeros(len(self.xx), dtype=torch.bool, device=DEV)
        for o in self.outside:
            if o.get("deg") is not None:
                L |= self.cones(np.array([[o["x"], o["y"], o["deg"]]], np.float32), full=bool(o.get("full")))[0]
        for j, p in poses.items():
            if p is not None and self.team[j]:
                L |= self.pose_cone(tuple(p[:3]))
        return L

    def jump_report(self, poses: dict) -> list[dict]:
        """0.6.0 "boxes": every caster whose cone crosses a box in the window, its state, and per crossed
        box the pixels past it and how many of the compared ones read lit (filled by `light_stats`)."""
        rows = []
        cast = [("scene", j, p) for j, p in poses.items() if p is not None and self.team[j]]
        cast += [("outside", k, (o["x"], o["y"], o["deg"], float(self.out_jump[k])))
                 for k, o in enumerate(self.outside) if o.get("deg") is not None]
        for kind, j, p in cast:
            full = kind == "outside" and bool(self.outside[j].get("full"))
            meta = {}
            self.cones(np.array([p[:3]], np.float64), full=full, _meta=meta)
            if not meta.get("keys") or not meta["ok"][0]:
                continue
            key = meta["keys"][int(meta["vid"][0])]
            _u, per = self._beyond(*key, full=full)
            V = self.cones(np.array([p[:3]], np.float64), full=full)[0]
            boxes = {}
            for b, m in per.items():
                w = self.cones(np.array([p[:3]], np.float64), full=full, jump=True)[0] & m & ~V
                if w.any():
                    boxes[b] = w
            if not boxes:
                continue
            rows.append({"caster": kind, "index": j, "jumping": bool(self.jumping(p)) if kind == "scene"
                         else bool(self.out_jump[j]), "_boxes": boxes,
                         "role": (self.outside[j].get("role") if kind == "outside" else None)})
        return rows

    def extra(self, poses: dict, skip=None) -> float:
        """0.6.0 "boxes": the prior cost of every jumping caster held (scene icons but `skip`, outside)."""
        if not self.boxes:
            return 0.0
        n = sum(self.team[j] and self.jumping(p) for j, p in poses.items() if p is not None and j != skip)
        return BOX_JUMP_COST * (n + int(self.out_jump.sum()))

    def set_outside_jump(self, k: int, jump: bool):
        """Put outside caster `k` standing or jumping and rebuild the held outside light."""
        self.out_jump[k] = jump
        o = self.outside[k]
        o["_cone"] = self.cones(np.array([[o["x"], o["y"], o["deg"]]], np.float32), full=bool(o.get("full")),
                                jump=jump)[0]
        out = torch.zeros(len(self.xx), dtype=torch.bool, device=DEV)
        for q in self.outside:
            if "_cone" in q:
                out |= q["_cone"]
        self.out_cones = out.clone()
        if SOURCE_STATE == "lit":
            out |= self.src
        self.out = out

    def err(self, e2, L, free):
        """Per-pixel error (N, P): the pose-predicted floor state, or the other one at its cost."""
        e_pred = torch.where(L, e2[:, 1], e2[:, 0])
        cm = torch.full_like(e_pred, self.c_m)
        cu = torch.full_like(e_pred, self.c_u)
        cost = torch.where(L, cm, cu) * (~free).float()[None]
        e_alt = torch.where(L, e2[:, 0], e2[:, 1]) + cost
        return torch.minimum(e_pred, e_alt)

    def read_lit(self, e2):
        """The instrument's per-pixel read (light-diagnosis-0.1.0): lit iff `e2[1] + c_u < e2[0]`."""
        return e2[:, 1] + self.c_u < e2[:, 0]

    def regions_of(self, comp, L):
        """(N, P) int64 labels: 4-connected components of the compared pixels `comp` with one predicted
        state `L`, so a region is bounded by the cone edges, the baked walls (not floor, never compared)
        and the icons' footprints. Row and column passes of a segmented minimum until nothing changes."""
        N, P = comp.shape
        H, W = self.H, self.W
        c = comp.view(N, H, W)
        l_ = L.view(N, H, W)
        hb = torch.ones(N, H, W, dtype=torch.bool, device=DEV)
        hb[:, :, 1:] = ~(c[:, :, 1:] & c[:, :, :-1] & (l_[:, :, 1:] == l_[:, :, :-1]))
        hseg = torch.cumsum(hb.reshape(-1).long(), 0) - 1                       # row-major segments
        vb = torch.ones(N, W, H, dtype=torch.bool, device=DEV)
        ct, lt = c.transpose(1, 2), l_.transpose(1, 2)
        vb[:, :, 1:] = ~(ct[:, :, 1:] & ct[:, :, :-1] & (lt[:, :, 1:] == lt[:, :, :-1]))
        vseg_t = torch.cumsum(vb.reshape(-1).long(), 0) - 1                     # column-major segments
        vseg = vseg_t.view(N, W, H).transpose(1, 2).reshape(-1)
        lab = torch.arange(N * P, device=DEV)
        big = N * P
        for _ in range(REGION_PASSES):
            m = torch.full((int(hseg[-1]) + 1,), big, dtype=torch.long, device=DEV)
            lab2 = m.scatter_reduce(0, hseg, lab, "amin")[hseg]
            m = torch.full((int(vseg_t[-1]) + 1,), big, dtype=torch.long, device=DEV)
            lab2 = m.scatter_reduce(0, vseg, lab2, "amin")[vseg]
            if torch.equal(lab2, lab):
                break
            lab = lab2
        return lab.view(N, P)

    def region_state(self, e2, L, comp):
        """0.6.0 "regions": (N, P) bool, the state each compared pixel's region takes as a whole: lit iff
        the sum over its pixels of the read's log-likelihood ratio (`instrument_rates`) and the cone
        prediction's prior log-odds (`c_m / 2` for lit, `c_u / 2` against, since a cost is -2 ln odds)
        is positive."""
        p1, p0 = self.rates
        l1, l0 = math.log(p1 / p0), math.log((1.0 - p1) / (1.0 - p0))
        read = self.read_lit(e2)
        t = torch.where(read, torch.full_like(read, l1, dtype=torch.float32),
                        torch.full_like(read, l0, dtype=torch.float32))
        t = t + torch.where(L, torch.full_like(t, self.c_m / 2.0), torch.full_like(t, -self.c_u / 2.0))
        lab = self.regions_of(comp, L).reshape(-1)
        tot = torch.zeros(lab.numel(), dtype=torch.float32, device=DEV)
        tot.index_add_(0, lab, (t * comp.float()).reshape(-1))
        return (tot[lab] > 0).view(comp.shape) & comp

    def region_err(self, e2, L, free, comp):
        """0.6.0 "regions": per-pixel error (N, P). A compared pixel pays its colour error under its
        region's state, plus the prediction's cost where the region disagrees with the cone; every other
        pixel keeps 0.5.0's `err`."""
        base = self.err(e2, L, free)
        S = self.region_state(e2, L, comp)
        e_s = torch.where(S, e2[:, 1], e2[:, 0])
        cost = torch.where(L, torch.full_like(e_s, self.c_m), torch.full_like(e_s, self.c_u))
        e_r = e_s + cost * (S != L).float()
        return torch.where(comp, e_r, base)


def frame_team(s, r: dict, sc: float) -> list[dict]:
    """The frame's team icons with their teardrop poses (`facing_fusion.team_icons`), cached on the row."""
    if "_team" not in r:
        r["_team"] = ff.team_icons(s, r["_crop"], sc)
    return r["_team"]


def outside_icons(team: list[dict], sc: float, scene_icons: list[dict]) -> list[dict]:
    """The frame's team icons that no scene team icon is (none within `SAME_PX` of one's prior centre)."""
    out = []
    for ic in team:
        if any(q["cls"] != "enemy" and math.hypot(q["x0"] - ic["cx"], q["y0"] - ic["cy"]) <= SAME_PX * sc
               for q in scene_icons):
            continue
        out.append({"x": ic["x"], "y": ic["y"], "deg": ic["deg"], "role": ic["role"]})
    return out


# ---------------------------------------------------------------- 0.6.0: casters, rates, darkening

_RATES: dict = {}


def instrument_rates(sc: float) -> tuple[float, float]:
    """`(p1, p0)`: the share of truly lit and of truly unlit compared pixels the read rule reads lit,
    measured by light-diagnosis-0.1.0 at the nearest widget scale (`INSTRUMENT_PATH`)."""
    if not _RATES:
        _RATES.update(json.loads(INSTRUMENT_PATH.read_text(encoding="utf-8")))
    scales = sorted({k.split("@")[1] for k in _RATES if "@" in k}, key=lambda k: abs(float(k) - sc))
    k = scales[0]
    return float(_RATES[f"lit@{k}"]["rule_lit_share"]), float(_RATES[f"unlit@{k}"]["rule_lit_share"])


def minimap_darkened(s, crop: np.ndarray) -> dict:
    """0.6.0 "dark": the median of the crop's grey minus the baked static's grey over the known floor,
    and whether it sits below `DARK_MEDIAN` (the whole minimap darkened, as by an enemy Reyna's blind
    [domain:abilities/reyna-leer-darkens-minimap]). The owner `minimap.widget_drawn`'s answer is kept
    beside it, as a second channel: the stored minimap_dark rows call c40d950031bb's blinded frames
    `widget_not_drawn`."""
    from reticle.minimap import widget_drawn
    st = s.inputs.static
    if st.shape[:2] != crop.shape[:2]:
        return {"median": None, "darkened": None, "reason": "geometry_size_mismatch"}
    sg = cv2.cvtColor(st, cv2.COLOR_BGR2GRAY)
    d = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32) - sg.astype(np.float32)
    kn = s.ref.known.astype(bool)
    med = float(np.median(d[kn]))
    try:
        drawn = bool(widget_drawn(crop, sg, s.floor))
    except Exception as e:       # the owner's signature or inputs differ: record, never guess
        drawn = f"unread: {type(e).__name__}"
    return {"median": round(med, 1), "darkened": med < DARK_MEDIAN, "widget_drawn": drawn}


class TVFrames:
    """0.6.0 "cast": the stored team_vision frames of one session near the wanted instants, full icon
    dicts (role, track_id, x, y, facing, interpolated), back `CAST_BACK_MS` for the hidden-icon rule."""

    def __init__(self, sid: str, wanted: list[float]):
        self.rows: dict = {}
        p = sem.STORE / "events" / "team_vision" / f"{sid}.jsonl"
        if not p.is_file():
            return
        lo = [(t - CAST_BACK_MS - 50.0, t + CAST_FRAME_MS) for t in wanted]
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
                self.rows[t] = [ic for ic in d.get("icons", []) if ic.get("x") is not None]

    def at(self, t_ms: float):
        near = [t for t in self.rows if abs(t - t_ms) <= CAST_FRAME_MS]
        if not near:
            return None, []
        t = min(near, key=lambda x: abs(x - t_ms))
        return t, self.rows[t]


def _isolated(x, y, others, sc) -> bool:
    return all(math.hypot(x - ox, y - oy) > STACK_PX * sc for ox, oy in others)


def _last_visible(s, tv: TVFrames, track_id, role: str, t_ms: float, sc: float):
    """The teardrop facing of the track's last visible, isolated read within `CAST_BACK_MS` before
    `t_ms`, in the crop cache: `(t, deg, x, y)` or None. The stored frame there places the icon and its
    neighbours; the teardrop (`facing_fusion.fit`) reads it."""
    times = sorted((t for t in tv.rows if t_ms - CAST_BACK_MS <= t < t_ms - 1.0), reverse=True)
    cache = np.asarray(s.cache_t, np.float64)
    if not len(cache):
        return None
    cls = "self" if role == "self" else "ally"
    for t in times:
        ics = tv.rows[t]
        me = [ic for ic in ics if ic.get("track_id") == track_id]
        if not me:
            continue
        me = me[0]
        k = int(np.argmin(np.abs(cache - t)))
        if abs(cache[k] - t) > 20.0:
            continue
        others = [(ic["x"], ic["y"]) for ic in ics if ic is not me]
        if not _isolated(me["x"], me["y"], others, sc):
            continue
        got = list(s.crops([float(cache[k])]))
        if not got:
            continue
        crop = got[0][1]
        f = ff.fit(crop, cls, float(me["x"]), float(me["y"]), sc)
        if f.get("read"):
            return float(cache[k]), float(f["deg"]), float(f["x"]), float(f["y"])
    return None


def team_casters(s, r: dict, sc: float, scene_icons: list[dict], tv: TVFrames | None) -> tuple[list, list]:
    """0.6.0 "cast": `(outside, casters)`. Every teammate the stored team_vision frame at the instant
    places casts: a scene icon from the joint fit (not in `outside`), a visible icon from its teardrop,
    a hidden one (tracked, no teardrop read there) from its last visible isolated teardrop within
    `CAST_BACK_MS` (`depends_on` names that read), else from the stored track facing, else it frees the
    floor nearest it, as 0.5.0 does for an unread icon. Outside casters cast at full range. A frame team
    icon no track places casts as in 0.5.0. `casters` records each one's facing source."""
    team = frame_team(s, r, sc)
    t_f, icons = tv.at(float(r["t_ms"])) if tv is not None else (None, [])
    enemy = [(d["cx"], d["cy"]) for d in it_.detections(r["_crop"], "enemy", s)]
    used = set()
    outside, casters = [], []
    for ic in icons:
        role = ic.get("role")
        if role not in ("self", "ally"):
            continue
        x, y, tid = float(ic["x"]), float(ic["y"]), ic.get("track_id")
        rec = {"role": role, "track_id": tid, "x": round(x, 2), "y": round(y, 2), "tv_t_ms": t_f,
               "interpolated": ic.get("interpolated")}
        scene_hit = [q for q in scene_icons if q["cls"] != "enemy" and (
            (q.get("track_id") is not None and q.get("track_id") == tid)
            or math.hypot(q["x0"] - x, q["y0"] - y) <= SAME_PX * sc)]
        near = [k for k, q in enumerate(team) if k not in used and math.hypot(q["cx"] - x, q["cy"] - y)
                <= SAME_PX * sc]
        if near:
            k = min(near, key=lambda k: math.hypot(team[k]["cx"] - x, team[k]["cy"] - y))
            used.add(k)
        else:
            k = None
        if scene_hit:
            casters.append({**rec, "facing_source": "joint_fit"})
            continue
        q = team[k] if k is not None else None
        if q is not None and q.get("deg") is not None:
            others = [(o["cx"], o["cy"]) for kk, o in enumerate(team) if kk != k] + enemy
            iso = _isolated(q["cx"], q["cy"], others, sc)
            outside.append({"x": q["x"], "y": q["y"], "deg": q["deg"], "role": role, "full": True})
            casters.append({**rec, "facing_source": "teardrop" if iso else "teardrop_stacked",
                            "deg": round(float(q["deg"]), 2)})
            continue
        prev = _last_visible(s, tv, tid, role, float(r["t_ms"]), sc) if tid is not None else None
        if prev is not None:
            tp, deg, _px, _py = prev
            outside.append({"x": x, "y": y, "deg": deg, "role": role, "full": True})
            casters.append({**rec, "facing_source": "last_visible_teardrop", "deg": round(deg, 2),
                            "depends_on": {"t_ms": tp, "track_id": tid,
                                           "rule": "a hidden icon keeps its last visible isolated teardrop"}})
            continue
        if ic.get("facing") is not None:
            outside.append({"x": x, "y": y, "deg": float(ic["facing"]), "role": role, "full": True})
            casters.append({**rec, "facing_source": "stored_track", "deg": round(float(ic["facing"]), 2)})
            continue
        outside.append({"x": x, "y": y, "deg": None, "role": role})
        casters.append({**rec, "facing_source": None, "reason": "no facing: hidden, no visible read, "
                                                               "no stored facing"})
    for k, q in enumerate(team):
        if k in used:
            continue
        if any(qq["cls"] != "enemy" and math.hypot(qq["x0"] - q["cx"], qq["y0"] - q["cy"]) <= SAME_PX * sc
               for qq in scene_icons):
            continue
        outside.append({"x": q["x"], "y": q["y"], "deg": q["deg"], "role": q["role"], "full": True})
        casters.append({"role": q["role"], "track_id": None, "x": round(float(q["x"]), 2),
                        "y": round(float(q["y"]), 2), "facing_source": "teardrop_untracked"
                        if q["deg"] is not None else None,
                        "deg": None if q["deg"] is None else round(float(q["deg"]), 2)})
    return outside, casters


#: The agents whose own ability lifts them over a tall box (the player, 2026-09-30): Jett's updraft,
#: Waylay's vertical ability, Raze's satchel. Until box heights exist a boosted caster's cone is a
#: jumping one's, so the state is only an eligibility: a pass by a caster who cannot boost is stored
#: as a surprise.
BOOST_AGENTS = ("jett", "waylay", "raze")
_BOOST: dict = {}


def boost_eligible(sid: str, role: str) -> str:
    """"yes", "no" or "unknown": whether the caster's agent (from the stored lineup, named by the
    identity arbiter) can boost. An ally track carries no agent, so an ally is "unknown" when any
    teammate but the player may be a boost agent and "no" only when the side is named in full."""
    key = (sid, role)
    if key in _BOOST:
        return _BOOST[key]
    from reticle.lineup import load_lineup
    from reticle.adjudication.ult_cast import lineup_sides, player_agent
    lu = load_lineup(sid, sem.STORE)
    me = player_agent(lu, sid)
    if role == "self":
        got = "unknown" if me is None else ("yes" if me.lower() in BOOST_AGENTS else "no")
    else:
        side = (lineup_sides(lu, sid) or {}).get("ally")
        if not side:
            got = "unknown"
        else:
            names = [a.lower() for a in side["named"] + side["soft"]]
            if me is not None and me.lower() in names:
                names.remove(me.lower())
            if any(a in BOOST_AGENTS for a in names):
                got = "unknown"
            else:
                got = "no" if side["complete"] else "unknown"
    _BOOST[key] = got
    return got


# ---------------------------------------------------------------- the drawn light sources (0.4.0)

#: The non-cone sources 0.4.0 draws, in order. `--no-sources` empties it: the 0.3.0 control.
SOURCES = ("audio", "clove", "ability")
#: How a drawn source's disc enters the light: "free", either floor state at no cost, so no cone is
#: evidence there. The first design, "lit" (the disc predicted lit), was dropped after the instrument
#: check on unlabelled frames (`--light-cal`, before any labelled score): known floor inside the drawn
#: discs read nearer the lit state on only 0.46 (331 px) and 0.43 (465 px), and the calibrated
#: missing-light rate rose from 0.19 to 0.25 and from 0.08 to 0.24. The audio disc tints the floor white
#: over either state; it is not the lit state. 0.5.0 renders that tint ("tint", the measured profile of
#: `--tint-cal`, `tint_maps`); `--disc` sets "free" again, the 0.4.0 control.
SOURCE_STATE = "tint"
#: A frame's circle counts as observed when its ring score (grey levels, inside minus outside) reaches
#: audio_circle's upper hysteresis cut, one frame alone (no hysteresis across frames here) ...
SRC_T = ac.T_HI
#: ... and its exact fit (`clove_circle.fit_circle`) meets audio_circle.radius_span's good-fit rule.
SRC_FIT_INLIERS, SRC_FIT_RMS = 0.5, 1.5
#: Scale 1.0: a free-search circle whose centre and radius lie this near the audio circle's is it.
SRC_SAME_PX = 6.0
#: Scale 1.0: the audio circle's centre is sought this far from the stored self position. Set after
#: viewing one labelled frame's sources (not its facing scores): at e37fdeca944f 1795.08 s the pale disc's
#: centre lies about 17 px (331 px widget) from the self icon, and a +-4 px search fitted a false circle.
AUDIO_REACH_PX = 32.0
#: The ability areas the player named; each is drawn only as a circle fitted round a stored observation
#: (the player's label of its icon) within `ABILITY_WINDOW_MS` of the frame, and only where the frame
#: shows one [domain:abilities/ability-rules-are-unique]. No radius is assumed: it is fitted per frame.
ABILITY_NAMES = ("chamber:trademark", "veto:chokehold", "deadlock:sonic sensor")
ABILITY_WINDOW_MS = 1000.0
ABILITY_R = (8.0, 60.0)      # scale 1.0: the searched radii round a labelled ability icon
_AC: dict = {}
_DEAD: dict = {}
_ABIL: dict = {}


def _ac_session(sid: str):
    """audio_circle's session (cache, baked static, stored self track), or `(None, reason)`."""
    if sid not in _AC:
        try:
            _AC[sid] = (ac.Session(sid), None)
        except StopIteration:
            _AC[sid] = (None, "no stored self track (l1/minimap)")
        except SystemExit as e:
            _AC[sid] = (None, str(e))
    return _AC[sid]


def _ring_fit(d: np.ndarray, c, radii: np.ndarray, reach: float = 0.0) -> dict | None:
    """The best circle centred within `reach` (+ audio_circle's +-4 px grid) of `c` over `radii`:
    audio_circle's ring score grid at base centres every 8 px, the peak over centre and radius, then
    `clove_circle.fit_circle` there. Observed when the peak and the fitted ring clear audio_circle's cuts,
    the fit is good, and the fitted centre stays within `reach` + 4 px of `c`.

    A thin wrapper for per-frame radius fitting, since the player saw the audio circle's radius vary;
    `audio_circle.py` gains its own per-frame fit on another branch, and the two are to be reconciled."""
    n = int(round(reach / 8.0))
    best = (-np.inf, None, None)
    for bx in range(-n, n + 1):
        for by in range(-n, n + 1):
            b = (c[0] + 8.0 * bx, c[1] + 8.0 * by)
            cur = ac.ring_curve(d, b, radii)
            if not np.isfinite(cur).any():
                continue
            o, k = np.unravel_index(int(np.nanargmax(np.nan_to_num(cur, nan=-1e9))), cur.shape)
            if cur[o, k] > best[0]:
                best = (float(cur[o, k]), (b[0] + ac.OFFS[o][0], b[1] + ac.OFFS[o][1]), float(radii[k]))
    if best[1] is None:
        return None
    f = cc.fit_circle(d, best[1], best[2], win=6.0)
    f.update(score=best[0], r0=best[2], ring=cc.ringscore(d, (f["cx"], f["cy"]), f["r"]),
             centre_off=float(math.hypot(f["cx"] - c[0], f["cy"] - c[1])))
    f["observed"] = bool(f["score"] >= SRC_T and f["inliers"] >= SRC_FIT_INLIERS and f["rms"] < SRC_FIT_RMS
                         and f["ring"] >= ac.T_LO and f["centre_off"] <= 8.0 * n + 6.0)
    return f


#: The audio circle is white-tinted [domain:minimap/self-audio-circle]: its rim raises every colour
#: channel. A fit counts as the audio circle only when its weakest channel's step (inside minus outside,
#: crop minus baked static) reaches this share of its strongest. Set after viewing the census's circles
#: (not any facing score): at 223d636bf8d2 1095.33 s the self-centred fit was a thick yellow ring.
AUDIO_WHITE_MIN = 0.5


def rim_steps(crop: np.ndarray, static: np.ndarray, c, r: float, band: float = 4.0) -> np.ndarray:
    """(3,) BGR: the median over 180 rays of the mean channel change (crop minus static) in the band just
    inside radius `r` minus the band just outside it."""
    h, w = crop.shape[:2]
    a = np.linspace(0, 2 * np.pi, 180, endpoint=False)
    dd = crop.astype(np.float32) - static.astype(np.float32)

    def ring(rr):
        x = np.rint(c[0] + rr[:, None] * np.cos(a)[None]).astype(int)
        y = np.rint(c[1] + rr[:, None] * np.sin(a)[None]).astype(int)
        ok = (x >= 0) & (x < w) & (y >= 0) & (y < h)
        v = np.full(x.shape + (3,), np.nan, np.float32)
        v[ok] = dd[y[ok], x[ok]]
        return np.nanmean(v, axis=0)                      # (180, 3)

    with np.errstate(all="ignore"), warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        step = ring(np.arange(r - band, r) + 0.5) - ring(np.arange(r + 1, r + band + 1) - 0.5)
        return np.nanmedian(step, axis=0)


def whiteness(steps: np.ndarray) -> float:
    """The weakest channel's rim step as a share of the strongest (<= 0 when a channel falls)."""
    hi = float(np.nanmax(steps))
    return float(np.nanmin(steps)) / hi if hi > 0 else float("nan")


def _dead_cloves(sid: str) -> tuple[list[float], list[float]]:
    """`(round starts, ally Clove death times)`: the victim named by the identity arbiter
    (`death_identity`, `adjudication.identity`), the side from the death owner's event, the round
    starts from the stored rounds table."""
    if sid in _DEAD:
        return _DEAD[sid]
    side, name = {}, {}
    p = sem.STORE / "events" / "death_identity" / f"{sid}.jsonl"
    for line in (p.open(encoding="utf-8") if p.is_file() else []):
        e = json.loads(line)
        if e.get("event_kind") == "entity_deleted":
            side[e["entity_id"]] = ((e.get("metadata") or {}).get("side"), float(e["t_ms"]))
        elif e.get("event_kind") == "identity_distribution":
            dist = (e.get("identity_distribution") or {}).get("distribution") or {}
            if dist:
                top = max(dist, key=dist.get)
                if dist[top] >= 0.5:
                    name[e["identity_distribution"]["subject_entity_id"]] = top
    from reticle.cli import _date_of
    from reticle.store import Store
    st = Store()
    tb = st.read_rounds(sid, _date_of(st.read_manifest(sid)))
    starts = sorted(float(r["t_start_ms"]) for r in (tb.to_pylist() if tb is not None else []))
    deaths = sorted(t for eid, (sd, t) in side.items() if sd == "ally" and name.get(eid) == "Clove")
    _DEAD[sid] = (starts, deaths)
    return _DEAD[sid]


def _clove_dead_at(sid: str, t_ms: float) -> float | None:
    """The last ally Clove death at or before `t_ms` in the round that holds `t_ms`, else None."""
    starts, deaths = _dead_cloves(sid)
    k = int(np.searchsorted(starts, t_ms, "right")) - 1
    t0 = starts[k] if k >= 0 else float("-inf")
    got = [t for t in deaths if t0 <= t <= t_ms]
    return got[-1] if got else None


def _ability_obs(sid: str) -> list[dict]:
    """The player's labels of the named abilities' icons (`labels/ability`, `labels/ability_paint`)."""
    if sid in _ABIL:
        return _ABIL[sid]
    out = []
    root = sem.STORE / "labels"
    p = root / "ability" / f"{sid}.jsonl"
    for line in (p.open(encoding="utf-8") if p.is_file() else []):
        r = json.loads(line)
        if not r.get("not_ability") and r.get("category_id") in ABILITY_NAMES:
            out.append({"t_ms": float(r["t_ms"]), "x": float(r["x"]), "y": float(r["y"]),
                        "name": r["category_id"], "source": "labels/ability"})
    p = root / "ability_paint" / f"{sid}.jsonl"
    for line in (p.open(encoding="utf-8") if p.is_file() else []):
        r = json.loads(line)
        for ic in r.get("icons") or []:
            if ic.get("category_id") in ABILITY_NAMES:
                out.append({"t_ms": float(r["t_ms"]), "x": float(ic["x"]), "y": float(ic["y"]),
                            "name": ic["category_id"], "source": "labels/ability_paint"})
    _ABIL[sid] = out
    return out


def _free_circle(d: np.ndarray, radii: np.ndarray, avoid: dict | None):
    """`clove_circle.free_search` over every in-widget centre, with the audio circle's rim (when
    observed) blanked so the search cannot return it."""
    if avoid is not None:
        yy, xx = np.mgrid[0:d.shape[0], 0:d.shape[1]]
        d = d.copy()
        d[np.abs(np.hypot(xx - avoid["cx"], yy - avoid["cy"]) - avoid["r"]) <= 5.0] = np.nan
    return cc.free_search(d.astype(np.float32), radii=radii, step=4.0)


def find_sources_v4(sid: str, t_ms: float, crop: np.ndarray, sc: float, kinds=None) -> dict:
    """0.4.0's non-cone light sources on this frame, `{"drawn": [circle], "notes": {kind: reason}}`, over
    `kinds` (default SOURCES); 0.5.0 keeps its ability search and replaces the audio and Clove fits.

    Each drawn circle is `{"kind", "cx", "cy", "r", "score", "rms", "inliers", ...}`, fitted on this
    frame's static-subtracted grey (audio_circle's `Session.diff`, the baked static as background):
    - audio: round the stored self position [domain:minimap/self-audio-circle], radius fitted per frame;
    - clove: only while an ally Clove is dead in this round by the stored death data, the best circle
      at any centre [domain:abilities/clove-dead-smoke-range-circle], never the audio circle;
    - ability: round a labelled Trademark, Chokehold or Sonic Sensor icon within ABILITY_WINDOW_MS.
    """
    out = {"drawn": [], "notes": {}}
    kinds = SOURCES if kinds is None else kinds
    if not kinds:
        return out
    S, why = _ac_session(sid)
    if S is None:
        out["notes"] = {k: why for k in kinds}
        return out
    if S.static.shape[:2] != crop.shape[:2]:
        out["notes"] = {k: f"crop {crop.shape[:2]} is not the baked frame {S.static.shape[:2]}" for k in kinds}
        return out
    d = S.diff(crop)
    audio = None
    if "audio" in kinds:
        me, _drawn = S.self_at(t_ms)
        if me is None:
            out["notes"]["audio"] = "no stored self position within +-200 ms"
        else:
            f = _ring_fit(d, me, S.radii, reach=AUDIO_REACH_PX * sc)
            if f is not None:
                f["bgr_step"] = [round(float(v), 2) for v in rim_steps(crop, S.static, (f["cx"], f["cy"]), f["r"])]
                f["white"] = whiteness(np.array(f["bgr_step"]))
            if f is None or not f["observed"] or not f["white"] >= AUDIO_WHITE_MIN:
                out["notes"]["audio"] = "not observed" + ("" if f is None else (
                    f" (score {f['score']:.1f} ring {f['ring']:.1f} rms {f['rms']:.2f} inliers {f['inliers']:.2f} "
                    f"r {f['r']:.1f} off {f['centre_off']:.1f} white {f['white']:.2f})"))
            else:
                audio = {"kind": "audio", **{k: f[k] for k in ("cx", "cy", "r", "score", "ring", "rms", "inliers",
                                                               "centre_off", "white", "bgr_step")},
                         "self_x": me[0], "self_y": me[1]}
                out["drawn"].append(audio)
    if "clove" in kinds:
        td_ = _clove_dead_at(sid, t_ms)
        if td_ is None:
            out["notes"]["clove"] = "no ally Clove dead in this round (stored death data)"
        else:
            score, where = _free_circle(d, S.radii[::2], audio)
            if where is None or score < SRC_T:
                out["notes"]["clove"] = f"ally Clove dead since {td_ / 1000:.1f} s; no circle (best {score:.1f})"
            else:
                f = cc.fit_circle(d, where[:2], where[2], win=6.0)
                ring = cc.ringscore(d, (f["cx"], f["cy"]), f["r"])
                same = audio is not None and (math.hypot(f["cx"] - audio["cx"], f["cy"] - audio["cy"])
                                              <= SRC_SAME_PX * sc and abs(f["r"] - audio["r"]) <= SRC_SAME_PX * sc)
                if f["inliers"] >= SRC_FIT_INLIERS and f["rms"] < SRC_FIT_RMS and ring >= ac.T_LO and not same:
                    out["drawn"].append({"kind": "clove", **{k: f[k] for k in ("cx", "cy", "r", "rms", "inliers")},
                                         "score": score, "ring": ring, "death_t_ms": td_})
                else:
                    out["notes"]["clove"] = (f"ally Clove dead since {td_ / 1000:.1f} s; best circle's fit fails "
                                             f"(score {score:.1f} ring {ring:.1f} rms {f['rms']:.2f} "
                                             f"inliers {f['inliers']:.2f}{' same as audio' if same else ''})")
    if "ability" in kinds:
        near = [a for a in _ability_obs(sid) if abs(a["t_ms"] - t_ms) <= ABILITY_WINDOW_MS]
        if not near:
            out["notes"]["ability"] = "no labelled Trademark, Chokehold or Sonic Sensor within 1 s"
        radii = np.arange(round(ABILITY_R[0] * sc), round(ABILITY_R[1] * sc) + 1, 1.0)
        for a in near:
            f = _ring_fit(d, (a["x"], a["y"]), radii)
            if f is not None and f["observed"]:
                out["drawn"].append({"kind": "ability", "name": a["name"], "label_t_ms": a["t_ms"],
                                     **{k: f[k] for k in ("cx", "cy", "r", "score", "ring", "rms", "inliers")}})
            else:
                out["notes"]["ability"] = (f"{a['name']} labelled at {a['t_ms'] / 1000:.2f} s: no area observed"
                                           + ("" if f is None else (
                                               f" (score {f['score']:.1f} ring {f['ring']:.1f} rms {f['rms']:.2f} "
                                               f"inliers {f['inliers']:.2f} r {f['r']:.1f})")))
    return out


def source_mask(src: dict, shape) -> np.ndarray:
    """(H, W) bool: the floor the drawn sources light (each circle's disc)."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros(shape, bool)
    for c in src["drawn"]:
        m |= np.hypot(xx - c["cx"], yy - c["cy"]) <= c["r"]
    return m


# ---------------------------------------------------------------- 0.5.0: the sources as rendered tints

#: 0.5.0 renders each drawn source as a measured tint over either floor state (`SOURCE_STATE = "tint"`):
#: the predicted background is `(1 - a) bg + a W`, `a` the source's radial opacity profile and `W` its
#: tint colour, both measured by `--tint-cal` on unlabelled frames where the circle turns on or off in
#: place, so the off frame shows the floor under it in whatever state it is. The cones still predict the
#: floor's state inside the circle, so the floor there stays evidence. `--disc` reruns 0.4.0 (the disc
#: freed, `find_sources_v4`) as the control.
TINT_CAL_NAME = "tint_calibration.json"
#: Scale 1.0: an audio fit counts only when its centre lies this near the stored self position, because
#: the circle follows the self icon (the player, 2026-09-30) [domain:minimap/self-audio-circle]. Set from
#: unlabelled fits before any labelled item was refitted: `audio_circle.frame_fit` on 200 drawn own-view
#: frames of 4f207c0c4e39 put the centre a median 1.6 px from the stored self, the 95th percentile 3.1 px
#: and the 99th 6.6 px (the stored track jumps); 7 px at scale 1.0 is 5.0 px on a 331 px widget, which
#: keeps about 98 in 100 true fits and rejects a circle centred 17 px away.
AUDIO_CENTRE_TOL_PX = 7.0
#: Scale 1.0: a fit's radius must be the session's footstep size (the mode of its unlabelled fits,
#: `--tint-cal`) or its reload size (that times audio_circle's measured reload/footstep ratio) within this.
#: The ranges are in-game distances and the drawn size follows the map scaling
#: [domain:capture/minimap-size-settings], so each session measures its own size; the ratio is one
#: capture's, carried to the others as a belief the per-session reload fits test.
AUDIO_SIZE_TOL_PX = 2.0
#: A dead Clove's circle is centred on the death location [domain:abilities/clove-dead-smoke-range-circle].
#: The stored death data (death_identity) holds the time and the victim, not the place, so the death point
#: is the last position of the stored ally track (events/team_vision) that ends within this window of the
#: stored death time, unless another ally track starts within CLOVE_GAP_MS and CLOVE_SAME_TRACK_PX of that
#: end (the tracker split one living icon).
CLOVE_TRACK_WINDOW_MS = (-1500.0, 500.0)
CLOVE_GAP_MS = 1000.0
CLOVE_SAME_TRACK_PX = 12.0     # scale 1.0
#: Scale 1.0: the circle's fitted centre lies this near a death point. The one measured cast put it 0.56 px
#: from the death X [domain:abilities/clove-dead-smoke-range-circle]; the slack is the stored track's.
CLOVE_REACH_PX = 8.0
#: The tint profile's bins over dr, a pixel's distance from the circle's centre minus its radius, in
#: widget px: one interior bin (dr < -12), 1 px bins to +3, one exterior bin [3, 6); zero beyond 6.
TINT_EDGES = np.arange(-12.0, 4.0, 1.0)
TINT_OUTER = 6.0
#: The bins whose pixels measure the tint colour W (the brightest part of the rim).
TINT_W_BINS = (-3.0, 0.0)
#: A pixel this near the self icon's centre (scale 1.0) is the icon, not floor, in a tint pair.
TINT_ICON_PX = 14.0
#: `--tint-cal`: per labelled session and the Iso capture, this many windows of unlabelled frames,
#: each TINT_WINDOW_S long and at least CAL_AWAY_MS from any labelled instant, are scanned for the
#: audio circle turning on or off; the frames of a pair are two cache frames apart (the circle appears
#: within one frame and fades through one [audio_circle, 2026-09-29]).
TINT_WINDOWS = 40
TINT_WINDOW_S = 3.0
TINT_PAIR_GAP = 2
TINT_MOVE_PX = 1.5            # the self moved at most this (widget px) between the pair's frames
TINT_MAX_PAIRS = 60           # audio pairs kept per session, in window order
#: `--tint-cal` scans each stored ally Clove death this long (or to the round's end) for its circle.
CLOVE_SCAN_MS = 60000.0
#: A tint alpha under this does not count as tinted floor in the statistics.
TINT_MIN = 0.02
TCAL: dict = {}
_TRACKS: dict = {}


def _reload_ratio() -> float:
    """audio_circle's reload/footstep radius ratio on the Iso capture (`score --per-frame`)."""
    j = json.loads((ac.PF_OUT / "per_frame.json").read_text(encoding="utf-8"))
    return float(j["small_r_median"]) / float(j["large_r_median"])


def session_sizes(sid: str) -> dict | None:
    """`{"footstep", "reload"}` px for this session from `--tint-cal`, or None when it measured none."""
    got = (TCAL.get("audio_sizes") or {}).get(sid)
    if not got or got.get("footstep") is None:
        return None
    return {"footstep": float(got["footstep"]), "reload": float(got["footstep"]) * float(TCAL["reload_ratio"])}


def audio_fit(S, crop: np.ndarray, me, sc: float, sizes: dict | None) -> dict:
    """The self audio circle on one frame by audio_circle's per-frame fit (`frame_fit`: the ring-score
    argmax over every scanned radius and a +-4 px centre grid round the stored self, then
    `clove_circle.fit_circle`), and whether it counts: ring score, good fit, ring contrast, a centre within
    AUDIO_CENTRE_TOL_PX of the stored self, a white rim, and a radius of one of the session's two sizes.
    Every failed test is named in `reason`."""
    f = ac.frame_fit(S, crop, me)
    if f is None:
        return {"observed": False, "reason": "no ring curve (the self is off the widget)"}
    f = dict(f)
    f["score"] = f["best"]
    f["centre_off"] = float(math.hypot(f["cx"] - me[0], f["cy"] - me[1]))
    f["bgr_step"] = [round(float(v), 2) for v in rim_steps(crop, S.static, (f["cx"], f["cy"]), f["r"])]
    f["white"] = whiteness(np.array(f["bgr_step"]))
    why = []
    if f["best"] < SRC_T:
        why.append(f"ring score {f['best']:.1f} under {SRC_T:g}")
    if f["inliers"] < SRC_FIT_INLIERS or f["rms"] >= SRC_FIT_RMS:
        why.append(f"fit inliers {f['inliers']:.2f} rms {f['rms']:.2f}")
    if f["ring"] < ac.T_LO:
        why.append(f"fitted ring {f['ring']:.1f} under {ac.T_LO:g}")
    tol = AUDIO_CENTRE_TOL_PX * sc
    if f["centre_off"] > tol:
        why.append(f"centre {f['centre_off']:.1f} px from the stored self, over {tol:.1f}")
    if not f["white"] >= AUDIO_WHITE_MIN:
        why.append(f"rim white {f['white']:.2f} under {AUDIO_WHITE_MIN:g}")
    f["size"] = "unknown: the session measured no size"
    if sizes is not None:
        st = AUDIO_SIZE_TOL_PX * sc
        if abs(f["r"] - sizes["footstep"]) <= st:
            f["size"] = "footstep"
        elif abs(f["r"] - sizes["reload"]) <= st:
            f["size"] = "reload"
        else:
            f["size"] = None
            why.append(f"radius {f['r']:.1f} is neither size ({sizes['footstep']:.1f}, {sizes['reload']:.1f})")
    f["observed"] = not why
    f["reason"] = "; ".join(why) or None
    return f


def _ally_tracks(sid: str) -> list[dict]:
    """Each stored ally track (events/team_vision) with its first and last frame."""
    if sid in _TRACKS:
        return _TRACKS[sid]
    spans: dict = {}
    p = sem.STORE / "events" / "team_vision" / f"{sid}.jsonl"
    for line in (p.open(encoding="utf-8") if p.is_file() else []):
        if '"kind":"frame"' not in line:
            continue
        e = json.loads(line)
        for ic in e.get("icons") or []:
            if ic.get("role") != "ally" or ic.get("interpolated"):
                continue
            sp = spans.get(ic["track_id"])
            t = float(e["t_ms"])
            if sp is None:
                spans[ic["track_id"]] = sp = {"track_id": ic["track_id"], "t_first": t, "x_first": ic["x"],
                                              "y_first": ic["y"]}
            sp.update(t_last=t, x_last=ic["x"], y_last=ic["y"])
    _TRACKS[sid] = list(spans.values())
    return _TRACKS[sid]


def clove_death_points(sid: str, t_death: float, sc: float) -> list[dict]:
    """Candidate death points of an ally Clove who died at `t_death` (stored death data): the last
    positions of the stored ally tracks that end then (CLOVE_TRACK_WINDOW_MS) with no successor."""
    tr = _ally_tracks(sid)
    out = []
    for sp in tr:
        if not (t_death + CLOVE_TRACK_WINDOW_MS[0] <= sp["t_last"] <= t_death + CLOVE_TRACK_WINDOW_MS[1]):
            continue
        if any(o is not sp and 0.0 < o["t_first"] - sp["t_last"] <= CLOVE_GAP_MS
               and math.hypot(o["x_first"] - sp["x_last"], o["y_first"] - sp["y_last"]) <= CLOVE_SAME_TRACK_PX * sc
               for o in tr):
            continue
        out.append({"x": float(sp["x_last"]), "y": float(sp["y_last"]), "track_id": sp["track_id"],
                    "t_last_ms": sp["t_last"]})
    return out


def is_self_audio(f: dict, me, sizes: dict | None, sc: float) -> bool:
    """Whether a circle is the self audio circle by the other channel that observes it: centred within
    AUDIO_CENTRE_TOL_PX of the stored self and at the session's footstep or reload size. A Clove fit near a
    death point the self stands on finds this circle, since only the self draws one round itself."""
    if me is None or sizes is None:
        return False
    if math.hypot(f["cx"] - me[0], f["cy"] - me[1]) > AUDIO_CENTRE_TOL_PX * sc:
        return False
    return any(abs(f["r"] - sizes[k]) <= AUDIO_SIZE_TOL_PX * sc for k in ("footstep", "reload"))


def clove_fit(d: np.ndarray, pts: list[dict], radii: np.ndarray, sc: float, me=None,
              sizes: dict | None = None) -> dict | None:
    """The best circle centred near any death point: audio_circle's ring-score grid (+-4 px) at base
    centres every 4 px within CLOVE_REACH_PX - 4 of the point, the peak over centre and radius, then
    `clove_circle.fit_circle`. Observed when the peak and the fitted ring clear the cuts, the fit is good
    and the fitted centre stays within CLOVE_REACH_PX of that point. With the session's audio sizes known,
    radii within AUDIO_SIZE_TOL_PX of them leave the search: a Clove fit near a death point the self stands
    on otherwise finds the self audio circle (the 0.5.0 --tint-cal first run: 12 and 22 frames at 74.7 px
    after the 913.5 s and 1343.5 s deaths on e37fdeca944f, where the Clove circle is 96.8 px), and a frame
    with both keeps the Clove's. A circle whose exact fit lands at an audio size again, or that passes
    `is_self_audio`, is refused (the second run: 6 frames at 74.77 px after 1343.5 s, the fit sliding back
    from an excluded radius)."""
    reach = CLOVE_REACH_PX * sc
    if sizes is not None:
        away = np.all([np.abs(radii - sizes[k]) > AUDIO_SIZE_TOL_PX * sc for k in ("footstep", "reload")], axis=0)
        radii = radii[away]
    n = int(max(0.0, reach - 4.0) // 4.0)
    best = (-np.inf, None, None, None)
    for p in pts:
        for bx in range(-n, n + 1):
            for by in range(-n, n + 1):
                b = (p["x"] + 4.0 * bx, p["y"] + 4.0 * by)
                cur = ac.ring_curve(d, b, radii)
                if not np.isfinite(cur).any():
                    continue
                o, k = np.unravel_index(int(np.nanargmax(np.nan_to_num(cur, nan=-1e9))), cur.shape)
                if cur[o, k] > best[0]:
                    best = (float(cur[o, k]), (b[0] + ac.OFFS[o][0], b[1] + ac.OFFS[o][1]), float(radii[k]), p)
    if best[1] is None:
        return None
    f = cc.fit_circle(d, best[1], best[2], win=6.0)
    p = best[3]
    f.update(score=best[0], ring=cc.ringscore(d, (f["cx"], f["cy"]), f["r"]), death_x=p["x"], death_y=p["y"],
             track_id=p["track_id"], centre_off_death=float(math.hypot(f["cx"] - p["x"], f["cy"] - p["y"])))
    f["observed"] = bool(f["score"] >= SRC_T and f["inliers"] >= SRC_FIT_INLIERS and f["rms"] < SRC_FIT_RMS
                         and f["ring"] >= ac.T_LO and f["centre_off_death"] <= reach)
    f["self_audio"] = is_self_audio(f, me, sizes, sc) or (sizes is not None and any(
        abs(f["r"] - sizes[k]) <= AUDIO_SIZE_TOL_PX * sc for k in ("footstep", "reload")))
    if f["self_audio"]:
        f["observed"] = False
    return f


def find_sources(sid: str, t_ms: float, crop: np.ndarray, sc: float) -> dict:
    """The non-cone light sources this frame shows (0.5.0), `{"drawn", "notes", "rejected"}`.

    - audio: audio_circle's per-frame fit round the stored self position (`audio_fit`), which counts only
      centred on the self icon and at one of the session's two sizes;
    - clove: while an ally Clove is dead in this round by the stored death data, the best circle centred
      near the death point (`clove_death_points`, `clove_fit`); with no stored track ending at the death,
      0.4.0's free search over the widget, flagged as the surprise path;
    - ability: 0.4.0's, round a labelled Trademark, Chokehold or Sonic Sensor icon within 1 s.
    `rejected` keeps the fits that failed, with their reasons, for the sheet.
    """
    if SOURCE_STATE == "free":
        return find_sources_v4(sid, t_ms, crop, sc)
    out = {"drawn": [], "notes": {}, "rejected": []}
    if not SOURCES:
        return out
    S, why = _ac_session(sid)
    if S is None:
        out["notes"] = {k: why for k in SOURCES}
        return out
    if S.static.shape[:2] != crop.shape[:2]:
        out["notes"] = {k: f"crop {crop.shape[:2]} is not the baked frame {S.static.shape[:2]}" for k in SOURCES}
        return out
    d = S.diff(crop)
    audio = None
    if "audio" in SOURCES:
        me, _drawn = S.self_at(t_ms)
        if me is None:
            out["notes"]["audio"] = "no stored self position within +-200 ms"
        else:
            f = audio_fit(S, crop, me, sc, session_sizes(sid))
            keep = {k: f[k] for k in ("cx", "cy", "r", "score", "ring", "rms", "inliers", "centre_off", "white",
                                      "bgr_step", "size") if k in f}
            if f["observed"]:
                audio = {"kind": "audio", **keep, "self_x": me[0], "self_y": me[1]}
                out["drawn"].append(audio)
            else:
                out["notes"]["audio"] = "not observed (" + f["reason"] + ")"
                if "cx" in f:
                    out["rejected"].append({"kind": "audio", **keep, "reason": f["reason"]})
    if "clove" in SOURCES:
        td_ = _clove_dead_at(sid, t_ms)
        if td_ is None:
            out["notes"]["clove"] = "no ally Clove dead in this round (stored death data)"
        else:
            pts = clove_death_points(sid, td_, sc)
            if pts:
                me_c, _ = S.self_at(t_ms)
                f = clove_fit(d, pts, S.radii, sc, me_c, session_sizes(sid))
                path = f"death point from stored ally track {'/'.join(str(p['track_id']) for p in pts)}"
            else:
                f, path = None, "no stored ally track ends at the death: free search (surprise path)"
                score, where = _free_circle(d, S.radii[::2], audio)
                if where is not None and score >= SRC_T:
                    f = cc.fit_circle(d, where[:2], where[2], win=6.0)
                    f.update(score=score, ring=cc.ringscore(d, (f["cx"], f["cy"]), f["r"]), death_x=None,
                             death_y=None, track_id=None, centre_off_death=None)
                    f["observed"] = bool(f["inliers"] >= SRC_FIT_INLIERS and f["rms"] < SRC_FIT_RMS
                                         and f["ring"] >= ac.T_LO)
            same = f is not None and audio is not None and (
                math.hypot(f["cx"] - audio["cx"], f["cy"] - audio["cy"]) <= SRC_SAME_PX * sc
                and abs(f["r"] - audio["r"]) <= SRC_SAME_PX * sc)
            keep = {} if f is None else {k: f[k] for k in ("cx", "cy", "r", "score", "ring", "rms", "inliers",
                                                           "death_x", "death_y", "track_id", "centre_off_death")}
            if f is not None and f["observed"] and not same:
                out["drawn"].append({"kind": "clove", **keep, "death_t_ms": td_, "path": path})
            else:
                out["notes"]["clove"] = (f"ally Clove dead since {td_ / 1000:.1f} s; {path}; no circle"
                                         + ("" if f is None else (
                                             f" (score {f['score']:.1f} ring {f['ring']:.1f} rms {f['rms']:.2f} "
                                             f"inliers {f['inliers']:.2f} r {f['r']:.1f}"
                                             + (f" off death {f['centre_off_death']:.1f}"
                                                if f.get("centre_off_death") is not None else "")
                                             + (" same as audio" if same else "")
                                             + (" the self audio circle" if f.get("self_audio") else "") + ")")))
                if f is not None:
                    out["rejected"].append({"kind": "clove", **keep, "reason": out["notes"]["clove"]})
    if "ability" in SOURCES:
        v4 = find_sources_v4(sid, t_ms, crop, sc, kinds=("ability",))
        out["drawn"] += v4["drawn"]
        out["notes"].update(v4["notes"])
    return out


def tint_maps(src: dict, shape, sc: float):
    """`(A, C, band)` for the drawn sources: the combined opacity (H, W), the premultiplied tint colour
    (H, W, 3) in 0..1 (the background becomes `(1 - A) bg + C`), and the rim band (|dr| <= 3 px) of any
    source with no measured profile at this scale, which leaves the comparison."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    A = np.zeros(shape, np.float32)
    C = np.zeros(shape + (3,), np.float32)
    band = np.zeros(shape, bool)
    for c in src["drawn"]:
        dr = np.hypot(xx - c["cx"], yy - c["cy"]) - c["r"]
        prof = (TCAL.get("profiles") or {}).get(f"{c['kind']}@{_skey(sc)}")
        if prof is None or prof.get("alpha") is None:
            band |= np.abs(dr) <= 3.0
            continue
        al = np.clip(np.asarray(prof["alpha"], np.float32), 0.0, 1.0)
        a = al[np.searchsorted(TINT_EDGES, dr, side="right")]
        a[dr >= TINT_OUTER] = 0.0
        W = np.asarray(prof["W_bgr"], np.float32) / 255.0
        C = C * (1.0 - a)[..., None] + a[..., None] * W[None, None]
        A = 1.0 - (1.0 - A) * (1.0 - a)
    return A, C, band


def scene_sources(r: dict | None, sid: str, t_ms: float, crop: np.ndarray, sc: float):
    """`(src, srcm, tint)`: the frame's drawn sources (cached on the row when given), the floor they
    cover (0.4.0: each disc; 0.5.0: tinted over TINT_MIN or in an unmeasured rim band), and 0.5.0's
    tint maps (None in 0.4.0 or with nothing drawn)."""
    src = item_sources(r, sid, t_ms, crop, sc) if r is not None else find_sources(sid, float(t_ms), crop, sc)
    if not src["drawn"]:
        return src, None, None
    if SOURCE_STATE == "tint":
        A, C, band = tint_maps(src, crop.shape[:2], sc)
        return src, (A > TINT_MIN) | band, (A, C, band)
    return src, source_mask(src, crop.shape[:2]), None


def item_sources(r: dict, sid: str, t_ms: float, crop: np.ndarray, sc: float) -> dict:
    """`find_sources`, cached on the row."""
    if "_src" not in r:
        r["_src"] = find_sources(sid, float(t_ms), crop, sc)
    return r["_src"]


class RGBScene:
    """One neighbourhood in RGB: the crop and the two-state baked background over a window, and the icons.

    Poses are `(x, y, deg, 0, 0)`: no gains, so a misplaced lobe cannot be dimmed away.
    """

    def __init__(self, crop: np.ndarray, s, icons: list[dict], sc: float, cal: dict,
                 outside: list[dict] | None = None, light_costs: dict | None = None,
                 src: np.ndarray | None = None, tint=None):
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
        self.tinted = tint is not None
        if tint is not None:
            # 0.5.0: the drawn sources tint either floor state, `(1 - A) bg + C`, under every icon.
            A, C, band = tint
            At = torch.tensor(A[y0:y1, x0:x1].ravel(), dtype=torch.float32, device=DEV)
            Ct = torch.tensor(C[y0:y1, x0:x1].reshape(-1, 3).T.copy(), dtype=torch.float32, device=DEV)
            self.bg = self.bg * (1.0 - At)[None, None] + Ct[None]
            if band.any():
                # a source with no measured profile at this scale: its rim band leaves the comparison
                keep &= ~band[y0:y1, x0:x1]
                self.keep_np = keep
                self.keep = torch.tensor(keep.ravel(), dtype=torch.float32, device=DEV)
        sdw = torch.tensor(sd[y0:y1, x0:x1].ravel(), dtype=torch.float32, device=DEV)
        self.sig = torch.sqrt(scal["sigma_noise"] ** 2 + sdw ** 2)                           # (P,)
        self.cls_cal = {c: scal["classes"][c] for c in {ic["cls"] for ic in icons}}
        self.light = (Light(s, self.win, icons, outside or [], sc, light_costs, src)
                      if LIGHT == "pose" and s.inputs.light is not None else None)

    def _one(self, i: int, pose):
        ic = self.icons[i]
        x, y, deg = (torch.tensor([[v]], dtype=torch.float32, device=DEV) for v in pose[:3])
        O, C, own = rgb_layers(ic["cls"], self.sc, self.cls_cal[ic["cls"]], self.px, self.py, x, y,
                               torch.deg2rad(deg))
        return O[0], C[0], own[0]

    def _held(self, poses, skip=None):
        """`(L, free, extra)`: the held light, the free pixels and (0.6.0 "boxes") the jump costs held."""
        if self.light is None:
            return None
        return (*self.light.held(poses, skip), self.light.extra(poses, skip))

    def stack(self, order, poses, skip=None):
        """`(K, Wn, LF)`: the composite (2, 3, P), one per floor state, the compared weight (P,) and the
        light `(L, free)` (None in 0.2.0). With `skip`, the layers below and above icon `skip` and the
        light the others cast: `(Kb, Wb, T, Ca, Wa, LF)`."""
        K, Wn = self.bg.clone(), torch.ones(self.px.shape[0], device=DEV)
        if skip is None:
            for i in order:
                O, C, own = self._one(i, poses[i])
                K = (1 - O)[None, None] * K + C[None]
                Wn = (1 - O) * Wn + O * (1 - own)
            return K, Wn, self._held(poses)
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
        return K, Wn, T, Ca, Wa, self._held(poses, skip)

    def predict(self, K):
        """Blurred prediction (N, 2, 3, P) of composites (N, 2, 3, P)."""
        N = K.shape[0]
        return blur(K.reshape(N * 2, 3, self.H, self.W), self.k).reshape(N, 2, 3, -1)

    def _err2(self, K):
        """Per-pixel error (N, 2, P) in sigma^2 for each floor state, before truncation."""
        return (((self.obs[None, None] - self.predict(K)) / self.sig) ** 2).sum(2)

    def compared(self, Wn, free):
        """(N, P) bool: the compared known floor, as `light_stats` counts it."""
        return (self.keep > 0)[None] & (Wn > 0.5) & self.light.known[None] & ~free[None]

    def _loss(self, K, Wn, LF=None):
        """(N,) loss. `LF` is `(L, free)` or `(L, free, extra)`, `extra` a float or (N,) of jump costs."""
        e2 = self._err2(K)
        if LF is None:
            e = e2.min(1).values
        elif self.light.regions:
            e = self.light.region_err(e2, LF[0], LF[1], self.compared(Wn, LF[1]))
        else:
            e = self.light.err(e2, LF[0], LF[1])
        e = e.clamp(max=TAU_SIG ** 2)
        lo = (self.keep[None] * (Wn * e + (1 - Wn) * OWN_COST)).sum(-1)
        if LF is not None and len(LF) > 2:
            lo = lo + LF[2]
        return lo

    def loss_of(self, KWL) -> float:
        K, Wn, LF = KWL
        return float(self._loss(K[None], Wn[None], None if LF is None else (LF[0][None], *LF[1:]))[0])

    def search(self, i: int, order, poses, cands: np.ndarray):
        ic = self.icons[i]
        Kb, Wb, T, Ca, Wa, LF = self.stack(order, poses, skip=i)
        out, gs = [], []
        for a in range(0, len(cands), CHUNK // 4):
            cc = torch.tensor(cands[a:a + CHUNK // 4], dtype=torch.float32, device=DEV)
            O, C, own = rgb_layers(ic["cls"], self.sc, self.cls_cal[ic["cls"]], self.px, self.py,
                                   cc[:, :1], cc[:, 1:2], torch.deg2rad(cc[:, 2:3]))
            K = T[None, None, None] * ((1 - O)[:, None, None] * Kb[None] + C[:, None]) + Ca[None, None]
            Wn = T[None] * ((1 - O) * Wb[None] + O * (1 - own)) + Wa[None]
            if LF is None:
                out.append(self._loss(K, Wn))
                gs.append(torch.zeros(len(cc), 2, device=DEV))
                continue
            Lh, free, xh = LF
            cs = cands[a:a + CHUNK // 4]
            if ic["cls"] != "enemy":        # an enemy casts no team light
                L = self.light.cones(cs) | Lh[None]
            else:
                L = Lh[None].expand(len(cc), -1)
            lo = self._loss(K, Wn, (L, free, xh))
            g = torch.zeros(len(cc), 2, device=DEV)
            if self.light.boxes and ic["cls"] != "enemy":
                # 0.6.0: the caster standing (every box blocks) or jumping (every crossed box passes) at
                # BOX_JUMP_COST; the cheaper state wins, its flag carried in the pose's slot 3.
                cr = self.light.crosses(cs)
                if cr.any():
                    sel = np.nonzero(cr)[0]
                    st = torch.tensor(sel, device=DEV)
                    Lj = self.light.cones(cs[sel], jump=True) | Lh[None]
                    lj = self._loss(K[st], Wn[st], (Lj, free, xh + BOX_JUMP_COST))
                    win = lj < lo[st]
                    lo[st] = torch.where(win, lj, lo[st])
                    g[st, 0] = win.float()
            out.append(lo)
            gs.append(g)
        return torch.cat(out).cpu().numpy(), torch.cat(gs).cpu().numpy()

    def light_stats(self, order, poses) -> dict:
        """At fixed poses, over compared known floor: pixels predicted lit, and those read against the
        prediction at its cost (`unexplained`: lit where no cone reaches; `missing`: unlit inside a cone)."""
        if self.light is None:
            return {}
        K, Wn, (L, free, _x) = self.stack(order, poses)
        e2 = self._err2(K[None])[0]
        comp = (self.keep > 0) & (Wn > 0.5) & self.light.known & ~free
        unex = comp & ~L & (e2[1] + self.light.c_u < e2[0])
        miss = comp & L & (e2[0] + self.light.c_m < e2[1])
        extra = {}
        if self.light.regions:
            # 0.6.0: the region-decided light; the pixel counts above stay the rule's, comparable with 0.5.0.
            S = self.light.region_state(e2[None], L[None], comp[None])[0]
            lab = self.light.regions_of(comp[None], L[None])[0]
            ur, mr = comp & ~L & S, comp & L & ~S
            extra = {"unexplained_region_n": int(ur.sum()), "missing_region_n": int(mr.sum()),
                     "regions_n": int(torch.unique(lab[comp]).numel()) if comp.any() else 0,
                     "unexplained_regions": int(torch.unique(lab[ur]).numel()) if ur.any() else 0,
                     "missing_regions": int(torch.unique(lab[mr]).numel()) if mr.any() else 0}
        # The same poses with the sources taken away: what the drawn sources explain. `floor_nosrc_n` is
        # the compared floor without them (0.3.0's), the common denominator of both unexplained shares.
        Lc, free_c = self.light.held(poses, sources=False)
        comp_c = (self.keep > 0) & (Wn > 0.5) & self.light.known & ~free_c
        unex_nosrc = comp_c & ~Lc & (e2[1] + self.light.c_u < e2[0])
        return {"floor_n": int(comp.sum()), "lit_pred_n": int((comp & L).sum()), "unexplained_n": int(unex.sum()),
                "missing_n": int(miss.sum()), "free_n": int(((self.keep > 0) & self.light.known & free).sum()),
                "source_n": int((comp_c & self.light.src).sum()), "unexplained_nosrc_n": int(unex_nosrc.sum()),
                "floor_nosrc_n": int(comp_c.sum()), **extra}

    def box_outcomes(self, order, poses) -> list[dict]:
        """0.6.0 "boxes": per caster whose cone crosses a box, its winning state and, per crossed box,
        the window pixels past it, the compared ones, and how many of those read lit. A box whose
        compared pixels mostly read lit supports "passes" (short, or its caster raised); mostly unlit,
        "blocks" (tall, or its caster standing)."""
        if self.light is None or not self.light.boxes:
            return []
        K, Wn, (L, free, _x) = self.stack(order, poses)
        e2 = self._err2(K[None])[0]
        comp = self.compared(Wn[None], free)[0]
        read = self.light.read_lit(e2[None])[0]
        rows = self.light.jump_report(poses)
        for row in rows:
            boxes = []
            for b, m in row.pop("_boxes").items():
                c = m & comp
                n, lit = int(c.sum()), int((c & read).sum())
                boxes.append({"box_id": b, "px": int(m.sum()), "compared": n, "read_lit": lit,
                              "supports": None if n < LIGHT_FIRE_PX else ("passes" if lit >= n / 2 else "blocks")})
            row["boxes"] = boxes
        return rows

    def full_images(self, order, poses, shape):
        """Prediction, weight, residual magnitude and light code as crop-sized arrays. The prediction's
        floor is the pose-predicted state (0.3.0) or the cheaper one (0.2.0); the light code is 1 predicted
        lit, 2 unexplained light, 3 missing light, 4 free, 5 lit by a drawn source (0.4.0), on known floor
        (0 elsewhere)."""
        K, Wn, LF = self.stack(order, poses)
        pred = self.predict(K[None])[0]                                      # (2, 3, P)
        e2 = (((self.obs[None] - pred) / self.sig) ** 2).sum(1)              # (2, P)
        code = torch.zeros(e2.shape[1], device=DEV)
        if LF is None:
            j = e2.argmin(0)
            e = e2.min(0).values
        else:
            L, free = LF[0], LF[1]
            j = L.long()
            e = self.light.err(e2[None], L[None], free)[0]
            kn = self.light.known
            code[kn & L] = 1
            code[kn & ~L & ~free & (e2[1] + self.light.c_u < e2[0])] = 2
            code[kn & L & ~free & (e2[0] + self.light.c_m < e2[1])] = 3
            code[kn & free] = 4
            code[kn & self.light.src] = 5
            if self.light.regions:
                # 0.6.0: a whole region decided lit where no cone reaches (6), or unlit inside one (7)
                comp = self.compared(Wn[None], free)[0]
                S = self.light.region_state(e2[None], L[None], comp[None])[0]
                e = self.light.region_err(e2[None], L[None], free, comp[None])[0]
                code[comp & ~L & S] = 6
                code[comp & L & ~S] = 7
            if self.light.boxes:
                # 0.6.0: light a jumping caster casts only through a box (8)
                code[kn & L & ~self.light.held_standing(poses)] = 8
        best = torch.where(j[None] == 0, pred[0], pred[1])
        res = e.clamp(max=TAU_SIG ** 2).sqrt()
        x0, y0, x1, y1 = self.win
        h, w = shape
        P = np.zeros((h, w, 3), np.uint8)
        R = np.zeros((h, w), np.float32)
        Wimg = np.zeros((h, w), np.float32)
        Cimg = np.zeros((h, w), np.uint8)
        P[y0:y1, x0:x1] = np.clip(best.T.reshape(self.H, self.W, 3).cpu().numpy() * 255, 0, 255).astype(np.uint8)
        R[y0:y1, x0:x1] = (res * self.keep).reshape(self.H, self.W).cpu().numpy()
        Wimg[y0:y1, x0:x1] = (Wn * self.keep).reshape(self.H, self.W).cpu().numpy()
        Cimg[y0:y1, x0:x1] = (code * self.keep).reshape(self.H, self.W).cpu().numpy().astype(np.uint8)
        return P, R, Wimg, Cimg


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


def light_costs(sc: float) -> dict | None:
    """The unexplained- and missing-light costs at this widget scale (`--light-cal`), None in 0.2.0."""
    if LIGHT != "pose":
        return None
    got = LCAL.get("scales", {}).get(_skey(sc))
    if got is None:
        raise SystemExit(f"no light calibration at scale {_skey(sc)}: run --light-cal")
    return got


def _cost(q: float) -> float:
    """`2 ln((1-q)/q)`: the loss (sigma^2 units, -2 log likelihood) of a floor state read against the
    prediction with rate `q`, clamped to [0, TAU_SIG^2]."""
    q = min(max(q, 1e-4), 0.5)
    return float(min(LIGHT_COST_MAX, 2.0 * math.log((1.0 - q) / q)))


def light_calibrate(sess, label_times: dict) -> dict:
    """The light costs per widget scale, from confident owner teardrop poses on unlabelled frames.

    The same isolated team icons as `calibrate` (at least `CAL_AWAY_MS` from any
    labelled instant). Each icon's cone is cast from the owner's pose, every
    other team icon of the frame from its own teardrop pose; the compared
    pixels are the scene window's known floor outside every team icon's
    footprint (a disc of the apex's reach grown by `cone_origin.PAD`) and the
    free pixels. `q_u` is the share of pixels no cone reaches that the lit
    state explains better, `q_m` the share of cone pixels the unlit state
    explains better. It also measures P9 with the owner's lit decision
    (`lighting.raw_lit`) and the cut (360-degree cast cut to the wedge)
    against the owner's own cone cast.

    0.4.0 draws the frame's non-cone sources (`find_sources`) first; with
    `SOURCE_STATE = "free"` their discs leave the compared floor, so `q_u`
    and `q_m` are the rates outside them and `q_u_nosrc`, `q_m_nosrc` the
    rates on 0.3.0's floor. `source_lit_nearer_share` and
    `source_raw_lit_share` say how often the floor inside a disc reads lit.
    It also measures the FLOOR-COLOUR ERROR on 0.3.0's compared floor and
    predicted state: the RGB distance (0-255 units) between the crop and the
    blurred baked floor in the predicted state, over all of them, over those whose predicted state is
    also the nearer one (`right`: the state is right, so what is left is the
    colour), per predicted state, the signed grey bias (crop minus
    prediction), and the share whose error reaches the truncation `TAU_SIG`.
    """
    icons = calibration_icons(sess, label_times)
    acc = defaultdict(lambda: defaultdict(float))
    fe = defaultdict(lambda: defaultdict(list))
    sessions = defaultdict(set)
    for (cls, skey), v in sorted(icons.items()):
        if cls == "enemy":
            continue
        for ic in v:
            s, crop, sc = ic["_s"], ic["_crop"], ic["sc"]
            team = ff.team_icons(s, crop, sc)
            scene_ic = [{"cls": cls, "x0": ic["x"], "y0": ic["y"]}]
            outside = outside_icons(team, sc, scene_ic)
            src, srcm, tint = scene_sources(None, ic["sid"], ic["t_ms"], crop, sc)
            scene = RGBScene(crop, s, scene_ic, sc, CAL, outside=outside, light_costs={"c_u": 0.0, "c_m": 0.0},
                             src=srcm, tint=tint)
            lt = scene.light
            pose = (ic["x"], ic["y"], ic["deg"], 0.0, 0.0)
            K, Wn, (L, free, *_x) = scene.stack([0], {0: pose})
            e2t = scene._err2(K[None])[0]
            e2 = e2t.cpu().numpy()
            pred = scene.predict(K[None])[0].cpu().numpy()                     # (2, 3, P), 0..1
            obs = scene.obs.cpu().numpy()
            Lc, free_c = (x.cpu().numpy() for x in lt.held({0: pose}, sources=False))
            srcw = lt.src.cpu().numpy()
            own = lt.pose_cone(pose).cpu().numpy()
            Ln, freen = L.cpu().numpy(), free.cpu().numpy()
            foot = np.zeros(len(lt.xx), bool)
            for qx, qy in [(ic["x"], ic["y"])] + [(o["x"], o["y"]) for o in team]:
                foot |= np.hypot(lt.xx - qx, lt.yy - qy) <= td.L * sc + co.PAD
            x0, y0, x1, y1 = scene.win
            raw = lighting.raw_lit(crop, s.ref)[y0:y1, x0:x1].ravel()
            kk = scene.keep_np.ravel()
            comp = kk & lt.known_np & ~freen & ~foot
            comp_c = kk & lt.known_np & ~free_c & ~foot                         # 0.3.0's compared floor
            a = acc[skey]
            sessions[skey].add(ic["sid"])
            a["icons"] += 1
            a["own_in_n"] += (comp & own).sum()
            a["own_in_lit"] += (comp & own & raw).sum()
            a["dark_n"] += (comp & ~Ln).sum()
            a["dark_unlit"] += (comp & ~Ln & ~raw).sum()
            a["dark_alt"] += (comp & ~Ln & (e2[1] < e2[0])).sum()
            a["cone_n"] += (comp & Ln).sum()
            a["cone_alt"] += (comp & Ln & (e2[0] < e2[1])).sum()
            a["dark_nosrc_n"] += (comp_c & ~Lc).sum()
            a["dark_nosrc_alt"] += (comp_c & ~Lc & (e2[1] < e2[0])).sum()
            a["cone_nosrc_n"] += (comp_c & Lc).sum()
            a["cone_nosrc_alt"] += (comp_c & Lc & (e2[0] < e2[1])).sum()
            a["src_n"] += (comp_c & srcw).sum()
            a["src_lit_nearer"] += (comp_c & srcw & (e2[1] < e2[0])).sum()
            a["src_raw_lit"] += (comp_c & srcw & raw).sum()
            a["icons_with_source"] += bool(src["drawn"])
            for c in src["drawn"]:
                a[f"drawn_{c['kind']}"] += 1
            st = Lc.astype(int)                                                 # 0.3.0's predicted state
            idx = np.nonzero(comp_c)[0]
            pp = pred[st[idx], :, idx]                                          # (n, 3)
            dif = (obs[:, idx].T - pp) * 255.0
            f = fe[skey]
            f["err"].append(np.sqrt((dif ** 2).sum(1)))
            f["grey"].append(dif.mean(1))
            f["lit"].append(Lc[idx])
            f["src"].append(srcw[idx])
            f["right"].append(e2[st[idx], idx] <= e2[1 - st[idx], idx])
            f["sat"].append(e2[st[idx], idx] >= TAU_SIG ** 2)
            m = cone.raycast(s.passable, ic["x"], ic["y"], ic["deg"], visible=s.floor,
                             max_r=lt.max_r)[y0:y1, x0:x1].ravel()
            a["cut_union_px"] += (kk & (m | own)).sum()
            a["cut_diff_px"] += (kk & (m != own)).sum()
    out = {"version": VERSION, "made_from": "confident isolated owner teardrops (as calibrate) on unlabelled "
           f"frames, >= {CAL_AWAY_MS:.0f} ms from any labelled instant; cones by cone.raycast from each "
           "team icon's teardrop pose; costs 2 ln((1-q)/q); drawn sources " + (",".join(SOURCES) or "none"),
           "scales": {}}
    for skey, a in sorted(acc.items()):
        q_u = a["dark_alt"] / max(a["dark_n"], 1)
        q_m = a["cone_alt"] / max(a["cone_n"], 1)
        vals = {"icons": int(a["icons"]), "q_u": round(q_u, 4), "q_m": round(q_m, 4),
                "c_u": round(_cost(q_u), 4), "c_m": round(_cost(q_m), 4),
                "own_cone_lit_share": round(a["own_in_lit"] / max(a["own_in_n"], 1), 4),
                "own_cone_px": int(a["own_in_n"]),
                "no_cone_unlit_share": round(a["dark_unlit"] / max(a["dark_n"], 1), 4),
                "no_cone_px": int(a["dark_n"]),
                "cut_disagree_share": round(a["cut_diff_px"] / max(a["cut_union_px"], 1), 4),
                "q_u_nosrc": round(a["dark_nosrc_alt"] / max(a["dark_nosrc_n"], 1), 4),
                "q_m_nosrc": round(a["cone_nosrc_alt"] / max(a["cone_nosrc_n"], 1), 4),
                "icons_with_source": int(a["icons_with_source"]),
                **{k: int(a[k]) for k in ("drawn_audio", "drawn_clove", "drawn_ability")},
                "source_px": int(a["src_n"]),
                "source_lit_nearer_share": round(a["src_lit_nearer"] / max(a["src_n"], 1), 4),
                "source_raw_lit_share": round(a["src_raw_lit"] / max(a["src_n"], 1), 4),
                "sessions": sorted(sessions[skey])}
        f = {k: np.concatenate(x) for k, x in fe[skey].items()}
        if len(f.get("err", [])):
            med = lambda x: round(float(np.median(x)), 2) if len(x) else None  # noqa: E731
            lit, right, srcp = f["lit"], f["right"], f["src"]
            vals.update({
                "floor_px": int(len(f["err"])),
                "floor_err_median": med(f["err"]),
                "floor_err_p90": round(float(np.percentile(f["err"], 90)), 2),
                "floor_err_right_median": med(f["err"][right]),
                "floor_right_share": round(float(right.mean()), 4),
                "floor_err_lit_median": med(f["err"][lit]),
                "floor_err_unlit_median": med(f["err"][~lit]),
                "floor_err_source_median": med(f["err"][srcp]),
                "floor_grey_bias_lit_median": med(f["grey"][lit & ~srcp]),
                "floor_grey_bias_unlit_median": med(f["grey"][~lit]),
                "floor_grey_bias_source_median": med(f["grey"][srcp]),
                "floor_sat_share": round(float(f["sat"].mean()), 4),
                "floor_sat_share_right": round(float(f["sat"][right].mean()), 4) if right.any() else None,
                "noise_sigma_255": round(float(CAL["scales"][skey]["sigma_noise"]) * 255.0, 2)})
        out["scales"][skey] = vals
        print(f"  light calibration {skey}: {vals}", flush=True)
    return out


# ---------------------------------------------------------------- 0.5.0: measuring the tint (unlabelled frames)

def _pair_pixels(c_off, c_on, circ, me, sc, lit_off=None):
    """The pixels of a tint pair within TINT_OUTER of the circle, away from the self icon:
    `(off (n, 3), on (n, 3), dr (n,), lit (n,) or None)`, 0..255."""
    h, w = c_on.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    dr = np.hypot(xx - circ["cx"], yy - circ["cy"]) - circ["r"]
    m = dr < TINT_OUTER
    if me is not None:
        m &= np.hypot(xx - me[0], yy - me[1]) > TINT_ICON_PX * sc
    return (c_off[m].astype(np.float32), c_on[m].astype(np.float32), dr[m].astype(np.float32),
            None if lit_off is None else lit_off[m])


def _fit_profile(OFF, ON, DR, LIT=None) -> dict:
    """The tint `on = (1 - a) off + a W`: W per channel from the rim bins (a robust line per channel,
    W = intercept / (1 - slope)), then `a` per dr bin by trimmed least squares over the three channels.
    With LIT (the off pixel's floor state, lit or unlit, where known), the interior and rim alphas are
    repeated per state: a tint over either state has one alpha."""
    def line(x, y):
        keep = np.ones(len(x), bool)
        sl = ic = float("nan")
        for _ in range(4):
            if keep.sum() < 20:
                break
            A = np.stack([x[keep], np.ones(int(keep.sum()))], 1)
            sl, ic = np.linalg.lstsq(A, y[keep], rcond=None)[0]
            res = y - (sl * x + ic)
            s = 1.4826 * np.median(np.abs(res[keep])) + 1e-3
            keep = np.abs(res) < 3 * s
        return float(sl), float(ic)

    def alpha(sel, W):
        y = (ON[sel] - OFF[sel]).ravel()
        x = (W[None] - OFF[sel]).ravel()
        keep = np.abs(x) > 20.0
        a = float("nan")
        for _ in range(4):
            if keep.sum() < 20:
                return None, int(sel.sum())
            a = float((x[keep] * y[keep]).sum() / (x[keep] ** 2).sum())
            res = y - a * x
            s = 1.4826 * np.median(np.abs(res[keep])) + 1e-3
            keep = (np.abs(res) < 3 * s) & (np.abs(x) > 20.0)
        return round(a, 4), int(sel.sum())

    rim = (DR >= TINT_W_BINS[0]) & (DR < TINT_W_BINS[1])
    W = []
    for ch in range(3):
        sl, ic = line(OFF[rim, ch], ON[rim, ch])
        W.append(ic / (1.0 - sl) if 1.0 - sl > 0.02 else 255.0)
    W = np.clip(np.array(W, np.float32), 0, 255)
    idx = np.searchsorted(TINT_EDGES, DR, side="right")
    al, npx = [], []
    for k in range(len(TINT_EDGES) + 1):
        a, n = alpha((idx == k) & (DR < TINT_OUTER), W)
        al.append(a)
        npx.append(n)
    out = {"edges": TINT_EDGES.tolist(), "outer": TINT_OUTER, "alpha": al, "px": npx,
           "W_bgr": [round(float(v), 1) for v in W]}
    if LIT is not None:
        for name, st in (("lit", LIT == 1), ("unlit", LIT == 0)):
            out[f"alpha_interior_{name}"] = alpha((idx == 0) & st, W)[0]
            out[f"alpha_rim_{name}"] = alpha(rim & st, W)[0]
            out[f"px_rim_{name}"] = int((rim & st).sum())
    return out


def _lit_of(s, crop):
    """(H, W) int: 1 lit, 0 unlit by the owner's lit decision (`lighting.raw_lit`) on known floor, -1 off it."""
    if s is None or s.inputs.light is None:
        return None
    lit = np.where(lighting.raw_lit(crop, s.ref), 1, 0)
    lit[~s.ref.known] = -1
    return lit


def tint_calibrate(sess, label_times: dict) -> dict:
    """The audio and Clove circles' tint profiles and each session's audio circle size, on unlabelled
    frames (at least CAL_AWAY_MS from every labelled instant).

    Audio: TINT_WINDOWS windows per session (the labelled sessions and the Iso capture), every cached
    frame fitted (`audio_fit`, no size gate); the session's footstep size is the mode of its observed
    radii. A pair is two frames TINT_PAIR_GAP apart where the circle is observed on one and its ring
    under audio_circle's lower cut on the other at the same circle, the self moved at most TINT_MOVE_PX,
    and the observed radius is one of the session's sizes. Clove: each stored ally Clove death scanned
    for CLOVE_SCAN_MS (or to the round's end) at its death points (`clove_fit`); a pair is an onset or
    offset in place. The off frame of a pair shows the floor under the circle, in whatever state."""
    rng = np.random.default_rng(0)
    pix = defaultdict(lambda: defaultdict(list))
    sizes, pairs_n, clove_runs = {}, defaultdict(int), []
    sids = sorted(set(label_times) | {ac.ISO})
    for sid in sids:
        S, why = _ac_session(sid)
        if S is None:
            sizes[sid] = {"footstep": None, "reason": why}
            print(f"  tint {sid}: {why}", flush=True)
            continue
        try:
            s = sess(sid)
        except Exception as e:          # noqa: BLE001 - the Iso capture may have no team_vision inputs
            s, _ = None, e
        sc = widget_scale(S.static.shape[1])
        skey = _skey(sc)
        lts = np.asarray(sorted(label_times.get(sid, [])), float)
        holds = np.asarray(sorted(S.cache.holds()), float)
        away = lambda t: not len(lts) or np.min(np.abs(lts - t)) >= CAL_AWAY_MS  # noqa: E731
        starts = [t for t in holds[::15] if away(t) and away(t + TINT_WINDOW_S * 1000)]
        pick = sorted(rng.choice(len(starts), min(TINT_WINDOWS, len(starts)), replace=False)) if starts else []
        radii_obs, cand = [], []
        for k in pick:
            t0 = starts[k]
            ts = [t for t in holds[(holds >= t0) & (holds <= t0 + TINT_WINDOW_S * 1000)] if away(t)]
            fr = []
            for tm, crop in S.crops(ts):
                me, _ = S.self_at(tm)
                f = audio_fit(S, crop, me, sc, None) if me is not None else None
                fr.append((tm, crop, me, f))
                if f is not None and f["observed"]:
                    radii_obs.append(f["r"])
            for i in range(len(fr) - TINT_PAIR_GAP):
                a, b = fr[i], fr[i + TINT_PAIR_GAP]
                if a[2] is None or b[2] is None or a[3] is None or b[3] is None:
                    continue
                if math.hypot(a[2][0] - b[2][0], a[2][1] - b[2][1]) > TINT_MOVE_PX:
                    continue
                for on, off in ((b, a), (a, b)):
                    if not on[3]["observed"] or off[3]["observed"]:
                        continue
                    circ = on[3]
                    if cc.ringscore(S.diff(off[1]), (circ["cx"], circ["cy"]), circ["r"]) >= ac.T_LO:
                        continue
                    cand.append((off[1], on[1], {k2: circ[k2] for k2 in ("cx", "cy", "r")}, on[2],
                                 _lit_of(s, off[1])))
        foot = None
        if len(radii_obs) >= 10:
            R = np.asarray(radii_obs)
            h = np.histogram(R, bins=np.arange(R.min() - 0.5, R.max() + 1.0, 0.5))
            m = h[1][int(np.argmax(h[0]))] + 0.25
            foot = float(np.median(R[np.abs(R - m) <= 1.0]))
        sizes[sid] = {"footstep": None if foot is None else round(foot, 2), "fits": len(radii_obs),
                      "reason": None if foot is not None else f"{len(radii_obs)} observed fits, under 10"}
        n_ok = 0
        for off, on, circ, me, lit in cand:
            if foot is None or n_ok >= TINT_MAX_PAIRS:
                break
            tol = AUDIO_SIZE_TOL_PX * sc
            size = "footstep" if abs(circ["r"] - foot) <= tol else (
                "reload" if abs(circ["r"] - foot * TCAL["reload_ratio"]) <= tol else None)
            if size is None:
                continue
            o, n_, dr, lt = _pair_pixels(off, on, circ, me, sc, lit)
            for key, v in (("off", o), ("on", n_), ("dr", dr), ("lit", lt)):
                if v is not None:
                    pix[("audio", skey)][key].append(v)
            n_ok += 1
            pairs_n[("audio", skey, sid)] += 1
        print(f"  tint {sid} ({skey}): {len(pick)} windows, {len(radii_obs)} observed audio fits, footstep "
              f"{foot}, pairs {n_ok} of {len(cand)}", flush=True)
        # the dead Clove's circle
        starts_r, deaths = _dead_cloves(sid) if (sem.STORE / "events" / "death_identity" / f"{sid}.jsonl").is_file() \
            else ([], [])
        for td_ in deaths:
            pts = clove_death_points(sid, td_, sc)
            k = int(np.searchsorted(starts_r, td_, "right"))
            t_end = min(td_ + CLOVE_SCAN_MS, starts_r[k] if k < len(starts_r) else td_ + CLOVE_SCAN_MS)
            run = {"session": sid, "death_t_ms": td_, "points": pts, "observed_t": []}
            if not pts:
                run["reason"] = "no stored ally track ends at the death"
                clove_runs.append(run)
                continue
            ts = [t for t in holds if td_ <= t <= t_end]
            fr = []
            for tm, crop in S.crops(ts):
                me_c, _ = S.self_at(tm)
                f = clove_fit(S.diff(crop), pts, S.radii, sc, me_c, None if foot is None else
                              {"footstep": foot, "reload": foot * TCAL["reload_ratio"]})
                obs = f is not None and f["observed"]
                if f is not None and f["self_audio"]:
                    run["self_audio_frames"] = run.get("self_audio_frames", 0) + 1
                fr.append((tm, crop, f if obs else None))
                if obs:
                    run["observed_t"].append(round(tm, 1))
                    run.setdefault("r", []).append(f["r"])
                    run.setdefault("off_death", []).append(f["centre_off_death"])
            for i in range(len(fr) - TINT_PAIR_GAP):
                a, b = fr[i], fr[i + TINT_PAIR_GAP]
                for on, off in ((b, a), (a, b)):
                    if on[2] is None or off[2] is not None or not (away(on[0]) and away(off[0])):
                        continue
                    circ = on[2]
                    if cc.ringscore(S.diff(off[1]), (circ["cx"], circ["cy"]), circ["r"]) >= ac.T_LO:
                        continue
                    me, _ = S.self_at(on[0])
                    o, n_, dr, lt = _pair_pixels(off[1], on[1], circ, me, sc, _lit_of(s, off[1]))
                    for key, v in (("off", o), ("on", n_), ("dr", dr), ("lit", lt)):
                        if v is not None:
                            pix[("clove", skey)][key].append(v)
                    pairs_n[("clove", skey, sid)] += 1
            if run.get("r"):
                run["r_median"] = round(float(np.median(run.pop("r"))), 2)
                run["off_death_median"] = round(float(np.median(run.pop("off_death"))), 2)
            run["frames_scanned"] = len(fr)
            run["frames_observed"] = len(run["observed_t"])
            ot = run["observed_t"]
            run["observed_span_s"] = [round(ot[0] / 1000, 2), round(ot[-1] / 1000, 2)] if ot else None
            del run["observed_t"]
            clove_runs.append(run)
            print(f"  clove {sid} death {td_ / 1000:.1f} s: points {len(pts)}, observed {run['frames_observed']} of "
                  f"{len(fr)} frames {run['observed_span_s']} r {run.get('r_median')} off {run.get('off_death_median')}",
                  flush=True)
    profiles = {}
    for (kind, skey), v in sorted(pix.items()):
        OFF, ON, DR = (np.concatenate(v[k]) for k in ("off", "on", "dr"))
        LIT = np.concatenate(v["lit"]) if len(v["lit"]) == len(v["off"]) else None
        prof = _fit_profile(OFF, ON, DR, LIT)
        prof["pairs"] = int(sum(n for (k2, s2, _), n in pairs_n.items() if (k2, s2) == (kind, skey)))
        prof["sessions"] = sorted({sid for (k2, s2, sid) in pairs_n if (k2, s2) == (kind, skey)})
        profiles[f"{kind}@{skey}"] = prof
        print(f"  profile {kind}@{skey}: pairs {prof['pairs']} W {prof['W_bgr']} alpha {prof['alpha']}", flush=True)
    return {"version": VERSION, "made_from": "tint pairs on unlabelled frames (TINT_* constants), stored self "
            "track, stored death data and ally tracks, baked static as the diff background",
            "reload_ratio": TCAL["reload_ratio"], "audio_sizes": sizes, "profiles": profiles, "clove_runs": clove_runs}


def fit_agree(all_rows: dict) -> dict:
    """0.4.0's thin wrapper (`_ring_fit`, reach AUDIO_REACH_PX, its own acceptance) against audio_circle's
    per-frame fit (`audio_fit` without the size gate) on a probe set: every labelled item's frame (fits
    only; no facing is read) and 200 drawn own-view frames of the Iso capture."""
    probe = []
    for rows in all_rows.values():
        for r in rows:
            probe.append(("labelled", r["session"], float(r["t_ms"]), r["_crop"]))
    z = np.load(ac.PF_OUT / "per_frame.npz")
    idx = np.nonzero((z["state"] == 1) & (z["pov"] == "own") & np.isfinite(z["r_fit"]))[0]
    pick = sorted(np.random.default_rng(1).choice(idx, min(200, len(idx)), replace=False))
    S_iso, _ = _ac_session(ac.ISO)
    for tm, crop in S_iso.crops([float(z["t"][i]) * 1000 for i in pick]):
        probe.append(("iso", ac.ISO, float(tm), crop))
    rows_out = []
    for kind, sid, tm, crop in probe:
        S, why = _ac_session(sid)
        if S is None or S.static.shape[:2] != crop.shape[:2]:
            continue
        me, _ = S.self_at(tm)
        if me is None:
            continue
        sc = widget_scale(crop.shape[1])
        d = S.diff(crop)
        f4 = _ring_fit(d, me, S.radii, reach=AUDIO_REACH_PX * sc)
        if f4 is not None:
            f4["white"] = whiteness(rim_steps(crop, S.static, (f4["cx"], f4["cy"]), f4["r"]))
        ok4 = f4 is not None and f4["observed"] and f4["white"] >= AUDIO_WHITE_MIN
        f5 = audio_fit(S, crop, me, sc, None)
        # the per-frame fit's own acceptance without the centre rule, to compare the fits themselves
        ok5_raw = f5.get("reason") is None or all(x.startswith("centre") for x in f5["reason"].split("; "))
        ok5_raw = ok5_raw and "cx" in f5
        rows_out.append({"probe": kind, "session": sid, "t_ms": tm, "sc": sc, "v4": ok4, "v5_raw": ok5_raw,
                         "v5": bool(f5["observed"]), "v5_reason": f5.get("reason"),
                         "d_r": None if not (ok4 and ok5_raw) else round(abs(f4["r"] - f5["r"]), 2),
                         "d_c": None if not (ok4 and ok5_raw) else round(math.hypot(f4["cx"] - f5["cx"],
                                                                                    f4["cy"] - f5["cy"]), 2),
                         "v4_r": None if f4 is None else round(f4["r"], 2), "v5_r": round(f5.get("r", np.nan), 2),
                         "v4_off": None if f4 is None else round(f4["centre_off"], 2),
                         "v5_off": round(f5.get("centre_off", np.nan), 2)})
    res = {}
    for kind in ("labelled", "iso", "all"):
        sub = [x for x in rows_out if kind == "all" or x["probe"] == kind]
        both = [x for x in sub if x["v4"] and x["v5_raw"]]
        dr = np.array([x["d_r"] for x in both]) if both else np.array([np.nan])
        dc = np.array([x["d_c"] for x in both]) if both else np.array([np.nan])
        res[kind] = {"n": len(sub), "v4_observed": sum(x["v4"] for x in sub),
                     "v5_raw_observed": sum(x["v5_raw"] for x in sub), "v5_observed": sum(x["v5"] for x in sub),
                     "both": len(both), "only_v4": sum(x["v4"] and not x["v5_raw"] for x in sub),
                     "only_v5": sum(x["v5_raw"] and not x["v4"] for x in sub),
                     "both_same": sum(x["d_r"] <= 1.0 and x["d_c"] <= 2.0 for x in both),
                     "d_r_median": round(float(np.nanmedian(dr)), 3), "d_r_max": round(float(np.nanmax(dr)), 3),
                     "d_c_median": round(float(np.nanmedian(dc)), 3), "d_c_max": round(float(np.nanmax(dc)), 3)}
        print(f"  fit agreement {kind}: {res[kind]}", flush=True)
    for x in rows_out:
        if x["v4"] != x["v5_raw"] or (x["d_r"] is not None and (x["d_r"] > 1.0 or x["d_c"] > 2.0)):
            print(f"    disagree {x}", flush=True)
    return {"summary": res, "rows": rows_out}


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


def outside_jumps(scene) -> list[dict]:
    """0.6.0 "boxes": each outside caster whose cone crosses a box, standing against jumping at the
    fitted scene poses; the cheaper state stays. Greedy, one caster at a time, in frame order."""
    lt = getattr(scene, "light", None)
    if lt is None or not lt.boxes:
        return []
    out = []
    got = scene._last_fit
    for k, o in enumerate(lt.outside):
        if o.get("deg") is None:
            continue
        if not lt.crosses(np.array([[o["x"], o["y"], o["deg"]]], np.float64), full=bool(o.get("full")))[0]:
            continue
        lo_s = scene.loss_of(scene.stack(got["order"], got["poses"]))
        lt.set_outside_jump(k, True)
        lo_j = scene.loss_of(scene.stack(got["order"], got["poses"]))
        if lo_j >= lo_s:
            lt.set_outside_jump(k, False)
        out.append({"outside": k, "role": o.get("role"), "loss_standing": round(lo_s, 3),
                    "loss_jumping": round(lo_j, 3), "jumping": lo_j < lo_s})
    return out


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


def run_item(s, r: dict, tracks, do_fit: bool = True, tv: TVFrames | None = None) -> dict:
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
    if "dark" in CHANGES and SPACE == "rgb":
        # 0.6.0: a darkened minimap is refused before any light is compared; the teardrop still reads.
        dk = minimap_darkened(s, crop)
        out["minimap_dark"] = dk
        if dk["darkened"]:
            out["refused"] = "minimap-darkened"
            return out
    srcm = tint = None
    if SPACE == "rgb" and LIGHT == "pose":
        src, srcm, tint = scene_sources(r, r["session"], r["t_ms"], crop, sc)
        out["light_sources"] = src["drawn"]
        out["light_source_notes"] = src["notes"]
        out["light_sources_rejected"] = src.get("rejected", [])
    if not do_fit:
        return out
    t0 = time.perf_counter()
    if SPACE == "rgb":
        if LIGHT == "pose" and "cast" in CHANGES:
            outside, out["casters"] = team_casters(s, r, sc, nb["icons"], tv)
        else:
            outside = outside_icons(frame_team(s, r, sc), sc, nb["icons"]) if LIGHT == "pose" else []
        scene = RGBScene(crop, s, nb["icons"], sc, CAL, outside=outside, light_costs=light_costs(sc), src=srcm,
                         tint=tint)
    else:
        scene = Scene(keys(crop), keys(s.inputs.static), nb["icons"], sc)
    got = fit_scene(scene)
    if SPACE == "rgb" and scene.light is not None and scene.light.boxes:
        # 0.6.0: the outside casters' states at the fitted poses; a flip to jumping refits the scene.
        scene._last_fit = got
        out["outside_jumps"] = outside_jumps(scene)
        if any(x["jumping"] for x in out["outside_jumps"]):
            got = fit_scene(scene)
        bo = scene.box_outcomes(got["order"], got["poses"])
        for row in bo:
            role = (nb["icons"][row["index"]]["cls"] if row["caster"] == "scene" else row.get("role"))
            row["role"] = role
            row["boost"] = boost_eligible(r["session"], role) if role in ("self", "ally") else None
            if row["jumping"] and row["boost"] == "no":
                # The player: tall boxes block a jump; only a boost ability lifts over them. A pass by a
                # caster who cannot boost says every box it crosses is short, or the model is wrong.
                row["surprise"] = "pass-without-boost"
        out["box_outcomes"] = bo
    out["fit_s"] = time.perf_counter() - t0
    if SPACE == "rgb" and scene.light is not None:
        out["light"] = scene.light_stats(got["order"], got["poses"])
        out["light"].update(outside_cast=scene.light.n_outside_cast, outside_free=scene.light.n_outside_free)
    p = got["poses"][0]
    out["joint"] = float(td._signed_deg(p[2]))
    out["joint_xy"] = (p[0], p[1])
    out["joint_gains"] = (p[3], p[4])
    out["joint_jumping"] = bool(Light.jumping(p)) if SPACE == "rgb" else False
    sp = got["solos"][0]["best"]
    out["solo"] = float(td._signed_deg(sp[2]))
    out["solo_xy"] = (sp[0], sp[1])
    out["margin"] = got["margin"]
    out["solo_margin"] = got["solos"][0]["far_loss"] - got["solos"][0]["loss"]
    out["order"] = got["order"]
    out["starts"] = got["starts"]
    out["neighbour_poses"] = [got["poses"][i] for i in range(1, len(scene.icons))]
    out["rests_on"] = [("baked static RGB (map, profile)" if SPACE == "rgb" else "baked static keys (map, profile)")] + (
        ["baked walls and boxes (map, profile) via cone.raycast; outside team icons' teardrop poses"]
        if SPACE == "rgb" and LIGHT == "pose" else []) + (
        ["team_vision stored track positions"] if "track" in nb["sources"] else []) + (
        ["class detectors at this frame"] if "detector" in nb["sources"] else []) + ["label set's detector centre"] + (
        [f"drawn light sources fitted on this frame ({','.join(sorted({c['kind'] for c in out['light_sources']}))}): "
         "stored self track, stored death data and rounds, the player's ability labels"]
        if out.get("light_sources") else []) + (
        ["0.6.0 casters: the stored team_vision frame places every teammate; a hidden one's facing rests on "
         "its last visible teardrop (casters[].depends_on)"] if out.get("casters") is not None else []) + (
        ["0.6.0 regions: light-diagnosis-0.1.0's per-pixel read rates"] if "regions" in CHANGES else []) + (
        ["0.6.0 boxes: baked boxes via cone.box_crossings; the stored lineup for boost eligibility"]
        if "boxes" in CHANGES else [])
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
    # Identical items: flips of each arm over the items both the teardrop and the joint fit read.
    out["both_teardrop_flips"] = sum(abs(err(r, "teardrop")) > 90 for r in both)
    out["both_joint_flips"] = sum(abs(err(r, "joint")) > 90 for r in both)
    js = [r for r in rows if err(r, "joint") is not None and err(r, "solo") is not None]
    out["joint_vs_solo_fixed"] = sum(abs(err(r, "solo")) > 90 and abs(err(r, "joint")) <= 90 for r in js)
    out["joint_vs_solo_broken"] = sum(abs(err(r, "solo")) <= 90 and abs(err(r, "joint")) > 90 for r in js)
    unread = [r for r in rows if r.get("teardrop") is None and err(r, "joint") is not None]
    out["joint_on_td_unread_n"] = len(unread)
    out["joint_on_td_unread_flips"] = sum(abs(err(r, "joint")) > 90 for r in unread)
    lit = [r["light"] for r in rows if r.get("light")]
    if lit:
        out["light_n"] = len(lit)
        out["light_unexplained_fire"] = sum(x["unexplained_n"] >= LIGHT_FIRE_PX for x in lit)
        out["light_missing_fire"] = sum(x["missing_n"] >= LIGHT_FIRE_PX for x in lit)
        out["light_unexplained_share_median"] = round(float(np.median(
            [x["unexplained_n"] / max(x["floor_n"], 1) for x in lit])), 4)
        if all("floor_nosrc_n" in x for x in lit):
            # Shares over the compared floor without the sources (0.3.0's floor), so with and without share
            # one denominator; `_src_items` pools only the items where a source covers compared floor.
            den = lambda x: max(x["floor_nosrc_n"], 1)  # noqa: E731
            out["light_unexplained_nosrc_share_median"] = round(float(np.median(
                [x["unexplained_nosrc_n"] / den(x) for x in lit])), 4)
            out["light_unexplained_srcfloor_share_median"] = round(float(np.median(
                [x["unexplained_n"] / den(x) for x in lit])), 4)
            out["light_source_share_median"] = round(float(np.median([x["source_n"] / den(x) for x in lit])), 4)
            for tag, sub in (("", lit), ("_src_items", [x for x in lit if x["source_n"] > 0])):
                fl = max(sum(x["floor_nosrc_n"] for x in sub), 1)
                out[f"light{tag}_n"] = len(sub)
                out[f"light_unexplained_share_pooled{tag}"] = round(sum(x["unexplained_n"] for x in sub) / fl, 4)
                out[f"light_unexplained_nosrc_share_pooled{tag}"] = round(
                    sum(x["unexplained_nosrc_n"] for x in sub) / fl, 4)
    out["refused_minimap_darkened"] = sum(r.get("refused") == "minimap-darkened" for r in rows)
    if lit and all("unexplained_region_n" in x for x in lit):
        fl = max(sum(x["floor_nosrc_n"] for x in lit), 1)
        out["light_unexplained_region_share_pooled"] = round(sum(x["unexplained_region_n"] for x in lit) / fl, 4)
        out["light_missing_region_share_pooled"] = round(sum(x["missing_region_n"] for x in lit) / fl, 4)
        out["light_unexplained_region_items"] = sum(x["unexplained_region_n"] > 0 for x in lit)
    bo = [b for r in rows for b in r.get("box_outcomes") or []]
    if any("box_outcomes" in r for r in rows):
        out["box_casters"] = len(bo)
        out["box_casters_jumping"] = sum(b["jumping"] for b in bo)
        out["box_pass_without_boost"] = sum(b.get("surprise") == "pass-without-boost" for b in bo)
        out["box_items"] = sum(bool(r.get("box_outcomes")) for r in rows)
    cs = [c for r in rows for c in r.get("casters") or []]
    if any("casters" in r for r in rows):
        for src_ in ("joint_fit", "teardrop", "teardrop_stacked", "last_visible_teardrop", "stored_track",
                     "teardrop_untracked", None):
            out[f"casters_{src_ or 'free'}"] = sum(c.get("facing_source") == src_ for c in cs)
    out["items_with_source"] = sum(bool(r.get("light_sources")) for r in rows)
    for kind in SOURCES:
        out[f"items_with_{kind}"] = sum(any(c["kind"] == kind for c in r.get("light_sources") or []) for r in rows)
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
    print(f"  identical items (n {res['both_n']}): teardrop flips {res['both_teardrop_flips']}, "
          f"joint flips {res['both_joint_flips']}; refused minimap-darkened {res['refused_minimap_darkened']}")
    if "light_unexplained_region_share_pooled" in res:
        print(f"  regions: unexplained region share pooled {res['light_unexplained_region_share_pooled']}, "
              f"missing {res['light_missing_region_share_pooled']}")
    if "box_casters" in res:
        print(f"  boxes: casters crossing a box {res['box_casters']}, jumping {res['box_casters_jumping']}, "
              f"pass without boost {res['box_pass_without_boost']}")
    if "casters_joint_fit" in res:
        print("  casters: " + ", ".join(f"{k[8:]} {v}" for k, v in res.items() if k.startswith("casters_")))
    if res.get("light_n"):
        print(f"  light at the fitted pose: unexplained fires {res['light_unexplained_fire']}/{res['light_n']}, "
              f"missing fires {res['light_missing_fire']}/{res['light_n']}, median unexplained share "
              f"{res['light_unexplained_share_median']}"
              + (f"; over 0.3.0's floor with/without the sources: median "
                 f"{res['light_unexplained_srcfloor_share_median']}/{res['light_unexplained_nosrc_share_median']}, "
                 f"pooled {res['light_unexplained_share_pooled']}/{res['light_unexplained_nosrc_share_pooled']}, "
                 f"pooled on the {res['light_src_items_n']} items a source covers "
                 f"{res['light_unexplained_share_pooled_src_items']}/"
                 f"{res['light_unexplained_nosrc_share_pooled_src_items']}; "
                 f"items with a drawn source {res['items_with_source']}"
                 if "light_unexplained_nosrc_share_median" in res else ""))


# ---------------------------------------------------------------- the sheet

def _false(k: np.ndarray) -> np.ndarray:
    """Keys (3, h, w) as BGR: teal, yellow, red."""
    t, y, r = (np.clip(k[i], 0, 1) for i in range(3))
    img = np.stack([255 * t, 255 * np.maximum(t, y), 255 * np.maximum(y, r)], -1)
    return np.clip(img, 0, 255).astype(np.uint8)


def tile(r: dict, zoom: int = 6) -> np.ndarray:
    """Crop, render, |residual| and (0.3.0) the light round the labelled icon; arrows: label green,
    teardrop blue, solo magenta, joint white; neighbours' joint facings orange. The light panel: predicted
    lit yellow, lit by a drawn source green, unexplained light cyan, missing light red, free (unattributable)
    blue. The last panel is the whole widget with the drawn sources' circles (audio white, Clove magenta,
    ability green) and the tile's box (yellow)."""
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
        P, R, Wimg, Cimg = scene.full_images(got["order"], got["poses"], crop.shape[:2])
        keep = np.zeros(crop.shape[:2], bool)
        x0w, y0w, x1w, y1w = scene.win
        keep[y0w:y1w, x0w:x1w] = scene.keep_np
        owned = keep & (Wimg < 0.5)
        Pv = P.copy()
        Pv[owned] = (0.5 * Pv[owned] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)   # owned portrait: magenta
        rimg = cv2.applyColorMap(np.clip(R / TAU_SIG * 255, 0, 255).astype(np.uint8), cv2.COLORMAP_INFERNO)
        rimg[~keep] = 0
        panels += [sub(Pv), sub(rimg)]
        if scene.light is not None:
            # The light: grey crop, predicted lit yellow, unexplained light cyan, missing light red, free blue.
            g = cv2.cvtColor(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR) // 2
            # 0.6.0: a region decided lit with no cone white, one decided unlit in a cone dark red, light
            # a jumping caster casts through a box spring green.
            for c, col in ((1, (0, 200, 255)), (5, (0, 200, 0)), (2, (255, 255, 0)), (3, (0, 0, 255)),
                           (4, (255, 80, 0)), (6, (255, 255, 255)), (7, (0, 0, 128)), (8, (128, 255, 0))):
                g[(Cimg == c) & keep] = col
            g[~keep] = 0
            panels.append(sub(g))
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
    src = r.get("_src")
    if src is not None:
        H = big[0].shape[0]
        k = H / crop.shape[0]
        wv = cv2.resize(crop, (int(round(crop.shape[1] * k)), H), interpolation=cv2.INTER_AREA)
        cols = {"audio": (255, 255, 255), "clove": (255, 0, 255), "ability": (0, 255, 0)}
        for c in src.get("rejected") or []:          # 0.5.0: a fit that failed its tests, grey
            cv2.circle(wv, (int(round(c["cx"] * k)), int(round(c["cy"] * k))), int(round(c["r"] * k)),
                       (128, 128, 128), 1, cv2.LINE_AA)
        for c in src["drawn"]:
            if c.get("death_x") is not None:        # the Clove's death point: a magenta cross
                p = (int(round(c["death_x"] * k)), int(round(c["death_y"] * k)))
                cv2.drawMarker(wv, p, (255, 0, 255), cv2.MARKER_CROSS, 10, 1)
            cv2.circle(wv, (int(round(c["cx"] * k)), int(round(c["cy"] * k))), int(round(c["r"] * k)),
                       cols[c["kind"]], 1, cv2.LINE_AA)
        cv2.rectangle(wv, (int(x0 * k), int(y0 * k)), (int((x0 + 2 * half + 1) * k), int((y0 + 2 * half + 1) * k)),
                      (0, 255, 255), 1)
        big.append(wv)
    row = np.hstack([np.pad(b, ((0, 0), (0, 3), (0, 0))) for b in big])
    et, es, ej = err(r, "teardrop"), err(r, "solo"), err(r, "joint")
    f = lambda e: "-" if e is None else f"{e:+.0f}"  # noqa: E731
    lines = [f"{r['set']} {r['session'][:4]} {r['t_ms'] / 1000:.1f}s {'STACK' if r.get('stacked') else ''} "
             f"touch {r.get('n_touch')} {','.join(r.get('neighbour_classes', []))} order {r.get('order')}",
             f"err td {f(et)} solo {f(es)} joint {f(ej)}  margin {r.get('margin', 0):.2f}"
             + ("  light lit {lit_pred_n} unexpl {unexplained_n} miss {missing_n} free {free_n} of {floor_n}".format(
                 **r["light"]) if r.get("light") else "")]
    if r.get("refused"):
        lines.append(f"REFUSED {r['refused']}: known-floor grey median {r['minimap_dark']['median']:+.0f} "
                     f"vs static; owner widget_drawn {r['minimap_dark'].get('widget_drawn')}")
    if "joint_v5_err" in r or r.get("casters") is not None:
        lines.append(f"0.5.0 joint err {f(r.get('joint_v5_err'))}; region unexpl "
                     f"{(r.get('light') or {}).get('unexplained_region_n', '-')} miss "
                     f"{(r.get('light') or {}).get('missing_region_n', '-')}; casters " + "; ".join(
                         f"{c['role']}:{c.get('facing_source') or 'free'}"
                         + (f"@{c['depends_on']['t_ms'] / 1000:.2f}s" if c.get("depends_on") else "")
                         for c in r.get("casters") or []))
    for b in r.get("box_outcomes") or []:
        lines.append(f"box caster {b['caster']}:{b['role']} {'JUMPING' if b['jumping'] else 'standing'} boost "
                     f"{b['boost']} {b.get('surprise') or ''}; " + "; ".join(
                         f"box {x['box_id']} past {x['compared']} lit {x['read_lit']} {x['supports']}"
                         for x in b["boxes"]))
    if src is not None:
        lit = r.get("light") or {}
        lines.append("sources: " + ("; ".join(f"{c['kind']} r {c['r']:.1f} score {c['score']:.1f}"
                                              + (f" {c['size']}" if c.get("size") else "")
                                              + (f" off self {c['centre_off']:.1f}" if "centre_off" in c else "")
                                              + (f" off death {c['centre_off_death']:.1f}"
                                                 if c.get("centre_off_death") is not None else "")
                                              for c in src["drawn"]) or "none drawn")
                     + "".join(f"; rejected {c['kind']} r {c['r']:.1f} ({c['reason'][:70]})"
                               for c in src.get("rejected") or [])
                     + (f"  src-lit floor {lit['source_n']}, unexpl without sources {lit['unexplained_nosrc_n']}"
                        if "source_n" in lit else ""))
    bar = np.zeros((6 + 17 * len(lines), row.shape[1], 3), np.uint8)
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
#: 0.2.0 checked "rgb-mask", "rgb-disc" and "keys"; 0.3.0 checks 0.2.0's renderer ("rgb-mask", the light
#: free) against its own ("light") on the same items and protocols.
CHECK_VARIANTS = ("rgb-mask", "light")
#: "td": the centre fixed at the owner teardrop's centre (the detector's where it has none), widget scale fixed;
#: "click": 0.2.0's protocol, the centre free within `CHECK_CENTRE_PX` of the player's click.
CHECK_PROTOCOLS = ("td", "click")
CHECK_CENTRE_PX = 1.0     # scale 1.0: the centre is re-optimised this far round the player's click at each facing


def attach_clicks(k: str, rows: list[dict], store) -> None:
    ans = lsf.load_answers(LABEL_FILES[k](store))
    for r in rows:
        a = ans.get(r["key"], {})
        r["click"] = (float(a["centre_x"]), float(a["centre_y"])) if a.get("centre_x") is not None else None


def check_item(s, r: dict, variant: str) -> dict:
    """The labelled icon's sprite alone: loss at the labelled facing against the reversed one under each
    protocol, and the renderer's own best pose over the solo search. In the light variant every other team
    icon of the frame casts from its teardrop pose (held); no other sprite is drawn."""
    global PORTRAIT, LIGHT
    crop = r["_crop"]
    sc = widget_scale(crop.shape[1])
    icons = [{"cls": r["cls"], "x0": float(r["det_cx"]), "y0": float(r["det_cy"])}]
    if variant == "keys":
        scene = Scene(keys(crop), keys(s.inputs.static), icons, sc)
    else:
        PORTRAIT = "disc" if variant == "rgb-disc" else "mask"
        LIGHT = "pose" if variant == "light" else "free"
        outside = outside_icons(frame_team(s, r, sc), sc, icons) if LIGHT == "pose" else []
        srcm = None
        if LIGHT == "pose":
            src = item_sources(r, r["session"], r["t_ms"], crop, sc)
            srcm = source_mask(src, crop.shape[:2]) if src["drawn"] else None
        scene = RGBScene(crop, s, icons, sc, CAL, outside=outside, light_costs=light_costs(sc), src=srcm)
    out = {}
    centres = {"td": (r.get("td_xy") or (r["det_cx"], r["det_cy"]), 0.0),
               "click": (r["click"] or (r["det_cx"], r["det_cy"]), CHECK_CENTRE_PX * sc)}
    for proto in CHECK_PROTOCOLS:
        (cx, cy), half = centres[proto]
        for name, deg in (("lab", r["label_deg"]), ("rev", r["label_deg"] + 180.0)):
            cands = _pose_grid(cx, cy, half, 0.25, np.array([deg], np.float32))
            loss, _ = scene.search(0, [0], {0: None}, cands)
            out[f"{proto}_{name}"] = float(loss.min())
    sol = solo(scene, 0)
    out["global_err"] = float(td._signed_deg(sol["best"][2] - r["label_deg"]))
    if variant == "light" and getattr(scene, "light", None) is not None:
        (cx, cy), _h = centres["td"]
        out["light_lab"] = scene.light_stats([0], {0: (cx, cy, r["label_deg"], 0.0, 0.0)})
        out["light_global"] = scene.light_stats([0], {0: sol["best"]})
        # For the sheet: the renderer's own best pose, drawn as the solo arrow.
        r.update(_scene=scene, _fit={"order": [0], "poses": {0: sol["best"]}}, solo=float(td._signed_deg(
            sol["best"][2])), solo_xy=(sol["best"][0], sol["best"][1]), light=out["light_global"], joint=None,
            margin=sol["far_loss"] - sol["loss"], order=[0])
    PORTRAIT, LIGHT = "mask", "pose"
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
                    for proto in CHECK_PROTOCOLS:
                        vals[f"{part}_{tag}_{proto}_lab_beats_rev"] = sum(
                            r["check"][v][f"{proto}_lab"] < r["check"][v][f"{proto}_rev"] for r in pick)
                    vals[f"{part}_{tag}_global_flips"] = sum(abs(r["check"][v]["global_err"]) > 90 for r in pick)
                lab = [r["check"]["light"]["light_lab"] for r in pick if r["check"]["light"].get("light_lab")]
                vals[f"{part}_light_lab_unexplained_fire"] = sum(x["unexplained_n"] >= LIGHT_FIRE_PX for x in lab)
                vals[f"{part}_light_lab_missing_fire"] = sum(x["missing_n"] >= LIGHT_FIRE_PX for x in lab)
            vals["gate_pass"] = int(vals["all_light_global_flips"] <= vals["all_teardrop_flips"] + 1)
            res[name] = ("+".join(sorted({r["session"] for r in sub})), vals)
            print(f"\n== check {name}: n {vals['all_n']} (stacked {vals['stacked_n']}, isolated {vals['isolated_n']}),"
                  f" teardrop flips {vals['all_teardrop_flips']}; gate {'PASS' if vals['gate_pass'] else 'FAIL'}; "
                  f"at the label, unexplained light fires {vals['all_light_lab_unexplained_fire']}, "
                  f"missing {vals['all_light_lab_missing_fire']}")
            for v in CHECK_VARIANTS:
                tag = v.replace("-", "_")
                print(f"  {v:9s} " + "; ".join(
                    f"{proto}: label beats reversed {vals[f'all_{tag}_{proto}_lab_beats_rev']}/{vals['all_n']} "
                    f"(stacked {vals[f'stacked_{tag}_{proto}_lab_beats_rev']}/{vals['stacked_n']}, isolated "
                    f"{vals[f'isolated_{tag}_{proto}_lab_beats_rev']}/{vals['isolated_n']})" for proto in CHECK_PROTOCOLS)
                      + f"; global flips {vals[f'all_{tag}_global_flips']}")
    return res


# ---------------------------------------------------------------- main

CAL: dict = {}
LCAL: dict = {}


def _idle():
    """Below Normal priority, verified. `tip_highlight._idle`'s untyped ctypes call truncates the 64-bit
    process handle and fails silently on this venv, so 0.4.0 ran at Normal; the handle is typed here."""
    cv2.setNumThreads(1)
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.GetCurrentProcess.restype = wintypes.HANDLE
    k.SetPriorityClass.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    k.GetPriorityClass.argtypes = (wintypes.HANDLE,)
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, 0x4000)                     # BELOW_NORMAL_PRIORITY_CLASS
    got = k.GetPriorityClass(h)
    print(f"priority class {got:#x} ({'Below Normal' if got == 0x4000 else 'NOT Below Normal'})", flush=True)
    if got != 0x4000:
        raise SystemExit("could not set Below Normal priority")


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
    ap.add_argument("--recalibrate", action="store_true",
                    help="refit the RGB colour calibration on unlabelled frames (written under OUT, not over 0.2.0's)")
    ap.add_argument("--light-cal", action="store_true",
                    help="measure the light costs and the P9 instrument on unlabelled frames; fit nothing")
    ap.add_argument("--no-sources", action="store_true",
                    help="the 0.3.0 control: draw no non-cone source, read 0.3.0's light costs, record "
                         "scene_stack_eval_v3_allsets under OUT/control-0.3.0")
    ap.add_argument("--disc", action="store_true",
                    help="the 0.4.0 control: the free-state disc and 0.4.0's source fits, 0.4.0's light costs; "
                         "never recorded, written under OUT/control-0.4.0")
    ap.add_argument("--tint-cal", action="store_true",
                    help="measure the sources' tint profiles and each session's audio circle size on "
                         "unlabelled frames; fit nothing")
    ap.add_argument("--fit-agree", action="store_true",
                    help="0.4.0's audio fit against audio_circle's per-frame fit on a probe set; fit nothing")
    ap.add_argument("--v5", action="store_true",
                    help="0.5.0 exactly: none of 0.6.0's changes; never recorded, written under OUT/control-0.5.0")
    ap.add_argument("--only", choices=("cast", "regions", "boxes"),
                    help="one 0.6.0 change alone (with the darkened-minimap refusal): the ablation, "
                         "recorded as scene_stack_eval_v6_only_<change> under OUT/only-<change>")
    ap.add_argument("--compare", action="store_true",
                    help="the teardrop, 0.5.0, 0.6.0 and each ablation on the items every arm reads, from the "
                         "stored items.json files; fit nothing")
    args = ap.parse_args(argv)
    global GAIN_MODE, OUT, SPACE, CAL, LCAL, CAL_PATH, SOURCES, VERSION, LIGHT_CAL_PATH, SERIES, CHECK_SERIES
    global SOURCE_STATE, TCAL, CHANGES
    SPACE = args.space
    if args.compare:
        return compare(record=args.record)
    if args.v5 or args.no_sources or args.disc:
        if args.v5 and args.record:
            raise SystemExit("--v5 reruns 0.5.0 as a control: it records nothing")
        CHANGES = set()
        if args.v5:
            VERSION, SERIES = "scene-stack-0.5.0", "scene_stack_eval_v5"
            OUT = OUT / "control-0.5.0"
    elif args.only:
        CHANGES = {args.only, "dark"}
        VERSION, SERIES = f"scene-stack-0.6.0-only-{args.only}", f"scene_stack_eval_v6_only_{args.only}"
        OUT = OUT / f"only-{args.only}"
    print(f"{VERSION}: changes {sorted(CHANGES)}", flush=True)
    if args.no_sources:
        if args.light_cal:
            raise SystemExit("--no-sources reads 0.3.0's light calibration; it never rewrites it")
        SOURCES, VERSION, LIGHT_CAL_PATH = (), "scene-stack-0.3.0", LIGHT_CAL_PATH_V3
        SERIES, CHECK_SERIES = "scene_stack_eval_v3_allsets", "scene_stack_check_v3_allsets"
        OUT = OUT / "control-0.3.0"
    if args.disc:
        if args.light_cal or args.record or args.tint_cal:
            raise SystemExit("--disc reruns 0.4.0 as a control: it records nothing and rewrites no calibration")
        SOURCE_STATE, VERSION, LIGHT_CAL_PATH = "free", "scene-stack-0.4.0", LIGHT_CAL_PATH_V4
        OUT = OUT / "control-0.4.0"
    if args.limit:
        OUT = OUT / "smoke"                 # a smoke run never overwrites a full run's items or sheets
    TCAL = {"reload_ratio": _reload_ratio()}
    # 0.6.0 reads 0.5.0's tint calibration; `--tint-cal` writes a new one under this version's OUT.
    tint_path = (OUT if args.tint_cal else OUT_V5) / TINT_CAL_NAME
    if SOURCE_STATE == "tint" and SOURCES and not (args.tint_cal or args.fit_agree):
        if not tint_path.is_file():
            raise SystemExit(f"no {tint_path}: run --tint-cal first")
        TCAL = json.loads(tint_path.read_text(encoding="utf-8"))
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
    full_sets = args.sets == ap.get_default("sets") and not args.limit
    if args.recalibrate:
        CAL_PATH = OUT / "calibration.json"
    cal_path = CAL_PATH
    if args.recalibrate or not cal_path.is_file():
        if not full_sets:
            raise SystemExit("calibrate with every label set loaded, so every labelled instant is excluded")
        print("calibrating on unlabelled frames", flush=True)
        CAL = calibrate(sess, {sid: ts for sid, ts in need.items()})
        cal_path.parent.mkdir(parents=True, exist_ok=True)
        cal_path.write_text(json.dumps(CAL, indent=1), encoding="utf-8")
        print("wrote", cal_path)
    CAL = json.loads(cal_path.read_text(encoding="utf-8"))
    if args.tint_cal:
        if not full_sets:
            raise SystemExit("measure the tint with every label set loaded, so every labelled instant is excluded")
        from reticle import metrics
        got = tint_calibrate(sess, {sid: ts for sid, ts in need.items()})
        tint_path.parent.mkdir(parents=True, exist_ok=True)
        tint_path.write_text(json.dumps(got, indent=1, default=str), encoding="utf-8")
        print("wrote", tint_path)
        if args.record:
            deps = {"prototype": VERSION, "cal_away_ms": CAL_AWAY_MS, **_source_deps()}
            for name, p in got["profiles"].items():
                kind, skey = name.split("@")
                v = {f"alpha_{i}": a for i, a in enumerate(p["alpha"])}
                v |= {"alpha_interior": p["alpha"][0], "alpha_rim_max": max(a for a in p["alpha"] if a is not None),
                      "W_b": p["W_bgr"][0], "W_g": p["W_bgr"][1], "W_r": p["W_bgr"][2], "pairs": p["pairs"],
                      "px_interior": p["px"][0]}
                v |= {k: p[k] for k in p if k.startswith(("alpha_interior_", "alpha_rim_", "px_rim_"))}
                metrics.record(TINT_CAL_SERIES, part=f"{kind}-scale-{skey}", session="+".join(p["sessions"]),
                               values=v, deps=deps, context={"edges": p["edges"], "outer": p["outer"]})
                print("recorded tint profile", name)
            sz = {f"footstep_{sid}": v["footstep"] for sid, v in got["audio_sizes"].items()}
            sz |= {f"fits_{sid}": v.get("fits") for sid, v in got["audio_sizes"].items()}
            sz["reload_ratio"] = got["reload_ratio"]
            metrics.record(TINT_CAL_SERIES, part="audio-sizes", session="+".join(sorted(got["audio_sizes"])),
                           values=sz, deps=deps)
            cr = got["clove_runs"]
            cv = {"deaths": len(cr), "deaths_with_point": sum(bool(x["points"]) for x in cr),
                  "deaths_with_circle": sum(x.get("frames_observed", 0) > 0 for x in cr),
                  "frames_observed": sum(x.get("frames_observed", 0) for x in cr),
                  "frames_scanned": sum(x.get("frames_scanned", 0) for x in cr)}
            obs = [x for x in cr if x.get("frames_observed")]
            if obs:
                cv["r_median"] = round(float(np.median([x["r_median"] for x in obs])), 2)
                cv["off_death_median"] = round(float(np.median([x["off_death_median"] for x in obs])), 2)
            metrics.record(TINT_CAL_SERIES, part="clove-runs", session="+".join(sorted({x["session"] for x in cr})),
                           values=cv, deps=deps)
            print("recorded audio sizes and clove runs", cv)
        return 0
    if args.fit_agree:
        from reticle import metrics
        got = fit_agree(all_rows)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "fit_agree.json").write_text(json.dumps(got, indent=1, default=str), encoding="utf-8")
        print("wrote", OUT / "fit_agree.json")
        if args.record and full_sets:
            deps = {"prototype": VERSION, "audio_reach_px": AUDIO_REACH_PX, "audio_circle": ac.VERSION,
                    "same": "radius within 1 px and centre within 2 px", **_source_deps()}
            for kind, v in got["summary"].items():
                metrics.record(FIT_AGREE_SERIES, part=kind,
                               session="+".join(sorted({x["session"] for x in got["rows"]
                                                        if kind == "all" or x["probe"] == kind})),
                               values=v, deps=deps)
                print("recorded fit agreement", kind)
        return 0
    if args.light_cal:
        if not full_sets:
            raise SystemExit("calibrate the light with every label set loaded, so every labelled instant is excluded")
        from reticle import metrics
        LCAL = light_calibrate(sess, {sid: ts for sid, ts in need.items()})
        LIGHT_CAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        LIGHT_CAL_PATH.write_text(json.dumps(LCAL, indent=1), encoding="utf-8")
        print("wrote", LIGHT_CAL_PATH)
        if args.record:
            deps = {"prototype": VERSION, "calibration": str(cal_path), "light_rays": LIGHT_RAYS,
                    "half_angle_deg": cone.CONE_HALF_ANGLE_DEG, "cal_away_ms": CAL_AWAY_MS, **_source_deps()}
            for skey, vals in LCAL["scales"].items():
                v = {k: x for k, x in vals.items() if k != "sessions"}
                metrics.record(LIGHT_CAL_SERIES, part=f"scale-{skey}", session="+".join(vals["sessions"]),
                               values=v, deps=deps)
                print("recorded light calibration", skey)
        return 0
    if LIGHT == "pose" and SPACE == "rgb" and not args.census:
        if not LIGHT_CAL_PATH.is_file():
            raise SystemExit(f"no {LIGHT_CAL_PATH}: run --light-cal first")
        LCAL = json.loads(LIGHT_CAL_PATH.read_text(encoding="utf-8"))
    tracks = {sid: TrackIndex(sid, ts) for sid, ts in need.items()}
    for sid, tr in tracks.items():
        print(f"  prior {sid}: {len(tr.rows)} stored frames ({tr.version})", flush=True)
    tvs = {sid: TVFrames(sid, ts) for sid, ts in need.items()} if "cast" in CHANGES else {}
    t0 = time.perf_counter()
    for k, rows in all_rows.items():
        for i, r in enumerate(rows):
            got = run_item(sess(r["session"]), r, tracks.get(r["session"]), do_fit=not (args.census or args.check),
                           tv=tvs.get(r["session"]))
            r.update(got)
            if (i + 1) % 10 == 0:
                print(f"  {k} {i + 1}/{len(rows)} {time.perf_counter() - t0:.0f}s", flush=True)
    if args.check:
        from reticle import metrics
        res = check(all_rows, sess, store)
        if args.record and not args.limit:
            deps = {"prototype": VERSION, "calibration": str(cal_path), "light_calibration": str(LIGHT_CAL_PATH),
                    "check_centre_px": CHECK_CENTRE_PX, "variants": list(CHECK_VARIANTS),
                    "protocols": list(CHECK_PROTOCOLS), "tau_sig": TAU_SIG, "own_cost": OWN_COST,
                    "light_fire_px": LIGHT_FIRE_PX, "gate": "light global flips <= teardrop flips + 1"}
            for name, (session, vals) in res.items():
                metrics.record(CHECK_SERIES, part=name, session=session, values=vals, deps=deps)
                print("recorded check", name)
        if args.sheet:
            for k, rows in all_rows.items():
                if not k.endswith("331") and k != "331":
                    continue
                pick = [r for r in rows if r.get("_scene") is not None and (
                    abs(r["check"]["light"]["global_err"]) > 90 or r["stacked"])]
                for p in sheet(pick, OUT / f"check_{k}.png"):
                    print("wrote", p)
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
            notes = defaultdict(int)
            for r in rows:
                for kind, why in (r.get("light_source_notes") or {}).items():
                    notes[f"{kind}: {why.split(' (')[0] if kind != 'clove' or 'since' not in why else 'dead ally Clove, ' + why.split('; ')[-1].split(' (')[0]}"] += 1
            print(f"  sources drawn: {sum(bool(r.get('light_sources')) for r in rows)} items; "
                  + ", ".join(f"{kind} {sum(any(c['kind'] == kind for c in r.get('light_sources') or []) for r in rows)}"
                              for kind in SOURCES) + f"; notes {dict(notes)}")
            for r in rows:
                for c in r.get("light_sources") or []:
                    print(f"    {r['set']} {r['session']} {r['t_ms'] / 1000:.2f}s {'STACK' if r['stacked'] else 'iso'} "
                          f"{c['kind']} centre ({c['cx']:.1f}, {c['cy']:.1f}) r {c['r']:.1f} score {c['score']:.1f} "
                          f"ring {c['ring']:.1f} rms {c['rms']:.2f} inliers {c['inliers']:.2f}")
        return 0

    from reticle import metrics
    deps = {"prototype": VERSION, "teardrop": td.ICON_TEARDROP_VERSION, "grid_deg": GRID_DEG, "tau": TAU,
            "gain": list(GAIN), "enemy_lobe_alpha": ENEMY_LOBE_ALPHA, "solo_search_px": SOLO_SEARCH_PX,
            "joint_search_px": JOINT_SEARCH_PX, "sweeps": SWEEPS, "touch_pad": TOUCH_PAD, "stack_px": STACK_PX,
            "max_neighbours": MAX_NEIGHBOURS, "gain_mode": GAIN_MODE, "prior": "team_vision stored tracks + class detectors",
            "space": SPACE, "portrait": PORTRAIT, "tau_sig": TAU_SIG, "own_cost": OWN_COST,
            "calibration": str(cal_path), "light": LIGHT, "light_calibration": str(LIGHT_CAL_PATH),
            "light_rays": LIGHT_RAYS, "light_fire_px": LIGHT_FIRE_PX, **_source_deps(), **_v6_deps()}
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
    for rows in all_rows.values():
        for r in rows:
            et, ej = err(r, "teardrop"), err(r, "joint")
            if not r["n_touch"] and et is not None and ej is not None and abs(et) <= 90 < abs(ej):
                print(f"ISOLATED BROKEN {r['set']} {r['session']} t_ms {r['t_ms']} key {r.get('key')}: "
                      f"teardrop {et:+.1f} joint {ej:+.1f} light {r.get('light')} "
                      f"sources {[c['kind'] for c in r.get('light_sources') or []]}")
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
        # The sources sheet (rule fixed before viewing): the 331 px items, in load order, first up to 4
        # stacked and 4 isolated with a drawn source, then up to 2 stacked and 2 isolated without one.
        pick = []
        rows331 = [r for k, rows in all_rows.items() if k in ("331", "s331", "e331") for r in rows]
        for want_src, n in ((True, 4), (False, 2)):
            for stacked in (True, False):
                pick += [r for r in rows331 if bool(r.get("light_sources")) == want_src
                         and bool(r["stacked"]) == stacked][:n]
        for p in sheet(pick, OUT / "sheet_sources_331.png", per_page=len(pick) or 1):
            print("wrote", p)
        # 0.5.0's tint sheet (rule fixed before any 0.5.0 score): every 331 px item on which 0.4.0 drew a
        # source (its items.json) or this run draws one, every item with an ally Clove dead in its round,
        # and e37fdeca944f 1795.08 s, in load order.
        v4 = set()
        p4 = OUT_V4 / "items.json"
        if p4.is_file():
            for rows in json.loads(p4.read_text(encoding="utf-8"))["sets"].values():
                v4 |= {(x["session"], round(float(x["t_ms"]))) for x in rows if x.get("light_sources")}
        pick = [r for r in rows331 if (r["session"], round(float(r["t_ms"]))) in v4 or r.get("light_sources")
                or "since" in (r.get("light_source_notes") or {}).get("clove", "")
                or (r["session"] == "e37fdeca944f" and abs(float(r["t_ms"]) - 1795083.3) < 50)]
        print(f"tint sheet: {len(pick)} items")
        for p in sheet(pick, OUT / "sheet_tint_331.png", per_page=8):
            print("wrote", p)
        if CHANGES:
            sheet_v6(all_rows, sess, tracks, tvs)
    return 0


def _v6_deps() -> dict:
    if not CHANGES:
        return {}
    d = {"changes": sorted(CHANGES)}
    if "cast" in CHANGES:
        d |= {"cast_back_ms": CAST_BACK_MS, "cast_frame_ms": CAST_FRAME_MS, "cast_range": "unlimited outside"}
    if "regions" in CHANGES:
        d |= {"instrument": str(INSTRUMENT_PATH), "region_passes": REGION_PASSES,
              "region_rates": {k: instrument_rates(float(k)) for k in ("0.712", "1.000")}}
    if "boxes" in CHANGES:
        d |= {"box_jump_cost": round(BOX_JUMP_COST, 4), "box_states": ["standing", "jumping"],
              "boost_agents": list(BOOST_AGENTS)}
    if "dark" in CHANGES:
        d |= {"dark_median": DARK_MEDIAN}
    return d


# ---------------------------------------------------------------- 0.6.0: the comparison and its sheet

COMPARE_ARMS = (("0.5.0", lambda: OUT_V5 / "items.json"), ("0.6.0", lambda: OUT / "items.json"),
                ("only-cast", lambda: OUT / "only-cast" / "items.json"),
                ("only-regions", lambda: OUT / "only-regions" / "items.json"),
                ("only-boxes", lambda: OUT / "only-boxes" / "items.json"))


def _ikey(r):
    return (r["set"], r["session"], round(float(r["t_ms"]), 1), r.get("key"))


def compare(record: bool = False) -> int:
    """The teardrop and every arm's joint fit on the items every arm reads (none refused), per label set
    and pooled: flips, isolated items broken, the unexplained-light share (pixel rule; regions too)."""
    arms = {}
    for name, path in COMPARE_ARMS:
        p = path()
        if not p.is_file():
            print(f"compare: no {p}; arm {name} left out")
            continue
        rows = [x for v in json.loads(p.read_text(encoding="utf-8"))["sets"].values() for x in v]
        arms[name] = {_ikey(x): x for x in rows}
    if "0.5.0" not in arms or "0.6.0" not in arms:
        raise SystemExit("compare needs 0.5.0's and 0.6.0's items.json")
    base = arms["0.6.0"]
    keys_ = [k for k, x in base.items() if err(x, "teardrop") is not None
             and all(k in a and err(a[k], "joint") is not None for a in arms.values())]
    sets = sorted({k[0] for k in keys_})
    refused = {k for k, x in base.items() if x.get("refused")}
    res = {}
    for part in sets + ["pooled"]:
        ks = [k for k in keys_ if part == "pooled" or k[0] == part]
        v = {"n": len(ks), "teardrop_flips": sum(abs(err(base[k], "teardrop")) > 90 for k in ks),
             "refused_minimap_darkened": sum(1 for k in refused if part == "pooled" or k[0] == part)}
        for name, a in arms.items():
            tag = name.replace(".", "").replace("-", "_")
            v[f"{tag}_flips"] = sum(abs(err(a[k], "joint")) > 90 for k in ks)
            iso = [k for k in ks if not a[k]["n_touch"] and abs(err(a[k], "teardrop")) <= 90
                   and abs(err(a[k], "joint")) > 90]
            v[f"{tag}_isolated_broken"] = len(iso)
            lit = [a[k]["light"] for k in ks if a[k].get("light")]
            fl = max(sum(x["floor_nosrc_n"] for x in lit), 1)
            v[f"{tag}_unexplained_share_pooled"] = round(sum(x["unexplained_n"] for x in lit) / fl, 4)
            if lit and all("unexplained_region_n" in x for x in lit):
                v[f"{tag}_unexplained_region_share_pooled"] = round(
                    sum(x["unexplained_region_n"] for x in lit) / fl, 4)
            if part == "pooled":
                for k in iso:
                    print(f"  {name} ISOLATED BROKEN {k[0]} {k[1]} t_ms {k[2]}: teardrop "
                          f"{err(a[k], 'teardrop'):+.1f} joint {err(a[k], 'joint'):+.1f}")
        res[part] = ("+".join(sorted({k[1] for k in ks})), v)
        print(f"== {part}: n {v['n']} teardrop flips {v['teardrop_flips']}; " + "; ".join(
            f"{name} flips {v[name.replace('.', '').replace('-', '_') + '_flips']} iso-broken "
            f"{v[name.replace('.', '').replace('-', '_') + '_isolated_broken']} unexpl "
            f"{v[name.replace('.', '').replace('-', '_') + '_unexplained_share_pooled']}" for name in arms))
    if record:
        from reticle import metrics
        deps = {"prototype": VERSION, "arms": {n: str(p()) for n, p in COMPARE_ARMS if n in arms},
                "items": "teardrop and every arm's joint read, none refused"}
        for part, (session, v) in res.items():
            metrics.record(COMPARE_SERIES, part=part, session=session, values=v, deps=deps)
            print("recorded compare", part)
    return 0


BFAD_T = 618133.3                       # the player: the self casts this light, drawn under Deadlock's icon


def sheet_v6(all_rows: dict, sess, tracks, tvs) -> None:
    """0.6.0's sheet (rule fixed before any 0.6.0 score): c40d950031bb 205.5 s; every refused item;
    every item where a caster jumped, then up to six where a crossing caster stood; and bfad2778a372
    618.133 s, unlabelled, fitted round the self icon. Each tile names 0.5.0's joint error."""
    v5 = {}
    p5 = OUT_V5 / "items.json"
    if p5.is_file():
        v5 = {_ikey(x): x for v in json.loads(p5.read_text(encoding="utf-8"))["sets"].values() for x in v}
    rows = [r for v in all_rows.values() for r in v]
    for r in rows:
        q = v5.get(_ikey(r))
        r["joint_v5_err"] = err(q, "joint") if q else None
    pick = [r for r in rows if r["session"] == "c40d950031bb" and abs(float(r["t_ms"]) - 205500) < 50]
    pick += [r for r in rows if r.get("refused") and r not in pick]
    pick += [r for r in rows if any(b["jumping"] for b in r.get("box_outcomes") or []) and r not in pick]
    pick += [r for r in rows if r.get("box_outcomes") and r not in pick][:6]
    sid = "bfad2778a372"
    s = sess(sid)
    t = min(s.cache_t, key=lambda x: abs(x - BFAD_T))
    crop = list(s.crops([t]))[0][1]
    det = it_.detections(crop, "self", s)
    if det:
        d = det[0]
        b = {"session": sid, "t_ms": float(t), "cls": "self", "det_cx": float(d["cx"]), "det_cy": float(d["cy"]),
             "set": "unlabelled", "label_deg": None, "key": "bfad-618133", "_crop": crop}
        tv = tvs.get(sid) or (TVFrames(sid, [float(t)]) if "cast" in CHANGES else None)
        tr = tracks.get(sid) or TrackIndex(sid, [float(t)])
        b.update(run_item(s, b, tr, tv=tv))
        pick.append(b)
        print(f"bfad 618.133: joint {b.get('joint')} teardrop {b.get('teardrop')} light {b.get('light')} "
              f"casters {b.get('casters')} boxes {b.get('box_outcomes')}")
    print(f"0.6.0 sheet: {len(pick)} items")
    for p in sheet([r for r in pick if r.get("_scene") is not None or r.get("refused")], OUT / "sheet_v6.png",
                   per_page=8):
        print("wrote", p)


def _source_deps() -> dict:
    return {"sources": list(SOURCES), "source_state": SOURCE_STATE, "audio_reach_px": AUDIO_REACH_PX,
            "audio_white_min": AUDIO_WHITE_MIN, "source_ring_t": SRC_T, "source_ring_t_lo": ac.T_LO,
            "source_fit": [SRC_FIT_INLIERS, SRC_FIT_RMS], "source_same_px": SRC_SAME_PX,
            "ability_names": list(ABILITY_NAMES), "ability_window_ms": ABILITY_WINDOW_MS,
            "ability_r": list(ABILITY_R), "audio_circle": ac.VERSION, "clove_circle": cc.VERSION,
            **({} if SOURCE_STATE != "tint" else {
                "audio_fit": "audio_circle.frame_fit", "audio_centre_tol_px": AUDIO_CENTRE_TOL_PX,
                "audio_size_tol_px": AUDIO_SIZE_TOL_PX, "clove_track_window_ms": list(CLOVE_TRACK_WINDOW_MS),
                "clove_gap_ms": CLOVE_GAP_MS, "clove_same_track_px": CLOVE_SAME_TRACK_PX,
                "clove_reach_px": CLOVE_REACH_PX, "tint_edges": [float(TINT_EDGES[0]), float(TINT_EDGES[-1])],
                "tint_outer": TINT_OUTER, "tint_w_bins": list(TINT_W_BINS), "tint_windows": TINT_WINDOWS,
                "tint_window_s": TINT_WINDOW_S, "tint_pair_gap": TINT_PAIR_GAP, "tint_move_px": TINT_MOVE_PX,
                "tint_max_pairs": TINT_MAX_PAIRS, "tint_min": TINT_MIN, "tint_icon_px": TINT_ICON_PX,
                "clove_scan_ms": CLOVE_SCAN_MS,
                "tint_calibration_version": TCAL.get("version")})}


if __name__ == "__main__":
    raise SystemExit(main())
