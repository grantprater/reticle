r"""E2: ally icons rendered in YCbCr through the source's blur, with portraits and lighting.

    .\.venv\Scripts\python.exe prototypes\luma_render_e2.py cands SESSION [--between T0 T1]
    .\.venv\Scripts\python.exe prototypes\luma_render_e2.py fit SESSION [--between T0 T1]
    .\.venv\Scripts\python.exe prototypes\luma_render_e2.py score --calib S:T0-T1 ... --test S:T0-T1 ...
    .\.venv\Scripts\python.exe prototypes\luma_render_e2.py sheet SESSION [--between T0 T1]

Task `luma-render-20261002` (E2) in the store's `notes/predictions.jsonl`;
E1 is `prototypes/luma_render.py`. `capture_psf.py`'s stage-2 fit lost to the
stored reader because it rendered a flat portrait disc, had no lighting term,
fitted two overlapping icons as one and accepted on a mis-calibrated cut.
This fit changes each of those.

**Candidates** (`cands`). The current reader (`ally-icon-0.7.0`) run on the
slice's cached frames, as `upscale_trial._candidates` runs it: every
ally-channel ring fit with its decision. A fit refused by another channel's
rule stays refused (`on_spike_glyph`; a barrier by `map_diff`, the
descriptor's or the baseline's). The rest -- accepted, `shape_gate`,
`facing_unread`, `nearer_fit_preferred` -- are hypotheses for the render to
judge. Fits within `SAME_FRAC` x r_out of each other are one hypothesis
(the best-covered one's pose starts it); two hypotheses within `PAIR_FRAC` x
2 r_out are fitted jointly.

**The render** (`Model`). The ally teardrop of `teardrop.ICON_CLASSES['ally']`
x `geometry.map_scale` x a free scale s: ring and lobe T, portrait disc D,
one-pixel outline O, and background. The source sets the blur (`RAMP`):
luma coverage through a linear ramp of the source's PSF variance (H.264:
the pixel box plus stage 1's 0.15 px Gaussian, 1.13 px; a 4:4:4 live frame:
the pixel box alone, 1.0 px, unmeasured), chroma box-averaged on the 2x2
grid and rebuilt as the decoder does (`capture_psf._q420`) or left alone on
a 4:4:4 source. Background: the baked static x gain + offset per channel,
plus a luma plane (x and y gradients) -- the lighting term. Portrait: the
art of the candidate agents (`reference/assets/agents/<A>_minimap_portrait.png`),
sampled upright at the icon's centre with 2x2 supersampling (the pixel
box), with a gain and offset per channel. Colours are solved linearly.

**Which agents.** The side's five from the stored lineup
(`lineups/<sid>.json`): each slot's agent, or for a refused slot its best
guess and rival. Every result declares `rests_on` that lineup. The full
gallery is the surprise path, justified only where no lineup exists: the
solo demo e78e75b2d191 has none, as the lineup reader's 29 agents are
justified before any lineup exists (`rests_on` null).

**The fit.** Geometry first, with the disc's deep interior unweighted and
a flat disc (`capture_psf`'s grid and compass); then each candidate agent at
that pose with every pixel weighted; then a compass refine of centre, scale
and facing with the best agent. A pair is fitted icon by icon with the other
held, in both drawing orders, and the better order kept.

**Outputs per hypothesis.** Pose, `sse`, `sse_without` (the icon's layers
removed, the rest refitted), `gain_px` = (sse_without - sse) / (n_support x
NOISE^2), the ring colour's tealness, the best agent and its margin over the
second, the portrait's luma gain, and the centre's predicted standard error
from noise (`crlb_px`: the model's Jacobian in cx, cy with the residual's
variance off the icon).

**Scoring** (`score`). The accept rule is `teal >= t*` and `gain_px >= g*`,
chosen on the calibration slices by roster MAE (`upscale_trial._population`)
and then frozen for the test slices, which are scored against condition
`1.0` (the stored reader rerun, `luma_render.py e1-run --cond 1.0`) with the
same block bootstrap. Centre stability: on chains of one icon over
consecutive frames (`CHAIN_MS`, `CHAIN_PX` links) that A and E2 both accept,
the middle centre's residual from a least-squares quadratic in time through
each five-frame neighbourhood, divided by sqrt(1 - h), for E2, the stored
pose and the ring fit; reported on all neighbourhoods and on moving ones
(stored pose spans `MOVING_PX`), where a quantised centre cannot win by
holding still; and E2's observed scatter against its `crlb_px`. `sheet`
draws observed / model / luma residual for 12 added and 12 dropped icons.

Unwired (`"wire": "no"`): a measurement, not a reader.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "2"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import capture_psf as cp  # noqa: E402
import luma_render as lr  # noqa: E402
import upscale_trial as ut  # noqa: E402
from reticle import geometry, teardrop  # noqa: E402
from reticle.decode import Sample  # noqa: E402
from reticle.minimap import ALLY_MAP_DIFF_MIN, ally_icon_reader  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.version import ALLY_ICON_VERSION  # noqa: E402

VERSION = "luma-render-e2-0.1.0"
TASK = lr.TASK
STORE = Path(DEFAULT_STORE)
OUT = lr.OUT
ALLY = teardrop.ICON_CLASSES["ally"]
#: Luma ramp per source: sqrt(1 + 12 sigma_g^2) for the pixel box plus a
#: Gaussian sigma_g (stage 1: 0.15 px on H.264; unmeasured live: 0).
RAMP = {"h264-420": 1.13, "rgb-444": 1.0}
NOISE = 4.0                 # grey; the unit of gain_px
SAME_FRAC = 0.5             # fits nearer than this x r_out are one hypothesis
PAIR_FRAC = 1.1             # hypotheses nearer than this x 2 r_out are fitted jointly
DEEP_PX = cp.DEEP_PX
POOL = {"eligible", "shape_gate", "facing_unread", "nearer_fit_preferred"}
C_GRID, S_GRID = cp.C_GRID, cp.S_GRID
TH_NEAR, TH_ALL = cp.TH_NEAR, cp.TH_ALL
ART_BLUR = 1.4              # art px: pre-blur before 2x2 supersampling
#: The free scale's range. capture_psf's stage 2 found the drawn size at the
#: map scale (S2 held: s within a few percent of 1); a wider range let one
#: icon swell over a stack of two on the first check sheet.
S_RANGE = (0.85, 1.15)


def _tdev():
    import torch
    return "cuda" if torch.cuda.is_available() else "cpu"


# ------------------------------------------------------------------ candidates
def _slice_tag(between):
    return lr._tag(between)


def cands(sid: str, between=None) -> Path:
    """The reader's ally-channel fits and decisions on the slice (crop cache)."""
    from reticle.adjudication.minimap_candidates import ally_decisions
    store, man, profile, ctx = ut._session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no crop cache ({why}); not decoding")
    want, stored_idx, src = ut._timeline(store, sid, cache, between, False)
    r = ally_icon_reader(ctx)
    t0 = time.perf_counter()
    for smp in cache.samples(want, rois=("minimap",)):
        r.feed(Sample(frame_idx=int(stored_idx.get(smp.t_ms, smp.frame_idx)),
                      t_ms=float(smp.t_ms), frame=smp.frame))
    rows = json.loads(json.dumps(r.candidate_rows(sid), allow_nan=False))
    dec = {d["candidate_key"]: d for d in ally_decisions(rows)}
    keep = []
    for c in rows:
        if c["channel"] != "ally":
            continue
        d = dec[c["candidate_key"]]
        md = c.get("map_diff") if c.get("map_diff") is not None else c.get("baseline_map_diff")
        keep.append({"t_ms": c["t_ms"], "frame_idx": c["frame_idx"], "cx": c["cx"], "cy": c["cy"],
                     "r": c["r"], "cov": c["cov"], "inner": c["inner"], "facing": c["facing"],
                     "ring": c.get("ring"), "pose_origin": (c.get("pose") or {}).get("origin"),
                     "reason": d["reason"], "family": d["family"], "map_diff": md})
    out = {"version": VERSION, "session_id": sid, "between": between, "timeline": src,
           "frames": [{"t_ms": f["t_ms"], "widget_drawn": f["widget_drawn"], "self": f["self"]}
                      for f in r.frames],
           "candidates": keep, "seconds": round(time.perf_counter() - t0, 1)}
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"e2_cands_{sid}_{_slice_tag(between)}.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps({"session": sid, "frames": len(out["frames"]), "candidates": len(keep),
                      "reasons": Counter(c["reason"] for c in keep), "seconds": out["seconds"]},
                     default=str))
    print(f"wrote {p}")
    return p


def hypotheses(cs: list[dict], ms: float) -> list[dict]:
    """One frame's pool, clustered: fits nearer than SAME_FRAC r_out are one."""
    r_out = ALLY.r_out * ms
    pool = sorted([c for c in cs if c["reason"] in POOL and
                   not (c["map_diff"] is not None and c["map_diff"] < ALLY_MAP_DIFF_MIN)],
                  key=lambda c: -c["cov"])
    hyp = []
    for c in pool:
        if any(math.hypot(c["cx"] - h["cx"], c["cy"] - h["cy"]) < SAME_FRAC * r_out for h in hyp):
            continue
        hyp.append({"cx": c["cx"], "cy": c["cy"], "facing": c["facing"], "src": c})
    return hyp


# ------------------------------------------------------------------ portraits
def lineup_agents(sid: str) -> tuple[list[str], str | None]:
    """The side's five (refused slots: best guess and rival), resting on the
    lineup; with no lineup, the full gallery, the surprise path the rule
    allows before any lineup exists (`rests_on` None)."""
    p = STORE / "lineups" / f"{sid}.json"
    if not p.is_file():
        art = STORE / "reference" / "assets" / "agents"
        return sorted(q.stem[:-len("_minimap_portrait")]
                      for q in art.glob("*_minimap_portrait.png")), None
    d = json.loads(p.read_text(encoding="utf-8"))
    names = []
    for s in d["sides"]["ally"]:
        for k in (("agent",) if s["agent"] else ("best_guess", "rival")):
            if s.get(k) and s[k] not in names:
                names.append(s[k])
    return names, f"lineups/{sid}.json@{d['version']}"


def art_tensor(names: list[str]):
    """(A, 4, 64, 64) art: Y, Cb, Cr premultiplied by alpha, and alpha; pre-blurred."""
    import torch
    arts = []
    for n in names:
        im = cv2.imread(str(STORE / "reference" / "assets" / "agents" / f"{n}_minimap_portrait.png"),
                        cv2.IMREAD_UNCHANGED)
        if im is None or im.shape[2] != 4:
            raise SystemExit(f"no portrait art for {n}")
        a = im[..., 3:].astype(np.float32) / 255.0
        yc = lr.ycc(im[..., :3]) * a
        t = np.concatenate([yc, a], 2)
        t = cv2.GaussianBlur(t, (0, 0), ART_BLUR)
        arts.append(np.moveaxis(t, 2, 0))
    return torch.as_tensor(np.stack(arts), device=_tdev(), dtype=torch.float32)


def sample_art(art, idx, dx, dy, s, sc):
    """Portrait Y, Cb, Cr (premultiplied) and alpha at offsets dx, dy (B, P, H, W)
    from the centre; art `idx` (B, P) of `art` (A, 4, 64, 64). The art's side
    spans the disc's diameter, 2 r_in x map scale x s; 2x2 supersampled."""
    import torch
    import torch.nn.functional as F
    B, P, H, W = dx.shape
    side = 2.0 * ALLY.r_in * sc * s                                   # (B, P, 1, 1) native px
    acc = 0.0
    for ox in (-0.25, 0.25):
        for oy in (-0.25, 0.25):
            u = (dx + ox) / side * 2.0                                # [-1, 1] across the art
            v = (dy + oy) / side * 2.0
            grid = torch.stack([u, v], -1).reshape(B * P, H, W, 2)
            src = art[idx.reshape(-1)]                                # (B*P, 4, 64, 64)
            acc = acc + F.grid_sample(src, grid, mode="bilinear", padding_mode="zeros",
                                      align_corners=False)
    return (acc / 4.0).reshape(B, P, 4, H, W)


# ------------------------------------------------------------------ the model
def layers(dx, dy, th, s, sc, ramp):
    """T (ring and lobe), D (disc), O (outline) coverage at pixel centres,
    `capture_psf._layers` with the source's luma ramp."""
    import torch
    r_in, r_out, L_ = ALLY.r_in * sc * s, ALLY.r_out * sc * s, ALLY.L * sc * s
    c, sn = torch.cos(th), torch.sin(th)
    u = dx * c + dy * sn
    v = -dx * sn + dy * c
    rho = torch.sqrt(dx * dx + dy * dy)
    ca = r_out / L_
    sa = torch.sqrt(torch.clamp(1.0 - ca * ca, min=0.0))
    d_wedge = u * ca + v.abs() * sa - r_out
    d_tri = torch.maximum(d_wedge, torch.maximum(r_out * ca - u, u - L_))
    d_tear = torch.minimum(rho - r_out, d_tri)
    T = torch.clamp(0.5 - torch.maximum(d_tear, r_in - rho) / ramp, 0.0, 1.0)
    D = torch.clamp(0.5 - (rho - r_in) / ramp, 0.0, 1.0)
    O = (torch.clamp(0.5 - (d_tear - 1.0) / ramp, 0.0, 1.0)
         - torch.clamp(0.5 - d_tear / ramp, 0.0, 1.0)).clamp(0.0, 1.0)
    return T, D, O


class Model:
    """B windows of I icons each (I = 1 or 2): observed Y/Cb/Cr on the inner
    window, the baked static on the window padded by 2 (for 4:2:0), weights,
    frame origins. `loss` renders and solves colours for P proposals."""

    def __init__(self, obs, stat, w, fx0, fy0, sc, half, source, art=None):
        import torch
        dev = _tdev()
        T = lambda a, dt=torch.float32: torch.as_tensor(a, device=dev, dtype=dt)  # noqa: E731
        self.obs, self.stat, self.w = T(obs), T(stat), T(w)
        self.fx0, self.fy0 = T(fx0, torch.long), T(fy0, torch.long)
        self.sc, self.half, self.source = float(sc), int(half), source
        self.ramp = RAMP[source.name]
        self.art = art
        Hp = 2 * half + 1 + 4
        g = torch.arange(Hp, device=dev, dtype=torch.float32) - 2.0
        self.Y, self.X = torch.meshgrid(g, g, indexing="ij")
        self.Hp = Hp
        self.xn = (self.X - half) / max(half, 1)                         # lighting plane
        self.yn = (self.Y - half) / max(half, 1)

    def _inner(self, M):
        n = 2 * self.half + 1
        return M[..., 2:2 + n, 2:2 + n].reshape(*M.shape[:2], n * n)

    def _chroma(self, M):
        if self.source.chroma_block == 2:
            return cp._q420(M, self.fx0, self.fy0)
        return M

    def render_parts(self, cx, cy, s, th, agent=None):
        """Per icon (front first) the occluded layers; and background."""
        import torch
        icons, cover = [], None
        for i in range(cx.shape[-1]):
            dx = self.X[None, None] - cx[..., i, None, None]
            dy = self.Y[None, None] - cy[..., i, None, None]
            Ti, Di, Oi = layers(dx, dy, th[..., i, None, None], s[..., i, None, None], self.sc, self.ramp)
            port = None
            if agent is not None:
                port = sample_art(self.art, agent[..., i], dx, dy, s[..., i, None, None], self.sc)
            if cover is not None:
                vis = (1.0 - cover).clamp(0.0, 1.0)
                Ti, Di, Oi = Ti * vis, Di * vis, Oi * vis
            c = (Ti + Di + Oi).clamp(0.0, 1.0)
            cover = c if cover is None else (cover + c).clamp(0.0, 1.0)
            icons.append((Ti, Di, Oi, port))
        Bg = (1.0 - cover).clamp(0.0, 1.0)
        return icons, Bg

    def design(self, icons, Bg, skip=None):
        """Design matrices (B, P, K, N) for Y, Cb, Cr. `skip`: icon index left out."""
        import torch
        cols = {0: [], 1: [], 2: []}
        for i, (Ti, Di, Oi, port) in enumerate(icons):
            if i == skip:
                continue
            for k in range(3):
                f = (lambda M: M) if k == 0 else self._chroma
                cols[k] += [self._inner(f(Ti)), self._inner(f(Di)), self._inner(f(Oi))]
                if port is not None:
                    # the portrait's colour, premultiplied by its alpha, inside the disc
                    cols[k].append(self._inner(f(Di * port[:, :, k])))
        if skip is not None:
            # the skipped icon's pixels show background
            Ts, Ds, Os, _ = icons[skip]
            Bg = (Bg + Ts + Ds + Os).clamp(0.0, 1.0)
        for k in range(3):
            f = (lambda M: M) if k == 0 else self._chroma
            sk = self.stat[:, k][:, None]
            cols[k] += [self._inner(f(sk * Bg)), self._inner(f(Bg))]
            if k == 0:
                cols[k] += [self._inner(Bg * self.xn), self._inner(Bg * self.yn)]
        return [torch.stack(cols[k], 2) for k in range(3)]

    def loss(self, cx, cy, s, th, agent=None, skip=None, want_coef=False, w=None):
        icons, Bg = self.render_parts(cx, cy, s, th, agent)
        Xs = self.design(icons, Bg, skip)
        w = self.w if w is None else w
        tot, coefs = 0.0, []
        for k in range(3):
            sse, coef = cp._solve(Xs[k], self.obs[:, k], w)
            tot = tot + sse
            coefs.append(coef)
        return (tot, coefs) if want_coef else tot


# ------------------------------------------------------------------ fitting
def _compass(m, p, which, steps, agent=None, w=None, iters=60, step_min=0.02):
    """Compass search over params p (B, I, 4: cx, cy, s, th_deg) of icon `which`."""
    import torch
    B = p.shape[0]
    dev = p.device
    step = torch.tensor(steps, device=dev).repeat(B, 1)                    # (B, 3)
    dirs = torch.tensor([[0, 0, 0, 0], [1, 0, 0, 0], [-1, 0, 0, 0], [0, 1, 0, 0], [0, -1, 0, 0],
                         [0, 0, 1, 0], [0, 0, -1, 0], [0, 0, 0, 1], [0, 0, 0, -1]],
                        device=dev, dtype=torch.float32)
    ar = torch.arange(B, device=dev)
    best = None
    for _ in range(iters):
        sc4 = torch.stack([step[:, 0], step[:, 0], step[:, 1], step[:, 2]], 1)
        cand = p[:, None].repeat(1, 9, 1, 1)                                # (B, 9, I, 4)
        cand[:, :, which] = cand[:, :, which] + dirs[None] * sc4[:, None]
        cand[..., 2] = cand[..., 2].clamp(*S_RANGE)
        ag = None if agent is None else agent[:, None].expand(B, 9, agent.shape[-1])
        L = m.loss(cand[..., 0], cand[..., 1], cand[..., 2], torch.deg2rad(cand[..., 3]), ag, w=w)
        v, j = L.min(1)
        p = cand[ar, j]
        best = v
        moved = j != 0
        step = torch.where(moved[:, None], step, step / 2)
        if bool((step[:, 0] < step_min).all()):
            break
    return p, best


def _grid(m, p, which, init_f, w):
    """`capture_psf.fit_batch`'s grid for icon `which`, others held."""
    import torch
    B = p.shape[0]
    dev = p.device
    G = torch.tensor([(a, b, c) for a in C_GRID for b in C_GRID for c in S_GRID],
                     device=dev, dtype=torch.float32)
    has_f = ~torch.isnan(init_f)
    nt = len(TH_NEAR) if bool(has_f.all()) else len(TH_ALL)
    ths_near = torch.tensor(TH_NEAR, device=dev, dtype=torch.float32)
    ths_all = torch.tensor(TH_ALL, device=dev, dtype=torch.float32)
    best = torch.full((B,), float("inf"), device=dev)
    bp = p[:, which].clone()
    ar = torch.arange(B, device=dev)
    for ti in range(nt):
        th = torch.where(has_f, torch.nan_to_num(init_f) + ths_near[ti % len(TH_NEAR)],
                         ths_all[ti % len(TH_ALL)].expand(B))
        for g0 in range(0, G.shape[0], 49):
            Gc = G[g0:g0 + 49]
            P = Gc.shape[0]
            cand = p[:, None].repeat(1, P, 1, 1)
            cand[:, :, which, 0] = p[:, None, which, 0] + Gc[None, :, 0]
            cand[:, :, which, 1] = p[:, None, which, 1] + Gc[None, :, 1]
            cand[:, :, which, 2] = Gc[None, :, 2].expand(B, P)
            cand[:, :, which, 3] = th[:, None].expand(B, P)
            L = m.loss(cand[..., 0], cand[..., 1], cand[..., 2], torch.deg2rad(cand[..., 3]), w=w)
            v, j = L.min(1)
            upd = v < best
            best = torch.where(upd, v, best)
            bp = torch.where(upd[:, None], cand[ar, j, which], bp)
    out = p.clone()
    out[:, which] = bp
    return out


def fit_model(m, init, n_agents: int) -> dict:
    """init (B, I, 3): cx, cy (window px), facing deg (nan: unknown)."""
    import torch
    B, I, _ = init.shape
    dev = init.device
    p = torch.zeros((B, I, 4), device=dev)
    p[..., 0], p[..., 1], p[..., 2] = init[..., 0], init[..., 1], 1.0
    p[..., 3] = torch.nan_to_num(init[..., 2])
    # Geometry, flat disc, deep interior unweighted (`capture_psf`).
    for which in range(I):
        p = _grid(m, p, which, init[:, which, 2], m.w_geo)
    for which in range(I):
        p, _ = _compass(m, p, which, cp.STEP0, w=m.w_geo)
    # Agents at that pose, every pixel weighted: each icon's best, others held at agent 0
    # first, then the pair's combination searched icon by icon.
    ag = torch.zeros((B, I), dtype=torch.long, device=dev)
    per = torch.zeros((B, I, n_agents), device=dev)
    for which in range(I):
        A = n_agents
        cand = ag[:, None].repeat(1, A, 1)
        cand[:, :, which] = torch.arange(A, device=dev)[None]
        pp = p[:, None].expand(B, A, I, 4)
        L = m.loss(pp[..., 0], pp[..., 1], pp[..., 2], torch.deg2rad(pp[..., 3]), cand)
        per[:, which] = L
        ag[:, which] = L.argmin(1)
    # Refine with the chosen agents.
    for which in range(I):
        p, _ = _compass(m, p, which, (0.25, 0.03, 6.0), agent=ag)
    ar = p[:, None]
    sse, coefs = m.loss(ar[..., 0], ar[..., 1], ar[..., 2], torch.deg2rad(ar[..., 3]), ag[:, None],
                        want_coef=True)
    return {"p": p, "agent": ag, "per_agent": per, "sse": sse[:, 0], "coefs": coefs}


def _without(m, p, ag, which):
    import torch
    ar = p[:, None]
    return m.loss(ar[..., 0], ar[..., 1], ar[..., 2], torch.deg2rad(ar[..., 3]), ag[:, None],
                  skip=which)[:, 0]


def _flat(m, p, which):
    """SSE at the final pose with flat discs (no portrait), every pixel weighted."""
    import torch
    ar = p[:, None]
    return m.loss(ar[..., 0], ar[..., 1], ar[..., 2], torch.deg2rad(ar[..., 3]))[:, 0]


def _crlb(m, p, ag, coefs, which, sigma):
    """Predicted centre standard error (px) from noise: sigma^2 (J^T W J)^-1 over
    the rendered model's derivatives in cx, cy, colours held at the fit."""
    import torch
    h = 0.05

    def model_img(pp):
        icons, Bg = m.render_parts(pp[..., 0], pp[..., 1], pp[..., 2], torch.deg2rad(pp[..., 3]),
                                   ag[:, None])
        Xs = m.design(icons, Bg)
        return [(Xs[k] * coefs[k][..., None]).sum(2)[:, 0] for k in range(3)]       # (B, N)

    J = []
    for d in (0, 1):
        a, b = p[:, None].clone(), p[:, None].clone()
        a[:, :, which, d] += h
        b[:, :, which, d] -= h
        ma, mb = model_img(a), model_img(b)
        J.append(torch.cat([(ma[k] - mb[k]) / (2 * h) for k in range(3)], 1))
    Jm = torch.stack(J, 2)                                                       # (B, 3N, 2)
    w = torch.cat([m.w] * 3, 1)[..., None]
    F = (Jm * w).transpose(1, 2) @ Jm                                            # (B, 2, 2)
    F = F + 1e-6 * torch.eye(2, device=F.device)
    cov = torch.linalg.inv(F) * (sigma[:, None, None] ** 2)
    return torch.sqrt(torch.clamp(cov[:, 0, 0] + cov[:, 1, 1], min=0.0))


# ------------------------------------------------------------------ running
def fit(sid: str, between=None, batch: int = 24, limit: int | None = None, split: bool = True) -> Path:
    import torch
    store, man, profile, ctx = ut._session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    src = lr.source_of(man)
    C = json.loads((OUT / f"e2_cands_{sid}_{_slice_tag(between)}.json").read_text(encoding="utf-8"))
    rd = ally_icon_reader(ctx)
    x0, y0, x1, y1 = rd.box
    ms = lr._ms(sid)
    st = lr.ycc(rd.static)
    names, rests_on = lineup_agents(sid)
    art = art_tensor(names)
    H, W = st.shape[:2]
    half = int(math.ceil(ALLY.L * ms * 1.15 + 3))
    n = 2 * half + 1
    pad = half + 2 + int(math.ceil(2 * ALLY.r_out * ms * PAIR_FRAC))
    stp = np.pad(st, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    inside = np.pad(np.ones((H, W), np.float32), ((pad, pad), (pad, pad)))
    by_t = defaultdict(list)
    for c in C["candidates"]:
        by_t[float(c["t_ms"])].append(c)
    r_out = ALLY.r_out * ms
    r_deep = ALLY.r_in * ms - DEEP_PX
    yy, xx = np.mgrid[-half:half + 1, -half:half + 1]
    jobs = {1: [], 2: []}
    results = []
    times = sorted(t for t in by_t if any(c["reason"] in POOL for c in by_t[t]))
    if limit:
        times = times[:limit]
    t_start = time.perf_counter()
    r_in_px = ALLY.r_in * ms

    def _queue_split(m, f, icons, Bg, J):
        """A single icon's residual names a second icon the reader missed: seed
        it at the peak of residual energy (luma + 2 x chroma, smoothed by a
        disc-sized box) outside 0.8 r_in of the fitted centre, and fit the two
        jointly (`split`). The accept rule judges the second like any icon."""
        import torch.nn.functional as Fn
        Xs = m.design(icons, Bg)
        res = [m.obs[:, k] - (Xs[k] * f["coefs"][k][..., None]).sum(2)[:, 0] for k in range(3)]
        E = (res[0].abs() + 2.0 * (res[1].abs() + res[2].abs())) * m.w
        B = E.shape[0]
        k = max(3, int(round(r_in_px)) | 1)
        E = Fn.avg_pool2d(E.reshape(B, 1, n, n), k, stride=1, padding=k // 2)[:, 0]
        g = torch.arange(n, device=E.device, dtype=torch.float32)
        Yg, Xg = torch.meshgrid(g, g, indexing="ij")
        p0 = f["p"][:, 0]
        rho = torch.sqrt((Xg[None] - p0[:, 0, None, None]) ** 2 + (Yg[None] - p0[:, 1, None, None]) ** 2)
        edge = (Xg < r_in_px) | (Yg < r_in_px) | (Xg > n - 1 - r_in_px) | (Yg > n - 1 - r_in_px)
        E = torch.where((rho < 0.8 * r_in_px) | edge[None], torch.zeros_like(E), E)
        idx = E.reshape(B, -1).argmax(1)
        for b, j in enumerate(J):
            py, px = divmod(int(idx[b]), n)
            a = [float(v) for v in p0[b].tolist()]
            wg = j["w"].reshape(n, n).copy()
            for cx_, cy_ in ((a[0], a[1]), (px, py)):
                wg[np.hypot(xx + half - cx_, yy + half - cy_) < r_deep] = 0.0
            mate = {"cx": px + j["ox"], "cy": py + j["oy"], "facing": None,
                    "src": {"cx": px + j["ox"], "cy": py + j["oy"], "r": None, "cov": None, "inner": None,
                            "facing": None, "reason": "split", "family": None, "ring": None,
                            "pose_origin": "e2_split"}}
            # A single fit over a stack of two straddles them: start the first
            # icon half a step away from the seed, and try both drawing orders.
            ax, ay = a[0] - 0.5 * (px - a[0]), a[1] - 0.5 * (py - a[1])
            ia = [ax, ay, a[3]]
            ib = [px, py, np.nan]
            for order in ([0, 1], [1, 0]):
                pair_init = [ia, ib] if order == [0, 1] else [ib, ia]
                pair_src = [j["src"][0], mate] if order == [0, 1] else [mate, j["src"][0]]
                jobs[2].append({**j, "init": np.array(pair_init, np.float32), "w_geo": wg.reshape(-1),
                                "src": pair_src, "order": order, "split": True})

    def flush(I):
        J = jobs[I]
        if not J:
            return
        obs = np.stack([j["obs"] for j in J])
        stat = np.stack([j["stat"] for j in J])
        w = np.stack([j["w"] for j in J])
        wg = np.stack([j["w_geo"] for j in J])
        m = Model(obs, stat, w, np.array([j["fx0"] for j in J]), np.array([j["fy0"] for j in J]),
                  ms, half, src, art)
        m.w_geo = torch.as_tensor(wg, device=m.obs.device, dtype=torch.float32)
        init = torch.as_tensor(np.stack([j["init"] for j in J]), device=m.obs.device,
                               dtype=torch.float32)
        with torch.no_grad():
            f = fit_model(m, init, len(names))
            p, ag = f["p"], f["agent"]
            flat = _flat(m, p, None)
            for which in range(I):
                wo = _without(m, p, ag, which)
                # icon support: pixels the icon covers at least half
                icons, Bg = m.render_parts(p[:, None, :, 0], p[:, None, :, 1], p[:, None, :, 2],
                                           torch.deg2rad(p[:, None, :, 3]), ag[:, None])
                Ti, Di, Oi, _ = icons[which]
                sup = m._inner(Ti + Di)[:, 0] >= 0.5
                n_sup = (sup * m.w).sum(1).clamp(min=1.0)
                # gain per pixel of the whole drawn icon, so an icon hidden behind
                # another (tiny visible support) cannot score a large gain
                n_ref = math.pi * (ALLY.r_out * ms * p[:, which, 2]) ** 2
                bgm = (m._inner(Bg)[:, 0] >= 0.95) & (m.w > 0)
                ycoef = f["coefs"][0][:, 0]
                # residual luma variance off the icon: the noise the CRLB uses
                Xs = m.design(icons, Bg)
                res_y = m.obs[:, 0] - (Xs[0] * f["coefs"][0][..., None]).sum(2)[:, 0]
                sig = torch.sqrt(((res_y ** 2) * bgm).sum(1) / bgm.sum(1).clamp(min=1.0)).clamp(min=1.0)
                crlb = _crlb(m, p, ag, f["coefs"], which, sig)
                per = f["per_agent"][:, which]
                srt = per.sort(1).values
                if I == 1 and split:
                    _queue_split(m, f, icons, Bg, J)
                for b, j in enumerate(J):
                    # ring colour: the icon's T column per channel
                    kT = 4 * which
                    ring = [float(f["coefs"][k][b, 0, kT]) for k in range(3)]
                    teal = float(teardrop.tealness(cp._ycc_to_bgr(ring)[None, None])[0, 0])
                    results.append({
                        "t_ms": j["t_ms"], "pair": I == 2, "which": which, "split": bool(j.get("split")),
                        "r_out_px": float(ALLY.r_out * ms * p[b, which, 2]),
                        "partner": j["src"][1 - which]["src"].get("cx") if I == 2 else None,
                        "src": {k: j["src"][which]["src"][k] for k in
                                ("cx", "cy", "r", "cov", "inner", "facing", "reason", "family", "ring",
                                 "pose_origin")},
                        "cx": float(p[b, which, 0] + j["ox"]), "cy": float(p[b, which, 1] + j["oy"]),
                        "s": float(p[b, which, 2]), "facing": float(p[b, which, 3] % 360.0),
                        "sse": float(f["sse"][b]), "sse_without": float(wo[b]), "sse_flat": float(flat[b]),
                        "n_support": float(n_sup[b]),
                        "gain_px": float((wo[b] - f["sse"][b]) / (n_ref[b] * NOISE ** 2)),
                        "port_gain_px": float((flat[b] - f["sse"][b]) / (n_ref[b] * NOISE ** 2)),
                        "teal": teal, "ring_ycc": ring,
                        "port_luma_gain": float(ycoef[b, 4 * which + 3]),
                        "agent": names[int(ag[b, which])],
                        "agent_margin_px": float((srt[b, 1] - srt[b, 0]) / (n_ref[b] * NOISE ** 2))
                        if srt.shape[1] > 1 else None,
                        "sigma_bg": float(sig[b]), "crlb_px": float(crlb[b]),
                        "job": {"p": [[float(v) for v in q] for q in p[b].tolist()],
                                "agents": [names[int(a)] for a in ag[b]],
                                "origin": [j["ox"], j["oy"]]}})
        J.clear()

    for smp in cache.samples(times, rois=("minimap",)):
        crop = smp.frame[y0:y1, x0:x1]
        yc = np.pad(lr.ycc(crop), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
        hyp = hypotheses(by_t[float(smp.t_ms)], ms)
        used = set()
        groups = []
        for i, h in enumerate(hyp):
            if i in used:
                continue
            mate = next((k for k in range(i + 1, len(hyp)) if k not in used and
                         math.hypot(hyp[k]["cx"] - h["cx"], hyp[k]["cy"] - h["cy"])
                         < PAIR_FRAC * 2 * r_out), None)
            if mate is not None:
                used.update((i, mate))
                groups.append([h, hyp[mate]])
            else:
                used.add(i)
                groups.append([h])
        for g in groups:
            mx = sum(h["cx"] for h in g) / len(g)
            my = sum(h["cy"] for h in g) / len(g)
            ix, iy = int(round(mx)), int(round(my))
            ox, oy = ix - half, iy - half
            sy, sx = oy + pad, ox + pad
            ob = yc[sy:sy + n, sx:sx + n]
            sp = stp[sy - 2:sy + n + 2, sx - 2:sx + n + 2]
            wv = inside[sy:sy + n, sx:sx + n].copy()
            wg = wv.copy()
            for h in g:
                rho = np.hypot(xx + half - (h["cx"] - ox), yy + half - (h["cy"] - oy))
                wg[rho < r_deep] = 0.0
            init = np.array([[h["cx"] - ox, h["cy"] - oy, np.nan if h["facing"] is None else
                              float(h["facing"])] for h in g], np.float32)
            I = len(g)
            for order in ([0, 1] if I == 2 else [0]), ([1, 0] if I == 2 else None):
                if order is None:
                    continue
                jobs[I].append({"t_ms": float(smp.t_ms), "obs": np.moveaxis(ob, 2, 0).reshape(3, -1),
                                "stat": np.moveaxis(sp, 2, 0), "w": wv.reshape(-1),
                                "w_geo": wg.reshape(-1), "fx0": x0 + ox - 2, "fy0": y0 + oy - 2,
                                "init": init[order], "src": [g[k] for k in order], "ox": ox, "oy": oy,
                                "order": order, "has_port": True})
            for I_ in (1, 2):
                if len(jobs[I_]) >= batch:
                    flush(I_)
    flush(1)
    flush(2)
    # A pair was fitted in both drawing orders; keep the order with the lower SSE.
    single = [r for r in results if not r["pair"]]
    pairs = defaultdict(list)
    for r in results:
        if r["pair"]:
            pairs[(r["t_ms"], round(min(r["src"]["cx"], r["partner"]), 3),
                   round(max(r["src"]["cx"], r["partner"]), 3))].append(r)
    kept = list(single)
    for k, rs in pairs.items():
        sse_by_order = defaultdict(list)
        for r in rs:
            sse_by_order[r["sse"]].append(r)
        best = min(sse_by_order)
        kept += sse_by_order[best]
    out = {"version": VERSION, "task": TASK, "session_id": sid, "between": between,
           "source": src.name, "ramp": RAMP[src.name], "map_scale": ms, "half": half,
           "agents": names, "rests_on": rests_on, "noise": NOISE,
           "seconds": round(time.perf_counter() - t_start, 1), "fits": kept}
    p = OUT / f"e2_fits_{sid}_{_slice_tag(between)}.json"
    p.write_text(json.dumps(out), encoding="utf-8")
    print(json.dumps({"session": sid, "fits": len(kept), "pairs": len(pairs), "seconds": out["seconds"],
                      "agents": names}))
    print(f"wrote {p}")
    return p


# ------------------------------------------------------------------ scoring
#: Accept-rule grids. The gain grid spans the calibration fits' gain
#: distribution (A's eligible fits: 1st percentile about 54, median about
#: 240 on 223d636bf8d2 1090-1250 s); the first grid, 0-32, lay wholly below it.
#: (0, -inf) accepts every pooled hypothesis: the pool without the render.
T_GRID = (0.0, 0.02, 0.05, 0.1, 0.2, 0.3, 0.5, 0.7)
G_GRID = (-1e9, 10.0, 25.0, 50.0, 75.0, 100.0, 150.0, 200.0, 300.0, 400.0)
HIT_PX = 4.0
CHAIN_MS = 150.0            # consecutive cached frames (125 ms cadence) link
CHAIN_PX = 2.0
MOVING_PX = 1.5             # a five-frame neighbourhood whose stored pose spans this moves


def _parse_slice(x: str):
    sid, span = x.split(":")
    if span == "all":
        return sid, None
    a, b = span.split("-")
    return sid, (float(a), float(b))


def _load_fits(sid, between) -> dict:
    return json.loads((OUT / f"e2_fits_{sid}_{_slice_tag(between)}.json").read_text(encoding="utf-8"))


def _accept(f, t_star, g_star) -> bool:
    return f["teal"] >= t_star and f["gain_px"] >= g_star


def _accepted(fits, t_star, g_star, splits: bool = True) -> dict:
    """{t: accepted icons}: every accepted hypothesis, plus each accepted
    split mate (`which` 1) that no accepted icon already covers within half
    its r_out."""
    out = defaultdict(list)
    for f in fits:
        if not f.get("split") and _accept(f, t_star, g_star):
            out[float(f["t_ms"])].append(f)
    if splits:
        for f in fits:
            if f.get("split") and f["src"]["reason"] == "split" and _accept(f, t_star, g_star):
                t = float(f["t_ms"])
                if not any(math.hypot(o["cx"] - f["cx"], o["cy"] - f["cy"]) < 0.5 * f["r_out_px"]
                           for o in out[t]):
                    out[t].append(f)
    return out


def _counts(fits, t_star, g_star, splits: bool = True) -> Counter:
    return Counter({t: len(v) for t, v in _accepted(fits, t_star, g_star, splits).items()})


def _base(sid, between) -> dict:
    p = OUT / f"{sid}_{_slice_tag(between)}_1.0.json"
    if not p.is_file():
        raise SystemExit(f"no condition 1.0 file {p}; run luma_render.py e1-run --cond 1.0 first")
    return json.loads(p.read_text(encoding="utf-8"))


def _residuals(store, sid, between, fits, t_star, g_star, splits=True):
    """(A's residual, E2's residual) per population frame: icons less capacity."""
    base = _base(sid, between)
    ts = sorted({float(f["t_ms"]) for f in base["frames_rows"]})
    pop = ut._population(store, sid, ts)
    if pop is None:
        pop = {float(f["t_ms"]): 0 for f in base["frames_rows"] if f["widget_drawn"]}
    na = Counter(float(i["t_ms"]) for i in base["icons"] if i["family"] != "barrier")
    nb = _counts(fits, t_star, g_star, splits)
    ra = {t: na.get(t, 0) - c for t, c in pop.items()}
    rb = {t: nb.get(t, 0) - c for t, c in pop.items()}
    return ra, rb, base


def _chains(items, key):
    """Chains of one icon over consecutive frames: unique links within CHAIN_PX
    and CHAIN_MS by `key` (a function giving cx, cy)."""
    by_t = defaultdict(list)
    for it in items:
        by_t[float(it["t_ms"])].append(it)
    ts = sorted(by_t)
    nxt, has_prev = {}, set()
    for ta, tb in zip(ts[:-1], ts[1:]):
        if tb - ta > CHAIN_MS:
            continue
        for a in by_t[ta]:
            ax, ay = key(a)
            near = [b for b in by_t[tb] if math.hypot(key(b)[0] - ax, key(b)[1] - ay) <= CHAIN_PX]
            if len(near) == 1:
                nxt[id(a)] = near[0]
                has_prev.add(id(near[0]))
    chains = []
    for t in ts:
        for a in by_t[t]:
            if id(a) in has_prev:
                continue
            c = [a]
            while id(c[-1]) in nxt:
                c.append(nxt[id(c[-1])])
            if len(c) >= 5:
                chains.append(c)
    return chains


def _smooth_resid(chains, getter, moving_only, pose_getter):
    """Per five-frame neighbourhood, the middle centre's residual from a least
    squares quadratic in time, divided by sqrt(1 - h) (h the hat matrix's
    diagonal there), so its RMS estimates the per-axis noise sigma whatever
    the cadence. A quantised centre that holds still scores 0 on a still
    icon; `moving_only` keeps neighbourhoods whose stored pose spans at least
    MOVING_PX, where a quantised centre must step."""
    out = []
    for c in chains:
        for i in range(2, len(c) - 2):
            nb = c[i - 2:i + 3]
            if moving_only:
                P = np.array([pose_getter(x) for x in nb], float)
                if math.hypot(*(P.max(0) - P.min(0))) < MOVING_PX:
                    continue
            vals = [getter(x) for x in nb]
            if any(v is None or v[0] is None for v in vals):
                continue
            t = np.array([float(x["t_ms"]) for x in nb]) / 1000.0
            t = t - t[2]
            X = np.stack([np.ones(5), t, t * t], 1)
            H = X @ np.linalg.pinv(X)
            h = H[2, 2]
            V = np.array(vals, float)
            r = V[2] - (H[2] @ V)
            out.append(r / math.sqrt(max(1.0 - h, 1e-6)))
    if not out:
        return {"n": 0}
    R = np.array(out)
    sig = np.sqrt((R ** 2).mean(0))
    return {"n": int(len(R)), "sigma_x": round(float(sig[0]), 4), "sigma_y": round(float(sig[1]), 4),
            "sigma_2d": round(float(math.hypot(sig[0], sig[1])), 4),
            "median_abs_2d": round(float(np.median(np.hypot(R[:, 0], R[:, 1]))), 4)}


def _stability(sid, between, fits, t_star, g_star) -> dict:
    """Centre stability on icons both A (reason eligible) and E2 accept."""
    both = [f for f in fits if not f.get("split") and _accept(f, t_star, g_star)
            and f["src"]["reason"] == "eligible"]
    pose = lambda f: (f["src"]["cx"], f["src"]["cy"])  # noqa: E731
    chains = _chains(both, pose)
    get = {"e2": lambda f: (f["cx"], f["cy"]),
           "stored_pose": pose,
           "ring": lambda f: ((f["src"].get("ring") or {}).get("cx"), (f["src"].get("ring") or {}).get("cy"))}
    out = {"chains": len(chains), "chain_frames": sum(len(c) for c in chains)}
    for moving in (False, True):
        out["moving" if moving else "all"] = {k: _smooth_resid(chains, g, moving, pose) for k, g in get.items()}
    crlb = [f["crlb_px"] for c in chains for f in c]
    out["crlb_px_median"] = round(float(np.median(crlb)), 4) if crlb else None
    s2 = out["all"]["e2"].get("sigma_2d")
    out["observed_over_crlb"] = round(s2 / out["crlb_px_median"], 2) if s2 and out["crlb_px_median"] else None
    return out


def _pale(sid, between, fits, t_star, g_star) -> dict | None:
    """Stored icons `capture_psf`'s fit called pale (teal < 0.5): how many E2 accepts."""
    p = STORE / "analysis" / "capture-psf-20261001" / f"{sid}_{_slice_tag(between)}_icons.json"
    if not p.is_file():
        return None
    rows = [r for r in json.loads(p.read_text(encoding="utf-8"))["icons"]
            if r["family"] == "ally" and r["psf"]["teal"] < 0.5]
    by_t = defaultdict(list)
    for f in fits:
        if not f.get("split"):
            by_t[float(f["t_ms"])].append(f)
    hit = acc = 0
    teal = []
    for r in rows:
        near = [f for f in by_t[float(r["t_ms"])]
                if math.hypot(f["src"]["cx"] - r["stored"]["cx"], f["src"]["cy"] - r["stored"]["cy"]) <= HIT_PX]
        if not near:
            continue
        hit += 1
        f = min(near, key=lambda f: math.hypot(f["src"]["cx"] - r["stored"]["cx"],
                                               f["src"]["cy"] - r["stored"]["cy"]))
        teal.append(f["teal"])
        acc += _accept(f, t_star, g_star)
    return {"psf_pale": len(rows), "fitted": hit, "e2_accepts": acc,
            "e2_teal_median": round(float(np.median(teal)), 3) if teal else None}


def _diff(sid, between, fits, ra, base, t_star, g_star, splits=True) -> dict:
    """E2 accepts A lacks (added) and A's icons E2 does not accept (dropped),
    split by A's residual on the frame."""
    acc = _accepted(fits, t_star, g_star, splits)
    a_ic = defaultdict(list)
    for i in base["icons"]:
        if i["family"] != "barrier":
            a_ic[float(i["t_ms"])].append(i)
    added, dropped = [], []
    for t, r in ra.items():
        for f in acc[t]:
            if not any(math.hypot(i["cx"] - f["cx"], i["cy"] - f["cy"]) <= HIT_PX for i in a_ic[t]):
                added.append({"t_ms": t, "cx": f["cx"], "cy": f["cy"], "resid_A": r, "fit": f})
        for i in a_ic[t]:
            if not any(math.hypot(i["cx"] - f["cx"], i["cy"] - f["cy"]) <= HIT_PX for f in acc[t]):
                dropped.append({"t_ms": t, "cx": i["cx"], "cy": i["cy"], "resid_A": r,
                                "fit": next((f for f in fits if float(f["t_ms"]) == t and
                                             math.hypot(f["src"]["cx"] - i["cx"], f["src"]["cy"] - i["cy"])
                                             <= HIT_PX), None)})
    return {"added": added, "dropped": dropped,
            "counts": {"added_under": sum(a["resid_A"] < 0 for a in added),
                       "added_at_or_over": sum(a["resid_A"] >= 0 for a in added),
                       "dropped_over": sum(d["resid_A"] > 0 for d in dropped),
                       "dropped_at_or_under": sum(d["resid_A"] <= 0 for d in dropped)}}


def score(calib: list[str], test: list[str]) -> dict:
    """Choose (t*, g*) by pooled calibration MAE; freeze; score the test slices."""
    store = Store(STORE)
    mae = lambda v: float(np.abs(v).mean())  # noqa: E731
    cal = [_parse_slice(x) for x in calib]
    cal_fits = {x: _load_fits(*c)["fits"] for x, c in zip(calib, cal)}
    surface, a_mae = {}, None
    for sp in (False, True):
        for t_star in T_GRID:
            for g_star in G_GRID:
                errs, errs_a = [], []
                for x, (sid, bw) in zip(calib, cal):
                    ra, rb, _ = _residuals(store, sid, bw, cal_fits[x], t_star, g_star, sp)
                    errs += [abs(v) for v in rb.values()]
                    errs_a += [abs(v) for v in ra.values()]
                surface[(t_star, g_star, sp)] = float(np.mean(errs))
                a_mae = float(np.mean(errs_a))
    # ties go to the stricter rule and to no splits
    best = min(surface, key=lambda k: (surface[k], k[2], -k[0], -k[1]))
    t_star, g_star, use_split = best
    vals = np.array(list(surface.values()))
    # Sanity: what A accepts, E2 should mostly keep on calibration.
    elig = [f for x in calib for f in cal_fits[x] if not f.get("split") and f["src"]["reason"] == "eligible"]
    rej = sum(not _accept(f, t_star, g_star) for f in elig) / max(len(elig), 1)
    out = {"version": VERSION, "task": TASK, "calib": calib, "test": test,
           "t_star": t_star, "g_star": g_star, "splits": use_split,
           "calib_mae": round(surface[best], 4), "calib_mae_A": round(a_mae, 4),
           "calib_mae_accept_all": round(surface[(0.0, -1e9, False)], 4),
           "calib_mae_best_no_split": round(min(v for k, v in surface.items() if not k[2]), 4),
           "calib_mae_best_split": round(min(v for k, v in surface.items() if k[2]), 4),
           "surface": {f"{k[0]}|{k[1]}|{int(k[2])}": round(v, 4) for k, v in surface.items()},
           "sanity": {"interior_t": T_GRID[0] < t_star < T_GRID[-1],
                      "interior_g": G_GRID[0] < g_star < G_GRID[-1],
                      "surface_range": round(float(vals.max() - vals.min()), 4),
                      "A_eligible_rejected": round(rej, 4), "A_eligible_n": len(elig)},
           "results": {}}
    for x in calib + test:
        sid, bw = _parse_slice(x)
        F = _load_fits(sid, bw)
        fits = F["fits"]
        ra, rb, base = _residuals(store, sid, bw, fits, t_star, g_star, use_split)
        d_mae = ut._boot(ra, rb, mae)
        dd = _diff(sid, bw, fits, ra, base, t_star, g_star, use_split)
        out["results"][x] = {
            "role": "calib" if x in calib else "test",
            "rests_on": F["rests_on"], "agents": F["agents"], "source": F["source"],
            "A": ut._metrics(ra), "E2": ut._metrics(rb), "d_mae": d_mae,
            "noise_bound_mae": round((d_mae[2] - d_mae[1]) / 2, 4),
            "diff": dd["counts"], "pale": _pale(sid, bw, fits, t_star, g_star),
            "stability": _stability(sid, bw, fits, t_star, g_star),
            "E2_no_split": ut._metrics(_residuals(store, sid, bw, fits, t_star, g_star, False)[1]),
            "E2_split": ut._metrics(_residuals(store, sid, bw, fits, t_star, g_star, True)[1]),
            "split_mates_accepted": sum(len([f for f in v if f.get("split")])
                                        for v in _accepted(fits, t_star, g_star).values()),
            "fits": len(fits),
            "accepted": sum(len(v) for v in _accepted(fits, t_star, g_star, use_split).values())}
        (OUT / f"e2_diff_{sid}_{_slice_tag(bw)}.json").write_text(
            json.dumps({"t_star": t_star, "g_star": g_star, **dd}), encoding="utf-8")
    (OUT / "e2_score.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "surface"}, indent=1))
    return out


# ------------------------------------------------------------------ sheet
def _render_fit(m, f, names):
    """Observed and rendered Y, Cb, Cr windows (3, n, n) for one stored fit."""
    import torch
    p = torch.as_tensor(f["job"]["p"], device=m.obs.device, dtype=torch.float32)[None]
    ag = torch.as_tensor([[names.index(a) for a in f["job"]["agents"]]], device=m.obs.device)
    ar = p[:, None]
    _, coefs = m.loss(ar[..., 0], ar[..., 1], ar[..., 2], torch.deg2rad(ar[..., 3]), ag[:, None],
                      want_coef=True)
    icons, Bg = m.render_parts(ar[..., 0], ar[..., 1], ar[..., 2], torch.deg2rad(ar[..., 3]), ag[:, None])
    Xs = m.design(icons, Bg)
    n = 2 * m.half + 1
    return np.stack([(Xs[k] * coefs[k][..., None]).sum(2)[0, 0].reshape(n, n).cpu().numpy()
                     for k in range(3)])


def sheet(sid: str, between=None, n: int = 12, D: dict | None = None, sfx: str = "") -> list[Path]:
    """Observed / model / residual (luma x3 + 128) for n added and n dropped
    icons (seed 7), 8x nearest (display only); E2 centre red, A's green.
    `D` replaces the stored diff (sides `added`, `dropped`) for a check sheet."""
    import torch
    store, man, profile, ctx = ut._session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    src = lr.source_of(man)
    F = _load_fits(sid, between)
    if D is None:
        D = json.loads((OUT / f"e2_diff_{sid}_{_slice_tag(between)}.json").read_text(encoding="utf-8"))
    rd = ally_icon_reader(ctx)
    x0, y0, x1, y1 = rd.box
    st = lr.ycc(rd.static)
    ms, half, names = F["map_scale"], F["half"], F["agents"]
    art = art_tensor(names)
    nwin = 2 * half + 1
    pad = half + 2 + int(math.ceil(2 * ALLY.r_out * ms * PAIR_FRAC))
    stp = np.pad(st, ((pad, pad), (pad, pad), (0, 0)), mode="edge")
    rng = np.random.default_rng(7)
    paths = []
    for side in ("added", "dropped"):
        items = [x for x in D[side] if x["fit"] is not None]
        pick = [items[i] for i in sorted(rng.choice(len(items), min(n, len(items)), replace=False))] if items else []
        tiles = []
        frames = {float(s.t_ms): s.frame for s in cache.samples(sorted({x["t_ms"] for x in pick}),
                                                                 rois=("minimap",))}
        for x in pick:
            f = x["fit"]
            ox, oy = f["job"]["origin"]
            crop = frames[float(x["t_ms"])][y0:y1, x0:x1]
            yc = np.pad(lr.ycc(crop), ((pad, pad), (pad, pad), (0, 0)), mode="edge")
            sy, sx = oy + pad, ox + pad
            ob = yc[sy:sy + nwin, sx:sx + nwin]
            sp = stp[sy - 2:sy + nwin + 2, sx - 2:sx + nwin + 2]
            m = Model(np.moveaxis(ob, 2, 0).reshape(1, 3, -1), np.moveaxis(sp, 2, 0)[None],
                      np.ones((1, nwin * nwin), np.float32), np.array([x0 + ox - 2]), np.array([y0 + oy - 2]),
                      ms, half, src, art)
            with torch.no_grad():
                R = _render_fit(m, f, names)
            O = np.moveaxis(ob, 2, 0)
            obs_bgr = cv2.cvtColor(np.clip(np.stack([O[0], O[2], O[1]], 2), 0, 255).astype(np.uint8),
                                   cv2.COLOR_YCrCb2BGR)
            mod_bgr = cv2.cvtColor(np.clip(np.stack([R[0], R[2], R[1]], 2), 0, 255).astype(np.uint8),
                                   cv2.COLOR_YCrCb2BGR)
            res = np.clip((O[0] - R[0]) * 3 + 128, 0, 255).astype(np.uint8)
            row = np.hstack([obs_bgr, mod_bgr, cv2.cvtColor(res, cv2.COLOR_GRAY2BGR)])
            big = cv2.resize(row, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST)
            for k in range(3):
                for (cx, cy), col in (((f["cx"] - ox, f["cy"] - oy), (0, 0, 255)),
                                      ((f["src"]["cx"] - ox, f["src"]["cy"] - oy), (0, 255, 0))):
                    cv2.circle(big, (int((cx + 0.5) * 8) + k * nwin * 8, int((cy + 0.5) * 8)), 3, col, -1)
            lab = (f"{x['t_ms'] / 1000:.2f}s A{x['resid_A']:+d} {f['agent']} teal {f['teal']:.2f} "
                   f"gain {f['gain_px']:.1f} {f['src']['reason']}")
            cv2.putText(big, lab, (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1, cv2.LINE_AA)
            tiles.append(cv2.copyMakeBorder(big, 0, 3, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 255)))
        if not tiles:
            continue
        img = np.vstack(tiles)
        p = OUT / f"e2_sheet_{side}_{sid}_{_slice_tag(between)}{sfx}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
        print(f"wrote {p}")
    return paths


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("cands", "fit", "sheet"):
        a = sub.add_parser(name)
        a.add_argument("session")
        a.add_argument("--between", nargs=2, type=float)
        if name == "fit":
            a.add_argument("--limit", type=int)
    a = sub.add_parser("score")
    a.add_argument("--calib", nargs="+", required=True)
    a.add_argument("--test", nargs="+", required=True)
    args = ap.parse_args(argv)
    ut._idle()
    try:
        import torch
        torch.set_num_threads(2)
    except Exception:
        pass
    if args.cmd == "score":
        score(args.calib, args.test)
        return 0
    if args.cmd == "sheet":
        sheet(args.session, args.between)
        return 0
    if args.cmd == "cands":
        cands(args.session, args.between)
    elif args.cmd == "fit":
        fit(args.session, args.between, limit=args.limit)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
