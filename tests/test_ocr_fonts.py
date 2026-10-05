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
        self.assertEqual(set(ft.by_field) | set(ocr.SOFT_FIELDS), set(ocr.FIELD_FONTS))
        self.assertEqual(set(ft.fonts), set(ocr.FIELD_FONTS))
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


def _draw(roi: np.ndarray, text: str, pens, baseline: float, font: str, pt: float,
          alpha: tuple[float, ...] = ()) -> None:
    """Composite white `text` into float `roi` as the game draws it: each
    character's coverage at its pen, drawn 8x and shrunk with INTER_AREA.
    `alpha` scales each character's coverage in turn (default 1)."""
    from PIL import Image, ImageDraw, ImageFont
    import cv2
    ss = 8
    f = ImageFont.truetype(font, pt * ocr.SLATE_PX_PER_PT * ss,
                           layout_engine=ImageFont.Layout.BASIC)
    h, w = roi.shape
    for k, (ch, pen) in enumerate(zip(text, pens)):
        im = Image.new("L", (w * ss, h * ss), 0)
        ImageDraw.Draw(im).text((pen * ss, baseline * ss), ch, fill=255, font=f, anchor="ls")
        cover = cv2.resize(np.asarray(im, np.float32) / 255.0, (w, h),
                           interpolation=cv2.INTER_AREA)
        cover *= alpha[k] if k < len(alpha) else 1.0
        roi[:] = cover * 255.0 + (1.0 - cover) * roi


def _scoreline(left: str, left_plate: float, right: str, right_plate: float,
               left_alpha: tuple[float, ...] = (), clock: str = "") -> np.ndarray:
    """A 59x308 scoreline ROI: white DIN Next 22 pt score digits composited
    over flat plates at the widget's measured places (`ocr.SCORE_PENS`),
    and `clock` (M:SS, or SS.hh) in DIN Next 28 pt at its places, or an
    empty clock field. `left_alpha` scales each left digit's coverage."""
    font = str(_store_font("DINNext_Regular.ttf"))
    roi = np.full((59, 308), 60.0, np.float32)
    roi[:, :90] = left_plate
    roi[:, 220:] = right_plate
    for name, text, alpha in (("score_left", left, left_alpha), ("score_right", right, ())):
        if text:
            pens = ocr.SCORE_PENS[name][len(text) - 1]
            _draw(roi, text, pens, ocr.FIELD_BASELINE[name], font, 22.0, alpha)
    if ":" in clock:
        pens = (ocr.CLOCK_PENS[0], ocr.COLON_PEN) + ocr.CLOCK_PENS[1:]
        _draw(roi, clock, pens, ocr.FIELD_BASELINE["clock"], font, 28.0)
    elif clock:
        p = ocr.HUNDREDTHS_PENS
        pens = (p[0], p[1], p[1] + 18.25, p[2], p[3])
        _draw(roi, clock, pens, ocr.FIELD_BASELINE["clock"], font, 28.0)
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

    def test_every_digit_reads_at_both_places(self):
        for d in "0123456789":
            r = ocr.read_scoreline(_scoreline(d, 100.0, "1" + d, 120.0), self.tpl)
            self.assertEqual((r.score_left, r.score_right), (int(d), int("1" + d)), d)

    def test_near_white_plate_refuses_low_contrast(self):
        r = ocr.read_scoreline(_scoreline("7", 245.0, "4", 100.0), self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "low_contrast")
        self.assertEqual(r.score_right, 4)

    def test_pale_scenery_is_not_ink(self):
        # A 3 px pale rim (luma 182 over 90) at the ROI's edge is no digit.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[26:42, 0:3] = 182
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertEqual(r.score_left, 4)

    def test_white_streak_through_a_score_refuses(self):
        # Thinner than the opening, so it is ink, and taller than a digit:
        # the 4 under it leaves ink its cell does not explain.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[5:55, 16:20] = 255
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertIn(r.score_left_reason, ("fused", "occluded", "low_margin"))

    def test_white_mass_wider_than_the_opening_refuses(self):
        # A mass wider than the opening is plate as white as the ink.
        gray = _scoreline("4", 90.0, "7", 100.0)
        gray[5:55, 0:40] = 255
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "low_contrast")

    def test_pale_piece_apart_from_the_digits_is_not_ink(self):
        # A digit-tall pale piece outside every cell of the field is ignored.
        gray = _scoreline("4", 100.0, "7", 100.0)
        gray[18:38, 60:65] = 201
        r = ocr.read_scoreline(gray, self.tpl)
        self.assertEqual(r.score_left, 4)
        self.assertIsNone(r.score_left_reason)

    def test_dim_one_beside_a_one_refuses_faint_digit(self):
        # Two tabular 1s, the second dimmed by scenery to coverage 0.6: the
        # field refuses rather than read 11 as 1.
        r = ocr.read_scoreline(_scoreline("11", 100.0, "7", 100.0, left_alpha=(1.0, 0.6)),
                               self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "faint_digit")

    def test_half_coverage_second_one_refuses(self):
        # The hard 0.55 cut that hud-0.22.0 made before every decision left
        # a 1 at half coverage no component, so 11 read as 1. Soft cells
        # decide that cell once, between a digit and an empty cell.
        r = ocr.read_scoreline(_scoreline("11", 200.0, "7", 100.0, left_alpha=(1.0, 0.5)), self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "faint_digit")

    def test_lone_digit_at_a_two_digit_place_refuses(self):
        # The score is centred: a 1 at the first of two places has a partner
        # drawn and unseen.
        r = ocr.read_scoreline(_scoreline("11", 100.0, "7", 100.0, left_alpha=(1.0, 0.0)), self.tpl)
        self.assertIsNone(r.score_left)
        self.assertEqual(r.score_left_reason, "missing_digit")

    def test_no_ink_in_a_score_field_is_no_widget(self):
        # A scoreline drawn shows a score in both fields; a dark field with
        # no ink means the widget is absent, and every field says so.
        r = ocr.read_scoreline(_scoreline("", 80.0, "4", 100.0, clock="1:30"), self.tpl)
        self.assertEqual((r.score_left_reason, r.score_right_reason, r.clock_reason),
                         ("no_widget", "no_widget", "no_widget"))

    def test_clock_reads_m_ss(self):
        for text, ms in (("1:30", 90000), ("0:07", 7000), ("1:00", 60000)):
            r = ocr.read_scoreline(_scoreline("3", 100.0, "4", 100.0, clock=text), self.tpl)
            self.assertEqual(r.clock_ms, ms, text)
            self.assertIsNone(r.clock_reason)

    def test_clock_over_a_pale_plate_reads(self):
        # a06f04a0059f 904.5 s: the 190 cut fused a 0:24 over a pale plate.
        r = ocr.read_scoreline(_scoreline("6", 200.0, "3", 200.0, clock="0:24"), self.tpl)
        self.assertEqual(r.clock_ms, 24000)

    def test_hundredths_form_refuses_by_name(self):
        r = ocr.read_scoreline(_scoreline("6", 100.0, "6", 100.0, clock="18.18"), self.tpl)
        self.assertIsNone(r.clock_ms)
        self.assertEqual(r.clock_reason, "hundredths")

    def test_empty_clock_field_is_no_glyphs(self):
        r = ocr.read_scoreline(_scoreline("6", 100.0, "6", 100.0), self.tpl)
        self.assertEqual(r.clock_reason, "no_glyphs")


if __name__ == "__main__":
    unittest.main()
