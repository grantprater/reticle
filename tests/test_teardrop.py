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
        o = teardrop.SelfConeReader().read(np.zeros((80, 80, 3), np.uint8), 40.0, 41.0)
        self.assertEqual((o["x"], o["y"], o["deg"], o["origin"], o["reason"]),
                         (40.0, 41.0, None, "ring_fit", "no_yellow"))

    def test_a_repeated_image_returns_the_fit_a_fresh_one_gives(self):
        crop = _crop(40.0, 40.0, -60.0)
        reader = teardrop.SelfConeReader()
        first = reader.read(crop, 41.0, 39.0)
        with patch("reticle.teardrop.fit_teardrop", side_effect=AssertionError("refit")):
            again = reader.read(crop.copy(), 41.0, 39.0)
        self.assertEqual(first, again)
        self.assertEqual(first["origin"], "teardrop")


def _teal(cx, cy, deg, scale=1.0, size=80):
    """A teal ally teardrop drawn by the ally class's own model at `scale`."""
    c = teardrop.ICON_CLASSES["ally"]
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
    m = teardrop.render(xx - cx, yy - cy, np.float32(math.radians(deg)),
                        c.r_in * scale, c.r_out * scale, c.L * scale, teardrop.EDGE * scale)
    crop = np.zeros((size, size, 3), np.uint8)
    # min(G, B) - R = 80 and G = B on the silhouette: tealness 1.0.
    crop[..., 0] = crop[..., 1] = (80 * m).astype(np.uint8)
    return crop


class IconTeardropTests(unittest.TestCase):
    def test_the_ally_fit_finds_centre_and_facing_at_the_widget_s_scale(self):
        # A 331 px widget draws the icon at 0.712 of the 465 px size.
        crop = _teal(40.4, 37.7, -120.0, scale=331 / 465)
        got = teardrop.fit_icon(crop, "ally", 42.0, 36.0, scale=331 / 465)
        self.assertTrue(got["read"])
        self.assertLess(math.hypot(got["x"] - 40.4, got["y"] - 37.7), 0.3)
        self.assertLess(abs((got["deg"] + 120.0 + 180.0) % 360.0 - 180.0), 2.0)

    def test_an_unkeyed_window_is_unread_with_a_reason(self):
        got = teardrop.fit_icon(np.zeros((80, 80, 3), np.uint8), "enemy", 40.0, 40.0)
        self.assertEqual(got, {"cls": "enemy", "read": False, "reason": "no_key"})

    def test_the_pose_reader_falls_back_to_the_ring_fit_and_says_so(self):
        o = teardrop.IconPoseReader("ally").read(np.zeros((80, 80, 3), np.uint8), 40.0, 41.0)
        self.assertEqual((o["x"], o["y"], o["deg"], o["origin"], o["reason"]),
                         (40.0, 41.0, None, "ring_fit", "no_key"))

    def test_the_pose_reader_returns_the_fit_a_fresh_one_gives(self):
        crop = _teal(40.0, 40.0, 45.0)
        reader = teardrop.IconPoseReader("ally")
        first = reader.read(crop, 41.0, 39.0)
        with patch("reticle.teardrop.fit_icon", side_effect=AssertionError("refit")):
            again = reader.read(crop.copy(), 41.0, 39.0)
        self.assertEqual(first, again)
        self.assertEqual(first["origin"], "teardrop")
        fresh = teardrop.fit_icon(crop, "ally", 41.0, 39.0)
        self.assertEqual((first["x"], first["y"], first["deg"]), (fresh["x"], fresh["y"], fresh["deg"]))


def _run(crop, det, frames=12):
    floor = np.ones((80, 80), bool)
    # width 465 is widget scale 1.0, the scale the teardrop constants were fitted at.
    vision = TeamVision(floor, floor, np.zeros((80, 80)), width=465)
    with patch("reticle.team_vision.widget_drawn", return_value=True),             patch("reticle.team_vision.ally_icons", return_value=[]),             patch("reticle.team_vision.self_icons", side_effect=lambda *a, **k: [dict(det)]):
        for i in range(frames):
            got = vision.step(crop, i * 66.7)
    return floor, got


class SelfConeTests(unittest.TestCase):
    def test_the_self_cone_starts_at_the_teardrop_centre_along_its_facing(self):
        # The ring fit says 0 degrees; the teardrop points at 90.
        det = {"cx": 30.0, "cy": 43.0, "r": 8, "cov": 0.9, "facing": 0.0}
        floor, got = _run(_crop(30.0, 40.0, 90.0), det)
        sc = got.self_cone
        self.assertEqual((sc["origin"], sc["facing"]), ("teardrop", "teardrop"))
        self.assertLess(math.hypot(sc["x"] - 30.0, sc["y"] - 40.0), 0.2)
        self.assertLess(abs(got.resolved[-1][2] - 90.0), 2.0)
        want = cone.observable(floor, [(sc["x"], sc["y"], got.resolved[-1][2])], visible=floor)[0]
        self.assertTrue(np.array_equal(got.observable_all, want))
        icon = frame_row(got)["icons"][-1]
        self.assertEqual(icon["role"], "self")
        # The track keeps the ring fit's position; the cone's record sits beside it.
        self.assertEqual((icon["x"], icon["y"]), (30.0, 43.0))
        self.assertEqual(icon["facing"], got.resolved[-1][2])
        self.assertEqual(icon["self_cone"]["origin"], "teardrop")

    def test_an_unread_teardrop_keeps_the_track_bearing_and_says_so(self):
        det = {"cx": 30.0, "cy": 40.0, "r": 8, "cov": 0.9, "facing": 0.0}
        floor, got = _run(np.zeros((80, 80, 3), np.uint8), det)
        sc = got.self_cone
        self.assertEqual((sc["origin"], sc["facing"], sc["reason"]), ("ring_fit", "track", "no_yellow"))
        self.assertEqual(got.resolved[-1][2], sc["track_deg"])
        want = cone.observable(floor, [(30.0, 40.0, sc["track_deg"])], visible=floor)[0]
        self.assertTrue(np.array_equal(got.observable_all, want))


if __name__ == "__main__":
    unittest.main()
