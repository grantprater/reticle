"""The declared layering, and the four faults its checks exist for."""
import contextlib
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import architecture


DECLARATION = """
[layers]
order = ["bottom", "middle", "top"]

[bottom]
claim = "nothing below"
modules = ["version"]

[middle]
claim = "readers"
modules = ["reader"]

[top]
claim = "the command surface"
modules = ["cli"]

[trees]
claim = "reticle/ must not import prototypes/"
allow = []
"""


class Tree:
    """A throwaway repo: architecture.toml plus a reticle/ and a prototypes/."""

    def __init__(self, stack, modules, declaration=DECLARATION, prototypes=()):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "architecture.toml").write_text(declaration, encoding="utf-8")
        (self.root / "reticle").mkdir()
        (self.root / "prototypes").mkdir()
        for name in prototypes:
            (self.root / "prototypes" / f"{name}.py").write_text("", encoding="utf-8")
        for name, body in modules.items():
            (self.root / "reticle" / f"{name}.py").write_text(
                textwrap.dedent(body), encoding="utf-8")

    def verify(self):
        data = architecture.load(self.root / "architecture.toml")
        return architecture.verify(data, self.root)

    def messages(self, level=None):
        return [m for lv, m in self.verify() if level is None or lv == level]


class SiblingImportTests(unittest.TestCase):
    def test_an_import_inside_a_function_is_deferred(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": """
                from .version import A

                def go():
                    from .reader import B
                """})
            got = architecture.sibling_imports(tree.root / "reticle" / "cli.py")
        kinds = {name: deferred for name, _line, deferred in got}
        self.assertEqual(kinds, {"version": False, "reader": True})

    def test_both_absolute_and_relative_spellings_are_seen(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": """
                import reticle.version
                from reticle.reader import x
                from . import version
                """})
            got = {name for name, _line, _d in
                   architecture.sibling_imports(tree.root / "reticle" / "cli.py")}
        self.assertEqual(got, {"version", "reader"})


class LayerTests(unittest.TestCase):
    def test_a_downward_import_is_fine(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "from .version import A",
                                "cli": "from .reader import B"})
            self.assertEqual(tree.verify(), [])

    def test_an_eager_upward_import_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "from .reader import A",
                                "reader": "", "cli": ""})
            errors = tree.messages("ERROR")
        self.assertTrue(any("`version` (bottom) imports `reader` (middle) eager"
                            in m for m in errors))

    def test_a_deferred_upward_import_is_reported_but_does_not_block(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": """
                def go():
                    from .reader import A
                """, "reader": "", "cli": ""})
            found = tree.verify()
        self.assertEqual({lv for lv, _m in found}, {"WARN"})
        self.assertTrue(any("deferred" in m for _lv, m in found))

    def test_a_blessed_edge_passes_and_a_changed_kind_does_not(self):
        blessed = DECLARATION + """
[[exception]]
from = "version"
to = "reader"
kind = "deferred"
reason = "for the test"
"""
        with contextlib.ExitStack() as stack:
            deferred = Tree(stack, {"version": """
                def go():
                    from .reader import A
                """, "reader": "", "cli": ""}, blessed)
            self.assertEqual(deferred.verify(), [])
        with contextlib.ExitStack() as stack:
            eager = Tree(stack, {"version": "from .reader import A",
                                 "reader": "", "cli": ""}, blessed)
            self.assertTrue(any("blessed as deferred and is now eager" in m
                                for m in eager.messages("ERROR")))

    def test_a_module_may_import_its_own_layer(self):
        same = """
[layers]
order = ["only"]

[only]
claim = "one layer"
modules = ["a", "b"]

[trees]
claim = "no crossing"
allow = []
"""
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"a": "from .b import B", "b": ""}, same)
            self.assertEqual(tree.verify(), [])


class StaleDeclarationTests(unittest.TestCase):
    def test_an_unplaced_module_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": "",
                                "stranger": ""})
            self.assertTrue(any("stranger" in m and "no declared layer" in m
                                for m in tree.messages("ERROR")))

    def test_a_phantom_module_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": ""})
            self.assertTrue(any("declares `cli`" in m
                                for m in tree.messages("ERROR")))

    def test_a_module_in_two_layers_is_an_error(self):
        twice = DECLARATION.replace('modules = ["cli"]',
                                    'modules = ["cli", "reader"]')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": ""}, twice)
            self.assertTrue(any("more than one layer" in m
                                for m in tree.messages("ERROR")))

    def test_an_exception_for_an_edge_that_is_gone_is_reported(self):
        stale = DECLARATION + """
[[exception]]
from = "version"
to = "reader"
kind = "eager"
reason = "the edge was deleted"
"""
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": ""}, stale)
            self.assertTrue(any("no longer exists" in m
                                for m in tree.messages("WARN")))


class TreeDirectionTests(unittest.TestCase):
    def test_a_prefixed_import_of_the_other_tree_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli":
                                "from prototypes import helper"},
                        prototypes=("helper",))
            self.assertTrue(any("imports the prototypes tree" in m
                                for m in tree.messages("ERROR")))

    def test_a_BARE_import_after_a_path_insert_is_also_an_error(self):
        """The spelling that hides. `lineup` and `doctor` both use it."""
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": """
                import sys
                sys.path.insert(0, "prototypes")
                import helper
                """}, prototypes=("helper",))
            self.assertTrue(any("imports the prototypes tree" in m and
                                "helper" in m
                                for m in tree.messages("ERROR")))

    def test_a_bare_import_that_is_not_a_prototype_is_left_alone(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "",
                                "cli": "import json\nimport numpy"},
                        prototypes=("helper",))
            self.assertEqual(tree.verify(), [])

    def test_an_allowed_module_passes_and_a_stale_allowance_is_reported(self):
        allowed = DECLARATION.replace("allow = []", 'allow = ["cli"]')
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "",
                                "cli": "from prototypes import helper"},
                        allowed, prototypes=("helper",))
            self.assertEqual(tree.verify(), [])
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"version": "", "reader": "", "cli": ""},
                        allowed, prototypes=("helper",))
            self.assertTrue(any("no longer does" in m
                                for m in tree.messages("WARN")))


class RepositoryDeclarationTests(unittest.TestCase):
    """The real declaration, which must hold on every run."""

    def test_the_shipped_declaration_has_no_errors(self):
        problems = architecture.verify()
        self.assertEqual([m for lv, m in problems if lv == "ERROR"], [])

    def test_every_module_is_placed_exactly_once(self):
        data = architecture.load()
        self.assertEqual(data["_duplicated"], [])
        present = {p.stem for p in (architecture.ROOT / "reticle").glob("*.py")
                   if p.stem != "__init__"}
        self.assertEqual(present - set(data["_index"]), set())

    def test_the_module_level_graph_is_acyclic(self):
        """The declared order can only exist if the eager graph is a DAG."""
        edges = {m: e["eager"] for m, e in architecture.graph().items()}
        colour: dict[str, int] = {}
        cycles: list[str] = []

        def walk(node):
            colour[node] = 1
            for onward in edges.get(node, ()):
                if colour.get(onward) == 1:
                    cycles.append(f"{node} -> {onward}")
                elif onward not in colour:
                    walk(onward)
            colour[node] = 2

        for node in sorted(edges):
            if node not in colour:
                walk(node)
        self.assertEqual(cycles, [])


if __name__ == "__main__":
    unittest.main()
