"""Which round an event first seen on a round boundary belongs to."""
from __future__ import annotations

import unittest

from reticle.rounds import in_round_window


def _ev(t):
    return {"t_first": float(t)}


class RoundBoundary(unittest.TestCase):
    def test_an_event_at_the_end_belongs_to_the_round_it_ends(self):
        got = in_round_window([_ev(100), _ev(527.5)], 100.0, 527.5, ends={527.5})
        self.assertEqual([e["t_first"] for e in got], [100.0, 527.5])

    def test_touching_rounds_count_the_shared_instant_once(self):
        ends = {447.5, 527.5}
        seq = [_ev(447.5)]
        first = in_round_window(seq, 335.0, 447.5, ends)
        second = in_round_window(seq, 447.5, 527.5, ends)
        self.assertEqual((len(first), len(second)), (1, 0))

    def test_the_post_round_gap_belongs_to_no_round(self):
        ends = {927.5, 1008.0}
        seq = [_ev(929.0)]
        self.assertEqual(in_round_window(seq, 864.5, 927.5, ends), [])
        self.assertEqual(in_round_window(seq, 935.5, 1008.0, ends), [])


if __name__ == "__main__":
    unittest.main()
