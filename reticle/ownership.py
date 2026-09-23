"""Who owns each piece of information, declared and VERIFIED against the code.

    .\\.venv\\Scripts\\python.exe -m reticle ownership [QUESTION]

What this answers that nothing else does
-----------------------------------------
`architecture.toml` says which imports are permitted. `domain/*.toml` says what
is true of the game. Neither says **which module is allowed to decide a given
question**, and that is the one that keeps being got wrong, because the names
collide. `roster` and `lineup` both sound like identity. `minimap.pick_self`
and `lineup`'s player vote are both called *self*. `minimap_lifecycle` and
`round_lifetimes` both speak lifecycle. `track` sounds like the answer to every
identity question in the repo and owns none of them.

Two faults, both already paid for
----------------------------------
1. **A slot index read as an identity.** The HUD death signal dims a PACKED
   living-slot position rather than a canonical player slot; used as identity it
   named the wrong victim in both rounds it was tested on. `roster` owns the
   count and says so here; naming the agent is `lineup`'s.
2. **Two modules owning one law.** `minimap_lifecycle` restated `track`'s
   continuation ceiling and the two drifted -- `RUN_PX*dt + sqrt(2)`, which at
   60 Hz is 2.2 px against the tracker's 4.8, so it quarantined appearances the
   tracker had already associated. `defers_to` is the fix with teeth: the
   deferring module must IMPORT the owner it defers to, so inlining the rule
   again breaks the declaration.

Why a registry and not a document
----------------------------------
The first proposal was a hand-written index restating each module's boundary in
prose, with the machine-readable form and the checks deferred to later phases.
That is the shape `domain/*.toml` exists to replace: a restatement is a place to
drift, and 65 of them drift 65 ways. So the declaration ships with its checker,
prose CITES an entry by its `[owns:<id>]` token instead of repeating it, and the
argument stays in the owner's own docstring, where it already is and where it is
better written than any summary of it.

What a check here must clear
-----------------------------
`doctor`'s bar: a fault that has actually happened, or a declaration that can go
stale in silence. Reference integrity, the owner's own claim, the placement of
every module, the `defers_to` edges and the prototype-backed statuses are
checked. An import PROHIBITION is deliberately absent -- `lineup` imports
`roster` legitimately and the fault was in the reading, not in the edge, so a
forbidden-edge list would be theatre.

The gap is declared too
------------------------
An entry with `status = "unowned"` names a question nothing owns yet and what
blocks it. Cross-channel agent identity -- which named agent an icon, a track,
an ability or a death belongs to -- is the missing owner, and it stays visible
on every run instead of being rediscovered from `NOTES.md`.
"""
from __future__ import annotations

import ast
import re
import tomllib
from pathlib import Path

from .architecture import foreign_imports, modules

ROOT = Path(__file__).resolve().parent.parent
DECLARATION = ROOT / "ownership.toml"

#: The one reference form, resolvable by eye as well as by this module.
CITE = re.compile(r"\[owns:([a-z0-9][a-z0-9-]*)\]")

#: The semantic roles. `infrastructure` is not among them: a module answering no
#: question belongs in `[infrastructure]`, not in an entry whose role means
#: "none of these".
ROLES = frozenset({"detect", "assign", "track", "group", "attribute",
                   "constrain", "adjudicate", "lifecycle", "corroborate",
                   "count"})

#: `shipped` is wired and validated; `partial` is wired with a stated limit;
#: `transitional` is wired but reaching `prototypes/`, and owes an `exit`;
#: `unowned` is a question with no owner, and owes a `blocked_by`.
STATUSES = frozenset({"shipped", "partial", "transitional", "unowned"})

REQUIRED = ("question", "role", "status", "not_for")

#: The one question every agent name in the match is decided under. An entry
#: declaring `names_agents = true` outputs agent names and must defer to it;
#: only its owner may emit identity events. See `adjudication.identity`.
IDENTITY_QUESTION = "agent-identity"
IDENTITY_EMITTER = "identity_distribution_event("


def public_names(path: Path) -> set[str]:
    """Top-level names a module defines: what another module may name."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out.add(node.name)
        elif isinstance(node, ast.Assign):
            out.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out.add(node.target.id)
    return out


def imports_of(path: Path, package: str = "reticle") -> set[str]:
    """Sibling modules a file imports, however it spells it.

    Dotted for the subpackage, so `from .adjudication.ability import x` reads as
    `adjudication.ability` rather than as a module called `adjudication`.
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (SyntaxError, OSError):
        return set()
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module is None and node.level:
                out.update(a.name for a in node.names)
            elif node.module:
                if node.level:
                    out.add(node.module)
                elif node.module == package:
                    # `from reticle import domain, metrics` -- how `doctor`
                    # spells every one of its dependencies.
                    out.update(a.name for a in node.names)
                elif node.module.startswith(f"{package}."):
                    out.add(node.module[len(package) + 1:])
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(f"{package}."):
                    out.add(alias.name[len(package) + 1:])
    return out


def reaches(consumer: str, owner: str, paths: dict[str, Path]) -> bool:
    """Does `consumer` import `owner`, under either module's spelling?"""
    path = paths.get(consumer)
    if path is None:
        return False
    tail = owner.split(".")[-1]
    return any(name == owner or name.split(".")[-1] == tail
               for name in imports_of(path))


def load(path: Path | None = None) -> dict:
    """The declaration, with entries indexed by id."""
    source = Path(path) if path else DECLARATION
    if not source.is_file():
        return {}
    data = tomllib.loads(source.read_text(encoding="utf-8"))
    index: dict[str, dict] = {}
    duplicated: list[str] = []
    for entry in data.get("entry", []):
        key = str(entry.get("id", ""))
        if key in index:
            duplicated.append(key)
        index[key] = entry
    data["_index"] = index
    data["_duplicated"] = sorted(set(duplicated))
    return data


def owners(data: dict) -> dict[str, list[str]]:
    """Module -> the entry ids it owns."""
    out: dict[str, list[str]] = {}
    for key, entry in data.get("_index", {}).items():
        owner = str(entry.get("owner", ""))
        if owner:
            out.setdefault(owner, []).append(key)
    return out


def _listed(entry: dict, field: str) -> list[str]:
    value = entry.get(field, [])
    return [value] if isinstance(value, str) else list(value)


def _flat(text: str, limit: int = 96) -> str:
    """A wrapped TOML paragraph as one line, for a finding that must fit one."""
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[:limit - 3].rstrip(" ,.") + "..."


def verify(data: dict | None = None, root: Path | None = None
           ) -> list[tuple[str, str]]:
    """`(level, message)` pairs. ERROR blocks; WARN is a list to work off."""
    base = Path(root) if root else ROOT
    if data is None:
        data = load(base / "ownership.toml" if root else None)
    if not data:
        return [("WARN", "ownership.toml is absent -- who owns what is declared "
                         "there, see reticle/ownership.py")]

    paths = modules(base)
    index = data["_index"]
    held = owners(data)
    infra = set(data.get("infrastructure", {}).get("modules", []))
    # `architecture` already knows both spellings of a crossing into the other
    # tree, including the `sys.path` insert plus a bare import. A second copy
    # here is the fork this repo checks for.
    stems = frozenset(p.stem for p in (base / "prototypes").glob("*.py"))
    out: list[tuple[str, str]] = []

    for key in data["_duplicated"]:
        out.append(("ERROR", f"`{key}` is declared more than once"))

    # Identity events have one producer. `death` built its own, from its own
    # copy of the cross-channel rule, and nothing failed.
    arbiter = str(index.get(IDENTITY_QUESTION, {}).get("owner", ""))
    for name, path in sorted(paths.items()):
        if name in (arbiter, "events", "ownership"):
            continue
        if IDENTITY_EMITTER in path.read_text(encoding="utf-8", errors="replace"):
            out.append(("ERROR", f"`{name}` builds identity events itself -- "
                                 f"call `identity_events` in `{arbiter}`"))

    for key in sorted(index):
        entry = index[key]
        where = f"ownership.toml [{key}]"
        for field in REQUIRED:
            if not str(entry.get(field, "")).strip():
                out.append(("ERROR", f"{where} has no `{field}`"))
        for name in _listed(entry, "role"):
            if name not in ROLES:
                out.append(("ERROR", f"{where} has role `{name}`, which is not "
                                     f"one of {', '.join(sorted(ROLES))}"))
        status = str(entry.get("status", ""))
        if status and status not in STATUSES:
            out.append(("ERROR", f"{where} has status `{status}`, which is not "
                                 f"one of {', '.join(sorted(STATUSES))}"))
        owner = str(entry.get("owner", ""))

        if status == "unowned":
            if owner:
                out.append(("ERROR", f"{where} is unowned and names owner "
                                     f"`{owner}` -- one or the other"))
            if not str(entry.get("blocked_by", "")).strip():
                out.append(("ERROR", f"{where} is unowned and says nothing "
                                     f"about what blocks it"))
            else:
                out.append(("WARN", f"nothing owns `{key}` -- "
                                    f"{_flat(entry.get('question'), 60)} "
                                    f"blocked by "
                                    f"{_flat(entry['blocked_by'], 80)}"))
            continue

        if owner not in paths:
            out.append(("ERROR", f"{where} names owner `{owner}`, which is not "
                                 f"a module in reticle/"))
            continue
        if owner in infra:
            out.append(("ERROR", f"{where} names `{owner}`, which is also "
                                 f"declared infrastructure -- a module that "
                                 f"owns a question is not infrastructure"))

        spelt = owner.replace(".", "/")
        names = public_names(paths[owner])
        produces = _listed(entry, "produces")
        if not produces:
            out.append(("ERROR", f"{where} names no `produces` -- an entry "
                                 f"pointing at no code cannot go stale"))
        for name in produces:
            if name not in names:
                out.append(("ERROR", f"{where} says `{owner}` produces "
                                     f"`{name}`, which it does not define"))

        text = paths[owner].read_text(encoding="utf-8", errors="replace")
        if f"[owns:{key}]" not in text:
            out.append(("ERROR", f"`reticle/{spelt}.py` does not claim "
                                 f"`[owns:{key}]` -- the owner names its own "
                                 f"contract, or the entry is stale"))

        if (entry.get("names_agents") and key != IDENTITY_QUESTION
                and IDENTITY_QUESTION not in _listed(entry, "defers_to")):
            out.append(("ERROR", f"{where} names agents and does not defer to "
                                 f"`{IDENTITY_QUESTION}` -- a name is decided by "
                                 f"the identity arbiter, never beside it"))

        for other in _listed(entry, "defers_to"):
            if other not in index:
                out.append(("ERROR", f"{where} defers to `{other}`, which is "
                                     f"not an entry"))
                continue
            to = str(index[other].get("owner", ""))
            if to and not reaches(owner, to, paths):
                out.append(("ERROR", f"`{owner}` defers to `{other}` and no "
                                     f"longer imports `{to}` -- either it "
                                     f"restates the rule, or the declaration "
                                     f"is stale"))

        for consumer in _listed(entry, "consumers"):
            if consumer not in paths:
                out.append(("ERROR", f"{where} names consumer `{consumer}`, "
                                     f"which is not a module in reticle/"))
            elif not reaches(consumer, owner, paths):
                out.append(("WARN", f"{where} names `{consumer}` as a consumer "
                                    f"and it does not import `{owner}` -- move "
                                    f"it to `stored_consumers`, or delete it"))
        for consumer in _listed(entry, "stored_consumers"):
            if consumer not in paths:
                out.append(("ERROR", f"{where} names stored consumer "
                                     f"`{consumer}`, which is not a module"))

        reaching = bool(foreign_imports(paths[owner], stems=stems))
        if reaching and status != "transitional":
            out.append(("ERROR", f"{where} is `{status}` and `{owner}` imports "
                                 f"the prototypes tree -- that is "
                                 f"`transitional`, and owes an `exit`"))
        if status == "transitional":
            if not str(entry.get("exit", "")).strip():
                out.append(("ERROR", f"{where} is transitional and names no "
                                     f"`exit` condition"))
            if not reaching:
                out.append(("WARN", f"{where} is transitional and `{owner}` no "
                                    f"longer reaches prototypes/ -- the "
                                    f"promotion happened, update the status"))

    for module in sorted(set(paths) - set(held) - infra):
        out.append(("ERROR", f"`reticle/{module.replace('.', '/')}.py` owns no "
                             f"entry and is not declared infrastructure -- "
                             f"place it in ownership.toml"))
    for module in sorted(infra - set(paths)):
        out.append(("ERROR", f"ownership.toml declares `{module}` "
                             f"infrastructure, which is not a module"))

    for module, path in sorted(paths.items()):
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in sorted(set(CITE.findall(text)) - set(held.get(module, ()))):
            spelt = module.replace(".", "/")
            if key not in index:
                out.append(("ERROR", f"`reticle/{spelt}.py` cites "
                                     f"`[owns:{key}]`, which is not an entry"))
            else:
                out.append(("ERROR", f"`reticle/{spelt}.py` claims "
                                     f"`[owns:{key}]`, which "
                                     f"`{index[key].get('owner')}` owns"))

    for path in sorted(base.glob("*.md")) + sorted(base.glob("docs/*.md")):
        text = path.read_text(encoding="utf-8", errors="replace")
        for key in sorted(set(CITE.findall(text)) - set(index)):
            out.append(("ERROR", f"{path.relative_to(base).as_posix()} cites "
                                 f"`[owns:{key}]`, which is not an entry"))
    return out


def route(query: str, data: dict | None = None) -> list[dict]:
    """Entries matching a plain-language question, best first.

    Scored on words of three letters or more, so *which agent died* reaches the
    death entry and *where is the player* reaches `minimap`, without either
    matching every entry containing the word *the*.

    Only the best-scoring entries come back. A routing tool that answers a
    three-word question with twenty-seven entries has not routed anything, and
    `not_for` is searched too -- asking the wrong owner by name should still
    reach the entry that says so.
    """
    data = data if data is not None else load()
    words = {w for w in re.findall(r"[a-z]+", query.lower()) if len(w) > 2}
    scored: list[tuple[int, str, dict]] = []
    for key, entry in data.get("_index", {}).items():
        hay = " ".join([key.replace("-", " "), str(entry.get("question", "")),
                        str(entry.get("owner", "")),
                        str(entry.get("not_for", ""))]).lower()
        score = sum(1 for w in words if w in hay)
        if score:
            scored.append((-score, key, entry))
    if not scored:
        return []
    best = min(score for score, _key, _entry in scored)
    return [entry for score, _key, entry in sorted(scored, key=lambda r: r[:2])
            if score == best]


def render(entry: dict) -> str:
    """One entry, as the routing answer a developer reads."""
    import textwrap

    def block(label: str, text: str) -> str:
        body = textwrap.fill(" ".join(str(text).split()), width=78,
                             initial_indent=" " * 15, subsequent_indent=" " * 15)
        return f"    {label:<11}{body[15:]}"

    lines = [f"{entry.get('id')}  [{entry.get('status')}]",
             block("question", entry.get("question", "")),
             f"    owner      {entry.get('owner') or '-- nothing owns this'}"]
    for field in ("role", "produces", "defers_to", "consumers",
                  "stored_consumers"):
        if entry.get(field):
            lines.append(f"    {field:<10} {', '.join(_listed(entry, field))}")
    lines.append(block("NOT for", entry.get("not_for", "")))
    for field in ("evidence", "exit", "blocked_by"):
        if entry.get(field):
            lines.append(block(field, entry[field]))
    return "\n".join(lines)


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="reticle ownership",
        description=__doc__.split("\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="*",
                        help="a question in plain language, to route")
    parser.add_argument("--module", help="the entries one module owns")
    parser.add_argument("--check", action="store_true",
                        help="verify the declaration against the code")
    args = parser.parse_args(argv)

    data = load()
    if args.check:
        problems = verify(data)
        for level, message in problems:
            print(f"{level:6s} {message}")
        errors = sum(1 for level, _m in problems if level == "ERROR")
        print(f"\n{len(data.get('_index', {}))} entries, "
              f"{len(data.get('infrastructure', {}).get('modules', []))} "
              f"infrastructure, {len(problems)} finding(s), {errors} error(s)")
        return 1 if errors else 0

    if args.module:
        found = [data["_index"][k] for k in sorted(owners(data).get(args.module, ()))]
        if not found:
            print(f"`{args.module}` owns no entry")
            return 1
    elif args.question:
        found = route(" ".join(args.question), data)
        if not found:
            print("no entry matches -- if the question is real, add one before "
                  "adding the dependency")
            return 1
    else:
        found = sorted(data.get("_index", {}).values(),
                       key=lambda e: str(e.get("id")))
    print("\n\n".join(render(entry) for entry in found))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
