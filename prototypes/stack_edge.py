r"""Stack-edge discrimination: name a teammate leaving a stack from its newly
exposed portrait pixels alone, measured against replay truth.

    .\.venv\Scripts\python.exe prototypes\stack_edge.py SESSION [--events 200]

Feasibility for task `stack-edge-discrimination-20261006` in the store's
`notes/predictions.jsonl`; that row fixed every constant below before any
crop was read. Nothing in `reticle/` imports this file.

The idea (the player, 2026-10-06): when a stack's edge moves, score only the
pixels that just came into view, against only the stack's known members, on
the pixels that best separate them.

* **Exposure.** A teammate's portrait is a soft disc of radius
  `r_out / 1.26` (the container-to-portrait ratio the minimap-render probe
  measured). Containers draw under every portrait, so only other portraits,
  and the player's own icon, cover it. A portrait pixel is *exposed* in
  proportion to the product of `1 - P_j` over the others: an order-free
  region that shows this member whatever the draw order.
* **Reference.** `ally_portrait.render_reference` of the game's minimap
  portrait art under the stored calibration, in `ally_portrait`'s aligned
  frame (`align_icon`), compared in Lab.
* **Score.** A Gaussian log-likelihood over the exposed aligned pixels,
  per-pixel variance the calibration's Lab cell variance plus a half-pixel
  pose term on the reference's gradient, maximised over a 5x5 half-pixel
  centre grid. The pairwise log-ratio is then Fisher's discriminant, so the
  per-pair pixel weights are the reference difference over that variance.
  Sums are counted per independent sample (the calibration's 1 px blur).

Three readers are scored on each exit: the **oracle** (replay positions and
the replay's stack members), **realistic candidates** (replay positions, the
stored stream's names near the stack), and **realistic** (a pixel trigger,
the stored stream's positions and names). The stored `round_entity` names on
the same frames are the baseline. Reports go to
`<store>/analysis/stack-edge-20261006/`.

The row's same-match exemplar diagnostic (a median of the match's isolated
icon crops) ran once and is gone: `doctor` SESSION_STATIC rejects any
capture median in a prototype.

Clocks. Frames are the crop cache's own; truth is `replay_truth.truth_px`
at each cache time; the stored stream joins by the nearest scored ally_icon
frame within half a sample, and a match whose ally_icon frames join the cache
below 0.99 is refused (c817691bcd15's cache and ally_icon sit on different
60 Hz phases, so an exact frame join keeps 0.57 of its frames).

Added after the prediction row, and labelled so in every report: the
`posthoc_loose_exits` and `posthoc_partial_frames` event sets (the row's rule
finds few exits), `--extra-lag-ms` (isolated stored fits trail replay truth
along the motion by 1.5-1.8 px, about 70 ms), the background candidate (the
baked static map as a null, beside the row's residual test) and children
whose owner's share is below 0.5.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "OPENCV_FOR_THREADS_NUM"):
    os.environ.setdefault(_v, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import crowd_blob as cb  # noqa: E402  (Pixels: geometry, crop cache, stack_fit Fitter)
import replay_truth as rt  # noqa: E402  (_assign, load_round_entity)
from reticle import agent_names, replay_layer, replay_source, teardrop  # noqa: E402
from reticle import ally_portrait as AP  # noqa: E402

VERSION = "stack-edge-0.1.0"
TASK = "stack-edge-discrimination-20261006"
OUT = rt.STORE / "analysis" / "stack-edge-20261006"
NEVER = ("cea8ecbc94ab",)          # the held-out capture: never read

# ---- constants fixed by the prediction row
PORTRAIT_RATIO = 1.26              # container / portrait disc (minimap-render)
F_STACKED = 0.1                    # exclusive share below this is stacked
STACKED_RUN = 5                    # frames
WINDOW_K = 15                      # frames after the exit begins
PRE_K = 5                          # member set looks back this far
MEMBER_R = 2.0                     # x r_out: a stack member
NEAR_R = 3.0                       # x r_out: realistic candidates, isolation
S_POS = 0.5                        # native px pose term
OFFS = np.asarray([-1.0, -0.5, 0.0, 0.5, 1.0])
MARGIN = 2.0                       # confident margin, independent-sample nats
UNKNOWN = 4.0                      # mean normalised squared residual
SIGMA_CAL = 1.0                    # calibration blur, native px
TRIGGER_MASS = 0.5                 # x one icon's seed mass
GATE_M = 8.0                       # stored-name match gate (replay-truth's)
SEED = 20261006
EXP_BINS = (0, 1, 15, 25, 40, 80, 1e9)   # 0-1: no evidence (reporting split)
HALF_SAMPLE_MS = 1000.0 / 30 + 0.01       # stored-stream join: nearest within half a sample
MIN_JOIN = 0.99                           # refuse a match joined below this
BACKGROUND = "__background__"             # post-hoc null candidate
K_BINS = ((0, 0), (1, 1), (2, 2), (3, 5), (6, 10), (11, 15))

U = np.arange(AP.SIDE, dtype=np.float32) - (AP.SIDE - 1) / 2
UU, VV = np.meshgrid(U, U)                       # aligned offsets from centre
RHO = np.hypot(UU, VV)
DISC_SOFT = np.clip(0.5 + (0.75 * AP.DISC_R - RHO), 0.0, 1.0).astype(np.float32)
IDX = np.flatnonzero(DISC_SOFT.ravel() > 0)


def soft_disc(d, r, edge):
    return np.clip(0.5 - (d - r) / edge, 0.0, 1.0)


def lab(img_bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(img_bgr, cv2.COLOR_BGR2Lab).astype(np.float32)


class Match:
    """One development match: replay-layer truth on the crop cache's frames,
    the stored stream, geometry and the rendered references."""

    def __init__(self, sid: str, extra_lag_ms: float = 0.0):
        if sid in NEVER:
            raise SystemExit(f"{sid} is held out")
        self.sid = sid
        L = replay_layer.load(sid)
        if replay_layer.is_held_out(L.match):
            raise SystemExit(f"{sid}: replay {L.match} is held out")
        self.L = L
        self.px = cb.Pixels(sid)
        x0, y0, x1, y1 = self.px.box
        self.width = x1 - x0
        self.s = AP.UPS * AP.W_REF / self.width          # aligned px per native px
        sh = self.px.shape
        self.r_out = sh.r_out
        self.r_p = sh.r_out / PORTRAIT_RATIO
        self.edge = teardrop.EDGE * sh.scale
        # Truth is replay-truth's (`session_context`, `truth_px`): it names the
        # player from the replay, so a match without a Riot record scores too.
        # Frames are the crop cache's own (its minimap rect), and the stored
        # stream joins by the nearest ally_icon frame within half a sample:
        # on c817691bcd15 the cache and ally_icon sit on different 60 Hz
        # phases, so an exact join drops about half its frames.
        ctx = rt.session_context(sid)
        if "refused" in ctx["out"]:
            raise SystemExit(f"{sid}: replay-truth refused ({ctx['out']['refused']})")
        self.ctx = ctx
        mates = list(ctx["allies"])
        self.subjects = mates
        self.me = mates.index(ctx["me"])
        self.team = list(range(len(mates)))
        self.agent = [agent_names.canonical_agent(ctx["agent"].get(m_)) for m_ in mates]
        self.a = float(ctx["a"])
        cache = self.px.cache
        from reticle.roi_cache import CACHE_SETS, spans_mask
        k_mm = CACHE_SETS[cache.record["roi"]].index("minimap")
        sel = cache.rect == k_mm
        t_c, o = np.unique(np.asarray(cache.t_ms, float)[sel], return_index=True)
        fi_c = np.asarray(cache.frame_idx, np.int64)[sel][o]
        AI = ctx["AI"]
        sc = spans_mask(AI["t_ms"], cache.record.get("spans") or []) & AI["drawn"]
        ai_t, ai_fi = AI["t_ms"][sc], AI["frame_idx"][sc]
        o2 = np.argsort(ai_t)
        ai_t, ai_fi = ai_t[o2], ai_fi[o2]

        def nearest(src, dst):
            j = np.clip(np.searchsorted(dst, src), 1, dst.size - 1)
            jj = np.where(np.abs(dst[j - 1] - src) <= np.abs(dst[j] - src), j - 1, j)
            return jj, np.abs(dst[jj] - src)

        # the coordinator's direction: each scored ally_icon frame finds a cache frame
        _jj, d_ai = nearest(ai_t, t_c)
        jj, dt = nearest(t_c, ai_t)
        ok = dt <= HALF_SAMPLE_MS
        self.join = {"ally_icon_scored_frames": int(ai_t.size),
                     "rate": round(float((d_ai <= HALF_SAMPLE_MS).mean()), 4),
                     "exact_frame_idx": round(float(np.isin(ai_fi, fi_c).mean()), 4),
                     "cache_frames": int(t_c.size), "cache_frames_joined": int(ok.sum()),
                     "dt_ms_median": round(float(np.median(dt[ok])), 2),
                     "dt_ms_max_joined": round(float(dt[ok].max()), 2)}
        # analysis frames: cache frames joined to a scored ally_icon frame
        self.t, self.fi, self.ai_fi = t_c[ok], fi_c[ok], ai_fi[jj[ok]]
        X, Y, _yaw, A = rt.truth_px(ctx["rp"], ctx["mf"], mates,
                                    replay_source.frames_to_replay(self.t + extra_lag_ms, self.a,
                                                                   replay_source.MINIMAP_LAG_MS))
        self.X, self.Y, self.A = X, Y, A & np.isfinite(X)
        self.contig = np.r_[False, np.abs(np.diff(self.t) - 1000.0 / 15) < 1.0]
        self.gate = float(ctx["gate"])
        self.refs = self._references()

    # ---------------------------------------------------------- references
    def _references(self) -> dict:
        root = rt.STORE
        cal = json.loads((root / "reference" / "ally_portrait" / "calibration.json")
                         .read_text(encoding="utf-8"))
        v = np.asarray(cal["var"]["grid3_lab"], np.float32).reshape(9, 3).mean(0)
        self.s2 = v
        out = {}
        for a in set(self.agent):
            p = root / "reference" / "assets" / "agents" / f"{a}_minimap_portrait.png"
            art = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            out[a] = self._ref_terms(lab(AP.render_reference(art, cal)))
        return out

    def _ref_terms(self, R: np.ndarray) -> tuple:
        gy, gx = np.gradient(R, axis=(0, 1))
        g2 = (gx * gx + gy * gy) * self.s * self.s           # per native px, squared
        V = self.s2[None, None, :] + S_POS * S_POS * g2
        return R.astype(np.float32), (1.0 / V).astype(np.float32)

    # ---------------------------------------------------------- exposure
    def exclusive(self, cx, cy, others) -> float:
        """Exclusive share of a portrait at (cx, cy); `others` (x, y, r)."""
        g = np.arange(-math.ceil(self.r_p + self.edge), math.ceil(self.r_p + self.edge) + 0.5, 0.5)
        gx, gy = np.meshgrid(g, g)
        P = soft_disc(np.hypot(gx, gy), self.r_p, self.edge)
        W = P.copy()
        for x, y, r in others:
            W *= 1.0 - soft_disc(np.hypot(gx + cx - x, gy + cy - y), r, self.edge)
        return float(W.sum() / P.sum())

    def shares(self) -> np.ndarray:
        """f[n, K]: every teammate's exclusive share on every frame (1 where
        nothing is near; NaN where dead)."""
        n, K = self.X.shape
        f = np.where(self.A, 1.0, np.nan)
        g = np.arange(-math.ceil(self.r_p + self.edge), math.ceil(self.r_p + self.edge) + 0.5, 0.5)
        gx, gy = (a.ravel().astype(np.float32) for a in np.meshgrid(g, g))
        P = soft_disc(np.hypot(gx, gy), self.r_p, self.edge)
        reach = self.r_p + self.r_out + 2 * self.edge
        for i in range(K):
            if i == self.me:
                continue
            d = np.hypot(self.X - self.X[:, i:i + 1], self.Y - self.Y[:, i:i + 1])
            d[:, i] = np.inf
            near = self.A[:, i] & (np.nanmin(np.where(np.isfinite(d), d, np.inf), 1) < reach)
            rows = np.flatnonzero(near)
            for a in range(0, rows.size, 2000):
                rr = rows[a:a + 2000]
                W = np.broadcast_to(P, (rr.size, P.size)).copy()
                for j in range(K):
                    if j == i:
                        continue
                    ox = (self.X[rr, i] - self.X[rr, j])[:, None]
                    oy = (self.Y[rr, i] - self.Y[rr, j])[:, None]
                    r = self.r_out if j == self.me else self.r_p
                    dj = np.hypot(gx[None] + ox, gy[None] + oy)
                    Pj = np.where(np.isfinite(dj), soft_disc(dj, r, self.edge), 0.0)
                    W *= 1.0 - Pj
                f[rr, i] = W.sum(1) / P.sum()
        return f

    # ---------------------------------------------------------- scoring
    def score(self, crop, cx, cy, others, refs: dict, background: bool = False) -> dict:
        """Name the portrait at (cx, cy) from its exposed pixels; with
        `background`, the bare map is a candidate too (post hoc)."""
        names = list(refs)
        offs = [(dx, dy) for dy in OFFS for dx in OFFS]
        # only the scoring disc's pixels carry weight
        Aimg = np.stack([lab(AP.align_icon(crop, cx + dx, cy + dy, self.width)).reshape(-1, 3)[IDX]
                         for dx, dy in offs])                   # (O, P, 3)
        ox = np.asarray([o[0] for o in offs], np.float32)[:, None]
        oy = np.asarray([o[1] for o in offs], np.float32)[:, None]
        qx = cx + ox + UU.ravel()[IDX][None] / self.s
        qy = cy + oy + VV.ravel()[IDX][None] / self.s
        w = np.broadcast_to(DISC_SOFT.ravel()[IDX], qx.shape).copy()
        for x, y, r in others:
            w *= 1.0 - soft_disc(np.hypot(qx - x, qy - y), r, self.edge)
        R = np.stack([refs[a][0].reshape(-1, 3)[IDX] for a in names])   # (C, P, 3)
        Vi = np.stack([refs[a][1].reshape(-1, 3)[IDX] for a in names])
        q = (((Aimg[:, None] - R[None]) ** 2) * Vi[None]).sum(-1)       # (O, C, P)
        if background:
            # POST HOC null candidate: the baked static map (game-texture
            # geometry, never session pixels) aligned at each offset
            Bg = np.stack([lab(AP.align_icon(self.px.static, cx + dx, cy + dy, self.width))
                           for dx, dy in offs])
            gy, gx = np.gradient(Bg.reshape(len(offs), AP.SIDE, AP.SIDE, 3), axis=(1, 2))
            Vb = 1.0 / (self.s2[None, None, None, :]
                        + S_POS * S_POS * (gx * gx + gy * gy) * self.s * self.s)
            Bg, Vb = Bg.reshape(len(offs), -1, 3)[:, IDX], Vb.reshape(len(offs), -1, 3)[:, IDX]
            qb = (((Aimg - Bg) ** 2) * Vb).sum(-1)                       # (O, P)
            q = np.concatenate([q, qb[:, None]], 1)
            names = names + [BACKGROUND]
        unit = 1.0 / (self.s * self.s) / (2 * math.pi * SIGMA_CAL ** 2)
        ll = -0.5 * np.einsum("ocp,op->oc", q, w) * unit
        ob = ll.argmax(0)                                   # best offset per candidate
        best = ll[ob, np.arange(len(names))]
        o = np.argsort(-best)
        c0 = int(o[0])
        wsum = float(w[ob[c0]].sum())
        resid = float((q[ob[c0], c0] * w[ob[c0]]).sum() / max(3.0 * wsum, 1e-9))
        margin = float(best[o[0]] - best[o[1]]) if len(names) > 1 else float("inf")
        wimg = np.zeros(AP.SIDE * AP.SIDE, np.float32)
        wimg[IDX] = w[ob[c0]]
        return {"pick": names[c0], "margin": margin, "resid": resid,
                "exposed": wsum / (self.s * self.s), "unknown": resid > UNKNOWN,
                "w": wimg.reshape(AP.SIDE, AP.SIDE), "off": offs[ob[c0]]}

    def others_truth(self, r, i):
        out = []
        for j in range(len(self.team)):
            if j != i and self.A[r, j]:
                out.append((self.X[r, j], self.Y[r, j], self.r_out if j == self.me else self.r_p))
        return out


# ------------------------------------------------------------------ events

def _members(M: Match, i: int, pre) -> set:
    mem = {i}
    for rr in pre:
        d = np.hypot(M.X[rr] - M.X[rr, i], M.Y[rr] - M.Y[rr, i])
        mem |= {j for j in range(len(M.team)) if j != M.me and M.A[rr, j]
                and d[j] <= MEMBER_R * M.r_out}
    return mem


def partial_frames(M: Match, f: np.ndarray, n: int) -> list[dict]:
    """POST HOC (not in the prediction row): a uniform sample of frames on
    which a living teammate is partly covered (0.02 < share < 0.9), each its
    own one-frame event; `k` is frames since its share was last below
    F_STACKED (within WINDOW_K), else -1."""
    K = len(M.team)
    cand = [(r, i) for i in range(K) if i != M.me
            for r in np.flatnonzero(M.A[:, i] & (f[:, i] > 0.02) & (f[:, i] < 0.9))]
    rng = np.random.default_rng(SEED + 4)
    pick = sorted(rng.choice(len(cand), size=min(n, len(cand)), replace=False).tolist())
    out = []
    for p in pick:
        r, i = cand[p]
        r = int(r)
        k = -1
        for back in range(0, WINDOW_K + 1):
            rr = r - back
            if rr < 0 or (back and not M.contig[rr + 1]):
                break
            if M.A[rr, i] and f[rr, i] < F_STACKED:
                k = back
                break
        mem = _members(M, i, [r])
        out.append({"i": i, "r0": r, "rows": [r], "k_fixed": k, "members": sorted(mem),
                    "roster": sorted(j for j in range(K) if j != M.me and M.A[r, j]),
                    "self_only": mem == {i}})
    return out


def exits(M: Match, f: np.ndarray, thr: float = F_STACKED, run_min: int = STACKED_RUN) -> list[dict]:
    """Every exit: k=0 is the first frame with share >= `thr` after at
    least `run_min` contiguous frames below it (the row: 0.1 and 5)."""
    out = []
    n, K = f.shape
    for i in range(K):
        if i == M.me:
            continue
        st = M.A[:, i] & (f[:, i] < thr)
        run = 0
        for r in range(n):
            if not M.contig[r]:
                run = 0
            if st[r]:
                run += 1
                continue
            if run >= run_min and M.A[r, i] and M.contig[r]:
                rows = [r]
                while (len(rows) <= WINDOW_K and rows[-1] + 1 < n and M.contig[rows[-1] + 1]
                       and M.A[rows[-1] + 1, i]):
                    rows.append(rows[-1] + 1)
                pre = list(range(max(0, r - PRE_K), r + 1))
                mem = {i}
                for rr in pre:
                    d = np.hypot(M.X[rr] - M.X[rr, i], M.Y[rr] - M.Y[rr, i])
                    mem |= {j for j in range(K) if j != M.me and M.A[rr, j]
                            and d[j] <= MEMBER_R * M.r_out}
                roster = {j for j in range(K) if j != M.me and M.A[r, j]}
                out.append({"i": i, "r0": r, "rows": rows, "members": sorted(mem),
                            "roster": sorted(roster), "self_only": mem == {i}})
            run = 0
    return out


# ------------------------------------------------------------------ stored stream

class Stored:
    """The stored round_entity teammate observations, indexed by frame."""

    def __init__(self, sid: str):
        RE = rt.load_round_entity(sid)
        o = np.argsort(RE["frame_idx"], kind="stable")
        self.RE = {k: (v[o] if isinstance(v, np.ndarray) else v) for k, v in RE.items()}
        self.fi = self.RE["frame_idx"]

    def at(self, f: int) -> np.ndarray:
        a, b = np.searchsorted(self.fi, [f, f + 1])
        return np.arange(a, b)

    def matched(self, M: Match, rows_r: list[int]) -> dict:
        """(r, i) -> (stored row index or -1, name) for the frames `rows_r`
        by replay-truth's one-to-one rule within the 8 m gate."""
        ids, fr = [], []
        for r in rows_r:
            k = self.at(int(M.ai_fi[r]))
            ids.append(k)
            fr.append(np.full(k.size, r))
        if not ids:
            return {}
        ids, fr = np.concatenate(ids), np.concatenate(fr)
        D = np.hypot(M.X[fr] - self.RE["x"][ids][:, None], M.Y[fr] - self.RE["y"][ids][:, None])
        j, _d = rt._assign(fr, D, M.gate)
        out = {}
        for k, r, jj in zip(ids, fr, j):
            if jj >= 0 and jj != M.me and self.RE["family"][k] == "ally":
                out[(int(r), int(jj))] = (int(k), self.RE["agent"][k])
        return out


def stored_status(name, truth) -> str:
    if name is None:
        return "refused"
    return "right" if agent_names.same_agent(name, truth) else "wrong"


# ------------------------------------------------------------------ run

def run_match(sid: str, n_events: int, n_frames: int, sheet: bool = True, extra_lag_ms: float = 0.0) -> dict:
    t0 = time.perf_counter()
    M = Match(sid, extra_lag_ms)
    tag = "" if not extra_lag_ms else f"_lag{extra_lag_ms:+g}"
    if M.join["rate"] < MIN_JOIN:
        raise SystemExit(f"{sid}: stored-stream join rate {M.join['rate']} < {MIN_JOIN}; refused")
    f = M.shares()
    rng = np.random.default_rng(SEED)

    def sample(ev, n):
        pick = sorted(rng.choice(len(ev), size=min(n, len(ev)), replace=False).tolist())
        return [ev[k] for k in pick]

    reg_all = exits(M, f)
    loose_all = exits(M, f, 0.5, 3)
    sets = {"registered": sample(reg_all, n_events),
            "posthoc_loose_exits": sample(loose_all, n_events),
            "posthoc_partial_frames": partial_frames(M, f, n_frames)}
    t_setup = time.perf_counter() - t0
    S = Stored(sid)
    need = set()
    for ev in sets.values():
        for e in ev:
            need |= set(range(max(0, e["r0"] - 2), e["rows"][-1] + 1))
    kids = ability_children(M, f)
    for c in kids:
        need |= set(c["rows"])
        need |= {r - 1 for r in c["rows"] if r > 0}
    need = sorted(need)
    stored = S.matched(M, need)
    crops = {}
    t1 = time.perf_counter()
    r_of_t = {float(M.t[r]): r for r in need}
    for t, crop in M.px.crops([float(M.t[r]) for r in need]):
        crops[r_of_t[t]] = crop.copy()
    t_decode = time.perf_counter() - t1
    cost, trig_cost = [], []
    rows_by = {name: score_set(M, S, ev, crops, stored, f, cost, trig_cost)
               for name, ev in sets.items()}
    kid_rows = score_children(M, kids, crops)
    rate = trigger_rate(M, f)
    meta = {"setup_s": round(t_setup, 1), "decode_s": round(t_decode, 1),
            "frames_decoded": len(crops), "join": M.join,
            "events_total": {"registered": len(reg_all), "posthoc_loose_exits": len(loose_all)},
            "posthoc_note": ("posthoc_* sets are NOT in the prediction row: the registered rule "
                             "(share < 0.1 for 5 frames) yields few exits, so a looser exit rule "
                             "(share < 0.5 for 3 frames) and a uniform sample of partly covered "
                             "frames (0.02 < share < 0.9) are reported beside it, labelled")}
    rep = summarise(M, rows_by, kid_rows, rate, cost, trig_cost, meta)
    OUT.mkdir(parents=True, exist_ok=True)
    meta["extra_lag_ms"] = extra_lag_ms
    rep["meta"] = meta
    with open(OUT / f"rows_{sid}{tag}.jsonl", "w", encoding="utf-8") as fh:
        for name, rows in rows_by.items():
            for r in rows:
                fh.write(json.dumps({"set": name} | r) + "\n")
        for r in kid_rows:
            fh.write(json.dumps({"set": "children"} | r) + "\n")
    (OUT / f"report_{sid}{tag}.json").write_text(json.dumps(rep, indent=1), encoding="utf-8")
    if sheet:
        ev = sets["registered"] + sets["posthoc_loose_exits"]
        contact_sheet(M, ev, rows_by["registered"] + rows_by["posthoc_loose_exits"], crops,
                      OUT / f"contact_{sid}{tag}.png")
    return rep


def score_set(M, S, ev, crops, stored, f, cost, trig_cost) -> list[dict]:
    out_rows = []
    for e in ev:
        i = e["i"]
        truth = M.agent[i]
        mem = {M.agent[j]: M.refs[M.agent[j]] for j in e["members"]}
        ros = {M.agent[j]: M.refs[M.agent[j]] for j in e["roster"]}
        real = realistic_names(M, S, e)
        rcand = {a: M.refs[a] for a in real if a in M.refs}
        for k, r in enumerate(e["rows"]):
            if r not in crops:
                continue
            crop = crops[r]
            oth = M.others_truth(r, i)
            row = {"event": f"{M.fi[e['r0']]}:{i}", "k": e.get("k_fixed", k),
                   "frame_idx": int(M.fi[r]), "truth": truth, "f": round(float(f[r, i]), 3),
                   "members": len(mem), "self_only": e["self_only"]}
            if len(mem) >= 2:
                c0 = time.perf_counter()
                o = M.score(crop, M.X[r, i], M.Y[r, i], oth, mem)
                cost.append(time.perf_counter() - c0)
                row |= {"exposed": round(o["exposed"], 1), "oracle": o["pick"],
                        "margin": round(o["margin"], 2), "resid": round(o["resid"], 2),
                        "unknown": bool(o["unknown"])}
                ob = M.score(crop, M.X[r, i], M.Y[r, i], oth, mem, background=True)
                row |= {"bg_pick": ob["pick"], "bg_margin": round(ob["margin"], 2)}
            if len(ros) >= 2:
                o = M.score(crop, M.X[r, i], M.Y[r, i], oth, ros)
                row |= {"roster": o["pick"], "roster_margin": round(o["margin"], 2),
                        "exposed_roster": round(o["exposed"], 1)}
            if len(rcand) >= 2:
                o = M.score(crop, M.X[r, i], M.Y[r, i], oth, rcand)
                row |= {"realcand": o["pick"], "realcand_margin": round(o["margin"], 2),
                        "realcand_unknown": bool(o["unknown"]), "realcand_n": len(rcand),
                        "realcand_has_truth": truth in rcand}
            st = stored.get((r, i))
            row["stored"] = "unlocated" if st is None else stored_status(st[1], truth)
            # realistic: pixel trigger, stored poses and names
            if r - 1 in crops and M.contig[r]:
                c0 = time.perf_counter()
                tr = trigger(M, crops[r - 1], crop, M.X[r, i], M.Y[r, i])
                trig_cost.append(time.perf_counter() - c0)
                row["trigger"] = tr
                if tr and st is not None:
                    k_ = st[0]
                    sx, sy = S.RE["x"][k_], S.RE["y"][k_]
                    if math.hypot(sx - M.X[r, i], sy - M.Y[r, i]) <= M.r_out:
                        oth_s = []
                        for kk in S.at(int(M.ai_fi[r])):
                            if kk != k_:
                                rr = M.r_out if S.RE["family"][kk] == "self" else M.r_p
                                oth_s.append((S.RE["x"][kk], S.RE["y"][kk], rr))
                        names = stored_near(M, S, e["r0"], sx, sy)
                        cand = {a: M.refs[a] for a in names if a in M.refs}
                        if len(cand) >= 2:
                            c0 = time.perf_counter()
                            o = M.score(crop, sx, sy, oth_s, cand)
                            cost.append(time.perf_counter() - c0)
                            row |= {"real": o["pick"], "real_margin": round(o["margin"], 2),
                                    "real_unknown": bool(o["unknown"]),
                                    "real_exposed": round(o["exposed"], 1)}
            out_rows.append(row)
    return out_rows


def realistic_names(M: Match, S: Stored, e: dict) -> list[str]:
    i, r0 = e["i"], e["r0"]
    names = set()
    for r in range(max(0, r0 - WINDOW_K), r0):
        if not M.A[r, i]:
            continue
        for k in S.at(int(M.ai_fi[r])):
            if (S.RE["family"][k] == "ally" and S.RE["agent"][k] is not None and
                    math.hypot(S.RE["x"][k] - M.X[r, i], S.RE["y"][k] - M.Y[r, i])
                    <= NEAR_R * M.r_out):
                names.add(agent_names.canonical_agent(S.RE["agent"][k]))
    if len(names) < 2:
        names = {M.agent[j] for j in range(len(M.team)) if j != M.me}
    return sorted(names)


def stored_near(M: Match, S: Stored, r0: int, x: float, y: float) -> list[str]:
    """Realistic candidates from stored rows only: names observed within
    NEAR_R r_out of (x, y) in the WINDOW_K frames before r0."""
    names = set()
    for r in range(max(0, r0 - WINDOW_K), r0):
        for k in S.at(int(M.ai_fi[r])):
            if (S.RE["family"][k] == "ally" and S.RE["agent"][k] is not None and
                    math.hypot(S.RE["x"][k] - x, S.RE["y"][k] - y) <= NEAR_R * M.r_out):
                names.add(agent_names.canonical_agent(S.RE["agent"][k]))
    if len(names) < 2:
        names = {M.agent[j] for j in range(len(M.team)) if j != M.me}
    return sorted(names)


def trigger(M: Match, prev, crop, x, y) -> bool:
    """The pixel trigger at (x, y): the stack_fit window holding it gained
    at least TRIGGER_MASS of one icon's teal seed mass since the last frame."""
    T1, _B, Wt = cb_maps(M, crop)
    T0, _, _ = cb_maps(M, prev)
    from reticle.stack_fit import stack_windows
    gain = np.maximum(T1 - T0, 0.0) * Wt
    for w in stack_windows(T1, Wt, M.px.slab, M.px.shape):
        a, b, c, d = w["box"]
        if a <= y < b and c <= x < d:
            return bool(gain[a:b, c:d].sum() >= TRIGGER_MASS * M.px.fitter.one)
    return False


def cb_maps(M: Match, crop):
    from reticle.stack_fit import frame_maps
    return frame_maps(crop, M.px.fitter.static_key, M.px.floor)


def trigger_rate(M: Match, f: np.ndarray, n: int = 300) -> dict:
    """Triggered windows per round-minute on random contiguous frame pairs."""
    from reticle.stack_fit import stack_windows
    rng = np.random.default_rng(SEED + 1)
    ok = np.flatnonzero(M.contig)
    rows = sorted(rng.choice(ok, size=min(n, ok.size), replace=False).tolist())
    need = sorted(set(rows) | {r - 1 for r in rows})
    r_of_t = {float(M.t[r]): r for r in need}
    C = {r_of_t[t]: c.copy() for t, c in M.px.crops([float(M.t[r]) for r in need])}
    fired, wins, stacked_fired, cost = 0, 0, 0, []
    for r in rows:
        if r not in C or r - 1 not in C:
            continue
        c0 = time.perf_counter()
        T1, _B, Wt = cb_maps(M, C[r])
        T0, _, _ = cb_maps(M, C[r - 1])
        gain = np.maximum(T1 - T0, 0.0) * Wt
        ws = stack_windows(T1, Wt, M.px.slab, M.px.shape)
        hit = [w for w in ws if gain[w["box"][0]:w["box"][1], w["box"][2]:w["box"][3]].sum()
               >= TRIGGER_MASS * M.px.fitter.one]
        cost.append(time.perf_counter() - c0)
        wins += len(ws)
        fired += len(hit)
        stacked_fired += sum(w["mass"] / M.px.fitter.one > 1.0 for w in hit)
    m = len(cost)
    return {"frames": m, "windows_per_frame": round(wins / max(m, 1), 3),
            "fired_per_frame": round(fired / max(m, 1), 4),
            "fired_per_minute": round(fired / max(m, 1) * 15 * 60, 1),
            "fired_in_stack_windows_per_minute": round(stacked_fired / max(m, 1) * 15 * 60, 1),
            "trigger_ms_median": round(1000 * float(np.median(cost)), 2) if cost else None,
            "trigger_ms_p95": round(1000 * float(np.percentile(cost, 95)), 2) if cost else None}


def ability_children(M: Match, f: np.ndarray, limit: int = 120) -> list[dict]:
    """Teammates' replay children opened while their owner is stacked."""
    E = M.L.entities
    subj = {s_: k for k, s_ in enumerate(M.subjects)}
    ch = np.flatnonzero(E["kind"] == "child")
    # the capture time at which the minimap draws the replay's opening,
    # inverting replay_source.frames_to_replay, and replay-truth's px transform
    t_open = (np.asarray(E["t_open_rep"][ch], float) + M.a + replay_source.MINIMAP_LAG_MS)
    sx, sy = replay_source.to_px(M.ctx["mf"], np.asarray(E["spawn_x"][ch], float),
                                 np.asarray(E["spawn_y"][ch], float))
    kids = []
    for n_, c in enumerate(ch):
        k = subj.get(E["subject"][c])
        t = t_open[n_]
        if k is None or k == M.me or not np.isfinite(t) or not np.isfinite(sx[n_]):
            continue
        r = int(np.searchsorted(M.t, t))
        # the row: owner share < F_STACKED; post hoc also < 0.5 (tagged by owner_f)
        if r >= M.t.size or M.t[r] - t > 100 or not M.A[r, k] or not (f[r, k] < 0.5):
            continue
        rows = [rr for rr in range(r, min(r + 6, M.t.size)) if M.A[rr, k]]
        d = np.hypot(M.X[r] - M.X[r, k], M.Y[r] - M.Y[r, k])
        mem = {k} | {j for j in range(len(M.team)) if j != M.me and M.A[r, j]
                     and d[j] <= MEMBER_R * M.r_out}
        kids.append({"e": int(c), "owner": k, "ability": E["ability"][c] or E["mapped"][c],
                     "owner_f": round(float(f[r, k]), 3),
                     "rows": rows, "members": sorted(mem),
                     "x": float(sx[n_]), "y": float(sy[n_])})
    rng = np.random.default_rng(SEED + 2)
    if len(kids) > limit:
        kids = [kids[k] for k in sorted(rng.choice(len(kids), limit, replace=False))]
    return kids


def score_children(M: Match, kids, crops) -> list[dict]:
    rows = []
    for c in kids:
        mem = {M.agent[j]: M.refs[M.agent[j]] for j in c["members"]}
        if len(mem) < 2:
            continue
        for k, r in enumerate(c["rows"]):
            if r not in crops:
                continue
            oth = [(M.X[r, j], M.Y[r, j], M.r_out if j == M.me else M.r_p)
                   for j in range(len(M.team)) if M.A[r, j]]
            o = M.score(crops[r], c["x"], c["y"], oth, mem)
            ob = M.score(crops[r], c["x"], c["y"], oth, mem, background=True)
            trig = (trigger(M, crops[r - 1], crops[r], c["x"], c["y"])
                    if r - 1 in crops and M.contig[r] else None)
            rows.append({"child": c["e"], "ability": c["ability"], "k": k, "owner_f": c["owner_f"],
                         "owner": M.agent[c["owner"]], "exposed": round(o["exposed"], 1),
                         "pick": o["pick"], "margin": round(o["margin"], 2),
                         "unknown": bool(o["unknown"]), "trigger": trig,
                         "misfire": bool(o["margin"] >= MARGIN and not o["unknown"]),
                         "bg_pick": ob["pick"], "bg_margin": round(ob["margin"], 2),
                         "misfire_bg": bool(ob["pick"] != BACKGROUND and ob["margin"] >= MARGIN)})
    return rows


# ------------------------------------------------------------------ report

def _bin(v, edges):
    for a, b in zip(edges[:-1], edges[1:]):
        if a <= v < b:
            return f"{a:g}-{b:g}" if b < 1e8 else f"{a:g}+"
    return None


def _acc(rows, key, truth="truth"):
    sc = [r for r in rows if r.get(key) is not None]
    right = sum(agent_names.same_agent(r[key], r[truth]) is True for r in sc)
    return {"n": len(sc), "right": right, "acc": round(right / len(sc), 4) if sc else None}


def _acc_block(rows):
    b = {"oracle": _acc(rows, "oracle"),
         "roster": _acc(rows, "roster"), "realcand": _acc(rows, "realcand"),
         "real": _acc(rows, "real")}
    conf = [r for r in rows if r.get("oracle") is not None and r["margin"] >= MARGIN
            and not r["unknown"]]
    cr = sum(agent_names.same_agent(r["oracle"], r["truth"]) is True for r in conf)
    b["oracle_confident"] = {"named": len(conf), "of": b["oracle"]["n"],
                             "right": cr, "right_of_named": round(cr / len(conf), 4) if conf else None,
                             "named_share": round(len(conf) / b["oracle"]["n"], 4) if b["oracle"]["n"] else None}
    unk = [r for r in rows if r.get("oracle") is not None and r["unknown"]]
    b["oracle_unknown_share"] = round(len(unk) / b["oracle"]["n"], 4) if b["oracle"]["n"] else None
    ru = [r for r in rows if r.get("realcand") is not None]
    b["realcand_unknown_share"] = (round(sum(r["realcand_unknown"] for r in ru) / len(ru), 4)
                                   if ru else None)
    b["realcand_truth_in_set"] = (round(sum(r["realcand_has_truth"] for r in ru) / len(ru), 4)
                                  if ru else None)
    st = Counter(r["stored"] for r in rows if r.get("oracle") is not None)
    loc = st["right"] + st["wrong"] + st["refused"]
    b["stored_same_frames"] = dict(st) | {
        "right_of_located": round(st["right"] / loc, 4) if loc else None,
        "right_of_named": round(st["right"] / (st["right"] + st["wrong"]), 4)
        if st["right"] + st["wrong"] else None,
        "right_of_all": round(st["right"] / sum(st.values()), 4) if st else None}
    return b


def _set_report(rows) -> dict:
    by_exp, by_k = defaultdict(list), defaultdict(list)
    for r in rows:
        if r.get("exposed") is not None:
            by_exp[_bin(r["exposed"], EXP_BINS)].append(r)
        for a, b in K_BINS:
            if a <= r["k"] <= b:
                by_k[f"{a}-{b}" if a != b else str(a)].append(r)
        if r["k"] < 0:
            by_k["none_within_15"].append(r)
    ev_first = {}
    for r in rows:
        if r.get("trigger") is not None and 0 <= r["k"] <= 3:
            ev_first.setdefault(r["event"], None)
            if r["trigger"] and ev_first[r["event"]] is None:
                ev_first[r["event"]] = r["k"]
    events = {r["event"] for r in rows}
    fired = sum(v is not None for v in ev_first.values())
    return {"events": len(events), "frames": len(rows),
            "all": _acc_block(rows),
            "evidence_ge_1px": _acc_block([r for r in rows if r.get("exposed", -1) >= 1]),
            "exposed_ge_25": _acc_block([r for r in rows if r.get("exposed", -1) >= 25]),
            "exposed_ge_40": _acc_block([r for r in rows if r.get("exposed", -1) >= 40]),
            "by_exposed_px": {k: _acc_block(v) for k, v in sorted(
                by_exp.items(), key=lambda kv: float(kv[0].split("-")[0].rstrip("+")))},
            "by_k": {k: _acc_block(v) for k, v in by_k.items()},
            "self_only_events": len({r["event"] for r in rows if r["self_only"]}),
            "trigger_by_k3": {"events_with_k0_3": len(ev_first), "fired": fired,
                              "share": round(fired / len(ev_first), 4) if ev_first else None,
                              "first_k": dict(Counter(v for v in ev_first.values() if v is not None))},
            "confusions": dict(Counter(f"{r['truth']}->{r['oracle']}" for r in rows
                                       if r.get("oracle") and r.get("exposed", 0) >= 1
                                       and not agent_names.same_agent(r["oracle"], r["truth"])
                                       ).most_common(12))}


def summarise(M, rows_by, kid_rows, rate, cost, trig_cost, meta) -> dict:
    kid = Counter()
    for r in kid_rows:
        kid["frames"] += 1
        kid["misfire"] += r["misfire"]
        kid["unknown"] += r["unknown"]
        kid["triggered"] += bool(r["trigger"])
        kid["misfire_and_triggered"] += bool(r["misfire"] and r["trigger"])
    return {"version": VERSION, "task": TASK, "session": M.sid, "match": M.L.match,
            "geometry": {"width": M.width, "scale": M.px.shape.scale, "r_out": M.r_out,
                         "r_portrait": round(M.r_p, 2), "aligned_per_native": round(M.s, 4),
                         "scored_disc_native_r": round(0.75 * AP.DISC_R / M.s, 2),
                         "gate_px": round(M.gate, 1)},
            "meta": meta,
            "sets": {name: _set_report(rows) for name, rows in rows_by.items()},
            "trigger_rate": rate,
            "children": dict(kid) | {
                "by_ability": dict(Counter(r["ability"] for r in kid_rows)),
                "misfire_share": round(kid["misfire"] / kid["frames"], 4) if kid["frames"] else None,
                "misfire_and_triggered_share": (round(kid["misfire_and_triggered"] / kid["frames"], 4)
                                                if kid["frames"] else None),
                "exposed_median": float(np.median([r["exposed"] for r in kid_rows])) if kid_rows else None},
            "cost": {"score_calls": len(cost),
                     "score_ms_median": round(1000 * float(np.median(cost)), 2) if cost else None,
                     "score_ms_p95": round(1000 * float(np.percentile(cost, 95)), 2) if cost else None,
                     "trigger_ms_median": round(1000 * float(np.median(trig_cost)), 2) if trig_cost else None}}


# ------------------------------------------------------------------ contact sheet

def contact_sheet(M: Match, ev, rows, crops, path: Path, n: int = 12):
    """Twelve exits, k = -1, 0, 2, 4, 8, 12: the 41 px window round the
    truth centre (nearest-neighbour x4, display only), the exposed weight
    tinted magenta, other teammates' truth centres as small circles."""
    rng = np.random.default_rng(SEED + 3)
    scored = [e for e in ev if len(e["members"]) >= 2]
    sel = [scored[k] for k in sorted(rng.choice(len(scored), min(n, len(scored)), replace=False))]
    by = {(r["event"], r["k"]): r for r in rows}
    ks = (-1, 0, 2, 4, 8, 12)
    Z, H = 4, 41
    tiles = []
    for e in sel:
        i = e["i"]
        key = f"{M.fi[e['r0']]}:{i}"
        line = []
        for k in ks:
            r = e["r0"] + k
            tile = np.zeros((H * Z, H * Z, 3), np.uint8)
            if r in crops and 0 <= r < M.fi.size:
                cx, cy = M.X[r, i], M.Y[r, i]
                if np.isfinite(cx):
                    m = np.float32([[1, 0, (H - 1) / 2 - cx], [0, 1, (H - 1) / 2 - cy]])
                    win = cv2.warpAffine(crops[r], m, (H, H), flags=cv2.INTER_LINEAR)
                    tile = cv2.resize(win, (H * Z, H * Z), interpolation=cv2.INTER_NEAREST)
                    if k >= 0:
                        o = M.score(crops[r], cx, cy, M.others_truth(r, i),
                                    {M.agent[j]: M.refs[M.agent[j]] for j in e["members"]})
                        w = cv2.resize(o["w"], (int(round(AP.SIDE / M.s * Z)),) * 2,
                                       interpolation=cv2.INTER_LINEAR)
                        big = np.zeros((H * Z, H * Z), np.float32)
                        h = w.shape[0]
                        a0 = (H * Z - h) // 2
                        big[a0:a0 + h, a0:a0 + h] = w[:H * Z - a0, :H * Z - a0]
                        tint = np.array([255, 0, 255], np.float32)
                        tile = (tile * (1 - 0.45 * big[..., None]) + tint * 0.45 * big[..., None]).astype(np.uint8)
                    for j in range(len(M.team)):
                        if j != i and M.A[r, j]:
                            p = (int((M.X[r, j] - cx + (H - 1) / 2) * Z), int((M.Y[r, j] - cy + (H - 1) / 2) * Z))
                            cv2.circle(tile, p, 3, (0, 255, 255) if j == M.me else (255, 255, 0), 1)
                    rr = by.get((key, k))
                    txt = f"k{k}"
                    if rr is not None:
                        txt += f" {rr.get('exposed', '-')}px"
                        cv2.putText(tile, f"SED {str(rr.get('oracle'))[:7]} {rr.get('margin', '')}",
                                    (2, H * Z - 18), cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 255, 255), 1)
                        cv2.putText(tile, f"stored {rr['stored']}", (2, H * Z - 4),
                                    cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 255, 255), 1)
                    cv2.putText(tile, txt, (2, 12), cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 255, 255), 1)
            line.append(tile)
        lab_ = np.zeros((H * Z, 150, 3), np.uint8)
        cv2.putText(lab_, M.agent[i][:10], (4, 20), cv2.FONT_HERSHEY_PLAIN, 1.1, (255, 255, 255), 1)
        cv2.putText(lab_, "vs " + ",".join(M.agent[j][:5] for j in e["members"] if j != i),
                    (4, 40), cv2.FONT_HERSHEY_PLAIN, 0.8, (200, 200, 200), 1)
        cv2.putText(lab_, f"f{M.fi[e['r0']]}", (4, 60), cv2.FONT_HERSHEY_PLAIN, 0.8, (200, 200, 200), 1)
        tiles.append(np.hstack([lab_] + line))
    cv2.imwrite(str(path), np.vstack(tiles))


def alignment(sid: str) -> dict:
    """Instrument check: stored ally fits against replay truth on isolated
    teammates (no other icon within NEAR_R r_out), the offset's median and
    p90, and its median component along the motion of running teammates
    (above 20 px/s), where a clock lag shows."""
    ctx = rt.session_context(sid)
    mates = list(ctx["allies"])
    me = mates.index(ctx["me"])
    AI, RE = ctx["AI"], rt.load_round_entity(sid)
    t_of = dict(zip(AI["frame_idx"].tolist(), AI["t_ms"].tolist()))
    fr = np.unique(RE["frame_idx"])
    tt = np.asarray([t_of.get(int(f_), np.nan) for f_ in fr])
    ok = np.isfinite(tt)
    fr, tt = fr[ok], tt[ok]
    lag = replay_source.MINIMAP_LAG_MS
    X, Y, _y, _L = rt.truth_px(ctx["rp"], ctx["mf"], mates, replay_source.frames_to_replay(tt, ctx["a"], lag))
    Xn, Yn, _, _ = rt.truth_px(ctx["rp"], ctx["mf"], mates,
                               replay_source.frames_to_replay(tt + 1000.0 / 15, ctx["a"], lag))
    r = np.clip(np.searchsorted(fr, RE["frame_idx"]), 0, fr.size - 1)
    idx = np.flatnonzero(fr[r] == RE["frame_idx"])
    r = r[idx]
    j, _d = rt._assign(r, np.hypot(X[r] - RE["x"][idx][:, None], Y[r] - RE["y"][idx][:, None]),
                       ctx["gate"])
    r_out = cb.Pixels(sid).shape.r_out
    dd = np.hypot(X[:, :, None] - X[:, None, :], Y[:, :, None] - Y[:, None, :])
    k = X.shape[1]
    dd[:, np.arange(k), np.arange(k)] = np.inf
    iso = np.nanmin(np.where(np.isfinite(dd), dd, np.inf), 2) > NEAR_R * r_out
    sel = (j >= 0) & (j != me) & (RE["family"][idx] == "ally")
    sel &= iso[r, np.clip(j, 0, None)]
    rr, jj, ii = r[sel], j[sel], idx[sel]
    ox, oy = RE["x"][ii] - X[rr, jj], RE["y"][ii] - Y[rr, jj]
    vx, vy = (Xn[rr, jj] - X[rr, jj]) * 15, (Yn[rr, jj] - Y[rr, jj]) * 15
    sp = np.hypot(vx, vy)
    mv = sp > 20
    along = (ox[mv] * vx[mv] + oy[mv] * vy[mv]) / sp[mv]
    dist = np.hypot(ox, oy)
    return {"session": sid, "isolated_fits": int(sel.sum()),
            "offset_px_median": round(float(np.median(dist)), 3),
            "offset_px_p90": round(float(np.percentile(dist, 90)), 3),
            "running_fits": int(mv.sum()),
            "along_motion_px_median": round(float(np.median(along)), 3) if mv.any() else None,
            "implied_lag_ms_median": round(float(np.median(along / sp[mv] * 1000)), 1) if mv.any() else None,
            "r_portrait_px": round(r_out / PORTRAIT_RATIO, 2)}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("session")
    ap.add_argument("--events", type=int, default=200)
    ap.add_argument("--frames", type=int, default=1000, help="post-hoc partial-frame sample")
    ap.add_argument("--no-sheet", action="store_true")
    ap.add_argument("--extra-lag-ms", type=float, default=0.0,
                    help="POST HOC sensitivity: read truth this much later on the capture clock "
                         "(-70 corrects the lag isolated fits show; not in the prediction row)")
    ap.add_argument("--align", action="store_true",
                    help="instrument check only: stored fits against truth on isolated teammates")
    a = ap.parse_args()
    if a.align:
        res = alignment(a.session)
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"alignment_{a.session}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
        print(json.dumps(res))
        return
    rep = run_match(a.session, a.events, a.frames, sheet=not a.no_sheet, extra_lag_ms=a.extra_lag_ms)
    brief = {k: rep[k] for k in ("geometry", "meta", "trigger_rate", "children", "cost")}
    brief["sets"] = {n: {k: v[k] for k in ("events", "frames", "evidence_ge_1px", "exposed_ge_25")}
                     for n, v in rep["sets"].items()}
    print(json.dumps(brief, indent=1))


if __name__ == "__main__":
    main()
