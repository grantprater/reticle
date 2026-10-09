"""The mechanics sheet: game-file pre-fill, the player's walk, and the import."""
import io
import json
import tempfile
import unittest
from pathlib import Path

from reticle import domain
from reticle import mechanics_sheet as ms

GD = """
[ability-rules-are-unique]
claim = "Each ability's mechanics are its own."
kind = "rule"
known = "player"
since = "2026-09-26"
"""

GAME_DATA = """
[zed-trap-game-data]
claim = "The game files give Zed's Trap (slot C) these values."
kind = "measurement"
known = "measured"
since = "2026-10-04"
subject = "zed:trap"
source = "test"
values = { life = { initial_life_span_s = 8.0 } }

[zed-dash-game-data]
claim = "The game files give Zed's Dash (slot Q) these values."
kind = "measurement"
known = "measured"
since = "2026-10-04"
subject = "zed:dash"
source = "test"
values = { life = { a_s = 1.0, b_s = 2.0 }, move = { duration_s = 0.5 } }
"""

STATES = {"agents": {"Zed": {"abilities": {
    "C": {"ability": "Trap", "equippable": "/Game/Characters/Zed/Ability_C",
          "entities": [{"entity": "/Game/Characters/Zed/GameObject_Zed_Trap", "how": "spawns",
                        "named_by": "/Game/Characters/Zed/Ability_C"},
                       {"entity": "/Game/Characters/Zed/Debuff_Zed_Slow", "how": "names"}],
          "states": [{"owner": "/Game/Characters/Zed/Ability_C", "owner_kind": "equippable",
                      "state": "EquipState", "phase": "equip", "icons": []},
                     {"owner": "/Game/Characters/Zed/GameObject_Zed_Trap", "owner_kind": "entity",
                      "state": "ArmState", "phase": "activate",
                      "icons": [{"texture": "TX_Zed_Minimap", "role": "minimap_IconBrush",
                                 "views": {"self": True, "teammate": True, "enemy": None}}]}]},
    "Q": {"ability": "Dash", "equippable": "/Game/Characters/Zed/Ability_Q",
          "entities": [{"entity": "/Game/Characters/Zed/GameObject_Zed_Anchor", "how": "spawns"}],
          "states": []},
}}}}

TRAP_EXPORT = [{"Type": "ChildDamageSectionComponent", "Name": "HealthDamageSection",
                "Properties": {"bCanBeDestroyed": True, "Life": 20.0}}]


class Sheet:
    """A throwaway domain directory and store holding one fake agent."""

    def __init__(self, stack):
        self.root = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        self.dom = self.root / "domain"
        self.dom.mkdir()
        (self.dom / "abilities.toml").write_text(GD, encoding="utf-8")
        (self.dom / "game_data.toml").write_text(GAME_DATA, encoding="utf-8")
        self.store = self.root / "store"
        trap = self.store / ms.GAME_EXPORTS / "Characters/Zed/GameObject_Zed_Trap.json"
        trap.parent.mkdir(parents=True)
        trap.write_text(json.dumps(TRAP_EXPORT), encoding="utf-8")
        self.facts = domain.load(self.dom)
        self.rows = ms.build_rows(STATES, self.facts, ms.GameExports(self.store), {})

    def row(self, slot):
        return next(r for r in self.rows if r["slot"] == slot)

    def walk(self, lines, **kw):
        it = iter(lines)
        out = io.StringIO()
        ms.walk(self.store, self.rows, read=lambda _p: next(it, "q"), out=out, **kw)
        return out.getvalue()


class PrefillTest(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.s = Sheet(self.stack)

    def tearDown(self):
        self.stack.close()

    def test_one_row_per_slot_ability(self):
        self.assertEqual([(r["agent"], r["slot"]) for r in self.s.rows], [("Zed", "C"), ("Zed", "Q")])

    def test_cells_carry_their_game_file_sources(self):
        c = self.s.row("C")["cells"]
        self.assertEqual(c["lifecycle_class"]["value"], "deployed")
        self.assertEqual(c["lifetime_s"]["value"]["s"], 8.0)
        self.assertIn("[domain:" + "game_data/zed-trap-game-data]", c["lifetime_s"]["sources"])
        self.assertEqual(c["destructible"]["value"], "yes")
        self.assertIn("GameObject_Zed_Trap.json#HealthDamageSection", c["destructible"]["sources"][0])
        self.assertEqual(c["ends_on"]["value"], ["lifetime", "destroyed", "round_end"])
        self.assertEqual([d["effect"] for d in c["effects"]["value"]], ["slow"])
        self.assertEqual(c["minimap_drawing"]["value"], "icon")
        self.assertIn("TX_Zed_Minimap", c["minimap_drawing"]["evidence"]["textures"])
        self.assertEqual(c["engine_states"]["status"], "hidden")

    def test_no_source_means_ask_and_empty(self):
        c = self.s.row("C")["cells"]["owner_death"]
        self.assertEqual((c["status"], c["value"]), ("ask", None))

    def test_two_classes_are_a_conflict(self):
        c = self.s.row("Q")["cells"]["lifecycle_class"]
        self.assertEqual(c["status"], "conflict")
        self.assertEqual(c["candidates"], ["deployed", "movement"])

    def test_several_life_values_need_a_pick(self):
        c = self.s.row("Q")["cells"]["lifetime_s"]
        self.assertIsNone(c["value"])
        self.assertEqual(len(c["candidates"]), 2)


CAM = "/Game/Characters/Gumshoe/S0/Ability_E/"
SPYCAM = {"agents": {"Cypher": {"codename": "Gumshoe", "abilities": {"E": {
    "ability": "Spycam", "equippable": CAM + "Ability_Gumshoe_E_Camera",
    "entities": [
        {"entity": CAM + "Pawn_Gumshoe_E_PossessableCamera", "named_by": CAM + "Ability_Gumshoe_E_Camera", "how": "spawns"},
        {"entity": CAM + "Ability_Gumshoe_E_Camera_Dart", "named_by": CAM + "Pawn_Gumshoe_E_PossessableCamera", "how": "names"},
        {"entity": CAM + "Projectile_Gumshoe_E_CameraTrackingDart", "named_by": CAM + "Ability_Gumshoe_E_Camera_Dart", "how": "spawns"},
        {"entity": CAM + "GameObject_RemovableObject_GumshoeTrackingDart",
         "named_by": CAM + "Projectile_Gumshoe_E_CameraTrackingDart", "how": "spawns"},
        {"entity": CAM + "Buff_Gumshoe_RecentlyRevealed",
         "named_by": CAM + "GameObject_RemovableObject_GumshoeTrackingDart", "how": "names"}],
    "states": []}}}}}
DRONE = "/Game/Characters/Hunter/S0/Ability_E/Drone/"
OWL = {"agents": {"Sova": {"codename": "Hunter", "abilities": {"C": {
    "ability": "Owl Drone", "equippable": DRONE + "Ability_Hunter_E_DeployDrone",
    "entities": [
        {"entity": DRONE + "Pawn_Hunter_E_Drone", "named_by": DRONE + "Ability_Hunter_E_DeployDrone", "how": "spawns"},
        {"entity": DRONE + "Ability_Hunter_E_Drone_Abilities", "named_by": DRONE + "Pawn_Hunter_E_Drone", "how": "names"},
        {"entity": DRONE + "GameObject_Hunter_E_Drone_RevealDart",
         "named_by": DRONE + "Ability_Hunter_E_Drone_Abilities", "how": "names"}],
    "states": []}}}}}


class SpawnTreeTest(unittest.TestCase):
    """An ability spawning two objects yields two rows, each with its parent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name)
        dart = self.store / ms.GAME_EXPORTS / "Characters/Gumshoe/S0/Ability_E/GameObject_RemovableObject_GumshoeTrackingDart.json"
        dart.parent.mkdir(parents=True)
        dart.write_text(json.dumps([{"Type": "GameObject", "Name": "Default__Dart_C",
                                     "Properties": {"DestroyOnOwnerDeath": True}}]), encoding="utf-8")
        abilities = self.store / ms.GAME_EXPORTS / "Characters/Hunter/S0/Ability_E/Drone/Ability_Hunter_E_Drone_Abilities.json"
        abilities.parent.mkdir(parents=True)
        abilities.write_text(json.dumps([{"Name": "CallFunc_FinishSpawningActor_ReturnValue",
                                          "PropertyClass": {"ObjectName":
                                          "BlueprintGeneratedClass'GameObject_Hunter_E_Drone_RevealDart_C'"}}],
                                        indent=1), encoding="utf-8")
        self.exports = ms.GameExports(self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_spycam_yields_a_camera_row_and_a_dart_row_under_it(self):
        rows = ms.build_rows(SPYCAM, {}, self.exports, {})
        self.assertEqual([r["object"] for r in rows],
                         ["Pawn_Gumshoe_E_PossessableCamera", "GameObject_RemovableObject_GumshoeTrackingDart"])
        cam, dart = rows
        self.assertEqual(cam["cells"]["parent"]["value"], "ability")
        self.assertEqual(dart["cells"]["parent"]["value"], "Pawn_Gumshoe_E_PossessableCamera")
        self.assertEqual(dart["cells"]["parent"]["status"], "confirm")
        self.assertEqual(dart["cells"]["owner_death"]["value"], "destroyed")
        self.assertEqual(cam["cells"]["owner_death"]["status"], "ask")
        self.assertEqual([d["effect"] for d in dart["cells"]["effects"]["value"]], ["reveal"])
        self.assertEqual(cam["cells"]["effects"]["status"], "ask")
        self.assertNotEqual(ms.cell_key(cam, "parent"), ms.cell_key(dart, "parent"))

    def test_prompts_use_plain_words_never_class_names(self):
        _cam, dart = ms.build_rows(SPYCAM, {}, self.exports, {})
        text, _ = ms.render(dart, "owner_death", ms.cell_key(dart, "owner_death"), {})
        self.assertIn("When Cypher dies, Spycam's tracking dart:", text)
        self.assertIn("2 disappears", text)
        self.assertNotIn("GameObject", text)
        self.assertNotIn("Gumshoe", text)
        for column in ms.COLUMNS:
            if dart["cells"][column]["status"] not in ms.NOT_ASKED:
                text, _ = ms.render(dart, column, ms.cell_key(dart, column), {})
                self.assertNotRegex(text, r"GameObject|Pawn_|_C'|\.json")

    def test_a_bytecode_spawn_call_sets_the_parent(self):
        drone, dart = ms.build_rows(OWL, {}, self.exports, {})
        self.assertEqual(dart["cells"]["parent"]["value"], "Pawn_Hunter_E_Drone")
        self.assertIn("FinishSpawningActor", dart["cells"]["parent"]["sources"][0])

    def test_a_reference_without_a_spawn_is_asked(self):
        (self.store / ms.GAME_EXPORTS / "Characters/Hunter/S0/Ability_E/Drone/Ability_Hunter_E_Drone_Abilities.json").unlink()
        _drone, dart = ms.build_rows(OWL, {}, ms.GameExports(self.store), {})
        self.assertEqual((dart["cells"]["parent"]["status"], dart["cells"]["parent"]["value"]), ("ask", None))


class WalkAndImportTest(unittest.TestCase):
    def setUp(self):
        from contextlib import ExitStack
        self.stack = ExitStack()
        self.s = Sheet(self.stack)
        self.target = self.s.dom / "abilities.toml"

    def tearDown(self):
        self.stack.close()

    def answers(self):
        return ms.load_sheet_answers(self.s.store)

    def test_answers_are_stored_apart_and_last_row_wins(self):
        self.s.walk(["y", "a", "3", "q"], columns=("lifecycle_class",), agent="Zed")
        p = self.s.store / ms.ANSWERS
        self.assertEqual(len(p.read_text(encoding="utf-8").splitlines()), 2)
        self.assertEqual(self.answers()["Zed:C:lifecycle_class"]["answer"], "self_buff")
        self.assertFalse((self.s.store / ms.PREFILL_DIR).exists())

    def test_game_file_lifetime_refuses_a_typed_number(self):
        out = self.s.walk(["7 5.0", "u", "q"], columns=("lifetime_s",))
        self.assertIn("not understood", out)
        self.assertTrue(self.answers()["Zed:C:lifetime_s"]["unsure"])

    def test_import_skips_unconfirmed_rows(self):
        self.s.walk(["y", "y", "u", "q"])
        before = self.target.read_text(encoding="utf-8")
        texts, skipped = ms.import_rows(self.s.store, self.s.rows, write=True,
                                        target=self.target, out=io.StringIO())
        self.assertEqual(texts, [])
        self.assertTrue(any("open" in s for s in skipped))
        self.assertEqual(self.target.read_text(encoding="utf-8"), before)

    def test_import_writes_a_valid_lifecycle_fact(self):
        # Zed's modes 0 (none); C: parent y, class y, placement 2 (within
        # reach), visible phases typed, lifetime y, destructible y, owner
        # death d (default), ends_on y, effects y, slow targets 3 (enemies),
        # minimap y. Engine states are never asked.
        self.s.rows += ms.build_agent_rows(STATES, self.s.facts)
        out = self.s.walk(["0", "y", "y", "2", "thrown -> placed -> armed -> gone", "y", "y",
                           "d", "y", "y", "3", "y", "q"], agent="Zed")
        self.assertEqual(self.answers()["Zed:modes"]["answer"], [])
        self.assertEqual(self.answers()["Zed:C:placement"]["answer"], "body_relative")
        self.assertNotIn("engine_states", out)
        self.assertEqual(self.answers()["Zed:C:owner_death"]["how"], "default")
        self.assertEqual(self.answers()["Zed:C:visible_phases"]["answer"],
                         ["thrown", "placed", "armed", "gone"])
        texts, _ = ms.import_rows(self.s.store, self.s.rows, write=True,
                                  target=self.target, out=io.StringIO())
        self.assertEqual(len(texts), 1)
        facts = domain.load(self.s.dom)
        f = facts["abilities/zed-trap-lifecycle"]
        self.assertEqual((f.kind, f.known, f.subject), ("lifecycle", "player", "zed:trap"))
        self.assertEqual(f.lifecycle_class, "deployed")
        self.assertIn("Placement: body-relative.", " ".join(f.claim.split()))
        self.assertEqual(f.ends_on, ("lifetime", "destroyed", "round_end"))
        self.assertEqual((f.destructible, f.owner_death), ("yes", "disabled"))
        self.assertEqual(f.effects, ("slow:enemies",))
        self.assertEqual(f.lifetime, "game_data/zed-trap-game-data#life.initial_life_span_s")
        self.assertEqual(f.states, ("equip", "activate"))
        errors = [m for lvl, m in domain.validate(facts, root=self.s.root)
                  if lvl == "ERROR" and "zed-trap-lifecycle" in m]
        self.assertEqual(errors, [])
        # A second import never rewrites the fact.
        texts, skipped = ms.import_rows(self.s.store, self.s.rows, write=True,
                                        target=self.target, out=io.StringIO())
        self.assertEqual(texts, [])
        self.assertTrue(any("exists" in s for s in skipped))

    def test_an_answer_under_a_renamed_column_stays_valid(self):
        ms.append_answer(self.s.store, {"key": "Zed:C:states", "answer": ["equip"], "unsure": False})
        self.assertIn("Zed:C:engine_states", self.answers())

    def test_validate_rejects_a_class_outside_the_plan(self):
        (self.s.dom / "abilities.toml").write_text(GD + """
[zed-trap-lifecycle]
claim = "x"
kind = "lifecycle"
known = "player"
since = "2026-10-09"
subject = "zed:trap"
lifecycle_class = "projectile"
""", encoding="utf-8")
        msgs = [m for lvl, m in domain.validate(domain.load(self.s.dom), root=self.s.root)
                if lvl == "ERROR"]
        self.assertTrue(any("lifecycle_class projectile" in m for m in msgs))


ASTRA_FACTS = GD + """
[astra-nebula-global-placement]
claim = "Astra's smoke placement is global."
kind = "rule"
known = "player"
since = "2026-09-29"
subject = "astra:nebula"

[astra-astral-form-any-time]
claim = "Astra can enter Astral Form at any time."
kind = "rule"
known = "player"
since = "2026-10-09"
subject = "astra:astral form"

[astra-astral-form-body-stays]
claim = "In Astral Form, Astra's body stays where she entered the form."
kind = "rule"
known = "player"
since = "2026-10-09"
subject = "astra:astral form"
"""
ASTRA = {"agents": {
    "Astra": {"codename": "Rift", "abilities": {"E": {
        "ability": "Nebula  / Dissipate", "equippable": "/Game/Characters/Rift/Ability_E",
        "entities": [{"entity": "/Game/Characters/Rift/GameObject_Rift_E_SmokeZone",
                      "how": "spawns", "named_by": "/Game/Characters/Rift/Ability_E"}],
        "states": []}}},
    "Zed": STATES["agents"]["Zed"]}}


class PlacementAndModesTest(unittest.TestCase):
    """Placement comes from the ability's own fact; modes are asked per agent."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        dom = self.root / "domain"
        dom.mkdir()
        (dom / "abilities.toml").write_text(ASTRA_FACTS, encoding="utf-8")
        self.facts = domain.load(dom)
        self.rows = ms.build_rows(ASTRA, self.facts, ms.GameExports(self.root), {})
        self.agents = {r["agent"]: r for r in ms.build_agent_rows(ASTRA, self.facts)}

    def tearDown(self):
        self.tmp.cleanup()

    def test_a_global_placement_fact_fills_its_ability_only(self):
        nebula = next(r for r in self.rows if r["agent"] == "Astra")
        cell = nebula["cells"]["placement"]
        self.assertEqual((cell["status"], cell["value"]), ("confirm", "global"))
        self.assertEqual(cell["sources"], ["[domain:abilities/astra-nebula-global-placement]"])
        zed = next(r for r in self.rows if r["agent"] == "Zed")
        self.assertEqual(zed["cells"]["placement"]["status"], "ask")
        text, _ = ms.render(nebula, "placement", ms.cell_key(nebula, "placement"), {})
        self.assertEqual(nebula["ability"], "Nebula / Dissipate")
        self.assertIn("  Where can Astra put Nebula / Dissipate?\n"
                      "    1 anywhere on the map, wherever Astra is standing\n"
                      "    2 only within reach of where Astra stands\n"
                      "    3 doesn't apply: it isn't put anywhere\n", text)
        self.assertIn("Suggested: anywhere on the map, wherever Astra is standing.", text)

    def test_modes_prefill_from_facts_and_ask_plainly_elsewhere(self):
        astra, zed = self.agents["Astra"], self.agents["Zed"]
        self.assertEqual(astra["cells"]["modes"]["value"], ["Astral Form"])
        self.assertEqual(zed["cells"]["modes"]["status"], "ask")
        text, _ = ms.render(zed, "modes", ms.cell_key(zed, "modes"), {})
        self.assertIn("Does Zed have a mode or view they enter, separate from casting one "
                      "ability? (e.g. Astra's Astral Form)", text)
        self.assertEqual(ms.cell_key(astra, "modes"), "Astra:modes")
        qs = ms.questions(self.rows + list(self.agents.values()), {}, agent="Astra")
        self.assertEqual(qs[0][1], "modes")
        self.assertEqual(ms.resolve(astra, {})[0], None)


if __name__ == "__main__":
    unittest.main()
