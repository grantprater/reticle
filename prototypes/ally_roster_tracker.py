r"""Track the four teammates, not open-ended entities.

    .\.venv\Scripts\python.exe prototypes\ally_roster_tracker.py [SID]

Measured, not wired: `round_lifetimes.RoundLifetimes` owns round entities.

Ally icons are always drawn and a side fields one agent each
[domain:rounds/agent-uniqueness], so the ally minimap population is the
lineup's allies less the player, whose icon is the self key. Each round keeps
one track per teammate agent. Each frame's icons go to those tracks one-to-one
(`track.assign`), maximising the owner's per-icon identity scores
(`identity.claims_from_ally_icons`, the evidence's `scores`), and a pair is
allowed only when `track.admits` lets a walker cover the distance from the
track's last sighting in the time since; a track not yet seen this round
takes any position. An icon no teammate can take is a misread and is refused
with that reason, never minted as an entity.

Round bounds come from the stored `round_entity` observations. With
`--deaths` a teammate's track ends at its killfeed death (stored death
verdicts, ally side, named victim); without, the deaths are the independent
check: a dead teammate's track should take no icon after its death.
Predictions and outcome: `ally-roster-tracker` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.adjudication.identity import claims_from_ally_icons, load_identity_gallery  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.round_lifetimes import REFIT_SEPARATION_PX, replay_scale  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.track import CLASSES, admits, assign, association_tolerance  # noqa: E402

STORE = Store()
#: A dead teammate's track may take icons this long after the killfeed death
#: before the check counts it: the icon fades, and the entry lags the kill.
DEATH_GRACE_MS = 2000.0


def load(sid: str):
    icons = [e for e in STORE.read_events("ally_icon", sid) if e.get("kind") == "icon"]
    lineup = load_lineup(sid, STORE.root)
    claims = claims_from_ally_icons(icons, lineup, gallery=load_identity_gallery(STORE.root),
                                    session_id=sid)
    scores = {c["entity_id"].rsplit(":ally_icon:", 1)[-1]: (c.get("evidence") or {}).get("scores") or {}
              for c in claims}
    rounds = {}
    for o in STORE.read_events("round_entity", sid):
        if o.get("kind") == "observation":
            lo, hi = rounds.get(o["round_no"], (math.inf, -math.inf))
            rounds[o["round_no"]] = (min(lo, o["t_ms"]), max(hi, o["t_ms"]))
    deaths = defaultdict(list)
    for v in STORE.read_events("death", sid):
        if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim"):
            deaths[v["victim"]].append(float(v["t_ms"]))
    player = (lineup.get("player") or {}).get("agent")
    agents = sorted({r.get("agent") for r in lineup["sides"]["ally"]} - {player, None})
    return icons, scores, rounds, deaths, agents


def track(sid: str, *, use_deaths: bool = False) -> dict:
    icons, scores, rounds, deaths, agents = load(sid)
    scale, _ = replay_scale({"session": sid}, STORE.root)
    # The ring fit jumps up to REFIT_SEPARATION_PX onto the teardrop lobe
    # between frames (ROUND_ENTITIES.md); that is the fit, not the teammate.
    slack = max(association_tolerance(scale), REFIT_SEPARATION_PX * scale)
    by_frame = defaultdict(list)
    for e in icons:
        by_frame[e["t_ms"]].append(e)
    out = {}
    for rn, (t0, t1) in sorted(rounds.items()):
        last = {}   # agent -> (t, x, y)
        dead_at = {a: min((t for t in deaths.get(a, []) if t0 <= t <= t1), default=None)
                   for a in agents}
        for t in sorted(k for k in by_frame if t0 <= k <= t1):
            obs = by_frame[t]
            live = [a for a in agents if not (use_deaths and dead_at[a] is not None and t > dead_at[a])]
            cost = []
            for e in obs:
                s = scores.get(e["observation_key"], {})
                row = []
                for a in live:
                    ok = True
                    if a in last:
                        lt, lx, ly = last[a]
                        d = math.hypot(e["cx"] - lx, e["cy"] - ly)
                        ok = admits(CLASSES["walker"], max(0.0, d - slack), (t - lt) / 1000, scale)[0]
                    row.append(-s.get(a, 0.0) if ok else math.inf)
                cost.append(row)
            got = assign(cost) if live and obs else [-1] * len(obs)
            for e, j in zip(obs, got):
                if j >= 0 and math.isfinite(cost[obs.index(e)][j]):
                    a = live[j]
                    last[a] = (t, e["cx"], e["cy"])
                    out[e["observation_key"]] = {"agent": a, "round": rn, "t": t}
                else:
                    out[e["observation_key"]] = {"agent": None, "round": rn, "t": t,
                                                 "reason": "no living teammate can take it"}
    return {"assigned": out, "deaths": deaths, "rounds": rounds, "agents": agents}


def evaluate(sid: str) -> dict:
    res = track(sid)
    a = res["assigned"]
    n = Counter("assigned" if x["agent"] else "refused" for x in a.values())
    # Consistency with the round_entity arbiter's resolved entity agents.
    ents = {e["id"]: e.get("agent") for e in STORE.read_events("round_entity", sid)
            if e.get("kind") == "entity"}
    agree = Counter()
    for o in STORE.read_events("round_entity", sid):
        if o.get("kind") == "observation" and o.get("family") == "ally":
            ent = ents.get(o.get("entity_id"))
            x = a.get(o["observation_key"])
            if ent and x and x["agent"]:
                agree["agree" if x["agent"] == ent else "differ"] += 1
    # Independent: a dead teammate takes no icon after its death.
    after = Counter()
    for agent, ts in res["deaths"].items():
        for t in ts:
            rn = next((r for r, (lo, hi) in res["rounds"].items() if lo <= t <= hi), None)
            if rn is None or agent not in res["agents"]:
                continue
            late = [x for x in a.values() if x["agent"] == agent and x["round"] == rn
                    and x["t"] > t + DEATH_GRACE_MS]
            after["silent" if not late else "icons after death"] += 1
    probe = [k for k, x in a.items() if x["round"] == 14 and abs(x["t"] - 1375083) < 40]
    return {"icons": dict(n), "refused_share": round(n["refused"] / max(1, sum(n.values())), 4),
            "agreement": dict(agree), "agreement_rate": round(agree["agree"] / max(1, sum(agree.values())), 4),
            "deaths": dict(after), "probe_1375083": [(k, a[k]["agent"]) for k in probe]}


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(sys.argv[1] if len(sys.argv) > 1 else "a06f04a0059f"), indent=1))
