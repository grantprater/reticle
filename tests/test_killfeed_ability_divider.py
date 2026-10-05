"""Ability kills whose icon the line-art pass passed over, on real crops.

Each fixture is the top 60 rows of the `killfeed` ROI, read from the ROI crop
cache (lossless PNG, no video). In both, a portrait's edge is a knife-sized
line-art piece with name glyphs either side of it, and the first pass took it
for the icon; the weapon reader then refused the row. The icon is drawn on
the killer's plate [domain:killfeed/weapon-cell], so a divider's centre must
lie left of the seam with plate behind it (hud-0.24.0).
"""
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle.killfeed import analyse_killfeed, killfeed_roi, weapon_icon_observations
from reticle.profiles import get_profile

DATA = Path(__file__).parent / "data" / "killfeed_ability"


def _read(name: str):
    roi = killfeed_roi(get_profile("valorant-16x9"))
    x0, y0, x1, y1 = roi.pixels(1920, 1080)
    crop = cv2.imread(str(DATA / name), cv2.IMREAD_COLOR)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[y0:y0 + crop.shape[0], x0:x1] = crop
    mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
    views = [v for v in analyse_killfeed(frame, roi, 1920, 1080, mask) if v.slot == 0]
    return views, weapon_icon_observations(frame, roi, 1920, 1080, views)


class AbilityDividerTests(unittest.TestCase):
    def test_overdrive_divides_at_its_strokes_not_the_victims_portrait(self):
        """a1a995e6b19b 742.0 s, Neon [Overdrive] Deadlock: the seam at 339;
        the victim portrait's edge (420-426) divided before, refused
        `off_plate_run`."""
        views, rows = _read("a1a995e6b19b_07420.png")
        self.assertEqual(len(views), 1)
        v = views[0]
        self.assertTrue(300 <= v.wx0 and v.wx1 <= 339, (v.wx0, v.wx1))
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["reason"])

    def test_annihilation_divides_at_its_icon_not_the_killers_portrait(self):
        """5822b6646448 925.5 s, barden [Annihilation] PoopyNadia over bright
        sky: no plate behind the killer portrait's right
        edge (214-221) divided before, refused `no_plate`."""
        views, rows = _read("5822b6646448_09255.png")
        self.assertEqual(len(views), 1)
        v = views[0]
        self.assertTrue(280 <= v.wx0 and v.wx1 <= 321, (v.wx0, v.wx1))
        self.assertIsNone(rows[0]["reason"])

    def test_a_gun_divides_where_its_white_columns_break_the_plate_run(self):
        """3694746e4e54 296.0 s, Vyse [Vandal, wallbang, headshot] jhulsunkwn:
        the gun's white columns are not plate columns, so the killer's run
        starts inside the gun (201); a gate on that run moved the divider to
        the headshot mark (291-314)."""
        views, rows = _read("3694746e4e54_02960.png")
        self.assertEqual(len(views), 1)
        v = views[0]
        self.assertTrue(v.wx0 <= 160 and 230 <= v.wx1 <= 250, (v.wx0, v.wx1))
        self.assertIsNone(rows[0]["reason"])


if __name__ == "__main__":
    unittest.main()
