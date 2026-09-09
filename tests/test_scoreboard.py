import types
import unittest
from unittest.mock import patch

import numpy as np

from reticle.reconciliation import adjudicate_scoreboard_credits
from reticle.scoreboard import Row, ScoreboardRead, ScoreboardReader, read_scoreboard
from reticle.version import SCOREBOARD_VERSION


class ScoreboardTests(unittest.TestCase):
    def test_reader_emits_context_free_credit_and_portrait_evidence(self):
        row = Row("ally", 10, 20, 1, 2, 3, True, credits=2250,
                  credits_candidate=2250, credits_confidence=.81,
                  credits_margin=.06)
        board = ScoreboardRead(True, (row,), 100, 500)
        portrait = {"display_row": 0, "portrait_x0": 90, "portrait_y0": 10,
                    "portrait_x1": 98, "portrait_y1": 20,
                    "portrait_detail": 50.0,
                    "portrait_composition": [0.0] * 90}
        with patch("reticle.scoreboard.Templates.load", return_value=object()), \
                patch("reticle.scoreboard.read_scoreboard", return_value=board), \
                patch("reticle.scoreboard.portrait_observations",
                      return_value=[portrait]):
            reader = ScoreboardReader("test")
            reader.feed(types.SimpleNamespace(
                frame=np.zeros((30, 600, 3), np.uint8), frame_idx=12, t_ms=500.0))
        event = reader.events("s")[1]
        self.assertEqual(event["credits"], 2250)
        self.assertEqual(event["portrait_composition"], [0.0] * 90)
        self.assertTrue(event["is_player"])
        self.assertEqual(event["scoreboard_version"], SCOREBOARD_VERSION)
        self.assertNotIn("agent", event)
        self.assertNotIn("player_id", event)

    def test_portrait_descriptor_is_normalized_and_context_free(self):
        from reticle.scoreboard import portrait_observations
        rows = tuple(Row("ally" if i < 5 else "enemy", 20 + i * 20,
                         40 + i * 20, 0, 0, 0, False) for i in range(10))
        board = ScoreboardRead(True, rows, 100, 650)
        frame = np.zeros((240, 700, 3), np.uint8)
        # Texture across the portrait search band makes its structural trough
        # and every row's descriptor available without assigning an identity.
        rng = np.random.default_rng(4)
        frame[20:240, 80:160] = rng.integers(0, 256, (220, 80, 3), np.uint8)
        got = portrait_observations(frame, board)
        self.assertEqual(len(got), 10)
        self.assertTrue(all(len(r["portrait_composition"]) == 90 for r in got))
        self.assertTrue(all(abs(sum(r["portrait_composition"]) - 1.0) < 1e-5
                            for r in got))

    def test_enemy_rows_take_height_from_independent_ally_block(self):
        green = np.zeros((300, 700), bool)
        red = np.zeros_like(green)
        green[10:110, 50:650] = True
        # Connected history makes the red region taller than five player rows.
        red[120:260, 50:650] = True
        frame = np.zeros((300, 700, 3), np.uint8)
        detail = (0, None, 1.0, 1.0, 0)
        with patch("reticle.scoreboard._slabs", return_value=(green, red)), \
                patch("reticle.scoreboard._read_cell_detail", return_value=detail):
            board = read_scoreboard(frame, object(), 0, 0)
        self.assertTrue(board.open_)
        self.assertEqual((board.rows[5].y0, board.rows[-1].y1), (160, 260))
        self.assertEqual({r.y1 - r.y0 for r in board.rows[:5]}, {20})
        self.assertEqual({r.y1 - r.y0 for r in board.rows[5:]}, {20})

    def test_adjudicator_preserves_cross_channel_disagreement(self):
        rows = []
        for frame, t in ((1, 1000.0), (2, 1500.0)):
            rows.append({"kind": "row_observation", "observation_key": f"s:{frame}:0",
                         "t_ms": t, "display_row": 0, "team": "ally",
                         "credits": 2250 if frame == 2 else None,
                         "credits_candidate": 2250, "is_player": True})
        claims = {"s:1:0": [{"channel": "killfeed", "player_id": "ally:Phoenix"}]}
        result = adjudicate_scoreboard_credits(rows, claims)[0]
        self.assertEqual(result["credits"], 2250)
        self.assertEqual(result["credit_status"], "repeated_consensus")
        self.assertIsNone(result["player_id"])
        self.assertEqual(result["identity_status"], "disagreement")
        self.assertEqual({c["channel"] for c in result["identity_claims"]},
                         {"killfeed", "scoreboard_highlight"})

    def test_adjudicator_resolves_agreeing_independent_claims(self):
        row = {"kind": "row_observation", "observation_key": "s:1:3",
               "t_ms": 1000.0, "display_row": 3, "team": "enemy",
               "credits": 4400, "credits_candidate": 4400, "is_player": False}
        claims = {"s:1:3": [
            {"channel": "lineup", "player_id": "enemy:Skye"},
            {"channel": "minimap", "player_id": "enemy:Skye"},
        ]}
        result = adjudicate_scoreboard_credits([row], claims)[0]
        self.assertEqual(result["credits"], 4400)
        self.assertEqual(result["credit_status"], "single_strict_read")
        self.assertEqual(result["player_id"], "enemy:Skye")
        self.assertEqual(result["identity_status"], "resolved")


if __name__ == "__main__":
    unittest.main()
