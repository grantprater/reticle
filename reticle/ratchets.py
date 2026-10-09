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

ABILITY (`ability_findings`, docs/ABILITY_ENTITIES.md step 1) joins them: every
ability stream, lane and ownership entry is a declared input of the child
owner (`slot_state.CHANNELS`) or the child owner's own, else listed in the
shrink-only `ABILITY_LEGACY` with the plan step that clears it.

KINDS (`kinds_findings`): every entity kind the slot owner declares
(`slot_state`'s `KIND_*` constants, or an entry its `CHANNELS` rows feed) is
one `slot_state.build_slots` builds, else listed in the shrink-only
`KINDS_LEGACY` with the plan step that builds it.

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
class Audit:
    """A frame gate's audit cadence, fixed in advance (AGENTS.md: audit a
    prior on a cadence fixed in advance, stored apart).

    Inside each of the reader's spans -- the opportunity the reader already
    waits for, a live round -- the windows `[s0 + phase + k every, + window)`
    are read at the reader's full grid whatever the gate says. The cadence
    depends on the span's start alone, never on a read, so an audit sample
    is an opportunity-gated sample and never a surprise-triggered one. The
    hook (`passes`) marks each such frame `audit`; its owner stores the
    audit reads apart from the gated stream.
    """

    every_ms: float
    window_ms: float
    phase_ms: float = 0.0

    def __post_init__(self):
        if not (0 < self.window_ms < self.every_ms) or self.phase_ms < 0:
            raise ValueError("an audit reads a window shorter than its period, at a phase >= 0")

    def covers(self, t_ms: float, span_start: float | None) -> bool:
        """Is `t_ms` inside an audit window of the span that starts at
        `span_start` and holds it? None: no span holds it."""
        if span_start is None:
            return False
        k = float(t_ms) - float(span_start) - float(self.phase_ms)
        return k >= 0 and (k % float(self.every_ms)) < float(self.window_ms)

    def stamp(self) -> dict:
        return {"every_ms": float(self.every_ms), "window_ms": float(self.window_ms),
                "phase_ms": float(self.phase_ms), "anchor": "each span's start"}


@dataclass(frozen=True)
class Gate:
    """A reader's declared opportunity gate: what opens a read, and where the
    gate's belief comes from.

    A reader declares one as its CLASS attribute `opportunity_gate`, so
    `doctor` can see it without running anything; an instance may bind its
    own copy (`bound`), which `declared_gate` prefers. `kind` says who
    applies it:

    - `"spans"`: the reader's `spans` are the opportunity windows, built from
      stored evidence before the pass (`clove_circle.stored_windows` builds
      Clove's). `decode.sample_multi` and `passes.cache_feed` already honour
      spans, so the gate needs no hook.
    - `"frame"`: the reader's `wants(t_ms)` decides per sample, from the
      gate's belief (`source`). The per-frame gate hook in `passes.run`,
      `passes.run_cached` and `process_shards` consumes it (`FRAME_HOOK`):
      it asks before the decode's retrieve or the crop's fetch, records each
      refusal with its reason, and feeds the frame only where the gate opens
      or the audit cadence covers it. A `"frame"` gate names its `version`
      and its `audit` cadence; CONVERT errors on one without `wants`, a
      version or an audit.

    `opportunity` names the event that opens a read ("an ally Clove's death
    window"); `source` names the stored stream or function the gate reads.
    `version` stamps the gate's rule into every stream it gated. `rests_on`
    names the prior the instance's gate reads (the slot belief's stamp), so
    a result the gate shaped never counts that prior again; the class
    declaration leaves it empty and `bound` fills it per instance.

    One reader serving many abilities binds one gate per instance; `doctor`
    reads the class declaration as the floor.
    """

    opportunity: str
    source: str
    kind: str = "spans"
    version: str = ""
    audit: Audit | None = None
    rests_on: tuple = ()

    def __post_init__(self):
        if self.kind not in ("spans", "frame"):
            raise ValueError(f"a gate's kind is 'spans' or 'frame', not {self.kind!r}")
        if not self.opportunity or not self.source:
            raise ValueError("a gate names its opportunity and its source")
        if self.kind == "frame" and (not self.version or self.audit is None):
            raise ValueError("a 'frame' gate names its version and its audit cadence")

    def bound(self, rests_on) -> "Gate":
        """This declaration for one instance, naming the prior it rests on."""
        from dataclasses import replace
        return replace(self, rests_on=tuple(rests_on))


#: Does `passes.run` apply `"frame"` gates? True since the hook landed
#: (gate-hook-20261009): `passes.run`, `passes.run_cached` and
#: `process_shards` ask a frame-gated reader's `wants` before each frame.
FRAME_HOOK = True


def declared_gate(reader) -> Gate | None:
    """The `Gate` a reader declares, through any wrapper: the instance's own
    binding first, then its class's; None where it declares none (a
    fixed-grid reader)."""
    inner = _unwrap(reader)
    got = getattr(inner, "__dict__", {}).get("opportunity_gate")
    if not isinstance(got, Gate):
        got = getattr(type(inner), "opportunity_gate", None)
    return got if isinstance(got, Gate) else None


def converted(gate: Gate | None) -> bool:
    """Does `gate` stop a fixed grid today? A `"spans"` gate does; a
    `"frame"` gate only once `FRAME_HOOK` applies it."""
    return gate is not None and (gate.kind == "spans" or FRAME_HOOK)


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
    "reticle/trial.py::_AbilityGlyphPass": {
        "rate": "2 Hz: `trial._ability_timeline`'s 0.5 s grid over the minimap cache "
                "(its driver's grid; the class binds no `hz`)",
        "converts": "BACKLOG 1: with the ability readers it wraps"},
}

#: The keys CONVERT_LEGACY held when it was seeded, 2026-10-09, less each
#: reader converted since (removal is the one way it changes:
#: `minimap.AllyIconReader`, gate-hook-20261009). Frozen: doctor errors on a
#: CONVERT_LEGACY key outside it, so the list cannot grow by an edit that
#: adds one entry and drops another.
CONVERT_SEED = frozenset({
    "reticle/cli.py::_MinimapPass",
    "reticle/ping.py::PingReader", "reticle/minimap_dark.py::DarkRegionReader",
    "reticle/ability_scan.py::AbilityShapeReader", "reticle/ability_icons.py::AbilityIconReader",
    "reticle/minimap_glyph.py::AbilityGlyphReader", "reticle/hud_reader.py::HudReader",
    "reticle/killfeed.py::KillfeedPortraitReader", "reticle/roster.py::RosterReader",
    "reticle/scoreboard.py::ScoreboardReader", "reticle/combat_report.py::CombatReportReader",
    "reticle/lineup.py::LineupReader", "reticle/roi_cache.py::RoiCacheWriter",
    "reticle/trial.py::_AbilityGlyphPass",
})


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


@dataclass(frozen=True)
class ReaderClass:
    """One reader class as `doctor` sees it in the source.

    `rate` says where its sampling rate comes from: `"class"` (a class
    attribute or `self.hz`, set from a constructor argument or a module
    constant), `"property"`, `"inherited from <Base>"`, `"assigned outside
    the class"` (`r = Reader(...); r.hz = ...`), or `"its driver's grid"`
    (no `hz` at all; the code that feeds it picks the times). `gate_kind` is the
    declared gate's `kind` ("spans" where the call does not say).
    """

    key: str
    line: int
    gated: bool
    gate_ok: bool
    gate_kind: str | None
    wants: bool
    rate: str
    #: The keyword fields the declaration names (`version`, `audit`, ...).
    gate_fields: frozenset = frozenset()


def _one_arg_feed(fn) -> bool:
    a = fn.args
    return (fn.name == "feed" and len(a.posonlyargs) + len(a.args) == 2
            and a.vararg is None)


def _base_names(c: ast.ClassDef) -> list[str]:
    return [b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""
            for b in c.bases]


def _class_facts(c: ast.ClassDef) -> dict:
    meths = {n.name: n for n in c.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    hz = None
    for n in ast.walk(c):
        tg = (n.targets if isinstance(n, ast.Assign)
              else [n.target] if isinstance(n, ast.AnnAssign) else [])
        for t in tg:
            # `self.hz`, a class attribute, or `reader.hz` inside a classmethod
            if any(x == "hz" or x.endswith(".hz") for x in _bound_names(t)):
                hz = "class"
    if "hz" in meths and any(isinstance(d, ast.Name) and d.id == "property"
                             for d in meths["hz"].decorator_list):
        hz = "property"
    gate = None
    for n in c.body:
        tg = (n.targets if isinstance(n, ast.Assign)
              else [n.target] if isinstance(n, ast.AnnAssign) else [])
        if any(isinstance(t, ast.Name) and t.id == "opportunity_gate" for t in tg):
            v = n.value
            ok = (isinstance(v, ast.Call)
                  and ((isinstance(v.func, ast.Name) and v.func.id == "Gate")
                       or (isinstance(v.func, ast.Attribute) and v.func.attr == "Gate")))
            kind = "spans"
            named = set()
            if ok:
                for kw in v.keywords:
                    if kw.arg == "kind" and isinstance(kw.value, ast.Constant):
                        kind = str(kw.value.value)
                    named.add(kw.arg)
                if len(v.args) >= 3 and isinstance(v.args[2], ast.Constant):
                    kind = str(v.args[2].value)
                # positional arguments name the fields in their declared order
                named |= set(("opportunity", "source", "kind", "version", "audit",
                              "rests_on")[:len(v.args)])
            gate = (ok, kind, named)
    return {"node": c, "bases": _base_names(c),
            "protocol": "Protocol" in _base_names(c),
            "feed": "feed" in meths and _one_arg_feed(meths["feed"]),
            "wrapper": "__getattr__" in meths,
            "wants": "wants" in meths, "hz": hz, "gate": gate}


def reader_classes(base: Path | None = None) -> list[ReaderClass]:
    """Every reader class in `reticle/`.

    A reader is what a pass feeds: a class whose `feed` takes one sample,
    defined on it or inherited from a base in `reticle/`. Its rate may come
    from anywhere -- a constructor argument, a module constant, a property,
    a base class, an assignment outside the class, or the driver's own grid
    (`trial._AbilityGlyphPass` binds no `hz`) -- so the rate does not decide
    who is a reader; it is reported. A `typing.Protocol` is a description,
    and a class defining `__getattr__` is a wrapper (`widget_frame.Normalised`)
    whose inner reader is checked instead. A gate is inherited as Python
    inherits it.
    """
    base = ROOT if base is None else base
    facts: dict[str, list[tuple[str, dict]]] = {}
    outside_hz: set[str] = set()
    for p in _py_files(base):
        tree = _parse_source(p)
        if tree is None:
            continue
        rel = _rel(p, base)
        made: dict[str, str] = {}       # variable -> the class it was built from
        for n in ast.walk(tree):
            if isinstance(n, ast.ClassDef):
                facts.setdefault(n.name, []).append((rel, _class_facts(n)))
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) \
                    and isinstance(n.value.func, ast.Name):
                for t in n.targets:
                    if isinstance(t, ast.Name):
                        made[t.id] = n.value.func.id
        for n in ast.walk(tree):
            for t in (n.targets if isinstance(n, ast.Assign) else []):
                if isinstance(t, ast.Attribute) and t.attr == "hz" \
                        and isinstance(t.value, ast.Name) and t.value.id in made:
                    outside_hz.add(made[t.value.id])

    def lineage(f: dict, seen=()):
        yield None, f
        for b in f["bases"]:
            if b in facts and b not in seen:
                for _rel_b, fb in facts[b][:1]:
                    for _who, g in lineage(fb, seen + (b,)):
                        yield (b if _who is None else _who), g

    out = []
    for name, entries in sorted(facts.items()):
        for rel, f in entries:
            if f["protocol"] or f["wrapper"]:
                continue
            chain = list(lineage(f))
            if not any(g["feed"] for _w, g in chain):
                continue
            rate = next((g["hz"] if who is None else f"inherited from {who}"
                         for who, g in chain if g["hz"]), None)
            if rate is None:
                rate = ("assigned outside the class" if name in outside_hz
                        else "its driver's grid")
            gate = next((g["gate"] for _w, g in chain if g["gate"]), None)
            out.append(ReaderClass(
                key=f"{rel}::{name}", line=f["node"].lineno, gated=gate is not None,
                gate_ok=bool(gate and gate[0]), gate_kind=gate[1] if gate else None,
                wants=any(g["wants"] for _w, g in chain), rate=rate,
                gate_fields=frozenset(gate[2]) if gate else frozenset()))
    return sorted(out, key=lambda r: r.key)


def convert_findings(base: Path | None = None, legacy: dict | None = None,
                     seed: frozenset | None = None) -> list[tuple[str, str]]:
    """CONVERT: a reader samples a fixed grid unless it declares a gate.

    A reader converts when it declares a `"spans"` gate, or a `"frame"` gate
    once `FRAME_HOOK` applies it. An unconverted reader with no
    `CONVERT_LEGACY` entry is an ERROR: a new fixed-grid reader. A listed one
    is a WARN naming its rate and the item that converts it. A `"frame"` gate
    with no `wants` method, or declared without its `version` or `audit`,
    is an ERROR. A listed reader that converted, or
    no longer exists, is an ERROR until its entry goes; a listed key outside
    the frozen `CONVERT_SEED` is an ERROR, so the list only shrinks. Clove's
    circle (`clove_circle.CloveCircleReader`) declares a `"spans"` gate, its
    death windows, and passes.
    """
    legacy = CONVERT_LEGACY if legacy is None else legacy
    seed = CONVERT_SEED if seed is None else seed
    found = reader_classes(base)
    keys = {r.key for r in found}
    out = []
    for r in found:
        where = f"`{r.key}` (line {r.line})"
        if r.gated and not r.gate_ok:
            out.append((ERROR, f"{where} binds `opportunity_gate` to something other than "
                               "a `ratchets.Gate(...)`"))
        if r.gate_kind == "frame" and not r.wants:
            out.append((ERROR, f"{where} declares a \"frame\" gate and no `wants(t_ms)` "
                               "method for the hook to call"))
        if r.gate_ok and r.gate_kind == "frame":
            for need in ("version", "audit"):
                if need not in r.gate_fields:
                    out.append((ERROR, f"{where} declares a \"frame\" gate without its "
                                       f"`{need}` (a stamp and an audit cadence fixed in "
                                       "advance)"))
        done = r.gate_ok and (r.gate_kind == "spans" or FRAME_HOOK)
        frame_wait = r.gate_kind == "frame" and not FRAME_HOOK
        if done and r.key in legacy:
            out.append((ERROR, f"{where} declares a gate and still has a CONVERT_LEGACY "
                               "entry -- remove it from the allowlist"))
        elif not done and r.key in legacy:
            e = legacy[r.key]
            out.append((WARN, f"legacy fixed-grid reader {where}: {e['rate']}; "
                              f"converts in {e['converts']}"
                              + ("; its \"frame\" gate waits for the passes hook"
                                 if frame_wait else "")))
        elif frame_wait:
            out.append((ERROR, f"{where} declares a \"frame\" gate, which converts nothing "
                               "until the passes hook applies it (BACKLOG 1) -- the reader "
                               f"still samples a fixed grid ({r.rate})"))
        elif not done:
            out.append((ERROR, f"{where} samples a fixed grid (rate: {r.rate}) and declares "
                               "no `opportunity_gate` -- declare a `ratchets.Gate`, never "
                               "a new CONVERT_LEGACY entry"))
    for key in sorted(set(legacy) - keys):
        out.append((ERROR, f"CONVERT_LEGACY names `{key}`, which is no reader any more -- "
                           "remove it from the allowlist"))
    for key in sorted(set(legacy) - set(seed)):
        out.append((ERROR, f"CONVERT_LEGACY names `{key}`, outside the frozen CONVERT_SEED -- "
                           "the allowlist only shrinks"))
    return out


def legacy_running(readers, legacy: dict | None = None) -> list[str]:
    """One warning line per running reader that `CONVERT_LEGACY` lists and
    no applied gate converts: what `scan` prints before its pass. A warning,
    never a refusal."""
    legacy = CONVERT_LEGACY if legacy is None else legacy
    out = []
    for r in readers:
        key = convert_key(r)
        if key in legacy and not converted(declared_gate(r)):
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
        # An ordering keeps a window; an equality on a time or round key
        # (`r["round"] == rnd`, `r["frame_idx"] == i`) keeps a slice. Both
        # walk the whole collection to find it.
        if isinstance(n, ast.Compare) \
                and any(isinstance(o, ORDERING + (ast.Eq,)) for o in n.ops):
            used = _names(n)
            if used & elem and (used - elem) & varying and _timelike(n):
                return True
        if isinstance(n, ast.Call) and n.args:
            # A call keeps a window only when it reads a FIELD of the element
            # against a varying value (`in_window(line, r["t_ms"], win)`); a
            # call on the bare element (`self.refusal(t, rois)`) is a
            # per-element lookup, one pass, not a window.
            fields = [a for a in n.args if isinstance(a, (ast.Subscript, ast.Attribute))
                      and _names(a) & elem]
            used = set().union(*(_names(a) for a in n.args))
            if fields and (used - elem) & varying and _timelike(n):
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
        grown = base.startswith("self.") and base[5:] in self.grown and self.per_sample
        if not grown and any(_window_test(t, elem, varying) for t in _filters(node)):
            ctx = ("loop" if loops else "per_sample" if self.per_sample
                   else "param" if base in self.params or base.startswith("self.") else None)
            if ctx is None:
                return
            self.sites.append(Site(f"{self.rel}::{self.qual}::window_scan", node.lineno,
                                   f"{base} ({ctx})"))
        elif grown:
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
    """ONE scalar query per call -- `bisect`, or `searchsorted` read back as
    `int(...)`, `float(...)` or `.item()` -- over a sequence this call built
    from its arguments or `self`: an index rebuilt for every query.

    A vectorised `np.searchsorted(index, queries)` over an index built once
    in the call is the cure, not the fault, and is not flagged."""
    scalar: set[int] = set()
    for n in _FunctionScan._own_nodes(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) \
                and n.func.id in ("int", "float") and n.args:
            scalar.add(id(n.args[0]))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
                and n.func.attr == "item" and not n.args:
            scalar.add(id(n.func.value))
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
            one = name != "searchsorted" or id(n) in scalar
            if name in INDEX_CALLS and one and isinstance(a0, ast.Name) and a0.id in built:
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
    "reticle/round_lifetimes.py::RoundLifetimes.step::accumulated_scan": {
        "audit": (2,), "cited": "round_lifetimes.py:399",
        "reason": "the same scan: `self.entities` grows all round and each step walks it"},
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
    "reticle/minimap_lifecycle.py::Lifecycle._expire::accumulated_scan": {
        "audit": (9,), "cited": "minimap_lifecycle.py:119",
        "reason": "expires one anchor per observation, not one per entity, and walks "
                  "them again for the live set"},
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
    "reticle/adjudication/ability.py::onset_groups::window_scan",
    "reticle/adjudication/ability.py::predict_ability_births::window_scan",
    "reticle/adjudication/combat_report.py::_killfeed_name::window_scan",
    "reticle/adjudication/combat_report.py::assign_rounds::window_scan",
    "reticle/adjudication/combat_report.py::episodes::window_scan",
    "reticle/adjudication/combat_report.py::name_rows::window_scan",
    "reticle/adjudication/combat_report.py::portrait_clusters::window_scan",
    "reticle/adjudication/combat_report.py::round_counts::window_scan",
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
    "reticle/adjudication/identity.py::_portrait_scores::window_scan",
    "reticle/adjudication/phases.py::candidate_causes::window_scan",
    "reticle/adjudication/smoke_owner.py::circle_runs::window_scan",
    "reticle/adjudication/smoke_owner.py::circle_verdict::window_scan",
    "reticle/adjudication/smoke_owner.py::tray_verdict::window_scan",
    "reticle/adjudication/tray_kit.py::spectated_agent::window_scan",
    "reticle/adjudication/weapon.py::bind_entry::window_scan",
    "reticle/checks.py::merge_split_tracks::window_scan",
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
    "reticle/entity_events.py::EntityEvents.coverage::window_scan",
    "reticle/episodes.py::_attempts::window_scan",
    "reticle/episodes.py::_covering::window_scan",
    "reticle/episodes.py::_duels::window_scan",
    "reticle/episodes.py::_engagements::window_scan",
    "reticle/episodes.py::_rotations::window_scan",
    "reticle/episodes.py::round_at::window_scan",
    "reticle/fidelity.py::score_killfeed::window_scan",
    "reticle/gametime.py::_schedule_at::index_rebuilt",
    "reticle/gametime.py::build_session_gametime::window_scan",
    "reticle/killfeed.py::EntryAnchors.frame::session_query",
    "reticle/killfeed.py::EntryAnchors.frame::window_scan",
    "reticle/menu.py::MenuWitness.at::session_query",
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::accumulated_scan",
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::carried_prior",
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::accumulated_scan",
    "reticle/overlay.py::_state_at::window_scan",
    "reticle/refinement.py::save_refinement::window_scan",
    "reticle/replay_keep.py::overlapping::window_scan",
    "reticle/roi_cache.py::GridPicker._in::window_scan",
    "reticle/round_entities.py::ally_dead_intervals::window_scan",
    "reticle/round_entities.py::drop_binding_refusal::window_scan",
    "reticle/round_entities.py::player_dead_spans::window_scan",
    "reticle/round_lifetimes.py::RoundLifetimes._record_ambiguous_components::accumulated_scan",
    "reticle/round_lifetimes.py::RoundLifetimes.association_for::accumulated_scan",
    "reticle/round_lifetimes.py::seen_after_death::window_scan",
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
    "reticle/track.py::Tracker.principal::window_scan",
    "reticle/tray.py::flag_suspect::window_scan",
    "reticle/tray.py::gold_witness::window_scan",
    "reticle/tray_countdown.py::score_against_returns::window_scan",
    "reticle/view_events.py::Loaded.active::index_rebuilt",
    "reticle/view_events.py::_team_vision::window_scan",
    "reticle/widget_frame.py::WidgetFrame.at::session_query",
    "reticle/widget_frame.py::WidgetFrame.at::window_scan",
    "reticle/widget_frame.py::fit_session::window_scan",
    "reticle/widget_frame.py::round_frames::window_scan",
    "reticle/widget_frame.py::snap_switch::window_scan",
)

#: Every list key when the lists were seeded (2026-10-09, recounted after
#: review the same day): its list and how many distinct lines the detector
#: found in its function. Frozen: never add a key or raise a count.
ROUNDSCOPE_SEED: dict[str, tuple[str, int]] = {
    "reticle/ability_candidates.py::CandidateSupply._alive::session_query": ("UNREVIEWED", 1),
    "reticle/ability_candidates.py::CandidateSupply._alive::window_scan": ("UNREVIEWED", 1),
    "reticle/ability_icons.py::AbilityIconReader.feed::carried_prior": ("LEGACY", 2),
    "reticle/ability_timeline.py::_admit_lined_x::window_scan": ("LEGACY", 1),
    "reticle/ability_timeline.py::_kit_end::window_scan": ("UNREVIEWED", 1),
    "reticle/ability_timeline.py::build_timeline::window_scan": ("UNREVIEWED", 1),
    "reticle/ability_timeline.py::dead_ruse_casts::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/ability.py::onset_groups::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/ability.py::predict_ability_births::window_scan": ("UNREVIEWED", 2),
    "reticle/adjudication/combat_report.py::_killfeed_name::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/combat_report.py::_stat::window_scan": ("LEGACY", 1),
    "reticle/adjudication/combat_report.py::assign_rounds::window_scan": ("UNREVIEWED", 2),
    "reticle/adjudication/combat_report.py::bind_deaths::window_scan": ("LEGACY", 3),
    "reticle/adjudication/combat_report.py::episodes::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/combat_report.py::name_rows::window_scan": ("UNREVIEWED", 3),
    "reticle/adjudication/combat_report.py::portrait_clusters::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/combat_report.py::round_counts::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::_board_interval::window_scan": ("UNREVIEWED", 3),
    "reticle/adjudication/death.py::_match_shrinks::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::_portrait_channel::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::_roster_before::index_rebuilt": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::_score_unread::index_rebuilt": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::adjudicate_round_deaths::window_scan": ("LEGACY", 2),
    "reticle/adjudication/death.py::adjudicate_session_deaths::window_scan": ("LEGACY", 4),
    "reticle/adjudication/death.py::entry_follow_evidence.propose::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::entry_follow_evidence::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::entry_slot_path::window_scan": ("UNREVIEWED", 2),
    "reticle/adjudication/death.py::match_xmark::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::revive_context::window_scan": ("UNREVIEWED", 4),
    "reticle/adjudication/death.py::same_entry::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::second_life_death::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::session_entries::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::split_second_lives::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/death.py::xmark_births::window_scan": ("LEGACY", 4),
    "reticle/adjudication/identity.py::_portrait_scores::window_scan": ("UNREVIEWED", 2),
    "reticle/adjudication/killstreak.py::bind_rows::window_scan": ("LEGACY", 2),
    "reticle/adjudication/phases.py::candidate_causes::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/smoke_owner.py::circle_runs::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/smoke_owner.py::circle_verdict::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/smoke_owner.py::tray_verdict::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/spike_carrier.py::check::window_scan": ("LEGACY", 4),
    "reticle/adjudication/tray_kit.py::spectated_agent::window_scan": ("UNREVIEWED", 1),
    "reticle/adjudication/weapon.py::bind_entry::window_scan": ("UNREVIEWED", 1),
    "reticle/checks.py::merge_split_tracks::window_scan": ("UNREVIEWED", 1),
    "reticle/cli.py::_MinimapPass.feed::carried_prior": ("UNREVIEWED", 1),
    "reticle/cli.py::_tray_kit_values::window_scan": ("UNREVIEWED", 1),
    "reticle/cli.py::cmd_kd::window_scan": ("UNREVIEWED", 2),
    "reticle/clove_circle.py::CloveCircleReader._window_of::window_scan": ("LEGACY", 1),
    "reticle/clove_circle.py::opportunity_windows::window_scan": ("UNREVIEWED", 2),
    "reticle/clove_circle.py::self_position_at::index_rebuilt": ("LEGACY", 1),
    "reticle/coaching.py::attach_event_estimates::window_scan": ("UNREVIEWED", 1),
    "reticle/combat_report.py::read_flag::window_scan": ("UNREVIEWED", 1),
    "reticle/decode.py::windows_of::window_scan": ("UNREVIEWED", 1),
    "reticle/dev_sample.py::new_targets::window_scan": ("UNREVIEWED", 1),
    "reticle/dev_sample.py::opportunity_rounds::window_scan": ("UNREVIEWED", 1),
    "reticle/economy.py::EconomyTracker.reset_period::session_query": ("UNREVIEWED", 1),
    "reticle/enemy_tracks.py::build::window_scan": ("LEGACY", 2),
    "reticle/entity_events.py::EntityEvents.coverage::session_query": ("LEGACY", 1),
    "reticle/entity_events.py::EntityEvents.coverage::window_scan": ("UNREVIEWED", 1),
    "reticle/entity_events.py::EntityEvents.entities::session_query": ("LEGACY", 1),
    "reticle/entity_events.py::EntityEvents.events::session_query": ("LEGACY", 1),
    "reticle/entity_events.py::EntityEvents.ledger::session_query": ("LEGACY", 1),
    "reticle/episodes.py::_attempts::window_scan": ("UNREVIEWED", 5),
    "reticle/episodes.py::_covering::window_scan": ("UNREVIEWED", 1),
    "reticle/episodes.py::_duels::window_scan": ("UNREVIEWED", 1),
    "reticle/episodes.py::_engagements::window_scan": ("UNREVIEWED", 2),
    "reticle/episodes.py::_rotations::window_scan": ("UNREVIEWED", 1),
    "reticle/episodes.py::round_at::window_scan": ("UNREVIEWED", 1),
    "reticle/fidelity.py::score_killfeed::window_scan": ("UNREVIEWED", 3),
    "reticle/gametime.py::_schedule_at::index_rebuilt": ("UNREVIEWED", 1),
    "reticle/gametime.py::build_session_gametime::window_scan": ("UNREVIEWED", 1),
    "reticle/killfeed.py::EntryAnchors.frame::session_query": ("UNREVIEWED", 1),
    "reticle/killfeed.py::EntryAnchors.frame::window_scan": ("UNREVIEWED", 1),
    "reticle/menu.py::MenuWitness.at::session_query": ("UNREVIEWED", 1),
    "reticle/minimap.py::AllyIconReader._stack::accumulated_scan": ("LEGACY", 1),
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::accumulated_scan": ("UNREVIEWED", 1),
    "reticle/minimap_glyph.py::AbilityGlyphReader._end_all::carried_prior": ("UNREVIEWED", 1),
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::accumulated_scan": ("UNREVIEWED", 3),
    "reticle/minimap_glyph.py::AbilityGlyphReader.feed::carried_prior": ("LEGACY", 1),
    "reticle/minimap_lifecycle.py::Lifecycle._expire::accumulated_scan": ("LEGACY", 3),
    "reticle/minimap_lifecycle.py::Lifecycle._expire::session_query": ("LEGACY", 1),
    "reticle/minimap_lifecycle.py::Lifecycle.step::accumulated_scan": ("LEGACY", 3),
    "reticle/minimap_lifecycle.py::matching_events::window_scan": ("LEGACY", 1),
    "reticle/overlay.py::_state_at::window_scan": ("UNREVIEWED", 1),
    "reticle/ping.py::resolve::window_scan": ("LEGACY", 1),
    "reticle/primitives.py::PrimitiveExtractor.process::carried_prior": ("BOUNDED", 2),
    "reticle/primitives.py::PrimitiveExtractor.process::session_query": ("BOUNDED", 1),
    "reticle/refinement.py::save_refinement::window_scan": ("UNREVIEWED", 1),
    "reticle/replay_keep.py::overlapping::window_scan": ("UNREVIEWED", 1),
    "reticle/roi_cache.py::GridPicker._in::window_scan": ("UNREVIEWED", 1),
    "reticle/round_entities.py::ally_dead_intervals::window_scan": ("UNREVIEWED", 1),
    "reticle/round_entities.py::drop_binding_refusal::window_scan": ("UNREVIEWED", 1),
    "reticle/round_entities.py::player_dead_spans::window_scan": ("UNREVIEWED", 1),
    "reticle/round_entities.py::session_lifetimes::window_scan": ("LEGACY", 1),
    "reticle/round_lifetimes.py::RoundLifetimes._record_ambiguous_components::accumulated_scan": ("UNREVIEWED", 1),
    "reticle/round_lifetimes.py::RoundLifetimes.association_for::accumulated_scan": ("UNREVIEWED", 1),
    "reticle/round_lifetimes.py::RoundLifetimes.step::accumulated_scan": ("LEGACY", 1),
    "reticle/round_lifetimes.py::RoundLifetimes.step::session_query": ("LEGACY", 1),
    "reticle/round_lifetimes.py::RoundLifetimes.step::window_scan": ("LEGACY", 1),
    "reticle/round_lifetimes.py::seen_after_death::window_scan": ("UNREVIEWED", 1),
    "reticle/round_outcome.py::fit_columns::window_scan": ("UNREVIEWED", 1),
    "reticle/round_view.py::_timeline_strip::window_scan": ("UNREVIEWED", 1),
    "reticle/rounds.py::_reset_after::index_rebuilt": ("UNREVIEWED", 2),
    "reticle/rounds.py::build_rounds::window_scan": ("UNREVIEWED", 1),
    "reticle/rounds.py::in_round_window::window_scan": ("UNREVIEWED", 1),
    "reticle/rounds.py::round_containing::window_scan": ("UNREVIEWED", 1),
    "reticle/self_icon.py::all_alive::index_rebuilt": ("UNREVIEWED", 1),
    "reticle/stalls.py::spans::window_scan": ("UNREVIEWED", 1),
    "reticle/stalls.py::stalled_at::index_rebuilt": ("LEGACY", 1),
    "reticle/teardrop.py::IconPoseReader.read::accumulated_scan": ("LEGACY", 1),
    "reticle/teardrop.py::IconPoseReader.read::carried_prior": ("LEGACY", 1),
    "reticle/teardrop.py::IconPoseReader.read::session_query": ("LEGACY", 1),
    "reticle/tiers.py::check_omen_smokes::window_scan": ("UNREVIEWED", 2),
    "reticle/track.py::Track.resolved_facing::window_scan": ("UNREVIEWED", 1),
    "reticle/track.py::Tracker.principal::window_scan": ("UNREVIEWED", 1),
    "reticle/track.py::Tracker.step::session_query": ("BOUNDED", 1),
    "reticle/track.py::Tracker.step::window_scan": ("BOUNDED", 1),
    "reticle/tray.py::flag_suspect::window_scan": ("UNREVIEWED", 1),
    "reticle/tray.py::gold_witness::window_scan": ("UNREVIEWED", 1),
    "reticle/tray_countdown.py::score_against_returns::window_scan": ("UNREVIEWED", 1),
    "reticle/view_events.py::Loaded.active::index_rebuilt": ("UNREVIEWED", 2),
    "reticle/view_events.py::_team_vision::window_scan": ("UNREVIEWED", 1),
    "reticle/widget_frame.py::WidgetFrame.at::session_query": ("UNREVIEWED", 1),
    "reticle/widget_frame.py::WidgetFrame.at::window_scan": ("UNREVIEWED", 1),
    "reticle/widget_frame.py::fit_session::window_scan": ("UNREVIEWED", 1),
    "reticle/widget_frame.py::round_frames::window_scan": ("UNREVIEWED", 1),
    "reticle/widget_frame.py::snap_switch::window_scan": ("UNREVIEWED", 1),
}


def roundscope_findings(base: Path | None = None, legacy: dict | None = None,
                        bounded: dict | None = None, unreviewed=None,
                        seed: dict | None = None, files=None) -> list[tuple[str, str]]:
    """ROUNDSCOPE: state outlives a round, or a search walks past the
    could-overlap set.

    A site no list names is an ERROR. An audited legacy site is a WARN with its
    case, citation and reason; the unreviewed sites are one WARN that counts
    them by module; a bounded site is silent.

    Every list is held to `ROUNDSCOPE_SEED`, frozen when the lists were
    seeded: a key outside the seed, or listed in another list than the seed
    put it in, is an ERROR, so no list grows or trades entries. A site key
    names a function, so the seed also freezes how many distinct lines each
    listed function holds: one more is a new site inside a listed function,
    an ERROR; one fewer is a fix, and the seed's count must come down with
    it. A list key whose site the detector no longer finds is an ERROR until
    the key goes. The detector is a heuristic (`roundscope_sites`); it must
    find every audited case, which `tests/test_ratchets.py` checks.
    """
    legacy = ROUNDSCOPE_LEGACY if legacy is None else legacy
    bounded = ROUNDSCOPE_BOUNDED if bounded is None else bounded
    unreviewed = set(ROUNDSCOPE_UNREVIEWED if unreviewed is None else unreviewed)
    seed = ROUNDSCOPE_SEED if seed is None else seed
    lines: dict[str, set[int]] = {}
    for s in roundscope_sites(base, files=files):
        lines.setdefault(s.key, set()).add(s.line)
    lists = {"LEGACY": set(legacy), "BOUNDED": set(bounded), "UNREVIEWED": unreviewed}
    out = []
    pending = []
    for key in sorted(lines):
        at = ", ".join(str(x) for x in sorted(lines[key]))
        if key in legacy:
            e = legacy[key]
            cases = ", ".join(f"#{c}" for c in e["audit"])
            out.append((WARN, f"legacy `{key}` (lines {at}; audit {cases}, {e['cited']}): "
                              f"{e['reason']}"))
        elif key in bounded:
            pass
        elif key in unreviewed:
            pending.append(key)
        else:
            out.append((ERROR, f"`{key}` (lines {at}) holds state past a round or searches "
                               "past the could-overlap set -- scope it to the round or slice "
                               "by sorted time; never a new allowlist entry"))
            continue
        frozen = seed.get(key)
        if frozen is not None and len(lines[key]) > frozen[1]:
            out.append((ERROR, f"`{key}` holds {len(lines[key])} sites (lines {at}); the seed "
                               f"froze {frozen[1]} -- a new site inside a listed function"))
        elif frozen is not None and len(lines[key]) < frozen[1]:
            out.append((ERROR, f"`{key}` holds {len(lines[key])} sites, the seed {frozen[1]} -- "
                               f"lower ROUNDSCOPE_SEED's count to {len(lines[key])}"))
    if pending:
        mods = sorted({k.split("::")[0] for k in pending})
        out.append((WARN, f"{len(pending)} unreviewed legacy sites (found 2026-10-09, outside "
                          f"the audit) in {len(mods)} modules: "
                          + ", ".join(m.removeprefix("reticle/") for m in mods)))
    for name, keys in lists.items():
        for key in sorted(keys):
            frozen = seed.get(key)
            if frozen is None:
                out.append((ERROR, f"ROUNDSCOPE_{name} names `{key}`, outside the frozen "
                                   "ROUNDSCOPE_SEED -- the allowlists only shrink"))
            elif frozen[0] != name and not (frozen[0] == "UNREVIEWED" and name == "BOUNDED"):
                # Review may judge an unreviewed site bounded; nothing else moves.
                out.append((ERROR, f"ROUNDSCOPE_{name} names `{key}`, which the seed put in "
                                   f"ROUNDSCOPE_{frozen[0]}"))
        for key in sorted(keys - set(lines)):
            out.append((ERROR, f"ROUNDSCOPE_{name} names `{key}`, which the detector no longer "
                               "finds -- remove it from the allowlist"))
    return out


# ---------------------------------------------------------------------------
# PROMOTE strict: a passed pilot meant for production is wired or scheduled
# ---------------------------------------------------------------------------

#: Ledger row kinds that record a result rather than a prediction.
RESULT_KINDS = frozenset({"outcome", "prediction_outcome", "decision", "wire_decision",
                          "promotion"})
#: `wire` values that mean the result is meant for production.
WIRE_INTENT = frozenset({"yes", "pending"})
RETICLE_MODULE = re.compile(r"\breticle[/.]((?:adjudication[/.])?\w+)")
BACKLOG_ITEM = re.compile(r"\bBACKLOG\s+(\d+)\b")

#: Passed pilots meant for production that were neither wired, scheduled nor
#: declined when the strict check landed, 2026-10-09, once a mention in a
#: comment stopped counting as wiring. (`ability_disc` and `mine_icons` passed,
#: and later rows with their subject declined them.) An entry names a stem and
#: why it waits; it goes when the pilot is wired or a ledger row schedules it.
PROMOTE_LEGACY: dict[str, str] = {
    "icon_teardrop": "decision row, wire yes (2026-09-29): ported as reticle/teardrop.py "
                     "under another name; no import, call or `wired_by` row records it",
    "proposal_audit": "outcome row, wire yes, subject with mine_icons (2026-09-10): the change "
                      "landed in the prototype tools; later rows decline mine_icons only",
}
#: PROMOTE_LEGACY's keys when seeded. Frozen: the list only shrinks.
PROMOTE_SEED: frozenset[str] = frozenset({"icon_teardrop", "proposal_audit"})


def _mentions(stems: set[str], text: str) -> set[str]:
    return stems.intersection(re.findall(r"\w+", text))


def _named(stems: set[str], row: dict) -> set[str]:
    """The prototypes a row names in its `prototype`, `subject` and `also`
    fields; never its prose."""
    also = row.get("also") or []
    text = " ".join([str(row.get("prototype") or ""), str(row.get("subject") or "")]
                    + [str(x) for x in (also if isinstance(also, list) else [also])])
    return _mentions(stems, text)


def passed_pilots(rows: list[dict], stems: set[str]) -> dict[str, list[dict]]:
    """Prototype stem -> the ledger rows that record a result with `wire`
    "yes" or "pending": a pilot that passed and is meant for production.

    A row names its prototypes in its `prototype`, `subject` and `also`
    fields; a row whose fields name none names nothing, whatever its prose
    mentions.
    """
    out: dict[str, list[dict]] = {}
    for r in rows:
        if r.get("kind") not in RESULT_KINDS:
            continue
        if str(r.get("wire", "")).lower() not in WIRE_INTENT:
            continue
        for s in _named(stems, r):
            out.setdefault(s, []).append(r)
    return out


def promote_strict(rows: list[dict], stems: set[str], used: set[str],
                   modules: set[str], open_items: set[int],
                   legacy: dict | None = None,
                   seed: frozenset | None = None) -> tuple[list[tuple[str, str]], list[str]]:
    """PROMOTE strict: `(findings, unwired)` for the passed pilots.

    A passed pilot is wired when a `reticle/` module imports or calls it
    (`used`; a comment or docstring naming it is no wiring), when its result
    row's `wire_reason` names an existing `reticle` module (`modules`, dotted
    names) that took it over, or when a row naming it carries a `wired_by`
    module path (`"reticle/slot_state.py ..."`) that exists. It is scheduled
    when such a row's `wired_by` names an open item, `"BACKLOG <n>"`. A
    `wired_by` module this tree lacks is a WARN: the promotion lives on a
    branch not merged here. A row names a pilot in its `prototype`, `subject`
    or `also` field only; prose names nothing. A `"wire": "no"` row declines
    it only when it comes after the pilot's last passing row and names it.

    Anything else is an ERROR, or a WARN where `PROMOTE_LEGACY` lists it; a
    listed pilot now wired, scheduled or declined is an ERROR until its entry
    goes, and a listed stem outside the frozen `PROMOTE_SEED` is an ERROR. The
    loopholes this closes: the loose check only warned, so a result row saying
    "wire: yes" could sit unwired with no item named for it; a decline
    without a subject retired every prototype its prose mentioned; a mention
    in a comment counted as wiring. `unwired` lists the passed pilots neither
    wired nor declined, scheduled ones with their item, for `status`.
    """
    legacy = PROMOTE_LEGACY if legacy is None else legacy
    seed = PROMOTE_SEED if seed is None else seed
    pilots = passed_pilots(rows, stems)
    last_pass = {s: max(i for i, r in enumerate(rows) if any(r is p for p in ps))
                 for s, ps in pilots.items()}
    declined: set[str] = set()
    scheduled: dict[str, str] = {}
    wired_by: set[str] = set()
    absent: dict[str, str] = {}
    bad_item: dict[str, str] = {}
    for i, r in enumerate(rows):
        named = _named(stems, r)
        if str(r.get("wire", "")).lower() == "no":
            declined |= {s for s in named if i > last_pass.get(s, -1)}
        if not r.get("wired_by"):
            continue
        how = str(r["wired_by"])
        item = BACKLOG_ITEM.search(how)
        mods = {m.group(1).replace("/", ".") for m in RETICLE_MODULE.finditer(how)}
        for s in named:
            if mods & modules:
                wired_by.add(s)
            elif mods:
                absent[s] = how
            elif item and int(item.group(1)) in open_items:
                scheduled[s] = f"BACKLOG {item.group(1)}"
            else:
                bad_item[s] = how
    out, unwired = [], []
    for s in sorted(pilots):
        if s in declined:
            continue
        # The module that took it over, named in the result's reason or in
        # its subject (`reticle/adjudication/identity.py load_identity_gallery`).
        reasons = " ".join(str(r.get(k) or "") for r in pilots[s]
                           for k in ("wire_reason", "subject"))
        took = {m.group(1).replace("/", ".") for m in RETICLE_MODULE.finditer(reasons)}
        if s in used or s in wired_by or took & modules:
            continue
        if s in scheduled:
            unwired.append(f"{s} ({scheduled[s]})")
            continue
        if s in absent:
            unwired.append(f"{s} ({absent[s].split()[0]}, not in this tree)")
            out.append((WARN, f"`prototypes/{s}.py` is wired by `{absent[s]}`, a module this "
                              "tree lacks -- merge the branch that promotes it"))
            continue
        unwired.append(s)
        tag = str(pilots[s][0].get("id") or pilots[s][0].get("date")
                  or pilots[s][0].get("ts") or "")[:40]
        if s in bad_item:
            out.append((ERROR, f"`prototypes/{s}.py` names `{bad_item[s]}` as its wiring, "
                               "which is neither an open BACKLOG item nor a reticle module"))
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
    for s in sorted(set(legacy) - set(seed)):
        out.append((ERROR, f"PROMOTE_LEGACY names `{s}`, outside the frozen PROMOTE_SEED -- "
                           "the allowlist only shrinks"))
    return out, unwired


# ---------------------------------------------------------------------------
# ABILITY: every ability fragment is a declared input of the child owner
# ---------------------------------------------------------------------------

#: A stream the store's registry declares is an ability stream when its name
#: says so; retired streams are evidence no command writes, and are skipped.
ABILITY_STREAM = re.compile(r"^(ability_\w+|smoke\w*|ult_\w+|tray_\w+|clove_\w+|dead_ruse\w*"
                            r"|minimap_dark)$")
#: An ownership entry whose id says ability must carry `entity_kind`, so an
#: ability entry cannot escape the check by omitting the tag.
ABILITY_ENTRY = re.compile(r"(^|-)(ability|smoke|ult|tray|glyph|clove|ruse)(-|$)")
#: The tag that puts an ownership entry under ABILITY.
ABILITY_KIND = "ability"
#: Where a legacy entry's `step` points: a migration step that is still to run.
ABILITY_STEP = re.compile(r"^step [2-7]\b")
#: What a `CHANNELS` row declares.
CHANNEL_FIELDS = ("witness", "parent", "wired", "owners", "readers", "streams", "feeds", "opens", "joins",
                  "ends", "kind", "agent_claim", "position", "effect")

#: Ability entries the plan keeps apart from the child owner by design, and
#: why: development tools and replay truth, never a witness (section 1.2 and
#: 1.4). Not a debt and not an input; `doctor` errors if one becomes a
#: `CHANNELS` entry or stops being an entry.
ABILITY_APART: dict[str, str] = {
    "capture-queue": "a development tool for demo captures (section 1.2)",
    "ability-evidence": "a development inventory of stored evidence (section 1.2)",
    "replay-ability-actors": "replay truth, never a reader input (section 1.4)",
    "ability-mechanics-sheet": "a domain-fact confirmation tool: pre-fills from game files, "
                               "asks the player and imports into domain/*.toml; facts, never "
                               "observation evidence",
}
#: ABILITY_APART's keys when seeded, 2026-10-09. Frozen: a key outside it is
#: an ERROR, so no entry escapes ABILITY by being declared apart. Seed changes
#: are deliberate: `ability-mechanics-sheet` joined 2026-10-09, when the
#: mechanics-sheet branches merged beside step 1.
ABILITY_APART_SEED: frozenset[str] = frozenset({
    "capture-queue", "ability-evidence", "replay-ability-actors", "ability-mechanics-sheet"})

#: Every ability fragment outside `slot_state.CHANNELS` and the child owner on
#: 2026-10-09 (docs/ABILITY_ENTITIES.md section 1), found by
#: `ability_findings` over the store's stream registry (`plan`), the entity
#: lanes (`entity_events.ENTITY_LANES`) and `ownership.toml`, plus the code the
#: plan retires by name. Keys: `stream:<name>`, `lane:<name>`, `entry:<id>`,
#: `code:<path>::<name>`. Each names its fate and the step that clears it;
#: remove an entry in the commit that clears its fragment.
ABILITY_LEGACY: dict[str, dict[str, str]] = {
    "stream:ability_light": {
        "fate": "retires with milestone C, beside `light_refusals` and `reticle ability-light`",
        "step": "step 3"},
    "stream:ability_shape_audit": {
        "fate": "the gate's 2 Hz audit rows, read by prototypes only; merges into the gated fits",
        "step": "step 6"},
    "stream:ability_shape_scan": {
        "fate": "the gate's 2 Hz scan rows, read by prototypes only; merges into the gated fits",
        "step": "step 6"},
    "stream:tray_countdown": {
        "fate": "a reader of the kit owner; nothing reads it until kits cover every slot",
        "step": "step 5"},
    "lane:smoke": {
        "fate": "declared, never projected; folds into the one `ability` lane",
        "step": "step 3"},
    "lane:ult_cast": {
        "fate": "declared, never projected; folds into the one `ability` lane",
        "step": "step 3"},
    "entry:ability-appearance": {
        "fate": "the gallery's classifier retires; the game-texture glyph reader replaced it",
        "step": "step 3"},
    "entry:ability-detection": {
        "fate": "`minimap.detect_ability_*` retire; `ability_icons` and `ability_shapes` "
                "replaced them",
        "step": "step 3"},
    "entry:ability-hypothesis": {
        "fate": "milestone C (`build_entities` and the grouping rules) retires",
        "step": "step 3"},
    "entry:ability-phase": {
        "fate": "`adjudication.phases` retires; its two structural rules become the child "
                "owner's tests",
        "step": "step 3"},
    "entry:drawn-light": {
        "fate": "kept until its consumer `light_refusals` retires with milestone C",
        "step": "step 3"},
    "entry:tray-restock-countdown": {
        "fate": "a reader of the kit owner; nothing reads it until kits cover every slot",
        "step": "step 5"},
    "code:reticle/ability_timeline.py::build_timeline": {
        "fate": "the `ability-timeline` bundle retires with milestone C",
        "step": "step 3"},
    "code:reticle/adjudication/ability.py::light_refusals": {
        "fate": "retires with milestone C and `ability_light`",
        "step": "step 3"},
    "code:reticle/adjudication/ability.py::predict_ability_births": {
        "fate": "retires with milestone C; its category gate is a rule by analogy",
        "step": "step 3"},
    "code:reticle/adjudication/ability_glyph.py::glyph_placement": {
        "fate": "`detection_reality` asks the child owner in its place, so a child of any "
                "channel explains a find",
        "step": "step 4"},
    "code:reticle/adjudication/ult_cast.py::player_x_drops": {
        "fate": "binding an own ult line to its X drop moved to the child owner in step 2; "
                "the function stays while `ult_cast` selects a sub-threshold peak an X cast "
                "witnesses (`tray_x_cast`), a selection rule whose move changes `ult_cast` "
                "itself",
        "step": "step 3"},
}

#: ABILITY_LEGACY's keys when seeded, 2026-10-09. Frozen: doctor errors on a
#: key outside it, so the list cannot grow by an edit that adds one entry and
#: drops another. `status` counts a seed key no longer in the list as cleared:
#: step 2 (2026-10-09) cleared `stream:dead_ruse_cast` and `smoke_owner.cast_links`.
ABILITY_SEED: frozenset[str] = frozenset({
    "stream:ability_light", "stream:ability_shape_audit", "stream:ability_shape_scan",
    "stream:dead_ruse_cast", "stream:tray_countdown",
    "lane:smoke", "lane:ult_cast",
    "entry:ability-appearance", "entry:ability-detection", "entry:ability-hypothesis",
    "entry:ability-phase", "entry:drawn-light", "entry:tray-restock-countdown",
    "code:reticle/ability_timeline.py::build_timeline",
    "code:reticle/adjudication/ability.py::light_refusals",
    "code:reticle/adjudication/ability.py::predict_ability_births",
    "code:reticle/adjudication/ability_glyph.py::glyph_placement",
    "code:reticle/adjudication/smoke_owner.py::cast_links",
    "code:reticle/adjudication/ult_cast.py::player_x_drops",
})


@dataclass(frozen=True)
class AbilityInputs:
    """What ABILITY reads, gathered by `doctor.check_ability` so this module
    imports nothing above the foundation.

    `channels`, `lanes_declared`, `child_owner` and `child_entries` are the
    child owner's declaration (`slot_state.CHANNELS`, `ABILITY_LANES`, the
    module name, `ABILITY_ENTRIES`); `streams` the store's stream registry
    (`plan`'s declared streams) and `retired` its retired streams; `lanes` the
    entity lanes as `{lane: inputs}`; `entries` the ownership entries by id.
    """

    channels: tuple
    lanes_declared: frozenset
    child_owner: str
    child_entries: tuple
    streams: frozenset
    retired: frozenset
    lanes: dict
    entries: dict
    #: The streams the child owner writes (`slot_state.ABILITY_STREAMS`): its
    #: own output, never an input `CHANNELS` must list.
    child_streams: tuple = ()


def _listed(entry: dict, field: str) -> list[str]:
    value = entry.get(field, [])
    return [value] if isinstance(value, str) else list(value)


def _code_exists(key: str, base: Path) -> bool:
    """Does `code:<path>::<name>` still define `<name>` at its module's top level?"""
    rel, _, name = key[len("code:"):].partition("::")
    tree = _parse_source(base / rel) if (base / rel).is_file() else None
    return tree is not None and any(
        isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == name
        for n in tree.body)


def ability_streams(inputs: AbilityInputs) -> list[str]:
    """The registry's ability streams, by `ABILITY_STREAM`, retired ones aside."""
    return sorted(s for s in inputs.streams - inputs.retired if ABILITY_STREAM.match(s))


def ability_lanes(inputs: AbilityInputs) -> list[str]:
    """Entity lanes that carry ability evidence: an ability name, or an
    ability stream among their inputs."""
    return sorted(lane for lane, ins in inputs.lanes.items()
                  if ABILITY_STREAM.match(lane) or lane in inputs.lanes_declared
                  or any(ABILITY_STREAM.match(s) for s in ins))


def ability_findings(inputs: AbilityInputs, legacy: dict | None = None,
                     seed: frozenset | None = None, apart: dict | None = None,
                     base: Path | None = None,
                     apart_seed: frozenset | None = None) -> list[tuple[str, str]]:
    """ABILITY: every ability stream, lane and ownership entry is a declared
    input of the child owner (docs/ABILITY_ENTITIES.md section 4).

    A fragment is accounted for when `slot_state.CHANNELS` names it (a row's
    `streams`, `owners` or `readers`), when the child owner holds it (its
    entries and `ABILITY_LANES`), or, for an entry, when `ABILITY_APART`
    keeps it apart. Anything else is an ERROR, or a WARN where
    `ABILITY_LEGACY` lists it with its fate and step. Fragments come from the
    store's stream registry (`ABILITY_STREAM` over `plan`'s declared streams),
    the entity lanes, and the ownership entries tagged `entity_kind =
    "ability"`; an entry whose id says ability and carries no `entity_kind` is
    an ERROR.

    The declaration is checked too: a `CHANNELS` row naming a stream the
    registry lacks, or an entry that is none or is untagged, or an owner that
    does not declare the row's `feeds`, is an ERROR, as is a `feeds` naming
    no entry or from an entry no row names as an owner. A legacy entry whose
    fragment is gone or now accounted for is an ERROR until it goes, and a
    legacy key outside the frozen `ABILITY_SEED` is an ERROR, so the list only
    shrinks.
    """
    legacy = ABILITY_LEGACY if legacy is None else legacy
    seed = ABILITY_SEED if seed is None else seed
    apart = ABILITY_APART if apart is None else apart
    apart_seed = ABILITY_APART_SEED if apart_seed is None else apart_seed
    base = ROOT if base is None else base
    entries = inputs.entries
    out: list[tuple[str, str]] = []

    # The declaration: every row well formed, every name resolvable.
    ch_streams: set[str] = set()
    ch_entries: set[str] = set()
    ch_owners: dict[str, set[str]] = {}
    for i, row in enumerate(inputs.channels):
        where = f"CHANNELS row {i} (`{row.get('witness', '?')}`)"
        missing = [f for f in CHANNEL_FIELDS if f not in row]
        extra = sorted(set(row) - set(CHANNEL_FIELDS))
        if missing or extra:
            out.append((ERROR, f"{where} lacks {missing} or holds {extra}; a row declares "
                               f"{', '.join(CHANNEL_FIELDS)}"))
            continue
        if not (row["opens"] or row["joins"] or row["ends"]):
            out.append((ERROR, f"{where} may neither open, join nor end a child"))
        if not row["wired"] and (row["owners"] or row["streams"]):
            out.append((ERROR, f"{where} is unwired and names owners or streams"))
        if row["wired"] and not row["owners"]:
            out.append((ERROR, f"{where} is wired and names no owner"))
        for s in row["streams"]:
            ch_streams.add(s)
            if s not in inputs.streams:
                out.append((ERROR, f"{where} names stream `{s}`, which the store's stream "
                                   "registry (`plan`) does not declare"))
            elif s in inputs.retired:
                out.append((ERROR, f"{where} names stream `{s}`, which is retired"))
        for f in row["feeds"]:
            if f not in inputs.child_entries:
                out.append((ERROR, f"{where} feeds `{f}`, which is not the child owner's"))
        for key in tuple(row["owners"]) + tuple(row["readers"]):
            ch_entries.add(key)
            e = entries.get(key)
            if e is None:
                out.append((ERROR, f"{where} names `{key}`, which is no ownership entry"))
            elif e.get("entity_kind") != ABILITY_KIND:
                out.append((ERROR, f"{where} names `{key}`, whose ownership entry does not "
                                   f"declare entity_kind = \"{ABILITY_KIND}\""))
        for key in row["owners"]:
            ch_owners.setdefault(key, set()).update(row["feeds"])
    for key, feeds in sorted(ch_owners.items()):
        e = entries.get(key)
        if e is not None and not feeds <= set(_listed(e, "feeds")):
            out.append((ERROR, f"ownership.toml [{key}] feeds the child owner through CHANNELS "
                               f"and declares feeds = {_listed(e, 'feeds')}, not "
                               f"{sorted(feeds)}"))

    # The child owner's own entries.
    for key in inputs.child_entries:
        e = entries.get(key)
        if e is None:
            out.append((ERROR, f"the child owner's entry `{key}` is not in ownership.toml"))
        elif e.get("entity_kind") != ABILITY_KIND:
            out.append((ERROR, f"ownership.toml [{key}] is the child owner's and does not "
                               f"declare entity_kind = \"{ABILITY_KIND}\""))

    # Ownership entries.
    accounted: set[str] = set()
    for key in sorted(entries):
        e = entries[key]
        tagged = e.get("entity_kind") == ABILITY_KIND
        for f in _listed(e, "feeds"):
            if f not in entries:
                out.append((ERROR, f"ownership.toml [{key}] feeds `{f}`, which is no entry"))
        if _listed(e, "feeds") and key not in ch_owners:
            out.append((ERROR, f"ownership.toml [{key}] declares feeds and no CHANNELS row "
                               "names it as an owner"))
        if not tagged:
            if ABILITY_ENTRY.search(key):
                out.append((ERROR, f"ownership.toml [{key}] reads as ability evidence and "
                                   f"does not declare entity_kind = \"{ABILITY_KIND}\""))
            continue
        if str(e.get("owner", "")) == inputs.child_owner and key in inputs.child_entries:
            accounted.add(f"entry:{key}")
        elif key in ch_entries:
            accounted.add(f"entry:{key}")
            if key in apart:
                out.append((ERROR, f"`{key}` is both kept apart (ABILITY_APART) and named "
                                   "by CHANNELS"))
        elif key in apart:
            accounted.add(f"entry:{key}")
        elif f"entry:{key}" in legacy:
            pass
        else:
            out.append((ERROR, f"ownership.toml [{key}] is ability evidence outside CHANNELS "
                               "and the child owner -- declare it a CHANNELS input, never a "
                               "new ABILITY_LEGACY entry"))
    for key in sorted(apart):
        if key not in entries:
            out.append((ERROR, f"ABILITY_APART names `{key}`, which is no ownership entry"))
    for key in sorted(set(apart) - set(apart_seed)):
        out.append((ERROR, f"ABILITY_APART names `{key}`, outside the frozen ABILITY_APART_SEED "
                           "-- declare it a CHANNELS input instead"))

    # Streams and lanes.
    found: set[str] = {f"entry:{k}" for k, e in entries.items()
                       if e.get("entity_kind") == ABILITY_KIND}
    for s in ability_streams(inputs):
        found.add(f"stream:{s}")
        if s in ch_streams or s in inputs.child_streams:
            accounted.add(f"stream:{s}")
        elif f"stream:{s}" not in legacy:
            out.append((ERROR, f"stream `{s}` is ability evidence outside CHANNELS -- "
                               "declare it a CHANNELS input, never a new ABILITY_LEGACY entry"))
    for lane in ability_lanes(inputs):
        found.add(f"lane:{lane}")
        if lane in inputs.lanes_declared:
            accounted.add(f"lane:{lane}")
        elif f"lane:{lane}" not in legacy:
            out.append((ERROR, f"entity lane `{lane}` carries ability evidence outside the "
                               "child owner's lanes (`ability`, `ability_tray`)"))

    # The legacy list: warn per live entry, error on a stale one.
    for key in sorted(legacy):
        e = legacy[key]
        if not ABILITY_STEP.match(str(e.get("step", ""))) or not e.get("fate"):
            out.append((ERROR, f"ABILITY_LEGACY `{key}` names no fate or no step 2-7 that "
                               "clears it"))
        if key.startswith("code:"):
            live = _code_exists(key, base)
        else:
            live = key in found and key not in accounted
        if not live:
            out.append((ERROR, f"ABILITY_LEGACY names `{key}`, which is gone or now a declared "
                               "input -- remove it from the allowlist"))
        else:
            out.append((WARN, f"legacy ability fragment `{key}`: {e.get('fate')}; clears in "
                              f"{e.get('step')} (docs/ABILITY_ENTITIES.md)"))
    for key in sorted(set(legacy) - set(seed)):
        out.append((ERROR, f"ABILITY_LEGACY names `{key}`, outside the frozen ABILITY_SEED -- "
                           "the allowlist only shrinks"))
    return out


def ability_progress(legacy: dict | None = None, seed: frozenset | None = None) -> dict:
    """ABILITY's progress against its seed, and the open entries per step."""
    legacy = ABILITY_LEGACY if legacy is None else legacy
    seed = ABILITY_SEED if seed is None else seed
    steps: dict[str, int] = {}
    for e in legacy.values():
        steps[e["step"]] = steps.get(e["step"], 0) + 1
    return {"cleared": len(seed - set(legacy)), "legacy": len(legacy),
            "steps": dict(sorted(steps.items()))}


def ability_progress_line(p: dict) -> str:
    """`status`'s ability conversion line."""
    per = ", ".join(f"{s}: {n}" for s, n in p["steps"].items()) or "none"
    return (f"Ability entities (docs/ABILITY_ENTITIES.md): ABILITY {p['cleared']} cleared / "
            f"{p['legacy']} legacy fragments ({per}).")


# ---------------------------------------------------------------------------
# KINDS: every entity kind the slot owner declares, its builder builds
# ---------------------------------------------------------------------------

#: The slot owner, the function that builds its entity axis, and the one
#: that builds its ability children and effects (docs/ABILITY_ENTITIES.md
#: step 2). A builder's kinds are those of its `EntityRow(...)` calls and of
#: its row literals' `"entity_kind": KIND_<X>`.
KINDS_MODULE = "reticle/slot_state.py"
KINDS_BUILDER = "build_slots"
KINDS_BUILDERS = (KINDS_BUILDER, "build_abilities")
#: The slot owner's constant naming the sides its ability builder builds.
KINDS_SIDES_CONSTANT = "ABILITY_SIDES_BUILT"
#: A module-level constant that declares an entity kind.
KIND_CONSTANT = re.compile(r"^KIND_[A-Z0-9_]+$")

#: Entity kinds `slot_state` declares and `build_slots` did not build when
#: the check landed, 2026-10-09 (task enemy-slots-20261009, after the enemy
#: player slots joined), each with the plan step that builds it. An entry
#: goes when the builder builds its kind.
#: Step 2 built `ability` and `effect` for the player's own side, so the
#: list is empty; KINDS_SIDE_LEGACY keeps the check honest per side.
KINDS_LEGACY: dict[str, str] = {}
#: KINDS_LEGACY's keys. Frozen: the list only shrinks (seeded with `ability`
#: and `effect`, both cleared by step 2 on 2026-10-09).
KINDS_SEED: frozenset[str] = frozenset()
#: `<kind>:<side>` pairs the ability builder does not build yet, each with
#: the plan step that builds it. A kind counts as built once any side is, so
#: this list holds the sides `ABILITY_SIDES_BUILT` leaves out; an entry
#: goes when its side joins that constant.
KINDS_SIDE_LEGACY: dict[str, str] = {
    "ability:team": "docs/ABILITY_ENTITIES.md step 3 (the team's ability children)",
    "ability:enemy": "docs/ABILITY_ENTITIES.md step 4 (the enemy's ability children)",
    "effect:team": "docs/ABILITY_ENTITIES.md step 3 (the team's effects)",
    "effect:enemy": "docs/ABILITY_ENTITIES.md step 4 (the enemy's effects)",
}
#: KINDS_SIDE_LEGACY's keys when seeded, 2026-10-09. Frozen: only shrinks.
KINDS_SIDE_SEED: frozenset[str] = frozenset(KINDS_SIDE_LEGACY)


def _kind_constants(tree: ast.Module) -> dict[str, str]:
    """`{constant: kind}` for each module-level `KIND_<X> = "<kind>"`."""
    out = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str):
            for t in node.targets:
                if isinstance(t, ast.Name) and KIND_CONSTANT.match(t.id):
                    out[t.id] = node.value.value
    return out


def _channel_feeds(tree: ast.Module) -> set[str]:
    """Every ownership entry a `CHANNELS` row `feeds`, read from the literal."""
    out: set[str] = set()
    for node in tree.body:
        targets = [node.target] if isinstance(node, ast.AnnAssign) else \
            node.targets if isinstance(node, ast.Assign) else []
        if not any(isinstance(t, ast.Name) and t.id == "CHANNELS" for t in targets):
            continue
        for d in ast.walk(node.value):
            if not isinstance(d, ast.Dict):
                continue
            for k, v in zip(d.keys, d.values):
                if isinstance(k, ast.Constant) and k.value == "feeds":
                    out |= {e.value for e in ast.walk(v)
                            if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return out


def declared_kinds(tree: ast.Module, entity_kinds: dict | None = None) -> dict[str, str]:
    """`{kind: where it is declared}`: each `KIND_<X>` constant, and the
    `entity_kind` of each ownership entry a `CHANNELS` row feeds
    (`entity_kinds`: entry id -> kind)."""
    out = {kind: name for name, kind in _kind_constants(tree).items()}
    for entry in sorted(_channel_feeds(tree)):
        kind = (entity_kinds or {}).get(entry)
        if kind:
            out.setdefault(kind, f"CHANNELS feeds `{entry}`")
    return out


def built_kinds(tree: ast.Module, builder: str = KINDS_BUILDER,
                extra: tuple = ()) -> set[str] | None:
    """The kinds of every `EntityRow(...)`, and of every row literal's
    `"entity_kind": KIND_<X>`, built in `builder` (and each of `extra` the
    module defines) or in a module-level function they reach by calls; None
    without `builder`."""
    funcs = {n.name: n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if builder not in funcs:
        return None
    consts = _kind_constants(tree)
    seen, todo, kinds = set(), [builder] + [b for b in extra if b in funcs], set()
    while todo:
        name = todo.pop()
        if name in seen:
            continue
        seen.add(name)
        for d in ast.walk(funcs[name]):
            if isinstance(d, ast.Dict):
                for k, v in zip(d.keys, d.values):
                    if isinstance(k, ast.Constant) and k.value == "entity_kind" \
                            and isinstance(v, ast.Name) and v.id in consts:
                        kinds.add(consts[v.id])
        for call in ast.walk(funcs[name]):
            if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Name):
                continue
            if call.func.id in funcs:
                todo.append(call.func.id)
            if call.func.id != "EntityRow":
                continue
            arg = call.args[0] if call.args else next(
                (k.value for k in call.keywords if k.arg == "kind"), None)
            if isinstance(arg, ast.Name) and arg.id in consts:
                kinds.add(consts[arg.id])
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                kinds.add(arg.value)
    return kinds


def _sides_built(tree: ast.Module) -> set[str]:
    """The strings of the module's `ABILITY_SIDES_BUILT` tuple literal."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == KINDS_SIDES_CONSTANT
                                                for t in node.targets):
            return {e.value for e in ast.walk(node.value)
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return set()


def kinds_findings(base: Path | None = None, entity_kinds: dict | None = None,
                   legacy: dict | None = None,
                   seed: frozenset | None = None, side_legacy: dict | None = None,
                   side_seed: frozenset | None = None) -> list[tuple[str, str]]:
    """KINDS: each entity kind `slot_state` declares (`KIND_*`, or an entry
    `CHANNELS` feeds) is one `build_slots` builds.

    An unbuilt kind is a WARN, once per kind, naming the plan step in
    `KINDS_LEGACY` that builds it, else an ERROR. A listed kind the builder
    now builds, or no longer declared, is an ERROR until its entry goes; a
    listed kind outside the frozen `KINDS_SEED` is an ERROR. `entity_kinds`
    maps ownership entry ids to their `entity_kind` (`doctor` reads
    `ownership.toml`); the module is read as source, never imported.

    Per side: a kind counts as built once any side is, so each
    `<kind>:<side>` of `KINDS_SIDE_LEGACY` that `ABILITY_SIDES_BUILT` leaves
    out is a WARN naming its step; one that constant now names, or one
    outside the frozen `KINDS_SIDE_SEED`, is an ERROR."""
    base = ROOT if base is None else Path(base)
    legacy = KINDS_LEGACY if legacy is None else legacy
    seed = KINDS_SEED if seed is None else seed
    side_legacy = KINDS_SIDE_LEGACY if side_legacy is None else side_legacy
    side_seed = KINDS_SIDE_SEED if side_seed is None else side_seed
    path = base / KINDS_MODULE
    tree = _parse_source(path) if path.is_file() else None
    if tree is None:
        return [(ERROR, f"`{KINDS_MODULE}` is missing or does not parse")]
    built = built_kinds(tree, KINDS_BUILDER, KINDS_BUILDERS[1:])
    if built is None:
        return [(ERROR, f"`{KINDS_MODULE}` defines no `{KINDS_BUILDER}`")]
    declared = declared_kinds(tree, entity_kinds)
    out = []
    for kind in sorted(set(declared) - built):
        if kind in legacy:
            out.append((WARN, f"entity kind `{kind}` ({declared[kind]}) is declared and "
                              f"`slot_state.{KINDS_BUILDER}` does not build it; {legacy[kind]}"))
        else:
            out.append((ERROR, f"entity kind `{kind}` ({declared[kind]}) is declared and "
                               f"`slot_state.{KINDS_BUILDER}` does not build it -- build it, or "
                               "drop the declaration"))
    for kind in sorted(set(legacy) & built):
        out.append((ERROR, f"KINDS_LEGACY names `{kind}`, which `slot_state.{KINDS_BUILDER}` now "
                           "builds -- remove it from the allowlist"))
    for kind in sorted(set(legacy) - set(declared) - built):
        out.append((ERROR, f"KINDS_LEGACY names `{kind}`, which `slot_state` no longer declares "
                           "-- remove it from the allowlist"))
    for kind in sorted(set(legacy) - set(seed)):
        out.append((ERROR, f"KINDS_LEGACY names `{kind}`, outside the frozen KINDS_SEED -- "
                           "the allowlist only shrinks"))
    sides = _sides_built(tree)
    for key in sorted(side_legacy):
        kind, _, side = key.partition(":")
        if side in sides:
            out.append((ERROR, f"KINDS_SIDE_LEGACY names `{key}`, which `slot_state."
                               f"{KINDS_SIDES_CONSTANT}` now builds -- remove it from the allowlist"))
        elif key not in side_seed:
            out.append((ERROR, f"KINDS_SIDE_LEGACY names `{key}`, outside the frozen "
                               "KINDS_SIDE_SEED -- the allowlist only shrinks"))
        else:
            out.append((WARN, f"entity kind `{kind}` is built for {sorted(sides) or 'no side'} "
                              f"and not for `{side}`; {side_legacy[key]}"))
    return out


# ---------------------------------------------------------------------------
# Progress, for `status`
# ---------------------------------------------------------------------------

def progress(base: Path | None = None) -> dict:
    """Conversion progress per ratchet, against the frozen seeds: readers
    converted against legacy, audited sites fixed against legacy, unreviewed
    sites left."""
    readers = reader_classes(base)
    seeded = lambda name: {k for k, (lst, _n) in ROUNDSCOPE_SEED.items() if lst == name}
    return {
        "convert": {"gated": sum(1 for r in readers if r.gate_ok and
                                 (r.gate_kind == "spans" or FRAME_HOOK)),
                    "legacy": len(CONVERT_LEGACY)},
        "roundscope": {"fixed": len(seeded("LEGACY") - set(ROUNDSCOPE_LEGACY)),
                       "legacy": len(ROUNDSCOPE_LEGACY),
                       "reviewed": len(seeded("UNREVIEWED") - set(ROUNDSCOPE_UNREVIEWED)),
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
