"""Synthetic checks of the class-aware harness (prototypes/question_acceptance.py):
`truth_under`'s parts, the outcome taxonomy, the coverage report, and T0's
child table (`episodes.ChildTable`).

No store is read; every input is built here.
"""
import json
import sys
import types
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
import question_acceptance as qa  # noqa: E402
from reticle import episodes as ep  # noqa: E402
from reticle.domain import Fact  # noqa: E402


def child_table(cls=("Pawn_A", "Static_B"), ticks=None, **cols):
    n = len(cls)
    base = {"entity_id": np.array([f"child:{i}" for i in range(n)], object), "guid": np.array(range(n), object),
            "cls": np.array(cls, object), "role": np.array(["pawn"] * n, object),
            "agent": np.array(["Tejo"] * n, object), "subject": np.array(["s9"] * n, object),
            "team": np.array(["B"] * n, object), "side_rel": np.array(["enemy"] * n, object),
            "ability": np.array(["Stealth Drone"] * n, object), "tray_key": np.array(["C"] * n, object),
            "mapped": np.array(["Tejo: Stealth Drone"] * n, object), "unmapped_reason": np.array([None] * n, object),
            "round": np.zeros(n), "t_open": np.zeros(n), "t_close": np.full(n, 1000.0),
            "close_basis": np.array([None] * n, object), "spawn_x": np.zeros(n), "spawn_y": np.zeros(n),
            "n_ticks": np.zeros(n, int)}
    base.update({k: np.asarray(v, object if isinstance(v[0], (str, type(None))) else float)
                 for k, v in cols.items()})
    # child 0 moves along x; child 1 has only its spawn tick at (500, 500)
    ticks = ticks or {"c": [0, 0, 0, 1], "t": [0.0, 100.0, 600.0, 0.0], "x": [0.0, 100.0, 600.0, 500.0],
                      "y": [0.0, 0.0, 0.0, 500.0]}
    base["n_ticks"] = np.bincount(ticks["c"], minlength=n)
    return ep.ChildTable(base, ticks["c"], ticks["t"], ticks["x"], ticks["y"], max_gap_ms=250.0)


# ----------------------------------------------------------------- T0's children

class TestChildTable:
    def test_position_interpolates_within_the_gap_and_holds_across_a_wider_one(self):
        ct = child_table()
        x, y = ct.position([0, 0, 0, 0], [50.0, 100.0, 350.0, 900.0])
        assert np.allclose(x, [50.0, 100.0, 100.0, 600.0])      # 100->600 is 500 ms apart: held
        assert np.allclose(y, 0.0)

    def test_a_static_child_holds_its_spawn_and_nothing_precedes_the_first_tick(self):
        ct = child_table()
        x, y = ct.position([1, 1, 0], [0.0, 800.0, -10.0])
        assert (x[0], y[0], x[1], y[1]) == (500.0, 500.0, 500.0, 500.0)
        assert np.isnan(x[2]) and np.isnan(y[2])

    def test_from_a_layer_the_children_stand_apart_from_the_players(self):
        E = {"kind": np.array(["player", "child", "child"], object),
             "entity_id": np.array(["player:a", "child:7", "child:8"], object),
             "class": np.array([None, "Pawn_A", "UltPointOrb_C"], object),
             "t_open_rep": np.array([None, 10.0, 0.0], object), "t_close_rep": np.array([None, None, 50.0], object),
             "spawn_x": np.array([None, 1.0, 2.0], object), "spawn_y": np.array([None, 1.0, 2.0], object),
             "round": np.array([None, 0, 0], object)}
        for c in ("guid", "role", "agent", "subject", "team", "side_rel", "ability", "tray_key", "mapped",
                  "unmapped_reason", "close_basis"):
            E[c] = np.array([None, None, None], object)
        T = {"e": np.array([0, 1, 1, 2]), "t_rep": np.array([0.0, 10.0, 20.0, 0.0]),
             "x": np.array([9.0, 1.0, 3.0, 2.0]), "y": np.array([9.0, 1.0, 1.0, 2.0])}
        L = types.SimpleNamespace(entities=E, ticks=T)
        ct = ep.children_from_layer(L, 250.0)
        assert ct.n == 2 and list(ct.cols["entity_id"]) == ["child:7", "child:8"]
        assert np.isnan(ct.cols["t_close"][0]) and ct.cols["t_close"][1] == 50.0
        assert ct.cols["n_ticks"].tolist() == [2, 1]
        x, _ = ct.position([0, 1], [15.0, 40.0])
        assert np.allclose(x, [2.0, 2.0])

    def test_an_array_timeline_without_children_samples_as_before(self):
        tl = ep.ArrayTimeline("m", "map", [ep.Slot("a", "A")],
                              {"a": {"t": np.array([0.0, 100.0]), "x": np.array([0.0, 10.0]),
                                     "y": np.zeros(2), "z": np.zeros(2), "yaw": np.zeros(2),
                                     "pitch": np.zeros(2)}}, [], alive_fn=lambda t: np.ones((1, t.size), bool))
        assert tl.children is None
        assert np.allclose(tl.sample(np.array([50.0]))["x"], [[5.0]])


# ----------------------------------------------------------------- truth_under's parts

class TestTruthJoin:
    def test_life_is_open_to_close_plus_the_tail_unless_measured(self):
        lo, hi, flag = qa.child_life(["A", "Bolt", "A"], ["enemy", "self", "enemy"], [0.0, 0.0, 0.0],
                                     [1000.0, 1000.0, np.nan], [5000.0, 5000.0, 5000.0],
                                     {("Bolt", "self"): (315.5, -108.8)})
        assert lo.tolist() == [0.0, 315.5, 0.0]
        assert hi.tolist() == [1000.0 + qa.LIFE_TAIL_MS, 891.2, 5000.0 + qa.LIFE_TAIL_MS]
        assert flag.tolist() == ["life_window_unmeasured", "measured", "life_window_unmeasured,close_unseen"]

    def test_a_bolt_of_another_side_borrows_no_window(self):
        lo, _hi, flag = qa.child_life(["Bolt"], ["enemy"], [0.0], [1000.0], [5000.0],
                                      {("Bolt", "self"): (315.5, -108.8)})
        assert lo[0] == 0.0 and flag[0] == "life_window_unmeasured"

    def test_the_window_keeps_the_nearest_and_respects_life(self):
        ct = child_table()
        lo = np.array([0.0, 0.0])
        hi = np.array([1000.0, 1000.0])
        # a find at x=50 at t=100: child 0 passed x=50 at t=50 (inside -150 ms)
        d, off = qa.child_window_dist(ct.position, [0], [100.0], [50.0], [0.0], lo, hi)
        assert d[0] == pytest.approx(0.0, abs=1e-6) and off[0] == -50.0
        # it then holds at x=100 (the next tick is 500 ms away): a find at x=150 is 50 cm off
        d1, _ = qa.child_window_dist(ct.position, [0], [100.0], [150.0], [0.0], lo, hi)
        assert d1[0] == pytest.approx(50.0)
        # outside its life the child is not there
        d2, _ = qa.child_window_dist(ct.position, [0], [2000.0], [600.0], [0.0], lo, hi)
        assert np.isnan(d2[0])

    def test_one_to_one_holds_beyond_64_columns(self):
        # replay_truth._assign keys frame*64 + column: frame 0 column 65 and
        # frame 1 column 1 would share a key without the spread
        D = np.full((2, 130), np.nan)
        D[0, 65] = 10.0
        D[1, 1] = 20.0
        j, d = qa.assign_one_to_one(np.array([0, 1]), D, 300.0)
        assert j.tolist() == [65, 1] and d.tolist() == [10.0, 20.0]

    def test_the_nearer_find_keeps_the_entity(self):
        D = np.array([[50.0, np.nan], [20.0, np.nan]])
        j, _d = qa.assign_one_to_one(np.array([3, 3]), D, 300.0)
        assert j.tolist() == [-1, 0]

    def test_two_classes_within_a_metre_are_ambiguous(self):
        D = np.array([[40.0, 90.0, 250.0], [40.0, 150.0, 60.0]])
        amb = qa.ambiguous_classes(D, ["player_enemy", "ability_enemy:Tejo:Stealth Drone", "player_enemy"])
        assert amb == [["ability_enemy:Tejo:Stealth Drone", "player_enemy"], ["player_enemy"]]


# ----------------------------------------------------------------- the outcome taxonomy

class TestOutcomes:
    def test_every_branch(self):
        f = qa.outcome_of
        assert f("player", ambiguous=False, assigned=True, side_rel="enemy", drawn=True, subj_named=5,
                 subj_truth=5) == ("right_entity", "right_entity:name_right")
        assert f("player", ambiguous=False, assigned=True, side_rel="enemy", drawn=True, subj_named=6,
                 subj_truth=5)[1] == "right_entity:name_wrong"
        assert f("player", ambiguous=False, assigned=True, side_rel="enemy", drawn=True, subj_named=-1,
                 subj_truth=5)[1] == "right_entity:unnamed"
        assert f("player", ambiguous=False, assigned=True, side_rel="enemy", drawn=False)[0] == "undrawn_truth"
        assert f("player", ambiguous=False, assigned=True, side_rel="ally",
                 key="player_ally:Raze:-")[1] == "other_entity:player_ally:Raze:-"
        assert f("child", ambiguous=False, assigned=True, side_rel="enemy",
                 key="ability_enemy:Tejo:Stealth Drone")[1] == "other_entity:ability_enemy:Tejo:Stealth Drone"
        assert f("child", ambiguous=False, assigned=True, key="unmapped:X_C", cls="X_C",
                 unmapped_reason="instigator chain ends at ['A'], agents ['B']") == \
            ("coverage_gap", "coverage_gap:X_C:instigator chain ends")
        assert f(None, ambiguous=False, assigned=False, derivation="kill_x")[1] == "nothing_there:kill_x"
        assert f("player", ambiguous=True, assigned=True, side_rel="enemy", drawn=True)[0] == "ambiguous"
        assert set(qa.CLASS_OUTCOMES) == {"right_entity", "other_entity", "undrawn_truth", "nothing_there",
                                          "coverage_gap", "ambiguous"}

    def test_derivations_take_the_first_that_explains(self):
        kills = np.array([[0.0, 9000.0, 0.0, 0.0]])
        swaps = np.array([[0.0, 4000.0, 1000.0, 0.0]])
        fx = np.array([100.0, 1100.0, 5000.0, 5000.0, 100.0, 9000.0])
        fy = np.zeros(6)
        ft = np.array([500.0, 500.0, 500.0, 500.0, 500.0, 500.0])
        ping = np.array([True, False, True, False, False, False])
        near = np.array([False, False, False, True, False, False])
        held = np.array([False, False, False, False, True, False])
        got = qa.nothing_derivation(fx, fy, ft, kills, swaps, ping, near, held)
        assert got.tolist() == ["kill_x", "question_swap", "ping", "enemy_3_8m", "held_by_nearer_find", "none"]

    def test_a_kill_x_holds_only_inside_its_window(self):
        got = qa.nothing_derivation([0.0], [0.0], [9500.0], np.array([[0.0, 9000.0, 0.0, 0.0]]),
                                    np.zeros((0, 4)), [False], [False])
        assert got.tolist() == ["none"]

    def test_drawn_by_fact_reads_only_the_subjects_own_facts_and_side(self):
        def fact(i, subj):
            return Fact(domain="abilities", id=i, claim="c", kind="appearance", known="player", since="x",
                        subject=subj)
        F = {f.key: f for f in (fact("tejo-stealth-drone-enemy-minimap-icon", "tejo:stealth drone"),
                                fact("phoenix-blaze-no-minimap-icon", "phoenix:blaze"),
                                fact("fade-prowler-minimap-icon", "fade:prowler"),
                                fact("sova-recon-bolt-minimap-everyone", "sova:recon bolt"))}
        assert qa.drawn_by_fact(F, "Tejo", "Stealth Drone", "enemy")[0] == "yes"
        assert qa.drawn_by_fact(F, "Tejo", "Stealth Drone", "ally")[0] == "unknown"
        assert qa.drawn_by_fact(F, "Phoenix", "Blaze", "self")[0] == "no"
        assert qa.drawn_by_fact(F, "Fade", "Prowler", "self")[0] == "yes"
        assert qa.drawn_by_fact(F, "Fade", "Prowler", "ally")[0] == "unknown"     # the caster's own minimap only
        assert qa.drawn_by_fact(F, "Fade", "Prowler", "enemy")[0] == "unknown"
        assert qa.drawn_by_fact(F, "Sova", "Recon Bolt", "ally")[0] == "yes"
        assert qa.drawn_by_fact(F, "Sova", "Recon Bolt", "enemy")[0] == "unknown"


# ----------------------------------------------------------------- the coverage report

class TestCoverage:
    def census(self):
        ct = child_table(cls=("Pawn_Cashew_4_Spider_LockOn_C", "BombEquippable_C", "Odd_C"),
                         ticks={"c": [0, 1, 2], "t": [0.0, 0.0, 0.0], "x": [0.0, 1.0, 2.0], "y": [0.0, 1.0, 2.0]},
                         mapped=["Tejo: Stealth Drone", "spike item (carried or dropped)", None],
                         ability=["Stealth Drone", None, None], agent=["Tejo", "Raze", None],
                         unmapped_reason=[None, None, "instigator chain ends at ['X']"])
        joinable = ~np.isin(ct.cols["cls"].astype(str), list(qa.NOT_JOINED))
        flag = np.array(["life_window_unmeasured"] * 3, object)
        return qa._census(ct, joinable, flag, "me", {}, {})

    def test_every_class_appears_with_its_joined_state_and_reason(self):
        c = self.census()
        assert set(c) == {"ability_enemy:Tejo:Stealth Drone", "spike:-:spike item (carried or dropped)",
                          "unmapped:Odd_C", "player_enemy", "player_ally"}
        assert c["spike:-:spike item (carried or dropped)"]["joined"] == 0
        assert list(c["spike:-:spike item (carried or dropped)"]["not_joined"]) == [qa.NOT_JOINED["BombEquippable_C"]]
        assert c["ability_enemy:Tejo:Stealth Drone"]["joined"] == 1

    def test_claims_come_from_the_stored_streams(self, tmp_path, monkeypatch):
        sid = "fake"
        ev = tmp_path / "events"
        for s, rows in {"ability_glyph_name": [{"kind": "verdict", "ability": {"agent": "Tejo", "slot": "C"}}],
                        "enemy_track": [{"kind": "summary"}], "spike_carrier": [{"kind": "x"}]}.items():
            (ev / s).mkdir(parents=True)
            (ev / s / f"{sid}.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        monkeypatch.setattr(qa, "STORE", tmp_path)
        c = self.census()
        qa.claims(sid, c)
        assert c["ability_enemy:Tejo:Stealth Drone"]["claimed_by"] == ["ability_glyph_name"]
        assert c["ability_enemy:Tejo:Stealth Drone"]["scored"] == "yes"
        assert c["player_enemy"]["claimed_by"] == ["enemy_track"]
        assert c["player_ally"]["claimed_by"] == []
        assert c["spike:-:spike item (carried or dropped)"]["claimed_by"] == ["spike_carrier"]
        assert c["spike:-:spike item (carried or dropped)"]["scored"].startswith("no: the layer holds only")
        assert c["unmapped:Odd_C"]["claimed_by"] == []


C817 = "c817691bcd15"


def _has_layer():
    try:
        from reticle import replay_layer as rl
        m, _s = rl.resolve(C817)
        return m is not None and (rl.layer_dir(m) / "layer.json").is_file()
    except Exception:
        return False


@pytest.mark.skipif(not _has_layer(), reason="the c817 replay layer is not built in this store")
def test_stored_child_positions_match_the_layers_state_at():
    from reticle import replay_layer as rl
    from reticle.replay_source import MAX_GAP_MS
    L = rl.load(C817)
    ct = ep.children_from_layer(L, MAX_GAP_MS)
    ids = np.flatnonzero(L.entities["kind"] == "child")
    moving = [int(i) for i, e in enumerate(ids) if ct.cols["n_ticks"][i] > 3][:5]
    static = [int(i) for i, e in enumerate(ids) if ct.cols["n_ticks"][i] == 1][:5]
    for c in moving + static:
        t = float(ct.cols["t_open"][c]) + 40.0
        x, y = ct.position([c], [t])
        st = L.state_at(t, clock="replay", entities=[int(ids[c])])
        assert st and np.isclose(x[0], st[0]["x"]) and np.isclose(y[0], st[0]["y"])
