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


if __name__ == "__main__":
    unittest.main()
