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

    def test_off_map_self_fit_binds_no_spectated_slot(self):
        # the player is dead and the tray names slot 3, but the self fit sits
        # on background art off the map
        F = 2
        frames = [[(5.0, 5.0, Z, (), True)], [(90.0, 90.0, Z, ("off_map",), True)]]
        open_ = np.ones((5, F), bool)
        open_[0, :] = False
        out = _bind(_fits(frames, F), F, open_=open_, spect=np.array([3, 3]))
        self.assertEqual(out["how"][3, 0], eb.HOW_SPECTATE)
        self.assertFalse(out["has"][:, 1].any())
        self.assertEqual(out["np_bucket"][1], "off_map")
        self.assertEqual(out["counts"]["self_off_map"], 1)


def _same_up_to(test, full, cut, keys_full, keys_cut, n):
    """The published state of frames [0, n) agrees: X, Y, has, how, wit and
    each bound fit's observation key."""
    for name in ("has", "how", "wit"):
        np.testing.assert_array_equal(full[name][:, :n], cut[name][:, :n], err_msg=name)
    for name in ("X", "Y"):
        np.testing.assert_array_equal(full[name][:, :n], cut[name][:, :n], err_msg=name)
    kf = np.where(full["obs"][:, :n] >= 0, keys_full[np.maximum(full["obs"][:, :n], 0)], None)
    kc = np.where(cut["obs"][:, :n] >= 0, keys_cut[np.maximum(cut["obs"][:, :n], 0)], None)
    test.assertTrue((kf == kc).all(), "observation keys differ")


class SyntheticTruncationTest(unittest.TestCase):
    """Causality on synthetic fits: the fits after frame `n` change nothing
    published at or before it."""

    def test_later_fits_change_no_earlier_frame(self):
        rng = np.random.default_rng(7)
        F, n = 120, 70
        frames = []
        for k in range(F):
            fr = [(float(10 * s + rng.normal(0, 0.3)), float(rng.normal(0, 0.3)),
                   _llr(s, float(rng.uniform(-1, 2))), (), False) for s in range(1, 5)]
            fr += [(float(rng.uniform(0, 60)), float(rng.uniform(-20, 20)), Z,
                    ("ping",) if rng.random() < 0.5 else (), False)]
            fr.append((float(rng.uniform(0, 5)), 0.0, Z, (), True))
            frames.append(fr)
        open_ = np.ones((5, F), bool)
        open_[0, 40:] = False                              # the player dies
        spect = np.where(np.arange(F) >= 40, 2, -1)
        full = _bind(_fits(frames, F), F, open_=open_, spect=spect)
        cut_frames = frames[:n + 1] + [[] for _ in range(F - n - 1)]
        cut = _bind(_fits(cut_frames, F), F, open_=open_, spect=spect)
        keys = lambda fr: np.asarray([f"{k}:{j}" for k, x in enumerate(fr) for j in range(len(x))],
                                     object)
        _same_up_to(self, full, cut, keys(frames), keys(cut_frames), n + 1)


@unittest.skipUnless((STORE / "events" / "ally_icon" / f"{DEV}.jsonl").is_file(),
                     "no stored ally_icon rows for the dev session")
class StoredTruncationTest(unittest.TestCase):
    """Causality on `a06f04a0059f`'s stored rows: the binding's own inputs
    (the `ally_icon`, `ping`, `spike` and `tray_kit` rows) cut at time T
    publish the same X, Y, has, how, wit and observation keys for every frame
    up to T as the whole session does.

    T lies 50 ms before a teammate's `tray_kit` span starts, where the
    owner's default `KIT_LOOKAHEAD_MS` would read the span early. The cut
    span rows keep their stored agent (pooled over the whole span, the
    disclosed post-round verdict); the lineup and the slots' lifecycle come
    from their owners, uncut."""

    def test_rows_after_t_change_no_earlier_frame(self):
        from unittest import mock

        from prototypes import entity_state as es
        import crowd_region as v1                       # on the path entity_state sets
        from reticle.adjudication.tray_kit import stored_kit_witness
        from reticle.agent_names import same_agent
        from reticle.store import Store

        sid = DEV
        S = v1.Session(sid)
        L = es.lineup_slots(sid)
        (_, to_m, m_per_px), _ = es.world_frame(sid)
        v_max = es.v_max_m_s()
        r_icon = float(S.r) * m_per_px
        r_fit = r_icon + v_max * float(np.median(np.diff(S.fr_t))) / 1000.0
        life = es.lifecycle(sid, S, L["slots"])
        read = Store.read_events
        w = stored_kit_witness(read(Store(STORE), "tray_kit", sid), agent=L["player_agent"])
        mates = [s for s in w["spans"] if same_agent(s[2], L["player_agent"]) is False
                 and s[0] > S.fr_t[0] + 60_000]
        self.assertTrue(mates, "no teammate tray_kit span to cut before")
        T = mates[len(mates) // 2][0] - 50.0
        t_of = dict(zip(S.fr_f.tolist(), S.fr_t.tolist()))

        def cut_rows(store, kind, session_id):
            rows = read(store, kind, session_id)
            if session_id != sid:
                return rows
            if kind == "ally_icon":
                return [r for r in rows if "frame_idx" not in r
                        or t_of.get(int(r["frame_idx"]), np.inf) <= T]
            if kind in ("ping", "spike"):
                return [r for r in rows if "t_ms" not in r or float(r["t_ms"]) <= T]
            if kind == "tray_kit":
                out = []
                for r in rows:
                    if r.get("kind") == "span":
                        if float(r["t_first_ms"]) > T:
                            continue
                        r = {**r, "t_last_ms": min(float(r["t_last_ms"]), T)}
                    elif "t_ms" in r and float(r["t_ms"]) > T:
                        continue
                    out.append(r)
                return out
            return rows

        def run():
            fits = eb.load_fits(sid, S, L["slots"], L["player_slot"], to_m, float(S.r))
            spect = eb.spectated_slots(sid, S, L["slots"], L["player_agent"])
            b = eb.causal_bind(S.fr_t, fits, life["open"], life["seg_start"], L["player_slot"],
                               spect["slot"], r_fit=r_fit, v_max=v_max,
                               log_area=math.log(fits["map_px"] * m_per_px ** 2),
                               r_dup_m=2.0 * r_icon, margin_min=fits["margin_min"])
            return b, fits["key"], spect

        full, kf, sf = run()
        with mock.patch.object(Store, "read_events", cut_rows):
            cut, kc, sc = run()
        n = int(np.searchsorted(S.fr_t, T, side="right"))
        np.testing.assert_array_equal(sf["slot"][:n], sc["slot"][:n])
        _same_up_to(self, full, cut, kf, kc, n)
        self.assertIn("post-round", sf["rests_on"])


@unittest.skipUnless((STORE / "events" / "ally_icon" / f"{DEV}.jsonl").is_file(),
                     "no stored ally_icon rows for the dev session")
class StoredRowRegressionTest(unittest.TestCase):
    """`a06f04a0059f` (dev) from stored rows, against the run of 2026-10-04
    (entity-binding-0.1.1 on ally-icon-0.11.0, after the causal fix: no kit
    lookahead, off-map self fits refused): 57430 fits, 54423 bound (54474
    before the fix), the rest explained, none bound twice."""

    def test_dev_session_binding(self):
        from prototypes import entity_state as es
        G = es.build_slots(DEV, binding="causal")
        if G["S"].ally_icon_version != "ally-icon-0.11.0":
            self.skipTest(f"ally_icon is {G['S'].ally_icon_version}; the counts are 0.11.0's")
        c = G["bind"]["counts"]
        self.assertEqual(c["fit_bound_twice"], 0)
        self.assertEqual(c["fits"], 57430)
        self.assertEqual(c["fits_bound"], 54423)
        self.assertEqual(c["fits_bound"] + sum(G["bind"]["np_by_reason"].values()), c["fits"])
        self.assertEqual(G["bind"]["np_by_reason"]["ability_glyph"], 2050)


if __name__ == "__main__":
    unittest.main()
