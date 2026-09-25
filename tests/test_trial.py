from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle.decode import Sample, windows_of
from reticle.profiles import get_profile
from reticle.roi_cache import RoiCache, RoiCacheWriter, roi_rect
from reticle.trial import diff, targets


def _manifest(sid="s1", key="k1"):
    return {"session_id": sid, "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "content_key": key}}


class TrialTest(unittest.TestCase):

    def test_windows_split_on_gaps(self):
        self.assertEqual(windows_of([0, 500, 1000, 9000, 9500], gap_ms=4000),
                         [[0, 500, 1000], [9000, 9500]])

    def test_occupied_targets_pad_around_entries(self):
        hud = {"t_ms": [0, 1000, 2000, 3000, 4000, 5000, 9000],
               "kf_entry_mask": [0, 0, 0, 1, 0, 0, 0]}
        self.assertEqual(targets(hud, "occupied", pad_ms=2000), [1000, 2000, 3000, 4000, 5000])
        self.assertEqual(len(targets(hud, "all")), 7)

    def test_diff_compares_only_the_trials_frames(self):
        stored = [{"kind": "coverage"}, {"t_ms": 1.0, "a": 1}, {"t_ms": 2.0, "a": 2},
                  {"t_ms": 9.0, "a": 9}]
        new = [{"kind": "coverage", "frames_offered": 2}, {"t_ms": 1.0, "a": 1},
               {"t_ms": 2.0, "a": 3}]
        d = diff(new, stored, {1.0, 2.0})
        self.assertEqual((d["same"], d["only_trial"], d["only_stored"],
                          d["stored_outside_frames"]), (1, 1, 1, 1))

    def test_cache_round_trip_is_lossless_inside_the_roi(self):
        profile = get_profile("valorant-16x9")
        man = _manifest()
        rng = np.random.default_rng(0)
        frame = rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "killfeed", hz=2.0)
            w.feed(Sample(frame_idx=30, t_ms=500.0, frame=frame))
            w.finish()
            cache, why = RoiCache.load(Path(root), man, profile, "killfeed")
            self.assertIsNone(why)
            (got,) = list(cache.samples([500.0, 999.0]))
            x0, y0, x1, y1 = roi_rect("killfeed", profile, (1920, 1080))
            self.assertTrue(np.array_equal(got.frame[y0:y1, x0:x1], frame[y0:y1, x0:x1]))
            self.assertEqual((got.frame_idx, got.t_ms), (30, 500.0))
            self.assertEqual(int(got.frame[:y0].max(initial=0)), 0)
            # A different capture is refused, never served.
            self.assertEqual(RoiCache.load(Path(root), _manifest(key="k2"), profile,
                                           "killfeed"), (None, "stale_content_key"))


if __name__ == "__main__":
    unittest.main()
