"""Decide which stored minimap fits can represent drawn player icons.

Owns [owns:minimap-icon-disposition]. The reader measures shape and appearance;
this module decides gates, suppression, and map-furniture status. It never names
an agent.
"""

from __future__ import annotations

from collections import defaultdict
from math import hypot

from ..minimap import (ALLY_COV_MIN, ALLY_INNER_MAX, ALLY_MAP_DIFF_MIN,
                       MIN_ICON_SEPARATION_PX)

MINIMAP_ICON_DECISION_VERSION = "minimap-icon-decision-0.1.0"


def ally_decisions(rows: list[dict]) -> list[dict]:
    """Account for every fitted ally hypothesis from stored measurements."""
    groups = defaultdict(list)
    for row in rows:
        groups[(row["frame_idx"], row["channel"])].append(row)
    out = []
    for (_, channel), group in groups.items():
        kept = []
        for row in sorted(group, key=lambda r: -r["cov"]):
            reason = None
            preferred = None
            if row["cov"] < ALLY_COV_MIN or row["inner"] > ALLY_INNER_MAX:
                reason = "shape_gate"
            elif channel == "ally" and row["facing"] is None:
                reason = "facing_unread"
            else:
                preferred = next((k for k in kept if hypot(
                    row["cx"] - k["cx"], row["cy"] - k["cy"]) <
                    MIN_ICON_SEPARATION_PX * row["widget_scale"]), None)
                if preferred is not None:
                    reason = "nearer_fit_preferred"
            if channel == "self" and reason is None and kept:
                reason = "alternate_self_fit"
            if reason is None:
                kept.append(row)
            family = ("barrier" if reason is None and
                      channel == "ally" and
                      row.get("map_diff") is not None and
                      row["map_diff"] < ALLY_MAP_DIFF_MIN else channel)
            out.append({"kind": "decision", "candidate_key": row["candidate_key"],
                        "rule_version": MINIMAP_ICON_DECISION_VERSION,
                        "disposition": ("suppressed" if preferred is not None else
                                        "rejected" if reason else "accepted"),
                        "reason": reason or ("interior_is_map" if family == "barrier"
                                             else "eligible"),
                        "preferred_candidate_key": (preferred["candidate_key"]
                                                    if preferred else None),
                        "family": family if reason is None else None})
    return out


def accepted(rows: list[dict], decisions: list[dict]) -> list[dict]:
    by_key = {r["candidate_key"]: r for r in rows}
    return [dict(by_key[d["candidate_key"]], decision=d)
            for d in decisions if d["disposition"] == "accepted"]
