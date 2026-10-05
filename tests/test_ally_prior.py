"""The prior-first teammate prototype's pixel helpers and rules
(`prototypes/ally_prior.py`) on synthetic inputs; none is evidence."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

import numpy as np

from prototypes.ally_prior import (SPAWN_MS, Cells, Track, _explain, ring_cover_at,
                                   window_blob)


def ring(shape, cx, cy, r_in=5.0, r_out=6.6):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    d = np.hypot(xx - cx, yy - cy)
    return ((d >= r_in) & (d <= r_out)).astype(np.float32)


def px_for(r_out=6.6):
    return SimpleNamespace(sigma=0.45 * r_out, level={"mask": 0.1},
                           shape=SimpleNamespace(r_out=r_out, r_in=5.0))


class Pixels(unittest.TestCase):
    def test_cells_average_whole_pixel_blocks(self):
        key = np.zeros((40, 40), np.float32)
        key[0:7, 0:7] = 1.0
        c = Cells(key.shape, 6.6)
        self.assertEqual(c.g, 7)
        G = c.of(key)
        self.assertAlmostEqual(float(G[0, 0]), 1.0, places=5)
        self.assertAlmostEqual(float(G[1, 1]), 0.0, places=5)
        near = c.near([3.5], [3.5], 8.0)
        self.assertTrue(near[0, 0] and near[0, 1] and not near[4, 4])

    def test_ring_presence_at_an_icon_and_beside_it(self):
        key = ring((60, 60), 30, 30)
        cov = ring_cover_at(key, [30.0, 45.0], [30.0, 30.0], 5.0, 6.6)
        self.assertGreater(cov[0], 0.9)
        self.assertLess(cov[1], 0.5)

    def test_window_blob_finds_the_crowd_and_its_elongation(self):
        key = np.maximum(ring((80, 100), 40, 40), ring((80, 100), 48, 40))
        b = window_blob(px_for(), key, (10, 10, 90, 70), (44, 40))
        self.assertIsNotNone(b)
        self.assertGreater(b["elong"], 1.0)
        self.assertTrue(30 < b["cx"] < 58)
        self.assertIsNone(window_blob(px_for(), np.zeros((80, 100), np.float32),
                                      (10, 10, 90, 70), (44, 40)))


class Rules(unittest.TestCase):
    def test_prediction_is_capped_at_the_link(self):
        tr = Track("T", 10.0, 10.0, 0.0, "k", 0, "Sage", None, "round_start")
        tr.vx, tr.vy = 100.0, 0.0
        x, y = tr.predict(1000.0, 15.0)
        self.assertAlmostEqual(x, 25.0)
        self.assertAlmostEqual(y, 10.0)

    def test_a_spawn_is_explained_or_counted(self):
        casts = {"ult": [(9000.0, "Omen")], "own": [], "revive": []}
        self.assertEqual(_explain(1000.0, 0, 0, "Sage", "unexplained_teal", [], casts, 0.0)["why"],
                         "round_start")
        self.assertGreater(SPAWN_MS, 1000.0)
        got = _explain(10000.0, 0, 0, "Omen", "unexplained_teal", [], casts, 0.0)
        self.assertEqual(got["why"], "ally_ult_cast")
        self.assertTrue(got["candidate_only"])
        lost = Track("L", 1.0, 1.0, 0.0, "k", 0, "Sage", None, "round_start")
        lost.status, lost.t_conf = "lost", 18000.0
        got = _explain(20000.0, 0, 0, "Sage", "unexplained_teal", [lost], casts, 0.0)
        self.assertEqual(got["why"], "reacquired")
        got = _explain(40000.0, 0, 0, "Jett", "unexplained_teal", [], casts, 0.0)
        self.assertEqual(got["why"], "unexplained")


if __name__ == "__main__":
    unittest.main()
