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

    def test_red_inside_the_ally_block_is_not_the_enemy_block(self):
        green = np.zeros((300, 700), bool)
        red = np.zeros_like(green)
        green[10:110, 50:650] = True
        # The ally slab over a purple backdrop also passes the red test, and
        # the real enemy slab is too faint to make a block.
        red[30:108, 50:650] = True
        red[160:190, 50:650] = True
        frame = np.zeros((300, 700, 3), np.uint8)
        detail = (0, None, 1.0, 1.0, 0)
        with patch("reticle.scoreboard._slabs", return_value=(green, red)),                 patch("reticle.scoreboard._read_cell_detail", return_value=detail):
            board = read_scoreboard(frame, object(), 0, 0)
        self.assertFalse(board.open_)

    def test_an_enemy_block_anchored_into_the_ally_rows_closes_the_board(self):
        green = np.zeros((300, 700), bool)
        red = np.zeros_like(green)
        green[10:110, 50:650] = True
        red[110:200, 50:650] = True       # a short run at the ally bottom
        frame = np.zeros((300, 700, 3), np.uint8)
        detail = (0, None, 1.0, 1.0, 0)
        with patch("reticle.scoreboard._slabs", return_value=(green, red)),                 patch("reticle.scoreboard._read_cell_detail", return_value=detail):
            board = read_scoreboard(frame, object(), 0, 0)
        self.assertFalse(board.open_)

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

class PortraitBandTests(unittest.TestCase):
    """A degenerate scoreboard row must refuse, not raise.

    `cvtColor` asserts on an empty Mat, so one row of no height took down a
    whole corpus re-scan mid-run before this was guarded.
    """

    def frame(self, h=200, w=800):
        return np.full((h, w, 3), 40, np.uint8)

    def test_a_row_with_no_height_is_skipped_rather_than_read(self):
        from reticle.scoreboard import portrait_observations
        good = Row("ally", 10, 40, 1, 2, 3, True)
        flat = Row("ally", 60, 61, 1, 2, 3, True)     # y1 - 1 == y0 + 1 - 1
        board = ScoreboardRead(True, (good, flat), 300, 700)
        out = portrait_observations(self.frame(), board)
        self.assertEqual([o["display_row"] for o in out], [0])

    def test_every_row_degenerate_reads_nothing_at_all(self):
        from reticle.scoreboard import portrait_observations
        rows = tuple(Row("ally", 60 + i, 61 + i, 1, 2, 3, True) for i in range(3))
        board = ScoreboardRead(True, rows, 300, 700)
        self.assertEqual(portrait_observations(self.frame(), board), [])

    def test_a_row_past_the_frame_reads_nothing(self):
        from reticle.scoreboard import portrait_observations
        board = ScoreboardRead(True, (Row("ally", 900, 940, 1, 2, 3, True),),
                               300, 700)
        self.assertEqual(portrait_observations(self.frame(), board), [])


class CloseReasonTests(unittest.TestCase):
    """Each refusal branch of `read_scoreboard` names itself; open reads name none."""

    def read(self, green, red):
        frame = np.zeros(green.shape + (3,), np.uint8)
        detail = (0, None, 1.0, 1.0, 0)
        with patch("reticle.scoreboard._slabs", return_value=(green, red)), \
                patch("reticle.scoreboard._read_cell_detail", return_value=detail):
            return read_scoreboard(frame, object(), 0, 0)

    def masks(self):
        return np.zeros((400, 700), bool), np.zeros((400, 700), bool)

    def test_an_open_board_carries_no_reason(self):
        green, red = self.masks()
        green[10:110, 50:650] = True
        red[150:250, 50:650] = True
        board = self.read(green, red)
        self.assertTrue(board.open_)
        self.assertIsNone(board.reason)

    def test_a_black_frame_has_no_green_rows(self):
        board = read_scoreboard(np.zeros((1080, 1920, 3), np.uint8), object())
        self.assertEqual((board.open_, board.reason), (False, "green_no_rows"))

    def test_green_blocks_outside_the_height_band(self):
        green, red = self.masks()
        green[10:60, 50:650] = True                     # 50 rows < MIN_BLOCK_H
        self.assertEqual(self.read(green, red).reason, "green_short")
        green, red = self.masks()
        green[10:350, 50:650] = True                    # 340 rows > MAX_BLOCK_H
        self.assertEqual(self.read(green, red).reason, "green_tall")

    def test_red_blocks_below_the_ally_block(self):
        green, red = self.masks()
        green[10:110, 50:650] = True
        red[30:108, 50:650] = True                      # only inside the ally block
        self.assertEqual(self.read(green, red).reason, "red_no_rows")
        red[160:190, 50:650] = True                     # 30 rows below it
        self.assertEqual(self.read(green, red).reason, "red_short")
        green, red = self.masks()
        green[10:110, 50:650] = True
        red[110:395, 50:650] = True                     # 285 rows is in band ...
        self.assertIsNone(self.read(green, red).reason)
        green = np.zeros((500, 700), bool)
        red = np.zeros_like(green)
        green[10:110, 50:650] = True
        red[110:420, 50:650] = True                     # ... 310 rows is not
        self.assertEqual(self.read(green, red).reason, "red_tall")

    def test_enemy_rows_anchored_into_the_ally_block(self):
        green, red = self.masks()
        green[10:110, 50:650] = True
        red[110:200, 50:650] = True     # 90 rows ending 90 below: anchored at 100
        board = self.read(green, red)
        self.assertEqual((board.open_, board.reason), (False, "enemy_overlaps_ally"))

    def test_a_block_of_wide_rows_with_no_dense_column(self):
        green = np.zeros((400, 1920), bool)
        red = np.zeros_like(green)
        # Every row holds 520 green pixels, in one of three disjoint places,
        # so each column is green on a third of the block's rows.
        for y in range(10, 110):
            k = y % 3
            green[y, 600 * k:600 * k + 520] = True
        red[150:250, 50:650] = True
        board = self.read(green, red)
        self.assertEqual((board.open_, board.reason), (False, "no_dense_columns"))

    def test_a_narrow_table(self):
        green, red = self.masks()
        # A 400 px dense core; every third row is wide enough to count, and
        # the blocks merge across the gaps, but the wings are not dense.
        green[10:110, 150:550] = True
        green[10:110:3, 20:150] = True
        green[10:110:3, 550:680] = True
        red[150:250, 50:650] = True
        board = self.read(green, red)
        self.assertEqual((board.open_, board.reason), (False, "table_narrow"))

    def test_every_reason_is_declared(self):
        from reticle.scoreboard import CLOSE_REASONS
        self.assertEqual(len(set(CLOSE_REASONS)), 12)

    def test_the_reader_stores_a_sample_row_per_frame_offered(self):
        closed = ScoreboardRead(False, reason="red_short")
        with patch("reticle.scoreboard.Templates.load", return_value=object()), \
                patch("reticle.scoreboard.read_scoreboard", return_value=closed):
            reader = ScoreboardReader("test")
            for i in range(3):
                reader.feed(types.SimpleNamespace(
                    frame=np.zeros((30, 600, 3), np.uint8), frame_idx=30 * i, t_ms=500.0 * i))
        events = reader.events("s")
        self.assertEqual(events[0]["closed_reasons"], {"red_short": 3})
        samples = [e for e in events if e["kind"] == "sample"]
        self.assertEqual([(s["frame_idx"], s["open"], s["reason"]) for s in samples],
                         [(0, False, "red_short"), (30, False, "red_short"),
                          (60, False, "red_short")])
        self.assertEqual({s["scoreboard_version"] for s in samples}, {SCOREBOARD_VERSION})


class StripAnchorTests(unittest.TestCase):
    """Where the round-history strip is present, the blocks are the runs that
    meet its marker lines; where it is not, the tallest runs, as at 0.7.0.

    The frames are drawn in pixels at 1920x1080 and read by the real colour
    test and the real strip witness; only the digit reader is stubbed."""

    GREEN, RED, WORLD, BAND = (70, 120, 70), (60, 60, 130), (50, 80, 140), (90, 90, 90)
    X0, X1 = 572, 1348            # the table's columns
    RECT = (883, 486, 1037, 594)  # the profile's centre ROI at 1920x1080

    def frame(self, lines=True, ally=(340, 510), enemy=(568, 738), world=(738, 1000),
              green_band=0):
        from reticle import scoreboard_strip as strip
        f = np.full((1080, 1920, 3), 40, np.uint8)
        f[ally[1]:enemy[0] if enemy else 568, self.X0:self.X1] = self.BAND
        f[ally[0]:ally[1] + green_band, self.X0:self.X1] = self.GREEN
        if enemy:
            f[enemy[0]:enemy[1], self.X0:self.X1] = self.RED
        if world:
            f[world[0]:world[1], :] = self.WORLD   # warm floor passes the red test
        if lines:
            for y in strip.ROW_Y:
                for k in range(6):
                    x = self.RECT[0] + 12 + 22 * k
                    f[y:y + 2, x:x + 2] = 30
        return f

    def read(self, frame, rect=RECT, icons=None):
        detail = (0, None, 1.0, 1.0, 0)
        with patch("reticle.scoreboard._read_cell_detail", return_value=detail):
            return read_scoreboard(frame, object(), 0, 0, rect, icons)

    def test_world_below_the_enemy_block_is_cut_off_at_the_board(self):
        board = self.read(self.frame())
        self.assertEqual((board.open_, board.anchor, board.strip), (True, "strip", "present"))
        self.assertEqual((board.edges, board.confirm), (("run", "strip"), "red_run"))
        self.assertEqual([(r.team, r.y0, r.y1) for r in board.rows],
                         [("ally", 340 + 34 * k, 374 + 34 * k) for k in range(5)]
                         + [("enemy", 568 + 34 * k, 602 + 34 * k) for k in range(5)])

    def test_without_the_strip_the_tallest_run_decides_as_at_0_7_0(self):
        board = self.read(self.frame(lines=False))
        self.assertEqual((board.open_, board.reason, board.anchor, board.strip),
                         (False, "red_tall", "tallest_run", "absent"))
        # Not consulted at all: the same verdict, with no strip verdict.
        board = self.read(self.frame(), rect=None)
        self.assertEqual((board.open_, board.reason, board.anchor, board.strip),
                         (False, "red_tall", "tallest_run", None))

    def test_a_taller_world_run_no_longer_takes_the_enemy_rows(self):
        # The floor is its own red run, taller than the enemy block: at 0.7.0
        # it took the enemy rows off the board.
        world = (800, 1080)
        old = self.read(self.frame(lines=False, world=world))
        self.assertTrue(old.open_)
        self.assertEqual(old.rows[5].y0, 1080 - 170)
        board = self.read(self.frame(world=world))
        self.assertEqual((board.open_, board.anchor, board.edges), (True, "strip", ("run", "run")))
        self.assertEqual((board.rows[5].y0, board.rows[9].y1), (568, 738))
        # Rows on a run that ends where the ally height puts it keep the 0.7.0 place.
        same = self.read(self.frame(lines=False, world=None))
        self.assertEqual([(r.y0, r.y1) for r in same.rows], [(r.y0, r.y1) for r in board.rows])

    def test_a_strip_with_no_slab_run_beside_it_refuses(self):
        board = self.read(self.frame(enemy=None, world=(800, 1080)))
        self.assertEqual((board.open_, board.reason, board.anchor), (False, "red_not_at_strip", "strip"))
        board = self.read(self.frame(ally=(300, 480)))
        self.assertEqual((board.open_, board.reason), (False, "green_not_at_strip"))
        board = self.read(self.frame(enemy=(568, 640), world=None))
        self.assertEqual((board.open_, board.reason), (False, "red_short_at_strip"))

    def test_a_red_run_inside_the_span_the_line_predicts_confirms_the_rows(self):
        # The slab's top rows fail the red test (a pale world behind them), so
        # no red run begins at the line; the line places the rows, and the red
        # run below confirms a slab there.
        board = self.read(self.frame(enemy=(600, 738)))
        self.assertEqual((board.open_, board.edges, board.confirm),
                         (True, ("run", "strip"), "red_overlap"))
        self.assertEqual((board.rows[5].y0, board.rows[9].y1), (568, 738))
        # Under half the ally height of red in the span confirms nothing.
        board = self.read(self.frame(enemy=(660, 738), world=None))
        self.assertEqual((board.open_, board.reason), (False, "red_not_at_strip"))

    def test_the_portraits_confirm_rows_no_red_run_does(self):
        frame = self.frame(enemy=None, world=None)
        seen = []

        def scorer(score):
            def agent(frame, box, icons):
                seen.append(box)
                return {"portrait_agent_score": score}
            return agent

        with patch("reticle.scoreboard.portrait_agent", side_effect=scorer(0.9)):
            board = self.read(frame, icons={"Omen": None})
        self.assertEqual((board.open_, board.edges, board.confirm),
                         (True, ("run", "strip"), "portraits"))
        self.assertEqual([(r.team, r.y0) for r in board.rows[5:]],
                         [("enemy", 568 + 34 * k) for k in range(5)])
        self.assertEqual(seen, [(self.X0, 568 + 34 * k, self.X0 + 34, 602 + 34 * k)
                                for k in range(5)])
        # One portrait under the gate refuses the board; so do missing icons.
        scores = iter([0.9, 0.9, 0.80, 0.9, 0.9])
        with patch("reticle.scoreboard.portrait_agent",
                   side_effect=lambda f, b, i: {"portrait_agent_score": next(scores)}):
            board = self.read(frame, icons={"Omen": None})
        self.assertEqual((board.open_, board.reason, board.confirm), (False, "red_not_at_strip", None))
        self.assertEqual(self.read(frame).reason, "red_not_at_strip")
        # The tallest-run rule never asks the portraits.
        self.assertIsNone(self.read(self.frame(lines=False, world=None)).confirm)

    def test_a_green_band_is_cut_off_at_the_upper_line(self):
        board = self.read(self.frame(green_band=30))   # green world across the upper line
        self.assertEqual((board.open_, board.edges), (True, ("strip", "strip")))
        self.assertEqual((board.rows[0].y0, board.rows[4].y1), (340, 510))

    def test_the_strip_rectangle_is_the_profile_roi_at_the_measured_size(self):
        from reticle.scoreboard import strip_rect
        self.assertEqual(strip_rect("valorant-16x9", 1920, 1080), self.RECT)
        self.assertIsNone(strip_rect("valorant-16x9", 2560, 1440))
        self.assertIsNone(strip_rect("no-such-profile", 1920, 1080))


if __name__ == "__main__":
    unittest.main()
