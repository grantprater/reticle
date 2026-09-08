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
        self.assertTrue(got["agree"])
        self.assertEqual(got["witnesses"]["self_icon"]["agent"], "Sova")

    def test_no_self_icon_names_nobody(self):
        got = self.build().player("ally")
        self.assertIsNone(got["slot"])
        self.assertEqual(got["reason"], "no self icon seen")

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
        # Make the top bar unsure about the slot the self icon lands on.
        st.scores["ally"][3] = [0, 0, 0, 0.50, 0.49, 0]
        got = st.player("ally")
        self.assertFalse(got["agree"])
        self.assertIsNone(got["witnesses"]["top_bar"]["agent"])


class SlotCropTests(unittest.TestCase):
    def test_the_bar_splits_into_five_and_an_empty_bar_into_none(self):
        self.assertEqual(len(lineup.slot_crops(np.zeros((40, 100, 3), np.uint8))), 5)
        self.assertEqual(lineup.slot_crops(np.zeros((0, 0, 3), np.uint8)), [])
        self.assertEqual(lineup.slot_crops(None), [])


if __name__ == "__main__":
    unittest.main()
