"""Which round an event near a round boundary belongs to."""
from __future__ import annotations

import unittest

from reticle.rounds import final_round, in_round_window, match_over, round_closes


def _ev(t):
    return {"t_first": float(t)}


def _times(seq):
    return [e["t_first"] for e in seq]


class RoundBoundary(unittest.TestCase):
    def test_an_event_at_the_end_belongs_to_the_round_it_ends(self):
        got = in_round_window([_ev(100), _ev(527.5)], 100.0, 527.5, 535.0, ends={527.5})
        self.assertEqual(_times(got), [100.0, 527.5])

    def test_touching_rounds_count_the_shared_instant_once(self):
        ends = {447.5, 527.5}
        seq = [_ev(447.5)]
        first = in_round_window(seq, 335.0, 447.5, 447.5, ends)
        second = in_round_window(seq, 447.5, 527.5, 535.0, ends)
        self.assertEqual((len(first), len(second)), (1, 0))

    def test_a_post_round_kill_belongs_to_the_round_just_decided(self):
        ends = {927.5, 1008.0}
        seq = [_ev(929.0)]
        self.assertEqual(_times(in_round_window(seq, 864.5, 927.5, 935.5, ends)), [929.0])
        self.assertEqual(in_round_window(seq, 935.5, 1008.0, 1015.5, ends), [])

    def test_the_last_round_closes_one_median_gap_after_its_end(self):
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0},
                  {"t_start_ms": 107.0, "t_end_ms": 200.0},
                  {"t_start_ms": 209.0, "t_end_ms": 300.0}]
        self.assertEqual(round_closes(rounds), [107.0, 209.0, 308.0])



class MatchEnd(unittest.TestCase):
    def test_the_match_end_rule(self):
        self.assertTrue(match_over(13, 11))
        self.assertFalse(match_over(13, 12))      # overtime: not two ahead
        self.assertFalse(match_over(12, 12))
        self.assertTrue(match_over(15, 13))
        self.assertFalse(match_over(10, 2))       # a capture cut short, or a surrender

    def _session(self, final_scores):
        # Last decided round ends at 100 s at 12-6; the buy-phase clock resets
        # at 107 s and the scoreline is read until 190 s.
        t = [float(x) for x in range(95, 200)]
        clock = [5000 if x < 107 else 30000 - (x - 107) * 100 for x in range(95, 200)]
        left = [12 if x >= 100 else 11 for x in range(95, 200)]
        right = [6] * len(t)
        if final_scores is None:
            left = [v if x < 191 else None for v, x in zip(left, range(95, 200))]
            right = [v if x < 191 else None for v, x in zip(right, range(95, 200))]
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 100.0, "left_before": 11,
                   "right_before": 6, "won_left": True}]
        return t, left, right, clock, rounds

    def test_an_unread_final_round_is_inferred_with_its_winner(self):
        t, left, right, clock, rounds = self._session(None)
        got = final_round(t, left, right, clock, rounds)
        self.assertEqual((got["t_start_ms"], got["t_end_ms"], got["won_left"]), (107.0, 190.0, True))
        self.assertEqual(got["end_source"], "match_end_rule")

    def test_no_final_round_when_no_single_result_ends_the_match(self):
        t, left, right, clock, rounds = self._session(None)
        rounds[0].update(left_before=9, right_before=2)      # 10-2 after it
        self.assertIsNone(final_round(t, left, right, clock, rounds))


if __name__ == "__main__":
    unittest.main()
