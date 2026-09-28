import json
import tempfile
import unittest
from pathlib import Path

from reticle.doctor import backlog_open_items, check_handoff

#: The queue's real shape: a numbered item, bold paragraphs, and prose that
#: is not an item. Four open items.
AGREED = (
    "# Queue\n\n## Agreed order (2026-09-23)\n\n"
    "Steps 1 to 5 are done ([archive](docs/archive/x.md)).\n\n"
    "6. **Minimap identity.** First slice built.\n\n"
    "**Priority: the adjudicator.** Ideate and\n"
    "**experiment** on it; a wrapped bold line is not an item.\n\n"
    "**Roster defect:** reads 1 on a wiped side.\n\n"
    "**Geometry stamp:** normalise at the next rebuild.\n\n"
    "## Completed\n\n- **`t0`:** done.\n\n"
    "## Deferred\n\n**Killfeed HUD work.** Later.\n")


class HandoffTests(unittest.TestCase):
    def fixture(self, root):
        (root / "docs").mkdir()
        (root / "NOTES.md").write_text("# Notes\n\n## Picking up\n\nTask t.\n", encoding="utf-8")
        (root / "BACKLOG.md").write_text("# Queue\n\n## Agreed order\n\n**t.** Do t.\n",
                                         encoding="utf-8")
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

    def test_duplicate_oversize_and_too_many_open_items(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "NOTES.md").write_text("## Picking up\n" * 101, encoding="utf-8")
            (root / "BACKLOG.md").write_text(AGREED, encoding="utf-8")
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("101 Picking up" in message for message in findings))
            self.assertTrue(any("101 lines" in message for message in findings))
            self.assertIn("BACKLOG.md has 4 open items under Agreed order; limit is three",
                          findings)

    def test_agreed_order_counts_its_items_and_nothing_else(self):
        items = backlog_open_items(AGREED)
        self.assertEqual([line.split("**")[1] for line in items],
                         ["Minimap identity.", "Priority: the adjudicator.",
                          "Roster defect:", "Geometry stamp:"])

    def test_numbered_items_count_without_blank_lines(self):
        text = "## Agreed order\n\n1. **a.** x\n2. **b.** y\n3. **c.** z\n"
        self.assertEqual(len(backlog_open_items(text)), 3)

    def test_a_missing_agreed_order_is_reported_not_counted_as_zero(self):
        # The check keyed on `## Active:` for weeks after BACKLOG dropped it
        # and passed on nothing. A vanished section must say so.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "BACKLOG.md").write_text("# Queue\n\n## Active: t\n", encoding="utf-8")
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("no `## Agreed order` heading" in message
                                for message in findings))

    def test_absent_tasks_json_is_silent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "docs/tasks.json").unlink()
            self.assertEqual(check_handoff(root), [])

    def test_backlog_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            done = "".join(f"- **`t{i}`:** done.\n" for i in range(6))
            (root / "BACKLOG.md").write_text(
                "# Queue\n\n## Agreed order\n\n**t.** Do t.\n\n## Completed\n\n" + done
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
