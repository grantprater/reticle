"""`pick_self`'s gate, and the two ways it used to be tied to a nominal rate.

Both tests below failed before 2026-09-09: the gate was
`RUN_PX * scale * step * 2` with no floor and with the sampler's CONFIGURED
period, so at 60 Hz it was 1.50 px -- narrower than the icon fit's own error --
and a five-second death screen counted as one frame of elapsed time.
"""
import unittest

from reticle.minimap import (FIT_ERR_PX, GAP_MS, RUN_PX, SELF_PICK_RULES, filter_track,
                             pick_self, pick_self_declared)


def cand(area, x, y):
    return (area, float(x), float(y))


class GateFloorTests(unittest.TestCase):
    def test_the_player_own_icon_survives_its_fit_error_at_native_rate(self):
        # 60 Hz: the run allowance is RUN_PX/60*2 = 1.50 px, and a stationary
        # player's fitted centre moves further than that on its own.
        prev = (100.0, 100.0)
        jittered = cand(30, 103.0, 100.0)          # 3.0 px, inside 2e, past 1.5
        other = cand(90, 140.0, 100.0)             # a bigger blob, far away
        self.assertEqual(pick_self([jittered, other], prev, 1000 / 60),
                         jittered[1:])

    def test_the_floor_is_the_pair_budget_and_not_more(self):
        prev = (100.0, 100.0)
        inside = cand(10, 100.0 + 2 * FIT_ERR_PX - 0.01, 100.0)
        outside = cand(10, 100.0 + 2 * FIT_ERR_PX + 0.01, 100.0)
        big = cand(99, 300.0, 300.0)
        self.assertEqual(pick_self([inside, big], prev, 1000 / 60), inside[1:])
        # Nothing within the gate: the pick falls through to the largest blob,
        # which is the honest answer rather than a refusal.
        self.assertEqual(pick_self([outside, big], prev, 1000 / 60), big[1:])

    def test_a_low_rate_still_gets_its_full_run_allowance(self):
        # 2 Hz: 45 px, and the floor must not narrow it.
        prev = (100.0, 100.0)
        ran = cand(10, 140.0, 100.0)
        big = cand(99, 300.0, 300.0)
        self.assertEqual(pick_self([ran, big], prev, 500.0), ran[1:])

    def test_the_gate_never_narrows_as_the_rate_rises(self):
        prev = (100.0, 100.0)
        far = cand(10, 100.0 + 3.9, 100.0)
        big = cand(99, 400.0, 400.0)
        for dt in (1000 / 60, 1000 / 30, 1000 / 15, 100.0, 500.0):
            self.assertEqual(pick_self([far, big], prev, dt), far[1:],
                             f"refused at dt={dt:g}ms")


class ElapsedTimeTests(unittest.TestCase):
    def test_a_stale_previous_point_stops_constraining_the_pick(self):
        # The widget is gone for the whole death screen. `prev` is where the
        # player died; the gate must not still be pointing at it.
        prev = (100.0, 100.0)
        near_the_corpse = cand(10, 101.0, 100.0)
        elsewhere = cand(99, 300.0, 300.0)
        self.assertEqual(
            pick_self([near_the_corpse, elsewhere], prev, GAP_MS + 1.0),
            elsewhere[1:])
        self.assertEqual(
            pick_self([near_the_corpse, elsewhere], prev, GAP_MS),
            near_the_corpse[1:])

    def test_a_longer_gap_admits_a_longer_run(self):
        prev = (100.0, 100.0)
        ran = cand(10, 100.0 + RUN_PX * 0.5 * 2.0 - 1.0, 100.0)
        big = cand(99, 400.0, 400.0)
        self.assertEqual(pick_self([ran, big], prev, 500.0), ran[1:])
        self.assertEqual(pick_self([ran, big], prev, 100.0), big[1:])

    def test_the_widget_scale_carries_through(self):
        prev = (100.0, 100.0)
        c = cand(10, 100.0 + 2 * FIT_ERR_PX * 1.5 - 0.01, 100.0)
        big = cand(99, 400.0, 400.0)
        self.assertEqual(pick_self([c, big], prev, 1000 / 60, 1.5), c[1:])
        self.assertEqual(pick_self([c, big], prev, 1000 / 60, 1.0), big[1:])


class NoPreviousPointTests(unittest.TestCase):
    def test_no_candidates_is_None_rather_than_a_guess(self):
        self.assertIsNone(pick_self([], (100.0, 100.0), 16.7))
        self.assertIsNone(pick_self([], None, 16.7))

    def test_the_first_frame_takes_the_largest_blob(self):
        big = cand(99, 300.0, 300.0)
        self.assertEqual(pick_self([cand(10, 10.0, 10.0), big], None, 16.7),
                         big[1:])

    def test_fitted_icons_use_fitted_centres_and_arc_coverage(self):
        weak = {"cov": 0.26, "cx": 30.5, "cy": 40.5, "area": 100}
        strong = {"cov": 0.72, "cx": 10.25, "cy": 20.75, "area": 5}
        self.assertEqual(pick_self([weak, strong], None, 16.7),
                         (strong["cx"], strong["cy"]))


class DeclaredRuleTests(unittest.TestCase):
    """`pick_self_declared` names the rule; the choice stays `pick_self`'s."""

    def test_each_rule_is_named(self):
        prev = (100.0, 100.0)
        near = cand(10, 101.0, 100.0)
        big = cand(99, 300.0, 300.0)
        got = pick_self_declared([near, big], prev, 1000 / 15)
        self.assertEqual((got["rests_on"], got["widened"]), ("near_prior", False))
        self.assertEqual(got["runner_up"], (300.0, 300.0, 99.0))
        got = pick_self_declared([cand(10, 200.0, 100.0), big], prev, 1000 / 15)
        self.assertEqual((got["rests_on"], got["widened"]), ("full_search", True))
        got = pick_self_declared([near, big], None, 1000 / 15)
        self.assertEqual((got["rests_on"], got["widened"]), ("full_search", False))
        got = pick_self_declared([near], prev, 1000 / 15)
        self.assertEqual((got["rests_on"], got["runner_up"]), ("sole_candidate", None))
        self.assertEqual(pick_self_declared([], prev, 16.7)["rests_on"], "no_candidate")
        self.assertIn(got["rests_on"], SELF_PICK_RULES)

    def test_the_declared_choice_is_pick_self(self):
        prev = (100.0, 100.0)
        sets = [[cand(10, 101.0, 100.0), cand(99, 300.0, 300.0)],
                [cand(10, 200.0, 100.0), cand(99, 300.0, 300.0)],
                [cand(50, 101.0, 100.0), cand(50, 102.0, 100.0)]]
        for cs in sets:
            for p in (prev, None):
                self.assertEqual(pick_self_declared(cs, p, 1000 / 15)["xy"],
                                 pick_self(cs, p, 1000 / 15))


class MarkedTrackTests(unittest.TestCase):
    def test_interpolated_points_are_marked_and_the_default_is_unchanged(self):
        step = 1000 / 15
        found = [(0.0, 0.0, 0.0), (3 * step, 3.0, 0.0)]
        plain = filter_track(found, step)
        marked = filter_track(found, step, mark=True)
        self.assertEqual([p[:3] for p in marked], plain)
        self.assertEqual([p[3] for p in marked], [False, True, True, False])
        self.assertTrue(all(len(p) == 3 for p in plain))


if __name__ == "__main__":
    unittest.main()
