"""The minimap lag study's estimators and the scorer's clock, on synthetic data."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import minimap_lag as ml  # noqa: E402
import replay_truth as rt  # noqa: E402
from reticle import replay_source  # noqa: E402


class CaptureToReplay(unittest.TestCase):
    def test_slope_one_matches_frames_to_replay(self):
        t = np.array([0.0, 1000.0, 2_000_000.0])
        self.assertTrue(np.allclose(rt.capture_to_replay(t, 5000.0, 1.0, -450.0),
                                    replay_source.frames_to_replay(t, 5000.0, -450.0)))

    def test_slope_inverts_the_fit(self):
        replay = np.array([0.0, 600_000.0, 2_400_000.0])
        cap = 1234.0 + 1.0001 * replay
        self.assertTrue(np.allclose(rt.capture_to_replay(cap, 1234.0, 1.0001, 0.0), replay))
        # a positive lag reads the replay earlier
        self.assertTrue(np.allclose(rt.capture_to_replay(cap, 1234.0, 1.0001, 50.0), replay - 50.0))

    def test_class_lags(self):
        self.assertAlmostEqual(rt.SELF_LAG_MS, -450.0 + 100.0 / 3.0)
        self.assertAlmostEqual(rt.REMOTE_LAG_MS - rt.SELF_LAG_MS, 50.0)


class BestExtra(unittest.TestCase):
    def test_finds_the_true_lag_with_an_interval(self):
        rng = np.random.default_rng(1)
        extras = ml.EXTRAS_MS
        true = extras[24]   # +100 ms
        n = 3000
        noise = rng.normal(0, 0.3, n)
        speed = 20.0   # px/s
        E = np.abs((extras[None, :] - true) / 1000.0 * speed + noise[:, None])
        groups = np.repeat(np.arange(30), n // 30)
        b = ml.best_extra(E, groups, n_boot=100)
        self.assertAlmostEqual(b["best_extra_ms"], round(true, 1))
        self.assertLessEqual(b["ci90_ms"][0], b["best_extra_ms"])
        self.assertGreaterEqual(b["ci90_ms"][1], b["best_extra_ms"])
        self.assertEqual(b["groups"], 30)

    def test_drops_nan_rows_and_refuses_empty(self):
        E = np.full((5, ml.EXTRAS_MS.size), np.nan)
        self.assertIsNone(ml.best_extra(E, np.zeros(5)))


class ImpliedLag(unittest.TestCase):
    def test_trailing_icon_is_positive(self):
        # player at x=10 moving +x at 20 px/s; icon 1 px behind = 50 ms late
        il = ml.implied_lag_ms(np.array([9.0]), np.array([0.0]), np.array([10.0]), np.array([0.0]),
                               np.array([20.0]), np.array([0.0]))
        self.assertAlmostEqual(float(il[0]), 50.0)

    def test_leading_icon_is_negative(self):
        il = ml.implied_lag_ms(np.array([0.0]), np.array([11.0]), np.array([0.0]), np.array([10.0]),
                               np.array([0.0]), np.array([10.0]))
        self.assertAlmostEqual(float(il[0]), -100.0)


class PairedGap(unittest.TestCase):
    def test_gap_in_shared_rounds_only(self):
        rnd_a = np.repeat([0, 1, 2, 3], 40)
        rnd_b = np.repeat([0, 1, 2, 3, 4], 40)
        il_a = np.repeat([10.0, 20.0, 30.0, 40.0], 40)
        il_b = np.repeat([60.0, 70.0, 80.0, 90.0, 500.0], 40)
        g = ml.paired_gap(rnd_a, il_a, rnd_b, il_b, n_boot=50)
        self.assertEqual(g["rounds"], 4)
        self.assertAlmostEqual(g["gap_ms"], 50.0)
        self.assertEqual(g["ci90_ms"], [50.0, 50.0])

    def test_refuses_few_rounds(self):
        g = ml.paired_gap(np.zeros(40), np.zeros(40), np.zeros(40), np.ones(40))
        self.assertEqual(g["refused"], "too_few_rounds")


class Drift(unittest.TestCase):
    def test_slope_and_rho(self):
        t = np.repeat(np.arange(10) * 100_000.0, 50)
        lag = 1e-4 * t + 20.0
        d = ml.lag_drift(t, lag, np.repeat(np.arange(10), 50))
        self.assertAlmostEqual(d["slope_ms_per_ms"], 1e-4, places=7)
        self.assertAlmostEqual(d["spearman_rho"], 1.0)
        self.assertEqual(d["rounds"], 10)


class RoundStartAnchor(unittest.TestCase):
    def test_drift_of_stored_starts(self):
        rs = np.arange(1, 9) * 100_000.0
        a = 5000.0
        rows = [{"t_start_ms": float(x + a + 200.0 + 2e-4 * x), "start_source": "clock_reset"}
                for x in rs]
        rows.append({"t_start_ms": 1.0, "start_source": "capture_start"})
        out = ml.round_start_anchor(rows, rs, a)
        self.assertEqual(out["n"], 8)
        self.assertAlmostEqual(out["slope_ms_per_ms"], 2e-4, places=7)
        self.assertAlmostEqual(out["spearman_rho"], 1.0)


class Isolated(unittest.TestCase):
    def test_neighbour_within_radius(self):
        X = np.array([[0.0, 5.0, np.nan], [0.0, 50.0, 1.0]])
        Y = np.zeros_like(X)
        iso = ml.isolated(X, Y, np.array([0, 0]), 10.0)
        self.assertEqual(iso.tolist(), [False, False])
        iso = ml.isolated(X, Y, np.array([1, 1]), 10.0)
        self.assertEqual(iso.tolist(), [False, True])
        iso = ml.isolated(X, Y, np.array([-1, -1]), 10.0)
        self.assertEqual(iso.tolist(), [False, False])


class SpeedBins(unittest.TestCase):
    def test_bins_and_labels(self):
        bins = ml.POSTHOC["bins"]
        self.assertEqual(ml.speed_bin([0.5, 2.0, 6.75, 9.0], bins).tolist(), [0, 1, 2, 3])
        self.assertEqual(ml.bin_label(2, bins), "4-8")
        self.assertEqual(ml.bin_label(3, bins), "8+")


if __name__ == "__main__":
    unittest.main()
