r"""Every ability's states, and the sounds and minimap icons of each state, read from the game's own data.

    .\.venv\Scripts\python.exe prototypes\ability_states_gamedata.py build  [--agents Sova,Skye,...] [--out DIR]
    .\.venv\Scripts\python.exe prototypes\ability_states_gamedata.py checks [--out DIR]

`build` walks the blueprints exported with their script bytecode (store
reference/game-files/<build>/ability-states, game-extract `sets --only ability-states
--script --sounds`) and writes `ability-states-gamedata-<v>.jsonl` (one row per cue),
`ability-states-gamedata-<v>.json` (per ability: its states, each with its sounds,
voice rows, montage notifies and minimap textures; coverage) and a provenance file into
the store's reference/ability-states/. `checks` compares the table with the audio
manifest (ability-audio-ref-0.2.0), the minimap texture inventory
(minimap-texture-inventory-0.1.0) and the domain facts the task names, and writes
`checks-<v>.json`.

The chain each row rests on, all game data:

- key: ShooterGame/Config/DefaultInput.ini maps the input actions Activate_GrenadeAbility,
  Activate_Ability1, Activate_Ability2 and Activate_Ultimate to C, Q, E and X; the agent's
  <Agent>_UIData `Abilities` map names, per ECharacterAbilitySlot (Grenade, Ability1,
  Ability2, Ultimate), the ability's UIData class; the AbilityPrimaryAsset whose `UIData`
  is that class names the `Equippable`. The action name and the slot enum share their
  word (Grenade, Ability1, ...); that pairing is the one step the data states by name only.
- states: the equippable's state components (TimedStateComponent, EquipStateComponent,
  ProjectileThrowStateComponent, RespondToEventStateComponent, ...), merged down the class
  chain (`Super`), and the effects each names in `StateEffects`, `MultiStateEffects` or a
  class-default property (FXC_EquippedSettings); the entities the ability spawns
  (projectiles, game objects, pawns, buffs) and, per entity, each event function's
  reachable bytecode (ubergraph walked from the event's entry offset, both branches,
  latent resumes followed) with the FX controllers, sounds and textures it names.
- sounds: an FX controller's audio components (Comp_FXC_AudioBasic PlayOnStart,
  Comp_FXC_Audio_Loop PlayOnStart/StopEvent, PerspectiveEvents PlayOnStart1P/3PAlly/
  3PEnemy, EffectAudioComponent, ...) with their perspective flags (MuteThirdPerson,
  MuteFirstPerson, bOwnerEffectOnly on the state effect); its montages' Aud_AnimNotify
  events with their times (ability-anims export); each AkAudioEvent's media debug names,
  joined to the manifest's FLACs by file stem.
- icons: minimap components on entities and equippables (IconBrush, EnemyIcon,
  WidgetBrush, Image, Icon) and textures an event's bytecode names (an icon swap on
  deactivation), joined to the exported PNGs.

`phase` is lexical: the first family whose word appears in the state's own data name
(else the effect's, else the event's); `phase_basis` names the word and where. It is a
reading of the designers' names, never an inference across abilities
[domain:abilities/ability-rules-are-unique]; null when no word matches.

`views` (0.2.0) gives each row a value per viewer -- self (the caster), teammate, enemy
and spectator -- true, false or null, with `view_basis`. Views are separate per ability,
and a difference between them is a fact [domain:abilities/views-separate-per-ability].
Sounds take theirs from the mute flags and perspective events; minimap icons from
IconBrush on a spawned entity (the caster's side, the caster's own casts drawn as a
teammate's [domain:minimap/ability-drawing-colour-by-side]) and EnemyIcon; null where the
data names no rule. An entity's GameObjectVisibility.EnemyVisibility is recorded beside
the enemy view, not applied: the data does not define what it does to a minimap. The spectator
view copies the self view [domain:minimap/spectator-view-matches-self] unless a hand
reading of the bytecode (VIEW_READINGS, each cited) decides it apart; checks list every
such case as a disagreement with that belief.

Entities (0.2.0) record how each ability reaches them: `spawns` (SpawnedActors,
ProjectileClass, ActivateActor, StateBuffs, BuffClass, or a character form's starting
equippables) or `names` (anything else: a cast, a tracker, a class property). A character
form is a `*_PC` class outside the agent's root folder that an ability names (Astra's
Rift_TargetingForm_PC); its starting equippables' states join that ability. An entity one
ability spawns and another names is an entity with operations (`entity_operations`).

Wire: no. It builds a reference table from game data; readers that use the table
cite its version, and nothing in reticle/ imports this file.
"""
from __future__ import annotations

import argparse
import collections
import configparser  # noqa: F401  (DefaultInput.ini is read by regex: repeated keys)
import datetime
import glob
import hashlib
import json
import os
import re
import sys
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
try:
    import psutil
    psutil.Process().nice(psutil.BELOW_NORMAL_PRIORITY_CLASS if os.name == "nt" else 10)
except Exception:  # noqa: BLE001
    pass

VERSION = "ability-states-gamedata-0.2.0"
BUILD = "release-13.06-shipping-18-5590001"
STORE = Path("C:/Users/grant/reticle-store")
GX = STORE / "reference" / "game-files" / BUILD
EXP = GX / "ability-states"
ANIMS = GX / "ability-anims"
AUDIO = STORE / "reference" / "game-files" / "audio"
OUT = STORE / "reference" / "ability-states"
TEXTURE_SETS = ["minimap", "minimap-abilities", "killfeed-icons", "ability-state-textures"]

FIRST_AGENTS = ["Sova", "Skye", "Phoenix", "Clove", "Iso", "Omen", "Deadlock", "Killjoy", "Cypher"]
SLOT_ACTION = {"Grenade": "Activate_GrenadeAbility", "Ability1": "Activate_Ability1",
               "Ability2": "Activate_Ability2", "Ultimate": "Activate_Ultimate"}

#: Phase families and the words that name them in the designers' asset names. Order is priority:
#: "Unequip" must match before "Equip"; "RevealExpire" reads as an end, not an activation.
PHASES = [
    ("refused", ["fail", "failed", "rejected", "reject", "cantuse", "denied"]),
    ("unequip", ["unequip", "holster", "cancelunequip", "timeoutunequip"]),
    ("equip", ["equip", "equipped", "readying", "ready", "pullout"]),
    ("cancel", ["cancel"]),
    ("charge", ["charge", "charging", "windup", "chargeup", "focus"]),
    ("targeting", ["targeting", "placement", "aim", "preview", "select"]),
    ("cast", ["cast", "fire", "firing", "throw", "launch", "shoot", "release", "deploy", "place",
              "spawn", "consume", "use"]),
    ("travel", ["projectile", "missile", "flight", "fly", "inair", "travel", "moving", "move", "trail", "whoosh"]),
    ("bounce", ["bounce", "ricochet"]),
    ("impact", ["impact", "hit", "land", "landed", "stick", "attach"]),
    ("detonate", ["explode", "explosion", "detonate", "detonation", "blast", "burst", "pop"]),
    ("destroyed", ["destroy", "destroyed", "death", "die", "dies", "dead", "killed", "broken", "break"]),
    ("end", ["end", "expire", "expired", "complete", "completed", "fade", "fadeout", "outro", "timeout",
             "dissipate", "deactivate", "deactivated", "inactive", "finish", "off", "warn", "warning"]),
    ("activate", ["activate", "activated", "activation", "trigger", "triggered", "arm", "armed", "pulse",
                  "reveal", "revealed", "scan", "detect", "detected", "flash", "blind"]),
    ("loop", ["loop", "active", "idle", "sustain", "ongoing", "channel", "lingering", "persist", "ambient"]),
    ("recall", ["recall", "recalled", "pickup", "retrieve", "return"]),
    ("possess", ["possess", "possessed", "possessing", "unpossess", "control", "pilot"]),
]
PHASE_OF = {w: fam for fam, ws in PHASES for w in ws}


# --------------------------------------------------------------------------- loading


_cache: dict[str, list | None] = {}


def gpath(objpath: str) -> str:
    """/Game/X/Y.4 or /Game/X/Y.Y_C -> /Game/X/Y (the package)."""
    p = objpath.split(":")[0]
    head, _, tail = p.rpartition("/")
    return head + "/" + tail.split(".")[0]


def pkg_file(pkg: str, root: Path = EXP) -> Path:
    assert pkg.startswith("/Game/"), pkg
    return root / "ShooterGame" / "Content" / (pkg[len("/Game/"):] + ".json")


def load(pkg: str, root: Path = EXP):
    key = f"{root}|{pkg}"
    if key not in _cache:
        f = pkg_file(pkg, root)
        if f.exists():
            _cache[key] = json.load(open(f, encoding="utf-8"))
        elif Path(str(f) + ".gz").exists():
            import gzip
            _cache[key] = json.load(gzip.open(str(f) + ".gz", "rt", encoding="utf-8"))
        else:
            _cache[key] = None
    return _cache[key]


def rel(pkg: str, root: Path = EXP) -> str:
    """The store-relative file a row rests on."""
    return str(pkg_file(pkg, root).relative_to(STORE)).replace("\\", "/")


def walk_refs(x, out: set):
    """Every /Game/ object path a JSON value names."""
    if isinstance(x, dict):
        for k, v in x.items():
            if k in ("ObjectPath", "AssetPathName") and isinstance(v, str) and v.startswith("/Game/"):
                out.add(v)
            else:
                walk_refs(v, out)
    elif isinstance(x, list):
        for v in x:
            walk_refs(v, out)
    return out


def obj_class(name: str | None) -> str | None:
    """"AkAudioEvent'Play_X'" -> AkAudioEvent."""
    if not name:
        return None
    m = re.match(r"([A-Za-z0-9_]+)'", name)
    return m.group(1) if m else None


def walk_named(x, out: list, cls: str | None = None):
    """(class, object path) for every object reference a JSON value holds."""
    if isinstance(x, dict):
        if "ObjectPath" in x and isinstance(x.get("ObjectPath"), str) and x["ObjectPath"].startswith("/Game/"):
            out.append((obj_class(x.get("ObjectName")), x["ObjectPath"]))
        if "AssetPathName" in x and isinstance(x.get("AssetPathName"), str) and x["AssetPathName"].startswith("/Game/"):
            out.append((None, x["AssetPathName"]))
        for v in x.values():
            walk_named(v, out)
    elif isinstance(x, list):
        for v in x:
            walk_named(v, out)
    return out


def ref_kind(cls: str | None, path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    if cls == "AkAudioEvent" or "/WwiseAudio/Events/" in path:
        return "sound"
    if cls in ("Texture2D",) or re.search(r"/TX_|/T_UI|Minimap", base):
        if cls in (None, "Texture2D"):
            return "texture"
    if cls == "AnimMontage" or base.endswith("_Montage") or "_Montage." in base:
        return "montage"
    if base.startswith("FXC_"):
        return "fxc"
    if cls in ("MaterialInstanceConstant", "Material"):
        return "material"
    return "other"


class BP:
    """One blueprint package: its class, class-default object, components and functions."""

    def __init__(self, pkg: str):
        self.pkg = pkg
        self.ex = load(pkg) or []
        self.bpgc = next((e for e in self.ex if e.get("Type") in ("BlueprintGeneratedClass",
                                                                  "WidgetBlueprintGeneratedClass")), None)
        self.cdo = next((e for e in self.ex if e.get("Name", "").startswith("Default__")), None)
        sup = (self.bpgc or {}).get("Super") or {}
        self.super = gpath(sup["ObjectPath"]) if str(sup.get("ObjectPath", "")).startswith("/Game/") else None
        self.super_native = None if self.super else sup.get("ObjectName")
        self.functions = {e["Name"]: e for e in self.ex if e.get("Type") == "Function"}

    @property
    def ok(self) -> bool:
        return self.bpgc is not None

    def components(self) -> dict[str, dict]:
        """Component templates and default subobjects, by variable name."""
        out = {}
        skip = {"Function", "SCS_Node", "SimpleConstructionScript", "InheritableComponentHandler",
                "ComponentDelegateBinding", "BlueprintGeneratedClass", "WidgetBlueprintGeneratedClass",
                "UserDefinedEnum", "TimelineTemplate"}
        for i, e in enumerate(self.ex):
            if e.get("Type") in skip or e is self.cdo or "Outer" not in e:
                continue
            outer = e["Outer"].get("ObjectName", "")
            # direct children of the class (templates) or of the class-default object (default subobjects)
            if not (outer.startswith("BlueprintGeneratedClass'") or outer.startswith("WidgetBlueprintGeneratedClass'")
                    or "'Default__" in outer):
                continue
            if outer.count(":") or outer.count("."):
                # a subobject of a component (e.g. a component's own random number generator)
                if "'Default__" in outer and ":" in outer.split("'Default__", 1)[1]:
                    continue
            key = e["Name"].replace("_GEN_VARIABLE", "")
            m = re.match(r"(?:Widget)?BlueprintGeneratedClass'(/Game/[^'.]+)", e.get("Class") or "")
            out[key] = {"type": e["Type"], "props": e.get("Properties") or {}, "index": i, "name": e["Name"],
                        "class_path": m.group(1) if m else None}
        return out


_bp: dict[str, BP] = {}


def bp(pkg: str) -> BP:
    if pkg not in _bp:
        _bp[pkg] = BP(pkg)
    return _bp[pkg]


def class_chain(pkg: str, limit: int = 12) -> list[BP]:
    out, seen = [], set()
    while pkg and pkg not in seen and len(out) < limit:
        seen.add(pkg)
        b = bp(pkg)
        if not b.ok:
            break
        out.append(b)
        pkg = b.super
    return out


def merged_components(pkg: str) -> dict[str, dict]:
    """Components down the class chain; a property absent in a child's template comes from its parent's."""
    merged: dict[str, dict] = {}
    for b in class_chain(pkg):
        for key, c in b.components().items():
            if key not in merged:
                merged[key] = {"type": c["type"], "props": dict(c["props"]), "defined_in": [b.pkg],
                               "export": f"{rel(b.pkg)}#{c['name']}", "class_path": c.get("class_path")}
            else:
                m = merged[key]
                m["defined_in"].append(b.pkg)
                for k, v in c["props"].items():
                    m["props"].setdefault(k, v)
    return merged


def merged_cdo(pkg: str) -> tuple[dict, dict]:
    props, where = {}, {}
    for b in class_chain(pkg):
        for k, v in ((b.cdo or {}).get("Properties") or {}).items():
            if k not in props:
                props[k] = v
                where[k] = f"{rel(b.pkg)}#{(b.cdo or {}).get('Name')}"
    return props, where


# --------------------------------------------------------------------------- bytecode


#: Bytecode keys whose object is a type, not a thing the event uses: the class a cast tests
#: (`InterfaceClass`, `ClassPtr`), a variable's owner and declared type, a struct's type.
TYPE_ONLY_KEYS = {"Owner", "InterfaceClass", "ClassPtr", "Property", "PropertyClass", "MetaClass", "Struct"}


def _stmt_refs(st, refs: list, binds: set, latent: set, calls: set, uber: str, pkg: str):
    def rec(x):
        if isinstance(x, dict):
            tok = x.get("Token")
            if tok == "EX_BindDelegate" and x.get("FunctionName"):
                binds.add(x["FunctionName"])
            if tok == "EX_StructConst" and "LatentActionInfo" in str((x.get("Struct") or {}).get("ObjectName")):
                ps = x.get("Properties") or []
                if len(ps) >= 3 and ps[2].get("Value") == uber and ps[0].get("Token") == "EX_SkipOffsetConst":
                    latent.add(int(ps[0]["Value"]))
            if tok in ("EX_LocalVirtualFunction", "EX_LocalFinalFunction", "EX_FinalFunction", "EX_VirtualFunction"):
                fn = x.get("Function") or {}
                if isinstance(fn, str):  # a virtual call by name
                    calls.add(fn)
                    fn = {}
                on = fn.get("ObjectName", "")
                op = fn.get("ObjectPath", "")
                m = re.search(r":([^']+)'", on)
                if m and op.startswith(pkg + "."):
                    calls.add(m.group(1))
                elif tok in ("EX_LocalVirtualFunction", "EX_VirtualFunction") and isinstance(x.get("VirtualFunctionName"), str):
                    calls.add(x["VirtualFunctionName"])
            if "ObjectPath" in x and isinstance(x["ObjectPath"], str) and x["ObjectPath"].startswith("/Game/") \
                    and not x["ObjectPath"].startswith(pkg + ".") and not x["ObjectPath"].startswith(pkg + ":"):
                refs.append((obj_class(x.get("ObjectName")), x["ObjectPath"]))
            for k, v in x.items():
                if k not in TYPE_ONLY_KEYS:
                    rec(v)
        elif isinstance(x, list):
            for v in x:
                rec(v)
    rec(st)


class Graph:
    """Per event function of one blueprint: the refs its reachable bytecode names."""

    def __init__(self, b: BP):
        self.b = b
        self.uber = next((n for n in b.functions if n.startswith("ExecuteUbergraph")), None)
        self.stmts = {}
        if self.uber:
            for st in b.functions[self.uber].get("ScriptBytecode") or []:
                if "StatementIndex" in st:
                    self.stmts[st["StatementIndex"]] = st
        self.offsets = sorted(self.stmts)

    def _next(self, off: int):
        import bisect
        i = bisect.bisect_right(self.offsets, off)
        return self.offsets[i] if i < len(self.offsets) else None

    def walk_uber(self, entry: int):
        refs, binds, calls = [], set(), set()
        seen, stack = set(), [entry]
        while stack:
            off = stack.pop()
            while off is not None and off not in seen:
                seen.add(off)
                st = self.stmts.get(off)
                if st is None:
                    break
                latent = set()
                _stmt_refs(st, refs, binds, latent, calls, self.uber, self.b.pkg)
                stack.extend(latent)
                tok = st.get("Token")
                if tok == "EX_Jump":
                    stack.append(st["CodeOffset"])
                    break
                if tok == "EX_JumpIfNot":
                    stack.append(st["CodeOffset"])
                elif tok == "EX_PushExecutionFlow":
                    stack.append(st["PushingAddress"])
                elif tok in ("EX_PopExecutionFlow", "EX_Return", "EX_EndOfScript", "EX_ComputedJump"):
                    break
                off = self._next(off)
        return refs, binds, calls

    def function(self, name: str, depth: int = 0, stack: tuple = ()):
        """refs, binds, calls of a function, its ubergraph entry and the local functions it calls."""
        f = self.b.functions.get(name)
        if f is None or name in stack or depth > 6:
            return [], set(), set()
        refs, binds, calls = [], set(), set()
        for st in f.get("ScriptBytecode") or []:
            lat = set()
            _stmt_refs(st, refs, binds, lat, calls, self.uber or "", self.b.pkg)
            if st.get("Token") == "EX_LocalFinalFunction" and self.uber and \
                    str((st.get("Function") or {}).get("ObjectName", "")).endswith(f":{self.uber}'"):
                ps = st.get("Parameters") or []
                if ps and ps[0].get("Token") == "EX_IntConst":
                    r2, b2, c2 = self.walk_uber(int(ps[0]["Value"]))
                    refs += r2
                    binds |= b2
                    calls |= c2
        for c in sorted(calls - {self.uber, name}):
            if c in self.b.functions:
                r2, b2, _ = self.function(c, depth + 1, stack + (name,))
                refs += r2
                binds |= b2
        return refs, binds, calls

    def events(self) -> dict[str, dict]:
        out = {}
        for name in self.b.functions:
            if name == self.uber:
                continue
            refs, binds, calls = self.function(name)
            if refs or binds:
                out[name] = {"refs": refs, "binds": sorted(binds), "calls": sorted(c for c in calls if c != self.uber)}
        return out


# --------------------------------------------------------------------------- phases


def words(name: str) -> list[str]:
    s = re.sub(r"([a-z])([A-Z])", r"\1 \2", name.replace("_GEN_VARIABLE", ""))
    s = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", s)
    return [w.lower() for w in re.split(r"[^A-Za-z0-9]+", s) if w]


def phase_of(*named: tuple[str, str]) -> tuple[str | None, str | None]:
    """(family, basis) from the first named thing whose words include a family word."""
    for where, name in named:
        if not name:
            continue
        ws = words(re.sub(r"^(Play|Stop)_", "", name))
        joined = "".join(ws)
        for whole in (True, False):  # a whole word anywhere beats a fragment inside a compound
            for fam, vocab in PHASES:
                for w in vocab:
                    if (w in ws) if whole else (len(w) >= 6 and w in joined):
                        return fam, f"{where}:{name}~{w}"
    return None, None


def name_perspective(event: str) -> str | None:
    """The perspective an event's own name states (_1P, _3P), for comparison with the data's flags."""
    m = re.search(r"(?:^|_)(1P|3P|FP|TP)(?:_|$)", event.rsplit("/", 1)[-1], re.I)
    return {"1P": "1P", "FP": "1P", "3P": "3P", "TP": "3P"}.get(m.group(1).upper()) if m else None


# --------------------------------------------------------------------------- sounds and media


def manifest_index():
    rows = [json.loads(l) for l in open(AUDIO / "manifest-0.2.0.jsonl", encoding="utf-8")]
    by_stem = collections.defaultdict(list)
    for r in rows:
        for sp in [r["source_path"]] + list(r.get("also_source_paths") or []):
            st = re.sub(r" \((?:SFX|\d+)\)$", "", Path(sp).stem).lower()
            by_stem[st].append(r)
    return rows, by_stem


def event_media(evpath: str) -> dict:
    pkg = gpath(evpath)
    ex = load(pkg)
    if not ex:
        return {"event": pkg, "exported": False, "media": []}
    media = []
    for e in ex:
        for lm in (e.get("EventCookedData") or {}).get("EventLanguageMap", []):
            v = lm.get("Value") or {}
            for m in v.get("Media") or []:
                media.append(m.get("DebugName"))
            for leaf in v.get("SwitchContainerLeaves") or []:
                for m in (leaf.get("Media") or []):
                    media.append(m.get("DebugName"))
    return {"event": pkg, "exported": True, "media": sorted({m for m in media if m})}


def montage_notifies(mpath: str) -> dict:
    pkg = gpath(mpath)
    ex = load(pkg)
    if ex is None:
        ex = load(pkg, ANIMS)
    if ex is None:
        return {"montage": pkg, "exported": False, "notifies": []}
    by_path = {}
    for i, e in enumerate(ex):
        by_path[f"{pkg}.{i}"] = e
    out = []
    root = ex[0] if ex else {}
    for n in ((root.get("Properties") or {}).get("Notifies") or []):
        ref = (n.get("Notify") or {}).get("ObjectPath") or ""
        e = by_path.get(ref)
        if not e:
            continue
        ev = ((e.get("Properties") or {}).get("Event") or {})
        evs = []
        for k, v in (e.get("Properties") or {}).items():
            if isinstance(v, dict) and str(v.get("ObjectPath", "")).find("/WwiseAudio/Events/") >= 0:
                evs.append(v["ObjectPath"])
        if ev and ev.get("ObjectPath") and ev["ObjectPath"] not in evs:
            evs.append(ev["ObjectPath"])
        for evp in evs:
            out.append({"event": gpath(evp), "t_s": round(float(n.get("LinkValue") or 0.0), 4),
                        "notify": e.get("Type")})
    return {"montage": pkg, "exported": True, "notifies": out,
            "length_s": (root.get("Properties") or {}).get("SequenceLength")}


AUDIO_PROP_PERSPECTIVE = {"PlayOnStart1P": "1P", "PlayOnStart3PAlly": "3P-ally", "PlayOnStart3PEnemy": "3P-enemy"}
MONTAGE_PROP_PERSPECTIVE = {"1P_Animation": "1P", "1P_Overlay_Animation": "1P", "1P_Cosmetic_Animation": "1P",
                            "3P_Animation": "3P", "3P_Cosmetic_Animation": "3P", "3P Montage": "3P"}


def comp_defaults(ctype_path: str | None) -> dict:
    """Class-default properties of a blueprint component class (e.g. Comp_FXC_AudioBasic), if exported."""
    if not ctype_path or not ctype_path.startswith("/Game/"):
        return {}
    p, _ = merged_cdo(gpath(ctype_path))
    return p


def fxc_cues(fxc_pkg: str, seen: set | None = None) -> list[dict]:
    """The cues one FX controller plays: sounds (with perspective), montage notifies, voice rows, textures."""
    seen = seen if seen is not None else set()
    if fxc_pkg in seen:
        return []
    seen.add(fxc_pkg)
    cues = []
    comps = merged_components(fxc_pkg)
    b = bp(fxc_pkg)
    if not b.ok:
        return [{"cue_type": "missing_fxc", "cue": fxc_pkg, "via": "not exported", "rests_on": [rel(fxc_pkg)]}]
    for key, c in comps.items():
        props = c["props"]
        ctype = c["type"]
        cls_path = None
        e = bp(c["defined_in"][0]).ex[0] if False else None  # noqa: F841
        # the component class path, for defaults
        for bb in class_chain(fxc_pkg):
            for ee in bb.ex:
                if ee.get("Name") == key + "_GEN_VARIABLE" or ee.get("Name") == key:
                    m = re.match(r"BlueprintGeneratedClass'(/Game/[^']+)'", ee.get("Class", ""))
                    if m:
                        cls_path = m.group(1)
                    break
            if cls_path:
                break
        defaults = comp_defaults(cls_path)
        flags = {k: props.get(k, defaults.get(k)) for k in
                 ("MuteThirdPerson", "MuteFirstPerson", "bBypassThirdPerson", "PlayWithAlliance", "MuteContext",
                  "bEnablePerspectiveCheck", "EnemyParticles", "bShowIn1P", "bShowIn3P")
                 if k in props or k in defaults}
        where = f"{c['export']}"
        for pname, v in props.items():
            named = walk_named(v, [])
            for cls, path in named:
                kind = ref_kind(cls, path)
                if kind == "sound":
                    persp = AUDIO_PROP_PERSPECTIVE.get(pname)
                    if persp is None:
                        if flags.get("MuteThirdPerson") is True and flags.get("MuteFirstPerson") is not True:
                            persp = "1P"
                        elif flags.get("MuteFirstPerson") is True and flags.get("MuteThirdPerson") is not True:
                            persp = "3P"
                        elif flags.get("bBypassThirdPerson") is True:
                            persp = "1P?"
                        elif flags.get("MuteThirdPerson") is not True and flags.get("MuteFirstPerson") is not True:
                            # no mute flag: the component plays for every listener; Wwise picks the
                            # media by its perspective switch, which the cooked event does not expose
                            persp = "unmuted"
                    role = "stop" if re.search(r"Stop|Unequip", pname) else "play"
                    cues.append({"cue_type": "sound", "cue": gpath(path), "via": f"{ctype}.{pname}",
                                 "sound_role": role, "perspective": persp,
                                 "perspective_basis": (f"{ctype}.{pname}" if pname in AUDIO_PROP_PERSPECTIVE else
                                                       ", ".join(f"{k}={flags[k]}" for k in flags) or None),
                                 "team": ("ally" if pname == "PlayOnStart3PAlly" else "enemy" if pname == "PlayOnStart3PEnemy"
                                          else ("alliance:" + str(flags.get("PlayWithAlliance"))) if "PlayWithAlliance" in flags else None),
                                 "rests_on": [where]})
                elif kind == "montage":
                    persp = MONTAGE_PROP_PERSPECTIVE.get(pname)
                    mn = montage_notifies(path)
                    if not mn["notifies"]:
                        cues.append({"cue_type": "montage_no_sound" if mn["exported"] else "montage_not_exported",
                                     "cue": mn["montage"], "via": f"{ctype}.{pname}", "perspective": persp,
                                     "rests_on": [where]})
                    for n in mn["notifies"]:
                        cues.append({"cue_type": "sound", "cue": n["event"], "via": f"{ctype}.{pname} -> {mn['montage'].rsplit('/', 1)[-1]} @ {n['t_s']} s",
                                     "sound_role": "play", "perspective": persp, "perspective_basis": f"{ctype}.{pname}",
                                     "montage": mn["montage"], "montage_t_s": n["t_s"],
                                     "rests_on": [where, rel(mn["montage"], EXP if load(mn["montage"]) else ANIMS)]})
                elif kind == "texture":
                    cues.append({"cue_type": "texture", "cue": gpath(path), "via": f"{ctype}.{pname}", "rests_on": [where]})
                elif kind == "fxc" and gpath(path) != fxc_pkg:
                    for cc in fxc_cues(gpath(path), seen):
                        cc = dict(cc)
                        cc["via"] = f"{ctype}.{pname} -> {gpath(path).rsplit('/', 1)[-1]} :: " + cc["via"]
                        cc["rests_on"] = [where] + cc["rests_on"]
                        cues.append(cc)
            if ctype == "EffectAbilityVOComponent" and pname == "Line":
                row = (v or {}).get("RowName")
                dt = ((v or {}).get("DataTable") or {}).get("ObjectPath")
                cues.append({"cue_type": "vo_row", "cue": f"{gpath(dt) if dt else None}:{row}", "via": f"{ctype}.Line",
                             "rests_on": [where]})
    # the FX controller's own functions (StartEffect, StopEffect, ...): sounds and textures their bytecode names
    for bb in class_chain(fxc_pkg):
        g = Graph(bb)
        for ev, info in g.events().items():
            for cls, path in info["refs"]:
                kind = ref_kind(cls, path)
                if kind in ("sound", "texture"):
                    cues.append({"cue_type": kind, "cue": gpath(path), "via": f"bytecode {ev}",
                                 "sound_role": ("stop" if "Stop" in ev else "play") if kind == "sound" else None,
                                 "fxc_function": ev, "rests_on": [f"{rel(bb.pkg)}#{ev}"]})
                elif kind == "fxc" and gpath(path) != fxc_pkg:
                    for cc in fxc_cues(gpath(path), seen):
                        cc = dict(cc)
                        cc["via"] = f"bytecode {ev} -> {gpath(path).rsplit('/', 1)[-1]} :: " + cc["via"]
                        cc["rests_on"] = [f"{rel(bb.pkg)}#{ev}"] + cc["rests_on"]
                        cues.append(cc)
    # dedupe
    out, keys = [], set()
    for c in cues:
        k = (c["cue_type"], c["cue"], c["via"], c.get("perspective"))
        if k not in keys:
            keys.add(k)
            out.append(c)
    return out


# --------------------------------------------------------------------------- kit


def default_keys() -> dict:
    f = EXP / "ShooterGame" / "Config" / "DefaultInput.ini"
    keys = {}
    for line in open(f, encoding="utf-8", errors="replace"):
        m = re.match(r'\+ActionMappings=\(ActionName="(Activate_[A-Za-z0-9]+)".*?,Key=([A-Za-z0-9_]+)\)', line.strip())
        if m and not m.group(2).startswith("Gamepad"):
            keys.setdefault(m.group(1), m.group(2))
    return keys


def codenames() -> dict:
    d = json.load(open(AUDIO / "codenames.json", encoding="utf-8"))["event_folders"]
    out = {}
    for code, v in d.items():
        folder = v["asset_path"].split("/")[3]
        out[v["display_name"]] = {"codename": code, "folder": folder, "own": sorted(set(v.get("own_char_folders") or []) | {folder})}
    return out


def kit(agent: str, cn: dict, keys: dict) -> list[dict]:
    folder = cn[agent]["folder"]
    ui_pkg = f"/Game/Characters/{folder}/{folder}_UIData"
    ex = load(ui_pkg)
    if not ex:
        cands = glob.glob(str(EXP / "ShooterGame/Content/Characters" / folder / "*_UIData.json"))
        if not cands:
            return []
        ui_pkg = "/Game/Characters/" + folder + "/" + Path(cands[0]).stem
        ex = load(ui_pkg)
    abil = None
    for e in ex:
        a = (e.get("Properties") or {}).get("Abilities")
        if a:
            abil = a
            break
    # ability primary assets of this agent: UIData class -> equippable
    pa = {}
    for f in glob.glob(str(EXP / "ShooterGame/Content/Characters" / folder / "**" / "AbilityPrimaryAsset_*.json"), recursive=True):
        for e in json.load(open(f, encoding="utf-8")):
            p = e.get("Properties") or {}
            if "Equippable" in p and "UIData" in p:
                pa[gpath(p["UIData"]["AssetPathName"])] = {"equippable": gpath(p["Equippable"]["AssetPathName"]),
                                                          "asset": rel("/Game/" + str(Path(f).relative_to(EXP / "ShooterGame/Content")).replace("\\", "/")[:-5])}
    out = []
    for item in abil or []:
        slot = item["Key"].split("::")[-1]
        on = item["Value"]["ObjectName"]
        m = re.match(r"([A-Za-z0-9_]+)_C'", on)
        uicls = m.group(1) if m else None
        # the UIData subobject's own properties (display name, icon) live in the agent UIData package
        idx = int(item["Value"]["ObjectPath"].rsplit(".", 1)[1])
        sub = ex[idx] if idx < len(ex) else {}
        uip = None
        for f in glob.glob(str(EXP / "ShooterGame/Content/Characters" / folder / "**" / f"{uicls}.json"), recursive=True):
            uip = "/Game/" + str(Path(f).relative_to(EXP / "ShooterGame/Content")).replace("\\", "/")[:-5]
        props, _ = merged_cdo(uip) if uip else ({}, {})
        sp = sub.get("Properties") or {}
        name = ((sp.get("DisplayName") or props.get("DisplayName") or {}).get("LocalizedString"))
        icon = ((sp.get("DisplayIcon") or props.get("DisplayIcon") or {}).get("ObjectPath"))
        eq = pa.get(uip or "", {})
        action = SLOT_ACTION.get(slot)
        out.append({"agent": agent, "codename": cn[agent]["codename"], "slot_enum": slot,
                    "key": keys.get(action) if action else None,
                    "key_basis": (f"DefaultInput.ini {action} Key={keys.get(action)}; {rel(ui_pkg)} Abilities "
                                  f"ECharacterAbilitySlot::{slot}") if action else f"{rel(ui_pkg)} Abilities ECharacterAbilitySlot::{slot} (no input action)",
                    "ability": name, "uidata": uip, "display_icon": gpath(icon) if icon else None,
                    "equippable": eq.get("equippable"), "primary_asset": eq.get("asset"),
                    "ability_folder": (uip or "").split("/")[5] if uip and len((uip or "").split("/")) > 5 else None})
    return out


def variant_equippables(agent: str, cn: dict, kit_eqs: set) -> tuple[list[dict], list[dict]]:
    """Equippables an agent's character classes start with beyond the UIData kit, keyed by their own
    EquippableSlot (class default, down the class chain); those without a slot are listed unassigned."""
    folder = cn[agent]["folder"]
    out, unassigned = [], []
    for f in sorted(glob.glob(str(EXP / "ShooterGame/Content/Characters" / folder / "*_PC.json"))):
        pc = "/Game/Characters/" + folder + "/" + Path(f).stem
        props, _w = merged_cdo(pc)
        for cls, path in walk_named(props.get("StartingEquippableClasses"), []):
            eq = gpath(path)
            if eq in kit_eqs:
                continue
            slot = merged_cdo(eq)[0].get("EquippableSlot")
            item = {"equippable": eq, "character": pc, "equippable_slot": slot,
                    "basis": f"{rel(pc)} StartingEquippableClasses; {rel(eq)} EquippableSlot={slot}"}
            (out if SLOT_OF_ITEM.get(slot or "") else unassigned).append(item)
    return out, unassigned


SLOT_OF_ITEM = {"EAresItemSlot::GrenadeAbility": "Grenade", "EAresItemSlot::Ability1": "Ability1",
                "EAresItemSlot::Ability2": "Ability2", "EAresItemSlot::Ultimate": "Ultimate"}


# --------------------------------------------------------------------------- per ability


ENTITY_RE = re.compile(r"^(Projectile|GameObject|Pawn|Buff|StateComp|StateComponent|Comp|Character|Ability|"
                       r"Gameobject|Deployable|Actor|Turret|Wall|Smoke|Bot|Drone|Patch|Zone|Area|Placed|Spawn|"
                       r"Decoy|Trap|Mine|Grenade|Orb|Barrier|Seeker|Missile|Effect|Puddle)", re.I)


def is_entity_pkg(pkg: str, own: list[str]) -> bool:
    parts = pkg.split("/")
    if len(parts) < 4 or parts[2] != "Characters" or parts[3] not in own:
        return False
    base = parts[-1]
    if re.search(r"_PC(_|$)", base) or base.endswith("_Character"):
        return False  # the agent's own character class (a cast target, an owner type)
    if base.startswith(("FXC_", "UIData", "AbilityPrimaryAsset", "AbilityTuning", "DataTable", "Enum",
                        "FloatCurve", "Curve", "Struct", "ForceModule", "AbilityUIData")):
        return False
    ex = load(pkg)
    if not ex:
        return False
    return any(e.get("Type") == "BlueprintGeneratedClass" for e in ex)


def tuning(value, tags: set, entities: list):
    """Classes an AbilityTuning table hands the ability (spawned objects), and the table's tags."""
    for cls, path in walk_named(value, []):
        if cls == "DataTable" and gpath(path).rsplit("/", 1)[-1].startswith("AbilityTuning"):
            for e in load(gpath(path)) or []:
                for row in (e.get("Rows") or {}).values():
                    tags.add(((row.get("AbilityTuningTag") or {}).get("TagName")) or "")
                    for _c, p2 in walk_named(row.get("Value"), []):
                        entities.append(gpath(p2))


#: Properties that name a class to filter by (what this actor may use, ignore or hit), not one it spawns.
FILTER_PROP = re.compile(r"Filter|IncludedClasses|ExcludedClasses|Ignore|Allowed|Blocked|Valid.*Class")
#: Properties whose classes the owner creates (an actor, a projectile, a buff on someone); any other
#: class reference only names its class (a cast target, a tracker, a filter, a damage type).
SPAWN_PROPS = {"ProjectileClass", "SpawnedActors", "ActivateActor", "StateBuffs", "BuffClass"}
SPAWN_PROP_RE = re.compile(r"^Spawned\w*Class$|^\w*ClassToSpawn$|^SpawnClass$")


def is_spawn_prop(pname: str) -> bool:
    return pname in SPAWN_PROPS or bool(SPAWN_PROP_RE.match(pname))

#: Minimap component settings carried beside each icon row (who sees it, whether it turns or moves).
MINIMAP_PROPS = ("Visibility", "StartActive", "bRotates", "RotationSpace", "SizeSpace", "bMoves", "bEnemiesNeedLoS",
                 "EnemyVisibility", "AllyVisibility", "Size")


ICON_PREFIXES = ("minimap_", "inworld_", "icon_")


def surface_of(ctype: str) -> str:
    """Where a component draws its texture: the minimap, the in-world (3D HUD) icon, or elsewhere."""
    if "Minimap" in ctype:
        return "minimap"
    if "InWorldIcon" in ctype:
        return "inworld"
    return "icon"


def icon_row(key: str, c: dict, pname: str, path: str, owner: str, owner_kind: str) -> dict:
    props = c["props"]
    return {"state": key, "state_kind": c["type"], "owner": owner, "owner_kind": owner_kind,
            "cue_type": f"{surface_of(c['type'])}_{pname}", "cue": gpath(path), "via": f"{c['type']}.{pname}",
            "minimap_props": {k: props[k] for k in MINIMAP_PROPS if k in props} or None,
            "rests_on": [c["export"]]}


STATE_PROPS = ("TimerLength", "UnequipBehavior", "bAutoAddToStateMachine", "TransitionToNextStateOnProjectileStopped",
               "bShouldReportAbilityCast", "TriggerEventInputs", "DrainPerSecond", "MaxDamage", "bEquippableUsedState")


def state_rows(ab: dict, eq_pkg: str) -> tuple[list[dict], list[str], dict]:
    """The equippable's states and the cues of each; the entity classes it spawns or names."""
    rows, entities = [], []
    spawned = set()
    tuning_tags = set()
    comps = merged_components(eq_pkg)
    cdo, cdo_where = merged_cdo(eq_pkg)
    machine_effects = {}
    for key, c in comps.items():
        if c["type"] == "EquippableStateMachineComponent":
            for item in c["props"].get("MultiStateEffects") or []:
                et = (((item.get("Value") or {}).get("EffectInfo") or {}).get("Effect") or {}).get("EffectType") or {}
                if et.get("ObjectPath"):
                    machine_effects[item.get("Key")] = gpath(et["ObjectPath"])
    order = 0
    states = {}
    for key, c in comps.items():
        props = c["props"]
        is_state = ("State" in c["type"] and c["type"] != "EquippableStateMachineComponent") or \
            any(k in props for k in ("StateEffects", "MultiStateEffects", "StateBuffs"))
        if not is_state:
            # minimap components on the equippable (an aim preview or a held icon)
            for pname, v in props.items():
                for cls, path in walk_named(v, []):
                    if ref_kind(cls, path) in ("texture", "material"):
                        rows.append(icon_row(key, c, pname, path, eq_pkg, "equippable"))
            continue
        order += 1
        st = {"state": key, "state_kind": c["type"], "owner": eq_pkg, "owner_kind": "equippable",
              "declared_order": order, "params": {k: props[k] for k in STATE_PROPS if k in props},
              "rests_on": [c["export"]]}
        states[key] = st
        effects = []
        for i, se in enumerate(props.get("StateEffects") or []):
            et = ((se.get("Effect") or {}).get("EffectType") or {}).get("ObjectPath")
            if et:
                effects.append((gpath(et), {k: se.get(k) for k in ("bOwnerEffectOnly", "bStopEffectOnStateEnd",
                                                                   "bStopEffectOnStateInterrupt", "bStopEffectOnUnequip", "Context")},
                                f"StateEffects[{i}]"))
        for i, me in enumerate(props.get("MultiStateEffects") or []):
            nm = me.get("EffectName")
            if nm in machine_effects:
                effects.append((machine_effects[nm], {"multi_state_effect": nm}, f"MultiStateEffects[{i}]={nm}"))
        for pname in ("StateBuffs",):
            for i, sb in enumerate(props.get(pname) or []):
                bc = (sb.get("BuffClass") or {}).get("ObjectPath")
                if bc:
                    entities.append(gpath(bc))
                    spawned.add(gpath(bc))
        for pname in ("ProjectileClass", "SpawnedActors", "BuffClass", "Module", "SpawnTestClass", "ActivateActor"):
            for cls, path in walk_named(props.get(pname), []):
                entities.append(gpath(path))
                if pname in SPAWN_PROPS:
                    spawned.add(gpath(path))
        for fx, flags, where in effects:
            for cue in fxc_cues(fx):
                r = dict(st)
                r.update(cue)
                r["effect"] = fx
                r["effect_flags"] = flags
                if cue.get("perspective") in (None, "unmuted") and cue["cue_type"] == "sound" and flags.get("bOwnerEffectOnly") is True:
                    r["perspective"] = "1P"
                    r["perspective_basis"] = f"{key}.{where}.bOwnerEffectOnly=True"
                r["via"] = f"{key}.{where} -> {fx.rsplit('/', 1)[-1]} :: {cue['via']}"
                r["rests_on"] = st["rests_on"] + [rel(fx)] + cue["rests_on"]
                rows.append(r)
        if not effects:
            r = dict(st)
            r.update({"cue_type": "no_effect", "cue": None, "via": None})
            rows.append(r)
    # class-default properties that name effects (FXC_EquippedSettings, FXC_ID_*)
    for pname, v in cdo.items():
        for cls, path in walk_named(v, []):
            if ref_kind(cls, path) == "fxc":
                fx = gpath(path)
                for cue in fxc_cues(fx):
                    r = {"state": pname, "state_kind": "class_default_property", "owner": eq_pkg, "owner_kind": "equippable"}
                    r.update(cue)
                    r["effect"] = fx
                    r["via"] = f"CDO.{pname} -> {fx.rsplit('/', 1)[-1]} :: {cue['via']}"
                    r["rests_on"] = [cdo_where[pname], rel(fx)] + cue["rests_on"]
                    rows.append(r)
            elif ref_kind(cls, path) == "sound":
                rows.append({"state": pname, "state_kind": "class_default_property", "owner": eq_pkg, "owner_kind": "equippable",
                             "cue_type": "sound", "cue": gpath(path), "via": f"CDO.{pname}", "sound_role": "play",
                             "rests_on": [cdo_where[pname]]})
            elif cls is None or cls in ("BlueprintGeneratedClass",):
                entities.append(gpath(path))
                if is_spawn_prop(pname):
                    spawned.add(gpath(path))
    for c in comps.values():
        tuning(c["props"], tuning_tags, entities)
        if c.get("class_path"):
            # a blueprint component class (a state, a test branch, a handler): its own code may name more
            entities.append(c["class_path"])
    tuning(cdo, tuning_tags, entities)
    states["__equippable_slot__"] = cdo.get("EquippableSlot")
    # the equippable's own event graph
    for b in class_chain(eq_pkg):
        g = Graph(b)
        for ev, info in g.events().items():
            for cls, path in info["refs"]:
                kind = ref_kind(cls, path)
                p = gpath(path)
                if kind == "fxc":
                    for cue in fxc_cues(p):
                        r = {"state": ev, "state_kind": "event_function", "owner": eq_pkg, "owner_kind": "equippable"}
                        r.update(cue)
                        r["effect"] = p
                        r["via"] = f"bytecode {ev} -> {p.rsplit('/', 1)[-1]} :: {cue['via']}"
                        r["rests_on"] = [f"{rel(b.pkg)}#{ev}", rel(p)] + cue["rests_on"]
                        rows.append(r)
                elif kind in ("sound", "texture"):
                    rows.append({"state": ev, "state_kind": "event_function", "owner": eq_pkg, "owner_kind": "equippable",
                                 "cue_type": kind, "cue": p, "via": f"bytecode {ev}", "rests_on": [f"{rel(b.pkg)}#{ev}"]})
                else:
                    entities.append(p)
    states["__tuning_tags__"] = sorted(t for t in tuning_tags if t)
    states["__spawned__"] = spawned
    return rows, entities, states


def entity_rows(ent_pkg: str) -> tuple[list[dict], list[str], set]:
    """The entity's cues, the classes it names, and the subset it spawns (SPAWN_PROPS)."""
    rows, more, spawned = [], [], set()
    comps = merged_components(ent_pkg)
    cdo, cdo_where = merged_cdo(ent_pkg)
    for key, c in comps.items():
        props = c["props"]
        for pname, v in props.items():
            for cls, path in walk_named(v, []):
                kind = ref_kind(cls, path)
                p = gpath(path)
                if kind in ("texture", "material"):
                    rows.append(icon_row(key, c, pname, path, ent_pkg, "entity"))
                elif kind == "fxc":
                    for cue in fxc_cues(p):
                        r = {"state": key, "state_kind": c["type"], "owner": ent_pkg, "owner_kind": "entity"}
                        r.update(cue)
                        r["effect"] = p
                        r["via"] = f"{key}.{pname} -> {p.rsplit('/', 1)[-1]} :: {cue['via']}"
                        r["rests_on"] = [c["export"], rel(p)] + cue["rests_on"]
                        rows.append(r)
                elif kind == "sound":
                    rows.append({"state": key, "state_kind": c["type"], "owner": ent_pkg, "owner_kind": "entity",
                                 "cue_type": "sound", "cue": p, "via": f"{c['type']}.{pname}", "sound_role": "stop" if "Stop" in pname else "play",
                                 "rests_on": [c["export"]]})
                elif cls in (None, "BlueprintGeneratedClass") and not FILTER_PROP.search(pname):
                    more.append(p)
                    if is_spawn_prop(pname):
                        spawned.add(p)
    for pname, v in cdo.items():
        for cls, path in walk_named(v, []):
            kind = ref_kind(cls, path)
            p = gpath(path)
            if kind == "fxc":
                for cue in fxc_cues(p):
                    r = {"state": pname, "state_kind": "class_default_property", "owner": ent_pkg, "owner_kind": "entity"}
                    r.update(cue)
                    r["effect"] = p
                    r["via"] = f"CDO.{pname} -> {p.rsplit('/', 1)[-1]} :: {cue['via']}"
                    r["rests_on"] = [cdo_where[pname], rel(p)] + cue["rests_on"]
                    rows.append(r)
            elif kind in ("sound", "texture"):
                rows.append({"state": pname, "state_kind": "class_default_property", "owner": ent_pkg, "owner_kind": "entity",
                             "cue_type": kind, "cue": p, "via": f"CDO.{pname}", "rests_on": [cdo_where[pname]]})
            elif cls in (None, "BlueprintGeneratedClass") and not FILTER_PROP.search(pname):
                more.append(p)
                if is_spawn_prop(pname):
                    spawned.add(p)
    for b in class_chain(ent_pkg):
        g = Graph(b)
        for ev, info in g.events().items():
            for cls, path in info["refs"]:
                kind = ref_kind(cls, path)
                p = gpath(path)
                if kind == "fxc":
                    for cue in fxc_cues(p):
                        r = {"state": ev, "state_kind": "event_function", "owner": ent_pkg, "owner_kind": "entity",
                             "timer_binds": info["binds"] or None}
                        r.update(cue)
                        r["effect"] = p
                        r["via"] = f"bytecode {ev} -> {p.rsplit('/', 1)[-1]} :: {cue['via']}"
                        r["rests_on"] = [f"{rel(b.pkg)}#{ev}", rel(p)] + cue["rests_on"]
                        rows.append(r)
                elif kind in ("sound", "texture"):
                    rows.append({"state": ev, "state_kind": "event_function", "owner": ent_pkg, "owner_kind": "entity",
                                 "cue_type": kind, "cue": p, "via": f"bytecode {ev}", "rests_on": [f"{rel(b.pkg)}#{ev}"]})
                else:
                    more.append(p)
    return rows, more, spawned


def is_character_form(pkg: str, own: list[str]) -> bool:
    """A `*_PC` class in the agent's own folders but outside its root folder: a body an ability
    spawns and the player drives (Astra's Rift_TargetingForm_PC), not the agent's character."""
    parts = pkg.split("/")
    return (len(parts) > 5 and parts[2] == "Characters" and parts[3] in own
            and bool(re.search(r"_PC$", parts[-1])) and load(pkg) is not None)


def ability_table(ab: dict, own: list[str], other_equippables: set, owners_of: dict | None = None) -> tuple[list[dict], dict]:
    """The ability's rows. `owners_of` (from a first, unconstrained walk of every ability of the agent)
    names, per entity, the abilities it belongs to: those that spawn it, else those that reach it in
    the fewest steps. This walk leaves an entity another ability owns, and records that it named it."""
    owners_of = owners_of or {}
    rows = []
    eq = ab["equippable"]
    if not eq:
        return rows, {"entities": [], "unreached": "no equippable"}
    r0, ents, states = state_rows(ab, eq)
    tags = states.pop("__tuning_tags__", [])
    eslot = states.pop("__equippable_slot__", None)
    sp0 = states.pop("__spawned__", set())
    rows += r0
    seen = {eq} | {b.pkg for b in class_chain(eq)}
    queue = [(e, 1, eq, "spawns" if e in sp0 else "names") for e in ents]
    entity_list, skipped, forms = [], [], []
    while queue:
        p, d, via, how = queue.pop(0)
        if p in seen or d > 5 or p in other_equippables:
            continue
        if is_character_form(p, own):
            # a body the ability spawns: its starting equippables' states belong to this ability
            seen.add(p)
            props, where = merged_cdo(p)
            for _cls, path in walk_named(props.get("StartingEquippableClasses"), []):
                feq = gpath(path)
                if feq in seen or feq in other_equippables:
                    continue
                seen.add(feq)
                fslot = merged_cdo(feq)[0].get("EquippableSlot")
                if SLOT_OF_ITEM.get(fslot or "") and SLOT_OF_ITEM[fslot] != ab.get("slot_enum"):
                    # the form carries another ability's key: that ability, cast from this form
                    forms.append({"form": p, "equippable": feq, "depth": d, "named_by": via, "equippable_slot": fslot,
                                  "belongs_to_slot": SLOT_OF_ITEM[fslot],
                                  "basis": f"{where.get('StartingEquippableClasses', rel(p))} StartingEquippableClasses; "
                                           f"{rel(feq)} EquippableSlot={fslot}"})
                    continue
                fr, fents, fstates = state_rows(ab, feq)
                fsp = fstates.get("__spawned__", set())
                for r in fr:
                    r["character_form"] = p
                    r["form_equippable"] = feq
                    r["rests_on"] = [where.get("StartingEquippableClasses", rel(p))] + r["rests_on"]
                rows += fr
                forms.append({"form": p, "equippable": feq, "depth": d, "named_by": via,
                              "basis": f"{where.get('StartingEquippableClasses', rel(p))} StartingEquippableClasses"})
                queue += [(m, d + 1, feq, "spawns" if m in fsp else "names") for m in fents]
            continue
        if not is_entity_pkg(p, own):
            continue
        seen.add(p)
        if p in owners_of and ab["key"] not in owners_of[p]["keys"]:
            # another ability of this agent owns it (spawns it, or reaches it sooner); this one names it
            skipped.append({"entity": p, "named_by": via, "depth": d, "how": how, "owners": owners_of[p]})
            continue
        entity_list.append({"entity": p, "depth": d, "named_by": via, "how": how})
        r1, more, sp1 = entity_rows(p)
        for r in r1:
            r["entity_depth"] = d
            r["entity_named_by"] = via
        rows += r1
        queue += [(m, d + 1, p, "spawns" if m in sp1 else "names") for m in more]
    for r in rows:
        r.update({k: ab[k] for k in ("agent", "codename", "slot_enum", "key", "ability", "ability_folder", "equippable")})
    letters = sorted({t.split(".")[2] for t in tags if t.count(".") >= 3})
    return rows, {"entities": entity_list, "entities_left_to_other_abilities": skipped, "character_forms": forms,
                  "equippable_slot": eslot, "tuning_tag_letters": letters,
                  "tuning_tag_letter_agrees_with_key": (letters == [ab["key"]]) if letters else None}


# --------------------------------------------------------------------------- textures


def texture_index():
    idx = {}
    for s in TEXTURE_SETS:
        m = GX / s / "manifest.jsonl"
        if not m.exists():
            continue
        for line in open(m, encoding="utf-8"):
            r = json.loads(line)
            if r.get("kind") == "texture" and r.get("status") in ("ok", "dedup"):
                gp = "/Game/" + r["game_path"][len("ShooterGame/Content/"):].rsplit(".", 1)[0]
                idx.setdefault(gp, str((GX / (r.get("dedup_of") or r["output"])).relative_to(STORE)).replace("\\", "/")
                               if r.get("dedup_of") else str((GX / s / r["output"]).relative_to(STORE)).replace("\\", "/")
                               if not (GX / r["output"]).exists() else str((GX / r["output"]).relative_to(STORE)).replace("\\", "/"))
    return idx


# --------------------------------------------------------------------------- views

VIEWS = ("self", "teammate", "enemy", "spectator")
SOUND_VIEWS = {  # perspective -> (self, teammate, enemy)
    "1P": (True, False, False), "3P": (False, True, True), "3P-ally": (False, True, False),
    "3P-enemy": (False, False, True), "unmuted": (True, True, True), "1P?": (True, None, None)}
SPECTATOR_FACT = "minimap/spectator-view-matches-self"

_RIFT = "/Game/Characters/Rift"
_MARKERS = f"{_RIFT}/S0/Ability_X/GameObject_Rift_X_Markers"
_TRACKER = f"{_RIFT}/Global/Comp_Rift_X_RiftTracker"


def _cite(pkg: str, what: str) -> str:
    return f"{rel(pkg)}#{what}"


#: Views the data decides by bytecode read by hand, per (owner, event or component); each cites the
#: statements read. Astra's star selection runs only on Astra's own client: the tracker ticks the
#: selection only when the local controller's PlayerState is Astra's, and the selection is not replicated.
_STAR_SELF_ONLY = {
    "self": True, "teammate": False, "enemy": False, "spectator": False,
    "basis": ("Comp_Rift_X_RiftTracker ReceiveTick selects the best star only when "
              "GetLocalController().PlayerState == PawnPlayerState (statements 2615-2734) and enables its tick only "
              "then (3329-3420); CurrentlySelected and CurrentBestRift carry no Net flag, so no other client "
              "learns which star is selected"),
    "rests_on": [_cite(_TRACKER, "ExecuteUbergraph_Comp_Rift_X_RiftTracker@2615"),
                 _cite(_TRACKER, "SetHasUsableRift"), _cite(_MARKERS, "SetSelectedOnWidget"),
                 _cite(_MARKERS, "GameObject_Rift_X_Markers_C.ChildProperties.CurrentlySelected"),
                 _cite(_MARKERS, "GameObjectVisibility_GEN_VARIABLE")],
}
VIEW_READINGS = {(_MARKERS, ev): _STAR_SELF_ONLY for ev in
                 ("SelectedAsBest", "UnselectedAsBest", "SetSelected", "SetSelectedOnWidget")}
VIEW_READINGS[(_MARKERS, "Comp_InWorldIcon", "inworld_HighlightedTexture")] = dict(_STAR_SELF_ONLY, basis=(
    "HighlightedTexture shows when SetSelected(True) calls Comp_InWorldIcon.SetSelected (ubergraph 5908-5977), "
    "reached only through the tracker's local selection: " + _STAR_SELF_ONLY["basis"]))

#: Entity models read by hand from the bytecode, per agent: an entity with its own states and the
#: abilities that operate on it. Each state cites what it rests on; `predecessor` names the state the
#: data puts before it on the view it names.
ENTITY_READINGS = {
    "Astra": [{
        "entity": _MARKERS, "name": "star",
        "placed_by": {"key": "X", "basis": "Ability_Rift_X_WorldTargetingStart names Rift_TargetingForm_PC (ubergraph "
                      "2392); its StartingEquippableClasses[0] is Ability_Rift_X_PlaceMarkers_WorldTargeting, whose "
                      "SpawnActorState_Rift spawns GameObject_Rift_X_Markers",
                      "rests_on": [_cite(f"{_RIFT}/S0/Ability_X/Ability_Rift_X_WorldTargetingStart", "ExecuteUbergraph_Ability_Rift_X_WorldTargetingStart@2392"),
                                   _cite(f"{_RIFT}/S0/Ability_X/WorldTargeting/Rift_TargetingForm_PC", "Default__Rift_TargetingForm_PC_C.StartingEquippableClasses"),
                                   _cite(f"{_RIFT}/S0/Ability_X/WorldTargeting/Ability_Rift_X_PlaceMarkers_WorldTargeting", "SpawnActorState_Rift_GEN_VARIABLE")]},
        "states": [
            {"state": "forming", "predecessor": "placed",
             "what": "StartRiftMarker: IsUsable false, HasStarted true, activate timeline (RiftActivateTime 1.25 s, "
                     "CreationWarmupTime 3.0 s, RiftUsableDelayTime 1.4 s class defaults)",
             "rests_on": [_cite(_MARKERS, "StartRiftMarker"), _cite(_MARKERS, "Default__GameObject_Rift_X_Markers_C")]},
            {"state": "drawn", "views": {"self": True, "teammate": True, "enemy": None},
             "what": "minimap IconBrush TX_UI_Minimap_Rift_Passive_Default, 25 px screen size, colour alpha 0.75; "
                     "UpdateMinimap sets alpha 1.0 when the owner is alive and the star usable, else 0.25. "
                     "GameObjectVisibility.EnemyVisibility is Never; what that means for an enemy's minimap the data "
                     "does not define",
             "rests_on": [_cite(_MARKERS, "BaseMinimapComponent_Parent_GEN_VARIABLE"), _cite(_MARKERS, "UpdateMinimap"),
                          _cite(_MARKERS, "GameObjectVisibility_GEN_VARIABLE")]},
            {"state": "hovered", "predecessor": "drawn", "views": {k: _STAR_SELF_ONLY[k] for k in VIEWS},
             "what": "the tracker's best star within UseRiftAngle 6 degrees (server +1): SelectedAsBest -> SetSelected(True) "
                     "-> minimap brush TX_Astra_Minimap_PassiveGold and in-world HighlightedTexture "
                     "TX_UI_Minimap_Rift_Passive_Hovered",
             "rests_on": _STAR_SELF_ONLY["rests_on"] + [_cite(_TRACKER, "Default__Comp_Rift_X_RiftTracker_C")]},
            {"state": "unhovered", "predecessor": "hovered", "views": {k: _STAR_SELF_ONLY[k] for k in VIEWS},
             "what": "UnselectedAsBest -> SetSelected(False) -> minimap brush TX_Astra_Minimap_PassiveBlack",
             "rests_on": _STAR_SELF_ONLY["rests_on"]},
            {"state": "consumed", "predecessor": "hovered", "operated_on_by": {"C": "GameObject_Rift_4_BlackHole",
                                                                               "Q": "GameObject_Rift_Q_FlashBurst",
                                                                               "E": "GameObject_Rift_E_SmokeZone"},
             "what": "Ability_Rift_TransformRift_Parent: TestBranch_Rift_X_HasRiftToUse.StateTest takes the tracker's "
                     "HasUsableRift best star (the star the self view draws hovered) as the transition context; "
                     "GetTransformFromActorContext (DestroyContextActorAfter true) destroys it; each child's "
                     "SpawnActorState spawns its own game object at the star's transform. The data orders hovered "
                     "before consumed on the self view only; it states no frame count",
             "rests_on": [_cite(f"{_RIFT}/S0/Ability_X/TestBranch_Rift_X_HasRiftToUse", "StateTest"),
                          _cite(f"{_RIFT}/Global/Ability_Rift_TransformRift_Parent", "GetTransformFromActorContext_StateComponent_GEN_VARIABLE"),
                          _cite(f"{_RIFT}/S0/Ability_4/BlackHole/Ability_Rift_4_BlackHole", "SpawnActorState_GEN_VARIABLE"),
                          _cite(f"{_RIFT}/S0/Ability_Q/Ability_Rift_Q_FlashBurst", "SpawnActorState_GEN_VARIABLE"),
                          _cite(f"{_RIFT}/S0/Ability_E/Ability_Rift_E_TransformRift_Smoke", "SpawnActorState_GEN_VARIABLE")]},
            {"state": "dissipated", "predecessor": "drawn",
             "what": "Usable_FakeRift use, outside game phase 3, once started: AttempFakeSmoke, SpawnAbilityChildActor("
                     "FakeSmokeClass) at the star, MulticastDeactivateRift. Which key the use input is, the data here "
                     "does not name",
             "rests_on": [_cite(_MARKERS, "ExecuteUbergraph_GameObject_Rift_X_Markers@3904"), _cite(_MARKERS, "Usable_FakeRift_GEN_VARIABLE")]},
            {"state": "picked_up", "predecessor": "drawn",
             "what": "the same use in game phase 3 before the three-second countdown (CanPickupStar): the star "
                     "replenishes one charge (EquipmentChargeComponent.Replenish(1) on inventory slot 6)",
             "rests_on": [_cite(_MARKERS, "CanPickupStar"), _cite(_MARKERS, "ExecuteUbergraph_GameObject_Rift_X_Markers@4789")]},
            {"state": "deactivated", "predecessor": "consumed|dissipated",
             "what": "MulticastDeactivateRift (ubergraph 3077): destroys the star's effects, hides it "
                     "(AuthSetActorGameplayHidden 'Deactivated'), TrackReplenishTime (ReplenishCooldownTime 8 s)",
             "rests_on": [_cite(_MARKERS, "MulticastDeactivateRift"), _cite(_MARKERS, "ExecuteUbergraph_GameObject_Rift_X_Markers@2374")]},
        ],
        "open": ["which views draw the hovered (yellow) state: the data draws it on Astra's own client only, so "
                 "a spectator watching Astra sees no yellow, against the belief that a spectator's view matches "
                 "the player's [domain:" + SPECTATOR_FACT + "]",
                 "the frame count between hovered and consumed: the data orders them and names no time"],
    }],
}

_vis_cache: dict[str, dict] = {}


def entity_visibility(pkg: str) -> dict:
    """GameObjectVisibilityComponent settings of an entity (EnemyVisibility, ...), with where they sit."""
    if pkg not in _vis_cache:
        out = {}
        for key, c in merged_components(pkg).items():
            if c["type"] == "GameObjectVisibilityComponent":
                out = {k: v for k, v in c["props"].items() if "Visibility" in k}
                out["_where"] = c["export"]
        _vis_cache[pkg] = out
    return _vis_cache[pkg]


def views_of(r: dict, enemy_icon_states: set) -> tuple[dict, dict]:
    """(views, basis): per viewer true, false or null, and why. Spectator copies self unless a
    VIEW_READINGS entry decides it."""
    v = {k: None for k in VIEWS}
    b = {}
    ct = r.get("cue_type") or ""
    if ct == "sound" and r.get("perspective") in SOUND_VIEWS:
        v["self"], v["teammate"], v["enemy"] = SOUND_VIEWS[r["perspective"]]
        basis = f"perspective {r['perspective']}" + (f" ({r['perspective_basis']})" if r.get("perspective_basis") else "")
        if r["perspective"] == "unmuted":
            basis += "; Wwise picks the media per view by a switch the cooked event does not expose"
        b.update({k: basis for k in ("self", "teammate", "enemy")})
        if r.get("team") == "alliance:EAresAlliance::Alliance_Enemy":
            v["self"], v["teammate"], v["enemy"] = False, False, True
            b.update({k: "PlayWithAlliance=Alliance_Enemy" for k in ("self", "teammate", "enemy")})
    elif ct.startswith("minimap_"):
        if ct == "minimap_EnemyIcon":
            v["self"], v["teammate"], v["enemy"] = False, False, True
            b.update({k: "EnemyIcon: the enemy's drawing" for k in ("self", "teammate", "enemy")})
        elif r.get("owner_kind") == "equippable":
            # a minimap component on the held ability (an aim preview): the caster sees it; who else does, the
            # data does not say
            v["self"], b["self"] = True, f"{ct[len('minimap_'):]} on the equippable the caster holds"
        else:
            v["self"] = v["teammate"] = True
            b["self"] = b["teammate"] = (f"{ct[len('minimap_'):]} on the spawned entity: the caster's side draws it; the "
                                         "caster's own casts draw as a teammate's [domain:minimap/ability-drawing-colour-by-side]")
            if (r.get("owner"), r.get("state")) in enemy_icon_states:
                v["enemy"], b["enemy"] = False, "the same component draws EnemyIcon for enemies"
        vis = entity_visibility(r["owner"]) if r.get("owner_kind") == "entity" else {}
        ev = vis.get("EnemyVisibility")
        if ev:
            # a native setting whose effect on the enemy's minimap the data does not define: recorded, not applied
            b["enemy_visibility"] = f"{ev} ({vis['_where']})"
            if v["enemy"] is None:
                b["enemy"] = f"undecided: GameObjectVisibility {ev}, whose minimap meaning the data does not define"
    elif ct.startswith("inworld_"):
        v["self"], b["self"] = True, "in-world icon of the caster's entity"
    reading = VIEW_READINGS.get((r.get("owner"), r.get("state"), ct)) or VIEW_READINGS.get((r.get("owner"), r.get("state"))) or (
        VIEW_READINGS.get((r.get("owner"), (r.get("via") or "").split(" ", 1)[-1].split(" ->")[0]))
        if (r.get("via") or "").startswith("bytecode ") else None)
    if reading:
        for k in VIEWS:
            v[k] = reading[k]
            b[k] = "bytecode read by hand: " + reading["basis"]
        b["rests_on"] = reading["rests_on"]
    else:
        v["spectator"] = v["self"]
        b["spectator"] = f"copies self [domain:{SPECTATOR_FACT}]"
    return v, b


# --------------------------------------------------------------------------- build


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def cmd_build(args):
    t0 = datetime.datetime.now(datetime.timezone.utc)
    cn = codenames()
    keys = default_keys()
    agents = sorted(cn) if args.agents in (None, "", "all") else args.agents.split(",")
    rows_all, man_rows, by_stem = [], *manifest_index()
    tex = texture_index()
    summary = {}
    for agent in agents:
        own = cn[agent]["own"]
        k = kit(agent, cn, keys)
        eqs = {a["equippable"] for a in k if a["equippable"]}
        depth = {}  # first walk: the fewest steps each ability takes to each entity
        reach = collections.defaultdict(dict)  # entity -> {key: {"depth", "how"}}
        for a in k:
            if a["equippable"] and a["slot_enum"] in SLOT_ACTION:
                _r, inf = ability_table(a, own, eqs - {a["equippable"]})
                depth[a["equippable"]] = {e["entity"]: e["depth"] for e in inf["entities"]}
                for e in inf["entities"]:
                    reach[e["entity"]][a["key"]] = {"depth": e["depth"], "how": e["how"], "named_by": e["named_by"]}
        summary[agent] = {"codename": cn[agent]["codename"], "abilities": {}}
        # an entity one ability spawns and another names: the other ability operates on it
        ops = []
        for ent, by in sorted(reach.items()):
            spawners = sorted(kk for kk, v in by.items() if v["how"] == "spawns")
            namers = sorted(kk for kk, v in by.items() if v["how"] == "names")
            if len(by) > 1:
                ops.append({"entity": ent, "spawned_by": spawners, "named_by": namers,
                            "operated_on_by": [kk for kk in namers if spawners and kk not in spawners],
                            "reach": by})
        summary[agent]["entity_operations"] = ops
        owners_of = {}
        for ent, by in reach.items():
            spawners = [kk for kk, v in by.items() if v["how"] == "spawns"]
            if spawners:
                owners_of[ent] = {"keys": sorted(spawners), "basis": "spawns"}
            else:
                dmin = min(v["depth"] for v in by.values())
                owners_of[ent] = {"keys": sorted(kk for kk, v in by.items() if v["depth"] == dmin),
                                  "basis": f"fewest steps ({dmin})"}
        if ENTITY_READINGS.get(agent):
            summary[agent]["entity_readings"] = ENTITY_READINGS[agent]
        variants, unassigned = variant_equippables(agent, cn, eqs)
        summary[agent]["unassigned_equippables"] = unassigned
        for v in variants:
            base = next((a for a in k if a["slot_enum"] == SLOT_OF_ITEM[v["equippable_slot"]]), None)
            if base:
                vab = dict(base, equippable=v["equippable"])
                vrows, vinfo = ability_table(vab, own, eqs, set())
                for r in vrows:
                    r["equippable_variant"] = v["basis"]
                rows_all += vrows
                summary[agent].setdefault("variants", []).append({**v, "key": base["key"], "ability": base["ability"],
                                                                  "entities": vinfo["entities"]})
        for ab in k:
            if ab["slot_enum"] not in SLOT_ACTION:
                summary[agent]["abilities"][ab["slot_enum"]] = {"ability": ab["ability"], "skipped": "passive (no input action)"}
                continue
            rows, info = ability_table(ab, own, eqs - {ab["equippable"]}, owners_of)
            rows_all += rows
            # equippables a character form of this ability carries under another ability's slot
            for f in info.get("character_forms", []):
                base = next((a for a in k if a["slot_enum"] == f.get("belongs_to_slot")), None)
                if base:
                    vab = dict(base, equippable=f["equippable"])
                    vrows, vinfo = ability_table(vab, own, eqs, owners_of)
                    for r in vrows:
                        r["equippable_variant"] = f["basis"]
                        r["character_form"] = f["form"]
                    rows_all += vrows
                    summary[agent].setdefault("variants", []).append({**f, "key": base["key"], "ability": base["ability"],
                                                                      "cast_from_form_of": ab["key"],
                                                                      "entities": vinfo["entities"]})
            summary[agent]["abilities"][ab["key"] or ab["slot_enum"]] = {**{kk: ab[kk] for kk in (
                "ability", "slot_enum", "key", "key_basis", "ability_folder", "equippable", "primary_asset", "uidata",
                "display_icon")}, **info}
    # attach media and texture files
    ev_cache = {}
    for r in rows_all:
        if r.get("cue_type") == "sound":
            base = r["cue"].rsplit("/", 1)[-1]
            if base.startswith("Stop_"):
                r["sound_role"] = "stop"
            elif base.startswith("Play_") and r.get("sound_role") is None:
                r["sound_role"] = "play"
            r["name_perspective"] = name_perspective(base)
            if r["cue"] not in ev_cache:
                em = event_media(r["cue"])
                files = []
                for m in em["media"]:
                    st = re.sub(r"\.wav$", "", m.replace("\\", "/").rsplit("/", 1)[-1], flags=re.I).lower()
                    mp = name_perspective(st)  # the media file's own name: which view the switch likely picks it for
                    for mr in by_stem.get(st, []):
                        files.append({"media": m, "flac": mr["flac"], "manifest_ability": mr.get("ability"),
                                      "manifest_basis": mr.get("map_basis"), "manifest_role": mr.get("role"),
                                      "manifest_perspective": mr.get("perspective"), "media_name_perspective": mp})
                    if not by_stem.get(st):
                        files.append({"media": m, "flac": None, "media_name_perspective": mp})
                ev_cache[r["cue"]] = {"event_exported": em["exported"], "media": em["media"], "files": files}
            r.update(ev_cache[r["cue"]])
            r["rests_on"] = r["rests_on"] + ([rel(r["cue"])] if ev_cache[r["cue"]]["event_exported"] else [])
        elif r.get("cue_type", "").startswith(ICON_PREFIXES) or r.get("cue_type") == "texture":
            r["png"] = tex.get(r["cue"])
        r["phase"], r["phase_basis"] = phase_of(("state", r.get("state")), ("effect", (r.get("effect") or "").rsplit("/", 1)[-1]),
                                                ("cue", (r.get("cue") or "").rsplit("/", 1)[-1]))
        cited = list(dict.fromkeys(r["rests_on"]))
        r["rests_on"] = [x for x in cited if (STORE / x.split("#")[0]).exists()]
        r["not_exported"] = [x for x in cited if not (STORE / x.split("#")[0]).exists()] or None
        r["version"] = VERSION
        r["build"] = BUILD
    # views per viewer
    enemy_icon_states = {(r.get("owner"), r.get("state")) for r in rows_all if r.get("cue_type") == "minimap_EnemyIcon"}
    for r in rows_all:
        if r.get("cue_type") in (None, "no_effect", "missing_fxc", "montage_no_sound", "montage_not_exported"):
            continue
        r["views"], r["view_basis"] = views_of(r, enemy_icon_states)
    # which abilities reach each cue (shared cues witness no single ability)
    reach = collections.defaultdict(set)
    for r in rows_all:
        if r.get("cue"):
            reach[r["cue"]].add(f"{r['agent']}:{r['key']}")
    for r in rows_all:
        if r.get("cue"):
            r["cue_reached_from"] = sorted(reach[r["cue"]])
            r["cue_shared"] = len(reach[r["cue"]]) > 1
    OUT.mkdir(parents=True, exist_ok=True)
    out = Path(args.out) if args.out else OUT
    out.mkdir(parents=True, exist_ok=True)
    keyorder = ["version", "build", "agent", "codename", "key", "slot_enum", "ability", "ability_folder", "equippable",
                "equippable_variant", "character_form", "form_equippable", "owner_kind", "owner", "entity_depth", "entity_named_by",
                "state", "state_kind", "declared_order", "params", "phase", "phase_basis",
                "effect", "effect_flags", "cue_type", "cue", "sound_role", "perspective", "perspective_basis", "name_perspective", "team",
                "views", "view_basis",
                "montage", "montage_t_s", "via", "fxc_function", "timer_binds", "minimap_props", "event_exported", "media", "files", "png", "cue_reached_from", "cue_shared", "rests_on", "not_exported"]
    with open(out / f"{VERSION}.jsonl", "w", encoding="utf-8", newline="\n") as f:
        for r in rows_all:
            f.write(json.dumps({k: r.get(k) for k in keyorder if k in r}) + "\n")
    # per FLAC: the abilities, phases and states whose events play it (the event's media list joins the file)
    flac_rows = collections.defaultdict(list)
    for r in rows_all:
        if r.get("cue_type") == "sound":
            for f in r.get("files") or []:
                if f.get("flac"):
                    flac_rows[f["flac"]].append((r, f))
    man_by_flac = {m["flac"]: m for m in man_rows}
    with open(out / f"audio-phases-{VERSION}.jsonl", "w", encoding="utf-8", newline="\n") as fh:
        for flac in sorted(set(man_by_flac) | set(flac_rows)):
            m = man_by_flac.get(flac, {})
            rs = flac_rows.get(flac, [])
            abil = sorted({f"{r['agent']}:{r['key']}:{r['ability']}" for r, _ in rs})
            phases = sorted({r.get("phase") or "none" for r, _ in rs})
            fh.write(json.dumps({
                "version": VERSION, "flac": flac, "agent": m.get("agent"), "duration_s": m.get("duration_s"),
                "manifest_ability": m.get("ability"), "manifest_role": m.get("role"),
                "abilities": abil, "phases": phases,
                "decided": ("one ability, one phase" if len(abil) == 1 and len(phases) == 1 else
                            "one ability, several phases" if len(abil) == 1 else
                            "shared by abilities" if abil else "no ability's data plays it"),
                "media_name_perspective": next((f.get("media_name_perspective") for _, f in rs), None),
                "states": sorted({(r["key"], r["owner"].rsplit("/", 1)[-1], r["state"], r.get("phase") or "none",
                                   r["cue"].rsplit("/", 1)[-1], str(r.get("perspective"))) for r, _ in rs}),
                "basis": "the AkAudioEvent's media list names the file; the event is played by the listed states",
                "rests_on": sorted({x for r, _ in rs for x in r["rests_on"][:2]})}) + "\n")
    # per ability: states with their cues
    for agent, s in summary.items():
        for key, a in s["abilities"].items():
            if "skipped" in a:
                continue
            mine = [r for r in rows_all if r["agent"] == agent and (r["key"] or r["slot_enum"]) == key]
            st = collections.OrderedDict()
            for r in mine:
                sk = f"{r['owner'].rsplit('/', 1)[-1]}::{r['state']}"
                d = st.setdefault(sk, {"owner": r["owner"], "owner_kind": r["owner_kind"], "state": r["state"],
                                       "state_kind": r["state_kind"], "phase": None, "phase_basis": None,
                                       "sounds": [], "vo_rows": [], "icons": [], "effects": set(), "rests_on": set()})
                if r.get("phase") and not d["phase"]:
                    d["phase"], d["phase_basis"] = phase_of(("state", r["state"]))
                    if not d["phase"]:
                        d["phase"], d["phase_basis"] = r["phase"], r["phase_basis"]
                if r.get("effect"):
                    d["effects"].add(r["effect"].rsplit("/", 1)[-1])
                d["rests_on"].update(r["rests_on"][:2])
                if r["cue_type"] == "sound":
                    item = {"event": r["cue"].rsplit("/", 1)[-1], "role": r.get("sound_role"), "perspective": r.get("perspective"),
                            "views": r.get("views"), "team": r.get("team"), "shared_with": [x for x in r["cue_reached_from"] if x != f"{agent}:{key}"] or None,
                            "montage_t_s": r.get("montage_t_s"), "flacs": sorted({x["flac"] for x in r.get("files", []) if x.get("flac")})}
                    if item not in d["sounds"]:
                        d["sounds"].append(item)
                elif r["cue_type"] == "vo_row":
                    if r["cue"] not in d["vo_rows"]:
                        d["vo_rows"].append(r["cue"])
                elif r["cue_type"].startswith(ICON_PREFIXES) or r["cue_type"] == "texture":
                    item = {"texture": r["cue"].rsplit("/", 1)[-1], "role": r["cue_type"], "minimap_props": r.get("minimap_props"),
                            "views": r.get("views"), "png": r.get("png"), "via": r["via"]}
                    if item not in d["icons"]:
                        d["icons"].append(item)
            for d in st.values():
                d["effects"] = sorted(d["effects"])
                d["rests_on"] = sorted(d["rests_on"])
            a["states"] = list(st.values())
            a["coverage"] = {
                "states": len(st),
                "states_with_sound": sum(1 for d in st.values() if d["sounds"]),
                "sound_events": len({x["event"] for d in st.values() for x in d["sounds"]}),
                "flacs": len({f for d in st.values() for x in d["sounds"] for f in x["flacs"]}),
                "states_with_icon": sum(1 for d in st.values() if d["icons"]),
                "icon_textures": len({x["texture"] for d in st.values() for x in d["icons"]}),
                "icon_textures_without_png": sorted({x["texture"] for d in st.values() for x in d["icons"] if not x["png"]}),
                "phases": collections.Counter(d["phase"] for d in st.values()).most_common(),
            }
    meta = {"version": VERSION, "build": BUILD, "built_utc": t0.isoformat(), "agents": agents,
            "rows": len(rows_all), "phase_vocabulary": PHASES,
            "inputs": {"ability_states_export": str(EXP.relative_to(STORE)).replace("\\", "/"),
                       "ability_states_manifest_sha256": sha(EXP / "manifest.jsonl"),
                       "ability_anims_manifest_sha256": sha(ANIMS / "manifest-montages.jsonl"),
                       "audio_manifest": "reference/game-files/audio/manifest-0.2.0.jsonl",
                       "audio_manifest_sha256": sha(AUDIO / "manifest-0.2.0.jsonl"),
                       "codenames_sha256": sha(AUDIO / "codenames.json"),
                       "texture_sets": TEXTURE_SETS,
                       "build_provenance": str((GX / "provenance.json").relative_to(STORE)).replace("\\", "/")},
            "tool": {"path": "prototypes/ability_states_gamedata.py", "sha256": sha(Path(__file__))}}
    json.dump({"meta": meta, "agents": summary}, open(out / f"{VERSION}.json", "w", encoding="utf-8", newline="\n"),
              indent=1, default=list)
    json.dump(meta, open(out / f"provenance-{VERSION}.json", "w", encoding="utf-8", newline="\n"), indent=1, default=list)
    print(json.dumps({"rows": len(rows_all), "agents": len(agents)}))


# --------------------------------------------------------------------------- checks


ANSWERS = STORE / "labels" / "minimap_glyph_questions" / "answers.jsonl"
INVENTORY = STORE / "analysis" / "minimap-glyphs-20261004" / "inventory.json"
SHEET = Path(__file__).resolve().parents[1] / "docs" / "ABILITY_MECHANICS_SHEET.md"
SLOT_OF_ITEM_SLOT = {"EAresItemSlot::GrenadeAbility": "Grenade", "EAresItemSlot::Ability1": "Ability1",
                     "EAresItemSlot::Ability2": "Ability2", "EAresItemSlot::Ultimate": "Ultimate"}


def sheet_names() -> dict:
    """(agent, key) -> ability name, from the mechanics sheet's per-agent tables."""
    out, agent = {}, None
    for line in open(SHEET, encoding="utf-8"):
        m = re.match(r"^## (.+?)\s*$", line)
        if m:
            agent = m.group(1)
            continue
        m = re.match(r"^\| ([CQEX]) \| ([^|]+?) \|", line)
        if agent and m:
            out[(agent, m.group(1))] = m.group(2).strip()
    return out


def player_answers() -> dict:
    """Latest answer per key (the tool's rule: the last row per key wins)."""
    out = {}
    if ANSWERS.exists():
        for line in open(ANSWERS, encoding="utf-8"):
            r = json.loads(line)
            out[r["key"]] = r
    return out


def norm(name: str | None) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def cmd_checks(args):
    out = Path(args.out) if args.out else OUT
    table = json.load(open(out / f"{VERSION}.json", encoding="utf-8"))
    rows = [json.loads(l) for l in open(out / f"{VERSION}.jsonl", encoding="utf-8")]
    agents = table["meta"]["agents"]
    res = {"version": VERSION, "build": BUILD, "agents": agents}

    # 1. keys: DefaultInput + UIData slot, the equippable's own item slot, the tuning tag letter, the sheet's name
    sheet = sheet_names()
    keys = []
    for agent, s in table["agents"].items():
        for key, a in s["abilities"].items():
            if "skipped" in a:
                continue
            item = SLOT_OF_ITEM_SLOT.get(a.get("equippable_slot") or "")
            name_sheet = sheet.get((agent, key))
            keys.append({"agent": agent, "key": key, "ability": a["ability"], "slot_enum": a["slot_enum"],
                         "equippable_slot": a.get("equippable_slot"), "item_slot_agrees": (item == a["slot_enum"]) if item else None,
                         "tuning_tag_letters": a.get("tuning_tag_letters"),
                         "tuning_tag_agrees": a.get("tuning_tag_letter_agrees_with_key"),
                         "sheet_name": name_sheet, "sheet_agrees": (norm(name_sheet) == norm(a["ability"])) if name_sheet else None,
                         "ability_folder": a.get("ability_folder")})
    res["keys"] = {"rows": keys,
                   "item_slot_disagree": [k for k in keys if k["item_slot_agrees"] is False],
                   "tuning_tag_disagree": [k for k in keys if k["tuning_tag_agrees"] is False],
                   "sheet_disagree": [k for k in keys if k["sheet_agrees"] is False],
                   "counts": {"abilities": len(keys),
                              "item_slot_agree": sum(k["item_slot_agrees"] is True for k in keys),
                              "item_slot_absent": sum(k["item_slot_agrees"] is None for k in keys),
                              "tuning_tag_agree": sum(k["tuning_tag_agrees"] is True for k in keys),
                              "tuning_tag_absent": sum(k["tuning_tag_agrees"] is None for k in keys),
                              "sheet_agree": sum(k["sheet_agrees"] is True for k in keys)}}

    # 2. the audio manifest: which abilities' states reach each FLAC's events
    reach = collections.defaultdict(set)
    phase = collections.defaultdict(set)
    for r in rows:
        if r.get("cue_type") == "sound":
            reach[r["cue"]].add(f"{r['agent']}:{r['key']}:{r['ability']}")
            if r.get("phase"):
                phase[r["cue"]].add(r["phase"])
    man = [json.loads(l) for l in open(AUDIO / "manifest-0.2.0.jsonl", encoding="utf-8")]
    cats = collections.Counter()
    disagree, resolved, silent_unmapped, shared_rows = [], [], [], []
    role_vs_phase = collections.Counter()
    for m in man:
        if m["agent"] not in agents:
            continue
        evs = ["/Game/" + e for e in m.get("events") or []]
        data = set().union(*[reach.get(e, set()) for e in evs]) if evs else set()
        names = {d.split(":", 2)[2] for d in data if d.split(":")[0] == m["agent"]}
        ph = set().union(*[phase.get(e, set()) for e in evs]) if evs else set()
        role_vs_phase[(m.get("role"), ",".join(sorted(ph)) or None)] += 1
        item = {"flac": m["flac"], "events": [e.rsplit("/", 1)[-1] for e in evs], "manifest_ability": m.get("ability"),
                "manifest_basis": m.get("map_basis"), "manifest_role": m.get("role"), "data_abilities": sorted(data),
                "data_phases": sorted(ph)}
        if m.get("ability") is None:
            if names:
                cats["unmapped_resolved_by_data" if len(names) == 1 else "unmapped_data_shared"] += 1
                resolved.append(item)
            else:
                cats["unmapped_data_silent"] += 1
                silent_unmapped.append(item | {"unmapped_reason": m.get("unmapped_reason")})
        elif not names:
            cats["mapped_data_silent"] += 1
        elif m["ability"] in names and len(names) == 1:
            cats["agree"] += 1
        elif m["ability"] in names:
            cats["agree_shared"] += 1
            shared_rows.append(item)
        else:
            cats["disagree"] += 1
            disagree.append(item)
    res["audio_manifest"] = {"counts": dict(cats), "disagree": disagree, "unmapped_resolved": resolved,
                             "unmapped_silent": silent_unmapped, "shared": shared_rows,
                             "role_vs_phase": sorted([[k[0], k[1], v] for k, v in role_vs_phase.items()],
                                                     key=lambda x: -x[2])}

    # 3. minimap textures: the abilities whose entities or equippables name each one, against the
    #    inventory's proposal and the player's answers (labels, known = player)
    owners = collections.defaultdict(set)
    tex_rows = collections.defaultdict(list)
    for r in rows:
        if (r.get("cue_type", "").startswith(ICON_PREFIXES) or r.get("cue_type") == "texture") and "inimap" in (r.get("cue") or ""):
            t = r["cue"].rsplit("/", 1)[-1]
            owners[t].add(f"{r['agent']}:{r['key']}")
            tex_rows[t].append({"ability": f"{r['agent']}:{r['key']} {r['ability']}", "owner": r["owner"].rsplit("/", 1)[-1],
                                "state": r["state"], "role": r["cue_type"], "via": r["via"]})
    inv = json.load(open(INVENTORY, encoding="utf-8"))["rows"]
    answers = player_answers()
    tex_answers = {k.split(":", 1)[1]: v for k, v in answers.items() if v["kind"] == "texture"}

    def answer_for(name):
        best = None
        for base, a in tex_answers.items():
            if name == base or name.startswith(base + "_"):
                if best is None or len(base) > len(best[0]):
                    best = (base, a)
        return best

    tex_checks = []
    names = sorted(set(owners) | {r["name"] for r in inv if r.get("agent") in agents})
    for name in names:
        ir = next((r for r in inv if r["name"] == name), None)
        ans = answer_for(name)
        data = sorted(owners.get(name, set()))
        item = {"texture": name, "data_abilities": data, "data_rows": tex_rows.get(name, [])[:6],
                "inventory_status": (ir or {}).get("status"), "inventory_proposed": (ir or {}).get("proposed"),
                "inventory_state": (ir or {}).get("state"),
                "player_answer": (ans[1]["answer"] if ans else None), "player_unsure": (ans[1]["unsure"] if ans else None),
                "player_key": ("texture:" + ans[0]) if ans else None}
        item["agrees_with_player"] = (item["player_answer"] in data) if (data and item["player_answer"]) else None
        item["agrees_with_inventory"] = (item["inventory_proposed"] in data) if (data and item["inventory_proposed"]) else None
        tex_checks.append(item)
    res["minimap_textures"] = {
        "rows": tex_checks,
        "counts": {"textures": len(tex_checks), "named_by_data": sum(bool(t["data_abilities"]) for t in tex_checks),
                   "player_agree": sum(t["agrees_with_player"] is True for t in tex_checks),
                   "player_disagree": sum(t["agrees_with_player"] is False for t in tex_checks),
                   "inventory_agree": sum(t["agrees_with_inventory"] is True for t in tex_checks),
                   "inventory_disagree": sum(t["agrees_with_inventory"] is False for t in tex_checks),
                   "inventory_rows_not_named_by_data": sum(1 for t in tex_checks if t["inventory_status"] and not t["data_abilities"])},
        "player_disagree": [t for t in tex_checks if t["agrees_with_player"] is False],
        "inventory_disagree": [t for t in tex_checks if t["agrees_with_inventory"] is False]}

    # 4. the domain facts the task names
    def who(event_base):
        return sorted({x for e, s in reach.items() if e.rsplit("/", 1)[-1] == event_base for x in s})
    facts = {}
    facts["sova-abilq-cast-is-shock-bolt"] = {"event": "Play_Hunter_AbilQ_Cast", "reached_from": who("Play_Hunter_AbilQ_Cast"),
                                              "fact_says": "Shock Bolt's cast, not the Recon Bolt's (player)"}
    facts["skye-scout-expire-is-guiding-light"] = {
        "event": "Play_Guide_AbilE_ScoutExpire", "reached_from": who("Play_Guide_AbilE_ScoutExpire"),
        "event_1P": who("Play_Guide_AbilE_ScoutExpire_1P"), "fact_says": "Guiding Light's expiry (player)"}
    eq_events = ["Play_Hunter_Abil4_Equip_Bow_Mvt_A", "Play_Hunter_Abil4_Equip_Bow_Mvt_B",
                 "Play_Hunter_S0_AB_Q_SonarBolt_Equip_Bow_Mvt_C", "Play_Hunter_S0_AB_Q_SonarBolt_Equip_Elec_A",
                 "Play_Hunter_Abil4_Equip_Elec_B", "Play_Hunter_S0_AB_Q_SonarBolt_Equip_Circle"]
    facts["sova-bolt-equips-share-sounds"] = {"events": {e: who(e) for e in eq_events},
                                              "fact_says": "Bow_Mvt_A, _B, _C and Elec_A shared; Elec_B Shock Bolt only; Circle Recon Bolt only"}
    res["domain_facts"] = facts

    # 6. views: per viewer, from the data; a teammate-enemy difference is a recorded fact, never a conflict
    vrows = [r for r in rows if r.get("views")]
    fam = lambda r: r["cue_type"].split("_")[0]  # noqa: E731
    differs_spec = [{"agent": r["agent"], "key": r["key"], "owner": r["owner"].rsplit("/", 1)[-1], "state": r["state"],
                     "cue": (r.get("cue") or "").rsplit("/", 1)[-1], "views": r["views"],
                     "basis": r["view_basis"].get("spectator"), "rests_on": r["view_basis"].get("rests_on")}
                    for r in vrows if r["views"]["spectator"] != r["views"]["self"]]
    tm_vs_en = [r for r in vrows if None not in (r["views"]["teammate"], r["views"]["enemy"])
                and r["views"]["teammate"] != r["views"]["enemy"]]
    # the player's sure visibility answers (latest row per key) beside the data's minimap rows of that ability
    last = {}
    if ANSWERS.exists():
        for line in open(ANSWERS, encoding="utf-8"):
            if line.strip():
                a = json.loads(line)
                last[a["key"]] = a
    vis_cmp = []
    for kk, a in sorted(last.items()):
        parts = kk.split(":")
        if parts[0] != "visibility" or len(parts) != 4 or parts[3] not in ("ally", "enemy") or a.get("unsure") \
                or parts[1] not in agents:
            continue
        view = "teammate" if parts[3] == "ally" else "enemy"
        mrows = [r for r in vrows if r["agent"] == parts[1] and r["key"] == parts[2] and fam(r) == "minimap"]
        vals = {r["views"][view] for r in mrows}
        data = True if True in vals else (False if vals == {False} else None)
        ans = a.get("answer")
        drawn = None if ans in (None, "other") else ans != "nothing"
        vis_cmp.append({"key": kk, "answer": ans, "other": a.get("other"), "data_draws": data,
                        "data_textures": sorted({r["cue"].rsplit("/", 1)[-1] for r in mrows if r["views"][view] is not None}),
                        "enemy_visibility": sorted({r["view_basis"]["enemy_visibility"].split(" (")[0] for r in mrows
                                                    if r["view_basis"].get("enemy_visibility")}) if view == "enemy" else None,
                        "status": ("undecided_by_data" if data is None else "not_compared" if drawn is None
                                   else "agree" if drawn == data else "disagree")})
    res["views"] = {
        "counts": {"rows_with_views": len(vrows),
                   **{f"{f}_{v}_{s}": n for (f, v, s), n in collections.Counter(
                       (fam(r), v, str(r["views"][v]).lower()) for r in vrows for v in VIEWS).items()
                      if f in ("sound", "minimap")},
                   "spectator_differs_from_self": len(differs_spec),
                   "teammate_enemy_differ": len(tm_vs_en),
                   "answers_compared": sum(c["status"] in ("agree", "disagree") for c in vis_cmp),
                   "answers_agree": sum(c["status"] == "agree" for c in vis_cmp),
                   "answers_disagree": sum(c["status"] == "disagree" for c in vis_cmp),
                   "answers_undecided_by_data": sum(c["status"] == "undecided_by_data" for c in vis_cmp),
                   "enemy_answers_beside_enemy_visibility_never": sum(
                       1 for c in vis_cmp if c["enemy_visibility"] and any(e.endswith("Never") for e in c["enemy_visibility"])),
                   "enemy_drawn_answers_beside_enemy_visibility_never": sum(
                       1 for c in vis_cmp if c["enemy_visibility"] and any(e.endswith("Never") for e in c["enemy_visibility"])
                       and c["answer"] not in (None, "other", "nothing"))},
        "spectator_fact": SPECTATOR_FACT,
        "spectator_differs_from_self": differs_spec,
        "teammate_enemy_differences": [{"agent": r["agent"], "key": r["key"], "cue_type": r["cue_type"],
                                        "cue": (r.get("cue") or "").rsplit("/", 1)[-1], "views": r["views"],
                                        "basis": {v: r["view_basis"].get(v) for v in ("teammate", "enemy")}}
                                       for r in tm_vs_en if fam(r) == "minimap"],
        "player_visibility_answers": vis_cmp,
    }

    # 7. entities with operations, shared components and character forms
    ops, shared, forms = [], [], []
    for agent, s in table["agents"].items():
        for o in s.get("entity_operations", []):
            item = {"agent": agent, "entity": o["entity"].rsplit("/", 1)[-1], "spawned_by": o["spawned_by"],
                    "named_by": o["named_by"], "operated_on_by": o["operated_on_by"]}
            (ops if o["operated_on_by"] else shared).append(item)
        for key, a in s["abilities"].items():
            for f in a.get("character_forms", []) or []:
                forms.append({"agent": agent, "key": key, "form": f["form"].rsplit("/", 1)[-1],
                              "equippable": f["equippable"].rsplit("/", 1)[-1], "belongs_to_slot": f.get("belongs_to_slot")})
    res["entities"] = {"counts": {"operated_entities": len(ops), "agents_with_operated_entities": len({o["agent"] for o in ops}),
                                  "shared_named_or_spawned": len(shared), "character_form_equippables": len(forms)},
                       "operated": ops, "shared": shared, "character_forms": forms,
                       "readings": {ag: s.get("entity_readings") for ag, s in table["agents"].items() if s.get("entity_readings")}}

    # 5. predictions S1..S10 (logged before this run, task ability-states-20261004)
    p = {}
    nine = [a for a in FIRST_AGENTS if a in agents]
    abil = [(ag, k, a) for ag in nine for k, a in table["agents"][ag]["abilities"].items() if "skipped" not in a]
    st_counts = [sum(1 for s in a["states"] if s["owner"] == a["equippable"] and s["state_kind"] not in
                     ("class_default_property", "event_function")) for _, _, a in abil]
    p["S1"] = {"abilities": len(abil), "with_ge2_state_components": sum(c >= 2 for c in st_counts), "threshold": 32}
    fx = {r["effect"] for r in rows if r["agent"] in nine and r.get("effect") and r["state_kind"] not in ("event_function",)}
    fx_snd = {r["effect"] for r in rows if r["agent"] in nine and r.get("effect") and r["cue_type"] == "sound"
              and not str(r.get("via", "")).count("bytecode")}
    p["S2"] = {"fxc_named_by_states": len(fx), "with_sound_without_bytecode": len(fx & fx_snd),
               "share": round(len(fx & fx_snd) / max(1, len(fx)), 3), "threshold": 0.7}
    man_ev = {"/Game/" + e for m in man if m["agent"] in nine for e in (m.get("events") or [])}
    p["S3"] = {"manifest_events": len(man_ev), "reached": len(man_ev & set(reach)),
               "share": round(len(man_ev & set(reach)) / max(1, len(man_ev)), 3), "threshold": 0.6}
    pairs = [(r.get("name_perspective"), r.get("perspective")) for r in rows
             if r["agent"] in nine and r["cue_type"] == "sound" and r.get("name_perspective")]
    decided = [(n, d) for n, d in pairs if d in ("1P", "3P", "3P-ally", "3P-enemy")]
    p["S4"] = {"named_events": len(pairs), "with_flag": len(decided),
               "agree": sum(1 for n, d in decided if d.startswith(n)),
               "share": round(sum(1 for n, d in decided if d.startswith(n)) / max(1, len(decided)), 3), "threshold": 0.8,
               "unmuted_named": sum(1 for n, d in pairs if d == "unmuted")}
    p["S5"] = facts["sova-abilq-cast-is-shock-bolt"]["reached_from"]
    p["S6"] = facts["skye-scout-expire-is-guiding-light"]["reached_from"]
    p["S7"] = {t["texture"]: t["data_abilities"] for t in tex_checks if t["texture"].startswith("TX_UI_Minimap_Killjoy")}
    p["S8"] = {"drone": {t["texture"]: t["data_abilities"] for t in tex_checks if "Sova:C" in t["data_abilities"]},
               "shock_bolt_minimap": [t["texture"] for t in tex_checks if "Sova:Q" in t["data_abilities"]]}
    p["S9"] = default_keys()
    un9 = [m for m in man if m["agent"] in nine and m.get("ability") is None]
    got = [m for m in un9 if any(d.split(":")[0] == m["agent"] for e in (m.get("events") or []) for d in reach.get("/Game/" + e, ()))]
    p["S10"] = {"unmapped_rows": len(un9), "reached_by_data": len(got), "share": round(len(got) / max(1, len(un9)), 3),
                "threshold": 0.5}
    # V1..V4 (logged before the 0.2.0 build)
    star = next((o for o in ops + shared if o["agent"] == "Astra" and o["entity"] == "GameObject_Rift_X_Markers"), None)
    p["V1"] = star
    p["V2"] = {"agents": sorted({o["agent"] for o in ops} - {"Astra"}),
               "sova_or_cypher": [o for o in ops if o["agent"] in ("Sova", "Cypher")]}
    enemy_decided = {(r["agent"], r["key"]) for r in vrows if fam(r) == "minimap" and r["views"]["enemy"] is not None}
    p["V3"] = {"abilities_with_enemy_minimap_rule": len(enemy_decided), "threshold": 25}
    p["V4"] = {"agents_where_spectator_differs": sorted({d["agent"] for d in differs_spec})}
    res["predictions"] = p
    json.dump(res, open(out / f"checks-{VERSION}.json", "w", encoding="utf-8", newline="\n"), indent=1, default=list)
    if args.record:
        record_metrics(res, table)
    print(json.dumps({"keys": res["keys"]["counts"], "audio": res["audio_manifest"]["counts"],
                      "textures": res["minimap_textures"]["counts"], "views": res["views"]["counts"],
                      "entities": res["entities"]["counts"]}, indent=1))


def record_metrics(res: dict, table: dict):
    """One run summary in the store's metrics log (series ability_states_gamedata/checks@all-agents)."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from reticle import metrics  # prototypes may import reticle; never the reverse
    values = {}
    for group in ("keys", "audio_manifest", "minimap_textures", "views", "entities"):
        for k, v in res[group]["counts"].items():
            values[f"{group}_{k}"] = v
    cov = collections.Counter()
    for s in table["agents"].values():
        for a in s["abilities"].values():
            if "skipped" not in a:
                cov["abilities"] += 1
                cov["states"] += a["coverage"]["states"]
                cov["states_with_sound"] += a["coverage"]["states_with_sound"]
                cov["states_with_icon"] += a["coverage"]["states_with_icon"]
    values.update({f"table_{k}": v for k, v in cov.items()})
    values["table_rows"] = table["meta"]["rows"]
    metrics.record("ability_states_gamedata", part="checks", session="all-agents" if len(res["agents"]) > 9 else "nine-agents",
                   values=values, deps={"version": VERSION, "build": BUILD,
                                        "export_manifest_sha256": table["meta"]["inputs"]["ability_states_manifest_sha256"]},
                   context={"audio_manifest_sha256": table["meta"]["inputs"]["audio_manifest_sha256"],
                            "answers_rows": sum(1 for _ in open(ANSWERS, encoding="utf-8")) if ANSWERS.exists() else 0,
                            "agents": len(res["agents"])})


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--agents", default=",".join(FIRST_AGENTS))
    b.add_argument("--out", default=None)
    c = sub.add_parser("checks")
    c.add_argument("--out", default=None)
    c.add_argument("--record", action="store_true", help="append the run summary to the store's metrics log")
    a = ap.parse_args()
    if a.cmd == "build":
        cmd_build(a)
    else:
        cmd_checks(a)


if __name__ == "__main__":
    main()
