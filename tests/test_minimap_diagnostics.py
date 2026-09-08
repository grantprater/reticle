import unittest
from unittest.mock import patch
from types import SimpleNamespace

import numpy as np

from reticle.track import Tracker
from reticle.minimap_diagnostics import light_support, distance_agreement
from reticle.overlay import _draw_minimap


def detection(x=20):
    return {"cx": x, "cy": 20, "facing": 0}


class TemporalEvidenceTests(unittest.TestCase):
    def test_elapsed_gap_expires_the_track(self):
        # Elapsed time is the ONLY expiry. It used to share the job with a
        # frames-missed count, which made the real budget depend on the sample
        # rate: three missed frames is 50 ms at 60 Hz and 200 ms at 15 Hz.
        tracker = Tracker()
        first = tracker.step(0, [detection()])[0].tid
        second = tracker.step(501, [detection()])[0].tid
        self.assertNotEqual(first, second)

    def test_a_long_blink_inside_the_budget_keeps_the_identity(self):
        tracker = Tracker()
        first = tracker.step(0, [detection()])[0].tid
        for i in range(1, 20):                       # 317 ms of 60 Hz misses
            tracker.step(i * 1000 / 60, [])
        self.assertEqual(tracker.step(334, [detection(21)])[0].tid, first)

    def test_short_gap_retains_id_but_not_fresh_bearing(self):
        tracker = Tracker()
        first = tracker.step(0, [detection()])[0].tid
        tracker.step(67, [])
        self.assertIsNone(tracker.bearings(67)[0][2])
        self.assertEqual(tracker.step(134, [detection(21)])[0].tid, first)

    def test_integer_centers_do_not_fragment_subpixel_motion(self):
        # 30 px/s is below RUN_PX, but rasterization produces 60 px/s steps
        # at 60Hz. Test an independently specified continuous trajectory.
        tracker = Tracker(position_error_px=np.sqrt(0.5))   # the old floor
        ids = []
        for i in range(60):
            rows = tracker.step(i * 1000 / 60, [detection(round(20 + i * 0.5))])
            ids.append(next(t.tid for t in rows if t.t_ms == i * 1000 / 60))
        self.assertEqual(len(set(ids)), 1)
        rows = tracker.step(1000, [detection(100)])
        self.assertNotEqual(rows[-1].tid, ids[0])

    def test_time_order_refuses_before_mutating(self):
        tracker = Tracker()
        tracker.step(100, [detection()])
        for t in (100, 99, float("nan")):
            with self.assertRaises(ValueError):
                tracker.step(t, [])
        self.assertEqual(tracker.tracks[0].missed, 0)

    def test_widget_absence_ages_tracks(self):
        tracker = Tracker()
        tracker.step(0, [detection()])
        ctx = SimpleNamespace(mm_box=(0, 0, 50, 50), mm_sgray=np.zeros((50, 50)),
                              mm_floor=np.ones((50, 50), bool),
                              mm_track_self=tracker, mm_track_ally=Tracker())
        frame = np.zeros((50, 50, 3), np.uint8)
        with patch("reticle.overlay.widget_drawn", return_value=False):
            _draw_minimap(frame.copy(), frame, 600, ctx)
        self.assertEqual(tracker.tracks, [])
        self.assertEqual(ctx.mm_diagnostic["widget"], "not_drawn")

    def test_unknown_light_is_not_negative_evidence(self):
        empty = np.zeros((60, 60), bool)
        score = light_support(30, 30, empty, empty)
        self.assertIsNone(score["fraction"])
        self.assertEqual(score["known"], 0)

    def test_support_is_scored_on_the_same_annulus_for_every_fit(self):
        # Two candidate fits of one icon disagree about the radius. Scoring
        # each on `d > its own r` scores them on different annuli, and the
        # larger fit reads as better lit for that reason alone.
        known = np.ones((80, 80), bool)
        lit = np.zeros_like(known)
        yy, xx = np.ogrid[:80, :80]
        lit[(xx - 40) ** 2 + (yy - 40) ** 2 <= 18 ** 2] = True   # a lit halo
        a = light_support(40, 40, lit, known)
        b = light_support(40, 40, lit, known)
        self.assertEqual((a["known"], a["lit"]), (b["known"], b["lit"]))
        self.assertGreater(a["known"], 0)

    def test_a_frozen_source_is_not_an_observation(self):
        # A capture stall reads the same positions every frame, so every track
        # holds and the channel reports a world it is not observing -- the most
        # confident-looking tracking in a session. `haven 421-428` is 6.4 s of
        # it. Treated like an absent widget, but recorded as its own state.
        tracker = Tracker()
        tracker.step(0, [detection()])
        ctx = SimpleNamespace(mm_box=(0, 0, 50, 50), mm_sgray=np.zeros((50, 50)),
                              mm_floor=np.ones((50, 50), bool), mm_slab=None,
                              mm_track_self=tracker, mm_track_ally=Tracker(),
                              mm_prev_luma=None, mm_light=None, mm_lifecycle=None,
                              mm_passable=np.ones((50, 50), bool),
                              mm_origin_events=(), mm_apply_lifecycle=False)
        frame = np.zeros((50, 50, 3), np.uint8)
        frame[10:20, 10:20] = 200
        with patch("reticle.overlay.widget_drawn", return_value=True):
            _draw_minimap(frame.copy(), frame, 100, ctx)     # first: no previous
            self.assertIsNone(ctx.mm_diagnostic["source_delta"])
            _draw_minimap(frame.copy(), frame, 200, ctx)     # identical source
        self.assertEqual(ctx.mm_diagnostic["widget"], "stale")
        self.assertEqual(ctx.mm_diagnostic["source_delta"], 0.0)
        self.assertEqual(ctx.mm_diagnostic["stale_evidence"], "pixels only, no clock")
        self.assertEqual(ctx.mm_diagnostic["observations"], [])

    def test_a_ticking_clock_refutes_a_stall_whatever_the_pixels_say(self):
        # The player's point: the clock is the better witness. Post-plant it is
        # replaced by the spike timer, so the pixel delta stays as the fallback
        # and the record says which witness the answer rests on.
        from reticle.minimap_diagnostics import stale_source
        self.assertEqual(stale_source(0.0, None, None), (True, "pixels only, no clock"))
        self.assertEqual(stale_source(0.0, 54000, 200.0), (False, "clock advancing"))
        self.assertEqual(stale_source(0.0, 54000, 4000.0),
                         (True, "clock held and pixels static"))
        self.assertEqual(stale_source(9.0, 54000, 4000.0),
                         (False, "clock held, pixels moving"))
        self.assertEqual(stale_source(None, None, None), (False, "no previous frame"))

    def test_the_track_picks_the_self_icon_not_this_frame_s_coverage(self):
        # The Haven death window: two self-coloured candidates 35-45 px apart,
        # alternating frame to frame, both at the 0.25 coverage floor. Taking
        # the better-covered one per frame moved the player across the map and
        # back seven times in three seconds.
        tracker = Tracker(scale=1.0)
        real = {"cx": 155.0, "cy": 206.0, "r": 6, "cov": 0.28, "facing": 0.0}
        blob = {"cx": 118.0, "cy": 217.0, "r": 6, "cov": 0.99, "facing": 0.0}
        for i in range(6):
            tracker.step(i * 1000 / 60, [real])
        tracker.step(6 * 1000 / 60, [real, blob])
        self.assertEqual((tracker.principal().x, tracker.principal().y),
                         (real["cx"], real["cy"]))
        self.assertEqual(len(tracker.tracks), 2)   # the other is kept, not deleted

    def test_a_blob_supported_only_by_the_margin_is_not_an_icon(self):
        # `floor` arrives dilated so an icon at the slab's edge is not clipped,
        # and that margin lies over the see-through part of the widget. On
        # Ascent the world behind it is a green glass wall that keys as ally
        # teal: 7,855 keyed px at 299.6s against 153 a second earlier.
        from reticle.minimap import icons
        crop = np.zeros((80, 80, 3), np.uint8)
        crop[:] = (60, 60, 60)
        slab = np.zeros((80, 80), bool)
        slab[10:40, 10:40] = True
        floor = np.zeros((80, 80), bool)
        floor[5:75, 5:75] = True            # the dilated version, generously
        mask = np.zeros((80, 80), bool)
        yy, xx = np.ogrid[:80, :80]
        ring = ((xx - 60) ** 2 + (yy - 60) ** 2 <= 10 ** 2) &                ((xx - 60) ** 2 + (yy - 60) ** 2 >= 6 ** 2)
        mask[ring] = True                    # entirely in the margin
        kw = dict(cov_min=0.0, inner_max=1.0, require_facing=False)
        self.assertTrue(icons(mask, crop, floor, **kw))
        self.assertEqual(icons(mask, crop, floor, support=slab, **kw), [])
        # ...and one that touches the slab survives the same rule.
        on = ((xx - 25) ** 2 + (yy - 25) ** 2 <= 10 ** 2) &              ((xx - 25) ** 2 + (yy - 25) ** 2 >= 6 ** 2)
        self.assertTrue(icons(on, crop, floor, support=slab, **kw))

    def test_distance_bins_partition_known_pixels(self):
        known = np.ones((120, 120), bool)
        lit = np.zeros_like(known)
        lit[:60] = True
        predicted = np.zeros_like(known)
        predicted[:, :60] = True
        rows = distance_agreement(predicted, lit, known, [(0, 0), (60, 60)])["bins"]
        for key, expected in (("known", 14400), ("lit", 7200),
                              ("predicted", 7200), ("overlap", 3600)):
            self.assertEqual(sum(r[key] for r in rows), expected)


if __name__ == "__main__":
    unittest.main()
