"""Synthetic checks of prototypes/audio_others.py: split, detections, the
null threshold, pairing, side tokens and votes, and the peak scan over an
injected template. No store is read; every input is built here.
"""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import audio_others as ao  # noqa: E402


class Rules(unittest.TestCase):
    def test_dev_half_is_fixed_and_splits(self):
        sids = [f"{i:012x}" for i in range(200)]
        dev = [ao.dev_half(s) for s in sids]
        self.assertEqual(dev, [ao.dev_half(s) for s in sids])
        self.assertTrue(60 < sum(dev) < 140)

    def test_side_token(self):
        self.assertEqual(ao.side_token("Veto/Q/X_Interceptor_Ally_3P (SFX).flac"), "ally")
        self.assertEqual(ao.side_token("Gekko/E/Zamboni_Enemy_Splat (SFX).flac"), "enemy")
        self.assertIsNone(ao.side_token("Sova/E/Hunter_AbilQ_Cast (SFX).flac"))
        self.assertIsNone(ao.side_token("x/Ally_vs_Enemy.flac"))

    def test_canon(self):
        self.assertEqual(ao.canon("KAY/O"), ao.canon("KAY_O"))

    def test_detections_merge_at_first_peak(self):
        f = np.array([100, 150, 400, 900, 950, 2000])
        v = np.array([2.0, 3.0, 0.4, 2.0, 2.0, 1.0])
        d = ao.detections(f, v, 1.0, merge_frames=300)
        # 100 and 150 merge (gap 50); 400 below threshold; 900/950 merge; 2000 alone
        np.testing.assert_array_equal(d, [100, 900, 2000])
        idx = ao.detection_index(f, v, 1.0, merge_frames=300)
        np.testing.assert_array_equal(f[idx], d)
        self.assertEqual(len(ao.detections(f, v, 5.0, 300)), 0)

    def test_threshold_for_meets_budget(self):
        rng = np.random.default_rng(0)
        null = [(np.arange(0, 60000, 100), rng.uniform(0.5, 3.0, 600)) for _ in range(2)]
        live_min = 20.0
        thr = ao.threshold_for(null, live_min, ff_per_min=0.5, merge_frames=1)
        n = sum(len(ao.detections(f, v, thr, 1)) for f, v in null)
        self.assertLessEqual(n, 0.5 * live_min)
        lower = thr - ao.GRID_STEP
        n2 = sum(len(ao.detections(f, v, lower, 1)) for f, v in null)
        self.assertGreater(n2, 0.5 * live_min)
        self.assertIsNone(ao.threshold_for(null, 0.0))

    def test_pair_window_and_one_to_one(self):
        det = [10.0, 10.5, 30.0, 50.0]
        tru = [9.6, 29.5, 45.0, 52.0]
        prs = ao.pair(det, tru, pre=1.0, post=3.0)
        got = {(i, j) for i, j, _ in prs}
        # 10.0 and 10.5 both near 9.6; only the nearer pairs; 50.0 is 5 s
        # after 45.0 (outside) and 2 s before 52.0 (outside the 1 s pre)
        self.assertEqual(got, {(0, 0), (2, 1)})
        self.assertEqual(ao.pair([], tru), [])

    def test_distance_bin_and_vote(self):
        np.testing.assert_array_equal(ao.distance_bin([0.0, 9.9, 10.0, 35.0]), [0, 0, 10, 30])
        v = ao.side_vote([1.0, 0.2, np.nan, 1.0], [0.5, 0.9, 1.0, 1.0])
        self.assertEqual(list(v), ["ally", "enemy", None, None])

    def test_class_keys(self):
        self.assertEqual(ao.class_keys("Q+E", {"Q+E": ["Q", "E"]}), ["Q", "E"])
        self.assertEqual(ao.class_keys("C", {"Q+E": ["Q", "E"]}), ["C"])

    def test_bank_labels_side_tracks_only_with_both(self):
        bank = {"rows": [{"class": "Q", "side": "ally"}, {"class": "Q", "side": "enemy"},
                         {"class": "Q", "side": None}, {"class": "E", "side": "ally"}]}
        labels, extra = ao.bank_labels(bank)
        self.assertEqual(labels, ["Q", "Q", "Q", "E"])
        self.assertEqual(extra, {"Q|ally": [0], "Q|enemy": [1]})

    def test_net_gain_is_a_range_and_never_clips(self):
        self.assertEqual(ao.net_gain(10, 4.0, 20), (6.0, 8.0))
        # more false alarms expected than gained: both go negative, not zero
        u, p = ao.net_gain(2, 5.0, 4)
        self.assertEqual(u, -3.0)
        self.assertAlmostEqual(p, -0.5)
        self.assertEqual(ao.net_gain(0, 3.0, 0), (-3.0, 0.0))

    def test_side_summary_pools_balanced_classes_apart(self):
        votes = {("K", "Q", "ally", "enemy"): 9, ("K", "Q", "ally", "ally"): 1,
                 ("S", "E", "ally", "ally"): 3, ("S", "E", "enemy", "ally"): 1,
                 ("S", "E", "enemy", None): 5}
        counts = {("K", "Q"): {"ally": 1, "enemy": 7}, ("S", "E"): {"ally": 1, "enemy": 1}}
        s = ao.side_summary(votes, counts)
        self.assertEqual(s["all"], {"agree": 4, "voted": 14, "share": round(4 / 14, 4)})
        self.assertEqual(s["balanced"], {"agree": 3, "voted": 4, "share": 0.75})
        self.assertEqual(s["unbalanced"]["voted"], 10)
        self.assertFalse(s["per_class"]["K|Q"]["balanced"])
        self.assertEqual(ao.side_summary({}, {})["balanced"]["share"], None)

    def test_rank_classes_by_precision_then_recall(self):
        per = {"A|Q": {"detections": 10, "paired": 5, "truth_live_others": 4, "paired_live_others": 1},
               "B|E": {"detections": 4, "paired": 2, "truth_live_others": 2, "paired_live_others": 2},
               "C|C": {"detections": 2, "paired": 2, "truth_live_others": 0, "paired_live_others": 0},
               "D|X": {"detections": 0, "paired": 0, "truth_live_others": 3, "paired_live_others": 0}}
        r = ao.rank_classes(per, {"A|Q": 0.5})
        self.assertEqual([x["class"] for x in r], ["C|C", "B|E", "A|Q", "D|X"])
        self.assertIsNone(r[0]["recall"])
        self.assertAlmostEqual(r[1]["f1"], 2 * 0.5 * 1.0 / 1.5)
        self.assertEqual(r[2]["weapon_share"], 0.5)
        self.assertIsNone(r[3]["precision"])

    def test_dropped_side_pairs_take_their_folders_class(self):
        bank = {"manifest_agent": "Cypher",
                "rows": [{"flac": "Cypher/E/Tripwire_1.flac", "class": "C"},
                         {"flac": "Cypher/Q/Camera_1.flac", "class": "E"},
                         {"flac": "Cypher/Q/Camera_2.flac", "class": "E"},
                         {"flac": "Cypher/Q/place.flac", "class": "C"}]}
        man = [{"agent": "Cypher", "flac": "Cypher/E/abile_ally_loop.flac"},
               {"agent": "Cypher", "flac": "Cypher/E/abile_enemy_loop.flac"},
               {"agent": "Cypher", "flac": "Cypher/Q/Possess_3P_Ally.flac"},
               {"agent": "Cypher", "flac": "Cypher/Q/Possess_3P_Enemy.flac"},
               {"agent": "Cypher", "flac": "Cypher/X/only_Enemy.flac"},
               {"agent": "Sova", "flac": "Sova/E/x_Ally.flac"},
               {"agent": "Cypher", "flac": "Cypher/E/Tripwire_1.flac"}]
        got = ao.dropped_side_pairs(bank, man)
        self.assertEqual(got, {"C": {"ally": ["Cypher/E/abile_ally_loop.flac"],
                                     "enemy": ["Cypher/E/abile_enemy_loop.flac"]},
                               "E": {"ally": ["Cypher/Q/Possess_3P_Ally.flac"],
                                     "enemy": ["Cypher/Q/Possess_3P_Enemy.flac"]}})


class Scan(unittest.TestCase):
    def test_injected_sound_is_a_peak_of_its_class_only(self):
        from reticle.adjudication import ability_audio as aa
        rng = np.random.default_rng(1)
        nb = int(aa.BMASK.sum())
        n = 6000
        X = rng.normal(0, 1, (n, nb)).astype(np.float32)
        A = rng.normal(0, 1, (40, nb)).astype(np.float32)
        B = rng.normal(0, 1, (40, nb)).astype(np.float32)
        for k in (1000, 3000, 5000):
            X[k:k + 40] += 4 * A
        tA = A - A.mean()
        tB = B - B.mean()
        bank = {"templates": [tA / np.linalg.norm(tA), tB / np.linalg.norm(tB)],
                "rows": [{"class": "Q", "side": None}, {"class": "E", "side": None}]}
        live = np.ones(n, bool)
        bg = live.copy()
        for k in (1000, 3000, 5000):
            bg[k - 50:k + 90] = False
        s = {"live": live, "bg": bg}
        out = ao.session_peaks(X, s, {"Sova": bank}, np)
        q = out[("Sova", "Q")]
        top = q["frame"][np.argsort(q["value"])[::-1][:3]]
        np.testing.assert_array_equal(np.sort(top), [1000, 3000, 5000])
        d = ao.detections(q["frame"], q["value"], 3.0, 300)
        np.testing.assert_array_equal(d, [1000, 3000, 5000])
        e = out[("Sova", "E")]
        self.assertEqual(len(ao.detections(e["frame"], e["value"], 3.0, 300)), 0)


if __name__ == "__main__":
    unittest.main()
