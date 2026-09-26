"""Killfeed name clusters: the crop descriptor, the clusters and the per-match
assignment that replaces a role's per-entry portrait vote."""
from __future__ import annotations

import unittest

import numpy as np

from reticle.adjudication.death import adjudicate_death
from reticle.adjudication.identity import (NAME_CLUSTER_CHANNEL, NAME_CLUSTER_MIN,
                                           name_cluster_claims)
from reticle.adjudication.killfeed_names import followed_views, name_clusters, ncc
from reticle.killfeed import unpack_name_gray


def _crop(seed: int, w: int = 40) -> np.ndarray:
    """A 24-row band with white glyph-like strokes on a grey plate."""
    rng = np.random.default_rng(seed)
    g = np.full((24, w), 90, np.uint8)
    for x in range(1, w - 3, 5):
        h = int(rng.integers(4, 10))
        g[8:8 + h, x:x + 2] = 240
    return g


def _lineup(ally, enemy, player="Jett"):
    rows = lambda names: [{"slot": i, "agent": a} for i, a in enumerate(names)]
    return {"sides": {"ally": rows(ally), "enemy": rows(enemy)},
            "player": {"agent": player}}


class NameDescriptorTest(unittest.TestCase):
    def test_gray_round_trips_losslessly(self):
        import base64
        import zlib
        g = _crop(1)
        row = {"shape": list(g.shape),
               "gray": base64.b64encode(zlib.compress(g.tobytes())).decode()}
        self.assertTrue(np.array_equal(unpack_name_gray(row), g))
        self.assertIsNone(unpack_name_gray({"gray": None, "reason": "no_name_text"}))


class NameClusterTest(unittest.TestCase):
    def test_one_name_joins_and_another_does_not(self):
        a, b = _crop(1), _crop(2)
        self.assertGreaterEqual(ncc(a, a[:, :39]), 0.9)
        self.assertLess(ncc(a, b), 0.9)

    def test_plate_sides_and_me_stay_apart(self):
        a = _crop(1)
        crops = {"d1": {"team": "ally", "me": False, "gray": a, "reason": None},
                 "d2": {"team": "enemy", "me": False, "gray": a, "reason": None},
                 "d3": {"team": "ally", "me": False, "gray": a.copy(), "reason": None},
                 "d4": {"team": "ally", "me": True, "gray": a, "reason": "player_me"}}
        out = name_clusters(crops)
        self.assertEqual(out["sides"]["ally"], [["d1", "d3"]])
        self.assertEqual(out["sides"]["enemy"], [["d2"]])
        self.assertEqual(out["left_out"], {"d4": "player_me"})

    def test_followed_views_take_a_third_and_two_thirds(self):
        obs = [{"t_ms": 1000.0 + 500 * i, "observation_key": f"s:{10 + i}:{2 - i // 3}:killer"}
               for i in range(6)]
        self.assertEqual(followed_views(obs), [(2000.0, 2, 12), (3000.0, 1, 14)])


class NameAssignmentTest(unittest.TestCase):
    enemy = ["Sova", "Sage", "Omen", "Raze", "Neon"]

    def _setup(self, weak=None):
        clusters = {"sides": {"ally": [], "enemy": []}}
        evidence = {}
        for j, agent in enumerate(self.enemy):
            members = [f"e{j}:{i}" for i in range(NAME_CLUSTER_MIN)]
            clusters["sides"]["enemy"].append(members)
            for m in members:
                llr = {a: (2.0 if a == agent else -2.0) for a in self.enemy}
                if weak == agent:
                    llr = {a: 0.0 for a in self.enemy}
                evidence[m] = {"portrait": llr, "channels": []}
        return clusters, evidence

    def test_large_clusters_take_the_side_one_to_one(self):
        clusters, evidence = self._setup()
        claims = name_cluster_claims(clusters, evidence,
                                     _lineup(["Jett", "A", "B", "C", "D"], self.enemy))
        named = {c["entity_id"]: c["agent"] for c in claims}
        self.assertEqual(len(claims), 25)
        self.assertEqual(named["e2:0"], "Omen")
        self.assertTrue(all(c["channel"] == NAME_CLUSTER_CHANNEL for c in claims))
        self.assertEqual(claims[0]["depends_on"], [])

    def test_elimination_names_the_cluster_nothing_read(self):
        # Four clusters read their agents; the fifth reads nothing and takes
        # the one agent left, as the one-to-one constraint says.
        clusters, evidence = self._setup(weak="Neon")
        claims = name_cluster_claims(clusters, evidence,
                                     _lineup(["Jett", "A", "B", "C", "D"], self.enemy))
        self.assertEqual({c["agent"] for c in claims if c["entity_id"].startswith("e4:")},
                         {"Neon"})

    def test_refused_slot_is_a_rival_that_never_takes_the_name(self):
        clusters, evidence = self._setup()
        lineup = _lineup(["Jett", "A", "B", "C", "D"], self.enemy)
        lineup["sides"]["enemy"][4] = {"slot": 4, "agent": None, "best_guess": "Neon"}
        claims = name_cluster_claims(clusters, evidence, lineup)
        e4 = [c for c in claims if c["entity_id"].startswith("e4:")]
        self.assertTrue(all(c["agent"] is None for c in e4))
        self.assertTrue(e4[0]["reason"].startswith("name_cluster_best_is_refused_slot"))

    def test_blind_side_names_nothing(self):
        clusters, evidence = self._setup()
        lineup = _lineup(["Jett", "A", "B", "C", "D"], self.enemy)
        lineup["sides"]["enemy"][4] = {"slot": 4, "agent": None}
        self.assertEqual(name_cluster_claims(clusters, evidence, lineup), [])

    def test_own_channel_is_left_out_of_its_own_claim(self):
        clusters, evidence = self._setup()
        evidence["e0:0"]["channels"] = [("scoreboard_dim", "Sova")]
        table = {"agents": {}, "channels": {"scoreboard_dim": {"mean": 0.97}}}
        claims = {c["entity_id"]: c for c in name_cluster_claims(
            clusters, evidence, _lineup(["Jett", "A", "B", "C", "D"], self.enemy),
            reliability=table)}
        self.assertTrue(claims["e0:0"]["evidence"]["left_out_own_channels"])
        self.assertFalse(claims["e0:1"]["evidence"]["left_out_own_channels"])


class ReplacedPortraitVoteTest(unittest.TestCase):
    def _cluster(self, agent):
        return {"channel": NAME_CLUSTER_CHANNEL, "agent": agent, "reason": None,
                "source_version": "t", "evidence": {"n": 12}}

    def test_named_cluster_replaces_the_portrait_vote(self):
        v = adjudicate_death(
            death_id="death:s:1000:0", t_ms=1000.0, side="enemy",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Breach"},
            victim_name_claim=self._cluster("Brimstone"),
            killer_claim={"channel": "killfeed_portrait", "agent": "Sova"},
            killer_name_claim=self._cluster("Sage"))
        ident = v.metadata["identity"]
        self.assertEqual((ident["status"], ident["agent"]), ("resolved", "Brimstone"))
        self.assertEqual(ident["independent_channels"], 1)
        self.assertIsNone(ident["by_channel"]["killfeed_portrait"]["agent"])
        self.assertIn("per-entry said Breach", ident["by_channel"]["killfeed_portrait"]["reason"])
        self.assertEqual(v.killer, "Sage")
        self.assertIsNone(v.metadata["killer_identity"]["by_channel"]["killfeed_portrait"]["agent"])

    def test_another_channel_still_disagrees(self):
        v = adjudicate_death(
            death_id="death:s:1000:0", t_ms=1000.0, side="enemy",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Breach"},
            victim_name_claim=self._cluster("Brimstone"),
            scoreboard_claim={"channel": "scoreboard_dim", "agent": "Breach"})
        self.assertEqual(v.status, "disagreement")

    def test_refusing_cluster_keeps_the_portrait_vote(self):
        refused = dict(self._cluster(None), reason="name_cluster_posterior 0.6 below 0.9")
        v = adjudicate_death(
            death_id="death:s:1000:0", t_ms=1000.0, side="enemy",
            killfeed_claim={"channel": "killfeed_portrait", "agent": "Breach"},
            victim_name_claim=refused)
        self.assertEqual((v.status, v.victim), ("resolved", "Breach"))
        self.assertIn(NAME_CLUSTER_CHANNEL, v.metadata["identity"]["by_channel"])


if __name__ == "__main__":
    unittest.main()
