r"""Whose kit the ability tray shows: the kit witness.

    .\.venv\Scripts\python.exe -m reticle tray-kit <session> | --all [--record]

Owns [owns:tray-kit].

After the player dies the tray shows a spectated teammate's kit
[domain:hud/tray-after-player-death]. The pipeline froze the player's kit only
where a killfeed entry witnessed the death, and a capture whose killfeed
prints no entry for the player (`4f207c0c4e39`) read every teammate's charges
and casts as the player's. This module reads the kit from the tray's own
icons, so the tray says when it stops being the player's.

**What it is handed.** Per sample of the crop cache, whether `tray` finds the
tray drawn, and a scorer that matches the four slot icons against any set of
agents' catalogue icons (`tray_icons.slot_scores`, run by the command). It
reads no pixels itself. A kit's fit is the mean of its four slot scores.

**The candidate set follows the context.** The prior comes first, and each
widening is a surprise the row records:

1. `player` -- the lineup's verdict on the player's slot. While the player
   lives the tray shows the player's kit, so the player's kit is the
   prediction. It is accepted when its fit reaches PLAYER_FIT_MIN; one
   candidate has no runner-up, so the threshold is set above every fit the
   player's kit reached on a spectated kit (docs/TRAY_KIT_WITNESS.md).
2. `allies` -- the ally side's agents as the arbiter names them, with the best
   guess of an unresolved slot as a rival that can take the match away and
   never the name (`identity.side_candidates`). A spectated kit is a
   teammate's. The best kit names when its fit reaches KIT_FIT_MIN and its
   margin over the runner-up reaches MARGIN_MIN.
3. `all` -- every agent the catalogue holds, only where no ally kit fits or the
   ally side has a slot with no guess (`blind`); the row says `widened` and why.

A named sample's claim declares `depends_on` the lineup verdicts its set rests
on: the player's slot for `player`, every ally slot for `allies`, none for
`all`. The prior is thereby weighed once.

**Refusals.** An unread kit is null with the first reason that applies:
`no_lineup` (no stored lineup, so no candidate set), `tray_not_drawn`
(`tray.drawn`), `icons_dim` (fewer than MIN_READ_SLOTS slots hold an icon any
agent's reference fits at SLOT_READ_MIN: dimmed, flashed or covered),
`rival_best` (an unresolved slot's guess fits best), `margin_below` (a kit
fits, and another fits nearly as well), `fit_below` (no kit fits, even after
widening).

**Names come from the arbiter.** Named samples form spans: runs of samples in
one cache span that name one kit, where a run shorter than MIN_RUN between two
runs of one kit joins them as dissent. Each span is an entity,
`<sid>:tray:kit:<first t_ms>`, and each named sample in it publishes one
`identity_claim` on channel `tray_kit`. The span's agent is the arbiter's
verdict (`adjudicate_agent_identity`), whose majority keeps the dissent on the
row.

**The kit change.** The first sample of a span the arbiter names for another
agent than the player's, holding at least MIN_RUN claims for that agent and
following a span of the player's kit in the same cache span, is a stored
observation `kit_change_ms`, with the player's last sample before it
(`since_ms`). The owner of a death is `death`, keyed by killfeed entries; this
witness says only that the tray stopped showing the player's kit. Consumers
read it as evidence that the owner is dead with a reason of their own
(`ability_timeline.player_tray_casts`, `adjudication.ability_state`). A return
to the player's kit within a cache span (the round ends and the view returns to
the player [domain:hud/tray-slot-icons], or a revive) is stored as
`kit_return`; the consumers end the witness's death there, since the tray shows
the player's kit again.

**Consumers judge own against their agent.** A span's agent is the arbiter's
verdict on the kit and holds no player agent; only its `own` does. Rows written
while the arbiter named no player agent (`4f207c0c4e39`) stored no change, and
the gate passed 28 drops under teammates' kits. So `stored_kit_witness`
recomputes the changes against the consumer's player agent
(`kit_transitions`), and `kit_agents_at` names the kit at any instant, which
the gate reads at each drop.
"""
from __future__ import annotations

from collections import Counter

import numpy as np

from ..version import TRAY_KIT_VERSION
from .identity import (AGENT_IDENTITY_VERSION, adjudicate_agent_identity, identity_claim,
                       identity_events, player_identity, side_candidates)

#: The identity channel every kit claim is made on.
CHANNEL = "tray_kit"
SLOT_KEYS = ("C", "Q", "E", "X")
#: The least fit at which the player's kit, the only candidate, is accepted.
PLAYER_FIT_MIN = 0.6
#: The least fit at which the best kit of a set of two or more names.
KIT_FIT_MIN = 0.5
#: The least margin of the best kit's fit over the runner-up's.
MARGIN_MIN = 0.1
#: A slot holds a legible icon when some agent's reference scores this there.
SLOT_READ_MIN = 0.5
#: The fewest legible slots a sample needs to be read at all.
MIN_READ_SLOTS = 2
#: The fewest claims a run needs to stand as its own span, and a kit change
#: needs to be one.
MIN_RUN = 2
#: The refusal reasons, in the order they are tested.
REFUSALS = ("no_lineup", "tray_not_drawn", "icons_dim", "rival_best", "margin_below",
            "fit_below")


def candidate_sets(lineup: dict | None, session_id: str) -> dict | None:
    """The sets the context allows, from the stored lineup's identity
    verdicts, or None without a lineup. `player` is the player's agent where
    the arbiter resolves the player's slot; `allies` the ally side's named
    agents and `rivals` the guesses of its unresolved slots
    (`identity.side_candidates`); `blind` the unresolved slots with no guess;
    and the entity ids each set rests on."""
    if not lineup or not (lineup.get("sides") or {}).get("ally"):
        return None
    verdicts = {v.get("entity_id"): v for v in lineup.get("agent_identity") or []}
    rows, eids = [], []
    for i, row in enumerate(lineup["sides"]["ally"]):
        slot = row.get("slot", i)
        eid = f"{session_id}:ally:slot:{slot}"
        v = verdicts.get(eid) or {}
        named = v.get("agent") if v.get("status") == "resolved" else None
        rows.append({"slot": slot, "agent": named, "best_guess": row.get("best_guess")})
        eids.append(eid)
    sides = side_candidates(rows)
    who = player_identity(lineup, session_id)
    player = who["agent"]
    return {"player": player, "player_entity": who["entity_id"] if player else None,
            "allies": list(sides["named"]), "rivals": [r for r in sides["rivals"] if r],
            "blind": len(sides["blind"]), "ally_entities": eids}


def _ranked(agents: list[str], scores: np.ndarray) -> list[tuple[str, float]]:
    fit = np.nanmean(np.where(np.isfinite(scores), scores, np.nan), axis=1)
    fit = np.where(np.isfinite(fit), fit, -1.0)
    return sorted(((a, float(f)) for a, f in zip(agents, fit)), key=lambda x: (-x[1], x[0]))


def _slots(agents: list[str], scores: np.ndarray) -> list[dict]:
    """Per slot: the best agent of the set, its score, the runner-up and the margin."""
    out = []
    for k, key in enumerate(SLOT_KEYS):
        col = [(float(scores[i, k]), a) for i, a in enumerate(agents) if np.isfinite(scores[i, k])]
        col.sort(key=lambda x: (-x[0], x[1]))
        best = col[0] if col else (None, None)
        second = col[1] if len(col) > 1 else (None, None)
        out.append({"slot": key, "best": best[1],
                    "score": None if best[0] is None else round(best[0], 3),
                    "runner_up": second[1],
                    "margin": (None if second[0] is None or best[0] is None
                               else round(best[0] - second[0], 3))})
    return out


def read_sample(drawn: bool, score, sets: dict | None, all_agents: list[str]) -> dict:
    """One sample's reading: the kit it names or the reason it refuses, the
    set it was read against and why, and the evidence. `score(agents)` returns
    the `len(agents)` x 4 slot scores of this sample. Pure in its inputs."""
    if sets is None:
        return {"kit_agent": None, "reason": "no_lineup", "set": None}
    if not drawn:
        return {"kit_agent": None, "reason": "tray_not_drawn", "set": None}
    stages = []
    if sets["player"]:
        stages.append(("player", [sets["player"]],
                       "the lineup's verdict on the player's slot: the tray shows the "
                       "player's kit while the player lives", [sets["player_entity"]]))
    if sets["blind"]:
        why_all = f"widened: the ally side has {sets['blind']} slot(s) with no guess"
    else:
        allies = sorted(set(sets["allies"]) | set(sets["rivals"]))
        stages.append(("allies", allies, "the lineup's ally side: a spectated kit is a "
                                         "teammate's", list(sets["ally_entities"])))
        why_all = "widened: no kit of the ally side fits"
    stages.append(("all", list(all_agents), why_all, []))
    tried = []
    for name, agents, why, deps in stages:
        sc = score(agents)
        ranked = _ranked(agents, sc)
        (best, fit), second = ranked[0], (ranked[1] if len(ranked) > 1 else (None, None))
        margin = None if second[0] is None else round(fit - second[1], 3)
        ev = {"set": {"name": name, "agents": agents, "why": why, "depends_on": deps},
              "slots": _slots(agents, sc),
              "kit": {"best": best, "fit": round(fit, 3), "runner_up": second[0],
                      "runner_up_fit": None if second[1] is None else round(second[1], 3),
                      "margin": margin},
              "tried": list(tried)}
        need = PLAYER_FIT_MIN if len(agents) == 1 else KIT_FIT_MIN
        if fit < need:
            tried.append({"set": name, "best": best, "fit": round(fit, 3)})
            if name != "all":
                continue
            legible = int(np.sum(np.nanmax(np.where(np.isfinite(sc), sc, -1.0), axis=0)
                                 >= SLOT_READ_MIN))
            ev["legible_slots"] = legible
            return {"kit_agent": None,
                    "reason": "icons_dim" if legible < MIN_READ_SLOTS else "fit_below", **ev}
        if best in sets["rivals"] and best not in sets["allies"] and name == "allies":
            return {"kit_agent": None, "reason": "rival_best", **ev}
        if margin is not None and margin < MARGIN_MIN:
            return {"kit_agent": None, "reason": "margin_below", **ev}
        return {"kit_agent": best, "reason": None, **ev}
    raise AssertionError("the last stage always returns")


def _runs(named: list[tuple[int, str]]) -> list[list]:
    """Group (sample index, agent) pairs, in order, into runs of one agent,
    then join a run shorter than MIN_RUN into the runs either side when both
    name one agent. Returns [majority agent, [indices]] per span."""
    runs: list[list] = []
    for i, a in named:
        if runs and runs[-1][0] == a:
            runs[-1][1].append(i)
        else:
            runs.append([a, [i]])
    out: list[list] = []
    j = 0
    while j < len(runs):
        a, idx = runs[j][0], list(runs[j][1])
        while (j + 2 < len(runs) and len(runs[j + 1][1]) < MIN_RUN
               and runs[j + 2][0] == a):
            idx += runs[j + 1][1] + runs[j + 2][1]
            j += 2
        out.append([a, sorted(idx)])
        j += 1
    return out


def same_agent(a: str | None, b: str | None) -> bool | None:
    """Whether two agent names are one agent, across the asset spelling
    (KAY/O is KAY_O); None where either is unknown."""
    if a is None or b is None:
        return None
    return str(a).replace("/", "_") == str(b).replace("/", "_")


def kit_transitions(span_rows: list[dict], player: str | None,
                    common: dict | None = None) -> list[dict]:
    """The `kit_change` and `kit_return` rows of a session's span rows, each
    span judged own or another's against `player` (`same_agent`). The module
    docstring gives the rule; `adjudicate` stores these rows, and
    `stored_kit_witness` recomputes them against a consumer's agent."""
    common = common or {}
    changes = []
    for cs in sorted({r["cache_span"] for r in span_rows}):
        state, last_own, last_other = "start", None, None
        for r in (r for r in span_rows if r["cache_span"] == cs):
            own = same_agent(r.get("agent"), player)
            if own is True:
                if state == "changed":
                    changes.append({**common, "kind": "kit_return", "cache_span": cs,
                                    "t_ms": r["t_first_ms"], "since_ms": last_other,
                                    "entity_id": r["entity_id"], "agent": r["agent"]})
                state, last_own = "own", r["t_last_ms"]
            elif own is False and r["claims_for_agent"] >= MIN_RUN:
                if state == "own":
                    changes.append({**common, "kind": "kit_change", "cache_span": cs,
                                    "kit_change_ms": r["t_first_ms"], "since_ms": last_own,
                                    "entity_id": r["entity_id"], "agent": r["agent"],
                                    "claims": r["claims"]})
                    state = "changed"
                last_other = r["t_last_ms"]
    return changes


def adjudicate(session_id: str, samples: list[dict], sets: dict | None,
               inputs: dict, parameters: dict) -> dict:
    """The session's stored rows, its identity claims, the arbiter's verdicts
    and the formal identity events.

    `samples` are, in time order, {"t_ms", "cache_span", "drawn", **read_sample};
    `inputs` the stamps of what they were read from; `parameters` the reader's
    geometry and sampling rate."""
    common = {"session_id": session_id, "tray_kit_version": TRAY_KIT_VERSION}
    player = (sets or {}).get("player")
    claims, spans = [], []
    for cs in sorted({s["cache_span"] for s in samples}):
        mine = [(i, s["kit_agent"]) for i, s in enumerate(samples)
                if s["cache_span"] == cs and s["kit_agent"]]
        for agent, idx in _runs(mine):
            eid = f"{session_id}:tray:kit:{int(round(samples[idx[0]]['t_ms']))}"
            for i in idx:
                s = samples[i]
                claims.append(identity_claim(
                    eid, s["kit_agent"], channel=CHANNEL, observed_at_ms=s["t_ms"],
                    source_version=TRAY_KIT_VERSION,
                    evidence={"fit": s["kit"]["fit"], "margin": s["kit"]["margin"],
                              "runner_up": s["kit"]["runner_up"], "set": s["set"]["name"]},
                    depends_on=s["set"]["depends_on"]))
            spans.append({"entity_id": eid, "cache_span": cs, "index": idx, "run_agent": agent})
    verdicts = adjudicate_agent_identity(claims)
    by_id = {v["entity_id"]: v for v in verdicts}

    span_rows, events = [], []
    for sp in spans:
        v, idx = by_id[sp["entity_id"]], sp["index"]
        agent = v["agent"] if v["status"] == "resolved" else None
        span_rows.append({
            **common, "kind": "span", "entity_id": sp["entity_id"],
            "cache_span": sp["cache_span"], "t_first_ms": samples[idx[0]]["t_ms"],
            "t_last_ms": samples[idx[-1]]["t_ms"], "claims": len(idx),
            "claims_for_agent": sum(samples[i]["kit_agent"] == agent for i in idx),
            "sets": dict(Counter(samples[i]["set"]["name"] for i in idx)),
            "agent": agent, "identity_status": v["status"], "identity_reason": v["reason"],
            "votes": v["by_channel"][CHANNEL]["votes"],
            "independent_channels": v["independent_channels"], "depends_on": v["depends_on"],
            "own": None if player is None or agent is None else agent == player})
        events += identity_events([v], session_id, samples[idx[0]]["t_ms"])

    changes = kit_transitions(span_rows, player, common)

    sample_rows = [{**common, "kind": "sample", **{k: v for k, v in s.items()}}
                   for s in samples]
    named = [s for s in samples if s["kit_agent"]]
    coverage = {
        **common, "kind": "coverage", "inputs": dict(sorted(inputs.items())),
        "agent_identity": AGENT_IDENTITY_VERSION, "parameters": parameters,
        "thresholds": {"PLAYER_FIT_MIN": PLAYER_FIT_MIN, "KIT_FIT_MIN": KIT_FIT_MIN,
                       "MARGIN_MIN": MARGIN_MIN, "SLOT_READ_MIN": SLOT_READ_MIN,
                       "MIN_READ_SLOTS": MIN_READ_SLOTS, "MIN_RUN": MIN_RUN},
        "lineup": sets is not None, "player_agent": player,
        "candidate_sets": sets,
        "samples": len(samples), "named": len(named),
        "named_by_agent": dict(sorted(Counter(s["kit_agent"] for s in named).items())),
        "named_by_set": dict(sorted(Counter(s["set"]["name"] for s in named).items())),
        "refused": dict(sorted(Counter(s["reason"] for s in samples if s["reason"]).items())),
        "spans": len(span_rows),
        "spans_own": sum(r["own"] is True for r in span_rows),
        "spans_other": sum(r["own"] is False for r in span_rows),
        "kit_changes": sum(c["kind"] == "kit_change" for c in changes),
        "kit_returns": sum(c["kind"] == "kit_return" for c in changes)}
    return {"rows": [coverage] + span_rows + changes + sample_rows, "claims": claims,
            "verdicts": verdicts, "events": events}


def stored_kit_witness(rows: list[dict], version: str = TRAY_KIT_VERSION, *,
                       agent: str | None = None) -> dict:
    """What a consumer reads from a session's stored `tray_kit` rows: the kit
    changes and returns, the spans of another agent's kit, every span the
    arbiter named (`spans`, (t_first_ms, t_last_ms, agent)), the stamp, and
    which agent "own" was judged against (`own_basis`).

    The span rows hold the arbiter's verdict on each span's kit, which no
    player agent enters; only "own" does. So the changes, returns and other
    spans are recomputed (`kit_transitions`) against the consumer's `agent`,
    the identity arbiter's verdict on the player, where it is given:
    `own_basis` is `stored` where it equals the agent the rows were written
    against and `consumer_agent` where the rows named none or another. Without
    an agent from either, the changes and other spans are empty with the
    reason `no_player_agent`, and `spans` still lists the named kits, so a
    consumer can refuse a drop under a named kit it cannot call the player's.
    Empty lists, `spans` included, with the reason they are not used:
    `no_rows`, `stale:<version>`, `no_lineup`."""
    empty = {"kit_changes_ms": [], "kit_returns_ms": [], "other_spans": [], "spans": [],
             "own_basis": None}
    cov = next((r for r in rows if r.get("kind") == "coverage"), None)
    if cov is None:
        return {**empty, "version": None, "reason": "no_rows"}
    if cov.get("tray_kit_version") != version:
        return {**empty, "version": cov.get("tray_kit_version"),
                "reason": f"stale:{cov.get('tray_kit_version')}"}
    if not cov.get("lineup"):
        return {**empty, "version": version, "reason": "no_lineup"}
    span_rows = [r for r in rows if r.get("kind") == "span"]
    spans = [(float(r["t_first_ms"]), float(r["t_last_ms"]), r["agent"])
             for r in span_rows if r.get("agent")]
    player = agent if agent is not None else cov.get("player_agent")
    if player is None:
        return {**empty, "spans": spans, "version": version, "reason": "no_player_agent"}
    basis = "stored" if same_agent(player, cov.get("player_agent")) else "consumer_agent"
    changes = kit_transitions(span_rows, player)
    return {"kit_changes_ms": sorted(float(r["kit_change_ms"]) for r in changes
                                     if r["kind"] == "kit_change"),
            "kit_returns_ms": sorted(float(r["t_ms"]) for r in changes
                                     if r["kind"] == "kit_return"),
            "other_spans": [s for s in spans if same_agent(s[2], player) is False],
            "spans": spans, "own_basis": basis, "version": version, "reason": None}


def spectated_agent(t_ms: float, other_spans) -> str | None:
    """The agent of the other kit whose span holds `t_ms`, or None."""
    return next((a for t0, t1, a in other_spans if t0 <= t_ms <= t1), None)


#: How far before a drop the last named kit sample may lie and still name the
#: kit the drop fell from: three samples of the 0.5 s grid, so a tray the cast
#: itself dims or flashes for a sample or two keeps the kit read before it.
KIT_LOOKBACK_MS = 1500.0
#: How far after a drop a span may start and still hold it: under one sample,
#: so the kit that follows a spectator switch never names the drop before it.
KIT_LOOKAHEAD_MS = 100.0


def kit_agents_at(times_ms, spans, lookback_ms: float = KIT_LOOKBACK_MS,
                  lookahead_ms: float = KIT_LOOKAHEAD_MS) -> list[str | None]:
    """Per instant of `times_ms`, the arbiter's agent for the kit the tray
    showed then: of the named `spans` (t_first_ms, t_last_ms, agent) that
    start by the instant plus `lookahead_ms` and last until at least the
    instant less `lookback_ms`, the one that starts last; None where no span
    does. Vectorised over instants and spans."""
    t = np.asarray(times_ms, float).reshape(-1, 1)
    if not len(spans) or not t.size:
        return [None] * t.shape[0]
    t0 = np.array([s[0] for s in spans], float)
    t1 = np.array([s[1] for s in spans], float)
    hold = (t0[None] <= t + lookahead_ms) & (t1[None] >= t - lookback_ms)
    j = np.argmax(np.where(hold, t0[None], -np.inf), axis=1)
    return [spans[k][2] if hold[i, k] else None for i, k in enumerate(j)]
