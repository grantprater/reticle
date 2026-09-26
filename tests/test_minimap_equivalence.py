"""Fast paths in `reticle.minimap` against the reference forms they replace."""
import unittest

import numpy as np

from reticle import minimap


class ReachMatchesLoop(unittest.TestCase):
    def test_random_masks(self):
        rng = np.random.default_rng(0)
        for i in range(400):
            h, w = (int(v) for v in rng.integers(20, 90, 2))
            red = (rng.random((h, w)) < rng.random()).astype(np.uint8)
            r = int(rng.integers(3, 15))
            cx = float(rng.uniform(-5, w + 5)) if i % 2 else int(rng.integers(0, w))
            cy = int(rng.integers(-5, h + 5))
            self.assertEqual(minimap._reach(red, cx, cy, r).tobytes(),
                             minimap._reach_loop(red, cx, cy, r).tobytes())


class GatedMatchesIcons(unittest.TestCase):
    def test_gated_from_raw_equals_gated_fit(self):
        rng = np.random.default_rng(1)
        for _ in range(20):
            crop = rng.integers(0, 256, (120, 110, 3), dtype=np.uint8)
            floor = np.ones(crop.shape[:2], bool)
            mask = rng.random(crop.shape[:2]) < 0.2
            raw = minimap.icons(mask, crop, floor, gates=False)
            sc = minimap.widget_scale(crop.shape[1])
            for facing in (True, False):
                self.assertEqual(minimap._gated(raw, sc, require_facing=facing),
                                 minimap.icons(mask, crop, floor, require_facing=facing))


if __name__ == "__main__":
    unittest.main()
