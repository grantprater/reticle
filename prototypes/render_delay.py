r"""Capture-only estimators of the minimap's remote-minus-self render delay.

    .\.venv\Scripts\python.exe prototypes\render_delay.py SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\render_delay.py --summary
    .\.venv\Scripts\python.exe prototypes\render_delay.py --peek
    .\.venv\Scripts\python.exe prototypes\render_delay.py --record

Measurement for task `render-delay-estimator-20261006` in the store's
`notes/predictions.jsonl`; that row fixed every estimator below before any ran.
`docs/RENDER_DELAY.md` holds the design they serve. Nothing in `reticle/`
imports this file. Reports go to `<store>/analysis/render-delay-20261006/`.

The captured minimap draws other players later than the player's own icon
[domain:capture/minimap-remote-player-lag]; call the gap Delta. The replay
measured it per match (`prototypes/minimap_lag.py --posthoc`, the paired
gap). Each estimator here reads only stored capture streams and estimates
Delta per match, so the entity layer could correct a capture with no replay:

* **E1 lockstep.** A teammate moving with the player, same heading and speed,
  is drawn `v * Delta` behind where it stands; its offset along the motion
  over the speed is a trailing time, biased by where it truly walks
  (`lockstep`).
* **E2 death X.** A dying player's icon gives way to an X. Extrapolating the
  last live icon to the X gives `tau`, the time the icon would still need;
  teammates' `tau` less the player's own is Delta when both Xs share one
  event delay (`death_tau`).
* **E3 plant.** The planter stands still for the 4 s plant; the plant HUD
  minus the planter icon's stop, self against teammates (`plant_lag`).
* **E4 barrier.** At the buy phase's end every player is freed at once; the
  earliest teammate's motion onset less the player's (`barrier_onsets`).
* **E6 clock.** The HUD round clock against capture time within rounds: the
  capture clock's drift, which no inference question needs (`clock_slope`).

`--peek` measures the duel side on replay truth (tasks `peek-advantage-20261006`
and `sight-geometry-20261006`): each side's 128 Hz sight onset, peek or hold
from movement before it (`peek_study`), and with `--geometry` sight of any
part of a body 42 cm wide (`body_sees`) and each player's distance to the
occluding edge (`edge_distances`).

The ping readout (E5) has no stored reader. The replay is read only to score
(truth Delta from the minimap-lag reports) and for the labelled truth-side
diagnostics: E1's formation bias and E4's behaviour term, computed on replay
positions at the same instants.
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

from reticle.dev_set import FROZEN_DEV, FROZEN_HELD_OUT, FROZEN_HELD_OUT_REPLAY  # noqa: E402

RENDER_DELAY_VERSION = "render-delay-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "render-delay-20261006"
LAG_REPORTS = STORE / "analysis" / "minimap-lag-20261006"
#: Held out from every development measurement; refused by name. `DEV` is the
#: frozen development set its stored results read (`reticle.dev_set`).
HELD_OUT = FROZEN_HELD_OUT + FROZEN_HELD_OUT_REPLAY
DEV = FROZEN_DEV

FRAME_MS = 1000.0 / 15.0
#: A track segment breaks where consecutive observations sit further apart.
SEG_GAP_MS = 2.5 * FRAME_MS
SG_WINDOW = 7
N_BOOT = 400
PRIOR_MS = 50.0
#: The registered recovery criterion.
RECOVER_TOL_MS = 30.0
RECOVER_CI_MS = 80.0
SEPARATE_MS = 70.0

# E1
LS_SPEED = (3.0, 8.0)
LS_HEADING_DEG = 20.0
LS_RATIO = (0.8, 1.25)
LS_SEP_M = (1.0, 12.0)
LS_MIN_RUN = 8
# E2
DX_LOOKBACK_MS = 2000.0
DX_AFTER_LAST_MS = 400.0
DX_R_ICON = 1.5
DX_MOVING = 2.5
DX_FRESH_MS = 1000.0
# E3
PL_STILL = 1.0
PL_WINDOW = (3500.0, 500.0)
PL_SEARCH_MS = 8000.0
PL_MIN = 3
# E4
BO_WINDOW = (2000.0, 2500.0)
BO_UP = 2.5
BO_STILL = 1.0
BO_STILL_FRAMES = 8


# ------------------------------------------------------------ pure functions

def segments(t, gap_ms=SEG_GAP_MS):
    """Start and stop indices (half-open) of runs of `t` with no step above `gap_ms`."""
    t = np.asarray(t, float)
    if t.size == 0:
        return np.zeros(0, int), np.zeros(0, int)
    cut = np.flatnonzero(np.diff(t) > gap_ms) + 1
    return np.r_[0, cut], np.r_[cut, t.size]


def track_velocity(t, x, y, window=SG_WINDOW, gap_ms=SEG_GAP_MS):
    """(vx, vy) in units per second: per contiguous segment, the
    least-squares slope over `window` samples centred on each sample, on the
    samples' own times; the first and last `window // 2` samples take the
    segment's first and last full window. NaN on segments shorter than
    `window`.

    Post hoc (revision row of `render-delay-estimator-20261006`): the
    registered Savitzky-Golay filter (order 2) assumes even spacing, and the
    stored grids step 4 or 5 source frames (67 or 83 ms). At the window's
    centre its derivative equals this order-1 slope; at a segment's end this
    takes the last window's mean slope rather than a quadratic's end
    derivative."""
    from numpy.lib.stride_tricks import sliding_window_view as swv

    t, x, y = (np.asarray(a, float) for a in (t, x, y))
    vx = np.full(t.shape, np.nan)
    vy = np.full(t.shape, np.nan)
    h = window // 2
    for a, b in zip(*segments(t, gap_ms)):
        if b - a < window:
            continue
        T = swv(t[a:b], window) / 1000.0
        Tc = T - T.mean(axis=1, keepdims=True)
        den = np.sum(Tc * Tc, axis=1)
        for src, dst in ((x, vx), (y, vy)):
            V = swv(src[a:b], window)
            sl = np.sum(Tc * (V - V.mean(axis=1, keepdims=True)), axis=1) / den
            dst[a + h:b - h] = sl
            dst[a:a + h] = sl[0]
            dst[b - h:b] = sl[-1]
    return vx, vy


def true_runs(mask, min_len, breaks=None):
    """Start and stop indices (half-open) of runs of True in `mask` at least
    `min_len` long; a True in `breaks` starts a new run at that index."""
    mask = np.asarray(mask, bool)
    if breaks is not None:
        # a sentinel False between every broken pair splits the runs
        brk = np.flatnonzero(np.asarray(breaks, bool))
        ins = np.insert(mask, brk, False)
        pos = np.insert(np.arange(mask.size), brk, -1)
    else:
        ins, pos = mask, np.arange(mask.size)
    m = np.r_[False, ins, False]
    d = np.diff(m.astype(np.int8))
    st, en = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    keep = (en - st) >= min_len
    st, en = st[keep], en[keep]
    return pos[st], pos[en - 1] + 1


def lockstep(ps, vs, pm, vm, px_per_m, speed=LS_SPEED, heading_deg=LS_HEADING_DEG,
             ratio=LS_RATIO, sep_m=LS_SEP_M):
    """Per frame: the co-moving mask and the teammate's trailing time (ms),
    its offset behind the player along the pair's mean heading over the mean
    speed. `ps`, `pm` are (n, 2) positions and `vs`, `vm` (n, 2) velocities
    in px and px/s; positive means the teammate is drawn behind."""
    ps, vs, pm, vm = (np.asarray(a, float) for a in (ps, vs, pm, vm))
    ss, sm = np.hypot(*vs.T), np.hypot(*vm.T)
    with np.errstate(invalid="ignore", divide="ignore"):
        cosang = np.sum(vs * vm, axis=1) / (ss * sm)
        r = sm / ss
        u = vs + vm
        u = u / np.hypot(*u.T)[:, None]
        along = np.sum((pm - ps) * u, axis=1)
        vbar = 0.5 * (ss + sm)
        trail = -along / vbar * 1000.0
    sep = np.hypot(*(pm - ps).T) / px_per_m
    lo, hi = speed[0] * px_per_m, speed[1] * px_per_m
    ok = ((ss >= lo) & (ss <= hi) & (sm >= lo) & (sm <= hi)
          & (cosang >= np.cos(np.radians(heading_deg)))
          & (r >= ratio[0]) & (r <= ratio[1]) & (sep >= sep_m[0]) & (sep <= sep_m[1]))
    return ok & np.isfinite(trail), trail, along, vbar


def within_slope(a, v, groups):
    """Pooled within-group least-squares slope of `a` on `v` (group means removed)."""
    a, v, g = np.asarray(a, float), np.asarray(v, float), np.asarray(groups)
    ok = np.isfinite(a) & np.isfinite(v)
    a, v, g = a[ok], v[ok], g[ok]
    if a.size < 3:
        return None
    _, gi = np.unique(g, return_inverse=True)
    n = np.bincount(gi)
    da = a - (np.bincount(gi, a) / n)[gi]
    dv = v - (np.bincount(gi, v) / n)[gi]
    den = float(np.sum(dv * dv))
    return float(np.sum(da * dv) / den) if den > 0 else None


def death_tau(t_last, p_last, v_last, t_x, p_x):
    """Time (ms) the last live icon, moving on at `v_last` (px/s), would
    still need to reach the X's place along its motion, less the time the X
    already took to appear: positive when the X shows before the drawn icon
    gets there."""
    p_last, v_last, p_x = (np.asarray(a, float) for a in (p_last, v_last, p_x))
    sp = np.hypot(*v_last.T)
    with np.errstate(invalid="ignore", divide="ignore"):
        along = np.sum((p_x - p_last) * v_last, axis=-1) / sp
        return np.asarray(t_last, float) + along / sp * 1000.0 - np.asarray(t_x, float)


def onset(t, speed, t_from, t_to, up=BO_UP, still=BO_STILL, still_frames=BO_STILL_FRAMES):
    """First time in [t_from, t_to] the speed crosses `up` from below,
    linearly interpolated, after at least `still_frames` consecutive samples
    below `still`; NaN when none."""
    t, s = np.asarray(t, float), np.asarray(speed, float)
    m = (t >= t_from) & (t <= t_to) & np.isfinite(s)
    t, s = t[m], s[m]
    if t.size < still_frames + 1:
        return np.nan
    below = s < still
    ar = np.arange(t.size)
    # consecutive still samples ending at each index
    c = ar - np.maximum.accumulate(np.where(~below, ar, -1))
    last_below = np.maximum.accumulate(np.where(below, ar, -1))
    cross = np.flatnonzero((s[1:] >= up) & (s[:-1] < up)) + 1
    j = last_below[cross - 1]
    good = cross[(j >= 0) & (c[np.clip(j, 0, None)] >= still_frames)]
    if good.size == 0:
        return np.nan
    k = int(good[0])
    w = (up - s[k - 1]) / (s[k] - s[k - 1])
    return float(t[k - 1] + w * (t[k] - t[k - 1]))


def stop_time(t, speed, t_window, t_search, still=PL_STILL, min_cover=0.8):
    """Last time before the window `t_window` (lo, hi) at which the speed
    stood at or above `still`, within `t_search` before it, when the speed
    stays below `still` over the window with at least `min_cover` of the
    window's frames present; NaN otherwise."""
    t, s = np.asarray(t, float), np.asarray(speed, float)
    lo, hi = t_window
    w = (t >= lo) & (t <= hi) & np.isfinite(s)
    expect = (hi - lo) / FRAME_MS
    if w.sum() < min_cover * expect or np.any(s[w] >= still):
        return np.nan
    pre = (t < lo) & (t >= lo - t_search) & np.isfinite(s) & (s >= still)
    return float(t[pre].max()) if pre.any() else np.nan


def clock_transitions(t, clock):
    """(capture ms, server elapsed ms) at each one-second step down of the
    HUD clock: the midpoint of the two samples around the step, against the
    clock value it left."""
    t, c = np.asarray(t, float), np.asarray(clock, float)
    ok = np.isfinite(c[1:]) & np.isfinite(c[:-1]) & ((c[:-1] - c[1:]) == 1000.0)
    i = np.flatnonzero(ok)
    return 0.5 * (t[i] + t[i + 1]), -c[i]


def live_start(t, clock, t_from, t_to, live_min=90_000.0, buy_max=1_000.0) -> float:
    """Capture ms the HUD clock turns from the buy phase's 0 to the live
    clock (the barrier drop), as the first sample reading at least
    `live_min` after one reading at most `buy_max`, less half the 2 Hz
    period; NaN when none in [t_from, t_to].

    Post hoc: the registered E4 window centred on the stored round start,
    which is the buy phase's start (`clock_reset` reads the 30 s buy clock),
    not the barrier drop."""
    t, c = np.asarray(t, float), np.asarray(clock, float)
    m = (t >= t_from) & (t <= t_to) & np.isfinite(c)
    t, c = t[m], c[m]
    k = np.flatnonzero((c[1:] >= live_min) & (c[:-1] <= buy_max)) + 1
    return float(t[k[0]] - 250.0) if k.size else np.nan


def clock_segments(t, clock):
    """Segment id per sample: a new segment wherever the clock reads higher than before."""
    c = np.asarray(clock, float)
    return np.cumsum(np.r_[True, (c[1:] > c[:-1])]) if c.size else np.zeros(0, int)


def clock_slope(t, server, groups):
    """Capture ms per server ms minus one, pooled within groups (rounds)."""
    s = within_slope(t, server, groups)
    return None if s is None else s - 1.0


def boot_median(values, groups, n_boot=N_BOOT, seed=0, stat=np.median):
    """`stat` of `values` and its 5-95% interval over bootstrap resamples of
    whole groups."""
    v, g = np.asarray(values, float), np.asarray(groups)
    ok = np.isfinite(v)
    v, g = v[ok], g[ok]
    if v.size == 0:
        return None
    ug, gi = np.unique(g, return_inverse=True)
    rng = np.random.default_rng(seed)
    order = np.argsort(gi, kind="stable")
    bounds = np.r_[0, np.cumsum(np.bincount(gi, minlength=ug.size))]
    boots = np.empty(n_boot)
    for b in range(n_boot):
        pick = rng.integers(0, ug.size, ug.size)
        rows = np.concatenate([order[bounds[p]:bounds[p + 1]] for p in pick])
        boots[b] = stat(v[rows])
    lo, hi = np.percentile(boots, [5, 95])
    return {"est_ms": round(float(stat(v)), 1), "ci90_ms": [round(float(lo), 1), round(float(hi), 1)],
            "n": int(v.size), "groups": int(ug.size)}


def boot_diff(a, b, n_boot=N_BOOT, seed=0):
    """median(a) - median(b) with a 5-95% interval, each sample resampled on its own."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    if a.size == 0 or b.size == 0:
        return {"n_a": int(a.size), "n_b": int(b.size), "refused": "empty_class"}
    rng = np.random.default_rng(seed)
    d = (np.median(a[rng.integers(0, a.size, (n_boot, a.size))], axis=1)
         - np.median(b[rng.integers(0, b.size, (n_boot, b.size))], axis=1))
    lo, hi = np.percentile(d, [5, 95])
    return {"est_ms": round(float(np.median(a) - np.median(b)), 1),
            "ci90_ms": [round(float(lo), 1), round(float(hi), 1)], "n_a": int(a.size), "n_b": int(b.size)}


def recovery_verdict(est: dict | None, truth: float, tol=RECOVER_TOL_MS, ci=RECOVER_CI_MS) -> dict:
    """The registered recovery test of one estimate against truth."""
    if not est or "est_ms" not in est:
        return {"recovers": False, "why": "no_estimate"}
    err = est["est_ms"] - truth
    width = est["ci90_ms"][1] - est["ci90_ms"][0]
    return {"error_ms": round(err, 1), "ci_width_ms": round(width, 1),
            "recovers": bool(abs(err) <= tol and width < ci)}


def convergence(values, rounds_of, round_end_ms, t_first_ms, truth, estimate, tol=RECOVER_TOL_MS):
    """Cumulative `estimate(values[rounds_of <= r])` by round; the capture
    minutes from `t_first_ms` to the end of the round from which it stays
    within `tol` of `truth` to the end (None if it never settles)."""
    v, r = np.asarray(values, float), np.asarray(rounds_of)
    path = []
    for rn in sorted(round_end_ms):
        m = (r <= rn) & np.isfinite(v)
        path.append((rn, float(estimate(v[m])) if m.any() else np.nan))
    ok = [np.isfinite(e) and abs(e - truth) <= tol for _, e in path]
    settled = None
    for i in range(len(ok)):
        if all(ok[i:]):
            settled = path[i][0]
            break
    mins = None if settled is None else round((round_end_ms[settled] - t_first_ms) / 60000.0, 1)
    return {"minutes": mins, "settled_after_round": settled,
            "path": [[rn, None if not np.isfinite(e) else round(e, 1)] for rn, e in path]}


# ------------------------------------------------------------ stored data

def _rows(path, needle=None):
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            if needle and needle not in line:
                continue
            if line.strip():
                yield json.loads(line)


def truth_delta(sid: str) -> dict:
    """The replay-measured Delta (teammates' paired gap over self) and the
    per-class best extras of `minimap_lag.py --posthoc`."""
    d = json.loads((LAG_REPORTS / f"{sid}_posthoc.json").read_text(encoding="utf-8"))
    g = d["gap_vs_self_ms"]["ally_round_entity"]
    cl = d["classes"]
    return {"delta_ms": g["gap_ms"], "ci90_ms": g["ci90_ms"], "rounds": g["rounds"],
            "self_extra_ms": cl["self"]["moving_best"]["best_extra_ms"],
            "ally_extra_ms": cl["ally_round_entity"]["moving_best"]["best_extra_ms"]}


def load_capture(sid: str, rt) -> dict:
    """Stored capture streams: the self track, teammate tracks by entity,
    blue X marks, deaths, rounds, the spike carrier's rounds and the HUD clock."""
    import pyarrow.parquet as pq
    from reticle.store import Store

    S = STORE / "events"
    AI = rt.load_ally_icon(sid)
    has = np.isfinite(AI["self_x"]) & AI["drawn"]
    selfT = {"frame": AI["frame_idx"][has], "t": AI["t_ms"][has],
             "x": AI["self_x"][has], "y": AI["self_y"][has]}
    RE = rt.load_round_entity(sid)
    m = (RE["family"] == "ally") & (RE["entity"] >= 0)
    allies = {}
    for e in np.unique(RE["entity"][m]):
        k = m & (RE["entity"] == e)
        o = np.argsort(RE["t_ms"][k], kind="stable")
        allies[int(e)] = {"frame": RE["frame_idx"][k][o], "t": RE["t_ms"][k][o],
                          "x": RE["x"][k][o], "y": RE["y"][k][o]}
    xt, xx, xy = [], [], []
    for r in _rows(S / "minimap_object" / f"{sid}.jsonl", '"blue":[{'):
        for mk in (r.get("x_marks") or {}).get("blue") or []:
            xt.append(r["t_ms"]), xx.append(mk["x"]), xy.append(mk["y"])
    deaths = [r for r in _rows(S / "death" / f"{sid}.jsonl", "death_verdict")
              if r.get("kind") == "death_verdict" and not r.get("is_revive")]
    st = Store(STORE)
    man = st.read_manifest(sid)
    date = man["ingested_at"][:10]
    rounds = st.read_rounds(sid, date).to_pylist()
    spike = [r for r in _rows(S / "spike_carrier" / f"{sid}.jsonl", '"round"') if r.get("kind") == "round"]
    hp = STORE / "l1" / "hud" / f"date={date}" / f"session={sid}" / "hud.parquet"
    hud = pq.read_table(hp, columns=["t_ms", "clock_ms"]).to_pydict()
    return {"self": selfT, "allies": allies,
            "xmarks": {"t": np.asarray(xt, float), "x": np.asarray(xx, float), "y": np.asarray(xy, float)},
            "deaths": deaths, "rounds": rounds, "spike": spike,
            "hud_t": np.asarray(hud["t_ms"], float),
            "hud_clock": np.asarray([np.nan if c is None else c for c in hud["clock_ms"]], float)}


def add_velocity(tr: dict, px_per_m: float) -> dict:
    vx, vy = track_velocity(tr["t"], tr["x"], tr["y"])
    tr["vx"], tr["vy"] = vx, vy
    tr["speed_m"] = np.hypot(vx, vy) / px_per_m
    return tr


def round_of(t, rounds) -> np.ndarray:
    """Stored round number holding each capture time (by round start), 0 before the first."""
    st = np.array([r["t_start_ms"] for r in rounds], float)
    no = np.array([r["round_no"] for r in rounds])
    o = np.argsort(st)
    i = np.searchsorted(st[o], np.asarray(t, float), side="right") - 1
    return np.where(i >= 0, no[o][np.clip(i, 0, None)], 0)


# ------------------------------------------------------------ estimators on one capture

def e1_lockstep(C, ppm, truth_pos=None) -> dict:
    """E1 over every teammate entity sharing frames with the self track.
    `truth_pos(frame_idx, kind)` -> (n, 2) replay px, when given, adds the
    labelled formation-bias diagnostic on the same frames."""
    S = C["self"]
    rows = {"trail": [], "ep": [], "rnd": [], "along": [], "v": [], "t": [], "true_trail": []}
    ep_id = 0
    for e, A in C["allies"].items():
        fr, ia, ib = np.intersect1d(S["frame"], A["frame"], return_indices=True)
        if fr.size < LS_MIN_RUN:
            continue
        ps = np.c_[S["x"][ia], S["y"][ia]]
        vs = np.c_[S["vx"][ia], S["vy"][ia]]
        pm = np.c_[A["x"][ib], A["y"][ib]]
        vm = np.c_[A["vx"][ib], A["vy"][ib]]
        ok, trail, along, vbar = lockstep(ps, vs, pm, vm, ppm)
        t_sh = S["t"][ia]
        st, en = true_runs(ok, LS_MIN_RUN, breaks=np.r_[False, np.diff(t_sh) > 1.5 * FRAME_MS])
        tt = None
        if truth_pos is not None and st.size:
            Ts, Tm = truth_pos(fr, "self"), truth_pos(fr, ("ally", e))
            with np.errstate(invalid="ignore", divide="ignore"):
                u = vs + vm
                u = u / np.hypot(*u.T)[:, None]
                tt = -np.sum((Tm - Ts) * u, axis=1) / vbar * 1000.0
        for a, b in zip(st, en):
            n = b - a
            rows["trail"].append(trail[a:b])
            rows["ep"].append(np.full(n, ep_id))
            rows["rnd"].append(round_of(S["t"][ia][a:b], C["rounds"]))
            rows["along"].append(along[a:b])
            rows["v"].append(vbar[a:b])
            rows["t"].append(S["t"][ia][a:b])
            rows["true_trail"].append(tt[a:b] if tt is not None else np.full(n, np.nan))
            ep_id += 1
    if not rows["trail"]:
        return {"refused": "no_comoving_episodes"}
    R = {k: np.concatenate(v) for k, v in rows.items()}
    ue = np.unique(R["ep"])
    ep_med = np.array([np.median(R["trail"][R["ep"] == u]) for u in ue])
    ep_rnd = np.array([R["rnd"][R["ep"] == u][0] for u in ue])
    ep_true = np.array([np.nanmedian(R["true_trail"][R["ep"] == u]) if np.isfinite(R["true_trail"][R["ep"] == u]).any()
                        else np.nan for u in ue])
    ep_t = np.array([R["t"][R["ep"] == u][0] for u in ue])
    slope = within_slope(R["along"], R["v"], R["ep"])
    out = {"episodes": int(ue.size), "frames": int(R["trail"].size),
           "comoving_minutes": round(R["trail"].size * FRAME_MS / 60000.0, 2),
           "estimate": boot_median(ep_med, ep_rnd),
           "within_slope_ms": None if slope is None else round(-slope * 1000.0, 1),
           "_samples": {"v": ep_med, "rnd": ep_rnd, "t": ep_t}}
    if np.isfinite(ep_true).any():
        out["truth_formation_bias"] = boot_median(ep_true, ep_rnd)
        out["capture_minus_truth"] = boot_median(ep_med - ep_true, ep_rnd)
    return out


def e2_death_x(C, ppm, r_icon) -> dict:
    """E2 over deaths whose X follows a moving last live icon."""
    X = C["xmarks"]
    reach = DX_R_ICON * r_icon
    taus = {"self": [], "ally": []}
    rnds = {"self": [], "ally": []}
    counts = {"deaths": 0, "x_found": 0, "moving": 0}

    # fresh X marks: none within `reach` in the second before
    order = np.argsort(X["t"], kind="stable")
    Xt, Xx, Xy = X["t"][order], X["x"][order], X["y"][order]

    def fresh(i):
        d = np.hypot(Xx - Xx[i], Xy - Xy[i]) <= reach
        return not np.any(d & (Xt < Xt[i]) & (Xt >= Xt[i] - DX_FRESH_MS))

    for dth in C["deaths"]:
        counts["deaths"] += 1
        kf = float(dth["t_ms"])
        if dth.get("kf_player_death"):
            cls, tracks = "self", [C["self"]]
        elif dth.get("side") == "ally":
            cls, tracks = "ally", list(C["allies"].values())
        else:
            continue
        counts[cls + "_deaths"] = counts.get(cls + "_deaths", 0) + 1
        win = np.flatnonzero((Xt >= kf - DX_LOOKBACK_MS) & (Xt <= kf))
        loc = dth.get("location")
        if loc:
            win = win[np.hypot(Xx[win] - loc[0], Xy[win] - loc[1]) <= reach]
        win = [i for i in win if fresh(i)]
        if not win:
            counts[cls + ":no_fresh_x"] = counts.get(cls + ":no_fresh_x", 0) + 1
            continue
        best, why = None, "no_track_before_x"
        for i in win:
            for tr in tracks:
                k = np.flatnonzero((tr["t"] < Xt[i]) & (tr["t"] >= Xt[i] - DX_AFTER_LAST_MS)
                                   & (np.hypot(tr["x"] - Xx[i], tr["y"] - Xy[i]) <= reach))
                if k.size == 0:
                    continue
                j = k[-1]
                # the track ends at the X: no observation in the 0.4 s after it
                if np.any((tr["t"] > Xt[i]) & (tr["t"] <= Xt[i] + DX_AFTER_LAST_MS)):
                    why = "track_continues"
                    continue
                gap = Xt[i] - tr["t"][j]
                if best is None or gap < best[0]:
                    best = (gap, tr, j, i)
        if best is None:
            counts[cls + ":" + why] = counts.get(cls + ":" + why, 0) + 1
            continue
        counts["x_found"] += 1
        _, tr, j, i = best
        v = np.array([tr["vx"][j], tr["vy"][j]])
        if not np.all(np.isfinite(v)) or np.hypot(*v) / ppm < DX_MOVING:
            continue
        counts["moving"] += 1
        tau = death_tau(tr["t"][j], np.array([tr["x"][j], tr["y"][j]]), v, Xt[i],
                        np.array([Xx[i], Xy[i]]))
        taus[cls].append(float(tau))
        rnds[cls].append(int(dth.get("round_no") or 0))
    a, s = np.asarray(taus["ally"]), np.asarray(taus["self"])
    out = {"counts": counts, "n_ally": int(a.size), "n_self": int(s.size),
           "ally_tau": boot_median(a, np.arange(a.size)) if a.size else None,
           "self_tau": boot_median(s, np.arange(s.size)) if s.size else None,
           "estimate": boot_diff(a, s),
           "_samples": {"ally": a, "self": s, "rnd_ally": np.asarray(rnds["ally"]),
                        "rnd_self": np.asarray(rnds["self"])}}
    return out


def e3_plant(C, ppm) -> dict:
    """E3 over rounds whose spike-carrier row names a planter."""
    e = {"self": [], "ally": []}
    refused = []
    for r in C["spike"]:
        if not r.get("planter_slot") or not r.get("plant_t_ms"):
            continue
        pt = float(r["plant_t_ms"])
        win = (pt - PL_WINDOW[0], pt - PL_WINDOW[1])
        found = []
        for cls, tr in [("self", C["self"])] + [("ally", A) for A in C["allies"].values()]:
            ts = stop_time(tr["t"], tr["speed_m"], win, PL_SEARCH_MS)
            if np.isfinite(ts):
                found.append((cls, ts))
        if len(found) != 1:
            refused.append({"round": r["round_no"], "candidates": len(found)})
            continue
        e[found[0][0]].append(pt - found[0][1])
    out = {"n_self": len(e["self"]), "n_ally": len(e["ally"]), "refused": refused,
           "self_ms": [round(x, 1) for x in e["self"]], "ally_ms": [round(x, 1) for x in e["ally"]]}
    if len(e["self"]) < PL_MIN or len(e["ally"]) < PL_MIN:
        out["estimate"] = {"refused": f"under_{PL_MIN}_per_class"}
    else:
        out["estimate"] = boot_diff(e["self"], e["ally"])
    return out


def e4_barrier(C, ppm, truth_onsets=None) -> dict:
    """E4 per round with a clock_reset start. `truth_onsets(t0)` -> (self,
    [teammates]) onsets in capture ms from replay tracks adds the labelled
    behaviour diagnostic."""
    d, dt, rn, tt = [], [], [], []
    n_rounds = n_live = 0
    for r in C["rounds"]:
        if r.get("start_source") != "clock_reset":
            continue
        n_rounds += 1
        t0 = live_start(C["hud_t"], C["hud_clock"], float(r["t_start_ms"]),
                        float(r["t_start_ms"]) + 60_000.0)
        if not np.isfinite(t0):
            continue
        n_live += 1
        lo, hi = t0 - BO_WINDOW[0], t0 + BO_WINDOW[1]
        s_on = onset(C["self"]["t"], C["self"]["speed_m"], lo, hi)
        m_on = [onset(A["t"], A["speed_m"], lo, hi) for A in C["allies"].values()
                if np.any((A["t"] >= lo) & (A["t"] <= hi))]
        m_on = [x for x in m_on if np.isfinite(x)]
        if not np.isfinite(s_on) or not m_on:
            continue
        d.append(min(m_on) - s_on)
        rn.append(int(r["round_no"]))
        tt.append(t0)
        if truth_onsets is not None:
            ts, tm = truth_onsets(lo, hi)
            tm = [x for x in tm if np.isfinite(x)]
            dt.append(min(tm) - ts if np.isfinite(ts) and tm else np.nan)
    d, rn = np.asarray(d), np.asarray(rn)
    out = {"rounds_clock_reset": n_rounds, "rounds_live_start": n_live, "rounds_used": int(d.size),
           "estimate": boot_median(d, rn) if d.size else None,
           "per_round_ms": [round(float(x), 1) for x in d],
           "_samples": {"v": d, "rnd": rn, "t": np.asarray(tt)}}
    if truth_onsets is not None and d.size:
        dt = np.asarray(dt)
        out["truth_behaviour"] = boot_median(dt, rn)
        out["capture_minus_truth"] = boot_median(d - dt, rn)
        out["per_round_truth_ms"] = [None if not np.isfinite(x) else round(float(x), 1) for x in dt]
    return out


def e6_clock(C) -> dict:
    """E6: the HUD clock's within-round slope against capture time."""
    t, c = C["hud_t"], C["hud_clock"]
    ts, srv, g = [], [], []
    for r in C["rounds"]:
        if r.get("start_source") != "clock_reset":
            continue
        end = r.get("plant_t_ms") or r.get("t_end_ms")
        m = (t >= r["t_start_ms"]) & (t <= float(end)) & np.isfinite(c)
        seg = clock_segments(t[m], c[m])
        for u in np.unique(seg):
            k = seg == u
            a, b = clock_transitions(t[m][k], c[m][k])
            ts.append(a), srv.append(b), g.append(np.full(a.size, r["round_no"] * 100 + int(u)))
    if not ts:
        return {"refused": "no_rounds"}
    T, V, G = (np.concatenate(x) for x in (ts, srv, g))
    est = clock_slope(T, V, G)
    rng = np.random.default_rng(0)
    ug = np.unique(G)
    boots = []
    for _ in range(N_BOOT):
        pick = rng.choice(ug, ug.size)
        rows = np.concatenate([np.flatnonzero(G == u) for u in pick])
        gg = np.concatenate([np.full((G == u).sum(), k) for k, u in enumerate(pick)])
        s = clock_slope(T[rows], V[rows], gg)
        if s is not None:
            boots.append(s)
    lo, hi = np.percentile(boots, [5, 95])
    return {"transitions": int(T.size), "segments": int(ug.size), "drift": float(f"{est:.3g}"),
            "ci90": [float(f"{lo:.3g}"), float(f"{hi:.3g}")]}


# ------------------------------------------------------------ one capture

def measure(sid: str) -> dict:
    if sid.startswith(HELD_OUT):
        raise SystemExit(f"{sid}: held out; refused")
    import replay_truth as rt
    from reticle import replay_source

    ctx = rt.session_context(sid)
    if "refused" in ctx["out"]:
        return {"session": sid, "refused": ctx["out"]["refused"]}
    mf = ctx["mf"]
    ppm = mf.px_per_unit * 100.0
    r_icon = float(mf.icon_px)
    C = load_capture(sid, rt)
    add_velocity(C["self"], ppm)
    for A in C["allies"].values():
        add_velocity(A, ppm)
    T = truth_delta(sid)
    out = {"session": sid, "render_delay_version": RENDER_DELAY_VERSION,
           "replay_truth_version": rt.REPLAY_TRUTH_VERSION, "px_per_m": round(ppm, 3),
           "r_icon_px": round(r_icon, 2), "truth": T,
           "streams": {"self_frames": int(C["self"]["t"].size), "ally_entities": len(C["allies"]),
                       "ally_obs": int(sum(A["t"].size for A in C["allies"].values())),
                       "x_marks": int(C["xmarks"]["t"].size), "deaths": len(C["deaths"]),
                       "rounds": len(C["rounds"])}}
    truth = T["delta_ms"]

    # --- truth-side helpers (labelled diagnostics; never feed an estimate)
    rp, a_ls, slope = ctx["rp"], ctx["clock"][0], ctx["clock"][1]
    me, mates = ctx["me"], list(ctx["allies"])
    self_lag = replay_source.MINIMAP_LAG_MS + T["self_extra_ms"]
    ally_lag = replay_source.MINIMAP_LAG_MS + T["ally_extra_ms"]
    others = [s for s in mates if s != me]
    # assign each teammate entity to a replay teammate by majority over its observations
    ent_player = {}
    for e, A in C["allies"].items():
        X_, Y_, _yaw, _L = rt.truth_px(rp, mf, others, rt.capture_to_replay(A["t"], a_ls, slope, ally_lag))
        D = np.hypot(X_ - A["x"][:, None], Y_ - A["y"][:, None])
        D = np.where(np.isfinite(D), D, np.inf)
        j = np.argmin(D, axis=1)
        okj = D[np.arange(j.size), j] <= ctx["gate"]
        if okj.any():
            ent_player[e] = others[int(np.bincount(j[okj]).argmax())]
    frame_t = dict(zip(C["self"]["frame"].tolist(), C["self"]["t"].tolist()))

    def truth_pos(frames, kind):
        """Replay px at the self icon's server instant of each frame: the
        true formation at the moment the self icon shows."""
        t_cap = np.array([frame_t[int(f)] for f in frames], float)
        t_rep = rt.capture_to_replay(t_cap, a_ls, slope, self_lag)
        s = me if kind == "self" else ent_player.get(kind[1])
        if s is None:
            return np.full((t_cap.size, 2), np.nan)
        X_, Y_, _yaw, _L = rt.truth_px(rp, mf, [s], t_rep)
        return np.c_[X_[:, 0], Y_[:, 0]]

    def truth_onsets(lo, hi):
        """Onsets on replay tracks, put back on capture time at the self
        lag, so they carry no render delay: (self, [teammates])."""
        grid = np.arange(lo, hi + 1e-6, FRAME_MS)
        t_rep = rt.capture_to_replay(grid, a_ls, slope, self_lag)
        res = []
        for s in [me] + others:
            q = rp.sample(s, t_rep)
            px, py = replay_source.to_px(mf, q["x"], q["y"])
            vx, vy = track_velocity(grid, px, py)
            res.append(onset(grid, np.hypot(vx, vy) / ppm, lo, hi))
        return res[0], res[1:]

    est = {}
    est["E0_prior"] = {"estimate": {"est_ms": PRIOR_MS, "ci90_ms": [PRIOR_MS, PRIOR_MS]}}
    est["E1_lockstep"] = e1_lockstep(C, ppm, truth_pos)
    est["E2_death_x"] = e2_death_x(C, ppm, r_icon)
    est["E3_plant"] = e3_plant(C, ppm)
    est["E4_barrier"] = e4_barrier(C, ppm, truth_onsets)
    est["E6_clock"] = e6_clock(C) | {"killfeed_slope_minus_1": float(f"{slope - 1.0:.3g}")}

    # --- verdicts and convergence
    rounds_end = {int(r["round_no"]): float(r.get("t_close_ms") or r["t_end_ms"]) for r in C["rounds"]}
    t_first = min(float(r["t_start_ms"]) for r in C["rounds"])
    for k in ("E0_prior", "E1_lockstep", "E2_death_x", "E3_plant", "E4_barrier"):
        e = est[k]
        e["verdict"] = recovery_verdict(e.get("estimate"), truth)
    for k in ("E1_lockstep", "E4_barrier"):
        smp = est[k].pop("_samples", None)
        if smp is not None and np.size(smp["v"]):
            est[k]["convergence"] = convergence(smp["v"], smp["rnd"], rounds_end, t_first, truth, np.median)
    smp = est["E2_death_x"].pop("_samples")
    if smp["ally"].size and smp["self"].size:
        path = []
        for rn in sorted(rounds_end):
            a_ = smp["ally"][smp["rnd_ally"] <= rn]
            s_ = smp["self"][smp["rnd_self"] <= rn]
            path.append((rn, float(np.median(a_) - np.median(s_)) if a_.size and s_.size else np.nan))
        ok = [np.isfinite(v) and abs(v - truth) <= RECOVER_TOL_MS for _, v in path]
        settled = next((path[i][0] for i in range(len(ok)) if all(ok[i:])), None)
        est["E2_death_x"]["convergence"] = {
            "minutes": None if settled is None else round((rounds_end[settled] - t_first) / 60000.0, 1),
            "settled_after_round": settled,
            "path": [[rn, None if not np.isfinite(v) else round(v, 1)] for rn, v in path]}
    out["estimators"] = est
    return out


# ------------------------------------------------------------ peeker's advantage (replay truth)

#: The development replays (truth episodes are keyed by replay match id).
DEV_REPLAY = {"9acf02f98283": "b03fecd3-8d80-4e6c-bae0-ac2ec0344567",
              "c817691bcd15": "60c7f1e0-095f-4944-87f9-ea613d595598",
              "d3dcfb182ab1": "16a475cb-546e-4fe3-8741-008750e01237"}
PK_HZ = 128.0
PK_PRE_MS = 500.0
PK_SPEED_MS = 300.0
PK_MOVING = 2.0
PK_STILL = 1.0


def first_onset(mask, t) -> float:
    """Time of the first True in `mask`; NaN when none."""
    mask = np.asarray(mask, bool)
    return float(np.asarray(t, float)[int(np.argmax(mask))]) if mask.any() else np.nan


def mean_speed(t, x, y) -> float:
    """Mean horizontal speed (units per second) of a sampled path: path length over time."""
    t, x, y = (np.asarray(a, float) for a in (t, x, y))
    ok = np.isfinite(x) & np.isfinite(y)
    t, x, y = t[ok], x[ok], y[ok]
    if t.size < 2 or t[-1] <= t[0]:
        return np.nan
    return float(np.sum(np.hypot(np.diff(x), np.diff(y))) / ((t[-1] - t[0]) / 1000.0))


def peek_label(sa: float, sb: float, moving=PK_MOVING, still=PK_STILL) -> tuple[str, int | None]:
    """('peek', 0 or 1 for the peeker), 'both_moving', 'both_still', 'mixed' or 'unread'."""
    if not (np.isfinite(sa) and np.isfinite(sb)):
        return "unread", None
    if sa >= moving and sb <= still:
        return "peek", 0
    if sb >= moving and sa <= still:
        return "peek", 1
    if sa >= moving and sb >= moving:
        return "both_moving", None
    if sa <= still and sb <= still:
        return "both_still", None
    return "mixed", None


#: The navigation agent's radius in cm [domain:movement/game-units-are-centimetres].
AGENT_RADIUS_CM = 42.0
#: Hits from the two ends further apart than this along the eye line are two occluders.
SAME_EDGE_CM = 200.0


def body_sees(viewer_c, viewer_yaw, viewer_pitch, target_c, alive, occ, hfov_deg, radius=AGENT_RADIUS_CM):
    """(T,) True where any body point of the target lies in the viewer's
    frustum with a clear segment from the viewer's eye."""
    from reticle import episodes as ep
    from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM

    vc, tc = np.asarray(viewer_c, float), np.asarray(target_c, float)
    eye = vc + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
    d = tc[:, :2] - vc[:, :2]
    n = np.c_[-d[:, 1], d[:, 0]] / np.maximum(np.hypot(*d.T), 1e-9)[:, None]
    n3 = np.c_[n, np.zeros(len(n))] * radius
    te = tc + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
    P = np.stack([tc, te, tc + n3, tc - n3, te + n3, te - n3], axis=1)   # (T, 6, 3)
    T, K = P.shape[:2]
    D = P - eye[:, None, :]
    fr = ep.frustum(np.repeat(viewer_yaw[:, None], K, 1), np.repeat(viewer_pitch[:, None], K, 1), D, hfov_deg)
    cand = fr & np.asarray(alive, bool)[:, None] & np.isfinite(D).all(-1)
    out = np.zeros((T, K), bool)
    if cand.any():
        ti, ki = np.nonzero(cand)
        clear = ~occ.blocked(eye[ti], P[ti, ki])
        out[ti[clear], ki[clear]] = True
    return out.any(axis=1)


def edge_distances(ea, eb, occ):
    """Per sample: each end's distance (cm) to the first occluder along the
    eye-to-eye segment, and whether both hits lie on one occluder; NaN where clear."""
    ea, eb = np.asarray(ea, float), np.asarray(eb, float)
    v = eb - ea
    L = np.linalg.norm(v, axis=1)
    u = v / np.maximum(L, 1e-9)[:, None]
    _ia, da = occ.first_hit(ea, u)
    _ib, db = occ.first_hit(eb, -u)
    hit = (da < L) & (db < L)
    da, db = np.where(hit, da, np.nan), np.where(hit, db, np.nan)
    pa, pb = ea + u * da[:, None], eb - u * db[:, None]
    same = np.linalg.norm(pa - pb, axis=1) <= SAME_EDGE_CM
    return da, db, same & hit


def peek_study(key: str, geometry: bool = False) -> dict:
    """Per truth duel with sight and a first hitter: each side's 128 Hz sight
    onset, the signed gap, the peek label and who hit and killed first."""
    if key.startswith(HELD_OUT) or any(key.startswith(h) for h in ("bd7efa02",)):
        raise SystemExit(f"{key}: held out; refused")
    from reticle import episodes as ep
    from reticle.line_of_sight import Occluders

    tl = ep.from_replay_layer(key)
    occ = Occluders(tl.map)
    ev = {e.event_id: e for e in tl.events}
    idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
    rows = []
    for d in ep.read_episodes(key):
        if d.get("kind") != "duel" or not d.get("sight") or not d.get("first_hitter"):
            continue
        a, b = d["participants"]["a"], d["participants"]["b"]
        dmg = [ev[m] for m in d["members"] if m in ev and ev[m].kind == "damage"]
        if not dmg:
            continue
        t_d = min(e.t_ms for e in dmg)
        grid = np.arange(d["t_start_ms"] - PK_PRE_MS, t_d + 1e-6, 1000.0 / PK_HZ)
        if grid.size < 2:
            continue
        ia, ib = idx[a], idx[b]
        smp = {k: v[[ia, ib]] for k, v in tl.sample(grid).items()}
        sees = ep.sight(smp, [tl.slots[ia], tl.slots[ib]], occ, ep.PARAMS["HFOV_DEG"])
        on_a, on_b = first_onset(sees[0, 1], grid), first_onset(sees[1, 0], grid)
        t_on = np.nanmin([on_a, on_b]) if np.isfinite([on_a, on_b]).any() else np.nan
        sp = [np.nan, np.nan]
        if np.isfinite(t_on):
            g2 = np.arange(t_on - PK_SPEED_MS, t_on + 1e-6, 1000.0 / PK_HZ)
            s2 = tl.sample(g2)
            sp = [mean_speed(g2, s2["x"][k], s2["y"][k]) / 100.0 for k in (ia, ib)]
        lab, pk = peek_label(*sp)
        seer = (None if not np.isfinite(t_on) else
                "both" if on_a == on_b else a if (np.isfinite(on_a) and (not np.isfinite(on_b) or on_a < on_b)) else b)
        geo = {}
        if geometry:
            ca = np.stack([smp["x"][0], smp["y"][0], smp["z"][0]], -1)
            cb = np.stack([smp["x"][1], smp["y"][1], smp["z"][1]], -1)
            alive = smp["alive"][0] & smp["alive"][1]
            ba_ = body_sees(ca, smp["yaw"][0], smp["pitch"][0], cb, alive, occ, ep.PARAMS["HFOV_DEG"])
            bb_ = body_sees(cb, smp["yaw"][1], smp["pitch"][1], ca, alive, occ, ep.PARAMS["HFOV_DEG"])
            geo = {"body_on_a": first_onset(ba_, grid), "body_on_b": first_onset(bb_, grid)}
            from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM
            ea = ca + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
            eb = cb + np.array([0.0, 0.0, EYE_ABOVE_CENTRE_CM])
            ok = alive & np.isfinite(ea).all(1) & np.isfinite(eb).all(1)
            clear = ok & ~occ.blocked(ea, eb) & ~occ.blocked(eb, ea)
            k = int(np.argmax(clear)) if clear.any() else -1
            if k <= 0 or not ok[k - 1]:
                geo["edge"] = "never_blocked" if k == 0 else "never_clear" if k < 0 else "unread"
            else:
                da, db, same = edge_distances(ea[k - 1:k], eb[k - 1:k], occ)
                geo["edge"] = "one_occluder" if same[0] else "two_occluders"
                geo["d_a_cm"], geo["d_b_cm"] = float(da[0]), float(db[0])
        rows.append({**geo, "duel": d["episode_id"], "a": a, "b": b, "on_a": on_a, "on_b": on_b,
                     "gap_ms": (on_b - on_a) if np.isfinite(on_a) and np.isfinite(on_b) else None,
                     "censored": bool(np.isfinite(t_on) and not (np.isfinite(on_a) and np.isfinite(on_b))),
                     "speed_a": sp[0], "speed_b": sp[1], "label": lab,
                     "peeker": None if pk is None else (a, b)[pk],
                     "first_seer": seer, "first_hitter": d["first_hitter"],
                     "killer": (d.get("outcome") or {}).get("killer")})
    return {"match": key, "duels": rows}


def share(flags, n_boot=N_BOOT, seed=0) -> dict | None:
    """Share of True with a 5-95% bootstrap interval."""
    f = np.asarray(flags, float)
    if f.size == 0:
        return None
    rng = np.random.default_rng(seed)
    b = f[rng.integers(0, f.size, (n_boot, f.size))].mean(axis=1)
    lo, hi = np.percentile(b, [5, 95])
    return {"share": round(float(f.mean()), 3), "ci90": [round(float(lo), 3), round(float(hi), 3)],
            "n": int(f.size)}


def peek_summary(rows: list[dict]) -> dict:
    """The registered shares and gap quantiles over duel rows."""
    gaps = np.array([abs(r["gap_ms"]) for r in rows if r["gap_ms"] is not None], float)
    clean = [r for r in rows if r["label"] == "peek"]
    labels = {}
    for r in rows:
        labels[r["label"]] = labels.get(r["label"], 0) + 1
    seer_clean = [r for r in clean if r["first_seer"] not in (None, "both")]
    wide = [r for r in seer_clean if r["gap_ms"] is None or abs(r["gap_ms"]) >= 62.5]
    out = {"duels": len(rows), "labels": labels,
           "clean_share": share([r["label"] == "peek" for r in rows]),
           "mutual": int(gaps.size),
           "censored": int(sum(r["censored"] for r in rows)),
           "abs_gap_ms": None if gaps.size == 0 else {
               q: round(float(np.percentile(gaps, p)), 1)
               for q, p in (("p25", 25), ("median", 50), ("p75", 75), ("p90", 90))},
           "abs_gap_under_62_5": share(gaps < 62.5) if gaps.size else None,
           "abs_gap_under_100": share(gaps < 100.0) if gaps.size else None,
           "peeker_first_damage": share([r["first_hitter"] == r["peeker"] for r in clean]),
           "peeker_kill": share([r["killer"] == r["peeker"] for r in clean if r["killer"]]),
           "first_seer_is_peeker": share([r["first_seer"] == r["peeker"] for r in seer_clean]),
           "first_seer_first_damage_clean_gap_62_5": share([r["first_hitter"] == r["first_seer"]
                                                            for r in wide]),
           "first_seer_first_damage_all": share([r["first_hitter"] == r["first_seer"] for r in rows
                                                 if r["first_seer"] not in (None, "both")])}
    for lab in ("both_moving", "both_still", "mixed"):
        sub = [r for r in rows if r["label"] == lab]
        out[f"{lab}_gap_median_ms"] = (None if not sub or not any(r["gap_ms"] is not None for r in sub)
                                      else round(float(np.median([abs(r["gap_ms"]) for r in sub
                                                                  if r["gap_ms"] is not None])), 1))
    return out


def geometry_summary(rows: list[dict]) -> dict:
    """The registered sight-geometry splits (`sight-geometry-20261006`)."""
    from scipy.stats import spearmanr

    fin = lambda x: x is not None and np.isfinite(x)  # noqa: E731
    mutual = [r for r in rows if fin(r.get("body_on_a")) and fin(r.get("body_on_b"))]
    edges = {}
    for r in rows:
        edges[r.get("edge")] = edges.get(r.get("edge"), 0) + 1
    split = [r for r in mutual if r.get("edge") == "one_occluder"]
    gaps, ratio, pgaps = [], [], []
    for r in split:
        close_a = r["d_a_cm"] < r["d_b_cm"]
        c, f = ("a", "b") if close_a else ("b", "a")
        gaps.append(r[f"body_on_{c}"] - r[f"body_on_{f}"])
        dc, df = sorted((r["d_a_cm"], r["d_b_cm"]))
        ratio.append((df - dc) / (df + dc))
        pgaps.append((r[f"on_{c}"] - r[f"on_{f}"]) if fin(r[f"on_{c}"]) and fin(r[f"on_{f}"]) else np.nan)
        r["_closer"] = r[c]
    gaps, ratio, pgaps = np.asarray(gaps), np.asarray(ratio), np.asarray(pgaps)
    nz = gaps != 0
    out = {"duels": len(rows), "mutual_body": len(mutual), "edge": edges,
           "body_ties": share([r["body_on_a"] == r["body_on_b"] for r in mutual]),
           "point_ties_same_duels": share([r["on_a"] == r["on_b"] for r in mutual
                                           if fin(r["on_a"]) and fin(r["on_b"])]),
           "edge_split": int(len(split)), "edge_split_nonzero": int(nz.sum()),
           "closer_sees_later": share(gaps[nz] > 0) if nz.any() else None,
           "closer_minus_farther_ms": None if not nz.any() else {
               q: round(float(np.percentile(gaps[nz], v)), 1) for q, v in
               (("p10", 10), ("p25", 25), ("median", 50), ("p75", 75), ("p90", 90))},
           "gap_vs_ratio_rho": (round(float(spearmanr(ratio[nz], gaps[nz]).statistic), 3)
                                if nz.sum() >= 5 else None),
           "point_model_closer_sees_later": share(pgaps[np.isfinite(pgaps) & (pgaps != 0)] > 0)
           if np.any(np.isfinite(pgaps) & (pgaps != 0)) else None}
    by_ratio = {}
    for lo, hi in ((0.0, 0.2), (0.2, 0.5), (0.5, 1.01)):
        m = nz & (ratio >= lo) & (ratio < hi)
        by_ratio[f"{lo:g}-{hi:g}"] = {"n": int(m.sum()),
                                      "median_ms": round(float(np.median(gaps[m])), 1) if m.any() else None,
                                      "closer_later": round(float(np.mean(gaps[m] > 0)), 3) if m.any() else None}
    out["by_ratio"] = by_ratio
    clean = [r for r in split if r["label"] == "peek"]
    out["clean_edge_split"] = len(clean)
    out["peeker_is_closer"] = share([r["peeker"] == r["_closer"] for r in clean])
    out["peeker_first_damage_when_closer"] = share([r["first_hitter"] == r["peeker"] for r in clean
                                                    if r["peeker"] == r["_closer"]])
    out["peeker_first_damage_when_farther"] = share([r["first_hitter"] == r["peeker"] for r in clean
                                                     if r["peeker"] != r["_closer"]])
    nzc = [r for r in clean if r["body_on_a"] != r["body_on_b"]]
    out["clean_body_first_seer_is_peeker"] = share([
        (r["a"] if r["body_on_a"] < r["body_on_b"] else r["b"]) == r["peeker"] for r in nzc])
    out["body_first_seer_first_damage"] = share([
        (r["a"] if r["body_on_a"] < r["body_on_b"] else r["b"]) == r["first_hitter"]
        for r in mutual if r["body_on_a"] != r["body_on_b"]])
    for r in split:
        r.pop("_closer", None)
    return out


def summary() -> dict:
    rows = {}
    for sid in DEV:
        p = OUT / f"{sid}.json"
        if p.is_file():
            rows[sid] = json.loads(p.read_text(encoding="utf-8"))
    table = {}
    for k in ("E0_prior", "E1_lockstep", "E2_death_x", "E3_plant", "E4_barrier"):
        table[k] = {}
        for sid, d in rows.items():
            e = d["estimators"][k]
            table[k][sid] = {"estimate": e.get("estimate"), "verdict": e.get("verdict"),
                             "truth_ms": d["truth"]["delta_ms"],
                             "minutes": (e.get("convergence") or {}).get("minutes")}
        ests = {sid: (v["estimate"] or {}) for sid, v in table[k].items()}
        if all("est_ms" in ests.get(s, {}) for s in DEV):
            a = ests["9acf02f98283"]
            sep = all(a["est_ms"] - ests[s]["est_ms"] >= SEPARATE_MS and a["ci90_ms"][0] > ests[s]["ci90_ms"][1]
                      for s in DEV[1:])
            table[k]["separates_9acf02f98283"] = bool(sep)
    return table


def record_ledger() -> list[str]:
    """Record the stored reports in the metrics ledger; return the citation tokens."""
    from reticle import metrics

    deps = {"render_delay": RENDER_DELAY_VERSION}
    toks = []
    for sid in DEV:
        p = OUT / f"{sid}.json"
        if not p.is_file():
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        e = d["estimators"]
        v = {"truth_delta": d["truth"]["delta_ms"], "r_icon_m": round(d["r_icon_px"] / d["px_per_m"], 2)}
        for k, name in (("E1_lockstep", "e1"), ("E2_death_x", "e2"), ("E4_barrier", "e4")):
            est = e[k].get("estimate") or {}
            if "est_ms" in est:
                v[f"{name}_est"] = est["est_ms"]
            for sub in ("truth_formation_bias", "truth_behaviour", "capture_minus_truth"):
                if (e[k].get(sub) or {}).get("est_ms") is not None:
                    v[f"{name}_{sub}"] = e[k][sub]["est_ms"]
        v["e1_episodes"] = e["E1_lockstep"].get("episodes", 0)
        v["e2_n_ally"] = e["E2_death_x"]["n_ally"]
        v["e2_n_self"] = e["E2_death_x"]["n_self"]
        v["e4_rounds"] = e["E4_barrier"].get("rounds_used", 0)
        if "drift" in e["E6_clock"]:
            v["e6_drift"] = e["E6_clock"]["drift"]
        metrics.record("render_delay", part="estimate", session=sid, values=v, deps=deps)
        toks += [f"[metric:render_delay/estimate@{sid}#{k}={x}]" for k, x in v.items()]
    p = OUT / "peek_summary.json"
    if p.is_file():
        s = json.loads(p.read_text(encoding="utf-8"))["pooled"]
        v = {"duels": s["duels"], "gap_under_62_5": s["abs_gap_under_62_5"]["share"],
             "gap_p90_ms": s["abs_gap_ms"]["p90"], "clean_share": s["clean_share"]["share"],
             "peeker_first_damage": s["peeker_first_damage"]["share"],
             "peeker_kill": s["peeker_kill"]["share"],
             "first_seer_first_damage": s["first_seer_first_damage_all"]["share"],
             "first_seer_n": s["first_seer_first_damage_all"]["n"]}
        metrics.record("render_delay", part="peek", session="dev3", values=v, deps=deps)
        toks += [f"[metric:render_delay/peek@dev3#{k}={x}]" for k, x in v.items()]
    p = OUT / "peek_geometry_summary.json"
    if p.is_file():
        g = json.loads(p.read_text(encoding="utf-8"))["pooled"]
        v = {"body_ties": g["body_ties"]["share"], "point_ties": g["point_ties_same_duels"]["share"],
             "edge_split_nonzero": g["edge_split_nonzero"],
             "closer_sees_later": g["closer_sees_later"]["share"],
             "closer_minus_farther_median_ms": g["closer_minus_farther_ms"]["median"],
             "closer_minus_farther_p90_ms": g["closer_minus_farther_ms"]["p90"],
             "gap_vs_ratio_rho": g["gap_vs_ratio_rho"],
             "peeker_is_closer": g["peeker_is_closer"]["share"],
             "peeker_first_damage_when_closer": g["peeker_first_damage_when_closer"]["share"],
             "peeker_first_damage_when_farther": g["peeker_first_damage_when_farther"]["share"],
             "clean_body_first_seer_is_peeker": g["clean_body_first_seer_is_peeker"]["share"]}
        for k, b in g["by_ratio"].items():
            v[f"median_ms_ratio_{k}"] = b["median_ms"]
        metrics.record("render_delay", part="sight_geometry", session="dev3", values=v, deps=deps)
        toks += [f"[metric:render_delay/sight_geometry@dev3#{k}={x}]" for k, x in v.items()]
    return toks


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
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--summary", action="store_true", help="tabulate the stored reports")
    ap.add_argument("--record", action="store_true", help="record the stored reports in the metrics ledger")
    ap.add_argument("--geometry", action="store_true",
                    help="with --peek: body-extent sight and each player's distance to the occluding edge")
    ap.add_argument("--peek", action="store_true",
                    help="the peeker's-advantage study on the development replays' truth duels")
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    if args.peek:
        allrows, per = [], {}
        for sid, key in DEV_REPLAY.items():
            st = peek_study(key, geometry=args.geometry)
            for r in st["duels"]:
                r["_sid"] = sid
            per[sid] = peek_summary(st["duels"])
            allrows.extend(st["duels"])
            (OUT / (f"peek_geometry_{sid}.json" if args.geometry else f"peek_{sid}.json")).write_text(json.dumps(st, indent=1, default=_default),
                                                  encoding="utf-8")
        rep = {"render_delay_version": RENDER_DELAY_VERSION, "per_match": per,
               "pooled": peek_summary(allrows)}
        if args.geometry:
            rep = {"render_delay_version": RENDER_DELAY_VERSION,
                   "per_match": {sid: geometry_summary([r for r in allrows if r.get("_sid") == sid])
                                 for sid in DEV_REPLAY},
                   "pooled": geometry_summary(allrows)}
        p = OUT / ("peek_geometry_summary.json" if args.geometry else "peek_summary.json")
        p.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
        print(json.dumps(rep["pooled"], indent=1, default=_default))
    for sid in args.sessions:
        rep = measure(sid)
        p = OUT / f"{sid}.json"
        p.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
        print(p)
    if args.record:
        print("\n".join(record_ledger()))
    if args.summary:
        s = summary()
        p = OUT / "summary.json"
        p.write_text(json.dumps(s, indent=1, default=_default), encoding="utf-8")
        print(json.dumps(s, indent=1, default=_default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
