r"""How late the stored minimap streams draw each class, against replay truth.

    .\.venv\Scripts\python.exe prototypes\minimap_lag.py SESSION [SESSION ...]

Measurement for task `teammate-lag-20261006` in the store's
`notes/predictions.jsonl`; that row fixed the design below before any sweep
ran. Nothing in `reticle/` imports this file. Reports go to
`<store>/analysis/minimap-lag-20261006/<session>.json`.

`replay_truth` reads replay truth for a stored frame at capture time `t` as
`frames_to_replay(t, a, MINIMAP_LAG_MS + extra)`; this module sweeps `extra`
from -300 to +300 ms in 1000/60 ms steps. A positive extra reads the replay
earlier: the stored icon trails truth.

* **Classes.** Self (`ally_icon`'s self fit), teammates (`round_entity`
  observations of family ally, and `ally_icon`'s raw icons as the reader
  check) and enemies (`minimap_object` icons).
* **Frames.** The scorer's denominator: `ally_icon` frames inside the
  minimap crop cache's spans with the widget drawn. Each observation joins
  that grid by time (`frame_join.grid_join`, 15 Hz); the join rates are
  reported, and truth is read at the observation's own time.
* **Assignment.** Fixed once at extra 0, one to one within the 8 m gate
  (`replay_truth._assign`), against the class's living players; an
  observation counts only when no other living player of either team lies
  within 2 `r_icon` of its player (isolated). The lag never changes it.
* **Speed.** The assigned player's truth speed in widget px/s, from
  `truth_px` 1000/30 ms either side; bins `SPEED_BINS`; moving is 20+ px/s.
* **Estimate.** The extra minimising the median error on moving icons, with
  a 90% interval by bootstrap over rounds (`best_extra`). Beside it, the
  implied lag of each moving icon: its offset from truth along the motion
  over the speed (`implied_lag_ms`), whose per-round medians are regressed on
  round time (`lag_drift`) against the killfeed alignment's slope.

`--posthoc` runs the design the second prediction row
(`teammate-lag-20261006-netcode-prediction`) fixed after the first sweep:
truth on the killfeed fit's own clock (`replay_truth.capture_to_replay`,
slope kept), speed bins in m/s (`POSTHOC`, moving 4-8 m/s), and each class's
implied lag less the player's in shared rounds (`paired_gap`). Its reports
are `<session>_posthoc.json`. The stored round starts give an independent
check of the clock's drift (`round_start_anchor`).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import replay_truth as rt  # noqa: E402
from reticle import frame_join, replay_source  # noqa: E402

MINIMAP_LAG_VERSION = "minimap-lag-0.1.0"
OUT = rt.STORE / "analysis" / "minimap-lag-20261006"
STEP_MS = 1000.0 / 60.0
EXTRAS_MS = np.round(np.arange(-18, 19) * STEP_MS, 3)
#: Truth speed bins in widget px/s; the last is open.
SPEED_BINS = (0.0, 5.0, 20.0, 40.0)
MOVING_PX_S = 20.0
N_BOOT = 400
#: A player is isolated when no other living player lies within this many r_icon.
ISOLATED_R_ICON = 2.0
#: Fewer moving fits than this in a class leave its estimate unreported.
MIN_MOVING = 300


def subject_px(rp, mf, subs, col, t_rep):
    """Widget px (x, y) of player `subs[col[i]]` at replay time `t_rep[i]`;
    NaN where `col` is negative, the player dead or unsampled."""
    col = np.asarray(col, np.int64)
    t_rep = np.asarray(t_rep, float)
    x = np.full(col.shape, np.nan)
    y = np.full(col.shape, np.nan)
    for c in np.unique(col[col >= 0]):
        m = col == c
        X, Y, _yaw, _L = rt.truth_px(rp, mf, [subs[int(c)]], t_rep[m])
        x[m], y[m] = X[:, 0], Y[:, 0]
    return x, y


def error_matrix(rp, mf, subs, col, t_cap, ox, oy, to_rep, base_lag, extras=EXTRAS_MS):
    """(n, len(extras)) distance in px from each observation to its assigned
    player's truth read at `to_rep(t_cap, base_lag + extra)`."""
    E = np.full((np.size(col), len(extras)), np.nan)
    for k, ex in enumerate(extras):
        x, y = subject_px(rp, mf, subs, col, to_rep(t_cap, base_lag + float(ex)))
        E[:, k] = np.hypot(x - ox, y - oy)
    return E


def best_extra(E, groups, extras=EXTRAS_MS, n_boot=N_BOOT, seed=0) -> dict | None:
    """The extra whose column of `E` has the least median, and its 5-95%
    interval over `n_boot` bootstrap resamples of the `groups` (rows of one
    group are drawn together). Rows with any NaN are dropped first."""
    E = np.asarray(E, float)
    g = np.asarray(groups)
    ok = np.all(np.isfinite(E), axis=1)
    E, g = E[ok], g[ok]
    if E.shape[0] == 0:
        return None
    extras = np.asarray(extras, float)
    med = np.median(E, axis=0)
    best = float(extras[int(np.argmin(med))])
    ug, gi = np.unique(g, return_inverse=True)
    order = np.argsort(gi, kind="stable")
    bounds = np.r_[0, np.cumsum(np.bincount(gi, minlength=ug.size))]
    rng = np.random.default_rng(seed)
    boots = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, ug.size, ug.size)
        rows = np.concatenate([order[bounds[p]:bounds[p + 1]] for p in pick])
        boots[b] = extras[int(np.argmin(np.median(E[rows], axis=0)))]
    lo, hi = np.percentile(boots, [5, 95])
    return {"n": int(E.shape[0]), "groups": int(ug.size), "best_extra_ms": round(best, 1),
            "ci90_ms": [round(float(lo), 1), round(float(hi), 1)],
            "median_err_px_at_best": round(float(med.min()), 3),
            "median_err_px_at_zero": round(float(med[int(np.argmin(np.abs(extras)))]), 3)}


def implied_lag_ms(ox, oy, tx, ty, vx, vy):
    """Each observation's offset from truth along the motion (px), over the
    speed (px/s), in ms: positive when the icon sits behind its player."""
    sp = np.hypot(vx, vy)
    with np.errstate(invalid="ignore", divide="ignore"):
        along = ((ox - tx) * vx + (oy - ty) * vy) / sp
        return -along / sp * 1000.0


def lag_drift(t_ms, lag_ms, groups, min_n=30) -> dict | None:
    """Per-group median of `lag_ms` against the group's median time: Spearman
    rho and the least-squares slope (ms of lag per ms of capture time)."""
    from scipy.stats import spearmanr

    t_ms, lag_ms, g = np.asarray(t_ms, float), np.asarray(lag_ms, float), np.asarray(groups)
    ok = np.isfinite(t_ms) & np.isfinite(lag_ms)
    rows = []
    for u in np.unique(g[ok]):
        m = ok & (g == u)
        if m.sum() >= min_n:
            rows.append((float(np.median(t_ms[m])), float(np.median(lag_ms[m])), int(m.sum())))
    if len(rows) < 4:
        return None
    T, L, N = (np.array(c) for c in zip(*rows))
    slope, icpt = np.polyfit(T, L, 1)
    rho = spearmanr(T, L).statistic
    return {"rounds": len(rows), "spearman_rho": round(float(rho), 3),
            "slope_ms_per_ms": float(f"{slope:.3g}"), "lag_at_first_ms": round(float(slope * T[0] + icpt), 1),
            "lag_at_last_ms": round(float(slope * T[-1] + icpt), 1),
            "per_round": [[round(t / 1000, 1), round(lg, 1), n_] for t, lg, n_ in rows]}


def speed_bin(sp, bins=SPEED_BINS) -> np.ndarray:
    return np.searchsorted(np.asarray(bins), np.asarray(sp, float), side="right") - 1


def bin_label(b: int, bins=SPEED_BINS) -> str:
    lo = bins[b]
    return f"{lo:g}+" if b == len(bins) - 1 else f"{lo:g}-{bins[b + 1]:g}"


#: The post-hoc design (`teammate-lag-20261006-netcode-prediction`): speed in
#: m/s, moving the 4-8 m/s bin (8+ is no run speed), the killfeed slope fitted.
POSTHOC = {"bins": (0.0, 1.5, 4.0, 8.0), "moving": (4.0, 8.0), "unit": "m_s", "align": "ls"}
REGISTERED = {"bins": SPEED_BINS, "moving": (MOVING_PX_S, np.inf), "unit": "px_s", "align": "slope1"}


def class_block(ctx, subs, col, t_cap, ox, oy, rnd, to_rep, design=REGISTERED) -> dict:
    """Sweep, speed bins, implied lag and drift for one class's assigned
    isolated observations."""
    rp, mf = ctx["rp"], ctx["mf"]
    base = replay_source.MINIMAP_LAG_MS
    t_rep = to_rep(t_cap, base)
    tx, ty = subject_px(rp, mf, subs, col, t_rep)
    xa, ya = subject_px(rp, mf, subs, col, t_rep - 1000.0 / 30)
    xb, yb = subject_px(rp, mf, subs, col, t_rep + 1000.0 / 30)
    vx, vy = (xb - xa) * 15.0, (yb - ya) * 15.0
    sp = np.hypot(vx, vy)
    sp_u = sp / (mf.px_per_unit * 100.0) if design["unit"] == "m_s" else sp
    E = error_matrix(rp, mf, subs, col, t_cap, ox, oy, to_rep, base)
    bins = design["bins"]
    sb = speed_bin(sp_u, bins)
    mv = (sp_u >= design["moving"][0]) & (sp_u < design["moving"][1])
    out = {"observations": int(col.size), "moving": int(mv.sum()),
           "by_speed_" + design["unit"]: {}}
    for b in range(len(bins)):
        m = sb == b
        out["by_speed_" + design["unit"]][bin_label(b, bins)] = (
            best_extra(E[m], rnd[m]) if m.sum() >= MIN_MOVING
            else {"n": int(m.sum()), "refused": "too_few"})
    out["moving_best"] = (best_extra(E[mv], rnd[mv]) if mv.sum() >= MIN_MOVING
                          else {"n": int(mv.sum()), "refused": "too_few"})
    il = implied_lag_ms(ox, oy, tx, ty, vx, vy)
    if mv.sum() >= MIN_MOVING:
        v = il[mv & np.isfinite(il)]
        out["implied_lag_ms"] = {"median": round(float(np.median(v)), 1),
                                 "p25": round(float(np.percentile(v, 25)), 1),
                                 "p75": round(float(np.percentile(v, 75)), 1)}
        for b in range(1, len(bins)):
            m = (sb == b) & np.isfinite(il)
            out["implied_lag_ms"][bin_label(b, bins)] = (round(float(np.median(il[m])), 1)
                                                         if m.sum() >= 30 else None)
        out["drift"] = lag_drift(t_cap[mv], il[mv], rnd[mv])
    out["_rows"] = {"t": t_cap[mv], "il": il[mv], "rnd": rnd[mv], "E": E[mv], "col": col[mv]}
    return out


def isolated(X, Y, col, r):
    """True where no other living player in (X, Y) lies within `r` of the
    player `col` (columns of X), row by row."""
    n = col.size
    rows = np.arange(n)
    cx, cy = X[rows, np.clip(col, 0, None)], Y[rows, np.clip(col, 0, None)]
    d = np.hypot(X - cx[:, None], Y - cy[:, None])
    d[rows, np.clip(col, 0, None)] = np.inf
    d = np.where(np.isfinite(d), d, np.inf)
    return (col >= 0) & (d.min(axis=1) > r)


def measure(sid: str, design=REGISTERED, keep_rows: bool = False) -> dict:
    """One session's report. With `keep_rows`, `_rows` holds each class's moving
    rows (time, implied lag, round, column of `_subjects`; `_me` the player,
    the first `_n_mates` columns his team) for a caller to regroup; `main`
    never writes them."""
    from reticle import roi_cache

    ctx = rt.session_context(sid)
    out = {"session": sid, "minimap_lag_version": MINIMAP_LAG_VERSION, "design": design,
           "replay_truth_version": rt.REPLAY_TRUTH_VERSION,
           "minimap_lag_ms": replay_source.MINIMAP_LAG_MS,
           "extras_ms": [float(e) for e in EXTRAS_MS], "head": ctx["out"]}
    if "refused" in ctx["out"]:
        return out
    rp, mf, a, me = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"]
    mates, foes = list(ctx["allies"]), list(ctx["foes"])
    everyone = mates + foes
    c_me = mates.index(me)
    r_icon = float(mf.icon_px)
    rs = rp.round_starts()
    AI = ctx["AI"]
    rec = roi_cache.stored_record(rt.STORE, sid, "minimap")
    sc = roi_cache.spans_mask(AI["t_ms"], (rec or {}).get("spans") or []) & AI["drawn"]
    S_t = AI["t_ms"][sc]
    al = ctx["out"]["align"]
    out["align"] = {k: al.get(k) for k in ("a_ms", "slope", "a_ls_ms", "matched",
                                          "residual_median_ms", "residual_mad_ms")}
    out["joins"] = {}
    if design["align"] == "ls":
        a_, b_ = float(al["a_ls_ms"]), float(al["slope"])
    else:
        a_, b_ = float(a), 1.0

    def to_rep(t, lag):
        return rt.capture_to_replay(t, a_, b_, lag)

    def joined(name, t):
        fj = frame_join.grid_join(t, S_t, rt.GRID_HZ, min_rate=0.0)
        out["joins"][name] = fj.stamp() | {
            "offset_ms_abs_p99": (round(float(np.nanpercentile(np.abs(fj.offset_ms), 99)), 3)
                                  if fj.n_joined else None)}
        return fj.joined

    def prepare(name, fr, t, x, y, cand_cols):
        """Assign each joined observation to a living player among
        `cand_cols` (columns of `everyone`), keep the isolated ones."""
        keep = joined(name, t)
        if keep is None:
            keep = np.zeros(np.size(t), bool)
        fr, t, x, y = fr[keep], t[keep], x[keep], y[keep]
        X, Y, _yaw, _L = rt.truth_px(rp, mf, everyone, to_rep(t, replay_source.MINIMAP_LAG_MS))
        cand = np.asarray(cand_cols)
        D = np.hypot(X[:, cand] - x[:, None], Y[:, cand] - y[:, None])
        j, _d = rt._assign(fr, D, ctx["gate"])
        col = np.where(j >= 0, cand[np.clip(j, 0, None)], -1)
        iso = isolated(X, Y, col, ISOLATED_R_ICON * r_icon)
        out.setdefault("counts", {})[name] = {"joined": int(keep.sum()), "assigned": int((j >= 0).sum()),
                                              "isolated": int(iso.sum())}
        rnd = np.searchsorted(rs, to_rep(t, replay_source.MINIMAP_LAG_MS), side="right") - 1
        return col[iso], t[iso], x[iso], y[iso], rnd[iso]

    blocks = {}
    # self: ally_icon's self fit, assigned to the player only
    has = sc & np.isfinite(AI["self_x"])
    s = prepare("self", AI["frame_idx"][has], AI["t_ms"][has], AI["self_x"][has], AI["self_y"][has],
                [c_me])
    blocks["self"] = class_block(ctx, everyone, *s, to_rep, design)
    # teammates: round_entity family ally, assigned among the non-self teammates
    RE = rt.load_round_entity(sid)
    m = RE["family"] == "ally"
    ally_cols = [c for c in range(len(mates)) if c != c_me]
    s = prepare("ally_round_entity", RE["frame_idx"][m], RE["t_ms"][m], RE["x"][m], RE["y"][m], ally_cols)
    blocks["ally_round_entity"] = class_block(ctx, everyone, *s, to_rep, design)
    s = prepare("ally_ally_icon", AI["icon_frame"], AI["icon_t"], AI["icon_x"], AI["icon_y"], ally_cols)
    blocks["ally_ally_icon"] = class_block(ctx, everyone, *s, to_rep, design)
    # enemies: minimap_object icons, among the foes
    MO = rt.load_minimap_object(sid)
    foe_cols = list(range(len(mates), len(everyone)))
    s = prepare("enemy_minimap_object", MO["enemy_frame"], MO["enemy_t"], MO["enemy_x"], MO["enemy_y"],
                foe_cols)
    blocks["enemy_minimap_object"] = class_block(ctx, everyone, *s, to_rep, design)
    # self and teammates pooled: the drift test
    rows = [blocks[k].pop("_rows") for k in list(blocks)]
    R = dict(zip(blocks, rows))
    out["gap_vs_self_ms"] = {k: paired_gap(R["self"]["rnd"], R["self"]["il"], R[k]["rnd"], R[k]["il"])
                             for k in blocks if k != "self"}
    P = {k: np.concatenate([r[k] for r in rows[:2]]) for k in ("t", "il", "rnd")}
    out["pooled_self_ally_drift"] = lag_drift(P["t"], P["il"], P["rnd"])
    out["classes"] = blocks
    if keep_rows:
        out["_rows"], out["_subjects"], out["_me"], out["_n_mates"] = R, everyone, me, len(mates)
    # the independent anchor: stored round starts (clock_reset) against roundStarted
    out["round_start_anchor"] = round_start_anchor(ctx["rounds"], rs, a)
    return out


def paired_gap(rnd_a, il_a, rnd_b, il_b, min_n=30, n_boot=N_BOOT, seed=0) -> dict | None:
    """Class b's implied lag less class a's: per round, the difference of the
    two classes' medians in rounds where each holds `min_n` finite rows; the
    median over rounds, with a 5-95% interval by bootstrap over those rounds."""
    def per_round(r, v):
        r, v = np.asarray(r), np.asarray(v, float)
        ok = np.isfinite(v)
        return {int(u): float(np.median(v[ok & (r == u)])) for u in np.unique(r[ok])
                if np.sum(ok & (r == u)) >= min_n}
    A, B = per_round(rnd_a, il_a), per_round(rnd_b, il_b)
    both = sorted(set(A) & set(B))
    if len(both) < 3:
        return {"rounds": len(both), "refused": "too_few_rounds"}
    d = np.array([B[u] - A[u] for u in both])
    rng = np.random.default_rng(seed)
    boots = np.median(d[rng.integers(0, d.size, (n_boot, d.size))], axis=1)
    lo, hi = np.percentile(boots, [5, 95])
    return {"rounds": len(both), "gap_ms": round(float(np.median(d)), 1),
            "ci90_ms": [round(float(lo), 1), round(float(hi), 1)],
            "per_round_ms": [round(float(x), 1) for x in d], "round_idx": both}


def round_start_anchor(rounds, rs, a, source="clock_reset", reach_ms=1500.0) -> dict | None:
    """Stored round starts of `source` minus the nearest replay roundStarted
    put on capture time (`rs + a`), within `reach_ms` of their median: the
    median, and the slope and Spearman rho against capture time. An
    independent check of the killfeed offset `a` and its drift."""
    from scipy.stats import spearmanr

    t0 = np.array([r["t_start_ms"] for r in rounds if r.get("start_source") == source], float)
    if t0.size < 4 or np.size(rs) == 0:
        return None
    cand = np.asarray(rs, float) + a
    dd = t0[:, None] - cand[None, :]
    d_ = dd[np.arange(t0.size), np.argmin(np.abs(dd), axis=1)]
    ok = np.abs(d_ - np.median(d_)) <= reach_ms
    if ok.sum() < 4:
        return None
    sl = np.polyfit(t0[ok], d_[ok], 1)[0]
    return {"source": source, "n": int(ok.sum()), "median_ms": round(float(np.median(d_[ok])), 1),
            "slope_ms_per_ms": float(f"{sl:.3g}"),
            "spearman_rho": round(float(spearmanr(t0[ok], d_[ok]).statistic), 3)}


def _default(o):
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--posthoc", action="store_true",
                    help="the post-hoc design: killfeed slope fitted, speed in m/s")
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in args.sessions:
        if sid.startswith("cea8ecbc94ab"):
            print(f"{sid}: held out; refused")
            continue
        rep = measure(sid, POSTHOC if args.posthoc else REGISTERED)
        p = OUT / (f"{sid}_posthoc.json" if args.posthoc else f"{sid}.json")
        p.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
        print(p)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
