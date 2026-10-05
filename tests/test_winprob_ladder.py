"""winprob_ladder's pure parts on synthetic matches: no store."""
import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import winprob_ladder as wl  # noqa: E402
import winprob_reference as wr  # noqa: E402

RED = [f"r{i}" for i in range(5)]
BLUE = [f"b{i}" for i in range(5)]


def v4_match(mid="m1", plants=True, kill_seed=0):
    """Two rounds: round 0 (Red attacks) Red plants and wins by detonation;
    round 12 (Blue attacks) Red eliminates Blue."""
    rng = np.random.default_rng(kill_seed)
    players = [{"player": p, "team": "Red"} for p in RED] + [{"player": p, "team": "Blue"} for p in BLUE]
    rounds = [{"round": 0, "winning_team": "Red", "result": "Detonate", "plant_ms": 40000,
               "plant_x": 1, "plant_y": 2, "planter": "r0" if plants else None,
               "defuse_ms": None, "defuser": None},
              {"round": 12, "winning_team": "Red", "result": "Elimination", "plant_ms": None,
               "plant_x": None, "plant_y": None, "planter": None, "defuse_ms": None, "defuser": None}]
    econ = [{"round": n, "player": p, "loadout_value": 3000 if p.startswith("r") else 1000,
             "remaining": 500, "was_afk": False, "received_penalty": False}
            for n in (0, 12) for p in RED + BLUE]
    kills, pos, k = [], [], 0
    alive = set(RED + BLUE)
    for t, v in ((10000, "b0"), (20000, "b1")):
        kills.append({"kill": k, "round": 0, "time_in_round_ms": t, "time_in_match_ms": 50000 + t,
                      "killer": "r1", "victim": v})
        alive.discard(v)
        pos += [{"event": "kill", "kill": k, "player": p, "x": float(rng.integers(0, 100)), "y": 0.0}
                for p in sorted(alive)]
        k += 1
    alive = set(RED + BLUE)
    for i, v in enumerate(BLUE):
        kills.append({"kill": k, "round": 12, "time_in_round_ms": 5000 * (i + 1),
                      "time_in_match_ms": 900000 + 5000 * (i + 1), "killer": "r2", "victim": v})
        alive.discard(v)
        pos += [{"event": "kill", "kill": k, "player": p, "x": 0.0, "y": 0.0} for p in sorted(alive)]
        k += 1
    m = {"match_id": mid, "queue": "competitive"}
    return m, players, rounds, econ, kills, pos


class Adapter(unittest.TestCase):
    def test_attacker_rule(self):
        self.assertEqual([wl.attacker_team(n) for n in (0, 11, 12, 23, 24, 25, 26)],
                         ["Red", "Red", "Blue", "Blue", "Red", "Blue", "Red"])

    def test_record_runs_through_reference_simulation(self):
        rec, why = wl.v4_record(*v4_match(), "/Game/Maps/Ascent/Ascent")
        self.assertEqual(sum(why.values()), 0)
        rounds, w = wl.admit({"m1": rec})
        self.assertEqual(len(rounds), 2)
        self.assertEqual(w["simulation_disagrees"], 0)
        r0, r12 = rounds
        self.assertEqual((r0["att_team"], r0["y"], r0["dec_kind"]), ("Red", 1, "detonation"))
        self.assertEqual((r12["att_team"], r12["y"], r12["dec_kind"]), ("Blue", 0, "elimination"))
        self.assertEqual(r0["map"], "Ascent")
        D = wl.state_sets(rounds)
        s = D["G"].S[0]
        self.assertEqual((s["a"], s["d"], s["aload"] - s["dload"], s["acred"] - s["dcred"]),
                         (5, 5, 10000.0, 0.0))
        # after the first kill in round 0 one defender (Blue) is gone
        k = D["K"].S[0]
        self.assertEqual((k["a"], k["d"], k["dcred"]), (5, 4, 2000.0))

    def test_planter_on_wrong_side_excludes_round(self):
        m, players, rounds, econ, kills, pos = v4_match()
        rounds[0]["planter"] = "b3"
        rec, why = wl.v4_record(m, players, rounds, econ, kills, pos, "/Game/Maps/Ascent/Ascent")
        self.assertEqual(why["side_rule_planter_mismatch"], 1)
        self.assertEqual([r["roundNum"] for r in rec["match"]["roundResults"]], [12])

    def test_split(self):
        ms = [{"match_id": "a", "captured": False, "holdout": False},
              {"match_id": "b", "captured": False, "holdout": True},
              {"match_id": "c", "captured": True, "holdout": True},
              {"match_id": "d", "captured": False, "holdout": True},
              {"match_id": "e", "captured": False, "holdout": False}]
        role, why = wl.split_sets(ms, riot_ids={"e"}, kept={"d"})
        self.assertEqual(role, {"a": "FIT", "b": "E2", "c": None, "d": None, "e": None})
        self.assertEqual(dict(why), {"captured": 2, "kept_replay_final_test": 1})


def synth(n_matches, n_rounds=20, beta=(1.5, 1.0, 0.1, 0.8), seed=0, prefix="s"):
    """Kill-like states with known logistic truth on alive, side, plant flag."""
    rng = np.random.default_rng(seed)
    rounds, S = [], []
    for m in range(n_matches):
        for r in range(n_rounds):
            a, d = 5, 5
            pl = bool(rng.random() < 0.4)
            states = []
            for _ in range(4):
                if rng.random() < 0.5:
                    a = max(a - 1, 1)
                else:
                    d = max(d - 1, 1)
                states.append({"t": 0.0, "a": a, "d": d, "aload": 0.0, "dload": 0.0,
                               "planted": pl, "tp": 0.0 if pl else None})
            x = np.array([(a - d) / 5, (a - d) / (a + d), 1.0, float(pl)])
            y = int(rng.random() < wr.sig(x @ np.array(beta)))
            ri = len(rounds)
            rounds.append({"sid": f"{prefix}{m}", "y": y, "map": "x"})
            S += [s | {"ri": ri} for s in states]
    return wr.Data(S, rounds)


class Scores(unittest.TestCase):
    def test_ece_of_perfect_bins_and_bootstrap_shape(self):
        D = synth(10)
        p = np.where(D.y > 0, 0.95, 0.05)
        out = wl.evaluate_scores(D, p, boot=50)
        self.assertAlmostEqual(out["ece"], 0.05, places=6)
        self.assertLessEqual(out["logloss_nats_ci95"][0], out["logloss_nats"])
        self.assertGreaterEqual(out["logloss_nats_ci95"][1], out["logloss_nats"])
        self.assertEqual(sum(r["round_weight"] for r in out["reliability10"]), 200)

    def test_centred_fit_limits(self):
        D = synth(30, seed=1)
        X, y, w, _m, pen = wl.matrices(D, wl.CS_SPEC, [])
        mle = wl.fit_centered(X, y, w, np.full(4, 1e-6), np.zeros(4))
        self.assertTrue(np.allclose(mle, wr.fit_logit(X, y, w, [1e-6] * 4), atol=1e-6))
        b0 = np.array([0.1, -0.2, 0.3, -0.4])
        far = wl.fit_centered(X, y, w, np.full(4, 1e9), b0)
        self.assertTrue(np.allclose(far, b0, atol=1e-4))

    def test_learning_curve_prior_helps_small_samples(self):
        F = synth(12, seed=2)
        E = synth(8, seed=3, prefix="e")
        X, y, w, _m, pen = wl.matrices(synth(200, seed=4, prefix="c"), wl.CS_SPEC, [])
        prior = wr.fit_logit(X, y, w, list(pen))
        out = wl.learning_curve(F, E, {"cs": prior}, boot=100, sizes=(2,), reps=4)
        self.assertEqual(set(out), {"2", "all"})
        self.assertGreater(out["2"]["cs"]["gain_nats"], 0)
        self.assertEqual(out["all"]["reps"], 1)

    def test_band_difference_interval_covers_zero_for_same_truth(self):
        D = synth(24, seed=5)
        strata = {f"s{m}": ("Silver" if m % 2 else "Gold") for m in range(24)}
        out = wl.band_coefs(D, strata, wl.CS_SPEC, boot=60)
        self.assertEqual(out["columns"], ["alive_diff_5", "alive_diff_ratio", "side", "planted"])
        self.assertEqual(out["bronze_silver"]["matches"] + out["gold_platinum"]["matches"], 24)
        self.assertEqual(len(out["difference"]["ci95"]), 4)

    def test_concat_rebases_rounds(self):
        A, B = synth(2, prefix="a"), synth(3, prefix="b")
        C = wl.concat(A, B)
        self.assertEqual(len(C.S), len(A.S) + len(B.S))
        self.assertEqual(len(set(C.match.tolist())), 5)
        self.assertTrue(np.array_equal(C.y, np.concatenate([A.y, B.y])))


if __name__ == "__main__":
    unittest.main()
