"""How each round ended: one claim per round, pooled from the strip's cells.

The reader (`reticle.round_outcome`) stores, per Tab frame, what each
column of the board's round-history strip shows: an outcome icon with its
reason scores, line and tint, or a refusal. This module combines every
frame's reading of one round into one claim, keeps the votes and the
disagreements, and refuses where the frames do not agree.

Which column is which round. Column N of the strip is game round N. A
stored round's `score_us + score_them` is the score before it, so it is
game round `score_us + score_them + 1`; a capture that starts mid-match
maps through the same sum. A stored round without both scores maps to no
column.

Which frames count. A column holds its round's icon only once the round
has ended; before that it shows dots, and the reader's false icons on
unplayed columns sit there. So a frame votes for round N only when it lies
after the stored round's end (`t_end_ms`, or `t_close_ms` when the end is
unread). Every vote is an `icon` cell with a named reason; an icon whose
reason margin was too thin votes for the winner only.

Rule (`pool_outcomes`). A round with no voting frame refuses `no_frames`;
with fewer than `MIN_FRAMES`, `few_frames`. The reason is the majority of
the reason votes when it holds at least `AGREE_MIN` of them, else the claim
refuses `frames_disagree` and keeps the votes. The winner is the majority
line under the same cut (`ally` the upper, the player's team). Tint and
line are two readings of one cell; a vote whose tint names the other side
counts in `tint_disagrees`. The stored round's `won` is never changed: the
claim records `won_stored` and `won_disagrees` beside its own winner.

Each claim carries `claim_id` (`<session>:round_outcome:<N>`), the stored
`round_no`, the frames it rests on (`evidence`, frame indices and times)
and its version `ROUND_OUTCOME_CLAIM_VERSION` beside the reader's.

Owns [owns:round-outcome].
"""
from __future__ import annotations

from collections import Counter

from ..version import ROUND_OUTCOME_CLAIM_VERSION

#: Least number of voting frames for a claim.
MIN_FRAMES = 2
#: Least share of the votes the majority reason (and line) must hold.
AGREE_MIN = 0.8


def game_round(stored: dict) -> int | None:
    """The strip column (game round, from 1) of a stored round, or None."""
    a, b = stored.get("score_us"), stored.get("score_them")
    if a is None or b is None:
        return None
    return int(a) + int(b) + 1


def _round_end(stored: dict) -> float | None:
    for k in ("t_end_ms", "t_close_ms"):
        if stored.get(k) is not None:
            return float(stored[k])
    return None


def _majority(votes: Counter) -> tuple[str | None, float]:
    n = sum(votes.values())
    if not n:
        return None, 0.0
    top, k = votes.most_common(1)[0]
    return top, k / n


def pool_outcomes(session_id: str, frame_rows, rounds) -> list[dict]:
    """One claim per stored round from the reader's `frame` rows.

    `frame_rows` are `round_outcome` rows of kind `frame` (`t_ms`,
    `frame_idx`, `cells`); `rounds` the stored rounds. Returns claims in
    round order; see the module docstring for the rule."""
    frames = sorted((r for r in frame_rows if r.get("kind") == "frame"),
                    key=lambda r: float(r["t_ms"]))
    reader_versions = sorted({r.get("round_outcome_version") for r in frames} - {None})
    by_round: dict[int, list] = {}                        # column -> [(t, frame, cell)]
    for fr in frames:
        for c in fr["cells"]:
            by_round.setdefault(c["round"], []).append((float(fr["t_ms"]), int(fr["frame_idx"]), c))
    claims = []
    for stored in sorted(rounds, key=lambda r: r["round_no"]):
        n = game_round(stored)
        end = _round_end(stored)
        base = {"session_id": session_id, "kind": "round_outcome_claim",
                "round_outcome_claim_version": ROUND_OUTCOME_CLAIM_VERSION,
                "round_outcome_version": reader_versions[0] if len(reader_versions) == 1 else reader_versions,
                "round_no": stored["round_no"], "game_round": n,
                "claim_id": f"{session_id}:round_outcome:{n}" if n else None,
                "t_end_ms": end, "won_stored": stored.get("won")}
        if n is None or end is None:
            claims.append({**base, "end_reason": None, "winner": None, "frames": 0,
                           "refusal": "round_unmapped" if n is None else "round_end_unread"})
            continue
        reasons, lines, tints = Counter(), Counter(), Counter()
        evidence, tint_dis, unread = [], 0, Counter()
        for t, f, cell in by_round.get(n, ()):           # an empty cell is not listed
            if t <= end:
                continue
            if cell["verdict"] != "icon":
                unread[cell.get("refusal") or "unread"] += 1
                continue
            lines[cell["line"]] += 1
            if cell.get("reason"):
                reasons[cell["reason"]] += 1
            if cell.get("tint"):
                tints[cell["tint"]] += 1
                if (cell["tint"] == "teal") != (cell["line"] == "ally"):
                    tint_dis += 1
            evidence.append([f, t])
        reason, r_share = _majority(reasons)
        winner, w_share = _majority(lines)
        votes = len(evidence)
        refusal = None
        if not votes:
            refusal = "no_frames"
        elif votes < MIN_FRAMES:
            refusal = "few_frames"
        elif r_share < AGREE_MIN or w_share < AGREE_MIN:
            refusal = "frames_disagree"
        won = None if winner is None else winner == "ally"
        claims.append({
            **base,
            "end_reason": None if refusal else reason,
            "winner": None if refusal else winner,
            "frames": votes, "reason_votes": dict(reasons), "line_votes": dict(lines),
            "tint_votes": dict(tints), "tint_disagrees": tint_dis,
            "reason_agree": round(r_share, 3), "line_agree": round(w_share, 3),
            "unread_cells": dict(unread),
            "won_disagrees": (None if refusal or won is None or stored.get("won") is None
                              else bool(won != stored["won"])),
            "t_first_ms": evidence[0][1] if evidence else None,
            "evidence": evidence, "refusal": refusal,
        })
    return claims
