"""A cone never passes a wall; boxes block by default and report their crossings."""
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import cone
from reticle import occluders as mo
from reticle.minimap import BOXEDGE, FLOOR, VOID


def ring(shape, pts, thickness=1):
    """A closed wall drawn with cv2, 8-connected, as a bool mask."""
    m = np.zeros(shape, np.uint8)
    cv2.polylines(m, [np.array(pts, np.int32)], True, 1, thickness=thickness,
                  lineType=cv2.LINE_8)
    return m > 0


class NeverPassesAWall(unittest.TestCase):
    def test_closed_sealed_wall_holds_every_cone(self):
        rng = np.random.default_rng(20260929)
        shape = (120, 120)
        for trial in range(20):
            # A random polygon, sealed to 4-connected as the builder seals it.
            ang = np.sort(rng.uniform(0, 2 * np.pi, 7))
            rad = rng.uniform(25, 50, 7)
            pts = np.c_[60 + rad * np.cos(ang), 60 + rad * np.sin(ang)]
            wall = mo.seal_diagonals(ring(shape, pts))
            inside = np.zeros(shape, np.uint8)
            cv2.fillPoly(inside, [pts.astype(np.int32)], 1)
            inside = (inside > 0) & ~wall
            floor = np.ones(shape, bool)
            occ = np.where(wall, cone.OCC_WALL, cone.OCC_OPEN).astype(np.uint8)
            p = cone.passable_from(np.zeros(shape, np.uint8), floor, occ)
            ys, xs = np.nonzero(inside)
            for k in rng.choice(len(ys), 5, replace=False):
                for deg in (0.0, 72.0, 144.0, 216.0, 288.0):
                    m = cone.raycast(p, float(xs[k]), float(ys[k]), deg)
                    self.assertFalse((m & ~inside).any(),
                                     f"trial {trial}: a ray left a closed wall")

    def test_a_corner_touching_line_leaks_unless_sealed(self):
        # Why the builder seals: the raycast rounds each step to a pixel and
        # passes between two wall pixels that touch only at a corner.
        shape = (60, 60)
        diag = np.zeros(shape, bool)
        for i in range(60):
            diag[i, 59 - i] = True                      # an 8-connected anti-diagonal
        floor = np.ones(shape, bool)
        yy, xx = np.indices(shape)
        far = (xx + yy) > 59
        leaked = False
        for deg in np.arange(0.0, 90.0, 3.0):
            m = cone.raycast(floor & ~diag, 10.0, 10.0, float(deg), 1.0)
            leaked |= bool((m & far).any())
        self.assertTrue(leaked)
        sealed = mo.seal_diagonals(diag)
        for deg in np.arange(0.0, 90.0, 3.0):
            m = cone.raycast(floor & ~sealed, 10.0, 10.0, float(deg), 1.0)
            self.assertFalse((m & far).any())


class Classes(unittest.TestCase):
    def test_passable_falls_back_to_boxedge_without_occ(self):
        labels = np.full((5, 5), FLOOR, np.uint8)
        labels[2, :] = BOXEDGE
        floor = np.ones((5, 5), bool)
        self.assertFalse(cone.passable_from(labels, floor)[2].any())
        occ = np.zeros((5, 5), np.uint8)
        occ[:, 1] = cone.OCC_WALL
        occ[:, 3] = cone.OCC_BOX
        p = cone.passable_from(labels, floor, occ)
        self.assertTrue(p[2, 0])                        # occ replaces the art's classes
        self.assertFalse(p[:, 1].any())
        self.assertFalse(p[:, 3].any())
        q = cone.passable_from(labels, floor, occ, boxes_block=False)
        self.assertFalse(q[:, 1].any())
        self.assertTrue(q[:, 3].all())

    def test_builder_finds_the_wall_and_the_box(self):
        # A grey floor with a bright white wall across it and a small box
        # drawn as a faint closed outline, on the widget width the constants
        # were measured at.
        h, w = 80, 465                                 # scale 1: the constants as written
        static = np.full((h, w, 3), 117, np.uint8)
        static[:, 50] = 235                             # the wall
        static[20:29, 20] = static[20:29, 28] = 170     # the box outline, faint
        static[20, 20:29] = static[28, 20:29] = 170
        labels = np.full((h, w), FLOOR, np.uint8)
        labels[:2] = labels[-2:] = VOID
        labels[:, :2] = labels[:, -2:] = VOID
        occ, box_id, info = mo.classify(static, labels)
        self.assertTrue((occ[5:75, 50] == mo.WALL).all())
        self.assertEqual(int(occ[24, 24]), mo.BOX)      # the interior is the box
        self.assertTrue((box_id[20:29, 20:29] == box_id[24, 24]).all())
        self.assertEqual(int(occ[60, 30]), mo.OPEN)


class Bake(unittest.TestCase):
    def test_bake_adds_the_table_and_keeps_every_array(self):
        h, w = 60, 465
        static = np.full((h, w, 3), 117, np.uint8)
        static[:, 200] = 235
        labels = np.full((h, w), FLOOR, np.uint8)
        labels[:2] = labels[-2:] = VOID
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "geometry" / "testmap__testprofile.npz"
            p.parent.mkdir()
            np.savez_compressed(p, static=static, labels=labels, built_by=np.array("x"))
            mo.bake("testmap__testprofile", d, write=False)
            with np.load(p) as z:
                self.assertNotIn("occ", z.files)           # a dry run writes nothing
            mo.bake("testmap__testprofile", d)
            with np.load(p) as z:
                self.assertEqual(str(z["occ_built_by"]), mo.occluder_stamp())
                self.assertTrue(np.array_equal(z["static"], static))
                self.assertTrue(np.array_equal(z["labels"], labels))
                self.assertEqual(str(z["built_by"]), "x")
                self.assertTrue((z["occ"][5:55, 200] == mo.WALL).all())


class BoxCrossings(unittest.TestCase):
    def setUp(self):
        self.shape = (41, 61)
        self.box_id = np.zeros(self.shape, np.int16)
        self.box_id[15:26, 30:33] = 7                   # a box ahead of the caster
        self.p = np.ones(self.shape, bool)              # walls none, boxes open

    def test_blocked_equals_the_cast_with_boxes_closed(self):
        blocked, beyond = cone.box_crossings(self.p, self.box_id, 10.0, 20.0, 0.0, 30.0)
        closed = cone.raycast(self.p & (self.box_id == 0), 10.0, 20.0, 0.0, 30.0)
        self.assertTrue(np.array_equal(blocked, closed))
        self.assertEqual(set(beyond), {7})
        self.assertTrue(beyond[7][20, 45])              # behind the box
        self.assertFalse(blocked[20, 45])
        self.assertFalse((beyond[7] & blocked).any())

    def test_the_box_under_the_origin_is_not_crossed(self):
        blocked, beyond = cone.box_crossings(self.p, self.box_id, 31.0, 20.0, 0.0, 30.0)
        self.assertEqual(beyond, {})
        self.assertTrue(blocked[20, 50])


if __name__ == "__main__":
    unittest.main()
