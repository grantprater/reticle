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
from ..spike import on_glyph

#: 0.2.0: a fit that lands on a stored spike glyph is rejected as
#: `on_spike_glyph`, after the shape gate and before facing and separation;
#: the frame's shape-gated fits of both channels are the icons a carried glyph
#: may belong to (`spike.on_glyph`).
#: 0.3.0: the stacked-icon search's members (channel `stack`, ally-icon-0.11.0)
#: are decided after the frame's ring fits (`_stack_decisions`); ring-fit
#: decisions are unchanged.
#: 0.4.0 (2026-10-06, self-spike-tracker-20260929's 0.3.0 renumbered): a
#: candidate that says `glyph_masked` (ally-icon-0.14.0) was fitted with every
#: dropped glyph's footprint removed from its key (`icon_prior.veto_for`), so
#: a dropped glyph beside it is no reason to refuse it: an icon standing on
#: the spike -- a teammate planting or defusing -- is kept. A carried glyph
#: still refuses a fit ringing it. The shape gate reads the coverage of the
#: ring the mask left visible (`cov_visible`) where the candidate carries it.
MINIMAP_ICON_DECISION_VERSION = "minimap-icon-decision-0.4.0"

#: A stacked-icon member within this share of the icon's outer radius of an
#: accepted ring fit (or the self fit) is that icon found again. Two
#: teammates drawn closer than half a radius are one shape: the probe read
#: the underneath portrait at that spacing on 0.03-0.5 of icons even at
#: Riot's own centre (`minimap-render-20261003`, S3).
SAME_ICON_FRAC = 0.5


def ally_decisions(rows: list[dict]) -> list[dict]:
    """Account for every fitted ally hypothesis from stored measurements."""
    groups = defaultdict(list)
    shaped = defaultdict(list)
    stack = defaultdict(list)
    for row in rows:
        if row["channel"] == "stack":
            stack[row["frame_idx"]].append(row)
            continue
        groups[(row["frame_idx"], row["channel"])].append(row)
        # Either channel's fit past the shape gate may carry a spike glyph.
        if row.get("cov_visible", row["cov"]) >= ALLY_COV_MIN and row["inner"] <= ALLY_INNER_MAX:
            shaped[row["frame_idx"]].append(row)
    out = []
    for (_, channel), group in groups.items():
        kept = []
        for row in sorted(group, key=lambda r: -r["cov"]):
            reason = None
            preferred = None
            glyphs = row.get("spike_glyphs") or []
            if "glyph_masked" in row:
                # ally-icon-0.14.0 masked every dropped glyph before the fit.
                glyphs = [g for g in glyphs if g.get("state") != "dropped"]
            if row.get("cov_visible", row["cov"]) < ALLY_COV_MIN or row["inner"] > ALLY_INNER_MAX:
                reason = "shape_gate"
            elif on_glyph(row["cx"], row["cy"], glyphs,
                          row["widget_scale"], shaped[row["frame_idx"]]) is not None:
                # The fit is the spike glyph (`spike.on_glyph`). Candidates
                # stored before ally-icon-0.5.0 carry no glyphs and pass.
                reason = "on_spike_glyph"
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
    if stack:
        verdict = {d["candidate_key"]: d for d in out}
        held = defaultdict(list)
        for row in rows:
            d = verdict.get(row["candidate_key"])
            if d is not None and d["disposition"] == "accepted":
                held[row["frame_idx"]].append((row, d["family"]))
        for f, members in stack.items():
            out += _stack_decisions(members, held[f], shaped[f])
    return out


def _stack_decisions(members: list[dict], held: list[tuple[dict, str]],
                     shaped: list[dict]) -> list[dict]:
    """One frame's stacked-icon members against its accepted fits `held`
    (row, family).

    In order: a member on a spike glyph is rejected (`on_spike_glyph`); one
    whose interior is the map (`map_diff` under `ALLY_MAP_DIFF_MIN`) is
    furniture (`interior_is_map`); one within `SAME_ICON_FRAC` of the icon's
    outer radius of an accepted fit of either channel is that icon
    (`same_icon_as_ring_fit`, naming it in `same_icon_candidate_key`). The
    rest are accepted by margin while the ring fit's teammates and the
    accepted members stay within the capacity the member rests on; the
    others are `over_capacity`.
    """
    out = []

    def decide(row, disposition, reason, family=None, same=None):
        out.append({"kind": "decision", "candidate_key": row["candidate_key"],
                    "rule_version": MINIMAP_ICON_DECISION_VERSION,
                    "disposition": disposition, "reason": reason,
                    "preferred_candidate_key": None, "family": family,
                    **({"same_icon_candidate_key": same} if same else {})})

    ring = sum(1 for _, fam in held if fam == "ally")
    room = None
    left = []
    for row in sorted(members, key=lambda r: -r["stack"]["margin"]):
        if room is None:
            room = (row["capacity"] or 0) - ring
        same = min(((hypot(row["cx"] - h["cx"], row["cy"] - h["cy"]), h["candidate_key"])
                    for h, _ in held), default=None)
        if on_glyph(row["cx"], row["cy"], row.get("spike_glyphs") or [],
                    row["widget_scale"], shaped) is not None:
            decide(row, "rejected", "on_spike_glyph")
        elif row["map_diff"] is not None and row["map_diff"] < ALLY_MAP_DIFF_MIN:
            decide(row, "rejected", "interior_is_map")
        elif same is not None and same[0] < SAME_ICON_FRAC * row["stack"]["r_out"]:
            decide(row, "rejected", "same_icon_as_ring_fit", same=same[1])
        else:
            left.append(row)
    for row in left:
        if room > 0:
            decide(row, "accepted", "eligible", family="ally")
            room -= 1
        else:
            decide(row, "rejected", "over_capacity")
    return out


def accepted(rows: list[dict], decisions: list[dict]) -> list[dict]:
    by_key = {r["candidate_key"]: r for r in rows}
    return [dict(by_key[d["candidate_key"]], decision=d)
            for d in decisions if d["disposition"] == "accepted"]
