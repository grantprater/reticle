r"""Where the game places each side's spawn barriers, from its own level files.

[owns:spawn-barriers]

    .\.venv\Scripts\python.exe -m reticle.spawn_barriers build     bake every map's table
    .\.venv\Scripts\python.exe -m reticle.spawn_barriers show MAP  print one map's barriers

A spawn barrier holds a team in its spawn through the buy phase and falls at
the drop [domain:rounds/buy-phase-barriers]. The game places them as actors of
`SpawnBarrier_C` (and its subclasses `SpawnBarrier_Corner_C`,
`SpawnBarrier_InfinityLedge_C`) in one level per map, the level the match
loads beside the map's geometry. The 3D sightline tables leave them out (they
fall in the round) and keep only their names, so this module reads them
afresh from the game files and stores them apart; no geometry table and no
geometry stamp changes.

Source
------
The store's extractor (`<store>/tools/game-extract`, CUE4Parse) exported each
map's barrier level and the three barrier classes into
`<store>/reference/game-files/<BUILD>/spawn-barriers/`, whose `manifest.jsonl`
names each file's game path and sha256 and whose provenance names the build,
the CUE4Parse and tool commits and the mapping file. The levels were found by
`game-extract whorefs "ShooterGame/Content/Maps/**"` on the class names and
kept where the map's 3D sightline table loads the same level.

Shape
-----
A barrier's blocking body is its `GameObjectMesh` component, the box mesh
`SuperGrid_BoxCentered` (the bulletproof glass; the visible `SM_Barrier` has
no collision). Its world box is the mesh's collision bounds through the
component's transform, then the actor root's (`TheScene`), composed as the
engine composes them (scale, rotation, translation, child before parent).
Each property comes from the instance where it sets it, else from the
subclass's default component, else from `SpawnBarrier_C`'s. The side is the
actor's `TeamRoleComponent.TeamRole` (`Attacker`, `Defender`); an actor
without one (Abyss's ledge barriers) keeps side null with the reason.

Reads no capture and no replay.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

import numpy as np

from .store import DEFAULT_STORE

SPAWN_BARRIERS_VERSION = "spawn-barriers-0.1.0"
GAME_BUILD = "release-13.06-shipping-18-5590001"
EXPORT_SET = "spawn-barriers"
#: Each map's barrier level, keyed by the sightline tables' map key. Found by
#: `whorefs` on the class names; each is a level the map's 3D table loads.
LEVELS = {
    "abyss": "ShooterGame/Content/Maps/Infinity/Infinity_Barriers.umap",
    "ascent": "ShooterGame/Content/Maps/Ascent/Ascent_Gameplay.umap",
    "bind": "ShooterGame/Content/Maps/Duality/Duality_Gameplay.umap",
    "breeze": "ShooterGame/Content/Maps/Foxtrot/Foxtrot_Gameplay.umap",
    "corrode": "ShooterGame/Content/Maps/Rook/Rook_Gameplay.umap",
    "fracture": "ShooterGame/Content/Maps/Canyon/Canyon_Gameplay.umap",
    "haven": "ShooterGame/Content/Maps/Triad/Triad_Gameplay.umap",
    "icebox": "ShooterGame/Content/Maps/Port/Port_Gameplay.umap",
    "lotus": "ShooterGame/Content/Maps/Jam/Jam_Gameplay.umap",
    "pearl": "ShooterGame/Content/Maps/Pitt/Pitt_Gameplay.umap",
    "split": "ShooterGame/Content/Maps/Bonsai/Bonsai_Gameplay.umap",
    "summit": "ShooterGame/Content/Maps/Plummet/Plummet_Design_SpawnBarriers.umap",
    "sunset": "ShooterGame/Content/Maps/Juliett/Juliett_Barriers.umap",
}
#: The barrier classes and their blueprints; the first is the parent.
CLASSES = {
    "SpawnBarrier_C": "ShooterGame/Content/Blueprint/SpawnBarrier.uasset",
    "SpawnBarrier_Corner_C": "ShooterGame/Content/Blueprint/SpawnBarrier_Corner.uasset",
    "SpawnBarrier_InfinityLedge_C": "ShooterGame/Content/Blueprint/SpawnBarrier_InfinityLedge.uasset",
}
PARENT_CLASS = "SpawnBarrier_C"
COLLISION_COMPONENT = "GameObjectMesh"
ROOT_COMPONENT = "TheScene"
BOX_MESH = "ShooterGame/Content/SuperGrid/Source/Meshes/SuperGrid_BoxCentered.uasset"
SIDES = {"EAresTeamRole::Attacker": "attack", "EAresTeamRole::Defender": "defence"}
TRANSFORM_KEYS = ("RelativeLocation", "RelativeRotation", "RelativeScale3D", "StaticMesh")


# ----------------------------------------------------------------- paths

def build_root(root=DEFAULT_STORE) -> Path:
    return Path(root) / "reference" / "game-files" / GAME_BUILD


def export_dir(root=DEFAULT_STORE) -> Path:
    return build_root(root) / EXPORT_SET


def table_dir(root=DEFAULT_STORE) -> Path:
    return Path(root) / "spawn_barriers"


def barrier_table_path(key: str, root=DEFAULT_STORE) -> Path:
    return table_dir(root) / f"{key}__{SPAWN_BARRIERS_VERSION}.json"


def json_of(game_path: str, root=DEFAULT_STORE) -> Path:
    stem = str(Path(game_path).with_suffix(""))
    p = export_dir(root) / f"{stem}.json"
    return p if p.is_file() else p.with_name(p.name + ".gz")


def exports(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return json.load(f)


# ----------------------------------------------------------------- transforms

def rotator(pitch: float, yaw: float, roll: float) -> np.ndarray:
    """(3, 3) the engine's FRotationMatrix: rows are the local X, Y and Z axes
    in the parent frame (row vectors, `v_parent = v_local @ M`)."""
    p, y, r = np.radians([pitch, yaw, roll])
    sp, cp, sy, cy, sr, cr = np.sin(p), np.cos(p), np.sin(y), np.cos(y), np.sin(r), np.cos(r)
    return np.array([[cp * cy, cp * sy, sp],
                     [sr * sp * cy - cr * sy, sr * sp * sy + cr * cy, -sr * cp],
                     [-(cr * sp * cy + sr * sy), cy * sr - cr * sp * sy, cr * cp]])


def transform(props: dict) -> np.ndarray:
    """(4, 4) a component's relative transform as a row-vector matrix:
    scale, then rotation, then translation."""
    loc = props.get("RelativeLocation") or {}
    rot = props.get("RelativeRotation") or {}
    sc = props.get("RelativeScale3D") or {}
    S = np.diag([sc.get("X", 1.0), sc.get("Y", 1.0), sc.get("Z", 1.0)])
    M = np.eye(4)
    M[:3, :3] = S @ rotator(rot.get("Pitch", 0.0), rot.get("Yaw", 0.0), rot.get("Roll", 0.0))
    M[3, :3] = [loc.get("X", 0.0), loc.get("Y", 0.0), loc.get("Z", 0.0)]
    return M


def box_corners(lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """(8, 4) the homogeneous corners of an axis-aligned box."""
    ix = np.array([[i >> 2 & 1, i >> 1 & 1, i & 1] for i in range(8)])
    return np.column_stack([np.where(ix == 1, hi, lo), np.ones(8)])


# ----------------------------------------------------------------- reading

def _actor_of(e: dict) -> str | None:
    o = e.get("Outer")
    if not isinstance(o, dict):
        return None
    return o.get("ObjectName", "").rsplit(".", 1)[-1].rstrip("'") or None


def mesh_bounds(root=DEFAULT_STORE) -> tuple[np.ndarray, np.ndarray]:
    """The box mesh's collision bounds (cm): the min and max of its convex
    elements' vertices."""
    for e in exports(json_of(BOX_MESH, root)):
        if e.get("Type") == "BodySetup":
            v = np.array([[p["X"], p["Y"], p["Z"]]
                          for c in e["Properties"]["AggGeom"]["ConvexElems"] for p in c["VertexData"]])
            return v.min(0), v.max(0)
    raise ValueError(f"no collision body in {BOX_MESH}")


def class_defaults(root=DEFAULT_STORE) -> dict[str, dict[str, dict]]:
    """Each barrier class's default `GameObjectMesh` and root properties,
    the subclass's over the parent's."""
    own = {}
    for cls, gp in CLASSES.items():
        comps = {}
        for e in exports(json_of(gp, root)):
            name = e.get("Name", "").removesuffix("_GEN_VARIABLE")
            if name in (COLLISION_COMPONENT, ROOT_COMPONENT) and "Component" in e.get("Type", ""):
                p = e.get("Properties") or {}
                comps[name] = {k: p[k] for k in TRANSFORM_KEYS if k in p}
        own[cls] = comps
    out = {}
    for cls in CLASSES:
        out[cls] = {}
        for comp in (COLLISION_COMPONENT, ROOT_COMPONENT):
            merged = dict(own[PARENT_CLASS].get(comp, {}))
            if cls != PARENT_CLASS:
                merged.update(own[cls].get(comp, {}))
            out[cls][comp] = merged
    return out


def level_barriers(level: list[dict], defaults: dict, lo: np.ndarray, hi: np.ndarray) -> list[dict]:
    """Every barrier actor in one level's exports, with its world box."""
    actors = {e["Name"]: e for e in level if e.get("Type") in CLASSES}
    comps: dict[str, dict] = {a: {} for a in actors}
    for e in level:
        a = _actor_of(e)
        if a in comps:
            comps[a][e.get("Name")] = e
    out = []
    corners = box_corners(lo, hi)
    for name in sorted(actors):
        cls = actors[name]["Type"]
        c = comps[name]
        props = {}
        for comp in (COLLISION_COMPONENT, ROOT_COMPONENT):
            p = dict(defaults[cls][comp])
            inst = (c.get(comp) or {}).get("Properties") or {}
            p.update({k: inst[k] for k in TRANSFORM_KEYS if k in inst})
            props[comp] = p
        mesh = (props[COLLISION_COMPONENT].get("StaticMesh") or {}).get("ObjectName", "")
        role = ((c.get("TeamRole") or {}).get("Properties") or {}).get("TeamRole")
        row = {"actor": name, "class": cls, "team_role": role, "side": SIDES.get(role),
               "side_reason": None if role in SIDES else "no_team_role",
               "mesh": mesh}
        if "SuperGrid_BoxCentered" not in mesh:
            row.update(refused=f"collision_mesh_unread:{mesh or 'none'}")
            out.append(row)
            continue
        M = transform(props[COLLISION_COMPONENT]) @ transform(props[ROOT_COMPONENT])
        w = (corners @ M)[:, :3]
        row.update(corners=np.round(w, 2).tolist(),
                   centre=np.round(w.mean(0), 2).tolist(),
                   z_lo=round(float(w[:, 2].min()), 2), z_hi=round(float(w[:, 2].max()), 2),
                   plan=np.round(plan_rectangle(w), 2).tolist())
        out.append(row)
    return out


def plan_rectangle(corners: np.ndarray) -> np.ndarray:
    """(n, 2) a box's footprint in plan: the convex hull of its eight corners'
    x and y; for a box upright in the world, its four-corner rectangle."""
    import cv2
    h = cv2.convexHull(np.asarray(corners)[:, :2].astype(np.float32)).reshape(-1, 2)
    return h.astype(float)


def _export_manifest(root=DEFAULT_STORE) -> dict[str, dict]:
    rows = {}
    for f in sorted(export_dir(root).glob("manifest*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                rows[r["game_path"]] = r
    return rows


def _export_provenance(root=DEFAULT_STORE) -> dict:
    p = export_dir(root) / "manifest.jsonl.provenance.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    return {"build": d.get("build"), "cue4parse": (d.get("cue4parse") or {}).get("commit"),
            "tool_commit": (d.get("tool") or {}).get("commit"),
            "usmap_sha256": (d.get("usmap") or {}).get("sha256")}


def bake(key: str, root=DEFAULT_STORE) -> dict:
    """One map's barrier table: every barrier with its side and world box,
    and the provenance of each file read."""
    rows = _export_manifest(root)
    level_gp = LEVELS[key]
    lo, hi = mesh_bounds(root)
    placed = level_barriers(exports(json_of(level_gp, root)), class_defaults(root), lo, hi)
    files = [level_gp, BOX_MESH, *CLASSES.values()]
    src = [{"game_path": gp, "sha256": (rows.get(gp) or {}).get("sha256"),
            "export": str(json_of(gp, root).relative_to(build_root(root))).replace("\\", "/")}
           for gp in files]
    return {"version": SPAWN_BARRIERS_VERSION, "map": key, "units": "cm",
            "barriers": placed,
            "counts": {s: sum(b["side"] == s for b in placed) for s in ("attack", "defence")}
            | {"no_side": sum(b["side"] is None for b in placed),
               "refused": sum("refused" in b for b in placed)},
            "mesh_bounds_cm": [lo.round(3).tolist(), hi.round(3).tolist()],
            "provenance": {"source": "game files", "export_set": EXPORT_SET,
                           **_export_provenance(root), "files": src,
                           "collision_component": COLLISION_COMPONENT,
                           "root_component": ROOT_COMPONENT,
                           "found_by": 'game-extract whorefs "ShooterGame/Content/Maps/**" '
                                       "--names-file (SpawnBarrier, SpawnBarrier_Corner, "
                                       "SpawnBarrier_InfinityLedge)"}}


def build(root=DEFAULT_STORE, keys=None) -> list[Path]:
    """Bake and write every map's table; never overwrite a different one."""
    d = table_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    out = []
    for key in keys or LEVELS:
        t = bake(key, root)
        text = json.dumps(t, indent=1, sort_keys=True)
        p = barrier_table_path(key, root)
        if p.is_file() and p.read_text(encoding="utf-8") != text:
            raise FileExistsError(f"{p} holds a different {SPAWN_BARRIERS_VERSION} table; bump the version")
        p.write_text(text, encoding="utf-8")
        out.append(p)
    return out


def load(map_name: str, root=DEFAULT_STORE) -> dict:
    """The stored barrier table of a map (display name or key)."""
    from .line_of_sight import map_key
    p = barrier_table_path(map_key(map_name), root)
    if not p.is_file():
        raise FileNotFoundError(f"no {SPAWN_BARRIERS_VERSION} table for {map_name!r}")
    t = json.loads(p.read_text(encoding="utf-8"))
    t["path"] = p.name
    t["sha16"] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return t


def side_footprints(table: dict, side: str) -> np.ndarray:
    """(n, 2) the plan footprint corners (cm) of one side's barriers."""
    r = [p for b in table["barriers"] if b.get("side") == side and "plan" in b for p in b["plan"]]
    return np.asarray(r, float).reshape(-1, 2)


def main(argv: list[str]) -> int:
    if argv[:1] == ["build"]:
        for p in build(keys=argv[1:] or None):
            t = json.loads(p.read_text(encoding="utf-8"))
            print(p.name, t["counts"])
        return 0
    if argv[:1] == ["show"] and len(argv) == 2:
        t = load(argv[1])
        for b in t["barriers"]:
            print(b["actor"], b["class"], b["side"], b.get("centre"), b.get("refused", ""))
        return 0
    print(__doc__.splitlines()[2:4])
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
