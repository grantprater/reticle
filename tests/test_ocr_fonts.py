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


if __name__ == "__main__":
    unittest.main()
