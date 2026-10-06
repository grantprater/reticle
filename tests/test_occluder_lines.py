"""occluders-2.0.0: the baked line classes decide which lines occlude, and box heights come from hints."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import cone
from reticle import occluders as mo
from reticle.minimap import FLOOR, VOID


def scene():
    """A 465 px widget: a bright wall at x 50, a faint box outline, a bright ramp line at x 300."""
    h, w = 80, 465
    static = np.full((h, w, 3), 117, np.uint8)
    static[:, 50] = 235                              # the wall
    static[20:29, 20] = static[20:29, 28] = 170      # the box outline, faint
    static[20, 20:29] = static[28, 20:29] = 170
    static[10:70, 300] = 235                         # a line the sorter calls a ramp
    labels = np.full((h, w), FLOOR, np.uint8)
    labels[:2] = labels[-2:] = VOID
    labels[:, :2] = labels[:, -2:] = VOID
    return static, labels


def classes(static, labels):
    line = mo.line_mask(static, labels)
    cls = np.where(line, mo.LINE_WALL, mo.LINE_NONE).astype(np.uint8)
    cls[line & (np.arange(line.shape[1])[None, :] < 40)] = mo.LINE_BOX
    cls[line & (np.arange(line.shape[1])[None, :] > 250)] = mo.LINE_RAMP
    return cls


class ApplyLines(unittest.TestCase):
    def test_a_ramp_line_stops_nothing_and_walls_and_boxes_stay(self):
        static, labels = scene()
        occ, box_id, _ = mo.classify(static, labels)
        self.assertTrue((occ[15:65, 300] == mo.WALL).all())      # occluders-1 walls the ramp line
        new, bid, height, info = mo.apply_lines(occ, box_id, classes(static, labels))
        self.assertFalse((new[:, 300] > 0).any())
        self.assertTrue((new[5:75, 50] == mo.WALL).all())
        self.assertEqual(int(new[24, 24]), mo.BOX)                # the box keeps its fill
        self.assertTrue((bid[20:29, 20:29] == bid[24, 24]).all())
        self.assertEqual(int(height[24, 24]), mo.H_UNKNOWN)       # no hint: unknown, never a guess
        floor = np.ones(occ.shape, bool)
        lit = cone.raycast(cone.passable_from(labels, floor, new), 280.0, 40.0, 0.0, 10.0)
        self.assertTrue(lit[40, 320])                             # light crosses the ramp line
        self.assertGreater(info["opened_line_px"], 0)

    def test_art_wall_beside_an_open_line_is_cleared(self):
        static, labels = scene()
        occ, box_id, _ = mo.classify(static, labels)
        occ[10:70, 301] = mo.WALL                                 # an art wall hugging the ramp line
        new, _, _, info = mo.apply_lines(occ, box_id, classes(static, labels))
        self.assertFalse((new[10:70, 301] > 0).any())
        self.assertGreater(info["cleared_ring_px"], 0)

    def test_heights_come_only_from_hints(self):
        static, labels = scene()
        occ, box_id, _ = mo.classify(static, labels)
        cls = classes(static, labels)
        seg = {"id": "note:x", "kind": "segment", "class": "tall", "px": [[20, 22], [20, 23]], "source": "t"}
        _, bid, height, info = mo.apply_lines(occ, box_id, cls, [seg])
        self.assertEqual(int(height[24, 24]), mo.H_TALL)
        self.assertEqual(info["named_boxes"], {int(bid[24, 24]): "tall"})
        bb = {"id": "heights:y", "kind": "bbox", "class": "short", "bbox": [18, 18, 30, 30], "source": "t"}
        _, _, height2, _ = mo.apply_lines(occ, box_id, cls, [bb])
        self.assertEqual(int(height2[24, 24]), mo.H_SHORT)
        _, _, height3, info3 = mo.apply_lines(occ, box_id, cls, [seg, bb])
        self.assertEqual(int(height3[24, 24]), mo.H_UNKNOWN)      # hints that disagree name nothing
        self.assertIn("reason", info3["boxes"][0] if info3["boxes"][0]["id"] == int(bid[24, 24])
                      else next(b for b in info3["boxes"] if b["id"] == int(bid[24, 24])))


class BakeLines(unittest.TestCase):
    def _npz(self, d, **extra):
        static, labels = scene()
        p = Path(d) / "geometry" / "testmap__testprofile.npz"
        p.parent.mkdir(exist_ok=True)
        np.savez_compressed(p, static=static, labels=labels, built_by=np.array("x"), **extra)
        return p, static, labels

    def test_bake_applies_current_lines_and_records_them(self):
        with tempfile.TemporaryDirectory() as d:
            static, labels = scene()
            p, static, labels = self._npz(d, line_cls=classes(static, labels),
                                          lines_static_sha=np.array(mo.static_sha(static)),
                                          lines_built_by=np.array("L1"), line_hints=np.array("[]"),
                                          lines_meta=np.array(json.dumps({"validation": {"status": "labels"}})))
            info = mo.bake("testmap__testprofile", d, path=p)
            self.assertEqual(info["occ_lines"], "L1")
            with np.load(p) as z:
                self.assertFalse((z["occ"][:, 300] > 0).any())
                self.assertEqual(str(z["occ_lines"]), "L1")
                self.assertEqual(str(z["occ_validation"]), "labels")
                self.assertEqual(str(z["occ_version"]), mo.OCCLUDER_VERSION)
                self.assertIn("box_height", z.files)
                self.assertTrue(np.array_equal(z["static"], static))

    def test_stale_or_absent_lines_keep_the_old_rule_and_say_why(self):
        with tempfile.TemporaryDirectory() as d:
            static, labels = scene()
            p, _, _ = self._npz(d, line_cls=classes(static, labels),
                                lines_static_sha=np.array("another static"), lines_built_by=np.array("L1"))
            info = mo.bake("testmap__testprofile", d, path=p)
            self.assertTrue(info["occ_lines"].startswith("stale:"))
            with np.load(p) as z:
                self.assertTrue((z["occ"][15:65, 300] == mo.WALL).all())
        with tempfile.TemporaryDirectory() as d:
            p, _, _ = self._npz(d)
            self.assertTrue(mo.bake("testmap__testprofile", d, path=p)["occ_lines"].startswith("absent:"))
        with tempfile.TemporaryDirectory() as d:
            p, _, _ = self._npz(d, lines_refused=np.array("most walls opened"))
            self.assertTrue(mo.bake("testmap__testprofile", d, path=p)["occ_lines"].startswith("refused:"))


class Shapes(unittest.TestCase):
    """occluders-2.1.0: boxes fitted from the art's shading, and door leaves in a wall's gap."""

    def test_a_raised_region_drawn_by_one_line_is_a_whole_box(self):
        h, w = 60, 465
        labels = np.full((h, w), FLOOR, np.uint8)
        kind = np.full((h, w), mo.KIND_FLOOR, np.uint8)
        step = np.ones((h, w), np.uint8)
        step[20:32, 20:40] = 2                                    # a box top, a rung above the floor
        line = np.zeros((h, w), bool)
        line[19, 19:41] = True                                    # drawn by its top line only
        boxes = mo.raised_boxes(labels, kind, step, line)
        self.assertEqual(len(boxes), 1)
        b = boxes[0]
        self.assertTrue(b["mask"][20:32, 20:40].all())            # its extent is the shading's
        self.assertTrue(b["partly_drawn"])
        self.assertFalse(b["diagonal"] or b["non_rectangular"])
        kind[20:32, 41] = mo.KIND_RAMP                            # a ramp beside it: elevation
        self.assertEqual(mo.raised_boxes(labels, kind, step, line), [])

    def test_a_t_shaped_region_is_non_rectangular(self):
        h, w = 60, 465
        labels = np.full((h, w), FLOOR, np.uint8)
        kind = np.full((h, w), mo.KIND_FLOOR, np.uint8)
        step = np.ones((h, w), np.uint8)
        step[10:18, 10:40] = 2
        step[18:34, 20:30] = 2
        line = mo._ring(step == 2, 1)
        (b,) = mo.raised_boxes(labels, kind, step, line)
        self.assertTrue(b["non_rectangular"])

    def test_a_diagonal_leaf_in_a_wall_gap_is_a_door_and_an_open_gap_is_not(self):
        h, w = 60, 465
        static = np.full((h, w, 3), 117, np.uint8)
        labels = np.full((h, w), FLOOR, np.uint8)
        static[30, 10:40] = 235                                   # wall, gap 40..51, wall
        static[30, 52:90] = 235
        self.assertEqual(mo.doorways(static, labels), [])         # an open doorway draws nothing
        for i in range(6):                                        # a leaf hinged at the left stub
            static[29 - i // 2, 41 + i] = 165
        (d,) = mo.doorways(static, labels)
        self.assertTrue(d["mask"][29, 41])
        self.assertGreaterEqual(d["angle_off_axis"], mo.DIAGONAL_DEG)

    def test_a_shape_becomes_one_box_and_never_overwrites_a_wall(self):
        static, labels = scene()
        occ, box_id, _ = mo.classify(static, labels)
        m = np.zeros(occ.shape, bool)
        m[40:50, 45:60] = True                                    # overlaps the wall at x 50
        shape = {"drawn": "raised", "mask": m, "edge": np.zeros(occ.shape, bool)}
        new, bid, height, info = mo.apply_lines(occ, box_id, classes(static, labels), (), [shape])
        self.assertTrue((new[40:50, 50] == mo.WALL).all())
        self.assertTrue((new[40:50, 45:50] == mo.BOX).all())
        self.assertEqual(len({int(v) for v in bid[m & (new == mo.BOX)]}), 1)
        self.assertEqual(int(height[45, 55]), mo.H_UNKNOWN)
        self.assertEqual(len(info["shapes"]), 1)


if __name__ == "__main__":
    unittest.main()
