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
        self.assertEqual(self.rows["Sova:E"]["decided_by"], "two_flag_rule")

    def test_a_key_no_component_draws_is_an_unverified_default(self):
        r = self.rows["Sova:Q"]
        self.assertEqual((r["policy"], r["decided_by"]), ("upright", "no_component_default"))
        self.assertIn("unverified", r["reason"])


class Provenance(unittest.TestCase):
    def item(self, sid, split="dev", src="ability"):
        return {"sid": sid, "split": split, "src": src, "t_ms": 1000.0}

    def test_fields_present_and_no_heldout_session(self):
        dev = {"d95cfad5693a", "dae6f33f3f48"}
        p = gt.table_provenance({}, [self.item("d95cfad5693a"), self.item("dae6f33f3f48", src="paint")], dev, [347, 369],
                                ["043bafca271a"], ["043bafca271a", "4f207c0c4e39"])
        for f in ("generator", "build", "answers", "gamedata", "dev_sessions", "dev_run", "heldout_sessions"):
            self.assertIn(f, p)
        self.assertEqual(p["heldout_sessions"]["eval_heldout_split"], ["043bafca271a"])
        self.assertEqual(p["heldout_sessions"]["s5_match_sessions"], ["043bafca271a", "4f207c0c4e39"])
        self.assertEqual(p["answers"]["lines"], [347, 369])
        self.assertEqual(p["dev_sessions"], sorted(dev))
        self.assertEqual(p["heldout_sessions_used"], [])
        self.assertFalse(set(p["dev_sessions"]) & set(p["heldout_sessions"]["heldout_pass"]))

    def test_refuses_an_item_from_outside_the_dev_sessions(self):
        dev = {"d95cfad5693a"}
        for bad in (self.item("29eff6920e8f", split="heldout"), self.item("d95cfad5693a", src="minimap_glyph_heldout"),
                    self.item("043bafca271a")):
            with self.assertRaises(SystemExit):
                gt.table_provenance({}, [bad], dev, [], ["043bafca271a"], [])


class Cut(unittest.TestCase):
    def test_at_most_the_rate_exceeds_the_cut(self):
        s = list(range(100))
        c = gt.cut_at(s, 0.05)
        self.assertEqual(c, 94.0)
        self.assertEqual(sum(v > c for v in s), 5)
        self.assertIsNone(gt.cut_at([], 0.05))

    def test_bank_cut_holds_each_bank_and_scale_at_the_rate(self):
        import numpy as np
        keys = ["A:C", "A:Q", "B:C"]
        rng = np.random.default_rng(0)
        neg = [{"win_index": i, "scale": 1.0 if i < 40 else 1.15, "kit": ["A:C", "A:Q"]} for i in range(80)]
        sc = {i: rng.random(3).astype(np.float32) for i in range(80)}
        best = np.array([max(sc[i][:2]) for i in range(80)])
        b = gt.bank_cut(neg, [], sc, keys, "context", best)
        self.assertLessEqual(b["rate"], 0.05)
        self.assertEqual(b["named"], 4)
        self.assertEqual(sorted(b["by_scale"]), ["1.0", "1.15"])
        self.assertTrue(all(v["rate"] <= 0.05 for v in b["by_scale"].values()))

    def test_paired_counts_the_self_seed_on_casts_the_thrown_seed_named(self):
        rows = [{"self_seed": "right", "rotate_all": {"outcome": "right"}},
                {"self_seed": "wrong", "rotate_all": {"outcome": "right"}},
                {"self_seed": "wrong", "rotate_all": {"outcome": "wrong"}},
                {"self_seed": "refused", "rotate_all": {"outcome": "wrong"}},
                {"self_seed": "right", "rotate_all": {"outcome": "refused"}},
                {"refused": "no_thrown_birth"}]
        p = gt.paired(rows)
        self.assertEqual((p["thrown_named"], p["self_right"], p["self_wrong"], p["self_refused"]), (4, 1, 2, 1))
        self.assertEqual((p["both_named"], p["both_right"], p["both_wrong"], p["thrown_only_right"],
                          p["self_only_right"]), (3, 1, 1, 1, 0))

    def test_items_move_to_the_full_transform_and_a_wrong_widget_refuses(self):
        """A: the null is measured at widget x map zoom (geometry.MapScale.scale)."""
        from unittest import mock
        from reticle import geometry
        ms = geometry.MapScale("ascent__valorant-16x9", 0.71183, 0.8871, "test")
        items = [{"sid": "d95cfad5693a", "scale": 331 / 465.0}]
        with mock.patch.object(geometry, "map_scale_of", return_value=ms):
            prov = gt.to_map_scale(items)
            self.assertAlmostEqual(items[0]["scale"], ms.scale)
            self.assertAlmostEqual(items[0]["widget_scale"], 331 / 465.0)
            self.assertEqual(prov["d95cfad5693a"]["map_zoom"], 0.8871)
            gt.to_map_scale(items)                        # idempotent: it reads the kept widget scale
            self.assertAlmostEqual(items[0]["scale"], ms.scale)
            with self.assertRaises(SystemExit):
                gt.to_map_scale([{"sid": "d95cfad5693a", "scale": 1.0}])
        with mock.patch.object(geometry, "map_scale_of", return_value=None):
            with self.assertRaises(SystemExit):
                gt.to_map_scale([{"sid": "x", "scale": 1.0}])

    def test_the_audit_null_reads_every_key_and_holds_its_bank_at_the_rate(self):
        """C: per-key cuts and one bank cut at the audit's search size."""
        import numpy as np
        keys = ["A:C", "A:Q", "B:C"]
        rng = np.random.default_rng(1)
        neg = [{"win_index": i} for i in range(60)]
        sc = {i: rng.random(3).astype(np.float32) for i in range(60)}
        sc[100] = np.array([0.1, 0.99, 0.2], np.float32)
        pos = [{"win_index": 100, "truth": "A:Q"}]
        a = gt.audit_null(neg, pos, sc, keys)
        self.assertEqual(sorted(a["keys"]), keys)
        self.assertLessEqual(a["bank_cut"]["rate"], 0.05)
        self.assertEqual(a["bank_cut"]["named"], 3)
        self.assertEqual(a["bank_cut"]["glyph_items_named_right_cut"], 1)

    def test_gate3_counts_unlabelled_discs_only_when_some_entered(self):
        bank = {"false_naming_rate_cut": 0.1, "bank_cut": {"rate": 0.04, "by_scale": {"1.0": {"rate": 0.04}}}}
        nt = {"banks": {"context": bank, "full": bank, "audit": {"bank_cut": {"rate": 0.04}}},
              "negatives": {"by_source": {"ability": 63}}}
        self.assertFalse(gt.gate3(nt)["unlabelled_proposer_discs"])
        nt["negatives"]["by_source"][gt.UNLABELLED_SRC] = 4
        g = gt.gate3(nt)
        self.assertTrue(g["unlabelled_proposer_discs"])
        self.assertEqual(g["unlabelled_n"], 4)

    def test_only_exhaustive_paint_frames_vouch_for_unlabelled_discs(self):
        """B: a proposer disc no label names is a negative only on a frame the
        player painted exhaustively; the latest row per time decides, so a
        later non-exhaustive or unsure row retracts an exhaustive one."""
        from unittest import mock
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "ability_paint"
            p.mkdir()
            rows = [{"kind": "frame", "t_ms": 0, "exhaustive": True, "icons": []},
                    {"kind": "frame", "t_ms": 0, "exhaustive": True, "icons": [{"x": 1, "y": 2}]},
                    {"kind": "frame", "t_ms": 500, "exhaustive": False, "icons": []},
                    {"kind": "frame", "t_ms": 900, "exhaustive": True, "unsure": True, "icons": []},
                    {"kind": "frame", "t_ms": 1400, "exhaustive": True, "icons": []},
                    {"kind": "frame", "t_ms": 1400, "exhaustive": False, "icons": []},     # retracted
                    {"kind": "frame", "t_ms": 1900, "exhaustive": True, "icons": []},
                    {"kind": "frame", "t_ms": 1900, "exhaustive": True, "unsure": True, "icons": []}]
            (p / "s1.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
            with mock.patch.object(gt.mge, "LABELS", Path(d)):
                got = gt.exhaustive_paint_frames("s1")
                self.assertEqual(sorted(got), [0.0])
                self.assertEqual(got[0.0]["icons"], [{"x": 1, "y": 2}])
                self.assertEqual(gt.exhaustive_paint_frames("none"), {})

    def test_every_answer_fact_exists(self):
        text = (ROOT / "domain" / "abilities.toml").read_text(encoding="utf-8")
        ids = set(re.findall(r"^\[([a-z0-9-]+)\]", text, re.M))
        for k, f in gt.ANSWER_FACTS.items():
            self.assertIn(f.split("/", 1)[1], ids, k)


if __name__ == "__main__":
    unittest.main()
