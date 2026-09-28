import tempfile
import unittest
from pathlib import Path

from reticle.doctor import backlog_open_blocks, backlog_open_items, check_handoff

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

#: One open item that carries its contract lines inside its paragraph.
ITEM = ("**t.** Do t.\n"
        "Acceptance: `python -m reticle t` passes.\n"
        "Evidence: the player reviews t against source.\n")


class HandoffTests(unittest.TestCase):
    def fixture(self, root):
        (root / "NOTES.md").write_text("# Notes\n\n## Picking up\n\nTask t.\n", encoding="utf-8")
        (root / "BACKLOG.md").write_text("# Queue\n\n## Agreed order\n\n" + ITEM,
                                         encoding="utf-8")

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

    def test_no_tasks_json_draws_no_contract_finding(self):
        # The contracts moved onto the items, so HANDOFF reads no
        # docs/tasks.json: neither its absence nor a broken leftover counts.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            self.assertEqual(check_handoff(root), [])
            (root / "docs").mkdir()
            (root / "docs/tasks.json").write_text("{", encoding="utf-8")
            self.assertEqual(check_handoff(root), [])

    def test_an_item_lacking_evidence_is_counted_and_named(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "BACKLOG.md").write_text(
                "# Queue\n\n## Agreed order\n\n" + ITEM + "\n"
                "**Half a contract (next, 2026-09-27).** Do u.\n"
                "Acceptance: `python -m reticle u` passes.\n", encoding="utf-8")
            self.assertEqual(check_handoff(root), [(
                "WARN", 'BACKLOG.md: 1 of 2 open items carry no Acceptance: or Evidence: '
                        'line -- "Half a contract (next, 2026-09-27)."; write both on each '
                        'item, and on every new one')])

    def test_contract_lines_count_only_inside_the_items_paragraph(self):
        text = ("## Agreed order\n\n**a.** x\n\nAcceptance: `y`\nEvidence: z.\n\n"
                "1. **b.** x\nAcceptance: `y`\n2. **c.** x\nEvidence: z.\n")
        self.assertEqual(backlog_open_blocks(text), [
            ["**a.** x"], ["1. **b.** x", "Acceptance: `y`"], ["2. **c.** x", "Evidence: z."]])

    def test_items_without_contracts_draw_one_finding(self):
        # Twelve bare items must not flood doctor: one finding names three.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            (root / "BACKLOG.md").write_text(AGREED, encoding="utf-8")
            contract = [message for _, message in check_handoff(root)
                        if "Acceptance:" in message]
            self.assertEqual(contract, [
                'BACKLOG.md: 4 of 4 open items carry no Acceptance: or Evidence: line -- '
                '"Minimap identity.", "Priority: the adjudicator.", "Roster defect:"; '
                'write both on each item, and on every new one'])

    def test_backlog_is_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.fixture(root)
            done = "".join(f"- **`t{i}`:** done.\n" for i in range(6))
            (root / "BACKLOG.md").write_text(
                "# Queue\n\n## Agreed order\n\n" + ITEM + "\n## Completed\n\n" + done
                + "\n## Deferred\n\n" + "word " * 1600, encoding="utf-8")
            findings = [message for _, message in check_handoff(root)]
            self.assertTrue(any("6 completed" in message for message in findings))
            self.assertTrue(any("limits are 150 and 1500" in message for message in findings))
