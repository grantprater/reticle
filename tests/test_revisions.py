import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from reticle.revisions import current_revision, publish_revision


class RevisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.out = Path(self.temp.name) / "analysis" / "example"

    def tearDown(self):
        self.temp.cleanup()

    def publish(self, value):
        return publish_revision(
            self.out, artifact="example", producer_version="example-1.0.0",
            files={"rows.jsonl": json.dumps({"value": value}) + "\n"},
            manifest={"schema_version": 1, "value": value},
        )

    def test_revisions_are_immutable_and_identical_content_is_reused(self):
        first = self.publish(1)
        before = {p.name: p.read_bytes() for p in first.iterdir()}
        self.assertEqual(self.publish(1), first)
        self.assertEqual({p.name: p.read_bytes() for p in first.iterdir()}, before)
        second = self.publish(2)
        self.assertNotEqual(second, first)
        self.assertTrue(first.is_dir())
        self.assertEqual(current_revision(self.out), second)
        self.assertEqual(json.loads((self.out / "rows.jsonl").read_text())["value"], 2)

    def test_failed_publication_keeps_the_prior_revision_current(self):
        first = self.publish(1)
        from reticle import revisions
        real_replace = revisions._replace

        def fail_pointer(source, target):
            if target.name == "current.json":
                raise OSError("injected pointer failure")
            return real_replace(source, target)

        with patch("reticle.revisions._replace", side_effect=fail_pointer):
            with self.assertRaisesRegex(OSError, "pointer failure"):
                self.publish(2)
        self.assertEqual(current_revision(self.out), first)

    def test_corrupt_pointer_and_run_collision_refuse(self):
        run = self.publish(1)
        (run / "rows.jsonl").write_text("corrupt", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "collision"):
            self.publish(1)
        (self.out / "current.json").write_text('{"revision_id":"missing"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "missing run"):
            current_revision(self.out)


if __name__ == "__main__":
    unittest.main()
