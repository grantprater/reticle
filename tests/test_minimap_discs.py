"""Unit tests for minimap ability disc detection.

Verifies [owns:ability-detection] claimed by reticle.minimap.
"""
from __future__ import annotations

import unittest
import numpy as np

from reticle.minimap import detect_ability_discs, BH_K, BH_MIN


class MinimapDiscsTest(unittest.TestCase):
    def test_empty_slab_returns_no_discs(self):
        gray = np.full((100, 100), 120, dtype=np.uint8)
        floor = np.ones((100, 100), dtype=bool)
        discs = detect_ability_discs(gray, floor, k=15, bh_min=50)
        self.assertEqual(len(discs), 0)

    def test_isolated_dark_disc_is_detected(self):
        # Background: gray 180
        gray = np.full((100, 100), 180, dtype=np.uint8)
        floor = np.ones((100, 100), dtype=bool)
        # Draw dark circle at (50, 50) of radius 5 (intensity 20)
        import cv2
        cv2.circle(gray, (50, 50), 5, 20, -1)
        discs = detect_ability_discs(gray, floor, k=19, bh_min=80)
        self.assertEqual(len(discs), 1)
        self.assertAlmostEqual(discs[0]["cx"], 50.0, delta=2.0)
        self.assertAlmostEqual(discs[0]["cy"], 50.0, delta=2.0)

    def test_static_peaks_and_self_xy_are_filtered(self):
        gray = np.full((100, 100), 180, dtype=np.uint8)
        floor = np.ones((100, 100), dtype=bool)
        import cv2
        # Two dark spots: one at (30, 30), one at (70, 70)
        cv2.circle(gray, (30, 30), 5, 20, -1)
        cv2.circle(gray, (70, 70), 5, 20, -1)
        # Exclude (30, 30) via static_peaks, and (70, 70) via self_xy
        static_peaks = [(30.0, 30.0, 150.0)]
        self_xy = (70.0, 70.0)
        discs = detect_ability_discs(gray, floor, static_peaks=static_peaks,
                                     self_xy=self_xy, k=19, bh_min=80)
        self.assertEqual(len(discs), 0)

    def test_discs_outside_radar_circle_are_filtered(self):
        gray = np.full((100, 100), 180, dtype=np.uint8)
        floor = np.ones((100, 100), dtype=bool)
        import cv2
        cv2.circle(gray, (5, 5), 4, 20, -1)
        discs = detect_ability_discs(gray, floor, k=15, bh_min=50)
        self.assertEqual(len(discs), 0)


if __name__ == "__main__":
    unittest.main()
