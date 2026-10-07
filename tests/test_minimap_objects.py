"""The enemy lane's reader: its stamp, its slab gate, the "?" walk, and the
death owner's X classifier and X births, on synthetic frames."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle import minimap_objects as mo
from reticle.adjudication import death


class StampTests(unittest.TestCase):
    def test_each_fix_is_part_of_the_stamp(self):
        on = mo.minimap_object_version({"teardrop_box": True, "slab_gate": True})
        self.assertEqual(on, f"{mo.MINIMAP_OBJECT_BASE}+teardrop_box+slab_gate")
        stamps = {on, mo.minimap_object_version({"teardrop_box": False, "slab_gate": True}),
                  mo.minimap_object_version({"teardrop_box": True, "slab_gate": False}),
                  mo.minimap_object_version({})}
        self.assertEqual(len(stamps), 4)
        self.assertTrue(mo.minimap_object_version({}).endswith("+nofix"))
        every = mo.minimap_object_version({f: True for f in mo.FIXES})
        self.assertEqual(every, f"{mo.MINIMAP_OBJECT_BASE}+teardrop_box+slab_gate+owner_gate")
        self.assertEqual(mo.minimap_object_version(), every)    # every fix on by default


class GateTests(unittest.TestCase):
    def test_red_off_the_slab_is_dropped_and_no_red_abstains(self):
        red = np.zeros((60, 60), bool)
        slab = np.zeros((60, 60), bool)
        slab[:, :30] = True
        red[18:22, 40:44] = True                 # all of it off the slab
        share, drop = mo._gate({"slab_gate": True}, red, slab, 42, 20, 1.0)
        self.assertEqual(share, 0.0)
        self.assertTrue(drop.startswith("off_slab"))
        self.assertEqual(mo._gate({"slab_gate": False}, red, slab, 42, 20, 1.0), (None, None))
        red[18:22, 10:14] = True
        self.assertEqual(mo._gate({"slab_gate": True}, red, slab, 12, 20, 1.0), (1.0, None))
        self.assertEqual(mo.slab_red_share(red, slab, 12, 50, 1.0), None)     # no red: abstain


def _frame(t, enemies=(), blobs=()):
    return {"kind": "frame", "t_ms": t, "reason": None,
            "enemies": [{"x": x, "y": y} for x, y in enemies],
            "red_blobs": [[20, x, y] for x, y in blobs]}


class LastKnownTests(unittest.TestCase):
    def test_a_red_blob_where_an_icon_ended_is_a_question(self):
        frames = [_frame(1000.0 + 67 * i, enemies=[(100.0, 100.0)]) for i in range(5)]
        t_end = frames[-1]["t_ms"]
        frames += [_frame(t_end + 67 * i, blobs=[(101.0, 100.0), (300.0, 300.0)])
                   for i in range(1, 6)]
        mo.last_known(frames, 1.0)
        last = frames[-1]
        self.assertEqual(len(last["questions"]), 1)
        q = last["questions"][0]
        self.assertEqual((q["icon_last_ms"], q["icon_key"]), (t_end, f"{t_end:.1f}:0"))
        self.assertEqual(last["red_other"][0]["reason"], "no_icon_before")
        self.assertNotIn("red_blobs", last)

    def test_a_run_begun_long_after_the_icon_is_no_question(self):
        frames = [_frame(1000.0, enemies=[(100.0, 100.0)]), _frame(1100.0), _frame(1200.0)]
        frames += [_frame(1300.0 + 67 * i, blobs=[(100.0, 100.0)]) for i in range(3)]
        mo.last_known(frames, 1.0)
        self.assertEqual(frames[-1]["questions"], [])
        self.assertEqual(frames[-1]["red_other"][0]["reason"], "icon_ended_early")


def _crop_with(draw) -> np.ndarray:
    img = np.full((80, 80, 3), 40, np.uint8)
    draw(img)
    return img


class XClassifierTests(unittest.TestCase):
    def test_a_drawn_x_is_an_x_and_a_disc_is_not(self):
        def x(img):
            cv2.line(img, (35, 35), (43, 43), (40, 40, 240), 2)
            cv2.line(img, (43, 35), (35, 43), (40, 40, 240), 2)
        got = death.x_shape(_crop_with(x), "red", 39, 39, 1.0)
        self.assertTrue(got["x"], got)
        disc = _crop_with(lambda img: cv2.circle(img, (39, 39), 6, (40, 40, 240), -1))
        self.assertFalse(death.x_shape(disc, "red", 39, 39, 1.0)["x"])

    def test_a_blue_x_is_read_by_the_same_test(self):
        def x(img):
            cv2.line(img, (35, 35), (43, 43), (240, 160, 40), 2)
            cv2.line(img, (43, 35), (35, 43), (240, 160, 40), 2)
        self.assertTrue(death.x_shape(_crop_with(x), "blue", 39, 39, 1.0)["x"])


class XBirthTests(unittest.TestCase):
    ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 20000.0}]

    def frames(self):
        out = []
        for i in range(150):
            t = 1000.0 + 67.0 * i
            red = [{"x": 100.0, "y": 100.0}] if t >= 5000.0 else []
            red += [{"x": 300.0, "y": 50.0}] if t >= 5300.0 else []
            out.append({"kind": "frame", "t_ms": t, "reason": None,
                        "x_marks": {"blue": [], "red": red}})
        return out

    def test_a_birth_after_an_icon_places_the_death(self):
        def icons_at(side, t):
            return [(100.0, 100.0)] if side == "enemy" and t < 5000.0 else []
        births = death.xmark_births(self.frames(), icons_at, rounds=self.ROUNDS)
        self.assertEqual(len(births), 2)
        used = set()
        b, status = death.match_xmark(births, "enemy", 5100.0, used)
        self.assertEqual((status, b["x"], b["y"]), ("placed", 100.0, 100.0))
        self.assertIsNotNone(b["icon_last_ms"])
        used.add(id(b))
        # The other X follows no icon: it places nothing.
        self.assertEqual(death.match_xmark(births, "enemy", 5400.0, used),
                         (None, "x_without_icon"))
        self.assertEqual(death.match_xmark(births, "ally", 5100.0, set()),
                         (None, "no_x_at_time"))


if __name__ == "__main__":
    unittest.main()
