"""The ability mechanics sheet, pre-filled from the game files for the player to confirm.

    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet build             # write the pre-fill
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet ask [--agent A] [--column C] [--reask-unsure]
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet status            # counts per column
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet import [--write]  # confirmed rows only

One row per ability (C, Q, E and X) of every agent the game data names, and
one row per spawned object where an ability spawns more than one world
object or pawn: each such object is its own child entity
(docs/ABILITY_ENTITIES.md), with its own lifecycle. A row is keyed by
(ability, object) and reads only the object's class, its parent classes and
the classes only it references; what no object owns (the held equippable, a
tuning table) is shown beside the row, never pre-filled into it. Spycam's
camera and its tracking dart differ at the owner's death
[domain:abilities/cypher-spycam-persists-after-death]
[domain:abilities/cypher-tracking-dart-ends-on-owner-death]. The columns the
ability-entity plan needs (sections 2.4 and 6, question 4):

* `parent`: the object's parent in the spawn tree, another object or the
  ability, from a spawn in the exports (the states table's `spawns`, or a
  spawn call in the referrer's bytecode); a reference without a spawn is `ask`.
* `lifecycle_class`: the plan's classes, `domain.LIFECYCLE_CLASSES`.
* `lifetime_s`: a `life` value of the ability's `*-game-data` fact, read from
  the row's own classes.
* `destructible`: whether the enemy can destroy it, yes or no.
* `owner_death`: disabled, destroyed, persists, or not applicable.
* `ends_on`: a set of `domain.ENDS_ON`; `round_end` is always a member.
* `visible_phases`: what the player sees on the minimap and the screen, cast
  to gone, in the player's words; filled only by a fact that states it.
* `effects`: the game's buff, debuff and blind classes and effect fields,
  each with its targets.
* `minimap_drawing`: icon, shape, both or nothing; a minimap texture in the
  game data suggests an icon.
* `engine_states`: the game data's lexical phases per owner. Evidence, never
  a question: game files outrank the player, so the import writes them as the
  fact's `states` unasked.

The walk asks one plain question per cell about a thing the player knows,
named by the ability and the object's words ("Spycam's tracking dart"),
never a class name, with choices in words and the evidence reduced to one
line the player can ignore. It runs by agent, ability, then object, and
skips hidden cells and engine helpers no player can see (`UNSEEN`).

Mechanics are unique per ability [domain:abilities/ability-rules-are-unique]:
every pre-filled cell comes from that ability's own game files or its own
domain facts, never from a sibling. A cell carries its sources (a domain
token or a game-file path) and a status: `confirm` where a source fills it,
`conflict` where two sources disagree, `ask` where none does. The game
data's names are the designers' words, so a class, a phase or an effect read
from a name is a draft; the player confirms it or replaces it.

The player's rules of 2026-10-09 stand in the header as defaults, never as a
pre-fill (`DEFAULT_RULES`): the `d` key applies one to a cell, ability by
ability, and the answer records that it did.

Answers follow the labelling-pass conventions: append-only JSONL at
`<store>/labels/mechanics_sheet/answers.jsonl`, apart from the pre-fill; the
last row for a key wins; a rerun skips answered keys; `u` is unsure, kept
out of the import; `a` goes back one; `q` saves and quits. Game-file
quantities outrank the player's numbers
[domain:abilities/game-files-outrank-player-quantities]: where the game data
gives a lifetime the player picks one of its values or none, and types a
number only where it gives none. The player's qualitative answers outrank
every draft.

`import` writes one `lifecycle` fact per confirmed row into
`domain/abilities.toml`: every column answered, none unsure. It never writes
an unconfirmed row and never rewrites an existing fact. A fact with `states`
makes `entity_contract.ability_states` check emitted phases against them. An
answer given under a column's old name (`RENAMED`) reads under its new one.

Stored data and game files only: no decode, no game install or extractor.

Owns [owns:ability-mechanics-sheet].
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import hashlib
import json
import re
import sys
from pathlib import Path

from . import domain

VERSION = "mechanics-sheet-0.3.0"
BUILD = "release-13.06-shipping-18-5590001"
#: The game-data states table (`prototypes/ability_states_gamedata.py`).
STATES_TABLE = ("reference/ability-states", "ability-states-gamedata-0.2.0")
GAME_EXPORTS = f"reference/game-files/{BUILD}/ability-states/ShooterGame/Content"
PREFILL_DIR = "reference/mechanics-sheet"
ANSWERS = "labels/mechanics_sheet/answers.jsonl"
#: The player's earlier per-view minimap answers (`prototypes/ask_minimap_glyphs.py`).
VIEW_ANSWERS = "labels/minimap_glyph_questions/answers.jsonl"
SLOTS = ("C", "Q", "E", "X")
COLUMNS = ("parent", "lifecycle_class", "visible_phases", "lifetime_s", "destructible",
           "owner_death", "ends_on", "effects", "minimap_drawing", "engine_states")
#: Columns renamed since an earlier sheet: an old answer reads under the new name.
RENAMED = {"states": "engine_states"}
CLASSES = ("deployed", "instant", "self_buff", "equipped", "movement")
ENDS = ("lifetime", "destroyed", "owner_death", "recall_or_reactivation", "round_end")
TARGETS = ("self", "allies", "enemies")
DRAWINGS = ("icon", "shape", "icon_and_shape", "nothing")
assert set(CLASSES) == domain.LIFECYCLE_CLASSES and set(ENDS) == domain.ENDS_ON

#: The player's rules of 2026-10-09, shown in the header and applied by `d`.
DEFAULT_RULES = (
    "Nothing carries into the next round: everything is gone when the round ends.",
    "A placed thing with no time limit stays until enemies destroy it or the round ends.",
    "A placed thing, an enemy's included, stops working when its owner dies.",
    "Some things with a time limit can also be destroyed by enemies "
    "(Miks' heal and concuss throwables).",
    "Boosts, reveals and blinds are effects, each a thing of its own.",
)

#: Player facts that state one cell for one ability, named one by one; the
#: `*-persists-after-death` facts are found by their id.
PLAYER_FACT_CELLS = {
    ("skye:seekers", "destructible"): ("yes", "abilities/skye-seekers-track-and-blind"),
    ("sage:barrier orb", "destructible"): ("yes", "abilities/sage-barrier-orb-segments"),
    ("omen:dark cover", "owner_death"): ("persists", "abilities/omen-dark-cover"),
}

#: Effect kinds read from the game's own effect classes (`Buff_*`, `Debuff_*`,
#: `BlindConfig_*`) and effect fields of the game-data facts. A lexical draft.
EFFECT_WORDS = (
    ("blind", r"blind"), ("nearsight", r"nearsight"), ("concuss", r"concuss"),
    ("slow", r"slow"), ("heal", r"heal|temphealth"), ("reveal", r"reveal|darted|tagging"),
    ("decay", r"decay"), ("fragile", r"fragile|vulnerab"), ("suppress", r"suppress"),
    ("deafen", r"deafen"), ("stun", r"stun"), ("speed_boost", r"speedboost|speedstim"),
    ("invisible", r"invis|cloak"), ("invulnerable", r"invuln|immunity"),
    ("detain", r"netted|chained|detain|tether"), ("knockup", r"knockup"),
    ("damage", r"damage"),
)
EFFECT_FIELDS = {"concuss_duration_s": "concuss", "flash_max_duration_s": "blind",
                 "slow_buff_duration_s": "slow", "stun_duration_s": "stun",
                 "suppression_duration_s": "suppress"}
EFFECT_PREFIX = re.compile(r"^(Buff|Debuff|BlindConfig)_", re.I)
#: A world object or pawn the ability spawns or names drafts `deployed`; a
#: parent class and a trajectory warning are not the ability's own object.
DEPLOYED_PREFIX = re.compile(r"^(GameObject|Pawn|AIPawn|Patch|Zone)_", re.I)
NOT_DEPLOYED = re.compile(r"parent|_base$|trajectorywarning", re.I)
RECALL_STATE = re.compile(r"recall|reactivat|pickup|reclaim", re.I)
DESTROY_KEYS = ("CooldownOnDestroy", "DestroyedCooldown", "RefundOnDestroyed")
OWNER_DEATH_KEYS = ("DestroyOnOwnerDeath", "DestroyIfInstigatorDies")
#: A spawn call in exported bytecode; the spawned class follows its name.
SPAWN_CALL = re.compile(r'"(CallFunc_(?:FinishSpawningActor|BeginDeferredActorSpawnFromClass'
                        r'|BeginSpawningActorFromClass|SpawnActor\w*)_ReturnValue\w*)"')
#: A game-data fact's source names each value, then the asset it reads.
VALUE_ASSET = re.compile(r"(\w+):\s+(ShooterGame/\S+?)\.uasset")
#: Objects a player cannot see: managers, spawners and other engine helpers.
UNSEEN = re.compile(r"manager|spawner|precomputed", re.I)


def subject_of(agent: str, ability: str) -> str:
    """`<agent>:<ability>` as the domain facts write it: lower case, one space."""
    return f"{agent.lower()}:{' '.join(ability.lower().split())}"


def _subject_norm(subject: str) -> str:
    return " ".join(subject.lower().replace("-", " ").split())


def _sheet_cell(status: str, value=None, sources=(), basis: str = "", candidates=None,
          display: str = "") -> dict:
    out = {"status": status, "value": value, "sources": list(sources), "basis": basis}
    if candidates is not None:
        out["candidates"] = candidates
    out["display"] = display or ("" if value is None else _show(value))
    return out


def _show(value) -> str:
    if isinstance(value, list):
        return ", ".join(_show(v) for v in value)
    if isinstance(value, dict):
        return "; ".join(f"{k}: {_show(v)}" for k, v in value.items())
    return str(value)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

class GameExports:
    """Reads the exported class JSON of an ability's equippable and entities."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self._cache: dict[str, list | None] = {}

    def rel(self, game_path: str) -> str:
        return f"{GAME_EXPORTS}/{game_path[len('/Game/'):]}.json"

    def exports(self, game_path: str) -> list | None:
        if game_path not in self._cache:
            p = self.root / self.rel(game_path)
            self._cache[game_path] = (json.loads(p.read_text(encoding="utf-8"))
                                      if p.is_file() else None)
        return self._cache[game_path]

    def destruction(self, game_path: str) -> dict:
        """Evidence in one class: destructible yes/no, destroyed on owner death."""
        out = {"yes": [], "no": [], "owner_death": []}
        rel = self.rel(game_path)
        for ex in self.exports(game_path) or []:
            props = ex.get("Properties") or {}
            name = ex.get("Name", "")
            where = f"{rel}#{name}"
            for k in DESTROY_KEYS:
                if k in props and props[k] not in (False, 0, None):
                    out["yes"].append(f"{where}.{k} = {props[k]}")
            for k in OWNER_DEATH_KEYS:
                if props.get(k) is True:
                    out["owner_death"].append(f"{where}.{k} = true")
            if "DamageSection" in ex.get("Type", ""):
                life = props.get("Life")
                if props.get("bCanBeDestroyed") is False:
                    out["no"].append(f"{where}.bCanBeDestroyed = false")
                elif props.get("bCanBeDestroyed") is True:
                    out["yes"].append(f"{where}.bCanBeDestroyed = true, Life = {life}")
                elif isinstance(life, (int, float)) and life > 0:
                    out["yes"].append(f"{where}.Life = {life} (bCanBeDestroyed not "
                                      f"exported; its default is unread)")
        return out

    def supers(self, game_path: str, limit: int = 8) -> list[str]:
        """The class's parent classes under /Game/, nearest first (`SuperStruct`)."""
        out, node = [], game_path
        for _ in range(limit):
            nxt = None
            for ex in self.exports(node) or []:
                if ex.get("Type") == "BlueprintGeneratedClass" and ex.get("SuperStruct"):
                    nxt = str(ex["SuperStruct"].get("ObjectPath", "")).rsplit(".", 1)[0]
                    break
            if not nxt or not nxt.startswith("/Game/") or self.exports(nxt) is None:
                break
            out.append(nxt)
            node = nxt
        return out

    def spawn_calls(self, game_path: str, stem: str) -> list[str]:
        """Spawn calls in a class's bytecode whose return value is `stem`'s class."""
        p = self.root / self.rel(game_path)
        if not p.is_file():
            return []
        text = p.read_text(encoding="utf-8")
        want = f"BlueprintGeneratedClass'{stem}_C'"
        hits = sorted({m.group(1) for m in SPAWN_CALL.finditer(text)
                       if want in text[m.end():m.end() + 800]})
        return [f"{self.rel(game_path)}#{h} returns {stem}" for h in hits]


def _game_data_facts(facts: dict) -> dict[tuple[str, str], list]:
    """(agent prefix, slot) -> the `*-game-data` facts of that ability."""
    out: dict[tuple[str, str], list] = {}
    for key, f in facts.items():
        if not key.startswith("game_data/") or not key.endswith("-game-data"):
            continue
        m = re.search(r"\(slot ([CQEX])\)", f.claim)
        if not m or ":" not in f.subject:
            continue
        out.setdefault((f.subject.split(":", 1)[0], m.group(1)), []).append(f)
    return out


def _view_answers(store_root: Path) -> dict:
    """`visibility:<agent>:<slot>:<view>` -> the player's last sure answer."""
    p = Path(store_root) / VIEW_ANSWERS
    out: dict = {}
    if not p.is_file():
        return out
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if str(r.get("key", "")).startswith("visibility:"):
            out[r["key"]] = None if r.get("unsure") else r.get("answer")
    return out


# ---------------------------------------------------------------------------
# The pre-fill
# ---------------------------------------------------------------------------

def _stem(path: str) -> str:
    return path.rsplit("/", 1)[-1]


def _objects(ab: dict) -> list[str]:
    """The world objects and pawns an ability spawns or names, in export order."""
    out: list[str] = []
    for e in ab.get("entities", []):
        short = _stem(e["entity"])
        if DEPLOYED_PREFIX.match(short) and not NOT_DEPLOYED.search(short) \
                and e["entity"] not in out:
            out.append(e["entity"])
    return out


def _referrers(ab: dict) -> dict[str, dict]:
    """entity path -> the states table's first `named_by`/`how` for it."""
    out: dict[str, dict] = {}
    for e in ab.get("entities", []):
        out.setdefault(e["entity"], e)
    return out


def _owner_object(path: str, ab: dict, objects: list[str]) -> str | None:
    """The nearest object above `path` on the reference chain, itself included."""
    refs = _referrers(ab)
    node, seen = path, set()
    while node and node not in seen:
        if node in objects:
            return node
        seen.add(node)
        node = refs.get(node, {}).get("named_by")
    return None


def _value_assets(f) -> dict[str, str]:
    """A game-data fact's value name -> the class stem its source reads it from."""
    src = " ".join(f.source.split())
    return {n: _stem(p) for n, p in VALUE_ASSET.findall(src)}


class Scope:
    """What one row reads: its classes, and whether it is the whole ability.

    A whole row reads every class of the ability. An object row reads the
    object's class, its parent classes and the classes only it references;
    `ability_level` holds the classes no object owns (the held equippable, a
    tuning table, a projectile in flight), shown to the player beside each
    object row and never pre-filled into it.
    """

    def __init__(self, ab: dict, exports: "GameExports", obj: str | None, split: bool):
        self.obj, self.split = obj, split
        objects = _objects(ab)
        entities = [e["entity"] for e in ab.get("entities", [])]
        equip = ab.get("equippable")
        if not split:
            self.paths = [p for p in [equip] + entities if p]
            self.ability_level: list[str] = []
        else:
            mine = [p for p in entities if _owner_object(p, ab, objects) == obj]
            self.paths = list(dict.fromkeys([obj] + mine + exports.supers(obj)))
            self.ability_level = [p for p in [equip] + entities
                                  if p and _owner_object(p, ab, objects) is None]
        self.stems = {_stem(p) for p in self.paths}
        self.level_stems = {_stem(p) for p in self.ability_level}

    def owns_state(self, s: dict) -> bool:
        if s.get("owner_kind") == "equippable":
            return not self.split
        return _stem(s["owner"]) in self.stems

    def owns_value(self, asset: str | None) -> str:
        """'own', 'ability' (ability-level) or 'other' (another object's)."""
        if not self.split:
            return "own"
        if asset in self.stems:
            return "own"
        if asset is None or asset in self.level_stems or asset.startswith("AbilityTuning_"):
            return "ability"
        return "other"


def _parent(obj: str | None, ab: dict, objects: list[str], exports: "GameExports",
            table_ref: str) -> dict:
    """The object's parent in the spawn tree, from the game files' spawn relations."""
    if obj is None:
        return _sheet_cell("n/a", basis="the row is the whole ability; nothing spawned")
    refs = _referrers(ab)
    first = refs.get(obj, {})
    referrer = first.get("named_by")
    path = [_stem(obj)]
    node = referrer
    while node and node not in objects and node in refs:
        path.append(_stem(node))
        node = refs[node].get("named_by")
    if node:
        path.append(_stem(node))
    parent = _stem(node) if node in objects else "ability"
    spawn = []
    if first.get("how") == "spawns" and referrer:
        spawn.append(f"{table_ref}: {_stem(referrer)} spawns {_stem(obj)}")
    elif referrer:
        spawn += exports.spawn_calls(referrer, _stem(obj))
    chain = " <- ".join(path)
    if not spawn:
        return _sheet_cell("ask", basis=f"the exports reference it ({chain}) but show no spawn")
    return _sheet_cell("confirm", parent, spawn, basis=f"spawn chain {chain}")


def _lifecycle_class(gd: list, ab: dict, scope: Scope) -> dict:
    found: dict[str, list[str]] = {}
    if scope.split:
        found["deployed"] = [f"object class {scope.obj}"]
    else:
        for f in gd:
            if f.values.get("move"):
                found.setdefault("movement", []).append(
                    f"[domain:{f.key}] caster movement: {_show(f.values['move'])}")
        for e in ab.get("entities", []):
            short = _stem(e["entity"])
            if DEPLOYED_PREFIX.match(short) and not NOT_DEPLOYED.search(short):
                found.setdefault("deployed", []).append(f"{e.get('how')} {e['entity']}")
    if not found:
        return _sheet_cell("ask", basis="no game-file evidence")
    if len(found) > 1:
        return _sheet_cell("conflict", candidates=sorted(found),
                           sources=[s for k in sorted(found) for s in found[k]],
                           basis="the game files support more than one class")
    (cls, src), = found.items()
    return _sheet_cell("confirm", cls, src, basis=(
        "a world object or pawn" if cls == "deployed" else "the game data gives caster movement"))


def _scoped_values(gd: list, group: str, scope: Scope):
    """(fact, name, value, 'own'|'ability') for one value group in the row's scope."""
    for f in gd:
        assets = _value_assets(f)
        for name, v in sorted((f.values.get(group) or {}).items()):
            where = scope.owns_value(assets.get(name))
            if where != "other":
                yield f, name, v, where, assets.get(name)


def _lifetime(gd: list, scope: Scope) -> dict:
    cands = []
    for f, name, v, where, asset in _scoped_values(gd, "life", scope):
        if isinstance(v, (int, float)):
            label = f"{name} = {v} s" + (f" (ability-level, {asset})" if where == "ability" else "")
            cands.append({"ref": f"{f.key}#life.{name}", "s": float(v), "label": label})
    if not cands:
        return _sheet_cell("ask", basis="no life value in the game data for this row")
    src = sorted({f"[domain:{c['ref'].split('#')[0]}]" for c in cands})
    if len(cands) == 1 and "ability-level" not in cands[0]["label"]:
        return _sheet_cell("confirm", cands[0], src, basis="the one life value",
                           candidates=cands, display=cands[0]["label"])
    return _sheet_cell("confirm", None, src, candidates=cands,
                       basis="pick this row's own life value, or none",
                       display=" | ".join(c["label"] for c in cands))


def _fact_cells(subject: str, column: str, facts: dict) -> dict[str, list[str]]:
    """Values a domain fact gives one cell of the row whose subject is `subject`."""
    out: dict[str, list[str]] = {}
    for key, f in facts.items():
        if not key.startswith("abilities/") or _subject_norm(f.subject) != _subject_norm(subject):
            continue
        got = getattr(f, column, "")
        if got:
            out.setdefault(got, []).append(f"[domain:{key}]")
        if column == "owner_death" and key.endswith("-persists-after-death"):
            v = "disabled" if "deactivated" in f.claim else "persists"
            out.setdefault(v, []).append(f"[domain:{key}]")
    pf = PLAYER_FACT_CELLS.get((subject, column))
    if pf and pf[1] in facts:
        out.setdefault(pf[0], []).append(f"[domain:{pf[1]}]")
    return out


def _decide(srcs: dict[str, list[str]], none_basis: str) -> dict:
    srcs = {k: v for k, v in srcs.items() if v}
    if not srcs:
        return _sheet_cell("ask", basis=none_basis)
    if len(srcs) > 1:
        return _sheet_cell("conflict", candidates=sorted(srcs),
                           sources=[s for k in sorted(srcs) for s in srcs[k]],
                           basis="the sources disagree")
    (v, src), = srcs.items()
    return _sheet_cell("confirm", v, src)


def _destructible(subject: str, evidence: dict, facts: dict) -> dict:
    srcs = {"yes": list(evidence["yes"]), "no": list(evidence["no"])}
    for v, s in _fact_cells(subject, "destructible", facts).items():
        srcs.setdefault(v, []).extend(s)
    return _decide(srcs, "no game-file evidence")


def _owner_death(subject: str, evidence: dict, facts: dict) -> dict:
    srcs: dict[str, list] = {}
    if evidence["owner_death"]:
        srcs["destroyed"] = list(evidence["owner_death"])
    for v, s in _fact_cells(subject, "owner_death", facts).items():
        srcs.setdefault(v, []).extend(s)
    return _decide(srcs, "no game-file evidence or fact")


def _states(ab: dict, scope: Scope, table_ref: str) -> dict:
    groups: dict[str, list[str]] = {}
    for s in ab.get("states", []):
        if not s.get("phase") or not scope.owns_state(s):
            continue
        owner = "held" if s.get("owner_kind") == "equippable" else _stem(s["owner"])
        seq = groups.setdefault(owner, [])
        if s["phase"] not in seq:
            seq.append(s["phase"])
    if not groups:
        return _sheet_cell("ask", basis="the game data names no phase for this row")
    return _sheet_cell("confirm", groups, [table_ref],
                       basis="lexical phases of the game's state names, in export order")


def _recall(subject: str, ab: dict, scope: Scope, facts: dict, table_ref: str) -> list[str]:
    src = [f"[domain:{k}]" for k, f in sorted(facts.items())
           if k.startswith("abilities/") and f.known == "measured"
           and _subject_norm(f.subject) == _subject_norm(subject) and re.search(r"recall|pickup", k)]
    names = sorted({s["state"] for s in ab.get("states", [])
                    if RECALL_STATE.search(s["state"]) and scope.owns_state(s)})
    if names:
        src.append(f"{table_ref} states {', '.join(names[:4])}")
    return src


def _effect_kinds(short: str) -> list[str]:
    return [kind for kind, pat in EFFECT_WORDS
            if re.search(pat, short, re.I) or (kind == "blind" and short.lower().startswith("blindconfig"))]


def _effects(gd: list, scope: Scope) -> tuple[dict, list[str]]:
    """The row's effect cell, and the ability-level effects shown beside it."""
    found: dict[str, dict] = {}
    level: list[str] = []
    for p in scope.paths:
        if EFFECT_PREFIX.match(_stem(p)):
            for kind in _effect_kinds(_stem(p)):
                found.setdefault(kind, {"effect": kind, "via": []})["via"].append(p)
    for p in scope.ability_level:
        if EFFECT_PREFIX.match(_stem(p)):
            level += [f"{k} ({_stem(p)})" for k in _effect_kinds(_stem(p))]
    for group in ("life", "other"):
        for f, name, v, where, asset in _scoped_values(gd, group, scope):
            kind = EFFECT_FIELDS.get(name)
            if not kind:
                continue
            if where == "ability":
                level.append(f"{kind} ({name} = {v}, {asset})")
                continue
            d = found.setdefault(kind, {"effect": kind, "via": []})
            d["via"].append(f"[domain:{f.key}] {name} = {v}")
            d["duration_s"] = v
    if not found:
        return _sheet_cell("ask", basis="no effect class or field in the game data for this row"), level
    value = [found[k] for k in sorted(found)]
    return _sheet_cell("confirm", value, [v for d in value for v in d["via"]],
                       basis="effect kinds read from the game's class and field names",
                       display=", ".join(d["effect"] for d in value)), level


def _minimap(ab: dict, gd: list, scope: Scope, views: dict, agent: str, slot: str,
             table_ref: str) -> dict:
    drawn: dict[str, dict] = {}
    for s in ab.get("states", []):
        if not scope.owns_state(s):
            continue
        for i in s.get("icons", []):
            if not str(i.get("role", "")).startswith("minimap"):
                continue
            owner = "held" if s.get("owner_kind") == "equippable" else _stem(s["owner"])
            d = drawn.setdefault(i["texture"], {"owner": owner, "views": {}})
            for v, on in (i.get("views") or {}).items():
                if on is not None:
                    d["views"][v] = d["views"].get(v) or on
    sizes, srcs = {}, []
    for f, name, v, where, _asset in _scoped_values(gd, "minimap", scope):
        if where == "own":
            sizes[name] = v
            srcs.append(f"[domain:{f.key}]")
    if not drawn and not sizes:
        return _sheet_cell("ask", basis="the game data names no minimap texture or size for this row")
    evidence = {"textures": drawn, "sizes_m": sizes}
    srcs = ([table_ref] if drawn else []) + sorted(set(srcs))
    if not drawn:
        cell = _sheet_cell("ask", sources=srcs, basis="the game files give a minimap size only")
        cell["evidence"] = evidence
        return cell
    # A minimap texture is an icon; whether a shape joins it the player says.
    value = "icon"
    disagree = []
    for view, key in (("self", "self"), ("teammate", "ally"), ("enemy", "enemy")):
        ans = views.get(f"visibility:{agent}:{slot}:{key}")
        if ans == "nothing" and any(d["views"].get(view) for d in drawn.values()):
            disagree.append(f"{view}: the game data draws a texture; the player answered nothing")
    disp = "; ".join(f"{t} ({d['owner']}; {','.join(v for v, on in d['views'].items() if on) or 'views unread'})"
                     for t, d in drawn.items())
    if sizes:
        disp += ("; " if disp else "") + "sizes " + _show(sizes)
    if disagree:
        cell = _sheet_cell("conflict", value, srcs + [VIEW_ANSWERS], basis="; ".join(disagree),
                           display=disp)
    else:
        cell = _sheet_cell("confirm", value, srcs, display=disp)
    cell["evidence"] = evidence
    return cell


def _visible(subject: str, ability_subject: str, facts: dict) -> dict:
    """What the player sees, cast to gone: only from a fact that states it.

    No fact carries the visible phases yet, so every cell asks; the lifecycle
    and minimap facts on the subject travel with it as evidence.
    """
    keys = sorted(k for k, f in facts.items()
                  if k.startswith(("abilities/", "minimap/")) and f.kind in ("lifecycle", "appearance")
                  and _subject_norm(f.subject) in {_subject_norm(subject), _subject_norm(ability_subject)})
    return _sheet_cell("ask", sources=[f"[domain:{k}]" for k in keys],
                       basis="no fact states the visible phases")


def build_rows(states_doc: dict, facts: dict, exports: "GameExports", views: dict) -> list[dict]:
    """One row per ability, or one per spawned object where it spawns several."""
    table_ref = f"{STATES_TABLE[0]}/{STATES_TABLE[1]}.json"
    gdata = _game_data_facts(facts)
    rows = []
    for agent in sorted(states_doc["agents"]):
        abilities = states_doc["agents"][agent]["abilities"]
        for slot in SLOTS:
            ab = abilities.get(slot)
            if not ab:
                continue
            objects = _objects(ab)
            split = len(objects) > 1
            for obj in (objects if split else [objects[0] if objects else None]):
                row = _row(agent, slot, ab, obj, split, objects, gdata, facts,
                           exports, views, table_ref)
                row["codename"] = states_doc["agents"][agent].get("codename", "")
                rows.append(row)
    return rows


def _row(agent, slot, ab, obj, split, objects, gdata, facts, exports, views, table_ref) -> dict:
    ability_subject = subject_of(agent, ab["ability"])
    subject = f"{ability_subject}/{_stem(obj).lower()}" if split else ability_subject
    gd = gdata.get((agent.lower(), slot), [])
    scope = Scope(ab, exports, obj, split)
    evidence = {"yes": [], "no": [], "owner_death": []}
    for path in scope.paths:
        for k, v in exports.destruction(path).items():
            evidence[k] += v
    ref = f"{table_ref}#{agent}/{slot}"
    effects, level_effects = _effects(gd, scope)
    cells = {
        "parent": _parent(obj, ab, objects, exports, table_ref),
        "lifecycle_class": _lifecycle_class(gd, ab, scope),
        "lifetime_s": _lifetime(gd, scope),
        "destructible": _destructible(subject, evidence, facts),
        "owner_death": _owner_death(subject, evidence, facts),
        "engine_states": _states(ab, scope, ref),
        "visible_phases": _visible(subject, ability_subject, facts),
        "effects": effects,
        "minimap_drawing": _minimap(ab, gd, scope, views, agent, slot, ref),
    }
    cells["ends_on"] = _ends_on(cells, _recall(subject, ab, scope, facts, ref))
    # Engine state names are evidence for the contract, never a question.
    cells["engine_states"]["status"] = "hidden"
    if obj and split and UNSEEN.search(_stem(obj)):
        for c in cells:
            if c != "engine_states":
                cells[c] = _sheet_cell("n/a", basis="an engine helper the player cannot see")
    hints = sorted(k for k, f in facts.items()
                   if not k.startswith("game_data/") and f.subject
                   and _subject_norm(f.subject) in {_subject_norm(subject), _subject_norm(ability_subject)})
    return {"agent": agent, "slot": slot, "ability": ab["ability"],
            "object": _stem(obj) if obj else None, "object_class": obj,
            "part": _stem(obj) if split else "", "subject": subject,
            "siblings": [_stem(o) for o in objects if o != obj] if split else [],
            "game_data": sorted(f.key for f in gd),
            "cells": {c: cells[c] for c in COLUMNS}, "hints": hints,
            "ability_level": {"classes": [_stem(p) for p in scope.ability_level],
                              "effects": level_effects}}


def _ends_on(cells: dict, recall_src: list[str]) -> dict:
    members: dict[str, list[str]] = {}
    life = cells["lifetime_s"]
    if life["status"] != "ask" and any("ability-level" not in c["label"]
                                       for c in life.get("candidates") or []):
        members["lifetime"] = list(life["sources"])
    if cells["destructible"]["value"] == "yes":
        members["destroyed"] = list(cells["destructible"]["sources"])
    if cells["owner_death"]["value"] in ("disabled", "destroyed"):
        members["owner_death"] = list(cells["owner_death"]["sources"])
    if recall_src:
        members["recall_or_reactivation"] = recall_src
    if not members:
        return _sheet_cell("ask", ["round_end"], basis="round_end only, by the player's rule")
    value = [m for m in ENDS if m in members] + ["round_end"]
    status = "conflict" if any(cells[c]["status"] == "conflict"
                               for c in ("destructible", "owner_death")) else "confirm"
    return _sheet_cell(status, value, [s for m in members for s in members[m]],
                       basis="members with a source; round_end by the player's rule")


def status_counts(rows: list[dict]) -> dict:
    out = {c: {"confirm": 0, "ask": 0, "conflict": 0, "n/a": 0, "hidden": 0} for c in COLUMNS}
    for r in rows:
        for c in COLUMNS:
            out[c][r["cells"][c]["status"]] += 1
    return out


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def build(store_root: Path) -> tuple[Path, list[dict]]:
    """Write the pre-fill (JSONL, a CSV to read, provenance) under the store."""
    store_root = Path(store_root)
    table = store_root / STATES_TABLE[0] / f"{STATES_TABLE[1]}.json"
    states_doc = json.loads(table.read_text(encoding="utf-8"))
    facts = domain.load()
    rows = build_rows(states_doc, facts, GameExports(store_root), _view_answers(store_root))
    out_dir = store_root / PREFILL_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    jl = out_dir / f"{VERSION}.jsonl"
    jl.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                  encoding="utf-8", newline="\n")
    with (out_dir / f"{VERSION}.csv").open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["agent", "slot", "ability", "object", "object_class"]
                   + [x for c in COLUMNS for x in (c, f"{c}_status", f"{c}_sources")])
        for r in rows:
            w.writerow([r["agent"], r["slot"], r["ability"], r["object"] or "", r["object_class"] or ""] + [
                x for c in COLUMNS for x in (r["cells"][c]["display"], r["cells"][c]["status"],
                                             " | ".join(r["cells"][c]["sources"]))])
    prov = {"version": VERSION, "build": BUILD, "built_utc": _dt.datetime.now(_dt.timezone.utc).isoformat(),
            "rows": len(rows), "counts": status_counts(rows), "default_rules": DEFAULT_RULES,
            "inputs": {"states_table": [str(table.relative_to(store_root)), _file_sha(table)],
                       "domain": {p.name: _file_sha(p) for p in sorted(domain.DOMAIN_DIR.glob("*.toml"))},
                       "view_answers": VIEW_ANSWERS}}
    (out_dir / f"provenance-{VERSION}.json").write_text(json.dumps(prov, indent=1), encoding="utf-8")
    return jl, rows


def load_prefill_rows(store_root: Path) -> list[dict]:
    p = Path(store_root) / PREFILL_DIR / f"{VERSION}.jsonl"
    if not p.is_file():
        raise SystemExit(f"no pre-fill at {p}; run `reticle mechanics-sheet build` first")
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


# ---------------------------------------------------------------------------
# Answers
# ---------------------------------------------------------------------------

def cell_key(row: dict, column: str, sub: str = "") -> str:
    part = f":{row['part']}" if row.get("part") else ""
    return f"{row['agent']}:{row['slot']}{part}:{column}" + (f":{sub}" if sub else "")


def _renamed_key(key: str) -> str:
    """An answer key under its column's current name (`RENAMED`)."""
    head, _, rest = key.rpartition(":")
    for old, new in RENAMED.items():
        if rest == old:
            return f"{head}:{new}"
        if f":{old}:" in key:
            return key.replace(f":{old}:", f":{new}:")
    return key


def load_sheet_answers(store_root: Path) -> dict:
    """key -> the last answer row (labelling-pass: the last row wins).

    An answer given under a renamed column reads under its new name, so an
    older sheet's answers stay valid.
    """
    p = Path(store_root) / ANSWERS
    out: dict = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[_renamed_key(r["key"])] = r
    return out


def append_answer(store_root: Path, row: dict) -> None:
    p = Path(store_root) / ANSWERS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


# ---------------------------------------------------------------------------
# Plain words: what the player reads
# ---------------------------------------------------------------------------

#: Class-name words that name nothing a player sees.
NOISE_WORDS = {"production", "removable", "object", "possessable", "new", "v2", "base",
               "s0", "gen", "variable", "c", "q", "e", "x", "4"}


def object_words(stem: str, codename: str = "") -> str:
    """A class name in the player's words: `Pawn_Gumshoe_E_PossessableCamera` -> camera."""
    body = re.sub(r"^(GameObject|Gameobject|Pawn|AIPawn|Patch|Zone)_", "", stem)
    words = []
    for token in body.split("_"):
        words += re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+|\d+", token)
    keep = [w.lower() for w in words
            if w.lower() not in NOISE_WORDS and w.lower() != codename.lower()]
    return " ".join(keep) or "object"


def thing_name(row: dict) -> str:
    """The thing a row asks about: the ability, or `<ability>'s <object>`."""
    if not row.get("part"):
        return row["ability"]
    return f"{row['ability']}'s {object_words(row['part'], row.get('codename', ''))}"


def _sibling_name(row: dict, stem: str) -> str:
    return f"{row['ability']}'s {object_words(stem, row.get('codename', ''))}"


def evidence_line(cell: dict) -> str:
    """One short line naming the kinds of source, never a class or a field."""
    kinds = []
    for s in cell.get("sources") or []:
        if s.startswith("[domain:abilities/") or s.startswith("[domain:minimap/"):
            kind = "a recorded fact"
        elif s.startswith("[domain:game_data/") or s.startswith("reference/") or "/Game/" in s \
                or s.startswith("object class") or s.startswith(("spawns", "names")):
            kind = "the game files"
        elif s.startswith("labels/"):
            kind = "your earlier minimap answers"
        else:
            kind = "the game files"
        if kind not in kinds:
            kinds.append(kind)
    return f"  (source: {', '.join(kinds)})" if kinds else ""


def _seconds(v: float) -> str:
    return f"{v:g} seconds"


def cell_question(row: dict, column: str, answers: dict, sub: str = "") -> tuple[str, list[tuple[str, object]], str]:
    """(question, [(choice words, stored value)], suggestion) for one cell."""
    name, agent = thing_name(row), row["agent"]
    cell = row["cells"][column.split(":")[0]]
    value = cell.get("value")
    if column == "parent":
        opts = [(f"{agent}, casting {row['ability']}", "ability")] + [
            (_sibling_name(row, s), s) for s in row.get("siblings", [])][:5]
        sug = dict((v, w) for w, v in opts).get(value, "") if cell["status"] == "confirm" else ""
        return f"What creates {name}?", opts, sug
    if column == "lifecycle_class":
        opts = [("something placed in the world that stays for a while", "deployed"),
                ("a one-off burst that leaves nothing behind", "instant"),
                (f"a boost on {agent}", "self_buff"),
                (f"something {agent} holds and uses like a weapon", "equipped"),
                (f"a dash or teleport that moves {agent}", "movement")]
        sug = dict((v, w) for w, v in opts).get(value, "") if cell["status"] == "confirm" else ""
        return f"What kind of thing is {name}?", opts, sug
    if column == "visible_phases":
        return (f"What does {name} look like on the minimap and on screen, from cast to gone? "
                f"Type the steps in order, separated by arrows or commas "
                f"(for example: thrown -> placed -> activated -> gone)."), [], ""
    if column == "lifetime_s":
        cands = cell.get("candidates") or []
        opts = [(_seconds(c["s"]), c) for c in cands[:5]] + [("it has no time limit", "none")]
        sug = _seconds(value["s"]) if isinstance(value, dict) else ""
        return f"How long does {name} last if nothing ends it early?", opts, sug
    if column == "destructible":
        opts = [("yes", "yes"), ("no", "no")]
        return f"Can enemies shoot or break {name}?", opts, value if cell["status"] == "confirm" else ""
    if column == "owner_death":
        opts = [("stops working but stays", "disabled"), ("disappears", "destroyed"),
                ("stays and keeps working", "persists"),
                ("doesn't apply: nothing of it is left in the world", "not_applicable")]
        sug = dict((v, w) for w, v in opts).get(value, "") if cell["status"] == "confirm" else ""
        return f"When {agent} dies, {name}:", opts, sug
    if column == "ends_on":
        opts = [("its time runs out", "lifetime"), ("enemies destroy it", "destroyed"),
                (f"{agent} dies", "owner_death"),
                (f"{agent} picks it up or uses it again", "recall_or_reactivation")]
        words = dict((v, w) for w, v in opts)
        sug = ", ".join(words[m] for m in (value or []) if m in words) if cell["status"] == "confirm" else ""
        return (f"What can end {name}? Type every number that applies "
                f"(0 for none of these). The round's end always ends it."), opts, sug
    if column == "effects":
        sug = ", ".join(d["effect"] for d in value or []) if cell["status"] == "confirm" else ""
        return (f"What does {name} do to players (blind, slow, heal, reveal, ...)? "
                f"Type the effects, separated by commas, or 0 for none."), [], sug
    if column == "effects:targets":
        opts = [(agent, "self"), (f"{agent}'s teammates", "allies"), ("enemies", "enemies")]
        return f"Who does {name}'s {sub} reach? Type every number that applies.", opts, ""
    if column == "minimap_drawing":
        opts = [("an icon", "icon"), ("a shape or area", "shape"),
                ("both an icon and a shape", "icon_and_shape"), ("nothing", "nothing")]
        sug = dict((v, w) for w, v in opts).get(value, "") if cell["status"] in ("confirm", "conflict") else ""
        return f"How does {name} show on the minimap?", opts, sug
    raise ValueError(column)


def default_for(row: dict, column: str, answers: dict):
    """The player's default rule for a cell, given this ability's answers so far."""
    def got(c):
        a = answers.get(cell_key(row, c))
        return None if a is None or a.get("unsure") else a.get("answer")
    if got("lifecycle_class") != "deployed":
        return None
    life = got("lifetime_s")
    if column == "owner_death":
        return "disabled"
    if column == "destructible" and life == "none":
        return "yes"
    if column == "ends_on" and life is not None:
        ends = ["lifetime"] if life != "none" else ["destroyed"]
        if life != "none" and got("destructible") == "yes":
            ends.append("destroyed")
        return [m for m in ENDS if m in ends + ["owner_death"]] + ["round_end"]
    return None


#: Statuses that are not questions: hidden evidence, or a cell no one can observe.
NOT_ASKED = ("n/a", "hidden")


def questions(rows: list[dict], answers: dict, columns=COLUMNS, agent: str | None = None,
              reask_unsure: bool = False) -> list[tuple[dict, str, str]]:
    """(row, column, key) for every open cell: by agent, ability, object, column.

    Effect targets follow the effects cell: one question per effect named.
    """
    order = {s: i for i, s in enumerate(SLOTS)}
    out = []
    for r in sorted(rows, key=lambda r: (r["agent"].lower(), order.get(r["slot"], 9),
                                         bool(r.get("part")) and r["cells"]["parent"].get("value") != "ability",
                                         r.get("part") or "")):
        if agent and r["agent"].lower() != agent.lower():
            continue
        for c in columns:
            if r["cells"][c]["status"] in NOT_ASKED:
                continue
            k = cell_key(r, c)
            a = answers.get(k)
            if a is None or (reask_unsure and a.get("unsure")):
                out.append((r, c, k))
            elif c == "effects" and not a.get("unsure"):
                for kind in a.get("answer") or []:
                    tk = cell_key(r, "effects", f"{kind}:targets")
                    ta = answers.get(tk)
                    if ta is None or (reask_unsure and ta.get("unsure")):
                        out.append((r, "effects:targets", tk))
    return out


def _parse_typed(column: str, text: str, cell: dict, opts: list, row: dict, answers: dict):
    """(answer, how) for one typed line, or None when it does not parse."""
    t = text.strip()
    if t == "y":
        if column == "effects":
            return [d["effect"] for d in cell["value"] or []] or None, "confirm"
        if column in ("effects:targets", "visible_phases") or cell["status"] not in ("confirm",) \
                or cell["value"] is None:
            return None  # nothing suggested: answer the question
        return cell["value"], "confirm"
    if t == "d":
        v = default_for(row, column, answers)
        return (v, "default") if v is not None else None
    if column == "visible_phases":
        steps = [s.strip() for s in re.split(r"->|→|,", t) if s.strip()]
        return (steps, "typed") if steps else None
    if column == "effects":
        if t == "0":
            return [], "typed"
        kinds = [s.strip().lower() for s in t.split(",") if s.strip()]
        return (kinds, "typed") if kinds and not t.isdigit() else None
    if t == "0" and column == "ends_on":
        return ["round_end"], "choose"
    multi = column in ("ends_on", "effects:targets")
    if t and all(ch.isdigit() for ch in t) and (multi or len(t) == 1):
        idx = sorted({int(ch) for ch in t})
        if any(i < 1 or i > len(opts) for i in idx):
            return None
        if multi:
            vals = [opts[i - 1][1] for i in idx]
            return (vals + ["round_end"] if column == "ends_on" else vals), "choose"
        return opts[idx[0] - 1][1], "choose"
    if t.startswith("7 ") or t.startswith("7:"):
        body = t[2:].strip()
        if not body:
            return None
        if column == "lifetime_s":
            if cell.get("candidates"):
                return None  # a game-file value stands; pick one or none
            try:
                return {"player_s": float(body)}, "other"
            except ValueError:
                return None
        return body, "other"
    return None


def _print_header(out) -> None:
    out.write("Ability mechanics sheet. Your defaults, which d applies to a question:\n")
    for rule in DEFAULT_RULES:
        out.write(f"  - {rule}\n")
    out.write("Keys: a number picks; y accepts the suggestion; '7 words' answers in your "
              "own words; u unsure; a back; q quit.\n\n")


def render(row: dict, column: str, key: str, answers: dict, remaining: int | None = None) -> tuple[str, list]:
    """The exact text the walker prints for one cell, and its choices."""
    sub = key.split(":")[-2] if column == "effects:targets" else ""
    question, opts, sug = cell_question(row, column.split(":")[0] if column != "effects:targets" else column,
                                 answers, sub)
    cell = row["cells"][column.split(":")[0]]
    lines = []
    head = f"[{remaining} left] " if remaining is not None else ""
    lines.append(f"{head}{row['agent']} -- {thing_name(row)}")
    lines.append(f"  {question}")
    for i, (words, _v) in enumerate(opts, 1):
        lines.append(f"    {i} {words}")
    if column == "ends_on":
        lines.append("    0 none of these")
    if sug:
        lines.append(f"  Suggested: {sug}. Press y to accept.")
    if cell["status"] == "conflict" and column != "effects:targets":
        lines.append("  The sources disagree; please choose.")
    dv = default_for(row, column, answers)
    if dv is not None:
        words = dict((v, w) for w, v in opts)
        shown = ", ".join(words.get(x, x) for x in dv if x != "round_end") if isinstance(dv, list) \
            else words.get(dv, dv)
        lines.append(f"  d = your default: {shown}")
    if column != "effects:targets":
        ev = evidence_line(cell)
        if ev:
            lines.append(ev)
        elif not sug:
            lines.append("  (the game files don't say)")
    return "\n".join(lines) + "\n", opts


def walk(store_root: Path, rows: list[dict], *, by: str = "player", columns=COLUMNS,
         agent: str | None = None, reask_unsure: bool = False,
         read=input, out=sys.stdout) -> int:
    """Ask every open cell in turn; append one answer row per answer."""
    _print_header(out)
    history: list[tuple[dict, str, str]] = []
    back: list[tuple[dict, str, str]] = []
    while True:
        answers = load_sheet_answers(store_root)
        todo = questions(rows, answers, columns, agent, reask_unsure)
        if back:
            todo = [back[-1]] + todo
        if not todo:
            out.write("Nothing left to ask.\n")
            return 0
        r, column, key = todo[0]
        cell = r["cells"][column.split(":")[0]]
        text_out, opts = render(r, column, key, answers, len(todo))
        out.write("\n" + text_out)
        text = read("> ").strip()
        if text in ("q", "\x1b"):
            return 0
        if text == "a":
            # Back one: ask the previous key again; its new answer wins, and
            # quitting first leaves the old one standing.
            if history:
                back.append(history.pop())
            continue
        if text == "u":
            ans, how = None, "unsure"
        else:
            parsed = _parse_typed(column, text, cell, opts, r, answers)
            if parsed is None:
                out.write("  not understood; try again\n")
                continue
            ans, how = parsed
        append_answer(store_root, {
            "key": key, "column": column, "agent": r["agent"], "slot": r["slot"],
            "ability": r["ability"], "object": r.get("object"), "answer": ans, "how": how,
            "unsure": how == "unsure", "by": by, "ts": _now(), "tool": VERSION,
            "prefill_version": VERSION,
            "shown": {"status": cell["status"], "display": cell.get("display", ""),
                      "sources": cell.get("sources", [])},
            "compared_against_derived": column != "effects:targets"})
        if back and back[-1][2] == key:
            back.pop()
        history.append((r, column, key))


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def _id_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def fact_id(row: dict) -> str:
    part = f"-{_id_slug(row['part'])}" if row.get("part") else ""
    return f"{_id_slug(row['agent'])}-{_id_slug(row['ability'])}{part}-lifecycle"


def resolve(row: dict, answers: dict) -> tuple[dict | None, list[str]]:
    """The confirmed values of one row, or None and what is still open."""
    got, missing = {}, []
    if all(row["cells"][c]["status"] in NOT_ASKED for c in COLUMNS):
        return None, ["nothing to confirm: an engine helper"]
    for c in COLUMNS:
        if row["cells"][c]["status"] in NOT_ASKED:
            continue
        a = answers.get(cell_key(row, c))
        if a is None or a.get("unsure") or a.get("answer") is None:
            missing.append(c)
            continue
        got[c] = a
    if "effects" in got:
        targets = {}
        for kind in got["effects"]["answer"]:
            ta = answers.get(cell_key(row, "effects", f"{kind}:targets"))
            if ta is None or ta.get("unsure") or not ta.get("answer"):
                missing.append(f"effects:{kind}:targets")
            else:
                targets[kind] = ta["answer"]
        got["effect_targets"] = targets
    cls = got.get("lifecycle_class", {}).get("answer")
    if cls is not None and cls not in CLASSES:
        missing.append(f"lifecycle_class '{cls}' is not a plan class")
    return (got if not missing else None), missing


def _lifetime_text(ans) -> tuple[str, str]:
    """(fact `lifetime` value, words for the claim)."""
    if ans == "none":
        return "none", "It has no lifetime."
    if isinstance(ans, dict) and "ref" in ans:
        return ans["ref"], (f"Its lifetime is {ans['s']} s, the game data's "
                            f"{ans['ref'].split('#')[1]} [domain:{ans['ref'].split('#')[0]}].")
    if isinstance(ans, dict) and "player_s" in ans:
        return "player", f"Its lifetime is {ans['player_s']} s, by the player."
    raise ValueError(f"unreadable lifetime answer {ans!r}")


def _toml_str(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)


def _toml_list(xs) -> str:
    return "[" + ", ".join(_toml_str(str(x)) for x in xs) + "]"


def _flat_states(value) -> list[str]:
    if isinstance(value, dict):
        seq = []
        for phases in value.values():
            for p in phases:
                if p not in seq:
                    seq.append(p)
        return seq
    return list(value or [])


def fact_text(row: dict, got: dict, since: str) -> str:
    """One `lifecycle` fact in TOML for a confirmed row."""
    lifetime, life_words = _lifetime_text(got["lifetime_s"]["answer"])
    cls = got["lifecycle_class"]["answer"]
    ends = [m for m in ENDS if m in set(got["ends_on"]["answer"]) | {"round_end"}]
    effects = [f"{k}:{'+'.join(got['effect_targets'][k])}" for k in got["effects"]["answer"]]
    draw_words = _show(got["minimap_drawing"]["answer"]).replace("_", " ")
    # The engine's own states stand without a question: game files outrank the player.
    states = _flat_states(row["cells"]["engine_states"].get("value"))
    phases = " -> ".join(got["visible_phases"]["answer"])
    see = sorted({"abilities/ability-rules-are-unique"} | set(row.get("game_data", [])))
    what = f"{row['agent']}'s {row['ability']} (slot {row['slot']})"
    if row.get("part"):
        parent = got["parent"]["answer"]
        what = (f"The {object_words(row['part'], row.get('codename', ''))} of {what} "
                f"({row['part']}), a child of "
                f"{'the ability' if parent == 'ability' else parent},")
    claim = (f"{what} is a {cls} ability. The player sees: {phases}. "
             f"{life_words} It ends on {', '.join(ends)}. Destructible by the enemy: "
             f"{got['destructible']['answer']}. At its owner's death: "
             f"{got['owner_death']['answer']}. Effects: {', '.join(effects) or 'none'}. "
             f"Minimap: {draw_words or 'nothing'}.")
    hows = sorted({a.get("how", "") for a in got.values() if isinstance(a, dict) and "how" in a})
    lines = [
        f"[{fact_id(row)}]",
        'claim = """',
        *_wrap(claim),
        '"""',
        'kind = "lifecycle"',
        'known = "player"',
        f'since = "{since}"',
        f"subject = {_toml_str(row['subject'])}",
        'source = """',
        *_wrap(f"the player confirmed each column through `reticle mechanics-sheet ask` "
               f"({', '.join(hows)}), answers {ANSWERS} under the store; pre-fill "
               f"{VERSION} from the game files of {BUILD} and the domain facts its cells cite"),
        '"""',
        'use = "the ability child\'s lifecycle in slot_state: class, ends, death, destruction and effects"',
        f"states = {_toml_list(states)}",
        f"lifecycle_class = {_toml_str(cls)}",
        f"ends_on = {_toml_list(ends)}",
        f"destructible = {_toml_str(got['destructible']['answer'])}",
        f"owner_death = {_toml_str(got['owner_death']['answer'])}",
        f"effects = {_toml_list(effects)}",
        f"lifetime = {_toml_str(lifetime)}",
        f"see = {_toml_list(see)}",
    ]
    return "\n".join(lines) + "\n"


def _wrap(text: str, width: int = 78) -> list[str]:
    out, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            out.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    if line:
        out.append(line)
    return out


def import_rows(store_root: Path, rows: list[dict], *, write: bool = False,
                target: Path | None = None, out=sys.stdout) -> tuple[list[str], list[str]]:
    """Facts for confirmed rows; append them to `domain/abilities.toml` with `write`."""
    target = Path(target) if target else domain.DOMAIN_DIR / "abilities.toml"
    answers = load_sheet_answers(store_root)
    existing = set(domain.load(target.parent)) if target.parent.is_dir() else set()
    texts, skipped = [], []
    for r in rows:
        got, missing = resolve(r, answers)
        fid = fact_id(r)
        if got is None:
            asked = [c for c in COLUMNS if r["cells"][c]["status"] not in NOT_ASKED]
            if asked and any(c not in missing for c in asked):
                skipped.append(f"{fid}: open {', '.join(missing)}")
            continue
        if f"{target.stem}/{fid}" in existing:
            skipped.append(f"{fid}: exists; supersede it by hand")
            continue
        since = max(a["ts"][:10] for a in got.values() if isinstance(a, dict) and "ts" in a)
        texts.append(fact_text(r, got, since))
    if write and texts:
        with target.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write("".join("\n" + t for t in texts))
    for t in texts:
        out.write(t + "\n")
    for s in skipped:
        out.write(f"skipped {s}\n")
    out.write(f"{len(texts)} confirmed row(s){' written to ' + str(target) if write and texts else ''}; "
              f"{len(skipped)} partly answered row(s) skipped\n")
    return texts, skipped


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None, store_root: Path | None = None) -> int:
    from .store import DEFAULT_STORE
    p = argparse.ArgumentParser(prog="reticle mechanics-sheet")
    p.add_argument("action", choices=("build", "ask", "status", "import"))
    p.add_argument("--store", type=Path, default=store_root or DEFAULT_STORE)
    p.add_argument("--agent")
    p.add_argument("--column", choices=COLUMNS)
    p.add_argument("--by", default="player")
    p.add_argument("--reask-unsure", action="store_true")
    p.add_argument("--write", action="store_true", help="import: append to domain/abilities.toml")
    a = p.parse_args(argv)
    if a.action == "build":
        path, rows = build(a.store)
        print(f"{len(rows)} rows -> {path}")
        _print_counts(rows)
        return 0
    rows = load_prefill_rows(a.store)
    if a.action == "status":
        _print_counts(rows)
        answers = load_sheet_answers(a.store)
        left = questions(rows, answers)
        done = sum(1 for r in rows if resolve(r, answers)[0] is not None)
        print(f"{len(left)} cells open; {done} of {len(rows)} rows confirmed")
        return 0
    if a.action == "ask":
        cols = (a.column,) if a.column else COLUMNS
        return walk(a.store, rows, by=a.by, columns=cols, agent=a.agent,
                    reask_unsure=a.reask_unsure)
    import_rows(a.store, rows, write=a.write, target=domain.DOMAIN_DIR / "abilities.toml")
    return 0


def _print_counts(rows: list[dict]) -> None:
    c = status_counts(rows)
    print(f"{'column':<16} {'pre-filled':>10} {'ask':>5} {'conflict':>8} {'n/a':>5} {'hidden':>6}")
    for col in COLUMNS:
        print(f"{col:<16} {c[col]['confirm']:>10} {c[col]['ask']:>5} {c[col]['conflict']:>8}"
              f" {c[col]['n/a']:>5} {c[col]['hidden']:>6}")
