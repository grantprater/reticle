"""Ally icon descriptors and the per-frame naming of teammates."""
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from reticle.adjudication.identity import (claims_from_ally_icons, rendered_art_fit,
                                           rendered_art_scores, teammate_fit_refusal)
from reticle.minimap import (ALLY_MAP_DIFF_MIN, AllyIconReader,
                             ally_icon_descriptors)
from reticle.version import ALLY_PORTRAIT_FEATURES_VERSION

#: The reference widget width, so the icon gates are unscaled.
W = 465

#: Four teammates whose portraits are one colour bin each.
GALLERY = {name: [np.eye(4, dtype=np.float32)[i]]
           for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}


def _lineup(ally=("Phoenix", "Breach", "Deadlock", "Reyna", "Miks"), player="Phoenix"):
    rows = [{"slot": i, "agent": a, "best_guess": a} for i, a in enumerate(ally)]
    return {"sides": {"ally": rows}, "player": {"agent": player} if player else None}


def _icon(frame, index, comp, reason=None, features=None):
    return {"frame_idx": frame, "t_ms": frame * 500.0, "index": index,
            "observation_key": f"s:{frame}:{index}", "cx": 10.0, "cy": 10.0, "r": 8,
            "composition": comp, "reason": reason, "portrait_features": features,
            "portrait_features_version": ALLY_PORTRAIT_FEATURES_VERSION if features else None}


def _features(i):
    """Portrait features equal to agent `i`'s reference in `_references`."""
    return {"grid3_lab": [float(i)] * 2, "hog_x1": [float(i)], "prof_h": [0.0]}


def _references():
    names = ["Breach", "Deadlock", "Miks", "Reyna"]
    return {"version": "t", "features_version": ALLY_PORTRAIT_FEATURES_VERSION,
            "margin_min": 0.5,
            "variance": {"grid3_lab": [1.0, 1.0], "hog_x1": [1.0], "prof_h": [1.0]},
            "agents": {n: _features(i) for i, n in enumerate(names)}}


def _one_hot(i, w=0.9):
    v = np.full(4, (1 - w) / 3, np.float32)
    v[i] = w
    return v.tolist()


class ClaimsFromAllyIconsTests(unittest.TestCase):
    def test_a_frames_icons_are_named_as_distinct_teammates(self):
        icons = [_icon(1, 0, _one_hot(0)), _icon(1, 1, _one_hot(3))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s")
        self.assertEqual([c["agent"] for c in claims], ["Breach", "Reyna"])
        self.assertEqual(claims[0]["entity_id"], "s:ally_icon:s:1:0")
        self.assertEqual(claims[0]["channel"], "minimap_portrait")
        self.assertNotIn("Phoenix", claims[0]["evidence"]["candidates"])

    def test_two_icons_with_the_same_best_match_cannot_both_take_it(self):
        icons = [_icon(1, 0, _one_hot(0, 0.9)), _icon(1, 1, _one_hot(0, 0.8))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s")
        named = [c["agent"] for c in claims if c["agent"]]
        self.assertEqual(len(named), len(set(named)))

    def test_rendered_art_names_icons_that_carry_portrait_features(self):
        refs = _references()
        icons = [_icon(1, 0, _one_hot(3), features=_features(0)),
                 _icon(1, 1, _one_hot(0), features=_features(3))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s", references=refs)
        # The features, not the contradicting composition, decide.
        self.assertEqual([c["agent"] for c in claims], ["Breach", "Reyna"])
        self.assertEqual({c["evidence"]["reference_source"] for c in claims},
                         {"rendered_art"})
        self.assertEqual(claims[0]["evidence"]["margin_min"], refs["margin_min"])

    def test_a_frame_without_features_falls_back_to_the_composition(self):
        icons = [_icon(1, 0, _one_hot(0), features=_features(3)),
                 _icon(1, 1, _one_hot(3))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s", references=_references())
        self.assertEqual([c["agent"] for c in claims], ["Breach", "Reyna"])
        self.assertEqual({c["evidence"]["reference_source"] for c in claims},
                         {"official_art"})

    def test_a_name_without_a_rendered_reference_is_not_scored_short(self):
        refs = _references()
        del refs["agents"]["Miks"]
        self.assertIsNone(rendered_art_scores(_features(0), ["Breach", "Miks"], refs))

    def test_an_icon_records_its_absolute_fit_to_the_closest_teammate(self):
        refs = _references()
        far = {"grid3_lab": [9.0, 9.0], "hog_x1": [9.0], "prof_h": [0.0]}
        self.assertEqual(rendered_art_fit(_features(1), ["Breach", "Deadlock"], refs),
                         (0.0, "Deadlock"))
        fit, agent = rendered_art_fit(far, ["Breach", "Deadlock"], refs)
        self.assertEqual(agent, "Deadlock")
        self.assertAlmostEqual(fit, (64.0 + 64.0 + 0.0) / 3)
        icons = [_icon(1, 0, _one_hot(0), features=_features(0))]
        (claim,) = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                          session_id="s", references=refs)
        self.assertEqual((claim["evidence"]["fit"], claim["evidence"]["fit_agent"]),
                         (0.0, "Breach"))

    def test_a_piece_that_fits_no_teammate_is_refused(self):
        table = {"fit_max": 2.0}
        reason, fit = teammate_fit_refusal([3.0, 5.0, None, 1.0], table)
        self.assertEqual(fit, 3.0)
        self.assertTrue(reason.startswith("not_a_teammate"))
        self.assertEqual(teammate_fit_refusal([1.0, 1.5], table), (None, 1.25))
        # No fitted table or no read fit: the test is not applied.
        self.assertEqual(teammate_fit_refusal([9.0], None), (None, None))
        self.assertEqual(teammate_fit_refusal([None], table), (None, None))

    def test_a_stored_refusal_is_quoted(self):
        icons = [_icon(1, 0, _one_hot(0), reason="interior_is_map")]
        (claim,) = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "interior_is_map")

    def test_an_unknown_player_refuses_every_icon(self):
        icons = [_icon(1, 0, _one_hot(0))]
        (claim,) = claims_from_ally_icons(icons, _lineup(player=None),
                                          gallery=GALLERY, session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "player_unknown")

    def test_a_refused_slot_is_a_rival_and_never_a_name(self):
        lineup = _lineup()
        lineup["sides"]["ally"][4] = {"slot": 4, "agent": None, "best_guess": "Miks"}
        icons = [_icon(1, 0, _one_hot(2))]
        (claim,) = claims_from_ally_icons(icons, lineup, gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertIn("refused_slot", claim["reason"])

    def test_a_blind_slot_refuses_the_side(self):
        lineup = _lineup()
        lineup["sides"]["ally"][4] = {"slot": 4, "agent": None, "best_guess": None}
        icons = [_icon(1, 0, _one_hot(0))]
        (claim,) = claims_from_ally_icons(icons, lineup, gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertTrue(claim["reason"].startswith("lineup_incomplete"))


class ClaimsFromEnemyIconsTests(unittest.TestCase):
    """`side="enemy"`: the ally rule over the enemy side's five."""

    @staticmethod
    def _lineup(enemy=("Breach", "Deadlock", "Miks", "Reyna", "Phoenix")):
        lu = _lineup()
        lu["sides"]["enemy"] = [{"slot": i, "agent": a, "best_guess": a}
                                for i, a in enumerate(enemy)]
        return lu

    def test_enemy_icons_are_named_from_the_enemy_five(self):
        refs = _references()
        refs["agents"]["Phoenix"] = {"grid3_lab": [7.0, 7.0], "hog_x1": [7.0], "prof_h": [0.0]}
        icons = [_icon(1, 0, None, features=_features(0)),
                 _icon(1, 1, None, features=_features(3))]
        claims = claims_from_ally_icons(icons, self._lineup(), gallery=GALLERY,
                                        session_id="s", references=refs, side="enemy")
        self.assertEqual([c["agent"] for c in claims], ["Breach", "Reyna"])
        self.assertEqual(claims[0]["entity_id"], "s:enemy_icon:s:1:0")
        # The player's agent is not removed from the enemy side.
        self.assertIn("Phoenix", claims[0]["evidence"]["candidates"])

    def test_enemy_side_needs_no_player_but_a_complete_five(self):
        lu = self._lineup()
        lu["player"] = None
        lu["sides"]["enemy"] = lu["sides"]["enemy"][:4]
        (claim,) = claims_from_ally_icons([_icon(1, 0, _one_hot(0))], lu, gallery=GALLERY,
                                          session_id="s", side="enemy")
        self.assertIsNone(claim["agent"])
        self.assertTrue(claim["reason"].startswith("lineup_incomplete: 4 of 5 enemies"))

    def test_the_ally_default_is_unchanged(self):
        icons = [_icon(1, 0, _one_hot(0)), _icon(1, 1, _one_hot(3))]
        a = claims_from_ally_icons(icons, self._lineup(), gallery=GALLERY, session_id="s")
        b = claims_from_ally_icons(icons, self._lineup(), gallery=GALLERY, session_id="s",
                                   side="ally")
        self.assertEqual(a, b)
        self.assertNotIn("Phoenix", a[0]["evidence"]["candidates"])

    def test_an_unknown_side_is_an_error(self):
        with self.assertRaises(ValueError):
            claims_from_ally_icons([], _lineup(), gallery=GALLERY, session_id="s",
                                   side="self")


def _ally_icon_crop(portrait_bgr):
    """A grey widget holding one teal teardrop around a portrait disc."""
    crop = np.full((W, W, 3), 128, np.uint8)
    cv2.circle(crop, (60, 60), 10, (200, 220, 40), 3)      # teal ring
    tri = np.array([[60, 44], [55, 51], [65, 51]], np.int32)
    cv2.fillPoly(crop, [tri], (200, 220, 40))              # the facing lobe
    cv2.circle(crop, (60, 60), 7, portrait_bgr, -1)
    return crop


class AllyIconDescriptorTests(unittest.TestCase):
    def setUp(self):
        self.floor = np.ones((W, W), bool)
        self.static = np.full((W, W, 3), 128, np.uint8)

    def test_a_portrait_is_described(self):
        crop = _ally_icon_crop((30, 60, 200))
        got = ally_icon_descriptors(crop, self.floor, static=self.static)
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["reason"])
        self.assertGreater(got[0]["map_diff"], ALLY_MAP_DIFF_MIN)
        self.assertAlmostEqual(sum(got[0]["composition"]), 1.0, places=4)

    def test_an_interior_that_is_the_map_is_refused(self):
        crop = _ally_icon_crop((128, 128, 128))
        got = ally_icon_descriptors(crop, self.floor, static=self.static)
        self.assertEqual([g["reason"] for g in got], ["interior_is_map"])

    def test_an_occluder_removes_its_pixels(self):
        crop = _ally_icon_crop((30, 60, 200))
        full = ally_icon_descriptors(crop, self.floor, static=self.static)[0]
        part = ally_icon_descriptors(crop, self.floor, static=self.static,
                                     occluders=[(66, 60, 4)])[0]
        self.assertLess(part["pixels"], full["pixels"])

    def test_the_reader_keeps_frames_without_icons(self):
        class Smp:
            frame_idx, t_ms = 3, 1500.0
            frame = np.full((W, W, 3), 128, np.uint8)
        reader = AllyIconReader(self.floor, None, self.static, (0, 0, W, W))
        reader.feed(Smp())
        rows = reader.events("s")
        self.assertEqual(rows[0]["kind"], "coverage")
        self.assertEqual([r["kind"] for r in rows[1:]], ["frame"])
        self.assertTrue(all(r["ally_icon_version"] for r in rows))

    def test_the_reader_stores_the_portrait_feature_families(self):
        class Smp:
            frame_idx, t_ms = 4, 2000.0
            frame = _ally_icon_crop((30, 60, 200))
        reader = AllyIconReader(self.floor, None, self.static, (0, 0, W, W))
        with patch("reticle.minimap.widget_drawn", return_value=True):
            reader.feed(Smp())
        icons = [r for r in reader.events("s") if r["kind"] == "icon"]
        self.assertEqual(len(icons), 1)
        pf = icons[0]["portrait_features"]
        self.assertEqual({k: len(v) for k, v in pf.items()},
                         {"grid3_lab": 27, "hog_x1": 32, "prof_h": 18})
        self.assertEqual(icons[0]["portrait_features_version"],
                         ALLY_PORTRAIT_FEATURES_VERSION)
        # The candidate row carries the same features, so a replay keeps them.
        cand = [c for c in reader.candidate_rows("s") if c["channel"] == "ally"
                and c["portrait_features"] is not None]
        self.assertEqual(cand[0]["portrait_features"], pf)

    def test_a_turned_placement_turns_the_portrait_back(self):
        """On a widget placed turned over, the baked frame holds the portrait
        upside down; the reader turns it back before taking its features
        [domain:minimap/upright-icons-on-turned-map]."""
        from reticle import ally_portrait
        crop = _ally_icon_crop((30, 60, 200))
        crop[53:60, 55:65] = (240, 240, 240)          # a portrait that is not symmetric

        class Smp:
            frame_idx, t_ms = 4, 2000.0
            frame = crop

        def portrait_of(turned):
            reader = AllyIconReader(self.floor, None, self.static, (0, 0, W, W),
                                    turned=turned)
            with patch("reticle.minimap.widget_drawn", return_value=True):
                reader.feed(Smp())
            rows = reader.events("s")
            return rows, [r for r in rows if r["kind"] == "icon"][0]

        rows_up, up = portrait_of(None)
        rows_t, turned = portrait_of(lambda t: t < 5000.0)
        self.assertNotEqual(up["portrait_features"], turned["portrait_features"])
        # The turned features are the upright reader's on the turned window.
        d = [r for r in rows_up if r["kind"] == "icon"][0]
        img = cv2.rotate(ally_portrait.align_icon(crop, d["cx"], d["cy"]), cv2.ROTATE_180)
        from reticle.minimap import portrait_key
        want = ally_portrait.stored(ally_portrait.portrait_features(img, portrait_key(img)))
        # The stored centre is rounded to 3 places, so the window moves a hair.
        for fam, v in want.items():
            np.testing.assert_allclose(turned["portrait_features"][fam], v, atol=1.0)
        frame_t = [r for r in rows_t if r["kind"] == "frame"][0]
        self.assertTrue(frame_t["turned"])
        self.assertEqual(rows_t[0]["widget_turned_frames"], 1)
        # An upright session's rows carry neither key.
        self.assertNotIn("turned", [r for r in rows_up if r["kind"] == "frame"][0])
        self.assertNotIn("widget_turned_frames", rows_up[0])
        # A placement turned only at other times leaves this frame upright.
        rows_late, late = portrait_of(lambda t: t >= 5000.0)
        self.assertEqual(late["portrait_features"], up["portrait_features"])
        self.assertEqual(rows_late, rows_up)

    def test_a_candidate_without_features_replays_as_unmeasured(self):
        row = {"frame_idx": 1, "t_ms": 0.0, "channel": "ally", "cx": 5.0, "cy": 5.0,
               "r": 6, "facing": None, "cov": 1.0, "inner": 1.0, "inner_v": 1.0,
               "lobe": 1.0, "area": 10, "map_diff": 20.0, "descriptor": [1.0],
               "descriptor_pixels": 9, "descriptor_reason": None,
               "candidate_key": "s:1:ally:0", "decision": {"family": "icon"},
               "self_occluder": None}
        rows = AllyIconReader.replay_events("s", [], [row], 15.0, "rev")
        icon = [r for r in rows if r["kind"] == "icon"][0]
        self.assertIsNone(icon["portrait_features"])
        self.assertEqual(icon["portrait_features_reason"], "not_measured_by_this_revision")


class AllyPortraitFeatureTests(unittest.TestCase):
    def test_both_widget_sizes_align_to_one_scale(self):
        # One disc drawn at each widget size, proportional to the width,
        # aligns to the same radius.
        from reticle import ally_portrait
        radii = []
        for width in (331, 465):
            crop = np.zeros((width, width, 3), np.uint8)
            r = {331: 10, 465: 14}[width]
            cv2.circle(crop, (100, 100), r, (255, 255, 255), -1)
            img = ally_portrait.align_icon(crop, 100.0, 100.0)
            radii.append(np.sqrt((img[..., 0] > 127).sum() / np.pi))
        self.assertAlmostEqual(radii[0], radii[1], delta=1.0)

    def test_a_window_past_the_crop_edge_is_black(self):
        from reticle import ally_portrait
        crop = np.full((50, 50, 3), 200, np.uint8)
        img = ally_portrait.align_icon(crop, 2.0, 2.0, width=331)
        self.assertEqual(img.shape, (ally_portrait.SIDE, ally_portrait.SIDE, 3))
        self.assertEqual(int(img[0, 0].max()), 0)
        self.assertEqual(int(img[-1, -1].min()), 200)

    def test_edge_histograms_are_unit_length(self):
        from reticle import ally_portrait
        rng = np.random.default_rng(0)
        img = rng.integers(0, 255, (ally_portrait.SIDE, ally_portrait.SIDE, 3), np.uint8)
        f = ally_portrait.portrait_features(img, np.zeros(img.shape[:2], bool))
        self.assertAlmostEqual(float(np.linalg.norm(f["hog_x1"])), 1.0, places=5)


if __name__ == "__main__":
    unittest.main()


class SurfaceSeedTests(unittest.TestCase):
    """A broken ring beside a filled lobe: the fit must find the ring's centre."""

    def crop(self):
        crop = np.full((W, W, 3), 128, np.uint8)
        teal = (200, 220, 40)
        centre = (200, 200)
        # Three separate arcs: each arc's centroid sits about a radius from
        # the centre, out of a centroid search's reach.
        for a0 in (200, 290, 20):
            cv2.ellipse(crop, centre, (10, 10), 0, a0, a0 + 60, teal, 2)
        lobe = np.array([[209, 192], [226, 200], [209, 208]], np.int32)
        cv2.fillPoly(crop, [lobe], teal)
        cv2.circle(crop, centre, 7, (30, 60, 200), -1)
        return crop

    def test_the_surface_seed_centres_on_the_ring(self):
        from reticle.minimap import icons, ally_mask

        crop = self.crop()
        floor = np.ones((W, W), bool)
        got = icons(ally_mask(crop), crop, floor, require_facing=False,
                    seed="surface")
        best = min(got, key=lambda f: np.hypot(f["cx"] - 200, f["cy"] - 200))
        self.assertLessEqual(np.hypot(best["cx"] - 200, best["cy"] - 200), 1.5)

    def test_an_unknown_seed_is_refused(self):
        from reticle.minimap import icons, ally_mask

        crop = self.crop()
        with self.assertRaises(ValueError):
            icons(ally_mask(crop), crop, np.ones((W, W), bool), seed="guess")


class PeakSeedTests(unittest.TestCase):
    """An enemy ring whose key touches a filled red glyph: one blob, two
    shapes. The centroid seed fits one circle for the blob and it lands on
    the glyph; the peaks seed gates before choosing and finds the ring."""

    def crop(self):
        crop = np.full((W, W, 3), 128, np.uint8)
        red = (40, 30, 220)
        cv2.circle(crop, (200, 200), 10, red, 2)                    # the icon's ring
        cv2.circle(crop, (200, 200), 7, (150, 170, 180), -1)        # its portrait
        cv2.circle(crop, (219, 200), 9, red, -1)                    # a glyph touching it
        return crop

    def fits(self, seed):
        from reticle.minimap import icons
        from reticle.minimap_objects import COV_MIN, INNER_RED_MAX, enemy_red_mask

        crop = self.crop()
        return icons(enemy_red_mask(crop), crop, np.ones((W, W), bool), cov_min=COV_MIN,
                     inner_max=INNER_RED_MAX, require_facing=False, seed=seed)

    def near(self, got):
        return [f for f in got if np.hypot(f["cx"] - 200, f["cy"] - 200) <= 1.5]

    def test_the_centroid_seed_loses_the_ring_to_the_glyph(self):
        self.assertEqual(self.near(self.fits("centroid")), [])

    def test_the_peaks_seed_finds_the_ring(self):
        got = self.near(self.fits("peaks"))
        self.assertEqual(len(got), 1)
        self.assertLessEqual(got[0]["inner"], 0.25)

    def test_the_peaks_seed_keeps_a_lone_ring(self):
        from reticle.minimap import icons
        from reticle.minimap_objects import COV_MIN, INNER_RED_MAX, enemy_red_mask

        crop = np.full((W, W, 3), 128, np.uint8)
        cv2.circle(crop, (120, 140), 10, (40, 30, 220), 2)
        got = icons(enemy_red_mask(crop), crop, np.ones((W, W), bool), cov_min=COV_MIN,
                    inner_max=INNER_RED_MAX, require_facing=False, seed="peaks")
        self.assertEqual(len(got), 1)
        self.assertLessEqual(np.hypot(got[0]["cx"] - 120, got[0]["cy"] - 140), 1.0)


class SoftCoverTests(unittest.TestCase):
    """A pale enemy ring: half its rim is saturated red the HSV key reads,
    half is a desaturated red under the key's saturation floor. The binary
    coverage holds about half the circle; soft redness scores the pale half
    too, and a cut above the binary share keeps it only softly."""

    def crop(self):
        crop = np.full((W, W, 3), 110, np.uint8)
        cv2.ellipse(crop, (120, 140), (10, 10), 0, 0, 180, (40, 30, 220), 2)
        cv2.ellipse(crop, (120, 140), (10, 10), 0, 180, 360, (120, 120, 175), 2)
        return crop

    def fits(self, soft, cov_min):
        from reticle.minimap import icons
        from reticle.minimap_objects import INNER_RED_MAX, enemy_red_mask
        from reticle.teardrop import redness

        crop = self.crop()
        return icons(enemy_red_mask(crop), crop, np.ones((W, W), bool), cov_min=cov_min,
                     inner_max=INNER_RED_MAX, require_facing=False, seed="peaks",
                     cov_map=redness(crop) if soft else None)

    def test_the_key_misses_the_pale_half_and_soft_redness_scores_it(self):
        self.assertEqual(self.fits(False, 0.7), [])
        got = self.fits(True, 0.7)
        self.assertEqual(len(got), 1)
        self.assertLessEqual(np.hypot(got[0]["cx"] - 120, got[0]["cy"] - 140), 1.0)

    def test_cov_map_needs_the_peaks_seed(self):
        from reticle.minimap import icons
        from reticle.minimap_objects import enemy_red_mask
        from reticle.teardrop import redness

        crop = self.crop()
        with self.assertRaises(ValueError):
            icons(enemy_red_mask(crop), crop, np.ones((W, W), bool), seed="centroid",
                  cov_map=redness(crop))


class RadiusBandTests(unittest.TestCase):
    """At the 331 px key's map scale (0.637) the base band [8, 13] spans
    5.1 to 8.3 px: `nearest` searches from 5 px, `inside` from 6 px."""

    SCALE = 0.637

    def fits(self, radii):
        from reticle.minimap import icons

        crop = np.full((80, 80, 3), 128, np.uint8)
        yy, xx = np.ogrid[:80, :80]
        d2 = (xx - 40) ** 2 + (yy - 40) ** 2
        mask = (d2 <= 6 ** 2) & (d2 >= 4 ** 2)        # a ring of radius 5
        return icons(mask, crop, np.ones((80, 80), bool), cov_min=0.0, inner_max=1.0,
                     require_facing=False, gates=False, scale=self.SCALE, radii=radii)

    def test_nearest_rings_the_five_pixel_icon(self):
        self.assertIn(5, [round(f["r"]) for f in self.fits("nearest")])

    def test_inside_searches_no_radius_below_the_band(self):
        got = self.fits("inside")
        self.assertTrue(got)
        self.assertTrue(all(f["r"] >= 6 for f in got))

    def test_an_unknown_band_rule_is_refused(self):
        with self.assertRaises(ValueError):
            self.fits("outside")
