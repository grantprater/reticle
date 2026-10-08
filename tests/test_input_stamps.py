"""Every derived stream records the stored stamp of each input it read, and
`plan` compares each recorded stamp with the input as stored now.

One test per hole the 2026-09-30 boundary audit found: an upstream current
but other than the one read, `no_rows` that became rows, the lifetimes cache
keyed on fewer inputs than plan compares, and a geometry rebake."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from reticle import input_stamps
from reticle.plan import _hand_specs, hand_code_fields, record_inputs, stale

from tests.test_plan import _current_store, _declared_head, _tray_drops


def _stream_row(store, stream: str, head: dict) -> dict:
    """Store `head` as `stream`'s first row, its inputs recorded as its writer does."""
    record_inputs(store, store.read_manifest("s"), stream, head)
    store.events[stream + ":rows"] = [head]
    return head


def _hand_head(stream: str) -> dict:
    """A hand-checked stream's first row, current in every code stamp."""
    key, current, _ = _hand_specs()[stream]
    head = {key: current}
    for path, value in hand_code_fields()[stream].values():
        *parents, leaf = path.split(".")
        at = head
        for part in parents:
            at = at.setdefault(part, {})
        at[leaf] = value
    return head


def _derived(store) -> dict:
    return {x["stream"]: x for x in stale(store, ["s"], never_run=False)["s"]["derived"]}


class RecordedStampTests(unittest.TestCase):
    def test_a_current_upstream_other_than_the_one_read_stales_the_reader(self):
        """H2: plan compared an input only while the input was itself stale.
        `tray_kit` was rerun to the current stamp after `ability_state` read an
        older one; nothing is stale upstream, and the kit state still is."""
        from reticle.version import TRAY_KIT_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            _tray_drops(store)
            _stream_row(store, "tray_kit", _declared_head("tray_kit"))
            store.events["tray_drop:rows"][0]["tray_kit"] = TRAY_KIT_VERSION
            head = _stream_row(store, "ability_state", _hand_head("ability_state"))
            self.assertEqual(head["inputs"]["tray_kit"], TRAY_KIT_VERSION)
            self.assertNotIn("ability_state", _derived(store))
            head["inputs"]["tray_kit"] = "tray-kit-0.0.1"
            derived = _derived(store)
            self.assertNotIn("tray_kit", derived)
            self.assertIn("tray_kit", derived["ability_state"]["inputs_moved"])

    def test_no_rows_read_then_rows_stored_stales_the_reader(self):
        """`no_rows` is read-and-empty: once the input holds rows, a stream
        built over none is stale; while it holds none, the stream is current."""
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            _tray_drops(store)
            head = _stream_row(store, "ability_state", _hand_head("ability_state"))
            self.assertEqual(head["inputs"]["tray_kit"], input_stamps.NO_ROWS)
            self.assertNotIn("ability_state", _derived(store))
            _stream_row(store, "tray_kit", _declared_head("tray_kit"))
            self.assertIn("tray_kit", _derived(store)["ability_state"]["inputs_moved"])

    def test_minimap_object_over_no_pings_is_stale_once_pings_are_written(self):
        """The owner gate abstains with no ping stream and records `no_rows`,
        not None (not read), so `plan` follows the pings once they appear."""
        from reticle import minimap_objects as mo
        from reticle.version import PING_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events.pop("ping", None)
            _, _, stamp = mo.stored_pings(store, "s")
            self.assertEqual(stamp, input_stamps.NO_ROWS)
            head = _declared_head("minimap_object")
            head["inputs"] = {"ping": stamp}
            _stream_row(store, "minimap_object", head)
            self.assertNotIn("minimap_object", _derived(store))
            store.events["ping"] = [{"v": PING_VERSION}]
            store.events["ping:rows"] = [{"event_kind": "entity_state", "entity_id": "p0",
                                          "t_ms": 0, "position": [1.0, 2.0],
                                          "producer_version": PING_VERSION}]
            self.assertIn("ping", _derived(store)["minimap_object"]["inputs_moved"])

    def test_the_lifetimes_cache_misses_where_plan_lists_round_entity(self):
        """H3: `reticle lifetimes` kept its cache over a roster, HUD, menu or
        self-icon change its key left out, so the command plan printed did
        nothing. The cache now holds only where plan lists no `round_entity`."""
        from reticle.cli import _lifetimes_plan_entry
        from reticle.version import MENU_VERSION
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            head = _declared_head("round_entity")
            head["menu_open"] = MENU_VERSION
            head = _stream_row(store, "round_entity", head)
            self.assertIsNone(_lifetimes_plan_entry(store, "s"))
            # The roster was reread to the current stamp after the lifetimes
            # ran: no upstream is stale, and the entities still are.
            head["inputs"]["roster"] = "roster-0.0.1"
            self.assertEqual(_lifetimes_plan_entry(store, "s")["inputs_moved"], ["roster"])

    def test_a_geometry_rebake_stales_every_stream_read_over_it(self):
        """M7: a rebake staled only the cones' occluder table."""
        from reticle import geometry
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            path = geometry.path("m__p", d)
            path.parent.mkdir(parents=True)
            np.savez(path, built_by=np.array("geometry-1"))
            for stream in ("minimap_object", "team_vision"):
                head = {**_declared_head(stream), "geometry_key": "m__p"}
                self.assertEqual(_stream_row(store, stream, head)["geometry_built_by"],
                                 "geometry-1")
            self.assertEqual(_derived(store), {})
            np.savez(path, built_by=np.array("geometry-2"))
            derived = _derived(store)
            for stream in ("minimap_object", "team_vision"):
                self.assertEqual(derived[stream]["inputs_moved"], ["geometry"], stream)

    def test_an_unrecorded_input_is_named_not_called_current_or_stale(self):
        with tempfile.TemporaryDirectory() as d:
            store = _current_store(Path(d))
            store.events["minimap_object:rows"] = [_declared_head("minimap_object")]
            p = stale(store, ["s"], never_run=False)["s"]
            self.assertEqual(p["derived"], [])
            self.assertEqual(p["unrecorded"], [{"stream": "minimap_object",
                                                "inputs": ["geometry"]}])

    def test_a_not_read_reason_and_older_absence_reasons_normalize(self):
        self.assertIsNone(input_stamps.normalize("no_rounds"))
        self.assertEqual(input_stamps.normalize("no_menu_rows"), input_stamps.NO_ROWS)
        self.assertEqual(input_stamps.normalize("stale:menu-0.1.0"), "menu-0.1.0")
        self.assertFalse(input_stamps.moved(None, "x"))
        self.assertTrue(input_stamps.moved(input_stamps.NO_ROWS, "x"))
        self.assertFalse(input_stamps.moved(input_stamps.NO_ROWS, None))


class InputsCheckTests(unittest.TestCase):
    """`doctor` INPUTS: a stamp a stored head records that plan does not compare."""

    def _store(self, d: str, head: dict) -> Path:
        root = Path(d)
        f = root / "events" / "smoke" / "s.jsonl"
        f.parent.mkdir(parents=True)
        f.write_text(json.dumps(head) + "\n", encoding="utf-8")
        return root

    def test_an_undeclared_recorded_stamp_is_an_error(self):
        from reticle.doctor import ERROR, check_inputs
        with tempfile.TemporaryDirectory() as d:
            root = self._store(d, {"smoke_version": "x", "inputs": {"roster": "roster-1"},
                                   "geometry_key": "m__p"})
            found = [m for s, m in check_inputs(root) if s == ERROR and m.startswith("smoke ")]
            self.assertEqual(len(found), 1, found)
            self.assertIn("inputs.roster", found[0])

    def test_the_code_reads_only_inputs_it_declares(self):
        from reticle.doctor import check_inputs
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual([m for _, m in check_inputs(Path(d))], [])


if __name__ == "__main__":
    unittest.main()
