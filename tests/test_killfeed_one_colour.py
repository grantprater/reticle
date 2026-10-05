"""One-colour killfeed entries and thin-stroked icons, on real crops.

Each fixture is the top 140 rows of the `killfeed` ROI, read from the ROI
crop cache (lossless PNG, no video): spike and self kills drawn in one plate
colour, a team kill, Raze's Paint Shells, and a striped wall that forms a
one-colour candidate band with no entry on it.
"""
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import killfeed
from reticle.killfeed import analyse_killfeed, killfeed_roi, read_killfeed
from reticle.profiles import get_profile

DATA = Path(__file__).parent / "data" / "killfeed_one_colour"


def _frame(name: str):
    roi = killfeed_roi(get_profile("valorant-16x9"))
    x0, y0, x1, y1 = roi.pixels(1920, 1080)
    crop = cv2.imread(str(DATA / name), cv2.IMREAD_COLOR)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]] = crop
    return frame, roi, np.ones((y1 - y0, x1 - x0), dtype=bool)


def _views(name: str, dropped=None):
    frame, roi, mask = _frame(name)
    return analyse_killfeed(frame, roi, 1920, 1080, mask, dropped=dropped)


def _entries(views):
    return [v for v in views if v.verdict != "empty_band"]


class OneColourEntryTests(unittest.TestCase):
    def test_a_red_spike_banner_is_an_entry(self):
        """e37fdeca944f 2039.0 s, Malboro -> Malboro by the spike: one red
        banner, no green in any row, so the both-colour profile read 0."""
        got = _entries(_views("e37fdeca944f_20390.png"))
        self.assertEqual(len(got), 1)
        v = got[0]
        self.assertEqual(v.slot, 0)
        self.assertGreater(v.wx1, v.wx0)          # an icon divides, not a seam
        self.assertTrue(300 <= v.wx0 and v.wx1 <= 345, (v.wx0, v.wx1))
        self.assertIs(v.killer_ally, False)
        self.assertIs(v.victim_ally, False)

    def test_a_not_dead_yet_expiry_divides_at_its_whole_icon(self):
        """ff636d173b07 1247.0 s, MommysMethpipe -> MommysMethpipe, Clove's
        Not Dead Yet expiring: a red banner whose icon breaks into three
        pieces. The left piece sits on the names' baseline touching the rest,
        and read as the killer's last letter (`one_colour:no_divider`)."""
        dropped = []
        got = _entries(_views("ff636d173b07_12470.png", dropped))
        self.assertEqual(len(got), 1, dropped)
        v = got[0]
        self.assertEqual(v.slot, 0)
        self.assertEqual((v.wx0, v.wx1), (245, 267))
        self.assertIs(v.victim_ally, False)

    def test_warm_scenery_above_the_first_slot_leaves_the_banner_on_the_grid(self):
        """ff636d173b07 1247.5 s, the same expiry over a warm ceiling: the
        one-colour rows run 0-183, and a PITCH split from row 0 (0-37,
        37-73, ...) held no band on the banner at 15-49 (hud-0.25.0 and
        earlier). The run starts above the first slot, so the resting slots
        place its bands."""
        dropped = []
        got = _entries(_views("ff636d173b07_12475.png", dropped))
        self.assertEqual(len(got), 1, dropped)
        v = got[0]
        self.assertEqual((v.slot, v.y0, v.y1), (0, 15, 49))
        self.assertEqual((v.wx0, v.wx1), (245, 267))
        self.assertTrue(all(a >= 15 for _slot, a, _z, _why in dropped), dropped)

    def test_two_one_colour_banners_stack_and_scenery_joins_the_lower(self):
        """4f207c0c4e39 1582.0 s: a red and a teal spike banner. The teal one
        runs into a teal sign below it (53 rows), and the slot grid places it."""
        got = _entries(_views("4f207c0c4e39_15820.png"))
        self.assertEqual([v.slot for v in got], [0, 1])
        self.assertEqual([(v.killer_ally, v.victim_ally) for v in got],
                         [(False, False), (True, True)])
        self.assertTrue(all(v.wx1 > v.wx0 for v in got))
        self.assertTrue(330 <= got[1].wx0 and got[1].wx1 <= 365, (got[1].wx0, got[1].wx1))

    def test_a_team_kill_by_the_player_reads_as_a_kill(self):
        """043bafca271a 1880.5 s, Me (Sova) -> Phoenix, all green."""
        got = _entries(_views("043bafca271a_18805.png"))
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].verdict, "kill")
        self.assertIs(got[0].killer_ally, True)

    def test_a_striped_wall_is_no_entry_and_says_why(self):
        """c62c2b06bcfb 109.0 s: below two real entries, stripes make glyphs
        either side of a 137 px blob on a one-colour candidate; no name runs
        nor plate flank it. The refusal reaches the stored row."""
        dropped = []
        got = _entries(_views("c62c2b06bcfb_01090.png", dropped))
        self.assertEqual([v.slot for v in got], [0, 1])
        self.assertTrue(any(str(d[3]).startswith("one_colour:") for d in dropped), dropped)
        frame, roi, mask = _frame("c62c2b06bcfb_01090.png")
        read = read_killfeed(frame, roi, 1920, 1080, mask)
        self.assertEqual(read.entries, 2)
        self.assertGreaterEqual(read.dropped_bands, 1)
        self.assertIsNotNone(read.dropped_band_reason)


class ThinIconTests(unittest.TestCase):
    def test_paint_shells_divides_its_entry(self):
        """4f207c0c4e39 1760.5 s, CEOofTree [Paint Shells] suko: the thin ring
        broke into pieces under MIN_COMP_AREA and the band went `no_icon`.
        The plate-relative cut joins it, and the divider is the icon."""
        got = _entries(_views("4f207c0c4e39_17605.png"))
        self.assertEqual(len(got), 2)
        self.assertEqual(got[0].slot, 0)
        self.assertTrue(335 <= got[0].wx0 and got[0].wx1 <= 362, (got[0].wx0, got[0].wx1))

    def test_a_strand_of_the_killers_portrait_never_divides(self):
        """96aa1ae9b96f 1043.5 s, inceloser [ability] Whiff A Lot: the softer
        cut keeps strands of the killer's hair (193-216); a divider needs a run
        of name glyphs on each side, so the icon divides, as on the next frame."""
        got = _entries(_views("96aa1ae9b96f_10435.png"))
        self.assertEqual(len(got), 1)
        self.assertTrue(290 <= got[0].wx0 and got[0].wx1 <= 320, (got[0].wx0, got[0].wx1))

    def test_the_thin_pass_needs_a_seam(self):
        """The plate-relative pass runs only where the plates meet at one seam."""
        frame, roi, mask = _frame("4f207c0c4e39_17605.png")
        x0, y0, x1, y1 = roi.pixels(1920, 1080)
        crop = frame[y0:y1, x0:x1]
        g, r, w = killfeed._plate_masks(crop, mask)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        a, z = 15, 49
        soft = lambda: killfeed.slot_white_mask(crop[a:z], g[a:z], r[a:z]) & mask[a:z]
        self.assertEqual(killfeed._band_text(w[a:z] > 0, mask[a:z], (g[a:z], r[a:z]), hsv[a:z]),
                         "no_icon")
        got = killfeed._band_text(w[a:z] > 0, mask[a:z], (g[a:z], r[a:z]), hsv[a:z],
                                  soft_white=soft)
        self.assertIsInstance(got, tuple)
        no_seam = (g[a:z] | r[a:z], np.zeros_like(r[a:z]))
        self.assertEqual(killfeed._band_text(w[a:z] > 0, mask[a:z], no_seam, hsv[a:z],
                                             soft_white=soft), "no_icon")


if __name__ == "__main__":
    unittest.main()
