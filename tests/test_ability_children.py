"""The player's own ability children and effects (docs/ABILITY_ENTITIES.md
step 2): `slot_state.build_abilities` over synthetic stored rows, and the
`ability` lane's scorer in `reticle.acceptance`."""
from __future__ import annotations

import pytest

from reticle import acceptance as acc
from reticle import slot_state as ss
from reticle.domain import Fact

SID = "s0"
KIT = {"C": "Owl Drone", "Q": "Shock Bolt", "E": "Recon Bolt", "X": "Hunter's Fury"}
ROUNDS = [
    {"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 100_000.0, "t_close_ms": 105_000.0},
    {"round_no": 2, "t_start_ms": 110_000.0, "t_end_ms": 200_000.0, "t_close_ms": 205_000.0},
]


def _facts() -> dict:
    """Recon Bolt: a deployed object, 30 s of life from game data, a reveal
    effect. Owl Drone and Shock Bolt: no lifecycle fact at all."""
    life = Fact(domain="abilities", id="sova-recon-bolt-lifecycle", claim="c", kind="lifecycle",
                known="k", since="2026-10-09", subject="Sova:Recon Bolt",
                lifecycle_class="deployed", ends_on=("lifetime",),
                lifetime="game_data/sova-recon-bolt-game-data#life.active_s",
                effects=("reveal:enemy",))
    gd = Fact(domain="game_data", id="sova-recon-bolt-game-data", claim="c", kind="measured",
              known="k", since="2026-10-09", subject="Sova:Recon Bolt",
              values={"life": {"active_s": 30}})
    return {life.key: life, gd.key: gd}


class _Store:
    def __init__(self, root):
        pass

    def read_manifest(self, sid):
        return {"ingested_at": "2026-10-09T00:00:00"}

    def read_rounds(self, sid, date):
        class T:
            def to_pylist(self):
                return [dict(r) for r in ROUNDS]
        return T()


def _cast(slot, t):
    return {"kind": "verdict", "transition": "cast", "slot": slot, "t_ms": float(t),
            "before": {"t_ms": float(t) - 100.0}, "claims": [], "agreed": ["tray"]}


def _vision(lit=None, uncast=False, frames=None):
    """The team's stored vision as the owner reads it back
    (`team_vision.StoredVision`): a 100 x 100 widget lit where `lit` (a
    (y0, y1, x0, x1) box) says, at every 15 Hz frame; no stream when `lit`
    is None. `uncast` adds an eligible icon that cast no cone."""
    from reticle import lighting
    from reticle.team_vision import StoredVision
    if lit is None:
        return StoredVision({}, None, None, reason="no_team_vision: `reticle vision` stored nothing")
    import numpy as np
    m = np.zeros((100, 100), bool)
    y0, y1, x0, x1 = lit
    m[y0:y1, x0:x1] = True
    icons = [{"role": "self", "eligible": True, "casts": True}]
    if uncast:
        icons.append({"role": "ally", "eligible": True, "casts": False})
    rows = [{"kind": "coverage", "team_vision_version": "team-vision-test", "cache_hz": 15.0}]
    for t in frames if frames is not None else [i * 1000.0 / 15.0 for i in range(0, 15 * 120)]:
        rows.append({"kind": "frame", "t_ms": float(t), "widget": "drawn",
                     "observable": lighting.pack_mask(m), "icons": icons})
    return StoredVision.from_rows(rows)


def _build(monkeypatch, streams: dict, allies=None, enemies=None, tree=None, kits=None,
           vision=None) -> dict:
    """`build_abilities` over synthetic stored rows: the player is Sova in
    ally slot 0; `allies` and `enemies` name the other slots' agents;
    `vision` is the team's stored vision (none by default)."""
    head = {"kind": "coverage", "kit": KIT, "ability_state_version": "kit-test",
            "parameters": {"E": {"max_charges": 2}}}
    data = {**streams, "ability_state": [head] + streams.get("ability_state", [])}
    monkeypatch.setattr(ss, "Store", _Store)
    monkeypatch.setattr(ss, "_stored", lambda st, stream, sid: list(data.get(stream, [])))
    names = ["Sova"] + list(allies or [None] * 4)
    slots = [{"key": f"{SID}:ally:slot:{k}", "agent": names[k],
              "status": "resolved" if names[k] else "unresolved", "reason": None} for k in range(5)]
    foes = list(enemies or [None] * 5)
    enemy = [{"key": f"{SID}:enemy:slot:{k}", "agent": foes[k],
              "status": "resolved" if foes[k] else "unresolved", "reason": None} for k in range(5)]
    monkeypatch.setattr(ss, "lineup_slots", lambda sid, root: {"slots": slots, "player_slot": 0,
                                                               "enemy_slots": enemy})
    monkeypatch.setattr(ss, "ability_objects", lambda root: {"tree": tree or {},
                                                             "stamp": {"version": "test"}})
    vis = vision if vision is not None else _vision()
    monkeypatch.setattr(ss, "_stored_vision", lambda root, sid: vis)
    monkeypatch.setattr(ss, "_kit_of", lambda agent, root: dict((kits or {}).get(agent, {})))
    return ss.build_abilities(SID, facts=_facts())


def _children(B):
    return [r for r in B["child_rows"] if r["kind"] == "child" and r["node"] == "instance"]


def _objects(B):
    return [r for r in B["child_rows"] if r["kind"] == "child" and r["node"] == "object"]


def test_child_opens_joins_a_spawned_object_an_effect_and_owner_death_disables(monkeypatch):
    B = _build(monkeypatch, {
        "ability_state": [_cast("E", 10_000), _cast("Q", 40_000),
                          {"kind": "verdict", "transition": "owner_death", "slot": None,
                           "t_ms": 20_000.0}],
        "ability_shape": [{"kind": "shape", "found": True, "slot": "E", "cast_t_ms": 10_000.0,
                           "t_ms": 10_500.0, "cx": 50.0, "cy": 60.0, "shape": "ring"}],
        "death": [{"kind": "death_verdict", "death_id": "d-me", "t_ms": 20_400.0, "victim": "Sova",
                   "side": "ally"},
                  {"kind": "death_verdict", "death_id": "d-kill", "t_ms": 41_000.0, "victim": "Jett",
                   "killer": "Sova", "side": "enemy",
                   "weapon_evidence": {"category": "ability", "name": "Shock Bolt"}}],
        "death_identity": [{"event_kind": "identity_distribution",
                            "entity_id": "identity:d-kill:killer",
                            "identity_distribution": {"distribution": {"Sova": 1.0}},
                            "metadata": {"status": "resolved"}}],
    })
    ch = {c["slot"]: c for c in _children(B)}
    e = ch["E"]
    assert e["child_id"] == f"{SID}:child:R1:1" and e["round"] == 1
    assert e["parent"] == f"{SID}:ally:slot:0" and e["depends_on"] == [f"identity:{SID}:ally:slot:0"]
    assert e["agent"] == "Sova"
    assert [w["witness"] for w in e["witnesses"]] == ["player_tray_cast", "shape_fit"]
    assert e["position"]["source"] == "ability_shape"
    assert e["lifecycle"]["lifetime_ms"] == 30_000.0
    assert e["predicted_end"] == {"lo_ms": 39_900.0, "hi_ms": 40_000.0, "basis": "lifetime_expiry"}
    # The owner died at 20 s, inside the 30 s life: a deployed object is disabled.
    assert e["disabled"]["t_ms"] == 20_000.0 and e["disabled"]["death_id"] == "d-me"
    assert e["owner_death"]["rule"] == "disabled"
    effects = [r for r in B["effect_rows"] if r["kind"] == "effect"]
    kill = next(r for r in effects if r["effect"] == "kill")
    assert kill["source"] == ch["Q"]["child_id"] and kill["target"]["ref"] == "identity:d-kill"
    assert kill["depends_on"] == ["identity:d-kill:killer"]
    reveal = next(r for r in effects if r["effect"] == "reveal")
    assert reveal["predicted"] is True and reveal["source"] == e["child_id"]
    assert reveal["target"]["targets"] == ["enemy"]


def test_nothing_crosses_a_round(monkeypatch):
    B = _build(monkeypatch, {
        "ability_state": [_cast("E", 95_000)],
        "ability_glyph_name": [{"kind": "verdict", "reason": None, "entity_id": "g1",
                                "birth_ms": 112_000.0,
                                "ability": {"agent": "Sova", "slot": "E", "key": "k"}}],
    })
    (e,) = _children(B)
    assert e["round"] == 1
    # 30 s of life from 95 s ends at round 1's barrier (105 s), never in round 2.
    assert e["end"]["hi_ms"] == 105_000.0 and e["end"]["basis"] == "round_barrier"
    assert [w["witness"] for w in e["witnesses"]] == ["player_tray_cast"]
    (cand,) = [r for r in B["child_rows"] if r["kind"] == "candidate"]
    assert cand["round"] == 2 and cand["reason"] == "no_live_child"


def test_a_missing_lifecycle_fact_is_a_no_fact_reason(monkeypatch):
    B = _build(monkeypatch, {"ability_state": [_cast("C", 5_000)]})
    (c,) = _children(B)
    life = c["lifecycle"]
    assert life["lifetime_ms"] is None
    assert life["lifetime_reason"] == "no-fact:sova:C:duration"
    assert life["owner_death"] is None and life["owner_death_reason"].startswith("no-fact:")
    assert c["ends_on"] == ["round_end"] and c["ends_on_reason"].startswith("no-fact:")
    assert c["end"]["basis"] == "round_barrier" and c["disabled"] is None


def test_charge_bound_flags_and_keeps(monkeypatch):
    B = _build(monkeypatch, {"ability_state": [_cast("E", t) for t in (1_000, 2_000, 3_000)]})
    ch = _children(B)
    assert len(ch) == 3 and [c["over_bound"] for c in ch] == [False, False, True]


def test_score_ability_lane_outcomes():
    finds = [
        {"key": "f1", "round": 1, "ability": "reconbolt", "kind": "sova:recon bolt", "open_lo": 900.0,
         "open_hi": 1_000.0, "end_hi": 31_000.0, "end_basis": "lifetime_expiry", "held": False},
        {"key": "f2", "round": 1, "ability": "owldrone", "kind": "sova:owl drone", "open_lo": 50_000.0,
         "open_hi": 50_100.0, "end_hi": 105_000.0, "end_basis": "round_barrier", "held": False},
        {"key": "f3", "round": 1, "ability": "shockbolt", "kind": "sova:shock bolt", "open_lo": 70_000.0,
         "open_hi": 70_100.0, "end_hi": 70_200.0, "end_basis": "round_barrier", "held": False},
    ]
    truth = [{"t_ms": 1_100.0, "ability": "reconbolt", "slot": 1, "end_ms": 31_000.0,
              "end_cause": "other"},
             {"t_ms": 20_000.0, "ability": "reconbolt", "slot": 1, "end_ms": None, "end_cause": None},
             {"t_ms": 70_050.0, "ability": None, "slot": 9, "end_ms": None, "end_cause": None}]
    others = [{"t_ms": 50_000.0, "ability": "Owl Drone", "agent": "Sova"}]
    doc, arrays = acc.score_ability_lane(finds, truth, others, [0.0])
    assert doc["outcome_of"] == {"f1": "right_entity", "f2": "other_entity",
                                 "f3": "coverage_gap:slot_unmapped:9"}
    rb = doc["classes"]["reconbolt"]
    assert rb["truth"] == 2 and rb["paired"] == 1 and rb["recall"] == 0.5
    assert rb["end_cause_agreement"] == 1.0
    # A coverage gap is never a false open; the other player's cast is.
    assert doc["all"]["false_opens"] == 1
    assert doc["coverage_gaps"] == {"coverage_gap:slot_unmapped:9": 1}
    pooled = acc.pool_ability_lane([arrays])
    assert pooled["_all"]["recall"] == 0.5


def test_child_streams_count_as_accounted():
    assert set(ss.ABILITY_STREAMS) == {"ability_child", "ability_effect", "ability_child_identity"}
    from reticle import plan
    derived = {d["stream"]: d for d in plan.derived_streams()}
    for s in ss.ABILITY_STREAMS:
        assert "ability-children" in derived[s]["command"]
    assert "dead_ruse_cast" in plan.RETIRED_STREAMS


# --- step 3: every slot, one builder; spawned objects as nodes

CYPHER_KIT = {"C": "Trapwire", "Q": "Cyber Cage", "E": "Spycam", "X": "Neural Theft"}
CAMERA, DART = "Pawn_Gumshoe_E_PossessableCamera", "GameObject_RemovableObject_GumshoeTrackingDart"


def _obj(part, parent, owner_death, ends_on, textures=()):
    def no(c):
        return (None, None, f"no-fact:cypher:E:{part}:{c}")
    return {"part": part, "subject": f"cypher:spycam/{part.lower()}", "agent": "Cypher", "slot": "E",
            "ability": "Spycam", "textures": list(textures),
            "cells": {"parent": (parent, "sheet", None), "lifecycle_class": ("deployed", "sheet", None),
                      "lifetime_s": no("lifetime_s"), "owner_death": (owner_death, "sheet", None),
                      "ends_on": (ends_on, "sheet", None), "effects": no("effects"),
                      "destructible": no("destructible")}}


def _glyph(eid, t, last, key="Cypher:E", texture="TX_UI_Minimap_Cypher_E_Default"):
    agent, slot = key.split(":")
    return {"kind": "verdict", "reason": None, "entity_id": eid, "birth_ms": float(t),
            "last_ms": float(last), "ability": {"agent": agent, "slot": slot, "key": key},
            "state": {"texture": texture}}


def _resolved(ref, agent, deps=(f"{SID}:ally:slot:1",)):
    return {"event_kind": "identity_distribution", "entity_id": ref,
            "identity_distribution": {"distribution": {agent: 1.0}},
            "metadata": {"status": "resolved", "depends_on": list(deps)}}


def _track(eid, end, xy, fixes=None):
    fx = fixes or [xy]
    return {"kind": "track", "entity_id": eid, "end": end, "birth_xy": list(xy),
            "fix": {"cx": [p[0] for p in fx], "cy": [p[1] for p in fx]}}


def _cypher_build(monkeypatch, extra=None, vision=None):
    tree = {("cypher", "E"): [_obj(CAMERA, "ability", "persists", ["destroyed", "round_end"],
                                   ["TX_UI_Minimap_Cypher_E_Default"]),
                              _obj(DART, CAMERA, "destroyed", ["owner_death", "round_end"])]}
    streams = {
        "ability_glyph_name": [_glyph("g1", 10_000, 60_000)],
        "ability_glyph_identity": [_resolved("identity:g1", "Cypher")],
        "ability_disc_track": [_track("g1", "frame_unread:not_live", (10.0, 10.0))],
        "death": [{"kind": "death_verdict", "death_id": "d-cy", "t_ms": 30_000.0, "victim": "Cypher",
                   "side": "ally"}],
        "death_identity": [_resolved("identity:d-cy", "Cypher")],
        **(extra or {})}
    return _build(monkeypatch, streams, allies=["Cypher", None, None, None], tree=tree,
                  kits={"Cypher": CYPHER_KIT}, vision=vision)


def test_spycam_camera_and_dart_are_two_nodes_and_the_dart_ends_at_owner_death(monkeypatch):
    B = _cypher_build(monkeypatch)
    (inst,) = [c for c in _children(B) if c["slot_side"] == "team"]
    objs = {o["object"]: o for o in _objects(B)}
    cam, dart = objs[CAMERA], objs[DART]
    assert inst["parent"] == f"{SID}:ally:slot:1" and inst["opened_by"] == "glyph_track"
    # The camera hangs under the instance, the dart under the camera.
    assert cam["parent"] == inst["child_id"] and cam["instance"] == inst["child_id"]
    assert dart["parent"] == cam["child_id"] and dart["instance"] == inst["child_id"]
    # The glyph draws the camera's texture: witnessed; no witness reads the dart.
    assert cam["exists"] == "witnessed" and dart["exists"] == "possible"
    # Cypher dies at 30 s: the dart ends there, the camera persists.
    assert dart["end"]["basis"] == "owner_death" and dart["end"]["hi_ms"] == 30_000.0
    assert cam["owner_death"]["rule"] == "persists" and cam["end"]["basis"] == "round_barrier"
    assert cam["end"]["hi_ms"] == 105_000.0
    # Each node's lifecycle is its own sheet row's.
    assert dart["ends_on"] == ["owner_death", "round_end"]
    assert cam["ends_on"] == ["destroyed", "round_end"]
    assert dart["lifecycle"]["lifetime_reason"].startswith("no-fact:cypher:E:")


def test_a_teammates_ability_binds_through_the_arbiter(monkeypatch):
    B = _cypher_build(monkeypatch, {
        "ult_cast": [{"kind": "cast", "entity_id": "u1", "t_ms": 50_000.0, "side": "ally",
                      "player_cast": False, "agent": "Cypher", "template": "Cypher_ult_ally",
                      "ult_cast_version": "u"},
                     {"kind": "cast", "entity_id": "u2", "t_ms": 60_000.0, "side": "ally",
                      "player_cast": False, "agent": "Cypher", "template": "Cypher_ult_ally"}],
        "ult_cast_identity": [_resolved("identity:u1", "Cypher"),
                              {"event_kind": "identity_distribution", "entity_id": "identity:u2",
                               "identity_distribution": {"distribution": {}},
                               "metadata": {"status": "abstained"}}]})
    xs = [c for c in _children(B) if c["slot"] == "X"]
    assert len(xs) == 1
    x = xs[0]
    slot_ref = f"identity:{SID}:ally:slot:1"
    assert x["slot_side"] == "team" and x["side"] == "ally" and x["agent"] == "Cypher"
    assert x["parent"] == f"{SID}:ally:slot:1" and x["agent_ref"] == slot_ref
    # The name rests on the slot's verdict and on the ult channel's verdict.
    assert x["depends_on"] == [slot_ref, "identity:u1"]
    assert B["child_rows"][0]["refused"]["ult_line_caster_unresolved"] == 1
    # The arbiter names the child on its own key from the re-keyed claims.
    ident = {r["entity_id"]: r for r in B["identity_rows"]}
    v = ident[f"identity:{x['child_id']}"]
    assert v["identity_distribution"]["distribution"] == {"Cypher": 1.0}
    assert v["metadata"]["status"] == "resolved"
    assert f"{SID}:ally:slot:1" in v["metadata"]["depends_on"]


def test_an_enemy_ability_kill_opens_an_enemy_child(monkeypatch):
    B = _build(monkeypatch, {
        "death": [{"kind": "death_verdict", "death_id": "d1", "t_ms": 20_000.0, "victim": "Sova",
                   "killer": "Jett", "side": "ally", "same_side": False,
                   "weapon_evidence": {"category": "ability", "name": "Blade Storm"}}],
        "death_identity": [_resolved("identity:d1:killer", "Jett")]},
        enemies=["Jett", None, None, None, None], kits={"Jett": {"X": "Blade Storm"}})
    (c,) = [c for c in _children(B) if c["slot_side"] == "enemy"]
    assert c["parent"] == f"{SID}:enemy:slot:0" and c["side"] == "enemy" and c["slot"] == "X"
    (kill,) = [e for e in B["effect_rows"] if e.get("effect") == "kill"]
    assert kill["source"] == c["child_id"] and kill["depends_on"] == ["identity:d1:killer"]


def test_nothing_crosses_a_round_for_any_side(monkeypatch):
    # Two Spycam glyphs at one place, either side of round 1's barrier (105 s).
    B = _cypher_build(monkeypatch, {
        "ability_glyph_name": [_glyph("g1", 100_000, 104_000), _glyph("g2", 112_000, 130_000)],
        "ability_glyph_identity": [_resolved("identity:g1", "Cypher"),
                                   _resolved("identity:g2", "Cypher")],
        "ability_disc_track": [_track(g, "frame_unread:not_live", (10.0, 10.0)) for g in ("g1", "g2")],
        "death": []})
    team = sorted((c for c in _children(B) if c["slot_side"] == "team"), key=lambda c: c["round"])
    assert [c["round"] for c in team] == [1, 2]
    for node in _children(B) + _objects(B):
        assert node["end"]["hi_ms"] <= node["barrier_ms"]
        assert node["child_id"].split(":")[2] == f"R{node['round']}"
    for node in _objects(B):
        inst = next(c for c in _children(B) if c["child_id"] == node["instance"])
        assert inst["round"] == node["round"]


def _found_again(monkeypatch, vision=None):
    return _cypher_build(monkeypatch, {
        "ability_glyph_name": [_glyph("g1", 10_000, 20_000), _glyph("g2", 22_000, 40_000),
                               _glyph("g3", 23_000, 40_000)],
        "ability_glyph_identity": [_resolved(f"identity:{g}", "Cypher") for g in ("g1", "g2", "g3")],
        "ability_disc_track": [_track("g1", "verify_lost", (10.0, 10.0), [(10.0, 10.0), (11.0, 11.0)]),
                               _track("g2", "verify_lost", (12.0, 12.0)),
                               _track("g3", "verify_lost", (80.0, 80.0))],
        "death": []}, vision=vision)


def _two_cameras(B):
    """The first camera (g1 found again as g2, lost at (12, 12)) and the
    second (g3, lost at (80, 80)), each with its camera object node."""
    team = sorted((c for c in _children(B) if c["slot_side"] == "team"),
                  key=lambda c: c["open"]["hi_ms"])
    objs = sorted((o for o in _objects(B) if o["object"] == CAMERA and o["exists"] == "witnessed"),
                  key=lambda o: o["open"]["hi_ms"])
    return team, objs


def test_a_glyph_found_again_at_its_place_joins_its_child(monkeypatch):
    B = _found_again(monkeypatch, _vision(lit=(0, 50, 0, 50)))
    team, _objs = _two_cameras(B)
    # g2 finds g1's drawing again; g3, far away, is a second camera.
    assert len(team) == 2
    assert [w["id"] for w in team[0]["witnesses"]] == ["g1", "g2"]


def test_a_drawing_lost_in_view_ends_its_node(monkeypatch):
    # The team's light covers (12, 12) through the loss and not (80, 80).
    B = _found_again(monkeypatch, _vision(lit=(0, 50, 0, 50)))
    team, objs = _two_cameras(B)
    for node in (team[0], objs[0]):
        assert node["end"]["basis"] == "observed_end" and node["end"]["lo_ms"] == 40_000.0
        dl = node["drawing_loss"]
        assert dl["view"]["status"] == "in_view" and dl["ends"] and dl["reason"] is None
        assert dl["rule"] == ss.DRAWING_LOSS_RULE
        assert dl["view"]["window_ms"] == [40_000.0, 40_000.0 + ss.GLYPH_STEP_MS]
        assert dl["view"]["frames"] == 7 and dl["view"]["share_min"] == 1.0


def test_a_moving_drawing_is_read_along_its_motion(monkeypatch):
    # The drawing moved from (30, 30) to (40, 40) over its last half second;
    # the light covers x, y < 45. Held at its last fix it reads in view; carried
    # on at the same speed it leaves the light inside the window, so unknown.
    track = {"kind": "track", "entity_id": "g1", "end": "verify_lost", "birth_xy": [30.0, 30.0],
             "fix": {"t_ms": [39_500.0, 40_000.0], "cx": [30.0, 40.0], "cy": [30.0, 40.0]}}
    B = _cypher_build(monkeypatch, {
        "ability_glyph_name": [_glyph("g1", 39_500, 40_000)],
        "ability_glyph_identity": [_resolved("identity:g1", "Cypher")],
        "ability_disc_track": [track], "death": []}, vision=_vision(lit=(0, 45, 0, 45)))
    (c,) = [c for c in _children(B) if c["slot_side"] == "team"]
    view = c["drawing_loss"]["view"]
    assert view["v_px_per_ms"] == [0.02, 0.02]
    assert view["status"] == "unknown" and view["reason"].startswith("vision_changed_in_window")
    still = _vision(lit=(0, 45, 0, 45)).in_view(40.0, 40.0, 40_000.0, 40_500.0, ss.VIEW_DISC_PX)
    assert still["status"] == "in_view"


def test_a_drawing_lost_out_of_view_leaves_its_node_open(monkeypatch):
    B = _found_again(monkeypatch, _vision(lit=(0, 50, 0, 50)))
    team, objs = _two_cameras(B)
    for node in (team[1], objs[1]):
        assert node["end"]["basis"] == "round_barrier"
        dl = node["drawing_loss"]
        assert dl["view"]["status"] == "out_of_view" and not dl["ends"]
        assert dl["reason"] == ss.DRAWING_LOST_OUT_OF_VIEW == "drawing_lost_out_of_view"
    head = next(r for r in B["child_rows"] if r["kind"] == "coverage")
    assert head["drawing_loss"]["by_view"] == {"instance:in_view": 1, "instance:out_of_view": 1,
                                               "object:in_view": 1, "object:out_of_view": 1}
    assert head["inputs"]["team_vision"] == "team-vision-test"


@pytest.mark.parametrize("vision, reason", [
    (None, "view_unknown: no_team_vision"),
    ("uncast", "view_unknown: ally_cone_unread"),
    ("edge", "view_unknown: vision_changed_in_window"),
    ("gap", "view_unknown: no_vision_frame"),
])
def test_an_unknown_view_stores_its_reason_and_ends_nothing(monkeypatch, vision, reason):
    v = {None: None, "uncast": _vision(lit=(0, 50, 0, 50), uncast=True),
         "gap": _vision(lit=(0, 50, 0, 50), frames=[0.0, 39_000.0, 41_000.0])}.get(vision)
    if vision == "edge":
        # the light covers (80, 80) for the window's first frames only
        from reticle import lighting
        from reticle.team_vision import StoredVision
        import numpy as np
        lit, dark = np.ones((100, 100), bool), np.zeros((100, 100), bool)
        rows = [{"kind": "coverage", "team_vision_version": "t", "cache_hz": 15.0}] + [
            {"kind": "frame", "t_ms": 40_000.0 + i * 1000.0 / 15.0, "widget": "drawn",
             "observable": lighting.pack_mask(lit if i < 4 else dark), "icons": []}
            for i in range(1, 8)]
        v = StoredVision.from_rows(rows)
    B = _found_again(monkeypatch, v)
    team, objs = _two_cameras(B)
    for node in (team[1], objs[1]):
        assert node["end"]["basis"] == "round_barrier"
        dl = node["drawing_loss"]
        assert dl["view"]["status"] == "unknown" and not dl["ends"]
        assert dl["reason"].startswith(reason)


def test_no_replay_input_reaches_the_in_view_estimate():
    """The estimate reads the stored team vision alone: neither `slot_state`'s
    drawing-loss rule nor the vision owner's query imports or names a replay
    module or stream (replays are evaluation truth only)."""
    import ast
    import inspect
    from reticle import team_vision as tv
    banned = ("replay", "vrf", "harness", "acceptance")
    for fn in (ss._drawing_lost, ss._stored_vision, tv.StoredVision):
        tree = ast.parse(inspect.getsource(fn))
        docs = {id(n.body[0].value) for n in ast.walk(tree)
                if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.body
                and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + [getattr(node, "module", None) or ""]
                assert not any(b in n.lower() for n in names for b in banned), (fn, names)
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docs:
                assert "replay" not in node.value.lower(), (fn, node.value)
    tv_src = inspect.getsource(tv)
    mod = ast.parse(tv_src)
    imported = {n.module for n in ast.walk(mod) if isinstance(n, ast.ImportFrom) and n.module} | \
        {a.name for n in ast.walk(mod) if isinstance(n, ast.Import) for a in n.names}
    assert not any(b in m.lower() for m in imported for b in banned), imported
    # The stream the builder opens for the view is the vision owner's alone.
    assert ss._stored_vision.__code__.co_names.count("StoredVision") == 1


def test_every_claim_names_the_owner_slots_stored_verdict(monkeypatch):
    B = _cypher_build(monkeypatch, {
        "ult_cast": [{"kind": "cast", "entity_id": "u1", "t_ms": 50_000.0, "side": "ally",
                      "player_cast": False, "agent": "Cypher", "template": "Cypher_ult_ally",
                      "ult_cast_version": "u"}],
        "ult_cast_identity": [_resolved("identity:u1", "Cypher")]})
    rows = [r for r in B["child_rows"] if r["kind"] == "child"]
    verdict = {f"{SID}:ally:slot:0": "Sova", f"{SID}:ally:slot:1": "Cypher"}
    claims = ss.child_claims(rows)
    by_key = {}
    for c in claims:
        by_key.setdefault(c["entity_id"], []).append(c)
    witnessed = [r for r in rows if r["exists"] == "witnessed"]
    assert witnessed and {r["child_id"] for r in witnessed} == set(by_key)
    for r in witnessed:
        for c in by_key[r["child_id"]]:
            # each claim names the owner slot's lineup verdict and rests on it
            assert c["agent"] == verdict[r["owner_slot"]]
            assert r["owner_slot"] in c["depends_on"]
            assert c["binding_from"] == "ability_child"
            assert c["channel"] == ss.claim_channel(next(
                w["witness"] for w in r["witnesses"] if ss.claim_channel(w["witness"]) == c["channel"]))
    # A possible node (the dart) publishes no claim and gets no verdict.
    possible = [r["child_id"] for r in rows if r["exists"] == "possible"]
    assert possible and not set(possible) & set(by_key)
    ident = {r["entity_id"] for r in B["identity_rows"]}
    assert not {f"identity:{k}" for k in possible} & ident


def test_possible_object_nodes_score_apart_from_witnessed_ones():
    node = lambda key, exists, lo, hi: {"key": key, "cls": "camera", "side": "team", "agent": "Cypher",
                                        "exists": exists, "open_lo": lo, "open_hi": hi,
                                        "end_hi": hi + 5_000.0, "end_basis": "round_barrier"}
    actor = lambda t: {"cls": "camera", "side": "team", "agent": "Cypher", "open_ms": t,
                       "close_ms": t + 5_000.0, "end_cause": "round_end"}
    nodes = [node("w1", "witnessed", 9_500.0, 10_000.0), node("w2", "witnessed", 70_000.0, 70_500.0),
             node("p1", "possible", 0.0, 100_000.0)]
    doc, arrays = acc.score_ability_objects(nodes, [actor(10_000.0), actor(40_000.0)], [0.0])
    w, p = doc["all"], doc["possible"]["all"]
    # The witnessed block: one of two actors found, one of two nodes false.
    assert (w["exists"], w["truth"], w["finds"], w["paired"], w["false_opens"]) == \
        ("witnessed", 2, 2, 1, 1)
    # The possible node pairs in its own block, never lifting the witnessed recall.
    assert (p["exists"], p["finds"], p["paired"], p["false_opens"]) == ("possible", 1, 1, 0)
    assert set(arrays) == {"witnessed", "possible"} and "team|camera" in arrays["witnessed"]


def test_claim_channels_come_from_the_channel_rows():
    for row in ss.CHANNELS:
        ch = ss.claim_channel(row["witness"])
        claim = row["agent_claim"]
        if not claim:
            assert ch is None
        elif claim.startswith("channel "):
            assert ch == claim.split()[1]
        else:
            assert ch == row["witness"]
    assert ss.claim_channel("no_such_witness") is None
