import unittest
from unittest.mock import patch

import numpy as np

from reticle import lighting
from reticle import cone
from reticle.minimap_diagnostics import R_MAX, SUPPORT_OUTER_PX, light_support
from reticle.team_vision import StoredAllyPoses, TeamVision, at_plan, frame_row


def _vision():
    # The crops are black, so no teardrop reads; the ring-fit fallback lets the
    # synthetic detections cast, which these tests of the chain's bookkeeping need.
    floor = np.ones((60, 60), bool)
    return TeamVision(floor, floor, np.zeros((60, 60)), width=60, ring_fallback=True)


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

    def test_the_stored_product_reads_ally_icon_and_refuses_an_unread_frame(self):
        floor = np.ones((60, 60), bool)
        ring = {"r": 5, "cov": 0.9, "inner": 0.0, "inner_v": 100.0, "lobe": 0.4, "area": 80,
                "map_diff": 40.0}
        audit = {"prior": None, "full": {"x": 30.0, "y": 30.0, "deg": 88.0, "ncc": 0.7,
                                         "margin": 0.1, "read": True, "reason": None}}
        rows = [
            {"kind": "frame", "frame_idx": 3, "t_ms": 0.0, "widget_drawn": True},
            {"kind": "frame", "frame_idx": 4, "t_ms": 100.0, "widget_drawn": False},
            # A teardrop read: its centre and facing cast.
            {"kind": "icon", "frame_idx": 3, "cx": 30.5, "cy": 30.25, "facing": 90.0,
             "facing_source": "teardrop",
             "ring": {"cx": 31.0, "cy": 32.0, "facing": 270.0}, "family": "ally",
             "pose": {"origin": "teardrop", "ncc": 0.8, "reason": None, "facing_reason": None,
                      "search": "full", "surprise": None, "rests_on": "s:ally:1",
                      "audit": audit}, **ring},
            # An unread teardrop: the stream keeps the ring fit's facing, which
            # this chain drops without `ring_fallback`.
            {"kind": "icon", "frame_idx": 3, "cx": 10.0, "cy": 10.0, "facing": 45.0,
             "facing_source": "ring_fit",
             "ring": {"cx": 10.0, "cy": 10.0, "facing": 45.0}, "family": "ally",
             "pose": {"origin": "ring_fit", "ncc": 0.3, "reason": "low_ncc",
                      "facing_reason": None}, **ring},
            {"kind": "icon", "frame_idx": 3, "cx": 50.0, "cy": 50.0, "facing": 0.0,
             "family": "barrier", "facing_source": "teardrop", "pose": {"origin": "teardrop"},
             **ring},
            {"kind": "icon", "frame_idx": 3, "cx": 45.0, "cy": 20.0, "facing": 0.0,
             "family": "ally", "facing_source": "stack_fit", "origin": "stack_fit"},
        ]
        # Frame 7 lies in a span the stream read, 5 in one its clip skipped,
        # 6 in none it was asked for.
        clip = {"reason": "outside_cache_rounds", "spans_asked": [[0.0, 200.0]],
                "spans_read": [[0.0, 40.0], [80.0, 200.0]], "spans_skipped": [[40.0, 80.0]]}
        stored = StoredAllyPoses.from_rows(rows, {"ally_icon_version": "ally-icon-x",
                                                  "spans_clip": clip})
        self.assertEqual(stored.skipped, {"barrier": 1, "stack_fit": 1})
        vision = TeamVision(floor, floor, np.zeros((60, 60)), width=60, ally_poses=stored)
        crop = np.zeros((60, 60, 3), np.uint8)
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.self_icons", return_value=[]), \
                patch("reticle.team_vision.ally_icons",
                      side_effect=AssertionError("the stored product fits no teammate")):
            got = vision.step(crop, 0.0, frame_idx=3)
            self.assertEqual(got.widget, "drawn")
            by_x = {d["cx"]: d for d in got.allies}
            self.assertEqual(sorted(by_x), [10.0, 30.5])
            self.assertEqual(by_x[30.5]["facing"], 90.0)
            self.assertEqual(by_x[30.5]["ring"]["cx"], 31.0)
            self.assertEqual(by_x[30.5]["pose"]["audit"], audit)
            self.assertEqual(by_x[30.5]["pose"]["rests_on"], "s:ally:1")
            self.assertNotIn("audit", by_x[10.0]["pose"])
            self.assertIsNone(by_x[10.0]["facing"])
            self.assertIsNone(by_x[10.0]["facing_source"])
            for t, frame_idx, cause, why in (
                    (20.0, 7, "no_frame_in_read_span",
                     "ally_icon stored no frame here (no_frame_in_read_span)"),
                    (66.7, 5, "outside_cache_rounds",
                     "ally_icon stored no frame here (outside_cache_rounds)"),
                    (100.0, 4, "widget_absent",
                     "ally_icon found the widget absent here (widget_absent)"),
                    (500.0, 6, "outside_spans_asked",
                     "ally_icon stored no frame here (outside_spans_asked)")):
                row = frame_row(vision.step(crop, t, frame_idx=frame_idx))
                self.assertEqual(row["widget"], "ally_unread")
                self.assertIsNone(row["observable"])
                self.assertEqual(row["ally_unread_cause"], cause)
                self.assertEqual(row["reason"], f"ally poses unread: {why}")
            with self.assertRaises(ValueError):
                vision.step(crop, 633.3)

    def test_unread_teammates_leave_the_self_cone_cast(self):
        # The stream reads frames 0-9 and 30-34; 10-29 lie outside the spans
        # it was asked for, as a buy phase does.
        floor = np.ones((60, 60), bool)
        ring = {"r": 5, "cov": 0.9, "inner": 0.0, "inner_v": 100.0, "lobe": 0.4, "area": 80,
                "map_diff": 40.0}
        read = [*range(10), *range(30, 35)]
        rows = [{"kind": "frame", "frame_idx": i, "t_ms": i * 66.7, "widget_drawn": True}
                for i in read]
        rows += [{"kind": "icon", "frame_idx": i, "cx": 30.0, "cy": 30.0, "facing": 90.0,
                  "facing_source": "teardrop", "family": "ally",
                  "ring": {"cx": 30.0, "cy": 30.0, "facing": 90.0},
                  "pose": {"origin": "teardrop", "ncc": 0.8, "reason": None,
                           "facing_reason": None}, **ring} for i in read]
        clip = {"reason": "outside_cache_rounds", "spans_asked": [[0.0, 650.0], [1990.0, 2400.0]],
                "spans_read": [[0.0, 650.0], [1990.0, 2400.0]], "spans_skipped": []}
        stored = StoredAllyPoses.from_rows(rows, {"spans_clip": clip})
        vision = TeamVision(floor, floor, np.zeros((60, 60)), width=60, ally_poses=stored,
                            ring_fallback=True)
        crop = np.zeros((60, 60, 3), np.uint8)
        me = {"cx": 15.0, "cy": 45.0, "r": 5, "cov": 0.9, "facing": 0.0}
        got = {}
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.self_icons", side_effect=lambda *a, **k: [dict(me)]):
            for i in range(35):
                got[i] = vision.step(crop, i * 66.7, frame_idx=i)
        for i in (12, 20, 29):
            row = frame_row(got[i], frame_idx=i)
            self.assertEqual(row["widget"], "ally_unread")
            self.assertEqual(row["ally_unread_cause"], "outside_spans_asked")
            self.assertIsNone(row["observable"])
            self.assertIsNone(row["observable_all"])
            # The self cone is cast and stored; no teammate casts.
            self.assertTrue(got[i].observable_self.any())
            self.assertTrue(np.array_equal(lighting.unpack_mask(row["observable_self"]),
                                           got[i].observable_self))
            casting = {ic["role"] for ic in row["icons"] if ic["casts"]}
            self.assertEqual(casting, {"self"})
            # The self track continues across the gap.
            me_row = [r for r in got[i].diagnostic["adjudication"] if r["role"] == "self"]
            self.assertEqual(me_row[0]["state"], "continuation")
        # The teammate returns after its anchors expired: a boundary of its
        # role's own, not an unexplained appearance.
        back = got[30].diagnostic["adjudication"]
        ally = [r for r in back if r["role"] == "ally"]
        self.assertEqual(ally[0]["state"], "left_censored")
        self.assertTrue(ally[0]["eligible"])
        self.assertEqual(got[30].widget, "drawn")
        self.assertIsNone(got[30].observable_self)

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

    def test_the_yellow_icon_after_his_death_is_not_his_cone(self):
        # Guard 6: dead from frame 6, spectating from frame 10.
        from reticle.adjudication.spectate import DeadIndex, DeadInterval
        floor = np.ones((60, 60), bool)
        dead = DeadIndex([DeadInterval(1, 6 * 66.7 - 1, 1e9, "killfeed_death", "d",
                                       10 * 66.7 - 1, "capture_end")])
        vision = TeamVision(floor, floor, np.zeros((60, 60)), width=60, dead=dead)
        crop = np.zeros((60, 60, 3), np.uint8)
        rows = []
        with patch("reticle.team_vision.widget_drawn", return_value=True), \
                patch("reticle.team_vision.ally_icons", return_value=[]), \
                patch("reticle.team_vision.self_icons",
                      side_effect=lambda *a, **k: [_ally(20.0)]):
            for i in range(14):
                rows.append(frame_row(vision.step(crop, i * 66.7)))
        roles = [[ic["role"] for ic in r["icons"]] for r in rows]
        self.assertEqual(roles[3], ["self"])
        self.assertEqual(roles[7], ["player_dead"])
        self.assertEqual(roles[12], ["spectated"])
        dead_icon = rows[7]["icons"][0]
        self.assertFalse(dead_icon["casts"])
        self.assertIsNone(dead_icon["facing"])
        self.assertEqual(dead_icon["rests_on"]["dead_rests_on"], "killfeed_death")
        self.assertEqual(rows[12]["icons"][0]["rests_on"]["rests_on"], "spectate_switch")

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
