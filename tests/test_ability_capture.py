import json
import tempfile
import unittest
from pathlib import Path

from reticle.adjudication.capture import (build_queue, record_take, takes_path,
                                          verify_takes)


def coverage_row(ability_id, group, status="not_exercised", demos=("demo1",)):
    agent, ability = ability_id.split(":")
    return {"ability_id": ability_id, "agent": agent.title(), "ability": ability.title(),
            "property_group": group, "status": status,
            "status_reason": "no_property_specific_evidence",
            "demo_session_ids": list(demos), "source_window_ids": [],
            "remaining_alternatives": ["property_not_observed"], "capture_request_id": None}


GROUPS = ("identity", "causality", "time", "geometry", "motion",
          "function", "state", "resources", "durability", "observation")


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("analysis/ability-coverage", "analysis/ability-gallery",
                     "analysis/ability-entities", "manifests", "notes"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        self.write("analysis/ability-coverage/coverage.jsonl",
                   [coverage_row("viper:pit", g) for g in GROUPS]
                   + [coverage_row("astra:star", g, demos=()) for g in GROUPS])
        self.write("analysis/ability-gallery/coverage.jsonl", [
            {"ability_id": "viper:pit", "named": 5, "with_trace": 5,
             "sessions": ["demo1"], "held_out_evaluable": False}])
        self.write("analysis/ability-entities/review.jsonl", [])
        self.write("analysis/ability-gallery/parameters.jsonl", [])

    def tearDown(self):
        self.temp.cleanup()

    def write(self, name, rows):
        (self.root / name).write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    def test_an_ability_never_observed_gets_no_card(self):
        bundle = build_queue(self.root)
        self.assertNotIn("astra:star", {c["ability_id"] for c in bundle["cards"]})
        self.assertTrue(any(r["ability_id"] == "astra:star"
                            for r in bundle["not_requested"]))

    def test_every_card_names_a_discriminator_and_an_action(self):
        bundle = build_queue(self.root)
        self.assertTrue(bundle["cards"])
        for card in bundle["cards"]:
            for field in ("named_missing_discriminator", "surviving_alternatives",
                          "why_existing_sources_fail", "separating_action",
                          "success_condition"):
                self.assertTrue(card[field], f"{card['capture_request_id']} lacks {field}")
            self.assertGreaterEqual(len(card["surviving_alternatives"]), 2)

    def test_review_items_request_no_recorded_seconds(self):
        bundle = build_queue(self.root)
        self.assertTrue(bundle["review"])
        self.assertEqual({r["recorded_s"] for r in bundle["review"]}, {0.0})

    def test_a_dispute_on_existing_footage_is_deferred_to_review(self):
        self.write("analysis/ability-entities/review.jsonl", [
            {"ability_id": "viper:pit", "component_ids": ["c1", "c2"]}])
        bundle = build_queue(self.root)
        deferred = [d for d in bundle["deferred"] if d.get("ability_id") == "viper:pit"]
        self.assertTrue(deferred)
        self.assertEqual(deferred[0]["status"], "deferred_to_review")
        self.assertNotIn("capture:grouping:viper:pit",
                         {c["capture_request_id"] for c in bundle["cards"]})


class TakeVerificationTests(unittest.TestCase):
    """A take is never allowed to certify itself."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "manifests").mkdir(parents=True, exist_ok=True)
        (self.root / "notes").mkdir(parents=True, exist_ok=True)
        (self.root / "manifests/newsess.json").write_text("{}", encoding="utf-8")
        self.cards = [{"capture_request_id": "capture:transfer:viper:pit",
                       "ability_id": "viper:pit"}]

    def tearDown(self):
        self.temp.cleanup()

    def gallery(self, sessions, evaluable):
        return [{"ability_id": "viper:pit", "named": 5, "sessions": sessions,
                 "held_out_evaluable": evaluable}]

    def test_a_claimed_success_with_no_evidence_stays_unverified(self):
        record_take(self.root, "t1", "newsess",
                    [{"capture_request_id": "capture:transfer:viper:pit",
                      "claimed_status": "success", "actual_action": "cast once"}])
        got = verify_takes(self.root, self.cards, self.gallery(["demo1"], False))
        self.assertEqual(got[0]["verdict"], "unverified")

    def test_a_labelled_use_that_still_cannot_be_held_out_is_partial(self):
        record_take(self.root, "t1", "newsess",
                    [{"capture_request_id": "capture:transfer:viper:pit",
                      "claimed_status": "success"}])
        got = verify_takes(self.root, self.cards,
                           self.gallery(["demo1", "newsess"], False))
        self.assertEqual(got[0]["verdict"], "partial")

    def test_evidence_the_take_could_not_assert_verifies_it(self):
        record_take(self.root, "t1", "newsess",
                    [{"capture_request_id": "capture:transfer:viper:pit",
                      "claimed_status": "success"}])
        got = verify_takes(self.root, self.cards,
                           self.gallery(["demo1", "newsess"], True))
        self.assertEqual(got[0]["verdict"], "verified")

    def test_a_failed_card_is_retained_beside_its_successful_siblings(self):
        record_take(self.root, "t1", "newsess", [
            {"capture_request_id": "capture:transfer:viper:pit", "claimed_status": "success"},
            {"capture_request_id": "capture:transfer:other:thing",
             "claimed_status": "failed", "failure_reason": "cue overlapped the next cast"}])
        got = verify_takes(self.root, self.cards, self.gallery(["demo1", "newsess"], True))
        self.assertEqual(len(got), 2)
        failed = next(v for v in got if v["verdict"] == "retained_failure")
        self.assertEqual(failed["failure_reason"], "cue overlapped the next cast")

    def test_takes_are_appended_not_overwritten(self):
        record_take(self.root, "t1", "s1", [{"capture_request_id": "a",
                                             "claimed_status": "failed"}])
        record_take(self.root, "t2", "s2", [{"capture_request_id": "a",
                                             "claimed_status": "failed"}])
        lines = takes_path(self.root).read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)

    def test_an_unknown_claimed_status_is_refused(self):
        with self.assertRaises(ValueError):
            record_take(self.root, "t1", "s1",
                        [{"capture_request_id": "a", "claimed_status": "probably fine"}])


if __name__ == "__main__":
    unittest.main()
