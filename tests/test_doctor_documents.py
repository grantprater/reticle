"""`doctor.check_documents`: the register, what reaches each document, and budgets."""
import shutil
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import doctor, documents

REGISTER = """
[[document]]
path = "AGENTS.md"
kind = "rules"
status = "live"
since = "2026-09-27"
eager = true
budget_words = 50

[[document]]
path = "docs/WORKING_MAP.md"
kind = "routing"
status = "live"
since = "2026-09-27"
eager = true
budget_words = 50

[[document]]
path = "docs/DESIGN.md"
kind = "design"
status = "proposed"
since = "2026-09-27"
waits_for = "A task that selects it."

[[document]]
path = "docs/FINDING.md"
kind = "findings"
status = "recorded"
since = "2026-09-27"
"""

FILES = {
    "AGENTS.md": "Read [the map](docs/WORKING_MAP.md).\n",
    "docs/WORKING_MAP.md": "Route: [design](DESIGN.md).\n",
    "docs/DESIGN.md": "A design.\n",
    "docs/FINDING.md": "A finding.\n",
    "docs/archive/OLD-2026-09-01.md": "History links [design](../DESIGN.md).\n",
    "reticle/m.py": '"""Measured in FINDING.md, a bare name."""\n',
    "reticle/cli.py": 'sub.add_parser("run", help="a command")\n',
}


class DocumentsCheckTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.write("documents.toml", REGISTER)
        for rel, text in FILES.items():
            self.write(rel, text)

    def write(self, rel, text):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")

    def register(self, old, new):
        path = self.root / "documents.toml"
        text = path.read_text(encoding="utf-8")
        self.assertIn(old, text)
        path.write_text(text.replace(old, new), encoding="utf-8")

    def found(self, level=None):
        return [message for sev, message in doctor.check_documents(self.root)
                if level is None or sev == level]

    def test_a_clean_register_has_no_findings(self):
        self.assertEqual(doctor.check_documents(self.root), [])

    def test_an_unregistered_document_is_a_warning(self):
        self.write("docs/NEW.md", "Written today.\n")
        self.assertEqual(self.found(doctor.WARN),
                         ["docs/NEW.md is in no documents.toml entry -- add a "
                          "[[document]] entry with its kind, status and since"])

    def test_a_registered_path_that_does_not_exist_is_an_error(self):
        (self.root / "docs/FINDING.md").unlink()
        self.assertEqual(self.found(doctor.ERROR),
                         ["documents.toml [docs/FINDING.md] names a file that does "
                          "not exist -- a move or a deletion left the entry behind"])

    def test_an_unreached_document_is_a_warning_and_history_revives_nothing(self):
        self.write("docs/WORKING_MAP.md", "Route: nothing yet.\n")
        self.assertEqual(self.found(doctor.WARN),
                         ["docs/DESIGN.md is reached by nothing -- link it from the "
                          "map or the guide, supersede it, or archive it"])

    def test_a_docstring_mention_reaches_a_document(self):
        self.assertEqual(self.found(), [])
        self.write("reticle/m.py", '"""Names no document."""\n')
        self.assertEqual(self.found(doctor.WARN),
                         ["docs/FINDING.md is reached by nothing -- link it from the "
                          "map or the guide, supersede it, or archive it"])

    def test_superseded_without_a_successor_is_a_warning(self):
        self.register('status = "proposed"', 'status = "superseded"')
        self.assertEqual(self.found(doctor.WARN),
                         ["docs/DESIGN.md is superseded and names no superseded_by "
                          "-- name its successor"])
        self.register('waits_for = "A task that selects it."',
                      'superseded_by = "docs/FINDING.md"')
        self.assertEqual(self.found(), [])

    def test_implemented_by_targets_must_resolve(self):
        self.register('status = "proposed"\nsince = "2026-09-27"\n'
                      'waits_for = "A task that selects it."',
                      'status = "partial"\nsince = "2026-09-27"\n'
                      'implemented_by = ["cmd:run", "reticle/m.py", "cmd:nope", "owns:x"]\n'
                      'remains = "The rest."')
        self.assertEqual(self.found(doctor.WARN), [
            "docs/DESIGN.md is implemented by cmd:nope, which is not a reticle subcommand",
            "docs/DESIGN.md is implemented by owns:x, which is not an ownership.toml entry",
        ])

    def test_an_eager_document_over_budget_is_a_warning(self):
        self.register("budget_words = 50", "budget_words = 1")
        self.assertEqual(self.found(doctor.WARN), [
            "AGENTS.md has 3 words; its budget is 1 -- move detail to its owner and "
            "history to docs/archive/",
            "docs/WORKING_MAP.md has 2 words; its budget is 1 -- move detail to its "
            "owner and history to docs/archive/",
            "eager documents have 5 words; their budgets sum to 2",
        ])

    def test_a_schema_fault_is_an_error_that_names_the_entry(self):
        self.register('status = "proposed"', 'status = "live"')
        self.assertEqual(self.found(), [
            "documents.toml [docs/DESIGN.md] is a design with status `live`; a design "
            "may be implemented, partial, proposed, superseded"])
        with self.assertRaises(documents.RegisterError):
            documents.load(self.root)

    def test_the_archive_is_never_registered(self):
        self.register('path = "docs/FINDING.md"', 'path = "docs/archive/OLD-2026-09-01.md"')
        self.assertTrue(any("registers dated history" in m for m in self.found(doctor.ERROR)))


if __name__ == "__main__":
    unittest.main()
