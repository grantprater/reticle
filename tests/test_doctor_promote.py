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

    def test_a_substring_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as d:
            root = _ledger(Path(d), [{"result": "xminimap_occlusiony.py"}])
            self.assertEqual(
                [m for _s, m in doctor.check_promote(root)
                 if "minimap_occlusion" in m], [])


if __name__ == "__main__":
    unittest.main()
