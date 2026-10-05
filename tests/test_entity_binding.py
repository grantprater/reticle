"""The causal binding prototype (`prototypes/entity_binding.py`) on synthetic
fits, and one regression on a dev session's stored rows; none is evidence."""
from __future__ import annotations

import math
import unittest
from pathlib import Path

import numpy as np

from prototypes import entity_binding as eb

STORE = Path.home() / "reticle-store"
DEV = "a06f04a0059f"


def _fits(frames: list[list[tuple]], n_frames: int) -> dict:
    """Flat fit arrays from per-frame lists of (x, y, llr5, flags, is_self)."""
    rows = [(k, *f) for k, fr in enumerate(frames) for f in fr]
    fpos = np.asarray([r[0] for r in rows], np.int64)
    x = np.asarray([r[1] for r in rows], float)
    y = np.asarray([r[2] for r in rows], float)
    llr = np.asarray([r[3] for r in rows], float).reshape(-1, 5)
    is_self = np.asarray([r[5] for r in rows], bool)
    flags = {name: np.asarray([name in r[4] for r in rows], bool) for name in eb.NP_REASONS}
    return {"fpos": fpos, "start": np.searchsorted(fpos, np.arange(n_frames + 1)),
            "x": x, "y": y, "llr": llr, "is_self": is_self, "flags": flags}


def _bind(fits, F, *, open_=None, player=0, spect=None, margin=0.6):
    t = np.arange(F, dtype=float) * 66.7
    op = np.ones((5, F), bool) if open_ is None else open_
    return eb.causal_bind(t, fits, op, np.zeros(F, np.int64), player,
                          np.full(F, -1, np.int64) if spect is None else spect,
                          r_fit=1.0, v_max=7.0, log_area=math.log(1.0e4), r_dup_m=1.0,
                          margin_min=margin)


def _llr(slot: int, v: float = 1.5) -> list[float]:
    out = [0.0] * 5
    out[slot] = v
    return out


Z = [0.0] * 5


class MotionTest(unittest.TestCase):
    def test_two_teammates_keep_their_slots(self):
        # frame 0 names them by portrait; afterwards no portrait, motion keeps them
        F = 8
        frames = [[(0.0, 0.0, _llr(1), (), False), (30.0, 0.0, _llr(2), (), False)]]
        for k in range(1, F):
            frames.append([(30.0 - 0.3 * k, 0.0, Z, (), False), (0.3 * k, 0.0, Z, (), False)])
        out = _bind(_fits(frames, F), F)
        self.assertTrue(np.allclose(out["X"][1, 1:], [0.3 * k for k in range(1, F)]))
        self.assertTrue(np.allclose(out["X"][2, 1:], [30.0 - 0.3 * k for k in range(1, F)]))
        self.assertEqual(out["counts"]["fit_bound_twice"], 0)

    def test_unbound_slot_keeps_no_fit_and_opens_nothing(self):
        F = 3
        frames = [[(0.0, 0.0, _llr(1), (), False)] for _ in range(F)]
        out = _bind(_fits(frames, F), F)
        self.assertTrue(out["has"][1].all())
        self.assertFalse(out["has"][2:].any())       # no fit creates a player


class ChainTest(unittest.TestCase):
    def test_portrait_evidence_moves_a_swapped_chain(self):
        # frame 0 binds the two fits the wrong way round (weak portraits), then
        # each fit's portrait names the other slot for many frames
        F = 40
        frames = [[(0.0, 0.0, _llr(2, 0.3), (), False), (40.0, 0.0, _llr(1, 0.3), (), False)]]
        for _ in range(1, F):
            frames.append([(0.0, 0.0, _llr(1), (), False), (40.0, 0.0, _llr(2), (), False)])
        out = _bind(_fits(frames, F), F)
        self.assertEqual(out["X"][2, 0], 0.0)       # published wrong at frame 0
        self.assertGreater(out["counts"].get("chain_swaps", 0), 0)
        self.assertEqual(out["X"][1, -1], 0.0)      # and right once the chains moved
        self.assertEqual(out["X"][2, -1], 40.0)


class NonPlayerTest(unittest.TestCase):
    def test_every_fit_is_bound_or_explained(self):
        F = 2
        frames = [[(0.0, 0.0, _llr(1), (), False)],
                   [(0.1, 0.0, _llr(1), (), False),
                    (0.4, 0.0, Z, (), False),                  # beside a bound fit
                    (20.0, 0.0, Z, ("ability_glyph",), False),  # the reader's barrier
                    (60.0, 60.0, Z, ("off_map",), False)]]
        open_ = np.zeros((5, F), bool)
        open_[[0, 1], :] = True                                 # one teammate lives
        out = _bind(_fits(frames, F), F, open_=open_)
        self.assertEqual(out["np_bucket"].tolist()[2:], ["duplicate", "ability_glyph", "off_map"])
        bound = int((out["bound_to"] >= 0).sum())
        self.assertEqual(bound + int((out["np_bucket"] != "").sum()), len(out["np_bucket"]))

    def test_relocation_binds_a_named_far_fit(self):
        # the slot's anchor is far; a fit its portrait names still binds there
        F = 3
        frames = [[(0.0, 0.0, _llr(1), (), False)], [], [(300.0, 0.0, _llr(1, 3.0), (), False)]]
        out = _bind(_fits(frames, F), F)
        self.assertEqual(out["X"][1, 2], 300.0)


class SelfFitTest(unittest.TestCase):
    def test_self_binds_player_then_spectated_then_assignment(self):
        F = 3
        frames = [[(5.0, 5.0, Z, (), True)] for _ in range(F)]
        open_ = np.ones((5, F), bool)
        open_[0, 1:] = False                                    # the player dies at frame 1
        spect = np.array([-1, 3, -1])
        out = _bind(_fits(frames, F), F, open_=open_, spect=spect)
        self.assertEqual(out["how"][0, 0], eb.HOW_SELF)
        self.assertEqual(out["how"][3, 1], eb.HOW_SPECTATE)
        self.assertEqual(out["wit"][3, 1], eb.WITNESS_SPECTATE)
        bound = [int(out["how"][s, 2]) for s in range(5) if out["has"][s, 2]]
        self.assertEqual(bound, [eb.HOW_ASSIGNED_SPECTATED])
        self.assertEqual(out["counts"]["self_offered_to_assignment"], 1)


@unittest.skipUnless((STORE / "events" / "ally_icon" / f"{DEV}.jsonl").is_file(),
                     "no stored ally_icon rows for the dev session")
class StoredRowRegressionTest(unittest.TestCase):
    """`a06f04a0059f` (dev) from stored rows, against the run of 2026-10-04
    (entity-binding-0.1.0 on ally-icon-0.11.0): 57430 fits, 54474 bound, the
    rest explained, none bound twice."""

    def test_dev_session_binding(self):
        from prototypes import entity_state as es
        G = es.build_slots(DEV, binding="causal")
        if G["S"].ally_icon_version != "ally-icon-0.11.0":
            self.skipTest(f"ally_icon is {G['S'].ally_icon_version}; the counts are 0.11.0's")
        c = G["bind"]["counts"]
        self.assertEqual(c["fit_bound_twice"], 0)
        self.assertEqual(c["fits"], 57430)
        self.assertEqual(c["fits_bound"], 54474)
        self.assertEqual(c["fits_bound"] + sum(G["bind"]["np_by_reason"].values()), c["fits"])
        self.assertEqual(G["bind"]["np_by_reason"]["ability_glyph"], 2050)


if __name__ == "__main__":
    unittest.main()
