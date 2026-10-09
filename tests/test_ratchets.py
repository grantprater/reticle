"""`ratchets`: CONVERT, ROUNDSCOPE and the strict PROMOTE, whose allowlists only
shrink. For each: a synthetic violation errors, a listed one warns, and a
stale list entry is reported."""
import tempfile
import textwrap
import unittest
from pathlib import Path

from reticle import doctor, ratchets
from reticle.ratchets import ERROR, WARN, Gate


def _repo(files: dict[str, str]) -> Path:
    root = Path(tempfile.mkdtemp())
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(text), encoding="utf-8")
    return root


READERS = {
    "reticle/grid.py": """
        class GridReader:
            def __init__(self, hz=15.0):
                self.name, self.hz, self.spans = "grid", hz, None
            def feed(self, smp):
                pass
    """,
    "reticle/gated.py": """
        from .ratchets import Gate
        class GatedReader:
            opportunity_gate = Gate(opportunity="a death window", source="stored_windows")
            hz = 4.0
            def feed(self, smp):
                pass
    """,
    "reticle/proto.py": """
        from typing import Protocol
        class Reader(Protocol):
            hz: float
            def feed(self, sample) -> None: ...
    """,
}
LEGACY = {"rate": "15 Hz", "converts": "BACKLOG 1"}


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo(READERS)

    def test_an_ungated_fixed_grid_reader_errors(self):
        found = ratchets.convert_findings(self.root, legacy={})
        self.assertEqual([s for s, m in found if "GridReader" in m], [ERROR])

    def test_a_listed_reader_warns_with_its_rate_and_item(self):
        found = ratchets.convert_findings(self.root, legacy={"reticle/grid.py::GridReader": LEGACY})
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], WARN)
        self.assertIn("15 Hz", found[0][1])
        self.assertIn("BACKLOG 1", found[0][1])

    def test_a_gated_reader_and_a_protocol_pass(self):
        found = ratchets.convert_findings(self.root, legacy={"reticle/grid.py::GridReader": LEGACY})
        self.assertFalse([m for _s, m in found if "GatedReader" in m or "proto.py" in m])

    def test_a_stale_entry_is_reported(self):
        legacy = {"reticle/grid.py::GridReader": LEGACY,
                  "reticle/gated.py::GatedReader": LEGACY,
                  "reticle/gone.py::GoneReader": LEGACY}
        found = ratchets.convert_findings(self.root, legacy=legacy)
        stale = [m for s, m in found if s == ERROR and "remove it from the allowlist" in m]
        self.assertEqual(len(stale), 2)
        self.assertTrue(any("GatedReader" in m for m in stale))
        self.assertTrue(any("GoneReader" in m for m in stale))

    def test_a_gate_must_be_a_gate(self):
        root = _repo({"reticle/bad.py": """
            class BadReader:
                opportunity_gate = {"opportunity": "x"}
                hz = 2.0
                def feed(self, smp):
                    pass
        """})
        found = ratchets.convert_findings(root, legacy={})
        self.assertTrue(any(s == ERROR and "Gate(" in m for s, m in found))

    def test_the_repository_lists_every_fixed_grid_reader_and_gates_clove(self):
        found = ratchets.convert_findings()
        self.assertEqual([m for s, m in found if s == ERROR], [])
        warned = " ".join(m for s, m in found if s == WARN)
        for key in ratchets.CONVERT_LEGACY:
            self.assertIn(key, warned)
        self.assertNotIn("CloveCircleReader", warned)
        gated = [k for k, _l, g, ok in ratchets.reader_classes() if g]
        self.assertEqual(gated, ["reticle/clove_circle.py::CloveCircleReader"])

    def test_clove_declares_a_spans_gate(self):
        from reticle.clove_circle import CloveCircleReader
        gate = ratchets.declared_gate(CloveCircleReader.__new__(CloveCircleReader))
        self.assertIsInstance(gate, Gate)
        self.assertEqual(gate.kind, "spans")

    def test_a_gate_names_its_kind_opportunity_and_source(self):
        with self.assertRaises(ValueError):
            Gate(opportunity="x", source="y", kind="grid")
        with self.assertRaises(ValueError):
            Gate(opportunity="", source="y")


class ScanWarningTests(unittest.TestCase):
    """`scan` prints one line per running legacy reader and never refuses."""

    def _reader(self, module, qualname, gate=None):
        cls = type(qualname, (), {"feed": lambda self, smp: None})
        cls.__module__, cls.__qualname__ = module, qualname
        if gate is not None:
            cls.opportunity_gate = gate
        r = cls()
        r.name, r.hz = qualname.lower(), 10.0
        return r

    def test_a_listed_reader_warns(self):
        lines = ratchets.legacy_running([self._reader("reticle.ping", "PingReader")])
        self.assertEqual(len(lines), 1)
        self.assertIn("10 Hz", lines[0])
        self.assertIn("BACKLOG 1", lines[0])

    def test_an_unlisted_or_gated_reader_is_silent(self):
        gate = Gate(opportunity="o", source="s")
        self.assertEqual(ratchets.legacy_running([
            self._reader("reticle.clove_circle", "CloveCircleReader"),
            self._reader("reticle.ping", "PingReader", gate=gate)]), [])

    def test_a_wrapped_reader_is_named_by_its_inner_class(self):
        from reticle.widget_frame import Normalised
        inner = self._reader("reticle.minimap", "AllyIconReader")
        self.assertEqual(ratchets.convert_key(Normalised(inner, None)),
                         "reticle/minimap.py::AllyIconReader")
        self.assertEqual(len(ratchets.legacy_running([Normalised(inner, None)])), 1)


SCOPE = {
    "reticle/lane.py": """
        def per_round(frames, rounds):
            out = []
            for rnd in rounds:
                a, z = rnd["t_start_ms"], rnd["t_end_ms"]
                inside = [f for f in frames if a <= f["t_ms"] < z]
                out.append(len(inside))
            return out

        def sliced(frames_by_round, rounds):
            out = []
            for rnd in rounds:
                inside = frames_by_round[rnd["round_no"]]
                kept = [f for f in inside if f["t_ms"] > 0]
                out.append(len(kept))
            return out

        def stalled(span_list, t_ms):
            import numpy as np
            starts = [s["t_start_ms"] for s in span_list]
            return int(np.searchsorted(starts, t_ms))

        class Reader:
            def __init__(self):
                self.rows, self._prev = [], None
            def feed(self, smp):
                n = sum(1 for r in self.rows if r["frame_idx"] == smp.frame_idx)
                self.rows.append({"frame_idx": smp.frame_idx, "n": n})
                self._prev = smp

        class Lane:
            def __init__(self, rows):
                self._rows = rows
            def events(self, round=None):
                return [r for r in self._rows if r["round"] == round]
    """,
}
KEYS = {
    "window": "reticle/lane.py::per_round::window_scan",
    "index": "reticle/lane.py::stalled::index_rebuilt",
    "accum": "reticle/lane.py::Reader.feed::accumulated_scan",
    "prior": "reticle/lane.py::Reader.feed::carried_prior",
    "query": "reticle/lane.py::Lane.events::session_query",
}


class RoundScopeTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo(SCOPE)

    def test_each_kind_is_found_and_the_slice_is_not(self):
        keys = {s.key for s in ratchets.roundscope_sites(self.root)}
        self.assertEqual(keys, set(KEYS.values()))

    def test_an_unlisted_site_errors(self):
        found = ratchets.roundscope_findings(self.root, legacy={}, bounded={}, unreviewed=())
        errors = [m for s, m in found if s == ERROR]
        self.assertEqual(len(errors), len(KEYS))

    def test_listed_sites_warn_and_bounded_ones_are_silent(self):
        legacy = {KEYS["window"]: {"audit": (3,), "cited": "lane.py:5", "reason": "slice"}}
        bounded = {KEYS["prior"]: "adjacent frames only"}
        unreviewed = (KEYS["index"], KEYS["accum"], KEYS["query"])
        found = ratchets.roundscope_findings(self.root, legacy=legacy, bounded=bounded,
                                             unreviewed=unreviewed)
        self.assertEqual([s for s, _m in found], [WARN, WARN])
        self.assertIn("audit #3", found[0][1])
        self.assertIn("3 unreviewed", found[1][1])

    def test_a_stale_entry_is_reported(self):
        legacy = {k: {"audit": (1,), "cited": "x", "reason": "y"} for k in KEYS.values()}
        legacy["reticle/lane.py::fixed::window_scan"] = {"audit": (2,), "cited": "x",
                                                        "reason": "y"}
        found = ratchets.roundscope_findings(self.root, legacy=legacy, bounded={},
                                             unreviewed=("reticle/lane.py::gone::index_rebuilt",))
        stale = [m for s, m in found if s == ERROR]
        self.assertEqual(len(stale), 2)
        self.assertTrue(all("remove it from the allowlist" in m for m in stale))

    def test_the_repository_has_no_unlisted_site(self):
        found = ratchets.roundscope_findings()
        self.assertEqual([m for s, m in found if s == ERROR], [])

    def test_every_audit_case_is_caught_once_unlisted(self):
        # The fifteen cases of the 2026-10-07 audit: each key, taken off the
        # list, is a new violation the detector names.
        legacy = ratchets.ROUNDSCOPE_LEGACY
        self.assertEqual({c for e in legacy.values() for c in e["audit"]}, set(range(1, 16)))
        found = ratchets.roundscope_findings(legacy={})
        errors = " ".join(m for s, m in found if s == ERROR)
        for key in legacy:
            self.assertIn(f"`{key}`", errors)

    def test_the_seed_counts_bound_the_lists(self):
        self.assertLessEqual(len(ratchets.ROUNDSCOPE_LEGACY), ratchets.SEEDED["ROUNDSCOPE"])
        self.assertLessEqual(len(ratchets.ROUNDSCOPE_UNREVIEWED),
                             ratchets.SEEDED["ROUNDSCOPE_UNREVIEWED"])
        self.assertLessEqual(len(ratchets.CONVERT_LEGACY), ratchets.SEEDED["CONVERT"])


STEMS = {"pilot_x", "other"}


def _passed(**kw):
    row = {"kind": "outcome", "wire": "yes", "subject": "prototypes/pilot_x.py",
           "id": "pilot-x-1", "wire_reason": "the reader should ship"}
    row.update(kw)
    return row


def _strict(rows, used=(), modules=(), items=(1,), legacy=None):
    return ratchets.promote_strict(rows, STEMS, set(used), set(modules), set(items),
                                   {} if legacy is None else legacy)


class PromoteStrictTests(unittest.TestCase):
    def test_a_passed_unwired_pilot_errors(self):
        found, unwired = _strict([_passed()])
        self.assertEqual([s for s, _m in found], [ERROR])
        self.assertIn("pilot_x", found[0][1])
        self.assertEqual(unwired, ["pilot_x"])

    def test_a_listed_pilot_warns(self):
        found, _ = _strict([_passed()], legacy={"pilot_x": "waits for the slot model"})
        self.assertEqual([s for s, _m in found], [WARN])

    def test_a_stale_entry_is_reported(self):
        found, _ = _strict([_passed()], used={"pilot_x"}, legacy={"pilot_x": "x"})
        self.assertEqual([s for s, _m in found], [ERROR])
        self.assertIn("remove it from the allowlist", found[0][1])

    def test_wired_by_mention_or_by_the_reason_naming_a_module(self):
        self.assertEqual(_strict([_passed()], used={"pilot_x"})[0], [])
        row = _passed(wire_reason="wired as reticle/adjudication/pilot.py (pilot-0.1.0)")
        self.assertEqual(_strict([row], modules={"adjudication.pilot"})[0], [])

    def test_scheduled_by_an_open_backlog_item(self):
        rows = [_passed(), {"kind": "decision", "subject": "prototypes/pilot_x.py",
                            "wired_by": "BACKLOG 1"}]
        found, unwired = _strict(rows)
        self.assertEqual(found, [])
        self.assertEqual(unwired, ["pilot_x (BACKLOG 1)"])

    def test_a_closed_item_does_not_schedule(self):
        rows = [_passed(), {"kind": "decision", "subject": "prototypes/pilot_x.py",
                            "wired_by": "BACKLOG 7"}]
        found, _ = _strict(rows, items=(1, 2))
        self.assertEqual([s for s, _m in found], [ERROR])
        self.assertIn("BACKLOG 7", found[0][1])

    def test_only_a_later_decline_with_a_subject_retires_a_pass(self):
        decline = {"kind": "decision", "wire": "no", "subject": "prototypes/pilot_x.py",
                   "wire_reason": "superseded"}
        self.assertEqual(_strict([_passed(), decline])[0], [])
        self.assertEqual(len(_strict([decline, _passed()])[0]), 1)
        prose = {"kind": "outcome", "wire": "no", "result": "pilot_x and other ran"}
        self.assertEqual(len(_strict([_passed(), prose])[0]), 1)

    def test_a_prediction_is_no_pass(self):
        self.assertEqual(_strict([_passed(kind="prediction")]), ([], []))

    def test_check_promote_carries_the_strict_finding(self):
        import json
        row = lambda s: {"kind": "outcome", "wire": "yes", "subject": f"prototypes/{s}.py"}
        stem = next(f.stem for f in sorted((doctor.ROOT / "prototypes").glob("*.py"))
                    if doctor.promote_state([row(f.stem)])[0])
        with tempfile.TemporaryDirectory() as d:
            notes = Path(d) / "notes"
            notes.mkdir()
            (notes / "predictions.jsonl").write_text(json.dumps(row(stem)) + "\n",
                                                     encoding="utf-8")
            found = doctor.check_promote(Path(d))
        mine = [(s, m) for s, m in found if f"prototypes/{stem}.py`" in m]
        self.assertEqual([s for s, _m in mine], [ERROR])


class StatusProgressTests(unittest.TestCase):
    def test_the_progress_line_counts_each_ratchet(self):
        from reticle.status import render
        p = ratchets.progress()
        data = {"sessions": [], "hud_version": "h", "minimap_version": "m", "ping_version": "p",
                "round_outcome_version": "r", "roster_version": "o", "stored": {},
                "ratchets": {"progress": p, "unwired": ["pilot_x (BACKLOG 1)"]}}
        out = render(data)
        self.assertIn(f"CONVERT {p['convert']['gated']} gated / "
                      f"{len(ratchets.CONVERT_LEGACY)} legacy readers", out)
        self.assertIn(f"ROUNDSCOPE {p['roundscope']['fixed']} fixed / "
                      f"{len(ratchets.ROUNDSCOPE_LEGACY)} legacy", out)
        self.assertIn("Passed pilots not wired: pilot_x (BACKLOG 1).", out)

    def test_no_pilot_reads_none(self):
        self.assertIn("Passed pilots not wired: none.",
                      ratchets.progress_line(ratchets.progress(), [])[-1])


if __name__ == "__main__":
    unittest.main()
