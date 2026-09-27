from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from reticle.adjudication.death import DEATH_ADJUDICATION_VERSION
from reticle.killfeed import KILLFEED_PORTRAIT_VERSION, KILLFEED_WEAPON_VERSION
from reticle.plan import reader_streams, render, stale
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
            self.assertEqual(plan["s"], {"decode": [], "derived": [], "absent": []})
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


if __name__ == "__main__":
    unittest.main()
