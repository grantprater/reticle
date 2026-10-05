"""The teleport-licence owner reads the player's movement facts
(`track.movement_licences`, `track.motion_for`)."""
from __future__ import annotations

import dataclasses
import unittest

from reticle import domain, track
from reticle.track import (CLASSES, DASH_PX_S, MOVEMENT_FACTS, RUN_PX, SPEED_PX_S,
                           SPEED_UNMEASURED, WEAK, admits, is_teleport, motion_for,
                           movement_licences)


class ConfirmedFacts(unittest.TestCase):
    def test_every_row_names_a_player_fact(self):
        facts = domain.load()
        for (agent, ability), (kind, key) in MOVEMENT_FACTS.items():
            self.assertIn(key, facts, f"{agent} {ability}")
            self.assertEqual(facts[key].known, "player", key)
        self.assertTrue(all(lic.confirmed for lic in movement_licences()))

    def test_classes_follow_the_confirmed_kinds(self):
        want = {"Omen": "walker_teleport", "Yoru": "walker_teleport",
                "Chamber": "walker_teleport", "Phoenix": "walker_teleport",
                "Veto": "walker_teleport", "Jett": "walker_dash", "Raze": "walker_dash",
                "Waylay": "walker_dash", "Neon": "walker_speed", "Sage": "walker",
                "KAY/O": "walker"}
        for agent, name in want.items():
            self.assertEqual(motion_for(agent).name, name, agent)
        self.assertEqual(motion_for("neon").name, "walker_speed")
        self.assertIs(motion_for(None), CLASSES["walker"])

    def test_high_gear_is_a_speed_change_not_a_jump(self):
        neon = motion_for("Neon")
        self.assertFalse(neon.may_dash or neon.may_teleport)
        self.assertTrue(neon.may_speed)

    def test_an_unconfirmed_fact_licenses_nothing(self):
        facts = domain.load()
        key = MOVEMENT_FACTS[("Omen", "Shrouded Step")][1]
        other = MOVEMENT_FACTS[("Omen", "From the Shadows")][1]
        inferred = dict(facts)
        inferred[key] = dataclasses.replace(facts[key], known="inferred")
        del inferred[other]
        rows = {(lic.agent, lic.ability): lic for lic in movement_licences(inferred)}
        self.assertFalse(rows[("Omen", "Shrouded Step")].confirmed)
        self.assertIn("not the player's", rows[("Omen", "Shrouded Step")].reason)
        self.assertIn("no fact", rows[("Omen", "From the Shadows")].reason)
        self.assertEqual(motion_for("Omen", inferred).name, "walker")

    def test_updraft_alone_licenses_no_horizontal_step(self):
        facts = dict(domain.load())
        del facts[MOVEMENT_FACTS[("Jett", "Tailwind")][1]]
        self.assertEqual(motion_for("Jett", facts).name, "walker")


class SpeedRule(unittest.TestCase):
    def test_speed_admits_up_to_its_bound_and_reports_it(self):
        neon = CLASSES["walker_speed"]
        ok, why = admits(neon, 0.5 * (RUN_PX + SPEED_PX_S), 1.0)
        self.assertEqual((ok, why), (True, SPEED_UNMEASURED))
        self.assertFalse(is_teleport(why))
        self.assertNotEqual(why, WEAK)
        self.assertFalse(admits(neon, SPEED_PX_S * 1.01, 1.0)[0])
        self.assertFalse(admits(neon, 10 * track.TELEPORT_PX, 1.0)[0])
        self.assertEqual(SPEED_PX_S, DASH_PX_S)

    def test_a_dash_class_never_jumps(self):
        jett = motion_for("Jett")
        self.assertFalse(admits(jett, 10 * track.TELEPORT_PX, 1.0)[0])


if __name__ == "__main__":
    unittest.main()
