import unittest

import numpy as np

from reticle.adjudication.identity import (
    AGENT_IDENTITY_VERSION,
    AgentIdentityArbiter,
    adjudicate_agent_identity,
    claim_from_killfeed_portrait,
    claims_from_killfeed_portraits,
    claims_from_lineup,
    identity_claim,
)


def _side(named, refused=()):
    """One side's lineup rows: the named slots, then the refused ones."""
    rows = [{"slot": i, "agent": name, "best_guess": name, "margin": 0.2,
             "reason": None} for i, name in enumerate(named)]
    for j, (guess, margin) in enumerate(refused):
        rows.append({"slot": len(named) + j, "agent": None,
                     "best_guess": guess, "margin": margin,
                     "reason": f"margin {margin} below 0.07"})
    return rows


class AgentIdentityTests(unittest.TestCase):
    def test_agreement_resolves_without_losing_witnesses(self):
        result = adjudicate_agent_identity([
            identity_claim("ally:track-7", "Phoenix", channel="lineup",
                           source_version="lineup-0.3.0"),
            identity_claim("ally:track-7", "Phoenix", channel="killfeed",
                           observed_at_ms=1200),
        ])[0]
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["agent"], "Phoenix")
        self.assertEqual(result["independent_channels"], 2)
        self.assertEqual(len(result["claims"]), 2)
        self.assertEqual(result["adjudication_version"], AGENT_IDENTITY_VERSION)

    def test_lineup_claims_have_a_canonical_stored_verdict(self):
        claims = claims_from_lineup(
            {"ally": [{"slot": 0, "agent": "Sage", "margin": 0.2,
                        "best_guess": "Sage", "reason": None}],
             "enemy": []},
            {"slot": 0, "agent": "Sage", "decided_by": "self_icon_among_top_bar_candidates",
             "witnesses": {}},
            observation_id="session-1", source_version="lineup-0.3.0")
        verdict = adjudicate_agent_identity(claims)
        self.assertEqual(len(verdict), 1)
        self.assertEqual(verdict[0]["entity_id"], "session-1:ally:slot:0")
        self.assertEqual(verdict[0]["agent"], "Sage")

    def test_killfeed_portrait_is_constrained_to_lineup_candidates(self):
        gallery = {"Phoenix": [np.array([1.0, 0.0])],
                   "Sage": [np.array([0.0, 1.0])],
                   "Tejo": [np.array([0.4, 0.6])]}
        observation = {"composition": [0.95, 0.05], "role": "victim",
                       "ally": True, "slot": 2, "clipped": 0.0}
        claim = claim_from_killfeed_portrait(
            observation, entity_id="entry:victim",
            candidates=["Phoenix", "Sage"], gallery=gallery)
        self.assertEqual(claim["agent"], "Phoenix")
        self.assertEqual(claim["channel"], "killfeed_portrait")
        self.assertEqual(claim["evidence"]["candidates"], ["Phoenix", "Sage"])

    def test_killfeed_portrait_refuses_a_thin_match(self):
        gallery = {"Phoenix": [np.array([1.0, 0.0])],
                   "Sage": [np.array([0.99, 0.01])]}
        observations = [
            {"composition": [1.0, 0.0], "role": "killer", "ally": False,
             "t_ms": 1000.0},
            {"composition": [0.0, 1.0], "role": "victim", "ally": None,
             "t_ms": 1000.0},
        ]
        lineup = {"sides": {"ally": _side(["Phoenix", "Sage", "Jett",
                                           "Omen", "Sova"]),
                            "enemy": _side(["Sage", "Phoenix", "Jett",
                                            "Omen", "Sova"])}}
        claims = claims_from_killfeed_portraits(
            observations, lineup, entry_id="session:1000:3", gallery=gallery)
        self.assertIsNone(claims[0]["agent"])
        self.assertIn("portrait_margin", claims[0]["reason"])
        self.assertEqual(claims[1]["reason"], "portrait_side_unknown")
        self.assertEqual(claims[0]["entity_id"], "session:1000:3:killer")

    def test_a_refused_slot_is_a_rival_and_never_a_name(self):
        """The alternative must be one the side can hold. See `side_candidates`."""
        gallery = {"Sage": [np.array([1.0, 0.0, 0.0])],
                   "Raze": [np.array([0.0, 1.0, 0.0])],
                   "Jett": [np.array([0.0, 0.0, 1.0])]}
        jett_ish = {"composition": [0.0, 0.3, 0.7], "role": "victim",
                    "ally": False, "t_ms": 4.0, "reason": ""}
        # Drop the refused slot and this portrait of Jett is named Raze, at a
        # margin of 0.3 that clears the gate -- the fault this rule removes.
        loose = claim_from_killfeed_portrait(
            jett_ish, entity_id="e:victim", candidates=["Sage", "Raze"],
            gallery=gallery)
        self.assertEqual(loose["agent"], "Raze")

        lineup = {"sides": {"ally": _side(["Omen"] * 5),
                            "enemy": _side(["Sage", "Raze", "Omen", "Sova"],
                                           refused=[("Jett", 0.04)])}}
        claim = claims_from_killfeed_portraits(
            [jett_ish], lineup, entry_id="E", gallery=gallery)[0]
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "portrait_best_is_refused_slot Jett")
        self.assertEqual(claim["evidence"]["rivals"], ["Jett"])

    def test_a_slot_with_no_candidate_blinds_the_whole_side(self):
        gallery = {"Sage": [np.array([1.0, 0.0])], "Raze": [np.array([0.0, 1.0])]}
        lineup = {"sides": {"ally": _side(["Sage", "Raze"],
                                          refused=[(None, 0.01)]),
                            "enemy": _side(["Omen"] * 5)}}
        claim = claims_from_killfeed_portraits(
            [{"composition": [1.0, 0.0], "role": "killer", "ally": True,
              "t_ms": 9.0}], lineup, entry_id="E", gallery=gallery)[0]
        self.assertIsNone(claim["agent"])
        self.assertTrue(claim["reason"].startswith("lineup_incomplete: 2 of 5"))

    def test_the_readers_own_refusal_is_quoted_not_rediagnosed(self):
        lineup = {"sides": {"ally": _side(["Sage"] * 5),
                            "enemy": _side(["Omen"] * 5)}}
        claim = claims_from_killfeed_portraits(
            [{"slot": 1, "role": "victim", "ally": True,
              "reason": "no gap past the name"}],
            lineup, entry_id="E", gallery={})[0]
        self.assertEqual(claim["reason"], "no gap past the name")
        self.assertEqual(claim["evidence"]["observation_reason"],
                         "no gap past the name")

    def test_conflict_is_not_resolved_by_majority(self):
        result = adjudicate_agent_identity([
            identity_claim("enemy:track-2", "Breach", channel="lineup"),
            identity_claim("enemy:track-2", "Tejo", channel="killfeed"),
            identity_claim("enemy:track-2", "Breach", channel="scoreboard"),
        ])[0]
        self.assertEqual(result["status"], "disagreement")
        self.assertIsNone(result["agent"])
        self.assertEqual(result["agents_seen"], ["Breach", "Tejo"])
        self.assertEqual(result["reason"], "conflicting_claims")

    def test_abstention_is_distinct_from_disagreement(self):
        result = adjudicate_agent_identity([
            identity_claim("ally:track-9", channel="killfeed",
                           reason="portrait_clipped"),
            identity_claim("ally:track-9", channel="minimap",
                           reason="no_self_icon"),
        ])[0]
        self.assertEqual(result["status"], "abstained")
        self.assertIsNone(result["agent"])
        self.assertEqual(result["reason"], "all_claims_abstained")
        self.assertEqual(result["claims"][0]["reason"], "portrait_clipped")

    def test_no_claims_produce_no_observation(self):
        self.assertEqual(adjudicate_agent_identity([]), [])

    def test_accumulator_keeps_raw_claims_and_recomputes(self):
        arbiter = AgentIdentityArbiter()
        arbiter.add(identity_claim("self", "Phoenix", channel="tray"))
        self.assertEqual(arbiter.verdict()[0]["agent"], "Phoenix")
        self.assertEqual(arbiter.claims[0]["channel"], "tray")

    def test_lineup_publishes_top_bar_and_deciding_player_witness(self):
        sides = {"ally": [{"slot": 0, "agent": "Phoenix", "margin": 0.2,
                            "best_guess": "Phoenix", "reason": None}],
                 "enemy": []}
        player = {"slot": 0, "agent": "Phoenix",
                  "decided_by": "ability_tray", "agree": "agrees",
                  "witnesses": {"tray": {"agent": "Phoenix"}}}
        claims = claims_from_lineup(sides, player, observation_id="s1",
                                    source_version="lineup-0.3.0")
        self.assertEqual({c["channel"] for c in claims},
                         {"top_bar", "ability_tray"})
        result = adjudicate_agent_identity(claims)[0]
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["agent"], "Phoenix")
        self.assertEqual(result["independent_channels"], 2)


if __name__ == "__main__":
    unittest.main()
