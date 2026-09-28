"""The local player's kit as a state per slot (`adjudication.ability_state`),
on a synthetic round: record shapes, charges, an equip, an ult, a death, the
unread values and determinism."""
from __future__ import annotations

import json
import unittest

from reticle.ability_timeline import kit_windows, player_tray_casts
from reticle.adjudication import ability_state as st
from reticle.domain import Fact

AGENT = "Tester"
KIT = {"C": "Widget", "Q": "Lamp", "E": "Twin Shot", "X": "Finale"}
FACTS = {
    "abilities/tester-tray-charges": Fact(
        domain="abilities", id="tester-tray-charges", kind="mechanic", known="player",
        since="2026-09-27", subject="tester:tray",
        claim="Tester's tray holds two Twin Shot charges in slot E."),
    "abilities/tester-twin-shot-duration": Fact(
        domain="abilities", id="tester-twin-shot-duration", kind="mechanic",
        known="player", since="2026-09-27", subject="tester:twin shot",
        claim="A Twin Shot lasts 4 seconds."),
}
ROUNDS = [{"round_no": 1, "t_start_ms": 0.0, "t_end_ms": 60000.0, "t_close_ms": 65000.0}]
STEP = 500.0


def _phase(t: float) -> str:
    return "buy_phase" if t < 5000 else "round_live" if t < 60000 else "round_end"


def _fill(slot: str, t: float) -> float:
    if slot == "C":
        return 1.0
    if slot == "Q":  # equipped 30 s to 32 s, released unspent
        return 1.5 if 30000 <= t < 32000 else 1.0
    if slot == "E":  # two charges, one spent at 20 s
        return 1.0 if t < 20000 else 0.5
    return 1.0 if t < 40000 else 0.0  # X: lit, then cast at 40 s


def _drop(t, slot, f, to):
    return {"t_ms": t, "slot": slot, "from": f, "to": to, "suspect": False, "forced": False,
            "cooccur": False, "across_gap": False}


def _run(deaths=(50000.0,)):
    ts = [i * STEP for i in range(int(64000 / STEP))]
    fills = [[_fill(s, t) for s in st.SLOTS] for t in ts]
    drops = [_drop(20000.0, "E", 1.0, 0.5), _drop(32000.0, "Q", 1.5, 1.0),
             _drop(40000.0, "X", 1.0, 0.0)]
    gate = player_tray_casts([dict(d) for d in drops], _phase, ROUNDS, list(deaths),
                             agent=AGENT)
    kits = kit_windows(ROUNDS, list(deaths), agent=AGENT)
    agent = {"agent": AGENT, "entity_id": "s:ally:slot:0", "status": "resolved",
             "reason": None, "adjudication_version": "test"}
    rows = st.adjudicate("s", drops=drops, gate_rows=gate, kits=kits, phase_of=_phase,
                         samples={"t_ms": ts, "fills": fills, "drawn": [True] * len(ts),
                                  "clean": [True] * len(ts)},
                         agent=agent, params=st.slot_parameters(AGENT, KIT, FACTS),
                         inputs={"tray_drop": "tray-test", "player_cast": "gate-test"})
    return rows


def _verdicts(rows, slot, transition=None):
    return [r for r in rows if r["kind"] == "verdict" and r["slot"] == slot
            and (transition is None or r["transition"] == transition)]


def _state_at(rows, slot, t):
    return next(r for r in rows if r["kind"] == "state" and r["slot"] == slot
                and r["t_first_ms"] <= t <= r["t_last_ms"])


class RecordShapeTest(unittest.TestCase):
    def test_rows_carry_their_kind_and_stamp(self):
        rows = _run()
        self.assertEqual(rows[0]["kind"], "coverage")
        self.assertEqual(rows[0]["ability_state_version"], st.ABILITY_STATE_VERSION)
        self.assertEqual({r["kind"] for r in rows[1:]}, {"claim", "verdict", "state"})
        for r in rows:
            self.assertEqual(r["ability_state_version"], st.ABILITY_STATE_VERSION)
        claim = next(r for r in rows if r["kind"] == "claim")
        for k in ("claim_id", "witness", "observed_at_ms", "interval_ms", "source_version",
                  "evidence", "depends_on"):
            self.assertIn(k, claim)
        state = next(r for r in rows if r["kind"] == "state")
        for k in ("charges", "charges_reason", "charges_range", "mode", "castable", "pips",
                  "owner_alive", "readable", "until_ms", "until_reason", "t_first_ms",
                  "t_last_ms", "agent"):
            self.assertIn(k, state)

    def test_the_gate_verdict_depends_on_the_drop(self):
        rows = _run()
        cast = _verdicts(rows, "E", "cast")[0]
        by_id = {r["claim_id"]: r for r in rows if r["kind"] == "claim"}
        drop, gate = (by_id[c] for c in cast["claims"])
        self.assertEqual(drop["witness"], "tray_drop")
        self.assertEqual(gate["depends_on"], [drop["claim_id"]])


class TransitionTest(unittest.TestCase):
    def test_a_two_charge_slot_spends_one(self):
        rows = _run()
        (cast,) = _verdicts(rows, "E", "cast")
        self.assertEqual(cast["before"]["charges"], 2)
        self.assertEqual(cast["after"]["charges"], 1)
        self.assertFalse(cast["surprise"])
        self.assertEqual(cast["until_ms"], 24000.0)
        self.assertEqual(_state_at(rows, "E", 22000.0)["mode"], "active")
        self.assertEqual(_state_at(rows, "E", 26000.0)["mode"], "idle")
        self.assertEqual(_state_at(rows, "E", 26000.0)["charges"], 1)

    def test_an_equip_and_release_spends_nothing(self):
        rows = _run()
        self.assertEqual(len(_verdicts(rows, "Q", "equip")), 1)
        (release,) = _verdicts(rows, "Q", "unequip")
        self.assertEqual(release["reason"], "equip_release")
        self.assertTrue(release["before"]["equipped"])
        self.assertEqual(release["before"]["held_level"], 1.0)
        self.assertEqual(release["after"]["level"], 1.0)
        self.assertFalse(release["surprise"])
        held = _state_at(rows, "Q", 31000.0)
        self.assertEqual((held["mode"], held["level"]), ("equipped", None))
        self.assertEqual(held["level_reason"], "equipped:teal_over_the_bar")
        self.assertEqual(held["charges_range"], [1, st.MAX_CHARGES_ANY])

    def test_an_x_cast_from_a_lit_bar(self):
        rows = _run()
        (cast,) = _verdicts(rows, "X", "cast")
        self.assertTrue(cast["before"]["castable"])
        self.assertFalse(cast["after"]["castable"])
        self.assertFalse(cast["surprise"])
        self.assertIsNone(_state_at(rows, "X", 10000.0)["pips"])

    def test_a_death_ends_the_kit(self):
        rows = _run()
        (end,) = _verdicts(rows, "C", "owner_death")
        self.assertEqual(end["t_ms"], 50000.0)
        dead = _state_at(rows, "C", 55000.0)
        self.assertEqual(dead["owner_alive"], False)
        self.assertEqual(dead["readable"], [])
        self.assertEqual(dead["unreadable_reason"], "kit_frozen:after_player_death")
        self.assertIsNone(dead["charges"])
        self.assertEqual(dead["charges_range"], [0, st.MAX_CHARGES_ANY])
        alive = _state_at(rows, "C", 45000.0)
        self.assertEqual(alive["owner_alive"], True)

    def test_a_drop_after_the_death_is_no_cast(self):
        deaths = (15000.0,)
        rows = _run(deaths)
        self.assertEqual(_verdicts(rows, "E", "cast"), [])
        drop = [v for v in _verdicts(rows, "E") if v["reason"] == "after_player_death"]
        self.assertEqual(len(drop), 1)
        self.assertEqual(drop[0]["transition"], "none")
        self.assertIn("kit frozen", drop[0]["stood_for"])


class UnreadTest(unittest.TestCase):
    def test_a_slot_without_a_fact_stores_null_with_a_reason(self):
        rows = _run()
        c = _state_at(rows, "C", 10000.0)
        self.assertIsNone(c["charges"])
        self.assertEqual(c["charges_reason"], "no-fact:tester:C:max_charges")
        self.assertEqual(c["charges_range"], [1, st.MAX_CHARGES_ANY])
        self.assertIn("no-fact:tester:C:max_charges", rows[0]["no_fact"])
        x = _state_at(rows, "X", 10000.0)
        self.assertIsNone(x["charges"])
        self.assertEqual(x["pips_reason"], "not_read:the_tray_reads_teal_not_pips")

    def test_outside_a_readable_phase_every_slot_is_unread(self):
        rows = _run()
        late = _state_at(rows, "X", 62000.0)
        self.assertEqual(late["mode"], "unreadable")
        self.assertIsNone(late["castable"])
        self.assertEqual(late["castable_reason"], late["unreadable_reason"])

    def test_a_half_level_on_a_one_charge_slot_is_no_count(self):
        self.assertEqual(st.charges_of(0.5, 1, None),
                         (None, "level_0.5_on_a_1_charge_slot", [0, 1]))
        self.assertEqual(st.charges_of(0.5, 2, None), (1, None, [1, 1]))
        self.assertEqual(st.charges_of(0.0, None, "no-fact"), (0, None, [0, 0]))


class LevelTest(unittest.TestCase):
    def test_the_low_tail_of_a_level_keeps_the_level(self):
        self.assertEqual(st._reading("C", 0.7)["level"], 1.0)
        self.assertEqual(st._reading("C", 0.46)["level"], 0.5)
        self.assertEqual(st._reading("C", 0.05)["level"], 0.0)
        self.assertTrue(st._reading("X", 0.78)["castable"])
        self.assertFalse(st._reading("X", 0.15)["castable"])
        self.assertTrue(st._reading("E", 1.4)["equipped"])
        self.assertFalse(st._reading("E", 1.1)["equipped"])


class FactTest(unittest.TestCase):
    def test_charge_and_duration_facts_parse(self):
        p = st.slot_parameters(AGENT, KIT, FACTS)
        self.assertEqual(p["E"]["max_charges"], 2)
        self.assertEqual(p["E"]["max_charges_fact"], "abilities/tester-tray-charges")
        self.assertEqual(p["E"]["duration_ms"], 4000.0)
        self.assertIsNone(p["Q"]["max_charges"])
        self.assertEqual(p["X"]["max_charges_reason"], "ult_slot:read_as_castable")

    def test_a_fact_naming_another_ability_is_not_used(self):
        p = st.slot_parameters(AGENT, {**KIT, "E": "Other"}, FACTS)
        self.assertIsNone(p["E"]["max_charges"])
        self.assertTrue(p["E"]["max_charges_reason"].startswith("fact-names-another-ability"))


class InvariantTest(unittest.TestCase):
    def test_the_synthetic_round_breaks_no_invariant(self):
        inv = _run()[0]["invariants"]
        self.assertEqual({k: v for k, v in inv.items() if isinstance(v, int) and v}, {})

    def test_a_cast_from_an_empty_slot_is_counted(self):
        rows = _run()
        cast = _verdicts(rows, "E", "cast")[0]
        cast["before"] = {**cast["before"], "charges_range": [0, 0]}
        self.assertEqual(st.invariant_violations(rows)["1_cast_without_a_charge"], 1)


class DeterminismTest(unittest.TestCase):
    def test_two_runs_store_the_same_rows(self):
        self.assertEqual(json.dumps(_run(), sort_keys=True), json.dumps(_run(), sort_keys=True))


if __name__ == "__main__":
    unittest.main()
