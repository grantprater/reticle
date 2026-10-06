import unittest

import numpy as np

from reticle.frame_join import (MIN_JOIN_RATE, NO_READ_YET, STALE, JoinRefused, grid_join,
                                sampled_state)


def grid_15hz(n: int, phase_ms: float = 0.0) -> np.ndarray:
    """A nominal 15 Hz grid drawn from 60 fps source frames, stepping 4, 5, 4
    frames (66.7, 83.3, 66.7 ms) as the stored streams do."""
    steps = np.resize([4, 5, 4], n)
    frames = np.r_[0, np.cumsum(steps[:-1])]
    return np.round(frames * (1000.0 / 60.0) + phase_ms, 3)


class GridJoinTests(unittest.TestCase):
    def test_an_exact_grid_joins_every_frame_to_itself(self):
        b = grid_15hz(400)
        j = grid_join(b, b, 15.0)
        self.assertIsNone(j.refused)
        self.assertEqual(j.rate, 1.0)
        np.testing.assert_array_equal(j.index, np.arange(b.size))
        self.assertTrue(np.all(j.offset_ms == 0))

    def test_a_phase_shifted_grid_joins_within_half_a_sample(self):
        b = grid_15hz(400)
        for phase in (16.667, 33.333, -16.667):
            a = grid_15hz(399, phase)[1:]
            j = grid_join(a, b, 15.0)
            self.assertIsNone(j.refused, phase)
            self.assertEqual(j.rate, 1.0, phase)
            self.assertLessEqual(float(np.nanmax(np.abs(j.offset_ms))), j.tol_ms + 1e-3)
        # an exact join would have found none of them
        self.assertFalse(np.isin(grid_15hz(399, 16.667), b).any())

    def test_the_declared_rate_sets_the_tolerance(self):
        j = grid_join([10.0, 40.0], [0.0, 1000.0], 15.0, min_rate=0.0)
        self.assertAlmostEqual(j.tol_ms, 1000.0 / 30.0)
        np.testing.assert_array_equal(j.index, [0, -1])

    def test_a_tie_goes_to_the_earlier_frame(self):
        j = grid_join([50.0], [0.0, 100.0], 10.0)
        self.assertEqual(int(j.index[0]), 0)

    def test_an_unsorted_b_is_indexed_as_given(self):
        j = grid_join([1.0, 99.0, 201.0], np.array([200.0, 0.0, 100.0]), 50.0)
        np.testing.assert_array_equal(j.index, [1, 2, 0])

    def test_a_sparse_a_joins_and_a_gap_in_b_borrows_no_neighbour(self):
        b = grid_15hz(400)
        self.assertEqual(grid_join(b[::7], b, 15.0).rate, 1.0)
        gap = np.r_[b[:100], b[200:]]
        j = grid_join(b, gap, 15.0, min_rate=0.0)
        self.assertAlmostEqual(j.rate, 300 / 400)
        self.assertTrue(np.all(j.index[101:199] == -1))

    def test_a_low_join_rate_refuses_with_its_reason(self):
        b = grid_15hz(400)
        j = grid_join(b, np.r_[b[:100], b[200:]], 15.0)
        self.assertIn("below", j.refused)
        self.assertIsNone(j.index)
        self.assertAlmostEqual(j.rate, 0.75)
        with self.assertRaises(JoinRefused):
            j.require()
        keep = int(np.ceil(MIN_JOIN_RATE * 400))
        j = grid_join(b, b[:keep], 15.0)
        self.assertIsNone(j.refused)
        self.assertGreaterEqual(j.rate, MIN_JOIN_RATE)

    def test_empty_streams_refuse(self):
        self.assertIsNotNone(grid_join([], [0.0, 1.0], 15.0).refused)
        self.assertIsNotNone(grid_join([0.0], [], 15.0).refused)
        self.assertIsNone(grid_join([4.0], [5.0], 15.0).refused)


class SampledStateTests(unittest.TestCase):
    def test_the_latest_read_at_or_before_holds_with_its_age(self):
        s = sampled_state([50.0, 100.0, 399.0, 950.0, 1200.0], [100.0, 400.0, 1000.0],
                          600.0, None)
        np.testing.assert_array_equal(s.index, [-1, 0, 0, 1, 2])
        np.testing.assert_allclose(s.age_ms[1:], [0.0, 299.0, 550.0, 200.0])
        self.assertEqual(s.reason, [NO_READ_YET, None, None, None, None])

    def test_a_read_older_than_the_max_age_is_stale_not_refused(self):
        s = sampled_state([100.0, 900.0], [0.0], 500.0, None)
        np.testing.assert_array_equal(s.index, [0, -1])
        self.assertEqual(s.reason, [None, STALE])
        self.assertTrue(np.isnan(s.age_ms[1]))

    def test_a_carried_prediction_holds_and_says_so(self):
        s = sampled_state([250.0, 100.0], [200.0, 0.0], 1000.0, [True, False])
        np.testing.assert_array_equal(s.index, [0, 1])
        np.testing.assert_array_equal(s.carried, [True, False])

    def test_no_reads_is_null_everywhere(self):
        s = sampled_state([1.0, 2.0], [], 100.0, None)
        np.testing.assert_array_equal(s.index, [-1, -1])
        self.assertEqual(s.reason, [NO_READ_YET, NO_READ_YET])


if __name__ == "__main__":
    unittest.main()
