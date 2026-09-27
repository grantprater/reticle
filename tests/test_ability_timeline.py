import json
import tempfile
import unittest
from pathlib import Path

from reticle.ability_timeline import (_step_ms, build_timeline, player_tray_casts,
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


def _drop(t, slot, forced=False, frm=1.0):
    return {"t_ms": float(t), "slot": slot, "from": frm, "to": 0.0, "forced": forced,
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
                         second_lives_ms=[50000.0], revives_ms=[51000.0])
        self.assertTrue(got[(20000.0, "E")]["player_cast"])
        # A badge or a revive undoes nothing for an agent without the mechanic.
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

    def test_clove_without_a_revive_entry_is_dead(self):
        got = self._gate([_drop(50500, "X")], [50000.0], agent="Clove")
        self.assertEqual(got[(50500.0, "X")]["reason"], "after_player_death")
        # A revive after her next death undoes only the death it follows.
        got = self._gate([_drop(50500, "X"), _drop(62000, "E")], [50000.0, 60000.0],
                         agent="Clove", revives_ms=[61000.0])
        self.assertEqual(got[(50500.0, "X")]["reason"], "after_player_death")
        self.assertEqual(got[(62000.0, "E")]["reason"], "after_player_death")


if __name__ == "__main__":
    unittest.main()
