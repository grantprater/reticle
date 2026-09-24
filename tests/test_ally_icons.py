"""Ally icon descriptors and the per-frame naming of teammates."""
import unittest

import cv2
import numpy as np

from reticle.adjudication.identity import claims_from_ally_icons
from reticle.minimap import (ALLY_MAP_DIFF_MIN, AllyIconReader,
                             ally_icon_descriptors)

#: The reference widget width, so the icon gates are unscaled.
W = 465

#: Four teammates whose portraits are one colour bin each.
GALLERY = {name: [np.eye(4, dtype=np.float32)[i]]
           for i, name in enumerate(["Breach", "Deadlock", "Miks", "Reyna"])}


def _lineup(ally=("Phoenix", "Breach", "Deadlock", "Reyna", "Miks"), player="Phoenix"):
    rows = [{"slot": i, "agent": a, "best_guess": a} for i, a in enumerate(ally)]
    return {"sides": {"ally": rows}, "player": {"agent": player} if player else None}


def _icon(frame, index, comp, reason=None):
    return {"frame_idx": frame, "t_ms": frame * 500.0, "index": index,
            "observation_key": f"s:{frame}:{index}", "cx": 10.0, "cy": 10.0, "r": 8,
            "composition": comp, "reason": reason}


def _one_hot(i, w=0.9):
    v = np.full(4, (1 - w) / 3, np.float32)
    v[i] = w
    return v.tolist()


class ClaimsFromAllyIconsTests(unittest.TestCase):
    def test_a_frames_icons_are_named_as_distinct_teammates(self):
        icons = [_icon(1, 0, _one_hot(0)), _icon(1, 1, _one_hot(3))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s")
        self.assertEqual([c["agent"] for c in claims], ["Breach", "Reyna"])
        self.assertEqual(claims[0]["entity_id"], "s:ally_icon:s:1:0")
        self.assertEqual(claims[0]["channel"], "minimap_portrait")
        self.assertNotIn("Phoenix", claims[0]["evidence"]["candidates"])

    def test_two_icons_with_the_same_best_match_cannot_both_take_it(self):
        icons = [_icon(1, 0, _one_hot(0, 0.9)), _icon(1, 1, _one_hot(0, 0.8))]
        claims = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                        session_id="s")
        named = [c["agent"] for c in claims if c["agent"]]
        self.assertEqual(len(named), len(set(named)))

    def test_a_stored_refusal_is_quoted(self):
        icons = [_icon(1, 0, _one_hot(0), reason="interior_is_map")]
        (claim,) = claims_from_ally_icons(icons, _lineup(), gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "interior_is_map")

    def test_an_unknown_player_refuses_every_icon(self):
        icons = [_icon(1, 0, _one_hot(0))]
        (claim,) = claims_from_ally_icons(icons, _lineup(player=None),
                                          gallery=GALLERY, session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "player_unknown")

    def test_a_refused_slot_is_a_rival_and_never_a_name(self):
        lineup = _lineup()
        lineup["sides"]["ally"][4] = {"slot": 4, "agent": None, "best_guess": "Miks"}
        icons = [_icon(1, 0, _one_hot(2))]
        (claim,) = claims_from_ally_icons(icons, lineup, gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertIn("refused_slot", claim["reason"])

    def test_a_blind_slot_refuses_the_side(self):
        lineup = _lineup()
        lineup["sides"]["ally"][4] = {"slot": 4, "agent": None, "best_guess": None}
        icons = [_icon(1, 0, _one_hot(0))]
        (claim,) = claims_from_ally_icons(icons, lineup, gallery=GALLERY,
                                          session_id="s")
        self.assertIsNone(claim["agent"])
        self.assertTrue(claim["reason"].startswith("lineup_incomplete"))


def _ally_icon_crop(portrait_bgr):
    """A grey widget holding one teal teardrop around a portrait disc."""
    crop = np.full((W, W, 3), 128, np.uint8)
    cv2.circle(crop, (60, 60), 10, (200, 220, 40), 3)      # teal ring
    tri = np.array([[60, 44], [55, 51], [65, 51]], np.int32)
    cv2.fillPoly(crop, [tri], (200, 220, 40))              # the facing lobe
    cv2.circle(crop, (60, 60), 7, portrait_bgr, -1)
    return crop


class AllyIconDescriptorTests(unittest.TestCase):
    def setUp(self):
        self.floor = np.ones((W, W), bool)
        self.static = np.full((W, W, 3), 128, np.uint8)

    def test_a_portrait_is_described(self):
        crop = _ally_icon_crop((30, 60, 200))
        got = ally_icon_descriptors(crop, self.floor, static=self.static)
        self.assertEqual(len(got), 1)
        self.assertIsNone(got[0]["reason"])
        self.assertGreater(got[0]["map_diff"], ALLY_MAP_DIFF_MIN)
        self.assertAlmostEqual(sum(got[0]["composition"]), 1.0, places=4)

    def test_an_interior_that_is_the_map_is_refused(self):
        crop = _ally_icon_crop((128, 128, 128))
        got = ally_icon_descriptors(crop, self.floor, static=self.static)
        self.assertEqual([g["reason"] for g in got], ["interior_is_map"])

    def test_an_occluder_removes_its_pixels(self):
        crop = _ally_icon_crop((30, 60, 200))
        full = ally_icon_descriptors(crop, self.floor, static=self.static)[0]
        part = ally_icon_descriptors(crop, self.floor, static=self.static,
                                     occluders=[(66, 60, 4)])[0]
        self.assertLess(part["pixels"], full["pixels"])

    def test_the_reader_keeps_frames_without_icons(self):
        class Smp:
            frame_idx, t_ms = 3, 1500.0
            frame = np.full((W, W, 3), 128, np.uint8)
        reader = AllyIconReader(self.floor, None, self.static, (0, 0, W, W))
        reader.feed(Smp())
        rows = reader.events("s")
        self.assertEqual(rows[0]["kind"], "coverage")
        self.assertEqual([r["kind"] for r in rows[1:]], ["frame"])
        self.assertTrue(all(r["ally_icon_version"] for r in rows))


if __name__ == "__main__":
    unittest.main()
