"""Which documents are live, what each one is, and what reaches it.

    .\\.venv\\Scripts\\python.exe -m reticle doctor      (the DOCS check)

The declaration
---------------
`documents.toml` at the root holds one `[[document]]` per live document.
Every entry states `path`, `kind`, `status` and `since` (YYYY-MM-DD, the date
the document took its status). The optional fields:

* `eager` -- every session reads it at pickup; it then needs `budget_words`,
  except `NOTES.md` and `BACKLOG.md`, whose limits HANDOFF owns;
* `implemented_by` -- what realises a `partial` or `implemented` design or
  plan: `owns:<ownership id>`, `cmd:<reticle subcommand>`, or a path under
  `reticle/` or `tools/`. A prototype implements nothing until it is wired;
* `superseded_by` -- the registered document that replaces this one;
* `generated_by` -- the command that writes it;
* `remains` -- one sentence: what no code does yet;
* `waits_for` -- one sentence: what starts the work.

`KINDS` and `ALLOWED` below give the vocabulary. `load` raises
`RegisterError` on a schema fault and names the entry. `docs/archive/` is
dated history and is never registered. The argument for the register is in
`PROJECT_GUIDE.md`, "Repository declarations and why they exist".

The checks
----------
Each returns `(level, message)` pairs, as `ownership.verify` does.

* `unregistered` -- a live document in `SCOPE` with no entry is a WARN; an
  entry naming no file is an ERROR, a dangling reference;
* `unreached` -- a document that is neither eager nor superseded must be
  reached by Markdown links from a root: an eager document, `README.md`, a
  skill, or a module in `reticle/` or `tools/` that names the file. History
  keeps nothing alive, and this module's own prose revives nothing;
* `inconsistent` -- a superseded document names a registered successor, and a
  partial or implemented one names targets that resolve;
* `over_budget` -- an eager document stays under its `budget_words`.

Only a schema fault and a missing file are ERRORs; the rest are findings.
"""
from __future__ import annotations

import datetime
import fnmatch
import posixpath
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import unquote

from reticle import ownership
from reticle.domain import HISTORY_PREFIXES

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = "documents.toml"

#: What a document is. The kind decides which statuses it may carry.
KINDS = frozenset({"rules", "routing", "reference", "generated", "design",
                   "plan", "findings", "handoff", "contract"})
#: A rule, a route or a reference is current or it is gone; a design or a plan
#: moves from proposed to implemented; a finding records one outcome.
ALLOWED = {**{kind: frozenset({"live"}) for kind in
              ("rules", "routing", "reference", "generated", "handoff", "contract")},
           "design": frozenset({"proposed", "partial", "implemented", "superseded"}),
           "plan": frozenset({"proposed", "partial", "implemented", "superseded"}),
           "findings": frozenset({"recorded", "superseded"})}
REQUIRED = ("path", "kind", "status", "since")
OPTIONAL = ("eager", "budget_words", "implemented_by", "superseded_by",
            "generated_by", "remains", "waits_for")
TEXT_FIELDS = ("superseded_by", "generated_by", "remains", "waits_for")
#: The forms an `implemented_by` target may take.
TARGET_PREFIXES = ("owns:", "cmd:", "reticle/", "tools/")

#: HANDOFF owns these limits; a second number here would drift from it.
HANDOFF_OWNED = frozenset({"NOTES.md", "BACKLOG.md"})
#: What the register must cover. A blind spot is declared, not discovered.
SCOPE = ("*.md", "docs/*.md", "prototypes/CLAUDE.md", ".claude/skills/*/SKILL.md")
#: The root `CLAUDE.md` is one line that imports `AGENTS.md`.
OUT_OF_SCOPE = frozenset({"CLAUDE.md"})
#: Landing pages: reachability roots beside the eager documents.
ENTRY_POINTS = ("README.md", ".claude/skills/*/SKILL.md")
#: Code whose docstrings and comments sit on the pickup route.
CODE_ROOTS = ("reticle", "tools")
#: The checker names documents in its own prose; that is no route to them.
SELF = "reticle/documents.py"

LINK = re.compile(r"\]\(\s*<?([^)\s>]+)")
ADD_PARSER = re.compile(r"\.add_parser\(\s*[\"']([\w-]+)[\"']")
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


@dataclass(frozen=True)
class Document:
    """One registered document. `path` is repo-relative POSIX."""
    path: str
    kind: str
    status: str
    since: str
    eager: bool = False
    budget_words: int | None = None
    implemented_by: tuple[str, ...] = ()
    superseded_by: str = ""
    generated_by: str = ""
    remains: str = ""
    waits_for: str = ""


class RegisterError(ValueError):
    """`documents.toml` contradicts its schema. Each problem names its entry."""

    def __init__(self, problems: list[str]):
        super().__init__("; ".join(problems))
        self.problems = list(problems)


def _problems(entry: dict, where: str) -> list[str]:
    """Schema faults in one entry, each naming it."""
    out = []
    missing = [key for key in REQUIRED if not str(entry.get(key, "")).strip()]
    if missing:
        out.append(f"{where} is missing {', '.join(missing)}")
    unknown = sorted(set(entry) - set(REQUIRED) - set(OPTIONAL))
    if unknown:
        out.append(f"{where} has unknown key(s) {', '.join(unknown)}; the schema "
                   f"is {', '.join(REQUIRED + OPTIONAL)}")
    path = entry.get("path", "")
    if not isinstance(path, str):
        out.append(f"{where} has a path that is not a string")
    elif path.startswith(HISTORY_PREFIXES):
        out.append(f"{where} registers dated history -- the archive is never "
                   f"registered; delete the entry")
    elif "\\" in path or path.startswith(("/", "./", "../")):
        out.append(f"{where} needs a repo-relative POSIX path")
    kind, status = str(entry.get("kind", "")), str(entry.get("status", ""))
    if kind and kind not in KINDS:
        out.append(f"{where} has kind `{kind}`; expected one of "
                   f"{', '.join(sorted(KINDS))}")
    elif kind and status and status not in ALLOWED[kind]:
        out.append(f"{where} is a {kind} with status `{status}`; a {kind} may "
                   f"be {', '.join(sorted(ALLOWED[kind]))}")
    since = entry.get("since", "")
    if since and not (type(since) is datetime.date
                      or (isinstance(since, str) and DATE.fullmatch(since))):
        out.append(f"{where} has since `{since}`; expected YYYY-MM-DD")
    eager = entry.get("eager", False)
    if not isinstance(eager, bool):
        out.append(f"{where} has eager `{eager}`; expected true or false")
    budget = entry.get("budget_words")
    if budget is not None and (isinstance(budget, bool) or not isinstance(budget, int)
                               or budget <= 0):
        out.append(f"{where} has budget_words `{budget}`; expected a positive integer")
    handoff = isinstance(path, str) and path in HANDOFF_OWNED
    if handoff and budget is not None:
        out.append(f"{where} sets budget_words; HANDOFF owns that limit -- delete it")
    elif eager is True and budget is None and not handoff:
        out.append(f"{where} is eager and has no budget_words -- every session "
                   f"reads it, so it needs a ceiling")
    elif budget is not None and eager is not True:
        out.append(f"{where} sets budget_words and is not eager")
    targets = entry.get("implemented_by", [])
    if not isinstance(targets, list) or not all(isinstance(t, str) for t in targets):
        out.append(f"{where} has implemented_by that is not a list of strings")
    else:
        for target in targets:
            if not target.startswith(TARGET_PREFIXES):
                out.append(f"{where} is implemented by `{target}`; a target is "
                           f"owns:<id>, cmd:<name>, or a path under reticle/ or tools/")
    for field in TEXT_FIELDS:
        if field in entry and not isinstance(entry[field], str):
            out.append(f"{where} has {field} that is not a string")
    return out


def load(root: Path | None = None) -> list[Document]:
    """The register, in file order. `[]` when there is none; raises on a fault."""
    base = Path(root) if root else ROOT
    source = base / DECLARATION
    if not source.is_file():
        return []
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise RegisterError([f"{DECLARATION} does not parse: {exc}"]) from exc
    problems: list[str] = []
    extra = sorted(set(data) - {"document"})
    if extra:
        problems.append(f"{DECLARATION} has unknown table(s) {', '.join(extra)}; "
                        f"the schema is [[document]]")
    entries = data.get("document", [])
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise RegisterError(problems + [f"{DECLARATION} declares documents as "
                                        f"[[document]] tables"])
    out: list[Document] = []
    seen: set[str] = set()
    for number, entry in enumerate(entries, 1):
        path = entry.get("path")
        named = isinstance(path, str) and path.strip()
        where = f"{DECLARATION} [{path}]" if named else f"{DECLARATION} entry {number}"
        found = _problems(entry, where)
        if named and path in seen:
            found.append(f"{where} is registered more than once")
        if found:
            problems += found
            continue
        seen.add(path)
        out.append(Document(
            path=path, kind=entry["kind"], status=entry["status"],
            since=str(entry["since"]), eager=entry.get("eager", False),
            budget_words=entry.get("budget_words"),
            implemented_by=tuple(entry.get("implemented_by", [])),
            **{field: entry.get(field, "") for field in TEXT_FIELDS}))
    if problems:
        raise RegisterError(problems)
    return out


def in_scope(root: Path | None = None) -> set[str]:
    """The live documents on disk that the register must cover."""
    base = Path(root) if root else ROOT
    out: set[str] = set()
    for pattern in SCOPE:
        for path in base.glob(pattern):
            rel = path.relative_to(base).as_posix()
            if (path.is_file() and rel not in OUT_OF_SCOPE
                    and not rel.startswith(HISTORY_PREFIXES)):
                out.add(rel)
    return out


def _resolve(token: str, bases: tuple[str, ...], registered: set[str]) -> str | None:
    """The registered document a link or a named path points at, if any."""
    token = unquote(token.split("#", 1)[0].split("?", 1)[0])
    if not token or "://" in token or token.startswith("mailto:"):
        return None
    for base in bases:
        rel = posixpath.normpath(posixpath.join(base, token))
        if rel in registered:
            return rel
    return None


def _named_in_code(base: Path, registered: set[str]) -> set[str]:
    """Registered documents a module in `CODE_ROOTS` names, bare names included.

    The scan looks for each registered file name, then walks back over the
    path characters before it, so `docs/X.md`, `../X.md` and a bare `X.md`
    all resolve. Searching for the names first keeps the scan cheap.
    """
    if not registered:
        return set()
    names = sorted({posixpath.basename(p) for p in registered}, key=len, reverse=True)
    pattern = re.compile(r"(?<![\w-])(?:" + "|".join(map(re.escape, names)) + r")(?![\w-])")
    found: set[str] = set()
    for tree in CODE_ROOTS:
        if not (base / tree).is_dir():
            continue
        for path in (base / tree).rglob("*.py"):
            rel = path.relative_to(base).as_posix()
            if rel == SELF or "__pycache__" in path.parts:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if ".md" not in text and ".json" not in text:
                continue
            here = posixpath.dirname(rel)
            for match in pattern.finditer(text):
                start = match.start()
                while start and (text[start - 1].isalnum() or text[start - 1] in "_./-"):
                    start -= 1
                hit = _resolve(text[start:match.end()], (here, "", "docs"), registered)
                if hit:
                    found.add(hit)
    return found


def reached(root: Path | None, docs: list[Document]) -> set[str]:
    """Documents reachable from a root by Markdown links, breadth-first.

    Only a registered document is ever a source, so nothing under
    `docs/archive/` keeps a document alive. A link resolves against the file
    that holds it, as a renderer resolves it; a broken link is no route.
    """
    base = Path(root) if root else ROOT
    registered = {doc.path for doc in docs}
    queue = sorted({doc.path for doc in docs if doc.eager}
                   | {p for p in registered
                      if any(fnmatch.fnmatch(p, e) for e in ENTRY_POINTS)}
                   | _named_in_code(base, registered))
    seen: set[str] = set()
    while queue:
        rel = queue.pop()
        if rel in seen:
            continue
        seen.add(rel)
        path = base / rel
        if not rel.endswith(".md") or not path.is_file():
            continue
        here = posixpath.dirname(rel)
        for match in LINK.finditer(path.read_text(encoding="utf-8", errors="replace")):
            hit = _resolve(match.group(1), (here,), registered)
            if hit and hit not in seen:
                queue.append(hit)
    return seen


def subcommands(root: Path | None = None) -> set[str]:
    """Every `sub.add_parser("name")` in `reticle/cli.py`, read without importing it.

    A pattern rather than a parse: `cli.py` registers every command with a
    literal name, and parsing the whole file dominated this check's time.
    """
    base = Path(root) if root else ROOT
    path = base / "reticle" / "cli.py"
    if not path.is_file():
        return set()
    return set(ADD_PARSER.findall(path.read_text(encoding="utf-8", errors="replace")))


def unregistered(root: Path | None, docs: list[Document]) -> list[tuple[str, str]]:
    """Live documents with no entry, and entries with no file."""
    base = Path(root) if root else ROOT
    registered = {doc.path for doc in docs}
    out = [("WARN", f"{rel} is in no documents.toml entry -- add a [[document]] "
                    f"entry with its kind, status and since")
           for rel in sorted(in_scope(base) - registered)]
    out += [("ERROR", f"documents.toml [{doc.path}] names a file that does not "
                      f"exist -- a move or a deletion left the entry behind")
            for doc in docs if not (base / doc.path).is_file()]
    return out


def unreached(root: Path | None, docs: list[Document]) -> list[tuple[str, str]]:
    """Documents no route reaches. A superseded one answers to its successor."""
    base = Path(root) if root else ROOT
    seen = reached(base, docs)
    return [("WARN", f"{doc.path} is reached by nothing -- link it from the map "
                     f"or the guide, supersede it, or archive it")
            for doc in docs
            if doc.path not in seen and not doc.eager and doc.status != "superseded"
            and (base / doc.path).is_file()]


def inconsistent(root: Path | None, docs: list[Document]) -> list[tuple[str, str]]:
    """A status its own fields do not support, or a target that resolves to nothing."""
    base = Path(root) if root else ROOT
    registered = {doc.path for doc in docs}
    index = ownership.load(base / "ownership.toml").get("_index", {})
    commands = subcommands(base)

    def why(target: str) -> str | None:
        kind, _, name = target.partition(":")
        if kind == "owns":
            if name not in index:
                return "is not an ownership.toml entry"
            if index[name].get("status") == "unowned":
                return "ownership.toml declares unowned"
            return None
        if kind == "cmd":
            return None if name in commands else "is not a reticle subcommand"
        return None if (base / target).is_file() else "does not exist"

    out = []
    for doc in docs:
        if doc.status == "superseded":
            if not doc.superseded_by:
                out.append(("WARN", f"{doc.path} is superseded and names no "
                                    f"superseded_by -- name its successor"))
            elif doc.superseded_by not in registered:
                out.append(("WARN", f"{doc.path} is superseded by "
                                    f"{doc.superseded_by}, which documents.toml "
                                    f"does not register"))
        if doc.status in ("partial", "implemented") and not doc.implemented_by:
            out.append(("WARN", f"{doc.path} is {doc.status} and names nothing in "
                                f"implemented_by -- name the owner (owns:<id>), "
                                f"the command (cmd:<name>) or the module"))
        for target in doc.implemented_by:
            reason = why(target)
            if reason:
                out.append(("WARN", f"{doc.path} is implemented by {target}, "
                                    f"which {reason}"))
        if doc.generated_by:
            reason = why(doc.generated_by)
            if reason:
                out.append(("WARN", f"{doc.path} is generated by "
                                    f"{doc.generated_by}, which {reason}"))
    return out


def over_budget(root: Path | None, docs: list[Document],
                handoff_limits: dict[str, int] | None = None
                ) -> list[tuple[str, str]]:
    """Eager documents past their ceilings, and the pickup total past the sum.

    Words are `str.split()`, HANDOFF's count. `handoff_limits` supplies the
    ceilings HANDOFF owns, so the total covers every document a session reads.
    """
    base = Path(root) if root else ROOT
    limits = dict(handoff_limits or {})
    out, total, ceiling = [], 0, 0
    for doc in docs:
        path = base / doc.path
        budget = doc.budget_words if doc.budget_words is not None else limits.get(doc.path)
        if not doc.eager or budget is None or not path.is_file():
            continue
        words = len(path.read_text(encoding="utf-8", errors="replace").split())
        total, ceiling = total + words, ceiling + budget
        if doc.budget_words is not None and words > budget:
            out.append(("WARN", f"{doc.path} has {words} words; its budget is "
                                f"{budget} -- move detail to its owner and history "
                                f"to docs/archive/"))
    if total > ceiling:
        out.append(("WARN", f"eager documents have {total} words; their budgets "
                            f"sum to {ceiling}"))
    return out


def verify(root: Path | None = None, docs: list[Document] | None = None,
           handoff_limits: dict[str, int] | None = None) -> list[tuple[str, str]]:
    """Every check above, in order. Raises `RegisterError` on a schema fault."""
    base = Path(root) if root else ROOT
    docs = load(base) if docs is None else docs
    return (unregistered(base, docs) + unreached(base, docs)
            + inconsistent(base, docs) + over_budget(base, docs, handoff_limits))
