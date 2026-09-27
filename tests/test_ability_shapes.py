"""Parametric minimap ability shapes: a ring round a seed or anywhere, a beam
from the caster, the widened search when the seed is wrong, and refusals."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle import ability_shapes as S

#: Teal in BGR: OpenCV hue 92, saturation 212, value 180.
TEAL = (180, 170, 30)


def _widget() -> np.ndarray:
    img = np.full((329, 331, 3), 40, np.uint8)
    cv2.rectangle(img, (60, 60), (270, 270), (128, 128, 128), -1)
    return img


class RingTest(unittest.TestCase):
    def test_a_regrowth_ring_is_found_round_the_seed(self):
        img = _widget()
        cv2.circle(img, (120, 150), 38, TEAL, 2)
        f = S.fit_shape(img, "Regrowth", (126, 153))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "seeded")
        self.assertLessEqual(np.hypot(f["cx"] - 120, f["cy"] - 150), 2)
        self.assertLessEqual(abs(f["r"] - 38), 1.5)

    def test_a_recon_ring_is_searched_over_the_widget(self):
        img = _widget()
        cv2.circle(img, (200, 110), 57, TEAL, 2)
        f = S.fit_shape(img, "Recon Bolt", (90, 250))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "free")
        self.assertLessEqual(np.hypot(f["cx"] - 200, f["cy"] - 110), 2)

    def test_a_ring_far_from_a_wrong_seed_is_found_widened(self):
        img = _widget()
        cv2.circle(img, (200, 200), 38, TEAL, 2)
        f = S.fit_shape(img, "Regrowth", (90, 90))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "widened")
        self.assertIsNotNone(f["seeded"])

    def test_an_icon_sized_ring_is_not_an_area(self):
        img = _widget()
        cv2.circle(img, (150, 150), 8, TEAL, 2)
        self.assertFalse(S.fit_shape(img, "Regrowth", (150, 150))["found"])


class BeamTest(unittest.TestCase):
    def _fury(self, img, x0=110, y0=220, deg=-60.0, length=120):
        t = np.radians(deg)
        cv2.line(img, (x0, y0), (int(x0 + length * np.cos(t)), int(y0 + length * np.sin(t))),
                 TEAL, 7)

    def test_a_fury_blast_is_found_from_the_caster(self):
        img = _widget()
        self._fury(img)
        f = S.fit_shape(img, "Hunter's Fury", (104, 230))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "seeded")
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 3.0)

    def test_a_wrong_seed_widens_to_the_longest_segment(self):
        img = _widget()
        self._fury(img)
        f = S.fit_shape(img, "Hunter's Fury", (250, 80))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "widened")
        self.assertTrue(f["oriented"])
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 2.0)


class RefusalTest(unittest.TestCase):
    def test_a_bare_widget_finds_nothing(self):
        img = _widget()
        for ability in ("Regrowth", "Recon Bolt", "Hunter's Fury"):
            f = S.fit_shape(img, ability, (150, 150))
            self.assertIs(f["found"], False, ability)
            self.assertIsNotNone(f["reason"], ability)

    def test_teal_off_the_map_is_not_a_shape(self):
        # Teal scenery through the widget, outside the map's footprint.
        img = _widget()
        cv2.line(img, (20, 60), (20, 270), TEAL, 7)
        support = np.zeros(img.shape[:2], bool)
        support[60:271, 60:271] = True
        self.assertTrue(S.fit_shape(img, "Hunter's Fury", None)["found"])
        f = S.fit_shape(img, "Hunter's Fury", None, support)
        self.assertIs(f["found"], False)
        self.assertEqual(f["support"], "art_footprint")
        self.assertEqual(S.fit_shape(img, "Regrowth", None, support[:10])["reason"], "support_shape")
        # A shorter blast on the map is found past the longer line off it.
        BeamTest()._fury(img, length=110)
        f = S.fit_shape(img, "Hunter's Fury", (250, 80), support)
        self.assertTrue(f["found"])
        self.assertGreaterEqual(f["on_map"], S.BEAM_ON_MAP)
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 2.0)

    def test_unread_is_distinct_from_not_found(self):
        self.assertEqual(S.fit_shape(None, "Regrowth", None)["reason"], "no_crop")
        self.assertIsNone(S.fit_shape(None, "Regrowth", None)["found"])
        self.assertEqual(S.fit_shape(_widget(), "Owl Drone", None)["reason"], "no_shape_model")

    def test_every_row_is_stamped(self):
        self.assertEqual(S.fit_shape(_widget(), "Recon Bolt", None)["ability_shape_version"],
                         S.ABILITY_SHAPE_VERSION)


if __name__ == "__main__":
    unittest.main()
