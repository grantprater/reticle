from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
from reticle.plan import derived_streams, reader_streams, record_inputs, render, stale
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
    # No plant graphic stream is stored, so the rounds read none.
    store.table("rounds", round_version=ROUND_VERSION, hud_version=HUD_VERSION,
                killfeed_portrait_version=KILLFEED_PORTRAIT_VERSION, plant_graphic_version="none")
    store.events["death:rows"] = [{"death_adjudication_version": DEATH_ADJUDICATION_VERSION,
                                   "inputs": {"hud": HUD_VERSION,
                                              "killfeed_portrait": KILLFEED_PORTRAIT_VERSION,
                                              "killfeed_weapon": KILLFEED_WEAPON_VERSION,
                                              "round": ROUND_VERSION,
                                              # no X marks read, as `reticle deaths` records
                                              "minimap_object": None, "ally_icon": None}}]
    store.events["ult_cast:rows"] = [{"ult_cast_version": ULT_CAST_VERSION,
                                      "inputs": {"ult_line": ULT_LINE_VERSION,
                                                 "round": ROUND_VERSION}}]
    from reticle.roi_cache import ROI_CACHE_VERSION
    from reticle.version import MENU_VERSION
    store.events["menu_open:rows"] = [{"menu_version": MENU_VERSION,
                                       "roi_cache_version": ROI_CACHE_VERSION}]
    # Each head records every stored input it declares, as its writer does.
    for stream in ("death", "ult_cast"):
        record_inputs(store, store.read_manifest("s"), stream, store.events[stream + ":rows"][0])
    return store


def _tray_drops(store) -> None:
    """Current tray drops, for a cast binding that read them."""
    from reticle.version import MENU_VERSION
    store.events["tray_drop:rows"] = [{"tray_version": TRAY_VERSION,
                                       "player_cast_version": PLAYER_CAST_VERSION,
                                       "tray_kit": "no_rows", "menu_open": MENU_VERSION}]


class PlanTests(unittest.TestCase):
    def test_current_store_is_not_stale(self):
        with tempfile.TemporaryDirectory() as d:
            plan = stale(_current_store(Path(d)), ["s"])
            self.assertEqual(plan["s"], {"decode": [], "derived": [], "absent": [], "waived": [],
                                         "declined": [],
                                         "unchecked": [], "held": [], "unrecorded": [],
                                         "widget": None, "placement": {}, "caches": []})
            self.assertEqual(render(plan), "nothing stale over 1 sessions")

    def test_a_per_side_session_without_a_placement_is_named(self):
        """A declared side-based widget needs a placement before its pixels
        are read; plan names the fit and every stored widget reader."""
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            base = store.read_manifest
            store.read_manifest = lambda sid: {**base(sid), "source_profile": "valorant-16x9",
                                               "minimap_mode": {"orientation": "per_side"}}
            p = stale(store, ["s"])["s"]
            self.assertEqual(p["widget"]["placement"]["reason"], "per_side_unplaced")
            moved = {x["stream"] for x in p["decode"] if "widget_placement" in
                     x.get("inputs_moved", [])}
            self.assertEqual(moved, {"minimap", "ping", "ally_icon", "minimap_dark"})
            text = render(stale(store, ["s"]))
            self.assertIn("placement reticle widget-fit s --write", text)
            self.assertLess(text.index("widget-fit"), text.index("ally_icon"))

    def test_a_drawn_collapse_without_a_placement_is_named(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            from reticle.plan import reader_streams as rs
            now = dict((s, v) for s, _, v, _ in rs())["minimap"]
            t = [float(x) for x in range(0, 1_800_000, 500)]
            path = store.minimap_path("s", None)
            pq.write_table(pa.table({"t_ms": t, "widget_drawn": [x < 1_200_000 for x in t]})
                           .replace_schema_metadata({"minimap_version": now}), path)
            rounds = [{"round_no": k + 1, "t_start_ms": k * 100_000.0,
                       "t_end_ms": k * 100_000.0 + 90_000.0} for k in range(18)]
            pq.write_table(pa.Table.from_pylist(rounds).replace_schema_metadata(
                {"round_version": ROUND_VERSION, "hud_version": HUD_VERSION,
                 "killfeed_portrait_version": KILLFEED_PORTRAIT_VERSION,
                 "plant_graphic_version": "none"}), store.rounds_path("s", None))
            p = stale(store, ["s"])["s"]
            w = p["widget"]["placement"]
            self.assertEqual(w["reason"], "drawn_collapse_unplaced")
            self.assertEqual(w["collapse"]["round_no"], 13)

    def test_unrecorded_portrait_stamp_stales_rounds_then_deaths(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.table("rounds", round_version=ROUND_VERSION, hud_version=HUD_VERSION,
                        plant_graphic_version="none")
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
                        killfeed_portrait_version="none", plant_graphic_version="none")
            derived = stale(store, ["s"])["s"]["derived"]
            # The rescan rewrites the portraits, and then the badges move the rounds.
            self.assertEqual(derived[0]["inputs_moved"], ["killfeed_portrait"])

    def test_a_stored_plant_graphic_stales_rounds_built_without_it(self):
        from reticle.version import PLANT_GRAPHIC_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["plant_graphic"] = [{"v": PLANT_GRAPHIC_VERSION}]
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual(derived[0]["stream"], "rounds")
            self.assertEqual(derived[0]["inputs_moved"], ["plant_graphic"])

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
            _tray_drops(store)
            store.events["ult_cast:rows"][0]["inputs"].update(tray_drop="tray-0.0.1",
                                                              hud=HUD_VERSION,
                                                              player_cast=PLAYER_CAST_VERSION)
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ult_cast", ["tray_drop"])])
            store.events["ult_cast:rows"][0]["inputs"]["tray_drop"] = TRAY_VERSION
            store.table("hud", hud_version="hud-0.0.1")
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            # The drops' gate read the HUD too, so the binding follows them.
            self.assertEqual(derived["ult_cast"]["inputs_moved"], ["hud", "round", "tray_drop"])


    def test_casts_bound_before_the_gate_had_its_own_stamp_are_stale(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            _tray_drops(store)
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
                              ("ability_shape", ["player_cast", "tray_drop"],
                               "reticle ability-shapes s")])
            for stream in ("tray_drop", "ability_shape"):
                store.events[stream + ":rows"][0]["player_cast_version"] = PLAYER_CAST_VERSION
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["ability_shape:rows"][0]["tray_version"] = "tray-0.0.1"
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ability_shape", ["tray_drop"])])

    def test_a_moved_candidate_table_stales_the_shapes(self):
        # `reticle ability-shapes` picks and sizes each fit from the candidate
        # table, and records its stamp and its facts' digest; both are compared.
        from reticle.ability_candidates import values_digest
        from reticle.plan import compared_paths
        from reticle.version import ABILITY_CANDIDATES_VERSION
        self.assertTrue({"ability_candidates_version", "appearance_values"}
                        <= compared_paths()["ability_shape"])
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            _tray_drops(store)
            head = {"ability_shape_version": ABILITY_SHAPE_VERSION, "tray_version": TRAY_VERSION,
                    "player_cast_version": PLAYER_CAST_VERSION}
            # A head written before the table was recorded is not compared on it.
            store.events["ability_shape:rows"] = [dict(head)]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            head.update(ability_candidates_version=ABILITY_CANDIDATES_VERSION,
                        appearance_values=values_digest())
            store.events["ability_shape:rows"] = [dict(head)]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            store.events["ability_shape:rows"] = [{**head, "ability_candidates_version":
                                                   "ability-candidates-0.0.1"}]
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ability_shape", ["candidates"])])
            store.events["ability_shape:rows"] = [{**head, "appearance_values": "000000000000"}]
            derived = stale(store, ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"]) for x in derived],
                             [("ability_shape", ["appearance_values"])])

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
                             [("ult_cast", ULT_CAST_VERSION, ["player_cast", "tray_drop"]),
                              ("tray_drop", TRAY_VERSION, ["player_cast"]),
                              ("ability_shape", ABILITY_SHAPE_VERSION,
                               ["player_cast", "tray_drop"])])


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
                              ("scoreboard_presence", ["scoreboard", "scoreboard_strip"],
                               "reticle openings s")])

    def test_a_reader_claim_or_strip_change_stales_the_round_outcomes(self):
        from reticle.roi_cache import ROI_CACHE_VERSION
        from reticle.version import (ROUND_OUTCOME_CLAIM_VERSION, ROUND_OUTCOME_VERSION,
                                     SCOREBOARD_STRIP_VERSION)
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["scoreboard_strip:rows"] = [{"scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                                                      "roi_cache_version": ROI_CACHE_VERSION}]
            store.events["round_outcome:rows"] = [
                {"round_outcome_version": ROUND_OUTCOME_VERSION,
                 "roi_cache_version": ROI_CACHE_VERSION,
                 "scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                 "round_outcome_claim_version": ROUND_OUTCOME_CLAIM_VERSION}]
            self.assertEqual(stale(store, ["s"])["s"]["derived"], [])
            head = store.events["round_outcome:rows"][0]
            head["round_outcome_version"] = "round-outcome-0.0.1"
            head["round_outcome_claim_version"] = "round-outcome-claim-0.0.1"
            store.events["scoreboard_strip:rows"][0]["scoreboard_strip_version"] = "strip-0.0.1"
            derived = {x["stream"]: x for x in stale(store, ["s"])["s"]["derived"]}
            got = derived["round_outcome"]
            self.assertEqual((got["command"], got["how"], got["stored"]),
                             ("reticle round-outcome s", "cache", "round-outcome-0.0.1"))
            self.assertIn("round_outcome_claim_version", got["inputs_moved"])
            self.assertIn("scoreboard_strip", got["inputs_moved"])

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
        from reticle.roi_cache import ROI_CACHE_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["scoreboard_strip:rows"] = [{"scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
                                                      "roi_cache_version": ROI_CACHE_VERSION}]
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
                # The lineup view folds the board in, so its readers follow it.
                self.assertEqual([(x["stream"], x["inputs_moved"]) for x in p["derived"]],
                                 [("death", ["scoreboard", "lineup"]),
                                  ("scoreboard_presence", ["scoreboard"]),
                                  ("ult_cast", ["lineup"])] if is_stale else [],
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


def _ally_store(root: Path, manifest: dict, tables: bool = True) -> _Store:
    """A current store whose ally_icon stream was written at 0.11.0, read
    through `manifest`; `tables` stores a minimap and a round table that hold
    the columns a side switch is looked for in, with no collapse."""
    from reticle.plan import reader_streams as rs
    store = _current_store(root)
    store.events["ally_icon"] = [{"v": "ally-icon-0.11.0"}]
    base = store.read_manifest
    store.read_manifest = lambda sid: {**base(sid), **manifest}
    if tables:
        now = dict((s, v) for s, _, v, _ in rs())["minimap"]
        t = [float(x) for x in range(0, 1_800_000, 500)]
        pq.write_table(pa.table({"t_ms": t, "widget_drawn": [True] * len(t)})
                       .replace_schema_metadata({"minimap_version": now}),
                       store.minimap_path("s", None))
        rounds = [{"round_no": k + 1, "t_start_ms": k * 100_000.0,
                   "t_end_ms": k * 100_000.0 + 90_000.0} for k in range(18)]
        pq.write_table(pa.Table.from_pylist(rounds).replace_schema_metadata(
            {"round_version": ROUND_VERSION, "hud_version": HUD_VERSION,
             "killfeed_portrait_version": KILLFEED_PORTRAIT_VERSION,
             "plant_graphic_version": "none"}), store.rounds_path("s", None))
    return store


def _placement(*rotations) -> dict:
    """A stored widget placement of one identity segment per rotation, split
    at 900 s."""
    from reticle.widget_frame import MANIFEST_KEY
    roi = [0, 0, 100, 100]
    bounds = [(None, 900_000.0), (900_000.0, None)] if len(rotations) == 2 else [(None, None)]
    return {MANIFEST_KEY: {"baked_roi": roi, "segments": [
        {"rotation": r, "t0_ms": a, "t1_ms": b, "affine": [[1, 0, 0], [0, 1, 0]]}
        for r, (a, b) in zip(rotations, bounds)]}}


class AllyIconWaiverTests(unittest.TestCase):
    """The player's 2026-10-04 stamp waiver: stored ally-icon-0.11.0 rows count
    as 0.12.0 only where the stored placement is upright throughout
    (`widget_frame.upright_throughout`)."""

    def test_the_waiver_is_declared_conditional(self):
        from reticle.plan import WAIVER_CONDITIONS, waiver
        from reticle.version import ALLY_ICON_VERSION, STAMP_WAIVERS
        self.assertEqual(ALLY_ICON_VERSION, "ally-icon-0.12.0")
        w = STAMP_WAIVERS[("ally-icon-0.12.0", "ally-icon-0.11.0")]
        self.assertIn(w["when"], WAIVER_CONDITIONS)
        self.assertIn("2026-10-04", w["why"])
        # No session to evaluate the condition on: never accepted.
        self.assertIsNone(waiver("ally-icon-0.11.0", "ally-icon-0.12.0"))
        # An older stamp is never waived.
        self.assertNotIn(("ally-icon-0.12.0", "ally-icon-0.10.0"), STAMP_WAIVERS)

    def _check(self, manifest: dict, tables: bool = True):
        with tempfile.TemporaryDirectory() as d:
            store = _ally_store(Path(d), manifest, tables)
            plan = stale(store, ["s"])
            return plan["s"], render(plan)

    def test_an_upright_session_is_accepted_by_waiver(self):
        for manifest in ({}, _placement(0), _placement(0, 0)):
            p, text = self._check(manifest)
            self.assertEqual([x["stream"] for x in p["decode"]], [], manifest)
            self.assertEqual([(w["stream"], w["stored"], w["current"]) for w in p["waived"]],
                             [("ally_icon", "ally-icon-0.11.0", "ally-icon-0.12.0")])
            self.assertIn("upright", p["waived"][0]["why"])
            self.assertEqual(p["declined"], [])
            self.assertTrue(text.startswith("nothing stale over 1 sessions"), text)
            self.assertIn("waived   ally_icon: ally-icon-0.11.0 accepted as ally-icon-0.12.0 "
                          "by waiver (version.STAMP_WAIVERS, where upright_placement holds)",
                          text)

    def test_a_turned_side_based_session_is_not(self):
        for manifest in (_placement(180, 0), _placement(0, 180),
                         {**_placement(0, 180), "minimap_mode": {"orientation": "per_side"}}):
            p, text = self._check(manifest)
            self.assertIn("ally_icon", [x["stream"] for x in p["decode"]])
            self.assertEqual(p["waived"], [])
            self.assertEqual([(w["stream"], w["why"].split(":")[1].strip())
                              for w in p["declined"]],
                             [("ally_icon", "turned")])
            self.assertIn("not waived ally_icon: ally-icon-0.11.0 stays stale", text)
            self.assertNotIn("accepted as ally-icon-0.12.0", text)

    def test_an_unknown_placement_is_not(self):
        cases = (({"minimap_mode": {"orientation": "per_side"}}, True, "per_side_unplaced"),
                 ({}, False, "no stored minimap and round tables"))
        for manifest, tables, reason in cases:
            p, text = self._check(manifest, tables)
            self.assertIn("ally_icon", [x["stream"] for x in p["decode"]])
            self.assertEqual(p["waived"], [])
            self.assertEqual(len(p["declined"]), 1)
            self.assertIn("unknown", p["declined"][0]["why"])
            self.assertIn(reason, p["declined"][0]["why"])
            self.assertNotIn("accepted as ally-icon-0.12.0", text)

    def test_the_condition_is_the_owners(self):
        """`plan` asks `widget_frame.upright_throughout`; it holds, fails or is
        unknown as the stored placement says."""
        from reticle.widget_frame import upright_throughout
        with tempfile.TemporaryDirectory() as d:
            store = _ally_store(Path(d), {})
            man = store.read_manifest("s")
            self.assertIs(upright_throughout(store, man)[0], True)
            self.assertIs(upright_throughout(store, {**man, **_placement(0, 180)})[0], False)
            self.assertIsNone(upright_throughout(
                store, {**man, "minimap_mode": {"orientation": "per_side"}})[0])


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


class AbilitySupplyStaleTests(unittest.TestCase):
    """On 2026-10-01 `plan` named `scan --only ability` for `ability_fit` heads
    whose `supply.death` read `death-adjudication-0.20.0` beside deaths at
    0.25.0, and the scan answered "requested channels are current": it
    compared each stream's own stamp alone, and `plan` followed `death` only
    while the deaths were themselves stale."""

    def _store(self, d, death_read: str):
        store = _current_store(Path(d))
        for stream in ("ability_fit", "ability_wall"):
            head = {**_declared_head(stream),
                    "supply": {"death": death_read, "rounds": ROUND_VERSION}}
            store.events[stream + ":rows"] = [head]
            store.events[stream] = [{"v": head[f"{stream}_version"]}]
        return store

    def test_plan_names_a_fit_over_older_deaths_after_the_deaths_rerun(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(stale(self._store(d, DEATH_ADJUDICATION_VERSION), ["s"])["s"]["derived"],
                             [])
            derived = stale(self._store(d, "death-adjudication-0.20.0"), ["s"])["s"]["derived"]
            self.assertEqual([(x["stream"], x["inputs_moved"], x["command"]) for x in derived],
                             [("ability_fit", ["death"], "reticle scan s --only ability"),
                              ("ability_wall", ["death"], "reticle scan s --only ability")])

    def test_scan_rereads_what_plan_calls_stale(self):
        from reticle.cli import _ability_stale
        with tempfile.TemporaryDirectory() as d:
            for death_read, want in ((DEATH_ADJUDICATION_VERSION, False),
                                     ("death-adjudication-0.20.0", True)):
                store = self._store(d, death_read)
                self.assertEqual(_ability_stale(store, "s", ("ability_fit", "ability_wall")), want)
                self.assertEqual(bool(stale(store, ["s"])["s"]["derived"]), want)

    def test_a_pass_with_no_supply_read_no_deaths(self):
        with tempfile.TemporaryDirectory() as d:
            store = self._store(d, DEATH_ADJUDICATION_VERSION)
            store.events["ability_fit:rows"][0].update(supply=None, supply_reason="no_lineup",
                                                       ability_candidates_version=None)
            got = stale(store, ["s"])["s"]
            self.assertEqual((got["derived"], got["unrecorded"]), ([], []))
            from reticle.cli import _ability_stale
            self.assertFalse(_ability_stale(store, "s", ("ability_fit",)))


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


class InputCycleTests(unittest.TestCase):
    """The death stream recorded the bytes of the reliability table, which is
    built from the deaths: each rerun of either restaled the other."""

    def test_the_declared_inputs_hold_no_loop(self):
        from reticle.plan import input_cycles
        self.assertEqual(input_cycles(), [])

    def test_the_one_loop_is_the_declared_feedback(self):
        from reticle.plan import input_cycles, input_graph
        self.assertEqual(input_cycles(input_graph(feedback=True)),
                         [["death", "reliability", "death"]])

    def test_a_loop_is_found(self):
        from reticle.plan import input_cycles
        self.assertEqual(input_cycles({"a": {"b"}, "b": {"c"}, "c": {"a", "d"}, "d": set()}),
                         [["a", "b", "c", "a"]])

    def test_deaths_and_reliability_rerun_to_a_clean_plan(self):
        """Two rounds of `reticle deaths` then `reticle reliability`, the table
        folding the death head's bytes as the real one folds its verdicts."""
        import hashlib
        import json
        from reticle.adjudication.reliability import write as write_table

        def deaths(store, table_rule):
            head = {k: v for k, v in store.events["death:rows"][0].items() if k != "inputs"}
            head["inputs"] = {k: v for k, v in store.events["death:rows"][0]["inputs"].items()
                              if k != "reliability_table"}
            head["read"] = table_rule
            record_inputs(store, store.read_manifest("s"), "death", head)
            store.events["death:rows"] = [head]

        def reliability(store):
            digest = hashlib.sha256(json.dumps(store.events["death:rows"][0],
                                               sort_keys=True).encode()).hexdigest()
            write_table(store.root, {"digest": digest}, {"death": DEATH_ADJUDICATION_VERSION})

        def stale_streams(store):
            return [x["stream"] for x in stale(store, ["s"])["s"]["derived"]]

        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            # A table built over an older death rule: the deaths read it.
            write_table(store.root, {"digest": "old"}, {"death": "death-adjudication-0.0.1"})
            deaths(store, "old")
            self.assertEqual(stale_streams(store), [])
            reliability(store)                       # rebuilt over this rule
            self.assertEqual(stale_streams(store), ["death"])
            for _ in range(2):
                deaths(store, "new")
                reliability(store)                   # new bytes, the same rule
                self.assertEqual(stale_streams(store), [])


class BuildOrderTests(unittest.TestCase):
    """A driver ran `plan`'s lines top to bottom and rebuilt `ult_cast` before
    the `tray` and `combat-report` it reads, so the casts went stale again."""

    def test_the_order_graph_holds_no_loop(self):
        from reticle.plan import input_cycles, order_graph
        self.assertEqual(input_cycles(order_graph()[0]), [])

    def test_no_reader_is_built_from_a_rerun_stream(self):
        from reticle.plan import _hand_specs, build_order, order_graph
        graph = order_graph()[0]
        rerun = set(_hand_specs()) | {s["stream"] for s in derived_streams()} | {"rounds"}
        for stream, *_ in reader_streams():
            seen, stack = set(), list(graph.get(stream, ()))
            while stack:
                n = stack.pop()
                if n not in seen:
                    seen.add(n)
                    stack.extend(graph.get(n, ()))
            self.assertFalse(seen & rerun, stream)
        self.assertEqual(build_order(["death", "hud"], graph), ["hud", "death"])

    def test_a_loop_keeps_its_given_order_and_its_dependents_follow(self):
        from reticle.plan import build_order
        graph = {"a": {"b"}, "b": {"a"}, "c": {"a"}}
        self.assertEqual(build_order(["c", "b", "a", "d"], graph), ["b", "a", "c", "d"])

    def test_plan_lines_follow_their_inputs(self):
        from reticle.plan import order_graph
        graph, fold = order_graph()
        rows = [("ult_cast_identity", "reticle ult-cast s1"), ("ult_cast", "reticle ult-cast s1"),
                ("death_identity", "reticle deaths s1"), ("smoke_owner", "reticle smokes s1"),
                ("round_entity", "reticle lifetimes s1"), ("death", "reticle deaths s1"),
                ("combat_report_round", "reticle combat-report s1"),
                ("tray_drop", "reticle tray s1"), ("rounds", "reticle rounds s1"),
                ("tray_kit", "reticle tray-kit s1"), ("ult_cast", "reticle ult-cast s2", "older")]
        # The s2 casts are stale for another reason, so they get a line of their own.
        derived = [{"stream": s, "stored": (rest or ("old",))[0], "current": "new",
                    "inputs_moved": [], "command": c} for s, c, *rest in rows]
        plan = {"s1": {"decode": [], "derived": [d for d in derived if "s1" in d["command"]]},
                "s2": {"decode": [], "derived": [d for d in derived if "s2" in d["command"]]}}
        lines = [ln for ln in render(plan).splitlines() if ln.startswith(("storage", "cache"))]
        order = [ln.split("(", 1)[1].split(":", 1)[0] for ln in lines]
        node = [fold.get(s, s) for s in order]

        def ancestors(s):
            seen, stack = set(), list(graph.get(s, ()))
            while stack:
                n = stack.pop()
                if n not in seen:
                    seen.add(n)
                    stack.extend(graph.get(n, ()))
            return seen

        for i, s in enumerate(node):
            later = set(node[i + 1:]) - {s}
            self.assertFalse(ancestors(s) & later, (order[i], order))
        for want in ("rounds", "tray_drop", "combat_report_round", "death"):
            self.assertLess(order.index(want), order.index("ult_cast"), order)
        # One stream's lines stay together, its identity stream right after.
        self.assertEqual(order[order.index("ult_cast"):order.index("ult_cast") + 3],
                         ["ult_cast", "ult_cast", "ult_cast_identity"])
        self.assertEqual(order[order.index("death") + 1], "death_identity")


class RoundOutcomeGeometryTests(unittest.TestCase):
    def test_the_fitted_column_geometry_is_not_a_stored_input(self):
        """round_outcome's head records `geometry`, its own column fit; doctor
        INPUTS must not call it an undeclared input."""
        import json
        from reticle import plan
        from reticle.doctor import ERROR, check_inputs
        self.assertIn("geometry", plan.NOT_INPUTS)
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "events" / "round_outcome" / "s.jsonl"
            f.parent.mkdir(parents=True)
            f.write_text(json.dumps({"kind": "coverage", "geometry": {"columns": []}}) + "\n",
                         encoding="utf-8")
            found = [m for s, m in check_inputs(Path(d)) if s == ERROR and "geometry" in m]
            self.assertEqual(found, [])


class RecordedInputsDeclaredTests(unittest.TestCase):
    """The stamps the 2026-10-03 writers record: death's stalls and
    round-outcome claims, ability_state's audio witness, and the kit owner's
    basis the gate records on four streams."""

    RECORDED = {"death": ("stalls", "round_outcome_claim"),
                "ability_state": ("ability_audio", "ability_audio_params", "audio_features",
                                  "audio_labels", "tray_kit_own_basis"),
                "ability_shape": ("tray_kit_own_basis",), "tray_drop": ("tray_kit_own_basis",),
                "ult_cast": ("tray_kit_own_basis",)}

    def test_doctor_finds_no_undeclared_input(self):
        import json
        from reticle.doctor import ERROR, check_inputs
        with tempfile.TemporaryDirectory() as d:
            for stream, keys in self.RECORDED.items():
                f = Path(d) / "events" / stream / "s.jsonl"
                f.parent.mkdir(parents=True)
                f.write_text(json.dumps({"inputs": {k: "x-0.1.0" for k in keys}}) + "\n",
                             encoding="utf-8")
            found = [m for s, m in check_inputs(Path(d))
                     if s == ERROR and "plan does not compare" in m]
            self.assertEqual(found, [])

    def test_a_moved_claim_or_audio_file_stales_its_reader(self):
        import json

        import numpy as np

        from reticle.ability_timeline import AUDIO_GATE_DIR
        from reticle.plan import hand_code_fields, inputs_moved
        from reticle.stalls import STALL_VERSION
        from reticle.version import ROUND_OUTCOME_CLAIM_VERSION
        self.assertEqual(hand_code_fields()["death"]["stalls"], ("inputs.stalls", STALL_VERSION))
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            store = _Store(root)
            man = store.read_manifest("s")
            store.events["round_outcome:rows"] = [
                {"round_outcome_claim_version": ROUND_OUTCOME_CLAIM_VERSION}]
            death = {"inputs": {"round_outcome_claim": ROUND_OUTCOME_CLAIM_VERSION}}
            self.assertEqual(inputs_moved(store, man, "death", death)[0], [])
            death["inputs"]["round_outcome_claim"] = "round-outcome-claim-0.0.1"
            self.assertEqual(inputs_moved(store, man, "death", death)[0],
                             ["round_outcome_claim"])
            gate = root / AUDIO_GATE_DIR
            (gate / "features").mkdir(parents=True)
            (gate / "labels").mkdir(parents=True)
            np.savez(gate / "features" / "s.npz", version=np.array("audio-gate-0.1.0"))
            (gate / "labels" / "s.json").write_text(json.dumps({"version": "audio-gate-0.1.0"}),
                                                    encoding="utf-8")
            state = {"inputs": {"audio_features": "audio-gate-0.1.0",
                                "audio_labels": "audio-gate-0.1.0"}}
            self.assertEqual(inputs_moved(store, man, "ability_state", state)[0], [])
            state["inputs"]["audio_features"] = "audio-gate-0.0.1"
            self.assertEqual(inputs_moved(store, man, "ability_state", state)[0],
                             ["audio_features"])
            # A refused witness read no audio: not compared.
            state["inputs"] = {"audio_features": None, "audio_labels": None}
            self.assertEqual(inputs_moved(store, man, "ability_state", state)[0], [])


class PlacementMovedTests(unittest.TestCase):
    """4f207c0c4e39's refit moved its side switch from 1192766.67 ms to
    1148000 ms; 37 ally_icon frame rows read through the old placement went
    unnamed, since no stamp moved. A change of the stored placement is an
    input change of every stream that read the widget's pixels."""

    OLD = ("widget-frame-0.1.0", "2026-09-29T02:50:49+00:00", 1192766.6666666667)
    NEW = ("widget-frame-0.3.0", "2026-10-04T22:09:54+00:00", 1148000.0)

    def _store(self, d):
        from tests.test_widget_frame import _placement
        store = _current_store(Path(d))
        old = _placement(self.OLD[2], self.OLD[0], self.OLD[1])
        new = _placement(self.NEW[2], self.NEW[0], self.NEW[1])
        base = store.read_manifest
        extra = {"minimap_widget": new, "minimap_widget_history": [old],
                 "source_profile": "valorant-16x9"}
        store.read_manifest = lambda sid: {**base(sid), **extra}
        return store, old, new

    def _ally(self, store, placement):
        from reticle.version import ALLY_ICON_VERSION
        head = {"v": ALLY_ICON_VERSION, "ally_icon_version": ALLY_ICON_VERSION}
        if placement is not None:
            head["widget_placement"] = placement
        store.events["ally_icon"] = [head]
        store.events["ally_icon:rows"] = [head]

    def test_a_head_read_through_the_old_placement_is_named(self):
        from reticle import widget_frame as wf
        with tempfile.TemporaryDirectory() as d:
            store, old, _new = self._store(d)
            self._ally(store, wf.placement_identity({"minimap_widget": old}))
            p = stale(store, ["s"])["s"]
            ally = [x for x in p["decode"] if x["stream"] == "ally_icon"]
            self.assertEqual(len(ally), 1)
            self.assertIn("widget_placement", ally[0]["inputs_moved"])
            self.assertIn("ally_icon", p["placement"])
            self.assertIn("reticle scan <sid> --only ally_icon", render({"s": p}))

    def test_a_head_read_through_the_stored_placement_is_current(self):
        from reticle import widget_frame as wf
        with tempfile.TemporaryDirectory() as d:
            store, _old, new = self._store(d)
            self._ally(store, wf.placement_identity({"minimap_widget": new}))
            p = stale(store, ["s"])["s"]
            self.assertNotIn("ally_icon", {x["stream"] for x in p["decode"]})
            # A refit that moves only the stamp moves no pixel.
            self._ally(store, "widget-frame-0.2.0#" + wf.placement_digest(new))
            self.assertNotIn("ally_icon", stale(store, ["s"])["s"]["placement"])

    def test_an_unrecorded_table_written_before_the_change_is_named(self):
        import datetime as dt
        import os
        with tempfile.TemporaryDirectory() as d:
            store, _old, _new = self._store(d)
            path = store.minimap_path("s", None)
            before = dt.datetime(2026, 10, 4, 21, 0, tzinfo=dt.timezone.utc).timestamp()
            os.utime(path, (before, before))
            p = stale(store, ["s"])["s"]
            self.assertIn("2026-10-04T22:09:54", p["placement"]["minimap"])
            mm = [x for x in p["decode"] if x["stream"] == "minimap"]
            self.assertEqual(mm[0]["inputs_moved"], ["widget_placement"])
            after = dt.datetime(2026, 10, 4, 23, 0, tzinfo=dt.timezone.utc).timestamp()
            os.utime(path, (after, after))
            self.assertNotIn("minimap", stale(store, ["s"])["s"]["placement"])

    def test_a_recorded_table_is_compared_by_its_record(self):
        from reticle import widget_frame as wf
        from reticle.plan import placement_moved, reader_streams as rs
        with tempfile.TemporaryDirectory() as d:
            store, old, new = self._store(d)
            man = store.read_manifest("s")
            now = dict((s, v) for s, _, v, _ in rs())["minimap"]
            store.table("minimap", minimap_version=now,
                        widget_placement=wf.placement_identity({"minimap_widget": new}))
            self.assertIsNone(placement_moved(store, man, "minimap"))
            store.table("minimap", minimap_version=now,
                        widget_placement=wf.placement_identity({"minimap_widget": old}))
            self.assertIsNotNone(placement_moved(store, man, "minimap"))

    def test_a_derived_widget_stream_is_named_and_recorded(self):
        from reticle import widget_frame as wf
        from reticle.plan import placement_moved, record_inputs
        from reticle.version import TEAM_VISION_VERSION
        with tempfile.TemporaryDirectory() as d:
            store, old, _new = self._store(d)
            man = store.read_manifest("s")
            head = record_inputs(store, man, "team_vision",
                                 {"team_vision_version": TEAM_VISION_VERSION})
            self.assertEqual(head["widget_placement"], wf.placement_identity(man))
            head["widget_placement"] = wf.placement_identity({"minimap_widget": old})
            store.events["team_vision:rows"] = [head]
            self.assertIsNotNone(placement_moved(store, man, "team_vision"))
            vision = [x for x in stale(store, ["s"])["s"]["derived"]
                      if x["stream"] == "team_vision"]
            self.assertIn("widget_placement", vision[0]["inputs_moved"])

    def test_a_session_with_no_placement_is_never_named(self):
        import os
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            os.utime(store.minimap_path("s", None), (0, 0))
            self.assertEqual(stale(store, ["s"])["s"]["placement"], {})


class _SpanStore(_Store):
    """A store that holds the spans table the minimap readers read."""

    def spans_path(self, sid, date):
        return self._path("spans", sid, date)


class SpanPlanTests(unittest.TestCase):
    """seg-0.3.0: the minimap readers read every in-match span, so spans the
    segmenter rebuilt stale every reader that read the old ones."""

    def _store(self, root: Path, seg: str, dark_head: dict) -> _SpanStore:
        store = _current_store(root)
        store.__class__ = _SpanStore
        store.table("spans", segmenter_version=seg)
        store.events["minimap_dark:rows"] = [dark_head]
        return store

    def test_old_spans_name_the_segment_rerun_and_every_span_reader(self):
        from reticle.version import SEGMENTER_VERSION
        with tempfile.TemporaryDirectory() as d:
            plan = stale(self._store(Path(d), "seg-0.2.0", {}), ["s"])["s"]
            spans = [x for x in plan["derived"] if x["stream"] == "spans"]
            self.assertEqual([(x["stored"], x["current"], x["command"]) for x in spans],
                             [("seg-0.2.0", SEGMENTER_VERSION, "reticle segment s")])
            moved = {x["stream"] for x in plan["decode"] if "spans" in x.get("inputs_moved", [])}
            self.assertEqual(moved, {"minimap", "ping", "ally_icon", "minimap_dark"})
            self.assertIn("reticle segment <sid>", render({"s": plan}))

    def test_a_reader_read_before_the_rebuild_is_stale_after_it(self):
        from reticle.version import SEGMENTER_VERSION
        with tempfile.TemporaryDirectory() as d:
            # Its head records no spans: it read seg-0.2.0's active spans.
            plan = stale(self._store(Path(d), SEGMENTER_VERSION, {}), ["s"])["s"]
            self.assertNotIn("spans", [x["stream"] for x in plan["derived"]])
            dark = [x for x in plan["decode"] if x["stream"] == "minimap_dark"]
            self.assertEqual([x["inputs_moved"] for x in dark], [["spans"]])
            self.assertIn("minimap", [x["stream"] for x in plan["decode"]])

    def test_a_reader_that_read_the_current_spans_is_current(self):
        from reticle.plan import spans_read_moved
        from reticle.version import MINIMAP_VERSION, SEGMENTER_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = self._store(Path(d), SEGMENTER_VERSION,
                                {"inputs": {"spans": SEGMENTER_VERSION}})
            plan = stale(store, ["s"])["s"]
            self.assertNotIn("minimap_dark", [x["stream"] for x in plan["decode"]])
            # `scan` asks the same question before it rereads.
            man = store.read_manifest("s")
            self.assertFalse(spans_read_moved(store, man, "minimap_dark"))
            self.assertTrue(spans_read_moved(store, man, "minimap"))
            store.table("minimap", minimap_version=MINIMAP_VERSION,
                        segmenter_version=SEGMENTER_VERSION)
            self.assertFalse(spans_read_moved(store, man, "minimap"))


if __name__ == "__main__":
    unittest.main()
