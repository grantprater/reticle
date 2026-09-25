"""How often each identity channel names the right agent, per agent.

Owns [owns:identity-channel-reliability].

A channel's reliability is measured where some OTHER, independent witness
named the same entity: the player HUD (the player's own kill or death), the
ability icon's caster, or the scoreboard's newly dimmed row. Those are
`REFERENCE_CHANNELS`; a claim that `depends_on` other verdicts is no
reference. Where the references present agree, every other channel's named
claim on that entity is an outcome, right or wrong, for (channel, true
agent). A reference is scored against the other references too, where two
of them name one entity.

The outcomes become a Beta posterior per channel from a uniform prior
(`right + 1`, `wrong + 1`), and per (channel, agent) from the channel's rate
as prior, worth `AGENT_PRIOR_WEIGHT` observations. This is a belief with its evidence, not a
verdict: it says how far a channel's name can be trusted, and it is biased
toward the population the references cover -- the player's own kills and
deaths, ability kills and scoreboard-bound deaths -- which the report keeps
beside the numbers. Portrait exemplars are labelled by these same reference
channels on OTHER entries, so the portrait channel measured here is the one
deployed, exemplars included; its own entry never labels itself.

Recomputed from stored `death` streams; decodes nothing.
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

RELIABILITY_VERSION = "identity-reliability-0.1.0"

#: Where a channel's scored outcomes came from; each is also reported alone,
#: because the witness population and the labelled sample are different feeds.
SOURCES = ("witness", "player_label")

#: Pseudo-observations the channel's own rate is worth as each agent's prior.
AGENT_PRIOR_WEIGHT = 20

#: Witnesses whose names are independent of the killfeed portraits.
REFERENCE_CHANNELS = ("player_hud", "killfeed_weapon", "scoreboard_dim")


def outcomes(death_rows: list[dict]) -> list[dict]:
    """One row per scored channel claim: the entity, role, channel, the agent
    the references name, the agent the channel said, and whether the claim
    rested on other verdicts."""
    out = []
    for r in death_rows:
        if r.get("kind") != "death_verdict":
            continue
        for key, role in (("identity", "victim"), ("killer_identity", "killer")):
            v = (r.get("metadata") or {}).get(key) or {}
            by = v.get("by_channel") or {}
            refs = {ch: row["agent"] for ch, row in by.items()
                    if ch in REFERENCE_CHANNELS and row.get("agent") and not row.get("depends_on")}
            for ch, row in by.items():
                said = row.get("agent")
                if not said:
                    continue
                others = {c: a for c, a in refs.items() if c != ch}
                if not others or len(set(others.values())) != 1:
                    continue
                out.append({"entity_id": v.get("entity_id"), "role": role, "channel": ch,
                            "truth": next(iter(others.values())), "said": said,
                            "reference": sorted(others), "dependent": bool(row.get("depends_on")),
                            "death_id": r.get("death_id"), "t_ms": r.get("t_ms"),
                            "session_id": r.get("session_id")})
    return out


def label_outcomes(label_rows: list[dict], death_rows: list[dict],
                   channel: str = "killfeed_portrait") -> list[dict]:
    """The player's names for sampled entities against the channel's claim on
    them now: the unbiased reference, since the sample is drawn from the names
    that channel alone decided. Unsure rows and "not a portrait" score nothing."""
    by_entity = {}
    for r in death_rows:
        for key, role in (("identity", "victim"), ("killer_identity", "killer")):
            v = (r.get("metadata") or {}).get(key) or {}
            if v.get("entity_id"):
                by_entity[v["entity_id"]] = (role, v, r)
    out = []
    for lab in label_rows:
        if lab.get("uncertain") or lab.get("class") != "agent" or lab["key"] not in by_entity:
            continue
        role, v, r = by_entity[lab["key"]]
        said = ((v.get("by_channel") or {}).get(channel) or {}).get("agent")
        if not said:
            continue
        out.append({"entity_id": lab["key"], "role": role, "channel": channel,
                    "truth": lab["answer"], "said": said, "reference": ["player_label"],
                    "dependent": bool(v.get("depends_on")), "death_id": r.get("death_id"),
                    "t_ms": r.get("t_ms"), "session_id": r.get("session_id")})
    return out


def icon_heldout_outcomes(by_name: dict) -> list[dict]:
    """The icon channel scored on the player's icon labels HELD OUT: the
    `weapon_icons/entries-loso` record, where each labelled entry was named by
    a gallery built without its session. Scoring the stored claims against the
    same labels would grade the gallery on its own exemplars. A right ability
    name is a right caster; a wrong name (a gun called an ability, or another
    ability) is a wrong one; refusals name no one and score nothing."""
    from .weapon import ability_agent
    out = []
    for name, c in by_name.items():
        agent = ability_agent(name)
        for _ in range(int(c.get("right", 0)) if agent else 0):
            out.append({"channel": "killfeed_weapon", "truth": agent, "said": agent,
                        "reference": ["player_label"], "role": "killer", "dependent": False})
        for _ in range(int(c.get("wrong", 0))):
            out.append({"channel": "killfeed_weapon", "truth": agent or name, "said": "another",
                        "reference": ["player_label"], "role": "killer", "dependent": False})
    return out


def beliefs(rows: list[dict]) -> dict:
    """Beta posteriors per (channel, agent) and per channel, with confusions."""
    per = defaultdict(lambda: [0, 0])
    overall = defaultdict(lambda: [0, 0])
    confusion = defaultdict(Counter)
    for o in rows:
        ok = o["said"] == o["truth"]
        per[(o["channel"], o["truth"])][0 if ok else 1] += 1
        overall[o["channel"]][0 if ok else 1] += 1
        if not ok:
            confusion[o["channel"]][f"{o['truth']} read as {o['said']}"] += 1
    beta = lambda r, w: {"right": r, "wrong": w, "alpha": r + 1, "beta": w + 1,
                         "mean": round((r + 1) / (r + w + 2), 3)}

    def shrunk(ch, r, w):
        # An agent's prior is its channel's rate, worth AGENT_PRIOR_WEIGHT
        # observations: a rarely scored agent inherits the channel's record
        # (Vyse at 4 of 4 is not 0.83), and its own misses still pull it down.
        cr, cw = overall[ch]
        m = (cr + 1) / (cr + cw + 2)
        a, b = AGENT_PRIOR_WEIGHT * m + r, AGENT_PRIOR_WEIGHT * (1 - m) + w
        return {"right": r, "wrong": w, "alpha": round(a, 3), "beta": round(b, 3),
                "mean": round(a / (a + b), 3)}
    by_source = defaultdict(lambda: [0, 0])
    for o in rows:
        src = "player_label" if o["reference"] == ["player_label"] else "witness"
        by_source[f"{o['channel']}@{src}"][0 if o["said"] == o["truth"] else 1] += 1
    return {"version": RELIABILITY_VERSION,
            "channels": {ch: beta(*rw) for ch, rw in sorted(overall.items())},
            "by_source": {k: beta(*rw) for k, rw in sorted(by_source.items())},
            "agents": {f"{ch}:{ag}": shrunk(ch, *rw) for (ch, ag), rw in sorted(per.items())},
            "confusions": {ch: dict(c.most_common()) for ch, c in sorted(confusion.items())},
            "population": dict(Counter(f"{o['role']} by {'+'.join(o['reference'])}"
                                       for o in rows))}


def name_probability(table: dict, verdict: dict) -> float | None:
    """How likely a resolved name is right, from the channels that named it.

    Each independent naming channel contributes its Beta mean for that agent
    (the channel's overall mean where the agent was never scored), and the
    name is wrong only if every one of them is: p = 1 - prod(1 - p_c). That
    assumes the channels err independently, which holds for different pixels
    (portrait, icon, HUD, scoreboard) better than for one channel's frames.
    None for a verdict that named no one. It annotates; it decides nothing.
    """
    if verdict.get("status") != "resolved" or not verdict.get("agent"):
        return None
    agent, miss = verdict["agent"], 1.0
    for ch, row in (verdict.get("by_channel") or {}).items():
        if row.get("agent") != agent or row.get("depends_on") or row.get("binding_from"):
            continue
        b = table["agents"].get(f"{ch}:{agent}") or table["channels"].get(ch)
        if b is None:
            continue
        miss *= 1.0 - b["mean"]
    return None if miss == 1.0 else round(1.0 - miss, 4)


def load(store_root: Path) -> dict | None:
    """The stored table at this version, or None when it was never built."""
    path = table_path(store_root)
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None


def table_path(store_root: Path) -> Path:
    return Path(store_root) / "reliability" / f"{RELIABILITY_VERSION}.json"


def write(store_root: Path, table: dict, inputs: dict) -> Path:
    path = table_path(store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**table, "inputs": inputs}, indent=1), encoding="utf-8")
    return path
