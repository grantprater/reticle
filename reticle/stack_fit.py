r"""Stacked teammate icons fitted jointly: k teardrops over the baked map,
scored softly against the crop's tealness (`version.STACK_FIT_VERSION`).

Ported from `prototypes/stack_fit.py` (`stack-fit-0.2.0`, branch
`stacked-icons-20261002`) with its model and search unchanged except where
this docstring says otherwise; the torch tensors are numpy arrays here.

**Why.** `minimap.icons` makes one ring fit per connected component of the
teal key, and `_gated` keeps the best-covered fit within
`MIN_ICON_SEPARATION_PX`: a separation rule, not a likelihood. Two touching
teammates are one component and get one circle, so the rear icon of a stack
is never proposed. On 881 stacked living teammates at Riot kill instants on
20 sessions the ring fit found 0.331 and this search 0.456; the union of the
two 0.564 (the minimap-render probe, task `minimap-render-20261003` in the
store's `notes/predictions.jsonl`).

**The model.** Each teammate is the teardrop silhouette (`teardrop`'s ally
class radii times the map scale, `geometry.map_scale`): teal on its ring and
lobe, `ICON_ALPHA` opaque over its whole disc, with a free gain in
`[G_MIN, G_MAX]`. The icons are semi-transparent
[domain:minimap/icons-semi-transparent]; the prototype drew them opaque.
Icons composite bottom to top over the baked static's own tealness
[domain:capture/session-pixels-are-not-the-map]. The residual against the
crop's continuous tealness (`teardrop.tealness` times a G - B ramp, no
threshold) is a truncated square, so clutter no sprite models costs a fixed
amount. Greedy forward selection from matched-filter peaks, each member
refined with the others held, then backward elimination: a member stays
only while removing it would cost more than `LAM` (times the icon's area
scale) and while the members above it leave `VIS_MIN` of its teal showing.

**What it does not do.** The key's G - B ramp erases the pale-cyan ring of
some teammates (the prototype's outcome: 42 of 197 labelled icons the ring
fit found were lost when this search replaced it). So it never replaces the
ring fit: `minimap.AllyIconReader` adds its members beside the ring fit's,
where the ring fit's count falls short of the roster's capacity, and
`adjudication.minimap_candidates` decides which members are new icons. The
draw order between teammates is not modelled beyond each member's place
(top or bottom) in its window; the player does not know what sets the
per-match order, and the order the probe measured is not a prior here. It
names nobody.

Pixels in, members out: it reads one crop, the baked static, floor and
slab, and keeps no state between frames. Owns [owns:stacked-ally-icons].
"""
from __future__ import annotations

import math

import cv2
import numpy as np

from . import teardrop

ALLY = teardrop.ICON_CLASSES["ally"]

N_TH = 24            # matched-filter facings (15 degrees)
G_MIN, G_MAX = 0.3, 1.3
TRUNC = 0.5          # residual truncation, tealness units
#: Existence cost at map scale 1.0; scales with area. The prototype chose it
#: on the calibration windows 223d636bf8d2 1090-1250 and a06f04a0059f 440-600.
LAM = 2.0
PROP_TOP = 10        # proposals per window
TEAL_SEED = 0.25     # a window grows from tealness above this
#: A member shows at least this share of its teal past the members above it.
VIS_MIN = 0.3
#: The icon's opacity over what lies under it. The minimap-render probe's
#: calibration fitted 0.897 on 249 isolated teammates of three sessions; the
#: player confirms the icons are see-through.
ICON_ALPHA = 0.9
#: At most this many members per window: four teammates and clutter.
MAX_MEMBERS = 6
#: Pose-pixels per candidate batch.
CHUNK_PX = 1_000_000
#: The lit floor is tinted toward cyan: B and G about 30 over R with G - B
#: near zero, which `tealness` scores 0.3-0.5. The icon's teal holds G 20-50
#: over B, so the key fades out as G - B falls from 20 to 4.
GB_RAMP = (4.0, 20.0)

GRID1 = np.asarray([(dx, dy, dt) for dx in (-1, -0.5, 0, 0.5, 1) for dy in (-1, -0.5, 0, 0.5, 1)
                    for dt in (-15, -7.5, 0, 7.5, 15)], np.float32)
GRID2 = np.asarray([(dx, dy, dt) for dx in (-0.25, 0, 0.25) for dy in (-0.25, 0, 0.25)
                    for dt in (-3.75, 0, 3.75)], np.float32)


#: The lattice every pose the search scores lies on: the proposals sit on
#: whole pixels and multiples of 360 / N_TH degrees, and GRID1 and GRID2
#: step by quarter pixels and 3.75 degrees, so a refined member stays on it.
#: `Shape.sprites` reads such a pose from a bank rendered once per shape.
LAT_PX = 4
LAT_DEG = 3.75
#: The bank's facings, in LAT_DEG steps: a member's facing is wrapped into
#: [0, 360), and the two grids move it at most 18.75 degrees either way.
#: Each facing keeps its unwrapped value, so the radians are the search's own.
_A_REACH = int(round((float(np.abs(GRID1[:, 2]).max()) + float(np.abs(GRID2[:, 2]).max()))
                     / LAT_DEG))
A_LO, A_HI = -_A_REACH, int(round(360.0 / LAT_DEG)) - 1 + _A_REACH
assert not (np.mod(np.concatenate([GRID1, GRID2])[:, :2] * LAT_PX, 1.0).any()
            or np.mod(np.concatenate([GRID1, GRID2])[:, 2] / LAT_DEG, 1.0).any()
            or (360.0 / N_TH) % LAT_DEG)


class Shape:
    """The ally teardrop at one session's map scale."""

    def __init__(self, scale: float, lam: float | None = None):
        self.scale = float(scale)
        self.r_in, self.r_out, self.L = ALLY.r_in * scale, ALLY.r_out * scale, ALLY.L * scale
        self.edge = teardrop.EDGE * scale
        self.reach = int(math.ceil(self.L + self.edge + 1))
        self.lam = (LAM if lam is None else lam) * scale * scale
        # the ring fit's integer radius the reader's descriptors read at
        self.r_int = int(round((self.r_in + self.r_out) / 2))
        ca = self.r_out / self.L
        self._ca, self._sa = ca, math.sqrt(max(0.0, 1.0 - ca * ca))
        #: A sprite's box half-width round its pose's whole pixel: the disc
        #: ends within `reach` of the pose, and the box keeps one more pixel.
        self.box = self.reach + 1
        self._bank = None
        self._kernels = None

    def layers(self, dx, dy, th):
        """Teal coverage `t` (ring and lobe) and disc coverage `o` (the whole
        teardrop, portrait included), broadcasting; `th` in radians."""
        c, s = np.cos(th), np.sin(th)
        u = dx * c + dy * s
        v = dy * c - dx * s
        rho = np.sqrt(dx * dx + dy * dy)
        d_wedge = u * self._ca + np.abs(v) * self._sa - self.r_out
        d_tri = np.maximum(d_wedge, np.maximum(self.r_out * self._ca - u, u - self.L))
        d_tear = np.minimum(rho - self.r_out, d_tri)
        o = np.clip(0.5 - d_tear / self.edge, 0.0, 1.0)
        t = np.clip(0.5 - np.maximum(d_tear, self.r_in - rho) / self.edge, 0.0, 1.0)
        return t.astype(np.float32, copy=False), o.astype(np.float32, copy=False)

    def kernels(self) -> list[np.ndarray]:
        """`proposals`' N_TH teal kernels on the integer offsets within `reach`."""
        if self._kernels is None:
            k = self.reach
            g = np.arange(-k, k + 1, dtype=np.float32)
            ky, kx = np.meshgrid(g, g, indexing="ij")
            self._kernels = [self.layers(kx, ky, i * (2 * math.pi / N_TH))[0]
                             for i in range(N_TH)]
        return self._kernels

    def _sprite_bank(self):
        """Every lattice pose's sprite, rendered once: for each facing in
        [A_LO, A_HI] LAT_DEG steps and each quarter-pixel phase, the box
        offsets `(dy, dx)` where its disc covers and `t`, `o` there.

        The offsets from a pose's whole pixel are whole numbers less the
        phase, so each value is the one `layers` gives at that pixel for
        the pose itself: the same float32 offsets and float32 radians."""
        if self._bank is not None:
            return self._bank
        R = self.box
        S = 2 * R + 1
        j = np.arange(-R, R + 1, dtype=np.float32)
        q = np.arange(LAT_PX, dtype=np.float32) / LAT_PX
        off = j[None, :] - q[:, None]                  # (phase, S): whole offsets less the phase
        dx = off[None, None, :, None, :]               # (1, 1, qx, 1, S)
        dy = off[None, :, None, :, None]               # (1, qy, 1, S, 1)
        degs = (np.arange(A_LO, A_HI + 1) * LAT_DEG).astype(np.float32)
        ths = np.deg2rad(degs)
        ts, os_ = [], []
        for i in range(0, len(ths), 8):
            t, o = self.layers(dx, dy, ths[i:i + 8, None, None, None, None])
            ts.append(t.reshape(-1, S * S))
            os_.append(o.reshape(-1, S * S))
        t, o = np.concatenate(ts), np.concatenate(os_)
        on = o > 0
        edge = np.zeros((S, S), bool)
        edge[[0, -1], :] = edge[:, [0, -1]] = True
        if on[:, edge.ravel()].any():
            raise AssertionError("stack_fit sprite reaches its box edge")
        n = on.sum(1)
        K = int(n.max())
        # each sprite's covered pixels first, in raster order
        order = np.argsort(~on, axis=1, kind="stable")[:, :K]
        valid = np.arange(K)[None] < n[:, None]
        rows = np.take_along_axis(t, order, 1)
        self._bank = {
            "dy": (order // S - R).astype(np.int32), "dx": (order % S - R).astype(np.int32),
            "t": np.where(valid, rows, 0).astype(np.float32),
            "o": np.where(valid, np.take_along_axis(o, order, 1), 0).astype(np.float32),
            "valid": valid}
        return self._bank

    def sprites(self, P: np.ndarray):
        """Poses `P` (n, 3: x, y, degrees) as sprites: `(iy, ix, dy, dx, t, o,
        valid)`, each pose's whole pixel and, per covered pixel, its offset
        from it and the layers there. A pose on the lattice is read from the
        bank; any other is rendered on its box, as `layers` renders it."""
        P = np.asarray(P, np.float32)
        ix = np.floor(P[:, 0]).astype(np.int64)
        iy = np.floor(P[:, 1]).astype(np.int64)
        qx = (P[:, 0] - ix) * LAT_PX
        qy = (P[:, 1] - iy) * LAT_PX
        qa = P[:, 2] / np.float32(LAT_DEG)
        on = ((qx == np.round(qx)) & (qy == np.round(qy)) & (qa == np.round(qa))
              & (qa >= A_LO) & (qa <= A_HI))
        if on.all():
            b = self._sprite_bank()
            k = ((np.round(qa).astype(np.int64) - A_LO) * LAT_PX
                 + np.round(qy).astype(np.int64)) * LAT_PX + np.round(qx).astype(np.int64)
            return iy, ix, b["dy"][k], b["dx"][k], b["t"][k], b["o"][k], b["valid"][k]
        R = self.box
        g = np.arange(-R, R + 1)
        gy, gx = np.meshgrid(g, g, indexing="ij")
        X = (ix[:, None, None] + gx[None]).astype(np.float32)
        Y = (iy[:, None, None] + gy[None]).astype(np.float32)
        t, o = self.layers(X - P[:, 0, None, None], Y - P[:, 1, None, None],
                           np.deg2rad(P[:, 2])[:, None, None])
        n = len(P)
        return (iy, ix, np.broadcast_to(gy.ravel(), (n, gy.size)),
                np.broadcast_to(gx.ravel(), (n, gx.size)), t.reshape(n, -1), o.reshape(n, -1),
                np.ones((n, gy.size), bool))


def _rho(R):
    """The truncated square, per pixel."""
    return np.minimum(R * R, TRUNC * TRUNC)


class Window:
    """One window's pixels: tealness `T`, background tealness `B`, weight
    `W`, pixel-centre coordinates `X`, `Y` in crop px."""

    def __init__(self, T, B, Wt, x0: int, y0: int):
        self.T = np.ascontiguousarray(T, np.float32)
        self.B = np.ascontiguousarray(B, np.float32)
        self.W = np.ascontiguousarray(Wt, np.float32)
        h, w = self.T.shape
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        self.X, self.Y = xx + x0, yy + y0
        self.x0, self.y0 = x0, y0
        self._memo: dict = {}

    def _layers(self, shape: Shape, m: dict):
        """A member's layers over the window: `shape.layers` on the box round
        its pose (the disc lies inside it) and zero elsewhere, which is what
        the whole window's render holds, pixel for pixel. Memoised by pose."""
        key = (m["x"], m["y"], m["deg"])
        got = self._memo.get(key)
        if got is not None:
            return got
        h, w = self.T.shape
        R = shape.box
        cx, cy = int(math.floor(m["x"])) - self.x0, int(math.floor(m["y"])) - self.y0
        r0, r1 = max(0, cy - R), min(h, cy + R + 1)
        c0, c1 = max(0, cx - R), min(w, cx + R + 1)
        t = np.zeros((h, w), np.float32)
        o = np.zeros((h, w), np.float32)
        if r0 < r1 and c0 < c1:
            sl = (slice(r0, r1), slice(c0, c1))
            t[sl], o[sl] = shape.layers(self.X[sl] - m["x"], self.Y[sl] - m["y"],
                                        math.radians(m["deg"]))
        self._memo[key] = got = (t, o)
        return got

    def composite(self, shape: Shape, S: list[dict]):
        """`(a, c)` with the set's render over a layer `Z` equal to `a + c * Z`."""
        a = np.zeros_like(self.T)
        c = np.ones_like(self.T)
        for m in S:  # bottom to top
            t, o = self._layers(shape, m)
            k = 1.0 - ICON_ALPHA * o
            a = m["g"] * t + k * a
            c = k * c
        return a, c

    def visible(self, shape: Shape, S: list[dict]) -> list[float]:
        """Per member, the share of its own teal the members above it leave
        showing: a teardrop drawn wholly under another is no evidence."""
        lay = [self._layers(shape, m) for m in S]
        out = []
        for i, (t, _) in enumerate(lay):
            c = np.ones_like(self.T)
            for _, o in lay[i + 1:]:
                c = c * (1.0 - ICON_ALPHA * o)
            out.append(float((self.W * t * c).sum() / max(1e-6, float((self.W * t).sum()))))
        return out

    def set_loss(self, shape: Shape, S: list[dict]) -> float:
        a, c = self.composite(shape, S)
        return float((self.W * _rho(self.T - (a + c * self.B))).sum())

    def _support(self, shape: Shape, P: np.ndarray):
        """The poses' layers on the pixels any of them covers: `(idx, t, o)`
        with `idx` flat window indices and `t`, `o` shaped (len(P), len(idx)).
        Memoised per pose set: the greedy search scores one seed's grid again
        after every member it adds.

        The poses' sprites (`Shape.sprites`) are laid on the box round the
        set's mean, each value the one a render on that box gives, so the
        support, its order and every value are the render's."""
        key = P.tobytes()
        got = self._memo.get(key)
        if got is not None:
            return got
        h, w = self.T.shape
        half = shape.reach + 2
        sx, sy = float(P[:, 0].mean()) - self.x0, float(P[:, 1].mean()) - self.y0
        r0, r1 = max(0, int(math.floor(sy)) - half), min(h, int(math.ceil(sy)) + half + 1)
        c0, c1 = max(0, int(math.floor(sx)) - half), min(w, int(math.ceil(sx)) + half + 1)
        if r0 >= r1 or c0 >= c1:
            got = (np.zeros(0, np.intp), np.zeros((len(P), 0), np.float32),
                   np.zeros((len(P), 0), np.float32))
        else:
            bh, bw = r1 - r0, c1 - c0
            n, off = len(P), bh * bw
            iy, ix, dy, dx, tv, ov, valid = shape.sprites(P)
            rr = (iy - self.y0 - r0).astype(np.int32)[:, None] + dy
            cc = (ix - self.x0 - c0).astype(np.int32)[:, None] + dx
            # a sprite's padding, and a pixel off the window, land on `off`
            flat = np.where(valid & (rr >= 0) & (rr < bh) & (cc >= 0) & (cc < bw),
                            rr * bw + cc, off)
            # A sprite holds exactly its disc's pixels (`o` > 0; `t` never
            # exceeds `o`), so the support is their union, in raster order.
            sup = np.zeros(off + 1, bool)
            sup[flat] = True
            sup[off] = False
            cols = np.flatnonzero(sup)
            m = len(cols)
            at = np.full(off + 1, m, np.intp)
            at[cols] = np.arange(m)
            # Column-major (column `m` takes what lies off the support), as a
            # boolean mask's columns come out of the render, so the sums
            # below add in the render's order.
            lin = (at[flat] * n + np.arange(n)[:, None]).ravel()
            t = np.zeros((m + 1) * n, np.float32)
            o = np.zeros((m + 1) * n, np.float32)
            t[lin] = tv.ravel()
            o[lin] = ov.ravel()
            t, o = t.reshape(m + 1, n).T[:, :m], o.reshape(m + 1, n).T[:, :m]
            rr_, cc_ = np.divmod(cols, bw)
            got = ((rr_ + r0) * w + (cc_ + c0), t, o)
        self._memo[key] = got
        return got

    def candidates(self, shape: Shape, S: list[dict], seeds: np.ndarray, grid: np.ndarray):
        """Loss and gain of each seed's grid of poses added on top of `S` and
        under it: (loss (n, len(grid), 2), gain (n, len(grid), 2)).

        A pose changes the render only where its disc covers, so each seed's
        poses are scored on the pixels any of them covers and the rest of the
        window keeps the set's own loss: the whole window's sums, at a
        fraction of the pixels."""
        a, c = self.composite(shape, S)
        base = a + c * self.B
        R0 = (self.W * _rho(self.T - base)).ravel()
        L0 = float(R0.sum())
        n, g = len(seeds), len(grid)
        Ls = np.empty((n, g, 2), np.float32)
        Gs = np.empty((n, g, 2), np.float32)
        Tf, Bf, Wf = self.T.ravel(), self.B.ravel(), self.W.ravel()
        af, cf, bf = a.ravel(), c.ravel(), base.ravel()
        for k in range(n):
            P = seeds[k][None] + grid
            idx, t, o = self._support(shape, P)
            # What the set `S` does not change, kept with the support.
            fixed = self._memo.get((b"fixed", P.tobytes()))
            if fixed is None:
                T, B, W = Tf[idx][None], Bf[idx][None], Wf[idx][None]
                k_ = 1.0 - ICON_ALPHA * o
                Wt = W * t
                fixed = self._memo[(b"fixed", P.tobytes())] = (
                    T, B, W, k_, Wt, np.maximum((Wt * t).sum(-1), 1e-6))
            T, B, W, k_, Wt, den_top = fixed
            ap, cp, bp = af[idx][None], cf[idx][None], bf[idx][None]
            rest = L0 - float(R0[idx].sum())
            # on top: M = g t + (1 - alpha o)(a + c B)
            U = k_ * bp
            g_top = np.clip((Wt * (T - U)).sum(-1) / den_top, G_MIN, G_MAX)
            L_top = (W * _rho(T - (g_top[:, None] * t + U))).sum(-1) + rest
            # underneath: M = a + c (g t + (1 - alpha o) B)
            ct = cp * t
            V = ap + cp * k_ * B
            Wct = W * ct
            g_bot = np.clip((Wct * (T - V)).sum(-1) /
                            np.maximum((Wct * ct).sum(-1), 1e-6), G_MIN, G_MAX)
            L_bot = (W * _rho(T - (V + g_bot[:, None] * ct))).sum(-1) + rest
            Ls[k, :, 0], Ls[k, :, 1] = L_top, L_bot
            Gs[k, :, 0], Gs[k, :, 1] = g_top, g_bot
        return Ls, Gs

    def proposals(self, shape: Shape, top: int = PROP_TOP) -> list[dict]:
        """Matched-filter peaks: the quadratic loss drop of one icon at each
        integer centre and facing, over the background alone."""
        R = ((self.T - self.B) * self.W).astype(np.float32)
        best = arg = None
        for i, t in enumerate(shape.kernels()):
            # correlation with a zero border, as the prototype's padded conv2d
            s = cv2.filter2D(R, cv2.CV_32F, t, borderType=cv2.BORDER_CONSTANT)
            nn = float((t * t).sum())
            gg = np.clip(s / nn, G_MIN, G_MAX)
            d = 2 * gg * s - gg * gg * nn
            if best is None:
                best, arg = d, np.zeros(d.shape, np.int32)
            else:
                up = d > best
                best = np.where(up, d, best)
                arg[up] = i
        pooled = cv2.dilate(best, np.ones((5, 5), np.uint8), borderType=cv2.BORDER_CONSTANT,
                            borderValue=-np.inf)
        peak = (best == pooled) & (best > shape.lam * 0.5)
        ys, xs = np.nonzero(peak)
        if not len(ys):
            return []
        v = best[ys, xs]
        order = np.argsort(-v, kind="stable")[:top]
        return [{"x": float(xs[i] + self.x0), "y": float(ys[i] + self.y0),
                 "deg": float(arg[ys[i], xs[i]]) * 360.0 / N_TH, "drop": float(v[i])}
                for i in order]


def _refine_seeds(win: Window, shape: Shape, S: list[dict], seeds: list[dict]):
    """Each seed refined against `S` on two grids; returns, per seed, the
    best `(loss, member, place)` with place 'top' or 'bottom'."""
    if not seeds:
        return []
    cur = np.array([(sd["x"], sd["y"], sd["deg"]) for sd in seeds], np.float32)
    n = len(seeds)
    for grid in (GRID1, GRID2):
        L, G = win.candidates(shape, S, cur, grid)
        flat = L.reshape(n, -1).argmin(1)
        i, j = np.divmod(flat, 2)
        cur = cur + grid[i]
    out = []
    for k in range(n):
        out.append((float(L[k, i[k], j[k]]), {"x": float(cur[k, 0]), "y": float(cur[k, 1]),
                                              "deg": float(cur[k, 2]) % 360.0,
                                              "g": float(G[k, i[k], j[k]])},
                    ("top", "bottom")[int(j[k])]))
    return out


def _place_member(S, m, where):
    return S + [m] if where == "top" else [m] + S


def fit_window(win: Window, shape: Shape, limit: int = MAX_MEMBERS) -> list[dict]:
    """Greedy forward selection, joint refinement and backward elimination
    on one window. Returns the members bottom to top, each with `margin`
    (the loss its removal would add) and `visible`."""
    seeds = win.proposals(shape)
    S: list[dict] = []
    L_S = win.set_loss(shape, S)
    used = set()
    while seeds and len(S) < limit:
        free = [k for k in range(len(seeds)) if k not in used]
        if not free:
            break
        res = _refine_seeds(win, shape, S, [seeds[k] for k in free])
        k, (L_new, m, where) = min(zip(free, res), key=lambda kr: kr[1][0])
        if L_S - L_new <= shape.lam:
            break
        used.add(k)
        S = _place_member(S, m, where)
        L_S = L_new
        # each member refined with the others held, in its place
        for i in range(len(S)):
            rest = S[:i] + S[i + 1:]
            (L_i, m_i, where_i), = _refine_seeds(win, shape, rest, [S[i]])
            if L_i < L_S - 1e-6:
                S = _place_member(rest, m_i, where_i)
                L_S = L_i
    # backward elimination: a member the others explain goes, and so does one
    # the members above it hide
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

def ally_key(img: np.ndarray) -> np.ndarray:
    """`teardrop.tealness` times a soft ramp on G - B: teal, not lit floor."""
    c = img.astype(np.float32)
    gb = np.clip((c[..., 1] - c[..., 0] - GB_RAMP[0]) / (GB_RAMP[1] - GB_RAMP[0]), 0.0, 1.0)
    return (teardrop.tealness(img) * gb).astype(np.float32)


def frame_maps(crop: np.ndarray, static_key: np.ndarray, floor: np.ndarray):
    """`(T, B, W)`: the crop's key, the baked static's key and the weight.
    The player's icon draws over teammates; its pixels explain no teammate."""
    T = ally_key(crop)
    Wt = floor.astype(np.float32)
    yel = teardrop.yellowness(crop) > 0.3
    yel = cv2.dilate(yel.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    Wt[yel] = 0.0
    return T, static_key, Wt


def single_mass(shape: Shape) -> float:
    """One unoccluded teammate's seed mass: its teal pixels above `TEAL_SEED`
    when drawn alone at gain 1 (the area `stack_windows` compares with)."""
    k = shape.reach
    g = np.arange(-k, k + 1, dtype=np.float32)
    ky, kx = np.meshgrid(g, g, indexing="ij")
    t, _ = shape.layers(kx, ky, 0.0)
    return float((t > TEAL_SEED).sum())


def stack_windows(T: np.ndarray, Wt: np.ndarray, slab: np.ndarray, shape: Shape) -> list[dict]:
    """Windows round connected teal on the slab, grown by the icon's reach;
    overlapping windows merged. Each carries its seed `mass` in pixels."""
    seed = (T > TEAL_SEED) & (Wt > 0)
    g = int(math.ceil(shape.r_out))
    grown = cv2.dilate(seed.astype(np.uint8), cv2.getStructuringElement(
        cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1)))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(grown, 8)
    H, W = T.shape
    out = []
    min_px = max(4, int(0.25 * 2 * math.pi * shape.r_out))
    m = shape.reach
    # each component's seed pixels, and those on the slab, counted at once
    mass_of = np.bincount(lbl[seed], minlength=n)
    on_slab = np.bincount(lbl[seed & slab.astype(bool, copy=False)], minlength=n) > 0
    for i in range(1, n):
        mass = int(mass_of[i])
        if mass < min_px or not on_slab[i]:
            continue
        x, y, w, h = (int(v) for v in st[i, :4])
        out.append([max(0, y - m), min(H, y + h + m), max(0, x - m), min(W, x + w + m), mass])
    merged = True
    while merged:
        merged = False
        for i in range(len(out)):
            for j in range(i + 1, len(out)):
                (a, b, c, d, p), (e, f, gg, h, q) = out[i], out[j]
                if a < f and e < b and c < h and gg < d:
                    out[i] = [min(a, e), max(b, f), min(c, gg), max(d, h), p + q]
                    del out[j]
                    merged = True
                    break
            if merged:
                break
    return [{"box": (a, b, c, d), "mass": p} for a, b, c, d, p in out]


def fit_box(T: np.ndarray, B: np.ndarray, Wt: np.ndarray, box, shape: Shape) -> list[dict]:
    """Members of one window `box` (row0, row1, col0, col1), bottom to top,
    each with its `depth` in the window."""
    a, b, c, d = box
    S = fit_window(Window(T[a:b, c:d], B[a:b, c:d], Wt[a:b, c:d], c, a), shape)
    return [{**m, "depth": k, "members": len(S)} for k, m in enumerate(S)]


#: A window is a stack when its seed mass exceeds this many unoccluded
#: teammates' (`single_mass`). Chosen on the probe's 60 sampled kill instants
#: of 5822b6646448 (465 px), a session outside the acceptance set, before any
#: acceptance session was fitted: windows holding one living teammate by Riot's
#: record read 0.48-0.92 (5th-95th percentile, n 33), two 0.65-1.68 (median
#: 1.35, n 21), three or more 1.19-2.77 (n 16).
STACK_MASS = 1.0


class Fitter:
    """One session's search: its map scale's shape, the baked static's key,
    floor and slab."""

    def __init__(self, scale: float, static: np.ndarray, floor: np.ndarray, slab: np.ndarray):
        self.shape = Shape(scale)
        self.static_key = ally_key(static)
        self.floor, self.slab = floor, slab
        self.one = single_mass(self.shape)

    def stacks(self, crop: np.ndarray):
        """`(T, B, W, windows)`: the frame's maps and its windows whose seed
        mass exceeds `STACK_MASS` teammates', each with `mass_ratio`."""
        T, B, Wt = frame_maps(crop, self.static_key, self.floor)
        wins = [{**w, "mass_ratio": w["mass"] / self.one}
                for w in stack_windows(T, Wt, self.slab, self.shape)]
        return T, B, Wt, [w for w in wins if w["mass_ratio"] > STACK_MASS]

    def fit(self, T, B, Wt, box) -> list[dict]:
        return fit_box(T, B, Wt, box, self.shape)
