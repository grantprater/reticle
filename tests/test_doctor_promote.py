"""`check_promote`: a measured prototype that never reached the pipeline.

The two older checks cannot see this state. `check_unwired` looks only at
modules already inside `reticle/`, and `check_orphan` exempts a prototype for
being NAMED in a document -- so writing a result up is what silences it. These
tests pin the inversion: leaving a prototype unwired now requires saying so.
"""
import json
import tempfile
import unittest
from pathlib import Path

from reticle import doctor


def _ledger(root: Path, rows: list[dict]) -> Path:
    notes = root / "notes"
    notes.mkdir(parents=True, exist_ok=True)
    with (notes / "predictions.jsonl").open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return root


class PromoteCheckTests(unittest.TestCase):
    def test_no_ledger_is_silent(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(doctor.check_promote(Path(d)), [])

    def test_a_named_prototype_that_nothing_uses_is_reported(self):
        stem = next(f.stem for f in (doctor.ROOT / "prototypes").glob("*.py"))
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"experiment": "e", "result": f"{stem}.py ran"}])
            found = doctor.check_promote(root)
        # Either it is reported, or `reticle/` genuinely uses it -- both are
        # correct answers, and the check must not invent a third.
        used = any(stem in f.read_text(encoding="utf-8", errors="replace")
                   for f in (doctor.ROOT / "reticle").glob("*.py"))
        self.assertEqual(bool(found), not used)
        if found:
            self.assertIn(stem, found[0][1])
            self.assertEqual(found[0][0], doctor.WARN)

    def test_wire_no_suppresses_it(self):
        stem = "minimap_occlusion"       # a measured NEGATIVE: correctly unwired
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"experiment": "e", "wire": "no",
                                      "wire_reason": "refuted; diagnostic only",
                                      "result": f"{stem}.py ran"}])
            self.assertEqual(doctor.check_promote(root), [])

    def test_a_later_decision_retires_an_earlier_mention(self):
        # The decision is about the PROTOTYPE, not about the row it sits on.
        # Skipping only the declining row left a 2026-09-03 mention reported
        # forever, and a finding that cannot be cleared is one people ignore.
        stem = "minimap_occlusion"
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [
                {"experiment": "old", "result": f"{stem}.py ran"},
                {"experiment": "triage", "wire": "no",
                 "wire_reason": "refuted; diagnostic only",
                 "subject": f"prototypes/{stem}.py"},
            ])
            self.assertEqual(
                [m for _s, m in doctor.check_promote(root) if stem in m], [])

    def test_pending_is_not_a_decline(self):
        stem = "minimap_occlusion"
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"wire": "pending",
                                      "subject": f"prototypes/{stem}.py"}])
            self.assertTrue(
                [m for _s, m in doctor.check_promote(root) if stem in m])

    def test_a_decline_does_not_retire_what_its_reason_mentions(self):
        # Declining `ability_scale` silently declined `ability_disc`, because
        # the reason said the two must ship together. A `subject` is the only
        # thing a decline speaks for.
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [
                {"wire": "no", "subject": "prototypes/ability_scale.py",
                 "wire_reason": "prerequisite of ability_disc; wire them together"},
                {"experiment": "old", "result": "ability_disc.py ran"},
            ])
            found = [m for _s, m in doctor.check_promote(root)]
            self.assertTrue([m for m in found if "ability_disc" in m])
            self.assertEqual([m for m in found if "ability_scale" in m], [])

    def test_the_checker_naming_a_prototype_is_not_using_it(self):
        # doctor.py names prototypes in its own prose and reads both trees by
        # design. Counting itself as a consumer would let it retire its own
        # findings by describing them.
        stem = "minimap_occlusion"
        self.assertIn(stem, (doctor.ROOT / "reticle" / "doctor.py")
                      .read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"result": f"{stem}.py ran"}])
            self.assertTrue(
                [m for _s, m in doctor.check_promote(root) if stem in m])

    def test_a_substring_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"result": "xminimap_occlusiony.py"}])
            self.assertEqual(
                [m for _s, m in doctor.check_promote(root)
                 if "minimap_occlusion" in m], [])


if __name__ == "__main__":
    unittest.main()
