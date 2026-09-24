"""Which round an event near a round boundary belongs to."""
from __future__ import annotations

import unittest

from reticle.rounds import in_round_window, round_closes


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


if __name__ == "__main__":
    unittest.main()
