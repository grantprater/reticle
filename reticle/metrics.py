"""Run summaries, and what may be compared with what (design doc SS7 addendum).

A tool that prints its numbers costs the same on every run and says nothing on
the second. This module stores each run's summary instead and prints the DIFF,
so a quiet run is quiet and a moved number is loud. Two things fall out of that
which are worth more than the saved tokens.

**The control is derived, not declared.** `version.py` already says a version
is bumped when the MEANING of a column changes. Read that as a contract and it
becomes checkable: if nothing a number depends on has changed, the number must
not change either. Same deps and a different value is not a result, it is the
code having changed without its version changing -- an uncommitted edit, a
forgotten bump, or nondeterminism. That is the standing check the conventions
ask for by hand ("confirm a known number comes back -- TP 43 / FN 3 / FP 80"),
enforced in code rather than remembered, and it costs one line of output.

**Comparability is a property of the dependency chain, not of the field.**
`recall` keeps its name and its dtype across a class split and stops being the
same quantity. So each record declares what it was computed FROM, and deps come
in two kinds, which is the whole design:

    deps      INVALIDATING -- code version, class definition, sampling rule.
              Different deps is not a comparison at all. New baseline.
    context   EXPLANATORY -- label count, pool, session set. Different context
              is a comparison, and it is the interesting one: labels arriving
              is the main reason a number here legitimately moves.

Collapse those two and it degrades either way: treat everything as invalidating
and every code touch resets the baseline, treat nothing as invalidating and you
get confident false comparisons across a boundary.

The four verdicts follow from the pair, and are total:

    INCOMPARABLE  deps differ -- different question, so no delta is shown
    BROKEN        deps and context both same, numbers differ
    CHANGED       context differs, numbers may move -- annotated with what grew
    UNCHANGED     nothing moved -- the quiet case, one line

Statuses are separate from verdicts and describe the RUN, not a comparison:
`pass`, `cannot-answer` (n too small, no painted mask -- the tool refusing),
`broken` (a declared control missed). Only `pass` rows are ever a baseline, and
that gate is structural: `baseline()` has no flag to include the others. A
broken run that silently became the new normal would re-baseline the fault and
the check would never fire again -- the seeding mistake in a third costume,
after `minimap_agent` and `answer()`'s refusal of `claude-*` provenance.

    python -m reticle.metrics --self-test
    python -m reticle.metrics                     # every tracked series
    python -m reticle.metrics --tool enemy_detect
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import sys
import time
from pathlib import Path

STORE = Path.home() / "reticle-store"
LOG = STORE / "notes" / "metrics.jsonl"

#: Run statuses. Only PASS is ever used as a baseline.
PASS = "pass"
CANNOT_ANSWER = "cannot-answer"
BROKEN = "broken"
STATUSES = (PASS, CANNOT_ANSWER, BROKEN)

#: Comparison verdicts, total over (deps moved?, context moved?, values moved?).
INCOMPARABLE = "INCOMPARABLE"
BROKEN_CMP = "BROKEN"
CHANGED = "CHANGED"
UNCHANGED = "UNCHANGED"

#: Default numeric tolerance. Exact: a count that moves by one is a finding,
#: and a float that moves at all without a dep change is nondeterminism.
DEFAULT_TOL = 0.0


def load(path: Path | None = None) -> list[dict]:
    """Rows in file order, which is time order -- the log is append-only."""
    p = Path(path) if path else LOG
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def key(row) -> tuple[str, str, str]:
    """What makes two runs the same series: tool, part, session."""
    return (row["tool"], row.get("part") or "", row.get("session") or "")


def _close(a, b, tol: float) -> bool:
    if a is None or b is None:
        return a is b
    numeric = (int, float)
    if isinstance(a, numeric) and isinstance(b, numeric) \
            and not isinstance(a, bool) and not isinstance(b, bool):
        return abs(a - b) <= tol
    return a == b


def _differing(a: dict, b: dict) -> list[str]:
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def fingerprint(*objs, **params) -> str:
    """Short hash of function SOURCE plus named parameters.

    A dependency is DERIVED here rather than declared, because a hand-kept list
    rots in the one direction that is silent: add a knob, forget to list it,
    and every later comparison crosses a boundary it should have refused.
    `inspect.getsource` tracks the behaviour that produced the number and
    ignores edits elsewhere in the file, which is the granularity that keeps
    this useful -- fingerprinting a whole module would reset the baseline on a
    comment, and that is the failure mode where per-field comparability stops
    being worth having.

    Editing a comment INSIDE a fingerprinted function does reset its baseline.
    That is the over-declaring side of the trade, taken on purpose: a spurious
    INCOMPARABLE is visible and cheap, a missed one is silent and expensive.
    """
    h = hashlib.sha1()
    for o in objs:
        try:
            h.update(inspect.getsource(o).encode("utf-8"))
        except (OSError, TypeError):
            h.update(repr(o).encode("utf-8"))
    for k in sorted(params):
        h.update(f"{k}={params[k]!r}".encode("utf-8"))
    return h.hexdigest()[:12]


def record(tool, *, part="", session="", values, deps, context=None,
           controls=(), status=None, tol=None, note="", log_path=None,
           **extra) -> dict:
    """Append one run summary.

    `deps` is what invalidates a comparison and `context` is what merely
    explains one; putting a field in the wrong one is the only way to get this
    wrong quietly, so both are required rather than inferred.

    `status` is derived from `controls` when not given. A control is an
    EXTERNAL truth (`checks.KNOWN_KD`, a fixture's answer), never this tool's
    own previous output -- that would be scoring the thing against itself.
    """
    controls = [dict(c) for c in controls]
    for c in controls:
        if "ok" not in c:
            c["ok"] = _close(c.get("observed"), c.get("expected"),
                             c.get("tol", DEFAULT_TOL))
    if status is None:
        status = BROKEN if any(not c["ok"] for c in controls) else PASS
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}, got {status!r}")

    row = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "tool": tool, "part": part, "session": session,
           "status": status, "values": dict(values), "deps": dict(deps),
           "context": dict(context or {}), "controls": controls,
           "tol": dict(tol or {}), "note": note, **extra}
    log = Path(log_path) if log_path else LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + chr(10))
    return row


def baseline(rows, row) -> dict | None:
    """The most recent PASS run of the same series strictly before `row`.

    There is deliberately no flag to consider a non-PASS run. A broken run
    admitted here would become the new normal and the check would stop firing.
    """
    k = key(row)
    seen = None
    for r in rows:
        if r is row:
            break
        if key(r) == k and r.get("status") == PASS:
            seen = r
    return seen


def compare(prev: dict | None, cur: dict) -> dict:
    """Field-wise verdict between two runs of one series.

    Returns `verdict`, the deps and context that moved, and per moved value a
    `(before, after)` pair. A value is only ever shown when the verdict says it
    means something.
    """
    if prev is None:
        return {"verdict": None, "reason": "no comparable baseline",
                "deps_changed": [], "context_changed": [], "values": {}}

    tol = {**prev.get("tol", {}), **cur.get("tol", {})}
    deps_changed = _differing(prev.get("deps", {}), cur.get("deps", {}))
    ctx_changed = _differing(prev.get("context", {}), cur.get("context", {}))
    pv, cv = prev.get("values", {}), cur.get("values", {})
    moved = {k: (pv.get(k), cv.get(k)) for k in sorted(set(pv) | set(cv))
             if not _close(pv.get(k), cv.get(k), tol.get(k, DEFAULT_TOL))}

    if deps_changed:
        # Not a comparison. Showing a delta across this boundary is the
        # confident-wrongness failure the module exists to prevent, so the
        # numbers are withheld rather than printed with a caveat.
        verdict = INCOMPARABLE
        reason = "deps changed: " + ", ".join(deps_changed)
        moved = {}
    elif moved and not ctx_changed:
        verdict = BROKEN_CMP
        reason = ("nothing it depends on changed and the numbers did -- "
                  "an unversioned edit or nondeterminism")
    elif moved:
        verdict = CHANGED
        reason = "context changed: " + ", ".join(ctx_changed)
    else:
        verdict, reason = UNCHANGED, ""
    return {"verdict": verdict, "reason": reason, "deps_changed": deps_changed,
            "context_changed": ctx_changed, "values": moved,
            "before_at": prev.get("at"), "after_at": cur.get("at")}


def diff(tool=None, part=None, session=None, rows=None, log_path=None) -> list[dict]:
    """Latest run of every matching series, against its baseline."""
    rows = load(log_path) if rows is None else rows
    latest: dict[tuple, dict] = {}
    for r in rows:
        if tool and r.get("tool") != tool:
            continue
        if part is not None and (r.get("part") or "") != part:
            continue
        if session and r.get("session") != session:
            continue
        latest[key(r)] = r
    out = []
    for k, cur in sorted(latest.items()):
        out.append({"key": k, "run": cur, **compare(baseline(rows, cur), cur)})
    return out


def control_history(rows, k) -> list[int]:
    """1 if every control held on that run, else 0 -- in time order.

    This is the only genuinely BINARY series here, so it is the only one
    `judgement.change_point` is applied to. A continuous metric needs a
    different test, and guessing at one would manufacture regimes -- the exact
    failure that test is Bonferroni-corrected against in the first place.
    """
    out = []
    for r in rows:
        if key(r) != k or not r.get("controls"):
            continue
        out.append(1 if all(c.get("ok") for c in r["controls"]) else 0)
    return out


def _fmt(v) -> str:
    return f"{v:.4g}" if isinstance(v, float) else str(v)


def report(rows=None, tool=None, log_path=None, verbose=False) -> str:
    """One line per series when nothing moved; detail only when it did."""
    rows = load(log_path) if rows is None else rows
    if not rows:
        return "no runs recorded -- nothing has called metrics.record() yet"
    ds = diff(tool=tool, rows=rows)
    if not ds:
        return f"no runs for tool {tool!r}"

    lines = []
    for d in ds:
        name = " ".join(x for x in d["key"] if x)
        run, v = d["run"], d["verdict"]
        st = run.get("status")
        if st != PASS:
            bad = [c["name"] for c in run.get("controls", []) if not c.get("ok")]
            lines.append(f"{name}: {st.upper()}"
                         + (f" -- controls missed: {', '.join(bad)}" if bad else "")
                         + (f" -- {run['note']}" if run.get("note") else ""))
            lines.append("    not a baseline; the last passing run still is.")
            continue
        if v is None:
            lines.append(f"{name}: first run, {len(run.get('values', {}))} values")
        elif v == UNCHANGED:
            lines.append(f"{name}: unchanged")
        else:
            lines.append(f"{name}: {v} -- {d['reason']}")
            for kk, (a, b) in d["values"].items():
                lines.append(f"    {kk:<20} {_fmt(a):>12} -> {_fmt(b):>12}")
            if v == CHANGED:
                for kk in d["context_changed"]:
                    lines.append(f"    ({kk} now {_fmt(run.get('context', {}).get(kk))})")
        if verbose:
            for kk, val in sorted(run.get("values", {}).items()):
                lines.append(f"      {kk:<20} {_fmt(val):>12}")

        hist = control_history(rows, d["key"])
        if len(hist) >= 10:
            try:
                from .judgement import change_point
            except ImportError:
                change_point = None
            cp = change_point(hist) if change_point else None
            if cp:
                lines.append(f"    controls: regime change at #{cp['index']}")
    return "\n".join(lines)


def _self_test() -> int:
    """Exercise all four verdicts and the baseline gate on a temp log."""
    import tempfile
    tmp = Path(tempfile.gettempdir()) / "metrics-selftest.jsonl"
    tmp.unlink(missing_ok=True)
    ok = True

    def check(label, got, want):
        nonlocal ok
        if got != want:
            ok = False
            print(f"  FAIL {label}: got {got!r}, want {want!r}")
        else:
            print(f"  ok   {label}: {got}")

    base = dict(tool="t", part="det", session="s", log_path=tmp)
    record(values={"tp": 43, "fp": 80}, deps={"v": "1"}, context={"n": 164}, **base)

    # Same deps, same context, same numbers -> quiet.
    record(values={"tp": 43, "fp": 80}, deps={"v": "1"}, context={"n": 164}, **base)
    check("unchanged", diff(rows=load(tmp))[0]["verdict"], UNCHANGED)

    # Same deps, same context, a moved number -> unversioned edit.
    record(values={"tp": 44, "fp": 80}, deps={"v": "1"}, context={"n": 164}, **base)
    d = diff(rows=load(tmp))[0]
    check("broken", d["verdict"], BROKEN_CMP)
    check("broken names the value", list(d["values"]), ["tp"])

    # Context grew -> a real measurement change, not a fault.
    record(values={"tp": 50, "fp": 80}, deps={"v": "1"}, context={"n": 373}, **base)
    check("changed", diff(rows=load(tmp))[0]["verdict"], CHANGED)

    # Deps moved -> not a comparison, and no delta is shown.
    record(values={"tp": 99, "fp": 1}, deps={"v": "2"}, context={"n": 373}, **base)
    d = diff(rows=load(tmp))[0]
    check("incomparable", d["verdict"], INCOMPARABLE)
    check("incomparable withholds values", d["values"], {})

    # A failed control marks the run broken, and it must not become a baseline.
    record(values={"tp": 0, "fp": 0}, deps={"v": "2"}, context={"n": 373},
           controls=[{"name": "known_kd", "expected": 19, "observed": 3}], **base)
    rows = load(tmp)
    check("control fails -> broken", rows[-1]["status"], BROKEN)
    check("broken run is not a baseline",
          baseline(rows, rows[-1])["values"]["tp"], 99)

    # cannot-answer is likewise never a baseline.
    record(values={}, deps={"v": "2"}, context={"n": 0},
           status=CANNOT_ANSWER, note="no painted mask", **base)
    rows = load(tmp)
    check("cannot-answer is not a baseline",
          baseline(rows, rows[-1])["values"]["tp"], 99)

    # A tolerance suppresses a move it covers, and only that move.
    record(values={"tp": 99, "fp": 1}, deps={"v": "2"}, context={"n": 373}, **base)
    record(values={"tp": 99.4, "fp": 3}, deps={"v": "2"}, context={"n": 373},
           tol={"tp": 0.5}, **base)
    d = diff(rows=load(tmp))[0]
    check("tolerance covers tp, not fp", list(d["values"]), ["fp"])

    tmp.unlink(missing_ok=True)
    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--tool", default=None)
    ap.add_argument("--log", default=None)
    ap.add_argument("--verbose", action="store_true",
                    help="print every value, not only the ones that moved")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    print(report(tool=a.tool, log_path=Path(a.log) if a.log else None,
                 verbose=a.verbose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
