import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import device_deactivation as D  # noqa: E402


class SincePreviousTests(unittest.TestCase):
    def test_uses_the_most_recent_prior_event(self):
        self.assertEqual(D.since_previous(100.0, [10.0, 50.0, 90.0]), 10.0)

    def test_none_when_nothing_happened_yet(self):
        self.assertIsNone(D.since_previous(5.0, [10.0, 50.0]))

    def test_an_event_at_the_same_instant_counts(self):
        self.assertEqual(D.since_previous(50.0, [50.0]), 0.0)


class PermutationTests(unittest.TestCase):
    """The gap has to survive shuffling which devices are called dim."""

    def rows(self, dim_times, live_times):
        return ([{"dim": True, "since_death_ms": t} for t in dim_times]
                + [{"dim": False, "since_death_ms": t} for t in live_times])

    def test_a_real_separation_is_significant(self):
        rng = np.random.default_rng(0)
        got = D.permutation_gap(self.rows([1, 2, 3, 4, 5], [90, 95, 100, 105, 110]),
                                rng, n=500)
        self.assertGreater(got["observed_gap_ms"], 0)
        self.assertLessEqual(got["p_value"], 0.05)

    def test_interleaved_groups_are_not(self):
        rng = np.random.default_rng(0)
        got = D.permutation_gap(self.rows([10, 30, 50, 70, 90], [20, 40, 60, 80, 100]),
                                rng, n=500)
        self.assertGreater(got["p_value"], 0.05)

    def test_it_refuses_rather_than_reporting_a_gap_from_one_side(self):
        rng = np.random.default_rng(0)
        got = D.permutation_gap(self.rows([1], [2, 3, 4]), rng, n=100)
        self.assertIsNone(got["p_value"])


class ExclusionTests(unittest.TestCase):
    def test_walls_and_barriers_are_excluded_from_the_prediction(self):
        """The player: the only deployed abilities that do NOT deactivate on
        death are walls and barriers, so counting them as failures would be
        scoring the rule against cases it does not claim."""
        self.assertTrue(any(w in "deadlock:barrier mesh" for w in D.PERSISTS_THROUGH_DEATH))
        self.assertFalse(any(w in "deadlock:sonic sensor" for w in D.PERSISTS_THROUGH_DEATH))


if __name__ == "__main__":
    unittest.main()
