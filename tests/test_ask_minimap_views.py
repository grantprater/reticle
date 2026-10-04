"""The minimap glyph asking tool asks each view (self, teammate, enemy) on its own: no view's answer settles another
[domain:abilities/views-separate-per-ability], the sheet's caster-view cell settles `self` alone, and the game data
orders and annotates questions without answering them."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import ask_minimap_glyphs as ask  # noqa: E402

SHEET = {("Omen", "X"): ("From the Shadows", "?"),
         ("Yoru", "X"): ("Dimensional Drift", "icon [domain:abilities/views-separate-per-ability]"),
         ("Sova", "C"): ("Owl Drone", "nothing (census 1)")}
INV = {"rows": [{"proposed": "Sova:C", "name": "TX_UI_Minimap_Hunter_C"}]}
GD = {("Omen", "X"): {"views": {"self": {"drawn": 2, "not_drawn": 0, "unknown": 0},
                                "teammate": {"drawn": 2, "not_drawn": 0, "unknown": 0},
                                "enemy": {"drawn": 0, "not_drawn": 2, "unknown": 0}}, "cues": ["TX_Omen_X"]}}


class ViewsSeparate(unittest.TestCase):
    def setUp(self):
        self.saved = ask.sheet_minimap
        ask.sheet_minimap = lambda: SHEET

    def tearDown(self):
        ask.sheet_minimap = self.saved

    def test_each_view_is_its_own_question(self):
        pruned = []
        keys = [q["key"] for q in ask.visibility_questions(INV, pruned, GD)]
        for v in ("self", "ally", "enemy"):
            self.assertIn(f"visibility:Omen:X:{v}", keys)
        self.assertNotIn("visibility:Omen:X:drawing", keys)
        self.assertFalse(any(k.endswith(":spectator") for k in keys))

    def test_decided_sheet_cell_settles_self_alone(self):
        pruned = []
        keys = [q["key"] for q in ask.visibility_questions(INV, pruned, GD)]
        self.assertEqual(pruned, [("Yoru:X", "Dimensional Drift")])
        self.assertNotIn("visibility:Yoru:X:self", keys)
        self.assertIn("visibility:Yoru:X:ally", keys)
        self.assertIn("visibility:Yoru:X:enemy", keys)

    def test_order_proposed_then_game_data_then_rest_self_first(self):
        qs = ask.visibility_questions(INV, [], GD)
        self.assertEqual([q["key"] for q in qs[:3]],
                         ["visibility:Sova:C:self", "visibility:Sova:C:ally", "visibility:Sova:C:enemy"])
        self.assertEqual(qs[3]["key"], "visibility:Omen:X:self")
        self.assertEqual(qs[-1]["key"], "visibility:Yoru:X:enemy")

    def test_game_data_annotates_never_answers(self):
        qs = {q["key"]: q for q in ask.visibility_questions(INV, [], GD)}
        q = qs["visibility:Omen:X:enemy"]
        self.assertIn("enemy: 0 drawn / 2 not", q["shown"]["game_data"])
        self.assertNotIn("answer", q)
        self.assertIn("Omen X From the Shadows, AN ENEMY'S, INSIDE VISION VIEW", ask.prompt(q))


class AnswersStandForTheirOwnKey(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "answers.jsonl"
        rows = [{"key": "visibility:Yoru:X:ally", "kind": "visibility", "answer": "icon", "unsure": False},
                {"key": "visibility:Omen:X:enemy", "kind": "visibility", "answer": None, "unsure": True}]
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.saved = ask.ANSWERS
        ask.ANSWERS = self.path

    def tearDown(self):
        ask.ANSWERS = self.saved
        self.tmp.cleanup()

    def test_teammate_answer_settles_no_other_view(self):
        done = ask.answered()
        self.assertIn("visibility:Yoru:X:ally", done)
        for k in ("visibility:Yoru:X:enemy", "visibility:Yoru:X:self", "visibility:Yoru:X:drawing"):
            self.assertNotIn(k, done)

    def test_reask_unsure(self):
        done = ask.answered()
        self.assertIn("visibility:Omen:X:enemy", ask.settled(done))
        self.assertNotIn("visibility:Omen:X:enemy", ask.settled(done, reask_unsure=True))
        self.assertIn("visibility:Yoru:X:ally", ask.settled(done, reask_unsure=True))


class SheetColumnsByHeader(unittest.TestCase):
    def test_minimap_cell_found_by_header_name(self):
        text = ("## Omen\n\n| Slot | Extra | Ability | Minimap | Notes |\n|---|---|---|---|---|\n"
                "| X | new column | From the Shadows | icon [domain:abilities/views-separate-per-ability] | n |\n\n"
                "## Yoru\n\n| Slot | Ability | Minimap |\n|---|---|---|\n| C | Fakeout | ? |\n")
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "sheet.md"
            p.write_text(text, encoding="utf-8")
            saved, ask.SHEET = ask.SHEET, p
            try:
                got = ask.sheet_minimap()
            finally:
                ask.SHEET = saved
        self.assertEqual(got, {("Omen", "X"): ("From the Shadows", "icon [domain:abilities/views-separate-per-ability]"),
                               ("Yoru", "C"): ("Fakeout", "?")})


if __name__ == "__main__":
    unittest.main()
