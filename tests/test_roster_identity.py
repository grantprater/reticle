"""The ordered assignment that names the living, and what it refuses."""
import unittest

import numpy as np

from prototypes.roster_identity import assign_alive, shrink_events
from reticle.roster import N_SLOTS

#: Five agents, five orthogonal one-hot "compositions". Orthogonal so the
#: assignment is decided by the ORDER constraint rather than by histogram
#: similarity, which is the property under test.
ROSTER = ["A", "B", "C", "D", "E"]
GALLERY = {name: [np.eye(5, dtype=np.float32)[i]] for i, name in enumerate(ROSTER)}


def cells(*names):
    """One composition per occupied cell, in packed order."""
    return ([GALLERY[n][0] for n in names]
            + [None] * (N_SLOTS - len(names)))


class OrderedAssignmentTests(unittest.TestCase):
    def test_a_full_bar_names_every_agent_in_order(self):
        got = assign_alive(cells(*ROSTER), ROSTER, 5, GALLERY)
        self.assertEqual(got["agents"], ROSTER)
        self.assertIsNone(got["reason"])

    def test_a_full_bar_reports_NO_MARGIN_because_there_is_no_choice(self):
        """Calling this 1.0 made the most trivial case look the most confident."""
        got = assign_alive(cells(*ROSTER), ROSTER, 5, GALLERY)
        self.assertIsNone(got["margin"])

    def test_the_survivors_are_identified_after_a_death(self):
        got = assign_alive(cells("A", "C", "D", "E"), ROSTER, 4, GALLERY)
        self.assertEqual(got["agents"], ["A", "C", "D", "E"])
        self.assertGreater(got["margin"], 0.0)

    def test_a_middle_death_is_not_read_as_the_last_slot_emptying(self):
        """The packing shifts survivors left; only the ORDER recovers who left."""
        got = assign_alive(cells("A", "B", "D", "E"), ROSTER, 4, GALLERY)
        self.assertEqual(got["agents"], ["A", "B", "D", "E"])
        self.assertNotIn("C", got["agents"])

    def test_one_survivor_is_named(self):
        got = assign_alive(cells("D"), ROSTER, 1, GALLERY)
        self.assertEqual(got["agents"], ["D"])

    def test_the_answer_is_a_subsequence_never_a_reordering(self):
        """Team order is preserved, so a swapped pair must not be proposed."""
        got = assign_alive(cells("C", "A"), ROSTER, 2, GALLERY)
        self.assertEqual(got["agents"], sorted(got["agents"],
                                               key=ROSTER.index))


class RefusalTests(unittest.TestCase):
    def test_an_unreadable_alive_count_refuses(self):
        got = assign_alive(cells(*ROSTER), ROSTER, None, GALLERY)
        self.assertEqual(got["agents"], [])
        self.assertEqual(got["reason"], "no_alive")

    def test_a_missing_cell_refuses_rather_than_guessing(self):
        got = assign_alive([None] * N_SLOTS, ROSTER, 3, GALLERY)
        self.assertEqual(got["reason"], "no_cells")

    def test_AN_INCOMPLETE_ROSTER_REFUSES_THE_WHOLE_SIDE(self):
        """An unnamed agent scores zero, so it silently loses every subset.

        Without this the assignment reports a NAMED agent alive in a cell whose
        true occupant lineup declined to name -- the named-wrong-one the plan
        forbids.
        """
        partial = ["A", None, None, "D", "E"]
        got = assign_alive(cells("A", "D", "E"), partial, 3, GALLERY)
        self.assertEqual(got["agents"], [])
        self.assertTrue(got["reason"].startswith("roster_incomplete:3/5"))

    def test_zero_alive_refuses(self):
        self.assertEqual(assign_alive(cells(), ROSTER, 0, GALLERY)["reason"],
                         "no_alive")


class ShrinkEventTests(unittest.TestCase):
    def _series(self, *sets):
        return [{"t_ms": i * 1000,
                 "ally": {"alive": len(s), "agents": list(s),
                          "margin": 0.5, "reason": None}}
                for i, s in enumerate(sets)]

    def test_a_death_is_reported_with_the_agent_that_vanished(self):
        series = self._series(ROSTER, ["A", "B", "D", "E"])
        got = shrink_events(series, "ally")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["gone"], ["C"])
        self.assertTrue(got[0]["named"])

    def test_a_stable_set_produces_no_event(self):
        self.assertEqual(shrink_events(self._series(ROSTER, ROSTER), "ally"), [])

    def test_a_growing_set_is_not_a_death(self):
        """A round reset refills the bar; that is not five resurrections."""
        series = self._series(["A", "B"], ROSTER)
        self.assertEqual(shrink_events(series, "ally"), [])

    def test_two_deaths_at_once_report_both(self):
        series = self._series(ROSTER, ["A", "B", "C"])
        got = shrink_events(series, "ally")
        self.assertEqual(got[0]["gone"], ["D", "E"])

    def test_a_refused_frame_does_not_reset_the_previous_set(self):
        series = self._series(ROSTER)
        series.append({"t_ms": 5000, "ally": {"alive": None, "agents": [],
                                              "margin": None,
                                              "reason": "roster_incomplete:3/5"}})
        series += [{"t_ms": 6000, "ally": {"alive": 4,
                                           "agents": ["A", "B", "D", "E"],
                                           "margin": 0.5, "reason": None}}]
        got = shrink_events(series, "ally")
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["gone"], ["C"])


if __name__ == "__main__":
    unittest.main()
