"""The ability tray: bar counts, fills, drops and their suspicion, and the gate
that decides which drops are the player's casts."""
from __future__ import annotations

import unittest

import numpy as np

from reticle import tray
from reticle.ability_timeline import player_tray_casts

TEAL = (180, 170, 30)


def _frame(fill=(1.0, 1.0, 1.0, 1.0)) -> np.ndarray:
    f = np.zeros((1080, 1920, 3), np.uint8)
    for k, x in enumerate(fill):
        cx = tray.SLOT_X0 + tray.SLOT_DX * k
        w = int(round(2 * tray.BAR_HALF * x))
        f[tray.BAR_Y0:tray.BAR_Y1, cx - tray.BAR_HALF:cx - tray.BAR_HALF + w] = TEAL
    return f


class TrayReadTest(unittest.TestCase):
    def test_counts_follow_the_bar(self):
        full, ok = tray.slot_counts(_frame())
        half, _ = tray.slot_counts(_frame((0.5, 1.0, 1.0, 1.0)))
        self.assertTrue(ok)
        self.assertAlmostEqual(half[0] / full[0], 0.5, delta=0.03)

    def test_a_teal_screen_is_refused(self):
        f = np.zeros((1080, 1920, 3), np.uint8)
        f[1000:1080] = TEAL
        self.assertFalse(tray.slot_counts(f)[1])

    def test_a_drop_and_a_spectator_switch(self):
        rows = [(1.0, 1.0, 1.0, 1.0)] * 3 + [(0.0, 1.0, 1.0, 1.0)] * 3 \
            + [(0.0, 0.0, 0.0, 1.0)] * 3
        counts = np.array([tray.slot_counts(_frame(r))[0] for r in rows], float)
        ts = [1000.0 * (i + 1) for i in range(len(rows))]
        got = tray.drops(ts, counts, np.ones(len(rows), bool))
        self.assertEqual([(d["t_ms"], d["slot"]) for d in got],
                         [(4000.0, "C"), (7000.0, "Q"), (7000.0, "E")])
        self.assertFalse(got[0]["suspect"])
        self.assertTrue(got[1]["cooccur"] and got[2]["cooccur"])

    def _flooded(self, fill):
        # Sova's bow glowing over the tray: the guard rows go teal.
        f = _frame(fill)
        f[tray.GUARD_Y[0][0]:tray.GUARD_Y[0][1], tray.SLOT_X0 - 60:tray.SLOT_X0 + 400] = TEAL
        return f

    def test_a_drop_under_a_flash_is_compared_across_it(self):
        frames = [_frame()] * 3 + [self._flooded((1.0, 1.0, 0.0, 1.0))] \
            + [_frame((1.0, 1.0, 0.0, 1.0))] * 3
        counts, clean = zip(*(tray.slot_counts(f) for f in frames))
        self.assertEqual(clean, (True,) * 3 + (False,) + (True,) * 3)
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        got = tray.drops(ts, np.array(counts, float), np.array(clean, bool))
        self.assertEqual([(d["t_ms"], d["slot"], d["across_gap"]) for d in got],
                         [(2500.0, "E", True)])

    def test_a_long_refusal_is_not_bridged(self):
        frames = [_frame()] * 3 + [self._flooded((1.0, 1.0, 0.0, 1.0))] * 7 \
            + [_frame((1.0, 1.0, 0.0, 1.0))] * 3
        counts, clean = zip(*(tray.slot_counts(f) for f in frames))
        ts = [500.0 * (i + 1) for i in range(len(frames))]
        self.assertEqual(tray.drops(ts, np.array(counts, float), np.array(clean, bool)), [])

    def test_an_undrawn_tray_is_no_reading(self):
        self.assertFalse(tray.drawn(np.zeros(4)))
        self.assertTrue(tray.drawn(np.array([0.0, 0.0, 0.5, 0.0])))

    def test_a_quiet_drop_is_marked_but_marks_no_other(self):
        ev = [(20.0, "Q", 1.25, 0.97, False), (20.0, "E", 1.0, 0.0, False),
              (30.0, "C", 1.0, 0.0, False)]
        self.assertEqual([s for *_x, s in tray.flag_suspect(ev)], [True, True, False])
        got = tray.flag_suspect(ev, quiet=[True, False, False])
        self.assertEqual([s for *_x, s in got], [True, False, False])


class PlayerCastGateTest(unittest.TestCase):
    def _drop(self, t, slot, forced=False):
        return {"t_ms": t, "slot": slot, "from": 1.0, "to": 0.0, "forced": forced,
                "suspect": forced, "cooccur": False}

    @staticmethod
    def _rounds(*bounds):
        return [{"t_start_ms": a, "t_end_ms": z, "t_close_ms": c} for a, z, c in bounds]

    def test_the_gate(self):
        rounds = self._rounds((0.0, 90000.0, 100000.0))
        phase = lambda t: "buy_phase" if t < 5000 else "round_live"
        drops = [self._drop(3000, "C"), self._drop(20000, "E"), self._drop(49500, "Q"),
                 self._drop(60000, "X"), self._drop(150000, "C")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [50000.0])}
        self.assertEqual(got[3000]["reason"], "phase:buy_phase")
        self.assertTrue(got[20000]["player_cast"])
        self.assertEqual(got[49500]["reason"], "after_player_death")
        self.assertEqual(got[60000]["reason"], "after_player_death")
        self.assertEqual(got[150000]["reason"], "no_round")

    def test_a_death_where_rounds_touch_belongs_to_the_round_it_ends(self):
        rounds = self._rounds((0.0, 60000.0, 60000.0), (60000.0, 150000.0, 150000.0))
        got = player_tray_casts([self._drop(80000, "E")], lambda t: "round_live",
                                rounds, [60000.0, 120000.0])
        self.assertTrue(got[0]["player_cast"])
        self.assertEqual(got[0]["first_player_death_ms"], 120000.0)

    def test_suspicion_is_recomputed_among_the_casts(self):
        # A cast beside a post-death spectator switch is no longer tainted by it.
        rounds = self._rounds((0.0, 100000.0, 100000.0))
        phase = lambda t: "round_live"
        drops = [self._drop(20000, "E"), self._drop(20500, "Q"), self._drop(40000, "C"),
                 self._drop(40800, "Q")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [41000.0])}
        self.assertEqual(got[20000]["reason"], "cooccur_among_casts")
        self.assertTrue(got[40000]["reason"] == "after_player_death")
        drops = [self._drop(38000, "C"), self._drop(40500, "Q")]
        got = {r["t_ms"]: r for r in player_tray_casts(drops, phase, rounds, [41000.0])}
        self.assertTrue(got[38000]["player_cast"])


if __name__ == "__main__":
    unittest.main()
