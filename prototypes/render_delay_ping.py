r"""Does the lobby's highest ping drive the minimap's remote render delay?

    .\.venv\Scripts\python.exe prototypes\render_delay_ping.py SESSION [SESSION ...]
    .\.venv\Scripts\python.exe prototypes\render_delay_ping.py --summary
    .\.venv\Scripts\python.exe prototypes\render_delay_ping.py --record

Measurement for task `render-delay-ping-20261006` in the store's
`notes/predictions.jsonl`; that row fixed the design before any ping summary
ran. Nothing in `reticle/` imports this file. Reports go to
`<store>/analysis/render-delay-ping-20261006/`.

The captured minimap draws other players later than the player's own icon
[domain:capture/minimap-remote-player-lag]; call the gap Delta. The player's
hypothesis: Delta is driven mostly by the highest ping in the lobby.

* **Ping.** The replay carries every player's ping: vrfkit's
  `fields.parquet`, group `BombPlayerState.BombPlayerState_C`, field `Ping`
  (16 bits, `value_i64`, ms), each player state named by its `Subject`
  field (`replay_actors.Export.player_state_subjects`). The series is a step
  function; per replay round (`roundStarted` to the next) each player's
  value is its median on a 100 ms grid (`round_pings`).
* **Delta per round.** `minimap_lag.measure` on the post-hoc design (the
  killfeed least-squares clock, moving 4-8 m/s): teammates' implied lag less
  the player's, per round (`paired_gap`, which now keeps the round index),
  and enemies' where `minimap_object` holds enough. Per teammate and round,
  the same difference for one teammate (`per_mate_gaps`).
* **Tests.** Within a match, Spearman rho of per-round Delta against per-round
  lobby max, mean and own ping, with a 5-95% bootstrap interval over rounds
  (`boot_spearman`); Delta = c + k * ping pooled over matches, rounds
  resampled within each match (`boot_fit`). Each remote player's own lag
  less the player's over the match, beside his ping (`per_player_lag`),
  tests whether a high-ping player is himself drawn later.
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

RENDER_DELAY_PING_VERSION = "render-delay-ping-0.1.0"
STORE = Path.home() / "reticle-store"
OUT = STORE / "analysis" / "render-delay-ping-20261006"
PARSED = STORE / "external" / "replays" / "parsed" / "vrfkit-0.2.5"
#: The development matches: session -> replay match.
MATCHES = {"9acf02f98283": "b03fecd3-8d80-4e6c-bae0-ac2ec0344567",
           "c817691bcd15": "60c7f1e0-095f-4944-87f9-ea613d595598",
           "d3dcfb182ab1": "16a475cb-546e-4fe3-8741-008750e01237"}
HELD_OUT = ("cea8ecbc94ab", "bd7efa02")
PS_GROUP = "/Game/GameModes/Bomb/BombPlayerState.BombPlayerState_C"
GRID_MS = 100.0
N_BOOT = 2000
MIN_N = 30


def ping_series(match: str) -> dict:
    """Subject -> (t_ms, ping_ms) of every `Ping` row of its player state,
    sorted by time; the guids no `Subject` row names are counted apart."""
    import pyarrow as pa
    import pyarrow.compute as pc
    import pyarrow.parquet as pq

    F = pq.read_table(PARSED / match / "export" / "fields.parquet",
                      columns=["time_ms", "actor_net_guid", "group_path", "field_name",
                               "value_i64", "value_str"])
    fn = pc.cast(F["field_name"], pa.string())
    gp = pc.cast(F["group_path"], pa.string())
    F = F.filter(pc.and_(pc.equal(gp, PS_GROUP), pc.is_in(fn, value_set=pa.array(["Ping", "Subject"]))))
    fn = np.array(pc.cast(F["field_name"], pa.string()).to_pylist(), dtype=object)
    g = F["actor_net_guid"].to_numpy().astype(np.int64)
    t = F["time_ms"].to_numpy().astype(np.float64)
    v = F["value_i64"].to_numpy(zero_copy_only=False)
    s = np.array(pc.cast(F["value_str"], pa.string()).to_pylist(), dtype=object)
    sub = {}
    for gg, ss in zip(g[fn == "Subject"], s[fn == "Subject"]):
        if ss:
            sub.setdefault(int(gg), ss)
    pm = fn == "Ping"
    out, unnamed = {}, 0
    for gg in np.unique(g[pm]):
        m = pm & (g == gg)
        if int(gg) not in sub:
            unnamed += int(m.sum())
            continue
        o = np.argsort(t[m], kind="stable")
        out.setdefault(sub[int(gg)], []).append((t[m][o], v[m][o].astype(float)))
    series = {}
    for k, parts in out.items():
        tt = np.concatenate([p[0] for p in parts])
        vv = np.concatenate([p[1] for p in parts])
        o = np.argsort(tt, kind="stable")
        series[k] = (tt[o], vv[o])
    return {"series": series, "rows": int(pm.sum()), "unnamed_rows": unnamed,
            "guids": int(np.unique(g[pm]).size)}


def step_at(t, v, grid):
    """The step series' value at each grid time (last row at or before it);
    NaN before its first row."""
    i = np.searchsorted(t, grid, side="right") - 1
    return np.where(i >= 0, v[np.clip(i, 0, None)], np.nan)


def round_pings(series: dict, rs, end_ms) -> dict:
    """Subject -> per-round median ping on a GRID_MS grid over
    [rs[i], rs[i+1]) (the last round to `end_ms`)."""
    bounds = np.r_[np.asarray(rs, float), float(end_ms)]
    out = {}
    for s, (t, v) in series.items():
        med = np.full(len(rs), np.nan)
        for i in range(len(rs)):
            grid = np.arange(bounds[i], bounds[i + 1], GRID_MS)
            x = step_at(t, v, grid)
            if np.isfinite(x).any():
                med[i] = np.nanmedian(x)
        out[s] = med
    return out


def per_mate_gaps(R: dict, subjects: list, me: str, n_mates: int, min_n=MIN_N) -> list:
    """(teammate, round, gap ms): one teammate's median implied lag in a round
    less the player's, where each holds `min_n` moving rows."""
    S, A = R["self"], R["ally_round_entity"]
    rows = []
    for u in np.unique(S["rnd"]):
        ms = (S["rnd"] == u) & np.isfinite(S["il"])
        if ms.sum() < min_n:
            continue
        ls = float(np.median(S["il"][ms]))
        for c in range(n_mates):
            if subjects[c] == me:
                continue
            ma = (A["rnd"] == u) & (A["col"] == c) & np.isfinite(A["il"])
            if ma.sum() >= min_n:
                rows.append((subjects[c], int(u), float(np.median(A["il"][ma])) - ls))
    return rows


def per_player_lag(R: dict, subjects: list, me: str, n_mates: int, pings: dict,
                   n_boot=N_BOOT, seed=0) -> list:
    """Each remote player's median implied lag over the match less the
    player's, from teammates' `round_entity` and enemies' `minimap_object`
    rows, with a 5-95% interval resampling rounds; beside his match ping."""
    S = R["self"]
    rng = np.random.default_rng(seed)
    out = []
    for key, cols in (("ally_round_entity", range(n_mates)),
                      ("enemy_minimap_object", range(n_mates, len(subjects)))):
        A = R[key]
        for c in cols:
            if subjects[c] == me:
                continue
            m = (A["col"] == c) & np.isfinite(A["il"])
            if m.sum() < MIN_N:
                continue
            us = np.unique(A["rnd"][m])
            boots = np.empty(n_boot)
            for b in range(n_boot):
                pick = us[rng.integers(0, us.size, us.size)]
                ia = np.concatenate([np.flatnonzero(m & (A["rnd"] == u)) for u in pick])
                isf = np.concatenate([np.flatnonzero((S["rnd"] == u) & np.isfinite(S["il"])) for u in pick])
                boots[b] = (np.median(A["il"][ia]) - np.median(S["il"][isf])) if isf.size else np.nan
            ms = np.isfinite(S["il"]) & np.isin(S["rnd"], us)
            out.append({"side": "ally" if c < n_mates else "enemy", "rows": int(m.sum()),
                        "rounds": int(us.size), "ping_ms": pings[subjects[c]],
                        "gap_ms": round(float(np.median(A["il"][m]) - np.median(S["il"][ms])), 1),
                        "ci90_ms": [round(float(v), 1) for v in np.nanpercentile(boots, [5, 95])]})
    return out


def _rank_rows(X):
    from scipy.stats import rankdata
    return rankdata(X, axis=1)


def boot_spearman(x, y, groups=None, n_boot=N_BOOT, seed=0) -> dict | None:
    """Spearman rho of `y` on `x` and its 5-95% interval; resampling draws
    whole `groups` (default: each pair its own group)."""
    from scipy.stats import spearmanr

    x, y = np.asarray(x, float), np.asarray(y, float)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y = x[ok], y[ok]
    g = np.arange(x.size) if groups is None else np.asarray(groups)[ok]
    if x.size < 4 or np.ptp(x) == 0:
        return {"n": int(x.size), "refused": "too_few_or_constant"}
    rho = float(spearmanr(x, y).statistic)
    rng = np.random.default_rng(seed)
    ug, gi = np.unique(g, return_inverse=True)
    if ug.size == x.size:
        idx = rng.integers(0, x.size, (n_boot, x.size))
    else:
        members = [np.flatnonzero(gi == k) for k in range(ug.size)]
        picks = rng.integers(0, ug.size, (n_boot, ug.size))
        idx = [np.concatenate([members[p] for p in row]) for row in picks]
    boots = np.empty(n_boot)
    if isinstance(idx, np.ndarray):
        RX, RY = _rank_rows(x[idx]), _rank_rows(y[idx])
        RX -= RX.mean(1, keepdims=True)
        RY -= RY.mean(1, keepdims=True)
        with np.errstate(invalid="ignore", divide="ignore"):
            boots = (RX * RY).sum(1) / np.sqrt((RX ** 2).sum(1) * (RY ** 2).sum(1))
    else:
        for b, ii in enumerate(idx):
            boots[b] = spearmanr(x[ii], y[ii]).statistic
    lo, hi = np.nanpercentile(boots, [5, 95])
    return {"n": int(x.size), "groups": int(ug.size), "rho": round(rho, 3),
            "ci90": [round(float(lo), 3), round(float(hi), 3)]}


def boot_fit(x, y, strata, n_boot=N_BOOT, seed=0) -> dict | None:
    """Least squares y = c + k x and 5-95% intervals of c and k, resampling
    rows within each stratum."""
    x, y, st = np.asarray(x, float), np.asarray(y, float), np.asarray(strata)
    ok = np.isfinite(x) & np.isfinite(y)
    x, y, st = x[ok], y[ok], st[ok]
    if x.size < 4 or np.ptp(x) == 0:
        return {"n": int(x.size), "refused": "too_few_or_constant"}
    k, c = np.polyfit(x, y, 1)
    rng = np.random.default_rng(seed)
    parts = [np.flatnonzero(st == u) for u in np.unique(st)]
    idx = np.concatenate([p[rng.integers(0, p.size, (n_boot, p.size))] for p in parts], axis=1)
    X, Y = x[idx], y[idx]
    xm, ym = X.mean(1, keepdims=True), Y.mean(1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        kb = ((X - xm) * (Y - ym)).sum(1) / ((X - xm) ** 2).sum(1)
    cb = ym[:, 0] - kb * xm[:, 0]
    resid = y - (c + k * x)
    return {"n": int(x.size), "k": round(float(k), 3), "c_ms": round(float(c), 1),
            "k_ci90": [round(float(v), 3) for v in np.nanpercentile(kb, [5, 95])],
            "c_ci90_ms": [round(float(v), 1) for v in np.nanpercentile(cb, [5, 95])],
            "resid_sd_ms": round(float(resid.std(ddof=2)), 1),
            "x_range": [round(float(x.min()), 1), round(float(x.max()), 1)]}


def measure(sid: str) -> dict:
    import minimap_lag as ml
    from reticle.replay_source import Replay

    match = MATCHES[sid]
    rep = ml.measure(sid, ml.POSTHOC, keep_rows=True)
    R, subjects, me, n_mates = rep.pop("_rows"), rep.pop("_subjects"), rep.pop("_me"), rep.pop("_n_mates")
    rp = Replay(match, STORE)
    rs = rp.round_starts()
    P = ping_series(match)
    assert set(P["series"]) == set(rp.subjects) == set(subjects), "player sets differ"
    RP = round_pings(P["series"], rs, rp.duration_ms)
    mates = subjects[:n_mates]
    foes = subjects[n_mates:]
    M = np.array([RP[s] for s in subjects])            # (10, rounds)
    lobby = {"max": np.nanmax(M, 0), "mean": np.nanmean(M, 0), "own": RP[me],
             "ally_max": np.nanmax(M[:n_mates], 0), "enemy_max": np.nanmax(M[n_mates:], 0),
             "max_other": np.nanmax(np.array([RP[s] for s in subjects if s != me]), 0),
             "second": np.sort(M, 0)[-2]}
    whole = {}
    for s in subjects:
        t, v = P["series"][s]
        grid = np.arange(rs[0], rp.duration_ms, GRID_MS)
        x = step_at(t, v, grid)
        whole[s] = {"median": float(np.nanmedian(x)), "p10": float(np.nanpercentile(x, 10)),
                    "p90": float(np.nanpercentile(x, 90)), "rows": int(t.size),
                    "side": "self" if s == me else ("ally" if s in mates else "enemy")}
    gaps = rep["gap_vs_self_ms"]
    rounds = []
    for key, name in (("ally_round_entity", "delta_ally"), ("enemy_minimap_object", "delta_enemy")):
        g = gaps.get(key) or {}
        for u, d in zip(g.get("round_idx") or [], g.get("per_round_ms") or []):
            rounds.append((name, int(u), float(d)))
    per_round = {}
    for name, u, d in rounds:
        r = per_round.setdefault(u, {"round": u, **{k: (None if not np.isfinite(v[u]) else round(float(v[u]), 2))
                                                    for k, v in lobby.items()}})
        r[name] = d
    mate_rows = per_mate_gaps(R, subjects, me, n_mates)
    mate = [{"side_slot": mates.index(s), "round": u, "gap_ms": round(d, 1),
             "mate_ping": round(float(RP[s][u]), 2), "own_ping": round(float(RP[me][u]), 2),
             "lobby_max": round(float(lobby["max"][u]), 2)} for s, u, d in mate_rows]
    return {"session": sid, "match": match, "version": RENDER_DELAY_PING_VERSION,
            "minimap_lag_version": ml.MINIMAP_LAG_VERSION, "replay_truth_version": rep["replay_truth_version"],
            "ping_field": {"group": PS_GROUP, "field": "Ping", "rows": P["rows"], "guids": P["guids"],
                           "unnamed_rows": P["unnamed_rows"], "players": len(P["series"])},
            "gap_vs_self_ms": {k: {kk: vv for kk, vv in v.items() if kk != "per_round_ms"}
                               for k, v in gaps.items()},
            "players": sorted(whole.values(), key=lambda w: (w["side"], -w["median"])),
            "per_round": [per_round[u] for u in sorted(per_round)],
            "per_mate_round": mate,
            "per_player_lag": per_player_lag(R, subjects, me, n_mates,
                                             {k: v["median"] for k, v in whole.items()}),
            "rounds_replay": int(len(rs))}


def summary() -> dict:
    reps = {sid: json.loads((OUT / f"{sid}.json").read_text(encoding="utf-8"))
            for sid in MATCHES if (OUT / f"{sid}.json").exists()}
    out = {"version": RENDER_DELAY_PING_VERSION, "matches": {}, "pooled": {}}
    X = {k: [] for k in ("max", "mean", "own", "ally_max", "enemy_max", "max_other", "second")}
    Y, ST = [], []
    for sid, r in reps.items():
        rows = [x for x in r["per_round"] if x.get("delta_ally") is not None]
        d = np.array([x["delta_ally"] for x in rows])
        m = {"delta_ms": r["gap_vs_self_ms"]["ally_round_entity"].get("gap_ms"),
             "delta_ci90": r["gap_vs_self_ms"]["ally_round_entity"].get("ci90_ms"),
             "delta_enemy_ms": (r["gap_vs_self_ms"].get("enemy_minimap_object") or {}).get("gap_ms"),
             "rounds": len(rows)}
        for k in X:
            v = np.array([np.nan if x[k] is None else x[k] for x in rows], float)
            m[f"{k}_median"] = round(float(np.nanmedian(v)), 1)
            m[f"{k}_p10_p90"] = [round(float(np.nanpercentile(v, q)), 1) for q in (10, 90)]
            if k in ("max", "mean", "own", "max_other", "ally_max", "enemy_max"):
                m[f"rho_{k}"] = boot_spearman(v, d)
            X[k].extend(v.tolist())
        m["fit_max"] = boot_fit([x["max"] for x in rows], d, np.zeros(len(rows)))
        er = [x for x in r["per_round"] if x.get("delta_enemy") is not None]
        if len(er) >= 4:
            m["rho_max_enemy_delta"] = boot_spearman([x["max"] for x in er], [x["delta_enemy"] for x in er])
        pm = r["per_mate_round"]
        if pm:
            g = [f'{x["round"]}' for x in pm]
            m["mate_rho_own_ping"] = boot_spearman([x["mate_ping"] for x in pm], [x["gap_ms"] for x in pm], g)
            m["mate_rho_ping_minus_own"] = boot_spearman(
                [x["mate_ping"] - x["own_ping"] for x in pm], [x["gap_ms"] for x in pm], g)
            # per teammate: median gap against median ping, across the four teammates
            slots = sorted({x["side_slot"] for x in pm})
            m["mate_median"] = [{"slot": s_,
                                 "gap_ms": round(float(np.median([x["gap_ms"] for x in pm if x["side_slot"] == s_])), 1),
                                 "ping": round(float(np.median([x["mate_ping"] for x in pm if x["side_slot"] == s_])), 1),
                                 "rounds": sum(1 for x in pm if x["side_slot"] == s_)} for s_ in slots]
        m["players"] = r["players"]
        m["per_player_lag"] = r.get("per_player_lag")
        out["matches"][sid] = m
        Y.extend(d.tolist())
        ST.extend([sid] * len(rows))
    for k in X:
        out["pooled"][f"fit_{k}"] = boot_fit(X[k], Y, ST)
    # between matches: match median Delta against match medians
    mm = out["matches"]
    out["between"] = {k: [[sid, mm[sid][f"{k}_median"], mm[sid]["delta_ms"]] for sid in mm]
                      for k in ("max", "mean", "own", "max_other")}
    return out


def scoreboard_open(sid: str) -> dict:
    """Stored scoreboard coverage: 2 Hz samples offered and open (the Tab
    board read), from the scoreboard stream's coverage row."""
    with open(STORE / "events" / "scoreboard" / f"{sid}.jsonl", encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") == "coverage":
                return {"offered": r["frames_offered"], "open": r["frames_open"],
                        "version": r["scoreboard_version"]}
    return {}


def record_ledger() -> list[str]:
    """Record the stored reports in the metrics ledger; return the citation tokens."""
    from reticle import metrics

    deps = {"render_delay_ping": RENDER_DELAY_PING_VERSION}
    s = json.loads((OUT / "summary.json").read_text(encoding="utf-8"))
    toks = []
    for sid, m in s["matches"].items():
        r = json.loads((OUT / f"{sid}.json").read_text(encoding="utf-8"))
        own = next(p["median"] for p in m["players"] if p["side"] == "self")
        top = max(m["per_player_lag"], key=lambda p: p["ping_ms"])
        rest = [p["gap_ms"] for p in m["per_player_lag"] if p is not top and p["side"] == top["side"]]
        sb = scoreboard_open(sid)
        v = {"delta": m["delta_ms"], "lobby_max": m["max_median"], "lobby_mean": m["mean_median"],
             "own_ping": own, "lobby_max_p10": m["max_p10_p90"][0], "lobby_max_p90": m["max_p10_p90"][1],
             "rounds": m["rounds"], "ping_rows": r["ping_field"]["rows"],
             "rho_max": m["rho_max"]["rho"], "rho_max_lo": m["rho_max"]["ci90"][0],
             "rho_max_hi": m["rho_max"]["ci90"][1], "rho_mean": m["rho_mean"]["rho"],
             "rho_own": m["rho_own"]["rho"], "rho_own_lo": m["rho_own"]["ci90"][0],
             "rho_own_hi": m["rho_own"]["ci90"][1],
             "mate_rho_ping": m["mate_rho_own_ping"]["rho"],
             "mate_rho_ping_lo": m["mate_rho_own_ping"]["ci90"][0],
             "mate_rho_ping_hi": m["mate_rho_own_ping"]["ci90"][1],
             "top_ping": top["ping_ms"], "top_ping_side": top["side"], "top_ping_gap": top["gap_ms"],
             "top_ping_gap_lo": top["ci90_ms"][0], "top_ping_gap_hi": top["ci90_ms"][1],
             "same_side_gap_min": min(rest), "same_side_gap_max": max(rest),
             "sb_open_s_per_round": round(sb["open"] / 2.0 / r["rounds_replay"], 1)}
        metrics.record("render_delay", part="ping", session=sid, values=v, deps=deps)
        toks += [f"[metric:render_delay/ping@{sid}#{k}={x}]" for k, x in v.items()]
    f = s["pooled"]["fit_max"]
    v = {"k": f["k"], "k_lo": f["k_ci90"][0], "k_hi": f["k_ci90"][1], "c": f["c_ms"],
         "c_lo": f["c_ci90_ms"][0], "c_hi": f["c_ci90_ms"][1], "resid_sd": f["resid_sd_ms"], "n": f["n"]}
    metrics.record("render_delay", part="ping_fit", session="dev3", values=v, deps=deps)
    toks += [f"[metric:render_delay/ping_fit@dev3#{k}={x}]" for k, x in v.items()]
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
    ap.add_argument("--summary", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="record the stored reports in the metrics ledger; print the citation tokens")
    args = ap.parse_args(argv)
    try:
        os.nice(19)
    except (AttributeError, OSError):
        pass
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in args.sessions:
        if sid.startswith(HELD_OUT) or sid not in MATCHES:
            print(f"{sid}: held out or not a development match; refused")
            continue
        rep = measure(sid)
        p = OUT / f"{sid}.json"
        p.write_text(json.dumps(rep, indent=1, default=_default), encoding="utf-8")
        print(p)
    if args.summary:
        p = OUT / "summary.json"
        p.write_text(json.dumps(summary(), indent=1, default=_default), encoding="utf-8")
        print(p)
    if args.record:
        print("\n".join(record_ledger()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
