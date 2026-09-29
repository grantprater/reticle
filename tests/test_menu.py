"""The menu witness: its two structural fits, the stored rows, the per-instant
answer, and the readers that refuse a covered reading."""
from __future__ import annotations

import unittest

import numpy as np

from reticle import menu, roster
from reticle.ability_timeline import player_tray_casts

TRAY_RECT = [739, 968, 1169, 1070]
TOP_RECTS = {"hud_roster": [434, 22, 751, 100], "scoreline": [806, 22, 1114, 81],
             "hud_roster_enemy": [1167, 22, 1467, 100]}


#: The two layouts' buttons: (x0, x1, y0, y1).
LARGE, SMALL = (810, 1109, 983, 1033), (850, 1069, 993, 1034)


def _tray(button=LARGE, scene=8, fill=(225, 231, 235)) -> np.ndarray:
    x0, y0, x1, y1 = TRAY_RECT
    c = np.full((y1 - y0, x1 - x0, 3), scene, np.uint8)
    if button:
        bx0, bx1, by0, by1 = button
        c[by0 - y0 - 6:by0 - y0 - 4, bx0 - x0 - 6:bx1 - x0 + 6] = 150      # the outline
        c[by0 - y0:by1 - y0, bx0 - x0:bx1 - x0] = fill
        c[by0 - y0 + 12:by1 - y0 - 12, bx0 - x0 + 40:bx1 - x0 - 40:7] = 30  # the label
    return c


def _top(roi: str, tabs=(26, 37), panel=20, scene=None) -> tuple[np.ndarray, list[int]]:
    x0, y0, x1, y1 = TOP_RECTS[roi]
    c = np.full((y1 - y0, x1 - x0, 3), panel if scene is None else scene, np.uint8)
    if tabs:
        a, b = tabs
        c[a - y0:b - y0, ::6] = 200                                             # the labels
    return c, TOP_RECTS[roi]


class FitTest(unittest.TestCase):
    def test_the_button_is_found_in_both_layouts_and_both_greys(self):
        for button in (LARGE, SMALL):
            for fill in ((225, 231, 235), (176, 176, 176)):
                got = menu.close_button(_tray(button, fill=fill), TRAY_RECT)
                self.assertTrue(got["open"], (button, fill, got))
                self.assertEqual(got["x"], [button[0], button[1]])

    def test_no_button_in_play(self):
        self.assertFalse(menu.close_button(_tray(button=None), TRAY_RECT)["open"])

    def test_a_flash_is_no_button(self):
        # Light everywhere: no edge inside the crop.
        self.assertFalse(menu.close_button(_tray(button=None, scene=250), TRAY_RECT)["open"])
        self.assertFalse(menu.close_button(_tray(scene=240), TRAY_RECT)["open"])

    def test_the_tab_strip_needs_all_three_crops(self):
        for rows in ((26, 37), (53, 64)):
            crops = {roi: _top(roi, tabs=rows) for roi in menu.TAB_ROIS}
            self.assertEqual(menu.tab_strip(crops)["rows"], list(rows))
        crops = {roi: _top(roi) for roi in menu.TAB_ROIS}
        self.assertTrue(menu.tab_strip(crops)["open"])
        crops["scoreline"] = _top("scoreline", tabs=False, scene=150)
        got = menu.tab_strip(crops)
        self.assertFalse(got["open"])
        self.assertEqual(got["crops_lit"], 2)

    def test_a_lit_panel_is_no_tab_strip(self):
        crops = {roi: _top(roi, panel=120) for roi in menu.TAB_ROIS}
        self.assertFalse(menu.tab_strip(crops)["open"])


class WitnessTest(unittest.TestCase):
    def setUp(self):
        fit = lambda o: {"open": o, "feature": "close_button", "light_rows": 32 if o else 0,
                         "side": 10.0}
        rows = menu.menu_rows("s", "minimap", [(1000.0, fit(False)), (1500.0, fit(True)),
                                               (2000.0, fit(False)), (2500.0, None)],
                              "menu-test", "roi-test")
        self.rows = rows
        self.w = menu.MenuWitness(rows)

    def test_rows(self):
        cov = self.rows[0]
        self.assertEqual((cov["kind"], cov["samples"], cov["unread"], cov["open"]),
                         ("coverage", 3, 1, 1))
        self.assertEqual([r["t_ms"] for r in self.rows[1:]], [1500.0])

    def test_at_keeps_unknown_apart(self):
        self.assertTrue(self.w.at(1500.0))
        self.assertTrue(self.w.at(1600.0))
        self.assertFalse(self.w.at(1000.0))
        self.assertIsNone(self.w.at(2500.0))     # unread: no sample answers
        self.assertIsNone(self.w.at(9000.0))     # never sampled
        self.assertEqual(self.w.open_ms(), [1500.0])


class ConsumerTest(unittest.TestCase):
    def test_a_menu_drop_is_refused_and_taints_nothing(self):
        rounds = [{"t_start_ms": 0.0, "t_end_ms": 90000.0, "t_close_ms": 90000.0}]
        drop = lambda t, s: {"t_ms": t, "slot": s, "from": 1.0, "to": 0.0, "forced": False,
                             "suspect": False, "cooccur": False}
        drops = [drop(20000.0, "E"), drop(20500.0, "Q"), drop(20500.0, "C")]
        live = lambda t: "round_live"
        before = {(r["t_ms"], r["slot"]): r["reason"]
                  for r in player_tray_casts([dict(d) for d in drops], live, rounds, [])}
        self.assertEqual(before[(20000.0, "E")], "cooccur_among_casts")
        covered = lambda t: True if t == 20500.0 else False
        got = {(r["t_ms"], r["slot"]): r for r in player_tray_casts(
            [dict(d) for d in drops], live, rounds, [], menu_at=covered)}
        self.assertEqual(got[(20500.0, "Q")]["reason"], "menu_open")
        self.assertEqual(got[(20500.0, "C")]["reason"], "menu_open")
        self.assertTrue(got[(20000.0, "E")]["player_cast"])

    def test_the_menu_outranks_a_missing_rounds_table(self):
        # A demo has no rounds table; its settings drops read as the menu's,
        # as a covered drop outside every round does on a match.
        drop = lambda t, s: {"t_ms": t, "slot": s, "from": 1.0, "to": 0.0, "forced": True,
                             "suspect": False, "cooccur": False}
        drops = [drop(3000.0, "C"), drop(20500.0, "Q"), drop(20500.0, "E")]
        covered = lambda t: True if t == 20500.0 else (None if t > 30000.0 else False)
        got = player_tray_casts([dict(d) for d in drops], None, None, [], menu_at=covered)
        self.assertEqual([r["reason"] for r in got], ["no_rounds", "menu_open", "menu_open"])
        self.assertFalse(any(r["player_cast"] for r in got))
        got = player_tray_casts([dict(d) for d in drops], lambda t: "round_live", [], [],
                                menu_at=covered)
        self.assertEqual([r["reason"] for r in got], ["no_round", "menu_open", "menu_open"])
        got = player_tray_casts([dict(d) for d in drops], None, None, [])
        self.assertEqual({r["reason"] for r in got}, {"no_rounds"})

    def test_the_roster_refuses_a_covered_row(self):
        crisp, blur = 30.0, 2.0
        rows = {"t_ms": [1000.0, 1500.0],
                "alive_ally": [3, 3], "alive_enemy": [5, 5],
                "detail_ally": [[blur, blur, crisp, crisp, crisp]] * 2,
                "detail_enemy": [[crisp] * 5] * 2}
        hud = {"t_ms": [1000.0, 1500.0], "score_left": [1, 1], "score_right": [2, 2]}
        self.assertEqual(roster.resolve(hud, rows), ([3, 3], [5, 5]))
        covered = lambda t: t == 1500.0
        self.assertEqual(roster.resolve(hud, rows, menu=covered), ([3, None], [5, None]))
        self.assertEqual(roster.refusals(rows, covered), [None, "menu_open"])

    def test_a_covered_instant_is_absent_for_the_belief(self):
        from reticle.belief import absent_instants
        rows = [{"t_ms": 1000.0, "self_x": 5.0, "widget_drawn": True},
                {"t_ms": 1500.0, "self_x": 5.0, "widget_drawn": True},
                {"t_ms": 2000.0, "self_x": None, "widget_drawn": False}]
        self.assertEqual(absent_instants(rows), [2000.0])
        self.assertEqual(absent_instants(rows, lambda t: t == 1500.0), [1500.0, 2000.0])


if __name__ == "__main__":
    unittest.main()
