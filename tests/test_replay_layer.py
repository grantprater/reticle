"""The replay layer: owner resolution, lives, RPC grouping, and the stored
examples on 60c7f1e0 (c817691bcd15) where its layer is built."""
from __future__ import annotations

import json

import numpy as np
import pytest

from reticle import replay_layer as rl
from reticle.replay_actors import Export


def fake_export(guid_subject: dict, cls: dict, instigator: dict, owner: dict | None = None):
    """An `Export` holding only what `owner_path` reads."""
    ex = object.__new__(Export)

    class _Rp:
        pass

    ex.rp = _Rp()
    ex.rp.guid_subject = guid_subject
    ex.cls = cls
    ex._refs = {"Instigator": instigator, "Owner": owner or {}}
    return ex


PC_W = "/Game/Characters/Wraith/Wraith_PC.Wraith_PC_C"
SMOKE = "/Game/Characters/Wraith/S0/Ability_4/Zone_Wraith_4_Smoke.Zone_Wraith_4_Smoke_C"


def test_two_omens_resolve_by_their_own_pawns():
    ex = fake_export({908: "omen-a", 1004: "omen-b"},
                     {908: PC_W, 1004: PC_W, 3862: SMOKE, 3900: SMOKE},
                     {3862: 908, 3900: 1004}, {3862: 3684})
    s, path = ex.owner_path(3862)
    assert s == "omen-a"
    assert [p["guid"] for p in path] == [3862, 908]
    assert path[0]["via"] == "Instigator" and path[-1]["via"] is None
    assert ex.owner_path(3900)[0] == "omen-b"


def test_spycam_dart_resolves_through_the_camera_pawn():
    cam = "/Game/Characters/Gumshoe/S0/Ability_E/Pawn_Gumshoe_E_PossessableCamera.Pawn_Gumshoe_E_PossessableCamera_C"
    dart = "/Game/Characters/Gumshoe/S0/Ability_E/Projectile_Gumshoe_E_CameraTrackingDart.Projectile_Gumshoe_E_CameraTrackingDart_C"
    ex = fake_export({810: "cypher"}, {810: "/Game/Characters/Gumshoe/Gumshoe_PC.Gumshoe_PC_C",
                                      4000: cam, 5000: dart}, {5000: 4000, 4000: 810})
    s, path = ex.owner_path(5000)
    assert s == "cypher"
    assert [p["class"] for p in path] == ["Projectile_Gumshoe_E_CameraTrackingDart_C",
                                          "Pawn_Gumshoe_E_PossessableCamera_C", "Gumshoe_PC_C"]
    assert [p["via"] for p in path] == ["Instigator", "Instigator", None]
    assert ex.owner_subject(5000) == ("cypher", [p["class"] for p in path])


def test_owner_is_followed_only_without_an_instigator():
    ex = fake_export({810: "p"}, {810: "x.P_PC_C", 7: "a.A_C", 8: "b.B_C"}, {}, {7: 8, 8: 810})
    s, path = ex.owner_path(7)
    assert s == "p" and [p["via"] for p in path] == ["Owner", "Owner", None]
    assert fake_export({}, {7: "a.A_C"}, {}, {}).owner_path(7) == (None, [
        {"guid": 7, "class": "A_C", "via": None}])


class FakeReplay:
    def __init__(self, subjects, deaths):
        self.subjects = subjects
        self._deaths = deaths

    def group(self, name):
        return self._deaths if name == "characterDeath" else []


ROUND = [{"round": 0, "t_start": 0.0, "t_end": 100_000.0, "end_basis": "phase_5",
          "t_next_start": 110_000.0}]


def test_lives_close_at_death_and_reopen_on_a_second_death():
    rp = FakeReplay(["a"], [{"t": 30_000.0, "victim": "a", "killer": "b"},
                            {"t": 60_000.0, "victim": "a", "killer": "b"}])
    lives = rl.lives_table(rp, ROUND, {})
    assert [(L["t_open"], L["t_close"], L["open_basis"]) for L in lives] == [
        (0.0, 30_000.0, "round_start"), (60_000.0, 60_000.0, "second_death")]
    assert lives[1]["t_open_lo"] == 30_000.0


def test_held_weapon_damage_after_death_opens_a_life_and_quiet_damage_does_not():
    rp = FakeReplay(["a"], [{"t": 30_000.0, "victim": "a", "killer": "b"}])
    early = {"a": np.array([31_000.0])}           # inside REVIVE_QUIET_MS: his death's own
    assert len(rl.lives_table(rp, ROUND, early)) == 1
    late = {"a": np.array([45_000.0])}
    lives = rl.lives_table(rp, ROUND, late)
    assert [(L["t_open"], L["t_close"], L["open_basis"]) for L in lives] == [
        (0.0, 30_000.0, "round_start"), (45_000.0, 100_000.0, "own_activity")]


def test_activity_counts_only_held_equippable_damage():
    EV = {"kind": ["damage", "damage", "effect"], "e": [0, 0, 0], "t_rep": [1.0, 2.0, 3.0],
          "detail": [json.dumps({"by_held_equippable": True}),
                     json.dumps({"by_held_equippable": False}), json.dumps({})]}
    act = rl.activity_by_subject(EV, {("player", "a"): 0})
    assert act["a"].tolist() == [1.0]


def test_rpc_calls_split_on_the_first_field_and_on_actor():
    n = ["R.A", "R.B", "R.A", "R.B", "R.A"]
    F = {"n": np.array(n, dtype=object), "g": np.array([1, 1, 1, 1, 2]),
         "obj": np.array([None] * 5, dtype=object), "packet": np.array([5, 5, 5, 5, 5]),
         "t": np.arange(5, dtype=float), "i": np.array([10, 11, 12, 13, 14], dtype=object),
         "f": np.array([None] * 5, dtype=object), "s": np.array([None] * 5, dtype=object),
         "b": np.array([None] * 5, dtype=object)}
    C = rl.rpc_calls(F, "R")
    assert C["g"].tolist() == [1, 1, 2]
    assert C["fields"]["A"].tolist() == [10, 12, 14]
    assert C["fields"]["B"].tolist() == [11, 13, None]


C817 = "60c7f1e0-095f-4944-87f9-ea613d595598"


@pytest.mark.skipif(not (rl.layer_dir(C817) / "layer.json").is_file(),
                    reason="the c817 replay layer is not built in this store")
def test_stored_examples_reproduce():
    L = rl.load(C817)
    E = L.entities

    def child(g):
        k = int(np.flatnonzero((E["guid"] == g) & (E["kind"] == "child"))[0])
        return L.entity(k)

    s = child(3862)
    assert s["class"] == "Zone_Wraith_4_Smoke_C"
    assert (s["t_open_rep"], s["t_close_rep"]) == (57187.0, 73189.0)
    assert np.allclose([s["spawn_x"], s["spawn_y"], s["spawn_z"]], [4524.8, -6092.7, 571.0], atol=0.05)
    assert json.loads(s["owner_path"])[-1]["guid"] == 908
    w = child(3124)
    assert (w["t_open_rep"], w["t_close_rep"]) == (29939.0, 127816.0)
    assert json.loads(w["owner_path"])[-1] == {"guid": 810, "class": "Gumshoe_PC_C", "via": None}
    assert w["agent"] == "Cypher" and w["ability"] == "Trapwire"
