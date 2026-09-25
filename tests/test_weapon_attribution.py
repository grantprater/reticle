"""Tests for killfeed weapon and ability icon extraction and classification."""
from __future__ import annotations

import unittest
from pathlib import Path

import numpy as np

from reticle.adjudication.weapon import (
    ABILITY_CANONICAL_NAMES,
    WEAPON_ADJUDICATION_VERSION,
    WEAPON_TAXONOMY,
    IconObservation,
    WeaponVerdict,
    classify_killfeed_icon,
    estimate_weapon_class,
    extract_icon_observation,
    load_ability_gallery,
    load_weapon_gallery,
)


class WeaponAttributionTests(unittest.TestCase):
    def test_extract_icon_observation_geometry(self):
        """extract_icon_observation calculates aspect ratio, fill ratio, and candidate flags."""
        # 1. Ability-sized crop (width 20, height 24, aspect 0.83)
        ability_crop = np.zeros((24, 20, 3), dtype=np.uint8)
        ability_crop[4:20, 4:16] = 255  # white content
        obs_ability = extract_icon_observation(ability_crop)

        self.assertEqual(obs_ability.width, 20)
        self.assertEqual(obs_ability.height, 24)
        self.assertAlmostEqual(obs_ability.aspect_ratio, 0.83, delta=0.05)
        self.assertTrue(obs_ability.is_ability_candidate)
        self.assertFalse(obs_ability.is_weapon_candidate)

        # 2. Rifle-sized crop (width 75, height 24, aspect 3.12)
        rifle_crop = np.zeros((24, 75, 3), dtype=np.uint8)
        rifle_crop[4:20, 5:70] = 255
        obs_rifle = extract_icon_observation(rifle_crop)

        self.assertEqual(obs_rifle.width, 75)
        self.assertEqual(obs_rifle.height, 24)
        self.assertGreater(obs_rifle.aspect_ratio, 2.5)
        self.assertFalse(obs_rifle.is_ability_candidate)
        self.assertTrue(obs_rifle.is_weapon_candidate)

    def test_estimate_weapon_class_categories(self):
        """estimate_weapon_class bins dimensions into ability, sidearm, smg, rifle, sniper."""
        self.assertEqual(estimate_weapon_class(width=20, aspect_ratio=0.8), "ability")
        self.assertEqual(estimate_weapon_class(width=36, aspect_ratio=1.5), "sidearm")
        self.assertEqual(estimate_weapon_class(width=52, aspect_ratio=1.9), "smg")
        self.assertEqual(estimate_weapon_class(width=72, aspect_ratio=2.4), "rifle")
        self.assertEqual(estimate_weapon_class(width=105, aspect_ratio=3.2), "sniper")

    def test_classify_killfeed_icon_breach_aftershock(self):
        """classify_killfeed_icon resolves Breach Aftershock when matching reference ability."""
        # Synthetic / mock gallery test or store gallery if available
        gallery = load_ability_gallery()
        if not gallery or "Breach_Grenade" not in gallery:
            # Synthetic template test
            synthetic_gallery = {
                "Breach_Grenade": np.full((128, 128, 4), 255, dtype=np.uint8),
                "Raze_Ultimate": np.zeros((128, 128, 4), dtype=np.uint8),
            }
            crop = np.full((24, 24, 3), 255, dtype=np.uint8)
            verdict = classify_killfeed_icon(crop, active_agent="Breach", gallery=synthetic_gallery)
            self.assertEqual(verdict.status, "resolved")
            self.assertEqual(verdict.name, "Aftershock")
            self.assertEqual(verdict.category, "ability")
            return

        # Real template test from reference store:
        # Create a test crop resized from Breach_Grenade
        ref_raw = gallery["Breach_Grenade"]
        import cv2
        resized = cv2.resize(ref_raw, (20, 24))
        crop = np.zeros((24, 20, 3), dtype=np.uint8)
        mask = resized[:, :, 3] > 128
        crop[mask] = 255

        verdict = classify_killfeed_icon(crop, active_agent="Breach", gallery=gallery)
        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.name, "Aftershock")
        self.assertEqual(verdict.category, "ability")
        self.assertGreaterEqual(verdict.confidence, 0.65)

    def test_classify_killfeed_icon_gun_geometry_fallback(self):
        """Guns without template match abstain specific name but resolve category and class."""
        rifle_crop = np.zeros((24, 70, 3), dtype=np.uint8)
        rifle_crop[6:18, 5:65] = 255
        verdict = classify_killfeed_icon(rifle_crop)

        self.assertEqual(verdict.status, "abstained")
        self.assertIsNone(verdict.name)
        self.assertEqual(verdict.category, "gun")
        self.assertEqual(verdict.weapon_class, "rifle")

    def test_load_weapon_gallery(self):
        """load_weapon_gallery loads canonical reference weapon templates from reticle-store."""
        gallery = load_weapon_gallery()
        if gallery:
            self.assertIn("Vandal", gallery)
            self.assertIn("Spectre", gallery)
            self.assertEqual(gallery["Vandal"].shape[2], 4)  # RGBA

    def test_classify_killfeed_icon_gun_template_match(self):
        """classify_killfeed_icon resolves specific weapon name when matching weapon gallery."""
        # Create a synthetic Spectre template with stepped silhouette
        mock_spectre = np.zeros((20, 60, 4), dtype=np.uint8)
        mock_spectre[6:14, 5:40] = (255, 255, 255, 255)
        mock_spectre[10:18, 20:30] = (255, 255, 255, 255)
        mock_spectre[4:8, 40:55] = (255, 255, 255, 255)
        weapon_gallery = {"Spectre": mock_spectre}

        crop = np.zeros((34, 62, 3), dtype=np.uint8)
        crop[7:27, 1:61][mock_spectre[:, :, 3] > 0] = 255
        verdict = classify_killfeed_icon(crop, weapon_gallery=weapon_gallery)

        self.assertEqual(verdict.status, "resolved")
        self.assertEqual(verdict.name, "Spectre")
        self.assertEqual(verdict.category, "gun")
        self.assertEqual(verdict.weapon_class, "smg")
        self.assertGreaterEqual(verdict.confidence, 0.70)

    @staticmethod
    def _mined(entries):
        """A mined gallery from (name, crop) pairs, normalised the owner's way."""
        from reticle.adjudication.weapon import icon_grid
        names, masks, aspects = [], [], []
        for name, crop in entries:
            grid, aspect = icon_grid(extract_icon_observation(crop).white_mask)
            names.append(name)
            masks.append(grid)
            aspects.append(aspect)
        return {"names": np.array(names), "masks": np.array(masks), "aspects": np.array(aspects)}

    @staticmethod
    def _shape(w, notch):
        crop = np.zeros((34, w + 4, 3), dtype=np.uint8)
        crop[8:16, 2:2 + w] = 255              # barrel
        crop[16:26, 2 + notch:10 + notch] = 255  # grip, placed by `notch`
        return crop

    def test_mined_gallery_names_a_gun(self):
        """The nearest player-named exemplar names the icon when it clears the rest."""
        mined = self._mined([("Vandal", self._shape(70, 10)), ("Phantom", self._shape(70, 50))])
        v = classify_killfeed_icon(self._shape(70, 10), mined_gallery=mined)
        self.assertEqual((v.status, v.name, v.category, v.weapon_class),
                         ("resolved", "Vandal", "gun", "rifle"))

    def test_mined_gallery_refuses_a_tie(self):
        """Two names with equally close exemplars are a refusal, not a pick."""
        from reticle.adjudication.weapon import icon_grid, name_icon
        mined = self._mined([("Vandal", self._shape(70, 10)), ("Phantom", self._shape(70, 10))])
        grid, aspect = icon_grid(extract_icon_observation(self._shape(70, 10)).white_mask)
        self.assertEqual(name_icon(grid, aspect, mined)["reason"], "tie")

    def test_mined_gallery_refuses_a_far_icon(self):
        """An icon no exemplar resembles gets no name from the mined gallery."""
        from reticle.adjudication.weapon import icon_grid, name_icon
        mined = self._mined([("Vandal", self._shape(70, 10))])
        block = np.zeros((34, 74, 3), dtype=np.uint8)
        block[8:26, 2:72] = 255                # same box, half its area unlike the gun
        grid, aspect = icon_grid(extract_icon_observation(block).white_mask)
        self.assertEqual(name_icon(grid, aspect, mined)["reason"], "no_close_exemplar")

    def test_mined_gallery_chamber_ability_is_not_a_gun(self):
        """Headhunter draws a revolver but is an ability, not a sidearm."""
        mined = self._mined([("Headhunter", self._shape(40, 4)), ("Sheriff", self._shape(40, 25))])
        v = classify_killfeed_icon(self._shape(40, 4), mined_gallery=mined)
        self.assertEqual((v.name, v.category, v.weapon_class),
                         ("Headhunter", "ability", "ability"))

    def test_mined_gallery_unnamed_ability_stays_an_ability(self):
        """A group the player knew only as an ability never falls back to a gun class."""
        mined = self._mined([("Ability", self._shape(70, 10))])
        v = classify_killfeed_icon(self._shape(70, 10), mined_gallery=mined,
                                   weapon_gallery={}, gallery={})
        self.assertEqual((v.status, v.category, v.name), ("abstained", "ability", None))

    def test_weapon_verdict_serialization(self):
        """WeaponVerdict serializes cleanly with adjudication version."""
        verdict = WeaponVerdict(
            name="Vandal",
            category="gun",
            weapon_class="rifle",
            confidence=0.92,
            margin=0.25,
            status="resolved",
            scores={"Vandal": 0.92, "Phantom": 0.67},
        )
        d = verdict.to_dict()
        self.assertEqual(d["name"], "Vandal")
        self.assertEqual(d["category"], "gun")
        self.assertEqual(d["weapon_class"], "rifle")
        self.assertEqual(d["adjudication_version"], WEAPON_ADJUDICATION_VERSION)


if __name__ == "__main__":
    unittest.main()

