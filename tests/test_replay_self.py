"""Which replay player is the capturing player (`replay_source`,
[owns:replay-self]'s rule): the pick on the stored self track, its refusals,
and Riot's record deciding with the pick stored as a cross-check."""
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import replay_source as rs


class ChooseSelfSubjectTest(unittest.TestCase):
    """`choose_self_subject` on synthetic self tracks: four subjects, 1000 frames."""

    SUBS = ["me", "mate", "foe", "far"]

    def _dist(self, n=1000, seed=0):
        g = np.random.default_rng(seed)
        return np.column_stack([g.uniform(0.0, 1.0, n),       # follows the icon
                                g.uniform(3.0, 30.0, n),      # a teammate nearby
                                g.uniform(10.0, 60.0, n),
                                np.full(n, 80.0)])

    def test_names_the_subject_the_track_follows(self):
        r = rs.choose_self_subject(self._dist(), self.SUBS, margin=0.25)
        self.assertEqual(r["subject"], "me")
        self.assertIsNone(r["reason"])
        self.assertEqual(r["best"]["share_within"], 1.0)
        self.assertEqual(r["runner_up"]["subject"], "mate")
        self.assertAlmostEqual(r["margin"], 1.0 - r["runner_up"]["share_within"], places=4)

    def test_a_dead_subject_counts_as_a_miss(self):
        D = self._dist()
        D[:600, 0] = np.nan            # the player dies; the icon follows the mate
        D[:600, 1] = 0.5
        r = rs.choose_self_subject(D, self.SUBS, margin=0.25)
        self.assertIsNone(r["subject"])
        self.assertEqual(r["best"]["subject"], "mate")
        self.assertTrue(r["reason"].startswith("margin_too_small"))
        self.assertEqual(r["candidates"][1]["frames_alive"], 400)

    def test_refuses_a_short_track(self):
        r = rs.choose_self_subject(self._dist(n=899), self.SUBS, margin=0.25)
        self.assertIsNone(r["subject"])
        self.assertEqual(r["reason"], "track_too_short:899<900")

    def test_refuses_an_empty_track(self):
        r = rs.choose_self_subject(np.zeros((0, 4)), self.SUBS)
        self.assertIsNone(r["subject"])
        self.assertEqual(r["reason"], "track_too_short:0<900")

    def test_refuses_a_poor_fit(self):
        D = self._dist()
        D[:, 0] = 5.0
        D[:250, 0] = 0.5               # within 2 m on a quarter of frames only
        r = rs.choose_self_subject(D, self.SUBS, margin=0.1)
        self.assertIsNone(r["subject"])
        self.assertTrue(r["reason"].startswith("no_fit"))

    def test_refuses_a_small_margin(self):
        D = self._dist()
        D[:500, 1] = 0.5               # a teammate stacked on half the track
        r = rs.choose_self_subject(D, self.SUBS, margin=0.6)
        self.assertIsNone(r["subject"])
        self.assertTrue(r["reason"].startswith("margin_too_small"))
        self.assertEqual(rs.choose_self_subject(D, self.SUBS, margin=0.5)["subject"], "me")

    def test_the_module_cut_is_set(self):
        self.assertEqual(rs.SELF_ID_MARGIN, 0.25)
        self.assertEqual(rs.choose_self_subject(self._dist(), self.SUBS)["margin_cut"], 0.25)

    def test_same_side_compares_partitions_not_labels(self):
        subs = ["a", "b", "c", "d"]
        riot = {"a": "Blue", "b": "Blue", "c": "Red", "d": "Red"}
        spawn = {"a": "B", "b": "B", "c": "A", "d": "A"}
        self.assertTrue(rs.same_side(spawn, "a", riot, "a", subs))
        spawn["b"] = "A"
        self.assertFalse(rs.same_side(spawn, "a", riot, "a", subs))
        self.assertIsNone(rs.same_side({}, "a", riot, "a", subs))


class DecidePlayerTest(unittest.TestCase):
    """`decide_player`: Riot decides where it names the player; the replay's
    pick decides, resting on `ally_icon.self`, where it does not."""

    SUBS = ["a", "b", "c", "d"]
    AGENT = {"a": "Sova", "b": "Jett", "c": "Omen", "d": "Sage"}
    SPAWN = {"a": "B", "b": "B", "c": "A", "d": "A"}
    RIOT = {"a": "Blue", "b": "Blue", "c": "Red", "d": "Red"}

    def _pick(self, subject="a", best="a", reason=None):
        D = np.full((1000, 4), 50.0)
        D[:, self.SUBS.index(best)] = 0.5
        p = rs.choose_self_subject(D, self.SUBS)
        p["subject"], p["reason"] = subject, reason
        p["rests_on"] = rs.SELF_ID_RESTS_ON
        return p

    def test_riot_decides_and_the_pick_agrees(self):
        w = rs.decide_player(self._pick(), self.SPAWN, "a", self.RIOT, self.AGENT, self.SUBS)
        self.assertEqual((w["me"], w["team"]), ("a", self.RIOT))
        self.assertIsNone(w["player_basis"])
        self.assertIsNone(w["refused"])
        si = w["self_identity"]
        self.assertEqual(si["used"], "riot_record")
        self.assertEqual(si["replay"]["agent"], "Sova")
        self.assertEqual(si["riot_cross_check"], {
            "present": True, "self_agrees": True, "best_agrees": True, "team_agrees": True,
            "riot_agent": "Sova", "disagreement": False})

    def test_riot_decides_and_a_disagreement_is_flagged(self):
        w = rs.decide_player(self._pick("b", "b"), self.SPAWN, "a", self.RIOT, self.AGENT,
                             self.SUBS)
        self.assertEqual(w["me"], "a")
        cc = w["self_identity"]["riot_cross_check"]
        self.assertFalse(cc["self_agrees"])
        self.assertFalse(cc["best_agrees"])
        self.assertTrue(cc["team_agrees"])           # b stands on a's side
        self.assertTrue(cc["disagreement"])

    def test_riot_decides_over_a_refused_pick(self):
        w = rs.decide_player(self._pick(None, "a", "margin_too_small:0.1<0.25"), self.SPAWN,
                             "a", self.RIOT, self.AGENT, self.SUBS)
        self.assertEqual(w["me"], "a")
        self.assertIsNone(w["refused"])
        cc = w["self_identity"]["riot_cross_check"]
        self.assertIsNone(cc["self_agrees"])
        self.assertTrue(cc["best_agrees"])
        self.assertFalse(cc["disagreement"])

    def test_without_riot_the_pick_decides(self):
        w = rs.decide_player(self._pick("c", "c"), self.SPAWN, None, {}, self.AGENT, self.SUBS)
        self.assertEqual((w["me"], w["team"]), ("c", self.SPAWN))
        self.assertEqual(w["player_basis"], "replay_self_track")
        self.assertEqual(w["team_source"], "replay_spawn_split")
        si = w["self_identity"]
        self.assertEqual(si["used"], "replay_self_track")
        self.assertEqual(si["riot_cross_check"], {"present": False})
        self.assertEqual(si["replay"]["rests_on"], "ally_icon.self")
        self.assertEqual(si["replay"]["agent"], "Omen")

    def test_without_riot_a_refused_pick_refuses_with_its_reason(self):
        w = rs.decide_player(self._pick(None, "c", "no_fit:best_share<0.3"), self.SPAWN, None,
                             {}, self.AGENT, self.SUBS)
        self.assertIsNone(w["me"])
        self.assertEqual(w["team"], {})
        self.assertEqual(w["refused"], "no_player_or_team:replay_self:no_fit:best_share<0.3")
        self.assertIsNone(w["self_identity"]["used"])

    def test_without_riot_or_spawn_teams_it_refuses(self):
        w = rs.decide_player(self._pick(), {}, None, {}, self.AGENT, self.SUBS)
        self.assertEqual(w["refused"], "no_player_or_team:replay_self:no_spawn_teams")


class SelfTrackTest(unittest.TestCase):
    def test_keeps_drawn_frames_with_a_self_fit_in_frame_order(self):
        rows = [{"kind": "frame", "frame_idx": 3, "t_ms": 300.0, "widget_drawn": True,
                 "self": [30.0, 31.0]},
                {"kind": "frame", "frame_idx": 1, "t_ms": 100.0, "widget_drawn": True,
                 "self": [10.0, 11.0]},
                {"kind": "frame", "frame_idx": 2, "t_ms": 200.0, "widget_drawn": False,
                 "self": [20.0, 21.0]},
                {"kind": "frame", "frame_idx": 4, "t_ms": 400.0, "widget_drawn": True,
                 "self": None},
                {"kind": "icon", "frame_idx": 1, "t_ms": 100.0, "cx": 5.0, "cy": 5.0}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "events" / "ally_icon"
            p.mkdir(parents=True)
            (p / "s.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n",
                                       encoding="utf-8")
            T = rs.ally_icon_self_track("s", d)
            self.assertEqual(T["t_ms"].tolist(), [100.0, 300.0])
            self.assertEqual(T["x"].tolist(), [10.0, 30.0])
            self.assertEqual(T["y"].tolist(), [11.0, 31.0])
            self.assertEqual(rs.ally_icon_self_track("absent", d)["t_ms"].size, 0)


if __name__ == "__main__":
    unittest.main()
