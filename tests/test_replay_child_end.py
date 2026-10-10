"""Child ends (replay-layer 0.3.0): each class's end markers, the unknown end,
and the scorers' named bucket for it."""
from __future__ import annotations

import numpy as np
import pytest

from reticle import acceptance as acc
from reticle import replay_layer as rl

NEXT = 100_000.0              # the next round's start
CLEANUP = NEXT - 150.0        # a channel close at the round's cleanup
NONE = {"killed": None, "destroy_effect": None}
PERSIST = ["GameObject_Deadeye_E_Trap_C", "GameObject_Deadeye_E_Teleporter_Tether_C",
           "GameObject_Gumshoe_4_TripWire_C", "GameObject_Gumshoe_4_TripWire_SecondWire_C",
           "Pawn_Gumshoe_E_PossessableCamera_C", "GameObject_Gumshoe_Q_CageTrap_C",
           "Pawn_Killjoy_Q_StealthAlarmbot_C", "Pawn_Killjoy_E_Turret_C",
           "Projectile_Killjoy_4_RemoteBees_MultiDetonate_C"]


def end(cls, close, markers=None, last=5_000.0):
    return rl.child_end(cls, close, NEXT, {**NONE, **(markers or {})}, last)


@pytest.mark.parametrize("cls", PERSIST)
def test_persisting_utility_lasts_to_the_cleanup_close(cls):
    # disabled at the owner's death, the object stays drawn, dimmer: the
    # cleanup close is its end, and a disable never is
    e = end(cls, CLEANUP, {"disabled_at_owner_death": 40_000.0})
    assert (e["t_end"], e["end_marker"], e["channel_close_kind"]) == (CLEANUP, "round_cleanup",
                                                                      "round_cleanup")


@pytest.mark.parametrize("cls", PERSIST)
def test_persisting_utility_that_never_closes_has_an_unknown_end(cls):
    e = end(cls, None, last=7_000.0)
    assert e["t_end"] is None and e["t_live_until"] == 7_000.0
    assert "no end marker of the class fired" in e["end_reason"]


def test_rendezvous_kill_ends_before_a_later_close():
    e = end("GameObject_Deadeye_E_Teleporter_Tether_C", 30_016.0, {"killed": 30_000.0})
    assert (e["t_end"], e["end_marker"]) == (30_000.0, "killed")


def test_trapwire_destroy_effect_ends_before_its_close():
    e = end("GameObject_Gumshoe_4_TripWire_SecondWire_C", 20_011.0, {"destroy_effect": 20_000.0})
    assert (e["t_end"], e["end_marker"]) == (20_000.0, "destroy_effect")


def test_spycam_mid_round_close_ends_it():
    e = end("Pawn_Gumshoe_E_PossessableCamera_C", 50_000.0)
    assert (e["t_end"], e["end_marker"], e["channel_close_kind"]) == (50_000.0, "channel_close", "mid_round")


def test_a_class_never_borrows_another_class_marker():
    # a kill marker on a class whose ends were never surveyed is ignored
    e = end("GameObject_Iris_E_Smoke_C", CLEANUP, {"killed": 40_000.0})
    assert e["end_marker"] == "unknown" and e["t_end"] is None


@pytest.mark.parametrize("close,kind", [(CLEANUP, "round_cleanup"), (None, "never")])
def test_unknown_end_keeps_its_last_live_marker_and_reason(close, kind):
    e = end("GameObject_Thumper_ConcussPulse_C", close, last=7_000.0)
    assert e["t_end"] is None and e["end_marker"] == "unknown"
    assert e["t_live_until"] == 7_000.0 and e["channel_close_kind"] == kind
    assert "no surveyed end marker" in e["end_reason"]


def test_unknown_end_skips_end_scores_and_counts_apart():
    actors = [{"ability": "M-pulse", "open_ms": 1_000.0, "close_ms": None, "end_unknown": True}]
    inst = acc.ability_truth_instances([{"t_ms": 900.0, "ability": "M-pulse", "slot": 1}], actors, [], [])
    assert inst[0]["end_ms"] is None and inst[0]["end_unknown"]
    find = {"key": "f", "ability": acc.ability_key("M-pulse"), "kind": "M-pulse", "open_lo": 800.0,
            "open_hi": 1_000.0, "end_hi": 5_000.0, "end_basis": "lifetime_expiry", "side": "self",
            "held": False, "round": 0}
    doc, arr = acc.score_ability_lane([find], inst, [], [0.0])
    assert doc["all"]["end_unknown_n"] == 1 and doc["all"]["end_cause_n"] == 0
    assert doc["all"]["end_cause"] == {"lifetime_expiry|end_unknown": 1}
    assert acc.pool_ability_lane([arr])["_all"]["end_unknown_n"] == 1


def test_unknown_object_end_counts_apart():
    node = {"key": "n", "cls": "x", "side": "team", "agent": "A", "exists": "witnessed", "open_lo": 0.0,
            "open_hi": 100.0, "end_hi": 9_000.0, "end_basis": "round_barrier"}
    act = {"cls": "x", "side": "team", "agent": "A", "open_ms": 50.0, "close_ms": None, "end_unknown": True,
           "end_cause": None}
    doc, _ = acc.score_ability_objects([node], [act], [0.0])
    assert doc["all"]["end_unknown_n"] == 1 and doc["all"]["end_cause"] == {"round_barrier|end_unknown": 1}


def test_close_kind():
    assert rl.close_kind(None, NEXT) == "never"
    assert rl.close_kind(NEXT - 100.0, NEXT) == "round_cleanup"
    assert rl.close_kind(NEXT + 10.0, NEXT) == "round_cleanup"
    assert rl.close_kind(NEXT - 1_000.0, NEXT) == "mid_round"
    assert rl.close_kind(np.nan, NEXT) == "never"


def test_disable_is_scored_as_its_own_question():
    pairs = [({"disabled_ms": 10_300.0}, {"disabled_ms": 10_000.0}),
             ({"disabled_ms": None}, {"disabled_ms": 20_000.0}),
             ({"disabled_ms": 5_000.0}, {"disabled_ms": None}),
             ({"disabled_ms": None}, {"disabled_ms": None})]
    dq, arr = acc.disabled_question(pairs)
    assert (dq["truth"], dq["marked"], dq["recall"], dq["marked_without_truth"]) == (2, 1, 0.5, 1)
    assert dq["time_error"]["median_ms"] == 300.0
    assert acc._pool_disabled([arr, arr])["truth"] == 4


def test_truth_instance_carries_its_actors_first_disable():
    actors = [{"ability": "Trapwire", "open_ms": 1_000.0, "close_ms": 9_000.0, "disabled_ms": 6_000.0},
              {"ability": "Trapwire", "open_ms": 1_000.0, "close_ms": 9_000.0, "disabled_ms": 5_000.0}]
    inst = acc.ability_truth_instances([{"t_ms": 900.0, "ability": "Trapwire", "slot": 1}], actors, [], [])
    assert inst[0]["disabled_ms"] == 5_000.0 and inst[0]["end_ms"] == 9_000.0
