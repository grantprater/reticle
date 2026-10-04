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
            verdict = classify_killfeed_icon(crop, agents=["Breach"], gallery=synthetic_gallery)
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

        verdict = classify_killfeed_icon(crop, agents=["Breach"], gallery=gallery)
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
        self.assertEqual(name_icon(grid, aspect, mined)["reason"], "ambiguous")

    def test_mined_gallery_refuses_a_far_icon(self):
        """An icon no exemplar resembles gets no name from the mined gallery."""
        from reticle.adjudication.weapon import icon_grid, name_icon
        mined = self._mined([("Vandal", self._shape(70, 10))])
        block = np.zeros((34, 74, 3), dtype=np.uint8)
        block[8:26, 2:72] = 255                # same box, half its area unlike the gun
        grid, aspect = icon_grid(extract_icon_observation(block).white_mask)
        self.assertEqual(name_icon(grid, aspect, mined)["reason"], "new")

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

    def _rows(self, mined, frames):
        """Stored `killfeed_weapon` rows from (t_ms, slot, wx0, box_w, crop) tuples."""
        from reticle.killfeed import icon_grid, icon_white_mask
        rows = []
        for t, slot, wx0, box_w, crop in frames:
            grid, aspect = icon_grid(icon_white_mask(crop))
            rows.append({"kind": "weapon_icon_observation", "t_ms": t, "slot": slot,
                         "wx0": wx0, "wx1": wx0 + box_w, "aspect": aspect,
                         "grid": np.packbits(grid.astype(bool)).tobytes().hex()})
        return rows

    def test_entry_weapon_follows_its_own_entry_when_the_stack_rises(self):
        """Two entries share a divider column; when both rise a slot, each keeps its own icon."""
        from reticle.adjudication.weapon import entry_weapon
        spectre, vandal = self._shape(50, 5), self._shape(70, 30)
        mined = self._mined([("Spectre", spectre), ("Vandal", vandal)])
        frames = []
        for k, t in enumerate(range(0, 5000, 500)):
            up = 1 if k >= 5 else 0              # the whole stack rises at 2.5 s
            frames += [(t, 1 - up, 200, 54, spectre), (t, 2 - up, 200, 74, vandal)]
        rows = self._rows(mined, frames)
        upper = entry_weapon({"t_first": 0, "t_last": 4500, "slot": 1, "sig": 200}, rows, mined)
        lower = entry_weapon({"t_first": 0, "t_last": 4500, "slot": 2, "sig": 200}, rows, mined)
        self.assertEqual((upper["status"], upper["name"], upper["names"]),
                         ("resolved", "Spectre", {"Spectre": 10}))
        self.assertEqual((lower["status"], lower["name"], lower["names"]),
                         ("resolved", "Vandal", {"Vandal": 10}))

    def test_entry_weapon_refuses_one_frame(self):
        """A single named frame is not an answer."""
        from reticle.adjudication.weapon import entry_weapon
        vandal = self._shape(70, 30)
        mined = self._mined([("Vandal", vandal)])
        rows = self._rows(mined, [(0, 0, 200, 74, vandal)])
        ev = entry_weapon({"t_first": 0, "t_last": 500, "slot": 0, "sig": 200}, rows, mined)
        self.assertEqual((ev["status"], ev["reason"]), ("refused", "too_few_named"))

    def test_entry_weapon_refuses_an_unknown_icon_as_new(self):
        """Frames that score low against every allowed name refuse as new, not as too few."""
        from reticle.adjudication.weapon import entry_weapon
        mined = self._mined([("Vandal", self._shape(70, 10))])
        block = np.zeros((34, 74, 3), dtype=np.uint8)
        block[8:26, 2:72] = 255
        rows = self._rows(mined, [(t, 0, 200, 74, block) for t in (0, 500, 1000)])
        ev = entry_weapon({"t_first": 0, "t_last": 1000, "slot": 0, "sig": 200}, rows, mined)
        self.assertEqual((ev["status"], ev["reason"], ev["frame_reasons"]),
                         ("refused", "new", {"new": 3}))

    def test_entry_weapon_refuses_a_tied_icon_as_ambiguous(self):
        """Frames whose two best names lie within the margin refuse as ambiguous."""
        from reticle.adjudication.weapon import entry_weapon
        vandal = self._shape(70, 10)
        mined = self._mined([("Vandal", vandal), ("Phantom", self._shape(70, 10))])
        rows = self._rows(mined, [(t, 0, 200, 74, vandal) for t in (0, 500, 1000)])
        ev = entry_weapon({"t_first": 0, "t_last": 1000, "slot": 0, "sig": 200}, rows, mined)
        self.assertEqual((ev["status"], ev["reason"]), ("refused", "ambiguous"))

    def test_entry_weapon_ability_group_names_the_cause_not_a_weapon(self):
        """A group the player knew only as an ability gives the cause, with no name."""
        from reticle.adjudication.weapon import entry_weapon
        glyph = self._shape(40, 10)
        mined = self._mined([("Ability", glyph)])
        rows = self._rows(mined, [(t, 0, 200, 44, glyph) for t in (0, 500, 1000)])
        ev = entry_weapon({"t_first": 0, "t_last": 1000, "slot": 0, "sig": 200}, rows, mined)
        self.assertEqual((ev["status"], ev["category"], ev["name"]), ("resolved", "ability", None))

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


class CasterTests(unittest.TestCase):
    """An ability icon names its caster; the lineup bounds the icon's names."""

    def test_caster_claim_names_the_abilitys_agent(self):
        from reticle.adjudication.weapon import caster_claim
        c = caster_claim("death:s:1:0:killer", "Blade Storm")
        self.assertEqual((c["agent"], c["channel"]), ("Jett", "killfeed_weapon"))
        self.assertEqual(caster_claim("k", "Not Dead Yet")["agent"], "Clove")
        self.assertIsNone(caster_claim("k", "Vandal"))
        self.assertIsNone(caster_claim("k", "Environmental"))

    def test_lineup_drops_abilities_no_one_there_can_cast(self):
        from reticle.adjudication.weapon import restrict_gallery
        g = {"names": np.array(["Vandal", "Blade Storm", "Headhunter"]),
             "masks": np.zeros((3, 2, 2)), "aspects": np.ones(3)}
        kept, dropped = restrict_gallery(g, {"Chamber", "Sova"})
        self.assertEqual(list(kept["names"]), ["Vandal", "Headhunter"])
        self.assertEqual(dropped, ["Blade Storm"])
        self.assertEqual(len(kept["masks"]), 2)

    def test_an_ability_kill_names_its_killer_without_a_portrait(self):
        from reticle.adjudication.death import adjudicate_death
        v = adjudicate_death(death_id="d", t_ms=1.0, side="enemy", death_cause="ability",
                             weapon="Blade Storm")
        self.assertEqual(v.metadata["killer_identity"]["agent"], "Jett")
        clash = adjudicate_death(death_id="d", t_ms=1.0, side="enemy", death_cause="ability",
                                 weapon="Blade Storm",
                                 killfeed_claim={"channel": "killfeed_portrait", "killer": "Reyna"})
        self.assertEqual(clash.metadata["killer_identity"]["status"], "disagreement")


class RoleNarrowingTests(unittest.TestCase):
    """weapon-adjudication-0.7.0: the acting agent's kit, then the lineup, then
    the full gallery; what an answer rests on; the fixed audit."""

    @staticmethod
    def _grid(cols, rows=16):
        from reticle.killfeed import ICON_GRID
        g = np.zeros(ICON_GRID, dtype=np.uint8)
        g[:rows, :cols] = 1
        return g

    def _gallery(self):
        # Aftershock (Breach) an ability-shaped block; Vandal a long gun.
        return {"names": np.array(["Aftershock", "Vandal"]),
                "masks": np.array([self._grid(20), self._grid(60, 6)]),
                "aspects": np.array([1.0, 3.0])}

    @staticmethod
    def _obs(grid, aspect, times=(0, 500, 1000)):
        hexgrid = np.packbits(grid.astype(bool)).tobytes().hex()
        return [{"kind": "weapon_icon_observation", "t_ms": t, "slot": 0, "wx0": 200,
                 "wx1": 220, "aspect": aspect, "grid": hexgrid} for t in times]

    ENTRY = {"t_first": 0, "t_last": 1000, "slot": 0, "sig": 200}
    BREACH = {"agent": "Breach", "entity_id": "death:s:0:0:killer", "role": "killer",
              "channels": ["killfeed_name_cluster"]}

    def test_breach_kit_is_aftershock_with_no_question(self):
        """The derived kits list Breach's Aftershock alone and hold no question
        of Breach, so the faint icon names Aftershock with Breach acting."""
        from reticle.adjudication.weapon import KILLFEED_KITS, KILLFEED_OPEN, entry_weapon
        self.assertEqual(KILLFEED_KITS["Breach"], frozenset({"Aftershock"}))
        self.assertNotIn("Breach", KILLFEED_OPEN)
        ev = entry_weapon(self.ENTRY, self._obs(self._grid(12), 1.0), self._gallery(),
                          agents={"Breach", "Sova"}, actor=self.BREACH)
        self.assertEqual((ev["status"], ev["name"], ev["kit_floor_frames"]),
                         ("resolved", "Aftershock", 3))

    def test_an_open_question_keeps_the_full_floor(self):
        """An agent with an ability the rule cannot decide keeps NAME_MIN_IOU,
        even with its listed kit in the gallery."""
        from unittest import mock
        from reticle.adjudication import weapon
        with mock.patch.dict(weapon.KILLFEED_OPEN, {"Breach": frozenset({"Fault Line"})}):
            self.assertEqual(weapon.kit_names(self._gallery(), "Breach"), frozenset())
            ev = weapon.entry_weapon(self.ENTRY, self._obs(self._grid(12), 1.0), self._gallery(),
                                     agents={"Breach", "Sova"}, actor=self.BREACH)
        self.assertEqual((ev["status"], ev["reason"], ev["kit_floor_frames"]), ("refused", "new", 0))

    def test_a_listed_kit_the_gallery_lacks_does_not_lower_the_floor(self):
        """A listed kit lowers the floor only when the gallery holds all of it,
        and only for the listed names."""
        from unittest import mock
        from reticle.adjudication import weapon
        with mock.patch.dict(weapon.KILLFEED_KITS,
                             {"Breach": frozenset({"Aftershock", "Rolling Thunder"})}):
            self.assertEqual(weapon.kit_names(self._gallery(), "Breach"), frozenset())
        with mock.patch.dict(weapon.KILLFEED_KITS, {"Breach": frozenset({"Aftershock"})}):
            self.assertEqual(weapon.kit_names(self._gallery(), "Breach"), frozenset({"Aftershock"}))
        with mock.patch.dict(weapon.KILLFEED_KITS, {"Breach": frozenset({"Vandal"})}):
            self.assertEqual(weapon.kit_names(self._gallery(), "Breach"), frozenset())

    def test_the_kit_floor_follows_the_tiers_null_not_the_aspect(self):
        """weapon-adjudication-1.4.0: a wide kit ability with no close
        neighbour takes the lower floor; one a gun of its tier resembles
        (kit_null at or over NAME_KIT_MIN_IOU) keeps NAME_MIN_IOU."""
        from unittest import mock
        from reticle.adjudication import weapon
        wide = {"names": np.array(["Aftershock", "Vandal"]),
                "masks": np.array([self._grid(40), self._grid(60, 6)]),
                "aspects": np.array([1.8, 3.0])}
        with mock.patch.dict(weapon.KILLFEED_KITS, {"Breach": frozenset({"Aftershock"})}):
            self.assertLess(weapon.kit_null(wide, "Aftershock"), weapon.NAME_KIT_MIN_IOU)
            self.assertEqual(weapon.kit_names(wide, "Breach"), frozenset({"Aftershock"}))
            near = dict(wide, masks=np.array([self._grid(40), self._grid(44)]),
                        aspects=np.array([1.8, 1.85]))
            self.assertGreaterEqual(weapon.kit_null(near, "Aftershock"), weapon.NAME_KIT_MIN_IOU)
            self.assertEqual(weapon.kit_names(near, "Breach"), frozenset())

    def test_the_kit_floor_names_a_faint_ability_the_full_floor_refuses(self):
        """An icon at IoU 0.6 to Aftershock is new without context, Aftershock
        given Breach as the killer with Breach's kit listed whole, and that
        answer rests on the killer."""
        from unittest import mock
        from reticle.adjudication import weapon
        from reticle.adjudication.weapon import entry_weapon
        listed = mock.patch.dict(weapon.KILLFEED_KITS, {"Breach": frozenset({"Aftershock"})})
        listed.start()
        self.addCleanup(listed.stop)
        gal, rows = self._gallery(), self._obs(self._grid(12), 1.0)
        bare = entry_weapon(self.ENTRY, rows, gal)
        self.assertEqual((bare["status"], bare["reason"]), ("refused", "new"))
        kit = entry_weapon(self.ENTRY, rows, gal, agents={"Breach", "Sova"}, actor=self.BREACH,
                           frames=True)
        self.assertEqual((kit["status"], kit["name"]), ("resolved", "Aftershock"))
        self.assertEqual([r["context"] for r in kit["rests_on"]], ["actor"])
        self.assertEqual(kit["rests_on"][0]["entity_id"], self.BREACH["entity_id"])
        self.assertEqual(kit["kit_floor_frames"], 3)
        self.assertTrue(all(f["rests_on"] for f in kit["frames"]))

    def test_another_agents_kit_does_not_lower_the_floor(self):
        """With Sova acting, Aftershock takes the full floor and the faint icon stays new."""
        from reticle.adjudication.weapon import entry_weapon
        sova = dict(self.BREACH, agent="Sova")
        ev = entry_weapon(self.ENTRY, self._obs(self._grid(12), 1.0), self._gallery(),
                          agents={"Breach", "Sova"}, actor=sova)
        self.assertEqual((ev["status"], ev["reason"], ev["surprise"]), ("refused", "new", False))

    def test_a_clear_icon_rests_on_the_lineup_not_the_actor(self):
        """An icon every tier names the same way does not rest on the actor."""
        from reticle.adjudication.weapon import entry_weapon
        ev = entry_weapon(self.ENTRY, self._obs(self._grid(20), 1.0), self._gallery(),
                          agents={"Breach"}, actor=self.BREACH)
        self.assertEqual((ev["name"], [r["context"] for r in ev["rests_on"]], ev["kit_floor_frames"]),
                         ("Aftershock", ["lineup"], 0))

    def test_an_ability_outside_the_lineup_is_a_surprise(self):
        """An icon only the full gallery names resolves through the surprise path."""
        from reticle.adjudication.weapon import entry_weapon
        ev = entry_weapon(self.ENTRY, self._obs(self._grid(20), 1.0), self._gallery(),
                          agents={"Sova"})
        self.assertEqual((ev["status"], ev["name"], ev["surprise"], ev["rests_on"]),
                         ("resolved", "Aftershock", True, []))

    def test_a_kit_shaped_caster_claim_depends_on_the_actor(self):
        """The caster claim from an answer resting on the actor depends on its entity."""
        from reticle.adjudication.weapon import caster_claim
        on = [{"context": "actor", **self.BREACH}]
        claim = caster_claim("death:s:0:0:killer", "Aftershock", on)
        self.assertEqual((claim["agent"], claim["depends_on"]),
                         ("Breach", ["death:s:0:0:killer"]))
        free = caster_claim("death:s:0:0:killer", "Aftershock", [{"context": "lineup"}])
        self.assertFalse(free["depends_on"])

    def test_the_audit_is_a_fixed_hash_and_stored_apart(self):
        """One key in AUDIT_EVERY carries the full search's answer under `audit`."""
        from reticle.adjudication.weapon import AUDIT_EVERY, audit_entry, entry_weapon
        keys = [f"death:s:{t}:0" for t in range(0, 500000, 500)]
        picked = [k for k in keys if audit_entry(k)]
        self.assertEqual(picked, [k for k in keys if audit_entry(k)])
        self.assertLess(abs(len(picked) / len(keys) - 1 / AUDIT_EVERY), 0.03)
        self.assertFalse(audit_entry(None))
        ev = entry_weapon(self.ENTRY, self._obs(self._grid(20), 1.0), self._gallery(),
                          agents={"Breach"}, key=picked[0])
        self.assertEqual((ev["audit"]["name"], ev["audit"]["agrees"]), ("Aftershock", True))
        self.assertNotIn("audit", entry_weapon(self.ENTRY, self._obs(self._grid(20), 1.0),
                                               self._gallery(), key=next(
                                                   k for k in keys if not audit_entry(k))))


class KayoReviveIconTests(unittest.TestCase):
    """weapon-gallery-0.4.0 holds NULL/cmd from a KAY/O revive entry's weapon
    slot [domain:killfeed/kayo-downed-entry]: the icon marks a revive, names
    the revived KAY/O and makes no claim on the reviver."""

    def test_null_cmd_marks_a_revive_and_claims_no_caster(self):
        from reticle.adjudication.death import revive_entry
        from reticle.adjudication.weapon import MINED_NOT_GUN, caster_claim
        self.assertEqual(MINED_NOT_GUN["NULL/cmd"], "ability")
        self.assertTrue(revive_entry({"weapon_evidence": {"name": "NULL/cmd"}}))
        self.assertIsNone(caster_claim("death:s:0:1:killer", "NULL/cmd"))
        self.assertEqual(caster_claim("death:s:0:1:killer", "Aftershock")["agent"], "Breach")

    def test_a_one_colour_banner_needs_kayo_fielded_for_his_revive(self):
        from reticle.adjudication.death import revive_context
        down = {"t_ms": 1000.0, "side": "enemy", "entry_type": {"type": "kill"}}
        e = {"t_ms": 5000.0, "side": "enemy"}
        named = {1000.0: ("KAY_O", "death:s:1000:0")}
        self.assertIs(revive_context(e, [down], {"enemy": [{"agent": "KAY_O"}]},
                                     victims=named)["value"], True)
        # His down unnamed: the gate cannot check it and stays open.
        self.assertIsNone(revive_context(e, [down], {"enemy": [{"agent": "KAY_O"}]})["value"])
        self.assertIs(revive_context(e, [down], {"enemy": [{"agent": "Jett"}]},
                                     victims=named)["value"], False)


class NewIconAspectGateTests(unittest.TestCase):
    """`weapon_icons.new_icon_entries` keeps a named member out when its aspect
    lies beyond NAME_ASPECT_TOL of every aspect its name already has."""

    def test_the_gate(self):
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "prototypes"))
        from weapon_icons import aspect_fault
        ref = {"Vandal": [3.30, 3.62], "Warden": [3.86]}
        self.assertIsNone(aspect_fault("Vandal", 3.5, ref))
        self.assertEqual(aspect_fault("Vandal", 4.887, ref)["reason"], "aspect_beyond_name")
        self.assertIsNone(aspect_fault("Warden", 4.05, ref))
        self.assertIsNotNone(aspect_fault("Warden", 3.227, ref))
        self.assertIsNone(aspect_fault("NULL/cmd", 1.235, ref))   # no reference: ungated


class EntryTypeTests(unittest.TestCase):
    """adjudication.death owns the entry type and its acting role."""

    def test_entry_types_and_roles(self):
        from reticle.adjudication.death import ENTRY_ROLES, entry_type
        revive = {"weapon_evidence": {"name": "Resurrection"}}
        self.assertEqual(entry_type(revive), "revive")
        self.assertEqual(ENTRY_ROLES["revive"], ("reviver", "revived"))
        self.assertEqual(entry_type({"is_second_life": True}), "second_life_death")
        self.assertEqual(entry_type({}, is_second_life=False), "kill")

    def test_the_actor_is_named_without_the_icons_own_claim(self):
        """The weapon icon's caster claim never names the actor that narrows it."""
        from reticle.adjudication.death import entry_actor
        from reticle.adjudication.identity import identity_claim
        eid = "death:s:0:0:killer"
        icon = identity_claim(eid, "Breach", channel="killfeed_weapon")
        self.assertIsNone(entry_actor({}, {"claims": [icon]}))
        name = identity_claim(eid, "Breach", channel="killfeed_name_cluster")
        actor = entry_actor({}, {"claims": [icon, name]})
        self.assertEqual((actor["agent"], actor["role"], actor["channels"]),
                         ("Breach", "killer", ["killfeed_name_cluster"]))
        revive = {"weapon_evidence": {"name": "Resurrection"}}
        self.assertEqual(entry_actor(revive, {"claims": [name]})["role"], "reviver")

if __name__ == "__main__":
    unittest.main()

