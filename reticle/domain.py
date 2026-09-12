"""What is true about VALORANT, in one place, in as little prose as possible.

    .\\.venv\\Scripts\\python.exe -m reticle domain [DOMAIN] [--id ID] [--uncited]

Why this exists
---------------
Domain facts were restated wherever they were next needed. The minimap vision
rule sat in five files, *semi-transparent over the void* in twenty-four, the
spike's inversion in four -- and every restatement is a place for the fact to
drift from the others without anything noticing. Worse, facts the player
supplied once got no consumer and were then lost in the shuffle: a question
answered by a human and then mislaid costs another interruption to ask again.

So the facts live in `domain/*.toml`, one file per domain, one TOML table per
fact, and prose cites them instead of repeating them. `tomllib` is stdlib, so
this adds no dependency.

The citation
------------
A fact is referenced as `[domain:<file>/<id>]` -- `[domain:minimap/vision-gate]`
-- in a docstring, a comment, or a markdown sentence. That token is the whole
convention, and it is what makes the registry enforceable rather than merely
tidy: `doctor` resolves every citation, so a dangling one is an ERROR, and it
reports every fact nothing cites, which is the *lost in the shuffle* failure
made visible.

Three things a fact carries beyond its claim
--------------------------------------------
`known` is the provenance -- `player`, `measured`, `observed`, `inferred` -- and
it is required because this repo's standing rule is that a guess must stay
distinguishable from a read. `use` says which channel to read the fact through,
because *own-team icons are always drawn* is useless without *use the DRAWN
light, not the raycast*. `phrases` is how a fact claims its own prose: any file
containing one of them without citing the fact is reported as a restatement,
which is what migrates the existing tangle incrementally instead of in one
sweep.

What is deliberately NOT here
-----------------------------
Measurements of this pipeline's own accuracy. Those are outcomes and belong in
the store's `notes/predictions.jsonl` and in `metrics`, which are append-only
and dated. This registry holds what is true of the GAME and its capture --
facts a new session should not have to rediscover, and that no rerun can
change. A fact whose truth depends on a detector version is not a domain fact.

Owns [owns:domain-fact].
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOMAIN_DIR = ROOT / "domain"

#: The one reference form. Both halves are the file stem and the table name, so
#: a citation is resolvable by eye as well as by this module.
CITE = re.compile(r"\[domain:([a-z0-9][a-z0-9-]*)/([a-z0-9][a-z0-9-]*)\]")

#: What kind of thing the fact is. Not decoration: a `measurement` may be
#: superseded by a better one, while a `rule` is the game's behaviour and can
#: only be wrong. Keeping them apart stops the second from being tuned.
KINDS = frozenset({
    "rule",          # the game always behaves this way
    "appearance",    # what something looks like on screen
    "constraint",    # something a rule may never assume away
    "geometry",      # fixed spatial fact about the widget or the map
    "codec",         # the capture pipeline, not the game
    "lifecycle",     # ordering of events in a round
    "measurement",   # a measured constant of the game, not of a detector
})

#: How the fact came to be known. Required, because a player's answer and an
#: inference must never become indistinguishable.
KNOWN = frozenset({"player", "measured", "observed", "inferred"})

REQUIRED = ("claim", "kind", "known", "since")
OPTIONAL = ("use", "exceptions", "source", "see", "phrases", "supersedes",
            "depends_on")

#: A fact whose `known` is one of these is GIVEN: someone told us, or we watched
#: it happen. It rests on nothing, so it may not declare `depends_on` -- that is
#: what stops an inference being laundered into a given by adding a provenance
#: it does not have.
GIVEN = frozenset({"player", "observed"})

#: A fact whose `known` is one of these is DERIVED and must say what from:
#: `inferred` from other FACTS, `measured` from a named SOURCE. An inference
#: resting on nothing stated is the shape every guess in this repo took first.
DERIVED = frozenset({"inferred", "measured"})

#: Append-only records. They hold the argument as it stood on a date, so a fact
#: restated inside them is HISTORY and rewriting it would be a lie about what
#: was known then. Restatement checks skip them; citation still works there.
HISTORY = ("NOTES.md", "BACKLOG.md")

#: Trees worth scanning for citations and restatements. Everything else --
#: `.venv`, the store, generated HTML -- is not this repo's prose.
SCAN_DIRS = ("", "docs", "reticle", "prototypes", "tools", "tests")
SCAN_SUFFIXES = (".py", ".md")

#: Files whose `[domain:...]` tokens are EXAMPLES of the convention rather than
#: uses of the fact. Without this the registry cites itself, and every seeded
#: fact named in a docstring would look consumed while nothing read it -- the
#: exact failure this module exists to report.
EXAMPLE_ONLY = frozenset({"reticle/domain.py", "tests/test_domain.py"})


@dataclass(frozen=True)
class Fact:
    """One domain fact. `key` is what a citation resolves to."""
    domain: str
    id: str
    claim: str
    kind: str
    known: str
    since: str
    use: str = ""
    exceptions: str = ""
    source: str = ""
    see: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    phrases: tuple[str, ...] = ()
    supersedes: str = ""
    unknown_keys: tuple[str, ...] = field(default=(), compare=False)
    missing_keys: tuple[str, ...] = field(default=(), compare=False)

    @property
    def key(self) -> str:
        return f"{self.domain}/{self.id}"

    @property
    def cite(self) -> str:
        return f"[domain:{self.key}]"


def _cycles(graph: dict[str, list[str]]) -> list[list[str]]:
    """Every dependency cycle, so no fact can rest on itself transitively."""
    seen: set[str] = set()
    stack: list[str] = []
    out: list[list[str]] = []

    def walk(node: str) -> None:
        if node in stack:
            out.append(stack[stack.index(node):] + [node])
            return
        if node in seen:
            return
        seen.add(node)
        stack.append(node)
        for onward in graph.get(node, ()):
            walk(onward)
        stack.pop()

    for node in sorted(graph):
        walk(node)
    return out


def _str_tuple(value) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


def load(domain_dir: Path | None = None) -> dict[str, Fact]:
    """Every fact, keyed `domain/id`. Malformed tables load and report later.

    A parse failure raises, because a registry that cannot be read is a broken
    repo rather than a stale one. Missing or unknown KEYS are carried on the
    `Fact` so `validate` can name them all at once instead of one per run.
    """
    directory = Path(domain_dir) if domain_dir else DOMAIN_DIR
    facts: dict[str, Fact] = {}
    if not directory.is_dir():
        return facts
    for path in sorted(directory.glob("*.toml")):
        tables = tomllib.loads(path.read_text(encoding="utf-8"))
        for fact_id, body in tables.items():
            if not isinstance(body, dict):
                continue
            missing = tuple(k for k in REQUIRED if not str(body.get(k, "")).strip())
            unknown = tuple(sorted(set(body) - set(REQUIRED) - set(OPTIONAL)))
            fact = Fact(
                depends_on=_str_tuple(body.get("depends_on")),
                domain=path.stem,
                id=fact_id,
                claim=str(body.get("claim", "")).strip(),
                kind=str(body.get("kind", "")).strip(),
                known=str(body.get("known", "")).strip(),
                since=str(body.get("since", "")).strip(),
                use=str(body.get("use", "")).strip(),
                exceptions=str(body.get("exceptions", "")).strip(),
                source=str(body.get("source", "")).strip(),
                see=_str_tuple(body.get("see")),
                phrases=_str_tuple(body.get("phrases")),
                supersedes=str(body.get("supersedes", "")).strip(),
                unknown_keys=unknown,
                missing_keys=missing,
            )
            facts[fact.key] = fact
    return facts


def scan_files(root: Path | None = None) -> list[Path]:
    """The repo's own prose and code, in a stable order."""
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
            rel_name = path.relative_to(base).as_posix()
            if rel_name in EXAMPLE_ONLY or rel_name in out_names:
                continue
            out_names.add(rel_name)
            out.append(path)
    return out


def citations(root: Path | None = None) -> dict[str, list[str]]:
    """Every `[domain:...]` token found, keyed by what it points at.

    The value is the repo-relative files that cite it, so an unresolved key is
    reported WITH the file that has to change.
    """
    base = Path(root) if root else ROOT
    found: dict[str, list[str]] = {}
    for path in scan_files(base):
        text = path.read_text(encoding="utf-8", errors="replace")
        for domain, fact_id in set(CITE.findall(text)):
            relative = path.relative_to(base).as_posix()
            found.setdefault(f"{domain}/{fact_id}", []).append(relative)
    return {key: sorted(paths) for key, paths in found.items()}


def restatements(facts: dict[str, Fact],
                 root: Path | None = None) -> dict[str, list[str]]:
    """Files that carry a fact's own phrasing without citing it.

    This is the migration signal, and the phrase list is authored by hand for
    the same reason `doctor`'s local-name blessing is: a hand-written list
    fires on everything it does not name, so a genuine restatement cannot hide
    behind a fuzzy similarity score nobody set.
    """
    base = Path(root) if root else ROOT
    cited = citations(base)
    out: dict[str, list[str]] = {}
    for key, fact in facts.items():
        if not fact.phrases:
            continue
        owners = set(cited.get(key, ()))
        hits = []
        for path in scan_files(base):
            relative = path.relative_to(base).as_posix()
            if relative in HISTORY or relative in owners:
                continue
            lowered = path.read_text(encoding="utf-8", errors="replace").lower()
            if any(phrase.lower() in lowered for phrase in fact.phrases):
                hits.append(relative)
        if hits:
            out[key] = sorted(hits)
    return out


def validate(facts: dict[str, Fact],
             root: Path | None = None) -> list[tuple[str, str]]:
    """Schema, dangling citations, unused facts, restated prose.

    Returns `(level, message)` pairs where level is `"ERROR"` for a registry
    that contradicts itself or a citation that resolves to nothing, and
    `"WARN"` for a fact nothing uses or prose that has not migrated yet. The
    split is deliberate: a dangling reference is a LIE and must block, while an
    unmigrated paragraph is debt and must not.
    """
    base = Path(root) if root else ROOT
    out: list[tuple[str, str]] = []

    for key, fact in sorted(facts.items()):
        if fact.missing_keys:
            out.append(("ERROR", f"{key} is missing required key(s): "
                                 f"{', '.join(fact.missing_keys)}"))
        if fact.unknown_keys:
            out.append(("ERROR", f"{key} has unknown key(s): "
                                 f"{', '.join(fact.unknown_keys)}; the schema is "
                                 f"{', '.join(REQUIRED + OPTIONAL)}"))
        if fact.kind and fact.kind not in KINDS:
            out.append(("ERROR", f"{key} has kind '{fact.kind}'; expected one of "
                                 f"{', '.join(sorted(KINDS))}"))
        if fact.known and fact.known not in KNOWN:
            out.append(("ERROR", f"{key} has known '{fact.known}'; expected one "
                                 f"of {', '.join(sorted(KNOWN))}"))
        if fact.since and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fact.since):
            out.append(("ERROR", f"{key} has since '{fact.since}'; expected an "
                                 f"absolute YYYY-MM-DD date"))
        for reference in fact.see:
            if reference not in facts:
                out.append(("ERROR", f"{key} sees '{reference}', which is not a "
                                     f"registered fact"))
        for reference in fact.depends_on:
            if reference not in facts:
                out.append(("ERROR", f"{key} depends on '{reference}', which is "
                                     f"not a registered fact"))
        if fact.known in GIVEN and fact.depends_on:
            out.append(("ERROR", f"{key} is {fact.known}, which is GIVEN, and "
                                 f"declares depends_on -- a fact someone told us "
                                 f"or we watched happen rests on nothing. Make "
                                 f"it inferred, or drop the dependency."))
        if fact.known == "inferred" and not fact.depends_on:
            out.append(("ERROR", f"{key} is inferred and names nothing it rests "
                                 f"on -- add depends_on"))
        if fact.known == "measured" and not fact.source:
            out.append(("ERROR", f"{key} is measured and names no source -- add "
                                 f"source, so the measurement can be found"))

    for cycle in _cycles({key: [d for d in fact.depends_on if d in facts]
                          for key, fact in facts.items()}):
        out.append(("ERROR", "facts depend on each other in a cycle: "
                             + " -> ".join(cycle)))

    cited = citations(base)
    for key, paths in sorted(cited.items()):
        if key not in facts:
            out.append(("ERROR", f"[domain:{key}] is cited by "
                                 f"{', '.join(paths)} and no such fact exists"))

    unused = sorted(key for key in facts if key not in cited)
    if unused:
        out.append(("WARN", f"{len(unused)} fact(s) nothing cites -- the "
                            f"lost-in-the-shuffle failure: {', '.join(unused)}"))

    for key, paths in sorted(restatements(facts, base).items()):
        out.append(("WARN", f"{key} is restated without citation in "
                            f"{', '.join(paths)}; cite {facts[key].cite} "
                            f"instead of repeating it"))
    return out


def _wrap(text: str, label: str = "", width: int = 76) -> list[str]:
    """Reflow a TOML multi-line value. The file wraps for diffs, not for eyes."""
    import textwrap
    body = " ".join(text.split())
    indent = " " * 4
    if label:
        head = f"{indent}{label:<11s} "
        return textwrap.wrap(body, width, initial_indent=head,
                             subsequent_indent=" " * len(head)) or []
    return textwrap.wrap(body, width, initial_indent=indent,
                         subsequent_indent=indent) or []


def render(facts: dict[str, Fact], domain: str | None = None,
           fact_id: str | None = None, cited: dict[str, list[str]] | None = None,
           uncited_only: bool = False) -> str:
    """The registry as a reader wants it: claim first, provenance beside it."""
    lines: list[str] = []
    for key, fact in sorted(facts.items()):
        if domain and fact.domain != domain:
            continue
        if fact_id and fact.id != fact_id:
            continue
        users = (cited or {}).get(key, [])
        if uncited_only and users:
            continue
        lines.append(f"{fact.cite}  [{fact.kind}, {fact.known}, {fact.since}]")
        lines += _wrap(fact.claim)
        for label, value in (("USE", fact.use),
                             ("EXCEPTIONS", fact.exceptions),
                             ("SOURCE", fact.source),
                             ("SUPERSEDES", fact.supersedes),
                             ("RESTS ON", ", ".join(fact.depends_on)),
                             ("SEE", ", ".join(fact.see)),
                             ("CITED BY", ", ".join(users) or "NOTHING")):
            if value:
                lines += _wrap(value, label)
        lines.append("")
    if not lines:
        return "no matching fact"
    return "\n".join(lines).rstrip()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("domain", nargs="?", help="limit to one domain file")
    parser.add_argument("--id", help="limit to one fact id")
    parser.add_argument("--uncited", action="store_true",
                        help="only facts nothing cites")
    parser.add_argument("--check", action="store_true",
                        help="validate and exit non-zero on an ERROR")
    args = parser.parse_args(argv)

    facts = load()
    if args.check:
        problems = validate(facts)
        for level, message in problems:
            print(f"{level:6s} {message}")
        errors = sum(1 for level, _m in problems if level == "ERROR")
        print(f"\n{len(facts)} fact(s), {len(problems)} finding(s), "
              f"{errors} error(s)")
        return 1 if errors else 0
    print(render(facts, args.domain, args.id, citations(), args.uncited))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
