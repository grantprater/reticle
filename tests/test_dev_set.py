"""The development split has one definition (`reticle.dev_set`), and every
output a frozen session feeds carries `dev_set.FROZEN_LABEL`.

No store is read: a frozen session's stale streams come from a stub.
"""
import ast
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reticle import dev_set

ROOT = Path(__file__).resolve().parents[1]
SPLIT_IDS = set(dev_set.DEV + dev_set.FROZEN + dev_set.FROZEN_HELD_OUT_REPLAY)
SPLIT_WORDS = ("DEV", "HELD", "FROZEN", "SCORED", "SPLIT", "NEW")
#: Literals naming split sessions that are not the split: (file, name) -> why.
NOT_THE_SPLIT = {
    ("reticle/harness/schedule.py", "JUDGED"): "the read-schedule study's registered pair (2026-10-07)",
}


def _split_literals(path: Path) -> list[tuple[int, str]]:
    """(line, name) of each collection literal holding two or more split ids,
    and of each assignment of one split id to a name, in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            v = node.value
            if isinstance(v, ast.Constant) and v.value in SPLIT_IDS:
                # one session named as a split role (a held-out or development id)
                out += [(node.lineno, n) for n in names if any(w in n for w in SPLIT_WORDS)]
            elif isinstance(v, (ast.Tuple, ast.List, ast.Set)):
                ids = [e.value for e in v.elts if isinstance(e, ast.Constant) and e.value in SPLIT_IDS]
                if len(ids) >= 2:
                    out += [(node.lineno, n) for n in names] or [(node.lineno, "?")]
        elif isinstance(node, ast.For) and isinstance(node.iter, (ast.Tuple, ast.List)):
            ids = [e for e in node.iter.elts if isinstance(e, ast.Constant) and e.value in SPLIT_IDS]
            if len(ids) >= 2:
                out.append((node.lineno, "for"))
    return out


class OneDefinitionTests(unittest.TestCase):
    def test_the_split_is_defined_once(self):
        found = []
        for d in ("reticle", "prototypes"):
            for p in sorted((ROOT / d).rglob("*.py")):
                rel = p.relative_to(ROOT).as_posix()
                if rel == "reticle/dev_set.py":
                    continue
                found += [f"{rel}:{ln} {n}" for ln, n in _split_literals(p)
                          if (rel, n) not in NOT_THE_SPLIT]
        self.assertEqual(found, [], "a copy of the split; import it from reticle.dev_set")

    def test_the_split(self):
        self.assertEqual(dev_set.DEV, ("cadaadeb2d8b", "066741deafe5", "9912c382130b"))
        self.assertEqual(set(dev_set.FROZEN),
                         {"9acf02f98283", "c817691bcd15", "d3dcfb182ab1", "cea8ecbc94ab"})
        self.assertEqual(dev_set.HELD_OUT, ())
        self.assertFalse(set(dev_set.DEV) & set(dev_set.FROZEN))

    def test_every_default_reads_the_one_definition(self):
        import argparse

        from reticle import cli, dev_sample
        from reticle.harness import commands
        self.assertIs(cli.ACCEPTANCE_DEV, dev_set.DEV)
        self.assertIs(dev_sample.MATCHES, dev_set.DEV)
        self.assertEqual({w.session for w in dev_sample.SAMPLE}, set(dev_set.DEV))
        ap = argparse.ArgumentParser()
        commands.add_parsers(ap.add_subparsers(dest="cmd"))
        for cmd in ("lane", "label", "ally", "replay-score", "budget", "slots", "ability-lane"):
            extra = ["--tag", "t"] if cmd in ("lane", "label", "budget", "ability-lane") else []
            self.assertEqual(ap.parse_args([cmd] + extra).sessions, list(dev_set.DEV), cmd)

    def test_pool_names_follow_the_sessions(self):
        self.assertEqual(dev_set.pool_name(reversed(dev_set.DEV)), "new3")
        self.assertEqual(dev_set.pool_name(dev_set.FROZEN_DEV), "dev3")
        self.assertEqual(dev_set.pool_name(["d3dcfb182ab1", "cadaadeb2d8b"]), "cadaadeb2d8b+d3dcfb182ab1")
        self.assertEqual(dev_set.frozen_in(["new3"]), [])
        self.assertEqual(sorted(dev_set.frozen_in(["dev3"])), sorted(dev_set.FROZEN_DEV))
        self.assertEqual(dev_set.frozen_in(["9acf02f98283_causal", "cadaadeb2d8b"]), ["9acf02f98283"])

    def test_held_out_matches_are_never_read(self):
        for name in ("cea8ecbc94ab", "bd7efa02-1111"):
            self.assertIn("held-out", dev_set.refusal(name))
        self.assertIsNone(dev_set.refusal("cadaadeb2d8b"))
        self.assertIsNone(dev_set.refusal("d3dcfb182ab1"))


class FrozenLabelTests(unittest.TestCase):
    NOTE = {"frozen": dev_set.FROZEN_LABEL, "stale_streams": ["ally_icon", "death"]}

    def setUp(self):
        from reticle.harness import extras
        self.extras = extras
        p = mock.patch.object(extras, "frozen_note", return_value=self.NOTE)
        p.start()
        self.addCleanup(p.stop)

    def test_a_document_a_frozen_session_feeds_is_labelled(self):
        doc = {"sessions": {}}
        got = self.extras.label(doc, ["cadaadeb2d8b", "d3dcfb182ab1"])
        self.assertEqual(got["frozen"], {"d3dcfb182ab1": self.NOTE})
        self.assertNotIn("frozen", doc)                       # a copy; the caller's doc is untouched
        self.assertNotIn("frozen", self.extras.label({"x": 1}, list(dev_set.DEV)))

    def test_a_metric_row_a_frozen_session_feeds_is_labelled(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / "metrics.jsonl"
            for session in ("dev3", "c817691bcd15", "new3"):
                self.extras.record("t", part="p", session=session, values={"v": 1}, deps={},
                                   log_path=log)
            rows = [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()]
        frozen = [r["context"].get("frozen") for r in rows]
        self.assertEqual(sorted(frozen[0]), sorted(dev_set.FROZEN_DEV))
        self.assertEqual(frozen[1], {"c817691bcd15": self.NOTE})
        self.assertIsNone(frozen[2])
        self.assertEqual(frozen[1]["c817691bcd15"]["frozen"], "frozen: stale inputs")


if __name__ == "__main__":
    unittest.main()
