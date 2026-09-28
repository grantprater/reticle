"""Operational scan usage stays separate from stored observations."""

import json
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from reticle.passes import run_cached
from reticle.usage import BUCKET_LIMITS_NS, CallTimes, ScanUsage, format_usage, load


class Reader:
    name = "probe"
    hz = 2.0
    spans = None
    cache_set = "killfeed"

    def __init__(self):
        self.seen = []
        self.finished = False

    def feed(self, sample):
        self.seen.append(sample)

    def finish(self):
        self.finished = True


class Cache:
    record = {"version": "cache-test"}
    t_ms = np.array([0, 500, 1000])

    def samples(self, targets_ms, rois):
        assert targets_ms == [0, 500, 1000]
        for t_ms in targets_ms:
            yield t_ms


class UsageTest(unittest.TestCase):
    def test_bucket_boundaries(self):
        times = CallTimes()
        for ns in (0, BUCKET_LIMITS_NS[0] - 1, BUCKET_LIMITS_NS[0],
                   BUCKET_LIMITS_NS[-1] + 1):
            times.add(ns)
        self.assertEqual(times.record()["buckets"][0], 2)
        self.assertEqual(times.record()["buckets"][1], 1)
        self.assertEqual(times.record()["buckets"][-1], 1)

    def test_cached_pass_records_one_shared_source_and_reader_calls(self):
        manifest = {"session_id": "s", "source": {"content_key": "key"}}
        reader = Reader()
        usage = ScanUsage(manifest, "profile", [reader], "cache:cache-test")
        self.assertEqual(run_cached(None, [reader], Cache(), usage=usage), 3)
        self.assertEqual(reader.seen, [0, 500, 1000])
        self.assertTrue(reader.finished)
        row = usage.record()
        self.assertEqual(row["source_calls"]["count"], 3)
        self.assertEqual(row["readers"]["probe"]["feed"]["count"], 3)
        self.assertEqual(row["readers"]["probe"]["hz"], 2.0)
        self.assertIn("probe", format_usage(row))
        with tempfile.TemporaryDirectory() as d:
            usage.write(Path(d))
            self.assertEqual(load(Path(d), "s")[0]["content_key"], "key")
            self.assertEqual(load(Path(d), "other"), [])
            path = Path(d) / "notes" / "usage.jsonl"
            self.assertEqual(len(path.read_text().splitlines()), 1)
            self.assertEqual(json.loads(path.read_text())["kind"], "vod_scan")


class StagedRecordTest(unittest.TestCase):
    """What a staged pass did reaches the record; each configuration is a series."""

    manifest = {"session_id": "s", "source": {"content_key": "key"}}

    def test_a_staged_pass_records_offered_fed_and_each_shard(self):
        from reticle.pipeline import StagedRun
        usage = ScanUsage(self.manifest, "profile", [Reader()], "cache:cache-test")
        usage.staged_run(StagedRun(
            frames=5, workers=2, shards={"probe": 2}, cv_threads={"pass": 1, "toggled": []},
            offered={"probe": 5}, fed={"probe": 5}, wait_ns=7,
            units=[{"label": "probe#0", "reader": "probe", "fed": 3, "max_queued": 2},
                   {"label": "probe#1", "reader": "probe", "fed": 2, "max_queued": 1}]))
        row = usage.record()
        self.assertEqual(row["readers"]["probe"]["offered"], 5)
        self.assertEqual([u["fed"] for u in row["readers"]["probe"]["shards"]], [3, 2])
        self.assertEqual(row["dispatcher"]["wait_ns"], 7)
        self.assertEqual((row["pipeline"], row["workers"], row["shards"]),
                         ("staged", 2, {"probe": 2}))

    def test_a_serial_pass_records_its_feeds_and_no_queue(self):
        reader = Reader()
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        run_cached(None, [reader], Cache(), usage=usage)
        row = usage.record()
        self.assertEqual((row["readers"]["probe"]["offered"], row["readers"]["probe"]["fed"]),
                         (3, 3))
        self.assertEqual(row["readers"]["probe"]["shards"], [])
        self.assertIsNone(row["dispatcher"]["wait_ns"])

    def test_each_configuration_is_its_own_metrics_series(self):
        def part(pipeline, workers=None, shards=None, cv=12, source="cache:cache-test"):
            usage = ScanUsage(self.manifest, "profile", [Reader()], source)
            usage.pipeline, usage.workers = pipeline, workers
            usage.shards, usage.cv_threads = dict(shards or {}), {"pass": cv}
            return usage.series_part()
        self.assertEqual(part("serial"), "probe/cache/serial/cv12")
        self.assertEqual(part("staged", 1, cv=1), "probe/cache/staged/w1/cv1")
        self.assertEqual(part("staged", 2, {"probe": 2}, cv=1),
                         "probe/cache/staged/w2/probe=2/cv1")
        self.assertEqual(part("serial", source="video"), "probe/video/serial/cv12")
        prefix = ScanUsage(self.manifest, "profile", [Reader()], "video")
        prefix.cv_threads, prefix.until_s = {"pass": 12}, 180.0
        self.assertEqual(prefix.series_part(), "probe/video/serial/cv12/until180")
        self.assertEqual(prefix.record()["until_s"], 180.0)
        self.assertIsNone(ScanUsage(self.manifest, "profile", [Reader()],
                                    "video").record()["until_s"])
        usage = ScanUsage(self.manifest, "profile", [Reader()], "cache:cache-test")
        usage.cv_threads = {"pass": 1}
        with tempfile.TemporaryDirectory() as d:
            row = usage.write_metric(Path(d))
        self.assertEqual((row["tool"], row["part"], row["session"]),
                         ("scan_usage", "probe/cache/serial/cv1", "s"))


#: Windows counts thread and process CPU in clock ticks of 15.6 ms, so each
#: CPU difference below may be off by one tick.
TICK_NS = 16_000_000


def spin(seconds):
    end = time.perf_counter() + seconds
    while time.perf_counter() < end:
        pass


class Timed(Reader):
    """Spins (computes) or sleeps (waits) for a fixed wall per frame."""

    def __init__(self, name, work="spin", seconds=0.015):
        super().__init__()
        self.name, self.work, self.seconds = name, work, seconds

    def feed(self, sample):
        (spin if self.work == "spin" else time.sleep)(self.seconds)
        super().feed(sample)


class Rows(Timed):
    shardable = ("seen",)


class Frames:
    """A crop cache's duck type with `n` frames, half a second apart."""
    record = {"version": "cache-test"}

    def __init__(self, n=20):
        self.t_ms = np.arange(n) * 500.0

    def samples(self, targets_ms, rois=None):
        from reticle.decode import Sample
        for i, t in enumerate(targets_ms):
            yield Sample(frame_idx=i, t_ms=float(t), frame=np.zeros((2, 2, 3), np.uint8))


class CpuTimeTest(unittest.TestCase):
    """CPU per process, dispatcher and worker thread tells computing from waiting."""

    manifest = {"session_id": "s", "source": {"content_key": "key"}}

    def staged(self, readers, **kw):
        from reticle.pipeline import run_staged
        usage = ScanUsage(self.manifest, "profile", readers, "cache:cache-test")
        with usage.timed_pass():
            got = run_staged(None, readers, Frames(), usage=usage, **kw)
        usage.staged_run(got)
        self.assertEqual(got.status, "completed", got.error)
        return usage

    def test_a_serial_pass_charges_its_one_thread_to_the_dispatcher(self):
        reader = Timed("busy")
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        with usage.timed_pass():
            run_cached(None, [reader], Frames(), usage=usage)
        row = usage.record()
        busy = row["readers"]["busy"]
        self.assertIsNone(busy["thread_cpu_ns"])
        self.assertIn("dispatcher", busy["thread_cpu_reason"])
        self.assertEqual(busy["shards"], [])
        own = row["dispatcher"]["thread_cpu_ns"]
        self.assertGreater(own, 0.5 * busy["feed"]["total_ns"])
        self.assertLessEqual(own, row["cpu_ns"] + 2 * TICK_NS)
        self.assertGreater(row["pass_ns"], 0)
        values = usage.metric_values()
        self.assertTrue({"pass_s", "source_s", "cpu_s", "dispatcher_cpu_s",
                         "feed_s_busy"} <= set(values))
        self.assertNotIn("thread_cpu_s_busy", values)
        self.assertNotIn("dispatcher_wait_s", values)

    def test_a_computing_worker_shows_cpu_near_its_wall_and_a_waiting_one_does_not(self):
        usage = self.staged([Timed("busy"), Timed("idle", work="sleep")], workers=2)
        row = usage.record()
        busy, idle = row["readers"]["busy"], row["readers"]["idle"]
        wall_busy, wall_idle = busy["shards"][0]["busy_ns"], idle["shards"][0]["busy_ns"]
        self.assertGreater(wall_busy, 0.2e9)
        self.assertGreater(busy["thread_cpu_ns"], 0.5 * wall_busy)
        self.assertLessEqual(busy["thread_cpu_ns"], wall_busy + 2 * TICK_NS)
        self.assertLess(idle["thread_cpu_ns"], 0.3 * wall_idle + 2 * TICK_NS)
        values = usage.metric_values()
        self.assertTrue({"cpu_s", "dispatcher_cpu_s", "dispatcher_wait_s",
                         "thread_cpu_s_busy", "thread_cpu_s_idle"} <= set(values))

    def test_thread_cpu_sums_to_at_most_the_process_cpu(self):
        usage = self.staged([Timed("a"), Timed("b"), Timed("c", work="sleep")], workers=3)
        row = usage.record()
        threads = [row["dispatcher"]["thread_cpu_ns"]] + [
            u["thread_cpu_ns"] for r in row["readers"].values() for u in r["shards"]]
        self.assertEqual(len(threads), 4)
        self.assertLessEqual(sum(threads), row["cpu_ns"] + (len(threads) + 1) * TICK_NS)
        # Two spinning workers under one GIL: their CPU together stays near
        # the pass's wall, not twice it -- the serialization the record shows.
        both = row["readers"]["a"]["thread_cpu_ns"] + row["readers"]["b"]["thread_cpu_ns"]
        self.assertLessEqual(both, row["pass_ns"] + 3 * TICK_NS)

    def test_shards_list_their_cpu_and_the_reader_sums_them(self):
        usage = self.staged([Rows("rows")], workers=2, shards={"rows": 2})
        rows = usage.record()["readers"]["rows"]
        self.assertEqual([u["label"] for u in rows["shards"]], ["rows#0", "rows#1"])
        self.assertEqual(rows["thread_cpu_ns"], sum(u["thread_cpu_ns"] for u in rows["shards"]))
        self.assertIsNone(rows["thread_cpu_reason"])

    def test_workers_0_starts_no_thread_and_says_so(self):
        usage = self.staged([Timed("busy", seconds=0.001)], workers=0)
        busy = usage.record()["readers"]["busy"]
        self.assertIsNone(busy["thread_cpu_ns"])
        self.assertIn("dispatcher", busy["thread_cpu_reason"])
        self.assertIsNone(busy["shards"][0]["thread_cpu_ns"])

    def test_field_names_are_identifiers(self):
        usage = ScanUsage(self.manifest, "profile", [Timed("lineup:s", seconds=0)],
                          "cache:cache-test")
        self.assertIn("feed_s_lineup_s", usage.metric_values())



class ContentionAndBackendTest(unittest.TestCase):
    """The record says what else ran during the pass and what decoded it."""

    manifest = {"session_id": "s", "source": {"content_key": "key"}}

    def test_other_load_is_system_cpu_less_this_process(self):
        from unittest.mock import patch
        import reticle.usage as usage_mod
        ticks = iter([1_000_000_000, 5_000_000_000])
        usage = ScanUsage(self.manifest, "profile", [Reader()], "cache:cache-test")
        with patch.object(usage_mod, "system_cpu_ns", lambda: next(ticks)):
            with usage.timed_pass():
                pass
        row = usage.record()
        self.assertEqual(row["version"], "scan-usage-3")
        got = row["contention"]
        self.assertEqual(got["system_cpu_ns"], 4_000_000_000)
        self.assertEqual(got["other_cpu_ns"], 4_000_000_000 - row["cpu_ns"])
        self.assertGreater(got["logical_cpus"], 0)
        self.assertIn("priority", got)
        self.assertIn("other_cpu_s", usage.metric_values())

    def test_no_system_counter_leaves_contention_null_with_a_reason(self):
        from unittest.mock import patch
        import reticle.usage as usage_mod
        usage = ScanUsage(self.manifest, "profile", [Reader()], "cache:cache-test")
        with patch.object(usage_mod, "system_cpu_ns", lambda: None):
            with usage.timed_pass():
                pass
        got = usage.record()["contention"]
        self.assertIsNone(got["other_cpu_ns"])
        self.assertTrue(got["reason"])
        self.assertNotIn("other_cpu_s", usage.metric_values())

    def test_a_decode_records_its_backend(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from reticle.decode import _NvdecCapture
        from reticle.passes import run

        class Cap:
            def __init__(self):
                self.pos = -1

            def isOpened(self):
                return True

            def grab(self):
                self.pos += 1
                return self.pos < 3

            def get(self, prop):
                return self.pos * 500.0

            def retrieve(self):
                return True, np.zeros((2, 2, 3), np.uint8)

            def release(self):
                pass

        import cv2

        class OpenCV(Cap, cv2.VideoCapture):
            def __init__(self):
                cv2.VideoCapture.__init__(self)
                Cap.__init__(self)

        class Nvdec(Cap, _NvdecCapture):
            def __init__(self):
                Cap.__init__(self)

        ctx = SimpleNamespace(media="x.mp4", fps=2.0)
        for cap, want in ((OpenCV, "opencv"), (Nvdec, "nvdec")):
            with self.subTest(want):
                usage = ScanUsage(self.manifest, "profile", [Reader()], "video")
                with patch("reticle.decode.open_capture", lambda path: cap()):
                    run(ctx, [Reader()], usage=usage)
                self.assertEqual(usage.record()["decode_backend"]["backend"], want)

    def test_a_cache_pass_records_the_cache_codec(self):
        reader = Reader()
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        cache = Cache()
        cache.record = {"version": "cache-test", "codec": "ffv1"}
        run_cached(None, [reader], cache, usage=usage)
        self.assertEqual(usage.record()["decode_backend"],
                         {"backend": "opencv", "codec": "ffv1", "source": "cache"})


if __name__ == "__main__":
    unittest.main()
