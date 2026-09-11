"""The two agent portraits every killfeed entry draws, and the plate under them."""
import unittest

import cv2
import numpy as np

from reticle import appearance, killfeed
from reticle.killfeed import (PORTRAIT_ASPECT, EntryView, _entry_columns,
                              _portrait_edge, portrait_observations)
from reticle.profiles import Roi


def _bgr(h, s, v):
    """One BGR triple from an HSV point, so a fixture cannot drift from the
    detector's own colour windows the way this one first did: hand-picked
    greens fell outside `GREEN_H`, no plate was found at all, and the test
    failed for the fixture's reason rather than the code's."""
    return tuple(int(c) for c in cv2.cvtColor(
        np.uint8([[[h, s, v]]]), cv2.COLOR_HSV2BGR)[0, 0])


GREEN = _bgr(sum(killfeed.GREEN_H) // 2, sum(killfeed.GREEN_S) // 2, 200)
RED = _bgr(4, 200, 200)
WHITE = (245, 245, 245)
#: Neither plate colour, and saturated enough to survive the value floor.
ART_A = _bgr(150, 200, 210)
ART_B = _bgr(30, 210, 200)


def band_frame(h=40, w=200, bh=20):
    """One synthetic entry: portrait, plate with text, plate, portrait.

    Laid out the way the game draws it -- `[portrait][name][icon][name]
    [portrait]` -- so the walk has to step over the text to find the gap.
    """
    frame = np.zeros((h, w, 3), np.uint8)
    y0, y1 = 4, 4 + bh
    pw = int(PORTRAIT_ASPECT * bh)
    # killer portrait: saturated art, deliberately neither plate colour
    frame[y0:y1, 10:10 + pw] = ART_A
    frame[y0:y1, 10 + pw:110] = GREEN          # killer plate
    frame[y0:y1, 60:70] = WHITE                # killer name, drawn ON the plate
    frame[y0:y1, 110:150] = RED                # victim plate
    frame[y0:y1, 120:130] = WHITE              # victim name
    frame[y0:y1, 150:150 + pw] = ART_B           # victim portrait
    return frame, y0, y1, bh, pw


class WalkTests(unittest.TestCase):
    """The walk stops at the portrait; every rule that did not ran off the end."""

    def test_the_walk_steps_over_text_and_stops_at_the_portrait(self):
        frame, y0, y1, bh, pw = band_frame()
        green = np.all(frame == GREEN, axis=2)
        red = np.all(frame == RED, axis=2)
        white = np.all(frame == WHITE, axis=2).astype(np.uint8) * 255
        on = _entry_columns(green[y0:y1], red[y0:y1], white[y0:y1], bh)
        # From inside the killer name, walking left: over the text, over the
        # plate, and stopping where the portrait begins.
        self.assertEqual(_portrait_edge(on, 64, -1, frame.shape[1]), 10 + pw - 1)
        # And right from the victim name to the victim portrait.
        self.assertEqual(_portrait_edge(on, 124, +1, frame.shape[1]), 150)

    def test_a_band_with_no_gap_refuses(self):
        frame, y0, y1, bh, _pw = band_frame()
        frame[y0:y1, :] = GREEN                # plate edge to edge, no portrait
        green = np.all(frame == GREEN, axis=2)
        red = np.zeros_like(green)
        white = np.zeros(green.shape, np.uint8)
        on = _entry_columns(green[y0:y1], red[y0:y1], white[y0:y1], bh)
        self.assertIsNone(_portrait_edge(on, 64, -1, frame.shape[1]))


class ObservationTests(unittest.TestCase):
    def observe(self, frame, y0, y1, ally=True):
        h, w = frame.shape[:2]
        view = EntryView(0, y0, y1, 80, 100, killer_run=(60, 70),
                         victim_run=(120, 130), victim_ally=ally)
        return portrait_observations(frame, Roi("kf", 0.0, 0.0, 1.0, 1.0), w, h,
                                     views=[view])

    def test_both_portraits_are_found_and_neither_is_named(self):
        frame, y0, y1, _bh, _pw = band_frame()
        got = self.observe(frame, y0, y1)
        self.assertEqual([o["role"] for o in got], ["killer", "victim"])
        for o in got:
            self.assertNotIn("agent", o)
            self.assertGreater(len(o["composition"]), 0)
            self.assertEqual(o["reason"], "")

    def test_the_killer_and_the_victim_are_on_opposite_sides(self):
        frame, y0, y1, _bh, _pw = band_frame()
        killer, victim = self.observe(frame, y0, y1, ally=True)
        self.assertTrue(victim["ally"])
        self.assertFalse(killer["ally"])
        killer, victim = self.observe(frame, y0, y1, ally=False)
        self.assertFalse(victim["ally"])
        self.assertTrue(killer["ally"])

    def test_an_undecidable_plate_leaves_the_side_unknown(self):
        frame, y0, y1, _bh, _pw = band_frame()
        for o in self.observe(frame, y0, y1, ally=None):
            self.assertIsNone(o["ally"])

    def test_the_plate_is_masked_out_of_the_descriptor(self):
        """Unmasked, every ally portrait would look like the ally plate."""
        frame, y0, y1, _bh, pw = band_frame()
        killer, _victim = self.observe(frame, y0, y1)
        art = frame[y0:y1, 10:10 + pw]
        self.assertGreater(appearance.agrees(killer["composition"],
                                             appearance.hsv_composition(art)), 0.95)
        plate = np.full_like(art, GREEN, dtype=np.uint8)
        self.assertLess(appearance.agrees(killer["composition"],
                                          appearance.hsv_composition(plate)), 0.05)

    def test_two_different_portraits_do_not_agree(self):
        frame, y0, y1, _bh, _pw = band_frame()
        killer, victim = self.observe(frame, y0, y1)
        self.assertLess(appearance.agrees(killer["composition"],
                                          victim["composition"]), 0.2)

    def test_a_portrait_cut_by_the_ROI_edge_reports_how_much(self):
        """The victim's portrait sits at the entry's right end and gets cut."""
        half = int(PORTRAIT_ASPECT * 20) // 2
        frame, y0, y1, _bh, pw = band_frame(w=150 + half)
        got = self.observe(frame, y0, y1)
        victim = next(o for o in got if o["role"] == "victim")
        self.assertGreater(victim["clipped"], 0.4)
        self.assertEqual(next(o for o in got if o["role"] == "killer")
                         ["clipped"], 0.0)

    def test_an_entry_with_no_name_runs_yields_nothing(self):
        frame, y0, y1, _bh, _pw = band_frame()
        h, w = frame.shape[:2]
        view = EntryView(0, y0, y1, verdict="unparsed")
        self.assertEqual(portrait_observations(frame, Roi("kf", 0.0, 0.0, 1.0, 1.0),
                                               w, h, views=[view]), [])


class CompositionTests(unittest.TestCase):
    def test_a_crop_with_too_few_pixels_describes_nothing(self):
        self.assertEqual(appearance.hsv_composition(
            np.zeros((3, 3, 3), np.uint8)).size, 0)
        self.assertEqual(appearance.agrees(np.zeros(0), np.zeros(0)), 0.0)

    def test_a_composition_sums_to_one(self):
        art = np.random.RandomState(0).randint(0, 255, (20, 40, 3), dtype=np.uint8)
        self.assertAlmostEqual(float(appearance.hsv_composition(art).sum()), 1.0, 5)

    def test_the_mask_is_what_is_described(self):
        art = np.zeros((20, 40, 3), np.uint8)
        art[:, :20] = (0, 0, 255)
        art[:, 20:] = (0, 255, 0)
        mask = np.zeros((20, 40), bool)
        mask[:, :20] = True
        self.assertGreater(appearance.agrees(
            appearance.hsv_composition(art, mask),
            appearance.hsv_composition(art[:, :20])), 0.99)


if __name__ == "__main__":
    unittest.main()
