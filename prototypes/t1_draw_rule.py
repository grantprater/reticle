r"""The minimap's enemy draw rule on replay truth, corrected: persistence, smokes, death.

Moved into the acceptance harness on 2026-10-09 (`reticle/harness/draw.py`,
task `harness-t1d-20261009`): T1d (`DrawRule`, `RealDrawMatch`, the smokes)
and `persist` and `smokes`, now `reticle acceptance draw-persist` and
`draw-smokes`. This file imports them back.

Task `t1-draw-rule-20261007` (rows TD1 in the store's
`notes/predictions.jsonl`). `coaching_questions.Match.drawn` (T1) draws an
enemy while a living capture-team player saw him within the last 1000 ms.
`enemy_lane_check` found that rule draws enemies the game does not: after
death, through smokes, and too long after the last sight. This prototype
measures the persistence and builds the corrected rule as a named option;
T1 stays the default of every `Match` and reproduces exactly.

**Persistence** (`persist`). Instances are stored `minimap_object` "?"
marks whose replaced icon sits in the read frame immediately before the
mark's first frame: the one-frame swap of [domain:minimap/last-known-mark-timing].
The enemy is the living truth enemy nearest the replaced icon (within
`NEAR_CM`, the next at least `NEAR_CM` farther). The swap's replay time is
the two frames' midpoint through `replay_truth.capture_to_replay` with the
killfeed clock and `REMOTE_LAG_MS` (replay-truth-0.4.0); the last sight is
the last instant any living capture-team player sees him (`episodes.sight`,
then the smoke filter below), refined from the 16 Hz grid to `FINE_MS`. The
persistence is swap less last sight; negative where sight outlasts the swap.

**Smokes** (`smokes`). Replay-layer children of the classes in `SMOKES`, each
a sphere at its spawn point with its own radius, delay and duration, read
from its ability's game-data fact or, where the fact is silent, the named
game file (never by analogy [domain:abilities/ability-rules-are-unique]). A
sight ray (eye to body centre, or eye to eye, as `episodes.sight` casts them)
whose segment passes within a live sphere's radius is blocked; both teams'
smokes block. `UNMODELLED` lists the vision blockers left out and why.

**Death.** A dead enemy is never drawn as an icon. `dead_mark` is its own
state: the enemy dead in the round after being drawn at his last living
sample [domain:minimap/enemy-death-mark].

**Rules** (`RULES`): `T1` (the old rule), `T1a` (alive only), `T1s` (alive,
smoke-blocked sight, P 1000 ms), `T1p` (alive, measured P, no smoke), `T1d`
(alive, smoke-blocked sight, measured P). `T1d` is the corrected rule; its P
is the median over the swaps the reader check keeps (`_clean`), and
`T1d_raw` takes the median over every swap, the registered design, which
reader misses of still-drawn icons pull down.

T1d draws enemy players only. Enemy-owned children that draw like players
follow their own facts and are scored as their own class; a find on one is
never an extra.

    python prototypes/t1_draw_rule.py smokes [MATCH ...]
    python prototypes/t1_draw_rule.py persist [SESSION ...]
    python prototypes/t1_draw_rule.py lane [SESSION ...] [--rules T1,T1a,...]
    python prototypes/t1_draw_rule.py truth [MATCH ...] [--rule T1d]
    python prototypes/t1_draw_rule.py report [--rule T1d]
    python prototypes/t1_draw_rule.py record

Stored data and replay truth only; no pixel is read. The held-out capture
(cea8ecbc94ab, replay bd7efa02) is refused by name. Outputs:
`<store>/analysis/t1-draw-rule-20261007/`. Not wired (`"wire": "no"`): an
evaluation over replay truth.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import coaching_questions as cq  # noqa: E402
import enemy_lane_check as elc  # noqa: E402
import real_reader_schedule as rrs  # noqa: E402
import replay_truth as rt  # noqa: E402
from reticle import episodes as ep  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

# Moved into the acceptance harness (`reticle/harness/draw.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.draw import (  # noqa: E402,F401
    _boot_median, _clean, _dist, _fine_last, _log, _swaps, BACK_MS, CLEAN_BACK_MS, DrawRule,
    FINE_MS, GF, LOOKBACK_MS, measured_p_ms, NEAR_CM, OUT, persist_match, RealDrawMatch, refuse,
    RENDER_BAND_MS, RENDER_PRIOR_MS, RULES, run_persist, run_smokes, seg_sphere, smoke_filter,
    smoke_table, SMOKES, STORE, SWAP_MAX_MS, TASK, UNMODELLED, VERSION)

DEV = elc.DEV


# ----------------------------------------------------------------- rules


class DrawMatch(DrawRule, cq.Match):
    pass


# ----------------------------------------------------------------- the lane population

def run_lane(sessions: list[str], rules: list[str]) -> int:
    """enemy_lane_check's population (live read frames, dev matches) under
    each rule: drawn share, pair hit rate, extras rate; old and new."""
    cq._idle()
    out = {}
    for sid in sessions:
        refuse(sid)
        M = RealDrawMatch(sid, rule="T1")
        out[sid] = {}
        for rule in rules:
            M.rule = rule
            R = elc.build_sets(sid, M=M)
            P = R["pairs"]
            nh = sum(r["set"] == "hit" for r in P)
            nm = sum(r["set"] == "miss" for r in P)
            info = R["info"]
            dm = None
            if rule != "T1":
                dmk = M.dead_mark(M.C)
                dm = round(float(dmk[M.ei].any(axis=0).mean()), 4)
            out[sid][rule] = {"drawn_share": round(info["samples"]["t1_any"], 4),
                              "drawn_share_alive": round(info["samples"]["t1_any_alive"], 4),
                              "real_share": round(info["samples"]["real_any"], 4),
                              "hits": nh, "misses": nm, "hit_rate": round(nh / max(nh + nm, 1), 4),
                              "hit_rate_ci": elc._ci(nh, nh + nm),
                              "extras": info["extras"], "icons": info["icons_valid"],
                              "extras_rate": round(info["extras"] / max(info["icons_valid"], 1), 4),
                              "dead_mark_any_share_of_grid": dm,
                              "valid_live_samples": info["samples"]["valid_live_samples"],
                              "p_ms": measured_p_ms(RULES[rule]["p_ms"]) if RULES[rule]["p_ms"] else cq.P_MS}
            _log(f"{sid} {rule}: {json.dumps(out[sid][rule])}")
    p = OUT / "lane.json"
    old = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    for sid, v in out.items():
        old.setdefault(sid, {}).update(v)
    p.write_text(json.dumps(old, indent=1), encoding="utf-8")
    return 0


# ----------------------------------------------------------------- the truth sweep

TRUTH_ARMS = ["Lp0.5-250w5", "Lp1-250w5"]


def run_truth(keys: list[str], rule: str) -> int:
    """Gate onset and the degrade sweep (TRUTH_ARMS) on the replays under
    one rule; rows appended to truth_<rule>.jsonl and gate_<rule>.jsonl."""
    cq._idle()
    OUT.mkdir(parents=True, exist_ok=True)
    for key in keys:
        if key.startswith(cq.HELD_OUT_PREFIX):
            raise SystemExit("the held-out replay is never read")
        t0 = time.time()
        M = DrawMatch(key, rule=rule)
        tl = M.tl0
        rows = ep.read_episodes(tl.match)
        eps = [r for r in rows if r.get("row") == "episode"]
        team_of = {s.slot_id: s.team for s in tl.slots}
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        go = cq.gate_onset_rows(M, key, tl, eps, team_of, idx)
        with (OUT / f"gate_{rule}.jsonl").open("a", encoding="utf-8") as f:
            for r in go:
                f.write(json.dumps(r, default=cq._jd) + "\n")
        sh = {C: float(M.drawn(C)[M.team != C].any(axis=0).mean()) for C in M.teams}
        cq.degrade_match(key, TRUTH_ARMS, OUT / f"truth_{rule}.jsonl", match_cls=lambda _k: M)
        _log(f"truth {rule} {key[:8]}: gate rows {len(go)}, drawn share {sh}, smokes {len(M.smokes)}, "
             f"{time.time() - t0:.0f} s")
    return 0


def truth_report(rule: str) -> dict:
    go = [json.loads(x) for x in (OUT / f"gate_{rule}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    rows = [json.loads(x) for x in (OUT / f"truth_{rule}.jsonl").read_text(encoding="utf-8").splitlines() if x]
    P = cq.pooled(rows)
    keep = ("opening_first_seer", "spacing_death", "spacing_5m", "first_sight_support", "duel_C", "contact_C",
            "engagement_C", "trade_C", "execute_C", "rotation_C", "lurk_C")
    arms = {a: {"share": round(P[a]["share"], 4), "frame_share": round(P[a]["frame_share"], 4),
                "vs_T1": {q: P[a]["vs_T1"][q]["agree"] for q in keep if q in P[a]["vs_T1"]},
                "vs_T0": {q: P[a]["vs_T0"][q]["agree"] for q in keep if q in P[a]["vs_T0"]}}
            for a in TRUTH_ARMS if a in P}
    t1 = {q: P["T1"]["vs_T0"][q]["agree"] for q in keep if q in P.get("T1", {}).get("vs_T0", {})}
    shares = [r["drawn_share_of_live_grid"] for r in rows if r["arm"] == "T1"]
    return {"rule": rule, "matches": len({r["match"] for r in rows}), "gate_onset": cq.gate_onset_summary(go),
            "arms": arms, "T1_vs_T0": t1, "drawn_share_mean": round(float(np.mean(shares)), 4) if shares else None}


def record_metrics() -> int:
    """Record the persistence, the lane comparison and the truth sweep in the
    metrics ledger, series `t1_draw_rule` (the old series stand untouched)."""
    from reticle.metrics import record as rec
    deps = {"version": VERSION, "episodes": ep.EPISODES_VERSION, "replay_truth": rt.REPLAY_TRUTH_VERSION,
            "remote_lag_ms": rt.REMOTE_LAG_MS, "smokes": sorted(SMOKES), "hfov_deg": ep.PARAMS["HFOV_DEG"]}
    ps = json.loads((OUT / "persistence_summary.json").read_text(encoding="utf-8"))
    for sid, v in list(ps["per_match"].items()) + [("dev3", ps["pooled"])]:
        vals = {}
        for k in ("smoke", "geom", "smoke_clean"):
            for a, b in v.get(k, {}).items():
                if isinstance(b, list):
                    vals[f"{k}.{a}_lo"], vals[f"{k}.{a}_hi"] = b
                elif b is not None:
                    vals[f"{k}.{a}"] = b
        rec("t1_draw_rule", part="persistence", session=sid, values=vals, deps=deps,
            context={"task": TASK, "status": v.get("status")},
            note="enemy icon -> '?' swap less the last smoke-blocked truth sight (ms); clean drops swaps with a "
                 "refused enemy at the '?' or an icon read there again within 250 ms")
    lane = json.loads((OUT / "lane.json").read_text(encoding="utf-8"))
    for sid, rules in lane.items():
        for rule, x in rules.items():
            rec("t1_draw_rule", part=f"lane/{rule}", session=sid,
                values={k: x[k] for k in ("drawn_share", "real_share", "hit_rate", "hits", "misses",
                                          "extras_rate", "extras", "icons", "p_ms")},
                deps=dict(deps, rule=RULES[rule]), context={"task": TASK, "population": "enemy_lane_check live read frames"})
    for rule in ("T1", "T1d"):
        if not (OUT / f"truth_{rule}.jsonl").is_file():
            continue
        R = truth_report(rule)
        sess = "pooled17" if R["matches"] >= 17 else f"pooled{R['matches']}"
        g = R["gate_onset"]
        rec("t1_draw_rule", part=f"truth/{rule}/gate_onset", session=sess,
            values={k: g[k] for k in ("n", "open_0", "open_250", "open_500", "local_open", "lead_ms_p50",
                                      "lead_ms_p10")},
            deps=dict(deps, rule=RULES[rule]), context={"task": TASK, "matches": R["matches"]})
        for arm, o in R["arms"].items():
            vals = {"share": o["share"], "frame_share": o["frame_share"]}
            vals.update({f"vs_T1.{q}": a for q, a in o["vs_T1"].items()})
            vals.update({f"vs_T0.{q}": a for q, a in o["vs_T0"].items()})
            rec("t1_draw_rule", part=f"truth/{rule}/{arm}", session=sess, values=vals,
                deps=dict(deps, rule=RULES[rule], arm=cq.ARMS[arm]), context={"task": TASK, "matches": R["matches"]})
        (OUT / f"truth_report_{rule}.json").write_text(json.dumps(R, indent=1), encoding="utf-8")
        print(json.dumps(R, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("smokes")
    a.add_argument("keys", nargs="*")
    b = sub.add_parser("persist")
    b.add_argument("sessions", nargs="*")
    c = sub.add_parser("lane")
    c.add_argument("sessions", nargs="*")
    c.add_argument("--rules", default="T1,T1a,T1s,T1p,T1d")
    d = sub.add_parser("truth")
    d.add_argument("keys", nargs="*")
    d.add_argument("--rule", default="T1d")
    e = sub.add_parser("report")
    e.add_argument("--rule", default="T1d")
    sub.add_parser("record")
    args = ap.parse_args(argv)
    if args.cmd == "record":
        return record_metrics()
    if args.cmd == "smokes":
        return run_smokes(args.keys or cq.replay_matches())
    if args.cmd == "persist":
        return run_persist(args.sessions or list(DEV))
    if args.cmd == "lane":
        return run_lane(args.sessions or list(DEV), args.rules.split(","))
    if args.cmd == "truth":
        return run_truth(args.keys or cq.replay_matches(), args.rule)
    print(json.dumps(truth_report(args.rule), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
