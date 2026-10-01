"""Enemy tracks over synthetic stored `minimap_object` rows: association, the
"?" binding, death binding and unbinding, and the identity refusals."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from reticle import enemy_tracks as et
from reticle import entity_events as ee
from reticle.entity_contract import validate_lane
from reticle.store import Store

SID = "s1"
ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 30000.0}]
FEATS = [0.5, 0.5]


def _enemy(x, y):
    return {"x": x, "y": y, "r": 9.5, "facing": 90.0, "facing_reason": None,
            "portrait_features": FEATS}


def object_rows():
    """One enemy walking right from 1000 to 3000 ms, then its "?" at the last place."""
    rows = [{"kind": "coverage", "minimap_object_version": "minimap-object-test",
             "portrait_features_version": "pf-test", "scale": 1.0}]
    t, x = 1000.0, 100.0
    while t <= 3000.0:
        rows.append({"kind": "frame", "t_ms": t, "frame_idx": int(t / 16.7), "reason": None,
                     "enemies": [_enemy(x, 200.0)], "questions": [],
                     "x_marks": {"blue": [], "red": []}})
        last_t, last_x = t, x
        t += 67.0
        x += 1.0
    key = f"{last_t:.1f}:0"
    for i in range(1, 20):
        rows.append({"kind": "frame", "t_ms": last_t + 67.0 * i, "frame_idx": 0, "reason": None,
                     "enemies": [], "x_marks": {"blue": [], "red": []},
                     "questions": [{"x": last_x, "y": 200.0, "onset_ms": last_t + 67.0,
                                    "icon_last_ms": last_t, "icon_key": key,
                                    "age_ms": 67.0 * i}]})
    rows.append({"kind": "frame", "t_ms": last_t + 67.0 * 20, "frame_idx": 0,
                 "reason": "widget_not_drawn"})
    return rows, last_t, last_x


def lineup(blind=False):
    agents = ["Raze", "Jett", "Sova", "Sage", None if blind else "Omen"]
    return {"version": "lineup-test", "sides": {"enemy": [
        {"slot": i, "agent": a} for i, a in enumerate(agents)]}}


def death(t_ms, location, victim="Raze"):
    return {"kind": "death_verdict", "death_id": "d1", "round_no": 1, "t_ms": t_ms,
            "side": "enemy", "victim": victim, "location": location, "is_revive": False}


class TrackTests(unittest.TestCase):
    def test_one_track_its_mark_and_its_death(self):
        rows, last_t, last_x = object_rows()
        got = et.build(SID, rows, ROUNDS, [death(last_t + 100.0, [last_x, 200.0])],
                       lineup(), None)
        ents = [r for r in got["rows"] if r["kind"] == "entity"]
        self.assertEqual(len(ents), 1)
        e = ents[0]
        self.assertEqual((e["end_reason"], e["death_id"]), ("death", "d1"))
        marks = [r for r in got["rows"] if r["kind"] == "mark"]
        self.assertEqual(len(marks), 1)
        self.assertEqual((marks[0]["entity_id"], marks[0]["detections"]), (e["id"], 19))
        self.assertEqual(e["mark_id"], marks[0]["mark_id"])
        head = got["rows"][0]
        self.assertEqual((head["kind"], head["enemy_track_version"]),
                         ("summary", et.ENEMY_TRACK_VERSION))
        self.assertEqual(head["coverage"]["absent_frames"], 1)

    def test_a_death_whose_x_lies_elsewhere_is_never_bound(self):
        rows, last_t, _x = object_rows()
        got = et.build(SID, rows, ROUNDS, [death(last_t + 100.0, [400.0, 400.0])],
                       lineup(), None)
        e = next(r for r in got["rows"] if r["kind"] == "entity")
        self.assertIsNone(e["death_id"])
        self.assertNotEqual(e["end_reason"], "death")
        # Refused before binding, so the post-hoc check has nothing to undo.
        self.assertIsNone(e["death_unbound"])
        self.assertEqual(got["rows"][0]["death_unbound"], {})

    def test_a_greedy_swap_binds_each_death_to_its_named_track(self):
        """Two tracks side by side, two deaths at their place. The larger track
        is nearer in time to the other agent's death; the arbiter's names keep
        each death for its own track instead of unbinding both."""
        from reticle.adjudication.identity import identity_claim
        rows = [{"kind": "coverage", "minimap_object_version": "mo", "scale": 1.0}]
        t = 1000.0
        while t <= 3000.0:
            ens = [_enemy(100.0, 200.0)] + ([_enemy(100.0, 215.0)] if t <= 2800.0 else [])
            rows.append({"kind": "frame", "t_ms": t, "frame_idx": int(t / 16.7),
                         "reason": None, "enemies": ens, "questions": []})
            last_a, t = t, t + 67.0
        last_b = max(r["t_ms"] for r in rows[1:] if len(r["enemies"]) == 2)
        name = {200.0: "Raze", 215.0: "Jett"}

        def claims(sid, frames, obs_entity, *_a, **_k):
            out = []
            for f in frames:
                for i, e in enumerate(f["enemies"]):
                    eid = obs_entity.get(f"{f['t_ms']:.1f}:{i}")
                    out.append(identity_claim(eid, name[e["y"]], channel=et.CHANNEL,
                                              source_version="test", observed_at_ms=f["t_ms"]))
            return out
        deaths = [{"kind": "death_verdict", "death_id": "dRaze", "round_no": 1,
                   "t_ms": last_a + 250.0, "side": "enemy", "victim": "Raze",
                   "location": [100.0, 207.0], "is_revive": False},
                  {"kind": "death_verdict", "death_id": "dJett", "round_no": 1,
                   "t_ms": last_a + 50.0, "side": "enemy", "victim": "Jett",
                   "location": [100.0, 207.0], "is_revive": False}]
        self.assertLess(abs(deaths[1]["t_ms"] - last_a), abs(deaths[0]["t_ms"] - last_a))
        self.assertLessEqual(abs(deaths[0]["t_ms"] - last_b), 2500.0)
        real = et.track_claims
        et.track_claims = claims
        try:
            got = et.build(SID, rows, ROUNDS, deaths, lineup(), None)
        finally:
            et.track_claims = real
        ents = {r["agent"]: r for r in got["rows"] if r["kind"] == "entity"}
        self.assertEqual(set(ents), {"Raze", "Jett"})
        self.assertEqual(ents["Raze"]["observations"] > ents["Jett"]["observations"], True)
        self.assertEqual((ents["Raze"]["death_id"], ents["Jett"]["death_id"]),
                         ("dRaze", "dJett"))
        self.assertEqual(got["rows"][0]["death_unbound"], {})
        self.assertEqual(got["rows"][0]["deaths"], 2)

    def test_an_unnamed_track_binds_on_time_and_x(self):
        rows, last_t, last_x = object_rows()
        got = et.build(SID, rows, ROUNDS, [death(last_t + 100.0, [last_x, 200.0], victim="Jett")],
                       lineup(), None)
        e = next(r for r in got["rows"] if r["kind"] == "entity")
        self.assertIsNone(e["agent"])
        self.assertEqual((e["end_reason"], e["death_id"]), ("death", "d1"))

    def test_claims_are_rekeyed_to_the_track_and_rest_on_the_lineup(self):
        rows, _t, _x = object_rows()
        frames = [r for r in rows if r["kind"] == "frame"]
        obs = {f"{f['t_ms']:.1f}:0": "s1:R1:E0001" for f in frames if f.get("enemies")}
        claims = et.track_claims(SID, frames, obs, lineup(), None, "mo", "pf-test")
        self.assertEqual({c["entity_id"] for c in claims}, {"s1:R1:E0001"})
        self.assertEqual(claims[0]["depends_on"], [f"{SID}:enemy:slot:{i}" for i in range(5)])
        self.assertEqual(claims[0]["binding_from"], et.BINDING)

    def test_an_incomplete_lineup_refuses_every_name(self):
        rows, _t, _x = object_rows()
        got = et.build(SID, rows, ROUNDS, [], lineup(blind=True), None)
        e = next(r for r in got["rows"] if r["kind"] == "entity")
        self.assertIsNone(e["agent"])
        self.assertEqual(e["identity_status"], "abstained")
        self.assertTrue(e["identity_reason"].startswith("lineup_incomplete"), e)
        ident = got["identity"]
        self.assertEqual(len(ident), 1)
        self.assertEqual(ident[0]["metadata"]["status"], "abstained")
        self.assertEqual(ident[0]["identity_distribution"]["distribution"], {})

    def test_no_lineup_refuses_with_its_reason(self):
        rows, _t, _x = object_rows()
        got = et.build(SID, rows, ROUNDS, [], None, None)
        e = next(r for r in got["rows"] if r["kind"] == "entity")
        self.assertEqual((e["agent"], e["identity_reason"]), (None, "no_lineup"))


class LaneTests(unittest.TestCase):
    """The tracks, written to a store and projected as the enemy lane."""

    def test_the_lane_validates_and_draws_the_mark_on_the_track(self):
        from test_entity_events import _jsonl, build_store
        with tempfile.TemporaryDirectory() as d:
            store = build_store(Path(d))
            rows, last_t, last_x = object_rows()
            got = et.build("s1", rows, ROUNDS, [], lineup(), None)
            _jsonl(store, "enemy_track", got["rows"])
            _jsonl(store, "enemy_track_identity", got["identity"])
            ee.project_lane(store, "s1", "enemy", stale={})
            for stream in ee.lane_streams("enemy"):
                self.assertEqual(validate_lane(stream, store.read_events(stream, "s1")), [])
            ev = ee.EntityEvents(store, "s1", lanes=("enemy",))
            q = ev.events(lane="enemy", kinds=("last_known",))
            self.assertEqual(len(q), 1)
            self.assertEqual(q[0]["position"]["x"], last_x)
            led = {r["ledger_id"]: r for r in ev.ledger(lane="enemy")}
            self.assertEqual(led["enemy:s1:R1:E0001"]["standing"], "abstained")


if __name__ == "__main__":
    unittest.main()
