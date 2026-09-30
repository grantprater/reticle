r"""Touching minimap icons fitted jointly: render every icon of a stack, composite, compare.

    .\.venv\Scripts\python.exe prototypes\scene_stack.py --census
    .\.venv\Scripts\python.exe prototypes\scene_stack.py [--record] [--sheet] [--sets 465,self,331,s331,e331]

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

**The renderer** works in the owners' continuous class keys, one channel each
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
`scene_stack_eval`; `--sheet` writes the store's
`analysis/scene-stack-20260929/`. Not wired: nothing in `reticle/` reads it.
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

VERSION = "scene-stack-0.1.0"
OUT = sem.STORE / "analysis" / "scene-stack-20260929"

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
    scene = Scene(keys(crop), keys(s.inputs.static), nb["icons"], sc)
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
    out["rests_on"] = ["baked static keys (map, profile)"] + (
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
    if scene is not None:
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


# ---------------------------------------------------------------- main

def _idle():
    th._idle()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sets", default="465,self,331,s331,e331")
    ap.add_argument("--census", action="store_true", help="count stacked labelled items; fit nothing")
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N items per set (a smoke run; never recorded)")
    ap.add_argument("--shared-gain", action="store_true",
                    help="post hoc: one gain per silhouette; recorded under part suffix -posthoc-shared")
    args = ap.parse_args(argv)
    global GAIN_MODE, OUT
    posthoc = ""
    if args.shared_gain:
        GAIN_MODE, posthoc = "shared", "-posthoc-shared"
        OUT = OUT / "posthoc-shared"
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
    tracks = {sid: TrackIndex(sid, ts) for sid, ts in need.items()}
    for sid, tr in tracks.items():
        print(f"  prior {sid}: {len(tr.rows)} stored frames ({tr.version})", flush=True)
    t0 = time.perf_counter()
    for k, rows in all_rows.items():
        for i, r in enumerate(rows):
            got = run_item(sess(r["session"]), r, tracks.get(r["session"]), do_fit=not args.census)
            r.update(got)
            if (i + 1) % 10 == 0:
                print(f"  {k} {i + 1}/{len(rows)} {time.perf_counter() - t0:.0f}s", flush=True)
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
            "max_neighbours": MAX_NEIGHBOURS, "gain_mode": GAIN_MODE, "prior": "team_vision stored tracks + class detectors"}
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
            metrics.record("scene_stack_eval", part=part + posthoc, session=session, values=v, deps=deps)
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
