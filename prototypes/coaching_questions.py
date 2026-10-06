"""Coaching questions: what each answer is worth, and what fidelity it needs.

`degrade` answers the catalogue's questions (docs/COACHING_QUESTIONS.md) on a
replay's truth timeline and on copies degraded the way a cheap minimap reader
would see the match: enemies only while drawn (T1), teammates read at a low
base rate except inside windows an enemy on the minimap opens. Each copy's
answers are scored against T1 (the rate's effect) and against the truth T0
(end to end), beside the copy's read share of today's 15 Hz reading. The
attention arms (`A<b>K<k>`) read only the top K engagement windows at full
fidelity, the player's own first. Kill duels also carry the peeker-or-holder
state (CQ17) and the distance to the occluding corner (CQ18) at the onset.
`value` measures each question's association with the round's result on the
stored truth episodes and on the ladder parse. `report` pools both.

Stored data only. The held-out replay (`replay_layer.HELD_OUT`, bd7efa02) is
excluded by name before any row is read. Predictions: task
`coaching-questions-20261006` in the store's `notes/predictions.jsonl`.

    python prototypes/coaching_questions.py degrade MATCH [MATCH ...] [--arms A,B]
    python prototypes/coaching_questions.py degrade --all
    python prototypes/coaching_questions.py value
    python prototypes/coaching_questions.py report [--record] [--path P] [--session S]
    python prototypes/coaching_questions.py cost [--record]
    python prototypes/coaching_questions.py inventory [--record]
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from reticle import episodes as ep  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "coaching-questions-0.1.0"
TASK = "coaching-questions-20261006"
HELD_OUT_PREFIX = "bd7efa02"
OUT = Path(DEFAULT_STORE) / "analysis" / TASK

FRAME_MS = 1000.0 / 15.0          # today's minimap reading rate
SIGHT_MS = 1000.0 / ep.PARAMS["SIGHT_HZ"]
P_MS = 1000.0                     # drawn after the last sight (QA plan's P)
LOCAL_CM = 2000.0                 # local gate reach, xy
SPACING_EDGES_M = (5.0, 10.0, 20.0)
SUPPORT_CM = 1000.0               # first sighting's support radius
START_TOL_MS = 1000.0             # executes, rotations: start and spread tolerance
ONSET_TOL_MS = 125.0              # contacts: two sight samples
PEEK_WIN_MS, PEEK_CMS = 250.0, 200.0  # CQ17: mean speed about the contact onset; peeker at or above
CORNER_DEG, CORNER_SEP_CM = (2.0, 4.0, 8.0, 16.0), 50.0  # CQ18: ray offsets; far side's margin
CORNER_LAT_CM = 100.0                 # CQ18 revision-1: the hit lies within 1 m of the sightline
LONG_CM, WIDE_CM = 2000.0, 200.0      # CQ18: a long angle; a wide swing


def _idle() -> None:
    """Idle priority, one thread (the machine's compute rules)."""
    try:
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass


def replay_matches(root=DEFAULT_STORE) -> list[str]:
    """Every replay with a stored layer, the held-out one removed by name."""
    d = Path(root) / "analysis" / "replay-layer"
    return sorted(p.name for p in d.iterdir()
                  if p.is_dir() and not p.name.startswith(HELD_OUT_PREFIX))


# ----------------------------------------------------------------- arms

def _arms() -> dict[str, dict]:
    a = {"T0": {"kind": "truth"}, "T1": {"kind": "full"}}
    for b in (0.25, 0.5, 1.0, 2.0):
        a[f"B{b:g}"] = {"kind": "base", "b": b}
    for g in ("G", "L"):
        for b in (0.5, 1.0):
            for lead in (0, 250, 500, 1000):
                a[f"{g}{b:g}-{lead}"] = {"kind": "gate", "gate": g, "b": b, "lead": lead, "wr": 15}
    for b in (0.25, 0.5, 1.0):
        a[f"L{b:g}-250w5"] = {"kind": "gate", "gate": "L", "b": b, "lead": 250, "wr": 5}
    for b in (0.5, 1.0):
        a[f"G{b:g}-250w5"] = {"kind": "gate", "gate": "G", "b": b, "lead": 250, "wr": 5}
    # post hoc, chosen after the development run: base reads in the live phase only
    for b in (0.25, 0.5, 1.0):
        a[f"Lp{b:g}-250w5"] = {"kind": "gate", "gate": "L", "b": b, "lead": 250, "wr": 5, "phase": "live",
                               "post_hoc": True}
    # attention budget (CQ13 revision-1): the top K windows at full fidelity, the player's own first
    for b in (0.5, 1.0):
        for k in (1, 2):
            a[f"A{b:g}K{k}"] = {"kind": "attention", "b": b, "K": k, "lead": 250, "wr": 15, "phase": "live"}
    a["B1r"] = {"kind": "base", "b": 1.0, "coarse": "region"}
    a["G1-250r"] = {"kind": "gate", "gate": "G", "b": 1.0, "lead": 250, "wr": 15, "coarse": "region"}
    a["L1-250r"] = {"kind": "gate", "gate": "L", "b": 1.0, "lead": 250, "wr": 15, "coarse": "region"}
    return a


ARMS = _arms()


# ----------------------------------------------------------------- timeline

class CutTimeline(ep.Timeline):
    """Per-slot tracks with a per-slot interpolation gap, life from the
    lifecycle alone (never from whether a position was read). A sample time
    within half a millisecond of a track sample takes that sample, so an
    isolated drawn sample stands."""

    def __init__(self, base: ep.ArrayTimeline, tracks: dict, gaps: dict, events, source: str):
        self.match, self.map, self.source = base.match, base.map, source
        self.slots = list(base.slots)
        self.events = sorted(events, key=lambda e: e.t_ms)
        self.stamps = dict(base.stamps)
        self.tracks, self.gaps = tracks, gaps
        self._alive_fn = base._alive_fn

    def sample(self, t) -> dict:
        t = np.atleast_1d(np.asarray(t, float))
        S = len(self.slots)
        out = {k: np.full((S, t.size), np.nan) for k in ("x", "y", "z", "yaw", "pitch")}
        for s, slot in enumerate(self.slots):
            P = self.tracks.get(slot.slot_id)
            if P is None or len(P["t"]) == 0:
                continue
            tt = np.asarray(P["t"], float)
            n = tt.size
            j = np.clip(np.searchsorted(tt, t), 0, n - 1)
            jm = np.clip(j - 1, 0, n - 1)
            near = np.where(np.abs(tt[jm] - t) < np.abs(tt[j] - t), jm, j)
            hit = np.abs(tt[near] - t) <= 0.5
            if n >= 2:
                i = np.clip(np.searchsorted(tt, t, side="right"), 1, n - 1)
                t0, t1 = tt[i - 1], tt[i]
                ok = (t >= t0) & (t <= t1) & ((t1 - t0) <= self.gaps[slot.slot_id])
                w = np.clip((t - t0) / np.where(t1 > t0, t1 - t0, 1.0), 0.0, 1.0)
                nn = np.where(w < 0.5, i - 1, i)
            else:
                i = np.zeros(t.size, int) + 1
                ok = np.zeros(t.size, bool)
                w = np.zeros(t.size)
                nn = np.zeros(t.size, int)
            for k in ("x", "y", "z"):
                v = np.asarray(P[k], float)
                lin = v[np.clip(i - 1, 0, n - 1)] * (1 - w) + v[np.clip(i, 0, n - 1)] * w if n >= 2 else v[nn]
                out[k][s] = np.where(hit, v[near], np.where(ok, lin, np.nan))
            for k in ("yaw", "pitch"):
                v = np.asarray(P.get(k, np.zeros(n)), float)
                out[k][s] = np.where(hit, v[near], np.where(ok, v[nn], np.nan))
        out["alive"] = self._alive_fn(t)
        return out


def _with_sides(tl: ep.ArrayTimeline, attack: dict) -> list:
    """The truth's events, each round_start carrying the side the capture
    knows (the round number and the player's own side)."""
    teams = sorted({s.team for s in tl.slots})
    out, k = [], 0
    for e in tl.events:
        if e.kind == "round_start":
            k += 1
            att = attack.get(str(k))
            side = ({tm: ("attack" if tm == att else "defence") for tm in teams}
                    if att is not None else None)
            e = ep.Event(e.kind, e.t_ms, e.event_id, side=side)
        out.append(e)
    return out


def _true_runs(mask: np.ndarray) -> list[tuple[int, int]]:
    m = np.asarray(mask, bool)
    if not m.any():
        return []
    d = np.diff(np.concatenate([[0], m.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(d == 1).tolist(), (np.flatnonzero(d == -1) - 1).tolist()))


def _merge(starts: np.ndarray, ends: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if starts.size == 0:
        return starts, ends
    o = np.argsort(starts)
    s, e = starts[o], ends[o]
    ce = np.maximum.accumulate(e)
    new = np.concatenate([[True], s[1:] > ce[:-1]])
    gi = np.cumsum(new) - 1
    S = s[new]
    E = np.zeros(S.size)
    np.maximum.at(E, gi, ce)
    return S, E


def _inside(t: np.ndarray, S: np.ndarray, E: np.ndarray) -> np.ndarray:
    if S.size == 0:
        return np.zeros(t.size, bool)
    i = np.searchsorted(S, t, side="right") - 1
    return (i >= 0) & (t < E[np.clip(i, 0, None)])


class Match:
    """One replay's truth, its sight, and the frames a reader would see."""

    def __init__(self, key: str):
        from reticle.line_of_sight import Occluders
        from reticle.map_regions import Regions, spawn_points
        from reticle.replay_layer import load
        from reticle.wall_penetration import Penetration

        if key.startswith(HELD_OUT_PREFIX):
            raise SystemExit("the held-out replay is never read")
        self.key = key
        self.tl0 = ep.from_replay_layer(key)
        if self.tl0.stamps.get("held_out"):
            raise SystemExit("the held-out replay is never read")
        self.occ = Occluders(self.tl0.map)
        self.pen = Penetration(self.occ) if getattr(self.occ, "table", "synthetic") != "synthetic" else None
        try:
            self.regions = Regions.load(self.tl0.map)
        except FileNotFoundError:
            self.regions = None
        self.spawns = spawn_points(self.tl0.map)
        self.slots = self.tl0.slots
        self.sid = [s.slot_id for s in self.slots]
        self.team = np.array([s.team for s in self.slots])
        self.teams = sorted(set(self.team.tolist()))
        L = load(key)
        subj = {int(e): str(L.entities["subject"][e]) for e in L.players()}
        self.lives = defaultdict(list)
        for i in range(L.lives["e"].size):
            e = int(L.lives["e"][i])
            if e in subj:
                self.lives[subj[e]].append((float(L.lives["t_open"][i]), float(L.lives["t_close"][i])))
        self.rounds = ep.timeline_rounds(self.tl0)
        self._sight()
        self._frames()

    def derive(self, tl) -> ep.Derived:
        return ep.derive_episodes(tl, occ=self.occ, regions=self.regions, spawns=self.spawns, pen=self.pen)

    def _sight(self) -> None:
        """Truth sight on derive's own 16 Hz grid, round by round."""
        G, R, sees, X, Y = [], [], [], [], []
        for r in self.rounds:
            t0 = r["t_live"] if r["t_live"] is not None else r["t_start"]
            g = np.arange(t0, r["t_next"], SIGHT_MS)
            if g.size == 0:
                continue
            smp = self.tl0.sample(g)
            sees.append(ep.sight(smp, self.slots, self.occ, ep.PARAMS["HFOV_DEG"]))
            G.append(g)
            R.append(np.full(g.size, r["round"]))
            X.append(smp["x"])
            Y.append(smp["y"])
        self.G = np.concatenate(G)
        self.G_round = np.concatenate(R)
        self.sees = np.concatenate(sees, axis=2)
        self.X = np.concatenate(X, axis=1)
        self.Y = np.concatenate(Y, axis=1)
        smp = self.tl0.sample(self.G)
        self.Z, self.YAW, self.PITCH = smp["z"], smp["yaw"], smp["pitch"]

    def _frames(self) -> None:
        """Today's 15 Hz frame grid per round, and each frame's base index."""
        F, K, R = [], [], []
        for r in self.rounds:
            n = int(np.floor((r["t_next"] - r["t_start"]) / FRAME_MS))
            k = np.arange(max(n, 0))
            F.append(r["t_start"] + k * FRAME_MS)
            K.append(k)
            R.append(np.full(k.size, r["round"]))
        self.F = np.concatenate(F)
        self.F_k = np.concatenate(K)
        self.F_round = np.concatenate(R)
        self.F_alive = self.tl0._alive_fn(self.F)

    # ------------------------------------------------------------- drawn

    def drawn(self, C: str) -> np.ndarray:
        """drawn[j, k]: enemy j of team C is on C's minimap at grid sample k:
        a living C player saw him within the last P (truth sight)."""
        ci = np.flatnonzero(self.team == C)
        vis = self.sees[ci].any(axis=0)                  # (S, K): j seen by some C player
        vis[ci] = False
        n = int(round(P_MS / SIGHT_MS))
        out = vis.copy()
        for rn in np.unique(self.G_round):
            sl = np.flatnonzero(self.G_round == rn)
            v = vis[:, sl]
            c = np.cumsum(np.concatenate([np.zeros((v.shape[0], 1), int), v.astype(int)], axis=1), axis=1)
            lo = np.clip(np.arange(sl.size) - n, 0, None)
            out[:, sl] = (c[:, np.arange(sl.size) + 1] - c[:, lo]) > 0
        return out

    def player(self, C: str) -> tuple[int, str]:
        """The capturing player on team C: the account's subject where the
        replay holds one on C, else C's first slot (a stand-in)."""
        if not hasattr(self, "_own"):
            import ladder_fetch as lf
            self._own = set(lf.owner_accounts(Path(DEFAULT_STORE)).values())
        ci = np.flatnonzero(self.team == C)
        mine = [s for s in ci if self.sid[s] in self._own]
        return (int(mine[0]), "subject") if len(mine) == 1 else (int(ci[0]), "first_slot")

    def windows(self, C: str, drawn: np.ndarray, K: int) -> tuple[np.ndarray, np.ndarray, dict]:
        """CQ13 revision-1. At each grid sample the drawn enemies form windows
        (single linkage within LOCAL_CM); a window involves the C slots that
        see a member or stand within LOCAL_CM of one. Windows involving the
        player rank first, then by the distance from the player (dead: from
        the nearest living teammate) to the window's nearest member. Returns
        the slots and enemies in the top K windows, and the concurrency."""
        from scipy.sparse.csgraph import connected_components
        S, Kg = len(self.slots), self.G.size
        slot_f = np.zeros((S, Kg), bool)
        enemy_f = np.zeros((S, Kg), bool)
        ci = np.flatnonzero(self.team == C)
        ei = np.flatnonzero(self.team != C)
        me, how = self.player(C)
        alive = np.isfinite(self.X) & np.isfinite(self.Y)
        nwin = np.zeros(Kg, int)
        for k in np.flatnonzero(drawn[ei].any(axis=0)):
            D = ei[drawn[ei, k] & alive[ei, k]]
            if not D.size:
                continue
            P = np.column_stack([self.X[D, k], self.Y[D, k]])
            dd = np.hypot(*(P[:, None, :] - P[None, :, :]).transpose(2, 0, 1))
            n, lab = connected_components(dd <= LOCAL_CM, directed=False)
            nwin[k] = n
            L = ci[alive[ci, k]]
            if not L.size:
                continue
            Q = np.column_stack([self.X[L, k], self.Y[L, k]])
            dl = np.hypot(*(Q[:, None, :] - P[None, :, :]).transpose(2, 0, 1))      # (living C, members)
            inv = (dl <= LOCAL_CM) | self.sees[:, :, k][np.ix_(L, D)]
            ref = me if alive[me, k] else L[np.argmin(dl.min(axis=1))]
            rq = np.hypot(P[:, 0] - self.X[ref, k], P[:, 1] - self.Y[ref, k])
            keys = []
            for w in range(n):
                m = lab == w
                slots = L[inv[:, m].any(axis=1)]
                keys.append((0 if me in slots else 1, float(rq[m].min()), w, slots))
            keys.sort(key=lambda x: (x[0], x[1], x[2]))
            for _a, _b, w, slots in keys[:K]:
                slot_f[slots, k] = True
                enemy_f[D[lab == w], k] = True
        have = nwin > 0
        conc = {"player": how, "drawn_samples": int(have.sum()),
                "ge2": float((nwin[have] >= 2).mean()) if have.any() else None,
                "ge3": float((nwin[have] >= 3).mean()) if have.any() else None}
        return slot_f, enemy_f, conc

    def t1_tracks(self, C: str, drawn: np.ndarray) -> tuple[dict, dict]:
        from reticle.replay_source import MAX_GAP_MS
        tracks, gaps = {}, {}
        for s, sid in enumerate(self.sid):
            if self.team[s] == C:
                tracks[sid] = self.tl0.tracks[sid]
                gaps[sid] = MAX_GAP_MS
            else:
                m = drawn[s] & np.isfinite(self.X[s])
                tracks[sid] = {"t": self.G[m], "x": self.X[s, m], "y": self.Y[s, m], "z": self.Z[s, m],
                               "yaw": self.YAW[s, m], "pitch": self.PITCH[s, m]}
                gaps[sid] = SIGHT_MS + 5.0
        return tracks, gaps

    # ------------------------------------------------------------- schedule

    def schedule(self, C: str, drawn: np.ndarray, arm: dict) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """reads[s, f]: slot s is read at frame f; with the base frames and
        each slot's window frames."""
        S = len(self.slots)
        reads = np.zeros((S, self.F.size), bool)
        b = arm["b"]
        step = 15.0 / b
        jmax = int(self.F_k.max() / step) + 2 if self.F_k.size else 0
        base_k = np.unique(np.round(np.arange(jmax) * step).astype(int))
        if arm.get("phase") == "live":
            # base reads only from buy end to the round's end, phase-locked at buy end
            base = np.zeros(self.F.size, bool)
            for r in self.rounds:
                if r["t_live"] is None:
                    continue
                t_hi = r["t_end"] if r["t_end"] is not None else r["t_next"]
                sel = np.flatnonzero((self.F_round == r["round"]) & (self.F >= r["t_live"]) & (self.F <= t_hi))
                if sel.size:
                    k = self.F_k[sel] - self.F_k[sel[0]]
                    base[sel] = np.isin(k, base_k)
        else:
            base = np.isin(self.F_k, base_k)
        win = np.zeros((S, self.F.size), bool)
        if arm["kind"] == "attention":
            slot_f = arm["_slot_f"]
            for s in np.flatnonzero(self.team == C):
                rr = _true_runs(slot_f[s])
                if not rr:
                    continue
                a = np.array([x for x, _ in rr])
                z = np.array([y for _, y in rr])
                St, En = _merge(self.G[a] - float(arm["lead"]), self.G[z] + SIGHT_MS)
                win[s] = _inside(self.F, St, En)
        if arm["kind"] == "gate":
            lead = float(arm["lead"])
            ci = np.flatnonzero(self.team == C)
            ei = np.flatnonzero(self.team != C)
            if arm["gate"] == "G":
                cond = {None: drawn[ei].any(axis=0)}
            else:
                cond = {}
                for s in ci:
                    d = np.hypot(self.X[ei] - self.X[s], self.Y[ei] - self.Y[s])
                    near = np.where(np.isfinite(d), d <= LOCAL_CM, False)
                    cond[s] = (drawn[ei] & (self.sees[s, ei] | near)).any(axis=0)
            for s in ci:
                c = cond[None] if None in cond else cond[s]
                rr = _true_runs(c)
                if not rr:
                    continue
                a = np.array([x for x, _ in rr])
                z = np.array([y for _, y in rr])
                St, En = _merge(self.G[a] - lead, self.G[z] + SIGHT_MS)
                w = _inside(self.F, St, En)
                if arm["wr"] < 15:
                    keep = np.zeros_like(w)
                    every = int(round(15 / arm["wr"]))
                    for x, y in _true_runs(w):
                        keep[x:y + 1:every] = True
                    w = keep
                win[s] = w
        for s in np.flatnonzero(self.team == C):
            al = self.F_alive[s]
            first = np.zeros_like(al)
            for x, _y in _true_runs(al):
                first[x] = True
            reads[s] = al & (base | win[s] | first)
        return reads, base, win

    def read_tracks(self, C: str, drawn: np.ndarray, arm: dict) -> tuple[dict, dict, dict]:
        conc = None
        if arm["kind"] == "attention":
            slot_f, enemy_f, conc = self.windows(C, drawn, int(arm["K"]))
            arm = dict(arm, _slot_f=slot_f)
            n_lead = int(round(float(arm["lead"]) / SIGHT_MS))
            for _ in range(n_lead):                     # the buffered frames before a window opens
                enemy_f[:, :-1] |= enemy_f[:, 1:]
        tracks, gaps = self.t1_tracks(C, drawn)
        reads, base, win = self.schedule(C, drawn, arm)
        ci = np.flatnonzero(self.team == C)
        if conc is not None:
            # every other drawn enemy only at the base samples, never interpolated
            bk = np.searchsorted(self.G, self.F[base], side="left")
            bk = bk[(bk < self.G.size)]
            bmask = np.zeros(self.G.size, bool)
            bmask[bk] = True
            for s in np.flatnonzero(self.team != C):
                m = drawn[s] & (enemy_f[s] | bmask) & np.isfinite(self.X[s])
                tracks[self.sid[s]] = {"t": self.G[m], "x": self.X[s, m], "y": self.Y[s, m], "z": self.Z[s, m],
                                       "yaw": self.YAW[s, m], "pitch": self.PITCH[s, m]}
                gaps[self.sid[s]] = SIGHT_MS + 5.0
        cols = np.flatnonzero(reads[ci].any(axis=0))
        smp = self.tl0.sample(self.F[cols])
        pos = {k: smp[k] for k in ("x", "y", "z", "yaw", "pitch")}
        col_of = np.full(self.F.size, -1)
        col_of[cols] = np.arange(cols.size)
        n_reads = 0
        for s in ci:
            sid = self.sid[s]
            f = np.flatnonzero(reads[s])
            c = col_of[f]
            ok = np.isfinite(pos["x"][s, c])
            f, c = f[ok], c[ok]
            n_reads += int(f.size)
            T = self.F[f]
            x, y, z = pos["x"][s, c].copy(), pos["y"][s, c].copy(), pos["z"][s, c]
            if arm.get("coarse") == "region" and self.regions is not None:
                x, y = self._snap(x, y, z, base[f] & ~win[s][f])
            yaw, pitch = pos["yaw"][s, c], pos["pitch"][s, c]
            # hold the last read to the life's end
            ht, hi = [], []
            for a, e in self.lives[sid]:
                inside = np.flatnonzero((T >= a) & (T < e))
                if inside.size and T[inside[-1]] < e - 1.0:
                    ht.append(e - 1.0)
                    hi.append(inside[-1])
            if ht:
                T = np.concatenate([T, ht])
                idx = np.concatenate([np.arange(f.size), hi])
                o = np.argsort(T, kind="stable")
                T = T[o]
                idx = idx[o]
                x, y, z, yaw, pitch = x[idx], y[idx], z[idx], yaw[idx], pitch[idx]
            tracks[sid] = {"t": T, "x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch}
            gaps[sid] = np.inf
        alive_ms = sum(e - a for s in ci for a, e in self.lives[self.sid[s]])
        frames_read = int(reads[ci].any(axis=0).sum())
        frames_live = int(self.F_alive[ci].any(axis=0).sum())
        cost = {"reads": n_reads, "denominator": alive_ms / FRAME_MS, "share": n_reads / (alive_ms / FRAME_MS),
                "frames_read": frames_read, "frames_live": frames_live,
                "frame_share": frames_read / max(frames_live, 1)}
        if conc is not None:
            cost["concurrency"] = conc
        return tracks, gaps, cost

    def _snap(self, x, y, z, mask):
        """Coarse reads at region precision: x, y moved to the centre of the
        callout volume holding the point; z kept (the floor is known)."""
        R = self.regions
        pts = np.stack([x, y, z], -1)
        k = R.volume_of(pts)
        use = mask & (k >= 0)
        if not use.any():
            return x, y
        fwd = np.linalg.inv(R.inv[k[use]])
        c = (R.lo[k[use]] + R.hi[k[use]]) / 2.0
        h = np.concatenate([c, np.ones((c.shape[0], 1))], axis=1)
        w = np.einsum("nij,nj->ni", np.transpose(fwd, (0, 2, 1)), h)
        x, y = x.copy(), y.copy()
        x[use], y[use] = w[:, 0], w[:, 1]
        return x, y


# ----------------------------------------------------------------- answers

def _tm(x, C, team_of):
    if x is None:
        return "none"
    if x == "both":
        return "both"
    return "C" if team_of.get(x) == C else "E"


def _bucket(d):
    if d is None or not np.isfinite(d):
        return None
    for i, e in enumerate(SPACING_EDGES_M):
        if d < e:
            return i
    return len(SPACING_EDGES_M)


def answers(der: ep.Derived, tl, C: str, occ=None) -> dict:
    """The catalogue's answers for capturing team C, from one arm's
    episodes and timeline."""
    team_of = {s.slot_id: s.team for s in tl.slots}
    att = der.header["attack_team"]
    eps = der.episodes
    out = {}
    out["attack_team"] = {int(k): v for k, v in att.items()}
    rr = {}
    for e in eps:
        if e["kind"] in ("phase_live", "phase_post_plant") and e.get("outcome"):
            rr[e["round"]] = (e["outcome"].get("end_reason"), e["outcome"].get("winner"))
    out["round_result"] = rr
    duels = [e for e in eps if e["kind"] == "duel"]
    out["opening_first_seer"] = {e["kill_event"]: _tm(e.get("first_seer"), C, team_of)
                                 for e in duels if e.get("opening") and e["outcome"]["result"] == "killed"}

    def item(k, e, **attrs):
        return {"k": k, "s": e["t_start_ms"], "e": e["t_end_ms"], "attrs": attrs}

    def side_of(e):
        p = e["participants"]
        return {team_of.get(p["a"]), team_of.get(p["b"])}

    out["duel_C"] = [item(e.get("kill_event") or ("pair", frozenset((e["participants"]["a"], e["participants"]["b"]))), e,
                          first_seer=_tm(e.get("first_seer"), C, team_of))
                     for e in duels if C in side_of(e)]
    # CQ17: peeker against holder at contact, per kill duel with sight
    pk = [e for e in duels if e["outcome"]["result"] == "killed" and e.get("sight") and C in side_of(e)
          and len(side_of(e)) == 2]
    out["peek_C"], out["peek_pair"], out["_peek_won"] = {}, {}, {}
    if pk:
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        off = np.arange(-PEEK_WIN_MS, PEEK_WIN_MS + 1.0, SIGHT_MS)
        T = np.concatenate([e["t_start_ms"] + off for e in pk])
        smp = tl.sample(T)
        m = off.size
        for n_, e in enumerate(pk):
            sl = slice(n_ * m, (n_ + 1) * m)
            st = {}
            for sid in (e["participants"]["a"], e["participants"]["b"]):
                x, y = smp["x"][idx[sid], sl], smp["y"][idx[sid], sl]
                ok = np.isfinite(x) & np.isfinite(y)
                tt = T[sl][ok]
                if ok.sum() < 2 or tt[-1] - tt[0] <= 0:
                    st[sid] = None
                    continue
                path = np.hypot(np.diff(x[ok]), np.diff(y[ok])).sum()
                st[sid] = "peek" if path / ((tt[-1] - tt[0]) / 1000.0) >= PEEK_CMS else "hold"
            a, b = e["participants"]["a"], e["participants"]["b"]
            c_, e_ = (a, b) if team_of.get(a) == C else (b, a)
            out["peek_C"][e["kill_event"]] = st[c_]
            out["peek_pair"][e["kill_event"]] = (st[c_], st[e_])
            out["_peek_won"][e["kill_event"]] = team_of.get(e["outcome"]["killer"]) == C
    # CQ18: each participant's distance to the occluding corner at the onset
    out["corner_C"], out["_corner"] = {}, {}
    if pk and occ is not None:
        from reticle.line_of_sight import eye
        smp = tl.sample(np.array([e["t_start_ms"] for e in pk]))
        P = eye(np.stack([smp["x"], smp["y"], smp["z"]], -1))          # (S, n, 3)
        rows_, O_, D_ = [], [], []
        for n_, e in enumerate(pk):
            a, b = e["participants"]["a"], e["participants"]["b"]
            c_, e_ = (a, b) if team_of.get(a) == C else (b, a)
            pc, pe = P[idx[c_], n_], P[idx[e_], n_]
            if not (np.isfinite(pc).all() and np.isfinite(pe).all()):
                continue
            for w, (o, t) in enumerate(((pc, pe), (pe, pc))):
                v = t - o
                Lh = max(float(np.hypot(v[0], v[1])), 1.0)
                th = np.arctan2(v[1], v[0])
                for k, dg in enumerate(CORNER_DEG):
                    for sg in (1.0, -1.0):
                        ang = th + sg * np.radians(dg)
                        d = np.array([np.cos(ang), np.sin(ang), v[2] / Lh])
                        O_.append(o)
                        D_.append(d / np.linalg.norm(d))
                        rows_.append((n_, w, k, float(np.linalg.norm(v))))
        if rows_:
            hit, dist = occ.first_hit(np.array(O_), np.array(D_))
            best = {}
            for (n_, w, k, Lr), h, dd in zip(rows_, hit, dist):
                if h >= 0 and dd < Lr and dd * np.sin(np.radians(CORNER_DEG[k])) <= CORNER_LAT_CM:
                    cur = best.get((n_, w))
                    if cur is None or k < cur[0] or (k == cur[0] and dd < cur[1]):
                        best[(n_, w)] = (k, float(dd))
            for n_, e in enumerate(pk):
                a, b = e["participants"]["a"], e["participants"]["b"]
                c_, e_ = (a, b) if team_of.get(a) == C else (b, a)
                pc, pe = P[idx[c_], n_], P[idx[e_], n_]
                if not (np.isfinite(pc).all() and np.isfinite(pe).all()):
                    out["corner_C"][e["kill_event"]] = None
                    continue
                dc = best.get((n_, 0), (None, None))[1]
                de = best.get((n_, 1), (None, None))[1]
                L = float(np.linalg.norm(pe - pc))
                lab = None
                if dc is not None and de is not None and abs(dc - de) >= CORNER_SEP_CM:
                    lab = "far" if dc > de else "near"
                out["corner_C"][e["kill_event"]] = lab
                out["_corner"][e["kill_event"]] = (dc, de, L, c_)
    out["contact_C"] = [{"k": frozenset((c["a"], c["b"])), "s": c["t_start_ms"], "e": c["t_end_ms"],
                         "attrs": {"first_seer": _tm(c.get("first_seer"), C, team_of)}}
                        for c in der.contacts]
    eng = []
    for e in eps:
        if e["kind"] != "engagement":
            continue
        comb = e["participants"]["combatants"]
        if not any(team_of.get(x) == C for x in comb):
            continue
        o = e["outcome"]
        eng.append({"k": "eng", "s": e["t_start_ms"], "e": e["t_end_ms"],
                    "kills": frozenset(e.get("kill_events") or []), "comb": frozenset(comb),
                    "attrs": {"kd": (o["kills"].get(C, 0), o["deaths"].get(C, 0))}})
    out["engagement_C"] = eng
    trades = []
    for e in eps:
        if e["kind"] != "trade":
            continue
        p = e["participants"]
        if team_of.get(p["traded"]) != C:
            continue
        trades.append(item(tuple(e["members"]), e, saw=bool(e["trader_saw_killer_at_t1"]),
                           dist=_bucket(e.get("trader_distance_m"))))
    out["trade_C"] = trades
    # spacing at each capturing-team death by an enemy
    deaths = [x for x in tl.events if x.kind == "death" and team_of.get(x.target) == C
              and x.actor in team_of and team_of[x.actor] != C]
    sp = {}
    if deaths:
        t = np.array([d.t_ms - 1.0 for d in deaths])
        smp = tl.sample(t)
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        ci = [k for k, s in enumerate(tl.slots) if s.team == C]
        for n, d in enumerate(deaths):
            v = idx[d.target]
            best = np.inf
            for k in ci:
                if k == v or not smp["alive"][k, n]:
                    continue
                dd = np.hypot(smp["x"][k, n] - smp["x"][v, n], smp["y"][k, n] - smp["y"][v, n]) / 100.0
                if np.isfinite(dd):
                    best = min(best, dd)
            has_mate = any(smp["alive"][k, n] for k in ci if k != v)
            if has_mate:
                sp[d.event_id] = _bucket(best) if np.isfinite(best) else None
    out["spacing_death"] = sp
    # first sighting by C per round and its support
    first = {}
    for c in der.contacts:
        fs = c.get("first_seer")
        seer = None
        if fs == "both":
            seer = c["a"] if team_of.get(c["a"]) == C else c["b"]
        elif fs is not None and team_of.get(fs) == C:
            seer = fs
        if seer is None:
            continue
        r = c["round"]
        if r not in first or c["t_start_ms"] < first[r][0]:
            first[r] = (c["t_start_ms"], seer)
    sup = {}
    if first:
        rs = sorted(first)
        t = np.array([first[r][0] for r in rs])
        smp = tl.sample(t)
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        ci = [k for k, s in enumerate(tl.slots) if s.team == C]
        for n, r in enumerate(rs):
            v = idx[first[r][1]]
            cnt = 0
            for k in ci:
                if k == v or not smp["alive"][k, n]:
                    continue
                dd = np.hypot(smp["x"][k, n] - smp["x"][v, n], smp["y"][k, n] - smp["y"][v, n])
                cnt += int(np.isfinite(dd) and dd <= SUPPORT_CM)
            sup[r] = (first[r][1], cnt)
    out["first_sight_support"] = sup
    for team_key, want in (("C", True), ("E", False)):
        ex, rot, lk = [], [], []
        for e in eps:
            if e["kind"] == "execute":
                com = e["participants"]["committed"]
                if com and ((team_of.get(com[0]) == C) == want):
                    cm = e["commitment"]
                    ex.append(item((e["round"], e["outcome"].get("site")), e, committed=cm["committed"],
                                   result=e["outcome"]["result"],
                                   spread=cm.get("entry_spread_ms")))
            elif e["kind"] == "rotation":
                r_ = e["participants"]["rotator"]
                if (team_of.get(r_) == C) == want:
                    rot.append(item((r_, e["round"], e["outcome"]["from_site"], e["outcome"]["to_site"]), e))
            elif e["kind"] == "lurk":
                l_ = e["participants"]["lurker"]
                if (team_of.get(l_) == C) == want:
                    lk.append(item((l_, e["round"]), e))
        out[f"execute_{team_key}"] = ex
        out[f"rotation_{team_key}"] = rot
        out[f"lurk_{team_key}"] = lk
    rt = {}
    for e in eps:
        if e["kind"] == "retake" and team_of.get((e["participants"].get("defenders") or [None])[0]) == C:
            rt[e["round"]] = ("retake", e["outcome"]["result"], e.get("entry_ms"))
        elif e["kind"] == "contested_plant" and team_of.get((e["participants"].get("defenders") or [None])[0]) == C:
            rt[e["round"]] = ("contested", None, None)
    out["retake_C"] = rt
    # the valued execute answer: per attack round, the largest commitment's band
    band = {}
    for rn, tm in out["attack_team"].items():
        if tm != C:
            continue
        mx = max([x["attrs"]["committed"] for x in out["execute_C"] if x["k"][0] == rn] or [0])
        band[rn] = 0 if mx == 0 else (1 if mx == 1 else (2 if mx == 2 else 3))
    out["execute_commit_band"] = band
    return out


INSTANT = ("attack_team", "round_result", "opening_first_seer", "spacing_death", "first_sight_support",
           "execute_commit_band", "peek_C", "peek_pair", "corner_C")
EPISODIC = ("duel_C", "contact_C", "engagement_C", "trade_C", "execute_C", "rotation_C", "lurk_C",
            "execute_E", "rotation_E", "lurk_E")


def _pair_up(T: list, A: list, slack: float = 500.0, key=None) -> list[tuple[int, int]]:
    by = defaultdict(list)
    for j, a in enumerate(A):
        by[a["k"] if key is None else key(a)].append(j)
    cand = []
    for i, t in enumerate(T):
        for j in by.get(t["k"] if key is None else key(t), []):
            ov = min(t["e"], A[j]["e"]) - max(t["s"], A[j]["s"])
            if ov >= -slack:
                cand.append((ov, i, j))
    cand.sort(key=lambda x: -x[0])
    ui, uj, out = set(), set(), []
    for _ov, i, j in cand:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j))
    return out


def _match_eng(T: list, A: list) -> list[tuple[int, int]]:
    cand = []
    for i, t in enumerate(T):
        for j, a in enumerate(A):
            if t["kills"] or a["kills"]:
                u = len(t["kills"] | a["kills"])
                jac = len(t["kills"] & a["kills"]) / u if u else 0.0
                if jac >= 0.5:
                    cand.append((jac, i, j))
            elif t["comb"] & a["comb"] and min(t["e"], a["e"]) - max(t["s"], a["s"]) >= -500.0:
                cand.append((0.1, i, j))
    cand.sort(key=lambda x: -x[0])
    ui, uj, out = set(), set(), []
    for _s, i, j in cand:
        if i in ui or j in uj:
            continue
        ui.add(i)
        uj.add(j)
        out.append((i, j))
    return out


def _attrs_equal(q: str, t: dict, a: dict) -> bool:
    ta, aa = t["attrs"], a["attrs"]
    if q.startswith("execute"):
        sp_ok = (ta["spread"] is None and aa["spread"] is None) or (
            ta["spread"] is not None and aa["spread"] is not None and abs(ta["spread"] - aa["spread"]) <= START_TOL_MS)
        return ta["committed"] == aa["committed"] and ta["result"] == aa["result"] and sp_ok
    if q.startswith("rotation"):
        return abs(t["s"] - a["s"]) <= START_TOL_MS
    if q == "contact_C":
        return abs(t["s"] - a["s"]) <= ONSET_TOL_MS and ta["first_seer"] == aa["first_seer"]
    return ta == aa


def score(T: dict, A: dict) -> dict:
    """Per question: counts for agreement of arm answers A with reference T."""
    out = {}
    for q in INSTANT:
        if q not in T or q not in A:
            continue
        t, a = T[q], A[q]
        n = len(t)
        eq = sum(1 for k, v in t.items() if k in a and a[k] == v)
        if q == "spacing_death":
            eq_r = sum(1 for k, v in t.items() if k in a and v is not None and a[k] is not None
                       and (v == 0) == (a[k] == 0))
            out[q] = {"n": n, "agree": eq, "extra": len(set(a) - set(t)), "agree_5m": eq_r}
        else:
            out[q] = {"n": n, "agree": eq, "extra": len(set(a) - set(t))}
    for q in EPISODIC:
        t, a = T[q], A[q]
        pairs = _match_eng(t, a) if q == "engagement_C" else _pair_up(t, a)
        tp = len(pairs)
        same = sum(1 for i, j in pairs if _attrs_equal(q, t[i], a[j]))
        out[q] = {"n": len(t), "arm": len(a), "tp": tp, "same": same}
    # retake label per round
    t, a = T["retake_C"], A["retake_C"]

    def rk(v):
        return v[0], v[1]
    eq = sum(1 for k, v in t.items() if k in a and rk(a[k]) == rk(v))
    eq_entry = sum(1 for k, v in t.items() if k in a and rk(a[k]) == rk(v) and (
        (v[2] is None and a[k][2] is None) or (v[2] is not None and a[k][2] is not None
                                               and abs(v[2] - a[k][2]) <= START_TOL_MS)))
    out["retake_C"] = {"n": len(t), "agree": eq, "agree_entry": eq_entry, "extra": len(set(a) - set(t))}
    return out


# ----------------------------------------------------------------- degrade

def degrade_match(key: str, arms: list[str], out_path: Path) -> list[dict]:
    t0 = time.time()
    M = Match(key)
    d0 = M.derive(M.tl0)
    stored = ep.read_episodes(M.tl0.match)
    kinds0 = Counter(e["kind"] for e in d0.episodes)
    kinds_s = Counter(r.get("kind") for r in stored if r.get("row") == "episode")
    check = {"stored_kind_counts_equal": kinds0 == kinds_s,
             "contacts": [len(d0.contacts), sum(1 for r in stored if r.get("row") == "contact")]}
    attack = d0.header["attack_team"]
    events = _with_sides(M.tl0, attack)
    rows = []
    print(f"{key[:8]} loaded and T0 derived in {time.time() - t0:.0f} s; stored equal {check['stored_kind_counts_equal']}",
          flush=True)
    for C in M.teams:
        drawn = M.drawn(C)
        A0 = answers(d0, M.tl0, C, M.occ)
        tracks, gaps = M.t1_tracks(C, drawn)
        tl1 = CutTimeline(M.tl0, tracks, gaps, events, "t1")
        d1 = M.derive(tl1)
        A1 = answers(d1, tl1, C, M.occ)
        drawn_share = float(drawn[M.team != C].any(axis=0).mean())
        base = {"version": VERSION, "match": M.tl0.match, "map": M.tl0.map, "team": C,
                "check": check, "drawn_share_of_live_grid": drawn_share}
        peek = [[A0["peek_pair"][k][0], A0["peek_pair"][k][1], A0["_peek_won"][k]] for k in A0["peek_pair"]]
        me, _how = M.player(C)
        corner = [list(A0["_corner"][k][:3]) + [A0["peek_pair"][k][0], A0["peek_pair"][k][1], A0["_peek_won"][k],
                                               A0["_corner"][k][3] == M.sid[me] and _how == "subject"]
                  for k in A0["_corner"]]
        rows.append(dict(base, arm="T1", cost={"share": 1.0}, vs_T0=score(A0, A1), vs_T1=None, peek_value=peek,
                         corner_value=corner))
        for name in arms:
            arm = ARMS[name]
            if arm["kind"] in ("truth", "full"):
                continue
            ta = time.time()
            tr, gp, cost = M.read_tracks(C, drawn, arm)
            tla = CutTimeline(M.tl0, tr, gp, events, name)
            da = M.derive(tla)
            Aa = answers(da, tla, C, M.occ)
            rows.append(dict(base, arm=name, cost=cost, vs_T0=score(A0, Aa), vs_T1=score(A1, Aa)))
            print(f"  {key[:8]} {C} {name}: share {cost['share']:.3f} ({time.time() - ta:.0f} s)", flush=True)
    with out_path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, default=_jd) + "\n")
    return rows


def _jd(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (set, frozenset)):
        return sorted(o)
    if isinstance(o, np.bool_):
        return bool(o)
    raise TypeError(type(o))


# ----------------------------------------------------------------- value

LADDER = Path(DEFAULT_STORE) / "external" / "ladder" / "henrikdev" / "v4" / "parsed" / "ladder-parse-0.2.0"
TRADE_MS = ep.PARAMS["TRADE_WINDOW_MS"]
BLIND_MS = 2000.0                  # killer unseen by the victim's team this long before the death
CHIP_MS, CHIP_DMG = 10000.0, 30.0  # damage taken before a kill duel
NEAR_M, FAR_M = 5.0, 10.0          # spacing: near and far, the middle left out
ECO_MAX, FULL_MIN = 2000.0, 3900.0  # buy bands, the player profile's choice


def _stratified(rows: list[dict], n_boot: int = 1000, seed: int = 7) -> dict:
    """The 0/1 outcome `y`'s difference between answers a=1 and a=0 within
    strata `z`, averaged by stratum size over strata holding both answers;
    a match bootstrap gives the interval."""
    if not rows:
        return {"n": 0}
    ms = sorted({r["m"] for r in rows})
    zs = sorted({r["z"] for r in rows}, key=str)
    mi = {m: i for i, m in enumerate(ms)}
    zi = {z: i for i, z in enumerate(zs)}
    cnt = np.zeros((len(ms), len(zs), 2, 2))
    for r in rows:
        cnt[mi[r["m"]], zi[r["z"]], int(bool(r["a"])), int(bool(r["y"]))] += 1

    def stat(c):
        n = c.sum(axis=2)
        k = c[..., 1]
        ok = (n[:, 0] > 0) & (n[:, 1] > 0)
        if not ok.any():
            return np.nan
        p1, p0 = k[ok, 1] / n[ok, 1], k[ok, 0] / n[ok, 0]
        w = n[ok].sum(axis=1)
        return float(((p1 - p0) * w).sum() / w.sum())

    tot = cnt.sum(axis=0)
    rng = np.random.default_rng(seed)
    W = rng.multinomial(len(ms), np.full(len(ms), 1.0 / len(ms)), size=n_boot)
    boot = np.array([stat(np.tensordot(w, cnt, axes=1)) for w in W])
    boot = boot[np.isfinite(boot)]
    n1, n0 = tot[:, 1].sum(), tot[:, 0].sum()
    return {"diff": round(stat(tot), 4),
            "ci": ([round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)]
                   if boot.size else None),
            "n": int(tot.sum()), "n_a1": int(n1), "n_a0": int(n0),
            "y_a1": round(float(tot[:, 1, 1].sum() / n1), 4) if n1 else None,
            "y_a0": round(float(tot[:, 0, 1].sum() / n0), 4) if n0 else None,
            "matches": len(ms), "strata": len(zs)}


def _side(team: str, round0: int) -> str | None:
    """The ladder's sides: Red starts on attack (the player profile's
    check), and `rounds.side_in_round` owns the swap."""
    from reticle.rounds import SIDES, side_in_round
    return side_in_round(round0 + 1, SIDES[0] if team == "Red" else SIDES[1])[0]


def _band(v: float) -> str:
    return "eco" if v < ECO_MAX else ("full" if v >= FULL_MIN else "force")


def ladder_instances() -> tuple[dict, dict]:
    """Instances per question from the ladder parse's non-holdout matches."""
    import pyarrow.parquet as pq
    M = pq.read_table(LADDER / "matches.parquet").to_pydict()
    keep = {m for m, h in zip(M["match_id"], M["holdout"])
            if not h and not str(m).startswith(HELD_OUT_PREFIX)}
    R = [r for r in pq.read_table(LADDER / "rounds.parquet").to_pylist()
         if r["match_id"] in keep and r["result"] not in ("", "Surrendered")]
    K = [k for k in pq.read_table(LADDER / "kills.parquet").to_pylist() if k["match_id"] in keep]
    Pz = pq.read_table(LADDER / "positions.parquet").to_pydict()
    E = [e for e in pq.read_table(LADDER / "economy.parquet").to_pylist() if e["match_id"] in keep]
    rkey = {(r["match_id"], r["round"]): r for r in R}
    kills = defaultdict(list)
    for k in K:
        if (k["match_id"], k["round"]) in rkey:
            kills[(k["match_id"], k["round"])].append(k)
    pos = defaultdict(list)
    for i in range(len(Pz["match_id"])):
        if Pz["event"][i] == "kill" and Pz["match_id"][i] in keep:
            pos[(Pz["match_id"][i], Pz["kill"][i])].append((Pz["player"][i], Pz["team"][i], Pz["x"][i], Pz["y"][i]))
    econ = defaultdict(list)
    for e in E:
        econ[(e["match_id"], e["round"], e["team"])].append(e["loadout_value"])
    inst = defaultdict(list)
    for (m, rn), r in rkey.items():
        ks = sorted(kills.get((m, rn), []), key=lambda k: k["time_in_round_ms"])
        plant = r["plant_ms"] if r["plant_ms"] is not None and r["plant_ms"] >= 0 else None
        first = next((k for k in ks if k["killer_team"] != k["victim_team"]
                      and k["killer_team"] in ("Red", "Blue") and k["victim_team"] in ("Red", "Blue")), None)
        for T in ("Red", "Blue"):
            side = _side(T, rn)
            won = r["winning_team"] == T
            if first is not None:
                inst["opening_kill"].append({"m": m, "z": side, "a": first["killer_team"] == T, "y": won})
            mine = econ.get((m, rn, T), [])
            theirs = econ.get((m, rn, "Blue" if T == "Red" else "Red"), [])
            if len(mine) == 5 and len(theirs) == 5 and rn not in (0, 12):
                mb, tb = float(np.mean(mine)), float(np.mean(theirs))
                inst["full_buy"].append({"m": m, "z": (side, _band(tb)), "a": _band(mb) == "full", "y": won})
                off = sum(1 for v in mine if (v >= FULL_MIN and mb < ECO_MAX) or (v < ECO_MAX and mb >= FULL_MIN))
                inst["buy_sync"].append({"m": m, "z": (side, _band(mb), _band(tb)), "a": off == 0, "y": won})
            if plant is not None:
                inst["_plant"].append({"m": m, "attack": side == "attack", "won": won})
        alive = {"Red": 5, "Blue": 5}
        for i, k in enumerate(ks):
            vt, kt = k["victim_team"], k["killer_team"]
            if vt not in alive:
                continue
            alive[vt] = max(alive[vt] - 1, 0)
            if vt == kt or kt not in alive:
                continue
            t = k["time_in_round_ms"]
            planted = plant is not None and plant <= t
            traded = any(k2["victim"] == k["killer"] and k2["killer_team"] == vt
                         and 0 < k2["time_in_round_ms"] - t <= TRADE_MS for k2 in ks[i + 1:])
            won = r["winning_team"] == vt
            z = (alive[vt], alive[kt], planted)
            inst["traded_death"].append({"m": m, "z": z, "a": traded, "y": won})
            mates = [(x, y) for pl, tm, x, y in pos.get((m, k["kill"]), []) if tm == vt and pl != k["victim"]]
            if mates and k["victim_x"] is not None:
                d = min(np.hypot(x - k["victim_x"], y - k["victim_y"]) for x, y in mates) / 100.0
                if d <= NEAR_M or d > FAR_M:
                    inst["spacing_near"].append({"m": m, "z": z, "a": d <= NEAR_M, "y": won, "traded": traded})
            lead = alive[kt] - alive[vt]
            if lead == 2 and not any(r_["m"] == m and r_["round"] == rn and r_["team"] == kt for r_ in inst["_adv"][-3:]):
                inst["_adv"].append({"m": m, "round": rn, "team": kt, "won": r["winning_team"] == kt})
    meta = {"matches": len(keep), "rounds": len(R), "kills": len(K), "source": LADDER.name}
    return inst, meta


def replay_instances(keys: list[str]) -> tuple[dict, dict]:
    """Instances per question from each replay's truth, both teams."""
    inst = defaultdict(list)
    meta = Counter()
    for key in keys:
        M = Match(key)
        tl = M.tl0
        rows = ep.read_episodes(tl.match)
        hdr = next(r for r in rows if r.get("row") == "header")
        att = {int(k): v for k, v in hdr["attack_team"].items()}
        eps = [r for r in rows if r.get("row") == "episode"]
        contacts = [r for r in rows if r.get("row") == "contact"]
        team_of = {s.slot_id: s.team for s in tl.slots}
        idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
        meta["matches"] += 1
        res = {}
        for e in eps:
            if e["kind"] in ("phase_live", "phase_post_plant") and e.get("outcome"):
                res[e["round"]] = e["outcome"].get("winner")
        meta["rounds"] += len(res)
        rounds = {r["round"]: r for r in M.rounds}
        trades = {e["members"][0] for e in eps if e["kind"] == "trade"}
        dmg = [x for x in tl.events if x.kind == "damage" and x.actor in team_of and x.target in team_of
               and team_of[x.actor] != team_of[x.target]]
        meta["damage_events"] += len(dmg)
        dmg_t = np.array([x.t_ms for x in dmg])
        dmg_v = np.array([float(x.amount or 0.0) for x in dmg])
        dmg_tg = np.array([x.target for x in dmg], object)
        deaths = [x for x in tl.events if x.kind == "death" and x.actor in team_of and x.target in team_of
                  and team_of[x.actor] != team_of[x.target]]
        meta["deaths"] += len(deaths)
        for d in deaths:
            r = next((rr for rr in M.rounds if rr["t_start"] <= d.t_ms < rr["t_next"]), None)
            if r is None or r["t_end"] is None or d.t_ms > r["t_end"] or r["round"] not in res:
                continue
            T, Kt = team_of[d.target], team_of[d.actor]
            al = tl._alive_fn(np.array([d.t_ms + 1.0]))[:, 0]
            na = sum(1 for s in tl.slots if s.team == T and al[idx[s.slot_id]])
            ne = sum(1 for s in tl.slots if s.team == Kt and al[idx[s.slot_id]])
            planted = r["plant"] is not None and r["plant"].t_ms <= d.t_ms
            z = (na, ne, planted)
            won = res[r["round"]] == T
            traded = d.event_id in trades
            inst["traded_death"].append({"m": key, "z": z, "a": traded, "y": won})
            mates = [idx[s.slot_id] for s in tl.slots if s.team == T]
            ksel = np.flatnonzero((M.G >= d.t_ms - BLIND_MS) & (M.G <= d.t_ms) & (M.G_round == r["round"]))
            if ksel.size:
                seen = bool(M.sees[np.ix_(mates, [idx[d.actor]], ksel)].any())
                inst["blind_death"].append({"m": key, "z": z, "a": not seen, "y": won, "traded": traded})
                live = [i for i in mates if i != idx[d.target] and al[i]]
                if live:
                    refrag = bool(M.sees[np.ix_(live, [idx[d.actor]], ksel[-2:])].any())
                    inst["refrag_sight"].append({"m": key, "z": z, "a": refrag, "y": won, "traded": traded})
            smp = tl.sample(np.array([d.t_ms - 1.0]))
            v = idx[d.target]
            ds = [np.hypot(smp["x"][i, 0] - smp["x"][v, 0], smp["y"][i, 0] - smp["y"][v, 0]) / 100.0
                  for i in mates if i != v and smp["alive"][i, 0]]
            ds = [x for x in ds if np.isfinite(x)]
            if ds:
                dm = min(ds)
                if dm <= NEAR_M or dm > FAR_M:
                    inst["spacing_near"].append({"m": key, "z": z, "a": dm <= NEAR_M, "y": won, "traded": traded})
        acts = sorted([x for x in tl.events if x.kind in ("damage", "death") and x.actor in team_of
                       and x.target in team_of and team_of[x.actor] != team_of[x.target]], key=lambda x: x.t_ms)
        act_t = np.array([x.t_ms for x in acts])
        for C in M.teams:
            drawn = M.drawn(C)
            ei = np.flatnonzero(M.team != C)
            gopen = drawn[ei].any(axis=0)
            for e in eps:
                if e["kind"] != "engagement":
                    continue
                comb = set(e["participants"]["combatants"])
                if not any(team_of.get(x) == C for x in comb):
                    continue
                sel = np.flatnonzero((act_t >= e["t_start_ms"] - 1.0) & (act_t <= e["t_end_ms"] + 1.0))
                first = next((acts[i] for i in sel if acts[i].actor in comb and acts[i].target in comb), None)
                if first is None:
                    continue
                on = first.t_ms
                rn = e["round"]
                rec_ = {"m": key}
                for lag in (0.0, 250.0, 500.0):
                    k = np.searchsorted(M.G, on - lag, side="right") - 1
                    rec_[f"open_{int(lag)}"] = bool(k >= 0 and M.G_round[k] == rn and gopen[k])
                k = np.searchsorted(M.G, on, side="right") - 1
                lead = None
                if rec_["open_0"]:
                    j = k
                    while j > 0 and gopen[j - 1] and M.G_round[j - 1] == rn:
                        j -= 1
                    lead = on - M.G[j]
                s_c = idx[first.actor] if team_of[first.actor] == C else idx[first.target]
                d = np.hypot(M.X[ei, k] - M.X[s_c, k], M.Y[ei, k] - M.Y[s_c, k]) if k >= 0 else np.array([np.inf])
                near = np.where(np.isfinite(d), d <= LOCAL_CM, False)
                rec_["local_open"] = bool(k >= 0 and M.G_round[k] == rn
                                          and (drawn[ei, k] & (M.sees[s_c, ei, k] | near)).any())
                rec_["lead_ms"] = lead
                rec_["enemy_first"] = team_of[first.actor] != C
                inst["_gate_onset"].append(rec_)
        duels = [e for e in eps if e["kind"] == "duel"]
        for rn, winner in res.items():
            r = rounds[rn]
            for T in M.teams:
                side = "attack" if att.get(rn) == T else "defence"
                won = winner == T
                op = next((e for e in duels if e["round"] == rn and e.get("opening")
                           and e["outcome"]["result"] == "killed"), None)
                if op is not None:
                    inst["opening_kill"].append({"m": key, "z": side, "a": team_of.get(op["outcome"]["killer"]) == T,
                                                 "y": won})
                net = 0.0
                n_do = 0
                for e in duels:
                    if e["round"] != rn or e["outcome"]["result"] == "killed":
                        continue
                    n_do += 1
                    for sid, v in (e.get("damage") or {}).items():
                        net += float(v or 0.0) * (1 if team_of.get(sid) == T else -1)
                inst["_dmg_only_net"].append({"m": key, "z": side, "net": net, "y": won, "n": n_do})
                if side == "attack":
                    ex = [e for e in eps if e["kind"] == "execute" and e["round"] == rn
                          and team_of.get((e["participants"]["committed"] or [None])[0]) == T]
                    if ex:
                        mx = max(e["commitment"]["committed"] for e in ex)
                        if mx >= 3 or mx <= 1:
                            inst["execute_commit3"].append({"m": key, "z": side, "a": mx >= 3, "y": won})
                    lk = any(e["kind"] == "lurk" and e["round"] == rn
                             and team_of.get(e["participants"]["lurker"]) == T for e in eps)
                    inst["lurk_present"].append({"m": key, "z": side, "a": lk, "y": won})
                else:
                    ro = any(e["kind"] == "rotation" and e["round"] == rn
                             and team_of.get(e["participants"]["rotator"]) == T for e in eps)
                    inst["defender_rotation"].append({"m": key, "z": side, "a": ro, "y": won})
                    rt = next((e for e in eps if e["kind"] == "retake" and e["round"] == rn), None)
                    if rt is not None and team_of.get((rt["participants"].get("defenders") or [None])[0]) == T:
                        inst["_retake"].append({"m": key, "result": rt["outcome"]["result"],
                                                "entry_ms": rt.get("entry_ms"), "y": won})
                fs = []
                for c in contacts:
                    if c["round"] != rn:
                        continue
                    f_ = c.get("first_seer")
                    if f_ == "both":
                        seer = c["a"] if team_of.get(c["a"]) == T else c["b"]
                    else:
                        seer = f_ if f_ is not None and team_of.get(f_) == T else None
                    if seer is not None:
                        fs.append((c["t_start_ms"], seer))
                if fs:
                    t1, seer = min(fs)
                    smp = tl.sample(np.array([t1]))
                    v = idx[seer]
                    sup = sum(1 for s in tl.slots if s.team == T and idx[s.slot_id] != v
                              and smp["alive"][idx[s.slot_id], 0]
                              and np.hypot(smp["x"][idx[s.slot_id], 0] - smp["x"][v, 0],
                                           smp["y"][idx[s.slot_id], 0] - smp["y"][v, 0]) <= SUPPORT_CM)
                    fk = next((x for x in deaths if r["t_start"] <= x.t_ms < r["t_next"]), None)
                    inst["first_sight_support"].append({"m": key, "z": side, "a": sup >= 1, "y": won,
                                                        "first_kill": fk is not None and team_of[fk.actor] == T})
        for e in duels:
            if e["outcome"]["result"] != "killed":
                continue
            a, b = e["participants"]["a"], e["participants"]["b"]
            killer = e["outcome"]["killer"]
            if e.get("opening") and e.get("first_seer") in (a, b):
                inst["_opening_first_seer"].append({"m": key, "seer_won": e["first_seer"] == killer})
            if dmg_t.size:
                sel = (dmg_t >= e["t_start_ms"] - CHIP_MS) & (dmg_t < e["t_start_ms"])
            for x in (a, b):
                taken = float(dmg_v[sel & (dmg_tg == x)].sum()) if dmg_t.size else 0.0
                inst["_chip"].append({"m": key, "chipped": taken >= CHIP_DMG, "won": x == killer})
        print(f"value: {key[:8]} done", flush=True)
    rows = inst.pop("_dmg_only_net")
    nets = np.array([r["net"] for r in rows])
    lo, hi = np.percentile(nets, [100 / 3, 200 / 3])
    for r in rows:
        if r["net"] <= lo or r["net"] >= hi:
            inst["dmg_only_net_top"].append({"m": r["m"], "z": r["z"], "a": r["net"] >= hi, "y": r["y"]})
    meta["dmg_only_terciles"] = [round(float(lo), 1), round(float(hi), 1)]
    meta["team_rounds_with_dmg_only"] = int(sum(1 for r in rows if r["n"] > 0))
    meta["team_rounds"] = len(rows)
    return inst, dict(meta)


def combat_report_reach(keys: list[str]) -> dict:
    """What the player's combat report could give, measured on the truth
    duels of the replays whose subjects include one of the player's
    accounts: his share of his team's kill-free bouts, and how often one
    (round, enemy) row would merge several bouts."""
    import ladder_fetch as lf
    own = set(lf.owner_accounts(Path(DEFAULT_STORE)).values())
    c = Counter()
    for key in keys:
        rows = ep.read_episodes(key)
        hdr = next(r for r in rows if r.get("row") == "header")
        team_of = {s["slot_id"]: s["team"] for s in hdr["slots"]}
        me = [s for s in team_of if s in own]
        if len(me) != 1:
            continue
        me = me[0]
        c["matches"] += 1
        pairs = defaultdict(list)
        for e in rows:
            if e.get("row") != "episode" or e.get("kind") != "duel":
                continue
            p = e["participants"]
            killed = e["outcome"]["result"] == "killed"
            teams = {team_of.get(p["a"]), team_of.get(p["b"])}
            if team_of[me] in teams and not killed:
                c["team_kill_free_bouts"] += 1
            if me in (p["a"], p["b"]):
                c["player_bouts"] += 1
                c["player_kill_free_bouts"] += int(not killed)
                other = p["b"] if p["a"] == me else p["a"]
                pairs[(e["round"], other)].append(killed)
        c["player_rows"] += len(pairs)
        c["player_rows_merging_bouts"] += sum(1 for v in pairs.values() if len(v) > 1)
        c["player_rows_kill_free_only"] += sum(1 for v in pairs.values() if not any(v))
        c["player_rows_mixed"] += sum(1 for v in pairs.values() if any(v) and not all(v) and len(v) > 1)
    out = dict(c)
    if c["team_kill_free_bouts"]:
        out["player_share_of_team_kill_free"] = round(c["player_kill_free_bouts"] / c["team_kill_free_bouts"], 4)
    if c["player_rows"]:
        out["rows_merging_share"] = round(c["player_rows_merging_bouts"] / c["player_rows"], 4)
    return out


def record_value() -> int:
    """Record `value.json` in the metrics ledger: per question its
    difference, interval, counts and stake (|difference| x instances per
    team-match; `stake_lo` from the interval's end nearer 0, 0 when the
    interval spans 0)."""
    from reticle.metrics import record as rec
    v = json.loads((OUT / "value.json").read_text(encoding="utf-8"))
    for src in ("ladder", "replays"):
        for q, o in v[src].items():
            if not o.get("n"):
                continue
            lo, hi = o["ci"]
            near0 = 0.0 if lo <= 0 <= hi else min(abs(lo), abs(hi))
            vals = {k: o[k] for k in ("diff", "n", "n_a1", "n_a0", "y_a1", "y_a0", "per_team_match", "matches")
                    if o.get(k) is not None}
            vals.update({"ci_lo": lo, "ci_hi": hi, "stake": round(abs(o["diff"]) * o["per_team_match"], 3),
                         "stake_lo": round(near0 * o["per_team_match"], 3)})
            for k in ("traded_a1", "traded_a0", "first_kill_a1", "first_kill_a0"):
                if o.get(k) is not None:
                    vals[k] = o[k]
            rec("coaching_questions", part=f"value/{src}/{q}", session="pooled", values=vals,
                deps={"version": v["version"], "episodes": ep.EPISODES_VERSION},
                context={"task": TASK, **(v["ladder_meta"] if src == "ladder" else {"matches": v["replay_meta"]["matches"]})})
    ex = dict(v["extra"])
    ex.get("retake", {}).pop("entry_ms_p50", None)
    for k, vals in ex.items():
        flat = {}
        for kk, vv in vals.items():
            if isinstance(vv, dict):
                flat.update({f"{kk}.{a}": b for a, b in vv.items()})
            elif vv is not None:
                flat[kk] = vv
        rec("coaching_questions", part=f"value/extra/{k}", session="pooled", values=flat,
            deps={"version": v["version"], "episodes": ep.EPISODES_VERSION}, context={"task": TASK})
    rec("coaching_questions", part="value/meta", session="pooled",
        values={**{f"ladder.{a}": b for a, b in v["ladder_meta"].items() if not isinstance(b, str)},
                **{f"replays.{a}": b for a, b in v["replay_meta"].items() if not isinstance(b, list)}},
        deps={"version": v["version"]}, context={"task": TASK})
    return 0


def run_value() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    lad, lmeta = ladder_instances()
    rep, rmeta = replay_instances(replay_matches())
    res = {"version": VERSION, "ladder_meta": lmeta, "replay_meta": rmeta, "ladder": {}, "replays": {}, "extra": {}}
    for src, inst in (("ladder", lad), ("replays", rep)):
        for q, rows in inst.items():
            if q.startswith("_"):
                continue
            out = _stratified(rows)
            out["per_team_match"] = round(len(rows) / (2 * len({r["m"] for r in rows})), 3)
            for extra in ("traded", "first_kill"):
                if rows and extra in rows[0]:
                    a1 = [r[extra] for r in rows if r["a"]]
                    a0 = [r[extra] for r in rows if not r["a"]]
                    out[f"{extra}_a1"] = round(float(np.mean(a1)), 4) if a1 else None
                    out[f"{extra}_a0"] = round(float(np.mean(a0)), 4) if a0 else None
            res[src][q] = out
    ch = rep.get("_chip", [])
    c1 = [r["won"] for r in ch if r["chipped"]]
    c0 = [r["won"] for r in ch if not r["chipped"]]
    res["extra"]["chip"] = {"n_chipped": len(c1), "won_chipped": round(float(np.mean(c1)), 4) if c1 else None,
                            "n_clean": len(c0), "won_clean": round(float(np.mean(c0)), 4) if c0 else None}
    of = rep.get("_opening_first_seer", [])
    res["extra"]["opening_first_seer"] = {"n": len(of),
                                          "seer_won": round(float(np.mean([r["seer_won"] for r in of])), 4) if of else None}
    rt = rep.get("_retake", [])
    em = [r["entry_ms"] for r in rt if r["entry_ms"] is not None]
    res["extra"]["retake"] = {"n": len(rt), "results": dict(Counter(r["result"] for r in rt)),
                              "with_entry": len(em)}
    go = rep.get("_gate_onset", [])
    if go:
        miss = [r for r in go if not r["open_0"]]
        leads = [r["lead_ms"] for r in go if r["lead_ms"] is not None]
        res["extra"]["gate_onset"] = {
            "n": len(go), "open_0": round(float(np.mean([r["open_0"] for r in go])), 4),
            "open_250": round(float(np.mean([r["open_250"] for r in go])), 4),
            "open_500": round(float(np.mean([r["open_500"] for r in go])), 4),
            "local_open": round(float(np.mean([r["local_open"] for r in go])), 4),
            "lead_ms_p50": round(float(np.median(leads)), 1) if leads else None,
            "lead_ms_p10": round(float(np.percentile(leads, 10)), 1) if leads else None,
            "misses": len(miss),
            "miss_enemy_first": round(float(np.mean([r["enemy_first"] for r in miss])), 4) if miss else None}
    pl = lad.get("_plant", [])
    res["extra"]["plant"] = {"planted_rounds": len(pl) // 2,
                             "attack_win_after_plant": round(float(np.mean([r["won"] for r in pl if r["attack"]])), 4) if pl else None}
    sys.path.insert(0, str(HERE))
    res["extra"]["combat_report"] = combat_report_reach(replay_matches())
    adv = lad.get("_adv", [])
    res["extra"]["two_player_lead"] = {"n": len(adv), "converted": round(float(np.mean([r["won"] for r in adv])), 4) if adv else None}
    (OUT / "value.json").write_text(json.dumps(res, indent=1, default=_jd), encoding="utf-8")
    print(json.dumps(res, indent=1, default=_jd))
    return 0


def inventory(record: bool = False) -> dict:
    """Row counts of every stored source the catalogue draws on; the
    held-out replay is dropped by name before any file opens."""
    import glob
    import pyarrow.parquet as pq
    S = Path(DEFAULT_STORE)
    inv = {}
    vrf = sorted(Path(p).stem for p in glob.glob(str(S / "external" / "replays" / "*.vrf")))
    keys = replay_matches()
    kinds = Counter()
    for k in keys:
        for r in ep.read_episodes(k):
            if r.get("row") == "episode":
                kinds[r["kind"]] += 1
            elif r.get("row") in ("contact", "act"):
                kinds[r["row"] + ("_death" if r.get("act") == "death" else "")] += 1
    inv["replays"] = {"vrf_files": len(vrf), "layers_read": len(keys), "held_out_dropped": 1,
                      "rounds": kinds["phase_buy"], "kill_acts": kinds["act_death"], "duels": kinds["duel"],
                      "engagements": kinds["engagement"], "contacts": kinds["contact"], "executes": kinds["execute"],
                      "rotations": kinds["rotation"], "lurks": kinds["lurk"], "retakes": kinds["retake"],
                      "trades": kinds["trade"]}
    riot = sorted(glob.glob(str(S / "external" / "riot" / "*.json")))
    rr = kk = 0
    for p in riot:
        if Path(p).stem.startswith(HELD_OUT_PREFIX):
            continue
        d = json.loads(Path(p).read_text(encoding="utf-8"))
        d = d.get("match", d)
        rr += len(d.get("roundResults") or [])
        kk += len(d.get("kills") or [])
    inv["riot"] = {"records": len(riot), "rounds": rr, "kills": kk}
    pd_ = sorted(Path(p).stem for p in glob.glob(str(S / "external" / "riot-pd-v1" / "raw" / "*.json")))
    lm = pq.read_table(LADDER / "matches.parquet").to_pydict()
    lids = set(lm["match_id"])
    inv["riot_pd_v1"] = {"records": len(pd_), "in_ladder": sum(p in lids for p in pd_),
                         "in_riot": sum(p in {Path(x).stem for x in riot} for p in pd_)}
    inv["ladder"] = {"matches": len(lids), "holdout": int(sum(bool(h) for h in lm["holdout"])),
                     "replays_in_ladder": sum(v in lids for v in vrf)}
    for t in ("rounds", "kills", "positions", "economy"):
        inv["ladder"][t] = pq.read_table(LADDER / f"{t}.parquet").num_rows
    cs = S / "external" / "cs"
    inv["cs"] = {"esta_demos": json.loads((cs / "esta" / "SOURCE.json").read_text(encoding="utf-8")).get("demos")}
    for sub, tabs in (("esta", ("rounds", "kills", "frames", "states")),
                      ("kaggle_mm", ("rounds", "kills", "damage", "states")),
                      ("kaggle_mm_mirror", ("meta", "kills", "dmg_file_rank"))):
        for t in tabs:
            f = cs / sub / f"{t}.parquet"
            if f.is_file():
                inv["cs"][f"{sub}.{t}"] = pq.read_metadata(f).num_rows
    maps = json.loads((S / "external" / "valorant-api" / "maps.json").read_text(encoding="utf-8"))
    maps = maps.get("data", maps) if isinstance(maps, dict) else maps
    inv["valorant_api"] = {"maps": len(maps), "maps_with_callouts": sum(1 for m in maps if m.get("callouts"))}
    print(json.dumps(inv, indent=1))
    if record:
        from reticle.metrics import record as rec
        for src, vals in inv.items():
            rec("coaching_questions", part=f"inventory/{src}", session="store", values=vals,
                deps={"version": VERSION}, context={"task": TASK})
    return inv


#: The degraded questions, each with the counts its agreement reads.
QUESTIONS = {
    "attack_team": "instant", "round_result": "instant", "opening_first_seer": "instant",
    "spacing_death": "instant", "spacing_5m": "spacing5", "first_sight_support": "instant",
    "execute_commit_band": "instant", "peek_C": "instant", "peek_pair": "instant", "corner_C": "instant",
    "duel_C": "episodic", "contact_C": "episodic", "engagement_C": "episodic", "trade_C": "episodic",
    "execute_C": "episodic", "rotation_C": "episodic", "lurk_C": "episodic", "retake_C": "retake",
    "execute_E": "episodic", "rotation_E": "episodic", "lurk_E": "episodic",
}


def _agree(rows: list[dict], q: str, ref: str) -> tuple[float | None, int, int]:
    """(agreement, numerator, denominator) pooled over rows."""
    kind = QUESTIONS[q]
    num = den = 0
    for r in rows:
        sc = r.get(ref)
        if not sc:
            continue
        if kind == "spacing5":
            v = sc["spacing_death"]
            num += v["agree_5m"]
            den += v["n"]
        elif kind == "instant":
            if q not in sc:
                continue
            v = sc[q]
            num += v["agree"]
            den += v["n"] + v.get("extra", 0)
        elif kind == "retake":
            v = sc[q]
            num += v["agree_entry"]
            den += v["n"] + v.get("extra", 0)
        else:
            v = sc[q]
            num += v["same"]
            den += v["n"] + v["arm"] - v["tp"]
    return (num / den if den else None), num, den


def pooled(rows: list[dict]) -> dict:
    from reticle.metrics import wilson
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    out = {}
    for arm, rs in by.items():
        reads = sum(r["cost"].get("reads", 0) for r in rs)
        den = sum(r["cost"].get("denominator", 0) for r in rs)
        fr = sum(r["cost"].get("frames_read", 0) for r in rs)
        fl = sum(r["cost"].get("frames_live", 0) for r in rs)
        o = {"perspectives": len(rs), "share": (reads / den) if den else 1.0,
             "frame_share": (fr / fl) if fl else 1.0, "vs_T1": {}, "vs_T0": {}}
        cc = [r["cost"]["concurrency"] for r in rs if r["cost"].get("concurrency")]
        if cc:
            w = sum(c["drawn_samples"] for c in cc)
            o["concurrency"] = {k: round(sum(c[k] * c["drawn_samples"] for c in cc if c[k] is not None) / w, 4)
                                for k in ("ge2", "ge3")}
            o["concurrency"]["subject_perspectives"] = sum(c["player"] == "subject" for c in cc)
        for ref in ("vs_T1", "vs_T0"):
            for q in QUESTIONS:
                a, k, n = _agree(rs, q, ref)
                if a is None:
                    continue
                o[ref][q] = {"agree": round(a, 4), "k": k, "n": n, "ci": [round(x, 4) for x in wilson(k, n)]}
                if QUESTIONS[q] == "episodic":
                    tp = sum(r[ref][q]["tp"] for r in rs if r.get(ref))
                    nn = sum(r[ref][q]["n"] + r[ref][q]["arm"] for r in rs if r.get(ref))
                    o[ref][q]["f1"] = round(2 * tp / nn, 4) if nn else None
        out[arm] = o
    if "T1" in out:
        out["T1"]["vs_T1"] = {q: {"agree": 1.0, "k": 0, "n": 0, "ci": [1.0, 1.0]} for q in QUESTIONS}
    return out


def cheapest(P: dict, qs: list[str], bar: float = 0.95, ref: str = "vs_T1") -> tuple[str | None, float | None]:
    best = None
    for arm, o in P.items():
        if arm in ("T0",):
            continue
        if all(o[ref].get(q, {}).get("agree", 0) >= bar for q in qs):
            if best is None or o["share"] < P[best]["share"]:
                best = arm
    return best, (P[best]["share"] if best else None)


def report(record: bool = False, path: Path | None = None, session: str | None = None,
           matches: str = "") -> int:
    path = Path(path or OUT / "degrade.jsonl")
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines() if s.strip()]
    if matches:
        want = tuple(m.lstrip("-") for m in matches.split(",") if m)
        drop = matches.startswith("-")
        rows = [r for r in rows if r["match"].startswith(want) != drop]
    matches = sorted({r["match"] for r in rows})
    P = pooled(rows)
    order = sorted(P, key=lambda a: P[a]["share"])
    qs = [q for q in QUESTIONS]
    print(f"{len(matches)} matches, {len(rows) // max(len(P), 1)} perspectives per arm")
    print("arm".ljust(12) + "share  fshare " + " ".join(q[:9].rjust(9) for q in qs))
    for arm in order:
        o = P[arm]
        print(arm.ljust(12) + f"{o['share']:.3f}  {o['frame_share']:.3f} "
              + " ".join(f"{o['vs_T1'].get(q, {}).get('agree', float('nan')):9.3f}" for q in qs))
    print("\nT1 against T0 (censoring):")
    print("  " + "; ".join(f"{q} {v['agree']:.3f} ({v['k']}/{v['n']})" for q, v in P["T1"]["vs_T0"].items()))
    print("\nCheapest arm at >= 0.95 against T1, per question:")
    cheap = {}
    for q in qs:
        arm, sh = cheapest(P, [q])
        cheap[q] = (arm, sh)
        print(f"  {q}: {arm} share {sh if sh is None else round(sh, 3)}")
    summary = {"version": VERSION, "matches": matches, "pooled": P, "cheapest": cheap}
    cv = corner_value(rows)
    if cv:
        summary["corner_value"] = cv
        print("Corner distance (T0):", json.dumps(cv))
    pv = peek_value(rows)
    if pv:
        summary["peek_value"] = pv
        print("Peeker against holder (T0):", json.dumps(pv))
    (path.parent / (path.stem + "_pooled.json")).write_text(json.dumps(summary, indent=1, default=_jd), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        sess = session or ("pooled17" if len(matches) >= 17 else f"pooled{len(matches)}")
        for arm, o in P.items():
            vals = {"share": round(o["share"], 4), "frame_share": round(o["frame_share"], 4)}
            vals.update({f"concurrency.{k}": v for k, v in (o.get("concurrency") or {}).items()})
            for ref in ("vs_T1", "vs_T0"):
                for q, v in o[ref].items():
                    if v["n"]:
                        vals[f"{ref}.{q}"] = v["agree"]
                        if v.get("f1") is not None:
                            vals[f"{ref}.{q}.f1"] = v["f1"]
            rec("coaching_questions", part=f"degrade/{arm}", session=sess, values=vals,
                deps={"version": VERSION, "episodes": ep.EPISODES_VERSION, "arm": ARMS.get(arm, {})},
                context={"task": TASK, "matches": len(matches), "perspectives": o["perspectives"]})
        if cv:
            flat = {}
            for k, v in cv.items():
                if isinstance(v, dict):
                    for a, b in v.items():
                        if isinstance(b, list):
                            flat[f"{k}.{a}_lo"], flat[f"{k}.{a}_hi"] = b
                        elif b is not None:
                            flat[f"{k}.{a}"] = b
                elif v is not None:
                    flat[k] = v
            rec("coaching_questions", part="value/extra/corner", session=sess, values=flat,
                deps={"version": VERSION, "episodes": ep.EPISODES_VERSION},
                context={"task": TASK, "matches": len(matches), "deg": list(CORNER_DEG), "sep_cm": CORNER_SEP_CM,
                         "long_cm": LONG_CM, "wide_cm": WIDE_CM})
        if pv:
            rec("coaching_questions", part="value/extra/peek", session=sess,
                values={k: v for k, v in pv.items() if v is not None and not isinstance(v, list)}
                | ({"ci_lo": pv["ci"][0], "ci_hi": pv["ci"][1]} if pv.get("ci") else {}),
                deps={"version": VERSION, "episodes": ep.EPISODES_VERSION},
                context={"task": TASK, "matches": len(matches), "peek_cms": PEEK_CMS, "window_ms": PEEK_WIN_MS})
    return 0


def corner_value(rows: list[dict]) -> dict | None:
    """CQ18 on T0, one perspective per match (the first team) so each duel
    counts once: the far side's win share; far against near stratified by
    both peek states; wide against tight long-angle peekers; the player's
    wide share."""
    first = {}
    for r in rows:
        if r["arm"] == "T1" and "corner_value" in r:
            first.setdefault(r["match"], r["team"])
    inst, wide, n_all, n_both, mine = [], [], 0, 0, []
    for r in rows:
        if r["arm"] != "T1" or "corner_value" not in r or first[r["match"]] != r["team"]:
            continue
        for dc, de, L, sc, se, won, is_me in r["corner_value"]:
            n_all += 1
            if dc is None or de is None:
                continue
            n_both += 1
            if abs(dc - de) >= CORNER_SEP_CM:
                inst.append({"m": r["match"], "z": (sc, se), "a": dc > de, "y": bool(won)})
            if L >= LONG_CM:
                for d_, st, y in ((dc, sc, bool(won)), (de, se, not won)):
                    if st == "peek":
                        wide.append({"m": r["match"], "z": "all", "a": d_ >= WIDE_CM, "y": y})
    # the player's long-angle peeks, from both perspectives
    for r in rows:
        if r["arm"] != "T1" or "corner_value" not in r:
            continue
        for dc, de, L, sc, se, won, is_me in r["corner_value"]:
            if is_me and dc is not None and L >= LONG_CM and sc == "peek":
                mine.append(dc >= WIDE_CM)
    if not inst:
        return None
    far_won = float(np.mean([x["y"] == x["a"] for x in inst]))
    return {"duels": n_all, "both_found": round(n_both / max(n_all, 1), 4), "n_far_near": len(inst),
            "far_won": round(far_won, 4), "far_vs_near": _stratified(inst), "wide_vs_tight": _stratified(wide),
            "player_long_peeks": len(mine), "player_wide_share": round(float(np.mean(mine)), 4) if mine else None}


def peek_value(rows: list[dict]) -> dict | None:
    """CQ17 on T0: with exactly one peeker, the peeker's kill-duel win share
    (each duel counted once), with a 1000-draw match bootstrap."""
    per = defaultdict(lambda: [0, 0])
    states = Counter()
    for r in rows:
        if r["arm"] != "T1" or "peek_value" not in r:
            continue
        for sc, se, won in r["peek_value"]:
            states[(sc, se)] += 1
            if {sc, se} == {"peek", "hold"}:
                per[r["match"]][0] += int((sc == "peek") == bool(won))
                per[r["match"]][1] += 1
    if not per:
        return None
    ms = sorted(per)
    a = np.array([per[m] for m in ms], float)
    rng = np.random.default_rng(7)
    W = rng.multinomial(len(ms), np.full(len(ms), 1.0 / len(ms)), size=1000)
    boot = (W @ a[:, 0]) / np.maximum(W @ a[:, 1], 1)
    tot = sum(states.values())
    return {"peeker_won": round(float(a[:, 0].sum() / a[:, 1].sum()), 4), "n_one_peeker": int(a[:, 1].sum() / 2),
            "ci": [round(float(np.percentile(boot, 2.5)), 4), round(float(np.percentile(boot, 97.5)), 4)],
            "duels": tot // 2, "both_peek": round(states[("peek", "peek")] / tot, 4),
            "both_hold": round(states[("hold", "hold")] / tot, 4),
            "one_peeker": round((states[("peek", "hold")] + states[("hold", "peek")]) / tot, 4),
            "unknown": round(sum(v for k, v in states.items() if None in k) / tot, 4), "matches": len(ms)}


# ----------------------------------------------------------------- cost target

COST_SESSION = "9acf02f98283"
COST_RUNS = {"cv4": "04c2c241", "cv12": "e5c119ba"}    # ally_icon cache passes, least and most contended
MINIMAP_RUN = "791fcd16"                               # minimap+ping video pass
CAPTURE_HZ = 60.0
TARGET_MS = 1.0                                        # the player's stretch goal, per captured frame


def _usage(run_prefix: str) -> dict:
    p = Path(DEFAULT_STORE) / "notes" / "usage.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if run_prefix in line:
            r = json.loads(line)
            if r.get("run_id", "").startswith(run_prefix):
                return r
    raise SystemExit(f"usage run {run_prefix} not found")


def _manifest_fps(session: str) -> float:
    m = json.loads((Path(DEFAULT_STORE) / "manifests" / f"{session}.json").read_text(encoding="utf-8"))
    return float(m["source"]["fps"])


def cost(record: bool, pooled_paths: list[Path]) -> int:
    """Today's per-frame reading cost from `reticle usage`'s stored runs, and
    each arm's implied cost per captured frame against TARGET_MS: the 15 Hz
    readers' ms per read frame x the arm's share x (15 / capture rate)."""
    fps = _manifest_fps(COST_SESSION)
    mm = _usage(MINIMAP_RUN)["readers"]["minimap"]["feed"]
    mm_ms = mm["total_ns"] / mm["count"] / 1e6
    today = {"capture_fps": fps}
    for tag, run in COST_RUNS.items():
        a = _usage(run)["readers"]["ally_icon"]["feed"]
        ai = a["total_ns"] / a["count"] / 1e6
        today[f"{tag}.ally_icon_ms_per_read"] = round(ai, 3)
        today[f"{tag}.ally_icon_fed"] = int(a["count"])
        today[f"{tag}.per_read_ms"] = round(ai + mm_ms, 3)
        today[f"{tag}.per_captured_ms"] = round((ai + mm_ms) * ((1000.0 / FRAME_MS) / fps), 3)
    today["minimap_ms_per_read"] = round(mm_ms, 3)
    today["minimap_fed"] = int(mm["count"])
    arms = {}
    for path in pooled_paths:
        P = json.loads(path.read_text(encoding="utf-8"))["pooled"]
        for arm, o in P.items():
            if arm in ("T0", "T1") or arm in arms:
                continue
            row = {"share": round(o["share"], 4), "frame_share": round(o["frame_share"], 4)}
            for tag in COST_RUNS:
                per = today[f"{tag}.per_read_ms"] * ((1000.0 / FRAME_MS) / fps)
                row[f"{tag}.slot_ms"] = round(per * o["share"], 3)
                row[f"{tag}.frame_ms"] = round(per * o["frame_share"], 3)
            row["meets_target_cv4_frame"] = row["cv4.frame_ms"] <= TARGET_MS
            arms[arm] = row
    out = {"today": today, "arms": arms, "target_ms": TARGET_MS}
    print(json.dumps(out, indent=1))
    (OUT / "cost.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        deps = {"version": VERSION, "runs": {**COST_RUNS, "minimap": MINIMAP_RUN}}
        rec("coaching_questions", part="cost/today", session=COST_SESSION, values=today, deps=deps,
            context={"task": TASK, "basis": "feed ms per fed frame from notes/usage.jsonl; per captured frame x 15/fps"})
        for arm, row in arms.items():
            rec("coaching_questions", part=f"cost/{arm}", session="pooled17", values=row, deps=deps,
                context={"task": TASK, "target_ms": TARGET_MS, "basis": "per captured 60 Hz frame"})
    return 0


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("degrade")
    d.add_argument("matches", nargs="*")
    d.add_argument("--all", action="store_true")
    d.add_argument("--arms", default="")
    d.add_argument("--out", default=str(OUT / "degrade.jsonl"))
    co = sub.add_parser("cost")
    co.add_argument("--record", action="store_true")
    co.add_argument("--pooled", default="degrade_pooled.json,degrade_attention_pooled.json")
    sub.add_parser("value")
    sub.add_parser("record-value")
    iv = sub.add_parser("inventory")
    iv.add_argument("--record", action="store_true")
    r = sub.add_parser("report")
    r.add_argument("--record", action="store_true")
    r.add_argument("--path", default=None)
    r.add_argument("--session", default=None)
    r.add_argument("--matches", default="", help="prefixes to keep, or -prefixes to drop")
    a = ap.parse_args(argv)
    _idle()
    if a.cmd == "degrade":
        keys = replay_matches() if a.all else a.matches
        full = replay_matches()
        keys = [next(m for m in full if m.startswith(k)) for k in keys]
        arms = [x for x in a.arms.split(",") if x] or list(ARMS)
        out = Path(a.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        done = set()
        if out.is_file():
            for s in out.read_text(encoding="utf-8").splitlines():
                if s.strip():
                    done.add(json.loads(s)["match"])
        for k in keys:
            if k in done:
                print(f"{k[:8]} already in {out.name}; skipped", flush=True)
                continue
            degrade_match(k, arms, out)
        return 0
    if a.cmd == "cost":
        return cost(a.record, [OUT / x for x in a.pooled.split(",") if (OUT / x).is_file()])
    if a.cmd == "value":
        return run_value()
    if a.cmd == "record-value":
        return record_value()
    if a.cmd == "inventory":
        inventory(record=a.record)
        return 0
    return report(record=a.record, path=a.path, session=a.session, matches=a.matches)


if __name__ == "__main__":
    raise SystemExit(main())
