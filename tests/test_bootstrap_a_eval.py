"""Unit tests for Bootstrap Lane A Independent Evaluator.

Tests 1-to-1 event matching mechanics, timing tolerances, null handling,
and duplicate-plus-miss cancellation detection on synthetic fixtures.
"""

import unittest
from tools.bootstrap_a_eval import (
    DeathEvent,
    EvaluationSpec,
    align_events,
)


class TestBootstrapAEval(unittest.TestCase):
    def setUp(self):
        self.spec = EvaluationSpec(dt_max_ms=2500.0)

    def test_exact_event_match(self):
        refs = [
            DeathEvent(
                death_id="d1", session_id="s1", round_no=1, t_ms=10000.0, side="ally",
                victim="Deadlock", killer="Killjoy", death_cause="gun", is_second_life=False,
            ),
            DeathEvent(
                death_id="d2", session_id="s1", round_no=1, t_ms=20000.0, side="enemy",
                victim="Jett", killer="Phoenix", death_cause="gun", is_second_life=False,
            ),
        ]
        cands = [
            DeathEvent(
                death_id="c1", session_id="s1", round_no=1, t_ms=10050.0, side="ally",
                victim="Deadlock", killer="Killjoy", death_cause="gun", is_second_life=False,
            ),
            DeathEvent(
                death_id="c2", session_id="s1", round_no=1, t_ms=19980.0, side="enemy",
                victim="Jett", killer="Phoenix", death_cause="gun", is_second_life=False,
            ),
        ]

        report = align_events(refs, cands, self.spec)
        self.assertEqual(report.n_matched, 2)
        self.assertEqual(report.n_missed, 0)
        self.assertEqual(report.n_extra, 0)
        self.assertEqual(report.precision, 1.0)
        self.assertEqual(report.recall, 1.0)
        self.assertTrue(report.count_match)
        self.assertFalse(report.duplicate_miss_cancellation)
        self.assertEqual(report.property_metrics["victim"]["accuracy"], 1.0)
        self.assertEqual(report.property_metrics["killer"]["accuracy"], 1.0)
        self.assertEqual(report.whole_event_correct, 2)

    def test_timing_bounds_tolerance(self):
        ref = DeathEvent(
            death_id="r1", session_id="s1", round_no=1, t_ms=10000.0, side="ally", victim="Reyna",
        )
        # Inside tolerance (dt = 2400 ms <= 2500 ms)
        cand_in = DeathEvent(
            death_id="c1", session_id="s1", round_no=1, t_ms=12400.0, side="ally", victim="Reyna",
        )
        report_in = align_events([ref], [cand_in], self.spec)
        self.assertEqual(report_in.n_matched, 1)

        # Outside tolerance (dt = 2600 ms > 2500 ms)
        cand_out = DeathEvent(
            death_id="c2", session_id="s1", round_no=1, t_ms=12600.0, side="ally", victim="Reyna",
        )
        report_out = align_events([ref], [cand_out], self.spec)
        self.assertEqual(report_out.n_matched, 0)
        self.assertEqual(report_out.n_missed, 1)
        self.assertEqual(report_out.n_extra, 1)

    def test_duplicate_plus_miss_cancellation(self):
        """Total counts match (3 == 3), but one event is missing and one is spurious."""
        refs = [
            DeathEvent("r1", "s1", 1, 10000.0, "ally", victim="Deadlock"),
            DeathEvent("r2", "s1", 1, 20000.0, "ally", victim="Reyna"),
            DeathEvent("r3", "s1", 1, 30000.0, "ally", victim="Miks"),
        ]
        cands = [
            DeathEvent("c1", "s1", 1, 10000.0, "ally", victim="Deadlock"),
            DeathEvent("c2", "s1", 1, 20000.0, "ally", victim="Reyna"),
            # Miks at 30s is missed; spurious event at 70s is added
            DeathEvent("c_extra", "s1", 1, 70000.0, "ally", victim="Breach"),
        ]

        report = align_events(refs, cands, self.spec)

        # Count match is True!
        self.assertTrue(report.count_match)
        # But cancellation is detected!
        self.assertTrue(report.duplicate_miss_cancellation)
        self.assertEqual(report.n_matched, 2)
        self.assertEqual(report.n_missed, 1)
        self.assertEqual(report.n_extra, 1)
        self.assertAlmostEqual(report.precision, 2 / 3)
        self.assertAlmostEqual(report.recall, 2 / 3)

    def test_null_and_abstained_properties(self):
        ref = DeathEvent(
            "r1", "s1", 1, 10000.0, "ally", victim="Jett", killer="Breach",
        )
        # Candidate matched in time, but victim was abstained (None)
        cand = DeathEvent(
            "c1", "s1", 1, 10100.0, "ally", victim=None, killer="Breach", status="abstained",
        )

        report = align_events([ref], [cand], self.spec)
        self.assertEqual(report.n_matched, 1)
        victim_metric = report.property_metrics["victim"]
        self.assertEqual(victim_metric["n_evaluable"], 1)
        self.assertEqual(victim_metric["n_correct"], 0)
        self.assertEqual(victim_metric["n_cand_null"], 1)
        self.assertEqual(victim_metric["n_conflict"], 0)
        self.assertEqual(victim_metric["accuracy"], 0.0)

        # Killer was predicted correctly
        killer_metric = report.property_metrics["killer"]
        self.assertEqual(killer_metric["accuracy"], 1.0)
        # Whole event is not correct because victim was abstained
        self.assertEqual(report.whole_event_correct, 0)

    def test_property_conflict(self):
        ref = DeathEvent("r1", "s1", 1, 10000.0, "ally", victim="Jett")
        cand = DeathEvent("c1", "s1", 1, 10000.0, "ally", victim="Iso")

        report = align_events([ref], [cand], self.spec)
        self.assertEqual(report.n_matched, 1)
        victim_metric = report.property_metrics["victim"]
        self.assertEqual(victim_metric["n_correct"], 0)
        self.assertEqual(victim_metric["n_conflict"], 1)
        self.assertEqual(victim_metric["accuracy"], 0.0)

    def test_greedy_closest_time_assignment(self):
        ref = DeathEvent("r1", "s1", 1, 10000.0, "ally", victim="Jett")
        cand_closer = DeathEvent("c1", "s1", 1, 10100.0, "ally", victim="Jett")
        cand_farther = DeathEvent("c2", "s1", 1, 10800.0, "ally", victim="Jett")

        report = align_events([ref], [cand_closer, cand_farther], self.spec)
        self.assertEqual(report.n_matched, 1)
        self.assertEqual(report.matched_pairs[0].candidate.death_id, "c1")
        self.assertEqual(report.n_extra, 1)
        self.assertEqual(report.extra_events[0].death_id, "c2")

    def test_partitioning_disjoint_rounds_and_sides(self):
        ref_round1 = DeathEvent("r1", "s1", 1, 10000.0, "ally", victim="Jett")
        cand_round2 = DeathEvent("c1", "s1", 2, 10000.0, "ally", victim="Jett")

        report = align_events([ref_round1], [cand_round2], self.spec)
        self.assertEqual(report.n_matched, 0)
        self.assertEqual(report.n_missed, 1)
        self.assertEqual(report.n_extra, 1)


if __name__ == "__main__":
    unittest.main()
