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
    python prototypes/coaching_belief.py priors [MATCH ...] [--all]
    python prototypes/coaching_belief.py report-priors [--record]
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
JUMP_CM, DROP_CM, BRIDGE_CM, GAP_CM = 120.0, 600.0, 150.0, 215.0   # [domain:game_data/character-jump] 1.15 m
STEP_MS = 250.0
HOPS = (1, 2)                 # masked hops at odd and even steps, six a second: contains the exact reach (revision-4)
EYE_FLOOR_CM = 100.0          # replay z above the cell floor (frame check, b03fecd3)
SPAWN_M = 5.0
HOLE_M = 10.0
HFOV = 103.0
DT_S = (1, 2, 3, 5, 8, 10, 12, 20)
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
        tri = np.unpackbits(D["vis_bits"], count=N * (N - 1) // 2).astype(bool)
        M = np.zeros((N, N), bool)
        M[np.triu(np.ones((N, N), bool), 1)] = tri
        del tri
        M |= M.T
        np.fill_diagonal(M, True)
        self.vis = np.packbits(M, axis=1)
        del M
        r, c = D["walk_r"].astype(np.int64), D["walk_c"].astype(np.int64)
        r, c = np.concatenate([r, c]), np.concatenate([c, r])
        # gaps of one missing cell (barriers, doors) between cells that see each other (revision-4)
        P = cKDTree(self.xy).query_pairs(GAP_CM, output_type="ndarray")
        gi, gj = P[:, 0], P[:, 1]
        gap = (np.hypot(*(self.xy[gi] - self.xy[gj]).T) > BRIDGE_CM) & (np.abs(self.z[gi] - self.z[gj]) <= JUMP_CM)
        gi, gj = gi[gap], gj[gap]
        seen = ((self.vis[gi, gj >> 3] >> (7 - (gj & 7))) & 1).astype(bool)
        r = np.concatenate([r, gi[seen], gj[seen]])
        c = np.concatenate([c, gj[seen], gi[seen]])
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
                for _h in range(HOPS[k % 2]):
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


def reach_exact(M, grid: Grid, C: str, deaths: list) -> list:
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
            rnd = next((x for x in M.rounds if x["round"] == rn), None)
            t_next = rnd["t_next"] if rnd else t0
            t_die = next((x.t_ms for x in deaths if x.target == M.sid[e] and t0 < x.t_ms < t_next), None)
            ends = [t for t in (t_end, t_die) if t is not None]
            end_s = float((min(ends) if ends else t_next) - t0) / 1000.0
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
                        "end_s": end_s, "ended": bool(ends),
                        "mates": int(sum(nd[s, 0] for s in ci))})
    return out


def _round_meta(M) -> dict:
    """Each round's attacking team and winner, from the truth episodes."""
    from reticle import episodes as ep
    rows = ep.read_episodes(M.tl0.match)
    hdr = next(r for r in rows if r.get("row") == "header")
    att = {int(k): v for k, v in hdr["attack_team"].items()}
    out = {}
    for e in rows:
        if e.get("row") == "episode" and e["kind"] in ("phase_live", "phase_post_plant") and e.get("outcome"):
            out[int(e["round"])] = {"attack": att.get(int(e["round"])), "winner": e["outcome"].get("winner")}
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
        res["rounds"] = _round_meta(M)
        for C in M.teams:
            p = {"reach": reach_exact(M, grid, C, deaths), "rates": {}}
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
    pr = sub.add_parser("priors")
    pr.add_argument("matches", nargs="*")
    pr.add_argument("--all", action="store_true")
    pr.add_argument("--out", default=str(OUT / "priors.jsonl"))
    pp = sub.add_parser("report-priors")
    pp.add_argument("--record", action="store_true")
    pp.add_argument("--path", default=str(OUT / "priors.jsonl"))
    rp = sub.add_parser("report")
    rp.add_argument("--record", action="store_true")
    rp.add_argument("--path", default=str(OUT / "belief.jsonl"))
    a = ap.parse_args(argv)
    cq._idle()
    if a.cmd == "report-priors":
        return report_priors(Path(a.path), a.record)
    if a.cmd == "priors":
        full = cq.replay_matches()
        keys = full if a.all else [next(m for m in full if m.startswith(k)) for k in a.matches]
        out = Path(a.out)
        done = set()
        if out.is_file():
            done = {json.loads(x)["match"] for x in out.read_text(encoding="utf-8").splitlines() if x.strip()}
        run_priors([k for k in keys if k not in done], out)
        return 0
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


def _pool_bins(summs: list[dict]) -> dict:
    """Pool `summarise_track` bins across perspectives, weighted by n."""
    acc = defaultdict(lambda: defaultdict(float))
    for sm in summs:
        for b, o in (sm or {}).items():
            acc[b]["n"] += o["n"]
            for k in ("in_pruned", "in_unpruned", "size_pruned", "size_unpruned", "cov_free"):
                acc[b][k] += o[k] * o["n"]
    return {b: {"n": int(o["n"]), **{k: round(o[k] / o["n"], 4) for k in o if k != "n"}} for b, o in acc.items()}


def _boot_ratio(groups: list, n_boot: int = 1000, seed: int = 7):
    """Rate ratio (a/ea)/(b/eb) over per-perspective sums, perspective bootstrap."""
    g = np.array(groups, float)
    if not g.size:
        return None, None

    def stat(w):
        s = (g * w[:, None]).sum(axis=0)
        return (s[0] / s[1]) / (s[2] / s[3]) if s[1] and s[3] and s[2] else np.nan
    rng = np.random.default_rng(seed)
    W = rng.multinomial(len(g), np.full(len(g), 1.0 / len(g)), size=n_boot)
    b = np.array([stat(w) for w in W])
    b = b[np.isfinite(b)]
    return round(float(stat(np.ones(len(g)))), 4), ([round(float(np.percentile(b, 2.5)), 4),
                                                     round(float(np.percentile(b, 97.5)), 4)] if b.size else None)


def report(path: Path, record: bool) -> int:
    """CQ11, CQ14-CQ16 from `belief.jsonl`."""
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {"version": VERSION, "matches": len(rows), "maps": sorted({r["map"] for r in rows})}
    # CQ11: exact reach from the last sight
    by_dt = defaultdict(lambda: defaultdict(list))
    sat = defaultdict(list)
    rsat = defaultdict(list)
    ends, evs = [], []
    for r in rows:
        for p in r["perspectives"].values():
            for x in p["reach"]:
                sat[r["map"]].append(x["sat_s"])
                if x["region_sat_s"] is not None:
                    rsat[r["map"]].append(x["region_sat_s"])
                ends.append(x["end_s"])
                evs.append(x["ended"])
                for y in x["rows"]:
                    for k in ("in_full", "in_half", "size_full", "size_half"):
                        by_dt[y["dt"]][k].append(float(y[k]))
    out["reach"] = {str(dt): {"n": len(v["in_full"]), **{k: round(float(np.mean(a)), 4) for k, a in v.items()}}
                    for dt, v in sorted(by_dt.items())}
    out["saturation"] = {m: {"n": len(v), "sat_p50": round(float(np.median(v)), 2),
                             "region_sat_p50": round(float(np.median(rsat[m])), 2) if rsat[m] else None,
                             "region_sooner": (round(1.0 - float(np.median(rsat[m])) / float(np.median(v)), 4)
                                               if rsat[m] else None)}
                         for m, v in sorted(sat.items())}
    allsat = [x for v in sat.values() for x in v]
    out["saturation_all_p50"] = round(float(np.median(allsat)), 2) if allsat else None
    out["unseen_km_p50"] = _km_median(ends, evs)
    out["unseen_n"], out["unseen_ended"] = len(ends), int(sum(evs))
    # CQ14, CQ16: the propagated beliefs at each pose rate
    out["rates"] = {}
    for rate in RATES:
        rk = str(rate)
        summs = [p["rates"][rk]["track"] for r in rows for p in r["perspectives"].values() if rk in p["rates"]]
        bins = _pool_bins(summs)
        sight = {b: o for b, o in bins.items() if b.startswith("sight:")}
        n = sum(o["n"] for o in sight.values())
        o = {"bins": bins, "n_sight": n,
             "in_pruned_sight": round(sum(v["in_pruned"] * v["n"] for v in sight.values()) / n, 4) if n else None,
             "in_unpruned_sight": round(sum(v["in_unpruned"] * v["n"] for v in sight.values()) / n, 4) if n else None}
        if rate != RATES[0]:
            mae = [p["rates"][rk]["control_mae"] for r in rows for p in r["perspectives"].values()
                   if p["rates"].get(rk, {}).get("control_mae") is not None]
            fa = [(p["rates"][rk]["flank_agree"], p["rates"][rk]["flank_n"]) for r in rows
                  for p in r["perspectives"].values() if p["rates"].get(rk, {}).get("flank_agree") is not None]
            o["control_mae"] = round(float(np.mean(mae)), 4) if mae else None
            o["flank_agree"] = round(sum(a * b for a, b in fa) / sum(b for _a, b in fa), 4) if fa else None
        out["rates"][rk] = o
    b5 = out["rates"][str(RATES[0])]["bins"].get("sight:5")
    out["pruned_over_unpruned_5s"] = (round(b5["size_pruned"] / b5["size_unpruned"], 4)
                                      if b5 and b5["size_unpruned"] else None)
    # collapse, overall and by formation
    col = [c for r in rows for p in r["perspectives"].values() for c in p["rates"][str(RATES[0])]["collapse"]]

    def km(sel):
        return _km_median([c["t"] for c in sel], [c["event"] for c in sel])
    cl = {"n": len(col), "events": sum(c["event"] for c in col), "km_p50": km(col)}
    for m_lo, m_hi, name in ((0, 2, "mates_le2"), (3, 4, "mates_3to4"), (5, 5, "mates_5")):
        sel = [c for c in col if m_lo <= c["mates"] <= m_hi]
        cl[name] = {"n": len(sel), "events": sum(c["event"] for c in sel), "km_p50": km(sel)}
    obs = np.array([c["obs_share"] for c in col if np.isfinite(c["obs_share"])])
    if obs.size >= 3:
        q1, q2 = np.quantile(obs, [1 / 3, 2 / 3])
        for lo, hi, name in ((-1, q1, "obs_low"), (q1, q2, "obs_mid"), (q2, 2, "obs_high")):
            sel = [c for c in col if np.isfinite(c["obs_share"]) and lo < c["obs_share"] <= hi]
            cl[name] = {"n": len(sel), "events": sum(c["event"] for c in sel), "km_p50": km(sel),
                        "obs_max": round(float(hi), 4) if hi < 2 else None}
    out["collapse"] = cl
    # CQ15: control against round outcome; flank hazard; holes
    ctl_rows, hz, holes, opens = [], [], [], []
    for r in rows:
        meta = {int(k): v for k, v in r.get("rounds", {}).items()}
        for C, p in r["perspectives"].items():
            q = p["rates"][str(RATES[0])]
            best = {}
            for rn, trel, c in q["control"]:
                if rn not in best or abs(trel - 20000.0) < abs(best[rn][0] - 20000.0):
                    best[rn] = (trel, c)
            for rn, (trel, c) in best.items():
                mm = meta.get(int(rn))
                if mm is None or mm["winner"] is None or abs(trel - 20000.0) > STEP_MS:
                    continue
                ctl_rows.append({"m": r["match"], "side": "attack" if mm["attack"] == C else "defence",
                                 "c": c, "y": mm["winner"] == C})
            fl = defaultdict(list)
            for _rn, sid, t, op in q["flank"]:
                fl[sid].append((t, float(op)))
                opens.append(op)
            oa = ob = 0.0
            for sid in list(fl):
                a = np.array(fl[sid])
                fl[sid] = a[np.argsort(a[:, 0])]
                oa += float(a[:, 1].sum()) * STEP_MS / 1000.0
                ob += float((1 - a[:, 1]).sum()) * STEP_MS / 1000.0
            da = db = 0
            for t, sid in p["deaths"]:
                a = fl.get(sid)
                if a is None or not len(a):
                    continue
                k = np.searchsorted(a[:, 0], t, side="left") - 1
                if k < 0 or t - a[k, 0] > STEP_MS * 2:
                    continue
                if a[k, 1]:
                    da += 1
                else:
                    db += 1
            hz.append((da, oa, db, ob))
            holes.extend(q["holes"])
    if ctl_rows:
        for side in ("attack", "defence"):
            v = np.array([x["c"] for x in ctl_rows if x["side"] == side])
            if v.size >= 3:
                lo, hi = np.quantile(v, [1 / 3, 2 / 3])
                for x in ctl_rows:
                    if x["side"] == side:
                        x["t"] = 2 if x["c"] > hi else (0 if x["c"] <= lo else 1)
        tr = [{"m": x["m"], "z": x["side"], "a": x["t"] == 2, "y": x["y"]} for x in ctl_rows if x.get("t") in (0, 2)]
        out["control_value"] = cq._stratified(tr)
        out["control_value"]["control_p50"] = {
            s: round(float(np.median([x["c"] for x in ctl_rows if x["side"] == s])), 4)
            for s in ("attack", "defence") if any(x["side"] == s for x in ctl_rows)}
    rr, ci = _boot_ratio(hz)
    out["flank_hazard"] = {"deaths_open": int(sum(h[0] for h in hz)), "deaths_closed": int(sum(h[2] for h in hz)),
                           "open_s": round(sum(h[1] for h in hz), 1), "closed_s": round(sum(h[3] for h in hz), 1),
                           "rate_ratio": rr, "ci": ci}
    out["holes"] = {"n": len(holes), "p50_s": round(float(np.median(holes)), 2) if holes else None,
                    "p90_s": round(float(np.quantile(holes, 0.9)), 2) if holes else None,
                    "open_share": round(float(np.mean(opens)), 4) if opens else None}
    txt = json.dumps(out, indent=1, default=cq._jd)
    print(txt)
    (path.parent / (path.stem + "_report.json")).write_text(txt, encoding="utf-8")
    if record:
        _record(out, path)
    return 0


def _record(out: dict, path: Path) -> None:
    from reticle.metrics import record as rec
    deps = {"version": VERSION}
    ctx = {"task": "coaching-questions-20261006", "matches": out["matches"], "source": path.name}
    sess = f"pooled{out['matches']}"
    for dt, o in out["reach"].items():
        rec("coaching_belief", part=f"reach/dt{dt}", session=sess, values=o, deps=deps, context=ctx)
    for m, o in out["saturation"].items():
        rec("coaching_belief", part=f"saturation/{m}", session=sess,
            values={k: v for k, v in o.items() if v is not None}, deps=deps, context=ctx)
    rec("coaching_belief", part="unseen", session=sess, deps=deps, context=ctx,
        values={k: v for k, v in {"km_p50": out["unseen_km_p50"], "n": out["unseen_n"], "ended": out["unseen_ended"],
                                  "saturation_all_p50": out["saturation_all_p50"],
                                  "pruned_over_unpruned_5s": out["pruned_over_unpruned_5s"]}.items() if v is not None})
    for rk, o in out["rates"].items():
        vals = {k: v for k, v in o.items() if k != "bins" and v is not None}
        for b, bo in o["bins"].items():
            vals.update({f"{b.replace(':', '_')}s.{k}": v for k, v in bo.items()})
        rec("coaching_belief", part=f"belief/rate{rk}", session=sess, values=vals, deps=deps, context=ctx)
    flat = {}
    for k, v in out["collapse"].items():
        if isinstance(v, dict):
            flat.update({f"{k}.{a}": b for a, b in v.items() if b is not None})
        elif v is not None:
            flat[k] = v
    rec("coaching_belief", part="collapse", session=sess, values=flat, deps=deps, context=ctx)
    cv = out.get("control_value") or {}
    vals = {k: v for k, v in cv.items() if k not in ("ci", "control_p50") and v is not None}
    if cv.get("ci"):
        vals.update({"ci_lo": cv["ci"][0], "ci_hi": cv["ci"][1]})
    vals.update({f"control_p50.{k}": v for k, v in (cv.get("control_p50") or {}).items()})
    rec("coaching_belief", part="control_value", session=sess, values=vals, deps=deps, context=ctx)
    fh = dict(out["flank_hazard"])
    ci = fh.pop("ci")
    if ci:
        fh.update({"ci_lo": ci[0], "ci_hi": ci[1]})
    rec("coaching_belief", part="flank_hazard", session=sess, values={k: v for k, v in fh.items() if v is not None},
        deps=deps, context=ctx)
    rec("coaching_belief", part="holes", session=sess, values={k: v for k, v in out["holes"].items() if v is not None},
        deps=deps, context=ctx)


# ----------------------------------------------------------------- priors (CQ12)

PROBE_MS = 20000.0           # the probe: 20 s after buy end
CENSOR_MS = 2000.0           # censored history: drawn within 2 s of the probe
MIN_PREV = 3                 # previous same-side rounds before a region prediction counts
MIN_PREV_SITE = 2
MIN_PREV_LURK = 2


def _mode(xs: list):
    from collections import Counter
    xs = [x for x in xs if x is not None]
    return Counter(xs).most_common(1)[0][0] if xs else None


def _auc(score: np.ndarray, y: np.ndarray) -> float | None:
    from scipy.stats import rankdata
    n1, n0 = int(y.sum()), int((~y).sum())
    if not n1 or not n0:
        return None
    r = rankdata(score)
    return float((r[y].sum() - n1 * (n1 + 1) / 2.0) / (n1 * n0))


def priors_match(key: str) -> dict:
    """One replay's prior instances: region at the probe by history, the
    first execute's site, lurking, and the censored history's reach."""
    from reticle import episodes as ep
    M = cq.Match(key)
    reg = M.regions
    rows = ep.read_episodes(M.tl0.match)
    hdr = next(r for r in rows if r.get("row") == "header")
    att = {int(k): v for k, v in hdr["attack_team"].items()}
    eps = [r for r in rows if r.get("row") == "episode"]
    sites = sorted({x for x in (reg.super_labels if reg is not None else []) if x in ("A", "B", "C")})
    out = {"match": M.tl0.match, "map": M.tl0.map, "region": [], "site": [], "lurk": [], "censor": [],
           "sites": len(sites)}
    if reg is None:
        return out
    hist = defaultdict(list)            # (sid, side) -> supers, truth
    cens = defaultdict(list)            # (C, sid, side) -> supers seen by C
    side_hist = defaultdict(list)       # side -> every player's supers
    team_hist = defaultdict(list)       # (team, side) -> supers
    site_hist = defaultdict(list)       # team -> first-execute sites
    lurk_hist = defaultdict(list)       # sid -> 0/1 per attack round
    drawn = {C: M.drawn(C) for C in M.teams}
    for r in M.rounds:
        rn = r["round"]
        if r["t_live"] is None or rn not in att:
            continue
        tp = r["t_live"] + PROBE_MS
        if tp >= r["t_next"]:
            continue
        smp = M.tl0.sample(np.array([tp]))
        pts = np.column_stack([smp["x"][:, 0], smp["y"][:, 0], smp["z"][:, 0]])
        sup = reg.super_of(pts)
        alive = M.tl0._alive_fn(np.array([tp]))[:, 0] & np.isfinite(pts[:, 0])
        cur = {}
        for s, sid in enumerate(M.sid):
            team = M.team[s]
            side = "attack" if att[rn] == team else "defence"
            if not alive[s] or sup[s] is None:
                continue
            cur[(sid, side)] = (s, team, sup[s])
            prev = hist[(sid, side)]
            if len(prev) >= MIN_PREV:
                out["region"].append({"m": key, "side": side, "y": sup[s], "own": _mode(prev),
                                      "team": _mode(team_hist[(team, side)]), "overall": _mode(side_hist[side]),
                                      "n_prev": len(prev)})
        # censored: what each team saw of the enemy at the probe
        k = np.flatnonzero((M.G_round == rn) & (np.abs(M.G - tp) <= CENSOR_MS))
        for C in M.teams:
            for (sid, side), (s, team, sp) in cur.items():
                if team == C:
                    continue
                seen = bool(k.size and drawn[C][s, k].any())
                ch = cens[(C, sid, side)]
                out["censor"].append({"m": key, "seen": seen, "y": sp, "own_cens": _mode(ch) if ch else None,
                                      "n_cens": len(ch)})
                if seen:
                    ch.append(sp)
        for (sid, side), (s, team, sp) in cur.items():
            hist[(sid, side)].append(sp)
            side_hist[side].append(sp)
            team_hist[(team, side)].append(sp)
        # the first execute's site
        A = att[rn]
        ex = sorted((e for e in eps if e["kind"] == "execute" and e["round"] == rn
                     and (e["outcome"] or {}).get("site") in sites
                     and any(M.team[M.sid.index(x)] == A for x in e["participants"]["committed"] if x in M.sid)),
                    key=lambda e: e["t_start_ms"])
        if ex:
            site = ex[0]["outcome"]["site"]
            if len(site_hist[A]) >= MIN_PREV_SITE:
                out["site"].append({"m": key, "y": site, "pred": _mode(site_hist[A]), "n_prev": len(site_hist[A])})
            site_hist[A].append(site)
        # lurking
        lurkers = {e["participants"]["lurker"] for e in eps if e["kind"] == "lurk" and e["round"] == rn}
        al0 = M.tl0._alive_fn(np.array([r["t_live"] + 1.0]))[:, 0]
        for s, sid in enumerate(M.sid):
            if M.team[s] != A or not al0[s]:
                continue
            h = lurk_hist[sid]
            y = sid in lurkers
            if len(h) >= MIN_PREV_LURK:
                out["lurk"].append({"m": key, "y": y, "score": float(np.mean(h)), "n_prev": len(h)})
            h.append(int(y))
    return out


def run_priors(keys: list[str], out_path: Path) -> None:
    for key in keys:
        t0 = time.time()
        res = priors_match(key)
        with out_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(res, default=cq._jd) + "\n")
        print(f"{key[:8]}: {time.time() - t0:.0f} s, {len(res['region'])} region, {len(res['site'])} site, "
              f"{len(res['lurk'])} lurk rows", flush=True)


def report_priors(path: Path, record: bool) -> int:
    from reticle.metrics import wilson
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    out = {"version": VERSION, "matches": len(rows)}
    R = [x for r in rows for x in r["region"]]
    for k in ("own", "team", "overall"):
        hit = sum(x[k] == x["y"] for x in R)
        out[f"region_{k}"] = {"acc": round(hit / len(R), 4) if R else None, "k": hit, "n": len(R),
                              "ci": [round(v, 4) for v in wilson(hit, len(R))] if R else None}
    for side in ("attack", "defence"):
        Rs = [x for x in R if x["side"] == side]
        out[f"region_own_{side}"] = round(sum(x["own"] == x["y"] for x in Rs) / len(Rs), 4) if Rs else None
        out[f"region_team_{side}"] = round(sum(x["team"] == x["y"] for x in Rs) / len(Rs), 4) if Rs else None
    S = [x for r in rows for x in r["site"]]
    hit = sum(x["pred"] == x["y"] for x in S)
    chance = [1.0 / r["sites"] for r in rows for _x in r["site"] if r["sites"]]
    out["site"] = {"acc": round(hit / len(S), 4) if S else None, "k": hit, "n": len(S),
                   "ci": [round(v, 4) for v in wilson(hit, len(S))] if S else None,
                   "chance": round(float(np.mean(chance)), 4) if chance else None}
    Lr = [x for r in rows for x in r["lurk"]]
    if Lr:
        y = np.array([x["y"] for x in Lr], bool)
        sc = np.array([x["score"] for x in Lr], float)
        ms = np.array([x["m"] for x in Lr])
        auc = _auc(sc, y)
        um = np.unique(ms)
        rng = np.random.default_rng(7)
        boot = []
        for _ in range(1000):
            pick = rng.choice(um, um.size)
            idx = np.concatenate([np.flatnonzero(ms == m) for m in pick])
            a = _auc(sc[idx], y[idx])
            if a is not None:
                boot.append(a)
        out["lurk_auc"] = {"auc": round(auc, 4) if auc is not None else None, "n": int(y.size), "pos": int(y.sum()),
                           "ci": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)]
                           if boot else None}
    Cn = [x for r in rows for x in r["censor"]]
    seen = sum(x["seen"] for x in Cn)
    held = [x for x in Cn if x["own_cens"] is not None]
    out["censor"] = {"seen_share": round(seen / len(Cn), 4) if Cn else None, "n": len(Cn),
                     "with_history": len(held),
                     "own_cens_acc": round(sum(x["own_cens"] == x["y"] for x in held) / len(held), 4) if held else None}
    txt = json.dumps(out, indent=1)
    print(txt)
    (path.parent / (path.stem + "_report.json")).write_text(txt, encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        flat = {}
        for k, v in out.items():
            if isinstance(v, dict):
                for a, b in v.items():
                    if isinstance(b, list):
                        flat[f"{k}.{a}_lo"], flat[f"{k}.{a}_hi"] = b
                    elif b is not None:
                        flat[f"{k}.{a}"] = b
            elif v is not None and k != "version":
                flat[k] = v
        rec("coaching_belief", part="priors", session=f"pooled{len(rows)}", values=flat, deps={"version": VERSION},
            context={"task": "coaching-questions-20261006", "source": path.name})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
