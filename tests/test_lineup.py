import unittest

import numpy as np

from reticle import lineup
from reticle.store import Store


class AbilityNamingTests(unittest.TestCase):
    """`agent:ability` is a lookup once the agent is known, not a matcher."""

    def setUp(self):
        self.store = Store().root

    def test_every_tray_slot_resolves_for_a_known_agent(self):
        got = lineup.abilities_for("Phoenix", self.store)
        self.assertEqual(got, {"C": "Blaze", "Q": "Hot Hands",
                               "E": "Curveball", "X": "Run it Back"})

    def test_the_asset_spelling_of_kayo_reaches_the_reference(self):
        # The art cannot hold "/" so it is `KAY_O`; the reference is `KAY/O`.
        self.assertEqual(lineup.abilities_for("KAY_O", self.store)["E"],
                         "ZERO/point")

    def test_label_matches_the_hand_labelled_form(self):
        self.assertEqual(lineup.ability_label("Phoenix", "C", self.store),
                         "phoenix:blaze")

    def test_an_unknown_half_names_nothing(self):
        self.assertIsNone(lineup.ability_label(None, "C", self.store))
        self.assertIsNone(lineup.ability_label("Phoenix", None, self.store))
        self.assertIsNone(lineup.ability_label("NotAnAgent", "C", self.store))


class VerdictTests(unittest.TestCase):
    """A slot is named only when it is SEPARATED from the runner-up."""

    def build(self, rows):
        gal = {n: [np.zeros(4, np.float32)] for n in
               ("Astra", "Breach", "Cypher", "Phoenix", "Sage", "Sova")}
        st = lineup.Lineup(gal)
        st.frames = 1
        st.scores["ally"] = np.array(rows, dtype=float)
        return st

    def test_a_clear_slot_is_named_and_a_close_one_is_refused(self):
        names = ["Astra", "Breach", "Cypher", "Phoenix", "Sage", "Sova"]
        rows = np.zeros((5, 6))
        rows[0] = [0.9, 0.2, 0, 0, 0, 0]        # Astra, wide margin
        rows[1] = [0, 0.50, 0.49, 0, 0, 0]      # Breach vs Cypher, too close
        rows[2] = [0, 0, 0, 0.9, 0.1, 0]
        rows[3] = [0, 0, 0, 0, 0.9, 0.1]
        rows[4] = [0, 0, 0, 0, 0, 0.9]
        out = self.build(rows).verdict("ally", margin_min=0.07)
        self.assertEqual(out[0]["agent"], "Astra")
        self.assertIsNone(out[1]["agent"])
        self.assertEqual(out[1]["best_guess"], "Breach")
        self.assertIn("not separated from", out[1]["reason"])
        self.assertEqual([r["agent"] for r in out[2:]],
                         ["Phoenix", "Sage", "Sova"])

    def test_a_refused_slot_still_reports_its_margin(self):
        rows = np.full((5, 6), 0.5)
        out = self.build(rows).verdict("ally")
        self.assertTrue(all(r["agent"] is None for r in out))
        self.assertTrue(all(r["margin"] == 0.0 for r in out))
        self.assertTrue(all(r["best_guess"] for r in out))

    def test_a_tie_the_assignment_already_broke_is_NAMED(self):
        """The 12 of 79 refusals the old margin threw away.

        Slot 0 is near-tied between Sage and Sova, and slot 1 wants Sova
        outright. The constraint therefore settles slot 0 on Sage, and the
        alternative it must be separated from is not Sova at 0.85 but the whole
        assignment that giving Sova away would force.
        """
        rows = np.zeros((5, 6))
        rows[0] = [0, 0, 0, 0, 0.90, 0.85]      # Sage, barely over Sova
        rows[1] = [0, 0, 0, 0, 0.10, 0.90]      # Sova, and nothing else
        rows[2] = [0, 0, 0.9, 0, 0, 0]
        rows[3] = [0, 0, 0, 0.9, 0, 0]
        rows[4] = [0.9, 0, 0, 0, 0, 0]
        out = self.build(rows).verdict("ally", margin_min=0.07)
        self.assertEqual(out[0]["agent"], "Sage")
        self.assertEqual(out[1]["agent"], "Sova")
        # The old rule saw 0.90 - 0.85 = 0.05 and refused.
        self.assertGreater(out[0]["margin"], 0.07)

    def test_a_tie_with_an_agent_NOBODY_else_wants_is_still_refused(self):
        """The other half: the rule must not name everything it touches."""
        rows = np.zeros((5, 6))
        rows[0] = [0, 0, 0, 0, 0.90, 0.85]      # Sage vs Sova, both free
        rows[1] = [0, 0.9, 0, 0, 0, 0]
        rows[2] = [0, 0, 0.9, 0, 0, 0]
        rows[3] = [0, 0, 0, 0.9, 0, 0]
        rows[4] = [0.9, 0, 0, 0, 0, 0]
        out = self.build(rows).verdict("ally", margin_min=0.07)
        self.assertIsNone(out[0]["agent"])
        self.assertAlmostEqual(out[0]["margin"], 0.05, places=4)
        self.assertEqual(out[0]["rival"], "Sova")

    def test_the_reason_names_the_rival_the_constraint_PERMITS(self):
        """A refusal's reason must name an alternative that was available."""
        rows = np.zeros((5, 6))
        rows[0] = [0, 0, 0, 0, 0.90, 0.89]      # closest rival is Sova...
        rows[1] = [0, 0, 0, 0, 0.05, 0.95]      # ...but slot 1 owns Sova
        rows[2] = [0, 0, 0.9, 0, 0, 0]
        rows[3] = [0, 0, 0, 0.9, 0, 0]
        rows[4] = [0.88, 0, 0, 0, 0, 0]         # Astra, weakly
        out = self.build(rows).verdict("ally", margin_min=5.0)   # refuse all
        self.assertNotEqual(out[0]["rival"], "Sova")
        self.assertIn(out[0]["rival"], out[0]["reason"])

    def test_adjudicate_is_pure_over_the_stored_matrix(self):
        """A stored lineup can be re-adjudicated without opening the capture."""
        rows = np.zeros((5, 6))
        rows[0] = [0.9, 0.2, 0, 0, 0, 0]
        rows[1] = [0, 0.50, 0.49, 0, 0, 0]
        rows[2] = [0, 0, 0, 0.9, 0.1, 0]
        rows[3] = [0, 0, 0, 0, 0.9, 0.1]
        rows[4] = [0, 0, 0, 0, 0, 0.9]
        st = self.build(rows)
        self.assertEqual(
            lineup.assign_side(st.mean_scores("ally"), st.names, st.frames,
                              "ally", 0.07),
            st.verdict("ally", margin_min=0.07))

    def test_the_five_slots_cannot_be_one_agent(self):
        # Every slot looks most like Sage; the assignment must still spread.
        rows = np.zeros((5, 6))
        for i in range(5):
            rows[i] = [0.1, 0.2, 0.3, 0.4, 0.9, 0.05]
        out = self.build(rows).verdict("ally", margin_min=0.0)
        self.assertEqual(len({r["agent"] for r in out}), 5)


class PlayerCorroborationTests(unittest.TestCase):
    """The self icon ranks the five the top bar proposes; the arbiter decides."""

    def build(self):
        gal = {n: [np.zeros(4, np.float32)] for n in
               ("Astra", "Breach", "Cypher", "Phoenix", "Sage", "Sova")}
        st = lineup.Lineup(gal)
        st.frames = 1
        rows = np.zeros((5, 6))
        rows[0] = [0.9, 0.1, 0, 0, 0, 0]        # Astra
        rows[1] = [0, 0.9, 0.1, 0, 0, 0]        # Breach
        rows[2] = [0, 0, 0.9, 0.1, 0, 0]        # Cypher
        rows[3] = [0, 0, 0, 0.9, 0.1, 0]        # Phoenix
        rows[4] = [0, 0, 0, 0, 0.9, 0.1]        # Sage
        st.scores["ally"] = rows
        return st

    def test_the_self_icon_picks_which_of_the_five_is_the_player(self):
        st = self.build()
        st.self_n = 1
        # The self icon likes Phoenix best AMONG the five on the team, even
        # though it is not the global maximum -- Sova is, and Sova is not here.
        st.self_scores = np.array([0.2, 0.1, 0.1, 0.8, 0.1, 0.95])
        got = st.result("s")
        who = got["player"]
        self.assertEqual((who["agent"], who["slot"], who["status"]), ("Phoenix", 3, "resolved"))
        self.assertEqual(who["channels"], ["self_icon"])
        claim = next(c for c in got["identity_claims"] if c["channel"] == "self_icon")
        self.assertEqual(claim["evidence"]["global_best"], "Sova")
        # Its candidates came from the top bar, so it rests on the ally slots.
        self.assertEqual(len(claim["depends_on"]), 5)

    def test_no_witness_names_nobody_and_says_why(self):
        who = self.build().result("s")["player"]
        self.assertEqual((who["agent"], who["slot"], who["status"]), (None, None, "abstained"))
        self.assertEqual(who["witnesses"]["self_icon"]["reason"], "no_self_icon_frames")
        self.assertTrue(who["witnesses"]["ability_tray"]["reason"].startswith("tray_unread"))

    def test_a_flat_self_witness_refuses_rather_than_picking_slot_zero(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.full(6, 0.5)
        who = st.result("s")["player"]
        self.assertIsNone(who["slot"])
        self.assertIn("below", who["witnesses"]["self_icon"]["reason"])

    def test_a_silent_top_bar_is_not_a_disagreement(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.array([0.2, 0.1, 0.1, 0.8, 0.1, 0.95])
        # Make the top bar unsure about the slot the self icon lands on. The
        # rival has to be Sova, the one agent no other slot claims: a tie with
        # Sage would not be one, because the assignment gives Sage to slot 4
        # and the margin is measured against what the constraint PERMITS.
        st.scores["ally"][3] = [0, 0, 0, 0.50, 0, 0.49]
        got = st.result("s")
        who = got["player"]
        self.assertEqual((who["agent"], who["slot"], who["top_bar"]), ("Phoenix", 3, None))
        slot = next(v for v in got["agent_identity"] if v["entity_id"] == "s:ally:slot:3")
        self.assertEqual((slot["status"], slot["independent_channels"]), ("resolved", 0))


class TrayWitnessTests(unittest.TestCase):
    """The tray names the agent outright; it is one witness among the player's."""

    def build(self):
        gal = {n: [np.zeros(4, np.float32)] for n in
               ("Astra", "Breach", "Cypher", "Phoenix", "Sage", "Sova")}
        st = lineup.Lineup(gal)
        st.frames = 1
        rows = np.zeros((5, 6))
        for i, j in enumerate((0, 1, 2, 3, 4)):
            rows[i, j] = 0.9
            rows[i, (j + 1) % 6] = 0.1
        st.scores["ally"] = rows
        return st

    def test_the_tray_names_the_player_without_a_self_icon(self):
        st = self.build()
        st.tray_votes = {"Phoenix": 9, "Sage": 2}
        st.tray_frames = 12
        got = st.result("s")
        who = got["player"]
        self.assertEqual((who["agent"], who["slot"]), ("Phoenix", 3))
        self.assertEqual(who["channels"], ["ability_tray"])
        self.assertEqual(got["player_witnesses"]["tray"]["votes"], {"Phoenix": 9, "Sage": 2})
        slot = next(v for v in got["agent_identity"] if v["entity_id"] == "s:ally:slot:3")
        self.assertEqual(slot["channels"], ["player_agent", "top_bar"])
        self.assertEqual(slot["independent_channels"], 1)

    def test_a_tray_agent_nobody_on_the_team_has_is_refused_not_forced(self):
        st = self.build()
        st.tray_votes = {"Sova": 9}
        st.tray_frames = 12
        st.scores["ally"][:, 5] = 0.0     # no slot proposes Sova
        who = st.result("s")["player"]
        self.assertEqual((who["agent"], who["slot"], who["status"]), (None, None, "unbound"))
        self.assertIn("no_ally_slot", who["reason"])

    def test_the_self_icon_names_the_player_when_the_tray_is_silent(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.array([0.1, 0.1, 0.1, 0.8, 0.1, 0.2])
        who = st.result("s")["player"]
        self.assertEqual((who["agent"], who["channels"]), ("Phoenix", ["self_icon"]))

    def test_the_tray_and_self_icon_disagreeing_names_nobody(self):
        # `Lineup.player` let the tray win and never published the self icon.
        st = self.build()
        st.tray_votes = {"Sage": 9}
        st.self_n = 1
        st.self_scores = np.array([0.1, 0.1, 0.1, 0.8, 0.1, 0.2])
        who = st.result("s")["player"]
        self.assertEqual((who["agent"], who["slot"], who["status"]),
                         (None, None, "disagreement"))
        self.assertEqual(who["agents_seen"], ["Phoenix", "Sage"])

    def test_a_tied_tray_refuses(self):
        st = self.build()
        st.tray_votes = {"Sage": 4, "Phoenix": 4}
        who = st.result("s")["player"]
        self.assertEqual(who["status"], "abstained")
        self.assertEqual(who["witnesses"]["ability_tray"]["reason"], "tray_tie Phoenix Sage")

    def test_a_legacy_file_reads_its_tray_winner(self):
        from reticle.adjudication.identity import (adjudicate_agent_identity,
                                                   claims_from_lineup,
                                                   lineup_player_witnesses,
                                                   player_identity)
        st = self.build()
        old = {"sides": {"ally": st.verdict("ally"), "enemy": []},
               "tray": {"agent": "Phoenix", "votes": 9, "total": 11, "frames_offered": 12}}
        w = lineup_player_witnesses(old)
        self.assertEqual((w["legacy"], w["tray"]["other_votes"]), (True, 2))
        claims = claims_from_lineup(old["sides"], w, observation_id="s")
        who = player_identity({"identity_claims": claims,
                               "agent_identity": adjudicate_agent_identity(claims)}, "s")
        self.assertEqual((who["agent"], who["slot"]), ("Phoenix", 3))

    def test_a_glyph_mask_that_fills_its_cell_is_refused(self):
        # The failure that made this witness lie: a flooded mask still has a
        # nearest neighbour, and its margin looks healthy.
        frame = np.full((1080, 1920, 3), 255, np.uint8)     # everything bright
        self.assertEqual(lineup.tray_shapes(frame), {})
        dark = np.zeros((1080, 1920, 3), np.uint8)
        self.assertEqual(lineup.tray_shapes(dark), {})

    def test_one_readable_slot_is_not_an_identification(self):
        glyphs = {"A": {"C": np.ones((48, 48), np.float32)},
                  "B": {"C": np.zeros((48, 48), np.float32)}}
        frame = np.zeros((1080, 1920, 3), np.uint8)
        self.assertEqual(lineup.tray_vote(frame, glyphs)[0], None)


class SlotCropTests(unittest.TestCase):
    def test_the_bar_splits_into_five_and_an_empty_bar_into_none(self):
        self.assertEqual(len(lineup.slot_crops(np.zeros((40, 100, 3), np.uint8))), 5)
        self.assertEqual(lineup.slot_crops(np.zeros((0, 0, 3), np.uint8)), [])
        self.assertEqual(lineup.slot_crops(None), [])


if __name__ == "__main__":
    unittest.main()


class LoadLineupBoardTests(unittest.TestCase):
    """A stored board whose verdicts the reader still reproduces is APPLIED;
    only a version that changed verdicts, or no board, leaves the top bar alone."""

    def store_with(self, board_version):
        import json
        import tempfile
        from pathlib import Path
        root = Path(tempfile.mkdtemp())
        (root / "lineups").mkdir()
        (root / "lineups" / "s1.json").write_text(json.dumps(
            {"version": "lineup-test", "sides": {}, "player": None}), encoding="utf-8")
        if board_version is not None:
            d = root / "events" / "scoreboard"
            d.mkdir(parents=True)
            (d / "s1.jsonl").write_text(json.dumps(
                {"scoreboard_version": board_version, "kind": "coverage"}) + "\n", encoding="utf-8")
        return root

    def test_the_current_version_applies_and_says_it_is_current(self):
        from reticle.version import SCOREBOARD_VERSION
        got = lineup.load_lineup("s1", self.store_with(SCOREBOARD_VERSION))
        self.assertEqual(got["board_state"], {"applied": True, "version": SCOREBOARD_VERSION,
                                              "current": True})

    def test_a_compatible_older_version_applies_and_says_it_is_not_current(self):
        got = lineup.load_lineup("s1", self.store_with("scoreboard-0.6.0"))
        self.assertEqual(got["board_state"], {"applied": True, "version": "scoreboard-0.6.0",
                                              "current": False})

    def test_a_version_that_changed_verdicts_is_refused_with_its_reason(self):
        got = lineup.load_lineup("s1", self.store_with("scoreboard-0.5.0"))
        self.assertFalse(got["board_state"]["applied"])
        self.assertTrue(got["board_state"]["reason"].startswith("stale_version scoreboard-0.5.0"))

    def test_a_board_newer_than_this_code_names_the_checkout_not_the_board(self):
        """A worktree older than the store once read a rescanned 0.13.0 board
        as `stale_version` and blamed the rescan for the top bar's refusals."""
        from reticle.version import SCOREBOARD_VERSION
        major, minor, patch = lineup._version_key(SCOREBOARD_VERSION)
        newer = f"scoreboard-{major}.{minor + 1}.0"
        got = lineup.load_lineup("s1", self.store_with(newer))
        self.assertFalse(got["board_state"]["applied"])
        self.assertTrue(got["board_state"]["reason"].startswith(
            f"code_older_than_store {newer} > {SCOREBOARD_VERSION}"))

    def test_no_board_is_said_so(self):
        got = lineup.load_lineup("s1", self.store_with(None))
        self.assertEqual(got["board_state"], {"applied": False, "reason": "no_scoreboard"})
