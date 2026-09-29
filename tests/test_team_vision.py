import unittest
from unittest.mock import patch

import numpy as np

from reticle import lighting
from reticle.team_vision import TeamVision, frame_row


def _vision():
    floor = np.ones((60, 60), bool)
    return TeamVision(floor, floor, np.zeros((60, 60)), width=60)


def _ally(x=30.0):
    return {"cx": x, "cy": 30.0, "r": 5, "cov": 0.9, "facing": 0.0}


class TeamVisionTests(unittest.TestCase):
    def test_the_stored_row_carries_the_masks_the_chain_computed(self):
        vision = _vision()
        crop = np.zeros((60, 60, 3), np.uint8)
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.self_icons", return_value=[]), \
                patch("reticle.team_vision.ally_icons", side_effect=lambda *a, **k: [_ally()]):
            for i in range(12):
                got = vision.step(crop, i * 66.7)
        self.assertEqual(got.widget, "drawn")
        self.assertTrue(got.observable_all.any())
        row = frame_row(got, frame_idx=7)
        self.assertTrue(np.array_equal(lighting.unpack_mask(row["observable"]), got.observable))
        self.assertTrue(np.array_equal(lighting.unpack_mask(row["observable_all"]),
                                       got.observable_all))
        self.assertEqual(len(row["icons"]), len(got.tracked))
        icon = row["icons"][0]
        self.assertEqual(icon["role"], "ally")
        # The first frame is a boundary, so the track is eligible and casts.
        self.assertTrue(icon["eligible"])
        self.assertEqual(icon["casts"], icon["facing"] is not None)
        self.assertEqual(row["observable_px"], int(got.observable.sum()))

    def test_an_absent_widget_stores_no_area_and_says_why(self):
        vision = _vision()
        with patch("reticle.team_vision.widget_drawn", return_value=False):
            got = vision.step(np.zeros((60, 60, 3), np.uint8), 0.0)
        row = frame_row(got)
        self.assertEqual(row["widget"], "not_drawn")
        self.assertIsNone(row["observable"])
        self.assertEqual(row["reason"], "widget unavailable")

    def test_an_ineligible_track_casts_no_adjudicated_cone(self):
        vision = _vision()
        crop = np.zeros((60, 60, 3), np.uint8)
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.self_icons", return_value=[]):
            with patch("reticle.team_vision.ally_icons", return_value=[_ally(10.0)]):
                for i in range(12):
                    vision.step(crop, i * 66.7)
            # A second icon appears far from every anchor after the boundary:
            # the lifecycle calls it unexplained, so it casts nothing.
            with patch("reticle.team_vision.ally_icons",
                       return_value=[_ally(10.0), {**_ally(50.0), "cy": 50.0}]):
                for i in range(12, 24):
                    got = vision.step(crop, i * 66.7)
        row = frame_row(got)
        late = [ic for ic in row["icons"] if ic["x"] == 50.0]
        self.assertEqual(len(late), 1)
        self.assertFalse(late[0]["eligible"])
        self.assertFalse(late[0]["casts"])
        self.assertLessEqual(row["observable_px"], row["observable_all_px"])


if __name__ == "__main__":
    unittest.main()
