"""The restock countdown numeral [domain:hud/ability-tray-restock-countdown]:
candidates rendered from the game font into one box, the read, its
opportunity, refusals, and the score against a return."""
from __future__ import annotations

import unittest

import numpy as np

from reticle import killfeed_numeral as kn
from reticle import tray
from reticle import tray_countdown as tc

FONT = tc.store_font("C:/Users/grant/reticle-store")
EMPTY_HALVES = np.array([[2, 2], [0, 0], [2, 2], [0, 0]])     # C and E spent


def _frame(text: str | None, slot: str = "E", bg=(70, 80, 120), noise: float = 3.0,
           seed: int = 0) -> np.ndarray:
    """A 1080p frame with `text` drawn white, centred where the numeral sits
    over `slot`."""
    rng = np.random.default_rng(seed)
    f = np.full((1080, 1920, 3), bg, np.float32)
    if text:
        ink = kn._ink(text, FONT, tc.FONT_PX, 0.0, 0.0)
        ys, xs = np.nonzero(ink > 0.02)
        ink = ink[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        cx = tray.SLOT_X0 + tray.SLOT_DX * tray.SLOT_KEYS.index(slot) + tc.NUMERAL_DX
        x0 = int(round(cx - ink.shape[1] / 2))
        y0 = int(round(tc.NUMERAL_CY - ink.shape[0] / 2))
        region = f[y0:y0 + ink.shape[0], x0:x0 + ink.shape[1]]
        region += ink[..., None] * (np.array([240, 242, 245], np.float32) - region)
    f += rng.normal(0, noise, f.shape)
    return np.clip(f, 0, 255).astype(np.uint8)


class OpportunityTest(unittest.TestCase):
    def test_only_spent_charge_slots_are_read(self):
        self.assertEqual(tc.read_opportunity(EMPTY_HALVES), ["C", "E"])
        self.assertEqual(tc.read_opportunity(np.zeros((4, 2), int)), [])

    def test_no_font_refuses_each_slot(self):
        got = tc.read_sample(_frame(None), EMPTY_HALVES, None)
        self.assertEqual([(r["slot"], r["reason"]) for r in got],
                         [("C", tc.REFUSE_NO_FONT), ("E", tc.REFUSE_NO_FONT)])


@unittest.skipUnless(FONT, "no game font in the store")
class ReadTest(unittest.TestCase):
    def test_one_box_holds_every_candidate(self):
        temps = tc.templates(FONT)
        self.assertEqual(temps.shape[0], len(tc.NUMERALS) * tc.PHASES ** 2)

    def test_each_numeral_reads_as_itself(self):
        temps = tc.templates(FONT)
        for text in ("50", "49", "9", "1", "0.4", "0.1", "27", "100"):
            r = tc.read_slot(_frame(text), "E", temps)
            self.assertEqual(r["numeral"], text, r)
            self.assertGreaterEqual(r["margin"], tc.READ_MIN_MARGIN)
        self.assertEqual(tc.read_slot(_frame("0.4"), "E", temps)["value_s"], 0.4)

    def test_an_unlit_box_is_no_read(self):
        self.assertIsNone(tc.read_slot(_frame(None), "E", tc.templates(FONT)))

    def test_a_lit_box_without_text_reads_empty_or_refuses(self):
        f = _frame(None, bg=(200, 205, 210), noise=12.0)
        r = tc.read_slot(f, "E", tc.templates(FONT))
        self.assertIn(r["numeral"], (tc.EMPTY, None))

    def test_the_sample_reads_only_its_opportunities(self):
        got = tc.read_sample(_frame("12"), EMPTY_HALVES, FONT)
        self.assertEqual([(r["slot"], r["numeral"]) for r in got], [("E", "12")])


class ScoreTest(unittest.TestCase):
    def test_a_numeral_dates_the_return(self):
        reads = [{"slot": "E", "t_ms": 1000.0, "numeral": "2", "value_s": 2.0},
                 {"slot": "E", "t_ms": 2500.0, "numeral": "0.6", "value_s": 0.6}]
        got = tc.score_against_returns(reads, [
            {"slot": "E", "t_ms": 3500.0, "t_before_ms": 3000.0},
            {"slot": "Q", "t_ms": 3500.0, "t_before_ms": 3000.0}])
        self.assertEqual(got[0]["zero_ms"], [3000.0, 3100.0])
        self.assertTrue(got[0]["agrees"])
        self.assertAlmostEqual(got[0]["lag_ms"], 400.0)
        self.assertIsNone(got[1]["read"])

    def test_a_gold_rise_is_a_return_to_date(self):
        g, e, t = 1, 2, 0
        halves = np.array([[[e, e], [t, t], [e, e], [e, e]],
                           [[e, e], [t, t], [e, g], [e, e]],
                           [[e, e], [t, t], [g, g], [e, e]],
                           [[e, e], [t, t], [g, g], [e, e]]])
        got = tc.gold_rises([0.0, 500.0, 1000.0, 9000.0], halves, [True] * 4, 0.5)
        self.assertEqual(got, [{"slot": "E", "t_ms": 500.0, "t_before_ms": 0.0},
                               {"slot": "E", "t_ms": 1000.0, "t_before_ms": 500.0}])


if __name__ == "__main__":
    unittest.main()
