r"""Which ultimate was cast, by which side, when: from stored voice-line peaks.

    .\.venv\Scripts\python.exe -m reticle ult-cast <session> | --all [--record]

Owns [owns:ult-cast].

Reads storage only: the `ult_line` peaks `ult_lines` stored, the lineup with
its board override (`lineup.load_lineup`), the rounds table, and the tray's
`tray_drop` rows with the HUD table that dates the player's deaths and the game
phase. It decodes nothing, so a change here reruns in seconds.

**Selection.** A peak is selected when its score reaches THRESHOLD, 0.0443,
formulation F-B's operating point in `prototypes/voice_lines.py`
[metric:voice_lines/evaluate-F-B@all-matches#tau_op=0.0443]: the score at which
lineup-impossible detections fall to a tenth per live minute
[metric:voice_lines/evaluate-F-B@all-matches#impossible_per_min=0.099], where
the player's own ultimates are found at
[metric:voice_lines/evaluate-F-B@all-matches#own_recall=0.667]. It was chosen
on the same 19 match sessions it is scored on, so those two numbers are fitted
values. Held out, it stands: picked on either alternate half, the point is
[metric:voice_lines/heldout-0.1.0@all-matches#tau_a=0.044322] or
[metric:voice_lines/heldout-0.1.0@all-matches#tau_b=0.044166], and the other
half's impossible rate is
[metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_a=0.0976]
or [metric:voice_lines/heldout-0.1.0@all-matches#heldout_impossible_per_min_b=0.1101]
per live minute (`docs/VOICE_LINES.md`, "Held-out threshold"). Every peak above
it stays: two templates that peak at one onset are two selections
(`docs/VOICE_LINES.md`, "Verdicts at 0.2.0").

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

**The tray.** The adjudicator asks `ability_timeline.player_tray_casts` which
stored tray drops are the player's casts (`player_x_drops`) and keeps the X
slot's drops with the owner's verdict; it restates none of the tray's rules.
An own selection binds to the nearest X cast whose drop lies within the
player's agent's cast window (`cast_window`): its `tray_witness` holds onset
minus drop, `dt_s`, and the drop's time, or is null with a reason. An
unwitnessed own line also stores the nearest X drop the owner refused within
the window, with the owner's reason (`tray_refused`), so the two channels'
disagreement is kept, not settled here. An X cast inside a round with no own
selection in its window is a `missed_line` row: the cast, its round, the
player's agent, and the best stored peak of the own template within the
window, which lies below THRESHOLD, or null with `no_peak_above_floor` when the
reader stored none there. The window binds two observations of one cast; it
selects nothing. A session without current tray drops, or without the player's
agent, binds nothing and says why in its coverage row.
"""
from __future__ import annotations

from collections import Counter

from ..version import ULT_CAST_VERSION
from .identity import (AGENT_IDENTITY_VERSION, adjudicate_agent_identity, identity_claim,
                       identity_events, player_identity)

#: A peak at or above this score is selected. See the module docstring for the
#: run that set it and the sessions it was chosen on.
THRESHOLD = 0.0443
#: The identity channel every claim from an ultimate's voice line is made on.
CHANNEL = "ult_line"
VARIANTS = ("ally", "enemy")
CLASSES = ("own", "possible", "impossible", "unknown")
#: The tray slot that holds the ultimate.
ULT_SLOT = "X"
#: An own line binds to an X cast when its onset minus the drop lies in the
#: player's agent's window, in seconds. Every agent: OWN_WINDOW_S either side,
#: since onset minus drop has a median of
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#onset_median_s=-0.43] s.
#: Phoenix: from 20 s before, because Run it Back's pips fall at expiry
#: [domain:abilities/phoenix-run-it-back-expiry-flash] while the caster hears
#: the line at the cast [domain:abilities/caster-hears-own-ult-line]. With
#: these windows the 0.2.0 prototype found
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#own_recall_agent_window=0.844]
#: of the player's X casts at THRESHOLD, against
#: [metric:voice_lines/evaluate-0.2.0-F-B-unsuppressed@all-matches#own_recall=0.667]
#: with 1.5 s for every agent. `prototypes/voice_lines.py` imports both.
OWN_WINDOW_S = 1.5
CAST_WINDOW = {"Phoenix": (-20.0, OWN_WINDOW_S)}
#: The fields `tray.drops` writes. The stored gate's fields stay behind, so the
#: owner decides afresh on the rounds this adjudicator reads.
DROP_FIELDS = ("t_ms", "slot", "from", "to", "suspect", "forced", "cooccur", "across_gap")


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
    """The player's agent, where the arbiter names it (`identity.player_identity`)."""
    agent = player_identity(lineup, session_id)["agent"]
    return _norm(agent) if agent else None


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
    from ..rounds import round_containing as owner_round
    r = owner_round(t_ms, rounds)
    return None if r is None else int(r["round_no"])


def cast_window(agent: str | None) -> tuple[float, float]:
    """(earliest, latest) onset minus X drop, in seconds, at which an own line
    of `agent` binds to the drop."""
    return CAST_WINDOW.get(agent, (-OWN_WINDOW_S, OWN_WINDOW_S))


def player_x_drops(drop_rows: list[dict], phase_of, rounds: list[dict],
                   player_deaths_ms: list[float], **gate) -> list[dict]:
    """The X-slot drops among a session's stored `tray_drop` rows, each with the
    `player_cast` and `reason` that `ability_timeline.player_tray_casts` gives
    it. Every slot's drops go in, because the owner's co-occurrence test reads
    them all. `gate` carries the owner's other inputs, as
    `ability_timeline.stored_gate_inputs` reads them."""
    from ..ability_timeline import player_tray_casts
    drops = [{k: r[k] for k in DROP_FIELDS if k in r} for r in drop_rows
             if r.get("kind") == "drop"]
    return [r for r in player_tray_casts(drops, phase_of, rounds, player_deaths_ms, **gate)
            if r["slot"] == ULT_SLOT]


def in_window(onset_ms: float, cast_ms: float, window: tuple[float, float]) -> bool:
    """Whether onset minus drop lies in `window` (seconds)."""
    return window[0] <= (onset_ms - cast_ms) / 1000.0 <= window[1]


def nearest_cast(t_ms: float, casts_ms: list[float],
                 window: tuple[float, float]) -> dict | None:
    """The X cast nearest a line's onset among those whose onset minus drop lies
    in `window`, as {dt_s, cast_t_ms}, or None."""
    near = [(abs(t_ms - c), c) for c in casts_ms if in_window(t_ms, c, window)]
    if not near:
        return None
    c = min(near)[1]
    return {"dt_s": round((t_ms - c) / 1000.0, 3), "cast_t_ms": c}


def adjudicate(session_id: str, peak_rows: list[dict], lineup: dict | None,
               rounds: list[dict], round_version: str | None,
               threshold: float = THRESHOLD, tray_drops: list[dict] | None = None,
               tray_reason: str | None = "no_tray_drops",
               tray_inputs: dict | None = None) -> dict:
    """The session's stored rows, its claims, the arbiter's verdicts and the
    formal identity events, from stored peaks, the lineup and the rounds.

    `tray_drops` are the X drops with the owner's verdict from
    `player_x_drops`, or None with `tray_reason`; `tray_inputs` are their
    stamps for the coverage row."""
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
    window = cast_window(player)
    if tray_drops is not None and player is None:
        tray_reason = "no_player_agent"
    bind = tray_drops is not None and player is not None
    tray_casts = [c for c in tray_drops if c["player_cast"]] if bind else []
    casts_ms = [float(c["t_ms"]) for c in tray_casts]
    refused = {float(c["t_ms"]): c["reason"] for c in tray_drops or [] if not c["player_cast"]}
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
            if m["class"] == "own":
                w = nearest_cast(m["t_ms"], casts_ms, window) if bind else None
                rows[-1]["tray_witness"] = w
                rows[-1]["tray_witness_reason"] = (
                    None if w else "no_x_cast_in_window" if bind else tray_reason)
                if bind and w is None:
                    r = nearest_cast(m["t_ms"], list(refused), window)
                    rows[-1]["tray_refused"] = None if r is None else {
                        "dt_s": r["dt_s"], "drop_t_ms": r["cast_t_ms"],
                        "reason": refused[r["cast_t_ms"]]}
        events += identity_events([v], session_id, m["t_ms"])

    # The player's X casts inside a round with no own selection in their window.
    missed, outside = [], 0
    own_tpl = f"{player}_ult_ally"
    own_ms = [r["t_ms"] for r in rows if r["kind"] == "cast" and r["class"] == "own"]
    own_peaks = [p for p in peaks if p["template"] == own_tpl]
    for c in tray_casts:
        t = float(c["t_ms"])
        rnd = round_of(t, rounds)
        if rnd is None:
            outside += 1
            continue
        if any(in_window(o, t, window) for o in own_ms):
            continue
        inside = [p for p in own_peaks if in_window(p["t_s"] * 1000.0, t, window)]
        best = max(inside, key=lambda p: (p["score"], -p["t_s"]), default=None)
        missed.append({
            **common, "kind": "missed_line", "t_ms": t, "cast_t_ms": t, "round": rnd,
            "player_agent": player, "template": own_tpl, "window_s": list(window),
            "tray": {k: c.get(k) for k in ("from", "to", "suspect", "cooccur", "forced",
                                           "across_gap")},
            "best_peak": None if best is None else {
                "score": best["score"], "floor": best.get("floor"), "t_s": best["t_s"],
                "dt_s": round(best["t_s"] - t / 1000.0, 3)},
            "best_peak_reason": None if best else "no_peak_above_floor"})
    rows += missed

    by_class = Counter(r["class"] for r in rows if r["kind"] in ("cast", "refusal"))
    own_rows = [r for r in rows if r["kind"] == "cast" and r["class"] == "own"]
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
                "rounds": len(rounds),
                "tray": {"bound": bind, "reason": None if bind else tray_reason,
                         "x_drops": len(tray_drops) if tray_drops is not None else None,
                         "player_x_casts": (sum(c["player_cast"] for c in tray_drops)
                                            if tray_drops is not None else None),
                         "casts_outside_round": outside, "window_s": list(window)},
                "own_witnessed": sum(r["tray_witness"] is not None for r in own_rows),
                "own_unwitnessed": sum(r["tray_witness"] is None for r in own_rows),
                "own_beside_refused_drop": dict(sorted(Counter(
                    r["tray_refused"]["reason"] for r in own_rows
                    if r.get("tray_refused")).items())),
                "missed_lines": len(missed),
                "missed_with_peak": sum(r["best_peak"] is not None for r in missed)}
    coverage["inputs"].update(tray_inputs or {})
    return {"rows": [coverage] + rows, "claims": claims, "verdicts": verdicts,
            "events": events}
