"""The Riot scorer's alignment and coordinate transform, on synthetic data."""
import math
import random
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import riot_ground_truth as rg  # noqa: E402


class AlignmentTest(unittest.TestCase):
    def _synthetic(self, offset_ms, slope=1.0, n=150, drop=0.05, extra=4, seed=7):
        rnd = random.Random(seed)
        game = sorted(rnd.uniform(60_000, 2_300_000) for _ in range(n))
        store = []
        for g in game:
            if rnd.random() < drop:
                continue
            # the feed's 2 Hz grid: the first sample at or after the entry
            t = offset_ms + slope * g + rnd.uniform(0, 300)
            store.append(math.ceil(t / 500.0) * 500.0)
        store += [rnd.uniform(0, 2_400_000) for _ in range(extra)]
        return game, store

    def test_recovers_offset(self):
        game, store = self._synthetic(103_618.0)
        fit = rg.fit_alignment(game, store)
        # the offset absorbs the grid's mean lag, under 500 ms
        self.assertGreater(fit["a_ms"], 103_618.0)
        self.assertLess(fit["a_ms"], 103_618.0 + 500.0)
        self.assertAlmostEqual(fit["slope"], 1.0, delta=1e-4)
        self.assertGreaterEqual(fit["matched"], int(0.93 * len(game)))
        self.assertLess(fit["residual_mad_ms"], 250.0)

    def test_reports_drift(self):
        game, store = self._synthetic(50_000.0, slope=1.0005)
        fit = rg.fit_alignment(game, store, tol_ms=2500.0)
        self.assertAlmostEqual(fit["slope"], 1.0005, delta=1e-4)
        self.assertGreater(abs(fit["drift_ms_over_match"]), 800.0)

    def test_negative_offset(self):
        game, store = self._synthetic(-20_000.0)
        fit = rg.fit_alignment(game, [t for t in store if t > 0])
        self.assertAlmostEqual(fit["a_ms"], -20_000.0 + 250.0, delta=300.0)

    def test_match_is_one_to_one(self):
        pairs = rg.match_times([1000.0, 1100.0], [1050.0], 0.0, 1.0, 500.0)
        self.assertEqual(len(pairs), 1)
        self.assertEqual({j for _i, j, _d in pairs}, {0})


class TransformTest(unittest.TestCase):
    MAP = {"xMultiplier": 7e-05, "yMultiplier": -7e-05,
           "xScalarToAdd": 0.813895, "yScalarToAdd": 0.573242}

    def test_axis_swap(self):
        u, v = rg.game_to_uv(1000.0, 0.0, self.MAP)
        self.assertAlmostEqual(u, 0.813895)
        self.assertAlmostEqual(v, 0.573242 - 0.07)
        u2, v2 = rg.game_to_uv(1000.0, 0.0, self.MAP, swap=False)
        self.assertAlmostEqual(u2, 0.813895 + 0.07)
        self.assertAlmostEqual(v2, 0.573242)

    def test_affine_matches_the_warp(self):
        """`art_affine` lands a dot where `cv2.warpAffine` and `_place` put it."""
        import cv2

        h0, w0 = 300, 260
        fit = (270.0, 0.37, -11, 7)
        art = np.zeros((h0, w0), np.float32)
        ax, ay = 190, 60
        art[ay - 2:ay + 3, ax - 2:ax + 3] = 1.0
        rot, scale, dx, dy = fit
        M = cv2.getRotationMatrix2D((w0 / 2, h0 / 2), rot, scale)
        side = int(max(h0, w0) * scale * 1.6)
        M[0, 2] += side / 2 - w0 / 2
        M[1, 2] += side / 2 - h0 / 2
        r = cv2.warpAffine(art, M, (side, side), flags=cv2.INTER_LINEAR)
        canvas = np.zeros((200, 200), np.float32)
        y0, x0 = max(0, dy), max(0, dx)
        canvas[y0:y0 + side - (y0 - dy), x0:x0 + side - (x0 - dx)] = \
            r[y0 - dy:, x0 - dx:][:200 - y0, :200 - x0]
        ys, xs = np.nonzero(canvas > 0.01)
        wts = canvas[ys, xs]
        cx, cy = float((xs * wts).sum() / wts.sum()), float((ys * wts).sum() / wts.sum())
        px, py = rg.apply(rg.art_affine((h0, w0), fit), ax, ay)
        self.assertAlmostEqual(px, cx, delta=0.3)
        self.assertAlmostEqual(py, cy, delta=0.3)

    def test_map_frame_crop_and_scale(self):
        """A crop shifts the art origin; px per unit follows the fit's scale."""
        mf = rg.MapFrame(self.MAP, (2048, 2048), (0.0, 0.25, 0, 0), crop=(100, 50, 1800, 1900))
        self.assertAlmostEqual(mf.px_per_unit, 7e-05 * 2048 * 0.25, places=6)
        x, y = mf.to_px(0.0, 0.0)
        side = int(1900 * 0.25 * 1.6)
        ex = 0.25 * (0.813895 * 2048 - 0.5 - 100 - 950) + side / 2
        ey = 0.25 * (0.573242 * 2048 - 0.5 - 50 - 900) + side / 2
        self.assertAlmostEqual(x, ex, places=4)
        self.assertAlmostEqual(y, ey, places=4)

    def test_facing_follows_the_transform(self):
        mf = rg.MapFrame(self.MAP, (2048, 2048), (0.0, 0.25, 0, 0))
        # +x in game is -v on the art (yMultiplier < 0): image up, 270 degrees
        self.assertAlmostEqual(mf.facing_deg(0.0, 0.0, 0.0), 270.0, delta=1e-6)
        # +y in game is +u: image right, 0 degrees
        self.assertAlmostEqual(mf.facing_deg(0.0, 0.0, math.pi / 2), 0.0, delta=1e-6)

    def test_angle_err_wraps(self):
        self.assertAlmostEqual(rg.angle_err(359.0, 2.0), 3.0)
        self.assertAlmostEqual(rg.angle_err(90.0, 270.0), 180.0)


class PairsTest(unittest.TestCase):
    def test_greedy_pairs_nearest_first(self):
        pr = rg.greedy_pairs([(0, 0), (10, 0)], [(9, 0), (1, 0), (50, 50)], 5.0)
        self.assertEqual(sorted((i, j) for i, j, _ in pr), [(0, 1), (1, 0)])


if __name__ == "__main__":
    unittest.main()
