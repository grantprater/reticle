"""Structural checks on the REPO, not on the store.

    .\\.venv\\Scripts\\python.exe -m reticle doctor [--verbose]

Why this exists, and what it deliberately does not do
------------------------------------------------------
`reticle status` answers *what is in the store*, and it exists because a
hand-written status line was wrong three ways at once. This answers the other
half: *what shape is the codebase in*, which nothing computed before and which
had gone wrong in three places at once by 2026-09-06.

**It does not re-check anything `status` covers.** L1 version staleness is
`status`'s question and it already reads the parquet metadata to answer it;
duplicating that here would be this file committing the exact fault it exists
to catch. Where a check needs a stored fact, it reads one `status` does not
look at.

Why a command and not a git hook
---------------------------------
A hook fires on commit, which is precisely when someone is in a hurry, and the
three recurrences this repo has recorded for *look at the image before
measuring it* all happened under time pressure. A hook that gets bypassed is
worse than a command that gets run, because it also creates the belief that
something is watching. Run this when picking work up, not when putting it down.

The occasion: `floor_mask` forked
----------------------------------
Two definitions with different behaviour for ten days, in the two files that
already disagreed about the slab, while the check written to catch exactly that
passed clean -- `git grep -h "^def " | sort | uniq -d` matches the whole
signature line and the two were `floor_mask(med)` and
`floor_mask(med, dilate=9)`. Every check here is a fault that has actually
happened, which is the bar for adding another.

**This module is allowed to read both trees.** That is a deliberate exception
to the dependency direction -- `reticle/` does not otherwise know `prototypes/`
exists -- and it is the whole point of an auditor: a checker that can only see
one side of a fork cannot see a fork.
"""
from __future__ import annotations

import argparse
import ast
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ERROR, WARN = "ERROR", "WARN"

#: Names that legitimately exist in both trees because they are LOCAL helpers
#: with the same obvious name and unrelated bodies -- a module's own `load`,
#: its own `render`. Blessing one is cheap and requires saying so here, which
#: is the point: the check fires on everything else, so a genuine fork cannot
#: hide among them. `floor_mask` was never in this set and never would be.
ALLOWED_LOCAL = frozenset({
    "main", "_self_test",          # entry points, one per runnable file
    "load", "render", "report", "summarise", "compare", "classify",
    "segment", "sample_frames", "_text",
})


def _defs(tree_name: str) -> dict[str, list[str]]:
    """Top-level function names per file in one tree."""
    out: dict[str, list[str]] = collections.defaultdict(list)
    for f in sorted((ROOT / tree_name).glob("*.py")):
        try:
            mod = ast.parse(f.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for n in mod.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[n.name].append(f"{tree_name}/{f.name}")
    return out


def check_duplicate() -> list[tuple[str, str]]:
    """A name DEFINED in both trees. The fault this whole file is named for.

    Matching on the name rather than the signature is the correction: two
    copies of one function drift apart by growing a parameter, so the moment
    they are worth catching is the moment a signature match stops firing.
    """
    a, b = _defs("reticle"), _defs("prototypes")
    out = []
    for name in sorted(set(a) & set(b)):
        if name in ALLOWED_LOCAL:
            continue
        where = ", ".join(a[name] + b[name])
        out.append((ERROR, f"`{name}` defined in both trees -- {where}. "
                           f"Promote and re-export; never copy."))
    return out


def _reticle_imports(path: Path) -> set[str]:
    """Sibling `reticle` modules this file imports, however it spells it."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return set()
    out: set[str] = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module:
            # `from .minimap import x` (level 1) or `from reticle.minimap import x`
            if n.level == 1:
                out.add(n.module.split(".")[0])
            elif n.module.startswith("reticle."):
                out.add(n.module.split(".")[1])
        elif isinstance(n, ast.ImportFrom) and n.level == 1 and n.module is None:
            # `from . import metrics`
            out.update(a.name for a in n.names)
        elif isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("reticle."):
                    out.add(a.name.split(".")[1])
    return out


def check_unwired() -> list[tuple[str, str]]:
    """Modules in `reticle/` that no CLI command can reach.

    Promoted-before-wired is the inverse of the fork and just as misleading: it
    makes "is it in `reticle/`?" stop meaning "is it in the pipeline?". Both
    `refine.py` and `roster.py` were in this state the day this was written.
    """
    seen, queue = set(), ["cli", "__main__"]
    while queue:
        m = queue.pop()
        if m in seen:
            continue
        seen.add(m)
        p = ROOT / "reticle" / f"{m}.py"
        if p.is_file():
            queue.extend(_reticle_imports(p) - seen)
    have = {f.stem for f in (ROOT / "reticle").glob("*.py")}
    # A module with its own `__main__` block IS an entry point -- `glance` and
    # `metrics` are documented as `python -m reticle.glance`, and calling those
    # unreachable is the check being wrong rather than the code. First run of
    # this file flagged `glance.py` for exactly that and it was a false
    # positive; a checker nobody believes is worse than no checker.
    entry = {f.stem for f in (ROOT / "reticle").glob("*.py")
             if '__name__ == "__main__"' in f.read_text(encoding="utf-8",
                                                        errors="replace")}
    orphan = sorted(have - seen - entry - {"__init__"})
    return [(WARN, f"`reticle/{m}.py` is reachable from no CLI command and has "
                   f"no entry point -- wire it, or move it back to prototypes/")
            for m in orphan]


def check_manifest(store: Path) -> list[tuple[str, str]]:
    """A manifest whose TAGS contradict the profile it was ingested with.

    Every constant in `minimap.py` is in widget pixels, and the profile is what
    sets the minimap ROI -- so a session tagged one widget size and ingested at
    another is read through the wrong crop, and nothing downstream says so. It
    returns answers, they are simply about the wrong pixels, which is the
    silent-failure shape the pre-ingest checklist keeps warning about.

    Found one on the first run: `2ba870ccbd50`, tagged `small-widget` and
    ingested `valorant-16x9-bigmap`. That session is already on record twice --
    a standing "never re-scan" hazard in `NOTES.md`, and a geometry failure
    `prototypes/CLAUDE.md` calls *unexplained*. A wrong-profile ingest would
    explain it. **Which of the two is wrong is not decided here**, and the
    check deliberately does not guess: it reports the contradiction.
    """
    man = store / "manifests"
    if not man.is_dir():
        return []
    out = []
    for f in sorted(man.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        prof = m.get("source_profile", "")
        tags = " ".join(m.get("tags") or [])
        big = "bigmap" in prof
        if ("small" in tags and big) or ("minimap:large" in tags and not big):
            out.append((WARN, f"{f.stem} is tagged `{tags}` but ingested as "
                              f"`{prof}` -- the widget size disagrees, so the "
                              f"minimap ROI may be the wrong crop"))
    return out


def check_orphan() -> list[tuple[str, str]]:
    """Prototypes named by no other file and by no document.

    A WARNING, never an error: a file written today and not yet wired is
    indistinguishable from one abandoned a fortnight ago, and only a person
    knows which. The value is the LIST, reviewed occasionally -- an entry that
    appears twice running is the one to delete.
    """
    protos = sorted(p.stem for p in (ROOT / "prototypes").glob("*.py"))
    text = []
    for d in ("reticle", "prototypes"):
        for f in (ROOT / d).glob("*.py"):
            text.append((f.stem, f.read_text(encoding="utf-8", errors="replace")))
    docs = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in list(ROOT.glob("*.md")) + list((ROOT / "prototypes").glob("*.md"))
        if p.is_file())
    dead = []
    for name in protos:
        if name in docs:
            continue
        if any(name in body for stem, body in text if stem != name):
            continue
        dead.append(name)
    if not dead:
        return []
    return [(WARN, f"{len(dead)} prototypes named by no code and no doc: "
                   f"{', '.join(dead)}")]


def check_geometry(store: Path) -> list[tuple[str, str]]:
    """Cached geometry whose `built_by` no longer matches the code.

    `status` cannot see this -- the npz are not L1 and carry no row version.
    The stamp is what caught a third "bomb site" growing out of 10921 px of
    brown void on Split, and it only works if something asks.
    """
    d = store / "geometry"
    if not d.is_dir():
        return []
    try:
        import sys
        sys.path.insert(0, str(ROOT / "prototypes"))
        sys.path.insert(0, str(ROOT))
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            import minimap_geometry as mg
        want = mg.source_stamp()
    except Exception as e:                                  # pragma: no cover
        return [(WARN, f"cannot compute the geometry stamp ({type(e).__name__}) "
                       f"-- staleness unchecked")]
    import numpy as np
    stale = []
    for p in sorted(d.glob("*.npz")):
        try:
            b = np.load(p, allow_pickle=True)["built_by"]
            got = str(b.item() if b.shape == () else b)
        except Exception:
            got = "unreadable"
        if got != want:
            stale.append(p.stem)
    if not stale:
        return []
    return [(ERROR, f"{len(stale)} of {len(list(d.glob('*.npz')))} geometry npz "
                    f"are STALE (built_by != current) -- rebuild with "
                    f"prototypes/minimap_geometry.py before trusting a minimap "
                    f"number. {', '.join(stale[:6])}"
                    f"{' ...' if len(stale) > 6 else ''}")]


def check_donor(store: Path) -> list[tuple[str, str]]:
    """Sessions sharing one static map across DIFFERENT widget sizes.

    Borrowing a donor's geometry is deliberate and measured -- a different
    account, day and encode still put the same map pixel within ~3 grey levels.
    Borrowing ACROSS widget sizes is not: every constant in `minimap.py` is in
    widget pixels, so a small-widget session wearing a large-widget donor's
    median is wrong in a way nothing downstream reports.
    """
    d, man = store / "geometry", store / "manifests"
    if not (d.is_dir() and man.is_dir()):
        return []
    import hashlib
    import numpy as np
    groups: dict[str, list[str]] = collections.defaultdict(list)
    for p in sorted(d.glob("*.npz")):
        try:
            s = np.load(p, allow_pickle=True)["static"]
        except Exception:
            continue
        groups[hashlib.md5(np.ascontiguousarray(s)).hexdigest()].append(p.stem)
    out = []
    for _, sids in groups.items():
        if len(sids) < 2:
            continue
        profiles = {}
        for sid in sids:
            f = man / f"{sid}.json"
            if f.is_file():
                m = json.loads(f.read_text(encoding="utf-8"))
                profiles[sid] = m.get("source_profile", "?")
        if len(set(profiles.values())) > 1:
            odd = collections.Counter(profiles.values())
            minority = odd.most_common()[-1][0]
            who = [s for s, pr in profiles.items() if pr == minority]
            out.append((WARN, f"{', '.join(who)} ({minority}) share a static map "
                              f"with {len(sids) - len(who)} sessions on "
                              f"{odd.most_common()[0][0]} -- widget sizes differ, "
                              f"so every widget-pixel constant is off"))
    return out


def run(store: Path, verbose: bool = False) -> list[tuple[str, str, str]]:
    checks = (("DUPLICATE", check_duplicate), ("UNWIRED", check_unwired),
              ("ORPHAN", check_orphan),
              ("GEOMETRY", lambda: check_geometry(store)),
              ("DONOR", lambda: check_donor(store)),
              ("MANIFEST", lambda: check_manifest(store)))
    out = []
    for name, fn in checks:
        for sev, msg in fn():
            out.append((sev, name, msg))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="reticle doctor",
                                 description=__doc__.split("\n")[0])
    ap.add_argument("--store", default=str(Path.home() / "reticle-store"))
    args = ap.parse_args(argv)

    found = run(Path(args.store))
    if not found:
        print("doctor  no structural findings")
        return 0
    width = max(len(n) for _, n, _ in found)
    for sev, name, msg in found:
        mark = "!!" if sev == ERROR else "  "
        print(f"{mark} {name:<{width}}  {msg}")
    n_err = sum(1 for s, _, _ in found if s == ERROR)
    print(f"\n{len(found)} finding(s), {n_err} error(s)")
    # Only an ERROR fails the command. A WARN is a list to review, and a
    # checker that fails on everything gets ignored, which is the failure mode
    # every convention in CLAUDE.md was rewritten to avoid.
    return 1 if n_err else 0


if __name__ == "__main__":
    raise SystemExit(main())
