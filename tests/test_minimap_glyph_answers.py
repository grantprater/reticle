"""The player's texture answers resolve last-row-wins in both readers, so an appended revision supersedes
the row it revises without editing it."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import ask_minimap_glyphs as ask  # noqa: E402
import minimap_glyph_eval as ev  # noqa: E402


def row(key, answer, **kw):
    return dict({"key": key, "kind": "texture", "answer": answer, "unsure": False, "other": None,
                 "by": "player"}, **kw)


class LastRowWins(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "answers.jsonl"
        rows = [row("texture:TX_UI_Minimap_Iris_C", "Miks:E"),
                row("texture:TX_UI_Minimap_Mage_E", "Harbor:Q"),
                row("texture:TX_UI_Minimap_Iris_C", "Miks:C", revises="answers.jsonl#L1")]
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        self.saved = (ev.ANSWERS, ask.ANSWERS)
        ev.ANSWERS = ask.ANSWERS = self.path

    def tearDown(self):
        ev.ANSWERS, ask.ANSWERS = self.saved
        self.tmp.cleanup()

    def test_eval_texture_answers_takes_the_revision(self):
        got = ev.texture_answers()
        self.assertEqual(got["TX_UI_Minimap_Iris_C"][0], 3)
        self.assertEqual(got["TX_UI_Minimap_Iris_C"][1]["answer"], "Miks:C")
        self.assertEqual(got["TX_UI_Minimap_Mage_E"][1]["answer"], "Harbor:Q")

    def test_asking_tool_takes_the_revision(self):
        got = ask.answered()
        self.assertEqual(got["texture:TX_UI_Minimap_Iris_C"]["answer"], "Miks:C")
        self.assertEqual(got["texture:TX_UI_Minimap_Iris_C"]["revises"], "answers.jsonl#L1")


class GameDataReferences(unittest.TestCase):
    """eval 0.3.0: the state inventory's minimap brushes assign markers; the player's answers still override."""

    @classmethod
    def setUpClass(cls):
        ev.build_extra(ev.PROBE_STATES, answers=True, gamedata=True)
        cls.log = dict(ev.GAMEDATA_LOG)
        cls.extra = {k: [p for _, p in v] for k, v in ev.EXTRA.items()}

    def test_alarmbot_takes_its_minimap_brush(self):
        refs = self.extra.get(("Killjoy", "Q"), [])
        self.assertTrue(any(p.startswith("gamedata:TX_UI_Minimap_Killjoy_Q_InActive.png ") for p in refs), refs)

    def test_an_agent_other_answer_removes_a_game_data_reference(self):
        flat = [p for v in self.extra.values() for p in v]
        self.assertFalse(any("TX_UI_Minimap_Rift_Passive_Default.png" in p for p in flat))

    def test_off_reproduces_eval_020(self):
        ev.build_extra(ev.PROBE_STATES, answers=True, gamedata=False)
        refs = [p for _, p in ev.EXTRA.get(("Killjoy", "Q"), [])]
        self.assertFalse(any("Killjoy_Q_InActive" in p for p in refs))
        self.assertEqual(ev.GAMEDATA_LOG, {})


if __name__ == "__main__":
    unittest.main()
