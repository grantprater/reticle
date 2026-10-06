"""Sanity report over stored truth episodes (docs/EPISODES.md, "Sanity run").

Reads `<store>/analysis/episodes/truth/*.jsonl` and the replay layers they
rest on; decodes nothing. The held-out match (`replay_layer.HELD_OUT`) is
skipped before any row is read. With `--record` it appends the pooled and
per-match figures to the metrics ledger under `episodes/sanity`.

    .\\.venv\\Scripts\\python.exe tools\\episodes_sanity.py [--record] [--episodes-root DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import episodes as ep  # noqa: E402
from reticle.replay_layer import is_held_out, load  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

KINDS = ("phase_buy", "phase_live", "phase_post_plant", "phase_round_over", "duel",
         "remote_damage", "engagement", "trade", "execute", "lurk", "retake",
         "contested_plant", "rotation")


def pct(x, q=(10, 50, 90)):
    a = np.asarray([v for v in x if v is not None and np.isfinite(v)], float)
    return None if a.size == 0 else [round(float(v), 2) for v in np.percentile(a, q)]


def share(k, n):
    return None if n == 0 else round(k / n, 4)


def riot_rounds(session: str | None, root: Path) -> list[dict] | None:
    if not session:
        return None
    from reticle.replay_source import riot_records
    rec = riot_records(root).get(session)
    return None if rec is None else rec["match"].get("roundResults")


RIOT_REASON = {"Elimination": "elimination", "Defuse": "defuse", "Detonate": "detonation",
               "": "time"}


def act_summary(acts, kill_acts, act_counts, sak, ex_all, R) -> dict:
    """Kill classes, sight per class, what wallbang lines cross, and the
    graded executes [domain:weapons/kill-line-of-sight],
    [domain:rounds/execute-is-a-site-attempt]."""
    nk = len(kill_acts)
    kc = Counter(a["class"] for a in kill_acts)
    out = {"kill_class_share": {k: share(v, nk) for k, v in sorted(kc.items())},
           "kill_class_n": dict(kc), "act_counts": dict(act_counts)}
    out["sight_at_kill_by_class"] = {k: share(c[True], c[True] + c[False]) for k, c in sorted(sak.items(), key=str)
                                     if k is not None}
    out["sight_at_kill_n_by_class"] = {str(k): c[True] + c[False] for k, c in sak.items()}
    wb = [a for a in acts if a["class"] == "gun_wallbang" and a.get("geometry")]
    n = len(wb)
    pl = Counter(min(a["geometry"]["placements"], 4) for a in wb)
    so = Counter(min(a["geometry"]["solids"], 4) for a in wb)
    out["wallbang_lines"] = {"n": n, **{f"placements_{k}{'+' if k == 4 else ''}": share(v, n) for k, v in sorted(pl.items())},
                             **{f"solids_{k}{'+' if k == 4 else ''}": share(v, n) for k, v in sorted(so.items())},
                             "impenetrable": share(sum(a["geometry"]["impenetrable"] for a in wb), n),
                             "unread": share(sum(a["geometry"]["unread"] for a in wb), n),
                             "clear_line": share(sum(1 for a in wb if a["line_clear"]), n)}
    read = [a for a in wb if not a["geometry"]["unread"]]
    out["wallbang_lines"]["placements_read_only_1"] = share(sum(1 for a in read if a["geometry"]["placements"] == 1), len(read))
    out["wallbang_classes"] = dict(Counter(c for a in wb for c in a["geometry"]["classes"]))
    out["wallbang_impenetrable_list"] = [
        {k: a[k] for k in ("match", "event_id", "t_ms", "actor", "target", "equippable")}
        | {"meshes": a["geometry"]["meshes"], "classes": a["geometry"]["classes"]}
        for a in wb if a["geometry"]["impenetrable"]]
    gun = sum(act_counts.get(k, 0) for k in ("gun_sight", "gun_wallbang", "gun_blocked"))
    gb = [a for a in acts if a["class"] == "gun_blocked"]
    out["gun_blocked"] = {"n": len(gb), "share_of_gun_acts": share(act_counts.get("gun_blocked", 0), gun),
                          "impenetrable": sum(1 for a in gb if a.get("geometry") and a["geometry"]["impenetrable"]),
                          "list": [{k: a[k] for k in ("match", "event_id", "t_ms", "actor", "target", "equippable")}
                                   | {"meshes": (a.get("geometry") or {}).get("meshes")} for a in gb]}
    ne = len(ex_all)
    res = Counter(e["outcome"]["result"] for e in ex_all)
    com = Counter(e["commitment"]["committed"] for e in ex_all)
    out["execute_attempts"] = {"per_round": round(ne / R, 3) if R else None,
                               "rounds_with": share(len({(e["match"], e["round"]) for e in ex_all}), R),
                               **{f"result_{k}": share(v, ne) for k, v in sorted(res.items())},
                               **{f"committed_{k}": share(v, ne) for k, v in sorted(com.items())},
                               "trigger_plant": share(sum(1 for e in ex_all if e["trigger"] == "plant"), ne)}
    sh = [e["commitment"]["share"] for e in ex_all if e["commitment"]["share"] is not None]
    out["execute_attempts"]["share_p50"] = round(float(np.median(sh)), 3) if sh else None
    out["execute_by_commitment"] = {str(k): dict(Counter(e["outcome"]["result"] for e in ex_all
                                                         if e["commitment"]["committed"] == k))
                                    for k in sorted(com)}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", type=Path, default=DEFAULT_STORE)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--episodes-root", type=Path, default=None,
                    help="read the episodes under this root (a branch's scratch store)")
    a = ap.parse_args(argv)
    root = a.store
    eroot = a.episodes_root or root
    files = sorted(ep.episodes_dir("truth", eroot).glob("*.jsonl"))
    per, pooled = {}, defaultdict(list)
    tot = Counter()
    lag = defaultdict(list)
    riot_cmp = {}
    acts_all, kill_acts, ex_all = [], [], []
    act_counts = Counter()
    sak = defaultdict(Counter)
    for f in files:
        m = f.stem
        if is_held_out(m):
            continue
        rows = ep.read_episodes(m, "truth", eroot)
        head = rows[0]
        eps = [r for r in rows if r["row"] == "episode"]
        con = [r for r in rows if r["row"] == "contact"]
        una = [r for r in rows if r["row"] == "unassigned_death"]
        notes = [r for r in rows if r["row"] == "note"]
        L = load(m, root)
        n_kills = int((L.events["kind"] == "kill").sum())
        n_rounds = int(L.rounds["round"].size)
        c = Counter(r["kind"] for r in eps)
        duels = [r for r in eps if r["kind"] == "duel"]
        kd = [r for r in duels if r["outcome"]["result"] == "killed"]
        eng = [r for r in eps if r["kind"] == "engagement"]
        in_eng = Counter(k for e in eng for k in e["kill_events"])
        phases = [r for r in eps if r["kind"] in ("phase_live", "phase_post_plant")
                  and r.get("outcome")]
        for r in phases:
            o = r["outcome"]
            if o.get("end_lag_ms") is not None:
                lag[o["end_reason"]].append(o["end_lag_ms"])
        side_notes = Counter(n["kind"] for n in notes)
        acts = [dict(r, match=m) for r in rows if r["row"] == "act"]
        acts_all += [a for a in acts if a["act"] == "damage"]
        kill_acts += [a for a in acts if a["act"] == "death"]
        act_counts.update(head.get("act_counts") or {})
        for r in kd:
            sak[r.get("kill_class")][bool(r["sight_at_kill"])] += 1
        ex_all += [dict(r, match=m) for r in eps if r["kind"] == "execute"]
        per[m] = {
            "map": head["map"].rsplit("/", 1)[-1], "session": head["stamps"].get("session"),
            "rounds": n_rounds, "kills": n_kills, "counts": {k: c.get(k, 0) for k in KINDS},
            "contacts": len(con), "unassigned": dict(Counter(u["reason"] for u in una)),
            "kills_in_one_engagement": sum(1 for v in in_eng.values() if v == 1),
            "kills_in_two_or_more": sum(1 for v in in_eng.values() if v > 1),
            "sight_at_kill": share(sum(1 for r in kd if r["sight_at_kill"]), len(kd)),
            "mutual_kill_duels": share(sum(1 for r in kd if r["mutual"]), len(kd)),
            "traded_share": share(c.get("trade", 0), len(kd)),
            "side_notes": dict(side_notes),
            "kill_classes": dict(Counter(a["class"] for a in acts if a["act"] == "death")),
        }
        tot.update(c)
        tot["rounds"] += n_rounds
        tot["kills"] += n_kills
        tot["kill_duels"] += len(kd)
        tot["sight_at_kill"] += sum(1 for r in kd if r["sight_at_kill"])
        tot["mutual"] += sum(1 for r in kd if r["mutual"])
        tot["contacts"] += len(con)
        tot["unassigned"] += len(una)
        tot["kills_in_one_engagement"] += per[m]["kills_in_one_engagement"]
        tot["eng_3plus"] += sum(1 for e in eng if len(e["participants"]["combatants"]) >= 3)
        tot["same_engagement"] += sum(1 for r in eps if r["kind"] == "trade" and r["same_engagement"])
        tot["executes_planted"] += sum(1 for r in eps if r["kind"] == "execute"
                                       and r["outcome"]["result"] == "planted")
        tot["plants"] += sum(1 for r in eps if r["kind"] == "phase_post_plant")
        tot["rounds_with_execute"] += len({r["round"] for r in eps if r["kind"] == "execute"})
        for k in KINDS:
            pooled[k] += [(r["t_end_ms"] - r["t_start_ms"]) / 1000.0 for r in eps
                          if r["kind"] == k and r["t_end_ms"] is not None]
        pooled["contact"] += [(r["t_end_ms"] - r["t_start_ms"]) / 1000.0 for r in con]
        rr = riot_rounds(head["stamps"].get("session"), root)
        if rr:
            ok_reason = ok_win = n = 0
            mine = {r["round"]: r["outcome"] for r in phases}
            for x in rr:
                o = mine.get(int(x["roundNum"]) + 1)
                if o is None or x.get("roundResultCode") == "Surrendered":
                    continue
                n += 1
                ok_reason += o["end_reason"] == RIOT_REASON.get(x.get("roundResultCode"), "?")
                ok_win += o["winner"] == x.get("winningTeam")
            riot_cmp[m] = {"rounds": n, "end_reason_agree": ok_reason, "winner_agree": ok_win}
    R = tot["rounds"]
    pooled_out = {
        "matches": len(per), "rounds": R, "kills": tot["kills"],
        "per_round": {k: round(tot[k] / R, 3) for k in KINDS},
        "contacts_per_round": round(tot["contacts"] / R, 2),
        "sight_at_kill": share(tot["sight_at_kill"], tot["kill_duels"]),
        "mutual_kill_duels": share(tot["mutual"], tot["kill_duels"]),
        "duel_kill_share": share(tot["kill_duels"], tot["duel"]),
        "traded_share": share(tot["trade"], tot["kill_duels"]),
        "same_engagement_trades": share(tot["same_engagement"], tot["trade"]),
        "unassigned_share": share(tot["unassigned"], tot["kills"]),
        "kills_in_exactly_one_engagement": share(tot["kills_in_one_engagement"], tot["kills"]),
        "engagements_3plus": share(tot["eng_3plus"], tot["engagement"]),
        "rounds_with_execute": share(tot["rounds_with_execute"], R),
        "executes_planted": share(tot["executes_planted"], tot["execute"]),
        "retake_share_of_plants": share(tot["retake"], tot["plants"]),
        "duration_s_p10_p50_p90": {k: pct(v) for k, v in pooled.items()},
        "end_lag_ms_p50_p95": {k: pct(v, (50, 95)) for k, v in lag.items()},
        "riot_round_check": riot_cmp,
    }
    pooled_out.update(act_summary(acts_all, kill_acts, act_counts, sak, ex_all, R))
    print(json.dumps({"pooled": pooled_out, "per_match": per}, indent=1))
    if a.record:
        from reticle.metrics import record
        deps = {"episodes": ep.EPISODES_VERSION}
        flat = {k: v for k, v in pooled_out.items() if isinstance(v, (int, float)) and v is not None}
        flat.update({f"per_round.{k}": v for k, v in pooled_out["per_round"].items()})
        for k, v in pooled_out["end_lag_ms_p50_p95"].items():
            if v:
                flat[f"end_lag_ms.{k}.p50"], flat[f"end_lag_ms.{k}.p95"] = v
        for k, v in pooled_out["duration_s_p10_p50_p90"].items():
            if v:
                flat[f"dur_s.{k}.p50"] = v[1]
        for sec in ("kill_class_share", "sight_at_kill_by_class", "wallbang_lines", "execute_attempts"):
            for k, v in (pooled_out.get(sec) or {}).items():
                if isinstance(v, (int, float)) and v is not None:
                    flat[f"{sec}.{k}"] = v
        record("episodes", part="sanity/pooled", values=flat, deps=deps,
               context={"matches": sorted(per)})
        for m, p in per.items():
            vals = {"rounds": p["rounds"], "kills": p["kills"], "contacts": p["contacts"],
                    **{f"n.{k}": v for k, v in p["counts"].items()}}
            for k in ("sight_at_kill", "mutual_kill_duels", "traded_share"):
                if p[k] is not None:
                    vals[k] = p[k]
            record("episodes", part=f"sanity/{m[:8]}", values=vals, deps=deps,
                   context={"map": p["map"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
