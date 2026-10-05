"""prototypes/tray_gate.py: the alive gate from stored rounds and deaths."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import tray_gate as tg  # noqa: E402


class TestAliveSpans(unittest.TestCase):
    ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 10000.0, "t_close_ms": 12000.0},
              {"round_no": 2, "t_start_ms": 12000.0, "t_end_ms": 30000.0, "t_close_ms": 32000.0}]

    def test_the_player_death_cuts_the_round_to_its_close(self):
        deaths = [{"round_no": 1, "side": "ally", "t_ms": 5000.0, "victim": "Sage"},
                  {"round_no": 1, "side": "ally", "t_ms": 6000.0, "victim": "Jett"},
                  {"round_no": 2, "side": "enemy", "t_ms": 20000.0, "victim": "Sage"}]
        live, dead = tg.alive_spans(self.ROUNDS, deaths, "Sage")
        # alive to the death plus the margin; dead to the close less it; an
        # enemy Sage's death cuts nothing
        self.assertEqual(dead, [[6000.0, 11000.0]])
        self.assertEqual(live, [[-1000.0, 6000.0], [11000.0, 33000.0]])

    def test_no_player_death_keeps_every_round(self):
        live, dead = tg.alive_spans(self.ROUNDS, [], "Sage")
        self.assertEqual((live, dead), ([[-1000.0, 33000.0]], []))

    def test_row_time(self):
        self.assertEqual(tg.row_time("ult_cast", {"drop": {"t_drop_ms": 5.0}}), 5.0)
        self.assertIsNone(tg.row_time("ult_cast", {"drop": None}))
        self.assertIsNone(tg.row_time("ability_state", {"kind": "claim", "witness": "audio",
                                                        "observed_at_ms": 1.0}))
        self.assertEqual(tg.row_time("ability_state", {"kind": "claim", "witness": "tray_fill",
                                                       "observed_at_ms": 2.0}), 2.0)


if __name__ == "__main__":
    unittest.main()
