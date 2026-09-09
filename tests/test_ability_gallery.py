import unittest

import numpy as np

from reticle.adjudication.gallery import (balanced_accuracy, eligible_contrasts,
                                          nearest_centroid, permutation_ceiling,
                                          permutation_p, shared_features,
                                          trace_features)


def example(cid, sid, ability, **scalar):
    return {"component_id": cid, "session_id": sid, "ability_id": ability,
            "agent": ability.split(":")[0], "origin": "detector_candidate",
            "scalar": scalar, "trace": {}, "relative": {},
            "appearance_bright": {}, "appearance_dim": {},
            "has_trace": False}


class ContrastEligibilityTests(unittest.TestCase):
    """The two rules that stop a session artefact being read as recognition."""

    def test_both_classes_must_share_the_test_session(self):
        rows = ([example(f"a{i}", "s1", "deadlock:sonic sensor") for i in range(4)]
                + [example(f"b{i}", "s2", "deadlock:barrier mesh") for i in range(4)])
        contrasts, excluded = eligible_contrasts(rows)
        self.assertEqual(contrasts, [])
        self.assertEqual({e["reason"] for e in excluded},
                         {"fewer_than_two_classes_in_one_session"})

    def test_a_class_seen_in_one_session_only_is_not_scored(self):
        rows = ([example(f"a{i}", "s1", "cypher:trapwire") for i in range(4)]
                + [example(f"b{i}", "s1", "cypher:spycam") for i in range(4)]
                + [example(f"c{i}", "s2", "cypher:trapwire") for i in range(4)])
        contrasts, excluded = eligible_contrasts(rows)
        self.assertEqual(contrasts, [])
        self.assertEqual(excluded[0]["reason"], "class_occurs_in_no_other_session")
        self.assertEqual(excluded[0]["untrainable"], ["cypher:spycam"])

    def test_a_contrast_with_both_classes_in_both_sessions_is_scored(self):
        rows = []
        for sid in ("s1", "s2"):
            rows += [example(f"a{sid}{i}", sid, "deadlock:sonic sensor") for i in range(3)]
            rows += [example(f"b{sid}{i}", sid, "deadlock:barrier mesh") for i in range(3)]
        contrasts, _ = eligible_contrasts(rows)
        self.assertEqual(len(contrasts), 2)
        for contrast in contrasts:
            self.assertNotIn(contrast["test_session"], contrast["train_sessions"])


class ScoringTests(unittest.TestCase):
    def test_balanced_accuracy_does_not_reward_the_majority_prior(self):
        truth = ["a"] * 9 + ["b"]
        self.assertEqual(balanced_accuracy(truth, ["a"] * 10), 0.5)

    def test_a_feature_missing_from_any_example_is_not_imputed(self):
        rows = [example("a", "s1", "x", area=1.0, aspect=2.0),
                example("b", "s1", "y", area=3.0)]
        self.assertEqual(shared_features(rows, ("scalar",)), ["scalar.area"])

    def test_classification_is_refused_when_no_feature_is_shared(self):
        train = [example("a", "s1", "x", area=1.0), example("b", "s1", "y", aspect=2.0)]
        test = [example("c", "s2", "x", area=1.0)]
        self.assertIsNone(nearest_centroid(train, test, ("scalar",)))

    def test_separable_classes_are_recovered_from_a_held_out_session(self):
        train = ([example(f"a{i}", "s1", "x", area=1.0 + i * 0.1) for i in range(4)]
                 + [example(f"b{i}", "s1", "y", area=9.0 + i * 0.1) for i in range(4)])
        test = [example("t1", "s2", "x", area=1.05), example("t2", "s2", "y", area=9.05)]
        got = nearest_centroid(train, test, ("scalar",))
        self.assertEqual(got, ["x", "y"])

    def test_trace_features_separate_relative_time_from_appearance(self):
        series = {
            "t_ms": np.array([0., 100., 200., 300.]),
            "index": {(1, 2, 100.0): 0},
            "arrays": {"g_mean": np.array([[10., 20., 80., 100.]])},
        }
        component = {"x": 1, "y": 2, "observed_t_ms": 100.0}
        appearance = {"appearance_segments": [
            {"appearance": "dim", "status": "stable_appearance",
             "from_ms": 0., "to_ms": 100.},
            {"appearance": "bright", "status": "stable_appearance",
             "from_ms": 200., "to_ms": 300.},
        ]}
        got = trace_features(series, component, appearance)
        self.assertEqual(got["appearance_dim.g_mean.median"], 15.0)
        self.assertEqual(got["appearance_bright.g_mean.median"], 90.0)
        self.assertTrue(any(key.startswith("relative_") for key in got))
        self.assertFalse(any(key.startswith("pre.") for key in got))

    def test_combined_evidence_does_not_treat_one_present_block_as_both(self):
        row = example("a", "s1", "x", area=1.0)
        row["relative"] = {"f": 1.0}
        self.assertTrue(row["relative"])
        self.assertFalse(all(row[block] for block in ("appearance_dim", "relative")))


class PermutationControlTests(unittest.TestCase):
    """A score only counts if shuffled training labels cannot reach it."""

    def split(self, separable):
        train = ([example(f"a{i}", "s1", "x", area=1.0 + i * 0.1) for i in range(6)]
                 + [example(f"b{i}", "s1", "y", area=(9.0 if separable else 1.3) + i * 0.1)
                    for i in range(6)])
        test = ([example(f"t{i}", "s2", "x", area=1.05 + i * 0.1) for i in range(5)]
                + [example(f"u{i}", "s2", "y", area=(9.05 if separable else 1.35) + i * 0.1)
                   for i in range(5)])
        return train, test, [e["ability_id"] for e in test]

    def test_a_perfect_score_on_two_classes_is_not_automatically_significant(self):
        """The degeneracy the p-value exists for: shuffled labels reach 1.0
        whenever the two collapsed centroids fall in the right order."""
        train, test, truth = self.split(separable=True)
        observed = balanced_accuracy(truth, nearest_centroid(train, test, ("scalar",)))
        chance = permutation_ceiling(train, test, truth, ("scalar",))
        self.assertEqual(observed, 1.0)
        self.assertEqual(chance["max"], 1.0)
        self.assertGreater(permutation_p(observed, chance), 0.05)

    def test_the_p_value_counts_shuffles_that_match_the_observed_score(self):
        control = {"permutations": 3, "median": 0.5, "max": 0.9,
                   "scores": [0.4, 0.5, 0.9]}
        self.assertEqual(permutation_p(0.95, control), round(1 / 4, 4))
        self.assertEqual(permutation_p(0.9, control), round(2 / 4, 4))
        self.assertIsNone(permutation_p(0.9, None))


if __name__ == "__main__":
    unittest.main()
