import unittest

import numpy as np

from reticle.belief import (HELD, INTERPOLATED, OBSERVED, UNRESOLVED, Fix,
                            absent_instants, resolve, round_voids)
from reticle.minimap import FIT_ERR_PX, GAP_MS, RUN_PX, filter_track


STEP = 100.0


def read(t, x, y):
    return (t, x, y)


class SourceTests(unittest.TestCase):
    def test_an_admitted_read_is_observed_at_the_fit_error(self):
        found = [read(0, 10, 10), read(STEP, 12, 10)]
        fixes = resolve(found, STEP)
        self.assertEqual([f.source for f in fixes], [OBSERVED, OBSERVED])
        self.assertTrue(all(f.observed for f in fixes))
        self.assertAlmostEqual(fixes[0].radius_px, FIT_ERR_PX)
        self.assertIsNone(fixes[0].reason)

    def test_a_bracketed_refusal_is_interpolated_and_bounded(self):
        # 10 px in 200 ms is 50 px/s, inside the step law -- a bracket the law
        # refuses is not a bracket, and the belief falls back to a hold.
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        got = resolve(found, STEP, absent_t=[])
        self.assertEqual(got[1].source, INTERPOLATED)
        self.assertAlmostEqual(got[1].x, 5.0)
        self.assertAlmostEqual(got[1].y, 0.0)
        # Bounded by the NEARER endpoint, so the belief is tightest mid-gap
        # rather than growing without limit.
        self.assertAlmostEqual(got[1].radius_px,
                               FIT_ERR_PX + RUN_PX * (STEP / 1000.0))

    def test_an_unclosed_refusal_is_held_with_a_growing_radius(self):
        found = [read(0, 5, 5), read(STEP, None, None), read(2 * STEP, None, None)]
        got = resolve(found, STEP, absent_t=[])
        self.assertEqual([f.source for f in got[1:]], [HELD, HELD])
        self.assertEqual((got[1].x, got[1].y), (5, 5))
        self.assertEqual((got[2].x, got[2].y), (5, 5))
        self.assertLess(got[1].radius_px, got[2].radius_px)

    def test_nothing_is_believed_across_an_absent_widget(self):
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        got = resolve(found, STEP, absent_t=[STEP])
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "widget_absent")
        self.assertIsNone(got[1].x)
        self.assertIsNone(got[1].radius_px)

    def test_a_stale_prior_refuses_rather_than_holding_forever(self):
        found = [read(0, 0, 0), read(GAP_MS + STEP, None, None)]
        got = resolve(found, STEP, absent_t=[])
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "stale")

    def test_a_rejected_read_still_gets_a_belief_that_names_the_rejection(self):
        # 500 px in 100 ms is far past RUN_PX * 1.6, so the step law drops it.
        found = [read(0, 0, 0), read(STEP, 500, 0), read(2 * STEP, 4, 0)]
        got = resolve(found, STEP, absent_t=[])
        self.assertNotEqual(got[1].source, OBSERVED)
        self.assertEqual(got[1].reason, "rejected_step")
        self.assertIsNotNone(got[1].x)

    def test_beliefs_never_outrank_the_reads_the_track_admitted(self):
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        admitted = {(t, x, y) for t, x, y in filter_track(found, STEP)}
        observed = {(f.t_ms, f.x, f.y)
                    for f in resolve(found, STEP, absent_t=[])
                    if f.observed}
        self.assertTrue(observed <= admitted)


class VoidTests(unittest.TestCase):
    def test_no_belief_is_carried_across_a_round_boundary(self):
        found = [read(0, 0, 0), read(STEP, None, None), read(2 * STEP, 10, 0)]
        got = resolve(found, STEP, absent_t=[], voids=[STEP / 2])
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "void")
        # The reads themselves are evidence and survive the boundary; only the
        # inference across it is refused.
        self.assertEqual([got[0].source, got[2].source], [OBSERVED, OBSERVED])

    def test_round_voids_takes_both_edges_of_every_round(self):
        rounds = [{"t_start_ms": 10.0, "t_end_ms": 90.0},
                  {"t_start_ms": 200.0, "t_end_ms": 260.0}]
        self.assertEqual(round_voids(rounds), [10.0, 90.0, 200.0, 260.0])


class ReachabilityTests(unittest.TestCase):
    def walkable(self, **kw):
        mask = np.zeros((40, 40), bool)
        mask[:, :20] = True          # a wall down the middle of the widget
        found = [read(0, 2, 2), read(STEP, None, None), read(2 * STEP, 8, 2)]
        return resolve(found, STEP, absent_t=[], reachable=mask, **kw)

    def test_a_believed_centre_on_the_floor_is_kept(self):
        got = self.walkable()
        self.assertEqual(got[1].source, INTERPOLATED)
        self.assertAlmostEqual(got[1].x, 5.0)

    def test_a_believed_centre_off_the_floor_is_refused(self):
        mask = np.zeros((40, 40), bool)
        mask[:, :4] = True
        mask[:, 8:] = True           # the midpoint at x=5 falls in the wall
        found = [read(0, 2, 2), read(STEP, None, None), read(2 * STEP, 8, 2)]
        got = resolve(found, STEP, absent_t=[], reachable=mask)
        self.assertEqual(got[1].source, UNRESOLVED)
        self.assertEqual(got[1].reason, "off_floor")

    def test_an_observed_read_is_never_gated_on_the_mask(self):
        # Evidence is not discarded for disagreeing with a mask.
        mask = np.zeros((40, 40), bool)
        found = [read(0, 2, 2), read(STEP, 3, 2)]
        got = resolve(found, STEP, absent_t=[], reachable=mask)
        self.assertEqual([f.source for f in got], [OBSERVED, OBSERVED])


class AbsenceEvidenceTests(unittest.TestCase):
    def test_a_read_ally_proves_the_widget_was_drawn(self):
        rows = [{"t_ms": 0.0, "self_x": None, "self_y": None, "n_allies": 2},
                {"t_ms": 100.0, "self_x": None, "self_y": None, "n_allies": 0},
                {"t_ms": 200.0, "self_x": 5.0, "self_y": 5.0, "n_allies": 0}]
        # The refusal beside a teammate is NOT absence; the lone NULL row is
        # all this rule can still call unobservable.
        self.assertEqual(absent_instants(rows), [100.0])

    def test_the_stored_flag_beats_the_ally_proxy(self):
        # minimap-0.6.0 records what the reader already knew. A refusal with
        # the widget DRAWN and no teammate visible is the case the proxy gets
        # wrong, and the flag gets right.
        rows = [{"t_ms": 0.0, "self_x": None, "self_y": None, "n_allies": 0,
                 "widget_drawn": True},
                {"t_ms": 100.0, "self_x": None, "self_y": None, "n_allies": 2,
                 "widget_drawn": False}]
        self.assertEqual(absent_instants(rows), [100.0])

    def test_a_missing_flag_is_unknown_not_false(self):
        # A pre-0.6.0 row carries no column. Reading its absence as "the widget
        # was not drawn" would call every refusal unobservable and silently
        # empty the belief layer.
        rows = [{"t_ms": 0.0, "self_x": None, "self_y": None, "n_allies": 3}]
        self.assertEqual(absent_instants(rows), [])


if __name__ == "__main__":
    unittest.main()
