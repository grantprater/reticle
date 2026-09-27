"""The voice-line matcher's pure parts on synthetic arrays: no decode, no store, no GPU."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import voice_lines as vl  # noqa: E402


# ---------------------------------------------------------------- correlation

class PlantedTemplateTests(unittest.TestCase):

    def test_log_mel_template_is_found_at_its_frame(self):
        rng = np.random.default_rng(0)
        T = rng.normal(0, 8, (60, 16)).astype(np.float32)
        W = rng.normal(0, 6, (2000, 16)).astype(np.float32)
        W[1234:1294] += T + 5.0          # a gain offset changes nothing
        s = vl.ncc_tracks(W, [vl.prepare(T)], xp=np)[0]
        assert int(np.argmax(s)) == 1234
        assert s[1234] > 0.7
        assert np.all(s[len(W) - 59:] == -1.0)     # windows past the end


    def test_flat_window_scores_zero_not_infinity(self):
        rng = np.random.default_rng(1)
        T = rng.normal(0, 8, (20, 8)).astype(np.float32)
        W = rng.normal(0, 6, (300, 8)).astype(np.float32)
        W[100:200] = 0.0                  # undecoded audio, as median_removed leaves it
        s = vl.ncc_tracks(W, [vl.prepare(T)], xp=np)[0]
        assert np.all(np.abs(s[s > -1]) <= 1.0 + 1e-5)
        assert np.all(s[100:181] == 0.0)


    def test_per_frame_normalisation_removes_a_gain_ramp(self):
        rng = np.random.default_rng(2)
        T = rng.normal(0, 8, (40, 16)).astype(np.float32)
        W = rng.normal(0, 3, (800, 16)).astype(np.float32)
        W[300:340] += T + np.linspace(0, 20, 40)[:, None]   # the line swells
        Wc = W - W.mean(axis=1, keepdims=True)
        s = vl.ncc_tracks(Wc, [vl.prepare(T, per_frame=True)], xp=np)[0]
        assert int(np.argmax(s)) == 300


    def test_waveform_template_is_found_at_its_hop(self):
        rng = np.random.default_rng(3)
        x = rng.normal(0, 0.3, 48000 * 3).astype(np.float32)
        y = rng.normal(0, 0.3, 4000).astype(np.float32)
        x[50000:54000] += y
        s = vl.phat_tracks(x, [y], chunk=1 << 15, xp=np)[0]
        assert int(np.argmax(s)) == 50000 // vl.HOP_N
        assert s.max() > 0.2
        assert np.median(s[s > -1]) < 0.05


    def test_a_template_straddling_two_chunks_is_still_found(self):
        rng = np.random.default_rng(4)
        x = rng.normal(0, 0.3, 48000 * 2).astype(np.float32)
        y = rng.normal(0, 0.3, 3000).astype(np.float32)
        chunk = 1 << 14
        step = (chunk - int(np.ceil(3000 / vl.HOP_N)) * vl.HOP_N) // vl.HOP_N * vl.HOP_N
        at = step - 1000                 # starts in chunk 0, ends past its step
        x[at:at + 3000] += y
        s = vl.phat_tracks(x, [y], chunk=chunk, xp=np)[0]
        assert int(np.argmax(s)) == at // vl.HOP_N


# ---------------------------------------------------------------- templates

class TemplateTests(unittest.TestCase):

    def test_trim_keeps_the_active_span_and_floors_silence(self):
        L = np.full((50, 4), -100.0, np.float32)
        L[10:30] = 40.0
        L[20, 2] = -100.0                # a digital hole inside the line
        ok = np.ones(50, bool)
        ok[:3] = False
        T, k0, k1 = vl.trim_floor(L, ok, active_db=40.0, floor_db=50.0)
        assert (k0, k1) == (10, 30)
        assert T.min() == -10.0


    def test_names_parse_to_agent_and_variant(self):
        assert vl.parse_name(Path("KAY_O_ult_enemy.mp3")) == ("KAY_O", "enemy")
        assert vl.parse_name(Path("Sova_ult_ally.mp3")) == ("Sova", "ally")


# ---------------------------------------------------------------- classes

def _sides(ally, ally_soft=(), enemy=(), enemy_refused=0):
    return {"ally": {"named": list(ally), "soft": list(ally_soft),
                     "refused": 5 - len(ally), "complete": len(ally) == 5},
            "enemy": {"named": list(enemy), "soft": [], "refused": enemy_refused,
                      "complete": enemy_refused == 0 and len(enemy) == 5}}


class ClassTests(unittest.TestCase):

    def test_classes_follow_the_lineup(self):
        s = _sides(["Sova", "Jett", "Sage", "Omen"], ally_soft=["Raze", "Breach"],
                   enemy=["Reyna", "Viper", "Neon", "Cypher", "Fade"])
        c = lambda a, v: vl.template_class(a, v, s, "Sova")
        assert c("Sova", "ally") == "own"
        assert c("Sova", "enemy") == "impossible"   # Sova is on no enemy slot
        assert c("Jett", "ally") == "possible"
        assert c("Raze", "ally") == "unknown"       # a refused slot's best guess
        assert c("Killjoy", "ally") == "impossible"
        assert c("Reyna", "enemy") == "possible"
        assert c("Killjoy", "enemy") == "impossible"


    def test_an_incomplete_enemy_side_leaves_enemy_lines_unknown(self):
        s = _sides(["Sova", "Jett", "Sage", "Omen", "Raze"],
                   enemy=["Reyna", "Viper", "Neon", "Cypher"], enemy_refused=1)
        assert vl.template_class("Killjoy", "enemy", s, "Sova") == "unknown"
        assert vl.template_class("Reyna", "enemy", s, "Sova") == "possible"
        assert vl.template_class("Killjoy", "ally", s, "Sova") == "impossible"


    def test_no_lineup_leaves_all_but_the_own_line_unknown(self):
        assert vl.template_class("Skye", "ally", None, "Skye") == "own"
        assert vl.template_class("Jett", "ally", None, "Skye") == "unknown"
        assert vl.template_class("Skye", "enemy", None, "Skye") == "unknown"


# ---------------------------------------------------------------- peaks

class PeakTests(unittest.TestCase):

    def test_nms_keeps_the_higher_peak_within_one_template_length(self):
        s = np.zeros(60, np.float32)
        s[10], s[14], s[30], s[45] = 0.9, 0.8, 0.7, 0.2
        pk = vl.nms_peaks(s, m=5, floor=0.5)
        assert pk.tolist() == [10, 30]
        assert vl.nms_peaks(s, m=4, floor=0.5).tolist() == [10, 14, 30]


    def test_operating_threshold_allows_the_stated_rate(self):
        imp = np.array([0.9, 0.5, 0.4, 0.3])
        tau = vl.operating_tau(imp, live_min=10.0, rate=0.1)   # one allowed
        assert (imp >= tau).sum() == 1 and tau > 0.5
        tau2 = vl.operating_tau(imp, live_min=25.0, rate=0.1)  # two allowed
        assert (imp >= tau2).sum() == 2


# ---------------------------------------------------------------- 0.2.0: suppression

class SuppressionTests(unittest.TestCase):

    def test_the_best_template_at_one_onset_stands(self):
        t = np.array([10.0, 10.3, 10.9, 12.0, 10.1])
        j = np.array([0, 1, 2, 1, 0])
        score = np.array([0.5, 0.9, 0.4, 0.3, 0.45])
        keep, by = vl.suppress(t, j, score, window=0.6)
        assert keep.tolist() == [False, True, False, True, False]
        assert by.tolist() == [1, -1, 1, -1, 1]


    def test_a_dropped_peak_drops_nothing(self):
        keep, by = vl.suppress(np.array([0.0, 1.0, 2.0]), np.array([0, 1, 2]),
                               np.array([0.9, 0.8, 0.7]), window=1.0)
        assert keep.tolist() == [True, False, True]
        assert by.tolist() == [-1, 0, -1]


    def test_peaks_of_one_template_never_drop_each_other(self):
        keep, _by = vl.suppress(np.array([0.0, 0.5]), np.array([3, 3]),
                                np.array([0.9, 0.8]), window=1.0)
        assert keep.tolist() == [True, True]


    def test_suppression_filters_every_per_peak_array(self):
        n = 4
        d = {"t": np.array([0.0, 0.2, 5.0, 9.0]), "j": np.array([0, 1, 0, 1]),
             "score": np.array([0.3, 0.6, 0.5, 0.1]), "cls": np.array(["a", "b", "c", "d"], object),
             "live": np.ones(n, bool), "dt": np.full(n, np.nan),
             "agent": np.array(["A", "B", "A", "B"], object),
             "variant": np.array(["ally"] * n, object), "names": ["A_ult_ally", "B_ult_ally"],
             "sid": "x"}
        out = vl.apply_suppression(d, 1.0)
        assert out["t"].tolist() == [0.2, 5.0, 9.0]
        assert out["cls"].tolist() == ["b", "c", "d"]
        assert out["kept"].tolist() == [False, True, True, True]
        assert out["dropped_by"].tolist() == [1, -1, -1, -1]
        assert vl.apply_suppression(d, None) is d


# ---------------------------------------------------------------- 0.2.0: cast windows

class CastWindowTests(unittest.TestCase):

    def test_phoenix_counts_a_line_long_before_the_drop(self):
        d = {"t": np.array([87.4, 250.0]), "score": np.array([0.3, 0.2]),
             "cls": np.array(["own", "own"], object)}
        casts = [{"t": 100.0}]
        best, _lag = vl.best_near(d, casts)
        assert best[0] == -np.inf
        lo, hi = vl.cast_window("Phoenix")
        best, lag = vl.best_near(d, casts, lo=lo, hi=hi)
        assert best[0] == 0.3 and abs(lag[0] + 12.6) < 1e-9
        assert vl.cast_window("Sova") == (-vl.OWN_WIN, vl.OWN_WIN)


# ---------------------------------------------------------------- 0.2.0: Gekko and merging

class HarvestTests(unittest.TestCase):

    def test_the_ult_pair_comes_from_the_ally_and_enemy_cast_sections(self):
        rows = [
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Cast", "file": "G__t__ally-cast__2.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Cast", "file": "G__t__ally-cast__1.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Enemy Cast", "file": "G__t__enemy-cast__1.mp3"},
            {"agent": "Gekko", "ability": "Thrash", "section": "Ally Recast", "file": "G__t__ally-recast__1.mp3"},
            {"agent": "Gekko", "ability": "Wingman", "section": "Cast", "file": "G__w__cast__1.mp3"},
            {"agent": "Sova", "ability": "Hunter's Fury", "section": "Ally Cast", "file": "S__h__ally-cast__1.mp3"}]
        got = vl.harvested_ults(rows, have={"Sova"})
        assert got == {"Gekko_ult_ally": "G__t__ally-cast__1.mp3",
                       "Gekko_ult_enemy": "G__t__enemy-cast__1.mp3"}


    def test_two_abilities_with_ally_casts_stop_the_harvest(self):
        rows = [{"agent": "X", "ability": "One", "section": "Ally Cast", "file": "a.mp3"},
                {"agent": "X", "ability": "Two", "section": "Enemy Cast", "file": "b.mp3"}]
        with self.assertRaises(SystemExit):
            vl.harvested_ults(rows, have=set())


    def test_merged_peaks_renumber_templates(self):
        base = {"names": np.array(["A", "B"]), "tpl": np.array([0, 1, 1], np.int16),
                "frame": np.array([5, 7, 9]), "score": np.array([0.1, 0.2, 0.3], np.float32),
                "floor": np.array([0.01, 0.02]), "median": np.array([0.0, 0.0]),
                "max": np.array([0.1, 0.3])}
        new = {"tpl": np.array([0, 0], np.int16), "frame": np.array([3, 4]),
               "score": np.array([0.5, 0.6], np.float32), "floor": np.array([0.05]),
               "median": np.array([0.0]), "max": np.array([0.6])}
        m = vl.merge_peaks(new, ["G"], base, ["A", "B", "G"])
        assert m["tpl"].tolist() == [0, 1, 1, 2, 2]
        assert m["frame"].tolist() == [5, 7, 9, 3, 4]
        assert np.allclose(m["floor"], [0.01, 0.02, 0.05])
        with self.assertRaises(SystemExit):
            vl.merge_peaks(new, ["G"], base, ["A", "C"])


# ---------------------------------------------------------------- rounds

class RoundTests(unittest.TestCase):

    def test_round_invariant_counts_repeats_of_one_line(self):
        keys = ["Sova_ally", "Sova_ally", "Jett_ally", "Sova_ally", "Sova_enemy", "Omen_ally"]
        rounds = [1, 1, 1, 2, 2, None]
        u = vl.round_unique(keys, rounds)
        assert u.tolist() == [False, False, True, True, True, False]


    def test_round_of_uses_the_round_window(self):
        rows = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100000.0, "t_close_ms": 107000.0},
                {"round_no": 2, "t_start_ms": 107000.0, "t_end_ms": 200000.0,
                 "t_close_ms": 207000.0}]
        assert vl.round_of(50.0, rows) == 1
        assert vl.round_of(103.0, rows) == 1        # the post-round period is the round's
        assert vl.round_of(150.0, rows) == 2
        assert vl.round_of(300.0, rows) is None


    def test_removals_count_the_cast_hits_suppression_costs(self):
        d = {"sid": "s", "t": np.array([10.0, 10.3]), "j": np.array([0, 1]),
             "score": np.array([0.2, 0.35]), "cls": np.array(["own", "possible"], object),
             "live": np.ones(2, bool), "agent": np.array(["Sova", "Fade"], object),
             "variant": np.array(["ally", "enemy"], object),
             "names": ["Sova_ult_ally", "Fade_ult_enemy"]}
        ctxs = {"s": {"sides": {}, "demo": False, "rounds": [], "own": [{"t": 10.2}],
                      "player": "Sova"}}
        v, rows = vl.removals([d], ctxs, tau=0.1, window=1.2)
        assert (v["removed_own"], v["removed_own_by_true"], v["removed_own_at_cast"]) == (1, 1, 1)
        assert (v["own_hits_unsuppressed"], v["own_hits_suppressed"], v["own_hits_lost"]) == (1, 0, 1)
        assert v["own_hits_agent_window_lost"] == 1
        assert rows[0]["dropped_by"] == "Fade_ult_enemy" and rows[0]["in_own_cast_window"]


if __name__ == "__main__":
    unittest.main()
