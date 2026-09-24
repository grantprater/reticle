"""The domain registry: schema, citations, and the restatement signal."""
import tempfile
import unittest
from pathlib import Path

from reticle import domain


FACT = """
[vision-gate]
claim = "Own-team icons are always drawn."
kind = "rule"
known = "player"
since = "2026-09-10"
phrases = ["always drawn"]
"""


class RegistryTree:
    """A throwaway repo: a domain/ file plus one scanned tree."""

    def __init__(self, stack, toml=FACT, files=None):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "domain").mkdir()
        (self.root / "domain" / "minimap.toml").write_text(toml, encoding="utf-8")
        (self.root / "docs").mkdir()
        for name, text in (files or {}).items():
            (self.root / name).write_text(text, encoding="utf-8")

    def facts(self):
        return domain.load(self.root / "domain")

    def validate(self):
        return domain.validate(self.facts(), self.root)

    def levels(self):
        return [level for level, _message in self.validate()]


class LoadTests(unittest.TestCase):
    def test_a_fact_is_keyed_by_file_and_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "minimap.toml").write_text(FACT, encoding="utf-8")
            facts = domain.load(directory)
        self.assertEqual(list(facts), ["minimap/vision-gate"])
        fact = facts["minimap/vision-gate"]
        self.assertEqual(fact.cite, "[domain:minimap/vision-gate]")
        self.assertEqual(fact.phrases, ("always drawn",))

    def test_a_missing_directory_is_empty_rather_than_an_error(self):
        self.assertEqual(domain.load(Path("no-such-directory")), {})

    def test_subject_and_given_are_loaded_and_filtered(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            toml_text = (
                '[smoke]\nclaim = "x"\nkind = "rule"\nknown = "player"\nsince = "2026-01-01"\n'
                'subject = "omen:dark cover"\ngiven = "alive"\n'
            )
            (directory / "abilities.toml").write_text(toml_text, encoding="utf-8")
            facts = domain.load(directory)
        self.assertIn("abilities/smoke", facts)
        fact = facts["abilities/smoke"]
        self.assertEqual(fact.subject, "omen:dark cover")
        self.assertEqual(fact.given, "alive")
        filtered = domain.by_subject(facts, "omen:dark cover")
        self.assertEqual(list(filtered), ["abilities/smoke"])
        self.assertEqual(domain.by_subject(facts, "cypher:trapwire"), {})


class SchemaTests(unittest.TestCase):
    def _errors(self, toml):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            (directory / "minimap.toml").write_text(toml, encoding="utf-8")
            facts = domain.load(directory)
            scan = Path(tmp) / "scan"
            scan.mkdir()
            return [m for level, m in domain.validate(facts, scan)
                    if level == "ERROR"]

    def test_a_missing_required_key_is_an_error(self):
        errors = self._errors('[a]\nclaim = "x"\nkind = "rule"\n'
                              'known = "player"\n')
        self.assertTrue(any("missing required key" in m and "since" in m
                            for m in errors))

    def test_an_unknown_key_is_an_error_so_a_typo_cannot_hide(self):
        errors = self._errors('[a]\nclaim = "x"\nkind = "rule"\n'
                              'known = "player"\nsince = "2026-01-01"\n'
                              'phrase = "typo"\n')
        self.assertTrue(any("unknown key" in m and "phrase" in m
                            for m in errors))

    def test_an_unregistered_kind_or_provenance_is_an_error(self):
        errors = self._errors('[a]\nclaim = "x"\nkind = "vibe"\n'
                              'known = "hunch"\nsince = "2026-01-01"\n')
        self.assertTrue(any("kind 'vibe'" in m for m in errors))
        self.assertTrue(any("known 'hunch'" in m for m in errors))

    def test_a_relative_date_is_an_error(self):
        errors = self._errors('[a]\nclaim = "x"\nkind = "rule"\n'
                              'known = "player"\nsince = "yesterday"\n')
        self.assertTrue(any("absolute YYYY-MM-DD" in m for m in errors))

    def test_a_dangling_see_reference_is_an_error(self):
        errors = self._errors('[a]\nclaim = "x"\nkind = "rule"\n'
                              'known = "player"\nsince = "2026-01-01"\n'
                              'see = ["minimap/nope"]\n')
        self.assertTrue(any("sees 'minimap/nope'" in m for m in errors))


class CitationTests(unittest.TestCase):
    def test_a_citation_resolves_to_the_file_that_makes_it(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(stack, files={
                "docs/plan.md": "read [domain:minimap/vision-gate] first"})
            found = domain.citations(tree.root)
        self.assertEqual(found, {"minimap/vision-gate": ["docs/plan.md"]})

    def test_a_citation_to_no_fact_is_an_error(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(stack, files={
                "docs/plan.md": "see [domain:minimap/ghost]"})
            errors = [m for level, m in tree.validate() if level == "ERROR"]
        self.assertTrue(any("minimap/ghost" in m and "no such fact" in m
                            for m in errors))

    def test_a_fact_nothing_cites_is_reported_but_does_not_block(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(stack)
            found = tree.validate()
        self.assertEqual({level for level, _m in found}, {"WARN"})
        self.assertTrue(any("nothing cites" in m for _level, m in found))


class RestatementTests(unittest.TestCase):
    def _restated(self, files):
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(stack, files=files)
            return domain.restatements(tree.facts(), tree.root)

    def test_prose_carrying_a_phrase_without_citing_is_reported(self):
        got = self._restated({"docs/plan.md": "ally icons are always drawn"})
        self.assertEqual(got, {"minimap/vision-gate": ["docs/plan.md"]})

    def test_a_file_that_cites_the_fact_may_also_state_it(self):
        got = self._restated({
            "docs/plan.md": "always drawn [domain:minimap/vision-gate]"})
        self.assertEqual(got, {})

    def test_the_bounded_working_documents_are_checked(self):
        # NOTES.md and BACKLOG.md are rewritten in place, not logs, so a
        # restatement in them drifts like anywhere else; history is archived.
        self.assertNotIn("NOTES.md", domain.HISTORY)
        got = self._restated({"NOTES.md": "ally icons are always drawn",
                              "BACKLOG.md": "always drawn, we found"})
        self.assertEqual(sorted(got["minimap/vision-gate"]), ["BACKLOG.md", "NOTES.md"])

    def test_archived_records_are_history(self):
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(stack)
            archive = tree.root / "docs" / "archive"
            archive.mkdir(parents=True)
            (archive / "old-notes.md").write_text("ally icons are always drawn", encoding="utf-8")
            self.assertEqual(domain.restatements(tree.facts(), tree.root), {})

    def test_a_fact_with_no_phrases_claims_no_prose(self):
        got = self._restated({"docs/plan.md": "icons are always drawn"})
        self.assertTrue(got)
        import contextlib
        with contextlib.ExitStack() as stack:
            tree = RegistryTree(
                stack,
                toml='[vision-gate]\nclaim = "x"\nkind = "rule"\n'
                     'known = "player"\nsince = "2026-01-01"\n',
                files={"docs/plan.md": "icons are always drawn"})
            self.assertEqual(domain.restatements(tree.facts(), tree.root), {})


class RepositoryRegistryTests(unittest.TestCase):
    """The real registry, which must stay valid on every run."""

    def test_the_shipped_registry_has_no_errors(self):
        problems = domain.validate(domain.load())
        errors = [m for level, m in problems if level == "ERROR"]
        self.assertEqual(errors, [])

    def test_every_shipped_fact_carries_provenance_and_a_date(self):
        facts = domain.load()
        self.assertTrue(facts, "the registry is the one place domain facts go")
        for key, fact in facts.items():
            self.assertIn(fact.known, domain.KNOWN, key)
            self.assertIn(fact.kind, domain.KINDS, key)
            self.assertTrue(fact.claim, key)

    def test_the_registry_module_does_not_count_as_a_consumer(self):
        self.assertIn("reticle/domain.py", domain.EXAMPLE_ONLY)
        cited = domain.citations()
        for paths in cited.values():
            self.assertNotIn("reticle/domain.py", paths)


if __name__ == "__main__":
    unittest.main()
