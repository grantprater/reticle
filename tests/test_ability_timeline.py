import json
import tempfile
import unittest
from pathlib import Path

from reticle.ability_timeline import _step_ms, build_timeline, write_timeline


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


if __name__ == "__main__":
    unittest.main()
