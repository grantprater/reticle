"""The declared topological order of `reticle/`, and the checks that hold it.

    .\\.venv\\Scripts\\python.exe -m reticle.architecture [--graph]

What this is
------------
`architecture.toml` declares the layers. This verifies the code agrees, and it
deliberately does NOT compute the layering: a derived order is an artifact of
where imports happen to sit, and enforcing it would freeze that accident. The
measurement that settled it -- depth by longest path puts `doctor`, `domain` and
`decode` at the bottom beside `version`, because their real dependencies are
deferred inside functions -- is the argument written into that file.

Four checks, and each is a fault this repo has actually had
-----------------------------------------------------------
1. **An eager upward import**, which inverts the layering at import time.
   `store` imports `roster` for `N_SLOTS` and `refinement` imports `review` for
   `REVIEW_VERSION` -- both schema and version stamps living above the module
   that needs them.
2. **A deferred upward import**, which is how an inversion hides. Every cycle
   in `reticle/` today is a deferred back-edge: `minimap`/`track`,
   `decode`/`refine`, `capabilities`/`acquisition`, `cli`/`fidelity`. The
   module-level graph is acyclic and the deferred edges are what make it look
   otherwise, so they are reported separately rather than forgiven silently.
3. **A stale declaration.** An unplaced module, a phantom one, a module in two
   layers, or an exception whose edge no longer exists. This is the half that
   stops the file rotting upward into permissiveness -- a declaration that is
   only ever verified can be satisfied by declaring everything.
4. **The tree direction.** `reticle/` must not import `prototypes/`. A shipped
   module depending on something with no version stamp and no tests is the
   fault `doctor`'s own docstring claims is protected, and
   `ability_timeline.materialize_demo_casts` has been violating it unreported.
   A `sys.path` change or an `importlib` load naming the tree is an ERROR
   for every module but a declared auditor (`trees.auditor`); `trees.allow`
   excuses only plain imports, and reports each one on every run.

Why layers and not edges
------------------------
Declaring all 99 module-level edges would be 99 lines that churn on every
import and get rubber-stamped. Eight layers catch the fault that matters --
something reaching upward -- and fit on a screen. Function-level granularity
was considered and rejected for the same reason one step further: it would
churn on every edit and be maintained by nobody.
"""
from __future__ import annotations

import ast
import hashlib
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = ROOT / "architecture.toml"


def modules(root: Path | None = None, package: str = "reticle") -> dict[str, Path]:
    """Every module in the package, INCLUDING its subpackages, dotted.

    `reticle/adjudication/` was invisible here until 2026-09-11: a `*.py` glob
    cannot see a directory, so four modules sat in no layer, unreported, and
    `adjudication/ability.py` imported `ability_timeline` -- an eager edge out
    of adjudication up into entities -- with nothing to say so. A checker's
    blind spot is worse than a missing check, because the clean run is read as
    a clean repo.
    """
    base = (Path(root) if root else ROOT) / package
    out: dict[str, Path] = {}
    for path in sorted(base.glob("*.py")):
        if path.stem != "__init__":
            out[path.stem] = path
    for sub in sorted(p for p in base.iterdir() if p.is_dir()):
        if sub.name.startswith(("_", ".")):
            continue
        for path in sorted(sub.glob("*.py")):
            if path.stem != "__init__":
                out[f"{sub.name}.{path.stem}"] = path
    return out


#: Per-file scan results, keyed on the scan, the file's bytes and the scan's
#: arguments. `doctor` and the repository tests ask these questions of the
#: same modules several times in one process, and parsing is the cost. Only
#: the small results stay, never the trees, so a long process holds no ASTs
#: for the collector to walk; an edited file has new bytes and a new key.
_RESULTS: dict[tuple, list | set] = {}
#: The last file parsed, so several scans of one file share one parse.
_TREE: list[tuple[bytes, ast.Module | None]] = []


def _memo(kind: str, path: Path, extra, compute):
    """`compute(tree)` for the file at `path`, once per distinct content: a
    fresh copy of the cached list or set. `tree` is None for a file that
    does not parse."""
    data = Path(path).read_bytes()
    digest = hashlib.blake2b(data, digest_size=20).digest()
    key = (kind, digest, extra)
    if key not in _RESULTS:
        if _TREE and _TREE[0][0] == digest:
            tree = _TREE[0][1]
        else:
            # As `read_text` reads: replaced errors, universal newlines.
            text = data.decode("utf-8", errors="replace")
            text = text.replace("\r\n", "\n").replace("\r", "\n")
            try:
                tree = ast.parse(text)
            except SyntaxError:
                tree = None
            _TREE[:] = [(digest, tree)]
        _RESULTS[key] = compute(tree)
    value = _RESULTS[key]
    return type(value)(value)


def _forget_tree() -> None:
    """Drop the last parsed tree once a scan of every module is done."""
    _TREE.clear()


def sibling_imports(path: Path, package: str = "reticle",
                    within: str = "", parsed: ast.Module | None = None
                    ) -> list[tuple[str, int, bool]]:
    """`(module, lineno, deferred)` for every same-package import in a file.

    `deferred` means the import sits inside a function or class body, so it
    runs on call rather than on import. That distinction is the whole point:
    it is what separates an inverted layer from a runtime call upward, and it
    is what makes every cycle in this package invisible to a naive graph.

    `within` is the subpackage the file itself lives in, because a relative
    import only resolves against it: inside `adjudication/`, `from .ability`
    means `adjudication.ability` and `from ..ability_timeline` means the
    top-level module of that name.
    """
    if parsed is None:
        return _memo("sibling", path, (package, within), lambda tree: [] if tree is None
                     else sibling_imports(path, package, within, tree))
    tree = parsed
    out: list[tuple[str, int, bool]] = []

    here = f"{within}." if within else ""

    def targets(node: ast.AST) -> list[str]:
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level == 1:
                return [f"{here}{a.name}" for a in node.names]
            if node.module:
                if node.level == 1:
                    return [f"{here}{node.module}"]
                if node.level == 2 and within:
                    return [node.module]
                if node.module == package:
                    return [a.name for a in node.names]
                if node.module.startswith(f"{package}."):
                    return [node.module[len(package) + 1:]]
            return []
        if isinstance(node, ast.Import):
            return [a.name[len(package) + 1:] for a in node.names
                    if a.name.startswith(f"{package}.")]
        return []

    def walk(node: ast.AST, deferred: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.Import, ast.ImportFrom)):
                for name in targets(child):
                    out.append((name, child.lineno, deferred))
            walk(child, deferred or isinstance(
                child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))

    walk(tree, False)
    return out


def foreign_imports(path: Path, tree_name: str = "prototypes",
                    stems: frozenset[str] | None = None,
                    parsed: ast.Module | None = None) -> list[tuple[str, int]]:
    """`(module, lineno)` for every import that crosses into the other tree.

    Both spellings, because the second is how the first hides. `from
    prototypes import x` is obvious. A `sys.path.insert` on the prototypes
    directory followed by a BARE `import map_shade` is the same dependency and
    reads like a stdlib import -- `doctor.check_shade` does exactly this, and a
    check blind to it would bless the pattern that evades it. So a bare import
    of any name that is a module in the other tree counts.
    """
    if stems is None:
        stems = frozenset(p.stem for p in (ROOT / tree_name).glob("*.py"))
    if parsed is None:
        return _memo("foreign", path, (tree_name, stems), lambda tree: [] if tree is None
                     else foreign_imports(path, tree_name, stems, tree))
    out = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            head = node.module.split(".")[0]
            if head == tree_name or head in stems:
                out.append((node.module, node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                head = alias.name.split(".")[0]
                if head == tree_name or head in stems:
                    out.append((alias.name, node.lineno))
    out.extend(foreign_loads(path, tree_name, stems, parsed))
    return sorted(out, key=lambda c: c[1])


#: Calls that load code by path or by a name held in a string: `importlib`'s
#: and `runpy`'s entry points, the file loader, `site` and the builtin.
_LOADERS = frozenset({"import_module", "spec_from_file_location", "run_path",
                      "run_module", "SourceFileLoader", "addsitedir",
                      "__import__"})
#: `sys.path` methods that change where a bare import resolves.
_PATH_MUTATORS = frozenset({"insert", "append", "extend"})


def _strings(node: ast.AST) -> list[str]:
    return [n.value for n in ast.walk(node)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)]


def _is_sys_path(node: ast.AST) -> bool:
    return (isinstance(node, ast.Attribute) and node.attr == "path"
            and isinstance(node.value, ast.Name) and node.value.id == "sys")


def _callee(func: ast.AST) -> str:
    if isinstance(func, ast.Attribute):
        return func.attr
    return func.id if isinstance(func, ast.Name) else ""


def foreign_loads(path: Path, tree_name: str = "prototypes",
                  stems: frozenset[str] | None = None,
                  parsed: ast.Module | None = None) -> list[tuple[str, int]]:
    """`(description, lineno)` for every reach into the other tree that no
    import statement shows: a `sys.path` change naming the tree, and an
    `importlib`, `runpy`, `site` or `__import__` load naming the tree or one
    of its modules.

    `lineup._composition` reached `prototypes/` this way, and the LAYER check
    stayed silent because `lineup` sat in `trees.allow`, which waved through
    every crossing a module made. The insert is the part that makes ANY later
    bare import resolve into the other tree, so `verify` judges these apart
    from plain imports, and `trees.allow` does not cover them.

    A string matches when it names the tree as a path part (`root /
    "prototypes"`, `"prototypes/x.py"`), as a dotted head, or is one of the
    tree's module names. A path built from no string constant is beyond a
    static check.
    """
    if stems is None:
        stems = frozenset(p.stem for p in (ROOT / tree_name).glob("*.py"))
    if parsed is None:
        return _memo("loads", path, (tree_name, stems), lambda tree: [] if tree is None
                     else foreign_loads(path, tree_name, stems, tree))

    def path_part(text: str) -> bool:
        return tree_name in text.replace("\\", "/").split("/")

    def names_tree(text: str) -> bool:
        return path_part(text) or text.split(".")[0] in (stems | {tree_name})

    out: list[tuple[str, int]] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Call):
            func = node.func
            args = list(node.args) + [k.value for k in node.keywords]
            if (isinstance(func, ast.Attribute) and _is_sys_path(func.value)
                    and func.attr in _PATH_MUTATORS):
                texts = [t for a in args for t in _strings(a)]
                hit = [t for t in texts if path_part(t)]
                if hit:
                    out.append((f"sys.path.{func.attr}({hit[0]!r})", node.lineno))
            elif _callee(func) in _LOADERS:
                texts = [t for a in args for t in _strings(a)]
                hit = [t for t in texts if names_tree(t)]
                if hit:
                    out.append((f"{_callee(func)}({hit[0]!r})", node.lineno))
        elif isinstance(node, (ast.Assign, ast.AugAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            touches = any(_is_sys_path(t) or (isinstance(t, ast.Subscript)
                                              and _is_sys_path(t.value))
                          for t in targets)
            hit = [t for t in _strings(node.value) if path_part(t)]
            if touches and hit:
                out.append((f"sys.path assignment ({hit[0]!r})", node.lineno))
    return out


def load(path: Path | None = None) -> dict:
    """The declaration, with the layer index resolved."""
    source = Path(path) if path else DECLARATION
    if not source.is_file():
        return {}
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    order = list(data.get("layers", {}).get("order", []))
    index: dict[str, int] = {}
    duplicated: list[str] = []
    for rank, layer in enumerate(order):
        for module in data.get(layer, {}).get("modules", []):
            if module in index:
                duplicated.append(module)
            index[module] = rank
    data["_order"] = order
    data["_index"] = index
    data["_duplicated"] = sorted(set(duplicated))
    return data


def _blessed(data: dict) -> dict[tuple[str, str], dict]:
    return {(str(e.get("from")), str(e.get("to"))): e
            for e in data.get("exception", [])}


def verify(data: dict | None = None,
           root: Path | None = None) -> list[tuple[str, str]]:
    """`(level, message)` pairs. ERROR blocks; WARN is a list to work off."""
    base = Path(root) if root else ROOT
    data = data if data is not None else load()
    if not data:
        return [("WARN", "architecture.toml is absent -- the layering is "
                         "declared there, see reticle/architecture.py")]
    order, index = data["_order"], data["_index"]
    paths = modules(base)
    present = set(paths)
    # Resolve the other tree's module names against the root being VERIFIED,
    # not the module's own. Passing a root and then reading the real repo made
    # the bare-import case pass vacuously under test.
    stems = frozenset(p.stem for p in (base / "prototypes").glob("*.py"))
    # Both scans of a module in one pass, so they share its parse.
    siblings, crossings_of = {}, {}
    for module in sorted(present):
        siblings[module] = sibling_imports(paths[module], within=module.rpartition(".")[0])
        crossings_of[module] = foreign_imports(paths[module], stems=stems)
    _forget_tree()
    out: list[tuple[str, str]] = []

    for module in data["_duplicated"]:
        out.append(("ERROR", f"`{module}` is declared in more than one layer"))
    for module in sorted(present - set(index)):
        out.append(("ERROR", f"`reticle/{module.replace('.', '/')}.py` is in no "
                             f"declared layer -- place it in architecture.toml"))
    for module in sorted(set(index) - present):
        out.append(("ERROR", f"architecture.toml declares `{module}`, which is "
                             f"not a module in reticle/"))

    blessed = _blessed(data)
    used: set[tuple[str, str]] = set()
    for module in sorted(present & set(index)):
        for target, line, deferred in siblings[module]:
            if target == module or target not in index:
                continue
            if index[target] <= index[module]:
                continue
            edge = (module, target)
            kind = "deferred" if deferred else "eager"
            exception = blessed.get(edge)
            if exception is not None:
                used.add(edge)
                declared = str(exception.get("kind", "")).strip()
                if declared and declared != kind:
                    out.append(("ERROR",
                                f"`{module}` -> `{target}` is blessed as "
                                f"{declared} and is now {kind} (line {line})"))
                continue
            level = "ERROR" if not deferred else "WARN"
            out.append((level,
                        f"`{module}` ({order[index[module]]}) imports `{target}` "
                        f"({order[index[target]]}) {kind} at line {line} -- "
                        f"upward, and not blessed in architecture.toml"))
    for edge in sorted(set(blessed) - used):
        out.append(("WARN", f"architecture.toml blesses `{edge[0]}` -> "
                            f"`{edge[1]}`, an edge that no longer exists -- "
                            f"delete the exception"))

    trees = data.get("trees", {})
    auditors = set(trees.get("auditor", []))
    allowed = set(trees.get("allow", []))
    seen_allowed: set[str] = set()
    for module in sorted(present):
        crossings = crossings_of[module]
        if not crossings:
            continue
        file = f"reticle/{module.replace('.', '/')}.py"
        if module in auditors:
            seen_allowed.add(module)
            continue
        loads = foreign_loads(paths[module], stems=stems)
        if loads:
            # A path change or a load by string is never allowed: it makes
            # every later bare import resolve into the other tree.
            where = ", ".join(f"{name} (line {line})" for name, line in loads)
            out.append(("ERROR", f"`{file}` loads the prototypes tree by path "
                                 f"or by string -- {where}. reticle/ must not "
                                 f"depend on it; trees.allow does not cover "
                                 f"this spelling."))
        plain = [c for c in crossings if c not in set(loads)]
        if not plain:
            continue
        where = ", ".join(f"{name} (line {line})" for name, line in plain)
        if module in allowed:
            # Allowed is unfinished, not blessed: report it every run, as a
            # dated consumer exemption is, so the allowance cannot go quiet.
            seen_allowed.add(module)
            out.append(("WARN", f"`{file}` imports the prototypes tree -- "
                                f"{where}; trees.allow lets it until the code "
                                f"is promoted"))
            continue
        out.append(("ERROR", f"`{file}` imports "
                             f"the prototypes tree -- {where}. reticle/ must "
                             f"not depend on it."))
    for module in sorted((allowed | auditors) - seen_allowed):
        out.append(("WARN", f"architecture.toml allows `{module}` to import "
                            f"prototypes/ and it no longer does -- delete it "
                            f"from trees.allow"))
    return out


def _string(node: ast.AST) -> str | None:
    return node.value if isinstance(node, ast.Constant) and isinstance(node.value, str) else None


def consumer_uses(path: Path, parsed: ast.Module | None = None, *,
                  calls: frozenset[str], imports: frozenset[str]
                  ) -> list[tuple[str, int]]:
    """`(use, lineno)` for everything a consumer may not touch but a sibling import.

    A use is `call:<name>` for a call to a forbidden store or parquet reader
    by attribute or name, `import:<module>` for a forbidden third-party
    import, and `path:events` for a path built into the store's `events/`
    directory -- `/ "events"`, a join over `"events"`, or a literal starting
    `events/`. Docstrings are prose, not paths, and are skipped.
    """
    if parsed is None:
        return _memo("consumer", path, (calls, imports), lambda tree: [] if tree is None
                     else consumer_uses(path, tree, calls=calls, imports=imports))
    tree = parsed
    docstrings = {id(n.value) for n in ast.walk(tree)
                  if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)}
    out: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else (
                f.id if isinstance(f, ast.Name) else None)
            if name in calls:
                out.append((f"call:{name}", node.lineno))
            if name in ("join", "joinpath", "Path") and any(
                    _string(a) == "events" for a in node.args):
                out.append(("path:events", node.lineno))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            if "events" in (_string(node.left), _string(node.right)):
                out.append(("path:events", node.lineno))
        elif isinstance(node, ast.Constant) and id(node) not in docstrings:
            text = _string(node)
            if text is not None and text.startswith("events/"):
                out.append(("path:events", node.lineno))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name in imports:
                    out.append((f"import:{alias.name}", node.lineno))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module in imports:
                out.append((f"import:{node.module}", node.lineno))
            for alias in node.names:
                if f"{node.module}.{alias.name}" in imports:
                    out.append((f"import:{node.module}.{alias.name}", node.lineno))
    return sorted(set(out), key=lambda u: (u[1], u[0]))


def ledger_calls(path: Path, parsed: ast.Module | None = None) -> list[int]:
    """Line numbers of every call to `ledger`, by attribute or by name."""
    if parsed is None:
        return _memo("ledger", path, None, lambda tree: [] if tree is None
                     else ledger_calls(path, tree))
    tree = parsed
    return sorted(node.lineno for node in ast.walk(tree)
                  if isinstance(node, ast.Call) and (
                      (isinstance(node.func, ast.Attribute) and node.func.attr == "ledger")
                      or (isinstance(node.func, ast.Name) and node.func.id == "ledger")))


def verify_consumers(data: dict | None = None,
                     root: Path | None = None) -> list[tuple[str, str]]:
    """CONSUMER: a declared consumer reads only emitted events.

    `[consumers]` in `architecture.toml` declares the consumer modules (the
    layer's own `modules`), the `review` subset that may call `ledger`, the
    layers a consumer may not import, and the store and parquet calls it may
    not make; the read goes through `read_through` (`entity_events`). A
    violation is an ERROR unless a `[[consumers.exemption]]` names that exact
    module and use with its `since`, its `until` and its reason; an exempted
    use is reported every run, and an exemption whose use is gone is stale.
    Any module outside `review` that calls `ledger` is an ERROR, consumer or
    not, bar the module that defines it.
    """
    base = Path(root) if root else ROOT
    data = data if data is not None else load()
    table = data.get("consumers") if data else None
    if not table:
        return []
    index, order = data["_index"], data["_order"]
    paths = modules(base)
    declared = list(table.get("modules", []))
    review = set(table.get("review", []))
    through = str(table.get("read_through", ""))
    forbidden = set(table.get("forbidden_layers", []))
    calls = frozenset(table.get("forbidden_calls", []))
    foreign = frozenset(table.get("forbidden_imports", []))
    out: list[tuple[str, str]] = []

    for layer in sorted(forbidden - set(order)):
        out.append(("ERROR", f"[consumers] forbids layer `{layer}`, which "
                             f"architecture.toml does not declare"))
    for module in sorted(review - set(declared)):
        out.append(("ERROR", f"[consumers] review names `{module}`, which is "
                             f"not a declared consumer"))

    exemptions: dict[tuple[str, str], dict] = {}
    for ex in table.get("exemption", []):
        key = (str(ex.get("module", "")), str(ex.get("uses", "")))
        missing = [f for f in ("module", "uses", "since", "until", "reason")
                   if not str(ex.get(f, "")).strip()]
        if missing:
            out.append(("ERROR", f"[consumers] exemption {key[0]} {key[1]} names "
                                 f"no {', '.join(missing)} -- a transitional "
                                 f"exemption is dated and names its end"))
        exemptions[key] = ex
    used: set[tuple[str, str]] = set()

    for module in declared:
        path = paths.get(module)
        if path is None:
            continue
        within = module.rpartition(".")[0]
        found: list[tuple[str, int]] = []
        for target, line, _deferred in sibling_imports(path, within=within):
            if target != through and target in index and order[index[target]] in forbidden:
                found.append((f"import:{target}", line))
        found += consumer_uses(path, calls=calls, imports=foreign)
        for use, line in sorted(set(found), key=lambda u: (u[1], u[0])):
            ex = exemptions.get((module, use))
            if ex is not None:
                if (module, use) not in used:
                    out.append(("WARN", f"`{module}` {use} (line {line}) is exempt "
                                        f"until {ex.get('until')}, since "
                                        f"{ex.get('since')}"))
                used.add((module, use))
                continue
            out.append(("ERROR", f"consumer `{module}` {use} at line {line} -- a "
                                 f"consumer reads only emitted events, through "
                                 f"`{through}`"))
    for key in sorted(set(exemptions) - used):
        out.append(("WARN", f"[consumers] exempts `{key[0]}` {key[1]}, a use that "
                            f"no longer exists -- delete the exemption"))

    for module, path in sorted(paths.items()):
        if module in review or module == through:
            continue
        for line in ledger_calls(path):
            out.append(("ERROR", f"`{module}` calls `ledger` at line {line} and is "
                                 f"not in the [consumers] review list"))
    _forget_tree()
    return out


def graph(root: Path | None = None) -> dict[str, dict]:
    """The eager and deferred sibling edges, for a reader rather than a check."""
    paths = modules(Path(root) if root else ROOT)
    present = set(paths)
    out: dict[str, dict] = {}
    for module in sorted(present):
        found = sibling_imports(paths[module], within=module.rpartition(".")[0])
        eager = sorted({t for t, _l, d in found if not d and t in present and t != module})
        deferred = sorted({t for t, _l, d in found
                           if d and t in present and t != module} - set(eager))
        out[module] = {"eager": eager, "deferred": deferred}
    return out


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--graph", action="store_true",
                        help="print the import graph instead of checking")
    args = parser.parse_args(argv)

    data = load()
    if args.graph:
        index = data.get("_index", {})
        order = data.get("_order", [])
        for module, edges in graph().items():
            layer = order[index[module]] if module in index else "UNPLACED"
            print(f"{module} [{layer}]")
            if edges["eager"]:
                print(f"    imports  {', '.join(edges['eager'])}")
            if edges["deferred"]:
                print(f"    deferred {', '.join(edges['deferred'])}")
        return 0

    problems = verify(data)
    for level, message in problems:
        print(f"{level:6s} {message}")
    errors = sum(1 for level, _m in problems if level == "ERROR")
    print(f"\n{len(data.get('_order', []))} layers, "
          f"{len(data.get('_index', {}))} modules placed, "
          f"{len(problems)} finding(s), {errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
