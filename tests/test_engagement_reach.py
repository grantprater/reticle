"""engagement_reach's pure helpers, on synthetic data."""
import sys
import types
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import engagement_reach as er  # noqa: E402
import sightlines as sl  # noqa: E402


class AttackingTeamTest(unittest.TestCase):
    def test_halves_and_overtime(self):
        n = np.array([0, 11, 12, 23, 24, 25, 26, 27])
        self.assertEqual(er.attacking_team(n).tolist(),
                         ["Red", "Red", "Blue", "Blue", "Red", "Blue", "Red", "Blue"])


class OwnMaskTest(unittest.TestCase):
    def test_keeps_the_observer_side(self):
        m = er.own_mask(np.array([True, False]), 2)
        self.assertEqual(m.tolist(), [[1, 0, 1, 0], [0, 1, 0, 1]])


class RegionRepsTest(unittest.TestCase):
    def test_nearest_centroid_inside_region(self):
        S = types.SimpleNamespace()
        S.cell_xy = np.array([[0, 0], [100, 0], [200, 0], [1000, 0], [1100, 0], [5000, 0]], float)
        S.region = {er.NODE_GRAPH: np.array([0, 0, 0, 1, 1, -1])}
        rep = er.region_reps(S)
        self.assertEqual(rep.tolist(), [1, 3])


class ReachRowsTest(unittest.TestCase):
    def test_batches_agree_with_one_call(self):
        S = types.SimpleNamespace()
        dm = np.array([[0, 10, 20], [10, 0, 10], [20, 10, 0]], np.uint16)
        S.reach_m = lambda p, vis: sl.Sightlines.reach_m(types.SimpleNamespace(dist_dm=dm), p, vis)
        vis = np.array([[False, False, True], [True, False, False]])
        cells = np.array([0, 1, 2, 0])
        row = np.array([0, 0, 1, 1])
        got = er.reach_rows(S, cells, vis, row, batch=3)
        self.assertEqual(got.tolist(), [2.0, 1.0, 2.0, 0.0])


class StatsTest(unittest.TestCase):
    def test_ratio_of_sums(self):
        r = er.ratio_ci(np.array([1.0, 1.0, 2.0]), np.array([2.0, 2.0, 4.0]), np.array(["a", "b", "c"]))
        self.assertAlmostEqual(r["value"], 0.5)
        self.assertEqual(r["ci95"], [0.5, 0.5])

    def test_diff_mean(self):
        v = np.array([1.0, 0.0, 1.0, 0.0])
        g = np.array(["a", "a", "b", "b"])
        d = er.diff_mean(v, g, np.array([True, False, True, False]), np.array([False, True, False, True]))
        self.assertEqual(d["diff"], 1.0)

    def test_kappa(self):
        self.assertEqual(er.kappa([0, 1, 2, 1], [0, 1, 2, 1]), 1.0)
        self.assertLess(er.kappa([0, 0, 1, 1], [1, 1, 0, 0]), 0.0)


if __name__ == "__main__":
    unittest.main()
