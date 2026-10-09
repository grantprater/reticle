"""Which callout region and super-region holds a world point.

[owns:callout-region]

A map's callout volumes are the game's own named playable regions, oriented
boxes exported with each 3D sightline table (`region_inv`, `region_lo`,
`region_hi`, `region_names`; docs/SIGHTLINES_3D_PROBE.md, "Floors"). A point
lies in the smallest volume that holds it, probed `PROBE_CM` above the given
height as the table's builder probes its cells.

Volume names are no label: five maps name them only by number
(`BP_CalloutRegion12`). The boxes of one actor form one region and take the
label of valorant-api's callout points (`regionName`, `superRegionName`: A,
B, C, Mid, Attacker Side, Defender Side) that lie inside any of them, the
majority winning; an actor holding none takes the points over or under its
boxes in plan, and failing those the point nearest its centre in plan. Each
label carries that basis (`inside`, `plan` or `nearest`), so a consumer can
see which labels rest on the weaker rules.
"""
from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

import numpy as np

from .line_of_sight import map_key, sightline_table
from .store import DEFAULT_STORE

MAP_REGIONS_VERSION = "map-regions-0.2.0"
#: Points are tested this far above the given z: a replay's z is the capsule
#: centre, a callout point's z sits at the floor.
PROBE_CM = 50.0
SITES = ("A", "B", "C")
#: `site_code_of` for a point inside a volume that is not a site proper.
OFF_SITE = -2


class Regions:
    """One map's callout volumes and their labels."""

    def __init__(self, inv, lo, hi, labels: list[dict], table: str = "synthetic"):
        self.inv = np.asarray(inv, float).reshape(-1, 4, 4)
        self.lo = np.asarray(lo, float).reshape(-1, 3)
        self.hi = np.asarray(hi, float).reshape(-1, 3)
        self.labels = labels
        self.table = table
        fwd = np.linalg.inv(self.inv)[:, :3, :3] if len(self.inv) else np.zeros((0, 3, 3))
        scale = np.linalg.norm(fwd, axis=2)
        self.volume = np.prod(np.abs(self.hi - self.lo) * scale, axis=1)
        self._codes()

    def _codes(self) -> None:
        self.super = np.array([lab.get("super") for lab in self.labels], dtype=object)
        #: The super-region names, and each volume's index into them (-1 none).
        self.super_labels = sorted({x for x in self.super.tolist() if x is not None})
        code = {x: i for i, x in enumerate(self.super_labels)}
        self.super_code = np.array([code.get(x, -1) for x in self.super.tolist()], np.int16)
        #: The volumes valorant-api names `<site> Site` (region "Site").
        self.site_proper = np.array([lab.get("region") == "Site" for lab in self.labels], bool)
        #: The volumes valorant-api names `<area> Link`: connectors between
        #: areas, which belong to one super-region and touch another.
        self.transit = np.array([lab.get("region") == "Link" for lab in self.labels], bool)

    @classmethod
    def load(cls, map_name: str, root=DEFAULT_STORE) -> "Regions":
        path = sightline_table(map_name, root)
        if path is None:
            raise FileNotFoundError(f"no sightline table with callout volumes for {map_name!r}")
        with np.load(path, allow_pickle=False) as z:
            inv, lo, hi = z["region_inv"], z["region_lo"], z["region_hi"]
            names = json.loads(str(z["region_names"]))
        reg = cls(inv, lo, hi, [{"volume": n} for n in names], table=path.name)
        reg.labels = label_volumes(reg, api_callouts(map_name, root), names)
        reg._codes()
        return reg

    def volume_of(self, pts: np.ndarray) -> np.ndarray:
        """Index of the smallest volume holding each point (xyz, cm), -1 for
        none or a non-finite point."""
        p = np.asarray(pts, float).reshape(-1, 3)
        out = np.full(len(p), -1, np.int32)
        if len(self.inv) == 0 or len(p) == 0:
            return out
        ok = np.isfinite(p).all(1)
        h = np.column_stack([p[:, 0], p[:, 1], p[:, 2] + PROBE_CM, np.ones(len(p))])
        h[~ok] = 0.0
        loc = np.einsum("nj,kji->kni", h, self.inv)[..., :3]
        inside = ((loc >= self.lo[:, None, :]) & (loc <= self.hi[:, None, :])).all(-1)
        inside &= ok[None, :]
        vol = np.where(inside, self.volume[:, None], np.inf)
        k = np.argmin(vol, axis=0)
        has = np.isfinite(vol[k, np.arange(len(p))])
        out[has] = k[has]
        return out

    def super_of(self, pts: np.ndarray) -> np.ndarray:
        """The super-region label of each point, None outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), None, dtype=object)
        out[k >= 0] = self.super[k[k >= 0]]
        return out

    def super_code_of(self, pts: np.ndarray) -> np.ndarray:
        """Each point's index into `super_labels`, -1 outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), -1, np.int16)
        out[k >= 0] = self.super_code[k[k >= 0]]
        return out

    def site_code_of(self, pts: np.ndarray) -> np.ndarray:
        """Each point's index into `super_labels` when a `Site` volume holds
        it, OFF_SITE inside any other volume, -1 outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), -1, np.int16)
        hit = k >= 0
        out[hit] = np.where(self.site_proper[k[hit]], self.super_code[k[hit]], OFF_SITE)
        return out

    def hold_code_of(self, pts: np.ndarray) -> np.ndarray:
        """Each point's index into `super_labels`, OFF_SITE inside a `Link`
        volume, -1 outside every volume."""
        k = self.volume_of(pts)
        out = np.full(len(k), -1, np.int16)
        hit = k >= 0
        out[hit] = np.where(self.transit[k[hit]], OFF_SITE, self.super_code[k[hit]])
        return out

    def provenance(self) -> dict:
        basis = Counter(lab.get("basis") for lab in self.labels)
        return {"owner": "callout-region", "version": MAP_REGIONS_VERSION,
                "table": self.table, "volumes": len(self.labels), "label_basis": dict(basis)}


def api_callouts(map_name: str, root=DEFAULT_STORE) -> list[dict]:
    """valorant-api's callout points for the map (game units)."""
    return list(_api_callouts(map_key(map_name), str(root)))


@lru_cache(maxsize=32)
def _api_callouts(key: str, root: str) -> tuple:
    p = Path(root) / "external" / "valorant-api" / "maps.json"
    if not p.is_file():
        return ()
    for m in json.loads(p.read_text(encoding="utf-8"))["data"]:
        if (m.get("displayName") or "").strip().lower() == key:
            return tuple(c for c in (m.get("callouts") or []) if c.get("location"))
    return ()


def _centre_xy(reg: Regions, k: int) -> np.ndarray:
    c = np.append((reg.lo[k] + reg.hi[k]) / 2.0, 1.0) @ np.linalg.inv(reg.inv[k])
    return c[:2]


def label_volumes(reg: Regions, callouts: list[dict], names: list[str]) -> list[dict]:
    """Each volume's (region, super) label from the callout points inside it.

    The boxes of one actor (one name) are one callout region, so their
    points vote together; an actor holding no point takes the label of the
    point nearest its boxes' centre in plan. Grouping by actor uses the name
    as an identifier only, never as a label."""
    labels = [{"volume": n, "region": None, "super": None, "basis": "no_callouts"} for n in names]
    if not callouts or len(names) == 0:
        return labels
    pts = np.array([[c["location"]["x"], c["location"]["y"], c["location"]["z"]] for c in callouts])
    k = reg.volume_of(pts)
    votes: dict[str, Counter] = {}
    near: dict[tuple, float] = {}
    for kk, c, p in zip(k.tolist(), callouts, pts):
        if kk >= 0:
            lab = (c.get("regionName"), c.get("superRegionName"))
            votes.setdefault(names[kk], Counter())[lab] += 1
            near[(names[kk], lab)] = min(near.get((names[kk], lab), np.inf),
                                         float(np.hypot(*(p[:2] - _centre_xy(reg, kk)))))
    fwd = np.linalg.inv(reg.inv)
    centre_local = np.column_stack([(reg.lo + reg.hi) / 2.0, np.ones(len(reg.lo))])
    centre = np.einsum("kj,kji->ki", centre_local, fwd)[:, :3]
    # In plan: a point over or under an actor's boxes (the box's own x and y).
    h = np.column_stack([pts, np.ones(len(pts))])
    loc = np.einsum("nj,kji->kni", h, reg.inv)[..., :2]
    over = ((loc >= reg.lo[:, None, :2]) & (loc <= reg.hi[:, None, :2])).all(-1)   # (K, N)
    for name in dict.fromkeys(names):
        idx = [i for i, n in enumerate(names) if n == name]
        plan = Counter((callouts[j].get("regionName"), callouts[j].get("superRegionName"))
                       for j in np.flatnonzero(over[idx].any(0)))
        if name in votes:
            # The most points win; a tie goes to the label whose point lies
            # nearest the volume's centre in plan.
            top = max(votes[name].values())
            region, sup = min((lab for lab, n in votes[name].items() if n == top),
                              key=lambda lab: near[(name, lab)])
            lab = {"region": region, "super": sup, "basis": "inside",
                   "points": sum(votes[name].values())}
        elif plan:
            (region, sup), _n = plan.most_common(1)[0]
            lab = {"region": region, "super": sup, "basis": "plan", "points": sum(plan.values())}
        else:
            c = centre[idx].mean(0)
            j = int(np.argmin(np.hypot(pts[:, 0] - c[0], pts[:, 1] - c[1])))
            lab = {"region": callouts[j].get("regionName"),
                   "super": callouts[j].get("superRegionName"), "basis": "nearest"}
        for i in idx:
            labels[i].update(lab)
    return labels


#: valorant-api's super-region of each side's spawn, keyed by the rounds
#: owner's side words (`rounds.SIDES`).
SPAWN_SUPER = {"attack": "Attacker Side", "defence": "Defender Side"}


def plan_corners(reg: Regions, k: np.ndarray | None = None) -> np.ndarray:
    """(K, 4, 2) the plan corners (game units) of volumes `k` (default all):
    each oriented box's four corners at its floor, in world x and y."""
    k = np.arange(len(reg.inv)) if k is None else np.asarray(k, int)
    lo, hi = reg.lo[k], reg.hi[k]
    xs = np.stack([lo[:, 0], hi[:, 0], hi[:, 0], lo[:, 0]], axis=1)
    ys = np.stack([lo[:, 1], lo[:, 1], hi[:, 1], hi[:, 1]], axis=1)
    local = np.stack([xs, ys, np.repeat(lo[:, 2:3], 4, axis=1), np.ones_like(xs)], axis=-1)
    world = np.einsum("kcj,kji->kci", local, np.linalg.inv(reg.inv[k]))
    return world[..., :2]


def spawn_footprints(reg: Regions) -> dict[str, np.ndarray]:
    """Each side's spawn as the plan corners (game units, (n, 2)) of the
    volumes labelled region `Spawn` in that side's super-region, keyed
    `attack` and `defence`; a side without one is left out. The volumes are
    the map's own callout actors; the label is the owner's
    (`label_volumes`)."""
    out = {}
    for side, sup in SPAWN_SUPER.items():
        k = [i for i, lab in enumerate(reg.labels)
             if lab.get("region") == "Spawn" and lab.get("super") == sup]
        if k:
            out[side] = plan_corners(reg, np.asarray(k)).reshape(-1, 2)
    return out


#: pre-round-area-0.1.0 (2026-10-09): the rule `pre_round_areas` draws.
PRE_ROUND_AREA_VERSION = "pre-round-area-0.1.0"
PRE_ROUND_AREA_RULE = (
    "walk_flood: the cells of the 3D table's walk graph reached from the side's Spawn callout "
    "volumes without entering or crossing a SpawnBarrier box (the segment at the capsule "
    "centre, the table's body_cm); the area is the convex hull of those cells' squares and the "
    "side's Spawn volumes. hull (where the flood leaks to the other spawn, or the table "
    "has no walk graph): the convex hull of the Spawn volumes and the side's barrier footprints")


#: Cells of different walk components this near in plan are tested for a
#: bridge: the table grids only callout volumes, so a doorway or seam between
#: two volumes can leave a row of cells out (Ascent's A Lobby lies 2 m from
#: the attackers' spawn cells at the same floor). Two missing cells at the
#: diagonal is 2 * sqrt(2) grid steps; a placeholder, not a game value.
BRIDGE_GRID_STEPS = 2.0 * 2 ** 0.5


def walk_cells(map_name: str, root=DEFAULT_STORE, bridge: bool = True) -> dict | None:
    """The standable cells and walk edges of the map's 3D sightline table
    (`cell_xy`, `cell_z`, `walk_r`, `walk_c`) with its grid step, capsule
    centre and jump heights; None where the table has no walk graph.

    With `bridge`, cells of different components within
    `BRIDGE_GRID_STEPS` grid steps in plan whose floors differ by at most the
    jump height are joined where the segment between them at the capsule
    centre crosses no Pawn-blocking triangle of the same table
    (`line_of_sight.Occluders` over the `pawn` set); `bridges` counts them."""
    path = sightline_table(map_name, root)
    if path is None:
        return None
    with np.load(path, allow_pickle=False) as z:
        if "walk_r" not in z.files:
            return None
        prov = json.loads(str(z["provenance"]))
        out = {"xy": z["cell_xy"].astype(float), "z": z["cell_z"].astype(float),
               "r": z["walk_r"].astype(np.int64), "c": z["walk_c"].astype(np.int64),
               "grid_cm": float(prov.get("grid_cm", 100.0)), "jump_cm": float(prov["jump_cm"]),
               "body_cm": float(prov["body_cm"]), "table": path.name, "bridges": 0}
        pawn = z["tris"][z["pawn"]] if bridge else None
    if bridge:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        from scipy.spatial import cKDTree

        from .line_of_sight import Occluders
        n = len(out["z"])
        g = coo_matrix((np.ones(len(out["r"]), np.int8), (out["r"], out["c"])), shape=(n, n))
        _nc, lab = connected_components(g, directed=False)
        pr = cKDTree(out["xy"]).query_pairs(BRIDGE_GRID_STEPS * out["grid_cm"] + 1e-6,
                                            output_type="ndarray")
        pr = pr[(lab[pr[:, 0]] != lab[pr[:, 1]])
                & (np.abs(out["z"][pr[:, 0]] - out["z"][pr[:, 1]]) <= out["jump_cm"])]
        if len(pr):
            p3 = np.column_stack([out["xy"], out["z"] + out["body_cm"]])
            ok = ~Occluders(map_name, root, tris=pawn).blocked(p3[pr[:, 0]], p3[pr[:, 1]])
            pr = pr[ok]
            out["r"] = np.concatenate([out["r"], pr[:, 0]])
            out["c"] = np.concatenate([out["c"], pr[:, 1]])
            out["bridges"] = int(len(pr))
    return out


def barrier_frames(placed: dict) -> tuple[np.ndarray, np.ndarray]:
    """Each barrier box's origin corner (B, 3) and the inverse of its edge
    matrix (B, 3, 3), so `(p - origin) @ inv` puts a world point in the box's
    unit cube. The corners are `spawn_barriers.box_corners` order."""
    C = np.asarray([b["corners"] for b in placed["barriers"] if "corners" in b], float)
    if not len(C):
        return np.zeros((0, 3)), np.zeros((0, 3, 3))
    o = C[:, 0]
    E = np.stack([C[:, 4] - o, C[:, 2] - o, C[:, 1] - o], axis=1)
    return o, np.linalg.inv(E)


def in_boxes(pts: np.ndarray, frames) -> np.ndarray:
    """(N,) whether each world point (cm) lies in any barrier box."""
    o, inv = frames
    if not len(o):
        return np.zeros(len(pts), bool)
    loc = np.einsum("nbj,bji->nbi", pts[:, None, :] - o[None], inv)
    return ((loc >= 0) & (loc <= 1)).all(-1).any(1)


def crosses_boxes(a: np.ndarray, b: np.ndarray, frames) -> np.ndarray:
    """(E,) whether each segment a -> b (world, cm) meets any barrier box:
    the slab test in each box's unit cube."""
    o, inv = frames
    if not len(o):
        return np.zeros(len(a), bool)
    pa = np.einsum("nbj,bji->nbi", a[:, None, :] - o[None], inv)
    pb = np.einsum("nbj,bji->nbi", b[:, None, :] - o[None], inv)
    d = pb - pa
    flat = np.abs(d) < 1e-12
    with np.errstate(divide="ignore", invalid="ignore"):
        ta = np.where(flat, -np.inf, (0 - pa) / d)
        tb = np.where(flat, np.inf, (1 - pa) / d)
    lo = np.where(flat, np.where((pa >= 0) & (pa <= 1), -np.inf, np.inf), np.minimum(ta, tb))
    hi = np.where(flat, np.where((pa >= 0) & (pa <= 1), np.inf, -np.inf), np.maximum(ta, tb))
    t0 = np.maximum(lo.max(-1), 0.0)
    t1 = np.minimum(hi.min(-1), 1.0)
    return (t0 <= t1).any(1)


def _in_volumes(reg: Regions, k: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """(N,) whether each point, probed PROBE_CM up, lies in any of volumes k."""
    if not len(k):
        return np.zeros(len(pts), bool)
    h = np.column_stack([pts[:, 0], pts[:, 1], pts[:, 2] + PROBE_CM, np.ones(len(pts))])
    loc = np.einsum("nj,kji->kni", h, reg.inv[k])[..., :3]
    return ((loc >= reg.lo[k][:, None, :]) & (loc <= reg.hi[k][:, None, :])).all(-1).any(0)


def pre_round_areas(reg: Regions, placed: dict, cells: dict | None = None) -> dict[str, dict]:
    """Each side's pre-round area, keyed `attack` and `defence`: `polygon`
    (convex, in plan, game units, (n, 2)), `basis` (`walk_flood` or `hull`),
    and for a flood the reached cells (`reached`, a mask over `cells`), the
    seed count and why a flood fell back.

    Before the drop a side may walk anywhere its spawn barriers enclose
    [domain:rounds/buy-phase-barriers]. The area floods the walk graph of the
    map's 3D table (`walk_cells`) from the cells inside the side's `Spawn`
    volumes, never entering a barrier box nor crossing one on the line at the
    capsule centre; every barrier of the map stops it, whichever side it
    holds (`spawn_barriers`, from the game files). The polygon is the convex
    hull of the reached cells' squares and the side's Spawn volumes, so it
    covers both. Defenders' barriers stand at the attackers' approaches, so a
    defence area holds the sites. A flood that reaches the other side's spawn
    has leaked through a gap the barriers do not close; that side, and
    a map without a walk graph, falls back to the convex hull of its Spawn
    volumes and its own barriers' footprints. A side with no spawn volume or
    no barrier is left out."""
    import cv2
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    from .spawn_barriers import side_footprints
    fp = spawn_footprints(reg)
    out: dict[str, dict] = {}
    flood = {}
    if cells is not None:
        frames = barrier_frames(placed)
        p3 = np.column_stack([cells["xy"], cells["z"] + cells["body_cm"]])
        blocked = in_boxes(p3, frames)
        r, c = cells["r"], cells["c"]
        ok = ~blocked[r] & ~blocked[c] & ~crosses_boxes(p3[r], p3[c], frames)
        n = len(p3)
        g = coo_matrix((np.ones(int(ok.sum()), np.int8), (r[ok], c[ok])), shape=(n, n))
        _nc, lab = connected_components(g, directed=False)
        floor = np.column_stack([cells["xy"], cells["z"]])
        seeds = {}
        for side, sup in SPAWN_SUPER.items():
            k = np.asarray([i for i, L in enumerate(reg.labels)
                            if L.get("region") == "Spawn" and L.get("super") == sup], int)
            seeds[side] = _in_volumes(reg, k, floor) & ~blocked
        for side in SPAWN_SUPER:
            other = next(s for s in SPAWN_SUPER if s != side)
            reached = np.isin(lab, np.unique(lab[seeds[side]])) & ~blocked
            leak = ["other_spawn"] if (reached & seeds[other]).any() else []
            flood[side] = {"reached": reached, "seeds": int(seeds[side].sum()),
                           "cells": int(reached.sum()), "leak": leak}
    h = (cells or {}).get("grid_cm", 100.0) / 2.0
    sq = np.array([[-h, -h], [h, -h], [h, h], [-h, h]])
    for side in SPAWN_SUPER:
        b = side_footprints(placed, side)
        if side not in fp or not len(b):
            continue
        f = flood.get(side)
        if f and f["seeds"] and not f["leak"]:
            # players stand against the barriers' faces, so the side's own
            # barrier footprints bound the area too
            pts = np.vstack([(cells["xy"][f["reached"]][:, None, :] + sq[None]).reshape(-1, 2),
                             fp[side], b])
            basis = "walk_flood"
        else:
            pts = np.vstack([fp[side], b])
            basis = "hull"
        poly = cv2.convexHull(pts.astype(np.float32), clockwise=False).reshape(-1, 2).astype(float)
        out[side] = {"polygon": poly, "basis": basis}
        if f:
            out[side].update({k: f[k] for k in ("reached", "seeds", "cells", "leak")})
            if basis == "hull":
                out[side]["fallback"] = ("no_seed" if not f["seeds"] else "leak:" + ",".join(f["leak"]))
        else:
            out[side]["fallback"] = "no_walk_graph"
    return out


def in_polygon(poly: np.ndarray, pts: np.ndarray, tol: float = 1.0) -> np.ndarray:
    """(N,) whether each plan point (game units) lies inside a convex polygon
    given counter-clockwise or clockwise, or within `tol` of its edge (the
    hull is drawn in float32)."""
    pts = np.asarray(pts, float).reshape(-1, 2)
    a = np.asarray(poly, float)
    e = np.roll(a, -1, axis=0) - a
    L = np.maximum(np.hypot(e[:, 0], e[:, 1]), 1e-9)
    cross = (e[None, :, 0] * (pts[:, None, 1] - a[None, :, 1])
             - e[None, :, 1] * (pts[:, None, 0] - a[None, :, 0])) / L[None, :]
    return (cross >= -tol).all(1) | (cross <= tol).all(1)


def spawn_points(map_name: str, root=DEFAULT_STORE) -> dict[str, np.ndarray]:
    """valorant-api's `Spawn` callout point of each side, keyed `attack` and
    `defence`; a side without one is left out."""
    side = {"Attacker Side": "attack", "Defender Side": "defence"}
    out = {}
    for c in api_callouts(map_name, root):
        s = side.get(c.get("superRegionName"))
        if s and c.get("regionName") == "Spawn":
            loc = c["location"]
            out[s] = np.array([loc["x"], loc["y"]], float)
    return out
