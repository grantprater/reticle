"""Which agent each scoreboard row shows, and whether the game dimmed it as dead.

The reader (`reticle.scoreboard`) scores every portrait against the official
square agent art and stores the raw best, runner-up, margin and brightness gain.
This module decides which openings are trustworthy and what they say.

**The board is the unit of acceptance, not the row.** A board still fading in
draws live portraits at low contrast, which reads exactly like the dimming the
game applies to the dead [domain:rounds/scoreboard-dead-dimmed]. On
`a06f04a0059f` at 237500 ms four live allies read dim while the enemy rows,
still sliding in, failed the agent gate. So one failed row refuses the whole
opening, and a gain between the two bands refuses it as well.

**Measured on one round, so provisional.** Round 4 of `a06f04a0059f`, eight
openings: expanded rows scored 0.80-0.94 with margins of at least 0.30, and
misaligned rows at most 0.70 with margins of at most 0.23. Live gain was
0.84-0.95 and dimmed gain was 0.30-0.41. The cuts sit in those gaps; the
row identity also has to hold across openings, which the death witness checks
by requiring each side's five agents to be distinct.

**This module gates rows; it does not decide names.** Each gated row becomes
an `identity_claim` on channel `scoreboard_portrait`, and the name on a row is
`adjudication.identity`'s verdict. The distinct-agents test only accepts or
refuses an opening. Naming a side from the board belongs to
`identity.assign_side`, which needs the full per-agent score matrix this
reader does not yet store.

Owns [owns:scoreboard-row-agent].
"""
from __future__ import annotations

from collections import defaultdict

from .identity import BOARD_MARGIN_MIN, adjudicate_agent_identity, identity_claim

SCOREBOARD_AGENT_VERSION = "scoreboard-agent-0.2.0"

AGENT_SCORE_MIN = 0.75
AGENT_MARGIN_MIN = BOARD_MARGIN_MIN
DIM_GAIN_MAX = 0.60
LIT_GAIN_MIN = 0.75


def _row_state(row: dict) -> tuple[str | None, bool | None, str | None]:
    """(agent, dim, reason) for one stored row; a refused row names nothing."""
    if row.get("portrait_agent_reason"):
        return None, None, row["portrait_agent_reason"]
    score, margin, gain = (row.get("portrait_agent_score"),
                           row.get("portrait_agent_margin"), row.get("portrait_gain"))
    if score is None or margin is None or gain is None:
        return None, None, "portrait_agent_not_scored"
    if score < AGENT_SCORE_MIN:
        return None, None, f"agent_score_below_gate {score:.3f}"
    if margin < AGENT_MARGIN_MIN:
        return None, None, f"agent_margin_below_gate {margin:.3f}"
    if gain <= DIM_GAIN_MAX:
        return row["portrait_agent_best"], True, None
    if gain >= LIT_GAIN_MIN:
        return row["portrait_agent_best"], False, None
    return None, None, f"gain_between_bands {gain:.3f}"


def scoreboard_openings(rows: list[dict]) -> list[dict]:
    """Group stored row observations into openings and gate each one whole.

    An accepted opening names five distinct agents per side, each lit or dim.
    A refused one keeps its per-row reasons and names nothing.
    """
    by_t: dict[float, list[dict]] = defaultdict(list)
    for row in rows:
        if row.get("kind") == "row_observation":
            by_t[float(row["t_ms"])].append(row)
    out = []
    for t_ms in sorted(by_t):
        group = sorted(by_t[t_ms], key=lambda r: r["display_row"])
        states, claims = [], []
        for row in group:
            agent, dim, reason = _row_state(row)
            entity = f"scoreboard:{t_ms:.0f}:{row['team']}:row:{row['display_row']}"
            claims.append(identity_claim(
                entity, agent, channel="scoreboard_portrait", observed_at_ms=t_ms,
                reason=reason, source_version=row.get("scoreboard_version"),
                evidence={"observation_key": row.get("observation_key"),
                          "score": row.get("portrait_agent_score"),
                          "margin": row.get("portrait_agent_margin"),
                          "gain": row.get("portrait_gain")}))
            states.append({"observation_key": row.get("observation_key"),
                           "entity_id": entity,
                           "display_row": row["display_row"], "team": row["team"],
                           "agent": None, "dim": dim, "reason": reason,
                           "score": row.get("portrait_agent_score"),
                           "margin": row.get("portrait_agent_margin"),
                           "gain": row.get("portrait_gain"),
                           "scores": row.get("portrait_agent_scores")})
        named = {v["entity_id"]: v["agent"] for v in adjudicate_agent_identity(claims)}
        for state in states:
            state["agent"] = named.get(state["entity_id"])
        reason = None
        teams = [s["team"] for s in states]
        ally_y = [r["row_y0"] for r in group if r["team"] == "ally" and r.get("row_y0") is not None]
        enemy_y = [r["row_y0"] for r in group if r["team"] == "enemy" and r.get("row_y0") is not None]
        if teams.count("ally") != 5 or teams.count("enemy") != 5:
            reason = "not_five_rows_per_side"
        elif ally_y and enemy_y and min(enemy_y) <= max(ally_y):
            # The enemy block is drawn below the ally block. At 1999000 ms of
            # a06f04a0059f the reader placed the enemy rows ON the ally rows
            # and read the ally portraits twice -- a reader defect this gate
            # refuses rather than names.
            reason = "enemy_rows_not_below_ally_rows"
        elif any(s["reason"] for s in states):
            reason = "row_refused"
        else:
            for side in ("ally", "enemy"):
                names = [s["agent"] for s in states if s["team"] == side]
                if len(set(names)) != 5:
                    reason = f"{side}_agents_not_distinct"
        out.append({"t_ms": t_ms, "frame_idx": group[0].get("frame_idx"),
                    "accepted": reason is None, "reason": reason, "rows": states,
                    "claims": claims,
                    "source_version": group[0].get("scoreboard_version"),
                    "version": SCOREBOARD_AGENT_VERSION})
    return out


def side_state(opening: dict, side: str) -> dict[str, set[str]]:
    """The accepted opening's agents on one side, split into lit and dim."""
    rows = [s for s in opening["rows"] if s["team"] == side]
    return {"lit": {s["agent"] for s in rows if s["dim"] is False},
            "dim": {s["agent"] for s in rows if s["dim"] is True}}
