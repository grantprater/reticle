"""The stacked-icon search (`reticle.stack_fit`), its gate
(`minimap.StackGate`) and the decision over its members
(`adjudication.minimap_candidates._stack_decisions`)."""
import numpy as np
import pytest

from reticle import stack_fit
from reticle.adjudication.minimap_candidates import SAME_ICON_FRAC, ally_decisions
from reticle.minimap import ALLY_MAP_DIFF_MIN, StackGate
from reticle.round_lifetimes import ROSTER_LAG_MS, roster_window


def _render(shape, members, size=64):
    """A window's tealness for `members` (bottom to top) over a dark map."""
    z = np.zeros((size, size), np.float32)
    win = stack_fit.Window(z, z, np.ones_like(z), 0, 0)
    a, c = win.composite(shape, members)
    return a + c * z


def test_composite_is_semi_transparent():
    """An icon over teal lets ICON_ALPHA of it through, never all of it
    [domain:minimap/icons-semi-transparent]."""
    shape = stack_fit.Shape(1.0)
    z = np.zeros((40, 40), np.float32)
    win = stack_fit.Window(z, z, np.ones_like(z), 0, 0)
    _, c = win.composite(shape, [{"x": 20, "y": 20, "deg": 0.0, "g": 1.0}])
    assert c[20, 20] == pytest.approx(1.0 - stack_fit.ICON_ALPHA, abs=1e-6)
    assert c[0, 0] == pytest.approx(1.0)


def test_two_touching_icons_are_two_members():
    shape = stack_fit.Shape(1.0)
    truth = [{"x": 28.0, "y": 32.0, "deg": 0.0, "g": 1.0},
             {"x": 36.0, "y": 32.0, "deg": 90.0, "g": 1.0}]
    T = _render(shape, truth)
    z = np.zeros_like(T)
    got = stack_fit.fit_box(T, z, np.ones_like(T), (0, 64, 0, 64), shape)
    assert len(got) == 2
    for m in truth:
        d = min(np.hypot(g["x"] - m["x"], g["y"] - m["y"]) for g in got)
        assert d < 1.0
    assert all(g["members"] == 2 and g["margin"] > shape.lam for g in got)
    assert sorted(g["depth"] for g in got) == [0, 1]


def test_one_icon_is_one_member_and_no_stack():
    shape = stack_fit.Shape(1.0)
    T = _render(shape, [{"x": 30.0, "y": 30.0, "deg": 45.0, "g": 1.0}])
    z = np.zeros_like(T)
    got = stack_fit.fit_box(T, z, np.ones_like(T), (0, 64, 0, 64), shape)
    assert len(got) == 1
    wins = stack_fit.stack_windows(T, np.ones_like(T), np.ones(T.shape, bool), shape)
    assert len(wins) == 1
    assert wins[0]["mass"] / stack_fit.single_mass(shape) <= stack_fit.STACK_MASS


def test_stacked_mass_exceeds_one_icon():
    shape = stack_fit.Shape(1.0)
    T = _render(shape, [{"x": 28.0, "y": 32.0, "deg": 0.0, "g": 1.0},
                        {"x": 38.0, "y": 32.0, "deg": 180.0, "g": 1.0}])
    wins = stack_fit.stack_windows(T, np.ones_like(T), np.ones(T.shape, bool), shape)
    assert len(wins) == 1
    assert wins[0]["mass"] / stack_fit.single_mass(shape) > stack_fit.STACK_MASS


def test_roster_window_keeps_the_read_in_force():
    times = [0.0, 1000.0, 2000.0, 3000.0]
    alive = [5, 4, None, 3]
    assert ROSTER_LAG_MS == 500.0
    assert roster_window(times, alive, 1400.0) == [5, 4]
    assert roster_window(times, alive, 1600.0) == [4, None]
    assert roster_window(times, alive, 2600.0) == [None, 3]


def test_stack_gate_reasons():
    gate = StackGate(object(), [0.0, 1000.0], [5, 4], "abc")
    assert gate.gate(0.0, False, 1)["reason"] == "self_unseen"
    at = gate.gate(0.0, True, 4)
    assert at["reason"] == "at_capacity" and at["capacity"] == 4
    run = gate.gate(0.0, True, 2)
    assert run["reason"] is None and run["capacity"] == 4
    assert run["rests_on"]["stream"] == "roster"
    assert run["rests_on"]["roster_sha256"] == "abc"
    assert run["rests_on"]["alive_ally"] == [5]
    assert StackGate(object(), [], [], "abc").gate(0.0, True, 0)["reason"] == "capacity_unread"
    assert StackGate(None, None, None, None, reason="no_stored_roster").gate(
        0.0, True, 0)["reason"] == "no_stored_roster"


def _ring(key, cx, cy):
    return {"candidate_key": key, "frame_idx": 7, "channel": "ally", "cx": cx, "cy": cy,
            "cov": 1.0, "inner": 0.0, "facing": 0.0, "map_diff": 40.0, "widget_scale": 1.0,
            "spike_glyphs": []}


def _member(key, cx, cy, margin, cap=3, map_diff=40.0):
    return {"candidate_key": key, "frame_idx": 7, "channel": "stack", "cx": cx, "cy": cy,
            "facing": 0.0, "map_diff": map_diff, "widget_scale": 1.0, "spike_glyphs": [],
            "capacity": cap, "stack": {"margin": margin, "r_out": 8.0}}


def test_stack_decisions():
    rows = [_ring("r1", 10.0, 10.0), _ring("r2", 100.0, 100.0),
            # the ring fit's icon found again
            _member("s_same", 10.0 + 0.9 * SAME_ICON_FRAC * 8.0, 10.0, 9.0),
            # the map, not an icon
            _member("s_map", 50.0, 50.0, 8.0, map_diff=ALLY_MAP_DIFF_MIN / 2),
            # two new icons, room for one: the larger margin wins
            _member("s_weak", 60.0, 20.0, 3.0), _member("s_strong", 20.0, 60.0, 5.0)]
    got = {d["candidate_key"]: d for d in ally_decisions(rows)}
    assert got["r1"]["disposition"] == got["r2"]["disposition"] == "accepted"
    assert got["s_same"]["reason"] == "same_icon_as_ring_fit"
    assert got["s_same"]["same_icon_candidate_key"] == "r1"
    assert got["s_map"]["reason"] == "interior_is_map"
    assert got["s_strong"]["disposition"] == "accepted"
    assert got["s_strong"]["family"] == "ally"
    assert got["s_weak"]["reason"] == "over_capacity"


def test_ring_decisions_ignore_stack_rows():
    """Adding stack members never changes a ring fit's decision."""
    ring = [_ring("r1", 10.0, 10.0), _ring("r2", 12.0, 10.0)]
    alone = {d["candidate_key"]: d for d in ally_decisions(ring)}
    both = {d["candidate_key"]: d for d in ally_decisions(ring + [_member("s", 40.0, 40.0, 5.0)])}
    for k in ("r1", "r2"):
        assert alone[k] == both[k]
