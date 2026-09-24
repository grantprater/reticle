"""Synthetic evidence exercises proposal plumbing, not game truth."""
import copy
import tempfile
import unittest
from pathlib import Path

from reticle import domain_learning, revisions


def sample():
    return {
        "schema_version": 1,
        "hypothesis": {
            "hypothesis_id": "synthetic-rule", "revision": "h1", "claim": "Synthetic test claim",
            "kind": "rule", "subject": "synthetic:object", "scope": {"map": None},
            "proposed_by": "synthetic fixture", "proposed_at": "2026-01-02", "rule_id": "synthetic-rule",
            "prediction": "A source window shows the pattern", "falsifier": "A window lacks it",
            "evaluation_plan": "Review separate source windows", "status": "proposed",
            "evidence": [
                {"id": "source", "revision": "s1", "role": "supporting"},
                {"id": "derived", "revision": "d1", "role": "supporting"},
                {"id": "counter", "revision": "c1", "role": "contradicting"},
                {"id": "unknown", "revision": "u1", "role": "unresolved"},
            ],
        },
        "evidence": [
            {"id": "source", "revision": "s1", "current_revision": "s1", "kind": "observation",
             "observed_at": "2026-01-01T00:00:00Z", "analyzed_at": "2026-01-02T00:00:00Z",
             "source": {"session": "synthetic-a", "window_ms": [100, 200]},
             "instance": "i1", "round": "r1", "session": "synthetic-a",
             "dependencies": [], "rules_used": []},
            {"id": "intermediate", "revision": "m1", "current_revision": "m1", "kind": "verdict",
             "observed_at": "2026-01-01T00:00:00Z", "analyzed_at": "2026-01-02T00:00:00Z",
             "source": {"session": "synthetic-a", "window_ms": [100, 200]},
             "dependencies": [], "rules_used": ["synthetic-rule"]},
            {"id": "derived", "revision": "d1", "current_revision": "d1", "kind": "verdict",
             "observed_at": "2026-01-01T00:00:00Z", "analyzed_at": "2026-01-02T00:00:00Z",
             "source": {"session": "synthetic-a", "window_ms": [100, 200]},
             "dependencies": [{"id": "intermediate", "revision": "m1"}], "rules_used": []},
            *[{"id": key, "revision": rev, "current_revision": rev, "kind": "observation",
               "observed_at": "2026-01-01T00:00:00Z", "analyzed_at": "2026-01-02T00:00:00Z",
               "source": {"session": "synthetic-b", "window_ms": [300, 400]},
               "dependencies": [], "rules_used": []}
              for key, rev in (("counter", "c1"), ("unknown", "u1"))],
        ],
        "consumers": [
            {"id": "verdict", "revision": "v1", "depends_on": ["synthetic-rule"], "stored_inputs": True},
            {"id": "review", "revision": "r1", "depends_on": ["verdict"], "stored_inputs": False},
        ],
    }


class DomainLearningTests(unittest.TestCase):
    def test_transitive_rule_feedback_and_counterexamples(self):
        report = domain_learning.validate(sample())
        self.assertTrue(report["valid"])
        self.assertEqual(report["independent_support"], ["source"])
        self.assertEqual(report["dependent_support"], ["derived"])
        self.assertEqual(report["contradicting"], ["counter"])
        self.assertEqual(report["unresolved"], ["unknown"])
        self.assertEqual(report["support_units"], {"instance": 1, "round": 1, "session": 1})
        self.assertEqual([item["id"] for item in report["withdrawal_impact"]], ["review", "verdict"])

    def test_missing_stale_cycle_and_invalid_transition_refuse(self):
        doc = sample()
        doc["evidence"][0]["current_revision"] = "s2"
        doc["evidence"][2]["dependencies"].append({"id": "absent", "revision": "x"})
        doc["evidence"][1]["dependencies"].append({"id": "derived", "revision": "d1"})
        doc["hypothesis"]["status"] = "accepted"
        doc["transition"] = {"from": "proposed", "reviewer": "person", "decided_at": "2026-01-03", "reason": "review"}
        errors = "\n".join(domain_learning.validate(doc)["errors"])
        for term in ("stale revision", "missing dependency", "dependency cycle", "invalid transition"):
            self.assertIn(term, errors)

    def test_accepted_proposal_stays_derived_and_revision_is_immutable(self):
        doc = sample()
        doc["hypothesis"]["status"] = "under_review"
        doc["transition"] = {"from": "proposed", "reviewer": "person", "decided_at": "2026-01-03", "reason": "inspect"}
        self.assertTrue(domain_learning.validate(doc)["valid"])
        doc["hypothesis"]["status"] = "accepted"
        doc["transition"]["from"] = "under_review"
        report = domain_learning.validate(doc)
        self.assertTrue(report["valid"])
        self.assertEqual(report["promotion_proposal"]["known"], "inferred")
        with tempfile.TemporaryDirectory() as tmp:
            path, _ = domain_learning.publish(doc, Path(tmp))
            same, _ = domain_learning.publish(doc, Path(tmp))
            self.assertEqual(path, same)
            changed = copy.deepcopy(doc)
            changed["hypothesis"]["claim"] = "Corrected synthetic claim"
            with self.assertRaisesRegex(ValueError, "immutable hypothesis revision"):
                domain_learning.publish(changed, Path(tmp))
            changed["hypothesis"]["revision"] = "h2"
            newer, _ = domain_learning.publish(changed, Path(tmp))
            self.assertNotEqual(path, newer)
            self.assertEqual(revisions.current_revision(tmp), newer)
            self.assertIn("Synthetic test claim", (path / "review.md").read_text())


if __name__ == "__main__":
    unittest.main()
