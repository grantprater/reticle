"""Synthetic checks of prototypes/question_acceptance.py: the lane outcome
of each find and the named-slot questions.

No store is read; every input is built here.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import question_acceptance as qa  # noqa: E402
import real_reader_schedule as rrs  # noqa: E402
from reticle.agent_names import agent_key  # noqa: E402

#: Enemy subjects 5-9; Sova is subject 5, Jett 6.
FOE = {agent_key("Sova"): [5], agent_key("Jett"): [6], agent_key("KAY/O"): [7]}


class TrackOutcomeTests(unittest.TestCase):
    def test_an_unresolved_track_is_abstained_whatever_its_agent(self):
        for st in ("abstained", "disagreement", "contested", None):
            self.assertEqual(rrs.track_outcome("Sova", st, FOE), ("identity_abstained", -1))

    def test_a_name_off_the_enemy_team_is_dropped(self):
        self.assertEqual(rrs.track_outcome("Omen", "resolved", FOE), ("agent_not_on_enemy_team", -1))

    def test_an_enemy_name_maps_to_its_subject_by_agent_key(self):
        self.assertEqual(rrs.track_outcome("Sova", "resolved", FOE), ("named", 5))
        self.assertEqual(rrs.track_outcome("KAYO", "resolved", FOE), ("named", 7))

    def test_a_name_two_enemies_share_is_not_a_slot(self):
        self.assertEqual(rrs.track_outcome("Sova", "resolved", {agent_key("Sova"): [5, 6]}),
                         ("agent_not_on_enemy_team", -1))


    def test_a_refused_track_is_no_entity_whatever_its_name(self):
        self.assertEqual(rrs.track_outcome("Sova", "resolved", FOE, "refused"), ("reality_refused", -1))
        self.assertEqual(rrs.track_outcome("Sova", "resolved", FOE, "accepted"), ("named", 5))
        self.assertEqual(rrs.track_outcome("Sova", "resolved", FOE, "unassessed"), ("named", 5))
        self.assertIn("reality_refused", qa.DROPPED)


class PairedBootstrapTests(unittest.TestCase):
    def test_identical_arms_differ_by_zero_and_a_lift_in_every_round_excludes_zero(self):
        a = np.array([8.0, 9.0, 7.0, 10.0])
        b = np.array([10.0, 10.0, 10.0, 10.0])
        self.assertEqual(qa._boot_pooled_diff([(a, b, a, b)]), [0.0, 0.0])
        lo, hi = qa._boot_pooled_diff([(a + 1, b, a, b)])
        self.assertGreater(lo, 0.0)
        self.assertGreaterEqual(hi, lo)


class IconOutcomeTests(unittest.TestCase):
    # frame 0: a Sova track, a second Sova track, a Jett track;
    # frame 1: an abstained track, an off-team track, an icon with no track, a Sova track
    icon_p = np.array([0, 0, 0, 1, 1, 1, 1])
    icon_eid = np.array(["s1", "s2", "j1", "a1", "o1", None, "s1"], dtype=object)
    track_out = {"s1": "named", "s2": "named", "j1": "named",
                 "a1": "identity_abstained", "o1": "agent_not_on_enemy_team"}
    icon_subj = np.array([5, 5, 6, -1, -1, -1, 5])

    def test_each_find_sorts_into_one_outcome(self):
        got = qa.icon_outcomes(self.icon_p, self.icon_eid, self.icon_subj, self.track_out).tolist()
        self.assertEqual(got, ["named_duplicate", "named_duplicate", "named", "identity_abstained",
                               "agent_not_on_enemy_team", "no_track", "named"])

    def test_the_outcomes_of_any_subset_sum_to_its_size(self):
        got = qa.icon_outcomes(self.icon_p, self.icon_eid, self.icon_subj, self.track_out)
        fa = [0, 3, 4, 5, 6]
        counts = {o: int(np.sum(got[fa] == o)) for o in qa.OUTCOMES}
        self.assertEqual(sum(counts.values()), len(fa))
        self.assertEqual(counts["named_duplicate"], 1)
        self.assertEqual(sum(counts[o] for o in qa.DROPPED), 2)

    def test_one_track_twice_in_a_frame_is_a_duplicate_too(self):
        got = qa.icon_outcomes([0, 0], np.array(["s1", "s1"], dtype=object), [5, 5], {"s1": "named"})
        self.assertEqual(got.tolist(), ["named_duplicate", "named_duplicate"])


class LaneQuestionTests(unittest.TestCase):
    def test_presence_and_position_by_named_slot(self):
        # 10 subjects, 2 samples; enemy 5 at (0, 0), enemy 6 at (1000, 0) cm
        X = np.zeros((10, 2))
        Y = np.zeros((10, 2))
        X[6] = 1000.0
        drawn = np.zeros((10, 2), bool)
        alive = np.ones((10, 2), bool)
        drawn[[5, 6], 0] = True
        drawn[5, 1] = True
        p_of = np.array([0, 1])
        # icons: frame 0 -> one on enemy 5 named 5, one 500 cm from enemy 6 named 6;
        #        frame 1 -> one on enemy 5 named 6 (wrong slot), one unnamed
        icon_p = np.array([0, 0, 1, 1])
        icon_subj = np.array([5, 6, 6, -1])
        icon_x = np.array([0.0, 500.0, 0.0, 0.0])
        icon_y = np.zeros(4)
        ks = np.array([0, 0, 1, 1])
        ic = np.array([0, 1, 2, 3])
        pair_k = np.array([0, 0, 1])
        pair_j = np.array([5, 6, 5])
        Q = qa.lane_questions(ks, ic, pair_k, pair_j, icon_p, icon_subj, icon_x, icon_y,
                              X, Y, drawn, alive, p_of, near_cm=300.0)
        self.assertEqual(Q["pair_named"].tolist(), [True, True, False])
        self.assertEqual(Q["pair_named_pos"].tolist(), [True, False, False])
        self.assertEqual(Q["icon_named"].tolist(), [True, True, True, False])
        # icon 2 names enemy 6, who is not drawn at sample 1
        self.assertEqual(Q["icon_named_drawn"].tolist(), [True, True, False, False])
        self.assertEqual(Q["icon_named_pos"].tolist(), [True, False, False, False])
        self.assertAlmostEqual(Q["icon_err_cm"][1], 500.0)
        self.assertTrue(np.isnan(Q["icon_err_cm"][3]))


class PooledBootstrapTests(unittest.TestCase):
    def test_a_constant_share_has_a_point_interval(self):
        a = np.array([1.0, 2.0, 3.0])
        self.assertEqual(qa._boot_pooled([(a, 2 * a), (a, 2 * a)]), [0.5, 0.5])

    def test_a_count_interval_brackets_the_sum(self):
        a = np.array([0.0, 5.0, 1.0, 4.0])
        lo, hi = qa._boot_pooled([(a, None)])
        self.assertLessEqual(lo, 10)
        self.assertGreaterEqual(hi, 10)


class FrameSampleTests(unittest.TestCase):
    """Steps 5 to 8: a stream's frames join the grid one sample per frame."""

    G = np.arange(0.0, 1000.0, 62.5)

    def test_a_frame_takes_the_nearest_sample_within_half_a_step(self):
        k = qa.frame_samples(self.G, [70.0, 130.0, 2000.0], [True, True, True], 31.25)
        self.assertEqual(k.tolist(), [1, 2, -1])

    def test_an_unread_frame_joins_nothing(self):
        k = qa.frame_samples(self.G, [70.0], [False], 31.25)
        self.assertEqual(k.tolist(), [-1])

    def test_two_frames_on_one_sample_keep_the_nearer(self):
        k = qa.frame_samples(self.G, [60.0, 64.0, 70.0], [True, True, True], 31.25)
        self.assertEqual(k.tolist(), [-1, 1, -1])


class ClaimOutcomeTests(unittest.TestCase):
    """Steps 5 to 8: the outcome of a find that claims a kind and a name."""

    ally = {"kind": "player", "family": "player_ally", "key": "player_ally:Sage:-", "entity_class": "player"}
    orb = {"kind": "child", "family": "ability_ally", "key": "ability_ally:Sage:Barrier Orb",
           "entity_class": "Orb_C"}
    gap = {"kind": "child", "family": "unmapped", "key": "unmapped:X_C", "entity_class": "X_C",
           "unmapped_reason": "instigator chain ends at [1, 2]"}

    def test_the_claimed_kind_is_right_and_named_by_the_claim(self):
        self.assertEqual(qa.claim_outcome(self.ally, ambiguous=False, claimed=True, name_claim="sage",
                                          name_truth="sage"), ("right_entity", "right_entity:name_right"))
        self.assertEqual(qa.claim_outcome(self.ally, ambiguous=False, claimed=True, name_claim="omen",
                                          name_truth="sage"), ("right_entity", "right_entity:name_wrong"))
        self.assertEqual(qa.claim_outcome(self.ally, ambiguous=False, claimed=True),
                         ("right_entity", "right_entity:unnamed"))

    def test_an_undrawn_claimed_entity_is_undrawn_truth(self):
        self.assertEqual(qa.claim_outcome(self.ally, ambiguous=False, claimed=True, drawn=False)[0],
                         "undrawn_truth")

    def test_other_kinds_gaps_nothing_and_ambiguity(self):
        self.assertEqual(qa.claim_outcome(self.orb, ambiguous=False, claimed=False),
                         ("other_entity", "other_entity:ability_ally:Sage:Barrier Orb"))
        self.assertEqual(qa.claim_outcome(self.gap, ambiguous=False, claimed=False),
                         ("coverage_gap", "coverage_gap:X_C:instigator chain ends"))
        self.assertEqual(qa.claim_outcome(None, ambiguous=False, claimed=False, derivation="kill_x"),
                         ("nothing_there", "nothing_there:kill_x"))
        self.assertEqual(qa.claim_outcome(self.ally, ambiguous=True, claimed=True)[0], "ambiguous")


class MarkRecallTests(unittest.TestCase):
    def test_a_mark_counts_only_where_a_valid_sample_lies_in_its_window(self):
        marks = {"k_from": np.array([0, 5]), "k_to": np.array([2, 7]), "round": np.array([1, 1]),
                 "desc": [{"recall_key": "death_x_ally"}, {"recall_key": "death_x_ally"}]}
        valid = np.array([False, True, False, False, False, False, False, False])
        rec = qa._recall_marks(marks, valid, {0}, {1: 0}, 1)
        num, den = rec["death_x_ally"]
        self.assertEqual((num.tolist(), den.tolist()), ([1.0], [1.0]))


if __name__ == "__main__":
    unittest.main()
