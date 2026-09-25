import json
import tempfile
import unittest
from pathlib import Path

from reticle.adjudication.ability import (bearing_groups, build_entities,
                                          light_refusals, onset_groups,
                                          persistence_groups, predict_ability_births)
from reticle import lighting


class GroupingUnitTests(unittest.TestCase):
    def component(self, ident, t, x, y):
        return {"component_id": ident, "observed_t_ms": t, "x": x, "y": y}

    def test_onset_group_is_order_stable(self):
        rows = [self.component("a", 100, 0, 0), self.component("b", 200, 20, 0),
                self.component("c", 1000, 200, 0)]
        expected = [["a", "b"], ["c"]]
        for order in (rows, list(reversed(rows))):
            self.assertEqual([[r["component_id"] for r in g] for g in onset_groups(order)], expected)

    def test_bearing_group_handles_wrap_without_order_dependence(self):
        rows = [self.component("o", 0, 0, 0), self.component("a", 1, 10, 1),
                self.component("b", 2, 10, -1), self.component("c", 3, -10, 0)]
        got = bearing_groups(list(reversed(rows)))
        member_sets = {frozenset(r["component_id"] for r in group) for group in got}
        self.assertIn(frozenset(("o", "a", "b")), member_sets)


class PersistenceGroupTests(unittest.TestCase):
    """An ability transforms and stays itself, so grouping must offer that."""

    def component(self, ident, t, x, y):
        return {"component_id": ident, "observed_t_ms": t, "x": x, "y": y}

    def test_one_position_across_a_long_gap_is_one_entity(self):
        rows = [self.component("live", 1000, 40, 40),
                self.component("dim", 21000, 41, 40)]
        got = persistence_groups(rows)
        self.assertEqual(len(got), 1)
        self.assertEqual({r["component_id"] for r in got[0]}, {"live", "dim"})

    def test_onset_grouping_splits_exactly_that_case(self):
        """The disagreement is the point: onset needs a shared onset within
        300 ms, which a transformation twenty seconds later does not have."""
        rows = [self.component("live", 1000, 40, 40),
                self.component("dim", 21000, 41, 40)]
        self.assertEqual(len(onset_groups(rows)), 2)
        self.assertEqual(len(persistence_groups(rows)), 1)

    def test_a_device_placed_elsewhere_stays_a_separate_entity(self):
        rows = [self.component("a", 1000, 40, 40),
                self.component("b", 1200, 200, 200)]
        self.assertEqual(len(persistence_groups(rows)), 2)

    def test_grouping_is_order_stable(self):
        rows = [self.component("a", 1000, 40, 40),
                self.component("b", 9000, 44, 41),
                self.component("c", 5000, 300, 40)]
        for order in (rows, list(reversed(rows))):
            got = [sorted(r["component_id"] for r in g)
                   for g in persistence_groups(order)]
            self.assertEqual(sorted(got), [["a", "b"], ["c"]])


class EntityBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("reference/assets/ability_sfx", "reference/assets/voicelines",
                     "manifests", "casts", "labels/ability",
                     "labels/ability_candidates", "series"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        ref = {"harvested": "test", "agents": {"Viper": {"abilities": [
            {"name": "Toxic Screen", "slot": "Ability2", "key": "E"}]}}}
        (self.root / "reference/abilities.json").write_text(json.dumps(ref))
        man = {"session_id": "demo", "source_profile": "p",
               "source": {"path": "missing", "duration_ms": 10000, "content_key": "k"},
               "tags": ["ability-demo", "viper"]}
        (self.root / "manifests/demo.json").write_text(json.dumps(man))
        (self.root / "casts/demo.step0.5.reader.json").write_text(
            json.dumps([[5.0, "E", 1.0, 0.0, False]]))
        candidates = [
            {"session_id": "demo", "t_ms": 5000, "x": 10, "y": 10,
             "duration_ms": 100, "n_observations": 2},
            {"session_id": "demo", "t_ms": 5500, "x": 20, "y": 10,
             "duration_ms": 100, "n_observations": 2},
            {"session_id": "demo", "t_ms": 6000, "x": 30, "y": 10,
             "duration_ms": 100, "n_observations": 2},
        ]
        (self.root / "labels/ability_candidates/demo.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in candidates))
        label = dict(candidates[0], agent="Viper", ability="Toxic Screen",
                     category_id="viper:toxic screen", not_ability=False, uncertain=False)
        (self.root / "labels/ability/demo.jsonl").write_text(json.dumps(label) + "\n")

    def tearDown(self):
        self.temp.cleanup()

    def test_named_component_supports_parent_but_group_stays_unresolved(self):
        got = build_entities(self.root)
        self.assertEqual(got["manifest"]["summary"]["supported_parent_edges"], 1)
        multi = [h for h in got["entity_hypotheses"] if len(h["component_ids"]) > 1]
        self.assertTrue(multi)
        self.assertTrue(all(not h["grouping_resolved"] for h in multi))
        null = next(h for h in got["entity_hypotheses"]
                    if h["grouping_method"] == "no_observed_spatial_child")
        self.assertEqual(null["status"], "contradicted")

    def test_property_values_keep_pixel_units_and_rule_status(self):
        got = build_entities(self.root)
        bearings = [p for p in got["properties"] if p["property"] == "bearing"
                    and p["value"] is not None]
        self.assertTrue(bearings)
        self.assertEqual(bearings[0]["units"], "degrees_image_xy")
        rules = [p for p in got["properties"] if p["property"] == "extent"]
        self.assertTrue(rules)
        self.assertEqual(rules[0]["status"], "domain_hypothesis_needs_patch_validation")

    def test_reach_gating_prunes_distant_candidate(self):
        import numpy as np
        t_arr = np.array([5000.0])
        sx = np.array([[100.0]])
        sy = np.array([[100.0]])
        np.savez(self.root / "series" / "demo.npz", t_ms=t_arr, self_x=sx, self_y=sy)

        ref = {"harvested": "test", "agents": {"Killjoy": {"abilities": [
            {"name": "Alarmbot", "slot": "Ability1", "key": "Q"}]}}}
        (self.root / "reference/abilities.json").write_text(json.dumps(ref))
        man = {"session_id": "demo", "source_profile": "p",
               "source": {"path": "missing", "duration_ms": 10000, "content_key": "k"},
               "tags": ["ability-demo", "killjoy"]}
        (self.root / "manifests/demo.json").write_text(json.dumps(man))
        (self.root / "casts/demo.step0.5.reader.json").write_text(
            json.dumps([[5.0, "Q", 1.0, 0.0, False]]))
        candidates = [
            {"session_id": "demo", "t_ms": 5200, "x": 110, "y": 100,
             "duration_ms": 100, "n_observations": 2},
            {"session_id": "demo", "t_ms": 5200, "x": 250, "y": 100,
             "duration_ms": 100, "n_observations": 2},
        ]
        (self.root / "labels/ability_candidates/demo.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in candidates))
        (self.root / "labels/ability/demo.jsonl").write_text("")

        got = build_entities(self.root)
        c_near = next(c for c in got["component_claims"] if c["origin"] == "detector_candidate" and "250" not in c["component_id"])
        c_far = next(c for c in got["component_claims"] if c["origin"] == "detector_candidate" and "250" in c["component_id"])
        self.assertTrue(any(p["status"] == "candidate" for p in c_near["possible_parents"]))
        self.assertFalse(any(p["status"] == "candidate" for p in c_far["possible_parents"]))
        self.assertTrue(any(p["reason"] == "outside_placement_reach" for p in c_far["contradicted_parents"]))

    def test_domain_non_minimap_ability_confirms_absent_null(self):
        ref = {"harvested": "test", "agents": {"Jett": {"abilities": [
            {"name": "Tailwind", "slot": "Ability2", "key": "E"}]}}}
        (self.root / "reference/abilities.json").write_text(json.dumps(ref))
        man = {"session_id": "demo", "source_profile": "p",
               "source": {"path": "missing", "duration_ms": 10000, "content_key": "k"},
               "tags": ["ability-demo", "jett"]}
        (self.root / "manifests/demo.json").write_text(json.dumps(man))
        (self.root / "casts/demo.step0.5.reader.json").write_text(
            json.dumps([[5.0, "E", 1.0, 0.0, False]]))
        candidates = [
            {"session_id": "demo", "t_ms": 5200, "x": 100, "y": 100,
             "duration_ms": 100, "n_observations": 2},
        ]
        (self.root / "labels/ability_candidates/demo.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in candidates))
        (self.root / "labels/ability/demo.jsonl").write_text("")

        got = build_entities(self.root)
        null_h = next(h for h in got["entity_hypotheses"] if h["grouping_method"] == "no_observed_spatial_child")
        self.assertEqual(null_h["status"], "confirmed_absent")
        self.assertEqual(null_h["status_reason"], "domain_invar_no_minimap_entity")


class OrphanEvidenceTests(unittest.TestCase):
    """A human label the detector never reproduced is still an observation."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("reference/assets/ability_sfx", "reference/assets/voicelines",
                     "manifests", "casts", "labels/ability",
                     "labels/ability_candidates", "series"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.root / "reference/abilities.json").write_text(json.dumps(
            {"harvested": "test", "agents": {"Cypher": {"abilities": [
                {"name": "Trapwire", "slot": "Ability1", "key": "C"}]}}}))
        (self.root / "manifests/quiet.json").write_text(json.dumps(
            {"session_id": "quiet", "source_profile": "p", "tags": ["map:ascent"],
             "source": {"path": "missing", "duration_ms": 30000, "content_key": "k"}}))
        (self.root / "labels/ability_candidates/quiet.jsonl").write_text(json.dumps(
            {"session_id": "quiet", "t_ms": 1000, "x": 5, "y": 5,
             "duration_ms": 100, "n_observations": 2}) + "\n")
        rows = [
            {"session_id": "quiet", "t_ms": 9000, "x": 300, "y": 300,
             "agent": "Cypher", "ability": "Trapwire", "category_id": "cypher:trapwire",
             "not_ability": False, "uncertain": False},
            {"session_id": "quiet", "t_ms": 12000, "x": 400, "y": 400,
             "agent": None, "ability": None, "category_id": None,
             "not_ability": True, "uncertain": False},
        ]
        (self.root / "labels/ability/quiet.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))

    def tearDown(self):
        self.temp.cleanup()

    def test_label_with_no_candidate_row_still_becomes_a_component(self):
        got = build_entities(self.root)
        origins = got["manifest"]["summary"]["components_by_origin"]
        self.assertEqual(origins["human_label"], 2)
        self.assertEqual(origins["detector_candidate"], 1)
        named = [c for c in got["component_claims"]
                 if c["origin"] == "human_label" and c["label_state"] == "named"]
        self.assertEqual(len(named), 1)
        self.assertEqual(named[0]["source_evidence"][0]["path"],
                         "labels/ability/quiet.jsonl")

    def test_a_silent_use_channel_is_named_rather_than_left_blank(self):
        got = build_entities(self.root)
        reasons = got["manifest"]["summary"]["orphan_reasons"]
        self.assertEqual(reasons, {"no_use_claims_in_session": 2})
        orphan_reviews = [r for r in got["review"]
                          if r["review_id"].startswith("ability-orphan")]
        self.assertTrue(orphan_reviews)
        self.assertEqual(orphan_reviews[0]["orphan_reasons"],
                         ["no_use_claims_in_session"])

    def test_human_clutter_is_answered_not_orphaned(self):
        got = build_entities(self.root)
        clutter = next(c for c in got["component_claims"] if c["label_state"] == "clutter")
        self.assertIsNone(clutter["orphan_reason"])
        reviewed = {cid for r in got["review"] for cid in r["component_ids"]}
        self.assertNotIn(clutter["component_id"], reviewed)


class LightRefusalTests(unittest.TestCase):
    def setUp(self):
        import numpy as np
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "manifests").mkdir(parents=True, exist_ok=True)
        (self.root / "geometry").mkdir(parents=True, exist_ok=True)
        (self.root / "events/ability_light").mkdir(parents=True, exist_ok=True)
        (self.root / "series").mkdir(parents=True, exist_ok=True)

        # Build mock geometry
        h, w = 50, 50
        lo_gray = np.full((h, w), 100, dtype=np.uint8)
        hi_gray = np.full((h, w), 160, dtype=np.uint8)
        sd_lo = np.full((h, w), 2.0, dtype=np.float32)
        sd_hi = np.full((h, w), 2.0, dtype=np.float32)
        labels = np.ones((h, w), dtype=np.int32)
        geo_path = self.root / "geometry/testmap__testprof.npz"
        np.savez_compressed(geo_path, lo_gray=lo_gray, hi_gray=hi_gray,
                            sd_lo=sd_lo, sd_hi=sd_hi, labels=labels)

        man = {"session_id": "s1", "source_profile": "testprof",
               "tags": ["map:testmap"],
               "source": {"path": "missing", "width": 1920, "height": 1080}}
        (self.root / "manifests/s1.json").write_text(json.dumps(man))

    def tearDown(self):
        self.temp.cleanup()

    def test_dark_object_is_not_refused_despite_light_or_facing(self):
        import numpy as np
        h, w = 50, 50
        raw_lit = np.zeros((h, w), dtype=bool)
        raw_lit[20:30, 20:30] = True
        raw_dark = np.zeros((h, w), dtype=bool)
        raw_dark[22:25, 22:25] = True  # Opaque object present

        row = {
            "session_id": "s1", "kind": "frame", "t_ms": 1000.0,
            "raw_lit": lighting.pack_mask(raw_lit),
            "raw_dark": lighting.pack_mask(raw_dark),
            "reason": None,
        }
        (self.root / "events/ability_light/s1.jsonl").write_text(json.dumps(row) + "\n")

        comp = [{"component_id": "c1", "session_id": "s1", "observed_t_ms": 1000.0,
                 "x": 25, "y": 25, "box": [20, 20, 10, 10]}]
        res = light_refusals(self.root, comp)
        self.assertEqual(res["c1"]["status"], "passed")

    def test_pure_light_viewcone_is_refused(self):
        import numpy as np
        h, w = 50, 50
        raw_lit = np.zeros((h, w), dtype=bool)
        raw_lit[20:30, 20:30] = True
        raw_dark = np.zeros((h, w), dtype=bool)

        row = {
            "session_id": "s1", "kind": "frame", "t_ms": 1000.0,
            "raw_lit": lighting.pack_mask(raw_lit),
            "raw_dark": lighting.pack_mask(raw_dark),
            "reason": None,
        }
        (self.root / "events/ability_light/s1.jsonl").write_text(json.dumps(row) + "\n")

        comp = [{"component_id": "c1", "session_id": "s1", "observed_t_ms": 1000.0,
                 "x": 25, "y": 25, "box": [20, 20, 10, 10]}]
        res = light_refusals(self.root, comp)
        self.assertEqual(res["c1"]["status"], "refused")
        self.assertEqual(res["c1"]["reason"], "drawn_light")

    def test_trajectory_ability_emits_parametric_beam_schema(self):
        from reticle.adjudication.ability import _properties
        use = {"use_claim_id": "u1", "ability_id": "sova:hunter's fury", "session_id": "s1"}
        group = [{"component_id": "c1", "observed_t_ms": 1000.0, "observed_end_ms": 1500.0,
                  "x": 20, "y": 20, "label_state": "named"},
                 {"component_id": "c2", "observed_t_ms": 1100.0, "observed_end_ms": 1600.0,
                  "x": 40, "y": 20, "label_state": "named"}]
        rule = {"origin_driver": "fixed", "bearing_driver": "fixed", "extent": "trajectory"}
        props = _properties(use, group, "entity:e1", "bearing", rule)
        schema_prop = next((p for p in props if p["property"] == "trajectory_schema"), None)
        self.assertIsNotNone(schema_prop)
        self.assertEqual(schema_prop["value"], "beam(x0, y0, theta, L, w)")


class PredictAbilityBirthsTests(unittest.TestCase):
    """Test cross-channel predict-update hypotheses and candidate gating."""

    def test_batch_desaturation_refused_as_artefact(self):
        casts = [
            {"t_s": 17.0, "slot": "C", "suspect": True},
            {"t_s": 17.0, "slot": "Q", "suspect": True},
            {"t_s": 17.0, "slot": "E", "suspect": True},
            {"t_s": 17.0, "slot": "X", "suspect": True},
        ]
        kit = {"C": "Trapwire", "Q": "Cyber Cage", "E": "Spycam", "X": "Neural Theft"}
        res = predict_ability_births(casts, lambda t: (100.0, 100.0), [], "Cypher", kit)
        self.assertEqual(len(res), 4)
        for r in res:
            self.assertEqual(r["status"], "fail:batch_desat_wipe")
            self.assertEqual(r["reason"], "simultaneous_multi_slot_desaturation_artefact")
            self.assertEqual(r["gated_candidates"], [])

    def test_domain_non_entity_predicts_empty_candidate_set(self):
        casts = [{"t_s": 16.5, "slot": "E", "suspect": False}]
        kit = {"E": "Tailwind"}
        # Clutter candidate should be ignored
        cands = [
            {"t_ms": 16500.0, "x": 105.0, "y": 105.0, "label_state": "clutter"},
            {"t_ms": 16600.0, "x": 102.0, "y": 102.0, "not_ability": True},
        ]
        res = predict_ability_births(casts, lambda t: (100.0, 100.0), cands, "Jett", kit)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "pass:confirmed_absent")
        self.assertEqual(res[0]["reason"], "domain_invar_no_minimap_entity")

        # Non-clutter candidate is unexpected
        cands_unexpected = [{"t_ms": 16500.0, "x": 105.0, "y": 105.0, "label_state": "named"}]
        res_fail = predict_ability_births(casts, lambda t: (100.0, 100.0), cands_unexpected, "Jett", kit)
        self.assertEqual(res_fail[0]["status"], "fail:unexpected_candidate")

    def test_local_placement_reach_gating(self):
        casts = [{"t_s": 27.0, "slot": "Q", "suspect": False}]
        kit = {"Q": "Alarmbot"}
        cands = [
            {"t_ms": 28000.0, "x": 265.0, "y": 95.0, "component_id": "c_near"},
            {"t_ms": 28000.0, "x": 100.0, "y": 300.0, "component_id": "c_far"},
            {"t_ms": 40000.0, "x": 265.0, "y": 95.0, "component_id": "c_late"},
        ]
        res = predict_ability_births(casts, lambda t: (262.0, 93.0), cands, "Killjoy", kit)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "pass:corroborated_birth")
        self.assertEqual([c["component_id"] for c in res[0]["gated_candidates"]], ["c_near"])

    def test_caster_unobserved_marked_honestly(self):
        casts = [{"t_s": 33.5, "slot": "E", "suspect": False}]
        kit = {"E": "Turret"}
        for pos in ((None, None), (float("nan"), float("nan"))):
            res = predict_ability_births(casts, lambda t: pos, [], "Killjoy", kit)
            self.assertEqual(len(res), 1)
            self.assertEqual(res[0]["status"], "fail:caster_unobserved")
            self.assertEqual(res[0]["reason"], "caster_position_missing_or_nan")

    def test_remote_flight_projectile(self):
        casts = [{"t_s": 14.5, "slot": "E", "suspect": False}]
        kit = {"E": "Recon Bolt"}
        res = predict_ability_births(casts, lambda t: (200.0, 200.0), [], "Sova", kit)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]["status"], "pass:remote_flight")
        self.assertEqual(res[0]["reason"], "projectile_lands_remote")


if __name__ == "__main__":
    unittest.main()

