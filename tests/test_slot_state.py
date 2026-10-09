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
                "params": {"v_max_m_s": 10.0}, "to_m": to_m, "m_per_px": 0.5,
                "windows": ss.round_windows(t, np.array([0.0, 150.0]))}

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

    def test_the_cursor_answers_what_the_one_off_query_answers(self):
        # instants before the first frame, on frames, between them and at
        # the round barrier at 150 ms, where frame 1 still answers
        G = self._G()
        cur = ss.RegionCursor(G)
        for t in (-5.0, 0.0, 20.0, 100.0, 149.0, 150.0, 199.0, 200.0, 260.0, 900.0):
            a, b = cur.at(t), ss.region_at(G, t)
            self.assertEqual((a["frame"], a["kind"]), (b["frame"], b["kind"]), t)
            np.testing.assert_array_equal(a["reach_m"], b["reach_m"])
        self.assertEqual(ss.region_at(G, 150.0)["frame"], 1)
        self.assertEqual(ss.region_at(G, 900.0)["frame"], 2)

    def test_the_cursor_refuses_to_move_back(self):
        cur = ss.RegionCursor(self._G())
        cur.at(120.0)
        with self.assertRaises(ValueError):
            cur.at(110.0)

    def test_a_round_barrier_bounds_the_search(self):
        # the frame axis cut at 150 ms: frames 0-1 before it, frame 2 after
        W = ss.round_windows(_grid(3), np.array([150.0]))
        self.assertEqual(W["lo"].tolist(), [0, 2, 3])
        self.assertEqual([v.size for v in W["t"]], [2, 1])


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


def _tracks(ents: list[dict], obs: list[tuple]) -> dict:
    """`stored_enemy_tracks`' arrays from track dicts and (t_ms, x, y, track) rows."""
    return {"ids": [f"E{i}" for i in range(len(ents))],
            "ents": [{"identity_status": "resolved", "reality_status": "accepted", "observations": 1, **e}
                     for e in ents],
            "t": np.asarray([o[0] for o in obs], float), "x": np.asarray([o[1] for o in obs], float),
            "y": np.asarray([o[2] for o in obs], float), "e": np.asarray([o[3] for o in obs], np.int64)}


def _to_m(px, py):
    return np.asarray(px, float) * 0.1, np.asarray(py, float) * 0.1


ENEMY = [{"key": f"s:enemy:slot:{k}", "agent": a}
         for k, a in enumerate(("Jett", "KAY_O", "Omen", "Sova", "Sage"))]


class EnemySlotTest(unittest.TestCase):
    """Enemy slots: the lifecycle, the binding and the belief law."""

    def _slots(self, F, deaths, rounds=({"t_start_ms": 0.0, "round_no": 1},)):
        S = SimpleNamespace(fr_t=_grid(F), rounds=list(rounds), deaths=deaths)
        return S, ss.player_lifecycle(S, ENEMY, side="enemy")

    def test_rows_are_the_enemy_five(self):
        rows = ss.enemy_rows(ENEMY)
        self.assertEqual(rows[1].key, ("player", "s:enemy:slot:1"))
        self.assertEqual({r.side for r in rows}, {"enemy"})

    def test_unanchored_then_fit_then_reach_then_closed(self):
        F = 8
        # Jett's track seen at frames 2 and 3; the death owner kills Jett at frame 6
        S, life = self._slots(F, [{"side": "enemy", "victim": "Jett", "t_ms": 600.0, "round_no": 1},
                                  {"side": "ally", "victim": "Omen", "t_ms": 100.0, "round_no": 1}])
        T = _tracks([{"agent": "Jett"}], [(200.0, 10.0, 0.0, 0), (300.0, 20.0, 0.0, 0)])
        bind = ss.bind_enemy_tracks(S.fr_t, T, ENEMY, life["open"], _to_m)
        self.assertEqual(bind["counts"]["bound"], 2)
        B = ss.beliefs(S.fr_t, bind["X"], bind["Y"], bind["has"], life["open"], life["seg_start"],
                       r_fit=1.0, r_icon=0.5, v_max=7.0, wit=bind["wit"])
        names = [ss.KINDS[int(k)] for k in B["kind"][0]]
        self.assertEqual(names, ["unanchored", "unanchored", "fit", "fit", "reach", "reach",
                                 "closed", "closed"])
        # reach grows from the last witnessed fix, at 2.0 m
        self.assertAlmostEqual(B["ax"][0, 5], 2.0)
        self.assertAlmostEqual(B["R"][0, 5], 7.0 * 0.2 + 1.0)
        # an ally's death closes no enemy slot; Omen's enemy slot stays open
        self.assertTrue(life["open"][2].all())
        self.assertEqual([ss.KINDS[int(k)] for k in set(B["kind"][2])], ["unanchored"])

    def test_state_resets_at_the_round_barrier(self):
        F = 8
        rounds = ({"t_start_ms": 0.0, "round_no": 1}, {"t_start_ms": 400.0, "round_no": 2})
        S, life = self._slots(F, [{"side": "enemy", "victim": "Jett", "t_ms": 300.0, "round_no": 1}],
                              rounds)
        # a death in round 1 closes the slot only to the round's end
        self.assertEqual(life["open"][0].tolist(), [True] * 3 + [False] + [True] * 4)
        T = _tracks([{"agent": "Omen"}], [(100.0, 10.0, 0.0, 0)])
        bind = ss.bind_enemy_tracks(S.fr_t, T, ENEMY, life["open"], _to_m)
        B = ss.beliefs(S.fr_t, bind["X"], bind["Y"], bind["has"], life["open"], life["seg_start"],
                       r_fit=1.0, r_icon=0.5, v_max=7.0, wit=bind["wit"])
        self.assertEqual([ss.KINDS[int(k)] for k in B["kind"][2]],
                         ["unanchored", "fit", "reach", "reach"] + ["unanchored"] * 4)

    def test_no_name_is_chosen_outside_the_arbiter(self):
        F = 4
        S, life = self._slots(F, [])
        T = _tracks([{"agent": "KAY/O"},                                     # the arbiter's spelling
                     {"agent": None, "identity_status": "abstained"},
                     {"agent": "Jett", "identity_status": "contested"},
                     {"agent": "Reyna"},                                     # not in the enemy five
                     {"agent": "Sova", "reality_status": "refused"}],
                    [(0.0, 1.0, 1.0, 0), (0.0, 2.0, 2.0, 1), (100.0, 3.0, 3.0, 2), (100.0, 4.0, 4.0, 3),
                     (200.0, 5.0, 5.0, 4), (200.0, 6.0, 6.0, -1), (900.0, 7.0, 7.0, 0)])
        bind = ss.bind_enemy_tracks(S.fr_t, T, ENEMY, life["open"], _to_m)
        c = bind["counts"]
        self.assertEqual((c["bound"], c["track_unnamed"], c["agent_not_in_lineup"], c["track_refused"],
                          c["no_track"], c["off_frame_axis"]), (1, 2, 1, 1, 1, 1))
        # only KAY/O's track binds, to the slot the lineup's verdict names KAY_O
        self.assertEqual(np.flatnonzero(bind["has"].any(axis=1)).tolist(), [1])
        # the module calls no identity rule: names come from stored verdicts only;
        # `child_identity` alone publishes the ability nodes' claims to the arbiter
        # [owns:ability-owner], each naming its owner slot's verdict
        import inspect
        src = Path(ss.__file__).read_text(encoding="utf-8").replace(
            inspect.getsource(ss.child_identity), "")
        for rule in ("adjudicate_agent_identity", "claims_from_ally_icons", "identity_claim("):
            self.assertNotIn(rule, src)

    def test_two_tracks_on_one_slot_frame_keep_the_longer(self):
        F = 3
        S, life = self._slots(F, [])
        T = _tracks([{"agent": "Sova", "observations": 2}, {"agent": "Sova", "observations": 9}],
                    [(100.0, 1.0, 0.0, 0), (100.0, 50.0, 0.0, 1)])
        bind = ss.bind_enemy_tracks(S.fr_t, T, ENEMY, life["open"], _to_m)
        self.assertEqual((bind["counts"]["bound"], bind["counts"]["duplicate"]), (1, 1))
        self.assertAlmostEqual(bind["X"][3, 1], 5.0)

    def test_the_law_runs_per_side(self):
        # an ally fit beside an enemy slot's last fix is no crowd host for it
        t = _grid(3)
        one = np.ones((1, 3), bool)
        Xa = np.array([[0.0, 0.2, 0.4]])
        Xe = np.array([[0.0, np.nan, np.nan]])
        Ba = ss.beliefs(t, Xa, Xa * 0, np.isfinite(Xa), one, np.zeros(3, int), r_fit=1.0, r_icon=0.5, v_max=7.0)
        Be = ss.beliefs(t, Xe, Xe * 0, np.isfinite(Xe), one, np.zeros(3, int), r_fit=1.0, r_icon=0.5, v_max=7.0)
        B = ss.join_beliefs([Ba, Be])
        self.assertEqual([ss.KINDS[int(k)] for k in B["kind"][1]], ["fit", "reach", "reach"])
        self.assertEqual(B["kind"].shape, (2, 3))
        self.assertTrue((B["host"][1] == -1).all())


class LaneRenameTest(unittest.TestCase):
    def test_the_tray_lane_cannot_pass_for_the_slot_model(self):
        from reticle.entity_contract import STATE_VOCABULARY
        from reticle.entity_events import LANE
        self.assertIn("ability_tray", LANE)
        self.assertNotIn("slot_state", LANE)
        self.assertIn("ability_tray", STATE_VOCABULARY)
        self.assertNotIn("slot_state", STATE_VOCABULARY)


class SpawnAnchorTest(unittest.TestCase):
    """A slot with no witnessed fix this round holds its side's spawn disc,
    grown by reach from the barrier drop, until the disc covers the map."""

    DISCS = {"attack": (0.0, 0.0, 5.0, 60.0), "defence": (100.0, 0.0, 6.0, 60.0)}

    def _beliefs(self, X, seg_start):
        F = X.shape[1]
        Y = np.where(np.isfinite(X), 0.0, np.nan)
        return ss.beliefs(_grid(F, 1000.0), X, Y, np.isfinite(X), np.ones(X.shape, bool),
                          seg_start, r_fit=1.0, r_icon=0.5, v_max=7.0)

    def test_anchors_at_round_start(self):
        F = 12
        t = _grid(F, 1000.0)
        B = self._beliefs(np.full((1, F), np.nan), np.zeros(F, np.int64))
        A, n = ss.spawn_anchor(B, t, np.zeros(F, np.int64), np.array([0]), np.array([2000.0]),
                               self.DISCS, r_fit=1.0, v_max=7.0)
        names = [ss.KINDS[int(k)] for k in A["kind"][0]]
        # held in spawn until the drop at 2 s, then 7 m/s until 5 + 1 + 7 dt reaches 60 m
        self.assertEqual(names[:10], ["spawn"] * 10)
        self.assertEqual(names[10:], ["unanchored"] * 2)
        np.testing.assert_allclose(A["R"][0, :4], [6.0, 6.0, 6.0, 13.0])
        self.assertEqual((A["ax"][0, 0], A["ay"][0, 0]), (0.0, 0.0))
        C = ss.contains(A, np.array([0, 0]), np.array([0, 0]), np.array([5.5, 30.0]), np.zeros(2))
        self.assertEqual(C["region"].tolist(), [True, False])
        self.assertAlmostEqual(float(ss.region_area(A, np.array([0]), np.array([0]))[0]), math.pi * 36.0)
        self.assertEqual(n["spawn"], 10)
        self.assertEqual(n["past_map"], 2)
        self.assertEqual(B["kind"][0, 0], ss.UNANCHORED)       # the input is left alone

    def test_the_anchor_resets_at_each_round(self):
        F = 8
        t = _grid(F, 1000.0)
        X = np.full((1, F), np.nan)
        X[0, 1] = 40.0                                         # a witnessed fix in round 0
        seg = np.array([0, 0, 0, 0, 1, 1, 1, 1])
        B = self._beliefs(X, np.array([0, 0, 0, 0, 4, 4, 4, 4]))
        A, _ = ss.spawn_anchor(B, t, seg, np.array([0, 1]), np.array([0.0, 5000.0]),
                               self.DISCS, r_fit=1.0, v_max=7.0)
        names = [ss.KINDS[int(k)] for k in A["kind"][0]]
        self.assertEqual(names, ["spawn", "fit", "reach", "reach", "spawn", "spawn", "spawn", "spawn"])
        # round 1 is played on defence: its disc and its own drop
        self.assertEqual(A["ax"][0, 4], 100.0)
        np.testing.assert_allclose(A["R"][0, 4:], [7.0, 7.0, 14.0, 21.0])
        np.testing.assert_allclose(A["R"][0, 2], 7.0 + 1.0)     # reach from the fix, untouched

    def test_side_swaps_at_half_and_in_overtime(self):
        rounds = [{"score_us": n - 1, "score_them": 0} for n in (1, 12, 13, 24, 25, 26)]
        team, why = ss.team_sides(rounds, "attack")
        self.assertEqual([ss.SIDE_CODES[k] for k in team],
                         ["attack", "attack", "defence", "defence", "attack", "defence"])
        team, why = ss.team_sides(rounds + [{"score_us": None, "score_them": None}], None)
        self.assertTrue((team == -1).all())
        self.assertEqual(why["starting_side_unread"], 7)

    def test_an_unread_side_leaves_the_slot_unanchored(self):
        F = 3
        B = self._beliefs(np.full((1, F), np.nan), np.zeros(F, np.int64))
        A, n = ss.spawn_anchor(B, _grid(F, 1000.0), np.zeros(F, np.int64), np.array([-1]),
                               np.array([0.0]), self.DISCS, r_fit=1.0, v_max=7.0)
        self.assertTrue((A["kind"] == ss.UNANCHORED).all())
        self.assertEqual(n["side_unread"], 3)

    def test_footprints_come_from_the_callout_volumes(self):
        from reticle import map_regions as mr
        inv = np.tile(np.eye(4), (2, 1, 1))
        reg = mr.Regions(inv, [[0, 0, 0], [50, 50, 0]], [[10, 20, 5], [60, 70, 5]],
                         [{"region": "Spawn", "super": "Attacker Side"},
                          {"region": "Site", "super": "A"}])
        fp = mr.spawn_footprints(reg)
        self.assertEqual(set(fp), {"attack"})
        np.testing.assert_allclose(sorted(map(tuple, fp["attack"])),
                                   [(0, 0), (0, 20), (10, 0), (10, 20)])

    def test_no_capture_pixels_are_read(self):
        # the anchor's code names no capture, crop or session-pixel source
        import ast
        import inspect
        banned = {"barriers", "roi_cache", "decode", "VideoCapture", "imread", "clip_preflight",
                  "path_of", "crop", "read_frame"}
        for fn in (ss.spawn_discs, ss.round_sides, ss.team_sides, ss.spawn_anchor, ss.spawn_context):
            names = {n.id for n in ast.walk(ast.parse(inspect.getsource(fn)))
                     if isinstance(n, ast.Name)}
            names |= {n.attr for n in ast.walk(ast.parse(inspect.getsource(fn)))
                      if isinstance(n, ast.Attribute)}
            names |= {a.name for n in ast.walk(ast.parse(inspect.getsource(fn)))
                      if isinstance(n, ast.ImportFrom) for a in n.names}
            self.assertFalse(names & banned, (fn.__name__, names & banned))

    @unittest.skipUnless((STORE / "sightlines" / "choice.json").is_file(), "no sightline tables")
    def test_spawn_discs_read_no_capture(self):
        import cv2
        from unittest import mock

        from reticle import barriers
        boom = mock.Mock(side_effect=AssertionError("a capture was read"))
        with mock.patch.object(cv2, "VideoCapture", boom), mock.patch.object(cv2, "imread", boom), \
                mock.patch.object(barriers, "load", boom):
            D = ss.spawn_discs("ascent", STORE)
        self.assertEqual(set(D["discs"]), {"attack", "defence"})
        self.assertEqual(D["provenance"]["owner"], "callout-region")
        for cx, cy, r, r_map in D["discs"].values():
            self.assertTrue(0.0 < r < r_map)


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
        rec = ss.frame_record(G["B"], G["obs"], G["t_ms"])
        self.assertEqual(rec.shape, (G["t_ms"].size, 10))
        self.assertEqual([r.side for r in G["rows"]], ["ally"] * 5 + ["enemy"] * 5)
        # every stored enemy observation is bound or counted by its reason
        e = G["enemy"]["bind"]["counts"]
        self.assertEqual(sum(e[r] for r in ss.ENEMY_FIT_REASONS), e["observations"])
        self.assertEqual(int(G["enemy"]["bind"]["has"].sum()), e["bound"])
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
