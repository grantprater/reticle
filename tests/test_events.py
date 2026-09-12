"""Tests for the unified event contract (reticle.events)."""

import unittest
from pathlib import Path
import tempfile

from reticle.events import (
    Event,
    EventKind,
    EntityState,
    CausalOriginKind,
    MotionClass,
    SourceChannel,
    PositionBounds,
    IdentityDistribution,
    EVENTS_VERSION,
    make_event_id,
    parse_event_id,
    entity_state_event,
    entity_deleted_event,
    entity_bounds_event,
    existence_probability_event,
    identity_distribution_event,
    causal_origin_event,
    session_boundary_event,
    validate_event_row,
    validate_event_rows,
    read_events_jsonl,
    iter_events_jsonl,
)
from reticle.ping import PingReader, PING_TYPES


class EventContractTests(unittest.TestCase):
    """Test Event construction, validation, and serialization."""

    def test_make_and_parse_event_id(self):
        eid = make_event_id("session_1", EventKind.ENTITY_STATE, 1234.5, ordinal=2)
        self.assertEqual(eid, "session_1:entity_state:1234.500:2")
        parsed = parse_event_id(eid)
        self.assertEqual(parsed["session_id"], "session_1")
        self.assertEqual(parsed["kind"], "entity_state")
        self.assertEqual(parsed["t_ms"], 1234.5)
        self.assertEqual(parsed["ordinal"], 2)

    def test_entity_state_event_roundtrip(self):
        e = entity_state_event(
            session_id="s1",
            entity_id="track:self",
            t_ms=100.0,
            position=(50.0, 75.0),
            state=EntityState.ALIVE,
            source_channel=SourceChannel.MINIMAP,
            producer_version="minimap-0.7.0",
            orientation=1.57,
            motion_class=MotionClass.WALKER,
            metadata={"test": True},
        )
        d = e.to_dict()
        self.assertEqual(d["event_kind"], "entity_state")
        self.assertEqual(d["position"], [50.0, 75.0])
        self.assertEqual(d["events_version"], EVENTS_VERSION)

        restored = Event.from_dict(d)
        self.assertEqual(restored.event_id, e.event_id)
        self.assertEqual(restored.position, (50.0, 75.0))
        self.assertEqual(restored.state, EntityState.ALIVE)
        self.assertEqual(restored.motion_class, MotionClass.WALKER)

    def test_entity_deleted_event(self):
        e = entity_deleted_event(
            session_id="s1",
            entity_id="ping:enemy:1",
            t_ms=5000.0,
            deletion_reason="expired",
            source_channel=SourceChannel.PING,
            producer_version="ping-0.3.0",
        )
        self.assertEqual(e.event_kind, EventKind.ENTITY_DELETED)
        self.assertEqual(e.deletion_reason, "expired")

    def test_entity_bounds_event(self):
        bounds = PositionBounds(circles=[(10.0, 20.0, 5.0)])
        e = entity_bounds_event(
            session_id="s1",
            entity_id="track:enemy:1",
            t_ms=200.0,
            position_bounds=bounds,
            source_channel=SourceChannel.TRACK,
            producer_version="track-0.3.0",
        )
        d = e.to_dict()
        self.assertEqual(d["position_bounds"]["circles"], [(10.0, 20.0, 5.0)])
        restored = Event.from_dict(d)
        self.assertEqual(restored.position_bounds.circles, [(10.0, 20.0, 5.0)])

    def test_existence_probability_event(self):
        e = existence_probability_event(
            session_id="s1",
            entity_id="track:enemy:1",
            t_ms=300.0,
            p_exists=0.85,
            source_channel=SourceChannel.TRACK,
            producer_version="track-0.3.0",
            last_observed_ms=100.0,
        )
        self.assertEqual(e.p_exists, 0.85)
        self.assertEqual(e.last_observed_ms, 100.0)

    def test_identity_distribution_event(self):
        dist = IdentityDistribution(
            distribution={"Jett": 0.8, "Raze": 0.2},
            subject_entity_id="killfeed:1:victim",
            contributing_channels=["killfeed_portrait", "lineup"],
        )
        e = identity_distribution_event(
            session_id="s1",
            entity_id="identity:killfeed:1:victim",
            t_ms=400.0,
            identity_distribution=dist,
            source_channel=SourceChannel.ADJUDICATION_IDENTITY,
            producer_version="agent-identity-0.2.0",
        )
        d = e.to_dict()
        restored = Event.from_dict(d)
        self.assertEqual(restored.identity_distribution.distribution["Jett"], 0.8)

    def test_causal_origin_event(self):
        e = causal_origin_event(
            session_id="s1",
            entity_id="lifecycle:ally:1",
            t_ms=500.0,
            origin_kind=CausalOriginKind.RELOCATION,
            source_channel=SourceChannel.MINIMAP_LIFECYCLE,
            producer_version="minimap-lifecycle-0.2.0",
            origin_event_id="track:teleport:10",
        )
        self.assertEqual(e.origin_kind, CausalOriginKind.RELOCATION)

    def test_session_boundary_event(self):
        e = session_boundary_event(
            session_id="s1",
            t_ms=0.0,
            boundary_type="round_start",
            source_channel=SourceChannel.MINIMAP_LIFECYCLE,
            producer_version="minimap-lifecycle-0.2.0",
            round_no=1,
        )
        self.assertEqual(e.boundary_type, "round_start")
        self.assertEqual(e.round_no, 1)

    def test_validation_rejects_missing_required_fields(self):
        row = {
            "session_id": "s1",
            "entity_id": "e1",
            "t_ms": 10.0,
            "event_kind": "entity_state",
            "source_channel": "minimap",
            "producer_version": "v1",
            "events_version": EVENTS_VERSION,
            # missing event_id and evidence_refs
        }
        ok, err = validate_event_row(row)
        self.assertFalse(ok)
        self.assertIn("missing required fields", err)

    def test_validation_rejects_missing_kind_payload(self):
        row = {
            "event_id": "s1:entity_state:10.0:0",
            "session_id": "s1",
            "entity_id": "e1",
            "t_ms": 10.0,
            "event_kind": "entity_state",
            "source_channel": "minimap",
            "producer_version": "v1",
            "evidence_refs": [],
            "events_version": EVENTS_VERSION,
            # missing position and state
        }
        ok, err = validate_event_row(row)
        self.assertFalse(ok)
        self.assertIn("missing required payload", err)

    def test_validation_rejects_out_of_bound_probability(self):
        row = {
            "event_id": "s1:existence_probability:10.0:0",
            "session_id": "s1",
            "entity_id": "e1",
            "t_ms": 10.0,
            "event_kind": "existence_probability",
            "source_channel": "track",
            "producer_version": "v1",
            "evidence_refs": [],
            "events_version": EVENTS_VERSION,
            "p_exists": 1.5,
        }
        ok, err = validate_event_row(row)
        self.assertFalse(ok)
        self.assertIn("p_exists must be in [0, 1]", err)

    def test_jsonl_io_roundtrip(self):
        e1 = session_boundary_event(
            session_id="s1",
            t_ms=0.0,
            boundary_type="round_start",
            source_channel=SourceChannel.MINIMAP_LIFECYCLE,
            producer_version="minimap-lifecycle-0.2.0",
        )
        e2 = entity_state_event(
            session_id="s1",
            entity_id="track:self",
            t_ms=10.0,
            position=(10.0, 20.0),
            state=EntityState.ALIVE,
            source_channel=SourceChannel.MINIMAP,
            producer_version="minimap-0.7.0",
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "events.jsonl"
            with open(path, "w", encoding="utf-8") as f:
                f.write(e1.to_json() + "\n")
                f.write(e2.to_json() + "\n")

            loaded = read_events_jsonl(str(path))
            self.assertEqual(len(loaded), 2)
            self.assertEqual(loaded[0].event_kind, EventKind.SESSION_BOUNDARY)
            self.assertEqual(loaded[1].event_kind, EventKind.ENTITY_STATE)

            streamed = list(iter_events_jsonl(str(path)))
            self.assertEqual(len(streamed), 2)
            self.assertEqual(streamed[0].event_id, e1.event_id)

    def test_ping_reader_emits_valid_events(self):
        reader = PingReader(None, (0, 0, 100, 100), hz=10.0)
        # Simulate a confirmed hit: kind, t0, t1, x, y, hue, n
        reader.hits = [("standard", 1.0, 9.0, 100, 150, 90, 80)]
        events = reader.events("session_ping_test")
        self.assertEqual(len(events), 2)

        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

        appearance, expiration = events[0], events[1]
        self.assertEqual(appearance["event_kind"], "entity_state")
        self.assertEqual(appearance["state"], "active")
        self.assertEqual(appearance["entity_id"], "ping:standard:0")
        self.assertEqual(appearance["t_ms"], 1000)

        self.assertEqual(expiration["event_kind"], "entity_deleted")
        self.assertEqual(expiration["deletion_reason"], "expired")
        self.assertEqual(expiration["entity_id"], "ping:standard:0")
        self.assertEqual(expiration["t_ms"], 9000)

    def test_store_write_events_validates_formal_events(self):
        from reticle.store import Store
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(Path(tmpdir))
            valid_events = [
                session_boundary_event(
                    session_id="s1",
                    t_ms=0.0,
                    boundary_type="round_start",
                    source_channel=SourceChannel.ROUNDS if hasattr(SourceChannel, "ROUNDS") else SourceChannel.MINIMAP_LIFECYCLE,
                    producer_version="rounds-0.1.0",
                ).to_dict()
            ]
            path = store.write_events("boundary", "s1", valid_events)
            self.assertTrue(path.is_file())

            invalid_events = [{"event_kind": "entity_state", "entity_id": "bad"}]
            with self.assertRaises(ValueError):
                store.write_events("bad", "s1", invalid_events)

    def test_store_write_events_allows_unconstrained_observations(self):
        from reticle.store import Store
        with tempfile.TemporaryDirectory() as tmpdir:
            store = Store(Path(tmpdir))
            obs = [{"kind": "coverage", "observations": 10}, {"kind": "portrait_observation", "data": 123}]
            path = store.write_events("killfeed_portrait", "s1", obs)
            self.assertTrue(path.is_file())
            read_back = store.read_events("killfeed_portrait", "s1")
            self.assertEqual(len(read_back), 2)
            self.assertEqual(read_back[0]["kind"], "coverage")

    def test_round_events_emits_valid_session_boundaries(self):
        from reticle.rounds import round_events
        sample_rounds = [
            {
                "round_no": 1,
                "t_start_ms": 1000.0,
                "t_end_ms": 75000.0,
                "start_source": "capture_start",
                "won_left": True,
                "left_before": 0,
                "right_before": 0,
                "spike_planted": False,
                "plant_t_ms": None,
            },
            {
                "round_no": 2,
                "t_start_ms": 82000.0,
                "t_end_ms": 145000.0,
                "start_source": "clock_reset",
                "won_left": False,
                "left_before": 1,
                "right_before": 0,
                "spike_planted": True,
                "plant_t_ms": 120000.0,
            },
        ]
        events = round_events(sample_rounds, "session-rounds-test")
        self.assertEqual(len(events), 4)

        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

        r1_start = events[0]
        self.assertEqual(r1_start["event_kind"], "session_boundary")
        self.assertEqual(r1_start["boundary_type"], "round_start")
        self.assertEqual(r1_start["round_no"], 1)
        self.assertEqual(r1_start["t_ms"], 1000.0)

        r2_end = events[3]
        self.assertEqual(r2_end["boundary_type"], "round_end")
        self.assertEqual(r2_end["round_no"], 2)
        self.assertTrue(r2_end["metadata"]["spike_planted"])


if __name__ == "__main__":
    unittest.main()
