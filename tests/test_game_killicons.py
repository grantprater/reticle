"""Tests for the game kill icons in the weapon gallery (weapon-gallery-0.8.0)."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from reticle.adjudication.weapon import (
    ABILITY_CANONICAL_NAMES,
    EXTRA_ABILITY_AGENTS,
    GAME_ICON_BUILD,
    GAME_KILL_ICON_SOURCES,
    GAME_KILL_ICONS,
    MINED_ONLY_NAMES,
    WEAPON_TAXONOMY,
    ability_agent,
    classify_killfeed_icon,
    drawn_icon_alpha,
    entry_weapon,
    game_icon_exemplar,
    game_build_dir,
    icon_grid,
    load_game_icons,
    load_gallery,
    name_category,
    name_icon,
)


def _left_heavy(h=48, w=96):
    """An RGBA texture whose ink fills its left third only."""
    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[:, : w // 3, :] = 255
    return rgba


class MirrorTests(unittest.TestCase):
    def test_the_drawn_alpha_is_mirrored(self):
        """Ink on the texture's left draws on the right, as the killfeed does."""
        a = drawn_icon_alpha(_left_heavy(), height=24.0)
        self.assertEqual(a.shape, (24, 48))
        self.assertGreater(a[:, 32:].mean(), 0.9)
        self.assertLess(a[:, :24].mean(), 0.05)

    def test_the_drawn_alpha_shrinks_softly(self):
        """INTER_AREA leaves a fractional edge where the ink ends mid-pixel."""
        rgba = np.zeros((48, 100, 4), np.uint8)
        rgba[:, 99 - 50:, 3] = 255                 # 51 columns: 25.5 drawn px
        a = drawn_icon_alpha(rgba, height=24.0)
        vals = np.unique(np.round(a[0], 3))
        self.assertTrue(any(0.0 < v < 1.0 for v in vals))

    def test_a_phase_moves_the_icon_by_a_fraction(self):
        """A sub-pixel phase shifts the ink's centroid by that fraction."""
        rgba = np.zeros((48, 48, 4), np.uint8)
        rgba[12:36, 12:36, 3] = 255
        a0 = drawn_icon_alpha(rgba, 24.0, (0.0, 0.0))
        a1 = drawn_icon_alpha(rgba, 24.0, (1 / 3, 0.0))
        cx = lambda a: (a.sum(0) * np.arange(a.shape[1])).sum() / a.sum()
        self.assertAlmostEqual(cx(a1) - (cx(a0) + 1), 1 / 3, delta=0.02)   # +1: margin

    def test_the_exemplar_is_the_readers_grid(self):
        """The exemplar is the drawn alpha through the reader's own cut and grid."""
        from reticle.killfeed import PLATE_WHITE_CUT
        rgba = _left_heavy()
        grid, aspect = game_icon_exemplar(rgba, 24.0)
        want = icon_grid(drawn_icon_alpha(rgba, 24.0) >= PLATE_WHITE_CUT)
        np.testing.assert_array_equal(grid, want[0])
        self.assertAlmostEqual(aspect, want[1])


class MappingTests(unittest.TestCase):
    def test_every_game_name_has_a_category(self):
        """Each game icon is a gun, melee, environmental death, ability or
        other (a base class or game-mode icon with no caster), the death
        causes `DeathVerdict` declares."""
        for name, (rel, category) in GAME_KILL_ICONS.items():
            self.assertIn(category, {"gun", "melee", "environmental", "ability", "other"}, name)
            self.assertEqual(name_category(name), category, name)
            self.assertTrue(rel.endswith(".png"), name)

    def test_every_game_gun_is_a_taxonomy_gun(self):
        """A game gun carries the gallery's own gun name."""
        guns = {n for n, (_, c) in GAME_KILL_ICONS.items() if c == "gun"}
        known = {n for names in WEAPON_TAXONOMY.values() for n in names}
        self.assertEqual(len(guns), 20)
        self.assertEqual(guns - known, set())

    def test_every_game_ability_names_its_agent(self):
        """An ability's name is canonical, so its caster resolves."""
        canonical = set(ABILITY_CANONICAL_NAMES.values()) | set(EXTRA_ABILITY_AGENTS)
        for name, (_, category) in GAME_KILL_ICONS.items():
            if category != "ability":
                continue
            self.assertIn(name, canonical, name)
            self.assertIsNotNone(ability_agent(name), name)

    def test_every_icon_names_its_damage_types(self):
        """Each texture names the DamageTypes that draw it, and only those."""
        self.assertEqual(set(GAME_KILL_ICON_SOURCES), set(GAME_KILL_ICONS))
        self.assertTrue(all(GAME_KILL_ICON_SOURCES.values()))

    def test_mined_only_names_have_no_game_icon(self):
        """A mined-only name is one no DamageType draws."""
        self.assertEqual(MINED_ONLY_NAMES & set(GAME_KILL_ICONS), set())

    def test_no_base_class_or_placeholder_icon_is_a_candidate(self):
        """weapon-gallery-0.9.0: the icons of base classes no kill deals and
        the placeholder stay out of the gallery, kept as provenance."""
        from reticle.adjudication.weapon import GAME_KILL_ICONS_EXCLUDED
        self.assertEqual(set(GAME_KILL_ICONS_EXCLUDED),
                         {"Explosion", "Pistol", "Phoenix fire", "Internal"})
        self.assertEqual(set(GAME_KILL_ICONS_EXCLUDED) & set(GAME_KILL_ICONS), set())
        self.assertTrue(all(v["why"] and v["damage_types"]
                            for v in GAME_KILL_ICONS_EXCLUDED.values()))

    def test_game_mode_icons_are_candidates_only_on_the_surprise_path(self):
        """A game-mode icon, and Grenade bounce (weapon-adjudication-1.5.0),
        leave the kit and lineup tiers and stay in full."""
        from reticle.adjudication.weapon import (GAME_MODE_ICONS, SURPRISE_ONLY_ICONS,
                                                 candidate_tiers)
        names = ["Vandal", "Golden Gun", "Snowball", "Plague orb", "Grenade bounce", "Aftershock"]
        g = {"names": np.array(names), "masks": np.zeros((6, 16, 64)), "aspects": np.ones(6)}
        self.assertEqual(set(SURPRISE_ONLY_ICONS) - set(GAME_KILL_ICONS), set())
        self.assertEqual(set(SURPRISE_ONLY_ICONS), set(GAME_MODE_ICONS) | {"Grenade bounce"})
        self.assertEqual(GAME_MODE_ICONS["Plague orb"], "Spike Rush")
        tiers = {t["tier"]: t for t in candidate_tiers(
            g, agents={"Breach"}, actor={"agent": "Breach", "entity_id": "e"})}
        for tier in ("kit", "lineup"):
            self.assertEqual(tiers[tier]["index"]["names"], ["Vandal", "Aftershock"], tier)
            self.assertEqual(set(tiers[tier]["dropped"]), set(SURPRISE_ONLY_ICONS), tier)
        self.assertEqual(tiers["full"]["index"]["names"], names)

    def test_stinger_reads_its_damage_types_texture(self):
        """Stinger's KillIcon TX_Hud_Vector is exported as a dedup of the
        KillStreamIcon file; the provenance names the DamageType's texture."""
        from reticle.adjudication.weapon import GAME_KILL_ICON_TEXTURES
        self.assertTrue(GAME_KILL_ICONS["Stinger"][0].endswith("TX_Hud_SMG_KrissVector_S.png"))
        self.assertTrue(GAME_KILL_ICON_TEXTURES["Stinger"].endswith("TX_Hud_Vector"))

    def test_blade_storm_draws_its_damage_types_single_dagger(self):
        """Blade Storm's kill icon is its DamageType's dagger, not the tray's
        three knives."""
        rel = GAME_KILL_ICONS["Blade Storm"][0]
        self.assertTrue(rel.startswith("damage-type-icons/"))
        self.assertTrue(rel.endswith("TX_Hud_Wushu_X_Dagger.png"))


class RefusalTests(unittest.TestCase):
    def test_a_store_without_the_export_refuses(self):
        """No exported icons is a named refusal, not an empty gallery."""
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(load_game_icons(Path(d)), (None, "no_game_icons"))
            self.assertEqual(load_gallery(Path(d))[1], "no_gallery")

    def test_a_texture_that_differs_from_the_manifest_refuses(self):
        """A texture whose sha256 differs from the manifest's is refused by name."""
        name, (rel, _) = next(iter(GAME_KILL_ICONS.items()))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            build = game_build_dir(root)
            (build / rel).parent.mkdir(parents=True)
            ok, png = cv2.imencode(".png", _left_heavy())
            (build / rel).write_bytes(png.tobytes())
            (build / "killfeed-icons" / "manifest.jsonl").write_text(json.dumps(
                {"output": rel, "sha256": "0" * 64}) + "\n")
            self.assertEqual(load_game_icons(root), (None, f"game_icon_sha256:{name}"))
            (build / "killfeed-icons" / "manifest.jsonl").write_text(json.dumps(
                {"output": rel,
                 "sha256": hashlib.sha256(png.tobytes()).hexdigest()}) + "\n")
            second = list(GAME_KILL_ICONS)[1]
            self.assertEqual(load_game_icons(root), (None, f"game_icon_missing:{second}"))

    def test_an_entry_without_a_gallery_carries_the_refusal(self):
        """`entry_weapon` refuses with the gallery's reason, never a guess."""
        with tempfile.TemporaryDirectory() as d:
            v = entry_weapon({"key": "e"}, [], store_root=Path(d))
        self.assertIsNone(v.get("name"))
        self.assertEqual(v.get("reason"), "no_gallery")


_BUILD = game_build_dir()


@unittest.skipUnless((_BUILD / "killfeed-icons" / "manifest.jsonl").is_file(),
                     "game kill icons not exported")
class StoreTests(unittest.TestCase):
    def test_the_gallery_keeps_build_and_sha256(self):
        """Each game exemplar names its build, and each texture its sha256."""
        g, why = load_game_icons()
        self.assertIsNone(why)
        self.assertEqual(g["provenance"]["build"], GAME_ICON_BUILD)
        self.assertEqual(set(g["provenance"]["icons"]), set(GAME_KILL_ICONS))
        self.assertTrue(all(len(v["sha256"]) == 64 for v in g["provenance"]["icons"].values()))
        self.assertTrue(all(str(k).startswith(f"game:{GAME_ICON_BUILD}:") for k in g["keys"]))

    def test_the_gallery_keeps_mined_exemplars_only_where_no_game_icon_exists(self):
        """0.8.0 serves the game set and the mined-only names, nothing mined else."""
        g, why = load_gallery()
        self.assertIsNone(why)
        names = {str(n) for n in g["names"]}
        self.assertEqual(names - set(GAME_KILL_ICONS), set(g["provenance"]["mined_only"]))
        self.assertLessEqual(set(g["provenance"]["mined_only"]), MINED_ONLY_NAMES)

    def test_a_clean_paint_shells_descriptor_is_named_paint_shells(self):
        """Raze's Paint Shells drawn whole at a placement no exemplar was drawn
        at, and cut as the reader cuts a descriptor, names Paint Shells. The
        capture's thin ring breaks under the cut (4f207c0c4e39 1759-1766 s
        through one-colour-band-20261003's reader: best Paint Shells, IoU
        0.44-0.49), so a real one still refuses as `new`."""
        from reticle.killfeed import PLATE_WHITE_CUT
        g, why = load_gallery()
        self.assertIsNone(why)
        rgba = cv2.imread(str(_BUILD / GAME_KILL_ICONS["Paint Shells"][0]), cv2.IMREAD_UNCHANGED)
        drawn = drawn_icon_alpha(rgba, 24.0, (0.5, 0.5))
        grid, aspect = icon_grid(drawn >= PLATE_WHITE_CUT)
        self.assertEqual(name_icon(grid, aspect, g)["name"], "Paint Shells")

    def test_another_agents_ability_art_is_no_candidate(self):
        """The ability art scores only the match's agents' abilities."""
        art = {"Breach_Grenade": np.full((128, 128, 4), 255, np.uint8)}
        crop = np.full((24, 24, 3), 255, np.uint8)
        hit = classify_killfeed_icon(crop, agents=["Breach"], gallery=art, use_mined=False)
        miss = classify_killfeed_icon(crop, agents=["Jett", "Sage"], gallery=art,
                                      use_mined=False)
        self.assertEqual(hit.name, "Aftershock")
        self.assertNotEqual(miss.name, "Aftershock")


if __name__ == "__main__":
    unittest.main()
