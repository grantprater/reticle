import unittest

import numpy as np

from prototypes.minimap_appearance import (RecentAppearanceRecovery,
                                            appearance_similarity, describe,
                                            match_near)


def scene(cx=20, cy=20, size=45):
    yy, xx = np.mgrid[0:size, 0:size]
    grey = np.full((size, size), 80, np.uint8)
    # An asymmetric upright interior whose correct centre is observable.
    icon = ((xx - cx) ** 2 + (yy - cy) ** 2 <= 25)
    grey[icon] = 125
    grey[(yy < cy) & (abs(xx - cx) <= 1) & icon] = 230
    grey[(xx < cx) & (yy > cy) & icon] = 165
    crop = np.repeat(grey[:, :, None], 3, axis=2)
    return crop, np.zeros((size, size), bool)


class DescriptorTests(unittest.TestCase):
    def test_shape_mismatch_is_refused(self):
        crop, colour = scene()
        with self.assertRaises(ValueError):
            describe(crop, colour[:-1], 20, 20, 9,
                     np.zeros(colour.shape), np.zeros(colour.shape))

    def test_identical_descriptors_have_unit_similarity(self):
        crop, colour = scene()
        lo = np.full(colour.shape, 60, np.float32)
        hi = np.full(colour.shape, 100, np.float32)
        d = describe(crop, colour, 20, 20, 9, lo, hi)
        self.assertIsNotNone(d)
        self.assertAlmostEqual(appearance_similarity(d, d, "luma"), 1.0,
                               places=5)
        self.assertAlmostEqual(appearance_similarity(d, d, "residual"), 1.0,
                               places=5)

    def test_local_search_finds_a_shifted_upright_pattern(self):
        anchor_crop, colour = scene(20, 20)
        query_crop, _ = scene(23, 18)
        lo = np.full(colour.shape, 60, np.float32)
        hi = np.full(colour.shape, 100, np.float32)
        exemplar = describe(anchor_crop, colour, 20, 20, 9, lo, hi)
        got = match_near(query_crop, colour, lo, hi, [exemplar], (20, 20),
                         9, 5, mode="residual", support=np.ones_like(colour))
        self.assertIsNotNone(got)
        self.assertEqual((got.x, got.y), (23.0, 18.0))
        self.assertEqual(got.mode, "residual")


class RecoveryTrustTests(unittest.TestCase):
    def test_two_fits_certify_anchor_but_recovery_does_not_seed_itself(self):
        crop0, colour = scene(20, 20)
        crop1, _ = scene(21, 20)
        crop2, _ = scene(22, 20)
        refs = np.full(colour.shape, 80, np.float32)
        recovery = RecentAppearanceRecovery(refs - 20, refs + 20,
                                             np.ones_like(colour))
        recovery.fitted(crop0, colour, {"cx": 20, "cy": 20, "r": 9}, 0)
        self.assertIsNone(recovery.refused(crop1, colour, 16))

        recovery.fitted(crop0, colour, {"cx": 20, "cy": 20, "r": 9}, 32)
        recovery.fitted(crop1, colour, {"cx": 21, "cy": 20, "r": 9}, 48)
        got = recovery.refused(crop2, colour, 64)
        self.assertIsNotNone(got)
        self.assertEqual((got.x, got.y), (22.0, 20.0))

        # The recovery broke the consecutive-fit pair. One new fit alone is
        # therefore insufficient to certify another appearance query.
        recovery.fitted(crop2, colour, {"cx": 22, "cy": 20, "r": 9}, 80)
        self.assertIsNone(recovery.refused(crop2, colour, 96))


if __name__ == "__main__":
    unittest.main()
