"""Operational scan usage stays separate from stored observations."""

import json
import tempfile
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
        usage = ScanUsage(self.manifest, "profile", [Reader()], "cache:cache-test")
        usage.cv_threads = {"pass": 1}
        with tempfile.TemporaryDirectory() as d:
            row = usage.write_metric(Path(d))
        self.assertEqual((row["tool"], row["part"], row["session"]),
                         ("scan_usage", "probe/cache/serial/cv1", "s"))


if __name__ == "__main__":
    unittest.main()
