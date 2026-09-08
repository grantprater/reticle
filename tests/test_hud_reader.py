import types
import unittest
from unittest.mock import patch

import numpy as np

from reticle.hud_reader import HudReader


class HudReaderTests(unittest.TestCase):
    def _manifest(self):
        return {"session_id": "s1", "source": {
            "path": "missing.mp4", "width": 100, "height": 80,
            "duration_ms": 10000, "fps": 30,
        }}

    def _args(self):
        return types.SimpleNamespace(min_confidence=.4, min_margin=.2, hz=5)

    def test_cached_mask_does_not_open_video(self):
        store = types.SimpleNamespace(read_kf_mask=lambda sid: np.ones((2, 2), dtype=bool))
        profile = types.SimpleNamespace(name="test")
        with patch("reticle.hud_reader.Templates.load", return_value=object()), \
                patch("reticle.hud_reader.scoreline_roi", return_value=(0, 0, 1, 1)), \
                patch("reticle.hud_reader.killfeed_roi", return_value=(0, 0, 1, 1)), \
                patch("cv2.VideoCapture", side_effect=AssertionError("video opened")):
            reader = HudReader(store, self._manifest(), profile, self._args())
        self.assertIsNotNone(reader.kf_mask)

    def test_feed_preserves_every_extractor_field(self):
        score = types.SimpleNamespace(clock_ms=None, score_left=2, score_right=None,
                                      clock_reason="unreadable", score_left_reason=None,
                                      score_right_reason="unreadable", confidence=.81,
                                      n_glyphs=4)
        bottom = types.SimpleNamespace(hp=None, shield=50, ammo_mag=12,
                                       ammo_reserve=None, confidence=.63)
        kill = types.SimpleNamespace(
            entries=("entry",), player_kill=True, player_death=False,
            entry_mask=1, kill_mask=2, death_mask=4, unattributed=False,
            unparsed=True, unparsed_reason="bad glyph", ally_mask=8,
            enemy_mask=16, entry_dividers=(10,), kill_dividers=(20,),
            death_dividers=(30,),
        )
        store = types.SimpleNamespace(read_kf_mask=lambda sid: np.ones((2, 2), dtype=bool))
        profile = types.SimpleNamespace(name="test")
        with patch("reticle.hud_reader.Templates.load", return_value=object()), \
                patch("reticle.hud_reader.scoreline_roi", return_value=(0, 0, 1, 1)), \
                patch("reticle.hud_reader.killfeed_roi", return_value=(0, 0, 1, 1)), \
                patch("reticle.hud_reader.crop_gray", return_value=np.zeros((1, 1), dtype=np.uint8)), \
                patch("reticle.hud_reader.read_scoreline", return_value=score), \
                patch("reticle.hud_reader.read_bottom_hud", return_value=bottom), \
                patch("reticle.hud_reader.read_killfeed", return_value=kill):
            reader = HudReader(store, self._manifest(), profile, self._args())
            reader.feed(types.SimpleNamespace(frame=np.zeros((80, 100, 3), dtype=np.uint8),
                                              frame_idx=17, t_ms=1234.5))
        self.assertEqual(reader.rows, [{
            "frame_idx": 17, "t_ms": 1234.5, "clock_ms": None,
            "score_left": 2, "score_right": None, "hp": None, "shield": 50,
            "ammo_mag": 12, "ammo_reserve": None, "kf_entries": ("entry",),
            "kf_player_kill": True, "kf_player_death": False, "kf_entry_mask": 1,
            "kf_kill_mask": 2, "kf_death_mask": 4, "kf_unattributed": False,
            "kf_unparsed": True, "kf_unparsed_reason": "bad glyph",
            "clock_reason": "unreadable", "score_left_reason": None,
            "score_right_reason": "unreadable", "kf_ally_mask": 8,
            "kf_enemy_mask": 16, "kf_entry_wx": (10,), "kf_kill_wx": (20,),
            "kf_death_wx": (30,), "confidence": .81,
            "bottom_confidence": .63, "n_glyphs": 4,
        }])


if __name__ == "__main__":
    unittest.main()
