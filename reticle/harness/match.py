r"""The truth grid: one replay's truth, its sight and the frames a reader sees.

Part of the one acceptance harness (`reticle.acceptance`, docs/QUESTION_ACCEPTANCE.md
B7), moved from `prototypes/coaching_questions.py` on 2026-10-09 (task
`harness-t1d-20261009`). Replay data is evaluation truth only.

`Match(key)` holds T0 (`episodes.from_replay_layer`), truth sight on derive's
16 Hz grid round by round (`G`, `G_round`, `sees`, `X`, `Y`, `Z`, `YAW`,
`PITCH`), today's 15 Hz frame grid (`F`, `F_k`, `F_round`, `F_alive`) and the
T1 draw rule (`drawn`: a living player of the team saw the enemy within the
last `P_MS`). `t1_tracks` keeps T1's drawn enemies as tracks. `answers` and
`score` derive the catalogue's sight questions from one arm's episodes and
score them against a reference. The read schedules of the coaching study
(`Match.schedule`, `read_tracks`, `windows`) stay in
`prototypes/coaching_questions.py`, which subclasses this `Match`.
"""
from __future__ import annotations

import ctypes
from collections import defaultdict
from pathlib import Path

import numpy as np

from reticle import episodes as ep
from reticle.dev_set import FROZEN_HELD_OUT_REPLAY
from reticle.store import DEFAULT_STORE


#: The frozen held-out replay (`reticle.dev_set`), never read.
HELD_OUT_PREFIX = FROZEN_HELD_OUT_REPLAY


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

    def drawn(self, C: str, p_ms: float = P_MS, sees: np.ndarray | None = None) -> np.ndarray:
        """drawn[j, k]: enemy j of team C is on C's minimap at grid sample k:
        a living C player saw him within the last P (truth sight). `p_ms` and
        `sees` default to T1's P and sight; `t1_draw_rule` passes its own."""
        ci = np.flatnonzero(self.team == C)
        vis = (self.sees if sees is None else sees)[ci].any(axis=0)   # (S, K): j seen by some C player
        vis[ci] = False
        n = int(round(p_ms / SIGHT_MS))
        out = vis.copy()
        for rn in np.unique(self.G_round):
            sl = np.flatnonzero(self.G_round == rn)
            v = vis[:, sl]
            c = np.cumsum(np.concatenate([np.zeros((v.shape[0], 1), int), v.astype(int)], axis=1), axis=1)
            lo = np.clip(np.arange(sl.size) - n, 0, None)
            out[:, sl] = (c[:, np.arange(sl.size) + 1] - c[:, lo]) > 0
        return out

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
