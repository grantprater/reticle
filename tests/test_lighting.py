"""The lit read and the lobe cross-reference, on synthetic geometry.

Synthetic because the point is the CONTRACT -- what refuses, what scales, and
that the lobe is chosen by the light rather than by the ring fit. The real
numbers are in `cone.resolve_lobe`'s docstring and were measured on footage.
"""
import unittest

import numpy as np

from reticle import cone, lighting
from reticle.minimap import FLOOR, VOID


def _z(w=465, h=485, span=60.0, sd=2.0):
    labels = np.full((h, w), FLOOR, np.uint8)
    labels[:20] = VOID
    return {"labels": labels,
            "lo_gray": np.full((h, w), 100.0, np.float32),
            "hi_gray": np.full((h, w), 100.0 + span, np.float32),
            "sd_lo": np.full((h, w), sd, np.float32),
            "sd_hi": np.full((h, w), sd, np.float32),
            "files": ("labels", "lo_gray", "hi_gray", "sd_lo", "sd_hi")}


class Reference(unittest.TestCase):
    def test_missing_arrays_return_none_rather_than_raise(self):
        self.assertIsNone(lighting.reference({"files": ("labels",)}))

    def test_void_is_never_usable(self):
        ref = lighting.reference(_z())
        self.assertFalse(ref.usable[:20].any())
        self.assertTrue(ref.usable[100:].all())

    def test_an_unseparated_pixel_is_refused_not_guessed(self):
        """Two states 1 grey level apart cannot answer, and say so."""
        ref = lighting.reference(_z(span=1.0))
        self.assertEqual(ref.usable.sum(), 0)

    def test_blob_threshold_scales_with_widget_AREA(self):
        big, small = lighting.reference(_z(465, 485)), lighting.reference(_z(331, 329))
        self.assertAlmostEqual(big.scale, 1.0, places=3)
        self.assertLess(small.scale, 0.75)


class LitMask(unittest.TestCase):
    def test_a_dark_frame_is_not_lit(self):
        ref = lighting.reference(_z())
        crop = np.full((485, 465, 3), 100, np.uint8)
        self.assertEqual(lighting.lit_mask(crop, ref).sum(), 0)

    def test_a_bright_frame_is_lit_where_usable(self):
        ref = lighting.reference(_z())
        crop = np.full((485, 465, 3), 160, np.uint8)
        lit = lighting.lit_mask(crop, ref)
        self.assertTrue(lit[100:].all())
        self.assertFalse(lit[:20].any())

    def test_speckle_smaller_than_a_cone_is_dropped(self):
        ref = lighting.reference(_z())
        crop = np.full((485, 465, 3), 100, np.uint8)
        crop[200:204, 200:204] = 160          # 16 px, far under MIN_BLOB_PX
        self.assertEqual(lighting.lit_mask(crop, ref).sum(), 0)


class ResolveLobe(unittest.TestCase):
    def setUp(self):
        self.passable = np.ones((200, 200), bool)

    def test_the_light_picks_the_lobe_the_ring_fit_got_backwards(self):
        lit = np.zeros((200, 200), bool)
        lit[:, 120:] = True                    # light lies to the EAST
        got = cone.resolve_lobe(self.passable, lit,
                                [{"cx": 100.0, "cy": 100.0, "facing": 180.0}])
        self.assertTrue(got[0]["lobe_flipped"])
        self.assertAlmostEqual(got[0]["facing"], 0.0)

    def test_a_bearing_already_right_is_left_alone(self):
        lit = np.zeros((200, 200), bool)
        lit[:, 120:] = True
        got = cone.resolve_lobe(self.passable, lit,
                                [{"cx": 100.0, "cy": 100.0, "facing": 0.0}])
        self.assertFalse(got[0]["lobe_flipped"])
        self.assertAlmostEqual(got[0]["facing"], 0.0)

    def test_no_light_means_no_opinion(self):
        lit = np.zeros((200, 200), bool)
        got = cone.resolve_lobe(self.passable, lit,
                                [{"cx": 100.0, "cy": 100.0, "facing": 33.0}])
        self.assertAlmostEqual(got[0]["facing"], 33.0)
        self.assertNotIn("lobe_flipped", got[0])

    def test_a_refused_bearing_stays_refused(self):
        lit = np.ones((200, 200), bool)
        got = cone.resolve_lobe(self.passable, lit,
                                [{"cx": 100.0, "cy": 100.0, "facing": None}])
        self.assertIsNone(got[0]["facing"])

    def test_the_input_detections_are_not_mutated(self):
        lit = np.zeros((200, 200), bool); lit[:, 120:] = True
        dets = [{"cx": 100.0, "cy": 100.0, "facing": 180.0}]
        cone.resolve_lobe(self.passable, lit, dets)
        self.assertAlmostEqual(dets[0]["facing"], 180.0)


if __name__ == "__main__":
    unittest.main()


class UnlitFill(unittest.TestCase):
    """A pixel never observed unlit still has an unlit level -- from its class."""

    def _z(self, w=200, h=200):
        z = _z(w, h)
        kind = np.ones((h, w), np.int16)            # all FLOOR
        step = np.zeros((h, w), np.int16)
        step[:, 100:] = 2                           # a raised platform
        # the platform never presented two states: lo == hi there
        z["lo_gray"] = z["lo_gray"].copy(); z["hi_gray"] = z["hi_gray"].copy()
        z["lo_gray"][:, 100:] = 150.0
        z["hi_gray"][:, 100:] = 150.0
        z["shade_kind"], z["shade_step"] = kind, step
        z["files"] = z["files"] + ("shade_kind", "shade_step")
        return z

    def test_a_class_with_no_measured_pixel_stays_unknown(self):
        z = self._z()
        ref = lighting.reference(z)
        # step 2 has no measured pixel anywhere, so nothing can be inferred.
        # Rows 0-19 are VOID in the fixture, so only solid rows are asserted on.
        self.assertTrue(ref.unknown[20:, 100:].all())
        self.assertFalse(ref.unknown[20:, :100].any())

    def test_a_class_with_measured_pixels_fills_the_rest(self):
        z = self._z()
        z["lo_gray"][20:40, 100:] = 100.0           # a strip of the platform IS measured
        z["hi_gray"][20:40, 100:] = 160.0
        ref = lighting.reference(z)
        self.assertEqual(ref.unknown.sum(), 0)
        self.assertGreater(ref.known.sum(), ref.usable.sum())

    def test_the_fill_never_overwrites_a_measurement(self):
        z = self._z()
        before = np.asarray(z["lo_gray"]).copy()
        z["lo_gray"][20:40, 100:] = 100.0
        z["hi_gray"][20:40, 100:] = 160.0
        before = np.asarray(z["lo_gray"]).copy()
        ref = lighting.reference(z)
        self.assertTrue(np.allclose(ref.lo[ref.usable], before[ref.usable]))

    def test_interior_holes_are_closed_but_the_mask_stays_inside_known(self):
        z = self._z()
        z["lo_gray"][20:40, 100:] = 100.0
        z["hi_gray"][20:40, 100:] = 160.0
        ref = lighting.reference(z)
        crop = np.full((200, 200, 3), 100, np.uint8)
        crop[40:120, 20:90] = 165                   # a solid lit region...
        crop[70:72, 50:52] = 100                    # ...with a 2 px hole in it
        lit = lighting.lit_mask(crop, ref)
        self.assertTrue(lit[70:72, 50:52].all())    # closed
        self.assertFalse((lit & ~ref.known).any())  # never claims outside known
