"""Checks for lane B's correspondence and synthetic wrong-anchor containment."""
import unittest

from reticle.adjudication.identity import adjudicate_agent_identity, identity_claim
from tools.bootstrap_b_run import changes


class BootstrapBTests(unittest.TestCase):
    def test_correspondence_refuses_changed_event(self):
        old = {"round": 4, "t_ms": 100.0, "slot": 0, "side": "ally",
               "victim": None, "killer": None}
        new = dict(old, slot=1, victim="Phoenix", victim_depends_on=[])
        with self.assertRaisesRegex(ValueError, "correspondence"):
            changes([old], [new])

    def test_wrong_anchor_is_dependent_and_conflict_stays_visible(self):
        wrong = identity_claim("synthetic-query", "Phoenix", channel="portrait-exemplar",
                               depends_on=["synthetic-wrong-anchor"])
        verdict = adjudicate_agent_identity([wrong])[0]
        self.assertEqual(verdict["agent"], "Phoenix")
        self.assertEqual(verdict["independent_channels"], 0)
        self.assertEqual(verdict["depends_on"], ["synthetic-wrong-anchor"])
        independent = identity_claim("synthetic-query", "Breach", channel="player-hud")
        conflict = adjudicate_agent_identity([wrong, independent])[0]
        self.assertEqual(conflict["status"], "disagreement")
        self.assertIsNone(conflict["agent"])
        # Withdrawal removes the learned claim from the isolated fixture.
        self.assertEqual(adjudicate_agent_identity([independent])[0]["agent"], "Breach")


if __name__ == "__main__":
    unittest.main()
