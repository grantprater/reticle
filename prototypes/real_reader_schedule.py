r"""Does the `Lp0.5-250w5` read schedule survive the real stored readers?

A storage-only pilot (task `real-reader-schedule-20261007`, rows RR0-RR6 in
the store's `notes/predictions.jsonl`). It is a substitution ladder on
`coaching_questions.py`'s truth harness: each arm replaces one truth input
with stored real reads and keeps the rest, then answers the catalogue's
sight questions through the same `derive_episodes` and `answers`.

    python prototypes/real_reader_schedule.py run SESSION [SESSION ...]
    python prototypes/real_reader_schedule.py report [--record]
    python prototypes/real_reader_schedule.py cost SESSION --crops 600 [--record]
    python prototypes/real_reader_schedule.py outcome

Arms, the capturing team's perspective only (the layer's self subject):

* `Lp`: `coaching_questions` `Lp0.5-250w5` on T1, reproduced (the instrument,
  RR0a, against the stored `degrade.jsonl` row).
* `T1v`: T0 with each enemy known only at a real enemy read: identity-resolved
  `enemy_track` observations, mapped to the enemy replay subject of the same
  agent (evaluation only), xy from the icon through `entity_state.world_frame`,
  z, yaw and pitch from T0. Consecutive reads at most `ENEMY_GAP_MS` apart
  interpolate; allies at full-rate truth.
* `Lpv` (`Lpv-reach`): T1v with allies read per `Lp0.5-250w5`, the local gate
  opened by any real enemy icon (identity-free) within 20 m of the ally or, for
  a mapped icon, seen by the ally (truth sight); `-reach` drops the sight clause.
* `V15h`: T1v enemies; allies from `entity_state.build_slots(binding="causal")`
  fits at every `ally_icon` frame inside the minimap crop cache's spans, slot to
  subject by agent (`truth_slot_map`, evaluation only), xy from the fit, z, yaw
  and pitch from T0.
* `Vgate`: V15h's fits at Lpv's scheduled times, each snapped to the nearest
  `ally_icon` frame inside the spans by `frame_join.grid_join` (15 Hz declared).
  A scheduled read with no fit is lost and counted with its reason.
* `V15t` / `Vgate-t`: the same with T1 enemies and the truth local gate.

Ally reads interpolate linearly (`gaps = inf`) and hold the last read to the
life's end, as `read_tracks` does; the V arms carry no truth read at a life's
first frame, so each life starts unknown (a NaN sample at its open) until its
first fit. Life and round phases come from T0 in every arm.

Clock: replay-truth-0.4.0 `capture_to_replay` with the killfeed least-squares
fit (`a_ls_ms`, `slope`) from `replay_source.capture_replay_context`, enemies
and teammates at `REMOTE_LAG_MS`, the player at `SELF_LAG_MS`; the layer's
slope-1 clock (`a_ms`) is reported beside it in RR0b as an instrument check.

Stored data only; decodes no video. The `cost` subcommand alone reads the
minimap crop cache (600 crops). The held-out capture (cea8ecbc94ab, replay
bd7efa02) is refused before any row is read. Outputs:
`<store>/analysis/real-reader-schedule-20261007/`. Not wired (`"wire": "no"`).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import coaching_questions as cq  # noqa: E402
from coaching_questions import (ARMS, CutTimeline, Match, _inside, _merge, _true_runs,  # noqa: E402
                                _with_sides, answers, pooled, score)
import entity_state as es  # noqa: E402
import replay_truth as rt  # noqa: E402
from reticle import episodes as ep  # noqa: E402
from reticle.frame_join import grid_join  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "real-reader-schedule-0.1.0"
TASK = "real-reader-schedule-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
HELD_OUT = ("cea8ecbc94ab", "bd7efa02")
SCHED = "Lp0.5-250w5"
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
DRAWN_MS = 1000.0     # Vgate-d: a read moves to the first drawn frame at most this far later
#: Arms run before QA5r2 was registered: their verdicts are post hoc.
POST_HOC = ("Lp", "T1v", "Lpv", "Lpv-reach", "V15h", "Vgate", "Vgate-r", "V15t", "Vgate-t", "Vgate-t-r",
            "Vgate-t-r1")
#: Follow-up (RX rows): a read with no fit retries on following frames this long.
RETRY_MS = 500.0
SCHED1 = "Lp1-250w5"
DIAG_WIN_MS, DIAG_FAR_CM, DIAG_SPAN_MS = 2000.0, 300.0, 4000.0
ORDER = ("Lp", "T1v", "Lpv", "Lpv-reach", "V15h", "Vgate", "Vgate-r", "Vgate-d", "V15t", "Vgate-t",
         "Vgate-t-r", "Vgate-t-r1", "Vgate-t-d")
ENEMY_GAP_MS = 125.0      # bridges consecutive real reads only (15 Hz cache steps 66.7-83.3 ms)
JOIN_HZ = 15.0            # the declared rate of the ally_icon and minimap_object grids
CUE_PX = 30.0             # RR5c: enemy-key pixels on the slab, x widget_scale^2 (fixed in advance)
ALLY_COST = ("coaching_questions", "cost/today", "9acf02f98283", "cv4.ally_icon_ms_per_read")


def refuse(name: str) -> None:
    if str(name).startswith(HELD_OUT):
        raise SystemExit("the held-out match (cea8ecbc94ab / bd7efa02) is never read")


def _log(msg: str) -> None:
    print(msg, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def _norm(o):
    return json.loads(json.dumps(o, default=cq._jd))


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


# ----------------------------------------------------------------- the match

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

    def schedule(self, C, drawn, arm):
        """The owner's schedule; an arm carrying `_cond` (per ally slot, a
        gate condition on the sight grid) takes its windows from that
        condition instead of the truth gate, with the owner's base and
        life-first reads."""
        cond = arm.get("_cond")
        if cond is None:
            return super().schedule(C, drawn, arm)
        reads, base, _w = super().schedule(C, drawn, {"kind": "base", "b": arm["b"],
                                                      "phase": arm.get("phase")})
        win = np.zeros_like(reads)
        lead = float(arm["lead"])
        for s in np.flatnonzero(self.team == C):
            rr = _true_runs(cond[s])
            if not rr:
                continue
            a = np.array([x for x, _ in rr])
            z = np.array([y for _, y in rr])
            St, En = _merge(self.G[a] - lead, self.G[z] + cq.SIGHT_MS)
            w = _inside(self.F, St, En)
            if arm["wr"] < 15:
                keep = np.zeros_like(w)
                every = int(round(15 / arm["wr"]))
                for x, y in _true_runs(w):
                    keep[x:y + 1:every] = True
                w = keep
            win[s] = w
            reads[s] |= self.F_alive[s] & w
        return reads, base, win

    def truth_local(self, drawn) -> dict:
        """The truth local gate per ally slot, as the owner's schedule builds it."""
        cond = {}
        for s in self.ci:
            d = np.hypot(self.X[self.ei] - self.X[s], self.Y[self.ei] - self.Y[s])
            near = np.where(np.isfinite(d), d <= cq.LOCAL_CM, False)
            cond[s] = (drawn[self.ei] & (self.sees[s, self.ei] | near)).any(axis=0)
        return cond

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
        wf, why = es.world_frame(self.cap)
        if wf is None:
            raise SystemExit(f"{self.cap}: world frame refused: {why}")
        _mf, to_m, _mpp = wf
        upm = es.units_per_m()
        ents, obs = {}, []
        stamp = {}
        for r in rt._rows(p_et):
            k = r.get("kind")
            if k == "entity":
                ents[r["id"]] = (r.get("agent"), r.get("identity_status"), r.get("identity_reason"))
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
        track_subj = {}
        for eid, (ag, st, _why) in ents.items():
            if st != "resolved":
                drops["track:identity_abstained"] += 1
                track_subj[eid] = -1
            elif len(foe.get(agent_key(ag), [])) != 1:
                drops["track:agent_not_on_enemy_team"] += 1
                track_subj[eid] = -1
            else:
                track_subj[eid] = foe[agent_key(ag)][0]
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
        o_t, o_x, o_y, o_j = [], [], [], []
        for f, t, x, y, eid, w in obs:
            j = track_subj.get(eid, -1)
            if eid not in ents:
                drops["obs:no_entity"] += 1
                continue
            if j < 0:
                st = ents[eid][1]
                drops["obs:identity_abstained" if st != "resolved" else "obs:agent_not_on_enemy_team"] += 1
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
                "tracks": len(ents), "observations": len(obs)}

    def rr0b(self, E: dict) -> dict:
        """Mapped real icons against their subject's truth xy, on both clocks."""
        out = {}
        for name, clock in (("ls_slope", self.clock), ("layer_slope1", self.clock1)):
            t = self.to_rep(E["obs_t_cap"], rt.REMOTE_LAG_MS, clock)
            smp = self.tl0.sample(t)
            j = E["obs_j"]
            n = np.arange(j.size)
            tx, ty = smp["x"][j, n], smp["y"][j, n]
            d = np.hypot(E["obs_x"] - tx, E["obs_y"] - ty) / 100.0
            ok = np.isfinite(d)
            out[name] = {"mapped_reads": int(j.size), "truth_known": int(ok.sum()),
                         "within_3m": round(float((d[ok] <= 3.0).mean()), 4) if ok.any() else None,
                         "median_m": round(float(np.median(d[ok])), 3) if ok.any() else None,
                         "p90_m": round(float(np.percentile(d[ok], 90)), 3) if ok.any() else None}
        out["clock"] = {"a_ls_ms": self.clock[0], "slope": self.clock[1], "layer_a_ms": self.clock1[0],
                        "remote_lag_ms": rt.REMOTE_LAG_MS, "self_lag_ms": rt.SELF_LAG_MS}
        return out

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

    def real_gate(self, E: dict) -> dict:
        """On the sight grid G: any real icon (global), and per ally the local
        gate (20 m reach, or a mapped icon the ally sees) and reach alone."""
        MO = E["MO"]
        t_fr = self.to_rep(MO["t_ms"], rt.REMOTE_LAG_MS)
        g_cap = self.to_cap(self.G, rt.REMOTE_LAG_MS)
        inG = self.in_spans(g_cap)
        gi = np.flatnonzero(inG)
        inrun, J, _rate = join_runs(self.G[gi], t_fr)
        K = self.G.size
        p_of = np.full(K, -1, np.int64)
        p_of[gi[inrun]] = J.index
        read_frame = np.array([r is None for r in MO["reason"]], bool)
        valid = p_of >= 0
        read_k = np.zeros(K, bool)
        read_k[valid] = read_frame[p_of[valid]]
        ip = E["icon_p"]
        start = np.searchsorted(ip, np.arange(MO["frame_idx"].size + 1))
        n_at = np.zeros(K, np.int64)
        kk = np.flatnonzero(read_k)
        n_at[kk] = start[p_of[kk] + 1] - start[p_of[kk]]
        ks = np.repeat(np.arange(K), n_at)
        first = np.repeat(start[np.clip(p_of, 0, None)], n_at)
        off = np.arange(ks.size) - np.repeat(np.cumsum(n_at) - n_at, n_at)
        ic = first + off
        any_ = n_at > 0
        local, reach = {}, {}
        sub = E["icon_subj"][ic]
        for s in self.ci:
            d = np.hypot(self.X[s, ks] - E["icon_x"][ic], self.Y[s, ks] - E["icon_y"][ic])
            near = np.where(np.isfinite(d), d <= cq.LOCAL_CM, False)
            seen = (sub >= 0) & self.sees[s, np.clip(sub, 0, None), ks]
            a = np.zeros(K, bool)
            np.logical_or.at(a, ks, near)
            reach[s] = a.copy()
            np.logical_or.at(a, ks, seen)
            local[s] = a
        return {"any": any_, "local": local, "reach": reach, "read_k": read_k, "in_spans": inG,
                "join": dict(J.stamp(), outside_minimap_object_runs=int((~inrun).sum()),
                             in_spans=int(gi.size))}

    # ------------------------------------------------------------- vision allies

    def vision_slots(self) -> dict:
        G = es.build_slots(self.cap, binding="causal")
        if "refused" in G:
            return {"refused": G["refused"]}
        tmap, notes = es.truth_slot_map(G["L"]["slots"], [self.agent.get(self.sid[s]) for s in self.ci])
        S = G["S"]
        slot_of = {}
        for s in self.ci:
            k = tmap.get(es._canon(self.agent.get(self.sid[s])))
            slot_of[int(s)] = None if k is None else int(k)
        in_sp = self.in_spans(S.fr_t)
        return {"G": G, "slot_of": slot_of, "notes": notes, "fr_t": S.fr_t, "in_sp": in_sp, "drawn": S.fr_drawn,
                "X": G["bind"]["X"] * es.units_per_m(), "Y": G["bind"]["Y"] * es.units_per_m(),
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

    def vgate_tracks(self, V: dict, reads: np.ndarray, retry_ms: float = 0.0, drawn_ms: float = 0.0
                     ) -> tuple[dict, dict, dict, dict]:
        """V15's fits at a schedule's reads (slot, M.F frame), each snapped to
        the nearest ally_icon frame inside the spans by `grid_join`. With
        `retry_ms`, a read whose frame holds no fit retries on each following
        ally_icon frame inside the spans up to `retry_ms` after the snapped
        frame; every attempt counts as a read (`reads` = attempts), the first
        frame holding a fit is the read. Without it `reads` counts the frames
        read with a fit (the RR rows' rule) and `attempts` stands beside.
        `self._vgate_detail` keeps each slot's scheduled reads for diagnosis."""
        in_idx = np.flatnonzero(V["in_sp"])
        A_t, A_s, A_f = [], [], []
        lost = Counter()
        sched = 0
        for s in self.ci:
            f = np.flatnonzero(reads[s])
            sched += int(f.size)
            if V["slot_of"][int(s)] is None:
                lost["slot_unnamed"] += int(f.size)
                continue
            tc = self.to_cap(self.F[f], self.lag(s))
            m = self.in_spans(tc)
            lost["outside_cache_spans"] += int((~m).sum())
            A_t.append(tc[m])
            A_s.append(np.full(int(m.sum()), s))
            A_f.append(f[m])
        A_t = np.concatenate(A_t) if A_t else np.zeros(0)
        A_s = np.concatenate(A_s) if A_s else np.zeros(0, int)
        A_f = np.concatenate(A_f) if A_f else np.zeros(0, int)
        B = V["fr_t"][in_idx]
        inrun, J, _rate = join_runs(A_t, B)
        lost["outside_ally_icon_runs"] += int((~inrun).sum())
        A_t, A_s, A_f = A_t[inrun], A_s[inrun], A_f[inrun]
        ok = J.index >= 0
        lost["not_joined"] += int((~ok).sum())
        tracks, gaps = {}, {}
        n_reads, frames, attempts = 0, set(), 0
        detail = {}
        if retry_ms <= 0:
            self._vgate_sched = {}
        for s in self.ci:
            sid = self.sid[s]
            k = V["slot_of"][int(s)]
            m = (A_s == s) & ok
            bpos = J.index[m]
            if k is None:
                tracks[sid] = self._track(s, np.zeros(0), np.zeros(0), np.zeros(0))
                gaps[sid] = np.inf
                continue
            got = bpos.copy()
            att = np.ones(bpos.size, np.int64)
            gone = np.zeros(bpos.size, bool)
            if drawn_ms > 0:
                # Vgate-d: a read on a frame whose stored ally_icon row says the widget is not
                # drawn moves to the first later drawn frame within drawn_ms; each frame tried
                # counts as a read
                dr = V["drawn"]
                pend = ~dr[in_idx[bpos]]
                lost["moved_off_undrawn"] += int(pend.sum())
                mm = 1
                while pend.any():
                    nb = bpos + mm
                    nbc = np.clip(nb, 0, B.size - 1)
                    valid = pend & (nb < B.size) & (B[nbc] - B[bpos] <= drawn_ms)
                    if not valid.any():
                        break
                    att += valid
                    hit = valid & dr[in_idx[nbc]]
                    got[hit] = nbc[hit]
                    pend = valid & ~hit
                    mm += 1
                gone = ~dr[in_idx[got]]
                lost["not_drawn_within_1s"] += int(gone.sum())
            h = V["has"][k, in_idx[got]] & ~gone
            if retry_ms > 0:
                pend = ~h
                mm = 1
                while pend.any():
                    nb = bpos + mm
                    inb = nb < B.size
                    nbc = np.clip(nb, 0, B.size - 1)
                    valid = pend & inb & (B[nbc] - B[bpos] <= retry_ms)
                    if not valid.any():
                        break
                    att += valid
                    hit = valid & V["has"][k, in_idx[nbc]]
                    got[hit] = nbc[hit]
                    h |= hit
                    pend = valid & ~hit
                    mm += 1
                lost["retry_recovered"] += int((h & (got != bpos)).sum())
            attempts += int(att.sum())
            f = in_idx[got]
            if retry_ms <= 0:
                self._vgate_sched[int(s)] = f
            lost["read_lost:no_fit"] += int((~h & ~gone).sum())
            detail[int(s)] = {"t_sched": self.F[A_f[m]], "ok": h.copy(), "x": V["X"][k, f], "y": V["Y"][k, f],
                              "t_fit": self.to_rep(V["fr_t"][f], self.lag(s)), "k": int(k),
                              "frame": in_idx[bpos], "b": bpos.copy()}
            f = f[h]
            T = self.to_rep(V["fr_t"][f], self.lag(s))
            al = self.tl0._alive_fn(T)[s] if T.size else np.zeros(0, bool)
            lost["fit_while_truth_dead"] += int((~al).sum())
            f, T = f[al], T[al]
            uf = np.unique(f)
            n_reads += int(uf.size)
            frames.update(uf.tolist())
            detail[int(s)]["t_reads"] = np.unique(T)
            tracks[sid] = self._track(s, T, V["X"][k, f], V["Y"][k, f])
            gaps[sid] = np.inf
        cost = self._cost(attempts if (retry_ms > 0 or drawn_ms > 0) else n_reads, len(frames), lost)
        cost["scheduled"] = sched
        cost["attempts"] = attempts
        cost["frames_with_fit_read"] = n_reads
        cost["retry_ms"] = retry_ms
        cost["drawn_ms"] = drawn_ms
        self._vgate_detail = detail
        return tracks, gaps, cost, J.stamp()


# ----------------------------------------------------------------- flips, onsets

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


def onsets(M: RealMatch, drawn, gates: dict) -> list[dict]:
    """Engagement onsets for the capturing team as `replay_instances` finds
    them, each gate's open state at onset (and 250, 500 ms before) and lead.
    `gates` maps a name to a (K,) global or a per-slot dict of (K,) masks."""
    tl = M.tl0
    rows = ep.read_episodes(tl.match)
    eps = [r for r in rows if r.get("row") == "episode"]
    team_of = {s.slot_id: s.team for s in tl.slots}
    idx = {s.slot_id: k for k, s in enumerate(tl.slots)}
    acts = sorted([x for x in tl.events if x.kind in ("damage", "death") and x.actor in team_of
                   and x.target in team_of and team_of[x.actor] != team_of[x.target]], key=lambda x: x.t_ms)
    act_t = np.array([x.t_ms for x in acts])
    C = M.C
    out = []
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
        on, rn = first.t_ms, e["round"]
        s_c = idx[first.actor] if team_of[first.actor] == C else idx[first.target]
        k = np.searchsorted(M.G, on, side="right") - 1
        rec = {"m": M.cap, "round": rn, "t": on, "slot": int(s_c), "enemy_first": team_of[first.actor] != C,
               "in_spans": bool(k >= 0 and M.in_spans(M.to_cap(np.array([M.G[k]]), rt.REMOTE_LAG_MS))[0])}
        for name, g in gates.items():
            gk = g[s_c] if isinstance(g, dict) else g
            for lag in (0.0, 250.0, 500.0):
                kk = np.searchsorted(M.G, on - lag, side="right") - 1
                rec[f"{name}.open_{int(lag)}"] = bool(kk >= 0 and M.G_round[kk] == rn and gk[kk])
            lead = None
            if rec[f"{name}.open_0"]:
                j = k
                while j > 0 and gk[j - 1] and M.G_round[j - 1] == rn:
                    j -= 1
                lead = float(on - M.G[j])
            rec[f"{name}.lead_ms"] = lead
        out.append(rec)
    return out


# ----------------------------------------------------------------- run

def _answers(M, tracks, gaps, events, name):
    tl = CutTimeline(M.tl0, tracks, gaps, events, name)
    d = M.derive(tl)
    if not hasattr(M, "TL"):
        M.TL = {}
    M.TL[name] = tl
    return answers(d, tl, M.C, M.occ)


def _stored_lp(match: str, team: str) -> dict:
    p = STORE / "analysis" / cq.TASK / "degrade.jsonl"
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r["match"] == match and r["team"] == team and r["arm"] == SCHED:
            return r
    raise SystemExit(f"no stored {SCHED} row for {match} {team}")


def instrument(M: RealMatch) -> dict:
    """RR0a and RR0b for one match; T0, T1 and Lp answers kept on M."""
    t0 = time.time()
    d0 = M.derive(M.tl0)
    M.d0 = d0
    M.events = _with_sides(M.tl0, d0.header["attack_team"])
    M.drawn_C = M.drawn(M.C)
    M.A = {"T0": answers(d0, M.tl0, M.C, M.occ)}
    tr1, gp1 = M.t1_tracks(M.C, M.drawn_C)
    M.A["T1"] = _answers(M, tr1, gp1, M.events, "t1")
    tr, gp, cost = M.read_tracks(M.C, M.drawn_C, ARMS[SCHED])
    M.A["Lp"] = _answers(M, tr, gp, M.events, SCHED)
    M.cost = {"Lp": cost}
    st = _stored_lp(M.tl0.match, M.C)
    mine = {"cost": _norm(cost), "vs_T0": _norm(score(M.A["T0"], M.A["Lp"])),
            "vs_T1": _norm(score(M.A["T1"], M.A["Lp"]))}
    diffs = []
    for k in ("cost", "vs_T0", "vs_T1"):
        a, b = mine[k], st[k]
        if k == "cost":
            for x in b:
                if not np.isclose(a.get(x, np.nan), b[x], rtol=0, atol=1e-9):
                    diffs.append(f"cost.{x}: {a.get(x)} vs stored {b[x]}")
        elif a != b:
            for q in b:
                if a.get(q) != b[q]:
                    diffs.append(f"{k}.{q}: {a.get(q)} vs stored {b[q]}")
    # the schedule hook, fed the truth gate, must rebuild the owner's reads
    r_owner = M.schedule(M.C, M.drawn_C, ARMS[SCHED])[0]
    r_hook = M.schedule(M.C, M.drawn_C, dict(ARMS[SCHED], _cond=M.truth_local(M.drawn_C)))[0]
    out = {"session": M.cap, "match": M.tl0.match, "team": M.C,
           "rr0a": {"equal": not diffs, "diffs": diffs, "share": cost["share"], "stored_share": st["cost"]["share"],
                    "counts_compared": {k: mine[k] for k in ("vs_T0", "vs_T1")},
                    "hook_reproduces_owner_schedule": bool((r_owner == r_hook).all())},
           "drawn_share_of_live_grid_T1": float(M.drawn_C[M.ei].any(axis=0).mean())}
    E = M.enemy_reads()
    M.E = E
    if E is not None:
        out["rr0b"] = M.rr0b(E)
        out["enemy_drops"] = E["drops"]
        out["enemy_track"] = {"tracks": E["tracks"], "observations": E["observations"],
                              "mapped_reads": int(E["obs_j"].size), "stamp": E["stamp"]}
    else:
        out["rr0b"] = {"refused": "no stored minimap_object or enemy_track"}
    _log(f"{M.cap} instrument in {time.time() - t0:.0f} s: RR0a equal {not diffs} share {cost['share']:.4f}; "
         f"RR0b {json.dumps(out['rr0b'].get('ls_slope', out['rr0b']))}")
    return out


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


def arms(M: RealMatch) -> tuple[list[dict], dict]:
    t0 = time.time()
    rows = [_arm_row(M, "Lp", M.cost["Lp"])]
    info = {"session": M.cap}
    E = M.E
    V = M.vision_slots()
    if "refused" in V:
        raise SystemExit(f"{M.cap}: build_slots refused: {V['refused']} (read the stored reason)")
    info["slots"] = {"slot_of": {M.sid[s]: k for s, k in V["slot_of"].items()}, "notes": V["notes"],
                     "build_cost": V["cost"], "in_spans_frames": int(V["in_sp"].sum()),
                     "frames": int(V["fr_t"].size),
                     "fit_share_in_spans": round(float(V["has"][:, V["in_sp"]].mean()), 4)}
    # ally_icon frames inside the spans onto minimap_object frames (the declared join)
    if E is not None:
        Jx = grid_join(V["fr_t"][V["in_sp"]], E["MO"]["t_ms"], JOIN_HZ)
        info["join_ally_icon_to_minimap_object"] = Jx.stamp()
    tr1, gp1 = M.t1_tracks(M.C, M.drawn_C)
    trV, gpV, costV = M.v15_tracks(V)
    # truth-gate vision arms
    M.A["V15t"] = _answers(M, {**tr1, **trV}, {**gp1, **gpV}, M.events, "V15t")
    rows.append(_arm_row(M, "V15t", costV))
    reads_lp = M.schedule(M.C, M.drawn_C, ARMS[SCHED])[0]
    trG, gpG, costG, jst = M.vgate_tracks(V, reads_lp)
    M.A["Vgate-t"] = _answers(M, {**tr1, **trG}, {**gp1, **gpG}, M.events, "Vgate-t")
    rows.append(_arm_row(M, "Vgate-t", costG, {"join": jst, "read_ratio_vs_ref": costG["reads"] / costV["reads"]}))
    _log(f"  {M.cap} V15t share {costV['share']:.4f}; Vgate-t share {costG['share']:.4f} "
         f"ratio {costG['reads'] / costV['reads']:.4f} lost {costG['lost']}")
    det_t = M._vgate_detail
    M._lost_rows = lost_reads(M, V, det_t)["rows"]
    _r, _b, win_lp = M.schedule(M.C, M.drawn_C, ARMS[SCHED])
    info["rx8"] = {"Lp": spacing_windows(M, "Lp", "T1", win_lp),
                   "Vgate-t": spacing_windows(M, "Vgate-t", "V15t", win_lp)}
    info["diag"] = {"Vgate-t": diagnose(M, "Vgate-t", "V15t", det_t),
                    "spacing_V15t_vs_T1": spacing_diag(M, "V15t", "T1")}
    trD, gpD, costD, jD = M.vgate_tracks(V, reads_lp, drawn_ms=DRAWN_MS)
    M.A["Vgate-t-d"] = _answers(M, {**tr1, **trD}, {**gp1, **gpD}, M.events, "Vgate-t-d")
    rows.append(_arm_row(M, "Vgate-t-d", costD, {"join": jD, "read_ratio_vs_ref": costD["reads"] / costV["reads"]}))
    _log(f"  {M.cap} Vgate-t-d share {costD['share']:.4f} lost {costD['lost']}")
    for name, sched in (("Vgate-t-r", SCHED), ("Vgate-t-r1", SCHED1)):
        rd = M.schedule(M.C, M.drawn_C, ARMS[sched])[0]
        trR, gpR, costR, jR = M.vgate_tracks(V, rd, retry_ms=RETRY_MS)
        M.A[name] = _answers(M, {**tr1, **trR}, {**gp1, **gpR}, M.events, name)
        rows.append(_arm_row(M, name, costR, {"join": jR, "read_ratio_vs_ref": costR["reads"] / costV["reads"],
                                              "schedule": sched}))
        info["diag"][name] = diagnose(M, name, "V15t", M._vgate_detail)
        _log(f"  {M.cap} {name} share {costR['share']:.4f} ratio {costR['reads'] / costV['reads']:.4f} "
             f"lost {costR['lost']}")
    if E is None:
        info["real_enemy_arms"] = "not run: no stored minimap_object or enemy_track"
        return rows, info
    trE, gpE, cntE = M.t1v_tracks(E)
    info["t1v"] = cntE
    M.A["T1v"] = _answers(M, trE, gpE, M.events, "T1v")
    rows.append(_arm_row(M, "T1v", {"share": 1.0, **cntE}))
    RG = M.real_gate(E)
    M.RG = RG
    info["real_gate_join"] = RG["join"]
    enemies = {M.sid[j]: trE[M.sid[j]] for j in M.ei}
    egaps = {M.sid[j]: gpE[M.sid[j]] for j in M.ei}
    for name, cond in (("Lpv", RG["local"]), ("Lpv-reach", RG["reach"])):
        arm = dict(ARMS[SCHED], _cond=cond)
        tr, gp, cost = M.read_tracks(M.C, M.drawn_C, arm)
        tr.update(enemies)
        gp.update(egaps)
        M.A[name] = _answers(M, tr, gp, M.events, name)
        rows.append(_arm_row(M, name, cost))
        _log(f"  {M.cap} {name} share {cost['share']:.4f}")
    M.A["V15h"] = _answers(M, {**trV, **enemies}, {**gpV, **egaps}, M.events, "V15h")
    rows.append(_arm_row(M, "V15h", costV))
    reads_lpv = M.schedule(M.C, M.drawn_C, dict(ARMS[SCHED], _cond=RG["local"]))[0]
    M.reads_lpv = reads_lpv
    trG, gpG, costG, jst = M.vgate_tracks(V, reads_lpv)
    M.A["Vgate"] = _answers(M, {**trG, **enemies}, {**gpG, **egaps}, M.events, "Vgate")
    rows.append(_arm_row(M, "Vgate", costG, {"join": jst, "read_ratio_vs_ref": costG["reads"] / costV["reads"]}))
    _log(f"  {M.cap} Vgate share {costG['share']:.4f} ratio {costG['reads'] / costV['reads']:.4f} "
         f"lost {costG['lost']}")
    info["diag"]["Vgate"] = diagnose(M, "Vgate", "V15h", M._vgate_detail)
    info["diag"]["spacing_V15h_vs_T1v"] = spacing_diag(M, "V15h", "T1v")
    trD, gpD, costD, jD = M.vgate_tracks(V, reads_lpv, drawn_ms=DRAWN_MS)
    M.A["Vgate-d"] = _answers(M, {**trD, **enemies}, {**gpD, **egaps}, M.events, "Vgate-d")
    rows.append(_arm_row(M, "Vgate-d", costD, {"join": jD, "read_ratio_vs_ref": costD["reads"] / costV["reads"]}))
    _log(f"  {M.cap} Vgate-d share {costD['share']:.4f} lost {costD['lost']}")
    trR, gpR, costR, jR = M.vgate_tracks(V, reads_lpv, retry_ms=RETRY_MS)
    M.A["Vgate-r"] = _answers(M, {**trR, **enemies}, {**gpR, **egaps}, M.events, "Vgate-r")
    rows.append(_arm_row(M, "Vgate-r", costR, {"join": jR, "read_ratio_vs_ref": costR["reads"] / costV["reads"]}))
    info["diag"]["Vgate-r"] = diagnose(M, "Vgate-r", "V15h", M._vgate_detail)
    _log(f"  {M.cap} Vgate-r share {costR['share']:.4f} ratio {costR['reads'] / costV['reads']:.4f} "
         f"lost {costR['lost']}")
    # RR1a: live-phase grid share with a real icon, against T1's drawn share
    live = np.zeros(M.G.size, bool)
    for r in M.rounds:
        if r["t_live"] is not None:
            hi = r["t_end"] if r["t_end"] is not None else r["t_next"]
            live |= (M.G_round == r["round"]) & (M.G >= r["t_live"]) & (M.G <= hi)
    t1d = M.drawn_C[M.ei].any(axis=0)
    info["rr1a"] = {"live_samples": int(live.sum()), "real_share_live": float(RG["any"][live].mean()),
                    "t1_share_live": float(t1d[live].mean()),
                    "ratio_live": float(RG["any"][live].mean() / t1d[live].mean()),
                    "real_share_all_grid": float(RG["any"].mean()), "t1_share_all_grid": float(t1d.mean()),
                    "live_in_spans": float(RG["in_spans"][live].mean()),
                    "live_read_frames": float(RG["read_k"][live].mean())}
    # onsets
    gates = {"truth_global": t1d, "truth_local": M.truth_local(M.drawn_C), "real_global": RG["any"],
             "real_local": RG["local"], "real_reach": RG["reach"]}
    info["onsets"] = onsets(M, M.drawn_C, gates)
    info["rr6"] = rr6(M, V)
    _log(f"  {M.cap} arms in {time.time() - t0:.0f} s")
    M.V = V
    return rows, info



# ----------------------------------------------------------------- diagnosis (RX1)

def _instances(M: RealMatch, q: str, keys, src: str = "T0") -> list[tuple]:
    """(key, time, involved ally slots) per instance of q: contacts from
    `src`'s items, first-sight support at T0's first sighting of the round
    (a round T0 lacks is skipped)."""
    team_of = {sl.slot_id: sl.team for sl in M.tl0.slots}
    idx = {sl.slot_id: k for k, sl in enumerate(M.tl0.slots)}
    out = []
    if q == "contact_C":
        items = M.A[src]["contact_C"]
        for i in keys:
            it = items[i]
            mates = [idx[x] for x in it["k"] if team_of.get(x) == M.C]
            out.append((i, float(it["s"]), mates))
    elif q == "first_sight_support":
        first = {}
        for c in M.d0.contacts:
            fs = c.get("first_seer")
            seer = None
            if fs == "both":
                seer = c["a"] if team_of.get(c["a"]) == M.C else c["b"]
            elif fs is not None and team_of.get(fs) == M.C:
                seer = fs
            if seer is None:
                continue
            r = c["round"]
            if r not in first or c["t_start_ms"] < first[r][0]:
                first[r] = (c["t_start_ms"], seer)
        for r in keys:
            if r not in first:
                continue
            t = float(first[r][0])
            al = M.tl0._alive_fn(np.array([t]))[:, 0]
            out.append((r, t, [int(x) for x in M.ci if al[x]]))
    return out


def diagnose(M: RealMatch, arm: str, ref: str, detail: dict) -> dict:
    """Each instance broken by `arm` against `ref` (judged on T0) in
    first_sight_support and contact_C, by cause, first that holds: a lost
    scheduled read of an involved ally within 2 s before (`lost_read`); a
    scheduled fit there more than 3 m from the ally's `ref` position at the
    scheduled time (`far_fit`); the arm's reads of an involved ally bracketing
    the instance more than 4 s apart (`long_span`); `other`. Non-exclusive
    counts and the arm-against-ref position gap at the instance stand beside."""
    out = {}
    T0 = M.A["T0"]
    for mode, q in [(m_, q_) for m_ in ("vs_T0_flips", "vs_ref_disagree")
                    for q_ in ("first_sight_support", "contact_C")]:
        if mode == "vs_T0_flips":
            broken = _ok_set(T0, M.A[ref], q) - _ok_set(T0, M.A[arm], q)
            inst = _instances(M, q, sorted(broken, key=str))
        else:
            R_ = M.A[ref][q]
            keys = range(len(R_)) if q in cq.EPISODIC else R_.keys()
            broken = set(keys) - _ok_set(M.A[ref], M.A[arm], q)
            inst = _instances(M, q, sorted(broken, key=str), src=ref)
        cls, flags = Counter(), Counter()
        for _key, t, mates in inst:
            f = {"lost_read": False, "far_fit": False, "long_span": False, "pos_gap_3m_at_instance": False}
            smp_a = M.TL[arm].sample(np.array([t]))
            smp_r = M.TL[ref].sample(np.array([t]))
            for sl in mates:
                d = detail.get(int(sl))
                if d is None:
                    continue
                w = (d["t_sched"] >= t - DIAG_WIN_MS) & (d["t_sched"] <= t)
                f["lost_read"] |= bool((w & ~d["ok"]).any())
                wf = w & d["ok"]
                if wf.any():
                    rs = M.TL[ref].sample(d["t_sched"][wf])
                    dd = np.hypot(d["x"][wf] - rs["x"][sl], d["y"][wf] - rs["y"][sl])
                    f["far_fit"] |= bool(np.any(np.where(np.isfinite(dd), dd > DIAG_FAR_CM, False)))
                tr = d.get("t_reads", np.zeros(0))
                lives = [(a, e) for a, e in M.lives[M.sid[sl]] if a <= t < e]
                a, e = lives[0] if lives else (t, t)
                pr = tr[(tr <= t) & (tr >= a)]
                nx = tr[(tr > t) & (tr < e)]
                lo = pr.max() if pr.size else a
                hi = nx.min() if nx.size else e
                f["long_span"] |= bool(hi - lo > DIAG_SPAN_MS)
                g = np.hypot(smp_a["x"][sl, 0] - smp_r["x"][sl, 0], smp_a["y"][sl, 0] - smp_r["y"][sl, 0])
                f["pos_gap_3m_at_instance"] |= bool(not np.isfinite(g) or g > DIAG_FAR_CM)
            for k, v in f.items():
                flags[k] += int(v)
            c = next((k for k in ("lost_read", "far_fit", "long_span") if f[k]), "other")
            cls[c] += 1
        out.setdefault(mode, {})[q] = {"broken": len(inst), "cause": dict(cls), "any_flag": dict(flags)}
    return out


def spacing_diag(M: RealMatch, arm: str, ref: str) -> dict:
    """The 15 Hz arm's spacing_5m disagreements with `ref`: whether a fit is
    missing (an involved ally's last V15 read more than 1 s old at the death,
    or none in the life) or far (every involved ally read within 1 s, one
    more than 3 m from T0). Involved: the victim and every living teammate."""
    bad = set(M.A[ref]["spacing_death"]) - _ok_set(M.A[ref], M.A[arm], "spacing_5m")
    ev = {e.event_id: e for e in M.tl0.events if e.kind == "death"}
    idx = {sl.slot_id: k for k, sl in enumerate(M.tl0.slots)}
    cls = Counter()
    for k in bad:
        e = ev[k]
        t = float(e.t_ms) - 1.0
        al = M.tl0._alive_fn(np.array([t]))[:, 0]
        inv = [idx[e.target]] + [int(x) for x in M.ci if al[x] and x != idx[e.target]]
        miss = far = False
        sa, s0 = M.TL[arm].sample(np.array([t])), M.tl0.sample(np.array([t]))
        for sl in inv:
            T = M._v15_reads.get(int(sl), np.zeros(0))
            pr = T[T <= t]
            if not pr.size or t - pr.max() > 1000.0:
                miss = True
            g = np.hypot(sa["x"][sl, 0] - s0["x"][sl, 0], sa["y"][sl, 0] - s0["y"][sl, 0])
            if not np.isfinite(g) or g > DIAG_FAR_CM:
                far = True
        cls["missing_fit" if miss else ("far_fit" if far else "other")] += 1
        cls["far_fit_any"] += int(far)
    return {"disagree": len(bad), "n": len(M.A[ref]["spacing_death"]), **dict(cls)}


def spacing_windows(M: RealMatch, arm: str, ref: str, win: np.ndarray) -> dict:
    """RX8: for each spacing_death instance (T1's keys), whether the nearest
    living teammate at the death in T1 had a gate-window frame (`win`, the
    schedule's 5 Hz window frames) within 1 s before it; split by whether
    `arm` broke the instance against `ref` (both judged against T1)."""
    T1 = M.A["T1"]
    sd = T1["spacing_death"]
    ref_ok, arm_ok = _ok_set(T1, M.A[ref], "spacing_death"), _ok_set(T1, M.A[arm], "spacing_death")
    ev = {e.event_id: e for e in M.tl0.events if e.kind == "death"}
    idx = {sl.slot_id: k for k, sl in enumerate(M.tl0.slots)}
    tl1 = M.TL["t1"]
    out = {"broken": {"n": 0, "outside": 0}, "unbroken": {"n": 0, "outside": 0},
           "both_right": {"n": 0, "outside": 0}, "no_teammate": 0}
    for k in sd:
        e = ev.get(k)
        if e is None:
            continue
        t = float(e.t_ms) - 1.0
        smp = tl1.sample(np.array([t]))
        v = idx[e.target]
        best, bs = np.inf, None
        for s_ in M.ci:
            if s_ == v or not smp["alive"][s_, 0]:
                continue
            d = np.hypot(smp["x"][s_, 0] - smp["x"][v, 0], smp["y"][s_, 0] - smp["y"][v, 0])
            if np.isfinite(d) and d < best:
                best, bs = d, int(s_)
        if bs is None:
            out["no_teammate"] += 1
            continue
        fr = (M.F >= t - 1000.0) & (M.F <= t)
        outside = not bool(win[bs][fr].any())
        broken = k in ref_ok and k not in arm_ok
        key = "broken" if broken else "unbroken"
        out[key]["n"] += 1
        out[key]["outside"] += int(outside)
        if k in ref_ok and k in arm_ok:
            out["both_right"]["n"] += 1
            out["both_right"]["outside"] += int(outside)
    return out


def rr6(M: RealMatch, V: dict) -> dict:
    """causal_bind rerun on Vgate's scheduled frames alone, against the dense binding."""
    import math
    import entity_binding as eb
    G = V["G"]
    fits, life = G["fits"], G["life"]
    sched = getattr(M, "_vgate_sched", {})
    if not sched:
        return {"not_run": "no Vgate schedule"}
    sel = np.unique(np.concatenate([f for f in sched.values()]))
    sel = sel[sel >= 0]
    F = V["fr_t"].size
    start = fits["start"]
    # the fits of the selected frames, re-indexed (flat arrays in frame order)
    take = np.concatenate([np.arange(start[f], start[f + 1]) for f in sel]) if sel.size else np.zeros(0, int)
    n = fits["x"].size
    sub = {}
    for k, v in fits.items():
        if isinstance(v, np.ndarray) and v.shape[:1] == (n,):
            sub[k] = v[take]
        elif k == "flags":
            sub[k] = {r: a[take] for r, a in v.items()}
        else:
            sub[k] = v
    newpos = np.full(F, -1, np.int64)
    newpos[sel] = np.arange(sel.size)
    sub["fpos"] = newpos[fits["fpos"][take]]
    sub["start"] = np.searchsorted(sub["fpos"], np.arange(sel.size + 1))
    p = G["params"]
    S = G["S"]
    m_per_px = G["m_per_px"]
    bind = eb.causal_bind(V["fr_t"][sel], sub, life["open"][:, sel], life["seg_start"][sel],
                          G["L"]["player_slot"], G["spect"]["slot"][sel], r_fit=p["r_fit_m"],
                          v_max=p["v_max_m_s"], log_area=math.log(fits["map_px"] * m_per_px ** 2),
                          r_dup_m=2.0 * p["r_icon_m"], margin_min=fits["margin_min"])
    dense = G["bind"]["bound_to"][take]
    sparse = bind["bound_to"]
    both = dense >= 0
    same = float((sparse[both] == dense[both]).mean()) if both.any() else None
    # scheduled reads with a bound fit, dense against sparse
    has_d, has_s, tot = 0, 0, 0
    for s, f in sched.items():
        k = V["slot_of"][s]
        if k is None:
            continue
        tot += f.size
        has_d += int(G["bind"]["has"][k, f].sum())
        has_s += int(bind["has"][k, newpos[f]].sum())
    _ = S
    return {"frames": int(sel.size), "fits": int(take.size), "dense_bound": int(both.sum()),
            "same_slot_share": None if same is None else round(same, 4),
            "sched_reads": int(tot), "dense_has_share": round(has_d / tot, 4) if tot else None,
            "sparse_has_share": round(has_s / tot, 4) if tot else None,
            "drop": round((has_d - has_s) / tot, 4) if tot else None,
            "rule": "fits of Vgate's scheduled ally_icon frames only, re-indexed; seg_start and spect subset"}


def gate_png(M: RealMatch, path: Path) -> dict:
    """One round's gate windows for one ally slot, truth against real,
    drawn with OpenCV (display code: nearest, no resampling of data)."""
    import cv2
    ons = [o for o in M._onsets if o["m"] == M.cap]
    (rn, s), _n = Counter((o["round"], o["slot"]) for o in ons).most_common(1)[0]
    k = np.flatnonzero(M.G_round == rn)
    t0 = M.G[k[0]]
    fs = np.flatnonzero(M.F_round == rn)
    lp = M.schedule(M.C, M.drawn_C, ARMS[SCHED])[0][s, fs]
    lv = M.reads_lpv[s, fs]
    bands = [("truth global (drawn)", M.drawn_C[M.ei].any(axis=0)[k], (127, 127, 127)),
             ("real global (any icon)", M.RG["any"][k], (34, 189, 188)),
             ("truth local", M.truth_local(M.drawn_C)[s][k], (180, 119, 31)),
             ("real local", M.RG["local"][s][k], (40, 39, 214)),
             ("real reach only", M.RG["reach"][s][k], (150, 152, 255))]
    span = max(float(M.G[k[-1]] - t0), 1.0)
    W, L0, H = 1500, 230, 34
    img = np.full((H * 8 + 40, W, 3), 255, np.uint8)
    xs = lambda t: (L0 + (np.asarray(t, float) - t0) / span * (W - L0 - 10)).astype(int)  # noqa: E731
    gx = xs(M.G[k])
    for i, (lab, m, c) in enumerate(bands):
        y = 10 + i * H
        cv2.putText(img, lab, (5, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        for a_, z_ in _true_runs(m):
            cv2.rectangle(img, (int(gx[a_]), y + 4), (int(gx[z_]) + 1, y + H - 4), c, -1)
    for i, (lab, m, c) in enumerate((("Lp reads (truth gate)", lp, (180, 119, 31)),
                                     ("Lpv reads (real gate)", lv, (40, 39, 214)))):
        y = 10 + (5 + i) * H
        cv2.putText(img, lab, (5, y + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        for x in xs(M.F[fs][m]):
            cv2.line(img, (int(x), y + 4), (int(x), y + H - 4), c, 1)
    for o in ons:
        if o["round"] == rn:
            x = int(xs(o["t"]))
            cv2.line(img, (x, 5), (x, 10 + 7 * H), (0, 0, 0), 1)
    y = 10 + 7 * H + 20
    for sec in range(0, int(span / 1000) + 1, 10):
        x = int(xs(t0 + sec * 1000.0))
        cv2.line(img, (x, y - 14), (x, y - 8), (0, 0, 0), 1)
        cv2.putText(img, f"{sec}s", (x - 8, y + 6), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(img, f"{M.cap} round {rn}, ally slot {M.agent.get(M.sid[s])}; black lines: engagement onsets; "
                     "x: seconds from buy end (replay clock)", (L0, y + 24 - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.imwrite(str(path), img)
    return {"path": str(path), "round": int(rn), "slot": M.sid[s], "agent": M.agent.get(M.sid[s]),
            "rule": "the (round, ally) with the most capturing-team engagement onsets"}


def run_matches(sessions: list[str]) -> int:
    for s in sessions:
        refuse(s)
    OUT.mkdir(parents=True, exist_ok=True)
    Ms = [RealMatch(s) for s in sessions]
    inst = []
    for M in Ms:
        r = instrument(M)
        inst.append(r)
        (OUT / "instrument.json").write_text(json.dumps(inst, indent=1, default=cq._jd), encoding="utf-8")
        if not r["rr0a"]["equal"] or not r["rr0a"]["hook_reproduces_owner_schedule"]:
            _log(f"STOP: RR0a differs on {M.cap}: {r['rr0a']['diffs']}")
            return 2
    for r in inst:
        b = r["rr0b"].get("ls_slope")
        if b and not (b["within_3m"] >= 0.85 and b["median_m"] <= 1.5):
            _log(f"STOP: RR0b out of bounds on {r['session']}: {b}")
            return 3
    rows, infos = [], []
    (OUT / "lost_reads.jsonl").write_text("", encoding="utf-8")
    for M in Ms:
        rw, info = arms(M)
        rows += rw
        infos.append(info)
        with (OUT / "lost_reads.jsonl").open("a", encoding="utf-8") as f:
            for x in getattr(M, "_lost_rows", []):
                f.write(json.dumps(x, default=cq._jd) + "\n")
        M._onsets = info.get("onsets", [])
        with (OUT / "rows.jsonl").open("w", encoding="utf-8") as f:
            for x in rows:
                f.write(json.dumps(x, default=cq._jd) + "\n")
        (OUT / "info.json").write_text(json.dumps(infos, indent=1, default=cq._jd), encoding="utf-8")
    pick = next((M for M in Ms if M.cap == "c817691bcd15" and getattr(M, "E", None) is not None), None)
    if pick is not None:
        png = gate_png(pick, OUT / f"gate_windows_{pick.cap}.png")
        infos.append({"png": png})
        (OUT / "info.json").write_text(json.dumps(infos, indent=1, default=cq._jd), encoding="utf-8")
        _log(f"PNG: {png}")
    return 0


# ----------------------------------------------------------------- report

def _pool(rows: list[dict]) -> dict:
    from reticle.metrics import wilson
    P = pooled(rows)
    out = {}
    by = defaultdict(list)
    for r in rows:
        by[r["arm"]].append(r)
    for arm, rs in by.items():
        o = {"perspectives": len(rs), "sessions": sorted(r["session"] for r in rs),
             "share": P[arm]["share"], "frame_share": P[arm]["frame_share"], "ref": REF[arm]}
        reads = sum(r["cost"].get("reads", 0) for r in rs)
        o["reads"] = reads
        lost = Counter()
        for r in rs:
            lost.update(r["cost"].get("lost") or {})
        o["lost"] = dict(lost)
        for ref in ("vs_ref", "vs_T1", "vs_T0"):
            o[ref] = {}
            for q in SIGHT_QS:
                a, k, n = cq._agree(rs, q, ref)
                if a is None:
                    continue
                o[ref][q] = {"agree": round(a, 4), "k": k, "n": n, "ci": [round(x, 4) for x in wilson(k, n)]}
        fl = {}
        for q in SIGHT_QS:
            b = sum(r["flips"][q]["broken"] for r in rs)
            f = sum(r["flips"][q]["fixed"] for r in rs)
            fl[q] = {"broken": b, "fixed": f, "n": sum(r["flips"][q]["n"] for r in rs)}
        o["flips_vs_T0"] = fl
        out[arm] = o
    for arm, o in out.items():
        ref = o["ref"]
        if ref in out and out[ref].get("reads"):
            o["read_ratio_vs_ref"] = o["reads"] / out[ref]["reads"]
    return out


def _onset_pool(ons: list[dict]) -> dict:
    out = {"n": len(ons), "in_spans": round(float(np.mean([o["in_spans"] for o in ons])), 4) if ons else None}
    names = sorted({k.split(".")[0] for o in ons for k in o if "." in k})
    for g in names:
        d = {}
        for lag in (0, 250, 500):
            d[f"open_{lag}"] = round(float(np.mean([o[f"{g}.open_{lag}"] for o in ons])), 4)
        L = np.array([o[f"{g}.lead_ms"] for o in ons if o[f"{g}.lead_ms"] is not None], float)
        if L.size:
            d.update({f"lead_p{p}": round(float(np.percentile(L, p)), 1) for p in (10, 25, 50, 75, 90)})
        out[g] = d
    return out


def _merge_counts(acc: dict, d: dict) -> None:
    """Add nested count dicts into `acc`, in place."""
    for k, v in d.items():
        if isinstance(v, dict):
            _merge_counts(acc.setdefault(k, {}), v)
        elif isinstance(v, (int, float)) and not isinstance(v, bool):
            acc[k] = acc.get(k, 0) + v


def report(record: bool = False) -> int:
    rows = [json.loads(s) for s in (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    infos = json.loads((OUT / "info.json").read_text(encoding="utf-8"))
    inst = json.loads((OUT / "instrument.json").read_text(encoding="utf-8"))
    sessions = sorted({r["session"] for r in rows})
    pools = {"dev2": [r for r in rows if r["session"] in JUDGED], "dev3": rows}
    for s in sessions:
        pools[s] = [r for r in rows if r["session"] == s]
    summary = {"version": VERSION, "pools": {k: _pool(v) for k, v in pools.items()}}
    ons = {i["session"]: i["onsets"] for i in infos if "onsets" in i}
    summary["onsets"] = {"dev2": _onset_pool([o for s in JUDGED for o in ons.get(s, [])]),
                         "dev3": _onset_pool([o for v in ons.values() for o in v])}
    for s, v in ons.items():
        summary["onsets"][s] = _onset_pool(v)
    summary["rr1a"] = {i["session"]: i["rr1a"] for i in infos if "rr1a" in i}
    summary["rr6"] = {i["session"]: i["rr6"] for i in infos if "rr6" in i}
    summary["rx8"] = {}
    for pname, sess in (("dev2", JUDGED), ("dev3", tuple(i["session"] for i in infos if "rx8" in i))):
        agg = {}
        for i in infos:
            if i.get("session") in sess and "rx8" in i:
                _merge_counts(agg, i["rx8"])
        summary["rx8"][pname] = agg
    print("rx8:", json.dumps(summary["rx8"]))
    summary["diag"] = {}
    for pname, sess in (("dev2", JUDGED), ("dev3", tuple(i["session"] for i in infos if "diag" in i))):
        agg = {}
        for i in infos:
            if i.get("session") not in sess or "diag" not in i:
                continue
            _merge_counts(agg, i["diag"])
        summary["diag"][pname] = agg
    print("diag:", json.dumps(summary["diag"], indent=1, default=dict))
    lp = OUT / "lost_reads.jsonl"
    if lp.is_file():
        LR = [json.loads(x) for x in lp.read_text(encoding="utf-8").splitlines() if x.strip()]
        summary["lost_reads"] = {"dev2": lost_table([r for r in LR if r["m"] in JUDGED]), "dev3": lost_table(LR)}
        print("lost_reads:", json.dumps(summary["lost_reads"], indent=1))
    summary["instrument"] = inst
    for name, P in summary["pools"].items():
        print(f"\n== pool {name}")
        print("arm".ljust(10) + "ref".ljust(6) + "share   fshare  ratio  " + " ".join(q[:11].rjust(17) for q in SIGHT_QS))
        for arm in ORDER:
            if arm not in P:
                continue
            o = P[arm]
            cells = []
            for q in SIGHT_QS:
                v = o["vs_ref"].get(q)
                f = o["flips_vs_T0"][q]
                cells.append(f"{v['agree']:.3f} {v['k']}/{v['n']} -{f['broken']}+{f['fixed']}".rjust(17) if v else "-".rjust(17))
            rr = o.get("read_ratio_vs_ref")
            print(arm.ljust(10) + o["ref"].ljust(6) + f"{o['share']:.4f} {o['frame_share']:.4f} "
                  + (f"{rr:.4f}" if rr is not None else "   -  ") + " " + " ".join(cells))
    print("\nonsets:", json.dumps(summary["onsets"], indent=1))
    print("rr1a:", json.dumps(summary["rr1a"], indent=1))
    print("rr6:", json.dumps(summary["rr6"], indent=1))
    (OUT / "pooled.json").write_text(json.dumps(summary, indent=1, default=cq._jd), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        deps = {"version": VERSION, "episodes": ep.EPISODES_VERSION, "schedule": SCHED,
                "replay_truth": rt.REPLAY_TRUTH_VERSION}
        for pname, P in summary["pools"].items():
            for arm, o in P.items():
                vals = {"share": round(o["share"], 4), "frame_share": round(o["frame_share"], 4),
                        "reads": o["reads"]}
                if o.get("read_ratio_vs_ref") is not None:
                    vals["read_ratio_vs_ref"] = round(o["read_ratio_vs_ref"], 4)
                for ref in ("vs_ref", "vs_T1", "vs_T0"):
                    for q, v in o[ref].items():
                        vals[f"{ref}.{q}"] = v["agree"]
                        vals[f"{ref}.{q}.k"] = v["k"]
                        vals[f"{ref}.{q}.n"] = v["n"]
                for q, f in o["flips_vs_T0"].items():
                    vals[f"flips.{q}.broken"] = f["broken"]
                    vals[f"flips.{q}.fixed"] = f["fixed"]
                for k, v in o["lost"].items():
                    vals[f"lost.{k}"] = v
                rec("real_reader_schedule", part=f"degrade/{arm}", session=pname, values=vals,
                    deps=deps, context={"task": TASK, "ref": o["ref"], "sessions": o["sessions"]})
        for pname, d in summary["onsets"].items():
            vals = {"n": d["n"]}
            for g, v in d.items():
                if isinstance(v, dict):
                    vals.update({f"{g}.{k}": x for k, x in v.items()})
            rec("real_reader_schedule", part="onset", session=pname, values=vals, deps=deps,
                context={"task": TASK})
        for s, v in summary["rr1a"].items():
            rec("real_reader_schedule", part="rr1a", session=s, values={k: round(x, 4) if isinstance(x, float) else x
                                                                         for k, x in v.items()},
                deps=deps, context={"task": TASK})
        for s, v in summary["rr6"].items():
            rec("real_reader_schedule", part="rr6", session=s,
                values={k: x for k, x in v.items() if isinstance(x, (int, float)) and x is not None},
                deps=deps, context={"task": TASK})
        for r in inst:
            vals = {"rr0a_equal": r["rr0a"]["equal"], "lp_share": round(r["rr0a"]["share"], 4)}
            for c in ("ls_slope", "layer_slope1"):
                for k, v in (r["rr0b"].get(c) or {}).items():
                    vals[f"rr0b.{c}.{k}"] = v
            rec("real_reader_schedule", part="rr0", session=r["session"], values=vals, deps=deps,
                context={"task": TASK, "match": r["match"], "team": r["team"]})
    return 0


# ----------------------------------------------------------------- cost


def _cue_times(sid: str, n_crops: int) -> tuple[dict, list]:
    """The minimap object context and n consecutive live-phase cache times,
    from the second round's buy end (the RR5 sample)."""
    from reticle import minimap_objects as mo
    from reticle.replay_source import capture_replay_context, replay_entry
    from reticle.store import Store
    refuse(sid)
    ctxr = capture_replay_context(sid, None, STORE)
    al = ctxr["out"]["align"]
    a, b = float(al["a_ls_ms"]), float(al["slope"])
    key = Path(replay_entry(sid, STORE)["file"]).stem
    refuse(key)
    R = ep.timeline_rounds(ep.from_replay_layer(key))
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(why)
    holds = np.asarray(ctx["cache"].holds(), float)
    live = np.zeros(holds.size, bool)
    tl_ = np.array([np.nan if r["t_live"] is None else r["t_live"] for r in R], float)
    te_ = np.array([np.nan if r["t_end"] is None else r["t_end"] for r in R], float)
    for lo, hi in zip(tl_, te_):
        if np.isfinite(lo) and np.isfinite(hi):
            live |= (holds >= a + b * lo) & (holds <= a + b * hi)
    cand = holds[live]
    lo2 = a + b * float(np.sort(tl_[np.isfinite(tl_)])[1])
    i0 = int(np.searchsorted(cand, lo2))
    return ctx, cand[i0:i0 + n_crops].tolist()


def _mo_rows(sid: str, frames=None) -> dict:
    """Stored minimap_object frame rows by frame_idx (raw: enemies, "?" marks,
    X marks, refused candidates), optionally only the frames asked."""
    want = None if frames is None else {int(f) for f in frames}
    out = {}
    for r in rt._rows(STORE / "events" / "minimap_object" / f"{sid}.jsonl"):
        if r.get("kind") != "frame":
            continue
        f = int(r["frame_idx"])
        if want is None or f in want:
            out[f] = r
    return out


def _ally_frames(sid: str) -> dict:
    """Stored ally_icon frame rows' fields by frame_idx: widget_drawn, stack_reason."""
    out = {}
    for r in rt._rows(STORE / "events" / "ally_icon" / f"{sid}.jsonl", "widget_drawn"):
        if r.get("kind") == "frame":
            out[int(r["frame_idx"])] = (bool(r.get("widget_drawn")), r.get("stack_reason"))
    return out


def lost_reads(M: RealMatch, V: dict, detail: dict) -> dict:
    """RX5: every scheduled read of a truth-gate arm, its stored outcome and
    context; lost reads (no fit) by the stored reason at that slot and frame.

    The stored reason is read, never inferred: the ally_icon frame row
    (`widget_drawn`, `stack_reason`) and the ally_icon icon rows within two
    icon radii of the slot's last fit at that frame (their `reason`; a
    described icon there is `described_unbound` or `described_bound_to_other`,
    with causal_bind's non-player bucket beside, which is recomputed from
    stored rows). Context: another bound slot's fit or the self fit within two
    radii of the last fit; a stored enemy icon, "?" mark or ally_icon
    `interior_is_map` icon (the ability-glyph class) within two radii at the
    frame; the last fit's distance to the widget edge; time since the round's
    first frame and since the last death (T0, any player); agent; transience
    (a fit on the next in-span frame, within 250 ms, within 500 ms)."""
    from reticle import geometry
    G = V["G"]
    fits, bind = G["fits"], G["bind"]
    S = G["S"]
    r2 = 2.0 * float(S.r)
    H, W = geometry.reference_static(M.cap, STORE).shape[:2]
    has, obs = V["has"], bind["obs"]
    seg = G["life"]["seg_start"]
    lf_all = es.last_fix(has, seg)
    start, cx, cy = fits["start"], fits["cx"], fits["cy"]
    reason = fits["reason"]
    glyph = fits["flags"]["ability_glyph"]
    is_self = fits["is_self"]
    bt = bind["bound_to"]
    npb = bind["np_bucket"]
    AF = _ally_frames(M.cap)
    MO = _mo_rows(M.cap)
    mo_f = np.array(sorted(MO), np.int64)
    mo_t = np.array([float(MO[f]["t_ms"]) for f in mo_f])
    o_ = np.argsort(mo_t)
    mo_f, mo_t = mo_f[o_], mo_t[o_]
    in_idx = np.flatnonzero(V["in_sp"])
    Bt = V["fr_t"][in_idx]
    deaths = np.sort(np.array([e.t_ms for e in M.tl0.events if e.kind == "death"], float))
    rows = []
    for s_, d in detail.items():
        k = d["k"]
        ag = M.agent.get(M.sid[s_])
        for i in range(d["frame"].size):
            f = int(d["frame"][i])
            ok = bool(d["ok"][i])
            fi = int(S.fr_f[f])
            drawn, stack = AF.get(fi, (None, None))
            lf = int(lf_all[k, f - 1]) if f > 0 and seg[f] < f else -1
            rec = {"m": M.cap, "ok": ok, "agent": ag, "stack_reason": stack}
            px = py = None
            if lf >= 0 and obs[k, lf] >= 0:
                px, py = float(cx[obs[k, lf]]), float(cy[obs[k, lf]])
            # stored reason at this slot and frame
            if drawn is False:
                why = "widget_not_drawn"
            elif px is None:
                why = "no_fit_yet_in_round"
            else:
                a_, b_ = int(start[f]), int(start[f + 1])
                ii = np.arange(a_, b_)
                dd = np.hypot(cx[ii] - px, cy[ii] - py) if ii.size else np.zeros(0)
                near = ii[dd <= r2]
                if not near.size:
                    why = "no_icon_row_near_last_fit"
                else:
                    j = near[np.argmin(np.hypot(cx[near] - px, cy[near] - py))]
                    if reason[j] is not None and str(reason[j]) not in ("", "None"):
                        why = f"icon_refused:{reason[j]}"
                    elif bt[j] < 0:
                        why = "described_unbound"
                        rec["np_bucket"] = str(npb[j]) or "none"
                    elif bt[j] == k:
                        why = "bound_to_slot"
                    else:
                        why = "described_bound_to_other"
            rec["reason"] = why
            if px is not None:
                crowd = False
                for j2 in range(5):
                    if j2 != k and obs[j2, lf] >= 0:
                        crowd |= bool(np.hypot(cx[obs[j2, lf]] - px, cy[obs[j2, lf]] - py) <= r2)
                a_, b_ = int(start[lf]), int(start[lf + 1])
                ii = np.arange(a_, b_)
                ii = ii[is_self[ii]]
                crowd |= bool(ii.size and (np.hypot(cx[ii] - px, cy[ii] - py) <= r2).any())
                rec["crowd"] = crowd
                # the minimap_object frame nearest in time (the grids' phases differ on c817691bcd15)
                jj = int(np.clip(np.searchsorted(mo_t, S.fr_t[f]), 1, max(mo_t.size - 1, 1)))
                jj = jj - 1 if abs(mo_t[jj - 1] - S.fr_t[f]) <= abs(mo_t[jj] - S.fr_t[f]) else jj
                mo = MO[int(mo_f[jj])] if mo_t.size and abs(mo_t[jj] - S.fr_t[f]) <= 42.0 else {}
                rec["mo_joined"] = bool(mo)
                age = float(S.fr_t[f] - S.fr_t[lf]) / 1000.0
                rec["last_fit_age_s"] = "<0.5" if age < 0.5 else ("0.5-2" if age < 2 else ("2-5" if age < 5 else ">=5"))
                rec["enemy_near"] = any(np.hypot(e["x"] - px, e["y"] - py) <= r2 for e in mo.get("enemies") or [])
                rec["q_near"] = any(np.hypot(q["x"] - px, q["y"] - py) <= r2 for q in mo.get("questions") or [])
                a_, b_ = int(start[f]), int(start[f + 1])
                ii = np.arange(a_, b_)
                rec["glyph_near"] = bool(ii.size and (glyph[ii] & (np.hypot(cx[ii] - px, cy[ii] - py) <= r2)).any())
                e_ = min(px, py, W - px, H - py)
                rec["edge"] = "<20px" if e_ < 20 else ("20-50px" if e_ < 50 else ">=50px")
            tr = float(S.fr_t[f] - S.fr_t[seg[f]]) / 1000.0
            rec["since_round_s"] = "<10" if tr < 10 else ("10-30" if tr < 30 else ("30-60" if tr < 60 else ">=60"))
            t_rep = float(d["t_sched"][i])
            dj = np.searchsorted(deaths, t_rep, side="right") - 1
            age = t_rep - deaths[dj] if dj >= 0 else np.inf
            rec["since_death_s"] = "<2" if age < 2000 else ("2-5" if age < 5000 else ">=5")
            if not ok:
                b = int(d["b"][i])
                nxt = {}
                for lim, name in ((None, "next_frame"), (250.0, "within_250ms"), (500.0, "within_500ms")):
                    got = False
                    for m_ in range(1, 9):
                        if b + m_ >= Bt.size:
                            break
                        if lim is None and m_ > 1:
                            break
                        if lim is not None and Bt[b + m_] - Bt[b] > lim:
                            break
                        if has[k, in_idx[b + m_]]:
                            got = True
                            break
                    nxt[name] = got
                rec.update(nxt)
            rows.append(rec)
    return {"rows": rows}


def lost_table(rows: list[dict]) -> dict:
    """RX5's tables: reasons of lost reads; per context value, the lost share
    of scheduled reads and the share of lost reads; transience."""
    lost = [r for r in rows if not r["ok"]]
    out = {"scheduled": len(rows), "lost": len(lost), "reason": dict(Counter(r["reason"] for r in lost)),
           "np_bucket_of_described_unbound": dict(Counter(r["np_bucket"] for r in lost if "np_bucket" in r)),
           "stack_reason": dict(Counter(str(r["stack_reason"]) for r in lost))}
    ctx = {}
    for key in ("crowd", "enemy_near", "q_near", "glyph_near", "edge", "last_fit_age_s", "since_round_s",
                "since_death_s", "agent", "m", "mo_joined"):
        vals = Counter(str(r.get(key)) for r in rows)
        lv = Counter(str(r.get(key)) for r in lost)
        ctx[key] = {v: {"scheduled": n, "lost": lv.get(v, 0), "lost_rate": round(lv.get(v, 0) / n, 4),
                        "share_of_lost": round(lv.get(v, 0) / max(len(lost), 1), 4)} for v, n in vals.items()}
    out["context"] = ctx
    out["reason_x_crowd"] = dict(Counter(f"{r['reason']}|crowd={r.get('crowd')}" for r in lost))
    for k in ("next_frame", "within_250ms", "within_500ms"):
        out[f"transient_{k}"] = round(sum(r[k] for r in lost) / max(len(lost), 1), 4)
    return out


def cue_study(sid: str, n_crops: int, record: bool = False) -> int:
    """RX6: where the red on no-enemy crops comes from, and a residual cue
    against the (map, profile) baked base map (fog and revealed layers drawn
    by map_asset; never a session median), on the RR5 crops."""
    import cv2
    from reticle import geometry, map_asset, metrics, minimap_objects as mo, teardrop
    ctx, times = _cue_times(sid, n_crops)
    x0, y0, x1, y1 = ctx["rect"]
    slab = ctx["slab"]
    scale = ctx["scale"]
    thr = CUE_PX * scale ** 2
    key = geometry.key_of(sid, STORE)
    map_name, prof = geometry.parse(key)
    fog_static = geometry.reference_static(sid, STORE)
    P = map_asset.transform(prof)
    fog, rev, _M, _rot, _tx = map_asset.drawn_layers(map_name, prof, STORE, P)
    bg = map_asset.void_background(fog[..., 3], P)
    lit = np.clip(np.rint(map_asset.composite(rev, bg, P)), 0, 255).astype(np.uint8)
    if lit.shape[:2] != fog_static.shape[:2]:
        raise SystemExit(f"baked layers differ in shape: {lit.shape} {fog_static.shape}")
    k3 = np.ones((3, 3), np.uint8)
    # baked red: either layer, one pixel of slack for the drawing's alignment
    base_hsv = cv2.dilate((mo.enemy_red_mask(fog_static) | mo.enemy_red_mask(lit)).astype(np.uint8), k3) > 0
    base_soft = cv2.dilate(np.maximum(teardrop.redness(fog_static), teardrop.redness(lit)), k3)
    slabf = slab.astype(np.float32)
    MOr = None
    rows, crops_keep = [], []
    src = Counter()
    it = ctx["cache"].samples(times, rois=["minimap"])
    t_res = []
    for smp in it:
        crop = smp.frame[y0:y1, x0:x1]
        if crop.shape[:2] != slab.shape:
            continue
        w0 = time.perf_counter()
        resid = np.clip(teardrop.redness(crop) - base_soft, 0.0, 1.0)
        score = float((resid * slabf).sum()) / thr
        t_res.append((time.perf_counter() - w0) * 1e3)
        red = mo.enemy_red_mask(crop) & slab
        rows.append({"t": float(smp.t_ms), "f": int(smp.frame_idx), "score": score, "pos": score >= 1.0,
                     "abs_px": int(red.sum()), "hsv_resid_px": int((red & ~base_hsv).sum())})
        crops_keep.append((int(smp.frame_idx), crop, red))
    MOr = _mo_rows(sid, [r["f"] for r in rows])
    # ally_icon icons and self fits at the nearest ally_icon frame in time (within 42 ms: the
    # grids' phases differ on c817691bcd15); interior_is_map is the ally reader's glyph class.
    # The ability_icon proposer's candidates at its nearest 2 Hz frame within 500 ms.
    tw = np.array([r["t"] for r in rows])
    by_t = defaultdict(list)
    for r in rt._rows(STORE / "events" / "ally_icon" / f"{sid}.jsonl"):
        k_ = r.get("kind")
        if k_ not in ("icon", "frame"):
            continue
        t_ = float(r["t_ms"])
        j_ = int(np.clip(np.searchsorted(tw, t_), 0, tw.size - 1))
        jj_ = [x for x in (j_ - 1, j_) if 0 <= x < tw.size and abs(tw[x] - t_) <= 42.0]
        if not jj_:
            continue
        if k_ == "icon":
            by_t[float(t_)].append((r["cx"], r["cy"], r.get("reason")))
        elif r.get("self") is not None:
            by_t[float(t_)].append((r["self"][0], r["self"][1], "self"))
    ai_t = np.array(sorted(by_t))
    AB = []
    for r in rt._rows(STORE / "events" / "ability_icon" / f"{sid}.jsonl"):
        if r.get("kind") == "frame" and r.get("candidates"):
            AB.append((float(r["t_ms"]), [(c["cx"], c["cy"]) for c in r["candidates"]]))
    ab_t = np.array([a for a, _ in AB])
    AI, ABI = {}, {}
    for r in rows:
        if ai_t.size:
            j_ = int(np.argmin(np.abs(ai_t - r["t"])))
            AI[r["f"]] = by_t[float(ai_t[j_])] if abs(ai_t[j_] - r["t"]) <= 42.0 else []
        if ab_t.size:
            j_ = int(np.argmin(np.abs(ab_t - r["t"])))
            ABI[r["f"]] = AB[j_][1] if abs(ab_t[j_] - r["t"]) <= 500.0 else []
    rad = mo.ICON_PX * scale
    yy, xx = np.mgrid[0:slab.shape[0], 0:slab.shape[1]]
    for row, (fi, crop, red) in zip(rows, crops_keep):
        m = MOr.get(fi) or {}
        row["stored_enemy"] = bool(m.get("enemies"))
        if row["stored_enemy"]:
            continue
        lab = np.full(slab.shape, "", object)
        left = red.copy()

        def take(mask, name):
            nonlocal left
            hit = left & mask
            src[name] += int(hit.sum())
            left = left & ~mask

        take(base_hsv, "baked_map_art")
        for name, pts in (("question_mark", [(q["x"], q["y"]) for q in m.get("questions") or []]),
                          ("x_mark", [(q["x"], q["y"]) for c in ("red", "blue")
                                      for q in (m.get("x_marks") or {}).get(c, [])]),
                          ("refused_red_candidate", [(q["x"], q["y"]) for q in m.get("refused") or []]),
                          ("ability_glyph_ally_reader", [(a, b) for a, b, rs in AI.get(fi, [])
                                                         if rs == "interior_is_map"]),
                          ("ally_or_self_icon", [(a, b) for a, b, rs in AI.get(fi, []) if rs != "interior_is_map"]),
                          ("ability_icon_proposer", ABI.get(fi, []))):
            mk = np.zeros(slab.shape, bool)
            for px_, py_ in pts:
                mk |= np.hypot(xx - px_, yy - py_) <= rad
            take(mk, name)
        src["other"] += int(left.sum())
        _ = lab
    se = np.array([r["stored_enemy"] for r in rows])
    pos = np.array([r["pos"] for r in rows])
    hpos = np.array([r["hsv_resid_px"] >= thr for r in rows])
    tot = sum(src.values())
    out = {"session": sid, "crops": len(rows), "geometry_key": key, "base": "map_asset fog static "
           "(geometry.reference_static) and revealed layer (map_asset.drawn_layers + composite), 3x3 dilated",
           "stored_enemy_crops": int(se.sum()),
           "red_sources_no_enemy_px": {k: int(v) for k, v in src.items()},
           "red_sources_no_enemy_share": {k: round(v / max(tot, 1), 4) for k, v in src.items()},
           "residual_soft": {"positive_share": round(float(pos.mean()), 4),
                             "recall_stored_enemy": round(float(pos[se].mean()), 4) if se.any() else None,
                             "precision": round(float(se[pos].mean()), 4) if pos.any() else None,
                             "agreement": round(float((pos == se).mean()), 4),
                             "score_median_no_enemy": round(float(np.median([r["score"] for r in rows if not r["stored_enemy"]])), 3),
                             "score_median_enemy": (round(float(np.median([r["score"] for r in rows if r["stored_enemy"]])), 3)
                                                    if se.any() else None),
                             "ms_wall": {"median": round(float(np.median(t_res)), 3),
                                         "p90": round(float(np.percentile(t_res, 90)), 3)}},
           "residual_hsv": {"positive_share": round(float(hpos.mean()), 4),
                            "recall_stored_enemy": round(float(hpos[se].mean()), 4) if se.any() else None,
                            "precision": round(float(se[hpos].mean()), 4) if hpos.any() else None},
           "threshold": f"residual redness sum on the slab >= {CUE_PX} x scale^2 (one cut)"}
    # the picture: the no-enemy crop with the most absolute red
    cand = [i for i, r in enumerate(rows) if not r["stored_enemy"]]
    i = max(cand, key=lambda i: rows[i]["abs_px"])
    fi, crop, red = crops_keep[i]
    resid = np.clip(teardrop.redness(crop) - base_soft, 0.0, 1.0) * slabf

    def gray(m):
        return cv2.cvtColor((np.clip(m, 0, 1) * 255).astype(np.uint8), cv2.COLOR_GRAY2BGR)
    panels = [crop, gray(red.astype(np.float32)), gray((base_hsv & slab).astype(np.float32)), gray(resid)]
    names = ["crop", "crop red mask (slab)", "baked map red mask (slab)", "residual redness"]
    big = []
    for im, nm in zip(panels, names):
        im = cv2.resize(im, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)  # display only
        im = cv2.copyMakeBorder(im, 30, 4, 4, 4, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(im, nm, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
        big.append(im)
    png = OUT / f"cue_residual_{sid}_{fi}.png"
    cv2.imwrite(str(png), np.hstack(big))
    out["png"] = {"path": str(png), "frame_idx": fi, "abs_px": rows[i]["abs_px"], "score": round(rows[i]["score"], 3),
                  "hsv_resid_px": rows[i]["hsv_resid_px"]}
    print(json.dumps(out, indent=1))
    (OUT / "cue.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        vals = {}
        for k, v in out.items():
            if isinstance(v, dict):
                for a_, x in v.items():
                    if isinstance(x, dict):
                        vals.update({f"{k}.{a_}.{b_}": y for b_, y in x.items() if isinstance(y, (int, float))})
                    elif isinstance(x, (int, float)) and x is not None:
                        vals[f"{k}.{a_}"] = x
            elif isinstance(v, (int, float)):
                vals[k] = v
        metrics.record("real_reader_schedule", part="cue_residual", session=sid, values=vals,
                       deps={"version": VERSION, "geometry_key": key, "asset": map_asset.asset_stamp(map_name, prof, STORE)},
                       context={"task": TASK, "crops": len(rows)})
    return 0


def cost(sid: str, n_crops: int, record: bool = False) -> int:
    """RR5: time the crop fetch, the cue and read_frame on n consecutive
    live-phase crops, CPU and wall apart, and price per captured frame."""
    from reticle import metrics, minimap_objects as mo
    from reticle.minimap import widget_drawn
    ctx, times = _cue_times(sid, n_crops)
    x0, y0, x1, y1 = ctx["rect"]
    scale = ctx["scale"]
    slab = ctx["slab"]
    thr = CUE_PX * scale ** 2
    fetch_w, fetch_c, cue_w, cue_c, rf_w, rf_c, pos, drawn_ = [], [], [], [], [], [], [], []
    cue_px = []
    it = ctx["cache"].samples(times, rois=["minimap"])
    t_got = []
    while True:
        w0, c0 = time.perf_counter(), time.process_time()
        try:
            smp = next(it)
        except StopIteration:
            break
        crop = smp.frame[y0:y1, x0:x1]
        fetch_w.append((time.perf_counter() - w0) * 1e3)
        fetch_c.append((time.process_time() - c0) * 1e3)
        t_got.append(float(smp.t_ms))
        w0, c0 = time.perf_counter(), time.process_time()
        n = int((mo.enemy_red_mask(crop) & slab).sum()) if crop.shape[:2] == slab.shape else 0
        cue_w.append((time.perf_counter() - w0) * 1e3)
        cue_c.append((time.process_time() - c0) * 1e3)
        pos.append(n >= thr)
        cue_px.append(n)
        dr = crop.shape[:2] == ctx["floor"].shape and widget_drawn(crop, ctx["sgray"], ctx["floor"])
        drawn_.append(bool(dr))
        if dr:
            seg = ctx["cache"].widget.at(smp.t_ms) if ctx["cache"].widget is not None else None
            turn = bool(seg) and int(seg.get("rotation", 0)) == 180
            w0, c0 = time.perf_counter(), time.process_time()
            mo.read_frame(crop, ctx, scale=scale, turn=turn)
            rf_w.append((time.perf_counter() - w0) * 1e3)
            rf_c.append((time.process_time() - c0) * 1e3)
    # the oracle cue: stored rows holding an enemy at these frames
    MO = rt.load_minimap_object(sid)
    want = np.asarray(t_got)
    j = np.searchsorted(MO["t_ms"], want)
    j = np.clip(j, 0, MO["t_ms"].size - 1)
    hit = np.abs(MO["t_ms"][j] - want) < 1.0
    has_enemy = np.isin(MO["frame_idx"][j], MO["enemy_frame"]) & hit

    def q(v):
        v = np.asarray(v, float)
        return {"median": round(float(np.median(v)), 3), "p90": round(float(np.percentile(v, 90)), 3),
                "mean": round(float(v.mean()), 3), "n": int(v.size)}

    def qc(v):
        # Windows process time ticks at 15.625 ms: a per-crop CPU median is
        # meaningless, so CPU is the batch mean (sum of intervals over n)
        v = np.asarray(v, float)
        return {"mean": round(float(v.mean()), 3), "n": int(v.size), "tick_ms": 15.625}
    ally_ms = None
    for r in metrics.load():
        if (r.get("tool"), r.get("part"), r.get("session")) == ALLY_COST[:3]:
            ally_ms = r["values"][ALLY_COST[3]]
    P = json.loads((OUT / "pooled.json").read_text(encoding="utf-8"))["pools"]
    cue_share = float(np.mean(pos))
    oracle_share = float(has_enemy.mean())
    out = {"session": sid, "crops": len(t_got), "t_first": t_got[0] if t_got else None,
           "t_last": t_got[-1] if t_got else None, "scale": scale, "cue_threshold_px": thr,
           "fetch_ms_wall": q(fetch_w), "fetch_ms_cpu": qc(fetch_c), "cue_ms_wall": q(cue_w),
           "cue_ms_cpu": qc(cue_c), "read_frame_ms_wall": q(rf_w), "read_frame_ms_cpu": qc(rf_c),
           "drawn_share": round(float(np.mean(drawn_)), 4), "cue_positive_share": round(cue_share, 4),
           "cue_px": {f"p{p_}": float(np.percentile(cue_px, p_)) for p_ in (10, 50, 90)},
           "cue_px_with_stored_enemy_median": (float(np.median(np.asarray(cue_px)[has_enemy]))
                                               if has_enemy.any() else None),
           "cue_px_without_stored_enemy_median": (float(np.median(np.asarray(cue_px)[~has_enemy]))
                                                  if (~has_enemy).any() else None),
           "stored_enemy_share": round(oracle_share, 4), "stored_rows_matched": int(hit.sum()),
           "ally_icon_ms_per_read": ally_ms, "ally_icon_source": "/".join(ALLY_COST)}
    for pool in ("dev2", "dev3"):
        fs = P[pool]["Vgate"]["frame_share"]
        cue_ms, rf_ms = out["cue_ms_wall"]["median"], out["read_frame_ms_wall"]["median"]
        fetch_ms = out["fetch_ms_wall"]["median"]
        base = 15.0 * cue_ms + 15.0 * fs * ally_ms
        out[f"price.{pool}"] = {
            "vgate_frame_share": round(fs, 4),
            "per_captured_ms_cue_gated": round((base + 15.0 * cue_share * rf_ms) / 60.0, 3),
            "per_captured_ms_oracle": round((base + 15.0 * oracle_share * rf_ms) / 60.0, 3),
            "decode_per_captured_ms": round(15.0 * fetch_ms / 60.0, 3),
            "basis": "per second: 15 cues + 15 x Vgate frame share x ally_icon ms + 15 x positive share x "
                     "read_frame ms (wall medians, one thread at idle priority; CPU means beside), over 60 captured frames; decode apart"}
    print(json.dumps(out, indent=1))
    (OUT / "cost.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        vals = {}
        for k, v in out.items():
            if isinstance(v, dict):
                vals.update({f"{k}.{a_}": x for a_, x in v.items() if isinstance(x, (int, float))})
            elif isinstance(v, (int, float)) and v is not None:
                vals[k] = v
        metrics.record("real_reader_schedule", part="cost", session=sid, values=vals,
                       deps={"version": VERSION, "minimap_object": mo.minimap_object_version()},
                       context={"task": TASK, "crops": len(t_got), "threads": 1, "priority": "idle"})
    return 0


# ----------------------------------------------------------------- outcome

def _clause(held, **nums) -> dict:
    return {"held": bool(held), **nums}


def outcome() -> int:
    P = json.loads((OUT / "pooled.json").read_text(encoding="utf-8"))
    C = json.loads((OUT / "cost.json").read_text(encoding="utf-8"))
    pred = STORE / "notes" / "predictions.jsonl"
    lines = pred.read_text(encoding="utf-8").splitlines()
    if any(f'"{TASK}-RR0-outcome"' in s for s in lines):
        raise SystemExit("outcome rows already appended")
    d2, d3 = P["pools"]["dev2"], P["pools"]["dev3"]
    inst = {r["session"]: r for r in P["instrument"]}
    res = {}
    stored = {"9acf02f98283": 0.0419, "c817691bcd15": 0.0465, "d3dcfb182ab1": 0.0577}
    res["RR0"] = {"RR0a": _clause(all(r["rr0a"]["equal"] for r in inst.values()),
                                  shares={s: round(r["rr0a"]["share"], 4) for s, r in inst.items()},
                                  registered=stored),
                  "RR0b": _clause(all(inst[s]["rr0b"]["ls_slope"]["within_3m"] >= 0.85
                                      and inst[s]["rr0b"]["ls_slope"]["median_m"] <= 1.5 for s in JUDGED),
                                  **{s: inst[s]["rr0b"] for s in inst if "ls_slope" in inst[s]["rr0b"]})}
    r1 = P["rr1a"]
    c1 = d2["T1v"]["vs_ref"]["contact_C"]
    res["RR1"] = {"RR1a": _clause(all(0.35 <= r1[s]["ratio_live"] <= 0.75 for s in JUDGED),
                                  **{s: round(r1[s]["ratio_live"], 4) for s in r1}),
                  "RR1b": _clause(None, note="filled below")}
    # contact recall: matched T1 contacts over T1 contacts, pooled from rows
    rows = [json.loads(s) for s in (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]
    tp = sum(r["vs_ref"]["contact_C"]["tp"] for r in rows if r["arm"] == "T1v" and r["session"] in JUDGED)
    nn = sum(r["vs_ref"]["contact_C"]["n"] for r in rows if r["arm"] == "T1v" and r["session"] in JUDGED)
    tp3 = sum(r["vs_ref"]["contact_C"]["tp"] for r in rows if r["arm"] == "T1v")
    nn3 = sum(r["vs_ref"]["contact_C"]["n"] for r in rows if r["arm"] == "T1v")
    res["RR1"]["RR1b"] = _clause(0.40 <= tp / nn <= 0.80, recall=round(tp / nn, 4), tp=tp, n=nn,
                                 strict_agreement=c1, dev3_recall=round(tp3 / nn3, 4))
    v = d2["Vgate"]["vs_ref"]
    res["RR2"] = {
        "RR2a": _clause(all(v[q]["agree"] >= 0.95 for q in ("contact_C", "duel_C", "trade_C")),
                        **{q: v[q] for q in ("contact_C", "duel_C", "trade_C")}),
        "RR2b": _clause(all(v[q]["agree"] >= 0.92 for q in ("opening_first_seer", "first_sight_support")),
                        **{q: v[q] for q in ("opening_first_seer", "first_sight_support")}),
        "RR2c": _clause(0.92 <= v["spacing_5m"]["agree"] <= 0.98 and 0.85 <= v["spacing_death"]["agree"] <= 0.95,
                        spacing_5m=v["spacing_5m"], spacing_death=v["spacing_death"]),
        "RR2d": _clause(0.030 <= d2["Vgate"]["read_ratio_vs_ref"] <= 0.060,
                        ratio=round(d2["Vgate"]["read_ratio_vs_ref"], 4))}
    o2 = P["onsets"]["dev2"]
    res["RR3"] = {
        "RR3a": _clause(0.55 <= o2["real_global"]["open_0"] <= 0.85
                        and o2["truth_global"]["open_0"] - o2["real_global"]["open_0"] >= 0.05,
                        real=o2["real_global"]["open_0"], truth=o2["truth_global"]["open_0"], n=o2["n"]),
        "RR3b": _clause(250 <= (o2["real_global"].get("lead_p50") or -1) <= 650,
                        lead_p50=o2["real_global"].get("lead_p50")),
        "RR3c": _clause(0.50 <= o2["real_local"]["open_0"] <= 0.80, real_local=o2["real_local"]["open_0"],
                        truth_local=o2["truth_local"]["open_0"])}
    vt, lp = d3["Vgate-t"]["vs_ref"], d3["Lp"]["vs_ref"]
    res["RR4"] = {"RR4a": _clause(all(abs(vt[q]["agree"] - lp[q]["agree"]) <= 0.03 for q in SIGHT_QS),
                                  **{q: [vt[q]["agree"], lp[q]["agree"]] for q in SIGHT_QS}),
                  "RR4b": _clause(0.040 <= d3["Vgate-t"]["read_ratio_vs_ref"] <= 0.065,
                                  ratio=round(d3["Vgate-t"]["read_ratio_vs_ref"], 4))}
    pr = C["price.dev2"]
    res["RR5"] = {"RR5a": _clause(0.4 <= C["cue_ms_wall"]["median"] <= 1.5, cue=C["cue_ms_cpu"], wall=C["cue_ms_wall"]),
                  "RR5b": _clause(3 <= C["read_frame_ms_wall"]["median"] <= 20, read_frame=C["read_frame_ms_cpu"],
                                  wall=C["read_frame_ms_wall"]),
                  "RR5c": _clause(0.40 <= C["cue_positive_share"] <= 0.80, share=C["cue_positive_share"]),
                  "RR5d": _clause(1.0 <= pr["per_captured_ms_cue_gated"] <= 3.0
                                  and 0.6 <= pr["per_captured_ms_oracle"] <= 1.6, **pr)}
    r6 = P["rr6"]
    ok6 = [s for s in JUDGED if s in r6 and r6[s].get("same_slot_share") is not None]
    res["RR6"] = {"RR6a": _clause(all(r6[s]["same_slot_share"] >= 0.90 for s in ok6) and ok6,
                                  **{s: r6[s]["same_slot_share"] for s in r6}),
                  "RR6b": _clause(all(0.02 <= r6[s]["drop"] <= 0.10 for s in ok6) and ok6,
                                  **{s: r6[s]["drop"] for s in r6})}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    with pred.open("a", encoding="utf-8") as f:
        for cand, cl in res.items():
            row = {"id": f"{TASK}-{cand}-outcome", "task": TASK, "date": time.strftime("%Y-%m-%d"), "ts": ts,
                   "domain": "episodes", "kind": "outcome", "branch": TASK, "commit": f"{TASK} (see git log)",
                   "prototype": "prototypes/real_reader_schedule.py", "version": VERSION, "wire": "no",
                   "wire_reason": "an evaluation pilot over stored rows and replay truth; reticle/ never imports it",
                   "outcome_of": [f"{TASK}-{cand}"], "candidate": cand,
                   "clauses": {k: dict(v, verdict="held" if v["held"] else "failed") for k, v in cl.items()},
                   "scored": "clauses judged on c817691bcd15 + d3dcfb182ab1 (RR4 on all three); "
                             "9acf02f98283's minimap_object and enemy_track streams were written after "
                             "registration and its real-enemy arms are pooled beside (dev3), never judged; "
                             "held-out cea8ecbc94ab / bd7efa02 never read; metrics series real_reader_schedule",
                   "outputs": str(OUT)}
            f.write(json.dumps(row, default=cq._jd) + "\n")
            print(cand, {k: ("held" if v["held"] else "failed") for k, v in cl.items()})
    return 0


def outcome_rx() -> int:
    """RX1-RX6 outcome rows, from pooled.json and cue.json."""
    P = json.loads((OUT / "pooled.json").read_text(encoding="utf-8"))
    pred = STORE / "notes" / "predictions.jsonl"
    if any(f'"{TASK}-RX1-outcome"' in x for x in pred.read_text(encoding="utf-8").splitlines()):
        raise SystemExit("RX outcome rows already appended")
    d2 = P["pools"]["dev2"]
    dg = P["diag"]["dev2"]["Vgate-t"]["vs_T0_flips"]
    br = sum(dg[q]["broken"] for q in ("first_sight_support", "contact_C"))
    lost = sum(dg[q]["any_flag"]["lost_read"] for q in ("first_sight_support", "contact_C"))
    far = sum(dg[q]["any_flag"]["far_fit"] for q in ("first_sight_support", "contact_C"))
    res = {"RX1": {"RX1a": _clause(br and lost / br >= 0.5, share=round(lost / br, 4) if br else None, k=lost, n=br),
                   "RX1b": _clause(br and far / br < 0.25, share=round(far / br, 4) if br else None, k=far, n=br)}}
    v = d2["Vgate-t-r"]["vs_ref"]
    others = ("opening_first_seer", "spacing_5m", "spacing_death", "duel_C", "trade_C")
    res["RX2"] = {"RX2a": _clause(v["first_sight_support"]["agree"] >= 0.85, **v["first_sight_support"]),
                  "RX2b": _clause(v["contact_C"]["agree"] >= 0.90, **v["contact_C"]),
                  "RX2c": _clause(all(v[q]["agree"] >= 0.92 for q in others), **{q: v[q]["agree"] for q in others}),
                  "RX2d": _clause(d2["Vgate-t-r"]["read_ratio_vs_ref"] <= 0.11,
                                  ratio=round(d2["Vgate-t-r"]["read_ratio_vs_ref"], 4))}
    v = d2["Vgate-r"]["vs_ref"]
    res["RX3"] = {"RX3a": _clause(v["contact_C"]["agree"] >= 0.90, **v["contact_C"]),
                  "RX3b": _clause(v["first_sight_support"]["agree"] >= 0.80, **v["first_sight_support"]),
                  "RX3c": _clause(d2["Vgate-r"]["read_ratio_vs_ref"] <= 0.075,
                                  ratio=round(d2["Vgate-r"]["read_ratio_vs_ref"], 4))}
    v = d2["Vgate-t-r1"]["vs_ref"]
    q4 = [q for q in SIGHT_QS if q != "spacing_death"]
    res["RX4"] = {"RX4a": _clause(all(v[q]["agree"] >= 0.92 for q in q4), **{q: v[q]["agree"] for q in q4}),
                  "RX4b": _clause(d2["Vgate-t-r1"]["share"] <= 0.08, share=round(d2["Vgate-t-r1"]["share"], 4))}
    L = P["lost_reads"]["dev2"]
    crowd = L["context"]["crowd"].get("True", {}).get("share_of_lost", 0.0)
    res["RX5"] = {"RX5a": _clause(crowd >= 0.5, share_crowd=crowd),
                  "RX5b": _clause(L["transient_within_500ms"] >= 0.6, share_within_500ms=L["transient_within_500ms"],
                                  next_frame=L["transient_next_frame"], within_250ms=L["transient_within_250ms"])}
    cp = OUT / "cue.json"
    if cp.is_file():
        C = json.loads(cp.read_text(encoding="utf-8"))["residual_soft"]
        res["RX6"] = {"RX6a": _clause(C["positive_share"] <= 0.25, share=C["positive_share"]),
                      "RX6b": _clause((C["recall_stored_enemy"] or 0) >= 0.9, recall=C["recall_stored_enemy"]),
                      "RX6c": _clause(C["ms_wall"]["median"] <= 1.5, ms=C["ms_wall"])}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    with pred.open("a", encoding="utf-8") as f:
        for cand, cl in res.items():
            row = {"id": f"{TASK}-{cand}-outcome", "task": TASK, "date": time.strftime("%Y-%m-%d"), "ts": ts,
                   "domain": "episodes", "kind": "outcome", "branch": TASK, "commit": f"{TASK} (see git log)",
                   "prototype": "prototypes/real_reader_schedule.py", "version": VERSION, "wire": "no",
                   "wire_reason": "an evaluation pilot over stored rows and replay truth; reticle/ never imports it",
                   "outcome_of": [f"{TASK}-{cand}"], "candidate": cand,
                   "clauses": {k: dict(v, verdict="held" if v["held"] else "failed") for k, v in cl.items()},
                   "scored": "dev2 = c817691bcd15 + d3dcfb182ab1 judged (RX6 on c817691bcd15's 600 RR5 crops); "
                             "dev3 with 9acf02f98283 beside in pooled.json; held-out never read",
                   "outputs": str(OUT)}
            f.write(json.dumps(row, default=cq._jd) + "\n")
            print(cand, {k: ("held" if v["held"] else "failed") for k, v in cl.items()})
    return 0


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
        for q in SIGHT_QS:
            I = [(r["session"], x[0], x[1], x[2]) for r in rs for x in r["paired_T1"][q]["i"]]
            if not I:
                continue
            cl = {}
            for sname, rn, ro, ao in I:
                c = cl.setdefault((sname, rn), [0, 0, 0])
                c[0] += ao - ro
                c[1] += 1
                c[2] += ao
            d = np.array([v[0] for v in cl.values()], float)
            n = np.array([v[1] for v in cl.values()], float)
            a = np.array([v[2] for v in cl.values()], float)
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
                         "broken": int(sum(1 for x in I if x[2] and not x[3])),
                         "fixed": int(sum(1 for x in I if x[3] and not x[2])), "clusters": int(d.size),
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


def outcome_qa5r2() -> int:
    """RX7's outcome row and one post-hoc QA5r2 verdict row per earlier arm."""
    Q = json.loads((OUT / "qa5r2.json").read_text(encoding="utf-8"))["pools"]
    pred = STORE / "notes" / "predictions.jsonl"
    have = set()
    for x in pred.read_text(encoding="utf-8").splitlines():
        if '"id"' in x:
            have.add(json.loads(x).get("id"))
    rows = [json.loads(x) for x in (OUT / "rows.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    nofit = defaultdict(int)
    for r in rows:
        if r["session"] in JUDGED:
            nofit[r["arm"]] += (r["cost"].get("lost") or {}).get("read_lost:no_fit", 0)
    d2 = Q["dev2"]

    def qs(arm):
        return {q: [v["loss"], v["ci"]] for q, v in d2[arm]["q"].items()}
    cl = {"RX7a": _clause(d2["Vgate-d"]["pass_except_spacing_death"], losses=qs("Vgate-d")),
          "RX7b": _clause(d2["Vgate-d"]["share"] <= 0.035, share=round(d2["Vgate-d"]["share"], 4)),
          "RX7c": _clause(nofit["Vgate-d"] <= 0.65 * nofit["Vgate"], no_fit=nofit["Vgate-d"], vgate=nofit["Vgate"],
                          fall=round(1 - nofit["Vgate-d"] / nofit["Vgate"], 4)),
          "RX7d": _clause(d2["Vgate-t-d"]["pass_except_spacing_death"], losses=qs("Vgate-t-d")),
          "RX7e": _clause(d2["Vgate-t-d"]["share"] <= 0.035, share=round(d2["Vgate-t-d"]["share"], 4)),
          "RX7f": _clause(nofit["Vgate-t-d"] <= 0.65 * nofit["Vgate-t"], no_fit=nofit["Vgate-t-d"],
                          vgate_t=nofit["Vgate-t"], fall=round(1 - nofit["Vgate-t-d"] / nofit["Vgate-t"], 4))}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    base = {"date": time.strftime("%Y-%m-%d"), "ts": ts, "domain": "episodes", "kind": "outcome", "branch": TASK,
            "commit": f"{TASK} (see git log)", "prototype": "prototypes/real_reader_schedule.py", "version": VERSION,
            "wire": "no", "wire_reason": "an evaluation pilot over stored rows and replay truth; reticle/ never imports it",
            "outputs": str(OUT / "qa5r2.json")}
    with pred.open("a", encoding="utf-8") as f:
        if f"{TASK}-RX7-outcome" not in have:
            f.write(json.dumps(dict(base, id=f"{TASK}-RX7-outcome", task=TASK, outcome_of=[f"{TASK}-RX7"],
                                candidate="RX7", clauses={k: dict(v, verdict="held" if v["held"] else "failed")
                                                          for k, v in cl.items()},
                                scored="dev2 under QA5r2 (question-acceptance-20261006 QA5r2); dev3 in qa5r2.json"),
                               default=cq._jd) + "\n")
        print("RX7", {k: ("held" if v["held"] else "failed") for k, v in cl.items()})
        for arm in POST_HOC:
            if arm not in d2 or arm in ("V15h", "V15t") or f"QA5r2-posthoc-{arm}" in have:
                continue
            o = d2[arm]
            f.write(json.dumps(dict(base, id=f"QA5r2-posthoc-{arm}", task="question-acceptance-20261006",
                                    outcome_of=["question-acceptance-20261006-QA5r2"], candidate="QA5r2",
                                    post_hoc=True, arm=arm, ref=o["ref"], verdict=o["verdict"],
                                    share=None if o["share"] is None else round(o["share"], 4),
                                    share_ok=o["share_ok"],
                                    per_question={q: {"loss": v["loss"], "ci": v["ci"], "pass": v["pass"],
                                                      "acc": v["acc"], "acc_ref": v["acc_ref"]}
                                                  for q, v in o["q"].items()},
                                    dev3_verdict=Q["dev3"][arm]["verdict"],
                                    scored="dev2; post hoc: the bar was set after this arm's numbers were seen"),
                               default=cq._jd) + "\n")
            print("post hoc", arm, o["verdict"])
    return 0


def outcome_qa5r3() -> int:
    """One post-hoc QA5r3 verdict row per arm (every arm predates the rule) and RX8's outcome."""
    Q = json.loads((OUT / "qa5r3.json").read_text(encoding="utf-8"))["pools"]
    pred = STORE / "notes" / "predictions.jsonl"
    have = {json.loads(x).get("id") for x in pred.read_text(encoding="utf-8").splitlines() if '"id"' in x}
    ts = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    base = {"date": time.strftime("%Y-%m-%d"), "ts": ts, "domain": "episodes", "kind": "outcome", "branch": TASK,
            "commit": f"{TASK} (see git log)", "prototype": "prototypes/real_reader_schedule.py", "version": VERSION,
            "wire": "no", "wire_reason": "an evaluation pilot over stored rows and replay truth; reticle/ never imports it"}
    d2 = Q["dev2"]
    with pred.open("a", encoding="utf-8") as f:
        for arm in ORDER:
            if arm not in d2 or arm in ("V15h", "V15t") or f"QA5r3-posthoc-{arm}" in have:
                continue
            o = d2[arm]
            f.write(json.dumps(dict(base, id=f"QA5r3-posthoc-{arm}", task="question-acceptance-20261006",
                                    outcome_of=["question-acceptance-20261006-QA5r3"], candidate="QA5r3",
                                    post_hoc=True, arm=arm, ref=o["ref"], verdict=o["verdict"],
                                    share=None if o["share"] is None else round(o["share"], 4),
                                    share_ok=o["share_ok"],
                                    per_question={q: {"loss": v["loss"], "ci": v["ci"], "pass": v["pass"]}
                                                  for q, v in o["q"].items()},
                                    dev3_verdict=Q["dev3"][arm]["verdict"],
                                    outputs=str(OUT / "qa5r3.json"),
                                    scored="dev2; post hoc: the bar was chosen after this arm's QA5r2 numbers were seen"),
                               default=cq._jd) + "\n")
            print("post hoc", arm, o["verdict"])
        P = json.loads((OUT / "pooled.json").read_text(encoding="utf-8"))
        r8 = P.get("rx8", {}).get("dev2")
        if r8 and f"{TASK}-RX8-outcome" not in have:
            cl = {}
            for arm, v in r8.items():
                b, u = v["broken"], v["unbroken"]
                sb = b["outside"] / b["n"] if b["n"] else None
                su = u["outside"] / u["n"] if u["n"] else None
                held = sb is not None and su is not None and sb >= 0.6 and su <= 0.4
                cl[f"RX8:{arm}"] = {"held": held, "verdict": "held" if held else "failed",
                                    "broken_outside": [b["outside"], b["n"], None if sb is None else round(sb, 4)],
                                    "unbroken_outside": [u["outside"], u["n"], None if su is None else round(su, 4)]}
            f.write(json.dumps(dict(base, id=f"{TASK}-RX8-outcome", task=TASK, outcome_of=[f"{TASK}-RX8"],
                                    candidate="RX8", clauses=cl, outputs=str(OUT / "pooled.json"),
                                    scored="dev2 (c817691bcd15 + d3dcfb182ab1); dev3 in pooled.json rx8"),
                               default=cq._jd) + "\n")
            print("RX8", {k: v["verdict"] for k, v in cl.items()})
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("sessions", nargs="+")
    rp = sub.add_parser("report")
    rp.add_argument("--record", action="store_true")
    rp.add_argument("--qa5r2", action="store_true", help="rescore under QA5r2 (accuracy against T1)")
    rp.add_argument("--qa5r3", action="store_true", help="rescore under QA5r3 (interval excludes a 0.05 loss)")
    c = sub.add_parser("cost")
    c.add_argument("session")
    c.add_argument("--crops", type=int, default=600)
    c.add_argument("--record", action="store_true")
    cu = sub.add_parser("cue")
    cu.add_argument("session")
    cu.add_argument("--crops", type=int, default=600)
    cu.add_argument("--record", action="store_true")
    sub.add_parser("outcome")
    sub.add_parser("outcome-rx")
    sub.add_parser("outcome-qa5r2")
    sub.add_parser("outcome-qa5r3")
    a = ap.parse_args(argv)
    for s in getattr(a, "sessions", []) or []:
        refuse(s)
    if getattr(a, "session", None):
        refuse(a.session)
    cq._idle()
    if a.cmd == "run":
        return run_matches(a.sessions)
    if a.cmd == "report":
        if a.qa5r3:
            return report_qa5r2(a.record, "QA5r3")
        return report_qa5r2(a.record) if a.qa5r2 else report(a.record)
    if a.cmd == "cost":
        return cost(a.session, a.crops, a.record)
    if a.cmd == "cue":
        return cue_study(a.session, a.crops, a.record)
    if a.cmd == "outcome-rx":
        return outcome_rx()
    if a.cmd == "outcome-qa5r2":
        return outcome_qa5r2()
    if a.cmd == "outcome-qa5r3":
        return outcome_qa5r3()
    return outcome()


if __name__ == "__main__":
    raise SystemExit(main())
