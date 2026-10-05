"""Synthetic checks of prototypes/ability_xchannel.py: candidate cells,
one-to-one pairing, the miss table and its tests, the Mantel-Haenszel odds
ratio, the count score and precision estimate, the dev rule choice, the
union and agree rules, strata and opportunities. No store is read; every
input is built here.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import ability_xchannel as ax  # noqa: E402

PLAYERS = [
    {"subject": "me", "agent": "Sova", "side": "self"},
    {"subject": "a1", "agent": "Clove", "side": "ally"},
    {"subject": "e1", "agent": "Clove", "side": "enemy"},
    {"subject": "e2", "agent": "Raze", "side": "enemy"},
]


class Cells(unittest.TestCase):
    def test_one_side_names_one_cell(self):
        w = {"side": "enemy", "agent": "Raze", "slot": "Ultimate"}
        self.assertEqual(ax.candidate_cells(w, PLAYERS), [("e2", "Ultimate")])

    def test_mirror_names_both_players(self):
        w = {"side": "both", "agent": "Clove", "slot": "Ability2"}
        self.assertEqual(sorted(ax.candidate_cells(w, PLAYERS)),
                         [("a1", "Ability2"), ("e1", "Ability2")])

    def test_ally_of_players_agent_is_the_player(self):
        w = {"side": "ally", "agent": "Sova", "slot": "Ability1"}
        self.assertEqual(ax.candidate_cells(w, PLAYERS), [("me", "Ability1")])

    def test_phase_group_names_each_slot(self):
        w = {"side": "self", "agent": "Sova", "slot": None, "slots": ["Ability1", "Ability2"]}
        self.assertEqual(ax.candidate_cells(w, PLAYERS), [("me", "Ability1"), ("me", "Ability2")])

    def test_unknown_side_or_slot_names_nothing(self):
        self.assertEqual(ax.candidate_cells({"side": None, "agent": "Raze", "slot": "Ultimate"},
                                            PLAYERS), [])
        self.assertEqual(ax.candidate_cells({"side": "enemy", "agent": "Raze", "slot": "Melee"},
                                            PLAYERS), [])
        self.assertEqual(ax.candidate_cells({"side": "ally", "agent": "Raze", "slot": "Ultimate"},
                                            PLAYERS), [])


class Pairing(unittest.TestCase):
    def test_window_cells_and_one_to_one(self):
        c = ("e2", "Ultimate")
        wit = [(10.0, {c}), (10.5, {c}), (30.0, {("e1", "Grenade")}), (50.0, {c})]
        casts = [(9.6, c), (29.5, c), (45.0, c)]
        prs = ax.pair_witnesses(wit, casts, pre=1.0, post=3.0)
        got = {(i, j) for i, j, _ in prs}
        # 10.0 is nearest to 9.6; 10.5 finds no free cast; 30.0 names the
        # wrong cell; 50.0 lies 5 s after 45.0, outside the window
        self.assertEqual(got, {(0, 0)})
        self.assertAlmostEqual(prs[0][2], 0.4)

    def test_effect_window_takes_latest_prior_cast(self):
        c = ("e2", "Ultimate")
        prs = ax.pair_witnesses([(100.0, {c})], [(40.0, c), (70.0, c), (100.5, c)],
                                pre=ax.EFFECT_AFTER_S, post=ax.EFFECT_LOOKBACK_S)
        # 100.5 is 0.5 s after the effect, inside EFFECT_AFTER_S, and nearest
        self.assertEqual([(i, j) for i, j, _ in prs], [(0, 2)])
        prs = ax.pair_witnesses([(100.0, {c})], [(40.0, c), (70.0, c)],
                                pre=ax.EFFECT_AFTER_S, post=ax.EFFECT_LOOKBACK_S)
        self.assertEqual([(i, j) for i, j, _ in prs], [(0, 1)])


class Independence(unittest.TestCase):
    def test_miss_table_counts_and_conditionals(self):
        a = [1, 1, 1, 0, 0, 0, 1, 0]
        b = [1, 1, 0, 0, 0, 1, 1, 0]
        m = ax.miss_table(a, b)
        self.assertEqual(m["table"], [[3, 1], [1, 3]])
        self.assertEqual(m["n"], 8)
        self.assertAlmostEqual(m["p_miss_a"], 0.5)
        self.assertAlmostEqual(m["p_miss_a_given_miss_b"], 0.75)
        self.assertAlmostEqual(m["p_miss_a_given_hit_b"], 0.25)
        self.assertAlmostEqual(m["odds_ratio"], 9.0)
        self.assertGreater(m["fisher_p"], 0.05)

    def test_strong_association_is_correlated(self):
        a = [1] * 20 + [0] * 20
        b = [1] * 18 + [0] * 2 + [1] * 2 + [0] * 18
        m = ax.miss_table(a, b)
        self.assertLess(m["fisher_p"], 0.001)
        self.assertTrue(ax.correlated(m))
        # the reverse association is not a correlated ERROR
        m2 = ax.miss_table(a, [1 - x for x in b])
        self.assertLess(m2["fisher_p"], 0.001)
        self.assertFalse(ax.correlated(m2))

    def test_empty_margin_has_no_test(self):
        m = ax.miss_table([1, 1, 0], [1, 1, 1])
        self.assertIsNone(m["fisher_p"])
        self.assertIsNone(m["p_miss_a_given_hit_b"])
        self.assertFalse(ax.correlated(m))

    def test_mh_odds_ratio(self):
        # two identical strata with OR 9 pool to 9; a zero denominator is None
        self.assertAlmostEqual(ax.mh_odds_ratio([[[3, 1], [1, 3]], [[3, 1], [1, 3]]]), 9.0)
        self.assertIsNone(ax.mh_odds_ratio([[[3, 0], [0, 3]]]))

    def test_strata_and_opportunity(self):
        self.assertEqual(ax.stratum_of(5.0), "0-20m")
        self.assertEqual(ax.stratum_of(20.0), "20-40m")
        self.assertEqual(ax.stratum_of(55.0), "40m+")
        self.assertEqual(ax.stratum_of(None), "unknown")
        self.assertEqual(ax.stratum_of(float("nan")), "unknown")
        casts = [{"agent": "Raze", "slot": "Ultimate", "side": "enemy", "hits": {}},
                 {"agent": "Raze", "slot": "Ultimate", "side": "self", "hits": {}},
                 {"agent": "Raze", "slot": "Grenade", "side": "enemy", "hits": {}}]
        vocab = {"killfeed": {("raze", "Ultimate"), ("raze", "Grenade")},
                 "ult_cast": {("raze", "Ultimate")}}
        self.assertEqual(len(ax.opportunity("ult_cast", casts, vocab, set())), 1)
        # the killfeed's opportunities are only the casts that killed
        self.assertEqual(ax.opportunity("killfeed", casts, vocab, {id(casts[2])}), [casts[2]])

    def test_independence_over_shared_opportunities(self):
        rng = np.random.default_rng(1)
        casts = []
        for i in range(60):
            far = i % 2 == 0
            hits = {}
            # both channels miss the far casts: a shared cause
            if not far:
                hits = {"audio_others": 0.1, "ult_cast": 0.0}
            elif rng.random() < 0.1:
                hits = {"ult_cast": 0.0}
            casts.append({"agent": "Raze", "slot": "Ultimate", "side": "enemy", "hits": hits,
                          "dist_m": 60.0 if far else 10.0, "los": None, "live": True})
        vocab = {"audio_others": {("raze", "Ultimate")}, "ult_cast": {("raze", "Ultimate")}}
        out = ax.independence(casts, vocab, set(), {"audio_others", "ult_cast"})
        row = out["audio_others~ult_cast"]
        self.assertEqual(row["n"], 60)
        self.assertTrue(row["correlated"])
        self.assertIn("dist:0-20m", row["strata"])


class Combination(unittest.TestCase):
    def test_count_score_and_precision(self):
        s = ax.count_score([(3, 2), (1, 4), (0, 1)])
        self.assertEqual((s["witnessed"], s["riot"], s["covered"]), (4, 7, 3))
        self.assertAlmostEqual(s["precision_bound"], 0.75)
        self.assertAlmostEqual(ax.precision_estimate(s, 2.0), 0.5)
        self.assertAlmostEqual(ax.precision_estimate(s, 0.0), 0.75)
        self.assertIsNone(ax.precision_estimate(ax.count_score([(0, 3)]), 0.0))

    def test_choose_rule(self):
        dev = {"audio_others": {"covered": 50, "precision": 0.4},
               "ult_cast": {"covered": 10, "precision": 0.95},
               "hi_union": {"covered": 12, "precision": 0.9},
               "union": {"covered": 55, "precision": 0.5}}
        self.assertEqual(ax.choose_rule(dev), "hi_union")
        low = {"audio_others": {"covered": 50, "precision": 0.4},
               "union": {"covered": 55, "precision": 0.5}}
        self.assertEqual(ax.choose_rule(low), "union")
        self.assertIsNone(ax.choose_rule({"x": {"covered": 0, "precision": None}}))

    def test_per_round_max(self):
        self.assertEqual(ax.per_round_max([(1, "a"), (1, "a"), (1, "b"), (2, "b"), (None, "a")]), 4)

    def test_agree_keep(self):
        other = [(100.0, "ult_cast"), (200.0, "killfeed")]
        keep = ax.agree_keep([98.0, 104.0, 150.0, 260.5, 201.0], other)
        # 98 and 104 lie within 3 s and 4 s of the ult line; 150 has the
        # kill 50 s later; 260.5 has none; 201 lies after the kill
        self.assertEqual(keep, [True, False, True, False, False])
        # an effect in another round does not agree
        keep = ax.agree_keep([150.0, 150.0], [(200.0, "killfeed", 3)], [2, 3])
        self.assertEqual(keep, [False, True])
        self.assertEqual(ax.agree_keep([1.0], []), [False])

    def test_rule_count(self):
        ws = [(10_000.0, "audio_others", 1), (11_000.0, "ult_cast", 1),
              (50_000.0, "audio_others", 2), (90_000.0, "audio_others", 3),
              (95_000.0, "killfeed", 3)]
        self.assertEqual(ax.rule_count("union", ws)[0], 3)
        self.assertEqual(ax.rule_count("today", ws), (2, 0))
        self.assertEqual(ax.rule_count("audio_others", ws)[0], 3)
        n, na = ax.rule_count("agree", ws)
        # rounds 1 and 3 have an agreeing witness; round 2's lone detection drops
        self.assertEqual(n, 2)
        self.assertEqual(ax.rule_count("hi_union", ws, {"ult_cast"}), (1, 0))

    def test_gain_totals_range(self):
        row = {"choice": "union",
               "held": {"today": {"by_side": {"enemy": {"riot": 10, "covered": 1, "witnessed": 1}}},
                        "union": {"witnessed": 8, "expected_false_audio": 4.0,
                                  "by_side": {"enemy": {"riot": 10, "covered": 6, "witnessed": 8}}}}}
        g = ax.gain_totals([row], "held")["enemy"]
        self.assertEqual(g["gained"], 5)
        self.assertAlmostEqual(g["net_unclipped"], 1.0)
        self.assertAlmostEqual(g["net_prop"], 2.5)
        # a class without a choice keeps today's count
        row2 = {"choice": None, "held": row["held"]}
        self.assertEqual(ax.gain_totals([row2], "held")["enemy"]["gained"], 0)


if __name__ == "__main__":
    unittest.main()
