"""The entity-event projection over a small synthetic store (stage 1).

Each test builds a store in a temp dir holding one session's rounds, deaths,
death verdicts, round entities, spike carrier rows and enemy tracks, projects
the built lanes, and reads them back through `EntityEvents`.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from reticle import entity_events as ee
from reticle.entity_contract import validate_lane
from reticle.store import Store

SID = "s1"
DATE = "2026-09-30"


def _jsonl(store: Store, stream: str, rows: list[dict]) -> None:
    path = store.events_path(stream, SID)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n" for r in rows),
                    encoding="utf-8", newline="\n")


def _verdict(ref: str, agent: str | None, status: str) -> dict:
    return {"event_kind": "identity_distribution", "entity_id": ref,
            "producer_version": ee.NAME_ARBITER,
            "identity_distribution": {"distribution": {agent: 0.9} if agent else {}},
            "metadata": {"status": status}}


def _death(did: str, t_ms: float, victim, killer, status="resolved", weapon="Ghost",
           weapon_status="resolved") -> dict:
    return {"kind": "death_verdict", "death_id": did, "t_ms": t_ms, "round_no": 1,
            "victim": victim, "killer": killer, "weapon": weapon,
            "weapon_evidence": {"status": weapon_status}, "status": status,
            "reason": f"{status} by the fixture", "death_cause": "gun",
            "is_second_life": False, "is_revive": False}


def _entity(eid, family, agent, status, *, end_ms=None, death_id=None, votes=None) -> dict:
    return {"kind": "entity", "id": eid, "family": family, "round_no": 1,
            "first_seen_ms": 1000.0, "last_seen_ms": 1500.0, "origin_ms": 1000.0,
            "origin_reason": "first observation", "end_ms": end_ms,
            "end_reason": "death" if death_id else "round end", "death_id": death_id,
            "right_censored_at_ms": None if end_ms else 60000.0,
            "identity_status": status, "agent": agent,
            "identity_votes": votes or ({agent: 3} if agent else {}),
            "identity_reason": None if status == "resolved" else "two agents tie"}


def _obs(oid, eid, t_ms, state="tracked", x=10.0, y=20.0) -> dict:
    return {"kind": "observation", "observation_id": oid, "entity_id": eid, "round_no": 1,
            "t_ms": t_ms, "x": x, "y": y, "observation_key": f"k{oid}", "state": state}


def build_store(root: Path) -> Store:
    store = Store(root)
    man = store.manifest_path(SID)
    man.parent.mkdir(parents=True, exist_ok=True)
    man.write_text(json.dumps({"session_id": SID, "ingested_at": f"{DATE}T00:00:00",
                               "tags": ["map:split"], "source_profile": "valorant-16x9"}),
                    encoding="utf-8")
    rounds = store.rounds_path(SID, DATE)
    rounds.parent.mkdir(parents=True, exist_ok=True)
    table = pa.table({"round_no": [1, 2], "t_start_ms": [0.0, 70000.0],
                      "t_end_ms": [65000.0, 130000.0], "spike_planted": [True, False],
                      "plant_t_ms": [50000.0, None]})
    pq.write_table(table.replace_schema_metadata({"round_version": "round-test-1"}), rounds)
    _jsonl(store, "death", [
        {"kind": "stamp", "death_adjudication_version": "death-test-1"},
        _death("d1", 30000.0, "Chamber", "Raze"),
        _death("d2", 40000.0, "Jett", "Raze", weapon=None, weapon_status="refused"),
        _death("d3", 45000.0, None, None, status="abstained"),
        _death("d4", 46000.0, "Sage", "Raze", status="contested")])
    _jsonl(store, "death_identity", [
        _verdict("identity:d1", "Chamber", "resolved"),
        _verdict("identity:d1:killer", "Raze", "resolved"),
        _verdict("identity:d2", "Jett", "resolved"),
        _verdict("identity:d2:killer", "Raze", "resolved"),
        _verdict("identity:d3", None, "abstained"),
        _verdict("identity:d4", "Sage", "contested"),
        _verdict("identity:d4:killer", "Raze", "resolved")])
    _jsonl(store, "round_entity", [
        {"kind": "stamp", "round_entity_version": "round-entity-test-1",
         "agent_identity_version": ee.NAME_ARBITER},
        # E1 ends at d1 named Skye, whose victim the death owner names Chamber.
        _entity("E1", "self", "Skye", "resolved", end_ms=30000.0, death_id="d1"),
        _entity("E2", "ally", "Jett", "resolved", end_ms=40000.0, death_id="d2"),
        _entity("E3", "ally", None, "provisional", votes={"Fade": 1, "Sova": 1}),
        _obs("o1", "E1", 1000.0, x=90.0, y=90.0), _obs("o2", "E2", 1000.0, x=50.0, y=60.0), _obs("o3", "E2", 1100.0),
        _obs("o4", "E2", 1500.0), _obs("o5", "E3", 1200.0),
        _obs("o6", None, 1300.0, state="refused: two icons overlap")])
    _jsonl(store, "spike_carrier", [
        {"kind": "stamp", "spike_carrier_version": "spike-carrier-test-1"},
        {"kind": "round", "round_no": 1, "spike_planted": True, "plant_t_ms": 50000.0},
        {"kind": "carrier_lost", "t_ms": 20000.0, "slot": 2, "death": True,
         "dropped_glyph_seen": False, "last_marked_ms": 19500.0,
         "depends_on": "agent-from-slot"}])
    _jsonl(store, "enemy_track", ENEMY_TRACK)
    _jsonl(store, "enemy_track_identity", [
        _verdict("identity:T1", "Raze", "resolved"),
        {**_verdict("identity:T2", None, "abstained"),
         "metadata": {"status": "abstained", "reason": "lineup_incomplete: 4 of 5"}}])
    return store


def _enemy_obs(oid, eid, t_ms, x=200.0, y=100.0) -> dict:
    return {"kind": "observation", "observation_id": oid, "entity_id": eid, "round_no": 1,
            "t_ms": t_ms, "x": x, "y": y, "r": 9.5, "observation_key": f"{t_ms:.1f}:0",
            "state": "continuation", "facing": 90.0, "facing_reason": None}


def _enemy(eid, agent, status, reason=None, mark_id=None) -> dict:
    return {"kind": "entity", "id": eid, "round_no": 1, "first_seen_ms": 2000.0,
            "last_seen_ms": 2600.0, "observations": 3, "end_reason": "last observation "
            "does not establish destruction/death", "end_ms": None, "death_id": None,
            "right_censored_at_ms": 2600.0, "agent": agent, "identity_status": status,
            "identity_reason": reason, "mark_id": mark_id}


#: Two enemy tracks: T1 named Raze, seen at 2000, 2100 and 2600 ms (one gap no
#: estimate owner fills) and then marked by a "?"; T2 unnamed. A second "?"
#: no track holds, and one refused observation.
ENEMY_TRACK = [
    {"kind": "summary", "enemy_track_version": "enemy-track-test-1",
     "minimap_object_version": "minimap-object-test-1", "agent_identity_version": ee.NAME_ARBITER},
    _enemy("T1", "Raze", "resolved", mark_id="s1:R1:Q:2600.0:0"),
    _enemy("T2", None, "abstained", "lineup_incomplete: 4 of 5"),
    _enemy_obs("q1", "T1", 2000.0), _enemy_obs("q2", "T1", 2100.0), _enemy_obs("q3", "T1", 2600.0),
    _enemy_obs("q4", "T2", 2100.0, x=300.0), _enemy_obs("q5", None, 2200.0, x=50.0),
    {"kind": "mark", "round_no": 1, "mark_id": "s1:R1:Q:2600.0:0", "icon_key": "2600.0:0",
     "entity_id": "T1", "x": 201.0, "y": 101.0, "first_ms": 2700.0, "last_ms": 5600.0,
     "onset_ms": 2700.0, "icon_last_ms": 2600.0, "detections": 40, "binding_reason": None},
    {"kind": "mark", "round_no": 1, "mark_id": "s1:R1:Q:3000.0:1", "icon_key": "3000.0:1",
     "entity_id": None, "x": 80.0, "y": 90.0, "first_ms": 3100.0, "last_ms": 4000.0,
     "onset_ms": 3100.0, "icon_last_ms": 3000.0, "detections": 12,
     "binding_reason": "icon_not_tracked"},
]


def project_all(store: Store, stale: dict | None = None) -> dict:
    return {lane: ee.project_lane(store, SID, lane, stale=stale or {})
            for lane in ee.PROJECTED}


class ProjectionTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = build_store(Path(self._dir.name))

    def tearDown(self):
        self._dir.cleanup()

    def test_every_written_lane_validates(self):
        project_all(self.store)
        for lane in ee.PROJECTED:
            for stream in ee.lane_streams(lane):
                rows = self.store.read_events(stream, SID)
                self.assertEqual(validate_lane(stream, rows), [], stream)
                self.assertEqual(rows[0]["row"], "stamp")

    def test_names_come_only_from_resolved_verdicts(self):
        project_all(self.store)
        ev = ee.EntityEvents(self.store, SID)
        deaths = {e["entity_id"]: e for e in ev.events(lane="death")}
        self.assertEqual(deaths["d1"]["identity"]["agent"], "Chamber")
        self.assertEqual(deaths["d1"]["participants"]["killer"]["identity"]["agent"], "Raze")
        # A contested verdict gives no name; the ledger holds it as ambiguous.
        self.assertIsNone(deaths["d4"]["identity"])
        self.assertTrue(deaths["d4"]["identity_reason"].startswith("withheld: "))
        led = {r["ledger_id"]: r for r in ev.ledger(lane="death")}
        self.assertEqual(led["death:d4"]["standing"], "ambiguous")
        # A refused weapon read is withheld, the rest of the death kept.
        self.assertIsNone(deaths["d2"]["state"]["weapon"])
        self.assertEqual(led["death:d2"]["fields"]["weapon"]["standing"], "refused")
        # A provisional ally keeps its track, and the name waits in the ledger.
        e3 = ev.entity("E3")
        self.assertIsNone(e3["identity"])
        led_re = {r["ledger_id"]: r for r in ev.ledger(lane="round_entity")}
        self.assertEqual(led_re["round_entity:E3"]["standing"], "abstained")
        self.assertEqual(ev.entity("E2")["identity"]["agent"], "Jett")

    def test_a_track_bound_to_a_death_named_otherwise_is_disputed(self):
        project_all(self.store)
        ev = ee.EntityEvents(self.store, SID)
        self.assertIsNone(ev.entity("E1"))
        row = next(r for r in ev.ledger(lane="round_entity")
                   if r["ledger_id"] == "round_entity:E1")
        self.assertEqual(row["standing"], "disputed")
        self.assertEqual(row["returns_to"], ["round-entity-session"])
        alts = row["fields"]["identity"]["alternatives"]
        self.assertEqual([(a["value"], a["owner"]) for a in alts],
                         [("Skye", "round-entity-session"), ("Chamber", "death-victim")])
        # Its poses go with it.
        self.assertEqual(ev.events(entity_id="E1"), [])
        self.assertIsNotNone(ee.ledger_value(row))

    def test_an_abstained_death_is_a_ledger_row_not_an_event(self):
        project_all(self.store)
        ev = ee.EntityEvents(self.store, SID)
        self.assertNotIn("d3", {e["entity_id"] for e in ev.events(lane="death")})
        row = next(r for r in ev.ledger(lane="death") if r["ledger_id"] == "death:d3")
        self.assertEqual(row["standing"], "abstained")
        self.assertEqual(ee.ledger_value(row)["event_id"], "death:d3")

    def test_a_gap_with_no_estimate_owner_is_debt(self):
        summary = project_all(self.store)["round_entity"]
        self.assertEqual(summary["estimate_debt_spans"], 1)        # E2: 1100 -> 1500 ms
        cov = ee.EntityEvents(self.store, SID).coverage(1, lane="round_entity")
        self.assertEqual([(u["entity_id"], u["lo_ms"], u["hi_ms"]) for u in cov[0]["unobserved"]],
                         [("E2", 1100.0, 1500.0)])

    def test_the_spike_plant_and_the_carrier_loss(self):
        summary = project_all(self.store)["spike"]
        self.assertEqual((summary["consumer_events"], summary["ledger_abstained"]), (1, 1))

    def test_a_stale_input_holds_every_row_resting_on_it(self):
        summary = project_all(self.store, stale={"round_entity": "inputs ally_icon"})
        self.assertEqual(summary["round_entity"]["consumer_entities"], 0)
        self.assertEqual(summary["death"]["held_inputs"], [])
        self.assertEqual(summary["round_entity"]["held_inputs"], ["round_entity"])
        status = ee.lane_status(self.store, SID, {"round_entity"})
        self.assertEqual(status, {"derived": [], "held": [
            {"stream": "entity_round_entity", "waits_for": ["round_entity"]}]})

    def test_a_second_run_writes_identical_bytes(self):
        project_all(self.store)
        paths = [self.store.events_path(s, SID) for lane in ee.PROJECTED
                 for s in ee.lane_streams(lane)]
        first = [p.read_bytes() for p in paths]
        project_all(self.store)
        self.assertEqual([p.read_bytes() for p in paths], first)

    def test_restamping_the_spike_carrier_stales_only_the_spike_lane(self):
        project_all(self.store)
        self.assertEqual({lane: ee.rebuild_reason(self.store, SID, lane)
                          for lane in ee.PROJECTED},
                         {lane: None for lane in ee.PROJECTED})
        rows = self.store.read_events("spike_carrier", SID)
        rows[0]["spike_carrier_version"] = "spike-carrier-test-2"
        _jsonl(self.store, "spike_carrier", rows)
        self.assertEqual({lane: ee.rebuild_reason(self.store, SID, lane)
                          for lane in ee.PROJECTED},
                         {"round_entity": None, "death": None, "enemy": None,
                          "spike": "inputs moved: spike_carrier"})
        derived = ee.lane_status(self.store, SID, set())["derived"]
        self.assertEqual([(d["stream"], d["command"]) for d in derived],
                         [("entity_spike", f"reticle project {SID} --lane spike")])
        with self.assertRaises(ee.StaleLanes) as cm:
            ee.EntityEvents(self.store, SID)
        self.assertEqual(set(cm.exception.lanes), {"spike"})
        ee.EntityEvents(self.store, SID, lanes=("death", "round_entity", "enemy"))

    def test_a_lane_never_projected_is_missing_not_empty(self):
        ee.project_lane(self.store, SID, "death", stale={})
        ev = ee.EntityEvents(self.store, SID)
        self.assertEqual(set(ev.missing), {"round_entity", "spike", "enemy"})
        self.assertEqual(len(ev.rounds()), 2)


class EnemyLaneTests(unittest.TestCase):
    """The enemy lane: tracks, poses, the "?" as `last_known`, the marks no
    track holds, and the gaps no estimate owner fills."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = build_store(Path(self._dir.name))

    def tearDown(self):
        self._dir.cleanup()

    def test_tracks_poses_and_marks(self):
        s = ee.project_lane(self.store, SID, "enemy", stale={})
        ev = ee.EntityEvents(self.store, SID)
        self.assertEqual(ev.entity("T1")["identity"]["agent"], "Raze")
        self.assertEqual(ev.entity("T1")["side"], "enemy")
        self.assertIsNone(ev.entity("T2")["identity"])
        poses = ev.events(lane="enemy", kinds=("pose",))
        self.assertEqual({p["event_id"] for p in poses}, {"pose:q1", "pose:q2", "pose:q3",
                                                           "pose:q4"})
        self.assertIsNone(poses[0]["orientation"])
        self.assertTrue(poses[0]["orientation_reason"].startswith("not_read: "))
        q = ev.events(lane="enemy", kinds=("last_known",))
        self.assertEqual([(e["entity_id"], e["observed_ms"], e["observed_last_ms"]) for e in q],
                         [("T1", 2700.0, 5600.0), ("s1:R1:Q:3000.0:1", 3100.0, 4000.0)])
        mark = ev.entity("s1:R1:Q:3000.0:1")
        self.assertEqual((mark["family"], mark["kind"]), ("mark", "last_known"))
        self.assertEqual(s["estimate_debt_spans"], 1)              # T1: 2100 -> 2600 ms
        led = {r["ledger_id"]: r for r in ev.ledger(lane="enemy")}
        self.assertEqual(led["enemy:T2"]["standing"], "abstained")
        self.assertEqual(led["enemy:pose:q5"]["standing"], "refused")

    def test_a_stale_track_stream_holds_the_lane(self):
        s = ee.project_lane(self.store, SID, "enemy", stale={"enemy_track": "inputs death"})
        self.assertEqual(s["consumer_entities"], 0)
        self.assertEqual(s["held_inputs"], ["enemy_track"])


class DeclarationTests(unittest.TestCase):
    def test_the_arbiter_literal_is_the_arbiter(self):
        from reticle.adjudication.identity import AGENT_IDENTITY_VERSION
        self.assertEqual(ee.NAME_ARBITER, AGENT_IDENTITY_VERSION)

    def test_every_projected_lane_is_declared(self):
        self.assertEqual(set(ee.PROJECTED), {"round_entity", "death", "spike", "enemy"})
        for lane in ee.PROJECTED:
            self.assertIn(lane, ee.LANE)


if __name__ == "__main__":
    unittest.main()
