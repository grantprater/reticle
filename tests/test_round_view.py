"""The round viewer consumes stored events only, and decides nothing."""
import ast
import json
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
#: widget's placement, and the event contract. Nothing that reads pixels,
#: tracks, or adjudicates.
ALLOWED = {"store", "profiles", "widget_frame", "view_events", "events", "version"}


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
            | set(arch["entities"]["modules"]) | {"passes", "pipeline", "trial", "roi_cache"}
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
        self.assertFalse(set(got) & bad, got)


def _write(store, stream, sid, rows):
    p = store.events_path(stream, sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _manifest(sid):
    return {"session_id": sid, "ingested_at": "2026-09-30T00:00:00+00:00",
            "source_profile": "valorant-16x9",
            "source": {"width": 1920, "height": 1080, "path": "none"}}


class Loader(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(self.tmp.name)
        self.sid = "abc123"
        _write(self.store, "round_entity", self.sid, [
            {"kind": "entity", "round_no": 2, "id": "abc123:R2:E0001/P0", "agent": "Jett",
             "identity_status": "resolved"},
            {"kind": "entity", "round_no": 2, "id": "abc123:R2:E0002", "agent": None,
             "identity_status": "abstained", "identity_reason": "no teammate fits"},
            {"kind": "observation", "round_no": 2, "t_ms": 1000.0, "entity_id": "abc123:R2:E0001/P0",
             "name": "ally 1", "family": "ally", "identity_status": "resolved", "x": 50, "y": 60,
             "observation_id": "abc123:R2:O1", "state": "continuation",
             "round_entity_version": "round-entity-9"},
            {"kind": "observation", "round_no": 2, "t_ms": 1000.0, "entity_id": "abc123:R2:E0002",
             "name": "ally 2", "family": "ally", "identity_status": "resolved", "x": 90, "y": 90,
             "observation_id": "abc123:R2:O2", "state": "continuation"},
            {"kind": "observation", "round_no": 2, "t_ms": 1066.0, "entity_id": None,
             "name": None, "family": "ally", "identity_status": "refused", "x": 10, "y": 10,
             "observation_id": "abc123:R2:O3", "state": "roster_conflict_refused"},
        ])
        _write(self.store, "death", self.sid, [
            {"kind": "death_verdict", "t_ms": 1500.0, "death_id": "death:abc123:1500:0",
             "status": "abstained", "reason": "no witness", "victim": None, "killer": "Sova",
             "side": "enemy", "death_adjudication_version": "death-9"}])
        _write(self.store, "ping", self.sid, [
            {"kind": "danger", "t_ms": 1200, "x": 5, "y": 6, "lifetime_s": 2.0,
             "ping_version": "ping-9"}])

    def tearDown(self):
        self.tmp.cleanup()

    def load(self):
        return ve.load(self.store, _manifest(self.sid), 0.0, 5000.0, {"round_no": 2,
                                                                     "t_start_ms": 0.0,
                                                                     "t_close_ms": 5000.0})

    def test_every_item_comes_from_a_stored_row(self):
        L = self.load()
        ids = {it.event_id for it in L.items["round_entity"]}
        self.assertEqual(ids, {"abc123:R2:O1", "abc123:R2:O2", "abc123:R2:O3"})
        jett = next(it for it in L.items["round_entity"] if it.event_id == "abc123:R2:O1")
        self.assertEqual(jett.label, "ally 1=Jett")
        self.assertIsNone(jett.facing)              # the stream stores no facing
        self.assertEqual(jett.version, "round-entity-9")

    def test_refusal_and_abstention_keep_their_reasons(self):
        L = self.load()
        by = {it.event_id: it for it in L.items["round_entity"]}
        self.assertEqual(by["abc123:R2:O3"].status, "refused")
        self.assertEqual(by["abc123:R2:O3"].reason, "roster_conflict_refused")
        self.assertEqual(by["abc123:R2:O2"].status, "abstained")
        self.assertIn("no teammate fits", by["abc123:R2:O2"].reason)
        death = L.items["death"][0]
        self.assertEqual(death.status, "abstained")
        self.assertIn("no witness", death.reason)
        self.assertIn(death.status, ve.NOT_READ)

    def test_absent_stream_is_named_not_empty(self):
        L = self.load()
        self.assertEqual(L.presence["team_vision"], "no stream for this session")
        self.assertEqual(L.items["team_vision"], [])

    def test_sampled_items_hold_only_until_stale(self):
        L = self.load()
        self.assertEqual(len(L.active("round_entity", 1030.0)), 2)
        self.assertEqual(len(L.active("round_entity", 1070.0)), 1)   # the next sample
        self.assertEqual(L.active("round_entity", 1500.0), [])       # past the hold
        self.assertEqual(len(L.active("ping", 3000.0)), 1)           # its stored lifetime
        self.assertEqual(L.active("ping", 3300.0), [])

    def test_marks_cite_the_nearest_stored_event_and_are_never_seeded(self):
        L = self.load()
        geo = rv.Geometry(1920, 1080, (0, 0, 331, 329), None)
        path = Path(self.tmp.name) / "labels" / "round_review" / f"{self.sid}.jsonl"
        marks = rv.Marks(path, self.sid)
        self.assertFalse(path.exists())
        row = marks.mark(1010.0, "round_entity", L, geo, point=(88.0, 92.0))
        self.assertEqual(row["nearest"]["event_id"], "abc123:R2:O2")
        self.assertEqual(row["nearest"]["version"], None)
        row = marks.mark(1600.0, "death", L, geo)
        self.assertEqual(row["nearest"]["event_id"], "death:abc123:1500:0")
        self.assertEqual(row["nearest"]["version"], "death-9")
        marks.retract_last()
        self.assertEqual([r["layer"] for r in rv.Marks(path, self.sid).live()],
                         ["round_entity"])

    def test_the_gap_table_measures_declared_fields(self):
        rows = {r["stream"]: r for r in ve.gap_rows(self.store, self.sid)}
        self.assertIn("orientation", rows["round_entity"]["lack"])
        self.assertIn("position", rows["round_entity"]["have"])
        self.assertIn("position (declared, null)", rows["death"]["lack"])
        self.assertIsNone(rows["team_vision"]["rows"])
        for spec in ve.STREAMS.values():
            self.assertEqual(set(spec.fields), set(ve.FIELDS), spec.stream)

    def test_render_draws_a_refusal_amber(self):
        L = self.load()
        geo = rv.Geometry(1920, 1080, (0, 0, 331, 329), None)
        img = rv.render(np.zeros((1080, 1920, 3), np.uint8), 1066.0, L, geo, rv.ViewState())
        self.assertEqual(img.shape, (1080 + rv.STRIP_H, 1920, 3))
        amber = np.all(img == np.array(rv.AMBER, np.uint8), axis=2)
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
