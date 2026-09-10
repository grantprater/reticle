import unittest

from reticle.minimap import (FIT_ERR_PX, GAP_MS, HELD, INTERPOLATED, OBSERVED,
                             RUN_PX, UNRESOLVED, absent_instants, filter_track,
                             resolve_track)


STEP = 100.0


def read(t, x, y):
    return (t, x, y)


class SourceTests(unittest.TestCase):
    def test_an_admitted_read_is_observed_at_the_fit_error(self):
        found = [read(0, 10, 10), read(STEP, 12, 10)]
        fixes = resolve_track(found, STEP)
        self.assertEqual([f.source for f in fixes], [OBSERVED, OBSERVED])
        self.assertTrue(all(f.observed for f in fixes))
        self.assertAlmostEqual(fixes[0].radius_px, FIT_ERR_PX)
        self.assertIsNone(fixes[0].reason)

    def test_a_bracketed_refusal_is_interpolated_and_bounded(self):
        # 10 px in 200 ms is 50 px/s, inside the step law -- a bracket the law
        # refuses is not a bracket, and the belief falls back to a hold.
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        got = resolve_track(found, STEP, absent_t=[])
        self.assertEqual(got[1].source, INTERPOLATED)
        self.assertAlmostEqual(got[1].x, 5.0)
        self.assertAlmostEqual(got[1].y, 0.0)
        # Bounded by the NEARER endpoint, so the belief is tightest mid-gap
        # rather than growing without limit.
        self.assertAlmostEqual(got[1].radius_px,
                               FIT_ERR_PX + RUN_PX * (STEP / 1000.0))

    def test_an_unclosed_refusal_is_held_with_a_growing_radius(self):
        found = [read(0, 5, 5), read(STEP, None, None), read(2 * STEP, None, None)]
        got = resolve_track(found, STEP, absent_t=[])
        self.assertEqual([f.source for f in got[1:]], [HELD, HELD])
        self.assertEqual((got[1].x, got[1].y), (5, 5))
        self.assertEqual((got[2].x, got[2].y), (5, 5))
        self.assertLess(got[1].radius_px, got[2].radius_px)

    def test_nothing_is_believed_across_an_absent_widget(self):
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        got = resolve_track(found, STEP, absent_t=[STEP])
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "widget_absent")
        self.assertIsNone(got[1].x)
        self.assertIsNone(got[1].radius_px)

    def test_a_stale_prior_refuses_rather_than_holding_forever(self):
        found = [read(0, 0, 0), read(GAP_MS + STEP, None, None)]
        got = resolve_track(found, STEP, absent_t=[])
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "stale")

    def test_a_rejected_read_still_gets_a_belief_that_names_the_rejection(self):
        # 500 px in 100 ms is far past RUN_PX * 1.6, so the step law drops it.
        found = [read(0, 0, 0), read(STEP, 500, 0), read(2 * STEP, 4, 0)]
        got = resolve_track(found, STEP, absent_t=[])
        self.assertNotEqual(got[1].source, OBSERVED)
        self.assertEqual(got[1].reason, "rejected_step")
        self.assertIsNotNone(got[1].x)

    def test_beliefs_never_outrank_the_reads_the_track_admitted(self):
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        admitted = {(t, x, y) for t, x, y in filter_track(found, STEP)}
        observed = {(f.t_ms, f.x, f.y)
                    for f in resolve_track(found, STEP, absent_t=[])
                    if f.observed}
        self.assertTrue(observed <= admitted)


class AbsenceEvidenceTests(unittest.TestCase):
    def test_a_read_ally_proves_the_widget_was_drawn(self):
        rows = [{"t_ms": 0.0, "self_x": None, "self_y": None, "n_allies": 2},
                {"t_ms": 100.0, "self_x": None, "self_y": None, "n_allies": 0},
                {"t_ms": 200.0, "self_x": 5.0, "self_y": 5.0, "n_allies": 0}]
        # The refusal beside a teammate is NOT absence; the lone NULL row is
        # all this rule can still call unobservable.
        self.assertEqual(absent_instants(rows), [100.0])


if __name__ == "__main__":
    unittest.main()
