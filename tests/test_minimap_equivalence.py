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

    def test_scaled_march_matches_loop(self):
        rng = np.random.default_rng(2)
        for _ in range(200):
            red = (rng.random((60, 70)) < rng.random()).astype(np.uint8)
            sc = float(rng.uniform(0.5, 2.0))
            r = float(rng.uniform(3, 15))
            cx, cy = float(rng.uniform(0, 70)), float(rng.uniform(0, 60))
            self.assertEqual(minimap._reach(red, cx, cy, r, sc).tobytes(),
                             minimap._reach_loop(red, cx, cy, r, sc).tobytes())


class BestCircleMatchesLoop(unittest.TestCase):
    def test_fractional_radii_and_scaled_search(self):
        rng = np.random.default_rng(3)
        for _ in range(30):
            red = (rng.random((50, 50)) < rng.random()).astype(bool)
            sc = float(rng.uniform(0.6, 1.4))
            g = minimap.ring_geometry(sc)
            cx, cy = float(rng.uniform(10, 40)), float(rng.uniform(10, 40))
            args = (red, cx, cy, g["r_min"], g["r_max"], g["step"], g["search"])
            self.assertEqual(minimap._best_circle(*args), minimap._best_circle_loop(*args))


class RingGeometryScales(unittest.TestCase):
    def test_the_reference_widget_uses_the_base_values(self):
        g = minimap.ring_geometry(1.0)
        self.assertEqual(minimap.ring_radii(g["r_min"], g["r_max"], g["step"]),
                         [float(r) for r in range(minimap.R_MIN, minimap.R_MAX + 1)])
        self.assertEqual((g["search"], g["reach_start"], g["reach_step"]), (9.0, 1.0, 0.7))

    def test_a_small_widget_keeps_its_floor_fractional(self):
        sc = minimap.widget_scale(331)
        g = minimap.ring_geometry(sc)
        rs = minimap.ring_radii(g["r_min"], g["r_max"], g["step"])
        self.assertAlmostEqual(rs[0], minimap.R_MIN * sc)
        self.assertLess(rs[0], 6.0)
        self.assertAlmostEqual(rs[-1], minimap.R_MAX * sc)
        self.assertEqual(len(rs), minimap.R_MAX - minimap.R_MIN + 1)

    def test_an_integer_radius_keeps_its_offsets(self):
        ring, disc = minimap._circle_offsets(9, 9)
        ring_f, disc_f = minimap._circle_offsets(9.0, 9.0)
        self.assertEqual(ring[9].tobytes(), ring_f[9.0].tobytes())
        self.assertEqual(disc[9].tobytes(), disc_f[9.0].tobytes())


class EnemyKeepsTheWholePixelGeometry(unittest.TestCase):
    """The enemy fit keeps the pre-0.8.0 geometry: whole-pixel radii, a 5 px
    search on every widget, an unscaled ray march, a rounded area gate."""

    def test_both_widgets(self):
        for width, radii in ((465, range(8, 14)), (331, range(6, 10))):
            sc = minimap.widget_scale(width)
            g = minimap.enemy_ring_geometry(sc)
            self.assertEqual(minimap.ring_radii(g["r_min"], g["r_max"], g["step"]),
                             [float(r) for r in radii])
            self.assertEqual((g["search"], g["march_sc"]), (5.0, 1.0))
            self.assertEqual(g["min_area"], max(4, int(round(minimap.MIN_ICON_AREA * sc * sc))))

    def test_the_ally_geometry_differs_only_off_the_reference_widget(self):
        a, e = minimap.ring_geometry(1.0), minimap.enemy_ring_geometry(1.0)
        self.assertEqual({k: a[k] for k in a if k != "search"},
                         {k: float(e[k]) for k in e if k != "search"})


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
