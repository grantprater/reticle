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
import functools
import json
import re
from pathlib import Path

from reticle import architecture, documents, domain, metrics, ownership, quoted

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

#: The stored donor median (`<store>/reference/preflight_donor/`) is a capture
#: median at rest. Only the preflight that writes it may name it, so it cannot
#: become a reader's background.
PREFLIGHT_DONOR_READERS = frozenset({"prototypes/clip_preflight.py"})


def check_session_static(store: Path, root: Path | None = None) -> list[tuple[str, str]]:
    """Reject per-session base-map construction and retired cache access.

    Session frames may determine only the minimap widget's dimensions and
    placement. Base pixels, floor, lighting references and detector backgrounds
    must come from baked ``(map, profile)`` geometry. This source check exists
    because that boundary repeatedly crept back through convenience prototypes.
    Only `clip_preflight` may name its stored donor median, `preflight_donor`.
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
            # Every checked call names one of these identifiers in source.
            # Avoid parsing files that cannot contain a violation.
            if not any(token in source for token in ("static_map", "median", ".static.npy",
                                                     "preflight_donor")):
                continue
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
            if "preflight_donor" in source and rel not in PREFLIGHT_DONOR_READERS:
                bad.add("preflight donor median")
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
            elif n.module == "reticle":
                # `from reticle import documents` -- this file's own spelling.
                out.update(a.name for a in n.names)
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
    if not stems:
        return []
    # A mention is a whole word: every stem is made of word characters, so
    # the words of a text intersected with the stems are exactly the stems a
    # `(?<!\w)stem(?!\w)` search finds, at a sixth of a 250-way
    # alternation's cost.
    word = re.compile(r"\w+")

    def mentions(text: str) -> set[str]:
        return stems.intersection(word.findall(text))

    used: set[str] = set()
    for f in (ROOT / "reticle").glob("*.py"):
        # This file names prototypes in its own prose and is the one module
        # allowed to read both trees, so counting itself as a consumer would
        # let the checker retire its own findings by describing them.
        if f.name == "doctor.py":
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        used |= mentions(text)
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
        declined |= mentions(target)
    seen: dict[str, str] = {}
    for row in rows:
        blob = " ".join(str(v) for v in row.values())
        # The ledger has carried several row shapes. Take whichever handle the
        # row actually has rather than printing a `?`, which tells a reader
        # nothing about which entry to go and read.
        tag = next((str(row[k]) for k in ("experiment", "id", "when", "date", "ts")
                    if row.get(k)), "")
        for s in mentions(blob):
            if s not in used and s not in declined:
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
        # A stored widget placement answers the contradiction: the readers
        # read that widget through it (`widget_frame`), not through the wrong crop.
        if m.get("minimap_widget"):
            continue
        if ("small" in tags and big) or ("minimap:large" in tags and not big):
            out.append((WARN, f"{f.stem} is tagged `{tags}` but ingested as "
                              f"`{prof}` -- the widget size disagrees, so the "
                              f"minimap ROI may be the wrong crop"))
    return out


def check_source(store: Path, verbose: bool = False) -> list[tuple[str, str]]:
    """Each session's capture is on disk, or retired with its audio kept.

    A retired session (`video_retired`, written by `reticle retire`) has no
    video: `plan` reports its video steps as `source_retired`, and the audio
    readers read the retained file (`audio_source`). The retained file must
    be on disk at the size the manifest recorded, and under `--verbose` at
    its sha256 too (about 50 MB read per session, so not on every run), or
    the session has lost its audio: an ERROR. A capture gone without a retirement is a
    WARN; so is a retired capture still on disk, with the command that
    deletes it."""
    from .audio_source import retirement, video_state
    from .retire import deletion_command, sha256_file
    man = store / "manifests"
    if not man.is_dir():
        return []
    out, missing = [], []
    for f in sorted(man.glob("*.json")):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        state = video_state(m)
        if state == "missing":
            missing.append(f.stem)
            continue
        if state == "present":
            continue
        a = (retirement(m) or {}).get("audio") or {}
        p = Path(a.get("path") or "")
        p = p if p.is_absolute() else store / p
        if not p.is_file():
            out.append((ERROR, f"{f.stem}: video retired, retained audio missing at {p}"))
        elif p.stat().st_size != a.get("bytes"):
            out.append((ERROR, f"{f.stem}: retained audio {p} differs from the bytes the "
                               "manifest recorded"))
        elif verbose and sha256_file(p) != a.get("sha256"):
            out.append((ERROR, f"{f.stem}: retained audio {p} differs from the sha256 the "
                               "manifest recorded"))
        if state == "retired_present":
            out.append((WARN, f"{f.stem}: video retired and still on disk; the player deletes "
                              f"it with {deletion_command(m)}"))
    if missing:
        out.append((WARN, f"{len(missing)} session(s) lost their capture with no retirement "
                          f"recorded (`reticle retire`): {' '.join(missing)}"))
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


def check_occluders(store: Path) -> list[tuple[str, str]]:
    """Geometry npz whose occluder table (`occ`) is missing or stale.

    `occ` holds the walls and boxes a ray stops at, read from the baked static
    by `occluders` and stamped `occ_built_by`. A STALE table
    is an ERROR: every cone is cast over it. A MISSING one is a WARN: the rays
    fall back to the art's box edges alone, which pass the walls the art's
    warp lost, and `team_vision` records `occluders: null` so the fallback is
    visible in every product. Building is seconds and decodes nothing:
    `reticle occluders --all`.
    """
    d = store / "geometry"
    if not d.is_dir():
        return []
    try:
        from . import occluders
        want = occluders.occluder_stamp()
    except Exception as e:                                  # pragma: no cover
        return [(WARN, f"cannot compute the occluder stamp ({type(e).__name__}) "
                       f"-- staleness unchecked")]
    import numpy as np
    stale, absent, other_lines = [], [], []
    for p in sorted(d.glob("*.npz")):
        try:
            with np.load(p, allow_pickle=False) as z:
                if "occ" not in z.files:
                    absent.append(p.stem)
                    continue
                got = str(z["occ_built_by"]) if "occ_built_by" in z.files else "unstamped"
                # occluders-2.0.0: the table must have been built over the npz's own line classes
                if "line_cls" in z.files and got == want:
                    built_over = str(z["occ_lines"]) if "occ_lines" in z.files else ""
                    if built_over != str(z["lines_built_by"]):
                        other_lines.append(p.stem)
        except Exception:
            got = "unreadable"
        if got != want:
            stale.append(p.stem)
    out = []
    if stale:
        out.append((ERROR, f"{len(stale)} geometry npz carry a STALE occluder table "
                           f"(occ_built_by != current) -- rebuild with "
                           f"`reticle occluders --all`. "
                           f"{', '.join(stale[:6])}{' ...' if len(stale) > 6 else ''}"))
    if other_lines:
        out.append((ERROR, f"{len(other_lines)} geometry npz carry an occluder table built over other "
                           f"line classes (occ_lines != lines_built_by) -- rebuild with "
                           f"`reticle occluders --all`. {', '.join(other_lines[:6])}"))
    if absent:
        out.append((WARN, f"{len(absent)} geometry npz have NO occluder table -- rays "
                          f"stop only at the art's box edges; build with "
                          f"`reticle occluders --all`. "
                          f"{', '.join(absent[:6])}{' ...' if len(absent) > 6 else ''}"))
    return out


def check_lines(store: Path) -> list[tuple[str, str]]:
    """Geometry npz whose baked line classes are missing, refused or stale.

    `line_cls` (prototypes/line_classes.py) tells `occluders` which drawn lines
    stop light: walls and boxes do, ramp and elevation lines, heaven edges and
    overhang starts do not. Its stamp `lines_built_by` covers the sorter, the
    labeller and every label, note and heights file the key reads, so a new
    answer from the player makes it stale. A WARN: a key without current
    classes keeps occluders-1's rule, which `occ_lines` names. A refused key
    is listed apart, since its sanity rule refused it on purpose. Every key the
    player has not labelled is also listed, as UNVALIDATED, so a number read
    over it is known to rest on the sorter's generalisation.
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
            import line_classes
    except Exception as e:                                  # pragma: no cover
        return [(WARN, f"cannot compute the line-class stamp ({type(e).__name__}) "
                       f"-- staleness unchecked")]
    import json
    import numpy as np
    stale, absent, refused, unvalidated = [], [], [], []
    for p in sorted(d.glob("*.npz")):
        try:
            with np.load(p, allow_pickle=False) as z:
                if "lines_refused" in z.files:
                    refused.append(p.stem)
                    continue
                if "line_cls" not in z.files:
                    absent.append(p.stem)
                    continue
                got = str(z["lines_built_by"])
                meta = json.loads(str(z["lines_meta"])) if "lines_meta" in z.files else {}
        except Exception:
            got, meta = "unreadable", {}
        if got != line_classes.stamp(p.stem):
            stale.append(p.stem)
        if (meta.get("validation") or {}).get("status") != "labels":
            unvalidated.append(p.stem)
    out = []
    if stale:
        out.append((WARN, f"{len(stale)} geometry npz carry STALE line classes "
                          f"(lines_built_by != current) -- rebake with "
                          f"prototypes/line_classes.py bake --all, then `reticle occluders --all`. "
                          f"{', '.join(stale[:6])}{' ...' if len(stale) > 6 else ''}"))
    if absent:
        out.append((WARN, f"{len(absent)} geometry npz have NO line classes: their occluders "
                          f"keep occluders-1's rule. {', '.join(absent[:6])}"
                          f"{' ...' if len(absent) > 6 else ''}"))
    if refused:
        out.append((WARN, f"{len(refused)} geometry npz had their line classes REFUSED by the "
                          f"sanity rule (lines_refused): {', '.join(refused)}"))
    if unvalidated:
        out.append((WARN, f"{len(unvalidated)} geometry npz carry line classes no player answer "
                          f"validates (the sorter's generalisation): {', '.join(unvalidated[:12])}"))
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
        stamp_of = map_shade.stamp
        stamp_of()                        # fail here rather than in the loop
    except Exception as e:                                  # pragma: no cover
        return [(WARN, f"cannot compute the shade stamp ({type(e).__name__}) "
                       f"-- staleness unchecked")]
    import numpy as np
    stale, absent = [], []
    for p in sorted(d.glob("*.npz")):
        # The stamp is PER MAP since 2026-09-10: it hashes the art the shade was
        # warped from, so a re-fetched map invalidates its own keys and nobody
        # else's. The geometry key is `<map>__<profile>`, which names the map.
        map_name = p.stem.split("__")[0]
        try:
            with np.load(p, allow_pickle=False) as z:
                if "shade" not in z.files:
                    absent.append(p.stem)
                    continue
                got = str(z["shade_built_by"])
        except Exception:
            got = "unreadable"
        if got != stamp_of(map_name):
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
                    f"{worst / 1000:.0f}s) -- those frames are not "
                    f"observations [domain:capture/stalled-capture]"))
    return sorted(out, key=lambda r: r[1])


def check_domain() -> list[tuple[str, str]]:
    """The domain registry: schema, dangling citations, and unmigrated prose.

    `domain/*.toml` holds what is true of the GAME, and `reticle/domain.py`
    owns the schema and the `[domain:...]` citation form. Two faults this has
    already had: the minimap vision rule stated five ways in five files, and a
    fact the player supplied once that nothing ever read. So a citation
    resolving to no fact is an ERROR -- it is a reference to something that
    does not exist -- while a fact nothing cites, or prose that still restates
    one, is a finding to work off rather than a wall to hit.
    """
    facts = domain.load()
    if not facts:
        return [("finding", "domain/ holds no facts -- the registry is the one "
                            "place domain knowledge belongs; see reticle/domain.py")]
    out = []
    for level, message in domain.validate(facts):
        out.append((ERROR if level == ERROR else "finding", message))
    return out


def check_movement() -> list[tuple[str, str]]:
    """The teleport-licence owner's movement table against the domain facts.

    `track.MOVEMENT_FACTS` names, per agent and ability, the fact that
    licenses a dash, a teleport or a speed change. A row whose fact is gone or
    is not the player's licenses nothing, silently, so it is a finding here; a
    set of confirmed kinds no motion class covers makes `track.motion_for`
    raise, so it is an ERROR before any caller meets it.
    """
    from . import track
    out = []
    for lic in track.movement_licences():
        if not lic.confirmed:
            out.append(("finding", f"{lic.agent} {lic.ability} {lic.kind}: "
                                   f"{lic.reason}; it licenses nothing"))
    for agent in sorted({agent for agent, _ability in track.MOVEMENT_FACTS}):
        try:
            track.motion_for(agent)
        except ValueError as exc:
            out.append((ERROR, f"track.motion_for: {exc} -- add the class to "
                               f"track's table, never guess one"))
    return out


def check_layer() -> list[tuple[str, str]]:
    """The declared topological order of `reticle/`, verified against the code.

    `architecture.toml` declares eight layers and blesses each upward edge with
    a reason; `reticle/architecture.py` owns the schema and the checks. It is
    DECLARED rather than derived because the derived order is an accident --
    depth by longest path puts `doctor`, `domain` and `decode` beside `version`,
    since their real dependencies are deferred inside functions.

    It earned its place with two faults nobody had reported: `reticle/lineup.py`
    and `reticle/ability_timeline.py` both import the prototypes tree, which
    `check_duplicate`'s own docstring says cannot happen. `lineup` does it by
    inserting the directory on `sys.path` and importing bare, which reads like
    a stdlib import -- so the check counts that spelling too.
    """
    out = []
    for level, message in architecture.verify():
        out.append((ERROR if level == ERROR else "finding", message))
    return out


def check_consumer() -> list[tuple[str, str]]:
    """A declared consumer reads only emitted events.

    Events are the interface (AGENTS.md): a consumer that imports a reader or
    an adjudicator, or reads the store's streams itself, recomputes what an
    owner should have emitted, and the missing field never reaches the event.
    `architecture.toml`'s `[consumers]` table declares the consumers, the
    `review` modules that may read the ledger, and dated exemptions;
    `architecture.verify_consumers` holds the rule (docs/ENTITY_EVENTS.md,
    section 4).
    """
    out = []
    for level, message in architecture.verify_consumers():
        out.append((ERROR if level == ERROR else "finding", message))
    return out


def check_ownership() -> list[tuple[str, str]]:
    """Which module owns which question, verified against the code.

    `architecture.toml` says which imports are permitted and `domain/*.toml`
    says what is true of the game. Neither says who may DECIDE something, and
    that is the boundary the names in this repo collide on: `roster` and
    `lineup` both sound like identity, `minimap.pick_self` and `lineup`'s player
    vote are both called self, and `track` sounds like the answer to every
    identity question while owning none of them.

    Two faults paid for it. The HUD death signal dims a PACKED living-slot
    index, and read as identity it named the wrong victim in both rounds it was
    tested on. `minimap_lifecycle` restated `track`'s continuation ceiling and
    the two drifted by a factor of two, so it quarantined appearances the
    tracker had already associated -- which is why a `defers_to` edge is checked
    as an import that must still exist.

    `reticle/ownership.py` owns the schema. An entry pointing at code that is
    gone, an owner that does not claim its own contract, a module in neither the
    entries nor the infrastructure list, and a `shipped` owner still reaching
    `prototypes/` are ERRORs. A question with no owner is a finding, deliberately
    -- `death-victim` is the product and stays on screen.
    """
    out = []
    for level, message in ownership.verify():
        out.append((ERROR if level == ERROR else "finding", message))
    return out


def check_quoted(store: Path) -> list[tuple[str, str]]:
    """Numbers quoted in prose, against the run that produced them.

    The last unenforced surface, and the one that rots fastest. `metrics`
    already stores every run with its dependencies and refuses false
    comparisons, and nothing linked the 15k lines of prose that QUOTE those
    figures to any of them -- 132 recorded runs, zero citations, so a number
    could be quoted, the code could move, and the prose would stay.

    `reticle/quoted.py` owns the `[metric:...]` form. A citation to a series
    with no recorded `pass` run is an ERROR; a quoted value disagreeing with
    the latest one is a finding, because the honest fix is sometimes the prose
    and sometimes the number. Only `docs/archive/` is exempt, as dated history,
    the same rule the DOMAIN check uses.
    """
    out = []
    for level, message in quoted.verify(rows=metrics.load(store / "notes" / "metrics.jsonl")):
        out.append((ERROR if level == ERROR else "finding", message))
    return out


NOTES_MAX_WORDS = 1000
BACKLOG_MAX_WORDS = 1500
BACKLOG_MAX_COMPLETED = 5
BACKLOG_MAX_OPEN = 3

#: The queue's section, up to the next second-level heading.
AGREED_ORDER = re.compile(r"(?ms)^## Agreed order[^\n]*\n(.*?)(?=^## |\Z)")
NUMBERED_ITEM = re.compile(r"\d+\.\s+\*\*")
#: An open item's contract: a source line inside its paragraph that opens with
#: the label and says something after it.
CONTRACT_LINES = {label: re.compile(rf"\s*{label}:\s*\S") for label in ("Acceptance", "Evidence")}


def backlog_open_blocks(backlog: str) -> list[list[str]] | None:
    """The source lines of each open item under `## Agreed order`; None without one.

    A numbered item starts on every line it opens, blank line or not; a bold
    lead starts one only at a paragraph's start, so wrapped prose that happens
    to open with bold text is not an item. An item runs to the next blank line
    or the next item.
    """
    section = AGREED_ORDER.search(backlog)
    if section is None:
        return None
    blocks, current, previous = [], None, ""
    for line in section.group(1).splitlines():
        if NUMBERED_ITEM.match(line) or (not previous.strip() and line.startswith("**")):
            current = [line]
            blocks.append(current)
        elif not line.strip():
            current = None
        elif current is not None:
            current.append(line)
        previous = line
    return blocks


def backlog_open_items(backlog: str) -> list[str] | None:
    """The first line of each open item under `## Agreed order`; None without one."""
    blocks = backlog_open_blocks(backlog)
    return None if blocks is None else [block[0] for block in blocks]


def _item_title(line: str) -> str:
    """An item's bold lead, or its first line when it has none, cut to 40 characters."""
    bold = re.search(r"\*\*(.+?)\*\*", line)
    return (bold.group(1) if bold else line).strip()[:40].rstrip()


def check_handoff(root: Path | None = None) -> list[tuple[str, str]]:
    """Warn on the small, exact handoff and queue conventions.

    `NOTES.md` and `BACKLOG.md` are bounded working documents, not logs. Both
    have size limits, `BACKLOG.md` holds at most three open items under
    `## Agreed order`, and it keeps at most five completed entries; older ones
    move to a dated file under `docs/archive/`.

    **The open-item count keyed on `## Active:` headings until 2026-09-27.**
    `BACKLOG.md` dropped them on 2026-09-23, so from then the limit and every
    contract check tied to an active task passed on nothing. It now reads the
    section the queue actually uses, and a missing section is a finding
    rather than zero items.

    **Each open item carries its own contract** (2026-09-27): an `Acceptance:`
    line names the one command that must exist and pass when the item closes,
    and an `Evidence:` line says what a reviewer must see first. Both open a
    source line inside the item's paragraph. They replace `docs/tasks.json`,
    which this check no longer reads. Items without them draw ONE finding
    that counts them and names three, so a queue written before the rule
    does not bury every other finding.
    """
    root = root or ROOT
    out = []
    notes_path = root / "NOTES.md"
    backlog_path = root / "BACKLOG.md"
    for path in (notes_path, backlog_path):
        if not path.is_file():
            return [(WARN, f"missing handoff file: {path.relative_to(root)}")]
    notes = notes_path.read_text(encoding="utf-8")
    headings = re.findall(r"(?im)^## Picking up\s*$", notes)
    if len(headings) != 1:
        out.append((WARN, f"NOTES.md has {len(headings)} Picking up headings; expected one"))
    lines = len(notes.splitlines())
    words = len(notes.split())
    if lines > 100 or words > NOTES_MAX_WORDS:
        out.append((WARN, f"NOTES.md has {lines} lines and {words} words; limits are "
                          f"100 and {NOTES_MAX_WORDS}"))
    backlog = backlog_path.read_text(encoding="utf-8")
    blocks = backlog_open_blocks(backlog)
    if blocks is None:
        out.append((WARN, "BACKLOG.md has no `## Agreed order` heading, so no open "
                          "item is counted"))
    else:
        if len(blocks) > BACKLOG_MAX_OPEN:
            out.append((WARN, f"BACKLOG.md has {len(blocks)} open items under Agreed order; "
                              f"limit is three"))
        bare = [block[0] for block in blocks
                if not all(any(rule.match(line) for line in block[1:])
                           for rule in CONTRACT_LINES.values())]
        if bare:
            named = ", ".join(f'"{_item_title(line)}"' for line in bare[:3])
            out.append((WARN, f"BACKLOG.md: {len(bare)} of {len(blocks)} open items carry "
                              f"no Acceptance: or Evidence: line -- {named}; write both on "
                              f"each item, and on every new one"))
    lines, words = len(backlog.splitlines()), len(backlog.split())
    if lines > 150 or words > BACKLOG_MAX_WORDS:
        out.append((WARN, f"BACKLOG.md has {lines} lines and {words} words; limits are "
                          f"150 and {BACKLOG_MAX_WORDS}; archive under docs/archive/"))
    done = re.search(r"(?ms)^## Completed\s*$(.*?)(?=^## |\Z)", backlog)
    n_done = len(re.findall(r"(?m)^- ", done.group(1))) if done else 0
    if n_done > BACKLOG_MAX_COMPLETED:
        out.append((WARN, f"BACKLOG.md lists {n_done} completed tasks; keep the latest "
                          f"{BACKLOG_MAX_COMPLETED} and archive the rest under docs/archive/"))
    return out


def check_documents(root: Path | None = None) -> list[tuple[str, str]]:
    """Which documents are live, and whether any route still reaches them.

    `reticle/documents.py` owns the schema of `documents.toml` and the checks.
    A register that breaks its schema, or an entry naming no file, is an ERROR:
    a declaration that points at nothing. An unregistered document, one no
    route reaches, a status its fields do not support, and an eager document
    past its budget are WARNs, for ORPHAN's reason: a document written today
    looks exactly like one abandoned, and only a person knows which.
    HANDOFF's limits for `NOTES.md` and `BACKLOG.md` enter the pickup total
    from here, so they keep one home.
    """
    base = root or ROOT
    if not (base / documents.DECLARATION).is_file():
        return [(WARN, f"{documents.DECLARATION} is absent -- which documents are "
                       f"live is declared there; see reticle/documents.py")]
    try:
        docs = documents.load(base)
    except documents.RegisterError as exc:
        return [(ERROR, problem) for problem in exc.problems]
    limits = {"NOTES.md": NOTES_MAX_WORDS, "BACKLOG.md": BACKLOG_MAX_WORDS}
    return [(ERROR if level == ERROR else WARN, message)
            for level, message in documents.verify(base, docs, handoff_limits=limits)]


#: Modules whose calls do not count as wiring: they render or diagnose what
#: the pipeline produced, so a producer reached only through them feeds no
#: stored answer. `overlay` is where `resolve_lobe` and the lifecycle hid.
RENDER_ONLY = frozenset({"overlay", "doctor"})


def _code_graph(base: Path):
    """Name-level call graph of `reticle/`: defs, what each references, calls.

    Deliberately approximate: an identifier resolves to EVERY def of that
    name, so a collision can only make more code reachable. The check can
    miss an unwired producer; it cannot invent one.
    """
    defs: dict[str, list[tuple[str, ast.AST]]] = collections.defaultdict(list)
    top: dict[str, list[ast.AST]] = {}
    for path in sorted((base / "reticle").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        rel = path.relative_to(base / "reticle").with_suffix("")
        module = ".".join(rel.parts)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        top[module] = []
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                defs[node.name].append((module, node))
            else:
                top[module].append(node)
    return defs, top


def _refs(node: ast.AST) -> set[str]:
    out = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            out.add(n.id)
        elif isinstance(n, ast.Attribute):
            out.add(n.attr)
    return out


def _reachable(defs, top, roots, skip=frozenset(), refs=_refs):
    """`(module, name)` pairs reachable from `roots`, never entering `skip`."""
    seen: set[tuple[str, str]] = set()
    queue = list(roots)
    # Module-level code runs on import: constants built from functions count.
    for module, nodes in top.items():
        if module in skip:
            continue
        for node in nodes:
            queue.extend(refs(node))
    while queue:
        name = queue.pop()
        for module, node in defs.get(name, ()):
            if module in skip or (module, name) in seen:
                continue
            seen.add((module, name))
            queue.extend(refs(node))
    return seen


def check_uncalled(base: Path | None = None) -> list[tuple[str, str]]:
    """Owned producers no CLI command reaches, and owned keywords never passed.

    `UNWIRED` asks whether a MODULE is reachable, and a module the CLI imports
    passes however little of it runs. On 2026-09-23 that hid, among others:
    `death.extract_minimap_death_marks` (no caller), the `tracks` and `xmarks`
    that `adjudicate_round_deaths` accepts and no caller passes (no death was
    ever located), `cone.resolve_lobe` (overlay only, so stored bearings keep
    their 180-degree flips), and three ability detectors reached only by
    benchmark tools. A producer is wired when a `cmd_*` in `cli` reaches it
    without passing through `RENDER_ONLY`.

    **A ratchet, because a warning was not enough.** As a warning this listed
    23 producers and stopped none: the team's adjudicated vision (lobe, track
    facing, lifecycle, observable area) ran only inside `overlay` while a new
    ability rule restated its first step. `uncalled_debt.toml` names each
    finding that existed on 2026-09-23. A finding not named there is an ERROR,
    and a named one no longer found is a WARN to delete it, so the list only
    shrinks. Wire the producer; never add to the list to pass.
    """
    base = base or ROOT
    data = ownership.load(base / "ownership.toml")
    if not data:
        return []
    defs, top = _code_graph(base)
    roots = [name for name, entries in defs.items()
             if name.startswith("cmd_") and any(m == "cli" for m, _n in entries)]
    refs = functools.cache(_refs)
    wired = _reachable(defs, top, roots, skip=RENDER_ONLY, refs=refs)
    rendered = _reachable(defs, top, roots, refs=refs) - wired

    def optional_inputs(node: ast.AST) -> list[str]:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return []
        args = node.args
        return [arg.arg for arg, default in zip(args.kwonlyargs, args.kw_defaults)
                if (isinstance(default, ast.Constant) and default.value is None) or
                (isinstance(default, (ast.Tuple, ast.List, ast.Dict)) and
                 not getattr(default, "elts", getattr(default, "keys", [1])))]

    owned = {(str(entry.get("owner", "")), name)
             for entry in data.get("_index", {}).values()
             for name in entry.get("produces", []) or []}
    watched = {arg for name, entries in defs.items() for module, node in entries
               if (module, name) in owned for arg in optional_inputs(node)}
    keyword_pattern = (re.compile(r"\b(?:" + "|".join(map(re.escape, sorted(watched))) + r")\s*=")
                       if watched else None)

    # Keywords passed to each function NAME by any call anywhere -- the
    # pipeline, tools or prototypes. An input nothing supplies is dead
    # whoever calls the function.
    passed: dict[str, set[str]] = collections.defaultdict(set)
    for tree in ("reticle", "tools", "prototypes"):
        for path in (base / tree).rglob("*.py"):
            source = path.read_text(encoding="utf-8", errors="replace")
            # An ASCII call must spell its keyword in source. Parse non-ASCII
            # files because Python normalizes Unicode identifiers in the AST.
            if keyword_pattern is None or (source.isascii() and not keyword_pattern.search(source)):
                continue
            try:
                parsed = ast.parse(source)
            except SyntaxError:
                continue
            for n in ast.walk(parsed):
                if isinstance(n, ast.Call):
                    f = n.func
                    fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
                    if fname:
                        passed[fname].update(k.arg for k in n.keywords if k.arg)

    debt_path = base / "uncalled_debt.toml"
    debt = set()
    if debt_path.is_file():
        import tomllib
        debt = set(tomllib.loads(debt_path.read_text(encoding="utf-8")).get("items", []))
    found: set[str] = set()

    def level(kind: str, key: str, names: list[str]) -> str:
        ids = {f"{kind}:{key}:{n}" for n in names}
        found.update(ids)
        return WARN if ids <= debt else ERROR

    out: list[tuple[str, str]] = []
    for key, entry in sorted(data.get("_index", {}).items()):
        owner = str(entry.get("owner", ""))
        if not owner:
            continue
        cold, render, unpassed = [], [], []
        for name in entry.get("produces", []) or []:
            here = [n for m, n in defs.get(name, ()) if m == owner]
            if not here or name.isupper():
                continue
            node = here[0]
            if (owner, name) in rendered:
                render.append(name)
            elif (owner, name) not in wired:
                cold.append(name)
            for arg in optional_inputs(node):
                if arg not in passed[name]:
                    unpassed.append(f"{name}({arg}=)")
        if cold:
            out.append((level("cold", key, cold), f"[{key}] `{owner}` produces {', '.join(cold)} and "
                              f"no CLI command reaches it -- wire it, or say "
                              f"in the entry why it waits"))
        if render:
            out.append((level("render", key, render), f"[{key}] `{owner}` produces {', '.join(render)}, "
                              f"reached only through {', '.join(sorted(RENDER_ONLY))} "
                              f"-- it draws, and feeds no stored answer"))
        if unpassed:
            out.append((level("unpassed", key, unpassed), f"[{key}] no call anywhere passes {', '.join(unpassed)} "
                              f"-- that input is accepted and never supplied"))
    paid = sorted(debt - found)
    if paid:
        out.append((WARN, f"{len(paid)} uncalled_debt.toml item(s) now wired or gone -- "
                          f"delete them: {', '.join(paid[:5])}"))
    check_uncalled.found = sorted(found)
    return out



#: Store methods that read a stored input, and the input `plan` names it by.
_INPUT_READS = {"read_hud": {"hud"}, "read_roster": {"roster"}, "read_minimap": {"minimap"},
                "rounds_path": {"rounds"}, "read_rounds": {"rounds"}, "load_lineup": {"lineup"},
                # the player-cast gate's stored inputs (`ability_timeline`)
                "stored_gate_inputs": {"hud", "killfeed_portrait", "death",
                                       "combat_report_round", "tray_kit", "menu_open",
                                       "ult_cast", "tray_countdown"},
                # rounds built in memory: the round rule is an input, compared
                # as a code stamp (`plan._code` on `ROUND_VERSION`)
                "build_rounds": {"round_rule"}}

#: `cli.py` helpers whose reads feed no stored stream, and why.
_INPUT_READ_EXEMPT = {
    "_tray_kit_values": "`tray-kit --record`'s quoted numbers, recorded to metrics, not the stream",
}


def _cli_reads_writes(path: Path) -> dict[str, tuple[set[str], set[str]]]:
    """function -> (streams it writes, stored inputs it reads), for each
    top-level function of `path`, with the reads of the module's own helpers
    it calls folded in. Only literal stream names count."""
    return {name: (set(w), set(r))
            for name, (w, r) in _cli_analysis(path.read_text(encoding="utf-8")).items()}


@functools.lru_cache(maxsize=2)
def _cli_analysis(text: str) -> dict[str, tuple[frozenset[str], frozenset[str]]]:
    """`_cli_reads_writes` of one source text. Parsing `cli.py` is nearly all
    of `check_inputs`' cost and the answer depends only on the text, so one
    process parses each version once."""
    tree = ast.parse(text)
    direct: dict[str, tuple[set[str], set[str], set[str]]] = {}
    for fn in tree.body:
        if not isinstance(fn, ast.FunctionDef):
            continue
        writes, reads, calls = set(), set(), set()
        for node in ast.walk(fn):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)
            lits = [a.value for a in node.args
                    if isinstance(a, ast.Constant) and isinstance(a.value, str)]
            if name == "write_events" and lits:
                writes.add(lits[0])
            elif name in ("read_events", "events_version", "_head", "head_row") and lits:
                reads.add(lits[0])
            elif name in _INPUT_READS:
                reads |= _INPUT_READS[name]
            elif isinstance(f, ast.Name):
                calls.add(f.id)
        direct[fn.name] = (writes, reads, calls)

    def reach(name, seen):
        w, r, calls = direct[name]
        r = set(r)
        for c in calls:
            if (c in direct and c not in seen and not direct[c][0]
                    and c not in _INPUT_READ_EXEMPT):
                seen.add(c)
                r |= reach(c, seen)
        return r

    return {n: (frozenset(w), frozenset(reach(n, {n}))) for n, (w, _, _) in direct.items()}


def check_inputs(store: Path) -> list[tuple[str, str]]:
    """A stream that read a stored input `plan` does not compare.

    `plan` calls a stream stale when an input it recorded no longer matches
    the input as stored (`plan.inputs_moved`), so an input a writer reads and
    no declaration names is one whose change stales nothing: `death` stamped
    the code's HUD version while it read the stored table, and the lifetimes
    cache keyed on four of its inputs. Two halves:

    - the code: a `reticle/cli.py` command that writes a declared stream and
      reads, by a literal name, a stored stream or table none of the written
      streams declares (`plan.stream_inputs`, a derived spec's `upstream`);
    - the store: a stamp-like key (`*_version`, `inputs.*`, `geometry*`,
      `menu_open`, `tray_kit`, `occluders`) in a stored first row that `plan`
      does not compare (`plan.compared_paths`) and `plan.NOT_INPUTS` does not
      excuse.

    It also fails on a loop in the declared inputs (`plan.input_cycles`): the
    death stream recorded the bytes of the reliability table built from the
    deaths, so each rerun restaled the next. A loop runs only through a
    declared `plan.FEEDBACK` edge, whose stamp runs once.

    What it misses: a read inside a module the command calls (`self_icon`,
    `minimap_objects`, `enemy_tracks` read through `read_session`), a stream
    named by a variable, a file read outside the store's read methods (the
    reliability table, the catalogue), and an input a writer reads and never
    records -- the store half sees only what was recorded.
    """
    from reticle import plan
    from reticle.version import ROUND_VERSION
    out: list[tuple[str, str]] = []
    declared = plan.stream_inputs()
    specs = {s["stream"]: s for s in plan.derived_streams()}
    compared = plan.compared_paths()
    # A reader decodes; what it reads from the store gates which frames it
    # samples, and a moved gate is the scan's question, not plan's.
    readers = {s for s, *_ in (*plan.reader_streams(), *plan.ability_streams())}
    for fn, (writes, reads) in sorted(_cli_reads_writes(ROOT / "reticle" / "cli.py").items()):
        mine = [w for w in writes if w in compared and w not in readers]
        if not mine:
            continue
        allowed = set(writes)
        for w in mine:
            # An identity stream is rewritten by its parent's command, and
            # follows the parent's inputs through it.
            for x in (w, *(specs[w]["upstream"] if specs.get(w, {}).get("identity") else ())):
                allowed |= plan.input_streams(x) | set(specs.get(x, {}).get("upstream", ()))
                if any(d["probe"] in ("lineup", "lineup_file")
                       for d in declared.get(x, {}).values()):
                    allowed.add("lineup")
                if any(d["probe"] == "=" + ROUND_VERSION for d in declared.get(x, {}).values()):
                    allowed.add("round_rule")
        extra = sorted(reads - allowed)
        if extra:
            out.append((ERROR, f"cli.{fn} writes {', '.join(sorted(mine))} and reads "
                               f"{', '.join(extra)}, which no declaration names -- declare "
                               f"it in plan.stream_inputs so plan compares it"))
    # A loop in the declared inputs restales its own streams on every rerun.
    for cycle in plan.input_cycles():
        out.append((ERROR, f"the declared inputs loop: {' <- '.join(cycle)} -- break it, or "
                           f"declare the edge in plan.FEEDBACK with a stamp that runs once"))
    for stream, name in sorted(plan.FEEDBACK):
        if name not in declared.get(stream, {}):
            out.append((ERROR, f"plan.FEEDBACK names {stream} input {name}, which "
                               f"plan.stream_inputs does not declare"))
    events = store / "events"
    if not events.is_dir():
        return out
    stampy =re.compile(r"(_version$|^geometry|^menu_open$|^tray_kit$|^occluders$)")
    undeclared: dict[tuple[str, str], int] = collections.Counter()
    for stream, paths in sorted(compared.items()):
        d = events / stream
        if not d.is_dir():
            continue
        needle = b'"event_kind":"identity_distribution"' if specs.get(stream, {}).get("identity") else None
        for f in sorted(d.glob("*.jsonl")):
            head = None
            with open(f, "rb") as fh:
                for line in fh:
                    if needle is None or needle in line:
                        head = json.loads(line)
                        break
            if not isinstance(head, dict):
                continue
            keys = [k for k in head if stampy.search(k)]
            if isinstance(head.get("inputs"), dict):
                keys += [f"inputs.{k}" for k in head["inputs"]]
            for k in keys:
                if k in paths or k.rsplit(".", 1)[-1] in plan.NOT_INPUTS:
                    continue
                undeclared[(stream, k)] += 1
    for (stream, k), n in sorted(undeclared.items()):
        out.append((ERROR, f"{stream} records {k} on {n} sessions and plan does not compare "
                           f"it -- declare it in plan.stream_inputs, or say why it is not an "
                           f"input in plan.NOT_INPUTS"))
    return out


def check_replay_layer(store: Path) -> list[tuple[str, str]]:
    """A session with a kept replay and no current replay layer.

    In the spirit of PROMOTE: a replay kept for a capture is truth no scorer,
    slot model or overlay can read until its layer is built
    (`replay_layer`, docs/REPLAY_LAYER.md), and before the layer every
    consumer re-derived the joins itself. The kept replays' manifest names
    each one's capture session; each such session needs its layer current
    against its parse, stored deaths, geometry, frame grid, lineup and code
    (`replay_layer.session_status`), and `reticle plan` names the command."""
    from .replay_layer import session_status
    from .replay_source import replay_manifest
    out = []
    for f in replay_manifest(store).get("files") or []:
        sid = f.get("capture_session")
        if not sid:
            continue
        st = session_status(sid, store)
        if st is None or st["state"] == "current":
            continue
        why = st["state"] + (f" ({', '.join(st['moved'])})" if st.get("moved") else "")
        out.append((ERROR, f"{sid} keeps replay {st['match'][:8]} and its replay layer is "
                           f"{why} -- run `{st['command']}`"))
    return out


def run(store: Path, verbose: bool = False) -> list[tuple[str, str, str]]:
    checks = (("HANDOFF", check_handoff), ("DOCS", check_documents),
              ("DUPLICATE", check_duplicate), ("UNWIRED", check_unwired),
              ("UNCALLED", check_uncalled),
              ("ORPHAN", check_orphan), ("DOMAIN", check_domain),
              ("MOVEMENT", check_movement),
              ("LAYER", check_layer), ("CONSUMER", check_consumer),
              ("OWNERSHIP", check_ownership),
              ("QUOTED", lambda: check_quoted(store)),
              ("PROMOTE", lambda: check_promote(store)),
              ("REPLAY_LAYER", lambda: check_replay_layer(store)),
              ("SESSION_STATIC", lambda: check_session_static(store)),
              ("GEOMETRY", lambda: check_geometry(store)),
              ("SHADE", lambda: check_shade(store)),
              ("OCCLUDERS", lambda: check_occluders(store)),
              ("LINES", lambda: check_lines(store)),
              ("COVERAGE", lambda: check_coverage(store)),
              ("MANIFEST", lambda: check_manifest(store)),
              ("SOURCE", lambda: check_source(store, verbose)),
              ("FURNITURE", lambda: check_furniture(store)),
              ("STALL", lambda: check_stalls(store)),
              ("INPUTS", lambda: check_inputs(store)))
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
