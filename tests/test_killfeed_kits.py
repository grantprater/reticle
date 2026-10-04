"""Tests for the killfeed kits derived from the reference's ability descriptions."""
from __future__ import annotations

import json
import unittest

from reticle.adjudication import killfeed_kits as kk


def _ref(*abilities):
    return {"harvested": "2026-09-04", "source": {},
            "agents": {"Test": {"abilities": [
                {"name": n, "key": "Q", "description": d, "functions": f} for n, d, f in abilities]}}}


class DamageRuleTests(unittest.TestCase):
    def status(self, description, functions=None, name="X"):
        return kk.damage_decision(name, description, functions)["status"]

    def test_a_damage_clause_is_damaging(self):
        self.assertEqual(self.status("The burst does heavy damage to anyone caught in its area."), "damaging")
        self.assertEqual(self.status("a fire zone that damages players within the zone."), "damaging")
        self.assertEqual(self.status("The cocooned enemy will die unless they are freed."), "damaging")
        self.assertEqual(self.status("a zone that damages and applies Vulnerable."), "damaging")

    def test_a_heal_or_a_condition_leaves_it_undecided(self):
        self.assertEqual(self.status("a zone that damages enemies. The zone heals you instead of dealing damage."),
                         "undecided")
        self.assertEqual(self.status("detonate, dealing damage if fully armed."), "undecided")

    def test_a_harm_word_outside_a_clause_is_undecided(self):
        self.assertEqual(self.status("Held enemies are Deafened, and Decayed."), "undecided")
        self.assertEqual(self.status("absorb an enemy that you damaged or killed."), "undecided")

    def test_kill_resets_and_after_death_are_not_harm(self):
        self.assertEqual(self.status("Dash forward. Charge resets every two kills."), "not_damaging")
        self.assertEqual(self.status("Launch smokes. You can use this ability after death."), "not_damaging")

    def test_a_weapon_or_an_attack_with_no_effect_is_undecided(self):
        self.assertEqual(self.status("ACTIVATE to equip a heavy pistol.", "Weapon Equip"), "undecided")
        self.assertEqual(self.status("deploy a turret that fires at enemies."), "undecided")
        self.assertEqual(self.status("The charge detonates to Blind all players looking at it."), "not_damaging")

    def test_a_fact_icon_decides_before_the_rule(self):
        d = kk.damage_decision("Headhunter", "ACTIVATE to equip a heavy pistol.", "Weapon Equip")
        self.assertEqual((d["status"], d["by"]), ("kit_icon", "fact:killfeed/chamber-gun-shaped-abilities"))


class AssistRuleTests(unittest.TestCase):
    def test_status_terms(self):
        self.assertEqual(kk.assist_decision("forcing any characters caught within to crouch and move slowly.")["status"],
                         "disabling")
        self.assertEqual(kk.assist_decision("set a slow-acting burst through the wall.")["status"], "not_disabling")
        self.assertEqual(kk.assist_decision("Revealing the location of nearby enemies.")["status"], "undecided")


class DerivationTests(unittest.TestCase):
    def test_derive_keeps_excerpts_kits_and_questions(self):
        out = kk.derive(_ref(("A", "The burst does heavy damage to anyone.", None),
                             ("B", "Held enemies are Deafened, and Decayed.", None),
                             ("C", "INSTANTLY propel high into the air.", None)))
        self.assertEqual(out["kits"], {"Test": ["A"]})
        self.assertEqual(out["open"], {"Test": ["B"]})
        self.assertEqual(out["assist_icons"], {"Test": ["B"]})
        a = out["abilities"][0]["damage"]
        self.assertEqual((a["by"], a["excerpt"]), ("rule:does-damage", "The burst does heavy damage to anyone."))

    def test_a_passive_draws_no_icon_and_answers_decide(self):
        """A slot-Passive ability is in no list; the player's answer decides an
        ability the rule left open, keeping the rule's decision beside it."""
        ref = _ref(("Hot Hands", "a zone that damages enemies. The zone heals you instead of dealing damage.", None),
                   ("Kill Contract", "duel to the death.", None))
        ref["agents"]["Phoenix"] = ref["agents"].pop("Test")
        ref["agents"]["Phoenix"]["abilities"].append(
            {"name": "Heating Up", "key": None, "slot": "Passive", "functions": None,
             "description": "PASSIVELY Heal Phoenix instead of taking damage"})
        out = kk.derive(ref)
        self.assertEqual(out["kits"]["Phoenix"], ["Hot Hands"])
        self.assertEqual(out["open"], {"Phoenix": ["Kill Contract"]})
        hot, _, heat = out["abilities"]
        self.assertEqual((hot["damage"]["status"], hot["damage"]["rule"]["status"]), ("damaging", "undecided"))
        self.assertEqual((heat["damage"]["status"], heat["assist"]["status"]), ("passive", "passive"))

    def test_iso_kill_contract_is_possible_and_unconfirmed(self):
        self.assertIn("Kill Contract", kk.kill_kits()["Iso"])
        self.assertEqual(kk.load()["unconfirmed"], {"Iso": ["Kill Contract"]})
        self.assertEqual(kk.open_questions(), {})

    def test_kits_spell_agents_as_ability_agent_does(self):
        """Every kit name's caster, as `weapon.ability_agent` spells it (the
        lineup's KAY_O), is the agent the kit is keyed by."""
        from reticle.adjudication.weapon import ability_agent
        kits = kk.kill_kits()
        self.assertIn("KAY_O", kits)
        self.assertNotIn("KAY/O", kits)
        for agent, names in kits.items():
            for n in names:
                if ability_agent(n) is not None:
                    self.assertEqual(ability_agent(n), agent, n)

    def test_kit_names_are_spelled_as_the_gallery_spells_them(self):
        """killfeed-kits-0.4.0: a capitalised reference word is capitalised
        ("TURRET"); the game's own mixed casing stays; every kit name is a
        weapon gallery name."""
        self.assertEqual(kk.kit_name("TURRET"), "Turret")
        for n in ("FRAG/ment", "NULL/cmd", "Hunter's Fury", "Tour De Force", "ZERO/point"):
            self.assertEqual(kk.kit_name(n), n)
        self.assertIn("Turret", kk.kill_kits()["Killjoy"])
        from reticle.adjudication.weapon import GAME_KILL_ICONS, MINED_ONLY_NAMES
        gallery = set(GAME_KILL_ICONS) | set(MINED_ONLY_NAMES)
        for agent, names in kk.kill_kits().items():
            self.assertEqual(set(names) - gallery, set(), agent)

    def test_stored_derivation_matches_the_reference(self):
        from reticle.store import DEFAULT_STORE
        ref = DEFAULT_STORE / kk.REFERENCE
        if not ref.exists():
            self.skipTest("no reference in the store")
        stored = json.loads(kk.DATA.read_text(encoding="utf-8"))
        self.assertEqual(stored, json.loads(json.dumps(kk.derive_from_store(DEFAULT_STORE))))


if __name__ == "__main__":
    unittest.main()
