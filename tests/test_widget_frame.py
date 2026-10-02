"""The widget placement: fit, identity, clipping, and a synthetic variant.

The synthetic test takes a cached frame of a normal Split session, draws its
widget into a larger canvas at a known scale, rotation and corner, and checks
that the fit recovers the placement and that the normalised crop reads the
same widget and the same self icon as the original.
"""
import unittest

import cv2
import numpy as np

from reticle import widget_frame as wf
from reticle.store import DEFAULT_STORE

SESSION = "bfad2778a372"          # Split at valorant-16x9, a baked-placement match


class TestAffine(unittest.TestCase):
    def test_zero_rotation_unit_scale_is_the_baked_placement(self):
        roi = [15, 22, 346, 351]
        a = wf.affine(0, 1.0, 1.0, 0, 0, (329, 331), (15, 22))
        np.testing.assert_allclose(a, wf.identity_affine(roi))
        self.assertTrue(wf.is_identity(a, roi))

    def test_rotation_maps_corners_to_corners(self):
        a = wf.affine(180, 1.0, 1.0, 0, 0, (10, 20), (0, 0))
        np.testing.assert_allclose(a @ [0, 0, 1], [19, 9])
        np.testing.assert_allclose(a @ [19, 9, 1], [0, 0])

    def test_no_entry_means_no_frame_and_the_standard_cohort(self):
        man = {"session_id": "x", "tags": ["map:split"]}
        self.assertIsNone(wf.for_session(man, [0, 0, 10, 10], DEFAULT_STORE))
        self.assertEqual(wf.cohort(man), "standard")
        self.assertIsNone(wf.capture_box(man))

    def test_an_identity_entry_is_not_a_variant(self):
        roi = [15, 22, 346, 351]
        man = {"session_id": "x", "minimap_widget": {
            "baked_roi": roi, "segments": [{"t0_ms": None, "t1_ms": None,
                                            "affine": wf.identity_affine(roi).tolist()}]}}
        self.assertFalse(wf.is_variant(man))
        self.assertIsNone(wf.for_session(man, roi, DEFAULT_STORE))

    def test_clipped_fraction(self):
        floor = np.zeros((100, 100), bool)
        floor[10:90, 10:90] = True
        ident = wf.identity_affine([0, 0, 100, 100])
        self.assertEqual(wf.clipped_fraction(ident, floor, [0, 0, 100, 100]), 0.0)
        big = wf.affine(0, 1.2, 1.2, 0, 0, (100, 100), (0, 0))
        self.assertGreater(wf.clipped_fraction(big, floor, [0, 0, 100, 100]), wf.MAX_CLIP)


@unittest.skipUnless((DEFAULT_STORE / "manifests" / f"{SESSION}.json").is_file(),
                     "needs the store")
class TestSyntheticVariant(unittest.TestCase):
    """A normal session's widget, redrawn at a known placement, reads back."""

    @classmethod
    def setUpClass(cls):
        from reticle import geometry
        from reticle.minimap import floor_mask, self_icons, widget_drawn
        from reticle.profiles import get_profile
        from reticle.roi_cache import RoiCache
        from reticle.store import Store

        store = Store(DEFAULT_STORE)
        man = store.read_manifest(SESSION)
        cache, why = RoiCache.load(store.root, man, get_profile(man["source_profile"]),
                                   "minimap")
        if cache is None:
            raise unittest.SkipTest(f"no minimap cache: {why}")
        cls.static = geometry.reference_static(SESSION, store.root)
        cls.sgray = cv2.cvtColor(cls.static, cv2.COLOR_BGR2GRAY).astype(np.float64)
        cls.floor = floor_mask(cls.static, sd=geometry.stability(
            SESSION, store.root, cls.static.shape[:2]))
        cls.box = cache.rect_of("minimap")
        x0, y0, x1, y1 = cls.box
        ts = np.unique(cache.t_ms)
        cls.crop = cls.fit0 = None
        for smp in cache.samples([float(t) for t in ts[200:2000:45]], rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            if not widget_drawn(crop, cls.sgray, cls.floor):
                continue
            got = self_icons(crop, cls.floor, require_facing=False)
            if got:
                cls.crop, cls.fit0 = crop, max(got, key=lambda f: f["cov"])
                break
        if cls.crop is None:
            raise unittest.SkipTest("no cached frame with a drawn widget and a self fit")
        cls.widget_drawn, cls.self_icons = staticmethod(widget_drawn), staticmethod(self_icons)

    def _variant(self, rotation, scale, corner):
        """A 1080p frame whose widget is the cached crop at a known placement."""
        h, w = self.crop.shape[:2]
        a = wf.affine(rotation, scale, scale, corner[0], corner[1], (h, w), (0, 0))
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[:] = (40, 60, 50)                       # scenery behind the widget
        warped = cv2.warpAffine(self.crop, a, (1920, 1080), flags=cv2.INTER_LINEAR,
                                borderMode=cv2.BORDER_TRANSPARENT, dst=frame)
        return warped, a

    def _check(self, rotation, scale, corner):
        frame, truth = self._variant(rotation, scale, corner)
        region = frame[:480, :480]
        fit = wf.fit_crop(self.static, region, (0, 0))
        self.assertIsNotNone(fit)
        self.assertEqual(fit["rotation"], rotation)
        self.assertAlmostEqual(fit["scale"], scale, delta=0.01)
        np.testing.assert_allclose(np.asarray(fit["affine"])[:, 2], truth[:, 2], atol=2.0)
        frame_of = wf.WidgetFrame(
            segments=[{"t0_ms": None, "t1_ms": None, "affine": fit["affine"]}],
            baked_roi=list(self.box), shape=self.crop.shape[:2], box=[0, 0, 1920, 1080])
        out = frame_of.normalise(frame, 0.0)
        x0, y0, x1, y1 = self.box
        crop = out[y0:y1, x0:x1]
        self.assertTrue(self.widget_drawn(crop, self.sgray, self.floor))
        got = self.self_icons(crop, self.floor, require_facing=False)
        self.assertTrue(got, "the self icon did not fit on the normalised crop")
        best = max(got, key=lambda f: f["cov"])
        # 2.5 px: ring-fit centres are integer offsets, so a resampled crop's fit
        # may land a pixel off on each axis; the 9 base px centroid search
        # (ally-ring-subpixel-20261001) puts the three variants at 2.0, 2.24 and 1.0 px.
        self.assertLess(np.hypot(best["cx"] - self.fit0["cx"], best["cy"] - self.fit0["cy"]), 2.5)

    def test_larger_and_rotated(self):
        self._check(180, 1.15, (6, 14))

    def test_larger_upright_and_moved(self):
        self._check(0, 1.18, (3, 20))

    def test_smaller(self):
        self._check(0, 0.90, (40, 30))


if __name__ == "__main__":
    unittest.main()
