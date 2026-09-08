"""Causal origin/continuity adjudication over stored minimap observations.

An unexplained appearance is quarantined from the inferred entity channel, not
deleted from observations. A lighting contradiction does not establish which
detector failed. Pings may originate in darkness; an existing entity may persist
there. A corroborated teleport is a relocation, never a new player birth.
"""
from __future__ import annotations

import math

from .minimap import RUN_PX

LIFECYCLE_VERSION = "minimap-lifecycle-0.1.0"
LEGAL_ORIGINS = {
    "ping": {"ping"}, "ability": {"cast", "equip"},
    "ally": {"round_start", "revive"}, "self": {"round_start", "revive"},
    "enemy": {"reveal", "visibility_entry", "revive", "round_start"},
    "death_mark": {"death"}, "last_known": {"visibility_loss"},
}


def light_state(observation, budget):
    support = observation.get("light_support") or {}
    if not support.get("known") or support.get("lit") is None:
        return "unknown"
    if support["lit"] > 0:
        return "lit"
    # A globally failed lighting read cannot accuse every icon independently.
    if budget is None or not budget.get("lit"):
        return "unknown"
    return "unlit"


def matching_events(obs, t_ms, events):
    """Positive, spatially linked evidence only; absent events are not vetoes.

    Events carry observation availability separately from occurrence bounds.
    `legal` must be explicitly established by the event's producing channels.
    An equip/cast timestamp alone cannot establish a destination or caster.
    """
    result = []
    for event in events:
        if event.get("legal") is not True or not event.get("evidence_refs"):
            continue
        if event.get("role") != obs["role"]:
            continue
        if not (event["t_start_ms"] <= t_ms <= event.get("match_until_ms", event["t_end_ms"])
                and event["available_t_ms"] <= t_ms):
            continue
        if event.get("radius_px", -1) < 0:
            continue
        if math.hypot(obs["x"] - event["x"], obs["y"] - event["y"]) > event["radius_px"]:
            continue
        if event["kind"] == "teleport":
            # Audio alone also describes fake teleports. Require the relocated
            # icon AND relocated viewcone, plus source/destination corroboration.
            channels = set(event.get("channels", []))
            if not {"icon", "viewcone"}.issubset(channels):
                continue
            if not channels.intersection({"audio", "destination"}):
                continue
            if not event.get("predecessor"):
                continue
        elif event["kind"] not in LEGAL_ORIGINS.get(obs["role"], set()):
            continue
        result.append(event)
    return result


class Lifecycle:
    """Candidate lifecycle graph with explicit censored boundaries and refusals.

    Track IDs are detector associations. Short-gap geometric predecessors are
    reported as alternatives; multiple parents never silently merge identities.
    Persistence of a quarantined candidate cannot corroborate itself.
    """
    def __init__(self, scale=1.0, max_gap_ms=500.0):
        self.scale, self.max_gap_ms = scale, max_gap_ms
        self.last_t = None
        self.boundary = True
        self.known = {}
        self.anchors = []

    def step(self, frame, events=()):
        t_ms = frame["t_ms"]
        if not math.isfinite(t_ms) or (self.last_t is not None and t_ms <= self.last_t):
            raise ValueError("lifecycle timestamps must be finite and increasing")
        if self.last_t is not None and t_ms - self.last_t > self.max_gap_ms:
            self.boundary = True
            self.known.clear()
            self.anchors.clear()
        self.last_t = t_ms
        if frame["widget"] != "drawn":
            self.boundary = True
            self.known.clear()
            self.anchors.clear()
            return []
        self.anchors = [a for a in self.anchors if t_ms - a["t_ms"] <= self.max_gap_ms]
        output, additions, used_events = [], [], set()
        for obs in frame.get("observations", []):
            if obs["position_state"] != "observed":
                continue
            key = f"{obs['role']}:{obs['track_id']}"
            light = light_state(obs, frame.get("light_budget"))
            matches = matching_events(obs, t_ms, events)
            parents = set()
            for anchor in self.anchors:
                if anchor["role"] != obs["role"]:
                    continue
                dt = (t_ms - anchor["t_ms"]) / 1000
                ceiling = RUN_PX * self.scale * dt + math.sqrt(2)
                # Static entities cannot acquire walking motion by association.
                if obs["role"] in {"ping", "ability", "death_mark", "last_known"}:
                    ceiling = math.sqrt(2)
                if math.hypot(obs["x"] - anchor["x"], obs["y"] - anchor["y"]) <= ceiling:
                    parents.add(anchor["entity_id"])
            accepted_event = next((e for e in matches if e["id"] not in used_events
                                   and (e["kind"] != "teleport"
                                        or any(a["entity_id"] == e["predecessor"]
                                               for a in self.anchors))), None)
            old = self.known.get(key)
            event_id, origin_ms = None, None
            if old and old["eligible"] and old["entity_id"] in parents:
                entity, state, eligible = old["entity_id"], "continuation", True
            elif accepted_event:
                event_id = accepted_event["id"]
                used_events.add(event_id)
                entity = accepted_event.get("predecessor") or key
                state = "relocation" if accepted_event["kind"] == "teleport" else "explained_origin"
                eligible = True
                origin_ms = (None if state == "relocation" else
                             [accepted_event["t_start_ms"], accepted_event["t_end_ms"]])
            elif parents:
                entity = next(iter(parents)) if len(parents) == 1 else key
                state = "continuation" if len(parents) == 1 else "ambiguous_continuation"
                eligible = len(parents) == 1
            elif self.boundary:
                entity, state, eligible = key, "left_censored", True
            else:
                entity, state, eligible = key, "unexplained_appearance", False
            # A non-ping whose actual origin is supported contradicts lighting
            # when it begins in darkness; preserve BOTH pieces of evidence.
            conflict = None
            if light == "unlit" and obs["role"] != "ping":
                conflict = ("origin_vs_lighting" if accepted_event else
                            "nonping_vs_lighting")
                if state == "unexplained_appearance":
                    state = "unlit_unexplained_appearance"
            row = {"observation_key": key, "t_ms": t_ms, "x": obs["x"], "y": obs["y"],
                   "role": obs["role"], "entity_id": entity, "state": state,
                   "eligible": eligible, "light_state": light, "conflict": conflict,
                   "alternatives": sorted(parents), "origin_event_id": event_id,
                   "origin_interval_ms": origin_ms,
                   "reason": None if eligible else "origin or continuity needs corroboration"}
            output.append(row)
            self.known[key] = row
            if eligible:
                additions.append(row)
        self.anchors.extend(additions)
        self.boundary = False
        return output
