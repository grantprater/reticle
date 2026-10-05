"""The sightline map's segment test and decision_value's fits, on synthetic data."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import decision_value as dv  # noqa: E402
import sightlines as sl  # noqa: E402


class SegmentsClearTest(unittest.TestCase):
    def setUp(self):
        self.m = np.ones((40, 40), bool)

    def test_open_floor_passes(self):
        a = np.array([[2.0, 2.0], [5.0, 30.0]])
        b = np.array([[37.0, 37.0], [30.0, 5.0]])
        self.assertTrue(sl.segments_clear(self.m, a, b).all())

    def test_wall_stops(self):
        m = self.m.copy()
        m[:, 20] = False
        ok = sl.segments_clear(m, np.array([[5.0, 10.0], [5.0, 10.0]]), np.array([[35.0, 12.0], [15.0, 30.0]]))
        self.assertEqual(ok.tolist(), [False, True])

    def test_four_connected_diagonal_wall_stops(self):
        # a staircase wall sealed to 4-connected: every diagonal step has its corner pixel
        m = self.m.copy()
        for i in range(39):
            m[i, i] = False
            m[i, i + 1] = False
        a = np.array([[5.0, 30.0], [10.0, 35.0]])
        b = np.array([[30.0, 5.0], [36.0, 3.0]])
        self.assertFalse(sl.segments_clear(m, a, b).any())

    def test_nearly_symmetric(self):
        """Rounding ties may part a segment from its reverse; rarely."""
        rng = np.random.default_rng(0)
        m = rng.random((40, 40)) > 0.08
        a = rng.uniform(0, 39, (200, 2))
        b = rng.uniform(0, 39, (200, 2))
        fwd, back = sl.segments_clear(m, a, b), sl.segments_clear(m, b, a)
        self.assertGreaterEqual((fwd == back).mean(), 0.95)


class FitTest(unittest.TestCase):
    def test_multinomial_recovers_slopes(self):
        rng = np.random.default_rng(1)
        n = 20000
        x = rng.normal(size=n)
        X = np.column_stack([np.ones(n), x])
        B = np.array([[-1.0, -2.0], [0.8, -0.5]])
        Z = np.column_stack([np.zeros(n), X @ B])
        P = np.exp(Z) / np.exp(Z).sum(1, keepdims=True)
        y = (rng.random(n)[:, None] > P.cumsum(1)).sum(1)
        Bh = dv.mn_fit(X, y, 3, [0.0, 0.0])
        np.testing.assert_allclose(Bh, B, atol=0.08)
        np.testing.assert_allclose(dv.mn_prob(X, Bh).sum(1), 1.0)

    def test_cluster_ci_mean(self):
        diff = np.array([1.0, 1.0, 3.0, 3.0])
        g = np.array(["a", "a", "b", "b"])
        r = dv.cluster_ci(diff, g, boot=200)
        self.assertAlmostEqual(r["mean"], 2.0)
        self.assertLessEqual(r["ci95"][0], r["ci95"][1])


if __name__ == "__main__":
    unittest.main()
