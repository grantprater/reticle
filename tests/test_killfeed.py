import unittest
from unittest import mock

import numpy as np

from reticle import killfeed
from reticle.killfeed import EMPTY_BAND_REFUSALS, read_killfeed
from reticle.profiles import get_profile


def _roi():
    from reticle.killfeed import killfeed_roi

    return killfeed_roi(get_profile("valorant-16x9"))


def read_with_bands(bands, refusals):
    """Drive `read_killfeed` over chosen bands with chosen text-read outcomes.

    The pixel detector is not what changed; what changed is which refusals stop
    a band from being an entry. Patching the two collaborators tests that rule
    directly instead of hunting for a synthetic frame that happens to trip it.
    """
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    plate = np.ones((300, 400), dtype=bool)
    answers = list(refusals)

    def band_text(*_args, **_kwargs):
        return answers.pop(0)

    with mock.patch.object(killfeed, "_plate_masks",
                           return_value=(plate, plate, plate)), \
            mock.patch.object(killfeed, "_entry_bands", return_value=bands), \
            mock.patch.object(killfeed, "_one_colour_bands", return_value=[]), \
            mock.patch.object(killfeed, "_band_text", side_effect=band_text):
        return read_killfeed(frame, _roi(), 1920, 1080,
                             np.ones((300, 400), dtype=bool))


class EmptyBandTests(unittest.TestCase):
    def test_a_band_with_none_of_an_entrys_furniture_is_not_an_entry(self):
        for refusal in EMPTY_BAND_REFUSALS:
            with self.subTest(refusal=refusal):
                got = read_with_bands([(0, 34)], [refusal])
                self.assertEqual(got.entries, 0)
                self.assertEqual(got.empty_bands, 1)
                self.assertEqual(got.empty_band_reason, refusal)
                self.assertEqual(got.unparsed, 0)

    def test_a_readable_band_that_merely_failed_to_split_stays_an_entry(self):
        """An ability kill carries both portraits and an ability icon where the
        weapon icon goes, so it reaches these refusals rather than the empty
        ones -- c40d950031bb 13:14 reads `death` for 1.6 s continuously.
        Dropping these would trade a real death for the wipe false positives.
        """
        for refusal in ("no_divider", "no_baseline"):
            with self.subTest(refusal=refusal):
                got = read_with_bands([(0, 34)], [refusal])
                self.assertEqual(got.entries, 1)
                self.assertEqual(got.unparsed, 1)
                self.assertEqual(got.empty_bands, 0)

    def test_an_occluded_band_stays_an_entry(self):
        got = read_with_bands([(0, 34)], ["occluded"])
        self.assertEqual(got.entries, 1)
        self.assertEqual(got.unattributed, 1)
        self.assertEqual(got.empty_bands, 0)

    def test_a_wipe_splitting_into_several_empty_bands_counts_no_entries(self):
        """The measured failure: `_entry_bands` divides a tall plate run by
        PITCH, so a respawn wipe painting both plate colours across the ROI
        yields several bands at once and every one of them holds no name."""
        bands = [(0, 34), (40, 74), (80, 114), (120, 154)]
        got = read_with_bands(bands, ["no_glyphs"] * 4)
        self.assertEqual(got.entries, 0)
        self.assertEqual(got.empty_bands, 4)
        self.assertEqual(got.entry_ys, ())
        self.assertEqual(got.slots, ())

    def test_an_empty_band_does_not_displace_a_real_one_in_the_stack(self):
        """Order matters: the parallel `_ys`/`_wx` tuples index the stack, so a
        rejected band must leave no hole and no shift behind it."""
        bands = [(0, 34), (40, 74)]
        got = read_with_bands(bands, ["no_glyphs", "no_divider"])
        self.assertEqual(got.entries, 1)
        self.assertEqual(got.entry_ys, (40,))
        self.assertEqual(len(got.entry_wxs), 1)
        self.assertEqual(got.empty_bands, 1)

    def test_attribution_cannot_be_reached_by_an_empty_band(self):
        """The reason the K/D table survives this change untouched: a band with
        no entry furniture never produced a kill or death verdict anyway."""
        got = read_with_bands([(0, 34), (40, 74)], ["no_ink", "no_glyphs"])
        self.assertFalse(got.player_kill)
        self.assertFalse(got.player_death)
        self.assertEqual((got.kill_ys, got.death_ys), ((), ()))


class KillerNameStartTests(unittest.TestCase):
    """The killer's portrait abuts the name's first letter, descenders included."""

    def test_a_dropped_descender_does_not_split_the_name(self):
        band = np.zeros((34, 120), np.uint8)
        # "R e y n a": four letters on the baseline (row 23), a descender to row 26.
        for x0, top, bottom in ((20, 12, 23), (29, 15, 23), (37, 15, 26), (45, 15, 23), (53, 15, 23)):
            band[top:bottom, x0:x0 + 6] = 255
        # The baseline run starts after the descender's gap: "na".
        self.assertEqual(killfeed.killer_name_start(band, (45, 58)), 20)

    def test_portrait_art_past_the_gap_is_not_the_name(self):
        band = np.zeros((34, 120), np.uint8)
        band[12:23, 40:46] = 255          # "N"
        band[15:23, 48:54] = 255          # "a"
        band[2:30, 20:28] = 255           # hair highlight: too tall for a glyph
        band[15:23, 25:31] = 255
        self.assertEqual(killfeed.killer_name_start(band, (40, 53)), 40)

    def test_two_touching_kerned_letters_are_one_glyph(self):
        band = np.zeros((34, 120), np.uint8)
        # "V" and "y" of "Vyse" touch at one pixel: 17 wide, past one glyph.
        band[12:23, 20:28] = 255
        band[15:26, 29:36] = 255
        band[20, 28] = 255
        band[15:23, 38:44] = 255          # "s"
        band[15:23, 46:52] = 255          # "e"
        self.assertEqual(killfeed.killer_name_start(band, (38, 51)), 20)

    def test_a_wide_blob_without_a_bridge_is_not_a_pair(self):
        band = np.zeros((34, 120), np.uint8)
        band[12:23, 18:38] = 255          # 20 wide, solid: art, not letters
        band[15:23, 40:46] = 255
        band[15:23, 48:54] = 255
        self.assertEqual(killfeed.killer_name_start(band, (40, 53)), 40)


class BandShiftTests(unittest.TestCase):
    """The names' baseline places an entry band that padding put too low."""

    @staticmethod
    def _names(base):
        band = np.zeros((34, 200), np.uint8)
        for x0 in (20, 28, 36, 120, 128, 136):
            band[base - 8:base, x0:x0 + 6] = 255
        return band

    def test_both_names_high_move_the_band_up(self):
        self.assertEqual(killfeed.band_shift(self._names(16), (20, 41), (120, 141)), -7)

    def test_names_on_the_row_move_nothing(self):
        self.assertEqual(killfeed.band_shift(self._names(23), (20, 41), (120, 141)), 0)

    def test_disagreeing_names_move_nothing(self):
        band = self._names(23)
        band[:, 20:42] = 0
        for x0 in (20, 28, 36):
            band[6:14, x0:x0 + 6] = 255   # the killer run on art, baseline 14
        self.assertEqual(killfeed.band_shift(band, (20, 41), (120, 141)), 0)


class SplitRunTests(unittest.TestCase):
    """An entry's text rows can drop its plate profile mid-entry; the two
    short runs left are one entry (c40d950031bb 701.0-703.0 s, runs 15-27 and
    31-49, read nowhere until 703.5 s)."""

    @staticmethod
    def _plates(rows_on):
        green = np.zeros((200, 300), dtype=bool)
        red = np.zeros((200, 300), dtype=bool)
        for a, z in rows_on:
            red[a:z, 40:200] = True
            green[a:z, 200:260] = True
        return green, red

    def test_an_entry_split_at_its_text_rows_is_one_band(self):
        green, red = self._plates([(15, 27), (31, 49)])
        self.assertEqual(killfeed._entry_bands(green, red), [(15, 49)])

    def test_the_join_leaves_whole_entries_alone(self):
        green, red = self._plates([(15, 49), (55, 89)])
        self.assertEqual(killfeed._entry_bands(green, red), [(15, 49), (55, 89)])

    def test_the_join_never_takes_a_run_that_stands_alone(self):
        self.assertEqual(killfeed._join_split_runs([(15, 40), (44, 52)]), [(15, 40), (44, 52)])

    def test_the_join_refuses_what_one_entry_cannot_hold(self):
        # Together taller than MAX_BAND_H: two entries' fragments, not one.
        self.assertEqual(killfeed._join_split_runs([(10, 25), (38, 52)]), [(10, 25), (38, 52)])
        # Two stray rows are no plate.
        self.assertEqual(killfeed._join_split_runs([(11, 12), (42, 43)]), [(11, 12), (42, 43)])


if __name__ == "__main__":
    unittest.main()


class IconExtentTests(unittest.TestCase):
    """`icon_extent` grows the divider piece to the whole weapon-slot icon."""

    def _band(self):
        white = np.zeros((20, 200), dtype=bool)
        white[5:15, 80:100] = True            # the divider piece: wx0..wx1 = 80..100
        return white, white.copy()

    def test_a_multi_piece_icon_spans_every_piece(self):
        white, icon = self._band()
        icon[3:17, 75:78] = True              # a ring arc 2 px left of the divider piece
        icon[3:17, 102:106] = True            # and one 2 px right
        self.assertEqual(killfeed.icon_extent(white, icon, 80, 100, 20, 170), (75, 106))

    def test_the_headshot_icon_stays_out(self):
        white, icon = self._band()
        icon[4:16, 109:111] = True            # a headshot cluster 9 px right of the icon
        icon[9:11, 109:119] = True
        self.assertEqual(killfeed.icon_extent(white, icon, 80, 100, 20, 170), (80, 100))

    def test_plate_bleed_and_names_stay_out(self):
        white, icon = self._band()
        icon[17:20, 60:120] = True            # bleed along the band's edge shares no row
        icon[5:15, 30:50] = True              # a name piece before the killer's run ends
        self.assertEqual(killfeed.icon_extent(white, icon, 80, 100, 55, 170), (80, 100))

    def test_the_plate_seam_fallback_is_unchanged(self):
        white, icon = self._band()
        self.assertEqual(killfeed.icon_extent(white, icon, 90, 90, 20, 170), (90, 90))

    def test_pieces_closer_than_the_element_gap_join(self):
        white, icon = self._band()
        gap = killfeed.ELEMENT_GAP
        icon[5:15, 100 + gap - 1:110 + gap] = True     # one column short of the gap
        self.assertEqual(killfeed.icon_extent(white, icon, 80, 100, 20, 170), (80, 110 + gap))

    def test_a_piece_at_the_element_gap_is_another_element(self):
        white, icon = self._band()
        gap = killfeed.ELEMENT_GAP
        icon[5:15, 100 + gap:110 + gap] = True
        self.assertEqual(killfeed.icon_extent(white, icon, 80, 100, 20, 170), (80, 100))

    def test_the_element_with_the_most_ink_under_the_divider_wins(self):
        # The divider piece spans a name's last glyph and the icon, merged over
        # a washed-out plate; the cut mask splits them, and the icon holds more ink.
        white = np.zeros((20, 200), dtype=bool)
        white[5:15, 60:120] = True
        icon = np.zeros_like(white)
        icon[8:12, 60:70] = True                   # a name glyph
        icon[5:15, 80:120] = True                  # the icon, 10 px on
        self.assertEqual(killfeed.icon_extent(white, icon, 60, 120, 20, 170), (80, 120))


# A red killfeed plate and white line art over it, BGR.
RED_PLATE = np.array([60, 60, 200], np.uint8)


def _over(plate, alpha):
    return (plate.astype(np.float32) * (1 - alpha) + 255 * alpha).round().astype(np.uint8)


class PlateWhitenessTests(unittest.TestCase):
    """Line art is judged against the entry's own plate: whiteness is the
    overlay's alpha over the local plate colour."""

    def _band(self, alpha):
        band = np.tile(RED_PLATE, (20, 60, 1))
        band[8:12, 20:40] = _over(RED_PLATE, alpha)
        green, red, _ = killfeed._plate_masks(band, np.ones(band.shape[:2], bool))
        return band, green, red

    def test_whiteness_recovers_the_overlay_alpha(self):
        band, green, red = self._band(0.7)
        w, ok = killfeed.plate_whiteness(band, green, red)
        self.assertTrue(ok.all())
        self.assertAlmostEqual(float(w[10, 30]), 0.7, delta=0.02)
        self.assertAlmostEqual(float(w[2, 30]), 0.0, delta=0.02)

    def test_a_tinted_stroke_the_fixed_cut_drops_passes(self):
        band, green, red = self._band(0.6)
        self.assertFalse(killfeed.icon_white_mask(band)[10, 30])
        m = killfeed.slot_white_mask(band, green, red)
        self.assertTrue(m[8:12, 20:40].all())
        self.assertFalse(m[:8].any() or m[12:].any())

    def test_a_faint_tint_stays_plate(self):
        band, green, red = self._band(0.2)
        self.assertFalse(killfeed.slot_white_mask(band, green, red).any())

    def test_no_plate_falls_back_to_the_fixed_cut(self):
        band = np.full((20, 60, 3), 128, np.uint8)
        band[8:12, 20:40] = 250
        none = np.zeros(band.shape[:2], bool)
        np.testing.assert_array_equal(killfeed.slot_white_mask(band, none, none),
                                      killfeed.icon_white_mask(band))


def _ring_band(ring=True, glyph=True, fill=False, h=34, w=120, cx=60):
    yy, xx = np.mgrid[0:h, 0:w]
    d = np.hypot(xx - cx, yy - (h - 1) / 2)
    r = 0.5 * h
    m = np.zeros((h, w), bool)
    if ring:
        m |= np.abs(d - r) <= 0.8
    if fill:
        m |= d <= r
    if glyph:
        m[12:22, cx - 8:cx + 8] = True
    return m


class RingFitTests(unittest.TestCase):
    """A revive's ring is fitted as a circle; the verdict refuses an unsure fit."""

    def test_a_drawn_ring_is_a_confident_ring(self):
        fit = killfeed.ring_fit(_ring_band(), 60, 34)
        self.assertGreaterEqual(fit["cover"], killfeed.RING_COVER_MIN)
        self.assertAlmostEqual(fit["r"], 17, delta=1.0)
        self.assertEqual(killfeed.ring_verdict(fit), (True, None))

    def test_a_glyph_alone_has_no_ring(self):
        band = np.zeros((34, 120), bool)
        band[12:22, 30:90] = True                    # a gun-like bar
        self.assertEqual(killfeed.ring_verdict(killfeed.ring_fit(band, 60, 34)), (False, None))

    def test_a_filled_disc_is_no_ring(self):
        fit = killfeed.ring_fit(_ring_band(fill=True), 60, 34)
        self.assertEqual(killfeed.ring_verdict(fit), (None, "filled_circle"))

    def test_too_little_ink_and_an_uncertain_fit_refuse(self):
        self.assertEqual(killfeed.ring_verdict(killfeed.ring_fit(np.zeros((34, 120), bool), 60, 34)),
                         (None, "too_little_ink"))
        mid = (killfeed.RING_ABSENT_MAX + killfeed.RING_COVER_MIN) / 2
        self.assertEqual(killfeed.ring_verdict({"cover": mid, "inner_ink": 0.0}),
                         (None, "uncertain_fit"))


class WeaponDescriptorTests(unittest.TestCase):
    """`weapon_icon_observations`: plate guard, ring strip and the `ringed` field."""

    ROI = killfeed.Roi("killfeed", 0.0, 0.0, 1.0, 1.0)

    def _frame(self, mask, plate=RED_PLATE):
        frame = np.tile(plate, mask.shape + (1,))
        frame[mask] = 255
        return frame

    def test_a_ringed_icon_is_stripped_to_its_glyph(self):
        frame = self._frame(_ring_band())
        view = killfeed.EntryView(0, 0, 34, 52, 68, verdict="kill")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertIs(row["ringed"], True)
        self.assertIsNone(row["reason"])
        self.assertEqual((row["ix0"], row["ix1"]), (52, 68))

    def test_an_unringed_icon_says_so(self):
        frame = self._frame(_ring_band(ring=False))
        view = killfeed.EntryView(0, 0, 34, 52, 68, verdict="kill")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertIs(row["ringed"], False)
        self.assertIsNotNone(row["grid"])

    def test_a_box_off_the_plate_refuses(self):
        frame = self._frame(_ring_band(ring=False), plate=np.array([128, 128, 128], np.uint8))
        view = killfeed.EntryView(0, 0, 34, 52, 68, verdict="kill")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertEqual((row["reason"], row["ringed"], row["ring_reason"]), ("no_plate", None, "no_plate"))
        self.assertIsNone(row["grid"])
        self.assertIsNone(row["soft"])
        self.assertIsNone(row["centroid"])

    def test_the_soft_patch_round_trips_the_slot_whiteness(self):
        frame = self._frame(_ring_band(ring=False))
        view = killfeed.EntryView(0, 0, 34, 52, 68, verdict="kill")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        patch, known = killfeed.unpack_soft(row["soft"])
        band = frame[0:34]
        green, red, _w = killfeed._plate_masks(band, np.ones(band.shape[:2], bool))
        w, ok = killfeed.plate_whiteness(band, green, red)
        x0 = row["soft"]["x0"]
        want = np.round(np.clip(w[:, x0:x0 + patch.shape[1]], 0, 1) * 255).astype(np.uint8)
        np.testing.assert_array_equal(patch, want)
        np.testing.assert_array_equal(known, ok[x0:x0 + patch.shape[1]])
        # The patch spans the icon box and SOFT_MARGIN columns either side.
        self.assertEqual(x0, row["ix0"] - killfeed.SOFT_MARGIN)
        self.assertEqual(patch.shape, (34, row["ix1"] - row["ix0"] + 2 * killfeed.SOFT_MARGIN))
        self.assertIs(row["ring_stripped"], False)
        self.assertEqual(row["slot_geom"]["box"], [row["ix0"], 0, row["ix1"], 34])
        self.assertEqual(row["slot_geom"]["scale"]["scale"], 1.0)

    def test_the_centroid_follows_a_sub_pixel_shift(self):
        # A white bar whose left edge column is half covered: the centroid moves
        # by a fraction of a pixel, which the whole-pixel box cannot show.
        def row_for(edge):
            frame = np.tile(RED_PLATE, (34, 120, 1))
            frame[10:24, 55:71] = 255
            plate = RED_PLATE.astype(np.float32)
            frame[10:24, 54] = np.round(plate + edge * (255 - plate)).astype(np.uint8)
            view = killfeed.EntryView(0, 0, 34, 55, 71, verdict="kill", ix0=53, ix1=74)
            return killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                     scale=killfeed.UNIT_SCALE)[0]
        a, b = row_for(0.0), row_for(0.6)
        self.assertIsNotNone(a["centroid"])
        self.assertAlmostEqual(a["centroid"][0], 62.5, places=2)
        self.assertLess(b["centroid"][0], a["centroid"][0])
        self.assertAlmostEqual(a["centroid"][1], b["centroid"][1], places=3)


class WeaponSlotPlacementTests(unittest.TestCase):
    """K2: the slot is cut where the names place the entry, and a divider off
    the band's plate runs refuses."""

    ROI = killfeed.Roi("killfeed", 0.0, 0.0, 1.0, 1.0)
    GREEN = np.array([100, 200, 70], np.uint8)

    def _plates(self, h=80, w=120):
        frame = np.tile(RED_PLATE, (h, w, 1))
        frame[:, 60:] = self.GREEN
        return frame

    def test_the_names_move_the_cut_to_their_entry(self):
        # The view band is rows 0..36, the names' baseline lies at band row 36,
        # 13 below NAME_BASE_ROW: the entry stands at rows 13..49.
        frame = self._plates()
        for c0 in (10, 18, 90, 98):
            frame[26:36, c0:c0 + 5] = 255
        frame[22:42, 40:56] = 255                      # the icon, its lower half below row 36
        view = killfeed.EntryView(0, 0, 36, 40, 56, killer_run=(10, 22),
                                  victim_run=(90, 102), verdict="other")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 80, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertEqual(row["band_shift"], 13)
        self.assertEqual((row["y0"], row["y1"]), (0, 36))      # the binding rows stay
        self.assertEqual(row["slot_geom"]["box"][1::2], [13, 49])
        self.assertIsNone(row["reason"])
        # The whole icon: 20 rows inside the shifted band, 14 inside the view's.
        patch, _known = killfeed.unpack_soft(row["soft"])
        self.assertEqual(int((patch[:, 3:19] == 255).any(axis=1).sum()), 20)

    def test_a_move_that_leaves_the_plate_is_refused(self):
        # Two runs that are not names (portrait art, the headshot mark) agree
        # 10 rows high; the move would put 10 rows of scenery in the band.
        frame = np.tile(np.array([128, 128, 128], np.uint8), (80, 120, 1))
        frame[40:74] = self._plates()[40:74]
        for c0 in (10, 18, 90, 98):
            frame[43:53, c0:c0 + 5] = 255
        frame[50:66, 40:56] = 255
        view = killfeed.EntryView(0, 40, 74, 40, 56, killer_run=(10, 22),
                                  victim_run=(90, 102), verdict="other")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 80, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertEqual(row["band_shift"], 0)
        self.assertIsNone(row["reason"])

    def test_names_on_their_row_move_nothing(self):
        frame = self._plates()
        for c0 in (10, 18, 90, 98):
            frame[13:23, c0:c0 + 5] = 255
        frame[10:26, 40:56] = 255
        view = killfeed.EntryView(0, 0, 34, 40, 56, killer_run=(10, 22),
                                  victim_run=(90, 102), verdict="other")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 80, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertEqual(row["band_shift"], 0)
        self.assertIsNone(row["reason"])

    def test_a_divider_left_of_the_plate_runs_refuses(self):
        # Plate colour touches the divider's columns only in a few rows (portrait
        # art), so the columns pass the plate-behind test; no covered run
        # reaches them: the entry's plate starts at column 60.
        frame = np.tile(np.array([128, 128, 128], np.uint8), (34, 120, 1))
        frame[:, 60:] = self.GREEN
        frame[0:6, 0:40] = RED_PLATE
        frame[10:26, 12:30] = 255
        view = killfeed.EntryView(0, 0, 34, 12, 30, verdict="other")
        row = killfeed.weapon_icon_observations(frame, self.ROI, 120, 34, [view],
                                                   scale=killfeed.UNIT_SCALE)[0]
        self.assertEqual(row["reason"], "off_plate_run")
        self.assertIsNone(row["grid"])
        self.assertIsNone(row["soft"])


class VictimSideTests(unittest.TestCase):
    """The killer's colour behind the weapon icon decides the victim's side;
    a warm victim portrait past a green plate once read the victim as enemy."""

    def _band(self, spans):
        green = np.zeros((34, 300), dtype=bool)
        red = np.zeros((34, 300), dtype=bool)
        for colour, x0, x1 in spans:
            (green if colour == "g" else red)[:, x0:x1] = True
        return green, red

    def test_a_warm_portrait_past_the_victims_plate_is_not_the_plate(self):
        # killer red through the icon (100..160), victim green, portrait red
        green, red = self._band([("r", 100, 190), ("g", 190, 250), ("r", 260, 290)])
        self.assertIs(killfeed.victim_is_ally(green, red, 0, 34, 160), False)
        self.assertIs(killfeed.victim_is_ally(green, red, 0, 34, 160, 100), True)

    def test_a_one_colour_entry_puts_the_victim_on_the_killers_side(self):
        green, red = self._band([("g", 100, 260)])
        self.assertIs(killfeed.victim_is_ally(green, red, 0, 34, 160, 100), True)

    def test_the_killer_side_is_the_plate_behind_the_icon(self):
        kill = self._band([("r", 100, 190), ("g", 190, 250)])
        self.assertIs(killfeed.killer_is_ally(*kill, 0, 34, 100, 160), False)
        revive = self._band([("g", 100, 260)])
        self.assertIs(killfeed.killer_is_ally(*revive, 0, 34, 100, 160), True)
        # Neither colour holds twice the other behind the icon: undecided.
        mixed = self._band([("r", 100, 130), ("g", 130, 160)])
        self.assertIsNone(killfeed.killer_is_ally(*mixed, 0, 34, 100, 160))
        # The plate seam stands in for an icon on an ability kill: no width.
        self.assertIsNone(killfeed.killer_is_ally(*kill, 0, 34, 150, 150))

    def test_same_side_slots_need_both_plates_read_and_equal(self):
        read = killfeed.KillfeedRead(
            entries=3, slots=(0, 1, 2), player_kill=False, player_death=False,
            entry_ys=(15, 55, 95), entry_ally=(True, True, None),
            entry_killer_ally=(True, False, None))
        self.assertEqual(read.same_side_mask, 0b001)
        # A read stored before the killer's plate was kept marks no slot.
        old = killfeed.KillfeedRead(entries=1, slots=(0,), player_kill=False,
                                    player_death=False, entry_ys=(15,), entry_ally=(True,))
        self.assertEqual(old.same_side_mask, 0)


class RingedDividerTests(unittest.TestCase):
    """A ringed icon divides the names at its whole extent, whichever piece
    wins. Built on bdfdcf009dba 687-689 s (C:/Users/grant/Videos/2026-08-23
    19-25-23.mp4), "Evan [Resurrection] Clove": the ring breaks into a left
    arc, an emblem and a right arc, and a glyph-sized emblem piece passed for
    a name beside either arc, so the divider read 317, 328 or 347 frame to
    frame and one plate became three entry tracks."""

    CX, R = 338, 20

    def _band(self, left_w, right_w):
        white = np.zeros((34, 480), dtype=bool)
        for x0, y0, w, h in ((279, 12, 7, 11), (287, 15, 7, 8), (295, 15, 7, 8),
                             (303, 15, 7, 8),                      # "Evan", baseline 23
                             (375, 12, 10, 12), (387, 12, 3, 12), (392, 15, 7, 9),
                             (401, 15, 7, 9), (410, 15, 7, 9),     # "Clove", baseline 24
                             (334, 14, 7, 8)):                     # the emblem's glyph-sized piece
            white[y0:y0 + h, x0:x0 + w] = True
        # The ring, clipped by the band and broken at its top and bottom into
        # a left and a right arc of the given stroke widths.
        yy, xx = np.mgrid[0:34, 0:480]
        d = np.hypot(xx - self.CX, yy - 16.5)
        gap = np.abs(xx - self.CX) < 6
        white |= (d <= self.R) & (d > self.R - left_w) & (xx < self.CX) & ~gap
        white |= (d <= self.R) & (d > self.R - right_w) & (xx > self.CX) & ~gap
        white[10:28, 330] = white[10:28, 346] = True               # the emblem's outline
        white[10, 330:347] = white[27, 330:347] = True
        value = np.zeros((34, 480, 3), dtype=np.uint8)
        value[...] = (60, 150, 120)
        value[white] = (0, 0, 255)
        return white, value

    def _extent(self, white):
        cols = np.nonzero(white[:, 312:370].any(axis=0))[0] + 312
        return int(cols[0]), int(cols[-1]) + 1

    def test_either_arc_winning_gives_one_divider(self):
        for left_w, right_w in ((3, 2), (2, 3)):
            white, value = self._band(left_w, right_w)
            parsed = killfeed._band_text(white, value=value, s=killfeed.UNIT_SCALE)
            self.assertNotIsInstance(parsed, str)
            _text, wx0, wx1 = parsed
            self.assertEqual((wx0, wx1), self._extent(white), (left_w, right_w))

    def test_the_emblem_piece_is_not_a_name(self):
        white, value = self._band(2, 3)
        text, wx0, wx1 = killfeed._band_text(white, value=value, s=killfeed.UNIT_SCALE)
        self.assertEqual(killfeed.name_run(text[:, :wx0], -1, killfeed.UNIT_SCALE), (279, 309))
        vrun = killfeed.name_run(text[:, wx1:], +1, killfeed.UNIT_SCALE)
        self.assertEqual(vrun[0] + wx1, 375)

    def test_a_piece_spanning_a_name_does_not_join_the_icon(self):
        # bdfdcf009dba 663.5 s: scenery and a portrait merged into one tall
        # piece across the killer's name up to the ring; joined, the divider
        # swallowed both names.
        white, value = self._band(3, 2)
        extent = self._extent(white)
        white[0:2, 200:extent[0] - 2] = white[32:34, 200:extent[0] - 2] = white[:, 200] = True
        value[white] = (0, 0, 255)
        _text, wx0, wx1 = killfeed._band_text(white, value=value, s=killfeed.UNIT_SCALE)
        self.assertEqual((wx0, wx1), extent)

    def test_a_gun_does_not_grow_into_a_pale_plate(self):
        # a06f04a0059f 1687.5 s (C:/Users/grant/Videos/2026-08-26 09-56-37.mp4):
        # a gun beside a pale plate's tall wash; no ring, so the divider stays
        # the gun and the wash stays off it.
        white = np.zeros((34, 480), dtype=bool)
        for x0 in (93, 101, 109):                                  # killer name
            white[15:23, x0:x0 + 6] = True
        for x0 in (373, 381, 389, 397):                            # victim name
            white[15:23, x0:x0 + 6] = True
        white[6:29, 233:310] = True                                # the gun
        white[0:34, 200:231:3] = True                              # the wash's strokes
        white[0, 200:231] = True
        value = np.zeros((34, 480, 3), dtype=np.uint8)
        value[...] = (60, 150, 120)
        value[white] = (0, 0, 255)
        _text, wx0, wx1 = killfeed._band_text(white, value=value, s=killfeed.UNIT_SCALE)
        self.assertEqual((wx0, wx1), (233, 310))
