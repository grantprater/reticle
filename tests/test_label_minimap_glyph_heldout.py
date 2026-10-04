import json
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))

import label_minimap_glyph_heldout as L  # noqa: E402


def cast(sid, t, slot, agent="Omen", ability=None):
    return {"key": f"{sid}:{int(t)}:{slot}", "session_id": sid, "t_cast_ms": float(t), "t_ms": float(t),
            "slot": slot, "agent": agent, "ability": ability or slot}


def vis(key, answer, unsure=False, other=None):
    return {"key": key, "answer": answer, "unsure": unsure, "other": other}


class ScopeTests(unittest.TestCase):
    def test_drawing_key_beats_ally_and_last_sure_row_wins(self):
        d = L.player_drawing([vis("visibility:Omen:Q:ally", "nothing"),
                              vis("visibility:Omen:Q:drawing", "icon"),
                              vis("visibility:Omen:E:ally", "icon"),
                              vis("visibility:Omen:E:ally", "shape"),
                              vis("visibility:Omen:C:ally", None, unsure=True)])
        self.assertEqual(d[("Omen", "Q")][0], "icon")
        self.assertEqual(d[("Omen", "E")][0], "shape")
        self.assertNotIn(("Omen", "C"), d)

    def test_scope_keeps_unanswered_and_drops_nothing_or_shape(self):
        d = {("A", "Q"): ("nothing", None, "k1"), ("A", "E"): ("shape", None, "k2"),
             ("A", "C"): ("icon_and_shape", None, "k3"), ("Gekko", "C"): ("other", "nothing, then", "visibility:Gekko:C:ally")}
        self.assertFalse(L.icon_scope(d, "A", "Q")[0])
        self.assertFalse(L.icon_scope(d, "A", "E")[0])
        self.assertTrue(L.icon_scope(d, "A", "C")[0])
        self.assertTrue(L.icon_scope(d, "A", "X")[0])
        self.assertFalse(L.icon_scope(d, "Gekko", "C")[0])


class PlanTests(unittest.TestCase):
    def setUp(self):
        self.holds = {"s1": np.arange(0, 60000, 66.6667), "s2": np.arange(0, 60000, 66.6667)}
        self.casts = [cast("s1", 5000, "Q"), cast("s1", 5000, "E"), cast("s1", 9000, "X"), cast("s2", 300, "C")]

    def test_offsets_dedupe_control_and_flags(self):
        drawing = {("Omen", "X"): ("nothing", None, "k")}
        items, excl = L.plan_items(self.casts, drawing, self.holds, {"s2": "spectator"}, {"s2"}, {"s1": [6100.0]})
        self.assertEqual([e["key"] for e in excl], ["s1:9000:X"])
        s1 = [it for it in items if it["session_id"] == "s1"]
        # Q and E at the same instant share each offset's sample; one control 1 s before the first cast
        self.assertEqual(len(s1), 3)
        ctl = [it for it in s1 if it["kind"] == "control"]
        self.assertEqual(len(ctl), 1)
        self.assertAlmostEqual(ctl[0]["t_ms"], 4000, delta=40)
        plus1 = [it for it in s1 if abs(it["t_ms"] - 6000) < 40][0]
        self.assertEqual(sorted(o["slot"] for o in plus1["opportunity"]), ["E", "Q"])
        self.assertTrue(plus1["near_tuned_label"])            # 6100 - 6000 lies in [-500, 3500]
        self.assertFalse(ctl[0]["near_tuned_label"])
        s2 = [it for it in items if it["session_id"] == "s2"]
        self.assertTrue(all(it["dev_session"] and it["view_default"] == "spectator" for it in s2))
        self.assertFalse(any(it["kind"] == "control" for it in s2))   # a cast at 0.3 s leaves no control frame
        self.assertEqual(len({it["key"] for it in items}), len(items))


class PassTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        mk = lambda t: {"key": f"s1:{t}", "session_id": "s1", "t_ms": float(t), "agent": "Omen", "kind": "after_cast",
                        "opportunity": [], "view_default": "self", "dev_session": False, "near_tuned_label": False}
        self.items = [mk(1000), mk(2000), mk(3000)]
        self.kits = {"Omen": [{"digit": "1", "slot": "C", "name": "Shrouded Step"},
                              {"digit": "2", "slot": "Q", "name": "Paranoia"}]}

    def tearDown(self):
        self.tmp.cleanup()

    def rows(self):
        return L.read_jsonl(self.dir / "s1.jsonl")

    def test_marks_names_views_and_validation(self):
        p = L.Pass(self.items, self.dir, "test", self.kits)
        self.assertEqual(p.key("space"), "")            # nothing marked: refused
        p.click(10, 20)
        self.assertEqual(p.key("d"), "")                # unnamed mark: refused
        p.click(11, 21)                                 # an unnamed mark moves, it does not stack
        self.assertEqual(len(p.marks), 1)
        p.key("2")
        p.key("x")
        p.click(50, 60)
        p.key("u")                                      # an icon there, ability unsure
        p.click(70, 80)
        self.assertEqual(p.key("7"), "")                # 7 needs text
        p.key("7", "a bot")
        self.assertEqual(p.key("n"), "")                # N with marks: refused
        self.assertEqual(p.key("space"), "advance")
        r = self.rows()[0]
        self.assertEqual([m["ability"] for m in r["marks"]], ["Omen:Q", None, "other"])
        self.assertEqual(r["marks"][0]["view"], "teammate")
        self.assertEqual(r["marks"][0]["view_source"], "player")
        self.assertEqual(r["marks"][1]["view_source"], "manifest_tag")
        self.assertTrue(r["marks"][1]["unsure"])
        self.assertEqual(r["marks"][2]["other"], "a bot")
        self.assertEqual(r["split"], "heldout")
        self.assertFalse(r["compared_against_derived"])

    def test_nothing_unsure_back_and_resume(self):
        p = L.Pass(self.items, self.dir, "test", self.kits)
        self.assertEqual(p.key("n"), "advance")
        self.assertEqual(p.key("u"), "advance")         # no marks: whole item unsure
        self.assertEqual(p.key("a"), "back")
        p.click(5, 5)
        p.undo()
        self.assertEqual(p.key("n"), "advance")         # re-answer item 2; the last row wins
        self.assertEqual(p.key("q"), "quit")
        done = L.answered(self.dir)
        self.assertTrue(done["s1:1000"]["nothing"])
        self.assertTrue(done["s1:2000"]["nothing"])
        self.assertFalse(done["s1:2000"]["unsure"])
        p2 = L.Pass(self.items, self.dir, "test", self.kits)
        self.assertEqual([it["key"] for it in p2.todo], ["s1:3000"])

    def test_headless_runner_uses_the_same_path(self):
        p = L.Pass(self.items, self.dir, "test", self.kits)
        L.run_headless(p, [["click", 3, 4], ["key", "1"], ["key", "space"], ["key", "n"], ["key", "q"]])
        rows = self.rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["marks"][0]["ability"], "Omen:C")
        self.assertTrue(rows[1]["nothing"])
        self.assertEqual(json.loads(json.dumps(rows[0]))["coords"], "minimap roi pixels")


if __name__ == "__main__":
    unittest.main()
