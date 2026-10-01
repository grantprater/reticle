from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
from reticle.plan import derived_streams, reader_streams, render, stale
from reticle.version import (ABILITY_SHAPE_VERSION, HUD_VERSION, PLAYER_CAST_VERSION,
                            ROUND_VERSION, TRAY_VERSION, ULT_CAST_VERSION, ULT_LINE_VERSION)


class _Store:
    """Only what `plan.stale` reads: stamped tables on disk, event stamps in memory."""

    def __init__(self, root: Path):
        self.root = root
        self.events: dict[str, list[dict]] = {}

    def read_manifest(self, sid):
        return {"session_id": sid, "ingested_at": "2026-09-25T00:00:00"}

    def _path(self, kind, sid, date):
        return self.root / kind / f"{sid}.parquet"

    def hud_path(self, sid, date):
        return self._path("hud", sid, date)

    def minimap_path(self, sid, date):
        return self._path("minimap", sid, date)

    def roster_path(self, sid, date):
        return self._path("roster", sid, date)

    def rounds_path(self, sid, date):
        return self._path("rounds", sid, date)

    def events_version(self, stream, sid):
        return self.events.get(stream, [{}])[0].get("v")

    def read_events(self, stream, sid):
        return self.events.get(stream + ":rows", [])

    def table(self, kind, **meta):
        path = self._path(kind, "s", None)
        path.parent.mkdir(parents=True, exist_ok=True)
        pq.write_table(pa.table({"x": [1]}).replace_schema_metadata(meta), path)


def _current_store(root: Path) -> _Store:
    """Every reader stream current, rounds and deaths built from them."""
    store = _Store(root)
    for stream, _, now, _ in reader_streams():
        if stream in ("hud", "minimap", "roster"):
            store.table(stream, **{f"{stream}_version": now})
        else:
            store.events[stream] = [{"v": now}]
    store.table("rounds", round_version=ROUND_VERSION, hud_version=HUD_VERSION,
                killfeed_portrait_version=KILLFEED_PORTRAIT_VERSION)
    store.events["death:rows"] = [{"death_adjudication_version": DEATH_ADJUDICATION_VERSION,
                                   "inputs": {"hud": HUD_VERSION,
                                              "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
                                              "killfeed_weapon": KILLFEED_WEAPON_VERSION,
                                              "round": ROUND_VERSION}}]
    store.events["ult_cast:rows"] = [{"ult_cast_version": ULT_CAST_VERSION,
                                      "inputs": {"ult_line": ULT_LINE_VERSION,
                                                 "round": ROUND_VERSION}}]
    return store


class PlanTests(unittest.TestCase):
    def test_current_store_is_not_stale(self):
        with tempfile.TemporaryDirectory() as d:
            plan = stale(_current_store(Path(d)), ["s"])
            self.assertEqual(plan["s"], {"decode": [], "derived": [], "absent": [], "waived": [],
                                         "unchecked": [], "held": []})
            self.assertEqual(render(plan), "nothing stale over 1 sessions")

    def test_unrecorded_portrait_stamp_stales_rounds_then_deaths(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.table("rounds", round_version=ROUND_VERSION, hud_version=HUD_VERSION)
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([x["stream"] for x in derived], ["rounds", "death", "ult_cast"])
            self.assertEqual(derived[0]["inputs_moved"], ["killfeed_portrait"])
            self.assertEqual(derived[1]["inputs_moved"], ["round"])
            self.assertEqual(derived[2]["inputs_moved"], ["round"])
            text = render(stale(store, ["s"]))
            self.assertLess(text.index("reticle rounds <sid>"), text.index("reticle deaths <sid>"))

    def test_a_hud_rescan_stales_rounds(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.table("hud", hud_version="hud-0.0.1")
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual(derived[0]["stream"], "rounds")
            self.assertEqual(derived[0]["inputs_moved"], ["hud"])
            self.assertEqual(derived[1]["inputs_moved"], ["hud", "round"])

    def test_rounds_built_without_badges_stay_current_while_portraits_are_stale(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["killfeed_portrait"] = [{"v": "killfeed-portrait-0.0.1"}]
            store.table("rounds", round_version=ROUND_VERSION, hud_version=HUD_VERSION,
                        killfeed_portrait_version="none")
            derived = stale(store, ["s"])["s"]["derived"]
            # The rescan rewrites the portraits, and then the badges move the rounds.
            self.assertEqual(derived[0]["inputs_moved"], ["killfeed_portrait"])

    def test_a_round_bump_stales_deaths_built_on_the_old_rounds(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["death:rows"][0]["inputs"]["round"] = "round-0.0.1"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("death", ["round"])])

    def test_a_newer_scoreboard_or_identity_rule_stales_the_deaths(self):
        """`7010b3d62460`'s deaths read scoreboard-0.6.0 after the stream moved
        to 0.9.0, and `plan` called them current."""
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["death:rows"][0]["inputs"].update(
                scoreboard="scoreboard-0.0.1", agent_identity="agent-identity-0.0.1")
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("death", ["agent_identity", "scoreboard"])])

    def test_stale_voice_line_peaks_reread_the_audio_then_rerun_the_casts(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["ult_line"] = [{"v": "ult-line-0.0.1"}]
            p = stale(store, ["s"])["s"]
            self.assertEqual([(x["stream"], x["channel"]) for x in p["decode"]],
                             [("ult_line", "audio")])
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in p["derived"]],
                             [("ult_cast", ["ult_line"])])
            text = render(stale(store, ["s"]))
            self.assertIn("accept reticle ult-lines <sid>", text)
            self.assertNotIn("--only audio", text)
            self.assertIn("reticle ult-cast <sid>", text)

    def test_a_round_bump_stales_the_ultimate_casts(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["ult_cast:rows"][0]["ult_cast_version"] = "ult-cast-0.0.1"
            store.events["ult_cast:rows"][0]["inputs"]["round"] = "round-0.0.1"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["stored"], x["inputs_moved"]) for x in derived],
                             [("ult_cast", "ult-cast-0.0.1", ["round"])])

    def test_older_tray_drops_or_a_hud_rescan_stale_the_casts_bound_to_them(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["ult_cast:rows"][0]["inputs"].update(tray_drop="tray-0.0.1",
                                                              hud=HUD_VERSION,
                                                              player_cast=PLAYER_CAST_VERSION)
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ult_cast", ["tray_drop"])])
            store.events["ult_cast:rows"][0]["inputs"]["tray_drop"] = TRAY_VERSION
            store.table("hud", hud_version="hud-0.0.1")
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            self.assertEqual(derived["ult_cast"]["inputs_moved"], ["hud", "round"])


    def test_casts_bound_before_the_gate_had_its_own_stamp_are_stale(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["ult_cast:rows"][0]["inputs"].update(tray_drop=TRAY_VERSION,
                                                              hud=HUD_VERSION)
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ult_cast", ["player_cast"])])
            store.events["ult_cast:rows"][0]["inputs"]["player_cast"] = PLAYER_CAST_VERSION
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])

    def test_a_gate_change_stales_the_stored_verdicts_and_the_shapes(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["tray_drop:rows"] = [{"tray_version": TRAY_VERSION}]
            store.events["ability_shape:rows"] = [{"ability_shape_version": ABILITY_SHAPE_VERSION,
                                                   "tray_version": TRAY_VERSION}]
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"], x["command"]) for x in derived],
                             [("tray_drop", ["player_cast"], "reticle tray s"),
                              ("ability_shape", ["player_cast"], "reticle ability-shapes s")])
            for stream in ("tray_drop", "ability_shape"):
                store.events[stream + ":rows"][0]["player_cast_version"] = PLAYER_CAST_VERSION
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["ability_shape:rows"][0]["tray_version"] = "tray-0.0.1"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ability_shape", ["tray_drop"])])

    def test_rows_the_gate_before_partial_charge_decided_are_stale(self):
        old = "player-cast-0.2.0"
        self.assertNotEqual(old, PLAYER_CAST_VERSION)
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["ult_cast:rows"][0]["inputs"].update(tray_drop=TRAY_VERSION,
                                                              hud=HUD_VERSION, player_cast=old)
            store.events["tray_drop:rows"] = [{"tray_version": TRAY_VERSION,
                                               "player_cast_version": old}]
            store.events["ability_shape:rows"] = [{"ability_shape_version": ABILITY_SHAPE_VERSION,
                                                   "tray_version": TRAY_VERSION,
                                                   "player_cast_version": old}]
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["stored"], x["inputs_moved"]) for x in derived],
                             [("ult_cast", ULT_CAST_VERSION, ["player_cast"]),
                              ("tray_drop", TRAY_VERSION, ["player_cast"]),
                              ("ability_shape", ABILITY_SHAPE_VERSION, ["player_cast"])])


    def test_a_strip_or_board_change_stales_the_strip_then_the_openings(self):
        from reticle.adjudication.scoreboard import SCOREBOARD_AGENT_VERSION
        from reticle.roi_cache import ROI_CACHE_VERSION
        from reticle.version import SCOREBOARD_STRIP_VERSION, SCOREBOARD_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["scoreboard_strip:rows"] = [{"scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                                                      "roi_cache_version": ROI_CACHE_VERSION}]
            store.events["scoreboard_presence:rows"] = [
                {"scoreboard_presence_version": SCOREBOARD_AGENT_VERSION,
                 "scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                 "scoreboard_version": SCOREBOARD_VERSION}]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["scoreboard_strip:rows"][0]["roi_cache_version"] = "roi-cache-0.0.1"
            store.events["scoreboard_presence:rows"][0]["scoreboard_version"] = "scoreboard-0.0.1"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"], x["command"]) for x in derived],
                             [("scoreboard_strip", ["roi_cache"], "reticle strip s"),
                              ("scoreboard_presence", ["scoreboard"], "reticle openings s")])

    def test_the_waiver_accepts_scoreboard_0_12_0_and_names_it(self):
        """The player's 2026-09-29 waiver: a 0.12.0 board stream, and the
        deaths and openings read from it, are not stale under 0.13.0, and
        `plan` names them as accepted by waiver. 0.11.0 and 0.10.0 stay stale."""
        from reticle.adjudication.scoreboard import SCOREBOARD_AGENT_VERSION
        from reticle.version import (SCOREBOARD_STRIP_VERSION, SCOREBOARD_VERSION,
                                     STAMP_WAIVERS)
        self.assertEqual(SCOREBOARD_VERSION, "scoreboard-0.13.0")
        self.assertEqual([k for k in STAMP_WAIVERS if k[0].startswith("scoreboard-")],
                         [("scoreboard-0.13.0", "scoreboard-0.12.0")])
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["scoreboard_presence:rows"] = [
                {"scoreboard_presence_version": SCOREBOARD_AGENT_VERSION,
                 "scoreboard_strip_version": SCOREBOARD_STRIP_VERSION}]
            for old, is_stale in (("scoreboard-0.12.0", False), ("scoreboard-0.11.0", True),
                                  ("scoreboard-0.10.0", True)):
                store.events["scoreboard"] = [{"v": old}]
                store.events["death:rows"][0]["inputs"]["scoreboard"] = old
                store.events["scoreboard_presence:rows"][0]["scoreboard_version"] = old
                plan = stale(store, ["s"])
                p = plan["s"]
                self.assertEqual([x["stream"] for x in p["decode"]],
                                 ["scoreboard"] if is_stale else [], old)
                self.assertEqual([(x["stream"], x["inputs_moved"]) for x in p["derived"]],
                                 [("death", ["scoreboard"]),
                                  ("scoreboard_presence", ["scoreboard"])] if is_stale else [],
                                 old)
                if is_stale:
                    self.assertEqual(p["waived"], [])
                    self.assertNotIn("waiver", render(plan))
                    continue
                self.assertEqual([(w["stream"], w["stored"], w["current"]) for w in p["waived"]],
                                 [("scoreboard", old, SCOREBOARD_VERSION),
                                  ("death input scoreboard", old, SCOREBOARD_VERSION),
                                  ("scoreboard_presence input scoreboard", old,
                                   SCOREBOARD_VERSION)])
                text = render(plan)
                self.assertTrue(text.startswith("nothing stale over 1 sessions"))
                self.assertIn("waived   scoreboard: scoreboard-0.12.0 accepted as "
                              "scoreboard-0.13.0 by waiver", text)


def _declared_head(stream: str) -> dict:
    """A first row of `stream` current in every stamp `plan` declares for it."""
    spec = next(s for s in derived_streams() if s["stream"] == stream)
    head = {spec["key"]: spec["current"]}
    for path, value in spec["fields"].items():
        *parents, leaf = path.split(".")
        at = head
        for part in parents:
            at = at.setdefault(part, {})
        at[leaf] = value
    return head


class DeclaredStreamTests(unittest.TestCase):
    """`plan` once compared a hand-picked list, so `team_vision` at 0.3.0 under
    0.6.0 and `round_entity` at 0.8.0 under 0.9.0 read as current."""

    def test_an_old_team_vision_and_round_entity_are_named_with_their_commands(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            for stream in ("team_vision", "round_entity"):
                store.events[stream + ":rows"] = [_declared_head(stream)]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["team_vision:rows"][0]["team_vision_version"] = "team-vision-0.0.1"
            store.events["round_entity:rows"][0]["round_entity_version"] = "round-entity-0.0.1"
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            self.assertEqual((derived["team_vision"]["command"], derived["team_vision"]["how"]),
                             ("reticle vision s", "cache"))
            self.assertEqual((derived["round_entity"]["command"], derived["round_entity"]["how"]),
                             ("reticle lifetimes s", "storage"))
            text = render(stale(store, ["s"]))
            self.assertIn("cache    reticle vision <sid>   (team_vision: team-vision-0.0.1 -> ",
                          text)
            self.assertIn("storage  reticle lifetimes <sid>", text)

    def test_a_stale_ally_icon_holds_round_entity_behind_it(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["round_entity:rows"] = [_declared_head("round_entity")]
            store.events["ally_icon"] = [{"v": "ally-icon-0.0.1"}]
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            self.assertEqual(derived["round_entity"]["inputs_moved"], ["ally_icon"])

    def test_a_cone_cast_over_another_occluder_table_is_stale(self):
        import numpy as np
        from reticle import geometry
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            path = geometry.path("m__p", d)
            path.parent.mkdir(parents=True)
            np.savez(path, occ=np.zeros((2, 2), bool), occ_built_by=np.array("occluders-2.0.0"))
            head = {**_declared_head("team_vision"), "geometry_key": "m__p",
                    "occluders": "occluders-2.0.0"}
            store.events["team_vision:rows"] = [head]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            head["occluders"] = "occluders-1.0.0"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("team_vision", ["occluders"])])
            head["occluders"] = None      # cast before the geometry held a table
            self.assertEqual(stale(store, ["s"])["s"]["derived"][0]["inputs_moved"],
                             ["occluders"])


class EnemyLaneStaleTests(unittest.TestCase):
    """The enemy lane: each fix is part of the `minimap_object` stamp, so a
    stream read with a fix off is stale, and the tracks and deaths built on it
    move with it."""

    def _store(self, d):
        from reticle.minimap_objects import minimap_object_version
        store = _current_store(Path(d))
        for stream in ("minimap_object", "enemy_track"):
            store.events[stream + ":rows"] = [_declared_head(stream)]
        store.events["minimap_object"] = [{"v": minimap_object_version()}]
        store.events["death:rows"][0]["inputs"]["minimap_object"] = minimap_object_version()
        return store

    def test_a_fix_turned_off_stales_the_objects_the_tracks_and_the_deaths(self):
        from reticle.minimap_objects import minimap_object_version
        off = minimap_object_version({"teardrop_box": True, "slab_gate": False})
        with tempfile.TemporaryDirectory() as d:
            store = self._store(d)
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["minimap_object:rows"][0]["minimap_object_version"] = off
            store.events["enemy_track:rows"][0]["minimap_object_version"] = off
            store.events["minimap_object"] = [{"v": off}]
            store.events["death:rows"][0]["inputs"]["minimap_object"] = off
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            self.assertEqual((derived["minimap_object"]["stored"],
                              derived["minimap_object"]["how"]), (off, "cache"))
            self.assertIn("minimap_object_version", derived["enemy_track"]["inputs_moved"])
            self.assertEqual(derived["death"]["inputs_moved"], ["minimap_object"])

    def test_deaths_built_before_the_x_marks_are_stale_once_they_are_stored(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store(d)
            del store.events["death:rows"][0]["inputs"]["minimap_object"]
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            self.assertEqual(derived["death"]["inputs_moved"], ["minimap_object"])
            store.events["minimap_object"] = [{"v": None}]       # none stored: current
            self.assertNotIn("death", {x["stream"] for x in stale(store, ["s"])["s"]["derived"]})


if __name__ == "__main__":
    unittest.main()
