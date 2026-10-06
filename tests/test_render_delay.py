"""The render-delay estimators' pure functions, on synthetic tracks."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import render_delay as rd  # noqa: E402

DT = rd.FRAME_MS


class Velocity(unittest.TestCase):
    def test_uneven_spacing(self):
        t = np.cumsum(np.r_[0, np.tile([4, 5], 10)]) * 1000 / 60.0
        vx, _ = rd.track_velocity(t, 2.0 * t / 1000.0, np.zeros_like(t))
        self.assertTrue(np.allclose(vx, 2.0))

    def test_constant_motion_and_gaps(self):
        t = np.r_[np.arange(20) * DT, 5000 + np.arange(5) * DT]
        x = 3.0 * t / 1000.0
        vx, vy = rd.track_velocity(t, x, np.zeros_like(t))
        self.assertTrue(np.allclose(vx[:20], 3.0))
        self.assertTrue(np.all(np.isnan(vx[20:])))  # a 5-frame segment is too short

    def test_segments(self):
        a, b = rd.segments([0, DT, 2 * DT, 1000, 1000 + DT])
        self.assertEqual(list(a), [0, 3])
        self.assertEqual(list(b), [3, 5])


class Runs(unittest.TestCase):
    def test_breaks_split_runs(self):
        m = np.ones(10, bool)
        st, en = rd.true_runs(m, 3, breaks=np.r_[np.zeros(5, bool), True, np.zeros(4, bool)])
        self.assertEqual(list(zip(st, en)), [(0, 5), (5, 10)])
        st, en = rd.true_runs(m, 6, breaks=np.r_[np.zeros(5, bool), True, np.zeros(4, bool)])
        self.assertEqual(st.size, 0)

    def test_plain(self):
        st, en = rd.true_runs([0, 1, 1, 1, 0, 1], 2)
        self.assertEqual(list(zip(st, en)), [(1, 4)])


class Lockstep(unittest.TestCase):
    def test_trailing_time_is_delay_without_formation_offset(self):
        n, ppm, v, delta = 30, 3.0, 6.0 * 3.0, 0.050   # px/s, s
        t = np.arange(n) * DT / 1000.0
        ps = np.c_[v * t, np.zeros(n)]
        # teammate truly 3 m to the side, drawn delta late
        pm = np.c_[v * (t - delta), np.full(n, 9.0)]
        vel = np.c_[np.full(n, v), np.zeros(n)]
        ok, trail, _a, _v = rd.lockstep(ps, vel, pm, vel, ppm)
        self.assertTrue(ok.all())
        self.assertTrue(np.allclose(trail, 50.0))

    def test_gates(self):
        ps = np.zeros((1, 2))
        pm = np.array([[9.0, 0.0]])
        ok, *_ = rd.lockstep(ps, np.array([[18.0, 0.0]]), pm, np.array([[0.0, 18.0]]), 3.0)
        self.assertFalse(ok[0])  # headings 90 degrees apart

    def test_within_slope(self):
        v = np.r_[10, 12, 14, 20, 22, 24.0]
        a = 5.0 - 0.05 * v + np.r_[0, 0, 0, 3, 3, 3]
        self.assertAlmostEqual(rd.within_slope(a, v, [0, 0, 0, 1, 1, 1]), -0.05)


class DeathTau(unittest.TestCase):
    def test_x_ahead_of_icon(self):
        # icon at 0 moving 20 px/s; X at 2 px, appearing 67 ms after the last frame
        tau = rd.death_tau(0.0, np.array([0.0, 0.0]), np.array([20.0, 0.0]), 67.0, np.array([2.0, 1.0]))
        self.assertAlmostEqual(float(tau), 100.0 - 67.0)

    def test_overrun_is_negative(self):
        tau = rd.death_tau(0.0, np.array([2.0, 0.0]), np.array([20.0, 0.0]), 67.0, np.array([0.0, 0.0]))
        self.assertAlmostEqual(float(tau), -100.0 - 67.0)


class Onsets(unittest.TestCase):
    def test_onset_after_stillness(self):
        t = np.arange(40) * DT
        s = np.r_[np.zeros(20), np.linspace(0, 6, 20)]
        on = rd.onset(t, s, 0, t[-1])
        k = 20 + int(np.ceil(2.5 / (6 / 19)))
        self.assertTrue(t[k - 1] <= on <= t[k])

    def test_no_onset_without_stillness(self):
        t = np.arange(40) * DT
        s = np.r_[np.full(5, 3.0), np.zeros(3), np.full(32, 4.0)]
        self.assertTrue(np.isnan(rd.onset(t, s, 0, t[-1])))

    def test_stop_time(self):
        t = np.arange(150) * DT
        s = np.r_[np.full(30, 5.0), np.zeros(120)]
        ts = rd.stop_time(t, s, (t[60], t[140]), 8000.0)
        self.assertAlmostEqual(ts, t[29])
        self.assertTrue(np.isnan(rd.stop_time(t, np.full(150, 5.0), (t[60], t[140]), 8000.0)))


class Clock(unittest.TestCase):
    def test_drift_recovered(self):
        rng = np.random.default_rng(1)
        t, c, g = [], [], []
        for r in range(5):
            start = 100_000.0 * r
            ts = start + np.arange(0, 100_000, 500.0)
            server = (ts - start) / (1 + 2e-4)
            clock = 100_000 - np.floor(server / 1000.0) * 1000.0
            t.append(ts), c.append(clock), g.append(np.full(ts.size, r))
        allt, allc = np.concatenate(t), np.concatenate(c)
        T, V, G = [], [], []
        for ts, cl, gg in zip(t, c, g):
            a, b = rd.clock_transitions(ts, cl)
            T.append(a), V.append(b), G.append(np.full(a.size, gg[0]))
        s = rd.clock_slope(np.concatenate(T), np.concatenate(V), np.concatenate(G))
        self.assertLess(abs(s - 2e-4), 5e-4)  # 2 Hz samples resolve it only coarsely
        del rng, allt, allc

    def test_live_start_and_segments(self):
        t = np.arange(0, 6000, 500.0)
        c = np.r_[3000, 2000, 2000, 1000, 1000, 0, 0, 99000, 99000, 98000, 98000, 97000.0]
        self.assertEqual(rd.live_start(t, c, 0, 6000), 3500.0 - 250.0)
        self.assertEqual(list(rd.clock_segments(t, c)), [1] * 7 + [2] * 5)
        self.assertTrue(np.isnan(rd.live_start(t, np.full(12, 5000.0), 0, 6000)))


class Stats(unittest.TestCase):
    def test_boot_median_and_verdict(self):
        b = rd.boot_median(np.r_[40, 50, 60, 50.0], [0, 0, 1, 1])
        self.assertEqual(b["est_ms"], 50.0)
        v = rd.recovery_verdict(b, 55.0)
        self.assertTrue(v["recovers"])
        self.assertFalse(rd.recovery_verdict({"est_ms": 50.0, "ci90_ms": [0.0, 200.0]}, 55.0)["recovers"])

    def test_boot_diff(self):
        d = rd.boot_diff([10, 10, 10.0], [4, 4.0])
        self.assertEqual(d["est_ms"], 6.0)
        self.assertEqual(rd.boot_diff([], [1.0])["refused"], "empty_class")

    def test_convergence(self):
        vals = np.r_[200, 50, 50, 50, 50.0]
        rnd = np.r_[1, 2, 3, 4, 5]
        ends = {1: 60_000.0, 2: 120_000.0, 3: 180_000.0, 4: 240_000.0, 5: 300_000.0}
        c = rd.convergence(vals, rnd, ends, 0.0, 50.0, np.median)
        self.assertEqual(c["settled_after_round"], 3)
        self.assertEqual(c["minutes"], 3.0)


class Peek(unittest.TestCase):
    def test_labels(self):
        self.assertEqual(rd.peek_label(3.0, 0.5), ("peek", 0))
        self.assertEqual(rd.peek_label(0.2, 4.0), ("peek", 1))
        self.assertEqual(rd.peek_label(3.0, 3.0)[0], "both_moving")
        self.assertEqual(rd.peek_label(0.1, 0.2)[0], "both_still")
        self.assertEqual(rd.peek_label(1.5, 0.2)[0], "mixed")
        self.assertEqual(rd.peek_label(np.nan, 0.2)[0], "unread")

    def test_speed_and_onset(self):
        t = np.arange(0, 301, 1000 / 128)
        self.assertAlmostEqual(rd.mean_speed(t, 500.0 * t / 1000, np.zeros_like(t)), 500.0)
        self.assertEqual(rd.first_onset([False, True, True], [0, 7.8, 15.6]), 7.8)
        self.assertTrue(np.isnan(rd.first_onset([False, False], [0, 1])))

    def test_summary_shares(self):
        rows = [{"gap_ms": 10.0, "label": "peek", "peeker": "a", "first_seer": "a", "first_hitter": "a",
                 "killer": "a", "censored": False},
                {"gap_ms": -120.0, "label": "peek", "peeker": "b", "first_seer": "a", "first_hitter": "a",
                 "killer": None, "censored": False},
                {"gap_ms": None, "label": "both_still", "peeker": None, "first_seer": "b",
                 "first_hitter": "b", "killer": "b", "censored": True}]
        s = rd.peek_summary(rows)
        self.assertEqual(s["peeker_first_damage"]["share"], 0.5)
        self.assertEqual(s["abs_gap_ms"]["median"], 65.0)
        self.assertEqual(s["censored"], 1)


class HeldOut(unittest.TestCase):
    def test_refused(self):
        with self.assertRaises(SystemExit):
            rd.measure("cea8ecbc94ab")
        with self.assertRaises(SystemExit):
            rd.peek_study("bd7efa02-3033-4dd3-adc0-1143d145e06b")


class BodyGeometry(unittest.TestCase):
    """A wall in the plane x = 0 for y < 0; its edge stands at y = 0."""

    def setUp(self):
        from reticle.line_of_sight import Occluders
        tris = np.array([[[0, -1000, -500], [0, 0, -500], [0, 0, 500]],
                         [[0, -1000, -500], [0, 0, 500], [0, -1000, 500]]], float)
        self.occ = Occluders("synthetic", tris=tris)

    def test_far_player_sees_the_near_one_first(self):
        a = np.array([[-100.0, -20.0, 0.0]])   # 1 m from the edge
        b = np.array([[1000.0, -20.0, 0.0]])   # 10 m from it
        alive = np.array([True])
        a_sees = rd.body_sees(a, np.array([0.0]), np.array([0.0]), b, alive, self.occ, 103.0)
        b_sees = rd.body_sees(b, np.array([180.0]), np.array([0.0]), a, alive, self.occ, 103.0)
        self.assertFalse(a_sees[0])
        self.assertTrue(b_sees[0])

    def test_edge_distances(self):
        ea = np.array([[-100.0, -20.0, 77.0]])
        eb = np.array([[1000.0, -20.0, 77.0]])
        da, db, same = rd.edge_distances(ea, eb, self.occ)
        self.assertAlmostEqual(float(da[0]), 100.0, places=2)
        self.assertAlmostEqual(float(db[0]), 1000.0, places=2)
        self.assertTrue(same[0])


if __name__ == "__main__":
    unittest.main()
