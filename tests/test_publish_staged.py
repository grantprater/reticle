"""A scan publishes a whole run or nothing, and names the run that wrote it.

`scan` wrote each stream into the store as it came; a minimap pass with no
rows exited after the killfeed streams were already written, leaving a
half-published run with nothing to say which run wrote what.
"""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from reticle.cli import _publish_staged
from reticle.store import Store

SID = "s0"


class _Usage:
    def __init__(self, run_id="r1"):
        self.run_id, self.status, self.error, self.written = run_id, "completed", None, []

    def write(self, root):
        self.written.append((Path(root), self.status, self.error))


def _events(tag):
    return [{"t_ms": 0.0, "killfeed_portrait_version": "v", "tag": tag}]


class PublishStagedTests(unittest.TestCase):
    def setUp(self):
        self._dir = tempfile.TemporaryDirectory()
        self.store = Store(self._dir.name)
        self.old = self.store.write_events("killfeed_portrait", SID, _events("old"))
        self.old_bytes = self.old.read_bytes()

    def tearDown(self):
        self._dir.cleanup()

    def files(self):
        return sorted(p.relative_to(self.store.root).as_posix()
                      for p in self.store.root.rglob("*") if p.is_file())

    def test_a_zero_rows_exit_after_another_write_publishes_nothing(self):
        def publish(out):
            out.write_events("killfeed_portrait", SID, _events("new"))
            out.write_events("killfeed_name", SID, _events("new"))
            raise SystemExit("decoded zero frames inside active spans -- is segmentation right?")
        usage = _Usage()
        before = self.files()
        with self.assertRaises(SystemExit):
            _publish_staged(self.store, publish, usage, SID)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual(self.files(), before)
        self.assertFalse((self.store.root / "staging").exists())
        # The failure is on record: a usage row that says so.
        self.assertEqual(len(usage.written), 1)
        root, status, error = usage.written[0]
        self.assertEqual((root, status), (self.store.root, "failed"))
        self.assertIn("zero frames", error)

    def test_a_whole_run_lands_with_a_run_record(self):
        def publish(out):
            out.write_events("killfeed_portrait", SID, _events("new"))
            out.write_events("killfeed_name", SID, _events("new"))
        usage = _Usage("r2")
        record = _publish_staged(self.store, publish, usage, SID)
        self.assertEqual(self.store.read_events("killfeed_portrait", SID)[0]["tag"], "new")
        self.assertFalse((self.store.root / "staging").exists())
        runs = [json.loads(l) for l in
                (self.store.root / "notes" / "runs.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(runs, [record])
        self.assertEqual((record["run_id"], record["session_id"], record["status"]),
                         ("r2", SID, "committed"))
        by_path = {f["path"]: f for f in record["files"]}
        self.assertEqual(sorted(by_path), ["events/killfeed_name/s0.jsonl",
                                           "events/killfeed_portrait/s0.jsonl"])
        for rel, f in by_path.items():
            data = (self.store.root / rel).read_bytes()
            self.assertEqual(f["sha256"], hashlib.sha256(data).hexdigest())
            self.assertEqual(f["bytes"], len(data))
        # Success leaves the usage record to the caller.
        self.assertEqual(usage.written, [])

    def test_an_immutable_revision_that_differs_refuses_the_whole_run(self):
        rel = Path("decisions") / "ally_icon" / SID / "rev__rule.json"
        (self.store.root / rel).parent.mkdir(parents=True)
        (self.store.root / rel).write_text('{"rows": [1]}', encoding="utf-8")

        def publish(out):
            out.write_events("killfeed_portrait", SID, _events("new"))
            (out.root / rel).parent.mkdir(parents=True)
            (out.root / rel).write_text('{"rows": [2]}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "immutable"):
            _publish_staged(self.store, publish, _Usage(), SID)
        self.assertEqual(self.old.read_bytes(), self.old_bytes)
        self.assertEqual((self.store.root / rel).read_text(encoding="utf-8"), '{"rows": [1]}')
        self.assertFalse((self.store.root / "staging").exists())

    def test_an_equal_immutable_revision_is_kept(self):
        rel = Path("candidates") / "ally_icon" / SID / "rev.json"
        (self.store.root / rel).parent.mkdir(parents=True)
        (self.store.root / rel).write_text("{}", encoding="utf-8")

        def publish(out):
            (out.root / rel).parent.mkdir(parents=True)
            (out.root / rel).write_text("{}", encoding="utf-8")
        record = _publish_staged(self.store, publish, _Usage(), SID)
        self.assertEqual(record["kept"], [rel.as_posix()])
        self.assertEqual(record["files"], [])


if __name__ == "__main__":
    unittest.main()
