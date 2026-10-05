r"""Sightlines in 3D from the game's own collision: a feasibility probe.

    .\.venv\Scripts\python.exe prototypes\sightlines_3d.py build --dump DIR --ini FILE --persistent FILE [--map ascent]
    .\.venv\Scripts\python.exe prototypes\sightlines_3d.py rebuild --map ascent --source OLDER.npz [--record]
    .\.venv\Scripts\python.exe prototypes\sightlines_3d.py gate [--map ascent] [--set dev|confirm] [--record]
    .\.venv\Scripts\python.exe prototypes\sightlines_3d.py state-props [--version sightlines-3d-0.3.0]
    .\.venv\Scripts\python.exe prototypes\sightlines_3d.py --self-test

Why this exists
---------------
Coaching asks whether a teammate could join a fight: swing with the player,
trade him or support him with utility. That is a question about sight across
the map's real 3D geometry, not about distance, and the minimap's 2D walls
cannot answer it where cover is low or floors stack. This probe asks whether
the extracted game files give a true 3D sightline map, cheaply.

Inputs
------
`<dump>` is the output of the store's extractor,
`game-extract meshes "ShooterGame/Content/Maps/<Map>/<Map>*.umap" --out <dump>`:
every placed static mesh with its world matrix and BodyInstance
(`instances.jsonl`), each mesh's collision trace flag, default collision and
simple shapes (`meshes.jsonl`), and the collision LOD's triangles
(`render.bin`). `--ini` is the game's `ShooterGame/Config/DefaultEngine.ini`
(collision profiles); `--persistent` is the persistent level's JSON, whose
`LevelStreamingAlwaysLoaded` rows name the sublevels a match loads.

What blocks sight
-----------------
A component blocks a trace channel when its collision answers queries and its
response to that channel is Block: the component's BodyInstance profile, else
the mesh's DefaultInstance profile, resolved through DefaultEngine.ini
(`Weapon` is `GameTraceChannel1`, default Block; `Custom` profiles use their
own ResponseArray). A mesh flagged `CTF_UseComplexAsSimple` collides with its
collision LOD's triangles (sections with collision on); any other mesh with its
simple shapes (boxes, convex hulls, spheres, capsules). Sight uses the Weapon
set; floors use the Pawn set.

Kept: every always-loaded sublevel plus the bomb-mode level (named
`_Mode_BombMode`, `_Modes_BombMode` or `_BombGameMode_Only` by map). Left out:
`Gameplay_Dynamic` (doors, window shields, switch boxes, respawning plates:
state changes in a round), `Greybox` (dynamic, not streamed in a match), the
other mode levels, and spawn barriers (they fall at round start). Maps
without a `Gameplay_Dynamic` level place their state-changing props in
always-loaded levels; their actor classes leave them out
(`STATE_CHANGING_CLASS`: doors, the drawbridge, switches, window shields,
respawning plates and shootables, destructibles and breakables), read off each
map's dump. Foliage, glass and invisible walls stay in or out by their own
collision profile, never by name.

A class name misses a subclass named for its art, so `state_changing` also
walks each placed class's parents through the class exports under the store's
`reference/game-files/<build>/props/` (`class_index`). A subclass of
`BP_Destructible_BASE_C` (its ReceiveAnyDamage calls Break: Bind's BP_Pot_1_C
and BP_Pot_3_C) is left out, and so is a door on the native `AresDoor` whose
default object is tagged `CollapsibleDoor` (Summit's DescentBox_v5_C starts
open and drops 300 cm over 1.75 s each round). A class with no export keeps
the name test alone; `state-props` lists, per map, what the test removes from
a stored table and which kept classes' chains it could not read.

Versions
--------
`sightlines-3d-0.4.0` changed only the maps whose blocker set held such a
prop (`REBUILT`); every other map's 0.3.0 table holds the same blockers,
heights and grid, and stands for 0.4.0 (`table_version`, `out_path`). A
map's gate rows carry its table's version.

Body heights
------------
Read at import from the game-data facts, which cite `BasePawn` and
`BasePlayerCharacter` [domain:game_data/character-eye-height]
[domain:game_data/character-jump]:

- `EYE_CM`, the standing eye: CapsuleHalfHeight plus BaseEyeHeight, the
  engine convention the fact states. StandingEyeOffset is left out; its use
  is unread.
- `BODY_CM`, the target on the victim: the capsule's centre. No field names
  a chest.
- `CROUCH_CLEAR_CM`, the free height a floor needs: the crouched capsule,
  twice CrouchedHalfHeight.
- `JUMP_CM`, the largest floor step the walk graph joins:
  DefaultJumpTuning.MaxJumpHeight.
- `WALKABLE_Z` stays UE's engine default walkable angle, a placeholder:
  the class chain serialises no walkable angle and its native parent's
  defaults are in no export.
- Three more heights are placeholders no field gives (`PLACEHOLDERS`):
  `CEILING_GAP_CM`, `BLOCKER_LINE_CM` and `REGION_PROBE_CM`.

No crouched eye is used: under a ceiling lower than the eye, the eye sits
`CEILING_GAP_CM` (5 cm) below the ceiling. `sightlines-3d-0.2.0` used placeholders throughout
(`HEIGHTS_0_2_0`); `rebuild` remakes a table from an older one's stored
blockers and callout volumes, which do not depend on the heights, so no
extraction reruns.

Tables
------
`<store>/sightlines/<map>__<VERSION>.npz`, one per map, beside the 2D tables
(`prototypes/sightlines.py`). Each carries the blockers, the standable cells,
the packed eye-to-eye visibility bits, the walk graph's edges (`walk_r`,
`walk_c`: a few MB in all; the all-pairs path distances are not cached, at
N x N uint16 they run to hundreds of MB a map), each cell's callout volume
(`cell_callout`, -1 outside every volume) and a provenance stamp naming the
game build and the extractor commit that dumped the meshes.

Data rules
----------
The 22 captured matches' Riot records are the development set; the gate
reads only those on the probed map. A map without development kills is gated
on the confirmation history's kills (`--set confirm`) as an instrument check
only: no hypothesis is scored, and the held-out replay matches, the captured
matches and the ladder's `holdout` matches stay out. Nothing here is a reader
input or shown during play; `wire = no` in the prediction row.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import re
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

VERSION = "sightlines-3d-0.4.0"
#: The version before; a map outside `REBUILT` keeps its table of that version.
PREVIOUS = "sightlines-3d-0.3.0"
#: The maps whose 0.3.0 blocker set held a placement the class-chain test
#: leaves out (`state-props` over the 0.3.0 tables): only their tables changed.
REBUILT = frozenset({"bind", "summit"})
GAME_BUILD = "release-13.06-shipping-18-5590001"
STORE = Path(os.environ.get("RETICLE_STORE", "C:/Users/grant/reticle-store"))
EXTRACTOR = STORE / "tools" / "game-extract"
REPO = Path(__file__).resolve().parents[1]
#: Class exports (`game-extract export`): each blueprint class's parent and its
#: default object's tags.
PROPS = STORE / "reference" / "game-files" / GAME_BUILD / "props"


def _game_body() -> dict:
    """The player character's body values, read from the game-data facts
    [domain:game_data/character-eye-height] [domain:game_data/character-jump]
    and converted to cm."""
    import tomllib
    facts = tomllib.loads((REPO / "domain" / "game_data.toml").read_text(encoding="utf-8"))
    eye, jump = facts["character-eye-height"]["values"], facts["character-jump"]["values"]
    return {"capsule_half_cm": 100.0 * eye["capsule"]["half_height_m"],
            "base_eye_cm": 100.0 * eye["eye"]["base_eye_height_m"],
            "crouched_half_cm": 100.0 * eye["capsule"]["crouched_half_height_m"],
            "step_cm": 100.0 * eye["nav_agent"]["step_height_m"],
            "max_jump_cm": 100.0 * jump["jump"]["max_jump_height_m"]}


GAME_BODY = _game_body()
#: The standing eye above the floor: the capsule's half-height plus
#: BaseEyeHeight, the engine convention the fact states (175 cm); the
#: StandingEyeOffset (-22 cm) is left out, as its use is unread.
EYE_CM = round(GAME_BODY["capsule_half_cm"] + GAME_BODY["base_eye_cm"], 3)
#: The target on the victim: the capsule's centre, its half-height above the
#: floor (98 cm). No field names a chest; 0.2.0 aimed at a 120 cm placeholder.
BODY_CM = round(GAME_BODY["capsule_half_cm"], 3)
#: Free height a floor needs: the crouched capsule, twice CrouchedHalfHeight (56 cm).
CROUCH_CLEAR_CM = round(2.0 * GAME_BODY["crouched_half_cm"], 3)
#: Neighbouring floors join in the walk graph when they differ by at most the
#: maximum jump height, DefaultJumpTuning.MaxJumpHeight (115 cm).
JUMP_CM = round(GAME_BODY["max_jump_cm"], 3)
#: Placeholder: UE's engine default walkable angle. The player's class chain
#: serializes no WalkableFloorAngle or WalkableFloorZ; its native parent's
#: default is in no export [domain:game_data/character-jump].
WALKABLE_Z = math.cos(math.radians(44.765))
#: `NavAgentProps.AgentStepHeight` of BasePlayerCharacter (45 cm); recorded, not used.
STEP_CM = round(GAME_BODY["step_cm"], 3)
#: Placeholder: under a ceiling lower than EYE_CM the eye sits this far below
#: the ceiling, standing in for the crouched eye; no field gives the gap.
CEILING_GAP_CM = 5.0
#: Placeholder: the walk graph tests pawn blockers on a line this far above
#: both floors (an invisible wall, a railing); no field gives the height.
BLOCKER_LINE_CM = 60.0
#: Placeholder: a floor counts inside the map's callout region when the point
#: this far above it lies in a region box; no field gives the height.
REGION_PROBE_CM = 50.0
PLACEHOLDERS = ["walkable_z", "ceiling_gap_cm", "blocker_line_cm", "region_probe_cm"]
#: The heights `sightlines-3d-0.2.0` used, all placeholders; kept to read its tables.
HEIGHTS_0_2_0 = {"eye_cm": 160.0, "body_cm": 120.0, "crouch_clear_cm": 100.0, "jump_cm": 120.0}
GRID_CM = 100.0
#: UE render triangles wind the other way from the right-handed cross product:
#: over Ascent, 142 of 142 first downward hits on render triangles (|nz| > 0.5)
#: faced down as stored, so they are flipped to face out; after the flip,
#: 8134 of 8146 first hits on the Weapon set face up.
RENDER_WINDING = -1
MAX_LAYERS = 16
#: Above any map's geometry; rays start here and look down.
TOP_CM = 20000.0

LEFT_OUT_LEVEL_SUFFIX = ("_Gameplay_Dynamic", "_Greybox")
LEFT_OUT_ACTOR_PREFIX = ("SpawnBarrier",)
#: Actor classes whose collision changes inside a round, found in the 13 maps'
#: always-loaded levels: TimedDoorEvac_C, Drawbridge_C, DroppableDoorCover_C,
#: Switch_BlackMarket_2_C, Switch_HiddenTemple_C, WindowShield_C,
#: RespawningWallPlate_C, RespawningPlummetShootable_C, BP_Destructible_BASE_C,
#: BP_Breakable_Simple_*_C. Ascent's and Split's always-loaded levels hold none
#: outside `Gameplay_Dynamic`, so their tables are unchanged by this rule.
STATE_CHANGING_CLASS = re.compile(r"Door|Drawbridge|^Switch_|WindowShield|^Respawning|Destructible|Breakable")
#: Parents whose subclasses change state in a round, read from their exports:
#: BP_Destructible_BASE_C's ReceiveAnyDamage calls Break.
STATE_CHANGING_ANCESTOR = frozenset({"BP_Destructible_BASE_C"})
#: A class on this native door whose default object carries this tag collapses
#: in a round: DescentBox_v5_C drops 300 cm over 1.75 s, with a crush box.
COLLAPSIBLE_DOOR = ("AresDoor", "CollapsibleDoor")
BOMB_MODE_LEVEL = re.compile(r"_(Mode_BombMode|Modes_BombMode|BombGameMode_Only)$")
QUERY_ENABLED = {"QueryOnly", "QueryAndPhysics", "ProbeOnly", "QueryAndProbe"}
#: Display name -> the game's map folder (valorant-api `mapUrl`).
CODENAMES = {"ascent": "Ascent", "split": "Bonsai", "haven": "Triad", "bind": "Duality", "icebox": "Port",
             "breeze": "Foxtrot", "fracture": "Canyon", "pearl": "Pitt", "lotus": "Jam", "sunset": "Juliett",
             "abyss": "Infinity", "summit": "Plummet", "corrode": "Rook"}
MAP_IDS = {k: f"/Game/Maps/{v}/{v}" for k, v in CODENAMES.items()}


# ------------------------------------------------------------------ compute rules

def quiet() -> None:
    """Below Normal priority and one logical CPU, so Embree's own threads stay on one core."""
    if sys.platform != "win32":
        return
    k = ctypes.windll.kernel32
    h = k.GetCurrentProcess()
    k.SetPriorityClass(h, 0x4000)
    n = os.cpu_count() or 1
    k.SetProcessAffinityMask(h, ctypes.c_size_t(1 << (n - 1)))


# ------------------------------------------------------------------ collision profiles

_PROFILE = re.compile(r'^\+(Profiles|EditProfiles)=\(Name="([^"]+)"(.*)\)\s*$')
_RESP = re.compile(r'\(Channel="([^"]+)"(?:,Response=(\w+))?\)')


def parse_profiles(ini_text: str) -> dict[str, dict]:
    """Collision profiles of DefaultEngine.ini: name -> enabled state and channel responses.

    `+Profiles` define, `+EditProfiles` amend, in file order; a response
    written without `Response=` is Block. A channel a profile does not name
    keeps its default, which is Block for every channel this probe asks about.
    """
    out: dict[str, dict] = {}
    section = False
    for line in ini_text.splitlines():
        s = line.strip()
        if s.startswith("["):
            section = s == "[/Script/Engine.CollisionProfile]"
            continue
        m = _PROFILE.match(s) if section else None
        if not m:
            continue
        kind, name, rest = m.groups()
        e = out.setdefault(name, {"enabled": None, "resp": {}})
        en = re.search(r"CollisionEnabled=(\w+)", rest)
        if en:
            e["enabled"] = en.group(1)
        cr = re.search(r"CustomResponses=\((.*)\)", rest)
        if cr:
            if kind == "Profiles":
                e["resp"] = {}
            for ch, r in _RESP.findall(cr.group(1)):
                e["resp"][ch] = r or "ECR_Block"
    return out


def _strip(v) -> str | None:
    return None if v is None else str(v).split("::")[-1]


def body_of(row: dict, mesh_default: dict | None) -> dict:
    """The BodyInstance a placed component traces with.

    With `bUseDefaultCollision` (serialised, else the StaticMeshActor default
    of true) the mesh's DefaultInstance rules; otherwise the archetype chain's
    BodyInstances merge root first and the instance's own fields override them.
    """
    udc = row.get("use_default_collision")
    if udc is None:
        udc = row.get("actor_class") == "StaticMeshActor"
    if udc:
        return dict(mesh_default or {})
    merged: dict = {}
    for t in reversed(row.get("body_templates") or []):
        merged.update(t or {})
    merged.update(row.get("body") or {})
    return merged


def effective(body: dict | None, profiles: dict, channel: str) -> bool:
    """Whether a BodyInstance blocks `channel` for traces.

    A named profile resolves through DefaultEngine.ini; a body without a name
    but with responses is `Custom`; one with neither keeps the native
    StaticMeshComponent default, BlockAll.
    """
    body = body or {}
    arr = (body.get("CollisionResponses") or {}).get("ResponseArray")
    name = body.get("CollisionProfileName") or ("Custom" if arr else "BlockAll")
    prof = profiles.get(name) if name != "Custom" else None
    enabled = _strip(body.get("CollisionEnabled"))
    if enabled is None:
        enabled = (prof or {}).get("enabled") or "QueryAndPhysics"
    if enabled not in QUERY_ENABLED:
        return False
    if prof is not None:
        resp = prof["resp"].get(channel, "ECR_Block")
    else:
        resp = {a.get("Channel"): _strip(a.get("Response")) for a in arr or []}.get(channel, "ECR_Block")
    return _strip(resp) == "ECR_Block"


# ------------------------------------------------------------------ shapes

def rotator_matrix(pitch: float, yaw: float, roll: float) -> np.ndarray:
    """UE FRotator (degrees) as a 3x3 row-vector rotation (v' = v @ M)."""
    p, y, r = (math.radians(a) for a in (pitch, yaw, roll))
    sp, cp, sy, cy, sr, cr = math.sin(p), math.cos(p), math.sin(y), math.cos(y), math.sin(r), math.cos(r)
    return np.array([[cp * cy, cp * sy, sp],
                     [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
                     [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp]])


def quat_matrix(q) -> np.ndarray:
    """Quaternion (x, y, z, w) as a 3x3 row-vector rotation."""
    x, y, z, w = (float(v) for v in q)
    n = math.sqrt(x * x + y * y + z * z + w * w) or 1.0
    x, y, z, w = x / n, y / n, z / n, w / n
    return np.array([[1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y)],
                     [2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x)],
                     [2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y)]])


_UNIT_BOX = None


def _unit_box() -> np.ndarray:
    global _UNIT_BOX
    if _UNIT_BOX is None:
        import trimesh
        _UNIT_BOX = np.asarray(trimesh.creation.box(extents=(1.0, 1.0, 1.0)).triangles)
    return _UNIT_BOX


def orient_outward(tris: np.ndarray) -> np.ndarray:
    """Wind a convex shape's triangles so each normal points away from its centroid."""
    if len(tris) == 0:
        return tris
    c = tris.reshape(-1, 3).mean(axis=0)
    n = np.cross(tris[:, 1] - tris[:, 0], tris[:, 2] - tris[:, 0])
    flip = np.einsum("ij,ij->i", n, tris.mean(axis=1) - c) < 0
    out = tris.copy()
    out[flip, 1], out[flip, 2] = tris[flip, 2], tris[flip, 1]
    return out


def simple_tris(m: dict) -> np.ndarray:
    """A mesh's simple collision as mesh-space triangles, each shape wound outward."""
    import trimesh
    parts = []
    for b in m.get("boxes") or []:
        if str(b[9]).endswith("NoCollision"):
            continue
        t = _unit_box() * np.array(b[6:9], float)
        parts.append(t @ rotator_matrix(*b[3:6]) + np.array(b[0:3], float))
    for s in m.get("spheres") or []:
        if str(s[4]).endswith("NoCollision"):
            continue
        parts.append(np.asarray(trimesh.creation.icosphere(1, radius=float(s[3])).triangles) + np.array(s[0:3], float))
    for s in m.get("sphyls") or []:
        if str(s[8]).endswith("NoCollision"):
            continue
        cap = np.asarray(trimesh.creation.capsule(height=float(s[7]), radius=float(s[6]), count=(8, 8)).triangles)
        parts.append(cap @ rotator_matrix(*s[3:6]) + np.array(s[0:3], float))
    for cv in m.get("convex") or []:
        if str(cv.get("enabled", "")).endswith("NoCollision"):
            continue
        v = np.asarray(cv["verts"], float).reshape(-1, 3)
        if len(v) < 4:
            continue
        idx = np.asarray(cv["index"], np.int64)
        if len(idx) < 3:
            from scipy.spatial import ConvexHull
            idx = ConvexHull(v).simplices.reshape(-1)
        t = v[idx.reshape(-1, 3)] * np.asarray(cv["s"], float)
        t = orient_outward(t)
        parts.append(t @ quat_matrix(cv["q"]) + np.asarray(cv["t"], float))
    return np.concatenate(parts) if parts else np.zeros((0, 3, 3))


def render_tris(m: dict, blob: np.ndarray, winding: int = 1) -> np.ndarray:
    """The collision LOD's triangles (sections with collision on), mesh space."""
    n = int(m.get("render_ntris") or 0)
    if m.get("render_offset") is None or n == 0:
        return np.zeros((0, 3, 3))
    off, nv = int(m["render_offset"]), int(m["render_nverts"])
    v = np.frombuffer(blob, np.float32, nv * 3, off).reshape(-1, 3).astype(np.float64)
    idx = np.frombuffer(blob, np.uint32, n * 3, off + nv * 12).reshape(-1, 3)
    t = v[idx]
    return t if winding > 0 else t[:, [0, 2, 1]]


def place(local: np.ndarray, mats: np.ndarray) -> np.ndarray:
    """Mesh-space triangles at every matrix (UE row-vector 4x4), winding kept outward."""
    r, tr = mats[:, :3, :3], mats[:, 3, :3]
    w = np.einsum("tvj,kji->ktvi", local, r) + tr[:, None, None, :]
    neg = np.linalg.det(r) < 0
    if neg.any():
        w[neg] = w[neg][:, :, [0, 2, 1]]
    return w.reshape(-1, 3, 3)


# ------------------------------------------------------------------ state-changing classes

def class_index(root: Path = PROPS) -> dict[str, dict]:
    """Blueprint class -> its parent's name and path and its default object's
    Tags (None where the default object sets none), from the class exports."""
    out: dict[str, dict] = {}
    if not root.is_dir():
        return out
    for f in sorted(root.rglob("*.json")):
        try:
            rows = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(rows, list):
            continue
        tags = None
        for e in rows:
            if str(e.get("Name", "")).startswith("Default__") and "Tags" in (e.get("Properties") or {}):
                tags = [str(t) for t in e["Properties"]["Tags"]]
        for e in rows:
            if e.get("Type") != "BlueprintGeneratedClass":
                continue
            sup = e.get("Super") or e.get("SuperStruct") or {}
            m = re.search(r"'([^']+)'", str(sup.get("ObjectName") or ""))
            out[str(e["Name"])] = {"super": m.group(1) if m else None,
                                   "super_path": str(sup.get("ObjectPath") or ""), "tags": tags,
                                   "file": f.relative_to(root).as_posix()}
    return out


def class_chain(cls: str, index: dict) -> tuple[list[str], bool]:
    """The class and its parents, nearest first, and whether the walk reached a
    native (`/Script/`) class; False where a parent's export is missing."""
    chain = [cls]
    while chain[-1] in index:
        row = index[chain[-1]]
        if not row["super"] or row["super"] in chain:
            return chain, False
        chain.append(row["super"])
        if row["super_path"].startswith("/Script/"):
            return chain, True
    return chain, False


def state_changing(cls: str, index: dict) -> str | None:
    """Why a placement of this class changes state in a round, or None: its
    name (`STATE_CHANGING_CLASS`), a state-changing parent, or a collapsible
    door (`COLLAPSIBLE_DOOR`), the tags read from the nearest default object
    in the chain that sets them."""
    if STATE_CHANGING_CLASS.search(cls):
        return "class name"
    chain, _ = class_chain(cls, index)
    for c in chain[1:]:
        if c in STATE_CHANGING_ANCESTOR:
            return f"subclass of {c}"
    base, tag = COLLAPSIBLE_DOOR
    if base in chain:
        tags = next((index[c]["tags"] for c in chain if c in index and index[c]["tags"] is not None), None) or []
        if tag in tags:
            return f"{base} tagged {tag}"
    return None


# ------------------------------------------------------------------ blockers

def streamed_levels(persistent: dict | list, map_name: str, available=None) -> list[str]:
    """Sublevels a match loads: the always-loaded set plus the bomb mode, whose
    name `available` (the dump's level names) settles when given."""
    names = []
    for e in persistent:
        if e.get("Type") == "LevelStreamingAlwaysLoaded":
            w = (e.get("Properties") or {}).get("WorldAsset") or {}
            p = w.get("AssetPathName", "") if isinstance(w, dict) else str(w)
            names.append(p.rsplit(".", 1)[-1])
    bomb = sorted(n for n in (available or ()) if n.startswith(map_name + "_") and BOMB_MODE_LEVEL.search(n))
    names.extend(bomb or [f"{map_name}_Mode_BombMode"])
    return sorted(set(names))


def build_blockers(dump: Path, profiles: dict, levels: list[str], complex_all: bool = False,
                   render_winding: int = RENDER_WINDING, classes: dict | None = None) -> dict:
    """World triangles with per-triangle Weapon/Pawn blocking flags and their source."""
    classes = class_index() if classes is None else classes
    inst = [json.loads(l) for l in (dump / "instances.jsonl").read_text(encoding="utf-8").splitlines() if l]
    meshes = {m["mesh"]: m for m in (json.loads(l) for l in (dump / "meshes.jsonl").read_text(encoding="utf-8").splitlines() if l)}
    blob = (dump / "render.bin").read_bytes()
    keep_lv = set(levels)
    counts = {"placements": len(inst), "level_left_out": 0, "actor_left_out": 0, "state_left_out": 0,
              "no_query": 0, "kept": 0}
    state_classes: dict[str, int] = {}
    groups: dict[tuple, list[int]] = {}
    flags = []
    for i, r in enumerate(inst):
        if r["level"] not in keep_lv or r["level"].endswith(LEFT_OUT_LEVEL_SUFFIX):
            counts["level_left_out"] += 1
            flags.append(None)
            continue
        if str(r.get("actor_class") or "").startswith(LEFT_OUT_ACTOR_PREFIX):
            counts["actor_left_out"] += 1
            flags.append(None)
            continue
        if state_changing(str(r.get("actor_class") or ""), classes):
            counts["state_left_out"] += 1
            state_classes[str(r["actor_class"])] = state_classes.get(str(r["actor_class"]), 0) + 1
            flags.append(None)
            continue
        body = body_of(r, (meshes.get(r["mesh"]) or {}).get("default_instance"))
        wb = effective(body, profiles, "Weapon")
        pb = effective(body, profiles, "Pawn")
        flags.append((wb, pb))
        if not (wb or pb):
            counts["no_query"] += 1
            continue
        counts["kept"] += 1
        groups.setdefault((r["mesh"], wb, pb), []).append(i)
    mats_all = np.array([np.asarray(r["matrix"], float).reshape(4, 4) if f else np.eye(4)
                         for r, f in zip(inst, flags)])
    tris, wfl, pfl, src = [], [], [], []
    local_cache: dict[str, tuple[np.ndarray, bool]] = {}
    cfl = []
    kinds = {"complex": 0, "simple": 0, "none": 0}
    for (mname, wb, pb), ids in groups.items():
        if mname not in local_cache:
            m = meshes[mname]
            cplx = complex_all or "UseComplexAsSimple" in str(m.get("trace_flag"))
            loc = render_tris(m, blob, render_winding) if cplx else simple_tris(m)
            if cplx and len(loc) == 0:
                loc = simple_tris(m)
            used_complex = bool(cplx and m.get("render_ntris"))
            kinds["complex" if used_complex else ("simple" if len(loc) else "none")] += 1
            local_cache[mname] = (loc, used_complex)
        loc, used_complex = local_cache[mname]
        if len(loc) == 0:
            continue
        w = place(loc, mats_all[ids])
        tris.append(w.astype(np.float32))
        wfl.append(np.full(len(w), wb))
        pfl.append(np.full(len(w), pb))
        cfl.append(np.full(len(w), used_complex))
        src.append(np.repeat(np.asarray(ids, np.int32), len(loc)))
    T = np.concatenate(tris)
    counts["state_classes"] = state_classes
    return {"tris": T, "weapon": np.concatenate(wfl), "pawn": np.concatenate(pfl),
            "src": np.concatenate(src), "complex": np.concatenate(cfl), "counts": counts, "mesh_kinds": kinds,
            "instances": inst, "meshes": meshes}


# ------------------------------------------------------------------ playable region

def region_boxes(inst: list[dict], meshes: dict, suffix: tuple = ("_Callout_Volumes", "_CalloutVolumes")) -> dict:
    """The map's callout volumes as oriented boxes: inverse matrices and mesh-space bounds.

    The callout regions name every playable area on the minimap, so a standable
    floor counts only inside one; this keeps the tops of pawn blocking volumes,
    roofs and the vista out of the floor set without any Riot position.
    """
    inv, lo, hi, names = [], [], [], []
    for r in inst:
        if not r["level"].endswith(suffix):
            continue
        t = simple_tris(meshes[r["mesh"]])
        if len(t) == 0:
            continue
        p = t.reshape(-1, 3)
        inv.append(np.linalg.inv(np.asarray(r["matrix"], float).reshape(4, 4)))
        lo.append(p.min(0))
        hi.append(p.max(0))
        names.append(str(r.get("actor")))
    return {"inv": np.array(inv), "lo": np.array(lo), "hi": np.array(hi), "names": names}


def in_region(pts: np.ndarray, reg: dict) -> np.ndarray:
    """True where a point lies inside any region box."""
    h = np.column_stack([pts, np.ones(len(pts))])
    loc = np.einsum("nj,kji->kni", h, reg["inv"])[..., :3]
    inside = ((loc >= reg["lo"][:, None, :]) & (loc <= reg["hi"][:, None, :])).all(-1)
    return inside.any(0)


# ------------------------------------------------------------------ ray casting

class Caster:
    """Embree scene over one triangle set; occlusion and first-hit queries."""

    def __init__(self, tris: np.ndarray):
        from embreex import mesh_construction, rtcore_scene
        self.tris = np.ascontiguousarray(tris, np.float32)
        self.scene = rtcore_scene.EmbreeScene()
        mesh_construction.TriangleMesh(self.scene, self.tris)
        self.region = None
        n = np.cross(self.tris[:, 1] - self.tris[:, 0], self.tris[:, 2] - self.tris[:, 0]).astype(np.float64)
        self.nz = n[:, 2] / np.maximum(np.linalg.norm(n, axis=1), 1e-12)

    def first_hit(self, o: np.ndarray, d: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        r = self.scene.run(np.ascontiguousarray(o, np.float32), np.ascontiguousarray(d, np.float32), output=1)
        return r["primID"].astype(np.int64), r["tfar"].astype(np.float64)

    def occluded(self, a: np.ndarray, b: np.ndarray, chunk: int = 2_000_000) -> np.ndarray:
        """True where the segment a->b crosses a triangle."""
        out = np.empty(len(a), bool)
        for s in range(0, len(a), chunk):
            aa, bb = a[s:s + chunk].astype(np.float64), b[s:s + chunk].astype(np.float64)
            d = bb - aa
            L = np.linalg.norm(d, axis=1)
            u = d / np.maximum(L, 1e-9)[:, None]
            r = self.scene.run(aa.astype(np.float32), u.astype(np.float32),
                               dists=np.maximum(L - 1.0, 0.0).astype(np.float32), query="OCCLUDED")
            out[s:s + chunk] = np.asarray(r) != -1
        return out


def floors(caster: Caster, xy: np.ndarray, top: float = TOP_CM) -> tuple[np.ndarray, np.ndarray]:
    """Standable floor heights under each (x, y): up to MAX_LAYERS, NaN where none.

    Downward rays from `top` record every hit; a floor is a hit on a face whose
    outward normal is walkable (nz >= WALKABLE_Z) with CROUCH_CLEAR_CM free
    above it and, when the caster carries a region, a point REGION_PROBE_CM
    (50 cm, a placeholder) above it inside one of the region's boxes (the
    map's callout volumes). Returns (z[n, MAX_LAYERS], clearance[n,
    MAX_LAYERS]), lowest first.
    """
    n = len(xy)
    z = np.full((n, MAX_LAYERS), np.nan)
    clr = np.full((n, MAX_LAYERS), np.nan)
    o = np.column_stack([xy, np.full(n, top)]).astype(np.float64)
    down = np.tile([0.0, 0.0, -1.0], (n, 1))
    up = np.tile([0.0, 0.0, 1.0], (n, 1))
    live = np.ones(n, bool)
    k = np.zeros(n, np.int64)
    for _ in range(4 * MAX_LAYERS):
        idx = np.flatnonzero(live)
        if len(idx) == 0:
            break
        prim, t = caster.first_hit(o[idx], down[idx])
        hit = prim >= 0
        live[idx[~hit]] = False
        idx, prim, t = idx[hit], prim[hit], t[hit]
        zh = o[idx, 2] - t
        walk = caster.nz[prim] >= WALKABLE_Z
        if walk.any():
            wi = idx[walk]
            p = np.column_stack([xy[wi], zh[walk] + 1.0])
            pu, tu = caster.first_hit(p, up[wi])
            free = np.where(pu >= 0, tu, np.inf)
            # an upward-facing face seen from below means the point is inside a solid
            inside = (pu >= 0) & (caster.nz[np.maximum(pu, 0)] > 0.0)
            ok = (free >= CROUCH_CLEAR_CM) & ~inside
            if caster.region is not None:
                ok &= in_region(np.column_stack([xy[wi], zh[walk] + REGION_PROBE_CM]), caster.region)
            room = k[wi] < MAX_LAYERS
            sel = ok & room
            z[wi[sel], k[wi[sel]]] = zh[walk][sel]
            clr[wi[sel], k[wi[sel]]] = np.minimum(free[sel], 1e6)
            k[wi[sel]] += 1
        o[idx, 2] = zh - 0.5
    # lowest first
    order = np.argsort(np.where(np.isnan(z), np.inf, z), axis=1)
    return np.take_along_axis(z, order, 1), np.take_along_axis(clr, order, 1)


# ------------------------------------------------------------------ grid and table

def walk_edges(cxy: np.ndarray, cz: np.ndarray, ix: np.ndarray, iy: np.ndarray, lay: np.ndarray,
               shape: tuple[int, int], pawn: Caster) -> tuple[np.ndarray, np.ndarray]:
    """Walk-graph edges (r, c), r < c in neighbour order, between standable cells.

    Cell k stands at grid column (ix[k], iy[k]) of a `shape` grid, on layer
    lay[k] at height cz[k]. It links to a cell in each of the 8 neighbouring
    columns whose floor differs by at most JUMP_CM, unless a pawn blocker
    crosses the line BLOCKER_LINE_CM (60 cm, a placeholder) above the two
    floors (an invisible wall, a railing).
    """
    n = len(cz)
    key = (ix.astype(np.int64) * shape[1] + iy) * MAX_LAYERS + lay
    order = np.argsort(key)
    skey = key[order]
    rows, cols = [], []
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            if (dx, dy) <= (0, 0):
                continue
            jx, jy = ix + dx, iy + dy
            okc = (jx >= 0) & (jx < shape[0]) & (jy >= 0) & (jy < shape[1])
            for L in range(MAX_LAYERS):
                k2 = (jx.astype(np.int64) * shape[1] + jy) * MAX_LAYERS + L
                pos = np.clip(np.searchsorted(skey, k2), 0, n - 1)
                found = okc & (skey[pos] == k2)
                j = order[pos]
                good = found & (np.abs(cz[j] - cz) <= JUMP_CM)
                rows.append(np.flatnonzero(good))
                cols.append(j[good])
    r = np.concatenate(rows)
    c = np.concatenate(cols)
    a3 = np.column_stack([cxy[r], cz[r] + BLOCKER_LINE_CM])
    b3 = np.column_stack([cxy[c], cz[c] + BLOCKER_LINE_CM])
    walk = ~pawn.occluded(a3, b3)
    return r[walk], c[walk]


def grid_cells(pawn: Caster, lo: np.ndarray, hi: np.ndarray, step: float = GRID_CM) -> dict:
    """Standable cells on a `step` grid inside [lo, hi] and the caster's region.

    Cells link to their 8 neighbours when the floors differ by at most JUMP_CM
    and no pawn blocker crosses the line BLOCKER_LINE_CM above them; the components are
    reported, not used to drop cells.
    """
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    xs = np.arange(lo[0] + step / 2, hi[0], step)
    ys = np.arange(lo[1] + step / 2, hi[1], step)
    gx, gy = np.meshgrid(xs, ys, indexing="ij")
    xy = np.column_stack([gx.ravel(), gy.ravel()])
    z, clr = floors(pawn, xy)
    col, lay = np.nonzero(~np.isnan(z))
    cz = z[col, lay]
    ix, iy = np.unravel_index(col, gx.shape)
    n = len(cz)
    r, c = walk_edges(xy[col], cz, ix, iy, lay, gx.shape, pawn)
    g = coo_matrix((np.ones(len(r), np.int8), (r, c)), shape=(n, n))
    ncomp, lab = connected_components(g, directed=False)
    sizes = np.bincount(lab)
    keep = np.ones(n, bool)  # every standable cell in the region; components only reported
    return {"walk_r": r.astype(np.int32), "walk_c": c.astype(np.int32),
            "xy": xy[col[keep]].astype(np.float32), "z": cz[keep].astype(np.float32),
            "clear": clr[col, lay][keep].astype(np.float32), "ix": ix[keep].astype(np.int32),
            "iy": iy[keep].astype(np.int32), "layer": lay[keep].astype(np.int8),
            "grid_lo": lo, "grid_hi": hi, "n_standable": int(n), "n_components": int(ncomp),
            "largest_component_share": float(sizes.max() / max(n, 1)), "component": lab.astype(np.int32)}


def eye_points(xy: np.ndarray, z: np.ndarray, clear: np.ndarray, h: float = EYE_CM) -> np.ndarray:
    """A point `h` above each floor, lowered under a low ceiling to
    CEILING_GAP_CM (5 cm, a placeholder for the crouched eye) below it."""
    hh = np.minimum(h, np.maximum(np.asarray(clear, float) - CEILING_GAP_CM, 1.0))
    return np.column_stack([xy, np.asarray(z, float) + hh])


def table(weapon: Caster, pts: np.ndarray, rows_per_chunk: int = 256) -> np.ndarray:
    """Packed upper-triangle visibility bits (i < j, row-major) of `pts`."""
    n = len(pts)
    total = n * (n - 1) // 2
    bits = np.zeros(total, bool)
    pos = 0
    for i0 in range(0, n - 1, rows_per_chunk):
        i1 = min(n - 1, i0 + rows_per_chunk)
        ii = np.arange(i0, i1)
        counts = n - 1 - ii
        a = np.repeat(ii, counts)
        start = np.repeat(ii + 1 - np.concatenate([[0], np.cumsum(counts)[:-1]]), counts)
        b = start + np.arange(len(a))
        vis = ~weapon.occluded(pts[a], pts[b])
        bits[pos:pos + len(a)] = vis
        pos += len(a)
    return np.packbits(bits)


def pair_index(i: np.ndarray, j: np.ndarray, n: int) -> np.ndarray:
    """Position of pair (i, j), i != j, in the row-major upper triangle."""
    a, b = np.minimum(i, j).astype(np.int64), np.maximum(i, j).astype(np.int64)
    return a * (2 * n - a - 1) // 2 + (b - a - 1)


def visible(bits: np.ndarray, i: np.ndarray, j: np.ndarray, n: int) -> np.ndarray:
    k = pair_index(i, j, n)
    return ((bits[k >> 3] >> (7 - (k & 7))) & 1).astype(bool) | (np.asarray(i) == np.asarray(j))


# ------------------------------------------------------------------ commands

def table_version(map_name: str) -> str:
    """The version whose table stands for the map at this `VERSION`."""
    return VERSION if map_name in REBUILT else PREVIOUS


def out_path(map_name: str, version: str | None = None) -> Path:
    """The map's table: of `version`, else of the version that stands for it."""
    return STORE / "sightlines" / f"{map_name}__{version or table_version(map_name)}.npz"


def extractor_commit(root: Path = EXTRACTOR) -> dict:
    """The extractor repository's HEAD commit, read from its repository files."""
    g = root / ".git"
    try:
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if head.startswith("ref: "):
            ref = head[5:]
            f = g / ref
            if f.is_file():
                sha = f.read_text(encoding="utf-8").strip()
            else:
                packed = (g / "packed-refs").read_text(encoding="utf-8").splitlines()
                sha = next(ln.split()[0] for ln in packed if ln.endswith(" " + ref))
        else:
            sha = head
        return {"repo": "reticle-store/tools/game-extract", "commit": sha}
    except (OSError, StopIteration):
        return {"repo": "reticle-store/tools/game-extract", "commit": None}


def cell_callouts(xy: np.ndarray, z: np.ndarray, reg: dict) -> np.ndarray:
    """Each cell's callout volume (index into the region names), -1 outside all:
    the smallest volume holding the point REGION_PROBE_CM above the floor."""
    p = np.column_stack([xy, np.asarray(z, float) + REGION_PROBE_CM])
    h = np.column_stack([p, np.ones(len(p))])
    out = np.full(len(p), -1, np.int16)
    if len(reg["inv"]) == 0:
        return out
    scale = np.linalg.norm(np.linalg.inv(reg["inv"])[:, :3, :3], axis=2)
    vol = np.prod(np.abs(reg["hi"] - reg["lo"]) * scale, axis=1)
    best = np.full(len(p), np.inf)
    for k in range(len(reg["inv"])):
        loc = (h @ reg["inv"][k])[:, :3]
        inside = ((loc >= reg["lo"][k]) & (loc <= reg["hi"][k])).all(1) & (vol[k] < best)
        out[inside] = k
        best[inside] = vol[k]
    return out


def heights() -> dict:
    """The body heights a table is built and gated with, and where each comes from."""
    return {"eye_cm": EYE_CM, "body_cm": BODY_CM, "crouch_clear_cm": CROUCH_CLEAR_CM, "jump_cm": JUMP_CM,
            "walkable_z": WALKABLE_Z, "step_cm": STEP_CM, "ceiling_gap_cm": CEILING_GAP_CM,
            "blocker_line_cm": BLOCKER_LINE_CM, "region_probe_cm": REGION_PROBE_CM,
            "placeholders": list(PLACEHOLDERS),
            "sources": {"eye_cm": "CapsuleHalfHeight + BaseEyeHeight [domain:game_data/character-eye-height]",
                        "body_cm": "CapsuleHalfHeight, the capsule centre [domain:game_data/character-eye-height]",
                        "crouch_clear_cm": "2 x CrouchedHalfHeight [domain:game_data/character-eye-height]",
                        "jump_cm": "DefaultJumpTuning.MaxJumpHeight [domain:game_data/character-jump]",
                        "step_cm": "NavAgentProps.AgentStepHeight [domain:game_data/character-eye-height]",
                        "walkable_z": "placeholder: UE engine default 44.765 degrees; no field "
                                      "[domain:game_data/character-jump]",
                        "ceiling_gap_cm": "placeholder: the eye's gap below a low ceiling, for the "
                                          "crouched eye; no field",
                        "blocker_line_cm": "placeholder: the walk graph's pawn-blocker line; no field",
                        "region_probe_cm": "placeholder: the callout-region probe above a floor; "
                                           "no field"}}


def cmd_build(a) -> int:
    quiet()
    t0 = time.perf_counter()
    profiles = parse_profiles(Path(a.ini).read_text(encoding="utf-8", errors="replace"))
    persistent = json.loads(Path(a.persistent).read_text(encoding="utf-8"))
    mname = CODENAMES[a.map]
    available = {json.loads(ln)["level"] for ln in (Path(a.dump) / "instances.jsonl").read_text(encoding="utf-8").splitlines() if ln}
    levels = streamed_levels(persistent, mname, available)
    B = build_blockers(Path(a.dump), profiles, levels, complex_all=a.complex_all)
    t1 = time.perf_counter()
    reg = region_boxes(B["instances"], B["meshes"])
    src_meta = [{"level": r["level"], "actor": r.get("actor"), "actor_class": r.get("actor_class"),
                 "mesh": r["mesh"].rsplit("/", 1)[-1]} for r in B["instances"]]
    base = {"levels": levels, "counts": B["counts"], "complex_all": a.complex_all, "mesh_kinds": B["mesh_kinds"],
            "source": {"dump": str(a.dump), "ini": str(a.ini), "persistent": str(a.persistent),
                       "build": a.build, "extractor": extractor_commit(),
                       "extractor_command": 'game-extract meshes "ShooterGame/Content/Maps/<Map>/<Map>*.umap"'}}
    return finish_build(a, B["tris"], B["weapon"], B["pawn"], B["src"], src_meta, reg, base, t0, t1)


def cmd_rebuild(a) -> int:
    """A table from an older table's stored blockers and callout volumes, with
    this version's body heights. The blocker set does not depend on the
    heights, so no extraction reruns; the provenance names the source table."""
    quiet()
    t0 = time.perf_counter()
    src_path = Path(a.source)
    D = load(a.map, src_path)
    old = D["provenance"]
    if old.get("map") != a.map:
        raise SystemExit(f"{src_path} holds {old.get('map')}, not {a.map}")
    base = {k: old[k] for k in ("levels", "complex_all", "mesh_kinds", "source")}
    base["rebuilt_from"] = {"path": str(src_path), "version": old.get("version"),
                            "heights": {k: old.get(k) for k in ("eye_cm", "chest_cm", "crouch_clear_cm",
                                                                 "walkable_z", "jump_cm")}}
    drop = state_props(D, class_index())
    counts = dict(old["counts"], state_classes=dict(old["counts"].get("state_classes") or {}))
    for cls, row in drop["left_out"].items():
        counts["state_classes"][cls] = counts["state_classes"].get(cls, 0) + row["placements"]
        counts["state_left_out"] += row["placements"]
        counts["kept"] -= row["placements"]
    base["counts"] = counts
    base["rebuild_left_out"] = drop["left_out"]
    keep = ~np.isin(D["src"], np.asarray(drop["placements"], np.int64))
    t1 = time.perf_counter()
    return finish_build(a, D["tris"][keep], D["weapon"][keep], D["pawn"][keep], D["src"][keep], D["src_meta"],
                        D["region"], base, t0, t1)


def state_props(D: dict, classes: dict) -> dict:
    """The placements in a stored table's blockers whose class `state_changing`
    leaves out, by class with the reason, and the kept classes whose parent
    chain stops at a missing export (the test read only their names)."""
    meta = D["src_meta"]
    src = np.asarray(D["src"])
    used, n_tris = np.unique(src, return_counts=True)
    left: dict[str, dict] = {}
    placements: list[int] = []
    unread: dict[str, int] = {}
    for i, n in zip(used.tolist(), n_tris.tolist()):
        cls = str(meta[i].get("actor_class") or "")
        why = state_changing(cls, classes)
        if why:
            row = left.setdefault(cls, {"reason": why, "placements": 0, "triangles": 0,
                                        "chain": class_chain(cls, classes)[0]})
            row["placements"] += 1
            row["triangles"] += int(n)
            placements.append(i)
        elif cls in classes and not class_chain(cls, classes)[1]:
            unread[cls] = unread.get(cls, 0) + 1
    return {"left_out": left, "placements": placements, "unread_chain": unread}


def cmd_state_props(a) -> int:
    """Per map, what `state_changing` removes from the stored tables of `--version`."""
    quiet()
    classes = class_index()
    out = {"version": VERSION, "tables": a.version, "classes_read": len(classes), "maps": {}}
    for m in sorted(CODENAMES):
        p = out_path(m, a.version)
        if not p.is_file():
            out["maps"][m] = None
            continue
        D = load(m, p)
        r = state_props(D, classes)
        meta = D["src_meta"]
        placed = {str(meta[i].get("actor_class") or "") for i in np.unique(D["src"]).tolist()}
        out["maps"][m] = {"left_out": r["left_out"], "unread_chain": r["unread_chain"],
                          "blueprint_classes_without_export": sorted(c for c in placed - set(classes)
                                                                     if c.endswith("_C"))}
    out["changed"] = sorted(m for m, r in out["maps"].items() if r and r["left_out"])
    print(json.dumps(out, indent=1))
    return 0


def finish_build(a, T, weapon, pawn, src, src_meta, reg, base: dict, t0: float, t1: float) -> int:
    """Grid, walk graph, callouts and the visibility table over a blocker set; write and record."""
    wcast = Caster(T[weapon])
    pcast = Caster(T[pawn])
    pcast.region = reg
    t2 = time.perf_counter()
    # grid bounds: the callout volumes' corners
    corners = np.array([[x, y, z] for x in (0, 1) for y in (0, 1) for z in (0, 1)], float)
    pts = []
    for k in range(len(reg["inv"])):
        c = reg["lo"][k] + corners * (reg["hi"][k] - reg["lo"][k])
        m = np.linalg.inv(reg["inv"][k])
        pts.append(c @ m[:3, :3] + m[3, :3])
    pts = np.concatenate(pts)
    lo = np.floor(pts[:, :2].min(0) / GRID_CM) * GRID_CM
    hi = np.ceil(pts[:, :2].max(0) / GRID_CM) * GRID_CM
    G = grid_cells(pcast, lo, hi)
    t3 = time.perf_counter()
    callout = cell_callouts(G["xy"], G["z"], reg)
    eyes = eye_points(G["xy"], G["z"], G["clear"], EYE_CM)
    bits = table(wcast, eyes) if not a.no_table else np.zeros(0, np.uint8)
    t4 = time.perf_counter()
    H = heights()
    prov = {"version": VERSION, "map": a.map,
            **{k: base[k] for k in ("levels", "counts", "complex_all", "mesh_kinds")},
            **{k: H[k] for k in ("eye_cm", "body_cm", "crouch_clear_cm", "walkable_z", "jump_cm")},
            "grid_cm": GRID_CM, "placeholders": H["placeholders"], "height_sources": H["sources"],
            "source": base["source"],
            "step_cm": STEP_CM, "step_cm_source": "BasePlayerCharacter CharMoveComp NavAgentProps.AgentStepHeight",
            "walk_edges": int(len(G["walk_r"])), "cells_in_callout": int((callout >= 0).sum()),
            "seconds": {"blockers": t1 - t0, "bvh": t2 - t1, "grid": t3 - t2, "table": t4 - t3},
            "n_cells": int(len(G["z"])), "n_standable": G["n_standable"], "n_components": G["n_components"],
            "largest_component_share": G["largest_component_share"],
            "n_tris": int(len(T)), "n_weapon_tris": int(weapon.sum()), "n_pawn_tris": int(pawn.sum())}
    if "rebuilt_from" in base:
        prov["rebuilt_from"] = base["rebuilt_from"]
    if "rebuild_left_out" in base:
        prov["rebuild_left_out"] = base["rebuild_left_out"]
    prov["state_classes_from"] = {"props": str(PROPS), "rule": "STATE_CHANGING_CLASS, STATE_CHANGING_ANCESTOR "
                                                                "and COLLAPSIBLE_DOOR over class_chain"}
    op = Path(a.out) if a.out else out_path(a.map, VERSION)
    op.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(op, tris=T, weapon=weapon, pawn=pawn, src=src,
                        src_meta=json.dumps(src_meta), cell_xy=G["xy"], cell_z=G["z"], cell_clear=G["clear"],
                        cell_ix=G["ix"], cell_iy=G["iy"], cell_layer=G["layer"], cell_component=G["component"], grid_lo=lo, grid_hi=hi,
                        vis_bits=bits, walk_r=G["walk_r"], walk_c=G["walk_c"], cell_callout=callout,
                        region_inv=reg["inv"], region_lo=reg["lo"], region_hi=reg["hi"],
                        region_names=json.dumps(reg["names"]), provenance=json.dumps(prov))
    prov["bytes"] = op.stat().st_size
    print(json.dumps(prov, indent=1))
    if a.record:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from reticle import metrics
        vals = {k: prov[k] for k in ("n_cells", "n_components", "largest_component_share", "n_tris",
                                     "n_weapon_tris", "n_pawn_tris", "bytes")}
        vals.update({f"seconds_{k}": v for k, v in prov["seconds"].items()})
        vals["seconds_total"] = sum(prov["seconds"].values())
        vals["pairs"] = prov["n_cells"] * (prov["n_cells"] - 1) // 2
        vals["placements_kept"] = prov["counts"]["kept"]
        metrics.record("sightlines_3d", part=f"build/{a.map}", values=vals,
                       deps={"version": VERSION, "geometry": prov["source"].get("build"), "grid_cm": GRID_CM,
                             "eye_cm": EYE_CM, "body_cm": BODY_CM, "crouch_clear_cm": CROUCH_CLEAR_CM,
                             "jump_cm": JUMP_CM, "extractor": (prov["source"].get("extractor") or {}).get("commit")},
                       context={"out": str(op), "levels": len(prov["levels"]),
                                "rebuilt_from": (prov.get("rebuilt_from") or {}).get("version")},
                       note="one core (affinity), Below Normal; timings shared the CPU with other workflows")
    return 0


def load(map_name: str, path: Path | None = None) -> dict:
    with np.load(path or out_path(map_name), allow_pickle=False) as z:
        d = {k: z[k] for k in z.files}
    d["provenance"] = json.loads(str(d["provenance"]))
    d["src_meta"] = json.loads(str(d["src_meta"]))
    d["region"] = {"inv": d["region_inv"], "lo": d["region_lo"], "hi": d["region_hi"],
                   "names": json.loads(str(d["region_names"]))}
    return d


def pick_floor(z: np.ndarray, clr: np.ndarray, rule: str = "lowest") -> tuple[np.ndarray, np.ndarray]:
    """One floor per position from its standable layers; NaN where none."""
    has = ~np.isnan(z)
    first = np.argmax(has, axis=1)
    if rule == "highest":
        first = MAX_LAYERS - 1 - np.argmax(has[:, ::-1], axis=1)
    r = np.arange(len(z))
    return z[r, first], clr[r, first]


def pick_floor_component(xy: np.ndarray, z: np.ndarray, clr: np.ndarray, D: dict) -> tuple[np.ndarray, np.ndarray]:
    """Post hoc: the layer whose grid cell joins the largest walkable component, else the lowest.

    A roof or a canopy top inside a tall callout volume forms its own small
    component; the floor players walk on joins the big one.
    """
    comp = D["cell_component"]
    big = np.bincount(comp).argmax()
    ix = np.floor((xy[:, 0] - D["grid_lo"][0]) / GRID_CM).astype(np.int64)
    iy = np.floor((xy[:, 1] - D["grid_lo"][1]) / GRID_CM).astype(np.int64)
    ny = int(D["cell_iy"].max()) + 2
    ckey = D["cell_ix"].astype(np.int64) * ny + D["cell_iy"]
    order = np.argsort(ckey, kind="stable")
    sk = ckey[order]
    pz, pc = pick_floor(z, clr)
    best = np.full(len(xy), np.inf)
    for L in range(MAX_LAYERS):
        zl = z[:, L]
        if np.isnan(zl).all():
            continue
        k = ix * ny + iy
        lo_ = np.searchsorted(sk, k, "left")
        hi_ = np.searchsorted(sk, k, "right")
        for off in range(int((hi_ - lo_).max(initial=0))):
            j = np.minimum(lo_ + off, len(sk) - 1)
            valid = (lo_ + off < hi_) & ~np.isnan(zl)
            cell = order[j]
            match = valid & (np.abs(D["cell_z"][cell] - zl) < 150.0) & (comp[cell] == big) & (zl < best)
            best[match] = zl[match]
            pc[match] = clr[match, L]
    pz = np.where(np.isfinite(best), best, pz)
    return pz, pc


def nearest_floors(caster: Caster, xy: np.ndarray, radius: float = 100.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Floors at each (x, y), else at the nearest of 8 points `radius` away. Returns z, clear, moved."""
    z, clr = floors(caster, xy)
    moved = np.zeros(len(xy), bool)
    miss = np.isnan(z).all(axis=1)
    for ang in np.radians(np.arange(0, 360, 45)):
        if not miss.any():
            break
        idx = np.flatnonzero(miss)
        p = xy[idx] + radius * np.array([math.cos(ang), math.sin(ang)])
        z2, c2 = floors(caster, p)
        got = ~np.isnan(z2).all(axis=1)
        z[idx[got]], clr[idx[got]] = z2[got], c2[got]
        moved[idx[got]] = True
        miss[idx[got]] = False
    return z, clr, moved


def dev_kills(map_name: str) -> tuple[list[dict], dict]:
    """Development-set kills on `map_name` (the 22 captured matches' Riot records)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import riot_ground_truth as rg
    return kills_of(rg.riot_records(STORE), map_name)


def confirm_kills(map_name: str) -> tuple[list[dict], dict, dict]:
    """Confirmation-history kills on `map_name`, for an instrument check only.

    `engagement_reach.ladder_records` drops the held-out replay matches and the
    captured ones; the ladder's `holdout` matches (one in five, docs/LADDER_SAMPLE.md)
    are dropped here as well. Returns (kills, per-match counts, exclusions)."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import engagement_reach as er
    import pyarrow.parquet as pq
    records, _me, counts = er.ladder_records({map_name})
    hold = {r["match_id"] for r in pq.read_table(er.LADDER / "matches.parquet",
                                                 columns=["match_id", "holdout"]).to_pylist() if r["holdout"]}
    kept = {k: v for k, v in records.items() if k not in hold}
    ex = {"matches_on_map": len(records), "holdout_excluded": len(records) - len(kept),
          "held_out_replay_excluded_all_maps": counts.get("held_out_excluded", 0),
          "captured_excluded_all_maps": counts.get("captured_excluded", 0)}
    out, per = kills_of({k: {"match": v["match"]} for k, v in kept.items()}, map_name)
    return out, per, ex


def kills_of(recs: dict, map_name: str) -> tuple[list[dict], dict]:
    """Kills on `map_name` from Riot-shaped records."""
    out, per = [], {}
    for sid, d in recs.items():
        m = d["match"]
        if m["matchInfo"].get("mapId") != MAP_IDS[map_name]:
            continue
        ks = m.get("kills") or []
        per[sid] = len(ks)
        team = {p["subject"]: p.get("teamId") for p in m.get("players") or []}
        for k in ks:
            loc = {p["subject"]: p["location"] for p in k.get("playerLocations") or []}
            kl = loc.get(k.get("killer"))
            kt = team.get(k.get("killer"))
            others = [(v["x"], v["y"]) for s_, v in loc.items()
                      if kt is not None and team.get(s_) not in (None, kt) and s_ != k.get("victim")]
            out.append({"sid": sid, "others_xy": others, "weapon": (k.get("finishingDamage") or {}).get("damageType") == "Weapon",
                        "killer_xy": (kl["x"], kl["y"]) if kl else None,
                        "victim_xy": (k["victimLocation"]["x"], k["victimLocation"]["y"]) if k.get("victimLocation") else None,
                        "all_xy": [(p["location"]["x"], p["location"]["y"]) for p in k.get("playerLocations") or []]
                        + ([(k["victimLocation"]["x"], k["victimLocation"]["y"])] if k.get("victimLocation") else [])})
    return out, per


FRAMES = {"identity": lambda x, y: (x, y), "swap": lambda x, y: (y, x),
          "neg_x": lambda x, y: (-x, y), "neg_y": lambda x, y: (x, -y), "neg_both": lambda x, y: (-x, -y)}


def frame_scores(pcast: Caster, xy: np.ndarray) -> dict:
    """Share of positions with a standable floor in the column, per candidate frame."""
    out = {}
    for name, f in FRAMES.items():
        x, y = f(xy[:, 0], xy[:, 1])
        p = np.column_stack([x, y])
        z, _ = floors(pcast, p)
        zn, _, moved = nearest_floors(pcast, p)
        out[name] = {"on_floor": float((~np.isnan(z).all(1)).mean()),
                     "within_1m": float((~np.isnan(zn).all(1)).mean())}
    return out


def los_2d(kills: list[dict], ok: np.ndarray, map_name: str, boxes_block: bool = True) -> np.ndarray:
    """2D line of sight on each kill's own baked widget geometry; NaN where unavailable."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import riot_ground_truth as rg
    from reticle import cone, geometry
    ref = rg.Reference(STORE / "external" / "valorant-api", fetch=False)
    recs = rg.riot_records(STORE)
    res = np.full(len(kills), np.nan)
    by_sid: dict[str, list[int]] = {}
    for i, k in enumerate(kills):
        if ok[i]:
            by_sid.setdefault(k["sid"], []).append(i)
    for sid, ids in by_sid.items():
        mf, why = rg.map_frame_for(sid, None, ref, recs[sid], STORE)
        gp = geometry.path_of(sid, STORE)
        if mf is None or gp is None:
            continue
        with np.load(gp) as z:
            labels, occ = z["labels"], z["occ"] if "occ" in z.files else None
        floor = geometry.footprint(sid, STORE, shape=labels.shape)
        if floor is None:
            continue
        passable = cone.passable_from(labels, floor, occ, boxes_block=boxes_block)
        a = np.array([mf.to_px(*kills[i]["killer_xy"]) for i in ids])
        b = np.array([mf.to_px(*kills[i]["victim_xy"]) for i in ids])
        L = np.linalg.norm(b - a, axis=1)
        t = np.linspace(0.0, 1.0, 400)
        p = a[:, None, :] + t[None, :, None] * (b - a)[:, None, :]
        # a cell lookup in the mask, not a resample: the pixel holding each point
        px = np.clip(np.floor(p[..., 0] + 0.5).astype(int), 0, labels.shape[1] - 1)
        py = np.clip(np.floor(p[..., 1] + 0.5).astype(int), 0, labels.shape[0] - 1)
        inner = (t[None, :] * L[:, None] > 2.0) & ((1 - t[None, :]) * L[:, None] > 2.0)
        blocked = (~passable[py, px] & inner).any(axis=1)
        res[ids] = (~blocked).astype(float)
    return res


def cmd_gate(a) -> int:
    quiet()
    t0 = time.perf_counter()
    D = load(a.map, Path(a.npz) if a.npz else None)
    T = D["tris"]
    wcast = Caster(T[D["weapon"]])
    pcast = Caster(T[D["pawn"]])
    pcast.region = D["region"]
    exclusions = {}
    if a.set == "dev":
        kills, per = dev_kills(a.map)
    else:
        kills, per, exclusions = confirm_kills(a.map)
    allpos = np.array([p for k in kills for p in k["all_xy"]], float)
    fs = frame_scores(pcast, allpos)
    # the frame: identity (S1); every number below uses it
    z_all, c_all, moved_all = nearest_floors(pcast, allpos)
    n_layers = (~np.isnan(z_all)).sum(1)
    gun = [k for k in kills if k["weapon"] and k["killer_xy"] and k["victim_xy"]]
    kxy = np.array([k["killer_xy"] for k in gun], float)
    vxy = np.array([k["victim_xy"] for k in gun], float)
    kz, kc, km = nearest_floors(pcast, kxy)
    vz, vc, vm = nearest_floors(pcast, vxy)
    kf, kcl = pick_floor(kz, kc)
    vf, vcl = pick_floor(vz, vc)
    ok = ~np.isnan(kf) & ~np.isnan(vf)
    eye = eye_points(kxy[ok], kf[ok], kcl[ok], EYE_CM)
    body = eye_points(vxy[ok], vf[ok], vcl[ok], BODY_CM)
    head = eye_points(vxy[ok], vf[ok], vcl[ok], EYE_CM)
    los = np.full(len(gun), np.nan)
    los[ok] = (~wcast.occluded(eye, body)).astype(float)
    los_head = np.full(len(gun), np.nan)
    los_head[ok] = (~wcast.occluded(eye, head)).astype(float)
    # post hoc: any standable floor pair (an upper bound over the multi-level choice)
    any_pair = np.full(len(gun), np.nan)
    idx = np.flatnonzero(ok)
    acc = np.zeros(len(idx), bool)
    for li in range(MAX_LAYERS):
        for lj in range(MAX_LAYERS):
            zz, zc = kz[idx, li], vz[idx, lj]
            g = ~np.isnan(zz) & ~np.isnan(zc)
            if not g.any():
                continue
            e = eye_points(kxy[idx][g], zz[g], kc[idx, li][g], EYE_CM)
            c = eye_points(vxy[idx][g], zc[g], vc[idx, lj][g], BODY_CM)
            acc[np.flatnonzero(g)] |= ~wcast.occluded(e, c)
    any_pair[idx] = acc
    l2 = los_2d(gun, ok, a.map) if a.set == "dev" else np.full(len(gun), np.nan)
    both = ok & ~np.isnan(l2)
    # post hoc: the multi-level choice by walkable component
    kf2, kcl2 = pick_floor_component(kxy, kz, kc, D)
    vf2, vcl2 = pick_floor_component(vxy, vz, vc, D)
    ok2 = ~np.isnan(kf2) & ~np.isnan(vf2)
    los_comp = np.full(len(gun), np.nan)
    los_comp[ok2] = ~wcast.occluded(eye_points(kxy[ok2], kf2[ok2], kcl2[ok2], EYE_CM),
                                     eye_points(vxy[ok2], vf2[ok2], vcl2[ok2], BODY_CM))
    # post hoc control: the killer against every other living opponent at the same instant
    ci = np.array([i for i, k in enumerate(gun) for _ in k["others_xy"]], np.int64)
    oxy = np.array([o for k in gun for o in k["others_xy"]], float).reshape(-1, 2)
    oz, oc, _ = nearest_floors(pcast, oxy)
    of, ocl = pick_floor(oz, oc)
    okc = ok[ci] & ~np.isnan(of)
    ctrl3 = ~wcast.occluded(eye_points(kxy[ci[okc]], kf[ci[okc]], kcl[ci[okc]], EYE_CM),
                            eye_points(oxy[okc], of[okc], ocl[okc], BODY_CM))
    ctrl_kills = [dict(gun[i], victim_xy=tuple(oxy[j])) for j, i in enumerate(ci)]
    ctrl2 = los_2d(ctrl_kills, okc, a.map) if a.set == "dev" else np.full(len(ctrl_kills), np.nan)
    tver = D["provenance"].get("version") or VERSION
    res = {
        "version": tver, "map": a.map, "set": a.set, "matches": len(per), "kills": len(kills),
        "dev_matches": len(per) if a.set == "dev" else 0, "dev_kills": len(kills) if a.set == "dev" else 0,
        "held_out_excluded": 0, "exclusions": exclusions, "frames": fs,
        "positions": int(len(allpos)),
        "on_floor_identity": float((~np.isnan(floors(pcast, allpos)[0]).all(1)).mean()),
        "within_1m_identity": float((~np.isnan(z_all).all(1)).mean()),
        "multi_level_share": float((n_layers >= 2).mean()),
        "gun_kills": len(gun), "gun_kills_resolved": int(ok.sum()),
        "los3d_share": float(np.nanmean(los)), "los3d_head_share": float(np.nanmean(los_head)),
        "los3d_any_pair_share": float(np.nanmean(any_pair)),
        "los2d_n": int(both.sum()), "los2d_share": float(np.nanmean(l2[both])) if both.any() else None,
        "los3d_share_on_2d_set": float(np.nanmean(los[both])) if both.any() else None,
        "agree_share": float((los[both] == l2[both]).mean()) if both.any() else None,
        "d3clear_d2blocked": int(((los == 1) & (l2 == 0) & both).sum()),
        "d3blocked_d2clear": int(((los == 0) & (l2 == 1) & both).sum()),
        "los3d_component_floor_share": float(np.nanmean(los_comp)),
        "control_pairs": int(okc.sum()),
        "control_los3d_share": float(ctrl3.mean()) if len(ctrl3) else None,
        "control_los2d_share": float(np.nanmean(ctrl2[okc])) if okc.any() and a.set == "dev" else None,
        "seconds": time.perf_counter() - t0,
    }
    print(json.dumps(res, indent=1))
    if a.disagreements:
        dis = np.flatnonzero(both & (los != l2))
        rows = []
        for i in dis[: a.disagreements]:
            e = eye_points(kxy[i:i + 1], kf[i:i + 1], kcl[i:i + 1], EYE_CM)[0]
            c = eye_points(vxy[i:i + 1], vf[i:i + 1], vcl[i:i + 1], BODY_CM)[0]
            d = c - e
            L = float(np.linalg.norm(d))
            prim, t = wcast.first_hit(e[None], (d / L)[None])
            hit = None
            if prim[0] >= 0 and t[0] < L:
                wi = np.flatnonzero(D["weapon"])[prim[0]]
                hit = dict(D["src_meta"][int(D["src"][wi])], at_cm=round(float(t[0])), of_cm=round(L),
                           hit_z=round(float(e[2] + d[2] / L * t[0])))
            rows.append({"i": int(i), "los3d": int(los[i]), "los2d": int(l2[i]), "dist_m": round(L / 100, 1),
                         "killer_floor": round(float(kf[i])), "victim_floor": round(float(vf[i])),
                         "killer_layers": int((~np.isnan(kz[i])).sum()), "victim_layers": int((~np.isnan(vz[i])).sum()),
                         "killer_xy": [round(v) for v in kxy[i]], "victim_xy": [round(v) for v in vxy[i]],
                         "sid": gun[i]["sid"][:6], "first_3d_hit": hit})
        print(json.dumps(rows, indent=1))
    if a.record:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
        from reticle import metrics
        vals = {k: v for k, v in res.items() if isinstance(v, (int, float)) and v is not None}
        for fname, s in fs.items():
            vals[f"frame_{fname}_on_floor"] = s["on_floor"]
            vals[f"frame_{fname}_within_1m"] = s["within_1m"]
        vals.update({f"exclusions.{k}": v for k, v in exclusions.items()})
        part = f"gate/{a.map}" if a.set == "dev" else f"gate_confirm/{a.map}"
        note = ("development set only (22 captured matches); post-hoc: los3d_head_share, los3d_any_pair_share, "
                "los3d_component_floor_share, control_*") if a.set == "dev" else (
            "instrument check only on confirmation-history kills (no development kills on this map; no hypothesis "
            "scored); held-out replay, captured and ladder holdout matches excluded; control_* post hoc")
        metrics.record("sightlines_3d", part=part, values=vals,
                       deps={"version": tver, "geometry": D["provenance"].get("source", {}).get("build"),
                             "extractor": D["provenance"].get("source", {}).get("extractor", {}).get("commit"),
                             "eye_cm": EYE_CM, "body_cm": BODY_CM},
                       context={"placeholders": D["provenance"]["placeholders"], "set": a.set,
                                "table_version": D["provenance"].get("version")},
                       note=note)
    return 0


def _self_test() -> int:
    """A synthetic room: floor, a wall with a gap, a platform; profiles; table packing."""
    import trimesh
    ini = ("[/Script/Engine.CollisionProfile]\n"
           '+Profiles=(Name="BlockAll",CollisionEnabled=QueryAndPhysics,CustomResponses=)\n'
           '+Profiles=(Name="InvisibleWall",CollisionEnabled=QueryAndPhysics,CustomResponses=((Channel="Visibility",Response=ECR_Ignore)))\n'
           '+EditProfiles=(Name="InvisibleWall",CustomResponses=((Channel="Weapon",Response=ECR_Ignore),(Channel="Level")))\n'
           '+Profiles=(Name="NoCollision",CollisionEnabled=NoCollision,CustomResponses=)\n')
    P = parse_profiles(ini)
    assert effective({"CollisionProfileName": "BlockAll"}, P, "Weapon")
    assert not effective({"CollisionProfileName": "InvisibleWall"}, P, "Weapon")
    assert effective({"CollisionProfileName": "InvisibleWall"}, P, "Pawn")
    assert effective({}, P, "Weapon")
    ign = {"CollisionResponses": {"ResponseArray": [{"Channel": "Weapon", "Response": "ECollisionResponse::ECR_Ignore"}]}}
    assert not effective(dict(ign, CollisionProfileName="Custom"), P, "Weapon")
    assert not effective(ign, P, "Weapon")
    sma = {"actor_class": "StaticMeshActor", "body": {"CollisionProfileName": "BlockAll"}}
    assert body_of(sma, {"CollisionProfileName": "NoCollision"})["CollisionProfileName"] == "NoCollision"
    bp = {"actor_class": "BP_X_C", "body": {"CollisionEnabled": "ECollisionEnabled::QueryOnly"},
          "body_templates": [dict(ign, CollisionProfileName="Custom")]}
    merged = body_of(bp, None)
    assert merged["CollisionProfileName"] == "Custom" and not effective(merged, P, "Weapon")

    def box(c, e):
        return np.asarray(trimesh.creation.box(extents=e).triangles) + np.asarray(c, float)

    ground = box((0, 0, -50), (2000, 2000, 100))          # top at z = 0
    wall = box((0, -600, 150), (40, 800, 300))             # x = 0 wall, y in [-1000, -200]
    wall2 = box((0, 600, 150), (40, 800, 300))             # gap at y in [-200, 200]
    plat = box((600, 600, 250), (400, 400, 20))            # platform top at z = 260
    T = np.concatenate([ground, wall, wall2, plat]).astype(np.float32)
    c = Caster(T)
    z, clr = floors(c, np.array([[500.0, -500.0], [600.0, 600.0], [0.0, -600.0]]))
    assert abs(z[0, 0]) < 1 and np.isnan(z[0, 1]), z[0]
    assert abs(z[1, 0]) < 1 and abs(z[1, 1] - 260) < 1, z[1]      # two levels under the platform
    assert abs(z[2, 0] - 300) < 1 and np.isnan(z[2, 1]), z[2]       # wall top only: no room inside it
    a = np.array([[-500, -500, 160], [-500, 0, 160]], float)
    b = np.array([[500, -500, 160], [500, 0, 160]], float)
    occ = c.occluded(a, b)
    assert occ.tolist() == [True, False], occ
    pts = np.array([[-500, -500, 160], [500, -500, 160], [-500, 0, 160], [500, 0, 160]], float)
    bits = table(c, pts, rows_per_chunk=2)
    n = len(pts)
    ii, jj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    V = visible(bits, ii.ravel(), jj.ravel(), n).reshape(n, n)
    assert (V == V.T).all() and not V[0, 1] and V[2, 3] and V[0, 2], V
    # placement: a mirrored instance keeps outward winding
    m = np.eye(4)
    m[0, 0] = -1
    t = place(box((0, 0, 0), (2, 2, 2)), m[None])
    n_ = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
    assert (np.einsum("ij,ij->i", n_, t.mean(1)) > 0).all()
    print("sightlines_3d self-test: ok")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--self-test", action="store_true")
    sub = ap.add_subparsers(dest="cmd")
    b = sub.add_parser("build")
    b.add_argument("--map", default="ascent")
    b.add_argument("--dump", required=True)
    b.add_argument("--ini", required=True)
    b.add_argument("--persistent", required=True)
    b.add_argument("--build", default=GAME_BUILD)
    b.add_argument("--out")
    b.add_argument("--no-table", action="store_true")
    b.add_argument("--record", action="store_true")
    b.add_argument("--complex-all", action="store_true", help="post hoc: every mesh traces its render triangles")
    r = sub.add_parser("rebuild", help="a table from an older table's blockers, with this version's heights")
    r.add_argument("--map", default="ascent")
    r.add_argument("--source", required=True,
                   help="the older table, e.g. <store>/sightlines/<map>__sightlines-3d-0.2.0.npz")
    r.add_argument("--out")
    r.add_argument("--no-table", action="store_true")
    r.add_argument("--record", action="store_true")
    g = sub.add_parser("gate")
    g.add_argument("--map", default="ascent")
    g.add_argument("--record", action="store_true")
    g.add_argument("--set", choices=("dev", "confirm"), default="dev",
                   help="confirm: an instrument check on the confirmation history, for maps without development kills")
    g.add_argument("--disagreements", type=int, default=10)
    g.add_argument("--npz", help="a built table other than the store default")
    sp = sub.add_parser("state-props", help="per map, the placements the state-changing test removes from stored tables")
    sp.add_argument("--version", default=PREVIOUS, help="the tables to read")
    a = ap.parse_args(argv)
    if a.self_test:
        return _self_test()
    if a.cmd == "build":
        return cmd_build(a)
    if a.cmd == "rebuild":
        return cmd_rebuild(a)
    if a.cmd == "gate":
        return cmd_gate(a)
    if a.cmd == "state-props":
        return cmd_state_props(a)
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
