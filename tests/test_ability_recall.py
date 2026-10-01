"""The ability recall scorer (`tools/ability_recall.py`) on synthetic labels."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools import ability_recall as R  # noqa: E402


def frame(i, t, rnd=1):
    return {"index": i, "t_ms": float(t), "round_no": rnd}


def ans(t, answer="marks", marks=()):
    return {"t_ms": float(t), "answer": answer, "marks": [dict(m) for m in marks]}


def mk(x, y, kind="icon", name=None):
    return {"x": x, "y": y, "kind": kind, "name": name}


def icon_row(t, cands, reason=None):
    return {"kind": "frame", "t_ms": float(t), "reason": reason,
            "candidates": [{"cx": x, "cy": y, "r": r} for x, y, r in cands]}


class ClopperPearsonTest(unittest.TestCase):
    def test_the_documents_bound(self):
        # Section 10: 54 of 60 gives a lower bound of 0.81.
        self.assertAlmostEqual(R.cp_lower(54, 60), 0.81, delta=0.005)

    def test_edges(self):
        self.assertIsNone(R.cp_lower(0, 0))
        self.assertEqual(R.cp_lower(0, 10), 0.0)
        # k = n: alpha ** (1 / n).
        self.assertAlmostEqual(R.cp_lower(60, 60), 0.05 ** (1 / 60), places=6)


class ExplainTest(unittest.TestCase):
    def test_icon_ring_and_beam(self):
        icon = {"type": "icon", "cx": 100.0, "cy": 100.0, "r": 5.0}
        self.assertTrue(R.explains(mk(107, 100), icon))        # 7 <= 5 + 3
        self.assertFalse(R.explains(mk(109, 100), icon))
        ring = {"type": "ring", "cx": 200.0, "cy": 200.0, "r": 40.0}
        self.assertTrue(R.explains(mk(209, 200), ring))        # within r / 4 of the centre
        self.assertFalse(R.explains(mk(220, 200), ring))       # inside, off centre and rim
        self.assertTrue(R.explains(mk(242, 200), ring))        # on the rim
        beam = {"type": "beam", "x0": 0.0, "y0": 0.0, "x1": 100.0, "y1": 0.0}
        self.assertTrue(R.explains(mk(50, 2.5), beam))
        self.assertFalse(R.explains(mk(50, 4), beam))
        self.assertFalse(R.explains(mk(105, 0), beam))         # past the end

    def test_proposals_take_accepted_shapes_unless_asked(self):
        shape = {"rings": [{"cx": 1, "cy": 1, "r": 30, "accepted": False},
                           {"cx": 2, "cy": 2, "r": 30, "accepted": True}],
                 "beam": {"x0": 0, "y0": 0, "x1": 9, "y1": 9, "accepted": False}}
        self.assertEqual([p["type"] for p in R.proposals(None, shape)], ["ring"])
        self.assertEqual(len(R.proposals(None, shape, all_shapes=True)), 3)


class EntityTest(unittest.TestCase):
    def test_linking_by_place_kind_round_and_name(self):
        frames = [frame(0, 0), frame(1, 10000), frame(2, 20000), frame(3, 30000, rnd=2)]
        answers = {
            0.0: ans(0, marks=[mk(50, 50), mk(150, 150, "ring")]),
            10000.0: ans(10000, marks=[mk(52, 51), mk(150, 150, "area")]),
            20000.0: ans(20000, marks=[mk(53, 52), mk(90, 90, "line", "Fury")]),
            30000.0: ans(30000, marks=[mk(53, 52), mk(10, 10, "smoke")]),
        }
        answers[0.0]["marks"].append(mk(300, 30, "line", "fury"))
        ents = R.entities(frames, answers)
        sizes = sorted(len(e["marks"]) for e in ents)
        # icon chain over frames 0-2 (3), the named line in one round (2), ring,
        # area, and round 2's icon (1 each); the smoke is no target.
        self.assertEqual(sizes, [1, 1, 1, 2, 3])

    def test_frames_apart_do_not_link(self):
        frames = [frame(0, 0), frame(1, 10000), frame(2, 20000)]
        answers = {0.0: ans(0, marks=[mk(50, 50)]), 10000.0: ans(10000, "nothing"),
                   20000.0: ans(20000, marks=[mk(50, 50)])}
        self.assertEqual(len(R.entities(frames, answers)), 2)


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.frames = [frame(0, 0), frame(1, 10000), frame(2, 20000), frame(3, 30000)]
        self.answers = {
            0.0: ans(0, marks=[mk(50, 50), mk(200, 200), mk(120, 120, "smoke")]),
            10000.0: ans(10000, marks=[mk(51, 50)]),
            20000.0: ans(20000, "nothing"),
            30000.0: ans(30000, "unsure"),
        }
        self.icons = {
            0.0: icon_row(0, [(200, 200, 5), (120, 120, 6), (400, 400, 5)]),
            10000.0: icon_row(10000, [(51, 50, 5)]),
            20000.0: icon_row(20000, [(10, 10, 4), (20, 20, 4)]),
            30000.0: icon_row(30000, [(1, 1, 4)] * 5),
        }

    def test_counts(self):
        s = R.score_session("s", self.frames, self.answers, self.icons, {}, scale=1.0)
        self.assertEqual(s["labelled"], 3)
        self.assertEqual(s["unsure_frames"], 1)
        # Entities: the icon at (50, 50) over frames 0-1 (found on frame 1)
        # and the one at (200, 200) (found); the smoke is no target.
        self.assertEqual((s["entities"], s["found"]), (2, 2))
        self.assertEqual((s["marks"], s["marks_hit"]), (3, 2))
        # The smoke explains its candidate; (400, 400) and both on the
        # nothing frame are unexplained; the unsure frame counts nowhere.
        self.assertEqual(s["unexplained"]["icon"], 3)
        self.assertEqual((s["nothing_frames"], s["nothing_unexplained"]), (1, 2))
        self.assertEqual(s["misses"], [])

    def test_a_miss_is_a_surprise_row_with_its_reason(self):
        answers = dict(self.answers)
        answers[20000.0] = ans(20000, marks=[mk(300, 300, "area", "molly")])
        icons = dict(self.icons)
        icons[20000.0] = {"kind": "frame", "t_ms": 20000.0, "reason": "widget_not_drawn",
                          "candidates": None}
        s = R.score_session("s", self.frames, answers, icons, {}, scale=1.0)
        self.assertEqual((s["entities"], s["found"]), (3, 2))
        (m,) = s["misses"]
        self.assertEqual((m["kind"], m["surprise"], m["t_ms"]), ("surprise", "ability_recall_miss", 20000.0))
        self.assertEqual((m["stream_reason"], m["name"], m["nearest"]), ("widget_not_drawn", "molly", None))

    def test_no_row_is_named(self):
        icons = {k: v for k, v in self.icons.items() if k != 0.0}
        s = R.score_session("s", self.frames, self.answers, icons, {}, scale=1.0)
        self.assertEqual({m["stream_reason"] for m in s["misses"]}, {"no_row"})

    def test_combine_and_bound(self):
        s = R.score_session("s", self.frames, self.answers, self.icons, {}, scale=1.0)
        c = R.combine([s, s])
        self.assertEqual((c["entities"], c["found"]), (4, 4))
        self.assertEqual(c["entity_recall"], 1.0)
        self.assertAlmostEqual(c["entity_recall_lower95"], 0.05 ** 0.25, places=6)
        self.assertAlmostEqual(c["frame_recall"], 2 / 3)
        self.assertAlmostEqual(c["unexplained_per_frame"]["icon"], 1.0)
        self.assertAlmostEqual(c["unexplained_per_nothing_frame"], 2.0)


class AnswersFileTest(unittest.TestCase):
    def test_last_row_for_a_time_wins(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.jsonl"
            p.write_text("\n".join(json.dumps(r) for r in (
                ans(0, marks=[mk(1, 1)]), ans(500, "nothing"), ans(0, "unsure"))) + "\n",
                encoding="utf-8")
            a = R.load_answers(p)
            self.assertEqual(a[0.0]["answer"], "unsure")
            self.assertEqual(len(a), 2)


if __name__ == "__main__":
    unittest.main()
