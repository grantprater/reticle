"""Child ends (replay-layer 0.3.0): each class's end markers, the unknown end,
and the scorers' named bucket for it."""
from __future__ import annotations

import numpy as np
import pytest

from reticle import acceptance as acc
from reticle import replay_layer as rl

NEXT = 100_000.0              # the next round's start
CLEANUP = NEXT - 150.0        # a channel close at the round's cleanup
NONE = {"disabled_at_owner_death": None, "killed": None, "destroy_effect": None}


def end(cls, close, markers=None, last=5_000.0):
    return rl.child_end(cls, close, NEXT, {**NONE, **(markers or {})}, last)


@pytest.mark.parametrize("cls", ["GameObject_Deadeye_E_Trap_C", "GameObject_Deadeye_E_Teleporter_Tether_C",
                                 "GameObject_Gumshoe_4_TripWire_C",
                                 "GameObject_Gumshoe_4_TripWire_SecondWire_C",
                                 "Pawn_Gumshoe_E_PossessableCamera_C"])
def test_disabled_at_owner_death_ends_the_four_drawn_classes(cls):
    e = end(cls, CLEANUP, {"disabled_at_owner_death": 40_000.0})
    assert (e["t_end"], e["end_marker"], e["channel_close_kind"]) == (40_000.0, "disabled_at_owner_death",
                                                                      "round_cleanup")


def test_trademark_cleanup_close_with_no_marker_is_the_objects_end():
    e = end("GameObject_Deadeye_E_Trap_C", CLEANUP)
    assert (e["t_end"], e["end_marker"]) == (CLEANUP, "round_cleanup")


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
    # Cypher's Cage shows a Disabled effect at its owner's death too, but the
    # class's ends were never verified: the marker is ignored
    e = end("GameObject_Gumshoe_Q_CageTrap_C", CLEANUP, {"disabled_at_owner_death": 40_000.0})
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
