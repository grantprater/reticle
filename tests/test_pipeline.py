"""The staged pass reproduces the serial one, and fails without hanging.

Synthetic readers over a synthetic source; no store, no media.
"""
import contextlib
import io
import math
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import cv2
import numpy as np

from reticle.candidate_evidence import revision
from reticle.decode import Sample
from reticle.passes import run, run_cached
from reticle.pipeline import FIFO_DEPTH, compare_trees, limit_to_prefix, run_staged
from reticle.usage import ScanUsage


class Cache:
    """`RoiCache`'s duck type: a record, timestamps and `samples`."""

    def __init__(self, n=40, step_ms=500.0, shape=(6, 8, 3)):
        self.record = {"version": "cache-test"}
        self.t_ms = np.arange(n) * step_ms
        self.shape = shape
        self.closed = False
        self.produced = 0
        self.consumed = 0          # a reader under test may count here
        self.ahead = 0

    def samples(self, targets_ms, rois=None):
        try:
            for i, t in enumerate(targets_ms):
                frame = np.full(self.shape, i % 251, np.uint8)
                frame[0, 0, 0] = i % 7
                self.produced += 1
                self.ahead = max(self.ahead, self.produced - self.consumed)
                yield Sample(frame_idx=i * 30, t_ms=float(t), frame=frame)
        finally:
            self.closed = True


class Collect:
    """A pure reader: one row per frame."""
    cache_set = "killfeed"

    def __init__(self, name="collect", spans=None, hz=2.0, sleep=0.0):
        self.name, self.spans, self.hz, self.sleep = name, spans, hz, sleep
        self.rows = []
        self.frames_from = "video"

    def feed(self, smp):
        if self.sleep:
            time.sleep(self.sleep)
        self.rows.append((smp.frame_idx, smp.t_ms, int(smp.frame.sum()), self.frames_from))

    def finish(self):
        return len(self.rows)


class Stateful(Collect):
    """Reads what the previous frame left, so it must see increasing t_ms."""

    def __init__(self, name="stateful", **kw):
        super().__init__(name, **kw)
        self.prev = None

    def feed(self, smp):
        if self.prev is not None and smp.t_ms <= self.prev:
            raise AssertionError(f"t_ms went back: {smp.t_ms} after {self.prev}")
        self.prev = smp.t_ms
        super().feed(smp)


class Candidates:
    """Shardable, appending a frame's candidates the way `AllyIconReader` does:
    self before ally, each by raw index, a varying number per frame."""
    cache_set = "killfeed"
    shardable = ("frames", "candidates")

    def __init__(self, name="cands", spans=None, hz=2.0):
        self.name, self.spans, self.hz = name, spans, hz
        self.frames, self.candidates = [], []
        self.frames_from = "video"

    def feed(self, smp):
        i = smp.frame_idx
        self.frames.append({"frame_idx": i, "t_ms": smp.t_ms, "from": self.frames_from})
        for k in range((i // 30) % 2):
            self.candidates.append({"key": f"{i}:self:{k}", "v": int(smp.frame[0, 0, 0])})
        for k in range((i // 30) % 4):
            self.candidates.append({"key": f"{i}:ally:{k}", "v": k * int(smp.frame.sum())})

    def doc(self):
        return {"frames": self.frames, "rows": self.candidates}


class Painting(Candidates):
    """Breaks the shard contract in place: writes into an array it holds."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.canvas = np.zeros(4, np.uint8)

    def feed(self, smp):
        self.canvas[0] += 1
        super().feed(smp)


class Counting(Candidates):
    """Breaks the shard contract: rebinds a counter outside its lists."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.n = 0

    def feed(self, smp):
        self.n += 1
        super().feed(smp)


class Raises(Collect):
    def __init__(self, name="raises", at=3, **kw):
        super().__init__(name, **kw)
        self.at = at

    def feed(self, smp):
        if len(self.rows) == self.at:
            raise RuntimeError(f"broke at frame {smp.frame_idx}")
        super().feed(smp)


class Writes(Collect):
    def feed(self, smp):
        smp.frame[0, 0, 0] = 255


def within(seconds, fn):
    """Run `fn` on a thread; fail if it has not returned in `seconds`."""
    box = {}

    def target():
        try:
            box["value"] = fn()
        except BaseException as exc:
            box["error"] = exc
    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)
    if t.is_alive():
        raise AssertionError(f"did not return within {seconds} s")
    if "error" in box:
        raise box["error"]
    return box["value"]


def readers():
    return [Collect("a"), Collect("b", spans=[(2000.0, 9000.0), (12000.0, 15000.0)]),
            Stateful(spans=[(0.0, 11000.0)])]


class StagedEqualsSerialTests(unittest.TestCase):
    def test_every_worker_count_reproduces_the_serial_pass(self):
        serial = readers()
        n = run_cached(None, serial, Cache())
        want = [(r.rows, r.frames_from) for r in serial]
        for workers in range(5):
            with self.subTest(workers=workers):
                staged = readers()
                got = within(30, lambda: run_staged(None, staged, Cache(), workers=workers))
                self.assertEqual(got.status, "completed", got.error)
                self.assertEqual(got.frames, n)
                self.assertEqual([(r.rows, r.frames_from) for r in staged], want)
                self.assertEqual(got.finished, {r.name: len(r.rows) for r in serial})
                self.assertEqual(got.offered, got.fed)

    def test_the_cache_path_never_thins(self):
        # At 0.5 Hz a decode would take every fourth 2 Hz frame; the cache's
        # rate was matched before the pass, so every frame inside the spans
        # is fed, as `run_cached` feeds it.
        spans = [(1000.0, 6000.0), (6200.0, 9000.0)]
        serial = [Collect("slow_rate", hz=0.5, spans=spans)]
        run_cached(None, serial, Cache())
        for workers in (0, 1):
            staged = [Collect("slow_rate", hz=0.5, spans=spans)]
            run_staged(None, staged, Cache(), workers=workers)
            self.assertEqual(staged[0].rows, serial[0].rows)
            self.assertEqual([t for _, t, _, _ in staged[0].rows],
                             [t for t in Cache().t_ms.tolist()
                              if any(a <= t <= b for a, b in spans)])

    def test_workers_0_feeds_in_the_serial_order_on_video(self):
        # `passes.run` feeds in the order of the set `sample_multi` yields,
        # here the reverse of the list's; inline feeding must match it.
        log = []

        class Logs(Collect):
            def feed(self, smp):
                log.append(self.name)
                super().feed(smp)

        def sample_multi(path, fps, req, info=None):
            for i in range(3):
                yield ("b", "a"), Sample(i, i * 500.0, np.full((2, 2, 3), i, np.uint8))
        ctx = SimpleNamespace(media="x.mp4", fps=60.0)
        with patch("reticle.decode.sample_multi", sample_multi):
            run(ctx, [Logs("a"), Logs("b")])
            serial, log[:] = list(log), []
            run_staged(ctx, [Logs("a"), Logs("b")], None, workers=0)
        self.assertEqual(serial, ["b", "a"] * 3)
        self.assertEqual(log, serial)

    def test_a_video_source_feeds_whoever_sample_multi_names(self):
        frames = [(frozenset({"a"}), 0), (frozenset({"a", "b"}), 1), (frozenset({"b"}), 2),
                  (frozenset({"a", "b"}), 3)]

        def sample_multi(path, fps, req, info=None):
            for who, i in frames:
                yield who, Sample(i, i * 500.0, np.full((2, 2, 3), i, np.uint8))
        ctx = SimpleNamespace(media="x.mp4", fps=60.0)
        with patch("reticle.decode.sample_multi", sample_multi):
            serial = [Collect("a"), Collect("b")]
            run(ctx, serial)
            for workers in (0, 2):
                staged = [Collect("a"), Collect("b")]
                got = run_staged(ctx, staged, None, workers=workers)
                self.assertEqual(got.frames, 4)
                self.assertEqual([r.rows for r in staged], [r.rows for r in serial])


class ShardTests(unittest.TestCase):
    def test_a_merge_keeps_producer_order_and_the_revision_id(self):
        serial = Candidates()
        run_cached(None, [serial], Cache(n=60))
        self.assertTrue(serial.candidates)
        # Frames with both kinds, so a sort within a frame moves a candidate.
        kinds = {}
        for c in serial.candidates:
            kinds.setdefault(c["key"].split(":")[0], set()).add(c["key"].split(":")[1])
        self.assertTrue(any(k == {"self", "ally"} for k in kinds.values()))
        want = revision(serial.doc())
        # A sort by key would move the id: the test can see a reordering.
        by_key = {"frames": serial.frames,
                  "rows": sorted(serial.candidates, key=lambda c: c["key"])}
        self.assertNotEqual(revision(by_key), want)
        for workers in (0, 1, 2, 4):
            for k in (2, 3):
                with self.subTest(workers=workers, shards=k):
                    staged = Candidates()
                    got = within(30, lambda: run_staged(None, [staged], Cache(n=60),
                                                        workers=workers, shards={"cands": k}))
                    self.assertEqual(got.status, "completed", got.error)
                    self.assertEqual(staged.candidates, serial.candidates)
                    self.assertEqual(staged.frames, serial.frames)
                    self.assertEqual(revision(staged.doc()), want)

    def test_shards_carry_the_chosen_sources_frames_from(self):
        staged = Candidates()
        run_staged(None, [staged], Cache(), workers=2, shards={"cands": 2})
        self.assertEqual({f["from"] for f in staged.frames}, {"cache-test"})

    def test_a_reader_that_declares_no_outputs_cannot_shard(self):
        with self.assertRaisesRegex(ValueError, "shardable"):
            run_staged(None, [Collect("a")], Cache(), workers=1, shards={"a": 2})

    def test_a_shard_that_rebinds_other_state_is_refused(self):
        with self.assertRaisesRegex(ValueError, "rebound `n`"):
            run_staged(None, [Counting()], Cache(), workers=1, shards={"cands": 2})

    def test_a_shard_that_writes_into_a_held_array_fails_and_the_flag_returns(self):
        for workers in (0, 2):
            with self.subTest(workers=workers):
                r = Painting()
                got = within(30, lambda: run_staged(None, [r], Cache(), workers=workers,
                                                    shards={"cands": 2}))
                self.assertEqual(got.status, "failed")
                self.assertIn("read-only", str(got.exception))
                self.assertTrue(r.canvas.flags.writeable)
        # Unsharded, the same reader owns its array and may write it.
        r = Painting()
        self.assertEqual(run_staged(None, [r], Cache(n=5), workers=1).status, "completed")
        self.assertEqual(r.canvas[0], 5)

    def test_units_record_each_shards_frames(self):
        got = run_staged(None, [Candidates()], Cache(n=9), workers=2, shards={"cands": 2})
        self.assertEqual([(u["label"], u["fed"]) for u in got.units],
                         [("cands#0", 5), ("cands#1", 4)])
        self.assertTrue(all(u["max_queued"] is not None for u in got.units))

    # The revision is git's answer, two subprocesses; this test never reads it.
    @patch("reticle.usage.code_revision", lambda root=None: {"sha": "0000000", "dirty": False})
    def test_shards_share_their_readers_usage(self):
        manifest = {"session_id": "s", "source": {"content_key": "k"}}
        staged = Candidates()
        usage = ScanUsage(manifest, "p", [staged], "cache:cache-test")
        got = run_staged(None, [staged], Cache(), workers=2, shards={"cands": 2}, usage=usage)
        self.assertEqual(usage.record()["readers"]["cands"]["feed"]["count"],
                         got.offered["cands"])
        self.assertEqual(usage.record()["source_calls"]["count"], got.frames)


class FailureTests(unittest.TestCase):
    def test_a_reader_that_raises_ends_the_run_with_its_exception(self):
        for workers in (0, 1, 2):
            with self.subTest(workers=workers):
                cache = Cache(n=400)
                others = [Collect("fine", sleep=0.001), Stateful()]
                bad = Raises(at=5)
                got = within(30, lambda: run_staged(None, others + [bad], cache,
                                                    workers=workers, depth=2))
                self.assertEqual(got.status, "failed")
                self.assertIsInstance(got.exception, RuntimeError)
                self.assertIn("raises", got.error)
                self.assertTrue(cache.closed)
                self.assertEqual(got.finished, {})
                self.assertLess(got.frames, 400)
                with self.assertRaises(RuntimeError):
                    got.raise_for_status()

    def test_a_reader_that_writes_into_a_frame_raises(self):
        for workers in (0, 1):
            with self.subTest(workers=workers):
                got = within(30, lambda: run_staged(None, [Collect("a"), Writes("w")],
                                                    Cache(), workers=workers))
                self.assertEqual(got.status, "failed")
                self.assertIsInstance(got.exception, ValueError)
                self.assertIn("read-only", str(got.exception))

    def test_a_failure_during_setup_joins_the_workers_and_restores_the_count(self):
        before = cv2.getNumThreads()

        class Broken:
            def timed_frames(self, frames):
                raise RuntimeError("usage broke after the workers started")
        with self.assertRaisesRegex(RuntimeError, "workers started"):
            within(30, lambda: run_staged(None, [Collect("a"), Collect("b")], Cache(),
                                          workers=2, usage=Broken()))
        self.assertFalse(any(t.name.startswith("reader:") for t in threading.enumerate()))
        self.assertEqual(cv2.getNumThreads(), before)
        # A second shard refused after the first froze its reader's array.
        held = Painting()
        with self.assertRaisesRegex(ValueError, "shardable"):
            run_staged(None, [held, Collect("a")], Cache(), workers=1,
                       shards={"cands": 2, "a": 2})
        self.assertTrue(held.canvas.flags.writeable)
        self.assertEqual(cv2.getNumThreads(), before)

    def test_a_raising_source_fails_the_run_and_stops_the_workers(self):
        class Broken(Cache):
            def samples(self, targets_ms, rois=None):
                yield from list(super().samples(targets_ms, rois))[:3]
                raise OSError("cache video ended")
        got = within(30, lambda: run_staged(None, [Collect("a", sleep=0.01)], Broken(),
                                            workers=1))
        self.assertEqual(got.status, "failed")
        self.assertIn("source", got.error)
        self.assertFalse(any(t.name.startswith("reader:") for t in threading.enumerate()))


class BoundTests(unittest.TestCase):
    def test_the_fifo_stays_bounded_and_the_dispatcher_waits(self):
        cache = Cache(n=60)

        class Slow(Collect):
            def feed(self, smp):
                time.sleep(0.003)
                super().feed(smp)
                cache.consumed += 1
        got = within(60, lambda: run_staged(None, [Slow("slow")], cache, workers=1, depth=3))
        self.assertEqual(got.status, "completed", got.error)
        self.assertLessEqual(got.max_queued["slow"], 3)
        self.assertGreater(got.wait_ns, 0)
        # Three queued, one in the worker, one in the dispatcher's hand.
        self.assertLessEqual(cache.ahead, 3 + 2)

    def test_the_default_depth_is_small(self):
        self.assertLessEqual(FIFO_DEPTH, 8)

    def test_round_trips_outpace_the_fastest_recorded_source(self):
        # The plan's fourth prediction: the transport is not the cost. The
        # fastest source in the baseline retrieved 144.2 frames a second.
        n = 1000
        start = time.perf_counter()
        got = within(60, lambda: run_staged(None, [Collect("a")], Cache(n=n, shape=(1, 1, 3)),
                                            workers=1))
        self.assertEqual(got.fed["a"], n)
        self.assertLess(time.perf_counter() - start, n / 144.2)


class OpenCvThreadTests(unittest.TestCase):
    def test_a_threaded_pass_runs_at_one_opencv_thread_and_restores_the_count(self):
        seen = []

        class Probe(Collect):
            def feed(self, smp):
                seen.append(cv2.getNumThreads())
                super().feed(smp)
        before = cv2.getNumThreads()
        got = run_staged(None, [Probe("p")], Cache(n=5), workers=2)
        self.assertEqual(set(seen), {1})
        self.assertEqual(got.cv_threads, {"pass": 1, "toggled": []})
        self.assertEqual(cv2.getNumThreads(), before)

    def test_a_threaded_pass_refuses_a_reader_declaring_another_count(self):
        r = Collect("a")
        r.cv_threads = 2
        with self.assertRaisesRegex(ValueError, "OpenCV"):
            run_staged(None, [r], Cache(n=5), workers=1)

    def test_inline_keeps_the_serial_toggle(self):
        r = Collect("a")
        r.cv_threads = 1
        got = run_staged(None, [r], Cache(n=5), workers=0)
        self.assertEqual(got.cv_threads["toggled"], ["a"])


class Capture:
    """`cv2.VideoCapture`'s front-to-back subset at 30 fps, counting its work."""

    def __init__(self, n=600, offset_ms=0.0):
        self.n, self.pos, self.grabs, self.retrieved = n, -1, 0, []
        self.offset_ms = offset_ms

    def isOpened(self):
        return True

    def grab(self):
        if self.pos + 1 >= self.n:
            return False
        self.pos += 1
        self.grabs += 1
        return True

    def get(self, prop):
        # frame 210 is observed at 7000.0 ms exactly, plus any offset
        return self.pos * 1000.0 / 30.0 + self.offset_ms

    def retrieve(self):
        self.retrieved.append(self.pos)
        return True, np.full((2, 2, 3), self.pos % 251, np.uint8)

    def release(self):
        pass


class PrefixTests(unittest.TestCase):
    """`scan --until`: only frames observed before the limit, on every path."""

    UNTIL = 7000.0          # the cache and the capture each hold a frame at it

    def paths(self, ctx):
        return (("serial", lambda rs, src: (run(ctx, rs) if src is None
                                            else run_cached(ctx, rs, src))),
                ("staged, workers 0", lambda rs, src: run_staged(ctx, rs, src, workers=0)),
                ("staged, workers 1", lambda rs, src: run_staged(ctx, rs, src, workers=1)))

    def assert_prefix_of(self, got, whole):
        for g, w in zip(got, whole):
            times = [t for _, t, _, _ in g.rows]
            self.assertTrue(times)
            self.assertLess(max(times), self.UNTIL)
            # Frame for frame the whole pass's rows before the limit.
            self.assertEqual([r[:3] for r in g.rows],
                             [r[:3] for r in w.rows if r[1] < self.UNTIL])

    def test_the_cache_stops_at_the_limit_and_still_never_thins(self):
        spans = [(1000.0, 6000.0), (6200.0, 9000.0)]

        def build():
            return [Collect("whole"), Collect("slow_rate", hz=0.5, spans=spans)]
        whole = build()
        run_cached(None, whole, Cache())
        for label, go in self.paths(None):
            with self.subTest(label):
                cache, readers = Cache(), build()
                go(readers, limit_to_prefix(readers, self.UNTIL, cache))
                self.assert_prefix_of(readers, whole)
                # At 0.5 Hz a decode would thin; the cache feeds every frame
                # inside the spans and before the limit.
                self.assertEqual([t for _, t, _, _ in readers[1].rows],
                                 [t for t in cache.t_ms.tolist() if t < self.UNTIL
                                  and any(a <= t <= b for a, b in spans)])
                # The cache read nothing at or past the limit.
                self.assertEqual(cache.produced, int((cache.t_ms < self.UNTIL).sum()))
                self.assertEqual(readers[0].frames_from, "cache-test, t < 7000 ms")
        self.assertEqual(spans, [(1000.0, 6000.0), (6200.0, 9000.0)])

    def test_a_video_decode_stops_at_the_limit(self):
        ctx = SimpleNamespace(media="x.mp4", fps=30.0)

        def build():
            return [Collect("whole"), Collect("late", hz=10.0, spans=[(5000.0, 20000.0)])]
        with patch("reticle.decode.open_capture", lambda path: Capture()):
            whole = build()
            run(ctx, whole)
        for label, go in self.paths(ctx):
            with self.subTest(label):
                cap = Capture()
                with patch("reticle.decode.open_capture", lambda path: cap):
                    readers = build()
                    self.assertIsNone(limit_to_prefix(readers, self.UNTIL))
                    go(readers, None)
                self.assert_prefix_of(readers, whole)
                # Frames 0-209 fall before the limit; `sample_multi` grabs
                # frame 210, sees 7000 ms and stops: no skip to the end.
                self.assertEqual(cap.grabs, 211)
                self.assertLess(max(cap.retrieved), 210)
                self.assertEqual(readers[0].frames_from, "video, t < 7000 ms")

    def test_spans_are_cut_as_new_lists(self):
        shared = [(0.0, 3000.0), (6000.0, 9000.0), (9500.0, 10000.0)]
        a, b = Collect("a", spans=shared), Collect("b", spans=shared)
        limit_to_prefix([a, b], self.UNTIL)
        self.assertEqual(shared, [(0.0, 3000.0), (6000.0, 9000.0), (9500.0, 10000.0)])
        # Cut at the float below the limit; a span past it is dropped.
        self.assertEqual(a.spans, [(0.0, 3000.0), (6000.0, math.nextafter(self.UNTIL, 0))])
        self.assertIsNot(a.spans, b.spans)
        whole = Collect("whole")
        limit_to_prefix([whole], self.UNTIL)
        self.assertEqual(whole.spans, [(-math.inf, math.nextafter(self.UNTIL, 0))])

    def test_the_cache_keeps_frames_before_zero(self):
        def early():
            cache = Cache()
            cache.t_ms = cache.t_ms - 250.0      # the first frame at -250 ms
            return cache
        whole = [Collect("whole")]
        run_cached(None, whole, early())
        self.assertLess(whole[0].rows[0][1], 0)
        for label, go in self.paths(None):
            with self.subTest(label):
                readers = [Collect("whole")]
                go(readers, limit_to_prefix(readers, self.UNTIL, early()))
                self.assert_prefix_of(readers, whole)

    def test_a_decode_keeps_a_first_frame_before_zero(self):
        # Frame 0 observed at -20 ms: a whole pass takes it and strides from
        # there, so dropping it would shift every later sample.
        ctx = SimpleNamespace(media="x.mp4", fps=30.0)
        with patch("reticle.decode.open_capture", lambda path: Capture(offset_ms=-20.0)):
            whole = [Collect("whole")]
            run(ctx, whole)
            self.assertLess(whole[0].rows[0][1], 0)
            for label, go in self.paths(ctx):
                with self.subTest(label):
                    readers = [Collect("whole")]
                    self.assertIsNone(limit_to_prefix(readers, self.UNTIL))
                    go(readers, None)
                    self.assert_prefix_of(readers, whole)


class UntilRefusalTests(unittest.TestCase):
    def test_until_needs_check_and_check_dir(self):
        from reticle.cli import cmd_scan
        for check, check_dir in ((False, None), (False, "d"), (True, None)):
            with self.subTest(check=check, check_dir=check_dir):
                with self.assertRaisesRegex(SystemExit, "--check and --check-dir"):
                    cmd_scan(SimpleNamespace(until=60.0, check=check, check_dir=check_dir))
        with self.assertRaisesRegex(SystemExit, "positive"):
            cmd_scan(SimpleNamespace(until=0.0, check=True, check_dir="d"))


class ScanCheckTests(unittest.TestCase):
    """`scan --check`: path b runs first, and only byte-equal files pass."""

    def check(self, write_b, pipeline="staged", cv_threads=None, threads=None):
        import tempfile
        from pathlib import Path

        import pyarrow as pa
        import pyarrow.parquet as pq

        from reticle.cli import _scan_check

        order = []

        def scan_once(out, pipeline="serial", workers=None, shards=None, cv_threads=None):
            label = out.root.name
            order.append(label)
            if threads is not None:
                threads[label] = (pipeline, cv_threads)
            table = pa.table({"t": [1.0, 2.0]})
            if label == "b":
                table = write_b(table)
            (out.root / "l1").mkdir(parents=True)
            pq.write_table(table, out.root / "l1" / "t.parquet")
            return SimpleNamespace(run_id=f"run-{label}")

        with tempfile.TemporaryDirectory() as d:
            args = SimpleNamespace(check_dir=str(Path(d) / "check"), pipeline=pipeline,
                                   workers=1 if pipeline == "staged" else None,
                                   cv_threads=cv_threads)
            with contextlib.redirect_stdout(io.StringIO()):
                code = _scan_check(scan_once, "s", args, {})
        return code, order

    def test_the_staged_path_runs_first(self):
        code, order = self.check(lambda t: t)
        self.assertEqual((code, order), (0, ["b", "a"]))

    def test_the_serial_path_takes_the_staged_paths_opencv_count(self):
        threads = {}
        self.check(lambda t: t, cv_threads=1, threads=threads)
        self.assertEqual(threads, {"b": ("staged", 1), "a": ("serial", 1)})

    def test_a_serial_check_at_a_count_compares_with_the_pool(self):
        # Asked for the serial pass at one thread, the check compares it with
        # the serial pass on OpenCV's own pool, not with itself.
        threads = {}
        self.check(lambda t: t, pipeline="serial", cv_threads=1, threads=threads)
        self.assertEqual(threads, {"b": ("serial", 1), "a": ("serial", None)})

    def test_metadata_alone_fails_the_check(self):
        code, _ = self.check(lambda t: t.replace_schema_metadata({b"m": b"1"}))
        self.assertEqual(code, 1)


class CompareTreesTests(unittest.TestCase):
    def test_equal_differing_and_missing_files(self):
        import tempfile
        from pathlib import Path

        import pyarrow as pa
        import pyarrow.parquet as pq

        with tempfile.TemporaryDirectory() as d:
            a, b = Path(d) / "a", Path(d) / "b"
            for root, meta, tail in ((a, b"1", "x"), (b, b"2", "y")):
                (root / "events").mkdir(parents=True)
                (root / "notes").mkdir()
                (root / "events" / "same.jsonl").write_text("{}\n", encoding="utf-8")
                (root / "events" / "moved.jsonl").write_text(f"{{}}\n{tail}\n",
                                                             encoding="utf-8")
                (root / "notes" / "usage.jsonl").write_text(tail, encoding="utf-8")
                table = pa.table({"t": [1.0, 2.0]}).replace_schema_metadata({b"m": meta})
                pq.write_table(table, root / "meta.parquet")
            (a / "only.json").write_text("{}", encoding="utf-8")
            got = {e["path"]: e for e in compare_trees(a, b)}
            self.assertEqual(got["events/same.jsonl"]["verdict"], "equal")
            self.assertEqual(got["events/moved.jsonl"]["detail"], "line 2 differs")
            self.assertEqual(got["meta.parquet"]["verdict"], "differs")
            self.assertFalse(got["meta.parquet"]["rows_differ"])
            self.assertEqual(got["only.json"]["verdict"], "only in a")
            self.assertNotIn("notes/usage.jsonl", got)


if __name__ == "__main__":
    unittest.main()
