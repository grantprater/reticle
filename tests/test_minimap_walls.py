"""Unit tests for minimap ability wall and linear detection.

Verifies [owns:ability-detection] claimed by reticle.minimap.
Cites [domain:abilities/viper-toxic-screen], [domain:abilities/phoenix-blaze],
[domain:abilities/neon-fast-lane], and [domain:abilities/cypher-trapwire].
"""
from __future__ import annotations

import unittest
import cv2
import numpy as np

from reticle.minimap import (
    detect_ability_walls,
    detect_trapwire_anchors,
    extract_static_lines,
    _line_similarity,
)


class MinimapWallsTest(unittest.TestCase):
    def test_empty_slab_returns_no_walls(self):
        crop = np.full((120, 120, 3), 100, dtype=np.uint8)
        floor = np.ones((120, 120), dtype=bool)
        walls = detect_ability_walls(crop, floor, min_length=15.0)
        self.assertEqual(len(walls), 0)

    def test_isolated_line_is_detected(self):
        crop = np.full((120, 120, 3), 80, dtype=np.uint8)
        floor = np.ones((120, 120), dtype=bool)
        # Draw bright line segment from (20, 30) to (80, 30) of width 3
        cv2.line(crop, (20, 30), (80, 30), (240, 240, 240), 3)
        walls = detect_ability_walls(crop, floor, min_length=20.0)
        self.assertGreaterEqual(len(walls), 1)
        # Verify length and orientation
        w = walls[0]
        self.assertAlmostEqual(w["cy"], 30.0, delta=4.0)
        self.assertAlmostEqual(w["cx"], 50.0, delta=10.0)
        self.assertGreaterEqual(w["length"], 35.0)
        self.assertAlmostEqual(abs(w["angle_deg"]) % 180.0, 0.0, delta=10.0)

    def test_static_lines_and_self_xy_are_filtered(self):
        crop = np.full((120, 120, 3), 80, dtype=np.uint8)
        floor = np.ones((120, 120), dtype=bool)
        # Draw two lines: line1 at y=30, line2 at (60, 60)
        cv2.line(crop, (20, 30), (80, 30), (240, 240, 240), 3)
        cv2.line(crop, (50, 60), (70, 60), (240, 240, 240), 3)

        # Static lines includes line 1
        static_lines = [(20.0, 30.0, 80.0, 30.0)]
        # Self icon sits at (60, 60)
        self_xy = (60.0, 60.0)

        walls = detect_ability_walls(crop, floor, static_lines=static_lines,
                                     self_xy=self_xy, min_length=15.0)
        # Both lines should be suppressed
        self.assertEqual(len(walls), 0)

    def test_color_hint_classification(self):
        crop = np.full((120, 120, 3), 80, dtype=np.uint8)
        floor = np.ones((120, 120), dtype=bool)
        # Draw teal line: BGR=(240, 160, 80)
        cv2.line(crop, (20, 40), (70, 40), (240, 160, 80), 3)
        # Draw warm flame line: BGR=(60, 100, 230)
        cv2.line(crop, (20, 80), (70, 80), (60, 100, 230), 3)

        teal_walls = detect_ability_walls(crop, floor, min_length=20.0, color_hint="teal")
        warm_walls = detect_ability_walls(crop, floor, min_length=20.0, color_hint="warm")

        self.assertGreaterEqual(len(teal_walls), 1)
        self.assertAlmostEqual(teal_walls[0]["cy"], 40.0, delta=4.0)

        self.assertGreaterEqual(len(warm_walls), 1)
        self.assertAlmostEqual(warm_walls[0]["cy"], 80.0, delta=4.0)

    def test_trapwire_anchors_detected(self):
        crop = np.full((100, 100, 3), 70, dtype=np.uint8)
        floor = np.ones((100, 100), dtype=bool)
        # Draw two anchor discs at (50, 40) and (50, 56)
        cv2.circle(crop, (50, 40), 3, (240, 240, 240), -1)
        cv2.circle(crop, (50, 56), 3, (240, 240, 240), -1)
        # Draw connecting wire
        cv2.line(crop, (50, 40), (50, 56), (220, 180, 150), 2)

        trapwires = detect_trapwire_anchors(crop, floor, min_wire_length=6.0, max_wire_length=25.0)
        self.assertGreaterEqual(len(trapwires), 1)
        tw = trapwires[0]
        self.assertAlmostEqual(tw["cx"], 50.0, delta=3.0)
        self.assertAlmostEqual(tw["cy"], 48.0, delta=4.0)
        self.assertEqual(tw["archetype"], "trapwire_dual")

    def test_walls_outside_radar_circle_are_filtered(self):
        crop = np.full((120, 120, 3), 80, dtype=np.uint8)
        floor = np.ones((120, 120), dtype=bool)
        cv2.line(crop, (2, 2), (20, 2), (240, 240, 240), 3)
        walls = detect_ability_walls(crop, floor, min_length=10.0)
        self.assertEqual(len(walls), 0)


if __name__ == "__main__":
    unittest.main()
