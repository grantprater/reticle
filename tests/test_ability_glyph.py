"""Unit tests for deterministic glyph classification and crop gallery."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from reticle.adjudication.gallery import (
    HARVEST_KNOWN_MAP,
    classify_ability_glyph,
    extract_glyph_features,
    integrate_crop_gallery,
    load_harvested_gallery,
)
from reticle.store import DEFAULT_STORE


class GlyphFeatureExtractionTests(unittest.TestCase):
    """Test deterministic feature extraction across mock patches."""

    def test_empty_patch_returns_empty_dict(self):
        self.assertEqual(extract_glyph_features(np.array([])), {})
        self.assertEqual(extract_glyph_features(None), {})

    def test_feature_keys_and_values(self):
        # Create synthetic 32x32 BGR patch
        patch = np.zeros((32, 32, 3), dtype=np.uint8)
        # Add white circle in center
        patch[12:20, 12:20] = [255, 255, 255]
        feats = extract_glyph_features(patch, archetype="deployable", r_self=8.0)

        required_keys = [
            "width", "height", "aspect_ratio", "radius_est", "radius_ratio",
            "r_all", "g_all", "b_all", "r_core", "g_core", "b_core",
            "h_all", "s_all", "v_all", "h_core", "s_core", "v_core",
            "h_ring", "s_ring", "v_ring", "red_prom", "blue_prom", "green_prom",
            "sat_frac", "sat_h_mean", "sat_s_mean", "glyph_core", "glyph_ring",
            "center_v", "radial_contrast"
        ]
        for k in required_keys:
            self.assertIn(k, feats)
            self.assertIsInstance(feats[k], (int, float))

        self.assertEqual(feats["width"], 32.0)
        self.assertEqual(feats["height"], 32.0)
        self.assertEqual(feats["radius_est"], 16.0)
        self.assertAlmostEqual(feats["radius_ratio"], 2.0, places=2)


class GlyphClassificationTests(unittest.TestCase):
    """Test deterministic classification across archetype classes."""

    def test_wall_contrast(self):
        # 1. Phoenix fire wall: red dominant
        phoenix_patch = np.full((48, 48, 3), [100, 130, 180], dtype=np.uint8)
        res_p = classify_ability_glyph(phoenix_patch, archetype="wall")
        self.assertEqual(res_p["ability_id"], "phoenix:blaze")
        self.assertGreater(res_p["confidence"], 0.90)

        # 2. Neon electric blue wall: high saturation, blue dominant
        neon_patch = np.full((48, 48, 3), [190, 130, 80], dtype=np.uint8)
        res_n = classify_ability_glyph(neon_patch, archetype="wall")
        self.assertEqual(res_n["ability_id"], "neon:fast lane")
        self.assertGreater(res_n["confidence"], 0.90)

        # 3. Viper toxic screen: toxic teal/green
        viper_patch = np.full((48, 48, 3), [150, 155, 140], dtype=np.uint8)
        res_v = classify_ability_glyph(viper_patch, archetype="wall")
        self.assertEqual(res_v["ability_id"], "viper:toxic screen")
        self.assertGreater(res_v["confidence"], 0.90)

    def test_deployable_contrast(self):
        # 1. Cypher Spycam: high saturation cyan core
        spycam_patch = np.zeros((32, 32, 3), dtype=np.uint8)
        # Fill core (radius <= 6.4 px from center 16,16) with bright cyan
        spycam_patch[9:23, 9:23] = [220, 200, 40]
        res_s = classify_ability_glyph(spycam_patch, archetype="deployable")
        self.assertEqual(res_s["ability_id"], "cypher:spycam")

        # 2. Killjoy Alarmbot: high glyph variance core
        alarm_patch = np.full((32, 32, 3), 140, dtype=np.uint8)
        # Create checkerboard in core to induce high laplacian variance
        alarm_patch[12:20:2, 12:20:2] = 250
        alarm_patch[13:20:2, 13:20:2] = 40
        res_a = classify_ability_glyph(alarm_patch, archetype="deployable")
        self.assertEqual(res_a["ability_id"], "killjoy:alarmbot")

    def test_smoke_contrast(self):
        # 1. Jett Cloudburst: pale desaturated white cloud
        jett_patch = np.full((32, 32, 3), 115, dtype=np.uint8)
        res_j = classify_ability_glyph(jett_patch, archetype="smoke")
        self.assertEqual(res_j["ability_id"], "jett:cloudburst")

        # 2. Omen Dark Cover: dark purple tint
        omen_patch = np.full((32, 32, 3), [110, 115, 125], dtype=np.uint8)
        omen_patch[12:20, 12:20] = [95, 90, 105]
        res_o = classify_ability_glyph(omen_patch, archetype="smoke")
        self.assertEqual(res_o["ability_id"], "omen:dark cover")


class GalleryIntegrationTests(unittest.TestCase):
    """Test loading and integration of harvested crop gallery."""

    def test_harvest_map_completeness(self):
        self.assertIn("omen_E", HARVEST_KNOWN_MAP)
        self.assertIn("clove_E", HARVEST_KNOWN_MAP)
        self.assertIn("jett_C", HARVEST_KNOWN_MAP)
        self.assertIn("viper_Q_smoke", HARVEST_KNOWN_MAP)
        self.assertIn("killjoy_Q", HARVEST_KNOWN_MAP)
        self.assertIn("killjoy_C", HARVEST_KNOWN_MAP)
        self.assertIn("cypher_E", HARVEST_KNOWN_MAP)
        self.assertIn("phoenix_C_wall", HARVEST_KNOWN_MAP)
        self.assertIn("viper_E_wall", HARVEST_KNOWN_MAP)
        self.assertIn("neon_C_wall", HARVEST_KNOWN_MAP)

    def test_load_harvested_gallery_runs(self):
        crops = load_harvested_gallery(DEFAULT_STORE)
        self.assertGreaterEqual(len(crops), 14)
        for c in crops:
            self.assertIn("filename", c)
            self.assertIn("archetype", c)
            self.assertIn("ability_id", c)
            self.assertIn("features", c)
            self.assertIn(c["archetype"], {"smoke", "deployable", "wall"})

    def test_integrate_crop_gallery_manifest(self):
        manifest = integrate_crop_gallery(DEFAULT_STORE)
        self.assertIn("producer_version", manifest)
        self.assertIn("archetypes", manifest)
        self.assertIn("centroids", manifest)
        self.assertIn("crops", manifest)
        self.assertGreaterEqual(manifest["total_crops"], 14)


if __name__ == "__main__":
    unittest.main()
