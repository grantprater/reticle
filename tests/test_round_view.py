"""The round viewer consumes stored events only, and decides nothing."""
import ast
import json
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

import numpy as np

from reticle import round_view as rv
from reticle import view_events as ve
from reticle.store import Store

ROOT = Path(__file__).resolve().parents[1]
CONSUMER = ("round_view", "view_events")
#: The lower modules a consumer may name: the store, the capture layout, the
#: event contract, and `entity_events`, the door the lanes are read through.
#: Nothing that reads pixels, tracks, or adjudicates.
ALLOWED = {"store", "profiles", "view_events", "events", "version", "entity_events"}
READ_THROUGH = "entity_events"

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_entity_events import SID, build_store  # noqa: E402  (the projection's fixture)


def _reticle_imports(module: str) -> set[str]:
    """Every `reticle` module a file imports, at any depth in the file."""
    tree = ast.parse((ROOT / "reticle" / f"{module}.py").read_text(encoding="utf-8"))
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.level == 1:
                if node.module:
                    out.add(node.module)
                else:
                    out.update(a.name for a in node.names)
            elif node.module and node.module.startswith("reticle"):
                out.add(node.module.removeprefix("reticle").lstrip(".") or "reticle")
        elif isinstance(node, ast.Import):
            out.update(a.name.removeprefix("reticle.") for a in node.names
                       if a.name.startswith("reticle"))
    return out


class ImportsNoReader(unittest.TestCase):
    def test_direct_imports_are_the_allowed_few(self):
        for m in CONSUMER:
            self.assertLessEqual(_reticle_imports(m), ALLOWED, m)

    def test_no_reader_or_adjudicator_is_imported_by_layer(self):
        arch = tomllib.loads((ROOT / "architecture.toml").read_text(encoding="utf-8"))
        forbidden = set(arch["readers"]["modules"]) | set(arch["adjudication"]["modules"]) \
            | (set(arch["entities"]["modules"]) - {READ_THROUGH}) \
            | {"passes", "pipeline", "trial", "roi_cache", "widget_frame"}
        for m in CONSUMER:
            self.assertFalse(_reticle_imports(m) & forbidden, m)
            self.assertIn(m, arch["consumers"]["modules"])

    def test_importing_the_viewer_loads_no_reader(self):
        # `store` imports `roster` for one schema constant (N_SLOTS, a blessed
        # edge in architecture.toml); that is the only reader allowed in.
        code = ("import sys, reticle.round_view; "
                "print(' '.join(sorted(m for m in sys.modules if m.startswith('reticle'))))")
        got = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True,
                             text=True, check=True).stdout.split()
        arch = tomllib.loads((ROOT / "architecture.toml").read_text(encoding="utf-8"))
        bad = {f"reticle.{m}" for m in arch["readers"]["modules"] + arch["adjudication"]["modules"]
               + arch["entities"]["modules"]} - {"reticle.roster"}
        bad.discard(f"reticle.{READ_THROUGH}")
        self.assertFalse(set(got) & bad, got)


def _write(store, stream, sid, rows):
    p = store.events_path(stream, sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


ROUND = {"round_no": 1, "t_start_ms": 0.0, "t_close_ms": 65000.0}


class Loader(unittest.TestCase):
    """The lanes of `test_entity_events`' store, projected, then loaded."""

    #: Tests that change the store: each gets a private copy of it.
    WRITES = {"test_absent_stream_and_unprojected_lane_are_named_not_empty",
              "test_a_stale_lane_is_drawn_and_says_so",
              "test_marks_cite_the_nearest_stored_event_and_are_never_seeded"}

    @classmethod
    def setUpClass(cls):
        from reticle import entity_events as ee
        cls.shared = tempfile.TemporaryDirectory()
        cls.shared_store = build_store(Path(cls.shared.name))
        for lane in ee.PROJECTED:
            ee.project_lane(cls.shared_store, SID, lane, stale={})
        _write(cls.shared_store, "ping", SID, [
            {"kind": "danger", "t_ms": 1200, "x": 5, "y": 6, "lifetime_s": 2.0,
             "ping_version": "ping-9"}])

    @classmethod
    def tearDownClass(cls):
        cls.shared.cleanup()

    def setUp(self):
        if self._testMethodName in self.WRITES:
            self.tmp = tempfile.TemporaryDirectory()
            shutil.copytree(self.shared.name, self.tmp.name, dirs_exist_ok=True)
            self.store = Store(Path(self.tmp.name))
        else:
            self.tmp = None
            self.store = self.shared_store

    def tearDown(self):
        if self.tmp is not None:
            self.tmp.cleanup()

    def load(self):
        return ve.load(self.store, self.store.read_manifest(SID), 0.0, 65000.0, ROUND)

    def test_every_item_comes_from_a_stored_row(self):
        L = self.load()
        self.assertEqual({it.event_id for it in L.items["entity_round_entity"]},
                         {"pose:o2", "pose:o3", "pose:o4", "pose:o5"})
        self.assertEqual({it.event_id for it in L.items["entity_round_entity_ledger"]},
                         {"pose:o1", "pose:o6"})
        jett = next(it for it in L.items["entity_round_entity"] if it.event_id == "pose:o2")
        self.assertEqual((jett.label, jett.x, jett.y), ("Jett", 50.0, 60.0))
        self.assertIsNone(jett.facing)              # the lane stores no facing
        self.assertEqual(jett.version, "entity-round-entity-0.1.0")
        self.assertEqual(L.versions["entity_death"], "entity-death-0.2.0")
        self.assertEqual([it.label for it in L.items["entity_spike"]],
                         ["R1 spike planted at 0:50.0"])

    def test_ledger_rows_keep_their_standing_and_reason(self):
        L = self.load()
        by = {it.event_id: it for s in ("entity_round_entity", "entity_round_entity_ledger")
              for it in L.items[s]}
        self.assertEqual((by["pose:o6"].status, by["pose:o6"].reason),
                         ("refused", "refused: two icons overlap"))
        self.assertEqual(by["pose:o1"].status, "disputed")
        self.assertIn("the death owner names its victim Chamber", by["pose:o1"].reason)
        self.assertEqual(by["pose:o1"].detail["alternatives"], ["Skye", "Chamber"])
        self.assertEqual(by["pose:o5"].status, "abstained")      # its name is withheld
        self.assertIn("two agents tie", by["pose:o5"].reason)
        deaths = {it.entity_id: it for s in ("entity_death", "entity_death_ledger")
                  for it in L.items[s]}
        self.assertEqual(deaths["d3"].stream, "entity_death_ledger")
        self.assertEqual((deaths["d3"].status, deaths["d3"].reason),
                         ("abstained", "abstained by the fixture"))
        self.assertEqual(deaths["d2"].status, "refused")          # the weapon read
        self.assertEqual(deaths["d1"].status, "ok")
        self.assertEqual(deaths["d1"].label, "0:30.0 Raze [Ghost] > Chamber")
        for it in (by["pose:o6"], by["pose:o1"], by["pose:o5"], deaths["d3"]):
            self.assertIn(it.status, ve.NOT_READ)
        lost = L.items["entity_spike_ledger"]
        self.assertEqual([(it.status, it.t_ms) for it in lost], [("abstained", 20000.0)])

    def test_absent_stream_and_unprojected_lane_are_named_not_empty(self):
        L = self.load()
        self.assertEqual(L.presence["team_vision"], "no stream for this session")
        self.assertEqual(L.items["team_vision"], [])
        self.store.events_path("entity_spike", SID).unlink()
        L = self.load()
        self.assertIn("not projected", L.presence["entity_spike"])
        self.assertEqual(L.items["entity_spike"], [])

    def test_a_stale_lane_is_drawn_and_says_so(self):
        rows = self.store.read_events("spike_carrier", SID)
        rows[0]["spike_carrier_version"] = "spike-carrier-test-2"
        _write(self.store, "spike_carrier", SID, rows)
        L = self.load()
        self.assertIn("STALE (inputs moved: spike_carrier)", L.presence["entity_spike"])
        self.assertNotIn("STALE", L.presence["entity_death"])
        self.assertEqual(len(L.items["entity_spike"]), 1)

    def test_sampled_items_hold_only_until_stale(self):
        L = self.load()
        self.assertEqual([it.event_id for it in L.active("entity_round_entity", 1030.0)],
                         ["pose:o2"])
        self.assertEqual([it.event_id for it in L.active("entity_round_entity", 1210.0)],
                         ["pose:o5"])
        self.assertEqual(L.active("entity_round_entity", 1450.0), [])   # past the hold
        self.assertEqual([it.event_id for it in L.active("entity_round_entity_ledger",
                                                            1310.0)], ["pose:o6"])
        self.assertEqual(len(L.active("ping", 3000.0)), 1)              # its stored lifetime
        self.assertEqual(L.active("ping", 3300.0), [])

    def test_marks_cite_the_nearest_stored_event_and_are_never_seeded(self):
        L = self.load()
        geo = rv.Geometry(1920, 1080, (0, 0, 331, 329), None)
        path = Path(self.tmp.name) / "labels" / "round_review" / f"{SID}.jsonl"
        marks = rv.Marks(path, SID)
        self.assertFalse(path.exists())
        row = marks.mark(1010.0, "round_entity", L, geo, point=(88.0, 92.0))
        self.assertEqual((row["nearest"]["event_id"], row["nearest"]["stream"]),
                         ("pose:o1", "entity_round_entity_ledger"))
        row = marks.mark(30500.0, "death", L, geo)
        self.assertEqual(row["nearest"]["event_id"], "death:d1")
        self.assertEqual(row["nearest"]["version"], "entity-death-0.2.0")
        marks.retract_last()
        self.assertEqual([r["layer"] for r in rv.Marks(path, SID).live()], ["round_entity"])

    def test_the_gap_table_measures_declared_fields(self):
        rows = {r["stream"]: r for r in ve.gap_rows(self.store, SID)}
        self.assertIn("orientation", rows["round_entity"]["lack"])
        self.assertIn("position", rows["round_entity"]["have"])
        self.assertIn("position (declared, null)", rows["death"]["lack"])
        self.assertIsNone(rows["team_vision"]["rows"])
        for spec in ve.STREAMS.values():
            self.assertEqual(set(spec.fields), set(ve.FIELDS), spec.stream)

    def test_render_draws_a_ledger_row_amber(self):
        L = self.load()
        geo = rv.Geometry(1920, 1080, (0, 0, 331, 329), None)
        img = rv.render(np.zeros((1080, 1920, 3), np.uint8), 1300.0, L, geo, rv.ViewState())
        self.assertEqual(img.shape, (1080 + rv.STRIP_H, 1920, 3))
        amber = np.all(img[:329, :331] == np.array(rv.AMBER, np.uint8), axis=2)
        self.assertTrue(amber.any())


class Declarations(unittest.TestCase):
    def test_stream_owners_exist(self):
        own = tomllib.loads((ROOT / "ownership.toml").read_text(encoding="utf-8"))
        ids = {e["id"] for e in own["entry"]}
        for spec in ve.STREAMS.values():
            self.assertIn(spec.owner, ids, spec.stream)

    def test_unpack_mask_matches_the_owner(self):
        from reticle import lighting
        m = np.random.default_rng(0).random((29, 31)) > 0.5
        self.assertTrue(np.array_equal(ve.unpack_mask(lighting.pack_mask(m)), m))


if __name__ == "__main__":
    unittest.main()
