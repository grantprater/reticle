"""Session round lifetimes from stored ally icon events."""
import unittest

from reticle.round_entities import ROUND_ENTITY_VERSION, session_lifetimes


def _frame(i, t, drawn=True, me=(100.0, 100.0, 10)):
    return {"kind": "frame", "session_id": "s", "frame_idx": i, "t_ms": t,
            "widget_drawn": drawn, "icons": 0, "self": list(me) if me else None}


def _icon(i, t, x, y=50.0, reason=None, comp=(1.0,)):
    return {"kind": "icon", "session_id": "s", "frame_idx": i, "t_ms": t, "index": 0,
            "observation_key": f"s:{i}:{x}", "cx": x, "cy": y, "r": 8,
            "reason": reason, "composition": list(comp) if comp else None}


ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 1000.0},
          {"round_no": 2, "t_start_ms": 1000.0, "t_end_ms": 2000.0}]


class SessionLifetimeTests(unittest.TestCase):
    def run_rows(self, events, roster=None):
        return session_lifetimes("s", events, ROUNDS, 1.0, roster)

    def test_one_walking_ally_is_one_entity_per_round(self):
        events = []
        for k, t in enumerate(range(0, 2000, 67)):
            events += [_frame(k, float(t)), _icon(k, float(t), 50.0 + k * 0.5)]
        rows = self.run_rows(events)
        allies = [r for r in rows if r["kind"] == "entity" and r["family"] == "ally"]
        self.assertEqual(sorted(r["round_no"] for r in allies), [1, 2])
        self.assertTrue(all(r["round_entity_version"] == ROUND_ENTITY_VERSION for r in rows))

    def test_an_interior_that_is_the_map_is_a_barrier_not_an_ally(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0, reason="interior_is_map")]
        rows = self.run_rows(events)
        (obs,) = [r for r in rows if r["kind"] == "observation" and r["family"] != "self"]
        self.assertEqual(obs["family"], "barrier")

    def test_an_absent_widget_suspends_rather_than_ends(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0),
                  _frame(1, 67.0, drawn=False, me=None),
                  _frame(2, 134.0), _icon(2, 134.0, 51.0)]
        rows = self.run_rows(events)
        allies = {r["entity_id"] for r in rows
                  if r["kind"] == "observation" and r["family"] == "ally"}
        self.assertEqual(len(allies), 1)
        self.assertEqual(rows[0]["absent_frames"], 1)

    def test_the_roster_count_marks_an_extra_ally(self):
        events = [_frame(0, 0.0), _icon(0, 0.0, 50.0), _icon(0, 0.0, 200.0)]
        events[2]["observation_key"] = "s:0:b"
        rows = self.run_rows(events, roster={"t_ms": [0.0], "alive_ally": [2]})
        marks = sorted(r["acquisition"] for r in rows
                       if r["kind"] == "observation" and r["family"] == "ally")
        self.assertEqual(marks, ["roster_count_conflict",
                                 "roster_slot_available_not_identity"])

    def test_track_segments_receive_adjudicated_agent_names(self):
        import numpy as np

        def _one_hot(i, w=0.9):
            v = np.full(4, (1.0 - w) / 3.0, dtype=np.float32)
            v[i] = w
            return v.tolist()

        gallery = {name: [np.eye(4, dtype=np.float32)[i]]
                   for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}
        lineup = {
            "sides": {
                "ally": [{"slot": i, "agent": a, "best_guess": a}
                         for i, a in enumerate(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"])]
            },
            "player": {"agent": "Phoenix"},
        }
        events = [
            _frame(0, 0.0, me=(100.0, 100.0, 10)),
            _icon(0, 0.0, 50.0, comp=_one_hot(0)),
            _icon(0, 0.0, 200.0, reason="interior_is_map"),
            _frame(1, 67.0, me=(100.0, 100.0, 10)),
            _icon(1, 67.0, 50.5, comp=_one_hot(0)),
        ]
        events[2]["observation_key"] = "s:0:barrier"
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, lineup=lineup, gallery=gallery)
        ents = {r["family"]: r for r in rows if r["kind"] == "entity"}

        self.assertIn("ally", ents)
        self.assertEqual(ents["ally"]["agent"], "Breach")
        self.assertEqual(ents["ally"]["teammate_key"], "s:teammate:Breach")
        self.assertEqual(ents["ally"]["identity_status"], "resolved")
        self.assertEqual(ents["ally"]["identity_votes"], {"Breach": 2})

        self.assertIn("self", ents)
        self.assertEqual(ents["self"]["agent"], "Phoenix")
        self.assertEqual(ents["self"]["teammate_key"], "s:teammate:Phoenix")
        self.assertEqual(ents["self"]["identity_status"], "resolved")

        self.assertIn("barrier", ents)
        self.assertIsNone(ents["barrier"]["agent"])
        self.assertIsNone(ents["barrier"]["teammate_key"])
        self.assertEqual(ents["barrier"]["identity_status"], "abstained")
        self.assertEqual(ents["barrier"]["identity_reason"], "barrier")

    def test_death_witness_names_abstained_track_with_depends_on(self):
        import numpy as np

        gallery = {name: [np.eye(4, dtype=np.float32)[i]]
                   for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}
        lineup = {
            "sides": {
                "ally": [{"slot": i, "agent": a, "best_guess": a}
                         for i, a in enumerate(["Phoenix", "Breach", "Deadlock", "Reyna", "Miks"])]
            },
            "player": {"agent": "Phoenix"},
        }
        # Track has no confident composition (e.g. comp is uniform noise, below margin)
        uniform_comp = [0.25, 0.25, 0.25, 0.25]
        events = [
            _frame(0, 0.0),
            _icon(0, 0.0, 50.0, comp=uniform_comp),
            _frame(1, 67.0),
            _icon(1, 67.0, 50.5, comp=uniform_comp),
        ]
        deaths = [{
            "kind": "death_verdict", "round_no": 1, "t_ms": 70.0, "side": "ally",
            "victim": "Reyna", "death_id": "death:s:70:0", "killer": "Jett", "weapon": "Vandal"
        }]
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, deaths=deaths, lineup=lineup, gallery=gallery)
        ents = {r["family"]: r for r in rows if r["kind"] == "entity"}

        self.assertIn("ally", ents)
        self.assertEqual(ents["ally"]["agent"], "Reyna")
        self.assertEqual(ents["ally"]["teammate_key"], "s:teammate:Reyna")
        self.assertEqual(ents["ally"]["identity_status"], "resolved")
        self.assertEqual(ents["ally"]["death_id"], "death:s:70:0")
        self.assertEqual(ents["ally"]["end_reason"], "death")


    def test_a_segment_that_fits_no_teammate_is_refused(self):
        from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION
        names = ["Breach", "Deadlock", "Miks", "Reyna"]
        refs = {"version": "t", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
                "margin_min": 0.5, "variance": {"g": [1.0]},
                "agents": {n: {"g": [float(i)]} for i, n in enumerate(names)},
                "teammate_fit": {"version": "t", "fit_max": 2.0}}
        lineup = {"sides": {"ally": [{"slot": i, "agent": a, "best_guess": a} for i, a in
                                     enumerate(["Phoenix"] + names)]},
                  "player": {"agent": "Phoenix"}}
        events = []
        for k in range(3):
            icon = _icon(k, 67.0 * k, 50.0 + k * 0.5)
            icon.update(portrait_features={"g": [9.0]},
                        portrait_features_version=ALLY_PORTRAIT_FEATURES_VERSION)
            events += [_frame(k, 67.0 * k), icon]
        rows = session_lifetimes("s", events, ROUNDS[:1], 1.0, lineup=lineup,
                                 gallery={n: [] for n in names}, references=refs)
        (ally,) = [r for r in rows if r["kind"] == "entity" and r["family"] == "ally"]
        self.assertIsNone(ally["agent"])
        self.assertTrue(ally["identity_reason"].startswith("not_a_teammate"))
        self.assertEqual(ally["teammate_fit"], 36.0)

if __name__ == "__main__":
    unittest.main()
