"""A word of a name holding a space is never "Me" (`killfeed.ME_WORD_GAP`).

Crops are the top rows of the `killfeed` ROI from the hud crop cache
(lossless PNG). 066741deafe5 prints the player's account name, and its enemy
"Mga Yawa" read as "Me" on all 68 stored player-entry frames at hud-0.27.0;
c40d950031bb prints "Me", whose kill and death must still read."""
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import killfeed
from reticle.killfeed import killfeed_roi, read_killfeed
from reticle.profiles import get_profile

DATA = Path(__file__).parent / "data" / "killfeed_me_word"


def _read(name: str, profile: str):
    roi = killfeed_roi(get_profile(profile))
    x0, y0, x1, _y1 = roi.pixels(1920, 1080)
    crop = cv2.imread(str(DATA / name), cv2.IMREAD_COLOR)
    frame = np.zeros((1080, 1920, 3), np.uint8)
    frame[y0:y0 + crop.shape[0], x0:x1] = crop
    return read_killfeed(frame, roi, 1920, 1080, profile_name=profile)


@unittest.skipUnless(killfeed.me_template("valorant-16x9") is not None
                     and killfeed.me_template("valorant-16x9-bigmap") is not None,
                     "no mined \"Me\" template")
class MeWordTests(unittest.TestCase):
    def test_a_first_or_last_word_of_a_spaced_name_is_not_me(self):
        # "erachdon [rifle] [headshot] Mga Yawa", "Mga Yawa [rifle] Jett"
        # and "petiteboytoy [rifle] [headshot] Mga Yawa", where "Yawa" splits
        # into "Y" and "awa".
        for name in ("066741deafe5_01680.png", "066741deafe5_04670.png",
                     "066741deafe5_07155.png"):
            got = _read(name, "valorant-16x9-bigmap")
            self.assertEqual((got.kill_ys, got.death_ys), ((), ()), name)

    def test_without_the_word_gate_mga_reads_as_me(self):
        old = killfeed.ME_WORD_GAP
        try:
            killfeed.ME_WORD_GAP = -1000
            got = _read("066741deafe5_01680.png", "valorant-16x9-bigmap")
        finally:
            killfeed.ME_WORD_GAP = old
        self.assertEqual(got.death_ys, (54,))

    def test_a_real_me_still_reads(self):
        self.assertEqual(_read("c40d950031bb_01890.png", "valorant-16x9").kill_ys, (54,))
        self.assertEqual(_read("c40d950031bb_01990.png", "valorant-16x9").death_ys, (15,))


if __name__ == "__main__":
    unittest.main()
