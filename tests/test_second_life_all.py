"""Second lives on every entry: the badge reader's lineup gate and ring, and
the per-entry vote that binds badge rows to the entry by its track reads."""
import unittest

import cv2
import numpy as np

from reticle import killfeed as KF
from reticle.adjudication.death import (entry_second_life, second_life_death, session_entries,
                                        split_second_lives)


def _band(ring: bool, letter: bool = False):
    """A 34-row entry: red killer plate with a white weapon bar, green victim
    plate from column 200, and a white ring of radius 19 at its left end, or
    a small round letter where the name starts."""
    h, w = 34, 400
    hsv = np.zeros((h, w, 3), np.uint8)
    hsv[:, :200] = (0, 150, 200)
    hsv[:, 200:] = (78, 120, 200)
    img = cv2.cvtColor(hsv, cv2.COLOR_HSV2BGR)
    img[12:22, 120:160] = 255
    if ring:
        cv2.circle(img, (219, 17), 19, (255, 255, 255), 2, lineType=cv2.LINE_AA)
    if letter:
        cv2.circle(img, (250, 17), 6, (255, 255, 255), 2, lineType=cv2.LINE_AA)
    view = KF.EntryView(0, 0, h, 120, 160, killer_run=(40, 100), victim_run=(245, 300),
                        verdict="other", victim_ally=True, killer_ally=False, ix0=120, ix1=160)
    usable = np.ones((h, w), bool)
    green, red, _ = KF._plate_masks(img, usable)
    return img, green, red, view, usable


class BadgeRing(unittest.TestCase):
    def test_a_ring_at_the_victim_plate_start_is_a_badge(self):
        img, green, red, view, usable = _band(ring=True)
        got = KF.badge_ring(img, green, red, view, usable)
        self.assertIs(got["has_badge"], True)
        self.assertEqual(got["anchor"], "victim_plate")
        # The ring's own ink thins the plate's first columns.
        self.assertTrue(200 <= got["plate_x0"] <= 205, got["plate_x0"])

    def test_a_round_letter_at_the_name_start_is_no_badge(self):
        img, green, red, view, usable = _band(ring=False, letter=True)
        self.assertIs(KF.badge_ring(img, green, red, view, usable)["has_badge"], False)


class Gate(unittest.TestCase):
    def view(self, verdict="other", ally=True):
        return KF.EntryView(0, 0, 34, victim_run=(10, 20), verdict=verdict, victim_ally=ally)

    def test_the_side_that_may_field_phoenix_or_kayo_is_read(self):
        cands = {"ally": ["Jett", "Phoenix"], "enemy": ["KAY_O", "Omen"]}
        self.assertEqual(KF.second_life_gate(self.view(ally=True), cands), "side")
        self.assertEqual(KF.second_life_gate(self.view(ally=False), cands), "side")
        none = {"ally": ["Jett", "Sage"], "enemy": ["Omen", "Raze"]}
        self.assertIsNone(KF.second_life_gate(self.view(), none))
        self.assertEqual(KF.second_life_gate(self.view(ally=None), cands), "match: side unread")
        self.assertEqual(KF.second_life_gate(self.view(), None), "all: no lineup given")
        self.assertEqual(KF.second_life_gate(self.view("death"), none), "player_death")


def _row(t, slot, badge, player_death=False):
    return {"kind": "second_life_observation", "t_ms": float(t), "slot": slot,
            "has_badge": badge, "player_death": player_death}


class EntryVote(unittest.TestCase):
    def test_rows_vote_only_at_the_entrys_own_reads(self):
        entry = {"t_first": 0.0, "t_last": 1000.0, "slot": 1,
                 "reads": [(0.0, 1), (500.0, 1), (1000.0, 0)]}
        rows = [_row(0, 1, True), _row(500, 1, True), _row(1000, 0, False),
                _row(0, 0, True), _row(500, 0, True), _row(500, 2, True), _row(0, 1, None)]
        got = entry_second_life(entry, rows)
        self.assertEqual((got["value"], got["badges"], got["reads"], got["binding"]),
                         (True, 2, 3, "entry_reads"))
        self.assertEqual(entry_second_life(entry, [_row(0, 0, True)])["value"], None)
        self.assertEqual(entry_second_life(entry, None)["binding"], "no_badge_stream")

    def test_the_player_track_vote_reads_only_the_players_rows(self):
        rows = [_row(1000, 0, True), _row(1500, 0, True), _row(1000, 1, False, True),
                _row(1500, 1, False, True), _row(1500, 1, None, True)]
        self.assertFalse(second_life_death(900, 1600, rows))
        self.assertIsNone(second_life_death(900, 1600, rows[:2]))
        deaths, lives = split_second_lives([{"t_first": 900.0, "t_last": 1600.0}], rows)
        self.assertEqual((len(deaths), len(lives)), (1, 0))


class SessionSecondLives(unittest.TestCase):
    def hud(self, death_mask):
        t = [float(x) for x in range(0, 6001, 500)]
        on = [1000 <= x <= 5000 for x in t]
        return {"t_ms": t, "kf_entry_mask": [3 if o else 0 for o in on],
                "kf_ally_mask": [2 if o else 0 for o in on],
                "kf_enemy_mask": [1 if o else 0 for o in on],
                "kf_kill_mask": [0] * len(t),
                "kf_death_mask": [death_mask if o else 0 for o in on]}

    def test_a_badged_entry_is_a_second_life_without_a_player_death_track(self):
        """587c15b07779 1294.5 s: the badge read, but no player death track
        owned the entry, so the track's vote never ran and a Run It Back was
        stored as a death."""
        t = [float(x) for x in range(1000, 5001, 500)]
        rows = [_row(x, 1, True) for x in t] + [_row(x, 0, False) for x in t]
        got = sorted(session_entries(self.hud(0), rows), key=lambda e: e["slot"])
        self.assertEqual([(e["slot"], e["kf_player_death"], e["is_second_life"]) for e in got],
                         [(0, False, False), (1, False, True)])
        self.assertEqual(got[1]["second_life_vote"]["binding"], "entry_reads")

    def test_a_neighbours_badge_never_makes_the_players_death_a_second_life(self):
        t = [float(x) for x in range(1000, 5001, 500)]
        rows = [_row(x, 0, True) for x in t] + [_row(x, 1, False, True) for x in t]
        got = sorted(session_entries(self.hud(2), rows), key=lambda e: e["slot"])
        self.assertEqual([(e["slot"], e["kf_player_death"], e["is_second_life"]) for e in got],
                         [(0, False, True), (1, True, False)])

    def test_unread_entries_stay_deaths(self):
        got = session_entries(self.hud(2), [])
        self.assertFalse(any(e["is_second_life"] for e in got))
        self.assertTrue(all(e["second_life_vote"]["value"] is None for e in got))
        got = session_entries(self.hud(2), None)
        self.assertTrue(all(e["second_life_vote"]["binding"] == "no_badge_stream" for e in got))


if __name__ == "__main__":
    unittest.main()
