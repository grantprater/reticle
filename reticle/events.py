"""Unified event contract for Reticle.

Every observable fact in the pipeline is an Event: instantaneous, identity-carrying,
provenance-tracked. Events are the north star artifact; trajectories, probabilities,
and adjudications are derived views built by consumers.

Version: events-0.1.0
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict, is_dataclass
from typing import Literal, Optional, Any
import json
import time
import uuid
from enum import Enum

EVENTS_VERSION = "events-0.1.0"


class EventKind(str, Enum):
    """Kinds of events in the contract.

    OBSERVED ENTITY EVENTS
    ----------------------
    entity_state        - position, orientation, state, motion_class for a directly observed entity
    entity_deleted      - entity removed (death, left widget, ping expired, track expired)

    UNOBSERVED ENTITY BOUNDS
    ------------------------
    entity_bounds       - position bounds or distribution for entities without direct observations
    existence_probability - P(entity exists | evidence) with last observation reference

    IDENTITY & CAUSALITY
    --------------------
    identity_distribution - agent identity uncertainty (from adjudication.identity)
    causal_origin         - minimap_lifecycle: continuation/explained_origin/relocation/left_censored/unexplained_appearance

    CONTROL & METADATA
    ------------------
    session_boundary    - round start/end, match start/end, capture start/end
    """
    # Observed entity events
    ENTITY_STATE = "entity_state"
    ENTITY_DELETED = "entity_deleted"

    # Unobserved entity bounds
    ENTITY_BOUNDS = "entity_bounds"
    EXISTENCE_PROBABILITY = "existence_probability"

    # Identity & causality
    IDENTITY_DISTRIBUTION = "identity_distribution"
    CAUSAL_ORIGIN = "causal_origin"

    # Control
    SESSION_BOUNDARY = "session_boundary"


class EntityState(str, Enum):
    """State of an observed entity."""
    ALIVE = "alive"
    ACTIVE = "active"        # for pings, abilities
    DELETED = "deleted"
    REVIVED = "revived"


class CausalOriginKind(str, Enum):
    """Causal origin states from minimap_lifecycle."""
    CONTINUATION = "continuation"
    EXPLAINED_ORIGIN = "explained_origin"
    RELOCATION = "relocation"
    LEFT_CENSORED = "left_censored"
    UNEXPLAINED_APPEARANCE = "unexplained_appearance"
    UNLIT_UNEXPLAINED_APPEARANCE = "unlit_unexplained_appearance"
    AMBIGUOUS_CONTINUATION = "ambiguous_continuation"


class MotionClass(str, Enum):
    """Motion classes from track.py — what an entity MAY do between observations."""
    WALKER = "walker"
    WALKER_DASH = "walker_dash"
    WALKER_TELEPORT = "walker_teleport"
    PILOTED = "piloted"
    FIXED_ROTATOR = "fixed_rotator"
    STATIC = "static"
    SETTLES = "settles"
    ENEMY_REACTIVE = "enemy_reactive"
    PING_PLAYER = "ping_player"
    PING_ENEMY = "ping_enemy"
    PING_ABILITY = "ping_ability"
    PING_THREAT = "ping_threat"


class SourceChannel(str, Enum):
    """Producers that emit events. Extensible — new channels register here."""
    MINIMAP = "minimap"
    KILLFEED = "killfeed"
    KILFEED = "killfeed"
    KILLFEED_PORTRAIT = "killfeed_portrait"
    PING = "ping"
    ROSTER = "roster"
    LINEUP = "lineup"
    ADJUDICATION_IDENTITY = "adjudication.identity"
    MINIMAP_LIFECYCLE = "minimap_lifecycle"
    ROUNDS = "rounds"
    COACHING = "coaching"
    TRACK = "track"
    CUSTOM = "custom"


@dataclass
class PositionBounds:
    """Position uncertainty for unobserved entities.

    Circles: list of (x, y, radius_px) in widget or world coordinates.
    The coordinate frame is declared in the event's metadata.coordinate_frame.
    """
    circles: list[tuple[float, float, float]] = field(default_factory=list)
    # Optional: mixture of Gaussians for particle-filter style distributions
    gmm_weights: Optional[list[float]] = None
    gmm_means: Optional[list[tuple[float, float]]] = None
    gmm_covariances: Optional[list[list[list[float]]]] = None

    def to_dict(self) -> dict:
        out = {"circles": self.circles}
        if self.gmm_weights is not None:
            out["gmm_weights"] = self.gmm_weights
            out["gmm_means"] = self.gmm_means
            out["gmm_covariances"] = self.gmm_covariances
        return out

    @classmethod
    def from_dict(cls, data: dict) -> PositionBounds:
        return cls(
            circles=data.get("circles", []),
            gmm_weights=data.get("gmm_weights"),
            gmm_means=data.get("gmm_means"),
            gmm_covariances=data.get("gmm_covariances"),
        )


@dataclass
class IdentityDistribution:
    """Agent identity uncertainty from adjudication.

    Maps agent name -> probability. Sum <= 1.0 (remaining mass = "unknown/other").
    """
    distribution: dict[str, float] = field(default_factory=dict)
    # The entity_id this distribution applies to (e.g., "killfeed:12:victim")
    subject_entity_id: str = ""
    # Channels that contributed to this distribution
    contributing_channels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "distribution": self.distribution,
            "subject_entity_id": self.subject_entity_id,
            "contributing_channels": self.contributing_channels,
        }

    @classmethod
    def from_dict(cls, data: dict) -> IdentityDistribution:
        return cls(
            distribution=data.get("distribution", {}),
            subject_entity_id=data.get("subject_entity_id", ""),
            contributing_channels=data.get("contributing_channels", []),
        )


@dataclass
class Event:
    """The unified event contract.

    Required fields (validated on construction):
      - event_id: globally unique identifier
      - session_id: session this event belongs to
      - entity_id: stable entity key (see ENTITY_ID_FORMAT below)
      - t_ms: observation timestamp in milliseconds
      - event_kind: what kind of event this is
      - source_channel: which producer emitted this
      - producer_version: version stamp of the producer (e.g., "minimap-0.7.0")

    All other fields are kind-dependent and optional.
    """
    # --- Identity (required) ---
    event_id: str
    session_id: str
    entity_id: str

    # --- Time (required) ---
    t_ms: float

    # --- Kind & provenance (required) ---
    event_kind: EventKind
    source_channel: SourceChannel
    producer_version: str

    # --- Evidence chain (required, can be empty for primary observations) ---
    evidence_refs: list[str] = field(default_factory=list)  # upstream event_ids or observation_keys

    # --- Observed entity payload (ENTITY_STATE, ENTITY_DELETED) ---
    position: Optional[tuple[float, float]] = None          # (x, y) in widget or world px
    orientation: Optional[float] = None                     # radians, None if N/A
    state: Optional[EntityState] = None
    motion_class: Optional[MotionClass] = None

    # --- Deletion payload (ENTITY_DELETED) ---
    deletion_reason: Optional[str] = None                   # "death", "left_widget", "expired", "track_lost"

    # --- Bounds payload (ENTITY_BOUNDS) ---
    position_bounds: Optional[PositionBounds] = None

    # --- Existence probability payload (EXISTENCE_PROBABILITY) ---
    p_exists: Optional[float] = None
    last_observed_ms: Optional[float] = None

    # --- Identity payload (IDENTITY_DISTRIBUTION) ---
    identity_distribution: Optional[IdentityDistribution] = None

    # --- Causal origin payload (CAUSAL_ORIGIN) ---
    origin_kind: Optional[CausalOriginKind] = None
    origin_event_id: Optional[str] = None
    origin_interval_ms: Optional[tuple[float, float]] = None
    alternatives: list[str] = field(default_factory=list)   # other entity_ids that could be parent
    conflict: Optional[str] = None                          # "origin_vs_lighting", etc.
    eligible: bool = True                                   # can this entity participate in future associations

    # --- Session boundary payload (SESSION_BOUNDARY) ---
    boundary_type: Optional[str] = None                     # "round_start", "round_end", "match_start", "match_end", "capture_start", "capture_end"
    round_no: Optional[int] = None
    metadata: dict = field(default_factory=dict)            # free-form extensibility

    # --- Contract version (auto-stamped) ---
    events_version: str = EVENTS_VERSION

    # ENTITY_ID FORMAT:
    #   "{owner}:{key}"
    #   owner = which module owns the identity continuity question:
    #     "track"      - track.py's persistent tracks (motion continuity)
    #     "lifecycle"  - minimap_lifecycle's promoted entities (causal origin)
    #     "killfeed"   - killfeed entry roles (entry_id:role)
    #     "ping"       - ping grouper groups
    #     "roster"     - roster slot (slot:N)
    #     "identity"   - adjudication.identity's resolved identities
    #   key = owner-specific stable key

    def __post_init__(self):
        """Validate required fields and kind-dependent payloads."""
        if not self.event_id:
            raise ValueError("event_id is required")
        if not self.session_id:
            raise ValueError("session_id is required")
        if not self.entity_id:
            raise ValueError("entity_id is required")
        if not isinstance(self.t_ms, (int, float)) or not (0 <= self.t_ms < 1e15):
            raise ValueError("t_ms must be a valid timestamp in milliseconds")
        if not isinstance(self.event_kind, EventKind):
            raise ValueError(f"event_kind must be EventKind, got {type(self.event_kind)}")
        if not isinstance(self.source_channel, SourceChannel):
            raise ValueError(f"source_channel must be SourceChannel, got {type(self.source_channel)}")
        if not self.producer_version:
            raise ValueError("producer_version is required")

        # Kind-dependent validation
        if self.event_kind == EventKind.ENTITY_STATE:
            if self.position is None:
                raise ValueError("ENTITY_STATE requires position")
            if self.state is None:
                raise ValueError("ENTITY_STATE requires state")
        elif self.event_kind == EventKind.ENTITY_DELETED:
            if self.deletion_reason is None:
                raise ValueError("ENTITY_DELETED requires deletion_reason")
        elif self.event_kind == EventKind.ENTITY_BOUNDS:
            if self.position_bounds is None:
                raise ValueError("ENTITY_BOUNDS requires position_bounds")
        elif self.event_kind == EventKind.EXISTENCE_PROBABILITY:
            if self.p_exists is None:
                raise ValueError("EXISTENCE_PROBABILITY requires p_exists")
            if not (0.0 <= self.p_exists <= 1.0):
                raise ValueError("p_exists must be in [0, 1]")
        elif self.event_kind == EventKind.IDENTITY_DISTRIBUTION:
            if self.identity_distribution is None:
                raise ValueError("IDENTITY_DISTRIBUTION requires identity_distribution")
        elif self.event_kind == EventKind.CAUSAL_ORIGIN:
            if self.origin_kind is None:
                raise ValueError("CAUSAL_ORIGIN requires origin_kind")
        elif self.event_kind == EventKind.SESSION_BOUNDARY:
            if self.boundary_type is None:
                raise ValueError("SESSION_BOUNDARY requires boundary_type")

    def to_json(self) -> str:
        """Serialize to JSON line for JSONL storage."""
        return json.dumps(self.to_dict(), separators=(",", ":"), allow_nan=False)

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        d = asdict(self)
        # Convert enums to values
        d["event_kind"] = self.event_kind.value
        d["source_channel"] = self.source_channel.value
        if self.state is not None:
            d["state"] = self.state.value
        if self.motion_class is not None:
            d["motion_class"] = self.motion_class.value
        if self.origin_kind is not None:
            d["origin_kind"] = self.origin_kind.value
        # Nested dataclasses
        if self.position_bounds is not None:
            d["position_bounds"] = self.position_bounds.to_dict()
        if self.identity_distribution is not None:
            d["identity_distribution"] = self.identity_distribution.to_dict()
        # Tuples to lists for JSON
        if self.position is not None:
            d["position"] = list(self.position)
        if self.origin_interval_ms is not None:
            d["origin_interval_ms"] = list(self.origin_interval_ms)
        return d

    @classmethod
    def from_dict(cls, data: dict) -> Event:
        """Deserialize from dictionary (JSONL line)."""
        data = data.copy()
        # Enums
        data["event_kind"] = EventKind(data["event_kind"])
        data["source_channel"] = SourceChannel(data["source_channel"])
        if data.get("state"):
            data["state"] = EntityState(data["state"])
        if data.get("motion_class"):
            data["motion_class"] = MotionClass(data["motion_class"])
        if data.get("origin_kind"):
            data["origin_kind"] = CausalOriginKind(data["origin_kind"])
        # Nested
        if data.get("position_bounds"):
            data["position_bounds"] = PositionBounds.from_dict(data["position_bounds"])
        if data.get("identity_distribution"):
            data["identity_distribution"] = IdentityDistribution.from_dict(data["identity_distribution"])
        # Lists back to tuples
        if data.get("position"):
            data["position"] = tuple(data["position"])
        if data.get("origin_interval_ms"):
            data["origin_interval_ms"] = tuple(data["origin_interval_ms"])
        return cls(**data)


# ---------------------------------------------------------------------------
# Event ID generation
# ---------------------------------------------------------------------------

def make_event_id(session_id: str, kind: EventKind, t_ms: float, ordinal: int = 0) -> str:
    """Generate a globally unique event_id.

    Format: {session_id}:{kind.value}:{t_ms:.3f}:{ordinal}
    The t_ms precision (milliseconds) + ordinal handles multiple events at same timestamp.
    """
    return f"{session_id}:{kind.value}:{t_ms:.3f}:{ordinal}"


def parse_event_id(event_id: str) -> dict:
    """Parse an event_id back into components."""
    parts = event_id.split(":")
    if len(parts) < 4:
        return {"raw": event_id}
    return {
        "session_id": parts[0],
        "kind": parts[1],
        "t_ms": float(parts[2]),
        "ordinal": int(parts[3]),
    }


# ---------------------------------------------------------------------------
# Factory functions for common event types
# ---------------------------------------------------------------------------

def entity_state_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    position: tuple[float, float],
    state: EntityState,
    source_channel: SourceChannel,
    producer_version: str,
    orientation: Optional[float] = None,
    motion_class: Optional[MotionClass] = None,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create an ENTITY_STATE event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.ENTITY_STATE, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.ENTITY_STATE,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        position=position,
        orientation=orientation,
        state=state,
        motion_class=motion_class,
        metadata=metadata or {},
    )


def entity_deleted_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    deletion_reason: str,
    source_channel: SourceChannel,
    producer_version: str,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create an ENTITY_DELETED event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.ENTITY_DELETED, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.ENTITY_DELETED,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        deletion_reason=deletion_reason,
        metadata=metadata or {},
    )


def entity_bounds_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    position_bounds: PositionBounds,
    source_channel: SourceChannel,
    producer_version: str,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create an ENTITY_BOUNDS event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.ENTITY_BOUNDS, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.ENTITY_BOUNDS,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        position_bounds=position_bounds,
        metadata=metadata or {},
    )


def existence_probability_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    p_exists: float,
    source_channel: SourceChannel,
    producer_version: str,
    last_observed_ms: Optional[float] = None,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create an EXISTENCE_PROBABILITY event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.EXISTENCE_PROBABILITY, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.EXISTENCE_PROBABILITY,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        p_exists=p_exists,
        last_observed_ms=last_observed_ms,
        metadata=metadata or {},
    )


def identity_distribution_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    identity_distribution: IdentityDistribution,
    source_channel: SourceChannel,
    producer_version: str,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create an IDENTITY_DISTRIBUTION event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.IDENTITY_DISTRIBUTION, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.IDENTITY_DISTRIBUTION,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        identity_distribution=identity_distribution,
        metadata=metadata or {},
    )


def causal_origin_event(
    *,
    session_id: str,
    entity_id: str,
    t_ms: float,
    origin_kind: CausalOriginKind,
    source_channel: SourceChannel,
    producer_version: str,
    origin_event_id: Optional[str] = None,
    origin_interval_ms: Optional[tuple[float, float]] = None,
    alternatives: Optional[list[str]] = None,
    conflict: Optional[str] = None,
    eligible: bool = True,
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create a CAUSAL_ORIGIN event (from minimap_lifecycle)."""
    return Event(
        event_id=make_event_id(session_id, EventKind.CAUSAL_ORIGIN, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.CAUSAL_ORIGIN,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        origin_kind=origin_kind,
        origin_event_id=origin_event_id,
        origin_interval_ms=origin_interval_ms,
        alternatives=alternatives or [],
        conflict=conflict,
        eligible=eligible,
        metadata=metadata or {},
    )


def session_boundary_event(
    *,
    session_id: str,
    t_ms: float,
    boundary_type: str,
    source_channel: SourceChannel,
    producer_version: str,
    round_no: Optional[int] = None,
    entity_id: str = "session",
    evidence_refs: Optional[list[str]] = None,
    metadata: Optional[dict] = None,
) -> Event:
    """Create a SESSION_BOUNDARY event."""
    return Event(
        event_id=make_event_id(session_id, EventKind.SESSION_BOUNDARY, t_ms),
        session_id=session_id,
        entity_id=entity_id,
        t_ms=t_ms,
        event_kind=EventKind.SESSION_BOUNDARY,
        source_channel=source_channel,
        producer_version=producer_version,
        evidence_refs=evidence_refs or [],
        boundary_type=boundary_type,
        round_no=round_no,
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Validation helpers for store.write_events
# ---------------------------------------------------------------------------

REQUIRED_FIELDS = {
    "event_id", "session_id", "entity_id", "t_ms",
    "event_kind", "source_channel", "producer_version",
    "evidence_refs", "events_version",
}

KIND_REQUIRED = {
    EventKind.ENTITY_STATE: {"position", "state"},
    EventKind.ENTITY_DELETED: {"deletion_reason"},
    EventKind.ENTITY_BOUNDS: {"position_bounds"},
    EventKind.EXISTENCE_PROBABILITY: {"p_exists"},
    EventKind.IDENTITY_DISTRIBUTION: {"identity_distribution"},
    EventKind.CAUSAL_ORIGIN: {"origin_kind"},
    EventKind.SESSION_BOUNDARY: {"boundary_type"},
}


def validate_event_row(row: dict) -> tuple[bool, Optional[str]]:
    """Validate a single event row (dict from JSONL) before write.

    Returns (ok, error_message). Used by store.write_events.
    """
    # Required fields
    missing = REQUIRED_FIELDS - set(row.keys())
    if missing:
        return False, f"missing required fields: {sorted(missing)}"

    # Enum values
    try:
        kind = EventKind(row["event_kind"])
    except ValueError:
        return False, f"invalid event_kind: {row['event_kind']}"

    try:
        SourceChannel(row["source_channel"])
    except ValueError:
        return False, f"invalid source_channel: {row['source_channel']}"

    # Kind-dependent required payload
    kind_missing = KIND_REQUIRED.get(kind, set()) - set(row.keys())
    if kind_missing:
        return False, f"{kind.value} missing required payload: {sorted(kind_missing)}"

    # One producer of names: the identity arbiter. A module that decided a
    # name beside it cannot publish that name.
    if (kind == EventKind.IDENTITY_DISTRIBUTION
            and row["source_channel"] != SourceChannel.ADJUDICATION_IDENTITY.value):
        return False, ("identity_distribution events come only from "
                       "adjudication.identity, got " + str(row["source_channel"]))

    # p_exists bounds
    if kind == EventKind.EXISTENCE_PROBABILITY:
        p = row.get("p_exists")
        if p is not None and not (0.0 <= float(p) <= 1.0):
            return False, "p_exists must be in [0, 1]"

    # Version stamp
    if row.get("events_version") != EVENTS_VERSION:
        return False, f"events_version mismatch: expected {EVENTS_VERSION}, got {row.get('events_version')}"

    return True, None


def validate_event_rows(rows: list[dict]) -> list[tuple[int, str]]:
    """Validate multiple event rows.

    Returns list of (index, error_message) for invalid rows. Empty = all valid.
    """
    errors = []
    for i, row in enumerate(rows):
        ok, err = validate_event_row(row)
        if not ok:
            errors.append((i, err))
    return errors


# ---------------------------------------------------------------------------
# Reading helpers
# ---------------------------------------------------------------------------

def read_events_jsonl(path: str) -> list[Event]:
    """Read events from a JSONL file."""
    events = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            events.append(Event.from_dict(json.loads(line)))
    return events


def iter_events_jsonl(path: str):
    """Iterate events from a JSONL file without loading all into memory."""
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield Event.from_dict(json.loads(line))


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # Round-trip test
    session_id = "test_session_123"

    # ENTITY_STATE
    e1 = entity_state_event(
        session_id=session_id,
        entity_id="track:self",
        t_ms=123456.7,
        position=(100.5, 200.3),
        state=EntityState.ALIVE,
        source_channel=SourceChannel.MINIMAP,
        producer_version="minimap-0.7.0",
        orientation=1.57,
        motion_class=MotionClass.WALKER,
    )
    assert e1.event_kind == EventKind.ENTITY_STATE
    assert e1.position == (100.5, 200.3)

    # ENTITY_DELETED
    e2 = entity_deleted_event(
        session_id=session_id,
        entity_id="ping:enemy:2",
        t_ms=123457.0,
        deletion_reason="expired",
        source_channel=SourceChannel.PING,
        producer_version="ping-0.3.0",
        evidence_refs=[e1.event_id],
    )
    assert e2.event_kind == EventKind.ENTITY_DELETED
    assert e2.deletion_reason == "expired"

    # ENTITY_BOUNDS
    bounds = PositionBounds(circles=[(300.0, 400.0, 50.0), (350.0, 420.0, 30.0)])
    e3 = entity_bounds_event(
        session_id=session_id,
        entity_id="lifecycle:enemy:3",
        t_ms=123457.0,
        position_bounds=bounds,
        source_channel=SourceChannel.MINIMAP_LIFECYCLE,
        producer_version="minimap-lifecycle-0.2.0",
    )
    assert e3.position_bounds.circles == [(300.0, 400.0, 50.0), (350.0, 420.0, 30.0)]

    # IDENTITY_DISTRIBUTION
    id_dist = IdentityDistribution(
        distribution={"Jett": 0.72, "Phoenix": 0.18},
        subject_entity_id="killfeed:12:victim",
        contributing_channels=["killfeed_portrait", "lineup"],
    )
    e4 = identity_distribution_event(
        session_id=session_id,
        entity_id="identity:killfeed:12:victim",
        t_ms=123456.7,
        identity_distribution=id_dist,
        source_channel=SourceChannel.ADJUDICATION_IDENTITY,
        producer_version="agent-identity-0.2.0",
    )
    assert e4.identity_distribution.distribution["Jett"] == 0.72

    # CAUSAL_ORIGIN
    e5 = causal_origin_event(
        session_id=session_id,
        entity_id="lifecycle:ally:2",
        t_ms=123457.0,
        origin_kind=CausalOriginKind.RELOCATION,
        source_channel=SourceChannel.MINIMAP_LIFECYCLE,
        producer_version="minimap-lifecycle-0.2.0",
        origin_event_id="track:teleport:45",
        origin_interval_ms=(123450.0, 123456.0),
        alternatives=["track:ally:2"],
    )
    assert e5.origin_kind == CausalOriginKind.RELOCATION

    # SESSION_BOUNDARY
    e6 = session_boundary_event(
        session_id=session_id,
        t_ms=0.0,
        boundary_type="round_start",
        source_channel=SourceChannel.MINIMAP_LIFECYCLE,
        producer_version="minimap-lifecycle-0.2.0",
        round_no=1,
    )
    assert e6.boundary_type == "round_start"
    assert e6.round_no == 1

    # Serialization round-trip
    for e in [e1, e2, e3, e4, e5, e6]:
        d = e.to_dict()
        e2 = Event.from_dict(d)
        assert e2.event_id == e.event_id
        assert e2.entity_id == e.entity_id
        assert e2.t_ms == e.t_ms
        assert e2.event_kind == e.event_kind

    # Validation
    ok, err = validate_event_row(e1.to_dict())
    assert ok, err

    ok, err = validate_event_row({"event_id": "x", "session_id": "s", "entity_id": "e", "t_ms": 1.0,
                                   "event_kind": "entity_state", "source_channel": "minimap",
                                   "producer_version": "v", "evidence_refs": [], "events_version": EVENTS_VERSION})
    assert not ok
    assert "position" in err

    print("All self-tests passed.")