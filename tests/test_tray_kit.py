"""The tray kit witness: the icon matcher (`tray_icons`), the staged reading
and the spans (`adjudication.tray_kit`), and its two consumers, the tray gate
(`ability_timeline.player_tray_casts`) and the kit state
(`adjudication.ability_state`), on synthetic icons and rounds."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle import tray, tray_icons
from reticle.ability_timeline import kit_windows, player_tray_casts
from reticle.adjudication import ability_state as st
from reticle.adjudication import tray_kit as tk

PX = tray_icons.ICON_PX


def _shape(kind: str, px: int = 128) -> np.ndarray:
    """A white glyph's alpha channel: a ring, a bar or a cross."""
    a = np.zeros((px, px), np.float32)
    c = px // 2
    if kind == "ring":
        cv2.circle(a, (c, c), px // 3, 1.0, px // 10)
    elif kind == "bar":
        cv2.rectangle(a, (px // 5, c - px // 10), (4 * px // 5, c + px // 10), 1.0, -1)
    else:
        cv2.line(a, (px // 5, px // 5), (4 * px // 5, 4 * px // 5), 1.0, px // 10)
        cv2.line(a, (4 * px // 5, px // 5), (px // 5, 4 * px // 5), 1.0, px // 10)
    return a


def _tpl(kind: str) -> np.ndarray:
    return cv2.resize(_shape(kind), (PX, PX), interpolation=cv2.INTER_AREA)


def _patch(kind: str, gain: float, offset: float, shift=(0, 0), seed=0) -> np.ndarray:
    """The icon composited over a noisy background: grey = gain * alpha + offset."""
    rng = np.random.default_rng(seed)
    n = PX + 2 * tray_icons.SHIFT_PX
    out = offset + rng.normal(0, 3, (n, n)).astype(np.float32)
    y0, x0 = tray_icons.SHIFT_PX + shift[1], tray_icons.SHIFT_PX + shift[0]
    out[y0:y0 + PX, x0:x0 + PX] += gain * _tpl(kind)
    return out.astype(np.float32)


class Matcher(unittest.TestCase):
    def test_lit_and_dim_icons_both_match_their_template(self):
        for gain in (200.0, 40.0):
            score, off = tray_icons.match_icon(_patch("ring", gain, 30.0, shift=(3, -2)), _tpl("ring"))
            self.assertGreater(score, 0.9, gain)
            self.assertEqual(off, (3, -2))

    def test_another_glyph_scores_lower(self):
        p = _patch("ring", 150.0, 40.0)
        self.assertGreater(tray_icons.match_icon(p, _tpl("ring"))[0] - tray_icons.match_icon(p, _tpl("bar"))[0], 0.3)

    def test_a_flat_patch_holds_no_icon(self):
        n = PX + 2 * tray_icons.SHIFT_PX
        self.assertEqual(tray_icons.match_icon(np.full((n, n), 90, np.float32), _tpl("ring")),
                         (0.0, (0, 0)))

    def test_slot_scores_read_each_slot_at_the_tray_geometry(self):
        frame = np.full((1080, 1920, 3), 25, np.uint8)
        kinds = ["ring", "bar", "cross", "ring"]
        half = PX // 2
        for k, kind in enumerate(kinds):
            cx = tray.SLOT_X0 + tray.SLOT_DX * k
            y0, x0 = tray_icons.ICON_CY - half, cx - half
            roi = frame[y0:y0 + PX, x0:x0 + PX].astype(np.float32)
            roi += 180.0 * _tpl(kind)[:, :, None]
            frame[y0:y0 + PX, x0:x0 + PX] = np.clip(roi, 0, 255).astype(np.uint8)
        icons = {"Right": {key: _tpl(kind) for key, kind in zip(tray_icons.SLOT_KEYS, kinds)},
                 "Wrong": {key: _tpl(kind) for key, kind in
                           zip(tray_icons.SLOT_KEYS, ["bar", "cross", "ring", "bar"])},
                 "Short": {"C": _tpl("ring")}}
        sc = tray_icons.slot_scores(tray_icons.slot_patches(frame), icons, ["Right", "Wrong", "Short"])
        self.assertEqual(sc.shape, (3, 4))
        self.assertTrue((sc[0] > 0.9).all())
        self.assertTrue((sc[0] > sc[1]).all())
        self.assertTrue(np.isnan(sc[2, 1:]).all())

    def test_catalogue_reads_the_reference_file_and_renames_kayo(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "reference" / "icons").mkdir(parents=True)
            big = np.zeros((512, 512, 4), np.uint8)
            big[:, :, :3] = 255
            big[:, :, 3] = (cv2.resize(_shape("bar"), (512, 512)) * 255).astype(np.uint8)
            cv2.imwrite(str(root / "reference" / "icons" / "k.png"), big)
            ref = {"agents": {"KAY/O": {"abilities": [
                {"key": "C", "icon": {"file": "icons\\k.png"}},
                {"key": "P", "icon": {"file": "icons\\k.png"}}]}}}
            (root / "reference" / "abilities.json").write_text(json.dumps(ref), encoding="utf-8")
            cat = tray_icons.catalogue(root)
            self.assertEqual(list(cat), ["KAY_O"])
            self.assertEqual(list(cat["KAY_O"]), ["C"])
            icons = tray_icons.load_slot_icons(root)
            self.assertEqual(icons["KAY_O"]["C"].shape, (PX, PX))
            self.assertEqual(len(tray_icons.reference_key(root)), 16)


def _sets(player="Iso", allies=("Iso", "Omen", "Sage", "Phoenix", "Reyna"), rivals=(), blind=0):
    return {"player": player, "player_entity": "s:ally:slot:0" if player else None,
            "allies": list(allies), "rivals": list(rivals), "blind": blind,
            "ally_entities": [f"s:ally:slot:{i}" for i in range(5)]}


def _scorer(fits: dict):
    """A scorer giving each agent the same score on all four slots."""
    return lambda agents: np.array([[fits.get(a, 0.1)] * 4 for a in agents], float)


ALL = ["Iso", "Omen", "Sage", "Phoenix", "Reyna", "Jett", "Viper"]


class Reading(unittest.TestCase):
    def test_the_player_kit_is_the_prediction(self):
        r = tk.read_sample(True, _scorer({"Iso": 0.9, "Omen": 0.3}), _sets(), ALL)
        self.assertEqual((r["kit_agent"], r["set"]["name"]), ("Iso", "player"))
        self.assertEqual(r["set"]["depends_on"], ["s:ally:slot:0"])
        self.assertEqual(r["tried"], [])

    def test_a_spectated_kit_widens_to_the_ally_side_and_says_so(self):
        r = tk.read_sample(True, _scorer({"Iso": 0.3, "Omen": 0.9, "Sage": 0.4}), _sets(), ALL)
        self.assertEqual((r["kit_agent"], r["set"]["name"]), ("Omen", "allies"))
        self.assertEqual(r["tried"], [{"set": "player", "best": "Iso", "fit": 0.3}])
        self.assertEqual(len(r["set"]["depends_on"]), 5)
        self.assertEqual(r["kit"]["runner_up"], "Sage")

    def test_refusals_keep_their_reasons(self):
        self.assertEqual(tk.read_sample(True, _scorer({}), None, ALL)["reason"], "no_lineup")
        self.assertEqual(tk.read_sample(False, _scorer({}), _sets(), ALL)["reason"],
                         "tray_not_drawn")
        close = tk.read_sample(True, _scorer({"Omen": 0.8, "Sage": 0.75}), _sets(), ALL)
        self.assertEqual((close["kit_agent"], close["reason"]), (None, "margin_below"))
        dim = tk.read_sample(True, _scorer({}), _sets(), ALL)
        self.assertEqual((dim["reason"], dim["set"]["name"]), ("icons_dim", "all"))
        mid = tk.read_sample(True, _scorer({a: 0.45 for a in ALL[:3]} | {"Viper": 0.55}),
                             _sets(), ALL)
        self.assertEqual(mid["kit_agent"], "Viper")
        self.assertEqual(mid["set"]["why"], "widened: no kit of the ally side fits")
        low = tk.read_sample(True, lambda ag: np.array([[0.6, 0.6, 0.1, 0.1]] * len(ag)),
                             _sets(), ALL)
        self.assertEqual(low["reason"], "fit_below")

    def test_a_rival_can_take_the_match_but_never_the_name(self):
        r = tk.read_sample(True, _scorer({"Jett": 0.9, "Omen": 0.4}),
                           _sets(allies=("Iso", "Omen", "Sage", "Phoenix"), rivals=("Jett",)), ALL)
        self.assertEqual((r["kit_agent"], r["reason"]), (None, "rival_best"))

    def test_a_blind_slot_skips_the_ally_stage(self):
        r = tk.read_sample(True, _scorer({"Iso": 0.2, "Jett": 0.9}), _sets(blind=1), ALL)
        self.assertEqual((r["kit_agent"], r["set"]["name"]), ("Jett", "all"))
        self.assertTrue(r["set"]["why"].startswith("widened"))

    def test_candidate_sets_come_from_the_lineup_verdicts(self):
        lineup = {"sides": {"ally": [{"slot": i, "best_guess": g} for i, g in
                                     enumerate(["Iso", "Omen", "Sage", "Jett", None])]},
                  "identity_claims": [{"entity_id": "s:ally:slot:0", "agent": "Iso",
                                       "channel": "player_agent", "depends_on": ["s:player"],
                                       "evidence": {"slot": 0}}],
                  "agent_identity": [{"entity_id": f"s:ally:slot:{i}", "agent": a,
                                      "status": "resolved"} for i, a in
                                     enumerate(["Iso", "Omen", "Sage"])]
                  + [{"entity_id": "s:player", "agent": "Iso", "status": "resolved",
                      "reason": None, "channels": ["ability_tray"], "agents_seen": ["Iso"],
                      "independent_channels": 1, "by_channel": {}}]}
        sets = tk.candidate_sets(lineup, "s")
        self.assertEqual((sets["player"], sets["allies"], sets["rivals"], sets["blind"]),
                         ("Iso", ["Iso", "Omen", "Sage"], ["Jett"], 1))
        self.assertIsNone(tk.candidate_sets(None, "s"))


def _smp(t, cs, agent, set_name="player"):
    if agent is None:
        return {"t_ms": float(t), "cache_span": cs, "drawn": False, "kit_agent": None,
                "reason": "tray_not_drawn", "set": None}
    return {"t_ms": float(t), "cache_span": cs, "drawn": True, "kit_agent": agent,
            "reason": None,
            "set": {"name": set_name, "agents": [agent], "why": "test",
                    "depends_on": ["s:ally:slot:0"]},
            "slots": [], "kit": {"best": agent, "fit": 0.9, "runner_up": None,
                                 "runner_up_fit": None, "margin": None}, "tried": []}


class Spans(unittest.TestCase):
    def test_a_short_run_between_two_runs_of_one_kit_joins_them(self):
        got = tk._runs([(0, "A"), (1, "A"), (2, "B"), (3, "A"), (4, "A"), (5, "B"), (6, "B")])
        self.assertEqual(got, [["A", [0, 1, 2, 3, 4]], ["B", [5, 6]]])

    def _rows(self):
        seq = (["Iso"] * 5 + ["Omen"] + ["Iso"] * 3 + [None] * 2 + ["Omen"] * 4
               + ["Sage"] * 3 + ["Iso"] * 3)
        samples = [_smp(1000 * i, 0, a) for i, a in enumerate(seq)]
        samples += [_smp(100000 + 1000 * i, 1, a) for i, a in enumerate(["Iso"] * 3 + ["Omen"])]
        return tk.adjudicate("s", samples, _sets(), {"test": "1"}, {"step_s": 1.0})

    def test_change_and_return_are_stored_with_their_times(self):
        out = self._rows()
        rows = out["rows"]
        spans = [r for r in rows if r["kind"] == "span"]
        self.assertEqual([(r["agent"], r["own"], r["claims"]) for r in spans],
                         [("Iso", True, 9), ("Omen", False, 4), ("Sage", False, 3),
                          ("Iso", True, 3), ("Iso", True, 3), ("Omen", False, 1)])
        self.assertEqual(spans[0]["votes"], {"Iso": 8, "Omen": 1})
        changes = [r for r in rows if r["kind"] == "kit_change"]
        returns = [r for r in rows if r["kind"] == "kit_return"]
        self.assertEqual([(c["kit_change_ms"], c["since_ms"], c["agent"]) for c in changes],
                         [(11000.0, 8000.0, "Omen")])
        self.assertEqual([(r["t_ms"], r["since_ms"]) for r in returns], [(18000.0, 17000.0)])
        self.assertEqual(rows[0]["kit_changes"], 1)
        self.assertEqual(len(out["claims"]), sum(r["claims"] for r in spans))
        self.assertTrue(all(c["depends_on"] == ["s:ally:slot:0"] for c in out["claims"]))

    def test_the_stored_witness_says_why_it_is_not_used(self):
        rows = self._rows()["rows"]
        got = tk.stored_kit_witness(rows)
        self.assertEqual((got["kit_changes_ms"], got["kit_returns_ms"], got["reason"]),
                         ([11000.0], [18000.0], None))
        self.assertEqual(got["other_spans"][0], (11000.0, 14000.0, "Omen"))
        self.assertEqual(tk.stored_kit_witness([])["reason"], "no_rows")
        stale = [{**rows[0], "tray_kit_version": "tray-kit-0.0.1"}] + rows[1:]
        self.assertEqual(tk.stored_kit_witness(stale)["reason"], "stale:tray-kit-0.0.1")
        self.assertEqual(tk.stored_kit_witness(rows, agent="Omen")["reason"],
                         "player_agent_moved")
        self.assertEqual(tk.spectated_agent(12500.0, got["other_spans"]), "Omen")
        self.assertIsNone(tk.spectated_agent(9000.0, got["other_spans"]))


ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 60000.0, "t_close_ms": 65000.0}]


def _drop(t, slot="E", f=1.0, to=0.0):
    return {"t_ms": float(t), "slot": slot, "from": f, "to": to, "suspect": False,
            "forced": False, "cooccur": False, "across_gap": False}


class Consumers(unittest.TestCase):
    def test_kit_windows_carry_the_first_change_and_the_return_after_it(self):
        k = kit_windows(ROUNDS, [], kit_changes_ms=[40000.0, 30000.0],
                        kit_returns_ms=[20000.0, 50000.0])[0]
        self.assertEqual((k["kit_change_ms"], k["kit_return_ms"], k["kit_end_ms"]),
                         (30000.0, 50000.0, None))
        self.assertIsNone(kit_windows(ROUNDS, [])[0]["kit_change_ms"])

    def test_the_gate_refuses_after_a_kit_change_and_names_the_killfeed_first(self):
        drops = [_drop(10000), _drop(21000, "C"), _drop(35000, "Q"), _drop(52000, "C")]
        live = lambda t: "round_live"
        rows = player_tray_casts([dict(d) for d in drops], live, ROUNDS, [],
                                 kit_changes_ms=[30000.0], kit_returns_ms=[50000.0])
        self.assertEqual([r["reason"] for r in rows], [None, None, "after_kit_change", None])
        self.assertEqual(rows[2]["kit_change_ms"], 30000.0)
        rows = player_tray_casts([dict(d) for d in drops], live, ROUNDS, [20000.0],
                                 kit_changes_ms=[30000.0])
        self.assertEqual([r["reason"] for r in rows],
                         [None, "after_player_death", "after_player_death",
                          "after_player_death"])
        self.assertEqual([r["reason"] for r in player_tray_casts(
            [dict(d) for d in drops], live, ROUNDS, [])], [None] * 4)

    def test_the_state_reads_the_spectated_kit_and_the_owner_dead_by_the_witness(self):
        kits = kit_windows(ROUNDS, [], kit_changes_ms=[30000.0], kit_returns_ms=[50000.0])
        phase = lambda t: "round_live"
        ctx = st._context([20000.0, 35000.0, 45000.0, 55000.0], [True] * 4, [True] * 4,
                          kits, phase, spectated=[(30000.0, 40000.0, "Omen")])
        self.assertEqual([c["unreadable"] for c in ctx],
                         [None, "kit:spectating:Omen", "owner_dead:kit_witness", None])
        self.assertEqual([c["owner_alive"] for c in ctx], [True, False, False, True])
        self.assertEqual(ctx[2]["owner_life"], "dead:kit_witness")
        # The killfeed's freeze is tested first and keeps its own reason.
        frozen = st._context([35000.0], [True], [True],
                             kit_windows(ROUNDS, [32000.0], kit_changes_ms=[30000.0]), phase,
                             spectated=[(30000.0, 40000.0, "Omen")])
        self.assertEqual(frozen[0]["unreadable"], "kit_frozen:after_player_death")

    def test_the_state_stores_the_witness_death_as_its_own_claim(self):
        ts = [i * 500.0 for i in range(130)]
        drops = [_drop(12000, "C", 1.0, 0.0), _drop(36000, "C", 1.0, 0.0)]
        phase = lambda t: "round_live" if t < 60000 else "round_end"
        kw = dict(kit_changes_ms=[30000.0])
        gate = player_tray_casts([dict(d) for d in drops], phase, ROUNDS, [], **kw)
        kits = kit_windows(ROUNDS, [], **kw)
        agent = {"agent": "Tester", "entity_id": "s:ally:slot:0", "status": "resolved",
                 "reason": None, "adjudication_version": "test"}
        kit = {"C": "Widget", "Q": "Lamp", "E": "Twin Shot", "X": "Finale"}
        rows = st.adjudicate(
            "s", drops=drops, gate_rows=gate, kits=kits, phase_of=phase,
            samples={"t_ms": ts, "fills": [[1.0 if t < 12000 else 0.0, 1.0, 1.0, 0.0]
                                           for t in ts],
                     "drawn": [True] * len(ts), "clean": [True] * len(ts)},
            agent=agent, params=st.slot_parameters("Tester", kit, {}),
            inputs={"tray_drop": "t", "player_cast": "g", "tray_kit": "tray-kit-test"},
            spectated=[(30000.0, 45000.0, "Omen")])
        cov = rows[0]
        self.assertEqual(cov["unreadable_slot_samples"]["kit:spectating"], 4 * 31)
        self.assertEqual(cov["unreadable_by_kit"], {"kit:spectating:Omen": 4 * 31})
        self.assertEqual(cov["kit_witness"]["samples_spectating"], 31)
        deaths = [r for r in rows if r["kind"] == "verdict" and r["transition"] == "owner_death"]
        self.assertEqual(len(deaths), 4)
        self.assertEqual({(d["t_ms"], d["reason"], tuple(d["agreed"])) for d in deaths},
                         {(30000.0, "owner_dead:kit_witness", ("tray_kit",))})
        witness = [r for r in rows if r["kind"] == "claim" and r["witness"] == "tray_kit"]
        self.assertEqual({r["source_version"] for r in witness}, {"tray-kit-test"})
        casts = [r for r in rows if r["kind"] == "verdict" and r["transition"] == "cast"]
        self.assertEqual([r["t_ms"] for r in casts], [12000.0])
        self.assertIn("kit:spectating", st.UNREADABLE_REASONS)
        self.assertIn("after_kit_change", st.STOOD_FOR)


if __name__ == "__main__":
    unittest.main()
