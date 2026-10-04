r"""Ultimate voice lines against each round's buy phase and barrier drop.

    .\.venv\Scripts\python.exe prototypes\ult_phase_audit.py --precision [--json OUT]
    .\.venv\Scripts\python.exe prototypes\ult_phase_audit.py --lines --window-s W [--json OUT] [--record]

A one-off audit (task ult-buyphase-measure-20261004). It reads stored data
only and decodes nothing: the `ult_cast` rows (ult-cast-0.4.0) and their
`ult_line` peaks (ult-line-0.2.0), the rounds table, the HUD table, the tray's
X casts as `adjudication.ult_cast.player_x_drops` judges them, the stored death
verdicts and Riot's match records.

**The drop.** `gametime.build_session_gametime` owns the barrier drop of each
round (`t_live_ms`) [domain:rounds/buy-phase-barriers]: the first HUD clock read
above 45 s, minus the time the clock has run. `--precision` measures how well
that instant is known, two ways, before any line is looked at:

* the HUD's own spread: every live clock read in the first 20 s after the drop
  implies a drop, `t - (100 s - clock)`; the spread of those values per round
  bounds the clock's quantisation and sampling;
* Riot's round zero: a Riot kill's `gameTime - roundTime`, carried into capture
  time by the killfeed alignment (`riot_ground_truth.fit_alignment`), whose
  residual it inherits.

**Phases.** A line's phase is read from the drop alone: `buy` when its onset
lies more than W before the round's drop and after the round's start (the
buy-phase snap), `at_drop` within W of the drop either side, `live` later.
A line in the previous round's post-round period belongs to that round
[domain:rounds/post-round-period] and is `live` there. W is fixed by
`--precision` before `--lines` runs.

Per agent it counts cast rows (and burst or impossible refusals apart) by
phase. For the player's own agent it pairs each own line with the tray's X
cast (`tray_witness`) and reports where each lies. For Chamber it reads every
stored Chamber line beside Riot's per-match count and the Tour De Force kill
rounds, and classes each line from stored evidence. It decides nothing that an
owner decides; any rule it supports goes into `adjudication.ult_cast`.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import riot_ground_truth as rgt  # noqa: E402
from reticle import gametime, stalls  # noqa: E402
from reticle.store import Store  # noqa: E402

AUDIT_VERSION = "ult-phase-audit-0.1.0"
#: Live clock reads this long after the drop imply the drop (`--precision`).
SPREAD_SPAN_MS = 20_000.0


def _date(man: dict) -> str:
    return man["ingested_at"][:10]


def sessions(store: Store) -> list[str]:
    """The match sessions with a Riot record and a stored ult_cast stream."""
    recs = rgt.riot_records(store.root)
    out = []
    for sid in sorted(recs):
        p = Path(store.root) / "events" / "ult_cast" / f"{sid}.jsonl"
        if p.is_file():
            out.append(sid)
    return out


def schedules(store: Store, sid: str):
    """(rounds, gametime schedules, hud table) for one session, from the owner."""
    man = store.read_manifest(sid)
    rounds = store.read_rounds(sid, _date(man)).to_pylist()
    hud = store.read_hud(sid, _date(man))
    gt = gametime.build_session_gametime(sid, hud, rounds,
                                         stall_list=stalls.for_session(store, sid, _date(man)))
    return rounds, gt.schedules, hud, man


def riot_alignment(store: Store, sid: str, d: dict) -> tuple[float | None, dict]:
    """(a_ms, {riot round index: Riot round zero in capture ms})."""
    deaths = rgt.stored_deaths(store.root, sid)
    if not deaths:
        return None, {}
    kill_like, _ = rgt.split_deaths(deaths)
    kills = sorted(d["match"]["kills"], key=lambda k: k["gameTime"])
    al = rgt.fit_alignment([k["gameTime"] for k in kills], [float(r["t_ms"]) for r in kill_like])
    if not al:
        return None, {}
    a = al["a_ms"]
    zero = {}
    for k in kills:
        zero.setdefault(k["round"], a + k["gameTime"] - k["roundTime"])
    return a, zero


def precision(store: Store, sids: list[str]) -> dict:
    recs = rgt.riot_records(store.root)
    spread, riot_dt, cadence, first_read, sources = [], [], [], [], Counter()
    riot_latest = []
    per = {}
    for sid in sids:
        rounds, sch, hud, man = schedules(store, sid)
        t = np.asarray(hud.column("t_ms").to_numpy(zero_copy_only=False), float)
        c = np.asarray([np.nan if x is None else x for x in hud.column("clock_ms").to_pylist()],
                       float)
        cadence.append(float(np.median(np.diff(t))))
        a, zero = riot_alignment(store, sid, recs[sid])
        rows = []
        for s in sch:
            m = (t >= s.t_live_ms) & (t < s.t_live_ms + SPREAD_SPAN_MS) & (c > 45_000)
            implied = t[m] - (gametime.ROUND_LIVE_CLOCK_MS - c[m])
            src = "live_clock" if m.any() else "other"
            sources[src] += 1
            row = {"round": s.round_no, "t_live_ms": s.t_live_ms,
                   "buy_s": round((s.t_live_ms - s.t_start_ms) / 1000.0, 2)}
            if implied.size >= 2:
                row["implied_min_ms"] = float(implied.min() - s.t_live_ms)
                row["implied_max_ms"] = float(implied.max() - s.t_live_ms)
                spread.append(float(implied.max() - implied.min()))
                first_read.append(float(t[m][0] - s.t_live_ms))
            if zero:
                near = [z for z in zero.values() if abs(z - s.t_live_ms) < 10_000]
                if near:
                    dz = min(near, key=lambda z: abs(z - s.t_live_ms)) - s.t_live_ms
                    row["riot_zero_minus_drop_ms"] = round(dz)
                    riot_dt.append(dz)
                    if "implied_max_ms" in row and abs(dz - row["implied_max_ms"]) < 5000:
                        riot_latest.append(dz - row["implied_max_ms"])
            rows.append(row)
        per[sid] = {"capture": man["source"]["path"], "a_ms": a, "rounds": rows}
        print(f"{sid}: {len(rows)} rounds, cadence {cadence[-1]:.0f} ms, "
              f"capture {man['source']['path']}", flush=True)

    def q(x):
        x = np.asarray(x, float)
        if not x.size:
            return None
        return {k: round(float(v), 1) for k, v in zip(
            ("min", "p05", "p25", "median", "p75", "p95", "max"),
            np.quantile(x, [0, .05, .25, .5, .75, .95, 1]))} | {"n": int(x.size)}

    out = {"hud_cadence_ms": q(cadence), "implied_spread_ms": q(spread),
           "first_live_read_after_drop_ms": q(first_read),
           "riot_zero_minus_drop_ms": q(riot_dt),
           "riot_zero_minus_latest_implied_ms": q(riot_latest),
           "drop_sources": dict(sources), "sessions": per}
    print(json.dumps({k: v for k, v in out.items() if k != "sessions"}, indent=1))
    return out


def phase_of(t_ms: float, s, w_ms: float) -> str:
    """`buy`, `at_drop` or `live` for an instant inside round schedule `s`."""
    if abs(t_ms - s.t_live_ms) <= w_ms:
        return "at_drop"
    return "buy" if t_ms < s.t_live_ms else "live"


def _row_agent(r: dict) -> str | None:
    return r.get("agent") or r.get("template_agent") or r["template"].rsplit("_ult_", 1)[0]


def session_lines(store: Store, sid: str, d: dict, ident: dict, ref, w_ms: float,
                  tray: bool = True) -> dict:
    """Every stored ult_cast row of one session with its phase, and the
    session's Riot players, Tour De Force rounds and X drops."""
    from reticle.adjudication.ult_cast import player_agent, round_of
    from reticle.lineup import load_lineup
    rounds, sch, hud, man = schedules(store, sid)
    by_no = {s.round_no: s for s in sch}
    rows = list(rgt._stream_rows(Path(store.root) / "events" / "ult_cast" / f"{sid}.jsonl"))
    cov = next(r for r in rows if r.get("kind") == "coverage")
    a, _zero = riot_alignment(store, sid, d)
    players = rgt.riot_ult_players(d, ident["subject"], ref) if ident.get("subject") else []
    out_rows = []
    for r in rows:
        if r.get("kind") not in ("cast", "refusal"):
            continue
        rnd = r.get("round")
        s = by_no.get(rnd)
        x = {"t_ms": r["t_ms"], "template": r["template"], "agent": _row_agent(r),
             "variant": r["variant"], "kind": r["kind"], "class": r["class"],
             "score": r["score"], "round": rnd, "reason": r.get("reason"),
             "selected_by": r.get("selected_by"), "witness": r.get("witness"),
             "tray_witness": r.get("tray_witness"), "tray_refused": r.get("tray_refused")}
        if s is None:
            x["phase"], x["dt_drop_s"] = "outside", None
        else:
            x["phase"] = phase_of(r["t_ms"], s, w_ms)
            x["dt_drop_s"] = round((r["t_ms"] - s.t_live_ms) / 1000.0, 2)
            x["dt_start_s"] = round((r["t_ms"] - s.t_start_ms) / 1000.0, 2)
        out_rows.append(x)
    # Riot ult kills in capture time, with their round and the drop.
    kills = []
    if a is not None:
        for p in players:
            for k in p["ult_kills"]:
                t = a + k["game_ms"]
                rnd = round_of(t, rounds)
                s = by_no.get(rnd)
                kills.append({"agent": p["agent"], "side": p["side"], "kind": k["kind"],
                              "t_ms": t, "round": rnd, "kills": k["kills"],
                              "dt_drop_s": None if s is None else round((t - s.t_live_ms) / 1000.0, 2)})
    xd = []
    if tray:
        from reticle.cli import _ult_tray_drops
        lineup = load_lineup(sid, store.root)
        drops, why, _st = _ult_tray_drops(store, sid, _date(man), rounds, player_agent(lineup, sid))
        for c in drops or ():
            rnd = round_of(float(c["t_ms"]), rounds)
            s = by_no.get(rnd)
            xd.append({"t_ms": float(c["t_ms"]), "player_cast": c["player_cast"],
                       "reason": c.get("reason"), "round": rnd,
                       **{k: c.get(k) for k in ("from", "to", "suspect", "forced", "cooccur",
                                                 "across_gap")},
                       "phase": "outside" if s is None else phase_of(float(c["t_ms"]), s, w_ms),
                       "dt_drop_s": None if s is None else
                       round((float(c["t_ms"]) - s.t_live_ms) / 1000.0, 2)})
    return {"session": sid, "capture": man["source"]["path"], "a_ms": a,
            "player_agent": cov.get("player_agent"), "vo_heard": (cov.get("vo_heard") or {}).get("heard"),
            "rows": out_rows, "players": [{k: p[k] for k in ("agent", "side", "me", "riot_casts")}
                                          for p in players],
            "ult_kills": kills, "x_drops": xd,
            "drops": {s.round_no: s.t_live_ms for s in sch}}


def summarise(res: list[dict], w_s: float) -> dict:
    """Per agent: cast rows by phase, refusals by phase, own lines against the
    tray, Riot counts against stored rows with and without the buy phase."""
    agents = defaultdict(lambda: {"cast": Counter(), "refusal": Counter(), "class_cast": Counter(),
                                  "buy_rows": [], "own": Counter(), "riot": 0, "stored": 0,
                                  "stored_no_buy": 0, "abs_all": 0, "abs_no_buy": 0,
                                  "players": 0, "ult_kill_dt": [], "at_drop_dt": []})
    for s in res:
        for r in s["rows"]:
            A = agents[r["agent"]]
            A[r["kind"]][r["phase"]] += 1
            if r["kind"] == "cast":
                A["class_cast"][r["class"]] += 1
                if r["phase"] == "at_drop":
                    A["at_drop_dt"].append(r["dt_drop_s"])
                if r["phase"] == "buy":
                    A["buy_rows"].append({"session": s["session"], "capture": s["capture"],
                                          **{k: r[k] for k in ("t_ms", "template", "class", "score",
                                                               "round", "dt_drop_s", "dt_start_s",
                                                               "selected_by", "tray_witness")}})
                if r["class"] == "own":
                    tw = r.get("tray_witness")
                    A["own"][f"line_{r['phase']}" + ("_tray" if tw else "_notray")] += 1
        for p in s["players"]:
            A = agents[p["agent"]]
            mine = [r for r in s["rows"] if r["kind"] == "cast" and r["agent"] == p["agent"]
                    and r["variant"] == p["side"]]
            nb = [r for r in mine if r["phase"] != "buy"]
            A["players"] += 1
            A["riot"] += p["riot_casts"]
            A["stored"] += len(mine)
            A["stored_no_buy"] += len(nb)
            A["abs_all"] += abs(len(mine) - p["riot_casts"])
            A["abs_no_buy"] += abs(len(nb) - p["riot_casts"])
        for k in s["ult_kills"]:
            if k["dt_drop_s"] is not None:
                agents[k["agent"]]["ult_kill_dt"].append(k["dt_drop_s"])
    out = {}
    for a, A in sorted(agents.items(), key=lambda x: str(x[0])):
        kd = sorted(A["ult_kill_dt"])
        out[a] = {"cast": dict(A["cast"]), "refusal": dict(A["refusal"]),
                  "class_cast": dict(A["class_cast"]), "own": dict(A["own"]),
                  "riot_players": A["players"], "riot_casts": A["riot"], "stored": A["stored"],
                  "stored_no_buy": A["stored_no_buy"], "abs_err_all": A["abs_all"],
                  "abs_err_no_buy": A["abs_no_buy"],
                  "ult_kills": len(kd), "ult_kills_within_10s_of_drop": sum(x <= 10 for x in kd),
                  "first_ult_kill_dt_s": kd[:3],
                  "at_drop_dt_s": sorted(A["at_drop_dt"]), "buy_rows": A["buy_rows"]}
    return out


def tray_phase(res: list[dict]) -> dict:
    """The player's X drops by phase and verdict, and each buy or at-drop
    accepted cast beside its nearest own line."""
    c, detail = Counter(), []
    for s in res:
        own = [r for r in s["rows"] if r["kind"] == "cast" and r["class"] == "own"]
        for x in s["x_drops"]:
            c[f"{x['phase']}_{'cast' if x['player_cast'] else 'refused'}"] += 1
            if x["phase"] in ("buy", "at_drop"):
                near = min(own, key=lambda r: abs(r["t_ms"] - x["t_ms"]), default=None)
                detail.append({"session": s["session"], "capture": s["capture"],
                               "agent": s["player_agent"], **x,
                               "nearest_own_dt_s": None if near is None else
                               round((near["t_ms"] - x["t_ms"]) / 1000.0, 2),
                               "nearest_own_phase": None if near is None else near["phase"]})
    return {"x_drops_by_phase": dict(sorted(c.items())), "buy_and_drop_x": detail}


def chamber(res: list[dict]) -> list[dict]:
    """Every stored Chamber row with the evidence that classes it."""
    out = []
    for s in res:
        ch = [p for p in s["players"] if p["agent"] == "Chamber"]
        for p in ch:
            side = p["side"]
            rows = sorted((r for r in s["rows"] if r["agent"] == "Chamber" and r["variant"] == side),
                          key=lambda r: r["t_ms"])
            tdf = sorted({k["round"] for k in s["ult_kills"] if k["agent"] == "Chamber"
                          and k["side"] == side and k["kind"] == "Tour De Force"} - {None})
            first_kill = {}
            for k in s["ult_kills"]:
                if k["agent"] == "Chamber" and k["side"] == side and k["kind"] == "Tour De Force":
                    first_kill[k["round"]] = min(first_kill.get(k["round"], 1e18), k["t_ms"])
            others = [r for r in s["rows"] if r["agent"] != "Chamber"]
            prev = None
            lines = []
            for r in rows:
                near = [o for o in others if abs(o["t_ms"] - r["t_ms"]) <= 2000]
                lines.append({**{k: r[k] for k in ("t_ms", "kind", "class", "score", "round",
                                                   "phase", "dt_drop_s", "reason", "selected_by")},
                              "since_prev_s": None if prev is None else
                              round((r["t_ms"] - prev["t_ms"]) / 1000.0, 2),
                              "prev_round": None if prev is None else prev["round"],
                              "tdf_kill_round": r["round"] in tdf,
                              "kill_after_s": None if r["round"] not in first_kill else
                              round((first_kill[r["round"]] - r["t_ms"]) / 1000.0, 2),
                              "co_fired": [(o["template"], o["score"], o["kind"]) for o in near]})
                if r["kind"] == "cast":
                    prev = r
            cast_rounds = {r["round"] for r in rows if r["kind"] == "cast"}
            out.append({"session": s["session"], "capture": s["capture"], "side": side,
                        "riot_casts": p["riot_casts"], "tdf_rounds": tdf,
                        "tdf_rounds_without_line": [x for x in tdf if x not in cast_rounds],
                        "casts": sum(r["kind"] == "cast" for r in rows),
                        "casts_by_phase": dict(Counter(r["phase"] for r in rows
                                                       if r["kind"] == "cast")),
                        "lines": lines})
    return out


def record_phase_metrics(prec: dict, res: list[dict], C: list[dict], w_s: float) -> list[str]:
    """Append the precision run and the per-agent phase counts to the metrics
    log, as `ult_phase/precision` and `ult_phase/agents` on all matches."""
    from scipy.stats import fisher_exact

    from reticle import metrics
    from reticle.version import ULT_CAST_VERSION, ULT_LINE_VERSION
    sids = [s["session"] for s in res]
    deps = {"audit": AUDIT_VERSION, "ult_cast_version": ULT_CAST_VERSION,
            "ult_line_version": ULT_LINE_VERSION, "gametime": gametime.GAMETIME_VERSION}
    pv = {"rounds": prec["implied_spread_ms"]["n"],
          "hud_cadence_ms": prec["hud_cadence_ms"]["median"],
          "implied_spread_ms_median": prec["implied_spread_ms"]["median"],
          "implied_spread_ms_p95": prec["implied_spread_ms"]["p95"],
          "window_s": w_s}
    for k in ("riot_zero_minus_drop_ms", "riot_zero_minus_latest_implied_ms"):
        for qn in ("p05", "median", "p95"):
            pv[f"{k}_{qn}"] = prec[k][qn]
    metrics.record("ult_phase", part="precision", session="all-matches", values=pv, deps=deps,
                   context={"session_ids": sids})
    tab = defaultdict(Counter)
    for s in res:
        for r in s["rows"]:
            if r["kind"] == "cast":
                tab[(r["agent"], r["variant"])][r["phase"]] += 1
    av = {}
    named = ("Chamber", "Jett", "Reyna", "Phoenix", "Skye", "Iso")
    for (a, v), c in tab.items():
        if a in named:
            for ph in ("buy", "at_drop", "live", "outside"):
                av[f"{a}_{v}_{ph}"] = c.get(ph, 0)
    other = Counter()
    for (a, v), c in tab.items():
        if a not in ("Chamber", "Jett", "Reyna"):
            other.update(c)
    for ph in ("buy", "at_drop", "live", "outside"):
        av[f"others_{ph}"] = other.get(ph, 0)
    ca, ce = tab[("Chamber", "ally")], tab[("Chamber", "enemy")]
    av["chamber_variant_fisher_p"] = round(float(fisher_exact(
        [[ca["buy"], ca["at_drop"]], [ce["buy"], ce["at_drop"]]])[1]), 6)
    av["chamber_players"] = len(C)
    av["chamber_riot_casts"] = sum(p["riot_casts"] for p in C)
    av["chamber_lines"] = sum(p["casts"] for p in C)
    av["chamber_tdf_rounds"] = sum(len(p["tdf_rounds"]) for p in C)
    av["chamber_tdf_rounds_without_line"] = sum(len(p["tdf_rounds_without_line"]) for p in C)
    av["chamber_players_riot_below_tdf_rounds"] = sum(p["riot_casts"] < len(p["tdf_rounds"])
                                                      for p in C)
    av["chamber_players_riot_above_lines"] = sum(p["riot_casts"] > p["casts"] for p in C)
    av["chamber_lines_outside_tdf_rounds"] = sum(
        ln["kind"] == "cast" and not ln["tdf_kill_round"] for p in C for ln in p["lines"])
    av["chamber_rounds_with_two_lines"] = sum(
        n > 1 for p in C for n in Counter(ln["round"] for ln in p["lines"]
                                          if ln["kind"] == "cast").values())
    xs = [x for s in res for x in s["x_drops"] if x["phase"] == "buy"]
    av["x_drops_buy"] = len(xs)
    av["x_drops_buy_forced_cooccur"] = sum(bool(x["forced"] and x["cooccur"]) for x in xs)
    av["x_drops_buy_cast"] = sum(bool(x["player_cast"]) for x in xs)
    own = [r for s in res for r in s["rows"] if r["kind"] == "cast" and r["class"] == "own"]
    for ph in ("buy", "at_drop", "live"):
        av[f"own_{ph}"] = sum(r["phase"] == ph for r in own)
    metrics.record("ult_phase", part="agents", session="all-matches", values=av, deps=deps,
                   context={"session_ids": sids, "window_s": w_s})
    return [f"recorded ult_phase/precision: {pv}", f"recorded ult_phase/agents: {av}"]


def _below_normal() -> None:
    with contextlib.suppress(Exception):
        rgt._below_normal()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(rgt.STORE))
    ap.add_argument("--precision", action="store_true")
    ap.add_argument("--lines", action="store_true")
    ap.add_argument("--window-s", type=float, default=None)
    ap.add_argument("--json", default=None)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--half", choices=("dev", "held", "all"), default="all",
                    help="the declared dev or held half of the Riot sessions (ULT_DEV_SESSIONS)")
    ap.add_argument("--no-tray", action="store_true", help="skip the tray's X drops")
    args = ap.parse_args(argv)
    _below_normal()
    store = Store(Path(args.store))
    sids = sessions(store)
    print(f"{len(sids)} sessions: {' '.join(sids)}")
    if args.half != "all":
        sids = [s for s in sids if (s in rgt.ULT_DEV_SESSIONS) == (args.half == "dev")]
        print(f"half {args.half}: {len(sids)} sessions")
    if args.record and not (args.precision and args.lines and args.half == "all"):
        ap.error("--record needs --precision --lines on all matches")
    prec = None
    if args.precision:
        prec = precision(store, sids)
        if args.json and not args.lines:
            Path(args.json).write_text(json.dumps(prec, indent=1, default=str), encoding="utf-8")
    if args.lines:
        if args.window_s is None:
            ap.error("--lines needs --window-s, fixed by --precision")
        recs = rgt.riot_records(store.root)
        idents = rgt.identify_player(recs, store.root)
        ref = rgt.Reference(Path(args.store) / "external" / "valorant-api", fetch=False)
        res = []
        for sid in sids:
            ident = rgt.resolve_lineup_player(recs[sid], idents[sid], ref)
            with contextlib.redirect_stdout(io.StringIO()):
                res.append(session_lines(store, sid, recs[sid], ident, ref,
                                         args.window_s * 1000.0, tray=not args.no_tray))
            print(f"{sid}: {len(res[-1]['rows'])} rows, player {res[-1]['player_agent']}, "
                  f"capture {res[-1]['capture']}", flush=True)
        S = summarise(res, args.window_s)
        T = tray_phase(res)
        C = chamber(res)
        print(f"\nW = {args.window_s} s; phase counts of cast rows (refusals) per agent")
        print(f"{'agent':10s} {'buy':>4s} {'drop':>4s} {'live':>5s} {'out':>4s} | "
              f"{'r.buy':>5s} {'r.drop':>6s} {'r.live':>6s} | riot stored nobuy |err| |err|nb "
              f"kills k<=10s")
        for a, v in S.items():
            c, r = v["cast"], v["refusal"]
            print(f"{str(a):10s} {c.get('buy', 0):4d} {c.get('at_drop', 0):4d} "
                  f"{c.get('live', 0):5d} {c.get('outside', 0):4d} | {r.get('buy', 0):5d} "
                  f"{r.get('at_drop', 0):6d} {r.get('live', 0):6d} | {v['riot_casts']:4d} "
                  f"{v['stored']:6d} {v['stored_no_buy']:5d} {v['abs_err_all']:5d} "
                  f"{v['abs_err_no_buy']:6d} {v['ult_kills']:5d} "
                  f"{v['ult_kills_within_10s_of_drop']:5d}")
        print("\nbuy-phase cast rows:")
        for a, v in S.items():
            for b in v["buy_rows"]:
                print(f"  {a:10s} {b['session']} r{b['round']} t={b['t_ms'] / 1000:.2f}s "
                      f"drop{b['dt_drop_s']:+.2f}s start{b['dt_start_s']:+.2f}s {b['template']} "
                      f"{b['class']} {b['score']:.4f} by {b['selected_by']} tray {b['tray_witness']}")
        print("\nat-drop cast rows, onset minus drop (s):")
        for a, v in S.items():
            if v["at_drop_dt_s"]:
                print(f"  {a:10s} {v['at_drop_dt_s']}")
        print("\nown lines by phase and tray witness:")
        for a, v in S.items():
            if v["own"]:
                print(f"  {a:10s} {v['own']}")
        print("\nX drops by phase:", T["x_drops_by_phase"])
        for x in T["buy_and_drop_x"]:
            print(f"  {x['session']} {x['agent']} r{x['round']} drop{x['dt_drop_s']:+.2f}s "
                  f"{x['phase']} cast={x['player_cast']} reason={x['reason']} "
                  f"fill {x['from']}->{x['to']} cooccur={x['cooccur']} forced={x['forced']} "
                  f"own line {x['nearest_own_dt_s']} s after ({x['nearest_own_phase']})")
        print("\nChamber players:")
        for p in C:
            print(f"  {p['session']} {p['side']:5s} riot {p['riot_casts']} casts {p['casts']} "
                  f"{p['casts_by_phase']} tdf rounds {p['tdf_rounds']} "
                  f"without line {p['tdf_rounds_without_line']}")
            for ln in p["lines"]:
                print(f"     r{ln['round']} {ln['kind']:7s} {ln['phase']:7s} "
                      f"drop{(ln['dt_drop_s'] if ln['dt_drop_s'] is not None else float('nan')):+7.2f}s "
                      f"{ln['score']:.4f} {ln['class']:8s} by={ln['selected_by']} "
                      f"prev={ln['since_prev_s']}s(r{ln['prev_round']}) tdf={ln['tdf_kill_round']} "
                      f"kill_after={ln['kill_after_s']} reason={ln['reason']} co={ln['co_fired']}")
        if args.json:
            Path(args.json).write_text(json.dumps({"window_s": args.window_s, "half": args.half,
                                                   "agents": S, "tray": T, "chamber": C,
                                                   "sessions": res}, indent=1, default=str),
                                       encoding="utf-8")
        if args.record:
            for line in record_phase_metrics(prec, res, C, args.window_s):
                print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
