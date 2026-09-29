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


class AutoSourceTest(unittest.TestCase):
    """`scan --from auto`: a span reader over a round cache reads the rounds
    only when the cache holds every live round of its spans, else decodes."""

    ROUNDS = [(0.0, 10.0), (20.0, 30.0)]
    #: Active spans reach into the buy phase before each round.
    ACTIVE = [(-5.0, 10.0), (15.0, 30.0)]

    def _cache(self, root, held):
        profile = get_profile("valorant-16x9")
        w = RoiCacheWriter(Path(root), _manifest(), profile, "hud", hz=2.0, spans=held)
        w.feed(Sample(frame_idx=0, t_ms=0.0, frame=np.zeros((1080, 1920, 3), np.uint8)))
        w.finish()
        return profile

    def _reader(self, spans, cache_set="killfeed", name="dp", records_clip=True):
        from types import SimpleNamespace
        return SimpleNamespace(name=name, cache_set=cache_set, hz=2.0, spans=spans,
                               records_clip=records_clip)

    def _choose(self, root, profile, readers, mode, rounds=None):
        from reticle.roi_cache import choose_source
        asked = []

        def live_rounds():
            asked.append(1)
            return (self.ROUNDS, None) if rounds is None else rounds
        got = choose_source(Path(root), _manifest(), profile, readers, mode, live_rounds)
        return got, len(asked)

    def test_covered_reads_the_cache_as_cache_does(self):
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root, [list(s) for s in self.ROUNDS])
            auto, cached = self._reader(list(self.ACTIVE)), self._reader(list(self.ACTIVE))
            (cache, why, notes), asked = self._choose(root, profile, [auto], "auto")
            self.assertIsNotNone(cache, why)
            self.assertEqual(asked, 1)
            (cache2, _, _), _ = self._choose(root, profile, [cached], "cache")
            self.assertIsNotNone(cache2)
            # Auto reads the frames `--from cache` reads: the rounds, no buy phase.
            self.assertEqual(auto.spans, cached.spans)
            self.assertEqual(auto.spans, [(0.0, 10.0), (20.0, 30.0)])
            self.assertTrue(any("inside all 2 live rounds" in n for n in notes), notes)
            self.assertTrue(any("clipped" in n for n in notes), notes)
            # Both record the same clip: the buy phase before each round is unread.
            self.assertEqual(auto.spans_clip, cached.spans_clip)
            self.assertEqual(auto.spans_clip["spans_skipped"], [[-5.0, 0.0], [15.0, 20.0]])
            self.assertEqual(auto.spans_clip["spans_read"], [[0.0, 10.0], [20.0, 30.0]])
            self.assertEqual(auto.spans_clip["frames_from"], "roi-cache-0.1.0")

    def test_partly_covered_decodes_its_whole_spans(self):
        with tempfile.TemporaryDirectory() as root:
            # The cache holds the first round only.
            profile = self._cache(root, [[0.0, 10.0]])
            r = self._reader(list(self.ACTIVE))
            (cache, why, notes), _ = self._choose(root, profile, [r], "auto")
            self.assertIsNone(cache)
            self.assertIn("outside the cache's spans", why)
            self.assertEqual(r.spans, self.ACTIVE)
            self.assertTrue(any("1 of its 2 in-round spans lie outside" in n for n in notes),
                            notes)
            # `--from cache` clips it to what the cache holds instead.
            c = self._reader(list(self.ACTIVE))
            (cache, _, _), _ = self._choose(root, profile, [c], "cache")
            self.assertIsNotNone(cache)
            self.assertEqual(c.spans, [(0.0, 10.0)])

    def test_absent_cache_decodes(self):
        with tempfile.TemporaryDirectory() as root:
            profile = get_profile("valorant-16x9")
            r = self._reader(list(self.ACTIVE))
            (cache, why, notes), asked = self._choose(root, profile, [r], "auto")
            self.assertIsNone(cache)
            self.assertEqual(why, "no_cache")
            self.assertEqual((r.spans, notes, asked), (self.ACTIVE, [], 0))

    def test_rounds_unknown_decodes_and_says_why(self):
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root, [list(s) for s in self.ROUNDS])
            r = self._reader(list(self.ACTIVE))
            (cache, _, notes), _ = self._choose(root, profile, [r], "auto",
                                                rounds=(None, "no rounds stored"))
            self.assertIsNone(cache)
            self.assertEqual(r.spans, self.ACTIVE)
            self.assertIn("no rounds stored", notes[0])

    def test_a_pass_the_cache_cannot_feed_puts_the_spans_back(self):
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root, [list(s) for s in self.ROUNDS])
            span = self._reader(list(self.ACTIVE))
            # A whole-capture reader is not clipped under auto, so the pass decodes.
            whole = self._reader(None, name="hud")
            (cache, why, notes), _ = self._choose(root, profile, [span, whole], "auto")
            self.assertIsNone(cache)
            self.assertIn("hud reads outside", why)
            self.assertEqual((span.spans, whole.spans), (self.ACTIVE, None))
            self.assertIn("restored", notes[-1])
            self.assertFalse(hasattr(span, "spans_clip"))

    def test_auto_never_clips_a_stream_that_cannot_record_it(self):
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root, [list(s) for s in self.ROUNDS])
            r = self._reader(list(self.ACTIVE), records_clip=False)
            (cache, _, notes), asked = self._choose(root, profile, [r], "auto")
            self.assertIsNone(cache)
            self.assertEqual((r.spans, asked), (self.ACTIVE, 0))
            self.assertFalse(hasattr(r, "spans_clip"))
            self.assertIn("cannot record", notes[0])

    def test_streams_record_the_clip(self):
        import json
        import pyarrow.parquet as pq
        from types import SimpleNamespace
        from reticle.minimap_dark import DarkRegionReader
        from reticle.roi_cache import clip_record
        from reticle.store import Store
        clip = clip_record(self.ACTIVE, self.ROUNDS, {"version": "roi-cache-0.1.0",
                                                       "roi": "minimap"})
        d = DarkRegionReader(floor=None, sgray=None, static=None, ref=None, box=[0, 0, 1, 1])
        self.assertTrue(d.records_clip)
        self.assertNotIn("spans_clip", d.events("s1", None)[0])
        d.spans_clip = clip
        self.assertEqual(d.events("s1", None)[0]["spans_clip"], clip)
        row = {"frame_idx": 0, "t_ms": 0.0, "self_x": None, "self_y": None, "n_allies": 0,
               "widget_drawn": False, "ally_x": [None], "ally_y": [None]}
        fp = SimpleNamespace(session_id="s1", content_key="k1")
        with tempfile.TemporaryDirectory() as root:
            store = Store(Path(root))
            meta = pq.read_schema(store.write_minimap([row], fp, "p", "2026-01-01")).metadata
            self.assertNotIn(b"spans_clip", meta)
            self.assertNotIn(b"frames_from", meta)
            meta = pq.read_schema(store.write_minimap(
                [row], fp, "p", "2026-01-01", frames_from="roi-cache-0.1.0",
                spans_clip=clip)).metadata
            self.assertEqual(json.loads(meta[b"spans_clip"]), clip)
            self.assertEqual(meta[b"frames_from"], b"roi-cache-0.1.0")

    def test_subtract_spans(self):
        from reticle.roi_cache import subtract_spans
        self.assertEqual(subtract_spans([(0.0, 10.0)], [(2.0, 3.0), (5.0, 12.0)]),
                         [(0.0, 2.0), (3.0, 5.0)])
        self.assertEqual(subtract_spans([(0.0, 10.0)], []), [(0.0, 10.0)])
        self.assertEqual(subtract_spans([(0.0, 10.0)], [(0.0, 10.0)]), [])

    def test_video_decodes_without_looking(self):
        with tempfile.TemporaryDirectory() as root:
            profile = self._cache(root, [list(s) for s in self.ROUNDS])
            r = self._reader(list(self.ACTIVE))
            (cache, why, notes), asked = self._choose(root, profile, [r], "video")
            self.assertEqual((cache, why, notes, asked, r.spans),
                             (None, "--from video", [], 0, self.ACTIVE))

    def test_rounds_covered(self):
        from reticle.roi_cache import rounds_covered
        held = [[0.0, 10.0], [20.0, 30.0]]
        self.assertTrue(rounds_covered(held, self.ACTIVE, self.ROUNDS)[0])
        self.assertFalse(rounds_covered(held, None, self.ROUNDS)[0])
        self.assertFalse(rounds_covered(held, [(40.0, 50.0)], self.ROUNDS)[0])
        self.assertFalse(rounds_covered([[0.0, 9.0]], self.ACTIVE, self.ROUNDS)[0])


class DarkCacheTest(unittest.TestCase):
    """`scan --only minimap_dark` reads the 15 Hz minimap cache on its 4 Hz grid."""

    def _dark(self, box, hz=4.0, spans=None):
        from reticle.minimap_dark import DarkRegionReader
        return DarkRegionReader(floor=None, sgray=None, static=None, ref=None, box=box,
                                hz=hz, spans=spans)

    def test_the_dark_reader_declares_the_minimap_set(self):
        from reticle.roi_cache import declare_set
        profile = get_profile("valorant-16x9")
        box = roi_rects("minimap", profile, (1920, 1080))[0]
        reader = self._dark(box)
        declare_set(reader, "minimap", profile, (1920, 1080))
        self.assertEqual(reader.cache_set, "minimap")
        self.assertTrue(reader.cache_resample)
        # A box other than the ROI reads outside the cached set.
        other = self._dark([box[0] + 1, box[1], box[2], box[3]])
        declare_set(other, "minimap", profile, (1920, 1080))
        self.assertIsNone(getattr(other, "cache_set", None))

    def test_a_resampling_reader_rides_a_faster_cache(self):
        from types import SimpleNamespace
        from reticle.roi_cache import cache_for
        profile = get_profile("valorant-16x9")
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "hud", hz=15.0)
            w.feed(Sample(frame_idx=0, t_ms=0.0, frame=np.zeros((1080, 1920, 3), np.uint8)))
            w.finish()
            r = lambda **kw: SimpleNamespace(**{"name": "d", "cache_set": "killfeed",
                                                "hz": 4.0, "spans": [(0.0, 9.0)], **kw})
            self.assertIsNotNone(cache_for(Path(root), _manifest(), profile,
                                           [r(cache_resample=True)])[0])
            self.assertIn("another rate", cache_for(Path(root), _manifest(), profile, [r()])[1])
            # Resampling only thins: a reader faster than the cache is refused.
            self.assertIn("another rate", cache_for(Path(root), _manifest(), profile,
                                                    [r(cache_resample=True, hz=30.0)])[1])

    def test_the_feed_reads_each_span_on_the_readers_grid(self):
        from types import SimpleNamespace
        from reticle.passes import cache_feed
        t = np.array([0, 67, 133, 200, 267, 333, 400, 467, 533, 1000, 1067, 1133, 1200, 1267],
                     float)
        cache = SimpleNamespace(t_ms=t, record={"hz": 15.0})
        dark = SimpleNamespace(name="d", hz=4.0, spans=[(0.0, 533.0), (1000.0, 1300.0)],
                               cache_resample=True)
        times, want = cache_feed([dark], cache)
        # First cached time at or after each 250 ms step, restarted per span.
        self.assertEqual(times, [0.0, 267.0, 533.0, 1000.0, 1267.0])
        # A reader at the cache's rate still takes every frame in its spans.
        full = SimpleNamespace(name="f", hz=15.0, spans=[(0.0, 100.0)])
        times, want = cache_feed([dark, full], cache)
        self.assertEqual(times, sorted(t.tolist()))
        self.assertEqual([r.name for r in want(SimpleNamespace(t_ms=67.0))], ["f"])
        self.assertEqual([r.name for r in want(SimpleNamespace(t_ms=0.0))], ["d", "f"])

    def test_a_cache_fed_coverage_row_names_the_cache(self):
        reader = self._dark([0, 0, 1, 1])
        self.assertNotIn("frames_from", reader.events("s1", None)[0])
        reader.frames_from = "roi-cache-0.1.0"
        self.assertEqual(reader.events("s1", None)[0]["frames_from"], "roi-cache-0.1.0")

    def test_ffv1_short_skips_are_grabbed_and_exact(self):
        from reticle.roi_cache import ffmpeg_path
        try:
            ffmpeg_path()
        except SystemExit:
            self.skipTest("ffmpeg not installed")
        profile = get_profile("valorant-16x9")
        rng = np.random.default_rng(3)
        frames = [rng.integers(0, 255, (1080, 1920, 3), dtype=np.uint8) for _ in range(6)]
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "minimap", hz=15.0,
                               spans=[[0.0, 1000.0]])
            for i, f in enumerate(frames):
                w.feed(Sample(frame_idx=i, t_ms=i * 66.7, frame=f))
            w.finish()
            cache, _ = RoiCache.load(Path(root), _manifest(), profile, "minimap")
            got = {s.frame_idx: s for s in cache.samples([0 * 66.7, 3 * 66.7, 5 * 66.7])}
            self.assertEqual(sorted(got), [0, 3, 5])
            x0, y0, x1, y1 = roi_rects("minimap", profile, (1920, 1080))[0]
            for i, s in got.items():
                self.assertTrue(np.array_equal(s.frame[y0:y1, x0:x1], frames[i][y0:y1, x0:x1]))


class AllyCacheTest(unittest.TestCase):
    """`scan --only ally_icon` reads the 15 Hz minimap cache at 2 Hz: the cached
    frame nearest each instant of the decode's grid."""

    def test_the_ally_reader_resamples_nearest_and_records_the_clip(self):
        from reticle.minimap import AllyIconReader
        from reticle.roi_cache import clip_record, declare_set
        profile = get_profile("valorant-16x9")
        box = roi_rects("minimap", profile, (1920, 1080))[0]
        static = np.zeros((box[3] - box[1], box[2] - box[0], 3), np.uint8)
        reader = AllyIconReader(None, None, static, box)
        declare_set(reader, "minimap", profile, (1920, 1080))
        self.assertEqual((reader.cache_set, reader.cache_resample, reader.records_clip),
                         ("minimap", "nearest", True))
        head = reader.events("s1", [], "rev")[0]
        self.assertNotIn("frames_from", head)
        self.assertNotIn("spans_clip", head)
        clip = clip_record([(0.0, 9.0)], [(1.0, 8.0)], {"version": "roi-cache-0.1.0",
                                                        "roi": "minimap"})
        head = AllyIconReader.replay_events("s1", [], [], 2.0, "rev",
                                            frames_from="roi-cache-0.1.0", spans_clip=clip)[0]
        self.assertEqual((head["frames_from"], head["spans_clip"]), ("roi-cache-0.1.0", clip))

    def test_auto_clips_the_ally_reader_to_the_cached_rounds(self):
        # The player scoped ally tracking to the rounds from the barrier-drop
        # lead onward (2026-09-29): auto reads the cache and records the buy
        # phase before each round as unread.
        from reticle.minimap import AllyIconReader
        from reticle.roi_cache import choose_source, declare_set
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        box = roi_rects("minimap", profile, (1920, 1080))[0]
        static = np.zeros((box[3] - box[1], box[2] - box[0], 3), np.uint8)
        rounds, active = [(1000.0, 2000.0)], [(0.0, 2000.0)]
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "minimap", hz=15.0,
                               spans=[list(s) for s in rounds])
            frame = np.zeros((1080, 1920, 3), np.uint8)
            for i in range(16):
                w.feed(Sample(frame_idx=60 + 4 * i, t_ms=1000.0 + 66.7 * i, frame=frame))
            w.finish()
            reader = AllyIconReader(None, None, static, box, spans=list(active))
            declare_set(reader, "minimap", profile, (1920, 1080))
            cache, why, notes = choose_source(Path(root), _manifest(), profile, [reader],
                                              "auto", lambda: (rounds, None))
            self.assertIsNotNone(cache, why)
            self.assertEqual(reader.spans, rounds)
            self.assertEqual(reader.spans_clip["spans_skipped"], [[0.0, 1000.0]])

    def test_nearest_times_take_the_decodes_phase(self):
        from reticle.roi_cache import nearest_times
        # 60 fps, cached every 4th or 5th frame as a 15 Hz decode takes them.
        idx = [0, 4, 8, 13, 17, 21, 26, 30, 34, 38, 43, 47, 51, 56, 60, 64]
        t = [i * (1.0 / 60.0) * 1000.0 for i in idx]
        # The decode takes frames 0, 30 and 60 from a span asked at 0 ms.
        self.assertEqual(nearest_times(t, [(0.0, 1100.0)], [(0.0, 1100.0)], 0.5),
                         [t[0], t[7], t[14]])
        # Asked at 120 ms, the grid is 120 and 620 ms, near frames 8 and 38.
        self.assertEqual(nearest_times(t, [(120.0, 1100.0)], [(120.0, 1100.0)], 0.5),
                         [t[2], t[9]])
        # Clipped to a round from 550 ms, the phase stays the asked span's.
        self.assertEqual(nearest_times(t, [(120.0, 1100.0)], [(550.0, 1100.0)], 0.5), [t[9]])

    def test_the_feed_phases_a_clipped_reader_at_the_spans_it_asked(self):
        from types import SimpleNamespace
        from reticle.passes import cache_feed
        t = np.array([i * 50.0 for i in range(40)])
        cache = SimpleNamespace(t_ms=t, record={"hz": 20.0})
        ally = SimpleNamespace(name="a", hz=2.0, spans=[(560.0, 1950.0)],
                               cache_resample="nearest",
                               spans_clip={"spans_asked": [[120.0, 1950.0]]})
        times, want = cache_feed([ally], cache)
        # Grid 620, 1120, 1620 ms from the asked start; nearest cached times.
        self.assertEqual(times, [600.0, 1100.0, 1600.0])
        # Unclipped, the phase is its own spans': 560, 1060 and 1560 ms.
        del ally.spans_clip
        self.assertEqual(cache_feed([ally], cache)[0], [600.0, 1050.0, 1550.0])
        ally.hz = 20.0
        # At the cache's rate it takes every cached frame inside its spans.
        self.assertEqual(cache_feed([ally], cache)[0], t.tolist())

    def test_plan_names_the_ally_trial(self):
        from reticle.plan import reader_streams
        from reticle.trial import TRIAL_READERS
        trial = {s: tr for s, _, _, tr in reader_streams()}
        self.assertEqual(trial["ally_icon"], "ally_icon")
        self.assertEqual(TRIAL_READERS["ally_icon"][0], "minimap")


def _needs_ffmpeg(test):
    from reticle.roi_cache import ffmpeg_path
    try:
        ffmpeg_path()
    except SystemExit:
        test.skipTest("ffmpeg not installed")


def _strip_rows(verdicts, version=None):
    from reticle.version import SCOREBOARD_STRIP_VERSION
    common = {"scoreboard_strip_version": version or SCOREBOARD_STRIP_VERSION}
    return ([{**common, "kind": "coverage"}]
            + [{**common, "kind": "sample", "frame_idx": 30 * i, "t_ms": 500.0 * i, "verdict": v}
               for i, v in enumerate(verdicts)])


class ScoreboardGateTest(unittest.TestCase):
    """The scoreboard set keeps the frames the strip witness offers, one
    sample either side, and never asks the slab test."""

    def test_the_gate_is_the_strip_opportunity_with_a_margin(self):
        from reticle.roi_cache import scoreboard_gate
        gate, why = scoreboard_gate(_strip_rows(
            ["absent", "absent", "present", "present", "absent", "absent", "absent",
             "unreadable", "absent", "absent"]))
        self.assertIsNone(why)
        self.assertEqual(gate["spans"], [[500.0, 2000.0], [3000.0, 4000.0]])
        self.assertEqual((gate["samples"], gate["witness_open"], gate["witness_samples"]),
                         (7, 3, 10))
        self.assertEqual(gate["verdicts"], ["present", "unreadable"])

    def test_no_current_strip_rows_is_no_gate(self):
        from reticle.roi_cache import scoreboard_gate
        self.assertIn("no stored", scoreboard_gate([])[1])
        gate, why = scoreboard_gate(_strip_rows(["present"], version="scoreboard-strip-0.0.1"))
        self.assertIsNone(gate)
        self.assertIn("0.0.1", why)

    def test_gate_spans_and_membership(self):
        from reticle.roi_cache import gate_spans, in_spans
        spans = gate_spans([0, 1, 2, 3, 4, 5, 6], [1, 0, 0, 0, 0, 0, 1], 1)
        self.assertEqual(spans, [[0.0, 1.0], [5.0, 6.0]])
        self.assertEqual([in_spans(t, spans) for t in (0, 1, 1.5, 3, 5, 6, 7)],
                         [True, True, False, False, True, True, False])
        self.assertEqual(gate_spans([0, 1, 2], [0, 0, 0], 2), [])

    def test_the_region_is_the_readers_and_needs_the_strip_rectangle(self):
        from reticle.scoreboard import reader_roi, strip_rect
        profile = get_profile("valorant-16x9")
        self.assertEqual(roi_rects("scoreboard", profile, (1920, 1080)),
                         [list(reader_roi(strip_rect(profile.name, 1920, 1080), 1080))])
        self.assertEqual(roi_rects("scoreboard", profile, (1920, 1080)), [[535, 0, 1383, 1080]])
        with self.assertRaises(ValueError):
            roi_rects("scoreboard", profile, (1280, 720))

    def test_scan_refuses_a_scoreboard_cache_it_cannot_write(self):
        from types import SimpleNamespace
        from reticle.cli import _scoreboard_cache_gate
        from reticle.store import Store
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            args = lambda **kw: SimpleNamespace(**{"cache_live": False, "cache_hz": None,
                                                   "hz": 2.0, **kw})
            with self.assertRaises(SystemExit) as no_strip:
                _scoreboard_cache_gate(store, "s1", args())
            self.assertIn("reticle strip s1", str(no_strip.exception))
            store.write_events("scoreboard_strip", "s1", _strip_rows(["absent", "present"]))
            self.assertEqual(_scoreboard_cache_gate(store, "s1", args())["spans"],
                             [[0.0, 500.0]])
            for bad in (args(cache_live=True), args(cache_hz=4.0)):
                with self.assertRaises(SystemExit):
                    _scoreboard_cache_gate(store, "s1", bad)

    def test_a_gated_cache_never_feeds_a_scan(self):
        from types import SimpleNamespace
        from reticle.roi_cache import cache_for, scoreboard_gate
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        gate, _ = scoreboard_gate(_strip_rows(["present"]))
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "scoreboard", hz=2.0, gate=gate)
            w.feed(Sample(frame_idx=0, t_ms=0.0, frame=np.zeros((1080, 1920, 3), np.uint8)))
            w.finish()
            reader = SimpleNamespace(name="sb", cache_set="scoreboard", hz=2.0, spans=None)
            cache, why = cache_for(Path(root), _manifest(), profile, [reader])
            self.assertIsNone(cache)
            self.assertIn("gate kept", why)

    def test_a_gate_that_keeps_nothing_writes_an_empty_cache(self):
        from reticle.roi_cache import scoreboard_gate
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        gate, _ = scoreboard_gate(_strip_rows(["absent", "absent", "absent"]))
        with tempfile.TemporaryDirectory() as root:
            w = RoiCacheWriter(Path(root), _manifest(), profile, "scoreboard", hz=2.0, gate=gate)
            for i in range(3):
                w.feed(Sample(frame_idx=30 * i, t_ms=500.0 * i,
                              frame=np.zeros((1080, 1920, 3), np.uint8)))
            w.finish()
            cache, why = RoiCache.load(Path(root), _manifest(), profile, "scoreboard")
            self.assertIsNone(why)
            self.assertEqual((cache.holds(), cache.record["frames_offered"]), ([], 3))
            self.assertEqual(list(cache.samples([0.0, 500.0])), [])
            self.assertEqual(cache.refusal(500.0), "outside_gate")


class ScoreboardCacheTrialTest(unittest.TestCase):
    """A scan's scoreboard crops, written beside the reader, reproduce its
    rows through `trial` and change none of them."""

    GREEN, RED, BAND = (70, 120, 70), (60, 60, 130), (90, 90, 90)
    X0, X1 = 572, 1348
    RECT = (883, 486, 1037, 594)

    def board(self, rng, lines=True):
        from reticle import scoreboard_strip as strip
        f = rng.integers(30, 50, (1080, 1920, 3), dtype=np.uint8)
        f[510:568, self.X0:self.X1] = self.BAND
        f[340:510, self.X0:self.X1] = self.GREEN
        f[568:738, self.X0:self.X1] = self.RED
        # grain, so a lossy crop could not pass
        f[340:738, self.X0:self.X1] += rng.integers(0, 3, (398, self.X1 - self.X0, 3),
                                                   dtype=np.uint8)
        if lines:
            for y in strip.ROW_Y:
                for k in range(6):
                    x = self.RECT[0] + 12 + 22 * k
                    f[y:y + 2, x:x + 2] = 30
        return f

    def test_trial_from_the_cache_reproduces_the_stored_rows(self):
        import json
        from reticle import scoreboard_strip as strip
        from reticle.roi_cache import scoreboard_gate
        from reticle.scoreboard import ScoreboardReader
        from reticle.store import Store
        from reticle.trial import run
        _needs_ffmpeg(self)
        profile = get_profile("valorant-16x9")
        man = {**_manifest(), "ingested_at": "2026-09-29T00:00:00"}
        man["source"] = {**man["source"], "fps": 60.0}
        rng = np.random.default_rng(5)
        world = lambda: rng.integers(100, 104, (1080, 1920, 3), dtype=np.uint8)
        frames = [world() for _ in range(2)] + [self.board(rng) for _ in range(3)]
        frames += [world() for _ in range(3)]
        samples = [Sample(frame_idx=30 * i, t_ms=500.0 * i, frame=f) for i, f in enumerate(frames)]
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            x0, y0, x1, y1 = self.RECT
            reads = [(s.frame_idx, s.t_ms, strip.read_strip(s.frame[y0:y1, x0:x1], self.RECT))
                     for s in samples]
            strip_rows = strip.strip_events("s1", reads, self.RECT, "roi-cache-0.1.0")
            self.assertEqual([r["verdict"] for r in strip_rows[1:]],
                             ["absent"] * 2 + ["present"] * 3 + ["absent"] * 3)
            store.write_events("scoreboard_strip", "s1", strip_rows)
            gate, _ = scoreboard_gate(strip_rows)
            # the pass without the cache, and the pass with it
            alone = ScoreboardReader(profile.name, icons_root=root,
                                     min_confidence=0.82, min_margin=0.05)
            beside = ScoreboardReader(profile.name, icons_root=root,
                                      min_confidence=0.82, min_margin=0.05)
            w = RoiCacheWriter(Path(root), man, profile, "scoreboard", hz=2.0, gate=gate)
            for s in samples:
                alone.feed(s)
                beside.feed(s)
                w.feed(s)
            w.finish()
            self.assertEqual(alone.events("s1"), beside.events("s1"))
            self.assertGreater(alone.frames_open, 0)
            store.write_events("scoreboard", "s1", beside.events("s1"))
            cache, why = RoiCache.load(Path(root), man, profile, "scoreboard")
            self.assertIsNone(why)
            self.assertEqual(cache.holds(), [500.0, 1000.0, 1500.0, 2000.0, 2500.0])
            self.assertEqual(cache.record["gate"], gate)
            self.assertEqual(cache.record["frames_offered"], 8)
            self.assertEqual(sorted(set(cache.frame_idx.tolist())), [30, 60, 90, 120, 150])
            rx0, ry0, rx1, ry1 = cache.stored_rect("scoreboard")
            for got in cache.samples(cache.holds()):
                src = frames[got.frame_idx // 30]
                self.assertTrue(np.array_equal(got.frame[ry0:ry1, rx0:rx1],
                                               src[ry0:ry1, rx0:rx1]))
                self.assertEqual(int(got.frame[:, :rx0].max()), 0)
            at = {500.0 * i for i in range(1, 6)}
            line = lambda r: json.dumps(r, separators=(",", ":"), allow_nan=False)
            stored = [line(r) for r in store.read_events("scoreboard", "s1")
                      if r["kind"] != "coverage" and r["t_ms"] in at]
            for name, want in (("occupied", {}), ("all", {"outside_gate": 3})):
                res = run(store, man, reader="scoreboard", source="cache", windows=name)
                self.assertEqual((res["frames"], res["refused"]), (5, want), name)
                d = res["diff"]["scoreboard"]
                self.assertEqual((d["only_trial"], d["only_stored"]), (0, 0), name)
                self.assertEqual(d["same"], d["stored_rows"])
                # Byte for byte: the rows the store would write, at the frames read.
                trial = [line(r) for r in res["rows"]["scoreboard"] if r["kind"] != "coverage"]
                self.assertEqual(trial, stored)
