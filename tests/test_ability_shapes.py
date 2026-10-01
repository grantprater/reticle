"""Parametric minimap ability shapes: a ring round a seed or anywhere, a beam
from the caster, the widened search when the seed is wrong, a wall of
segments, a curve, and refusals. Every finder is fed a descriptor; these
synthetic ones carry the surprise path's teal (the drawings are teal)."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle import ability_shapes as S

#: Teal in BGR: OpenCV hue 92, saturation 212, value 180.
TEAL = (180, 170, 30)
#: Orange in BGR: OpenCV hue 16, saturation 255.
ORANGE = (0, 140, 255)


def D(shape, prior="free", **sizes):
    """A synthetic descriptor in widget px at SET_AT."""
    d = {"id": f"test:{shape}", "ability": f"test {shape}", "side": "ally", "shape": shape,
         "prior": prior, "colour": S.SURPRISE_COLOUR, **sizes}
    if shape == "beam":
        d["geo"] = S.beam_geometry(d["width_px"], S.SET_AT)
    return d


REGROWTH = D("ring", "caster", radius_px=38.0)
RECON = D("ring", "free", radius_px=57.0)
FURY = D("beam", "caster", width_px=7.0)


def _widget() -> np.ndarray:
    img = np.full((329, 331, 3), 40, np.uint8)
    cv2.rectangle(img, (60, 60), (270, 270), (128, 128, 128), -1)
    return img


class RingTest(unittest.TestCase):
    def test_a_regrowth_ring_is_found_round_the_seed(self):
        img = _widget()
        cv2.circle(img, (120, 150), 38, TEAL, 2)
        f = S.fit_shape(img, REGROWTH, (126, 153))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "seeded")
        self.assertLessEqual(np.hypot(f["cx"] - 120, f["cy"] - 150), 2)
        self.assertLessEqual(abs(f["r"] - 38), 1.5)

    def test_a_recon_ring_is_searched_over_the_widget(self):
        img = _widget()
        cv2.circle(img, (200, 110), 57, TEAL, 2)
        f = S.fit_shape(img, RECON, (90, 250))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "free")
        self.assertLessEqual(np.hypot(f["cx"] - 200, f["cy"] - 110), 2)

    def test_a_ring_far_from_a_wrong_seed_is_found_widened(self):
        img = _widget()
        cv2.circle(img, (200, 200), 38, TEAL, 2)
        f = S.fit_shape(img, REGROWTH, (90, 90))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "widened")
        self.assertIsNotNone(f["seeded"])

    def test_a_ring_centred_off_the_footprint_is_not_found(self):
        img = _widget()
        cv2.circle(img, (40, 160), 45, TEAL, 2)
        recon = D("ring", "free", radius_px=45.0)
        self.assertTrue(S.fit_shape(img, recon, None)["found"])
        support = np.zeros(img.shape[:2], bool)
        support[60:271, 60:271] = True
        f = S.fit_shape(img, recon, None, support)
        self.assertIs(f["found"], False)
        self.assertTrue(f["cx"] is None or support[f["cy"], f["cx"]])

    def test_ring_candidates_list_every_ring_best_first(self):
        img = _widget()
        cv2.circle(img, (120, 130), 40, TEAL, 2)
        cv2.circle(img, (220, 220), 35, TEAL, 2)
        tl = S.teal(img)
        R, mask = S.widget(img.shape)
        got = [c for c in S.ring_candidates(tl, mask, S.SET_AT) if c["accepted"]]
        self.assertEqual(len(got), 2)
        self.assertGreaterEqual(got[0]["score"], got[1]["score"])
        centres = sorted((c["cx"], c["cy"]) for c in got)
        self.assertLessEqual(np.hypot(centres[0][0] - 120, centres[0][1] - 130), 2)
        self.assertLessEqual(np.hypot(centres[1][0] - 220, centres[1][1] - 220), 2)

    def test_an_icon_sized_ring_is_not_an_area(self):
        img = _widget()
        cv2.circle(img, (150, 150), 8, TEAL, 2)
        self.assertFalse(S.fit_shape(img, REGROWTH, (150, 150))["found"])

    def test_a_ring_outside_the_radius_window_is_not_the_candidate(self):
        # The candidate searches only round its drawn radius; a ring of
        # another size is the surprise path's.
        img = _widget()
        cv2.circle(img, (150, 150), 55, TEAL, 2)
        self.assertFalse(S.fit_shape(img, REGROWTH, (150, 150))["found"])
        tl, (_, mask) = S.teal(img), S.widget(img.shape)
        self.assertTrue(any(c["accepted"] for c in S.ring_candidates(tl, mask, S.SET_AT)))


class BeamTest(unittest.TestCase):
    def _fury(self, img, x0=110, y0=220, deg=-60.0, length=120):
        t = np.radians(deg)
        cv2.line(img, (x0, y0), (int(x0 + length * np.cos(t)), int(y0 + length * np.sin(t))),
                 TEAL, 7)

    def test_a_fury_blast_is_found_from_the_caster(self):
        img = _widget()
        self._fury(img)
        f = S.fit_shape(img, FURY, (104, 230))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "seeded")
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 3.0)

    def test_a_wrong_seed_widens_to_the_longest_segment(self):
        img = _widget()
        self._fury(img)
        f = S.fit_shape(img, FURY, (250, 80))
        self.assertTrue(f["found"])
        self.assertEqual(f["path"], "widened")
        self.assertTrue(f["oriented"])
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 2.0)


class RefusalTest(unittest.TestCase):
    def test_a_bare_widget_finds_nothing(self):
        img = _widget()
        for desc in (REGROWTH, RECON, FURY, SAGE, BLAZE):
            f = S.fit_shape(img, desc, (150, 150))
            self.assertIs(f["found"], False, desc["shape"])
            self.assertIsNotNone(f["reason"], desc["shape"])

    def test_teal_off_the_map_is_not_a_shape(self):
        # Teal scenery through the widget, outside the map's footprint.
        img = _widget()
        cv2.line(img, (20, 60), (20, 270), TEAL, 7)
        support = np.zeros(img.shape[:2], bool)
        support[60:271, 60:271] = True
        self.assertTrue(S.fit_shape(img, FURY, None)["found"])
        f = S.fit_shape(img, FURY, None, support)
        self.assertIs(f["found"], False)
        self.assertEqual(f["support"], "art_footprint")
        self.assertEqual(S.fit_shape(img, REGROWTH, None, support[:10])["reason"], "support_shape")
        # A shorter blast on the map is found past the longer line off it.
        BeamTest()._fury(img, length=110)
        f = S.fit_shape(img, FURY, (250, 80), support)
        self.assertTrue(f["found"])
        self.assertGreaterEqual(f["on_map"], S.BEAM_ON_MAP)
        d = abs(f["theta_deg"] - 300.0) % 180
        self.assertLessEqual(min(d, 180 - d), 2.0)

    def test_unread_is_distinct_from_not_found(self):
        self.assertEqual(S.fit_shape(None, REGROWTH, None)["reason"], "no_crop")
        self.assertIsNone(S.fit_shape(None, REGROWTH, None)["found"])

    def test_a_refused_descriptor_refuses_with_its_reason(self):
        f = S.fit_shape(_widget(), {"ability": "Owl Drone", "side": "ally",
                                    "refused": "no_appearance_fact"}, None)
        self.assertIsNone(f["found"])
        self.assertEqual(f["reason"], "no_appearance_fact")

    def test_every_row_is_stamped_with_its_descriptor(self):
        f = S.fit_shape(_widget(), RECON, None)
        self.assertEqual(f["ability_shape_version"], S.ABILITY_SHAPE_VERSION)
        self.assertEqual(f["descriptor"]["radius_px"], 57.0)


#: Barrier Orb and Blaze at SET_AT: the facts' base values times 0.636.
SAGE = D("segments", length_px=25.3, pieces_px=[7.8, 13.5, 19.2], width_px=3.1)
BLAZE = {**D("curve", width_px=3.75, length_px=[26.8, 53.9]),
         "colour": S.colour_model([16, 18, 20], [153, 194])}


class WallTest(unittest.TestCase):
    def _line(self, img, p0, p1, colour=TEAL, w=3):
        """A horizontal bar from x0 to x1 inclusive, `w` px thick (no caps)."""
        cv2.rectangle(img, (p0[0], p0[1] - w // 2), (p1[0], p1[1] + w // 2), colour, -1)

    def test_a_whole_wall_is_one_group_of_its_length(self):
        img = _widget()
        self._line(img, (100, 150), (125, 150))
        f = S.fit_shape(img, SAGE, None)
        self.assertTrue(f["found"])
        self.assertEqual(f["pieces"], 1)
        self.assertLessEqual(abs(f["span"] - 25.3), 3)

    def test_broken_pieces_on_one_line_join(self):
        img = _widget()
        self._line(img, (100, 150), (108, 150))
        self._line(img, (118, 150), (125, 150))
        f = S.fit_shape(img, SAGE, None)
        self.assertTrue(f["found"])
        self.assertEqual(f["pieces"], 2)

    def test_a_lone_piece_is_not_a_wall_on_one_crop(self):
        img = _widget()
        self._line(img, (100, 150), (108, 150))
        f = S.fit_shape(img, SAGE, None)
        self.assertFalse(f["found"])
        self.assertEqual(f["reason"], "piece_only")
        self.assertTrue(f["piece"])

    def test_a_curved_teal_arc_is_not_a_wall_piece(self):
        img = _widget()
        cv2.ellipse(img, (150, 150), (9, 9), 0, 200, 340, TEAL, 3)
        self.assertEqual(S.fit_shape(img, SAGE, None)["reason"], "no_component")

    def test_a_line_longer_than_the_wall_is_not_a_wall(self):
        img = _widget()
        self._line(img, (80, 150), (160, 150))
        self.assertFalse(S.fit_shape(img, SAGE, None)["found"])

    def test_a_blaze_curve_is_found_in_its_own_colour(self):
        img = _widget()
        pts = np.array([[100 + t, 150 + 0.012 * (t - 20) ** 2] for t in range(0, 41)], np.int32)
        cv2.polylines(img, [pts], False, ORANGE, 4)
        f = S.fit_shape(img, BLAZE, None)
        self.assertTrue(f["found"])
        self.assertEqual(len(f["points"]), 5)
        # The teal descriptor of the same shape sees nothing orange.
        self.assertFalse(S.fit_shape(img, {**BLAZE, "colour": S.SURPRISE_COLOUR}, None)["found"])


class SeedTest(unittest.TestCase):
    """The seed comes from the nearest stored self position within the tolerance."""

    T = [0.0, 67.0, 133.0, 200.0, 267.0, 333.0, 400.0]

    def test_the_row_at_the_crop_time_wins(self):
        sx = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]
        self.assertEqual(S.seed_from_track(self.T, sx, sx, 133.0), (3.0, 3.0))

    def test_a_single_frame_gap_is_bridged_by_its_neighbour(self):
        sx = [1.0, 2.0, None, 4.0, 5.0, 6.0, 7.0]
        self.assertEqual(S.seed_from_track(self.T, sx, sx, 133.0), (2.0, 2.0))

    def test_a_span_without_a_position_gives_none(self):
        sx = [None] * 7
        self.assertIsNone(S.seed_from_track(self.T, sx, sx, 200.0))
        sx = [1.0, None, None, None, None, None, None, None]
        self.assertIsNone(S.seed_from_track(self.T + [467.0], sx, sx, 400.0))

    def test_a_crop_far_from_every_row_gives_none(self):
        sx = [1.0] * 7
        self.assertIsNone(S.seed_from_track(self.T, sx, sx, 400.0 + S.SEED_TOL_MS + 1))
        self.assertIsNone(S.seed_from_track([], [], [], 0.0))


if __name__ == "__main__":
    unittest.main()
