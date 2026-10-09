"""The ability mechanics sheet, pre-filled from the game files for the player to confirm.

    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet build             # write the pre-fill
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet ask [--agent A] [--column C] [--reask-unsure]
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet status            # counts per column
    .\\.venv\\Scripts\\python.exe -m reticle mechanics-sheet import [--write]  # confirmed rows only

One row per ability (C, Q, E and X) of every agent the game data names, with
eight columns the ability-entity plan needs per ability
(docs/ABILITY_ENTITIES.md, sections 2.4 and 6, question 4):

* `lifecycle_class`: the plan's classes, `domain.LIFECYCLE_CLASSES`.
* `lifetime_s`: a `life` value of the ability's `*-game-data` fact.
* `destructible`: whether the enemy can destroy it, yes or no.
* `owner_death`: disabled, persists, or not applicable (nothing deployed).
* `ends_on`: a set of `domain.ENDS_ON`; `round_end` is always a member.
* `states`: the game data's lexical phases per owner, the held equippable
  and each spawned entity.
* `effects`: the game's buff, debuff and blind classes and effect fields,
  each with its targets.
* `minimap_drawing`: the minimap textures and sizes the game data names.

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
makes `entity_contract.ability_states` check emitted phases against them.

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

VERSION = "mechanics-sheet-0.1.0"
BUILD = "release-13.06-shipping-18-5590001"
#: The game-data states table (`prototypes/ability_states_gamedata.py`).
STATES_TABLE = ("reference/ability-states", "ability-states-gamedata-0.2.0")
GAME_EXPORTS = f"reference/game-files/{BUILD}/ability-states/ShooterGame/Content"
PREFILL_DIR = "reference/mechanics-sheet"
ANSWERS = "labels/mechanics_sheet/answers.jsonl"
#: The player's earlier per-view minimap answers (`prototypes/ask_minimap_glyphs.py`).
VIEW_ANSWERS = "labels/minimap_glyph_questions/answers.jsonl"
SLOTS = ("C", "Q", "E", "X")
COLUMNS = ("lifecycle_class", "lifetime_s", "destructible", "owner_death", "ends_on",
           "states", "effects", "minimap_drawing")
CLASSES = ("deployed", "instant", "self_buff", "equipped", "movement")
ENDS = ("lifetime", "destroyed", "owner_death", "recall_or_reactivation", "round_end")
TARGETS = ("self", "allies", "enemies")
DRAWINGS = ("icon", "shape", "icon_and_shape", "nothing")
assert set(CLASSES) == domain.LIFECYCLE_CLASSES and set(ENDS) == domain.ENDS_ON

#: The player's rules of 2026-10-09, shown in the header and applied by `d`.
DEFAULT_RULES = (
    "Nothing crosses a round barrier: every ability ends by the round's end, "
    "so round_end is a member of every ends_on.",
    "An ability has a lifetime or not; a deployed one without a lifetime lasts "
    "until the enemy destroys it or the round ends.",
    "A deployed ability, an enemy device included, is disabled when its owner dies.",
    "Some abilities with a lifetime can also be destroyed by the enemy "
    "(Miks' heal and concuss throwables).",
    "Buffs, reveals and blinds are effects, entities of their own.",
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

def _lifecycle_class(gd: list, entities: list) -> dict:
    found: dict[str, list[str]] = {}
    for f in gd:
        if f.values.get("move"):
            found.setdefault("movement", []).append(
                f"[domain:{f.key}] caster movement: {_show(f.values['move'])}")
    for e in entities:
        short = e["entity"].rsplit("/", 1)[-1]
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
        "the ability spawns a world object or pawn" if cls == "deployed"
        else "the game data gives caster movement"))


def _lifetime(gd: list) -> dict:
    cands = []
    for f in gd:
        for name, v in sorted((f.values.get("life") or {}).items()):
            if isinstance(v, (int, float)):
                cands.append({"ref": f"{f.key}#life.{name}", "s": float(v),
                              "label": f"{name} = {v} s"})
    if not cands:
        return _sheet_cell("ask", basis="no life value in the game data")
    src = sorted({f"[domain:{c['ref'].split('#')[0]}]" for c in cands})
    if len(cands) == 1:
        return _sheet_cell("confirm", cands[0], src, basis="the one life value",
                     candidates=cands, display=cands[0]["label"])
    return _sheet_cell("confirm", None, src, candidates=cands,
                 basis="several life values: pick the ability's own, or none",
                 display=" | ".join(c["label"] for c in cands))


def _destructible(subject: str, evidence: dict, facts: dict) -> dict:
    srcs = {"yes": list(evidence["yes"]), "no": list(evidence["no"])}
    pf = PLAYER_FACT_CELLS.get((subject, "destructible"))
    if pf and f"{pf[1]}" in facts:
        srcs[pf[0]].append(f"[domain:{pf[1]}]")
    have = [k for k in ("yes", "no") if srcs[k]]
    if not have:
        return _sheet_cell("ask", basis="no game-file evidence")
    if len(have) == 2:
        return _sheet_cell("conflict", candidates=["yes", "no"], sources=srcs["yes"] + srcs["no"],
                     basis="one entity can be destroyed, another cannot")
    return _sheet_cell("confirm", have[0], srcs[have[0]])


def _owner_death(subject: str, evidence: dict, facts: dict) -> dict:
    srcs: dict[str, list] = {}
    if evidence["owner_death"]:
        srcs["disabled"] = [s + " (destroyed at the owner's death)"
                            for s in evidence["owner_death"]]
    for key, f in facts.items():
        if key.startswith("abilities/") and key.endswith("-persists-after-death") \
                and _subject_norm(f.subject) == _subject_norm(subject):
            v = "disabled" if "deactivated" in f.claim else "persists"
            srcs.setdefault(v, []).append(f"[domain:{key}]")
    pf = PLAYER_FACT_CELLS.get((subject, "owner_death"))
    if pf and pf[1] in facts:
        srcs.setdefault(pf[0], []).append(f"[domain:{pf[1]}]")
    if not srcs:
        return _sheet_cell("ask", basis="no game-file evidence or fact")
    if len(srcs) > 1:
        return _sheet_cell("conflict", candidates=sorted(srcs),
                     sources=[s for k in sorted(srcs) for s in srcs[k]],
                     basis="the sources disagree")
    (v, src), = srcs.items()
    return _sheet_cell("confirm", v, src)


def _states(ab: dict, table_ref: str) -> dict:
    groups: dict[str, list[str]] = {}
    for s in ab.get("states", []):
        if not s.get("phase"):
            continue
        owner = "held" if s.get("owner_kind") == "equippable" else s["owner"].rsplit("/", 1)[-1]
        seq = groups.setdefault(owner, [])
        if s["phase"] not in seq:
            seq.append(s["phase"])
    if not groups:
        return _sheet_cell("ask", basis="the game data names no phase")
    return _sheet_cell("confirm", groups, [table_ref],
                 basis="lexical phases of the game's state names, in export order")


def _recall(subject: str, ab: dict, facts: dict, table_ref: str) -> list[str]:
    src = [f"[domain:{k}]" for k, f in sorted(facts.items())
           if k.startswith("abilities/") and f.known == "measured"
           and _subject_norm(f.subject) == _subject_norm(subject) and re.search(r"recall|pickup", k)]
    names = sorted({s["state"] for s in ab.get("states", []) if RECALL_STATE.search(s["state"])})
    if names:
        src.append(f"{table_ref} states {', '.join(names[:4])}")
    return src


def _effects(gd: list, entities: list) -> dict:
    found: dict[str, dict] = {}
    for e in entities:
        short = e["entity"].rsplit("/", 1)[-1]
        if not EFFECT_PREFIX.match(short):
            continue
        for kind, pat in EFFECT_WORDS:
            if re.search(pat, short, re.I) or (kind == "blind" and short.lower().startswith("blindconfig")):
                found.setdefault(kind, {"effect": kind, "via": []})["via"].append(e["entity"])
    for f in gd:
        for group in ("life", "other"):
            for name, v in (f.values.get(group) or {}).items():
                kind = EFFECT_FIELDS.get(name)
                if kind:
                    d = found.setdefault(kind, {"effect": kind, "via": []})
                    d["via"].append(f"[domain:{f.key}] {name} = {v}")
                    d["duration_s"] = v
    if not found:
        return _sheet_cell("ask", basis="no effect class or field in the game data")
    value = [found[k] for k in sorted(found)]
    return _sheet_cell("confirm", value, [v for d in value for v in d["via"]],
                 basis="effect kinds read from the game's class and field names",
                 display=", ".join(d["effect"] for d in value))


def _minimap(ab: dict, gd: list, views: dict, agent: str, slot: str, table_ref: str) -> dict:
    drawn: dict[str, dict] = {}
    for s in ab.get("states", []):
        for i in s.get("icons", []):
            if not str(i.get("role", "")).startswith("minimap"):
                continue
            owner = "held" if s.get("owner_kind") == "equippable" else s["owner"].rsplit("/", 1)[-1]
            d = drawn.setdefault(i["texture"], {"owner": owner, "views": {}})
            for v, on in (i.get("views") or {}).items():
                if on is not None:
                    d["views"][v] = d["views"].get(v) or on
    sizes = {}
    srcs = []
    for f in gd:
        if f.values.get("minimap"):
            sizes.update(f.values["minimap"])
            srcs.append(f"[domain:{f.key}]")
    if not drawn and not sizes:
        return _sheet_cell("ask", basis="the game data names no minimap texture or size")
    value = {"textures": drawn, "sizes_m": sizes}
    srcs = ([table_ref] if drawn else []) + srcs
    disagree = []
    for view, key in (("self", "self"), ("teammate", "ally"), ("enemy", "enemy")):
        ans = views.get(f"visibility:{agent}:{slot}:{key}")
        data_on = any(d["views"].get(view) for d in drawn.values())
        if ans == "nothing" and data_on:
            disagree.append(f"{view}: the game data draws a texture; the player answered nothing")
    disp = "; ".join(f"{t} ({d['owner']}; {','.join(v for v, on in d['views'].items() if on) or 'views unread'})"
                     for t, d in drawn.items())
    if sizes:
        disp += ("; " if disp else "") + "sizes " + _show(sizes)
    if disagree:
        return _sheet_cell("conflict", value, srcs + [VIEW_ANSWERS], basis="; ".join(disagree),
                     display=disp)
    return _sheet_cell("confirm", value, srcs, display=disp)


def build_rows(states_doc: dict, facts: dict, exports: GameExports, views: dict) -> list[dict]:
    """One row per C, Q, E and X ability of every agent in the states table."""
    table_ref = f"{STATES_TABLE[0]}/{STATES_TABLE[1]}.json"
    gdata = _game_data_facts(facts)
    rows = []
    for agent in sorted(states_doc["agents"]):
        abilities = states_doc["agents"][agent]["abilities"]
        for slot in SLOTS:
            ab = abilities.get(slot)
            if not ab:
                continue
            subject = subject_of(agent, ab["ability"])
            gd = gdata.get((agent.lower(), slot), [])
            entities = ab.get("entities", [])
            evidence = {"yes": [], "no": [], "owner_death": []}
            for path in [ab.get("equippable")] + [e["entity"] for e in entities]:
                if path:
                    for k, v in exports.destruction(path).items():
                        evidence[k] += v
            ref = f"{table_ref}#{agent}/{slot}"
            cells = {
                "lifecycle_class": _lifecycle_class(gd, entities),
                "lifetime_s": _lifetime(gd),
                "destructible": _destructible(subject, evidence, facts),
                "owner_death": _owner_death(subject, evidence, facts),
                "states": _states(ab, ref),
                "effects": _effects(gd, entities),
                "minimap_drawing": _minimap(ab, gd, views, agent, slot, ref),
            }
            cells["ends_on"] = _ends_on(cells, _recall(subject, ab, facts, ref))
            hints = sorted(k for k, f in facts.items()
                           if not k.startswith("game_data/") and f.subject
                           and _subject_norm(f.subject) == _subject_norm(subject))
            rows.append({"agent": agent, "slot": slot, "ability": ab["ability"],
                         "subject": subject, "game_data": sorted(f.key for f in gd),
                         "cells": {c: cells[c] for c in COLUMNS}, "hints": hints})
    return rows


def _ends_on(cells: dict, recall_src: list[str]) -> dict:
    members: dict[str, list[str]] = {}
    if cells["lifetime_s"]["status"] != "ask":
        members["lifetime"] = list(cells["lifetime_s"]["sources"])
    if cells["destructible"]["value"] == "yes":
        members["destroyed"] = list(cells["destructible"]["sources"])
    if cells["owner_death"]["value"] == "disabled":
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
    out = {c: {"confirm": 0, "ask": 0, "conflict": 0} for c in COLUMNS}
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
        w.writerow(["agent", "slot", "ability"] + [x for c in COLUMNS for x in (c, f"{c}_status", f"{c}_sources")])
        for r in rows:
            w.writerow([r["agent"], r["slot"], r["ability"]] + [
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
    return f"{row['agent']}:{row['slot']}:{column}" + (f":{sub}" if sub else "")


def load_sheet_answers(store_root: Path) -> dict:
    """key -> the last answer row (labelling-pass: the last row wins)."""
    p = Path(store_root) / ANSWERS
    out: dict = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def append_answer(store_root: Path, row: dict) -> None:
    p = Path(store_root) / ANSWERS
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()


def _options(row: dict, column: str, cell: dict, answers: dict) -> list[tuple[str, object]]:
    """(label, value) per digit key 1..6 for a column."""
    if column == "lifecycle_class":
        return [(c, c) for c in CLASSES]
    if column == "lifetime_s":
        cands = cell.get("candidates") or []
        return [(c["label"], c) for c in cands[:5]] + [("none: no lifetime", "none")]
    if column == "destructible":
        return [("yes", "yes"), ("no", "no")]
    if column == "owner_death":
        return [("disabled", "disabled"), ("persists", "persists"),
                ("not applicable: nothing deployed", "not_applicable")]
    if column == "ends_on":
        return [(m, m) for m in ENDS[:4]]
    if column == "minimap_drawing":
        return [(d, d) for d in DRAWINGS]
    if column == "effects:targets":
        return [(t, t) for t in TARGETS]
    return []


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


def questions(rows: list[dict], answers: dict, columns=COLUMNS, agent: str | None = None,
              reask_unsure: bool = False) -> list[tuple[dict, str, str]]:
    """(row, column, key) for every cell still open, in walking order.

    Effect targets follow the effects cell: one question per confirmed kind.
    """
    out = []
    for r in rows:
        if agent and r["agent"].lower() != agent.lower():
            continue
        for c in columns:
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
        if column == "effects:targets" or cell["status"] != "confirm" or cell["value"] is None:
            return None  # an empty, conflicting or multi-valued pre-fill needs a pick
        return cell["value"], "confirm"
    if t == "d":
        v = default_for(row, column, answers)
        return (v, "default") if v is not None else None
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
        if column in ("states", "effects"):
            return [x.strip() for x in body.split(",") if x.strip()], "other"
        return body, "other"
    return None


def _print_header(out) -> None:
    out.write(f"Ability mechanics sheet ({VERSION}). The player's defaults (key d):\n")
    for rule in DEFAULT_RULES:
        out.write(f"  - {rule}\n")
    out.write("Keys: y confirm the pre-fill; digits pick (several digits for a set); "
              "'7 text' other; d the default; u unsure; a back; q quit.\n\n")


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
        base = column.split(":")[0]
        cell = r["cells"][base]
        out.write(f"\n[{len(todo)} open] {r['agent']} {r['slot']} {r['ability']} -- {column}\n")
        if column == "effects:targets":
            kind = key.split(":")[-2]
            out.write(f"  Who does the {kind} effect reach?\n")
            disp, status, srcs = "", "ask", []
        else:
            disp, status, srcs = cell["display"], cell["status"], cell["sources"]
            out.write(f"  pre-fill [{status}]: {disp or '(empty)'}\n")
            if cell.get("basis"):
                out.write(f"  basis: {cell['basis']}\n")
            for s in srcs[:6]:
                out.write(f"    source: {s}\n")
            if len(srcs) > 6:
                out.write(f"    ... {len(srcs) - 6} more sources in the pre-fill\n")
            for h in r["hints"][:5]:
                out.write(f"    see [domain:{h}]\n")
        opts = _options(r, column, cell, answers)
        for i, (label, _v) in enumerate(opts, 1):
            out.write(f"  {i} {label}\n")
        if column == "ends_on":
            out.write("  0 round_end only (round_end joins every set)\n")
        dv =default_for(r, column, answers)
        if dv is not None:
            out.write(f"  d default: {_show(dv)}\n")
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
            "ability": r["ability"], "answer": ans, "how": how, "unsure": how == "unsure",
            "by": by, "ts": _now(), "tool": VERSION, "prefill_version": VERSION,
            "shown": {"status": status, "display": disp, "sources": srcs},
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
    return f"{_id_slug(row['agent'])}-{_id_slug(row['ability'])}-lifecycle"


def resolve(row: dict, answers: dict) -> tuple[dict | None, list[str]]:
    """The confirmed values of one row, or None and what is still open."""
    got, missing = {}, []
    for c in COLUMNS:
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
    drawing = got["minimap_drawing"]
    draw_words = (drawing["shown"]["display"] if drawing.get("how") == "confirm"
                  else _show(drawing["answer"]))
    states = _flat_states(got["states"]["answer"])
    see = sorted({"abilities/ability-rules-are-unique"} | set(row.get("game_data", [])))
    claim = (f"{row['agent']}'s {row['ability']} (slot {row['slot']}) is a {cls} ability. "
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
            if len(missing) < len(COLUMNS):
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
    print(f"{'column':<16} {'pre-filled':>10} {'ask':>5} {'conflict':>8}")
    for col in COLUMNS:
        print(f"{col:<16} {c[col]['confirm']:>10} {c[col]['ask']:>5} {c[col]['conflict']:>8}")
