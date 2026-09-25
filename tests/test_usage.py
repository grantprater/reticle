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


if __name__ == "__main__":
    unittest.main()
