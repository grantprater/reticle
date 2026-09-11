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
            lineup.adjudicate(st.mean_scores("ally"), st.names, st.frames,
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
    """Two witnesses that answer DIFFERENT questions, kept apart on purpose."""

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
        got = st.player("ally")
        self.assertEqual(got["slot"], 3)
        self.assertEqual(got["agent"], "Phoenix")
        self.assertEqual(got["agree"], "agrees")
        self.assertEqual(got["witnesses"]["self_icon"]["agent"], "Sova")

    def test_no_self_icon_names_nobody(self):
        got = self.build().player("ally")
        self.assertIsNone(got["slot"])
        self.assertEqual(got["reason"], "no self icon and no readable tray")

    def test_a_flat_self_witness_refuses_rather_than_picking_slot_zero(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.full(6, 0.5)
        got = st.player("ally")
        self.assertIsNone(got["slot"])
        self.assertIn("below", got["reason"])

    def test_disagreement_is_recorded_not_hidden(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.array([0.2, 0.1, 0.1, 0.8, 0.1, 0.95])
        # Make the top bar unsure about the slot the self icon lands on. The
        # rival has to be Sova, the one agent no other slot claims: a tie with
        # Sage would not be one, because the assignment gives Sage to slot 4
        # and the margin is measured against what the constraint PERMITS.
        st.scores["ally"][3] = [0, 0, 0, 0.50, 0, 0.49]
        got = st.player("ally")
        # The top bar could not separate that slot; that is silence, not
        # a contradiction, and the two must not read the same.
        self.assertEqual(got["agree"], "abstained")
        self.assertIsNone(got["witnesses"]["top_bar"]["agent"])


class TrayWitnessTests(unittest.TestCase):
    """The tray names the agent outright, so it decides when it has spoken."""

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

    def test_the_tray_decides_and_needs_no_self_icon(self):
        st = self.build()
        st.tray_votes = {"Phoenix": 9}
        st.tray_frames = 12
        got = st.player("ally")
        self.assertEqual(got["agent"], "Phoenix")
        self.assertEqual(got["slot"], 3)
        self.assertEqual(got["decided_by"], "ability_tray")
        self.assertEqual(got["self_frames"], 0)

    def test_a_tray_agent_nobody_on_the_team_has_is_refused_not_forced(self):
        st = self.build()
        st.tray_votes = {"Sova": 9}       # slot 5 does not exist; five slots only
        st.tray_frames = 12
        st.scores["ally"][:, 5] = 0.0     # no slot proposes Sova
        got = st.player("ally")
        self.assertIsNone(got["slot"])
        self.assertIn("no ally slot proposes", got["reason"])

    def test_the_self_icon_still_decides_when_the_tray_is_silent(self):
        st = self.build()
        st.self_n = 1
        st.self_scores = np.array([0.1, 0.1, 0.1, 0.8, 0.1, 0.2])
        got = st.player("ally")
        self.assertEqual(got["decided_by"],
                         "self_icon_among_top_bar_candidates")
        self.assertEqual(got["agent"], "Phoenix")

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
