"""Causal origin/continuity adjudication over stored minimap observations.

An unexplained appearance is quarantined from the inferred entity channel, not
deleted from observations. A lighting contradiction does not establish which
detector failed. Pings may originate in darkness; an existing entity may persist
there. A corroborated teleport is a relocation, never a new player birth.

**A missing observation is not a missing entity**, and that applies to this
module's own inputs: an absent widget suspends adjudication rather than ending
every lifetime, and only elapsed time past the gap budget makes a boundary.
The motion law and the teleport rule are `track`'s -- restating either here is
how they drifted apart the first time.
"""
from __future__ import annotations

import math

from .track import CLASSES, Corroboration, admits, association_tolerance, corroborates_teleport

LIFECYCLE_VERSION = "minimap-lifecycle-0.2.0"

#: What each role may do between two observations, as a `track.CLASSES` key.
#: The motion law is not restated here -- `track.admits` owns it, and the two
#: had already drifted: this module's continuation ceiling was `RUN_PX*dt +
#: sqrt(2)`, which at 60 Hz is 2.2 px against the tracker's 4.8, so it
#: quarantined appearances the tracker had already associated and called them
#: unexplained.
ROLE_MOTION = {"ally": "walker", "self": "walker", "enemy": "walker",
               "ping": "static", "ability": "static", "death_mark": "static",
               "last_known": "static"}
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
            # One rule, in `track.corroborates_teleport`: audio alone also
            # describes a FAKE teleport, so the icon and the viewcone must both
            # have relocated and something must tie that to a predecessor.
            if not corroborates_teleport(Corroboration.of(event))[0]:
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

    def _expire(self, t_ms):
        """Drop anchors older than the gap budget; a boundary is what remains.

        Continuity ends on ELAPSED TIME and nothing else -- the same law
        `track.Tracker` expires on, and the same budget.
        """
        self.anchors = [a for a in self.anchors if t_ms - a["t_ms"] <= self.max_gap_ms]
        live = {a["entity_id"] for a in self.anchors}
        self.known = {k: v for k, v in self.known.items() if v["entity_id"] in live}
        if not self.anchors:
            self.boundary = True

    def step(self, frame, events=()):
        t_ms = frame["t_ms"]
        if not math.isfinite(t_ms) or (self.last_t is not None and t_ms <= self.last_t):
            raise ValueError("lifecycle timestamps must be finite and increasing")
        self.last_t = t_ms
        if frame["widget"] != "drawn":
            # **A missing widget is a missing OBSERVATION, not a missing
            # entity.** The death screen and the M key remove the widget for
            # 5% of a session's frames, and wiping identity on each of them
            # made every reappearance a fresh birth -- the fault this module
            # exists to catch, committed by this module. The tracker already
            # carries its tracks across the same frames; now so does this.
            # Elapsed time still expires them, below.
            self._expire(t_ms)
            return []
        self._expire(t_ms)
        output, additions, used_events = [], [], set()
        for obs in frame.get("observations", []):
            if obs["position_state"] != "observed":
                continue
            key = f"{obs['role']}:{obs['track_id']}"
            light = light_state(obs, frame.get("light_budget"))
            matches = matching_events(obs, t_ms, events)
            parents = set()
            # Static entities cannot acquire walking motion by association;
            # the class per role says so, and `track.admits` applies it.
            motion = CLASSES[ROLE_MOTION.get(obs["role"], "static")]
            for anchor in self.anchors:
                if anchor["role"] != obs["role"]:
                    continue
                dt = (t_ms - anchor["t_ms"]) / 1000
                dist = math.hypot(obs["x"] - anchor["x"], obs["y"] - anchor["y"])
                slack = association_tolerance(self.scale, r_a=obs.get("r"),
                                              r_b=anchor.get("r"))
                if admits(motion, max(0.0, dist - slack), dt, self.scale)[0]:
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
                   "r": obs.get("r"),
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
