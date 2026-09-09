import json
import tempfile
import unittest
from pathlib import Path

from reticle.ability_coverage import build_inventory, write_inventory


class AbilityCoverageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("reference", "manifests", "casts", "labels/ability",
                     "labels/ability_candidates", "series",
                     "reference/assets/ability_sfx", "reference/assets/voicelines"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        reference = {
            "harvested": "test",
            "agents": {"Sova": {"abilities": [
                {"name": "Owl Drone", "slot": "Ability2", "key": "C",
                 "description": "test", "table_kind": "Basic"},
                {"name": "Hunter's Fury", "slot": "Ultimate", "key": "X",
                 "description": "test", "table_kind": "Ultimate"},
            ]}},
        }
        (self.root / "reference/abilities.json").write_text(json.dumps(reference))
        manifest = {
            "session_id": "demo", "source_profile": "p",
            "source": {"path": str(self.root / "missing.mp4"),
                       "duration_ms": 10000, "content_key": "content"},
            "tags": ["ability-demo", "sova"],
        }
        (self.root / "manifests/demo.json").write_text(json.dumps(manifest))
        (self.root / "casts/demo.step0.5.hash.json").write_text(
            json.dumps([[5.0, "C", 1.0, 0.0, False]]))
        label = {"session_id": "demo", "t_ms": 6000, "x": 3, "y": 4,
                 "agent": "Sova", "ability": "Owl Drone",
                 "category_id": "sova:owl drone", "not_ability": False,
                 "uncertain": False}
        (self.root / "labels/ability/demo.jsonl").write_text(json.dumps(label) + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_inventory_links_casts_and_preserves_legacy_label_key(self):
        got = build_inventory(self.root)
        self.assertEqual(got["manifest"]["summary"]["definitions"], 2)
        self.assertEqual(got["manifest"]["summary"]["source_windows"], 2)
        cast, label = got["source_windows"]
        self.assertEqual(cast["ability_id"], "sova:owl drone")
        self.assertEqual(label["legacy_key"], ["demo", 6000, 3, 4])
        self.assertFalse(got["sessions"][0]["source_available"])
        source_paths = {r["path"] for r in got["manifest"]["source_files"]}
        self.assertIn("manifests/demo.json", source_paths)

    def test_evidence_support_is_property_specific(self):
        got = build_inventory(self.root)
        rows = {(r["ability_id"], r["property_group"]): r
                for r in got["coverage"]}
        self.assertEqual(rows[("sova:owl drone", "identity")]["status"], "supported")
        self.assertEqual(rows[("sova:owl drone", "time")]["status"], "weak")
        self.assertEqual(rows[("sova:owl drone", "geometry")]["status"], "not_exercised")
        self.assertEqual(rows[("sova:hunter's fury", "identity")]["status"],
                         "not_exercised")

    def test_write_is_deterministic_and_does_not_modify_sources(self):
        before = (self.root / "labels/ability/demo.jsonl").read_bytes()
        bundle = build_inventory(self.root)
        first = write_inventory(bundle, self.root / "out-a")
        second = write_inventory(bundle, self.root / "out-b")
        self.assertEqual((first / "coverage.jsonl").read_bytes(),
                         (second / "coverage.jsonl").read_bytes())
        self.assertEqual(before, (self.root / "labels/ability/demo.jsonl").read_bytes())


if __name__ == "__main__":
    unittest.main()
