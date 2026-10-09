"""The acceptance core (`reticle.acceptance`): the truth join and its helpers,
pure over synthetic grids; and its place above every pipeline layer."""

import types

import numpy as np

from reticle import acceptance as acc


def _grid():
    """Two players (row 0 an ally, the player; row 1 an enemy) on four
    samples of round 1, and two children of round 0 in the layer's 0-based
    numbering (round 1 of the grid): a static enemy drone at (1000, 0) and an
    ally orb at (0, 1000)."""
    G = np.array([0.0, 100.0, 200.0, 300.0])
    X = np.array([[0.0, 0.0, 0.0, 0.0], [500.0, 500.0, 500.0, 500.0]])
    Y = np.zeros((2, 4))
    cols = {"round": np.array([0.0, 0.0]), "subject": np.array(["b", "a"], dtype=object),
            "side_rel": np.array(["enemy", "ally"], dtype=object),
            "cls": np.array(["Drone_C", "Orb_C"], dtype=object),
            "t_open": np.array([0.0, -2000.0]), "t_close": np.array([np.nan, -1000.0]),
            "n_ticks": np.array([0, 0]), "spawn_x": np.array([1000.0, 0.0]),
            "mapped": np.array(["Drone", "Orb"], dtype=object),
            "agent": np.array(["Tejo", "Sage"], dtype=object),
            "ability": np.array(["Stealth Drone", "Barrier Orb"], dtype=object),
            "tray_key": np.array(["E", "C"], dtype=object),
            "entity_id": np.array(["child:1", "child:2"], dtype=object),
            "unmapped_reason": np.array([None, None], dtype=object)}
    px = np.array([1000.0, 0.0])
    py = np.array([0.0, 1000.0])

    def position(c, t):
        c = np.asarray(c, np.int64)
        return px[c], py[c]

    ct = types.SimpleNamespace(cols=cols, n=2, position=position)
    return types.SimpleNamespace(G=G, X=X, Y=Y, G_round=np.array([1, 1, 1, 1]), rounds=[{"round": 1, "t_next": 400.0}],
                                 me="a", ei=np.array([1]), ci=np.array([0]), sid=["a", "b"],
                                 agent={"a": "Sage", "b": "Tejo"}, cap="test", tl0=types.SimpleNamespace(children=ct))


def test_child_life_takes_measured_classes_and_holds_unclosed_children_to_round_end():
    lo, hi, flag = acc.child_life(["A", "B", "A"], ["self", "self", "ally"], [0.0, 10.0, 20.0],
                                  [100.0, np.nan, 120.0], [500.0, 500.0, 500.0], {("A", "self"): (5.0, -7.0)})
    assert lo.tolist() == [5.0, 10.0, 20.0]
    assert hi.tolist() == [93.0, 500.0 + acc.LIFE_TAIL_MS, 120.0 + acc.LIFE_TAIL_MS]
    assert flag.tolist() == ["measured", "life_window_unmeasured,close_unseen", "life_window_unmeasured"]


def test_ambiguous_classes_lists_distinct_sorted_keys_within_the_radius():
    D = np.array([[50.0, 60.0, np.nan], [50.0, 500.0, 90.0], [np.nan, np.nan, np.nan]])
    out = acc.ambiguous_classes(D, ["player_enemy", "player_enemy", "ability_enemy:Tejo:Drone"])
    assert out == [["player_enemy"], ["ability_enemy:Tejo:Drone", "player_enemy"], []]


def test_assign_per_frame_gives_a_loser_its_next_free_truth():
    D = np.array([[10.0, 50.0], [20.0, 40.0], [10.0, np.nan]])
    j, d = acc.assign_per_frame(np.array([0, 0, 1]), D, 100.0)
    assert j.tolist() == [0, 1, 0]
    assert d.tolist() == [10.0, 40.0, 10.0]


def test_round_index_maps_round_numbers_and_marks_the_absent():
    assert acc.round_index({3: 0, 7: 1}, [7, 3, 5, 9]).tolist() == [1, 0, -1, -1]


def test_join_puts_players_children_and_nothing_under_finds():
    M = _grid()
    alive = np.ones((2, 4), bool)
    # find 0 on the enemy, find 1 on the drone, find 2 on the orb after its
    # life (closed at -1000 ms, its tail ends at -400), find 3 on nothing; each on its own sample
    ks = np.array([0, 1, 3, 2])
    fx = np.array([510.0, 990.0, 0.0, -3000.0])
    fy = np.array([0.0, 0.0, 1000.0, 0.0])
    t = M.G[ks]
    J = acc.join_entities(M, alive, ks, t, fx, fy)
    assert J["col_kind"].tolist() == ["player", "child", None, None]
    assert J["col_idx"].tolist() == [1, 0, -1, -1]
    assert J["descs_c"][0]["key"] == "ability_enemy:Tejo:Stealth Drone"
    assert np.isclose(J["dist"][0], 10.0) and np.isclose(J["dist"][1], 10.0)
    assert J["win_dt"][1] == -100.0      # a static child: the first offset inside its life (open at 0)
    assert J["joinable"].tolist() == [True, True]


def test_join_holds_a_duplicate_for_the_nearer_find():
    M = _grid()
    J = acc.join_entities(M, np.ones((2, 4), bool), np.array([0, 0]), np.array([0.0, 0.0]),
                          np.array([505.0, 560.0]), np.array([0.0, 0.0]))
    assert J["col_kind"].tolist() == ["player", None]
    assert J["held"].tolist() == [False, True]


def test_recall_counts_pairs_by_round_with_their_own_denominators():
    M = _grid()
    J = {"alive": np.ones((2, 4), bool)}
    num, den = acc.recall_players(M, J, np.arange(4), [1], {(0, 1), (2, 1)}, {1: 0}, 1)
    assert num.tolist() == [2.0] and den.tolist() == [4.0]
    G_ = acc.join_entities(M, J["alive"], np.zeros(0, np.int64), np.zeros(0), np.zeros(0), np.zeros(0))
    rec = acc.recall_children(M, G_, np.arange(4), M.G, np.array([True, False]), {(1, 0)}, {1: 0}, 1,
                              lambda d: d["key"])
    (n_, d_), = rec.values()
    assert n_.tolist() == [1.0] and d_.tolist() == [4.0]


def test_the_core_sits_above_every_pipeline_layer():
    from reticle.architecture import load
    data = load()
    order = data["layers"]["order"]
    assert "acceptance" in data["evaluation"]["modules"]
    assert order.index("evaluation") > order.index("consumers")
    assert order.index("evaluation") == order.index("delivery") - 1
