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
    def test_elapsed_gap_expires_even_without_missing_steps(self):
        tracker = Tracker(max_missed=100)
        first = tracker.step(0, [detection()])[0].tid
        second = tracker.step(501, [detection()])[0].tid
        self.assertNotEqual(first, second)

    def test_short_gap_retains_id_but_not_fresh_bearing(self):
        tracker = Tracker()
        first = tracker.step(0, [detection()])[0].tid
        tracker.step(67, [])
        self.assertIsNone(tracker.bearings(67)[0][2])
        self.assertEqual(tracker.step(134, [detection(21)])[0].tid, first)

    def test_integer_centers_do_not_fragment_subpixel_motion(self):
        # 30 px/s is below RUN_PX, but rasterization produces 60 px/s steps
        # at 60Hz. Test an independently specified continuous trajectory.
        tracker = Tracker(position_error_px=np.sqrt(0.5))
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
        score = light_support(30, 30, 10, empty, empty)
        self.assertIsNone(score["fraction"])
        self.assertEqual(score["known"], 0)

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
