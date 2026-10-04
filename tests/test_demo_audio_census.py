"""The demo audio census's pure rules (`prototypes/demo_audio_census.py`) on
synthetic data: the window's peaks, coincident drops, intervening casts,
the offset cluster, the slot statistics and the proposed phase."""
from __future__ import annotations

import math
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import demo_audio_census as dac  # noqa: E402


class WindowTest(unittest.TestCase):
    def test_peaks_carry_offsets_from_the_cast_and_clip_to_the_track(self):
        t = np.zeros(3000, np.float32)
        t[1050], t[1400], t[1420] = 2.0, 1.0, 0.9      # 1420 is within PEAK_GAP of 1400
        w = dac.window_peaks(t, 1000)
        self.assertEqual(w["max"], 2.0)
        self.assertEqual(w["at"], 0.5)
        self.assertEqual([p[0] for p in w["peaks"]], [0.5, 4.0])
        self.assertEqual(w["span"], [-2.0, 15.0])
        w = dac.window_peaks(t, 100)                    # the window starts at frame 0
        self.assertEqual(w["span"][0], -1.0)

    def test_the_level_rate_gives_alpha_per_window(self):
        lam = dac.window_lambda()
        self.assertAlmostEqual(dac.window_rate(lam), dac.ALPHA, places=9)
        self.assertEqual(dac.rate_at(np.array([1.0, 2.0, 3.0]), 2.0, 0.5), 4.0)
        self.assertTrue(math.isnan(dac.rate_at(np.array([1.0]), 0.5, 0.0)))


class CastsTest(unittest.TestCase):
    def test_coincident_casts_are_other_slots_at_one_instant(self):
        casts = [{"t_ms": 1000.0, "slot": "Q"}, {"t_ms": 1010.0, "slot": "E"},
                 {"t_ms": 5000.0, "slot": "Q"}, {"t_ms": 5020.0, "slot": "Q"}]
        np.testing.assert_array_equal(dac.coincident(casts), [True, True, False, False])

    def test_a_cast_intervenes_between_the_cast_and_its_peak(self):
        others = [("E", 13000.0), ("C", 8000.0)]
        self.assertEqual(dac.intervening(others, 10000.0, 2.5), ["E"])   # E at +3.0 <= 2.5 + 1
        self.assertEqual(dac.intervening(others, 10000.0, 1.5), [])
        self.assertEqual(dac.intervening(others, 10000.0, -1.5), ["C"])  # C at -2.0 >= -2.5
        self.assertEqual(dac.intervening(others, 10000.0, 0.0), [])


class ClusterTest(unittest.TestCase):
    def test_the_largest_cluster_within_the_span(self):
        k, cl = dac.largest_cluster([0.1, 5.0, 0.6, 9.0, 0.9])
        self.assertEqual(k, 3)
        self.assertEqual(cl, [0.1, 0.6, 0.9])
        self.assertEqual(dac.largest_cluster([]), (0, []))

    def _f(self, at, fired=True, near=(), co=False, n=1, span=0.0):
        own = fired and not near
        return {"fired": fired, "at": at, "near_other": list(near), "coincident": co,
                "own_fired": own, "own_at": at if own else None,
                "n_fire_peaks": n, "fire_span": span, "key": "k"}

    def test_slot_stats_leave_coincident_casts_out_and_clean_intervened_fires(self):
        st = dac.slot_stats([self._f(0.2), self._f(0.4), self._f(3.0, near=["E"]),
                             self._f(0.3, co=True), self._f(0.0, fired=False)])
        self.assertEqual((st["n_casts"], st["n_coincident"], st["n_used"], st["n_fired"]),
                         (5, 1, 4, 3))
        self.assertEqual(st["k_in"], 2)
        self.assertTrue(st["stable"])
        self.assertTrue(st["stable_clean"])
        self.assertEqual(st["near_other"], ["E"])
        st = dac.slot_stats([self._f(3.0, near=["E"]), self._f(3.2, near=["E"]), self._f(0.1)])
        self.assertTrue(st["stable"])
        self.assertFalse(st["stable_clean"])

    def test_ongoing_needs_repeated_peaks_on_two_casts(self):
        st = dac.slot_stats([self._f(1.0, n=4, span=5.0), self._f(1.2, n=3, span=2.5)])
        self.assertTrue(st["ongoing"])
        st = dac.slot_stats([self._f(1.0, n=4, span=5.0), self._f(1.2, n=1)])
        self.assertFalse(st["ongoing"])


class PhaseTest(unittest.TestCase):
    def test_timing_first_then_the_name_role(self):
        self.assertEqual(dac.propose_phase(False, None, None, False, 0)[0], "unknown")
        self.assertEqual(dac.propose_phase(False, 1.0, "impact", False, 2)[0], "unknown")
        self.assertEqual(dac.propose_phase(True, 0.1, "impact", False, 2)[0], "cast")
        self.assertIn("equip", dac.propose_phase(True, -0.8, None, False, 2)[1])
        self.assertEqual(dac.propose_phase(True, 2.0, "impact", False, 2)[0], "landing")
        self.assertEqual(dac.propose_phase(True, 2.0, "projectile", False, 2)[0], "in-flight")
        self.assertEqual(dac.propose_phase(True, 9.0, "end", False, 2)[0], "expire")
        self.assertEqual(dac.propose_phase(True, 2.0, None, False, 2)[0], "unknown")
        self.assertEqual(dac.propose_phase(True, 2.0, "impact", True, 2)[0], "ongoing")
        for args in ((True, 0.0, None, False, 2), (True, 3.0, "loop", False, 2)):
            self.assertIn(dac.propose_phase(*args)[0], dac.PHASES)


if __name__ == "__main__":
    unittest.main()
