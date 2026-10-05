import json
import tempfile
import unittest
from pathlib import Path

from reticle.ability_timeline import (EMPTY_MAX, FULL_AFTER_MIN, FULL_LEVEL, FULL_MIN,
                                      _step_ms, build_timeline, player_tray_casts,
                                      write_timeline)


class AbilityTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("reference/assets/ability_sfx", "reference/assets/voicelines",
                     "manifests", "casts", "labels/ability",
                     "labels/ability_candidates", "series"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        ref = {"harvested": "test", "agents": {"Omen": {"abilities": [
            {"name": "Shrouded Step", "slot": "Grenade", "key": "C"},
        ]}}}
        (self.root / "reference/abilities.json").write_text(json.dumps(ref))
        man = {"session_id": "abc123", "source_profile": "p",
               "source": {"path": str(self.root / "missing.mp4"),
                          "duration_ms": 10000, "content_key": "k"},
               "tags": ["ability-demo", "omen"]}
        (self.root / "manifests/abc123.json").write_text(json.dumps(man))
        (self.root / "casts/abc123.step0.5.reader.json").write_text(
            json.dumps([[5.0, "C", 1.0, 0.0, False]]))
        (self.root / "reference/assets/ability_sfx/omen_C__abc123_5.0s.wav").write_bytes(b"sound")

    def tearDown(self):
        self.temp.cleanup()

    def test_drop_is_a_bounded_candidate_with_unresolved_semantics(self):
        got = build_timeline(self.root)
        claim = got["use_claims"][0]
        self.assertEqual(claim["occurrence_interval_ms"], [4500.0, 5000.0])
        self.assertIsNone(claim["transition"])
        self.assertIn("end", claim["transition_alternatives"])
        self.assertFalse(claim["minimap_required"])
        self.assertEqual(claim["ability_id"], "omen:shrouded step")

    def test_source_linked_audio_is_reference_availability(self):
        got = build_timeline(self.root)
        claim = got["use_claims"][0]
        self.assertEqual(len(claim["audio_reference_candidates"]), 1)
        self.assertIn("not independent detections", got["manifest"]["limits"][1])

    def test_output_is_deterministic(self):
        bundle = build_timeline(self.root)
        a = write_timeline(bundle, self.root / "a")
        b = write_timeline(bundle, self.root / "b")
        self.assertEqual((a / "use_claims.jsonl").read_bytes(),
                         (b / "use_claims.jsonl").read_bytes())

    def test_equivalent_reader_caches_do_not_duplicate_game_events(self):
        (self.root / "casts/abc123.step0.5.other.json").write_text(
            json.dumps([[5.0, "C", 1.0, 0.0, False]]))
        got = build_timeline(self.root)
        self.assertEqual(len(got["use_claims"]), 1)
        self.assertEqual(len(got["use_claims"][0]["source_evidence"]), 2)
        self.assertEqual(got["manifest"]["summary"]["equivalent_cache_rows_collapsed"], 1)

    def test_numeric_reader_hash_is_not_part_of_sampling_step(self):
        self.assertEqual(_step_ms("casts/demo.step0.5.84229831.json"), 500.0)


def _drop(t, slot, forced=False, frm=1.0, to=0.0):
    return {"t_ms": float(t), "slot": slot, "from": frm, "to": to, "forced": forced,
            "suspect": forced, "cooccur": False}


#: One round from 0 to 100 s, closing at 108 s, all of it live.
ROUND = [{"t_start_ms": 0.0, "t_end_ms": 100000.0, "t_close_ms": 108000.0}]


class GateDeathTests(unittest.TestCase):
    """Which deaths end the player's kit (`player_tray_casts`)."""

    def _gate(self, drops, deaths, **kw):
        rows = player_tray_casts(drops, lambda t: "round_live", ROUND, deaths, **kw)
        return {(r["t_ms"], r["slot"]): r for r in rows}

    def test_an_ordinary_death_ends_the_kit(self):
        got = self._gate([_drop(20000, "E"), _drop(52000, "X")], [50000.0], agent="Sova",
                         second_lives_ms=[50000.0])
        self.assertTrue(got[(20000.0, "E")]["player_cast"])
        # A badge undoes nothing for an agent without the mechanic.
        self.assertEqual(got[(52000.0, "X")]["reason"], "after_player_death")
        self.assertEqual(got[(52000.0, "X")]["kit_end_ms"], 50000.0)

    def test_a_run_it_back_death_does_not_end_phoenix_kit(self):
        drops = [_drop(52000, "X"), _drop(70000, "Q"), _drop(81000, "C")]
        got = self._gate(drops, [50000.0, 80000.0], agent="Phoenix",
                         second_lives_ms=[50000.0])
        self.assertTrue(got[(52000.0, "X")]["player_cast"])
        self.assertTrue(got[(70000.0, "Q")]["player_cast"])
        self.assertEqual(got[(81000.0, "C")]["reason"], "after_player_death")
        self.assertEqual(got[(52000.0, "X")]["kit_end_ms"], 80000.0)
        self.assertEqual(got[(52000.0, "X")]["first_player_death_ms"], 50000.0)
        self.assertEqual(got[(52000.0, "X")]["undone_deaths"], [[50000.0, "run_it_back"]])

    def test_a_report_death_the_killfeed_missed_keeps_the_second_life_as_the_end(self):
        # The report counts one real death; the killfeed has none besides the
        # second life, so no instant after it is known to be Phoenix's.
        got = self._gate([_drop(52000, "X"), _drop(70000, "Q")], [50000.0], agent="Phoenix",
                         second_lives_ms=[50000.0], report_deaths={0.0: 1})
        self.assertEqual(got[(52000.0, "X")]["reason"], "after_player_death")
        self.assertEqual(got[(70000.0, "Q")]["reason"], "after_player_death")
        # A report that agrees with the killfeed undoes the second life.
        got = self._gate([_drop(52000, "X")], [50000.0], agent="Phoenix",
                         second_lives_ms=[50000.0], report_deaths={0.0: 0})
        self.assertTrue(got[(52000.0, "X")]["player_cast"])

    def test_clove_drop_after_her_death_meets_the_other_tests_when_she_revives(self):
        drops = [_drop(50500, "X"), _drop(60000, "E"), _drop(71000, "Q")]
        got = self._gate(drops, [50000.0, 70000.0], agent="Clove", revives_ms=[51500.0])
        self.assertTrue(got[(50500.0, "X")]["player_cast"])
        self.assertTrue(got[(60000.0, "E")]["player_cast"])
        self.assertEqual(got[(71000.0, "Q")]["reason"], "after_player_death")
        self.assertEqual(got[(50500.0, "X")]["undone_deaths"], [[50000.0, "not_dead_yet"]])
        # The death screen blanks the tray: a drop on an undrawn sample stays refused.
        got = self._gate([_drop(50000, "X", forced=True)], [50000.0, 70000.0], agent="Clove",
                         revives_ms=[51500.0])
        self.assertEqual(got[(50000.0, "X")]["reason"], "forced")

    def test_a_teammate_revive_returns_the_kit_after_the_player_was_dead(self):
        # A Sage revives the Sova player at 58 s: dead from the death (less
        # the lead) to the revive, alive with the kit after it.
        drops = [_drop(49500, "C"), _drop(54000, "E"), _drop(62000, "Q"),
                 _drop(80000, "X")]
        got = self._gate(drops, [50000.0, 79000.0], agent="Sova", revives_ms=[58000.0])
        for k in ((49500.0, "C"), (54000.0, "E"), (80000.0, "X")):
            self.assertEqual(got[k]["reason"], "after_player_death")
        self.assertTrue(got[(62000.0, "Q")]["player_cast"])
        self.assertEqual(got[(62000.0, "Q")]["undone_deaths"], [[50000.0, "revived"]])
        self.assertEqual(got[(62000.0, "Q")]["kit_end_ms"], 79000.0)
        # The span ends at the revive for a bridged drop too.
        bridged = {**_drop(60000, "Q"), "across_gap": True}
        got = self._gate([bridged, _drop(64000, "E")], [50000.0], agent="Sova",
                         revives_ms=[58000.0])
        self.assertTrue(got[(60000.0, "Q")]["player_cast"])
        self.assertTrue(got[(64000.0, "E")]["player_cast"])

    def test_an_own_ult_line_overturns_a_death_or_a_dark_tray_for_x(self):
        # Run It Back unread: the pips fall 2 s after the death that ends the
        # kit, 9 s after Phoenix's own line.
        got = self._gate([_drop(52000, "X")], [50000.0], agent="Phoenix",
                         own_lines_ms=[43000.0])
        r = got[(52000.0, "X")]
        self.assertTrue(r["player_cast"])
        self.assertEqual((r["refused_as"], r["line_ms"]), ("after_player_death", 43000.0))
        # The pass rests on the line, which the gate declares.
        self.assertEqual(r["rests_on"], [{"stream": "ult_cast", "owner": "adjudication.ult_cast",
                                          "t_ms": 43000.0}])
        # No line, or a line after the kit's end, overturns nothing.
        for lines in ([], [51000.0]):
            got = self._gate([_drop(52000, "X")], [50000.0], agent="Phoenix",
                             own_lines_ms=lines)
            self.assertEqual(got[(52000.0, "X")]["reason"], "after_player_death")
        # Clove empties X on the death screen; her line follows within 1.5 s.
        got = self._gate([_drop(60000, "X", forced=True)], [], agent="Clove",
                         own_lines_ms=[61000.0])
        self.assertEqual(got[(60000.0, "X")]["refused_as"], "forced")
        # Outside the window (1.5 s for any agent but Phoenix) it stays refused.
        got = self._gate([_drop(60000, "X", forced=True)], [], agent="Sova",
                         own_lines_ms=[62000.0])
        self.assertEqual(got[(60000.0, "X")]["reason"], "forced")
        # One line passes one drop, and none where a passed X drop holds it.
        got = self._gate([_drop(60000, "X", forced=True), _drop(60500, "X", forced=True)], [],
                         agent="Sova", own_lines_ms=[60400.0])
        self.assertEqual(sum(r["player_cast"] for r in got.values()), 1)
        self.assertTrue(got[(60500.0, "X")]["player_cast"])
        got = self._gate([_drop(30000, "X"), _drop(30500, "X", forced=True)], [],
                         agent="Sova", own_lines_ms=[30200.0])
        self.assertEqual(got[(30500.0, "X")]["reason"], "forced")
        # The charge tests still apply: a part-charged slot is no cast.
        got = self._gate([_drop(60000, "X", forced=True, frm=0.5)], [], agent="Sova",
                         own_lines_ms=[60000.0])
        self.assertEqual(got[(60000.0, "X")]["reason"], "forced")

    def test_a_gold_only_regrowth_drop_spends_the_rest_of_a_counted_pool(self):
        # A gold Regrowth bar is a partly spent pool, so its going empty is no
        # new purchase [domain:abilities/skye-regrowth-gold-bar-partly-spent]:
        # the teal drop that opened the pool is the cast.
        gold = {**_drop(30000, "C", frm=1.0, to=0.0), "witness": {"witnessed": True}}
        got = self._gate([_drop(20000, "C"), gold], [], agent="Skye", pool_slots=("C",))
        self.assertTrue(got[(20000.0, "C")]["player_cast"])
        self.assertNotIn("pool_gold_drop", got[(20000.0, "C")])
        r = got[(30000.0, "C")]
        self.assertTrue(r["pool_gold_drop"])
        self.assertFalse(r["player_cast"])
        self.assertEqual(r["reason"], "pool_rest")
        # An earlier refusal keeps its name: pool_rest is tested last.
        got = self._gate([gold], [], agent="Skye", pool_slots=("C",),
                         menu_at=lambda t: True)
        self.assertEqual(got[(30000.0, "C")]["reason"], "menu_open")
        # Only Regrowth's gold is a recorded fact: a pool slot of another
        # agent is marked, not refused, and a slot no pool fact names is
        # neither.
        got = self._gate([gold], [], agent="Viper", pool_slots=("C",))
        self.assertTrue(got[(30000.0, "C")]["pool_gold_drop"])
        self.assertTrue(got[(30000.0, "C")]["player_cast"])
        got = self._gate([gold], [], agent="Sova")
        self.assertNotIn("pool_gold_drop", got[(30000.0, "C")])
        self.assertTrue(got[(30000.0, "C")]["player_cast"])

    def test_ability_state_names_what_pool_rest_stood_for(self):
        from reticle.adjudication.ability_state import STOOD_FOR
        self.assertEqual(STOOD_FOR["pool_rest"][0], "none")

    def test_a_stabilised_kayo_keeps_his_kit(self):
        # Downed at 50 s, stabilised by a teammate's NULL/cmd revive at 56 s
        # [domain:abilities/kayo-null-cmd-stabilise-restores-kit]: dead while
        # downed, his kit back after it.
        from reticle.adjudication.death import player_revive_times
        v = {"kind": "death_verdict", "is_revive": True, "t_ms": 56000.0, "side": "ally",
             "killer": "Jett", "victim": "KAY_O", "weapon": "NULL/cmd"}
        for agent in ("KAY/O", "KAY_O"):
            revives = player_revive_times([v], agent)
            self.assertEqual(revives, [56000.0])
            got = self._gate([_drop(53000, "E"), _drop(60000, "Q")], [50000.0], agent=agent,
                             revives_ms=revives)
            self.assertEqual(got[(53000.0, "E")]["reason"], "after_player_death")
            self.assertTrue(got[(60000.0, "Q")]["player_cast"])
            self.assertEqual(got[(60000.0, "Q")]["undone_deaths"], [[50000.0, "revived"]])
        # NULL/cmd stabilises only KAY/O.
        self.assertEqual(player_revive_times([{**v, "victim": "Jett"}], "Jett"), [])

    def test_a_stored_line_pass_does_not_survive_a_run_without_the_line(self):
        # A full stored X row an earlier run passed on Phoenix's line at 43 s,
        # judged again with no own lines: the death refuses it, and nothing
        # the earlier run wrote comes back.
        stored = {**_drop(52000, "X"), "across_gap": False, "kind": "drop",
                  "player_cast": True, "reason": None, "refused_as": "after_player_death",
                  "line_ms": 43000.0, "pool_gold_drop": True, "numeral": "restarted",
                  "rests_on": [{"stream": "ult_cast", "owner": "adjudication.ult_cast",
                                "t_ms": 43000.0}]}
        r = self._gate([stored], [50000.0], agent="Phoenix")[(52000.0, "X")]
        self.assertFalse(r["player_cast"])
        self.assertEqual(r["reason"], "after_player_death")
        for f in ("refused_as", "line_ms", "rests_on", "pool_gold_drop", "numeral"):
            self.assertNotIn(f, r)
        # The same row with the line passes again, from this run's line.
        r = self._gate([stored], [50000.0], agent="Phoenix",
                       own_lines_ms=[44000.0])[(52000.0, "X")]
        self.assertTrue(r["player_cast"])
        self.assertEqual(r["line_ms"], 44000.0)

    def test_every_caller_gives_a_stored_drop_one_verdict(self):
        # `reticle tray` and ability-shapes hand the gate full rows; ult-cast,
        # ability-state and the audio fit hand it DROP_FIELDS. Both must agree.
        from reticle.adjudication.ult_cast import DROP_FIELDS
        stored = [{**_drop(30000, "C", frm=1.0, to=0.0), "across_gap": False,
                   "witness": {"witnessed": True}, "kind": "drop", "player_cast": True,
                   "reason": None, "phase": "round_live", "kit_end_ms": None},
                  {**_drop(30000, "E"), "across_gap": False, "kind": "drop"},
                  {**_drop(52000, "X"), "across_gap": True, "kind": "drop",
                   "player_cast": False, "reason": "stale"},
                  {**_drop(70000, "Q", frm=0.5), "across_gap": False, "kind": "drop"}]
        kw = dict(agent="Skye", pool_slots=("C",), own_lines_ms=[51500.0],
                  revives_ms=[49000.0])
        keys = ("player_cast", "reason", "pool_gold_drop", "refused_as", "line_ms", "rests_on")
        full = self._gate([dict(r) for r in stored], [48000.0], **kw)
        cut = self._gate([{k: r[k] for k in DROP_FIELDS if k in r} for r in stored],
                         [48000.0], **kw)
        self.assertEqual(full.keys(), cut.keys())
        for k in full:
            self.assertEqual({f: full[k].get(f) for f in keys},
                             {f: cut[k].get(f) for f in keys}, k)
        self.assertTrue(full[(30000.0, "C")]["pool_gold_drop"])

    def test_pool_slots_come_from_the_resource_bar_facts(self):
        from reticle.ability_timeline import pool_slots
        self.assertEqual(pool_slots("Skye"), (("C",), ["abilities/skye-regrowth-resource-bar"]))
        self.assertEqual(pool_slots("Sova"), ((), []))
        self.assertEqual(pool_slots(None), ((), []))

    def test_a_restock_numeral_witnesses_a_cooccurring_spend(self):
        # E and C fall in one sample; a numeral appears over E only.
        drops = [_drop(30000, "E"), _drop(30000, "C")]
        reads = [{"t_ms": 30000.0, "slot": "E", "numeral": "50", "value_s": 50.0}]
        got = self._gate(drops, [], agent="Sova", countdown_reads=reads)
        self.assertTrue(got[(30000.0, "E")]["player_cast"])
        self.assertEqual(got[(30000.0, "E")]["numeral"], "appeared")
        self.assertEqual(got[(30000.0, "C")]["reason"], "cooccur_among_casts")
        # No reads, or a slot whose numeral is no recorded spend witness.
        got = self._gate(drops, [], agent="Sova")
        self.assertEqual(got[(30000.0, "E")]["reason"], "cooccur_among_casts")
        q = [{**reads[0], "slot": "Q"}]
        got = self._gate([_drop(30000, "Q"), _drop(30000, "C")], [], agent="Skye",
                         countdown_reads=q)
        self.assertEqual(got[(30000.0, "Q")]["reason"], "cooccur_among_casts")
        # A numeral that keeps counting is no new spend.
        cont = [{"t_ms": 29000.0, "slot": "E", "numeral": "20", "value_s": 20.0},
                {"t_ms": 30000.0, "slot": "E", "numeral": "19", "value_s": 19.0}]
        got = self._gate(drops, [], agent="Sova", countdown_reads=cont)
        self.assertEqual(got[(30000.0, "E")]["numeral"], "continued")
        self.assertEqual(got[(30000.0, "E")]["reason"], "cooccur_among_casts")
        # The charge tests still apply after the numeral.
        got = self._gate([_drop(30000, "E", frm=1.3, to=0.98), _drop(30000, "C")], [],
                         agent="Sova", countdown_reads=reads)
        self.assertEqual(got[(30000.0, "E")]["reason"], "equip_release")

    def test_an_own_line_witnesses_a_cooccurring_x_drop(self):
        drops = [_drop(30000, "X"), _drop(30500, "C")]
        got = self._gate(drops, [], agent="Skye", own_lines_ms=[29600.0])
        self.assertEqual(got[(30000.0, "X")]["refused_as"], "cooccur_among_casts")
        self.assertEqual(got[(30500.0, "C")]["reason"], "cooccur_among_casts")

    def test_own_line_times_keep_lines_that_rest_on_no_tray_cast(self):
        from reticle.ability_timeline import own_line_times
        rows = [{"kind": "cast", "player_cast": True, "t_ms": 5.0, "rests_on": []},
                {"kind": "cast", "player_cast": True, "t_ms": 6.0,
                 "rests_on": [{"stream": "tray_drop"}]},
                {"kind": "cast", "player_cast": False, "t_ms": 7.0, "rests_on": []},
                {"kind": "refusal", "t_ms": 8.0}]
        self.assertEqual(own_line_times(rows), [5.0])

    def test_player_revive_times_names_the_player_as_the_revived(self):
        from reticle.adjudication.death import player_revive_times
        v = lambda t, **kw: {"kind": "death_verdict", "is_revive": True, "t_ms": t, **kw}
        res, ndy = dict(killer="Sage", weapon="Resurrection"), dict(weapon="Not Dead Yet")
        rows = [v(1.0, side="ally", victim="Skye", **res),
                v(2.0, side="enemy", victim="Skye", **res),
                v(3.0, side="ally", victim="Raze", **res),
                v(4.0, side="ally", victim=None, killer="Clove", kf_player_kill=True, **ndy),
                {"kind": "death_verdict", "t_ms": 5.0, "side": "ally", "victim": "Skye"},
                v(6.0, side="ally", victim="Clove", killer="Clove", **ndy)]
        self.assertEqual(player_revive_times(rows, "Skye"), [1.0])
        # Clove's own entry counts for a Clove player even with the victim unread.
        self.assertEqual(player_revive_times(rows, "Clove"), [4.0, 6.0])
        self.assertEqual(player_revive_times(rows, None), [])
        # A KAY/O stabilised from NULL/cmd returns his kit; a revive with its
        # icon unread does not.
        kayo = [v(7.0, side="ally", victim="KAY/O", killer="Sage", weapon="NULL/cmd"),
                v(8.0, side="ally", victim="KAY/O", killer="Sage", weapon=None)]
        self.assertEqual(player_revive_times(kayo, "KAY/O"), [7.0])

    def test_clove_without_a_revive_entry_is_dead(self):
        got = self._gate([_drop(50500, "X")], [50000.0], agent="Clove")
        self.assertEqual(got[(50500.0, "X")]["reason"], "after_player_death")
        # A revive after her next death undoes only the death it follows.
        got = self._gate([_drop(50500, "X"), _drop(62000, "E")], [50000.0, 60000.0],
                         agent="Clove", revives_ms=[61000.0])
        self.assertEqual(got[(50500.0, "X")]["reason"], "after_player_death")
        self.assertEqual(got[(62000.0, "E")]["reason"], "after_player_death")


class GateChargeTests(unittest.TestCase):
    """The ultimate casts only from a full X slot (`partial_charge`)."""

    def _gate(self, drops, deaths=(), **kw):
        rows = player_tray_casts(drops, lambda t: "round_live", ROUND, list(deaths), **kw)
        return {(r["t_ms"], r["slot"]): r for r in rows}

    def test_a_part_filled_x_drop_is_refused(self):
        got = self._gate([_drop(20000, "X", frm=0.36)])[(20000.0, "X")]
        self.assertFalse(got["player_cast"])
        self.assertEqual(got["reason"], "partial_charge")
        self.assertEqual(got["from"], 0.36)          # the reading stays as evidence

    def test_a_full_x_drop_passes(self):
        # Full within the reading's spread, and a fill above 1 is still full.
        for frm in (FULL_MIN, 0.9, 1.0, 1.18):
            got = self._gate([_drop(20000, "X", frm=frm)])[(20000.0, "X")]
            self.assertTrue(got["player_cast"], frm)
            self.assertIsNone(got["reason"])

    def test_the_rule_leaves_other_slots_alone(self):
        got = self._gate([_drop(20000, "Q", frm=0.4), _drop(40000, "C", frm=0.5)])
        self.assertTrue(got[(20000.0, "Q")]["player_cast"])
        self.assertTrue(got[(40000.0, "C")]["player_cast"])

    def test_the_refusal_stays_apart_from_the_others(self):
        drops = [_drop(10000, "X", frm=0.4),                  # partial_charge
                 _drop(30000, "X", frm=0.4, forced=True),     # forced first
                 _drop(50000, "X", frm=0.4), _drop(50500, "E"),  # co-occurring
                 _drop(81000, "X", frm=0.4)]                  # after the death
        got = self._gate(drops, [80000.0], agent="Sova")
        self.assertEqual({k: (r["player_cast"], r["reason"]) for k, r in got.items()},
                         {(10000.0, "X"): (False, "partial_charge"),
                          (30000.0, "X"): (False, "forced"),
                          (50000.0, "X"): (False, "cooccur_among_casts"),
                          (50500.0, "E"): (False, "cooccur_among_casts"),
                          (81000.0, "X"): (False, "after_player_death")})

    def test_a_part_filled_x_drop_still_taints_a_drop_beside_it(self):
        # Teal leaving a part-charged X slot is no release: a flash over the
        # whole tray leaves the same way (96aa1ae9b96f 673.0 s), so the
        # co-occurrence test still counts it.
        got = self._gate([_drop(20000, "X", frm=0.5), _drop(21000, "Q")])
        self.assertEqual(got[(21000.0, "Q")]["reason"], "cooccur_among_casts")
        self.assertEqual(got[(20000.0, "X")]["reason"], "cooccur_among_casts")


class GateLevelTests(unittest.TestCase):
    """A cast spends a charge: the X slot empties (`pips_lit`) and no slot is
    left at its full level (`equip_release`)."""

    def _gate(self, drops, deaths=(), **kw):
        rows = player_tray_casts(drops, lambda t: "round_live", ROUND, list(deaths), **kw)
        return {(r["t_ms"], r["slot"]): r for r in rows}

    def _one(self, slot, frm, to):
        return self._gate([_drop(20000, slot, frm=frm, to=to)])[(20000.0, slot)]

    def test_a_drop_that_spends_a_charge_passes(self):
        for slot, frm, to in (("X", 1.0, 0.0), ("X", 1.18, EMPTY_MAX), ("C", 1.0, 0.0),
                              ("C", 1.43, 0.0), ("E", 0.5, 0.0), ("Q", 1.05, 0.53)):
            got = self._one(slot, frm, to)
            self.assertTrue(got["player_cast"], (slot, frm, to))
            self.assertIsNone(got["reason"])

    def test_a_two_charge_slot_spending_one_charge_passes(self):
        # Two segments read 1.0, 0.5 and 0: a spent charge falls to the half level.
        got = self._gate([_drop(20000, "Q", frm=1.0, to=0.5), _drop(40000, "Q", frm=0.5)])
        self.assertTrue(got[(20000.0, "Q")]["player_cast"])
        self.assertTrue(got[(40000.0, "Q")]["player_cast"])

    def test_a_drop_to_the_full_level_is_equip_release(self):
        for slot, frm, to in (("C", 1.4, 0.99), ("Q", 1.43, 0.8), ("E", 1.05, FULL_AFTER_MIN),
                              ("Q", 1.6, 1.19)):
            got = self._one(slot, frm, to)
            self.assertFalse(got["player_cast"], (slot, frm, to))
            self.assertEqual(got["reason"], "equip_release")
            self.assertEqual(got["to"], to)            # the reading stays as evidence

    def test_an_x_drop_that_does_not_empty_is_pips_lit(self):
        for frm, to in ((1.03, 0.76), (1.0, 0.21), (1.33, 1.08)):
            got = self._one("X", frm, to)
            self.assertFalse(got["player_cast"], (frm, to))
            # 1.33 to 1.08 also leaves the slot full; the X test comes first.
            self.assertEqual(got["reason"], "pips_lit")

    def test_a_dip_before_the_cast_leaves_the_emptying_drop_as_the_cast(self):
        # 7010b3d62460: X 1.03 -> 0.76 at 1509.55 s, then 0.99 -> 0 at 1511.05 s.
        got = self._gate([_drop(20000, "X", frm=1.03, to=0.76), _drop(21500, "X", frm=0.99)])
        self.assertEqual(got[(20000.0, "X")]["reason"], "pips_lit")
        self.assertTrue(got[(21500.0, "X")]["player_cast"])

    def test_a_drop_refused_earlier_keeps_its_reason(self):
        drops = [_drop(10000, "X", frm=0.58, to=0.3),              # partial_charge first
                 _drop(30000, "C", frm=1.4, to=0.99, forced=True),  # forced first
                 _drop(50000, "C", frm=1.4, to=0.99), _drop(50500, "E"),  # co-occurring
                 _drop(81000, "Q", frm=1.4, to=0.99)]               # after the death
        got = self._gate(drops, [80000.0], agent="Sova")
        # The release at 50 s is tainted by the cast beside it, which it does
        # not taint in turn.
        self.assertEqual({k: (r["player_cast"], r["reason"]) for k, r in got.items()},
                         {(10000.0, "X"): (False, "partial_charge"),
                          (30000.0, "C"): (False, "forced"),
                          (50000.0, "C"): (False, "cooccur_among_casts"),
                          (50500.0, "E"): (True, None),
                          (81000.0, "Q"): (False, "after_player_death")})

    def test_a_released_slot_does_not_taint_a_cast_beside_it(self):
        # The player equips Q, which brightens its slot, then switches to E and
        # casts it: the release and the cast land in one sample.
        got = self._gate([_drop(20000, "Q", frm=1.25, to=0.97), _drop(20000, "E")])
        self.assertEqual(got[(20000.0, "Q")]["reason"], "cooccur_among_casts")
        self.assertTrue(got[(20000.0, "E")]["player_cast"])
        self.assertIsNone(got[(20000.0, "E")]["reason"])

    def test_an_ult_cast_beside_a_release_passes(self):
        # 3694746e4e54: X 1.01 -> 0 at 664.52 s, the player's own ult line at
        # 664.41 s, and C released from 1.32 to 0.99 at 665.0 s (moved into ROUND).
        got = self._gate([_drop(64517, "X", frm=1.01), _drop(65000, "C", frm=1.32, to=0.99)])
        self.assertTrue(got[(64517.0, "X")]["player_cast"])
        self.assertEqual(got[(65000.0, "C")]["reason"], "cooccur_among_casts")

    def test_only_a_release_from_above_the_full_level_is_quiet(self):
        # A slot at its full level that falls to it was not brightened: the
        # drop is `equip_release` but no release, and it taints.
        got = self._gate([_drop(20000, "C", frm=FULL_LEVEL, to=FULL_AFTER_MIN),
                          _drop(20000, "E")])
        self.assertEqual(got[(20000.0, "E")]["reason"], "cooccur_among_casts")
        self.assertEqual(got[(20000.0, "C")]["reason"], "cooccur_among_casts")

    def test_an_x_drop_the_charge_tests_refuse_still_taints(self):
        # A glow over a full X slot leaving it (75a55a296d3b 720.55 s) is no release.
        got = self._gate([_drop(20000, "X", frm=1.33, to=0.97), _drop(20500, "C", frm=1.01)])
        self.assertEqual(got[(20500.0, "C")]["reason"], "cooccur_among_casts")
        self.assertEqual(got[(20000.0, "X")]["reason"], "cooccur_among_casts")

    def test_releases_beside_nothing_else_keep_their_own_reason(self):
        got = self._gate([_drop(20000, "C", frm=1.4, to=0.99), _drop(20500, "Q", frm=1.3, to=0.95)])
        self.assertEqual(got[(20000.0, "C")]["reason"], "equip_release")
        self.assertEqual(got[(20500.0, "Q")]["reason"], "equip_release")

    def test_a_menu_dim_still_refuses_every_slot(self):
        # The menu dims every slot at one instant [domain:hud/menu-dims-tray];
        # bars land on fractions, not on the full level, so none is a release.
        dim = [_drop(20000, "C", frm=1.0, to=0.45), _drop(20000, "Q", frm=0.99, to=0.4),
               _drop(20000, "E", frm=1.0, to=0.55)]
        got = self._gate(dim)
        self.assertEqual({k: r["reason"] for k, r in got.items()},
                         {k: "cooccur_among_casts" for k in got})
        # A brightened slot the dim leaves at the full level is quiet, and the
        # other slots still taint each other and it.
        dim[1] = _drop(20000, "Q", frm=1.3, to=0.8)
        got = self._gate(dim)
        self.assertEqual({k: r["reason"] for k, r in got.items()},
                         {k: "cooccur_among_casts" for k in got})


if __name__ == "__main__":
    unittest.main()
