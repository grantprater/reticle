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


if __name__ == "__main__":
    unittest.main()
