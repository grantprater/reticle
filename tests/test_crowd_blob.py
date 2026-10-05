"""The blob crowd prototype's pixel tests and scoring rules
(`prototypes/crowd_blob.py`) on synthetic inputs; none is evidence."""
from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import cv2
import numpy as np

from prototypes.crowd_blob import (HOLD, _run, blob_of, disc_offsets, elongation, filled,
                                   score_splits, split_tests, truth_separations)


def discs(centres, R=6.6, shape=(60, 80)):
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    m = np.zeros(shape, np.uint8)
    for x, y in centres:
        m |= (np.hypot(xx - x, yy - y) <= R).astype(np.uint8)
    return m


def blobs_of(m):
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, connectivity=8)
    return SimpleNamespace(lbl=lbl, n=n, box=st[:, :4], area=st[:, 4],
                           cx=cen[:, 0], cy=cen[:, 1])


def px_for(R=6.6, erode_r=0.5):
    r = max(1, int(round(erode_r * R)))
    return SimpleNamespace(shape=SimpleNamespace(r_out=R),
                           erode_k=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,
                                                             (2 * r + 1, 2 * r + 1)))


class Pixels(unittest.TestCase):
    def test_filled_closes_the_portrait_hole(self):
        yy, xx = np.mgrid[0:30, 0:30]
        ring = ((np.hypot(xx - 15, yy - 15) <= 7) & (np.hypot(xx - 15, yy - 15) > 5))
        lbl = ring.astype(np.int32)
        f = filled(lbl, 1)
        self.assertEqual(int(f[15, 15]), 1)
        self.assertGreater(int(f.sum()), int(ring.sum()))

    def test_erosion_parts_the_neck_before_the_discs_part(self):
        px = px_for()
        F = blobs_of(discs([(30, 30), (30 + 1.85 * 6.6, 30)]))      # overlapping: one blob
        self.assertEqual(F.n, 2)
        self.assertGreaterEqual(split_tests(px, F, 1)["erode_pieces"], 2)
        F = blobs_of(discs([(30, 30), (30 + 1.0 * 6.6, 30)]))       # deep overlap
        self.assertEqual(split_tests(px, F, 1)["erode_pieces"], 1)

    def test_elongation_rises_as_discs_part(self):
        e1 = split_tests(px_for(), blobs_of(discs([(30, 30), (36, 30)])), 1)["elong"]
        e2 = split_tests(px_for(), blobs_of(discs([(30, 30), (42, 30)])), 1)["elong"]
        self.assertLess(e1, e2)
        self.assertAlmostEqual(float(elongation(4.0, 1.0, 0.0)), 2.0)

    def test_blob_of_takes_the_nearest_label_within_the_disc(self):
        lbl = np.zeros((20, 20), np.int32)
        lbl[5, 9] = 2
        lbl[5, 12] = 3
        off = disc_offsets(4.0)
        got = blob_of(lbl, np.array([10.0, 13.0, 1.0]), np.array([5.0, 5.0, 18.0]), off)
        self.assertEqual(got.tolist(), [2, 3, 0])


class Detectors(unittest.TestCase):
    def test_run_fires_at_one_frame_and_at_the_hold(self):
        c, ev = {}, []
        for k, cond in enumerate([True] * (HOLD + 1)):
            _run(c, "cc", cond, 100.0 * k, {"crowd": "c"}, ev)
        self.assertEqual([e["detector"] for e in ev], ["cc@1", "cc"])
        self.assertTrue(all(e["t"] == 0.0 for e in ev))      # timed at the run's start
        _run(c, "cc", False, 500.0, {"crowd": "c"}, ev)
        self.assertEqual(c["cc"], (0, None))


class Truth(unittest.TestCase):
    def test_a_held_separation_is_found_once(self):
        n = 30
        t = np.arange(n) * 66.7
        X = np.zeros((n, 2))
        Y = np.zeros((n, 2))
        X[:, 1] = np.where(np.arange(n) < 12, 5.0, 20.0)       # within 2r, then past it
        sep = truth_separations(t, X, Y, 6.0, np.ones(n, int))
        self.assertEqual(len(sep), 1)
        self.assertEqual(sep[0]["q"], 12)
        res = score_splits(sep, [{"kind": "split", "detector": "cc", "t": t[13], "x": 2.0,
                                  "y": 0.0},
                                 {"kind": "split", "detector": "cc", "t": t[13] + 5000,
                                  "x": 2.0, "y": 0.0}], 6.0, 1.0)
        self.assertEqual(res["cc"]["detected"], 1)
        self.assertEqual(res["cc"]["false_events"], 1)
        self.assertTrue(math.isclose(res["cc"]["latency_s"]["median"], 0.067, abs_tol=1e-3))


if __name__ == "__main__":
    unittest.main()
