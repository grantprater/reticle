"""Ratchets: allowlists of legacy code that only shrink (BACKLOG item 1).

    .\\.venv\\Scripts\\python.exe -m reticle doctor      # CONVERT, ROUNDSCOPE, PROMOTE
    .\\.venv\\Scripts\\python.exe -m reticle status      # conversion progress at pickup

The player chose, 2026-10-07, to convert the pipeline in place rather than
restart it: every reader moves to opportunity gating, and every reader,
tracker and lane holds round-scoped state. This module states both rules as
code that `doctor` checks, and lists the code that breaks them today. A list
entry is a debt with a name: `doctor` warns on it, errors on a new violation
that no entry covers, and errors on an entry whose violation is gone, so a
list can only shrink.

Three ratchets live here:

- CONVERT (`convert_findings`): a reader samples a fixed grid unless it
  declares a `Gate` as its class attribute `opportunity_gate`.
- ROUNDSCOPE (`roundscope_findings`): state that outlives a round, or a search
  beyond the could-overlap set, found by AST heuristics (`roundscope_sites`).
- PROMOTE strict (`promote_strict`): a pilot whose ledger row records a pass
  meant for production is wired into `reticle/` or names the backlog item
  that wires it.

The module reads source text and ledger rows only; it imports nothing from
`reticle/` above the foundation, so a reader may import `Gate` from it.
"""
from __future__ import annotations

import ast
import re
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ERROR, WARN = "ERROR", "WARN"


# ---------------------------------------------------------------------------
# CONVERT: the declared gate
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Gate:
    """A reader's declared opportunity gate: what opens a read, and where the
    gate's belief comes from.

    A reader declares one as its CLASS attribute `opportunity_gate`, so
    `doctor` can see it without running anything. `kind` says who applies it:

    - `"spans"`: the reader's `spans` are the opportunity windows, built from
      stored evidence before the pass (`clove_circle.stored_windows` builds
      Clove's). `decode.sample_multi` and `passes.cache_feed` already honour
      spans, so the gate needs no hook.
    - `"frame"`: the reader's `wants(t_ms) -> bool` decides per sample, from
      the gate's belief (`source`). The per-frame gate hook in `passes.run`
      and `passes.run_cached` (BACKLOG item 1, second step) consumes it; until
      that hook exists a `"frame"` gate is declared, not applied.

    `opportunity` names the event that opens a read ("an ally Clove's death
    window"); `source` names the stored stream or function the gate reads.
    """

    opportunity: str
    source: str
    kind: str = "spans"

    def __post_init__(self):
        if self.kind not in ("spans", "frame"):
            raise ValueError(f"a gate's kind is 'spans' or 'frame', not {self.kind!r}")
        if not self.opportunity or not self.source:
            raise ValueError("a gate names its opportunity and its source")


def declared_gate(reader) -> Gate | None:
    """The `Gate` a reader declares, through any wrapper; None where it
    declares none (a fixed-grid reader)."""
    inner = _unwrap(reader)
    got = getattr(type(inner), "opportunity_gate", None)
    return got if isinstance(got, Gate) else None


def _unwrap(reader):
    # `widget_frame.Normalised` holds its reader in `_inner`.
    seen = 0
    while seen < 4:
        try:
            inner = object.__getattribute__(reader, "_inner")
        except AttributeError:
            return reader
        reader, seen = inner, seen + 1
    return reader


def convert_key(reader) -> str:
    """`reticle/<module path>.py::<Class>` for a running reader, the key the
    CONVERT allowlist uses."""
    cls = type(_unwrap(reader))
    return f"{cls.__module__.replace('.', '/')}.py::{cls.__qualname__}"


#: Every reader that samples a fixed grid on 2026-10-09, found by
#: `reader_classes` and listed with its rate and the item that converts it.
#: Remove an entry in the commit that gives its reader an `opportunity_gate`;
#: `doctor` errors on an entry whose reader is gated or gone.
CONVERT_LEGACY: dict[str, dict[str, str]] = {
    "reticle/cli.py::_MinimapPass": {
        "rate": "15 Hz (`--minimap-hz`) over the in-match spans",
        "converts": "BACKLOG 1: the slot model's gate, after the ally pass"},
    "reticle/minimap.py::AllyIconReader": {
        "rate": "15 Hz (`ALLY_DESCRIPTOR_HZ`, `--ally-hz`) over the in-match spans",
        "converts": "BACKLOG 1: the ally pass, first"},
    "reticle/ping.py::PingReader": {
        "rate": "10 Hz (`--ping-hz`) over the in-match spans",
        "converts": "BACKLOG 1: after the ally pass"},
    "reticle/minimap_dark.py::DarkRegionReader": {
        "rate": "4 Hz (`--dark-hz`) over the in-match spans",
        "converts": "BACKLOG 1: with the ability readers"},
    "reticle/ability_scan.py::AbilityShapeReader": {
        "rate": "2 Hz (`ABILITY_HZ`) over live samples of the in-match spans",
        "converts": "BACKLOG 1: the ability readers, under their opportunity and audio gates"},
    "reticle/ability_icons.py::AbilityIconReader": {
        "rate": "2 Hz over live samples of the in-match spans",
        "converts": "BACKLOG 1: the ability readers, under their opportunity and audio gates"},
    "reticle/minimap_glyph.py::AbilityGlyphReader": {
        "rate": "2 Hz over live samples of the in-match spans",
        "converts": "BACKLOG 1: the ability readers, under their opportunity and audio gates"},
    "reticle/hud_reader.py::HudReader": {
        "rate": "2 Hz (`--hz`) over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/killfeed.py::KillfeedPortraitReader": {
        "rate": "2 Hz (`--hz`) over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/roster.py::RosterReader": {
        "rate": "2 Hz (`--hz`) over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/scoreboard.py::ScoreboardReader": {
        "rate": "2 Hz (`--hz`) over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/combat_report.py::CombatReportReader": {
        "rate": "1 Hz (`--report-hz`) over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/lineup.py::LineupReader": {
        "rate": "0.1 Hz over the whole capture",
        "converts": "BACKLOG 1: every reader; the HUD readers after the minimap ones"},
    "reticle/roi_cache.py::RoiCacheWriter": {
        "rate": "the cache's rate (`--cache-hz`, else `--hz`); gated per instance only "
                "for the scoreboard, killfeed panel and combat report sets",
        "converts": "BACKLOG 1: the crop cache follows its readers' gates"},
}


@dataclass(frozen=True)
class Site:
    """One finding's place in the code: `key` is what an allowlist names."""

    key: str
    line: int
    detail: str = ""


def _py_files(base: Path):
    for p in sorted((base / "reticle").rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        yield p


def _rel(p: Path, base: Path) -> str:
    return p.relative_to(base).as_posix()


def _parse_source(p: Path) -> ast.Module | None:
    try:
        return ast.parse(p.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None


def _bound_names(target) -> set[str]:
    """Plain names and `self.<attr>` names an assignment target binds."""
    out = set()
    for e in ast.walk(target):
        if isinstance(e, ast.Name):
            out.add(e.id)
        elif isinstance(e, ast.Attribute) and isinstance(e.value, ast.Name):
            out.add(f"{e.value.id}.{e.attr}")
    return out


def reader_classes(base: Path | None = None) -> list[tuple[str, int, bool, bool]]:
    """`(key, line, gated, gate_ok)` for every reader class in `reticle/`.

    A reader is what `passes.run` drives: a class with a `feed` method that
    binds `hz` (a class attribute or `self.hz`), the rate `decode.sample_multi`
    samples at. A `typing.Protocol` is a description, not a reader. `gated` is
    a class-level `opportunity_gate` binding; `gate_ok` says it is a `Gate(...)`
    call.
    """
    base = ROOT if base is None else base
    out = []
    for p in _py_files(base):
        tree = _parse_source(p)
        if tree is None:
            continue
        for c in ast.walk(tree):
            if not isinstance(c, ast.ClassDef):
                continue
            if any((isinstance(b, ast.Name) and b.id == "Protocol")
                   or (isinstance(b, ast.Attribute) and b.attr == "Protocol") for b in c.bases):
                continue
            if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "feed"
                       for n in c.body):
                continue
            binds_hz = False
            for n in ast.walk(c):
                tg = (n.targets if isinstance(n, ast.Assign)
                      else [n.target] if isinstance(n, ast.AnnAssign) else [])
                for t in tg:
                    names = _bound_names(t)
                    if "hz" in names or "self.hz" in names:
                        binds_hz = True
            if not binds_hz:
                continue
            gated, ok = False, False
            for n in c.body:
                tg = (n.targets if isinstance(n, ast.Assign)
                      else [n.target] if isinstance(n, ast.AnnAssign) else [])
                if any(isinstance(t, ast.Name) and t.id == "opportunity_gate" for t in tg):
                    gated = True
                    v = n.value
                    ok = (isinstance(v, ast.Call)
                          and ((isinstance(v.func, ast.Name) and v.func.id == "Gate")
                               or (isinstance(v.func, ast.Attribute) and v.func.attr == "Gate")))
            out.append((f"{_rel(p, base)}::{c.name}", c.lineno, gated, ok))
    return out


def convert_findings(base: Path | None = None,
                     legacy: dict | None = None) -> list[tuple[str, str]]:
    """CONVERT: a reader samples a fixed grid unless it declares a gate.

    A reader that declares no `opportunity_gate` and has no `CONVERT_LEGACY`
    entry is an ERROR: a new fixed-grid reader. A listed one is a WARN naming
    its rate and the item that converts it. A listed reader that now declares a
    gate, or no longer exists, is an ERROR until its entry goes: the list only
    shrinks. Clove's circle (`clove_circle.CloveCircleReader`) declares a
    `"spans"` gate, its death windows, and passes.
    """
    legacy = CONVERT_LEGACY if legacy is None else legacy
    found = reader_classes(base)
    keys = {k for k, *_ in found}
    out = []
    for key, line, gated, ok in found:
        where = f"`{key}` (line {line})"
        if gated and not ok:
            out.append((ERROR, f"{where} binds `opportunity_gate` to something other than "
                               "a `ratchets.Gate(...)`"))
        if gated and key in legacy:
            out.append((ERROR, f"{where} declares a gate and still has a CONVERT_LEGACY "
                               "entry -- remove it from the allowlist"))
        elif not gated and key in legacy:
            e = legacy[key]
            out.append((WARN, f"legacy fixed-grid reader {where}: {e['rate']}; "
                              f"converts in {e['converts']}"))
        elif not gated:
            out.append((ERROR, f"{where} samples a fixed grid and declares no "
                               "`opportunity_gate` -- declare a `ratchets.Gate`, never "
                               "a new CONVERT_LEGACY entry"))
    for key in sorted(set(legacy) - keys):
        out.append((ERROR, f"CONVERT_LEGACY names `{key}`, which is no reader any more -- "
                           "remove it from the allowlist"))
    return out


def legacy_running(readers, legacy: dict | None = None) -> list[str]:
    """One warning line per running reader that `CONVERT_LEGACY` lists: what
    `scan` prints before its pass. A warning, never a refusal."""
    legacy = CONVERT_LEGACY if legacy is None else legacy
    out = []
    for r in readers:
        key = convert_key(r)
        if key in legacy and declared_gate(r) is None:
            out.append(f"legacy     {getattr(r, 'name', key)} samples a fixed grid "
                       f"({legacy[key]['rate']}); converts in {legacy[key]['converts']}")
    return out


# ---------------------------------------------------------------------------
# ROUNDSCOPE: state that outlives a round, searches past the could-overlap set
# ---------------------------------------------------------------------------

ORDERING = (ast.Lt, ast.LtE, ast.Gt, ast.GtE)
INDEX_CALLS = frozenset({"searchsorted", "bisect", "bisect_left", "bisect_right",
                         "insort", "insort_left", "insort_right"})
UNWRAP_CALLS = frozenset({"values", "items", "keys", "enumerate", "reversed", "sorted",
                          "list", "tuple", "iter"})


def _iter_base(it) -> str | None:
    """The collection a loop or comprehension walks: a name or `self.<attr>`,
    through `.values()`, `enumerate()` and their kin; None for anything else."""
    while True:
        if isinstance(it, ast.Call):
            f = it.func
            if isinstance(f, ast.Attribute) and f.attr in UNWRAP_CALLS and not it.args:
                it = f.value
                continue
            if isinstance(f, ast.Name) and f.id in UNWRAP_CALLS and it.args:
                it = it.args[0]
                continue
            return None
        if isinstance(it, ast.Name):
            return it.id
        if isinstance(it, ast.Attribute) and isinstance(it.value, ast.Name) \
                and it.value.id == "self":
            return f"self.{it.attr}"
        return None


def _names(node) -> set[str]:
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _constant(name: str) -> bool:
    return name.isupper() or name in {"True", "False", "None"}


def _filters(node) -> list:
    """The tests a scan applies to each element: a comprehension's `if`
    clauses, and its element where it feeds `any`/`all`/`next`/`sum`; a `for`
    statement's top-level `if` tests."""
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        tests = [c for g in node.generators for c in g.ifs]
        if isinstance(node, ast.GeneratorExp):
            tests.append(node.elt)
        return tests
    return [s.test for s in node.body if isinstance(s, ast.If)]


def _element_vars(node) -> set[str]:
    if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
        return set().union(*(_names(g.target) for g in node.generators))
    return _names(node.target)


TIME_KEY = re.compile(r"(^|_)(t|t0|t1|ms|start|end|close|seen|time|round|frame_idx)(_|$)")
TIME_NAME = re.compile(r"^(t|t0|t1|t_\w+|\w+_ms|\w+_t)$")


def _timelike(node) -> bool:
    """Does `node` read a time or round: a `["t_ms"]`-like key, or a name
    such as `t`, `t0` or `last_seen_ms`?"""
    for n in ast.walk(node):
        if isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Constant) \
                and isinstance(n.slice.value, str) and TIME_KEY.search(n.slice.value):
            return True
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "get" and n.args and isinstance(n.args[0], ast.Constant) \
                and isinstance(n.args[0].value, str) and TIME_KEY.search(n.args[0].value):
            return True
        if isinstance(n, ast.Name) and TIME_NAME.match(n.id):
            return True
    return False


def _window_test(test, elem: set[str], varying: set[str]) -> bool:
    """Does `test` keep an element by its time or round against a value that
    varies per call or per outer iteration -- an ordering comparison, or a
    call that takes both, as `in_window(line, r["t_ms"], win)` does?"""
    for n in ast.walk(test):
        if isinstance(n, ast.Compare) and any(isinstance(o, ORDERING) for o in n.ops):
            used = _names(n)
            if used & elem and (used - elem) & varying and _timelike(n):
                return True
        if isinstance(n, ast.Call) and n.args:
            used = set().union(*(_names(a) for a in n.args))
            if used & elem and (used - elem) & varying and _timelike(n):
                return True
    return False


class _FunctionScan:
    """Window scans inside one function, with the loops that enclose them."""

    def __init__(self, fn, qual: str, rel: str, grown: set[str], per_sample: bool = False):
        self.fn, self.qual, self.rel, self.grown = fn, qual, rel, grown
        self.per_sample = per_sample
        a = fn.args
        self.params = {x.arg for x in a.args + a.kwonlyargs + a.posonlyargs} - {"self", "cls"}
        if a.vararg:
            self.params.add(a.vararg.arg)
        if a.kwarg:
            self.params.add(a.kwarg.arg)
        self.locals = set()
        for n in self._own_nodes(fn):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    self.locals |= {x for x in _bound_names(t) if "." not in x}
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                self.locals |= _names(n.target)
        self.sites: list[Site] = []

    @staticmethod
    def _own_nodes(fn):
        """The function's nodes, not descending into nested functions or
        classes, which are scanned as their own functions."""
        stack = list(fn.body)
        while stack:
            n = stack.pop()
            yield n
            for c in ast.iter_child_nodes(n):
                if isinstance(c, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef,
                                  ast.Lambda)):
                    continue
                stack.append(c)

    def run(self) -> list[Site]:
        self._visit(self.fn.body, loops=[], comp_elems=set())
        return self.sites

    def _visit(self, stmts, loops, comp_elems):
        for s in stmts:
            self._stmt(s, loops, comp_elems)

    def _loop_bound(self, loop) -> set[str]:
        out = _names(loop.target)
        for n in self._own_nodes(loop):
            if isinstance(n, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    out |= {x for x in _bound_names(t) if "." not in x}
            elif isinstance(n, (ast.For, ast.AsyncFor)):
                out |= _names(n.target)
        return out

    def _stmt(self, s, loops, comp_elems):
        if isinstance(s, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            return
        if isinstance(s, (ast.For, ast.AsyncFor)):
            self._scan(s, loops, comp_elems)
            for e in ast.walk(s.iter):
                if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                    self._scan(e, loops, comp_elems)
            inner = loops + [(s, self._loop_bound(s))]
            self._visit(s.body, inner, comp_elems)
            self._visit(s.orelse, loops, comp_elems)
            return
        for field, value in ast.iter_fields(s):
            if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                self._visit(value, loops, comp_elems)
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, ast.AST):
                        self._exprs(v, loops)
                    if isinstance(v, ast.ExceptHandler):
                        self._visit(v.body, loops, comp_elems)
                    if isinstance(v, ast.match_case):
                        self._visit(v.body, loops, comp_elems)
            elif isinstance(value, ast.AST) and not isinstance(value, ast.stmt):
                self._exprs(value, loops)

    def _exprs(self, node, loops):
        for e in ast.walk(node):
            if isinstance(e, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
                self._scan(e, loops, set())

    def _scan(self, node, loops, _comp_elems):
        """Flag a scan of a collection held outside the innermost loop,
        filtered against a value that loop or the call varies."""
        it = node.iter if isinstance(node, (ast.For, ast.AsyncFor)) else node.generators[0].iter
        base = _iter_base(it)
        if base is None:
            return
        elem = _element_vars(node)
        inner_bound = loops[-1][1] if loops else set()
        if base in inner_bound:
            return          # a per-iteration slice: the narrowed set
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp)):
            # a comprehension over an outer comprehension's element
            outer = set()
            for g in node.generators[1:]:
                outer |= _names(g.target)
            if base in outer:
                return
        varying = set().union(*(b for _l, b in loops)) if loops else set()
        varying |= self.params | self.locals
        varying = {v for v in varying if not _constant(v)} - elem - {base}
        if any(_window_test(t, elem, varying) for t in _filters(node)):
            ctx = ("loop" if loops else "per_sample" if self.per_sample
                   else "param" if base in self.params or base.startswith("self.") else None)
            if ctx is None:
                return
            self.sites.append(Site(f"{self.rel}::{self.qual}::window_scan", node.lineno,
                                   f"{base} ({ctx})"))
        elif base.startswith("self.") and base[5:] in self.grown and self.per_sample:
            self.sites.append(Site(f"{self.rel}::{self.qual}::accumulated_scan",
                                   node.lineno, base))


def _grown_attrs(cls: ast.ClassDef) -> set[str]:
    """`self.<attr>` collections a class adds to after `__init__`."""
    out = set()
    for fn in cls.body:
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) or fn.name == "__init__":
            continue
        for n in ast.walk(fn):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and n.func.attr in ("append", "extend", "insert", "add", "update",
                                        "setdefault"):
                v = n.func.value
                if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) \
                        and v.value.id == "self":
                    out.add(v.attr)
            tg = (n.targets if isinstance(n, ast.Assign)
                  else [n.target] if isinstance(n, ast.AugAssign) else [])
            for t in tg:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Attribute) \
                        and isinstance(t.value.value, ast.Name) and t.value.value.id == "self":
                    out.add(t.value.attr)
                if isinstance(n, ast.AugAssign) and isinstance(t, ast.Attribute) \
                        and isinstance(t.value, ast.Name) and t.value.id == "self":
                    out.add(t.attr)
    return out


PRIOR_ATTR = re.compile(r"^_?prev")


def roundscope_sites(base: Path | None = None, files=None) -> list[Site]:
    """Every ROUNDSCOPE smell in `reticle/`, by AST heuristic.

    Five kinds, each a site keyed `<file>::<qualname>::<kind>`. A per-sample
    method is `feed`, `step`, `read` or `process`, or a method one of them
    reaches through `self.<method>(...)`.

    - `window_scan`: a loop or comprehension walks a collection held outside
      the innermost enclosing loop (or a parameter, or `self.<attr>`) and keeps
      elements by an ordering comparison on a time or round, or a call such
      as `in_window`, against a value that loop or call varies. Per round or
      per item it filters the whole session where a slice by sorted time or
      round would do (audit cases 2-8, 11, 12). Spatial-only filters are not
      seen: case 5 is caught through its function's time filter.
    - `accumulated_scan`: a per-sample method walks a `self.<attr>` collection
      the object grows, so each step searches everything accumulated (cases
      1, 9).
    - `session_query`: a method taking `round`, `t_ms`, `t0_ms` or `t1_ms`
      walks a whole `self.<attr>` (case 13).
    - `index_rebuilt`: one `searchsorted` or `bisect` per call, over a
      sequence the call built from its arguments, so the index is rebuilt on
      every query (cases 10, 11).
    - `carried_prior`: a per-sample method sets a `self._prev*` attribute, a
      prior carried from the last sample that a round barrier must clear
      explicitly (cases 14, 15).
    """
    base = ROOT if base is None else base
    out: list[Site] = []
    for p in (files if files is not None else _py_files(base)):
        tree = _parse_source(p)
        if tree is None:
            continue
        rel = _rel(p, base)
        out += _module_sites(tree, rel)
    return out


#: The methods a pass or a lane calls once per sample or observation.
SAMPLE_ENTRIES = frozenset({"feed", "step", "read", "process"})
#: Parameters that make a method a per-round or per-time query.
QUERY_PARAMS = frozenset({"round", "round_no", "t_ms", "t0_ms", "t1_ms"})


def _methods(cls: ast.ClassDef) -> dict:
    return {f.name: f for f in cls.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _per_sample(cls: ast.ClassDef) -> set[str]:
    """The class's sample entries and every method they reach through
    `self.<method>(...)`."""
    meths = _methods(cls)
    todo = [m for m in SAMPLE_ENTRIES if m in meths]
    seen: set[str] = set()
    while todo:
        m = todo.pop()
        if m in seen:
            continue
        seen.add(m)
        for n in ast.walk(meths[m]):
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                    and isinstance(n.func.value, ast.Name) and n.func.value.id == "self" \
                    and n.func.attr in meths and n.func.attr not in seen:
                todo.append(n.func.attr)
    return seen


def _module_sites(tree: ast.Module, rel: str) -> list[Site]:
    out: list[Site] = []

    def visit(body, prefix: str, cls: ast.ClassDef | None):
        grown = _grown_attrs(cls) if cls is not None else set()
        sample = _per_sample(cls) if cls is not None else set()
        for n in body:
            if isinstance(n, ast.ClassDef):
                visit(n.body, f"{prefix}{n.name}.", n)
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                qual = f"{prefix}{n.name}"
                out.extend(_FunctionScan(n, qual, rel, grown, n.name in sample).run())
                out.extend(_index_rebuilt(n, qual, rel))
                if n.name in sample:
                    out.extend(_carried_prior(n, qual, rel))
                if cls is not None and n.name not in ("__init__", "__post_init__"):
                    out.extend(_session_query(n, qual, rel))
                visit(n.body, f"{qual}.", None)

    visit(tree.body, "", None)
    return out


def _carried_prior(fn, qual: str, rel: str) -> list[Site]:
    out = []
    for a in ast.walk(fn):
        tg = (a.targets if isinstance(a, ast.Assign)
              else [a.target] if isinstance(a, (ast.AnnAssign, ast.AugAssign)) else [])
        for t in tg:
            for x in ast.walk(t):
                if isinstance(x, ast.Attribute) and isinstance(x.value, ast.Name) \
                        and x.value.id == "self" and PRIOR_ATTR.match(x.attr):
                    out.append(Site(f"{rel}::{qual}::carried_prior", a.lineno,
                                    f"self.{x.attr}"))
    return out


def _session_query(fn, qual: str, rel: str) -> list[Site]:
    """A method asked for one round or time that walks a whole `self.<attr>`."""
    a = fn.args
    if not {x.arg for x in a.args + a.kwonlyargs} & QUERY_PARAMS:
        return []
    for n in _FunctionScan._own_nodes(fn):
        it = (n.iter if isinstance(n, (ast.For, ast.AsyncFor))
              else n.generators[0].iter
              if isinstance(n, (ast.ListComp, ast.SetComp, ast.GeneratorExp, ast.DictComp))
              else None)
        base = _iter_base(it) if it is not None else None
        if base is not None and base.startswith("self."):
            return [Site(f"{rel}::{qual}::session_query", n.lineno, base)]
    return []


def _index_rebuilt(fn, qual: str, rel: str) -> list[Site]:
    """`searchsorted` or `bisect` once per call, over a sequence this call
    built from its arguments or `self`: an index rebuilt for every query."""
    a = fn.args
    src = {x.arg for x in a.args + a.kwonlyargs + a.posonlyargs} | {"self"}
    assigns = [n for n in _FunctionScan._own_nodes(fn) if isinstance(n, (ast.Assign, ast.AnnAssign))
               and n.value is not None]
    built: set[str] = set()
    changed = True
    while changed:
        changed = False
        for n in assigns:
            if _names(n.value) & (src | built):
                for t in (n.targets if isinstance(n, ast.Assign) else [n.target]):
                    new = {x for x in _bound_names(t) if "." not in x} - built - src
                    if new:
                        built |= new
                        changed = True
    looped = set()
    for n in _FunctionScan._own_nodes(fn):
        if isinstance(n, (ast.For, ast.AsyncFor, ast.While, ast.ListComp, ast.SetComp,
                          ast.GeneratorExp, ast.DictComp)):
            body = n.body if isinstance(n, (ast.For, ast.AsyncFor, ast.While)) else [n]
            for b in body:
                looped |= {id(x) for x in ast.walk(b)}
    out = []
    for n in _FunctionScan._own_nodes(fn):
        if isinstance(n, ast.Call) and n.args and id(n) not in looped:
            f = n.func
            name = f.attr if isinstance(f, ast.Attribute) else f.id if isinstance(f, ast.Name) \
                else None
            a0 = n.args[0]
            if name in INDEX_CALLS and isinstance(a0, ast.Name) and a0.id in built:
                out.append(Site(f"{rel}::{qual}::index_rebuilt", n.lineno, a0.id))
    return out


#: The round-scope audit of 2026-10-07 (code reading at a789acf; `reticle/`
#: unchanged to 9bacd17), one entry per site key. `audit` names the audit's
#: case numbers, `cited` its file:line, `reason` the narrower set the
#: context allows. Remove an entry in the commit that fixes its site.
ROUNDSCOPE_LEGACY: dict[str, dict] = {
    "reticle/minimap.py::AllyIconReader._stack::accumulated_scan": {
        "audit": (1,), "cited": "minimap.py:1658",
        "reason": "counts this frame's stack members by scanning every candidate of the "
                  "session; a per-frame counter would do"},
    "reticle/round_lifetimes.py::RoundLifetimes.step::window_scan": {
        "audit": (2,), "cited": "round_lifetimes.py:399-468",
        "reason": "each step scans every entity born this round; the could-overlap set is "
                  "the entities seen within the merge or appearance gap, plus self"},
    "reticle/round_lifetimes.py::RoundLifetimes.step::session_query": {
        "audit": (2,), "cited": "round_lifetimes.py:399",
        "reason": "the same scan, seen as a whole walk of `self.entities` per step"},
    "reticle/round_entities.py::session_lifetimes::window_scan": {
        "audit": (3,), "cited": "round_entities.py:401",
        "reason": "per round, filters every frame of the session; slice by stored rounds"},
    "reticle/enemy_tracks.py::build::window_scan": {
        "audit": (3,), "cited": "enemy_tracks.py:262",
        "reason": "per round, filters every frame of the session; slice by stored rounds"},
    "reticle/adjudication/death.py::adjudicate_session_deaths::window_scan": {
        "audit": (4,), "cited": "adjudication/death.py:3538, 3543, 3574",
        "reason": "per round and per pass, filters every roster and board row; slice by round"},
    "reticle/adjudication/death.py::xmark_births::window_scan": {
        "audit": (4, 5), "cited": "adjudication/death.py:2158, 2164",
        "reason": "per round, filters every X-mark frame, and clusters each mark against "
                  "every cluster of the round; slice by round, then a spatial grid"},
    "reticle/adjudication/death.py::adjudicate_round_deaths::window_scan": {
        "audit": (6,), "cited": "adjudication/death.py:2912",
        "reason": "round-scoped by contract; callers must hand the lane the round slice"},
    "reticle/adjudication/combat_report.py::_stat::window_scan": {
        "audit": (7,), "cited": "combat_report.py:614",
        "reason": "per item, filters the whole board by time; index by time once"},
    "reticle/adjudication/combat_report.py::bind_deaths::window_scan": {
        "audit": (7,), "cited": "combat_report.py:742",
        "reason": "per panel, filters every death of the session; slice by round"},
    "reticle/adjudication/killstreak.py::bind_rows::window_scan": {
        "audit": (7,), "cited": "killstreak.py:116, 122",
        "reason": "per verdict, filters every row of the session; index by time once"},
    "reticle/adjudication/spike_carrier.py::check::window_scan": {
        "audit": (7,), "cited": "spike_carrier.py:140, 152",
        "reason": "per round, filters every carried-spike sample; slice by round"},
    "reticle/ability_timeline.py::_admit_lined_x::window_scan": {
        "audit": (7,), "cited": "ability_timeline.py:691",
        "reason": "per voice line, filters every ult-slot row; index by time once"},
    "reticle/minimap_lifecycle.py::matching_events::window_scan": {
        "audit": (8,), "cited": "minimap_lifecycle.py:63",
        "reason": "scans every origin event per observation; an interval index gives the "
                  "events live at t"},
    "reticle/minimap_lifecycle.py::Lifecycle.step::accumulated_scan": {
        "audit": (9,), "cited": "minimap_lifecycle.py:153",
        "reason": "keeps every eligible row of the gap window as an anchor; one belief per "
                  "entity within walk reach would do"},
    "reticle/minimap_lifecycle.py::Lifecycle._expire::window_scan": {
        "audit": (9,), "cited": "minimap_lifecycle.py:119",
        "reason": "expires one anchor per observation, not one per entity"},
    "reticle/minimap_lifecycle.py::Lifecycle._expire::accumulated_scan": {
        "audit": (9,), "cited": "minimap_lifecycle.py:119",
        "reason": "the same anchors, walked again for the live set"},
    "reticle/minimap_lifecycle.py::Lifecycle._expire::session_query": {
        "audit": (9,), "cited": "minimap_lifecycle.py:119",
        "reason": "the same anchors, walked again for the known set"},
    "reticle/stalls.py::stalled_at::index_rebuilt": {
        "audit": (10,), "cited": "stalls.py:214 via team_vision.py:518",
        "reason": "rebuilds the stall starts on every frame; build the array once per input"},
    "reticle/clove_circle.py::CloveCircleReader._window_of::window_scan": {
        "audit": (11,), "cited": "clove_circle.py:373",
        "reason": "walks every window per frame; searchsorted over sorted windows"},
    "reticle/clove_circle.py::self_position_at::index_rebuilt": {
        "audit": (11,), "cited": "clove_circle.py:295",
        "reason": "filters the whole self track per read; filter once"},
    "reticle/ping.py::resolve::window_scan": {
        "audit": (12,), "cited": "ping.py:431",
        "reason": "tests every boundary per group; bisect"},
    "reticle/entity_events.py::EntityEvents.entities::session_query": {
        "audit": (13,), "cited": "entity_events.py:1132",
        "reason": "every query scans every lane's session rows; key rows by round and "
                  "entity at load"},
    "reticle/entity_events.py::EntityEvents.events::session_query": {
        "audit": (13,), "cited": "entity_events.py:1147",
        "reason": "every query scans every lane's session rows; key rows by round and "
                  "entity at load"},
    "reticle/entity_events.py::EntityEvents.coverage::session_query": {
        "audit": (13,), "cited": "entity_events.py:1178",
        "reason": "every query scans every lane's session rows; key rows by round at load"},
    "reticle/entity_events.py::EntityEvents.ledger::session_query": {
        "audit": (13,), "cited": "entity_events.py:1184",
        "reason": "every query scans every lane's session rows; key rows by round at load"},
    "reticle/ability_icons.py::AbilityIconReader.feed::carried_prior": {
        "audit": (14,), "cited": "ability_icons.py:292",
        "reason": "carries the last frame's icons; crosses a round barrier when `phase_at` "
                  "is None; clear it at the barrier explicitly"},
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::carried_prior": {
        "audit": (14,), "cited": "minimap_glyph.py:878",
        "reason": "carries the last frame's glyphs; clear them at the round barrier explicitly"},
    "reticle/teardrop.py::IconPoseReader.read::carried_prior": {
        "audit": (15,), "cited": "teardrop.py:911",
        "reason": "the prior holds within PRIOR_GAP_MS (200 ms); make the barrier explicit"},
    "reticle/teardrop.py::IconPoseReader.read::accumulated_scan": {
        "audit": (15,), "cited": "teardrop.py:911",
        "reason": "the same prior, built by walking the image's fits"},
    "reticle/teardrop.py::IconPoseReader.read::session_query": {
        "audit": (15,), "cited": "teardrop.py:911",
        "reason": "the same prior, built by walking the image's fits"},
}

#: Sites the audit read and judged bounded ("Bounded, no action"). Not debts:
#: `doctor` stays silent on them, and errors if one stops being found.
ROUNDSCOPE_BOUNDED: dict[str, str] = {
    "reticle/track.py::Tracker.step::window_scan":
        "audit 2026-10-07: track.Tracker.step is bounded by its expiring track set",
    "reticle/track.py::Tracker.step::session_query":
        "audit 2026-10-07: track.Tracker.step is bounded by its expiring track set",
    "reticle/primitives.py::PrimitiveExtractor.process::carried_prior":
        "audit 2026-10-07: primitives._prev_dhash compares adjacent frames only",
    "reticle/primitives.py::PrimitiveExtractor.process::session_query":
        "audit 2026-10-07: primitives._prev_dhash compares adjacent frames only",
}

#: Sites the detector found on 2026-10-09 outside the audit's fifteen cases,
#: unreviewed. Each is a debt until someone reads it: fix it and drop the
#: key, or judge it bounded and move it to ROUNDSCOPE_BOUNDED with the reason.
ROUNDSCOPE_UNREVIEWED: tuple[str, ...] = (
    "reticle/ability_candidates.py::CandidateSupply._alive::session_query",
    "reticle/ability_candidates.py::CandidateSupply._alive::window_scan",
    "reticle/ability_timeline.py::_kit_end::window_scan",
    "reticle/ability_timeline.py::build_timeline::window_scan",
    "reticle/ability_timeline.py::dead_ruse_casts::window_scan",
    "reticle/ability_timeline.py::round_window_of::window_scan",
    "reticle/adjudication/ability.py::disc_tracks::index_rebuilt",
    "reticle/adjudication/ability.py::onset_groups::window_scan",
    "reticle/adjudication/ability.py::predict_ability_births::window_scan",
    "reticle/adjudication/ability_audio.py::clip_bounds::index_rebuilt",
    "reticle/adjudication/ability_audio.py::next_neighbour::index_rebuilt",
    "reticle/adjudication/ability_glyph.py::adjudicate::index_rebuilt",
    "reticle/adjudication/combat_report.py::_killfeed_name::window_scan",
    "reticle/adjudication/combat_report.py::assign_rounds::window_scan",
    "reticle/adjudication/combat_report.py::episodes::window_scan",
    "reticle/adjudication/combat_report.py::name_rows::window_scan",
    "reticle/adjudication/combat_report.py::panels::window_scan",
    "reticle/adjudication/combat_report.py::portrait_clusters::window_scan",
    "reticle/adjudication/death.py::_board_interval::window_scan",
    "reticle/adjudication/death.py::_match_shrinks::window_scan",
    "reticle/adjudication/death.py::_portrait_channel::window_scan",
    "reticle/adjudication/death.py::_roster_before::index_rebuilt",
    "reticle/adjudication/death.py::_score_unread::index_rebuilt",
    "reticle/adjudication/death.py::entry_follow_evidence.propose::window_scan",
    "reticle/adjudication/death.py::entry_follow_evidence::window_scan",
    "reticle/adjudication/death.py::entry_slot_path::window_scan",
    "reticle/adjudication/death.py::match_xmark::window_scan",
    "reticle/adjudication/death.py::revive_context::window_scan",
    "reticle/adjudication/death.py::same_entry::window_scan",
    "reticle/adjudication/death.py::second_life_death::window_scan",
    "reticle/adjudication/death.py::session_entries::window_scan",
    "reticle/adjudication/death.py::split_second_lives::window_scan",
    "reticle/adjudication/phases.py::candidate_causes::window_scan",
    "reticle/adjudication/smoke_owner.py::circle_runs::window_scan",
    "reticle/adjudication/smoke_owner.py::circle_verdict::window_scan",
    "reticle/adjudication/smoke_owner.py::tray_verdict::window_scan",
    "reticle/adjudication/tray_kit.py::own_kit_mask::index_rebuilt",
    "reticle/adjudication/tray_kit.py::spectated_agent::window_scan",
    "reticle/adjudication/ult_cast.py::adjudicate::window_scan",
    "reticle/adjudication/ult_cast.py::burst_of::index_rebuilt",
    "reticle/adjudication/ult_cast.py::nearest_cast::window_scan",
    "reticle/adjudication/weapon.py::bind_entry::window_scan",
    "reticle/belief.py::resolve::window_scan",
    "reticle/checks.py::merge_split_tracks::window_scan",
    "reticle/checks.py::panel_slots::index_rebuilt",
    "reticle/checks.py::track_entries::window_scan",
    "reticle/cli.py::_MinimapPass.feed::carried_prior",
    "reticle/cli.py::_tray_kit_values::window_scan",
    "reticle/cli.py::cmd_kd::window_scan",
    "reticle/clove_circle.py::opportunity_windows::window_scan",
    "reticle/coaching.py::attach_event_estimates::window_scan",
    "reticle/combat_report.py::read_flag::window_scan",
    "reticle/decode.py::windows_of::window_scan",
    "reticle/dev_sample.py::new_targets::window_scan",
    "reticle/dev_sample.py::opportunity_rounds::window_scan",
    "reticle/economy.py::EconomyTracker.reset_period::session_query",
    "reticle/episodes.py::ChildTable.position::index_rebuilt",
    "reticle/episodes.py::_attempts::window_scan",
    "reticle/episodes.py::_covering::window_scan",
    "reticle/episodes.py::_duels::window_scan",
    "reticle/episodes.py::_engagements::window_scan",
    "reticle/episodes.py::_execute_retake_lurk::index_rebuilt",
    "reticle/episodes.py::_rotations::window_scan",
    "reticle/episodes.py::alive_from_events::index_rebuilt",
    "reticle/episodes.py::round_at::window_scan",
    "reticle/fidelity.py::score_killfeed::window_scan",
    "reticle/frame_join.py::grid_join::index_rebuilt",
    "reticle/frame_join.py::sampled_state::index_rebuilt",
    "reticle/gametime.py::_schedule_at::index_rebuilt",
    "reticle/gametime.py::build_session_gametime::window_scan",
    "reticle/killfeed.py::EntryAnchors.frame::session_query",
    "reticle/killfeed.py::EntryAnchors.frame::window_scan",
    "reticle/killfeed.py::plate_colour::index_rebuilt",
    "reticle/menu.py::MenuWitness.at::session_query",
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::accumulated_scan",
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::carried_prior",
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::accumulated_scan",
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::window_scan",
    "reticle/overlay.py::_state_at::window_scan",
    "reticle/refinement.py::save_refinement::window_scan",
    "reticle/replay_keep.py::overlapping::window_scan",
    "reticle/replay_source.py::Replay.alive::index_rebuilt",
    "reticle/roi_cache.py::GridPicker._in::window_scan",
    "reticle/roi_cache.py::RoiCacheUnion.samples::window_scan",
    "reticle/round_entities.py::ally_dead_intervals::window_scan",
    "reticle/round_entities.py::drop_binding_refusal::window_scan",
    "reticle/round_entities.py::player_dead_spans::window_scan",
    "reticle/round_lifetimes.py::RoundLifetimes._record_ambiguous_components::accumulated_scan",
    "reticle/round_lifetimes.py::RoundLifetimes.association_for::accumulated_scan",
    "reticle/round_lifetimes.py::glyph_coincidence::index_rebuilt",
    "reticle/round_lifetimes.py::seen_after_death::window_scan",
    "reticle/round_outcome.py::fit_columns::index_rebuilt",
    "reticle/round_outcome.py::fit_columns::window_scan",
    "reticle/round_view.py::_timeline_strip::window_scan",
    "reticle/rounds.py::_reset_after::index_rebuilt",
    "reticle/rounds.py::build_rounds::window_scan",
    "reticle/rounds.py::in_round_window::window_scan",
    "reticle/rounds.py::round_containing::window_scan",
    "reticle/self_icon.py::all_alive::index_rebuilt",
    "reticle/stalls.py::spans::window_scan",
    "reticle/tiers.py::check_omen_smokes::window_scan",
    "reticle/track.py::Track.resolved_facing::window_scan",
    "reticle/tray.py::flag_suspect::window_scan",
    "reticle/tray.py::gold_witness::window_scan",
    "reticle/tray_countdown.py::score_against_returns::window_scan",
    "reticle/trial.py::targets::index_rebuilt",
    "reticle/view_events.py::Loaded.active::index_rebuilt",
    "reticle/view_events.py::_team_vision::window_scan",
    "reticle/widget_frame.py::WidgetFrame.at::session_query",
    "reticle/widget_frame.py::WidgetFrame.at::window_scan",
    "reticle/widget_frame.py::drawn_collapse::index_rebuilt",
    "reticle/widget_frame.py::fit_session::window_scan",
    "reticle/widget_frame.py::round_frames::window_scan",
    "reticle/widget_frame.py::snap_switch::window_scan",
)


def roundscope_findings(base: Path | None = None, legacy: dict | None = None,
                        bounded: dict | None = None, unreviewed=None,
                        files=None) -> list[tuple[str, str]]:
    """ROUNDSCOPE: state outlives a round, or a search walks past the
    could-overlap set.

    A site no list names is an ERROR. An audited legacy site is a WARN with its
    case, citation and reason; the unreviewed sites are one WARN that counts
    them by module; a bounded site is silent. A list key whose site the
    detector no longer finds is an ERROR until the key goes, so the lists
    only shrink. The detector is a heuristic (`roundscope_sites`); it must
    find every audited case, which `tests/test_ratchets.py` checks.
    """
    legacy = ROUNDSCOPE_LEGACY if legacy is None else legacy
    bounded = ROUNDSCOPE_BOUNDED if bounded is None else bounded
    unreviewed = set(ROUNDSCOPE_UNREVIEWED if unreviewed is None else unreviewed)
    lines: dict[str, list[int]] = {}
    for s in roundscope_sites(base, files=files):
        lines.setdefault(s.key, []).append(s.line)
    out = []
    pending = []
    for key in sorted(lines):
        at = ", ".join(str(x) for x in sorted(set(lines[key])))
        if key in legacy:
            e = legacy[key]
            cases = ", ".join(f"#{c}" for c in e["audit"])
            out.append((WARN, f"legacy `{key}` (lines {at}; audit {cases}, {e['cited']}): "
                              f"{e['reason']}"))
        elif key in bounded:
            continue
        elif key in unreviewed:
            pending.append(key)
        else:
            out.append((ERROR, f"`{key}` (lines {at}) holds state past a round or searches "
                               "past the could-overlap set -- scope it to the round or slice "
                               "by sorted time; never a new allowlist entry"))
    if pending:
        mods = sorted({k.split("::")[0] for k in pending})
        out.append((WARN, f"{len(pending)} unreviewed legacy sites (found 2026-10-09, outside "
                          f"the audit) in {len(mods)} modules: "
                          + ", ".join(m.removeprefix("reticle/") for m in mods)))
    for name, keys in (("ROUNDSCOPE_LEGACY", legacy), ("ROUNDSCOPE_BOUNDED", bounded),
                       ("ROUNDSCOPE_UNREVIEWED", unreviewed)):
        for key in sorted(set(keys) - set(lines)):
            out.append((ERROR, f"{name} names `{key}`, which the detector no longer finds -- "
                               "remove it from the allowlist"))
    return out


# ---------------------------------------------------------------------------
# PROMOTE strict: a passed pilot meant for production is wired or scheduled
# ---------------------------------------------------------------------------

#: Ledger row kinds that record a result rather than a prediction.
RESULT_KINDS = frozenset({"outcome", "prediction_outcome", "decision", "wire_decision"})
#: `wire` values that mean the result is meant for production.
WIRE_INTENT = frozenset({"yes", "pending"})
RETICLE_MODULE = re.compile(r"\breticle[/.]((?:adjudication[/.])?\w+)")
BACKLOG_ITEM = re.compile(r"\bBACKLOG\s+(\d+)\b")

#: Passed pilots meant for production that were neither wired, scheduled nor
#: declined when the strict check landed: none on 2026-10-09 (`ability_disc`
#: and `mine_icons` passed, and later rows with their subject declined them).
#: An entry names a stem and why it waits; it goes when the pilot is wired.
PROMOTE_LEGACY: dict[str, str] = {}


def _mentions(stems: set[str], text: str) -> set[str]:
    return stems.intersection(re.findall(r"\w+", text))


def passed_pilots(rows: list[dict], stems: set[str]) -> dict[str, list[dict]]:
    """Prototype stem -> the ledger rows that record a result with `wire`
    "yes" or "pending": a pilot that passed and is meant for production.

    A row names its prototype in `prototype` or `subject` when it has one;
    otherwise every prototype its text mentions.
    """
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("kind") not in RESULT_KINDS:
            continue
        if str(r.get("wire", "")).lower() not in WIRE_INTENT:
            continue
        target = str(r.get("prototype") or r.get("subject") or "")
        named = _mentions(stems, target) if target else set()
        if not named:
            named = _mentions(stems, " ".join(str(v) for v in r.values()))
        for s in named:
            out.setdefault(s, []).append(r)
    return out


def promote_strict(rows: list[dict], stems: set[str], used: set[str],
                   modules: set[str], open_items: set[int],
                   legacy: dict | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """PROMOTE strict: `(findings, unwired)` for the passed pilots.

    A passed pilot is wired when a `reticle/` module mentions it (`used`), or
    when its result row's `wire_reason` names an existing `reticle` module
    (`modules`, dotted names) that took it over. It is scheduled when any
    ledger row naming it carries `"wired_by": "BACKLOG <n>"` with `n` an open
    item. A `"wire": "no"` row declines it only when it comes after the
    pilot's last passing row and names the pilot in its `subject` or
    `prototype` field.

    Anything else is an ERROR, or a WARN where `PROMOTE_LEGACY` lists it; a
    listed pilot now wired, scheduled or declined is an ERROR until its entry
    goes. The loopholes this closes: the loose check only warned, so a result
    row saying "wire: yes" could sit unwired with no item named for it; and a
    decline without a subject retired every prototype its prose mentioned,
    a passed pilot included. `unwired` lists the passed pilots neither wired
    nor declined, scheduled ones with their item, for `status`.
    """
    legacy = PROMOTE_LEGACY if legacy is None else legacy
    pilots = passed_pilots(rows, stems)
    last_pass = {s: max(i for i, r in enumerate(rows) if any(r is p for p in ps))
                 for s, ps in pilots.items()}
    declined: set[str] = set()
    scheduled: dict[str, int] = {}
    bad_item: dict[str, str] = {}
    for i, r in enumerate(rows):
        subject = str(r.get("subject") or r.get("prototype") or "")
        if str(r.get("wire", "")).lower() == "no" and subject:
            declined |= {s for s in _mentions(stems, subject) if i > last_pass.get(s, -1)}
        if r.get("wired_by"):
            named = _mentions(stems, subject) if subject else \
                _mentions(stems, " ".join(str(v) for v in r.values()))
            m = BACKLOG_ITEM.search(str(r["wired_by"]))
            for s in named:
                if m and int(m.group(1)) in open_items:
                    scheduled[s] = int(m.group(1))
                else:
                    bad_item[s] = str(r["wired_by"])
    out, unwired = [], []
    for s in sorted(pilots):
        if s in declined:
            continue
        reasons = " ".join(str(r.get("wire_reason") or "") for r in pilots[s])
        took = {m.group(1).replace("/", ".") for m in RETICLE_MODULE.finditer(reasons)}
        wired = s in used or bool(took & modules)
        if wired:
            continue
        if s in scheduled:
            unwired.append(f"{s} (BACKLOG {scheduled[s]})")
            continue
        unwired.append(s)
        tag = str(pilots[s][0].get("id") or pilots[s][0].get("date")
                  or pilots[s][0].get("ts") or "")[:40]
        if s in bad_item:
            out.append((ERROR, f"`prototypes/{s}.py` names `{bad_item[s]}` as its wiring item, "
                               "which is no open BACKLOG item"))
        elif s in legacy:
            out.append((WARN, f"legacy passed pilot `prototypes/{s}.py`"
                              + (f" ({tag})" if tag else "")
                              + f": {legacy[s]}; wire it or name its BACKLOG item"))
        else:
            out.append((ERROR, f"`prototypes/{s}.py` passed a pilot meant for production"
                               + (f" ({tag})" if tag else "")
                               + " and is neither wired into `reticle/` nor scheduled -- "
                               "wire it, or record `\"wired_by\": \"BACKLOG <n>\"` on a "
                               "ledger row naming it"))
    # A ledger only grows, so a listed pilot absent from these rows is a
    # ledger this call was not given (a test's), not a resolved debt.
    live = {u.split(" ")[0] for u in unwired if "(" not in u}
    for s in sorted((set(legacy) & set(pilots)) - live):
        out.append((ERROR, f"PROMOTE_LEGACY names `{s}`, which is now wired, scheduled or "
                           "declined -- remove it from the allowlist"))
    return out, unwired


# ---------------------------------------------------------------------------
# Progress, for `status`
# ---------------------------------------------------------------------------

#: The allowlists' sizes when they were seeded, 2026-10-09.
SEEDED = {"CONVERT": 14, "ROUNDSCOPE": 31, "ROUNDSCOPE_UNREVIEWED": 114}


def progress(base: Path | None = None) -> dict:
    """Conversion progress per ratchet: readers gated against legacy, audited
    sites fixed against legacy, unreviewed sites left."""
    readers = reader_classes(base)
    return {
        "convert": {"gated": sum(1 for _k, _l, g, _o in readers if g),
                    "legacy": len(CONVERT_LEGACY)},
        "roundscope": {"fixed": SEEDED["ROUNDSCOPE"] - len(ROUNDSCOPE_LEGACY),
                       "legacy": len(ROUNDSCOPE_LEGACY),
                       "reviewed": SEEDED["ROUNDSCOPE_UNREVIEWED"] - len(ROUNDSCOPE_UNREVIEWED),
                       "unreviewed": len(ROUNDSCOPE_UNREVIEWED)},
    }


def progress_line(p: dict, unwired: list[str] | None = None) -> list[str]:
    """`status`'s pickup lines: conversion progress, then the passed pilots
    nothing wires yet."""
    c, r = p["convert"], p["roundscope"]
    out = [f"Conversion (BACKLOG 1): CONVERT {c['gated']} gated / {c['legacy']} legacy readers; "
           f"ROUNDSCOPE {r['fixed']} fixed / {r['legacy']} legacy audited sites, "
           f"{r['reviewed']} reviewed / {r['unreviewed']} unreviewed detector sites."]
    if unwired is not None:
        out.append(f"Passed pilots not wired: {', '.join(unwired) or 'none'}.")
    return out
