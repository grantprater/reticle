import json
import tempfile
import unittest
from pathlib import Path

from reticle.doctor import check_handoff


class HandoffTests(unittest.TestCase):
    def fixture(self, root):
        (root / "docs").mkdir()
        (root / "NOTES.md").write_text("# Notes\n\n## Picking up\n\nTask t.\n", encoding="utf-8")
        (root / "BACKLOG.md").write_text("# Queue\n\n## Active: t\n", encoding="utf-8")
        (root / "read.md").write_text("# Read\n", encoding="utf-8")
        (root / "docs/tasks.json").write_text(json.dumps({"tasks": [
            {"id": "t", "files": ["x.txt"], "reads": ["read.md#Read"]}
        ]}), encoding="utf-8")
        (root / "x.txt").write_text("x", encoding="utf-8")

    def test_compliant_handoff(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(check_handoff(root), [])

    def test_duplicate_oversize_and_bad_active_id(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "NOTES.md").write_text("## Picking up\n" * 101, encoding="utf-8")
            (root / "BACKLOG.md").write_text("## Active: missing\n" * 4, encoding="utf-8")
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("101 Picking up" in message for message in findings))
            self.assertTrue(any("101 lines" in message for message in findings))
            self.assertTrue(any("4 active" in message for message in findings))
            self.assertTrue(any("no contract" in message for message in findings))

    def test_backlog_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            done = "".join(f"- **`t{i}`:** done.\n" for i in range(6))
            (root / "BACKLOG.md").write_text(
                "# Queue\n\n## Active: t\n\n## Completed\n\n" + done
                + "\n## Deferred\n\n" + "word " * 1600, encoding="utf-8")
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("6 completed" in message for message in findings))
            self.assertTrue(any("limits are 150 and 1500" in message for message in findings))

    def test_missing_contract_read(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "read.md").unlink()
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("missing read" in message for message in findings))

    def test_missing_active_owning_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "x.txt").unlink()
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("missing owning file" in message for message in findings))
