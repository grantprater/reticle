r"""The 2D sightline map: a walkable grid, line of sight, path distances, regions.

    .\.venv\Scripts\python.exe prototypes\sightlines.py build [MAP ...]     # bake every dev map
    .\.venv\Scripts\python.exe prototypes\sightlines.py info
    .\.venv\Scripts\python.exe prototypes\sightlines.py gate [--record] [--renders DIR]
    .\.venv\Scripts\python.exe prototypes\sightlines.py coverage            # maps lacking geometry
    .\.venv\Scripts\python.exe prototypes\sightlines.py choose [--record]   # 2D or 3D per map

Why this exists
---------------
Coaching asks whether a fight was taken on the best available terms, and
"a teammate could join" is not "a teammate stood near": joining means
standing in, or a short walk from, a cell that sees the fight. Counting
players within a radius cannot say that. This file builds, per map, the
tables that can: which cells see which, how far each cell walks to each, and
two region graphs over the walkable floor. `prototypes/decision_value.py`
reads them; nothing in `reticle/` does.

Inputs: baked geometry only
---------------------------
Static map values come from the baked `(map, profile)` npz
[domain:capture/session-pixels-are-not-the-map]: `labels` (FLOOR and PLANT
are floor) and `occ` (`reticle.occluders`: WALL and BOX stop a ray), composed
by the owner `reticle.cone.passable_from`. The profile is the `-bigmap`
variant where one is baked (a finer pixel: 0.28-0.31 m against 0.42-0.49 m),
else `valorant-16x9`; `summit__valorant-16x9-crop75` places at IoU 0.663,
under `reticle.geometry.MIN_ART_FIT`, and is never used. Riot world positions
reach widget pixels through `riot_ground_truth.map_frame_for_geometry` (the
crossed axes are [domain:replay/vrf-minimap-axes-cross]); the whole chain is
affine, so it is fitted once from three points and inverted.

The grid
--------
Cells are `CELL_M` = 1 m squares, axis-aligned in Riot world coordinates
(Riot units read as centimetres, as `riot_ground_truth` states; no
`domain/*.toml` table records it). A cell's walkable share is the passable
mask box-filtered over one cell's width in pixels (the area filter) and
sampled at the cell centre with linear interpolation; a cell is walkable at
share >= `WALK_SHARE`, the one cut. Each walkable cell has a representative
pixel: the passable pixel nearest its centre (`scipy.ndimage`'s exact
distance transform).

Line of sight
-------------
Two cells see each other when the segment between their representative pixels
crosses only passable pixels, sampled every `STEP_PX` pixel and rounded to the
nearest pixel as `reticle.cone.raycast` does; the occluder lines are sealed to
4-connected, so no sample pair steps through one. Steps run in chunks and only
the segments still alive continue (vectorised in numpy). This is a 2D test:
a SHORT box blocks here although a jumping player sees over it, and floors at
different heights see each other wherever the plan does. The instrument gate
(`gate`) measures how often a gun kill has a line here.

Paths
-----
The walk graph joins 8-neighbour walkable cells whose representative pixels
see each other (so a one-pixel wall between two cells cuts the edge), weighted
by the centres' distance. `scipy.sparse.csgraph.dijkstra` gives all-pairs path
distances, stored as uint16 decimetres (`UNREACHABLE` where no path exists).
One-way drops and ropes are not modelled: the graph is symmetric and 2D.

Regions
-------
- **Callout regions**: valorant-api's callouts (`maps.json`, the cached map
  data `winprob_reference` reads). Each walkable cell joins the callout
  nearest along the path metric.
- **Sightline regions**: each cell's visibility row, L2-normalised, is
  reduced by a truncated SVD (`scipy.sparse.linalg.svds`, `SVD_K`
  components) and clustered by k-means (`scipy.cluster.vq.kmeans2`, k = the
  map's callout count, fixed seed). Each cluster splits into its connected
  pieces on the walk graph, and a piece under `MIN_REGION_CELLS` merges into
  the neighbour it shares the most boundary edges with.

Two regions are adjacent when a walk-graph edge joins them.

Cache
-----
`<store>/sightlines/<geometry key>.npz`, stamped with `VERSION`, the
geometry's `occ_built_by` and `lines_built_by`, and this file's source hash.

2D or 3D per map (`load`, `choose`)
-----------------------------------
`prototypes/sightlines_3d.py` builds a 3D table per map from the game's
collision. `load(map)` returns the 3D table (`Sightlines3D`, the same
interface) where `<store>/sightlines/choice.json` says 3D, else the 2D one;
`load(map, kind="2d")` and `kind="3d"` ask for one. `choose` writes the file:
3D where the 3D probe's instrument gate (ledger `sightlines_3d/gate/<map>`,
the rows of the map's standing table version, `sightlines_3d.table_version`:
killer eye to victim body at exact positions on the
development gun kills) beats the 2D map's share on the same kills, the rule
`engagement_reach` fixed before its confirmation; 2D otherwise; 3D on a map
with no baked 2D geometry, where it is the only instrument (its instrument
check on confirmation kills, `sightlines_3d/gate_confirm/<map>`, is recorded
beside). Each map's choice names its reason and the gate rows it read.

`Sightlines3D` places a position on the lowest standable cell of its 1 m grid
column (the probe's pre-registered floor rule), else the nearest column's;
its visibility is the table's eye-to-eye bit, strict; its walk graph is the
table's cached edges weighted by 3D centre distance, all pairs by
`scipy.sparse.csgraph.dijkstra` in memory (one-way drops not modelled). Its
callout regions are the 2D table's, joined by (x, y), where a 2D table
exists, else the game's own callout volumes (`cell_callout`), two volumes
adjacent when a walk edge joins them.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402
from scipy import ndimage, sparse  # noqa: E402
from scipy.sparse import csgraph  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import riot_ground_truth as rgt  # noqa: E402
from reticle import geometry as geom  # noqa: E402
from reticle.cone import passable_from  # noqa: E402
from reticle.minimap import FLOOR, PLANT  # noqa: E402

cv2.setNumThreads(1)

VERSION = "sightlines-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
OUT_DIR = STORE / "sightlines"

#: One cell's side in metres, and Riot units per metre (units read as cm).
CELL_M = 1.0
UNITS_PER_M = 100.0
#: A cell is walkable at this box-filtered passable share or more.
WALK_SHARE = 0.5
#: Line-of-sight sample spacing in widget pixels, and steps per chunk.
STEP_PX = 0.5
STEP_CHUNK = 24
#: Segments per vectorised batch.
PAIR_BATCH = 400_000
#: Path distances are stored in decimetres; this marks no path.
UNREACHABLE = np.uint16(65535)
#: Sightline regions: SVD components, k-means seed, smallest region (cells).
SVD_K = 24
KMEANS_SEED = 0
MIN_REGION_CELLS = 25
#: A position more than this far from its cell's centre is off the walkable grid.
OFF_GRID_M = 1.5

#: The dev maps, and which baked profile each uses (see the docstring).
PROFILE_ORDER = ("valorant-16x9-bigmap", "valorant-16x9")


def _below_normal() -> None:
    try:
        if sys.platform == "win32":
            import ctypes
            k = ctypes.windll.kernel32
            k.SetPriorityClass(k.GetCurrentProcess(), 0x00004000)
    except Exception:  # noqa: BLE001 -- best effort
        pass


def source_hash() -> str:
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()[:12]


def geometry_key(mname: str, store: Path = STORE) -> str | None:
    for prof in PROFILE_ORDER:
        if geom.path(f"{mname}__{prof}", store).is_file():
            return f"{mname}__{prof}"
    return None


def api_reference(store: Path = STORE) -> rgt.Reference:
    return rgt.Reference(store / "external" / "valorant-api", fetch=False)


def map_info(ref: rgt.Reference, mname: str) -> dict:
    for m in ref.maps.values():
        if rgt.canon(m["displayName"]) == rgt.canon(mname):
            return m
    raise KeyError(mname)


def world_affine(mf) -> np.ndarray:
    """2x3 affine from Riot world units to widget px (the chain is affine)."""
    p0 = np.array(mf.to_px(0.0, 0.0))
    px = np.array(mf.to_px(1000.0, 0.0))
    py = np.array(mf.to_px(0.0, 1000.0))
    return np.column_stack([(px - p0) / 1000.0, (py - p0) / 1000.0, p0])


def apply_affine(A: np.ndarray, xy: np.ndarray) -> np.ndarray:
    xy = np.asarray(xy, float)
    return xy @ A[:, :2].T + A[:, 2]


# ----------------------------------------------------------------- line of sight

def segments_clear(passable: np.ndarray, a: np.ndarray, b: np.ndarray,
                   step_px: float = STEP_PX) -> np.ndarray:
    """For each segment a[i] -> b[i] (widget px, float), whether every sample
    on it lands on a passable pixel. Vectorised; dead segments drop out."""
    h, w = passable.shape
    a = np.asarray(a, np.float64)
    b = np.asarray(b, np.float64)
    m = len(a)
    out = np.zeros(m, bool)
    if m == 0:
        return out
    d = b - a
    n = np.maximum(1, np.ceil(np.hypot(d[:, 0], d[:, 1]) / step_px)).astype(np.int64)
    flat = passable.ravel()
    live = np.arange(m)
    k0 = 0
    nmax = int(n.max())
    while live.size and k0 <= nmax:
        k1 = min(nmax + 1, k0 + STEP_CHUNK)
        ks = np.arange(k0, k1, dtype=np.float64)
        nl = n[live]
        f = np.minimum(ks[None, :] / nl[:, None], 1.0)
        xi = np.rint(a[live, 0, None] + d[live, 0, None] * f).astype(np.int64)
        yi = np.rint(a[live, 1, None] + d[live, 1, None] * f).astype(np.int64)
        inb = (xi >= 0) & (xi < w) & (yi >= 0) & (yi < h)
        np.clip(xi, 0, w - 1, out=xi)
        np.clip(yi, 0, h - 1, out=yi)
        ok = (flat[yi * w + xi] & inb).all(axis=1)
        done = ok & (nl < k1)
        out[live[done]] = True
        live = live[ok & ~done]
        k0 = k1
    return out


# ----------------------------------------------------------------- build

def build_map(mname: str, ref: rgt.Reference, store: Path = STORE, log=print) -> dict:
    key = geometry_key(mname, store)
    if key is None:
        raise SystemExit(f"no baked geometry for {mname}")
    gp = geom.path(key, store)
    mi = map_info(ref, mname)
    mf, why = rgt.map_frame_for_geometry(gp, mname, mi, store)
    if mf is None:
        raise SystemExit(f"{key}: {why}")
    with np.load(gp) as z:
        labels, occ = z["labels"], z["occ"]
        stamps = {k: str(z[k]) for k in ("occ_built_by", "lines_built_by", "occ_version",
                                          "occ_validation", "shade_built_by", "built_by")
                  if k in z.files}
    floor = np.isin(labels, (FLOOR, PLANT))
    passable = passable_from(labels, floor, occ)
    A = world_affine(mf)
    Ainv = cv2.invertAffineTransform(A.astype(np.float64))
    px_per_m = mf.px_per_unit * UNITS_PER_M
    t0 = time.time()

    # grid over the passable pixels' world extent
    ys, xs = np.nonzero(passable)
    corners = apply_affine(Ainv, np.column_stack([xs, ys]).astype(float))
    cu = CELL_M * UNITS_PER_M
    x0, y0 = corners.min(0) - cu
    x1, y1 = corners.max(0) + cu
    nx, ny = int(math.ceil((x1 - x0) / cu)), int(math.ceil((y1 - y0) / cu))
    gx, gy = np.meshgrid(x0 + (np.arange(nx) + 0.5) * cu, y0 + (np.arange(ny) + 0.5) * cu)
    cpx = apply_affine(A, np.column_stack([gx.ravel(), gy.ravel()]))
    k = max(1, int(round(CELL_M * px_per_m)))
    share = cv2.boxFilter(passable.astype(np.float32), -1, (k, k), normalize=True,
                          borderType=cv2.BORDER_CONSTANT)
    sh = cv2.remap(share, cpx[:, 0].astype(np.float32).reshape(ny, nx),
                   cpx[:, 1].astype(np.float32).reshape(ny, nx), cv2.INTER_LINEAR,
                   borderMode=cv2.BORDER_CONSTANT, borderValue=0.0)
    walk = sh >= WALK_SHARE
    # representative pixel: the passable pixel nearest the cell centre
    _dist, (iy, ix) = ndimage.distance_transform_edt(~passable, return_indices=True)
    cyi = np.clip(np.rint(cpx[:, 1]).astype(int), 0, passable.shape[0] - 1)
    cxi = np.clip(np.rint(cpx[:, 0]).astype(int), 0, passable.shape[1] - 1)
    rep = np.column_stack([ix[cyi, cxi], iy[cyi, cxi]]).astype(np.float64)
    rep_off = np.hypot(rep[:, 0] - cpx[:, 0], rep[:, 1] - cpx[:, 1])
    walk &= (rep_off <= 0.75 * CELL_M * px_per_m).reshape(ny, nx)
    cell_of = np.full(ny * nx, -1, np.int32)
    flat_ids = np.flatnonzero(walk.ravel())
    N = len(flat_ids)
    cell_of[flat_ids] = np.arange(N, dtype=np.int32)
    cell_xy = np.column_stack([gx.ravel()[flat_ids], gy.ravel()[flat_ids]])
    cell_rep = rep[flat_ids]
    log(f"{key}: grid {ny}x{nx}, {N} walkable cells, {px_per_m:.2f} px/m, k={k}")

    # walk graph: 8-neighbours whose representatives see each other
    r, c = np.divmod(flat_ids, nx)
    ei, ej, ew = [], [], []
    for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
        rr, cc = r + dr, c + dc
        ok = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
        nb = np.full(N, -1, np.int64)
        nb[ok] = cell_of[rr[ok] * nx + cc[ok]]
        src = np.flatnonzero(nb >= 0)
        dst = nb[src]
        clear = segments_clear(passable, cell_rep[src], cell_rep[dst])
        ei.append(src[clear]); ej.append(dst[clear])
        ew.append(np.full(int(clear.sum()), CELL_M * math.hypot(dr, dc)))
    ei, ej, ew = np.concatenate(ei), np.concatenate(ej), np.concatenate(ew)
    G = sparse.coo_matrix((np.r_[ew, ew], (np.r_[ei, ej], np.r_[ej, ei])), shape=(N, N)).tocsr()
    ncomp, comp = csgraph.connected_components(G, directed=False)
    big = np.bincount(comp).max()
    log(f"  walk graph {len(ei)} edges, {ncomp} components, largest {big}/{N}")

    # all-pairs line of sight (upper triangle, then mirrored)
    los = np.zeros((N, N), bool)
    rows_per = max(1, PAIR_BATCH // max(N, 1))
    t1 = time.time()
    for i0 in range(0, N, rows_per):
        i1 = min(N, i0 + rows_per)
        ii, jj = np.meshgrid(np.arange(i0, i1), np.arange(i0, N), indexing="ij")
        keep = jj > ii
        ii, jj = ii[keep], jj[keep]
        clear = segments_clear(passable, cell_rep[ii], cell_rep[jj])
        los[ii[clear], jj[clear]] = True
    los |= los.T
    np.fill_diagonal(los, True)
    log(f"  line of sight: {los.mean():.4f} of pairs, {time.time() - t1:.0f} s")

    # all-pairs path distances, uint16 decimetres
    t1 = time.time()
    dist = np.empty((N, N), np.uint16)
    for i0 in range(0, N, 256):
        i1 = min(N, i0 + 256)
        dd = csgraph.dijkstra(G, directed=False, indices=np.arange(i0, i1))
        fin = np.isfinite(dd)
        q = np.where(fin, np.minimum(np.rint(dd * 10.0), 65534), 65535)
        dist[i0:i1] = q.astype(np.uint16)
    log(f"  path distances {time.time() - t1:.0f} s")

    # callout regions
    co = [c for c in (mi.get("callouts") or [])]
    co_names = [f"{c['superRegionName']}:{c['regionName']}" for c in co]
    co_xy = np.array([[c["location"]["x"], c["location"]["y"]] for c in co], float)
    co_cell = nearest_cells(cell_xy, co_xy)[0]
    dco = dist[:, co_cell].astype(np.int64)
    reg_c = dco.argmin(1).astype(np.int32)
    reg_c[dco.min(1) >= int(UNREACHABLE)] = -1
    adj_c = region_adjacency(reg_c, ei, ej, len(co))

    # sightline regions
    reg_s, sinfo = sight_regions(los, G, ei, ej, len(co))
    adj_s = region_adjacency(reg_s, ei, ej, int(reg_s.max()) + 1)
    log(f"  regions: {len(co)} callouts, {int(reg_s.max()) + 1} sightline regions "
        f"({time.time() - t0:.0f} s total)")
    return {"version": np.array(VERSION), "source": np.array(source_hash()),
            "map": np.array(mname), "key": np.array(key),
            "geometry_stamps": np.array(json.dumps(stamps, sort_keys=True)),
            "cell_m": np.array(CELL_M), "units_per_m": np.array(UNITS_PER_M),
            "walk_share": np.array(WALK_SHARE), "step_px": np.array(STEP_PX),
            "origin": np.array([x0, y0]), "shape": np.array([ny, nx]),
            "affine": A, "px_per_m": np.array(px_per_m),
            "cell_of": cell_of.reshape(ny, nx), "cell_xy": cell_xy, "cell_rep": cell_rep,
            "comp": comp.astype(np.int32), "edges": np.column_stack([ei, ej]).astype(np.int32),
            "los_bits": np.packbits(los, axis=1), "n_cells": np.array(N),
            "dist_dm": dist,
            "callout_names": np.array(co_names), "callout_cells": co_cell.astype(np.int32),
            "region_callout": reg_c, "adj_callout": adj_c,
            "region_sight": reg_s, "adj_sight": adj_s,
            "sight_method": np.array(json.dumps(sinfo, sort_keys=True))}


def nearest_cells(cell_xy: np.ndarray, xy: np.ndarray):
    """Nearest walkable cell to each world point, and the distance in metres."""
    from scipy.spatial import cKDTree
    d, i = cKDTree(cell_xy).query(np.asarray(xy, float).reshape(-1, 2))
    return i.astype(np.int64), d / UNITS_PER_M


def region_adjacency(reg: np.ndarray, ei: np.ndarray, ej: np.ndarray, n: int) -> np.ndarray:
    a, b = reg[ei], reg[ej]
    k = (a >= 0) & (b >= 0) & (a != b)
    adj = np.zeros((n, n), bool)
    adj[a[k], b[k]] = True
    adj |= adj.T
    np.fill_diagonal(adj, True)
    return adj


def sight_regions(los: np.ndarray, G, ei, ej, k: int) -> tuple[np.ndarray, dict]:
    from scipy.cluster.vq import kmeans2
    from scipy.sparse.linalg import svds
    N = los.shape[0]
    V = sparse.csr_matrix(los, dtype=np.float32)
    nrm = np.sqrt(np.asarray(V.sum(1)).ravel())
    V = sparse.diags(1.0 / np.maximum(nrm, 1e-9)) @ V
    kk = min(SVD_K, N - 2)
    U, S, _ = svds(V, k=kk, random_state=KMEANS_SEED)
    E = U * S
    E /= np.maximum(np.linalg.norm(E, axis=1, keepdims=True), 1e-9)
    _cent, lab = kmeans2(E.astype(np.float64), k, seed=KMEANS_SEED, minit="++")
    # split clusters into connected pieces on the walk graph
    same = lab[ei] == lab[ej]
    H = sparse.coo_matrix((np.ones(int(same.sum())), (ei[same], ej[same])), shape=(N, N))
    _n, piece = csgraph.connected_components(H, directed=False)
    piece = piece.astype(np.int64)
    # merge small pieces into the neighbour sharing the most boundary edges
    merges = 0
    for _ in range(200):
        size = np.bincount(piece)
        small = size < MIN_REGION_CELLS
        small[size == 0] = False
        if not small.any():
            break
        a, b = piece[ei], piece[ej]
        cross = a != b
        a, b = np.r_[a[cross], b[cross]], np.r_[b[cross], a[cross]]
        cand = small[a] & ~small[b]
        if not cand.any():
            cand = small[a]
            if not cand.any():
                break
        M = sparse.coo_matrix((np.ones(int(cand.sum())), (a[cand], b[cand])),
                              shape=(len(size), len(size))).tocsr()
        best = np.asarray(M.argmax(1)).ravel()
        has = np.asarray(M.max(1).todense()).ravel() > 0
        tgt = np.arange(len(size))
        movers = np.flatnonzero(small & has)
        # move only pieces whose target is not itself moving this round
        movers = movers[~np.isin(best[movers], movers)] if len(movers) > 1 else movers
        if not len(movers):
            movers = np.flatnonzero(small & has)[:1]
        tgt[movers] = best[movers]
        piece = tgt[piece]
        merges += len(movers)
    _u, reg = np.unique(piece, return_inverse=True)
    info = {"method": "L2-normalised visibility rows; truncated SVD; k-means on unit embeddings; "
                      "split into walk-graph components; merge pieces under MIN_REGION_CELLS",
            "svd_k": kk, "kmeans_k": k, "seed": KMEANS_SEED, "min_region_cells": MIN_REGION_CELLS,
            "merges": int(merges)}
    return reg.astype(np.int32), info


# ----------------------------------------------------------------- load and query

class Sightlines:
    """One map's cached tables."""

    def __init__(self, path: Path):
        z = np.load(path, allow_pickle=False)
        self.path = path
        self.version = str(z["version"])
        self.key = str(z["key"])
        self.map = str(z["map"])
        self.A = z["affine"]
        self.origin = z["origin"]
        self.shape = tuple(int(v) for v in z["shape"])
        self.cell_of = z["cell_of"]
        self.cell_xy = z["cell_xy"]
        self.cell_rep = z["cell_rep"]
        self.N = int(z["n_cells"])
        self.los_bits = z["los_bits"]
        self.dist_dm = z["dist_dm"]
        self.edges = z["edges"]
        self.comp = z["comp"]
        self.region = {"callout": z["region_callout"], "sight": z["region_sight"]}
        self.adj = {"callout": z["adj_callout"], "sight": z["adj_sight"]}
        self.callout_names = [str(s) for s in z["callout_names"]]
        self.stamps = json.loads(str(z["geometry_stamps"]))
        from scipy.spatial import cKDTree
        self._tree = cKDTree(self.cell_xy)

    def cells(self, xy) -> tuple[np.ndarray, np.ndarray]:
        """Nearest walkable cell per world point, and its distance (m)."""
        d, i = self._tree.query(np.asarray(xy, float).reshape(-1, 2))
        return i.astype(np.int64), d / UNITS_PER_M

    def los_rows(self, q: np.ndarray) -> np.ndarray:
        return np.unpackbits(self.los_bits[np.asarray(q, np.int64)], axis=1, count=self.N).astype(bool)

    def los(self, i, j) -> np.ndarray:
        i = np.asarray(i, np.int64)
        j = np.asarray(j, np.int64)
        byte = self.los_bits[i, j >> 3]
        return ((byte >> (7 - (j & 7))) & 1).astype(bool)

    def dist_m(self, i, j) -> np.ndarray:
        d = self.dist_dm[np.asarray(i, np.int64), np.asarray(j, np.int64)].astype(np.float64)
        return np.where(d >= int(UNREACHABLE), np.inf, d / 10.0)

    def neighbourhood(self, xy) -> np.ndarray:
        """(M, 9) walkable cells of the 3x3 block round each world point's
        grid cell, -1 where a block cell is not walkable; column 4 is the
        point's own grid cell, and the nearest walkable cell fills it when
        that is not walkable."""
        xy = np.asarray(xy, float).reshape(-1, 2)
        ny, nx = self.shape
        g = np.floor((xy - self.origin) / (CELL_M * UNITS_PER_M)).astype(np.int64)
        dy, dx = np.meshgrid((-1, 0, 1), (-1, 0, 1), indexing="ij")
        rr = g[:, 1, None] + dy.ravel()[None, :]
        cc = g[:, 0, None] + dx.ravel()[None, :]
        inb = (rr >= 0) & (rr < ny) & (cc >= 0) & (cc < nx)
        out = np.full(rr.shape, -1, np.int64)
        out[inb] = self.cell_of[rr[inb], cc[inb]]
        own = self.cells(xy)[0]
        out[:, 4] = np.where(out[:, 4] >= 0, out[:, 4], own)
        return out

    def los_near(self, xy_a, xy_b) -> np.ndarray:
        """Line of sight with a one-cell tolerance: some cell of a's 3x3 block
        sees b's cell, or a's cell sees some cell of b's block. The baked
        geometry places Riot positions within about a metre
        ([metric:replay_truth/score@9acf02f98283~2026-10-04T16:14:32#ally_err_px_median=1.55] px on the widget)."""
        na, nb = self.neighbourhood(xy_a), self.neighbourhood(xy_b)
        out = np.zeros(len(na), bool)
        for col in range(9):
            for src, dst in ((na[:, col], nb[:, 4]), (nb[:, col], na[:, 4])):
                has = src >= 0
                out[has] |= self.los(src[has], dst[has])
        return out

    def vis_near(self, xy) -> np.ndarray:
        """(M, N) cells that see some cell of each point's 3x3 block."""
        nb = self.neighbourhood(xy)
        vis = np.zeros((len(nb), self.N), bool)
        for col in range(9):
            has = nb[:, col] >= 0
            vis[has] |= self.los_rows(nb[has, col])
        return vis

    def reach_m(self, p: np.ndarray, vis: np.ndarray) -> np.ndarray:
        """Path metres from cell p[i] to the nearest cell of the boolean row
        vis[i] (a visibility set, from `vis_near` or `los_rows`)."""
        p = np.asarray(p, np.int64)
        d = np.where(vis, self.dist_dm[p].astype(np.int32), int(UNREACHABLE)).min(1)
        return np.where(d >= int(UNREACHABLE), np.inf, d / 10.0)

    def near_region(self, graph: str, a: np.ndarray, b: np.ndarray) -> np.ndarray:
        """Whether cell a[i] lies in the same or an adjacent region as cell b[i]."""
        ra = self.region[graph][np.asarray(a, np.int64)]
        rb = self.region[graph][np.asarray(b, np.int64)]
        ok = (ra >= 0) & (rb >= 0)
        out = np.zeros(len(ra), bool)
        out[ok] = self.adj[graph][ra[ok], rb[ok]]
        return out


def table_path(mname: str, store: Path = STORE) -> Path | None:
    key = geometry_key(mname, store)
    return None if key is None else OUT_DIR / f"{key}.npz"


_CACHE: dict[str, Sightlines] = {}


def load_2d(mname: str, store: Path = STORE) -> Sightlines | None:
    """The map's 2D table, or None."""
    p = table_path(mname.lower(), store)
    if p is None or not p.is_file():
        return None
    if mname not in _CACHE:
        s = Sightlines(p)
        if s.version != VERSION:
            raise SystemExit(f"{p} is {s.version}, this file is {VERSION}: rebuild it")
        _CACHE[mname] = s
    return _CACHE[mname]


CHOICE_PATH = OUT_DIR / "choice.json"
_CACHE3: dict[str, "Sightlines3D"] = {}


def load_3d(mname: str, log=print) -> "Sightlines3D | None":
    """The map's 3D table behind the 2D interface, or None."""
    import sightlines_3d as s3
    mname = mname.lower()
    if mname not in _CACHE3:
        if not s3.out_path(mname).is_file():
            return None
        _CACHE3[mname] = Sightlines3D(mname, log=log)
    return _CACHE3[mname]


def choice(path: Path = CHOICE_PATH) -> dict:
    """Per map: {"kind": "2d" | "3d", "why": ...}, as `choose` wrote it; {} before."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))["maps"]
    except (OSError, KeyError, ValueError):
        return {}


def load(mname: str, store: Path = STORE, kind: str | None = None):
    """The map's sightline table: `kind` "2d" or "3d", else the recorded
    choice (`choice.json`), else 2D. None when the chosen table is missing."""
    mname = mname.lower()
    if kind is None:
        kind = choice().get(mname, {}).get("kind", "2d")
    return load_3d(mname) if kind == "3d" else load_2d(mname, store)


class Sightlines3D(Sightlines):
    """A 3D sightline table (`sightlines_3d`) behind the 2D table's interface."""

    def __init__(self, mname: str, log=print):
        import sightlines_3d as s3
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components, dijkstra
        from scipy.spatial import cKDTree
        t0 = time.time()
        D = s3.load(mname)
        S2 = load_2d(mname)
        self.path = s3.out_path(mname)
        self.version = s3.table_version(mname)
        self.key = f"{mname}__{self.version}"
        self.map = mname
        xy = D["cell_xy"].astype(np.float64)
        z = D["cell_z"].astype(np.float64)
        ix, iy, lay = D["cell_ix"].astype(np.int64), D["cell_iy"].astype(np.int64), D["cell_layer"].astype(np.int64)
        lo, hi = D["grid_lo"], D["grid_hi"]
        shape = (len(np.arange(lo[0] + s3.GRID_CM / 2, hi[0], s3.GRID_CM)),
                 len(np.arange(lo[1] + s3.GRID_CM / 2, hi[1], s3.GRID_CM)))
        N = len(z)
        self.N = N
        self.cell_xy, self.cell_z = xy, z
        self.lo, self.gshape = lo, shape
        # visibility: the packed upper triangle into full packed rows
        tri = np.unpackbits(D["vis_bits"], count=N * (N - 1) // 2).astype(bool)
        M = np.zeros((N, N), bool)
        M[np.triu(np.ones((N, N), bool), 1)] = tri
        del tri
        M |= M.T
        np.fill_diagonal(M, True)
        self.los_bits = np.packbits(M, axis=1)
        del M
        # walk graph: the table's cached edges, else rebuilt from the pawn blockers
        if "walk_r" in D:
            r, c = D["walk_r"].astype(np.int64), D["walk_c"].astype(np.int64)
            edges_from = "cached"
        else:
            r, c = s3.walk_edges(xy, z, ix, iy, lay, shape, s3.Caster(D["tris"][D["pawn"]]))
            edges_from = "rebuilt"
        w = np.linalg.norm(np.column_stack([xy[r] - xy[c], z[r] - z[c]]), axis=1) / UNITS_PER_M
        G = sparse.coo_matrix((w, (r, c)), shape=(N, N)).tocsr()
        ncomp, lab = connected_components(G, directed=False)
        stored = D["cell_component"]
        pairs = len(set(zip(lab.tolist(), stored.tolist())))
        self.edges_check = {"edges": int(len(r)), "from": edges_from, "components": int(ncomp),
                            "stored_components": int(len(np.unique(stored))),
                            "partition_matches_stored": bool(pairs == ncomp == len(np.unique(stored)))}
        self.edges = np.column_stack([r, c])
        self.comp = lab
        dm = np.empty((N, N), np.uint16)
        for b0 in range(0, N, 512):
            d = dijkstra(G, directed=False, indices=np.arange(b0, min(N, b0 + 512)))
            dm[b0:b0 + 512] = np.where(np.isfinite(d), np.minimum(np.round(d * 10.0), int(UNREACHABLE) - 1),
                                       int(UNREACHABLE)).astype(np.uint16)
        self.dist_dm = dm
        # the lowest cell of each grid column
        colkey = ix * shape[1] + iy
        order = np.lexsort((z, colkey))
        first = order[np.r_[True, colkey[order][1:] != colkey[order][:-1]]]
        self._colkey, self._colcell = colkey[first], first
        self._tree3 = cKDTree(xy[first])
        self._tree = self._tree3
        if S2 is not None:
            # callout regions from the 2D table, by (x, y)
            c2 = S2.cells(xy)[0]
            self.region = {"callout": S2.region["callout"][c2]}
            self.adj = {"callout": S2.adj["callout"]}
            self.callout_names = S2.callout_names
            regions_from = S2.key
        else:
            reg = D["cell_callout"].astype(np.int64) if "cell_callout" in D else np.full(N, -1)
            R = len(D["region"]["names"])
            adj = np.eye(R, dtype=bool)
            ok = (reg[r] >= 0) & (reg[c] >= 0)
            adj[reg[r][ok], reg[c][ok]] = True
            adj |= adj.T
            self.region = {"callout": reg}
            self.adj = {"callout": adj}
            self.callout_names = list(D["region"]["names"])
            regions_from = "callout volumes (sightlines_3d cell_callout)"
        self.stamps = {"sightlines_3d": self.version, "provenance_build": D["provenance"].get("source", {}).get("build"),
                       "extractor": D["provenance"].get("source", {}).get("extractor", {}).get("commit"),
                       "regions_from": regions_from}
        self.seconds = round(time.time() - t0, 1)
        log(f"[sightlines-3d] {mname}: {N} cells, {len(r)} edges ({edges_from}), {ncomp} components, {self.seconds} s")

    def cells(self, xy) -> tuple[np.ndarray, np.ndarray]:
        """The lowest standable cell of each point's grid column (else the
        nearest column's), and the point's distance (m) to its centre."""
        import sightlines_3d as s3
        xy = np.asarray(xy, float).reshape(-1, 2)
        g = np.floor((xy - self.lo[None, :2]) / s3.GRID_CM).astype(np.int64)
        inb = (g[:, 0] >= 0) & (g[:, 0] < self.gshape[0]) & (g[:, 1] >= 0) & (g[:, 1] < self.gshape[1])
        k = g[:, 0] * self.gshape[1] + g[:, 1]
        pos = np.clip(np.searchsorted(self._colkey, k), 0, len(self._colkey) - 1)
        hit = inb & (self._colkey[pos] == k)
        _d, near = self._tree3.query(xy)
        cell = np.where(hit, self._colcell[pos], self._colcell[near]).astype(np.int64)
        return cell, np.linalg.norm(xy - self.cell_xy[cell], axis=1) / UNITS_PER_M

    def los_near(self, xy_a, xy_b) -> np.ndarray:
        """Strict: the 3D table needs no registration tolerance."""
        return self.los(self.cells(xy_a)[0], self.cells(xy_b)[0])

    def vis_near(self, xy) -> np.ndarray:
        return self.los_rows(self.cells(xy)[0])


def _gate_row(tool: str, part: str, version: str) -> dict | None:
    """The latest pass row of a ledger series written by `version`."""
    from reticle import metrics
    rows = [r for r in metrics.load() if r.get("tool") == tool and r.get("part") == part
            and r.get("status") == "pass" and (r.get("deps") or {}).get("version") == version]
    return rows[-1] if rows else None


def choose(args=None) -> dict:
    """2D or 3D per map (see the module docstring); writes `choice.json`."""
    import sightlines_3d as s3
    out = {"rule": "3d where sightlines_3d/gate/<map> (the map's table version, development gun kills, exact "
                   "positions) gives los3d_share_on_2d_set > los2d_share; 2d otherwise; 3d where no 2D table exists",
           "sightlines": VERSION, "sightlines_3d": s3.VERSION, "maps": {}}
    for m in sorted(s3.CODENAMES):
        has2, has3 = table_path(m) is not None and table_path(m).is_file(), s3.out_path(m).is_file()
        tv = s3.table_version(m)
        g = _gate_row("sightlines_3d", f"gate/{m}", tv) if has3 else None
        gc = _gate_row("sightlines_3d", f"gate_confirm/{m}", tv) if has3 else None
        row = {"has_2d": has2, "has_3d": has3, "table_version": tv}
        if g:
            v = g["values"]
            row["gate"] = {"at": g["at"], "los3d_share_on_2d_set": v.get("los3d_share_on_2d_set"),
                           "los2d_share": v.get("los2d_share"), "los2d_n": v.get("los2d_n"),
                           "control_los3d_share": v.get("control_los3d_share"),
                           "control_los2d_share": v.get("control_los2d_share")}
        if gc:
            v = gc["values"]
            row["instrument_check"] = {"at": gc["at"], "set": "confirmation history, instrument check only",
                                       "gun_kills_resolved": v.get("gun_kills_resolved"),
                                       "los3d_share": v.get("los3d_share"),
                                       "control_los3d_share": v.get("control_los3d_share")}
        if has3 and not has2:
            row["kind"], row["why"] = "3d", "no baked 2D geometry: the 3D table is the only instrument"
        elif has3 and has2 and g and g["values"].get("los2d_share") is not None:
            beats = g["values"]["los3d_share_on_2d_set"] > g["values"]["los2d_share"]
            row["kind"] = "3d" if beats else "2d"
            row["why"] = "the 3D gate beats 2D on the same development kills" if beats else \
                "the 3D gate does not beat 2D on the same development kills"
        elif has2:
            row["kind"], row["why"] = "2d", "no 3D table or no 3D development gate of this version"
        else:
            row["kind"], row["why"] = None, "no table"
        out["maps"][m] = row
    print(json.dumps(out, indent=1))
    CHOICE_PATH.write_text(json.dumps(out, indent=1), encoding="utf-8")
    if args is not None and getattr(args, "record", False):
        from reticle import metrics
        vals = {f"{m}.uses_3d": int(r["kind"] == "3d") for m, r in out["maps"].items() if r["kind"]}
        metrics.record("sightlines", part="choice", values=vals,
                       deps={"version": VERSION, "sightlines_3d": s3.VERSION, "source": source_hash()},
                       context={"rule": out["rule"], "path": str(CHOICE_PATH)},
                       note="per-map 2D/3D choice that sightlines.load reads")
    return out


def dev_maps(store: Path = STORE) -> Counter:
    ref = api_reference(store)
    recs = rgt.riot_records(store)
    return Counter(ref.map_of(d["match"]["matchInfo"]["mapId"])["displayName"].lower()
                   for d in recs.values())


# ----------------------------------------------------------------- the instrument gate

def gun_kills(store: Path = STORE):
    """Every development-set gun kill: (sid, map, killer xy, victim xy, round,
    roundTime, the killer's other living enemies' xy)."""
    ref = api_reference(store)
    rows = []
    for sid, d in sorted(rgt.riot_records(store).items()):
        mname = ref.map_of(d["match"]["matchInfo"]["mapId"])["displayName"].lower()
        team = {p["subject"]: p["teamId"] for p in d["match"]["players"]}
        for k in d["match"]["kills"]:
            if ((k.get("finishingDamage") or {}).get("damageType")) != "Weapon":
                continue
            locs = k.get("playerLocations") or ()
            kl = next((p["location"] for p in locs if p["subject"] == k["killer"]), None)
            vl = k.get("victimLocation")
            if kl is None or vl is None or k["killer"] == k["victim"]:
                rows.append((sid, mname, None, None, k.get("round"), k.get("roundTime"), []))
                continue
            enemies = [(p["location"]["x"], p["location"]["y"]) for p in locs
                       if p["subject"] not in (k["killer"], k["victim"])
                       and team.get(p["subject"]) != team.get(k["killer"])]
            rows.append((sid, mname, (kl["x"], kl["y"]), (vl["x"], vl["y"]), k.get("round"),
                         k.get("roundTime"), enemies))
    return rows


def gate(args) -> dict:
    rows = gun_kills()
    by_map: dict[str, list] = {}
    for r in rows:
        by_map.setdefault(r[1], []).append(r)
    res, fails = {}, []
    for mname, rs in sorted(by_map.items()):
        S = load_2d(mname)
        if S is None:
            res[mname] = {"no_table": len(rs)}
            continue
        ok = [r for r in rs if r[2] is not None]
        K = np.array([r[2] for r in ok], float)
        V = np.array([r[3] for r in ok], float)
        ck, dk = S.cells(K)
        cv, dv = S.cells(V)
        los = S.los(ck, cv)
        # the 3x3 neighbourhood of both ends: a one-cell tolerance on position
        nb = S.los_near(K, V) | los
        # specificity control: the killer against his other living enemies
        ci = np.array([i for i, r in enumerate(ok) for _ in r[6]], int)
        CE = np.array([e for r in ok for e in r[6]], float).reshape(-1, 2)
        ctrl = S.los(ck[ci], S.cells(CE)[0]) if len(ci) else np.zeros(0, bool)
        ctrl_nb = (S.los_near(K[ci], CE) | ctrl) if len(ci) else np.zeros(0, bool)
        off = (dk > OFF_GRID_M) | (dv > OFF_GRID_M)
        dm = np.hypot(*(K - V).T) / UNITS_PER_M
        # post hoc diagnostics, at the exact positions rather than cells: the
        # same mask, and the mask with boxes opened (walls only)
        variants = {}
        with np.load(geom.path(S.key, STORE)) as z:
            labels, occ = z["labels"], z["occ"]
        fl = np.isin(labels, (FLOOR, PLANT))
        for vname, bb in (("exact", True), ("exact_walls_only", False)):
            pm = passable_from(labels, fl, occ, boxes_block=bb)
            _d, (iy, ix) = ndimage.distance_transform_edt(~pm, return_indices=True)

            def snap(p, pm=pm, iy=iy, ix=ix):
                q = np.rint(p).astype(int)
                q[:, 0] = q[:, 0].clip(0, pm.shape[1] - 1)
                q[:, 1] = q[:, 1].clip(0, pm.shape[0] - 1)
                return np.column_stack([ix[q[:, 1], q[:, 0]], iy[q[:, 1], q[:, 0]]]).astype(float)
            variants[vname] = segments_clear(pm, snap(apply_affine(S.A, K)), snap(apply_affine(S.A, V)))
        res[mname] = {"gun_kills": len(rs), "with_positions": len(ok),
                      "los": int(los.sum()), "los_share": round(float(los.mean()), 4),
                      "los_share_one_cell_tolerance": round(float(nb.mean()), 4),
                      "off_grid_end": int(off.sum()),
                      "los_share_on_grid": round(float(los[~off].mean()), 4) if (~off).any() else None,
                      "control_pairs": int(len(ci)),
                      "control_los_share": round(float(ctrl.mean()), 4) if len(ci) else None,
                      "control_los_share_one_cell_tolerance": round(float(ctrl_nb.mean()), 4) if len(ci) else None,
                      "post_hoc_exact_share": round(float(variants["exact"].mean()), 4),
                      "post_hoc_exact_walls_only_share": round(float(variants["exact_walls_only"].mean()), 4),
                      "post_hoc_cells_or_walls_only_one_cell": round(float((nb | variants["exact_walls_only"]).mean()), 4),
                      "median_kill_m": round(float(np.median(dm)), 1),
                      "median_kill_m_failed": round(float(np.median(dm[~los])), 1) if (~los).any() else None}
        for i in np.flatnonzero(~los):
            fails.append((mname, ok[i], int(ck[i]), int(cv[i]), float(dk[i]), float(dv[i]),
                          bool(nb[i]), float(dm[i])))
    tot = {k: sum(v.get(k, 0) for v in res.values() if isinstance(v, dict))
           for k in ("gun_kills", "with_positions", "los", "off_grid_end")}
    tot["los_share"] = round(tot["los"] / max(1, tot["with_positions"]), 4)
    mv = [v for v in res.values() if isinstance(v, dict) and "los_share" in v]
    for key, wkey in (("los_share_one_cell_tolerance", "with_positions"),
                      ("post_hoc_exact_walls_only_share", "with_positions"),
                      ("post_hoc_cells_or_walls_only_one_cell", "with_positions"),
                      ("control_los_share", "control_pairs"),
                      ("control_los_share_one_cell_tolerance", "control_pairs")):
        w = sum(v[wkey] for v in mv)
        tot[key] = round(sum(v[key] * v[wkey] for v in mv) / max(1, w), 4)
    tot["control_pairs"] = sum(v["control_pairs"] for v in mv)
    res["all"] = tot
    print(json.dumps(res, indent=1))
    if args.renders:
        render_failures(fails, Path(args.renders), args.n_renders)
    if args.record:
        from reticle import metrics
        vals = {f"{m}.los_share": v["los_share"] for m, v in res.items()
                if m != "all" and "los_share" in v}
        vals.update({f"{m}.gun_kills": v["with_positions"] for m, v in res.items()
                     if m != "all" and "with_positions" in v})
        vals.update({f"{m}.los_share_one_cell": v["los_share_one_cell_tolerance"]
                     for m, v in res.items() if m != "all" and "los_share" in v})
        vals.update({"all.los_share": tot["los_share"], "all.gun_kills": tot["with_positions"],
                     "all.off_grid_end": tot["off_grid_end"]})
        vals.update({f"all.{k}": tot[k] for k in (
            "los_share_one_cell_tolerance", "control_los_share", "control_los_share_one_cell_tolerance",
            "control_pairs")})
        vals.update({f"post_hoc:all.{k}": tot[k] for k in (
            "post_hoc_exact_walls_only_share", "post_hoc_cells_or_walls_only_one_cell")})
        stamps = {m: load_2d(m).stamps.get("occ_built_by") for m in res if m != "all" and load_2d(m)}
        metrics.record("sightlines", part="gate", values=vals,
                       deps={"version": VERSION, "source": source_hash(), "cell_m": CELL_M,
                             "walk_share": WALK_SHARE, "step_px": STEP_PX,
                             "keys": sorted(load_2d(m).key for m in res if m != "all" and load_2d(m)),
                             "occ_built_by": stamps},
                       context={"set": "development: the 22 captured Riot records",
                                "gun_kill": "finishingDamage.damageType == Weapon, killer != victim"},
                       note="2D line of sight between the killer's and victim's cells at the kill instant")
    return res


def render_failures(fails, out: Path, n: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(7)
    pick = rng.choice(len(fails), size=min(n, len(fails)), replace=False) if fails else []
    lines = []
    for j, i in enumerate(sorted(pick)):
        mname, r, ck, cv, dk, dv, nb, dm = fails[i]
        S = load_2d(mname)
        with np.load(geom.path(S.key, STORE)) as z:
            img = cv2.cvtColor(z["static"], cv2.COLOR_RGB2BGR) if z["static"].ndim == 3 else z["static"]
            labels, occ = z["labels"], z["occ"]
        img = img.copy()
        passable = passable_from(labels, np.isin(labels, (FLOOR, PLANT)), occ)
        tint = img.copy()
        tint[~passable] = (tint[~passable] * 0.35).astype(np.uint8)
        tint[occ == 1] = (0, 0, 255)
        tint[occ == 2] = (0, 165, 255)
        sc = 3
        big = cv2.resize(tint, None, fx=sc, fy=sc, interpolation=cv2.INTER_NEAREST)  # display only
        pk = apply_affine(S.A, np.array([r[2]]))[0] * sc
        pv = apply_affine(S.A, np.array([r[3]]))[0] * sc
        rk, rv = S.cell_rep[ck] * sc, S.cell_rep[cv] * sc
        cv2.line(big, tuple(int(v) for v in rk), tuple(int(v) for v in rv), (255, 255, 0), 1)
        cv2.circle(big, tuple(int(v) for v in pk), 6, (0, 255, 0), 2)
        cv2.circle(big, tuple(int(v) for v in pv), 6, (255, 0, 255), 2)
        # crop round the segment, 40 widget px of margin
        lo = np.floor(np.minimum(pk, pv) - 40 * sc).astype(int).clip(0)
        hi = np.ceil(np.maximum(pk, pv) + 40 * sc).astype(int)
        big = big[lo[1]:hi[1], lo[0]:hi[0]]
        name = f"fail_{j:02d}_{mname}.png"
        cv2.imwrite(str(out / name), big)
        lines.append(f"{name}: map {mname}, round {r[4]}, roundTime {r[5]} ms, kill distance {dm:.1f} m, "
                     f"snap killer {dk:.2f} m victim {dv:.2f} m, one-cell tolerance clears: {nb}")
    (out / "index.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"rendered {len(lines)} failures to {out}")


# ----------------------------------------------------------------- confirmation-set maps

def confirmation_maps() -> dict:
    """Maps the confirmation set uses that have no baked geometry, with match
    counts; the held-out replay matches are excluded and counted."""
    import pyarrow.parquet as pq
    held = {f["file"].rsplit(".", 1)[0] for f in
            json.loads((STORE / "external" / "replays" / "manifest.json").read_text(encoding="utf-8"))["files"]
            if not f.get("capture_session")}
    t = pq.read_table(STORE / "external" / "ladder" / "henrikdev" / "v4" / "parsed" / "ladder-parse-0.2.0"
                      / "matches.parquet", columns=["match_id", "map", "captured"]).to_pylist()
    riot = {json.loads(p.read_text(encoding="utf-8"))["match"]["matchInfo"]["matchId"]
            for p in (STORE / "external" / "riot").glob("*.json")}
    keep = [r for r in t if r["match_id"] not in held and r["match_id"] not in riot and not r["captured"]]
    c = Counter(r["map"].lower() for r in keep)
    out = {"matches_listed": len(t), "held_out_excluded": sum(r["match_id"] in held for r in t),
           "captured_excluded": sum((r["match_id"] in riot) or bool(r["captured"]) for r in t),
           "matches": len(keep), "per_map": dict(sorted(c.items())),
           "no_geometry": {m: n for m, n in sorted(c.items()) if geometry_key(m) is None}}
    out["no_geometry_matches"] = sum(out["no_geometry"].values())
    print(json.dumps(out, indent=1))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("maps", nargs="*")
    sub.add_parser("info")
    g = sub.add_parser("gate")
    g.add_argument("--record", action="store_true")
    g.add_argument("--renders", default=None)
    g.add_argument("--n-renders", type=int, default=10)
    sub.add_parser("coverage")
    ch = sub.add_parser("choose")
    ch.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    if args.cmd == "build":
        ref = api_reference()
        maps = args.maps or sorted(dev_maps())
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for m in maps:
            t = build_map(m, ref)
            p = OUT_DIR / f"{str(t['key'])}.npz"
            np.savez_compressed(p, **t)
            print(f"  wrote {p} ({p.stat().st_size / 1e6:.1f} MB)")
    elif args.cmd == "info":
        for p in sorted(OUT_DIR.glob("*.npz")):
            S = Sightlines(p)
            print(f"{p.name}: {S.version}, {S.N} cells, {p.stat().st_size / 1e6:.1f} MB, "
                  f"{len(S.callout_names)} callouts, {int(S.region['sight'].max()) + 1} sightline regions, "
                  f"largest component {np.bincount(S.comp).max()}")
    elif args.cmd == "gate":
        gate(args)
    elif args.cmd == "coverage":
        confirmation_maps()
    elif args.cmd == "choose":
        choose(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
