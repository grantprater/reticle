"""Quoted figures, checked against the run that produced them."""
import contextlib
import tempfile
import unittest
from pathlib import Path

from reticle import metrics, quoted


def row(tool, part, session, values, status=metrics.PASS, at="2026-09-10T10:00:00"):
    return {"at": at, "tool": tool, "part": part, "session": session,
            "status": status, "values": dict(values), "deps": {}, "context": {}}


ROWS = [row("proposal_audit", "acquisition", "d95", {"recall": 0.9375,
                                                     "precision": 0.0907}),
        row("enemy_detect", "labels", "", {"recall": 0.913})]


class Tree:
    """A throwaway repo holding one prose file."""

    def __init__(self, stack, files):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (self.root / "docs").mkdir()
        for name, text in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")

    def verify(self, rows=ROWS):
        return quoted.verify(self.root, rows)

    def messages(self, level=None, rows=ROWS):
        return [m for lv, m in self.verify(rows) if level is None or lv == level]


class AgreementTests(unittest.TestCase):
    def test_a_fraction_matches_at_its_own_precision(self):
        self.assertTrue(quoted._agrees("0.9375", 0.9375))
        self.assertTrue(quoted._agrees("0.94", 0.9375))
        self.assertFalse(quoted._agrees("0.77", 0.9375))

    def test_a_percentage_is_understood(self):
        self.assertTrue(quoted._agrees("93.8%", 0.9375))
        self.assertTrue(quoted._agrees("94%", 0.9375))
        self.assertFalse(quoted._agrees("77.1%", 0.9375))

    def test_an_integer_matches_a_rounded_value(self):
        self.assertTrue(quoted._agrees("12", 12))
        self.assertTrue(quoted._agrees("100%", 1.0))

    def test_a_missing_stored_value_never_agrees(self):
        self.assertFalse(quoted._agrees("0.5", None))

    def test_a_non_numeric_quote_compares_as_text(self):
        self.assertTrue(quoted._agrees("baked", "baked"))
        self.assertFalse(quoted._agrees("baked", "session"))


class CitationTests(unittest.TestCase):
    def test_a_citation_is_parsed_with_its_file_and_line(self):
        import contextlib as c
        with c.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "intro\nrecall 93.8% "
                                "[metric:proposal_audit/acquisition@d95"
                                "#recall=0.9375]\n"})
            got = quoted.citations(tree.root)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["series"], "proposal_audit/acquisition")
        self.assertEqual(got[0]["session"], "d95")
        self.assertEqual(got[0]["field"], "recall")
        self.assertEqual(got[0]["line"], 2)

    def test_a_series_name_may_carry_dots_spaces_and_pipes(self):
        import contextlib as c
        with c.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:floor_mask_eval/reticle.minimap | "
                                "PLANT#iou=0.9]"})
            got = quoted.citations(tree.root)
        self.assertEqual(got[0]["series"],
                         "floor_mask_eval/reticle.minimap | PLANT")

    def test_an_agreeing_citation_is_silent(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:proposal_audit/acquisition@d95"
                                "#recall=0.9375]"})
            self.assertEqual(
                [m for lv, m in tree.verify() if "nobody uses" not in m], [])

    def test_A_STALE_NUMBER_IS_REPORTED_WITH_BOTH_VALUES(self):
        """The whole reason the citation carries the value."""
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:proposal_audit/acquisition@d95"
                                "#recall=0.771]"})
            warns = tree.messages("WARN")
        stale = [m for m in warns if "stale" in m]
        self.assertEqual(len(stale), 1)
        self.assertIn("0.771", stale[0])
        self.assertIn("0.9375", stale[0])
        self.assertIn("docs/a.md:1", stale[0])

    def test_a_citation_to_an_unrecorded_series_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md": "[metric:no_such_tool/part#x=1]"})
            errors = tree.messages("ERROR")
        self.assertTrue(any("no_such_tool/part" in m and "no recorded" in m
                            for m in errors))

    def test_a_citation_to_a_field_the_run_lacks_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:proposal_audit/acquisition@d95"
                                "#f1=0.5]"})
            errors = tree.messages("ERROR")
        self.assertTrue(any("`f1`" in m and "does not record" in m
                            for m in errors))

    def test_a_citation_to_an_unrecorded_session_is_an_error(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:proposal_audit/acquisition@nope"
                                "#recall=0.9]"})
            errors = tree.messages("ERROR")
        self.assertTrue(any("nope" in m and "no recorded" in m for m in errors))

    def test_an_ambiguous_sessionless_citation_is_an_error(self):
        rows = ROWS + [row("proposal_audit", "acquisition", "a06",
                           {"recall": 0.7273})]
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:proposal_audit/acquisition#recall=0.9]"})
            errors = tree.messages("ERROR", rows)
        self.assertTrue(any("no session" in m and "@session" in m
                            for m in errors))

    def test_a_sessionless_series_resolves_without_one(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md":
                                "[metric:enemy_detect/labels#recall=0.913]"})
            self.assertEqual(
                [m for lv, m in tree.verify() if "nobody uses" not in m], [])


class BaselineTests(unittest.TestCase):
    def test_only_a_pass_run_is_ever_the_reference(self):
        """A broken run becoming the baseline would re-baseline the fault."""
        rows = [row("t", "p", "s", {"recall": 0.5}),
                row("t", "p", "s", {"recall": 0.9}, status=metrics.BROKEN,
                    at="2026-09-11T10:00:00")]
        index = quoted.latest_pass(rows)
        self.assertEqual(index[("t/p", "s")]["values"]["recall"], 0.5)

    def test_the_latest_pass_run_wins(self):
        rows = [row("t", "p", "s", {"recall": 0.5}),
                row("t", "p", "s", {"recall": 0.8}, at="2026-09-11T10:00:00")]
        index = quoted.latest_pass(rows)
        self.assertEqual(index[("t/p", "s")]["values"]["recall"], 0.8)


class ExemptionTests(unittest.TestCase):
    def test_the_append_only_records_are_not_scanned(self):
        self.assertIn("NOTES.md", quoted.HISTORY)
        self.assertIn("BACKLOG.md", quoted.HISTORY)
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"NOTES.md":
                                "[metric:proposal_audit/acquisition@d95"
                                "#recall=0.771]"})
            self.assertEqual(quoted.citations(tree.root), [])

    def test_a_recorded_series_nothing_cites_is_reported_once(self):
        with contextlib.ExitStack() as stack:
            tree = Tree(stack, {"docs/a.md": "no citations here"})
            warns = tree.messages("WARN")
        self.assertEqual(len(warns), 1)
        self.assertIn("2 recorded metric series", warns[0])


class RepositoryQuotesTests(unittest.TestCase):
    """The real prose, which must stay honest on every run."""

    def test_no_quoted_figure_in_the_repo_is_dangling(self):
        problems = quoted.verify()
        self.assertEqual([m for lv, m in problems if lv == "ERROR"], [])

    def test_no_quoted_figure_in_the_repo_is_stale(self):
        stale = [m for lv, m in quoted.verify() if "stale" in m]
        self.assertEqual(stale, [])

    def test_the_repo_actually_cites_something(self):
        """A check with nothing to check would pass forever."""
        self.assertGreater(len(quoted.citations()), 0)

    def test_this_module_does_not_count_as_a_citer(self):
        self.assertIn("reticle/quoted.py", quoted.EXAMPLE_ONLY)
        for cite in quoted.citations():
            self.assertNotIn(cite["file"], quoted.EXAMPLE_ONLY)


if __name__ == "__main__":
    unittest.main()
