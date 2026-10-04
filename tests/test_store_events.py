"""A truncated or partly written events file never reads as current.

`Store.events_version` answers `scan` and `plan`'s staleness question from
the file's first row; a file cut short after that row used to read as
current, so neither would rewrite it.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reticle.plan import stale
from reticle.store import Store
from reticle.version import PING_VERSION

SID = "s0"


def _rows(n=5):
    return [{"t_ms": 500.0 * i, "kind": "ping", "ping_version": PING_VERSION,
             "note": "x" * 40} for i in range(n)]


class TruncatedEventsTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = Store(self._dir.name)
        self.path = self.store.write_events("ping", SID, _rows())

    def tearDown(self):
        self._dir.cleanup()

    def cut(self, n_bytes: int):
        data = self.path.read_bytes()
        self.path.write_bytes(data[:n_bytes])

    def test_a_whole_file_reads_as_current(self):
        self.assertEqual(self.store.events_version("ping", SID), PING_VERSION)

    def test_a_file_cut_mid_row_is_not_current(self):
        data = self.path.read_bytes()
        self.cut(len(data) - 10)
        got = self.store.events_version("ping", SID)
        self.assertNotEqual(got, PING_VERSION)
        self.assertIsNotNone(got)          # present but incomplete, not absent
        self.assertTrue(got.startswith("incomplete"))

    def test_a_file_missing_its_last_newline_is_not_current(self):
        data = self.path.read_bytes()
        self.cut(len(data) - 1)
        self.assertNotEqual(self.store.events_version("ping", SID), PING_VERSION)

    def test_a_file_cut_inside_its_first_row_is_not_current(self):
        self.cut(12)
        self.assertTrue(self.store.events_version("ping", SID).startswith("incomplete"))

    def test_a_last_row_at_another_stamp_is_not_current(self):
        rows = _rows()
        rows[-1]["ping_version"] = "ping-0.0.1"
        with open(self.path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        self.assertNotEqual(self.store.events_version("ping", SID), PING_VERSION)

    def test_a_last_row_longer_than_one_read_is_found(self):
        rows = _rows()
        rows[-1]["note"] = "y" * 200_000
        self.store.write_events("ping", SID, rows)
        self.assertEqual(self.store.events_version("ping", SID), PING_VERSION)

    def test_a_writer_that_dies_leaves_the_old_file_whole(self):
        before = self.path.read_bytes()

        def boom(*a, **k):
            raise RuntimeError("killed mid-write")
        rows = _rows(8)
        rows[3] = {"unserialisable": object()}
        with self.assertRaises(TypeError):
            self.store.write_events("ping", SID, rows)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual([p.name for p in self.path.parent.iterdir()], [self.path.name])
        with patch("reticle.store.os.replace", boom):
            with self.assertRaises(RuntimeError):
                self.store.write_events("ping", SID, _rows(8))
        self.assertEqual(self.path.read_bytes(), before)

    def test_plan_calls_a_truncated_stream_stale(self):
        (self.store.root / "manifests").mkdir()
        self.store.manifest_path(SID).write_text(
            json.dumps({"session_id": SID, "ingested_at": "2026-09-28T00:00:00"}),
            encoding="utf-8")
        self.assertNotIn("ping", [d["stream"] for d in stale(self.store, [SID])[SID]["decode"]])
        data = self.path.read_bytes()
        self.cut(len(data) - 10)
        decode = {d["stream"]: d for d in stale(self.store, [SID])[SID]["decode"]}
        self.assertIn("ping", decode)
        self.assertTrue(decode["ping"]["stored"].startswith("incomplete"))


def _ping_events(n=3):
    """The rows `PingReader.events` writes: formal entity events, stamped
    `producer_version`, with no `ping_version` key."""
    from reticle.ping import PingReader
    pr = object.__new__(PingReader)
    pr.hz = 10.0
    pr.hits = [("standard", 1.0 + 10 * i, 8.0 + 10 * i, 100, 120, 79, 70) for i in range(n)]
    return pr.events(SID)


class FormalEventStampTests(unittest.TestCase):
    """`ping` writes formal entity events; their stamp is `producer_version`.
    Reading only `ping_version` made a fresh ping stream read as absent, so
    `plan` listed it absent and `scan` reread it on every pass (b3b9defb6fd7,
    2026-10-04)."""

    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = Store(self._dir.name)

    def tearDown(self):
        self._dir.cleanup()

    def test_a_formal_ping_stream_reads_at_its_producer_version(self):
        rows = _ping_events()
        self.assertNotIn("ping_version", rows[0])
        self.store.write_events("ping", SID, rows)
        self.assertEqual(self.store.events_version("ping", SID), PING_VERSION)

    def test_a_formal_last_row_at_another_stamp_is_not_current(self):
        rows = _ping_events()
        rows[-1]["producer_version"] = "ping-0.0.1"
        self.store.write_events("ping", SID, rows)
        self.assertTrue(self.store.events_version("ping", SID).startswith("incomplete"))

    def test_another_channels_producer_version_is_not_this_streams_stamp(self):
        rows = _ping_events()
        for r in rows:
            r["source_channel"] = "minimap"
        self.store.write_events("ping", SID, rows)
        self.assertIsNone(self.store.events_version("ping", SID))

    def test_plan_compares_the_formal_stamp_and_lists_the_stream_current(self):
        from reticle.plan import compared_paths
        self.assertIn("producer_version", compared_paths()["ping"])
        (self.store.root / "manifests").mkdir()
        self.store.manifest_path(SID).write_text(
            json.dumps({"session_id": SID, "ingested_at": "2026-09-28T00:00:00"}),
            encoding="utf-8")
        self.store.write_events("ping", SID, _ping_events())
        got = stale(self.store, [SID])[SID]
        self.assertNotIn("ping", got["absent"])
        self.assertNotIn("ping", [d["stream"] for d in got["decode"]])


if __name__ == "__main__":
    unittest.main()
