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


def _build(monkeypatch, streams: dict) -> dict:
    head = {"kind": "coverage", "kit": KIT, "ability_state_version": "kit-test",
            "parameters": {"E": {"max_charges": 2}}}
    data = {**streams, "ability_state": [head] + streams.get("ability_state", [])}
    monkeypatch.setattr(ss, "Store", _Store)
    monkeypatch.setattr(ss, "_stored", lambda st, stream, sid: list(data.get(stream, [])))
    slots = [{"key": f"{SID}:ally:slot:{k}", "agent": "Sova" if k == 0 else None,
              "status": "resolved" if k == 0 else "unresolved", "reason": None} for k in range(5)]
    monkeypatch.setattr(ss, "lineup_slots", lambda sid, root: {"slots": slots, "player_slot": 0})
    return ss.build_abilities(SID, facts=_facts())


def _children(B):
    return [r for r in B["child_rows"] if r["kind"] == "child"]


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
    assert set(ss.ABILITY_STREAMS) == {"ability_child", "ability_effect"}
    from reticle import plan
    derived = {d["stream"]: d for d in plan.derived_streams()}
    for s in ss.ABILITY_STREAMS:
        assert "ability-children" in derived[s]["command"]
    assert "dead_ruse_cast" in plan.RETIRED_STREAMS
