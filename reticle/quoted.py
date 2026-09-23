r"""Numbers quoted in prose, checked against the run that produced them.

    .\.venv\Scripts\python.exe -m reticle.quoted [--uncited]

Why this exists
---------------
This was the last unenforced surface, and it is the one that rots fastest.
`metrics.py` already stores every run with its dependencies and refuses false
comparisons; `domain/*.toml` holds what is true of the game; `architecture.toml`
holds the layering. None of them touch the 15k lines of markdown and docstrings
that QUOTE measured figures. There were 132 recorded runs and not one link from
prose to any of them, so a number could be quoted, the code could move, and the
prose would stay -- silently, forever. Every figure cited in the session that
built this was read out of prose rather than out of the store.

The citation
------------
    [metric:<tool>/<part>#<field>=<value>]
    [metric:<tool>/<part>@<session>#<field>=<value>]
    [metric:<tool>#<field>=<value>]

So `[metric:proposal_audit/acquisition@d95cfad5693a#recall=0.9375]`. The series
name is permissive because real ones contain dots, spaces and pipes
(`floor_mask_eval/reticle.minimap | PLANT`); the field and value are strict.

**The citation carries the VALUE, which is the whole point.** A citation naming
only its series would prove a measurement exists and say nothing about whether
the number beside it is still true -- and a wrong number that looks sourced is
worse than one that looks unsourced. So the check compares the quoted value to
the latest `pass` row of that series and reports the file when they disagree.

Three findings, and the levels are deliberate
----------------------------------------------
* a citation whose series has NO recorded run, or whose field that run does not
  carry, is an **ERROR** -- it is a reference to something that does not exist,
  the same rule `domain` uses for a dangling fact;
* a quoted value that DISAGREES with the latest `pass` row is a finding naming
  the file and both numbers. It is not an error because the honest fix is
  sometimes to update the prose and sometimes to look at why the number moved,
  and a checker that blocks on every improvement gets switched off;
* a recorded series that no document cites is a finding -- a measurement nobody
  uses, the same lost-in-the-shuffle failure `domain` reports for facts.

What is exempt, and why
-----------------------
`docs/archive/`. Its files are dated records of what was known then, so a
figure inside them was true when written and rewriting it would be a lie about
what was known then. That is the same HISTORY convention `reticle/domain.py`
uses, for the same reason. `NOTES.md` and `BACKLOG.md` are bounded working
documents and are checked like any other.
"""
from __future__ import annotations

import re
from pathlib import Path

from reticle import metrics

ROOT = Path(__file__).resolve().parent.parent

#: The one form. Permissive on the series, strict on the field and the value,
#: because a series name is data and a field name is an identifier.
CITE = re.compile(
    r"\[metric:"
    r"(?P<series>[^\]#@]+?)"
    r"(?:@(?P<session>[^\]#@]+?))?"
    r"#(?P<field>[A-Za-z_][A-Za-z0-9_]*)"
    r"=(?P<value>[^\]]+)\]")

#: Dated records live under HISTORY_PREFIXES. See the docstring.
HISTORY = ()

#: Where prose lives. `domain/` holds no figures and `tests/` asserts its own.
#: Scanned RECURSIVELY: a flat listing could not see `reticle/adjudication/`,
#: so five modules could quote any figure they liked and the check reported the
#: series as uncited instead. `architecture.py` had the same blind spot for the
#: same reason -- a directory is not a `*.py`.
SCAN_DIRS = ("", "docs", "reticle", "prototypes", "tools")
SCAN_SUFFIXES = (".py", ".md")

#: This module quotes the citation form in its own docstring as an EXAMPLE.
EXAMPLE_ONLY = frozenset({"reticle/quoted.py", "tests/test_quoted.py"})

#: A quoted figure is prose, so it is rounded. Compare at the precision the
#: prose actually states rather than demanding the stored float back.
def _agrees(quoted: str, stored) -> bool:
    """Does the prose's number match the store, at the prose's own precision?"""
    text = quoted.strip().rstrip("%")
    try:
        want = float(text)
    except ValueError:
        return str(stored).strip() == quoted.strip()
    if stored is None:
        return False
    try:
        got = float(stored)
    except (TypeError, ValueError):
        return False
    if quoted.strip().endswith("%"):
        got *= 100.0
    decimals = len(text.split(".")[1]) if "." in text else 0
    return round(got, decimals) == round(want, decimals)


def scan_files(root: Path | None = None) -> list[Path]:
    """The repo's prose, history and self-referential examples excluded."""
    base = Path(root) if root else ROOT
    out: list[Path] = []
    out_names: set[str] = set()
    for relative in SCAN_DIRS:
        directory = base / relative if relative else base
        if not directory.is_dir():
            continue
        walk = (sorted(directory.rglob("*")) if relative
                else sorted(directory.iterdir()))
        for path in walk:
            if not path.is_file() or path.suffix not in SCAN_SUFFIXES:
                continue
            name = path.relative_to(base).as_posix()
            if name in HISTORY or name in EXAMPLE_ONLY:
                continue
            if name in out_names:
                continue
            out_names.add(name)
            out.append(path)
    return out


def citations(root: Path | None = None) -> list[dict]:
    """Every quoted figure found, with the file and line that quotes it."""
    base = Path(root) if root else ROOT
    out = []
    for path in scan_files(base):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in CITE.finditer(text):
            out.append({
                "file": path.relative_to(base).as_posix(),
                "line": text.count("\n", 0, match.start()) + 1,
                "series": match.group("series").strip(),
                "session": (match.group("session") or "").strip(),
                "field": match.group("field"),
                "quoted": match.group("value").strip(),
            })
    return out


def latest_pass(rows: list[dict]) -> dict[tuple[str, str], dict]:
    """The most recent `pass` run per (series, session).

    Only `pass` rows, and for the reason `metrics.baseline` gives: a broken run
    that became the reference would re-baseline the fault and nothing would
    ever fire again.
    """
    out: dict[tuple[str, str], dict] = {}
    for row in rows:
        if row.get("status") != metrics.PASS:
            continue
        tool, part, session = metrics.key(row)
        series = f"{tool}/{part}" if part else tool
        out[(series, session)] = row
    return out


def _resolve(cite: dict, index: dict[tuple[str, str], dict]) -> dict | None:
    """The run a citation points at. An unsessioned citation may name any one."""
    exact = index.get((cite["series"], cite["session"]))
    if exact is not None:
        return exact
    if cite["session"]:
        return None
    matches = [row for (series, _s), row in index.items()
               if series == cite["series"]]
    return matches[-1] if len(matches) == 1 else None


def verify(root: Path | None = None,
           rows: list[dict] | None = None) -> list[tuple[str, str]]:
    """`(level, message)` pairs. ERROR blocks; WARN is a list to work off."""
    base = Path(root) if root else ROOT
    rows = metrics.load() if rows is None else rows
    index = latest_pass(rows)
    found = citations(base)
    out: list[tuple[str, str]] = []
    cited: set[str] = set()

    for cite in found:
        where = f"{cite['file']}:{cite['line']}"
        run = _resolve(cite, index)
        if run is None:
            sessions = sorted({s for (series, s) in index if series == cite["series"]})
            if not sessions:
                out.append(("ERROR", f"{where} quotes metric "
                                     f"`{cite['series']}`, which has no recorded "
                                     f"`pass` run"))
            elif cite["session"]:
                out.append(("ERROR", f"{where} quotes metric "
                                     f"`{cite['series']}` for session "
                                     f"`{cite['session']}`, which has no "
                                     f"recorded `pass` run; recorded: "
                                     f"{', '.join(s or '-' for s in sessions)}"))
            else:
                out.append(("ERROR", f"{where} quotes metric "
                                     f"`{cite['series']}` with no session, and "
                                     f"it has {len(sessions)} -- name one with "
                                     f"@session: "
                                     f"{', '.join(s or '-' for s in sessions)}"))
            continue
        tool, part, session = metrics.key(run)
        cited.add(f"{tool}/{part}" if part else tool)
        values = run.get("values") or {}
        if cite["field"] not in values:
            out.append(("ERROR", f"{where} quotes `{cite['field']}` of "
                                 f"`{cite['series']}`, which that run does not "
                                 f"record; it has "
                                 f"{', '.join(sorted(values)[:8])}"))
            continue
        stored = values[cite["field"]]
        if not _agrees(cite["quoted"], stored):
            out.append(("WARN", f"{where} quotes {cite['series']} "
                                f"{cite['field']}={cite['quoted']} and the "
                                f"latest pass run records {stored} -- the "
                                f"document is stale, or the number moved and "
                                f"nobody looked"))

    # Collapsed to one line, as `domain` does for uncited facts. Sixteen true
    # findings still train people to skip a check; the list belongs behind
    # `--uncited` where it can be worked through.
    recorded = {series for (series, _s) in index}
    uncited = sorted(recorded - cited)
    if uncited:
        out.append(("WARN", f"{len(uncited)} recorded metric series that no "
                            f"document cites -- measurements nobody uses: "
                            + ", ".join(uncited[:5])
                            + (" ..." if len(uncited) > 5 else "")
                            + "  (reticle.quoted --uncited lists them)"))
    return out


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--uncited", action="store_true",
                        help="list recorded series no document cites")
    args = parser.parse_args(argv)

    rows = metrics.load()
    index = latest_pass(rows)
    if args.uncited:
        cited = {c["series"] for c in citations()}
        for series in sorted({s for (s, _x) in index} - cited):
            sessions = sorted({x for (s, x) in index if s == series})
            print(f"{series}   sessions: "
                  f"{', '.join(x or '-' for x in sessions)}")
        return 0

    problems = verify(rows=rows)
    for level, message in problems:
        print(f"{level:6s} {message}")
    errors = sum(1 for level, _m in problems if level == "ERROR")
    print(f"\n{len(citations())} quoted figure(s), {len(index)} recorded series, "
          f"{len(problems)} finding(s), {errors} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
