"""Operational scan usage stays separate from stored observations."""

import argparse
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

import numpy as np

from reticle.passes import run_cached
from unittest import mock

from reticle import cli
from reticle.store import Store
from reticle.usage import (BUCKET_LIMITS_NS, CallTimes, CommandUsage, ScanUsage,
                           StepRecorder, format_usage, load, step, usage_level)


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
        self.assertEqual(row["version"], "scan-usage-4")
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

        # The stand-in replaces cv2.VideoCapture rather than subclassing it.
        # OpenCV declares VideoCapture without GC support, and its dealloc
        # frees a Python subclass's instance, which carries a GC header,
        # at the wrong address: the heap corrupts and a later collection
        # crashes the process.
        class FakeVideoCapture(Cap):
            pass

        class Nvdec(Cap, _NvdecCapture):
            def __init__(self):
                Cap.__init__(self)

        ctx = SimpleNamespace(media="x.mp4", fps=2.0)
        for cap, want in ((FakeVideoCapture, "opencv"), (Nvdec, "nvdec")):
            with self.subTest(want):
                usage = ScanUsage(self.manifest, "profile", [Reader()], "video")
                with patch("reticle.decode.open_capture", lambda path: cap()), \
                        patch("reticle.decode.cv2.VideoCapture", FakeVideoCapture):
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


class Stepped(Reader):
    """Two top-level steps per frame, the first with a nested one."""
    shardable = ("seen",)

    def __init__(self, name="stepped", seconds=0.002):
        super().__init__()
        self.name, self.seconds = name, seconds

    def feed(self, sample):
        from reticle.usage import step
        with step("fit"):
            spin(self.seconds)
            with step("grid"):
                spin(self.seconds)
        with step("glyph"):
            spin(self.seconds)
        spin(self.seconds)          # outside every step: `other`
        super().feed(sample)


class StepTest(unittest.TestCase):
    """Named steps inside a reader's feed, per thread, summing to the feed."""

    manifest = {"session_id": "s", "source": {"content_key": "key"}}

    def test_steps_accumulate_by_path_with_nesting(self):
        from reticle.usage import StepRecorder
        rec = StepRecorder(enabled=True)
        reader = Stepped()
        for i in range(4):
            rec.feed(reader.name, reader.feed, i)
        steps = rec.steps("stepped")
        self.assertEqual(sorted(steps), ["fit", "fit/grid", "glyph", "other"])
        self.assertTrue(all(steps[p]["count"] == 4 for p in steps))
        self.assertGreaterEqual(steps["fit"]["total_ns"], steps["fit/grid"]["total_ns"])
        self.assertGreater(steps["fit/grid"]["total_ns"], 4 * 0.001e9)
        self.assertEqual(sum(steps["fit"]["buckets"]), 4)
        self.assertGreaterEqual(steps["fit"]["max_ns"], steps["fit"]["total_ns"] // 4)

    def test_top_level_steps_and_other_sum_to_the_feed(self):
        reader = Stepped()
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        usage.step_times.enabled = True
        run_cached(None, [reader], Frames(6), usage=usage)
        row = usage.record()
        r = row["readers"]["stepped"]
        steps = r["steps"]
        top = sum(t["total_ns"] for p, t in steps.items() if "/" not in p)
        # `other` is the feed less its top-level steps; the record's feed adds
        # only the outer call's few hundred ns around it.
        self.assertLessEqual(top, r["feed"]["total_ns"])
        self.assertLess(r["feed"]["total_ns"] - top, 0.001e9)
        self.assertEqual(steps["other"]["count"], r["feed"]["count"])
        self.assertGreater(steps["other"]["total_ns"], 6 * 0.001e9)
        text = format_usage(row)
        self.assertIn("fit", text)
        self.assertIn("grid", text)
        self.assertIn("(rest)", text)
        self.assertIn("% of feed", text)

    def test_a_reader_without_steps_records_none_and_a_step_outside_a_feed_records_nothing(self):
        from reticle.usage import StepRecorder, step
        with step("loose"):
            pass
        reader = Reader()
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        run_cached(None, [reader], Cache(), usage=usage)
        self.assertEqual(usage.record()["readers"]["probe"]["steps"], {})
        off = StepRecorder(enabled=False)
        off.feed("stepped", Stepped().feed, 0)
        self.assertEqual(off.steps("stepped"), {})

    def test_threads_accumulate_apart_and_merge(self):
        import threading
        from reticle.usage import StepRecorder
        rec = StepRecorder(enabled=True)
        a, b = Stepped(seconds=0.0005), Stepped(seconds=0.0005)
        start = threading.Barrier(2)

        def run(reader, n):
            start.wait()
            for i in range(n):
                rec.feed("stepped", reader.feed, i)
        threads = [threading.Thread(target=run, args=(a, 5)),
                   threading.Thread(target=run, args=(b, 7))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(len(rec._sinks), 2)
        steps = rec.steps("stepped")
        self.assertTrue(all(steps[p]["count"] == 12 for p in steps))

    def test_a_staged_pass_with_shards_merges_every_worker(self):
        from reticle.pipeline import run_staged
        reader = Stepped(seconds=0.0005)
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        usage.step_times.enabled = True
        with usage.timed_pass():
            got = run_staged(None, [reader], Frames(10), usage=usage, workers=2,
                             shards={"stepped": 2})
        usage.staged_run(got)
        self.assertEqual(got.status, "completed", got.error)
        r = usage.record()["readers"]["stepped"]
        self.assertEqual(r["feed"]["count"], 10)
        self.assertTrue(all(t["count"] == 10 for t in r["steps"].values()))
        self.assertEqual(sorted(r["steps"]), ["fit", "fit/grid", "glyph", "other"])

    def test_load_reads_every_version_and_formats_rows_without_steps(self):
        reader = Stepped(seconds=0.0001)
        usage = ScanUsage(self.manifest, "profile", [reader], "cache:cache-test")
        usage.step_times.enabled = True
        run_cached(None, [reader], Frames(2), usage=usage)
        new = usage.record()
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "notes" / "usage.jsonl"
            path.parent.mkdir(parents=True)
            rows = []
            for version in ("scan-usage-1", "scan-usage-2", "scan-usage-3"):
                old = json.loads(json.dumps(new))
                old["version"] = version
                for r in old["readers"].values():
                    r.pop("steps")
                rows.append(old)
            rows.append(new)
            rows.append({**new, "version": "scan-usage-0"})
            path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            got = load(Path(root), "s")
        self.assertEqual([r["version"] for r in got],
                         ["scan-usage-1", "scan-usage-2", "scan-usage-3", "scan-usage-4"])
        self.assertNotIn("fit", format_usage(got[2]))
        self.assertIn("fit", format_usage(got[3]))


def _level(value, steps=None):
    env = {k: v for k, v in os.environ.items() if k not in ("RETICLE_USAGE", "RETICLE_USAGE_STEPS")}
    if value is not None:
        env["RETICLE_USAGE"] = value
    if steps is not None:
        env["RETICLE_USAGE_STEPS"] = steps
    return mock.patch.dict(os.environ, env, clear=True)


class CommandUsageTest(unittest.TestCase):
    def test_record_fields_and_steps_inside_the_command(self):
        def body():
            with step("compute"):
                with step("inner"):
                    pass
            return 0
        with _level(None):
            usage = CommandUsage("deaths", {"session": "s1", "func": None, "n": Path("x")}, "s1")
            self.assertEqual(usage.run(body), 0)
        row = usage.record()
        for key in ("version", "command", "arguments", "session_id", "recorded_at", "wall_ns",
                    "cpu_ns", "contention", "code_revision", "status", "error", "steps"):
            self.assertIn(key, row)
        self.assertEqual((row["version"], row["status"], row["exit_code"]),
                         ("command-usage-1", "completed", 0))
        self.assertEqual(row["arguments"]["n"], "x")
        self.assertEqual(set(row["steps"]), {"compute", "compute/inner", "other"})
        self.assertIn("priority", row["contention"])
        self.assertIn("compute", format_usage(row))

    def test_exception_records_failed_and_reraises(self):
        def body():
            raise RuntimeError("boom")
        with _level(None), tempfile.TemporaryDirectory() as root:
            usage = CommandUsage("deaths", {}, "s1")
            with self.assertRaises(RuntimeError):
                usage.run(body)
            usage.write(Path(root))
            (row,) = load(Path(root))
        self.assertEqual(row["status"], "failed")
        self.assertIn("boom", row["error"])

    def test_read_steps_are_keyed_by_stream_and_totalled(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.write_events("killfeed_portrait", "s1", [{"t_ms": 1}])
            path = store.events_path("killfeed_portrait", "s1")

            def body():
                store.read_events("killfeed_portrait", "s1")
                with step("compute"):
                    store.read_events("killfeed_portrait", "s1")
                    store.events_version("killfeed_portrait", "s1")
                return 0
            with _level(None):
                usage = CommandUsage("deaths", {}, "s1")
                usage.run(body)
            steps = usage.record()["steps"]
            self.assertEqual(steps["read:killfeed_portrait"]["count"], 1)
            self.assertEqual(steps["read:killfeed_portrait"]["bytes"], path.stat().st_size)
            self.assertEqual(steps["compute/read:killfeed_portrait"]["count"], 1)
            self.assertIn("compute/read:killfeed_portrait:version", steps)
            self.assertNotIn("bytes", steps["compute/read:killfeed_portrait:version"])
            text = format_usage(usage.record())
            self.assertRegex(text, r"read:killfeed_portrait\s+\d\.\d+s\s+2 calls")

    def test_marked_steps_of_the_stored_data_commands_reach_the_record(self):
        from reticle.lineup import load_lineup
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.write_kf_mask("s1", np.zeros((2, 2), bool))

            def body():
                self.assertIsNone(load_lineup("s1", root))
                store.read_kf_mask("s1")
                return 0
            with _level(None):
                usage = CommandUsage("deaths", {}, "s1")
                usage.run(body)
            steps = usage.record()["steps"]
        self.assertEqual(steps["load_lineup"]["count"], 1)
        self.assertEqual(steps["read:kf_mask"]["count"], 1)
        self.assertGreater(steps["read:kf_mask"]["bytes"], 0)
        self.assertRegex(format_usage(usage.record()), r"load_lineup\s+\d\.\d+s\s+1 call")

    def test_no_sink_records_nothing(self):
        with tempfile.TemporaryDirectory() as root:
            store = Store(root)
            store.write_events("hud_x", "s1", [{"t_ms": 1}])
            with _level(None):
                self.assertEqual(len(store.read_events("hud_x", "s1")), 1)
                rec = StepRecorder(enabled=True)
                self.assertEqual(rec.steps("deaths"), {})

    def _run_main(self, root, cmd, fn, level):
        parser = argparse.ArgumentParser()
        parser.add_argument("--store", default=str(root))
        sub = parser.add_subparsers(dest="cmd", required=True)
        s = sub.add_parser(cmd)
        s.add_argument("session", nargs="?")
        s.set_defaults(func=fn)
        with _level(level), mock.patch.object(cli, "build_parser", lambda: parser):
            return cli.main(["--store", str(root), cmd, "s1"])

    def test_main_records_listed_commands_only(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._run_main(root, "rounds", lambda a: 0, None), 0)
            self.assertEqual(self._run_main(root, "doctor", lambda a: 0, None), 0)
            rows = load(Path(root))
        self.assertEqual([(r["command"], r["session_id"]) for r in rows], [("rounds", "s1")])

    def test_main_failed_command_is_recorded_and_raises(self):
        def fail(a):
            raise ValueError("bad")
        with tempfile.TemporaryDirectory() as root:
            with self.assertRaises(ValueError):
                self._run_main(root, "deaths", fail, None)
            (row,) = load(Path(root))
        self.assertEqual(row["status"], "failed")

    def test_levels(self):
        with _level("off"):
            self.assertEqual(usage_level(), "off")
        with _level("record"):
            self.assertEqual(usage_level(), "record")
        with _level(None):
            self.assertEqual(usage_level(), "steps")
        with _level(None, "0"):
            self.assertEqual(usage_level(), "record")
        with _level("steps", "0"):
            self.assertEqual(usage_level(), "steps")
        with _level("bogus"), self.assertRaises(ValueError):
            usage_level()

    def test_command_levels(self):
        def body():
            with step("compute"):
                pass
            return 0
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(self._run_main(root, "rounds", lambda a: body(), "record"), 0)
            self.assertEqual(self._run_main(root, "rounds", lambda a: body(), "steps"), 0)
            self.assertEqual(self._run_main(root, "rounds", lambda a: body(), "off"), 0)
            rows = load(Path(root))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["steps"], {})
        self.assertIn("compute", rows[1]["steps"])

    def test_off_writes_nothing_for_scans_or_commands(self):
        manifest = {"session_id": "s", "source": {"content_key": "key"}}
        with tempfile.TemporaryDirectory() as root, _level("off"):
            reader = Reader()
            scan = ScanUsage(manifest, "profile", [reader], "cache:cache-test")
            run_cached(None, [reader], Cache(), usage=scan)
            self.assertIsNone(scan.write(Path(root)))
            self.assertIsNone(scan.write_metric(Path(root)))
            self.assertIsNone(scan.code_revision)
            self.assertEqual(scan.record()["readers"]["probe"]["steps"], {})
            self.assertEqual(self._run_main(root, "rounds", lambda a: 0, "off"), 0)
            self.assertEqual(list(Path(root).rglob("*.jsonl")), [])
            self.assertEqual(load(Path(root)), [])

    def test_record_level_scan_has_no_steps_but_writes(self):
        manifest = {"session_id": "s", "source": {"content_key": "key"}}
        with tempfile.TemporaryDirectory() as root, _level("record"):
            reader = Reader()
            scan = ScanUsage(manifest, "profile", [reader], "cache:cache-test")
            run_cached(None, [reader], Cache(), usage=scan)
            scan.write(Path(root))
            (row,) = load(Path(root))
        self.assertEqual(row["readers"]["probe"]["steps"], {})

    def test_every_listed_command_is_a_subcommand(self):
        from reticle.plan import rerun_commands
        parser = cli.build_parser()
        names = set(next(a for a in parser._actions
                         if isinstance(a, argparse._SubParsersAction)).choices)
        self.assertLessEqual(rerun_commands(), names)
        self.assertNotIn("scan", rerun_commands())

if __name__ == "__main__":
    unittest.main()
