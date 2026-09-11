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


def sibling_imports(path: Path, package: str = "reticle",
                    within: str = "") -> list[tuple[str, int, bool]]:
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
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
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
                    stems: frozenset[str] | None = None) -> list[tuple[str, int]]:
    """`(module, lineno)` for every import that crosses into the other tree.

    Both spellings, because the second is how the first hides. `from
    prototypes import x` is obvious. A `sys.path.insert` on the prototypes
    directory followed by a BARE `import map_shade` is the same dependency and
    reads like a stdlib import -- `doctor.check_shade` does exactly this, and a
    check blind to it would bless the pattern that evades it. So a bare import
    of any name that is a module in the other tree counts.
    """
    try:
        parsed = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return []
    if stems is None:
        stems = frozenset(p.stem for p in (ROOT / tree_name).glob("*.py"))
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
        within = module.rpartition(".")[0]
        for target, line, deferred in sibling_imports(paths[module], within=within):
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
    allowed = set(trees.get("allow", []))
    seen_allowed: set[str] = set()
    # Resolve the other tree's module names against the root being VERIFIED,
    # not the module's own. Passing a root and then reading the real repo made
    # the bare-import case pass vacuously under test.
    stems = frozenset(p.stem for p in (base / "prototypes").glob("*.py"))
    for module in sorted(present):
        crossings = foreign_imports(paths[module], stems=stems)
        if not crossings:
            continue
        if module in allowed:
            seen_allowed.add(module)
            continue
        where = ", ".join(f"{name} (line {line})" for name, line in crossings)
        out.append(("ERROR", f"`reticle/{module.replace('.', '/')}.py` imports "
                             f"the prototypes tree -- {where}. reticle/ must "
                             f"not depend on it."))
    for module in sorted(allowed - seen_allowed):
        out.append(("WARN", f"architecture.toml allows `{module}` to import "
                            f"prototypes/ and it no longer does -- delete it "
                            f"from trees.allow"))
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
