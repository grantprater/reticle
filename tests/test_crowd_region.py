"""The crowd prototype's geometry and emergence assignment
(`prototypes/crowd_region.py`) on synthetic inputs; none is evidence."""
from __future__ import annotations

import math
import unittest

import numpy as np

from prototypes.crowd_region import assign_emergers, hull_area_perimeter, region_distance


def pad(points, k=6):
    a = np.full((k, 2), np.nan)
    a[:len(points)] = points
    return a


class RegionDistance(unittest.TestCase):
    def test_point_segment_and_triangle(self):
        A = np.stack([pad([(0, 0)]), pad([(0, 0), (10, 0)]), pad([(0, 0), (10, 0), (0, 10)])])
        px = np.array([3.0, 5.0, 2.0])
        py = np.array([4.0, 3.0, 2.0])
        d = region_distance(px, py, A)
        self.assertAlmostEqual(d[0], 5.0)          # to the point
        self.assertAlmostEqual(d[1], 3.0)          # to the segment
        self.assertAlmostEqual(d[2], 0.0)          # inside the triangle

    def test_outside_a_square_hull(self):
        A = pad([(0, 0), (10, 0), (10, 10), (0, 10)])[None]
        self.assertAlmostEqual(region_distance(np.array([15.0]), np.array([5.0]), A)[0], 5.0)
        self.assertAlmostEqual(region_distance(np.array([5.0]), np.array([5.0]), A)[0], 0.0)

    def test_hull_area(self):
        area, per = hull_area_perimeter(np.array([(0, 0), (10, 0), (10, 10), (0, 10)], float))
        self.assertAlmostEqual(area, 100.0)
        self.assertAlmostEqual(per, 40.0)
        self.assertEqual(hull_area_perimeter(np.array([(1, 1)], float)), (0.0, 0.0))
        self.assertTrue(math.isclose(hull_area_perimeter(np.array([(0, 0), (3, 4)], float))[1], 10.0))


class AssignEmergers(unittest.TestCase):
    MEMBERS = [{"agent": "Jett"}, {"agent": "Sova"}]

    def test_names_then_elimination(self):
        out = assign_emergers(["Sova", None], self.MEMBERS)
        self.assertEqual((out[0]["member"], out[0]["how"]), (1, "name"))
        self.assertEqual((out[1]["member"], out[1]["how"]), (0, "elimination"))

    def test_two_unnamed_is_a_tie(self):
        out = assign_emergers([None, None], self.MEMBERS)
        self.assertEqual([o["how"] for o in out], ["tie", "tie"])
        self.assertEqual([o["member"] for o in out], [None, None])
        self.assertEqual(out[0]["alternatives"], ["Jett", "Sova"])

    def test_named_outsider_is_kept_as_a_surprise(self):
        out = assign_emergers(["Reyna"], self.MEMBERS)
        self.assertEqual((out[0]["member"], out[0]["how"]), (None, "name_not_member"))
        self.assertEqual(out[0]["alternatives"], ["Jett", "Sova"])

    def test_no_member(self):
        self.assertEqual(assign_emergers([None], [])[0]["how"], "no_hidden_member")


if __name__ == "__main__":
    unittest.main()
