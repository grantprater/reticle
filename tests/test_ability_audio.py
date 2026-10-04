"""The audio witness's scoring library (`adjudication.ability_audio`) on
synthetic data: the window, the refusals, the whitening, the template, the
FFT track against a direct Pearson, the threshold, the parameter store, and
the own-kit mask (`adjudication.tray_kit.own_kit_mask`)."""
from __future__ import annotations

import tempfile
import unittest

import numpy as np

from reticle.adjudication import ability_audio as aa
from reticle.adjudication.tray_kit import own_kit_mask


class WindowTest(unittest.TestCase):
    def test_the_window_maximum_matches_a_brute_force_scan(self):
        rng = np.random.default_rng(0)
        for pre, post in ((200, 300), (3, 5), (5, 3), (4, 4), (0, 3)):
            t = rng.normal(size=700).astype(np.float32)
            got = aa.window_max(t, pre, post)
            want = [t[max(0, k - pre):min(len(t), k + post)].max() for k in range(len(t))]
            np.testing.assert_array_equal(got, np.array(want, np.float32))


class ClippedWindowTest(unittest.TestCase):
    def test_a_window_stops_at_the_midpoint_to_each_neighbouring_cast(self):
        lo, hi = aa.clip_bounds([1000, 1000, 5000], [1000, 1001, 1200, 4000, 5000], 200, 300)
        # 1001 is the cast itself; 1200 cuts at 1100; 5000 has 4000 before it.
        np.testing.assert_array_equal(lo, [800, 800, 4800])
        np.testing.assert_array_equal(hi, [1100, 1100, 5300])
        lo, hi = aa.clip_bounds([1000, 4600], [], 200, 300)
        np.testing.assert_array_equal(lo, [800, 4400])
        np.testing.assert_array_equal(hi, [1300, 4900])
        lo, hi = aa.clip_bounds([1000], [997, 1002], 200, 300)
        self.assertEqual((int(lo[0]), int(hi[0])), (999, 1001))   # a lone frame window

    def test_the_range_maximum_matches_a_brute_force_scan(self):
        rng = np.random.default_rng(7)
        t = rng.normal(size=500).astype(np.float32)
        lo = np.array([0, 10, 490, 100, 50, -5])
        hi = np.array([5, 11, 520, 300, 60, 3])
        want = [t[max(a, 0):min(b, len(t))].max() for a, b in zip(lo, hi)]
        np.testing.assert_array_equal(aa.range_max(t, lo, hi), np.array(want, np.float32))

    def test_without_neighbours_the_scores_are_the_fixed_window(self):
        rng = np.random.default_rng(8)
        tracks = {"C": rng.normal(size=2000).astype(np.float32),
                  "Q": rng.normal(size=2000).astype(np.float32)}
        f = [300, 900, 1500]
        np.testing.assert_array_equal(aa.cast_scores(tracks, f, ["C", "Q"]),
                                      aa.cast_scores(tracks, f, ["C", "Q"], neighbours=[]))
        tracks["C"][:] = 0
        tracks["C"][1000] = 9.0
        got = aa.cast_scores(tracks, [900], ["C", "Q"], neighbours=[900, 1100])
        self.assertLess(got[0, 0], 9.0)    # the next cast's sound is not this cast's
        got = aa.cast_scores(tracks, [900], ["C", "Q"], neighbours=[900])
        self.assertEqual(got[0, 0], 9.0)


class SplitAndReferenceRuleTest(unittest.TestCase):
    def test_the_split_alternates_sorted_sessions_and_halves_a_lone_one(self):
        got = aa.split_sessions({"Sova": ["d", "b", "a", "c", "e"], "Iso": ["z"]})
        self.assertEqual(got["Sova"], {"dev": ["a", "c", "e"], "held": ["b", "d"]})
        self.assertEqual(got["Iso"], {"dev": ["z:first"], "held": ["z:second"]})

    def test_a_file_whose_event_two_abilities_play_is_shared(self):
        plays = {"Hunter|Play_Mvt_A": {"Q", "4"}, "Hunter|Play_Circle": {"Q"}}
        keep = aa.shared_reference_mask([["Hunter|Play_Circle"], ["Hunter|Play_Mvt_A"],
                                         [], ["Hunter|Play_Circle", "Hunter|Play_Mvt_A"]], plays)
        np.testing.assert_array_equal(keep, [True, False, True, False])

    def test_the_pooled_whitener_never_pairs_frames_across_sessions(self):
        from scipy.signal import lfilter
        rng = np.random.default_rng(9)
        sessions = []
        for k in range(3):
            y = lfilter([1.0], [1.0, -0.8, 0.1], rng.normal(size=(20000, 3)), axis=0)
            bg = np.ones(len(y), bool)
            bg[::500] = False
            sessions.append((y.astype(np.float32), bg))
        W = aa.fit_whitener(iter(sessions))
        np.testing.assert_allclose(W["ar"], [0.8, -0.1], atol=0.03)
        self.assertEqual(W["bg_frames"], sum(int(b.sum()) for _y, b in sessions))

    def test_a_correction_beside_a_label_sets_the_slot_and_keeps_the_label(self):
        import json
        from pathlib import Path
        from reticle import ability_audio_fit as fit
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / fit.VERIFIED_DIR).mkdir(parents=True)
            (root / fit.CORRECTIONS_DIR).mkdir(parents=True)
            label = {"key": "s:1911000:Q", "session_id": "s", "t_drop_s": 1911.0, "slot": "Q"}
            other = {"key": "s:20000:E", "session_id": "s", "t_drop_s": 20.0, "slot": "E"}
            text = json.dumps(label) + "\n" + json.dumps(other) + "\n"
            (root / fit.VERIFIED_DIR / "s.jsonl").write_text(text, encoding="utf-8")
            fix = {"key": "s:1911000:Q", "slot": "C", "basis": "player"}
            (root / fit.CORRECTIONS_DIR / "s.jsonl").write_text(json.dumps(fix) + "\n",
                                                                 encoding="utf-8")
            got = fit.verified_casts(root)["s"]
            self.assertEqual((got[0]["slot"], got[0]["label_slot"]), ("C", "Q"))
            self.assertEqual(got[1]["slot"], "E")
            self.assertNotIn("label_slot", got[1])
            self.assertEqual(json.loads((root / fit.VERIFIED_DIR / "s.jsonl")
                                        .read_text(encoding="utf-8").splitlines()[0])["slot"], "Q")


class IdentifyTest(unittest.TestCase):
    CLASSES = ["C", "Q", "E", aa.NONE]
    THR = {"C": 1.5, "Q": 1.5, "E": 1.5}

    def test_each_refusal_and_a_verdict(self):
        scores = np.array([[3.0, 1.0, 0.5, 0.0],    # C named
                           [1.0, 1.2, 0.5, 4.0],    # none wins
                           [1.2, 1.0, 0.5, 0.0],    # below the class threshold
                           [2.0, 1.9, 0.5, 0.0]])   # a tie with Q
        out = aa.identify(scores, self.CLASSES, self.THR)
        self.assertEqual([r["reason"] for r in out],
                         [None, "none_wins", "below_null", "pairwise_tie"])
        self.assertEqual(out[0]["verdict"], "C")
        self.assertEqual((out[0]["runner_up"], out[0]["margin"]), ("Q", 2.0))
        self.assertTrue(all(r["verdict"] is None for r in out[1:]))
        self.assertEqual(out[3]["runner_up"], "Q")

    def test_a_class_without_a_threshold_is_below_null(self):
        out = aa.identify(np.array([[5.0, 0.0]]), ["X", "C"], {"C": 1.0})
        self.assertEqual(out[0]["reason"], "below_null")

    def test_no_casts_give_no_rows(self):
        self.assertEqual(aa.identify(np.zeros((0, 2)), ["C", "Q"], self.THR), [])


class WhiteningTest(unittest.TestCase):
    def test_the_band_whitener_makes_the_background_white(self):
        rng = np.random.default_rng(1)
        A = rng.normal(size=(6, 6))
        X = rng.normal(size=(40000, 6)) @ A + 3.0
        mu, P, cond = aa.fit_band_whitener(X, shrink=0.0)
        C = np.cov(((X - mu) @ P).T)
        np.testing.assert_allclose(C, np.eye(6), atol=0.03)
        self.assertGreater(cond, 1.0)

    def test_ar2_recovers_its_coefficients_and_never_crosses_a_gap(self):
        from scipy.signal import lfilter
        rng = np.random.default_rng(2)
        y = lfilter([1.0], [1.0, -0.9, 0.2], rng.normal(size=(60000, 3)), axis=0)
        mask = np.ones(len(y), bool)
        mask[::1000] = False
        ar = aa.fit_ar2(y, mask)
        np.testing.assert_allclose(ar, [0.9, -0.2], atol=0.02)
        w = aa.whiten_frames(y, np.zeros(3), np.eye(3), ar)
        lag1 = np.corrcoef(w[3:, 0], w[2:-1, 0])[0, 1]
        self.assertLess(abs(lag1), 0.02)


class TemplateTest(unittest.TestCase):
    def test_a_template_is_unit_norm_and_zero_mean_and_a_silent_clip_none(self):
        L = np.full((300, aa.BMASK.size), -120.0)
        L[50:120] = np.random.default_rng(3).normal(-20, 5, size=(70, aa.BMASK.size))
        T = aa.template(L)
        self.assertEqual(T.shape[1], int(aa.BMASK.sum()))
        self.assertAlmostEqual(float(np.linalg.norm(T)), 1.0, places=5)
        self.assertAlmostEqual(float(T.mean()), 0.0, places=5)
        self.assertIsNone(aa.template(np.full((100, aa.BMASK.size), -200.0)))
        W = aa.whiten_template(T, np.eye(T.shape[1]), [0.5, -0.1])
        self.assertEqual(len(W), len(T) - 2)
        self.assertAlmostEqual(float(np.linalg.norm(W)), 1.0, places=5)


class TrackTest(unittest.TestCase):
    def test_the_fft_track_is_the_lagged_pearson_correlation(self):
        rng = np.random.default_rng(4)
        X = rng.normal(size=(400, 5)).astype(np.float32)
        W = rng.normal(size=(12, 5))
        W = ((W - W.mean()) / np.linalg.norm(W - W.mean())).astype(np.float32)
        X[100:112] += 40 * W
        tr = aa.Corpus(X, len(W)).track(W)
        for k in (0, 50, 100, 387):
            seg = X[k:k + len(W)].ravel()
            want = np.corrcoef(seg, W.ravel())[0, 1]
            self.assertAlmostEqual(float(tr[k]), want, places=4)
        self.assertEqual(int(np.argmax(tr)), 100)
        self.assertTrue((tr[400 - len(W) + 1:] == -1).all())

    def test_class_tracks_take_the_maximum_over_a_class_and_scale_on_the_null(self):
        rng = np.random.default_rng(5)
        X = rng.normal(size=(3000, 4)).astype(np.float32)
        W1 = aa.whiten_template(rng.normal(size=(10, 4)), np.eye(4), [0.0, 0.0])
        W2 = aa.whiten_template(rng.normal(size=(10, 4)), np.eye(4), [0.0, 0.0])
        null = np.ones(len(X), bool)
        tr = aa.class_tracks(X, [W1, W2], ["C", "C"], null)
        one = aa.class_tracks(X, [W1], ["C"], null)["C"]
        two = aa.class_tracks(X, [W2], ["C"], null)["C"]
        np.testing.assert_allclose(tr["C"], np.maximum(one, two), atol=1e-6)
        self.assertAlmostEqual(float(np.quantile(one, 0.999)), 1.0, places=2)


class ThresholdTest(unittest.TestCase):
    def test_the_threshold_lets_one_false_fire_per_live_minute(self):
        peaks = [np.array([5.0, 4.0, 3.0]), np.array([2.0, 1.0])]
        thr = aa.threshold_at(peaks, live_min=2.0)
        self.assertEqual(sum(int((p >= thr).sum()) for p in peaks), 2)
        self.assertGreater(thr, 3.0)
        self.assertIsNone(aa.threshold_at(peaks, live_min=0.0))

    def test_explained_frames_take_the_closest_kind(self):
        code = aa.explained(1000, [2.0], [(5.0, 6.0)], [8.0])
        self.assertEqual(code[200], 0)
        self.assertEqual(code[550], 1)
        self.assertEqual(code[800], 2)
        self.assertEqual(code[0], 3)
        self.assertEqual(code[999], 3)
        code = aa.explained(1000, [], [], [])
        self.assertTrue((code == 3).all())


class ParamsTest(unittest.TestCase):
    def test_a_parameter_set_round_trips_and_is_never_overwritten(self):
        a = {"mu": np.zeros(3), "P": np.eye(3), "ar": [0.9, -0.2],
             "templates": [np.ones((4, 3), np.float32), np.zeros((6, 3), np.float32)],
             "labels": ["C", "Q"], "files": ["a", "b"], "slots": {"C": "Widget"},
             "thresholds": {"C": 1.5, "Q": 1.4}, "dev": ["s1"], "fit": {"bg_frames": 9}}
        with tempfile.TemporaryDirectory() as d:
            aa.save_params(d, "p-test", {"KAY/O": a}, {"note": "test"})
            got, why = aa.load_params(d, "p-test", "KAY/O")
            self.assertIsNone(why)
            self.assertEqual([t.shape for t in got["templates"]], [(4, 3), (6, 3)])
            self.assertEqual(got["thresholds"], a["thresholds"])
            self.assertEqual(got["provenance"]["note"], "test")
            self.assertEqual(aa.load_params(d, "p-test", "Sova")[1], "no_params_for:Sova")
            self.assertEqual(aa.load_params(d, "p-none", "Sova")[1], "no_params:p-none")
            with self.assertRaises(FileExistsError):
                aa.save_params(d, "p-test", {"KAY/O": a}, {})

    def test_a_calibrated_set_copies_the_arrays_and_stores_the_calibration(self):
        a = {"mu": np.zeros(3), "P": np.eye(3), "ar": [0.9, -0.2],
             "templates": [np.ones((4, 3), np.float32)], "labels": ["C"], "files": ["a"],
             "slots": {"C": "Widget"}, "thresholds": {"C": 1.5}, "dev": ["s1"], "fit": {}}
        cal = {"pooled": {"w": [0.3, 1.0], "dev_n": 10, "dev_right": 8},
               "agents": {"KAY/O": {"w": [0.5, 2.0], "basis": "agent", "dev_n": 10,
                                    "dev_right": 8}}}
        with tempfile.TemporaryDirectory() as d:
            aa.save_params(d, "p-a", {"KAY/O": a}, {"split": {}})
            self.assertIsNone(aa.load_params(d, "p-a", "KAY/O")[0]["calibration"])
            with self.assertRaises(ValueError):
                aa.save_calibrated(d, "p-a", "p-x", {"pooled": cal["pooled"], "agents": {}}, {})
            aa.save_calibrated(d, "p-a", "p-b", cal, {"rule": "test"})
            got, _ = aa.load_params(d, "p-b", "KAY/O")
            self.assertEqual(got["calibration"]["w"], [0.5, 2.0])
            self.assertEqual(got["provenance"]["derived_from"]["version"], "p-a")
            self.assertEqual(got["provenance"]["calibration"]["pooled"], cal["pooled"])
            self.assertEqual((aa.params_path(d, "p-a") / "params.npz").read_bytes(),
                             (aa.params_path(d, "p-b") / "params.npz").read_bytes())
            with self.assertRaises(FileExistsError):
                aa.save_calibrated(d, "p-a", "p-b", cal, {})


class CalibrationTest(unittest.TestCase):
    def test_the_referenced_margin_leaves_none_out(self):
        best, m = aa.ref_margin(np.array([[1.0, 3.0, 2.0, 9.0], [5.0, 1.0, 1.5, 0.0]]),
                                ["C", "Q", "E", aa.NONE])
        self.assertEqual(best, ["Q", "C"])
        np.testing.assert_allclose(m, [1.0, 3.5])
        best, m = aa.ref_margin(np.array([[2.0, 1.0]]), ["C", aa.NONE])
        self.assertEqual(best, ["C"])
        self.assertTrue(np.isnan(m[0]))

    def test_an_agent_without_enough_wrong_dev_casts_takes_the_pooled_fit(self):
        rng = np.random.default_rng(1)
        x = rng.uniform(-3, 3, 2000)
        y = (rng.uniform(size=2000) < 1 / (1 + np.exp(-(0.5 + 1.0 * x)))).astype(float)
        cal = aa.calibrate({"A": (x, y), "B": (np.array([3.0, 4.0]), np.array([1.0, 1.0]))},
                           ["A", "B", "C"])
        np.testing.assert_allclose(cal["agents"]["A"]["w"], [0.5, 1.0], atol=0.1)
        self.assertEqual(cal["agents"]["A"]["basis"], "agent")
        self.assertEqual([cal["agents"][a]["basis"] for a in "BC"], ["pooled", "pooled"])
        self.assertEqual(cal["agents"]["C"]["w"], cal["pooled"]["w"])
        self.assertEqual(cal["pooled"]["dev_n"], 2002)
        p = aa.p_right([0.0, 10.0, np.nan], [-1.0, 2.0])
        self.assertAlmostEqual(p[0], 1 / (1 + np.e))
        self.assertAlmostEqual(p[1], 1 - 1e-6)
        self.assertTrue(np.isnan(p[2]))


class OwnKitMaskTest(unittest.TestCase):
    def test_frames_near_a_span_of_the_players_kit_only(self):
        spans = [(1000.0, 5000.0, "Sova"), (9000.0, 12000.0, "Omen")]
        t = np.array([500.0, 3000.0, 6500.0, 8500.0, 10000.0, 20000.0])
        np.testing.assert_array_equal(own_kit_mask(t, spans, "Sova"),
                                      [True, True, False, False, False, False])
        np.testing.assert_array_equal(own_kit_mask(t, spans, "Omen"),
                                      [False, False, False, True, True, False])


class WitnessRefusalTest(unittest.TestCase):
    def test_without_an_agent_or_parameters_every_cast_carries_the_reason(self):
        from reticle.ability_timeline import audio_cast_witness
        rows = [{"t_ms": 1000.0, "slot": "Q", "player_cast": True, "reason": None},
                {"t_ms": 2000.0, "slot": "E", "player_cast": False, "reason": "kit_not_player"}]
        with tempfile.TemporaryDirectory() as d:
            out = audio_cast_witness(d, "s", rows, None)
            self.assertEqual([r["reason"] for r in out["rows"]], ["no_player_agent"])
            out = audio_cast_witness(d, "s", rows, "Sova")
            self.assertTrue(out["coverage"]["reason"].startswith("no_params:"))
            self.assertIsNone(out["rows"][0]["verdict"])


if __name__ == "__main__":
    unittest.main()
