from __future__ import annotations

import unittest

from reticle.adjudication.reliability import beliefs, outcomes


def _row(victim_by: dict, killer_by: dict | None = None) -> dict:
    by = lambda d: {ch: {"agent": a, "depends_on": dep}
                    for ch, (a, dep) in d.items()}
    return {"kind": "death_verdict", "death_id": "d", "t_ms": 1.0, "session_id": "s",
            "metadata": {"identity": {"entity_id": "d", "by_channel": by(victim_by)},
                         "killer_identity": {"entity_id": "d:killer",
                                             "by_channel": by(killer_by or {})}}}


class ReliabilityTests(unittest.TestCase):

    def test_a_channel_is_scored_only_against_other_independent_witnesses(self):
        rows = [_row({"killfeed_portrait": ("Sage", []), "player_hud": ("Chamber", [])}),
                _row({"killfeed_portrait": ("Jett", []), "player_hud": ("Jett", [])}),
                # a reference that rests on other verdicts is no reference
                _row({"killfeed_portrait": ("Omen", []), "scoreboard_dim": ("Viper", ["x"])}),
                # no reference at all: nothing to score
                _row({"killfeed_portrait": ("Reyna", [])})]
        got = [(o["channel"], o["truth"], o["said"]) for o in outcomes(rows)]
        self.assertIn(("killfeed_portrait", "Chamber", "Sage"), got)
        self.assertIn(("killfeed_portrait", "Jett", "Jett"), got)
        self.assertNotIn("Viper", [t for _, t, _ in got])
        self.assertNotIn("Reyna", [s for _, _, s in got])

    def test_references_that_disagree_score_nothing(self):
        rows = [_row({"killfeed_portrait": ("Sage", []), "player_hud": ("Chamber", []),
                      "scoreboard_dim": ("Sage", [])})]
        scored = [o for o in outcomes(rows) if o["channel"] == "killfeed_portrait"]
        self.assertEqual(scored, [])

    def test_beliefs_are_beta_counts_with_a_uniform_prior(self):
        rows = [_row({"killfeed_portrait": ("Sage", []), "player_hud": ("Chamber", [])}),
                _row({"killfeed_portrait": ("Chamber", []), "player_hud": ("Chamber", [])}),
                _row({"killfeed_portrait": ("Chamber", []), "player_hud": ("Chamber", [])})]
        t = beliefs(outcomes(rows))
        c = t["channels"]["killfeed_portrait"]
        self.assertEqual((c["right"], c["wrong"], c["alpha"], c["beta"]), (2, 1, 3, 2))
        self.assertAlmostEqual(c["mean"], 0.6)
        # The agent's prior is the channel's rate (0.6) worth 20 observations.
        b = t["agents"]["killfeed_portrait:Chamber"]
        self.assertAlmostEqual(b["mean"], (20 * 0.6 + 2) / 23, places=3)
        self.assertEqual(t["confusions"]["killfeed_portrait"], {"Chamber read as Sage": 1})
        self.assertNotIn("killfeed_portrait:Astra", t["agents"])

    def test_a_name_is_wrong_only_if_every_naming_channel_is(self):
        from reticle.adjudication.reliability import name_probability
        table = {"channels": {"killfeed_portrait": {"mean": 0.9}, "killfeed_weapon": {"mean": 0.8}},
                 "agents": {}}
        v = {"status": "resolved", "agent": "Jett",
             "by_channel": {"killfeed_portrait": {"agent": "Jett", "depends_on": []},
                            "killfeed_weapon": {"agent": "Jett", "depends_on": []},
                            "scoreboard_dim": {"agent": "Jett", "depends_on": ["x"]}}}
        self.assertAlmostEqual(name_probability(table, v), 1 - 0.1 * 0.2)
        self.assertIsNone(name_probability(table, {"status": "abstained"}))


if __name__ == "__main__":
    unittest.main()
