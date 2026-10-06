import unittest

import numpy as np

from reticle import killfeed
from reticle.killfeed import (READOUT_BOX, READOUT_REFUSAL, readout_cover, readout_prior,
                              shooting_error_readout)

ROI_W, ROI_H = 489, 265


def _crop(box=True, background=20, value=255, skip=()):
    """A killfeed ROI crop over a flat background, with the readout's box
    outline drawn 1 px wide at its prior, less the borders named in `skip`."""
    c = np.full((ROI_H, ROI_W, 3), background, np.uint8)
    if box:
        x0, y0, x1, y1 = READOUT_BOX
        if "top" not in skip:
            c[y0, x0:x1 + 1] = value
        if "bottom" not in skip:
            c[y1, x0:x1 + 1] = value
        if "left" not in skip:
            c[y0:y1 + 1, x0] = value
        if "right" not in skip:
            c[y0:y1 + 1, x1] = value
    return c


def _frame(crop):
    f = np.zeros((1080, 1920, 3), np.uint8)
    f[81:81 + ROI_H, 1421:1421 + ROI_W] = crop
    return f


class ReadoutDetectorTests(unittest.TestCase):
    def test_the_drawn_box_is_present(self):
        got = shooting_error_readout(_crop())
        self.assertIs(got["present"], True)
        self.assertEqual(set(got["borders"]), {"top", "bottom", "left", "right"})

    def test_one_hidden_border_still_reads_the_box(self):
        """A graph bar along the right border fails that line on frames that
        show the box (4f207c0c4e39 224.5 s)."""
        self.assertIs(shooting_error_readout(_crop(skip=("right",)))["present"], True)

    def test_two_hidden_borders_read_no_box(self):
        self.assertIs(shooting_error_readout(_crop(skip=("right", "top")))["present"], False)

    def test_a_dark_frame_without_the_box_reads_none(self):
        self.assertIs(shooting_error_readout(_crop(box=False))["present"], False)

    def test_a_shifted_box_within_the_search_is_found(self):
        c = np.full((ROI_H, ROI_W, 3), 20, np.uint8)
        x0, y0, x1, y1 = READOUT_BOX
        c[y0 + 2, x0:x1 + 1] = c[y1 + 2, x0:x1 + 1] = 255
        c[y0 + 2:y1 + 3, x0 + 1] = c[y0 + 2:y1 + 3, x1 + 1] = 255
        self.assertIs(shooting_error_readout(c)["present"], True)

    def test_a_bright_scene_is_undecidable_not_absent(self):
        """Every border bright, none a line: the frame cannot tell."""
        got = shooting_error_readout(_crop(box=False, background=240))
        self.assertIsNone(got["present"])
        self.assertEqual(got["reason"], "bright_scene")


class ReadoutCoverTests(unittest.TestCase):
    def test_a_drawn_box_covers_its_footprint(self):
        foot, basis = readout_cover({"present": True}, np.ones((ROI_H, ROI_W), bool))
        self.assertEqual(basis, "frame")
        self.assertEqual(foot, readout_prior(shape=(ROI_H, ROI_W)))
        self.assertEqual(foot[2], ROI_W)            # the values run to the ROI's edge

    def test_an_undecidable_frame_takes_the_session_mask(self):
        mask = np.ones((ROI_H, ROI_W), bool)
        self.assertEqual(readout_cover({"present": None}, mask), (None, None))
        mask[140:195, 341:458] = False
        foot, basis = readout_cover({"present": None}, mask)
        self.assertEqual(basis, "session_mask")
        self.assertIsNotNone(foot)

    def test_a_frame_without_the_box_covers_nothing_whatever_the_mask(self):
        mask = np.zeros((ROI_H, ROI_W), bool)
        self.assertEqual(readout_cover({"present": False}, mask), (None, None))


class ReadoutRefusalTests(unittest.TestCase):
    def _read(self, bands, refusals, box=True):
        return read_with_bands_on(_frame(_crop(box=box)), bands, refusals)

    def test_a_band_under_the_box_refuses_and_reads_no_name(self):
        parsed = (np.zeros((34, 489), np.uint8), 200, 230)   # a parse that would read
        got = self._read([(132, 166)], [parsed])
        self.assertEqual(got.entries, 1)
        self.assertEqual(got.unattributed, 1)
        self.assertFalse(got.player_kill or got.player_death)
        self.assertEqual(got.readout_slots, (3,))
        self.assertEqual(got.readout_mask, 1 << 3)
        self.assertIs(got.readout, True)
        self.assertEqual(got.readout_basis, "frame")

    def test_a_band_above_the_box_is_untouched(self):
        got = self._read([(93, 127)], ["no_divider"])
        self.assertEqual(got.unparsed, 1)
        self.assertEqual(got.readout_slots, ())

    def test_without_the_box_nothing_changes(self):
        got = self._read([(132, 166)], ["occluded"], box=False)
        self.assertEqual(got.unattributed, 1)
        self.assertEqual(got.readout_slots, ())
        self.assertIs(got.readout, False)
        self.assertIsNone(got.readout_basis)


def read_with_bands_on(frame, bands, refusals):
    """`read_with_bands` over a given frame, so the readout detector sees it."""
    from unittest import mock
    from reticle.killfeed import read_killfeed
    from tests.test_killfeed import _roi
    plate = np.ones((ROI_H, ROI_W), dtype=bool)
    answers = list(refusals)
    with mock.patch.object(killfeed, "_plate_masks", return_value=(plate, plate, plate)), \
            mock.patch.object(killfeed, "_entry_bands", return_value=bands), \
            mock.patch.object(killfeed, "_one_colour_bands", return_value=[]), \
            mock.patch.object(killfeed, "_match_me", return_value=(18, 0.9)), \
            mock.patch.object(killfeed, "icon_extent", return_value=(200, 230)), \
            mock.patch.object(killfeed, "_band_text", side_effect=lambda *a, **k: answers.pop(0)):
        return read_killfeed(frame, _roi(), 1920, 1080, np.ones((ROI_H, ROI_W), dtype=bool))


if __name__ == "__main__":
    unittest.main()
