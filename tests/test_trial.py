from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle.decode import Sample, windows_of
from reticle.profiles import get_profile
from reticle.roi_cache import RoiCache, RoiCacheWriter, roi_rects
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
            x0, y0, x1, y1 = roi_rects("killfeed", profile, (1920, 1080))[0]
            self.assertTrue(np.array_equal(got.frame[y0:y1, x0:x1], frame[y0:y1, x0:x1]))
            self.assertEqual((got.frame_idx, got.t_ms), (30, 500.0))
            self.assertEqual(int(got.frame[:y0].max(initial=0)), 0)
            # A different capture is refused, never served.
            self.assertEqual(RoiCache.load(Path(root), _manifest(key="k2"), profile,
                                           "killfeed"), (None, "stale_content_key"))


if __name__ == "__main__":
    unittest.main()


class HudCacheTest(unittest.TestCase):

    def test_a_hud_cache_serves_the_killfeed_set(self):
        profile = get_profile("valorant-16x9")
        man = _manifest()
        frame = np.random.default_rng(1).integers(0, 255, (1080, 1920, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "hud", hz=2.0)
            w.feed(Sample(frame_idx=7, t_ms=0.0, frame=frame))
            w.finish()
            cache, why = RoiCache.load(Path(root), man, profile, "killfeed")
            self.assertIsNone(why)
            self.assertEqual(cache.record["roi"], "hud")
            (got,) = list(cache.samples([0.0]))
            for x0, y0, x1, y1 in roi_rects("hud", profile, (1920, 1080)):
                self.assertTrue(np.array_equal(got.frame[y0:y1, x0:x1], frame[y0:y1, x0:x1]))


class CacheFedScanTest(unittest.TestCase):
    """`roi_cache.cache_for` feeds a pass from the cache only when every reader can be."""

    def _cache(self, root, hz=2.0):
        profile = get_profile("valorant-16x9")
        w = RoiCacheWriter(Path(root), _manifest(), profile, "hud", hz=hz)
        w.feed(Sample(frame_idx=0, t_ms=0.0, frame=np.zeros((1080, 1920, 3), np.uint8)))
        w.finish()
        return profile

    def _reader(self, name, cache_set="killfeed", hz=2.0, spans=None):
        from types import SimpleNamespace
        return SimpleNamespace(name=name, cache_set=cache_set, hz=hz, spans=spans)

    def test_cached_readers_are_fed_from_the_cache(self):
        from reticle.roi_cache import cache_for
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root)
            cache, why = cache_for(Path(root), _manifest(), profile,
                                   [self._reader("kp"), self._reader("hud", "hud")])
            self.assertIsNotNone(cache, why)

    def test_one_uncached_reader_makes_it_a_decode(self):
        from reticle.roi_cache import cache_for
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root)
            for bad, reason in ((self._reader("mm", None), "outside"),
                                (self._reader("kp", spans=[(0, 1)]), "spans"),
                                (self._reader("kp", hz=15.0), "rate")):
                cache, why = cache_for(Path(root), _manifest(), profile, [bad])
                self.assertIsNone(cache)
                self.assertIn(reason, why)

    def test_the_roster_reader_rides_the_hud_cache(self):
        from reticle.roi_cache import CACHE_SETS, cache_for
        from reticle.roster import RosterReader
        reader = RosterReader(get_profile("valorant-16x9"), (1920, 1080))
        self.assertEqual(reader.cache_set, "hud")
        # Both ROIs it reads are in the set it declares.
        self.assertLessEqual({"hud_roster", "hud_roster_enemy"}, set(CACHE_SETS["hud"]))
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root)
            cache, why = cache_for(Path(root), _manifest(), profile, [reader])
            self.assertIsNotNone(cache, why)


class DiffStampTest(unittest.TestCase):

    def test_a_version_bump_alone_is_not_a_difference(self):
        old = [{"t_ms": 0.0, "observation_key": "k", "x0": 1, "stream_version": "0.1"}]
        new = [{"t_ms": 0.0, "observation_key": "k", "x0": 1, "stream_version": "0.2"}]
        self.assertEqual(diff(new, old, {0.0})["same"], 1)

    def test_moved_fields_are_named(self):
        old = [{"t_ms": 0.0, "observation_key": "k", "x0": 1, "x1": 5}]
        new = [{"t_ms": 0.0, "observation_key": "k", "x0": 2, "x1": 5}]
        self.assertEqual(diff(new, old, {0.0})["fields"], {"x0": 1})


class RoundCacheTest(unittest.TestCase):
    """A cache written over spans, and the FFV1 codec 15 Hz sets use."""

    def test_span_cache_feeds_only_readers_inside_it(self):
        from types import SimpleNamespace
        from reticle.roi_cache import cache_for, clip_spans, covers
        held = [[0.0, 10.0], [20.0, 30.0]]
        self.assertTrue(covers(held, [(1.0, 9.0), (20.0, 30.0)]))
        self.assertFalse(covers(held, [(5.0, 25.0)]))
        self.assertFalse(covers(held, None))
        self.assertEqual(clip_spans([(5.0, 25.0)], held), [(5.0, 10.0), (20.0, 25.0)])
        self.assertEqual(clip_spans(None, held), [(0.0, 10.0), (20.0, 30.0)])
        profile = get_profile("valorant-16x9")
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "hud", hz=2.0, spans=held)
            w.feed(Sample(frame_idx=0, t_ms=0.0, frame=np.zeros((1080, 1920, 3), np.uint8)))
            w.finish()
            r = lambda spans: SimpleNamespace(name="kp", cache_set="killfeed", hz=2.0, spans=spans)
            self.assertIsNotNone(cache_for(Path(root), _manifest(), profile, [r(held)])[0])
            for bad in (None, [(5.0, 25.0)]):
                cache, why = cache_for(Path(root), _manifest(), profile, [r(bad)])
                self.assertIsNone(cache)
                self.assertIn("outside the cache's spans", why)

    def test_ffv1_cache_round_trip_is_lossless(self):
        from reticle.roi_cache import ffmpeg_path
        try:
            ffmpeg_path()
        except SystemExit:
            self.skipTest("ffmpeg not installed")
        profile = get_profile("valorant-16x9")
        man = _manifest()
        rng = np.random.default_rng(2)
        frames = [rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8) for _ in range(3)]
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), man, profile, "minimap", hz=15.0, spans=[[0.0, 1000.0]])
            for i, f in enumerate(frames):
                w.feed(Sample(frame_idx=i, t_ms=i * 66.7, frame=f))
            w.finish()
            cache, why = RoiCache.load(Path(root), man, profile, "minimap")
            self.assertIsNone(why)
            self.assertEqual(cache.record["codec"], "ffv1")
            # Out of order, so the reader must seek.
            got = {s.frame_idx: s for s in cache.samples([133.4, 0.0, 66.7])}
            for i, f in enumerate(frames):
                for x0, y0, x1, y1 in roi_rects("minimap", profile, (1920, 1080)):
                    self.assertTrue(np.array_equal(got[i].frame[y0:y1, x0:x1], f[y0:y1, x0:x1]))
