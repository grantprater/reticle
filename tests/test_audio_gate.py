"""The audio gate's pure parts on synthetic arrays: no decode, no store, no GPU."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import audio_gate as ag  # noqa: E402


# ---------------------------------------------------------------- gunfire rule

class FireRuleTests(unittest.TestCase):

    def test_magazine_falling_with_reserve_still_is_fire(self):
        t = [0.0, 0.5, 1.0]
        fires, reloads, swaps = ag.fire_rule(t, [25, 20, 18], [50, 50, 50], [0.9, 0.9, 0.9])
        assert fires == [(0.0, 0.5), (0.5, 1.0)]
        assert reloads == [] and swaps == []


    def test_reload_and_swap_are_not_fire(self):
        t = [0.0, 0.5, 1.0]
        # 5 -> 25 with the reserve falling is a reload; 25 -> 12 with the reserve
        # changing too is a swap to another weapon.
        fires, reloads, swaps = ag.fire_rule(t, [5, 25, 12], [70, 50, 36], [0.9] * 3)
        assert fires == []
        assert reloads == [(0.0, 0.5)]
        assert swaps == [(0.5, 1.0)]


    def test_low_confidence_unread_and_distant_rows_are_skipped(self):
        t = [0.0, 0.5, 1.0, 1.5, 3.0]
        mag = [25, 20, None, 15, 10]
        res = [50, 50, 50, 50, 50]
        conf = [0.9, 0.5, 0.9, 0.9, 0.9]
        fires, _r, _s = ag.fire_rule(t, mag, res, conf)
        # 0->1: row 1 below the reader's threshold; 1->2 and 2->3: row 2 unread;
        # 3->4: 1.5 s apart, not consecutive at 2 Hz.
        assert fires == []
        assert ag.fire_rule([0.0, 0.5], [25, 20], [50, 50], [None, 0.9])[0] == []


# ---------------------------------------------------------------- windows

def _toy_classes(**kw):
    nb = 200                                    # 20 s of 100 ms frames
    args = dict(live=np.ones(nb, bool), buy=np.zeros(nb, bool), stalled=np.zeros(nb, bool),
                casts=[], drops_live=[], fires=[], others=[], other_deaths=[])
    args.update(kw)
    return ag.classify_blocks(nb, **args), (np.arange(nb) + 0.5) * ag.STEP


class WindowTests(unittest.TestCase):

    def test_cast_window_and_its_background_exclusion(self):
        cls, c = _toy_classes(casts=[5.0])
        cast = np.flatnonzero(cls == ag.CAST)
        # Frames overlapping [4.7, 6.5]: 4.7 lies in frame 47, 6.5 ends frame 64.
        assert cast[0] == 47 and cast[-1] == 64
        near = (np.abs(c - 5.0) < ag.BG_GAP_CAST) & (cls != ag.CAST)
        assert (cls[near] == ag.NONE).all()
        assert (cls[np.abs(c - 5.0) >= ag.BG_GAP_CAST] == ag.BG).all()


    def test_gunfire_and_known_others_exclude_background(self):
        cls, c = _toy_classes(fires=[(10.0, 10.5)], others=[15.0], other_deaths=[18.5])
        assert list(np.flatnonzero(cls == ag.FIRE)) == [100, 101, 102, 103, 104]
        assert (cls[(c > 9.0) & (c < 11.5) & (cls != ag.FIRE)] == ag.NONE).all()
        assert (cls[(c > 13.0) & (c < 17.0)] == ag.NONE).all()
        assert (cls[(c > 17.5) & (c < 19.5)] == ag.NONE).all()
        assert cls[5] == ag.BG and cls[125] == ag.BG


    def test_refused_drops_stalls_buy_and_dead_time(self):
        nb = 200
        live = np.ones(nb, bool)
        live[150:] = False                          # the player died
        buy = np.zeros(nb, bool)
        buy[:20] = True
        live[:20] = False
        stalled = np.zeros(nb, bool)
        stalled[60:70] = True
        cls, c = _toy_classes(live=live, buy=buy, stalled=stalled, drops_live=[12.0])
        assert (cls[:20] == ag.BUY).all()
        assert (cls[60:70] == ag.NONE).all()
        assert (cls[150:] == ag.NONE).all()
        assert (cls[(np.abs(c - 12.0) < ag.BG_GAP_CAST)] == ag.NONE).all()


    def test_explanation_prefers_cast_then_gunfire_then_known_other(self):
        code, when = ag.explain_codes(200, casts=[5.0], fires=[(5.5, 6.0), (12.0, 12.5)],
                                      others=[12.4, 18.0])
        assert code[50] == 0 and when[50] == 5.0            # onset 5.0 s: own cast
        assert code[120] == 1 and when[120] == 12.0         # own gunfire before a known other
        assert code[180] == 2 and when[180] == 18.0
        assert code[160] == 3 and np.isnan(when[160])       # 16 s: 2 s from 18 s
        assert code[int(round(16.5 / ag.STEP))] == 2        # 1.5 s from 18.0 counts


# ---------------------------------------------------------------- pooling

class PoolingTests(unittest.TestCase):

    def test_pooling_takes_mean_and_max_of_each_block(self):
        W = np.arange(25 * 2, dtype=float).reshape(25, 2)
        m, x = ag.pool_blocks(W)
        assert m.shape == (2, 2) and x.shape == (2, 2)      # the 5-frame tail is dropped
        assert np.allclose(m[0], W[:10].mean(axis=0))
        assert np.allclose(x[1], W[19])


    def test_context_features_span_five_blocks(self):
        W = np.zeros((100, 3))
        W[50:60, 0] = 10.0                                  # block 5 loud in band 0
        m, x = ag.pool_blocks(W)
        s1, s2 = ag.diff_sums(W)
        X = ag.context_features(m, x, s1, s2)
        assert X.shape == (10, 9)
        assert np.allclose(X[3:8, 0], 10.0 / 5)             # mean over five blocks sees it
        assert X[2, 0] == 0 and X[8, 0] == 0
        assert (X[3:8, 3] == 10.0).all()                    # max
        assert X[5, 6] > 0 and X[0, 6] == 0                 # delta spread


    def test_smoothing_is_a_centred_mean(self):
        s = ag.smooth(np.array([0, 0, 3, 0, 0], float))
        assert np.allclose(s, [0, 1, 1, 1, 0])


# ---------------------------------------------------------------- detections

class DetectionTests(unittest.TestCase):

    def test_frames_closer_than_the_merge_gap_join(self):
        s = np.zeros(30)
        s[[3, 4, 6, 10, 20, 23]] = 1.0
        on, off = ag.detect(s, 0.5)
        # 4 -> 6 is 0.2 s apart: one detection; 6 -> 10 and 20 -> 23 are 0.3 s or more.
        assert list(on) == [3, 10, 20, 23]
        assert list(off) == [6, 10, 20, 23]


    def test_recall_window_and_unexplained_rate_on_a_toy_timeline(self):
        onsets = np.array([9.6, 20.9, 31.1, 40.0])
        casts = np.array([10.0, 20.0, 30.0])
        hit, lag = ag.recall_hits(onsets, casts)
        # 9.6 is 0.4 s early (inside); 20.9 is 0.9 s late (inside); 31.1 is 1.1 s late.
        assert list(hit) == [True, True, False]
        assert np.allclose(lag[:2], [-0.4, 0.9])
        nb = 600
        live = np.ones(nb, bool)
        live[400:] = False
        code = np.full(nb, 3, np.int8)
        code[96] = 0
        on = np.array([96, 209, 311, 400])
        det, un = ag.rates(on, live, code, live_min=live.sum() * ag.STEP / 60)
        assert np.isclose(det, 3 / (40 / 60))                # onset 400 is outside live time
        assert np.isclose(un, 2 / (40 / 60))


    def test_a_long_detection_covers_a_cast_its_onset_misses(self):
        on, off = np.array([80, 300]), np.array([130, 302])   # 8.0-13.1 s and 30.0-30.3 s
        casts = np.array([10.0, 31.5, 50.0])
        assert list(ag.covered(on, off, casts)) == [True, False, False]
        assert list(ag.recall_hits(on * ag.STEP, casts)[0]) == [False, False, False]

    def test_leave_one_session_out(self):
        sessions = ["a", "b", "c", "d"]
        splits = list(ag.loso_splits(sessions))
        assert [h for h, _t in splits] == sessions
        for held, train in splits:
            assert held not in train and sorted(train + [held]) == sessions


    def test_duty_cycle_widens_each_detection_inside_live_time(self):
        s = np.zeros(400)
        s[100:103] = 1.0                                    # 10.0-10.3 s
        live = np.ones(400, bool)
        live[300:] = False
        d = {"s": s, "live": live}
        # frames 85..117 are within 1.5 s of the detection: 33 of 300 live frames
        assert np.isclose(ag.duty([d], 0.5), 33 / 300)
        assert ag.duty([d], 2.0) == 0.0

    def test_witness_onsets_near_detections_and_unexplained_near_witnesses(self):
        nb = 600
        s = np.zeros(nb)
        s[[100, 300, 500]] = 1.0                           # onsets at 10, 30, 50 s
        code = np.full(nb, 3, np.int8)
        code[100] = 0                                       # 10 s is an own cast
        d = {"sid": "x", "s": s, "live": np.ones(nb, bool), "code": code}
        onsets = {"x": {"ping": np.array([11.0, 31.2, 40.0]), "smoke": np.array([])}}
        v = ag.witness_eval("F9", [d], 0.5, onsets)
        assert v["ping_onsets_live"] == 3
        assert v["F9_ping_onsets_near"] == round(2 / 3, 3)       # 11 and 31.2; 40 is alone
        assert v["F9_ping_unexplained_near"] == 0.5              # 30 s of the 30 and 50 s pair
        assert v["smoke_onsets"] == 0 and v["F9_smoke_onsets_near"] is None

    def test_operating_points_read_the_curve(self):
        c = {"tau": np.array([0.1, 0.5, 0.9]), "unexpl": np.array([12.0, 2.5, 0.5]),
             "rv": np.array([0.9, 0.6, 0.2]), "ra": np.array([0.8, 0.5, 0.1])}
        assert ag.at_rate(c, 3) == 1 and ag.at_rate(c, 1) == 2 and ag.at_rate(c, 0.1) is None
        assert ag.at_recall(c, 0.6) == 1 and ag.at_recall(c, 0.95) is None


# ---------------------------------------------------------------- fits

class FitTests(unittest.TestCase):

    def test_logistic_regression_recovers_a_separable_problem(self):
        rng = np.random.default_rng(0)
        centres = np.array([[6, 0], [0, 6], [-6, -6]], float)
        y = np.repeat([0, 1, 2], [30, 200, 400])             # unbalanced on purpose
        X = (centres[y] + rng.normal(size=(len(y), 2))).astype(np.float32)
        m = ag.fit_logreg(X, y, 3, max_iter=2000)
        P = ag.predict_proba(X, m)
        assert (P.argmax(axis=1) == y).all()
        assert m["loss"] < 0.1 and 1 < m["iterations"] <= 2000


    def test_gaussian_density_ranks_outliers_last(self):
        rng = np.random.default_rng(1)
        X = rng.normal(size=(500, 4)).astype(np.float32)
        g = ag.fit_gauss(X)
        d = ag.mahalanobis(np.vstack([np.zeros(4), np.full(4, 6.0)]).astype(np.float32), g)
        assert d[1] > d[0] + 5
        assert np.allclose(ag.rank01(np.array([3.0, 1.0, 2.0])), [1.0, 0.0, 0.5])


if __name__ == "__main__":
    unittest.main()
