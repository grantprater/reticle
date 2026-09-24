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


if __name__ == "__main__":
    unittest.main()
