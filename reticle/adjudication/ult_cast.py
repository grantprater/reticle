r"""Which ultimate was cast, by which side, when: from stored voice-line peaks.

    .\.venv\Scripts\python.exe -m reticle ult-cast <session> | --all [--record]

Owns [owns:ult-cast].

Reads storage only: the `ult_line` peaks `ult_lines` stored, the lineup with
its board override (`lineup.load_lineup`), and the rounds table. It decodes
nothing, so a change here reruns in seconds.

**Selection.** A peak is selected when its score reaches THRESHOLD, 0.0443,
formulation F-B's operating point in `prototypes/voice_lines.py`
[metric:voice_lines/evaluate-F-B@all-matches#tau_op=0.0443]: the score at which
lineup-impossible detections fall to a tenth per live minute
[metric:voice_lines/evaluate-F-B@all-matches#impossible_per_min=0.099], where
the player's own ultimates are found at
[metric:voice_lines/evaluate-F-B@all-matches#own_recall=0.667]. It was chosen
on the same 19 match sessions it is scored on, so those two numbers are fitted
values, not held-out ones. Every peak above it stays: two templates that peak
at one onset are two selections (`docs/VOICE_LINES.md`, "Verdicts at 0.2.0").

**Classing** (`template_class`), against the lineup's identity verdicts:

* `own` -- the ally line of the player's agent; the caster hears their own ally
  line [domain:abilities/caster-hears-own-ult-line].
* `possible` -- the agent is named on the side the variant implies. The ally
  line is heard by the caster's team and the enemy line by the other
  [domain:abilities/ult-lines-heard-by-both-teams], so the variant is the
  caster's side relative to the player.
* `impossible` -- an ally line whose agent is neither named on the ally side
  nor the best guess or rival of an unresolved ally slot; an enemy line whose
  agent the fully named enemy side lacks. It is stored as a `refusal` row with
  its reason, and its claim abstains.
* `unknown` -- everything else, and every peak but the player's of a session
  without a lineup. A session without a lineup has no player either, so all of
  its peaks are `unknown`; the prototype read a demo's player from its tags.

**Names.** Each selected peak is one entity, `<sid>:ult_cast:<t_ms>:<template>`,
and publishes one claim through `adjudication.identity` on channel `ult_line`:
the template's agent (none for an impossible peak), with the score as evidence
and `depends_on` the lineup's slot verdicts of the variant's side, because the
class rests on them. A cast row's `agent` is the arbiter's verdict and nothing
else. The formal identity events go to their own stream, since a stream of
formal events holds nothing else.
"""
from __future__ import annotations

from collections import Counter

from ..version import ULT_CAST_VERSION
from .identity import (AGENT_IDENTITY_VERSION, adjudicate_agent_identity, identity_claim,
                       identity_events)

#: A peak at or above this score is selected. See the module docstring for the
#: run that set it and the sessions it was chosen on.
THRESHOLD = 0.0443
#: The identity channel every claim from an ultimate's voice line is made on.
CHANNEL = "ult_line"
VARIANTS = ("ally", "enemy")
CLASSES = ("own", "possible", "impossible", "unknown")


def _norm(agent):
    """The asset spelling of an agent name (KAY/O is KAY_O)."""
    return None if agent is None else str(agent).replace("/", "_")


def lineup_sides(lineup: dict | None, session_id: str) -> dict | None:
    """Per side, the agents the identity arbiter names, the best guess and
    rival of each slot it leaves unresolved, how many it leaves unresolved,
    whether all five are named, and the slot entity ids."""
    if not lineup or not lineup.get("sides"):
        return None
    verdicts = {v.get("entity_id"): v for v in lineup.get("agent_identity") or []}
    out = {}
    for side in VARIANTS:
        rows = lineup["sides"].get(side) or []
        named, soft, refused, slots = [], set(), 0, []
        for i, s in enumerate(rows):
            eid = f"{session_id}:{side}:slot:{s.get('slot', i)}"
            slots.append(eid)
            v = verdicts.get(eid) or {}
            if v.get("status") == "resolved" and v.get("agent"):
                named.append(_norm(v["agent"]))
            else:
                refused += 1
                soft |= {_norm(a) for a in (s.get("best_guess"), s.get("rival")) if a}
        out[side] = {"named": named, "soft": sorted(soft), "refused": refused,
                     "complete": refused == 0 and len(rows) == 5, "slots": slots}
    return out


def player_agent(lineup: dict | None, session_id: str) -> str | None:
    """The player's agent, where the arbiter resolves the player's slot."""
    if not lineup:
        return None
    slot = (lineup.get("player") or {}).get("slot")
    if slot is None:
        return None
    v = next((v for v in lineup.get("agent_identity") or []
              if v.get("entity_id") == f"{session_id}:ally:slot:{slot}"), None)
    return _norm(v["agent"]) if v and v.get("status") == "resolved" and v.get("agent") else None


def template_class(agent: str, variant: str, sides: dict | None,
                   player: str | None) -> tuple[str, str | None]:
    """(own, possible, impossible or unknown; the reason for any but possible)
    for one template in one session. See the module docstring."""
    if variant == "ally" and player is not None and agent == player:
        return "own", None
    if sides is None:
        return "unknown", "no_lineup"
    s = sides[variant]
    if agent in s["named"]:
        return "possible", None
    if variant == "ally":
        if agent in s["soft"]:
            return "unknown", "agent_is_a_guess_for_an_unresolved_ally_slot"
        return "impossible", "agent_not_on_ally_side"
    if s["complete"]:
        return "impossible", "agent_not_on_complete_enemy_side"
    return "unknown", f"enemy_side_has_{s['refused']}_unresolved_slots"


def round_of(t_ms: float, rounds: list[dict]) -> int | None:
    """The round an instant belongs to, by `rounds.in_round_window`: the
    post-round period is the round's own."""
    from ..rounds import in_round_window
    ends = {r["t_end_ms"] for r in rounds}
    e = [{"t_first": t_ms}]
    for r in rounds:
        if in_round_window(e, r["t_start_ms"], r["t_end_ms"], r["t_close_ms"], ends):
            return int(r["round_no"])
    return None


def adjudicate(session_id: str, peak_rows: list[dict], lineup: dict | None,
               rounds: list[dict], round_version: str | None,
               threshold: float = THRESHOLD) -> dict:
    """The session's stored rows, its claims, the arbiter's verdicts and the
    formal identity events, from stored peaks, the lineup and the rounds."""
    cover = next((r for r in peak_rows if r.get("kind") == "coverage"), {}) or {}
    peaks = [r for r in peak_rows if r.get("kind") == "peak"]
    sides = lineup_sides(lineup, session_id)
    player = player_agent(lineup, session_id)
    selected = sorted((p for p in peaks if p["score"] >= threshold),
                      key=lambda p: (p["frame"], p["template"]))
    source = cover.get("ult_line_version") or (peaks[0].get("ult_line_version") if peaks else None)

    claims, meta = [], {}
    for p in selected:
        agent, variant = _norm(p["agent"]), p["variant"]
        t_ms = round(p["t_s"] * 1000.0)
        cls, why = template_class(agent, variant, sides, player)
        eid = f"{session_id}:ult_cast:{t_ms}:{p['template']}"
        claims.append(identity_claim(
            eid, None if cls == "impossible" else agent, channel=CHANNEL,
            observed_at_ms=t_ms, reason=why, source_version=source,
            evidence={"template": p["template"], "variant": variant, "score": p["score"],
                      "floor": p.get("floor"), "class": cls, "threshold": threshold},
            depends_on=sides[variant]["slots"] if sides else None))
        meta[eid] = {"t_ms": t_ms, "peak": p, "agent": agent, "class": cls, "reason": why}

    verdicts = adjudicate_agent_identity(claims)
    by_id = {v["entity_id"]: v for v in verdicts}
    common = {"session_id": session_id, "ult_cast_version": ULT_CAST_VERSION}
    rows, events = [], []
    for eid, m in meta.items():
        p, v = m["peak"], by_id[eid]
        base = {**common, "entity_id": eid, "t_ms": m["t_ms"], "t_s": p["t_s"],
                "variant": p["variant"], "template": p["template"], "score": p["score"],
                "floor": p.get("floor"), "class": m["class"],
                "round": round_of(m["t_ms"], rounds)}
        if m["class"] == "impossible":
            rows.append({**base, "kind": "refusal", "template_agent": m["agent"],
                         "reason": m["reason"]})
        else:
            rows.append({**base, "kind": "cast", "side": p["variant"],
                         "player_cast": m["class"] == "own",
                         "agent": v["agent"] if v["status"] == "resolved" else None,
                         "identity_status": v["status"], "identity_reason": v["reason"],
                         "class_reason": m["reason"]})
        events += identity_events([v], session_id, m["t_ms"])

    by_class = Counter(r["class"] for r in rows)
    coverage = {**common, "kind": "coverage", "threshold": threshold,
                "inputs": {"ult_line": source,
                           "lineup": (lineup or {}).get("version"),
                           "board_state": (lineup or {}).get("board_state"),
                           "agent_identity": AGENT_IDENTITY_VERSION,
                           "round": round_version},
                "templates_key": cover.get("templates_key"),
                "ult_line_reason": cover.get("reason"),
                "lineup": sides is not None, "player_agent": player,
                "peaks": len(peaks), "selected": len(selected),
                "by_class": {c: by_class.get(c, 0) for c in CLASSES},
                "casts": sum(r["kind"] == "cast" for r in rows),
                "refusals": sum(r["kind"] == "refusal" for r in rows),
                "rounds": len(rounds)}
    return {"rows": [coverage] + rows, "claims": claims, "verdicts": verdicts,
            "events": events}
