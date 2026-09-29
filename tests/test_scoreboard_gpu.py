import os
import sys
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from reticle import scoreboard as sb

try:
    # Imported before any test patches os.environ: cupy records the CUDA
    # toolkit's location there on import, and a restored environment would
    # lose it for the kernels compiled later.
    import cupy  # noqa: F401
except Exception:
    pass


def _icons(rng, names=("A", "B", "C"), sizes=(10, 12)):
    """Agent art as `load_agent_icons` returns it: per scale, BGR and 3-channel mask."""
    out = {}
    for n in names:
        art = rng.integers(0, 256, (16, 16, 3), dtype=np.uint8)
        yy, xx = np.mgrid[:16, :16]
        alpha = ((yy - 7.5) ** 2 + (xx - 7.5) ** 2 < 60).astype(np.uint8)
        ims, masks = [], []
        for s in sizes:
            ims.append(np.ascontiguousarray(cv2.resize(art, (s, s), interpolation=cv2.INTER_AREA)))
            m = cv2.resize(alpha, (s, s), interpolation=cv2.INTER_NEAREST)
            masks.append(np.repeat(m[:, :, None], 3, 2))
        out[n] = (ims, masks)
    return out


class ScorerSelectionTests(unittest.TestCase):
    def test_cpu_mode_names_the_opencv_scorer(self):
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "cpu"}):
            self.assertIsNone(sb._gpu_gallery({}))
            self.assertEqual(sb.portrait_scorer(), "opencv-float32")

    def test_auto_mode_without_cupy_falls_back_to_opencv(self):
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "auto"}), \
                patch.dict(sys.modules, {"cupy": None}):
            self.assertIsNone(sb._gpu_gallery({}))
            self.assertEqual(sb.portrait_scorer(), "opencv-float32")

    def test_gpu_mode_without_cupy_refuses(self):
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "gpu"}), \
                patch.dict(sys.modules, {"cupy": None}):
            with self.assertRaises(ImportError):
                sb._gpu_gallery({})

    def test_unknown_mode_refuses(self):
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "fast"}):
            with self.assertRaises(ValueError):
                sb._gpu_gallery({})

    def test_coverage_row_names_the_scorer(self):
        rd = sb.ScoreboardReader.__new__(sb.ScoreboardReader)
        rd.frames_offered, rd.frames_open, rd.rows, rd.samples = 0, 0, [], []
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "cpu"}):
            head = rd.events("s")[0]
        self.assertEqual(head["portrait_scorer"], "opencv-float32")


class GpuScorerAgreementTests(unittest.TestCase):
    """The GPU scorer reproduces OpenCV's scores to 1e-3 and its best locations."""

    def setUp(self):
        try:
            with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "gpu"}):
                sb._gpu_gallery(None)
        except Exception as exc:  # no cupy or no CUDA device
            self.skipTest(f"GPU scorer unavailable: {exc}")

    def test_scores_and_locations_match_opencv(self):
        rng = np.random.default_rng(3)
        icons = _icons(rng)
        win = rng.integers(0, 256, (24, 26, 3), dtype=np.uint8)
        art = icons["B"][0][1]
        win[5:5 + art.shape[0], 7:7 + art.shape[1]] = art        # B sits at (7, 5)
        win[0:4, 0:4] = 0                                         # a flat patch
        cpu_scores, cpu_where = sb._art_scores_cpu(win, icons)
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "gpu"}):
            gpu_scores, gpu_where = sb._art_scores_gpu(win, sb._gpu_gallery(icons))
        self.assertEqual(set(cpu_scores), set(gpu_scores))
        for name in cpu_scores:
            self.assertAlmostEqual(cpu_scores[name], gpu_scores[name], delta=1e-3)
        self.assertEqual(cpu_where["B"], (1, (7, 5)))
        self.assertEqual(gpu_where["B"], cpu_where["B"])

    def test_art_larger_than_the_window_is_skipped_on_both(self):
        rng = np.random.default_rng(4)
        icons = _icons(rng)
        win = rng.integers(0, 256, (11, 11, 3), dtype=np.uint8)   # fits only scale 10
        _, cpu_where = sb._art_scores_cpu(win, icons)
        with patch.dict(os.environ, {"RETICLE_SCOREBOARD": "gpu"}):
            _, gpu_where = sb._art_scores_gpu(win, sb._gpu_gallery(icons))
        for name in icons:
            self.assertEqual(cpu_where[name][0], 0)
            self.assertEqual(gpu_where[name][0], 0)



class PortraitCacheTests(unittest.TestCase):
    """A reused result equals a fresh score, and only an exact window reuses."""

    def setUp(self):
        rng = np.random.default_rng(5)
        self.icons = _icons(rng)
        self.frame = rng.integers(0, 256, (30, 30, 3), dtype=np.uint8)
        self.box = (5, 5, 19, 19)
        env = patch.dict(os.environ, {"RETICLE_SCOREBOARD": "cpu"})
        env.start()
        self.addCleanup(env.stop)

    def test_a_hit_returns_the_fresh_result(self):
        cache = sb.PortraitCache()
        fresh = sb.portrait_agent(self.frame, self.box, self.icons)
        first = sb.portrait_agent(self.frame, self.box, self.icons, cache)
        again = sb.portrait_agent(self.frame.copy(), self.box, self.icons, cache)
        self.assertEqual(first, fresh)
        self.assertEqual(again, fresh)
        self.assertEqual((cache.hits, cache.misses), (1, 1))

    def test_one_changed_pixel_is_scored_again(self):
        cache = sb.PortraitCache()
        sb.portrait_agent(self.frame, self.box, self.icons, cache)
        other = self.frame.copy()
        other[10, 10, 0] ^= 1
        got = sb.portrait_agent(other, self.box, self.icons, cache)
        self.assertEqual(got, sb.portrait_agent(other, self.box, self.icons))
        self.assertEqual((cache.hits, cache.misses), (0, 2))

    def test_a_caller_cannot_change_what_the_cache_holds(self):
        cache = sb.PortraitCache()
        first = sb.portrait_agent(self.frame, self.box, self.icons, cache)
        first["portrait_agent_scores"]["A"] = 99.0
        again = sb.portrait_agent(self.frame, self.box, self.icons, cache)
        self.assertNotEqual(again["portrait_agent_scores"]["A"], 99.0)

    def test_other_art_and_the_bound(self):
        cache = sb.PortraitCache(size=2)
        for dx in range(3):
            sb.portrait_agent(self.frame, (5 + dx, 5, 19 + dx, 19), self.icons, cache)
        self.assertEqual(len(cache._held), 2)
        sb.portrait_agent(self.frame, (7, 5, 21, 19), self.icons, cache)
        self.assertEqual(cache.hits, 1)
        other_art = _icons(np.random.default_rng(6))
        sb.portrait_agent(self.frame, (7, 5, 21, 19), other_art, cache)
        self.assertEqual((cache.hits, len(cache._held)), (1, 1))


if __name__ == "__main__":
    unittest.main()
