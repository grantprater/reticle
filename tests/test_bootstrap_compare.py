"""Adversarial checks for the bounded source comparison contract."""
import unittest

from tools.bootstrap_compare import _max_match, compare
from tools.bootstrap_b_replay import qualify_frozen_anchors


def event(key, t, victim="Jett", killer="Phoenix"):
    values = dict(death_id=key, session_id="s", round_no=1, side="enemy",
                  t_ms=t, victim=victim, killer=killer, death_cause="gun",
                  is_second_life=False)
    values["reasons"] = {p: "unread" for p in ("victim", "killer", "death_cause", "is_second_life") if values[p] is None}
    return values


def reference(key, t, **changes):
    row = event(key, t)
    row.update(changes)
    row["source_keys"] = ["frame:" + key]
    row["observability"] = {p: "observable" for p in
                            ("victim", "killer", "death_cause", "is_second_life")}
    return row


SPEC = {"scope": {"session_id": "s", "rounds": [1], "contiguous": True},
        "truth_provenance": {"kind": "stored_agreement", "reference_revision": "r1"},
        "matching_criteria": {"dt_max_ms": 2500}}


class BootstrapCompareTest(unittest.TestCase):
    def test_maximum_cardinality_precedes_nearest_pair(self):
        # Greedy chooses r2-c1 and misses r1. Exact matcher pairs both.
        refs = [reference("r1", 0), reference("r2", 2000)]
        cands = [event("c1", 1000), event("c2", 4000)]
        self.assertEqual(len(_max_match(refs, cands, 2500)), 2)

    def test_duplicate_and_miss_cancel_counts(self):
        report = compare([reference("r1", 0), reference("r2", 10000)],
                         [event("c1", 0), event("extra", 20000)], SPEC)
        self.assertTrue(report["count_cancellation"])
        self.assertEqual(report["missed"], ["r2"])
        self.assertEqual(report["extra"], ["extra"])

    def test_equal_time_association_is_flagged(self):
        report = compare([reference("r1", 0), reference("r2", 0)],
                         [event("c1", 0), event("c2", 0)], SPEC)
        self.assertEqual(report["matched"], 2)
        self.assertEqual(len(report["matching_ambiguities"]), 2)

    def test_refusal_conflict_and_unobservable_assertion(self):
        a = reference("r1", 0)
        b = reference("r2", 10000)
        b["observability"]["killer"] = "source_unobservable"
        b["killer"] = None
        b["reasons"]["killer"] = "source_hidden"
        report = compare([a, b], [event("c1", 0, victim=None, killer="Iso"),
                                  event("c2", 10000)], SPEC)
        self.assertEqual(report["properties"]["victim"]["unresolved"], 1)
        self.assertEqual(report["properties"]["killer"]["wrong"], 1)
        self.assertEqual(report["properties"]["killer"]["unsupported_assertion"], 1)

    def test_source_accuracy_needs_review_revision(self):
        spec = {**SPEC, "truth_provenance": {"kind": "source_review"}}
        with self.assertRaisesRegex(ValueError, "revision"):
            compare([reference("r", 0)], [event("c", 0)], spec)

    def test_unqualified_anchor_refused(self):
        with self.assertRaisesRegex(ValueError, "outside the teaching session"):
            qualify_frozen_anchors([{"observation_key": "other:1", "label_entity": "death:S:1:0"}])
        self.assertEqual(qualify_frozen_anchors([{"observation_key": "a06f04a0059f:1",
                                                "label_entity": "death:S:1:0"}])[0]["label_entity"],
                         "death:a06f04a0059f:1:0")


if __name__ == "__main__":
    unittest.main()
