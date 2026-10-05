"""The killfeed assist panel [domain:killfeed/assist-panel]: the reader's walk
leftwards from the killer art (presence, icon cell, ROI cut), and the
adjudication's count vote, identity claims and icon sets."""
from __future__ import annotations

import unittest

import cv2
import numpy as np

from reticle import appearance
from reticle import killfeed_assist as ka
from reticle.adjudication import assist as adj
from reticle.killfeed import UNIT_SCALE

AGENTS = ("Alpha", "Bravo", "Charlie")


def _art(seed: int = 0) -> appearance.ArtTiles:
    """Three synthetic agents at the brush size: textured faces whose alpha
    leaves the left quarter transparent."""
    rng = np.random.default_rng(seed)
    h, w = ka.PORTRAIT_H, ka.PORTRAIT_W
    bgr = []
    for _ in AGENTS:
        base = rng.uniform(0.15, 0.85, (h // 3 + 1, w // 3 + 1, 3)).astype(np.float32)
        bgr.append(cv2.resize(base, (w, h), interpolation=cv2.INTER_LINEAR))
    lab = np.stack([cv2.cvtColor(b, cv2.COLOR_BGR2Lab) for b in bgr])
    alpha = np.ones((len(AGENTS), h, w), np.float32)
    alpha[:, :, : w // 4] = 0.0
    tiles = appearance.ArtTiles(AGENTS, lab, alpha, ka.ART_MARGIN)
    tiles.bgr = bgr
    return tiles


def _scene(art, placed, right=150, top=20, width=240, seed=1):
    """A crop with each (agent, icon) assister drawn leftwards from `right`."""
    rng = np.random.default_rng(seed)
    crop = rng.normal(90, 6, (70, width, 3)).astype(np.float32)
    edge = right
    for agent, icon in placed:
        pr = edge + ka.EDGE_NO_ICON - (ka.ICON_CELL if icon else 0)
        x = pr - ka.PORTRAIT_W
        tile = art.bgr[art.index[agent]] * 255.0
        a = art.alpha[art.index[agent]][..., None]
        plate = np.array([150, 200, 80], np.float32)
        x0 = max(0, x)
        crop[top:top + ka.PORTRAIT_H, x0:x + ka.PORTRAIT_W] = \
            (tile * a + plate * (1 - a))[:, x0 - x:]
        edge = x
    return np.clip(crop, 0, 255).astype(np.uint8)


class ReadPanel(unittest.TestCase):
    def setUp(self):
        self.art = _art()

    def test_no_panel_reads_zero(self):
        got = ka.read_panel(_scene(self.art, []), 150, 20, UNIT_SCALE, self.art, list(AGENTS))
        self.assertEqual(got["count"], 0)
        self.assertEqual(got["stop"]["reason"], ka.STOP_ABSENT)

    def test_one_assister_without_icon(self):
        got = ka.read_panel(_scene(self.art, [("Bravo", False)]), 150, 20, UNIT_SCALE,
                            self.art, list(AGENTS))
        self.assertEqual(got["count"], 1)
        a = got["assisters"][0]
        self.assertEqual(max(a["art_zncc"], key=a["art_zncc"].get), "Bravo")
        self.assertFalse(a["icon"])

    def test_two_assisters_icon_on_the_right_one(self):
        got = ka.read_panel(_scene(self.art, [("Alpha", True), ("Charlie", False)]), 150, 20,
                            UNIT_SCALE, self.art, list(AGENTS))
        self.assertEqual(got["count"], 2)
        first, second = got["assisters"]
        self.assertTrue(first["icon"])
        self.assertFalse(second["icon"])
        self.assertEqual(max(second["art_zncc"], key=second["art_zncc"].get), "Charlie")

    def test_roi_cut_refuses_the_count(self):
        # one assister, then the ROI's left edge leaves too few columns
        got = ka.read_panel(_scene(self.art, [("Bravo", False)], right=60), 60, 20,
                            UNIT_SCALE, self.art, list(AGENTS))
        self.assertIsNone(got["count"])
        self.assertEqual(got["count_min"], 1)
        self.assertEqual(got["stop"]["reason"], ka.STOP_CUT)

    def test_view_anchors_order_and_dedupe(self):
        row = {"entry_anchor": 90.0, "plate_left": 91.0, "plate_left_score": 9.0,
               "art_x0": 120, "art_reason": None}
        got = ka.view_anchors(row)
        self.assertEqual([s for _x, s in got], ["entry_anchor", "art_window"])


KITS = {"assist_icons": {"Alpha": ["Smoke"]}, "assist_open": {"Alpha": ["Reveal"]},
        "abilities": [{"agent": "Alpha", "name": n, "damage": {"status": st}}
                      for n, st in (("Smoke", "not_damaging"), ("Reveal", "not_damaging"),
                                    ("Heal", "not_damaging"), ("Passive", "passive"))]}


class Adjudicate(unittest.TestCase):
    def test_count_vote(self):
        self.assertEqual(adj.pool_count([{"count": 1}, {"count": 1}, {"count": 0}])["count"], 1)
        tie = adj.pool_count([{"count": 1}, {"count": 0}])
        self.assertIsNone(tie["count"])
        self.assertEqual(tie["count_reason"], "count_tie")
        cut = adj.pool_count([{"count": None, "count_min": 1, "reason": "cut_by_roi"},
                              {"count": None, "count_min": 2, "reason": "cut_by_roi"}])
        self.assertEqual(cut["count_min"], 1)
        self.assertTrue(cut["present"])

    def test_icon_sets_widen(self):
        got = adj.decide_icon({"Alpha/Smoke": 0.8, "Alpha/Heal": 0.3}, "Alpha", [], KITS)
        self.assertEqual((got["icon"], got["icon_set"]), ("Smoke", "assist_decision"))
        got = adj.decide_icon({"Alpha/Smoke": 0.2, "Alpha/Heal": 0.7}, "Alpha", [], KITS)
        self.assertEqual((got["icon"], got["icon_set"]), ("Heal", "kit"))
        got = adj.decide_icon({"assist:Damage": 0.7, "Alpha/Smoke": 0.1}, "Alpha", [], KITS)
        self.assertIsNone(got["icon"])
        self.assertEqual((got["icon_reason"], got["drawn"]), ("outside_kit", "assist:Damage"))

    def test_view_claim_names_only_side_agents(self):
        admitted = {"named": ["Alpha", "Bravo"], "rivals": ["Charlie"], "blind": []}
        row = {"k": 0, "art_zncc": {"Alpha": 0.9, "Bravo": 0.3, "Charlie": 0.2},
               "art_candidates": "side"}
        self.assertEqual(adj.view_claim(row, "e", admitted, 0.0)["agent"], "Alpha")
        row["art_zncc"] = {"Alpha": 0.3, "Bravo": 0.2, "Charlie": 0.9}
        self.assertIsNone(adj.view_claim(row, "e", admitted, 0.0)["agent"])
        row["art_candidates"] = "all"
        self.assertEqual(adj.view_claim(row, "e", admitted, 0.0)["reason"], "outside_side")
        self.assertEqual(adj.view_claim({**row, "art_candidates": "side"}, "e",
                                        {**admitted, "blind": [None]}, 0.0)["reason"], "blind_slot")

    def test_killer_side(self):
        self.assertEqual(adj.killer_side({"side": "ally"}), "enemy")
        self.assertEqual(adj.killer_side({"side": "ally", "same_side": True}), "ally")


if __name__ == "__main__":
    unittest.main()
