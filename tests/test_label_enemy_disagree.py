"""The enemy-disagreement labeller's loader and scorer, on synthetic files only."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import label_enemy_disagree as L  # noqa: E402


def _item(sid, st, cls, fi, x, y, w):
    return {"session": sid, "set": st, "cls": cls, "t_cap_ms": 1000.0 * fi, "frame_idx": fi, "round": 1,
            "widget_xy": [x, y], "reader": {"call": "hidden"}, "t1d": {"call": "hidden"}, "weight": w}


def _row(it, answer, count=None):
    return {"key": L.item_key(it), "session": it["session"], "answer": answer, "count": count}


class LoaderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_sample_keys_and_duplicates(self):
        items = [_item("s1", "miss", "a", 10, 1.0, 2.0, 3.0), _item("s1", "extra", "b", 10, 1.0, 2.0, 1.0)]
        p = self.d / "sample.json"
        p.write_text(json.dumps({"items": items}))
        got = L.load_sample(p)
        self.assertEqual([g["key"] for g in got], ["s1|miss|10|1.0|2.0", "s1|extra|10|1.0|2.0"])
        p.write_text(json.dumps({"items": items + [items[0]]}))
        with self.assertRaises(SystemExit):
            L.load_sample(p)

    def test_last_row_wins_across_session_files(self):
        it = _item("s1", "miss", "a", 10, 1.0, 2.0, 3.0)
        it2 = _item("s2", "miss", "a", 11, 1.0, 2.0, 3.0)
        lab = self.d / "labels"
        lab.mkdir()
        (lab / "s1.jsonl").write_text("\n".join(json.dumps(r) for r in
                                                [_row(it, "no_icon"), _row(it, "enemy_icon", "one")]) + "\n\n")
        (lab / "s2.jsonl").write_text(json.dumps(_row(it2, "glyph")) + "\n")
        (lab / "ask.json").write_text("{}")   # not a label file
        got = L.load_answers(lab)
        self.assertEqual(got[L.item_key(it)]["answer"], "enemy_icon")
        self.assertEqual(got[L.item_key(it2)]["answer"], "glyph")
        self.assertEqual(len(got), 2)
        self.assertEqual(L.load_answers(self.d / "missing"), {})

    def test_ask_order_is_fixed_and_a_permutation(self):
        items = [{**_item("s1", "miss", "a", i, 1.0, 2.0, 1.0)} for i in range(20)]
        for it in items:
            it["key"] = L.item_key(it)
        a, b = L.ask_order(items), L.ask_order(list(reversed(items)))
        self.assertEqual([x["key"] for x in a], [x["key"] for x in b])
        self.assertEqual(sorted(x["key"] for x in a), sorted(x["key"] for x in items))

    def test_compose_marks_missing_strip_frames(self):
        crop = np.full((120, 100, 3), 128, np.uint8)
        frames = {dt: (crop if dt in (0.0, 250.0) else None) for dt in L.STRIP_MS}
        img = L.compose(frames, 5.0, 60.0, 5.7, 6.2)   # near the edge: padded, not clipped
        self.assertEqual(img.dtype, np.uint8)
        self.assertGreaterEqual(img.shape[0], (2 * L.ZH + 1) * L.ZF)


class ScoreTests(unittest.TestCase):
    def test_sides_weights_and_exclusions(self):
        items = [
            # miss class "a": icon -> reader wrong (w 3); no_icon -> T1d wrong (w 1); unsure, other out
            _item("s1", "miss", "a", 1, 1.0, 1.0, 3.0),
            _item("s1", "miss", "a", 2, 1.0, 1.0, 1.0),
            _item("s2", "miss", "a", 3, 1.0, 1.0, 1.0),
            _item("s2", "miss", "a", 4, 1.0, 1.0, 1.0),
            _item("s2", "miss", "a", 5, 1.0, 1.0, 1.0),     # unlabelled
            # extra class "b": icon -> T1d wrong; "?" -> reader wrong
            _item("s1", "extra", "b", 6, 1.0, 1.0, 2.0),
            _item("s1", "extra", "b", 7, 1.0, 1.0, 6.0),
        ]
        for it in items:
            it["key"] = L.item_key(it)
        ans = {r["key"]: r for r in [
            _row(items[0], "enemy_icon", "two_or_more"), _row(items[1], "no_icon"),
            _row(items[2], "unsure"), _row(items[3], "other"),
            _row(items[5], "enemy_icon", "one"), _row(items[6], "question")]}
        out = L.score(items, ans)
        a = out["miss__a"]
        self.assertEqual((a["decided"], a["reader_errors"], a["t1d_errors"]), (2, 1, 1))
        self.assertEqual(a["answers"]["unlabelled"], 1)
        self.assertEqual(a["icon_count"], {"two_or_more": 1})
        self.assertAlmostEqual(a["reader_share"], 0.5)
        self.assertAlmostEqual(a["reader_share_w"], 0.75)
        lo, hi = a["reader_ci_w"]
        self.assertTrue(0.0 < lo < 0.75 < hi < 1.0)
        self.assertAlmostEqual(a["n_eff"], 1.6)   # (3+1)^2 / (9+1)
        b = out["extra__b"]
        self.assertEqual((b["reader_errors"], b["t1d_errors"]), (1, 1))
        self.assertAlmostEqual(b["reader_share_w"], 0.75)
        self.assertEqual(out["miss__ALL"]["decided"], 2)
        self.assertNotIn("reader_share", L.score(items, {})["miss__a"])

    def test_every_answer_has_a_side(self):
        for st in ("miss", "extra"):
            for a in list(L.CLASSES.values()) + ["unsure"]:
                self.assertIn(a, L.ERROR_SIDE[st])

    def test_score_cli_on_temp_files(self):
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            items = [_item("s1", "miss", "a", i, 1.0, 1.0, 2.0) for i in range(6)]
            (t / "sample.json").write_text(json.dumps({"items": items}))
            (t / "labels").mkdir()
            (t / "labels" / "s1.jsonl").write_text("".join(
                json.dumps(_row(it, "enemy_icon" if i < 4 else "x_mark", "one" if i < 4 else None)) + "\n"
                for i, it in enumerate(items)))
            rc = L.main(["score", "--sample", str(t / "sample.json"), "--labels", str(t / "labels"),
                         "--out", str(t / "score.json")])
            self.assertEqual(rc, 0)
            got = json.loads((t / "score.json").read_text())["classes"]["miss__a"]
            self.assertEqual((got["reader_errors"], got["t1d_errors"]), (4, 2))

    def test_smoke_refuses_the_store(self):
        with self.assertRaises(SystemExit):
            L.main(["ask", "--smoke", "1"])


if __name__ == "__main__":
    unittest.main()
