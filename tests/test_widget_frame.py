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


class TestUnionCaptureBox(unittest.TestCase):
    """One crop holds the widget under every stored placement and never less
    than the profile's ROI (`capture_box_for`)."""

    ROI = [15, 22, 346, 351]
    SHAPE = (329, 331)

    def _segs(self):
        upright = {"affine": wf.identity_affine(self.ROI).tolist()}
        # b3b9defb6fd7's turned half: rotation 180, scale 1, corner (336, 363).
        turned = {"affine": wf.affine(180, 1.0, 1.0, 336 - 330, 363 - 328, self.SHAPE,
                                      (0, 0)).tolist()}
        return upright, turned

    def test_union_covers_both_placements_and_the_profile_roi(self):
        upright, turned = self._segs()
        box = wf.capture_box_for([upright, turned], self.SHAPE, (1920, 1080), self.ROI)
        for seg in (upright, turned):
            one = wf.needed_box([seg], self.SHAPE, (1920, 1080))
            self.assertLessEqual(box[0], one[0])
            self.assertLessEqual(box[1], one[1])
            self.assertGreaterEqual(box[2], one[2])
            self.assertGreaterEqual(box[3], one[3])
        self.assertLessEqual(box[0], self.ROI[0])
        self.assertGreaterEqual(box[3], self.ROI[3])
        # b3b9defb6fd7's dry run named this box.
        self.assertEqual(box, [2, 18, 350, 368])
        floor = np.ones(self.SHAPE, bool)
        for seg in (upright, turned):
            self.assertEqual(wf.clipped_fraction(seg["affine"], floor, box), 0.0)

    def test_the_profile_roi_alone_clips_the_turned_widget(self):
        _, turned = self._segs()
        floor = np.ones(self.SHAPE, bool)
        self.assertGreater(wf.clipped_fraction(turned["affine"], floor, self.ROI), wf.MAX_CLIP)

    def test_a_smaller_widget_keeps_the_profile_crop(self):
        small = {"affine": wf.affine(0, 0.9, 0.9, 20, 30, self.SHAPE, (0, 0)).tolist()}
        box = wf.capture_box_for([small], self.SHAPE, (1920, 1080), self.ROI)
        self.assertEqual(box[:2], self.ROI[:2])
        self.assertEqual(box[2:], self.ROI[2:])


class TestPerSide(unittest.TestCase):
    """A side-based session is never read against the unturned static
    silently: declared or collapsing, it needs a placement first."""

    def _man(self, orientation="per_side", entry=None):
        m = {"session_id": "s1", "source_profile": "valorant-16x9",
             "minimap_mode": {"orientation": orientation}}
        if entry is not None:
            m[wf.MANIFEST_KEY] = entry
        return m

    def test_the_declaration_is_read_from_the_manifest_then_the_profile(self):
        self.assertEqual(wf.declared_orientation(self._man()), "per_side")
        self.assertEqual(wf.declared_orientation(
            {"source_profile": "valorant-16x9-crop75"}), "per_side")
        self.assertEqual(wf.declared_orientation({"source_profile": "valorant-16x9"}),
                         "always_same")

    def test_an_unplaced_per_side_session_is_refused_with_the_command(self):
        why = wf.unplaced_refusal(self._man())
        self.assertIn("per_side_unplaced", why)
        self.assertIn("reticle widget-fit s1 --write", why)
        self.assertIsNone(wf.unplaced_refusal(self._man("always_same")))

    def test_any_stored_placement_answers_it(self):
        roi = [15, 22, 346, 351]
        e = {"baked_roi": roi, "segments": [{"t0_ms": None, "t1_ms": None, "rotation": 0,
                                             "affine": wf.identity_affine(roi).tolist()}]}
        self.assertIsNone(wf.unplaced_refusal(self._man(entry=e)))
        self.assertIsNone(wf.placement_status(None, self._man(entry=e)))
        self.assertIsNone(wf.turned_at(self._man(entry=e)))

    def test_placement_status_names_a_declared_session(self):
        s = wf.placement_status(None, self._man())
        self.assertEqual(s["reason"], "per_side_unplaced")
        self.assertEqual(s["command"], "reticle widget-fit s1 --write")

    def test_turned_at_follows_the_turned_segments(self):
        e = {"baked_roi": [0, 0, 10, 10], "segments": [
            {"t0_ms": None, "t1_ms": 1000.0, "rotation": 180, "affine": [[-1, 0, 9], [0, -1, 9]]},
            {"t0_ms": 1000.0, "t1_ms": None, "rotation": 0, "affine": [[1, 0, 0], [0, 1, 0]]}]}
        turned = wf.turned_at(self._man(entry=e))
        self.assertTrue(turned(0.0))
        self.assertTrue(turned(999.9))
        self.assertFalse(turned(1000.0))
        self.assertFalse(turned(5e6))

    def _rounds(self, n=18, length=100_000.0):
        return [{"round_no": k + 1, "t_start_ms": k * length,
                 "t_end_ms": k * length + 0.9 * length} for k in range(n)]

    def test_a_collapse_at_the_switch_is_found(self):
        rounds = self._rounds()
        t = np.arange(0, 18 * 100_000.0, 500.0)
        drawn = np.where(t < 12 * 100_000.0, True, False)
        drawn[::40] = ~drawn[::40]                   # a little noise both ways
        c = wf.drawn_collapse(t, drawn, rounds)
        self.assertIsNotNone(c)
        self.assertEqual(c["round_no"], 13)
        self.assertGreaterEqual(c["before"], wf.DRAWN_BEFORE_MIN)
        self.assertLessEqual(c["after"], wf.DRAWN_AFTER_MAX)

    def test_a_steady_rate_is_no_collapse(self):
        rounds = self._rounds()
        t = np.arange(0, 18 * 100_000.0, 500.0)
        drawn = np.ones(len(t), bool)
        drawn[::20] = False
        self.assertIsNone(wf.drawn_collapse(t, drawn, rounds))
        # Undrawn time between rounds is not weighed.
        drawn = np.array([(tt % 100_000.0) < 90_000.0 for tt in t])
        self.assertIsNone(wf.drawn_collapse(t, drawn, rounds))

    def test_the_crop_cache_refuses_an_unplaced_per_side_session_by_name(self):
        import json
        import tempfile
        from pathlib import Path

        from reticle.profiles import get_profile
        from reticle.roi_cache import (ROI_CACHE_VERSION, RoiCache, cache_dir, rewrite_command,
                                       roi_rects)
        profile = get_profile("valorant-16x9")
        man = {**self._man(), "source": {"width": 1920, "height": 1080, "content_key": "k"}}
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cd = cache_dir(root, "minimap")
            cd.mkdir(parents=True)
            rec = {"version": ROI_CACHE_VERSION, "roi": "minimap", "profile": profile.name,
                   "content_key": "k", "wh": [1920, 1080], "hz": 15.0, "spans": [[0.0, 1.0]],
                   "rects": roi_rects("minimap", profile, (1920, 1080))}
            (cd / "s1.json").write_text(json.dumps(rec), encoding="utf-8")
            np.save(cd / "s1.idx.npy", np.zeros((0, 5)))
            cache, why = RoiCache.load(root, man, profile, "minimap")
            self.assertIsNone(cache)
            self.assertTrue(why.startswith("per_side_unplaced"))
            raw, why = RoiCache.load(root, man, profile, "minimap", raw=True)
            self.assertIsNotNone(raw, why)
            self.assertEqual(rewrite_command("s1", "minimap", rec),
                             "reticle scan s1 --only roi_cache --cache-roi minimap "
                             "--cache-hz 15 --cache-live")
            # A capture box in the stored placement makes the cache stale by rect.
            roi = [15, 22, 346, 351]
            placed = {**man, wf.MANIFEST_KEY: {
                "baked_roi": roi, "capture_box": [2, 18, 350, 368],
                "segments": [{"t0_ms": None, "t1_ms": None, "rotation": 0,
                              "affine": wf.identity_affine(roi).tolist()}]}}
            self.assertEqual(roi_rects("minimap", profile, (1920, 1080), placed)[0],
                             [2, 18, 350, 368])
            self.assertEqual(RoiCache.load(root, placed, profile, "minimap")[1], "stale_rects")
            # The placement fit reads the narrower cache raw, at the box it holds:
            # the stored box it does not use never refuses it (b3b9defb6fd7).
            raw, why = RoiCache.load(root, placed, profile, "minimap", raw=True)
            self.assertIsNotNone(raw, why)
            self.assertEqual(raw.stored_rect("minimap"), rec["rects"][0])
            self.assertIsNone(raw.widget)
            # A raw read still refuses a cache cut for another profile or size.
            stale = {**placed, "source": {**placed["source"], "width": 1280, "height": 720}}
            self.assertEqual(RoiCache.load(root, stale, profile, "minimap", raw=True)[1],
                             "stale_wh")

    def test_a_raw_read_refuses_a_stale_rect_outside_the_minimap(self):
        from reticle.roi_cache import _raw_rects_ok
        rec = {"roi": "minimap", "rects": [[15, 22, 346, 351]]}
        self.assertTrue(_raw_rects_ok(rec, [[2, 18, 350, 368]]))
        self.assertFalse(_raw_rects_ok({"roi": "killfeed", "rects": [[0, 0, 1, 1]]},
                                       [[0, 0, 2, 2]]))

    def _turn(self, prev_last, first, rot=(180, 0)):
        a = {"t0_ms": None, "t1_ms": first, "rotation": rot[0]}
        b = {"t0_ms": first, "t1_ms": None, "rotation": rot[1],
             "t_prev_last_ms": prev_last, "t_first_ms": first}
        return a, b

    def test_a_turn_starts_at_the_round_it_opens_across_a_cache_gap(self):
        # 4f207c0c4e39: round 13 starts at 1148000 ms; the cache holds nothing
        # from there to 1190000 ms and first reads upright at 1192766.67 ms.
        rounds = [{"round_no": 12, "t_start_ms": 1091000.0, "t_end_ms": 1140500.0},
                  {"round_no": 13, "t_start_ms": 1148000.0, "t_end_ms": 1257500.0},
                  {"round_no": 14, "t_start_ms": 1264500.0, "t_end_ms": 1355000.0}]
        a, b = self._turn(1147216.67, 1192766.67)
        wf.snap_switch(a, b, rounds)
        self.assertEqual((b["t0_ms"], a["t1_ms"], b["switch_round"]), (1148000.0, 1148000.0, 13))
        self.assertNotIn("switch_refusal", b)
        turned = wf.turned_at({wf.MANIFEST_KEY: {"segments": [a, b]}})
        self.assertTrue(turned(1147999.0))
        self.assertFalse(turned(1150000.0))

    def test_a_turn_read_one_hud_sample_before_its_round_start_keeps_its_frame(self):
        # b3b9defb6fd7: turned from 1430216.67 ms, round 13 stored at 1430500 ms.
        rounds = [{"round_no": 12, "t_start_ms": 1358000.0, "t_end_ms": 1423500.0},
                  {"round_no": 13, "t_start_ms": 1430500.0, "t_end_ms": 1524500.0}]
        a, b = self._turn(1430150.0, 1430216.67, rot=(0, 180))
        wf.snap_switch(a, b, rounds)
        self.assertEqual((b["t0_ms"], b["switch_round"]), (1430216.67, 13))

    def test_a_turn_inside_one_round_is_refused(self):
        rounds = [{"round_no": 13, "t_start_ms": 1148000.0, "t_end_ms": 1257500.0}]
        a, b = self._turn(1200000.0, 1210000.0)
        wf.snap_switch(a, b, rounds)
        self.assertIsNone(b["switch_round"])
        self.assertTrue(b["switch_refusal"].startswith("unbracketed: 0"))
        self.assertEqual(b["t0_ms"], 1210000.0)

    def test_a_turn_across_two_round_starts_is_refused(self):
        rounds = [{"round_no": 12, "t_start_ms": 1091000.0, "t_end_ms": 1140500.0},
                  {"round_no": 13, "t_start_ms": 1148000.0, "t_end_ms": 1257500.0}]
        a, b = self._turn(1000000.0, 1192766.67)
        wf.snap_switch(a, b, rounds)
        self.assertIsNone(b["switch_round"])
        self.assertTrue(b["switch_refusal"].startswith("unbracketed: 2"))

    def test_a_change_that_is_not_a_turn_is_refused(self):
        rounds = [{"round_no": 13, "t_start_ms": 1148000.0, "t_end_ms": 1257500.0}]
        a, b = self._turn(1147216.67, 1192766.67, rot=(0, 0))
        wf.snap_switch(a, b, rounds)
        self.assertTrue(b["switch_refusal"].startswith("not_a_turn"))

    def test_round_frames_take_one_cached_time_inside_each_round(self):
        rounds = self._rounds(4)
        ts = np.arange(0, 4 * 100_000.0, 1000.0)
        got = wf.round_frames(ts, rounds)
        self.assertEqual(len(got), 4)
        for r, t in zip(rounds, got):
            self.assertTrue(r["t_start_ms"] <= t < r["t_end_ms"])


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
        self.assertLess(np.hypot(best["cx"] - self.fit0["cx"], best["cy"] - self.fit0["cy"]), 2.0)

    def test_larger_and_rotated(self):
        self._check(180, 1.15, (6, 14))

    def test_larger_upright_and_moved(self):
        self._check(0, 1.18, (3, 20))

    def test_smaller(self):
        self._check(0, 0.90, (40, 30))


if __name__ == "__main__":
    unittest.main()
