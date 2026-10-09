r"""Stored real reads on the truth grid, and the QA5r3 score of read schedules.

[owns:read-schedule-loss] Moved from `prototypes/real_reader_schedule.py` on 2026-10-09 (task
`harness-t1d-20261009`). `RealMatch(sid)` is a development capture's replay
truth (`match.Match`) with its clock (the killfeed fit, `clock.capture_to_replay`
at `REMOTE_LAG_MS` or `SELF_LAG_MS`), the minimap crop cache's spans, the stored
enemy reads (`enemy_reads`, each track sorted by `track_outcome`) and the
vision slots (`slot_state.build_slots`); `join_runs` joins times onto a stored
15 Hz grid.

**QA5r3** (docs/QUESTION_ACCEPTANCE.md section 7): `qa5r2_pool` scores each arm
per sight question: accuracy against T1, the loss against its reference with a
paired bootstrap over (match, round) clusters, and the verdict. A question
fails only when the interval's upper end lies below -`QA5R3_TOL`; the read
share must stay at most `QA5R2_CAP`. `acceptance hook` runs the production
ally gate (`reticle.ally_gate`) through the passes hook over each session's
stored 15 Hz `ally_icon` frames and keeps V15h's fits where the gate reads
(`Vhook`) or reads or audits (`Vhook+a`); `acceptance hook-report` pools the
arms (dev3, new3, all6) under QA5r3 with read share and CPU per session;
`acceptance arms-report` scores the stored arms of
`prototypes/real_reader_schedule.py run`. The arms' read schedules (Lp, Lpv,
Vgate) stay in that prototype as development tooling.

The held-out capture (cea8ecbc94ab, replay bd7efa02) is refused before any
row is read.
"""
from __future__ import annotations

import json
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from reticle import slot_state as ss
from reticle.frame_join import grid_join
from reticle.store import DEFAULT_STORE

from . import clock as rt
from . import match as cq
from .match import CutTimeline, Match, _with_sides, answers, score


def _canon(a):
    return None if a is None else str(a).strip().lower().replace("/", "")


def truth_slot_map(slots: list[dict], truth_agents: list[str]) -> tuple[dict, list]:
    """Truth agent -> slot index: the arbiter's names, then one-to-one
    elimination of what is left (evaluation only)."""
    by = {_canon(s["agent"]): k for k, s in enumerate(slots) if s["agent"]}
    out, notes = {}, []
    left_t = []
    for a in truth_agents:
        if _canon(a) in by:
            out[_canon(a)] = by[_canon(a)]
        else:
            left_t.append(a)
    left_s = [k for k in range(5) if k not in out.values()]
    if len(left_t) == 1 and len(left_s) == 1:
        out[_canon(left_t[0])] = left_s[0]
        notes.append({"truth": left_t[0], "slot": left_s[0], "how": "elimination",
                      "slot_agent": slots[left_s[0]]["agent"]})
    elif left_t:
        notes.append({"unmapped_truth": left_t, "free_slots": left_s})
    return out, notes


VERSION = "real-reader-schedule-0.1.0"
TASK = "real-reader-schedule-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
HELD_OUT = ("cea8ecbc94ab", "bd7efa02")


#: The registered real-enemy development pair; 9acf02f98283 gained its
#: enemy streams after registration and is pooled beside, never judged.
JUDGED = ("c817691bcd15", "d3dcfb182ab1")
SIGHT_QS = ("opening_first_seer", "spacing_5m", "spacing_death", "first_sight_support",
            "contact_C", "duel_C", "trade_C")
#: Each arm's reference arm for agreement and paired flips.
REF = {"Lp": "T1", "T1v": "T1", "Lpv": "T1v", "Lpv-reach": "T1v", "V15h": "T1v",
       "Vgate": "V15h", "V15t": "T1", "Vgate-t": "V15t",
       "Vgate-t-r": "V15t", "Vgate-r": "V15h", "Vgate-t-r1": "V15t",
       "Vgate-d": "V15h", "Vgate-t-d": "V15t"}
#: QA5r2 (player, 2026-10-07): an arm's accuracy against T1 at most this far below its reference's.
QA5R2_TOL, QA5R2_CAP, BOOT_N, BOOT_SEED = 0.03, 0.06, 2000, 7
#: QA5r3 (player, 2026-10-07): a question fails only when the loss interval's upper end lies below -0.05.
QA5R3_TOL = 0.05


#: Arms run before QA5r2 was registered: their verdicts are post hoc.
POST_HOC = ("Lp", "T1v", "Lpv", "Lpv-reach", "V15h", "Vgate", "Vgate-r", "V15t", "Vgate-t", "Vgate-t-r",
            "Vgate-t-r1")


ORDER = ("Lp", "T1v", "Lpv", "Lpv-reach", "V15h", "Vgate", "Vgate-r", "Vgate-d", "V15t", "Vgate-t",
         "Vgate-t-r", "Vgate-t-r1", "Vgate-t-d")
ENEMY_GAP_MS = 125.0      # bridges consecutive real reads only (15 Hz cache steps 66.7-83.3 ms)
JOIN_HZ = 15.0            # the declared rate of the ally_icon and minimap_object grids


def refuse(name: str) -> None:
    if str(name).startswith(HELD_OUT):
        raise SystemExit("the held-out match (cea8ecbc94ab / bd7efa02) is never read")


def _log(msg: str) -> None:
    print(msg, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def join_runs(t_a, t_b) -> tuple[np.ndarray, object, float]:
    """`grid_join` of times A onto grid stream B, restricted by the caller to
    the A times B could hold: inside B's own runs (consecutive frames at most
    1.5 steps apart). The declared rate is B's slowest regular step (its 99th
    percentile; the grids step 66.7 and 83.3 ms on c817691bcd15), never above
    15 Hz. Returns (inrun mask over A, the join of A[inrun], the rate);
    a refused join raises."""
    a = np.asarray(t_a, float)
    B = np.asarray(t_b, float)
    step = float(np.percentile(np.diff(B), 99)) if B.size > 1 else 1000.0 / JOIN_HZ
    rate = min(JOIN_HZ, 1000.0 / step)
    brk = np.flatnonzero(np.diff(B) > 1.5 * step) if B.size > 1 else np.zeros(0, int)
    r_lo = np.r_[B[:1], B[brk + 1]]
    r_hi = np.r_[B[brk], B[-1:]]
    tol = 500.0 / rate
    i = np.searchsorted(r_lo - tol, a, side="right") - 1
    inrun = (i >= 0) & (a <= r_hi[np.clip(i, 0, None)] + tol)
    J = grid_join(a[inrun], B, rate)
    if J.index is None:
        raise SystemExit(f"join refused: {J.refused}")
    return inrun, J, rate


def track_outcome(agent: str | None, status: str | None, foe: dict,
                  reality: str | None = None) -> tuple[str, int]:
    """One emitted enemy track's lane outcome and its enemy replay subject.

    `foe` maps `agent_names.agent_key` of each enemy-team agent to its replay
    subjects (evaluation only). `reality_refused`: the track's
    `reality_status` is `refused` (`round_lifetimes.detection_reality`), so it
    is no entity, whatever its name; `identity_abstained`: the arbiter did not
    resolve the track (any status but `resolved`); `agent_not_on_enemy_team`:
    it named an agent that is not exactly one enemy subject; `named`: the
    subject. A dropped track's subject is -1."""
    from reticle.agent_names import agent_key
    if reality == "refused":
        return "reality_refused", -1
    if status != "resolved":
        return "identity_abstained", -1
    js = foe.get(agent_key(agent), [])
    if len(js) != 1:
        return "agent_not_on_enemy_team", -1
    return "named", int(js[0])


class RealMatch(Match):
    """A development capture's replay truth with its stored real reads."""

    def __init__(self, sid: str):
        from reticle import roi_cache
        from reticle.replay_source import capture_replay_context, replay_entry
        refuse(sid)
        entry = replay_entry(sid, STORE)
        if entry is None:
            raise SystemExit(f"{sid}: no replay")
        key = Path(entry["file"]).stem
        refuse(key)
        super().__init__(key)
        self.cap = sid
        ctx = capture_replay_context(sid, None, STORE)
        out = ctx["out"]
        if out.get("refused"):
            raise SystemExit(f"{sid}: replay context refused: {out['refused']}")
        al = out["align"]
        self.clock = (float(al["a_ls_ms"]), float(al["slope"]))
        head = json.loads((STORE / "analysis" / "replay-layer" / self.tl0.match / "layer.json")
                          .read_text(encoding="utf-8"))
        self.clock1 = (float(head["a_ms"]), 1.0)
        self.me = ctx["me"]
        self.agent = ctx["agent"]
        self.C = str(self.team[self.sid.index(self.me)])
        self.ci = np.flatnonzero(self.team == self.C)
        self.ei = np.flatnonzero(self.team != self.C)
        rec = roi_cache.stored_record(STORE, sid, "minimap")
        self.spans = (rec or {}).get("spans") or []
        self.cache_hz = (rec or {}).get("hz")

    def lag(self, s: int) -> float:
        return rt.SELF_LAG_MS if self.sid[s] == self.me else rt.REMOTE_LAG_MS

    def to_rep(self, t_cap, lag, clock=None):
        return rt.capture_to_replay(t_cap, *(clock or self.clock), lag)

    def to_cap(self, t_rep, lag):
        a, b = self.clock
        return a + b * (np.asarray(t_rep, float) + lag)

    def in_spans(self, t_cap):
        from reticle import roi_cache
        return roi_cache.spans_mask(t_cap, self.spans)

    # ------------------------------------------------------------- schedule hook

    # ------------------------------------------------------------- enemy reads

    def enemy_reads(self) -> dict | None:
        """Real enemy icons and identity-resolved tracks, in world cm on the
        replay clock, with every drop counted."""
        from reticle.agent_names import agent_key
        p_mo = STORE / "events" / "minimap_object" / f"{self.cap}.jsonl"
        p_et = STORE / "events" / "enemy_track" / f"{self.cap}.jsonl"
        if not (p_mo.is_file() and p_et.is_file()):
            return None
        MO = rt.load_minimap_object(self.cap)
        wf, why = ss.world_frame(self.cap)
        if wf is None:
            raise SystemExit(f"{self.cap}: world frame refused: {why}")
        _mf, to_m, _mpp = wf
        upm = ss.units_per_m()
        ents, obs = {}, []
        stamp, track_n = {}, {}
        for r in rt._rows(p_et):
            k = r.get("kind")
            if k == "entity":
                ents[r["id"]] = (r.get("agent"), r.get("identity_status"), r.get("identity_reason"),
                                 r.get("reality_status"))
                track_n[r["id"]] = r.get("observations")
            elif k == "observation":
                obs.append((int(r["frame_idx"]), float(r["t_ms"]), float(r["x"]), float(r["y"]),
                            r.get("entity_id"), int(str(r["observation_key"]).split(":")[1])))
            elif k == "summary":
                stamp = {x: r.get(x) for x in ("enemy_track_version", "minimap_object_version",
                                               "agent_identity_version", "lineup_version")}
        foe = {}
        for j in self.ei:
            foe.setdefault(agent_key(self.agent.get(self.sid[j])), []).append(int(j))
        drops = Counter()
        track_subj, track_out = {}, {}
        for eid, (ag, st, _why, real) in ents.items():
            track_out[eid], track_subj[eid] = track_outcome(ag, st, foe, real)
            if track_out[eid] != "named":
                drops[f"track:{track_out[eid]}"] += 1
        # icons of the read frames, frame position p in MO's frame order
        pos_of = {int(f): i for i, f in enumerate(MO["frame_idx"])}
        ip = np.array([pos_of[int(f)] for f in MO["enemy_frame"]], np.int64)
        within = np.zeros(ip.size, np.int64)
        if ip.size:
            first = np.r_[True, ip[1:] != ip[:-1]]
            starts = np.flatnonzero(first)
            within = np.arange(ip.size) - np.repeat(starts, np.diff(np.r_[starts, ip.size]))
        icon_of = {(int(MO["frame_idx"][p]), int(w)): i for i, (p, w) in enumerate(zip(ip, within))}
        ix, iy = to_m(MO["enemy_x"], MO["enemy_y"])
        ix, iy = ix * upm, iy * upm
        isub = np.full(ip.size, -1, np.int64)
        ieid = np.full(ip.size, None, dtype=object)
        o_t, o_x, o_y, o_j = [], [], [], []
        for f, t, x, y, eid, w in obs:
            j = track_subj.get(eid, -1)
            if eid not in ents:
                drops["obs:no_entity"] += 1
                continue
            i = icon_of.get((f, w))
            if i is not None:
                ieid[i] = eid
            if j < 0:
                drops[f"obs:{track_out[eid]}"] += 1
                continue
            i = icon_of.get((f, w))
            if i is None:
                drops["obs:no_minimap_object_icon"] += 1
            else:
                isub[i] = j
            o_t.append(t)
            o_x.append(x)
            o_y.append(y)
            o_j.append(j)
        o_t = np.asarray(o_t, float)
        mx, my = to_m(np.asarray(o_x, float), np.asarray(o_y, float))
        rep = self.to_rep(o_t, rt.REMOTE_LAG_MS)
        return {"MO": MO, "icon_p": ip, "icon_x": ix, "icon_y": iy, "icon_subj": isub,
                "obs_t_cap": o_t, "obs_t": rep, "obs_x": mx * upm, "obs_y": my * upm,
                "obs_j": np.asarray(o_j, np.int64), "drops": dict(drops), "stamp": stamp,
                "tracks": len(ents), "observations": len(obs),
                # per icon, the track its observation joined (None: no track);
                # per track, its lane outcome and agent (question_acceptance)
                "icon_eid": ieid, "track_outcome": track_out,
                "track_agent": {eid: v[0] for eid, v in ents.items()},
                "track_obs": track_n}

    def t1v_tracks(self, E: dict) -> tuple[dict, dict, dict]:
        """T0 allies; each enemy only at its mapped real reads."""
        from reticle.replay_source import MAX_GAP_MS
        tracks, gaps, cnt = {}, {}, Counter()
        smp = self.tl0.sample(E["obs_t"]) if E["obs_t"].size else None
        alive = self._alive_at(E["obs_t"])
        for s, sid in enumerate(self.sid):
            if self.team[s] == self.C:
                tracks[sid], gaps[sid] = self.tl0.tracks[sid], MAX_GAP_MS
                continue
            m = E["obs_j"] == s
            cnt["read_while_truth_dead"] += int((m & ~alive[s]).sum()) if alive is not None else 0
            idx = np.flatnonzero(m)
            T = E["obs_t"][idx]
            o = np.argsort(T, kind="stable")
            idx, T = idx[o], T[o]
            keep = np.r_[True, np.diff(T) > 0.5] if T.size else np.zeros(0, bool)
            cnt["duplicate_same_frame"] += int((~keep).sum())
            idx = idx[keep]
            tracks[sid] = {"t": E["obs_t"][idx], "x": E["obs_x"][idx], "y": E["obs_y"][idx],
                           "z": smp["z"][s, idx], "yaw": smp["yaw"][s, idx], "pitch": smp["pitch"][s, idx]}
            gaps[sid] = ENEMY_GAP_MS
            cnt["enemy_reads"] += int(idx.size)
        return tracks, gaps, dict(cnt)

    def _alive_at(self, t):
        t = np.asarray(t, float)
        return self.tl0._alive_fn(t) if t.size else None

    # ------------------------------------------------------------- vision allies

    def vision_slots(self) -> dict:
        G = ss.build_slots(self.cap, binding="causal")
        if "refused" in G:
            return {"refused": G["refused"]}
        tmap, notes = truth_slot_map(G["L"]["slots"], [self.agent.get(self.sid[s]) for s in self.ci])
        S = G["S"]
        slot_of = {}
        for s in self.ci:
            k = tmap.get(_canon(self.agent.get(self.sid[s])))
            slot_of[int(s)] = None if k is None else int(k)
        in_sp = self.in_spans(S.fr_t)
        return {"G": G, "slot_of": slot_of, "notes": notes, "fr_t": S.fr_t, "in_sp": in_sp, "drawn": S.fr_drawn,
                "X": G["bind"]["X"] * ss.units_per_m(), "Y": G["bind"]["Y"] * ss.units_per_m(),
                "has": G["bind"]["has"], "cost": G["cost"]}

    def _track(self, s, T, x, y, nan_starts=True) -> dict:
        """Reads of slot s on the replay clock: z, yaw, pitch from T0, a NaN
        at each life's open (no read before the first fit), the last read held
        to the life's end (`read_tracks`' rule)."""
        sid = self.sid[s]
        o = np.argsort(T, kind="stable")
        T, x, y = T[o], x[o], y[o]
        keep = np.r_[True, np.diff(T) > 0.5] if T.size else np.zeros(0, bool)
        T, x, y = T[keep], x[keep], y[keep]
        smp = self.tl0.sample(T) if T.size else {k: np.zeros((len(self.slots), 0)) for k in ("z", "yaw", "pitch")}
        z, yaw, pitch = smp["z"][s], smp["yaw"][s], smp["pitch"][s]
        ht, hi = [], []
        for a, e in self.lives[sid]:
            inside = np.flatnonzero((T >= a) & (T < e))
            if inside.size and T[inside[-1]] < e - 1.0:
                ht.append(e - 1.0)
                hi.append(inside[-1])
        cols = [x, y, z, yaw, pitch]
        if ht:
            idx = np.concatenate([np.arange(T.size), hi])
            T = np.concatenate([T, ht])
            cols = [c[idx] for c in cols]
        if nan_starts:
            ns = np.array([a - 1.0 for a, _e in self.lives[sid]])
            T = np.concatenate([T, ns])
            cols = [np.concatenate([c, np.full(ns.size, np.nan)]) for c in cols]
        o = np.argsort(T, kind="stable")
        x, y, z, yaw, pitch = (c[o] for c in cols)
        return {"t": T[o], "x": x, "y": y, "z": z, "yaw": yaw, "pitch": pitch}

    def _cost(self, n_reads: int, frames_read: int, lost: Counter) -> dict:
        alive_ms = sum(e - a for s in self.ci for a, e in self.lives[self.sid[s]])
        frames_live = int(self.F_alive[self.ci].any(axis=0).sum())
        den = alive_ms / cq.FRAME_MS
        return {"reads": int(n_reads), "denominator": den, "share": n_reads / den,
                "frames_read": int(frames_read), "frames_live": frames_live,
                "frame_share": frames_read / max(frames_live, 1), "lost": dict(lost)}

    def v15_tracks(self, V: dict) -> tuple[dict, dict, dict]:
        """Allies from the causal fits at every ally_icon frame in the spans."""
        tracks, gaps, lost = {}, {}, Counter()
        n_reads, frames = 0, set()
        self._v15_reads = {}
        for s in self.ci:
            k = V["slot_of"][int(s)]
            if k is None:
                lost["slot_unnamed"] += 1
                tracks[self.sid[s]] = {"t": np.zeros(0), "x": np.zeros(0), "y": np.zeros(0),
                                       "z": np.zeros(0), "yaw": np.zeros(0), "pitch": np.zeros(0)}
                gaps[self.sid[s]] = np.inf
                continue
            f = np.flatnonzero(V["in_sp"] & V["has"][k])
            T = self.to_rep(V["fr_t"][f], self.lag(s))
            al = self.tl0._alive_fn(T)[s] if T.size else np.zeros(0, bool)
            lost["fit_while_truth_dead"] += int((~al).sum())
            f, T = f[al], T[al]
            n_reads += int(f.size)
            frames.update(f.tolist())
            self._v15_reads[int(s)] = T
            tracks[self.sid[s]] = self._track(s, T, V["X"][k, f], V["Y"][k, f])
            gaps[self.sid[s]] = np.inf
        return tracks, gaps, self._cost(n_reads, len(frames), lost)


def _ok_set(T: dict, A: dict, q: str) -> set:
    if q == "spacing_5m":
        t, a = T["spacing_death"], A["spacing_death"]
        return {k for k, v in t.items() if k in a and v is not None and a[k] is not None
                and (v == 0) == (a[k] == 0)}
    if q in cq.EPISODIC:
        pairs = cq._pair_up(T[q], A[q])
        return {i for i, j in pairs if cq._attrs_equal(q, T[q][i], A[q][j])}
    return {k for k, v in T[q].items() if k in A[q] and A[q][k] == v}


def flips(T0: dict, Aref: dict, Aarm: dict) -> dict:
    """Per sight question, against T0: items the reference had right and the
    arm wrong (`broken`) and the opposite (`fixed`)."""
    out = {}
    for q in SIGHT_QS:
        r, a = _ok_set(T0, Aref, q), _ok_set(T0, Aarm, q)
        n = len(T0["spacing_death" if q == "spacing_5m" else q])
        out[q] = {"n": n, "ref_ok": len(r), "arm_ok": len(a), "broken": len(r - a), "fixed": len(a - r)}
    return out


def _answers(M, tracks, gaps, events, name):
    tl = CutTimeline(M.tl0, tracks, gaps, events, name)
    d = M.derive(tl)
    if not hasattr(M, "TL"):
        M.TL = {}
    M.TL[name] = tl
    return answers(d, tl, M.C, M.occ)


def _round_of(M, t: float) -> int:
    for r in M.rounds:
        if r["t_start"] <= t < r["t_next"]:
            return int(r["round"])
    return -1


def paired_T1(M, arm: str, ref: str) -> dict:
    """QA5r2's paired data: per sight question, each T1 instance as
    [round, ref right, arm right] against T1, and the arm's phantoms."""
    T1 = M.A["T1"]
    ev = {e.event_id: float(e.t_ms) for e in M.tl0.events}
    out = {}
    for q in SIGHT_QS:
        a_ok, r_ok = _ok_set(T1, M.A[arm], q), _ok_set(T1, M.A[ref], q)
        if q in cq.EPISODIC:
            keys = list(range(len(T1[q])))
            rnd = [_round_of(M, float(T1[q][i]["s"])) for i in keys]
        elif q == "first_sight_support":
            keys = list(T1[q])
            rnd = [int(k) for k in keys]
        else:
            keys = list(T1["spacing_death" if q == "spacing_5m" else q])
            rnd = [_round_of(M, ev.get(k, np.nan)) for k in keys]
        rec = {"i": [[r, int(k in r_ok), int(k in a_ok)] for k, r in zip(keys, rnd)]}
        if q in cq.EPISODIC:
            rec["phantoms"] = len(M.A[arm][q]) - len(cq._pair_up(T1[q], M.A[arm][q]))
        out[q] = rec
    return out


def _arm_row(M, arm, cost, extra=None) -> dict:
    ref = REF[arm]
    r = {"version": VERSION, "session": M.cap, "match": M.tl0.match, "team": M.C, "arm": arm, "ref": ref,
         "cost": cost, "vs_T0": score(M.A["T0"], M.A[arm]), "vs_T1": score(M.A["T1"], M.A[arm]),
         "vs_ref": score(M.A[ref], M.A[arm]), "flips": flips(M.A["T0"], M.A[ref], M.A[arm]),
         "paired_T1": paired_T1(M, arm, ref)}
    r.update(extra or {})
    return r


def qa5r2_pool(rows: list[dict], rule: str = "QA5r2") -> dict:
    """QA5r2 per arm and sight question: accuracy against T1, the loss
    against the reference with a paired round-bootstrap interval, the verdict."""
    rng = np.random.default_rng(BOOT_SEED)
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    out = {}
    for arm, rs in by.items():
        den = sum(r["cost"].get("denominator", 0) for r in rs)
        reads = sum(r["cost"].get("reads", 0) for r in rs)
        share = reads / den if den else None
        o = {"ref": REF[arm], "share": share, "post_hoc": arm in POST_HOC, "q": {}}
        scode = {s: k for k, s in enumerate(dict.fromkeys(r["session"] for r in rs))}
        for q in SIGHT_QS:
            # each instance as (session code, round, ref right, arm right)
            parts = [np.asarray(r["paired_T1"][q]["i"], np.int64).reshape(-1, 3) for r in rs]
            S = np.repeat([scode[r["session"]] for r in rs], [p.shape[0] for p in parts])
            X = np.concatenate(parts) if parts else np.zeros((0, 3), np.int64)
            if not X.shape[0]:
                continue
            ro, ao = X[:, 1], X[:, 2]
            # clusters are (session, round), numbered in order of first appearance
            _u, first, inv = np.unique(np.stack([S, X[:, 0]], 1), axis=0, return_index=True,
                                       return_inverse=True)
            rank = np.empty(first.size, np.int64)
            rank[np.argsort(first, kind="stable")] = np.arange(first.size)
            cid = rank[inv.reshape(-1)]
            d = np.bincount(cid, weights=(ao - ro).astype(float), minlength=first.size)
            n = np.bincount(cid, minlength=first.size).astype(float)
            a = np.bincount(cid, weights=ao.astype(float), minlength=first.size)
            W = rng.multinomial(d.size, np.full(d.size, 1.0 / d.size), size=BOOT_N).astype(float)
            boot = (W @ d) / np.maximum(W @ n, 1.0)
            loss = d.sum() / n.sum()
            lo, hi = np.percentile(boot, [2.5, 97.5])
            ph = sum(r["paired_T1"][q].get("phantoms", 0) for r in rs)
            o["q"][q] = {"n": int(n.sum()), "acc": round(float(a.sum() / n.sum()), 4),
                         "acc_ref": round(float((a.sum() - d.sum()) / n.sum()), 4),
                         "loss": round(float(loss), 4), "ci": [round(float(lo), 4), round(float(hi), 4)],
                         "pass": (bool(loss >= -QA5R2_TOL) if rule == "QA5r2" else bool(hi >= -QA5R3_TOL)),
                         "ci_excludes_tol": bool(lo > -QA5R2_TOL),
                         "ci_hi_below_005": bool(hi < -QA5R3_TOL),
                         "broken": int(((ro != 0) & (ao == 0)).sum()),
                         "fixed": int(((ao != 0) & (ro == 0)).sum()), "clusters": int(d.size),
                         **({"phantoms": ph} if q in cq.EPISODIC else {})}
        o["share_ok"] = share is not None and share <= QA5R2_CAP
        o["all_pass"] = all(v["pass"] for v in o["q"].values())
        o["pass_except_spacing_death"] = all(v["pass"] for q, v in o["q"].items() if q != "spacing_death")
        o["verdict"] = "pass" if (o["all_pass"] and o["share_ok"]) else "fail"
        out[arm] = o
    return out


def report_qa5r2(record: bool = False, rule: str = "QA5r2") -> int:
    rows = [json.loads(x) for x in (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    tol = QA5R2_TOL if rule == "QA5r2" else QA5R3_TOL
    res = {"rule": rule, "tol": tol, "cap": QA5R2_CAP, "boot": {"n": BOOT_N, "seed": BOOT_SEED,
                                                              "unit": "(match, round)"},
           "pools": {"dev2": qa5r2_pool([r for r in rows if r["session"] in JUDGED], rule),
                     "dev3": qa5r2_pool(rows, rule)}}
    for pname, P in res["pools"].items():
        print(f"\n== {rule} pool {pname}: acc vs T1 | loss vs ref [95% CI] | pass")
        print("arm".ljust(11) + "ref".ljust(6) + "share   " + " ".join(q[:12].rjust(30) for q in SIGHT_QS) + "  verdict")
        for arm in ORDER:
            if arm not in P:
                continue
            o = P[arm]
            cells = []
            for q in SIGHT_QS:
                v = o["q"].get(q)
                cells.append((f"{v['acc']:.3f} {v['loss']:+.3f}[{v['ci'][0]:+.3f},{v['ci'][1]:+.3f}]"
                              f"{'P' if v['pass'] else 'F'}").rjust(30) if v else "-".rjust(30))
            sh = "   -  " if o["share"] is None else f"{o['share']:.4f}"
            print(arm.ljust(11) + o["ref"].ljust(6) + sh + "  " + " ".join(cells)
                  + f"  {o['verdict']}{' (post hoc)' if (o['post_hoc'] or rule == 'QA5r3') else ''}")
    (OUT / f"{rule.lower()}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        for pname, P in res["pools"].items():
            for arm, o in P.items():
                vals = {"pass": o["verdict"] == "pass"}
                if o["share"] is not None:
                    vals["share"] = round(o["share"], 4)
                for q, v in o["q"].items():
                    vals.update({f"{q}.acc": v["acc"], f"{q}.acc_ref": v["acc_ref"], f"{q}.loss": v["loss"],
                                 f"{q}.ci_lo": v["ci"][0], f"{q}.ci_hi": v["ci"][1], f"{q}.n": v["n"]})
                rec("real_reader_schedule", part=f"{rule.lower()}/{arm}", session=pname, values=vals,
                    deps={"version": VERSION, "rule": rule, "tol": tol, "cap": QA5R2_CAP,
                          "boot": [BOOT_N, BOOT_SEED]},
                    context={"task": TASK, "ref": o["ref"], "post_hoc": o["post_hoc"] or rule == "QA5r3"})
    return 0


HOOK_TASK = "gate-hook-20261009"
HOOK_BASE = STORE / "analysis" / HOOK_TASK


def hook_out(version: str) -> Path:
    """Where the hook's results for gate `version` live: 0.1.0's at the
    task's root, where they were first written; each later gate's beside
    them, under its version."""
    return HOOK_BASE if version == "ally-gate-0.1.0" else HOOK_BASE / version


HOOK_DEV = ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1")
HOOK_NEW = ("cadaadeb2d8b", "066741deafe5", "9912c382130b")
#: Hook arms: V15h's fits kept only on the frames the gate reads
#: (`Vhook`), and on those plus its audit windows (`Vhook+a`).
REF.update({"Vhook": "V15h", "Vhook+a": "V15h", "Vgated": "V15h"})
ORDER = ORDER + ("Vhook", "Vhook+a", "Vgated")
#: Stored beside every hook result: what the simulated arms leave out.
HOOK_CAVEAT = ("Vhook and Vhook+a keep V15h's fits and its causal binding, both made on the "
               "continuous 15 Hz pass, whose pose priors never see a gap; a gated pass refits "
               "after gaps (full pose searches) and binds from its own frames, so the simulated "
               "arms overstate it. Vgated scores a real gated stream, rebuilt through "
               "slot_state.build_slots from its own rows.")
#: The real gated streams scored as `Vgated`, by session.
HOOK_REAL = {"ally-gate-0.1.0": {"cadaadeb2d8b": "ally_icon_gated"},
             "ally-gate-0.2.0": {"cadaadeb2d8b": "ally_icon_gated2"},
             "ally-gate-0.3.0": {"cadaadeb2d8b": "ally_icon_gated3"}}


def ally_ms_per_frame(sid: str) -> dict:
    """The stored 15 Hz arm's ally_icon cost per frame, from the scan record
    that wrote it, chosen explicitly: a completed `vod_scan` whose ally_icon
    ran at 15 Hz and fed exactly the stored `ally_icon` stream's frame count,
    recorded at most 10 minutes after that file was last written (publish
    moves the file before the record is written; a later gated reread offers
    the same count and must never stand in). Thread CPU, else feed time,
    over the frames fed."""
    import datetime as _dt
    path = STORE / "events" / "ally_icon" / f"{sid}.jsonl"
    with path.open(encoding="utf-8") as fh:
        head = json.loads(fh.readline())
    frames = int(head["frames"])
    written = _dt.datetime.fromtimestamp(path.stat().st_mtime, _dt.timezone.utc)
    pick = None
    for line in (STORE / "notes" / "usage.jsonl").open(encoding="utf-8"):
        if "vod_scan" not in line or sid not in line or "ally_icon" not in line:
            continue
        r = json.loads(line)
        if r.get("session_id") != sid or r.get("status") != "completed":
            continue
        rd = r.get("readers") or {}
        a = rd.get("ally_icon") if isinstance(rd, dict) else None
        if not a or float(a.get("hz") or 0) != 15.0 or a.get("fed") != frames:
            continue
        if _dt.datetime.fromisoformat(r["recorded_at"]) > written + _dt.timedelta(minutes=10):
            continue
        pick = (r, a)
    if pick is None:
        return {"ms": None, "reason": f"no completed 15 Hz scan record feeding {frames} frames "
                                      f"before {written.isoformat()}"}
    r, a = pick
    ns, what = (a["thread_cpu_ns"], "thread_cpu_ns") if a.get("thread_cpu_ns") else \
        (a["feed"]["total_ns"], "feed.total_ns (wall)")
    return {"ms": ns / 1e6 / a["fed"], "frames": a["fed"], "what": what, "source": r["source"],
            "run_id": r["run_id"], "recorded_at": r["recorded_at"],
            "rule": "15 Hz, fed == stored ally_icon frames, recorded within 10 min after the stream was written"}


def stored_ally_frames(sid: str) -> dict:
    """The stored ally_icon frames (time order) and each frame's teammate
    icons as the gate counts them (`ally_gate.teammate_fits`)."""
    from reticle.ally_gate import teammate_fits
    t, fi, icons = [], [], defaultdict(list)
    for line in (STORE / "events" / "ally_icon" / f"{sid}.jsonl").open(encoding="utf-8"):
        if '"kind":"frame"' in line:
            r = json.loads(line)
            t.append(float(r["t_ms"]))
            fi.append(int(r["frame_idx"]))
        elif '"kind":"icon"' in line:
            r = json.loads(line)
            icons[int(r["frame_idx"])].append(r)
    o = np.argsort(np.asarray(t, float), kind="stable")
    t = np.asarray(t, float)[o]
    fi = np.asarray(fi, np.int64)[o]
    return {"t": t, "fi": fi, "fits": {f: teammate_fits(v) for f, v in icons.items()}}


def simulate_gate(sid: str, A: dict | None = None) -> dict:
    """The ally gate (`ALLY_GATE_VERSION`) run over the stored 15 Hz ally_icon frames in order,
    through the production hook (`passes.gate_decide`, `gate_after`): each
    offered frame asks the gate; a frame it reads feeds back the teammate
    icons stored there. The spans are the frames' runs (cut at gaps over
    1 s), standing for the pass's live-round spans. No replay is read."""
    from types import SimpleNamespace

    from reticle.minimap import AllyIconReader
    from reticle.passes import gate_after, gate_decide
    from reticle.slot_state import ally_gate_for
    A = stored_ally_frames(sid) if A is None else A
    gate = ally_gate_for(sid, STORE)
    if isinstance(gate, dict):
        raise SystemExit(f"{sid}: ally gate refused: {gate['refused']}")
    t = A["t"]
    cut = np.flatnonzero(np.diff(t) > 1000.0) + 1
    lo, hi = np.r_[0, cut], np.r_[cut, t.size] - 1
    spans = [(float(t[a]), float(t[b])) for a, b in zip(lo, hi)]
    fits = A["fits"]
    fi_of = dict(zip(t.tolist(), A["fi"].tolist()))
    shim = SimpleNamespace(spans=spans, frame_gate=gate, wants=gate.wants,
                           opportunity_gate=AllyIconReader.opportunity_gate.bound(gate.rests_on))
    shim.observed = lambda tm: gate.observed(tm, fits.get(fi_of[float(tm)], []))
    c0 = time.process_time()
    for tm in t.tolist():
        d = gate_decide(shim, tm)
        if d.read or d.audit:
            gate_after(shim, tm, d)
    cpu = time.process_time() - c0
    log = shim.gate_log
    return {"log": log, "summary": log.summary(), "offered": int(t.size), "spans": len(spans),
            "gate_cpu_s": round(cpu, 3), "gate_us_per_offered": round(cpu / max(t.size, 1) * 1e6, 2),
            "params": gate.params(), "rests_on": list(gate.rests_on)}


def hook_arms(sid: str) -> tuple[list[dict], dict]:
    """V15h against the gated arms on one replay capture: T0, T1, real
    enemies (T1v), V15h's allies, then V15h's fits kept only at the frames
    the simulated gate reads. The binding is V15h's own, made over every
    15 Hz frame: a gated pass would bind from its own frames alone."""
    t0 = time.time()
    M = RealMatch(sid)
    d0 = M.derive(M.tl0)
    M.d0 = d0
    M.events = _with_sides(M.tl0, d0.header["attack_team"])
    M.drawn_C = M.drawn(M.C)
    M.A = {"T0": answers(d0, M.tl0, M.C, M.occ)}
    tr1, gp1 = M.t1_tracks(M.C, M.drawn_C)
    M.A["T1"] = _answers(M, tr1, gp1, M.events, "t1")
    E = M.enemy_reads()
    if E is None:
        raise SystemExit(f"{sid}: no stored minimap_object or enemy_track")
    V = M.vision_slots()
    if "refused" in V:
        raise SystemExit(f"{sid}: build_slots refused: {V['refused']}")
    trE, gpE, _cntE = M.t1v_tracks(E)
    M.A["T1v"] = _answers(M, trE, gpE, M.events, "T1v")
    enemies = {M.sid[j]: trE[M.sid[j]] for j in M.ei}
    egaps = {M.sid[j]: gpE[M.sid[j]] for j in M.ei}
    trV, gpV, costV = M.v15_tracks(V)
    M.A["V15h"] = _answers(M, {**trV, **enemies}, {**gpV, **egaps}, M.events, "V15h")
    rows = [_arm_row(M, "V15h", costV)]
    sim = simulate_gate(sid)
    log = sim["log"]
    cost_ms = ally_ms_per_frame(sid)
    read_t = np.asarray(sorted(log.read_t), float)
    both = np.asarray(sorted(set(log.read_t) | set(log.audit_t)), float)
    info = {"session": sid, "gate": sim["summary"], "offered": sim["offered"], "spans": sim["spans"],
            "gate_us_per_offered": sim["gate_us_per_offered"], "params": sim["params"],
            "rests_on": sim["rests_on"], "ally_cost": cost_ms, "caveat": HOOK_CAVEAT,
            "gate_version": sim["log"].version}
    for arm, keep in (("Vhook", read_t), ("Vhook+a", both)):
        Vh = dict(V)
        Vh["has"] = V["has"] & np.isin(V["fr_t"], keep)[None, :]
        tr, gp, cost = M.v15_tracks(Vh)
        cost["gate_frames"] = int(keep.size)
        cost["gate_frame_share"] = keep.size / max(sim["offered"], 1)
        if cost_ms.get("ms"):
            cost["ally_cpu_s_15hz"] = round(cost_ms["ms"] * sim["offered"] / 1000.0, 1)
            # The pass reads the audit frames whichever arm scores them.
            cost["ally_cpu_s_est"] = round(cost_ms["ms"] * both.size / 1000.0
                                           + sim["gate_us_per_offered"] * sim["offered"] / 1e6, 1)
        M.A[arm] = _answers(M, {**tr, **enemies}, {**gp, **egaps}, M.events, arm)
        rows.append(_arm_row(M, arm, cost, {"read_ratio_vs_ref": cost["reads"] / max(costV["reads"], 1)}))
    from reticle.ally_gate import ALLY_GATE_VERSION
    stream = HOOK_REAL.get(ALLY_GATE_VERSION, {}).get(sid)
    if stream is not None:
        Vg = gated_slots(M, stream)
        tr, gp, cost = M.v15_tracks(Vg)
        cost["gate_frames"] = int(Vg["fr_t"].size)
        cost["gate_frame_share"] = Vg["fr_t"].size / max(sim["offered"], 1)
        cost["stream"] = stream
        M.A["Vgated"] = _answers(M, {**tr, **enemies}, {**gp, **egaps}, M.events, "Vgated")
        rows.append(_arm_row(M, "Vgated", cost,
                             {"read_ratio_vs_ref": cost["reads"] / max(costV["reads"], 1)}))
        info["real_stream"] = {"stream": stream, "frames": int(Vg["fr_t"].size),
                               "slots": {M.sid[s]: k for s, k in Vg["slot_of"].items()}}
    _log(f"  {sid} hook arms in {time.time() - t0:.0f} s: gate frames {read_t.size}/{sim['offered']} "
         f"(+audit {both.size}), Vhook share {rows[1]['cost']['share']:.4f}")
    return rows, info


def gated_slots(M, stream: str) -> dict:
    """`M.vision_slots()` rebuilt from a stored gated stream instead of the
    15 Hz `ally_icon`: `slot_state` reads its ally rows from `stream` for
    this call only, so the binding and the beliefs are the gated pass's own."""
    import reticle.slot_state as ss
    real = ss._jsonl
    want = f"{M.cap}.jsonl"

    def redirected(path):
        path = Path(path)
        if path.name == want and path.parent.name == "ally_icon":
            path = path.parent.parent / stream / path.name
        return real(path)
    ss._jsonl = redirected
    try:
        V = M.vision_slots()
    finally:
        ss._jsonl = real
    if "refused" in V:
        raise SystemExit(f"{M.cap}: build_slots on {stream} refused: {V['refused']}")
    return V


def run_hook(sessions: list[str]) -> int:
    for s in sessions:
        refuse(s)
    from reticle.ally_gate import ALLY_GATE_VERSION
    HOOK_OUT = hook_out(ALLY_GATE_VERSION)
    HOOK_OUT.mkdir(parents=True, exist_ok=True)
    rows, infos = [], []
    for s in sessions:
        rw, info = hook_arms(s)
        rows += rw
        infos.append(info)
        with (HOOK_OUT / "rows.jsonl").open("w", encoding="utf-8") as f:
            for x in rows:
                f.write(json.dumps(x, default=cq._jd) + "\n")
        (HOOK_OUT / "info.json").write_text(json.dumps(infos, indent=1, default=cq._jd),
                                            encoding="utf-8")
    return 0


def report_hook(record: bool = False) -> int:
    """QA5r3 per pool for the hook arms, and read share and CPU per session."""
    from reticle.ally_gate import ALLY_GATE_VERSION
    HOOK_OUT = hook_out(ALLY_GATE_VERSION)
    rows = [json.loads(x) for x in (HOOK_OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines()
            if x.strip()]
    infos = {i["session"]: i for i in json.loads((HOOK_OUT / "info.json").read_text(encoding="utf-8"))}
    pools = {"dev3": [r for r in rows if r["session"] in HOOK_DEV],
             "new3": [r for r in rows if r["session"] in HOOK_NEW], "all6": rows}
    pools["cadaadeb2d8b"] = [r for r in rows if r["session"] == "cadaadeb2d8b"]
    res = {"rule": "QA5r3", "gate": ALLY_GATE_VERSION, "tol": QA5R3_TOL, "cap": QA5R2_CAP,
           "caveat": HOOK_CAVEAT,
           "pools": {k: qa5r2_pool(v, "QA5r3") for k, v in pools.items() if v}, "sessions": {}}
    print("session        offered  gate  +audit  frame_share  +audit  slot_share(V15h)  "
          "cpu_15hz_s  cpu_gated_s  ms/frame")
    for r in rows:
        if r["arm"] != "Vhook":
            continue
        s = r["session"]
        ra = next(x for x in rows if x["session"] == s and x["arm"] == "Vhook+a")
        rv = next(x for x in rows if x["session"] == s and x["arm"] == "V15h")
        c, ca = r["cost"], ra["cost"]
        ms = infos[s]["ally_cost"].get("ms")
        res["sessions"][s] = {"offered": infos[s]["offered"], "gate_frames": c["gate_frames"],
                              "audit_frames": ca["gate_frames"], "frame_share": c["gate_frame_share"],
                              "frame_share_audit": ca["gate_frame_share"], "slot_share": c["share"],
                              "slot_share_v15h": rv["cost"]["share"],
                              "cpu_15hz_s": c.get("ally_cpu_s_15hz"), "cpu_gated_s": c.get("ally_cpu_s_est"),
                              "cpu_gated_audit_s": ca.get("ally_cpu_s_est"), "ms_per_frame": ms,
                              "opened": infos[s]["gate"]["opened_reasons"],
                              "refused": infos[s]["gate"]["refused_reasons"]}
        print(f"{s}  {infos[s]['offered']:>7d} {c['gate_frames']:>5d} {ca['gate_frames']:>7d}"
              f"  {c['gate_frame_share']:.4f}      {ca['gate_frame_share']:.4f}  "
              f"{c['share']:.4f} ({rv['cost']['share']:.4f})   {c.get('ally_cpu_s_15hz')!s:>9}"
              f"  {c.get('ally_cpu_s_est')!s:>10}  {ms if ms is None else round(ms, 1)}")
    for pname, P in res["pools"].items():
        print(f"\n== QA5r3 pool {pname}: acc vs T1 | loss vs V15h [95% CI] | pass")
        for arm in ("Vhook", "Vhook+a", "Vgated"):
            o = P.get(arm)
            if o is None:
                continue
            print(f"{arm} share {o['share']:.4f} verdict {o['verdict']}")
            for q in SIGHT_QS:
                v = o["q"].get(q)
                if v:
                    print(f"   {q:22s} n {v['n']:>4d} acc {v['acc']:.3f} ref {v['acc_ref']:.3f} "
                          f"loss {v['loss']:+.4f} [{v['ci'][0]:+.4f}, {v['ci'][1]:+.4f}] "
                          f"{'pass' if v['pass'] else 'FAIL'}")
    (HOOK_OUT / "qa5r3.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        for pname, P in res["pools"].items():
            for arm, o in P.items():
                vals = {"pass": o["verdict"] == "pass", "share": round(o["share"], 4)}
                for q, v in o["q"].items():
                    vals.update({f"{q}.loss": v["loss"], f"{q}.ci_lo": v["ci"][0],
                                 f"{q}.ci_hi": v["ci"][1], f"{q}.n": v["n"]})
                rec("real_reader_schedule", part=f"hook/{arm}", session=pname, values=vals,
                    deps={"version": VERSION, "gate": ALLY_GATE_VERSION, "rule": "QA5r3"},
                    context={"task": HOOK_TASK, "ref": o["ref"], "caveat": HOOK_CAVEAT})
        for s, v in res["sessions"].items():
            rec("real_reader_schedule", part="hook/cost", session=s,
                values={k: (round(x, 4) if isinstance(x, float) else x) for k, x in v.items()
                        if not isinstance(x, dict)},
                deps={"version": VERSION, "gate": ALLY_GATE_VERSION},
                context={"task": HOOK_TASK, "caveat": HOOK_CAVEAT})
    return 0
