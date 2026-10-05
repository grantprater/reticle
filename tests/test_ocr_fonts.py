import unittest
from pathlib import Path

import numpy as np

from reticle import ocr


def _store_font(name: str) -> Path | None:
    try:
        p = ocr.font_dir() / name
    except Exception:
        return None
    return p if p.is_file() else None


class LeadingZeroTests(unittest.TestCase):
    def test_only_multi_digit_numbers_starting_with_zero_refuse(self):
        self.assertTrue(ocr._leading_zero("00"))
        self.assertTrue(ocr._leading_zero("05"))
        self.assertFalse(ocr._leading_zero("0"))
        self.assertFalse(ocr._leading_zero("100"))

    def test_bottom_field_refuses_two_zeros(self):
        # Two glyph-shaped zeros in the health field: "00" is no number the HUD draws.
        gray = np.zeros((65, 165), np.uint8)
        gray[19:53, 87:109] = 255
        gray[19:53, 112:132] = 255
        blank = ocr.Templates(["0", "1"], np.stack([np.ones((20, 12), np.float32),
                                                   np.zeros((20, 12), np.float32)]))
        spec = [s for s in ocr.BOTTOM_FIELDS["hud_hp"] if s.name == "hp"]
        vals, _occ, _conf = ocr.read_subfields(gray, spec, blank, 0.5, 0.0)
        self.assertIsNone(vals["hp"])


class FieldTemplatesTests(unittest.TestCase):
    def test_templates_for_picks_the_field_set(self):
        a = ocr.Templates(["1"], np.zeros((1, 20, 12), np.float32))
        b = ocr.Templates(["2"], np.zeros((1, 20, 12), np.float32))
        ft = ocr.FieldTemplates({"clock": a, "hp": b}, ())
        self.assertIs(ocr.templates_for(ft, "clock"), a)
        self.assertIs(ocr.templates_for(ft, "hp"), b)
        self.assertIs(ocr.templates_for(a, "hp"), a)

    def test_field_without_font_reads_the_default(self):
        a = ocr.Templates(["1"], np.zeros((1, 20, 12), np.float32))
        mined = ocr.Templates(["2"], np.zeros((1, 20, 12), np.float32))
        ft = ocr.FieldTemplates({"clock": a}, (), default=mined)
        self.assertIs(ocr.templates_for(ft, "ammo_reserve"), mined)
        with self.assertRaises(KeyError):
            ocr.FieldTemplates({"clock": a}, ())["ammo_reserve"]

    def test_displaced_glyph_is_misaligned_and_bloom_is_not(self):
        g = lambda y, h: ocr.Glyph(0, y, 8, h, np.zeros((20, 12), np.float32))
        # a06f04a0059f 1689.5 s: debris 3 px low at its top and 5 px at its bottom.
        self.assertTrue(ocr._misaligned([g(21, 22), g(18, 20)]))
        # Bloom grows one edge: the top moves 4 px, the bottom stays.
        self.assertFalse(ocr._misaligned([g(14, 24), g(18, 20)]))
        self.assertFalse(ocr._misaligned([g(18, 20)]))


@unittest.skipIf(_store_font("DINNext_Regular.ttf") is None, "store game fonts absent")
class RenderedDigitTests(unittest.TestCase):
    def test_off_grid_phase_reads_its_own_digit(self):
        # A phase between the grid's, at a cut between the set's, still reads
        # as its digit with the reader's margin.
        font = str(_store_font("DINNext_Regular.ttf"))
        tpl = ocr.font_digit_templates(font, 28.0)
        self.assertEqual(sorted(set(tpl.labels)), list("0123456789"))
        for d in "0123456789":
            cover = ocr._font_cover(d, font, 28.0 * ocr.SLATE_PX_PER_PT, 0.125, 0.375)
            bm = ocr._cut_glyph(cover, 0.62)
            label, score, margin = tpl.match(ocr.Glyph(0, 0, 12, 20, bm))
            self.assertEqual(label, d)
            self.assertGreaterEqual(margin, 0.05)

    def test_every_field_has_a_set(self):
        ft = ocr.game_font_templates()
        self.assertEqual(set(ft.by_field), set(ocr.FIELD_FONTS))
        self.assertTrue(all(Path(f).is_file() for f in ft.files))


class MatchManyTests(unittest.TestCase):
    def setUp(self):
        rng = np.random.default_rng(3)
        self.maps = (rng.random((40, 20, 12)) > 0.5).astype(np.float32)
        self.tpl = ocr.Templates([str(i % 7) for i in range(40)], self.maps)

    def test_agrees_with_match_off_ties(self):
        rng = np.random.default_rng(4)
        glyphs = (rng.random((30, 20, 12)) > 0.5).astype(np.float32)
        glyphs[:10] = self.maps[:10]
        labels, scores, margins = self.tpl.match_many(glyphs)
        for bm, label, score, margin in zip(glyphs, labels, scores, margins):
            want = self.tpl.match(ocr.Glyph(0, 0, 12, 20, bm))
            self.assertAlmostEqual(margin, want[2], places=6)
            self.assertAlmostEqual(score, want[1], places=6)
            if margin > 0:
                self.assertEqual(label, want[0])

    def test_margin_at_the_cut_is_the_cut(self):
        # Twelve of 240 pixels separate the two labels: the margin is 0.05
        # exactly, which the reader's `margin < 0.05` keeps.
        a = np.zeros((20, 12), np.float32)
        b = a.copy()
        b[0, :] = 1.0
        tpl = ocr.Templates(["0", "8"], np.stack([a, b]))
        _labels, _scores, margins = tpl.match_many(a[None])
        self.assertFalse(margins[0] < 0.05)

    def test_one_label_takes_its_next_template_as_rival(self):
        a = np.zeros((20, 12), np.float32)
        b = a.copy()
        b[0, :6] = 1.0
        tpl = ocr.Templates(["1", "1"], np.stack([a, b]))
        labels, _scores, margins = tpl.match_many(a[None])
        self.assertEqual(labels, ["1"])
        self.assertAlmostEqual(margins[0], 6 / 240)

    def test_no_glyphs(self):
        self.assertEqual(ocr._digits([], self.tpl), ("", 1.0, 1.0))


def _scoreline(left: str, left_plate: float, right: str, right_plate: float) -> np.ndarray:
    """A 59x308 scoreline ROI: white DIN Next 22 pt score digits composited
    over flat plates as the game draws them, the clock field empty."""
    font = str(_store_font("DINNext_Regular.ttf"))
    roi = np.full((59, 308), 60.0, np.float32)
    roi[:, :90] = left_plate
    roi[:, 220:] = right_plate
    for text, x in ((left, 12), (right, 290 - 14 * len(right))):
        for ch in text:
            cover = ocr._font_cover(ch, font, 22.0 * ocr.SLATE_PX_PER_PT, 0.25, 0.5)
            h, w = cover.shape
            plate = roi[14:14 + h, x:x + w]
            roi[14:14 + h, x:x + w] = cover * 255.0 + (1.0 - cover) * plate
            x += w - 4
    return np.clip(np.rint(roi), 0, 255).astype(np.uint8)


@unittest.skipIf(_store_font("DINNext_Regular.ttf") is None, "store game fonts absent")
class ScorePlateTests(unittest.TestCase):
    def setUp(self):
        self.tpl = ocr.game_font_templates()

    def test_scores_read_over_a_bright_plate(self):
        # Sky behind the plate lifts it past the 190 cut, which fused plate
        # and digits into one mass that refused as `occluded`.
        r = ocr.read_scoreline(_scoreline("7", 215.0, "4", 100.0), self.tpl)
        self.assertEqual((r.score_left, r.score_right), (7, 4))
        self.assertIsNone(r.score_left_reason)

    def test_two_digits_over_a_bright_plate(self):
        r = ocr.read_scoreline(_scoreline("12", 225.0, "10", 205.0), self.tpl)
        self.assertEqual((r.score_left, r.score_right), (12, 10))

    def test_near_white_plate_refuses_low_contrast(self):
        r = ocr.read_scoreline(_scoreline("7", 245.0, "4", 100.0), self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "low_contrast")
        self.assertEqual(r.score_right, 4)

    def test_pale_scenery_is_not_ink(self):
        # A 3 px pale rim (luma 182 over 90) at the ROI's edge peaks at cover
        # 0.58: no glyph, so the lone digit stays aligned and reads.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[26:42, 0:3] = 182
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertEqual(r.score_left, 4)

    def test_white_streak_over_a_score_refuses_occluded(self):
        # Thinner than the opening, so it is ink, and too tall for a digit.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[5:55, 30:36] = 255
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "occluded")

    def test_white_mass_wider_than_the_opening_refuses(self):
        # A mass wider than the opening is plate as white as the ink.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[5:55, 0:40] = 255
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "low_contrast")

    def test_pale_piece_apart_from_the_digits_is_not_ink(self):
        # A digit-tall piece at coverage 0.65 passes the segmentation cut but
        # scores below SCORE_INK_MIN; far from the digit, it is ignored.
        gray = _scoreline("4", 100.0, "7", 100.0)
        gray[18:38, 60:65] = 201
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertEqual(r.score_left, 4)
        self.assertIsNone(r.score_left_reason)

    def test_dim_one_beside_a_one_refuses_faint_digit(self):
        # Two tabular 1s stand 10 px apart; the second, dimmed by scenery to
        # coverage 0.6, must refuse the field rather than read 11 as 1.
        gray = _scoreline("1", 100.0, "7", 100.0)
        box = gray[14:40, 10:24] > 200
        ys, xs = np.nonzero(box)
        x0, x1 = xs.min() + 10, xs.max() + 10
        dim = gray[14:40, x0:x1 + 1].astype(np.float32)
        cover = np.clip((dim - 100.0) / 155.0, 0, 1) * 0.6
        gray[14:40, x1 + 11:x1 + 11 + (x1 - x0 + 1)] = np.rint(100.0 + cover * 155.0).astype(np.uint8)
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "faint_digit")

    def test_dim_mass_across_a_digit_rows_refuses_faint_digit(self):
        # A pale streak taller than a digit, beside it, may hide one.
        gray = _scoreline("4", 100.0, "7", 100.0)
        gray[8:52, 30:34] = 195
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "faint_digit")

    def test_ink_score_weights_the_core(self):
        labels = np.array([[0, 1, 1, 2]], np.int32)
        cover = np.array([[0.9, 1.0, 0.5, 0.6]], np.float32)
        s = ocr.ink_score(cover, labels, 3)
        self.assertEqual(s[0], 0.0)
        self.assertAlmostEqual(s[1], 1.25 / 1.5)
        self.assertAlmostEqual(s[2], 0.6, places=6)


if __name__ == "__main__":
    unittest.main()
