"""The entity-event contract (docs/ENTITY_EVENTS.md, stage 0) and CONSUMER.

Each rejection the plan's stage 0 names is one test: a consumer row carrying
an uncertainty field, a name without a resolved verdict, an inferred time
stored as an observation time, a position without a frame, a state outside
its vocabulary and a null without a reason.
"""
import copy
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import architecture, domain
from reticle import entity_contract as ec
from reticle.store import Store

C = ec.ENTITY_CONTRACT_VERSION
OWNERS = {"death-victim", "round-entity-session", "agent-identity", "position-belief",
          "spike-carrier", "ability-state"}
FRAME = "baked:split__valorant-16x9"


def stamp(stream, inputs=None):
    return {"row": "stamp", ec.stamp_key(stream): "entity-test-0.1.0", "contract": C,
            "inputs": inputs or {"death": "death-adjudication-0.20.0"}}


def entity(eid="s:R1:E0001/P0", family="icon_track", kind="ally", lane="t", **kw):
    row = {"row": "entity", "entity_id": eid, "family": family, "kind": kind,
           "side": "ally", "round": 1,
           "lifetime": {"first_observed_ms": 153000.0, "last_observed_ms": 167266.7,
                        "began": None, "began_reason": "not_read: origin not independently observed",
                        "ended": None, "ended_reason": "not_read: right_censored",
                        "censored_at_ms": 167266.7},
           "identity": {"agent": "Jett", "ref": "identity:s:R1:E0001",
                        "arbiter": "agent-identity-0.9.0"},
           "player": None, "player_reason": "not_read: no slot key",
           "producer": {"owner": "round-entity-session", "version": "round-entity-0.9.0"},
           "lane": lane, "contract": C}
    row.update(kw)
    return row


def event(kind="pose", eid="s:R1:E0001/P0", lane="t", t=153000.0, **kw):
    row = {"row": "event", "event_id": f"{lane}:{eid}:{t}", "entity_id": eid, "kind": kind,
           "round": 1, "observed_ms": t, "observed_last_ms": t,
           "occurred": None, "occurred_reason": "not_read: no_owner_bound",
           "position": {"frame": FRAME, "x": 38.0, "y": 153.0},
           "orientation": None, "orientation_reason": "not_read: no pose owner",
           "state": None, "state_reason": "not_applicable",
           "evidence": [{"stream": "ally_icon", "id": "ally_icon:s:9180:0",
                         "version": "minimap-0.1.0"}],
           "producer": {"owner": "round-entity-session", "version": "round-entity-0.9.0"},
           "lane": lane, "contract": C}
    row.update(kw)
    return row


def death(lane="death"):
    return event(
        "death", eid="death:s:177000:0", lane=lane, t=177000.0,
        observed_last_ms=181500.0,
        position=None, position_reason="not_read: location null",
        orientation_reason="not_applicable",
        state={"cause": "gun", "weapon": "Ghost", "second_life": False, "revive": False},
        state_reason=None,
        identity={"agent": "Skye", "ref": "identity:death:s:177000:0",
                  "arbiter": "agent-identity-0.9.0"},
        participants={"killer": {"entity_id": "death:s:177000:0:killer",
                                 "identity": {"agent": "Phoenix",
                                              "ref": "identity:death:s:177000:0:killer",
                                              "arbiter": "agent-identity-0.9.0"}}},
        evidence=[{"stream": "death", "id": "death:s:177000:0",
                   "version": "death-adjudication-0.20.0"}],
        producer={"owner": "death-victim", "version": "death-adjudication-0.20.0"})


def clean(row):
    """Drop a `state_reason: None` a helper override left behind."""
    return {k: v for k, v in row.items() if not (k.endswith("_reason") and v is None)}


def estimate(eid="s:R1:E0001/P0", lane="t", t=170000.0):
    return event("estimate", eid=eid, lane=lane, t=t, observed_ms=None,
                 observed_ms_reason="not_observed: estimate",
                 observed_last_ms=None, observed_last_ms_reason="not_observed: estimate",
                 occurred={"lo_ms": t, "hi_ms": t, "basis": "owner estimate"},
                 state={"basis": "overlap continuation over two observations"},
                 evidence=[], producer={"owner": "position-belief", "version": "belief-0.1.0"})


def lane_rows(stream, *rows):
    return [stamp(stream)] + [clean(r) for r in rows]


def errors(stream, rows, **kw):
    kw.setdefault("owners", OWNERS)
    return ec.validate_lane(stream, rows, **kw)


class ValidEventTests(unittest.TestCase):
    def test_a_death_lane_passes_and_is_written(self):
        rows = lane_rows("entity_death", death())
        self.assertEqual(errors("entity_death", rows), [])
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            store.write_events("entity_death", "s", rows)
            self.assertEqual(store.events_version("entity_death", "s"), "entity-test-0.1.0")

    def test_an_icon_track_with_poses_and_coverage_passes(self):
        cov = {"row": "coverage", "lane": "t", "round": 1,
               "observed": [{"lo_ms": 153000.0, "hi_ms": 167266.7}],
               "unobserved": [{"lo_ms": 167266.7, "hi_ms": 170000.0,
                               "cause": "not_observed: widget_not_drawn"}],
               "contract": C}
        rows = lane_rows("entity_t", entity(), event(), event(t=153066.7), cov)
        self.assertEqual(errors("entity_t", rows), [])

    def test_a_verdict_map_accepts_resolved_refs(self):
        rows = lane_rows("entity_death", death())
        verdicts = {"identity:death:s:177000:0": "resolved",
                    "identity:death:s:177000:0:killer": "resolved"}
        self.assertEqual(errors("entity_death", rows, verdicts=verdicts), [])

    def test_an_ability_with_no_lifecycle_fact_is_only_observed(self):
        row = event("ability_object", t=97450.0,
                    state={"ability": "miks:nowhere smoke", "slot": "E", "phase": "observed",
                           "phase_reason": "no-fact:miks:E:lifecycle"})
        self.assertEqual(errors("entity_t", lane_rows("entity_t", row)), [])
        drawn = copy.deepcopy(row)
        drawn["state"]["phase"] = "drawn"
        self.assertTrue(any("not a state the facts give" in m
                            for _i, m in errors("entity_t", lane_rows("entity_t", drawn))))


class RejectionTests(unittest.TestCase):
    def assertRejects(self, rows, text, stream="entity_t", **kw):
        found = errors(stream, rows, **kw)
        self.assertTrue(any(text in m for _i, m in found),
                        f"no rejection containing {text!r} in {found}")

    # a name not from a resolved arbiter verdict
    def test_a_name_without_a_ref(self):
        row = death()
        del row["identity"]["ref"]
        self.assertRejects(lane_rows("entity_death", row), "without a ref", "entity_death")

    def test_a_name_from_another_producer(self):
        row = entity(identity={"agent": "Jett", "ref": "identity:x",
                               "arbiter": "round-entity-0.9.0"})
        self.assertRejects(lane_rows("entity_t", row), "not an agent-identity stamp")

    def test_a_name_from_an_unresolved_verdict(self):
        rows = lane_rows("entity_death", death())
        verdicts = {"identity:death:s:177000:0": "contested",
                    "identity:death:s:177000:0:killer": "resolved"}
        self.assertRejects(rows, "contested, not resolved", "entity_death", verdicts=verdicts)

    def test_a_name_outside_an_identity_block(self):
        row = death()
        row["participants"]["killer"] = {"entity_id": "death:s:177000:0:killer",
                                         "agent": "Phoenix"}
        self.assertRejects(lane_rows("entity_death", row), "outside an identity block",
                           "entity_death")

    # a missing reason on a null field
    def test_a_null_without_a_reason(self):
        row = event()
        del row["orientation_reason"]
        self.assertRejects(lane_rows("entity_t", row), "orientation is null with no")

    def test_a_reason_outside_the_four_forms(self):
        row = event(orientation_reason="no pose owner")
        self.assertRejects(lane_rows("entity_t", row), "is not one of the forms")

    def test_a_nested_null_without_a_reason(self):
        row = death()
        row["state"]["weapon"] = None
        self.assertRejects(lane_rows("entity_death", row), "state.weapon is null",
                           "entity_death")

    # an inferred time stored as an observation time
    def test_an_undeclared_time_key(self):
        row = event(origin_ms=150000.0)
        self.assertRejects(lane_rows("entity_t", row), "inferred time stored as an observation time")

    def test_an_estimate_with_an_observation_time(self):
        row = estimate()
        row["observed_ms"], row["observed_last_ms"] = 170000.0, 170000.0
        del row["observed_ms_reason"], row["observed_last_ms_reason"]
        self.assertRejects(lane_rows("entity_t", entity(), row), "an estimate is not observed")

    def test_an_observation_time_with_no_evidence(self):
        row = event(evidence=[])
        self.assertRejects(lane_rows("entity_t", row), "cites no observation")

    def test_an_inferred_interval_without_a_basis(self):
        row = event(occurred={"lo_ms": 1.0, "hi_ms": 2.0})
        self.assertRejects(lane_rows("entity_t", row), "with no basis")

    def test_an_inferred_lifetime_bound_as_a_bare_number(self):
        row = entity()
        row["lifetime"]["began"] = 150000.0
        del row["lifetime"]["began_reason"]
        self.assertRejects(lane_rows("entity_t", row), "lifetime.began is an inferred time")

    # an uncertainty field in consumer output
    def test_a_standing_in_consumer_output(self):
        self.assertRejects(lane_rows("entity_t", event(standing="resolved")),
                           "uncertainty field")

    def test_nested_alternatives_and_confidence(self):
        row = entity()
        row["lifetime"]["confidence"] = 0.9
        self.assertRejects(lane_rows("entity_t", row), "uncertainty field")
        row = death()
        row["state"]["alternatives"] = ["Skye", "Chamber"]
        self.assertRejects(lane_rows("entity_death", row), "uncertainty field", "entity_death")

    # the plan's other stage 0 rejections
    def test_a_position_without_a_frame(self):
        row = event(position={"x": 1.0, "y": 2.0})
        self.assertRejects(lane_rows("entity_t", row), "no declared frame")

    def test_a_state_outside_its_vocabulary(self):
        row = death()
        row["state"]["cause"] = "fall"
        self.assertRejects(lane_rows("entity_death", row), "outside its vocabulary",
                           "entity_death")
        spike = event("spike", state={"phase": "defused"}, state_reason=None)
        self.assertRejects(lane_rows("entity_t", clean(spike)), "outside its vocabulary")

    def test_an_orientation_in_a_convention_the_contract_does_not_name(self):
        row = event(orientation={"deg": 90.0, "convention": "reader"},
                    orientation_reason=None)
        self.assertRejects(lane_rows("entity_t", clean(row)), "not one the contract names")

    def test_a_lane_without_its_stamp(self):
        self.assertRejects([clean(death())], "opens with its stamp row", "entity_death")

    def test_store_refuses_a_rejected_lane_and_writes_nothing(self):
        row = death()
        del row["identity"]["ref"]
        with tempfile.TemporaryDirectory() as d:
            store = Store(d)
            with self.assertRaises(ValueError):
                store.write_events("entity_death", "s", lane_rows("entity_death", row))
            self.assertFalse(store.has_events("entity_death", "s"))


class BetweenObservationTests(unittest.TestCase):
    def test_the_rule_per_family(self):
        b = ec.between_observations
        self.assertEqual(b("icon_track", "ally"), "estimate")
        self.assertEqual(b("icon_track", "self"), "estimate")
        self.assertEqual(b("icon_track", "ally", alive=False), "ended")
        self.assertEqual(b("icon_track", "enemy"), "estimate")
        self.assertEqual(b("icon_track", "enemy", marked=True), "last_known")
        self.assertEqual(b("mark", "last_known"), "last_known")
        for family, kind in (("ping", "standard"), ("ability_object", "smoke"),
                             ("spike", "spike"), ("icon_track", "spectated")):
            self.assertEqual(b(family, kind), "not_observed")

    def test_only_the_player_has_an_estimate_owner(self):
        self.assertIsNone(ec.estimate_gap_reason("icon_track", "self"))
        self.assertEqual(ec.estimate_gap_reason("icon_track", "ally"), ec.NO_ESTIMATE_OWNER)
        self.assertIsNone(ec.estimate_gap_reason("ping", "standard"))

    def test_an_alive_ally_estimate_passes(self):
        self.assertEqual(errors("entity_t", lane_rows("entity_t", entity(), estimate())), [])

    def test_an_estimate_past_an_ally_death_is_rejected(self):
        ally = entity()
        ally["lifetime"]["ended"] = {"lo_ms": 167266.7, "hi_ms": 168000.0, "basis": "death"}
        del ally["lifetime"]["ended_reason"]
        found = errors("entity_t", lane_rows("entity_t", ally, estimate()))
        self.assertTrue(any("shows ended" in m for _i, m in found), found)

    def test_an_enemy_estimate_until_its_mark_and_none_after(self):
        enemy = entity("s:R1:X1", kind="enemy", side="enemy")
        mark = event("last_known", eid="s:R1:X1", t=165000.0,
                     producer={"owner": "death-victim", "version": "v"})
        before = estimate("s:R1:X1", t=160000.0)
        after = estimate("s:R1:X1", t=166000.0)
        found = errors("entity_t", lane_rows("entity_t", enemy, before, mark, after))
        self.assertEqual([i for i, m in found], [4], found)
        self.assertIn("shows last_known", found[0][1])

    def test_a_last_known_mark_on_an_ally_is_rejected(self):
        mark = event("last_known", t=165000.0)
        found = errors("entity_t", lane_rows("entity_t", entity(), mark))
        self.assertTrue(any("belongs to an enemy track" in m for _i, m in found), found)

    def test_an_estimate_for_a_family_that_shows_none(self):
        ping = entity("s:ping:1", family="ping", kind="standard", side=None,
                      side_reason="not_read: ping stores no pinger", identity=None,
                      identity_reason="not_applicable")
        found = errors("entity_t", lane_rows("entity_t", ping, estimate("s:ping:1")))
        self.assertTrue(any("shows not_observed" in m for _i, m in found), found)


def withheld(**kw):
    row = {"row": "withheld", "ledger_id": "round_entity:s:R1:E0004", "lane": "round_entity",
           "subject": {"row": "entity", "entity_id": "s:R1:E0004"},
           "standing": "disputed",
           "reason": "binding: round_entity binds death:s:205000:0 to Skye; the death owner names Chamber",
           "fields": {"identity": {"standing": "disputed", "alternatives": [
               {"value": "Skye", "owner": "round-entity-session", "evidence": ["round_entity:s:R1:E0004"]},
               {"value": "Chamber", "owner": "death-victim", "evidence": ["death:s:205000:0"]}]}},
           "returns_to": ["round-entity-session"], "residual": False, "contract": C}
    row.update(kw)
    return row


class LedgerTests(unittest.TestCase):
    S = "entity_round_entity_ledger"

    def check(self, row):
        return errors(self.S, [stamp(self.S), row])

    def test_the_plans_disputed_row_passes(self):
        self.assertEqual(self.check(withheld()), [])
        self.assertEqual(ec.lane_of(self.S), ("round_entity", True))

    def test_every_standing_but_resolved(self):
        for standing in ec.STANDINGS:
            fields = {} if standing != "disputed" else withheld()["fields"]
            found = self.check(withheld(standing=standing, fields=fields))
            self.assertEqual(bool(found), standing == "resolved", (standing, found))

    def test_a_dispute_needs_two_alternatives(self):
        row = withheld()
        row["fields"]["identity"]["alternatives"].pop()
        self.assertTrue(any("fewer than two" in m for _i, m in self.check(row)))

    def test_returns_to_names_a_real_owner(self):
        self.assertTrue(self.check(withheld(returns_to=[])))
        self.assertTrue(any("not an ownership.toml entry" in m
                            for _i, m in self.check(withheld(returns_to=["nobody"]))))

    def test_no_residual_reason_is_declared_yet(self):
        found = self.check(withheld(residual=True, residual_reason="audio_only_below_floor"))
        self.assertTrue(any("not a declared residual reason" in m for _i, m in found))

    def test_a_ledger_holds_no_consumer_rows(self):
        self.assertTrue(errors(self.S, [stamp(self.S), clean(death("round_entity"))]))

    def test_the_default_owners_come_from_ownership_toml(self):
        self.assertEqual(ec.validate_lane(self.S, [stamp(self.S), withheld()]), [])


class VocabularyTests(unittest.TestCase):
    def test_every_spike_state_cites_a_registered_fact(self):
        facts = domain.load()
        self.assertEqual(set(ec.SPIKE_STATES), {"dropped", "carried", "planted", "detonated",
                                              "last_known"})
        for state, keys in ec.SPIKE_STATES.items():
            for key in keys:
                self.assertIn(key, facts, state)

    def test_ping_kinds_are_the_ping_owners(self):
        from reticle.ping import PING_TYPES
        self.assertEqual(ec.PING_KINDS, frozenset(name for name, _h, _d in PING_TYPES))

    def test_ability_states_fall_back_to_observed(self):
        states, reason = ec.ability_states("Nobody", "nothing", "Q")
        self.assertEqual(states, frozenset({"observed"}))
        self.assertEqual(reason, "no-fact:Nobody:Q:lifecycle")

    def test_ability_states_read_a_lifecycle_facts_states(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "abilities.toml").write_text(textwrap.dedent("""
                [x-cloud-phases]
                claim = "x"
                kind = "lifecycle"
                known = "player"
                since = "2026-09-30"
                subject = "viper:poison cloud"
                states = ["thrown", "on", "off"]
            """), encoding="utf-8")
            facts = domain.load(Path(d))
            self.assertEqual(facts["abilities/x-cloud-phases"].states, ("thrown", "on", "off"))
            self.assertEqual(domain.validate(facts, root=Path(d)),
                             [("WARN", "1 fact(s) nothing cites -- the lost-in-the-shuffle "
                                       "failure: abilities/x-cloud-phases")])

    def test_states_on_a_fact_that_is_no_lifecycle_is_an_error(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "minimap.toml").write_text(textwrap.dedent("""
                [x]
                claim = "x"
                kind = "appearance"
                known = "player"
                since = "2026-09-30"
                states = ["a"]
            """), encoding="utf-8")
            found = domain.validate(domain.load(Path(d)), root=Path(d))
            self.assertTrue(any(level == "ERROR" and "lists states" in m for level, m in found))


CONSUMER_DECL = """
[layers]
order = ["foundation", "readers", "adjudication", "entities", "consumers"]

[foundation]
claim = "x"
modules = ["store"]

[readers]
claim = "x"
modules = ["minimap"]

[adjudication]
claim = "x"
modules = ["death"]

[entities]
claim = "x"
modules = ["entity_events"]

[consumers]
claim = "x"
modules = ["viewer", "clips"]
review = ["viewer"]
read_through = "entity_events"
forbidden_layers = ["readers", "adjudication"]
forbidden_calls = ["read_events", "events_path", "read_table"]
forbidden_imports = ["pyarrow.parquet"]
"""


class ConsumerCheckTests(unittest.TestCase):
    def run_check(self, sources, extra=""):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "architecture.toml").write_text(CONSUMER_DECL + extra, encoding="utf-8")
            (root / "reticle").mkdir()
            base = {"store": "", "minimap": "", "death": "", "entity_events": "",
                    "viewer": "from .entity_events import x\n", "clips": ""}
            base.update(sources)
            for name, text in base.items():
                (root / "reticle" / f"{name}.py").write_text(textwrap.dedent(text), encoding="utf-8")
            data = architecture.load(root / "architecture.toml")
            return architecture.verify_consumers(data, root)

    def errors_of(self, found):
        return [m for level, m in found if level == "ERROR"]

    def test_a_clean_consumer_passes(self):
        self.assertEqual(self.run_check({}), [])

    def test_a_consumer_that_imports_a_reader_fails(self):
        found = self.errors_of(self.run_check({"clips": "from .minimap import fit\n"}))
        self.assertEqual(len(found), 1, found)
        self.assertIn("consumer `clips` import:minimap", found[0])

    def test_a_deferred_adjudication_import_fails_too(self):
        found = self.errors_of(self.run_check(
            {"clips": "def go():\n    from . import death\n"}))
        self.assertTrue(any("import:death" in m for m in found), found)

    def test_store_reads_and_parquet_and_events_paths_fail(self):
        src = """
            import pyarrow.parquet as pq
            def go(store, root):
                store.read_events("ping", "s")
                pq.read_table("x")
                return root / "events" / "ping"
        """
        uses = " ".join(self.errors_of(self.run_check({"clips": src})))
        for use in ("import:pyarrow.parquet", "call:read_events", "call:read_table",
                    "path:events"):
            self.assertIn(use, uses)

    def test_a_docstring_naming_events_is_prose(self):
        self.assertEqual(self.run_check({"clips": '"""reads events/<stream>."""\n'}), [])

    def test_ledger_only_in_review(self):
        call = "def go(ee):\n    return ee.ledger()\n"
        self.assertEqual(self.errors_of(self.run_check({"viewer": call})), [])
        found = self.errors_of(self.run_check({"clips": call}))
        self.assertTrue(any("calls `ledger`" in m for m in found), found)
        found = self.errors_of(self.run_check({"minimap": call}))
        self.assertTrue(any("`minimap` calls `ledger`" in m for m in found), found)

    def test_a_dated_exemption_warns_and_a_stale_one_is_reported(self):
        exempt = """
[[consumers.exemption]]
module = "clips"
uses = "import:minimap"
since = "2026-09-30"
until = "stage 1"
reason = "x"
"""
        found = self.run_check({"clips": "from .minimap import fit\n"}, exempt)
        self.assertEqual([lvl for lvl, _m in found], ["WARN"], found)
        self.assertIn("exempt until stage 1", found[0][1])
        found = self.run_check({}, exempt)
        self.assertTrue(any("no longer exists" in m for _l, m in found), found)
        undated = exempt.replace('since = "2026-09-30"\n', "")
        found = self.errors_of(self.run_check({"clips": "from .minimap import fit\n"}, undated))
        self.assertTrue(any("names no since" in m for m in found), found)

    def test_the_repository_passes(self):
        self.assertEqual([m for level, m in architecture.verify_consumers()
                          if level == "ERROR"], [])


if __name__ == "__main__":
    unittest.main()
