"""What the capturing team can believe about unseen enemies, measured on truth.

Two beliefs about each enemy, from his last sight (or from his spawn at buy
end): the **reachable set**, every walk-graph cell he could have reached at
the game's top run speed, and the **vision-pruned set**, the same less every
cell a living teammate observes at each step, so an enemy never passes a
watched choke unseen. Over them: the time each belief takes to cover the map
(after which it is "unknown"), the team's **map control** (cells no living
enemy could be in unseen) and its **holes** (a teammate's flank open when
some enemy's pruned set reaches within 10 m walk of him). `fidelity` rebuilds
the observed masks from teammate poses read at lower rates.

Truth only: the replay layer, `episodes.sight` and the map's 3D sightline
table (`prototypes/sightlines_3d.py`). The held-out replay is never read.
Predictions CQ11, CQ14-CQ16 (task `coaching-questions-20261006`). The design
is docs/COACHING_QUESTIONS.md section 4.

    python prototypes/coaching_belief.py run [MATCH ...] [--all]
    python prototypes/coaching_belief.py report [--record]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import coaching_questions as cq  # noqa: E402
import sightlines_3d as s3  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "coaching-belief-0.1.0"
OUT = cq.OUT
V_CMS = 675.0 * 1.25          # top run speed [domain:game_data/character-movement-speeds] x the graph's path factor (revision-2)
JUMP_CM, DROP_CM, BRIDGE_CM = 120.0, 600.0, 150.0   # [domain:game_data/character-jump] 1.15 m
STEP_MS = 250.0
EYE_FLOOR_CM = 100.0          # replay z above the cell floor (frame check, b03fecd3)
SPAWN_M = 5.0
HOLE_M = 10.0
HFOV = 103.0
DT_S = (1, 2, 3, 5, 8, 12, 20)
COLLAPSE = 0.9
RATES = (4.0, 1.0, 0.5, 0.25)


def display_name(map_url: str) -> str:
    m = json.loads((Path(DEFAULT_STORE) / "external" / "valorant-api" / "maps.json").read_text(encoding="utf-8"))
    m = m.get("data", m) if isinstance(m, dict) else m
    code = map_url.rstrip("/").split("/")[-1]
    return next(x["displayName"] for x in m if (x.get("mapUrl") or "").split("/")[-1] == code).lower()


class Grid:
    """One map's walk graph, visibility and step matrices."""

    def __init__(self, name: str):
        from scipy.spatial import cKDTree
        t0 = time.time()
        D = s3.load(name)
        self.name, self.version = name, s3.table_version(name)
        self.xy = D["cell_xy"].astype(np.float64)
        self.z = D["cell_z"].astype(np.float64)
        N = self.N = len(self.z)
        r, c = D["walk_r"].astype(np.int64), D["walk_c"].astype(np.int64)
        r, c = np.concatenate([r, c]), np.concatenate([c, r])
        # jump-ups and drops the table's walk edges leave out (revision-2)
        P = cKDTree(self.xy).query_pairs(BRIDGE_CM, output_type="ndarray")
        i, j = P[:, 0], P[:, 1]
        dz = self.z[j] - self.z[i]
        up = np.abs(dz) <= JUMP_CM
        di = (dz < -JUMP_CM) & (dz >= -DROP_CM)       # i above j: drop i -> j
        dj = (dz > JUMP_CM) & (dz <= DROP_CM)
        r = np.concatenate([r, i[up], j[up], i[di], j[dj]])
        c = np.concatenate([c, j[up], i[up], j[di], i[dj]])
        w = np.linalg.norm(np.column_stack([self.xy[r] - self.xy[c], self.z[r] - self.z[c]]), axis=1)
        key = r * N + c
        _u, first = np.unique(key, return_index=True)
        r, c, w = r[first], c[first], w[first]
        self.G = sparse.csr_matrix((w, (r, c)), shape=(N, N))
        self.AT = sparse.csr_matrix((np.ones(r.size, np.float32), (c, r)), shape=(N, N))  # B_next = AT @ B
        tri = np.unpackbits(D["vis_bits"], count=N * (N - 1) // 2).astype(bool)
        M = np.zeros((N, N), bool)
        M[np.triu(np.ones((N, N), bool), 1)] = tri
        del tri
        M |= M.T
        np.fill_diagonal(M, True)
        self.vis = np.packbits(M, axis=1)
        del M
        self.callout = D["cell_callout"].astype(np.int64) if "cell_callout" in D else np.full(N, -1)
        self.Rh = self._within(HOLE_M * 100.0)
        self._tree = cKDTree(self.xy)
        self.seconds = round(time.time() - t0, 1)

    def _within(self, lim_cm: float) -> sparse.csr_matrix:
        """Row p: the cells whose walk to p is within the limit."""
        rows, cols = [], []
        GT = self.G.T.tocsr()
        for b0 in range(0, self.N, 256):
            idx = np.arange(b0, min(self.N, b0 + 256))
            d = dijkstra(GT, directed=True, indices=idx, limit=lim_cm)
            i, j = np.nonzero(np.isfinite(d))
            rows.append(idx[i])
            cols.append(j)
        r, c = np.concatenate(rows), np.concatenate(cols)
        return sparse.csr_matrix((np.ones(r.size, np.float32), (r, c)), shape=(self.N, self.N))

    def cell(self, x, y, z) -> np.ndarray:
        """Each position's cell: of its 6 nearest in xy, the floor nearest
        EYE_FLOOR_CM below it; -1 where the position is unread."""
        x, y, z = (np.atleast_1d(np.asarray(a, float)) for a in (x, y, z))
        out = np.full(x.size, -1, np.int64)
        ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
        if ok.any():
            _d, i = self._tree.query(np.column_stack([x[ok], y[ok]]), k=6)
            dz = np.abs(self.z[i] - (z[ok, None] - EYE_FLOOR_CM))
            out[ok] = i[np.arange(i.shape[0]), np.argmin(dz, axis=1)]
        return out

    def observed(self, cells: np.ndarray, x, y, yaw) -> np.ndarray:
        """Cells some of the given players see within their horizontal FOV."""
        out = np.zeros(self.N, bool)
        for c, px, py, yw in zip(cells, x, y, yaw):
            if c < 0 or not np.isfinite(yw):
                continue
            row = np.unpackbits(self.vis[c], count=self.N).astype(bool)
            ang = np.degrees(np.arctan2(self.xy[:, 1] - py, self.xy[:, 0] - px))
            d = np.abs(((ang - yw) + 180.0) % 360.0 - 180.0)
            near = np.hypot(self.xy[:, 0] - px, self.xy[:, 1] - py) < 150.0
            out |= row & ((d <= HFOV / 2.0) | near)
        return out


def _km_median(times: list[float], events: list[bool]) -> float | None:
    """Kaplan-Meier median of event times with right censoring."""
    if not times:
        return None
    t = np.asarray(times, float)
    e = np.asarray(events, bool)
    o = np.argsort(t)
    t, e = t[o], e[o]
    s, n = 1.0, t.size
    for k in range(t.size):
        if e[k]:
            s *= 1.0 - 1.0 / (n - k)
            if s <= 0.5:
                return float(t[k])
    return None


def _poses(M, C, steps, rate):
    """Teammate x, y, z, yaw at the steps from reads at `rate` Hz (positions
    linear between reads, yaw from the nearer read); rate 4 reads every step."""
    smp = M.tl0.sample(steps)
    if rate >= 4.0:
        return smp
    out = {k: smp[k].copy() for k in ("x", "y", "z", "yaw")}
    period = 1000.0 / rate
    ci = np.flatnonzero(M.team == C)
    k = np.floor((steps - steps[0]) / period)
    t_lo = steps[0] + k * period
    t_hi = t_lo + period
    lo, hi = M.tl0.sample(t_lo), M.tl0.sample(np.minimum(t_hi, steps[-1]))
    w = np.clip((steps - t_lo) / period, 0.0, 1.0)
    for s in ci:
        for key in ("x", "y", "z"):
            a, b = lo[key][s], hi[key][s]
            out[key][s] = np.where(np.isfinite(b), a * (1 - w) + b * w, a)
        out["yaw"][s] = np.where(w < 0.5, lo["yaw"][s], hi["yaw"][s])
    return out


def run_perspective(M, grid: Grid, C: str, rate: float, deaths: list) -> dict:
    """Propagate every enemy's beliefs through each round for team C."""
    drawn = M.drawn(C)
    ci = np.flatnonzero(M.team == C)
    ei = np.flatnonzero(M.team != C)
    rec = defaultdict(list)
    for r in M.rounds:
        if r["t_live"] is None:
            continue
        steps = np.arange(r["t_live"], r["t_next"], STEP_MS)
        if steps.size < 2:
            continue
        truth = M.tl0.sample(steps)
        pose = _poses(M, C, steps, rate)
        alive = M.tl0._alive_fn(steps)
        cells_true = np.stack([grid.cell(truth["x"][s], truth["y"][s], truth["z"][s]) for s in range(len(M.slots))])
        cells_pose = np.stack([grid.cell(pose["x"][s], pose["y"][s], pose["z"][s]) for s in range(len(M.slots))])
        gk = np.clip(np.searchsorted(M.G, steps, side="right") - 1, 0, M.G.size - 1)
        dr = drawn[:, gk] & (M.G_round[gk] == r["round"])[None, :]
        start = cells_true[:, 0]
        comp_cells = np.zeros(grid.N, bool)
        seeds = start[start >= 0]
        if seeds.size:
            dd = dijkstra(grid.G, directed=True, indices=np.unique(seeds), min_only=True)
            comp_cells = np.isfinite(dd)
        ncomp = max(int(comp_cells.sum()), 1)
        B = np.zeros((grid.N, ei.size), bool)
        U0 = np.zeros((grid.N, ei.size), bool)
        for j, e in enumerate(ei):
            if start[e] >= 0 and alive[e, 0]:
                d5 = dijkstra(grid.G, directed=True, indices=start[e], limit=SPAWN_M * 100.0)
                B[:, j] = np.isfinite(d5)
                U0[:, j] = B[:, j]
        since = np.zeros(ei.size)
        origin = np.array(["spawn"] * ei.size, object)
        open_prev = {s: False for s in ci}
        run_len = {s: 0 for s in ci}
        mates_at_last = np.full(ei.size, -1)
        obs_share_at_last = np.full(ei.size, np.nan)
        collapsed = np.zeros(ei.size, bool)
        for k in range(steps.size):
            live_c = [s for s in ci if alive[s, k]]
            obs = grid.observed(cells_pose[live_c, k], pose["x"][live_c, k], pose["y"][live_c, k],
                                pose["yaw"][live_c, k]) if live_c else np.zeros(grid.N, bool)
            if k > 0:
                for _h in range(2 if k % 2 else 1):
                    B = (B | ((grid.AT @ B.astype(np.float32)) > 0)) & ~obs[:, None]
                    U0 = U0 | ((grid.AT @ U0.astype(np.float32)) > 0)
                since += STEP_MS / 1000.0
            free = max(int((comp_cells & ~obs).sum()), 1)
            for j, e in enumerate(ei):
                if not alive[e, k]:
                    if origin[j] == "sight" and not collapsed[j] and since[j] > 0:
                        rec["collapse"].append({"t": float(since[j]), "event": False, "mates": int(mates_at_last[j]),
                                                "obs_share": float(obs_share_at_last[j]), "map": grid.name})
                        collapsed[j] = True
                    B[:, j] = False
                    U0[:, j] = False
                    continue
                c = cells_true[e, k]
                if dr[e, k] and c >= 0:
                    if since[j] > 0 and not collapsed[j] and origin[j] == "sight":
                        rec["collapse"].append({"t": float(since[j]), "event": False, "mates": int(mates_at_last[j]),
                                                "obs_share": float(obs_share_at_last[j]), "map": grid.name})
                    B[:, j] = False
                    U0[:, j] = False
                    B[c, j] = True
                    U0[c, j] = True
                    since[j] = 0.0
                    origin[j] = "sight"
                    collapsed[j] = False
                    mates_at_last[j] = len(live_c)
                    obs_share_at_last[j] = float((obs & comp_cells).sum() / ncomp)
                    continue
                if c >= 0:
                    nb, nu = int(B[:, j].sum()), int(U0[:, j].sum())
                    cov = nb / free
                    rec["track"].append((origin[j] == "sight", since[j], bool(B[c, j]), bool(U0[c, j]),
                                         nb / ncomp, nu / ncomp, cov))
                    if origin[j] == "sight" and not collapsed[j] and cov >= COLLAPSE:
                        collapsed[j] = True
                        rec["collapse"].append({"t": float(since[j]), "event": True, "mates": int(mates_at_last[j]),
                                                "obs_share": float(obs_share_at_last[j]), "map": grid.name})
            U = B[:, [j for j, e in enumerate(ei) if alive[e, k]]].any(axis=1) if ei.size else np.zeros(grid.N, bool)
            ctrl = 1.0 - float((U & comp_cells).sum()) / ncomp
            rec["control"].append((r["round"], float(steps[k] - r["t_live"]), ctrl))
            Uf = U.astype(np.float32)
            for s in ci:
                if not alive[s, k] or cells_pose[s, k] < 0:
                    continue
                op = bool(grid.Rh[cells_pose[s, k]].dot(Uf)[0] > 0)
                rec["flank"].append((r["round"], M.sid[s], float(steps[k]), op))
                if op:
                    run_len[s] += 1
                elif open_prev[s] and run_len[s]:
                    rec["holes"].append(run_len[s] * STEP_MS / 1000.0)
                    run_len[s] = 0
                open_prev[s] = op
        for s in ci:
            if run_len[s]:
                rec["holes"].append(run_len[s] * STEP_MS / 1000.0)
        for j in range(ei.size):
            if origin[j] == "sight" and not collapsed[j] and since[j] > 0:
                rec["collapse"].append({"t": float(since[j]), "event": False, "mates": int(mates_at_last[j]),
                                        "obs_share": float(obs_share_at_last[j]), "map": grid.name})
    return rec


BINS = (0, 1, 2, 3, 5, 8, 12, 20, 30, 45, 60, 1e9)


def summarise_track(track: list) -> dict:
    """Containment and size by time since the last sight (or buy end)."""
    out = {}
    if not track:
        return out
    a = np.array(track, dtype=float)
    for org, name in ((1.0, "sight"), (0.0, "spawn")):
        sel = a[a[:, 0] == org]
        b = np.digitize(sel[:, 1], BINS) - 1
        for k in range(len(BINS) - 1):
            m = sel[b == k]
            if len(m):
                out[f"{name}:{BINS[k]:g}"] = {"n": int(len(m)), "in_pruned": float(m[:, 2].mean()),
                                              "in_unpruned": float(m[:, 3].mean()), "size_pruned": float(m[:, 4].mean()),
                                              "size_unpruned": float(m[:, 5].mean()), "cov_free": float(m[:, 6].mean())}
    return out


def reach_exact(M, grid: Grid, C: str) -> list:
    """CQ11: from each drawn run's last sight, exact walk distances; the
    true cell's containment at each dt, the set's size and the saturation."""
    drawn = M.drawn(C)
    ci = np.flatnonzero(M.team == C)
    ei = np.flatnonzero(M.team != C)
    vis = M.sees[ci].any(axis=0)
    out = []
    for e in ei:
        for a, b in cq._true_runs(drawn[e]):
            rn = M.G_round[a]
            seen = np.flatnonzero(vis[e, a:b + 1])
            if not seen.size:
                continue
            k0 = a + seen[-1]
            t0 = M.G[k0]
            c0 = grid.cell(M.X[e, k0], M.Y[e, k0], M.Z[e, k0])[0]
            if c0 < 0:
                continue
            d = dijkstra(grid.G, directed=True, indices=c0)
            comp = np.isfinite(d)
            dc = d[comp]
            regs = grid.callout[comp]
            nreg = max(len(np.unique(regs[regs >= 0])), 1)
            sat = float(np.quantile(dc, COLLAPSE) / V_CMS)
            reg_first = {}
            for rr in np.unique(regs[regs >= 0]):
                reg_first[rr] = dc[regs == rr].min()
            rsat = float(np.quantile(np.array(list(reg_first.values())), COLLAPSE) / V_CMS) if reg_first else None
            nxt = np.flatnonzero(drawn[e, b + 1:] & (M.G_round[b + 1:] == rn))
            t_end = M.G[b + 1 + nxt[0]] if nxt.size else None
            rows = []
            for dt in cq_dt():
                t = t0 + dt * 1000.0
                if t_end is not None and t >= t_end:
                    break
                al = M.tl0._alive_fn(np.array([t]))[e, 0]
                if not al:
                    break
                smp = M.tl0.sample(np.array([t]))
                c = grid.cell(smp["x"][e, 0], smp["y"][e, 0], smp["z"][e, 0])[0]
                if c < 0:
                    continue
                rows.append({"dt": dt, "in_full": bool(d[c] <= V_CMS * dt), "in_half": bool(d[c] <= V_CMS * dt / 2),
                             "size_full": float((dc <= V_CMS * dt).mean()), "size_half": float((dc <= V_CMS * dt / 2).mean())})
            nd = M.tl0._alive_fn(np.array([t0 + 1.0]))
            out.append({"map": grid.name, "sat_s": sat, "region_sat_s": rsat, "rows": rows,
                        "unseen_s": (None if t_end is None else float((t_end - t0) / 1000.0)),
                        "mates": int(sum(nd[s, 0] for s in ci))})
    return out


def cq_dt():
    return DT_S


def run_matches(keys: list[str], out_path: Path) -> None:
    grids = {}
    for key in keys:
        t0 = time.time()
        M = cq.Match(key)
        name = display_name(M.tl0.map)
        if name not in grids:
            grids.clear()
            grids[name] = Grid(name)
        grid = grids[name]
        deaths = [x for x in M.tl0.events if x.kind == "death"]
        res = {"version": VERSION, "match": M.tl0.match, "map": name, "grid": grid.version, "perspectives": {}}
        team_of = {s.slot_id: s.team for s in M.slots}
        for C in M.teams:
            p = {"reach": reach_exact(M, grid, C), "rates": {}}
            ref = None
            for rate in RATES:
                rec = run_perspective(M, grid, C, rate, deaths)
                track = rec.pop("track", [])
                summ = {"track": summarise_track(track),
                        "containment_pruned": float(np.mean([t[2] for t in track])) if track else None,
                        "containment_unpruned": float(np.mean([t[3] for t in track])) if track else None,
                        "n_track": len(track)}
                if ref is None:
                    ref = rec
                    summ.update({"control": rec["control"], "flank": rec["flank"], "holes": rec["holes"],
                                 "collapse": rec["collapse"]})
                else:
                    c0 = np.array([x[2] for x in ref["control"]])
                    c1 = np.array([x[2] for x in rec["control"]])
                    f0 = {(x[1], x[2]): x[3] for x in ref["flank"]}
                    both = [(f0[(x[1], x[2])], x[3]) for x in rec["flank"] if (x[1], x[2]) in f0]
                    summ.update({"control_mae": float(np.abs(c0 - c1).mean()) if c0.size == c1.size else None,
                                 "flank_agree": float(np.mean([a == b for a, b in both])) if both else None,
                                 "flank_n": len(both), "holes_n": len(rec["holes"])})
                p["rates"][str(rate)] = summ
            # the deaths of C players to enemies, for the hazard
            p["deaths"] = [(d.t_ms, d.target) for d in deaths
                           if team_of.get(d.target) == C and d.actor in team_of and team_of[d.actor] != C]
            res["perspectives"][C] = p
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res, default=cq._jd) + "\n")
        print(f"{key[:8]} {name}: {time.time() - t0:.0f} s (grid {grid.seconds} s, {grid.N} cells)", flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("matches", nargs="*")
    r.add_argument("--all", action="store_true")
    r.add_argument("--out", default=str(OUT / "belief.jsonl"))
    rp = sub.add_parser("report")
    rp.add_argument("--record", action="store_true")
    rp.add_argument("--path", default=str(OUT / "belief.jsonl"))
    a = ap.parse_args(argv)
    cq._idle()
    if a.cmd == "run":
        full = cq.replay_matches()
        keys = full if a.all else [next(m for m in full if m.startswith(k)) for k in a.matches]
        out = Path(a.out)
        done = set()
        if out.is_file():
            done = {json.loads(s)["match"] for s in out.read_text(encoding="utf-8").splitlines() if s.strip()}
        for k in keys:
            if k not in done:
                run_matches([k], out)
        return 0
    return report(Path(a.path), a.record)


def report(path: Path, record: bool) -> int:
    raise SystemExit("report: to write")


if __name__ == "__main__":
    raise SystemExit(main())
