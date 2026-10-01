"""The candidate owner: descriptors from the appearance facts, refusals with
their reasons, and the set a lineup and the living roster allow."""
from __future__ import annotations

import unittest
from types import SimpleNamespace

from reticle import ability_candidates as C
from reticle import ability_shapes as S
from reticle.geometry import MapScale


def _ms(scale=1.0, key="split__valorant-16x9-bigmap"):
    return MapScale(key, scale, 1.0, "test")


class DescriptorTest(unittest.TestCase):
    def test_a_ring_takes_its_maps_radius_times_the_scale(self):
        d = C.ability_descriptor("Regrowth", "ally", _ms(0.5))
        f = C.facts()["abilities/skye-regrowth-minimap-ring-size"]
        self.assertAlmostEqual(d["radius_px"], 0.5 * f.values["base_radius"]["split"], 5)
        self.assertEqual(d["shape"], "ring")
        self.assertEqual(d["prior"], "caster")

    def test_a_map_with_no_measured_radius_refuses(self):
        d = C.ability_descriptor("Regrowth", "ally", _ms(key="haven__valorant-16x9"))
        self.assertTrue(d["refused"].startswith("no_radius_on_map"))

    def test_an_unmeasured_side_refuses_rather_than_borrowing(self):
        d = C.ability_descriptor("Barrier Orb", "enemy", _ms())
        self.assertTrue(d["refused"].startswith("no_enemy_colour"))

    def test_an_ability_with_no_fact_refuses(self):
        self.assertEqual(C.ability_descriptor("Owl Drone", "ally", _ms())["refused"],
                         "no_appearance_fact")

    def test_walls_carry_their_drawn_sizes(self):
        d = C.ability_descriptor("Barrier Orb", "ally", _ms())
        self.assertEqual(len(d["pieces_px"]), 3)
        self.assertLess(d["pieces_px"][-1], d["length_px"])
        b = C.ability_descriptor("Blaze", "ally", _ms())
        self.assertLess(b["length_px"][0], b["length_px"][1])
        self.assertEqual(b["colour"], S.colour_model(*[
            C.facts()["abilities/phoenix-blaze-minimap-size"].values[k]
            for k in ("ally_hue", "ally_sat_p10")]))


class SupplyTest(unittest.TestCase):
    def _supply(self, ally, enemy, alive_ally, player="Skye"):
        snap = SimpleNamespace(t_ms=0.0, ally_agents=alive_ally, enemy_agents=list(enemy))
        sides = {"ally": {"named": list(ally), "rivals": [], "blind": []},
                 "enemy": {"named": list(enemy), "rivals": [], "blind": []}}
        return C.CandidateSupply("s", _ms(), sides, player, [snap], [0.0],
                                 seed_at=lambda t: (10.0, 20.0), rests_on={"lineup": "x"})

    def test_only_the_lineups_agents_are_candidates(self):
        got = self._supply(["Skye", "Sage", "Omen", "Raze", "Jett"], ["Neon"] * 1,
                           ["Skye", "Sage", "Omen", "Raze", "Jett"]).at(5.0)
        names = {(c["ability"], c["side"]) for c in got["candidates"]}
        self.assertEqual(names, {("Regrowth", "ally"), ("Barrier Orb", "ally")})
        why = {(e["ability"], e["side"]): e["reason"] for e in got["excluded"]}
        self.assertEqual(why[("Recon Bolt", "ally")], "not_in_lineup")

    def test_a_dead_skye_draws_no_regrowth_but_a_dead_sage_keeps_her_wall(self):
        got = self._supply(["Skye", "Sage"], [], ["Omen"]).at(5.0)
        why = {(e["ability"], e["side"]): e["reason"] for e in got["excluded"]}
        self.assertTrue(why[("Regrowth", "ally")].startswith("caster_dead"))
        sage = next(c for c in got["candidates"] if c["ability"] == "Barrier Orb")
        self.assertIs(sage["caster_alive"], False)
        self.assertEqual(sage["persistence"], "unasked")

    def test_the_players_caster_prior_takes_the_seed(self):
        got = self._supply(["Skye"], [], ["Skye"]).at(5.0)
        reg = next(c for c in got["candidates"] if c["ability"] == "Regrowth")
        self.assertEqual(reg["seed"], (10.0, 20.0))
        self.assertEqual(reg["rests_on"], ["lineup"])


class LockdownTest(unittest.TestCase):
    def test_the_enemy_ring_takes_the_measured_radius_and_yellow(self):
        d = C.ability_descriptor("Lockdown", "enemy", _ms(0.5))
        f = C.facts()["abilities/killjoy-lockdown-enemy-minimap-ring"]
        self.assertAlmostEqual(d["radius_px"], 0.5 * f.values["base_radius"]["split"], 5)
        self.assertEqual((d["agent"], d["shape"], d["prior"]), ("Killjoy", "ring", "free"))
        lo, hi = d["colour"]["hue"]
        self.assertLess(hi, S.TEAL_H[0])

    def test_the_ally_ring_refuses_rather_than_borrowing_the_enemys(self):
        d = C.ability_descriptor("Lockdown", "ally", _ms())
        self.assertTrue(d["refused"].startswith("no_ally_colour"))


class OpenSlotTest(unittest.TestCase):
    def _at(self, enemy_rows):
        from reticle.adjudication.identity import side_candidates
        sides = {"ally": {"named": [], "rivals": [], "blind": []},
                 "enemy": {**side_candidates(enemy_rows),
                           "open_reasons": C.open_reasons(enemy_rows)}}
        snap = SimpleNamespace(t_ms=0.0, ally_agents=[], enemy_agents=[])
        return C.CandidateSupply("s", _ms(), sides, None, [snap], [0.0]).at(5.0)

    def test_a_refused_slot_opens_every_agent_the_side_has_not_named(self):
        rows = [{"slot": i, "agent": a, "best_guess": a} for i, a in
                enumerate(["Reyna", "Neon", "Miks"])]
        rows += [{"slot": 3, "agent": None, "best_guess": "Skye",
                  "reason": "margin 0.028 below 0.07 -- not separated from Breach"},
                 {"slot": 4, "agent": None, "best_guess": "Astra",
                  "reason": "margin 0.020 below 0.07 -- not separated from Raze"}]
        got = self._at(rows)
        lock = next(c for c in got["candidates"] if c["ability"] == "Lockdown")
        self.assertTrue(lock["selected"].startswith("open_slot: 2 slot(s) unread"))
        self.assertIn("slot 4: margin 0.020 below 0.07 -- not separated from Raze "
                      "(best guess Astra)", lock["selected"])
        self.assertNotIn("refused best guess", lock["selected"])

    def test_a_fully_named_side_keeps_its_five(self):
        rows = [{"slot": i, "agent": a} for i, a in
                enumerate(["Reyna", "Neon", "Skye", "Miks", "Killjoy"])]
        got = self._at(rows)
        enemy = {c["ability"] for c in got["candidates"] if c["side"] == "enemy"}
        self.assertEqual(enemy, {"Lockdown"})
        why = {(e["ability"], e["side"]): e["reason"] for e in got["excluded"]}
        self.assertEqual(why[("Blaze", "enemy")], "not_in_lineup")


if __name__ == "__main__":
    unittest.main()
