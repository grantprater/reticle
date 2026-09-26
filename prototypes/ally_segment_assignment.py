r"""Name each round's ally segments so no two icons are one agent at once.

    .\.venv\Scripts\python.exe prototypes\ally_segment_assignment.py [SID]

Measured, not wired: `round_entities` owns the stored names.

A side fields each agent once [domain:rounds/agent-uniqueness], so two ally
icons seen in one frame are two teammates. The stored round entities break
that: on `a06f04a0059f` two icons resolve to one agent at once in 2626 of
20708 frames. Here each round's continuity segments (`round_entity` entities
of family `ally`) take the round's teammates -- the lineup's allies less the
player -- so that segments co-observed in any frame take distinct agents,
maximising the segments' stored `identity_votes`. The search is exact per
connected component of the co-observation graph (branch and bound).

A segment whose votes the constraint forces it to give up is REFUSED with that
reason, never renamed to an agent nothing voted for; a segment without votes
stays unnamed. `prototypes/ally_roster_tracker.py`, which assigned icons frame
by frame under a hard motion gate, compounded one early error and is refuted.

The independent check is the killfeed: after a teammate's death (stored death
verdicts, ally side, named victim), no segment named for that agent should be
observed more than `DEATH_GRACE_MS` later in the round. Predictions and
outcome: `ally-segment-assignment` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.lineup import load_lineup  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
DEATH_GRACE_MS = 2000.0
#: Nodes the exact search may visit per component before it keeps its best.
MAX_NODES = 200_000


def _co_observed_groups(ids, edges):
    seen, out = set(), []
    for s in ids:
        if s in seen:
            continue
        stack, comp = [s], []
        seen.add(s)
        while stack:
            u = stack.pop()
            comp.append(u)
            for v in edges[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
        out.append(comp)
    return out


def solve(segs: list[str], votes: dict, edges: dict, agents: list[str]) -> tuple[dict, bool]:
    """Best {segment: agent or None} for one component; True when exact."""
    order = sorted(segs, key=lambda s: -max(votes[s].values(), default=0))
    cap = [max((votes[s].get(a, 0) for a in agents), default=0) for s in order]
    rest = [sum(cap[i:]) for i in range(len(order))] + [0]
    best = {"score": -1, "pick": {}}
    nodes = [0]

    def visit(i, pick, score):
        nodes[0] += 1
        if score + rest[i] <= best["score"] or nodes[0] > MAX_NODES:
            return
        if i == len(order):
            best["score"], best["pick"] = score, dict(pick)
            return
        s = order[i]
        taken = {pick[v] for v in edges[s] if v in pick and pick[v]}
        for a in sorted(agents, key=lambda a: -votes[s].get(a, 0)):
            if a not in taken and votes[s].get(a, 0) > 0:
                pick[s] = a
                visit(i + 1, pick, score + votes[s][a])
        pick[s] = None
        visit(i + 1, pick, score)
        del pick[s]

    visit(0, {}, 0)
    return best["pick"], nodes[0] <= MAX_NODES


def assign_segments(sid: str) -> dict:
    ev = STORE.read_events("round_entity", sid)
    lineup = load_lineup(sid, STORE.root)
    player = (lineup.get("player") or {}).get("agent")
    agents = sorted({r.get("agent") for r in lineup["sides"]["ally"]} - {player, None})
    ents = {e["id"]: e for e in ev if e.get("kind") == "entity" and e.get("family") == "ally"}
    frames = defaultdict(set)
    for o in ev:
        if o.get("kind") == "observation" and o.get("entity_id") in ents:
            frames[o["t_ms"]].add(o["entity_id"])
    edges = defaultdict(set)
    for ids in frames.values():
        for a in ids:
            edges[a] |= ids - {a}
    out, inexact = {}, 0
    by_round = defaultdict(list)
    for e in ents.values():
        by_round[e["round_no"]].append(e["id"])
    for rn, ids in by_round.items():
        votes = {s: {a: n for a, n in (ents[s].get("identity_votes") or {}).items() if a in agents}
                 for s in ids}
        for comp in _co_observed_groups(ids, edges):
            pick, exact = solve(comp, votes, edges, agents)
            inexact += not exact
            for s in comp:
                a = pick.get(s)
                out[s] = {"agent": a, "stored": ents[s].get("agent"), "n": ents[s]["observations"],
                          "round": rn, "status": "named" if a else
                          "refused: agent uniqueness leaves no voted teammate" if votes[s] else "unnamed"}
    return {"segments": out, "inexact_components": inexact, "frames": frames, "ents": ents}


def evaluate(sid: str) -> dict:
    res = assign_segments(sid)
    seg, frames = res["segments"], res["frames"]

    def dup_frames(key):
        n = 0
        for ids in frames.values():
            c = Counter(seg[s][key] for s in ids if seg[s][key])
            n += any(v > 1 for v in c.values())
        return n
    # Independent: killfeed deaths.
    obs_t = defaultdict(list)
    for t, ids in frames.items():
        for s in ids:
            obs_t[s].append(t)
    deaths = [(v["victim"], float(v["t_ms"])) for v in STORE.read_events("death", sid)
              if v.get("kind") == "death_verdict" and v.get("side") == "ally" and v.get("victim")]
    rounds = {}
    for s, x in seg.items():
        lo, hi = rounds.get(x["round"], (float("inf"), float("-inf")))
        rounds[x["round"]] = (min(lo, min(obs_t[s], default=lo)), max(hi, max(obs_t[s], default=hi)))
    check = {}
    for key in ("stored", "agent"):
        c = Counter()
        for agent, t in deaths:
            rn = next((r for r, (lo, hi) in rounds.items() if lo <= t <= hi), None)
            if rn is None:
                continue
            late = any(x[key] == agent and x["round"] == rn and any(u > t + DEATH_GRACE_MS for u in obs_t[s])
                       for s, x in seg.items())
            c["seen after death" if late else "silent"] += 1
        check[key] = dict(c)
    long_ = [x for x in seg.values() if x["n"] >= 15]
    kept = sum(x["agent"] == x["stored"] for x in long_ if x["stored"])
    refused = [x for x in seg.values() if x["status"].startswith("refused")]
    return {"segments": len(seg), "status": dict(Counter(x["status"] for x in seg.values())),
            "inexact_components": res["inexact_components"],
            "dup_frames": {"stored": dup_frames("stored"), "assigned": dup_frames("agent")},
            "deaths_check": check,
            "long_kept": f"{kept}/{sum(1 for x in long_ if x['stored'])}",
            "refused_short": f"{sum(x['n'] < 15 for x in refused)}/{len(refused)}",
            "refused_sizes": sorted(x["n"] for x in refused)[-10:]}


if __name__ == "__main__":
    import json
    print(json.dumps(evaluate(sys.argv[1] if len(sys.argv) > 1 else "a06f04a0059f"), indent=1))
