"""The local player's kit as a state per slot (`adjudication.ability_state`),
on a synthetic round: record shapes, charges, an equip, an ult, a death, the
unread values, the charge prior from facts and the wiki harvest, and
determinism."""
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


def _run(deaths=(50000.0,), params=None):
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
                         agent=agent,
                         params=params or st.slot_parameters(AGENT, KIT, FACTS),
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
        self.assertEqual(held["charges_range"], [1, st.MAX_SEGMENTS_READ])

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
        self.assertEqual(dead["charges_range"], [0, st.MAX_SEGMENTS_READ])
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
        self.assertEqual(c["charges_range"], [1, st.MAX_SEGMENTS_READ])
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


#: A wiki harvest in the shape of `reference/abilities.json`: Tester's E
#: disagrees with the fact, KAY/O's Q is not a count, Pooler's C is a pool
#: by fact and its E holds more than the two segments the reader interprets.
CATALOGUE = {"source": {"wiki": "test"}, "harvested": "2026-09-04", "agents": {
    "Tester": {"abilities": [
        {"name": "Widget", "slot": "Grenade", "key": "C", "charges": "1"},
        {"name": "Lamp", "slot": "Ability1", "key": "Q", "charges": "2"},
        {"name": "Twin Shot", "slot": "Ability2", "key": "E", "charges": "1"},
        {"name": "Finale", "slot": "Ultimate", "key": "X", "charges": "Weapon Equip"},
        {"name": "Idle", "slot": "Passive", "key": None, "charges": None}]},
    "KAY/O": {"abilities": [
        {"name": "FRAG/ment", "slot": "Grenade", "key": "C", "charges": "1"},
        {"name": "FLASH/drive", "slot": "Ability1", "key": "Q", "charges": "2 (shared charges)"},
        {"name": "ZERO/point", "slot": "Ability2", "key": "E", "charges": None}]},
    "Pooler": {"abilities": [
        {"name": "Regrow", "slot": "Grenade", "key": "C", "charges": "1"},
        {"name": "Big Pack", "slot": "Ability2", "key": "E", "charges": "3"}]}}}
POOL = {"abilities/pooler-regrow-resource-bar": Fact(
    domain="abilities", id="pooler-regrow-resource-bar", kind="rule", known="player",
    since="2026-09-27", subject="pooler:regrow",
    claim="Pooler's Regrow in slot C draws on a pool drawn as a resource bar, not as charges.")}


class PriorTest(unittest.TestCase):
    def test_a_fact_outranks_the_catalogue_and_records_the_conflict(self):
        e = st.charge_priors(FACTS, catalogue=CATALOGUE)[("tester", "E")]
        self.assertEqual((e["max_charges"], e["source"], e["fact"]),
                         (2, "player", "abilities/tester-tray-charges"))
        self.assertEqual(e["conflict"], {"kind": "count", "player": 2, "catalogue": 1,
                                         "fact": "abilities/tester-tray-charges"})
        p = st.slot_parameters(AGENT, KIT, FACTS, catalogue=CATALOGUE)
        self.assertEqual((p["E"]["max_charges"], p["E"]["max_charges_source"]), (2, "player"))
        self.assertEqual(p["E"]["max_charges_conflict"]["catalogue"], 1)

    def test_the_catalogue_fills_a_slot_without_a_fact(self):
        p = st.slot_parameters(AGENT, KIT, FACTS, catalogue=CATALOGUE)
        self.assertEqual((p["C"]["max_charges"], p["C"]["max_charges_source"]), (1, "catalogue"))
        self.assertEqual((p["Q"]["max_charges"], p["Q"]["max_charges_source"]), (2, "catalogue"))
        self.assertIsNone(p["C"]["max_charges_fact"])
        self.assertIsNone(p["C"]["max_charges_reason"])
        self.assertEqual(p["C"]["max_charges_catalogue"]["path"], st.CATALOGUE_PATH)
        self.assertEqual(p["C"]["max_charges_catalogue"]["harvested"], "2026-09-04")
        self.assertIsNone(p["C"]["max_charges_conflict"])

    def test_the_harvest_slots_map_to_the_tray_keys(self):
        pri = st.charge_priors({}, catalogue=CATALOGUE)
        self.assertEqual({s for a, s in pri if a == "tester"}, set(st.SLOTS))
        self.assertEqual(pri[("tester", "C")]["catalogue"]["slot"], "Grenade")
        self.assertEqual(pri[("tester", "Q")]["catalogue"]["slot"], "Ability1")
        self.assertEqual(pri[("tester", "E")]["catalogue"]["slot"], "Ability2")
        self.assertEqual(pri[("tester", "X")]["catalogue"]["slot"], "Ultimate")
        self.assertFalse(any("Idle" == (v["catalogue"] or {}).get("ability") for v in pri.values()))
        self.assertEqual(st.slot_parameters(AGENT, KIT, {}, catalogue=CATALOGUE)["X"]
                         ["max_charges_reason"], "ult_slot:read_as_castable")

    def test_a_string_that_is_not_a_count_gives_a_reason(self):
        pri = st.charge_priors({}, catalogue=CATALOGUE)
        self.assertEqual(pri[("tester", "X")]["reason"], "catalogue_non_numeric")
        self.assertEqual(pri[("kayo", "Q")]["reason"], "catalogue_non_numeric")
        self.assertEqual(pri[("kayo", "E")]["reason"], "catalogue_missing")
        # The lineup's asset spelling and the harvest's name key alike.
        p = st.slot_parameters("KAY_O", {"C": "FRAG/ment", "Q": "FLASH/drive"}, {},
                               catalogue=CATALOGUE)
        self.assertEqual((p["C"]["max_charges"], p["C"]["max_charges_source"]), (1, "catalogue"))
        self.assertIsNone(p["Q"]["max_charges"])
        self.assertEqual(p["Q"]["max_charges_reason"], "no-fact:kayo:Q:max_charges")
        self.assertEqual(p["Q"]["max_charges_prior_reason"], "catalogue_non_numeric")

    def test_no_catalogue_or_no_entry_is_stated(self):
        p = st.slot_parameters(AGENT, KIT, FACTS)
        self.assertIsNone(p["C"]["max_charges"])
        self.assertEqual(p["C"]["max_charges_prior_reason"], "no_fact")
        self.assertEqual(p["E"]["max_charges"], 2)
        q = st.slot_parameters("Stranger", {"C": "Thing"}, FACTS, catalogue=CATALOGUE)
        self.assertEqual(q["C"]["max_charges_reason"], "no-fact:stranger:C:max_charges")
        self.assertEqual(q["C"]["max_charges_prior_reason"], "catalogue_missing")

    def test_a_pool_fact_refuses_the_catalogue_and_a_count_above_two_stands(self):
        pri = st.charge_priors(POOL, catalogue=CATALOGUE)
        c = pri[("pooler", "C")]
        self.assertEqual((c["max_charges"], c["source"], c["reason"]), (None, None, "resource_bar"))
        self.assertEqual(c["conflict"]["kind"], "resource_bar")
        self.assertEqual(c["conflict"]["catalogue"], 1)
        e = pri[("pooler", "E")]
        self.assertEqual((e["max_charges"], e["source"], e["reason"], e["conflict"]),
                         (3, "catalogue", None, None))
        p = st.slot_parameters("Pooler", {"C": "Regrow", "E": "Big Pack"}, POOL,
                               catalogue=CATALOGUE)
        self.assertEqual(p["C"]["max_charges_prior_reason"],
                         "resource_bar:abilities/pooler-regrow-resource-bar")

    def test_a_catalogue_naming_another_ability_is_not_used(self):
        p = st.slot_parameters(AGENT, {**KIT, "C": "Gizmo"}, FACTS, catalogue=CATALOGUE)
        self.assertIsNone(p["C"]["max_charges"])
        self.assertEqual(p["C"]["max_charges_prior_reason"],
                         "catalogue-names-another-ability:Widget")

    def test_state_rows_name_their_source_and_coverage_lists_the_conflicts(self):
        rows = _run(params=st.slot_parameters(AGENT, KIT, FACTS, catalogue=CATALOGUE))
        c = _state_at(rows, "C", 10000.0)
        self.assertEqual((c["charges"], c["charges_source"]), (1, "catalogue"))
        self.assertEqual(_state_at(rows, "E", 10000.0)["charges_source"], "player")
        self.assertIsNone(_state_at(rows, "X", 10000.0)["charges_source"])
        self.assertEqual(_state_at(rows, "C", 55000.0)["charges_source"], "catalogue")
        (cast,) = _verdicts(rows, "E", "cast")
        self.assertEqual(cast["before"]["charges_source"], "player")
        cov = rows[0]
        self.assertEqual(cov["charges_source"], {"C": "catalogue", "Q": "catalogue",
                                                 "E": "player", "X": None})
        self.assertEqual([(x["slot"], x["kind"]) for x in cov["charge_conflicts"]],
                         [("E", "count")])
        self.assertEqual(cov["slots_without_count"], [])
        self.assertGreater(cov["charges_source_readable_slot_samples"]["catalogue"], 0)
        # E reads half after its cast: two charges draw a segment there.
        self.assertGreater(cov["segments"]["E"]["agree"], 0)
        self.assertEqual(cov["segments_disagree"], 0)

    def test_the_prior_never_overwrites_a_half_reading(self):
        # Without the fact, the catalogue's one Twin Shot meets a half bar.
        rows = _run(params=st.slot_parameters(AGENT, KIT, {}, catalogue=CATALOGUE))
        e = _state_at(rows, "E", 26000.0)
        self.assertEqual(e["level"], 0.5)
        self.assertIsNone(e["charges"])
        self.assertEqual(e["charges_reason"], "level_0.5_on_a_1_charge_slot")
        self.assertEqual(e["charges_source"], "catalogue")
        cov = rows[0]
        self.assertGreater(cov["segments"]["E"]["disagree"], 0)
        self.assertEqual(cov["segments"]["E"]["agree"], 0)
        self.assertEqual(cov["segments_disagree"],
                         cov["invariants"]["1_level_outside_the_segments"])

    def test_a_slot_without_a_count_is_listed(self):
        cov = _run()[0]
        self.assertEqual([(x["slot"], x["prior_reason"]) for x in cov["slots_without_count"]],
                         [("C", "no_fact"), ("Q", "no_fact")])
        self.assertEqual(cov["charge_conflicts"], [])

    def test_the_prior_is_deterministic(self):
        params = st.slot_parameters(AGENT, KIT, FACTS, catalogue=CATALOGUE)
        self.assertEqual(json.dumps(_run(params=params), sort_keys=True),
                         json.dumps(_run(params=params), sort_keys=True))


def _fact(fid, subject, claim, known="player"):
    return Fact(domain="abilities", id=fid, kind="rule", known=known, since="2026-09-28",
                subject=subject, claim=claim)


#: The confirmation of the fixture's harvest, and three Twin Shot charges.
CONFIRM = {st.CONFIRM_FACT: _fact(
    "catalogue-charge-counts-confirmed", "abilities:charges",
    "The charge counts that the wiki harvest of 2026-09-04 (reference/abilities.json) "
    "gives for slots C, Q and E are the game's counts.")}
THREE = {"abilities/tester-twin-shot-charges": _fact(
    "tester-twin-shot-charges", "tester:twin shot", "Tester has three Twin Shot charges in slot E.")}
#: One pool of stars that three slots spend.
STARRY = {"abilities/starry-stars-shared": _fact(
    "starry-stars-shared", "starry:stars",
    "Starry's Pull in slot C, Pulse in slot Q and Cloud in slot E each expend her stars.")}
STARRY_CAT = {"harvested": "2026-09-04", "agents": {"Starry": {"abilities": [
    {"name": "Pull", "slot": "Grenade", "charges": "1"},
    {"name": "Pulse", "slot": "Ability1", "charges": None},
    {"name": "Cloud", "slot": "Ability2", "charges": None}]}}}


class CountsAboveTwoTest(unittest.TestCase):
    def test_the_charge_clause_parses_counts_to_twelve_and_digits(self):
        got = st.charge_facts({
            "abilities/a-charges": _fact("a-charges", "a:x", "A has three Sky Smoke charges in slot E."),
            "abilities/b-charges": _fact("b-charges", "b:x", "B has eight Headhunter charges in slot Q."),
            "abilities/c-charges": _fact("c-charges", "c:x", "C has 8 rounds in slot Q."),
            "abilities/d-charges": _fact("d-charges", "d:x", "D has twelve darts in slot C.")})
        self.assertEqual({k: v["max_charges"] for k, v in got.items()},
                         {("a", "E"): 3, ("b", "Q"): 8, ("c", "Q"): 8, ("d", "C"): 12})
        self.assertEqual(got[("b", "Q")]["clause"], "eight Headhunter charges in slot Q")

    def test_the_registry_gives_three_eight_and_the_shared_stars(self):
        from reticle import domain
        facts = domain.load()
        counts = st.charge_facts(facts)
        self.assertEqual(counts[("brimstone", "E")]["max_charges"], 3)
        self.assertEqual(counts[("chamber", "Q")]["max_charges"], 8)
        # Every other count still reads one or two.
        self.assertEqual({v["max_charges"] for k, v in counts.items()
                          if k not in {("brimstone", "E"), ("chamber", "Q")}}, {1, 2})
        self.assertEqual(st.shared_pool_facts(facts),
                         {("astra", s): "abilities/astra-stars-shared" for s in "CQE"})
        self.assertEqual(st._confirmed_harvest(facts),
                         (st.CONFIRM_FACT, "player", "2026-09-04"))
        seg = " ".join(facts["hud/ability-tray-charge-segments"].claim.split())
        self.assertIn("unobserved", seg)
        self.assertNotIn("No ability has more than two charges (", seg)

    def test_a_count_above_two_is_kept_and_its_segments_refused(self):
        why = st.SEGMENTS_UNOBSERVED
        self.assertEqual(st.charges_of(1.0, 3, None), (None, why, [1, 3]))
        self.assertEqual(st.charges_of(0.5, 8, None), (None, why, [0, 8]))
        self.assertEqual(st.charges_of(0.0, 8, None), (0, None, [0, 0]))
        self.assertEqual(st.charges_of(None, 8, None), (None, "unread_level", [0, 8]))
        # Two charges still read by segment.
        self.assertEqual(st.charges_of(0.5, 2, None), (1, None, [1, 1]))
        p = st.slot_parameters(AGENT, KIT, THREE, catalogue=CATALOGUE)
        self.assertEqual((p["E"]["max_charges"], p["E"]["max_charges_source"]), (3, "player"))
        rows = _run(params=p)
        full, half = _state_at(rows, "E", 10000.0), _state_at(rows, "E", 26000.0)
        self.assertEqual((full["charges"], full["charges_reason"], full["charges_range"],
                          full["charges_source"]), (None, why, [1, 3], "player"))
        self.assertEqual((half["charges"], half["charges_reason"], half["charges_range"]),
                         (None, why, [0, 3]))
        self.assertEqual(_state_at(rows, "E", 55000.0)["charges_range"], [0, 3])
        cov = rows[0]
        self.assertGreater(cov["segments"]["E"]["unscored"], 0)
        self.assertEqual((cov["segments"]["E"]["agree"], cov["segments"]["E"]["disagree"]),
                         (0, 0))
        self.assertGreater(cov["charges_unread_readable_slot_samples"][why], 0)
        self.assertEqual(cov["invariants"]["1_level_outside_the_segments"], 0)
        self.assertEqual(cov["invariants"]["1_cast_without_a_charge"], 0)
        # The catalogue's one Twin Shot disagrees with the fact's three.
        self.assertEqual(p["E"]["max_charges_conflict"]["catalogue"], 1)

    def test_a_shared_pool_takes_no_count(self):
        pri = st.charge_priors({**STARRY, **CONFIRM}, catalogue=STARRY_CAT)
        for s in "CQE":
            self.assertEqual((pri[("starry", s)]["max_charges"], pri[("starry", s)]["reason"],
                              pri[("starry", s)]["fact"]),
                             (None, "shared_pool", "abilities/starry-stars-shared"))
        self.assertEqual(pri[("starry", "C")]["conflict"],
                         {"kind": "shared_pool", "player": "shared_pool", "catalogue": 1,
                          "fact": "abilities/starry-stars-shared"})
        self.assertIsNone(pri[("starry", "Q")]["conflict"])
        p = st.slot_parameters("Starry", {"C": "Pull", "Q": "Pulse", "E": "Cloud"},
                               {**STARRY, **CONFIRM}, catalogue=STARRY_CAT)
        self.assertEqual(p["C"]["max_charges_reason"], "no-fact:starry:C:max_charges")
        self.assertEqual(p["C"]["max_charges_prior_reason"],
                         "shared_pool:abilities/starry-stars-shared")

    def test_a_confirmed_harvest_count_names_its_fact_and_entry(self):
        pri = st.charge_priors({**FACTS, **CONFIRM}, catalogue=CATALOGUE)
        c = pri[("tester", "C")]
        self.assertEqual((c["max_charges"], c["source"], c["fact"], c["known"]),
                         (1, "catalogue-confirmed", st.CONFIRM_FACT, "player"))
        self.assertEqual((c["catalogue"]["path"], c["catalogue"]["harvested"],
                          c["catalogue"]["ability"]),
                         (st.CATALOGUE_PATH, "2026-09-04", "Widget"))
        # A per-ability fact still outranks the confirmed harvest.
        e = pri[("tester", "E")]
        self.assertEqual((e["source"], e["conflict"]["kind"]), ("player", "count"))
        self.assertEqual(pri[("tester", "X")]["reason"], "catalogue_non_numeric")
        # A harvest of another date is a prior again.
        later = {**CATALOGUE, "harvested": "2026-10-01"}
        self.assertEqual(st.charge_priors(CONFIRM, catalogue=later)[("tester", "C")]["source"],
                         "catalogue")
        # A pool fact still wins over a confirmed count, and the conflict stays.
        pool = st.charge_priors({**POOL, **CONFIRM}, catalogue=CATALOGUE)[("pooler", "C")]
        self.assertEqual((pool["max_charges"], pool["reason"], pool["conflict"]["kind"]),
                         (None, "resource_bar", "resource_bar"))
        p = st.slot_parameters(AGENT, KIT, {**FACTS, **CONFIRM}, catalogue=CATALOGUE)
        self.assertEqual((p["C"]["max_charges"], p["C"]["max_charges_source"],
                          p["C"]["max_charges_fact"]), (1, "catalogue-confirmed", st.CONFIRM_FACT))
        rows = _run(params=p)
        self.assertEqual(_state_at(rows, "C", 10000.0)["charges_source"], "catalogue-confirmed")
        self.assertEqual(rows[0]["charges_source"]["C"], "catalogue-confirmed")

    def test_the_registry_keeps_skye_regrowth_a_pool(self):
        from reticle import domain
        cat = {"harvested": "2026-09-04", "agents": {
            "Skye": {"abilities": [{"name": "Regrowth", "slot": "Grenade", "charges": "1"}]},
            "Brimstone": {"abilities": [{"name": "Sky Smoke", "slot": "Ability2", "charges": "3"}]},
            "Chamber": {"abilities": [{"name": "Headhunter", "slot": "Ability1", "charges": "8"}]},
            "Sova": {"abilities": [{"name": "Owl Drone", "slot": "Grenade", "charges": "1"}]},
            "Gekko": {"abilities": [{"name": "Wingman", "slot": "Ability1", "charges": "1"}]}}}
        pri = st.charge_priors(domain.load(), catalogue=cat)
        self.assertEqual(pri[("gekko", "Q")]["source"], "catalogue-confirmed")
        skye = pri[("skye", "C")]
        self.assertEqual((skye["max_charges"], skye["reason"], skye["conflict"]["kind"]),
                         (None, "resource_bar", "resource_bar"))
        self.assertEqual((pri[("brimstone", "E")]["max_charges"],
                          pri[("brimstone", "E")]["source"]), (3, "player"))
        self.assertEqual((pri[("chamber", "Q")]["max_charges"],
                          pri[("chamber", "Q")]["source"]), (8, "player"))
        self.assertEqual(pri[("sova", "C")]["source"], "player")


if __name__ == "__main__":
    unittest.main()
