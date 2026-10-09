"""The entity-event contract: the one schema every consumer reads.

`docs/ENTITY_EVENTS.md` is the plan; this module is its stage 0. It declares
the rows an entity lane holds and checks them, and it projects nothing: the
projection that fills the lanes is `entity_events`, stage 1.

Two outputs per lane
--------------------
A lane `<lane>` writes `entity_<lane>` (the **consumer output**) and
`entity_<lane>_ledger` (the **ledger**). Each file opens with a `stamp` row
whose key follows the store's `<stream>_version` convention, so
`Store.events_version` and `plan` read it unchanged.

- Consumer rows are `stamp`, `entity`, `event` and `coverage`. A consumer row
  is certain or absent: it carries no uncertainty field (`standing`,
  `alternatives`, `confidence`, a distribution, a status), and a name comes
  only from a resolved arbiter verdict, cited by `ref`.
- Ledger rows are `stamp` and `withheld`: the row an owner did not resolve,
  with its standing, the owner's own reason verbatim, the alternatives, the
  owner the question `returns_to`, and whether it is residual.

Unread values
-------------
Every field the contract lists is present. An unread value is `null`, and a
sibling `<field>_reason` says why, in one of four forms (`REASON_FORMS`):
`not_applicable`, `not_read: <owner reason>`, `not_observed: <cause>` or
`withheld: <ledger id>`.

Times
-----
`observed_ms` and `observed_last_ms` are media times of observations, and a
non-null one cites its evidence. An inferred time is `occurred`, or an
entity's `lifetime.began`/`ended`: an interval `{lo_ms, hi_ms, basis}` that
only an owner supplies. Any other time key is rejected, because it cannot say
which of the two it is. An `estimate` is never observed: its `observed_ms` is
null and its instant is `occurred`.

Between observations
--------------------
`between_observations` answers what a track shows while nothing observes it,
per family and kind, from the player's answer of 2026-09-30 (plan section 8):
an alive ally or self track shows its owner's `estimate`; an enemy track shows
an `estimate` until its icon becomes the red "?"
[domain:minimap/last-known-mark], then the `last_known` mark; every other
family shows `not_observed` coverage. A consumer never chooses.

State vocabularies
------------------
`STATE_VOCABULARY` types each event kind's `state`. An ability object's phases
come only from the `states` list of that ability's lifecycle facts in
`domain/abilities.toml`, never by analogy
[domain:abilities/ability-rules-are-unique]; an ability whose facts name no
lifecycle gets only `observed`, with the `no-fact:<agent>:<slot>:lifecycle`
reason `ability_state` already uses. The spike's states each cite their fact
(`SPIKE_STATES`).

The validator
-------------
`validate_lane(stream, rows)` returns `(index, message)` for each rejected row;
`store.write_events` calls it for every `entity_*` stream and refuses to write
a lane with any. Pass `verdicts` (arbiter `ref` -> status) to check that every
cited verdict is resolved; without it the check is structural.
"""
from __future__ import annotations

import functools
import re
from typing import Iterable, Mapping

ENTITY_CONTRACT_VERSION = "entity-contract-0.1.0"

#: A lane's consumer stream is `entity_<lane>`; its ledger adds this suffix.
STREAM_PREFIX = "entity_"
LEDGER_SUFFIX = "_ledger"

# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------

#: The spike's states, each with the fact that shows it. Defusal has no fact
#: and no owner yet, so it is no state: it joins with its fact.
SPIKE_STATES: dict[str, tuple[str, ...]] = {
    # base down on the ground [domain:minimap/spike-inversion]
    "dropped": ("minimap/spike-inversion",),
    # base up, over the carrier's icon [domain:minimap/spike-carrier-overlay]
    "carried": ("minimap/spike-inversion", "minimap/spike-carrier-overlay"),
    # its own rotated icon [domain:minimap/spike-planted-icon]
    "planted": ("minimap/spike-planted-icon",),
    # the killfeed's hexagon entry [domain:killfeed/environmental-self-entry]
    "detonated": ("killfeed/environmental-self-entry",),
    # a spike on the ground outside the team's vision, drawn as its last-known
    # mark [domain:minimap/enemy-spike-ground-vision]
    "last_known": ("minimap/enemy-spike-ground-vision",),
}

#: The ping owner's kinds (`ping.PING_TYPES`); a test pins the two together,
#: since this foundation module may not import a reader.
PING_KINDS = frozenset({"standard", "need_help", "on_my_way", "watching_here", "danger"})

#: Tray slots.
SLOTS = frozenset({"C", "Q", "E", "X"})

#: `family` -> the kinds it admits; None admits any non-empty string (an
#: ability object's kind is its ability).
FAMILIES: dict[str, frozenset | None] = {
    "player": frozenset({"self", "ally", "enemy"}),
    # after the player's death the self icon is the spectated teammate's, its
    # own entity [domain:minimap/self-icon-shows-spectated]
    "icon_track": frozenset({"ally", "enemy", "self", "spectated"}),
    "ability_object": None,
    "spike": frozenset({"spike"}),
    "ping": PING_KINDS,
    "mark": frozenset({"death", "last_known"}),
    # buy-phase barriers [domain:rounds/buy-phase-barriers]
    "furniture": frozenset({"barrier"}),
}

#: Sides are the team's, not attack and defence, which swap at halftime
#: [domain:rounds/halftime-side-swap].
SIDES = frozenset({"ally", "enemy"})

ENTITY_KEYS = ("row", "entity_id", "family", "kind", "side", "round", "lifetime",
               "identity", "player", "producer", "lane", "contract")
#: `reality`: the detection-reality owner's answer on a track a lane assesses
#: (`round_lifetimes.detection_reality`): `{hypothesis, rule}` where it
#: accepted the track as a drawn player, else null with its reason, so a
#: consumer tells an unassessed track from an accepted one. Optional: a lane
#: that does not apply the rule omits it, and rows written before it validate.
ENTITY_OPTIONAL = ("reality",)
LIFETIME_KEYS = ("first_observed_ms", "last_observed_ms", "began", "ended",
                 "censored_at_ms")

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

EVENT_KEYS = ("row", "event_id", "entity_id", "kind", "round", "observed_ms",
              "observed_last_ms", "occurred", "position", "orientation", "state",
              "evidence", "producer", "lane", "contract")
#: `player` binds the event to a player entity where the binding owner stored
#: the slot key; `participants` maps a role (killer, pinger, planter) to
#: `{entity_id, identity}`, or to null with its reason.
EVENT_OPTIONAL = ("identity", "player", "participants", "round_ms")
#: The only time keys an event holds. `round_ms` is `gametime`'s round clock,
#: carried when that owner stores it.
TIME_KEYS = frozenset({"observed_ms", "observed_last_ms", "occurred", "round_ms"})
_TIME_LIKE = re.compile(r"(^t$|^t_|_ms$|_s$|_at$|^time|_time$)")

#: Value specs: ("enum", values), ("bool",), ("int",), ("number",), ("str",).
_BOOL, _INT, _NUM, _STR = ("bool",), ("int",), ("number",), ("str",)

#: `kind` -> {state field: spec}, or None where the kind has no state beyond
#: position and orientation (its `state` is null, `not_applicable`). Every
#: listed field is present; an unread one is null with its reason.
STATE_VOCABULARY: dict[str, dict | None] = {
    "pose": None,
    "estimate": {"basis": _STR},
    "last_known": None,
    # [domain:rounds/resurrection-mechanics]; causes are the death owner's
    "death": {"cause": ("enum", frozenset({"gun", "ability", "environmental",
                                           "melee", "other"})),
              "weapon": _STR, "second_life": _BOOL, "revive": _BOOL},
    "spike": {"phase": ("enum", frozenset(SPIKE_STATES))},
    "ping": {"ping": ("enum", PING_KINDS), "lifetime_s": _NUM},
    "ability_tray": {"level": _NUM, "charges": _INT, "equipped": _BOOL,
                     "castable": _BOOL, "pips": _INT},
    "cast": {"ability": _STR, "slot": ("enum", SLOTS)},
    # `phase` is checked against the ability's own lifecycle facts
    "ability_object": {"ability": _STR, "slot": ("enum", SLOTS), "phase": _STR},
}

#: Orientation conventions the contract names. None yet: the icon-pose owner
#: has not stated what it stores (plan, "What this plan does not settle"), so
#: an orientation is null with its reason until it does.
ORIENTATION_CONVENTIONS: frozenset[str] = frozenset()

#: `baked:<map>__<profile>` until `geometry` publishes a per-map transform,
#: then `map:<map>`. The contract converts nothing.
FRAME = re.compile(r"^(baked:[a-z0-9_]+__[a-z0-9_.-]+|map:[a-z0-9_]+)$")

# ---------------------------------------------------------------------------
# Unread values, uncertainty, names
# ---------------------------------------------------------------------------

REASON_FORMS = ("not_applicable", "not_read: <owner reason>",
                "not_observed: <cause>", "withheld: <ledger id>")
REASON = re.compile(r"^(not_applicable(: .+)?|not_read: .+|not_observed: .+|withheld: .+)$")

#: Keys that say how unsure a row is. The ledger holds them; a consumer row
#: carrying one is rejected wherever it sits.
UNCERTAINTY_KEYS = frozenset({
    "standing", "uncertainty", "confidence", "alternatives", "p_exists",
    "identity_distribution", "distribution", "probability", "posterior",
    "margin", "identity_status", "status", "position_bounds", "residual",
    "contested", "disputed", "ambiguous"})

#: Keys that would hold an agent name outside an `identity` block.
NAME_KEYS = frozenset({"agent", "agents", "victim", "killer", "caster",
                       "pinger", "planter", "carrier", "owner_agent"})
IDENTITY_KEYS = ("agent", "ref", "arbiter")
ARBITER = re.compile(r"^agent-identity-\d+\.\d+\.\d+$")
VERDICT_REF = re.compile(r"^identity:.+")

# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------

STANDINGS = ("resolved", "ambiguous", "abstained", "refused", "not_observed",
             "disputed", "stale")
#: Residual reasons, each with the fact that makes its event unobservable to
#: every other channel. None yet: a new one needs the player's approval and a
#: fact (plan section 3, "The drop rule").
RESIDUAL_REASONS: dict[str, str] = {}
LEDGER_KEYS = ("row", "ledger_id", "lane", "subject", "standing", "reason",
               "fields", "returns_to", "residual", "contract")

# ---------------------------------------------------------------------------
# Between observations
# ---------------------------------------------------------------------------

#: (family, kind) -> the rule while nothing observes it. Anything unlisted is
#: `not_observed`. It grows one family at a time, from the player or a fact.
BETWEEN_OBSERVATIONS: dict[tuple[str, str], str] = {
    ("icon_track", "ally"): "estimate",
    ("icon_track", "self"): "estimate",
    ("icon_track", "enemy"): "estimate_until_last_known",
    ("mark", "last_known"): "last_known",
}
#: The owner that stores each estimate. `position-belief` covers the player
#: alone; allies and enemies wait for gap 3a, and their gaps read
#: `NO_ESTIMATE_OWNER`.
ESTIMATE_OWNERS: dict[tuple[str, str], str | None] = {
    ("icon_track", "self"): "position-belief",
    ("icon_track", "ally"): None,
    ("icon_track", "enemy"): None,
}
NO_ESTIMATE_OWNER = "not_observed: no_estimate_owner"


def between_observations(family: str, kind: str, *, alive: bool = True,
                         marked: bool = False) -> str:
    """What an entity shows while nothing observes it.

    One of `estimate` (its owner's estimate event), `last_known` (the enemy's
    red "?" mark, after which no estimate follows), `ended` (a track past its
    death) or `not_observed` (coverage, no estimate).
    """
    rule = BETWEEN_OBSERVATIONS.get((family, kind))
    if rule is None:
        return "not_observed"
    if rule == "last_known":
        return "last_known"
    if not alive:
        return "ended"
    if rule == "estimate_until_last_known":
        return "last_known" if marked else "estimate"
    return "estimate"


def estimate_gap_reason(family: str, kind: str) -> str | None:
    """The coverage reason when a family's rule calls for an estimate no owner
    stores, or None when an owner exists or the rule calls for none."""
    if between_observations(family, kind) != "estimate":
        return None
    return None if ESTIMATE_OWNERS.get((family, kind)) else NO_ESTIMATE_OWNER


# ---------------------------------------------------------------------------
# Ability vocabularies, from the facts
# ---------------------------------------------------------------------------

@functools.lru_cache(maxsize=1)
def _lifecycle_states() -> dict[str, tuple[tuple[str, str], ...]]:
    """subject -> ((state, fact key), ...) over lifecycle facts with `states`."""
    from . import domain
    out: dict[str, list[tuple[str, str]]] = {}
    for key, fact in sorted(domain.load().items()):
        if fact.kind == "lifecycle" and fact.states and fact.subject:
            for state in fact.states:
                out.setdefault(fact.subject.lower(), []).append((state, key))
    return {k: tuple(v) for k, v in out.items()}


def ability_states(agent: str, ability: str, slot: str) -> tuple[frozenset, str | None]:
    """An ability object's phases and the reason when no fact names them.

    Read from the `states` of the lifecycle facts whose `subject` is
    `<agent>:<ability>` ([domain:abilities/ability-rules-are-unique]). With
    none, only `observed`, and `no-fact:<agent>:<slot>:lifecycle`.
    """
    found = _lifecycle_states().get(f"{agent}:{ability}".lower(), ())
    if found:
        return frozenset(s for s, _k in found), None
    return frozenset({"observed"}), f"no-fact:{agent}:{slot}:lifecycle"


@functools.lru_cache(maxsize=1)
def _ownership_ids() -> frozenset[str]:
    from . import ownership
    return frozenset(ownership.load().get("_index", {}))


# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

def is_entity_stream(stream: str) -> bool:
    return stream.startswith(STREAM_PREFIX)


def lane_of(stream: str) -> tuple[str, bool]:
    """`(lane, is_ledger)` for an `entity_*` stream."""
    body = stream[len(STREAM_PREFIX):]
    if body.endswith(LEDGER_SUFFIX):
        return body[:-len(LEDGER_SUFFIX)], True
    return body, False


def stamp_key(stream: str) -> str:
    return f"{stream}_version"


# ---------------------------------------------------------------------------
# Checks. Each returns a list of messages; empty means the value passes.
# ---------------------------------------------------------------------------

def _reasons(obj, path: str = "") -> list[str]:
    """A null field without a `<field>_reason` in one of the four forms, or a
    reason for a field that is not there, anywhere in the row."""
    out: list[str] = []
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            out += _reasons(item, f"{path}[{i}]")
        return out
    if not isinstance(obj, dict):
        return out
    for key, value in obj.items():
        where = f"{path}.{key}" if path else key
        if key.endswith("_reason"):
            if key[:-len("_reason")] not in obj:
                out.append(f"{where} gives a reason for a field the row does not hold")
            continue
        if value is None:
            reason = obj.get(f"{key}_reason")
            if not isinstance(reason, str) or not reason:
                out.append(f"{where} is null with no {key}_reason")
            elif not REASON.match(reason):
                out.append(f"{where}_reason {reason!r} is not one of the forms "
                           f"{', '.join(REASON_FORMS)}")
        else:
            out += _reasons(value, where)
    return out


def _find_keys(obj, keys: frozenset, path: str = "", skip: tuple = ()) -> list[str]:
    out: list[str] = []
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            out += _find_keys(item, keys, f"{path}[{i}]", skip)
    elif isinstance(obj, dict):
        for key, value in obj.items():
            where = f"{path}.{key}" if path else key
            if key in skip:
                continue
            if key in keys:
                out.append(where)
            out += _find_keys(value, keys, where, skip)
    return out


def _names_outside_identity(obj, path: str = "") -> list[str]:
    out: list[str] = []
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            out += _names_outside_identity(item, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for key, value in obj.items():
            where = f"{path}.{key}" if path else key
            if key == "identity":
                continue
            if key in NAME_KEYS and isinstance(value, (str, list)) and value:
                out.append(where)
            out += _names_outside_identity(value, where)
    return out


def check_identity(identity, where: str = "identity",
                   verdicts: Mapping[str, str] | None = None) -> list[str]:
    """A name only from a resolved arbiter verdict: `agent`, `ref`, `arbiter`."""
    if identity is None:
        return []
    if not isinstance(identity, dict):
        return [f"{where} is not an object"]
    out = []
    extra = sorted(set(identity) - set(IDENTITY_KEYS))
    if extra:
        out.append(f"{where} holds {extra}; an identity is agent, ref and arbiter")
    agent, ref, arbiter = (identity.get(k) for k in IDENTITY_KEYS)
    if not isinstance(agent, str) or not agent:
        out.append(f"{where} names no agent")
    if not isinstance(ref, str) or not VERDICT_REF.match(ref):
        out.append(f"{where} names {agent!r} without a ref to an arbiter verdict")
    if not isinstance(arbiter, str) or not ARBITER.match(arbiter):
        out.append(f"{where} names {agent!r} with arbiter {arbiter!r}, not an "
                   f"agent-identity stamp")
    if verdicts is not None and isinstance(ref, str) and VERDICT_REF.match(ref):
        status = verdicts.get(ref)
        if status != "resolved":
            out.append(f"{where} cites {ref}, a verdict that is "
                       f"{status or 'not stored'}, not resolved")
    return out


def _check_interval(value, where: str) -> list[str]:
    """An inferred interval: `{lo_ms, hi_ms, basis}` and optional evidence."""
    if value is None:
        return []
    if not isinstance(value, dict):
        return [f"{where} is an inferred time and must be an interval "
                f"{{lo_ms, hi_ms, basis}}, not {type(value).__name__}"]
    out = []
    extra = sorted(set(value) - {"lo_ms", "hi_ms", "basis", "evidence"})
    if extra:
        out.append(f"{where} holds {extra}")
    lo, hi = value.get("lo_ms"), value.get("hi_ms")
    if not _is_num(lo) or not _is_num(hi):
        out.append(f"{where} needs numeric lo_ms and hi_ms")
    elif lo > hi:
        out.append(f"{where} has lo_ms after hi_ms")
    if not isinstance(value.get("basis"), str) or not value.get("basis"):
        out.append(f"{where} is an inferred time with no basis")
    return out


def _is_num(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _check_spec(value, spec, where: str) -> list[str]:
    if value is None:
        return []
    kind = spec[0]
    if kind == "enum":
        return [] if value in spec[1] else [
            f"{where} {value!r} is outside its vocabulary {sorted(spec[1])}"]
    ok = {"bool": isinstance(value, bool),
          "int": isinstance(value, int) and not isinstance(value, bool),
          "number": _is_num(value),
          "str": isinstance(value, str) and bool(value)}[kind]
    return [] if ok else [f"{where} {value!r} is not a {kind}"]


def check_state(kind: str, state) -> list[str]:
    """`state` against its kind's declared vocabulary."""
    if kind not in STATE_VOCABULARY:
        return [f"event kind {kind!r} is not one of {sorted(STATE_VOCABULARY)}"]
    vocab = STATE_VOCABULARY[kind]
    if vocab is None:
        return [] if state is None else [
            f"a {kind} event has no state beyond position and orientation"]
    if state is None:
        return [f"a {kind} event must carry its state {sorted(vocab)}"]
    if not isinstance(state, dict):
        return ["state is not an object"]
    out = []
    fields = {k for k in state if not k.endswith("_reason")}
    for key in sorted(fields - set(vocab)):
        out.append(f"state.{key} is outside the {kind} vocabulary {sorted(vocab)}")
    for key in sorted(set(vocab) - fields):
        out.append(f"state.{key} is missing; an unread one is null with a reason")
    for key, spec in vocab.items():
        if key in state:
            out += _check_spec(state[key], spec, f"state.{key}")
    if kind == "ability_object" and isinstance(state.get("ability"), str):
        agent, _, ability = state["ability"].partition(":")
        phases, reason = ability_states(agent, ability, str(state.get("slot")))
        phase = state.get("phase")
        if phase is not None and phase not in phases:
            out.append(f"state.phase {phase!r} is not a state the facts give "
                       f"{state['ability']} ({sorted(phases)})")
        if reason and state.get("phase_reason") != reason:
            out.append(f"state.phase_reason must be {reason!r}: no lifecycle "
                       f"fact names this ability's states")
    return out


def check_position(position) -> list[str]:
    if position is None:
        return []
    if not isinstance(position, dict):
        return ["position is not an object"]
    out = []
    frame = position.get("frame")
    if not isinstance(frame, str) or not FRAME.match(frame):
        out.append(f"position has no declared frame (got {frame!r}); use "
                   f"baked:<map>__<profile> or map:<map>")
    if not _is_num(position.get("x")) or not _is_num(position.get("y")):
        out.append("position needs numeric x and y")
    extra = sorted(set(position) - {"frame", "x", "y", "r"})
    if extra:
        out.append(f"position holds {extra}")
    return out


def check_orientation(orientation) -> list[str]:
    if orientation is None:
        return []
    if not isinstance(orientation, dict) or not _is_num(orientation.get("deg")):
        return ["orientation needs numeric deg and a convention"]
    conv = orientation.get("convention")
    if conv not in ORIENTATION_CONVENTIONS:
        return [f"orientation convention {conv!r} is not one the contract names "
                f"({sorted(ORIENTATION_CONVENTIONS) or 'none yet'})"]
    return []


def check_producer(producer, owners: frozenset | None) -> list[str]:
    if not isinstance(producer, dict):
        return ["producer must be {owner, version}"]
    out = []
    owner, version = producer.get("owner"), producer.get("version")
    if not isinstance(owner, str) or not owner:
        out.append("producer names no owner")
    elif owners is not None and owner not in owners:
        out.append(f"producer {owner!r} is not an ownership.toml entry")
    if not isinstance(version, str) or not version:
        out.append("producer names no version")
    return out


def check_evidence(evidence) -> list[str]:
    if not isinstance(evidence, list):
        return ["evidence must be a list of {stream, id, version}"]
    out = []
    for i, ev in enumerate(evidence):
        if not isinstance(ev, dict) or not all(
                isinstance(ev.get(k), str) and ev.get(k) for k in ("stream", "id", "version")):
            out.append(f"evidence[{i}] must name stream, id and version")
    return out


def _check_common(row: dict, lane: str | None) -> list[str]:
    out = []
    if row.get("contract") != ENTITY_CONTRACT_VERSION:
        out.append(f"contract {row.get('contract')!r} is not {ENTITY_CONTRACT_VERSION}")
    if lane is not None and row.get("lane") != lane:
        out.append(f"lane {row.get('lane')!r} is not this file's lane {lane!r}")
    return out


def _keys(row: dict, required: Iterable[str], optional: Iterable[str] = ()) -> list[str]:
    required = tuple(required)
    allowed = set(required) | set(optional)
    out = [f"missing field {k}" for k in required if k not in row]
    for key in row:
        if key.endswith("_reason") or key in allowed:
            continue
        if _TIME_LIKE.search(key):
            out.append(f"{key} is a time outside observed_ms, observed_last_ms and "
                       f"occurred: an inferred time stored as an observation time")
        else:
            out.append(f"{key} is not a field of a {row.get('row')} row")
    return out


def check_entity(row: dict, *, lane: str | None = None,
                 verdicts: Mapping[str, str] | None = None,
                 owners: frozenset | None = None) -> list[str]:
    out = _keys(row, ENTITY_KEYS, ENTITY_OPTIONAL) + _check_common(row, lane)
    family, kind = row.get("family"), row.get("kind")
    if family not in FAMILIES:
        out.append(f"family {family!r} is not one of {sorted(FAMILIES)}")
    else:
        kinds = FAMILIES[family]
        if kinds is None:
            if not isinstance(kind, str) or not kind:
                out.append(f"a {family} entity needs a kind")
        elif kind not in kinds:
            out.append(f"kind {kind!r} is not a {family} kind {sorted(kinds)}")
    if row.get("side") is not None and row.get("side") not in SIDES:
        out.append(f"side {row.get('side')!r} is not ally or enemy")
    if family == "player" and row.get("round") is not None:
        out.append("a player entity is match-scoped and has no round")
    if row.get("round") is not None and not isinstance(row.get("round"), int):
        out.append("round must be the round table's number")
    life = row.get("lifetime")
    if not isinstance(life, dict):
        out.append("lifetime must be an object")
    else:
        out += _keys({**life, "row": "lifetime"}, LIFETIME_KEYS, ("row",))
        for key in ("first_observed_ms", "last_observed_ms", "censored_at_ms"):
            if life.get(key) is not None and not _is_num(life.get(key)):
                out.append(f"lifetime.{key} must be a number")
        for key in ("began", "ended"):
            out += _check_interval(life.get(key), f"lifetime.{key}")
    out += check_identity(row.get("identity"), verdicts=verdicts)
    out += check_producer(row.get("producer"), owners)
    return out


def check_event(row: dict, *, lane: str | None = None,
                verdicts: Mapping[str, str] | None = None,
                owners: frozenset | None = None) -> list[str]:
    out = _keys(row, EVENT_KEYS, EVENT_OPTIONAL) + _check_common(row, lane)
    kind = row.get("kind")
    first, last = row.get("observed_ms"), row.get("observed_last_ms")
    for key, value in (("observed_ms", first), ("observed_last_ms", last)):
        if value is not None and not _is_num(value):
            out.append(f"{key} must be a number: an inferred time is occurred, "
                       f"an interval with its basis")
    if _is_num(first) and _is_num(last) and last < first:
        out.append("observed_last_ms is before observed_ms")
    out += _check_interval(row.get("occurred"), "occurred")
    evidence = row.get("evidence")
    out += check_evidence(evidence)
    if first is not None and isinstance(evidence, list) and not evidence:
        out.append("observed_ms cites no observation: a time with no evidence is "
                   "an inference stored as an observation time")
    if kind == "estimate":
        if first is not None or last is not None:
            out.append("an estimate is not observed: its observed_ms is null and "
                       "its instant is occurred")
        if row.get("occurred") is None:
            out.append("an estimate needs occurred, the instant it estimates")
    out += check_state(kind, row.get("state"))
    out += check_position(row.get("position"))
    out += check_orientation(row.get("orientation"))
    out += check_identity(row.get("identity"), verdicts=verdicts)
    parts = row.get("participants")
    if parts is not None:
        if not isinstance(parts, dict):
            out.append("participants must map a role to {entity_id, identity}")
        else:
            for role, p in parts.items():
                if p is None or role.endswith("_reason"):
                    continue
                if not isinstance(p, dict) or not isinstance(p.get("entity_id"), str):
                    out.append(f"participants.{role} needs an entity_id")
                    continue
                out += check_identity(p.get("identity"),
                                      f"participants.{role}.identity", verdicts)
    if row.get("round_ms") is not None and not _is_num(row.get("round_ms")):
        out.append("round_ms must be a number")
    out += check_producer(row.get("producer"), owners)
    return out


def check_coverage(row: dict, *, lane: str | None = None) -> list[str]:
    out = _keys(row, ("row", "lane", "round", "observed", "unobserved", "contract"))
    out += _check_common(row, lane)
    for key in ("observed", "unobserved"):
        spans = row.get(key)
        if not isinstance(spans, list):
            out.append(f"{key} must be a list of intervals")
            continue
        for i, s in enumerate(spans):
            if not isinstance(s, dict) or not _is_num(s.get("lo_ms")) or not _is_num(s.get("hi_ms")):
                out.append(f"{key}[{i}] needs lo_ms and hi_ms")
            elif key == "unobserved" and not re.match(r"^not_observed: .+", str(s.get("cause"))):
                out.append(f"unobserved[{i}] needs a cause 'not_observed: <cause>'")
    return out


def check_stamp(row: dict, stream: str) -> list[str]:
    key = stamp_key(stream)
    out = []
    if not isinstance(row.get(key), str) or not row.get(key):
        out.append(f"the stamp row has no {key}")
    if row.get("contract") != ENTITY_CONTRACT_VERSION:
        out.append(f"the stamp's contract is not {ENTITY_CONTRACT_VERSION}")
    inputs = row.get("inputs")
    if not isinstance(inputs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) and v for k, v in inputs.items()):
        out.append("the stamp's inputs must map each input stream to its stored stamp")
    extra = sorted(set(row) - {"row", key, "contract", "inputs"})
    if extra:
        out.append(f"the stamp row holds {extra}")
    return out


def check_withheld(row: dict, *, lane: str | None = None,
                   owners: frozenset | None = None) -> list[str]:
    """A ledger row: what was withheld, why, the alternatives and who answers."""
    out = _keys(row, LEDGER_KEYS, ("residual_reason",)) + _check_common(row, lane)
    subject = row.get("subject")
    if (not isinstance(subject, dict) or subject.get("row") not in ("entity", "event", "coverage")
            or not (any(isinstance(subject.get(k), str) and subject.get(k)
                        for k in ("entity_id", "event_id"))
                    or isinstance(subject.get("round"), int))):
        out.append("subject must name the withheld row: {row, entity_id, event_id "
                   "or a coverage round}")
    standing = row.get("standing")
    if standing not in STANDINGS:
        out.append(f"standing {standing!r} is not one of {', '.join(STANDINGS)}")
    elif standing == "resolved":
        out.append("a resolved row belongs in the consumer output, not the ledger")
    if not isinstance(row.get("reason"), str) or not row.get("reason"):
        out.append("a withheld row keeps its owner's reason verbatim")
    fields = row.get("fields")
    if not isinstance(fields, dict):
        out.append("fields must map a field to its standing and alternatives")
    else:
        for name, f in fields.items():
            if not isinstance(f, dict) or f.get("standing") not in STANDINGS:
                out.append(f"fields.{name} needs a standing")
                continue
            alts = f.get("alternatives", [])
            if not isinstance(alts, list):
                out.append(f"fields.{name}.alternatives must be a list")
                continue
            for i, a in enumerate(alts):
                if (not isinstance(a, dict) or "value" not in a
                        or not isinstance(a.get("owner"), str)
                        or not isinstance(a.get("evidence"), list)):
                    out.append(f"fields.{name}.alternatives[{i}] needs value, owner "
                               f"and evidence")
            if f["standing"] == "disputed" and len(alts) < 2:
                out.append(f"fields.{name} is disputed and holds fewer than two "
                           f"alternatives")
    returns = row.get("returns_to")
    if not isinstance(returns, list) or not returns:
        out.append("returns_to must name the owner each question goes back to")
    elif owners is not None:
        for owner in returns:
            if owner not in owners:
                out.append(f"returns_to {owner!r} is not an ownership.toml entry")
    residual = row.get("residual")
    if not isinstance(residual, bool):
        out.append("residual must be true or false")
    elif residual and row.get("residual_reason") not in RESIDUAL_REASONS:
        out.append(f"residual_reason {row.get('residual_reason')!r} is not a "
                   f"declared residual reason ({sorted(RESIDUAL_REASONS) or 'none yet'}); "
                   f"a new one needs the player's approval and a fact")
    return out


def check_consumer_row(row: dict, *, lane: str | None = None,
                       verdicts: Mapping[str, str] | None = None,
                       owners: frozenset | None = None) -> list[str]:
    """One consumer-output row, apart from the rules that join rows."""
    kind = row.get("row")
    if kind == "entity":
        out = check_entity(row, lane=lane, verdicts=verdicts, owners=owners)
    elif kind == "event":
        out = check_event(row, lane=lane, verdicts=verdicts, owners=owners)
    elif kind == "coverage":
        out = check_coverage(row, lane=lane)
    else:
        return [f"row {kind!r} is not stamp, entity, event or coverage"]
    for where in _find_keys(row, UNCERTAINTY_KEYS):
        out.append(f"{where} is an uncertainty field; a consumer row is certain "
                   f"or absent, and the ledger holds the doubt")
    for where in _names_outside_identity(row):
        out.append(f"{where} holds a name outside an identity block; a name comes "
                   f"only from a resolved arbiter verdict")
    out += _reasons(row)
    return out


def _check_between(rows: list[dict]) -> list[tuple[int, str]]:
    """Estimates and last-known marks against their entity's family rule."""
    entities = {r.get("entity_id"): r for r in rows if r.get("row") == "entity"}
    marks: dict[str, float] = {}
    for r in rows:
        if r.get("row") == "event" and r.get("kind") == "last_known" and _is_num(r.get("observed_ms")):
            eid = r.get("entity_id")
            marks[eid] = min(marks.get(eid, float("inf")), r["observed_ms"])
    out = []
    for i, r in enumerate(rows):
        if r.get("row") != "event" or r.get("kind") not in ("estimate", "last_known"):
            continue
        ent = entities.get(r.get("entity_id"))
        if ent is None:
            out.append((i, f"a {r['kind']} event's entity {r.get('entity_id')!r} is not "
                           f"in the lane, so its family rule cannot be checked"))
            continue
        family, kind = ent.get("family"), ent.get("kind")
        if r["kind"] == "last_known":
            if (family, kind) not in (("icon_track", "enemy"), ("mark", "last_known")):
                out.append((i, f"a last_known event belongs to an enemy track or its "
                               f"mark, not a {family} {kind}"))
            continue
        occurred = r.get("occurred") if isinstance(r.get("occurred"), dict) else {}
        t = occurred.get("lo_ms")
        ended = (ent.get("lifetime") or {}).get("ended")
        alive = not (isinstance(ended, dict) and _is_num(t) and _is_num(ended.get("hi_ms"))
                     and t > ended["hi_ms"])
        marked = _is_num(t) and r.get("entity_id") in marks and t >= marks[r.get("entity_id")]
        rule = between_observations(family, kind, alive=alive, marked=marked)
        if rule != "estimate":
            out.append((i, f"an estimate on a {family} {kind} breaks the family rule: "
                           f"between observations it shows {rule}"))
    return out


def validate_lane(stream: str, rows: list[dict], *,
                  verdicts: Mapping[str, str] | None = None,
                  owners: Iterable[str] | None = None) -> list[tuple[int, str]]:
    """`(row index, message)` for every rejected row of an `entity_*` stream.

    `owners` defaults to the ids in `ownership.toml`. Empty means the lane
    may be written.
    """
    if not is_entity_stream(stream):
        return [(-1, f"{stream} is not an entity stream")]
    lane, ledger = lane_of(stream)
    owner_ids = frozenset(owners) if owners is not None else _ownership_ids()
    out: list[tuple[int, str]] = []
    if not rows or rows[0].get("row") != "stamp":
        out.append((0, "an entity lane opens with its stamp row"))
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            out.append((i, "a row must be an object"))
            continue
        kind = row.get("row")
        if kind == "stamp":
            if i != 0:
                out.append((i, "a lane holds one stamp row, first"))
            msgs = check_stamp(row, stream)
        elif ledger:
            msgs = (check_withheld(row, lane=lane, owners=owner_ids) if kind == "withheld"
                    else [f"row {kind!r} is not stamp or withheld in a ledger"])
        else:
            msgs = check_consumer_row(row, lane=lane, verdicts=verdicts, owners=owner_ids)
        out += [(i, m) for m in msgs]
    if not ledger:
        out += _check_between([r if isinstance(r, dict) else {} for r in rows])
    return sorted(out)
