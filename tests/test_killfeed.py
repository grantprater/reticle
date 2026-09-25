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


if __name__ == "__main__":
    unittest.main()
