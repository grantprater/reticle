import unittest

import numpy as np

from reticle.adjudication.identity import (
    AGENT_IDENTITY_VERSION,
    AgentIdentityArbiter,
    MINIMAP_SURFACES,
    adjudicate_agent_identity,
    claim_from_killfeed_portrait,
    claim_from_minimap_icon,
    claims_from_killfeed_portraits,
    claims_from_lineup,
    claims_from_minimap_icons,
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
        # Two channels, ONE witness: `Lineup.player` found the slot by
        # searching the top bar for the tray's name, so the tray cannot
        # disagree with the top bar here and is not counted against it.
        self.assertEqual(result["channels"], ["ability_tray", "top_bar"])
        self.assertEqual(result["independent_channels"], 1)
        self.assertEqual(result["by_channel"]["ability_tray"]["binding_from"],
                         "top_bar")

    def test_repeated_views_of_one_channel_accumulate(self):
        """One entry drawn over many frames is one witness, not many."""
        frames = [identity_claim("entry-7:victim", name,
                                 channel="killfeed_portrait", observed_at_ms=t)
                  for t, name in enumerate(["Sage", "Sage", "Raze", "Sage"])]
        result = adjudicate_agent_identity(frames)[0]
        self.assertEqual(result["status"], "resolved")
        self.assertEqual(result["agent"], "Sage")
        self.assertEqual(result["independent_channels"], 1)
        channel = result["by_channel"]["killfeed_portrait"]
        self.assertEqual(channel["votes"], {"Raze": 1, "Sage": 3})
        self.assertFalse(channel["constant"])

    def test_a_tie_inside_one_channel_abstains(self):
        result = adjudicate_agent_identity([
            identity_claim("entry-8:killer", "Sage", channel="killfeed_portrait"),
            identity_claim("entry-8:killer", "Raze", channel="killfeed_portrait"),
        ])[0]
        self.assertEqual(result["status"], "abstained")
        self.assertIsNone(result["agent"])
        self.assertEqual(result["by_channel"]["killfeed_portrait"]["reason"],
                         "channel_tie Raze Sage")

    def test_an_abstaining_channel_keeps_its_commonest_reason(self):
        result = adjudicate_agent_identity([
            identity_claim("entry-9:victim", channel="killfeed_portrait",
                           reason="portrait_margin 0.010 below 0.07"),
            identity_claim("entry-9:victim", channel="killfeed_portrait",
                           reason="portrait_margin 0.010 below 0.07"),
            identity_claim("entry-9:victim", channel="killfeed_portrait",
                           reason="no gap past the name"),
            identity_claim("entry-9:victim", "Sage", channel="top_bar"),
        ])[0]
        self.assertEqual(result["agent"], "Sage")
        self.assertEqual(result["channels"], ["top_bar"])
        self.assertEqual(result["by_channel"]["killfeed_portrait"]["reason"],
                         "portrait_margin 0.010 below 0.07")

    def test_arbiter_events_emits_valid_identity_distribution_events(self):
        from reticle.events import validate_event_rows
        arbiter = AgentIdentityArbiter()
        arbiter.extend([
            identity_claim("entry-1:killer", "Jett", channel="killfeed_portrait"),
            identity_claim("entry-1:killer", "Jett", channel="lineup"),
            identity_claim("entry-2:victim", "Raze", channel="killfeed_portrait"),
            identity_claim("entry-2:victim", "Sage", channel="top_bar"),
        ])
        events = arbiter.events("session-arbiter-test", t_ms=12345.0)
        self.assertEqual(len(events), 2)
        errors = validate_event_rows(events)
        self.assertEqual(errors, [])

        resolved = next(e for e in events if e["entity_id"] == "identity:entry-1:killer")
        self.assertEqual(resolved["event_kind"], "identity_distribution")
        self.assertEqual(resolved["identity_distribution"]["distribution"], {"Jett": 1.0})
        self.assertEqual(resolved["metadata"]["status"], "resolved")

        disagreed = next(e for e in events if e["entity_id"] == "identity:entry-2:victim")
        self.assertEqual(disagreed["metadata"]["status"], "disagreement")
        self.assertEqual(disagreed["identity_distribution"]["distribution"], {"Raze": 0.5, "Sage": 0.5})

    def test_minimap_icon_claim_resolves_when_margin_clears(self):
        gallery = {"Killjoy": [np.array([1.0, 0.0])],
                   "Skye": [np.array([0.0, 1.0])],
                   "Iso": [np.array([0.5, 0.5])]}
        observation = {"composition": [0.95, 0.05], "t_ms": 294000.0, "x": 223, "y": 267, "r": 8}
        claim = claim_from_minimap_icon(
            observation, entity_id="track-1", candidates=["Killjoy", "Skye"], gallery=gallery)
        self.assertEqual(claim["agent"], "Killjoy")
        self.assertEqual(claim["channel"], "minimap_portrait")
        self.assertEqual(claim["observed_at_ms"], 294000.0)
        self.assertEqual(claim["evidence"]["candidates"], ["Killjoy", "Skye"])
        self.assertGreater(claim["evidence"]["margin"], 0.07)

    def test_minimap_icon_refuses_thin_margin(self):
        gallery = {"Killjoy": [np.array([1.0, 0.0])],
                   "Skye": [np.array([0.98, 0.02])]}
        observation = {"composition": [1.0, 0.0], "t_ms": 294000.0}
        claim = claim_from_minimap_icon(
            observation, entity_id="track-2", candidates=["Killjoy", "Skye"], gallery=gallery)
        self.assertIsNone(claim["agent"])
        self.assertIn("icon_margin", claim["reason"])

    def test_minimap_icon_refuses_question_mark(self):
        observation = {"marked_kind": "question", "t_ms": 1161907.0, "x": 205, "y": 273}
        claim = claim_from_minimap_icon(
            observation, entity_id="icon-q", candidates=["Killjoy", "Skye"], gallery={})
        self.assertIsNone(claim["agent"])
        self.assertEqual(claim["reason"], "minimap_icon_question_mark")

    def test_minimap_icon_uses_precomputed_scores_when_present(self):
        observation = {"scores": {"Killjoy": 0.85, "Skye": 0.50}, "t_ms": 100.0}
        claim = claim_from_minimap_icon(
            observation, entity_id="track-3", candidates=["Killjoy", "Skye"], gallery={})
        self.assertEqual(claim["agent"], "Killjoy")
        self.assertEqual(claim["evidence"]["best_guess"], "Killjoy")
        self.assertAlmostEqual(claim["evidence"]["margin"], 0.35, places=5)

    def test_claims_from_minimap_icons_respects_lineup_and_entity_key(self):
        lineup = {"sides": {"enemy": _side(["Killjoy", "Skye", "Iso", "Omen", "Jett"])}}
        gallery = {"Killjoy": [np.array([1.0, 0.0])],
                   "Skye": [np.array([0.0, 1.0])],
                   "Iso": [np.array([0.0, 0.0])],
                   "Omen": [np.array([0.0, 0.0])],
                   "Jett": [np.array([0.0, 0.0])]}
        observations = [
            {"composition": [1.0, 0.0], "t_ms": 1000, "x": 10, "y": 20, "track_id": 42},
            {"composition": [0.0, 1.0], "t_ms": 2000, "x": 30, "y": 40, "track_id": 42},
        ]
        claims = claims_from_minimap_icons(observations, lineup, gallery=gallery)
        self.assertEqual(len(claims), 2)
        self.assertEqual(claims[0]["entity_id"], "minimap:enemy:track:42")
        self.assertEqual(claims[0]["agent"], "Killjoy")
        self.assertEqual(claims[1]["agent"], "Skye")

    def test_claims_from_minimap_icons_refuses_when_lineup_is_blind(self):
        lineup = {"sides": {"enemy": [{"slot": 0, "agent": None, "best_guess": None}]}}
        claims = claims_from_minimap_icons([{"composition": [1.0, 0.0], "t_ms": 100}], lineup, gallery={})
        self.assertIsNone(claims[0]["agent"])
        self.assertIn("lineup_incomplete", claims[0]["reason"])

    def test_minimap_and_killfeed_cross_channel_adjudication(self):
        """Cross-channel corroboration between minimap and killfeed claims."""
        arbiter = AgentIdentityArbiter()
        entity = "round4:enemy:entity-1"
        arbiter.add(identity_claim(entity, "Killjoy", channel="minimap_portrait", observed_at_ms=294100.0))
        arbiter.add(identity_claim(entity, "Killjoy", channel="killfeed_portrait", observed_at_ms=295000.0))
        verdicts = arbiter.verdict()
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0]["status"], "resolved")
        self.assertEqual(verdicts[0]["agent"], "Killjoy")
        self.assertEqual(verdicts[0]["independent_channels"], 2)


if __name__ == "__main__":
    unittest.main()


class DependentClaimTests(unittest.TestCase):
    def test_a_claim_resting_on_other_verdicts_is_not_independent(self):
        from reticle.adjudication.identity import adjudicate_agent_identity, identity_claim
        got = adjudicate_agent_identity([
            identity_claim("death:2", "Miks", channel="scoreboard_dim",
                           depends_on=["death:1", "death:3"])])[0]
        self.assertEqual((got["status"], got["agent"]), ("resolved", "Miks"))
        self.assertEqual(got["independent_channels"], 0)
        self.assertEqual(got["depends_on"], ["death:1", "death:3"])


class BoardSideSetTests(unittest.TestCase):
    """The scoreboard names a side's five agents; the top bar places them."""

    NAMES = ["Breach", "Clove", "Deadlock", "Iso", "Jett", "Killjoy", "Omen", "Raze", "Skye"]
    ENEMY = ["Jett", "Killjoy", "Skye", "Iso", "Omen"]

    def opening(self, t_ms, enemy=None, accepted=True):
        rows = []
        for team, agents in (("ally", ["Breach", "Deadlock", "Raze", "Clove", "Iso"]),
                             ("enemy", enemy or self.ENEMY)):
            for a in agents:
                rows.append({"team": team, "scores": {n: (0.9 if n == a else 0.3) for n in self.NAMES}})
        return {"t_ms": t_ms, "accepted": accepted, "rows": rows}

    def test_agreeing_openings_name_the_side(self):
        from reticle.adjudication.identity import board_side_sets
        got = board_side_sets([self.opening(1.0), self.opening(2.0),
                               self.opening(3.0, accepted=False)])
        self.assertEqual(sorted(got["enemy"]["agents"]), sorted(self.ENEMY))
        self.assertEqual(got["enemy"]["openings"], [1.0, 2.0])

    def test_one_opening_or_a_disagreement_refuses(self):
        from reticle.adjudication.identity import board_side_sets
        self.assertEqual(board_side_sets([self.opening(1.0)])["enemy"]["reason"],
                         "only_1_accepted_opening")
        other = ["Jett", "Killjoy", "Skye", "Iso", "Raze"]
        got = board_side_sets([self.opening(1.0), self.opening(2.0, enemy=other)])
        self.assertIsNone(got["enemy"]["agents"])
        self.assertEqual(got["enemy"]["reason"], "board_sets_disagree")

    def test_the_board_restricts_the_top_bar_and_keeps_the_disagreement(self):
        from reticle.adjudication.identity import board_side_sets, lineup_with_board
        # The top bar prefers Clove in slot 1 and cannot separate slot 0.
        scores = np.full((5, len(self.NAMES)), 0.2)
        best = {0: "Breach", 1: "Clove", 2: "Skye", 3: "Iso", 4: "Omen"}
        for slot, a in best.items():
            scores[slot, self.NAMES.index(a)] = 0.8
        scores[1, self.NAMES.index("Killjoy")] = 0.7
        scores[0, self.NAMES.index("Jett")] = 0.79
        lineup = {"session": "s", "version": "lineup-test", "frames": 10,
                  "scores": {"names": self.NAMES, "enemy": scores.tolist(),
                             "ally": scores.tolist()},
                  "sides": {"enemy": [{"slot": i, "agent": a if i else None}
                                      for i, a in best.items()]},
                  "player": None}
        board = board_side_sets([self.opening(1.0), self.opening(2.0)])
        got = lineup_with_board(lineup, board)
        self.assertEqual([r["agent"] for r in got["sides"]["enemy"]],
                         ["Jett", "Killjoy", "Skye", "Iso", "Omen"])
        self.assertIn({"side": "enemy", "slot": 1, "top_bar": "Clove",
                       "with_board": "Killjoy", "board_agents": board["enemy"]["agents"]},
                      got["board_disagreements"])
        self.assertEqual(got["top_bar_sides"]["enemy"][1]["agent"], "Clove")
