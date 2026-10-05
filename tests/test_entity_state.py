"""The ally slot prototype's belief law, binding and lifecycle
(`prototypes/entity_state.py`) on synthetic inputs; none is evidence."""
from __future__ import annotations

import math
import unittest
from types import SimpleNamespace

import numpy as np

from prototypes.entity_state import (CLOSED, CROWD, FIT, FIT_UNNAMED, REACH, UNANCHORED, beliefs,
                                     bind_entities, contains, last_fix, lifecycle,
                                     nearest_other, region_area, storage_record,
                                     truth_slot_map, union_area, v_max_m_s)


def _grid(F, dt=100.0):
    return np.arange(F, dtype=float) * dt


class LastFixTest(unittest.TestCase):
    def test_carries_and_resets_at_segment(self):
        has = np.array([[1, 0, 0, 1, 0, 0]], bool)
        seg_start = np.array([0, 0, 0, 0, 4, 4])
        self.assertEqual(last_fix(has, seg_start).tolist(), [[0, 0, 0, 3, -1, -1]])


class NearestOtherTest(unittest.TestCase):
    def test_host_within_distance_only(self):
        X = np.array([[0.0, 0.0], [1.0, 9.0], [np.nan, 0.5]])
        Y = np.zeros((3, 2))
        has = np.isfinite(X)
        h = nearest_other(X, Y, has, 2.0)
        self.assertEqual(h[:, 0].tolist(), [1, 0, -1])
        # frame 1: slot 2 at 0.5 is the nearest to slot 0; slot 1 at 9 m has none
        self.assertEqual(h[:, 1].tolist(), [2, -1, 0])


class BeliefTest(unittest.TestCase):
    def setUp(self):
        F = 6
        self.t = _grid(F)
        X = np.full((3, F), np.nan)
        Y = np.zeros((3, F))
        # slot 0: one fit at frame 0, then unseen (reach)
        X[0, 0] = 0.0
        # slot 1: fits at frames 0..5 at 10 m (the host of slot 2)
        X[1, :] = 10.0
        # slot 2: a fit at frame 0 under slot 1's icon, then unseen (crowd)
        X[2, 0] = 10.5
        self.X, self.Y = X, Y
        self.open = np.ones((3, F), bool)
        self.open[0, 5] = False
        self.seg = np.zeros(F, int)
        self.B = beliefs(self.t, X, Y, np.isfinite(X), self.open, self.seg,
                         r_fit=1.0, r_icon=0.5, v_max=10.0)

    def test_kinds(self):
        k = self.B["kind"]
        self.assertEqual(k[0].tolist(), [FIT, REACH, REACH, REACH, REACH, CLOSED])
        self.assertEqual(k[1].tolist(), [FIT] * 6)
        self.assertEqual(k[2].tolist(), [FIT] + [CROWD] * 5)

    def test_reach_radius_grows_at_v_max(self):
        # frame 3 is 0.3 s after the fix: 10 m/s * 0.3 s + r_fit
        self.assertAlmostEqual(self.B["R"][0, 3], 4.0)

    def test_containment(self):
        s = np.array([0, 0, 2, 2, 0])
        f = np.array([3, 3, 4, 4, 5])
        x = np.array([3.9, 4.1, 10.0 + 1.9, -100.0, 0.0])
        C = contains(self.B, s, f, x, np.zeros(5))
        self.assertEqual(C["region"].tolist(), [True, False, True, False, False])
        # the crowd core (host disc of 2 r_icon + r_fit = 2 m) holds 11.9 m
        self.assertEqual(C["core"].tolist()[2], True)

    def test_crowd_region_keeps_own_reach(self):
        # 0.4 s after the fix the member's reach is 5 m round 10.5: 6 m lies outside
        # the core (2 m round the host at 10) and inside the reach
        C = contains(self.B, np.array([2]), np.array([4]), np.array([6.0]), np.zeros(1))
        self.assertTrue(C["region"][0])
        self.assertFalse(C["core"][0])

    def test_unanchored_holds_everything(self):
        X = np.full((1, 3), np.nan)
        B = beliefs(_grid(3), X, np.zeros((1, 3)), np.zeros((1, 3), bool), np.ones((1, 3), bool),
                    np.zeros(3, int), r_fit=1.0, r_icon=0.5, v_max=10.0)
        self.assertEqual(B["kind"][0].tolist(), [UNANCHORED] * 3)
        self.assertTrue(contains(B, np.array([0]), np.array([1]), np.array([1e6]),
                                 np.array([0.0]))["region"][0])

    def test_fit_outside_open_slot_is_ignored(self):
        X = np.array([[0.0, 0.0]])
        op = np.array([[True, False]])
        B = beliefs(_grid(2), X, np.zeros((1, 2)), np.isfinite(X), op, np.zeros(2, int),
                    r_fit=1.0, r_icon=0.5, v_max=10.0)
        self.assertEqual(B["kind"][0].tolist(), [FIT, CLOSED])

    def test_storage_record(self):
        rec = storage_record(self.B, np.full((3, 6), -1))
        self.assertEqual(rec.shape, (6, 3))
        self.assertEqual(rec.dtype.itemsize, 24)


class UnwitnessedFitTest(unittest.TestCase):
    def test_unwitnessed_fit_keeps_the_witnessed_reach(self):
        # a witnessed fix at 0 m (frame 0), then a continuity fit at 20 m (frame 1):
        # the region is the 1 m fit disc round 20 m together with the reach from 0 m
        X = np.array([[0.0, 20.0, np.nan]])
        wit = np.array([[True, False, False]])
        B = beliefs(_grid(3), X, np.zeros((1, 3)), np.isfinite(X), np.ones((1, 3), bool),
                    np.zeros(3, int), r_fit=1.0, r_icon=0.5, v_max=10.0, wit=wit)
        self.assertEqual(B["kind"][0].tolist(), [FIT, FIT_UNNAMED, REACH])
        C = contains(B, np.array([0, 0, 0, 0]), np.array([1, 1, 1, 2]),
                     np.array([20.5, 1.5, 10.0, 2.9]), np.zeros(4))
        self.assertEqual(C["region"].tolist(), [True, True, False, True])
        self.assertEqual(C["core"].tolist()[:2], [True, False])
        # the reach at frame 2 grows from the witnessed fix, not the continuity fit
        self.assertAlmostEqual(B["ax"][0, 2], 0.0)
        a = region_area(B, np.array([0]), np.array([1]))
        self.assertAlmostEqual(a[0], math.pi * 1.0 + math.pi * 4.0)

    def test_no_witnessed_fix_holds_everything(self):
        X = np.array([[5.0]])
        B = beliefs(_grid(1), X, np.zeros((1, 1)), np.isfinite(X), np.ones((1, 1), bool),
                    np.zeros(1, int), r_fit=1.0, r_icon=0.5, v_max=10.0,
                    wit=np.zeros((1, 1), bool))
        self.assertTrue(contains(B, np.array([0]), np.array([0]), np.array([900.0]),
                                 np.zeros(1))["region"][0])

    def test_tolerance_widens_every_radius(self):
        X = np.array([[0.0]])
        B = beliefs(_grid(1), X, np.zeros((1, 1)), np.isfinite(X), np.ones((1, 1), bool),
                    np.zeros(1, int), r_fit=1.0, r_icon=0.5, v_max=10.0)
        q = (np.array([0]), np.array([0]), np.array([1.5]), np.zeros(1))
        self.assertFalse(contains(B, *q)["region"][0])
        self.assertTrue(contains(B, *q, tol=1.0)["region"][0])


class AreaTest(unittest.TestCase):
    def test_union_area_against_monte_carlo(self):
        rng = np.random.default_rng(0)
        pts = rng.uniform(-6, 6, (400000, 2))
        r1, r2, d = 3.0, 2.0, 2.5
        inside = (np.hypot(*pts.T) <= r1) | (np.hypot(pts[:, 0] - d, pts[:, 1]) <= r2)
        mc = inside.mean() * 144.0
        self.assertAlmostEqual(float(union_area(r1, r2, d)), mc, delta=0.15)
        self.assertAlmostEqual(float(union_area(3.0, 1.0, 0.5)), math.pi * 9, places=6)
        self.assertAlmostEqual(float(union_area(1.0, 1.0, 5.0)), 2 * math.pi, places=6)

    def test_region_area_by_kind(self):
        X = np.array([[0.0, np.nan]])
        B = beliefs(_grid(2), X, np.zeros((1, 2)), np.isfinite(X), np.ones((1, 2), bool),
                    np.zeros(2, int), r_fit=1.0, r_icon=0.5, v_max=10.0)
        a = region_area(B, np.array([0, 0]), np.array([0, 1]))
        self.assertAlmostEqual(a[0], math.pi)
        self.assertAlmostEqual(a[1], math.pi * 4.0)


class TruthSlotMapTest(unittest.TestCase):
    def test_elimination_of_one_unnamed(self):
        slots = [{"agent": a} for a in ("Jett", "Sova", None, "Omen", "Sage")]
        m, notes = truth_slot_map(slots, ["Jett", "Sova", "Reyna", "Omen", "Sage"])
        self.assertEqual(m["reyna"], 2)
        self.assertEqual(notes[0]["how"], "elimination")

    def test_two_unmapped_stay_unmapped(self):
        slots = [{"agent": a} for a in ("Jett", "Sova", None, None, "Sage")]
        m, notes = truth_slot_map(slots, ["Jett", "Sova", "Reyna", "Omen", "Sage"])
        self.assertNotIn("reyna", m)
        self.assertIn("unmapped_truth", notes[0])


def _session(F=10):
    t = _grid(F)
    return SimpleNamespace(fr_t=t, fr_f=np.arange(F),
                           rounds=[{"t_start_ms": 0.0}, {"t_start_ms": 500.0}],
                           deaths=[])


class LifecycleTest(unittest.TestCase):
    slots = [{"agent": a} for a in ("Jett", "Sova", "Clove", "Omen", "Sage")]

    def test_death_closes_until_next_round_and_revive_reopens(self):
        S = _session()
        S.deaths = [{"side": "ally", "victim": "Jett", "t_ms": 200.0},
                    {"side": "ally", "victim": "Clove", "t_ms": 100.0},
                    {"side": "ally", "victim": "Clove", "t_ms": 300.0, "is_revive": True},
                    {"side": "ally", "victim": None, "t_ms": 300.0},
                    {"side": "ally", "victim": "Sova", "t_ms": 300.0, "is_second_life": True},
                    {"side": "enemy", "victim": "Omen", "t_ms": 300.0}]
        L = lifecycle("s", S, self.slots)
        op = L["open"]
        self.assertEqual(op[0].tolist(), [True, True] + [False] * 3 + [True] * 5)
        self.assertEqual(op[2].tolist(), [True] + [False] * 2 + [True] * 7)
        self.assertTrue(op[1].all() and op[3].all())
        self.assertEqual(L["counts"]["maybe_dead_unnamed"], 1)
        self.assertEqual(L["counts"]["second_life"], 1)
        self.assertEqual(L["seg_start"].tolist(), [0] * 5 + [5] * 5)

    def test_death_keeps_its_own_round(self):
        # a round-1 death sampled at round 2's (score-increment) start closes nothing in round 2
        S = _session()
        S.rounds = [{"t_start_ms": 0.0, "round_no": 1}, {"t_start_ms": 500.0, "round_no": 2}]
        S.deaths = [{"side": "ally", "victim": "Jett", "t_ms": 500.0, "round_no": 1}]
        L = lifecycle("s", S, self.slots)
        self.assertTrue(L["open"][0].all())
        self.assertEqual(L["counts"]["death_past_its_round"], 1)


class BindTest(unittest.TestCase):
    def test_named_self_and_continuity(self):
        F = 6
        S = SimpleNamespace(fr_t=_grid(F), fr_f=np.arange(F))
        # entity 0 named Jett frames 0-2; entity 1 unnamed frames 3-5 near Jett's
        # last fix; entity 2 the self (player slot 1) frames 0-5; entity 3 named
        # Jett but overlapping entity 0 entirely (a conflict)
        f = [0, 1, 2, 3, 4, 5, 0, 1, 2, 3, 4, 5, 0, 1, 2]
        e = [0, 0, 0, 1, 1, 1, 2, 2, 2, 2, 2, 2, 3, 3, 3]
        x = [0, 0.5, 1, 1.2, 1.4, 1.6, 50, 50, 50, 50, 50, 50, 30, 30, 30]
        S.ob_f = np.asarray(f)
        S.ob_e = np.asarray(e)
        S.ob_x = np.asarray(x, float)
        S.ob_y = np.zeros(len(f))
        S.ob_self = np.asarray(e) == 2
        S.ent_ids = ["E0", "E1", "E2", "E3"]
        S.ents = {"E0": {"agent": "Jett"}, "E1": {"agent": None}, "E2": {"agent": "Sova"},
                  "E3": {"agent": "Jett"}}
        slots = [{"agent": a} for a in ("Jett", "Sova", "Clove", "Omen", "Sage")]
        op = np.ones((5, F), bool)
        R = bind_entities(S, slots, 1, op, np.zeros(F, int), lambda a, b: (a, b), 7.0, 1.0)
        self.assertEqual(R["X"][0].tolist(), [0, 0.5, 1, 1.2, 1.4, 1.6])
        self.assertEqual(R["X"][1].tolist(), [50.0] * 6)
        # the conflicting Jett entity binds by continuity to a free slot
        self.assertTrue(np.isfinite(R["X"][2:]).any())
        self.assertEqual(R["counts"]["named_conflict"], 1)
        self.assertEqual(R["counts"]["continuity_bound"], 2)


class FactTest(unittest.TestCase):
    def test_v_max_from_domain(self):
        self.assertAlmostEqual(v_max_m_s(), 7.425)


if __name__ == "__main__":
    unittest.main()
