"""Synthetic checks of prototypes/restock_measure.py: pairing, censoring, verdict.

No store is read; every input is built here.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import restock_measure as rm  # noqa: E402


def _state(t0, t1, rnd, phase="round_live", charges=1, unread=None):
    return {"kind": "state", "slot": "E", "t_first_ms": t0, "t_last_ms": t1, "round": rnd,
            "phase": phase, "charges": charges, "unreadable_reason": unread}


def _verdict(t, transition, before, after, step=500.0):
    return {"kind": "verdict", "slot": "E", "t_ms": t, "transition": transition, "reason": None,
            "before": {"t_ms": t - step, "charges": before}, "after": {"t_ms": t, "charges": after}}


class PairTest(unittest.TestCase):
    def test_one_charge_cast_and_return(self):
        rows = [_state(0, 200_000, 1),
                _verdict(10_000, "cast", 1, 0), _verdict(60_000, "recharge", 0, 1)]
        evs, states = rm.events(rows)
        iv, cen, out = rm.pair(evs, states)
        self.assertEqual(len(iv), 1)
        self.assertAlmostEqual(iv[0]["serial"], 50.0)
        self.assertEqual(iv[0]["bounds_s"], [49.5, 50.5])
        self.assertEqual(cen, [])
        self.assertEqual(out, [])

    def test_buy_phase_rise_is_not_a_return(self):
        rows = [_state(0, 20_000, 1, phase="buy_phase"), _state(20_000, 200_000, 1),
                _verdict(5_000, "buy", 0, 1), _verdict(30_000, "cast", 1, 0)]
        evs, states = rm.events(rows)
        self.assertEqual([e["kind"] for e in evs], ["spend"])

    def test_two_charges_serial_against_from_spend(self):
        # Spends at 10 s and 20 s; returns at 60 s and 110 s: one timer at a time.
        rows = [_state(0, 200_000, 1, charges=2),
                _verdict(10_000, "cast", 2, 1), _verdict(20_000, "cast", 1, 0),
                _verdict(60_000, "recharge", 0, 1), _verdict(110_000, "recharge", 1, 2)]
        iv, _c, _o = rm.pair(*rm.events(rows))
        self.assertEqual([i["serial"] for i in iv], [50.0, 50.0])
        self.assertEqual([i["from_spend"] for i in iv], [50.0, 90.0])

    def test_unreturned_spend_is_censored_at_last_readable(self):
        rows = [_state(0, 75_000, 1), _state(75_500, 90_000, 1, unread="kit_frozen:after_player_death"),
                _verdict(10_000, "cast", 1, 0)]
        iv, cen, _o = rm.pair(*rm.events(rows))
        self.assertEqual(iv, [])
        self.assertAlmostEqual(cen[0]["watched_s"], 65.0)
        self.assertEqual(rm.censored_against(cen), {"watched_past_50s": 1, "watched_past_60s": 1})

    def test_kill_and_orphan_returns_are_outliers(self):
        rows = [_state(0, 200_000, 1),
                _verdict(5_000, "recharge", 0, 1),
                _verdict(10_000, "cast", 1, 0), _verdict(30_000, "recharge", 0, 1)]
        iv, _c, out = rm.pair(*rm.events(rows), kills_ms=[29_000])
        self.assertEqual(iv, [])
        self.assertEqual([o["why"] for o in out],
                         ["return_without_a_pending_spend", "player_kill_before_return"])


class VerdictTest(unittest.TestCase):
    def test_candidates(self):
        self.assertEqual(rm.restock_verdict(rm.summarise([49.5, 50.0, 50.5]), {}), "50 s")
        self.assertEqual(rm.restock_verdict(rm.summarise([60.0, 59.5]), {}), "60 s")
        self.assertTrue(rm.restock_verdict(rm.summarise([40.0]), {}).startswith("neither"))

    def test_blind_instrument_cannot_answer(self):
        iv = [{"serial": 16.0}]
        v = rm.restock_verdict(rm.summarise([16.0]), {"watched_past_60s": 3}, iv)
        self.assertTrue(v.startswith("cannot-answer"))

    def test_censored_contradiction(self):
        v = rm.restock_verdict(rm.summarise([50.0]), {"watched_past_50s": 2}, [{"serial": 50.0}])
        self.assertIn("contradicted", v)

    def test_crop_bounds(self):
        b = rm.crop_bounds([("s", 10.0, 10.5, 60.0, 60.5, ""), ("s", 0.0, 0.5, 50.2, 50.4, "")])
        self.assertEqual(b["each"], [[49.5, 50.5], [49.7, 50.4]])
        self.assertEqual((b["common_lo"], b["common_hi"]), (49.7, 50.4))


if __name__ == "__main__":
    unittest.main()
