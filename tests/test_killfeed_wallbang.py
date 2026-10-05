"""The killfeed's wallbang mark [domain:killfeed/wallbang-mark]: the reader's
soft score and cut (`killfeed.wallbang_mark`), and one answer per entry
(`adjudication.weapon.entry_wallbang`)."""
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import killfeed
from reticle.adjudication.weapon import entry_wallbang
from reticle.killfeed import (UNIT_SCALE, WALLBANG_CUT, analyse_killfeed, killfeed_roi,
                              wallbang_mark, wallbang_template, weapon_icon_observations)
from reticle.profiles import get_profile
from reticle.store import Store

DATA = Path(__file__).parent / "data" / "killfeed_wallbang"


def _texture() -> np.ndarray:
    """A stand-in texture: a bullet and a wall bar, 64 x 64 coverage."""
    t = np.zeros((64, 64), np.float32)
    t[26:38, 4:40] = 1.0
    t[:, 56:62] = 1.0
    for k in range(12):
        t[4 + k, 40 + k] = t[59 - k, 40 + k] = 1.0
    return t


class WallbangMarkTests(unittest.TestCase):
    def test_a_drawn_mark_scores_high_and_its_absence_low(self):
        tpl = _texture()
        band = np.zeros((34, 200), np.float32)
        drawn = cv2.resize(tpl, (24, 24), interpolation=cv2.INTER_AREA)
        band[5:29, 120:144] = drawn
        got = wallbang_mark(band, 100, 170, tpl, UNIT_SCALE)
        self.assertTrue(got["wallbang"])
        self.assertGreater(got["wallbang_score"], 0.95)
        self.assertEqual(got["wallbang_x"], 120)
        self.assertFalse(wallbang_mark(np.zeros_like(band), 100, 170, tpl, UNIT_SCALE)["wallbang"])

    def test_no_room_and_no_texture_are_told_apart(self):
        band = np.zeros((34, 200), np.float32)
        narrow = wallbang_mark(band, 100, 120, _texture(), UNIT_SCALE)
        self.assertEqual((narrow["wallbang"], narrow["wallbang_reason"]), (False, "no_room"))
        none = wallbang_mark(band, 100, 170, None, UNIT_SCALE)
        self.assertEqual((none["wallbang"], none["wallbang_reason"]), (None, "no_template"))

    def test_an_entry_takes_the_median_of_its_views(self):
        rows = [{"wallbang_score": s, "wallbang_reason": None} for s in (0.2, 0.9, 0.95)]
        got = entry_wallbang(rows)
        self.assertEqual((got["wallbang"], got["score"], got["views"]), (True, 0.9, 3))
        self.assertGreaterEqual(got["score"], WALLBANG_CUT)
        room = entry_wallbang([{"wallbang_score": None, "wallbang_reason": "no_room"}])
        self.assertEqual((room["wallbang"], room["reason"]), (False, "no_room"))
        self.assertEqual(entry_wallbang([])["reason"], "no_observation")


@unittest.skipUnless((Path(Store().root) / killfeed.WALLBANG_TEXTURE).is_file(),
                     "the store holds no game files")
class WallbangCropTests(unittest.TestCase):
    """3694746e4e54 220.0 s, slot 0, "Articuno [Bandit] [mark] eeee", the top
    60 rows of the `killfeed` ROI from the crop cache (lossless PNG)."""

    def test_the_game_texture_finds_the_mark_on_a_real_entry(self):
        roi = killfeed_roi(get_profile("valorant-16x9"))
        x0, y0, x1, y1 = roi.pixels(1920, 1080)
        crop = cv2.imread(str(DATA / "3694746e4e54_02200.png"), cv2.IMREAD_COLOR)
        frame = np.zeros((1080, 1920, 3), np.uint8)
        frame[y0:y0 + crop.shape[0], x0:x1] = crop
        mask = np.ones((y1 - y0, x1 - x0), dtype=bool)
        views = [v for v in analyse_killfeed(frame, roi, 1920, 1080, mask) if v.slot == 0]
        rows = weapon_icon_observations(frame, roi, 1920, 1080, views,
                                        wallbang_tpl=wallbang_template(Store().root))
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["wallbang"])
        self.assertGreater(rows[0]["wallbang_score"], 0.9)
        self.assertTrue(rows[0]["ix1"] <= rows[0]["wallbang_x"] < 369)

    def test_the_headshot_mark_scores_under_the_cut(self):
        # the game's headshot texture, drawn mirrored as the killfeed draws it
        # [domain:killfeed/headshot-icon], where a wallbang mark would sit
        root = Path(Store().root)
        hs = cv2.imread(str(root / killfeed.WALLBANG_TEXTURE.replace(
            "Assets/TX_Hud_ThroughWalls_S.png",
            "KillFeed_Assists/Textures/KillfeedIcons/TX_Kilfeed_Headshot.png")), cv2.IMREAD_UNCHANGED)
        band = np.zeros((34, 200), np.float32)
        band[5:29, 120:144] = cv2.resize(hs[:, ::-1, 3].astype(np.float32) / 255.0, (24, 24),
                                         interpolation=cv2.INTER_AREA)
        got = wallbang_mark(band, 100, 170, wallbang_template(root), UNIT_SCALE)
        self.assertFalse(got["wallbang"])
        self.assertLess(got["wallbang_score"], WALLBANG_CUT)


if __name__ == "__main__":
    unittest.main()
