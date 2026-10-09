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
SEED = frozenset({"reticle/grid.py::GridReader"})


class ConvertTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo(READERS)

    def test_an_ungated_fixed_grid_reader_errors(self):
        found = ratchets.convert_findings(self.root, legacy={})
        self.assertEqual([s for s, m in found if "GridReader" in m], [ERROR])

    def test_a_listed_reader_warns_with_its_rate_and_item(self):
        found = ratchets.convert_findings(self.root, legacy={"reticle/grid.py::GridReader": LEGACY},
                                          seed=SEED)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0][0], WARN)
        self.assertIn("15 Hz", found[0][1])
        self.assertIn("BACKLOG 1", found[0][1])

    def test_a_gated_reader_and_a_protocol_pass(self):
        found = ratchets.convert_findings(self.root, legacy={"reticle/grid.py::GridReader": LEGACY},
                                          seed=SEED)
        self.assertFalse([m for _s, m in found if "GatedReader" in m or "proto.py" in m])

    def test_a_stale_entry_is_reported(self):
        legacy = {"reticle/grid.py::GridReader": LEGACY,
                  "reticle/gated.py::GatedReader": LEGACY,
                  "reticle/gone.py::GoneReader": LEGACY}
        found = ratchets.convert_findings(self.root, legacy=legacy, seed=frozenset(legacy))
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
        gated = [r.key for r in ratchets.reader_classes() if r.gated]
        self.assertEqual(gated, ["reticle/clove_circle.py::CloveCircleReader"])
        self.assertIn("reticle/trial.py::_AbilityGlyphPass",
                      {r.key for r in ratchets.reader_classes()})

    def test_a_listed_key_outside_the_seed_errors(self):
        legacy = {"reticle/grid.py::GridReader": LEGACY}
        found = ratchets.convert_findings(self.root, legacy=legacy, seed=frozenset())
        self.assertTrue(any(s == ERROR and "CONVERT_SEED" in m for s, m in found))


RATES = {
    "reticle/base.py": """
        class BaseReader:
            hz = 2.0
            def feed(self, smp):
                pass
        class Inherited(BaseReader):
            pass
        class Prop:
            @property
            def hz(self):
                return 5.0
            def feed(self, smp):
                pass
        class Outside:
            def feed(self, smp):
                pass
        class Driven:
            def feed(self, smp):
                pass
        class Wrapper:
            def __getattr__(self, k):
                return 1
            def feed(self, smp):
                pass
        class NotAReader:
            def feed(self, name, fn, sample):
                pass
        def build():
            r = Outside()
            r.hz = 4.0
            return r
    """,
}


class ReaderRateTests(unittest.TestCase):
    def test_every_rate_source_is_a_reader(self):
        got = {r.key.split("::")[1]: r.rate for r in ratchets.reader_classes(_repo(RATES))}
        self.assertEqual(got, {"BaseReader": "class", "Inherited": "inherited from BaseReader",
                               "Prop": "property", "Outside": "assigned outside the class",
                               "Driven": "its driver's grid"})

    def test_an_inherited_reader_needs_its_own_entry(self):
        found = ratchets.convert_findings(_repo(RATES), legacy={})
        self.assertEqual(sum(1 for s, _m in found if s == ERROR), 5)


FRAME = {
    "reticle/frame.py": """
        from .ratchets import Gate
        class FrameReader:
            opportunity_gate = Gate(opportunity="o", source="s", kind="frame")
            hz = 15.0
            def wants(self, t_ms):
                return True
            def feed(self, smp):
                pass
        class NoWants:
            opportunity_gate = Gate("o", "s", "frame")
            hz = 15.0
            def feed(self, smp):
                pass
    """,
}


class FrameGateTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo(FRAME)

    def test_a_frame_gate_converts_nothing_before_the_hook(self):
        self.assertFalse(ratchets.FRAME_HOOK)
        found = ratchets.convert_findings(self.root, legacy={})
        frame = [s for s, m in found if "FrameReader" in m]
        self.assertEqual(frame, [ERROR])

    def test_a_listed_frame_gated_reader_stays_a_warning(self):
        found = ratchets.convert_findings(
            self.root, legacy={"reticle/frame.py::FrameReader": LEGACY},
            seed=frozenset({"reticle/frame.py::FrameReader"}))
        self.assertEqual([s for s, m in found if "FrameReader" in m], [WARN])

    def test_a_frame_gate_needs_wants(self):
        found = ratchets.convert_findings(self.root, legacy={})
        self.assertTrue(any(s == ERROR and "NoWants" in m and "wants" in m for s, m in found))

    def test_scan_still_warns_for_a_frame_gate(self):
        cls = type("PingReader", (), {"feed": lambda self, smp: None})
        cls.__module__ = "reticle.ping"
        cls.opportunity_gate = Gate("o", "s", "frame")
        self.assertEqual(len(ratchets.legacy_running([cls()])), 1)

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

        def by_round_number(rows, rounds):
            return [len([r for r in rows if r["round"] == rnd["round_no"]]) for rnd in rounds]

        def by_round_loop(rows, rounds):
            out = []
            for rnd in rounds:
                out.append([r for r in rows if r["round"] == rnd["round_no"]])
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

        def vectorised(span_list, times):
            import numpy as np
            starts = np.sort(np.asarray([s["t_start_ms"] for s in span_list]))
            return np.searchsorted(starts, np.asarray(times))

        def lookups(targets_ms, cache):
            return [t for t in targets_ms if cache.refusal(t) is None]

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
    "equality": "reticle/lane.py::by_round_loop::window_scan",
    "index": "reticle/lane.py::stalled::index_rebuilt",
    "accum": "reticle/lane.py::Reader.feed::accumulated_scan",
    "prior": "reticle/lane.py::Reader.feed::carried_prior",
    "query": "reticle/lane.py::Lane.events::session_query",
    "query_eq": "reticle/lane.py::Lane.events::window_scan",
}


def _seed(legacy=(), bounded=(), unreviewed=(), count=1):
    out = {k: ("LEGACY", count) for k in legacy}
    out.update({k: ("BOUNDED", count) for k in bounded})
    out.update({k: ("UNREVIEWED", count) for k in unreviewed})
    return out


class RoundScopeTests(unittest.TestCase):
    def setUp(self):
        self.root = _repo(SCOPE)

    def test_each_kind_is_found_and_the_cures_are_not(self):
        keys = {s.key for s in ratchets.roundscope_sites(self.root)}
        # The comprehension's own generator over `rounds` is the outer loop
        # of `by_round_number`: its filter's `rnd` is bound by the same
        # comprehension, so only the statement loop is a scan per round.
        self.assertEqual(keys, set(KEYS.values()))
        for cure in ("sliced", "vectorised", "lookups"):
            self.assertFalse([k for k in keys if f"::{cure}::" in k])

    def test_an_unlisted_site_errors(self):
        found = ratchets.roundscope_findings(self.root, legacy={}, bounded={}, unreviewed=(),
                                             seed={})
        self.assertEqual(len([m for s, m in found if s == ERROR]), len(KEYS))

    def test_listed_sites_warn_and_bounded_ones_are_silent(self):
        legacy = {KEYS["window"]: {"audit": (3,), "cited": "lane.py:5", "reason": "slice"}}
        bounded = {KEYS["prior"]: "adjacent frames only"}
        unreviewed = tuple(v for k, v in KEYS.items() if k not in ("window", "prior"))
        found = ratchets.roundscope_findings(self.root, legacy=legacy, bounded=bounded,
                                             unreviewed=unreviewed,
                                             seed=_seed(legacy, bounded, unreviewed))
        self.assertEqual([s for s, _m in found], [WARN, WARN])
        self.assertIn("audit #3", found[0][1])
        self.assertIn("5 unreviewed", found[1][1])

    def test_a_stale_entry_is_reported(self):
        legacy = {k: {"audit": (1,), "cited": "x", "reason": "y"} for k in KEYS.values()}
        legacy["reticle/lane.py::fixed::window_scan"] = {"audit": (2,), "cited": "x",
                                                        "reason": "y"}
        gone = ("reticle/lane.py::gone::index_rebuilt",)
        found = ratchets.roundscope_findings(self.root, legacy=legacy, bounded={},
                                             unreviewed=gone, seed=_seed(legacy, (), gone))
        stale = [m for s, m in found if s == ERROR]
        self.assertEqual(len(stale), 2)
        self.assertTrue(all("remove it from the allowlist" in m for m in stale))

    def test_a_list_cannot_grow_past_its_seed(self):
        legacy = {KEYS["window"]: {"audit": (3,), "cited": "x", "reason": "y"}}
        rest = tuple(v for k, v in KEYS.items() if k != "window")
        # Not in the seed: the list grew.
        found = ratchets.roundscope_findings(self.root, legacy=legacy, unreviewed=rest,
                                             bounded={}, seed=_seed((), (), rest))
        self.assertTrue(any(s == ERROR and "outside the frozen" in m for s, m in found))
        # Bounded is held to the seed as well.
        found = ratchets.roundscope_findings(self.root, legacy=legacy, bounded={rest[0]: "x"},
                                             unreviewed=rest[1:],
                                             seed=_seed(legacy, (), rest[1:]))
        self.assertTrue(any(s == ERROR and "outside the frozen" in m for s, m in found))
        # A key moved from LEGACY to UNREVIEWED trades entries: an error.
        found = ratchets.roundscope_findings(self.root, legacy={}, bounded={},
                                             unreviewed=tuple(KEYS.values()),
                                             seed=_seed(legacy, (), rest))
        self.assertTrue(any(s == ERROR and "the seed put in ROUNDSCOPE_LEGACY" in m
                            for s, m in found))

    def test_a_new_site_inside_a_listed_function_errors(self):
        root = _repo({"reticle/lane.py": SCOPE["reticle/lane.py"].replace(
            "                out.append(len(inside))",
            "                late = [f for f in frames if f[\"t_ms\"] > z]\n"
            "                out.append(len(inside) + len(late))")})
        keys = tuple(KEYS.values())
        found = ratchets.roundscope_findings(root, legacy={}, bounded={}, unreviewed=keys,
                                             seed=_seed((), (), keys))
        self.assertTrue(any(s == ERROR and "a new site inside a listed function" in m
                            for s, m in found))
        # And a fixed one asks the seed's count down.
        found = ratchets.roundscope_findings(self.root, legacy={}, bounded={}, unreviewed=keys,
                                             seed=_seed((), (), keys, count=2))
        self.assertTrue(any(s == ERROR and "lower ROUNDSCOPE_SEED" in m for s, m in found))

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

    def test_the_seed_holds_every_list(self):
        seed = ratchets.ROUNDSCOPE_SEED
        for name, keys in (("LEGACY", ratchets.ROUNDSCOPE_LEGACY),
                           ("BOUNDED", ratchets.ROUNDSCOPE_BOUNDED),
                           ("UNREVIEWED", ratchets.ROUNDSCOPE_UNREVIEWED)):
            for k in keys:
                self.assertIn(k, seed)
        self.assertLessEqual(set(ratchets.CONVERT_LEGACY), ratchets.CONVERT_SEED)
        self.assertLessEqual(set(ratchets.PROMOTE_LEGACY), ratchets.PROMOTE_SEED)


def _row(witness="w", streams=("ability_x",), owners=("cast-owner",), feeds=("ability-child",),
         **kw):
    row = {"witness": witness, "parent": "the self slot", "wired": True, "owners": owners, "readers": (),
           "streams": streams, "feeds": feeds, "opens": "any", "joins": True, "ends": None,
           "kind": "the slot", "agent_claim": None, "position": None, "effect": None}
    row.update(kw)
    return row


def _entries(**extra):
    out = {"ability-child": {"owner": "slot_state", "entity_kind": "ability"},
           "cast-owner": {"owner": "m", "entity_kind": "ability", "feeds": ["ability-child"]},
           "ability-old": {"owner": "m", "entity_kind": "ability"},
           "death-victim": {"owner": "adjudication.death"}}
    out.update(extra)
    return out


def _inputs(channels=None, streams=("ability_x", "ability_old", "death"), lanes=None,
            entries=None):
    return ratchets.AbilityInputs(
        channels=tuple(channels if channels is not None else (_row(),)),
        lanes_declared=frozenset({"ability", "ability_tray"}), child_owner="slot_state",
        child_entries=("ability-child",), streams=frozenset(streams), retired=frozenset(),
        lanes=lanes if lanes is not None else {"death": ("death",), "smoke": ("death",),
                                               "ability_tray": ("ability_x",)},
        entries=entries if entries is not None else _entries())


ALEGACY = {"stream:ability_old": {"fate": "retires", "step": "step 3"},
           "entry:ability-old": {"fate": "retires", "step": "step 3"},
           "lane:smoke": {"fate": "folds into the ability lane", "step": "step 3"}}
ASEED = frozenset(ALEGACY)


def _ability(inputs=None, legacy=None, seed=ASEED, base=None):
    return ratchets.ability_findings(inputs or _inputs(),
                                     legacy=ALEGACY if legacy is None else legacy,
                                     seed=seed, apart={}, base=base)


class AbilityTests(unittest.TestCase):
    """ABILITY (docs/ABILITY_ENTITIES.md step 1): every ability stream, lane
    and entry is a CHANNELS input or the child owner's, else listed."""

    def test_listed_fragments_warn_once_each(self):
        found = _ability()
        self.assertEqual([s for s, _m in found], [WARN] * 3)
        self.assertTrue(all("clears in step 3" in m for _s, m in found))

    def test_an_undeclared_ability_stream_errors(self):
        found = _ability(_inputs(streams=("ability_x", "ability_old", "ability_new", "death")))
        self.assertEqual([s for s, m in found if "ability_new" in m], [ERROR])

    def test_an_undeclared_ability_entry_and_lane_error(self):
        entries = _entries(**{"ability-new": {"owner": "m", "entity_kind": "ability"}})
        lanes = {"ult_cast": ("ult_cast",), "smoke": ("death",)}
        found = _ability(_inputs(entries=entries, lanes=lanes))
        self.assertEqual([s for s, m in found if "ability-new" in m], [ERROR])
        self.assertEqual([s for s, m in found if "`ult_cast`" in m], [ERROR])

    def test_an_untagged_ability_entry_errors(self):
        found = _ability(_inputs(entries=_entries(**{"smoke-thing": {"owner": "m"}})))
        self.assertEqual([s for s, m in found if "smoke-thing" in m], [ERROR])

    def test_a_stale_entry_errors(self):
        # the fragment is gone: the registry no longer declares the stream
        found = _ability(_inputs(streams=("ability_x", "death")))
        self.assertEqual([s for s, m in found if "stream:ability_old" in m], [ERROR])
        # the fragment became a declared input
        rows = (_row(), _row("w2", streams=("ability_old",)))
        found = _ability(_inputs(channels=rows))
        self.assertEqual([s for s, m in found if "stream:ability_old" in m], [ERROR])

    def test_a_key_outside_the_seed_errors(self):
        legacy = {**ALEGACY, "stream:ability_new": {"fate": "x", "step": "step 2"}}
        inputs = _inputs(streams=("ability_x", "ability_old", "ability_new", "death"))
        found = _ability(inputs, legacy=legacy)
        self.assertIn((ERROR, "ABILITY_LEGACY names `stream:ability_new`, outside the frozen "
                              "ABILITY_SEED -- the allowlist only shrinks"), found)

    def test_a_legacy_entry_names_its_step(self):
        legacy = {**ALEGACY, "lane:smoke": {"fate": "folds", "step": "later"}}
        found = _ability(legacy=legacy)
        self.assertEqual([s for s, m in found if "no step 2-7" in m], [ERROR])

    def test_the_declaration_is_checked(self):
        found = _ability(_inputs(channels=(_row(streams=("ability_x", "ability_gone")),)))
        self.assertEqual([s for s, m in found if "ability_gone" in m], [ERROR])
        entries = _entries(**{"cast-owner": {"owner": "m", "entity_kind": "ability"}})
        found = _ability(_inputs(entries=entries))
        self.assertEqual([s for s, m in found if "declares feeds" in m], [ERROR])
        entries = _entries(**{"cast-owner": {"owner": "m", "feeds": ["ability-child"]}})
        found = _ability(_inputs(entries=entries))
        self.assertTrue(any(s == ERROR and "does not declare entity_kind" in m
                            for s, m in found))

    def test_feeds_without_a_channels_row_errors(self):
        entries = _entries(**{"other": {"owner": "m", "feeds": ["ability-child"]}})
        found = _ability(_inputs(entries=entries))
        self.assertEqual([s for s, m in found if "[other]" in m], [ERROR])

    def test_a_code_fragment_is_stale_once_its_definition_goes(self):
        root = _repo({"reticle/mod.py": "def binder():\n    pass\n"})
        legacy = {**ALEGACY, "code:reticle/mod.py::binder": {"fate": "moves", "step": "step 2"},
                  "code:reticle/mod.py::gone": {"fate": "moves", "step": "step 2"}}
        seed = ASEED | {"code:reticle/mod.py::binder", "code:reticle/mod.py::gone"}
        found = _ability(legacy=legacy, seed=seed, base=root)
        self.assertEqual([s for s, m in found if "binder" in m], [WARN])
        self.assertEqual([s for s, m in found if "::gone" in m], [ERROR])

    def test_an_apart_key_outside_its_seed_errors(self):
        entries = _entries(**{"ability-new": {"owner": "m", "entity_kind": "ability"}})
        found = ratchets.ability_findings(
            _inputs(entries=entries), legacy=ALEGACY, seed=ASEED,
            apart={"ability-new": "a tool"}, apart_seed=frozenset())
        self.assertEqual([s for s, m in found if "ability-new" in m], [ERROR])
        self.assertTrue(any("outside the frozen ABILITY_APART_SEED" in m for _s, m in found))
        found = ratchets.ability_findings(
            _inputs(entries=entries), legacy=ALEGACY, seed=ASEED,
            apart={"ability-new": "a tool"}, apart_seed=frozenset({"ability-new"}))
        self.assertEqual([s for s, m in found if "ability-new" in m], [])
        self.assertEqual(set(ratchets.ABILITY_APART), ratchets.ABILITY_APART_SEED)

    def test_the_tree_has_no_ability_error(self):
        found = doctor.check_ability()
        self.assertEqual([m for s, m in found if s == ERROR], [])
        self.assertEqual(sum(s == WARN for s, _m in found), len(ratchets.ABILITY_LEGACY))
        self.assertLessEqual(set(ratchets.ABILITY_LEGACY), ratchets.ABILITY_SEED)

    def test_the_progress_line_counts_by_step(self):
        line = ratchets.ability_progress_line(ratchets.ability_progress(ALEGACY, ASEED))
        self.assertIn("ABILITY 0 cleared / 3 legacy fragments (step 3: 3)", line)


STEMS = {"pilot_x", "other"}


def _passed(**kw):
    row = {"kind": "outcome", "wire": "yes", "subject": "prototypes/pilot_x.py",
           "id": "pilot-x-1", "wire_reason": "the reader should ship"}
    row.update(kw)
    return row


def _strict(rows, used=(), modules=(), items=(1,), legacy=None):
    legacy = {} if legacy is None else legacy
    return ratchets.promote_strict(rows, STEMS, set(used), set(modules), set(items),
                                   legacy, frozenset(legacy))


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

    def test_wired_by_a_module_path(self):
        row = {"kind": "promotion", "prototype": "prototypes/pilot_x.py", "also": ["other"],
               "wire": "yes", "wired_by": "reticle/slot_state.py (`reticle slot-state`)"}
        self.assertEqual(_strict([row], modules={"slot_state"}), ([], []))
        found, unwired = _strict([row])
        self.assertEqual([s for s, _m in found], [WARN, WARN])
        self.assertTrue(all("not in this tree" in u for u in unwired))

    def test_prose_neither_names_nor_schedules(self):
        rows = [_passed(), {"kind": "decision", "note": "pilot_x waits",
                            "wired_by": "BACKLOG 1"}]
        self.assertEqual([s for s, _m in _strict(rows)[0]], [ERROR])
        self.assertEqual(_strict([{"kind": "outcome", "wire": "yes",
                                   "result": "pilot_x passed"}]), ([], []))

    def test_a_listed_pilot_outside_the_seed_errors(self):
        found, _ = ratchets.promote_strict([_passed()], STEMS, set(), set(), {1},
                                           {"pilot_x": "x"}, frozenset())
        self.assertTrue(any(s == ERROR and "PROMOTE_SEED" in m for s, m in found))

    def test_a_comment_is_no_use(self):
        text = '"""Ports prototypes/pilot_x.py."""\n# pilot_x lives on\nx = 1\n'
        self.assertEqual(doctor.prototype_uses(text, STEMS), set())
        self.assertEqual(doctor.prototype_uses("from .pilot_x import f\n", STEMS), {"pilot_x"})
        self.assertEqual(doctor.prototype_uses("import other\nother.run()\n", STEMS), {"other"})
        self.assertEqual(doctor.prototype_uses(
            'subprocess.run(["python", "prototypes/pilot_x.py"])\n', STEMS), {"pilot_x"})

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
