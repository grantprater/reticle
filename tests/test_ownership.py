"""The declared ownership of each question, and the faults its checks exist for."""
import contextlib
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import ownership


DECLARATION = """
[[entry]]
id = "thing-position"
question = "Where is the thing?"
owner = "reader"
role = ["detect"]
status = "shipped"
produces = ["find_thing"]
not_for = "Which thing it is."

[infrastructure]
modules = ["cli"]
"""

READER = '''
"""A reader.

Owns [owns:thing-position].
"""


def find_thing():
    return 1
'''


class Tree:
    """A throwaway repo: ownership.toml plus a reticle/ and a prototypes/."""

    def __init__(self, stack, modules, declaration=DECLARATION, prototypes=(),
                 docs=None):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "ownership.toml").write_text(declaration, encoding="utf-8")
        (self.root / "reticle").mkdir()
        (self.root / "prototypes").mkdir()
        for name in prototypes:
            (self.root / "prototypes" / f"{name}.py").write_text("", encoding="utf-8")
        for name, body in (docs or {}).items():
            (self.root / name).write_text(textwrap.dedent(body), encoding="utf-8")
        for name, body in modules.items():
            path = self.root / "reticle" / f"{name.replace('.', '/')}.py"
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.parent != self.root / "reticle":
                (path.parent / "__init__.py").write_text("", encoding="utf-8")
            path.write_text(textwrap.dedent(body), encoding="utf-8")

    def verify(self):
        data = ownership.load(self.root / "ownership.toml")
        return ownership.verify(data, self.root)

    def messages(self, level=None):
        return [m for lv, m in self.verify() if level is None or lv == level]


class ReferenceTests(unittest.TestCase):
    def test_a_complete_declaration_passes(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""})
            self.assertEqual(tree.verify(), [])

    def test_a_produced_name_that_is_gone_is_an_error(self):
        """The half that makes an entry point at code rather than at a hope."""
        gone = READER.replace("def find_thing", "def find_something_else")
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": gone, "cli": ""})
            self.assertTrue(any("produces `find_thing`" in m
                                for m in tree.messages("ERROR")))

    def test_an_owner_that_is_not_a_module_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"cli": ""})
            self.assertTrue(any("names owner `reader`" in m
                                for m in tree.messages("ERROR")))

    def test_an_entry_with_no_produces_is_an_error(self):
        thin = DECLARATION.replace('produces = ["find_thing"]\n', "")
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, thin)
            self.assertTrue(any("names no `produces`" in m
                                for m in tree.messages("ERROR")))


class ClaimTests(unittest.TestCase):
    def test_an_owner_that_does_not_claim_the_entry_is_an_error(self):
        silent = READER.replace("\nOwns [owns:thing-position].\n", "")
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": silent, "cli": ""})
            self.assertTrue(any("does not claim `[owns:thing-position]`" in m
                                for m in tree.messages("ERROR")))

    def test_a_module_claiming_another_module_s_entry_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER,
                                "cli": '"""Owns [owns:thing-position]."""'})
            self.assertTrue(any("cli.py` claims `[owns:thing-position]`" in m
                                for m in tree.messages("ERROR")))

    def test_a_citation_to_no_entry_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER,
                                "cli": '"""See [owns:invented]."""'})
            self.assertTrue(any("`[owns:invented]`, which is not an entry" in m
                                for m in tree.messages("ERROR")))

    def test_a_document_citing_no_entry_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""},
                        docs={"NOTES.md": "routed by [owns:invented]\n"})
            self.assertTrue(any("NOTES.md cites `[owns:invented]`" in m
                                for m in tree.messages("ERROR")))


class PlacementTests(unittest.TestCase):
    def test_a_module_owning_nothing_and_not_infrastructure_is_an_error(self):
        """A new module lands in an entry or in the list; silence is not an option."""
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": "", "stranger": ""})
            self.assertTrue(any("stranger.py` owns no entry" in m
                                for m in tree.messages("ERROR")))

    def test_a_module_that_is_both_owner_and_infrastructure_is_an_error(self):
        both = DECLARATION.replace('modules = ["cli"]',
                                   'modules = ["cli", "reader"]')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, both)
            self.assertTrue(any("also declared infrastructure" in m
                                for m in tree.messages("ERROR")))

    def test_a_phantom_infrastructure_module_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER})
            self.assertTrue(any("declares `cli` infrastructure" in m
                                for m in tree.messages("ERROR")))

    def test_a_subpackage_module_is_placed_by_its_dotted_name(self):
        sub = DECLARATION.replace('owner = "reader"', 'owner = "pack.reader"')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"pack.reader": READER, "cli": ""}, sub)
            self.assertEqual(tree.verify(), [])


class DeferralTests(unittest.TestCase):
    """The rule one module owns and another restated until they disagreed."""

    LAW = DECLARATION + """
[[entry]]
id = "thing-lifetime"
question = "Did the thing end?"
owner = "lifecycle"
role = ["lifecycle"]
status = "shipped"
produces = ["ended"]
defers_to = ["thing-position"]
not_for = "Restating the reader's rule."
"""

    def test_a_deferral_backed_by_an_import_passes(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": "", "lifecycle": '''
                """A lifecycle.

                Owns [owns:thing-lifetime].
                """
                from .reader import find_thing


                def ended():
                    return find_thing()
                '''}, self.LAW)
            self.assertEqual(tree.verify(), [])

    def test_a_deferral_whose_import_is_gone_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": "", "lifecycle": '''
                """A lifecycle that re-derived the rule.

                Owns [owns:thing-lifetime].
                """


                def ended():
                    return 1
                '''}, self.LAW)
            self.assertTrue(any("no longer imports `reader`" in m
                                for m in tree.messages("ERROR")))


class ConsumerTests(unittest.TestCase):
    CONSUMED = DECLARATION.replace(
        'not_for = "Which thing it is."',
        'not_for = "Which thing it is."\nconsumers = ["cli"]')

    def test_a_consumer_that_imports_the_owner_passes(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER,
                                "cli": "from .reader import find_thing"},
                        self.CONSUMED)
            self.assertEqual(tree.verify(), [])

    def test_a_consumer_that_no_longer_imports_the_owner_is_reported(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, self.CONSUMED)
            found = tree.verify()
        self.assertEqual({lv for lv, _m in found}, {"WARN"})
        self.assertTrue(any("does not import `reader`" in m for _lv, m in found))


class StatusTests(unittest.TestCase):
    REACHING = '''
"""A reader that borrows a prototype.

Owns [owns:thing-position].
"""
from prototypes import helper


def find_thing():
    return helper
'''

    def test_an_owner_reaching_prototypes_must_be_transitional(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": self.REACHING, "cli": ""},
                        prototypes=("helper",))
            self.assertTrue(any("imports the prototypes tree" in m and
                                "`transitional`" in m
                                for m in tree.messages("ERROR")))

    def test_a_transitional_entry_owes_an_exit(self):
        moved = DECLARATION.replace('status = "shipped"',
                                    'status = "transitional"')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": self.REACHING, "cli": ""}, moved,
                        prototypes=("helper",))
            self.assertTrue(any("names no `exit`" in m
                                for m in tree.messages("ERROR")))

    def test_a_transitional_entry_whose_promotion_happened_is_reported(self):
        moved = DECLARATION.replace(
            'status = "shipped"',
            'status = "transitional"\nexit = "promote the helper"')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, moved,
                        prototypes=("helper",))
            self.assertTrue(any("no longer reaches prototypes/" in m
                                for m in tree.messages("WARN")))

    def test_an_unknown_status_is_an_error(self):
        odd = DECLARATION.replace('status = "shipped"', 'status = "nearly"')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, odd)
            self.assertTrue(any("status `nearly`" in m
                                for m in tree.messages("ERROR")))


class UnownedTests(unittest.TestCase):
    """A question with no owner is declared, not left to NOTES.md."""

    GAP = DECLARATION + """
[[entry]]
id = "thing-name"
question = "What is the thing called?"
role = ["assign"]
status = "unowned"
not_for = "The reader absorbing it."
"""

    def test_an_unowned_question_is_reported_every_run(self):
        with contextlib.ExitStack() as stack:
            named = self.GAP + 'blocked_by = "nothing reads names yet"\n'
            tree = Tree(stack, {"reader": READER, "cli": ""}, named)
            found = tree.verify()
        self.assertEqual({lv for lv, _m in found}, {"WARN"})
        self.assertTrue(any("nothing owns `thing-name`" in m for _lv, m in found))

    def test_an_unowned_question_owes_what_blocks_it(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"reader": READER, "cli": ""}, self.GAP)
            self.assertTrue(any("says nothing about what blocks it" in m
                                for m in tree.messages("ERROR")))


class RouteTests(unittest.TestCase):
    def test_only_the_best_matches_come_back(self):
        data = ownership.load()
        found = ownership.route("which agent died", data)
        self.assertEqual([e["id"] for e in found], ["death-victim"])

    def test_the_negative_boundary_is_searched_too(self):
        """Asking the wrong owner by name still reaches the entry saying so."""
        found = ownership.route("track semantic identity", ownership.load())
        self.assertIn("track-continuation", [e["id"] for e in found])


class RepositoryDeclarationTests(unittest.TestCase):
    """The real declaration, which must hold on every run."""

    def test_the_shipped_declaration_has_no_errors(self):
        self.assertEqual([m for lv, m in ownership.verify() if lv == "ERROR"], [])

    def test_every_module_owns_an_entry_or_is_infrastructure(self):
        data = ownership.load()
        placed = set(ownership.owners(data)) | set(
            data["infrastructure"]["modules"])
        self.assertEqual(set(ownership.modules()) - placed, set())

    def test_no_module_is_both_an_owner_and_infrastructure(self):
        data = ownership.load()
        self.assertEqual(set(ownership.owners(data)) &
                         set(data["infrastructure"]["modules"]), set())


if __name__ == "__main__":
    unittest.main()
