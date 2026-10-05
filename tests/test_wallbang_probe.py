"""The wallbang probe's (a) test on synthetic lines: solid intervals, surfaces, weapon budgets."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import wallbang_probe as wb  # noqa: E402

try:
    import embreex  # noqa: F401
    import trimesh  # noqa: F401
    HAVE_CASTER = True
except ImportError:
    HAVE_CASTER = False

#: EnergyReductionMultiplier by surface index for these tests: 0 default (1.0),
#: 1 wood (0.333), 2 impenetrable.
ERM = np.array([1.0, 0.333, 100000.0])


class IntervalTest(unittest.TestCase):
    def test_closed_solid_counts_its_path(self):
        ln, op = wb.intervals(np.zeros(2, int), np.array([10.0, 30.0]), np.zeros(2, int),
                              np.array([-1, 1]), np.array([100.0]))
        self.assertEqual(ln.tolist(), [20.0, 0.0])
        self.assertFalse(op.any())

    def test_single_sided_surfaces_add_nothing(self):
        # a leaving crossing with none open, then an entering one never left
        ln, op = wb.intervals(np.zeros(2, int), np.array([5.0, 20.0]), np.zeros(2, int),
                              np.array([1, -1]), np.array([100.0]))
        self.assertEqual(ln.tolist(), [0.0, 0.0])
        self.assertTrue(op.all())

    def test_shells_of_different_meshes_pair_along_the_ray(self):
        # an outer shell entered at 10 and an inner shell left at 40 bound one wall
        ln, _ = wb.intervals(np.zeros(4, int), np.array([10.0, 40.0, 60.0, 65.0]), np.zeros(4, int),
                             np.array([-1, 1, -1, 1]), np.array([100.0]))
        self.assertEqual(ln.tolist(), [30.0, 0.0, 5.0, 0.0])


@unittest.skipUnless(HAVE_CASTER, "embreex and trimesh")
class ThinWallTest(unittest.TestCase):
    def setUp(self):
        def box(c, e):
            return np.asarray(trimesh.creation.box(extents=e).triangles) + np.asarray(c, float)
        self.parts = [box((0, 0, 150), (10, 400, 300)),        # 10 cm, default surface
                      box((0, 1000, 150), (150, 400, 300)),    # 150 cm, default surface
                      box((0, 2000, 150), (10, 400, 300)),     # 10 cm, impenetrable
                      box((0, 3000, 150), (60, 400, 300))]     # 60 cm of wood
        surf = [0, 0, 2, 1]
        self.T = np.concatenate(self.parts).astype(np.float32)
        self.surf = np.concatenate([np.full(len(p), s) for p, s in zip(self.parts, surf)])
        self.c = wb.s3.Caster(self.T)
        ys = (0, 1000, 2000, 3000)
        self.a = np.array([[-500.0, y, 160.0] for y in ys])
        self.b = np.array([[500.0, y, 160.0] for y in ys])

    def test_thin_wall_is_penetrable_and_thick_is_not(self):
        r = wb.classify_line(self.c, self.a, self.b, self.surf, ERM, sdm=1.0, d0=100.0)
        self.assertAlmostEqual(float(r["thick"][0]), 10.0, delta=0.5)
        self.assertTrue(r["penetrable"][0])
        self.assertAlmostEqual(float(r["thick"][1]), 150.0, delta=0.5)
        self.assertFalse(r["penetrable"][1])

    def test_impenetrable_surface_stops_any_weapon(self):
        r = wb.classify_line(self.c, self.a, self.b, self.surf, ERM, sdm=1.5, d0=400.0)
        self.assertTrue(r["impen"][2])
        self.assertFalse(r["penetrable"][2])

    def test_surface_and_weapon_scale_the_budget(self):
        # 60 cm of wood costs 20 effective cm: a 0.5 weapon passes at D0 50, not at D0 25
        r50 = wb.classify_line(self.c, self.a, self.b, self.surf, ERM, sdm=0.5, d0=50.0)
        r25 = wb.classify_line(self.c, self.a, self.b, self.surf, ERM, sdm=0.5, d0=25.0)
        self.assertAlmostEqual(float(r50["cost"][3]), 60.0 * 0.333, delta=0.5)
        self.assertTrue(r50["penetrable"][3])
        self.assertFalse(r25["penetrable"][3])


if __name__ == "__main__":
    unittest.main()
