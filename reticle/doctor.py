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
import re
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

# These are the only sources allowed to implement/use capture aggregation.
# `reticle/minimap.py` retains the exact helper fingerprinted by existing baked
# artifacts; only the geometry builder may call it. Preflight uses its own
# median only to measure widget size/placement/orientation. Expanding this list
# is a design decision, not a way to silence a finding.
CAPTURE_MEDIAN_ALLOWLIST = frozenset({
    "reticle/minimap.py",
    "prototypes/clip_preflight.py",
    "prototypes/minimap_geometry.py",
})


def check_session_static(store: Path, root: Path | None = None) -> list[tuple[str, str]]:
    """Reject per-session base-map construction and retired cache access.

    Session frames may determine only the minimap widget's dimensions and
    placement. Base pixels, floor, lighting references and detector backgrounds
    must come from baked ``(map, profile)`` geometry. This source check exists
    because that boundary repeatedly crept back through convenience prototypes.
    """
    root = root or ROOT
    out = []
    for tree_name in ("reticle", "prototypes", "tools"):
        tree_dir = root / tree_name
        if not tree_dir.is_dir():
            continue
        for f in sorted(tree_dir.rglob("*.py")):
            rel = f.relative_to(root).as_posix()
            if rel == "reticle/doctor.py":
                continue
            source = f.read_text(encoding="utf-8", errors="replace")
            try:
                mod = ast.parse(source)
            except SyntaxError:
                continue
            bad = set()
            for node in ast.walk(mod):
                if not isinstance(node, ast.Call):
                    continue
                name = (node.func.id if isinstance(node.func, ast.Name) else
                        node.func.attr if isinstance(node.func, ast.Attribute) else "")
                if name in {"read_static_map", "write_static_map", "static_map",
                            "median_widget"} and rel not in CAPTURE_MEDIAN_ALLOWLIST:
                    bad.add(name)
                if name == "median" and any(
                        isinstance(child, ast.Call) and
                        ((isinstance(child.func, ast.Attribute) and child.func.attr == "stack") or
                         (isinstance(child.func, ast.Name) and child.func.id == "stack"))
                        for child in ast.walk(node)):
                    if rel not in CAPTURE_MEDIAN_ALLOWLIST:
                        bad.add("capture median")
            if ".static.npy" in source:
                bad.add("session .static.npy path")
            if bad:
                out.append((ERROR, f"{rel} uses {', '.join(sorted(bad))} -- "
                            "session pixels may only size/place the widget; "
                            "read baked (map, profile) geometry for every map value"))

    legacy = sorted((store / "masks").glob("*.static.npy"))
    if legacy:
        out.append((WARN, f"{len(legacy)} retired per-session static-map cache "
                    "file(s) remain under masks/. They are ignored by code; "
                    "remove them only as a deliberate cleanup."))
    return out


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


def check_promote(store: Path) -> list[tuple[str, str]]:
    """A prototype that was MEASURED and that nothing in `reticle/` uses.

    **This exists because not-wiring was the silent default, and the two checks
    above cannot see it.** `check_unwired` looks at modules already inside
    `reticle/`, so a result that never got promoted is invisible to it.
    `check_orphan` exempts a prototype for being NAMED in a document -- which
    means writing up a measured result is precisely what makes it stop being
    reported. Between them, the one state nobody was told about is the one that
    keeps recurring: measured, written down, never wired.

    The signal is `notes/predictions.jsonl`, the ledger every perceptual
    experiment is pre-registered in. A prototype named there was part of a
    recorded experiment; if no module in `reticle/` mentions it, that
    experiment has not reached the pipeline. **It reports the experiment, not
    the verdict** -- the ledger's rows are prose and this does not pretend to
    read them, so a listed entry means "decide about this", not "ship this".

    Keying on `kind == "outcome"` was tried first and reported NOTHING: of 22
    outcome rows, none names a prototype file. The ledger records what was
    measured, not what measured it. Narrowing to the rows that sound most
    conclusive therefore produced an empty check, which is the failure mode
    this whole check exists to attack.

    **Silence requires a recorded decision.** A measured NEGATIVE should not be
    wired -- `minimap_occlusion` refuted the overlap story and belongs exactly
    where it is -- so an outcome row may carry `"wire": "no"` with a
    `"wire_reason"`, and this skips it. That is the inversion the check is for:
    leaving a result unwired now costs one field in the ledger, where before it
    cost nothing at all.

    A WARNING, never an error. The check knows an experiment ran; it cannot
    know the result was good.
    """
    path = store / "notes" / "predictions.jsonl"
    if not path.is_file():
        return []
    stems = {f.stem for f in (ROOT / "prototypes").glob("*.py")}
    pats = {s: re.compile(rf"(?<!\w){re.escape(s)}(?!\w)") for s in stems}
    used: set[str] = set()
    for f in (ROOT / "reticle").glob("*.py"):
        # This file names prototypes in its own prose and is the one module
        # allowed to read both trees, so counting itself as a consumer would
        # let the checker retire its own findings by describing them.
        if f.name == "doctor.py":
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        used |= {s for s, p in pats.items() if p.search(text)}
    # A decision retires the PROTOTYPE, not the row it was written on. The
    # first version skipped only the declining row, so a `"wire": "no"` written
    # today could not retire a mention from 2026-09-03 and the finding never
    # cleared -- a check that cannot be satisfied is one people learn to skip.
    # So take two passes: gather what has been declined, then report the rest.
    lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines()
             if l.strip()]
    rows = []
    declined: set[str] = set()
    for line in lines:
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        rows.append(row)
        if str(row.get("wire", "")).lower() != "no":
            continue
        # A `subject`, when given, is the ONLY thing that row declines. Scanning
        # the whole row instead let a decline retire every prototype its reason
        # happened to name -- declining `ability_scale` silently declined
        # `ability_disc`, because the reason said the two must ship together.
        target = str(row.get("subject") or
                     " ".join(str(v) for v in row.values()))
        declined |= {s for s, p in pats.items() if p.search(target)}
    seen: dict[str, str] = {}
    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        # The ledger has carried several row shapes. Take whichever handle the
        # row actually has rather than printing a `?`, which tells a reader
        # nothing about which entry to go and read.
        tag = next((str(row[k]) for k in ("experiment", "id", "when", "date", "ts")
                    if row.get(k)), "")
        for s, p in pats.items():
            if s not in used and s not in declined and p.search(blob):
                seen.setdefault(s, tag[:40])
    return [(WARN, f"`prototypes/{s}.py` is in the prediction ledger"
                   + (f" under `{tag}`" if tag else "") +
                   " and no module in `reticle/` uses it -- wire it, or record "
                   "`\"wire\": \"no\"` with a reason on that row")
            for s, tag in sorted(seen.items())]


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

    **`BACKLOG.md` is EXCLUDED, and it is the whole reason this check nearly
    stopped working (2026-09-07).** Being named makes a prototype look alive, so
    writing the dead list into the backlog silenced the check outright -- five
    orphans to none, in one commit, with no code changed. That is a loop: the
    backlog entry's own stated trigger is *`doctor`'s ORPHAN check listing them
    twice in a row*, and satisfying the entry's format destroyed its trigger.
    Being on the deletion backlog is evidence a prototype is DEAD, not alive.

    `docs/` IS scanned (2026-09-08), and that is the opposite case: it is the
    documentation directory -- `docs/WORKING_MAP.md` is the routing entry point
    this repo tells every session to start from -- so a design doc naming a
    prototype is evidence it is alive, the same as a module importing it. The
    check read only the root and `prototypes/`, which made "named by no doc"
    mean something narrower than it says. Changed while it altered NOTHING:
    none of the nine current orphans appear in `docs/` either, so this cannot
    be a quiet way to clear the list.
    """
    protos = sorted(p.stem for p in (ROOT / "prototypes").glob("*.py"))
    text = []
    for d in ("reticle", "prototypes"):
        for f in (ROOT / d).glob("*.py"):
            text.append((f.stem, f.read_text(encoding="utf-8", errors="replace")))
    docs = "".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in (list(ROOT.glob("*.md")) + list((ROOT / "prototypes").glob("*.md"))
                  + list((ROOT / "docs").glob("*.md")))
        if p.is_file() and p.name != "BACKLOG.md")
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
                    f"prototypes/minimap_geometry.py --all before trusting a "
                    f"minimap number. {', '.join(stale[:6])}"
                    f"{' ...' if len(stale) > 6 else ''}")]


def check_coverage(store: Path) -> list[tuple[str, str]]:
    """Sessions that reach no geometry, and keys nothing has built.

    **This replaced `check_donor` on 2026-09-07, and the replacement is the
    point.** That check hunted for sessions sharing one static map across
    DIFFERENT widget sizes -- a real defect, because every constant in
    `minimap.py` is in widget pixels, and one a per-session store could always
    produce. Keying geometry `<map>__<profile>` makes it unrepresentable: a
    session reads the npz for its own profile or it reads nothing. A check that
    cannot fail is worse than no check, so it is gone rather than kept passing.

    What the new key CAN get wrong is coverage, in two directions: a session
    with no `map:` tag resolves to no key at all, and a key several sessions
    read may simply have never been built.
    """
    from . import geometry as G
    if not (store / "manifests").is_dir():
        return []
    out = []
    loose = G.untagged(store)
    if loose:
        out.append((WARN, f"{len(loose)} session(s) have no `map:` tag, so they "
                          f"reach NO geometry -- tag them: {', '.join(loose[:6])}"
                          f"{' ...' if len(loose) > 6 else ''}"))
    missing = [(k, len(G.sessions_for(k, store))) for k in G.keys_in_store(store)
               if not G.path(k, store).is_file()]
    if missing:
        out.append((WARN, f"{len(missing)} geometry key(s) that sessions read are "
                          f"NOT BUILT -- run prototypes/minimap_geometry.py: "
                          + ", ".join(f"{k} ({n} session(s))"
                                      for k, n in missing[:4])
                          + (" ..." if len(missing) > 4 else "")))
    return out


def check_shade(store: Path) -> list[tuple[str, str]]:
    """Geometry npz whose art-derived terrain levels are missing or stale.

    The sibling of `check_geometry`, and it exists for the same reason one
    level down: `shade`/`shade_kind`/`shade_step` are a COPY of
    `reference/shade/<map>__<profile>.npz`, so a copy can fall behind its
    source and nothing in the arrays says so. Refilling is seconds --
    `prototypes/map_shade.py build --all` -- which is why this is a WARN and
    not an ERROR: it is a cache, not a derivation.

    An npz with no shade at all is reported separately, because the cause is
    not staleness but a map whose art has never been fetched, and the fix is
    `wiki_map.py fetch` rather than a rebuild.
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
            import map_shade
        want = map_shade.stamp()
    except Exception as e:                                  # pragma: no cover
        return [(WARN, f"cannot compute the shade stamp ({type(e).__name__}) "
                       f"-- staleness unchecked")]
    import numpy as np
    stale, absent = [], []
    for p in sorted(d.glob("*.npz")):
        try:
            with np.load(p, allow_pickle=False) as z:
                if "shade" not in z.files:
                    absent.append(p.stem)
                    continue
                got = str(z["shade_built_by"])
        except Exception:
            got = "unreadable"
        if got != want:
            stale.append(p.stem)
    out = []
    if stale:
        out.append((WARN, f"{len(stale)} geometry npz carry a STALE shade "
                          f"(shade_built_by != current) -- refill with "
                          f"prototypes/map_shade.py build --all. "
                          f"{', '.join(stale[:6])}"
                          f"{' ...' if len(stale) > 6 else ''}"))
    if absent:
        out.append((WARN, f"{len(absent)} geometry npz have NO shade -- the "
                          f"map's art is not fetched. {', '.join(absent[:6])}"
                          f"{' ...' if len(absent) > 6 else ''}"))
    return out


def check_furniture(store: Path) -> list[tuple[str, str]]:
    """Baked geometry whose floor mask still swallows widget furniture.

    `floor_mask`'s BRIDGE rule re-attaches anything within 25 widget px of the
    map body, and proximity cannot tell a room from the widget's own drawing.
    On Sunset the location-name banner sits 9 px above the body, so the words
    `B Market` were map -- **57 entity hypotheses over 1410 observations** in
    one 79 s round, as persistent `ability?` and `enemy` boxes.

    The gate is `sd`, and `sd` is optional, so this reports what each baked
    geometry looks like WITH it against without. A finding here is not a stale
    cache to refill: it names the maps where a caller that omits `sd` still
    reports furniture as map, so the omission stays visible rather than
    quietly keeping the defect. It clears only when a geometry has no
    furniture to drop.
    """
    d = store / "geometry"
    if not d.is_dir():
        return []
    import numpy as np

    from .minimap import floor_mask
    hits = []
    for p in sorted(d.glob("*.npz")):
        try:
            with np.load(p, allow_pickle=False) as z:
                if "sd_lo" not in z.files or "static" not in z.files:
                    continue
                med, sd = z["static"].copy(), z["sd_lo"].copy()
        except Exception:                                   # pragma: no cover
            continue
        lost = int((floor_mask(med) & ~floor_mask(med, sd=sd)).sum())
        if lost:
            hits.append((lost, p.stem))
    if not hits:
        return []
    hits.sort(reverse=True)
    return [(WARN, f"{len(hits)} geometry admit widget furniture as floor "
                   f"unless `sd` is passed -- a caller on the pure-`med` path "
                   f"reads it as map. "
                   + ", ".join(f"{k} {n}px" for n, k in hits[:6])
                   + (" ..." if len(hits) > 6 else ""))]


def check_stalls(store: Path) -> list[tuple[str, str]]:
    """Sessions holding a lot of CAPTURE STALL -- frozen source, time passing.

    A finding rather than an error: a stall is the recording's fault and no
    code change fixes one after the fact. What it must not do is stay
    invisible, because a stalled stretch is the most confident-looking data a
    session has -- every reader reads the same frozen picture and reports a
    world it is no longer observing. Surfacing it at pickup is what stops a
    measurement being quoted over frames nothing was watching.

    Recomputed from `l1/primitives` (`stalls`), so it costs no decode. The
    threshold is deliberately loose: the point is the LIST and the worst
    offender, not a pass/fail.

    **Captures under five minutes are skipped, and the reason is not tidiness.**
    The ability-demo clips are 20-90 s of a static practice range, where a
    genuinely motionless scene repeats a thumbnail and the rule cannot tell
    that from a stall -- every one of them reports 4-17%. Left in, they were 26
    of 36 findings and drowned the five real matches. The shortest match is 16
    minutes and the longest clip is 1.4, so the cut sits in an empty gap.
    """
    from . import stalls as _stalls
    from .store import Store
    st = Store(store)
    out = []
    for man in st.sessions():
        sid = man["session_id"]
        date = str(man.get("ingested_at", ""))[:10] or None
        if date is None:
            continue
        found = _stalls.for_session(st, sid, date)
        if not found:
            continue
        table = st.read_primitives(sid, date)
        duration = float(table["t_ms"][-1]) if len(table["t_ms"]) else 0.0
        total = _stalls.total_ms(found)
        if duration < 300_000 or total / duration < 0.02:
            continue
        worst = max(s["t_end_ms"] - s["t_start_ms"] for s in found)
        out.append(("finding",
                    f"{sid} is {100 * total / duration:.1f}% stalled capture "
                    f"({total / 1000:.0f}s over {len(found)} stalls, longest "
                    f"{worst / 1000:.0f}s) -- those frames are not observations"))
    return sorted(out, key=lambda r: r[1])


def run(store: Path, verbose: bool = False) -> list[tuple[str, str, str]]:
    checks = (("DUPLICATE", check_duplicate), ("UNWIRED", check_unwired),
              ("ORPHAN", check_orphan),
              ("PROMOTE", lambda: check_promote(store)),
              ("SESSION_STATIC", lambda: check_session_static(store)),
              ("GEOMETRY", lambda: check_geometry(store)),
              ("SHADE", lambda: check_shade(store)),
              ("COVERAGE", lambda: check_coverage(store)),
              ("MANIFEST", lambda: check_manifest(store)),
              ("FURNITURE", lambda: check_furniture(store)),
              ("STALL", lambda: check_stalls(store)))
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
