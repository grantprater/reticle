import unittest

import numpy as np

from reticle.adjudication.phases import (DIM_CONTRAST_MAX, candidate_causes,
                                         segment, summarise)


def trace(pattern, step=100.0, live=240.0, dim=140.0):
    """`pattern` is a string of L and D, one character per sample."""
    times = np.arange(len(pattern), dtype=float) * step
    contrast = np.array([live if c == "L" else dim for c in pattern], float)
    return times, contrast


class SegmentTests(unittest.TestCase):
    def test_a_steady_object_is_one_phase(self):
        got = segment(*trace("L" * 40))
        self.assertEqual([p["appearance"] for p in got], ["bright"])
        self.assertEqual(got[0]["operational_state"], "unknown")

    def test_a_real_change_is_two_phases(self):
        got = segment(*trace("L" * 20 + "D" * 20))
        self.assertEqual([p["appearance"] for p in got], ["bright", "dim"])

    def test_a_flicker_is_absorbed_rather_than_becoming_a_phase(self):
        got = segment(*trace("L" * 20 + "D" + "L" * 20))
        self.assertEqual([p["appearance"] for p in got], ["bright"])
        self.assertEqual(got[0]["absorbed_transients"], 1)
        self.assertEqual(got[0]["transient_evidence"][0]["appearance"], "dim")

    def test_absorbing_a_flicker_never_leaves_two_runs_of_one_mode(self):
        """The defect this caught on the real data: appending regardless turned
        one steady sensor into four phases and reported live->live as a
        transition, which is not a transition at all."""
        for pattern in ("L" * 10 + "D" + "L" * 10 + "D" + "L" * 10,
                        "D" * 10 + "L" + "D" * 10,
                        "L" * 5 + "D" + "L" * 5 + "D" + "L" * 5 + "D" + "L" * 5):
            got = segment(*trace(pattern))
            modes = [p["appearance"] for p in got]
            self.assertEqual(modes, list(dict.fromkeys(modes)) if len(set(modes)) == 1
                             else modes)
            for a, b in zip(got, got[1:]):
                self.assertNotEqual(a["appearance"], b["appearance"],
                                    f"{pattern} produced a same-mode transition")

    def test_a_coverage_gap_is_not_filled_by_appearance(self):
        got = segment(np.array([0., 1000., 10000., 11000.]),
                      np.array([240., 240., 240., 240.]))
        self.assertEqual([p["appearance"] for p in got], ["bright", "bright"])
        self.assertEqual(got[1]["coverage_break_before_ms"], 9000.0)

    def test_the_split_is_the_measured_gap(self):
        self.assertGreater(DIM_CONTRAST_MAX, 175.0)
        self.assertLess(DIM_CONTRAST_MAX, 231.0)


class CauseTests(unittest.TestCase):
    def test_an_ally_death_is_conditional_until_the_owner_is_known(self):
        got = candidate_causes(10000.0, "deadlock:sonic sensor", "live", "dim",
                               deaths=[6000.0])
        owner = next(c for c in got if c["cause"] == "owner_death")
        self.assertEqual(owner["status"], "conditional")
        self.assertEqual(owner["evidence"]["nearby_ally_death_ms"], 4000.0)
        self.assertEqual(owner["prerequisites"]["owner_identity"], "unknown")

    def test_a_wall_is_excluded_rather_than_counted_as_a_failure(self):
        got = candidate_causes(10000.0, "deadlock:barrier mesh", "live", "dim",
                               deaths=[6000.0])
        owner = next(c for c in got if c["cause"] == "owner_death")
        self.assertEqual(owner["status"], "excluded")

    def test_the_radius_cause_is_listed_as_unavailable_not_omitted(self):
        """A channel that does not exist yet must be visible as a gap, the same
        treatment the origin model gives a birth it cannot explain."""
        got = candidate_causes(10000.0, "killjoy:turret", "live", "dim", deaths=[])
        radius = next(c for c in got if c["cause"] == "owner_left_radius")
        self.assertEqual(radius["status"], "unavailable")
        self.assertIn("no owner track", radius["limit"])

    def test_a_death_outside_the_window_does_not_support_the_transition(self):
        """The window is a candidate-generation bound, not a mechanic timing:
        a death a minute earlier explains nothing."""
        got = candidate_causes(80000.0, "deadlock:sonic sensor", "live", "dim",
                               deaths=[100.0])
        self.assertFalse([c for c in got if c["status"] == "supported"])
        owner = next(c for c in got if c["cause"] == "owner_death")
        self.assertEqual(owner["status"], "unsupported")


class StructuralRuleTests(unittest.TestCase):
    """The two rules the player's correction is about."""

    def row(self, phases):
        return {"component_id": "c1", "appearance_segments": phases, "transitions": [],
                "entity_count": 1,
                "observed_support_ms": [[phases[0]["from_ms"], phases[-1]["to_ms"]]]}

    def test_a_phase_change_does_not_create_a_second_entity(self):
        phases = [{"mode": "live", "from_ms": 0.0, "to_ms": 100.0},
                  {"mode": "dim", "from_ms": 100.0, "to_ms": 200.0}]
        row = self.row(phases)
        self.assertEqual(row["entity_count"], 1)
        self.assertEqual(summarise([row])["entities"], 1)

    def test_a_lifetime_spans_every_phase_rather_than_ending_at_one(self):
        phases = [{"mode": "live", "from_ms": 0.0, "to_ms": 100.0},
                  {"mode": "dim", "from_ms": 100.0, "to_ms": 900.0}]
        row = self.row(phases)
        self.assertEqual(row["observed_support_ms"], [[0.0, 900.0]])


if __name__ == "__main__":
    unittest.main()
