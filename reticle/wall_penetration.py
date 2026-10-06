"""What a straight bullet path crosses between two world points, by the
game's own penetration data.

[owns:wall-penetration]

A map's 3D sightline table stores every Weapon-blocking triangle with the
placement (`src`, `src_meta`) it came from. A crossing's surface is the hit
triangle's collision section, that section's material slot, the material's
PhysMaterial through its parent chain and the physical material's
SurfaceType; WallPenGlobals maps the surface to a penetration class
[domain:weapons/wall-penetration-surfaces]. The exports live in the store's
`reference/game-files/<build>/wallpen/` and `wallpen-meshes/`; a mesh or
material not exported leaves its crossings `unread`, never guessed.

`Penetration.lines` answers, per segment: how many crossings, distinct
placements and solid runs lie on it, how much solid path, whether an
Impenetrable surface lies on it and whether any surface is unread. It
never decides whether a bullet got through: the replay's damage records
say that (`wall_penetration`), and this module tests the geometry against
them. Promoted from `prototypes/wallbang_probe.py` (wallbang-probe-0.1.0),
which now imports these functions; the probe keeps its own budget test and
its placeholders.
"""
from __future__ import annotations

import gzip
import json
import re
from collections import defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from .store import DEFAULT_STORE

WALL_PENETRATION_VERSION = "wall-penetration-0.1.0"
GAME_BUILD = "release-13.06-shipping-18-5590001"
#: WallPen_High sets no EnergyReductionMultiplier; its native default is
#: unread, so High reads as 1.0 here, a placeholder that decides nothing in
#: `lines` (classes are reported, not costed).
HIGH_ERM = 1.0
#: An EnergyReductionMultiplier at or above this is Impenetrable (the
#: class sets 100000 [domain:weapons/wall-penetration-surfaces]).
IMPENETRABLE_ERM = 1000.0
HIT_EPS_CM = 0.05
MAX_HITS = 96


def build_root(root=DEFAULT_STORE) -> Path:
    return Path(root) / "reference" / "game-files" / GAME_BUILD


def exports(path: Path) -> list[dict]:
    op = gzip.open if path.suffix == ".gz" else open
    with op(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def surface_names(root=DEFAULT_STORE) -> dict[int, str]:
    """EPhysicalSurface index -> name, from the build's DefaultEngine.ini."""
    ini = (build_root(root) / "config" / "ShooterGame" / "Config" / "DefaultEngine.ini").read_text(
        encoding="utf-8")
    out = {0: "Default"}
    for m in re.finditer(r'\+PhysicalSurfaces=\(Type=SurfaceType(\d+),Name="([^"]+)"\)', ini):
        out[int(m.group(1))] = m.group(2)
    return out


def penetration_classes(root=DEFAULT_STORE) -> dict[str, float]:
    """WallPen class -> EnergyReductionMultiplier (High: `HIGH_ERM`)."""
    out = {}
    d = build_root(root) / "wallpen" / "ShooterGame/Content/Equippables/Guns/_Core/WallPenetration"
    for f in sorted(d.glob("WallPen_*.json")):
        p = next(x for x in exports(f) if x.get("Name", "").startswith("Default__"))["Properties"]
        erm = p.get("EnergyReductionMultiplier")
        out[f.stem] = float(HIGH_ERM if erm is None else erm)
    return out


def surface_table(root=DEFAULT_STORE) -> tuple[np.ndarray, list[str], dict]:
    """ERM per EPhysicalSurface index (from WallPenGlobals), the class names, and the curve."""
    g = next(x for x in exports(build_root(root) / "wallpen" / "ShooterGame/Content/Globals/WallPenGlobals.json")
             if x.get("Name", "").startswith("Default__"))["Properties"]
    cls = penetration_classes(root)
    names, erm = [], []
    for i in range(39):
        k = "WallPenetrationType" if i == 0 else f"WallPenetrationType[{i}]"
        # WallPenGlobals leaves index 38 unset (37 named surfaces after Default);
        # an unset entry reads as High here, an assumption no export confirms
        c = g[k]["AssetPathName"].split(".")[-1].removesuffix("_C") if k in g else "WallPen_High"
        names.append(c)
        erm.append(cls[c])
    curve = [(k["Time"], k["Value"]) for k in g["GlobalPenetrationCurve"]["EditorCurveData"]["Keys"]]
    return np.asarray(erm, float), names, {"curve": curve, "classes": cls}


@lru_cache(maxsize=4)
def _index_paths_cached(classes: tuple, root: str) -> dict:
    out: dict[str, list[str]] = defaultdict(list)
    with gzip.open(build_root(root) / "index.tsv.gz", "rt", encoding="utf-8") as f:
        next(f)
        for line in f:
            p, _, c = line.rstrip("\n").partition("\t")
            if c in classes:
                out[Path(p).stem.lower()].append(p)
    return dict(out)


def index_paths(classes: set[str], root=DEFAULT_STORE) -> dict[str, list[str]]:
    """Asset basename (lowercase) -> game paths of that class, from the build's index."""
    return _index_paths_cached(tuple(sorted(classes)), str(root))


def obj_path(ref: dict | None) -> str | None:
    """'/Game/A/B.0' -> 'ShooterGame/Content/A/B.uasset'."""
    if not ref or not ref.get("ObjectPath"):
        return None
    p = ref["ObjectPath"].rsplit(".", 1)[0]
    if p.startswith("/Game/"):
        return "ShooterGame/Content/" + p[len("/Game/"):] + ".uasset"
    if p.startswith("/Engine/"):
        return "Engine/Content/" + p[len("/Engine/"):] + ".uasset"
    return None


def json_of(game_path: str, root=DEFAULT_STORE) -> Path:
    """The exported JSON of a mesh or material in `wallpen-meshes/`."""
    p = build_root(root) / "wallpen-meshes" / Path(game_path).with_suffix(".json")
    return p if p.exists() else p.with_suffix(".json.gz")


class Surfaces:
    """Surface type of a crossing: (map table, placement, local triangle) -> EPhysicalSurface index.

    Complex collision (the placement's triangle count equals the collision
    LOD's collision-enabled sections) takes the hit section's material slot;
    simple collision takes BodySetup.PhysMaterial, else slot 0's material, the
    engine's order for simple shapes. A material's PhysMaterial is its own,
    else its parent's; none is the engine default, SurfaceType_Default (0).
    Component-level material overrides and PhysMaterialOverride are not read
    (`unread` in the result)."""

    def __init__(self, root=DEFAULT_STORE):
        self.root = root
        self.idx = index_paths({"StaticMesh"}, root)
        self._mesh: dict[str, dict] = {}
        self._mat: dict[str, int | None] = {}
        self._pm: dict[str, int] = {}

    def physmat_surface(self, gp: str | None) -> int:
        if gp is None:
            return 0
        if gp not in self._pm:
            f = build_root(self.root) / "wallpen" / Path(gp).with_suffix(".json")
            f = f if f.exists() else json_of(gp, self.root)
            st = 0
            if f.exists():
                for x in exports(f):
                    v = (x.get("Properties") or {}).get("SurfaceType")
                    if v:
                        st = int(str(v).split("SurfaceType")[-1])
            self._pm[gp] = st
        return self._pm[gp]

    def material_surface(self, gp: str | None, depth: int = 0) -> int | None:
        """Surface of a material's PhysMaterial through its parent chain; None if unread."""
        if gp is None or depth > 16:
            return None
        if gp not in self._mat:
            f = json_of(gp, self.root)
            if not f.exists():
                self._mat[gp] = None
                return None
            pr = next((x.get("Properties") or {} for x in exports(f)
                       if x.get("Type") in ("MaterialInstanceConstant", "Material", "MaterialInstanceDynamic")), {})
            pm = obj_path(pr.get("PhysMaterial"))
            if pm:
                self._mat[gp] = self.physmat_surface(pm)
            elif pr.get("Parent"):
                self._mat[gp] = self.material_surface(obj_path(pr["Parent"]), depth + 1)
            else:
                self._mat[gp] = 0
        return self._mat[gp]

    def mesh(self, name: str, ntris: int) -> dict:
        key = f"{name}#{ntris}"
        if key in self._mesh:
            return self._mesh[key]
        best = None
        for gp in self.idx.get(name.split(".")[0].lower(), []):
            f = json_of(gp, self.root)
            if not f.exists():
                continue
            ex = exports(f)
            sm = next((x for x in ex if x.get("Type") == "StaticMesh"), None)
            bs = next((x for x in ex if x.get("Type") == "BodySetup"), None)
            if sm is None:
                continue
            p = sm.get("Properties") or {}
            slots = [obj_path(s.get("MaterialInterface")) for s in p.get("StaticMaterials") or []]
            lods = (sm.get("RenderData") or {}).get("LODs") or []
            li = min(int(p.get("LODForCollision", 0)), max(len(lods) - 1, 0))
            secs = [s for s in (lods[li].get("Sections") if lods else []) if s.get("bEnableCollision")]
            counts = np.array([int(s["NumTriangles"]) for s in secs], np.int64)
            cand = {"path": gp, "slots": slots, "sec_material": np.array([int(s["MaterialIndex"]) for s in secs], np.int64),
                    "sec_end": np.cumsum(counts), "render_tris": int(counts.sum()),
                    "body_pm": obj_path(((bs or {}).get("Properties") or {}).get("PhysMaterial"))}
            if best is None or cand["render_tris"] == ntris:
                best = cand
        if best is None:
            best = {"path": None}
        else:
            best["complex"] = best["render_tris"] == ntris and ntris > 0
            simple = (self.physmat_surface(best["body_pm"]) if best["body_pm"] else
                      self.material_surface(best["slots"][0]) if best["slots"] else 0)
            best["simple_surface"] = 0 if simple is None else simple
            best["slot_surface"] = [self.material_surface(s) for s in best["slots"]]
        self._mesh[key] = best
        return best

    def of(self, meta: list[dict], ntris_of: np.ndarray, src: np.ndarray, local: np.ndarray):
        """(surface index, unread flag) per crossing."""
        out = np.zeros(len(src), np.int64)
        unread = np.zeros(len(src), bool)
        for s in np.unique(src):
            sel = src == s
            m = self.mesh(meta[int(s)]["mesh"], int(ntris_of[s]))
            if m.get("path") is None:
                unread[sel] = True
                continue
            if m["complex"]:
                sec = np.searchsorted(m["sec_end"], local[sel], side="right")
                sec = np.minimum(sec, len(m["sec_material"]) - 1)
                mi = m["sec_material"][sec]
                ss = np.array([m["slot_surface"][j] if j < len(m["slot_surface"]) else None for j in mi], object)
                unread[np.flatnonzero(sel)[ss == None]] = True  # noqa: E711
                out[sel] = np.array([0 if v is None else v for v in ss], np.int64)
            else:
                out[sel] = m["simple_surface"]
        return out, unread


def segment_hits(caster, a: np.ndarray, b: np.ndarray, max_hits: int = MAX_HITS):
    """Every triangle crossing on each segment a->b, nearest first.

    `caster` has `first_hit(origins, unit_dirs) -> (prim, t)` and `tris`.
    Returns (ray, t_cm, prim, facing, L) with facing = sign of the triangle
    normal along the ray (-1 entering an outward-wound solid, +1 leaving)."""
    a = np.asarray(a, np.float64)
    d = np.asarray(b, np.float64) - a
    L = np.linalg.norm(d, axis=1)
    u = d / np.maximum(L, 1e-9)[:, None]
    t0 = np.zeros(len(a))
    live = np.flatnonzero(L > 1.0)
    R, Tt, P = [], [], []
    for _ in range(max_hits):
        if len(live) == 0:
            break
        o = a[live] + u[live] * t0[live, None]
        prim, t = caster.first_hit(o, u[live])
        th = t0[live] + t
        ok = (prim >= 0) & (th < L[live] - 1.0)
        R.append(live[ok]); Tt.append(th[ok]); P.append(prim[ok])
        t0[live[ok]] = th[ok] + HIT_EPS_CM
        live = live[ok]
    ray = np.concatenate(R) if R else np.zeros(0, np.int64)
    tt = np.concatenate(Tt) if Tt else np.zeros(0)
    prim = np.concatenate(P) if P else np.zeros(0, np.int64)
    tri = np.asarray(caster.tris)[prim].astype(np.float64)
    n = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    facing = np.sign(np.einsum("ij,ij->i", n, u[ray]))
    order = np.lexsort((tt, ray))
    return ray[order], tt[order], prim[order], facing[order], L


def intervals(ray: np.ndarray, t: np.ndarray, group: np.ndarray, facing: np.ndarray, L: np.ndarray,
              runs: bool = False):
    """Solid path length per crossing, from outward-wound crossings.

    Along each ray (every caller passes one group per ray: the maps'
    architecture is single-sided shells, so a wall's outer and inner faces are
    often different meshes) a running depth counts entering minus leaving
    crossings, never below zero; the segment from a crossing to the ray's
    next one lies inside when the depth after it is positive, and its length
    belongs to that crossing's triangle. A leaving crossing with none open (a
    single-sided surface seen from behind) and an entering one never left (a
    single-sided surface, or a target inside a solid) add no length and set
    `open_surface`: the ray is never assumed to start inside a solid.

    Returns (length per crossing, open flag per crossing) and, with `runs`,
    a third array: the entering crossings that lift the depth from 0, one
    per solid run."""
    n = len(ray)
    if n == 0:
        return (np.zeros(0), np.zeros(0, bool)) + ((np.zeros(0, bool),) if runs else ())
    key = ray.astype(np.int64) * (int(group.max()) + 2) + group
    order = np.lexsort((t, key))
    k, tt, f = key[order], t[order], facing[order]
    start = np.r_[True, k[1:] != k[:-1]]
    gid = np.cumsum(start) - 1
    step = np.where(f < 0, 1, -1)
    cs = np.cumsum(step)
    g0 = np.flatnonzero(start)
    cg = cs - np.r_[0, cs[:-1]][g0][gid]            # depth within the group, unclipped
    big = 4 * (n + 1)
    run_min = np.minimum.accumulate(cg - gid * big) + gid * big   # running minimum, reset per group
    after = cg - np.minimum(0, run_min)             # depth clipped at zero (a reflected walk)
    before = np.where(start, 0, np.r_[0, after[:-1]])  # clipped depth before each crossing
    unmatched_exit = (step < 0) & (before <= 0)
    nxt_same = np.r_[~start[1:], False]
    t_next = np.r_[tt[1:], 0.0]
    length = np.zeros(n)
    inside = (after > 0) & nxt_same
    length[inside] = t_next[inside] - tt[inside]
    open_surface = ((after > 0) & ~nxt_same) | unmatched_exit
    run_start = (before <= 0) & (after > 0) & nxt_same
    out_len, out_open, out_run = np.empty(n), np.empty(n, bool), np.empty(n, bool)
    out_len[order], out_open[order], out_run[order] = length, open_surface, run_start
    return (out_len, out_open, out_run) if runs else (out_len, out_open)


class Penetration:
    """One map's Weapon-blocking triangles with their placements and surfaces.

    `occ` is the map's `line_of_sight.Occluders`, whose embree scene this
    reuses; the placements come from the same stored table."""

    def __init__(self, occ, root=DEFAULT_STORE, src=None, meta=None, surface_of_tri=None):
        self.occ = occ
        self.root = root
        if src is None:
            from .line_of_sight import sightline_table
            path = sightline_table(occ.map, root)
            with np.load(path, allow_pickle=False) as z:
                weapon = z["weapon"]
                full = z["src"]
                self.meta = json.loads(str(z["src_meta"]))
            widx = np.flatnonzero(weapon)
            self.src = full[widx]
            first = np.full(int(full.max()) + 1, -1, np.int64)
            srcs, fidx = np.unique(full, return_index=True)
            first[srcs] = fidx
            self.local = widx - first[self.src]
            self.ntris_of = np.bincount(full, minlength=int(full.max()) + 1)
            self.erm, self.class_names, _ = surface_table(root)
            self.surfaces = Surfaces(root)
            self.surface_of_tri = None
        else:                                         # synthetic: one placement per triangle group
            self.src = np.asarray(src, np.int64)
            self.meta = meta or []
            self.local = np.zeros(len(self.src), np.int64)
            self.ntris_of = np.bincount(self.src)
            self.erm, self.class_names = np.array([1.0, IMPENETRABLE_ERM * 100]), ["WallPen_High",
                                                                                   "WallPen_Impenetrable"]
            self.surfaces = None
            self.surface_of_tri = np.asarray(surface_of_tri, np.int64)

    def provenance(self) -> dict:
        return {"owner": "wall-penetration", "version": WALL_PENETRATION_VERSION,
                "game_build": GAME_BUILD, "table": getattr(self.occ, "table", None)}

    def lines(self, a: np.ndarray, b: np.ndarray) -> list[dict]:
        """Per segment a -> b (rows of xyz, cm): `crossings`, `placements`
        (distinct placements crossed), `solids` (runs of solid path),
        `open_surfaces` (single-sided crossings), `solid_cm`, `classes`
        (penetration classes met, unread aside), `impenetrable` and
        `unread` (a crossing whose surface no export gives)."""
        a = np.asarray(a, np.float64).reshape(-1, 3)
        b = np.asarray(b, np.float64).reshape(-1, 3)
        ray, t, prim, facing, L = segment_hits(self.occ, a, b)
        seglen, open_s, run0 = intervals(ray, t, np.zeros_like(prim), facing, L, runs=True)
        src = self.src[prim]
        if self.surface_of_tri is not None:
            st, unread = self.surface_of_tri[prim], np.zeros(len(prim), bool)
        else:
            st, unread = self.surfaces.of(self.meta, self.ntris_of, src, self.local[prim])
        cls = np.array(self.class_names, object)[np.minimum(st, len(self.class_names) - 1)]
        impen = (self.erm[np.minimum(st, len(self.erm) - 1)] >= IMPENETRABLE_ERM) & ~unread
        out = []
        for i in range(len(a)):
            s = ray == i
            out.append({"crossings": int(s.sum()), "placements": int(len(np.unique(src[s]))),
                        "solids": int(run0[s].sum()), "open_surfaces": int(open_s[s].sum()),
                        "solid_cm": round(float(seglen[s].sum()), 1),
                        "classes": sorted({str(c).removeprefix("WallPen_") for c in cls[s & ~unread]}),
                        "impenetrable": bool(impen[s].any()), "unread": bool(unread[s].any()),
                        "meshes": sorted({str(self.meta[int(x)].get("mesh")) for x in np.unique(src[s])})
                        if self.meta else []})
        return out
