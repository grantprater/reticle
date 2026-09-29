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

**A refusal names its rule and can heal** (0.3.0, `Lifecycle`): a per-role
boundary, one continuation per entity, second witnesses that do not read the
minimap (the roster's count, the player's death and spectate state), and
round-start and revive origin events. `adjudication_record` is the stored
form of each verdict.

Owns [owns:minimap-origin].
"""
from __future__ import annotations

import bisect
import math
from dataclasses import dataclass, field

from .track import CLASSES, Corroboration, admits, association_tolerance, corroborates_teleport

#: 0.3.0: a per-role boundary, one continuation per entity, second witnesses
#: (`Witnesses`), round-start and revive origin events, and a named refusal
#: (`reason_code`) on every refused row.
LIFECYCLE_VERSION = "minimap-lifecycle-0.3.0"

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


def round_start_events(rounds, width: float, height: float) -> list[dict]:
    """A `round_start` origin event per round and role, from the HUD's bounds.

    `rounds` are `rounds.build_rounds` rows (owner `rounds`, `round-bounds`):
    the start is the clock reset, observed at `t_start_ms`, so no icon may use
    the event before then (`available_t_ms`). The spawn places are not baked,
    so the event reaches the whole widget and its `capacity` bounds it: the
    four allies and the player.
    """
    diag = math.hypot(width, height)
    out = []
    for r in rounds:
        t0 = r.get("t_start_ms")
        if t0 is None:
            continue
        for role, cap in ROUND_START_CAPACITY.items():
            out.append({"id": f"round_start:{r.get('round_no')}:{role}", "kind": "round_start",
                        "role": role, "legal": True, "capacity": cap,
                        "t_start_ms": float(t0) - ROUND_START_BEFORE_MS,
                        "t_end_ms": float(t0) + ROUND_START_AFTER_MS,
                        "available_t_ms": float(t0), "x": width / 2, "y": height / 2,
                        "radius_px": diag,
                        "evidence_refs": [f"rounds:round_no={r.get('round_no')}:t_start_ms={t0}"]})
    return out


def revive_events(deaths, width: float, height: float) -> list[dict]:
    """A `revive` origin event per stored revive verdict of the ally side.

    `deaths` are `adjudication.death` rows; a `death_verdict` with
    `is_revive` is a revive's killfeed entry, available from its `t_ms`. The
    revived teammate's place is not read here, so the event reaches the whole
    widget and explains one icon.
    """
    diag = math.hypot(width, height)
    return [{"id": f"revive:{r['death_id']}", "kind": "revive", "role": "ally", "legal": True,
             "capacity": 1, "t_start_ms": float(r["t_ms"]),
             "t_end_ms": float(r["t_ms"]) + REVIVE_MATCH_MS,
             "available_t_ms": float(r["t_ms"]), "x": width / 2, "y": height / 2,
             "radius_px": diag, "evidence_refs": [r["death_id"]]}
            for r in deaths
            if r.get("kind") == "death_verdict" and r.get("is_revive") and r.get("side") == "ally"]


def adjudication_record(row: dict) -> dict:
    """One observed icon's verdict as `team_vision` stores it beside `icons`.

    Joined to its icon by `key` (`role:track_id`); the frame's time and the
    icon's position are not repeated. Fields: `entity_id`, `state`,
    `eligible`, `boundary` (`global` or `role` for a censored row),
    `reason_code` and `reason` (see `Lifecycle`; on an admitted row, the
    refusal its witness overcame), `nearest_anchor`, `refused_as`,
    `admitted_by`, `rests_on` (the ownership ids a verdict rests on),
    `origin_event_id`, `alternatives`, `light_state`, `conflict`.
    """
    return {"key": row["observation_key"], "entity_id": row["entity_id"],
            "state": row["state"], "eligible": bool(row["eligible"]),
            "boundary": row.get("boundary"), "reason_code": row.get("reason_code"),
            "reason": row.get("reason"), "nearest_anchor": row.get("nearest_anchor"),
            "refused_as": row.get("refused_as"), "admitted_by": row.get("admitted_by"),
            "rests_on": list(row.get("rests_on") or []),
            "origin_event_id": row.get("origin_event_id"),
            "alternatives": list(row.get("alternatives") or []),
            "light_state": row.get("light_state"), "conflict": row.get("conflict")}


#: States a second witness may lift. `left_censored` at a ROLE boundary is
#: vetoed by the roster the same way (`Lifecycle._corroborate`).
UNEXPLAINED = ("unexplained_appearance", "unlit_unexplained_appearance")
#: A spectated teammate drawn as the yellow icon anchors under this role, so
#: the player's own icon never continues it and it never continues the player.
SPECTATED = "spectated"
#: The HUD's round start is the clock reset (`rounds.round_bounds`); the team's
#: icons are redrawn at spawn in the seconds around it. Measured on the E8
#: replays of 5822b6646448 and c40d950031bb: track births cluster from about
#: 1.6 s before the reset to the reset itself. Not a domain fact.
ROUND_START_BEFORE_MS = 3000.0
ROUND_START_AFTER_MS = 1000.0
#: A revived teammate's icon returns within this of the revive's killfeed
#: entry. Unmeasured: no scored session holds a revive.
REVIVE_MATCH_MS = 3000.0
#: How many icons one origin event may explain in one frame, per role.
ROUND_START_CAPACITY = {"ally": 4, "self": 1}


def _anchor_role(row):
    return row.get("anchor_role") or row["role"]


@dataclass
class Witnesses:
    """Channels that count the team without reading the minimap.

    Pure over what the caller passes. `roster` is `(t_ms, alive_ally)` reads,
    the player included (owner `roster`, question `alive-count`), and
    `roster_lag_ms` the owner's lag (`round_entities.ROSTER_LAG_MS`), applied
    causally: the reads in `[t - lag, t]` and the read in force before them,
    never a read after `t`. `dead` answers `at(t_ms)` with the player's dead
    interval or None (owner `adjudication.spectate`, question `player-dead`:
    an interval has `holds`, `spectated` and `row()`). An absent witness
    admits nothing and refuses nothing. `versions` names each input's stamp
    for the stored coverage row.
    """

    roster: list = field(default_factory=list)
    roster_lag_ms: float = 500.0
    dead: object = None
    versions: dict = field(default_factory=dict)

    def __post_init__(self):
        self.roster = sorted((float(t), a) for t, a in self.roster)
        self._rt = [t for t, _a in self.roster]

    def roster_reads(self, t_ms: float) -> list:
        lo = max(0, bisect.bisect_right(self._rt, t_ms - self.roster_lag_ms) - 1)
        hi = bisect.bisect_right(self._rt, t_ms)
        return self.roster[lo:hi]

    def player(self, t_ms: float) -> tuple[str, dict | None]:
        """`alive`, `death_camera`, `spectating` or `unknown`, with evidence.

        With the death owner's intervals, a time outside every interval is
        the player alive: the owner ends the self track at his death and
        resumes it at the next round's start. Without them only the roster
        can say: five allies alive include the player.
        """
        if self.dead is not None:
            iv = self.dead.at(t_ms)
            if iv is None:
                return "alive", {"rule": "no_dead_interval"}
            return ("spectating" if iv.spectated(t_ms) else "death_camera"), iv.row()
        reads = [a for _t, a in self.roster_reads(t_ms) if a is not None]
        if reads and max(reads) >= 5:
            return "alive", {"rule": "roster_all_alive", "roster_reads": self.roster_reads(t_ms)}
        return "unknown", None


class Lifecycle:
    """Candidate lifecycle graph with explicit censored boundaries and refusals.

    Track IDs are detector associations. Short-gap geometric predecessors are
    reported as alternatives; multiple parents never silently merge identities.
    Persistence of a quarantined candidate cannot corroborate itself.

    **A refusal is re-read every frame, and says which rule refused it.** E8
    of docs/STATISTICAL_ADJUDICATOR.md found every quarantined row carrying one
    reason string, and 95% of them inherited from a refusal that could not
    heal: a quarantined key is no anchor, and the boundary that admits an
    appearance opened only when no anchor of ANY role was live, so one live
    self anchor kept a lost ally quarantined for its track's life. Four rules
    answer it (0.3.0):

    * the boundary is also per ROLE: an appearance of a role with no live
      anchor is `left_censored` with `boundary: "role"`, as the first frame
      is, and a quarantined key of that role is re-admitted by it;
    * an entity continues through one observation per frame: a key that
      continues its own entity holds it, and no other key within reach of
      the same anchor takes that identity;
    * a second witness that does not read the minimap (`Witnesses`) is asked
      of every refused row, every frame (`_corroborate`);
    * `round_start` and `revive` origin events (`round_start_events`,
      `revive_events`) explain appearances, `capacity` icons per frame each.

    Every refused row names its rule in `reason_code`: `beyond_reach`
    (anchors of its role live, none admits it), `ambiguous`,
    `over_capacity`, `death_camera`, or `persisting:<code>` for a key refused
    since an earlier frame. `nearest_anchor` says how far the nearest live
    anchor of its role was.
    """

    def __init__(self, scale=1.0, max_gap_ms=500.0, witnesses: Witnesses | None = None):
        self.scale, self.max_gap_ms = scale, max_gap_ms
        self.witnesses = witnesses
        self.last_t = None
        self.boundary = True
        self.known = {}
        self.anchors = []
        #: The last refused row per key, while the key is observed within the
        #: gap budget: what makes a refusal `persisting`.
        self.refused: dict = {}
        self.history: list[dict] = []

    def _expire(self, t_ms):
        """Drop anchors older than the gap budget; a boundary is what remains.

        Continuity ends on ELAPSED TIME and nothing else -- the same law
        `track.Tracker` expires on, and the same budget.
        """
        self.anchors = [a for a in self.anchors if t_ms - a["t_ms"] <= self.max_gap_ms]
        live = {a["entity_id"] for a in self.anchors}
        self.known = {k: v for k, v in self.known.items() if v["entity_id"] in live}
        self.refused = {k: v for k, v in self.refused.items()
                        if t_ms - v["t_ms"] <= self.max_gap_ms}
        if not self.anchors:
            self.boundary = True

    def _reach(self, obs, anchor, t_ms):
        """`(admitted, excess_px, dist_px, dt_ms)` of an anchor under `track.admits`."""
        motion = CLASSES[ROLE_MOTION.get(obs["role"], "static")]
        dt = (t_ms - anchor["t_ms"]) / 1000
        dist = math.hypot(obs["x"] - anchor["x"], obs["y"] - anchor["y"])
        slack = association_tolerance(self.scale, r_a=obs.get("r"), r_b=anchor.get("r"))
        ok = admits(motion, max(0.0, dist - slack), dt, self.scale)[0]
        walk = (motion.max_px_s or 0.0) * self.scale * dt
        return ok, dist - slack - walk, dist, t_ms - anchor["t_ms"]

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
        live = list(self.anchors)
        live_roles = {_anchor_role(a) for a in live}
        cands = []
        for obs in frame.get("observations", []):
            if obs["position_state"] != "observed":
                continue
            key = f"{obs['role']}:{obs['track_id']}"
            parents, nearest = set(), None
            # Static entities cannot acquire walking motion by association;
            # the class per role says so, and `track.admits` applies it.
            for anchor in live:
                if _anchor_role(anchor) != obs["role"]:
                    continue
                ok, excess, dist, dt = self._reach(obs, anchor, t_ms)
                if ok:
                    parents.add(anchor["entity_id"])
                if nearest is None or excess < nearest["excess"]:
                    nearest = {"dist": round(dist, 2), "dt_ms": round(dt, 1),
                               "excess": round(excess, 2), "entity": anchor["entity_id"]}
            old = self.known.get(key)
            own = (old["entity_id"] if old and old["eligible"] and old["entity_id"] in parents
                   else None)
            cands.append((obs, key, parents, own, nearest))
        # **An entity continues through one observation.** A key continuing
        # its own entity holds it; another key within reach of the same anchor
        # is not a second continuation of it. Taking a neighbour's identity
        # was the only way a quarantined key used to heal.
        claimed = {own for *_x, own, _n in cands if own is not None}
        output, used = [], {}
        for obs, key, parents, own, nearest in cands:
            if own is None:
                parents = parents - claimed
            light = light_state(obs, frame.get("light_budget"))
            matches = matching_events(obs, t_ms, events)
            accepted_event = next((e for e in matches
                                   if used.get(e["id"], 0) < int(e.get("capacity", 1))
                                   and (e["kind"] != "teleport"
                                        or any(a["entity_id"] == e["predecessor"]
                                               for a in live))), None)
            event_id, origin_ms, boundary = None, None, None
            if own is not None:
                entity, state, eligible = own, "continuation", True
            elif accepted_event:
                event_id = accepted_event["id"]
                used[event_id] = used.get(event_id, 0) + 1
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
                entity, state, eligible, boundary = key, "left_censored", True, "global"
            elif obs["role"] not in live_roles:
                entity, state, eligible, boundary = key, "left_censored", True, "role"
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
            code = None
            if not eligible:
                code = "ambiguous" if state == "ambiguous_continuation" else "beyond_reach"
                prev = self.refused.get(key)
                if prev is not None:
                    base = prev["reason_code"] or code
                    code = base if base.startswith("persisting:") else "persisting:" + base
            output.append({"observation_key": key, "t_ms": t_ms, "x": obs["x"], "y": obs["y"],
                           "r": obs.get("r"),
                           "role": obs["role"], "entity_id": entity, "state": state,
                           "eligible": eligible, "light_state": light, "conflict": conflict,
                           "alternatives": sorted(parents), "origin_event_id": event_id,
                           "origin_interval_ms": origin_ms, "boundary": boundary,
                           "reason_code": code, "nearest_anchor": nearest,
                           "refused_as": None, "admitted_by": None, "rests_on": [],
                           "reason": None if eligible else
                           f"{code}: origin or continuity needs corroboration"})
        self._corroborate(output, t_ms)
        for row in output:
            key = row["observation_key"]
            if row["eligible"]:
                self.refused.pop(key, None)
            else:
                self.refused[key] = row
            self.history.append(row)
            self.known[key] = row
            if row["eligible"]:
                self.anchors.append(row)
        self.boundary = False
        return output

    def _corroborate(self, rows, t_ms):
        """Ask the second witnesses of this frame's rows; see `Witnesses`.

        * **ally, by the roster**: `round_lifetimes.ally_capacity` licenses a
          number of ally icons; where every ally observed this frame fits it,
          a refused unexplained ally is `corroborated_appearance`; where more
          are observed, none of the unexplained or role-censored ones is
          admitted (`over_capacity`), because the count cannot say which is
          not a teammate. An unread roster, or an unobserved player icon,
          changes nothing.
        * **self, by the player's state**: alive admits a refused unexplained
          self icon; during the death camera the yellow icon is the camera's
          view of his place, not a live position (`death_camera_view`);
          while spectating it is the spectated teammate
          (`spectated_teammate`), whose cone is team vision, anchored apart
          from the player [domain:minimap/spectated-self-icon].

        An admitted row keeps the stock state in `refused_as`, its evidence
        in `admitted_by`, and what it rests on in `rests_on`; nothing earlier
        is rewritten.
        """
        w = self.witnesses
        if w is None:
            return
        from .round_lifetimes import ally_capacity
        allies = [r for r in rows if r["role"] == "ally"]
        selves = [r for r in rows if r["role"] == "self"]
        reads = w.roster_reads(t_ms)
        cap = ally_capacity([a for _t, a in reads], bool(selves)) if reads else None
        for r in allies:
            role_censored = r["boundary"] == "role"
            if not (r["state"] in UNEXPLAINED or role_censored):
                continue
            if cap is not None and len(allies) > cap:
                if r["eligible"]:
                    r.update(refused_as=r["state"], state="unexplained_appearance",
                             eligible=False)
                r.update(reason_code="over_capacity", rests_on=["alive-count"],
                         reason=f"{len(allies)} allies observed, the roster licenses {cap}")
            elif cap is not None and not r["eligible"]:
                r.update(refused_as=r["state"], state="corroborated_appearance", eligible=True,
                         reason=None, rests_on=["alive-count"],
                         admitted_by={"rule": "roster_capacity", "capacity": cap,
                                      "allies_observed": len(allies),
                                      "roster_reads": [list(x) for x in reads]})
            elif not r["eligible"]:
                r["reason"] = (f"{r['reason_code']}: roster unread or the player's icon "
                               "unobserved; origin or continuity needs corroboration")
        if not selves:
            return
        state, evidence = w.player(t_ms)
        rests = ["player-dead"] if w.dead is not None else ["alive-count"]
        for r in selves:
            if state == "spectating":
                r.update(refused_as=None if r["eligible"] else r["state"],
                         state="spectated_teammate", eligible=True, reason=None,
                         entity_id=f"{SPECTATED}:{r['observation_key']}", anchor_role=SPECTATED,
                         rests_on=["player-dead"],
                         admitted_by={"rule": "spectated_teammate", "interval": evidence})
            elif state == "death_camera":
                r.update(refused_as=r["state"], state="death_camera_view", eligible=False,
                         reason_code="death_camera", rests_on=["player-dead"],
                         reason="the death camera's view of the player's place, not a live icon",
                         admitted_by=None)
            elif state == "alive" and not r["eligible"] and r["state"] in UNEXPLAINED:
                r.update(refused_as=r["state"], state="corroborated_appearance", eligible=True,
                         reason=None, rests_on=rests,
                         admitted_by={"rule": "player_alive", "evidence": evidence})

    def events(self, session_id: str, transitions_only: bool = True) -> list[dict]:
        """Return formal CAUSAL_ORIGIN events.

        By default, transitions_only=True returns origin events: appearances,
        relocations, boundary onsets, and re-associations. Setting
        transitions_only=False returns events for every observation frame.
        """
        out = []
        seen_keys = set()
        for row in self.history:
            if transitions_only:
                key = row.get("observation_key")
                is_origin = (
                    key not in seen_keys
                    or row["state"] != "continuation"
                )
                seen_keys.add(key)
                if not is_origin:
                    continue
            out.append(lifecycle_row_to_event(row, session_id))
        return out


def lifecycle_row_to_event(row: dict, session_id: str) -> dict:
    """Convert a Lifecycle step row into a formal CAUSAL_ORIGIN event."""
    from .events import causal_origin_event, CausalOriginKind, SourceChannel

    origin_kind = CausalOriginKind(row["state"])
    return causal_origin_event(
        session_id=session_id,
        entity_id=f"lifecycle:{row['role']}:{row['entity_id']}",
        t_ms=float(row["t_ms"]),
        origin_kind=origin_kind,
        source_channel=SourceChannel.MINIMAP_LIFECYCLE,
        producer_version=LIFECYCLE_VERSION,
        origin_event_id=row.get("origin_event_id"),
        origin_interval_ms=tuple(row["origin_interval_ms"]) if row.get("origin_interval_ms") else None,
        alternatives=row.get("alternatives", []),
        conflict=row.get("conflict"),
        eligible=row.get("eligible", True),
        metadata={
            "observation_key": row.get("observation_key"),
            "role": row.get("role"),
            "light_state": row.get("light_state"),
            "x": row.get("x"),
            "y": row.get("y"),
            "r": row.get("r"),
            "reason": row.get("reason"),
            "reason_code": row.get("reason_code"),
            "refused_as": row.get("refused_as"),
            "admitted_by": row.get("admitted_by"),
            "rests_on": row.get("rests_on") or [],
        },
    ).to_dict()

