import unittest
from unittest.mock import patch

import numpy as np

from reticle import lighting
from reticle import cone
from reticle.minimap_diagnostics import R_MAX, SUPPORT_OUTER_PX, light_support
from reticle.team_vision import TeamVision, at_plan, frame_row


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

    def test_a_warm_up_frame_leaves_the_chain_where_a_full_frame_does(self):
        crop = np.zeros((60, 60, 3), np.uint8)
        full, warm = _vision(), _vision()

        def drift(i):
            return [_ally(20.0 + 0.4 * i)]

        with patch("reticle.team_vision.widget_drawn", return_value=True),                 patch("reticle.team_vision.self_icons", return_value=[]):
            for i in range(20):
                with patch("reticle.team_vision.ally_icons", return_value=drift(i)):
                    a = full.step(crop, i * 66.7)
                    b = warm.step(crop, i * 66.7, masks=i == 19)
        self.assertIsNotNone(b.observable)
        self.assertEqual(frame_row(a), frame_row(b))

    def test_at_plan_takes_both_neighbours_and_merges_overlapping_warm_ups(self):
        times = [i * 100.0 for i in range(100)]
        runs = at_plan(times, [250.0, 400.0, 9000.0], warmup_ms=300.0)
        self.assertEqual(len(runs), 2)
        frames, emit = runs[0]
        self.assertEqual(emit, {200.0, 300.0, 400.0})
        self.assertEqual(frames, [0.0, 100.0, 200.0, 300.0, 400.0])
        self.assertEqual(runs[1], ([8600.0, 8700.0, 8800.0, 8900.0, 9000.0],
                                   {8900.0, 9000.0}))

    def test_at_plan_starts_the_chain_at_the_last_gap_the_tracks_expire_across(self):
        times = [i * 100.0 for i in range(10)] + [5000.0 + i * 100.0 for i in range(10)]
        (frames, emit), = at_plan(times, [5550.0])
        self.assertEqual(frames[0], 5000.0)
        self.assertEqual(emit, {5500.0, 5600.0})
        (frames, _), = at_plan(times, [550.0])
        self.assertEqual(frames[0], 0.0)


class SpeedEquivalenceTests(unittest.TestCase):
    """The faster forms compute what the plain forms computed."""

    def test_the_chunked_cast_equals_the_loop_over_long_rays(self):
        rng = np.random.default_rng(3)
        p = rng.random((300, 280)) > 0.002
        for deg in (0.0, 37.0, 181.0, 290.0):
            a = cone.raycast(p, 140.3, 150.6, deg)
            b = cone._raycast_loop(p, 140.3, 150.6, deg)
            self.assertTrue(np.array_equal(a, b))

    def test_a_union_of_cast_cones_is_the_observable_area(self):
        p = np.ones((80, 80), bool)
        icons = [(20.0, 20.0, 0.0), (60.0, 60.0, 200.0), (40.0, 40.0, None)]
        agg, per = cone.observable(p, icons)
        self.assertTrue(np.array_equal(cone.union(per, p.shape), agg))
        sub, _ = cone.observable(p, [icons[1]])
        self.assertTrue(np.array_equal(cone.union([per[1]], p.shape), sub))
        self.assertFalse(cone.union([], p.shape).any())

    def test_light_support_in_a_window_counts_what_the_whole_widget_did(self):
        rng = np.random.default_rng(5)
        lit, known = rng.random((120, 110)) > 0.5, rng.random((120, 110)) > 0.2
        for x, y, sc in ((3.2, 4.9, 1.0), (60.5, 70.1, 1.3), (108.0, 119.0, 0.8)):
            yy, xx = np.ogrid[:120, :110]
            d2 = (xx - x) ** 2 + (yy - y) ** 2
            region = known & (d2 > (R_MAX * sc) ** 2) & (d2 <= (SUPPORT_OUTER_PX * sc) ** 2)
            got = light_support(x, y, lit, known, sc)
            self.assertEqual(got["known"], int(region.sum()))
            self.assertEqual(got["lit"], int((region & lit).sum()))


if __name__ == "__main__":
    unittest.main()
