"""The stage 1 table builder (prototypes/glyph_tables.py): a sure player answer decides its key's row and cites its
line and domain fact; an unsure answer rotates with its reason; the rule decides the rest; the provenance names
the dev sessions and refuses any item from outside them."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "prototypes"))

import glyph_tables as gt  # noqa: E402


def ans(key, answer=None, unsure=False, other=None):
    return {"key": f"rotation:{key}", "kind": "rotation", "answer": answer, "unsure": unsure, "other": other,
            "by": "player"}


class PolicyRows(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        p = Path(self.tmp.name) / "answers.jsonl"
        rows = [{"key": "texture:TX_A", "kind": "texture", "answer": "Sova:C"},
                ans("Reyna:C", "rotates"),
                ans("Cypher:E", "rotates"),
                ans("Cypher:C", unsure=True),
                ans("Deadlock:Q", "other", other="I think it could be any angle but it is always normal to the wall"),
                ans("Reyna:C", "upright")]                     # a later row revises line 2
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.answers = gt.rotation_answer_rows(p)
        verdicts = {"Cypher:E": "rotates", "Cypher:C": "rotates", "Reyna:C": "rotates", "Deadlock:Q": "mixed",
                    "Gekko:Q": "mixed", "Sova:E": "upright", "Phoenix:C": "undetermined"}
        keys = ["Cypher:C", "Cypher:E", "Deadlock:Q", "Gekko:Q", "Phoenix:C", "Reyna:C", "Sova:E", "Sova:Q"]
        self.rows = {r["key"]: r for r in gt.policy_rows(keys, self.answers, verdicts, {})}

    def tearDown(self):
        self.tmp.cleanup()

    def test_player_answer_decides_and_cites_its_line_and_fact(self):
        r = self.rows["Cypher:E"]
        self.assertEqual((r["policy"], r["decided_by"]), ("rotates", "player_answer"))
        self.assertEqual(r["answer"]["line"], 3)
        self.assertEqual(r["domain"], "abilities/cypher-spycam-minimap-glyph-turns")
        self.assertEqual(r["rotations"], list(range(0, 360, 15)))

    def test_last_answer_row_wins_and_a_contradicted_rule_is_a_surprise(self):
        r = self.rows["Reyna:C"]
        self.assertEqual((r["policy"], r["answer"]["line"], r["rotations"]), ("upright", 6, [0]))
        self.assertIn("contradicts the two-flag rule", r["surprise"])

    def test_unsure_key_rotates_with_its_reason(self):
        r = self.rows["Cypher:C"]
        self.assertEqual((r["policy"], r["decided_by"], r["reason"]),
                         ("rotates", "unsure_pending_player", "unsure_pending_player"))
        self.assertEqual(r["answer"]["line"], 4)

    def test_wall_normal_answer_searches_every_rotation(self):
        r = self.rows["Deadlock:Q"]
        self.assertEqual((r["policy"], r["decided_by"]), ("rotates", "player_answer"))
        self.assertEqual(r["domain"], "abilities/deadlock-sonic-sensor-square-follows-wall")

    def test_rule_decides_unanswered_keys(self):
        self.assertEqual(self.rows["Gekko:Q"]["policy"], "rotates")       # mixed
        self.assertEqual(self.rows["Phoenix:C"]["policy"], "rotates")     # undetermined
        self.assertEqual(self.rows["Sova:E"]["policy"], "upright")
        self.assertEqual((self.rows["Sova:Q"]["policy"], self.rows["Sova:Q"]["reason"]),
                         ("upright", "two_flag_rule:no_component"))


class Provenance(unittest.TestCase):
    def item(self, sid, split="dev", src="ability"):
        return {"sid": sid, "split": split, "src": src, "t_ms": 1000.0}

    def test_fields_present_and_no_heldout_session(self):
        dev = {"d95cfad5693a", "dae6f33f3f48"}
        p = gt.table_provenance({}, [self.item("d95cfad5693a"), self.item("dae6f33f3f48", src="paint")], dev, [347, 369])
        for f in ("generator", "build", "answers", "gamedata", "dev_sessions", "dev_run", "heldout_sessions"):
            self.assertIn(f, p)
        self.assertEqual(p["answers"]["lines"], [347, 369])
        self.assertEqual(p["dev_sessions"], sorted(dev))
        self.assertEqual(p["heldout_sessions_used"], [])
        self.assertFalse(set(p["dev_sessions"]) & set(p["heldout_sessions"]["heldout_pass"]))

    def test_refuses_an_item_from_outside_the_dev_sessions(self):
        dev = {"d95cfad5693a"}
        for bad in (self.item("29eff6920e8f", split="heldout"), self.item("d95cfad5693a", src="minimap_glyph_heldout")):
            with self.assertRaises(SystemExit):
                gt.table_provenance({}, [bad], dev, [])


class Cut(unittest.TestCase):
    def test_at_most_the_rate_exceeds_the_cut(self):
        s = list(range(100))
        c = gt.cut_at(s, 0.05)
        self.assertEqual(c, 94.0)
        self.assertEqual(sum(v > c for v in s), 5)
        self.assertIsNone(gt.cut_at([], 0.05))

    def test_every_answer_fact_exists(self):
        text = (ROOT / "domain" / "abilities.toml").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\[([a-z0-9-]+)\]", text, re.M))
        for k, f in gt.ANSWER_FACTS.items():
            self.assertIn(f.split("/", 1)[1], ids, k)


if __name__ == "__main__":
    unittest.main()
