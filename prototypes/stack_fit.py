r"""Stacked teammate icons fitted jointly: k teardrops over the baked map,
scored softly against the crop's tealness (`stack-fit-0.2.0`).

    .\.venv\Scripts\python.exe prototypes\stack_fit.py fit SESSION --between T0 T1 --out DIR [--no-cap] [--lam L] [--stride N] [--tag TAG]
    .\.venv\Scripts\python.exe prototypes\stack_fit.py size --master MASTER.json --stack STACK.json
    .\.venv\Scripts\python.exe prototypes\stack_fit.py sheet SESSION --between T0 T1 --out DIR --master MASTER.json --stack STACK.json [--n N]
    .\.venv\Scripts\python.exe prototypes\stack_fit.py labels --out DIR [--lam L]
    .\.venv\Scripts\python.exe prototypes\stack_fit.py crops SESSION T_S CX CY --name NAME --out DIR [--master M.json] [--stack S.json]

Task `stacked-icons-20261002` in the store's `notes/predictions.jsonl`.

**The fault at master.** `minimap.icons(seed="surface")` makes ONE ring fit
per connected component of the closed teal key, the best circumference
coverage anywhere within `r_max` of it, over radii `R_MIN..R_MAX` times the
WIDGET scale (6..9 px at 331 px). Two touching teammates, or a teammate
touching teal clutter, are one component and get one circle, and a circle
threaded through two rims can score more coverage than either icon's own
ring. On the four test slices the between fits were r 6 with a `ring_fit`
pose (the teardrop refused them), not oversized; the 331 px icon's outer
radius is 6.7 px (`ICON_CLASSES['ally'].r_out` times `geometry.map_scale`,
docs/CAPTURE_PSF.md), while the radius range reaches 9 px. `_gated` and `ally_decisions` then keep the best-covered fit within
`MIN_ICON_SEPARATION_PX` times the widget scale (11.4 px) and drop the rest:
a separation rule, not a likelihood, and it never asks whether the kept
circle explains the pixels.

**The model.** Each teammate is `teardrop.render`'s silhouette at the
class radii times `geometry.map_scale` (the one scale transform), teal on
its ring and lobe, opaque over its portrait disc, with a free gain in
`[G_MIN, G_MAX]`. Icons composite bottom to top over the baked static's own
tealness [domain:capture/session-pixels-are-not-the-map]; a pixel is
explained by the icon on top of it. The residual against the crop's
continuous tealness (`teardrop.tealness`, no threshold) is a truncated
square, so clutter no sprite models costs a fixed amount. The search is
greedy forward selection from matched-filter peaks with every member
refined given the others, then backward elimination: an icon stays only
while removing it would cost more than `LAM` (times the icon's area
scale). So a circle between two teammates loses its pixels to them and is
removed; nothing is merged by distance.

**Gates from other channels.** `--no-cap` fits the pixels alone; otherwise
the roster's capacity (`round_lifetimes.ally_capacity`, the owner of the
alive count) caps how many teammates the frame may hold, and the output
declares it under `rests_on`. Barriers keep master's rule
(`minimap._mark_barriers`). The spike glyph is not modelled.

Reads the minimap crop cache only; never decodes; writes under `--out`.

**Outcome (2026-10-02; `wire: no`).** Explaining-away removes master's
between-icon fits and recovers both icons of a pair, but the teal key loses
labelled teammates: the G - B ramp erases the pale-cyan ring, and plain
tealness still loses 331 px rings under 4:2:0 chroma. Dynamic teal fills
(bfad2778a372) fill the roster cap with phantoms. The successor scores the
same k-icon search against a luma-and-chroma render (`capture_psf`). The
predictions and the outcome are under this task in `notes/predictions.jsonl`.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "4")

import argparse
import bisect
import json
import math
import sys
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reticle import geometry, minimap, teardrop  # noqa: E402
from reticle.decode import Sample  # noqa: E402
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.round_lifetimes import ally_capacity  # noqa: E402
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

VERSION = "stack-fit-0.2.0"
TASK = "stacked-icons-20261002"
ALLY = teardrop.ICON_CLASSES["ally"]

N_TH = 24            # matched-filter facings (15 degrees)
G_MIN, G_MAX = 0.3, 1.3
TRUNC = 0.5          # residual truncation, tealness units
LAM = 2.0            # existence cost at map scale 1.0; scales with area. Chosen on the
                     # calibration windows 223d636bf8d2 1090-1250 and a06f04a0059f 440-600
                     # (lowest capped roster MAE of 2..30) before any test slice was fitted
PROP_TOP = 10        # proposals per cluster
TEAL_SEED = 0.25     # a cluster grows from tealness above this
MAX_ALLIES = minimap.MAX_ALLIES
CHUNK_PX = 2_000_000  # pose-pixels per candidate batch
VIS_MIN = 0.3        # a member shows at least this share of its teal (added after
                     # the first test sheets showed coincident duplicates)


def _priority():
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL
    except Exception:
        pass
    cv2.setNumThreads(4)


def _dev():
    import torch
    # Every cluster window has its own size, and cuDNN keeps a plan per
    # convolution shape: host memory grew about 15 MB a frame with it on.
    torch.backends.cudnn.enabled = False
    return "cuda" if torch.cuda.is_available() else "cpu"


# ------------------------------------------------------------------ the model

class Shape:
    """The ally teardrop at one session's map scale."""

    def __init__(self, scale: float, lam: float = None):
        self.scale = scale
        self.r_in, self.r_out, self.L = ALLY.r_in * scale, ALLY.r_out * scale, ALLY.L * scale
        self.edge = teardrop.EDGE * scale
        self.reach = int(math.ceil(self.L + self.edge + 1))
        self.lam = (LAM if lam is None else lam) * scale * scale
        # the ring fit's integer radius master's descriptors read at
        self.r_int = int(round((self.r_in + self.r_out) / 2))

    def layers(self, dx, dy, th):
        """Teal coverage `t` (ring and lobe) and opaque coverage `o` (the
        whole teardrop, portrait included), torch, broadcasting."""
        import torch
        c, s = torch.cos(th), torch.sin(th)
        u = dx * c + dy * s
        v = -dx * s + dy * c
        rho = torch.sqrt(dx * dx + dy * dy)
        ca = self.r_out / self.L
        sa = math.sqrt(max(0.0, 1.0 - ca * ca))
        d_wedge = u * ca + v.abs() * sa - self.r_out
        d_tri = torch.maximum(d_wedge, torch.maximum(self.r_out * ca - u, u - self.L))
        d_tear = torch.minimum(rho - self.r_out, d_tri)
        o = torch.clamp(0.5 - d_tear / self.edge, 0.0, 1.0)
        t = torch.clamp(0.5 - torch.maximum(d_tear, self.r_in - rho) / self.edge, 0.0, 1.0)
        return t, o


class Window:
    """One cluster's pixels on the device: tealness T, background tealness B,
    weight W, with pixel-centre coordinates X, Y in crop px."""

    def __init__(self, T, B, Wt, x0, y0):
        import torch
        dev = _dev()
        self.T = torch.as_tensor(T, device=dev, dtype=torch.float32)
        self.B = torch.as_tensor(B, device=dev, dtype=torch.float32)
        self.W = torch.as_tensor(Wt, device=dev, dtype=torch.float32)
        h, w = T.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.X = torch.as_tensor(xx + x0, device=dev)
        self.Y = torch.as_tensor(yy + y0, device=dev)
        self.x0, self.y0 = x0, y0

    def composite(self, shape: Shape, S: list[dict]):
        """`(a, c)` with the set's render over a layer `Z` equal to `a + c * Z`."""
        import torch
        a = torch.zeros_like(self.T)
        c = torch.ones_like(self.T)
        for m in S:  # bottom to top
            t, o = shape.layers(self.X - m["x"], self.Y - m["y"], torch.tensor(math.radians(m["deg"]),
                                                                              device=self.T.device))
            a = m["g"] * t + (1 - o) * a
            c = (1 - o) * c
        return a, c

    def visible(self, shape: Shape, S: list[dict]):
        """Per member, the share of its own teal the members above it leave
        showing: a teardrop drawn wholly under another is no evidence."""
        import torch
        lay = [shape.layers(self.X - m["x"], self.Y - m["y"],
                            torch.tensor(math.radians(m["deg"]), device=self.T.device)) for m in S]
        out = []
        for i, (t, _) in enumerate(lay):
            c = torch.ones_like(self.T)
            for _, o in lay[i + 1:]:
                c = c * (1 - o)
            out.append(float((self.W * t * c).sum() / (self.W * t).sum().clamp(min=1e-6)))
        return out

    def loss_of(self, R):
        import torch
        return (self.W * torch.clamp(R * R, max=TRUNC * TRUNC)).sum(dim=(-2, -1))

    def set_loss(self, shape: Shape, S: list[dict]) -> float:
        a, c = self.composite(shape, S)
        return float(self.loss_of(self.T - (a + c * self.B)))

    def candidates(self, shape: Shape, S: list[dict], poses):
        """Loss and gain of each pose (N, 3: x, y, deg) added on top of `S`
        and under it. Returns (loss (N, 2), gain (N, 2)). Poses go in chunks
        of at most `CHUNK_PX` pose-pixels: a large window otherwise holds
        gigabytes in the allocator's cache."""
        import torch
        a, c = self.composite(shape, S)
        P = torch.as_tensor(poses, device=self.T.device, dtype=torch.float32)
        n = max(1, CHUNK_PX // max(1, self.T.numel()))
        Ls, Gs = [], []
        for i in range(0, len(P), n):
            L, G = self._cand(shape, a, c, P[i:i + n])
            Ls.append(L)
            Gs.append(G)
        return torch.cat(Ls), torch.cat(Gs)

    def _cand(self, shape: Shape, a, c, P):
        import torch
        dx = self.X[None] - P[:, 0, None, None]
        dy = self.Y[None] - P[:, 1, None, None]
        t, o = shape.layers(dx, dy, torch.deg2rad(P[:, 2])[:, None, None])
        T, B, W = self.T[None], self.B[None], self.W[None]
        # on top: M = g t + (1 - o)(a + c B)
        U = (1 - o) * (a + c * self.B)[None]
        g_top = ((W * t * (T - U)).sum((-2, -1)) / (W * t * t).sum((-2, -1)).clamp(min=1e-6))
        g_top = g_top.clamp(G_MIN, G_MAX)
        L_top = self.loss_of(T - (g_top[:, None, None] * t + U))
        # underneath: M = a + c (g t + (1 - o) B)
        ct = c[None] * t
        V = a[None] + c[None] * (1 - o) * self.B[None]
        g_bot = ((W * ct * (T - V)).sum((-2, -1)) / (W * ct * ct).sum((-2, -1)).clamp(min=1e-6))
        g_bot = g_bot.clamp(G_MIN, G_MAX)
        L_bot = self.loss_of(T - (V + g_bot[:, None, None] * ct))
        return torch.stack([L_top, L_bot], 1), torch.stack([g_top, g_bot], 1)

    def proposals(self, shape: Shape, top: int = PROP_TOP):
        """Matched-filter peaks: the quadratic loss drop of one icon at each
        integer centre and facing, over the background alone."""
        import torch
        import torch.nn.functional as F
        R = ((self.T - self.B) * self.W)[None, None]
        k = shape.reach
        g = torch.arange(-k, k + 1, device=self.T.device, dtype=torch.float32)
        ky, kx = torch.meshgrid(g, g, indexing="ij")
        ths = torch.arange(N_TH, device=self.T.device, dtype=torch.float32) * (2 * math.pi / N_TH)
        t, _ = shape.layers(kx[None], ky[None], ths[:, None, None])         # (N_TH, K, K)
        s = F.conv2d(F.pad(R, (k, k, k, k)), t[:, None])[0]                  # (N_TH, h, w)
        n = (t * t).sum((-2, -1))[:, None, None]
        gg = (s / n).clamp(G_MIN, G_MAX)
        d = 2 * gg * s - gg * gg * n
        best, arg = d.max(0)
        peak = (best == F.max_pool2d(best[None, None], 5, 1, 2)[0, 0]) & (best > shape.lam * 0.5)
        ys, xs = torch.nonzero(peak, as_tuple=True)
        if not len(ys):
            return []
        v = best[ys, xs]
        order = torch.argsort(v, descending=True)[:top]
        out = []
        for i in order.tolist():
            y, x = int(ys[i]), int(xs[i])
            out.append({"x": float(x + self.x0), "y": float(y + self.y0),
                        "deg": float(arg[y, x]) * 360.0 / N_TH, "drop": float(v[i])})
        return out


GRID1 = [(dx, dy, dt) for dx in (-1, -0.5, 0, 0.5, 1) for dy in (-1, -0.5, 0, 0.5, 1)
         for dt in (-15, -7.5, 0, 7.5, 15)]
GRID2 = [(dx, dy, dt) for dx in (-0.25, 0, 0.25) for dy in (-0.25, 0, 0.25)
         for dt in (-3.75, 0, 3.75)]


def _refine(win: Window, shape: Shape, S: list[dict], seeds: list[dict]):
    """Each seed refined against `S` on two grids, all seeds in one batch;
    returns, per seed, the best `(loss, member, place)` with place 'top' or
    'bottom'."""
    if not seeds:
        return []
    cur = np.array([(sd["x"], sd["y"], sd["deg"]) for sd in seeds], np.float32)
    n = len(seeds)
    for grid in (GRID1, GRID2):
        g = np.asarray(grid, np.float32)
        poses = (cur[:, None, :] + g[None]).reshape(-1, 3)
        L, G = win.candidates(shape, S, poses)
        L = L.reshape(n, len(grid), 2).cpu().numpy()
        G = G.reshape(n, len(grid), 2).cpu().numpy()
        flat = L.reshape(n, -1).argmin(1)
        i, j = np.divmod(flat, 2)
        cur = poses.reshape(n, len(grid), 3)[np.arange(n), i]
    out = []
    for k in range(n):
        out.append((float(L[k, i[k], j[k]]), {"x": float(cur[k, 0]), "y": float(cur[k, 1]),
                                              "deg": float(cur[k, 2]) % 360.0,
                                              "g": float(G[k, i[k], j[k]])},
                    ("top", "bottom")[int(j[k])]))
    return out


def _place(S, m, where):
    return S + [m] if where == "top" else [m] + S


def fit_window(win: Window, shape: Shape, cap: int | None = None):
    """Greedy forward selection, joint refinement and backward elimination
    on one window. Returns (members bottom to top, each with `margin`)."""
    seeds = win.proposals(shape)
    S: list[dict] = []
    L_S = win.set_loss(shape, S)
    used = set()
    # A window holds at most the four teammates plus clutter; the bound keeps
    # a cluttered window from costing seconds.
    limit = MAX_ALLIES + 2 if cap is None else cap
    while seeds and len(S) < limit:
        cand = [(k, r) for k, r in zip(range(len(seeds)), _refine(win, shape, S, seeds))
                if k not in used]
        if not cand:
            break
        k, (L_new, m, where) = min(cand, key=lambda kr: kr[1][0])
        if L_S - L_new <= shape.lam:
            break
        used.add(k)
        S = _place(S, m, where)
        L_S = L_new
        # each member refined with the others held, in its place
        for i in range(len(S)):
            rest = S[:i] + S[i + 1:]
            (L_i, m_i, where_i), = _refine(win, shape, rest, [S[i]])
            if L_i < L_S - 1e-6:
                S = _place(rest, m_i, where_i)
                L_S = L_i
    # backward elimination: an icon whose pixels the others now explain goes,
    # and so does one the icons above it hide (`VIS_MIN`)
    while S:
        vis = win.visible(shape, S)
        i = int(np.argmin(vis))
        if vis[i] < VIS_MIN:
            S = S[:i] + S[i + 1:]
            L_S = win.set_loss(shape, S)
            continue
        drops = [win.set_loss(shape, S[:i] + S[i + 1:]) - L_S for i in range(len(S))]
        i = int(np.argmin(drops))
        if drops[i] > shape.lam:
            for m, d, v in zip(S, drops, vis):
                m["margin"] = float(d)
                m["visible"] = float(v)
            break
        S = S[:i] + S[i + 1:]
        L_S = win.set_loss(shape, S)
    return S


# --------------------------------------------------------------- one frame

#: The lit floor is tinted toward cyan: B and G about 30 over R with G - B
#: near zero (e37fdeca944f 1342.55 s: (191, 193, 164)), which `tealness`
#: scores 0.3-0.5. The icon's teal holds G 20-50 over B (`tealness`'s own
#: note), so the key fades out as G - B falls from 20 to 4.
GB_RAMP = (4.0, 20.0)


def ally_key(img):
    """`teardrop.tealness` times a soft ramp on G - B: teal, not lit floor."""
    c = img.astype(np.float32)
    gb = np.clip((c[..., 1] - c[..., 0] - GB_RAMP[0]) / (GB_RAMP[1] - GB_RAMP[0]), 0.0, 1.0)
    return teardrop.tealness(img) * gb


def frame_maps(crop, static, floor):
    T = ally_key(crop)
    B = ally_key(static)
    Wt = floor.astype(np.float32)
    # The player's icon draws over teammates; its pixels explain no teammate.
    yel = teardrop.yellowness(crop) > 0.3
    yel = cv2.dilate(yel.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    Wt[yel] = 0.0
    return T, B, Wt


def clusters(T, Wt, slab, shape: Shape):
    """Windows round connected teal on the slab, grown by the icon's reach."""
    seed = (T > TEAL_SEED) & (Wt > 0)
    g = int(math.ceil(shape.r_out))
    grown = cv2.dilate(seed.astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(grown, 8)
    H, W = T.shape
    out = []
    min_px = max(4, int(0.25 * 2 * math.pi * shape.r_out))
    for i in range(1, n):
        mine = (lbl == i) & seed
        if mine.sum() < min_px or not (mine & slab).any():
            continue
        x, y, w, h = (int(v) for v in st[i, :4])
        m = shape.reach
        a, b = max(0, y - m), min(H, y + h + m)
        c, d = max(0, x - m), min(W, x + w + m)
        out.append((a, b, c, d))
    # Windows that overlap share pixels; fitted apart, one icon in the overlap
    # was found twice. Merge them until none overlap.
    merged = True
    while merged:
        merged = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                (a, b, c, d), (e, f, g, h) = out[i], out[j]
                if a < f and e < b and c < h and g < d:
                    out[i] = (min(a, e), max(b, f), min(c, g), max(d, h))
                    del out[j]
                    merged = True
                    break
            if merged:
                break
    return out


def fit_frame(crop, static, floor, slab, shape: Shape, cap: int | None = None,
              ref_gray=None):
    T, B, Wt = frame_maps(crop, static, floor)
    wins = clusters(T, Wt, slab, shape)
    icons = []
    # The cap is per frame: windows fitted uncapped, then the frame keeps
    # its `cap` largest margins.
    for (a, b, c, d) in wins:
        win = Window(T[a:b, c:d], B[a:b, c:d], Wt[a:b, c:d], c, a)
        S = fit_window(win, shape, cap=None)
        del win
        for depth, m in enumerate(S):
            icons.append({**m, "depth": depth, "window": [c, a, d, b], "stacked": len(S) > 1})
    icons.sort(key=lambda m: -m.get("margin", 0.0))
    # master's barrier rule on every icon, at master's integer radius; the
    # cap then counts teammates only
    if icons:
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        ref = (cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.float32)
               if ref_gray is None else ref_gray)
        keyed = minimap.ally_mask(crop) | minimap.self_mask(crop)
        fs = [{"cx": m["x"], "cy": m["y"], "r": shape.r_int} for m in icons]
        minimap._mark_barriers(fs, keyed, grey, ref)
        for m, f in zip(icons, fs):
            m["map_diff"], m["barrier"] = f["map_diff"], f["barrier"]
    mates = [m for m in icons if not m["barrier"]]
    kept = mates if cap is None else mates[:cap]
    for m in icons:
        m["capped"] = not m["barrier"] and m not in kept
    return icons


# ------------------------------------------------------------------ sessions

class Session:
    def __init__(self, sid: str, lam: float | None = None):
        self.sid = sid
        self.store = Store(DEFAULT_STORE)
        self.man = self.store.read_manifest(sid)
        self.profile = get_profile(self.man["source_profile"])
        ctx = SessionContext(store=self.store, manifest=self.man, profile=self.profile)
        r = minimap.ally_icon_reader(ctx)
        self.floor, self.slab, self.static, self.box = r.floor, r.slab, r.static, r.box
        self.ref = r.ref
        self.width = self.box[2] - self.box[0]
        k = geometry.key_of(sid)
        ms = geometry.map_scale(k)
        if ms is None:
            raise SystemExit(f"{sid}: {k} has no map scale; refusing")
        self.ms = ms
        self.shape = Shape(ms.scale, lam)
        self.cache, why = RoiCache.load(self.store.root, self.man, self.profile, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why}); not decoding")
        self.frames = {float(r["t_ms"]): r for r in self.store.read_events_kind("ally_icon", sid, "frame")
                       if r.get("kind") == "frame"}

    def drawn_between(self, t0, t1):
        return sorted(t for t, r in self.frames.items()
                      if r.get("widget_drawn") and t0 * 1000 <= t <= t1 * 1000)

    def crops(self, times):
        x0, y0, x1, y1 = self.box
        for smp in self.cache.samples(list(times), rois=("minimap",)):
            yield float(smp.t_ms), smp.frame[y0:y1, x0:x1]

    def capacity(self, times):
        """The roster's ally capacity per time where the stored frame saw the
        player's icon in a round (`round_lifetimes.ally_capacity`)."""
        date = self.man["ingested_at"][:10]
        try:
            t = self.store.read_roster(self.sid, date)
            rounds = build_rounds(self.store.read_hud(self.sid, date))
        except SystemExit:
            return {}
        rt, ra = t.column("t_ms").to_pylist(), t.column("alive_ally").to_pylist()
        out = {}
        for x in times:
            f = self.frames.get(x)
            if not f or not f.get("widget_drawn") or not f.get("self"):
                continue
            if not any(r["t_start_ms"] <= x < r["t_end_ms"] for r in rounds):
                continue
            i = bisect.bisect_right(rt, x) - 1
            cap = ally_capacity(ra[i], True) if i >= 0 else None
            if cap is not None:
                out[x] = cap
        return out


def _icon_row(m):
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in m.items()}


def run_fit(sid, t0, t1, out: Path, cap_on: bool, tag: str, lam: float | None = None,
            stride: int = 1):
    s = Session(sid, lam)
    times = s.drawn_between(t0, t1)[::stride]
    caps = s.capacity(times)
    rows = []
    t_fit = 0.0
    for t, crop in s.crops(times):
        cap = caps.get(t) if cap_on else None
        q = time.perf_counter()
        icons = fit_frame(crop, s.static, s.floor, s.slab, s.shape, cap=cap, ref_gray=s.ref)
        t_fit += time.perf_counter() - q
        rows.append({"t_ms": t, "cap": caps.get(t), "icons": [_icon_row(m) for m in icons]})
    res = {"version": VERSION, "task": TASK, "sid": sid, "between": [t0, t1], "width": s.width,
           "map_scale": s.ms.provenance(), "lam": s.shape.lam, "cap_on": cap_on,
           "rests_on": "round_lifetimes.ally_capacity over the stored roster" if cap_on else None,
           "frames": rows, "fit_s_per_frame": round(t_fit / max(1, len(rows)), 4)}
    out.mkdir(parents=True, exist_ok=True)
    p = out / f"{sid}_{int(t0)}-{int(t1)}_{tag}.json"
    p.write_text(json.dumps(res), encoding="utf-8")
    print(json.dumps({"sid": sid, "frames": len(rows), "fit_s_per_frame": res["fit_s_per_frame"],
                      "out": str(p)}))
    return p


def kept_icons(fr):
    return [m for m in fr["icons"] if not m.get("capped") and not m.get("barrier")]


# ------------------------------------------------------------------ master

def master_frames(s: Session, times):
    """master's accepted ally icons per time: `AllyIconReader` fed the cached
    frames in order and published through the stored decision rule
    (`trial._ally_rows`), in memory. Frames more than 200 ms apart give no
    prior to each other (`teardrop.PRIOR_GAP_MS`)."""
    from reticle.trial import _ally_rows
    ctx = SessionContext(store=s.store, manifest=s.man, profile=s.profile)
    r = minimap.ally_icon_reader(ctx)
    for smp in s.cache.samples(list(times), rois=("minimap",)):
        fr = s.frames[float(smp.t_ms)]
        r.feed(Sample(frame_idx=int(fr["frame_idx"]), t_ms=float(smp.t_ms), frame=smp.frame))
    rows = json.loads(json.dumps(_ally_rows(r, s.sid)["ally_icon"], allow_nan=False))
    by = {}
    for e in rows:
        if e["kind"] == "icon":
            by.setdefault(float(e["t_ms"]), []).append(
                {k: e.get(k) for k in ("cx", "cy", "r", "family", "reason", "pose")})
    return by


def master_kept(icons):
    return [m for m in icons if m.get("family") != "barrier"]


# ------------------------------------------------------------------ labels

LABEL_PX = 3.0


def _labels(store):
    """Player labels of teammate icon centres: `death_icon` (class agent; the
    centre is the detection the player named), `icon_facing_20260928` and
    `ally_facing_331_20260929` (class ally; the player's clicked centre)."""
    root = store.root / "labels"
    out = []
    for p in sorted((root / "death_icon").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("class") == "agent":
                    out.append({"set": "death_icon", "sid": d["session_id"], "t_ms": d["t_ms"],
                                "x": d["cx"], "y": d["cy"], "answer": d.get("answer")})
    for name in ("icon_facing_20260928", "ally_facing_331_20260929"):
        p = root / f"{name}.jsonl"
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                if d.get("cls") == "ally" and d.get("centre_x") is not None:
                    out.append({"set": name, "sid": d["session"], "t_ms": d["t_ms"],
                                "x": d["centre_x"], "y": d["centre_y"], "answer": d.get("answer")})
    return out


def run_labels(out: Path, lam: float | None = None):
    store = Store(DEFAULT_STORE)
    by_sid = {}
    for lab in _labels(store):
        by_sid.setdefault(lab["sid"], []).append(lab)
    res = []
    for sid, ls in sorted(by_sid.items()):
        try:
            s = Session(sid, lam)
        except SystemExit as e:
            res += [{**lab, "skip": str(e)} for lab in ls]
            continue
        drawn = sorted(t for t, r in s.frames.items() if r.get("widget_drawn"))
        if not drawn:
            res += [{**lab, "skip": "no stored drawn frames"} for lab in ls]
            continue
        for lab in ls:
            lab["frame_t"] = min(drawn, key=lambda h: abs(h - lab["t_ms"]))
        times = sorted({lab["frame_t"] for lab in ls})
        mast = master_frames(s, times)
        caps = s.capacity(times)
        joint, nocap, secs = {}, {}, []
        for t, crop in s.crops(times):
            q = time.perf_counter()
            icons = fit_frame(crop, s.static, s.floor, s.slab, s.shape, cap=caps.get(t), ref_gray=s.ref)
            secs.append(time.perf_counter() - q)
            joint[t] = [m for m in icons if not m.get("capped") and not m.get("barrier")]
            nocap[t] = [m for m in icons if not m.get("barrier")]
        for lab in ls:
            t = lab["frame_t"]
            dm = min((math.hypot(m["cx"] - lab["x"], m["cy"] - lab["y"])
                      for m in master_kept(mast.get(t, []))), default=None)
            dj = min((math.hypot(m["x"] - lab["x"], m["y"] - lab["y"]) for m in joint.get(t, [])),
                     default=None)
            dn = min((math.hypot(m["x"] - lab["x"], m["y"] - lab["y"]) for m in nocap.get(t, [])),
                     default=None)
            res.append({**lab, "width": s.width, "dt_ms": round(t - lab["t_ms"], 1), "cap": caps.get(t),
                        "master_d": dm, "joint_d": dj, "joint_nocap_d": dn,
                        "master": dm is not None and dm <= LABEL_PX,
                        "joint": dj is not None and dj <= LABEL_PX,
                        "joint_nocap": dn is not None and dn <= LABEL_PX})
        print(sid, s.width, len(ls), "labels", round(float(np.median(secs)), 3), "s/frame", flush=True)
    out.mkdir(parents=True, exist_ok=True)
    p = out / "labels.json"
    p.write_text(json.dumps(res), encoding="utf-8")
    summ = {}
    for r in res:
        if "skip" in r:
            summ["skipped"] = summ.get("skipped", 0) + 1
            continue
        c = summ.setdefault(f"{r['set']}@{r['width']}", {"n": 0, "master": 0, "joint": 0, "joint_nocap": 0,
                                                         "lost": 0, "gained": 0, "lost_nocap": 0})
        c["n"] += 1
        for f in ("master", "joint", "joint_nocap"):
            c[f] += int(r[f])
        c["lost"] += int(r["master"] and not r["joint"])
        c["gained"] += int(r["joint"] and not r["master"])
        c["lost_nocap"] += int(r["master"] and not r["joint_nocap"])
    print(json.dumps(summ, indent=1))
    return p


# ------------------------------------------------------------------- the size

MATCH_PX = 3.0


def _pairs(pts, lim):
    return [(i, j) for i in range(len(pts)) for j in range(i + 1, len(pts))
            if math.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]) <= lim]


def classify_master(m, jp, r_out):
    """master's fit `m` against the joint icons `jp`: `on_joint` within
    MATCH_PX of one, `between` when two joint icons within 3 r_out of it lie
    on opposite sides, else `other`."""
    ds = sorted((math.hypot(m["cx"] - x, m["cy"] - y), x, y) for x, y in jp)
    if ds and ds[0][0] <= MATCH_PX:
        return "on_joint"
    near = [(x, y) for d, x, y in ds if d <= 3 * r_out]
    opp = any(((x1 - m["cx"]) * (x2 - m["cx"]) + (y1 - m["cy"]) * (y2 - m["cy"])) < 0
              for k, (x1, y1) in enumerate(near) for (x2, y2) in near[k + 1:])
    return "between" if opp else "other"


def size_table(master_run: Path, stack_run: Path):
    """Per frame of the roster population: master's and the joint fit's
    icons; the stack-candidate frames (capacity >= 2 and a pair of either
    detector's icons within two icon diameters, `4 r_out`); master's fits
    there classified by `classify_master`. The joint fit is a model, not
    truth; the visual sample checks both."""
    M = json.loads(Path(master_run).read_text(encoding="utf-8"))
    J = json.loads(Path(stack_run).read_text(encoding="utf-8"))
    r_out = ALLY.r_out * J["map_scale"]["scale"]
    d2 = 4 * r_out
    mby = {}
    for i in M["icons"]:
        if i["family"] != "barrier":
            mby.setdefault(float(i["t_ms"]), []).append(i)
    tab = {"frames": 0, "cap2": 0, "stack": 0, "master_fits": 0, "on_joint": 0, "between": 0,
           "other": 0, "joint_unmatched": 0, "master_big_r": 0, "stack_frames_with_between": 0}
    err = {"m": 0, "j": 0, "sm": 0, "sj": 0}
    stack_times = []
    for f in J["frames"]:
        t, cap = float(f["t_ms"]), f.get("cap")
        if cap is None:
            continue
        m = mby.get(t, [])
        j = kept_icons(f)
        tab["frames"] += 1
        err["m"] += abs(len(m) - cap)
        err["j"] += abs(len(j) - cap)
        if cap < 2:
            continue
        tab["cap2"] += 1
        mp = [(a["cx"], a["cy"]) for a in m]
        jp = [(a["x"], a["y"]) for a in j]
        if not (_pairs(mp, d2) or _pairs(jp, d2)):
            continue
        tab["stack"] += 1
        stack_times.append(t)
        err["sm"] += abs(len(m) - cap)
        err["sj"] += abs(len(j) - cap)
        any_between = False
        for a in m:
            tab["master_fits"] += 1
            tab["master_big_r"] += int(a["r"] >= r_out + 1.5)
            k = classify_master(a, jp, r_out)
            tab[k] += 1
            any_between |= k == "between"
        tab["stack_frames_with_between"] += int(any_between)
        tab["joint_unmatched"] += sum(1 for x, y in jp if not any(
            math.hypot(a["cx"] - x, a["cy"] - y) <= MATCH_PX for a in m))
    n, ns = max(1, tab["frames"]), max(1, tab["stack"])
    tab.update(mae_master=round(err["m"] / n, 4), mae_joint=round(err["j"] / n, 4),
               stack_mae_master=round(err["sm"] / ns, 4), stack_mae_joint=round(err["sj"] / ns, 4),
               fit_s_per_frame_joint=J.get("fit_s_per_frame"),
               master_s_per_frame=round(M["seconds"] / max(1, len(M["frames"])), 4))
    return tab, stack_times


# ------------------------------------------------------------------- views

def tile(crop, cx, cy, half=24, k=8, marks=(), static=None):
    """Native window and an x`k` nearest-neighbour enlargement (display only)
    with circles `(x, y, r, bgr)`; with `static`, the static's window beside."""
    H, W = crop.shape[:2]
    a, c = int(round(cy)) - half, int(round(cx)) - half
    pad = np.zeros((2 * half, 2 * half, 3), np.uint8)
    ys, xs = slice(max(0, a), min(H, a + 2 * half)), slice(max(0, c), min(W, c + 2 * half))
    pad[ys.start - a:ys.stop - a, xs.start - c:xs.stop - c] = crop[ys, xs]
    big = cv2.resize(pad, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)  # display only
    for x, y, r, col in marks:
        p = (int(round((x - c + 0.5) * k)), int(round((y - a + 0.5) * k)))
        cv2.circle(big, p, max(2, int(round(r * k))), col, 1, cv2.LINE_AA)
        cv2.drawMarker(big, p, col, cv2.MARKER_CROSS, 8, 1)
    if static is not None:
        sp = np.zeros_like(pad)
        sp[ys.start - a:ys.stop - a, xs.start - c:xs.stop - c] = static[ys, xs]
        big = np.hstack([big, cv2.resize(sp, None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)])
    return pad, big


def _overlay_marks(master_icons, joint_icons, r_out):
    """Master fits yellow at their ring radius, joint icons green at r_out."""
    out = [(m["cx"], m["cy"], m["r"], (0, 255, 255)) for m in master_icons]
    out += [(m["x"], m["y"], r_out, (0, 255, 0)) for m in joint_icons]
    return out


def run_sheet(sid, t0, t1, out: Path, master_run: Path, stack_run: Path, n: int = 12, seed: int = 20261002):
    """A seeded sample of stack-candidate frames: per row the native window
    enlarged x7 (nearest, display only), then master's fits (yellow, lettered)
    and the joint fit's (green, numbered). Writes the sheet and its index."""
    tab, stack_times = size_table(master_run, stack_run)
    rng = np.random.default_rng(seed)
    pick = sorted(rng.choice(stack_times, size=min(n, len(stack_times)), replace=False).tolist())
    s = Session(sid)
    M = json.loads(Path(master_run).read_text(encoding="utf-8"))
    J = json.loads(Path(stack_run).read_text(encoding="utf-8"))
    mby = {}
    for i in M["icons"]:
        if i["family"] != "barrier":
            mby.setdefault(float(i["t_ms"]), []).append(i)
    jfr = {float(f["t_ms"]): f for f in J["frames"]}
    r_out = s.shape.r_out
    half, k = 20, 7
    rows, index = [], []
    for t, crop in s.crops(pick):
        m, j = mby.get(t, []), kept_icons(jfr[t])
        # centre on the closest pair one detector placed (a master fit and
        # the joint fit of the same icon are no pair)
        best = None
        for pts in ([(a["cx"], a["cy"]) for a in m], [(a["x"], a["y"]) for a in j]):
            for a, b in _pairs(pts, 4 * r_out):
                d = math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1])
                if best is None or d < best[0]:
                    best = (d, (pts[a][0] + pts[b][0]) / 2, (pts[a][1] + pts[b][1]) / 2)
        _, cx, cy = best
        raw, big = tile(crop, cx, cy, half=half, k=k)
        _, ov = tile(crop, cx, cy, half=half, k=k, marks=_overlay_marks(m, j, r_out))
        x0, y0 = int(round(cx)) - half, int(round(cy)) - half
        for q, mm in enumerate(m):
            p = (int((mm["cx"] - x0 + 0.5) * k) + 4, int((mm["cy"] - y0 + 0.5) * k) - 4)
            cv2.putText(ov, "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[q], p, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
        for q, mm in enumerate(j):
            p = (int((mm["x"] - x0 + 0.5) * k) + 4, int((mm["y"] - y0 + 0.5) * k) + 14)
            cv2.putText(ov, str(q + 1), p, cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        lab = np.zeros((24, big.shape[1] * 2 + 8, 3), np.uint8)
        cv2.putText(lab, f"{len(rows)}: {sid} {t / 1000:.3f}s cap {jfr[t].get('cap')} centre {cx:.0f},{cy:.0f}",
                    (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        rows.append(np.vstack([lab, np.hstack([big, np.zeros((big.shape[0], 8, 3), np.uint8), ov])]))
        index.append({"row": len(rows) - 1, "t_ms": t, "centre": [cx, cy], "cap": jfr[t].get("cap"),
                      "master": [{"id": "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[q], "cx": mm["cx"], "cy": mm["cy"], "r": mm["r"],
                                  "class": classify_master(mm, [(a["x"], a["y"]) for a in j], r_out)}
                                 for q, mm in enumerate(m)],
                      "joint": [{"id": q + 1, "x": round(mm["x"], 2), "y": round(mm["y"], 2),
                                 "margin": round(mm["margin"], 2)} for q, mm in enumerate(j)]})
    out.mkdir(parents=True, exist_ok=True)
    pages = []
    for p0 in range(0, len(rows), 4):
        page = np.vstack(rows[p0:p0 + 4])
        f = out / f"sheet_{sid}_{int(t0)}-{int(t1)}_{p0 // 4}.png"
        cv2.imwrite(str(f), page)
        pages.append(str(f))
    (out / f"sheet_{sid}_{int(t0)}-{int(t1)}.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(json.dumps({"pages": pages, "rows": len(rows)}))


def run_crops(sid, t_s, cx, cy, out: Path, name: str, master_run: Path | None = None,
              stack_run: Path | None = None, half: int = 24):
    """Native and x8 crops round `(cx, cy)` at the frame nearest `t_s`, with
    master's fits (yellow) and the joint fit's (green) on the x8 crop."""
    s = Session(sid)
    t = min(s.frames, key=lambda h: abs(h - t_s * 1000))
    m, j = [], []
    if master_run:
        m = [i for i in json.loads(Path(master_run).read_text(encoding="utf-8"))["icons"]
             if float(i["t_ms"]) == t and i["family"] != "barrier"]
    if stack_run:
        j = next((kept_icons(f) for f in json.loads(Path(stack_run).read_text(encoding="utf-8"))["frames"]
                  if float(f["t_ms"]) == t), [])
    for tt, crop in s.crops([t]):
        if not stack_run:
            caps = s.capacity([t])
            j = [mm for mm in fit_frame(crop, s.static, s.floor, s.slab, s.shape, cap=caps.get(t),
                                        ref_gray=s.ref) if not mm.get("capped") and not mm.get("barrier")]
        if not master_run:
            m = master_kept(master_frames(s, [t]).get(t, []))
        nat, big = tile(crop, cx, cy, half=half, k=8, marks=_overlay_marks(m, j, s.shape.r_out))
        out.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(out / f"{name}_native.png"), nat)
        cv2.imwrite(str(out / f"{name}_x8.png"), big)
        print(json.dumps({"name": name, "t_ms": t, "origin": [int(round(cx)) - half, int(round(cy)) - half],
                          "master": [(round(a["cx"], 2), round(a["cy"], 2), a["r"]) for a in m
                                     if abs(a["cx"] - cx) <= half and abs(a["cy"] - cy) <= half],
                          "joint": [(round(a["x"], 2), round(a["y"], 2), round(a["margin"], 2)) for a in j
                                    if abs(a["x"] - cx) <= half and abs(a["y"] - cy) <= half]}))


# --------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fit")
    f.add_argument("sid")
    f.add_argument("--between", nargs=2, type=float, required=True)
    f.add_argument("--out", type=Path, required=True)
    f.add_argument("--no-cap", action="store_true")
    f.add_argument("--tag", default=None)
    f.add_argument("--lam", type=float, default=None, help="existence cost at map scale 1.0")
    f.add_argument("--stride", type=int, default=1, help="every Nth stored drawn frame")
    a = sub.add_parser("at")
    a.add_argument("sid")
    a.add_argument("times", nargs="+", type=float)
    lb = sub.add_parser("labels")
    lb.add_argument("--out", type=Path, required=True)
    lb.add_argument("--lam", type=float, default=None)
    z = sub.add_parser("size")
    z.add_argument("--master", type=Path, required=True)
    z.add_argument("--stack", type=Path, required=True)
    sh = sub.add_parser("sheet")
    sh.add_argument("sid")
    sh.add_argument("--between", nargs=2, type=float, required=True)
    sh.add_argument("--out", type=Path, required=True)
    sh.add_argument("--master", type=Path, required=True)
    sh.add_argument("--stack", type=Path, required=True)
    sh.add_argument("--n", type=int, default=12)
    c = sub.add_parser("crops")
    c.add_argument("sid")
    c.add_argument("t_s", type=float)
    c.add_argument("cx", type=float)
    c.add_argument("cy", type=float)
    c.add_argument("--name", required=True)
    c.add_argument("--out", type=Path, required=True)
    c.add_argument("--master", type=Path, default=None)
    c.add_argument("--stack", type=Path, default=None)
    args = ap.parse_args(argv)
    _priority()
    if args.cmd == "fit":
        tag = args.tag or ("stack_nocap" if args.no_cap else "stack")
        run_fit(args.sid, args.between[0], args.between[1], args.out, not args.no_cap, tag, args.lam,
                args.stride)
    elif args.cmd == "at":
        s = Session(args.sid)
        want = [min(s.frames, key=lambda h: abs(h - ts * 1000)) for ts in args.times]
        caps = s.capacity(want)
        for t, crop in s.crops(want):
            icons = fit_frame(crop, s.static, s.floor, s.slab, s.shape, cap=caps.get(t), ref_gray=s.ref)
            print(json.dumps({"t_ms": t, "cap": caps.get(t),
                              "icons": [_icon_row({k: v for k, v in m.items() if k != "window"})
                                        for m in icons]}))
    elif args.cmd == "labels":
        run_labels(args.out, args.lam)
    elif args.cmd == "size":
        tab, _ = size_table(args.master, args.stack)
        print(json.dumps(tab))
    elif args.cmd == "sheet":
        run_sheet(args.sid, args.between[0], args.between[1], args.out, args.master, args.stack, args.n)
    elif args.cmd == "crops":
        run_crops(args.sid, args.t_s, args.cx, args.cy, args.out, args.name, args.master, args.stack)


if __name__ == "__main__":
    main()
