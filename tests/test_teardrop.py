import math
import unittest
from unittest.mock import patch

import numpy as np

from reticle import cone, teardrop
from reticle.team_vision import TeamVision, frame_row


def _crop(cx, cy, deg, size=80):
    """A yellow teardrop silhouette on a dark crop, drawn by the reader's own model."""
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    m = teardrop.render(xx - cx, yy - cy, np.float32(math.radians(deg)))
    crop = np.zeros((size, size, 3), np.uint8)
    # min(G, R) - B = 70 on the silhouette: yellowness 1.0.
    crop[..., 1] = crop[..., 2] = (80 * m).astype(np.uint8)
    crop[..., 0] = (10 * m).astype(np.uint8)
    return crop


class TeardropTests(unittest.TestCase):
    def test_the_fit_finds_the_centre_the_ring_fit_misses(self):
        # The ring fit sits toward the apex; the teardrop's centre does not.
        crop = _crop(40.3, 38.6, 30.0)
        got = teardrop.fit_teardrop(crop, 43.0, 40.0)
        self.assertTrue(got["read"])
        self.assertLess(math.hypot(got["x"] - 40.3, got["y"] - 38.6), 0.2)
        self.assertLess(abs(got["deg"] - 30.0), 2.0)

    def test_no_yellow_is_unread_with_a_reason(self):
        got = teardrop.fit_teardrop(np.zeros((80, 80, 3), np.uint8), 40.0, 40.0)
        self.assertEqual(got, {"read": False, "reason": "no_yellow"})

    def test_an_unread_teardrop_falls_back_to_the_ring_fit_and_says_so(self):
        o = teardrop.OriginReader().origin(np.zeros((80, 80, 3), np.uint8), 40.0, 41.0)
        self.assertEqual((o["x"], o["y"], o["source"], o["reason"]),
                         (40.0, 41.0, "ring_fit", "no_yellow"))

    def test_a_repeated_image_returns_the_fit_a_fresh_one_gives(self):
        crop = _crop(40.0, 40.0, -60.0)
        reader = teardrop.OriginReader()
        first = reader.origin(crop, 41.0, 39.0)
        with patch("reticle.teardrop.fit_teardrop", side_effect=AssertionError("refit")):
            again = reader.origin(crop.copy(), 41.0, 39.0)
        self.assertEqual(first, again)
        self.assertEqual(first["source"], "teardrop")


class SelfConeOriginTests(unittest.TestCase):
    def test_the_self_cone_starts_at_the_teardrop_centre(self):
        floor = np.ones((80, 80), bool)
        # width 465 is widget scale 1.0, the scale the teardrop constants were fitted at.
        vision = TeamVision(floor, floor, np.zeros((80, 80)), width=465)
        crop = _crop(30.0, 40.0, 0.0)
        det = {"cx": 33.0, "cy": 40.0, "r": 8, "cov": 0.9, "facing": 0.0}
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.ally_icons", return_value=[]), \
                patch("reticle.team_vision.self_icons", side_effect=lambda *a, **k: [dict(det)]):
            for i in range(12):
                got = vision.step(crop, i * 66.7)
        self.assertEqual(got.self_origin["source"], "teardrop")
        ox, oy = got.self_origin["x"], got.self_origin["y"]
        self.assertLess(math.hypot(ox - 30.0, oy - 40.0), 0.2)
        want = cone.observable(floor, [(ox, oy, got.resolved[-1][2])], visible=floor)[0]
        self.assertTrue(np.array_equal(got.observable_all, want))
        icon = frame_row(got)["icons"][-1]
        self.assertEqual(icon["role"], "self")
        # The track keeps the ring fit's position; the origin is stored beside it.
        self.assertEqual((icon["x"], icon["y"]), (33.0, 40.0))
        self.assertEqual(icon["origin"]["source"], "teardrop")


if __name__ == "__main__":
    unittest.main()
