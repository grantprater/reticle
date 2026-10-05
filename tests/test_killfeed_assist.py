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
        # cut views never vote, even with a bound above the vote
        below = adj.pool_count([{"count": None, "count_min": 1, "reason": "cut_by_roi"},
                                {"count": 0}, {"count": None, "count_min": 1,
                                               "reason": "cut_by_roi"}])
        self.assertEqual(below["count"], 0)
        # an unverified view refuses and does not vote
        unv = adj.pool_count([{"count": None, "count_min": 0, "reason": "anchor_unverified"},
                              {"count": None, "count_min": 0, "reason": "anchor_unverified"}])
        self.assertEqual((unv["count"], unv["count_reason"], unv["present"]),
                         (None, "anchor_unverified", None))

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


def _tiles(h: int, w: int, margin: int, seed: int = 0) -> appearance.ArtTiles:
    """The three synthetic agents at any tile size, keeping their BGR."""
    rng = np.random.default_rng(seed)
    bgr = []
    for _ in AGENTS:
        base = rng.uniform(0.15, 0.85, (h // 3 + 1, w // 3 + 1, 3)).astype(np.float32)
        bgr.append(cv2.resize(base, (w, h), interpolation=cv2.INTER_LINEAR))
    lab = np.stack([cv2.cvtColor(b, cv2.COLOR_BGR2Lab) for b in bgr])
    tiles = appearance.ArtTiles(AGENTS, lab, np.ones((len(AGENTS), h, w), np.float32), margin)
    tiles.bgr = bgr
    return tiles


class CheckAnchor(unittest.TestCase):
    """The killer art's left edge is checked against the killer's own art."""

    def setUp(self):
        self.kart = _tiles(34, 68, 4, seed=5)
        rng = np.random.default_rng(2)
        self.crop = rng.normal(90, 6, (60, 300, 3)).astype(np.float32)
        self.crop[10:44, 150:218] = self.kart.bgr[self.kart.index["Bravo"]] * 255.0
        self.crop = np.clip(self.crop, 0, 255).astype(np.uint8)

    def test_confirmed_prior_is_verified(self):
        row = {"art_x0": 151, "art_reason": None, "art_y0": 10}
        got = ka.check_anchor(self.crop, row, UNIT_SCALE, self.kart, "Bravo")
        self.assertEqual(got["status"], ka.ANCHOR_VERIFIED)
        self.assertEqual(got["x"], 150.0)
        self.assertFalse(got["upstream_disagrees"])

    def test_misplaced_prior_widens_and_is_stored(self):
        row = {"art_x0": 60, "art_reason": None, "art_y0": 10}
        got = ka.check_anchor(self.crop, row, UNIT_SCALE, self.kart, "Bravo")
        self.assertEqual((got["status"], got["x"]), (ka.ANCHOR_LOCAL, 150.0))
        self.assertTrue(got["upstream_disagrees"])

    def test_unnamed_killer_searches_the_side(self):
        row = {"art_x0": 60, "art_reason": None, "art_y0": 10}
        got = ka.check_anchor(self.crop, row, UNIT_SCALE, self.kart, None, ["Alpha", "Bravo"])
        self.assertEqual((got["killer_candidates"], got["killer_at_best"]), ("side", "Bravo"))
        none = ka.check_anchor(self.crop, row, UNIT_SCALE, self.kart, None, [])
        self.assertEqual((none["status"], none["x"]), (ka.ANCHOR_NO_KILLER, 60))


class AllRowsAnchor(unittest.TestCase):
    """A prior whose row is a portrait off: the band holds no killer art, so
    every row is searched and the upstream row error is stored."""

    def setUp(self):
        self.kart = _tiles(34, 68, 4, seed=5)
        rng = np.random.default_rng(3)
        crop = rng.normal(90, 6, (130, 300, 3)).astype(np.float32)
        crop[60:94, 150:218] = self.kart.bgr[self.kart.index["Bravo"]] * 255.0
        self.crop = np.clip(crop, 0, 255).astype(np.uint8)

    def test_row_off_prior_is_found_in_all_rows(self):
        row = {"art_x0": 60, "art_reason": None, "art_y0": 45}
        got = ka.check_anchor(self.crop, row, UNIT_SCALE, self.kart, "Bravo")
        self.assertEqual((got["status"], got["x"], got["y"]), (ka.ANCHOR_ROWS, 150.0, 60))
        self.assertEqual(got["upstream_row_off"], 15)
        self.assertTrue(got["upstream_disagrees"])

    def test_absent_killer_stays_unverified_and_refuses(self):
        row = {"t_ms": 0.0, "art_x0": 60, "art_reason": None, "art_y0": 45,
               "observation_key": "k"}
        art = _art()
        got = ka.assist_observation(self.crop, row, UNIT_SCALE, art, list(AGENTS), None, [],
                                    "d", killer="Alpha", kart=self.kart)
        self.assertEqual(got["anchor_check"]["status"], ka.ANCHOR_UNVERIFIED)
        self.assertIsNone(got["count"])
        self.assertEqual(got["reason"], ka.REFUSE_UNVERIFIED)
        self.assertEqual(got["assisters"], [])
        self.assertIn("unverified_read", got)


class Unrecognised(unittest.TestCase):
    def test_drawn_rule_needs_art_plate_and_both_edges(self):
        ev = {"art_zncc": {"Alpha": 0.6}, "plate_mean": 0.25, "edge_bottom": 30.0,
              "edge_top": 20.0}
        self.assertTrue(ka.portrait_drawn(ev))
        self.assertFalse(ka.portrait_drawn({**ev, "edge_top": 3.0}))
        self.assertFalse(ka.portrait_drawn({**ev, "plate_mean": 0.0}))
        self.assertFalse(ka.portrait_drawn({**ev, "art_zncc": {"Alpha": 0.2}}))
        self.assertFalse(ka.portrait_drawn({}))

    def test_drawn_rule_is_measured_under_each_edge_prediction(self):
        # 223d636bf8d2 411.0 s: a no-icon placement over bare background
        # outscores the iconed portrait cell it overlaps; the drawn rule
        # must still be measured at the iconed placement.
        art = _art()
        edge, top = 150, 20
        x_no = edge + ka.EDGE_NO_ICON - ka.PORTRAIT_W
        x_ic = x_no - ka.ICON_CELL
        crop = np.full((70, 240, 3), 90, np.uint8)
        crop[top:top + ka.PORTRAIT_H, x_ic:x_ic + ka.PORTRAIT_W] = (150, 200, 80)
        lab = appearance.to_lab(crop)
        plate = ka.plate_score(crop)
        xs = np.arange(x_ic - 3, x_no + 4)
        ya = top - 1
        z = np.full((3, len(xs), len(AGENTS)), 0.1, np.float32)
        z[1, int(np.flatnonzero(xs == x_ic)[0]), 0] = 0.6      # Alpha, iconed, on the cell
        z[0, int(np.flatnonzero(xs == x_no)[0]), 1] = 0.62     # Bravo, no icon, a row high
        ev = ka._stop_evidence((z, xs, ya), list(AGENTS), art, lab, plate, edge,
                               UNIT_SCALE.px(ka.ICON_GAP_MIN))
        self.assertFalse(ev["predictions"]["no_icon"]["drawn"])
        self.assertTrue(ev["predictions"]["icon"]["drawn"])
        self.assertEqual((ev["drawn_by"], ev["x"], ev["y"], ev["agent"]), ("icon", x_ic, top, "Alpha"))
        self.assertEqual(ev["art_zncc"]["Bravo"], 0.62)
        self.assertTrue(ka.portrait_drawn(ev))

    def test_unrecognised_row_claims_nobody(self):
        admitted = {"named": ["Alpha"], "rivals": [], "blind": []}
        row = {"k": 0, "recognised": False, "art_zncc": {"Alpha": 0.6}, "art_candidates": "side"}
        c = adj.view_claim(row, "e", admitted, 0.0)
        self.assertIsNone(c["agent"])
        self.assertEqual(c["reason"], ka.UNRECOGNISED)

    def test_absence_near_roi_edge_is_flagged(self):
        art = _art()
        right = ka.EMPTY_VISIBLE_MIN - 4 + ka.PORTRAIT_W + 1
        # one assister whose left edge lies just inside EMPTY_VISIBLE_MIN
        got = ka.read_panel(_scene(art, [("Bravo", False)], right=right), right, 20,
                            UNIT_SCALE, art, list(AGENTS))
        self.assertEqual(got["count"], 1)
        self.assertEqual(got["stop"]["reason"], ka.STOP_ABSENT)
        self.assertIn("within_visible_min", got["stop"])


class FramedPortrait(unittest.TestCase):
    def test_framed_path_marks_the_self_frame(self):
        art = _art()
        framed = appearance.ArtTiles(art.agents, art._lab, art.alpha, ka.FRAME_MARGIN)
        crop = _scene(art, [("Charlie", False)])
        x = 150 + ka.EDGE_NO_ICON - ka.PORTRAIT_W
        yellow = np.array([30, 236, 231], np.uint8)        # E7EC77 in BGR
        for r in (20, 21, 22, 35, 36, 37):
            crop[r, x:x + ka.PORTRAIT_W] = yellow
        for c in (0, 1, 2, ka.PORTRAIT_W - 3, ka.PORTRAIT_W - 2, ka.PORTRAIT_W - 1):
            crop[20:20 + ka.PORTRAIT_H, x + c] = yellow
        plain = ka.read_panel(crop, 150, 20, UNIT_SCALE, art, list(AGENTS))
        got = ka.read_panel(crop, 150, 20, UNIT_SCALE, art, list(AGENTS), framed_art=framed)
        self.assertEqual(got["count"], 1)
        a = got["assisters"][0]
        self.assertEqual(max(a["art_zncc"], key=a["art_zncc"].get), "Charlie")
        self.assertEqual(plain["count"], 0)      # the frame hides it at ART_MARGIN
        self.assertEqual(a["frame"], "self")


class JoinAssists(unittest.TestCase):
    def _assist(self, death_rule):
        from reticle.adjudication import death
        return [{"kind": "summary", "assist_adjudication_version": adj.ASSIST_ADJUDICATION_VERSION,
                 "inputs": {"death": death_rule or death.DEATH_ADJUDICATION_VERSION}},
                {"kind": "assist_verdict", "death_id": "d1", "count": 1, "count_min": 1,
                 "present": True, "count_status": "read", "count_reason": None,
                 "rests_on": {"killfeed_assist_version": ka.KILLFEED_ASSIST_VERSION},
                 "assisters": [{"k": 0, "entity_id": "d1:assist:0", "agent": "Alpha",
                                "identity": {"status": "resolved"}, "icon": "none",
                                "icon_status": "read", "icon_set": None}]},
                {"kind": "assist_verdict", "death_id": "d2", "count": None, "count_min": 1,
                 "present": True, "count_status": "refused", "count_reason": "cut_by_roi",
                 "assisters": []}]

    def test_join_by_death_id(self):
        from reticle.adjudication import death
        rows = [{"kind": "death_verdict", "death_id": d} for d in ("d1", "d2", "d3")]
        got = death.join_assists(rows, self._assist(None))
        self.assertEqual(got, {"read": 1, "lower_bound": 1, death.ASSISTS_NO_ROW: 1})
        self.assertEqual(rows[0]["assists"]["assisters"][0]["agent"], "Alpha")
        self.assertEqual(rows[1]["assists"]["count_min"], 1)
        self.assertEqual(rows[2]["assists"]["status"], "unread")
        self.assertEqual(death.assist_stamp(self._assist(None)), adj.ASSIST_ADJUDICATION_VERSION)

    def test_stale_or_missing_stream_is_unread(self):
        from reticle.adjudication import death
        rows = [{"kind": "death_verdict", "death_id": "d1"}]
        death.join_assists(rows, self._assist("death-adjudication-0.1.0"))
        self.assertEqual(rows[0]["assists"]["reason"], death.ASSISTS_STALE)
        self.assertTrue(death.assist_stamp(self._assist("death-adjudication-0.1.0"))
                        .startswith("stale:"))
        death.join_assists(rows, None)
        self.assertEqual(rows[0]["assists"]["reason"], death.ASSISTS_NO_STREAM)


if __name__ == "__main__":
    unittest.main()
