"""`reticle/slot_state.py`: the round barrier, the entity axis's extension
points, the gate's query, the renamed tray lane, and one regression on a
development match's stored rows. Synthetic cases are no evidence."""
from __future__ import annotations

import math
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from reticle import slot_state as ss

STORE = Path.home() / "reticle-store"
DEV = "9acf02f98283"


def _grid(F, dt=100.0):
    return np.arange(F, dtype=float) * dt


def _fits(frames: list[list[tuple]], n_frames: int) -> dict:
    """Flat fit arrays from per-frame lists of (x, y)."""
    rows = [(k, *f) for k, fr in enumerate(frames) for f in fr]
    fpos = np.asarray([r[0] for r in rows], np.int64)
    n = fpos.size
    return {"fpos": fpos, "start": np.searchsorted(fpos, np.arange(n_frames + 1)),
            "x": np.asarray([r[1] for r in rows], float), "y": np.asarray([r[2] for r in rows], float),
            "llr": np.zeros((n, 5)), "is_self": np.zeros(n, bool),
            "flags": {r: np.zeros(n, bool) for r in ss.NP_REASONS}}


class RoundBarrierTest(unittest.TestCase):
    """No state outlives a round."""

    def test_beliefs_forget_the_last_round(self):
        F = 6
        t = _grid(F)
        X = np.full((1, F), np.nan)
        X[0, 1] = 3.0
        Y = np.where(np.isfinite(X), 0.0, np.nan)
        seg_start = np.array([0, 0, 0, 3, 3, 3])
        B = ss.beliefs(t, X, Y, np.isfinite(X), np.ones((1, F), bool), seg_start,
                       r_fit=1.0, r_icon=0.5, v_max=7.0)
        names = [ss.KINDS[int(k)] for k in B["kind"][0]]
        self.assertEqual(names, ["unanchored", "fit", "reach", "unanchored", "unanchored", "unanchored"])
        self.assertAlmostEqual(B["R"][0, 2], 7.0 * 0.1 + 1.0)

    def test_causal_binding_reanchors_after_the_barrier(self):
        # one teammate fit per frame; across the barrier the motion prior is gone,
        # so a fit far from the last round's binds by the uniform prior, not a relocation
        F = 4
        fits = _fits([[(0.0, 0.0)], [(0.5, 0.0)], [(80.0, 0.0)], [(80.5, 0.0)]], F)
        out = ss.causal_bind(_grid(F), fits, np.ones((5, F), bool), np.array([0, 0, 2, 2]), 0,
                             np.full(F, -1, np.int64), r_fit=1.0, v_max=7.0,
                             log_area=math.log(1.0e4), r_dup_m=1.0, margin_min=0.6)
        self.assertEqual(out["counts"]["fits_bound"], 4)
        self.assertEqual(out["counts"]["fit_bound_twice"], 0)
        slot = [int(np.flatnonzero(out["has"][:, k])[0]) for k in range(F)]
        self.assertNotIn(0, slot)                 # the player's slot takes no teammate fit
        self.assertEqual(slot[0], slot[1])
        self.assertEqual(slot[2], slot[3])


class EntityAxisTest(unittest.TestCase):
    """A second kind joins the entity axis without a second module."""

    def test_rows_are_keyed_by_kind_and_id(self):
        slots = [{"key": f"s:ally:slot:{k}", "agent": None} for k in range(5)]
        rows = ss.player_rows(slots)
        self.assertEqual(rows[2].key, ("player", "s:ally:slot:2"))
        self.assertEqual({r.side for r in rows}, {"ally"})

    def test_a_second_kind_stacks_and_shares_the_belief_law(self):
        F = 4
        t = _grid(F)
        player = {"rows": [ss.EntityRow("player", "p0", "ally", slot=0)],
                  "open": np.ones((1, F), bool), "X": np.array([[0.0, np.nan, np.nan, np.nan]]),
                  "Y": np.array([[0.0, np.nan, np.nan, np.nan]]), "has": np.array([[1, 0, 0, 0]], bool),
                  "wit": np.array([[1, 0, 0, 0]], bool), "obs": np.full((1, F), -1)}
        # an ability instance spawned at frame 1 and expired after frame 2
        ability = {"rows": [ss.EntityRow("ability", "a0", "ally", owner="p0")],
                   "open": np.array([[0, 1, 1, 0]], bool),
                   "X": np.array([[np.nan, 10.0, np.nan, np.nan]]),
                   "Y": np.array([[np.nan, 0.0, np.nan, np.nan]]),
                   "has": np.array([[0, 1, 0, 0]], bool), "wit": np.array([[0, 1, 0, 0]], bool),
                   "obs": np.full((1, F), -1)}
        E = ss.stack_entities([player, ability])
        B = ss.beliefs(t, E["X"], E["Y"], E["has"], E["open"], np.zeros(F, int),
                       r_fit=1.0, r_icon=0.5, v_max=7.0, wit=E["wit"])
        self.assertEqual([r.key for r in E["rows"]], [("player", "p0"), ("ability", "a0")])
        self.assertEqual([ss.KINDS[int(k)] for k in B["kind"][1]], ["closed", "fit", "reach", "closed"])


class RegionAtTest(unittest.TestCase):
    def _G(self):
        F = 3
        t = _grid(F)
        X = np.array([[0.0, np.nan, np.nan]])
        Y = np.array([[0.0, np.nan, np.nan]])
        B = ss.beliefs(t, X, Y, np.isfinite(X), np.ones((1, F), bool), np.zeros(F, int),
                       r_fit=1.0, r_icon=0.5, v_max=10.0)

        def to_m(px, py):
            return np.asarray(px, float) * 0.5, np.asarray(py, float) * 0.5
        to_m.to_px = lambda x, y: (np.asarray(x, float) * 2.0, np.asarray(y, float) * 2.0)
        return {"t_ms": t, "B": B, "rows": [ss.EntityRow("player", "p0", "ally", slot=0)],
                "params": {"v_max_m_s": 10.0}, "to_m": to_m, "m_per_px": 0.5}

    def test_closed_before_the_first_frame(self):
        q = ss.region_at(self._G(), -5.0)
        self.assertFalse(q["open"][0])
        self.assertEqual(q["frame"], -1)

    def test_radius_grows_with_age_since_the_frame(self):
        q = ss.region_at(self._G(), 150.0)        # frame 1 (reach), 50 ms later
        self.assertEqual(q["kind"], ["reach"])
        self.assertAlmostEqual(q["reach_m"][0], 10.0 * 0.1 + 1.0 + 10.0 * 0.05)
        self.assertAlmostEqual(q["reach_px"][0], q["reach_m"][0] / 0.5)
        self.assertEqual((q["ax_m"][0], q["apx"][0]), (0.0, 0.0))
        self.assertTrue(np.isnan(q["r_m"][0]))        # a reach belief has no point disc
        self.assertEqual(q["key"], [("player", "p0")])

    def test_a_fit_has_a_point_disc_and_no_reach(self):
        q = ss.region_at(self._G(), 20.0)         # frame 0 (fit), 20 ms later
        self.assertEqual(q["kind"], ["fit"])
        self.assertAlmostEqual(q["r_m"][0], 1.0 + 10.0 * 0.02)
        self.assertTrue(np.isnan(q["reach_m"][0]))


class LifecycleTest(unittest.TestCase):
    def test_agent_spellings_compare_through_the_owner(self):
        # the lineup's `KAY_O` and the killfeed's `KAY/O` are one agent
        F = 10
        S = SimpleNamespace(fr_t=_grid(F), fr_f=np.arange(F), rounds=[{"t_start_ms": 0.0}],
                            deaths=[{"side": "ally", "victim": "KAY/O", "t_ms": 300.0}])
        slots = [{"agent": a} for a in ("Jett", "KAY_O", "Clove", "Omen", "Sage")]
        L = ss.player_lifecycle(S, slots)
        self.assertEqual(L["open"][1].tolist(), [True] * 3 + [False] * 7)
        self.assertEqual(L["counts"]["close"], 1)


class LaneRenameTest(unittest.TestCase):
    def test_the_tray_lane_cannot_pass_for_the_slot_model(self):
        from reticle.entity_contract import STATE_VOCABULARY
        from reticle.entity_events import LANE
        self.assertIn("ability_tray", LANE)
        self.assertNotIn("slot_state", LANE)
        self.assertIn("ability_tray", STATE_VOCABULARY)
        self.assertNotIn("slot_state", STATE_VOCABULARY)


@unittest.skipUnless((STORE / "events" / "ally_icon" / f"{DEV}.jsonl").is_file(),
                     "no stored ally_icon rows for the development match")
class StoredRowRegressionTest(unittest.TestCase):
    """`9acf02f98283` from stored rows, as entity-state-0.3.0 built it on
    2026-10-09 on ally-icon-0.12.0 rows: 55047 fits, 52519 bound."""

    def test_development_match(self):
        G = ss.build_slots(DEV, binding="causal")
        if G["S"].ally_icon_version != "ally-icon-0.12.0":
            self.skipTest(f"ally_icon is {G['S'].ally_icon_version}")
        c = G["bind"]["counts"]
        self.assertEqual(c["fit_bound_twice"], 0)
        self.assertEqual((c["fits"], c["fits_bound"]), (55047, 52519))
        self.assertEqual(c["fits_bound"] + sum(G["bind"]["np_by_reason"].values()), c["fits"])
        self.assertEqual(G["life"]["counts"]["close"], 87)
        rec = ss.frame_record(G["B"], G["bind"]["obs"], G["t_ms"])
        self.assertEqual(rec.shape, (G["t_ms"].size, 5))
        fit = rec["kind"] == ss.FIT
        np.testing.assert_array_equal(rec["t_obs"][fit], np.broadcast_to(G["t_ms"][:, None], rec.shape)[fit])
        # the world frame's inverse round-trips widget pixels
        x, y = G["to_m"](np.array([100.0, 200.0]), np.array([150.0, 50.0]))
        px, py = G["to_m"].to_px(x, y)
        np.testing.assert_allclose(px, [100.0, 200.0], atol=1e-6)
        np.testing.assert_allclose(py, [150.0, 50.0], atol=1e-6)
        self.assertEqual(G["stamp"]["slot_state_version"], ss.SLOT_STATE_VERSION)


if __name__ == "__main__":
    unittest.main()
