"""Execution questions on truth: can the replay answer them, do they matter,
and how well can a capture measure them (docs/EXECUTION_QUESTIONS.md).

    python prototypes/execution_questions.py fields MATCH       # what the replay holds, and its rates
    python prototypes/execution_questions.py duels MATCH [...]  # per-duel rows for matches
    python prototypes/execution_questions.py value [--record]   # pooled value over the stored duel rows
    python prototypes/execution_questions.py ladder [--record]  # head share of hits against round win
    python prototypes/execution_questions.py selfface [--record]  # capture self facing against replay yaw
    python prototypes/execution_questions.py hudfire [--record]   # 2 Hz HUD ammo drop against truth shots

An evaluation script over stored truth (replay layer, vrfkit export, truth
episodes, raw ladder history) and stored capture rows (team_vision, hud);
reticle/ never imports it. The held-out match bd7efa02 (capture cea8ecbc94ab)
is refused by name before any file opens. Predictions EQ0-EQ9 sit in the
store's notes/predictions.jsonl, task execution-questions-20261007,
registered before the first value run.

What the replay adds beyond the layer, read here from vrfkit's export:

- shots: a gun's magazine (`AmmoComponent.AuthResourceAmount`, the
  component with the most single steps) falls by one per shot, on the
  server tick the shot's damage call carries; the gun's latest `Owner`
  reference names the shooter (`replay_actors.Export.owner_subject`).
- hit region: `MulticastNotifyDamage_Point.RegionalDamage`; 1 is checked as
  head and 2 as legs (domain:replay/vrf-damage-hit-region); this script calls
  every other value of a player hit "body", unverified.
- blinds: each onset of `BlindManagerComponent.LongestActiveBlindDuration` on
  a player's pawn opens a blind of that many seconds (0.2.0; 0.1.0 read
  `ActiveBlinds[k].InitialDuration`, which vrfkit decodes on two replays only).
"""
from __future__ import annotations

import ctypes
import gzip
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from reticle import episodes as ep  # noqa: E402
from reticle.dev_set import FROZEN_DEV, FROZEN_HELD_OUT, FROZEN_HELD_OUT_REPLAY  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "execution-questions-0.2.0"
TASK = "execution-questions-20261007"
HELD_OUT_PREFIX = FROZEN_HELD_OUT_REPLAY[0]
HELD_OUT_SESSION = FROZEN_HELD_OUT[0]
OUT = Path(DEFAULT_STORE) / "analysis" / TASK
DEV = ("60c7f1e0", "b03fecd3", "16a475cb")
DEV_SESSIONS = FROZEN_DEV

GRID_MS = 8.0                 # the server tick (domain:replay/vrf-position-stream)
PRE_MS = 1000.0               # window before the contact onset
BACK_MS = 3000.0              # exposure search reaches this far back before calling it censored
RENDER_MS = 50.0              # RENDER_DELAY's constant prior: the target as shown
HEAD_CM = 15.0                # on target: within atan(15 cm / distance)
PREFIRE_MS = 300.0
#: The kill event precedes its damage call by a tick or two (60c7f1e0 round 1: 9 ms).
KILL_SLACK_MS = 50.0
HIT_TOL_MS = 16.0
SPEED_DT_MS = 16.0
STILL_CMS, MOVING_CMS = 100.0, 250.0
REGION = {1: "head", 0: "body", 2: "legs", 5: "none"}
GUN_PATH = "/Game/Equippables/Guns/"


def _idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)   # IDLE_PRIORITY_CLASS
    except Exception:
        pass


def _refuse(key: str) -> None:
    if key.startswith(HELD_OUT_PREFIX) or key.startswith(HELD_OUT_SESSION):
        raise SystemExit("the held-out replay is never read")


def replay_matches() -> list[str]:
    d = Path(DEFAULT_STORE) / "analysis" / "replay-layer"
    return sorted(p.name for p in d.iterdir() if p.is_dir() and not p.name.startswith(HELD_OUT_PREFIX))


def _full(key: str) -> str:
    hits = [m for m in replay_matches() if m.startswith(key)]
    if len(hits) != 1:
        raise SystemExit(f"{key}: {len(hits)} matches")
    return hits[0]


# ----------------------------------------------------------------- truth extras

class Extras:
    """Shots, hit regions and blinds of one replay, from vrfkit's export."""

    def __init__(self, match: str):
        import pyarrow as pa
        import pyarrow.compute as pc
        import pyarrow.parquet as pq
        from reticle.replay_actors import Export, _leaf
        from reticle.replay_layer import _read_fields, _subject_of_guid, rpc_calls

        _refuse(match)
        self.match = match
        ex = Export(match)
        rp = ex.rp
        self.ex = ex
        F = pq.read_table(ex.dir / "export" / "fields.parquet",
                          columns=["time_ms", "actor_net_guid", "object_net_guid", "group_path", "field_name",
                                   "value_i64", "value_f64"])
        gp = pc.cast(F["group_path"], pa.string())
        fn = pc.cast(F["field_name"], pa.string())
        # shots
        A = F.filter(pc.and_(pc.equal(gp, "/Script/ShooterGame.AmmoComponent"),
                             pc.equal(fn, "AuthResourceAmount")))
        t = A["time_ms"].to_numpy().astype(float)
        g = A["actor_net_guid"].to_numpy().astype(np.int64)
        o = np.array([-1 if v is None else int(v) for v in A["object_net_guid"].to_pylist()], np.int64)
        v = A["value_i64"].to_numpy(zero_copy_only=False).astype(float)
        O = F.filter(pc.equal(fn, "Owner"))
        own = defaultdict(list)
        for tt, gg, vv, gpp in zip(O["time_ms"].to_numpy(), O["actor_net_guid"].to_numpy(),
                                   O["value_i64"].to_numpy(zero_copy_only=False),
                                   pc.cast(O["group_path"], pa.string()).to_pylist()):
            leaf = _leaf(ex.cls.get(int(gg))).removesuffix("_C")
            if leaf and leaf in (gpp or "") and vv is not None and np.isfinite(vv) and int(vv):
                own[int(gg)].append((float(tt), int(vv)))
        best = {}
        for gg in np.unique(g):
            sel = g == gg
            for oo in np.unique(o[sel]):
                s2 = sel & (o == oo)
                k = np.argsort(t[s2], kind="stable")
                n1 = int((np.diff(v[s2][k]) == -1).sum())
                if n1 > best.get(int(gg), (None, -1))[1]:
                    best[int(gg)] = (int(oo), n1)
        sub_cache = {}
        shots = defaultdict(list)
        self.shot_steps = Counter()
        self.unowned_shots = 0
        for gg, (oo, _n1) in best.items():
            if not ex.cls.get(gg, "").startswith(GUN_PATH):
                continue
            s2 = (g == gg) & (o == oo)
            k = np.argsort(t[s2], kind="stable")
            tt, vv = t[s2][k], v[s2][k]
            ol = own.get(gg, [])
            ot = np.array([x[0] for x in ol])
            for i in np.flatnonzero(np.diff(vv) < 0):
                step = int(vv[i] - vv[i + 1])
                self.shot_steps[step] += 1
                if step != 1:
                    continue
                ts = float(tt[i + 1])
                j = int(np.searchsorted(ot, ts, side="right")) - 1 if ot.size else -1
                if j < 0:
                    self.unowned_shots += 1
                    continue
                og = ol[j][1]
                if og not in sub_cache:
                    sub_cache[og] = ex.owner_subject(og)[0]
                s = sub_cache[og]
                if s is None:
                    self.unowned_shots += 1
                    continue
                shots[s].append((ts, _leaf(ex.cls.get(gg))))
        self.shots = {s: np.array(sorted(x[0] for x in L)) for s, L in shots.items()}
        self.shot_class = {s: [c for _t, c in sorted(L)] for s, L in shots.items()}
        # hits with region
        Fd = _read_fields(match, DEFAULT_STORE, prefixes=("MulticastNotifyDamage_Point.",))
        C = rpc_calls(Fd, "MulticastNotifyDamage_Point")
        f = C["fields"]
        ps_sub = ex.player_state_subjects()
        from reticle.replay_layer import _net_guid_paths
        paths = _net_guid_paths(match, DEFAULT_STORE)

        def get(k, i):
            return f[k][i] if k in f else None
        hits = []
        for i in range(C["t"].size):
            victim = rp.guid_subject.get(int(C["g"][i]))
            if victim is None:
                continue
            dmgr = _subject_of_guid(get("EventInstigatorPawn", i) or None, rp, ex, ps_sub) \
                or _subject_of_guid(get("DamagerPlayerState", i) or None, rp, ex, ps_sub)
            eq = get("EquippableUsed", i)
            eqp = (paths.get(int(eq)) or ex.cls.get(int(eq)) or "") if eq else ""
            hits.append({"t": float(C["t"][i]), "by": dmgr, "to": victim,
                         "region": REGION.get(int(get("RegionalDamage", i) or 0), "unknown")
                         if get("RegionalDamage", i) is not None else "unknown",
                         "bone": get("DamagedBone", i), "dealt": get("DamageDealt", i),
                         "zoomed": bool(get("bEquippableUsedZoomed", i)),
                         "gun": eqp.startswith(GUN_PATH), "equippable": _leaf(eqp)})
        self.hits = hits
        # blinds: vrfkit leaves ActiveBlinds as raw bits on most builds but
        # decodes LongestActiveBlindDuration; its onsets (a positive value
        # after 0, or a rise) equal ActiveBlinds[k].InitialDuration where both
        # exist (60c7f1e0 57 of 60, 16a475cb 6 of 6, same ms, same seconds)
        B = F.filter(pc.and_(pc.equal(gp, "/Script/ShooterGame.BlindManagerComponent"),
                             pc.equal(fn, "LongestActiveBlindDuration")))
        per = defaultdict(list)
        for tt, gg, vf in zip(B["time_ms"].to_numpy(), B["actor_net_guid"].to_numpy(),
                              B["value_f64"].to_numpy(zero_copy_only=False)):
            vf = 0.0 if vf is None or not np.isfinite(vf) else float(vf)
            per[int(gg)].append((float(tt), vf))
        blinds = defaultdict(list)
        for gg, rows in per.items():
            s = rp.guid_subject.get(gg)
            if s is None:
                s = ex.owner_subject(gg)[0]
            if s is None:
                continue
            prev = 0.0
            for tt, vf in sorted(rows):
                if vf > 0 and (prev == 0 or vf > prev + 1e-6):
                    blinds[s].append((tt, tt + 1000.0 * vf))
                prev = vf
        self.blinds = {s: sorted(v) for s, v in blinds.items()}
        self.blind_durations = [b - a for L in blinds.values() for a, b in L]

    def check(self) -> dict:
        """EQ0: gun damage calls on players explained by a same-shooter shot."""
        n = k = 0
        lag = []
        for h in self.hits:
            if not h["gun"] or h["by"] is None:
                continue
            n += 1
            arr = self.shots.get(h["by"])
            if arr is None or arr.size == 0:
                continue
            j = np.searchsorted(arr, h["t"])
            d = min((abs(h["t"] - arr[q]) for q in (j - 1, j) if 0 <= q < arr.size), default=1e9)
            lag.append(d)
            k += d <= HIT_TOL_MS
        reg = Counter((h["region"], str(h["bone"])) for h in self.hits if h["gun"])
        head = sum(c for (r, b), c in reg.items() if r == "head")
        headbone = sum(c for (r, b), c in reg.items() if r == "head" and b in ("Head", "Neck"))
        legs = sum(c for (r, b), c in reg.items() if r == "legs")
        legbone = sum(c for (r, b), c in reg.items() if r == "legs" and any(x in b for x in ("Hip", "Knee", "Foot", "Ankle", "Leg", "Thigh", "Calf")))
        shots_n = int(sum(a.size for a in self.shots.values()))
        k = int(k)
        return {"gun_hits": n, "explained": k, "explained_share": round(k / n, 4) if n else None,
                "lag_p99_ms": float(np.percentile(lag, 99)) if lag else None,
                "shots": shots_n, "unowned_shots": self.unowned_shots,
                "multi_steps": int(sum(c for s, c in self.shot_steps.items() if s != 1)),
                "head_rows": head, "head_bone_share": round(headbone / head, 4) if head else None,
                "leg_rows": legs, "leg_bone_share": round(legbone / legs, 4) if legs else None,
                "zoomed_share": round(float(np.mean([h["zoomed"] for h in self.hits if h["gun"]])), 4)
                if self.hits else None,
                "blinds": int(sum(len(v) for v in self.blinds.values())),
                "blind_dur_p50_ms": float(np.median(self.blind_durations)) if self.blind_durations else None}


# ----------------------------------------------------------------- fields

def fields(key: str) -> dict:
    """What the replay layer holds for execution questions, and its rates."""
    from reticle.replay_layer import load
    _refuse(key)
    L = load(key)
    T, E = L.ticks, L.entities
    pe = [i for i, k in enumerate(E["kind"]) if k == "player"]
    dts, ystep = [], []
    for e in pe:
        m = (T["e"] == e) & (T["sample"] == "movement") & T["alive"]
        t = np.sort(T["t_rep"][m])
        d = np.diff(t)
        dts.append(d[d < 250])
        u = np.unique(T["yaw"][m])
        s = np.diff(u)
        ystep.append(s[s > 0].min() if s.size else np.nan)
    d = np.concatenate(dts)
    ev = L.events
    kinds = Counter(ev["kind"].tolist())
    st = Counter(L.state["field"].tolist())
    return {"match": L.head["match"], "session": L.head.get("session"),
            "tick_dt_ms": {"p5": float(np.percentile(d, 5)), "p50": float(np.percentile(d, 50)),
                           "p95": float(np.percentile(d, 95)), "p99": float(np.percentile(d, 99)),
                           "share_le_8": round(float((d <= 8.0).mean()), 4)},
            "yaw_step_deg_min": float(np.nanmin(ystep)),
            "ticks_columns": sorted(T.keys()), "event_kinds": dict(kinds),
            "damage_detail_keys": sorted(json.loads(ev["detail"][np.flatnonzero(ev["kind"] == "damage")[0]]).keys()),
            "state_fields_top": dict(Counter({k: v for k, v in st.items() if not k.startswith("charges:")}).most_common(8))}


# ----------------------------------------------------------------- per-duel rows

def _unit(yaw, pitch):
    y, p = np.radians(yaw), np.radians(((np.asarray(pitch, float) + 180.0) % 360.0) - 180.0)
    return np.stack([np.cos(p) * np.cos(y), np.cos(p) * np.sin(y), np.sin(p)], -1)


def _angle(u, d):
    n = np.linalg.norm(d, axis=-1)
    c = (u * d).sum(-1) / np.maximum(n, 1e-9)
    return np.degrees(np.arccos(np.clip(c, -1.0, 1.0)))


def _track_at(P: dict, t: np.ndarray, max_gap: float = 250.0) -> dict:
    tt = np.asarray(P["t"], float)
    i = np.clip(np.searchsorted(tt, t, side="right"), 1, tt.size - 1)
    t0, t1 = tt[i - 1], tt[i]
    ok = (t >= t0) & (t <= t1) & ((t1 - t0) <= max_gap)
    w = np.clip((t - t0) / np.where(t1 > t0, t1 - t0, 1.0), 0.0, 1.0)
    out = {}
    for k in ("x", "y", "z"):
        v = np.asarray(P[k], float)
        out[k] = np.where(ok, v[i - 1] * (1 - w) + v[i] * w, np.nan)
    near = np.where(w < 0.5, i - 1, i)
    for k in ("yaw", "pitch"):
        v = np.asarray(P[k], float)
        out[k] = np.where(ok, v[near], np.nan)
    return out


def duel_rows(key: str) -> list[dict]:
    from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM, Occluders

    _refuse(key)
    match = _full(key)
    t0w = time.time()
    tl = ep.from_replay_layer(match)
    if tl.stamps.get("held_out"):
        raise SystemExit("the held-out replay is never read")
    occ = Occluders(tl.map)
    X = Extras(match)
    eps = [r for r in ep.read_episodes(match) if r.get("row") == "episode" and r.get("kind") == "duel"]
    team = {s.slot_id: s.team for s in tl.slots}
    hits_by = defaultdict(list)
    for h in X.hits:
        if h["by"] is not None:
            hits_by[(h["by"], h["to"])].append(h)
    for k in hits_by:
        hits_by[k].sort(key=lambda h: h["t"])
    rows = []
    for e in eps:
        if e["outcome"].get("result") != "killed" or not e.get("sight"):
            continue
        a, b = e["participants"]["a"], e["participants"]["b"]
        if team.get(a) == team.get(b) or a not in tl.tracks or b not in tl.tracks:
            continue
        on, tk = float(e["t_start_ms"]), float(e["t_end_ms"])
        G = np.arange(on - BACK_MS, tk + KILL_SLACK_MS + 0.5 * GRID_MS, GRID_MS)
        Pa, Pb = _track_at(tl.tracks[a], G), _track_at(tl.tracks[b], G)
        Pa_r, Pb_r = _track_at(tl.tracks[a], G - RENDER_MS), _track_at(tl.tracks[b], G - RENDER_MS)
        alive = ep.alive_from_events(tl, G)
        ia = [s.slot_id for s in tl.slots].index(a)
        ib = [s.slot_id for s in tl.slots].index(b)
        both = alive[ia] & alive[ib]
        eye = {}
        for nm, P in (("a", Pa), ("b", Pb)):
            c = np.stack([P["x"], P["y"], P["z"]], -1)
            eye[nm] = c + np.array([0, 0, EYE_ABOVE_CENTRE_CM])
        fin = np.isfinite(eye["a"]).all(1) & np.isfinite(eye["b"]).all(1) & both
        clear = np.zeros(G.size, bool)
        idx = np.flatnonzero(fin)
        if idx.size:
            clear[idx] = ~occ.blocked(eye["a"][idx], eye["b"][idx])
        dist = np.linalg.norm(eye["a"] - eye["b"], axis=1)
        win = G >= on - PRE_MS
        # exposure: the clear run that holds the first clear sample inside the window
        first_in = np.flatnonzero(clear & win)
        expo_i, censored = None, None
        if first_in.size:
            k = int(first_in[0])
            while k > 0 and clear[k - 1]:
                k -= 1
            expo_i, censored = k, (k == 0)
        killer = e["outcome"]["killer"]
        base = {"match": match, "duel": e["episode_id"], "round": e["round"], "onset": on, "kill": tk,
                "killer": killer, "first_hitter": e.get("first_hitter"), "first_seer": e.get("first_seer"),
                "opening": bool(e.get("opening")), "wallbang": bool(e.get("wallbang")),
                "kill_class": e.get("kill_class")}
        for me, op, Pm, Po_r, em, eo in (("a", "b", Pa, Pb_r, a, b), ("b", "a", Pb, Pa_r, b, a)):
            r = dict(base, who=em, opp=eo, won=(killer == em), team=team.get(em))
            u = _unit(Pm["yaw"], Pm["pitch"])
            tgt = np.stack([Po_r["x"], Po_r["y"], Po_r["z"] + EYE_ABOVE_CENTRE_CM], -1)
            tgt0 = eye[op]
            err = _angle(u, tgt - eye[me])
            err0 = _angle(u, tgt0 - eye[me])
            yaw_err = np.abs(((np.degrees(np.arctan2(tgt[:, 1] - eye[me][:, 1], tgt[:, 0] - eye[me][:, 0]))
                               - Pm["yaw"] + 180.0) % 360.0) - 180.0)
            tol = np.degrees(np.arctan2(HEAD_CM, np.maximum(dist, 1.0)))
            r["exposure_censored"] = censored
            if expo_i is not None:
                tx = float(G[expo_i])
                r["exposure"] = tx
                r["dist_m"] = round(float(dist[expo_i]) / 100.0, 2)
                r["err_deg"] = round(float(err[expo_i]), 3) if np.isfinite(err[expo_i]) else None
                r["err0_deg"] = round(float(err0[expo_i]), 3) if np.isfinite(err0[expo_i]) else None
                r["yaw_err_deg"] = round(float(yaw_err[expo_i]), 3) if np.isfinite(yaw_err[expo_i]) else None
                for dly in (0.0, 100.0):
                    Pq = _track_at(tl.tracks[eo], G[expo_i:expo_i + 1] - dly)
                    tq = np.array([Pq["x"][0], Pq["y"][0], Pq["z"][0] + EYE_ABOVE_CENTRE_CM])
                    r[f"err_deg_d{int(dly)}"] = round(float(_angle(u[expo_i], tq - eye[me][expo_i])), 3) \
                        if np.isfinite(tq).all() and np.isfinite(u[expo_i]).all() else None
                after = np.flatnonzero((np.arange(G.size) >= expo_i) & (G <= tk + KILL_SLACK_MS) & (err <= tol))
                r["on_target_ms"] = float(G[after[0]] - tx) if after.size else None
                sh = X.shots.get(em, np.array([]))
                post = sh[(sh >= tx) & (sh <= tk + KILL_SLACK_MS)]
                r["prefire"] = bool(((sh >= tx - PREFIRE_MS) & (sh < tx)).any())
                r["shots_to_kill"] = int(post.size)
                if post.size:
                    f = float(post[0])
                    r["first_shot_ms"] = f - tx
                    hh = [h for h in hits_by.get((em, eo), []) if abs(h["t"] - f) <= HIT_TOL_MS and h["gun"]]
                    r["first_hit"] = bool(hh)
                    r["first_region"] = hh[0]["region"] if hh else None
                    r["first_zoomed"] = hh[0]["zoomed"] if hh else None
                    Ps = _track_at(tl.tracks[em], np.array([f - SPEED_DT_MS, f + SPEED_DT_MS]))
                    sp = math.hypot(Ps["x"][1] - Ps["x"][0], Ps["y"][1] - Ps["y"][0]) / (2 * SPEED_DT_MS / 1000.0)
                    r["speed_cms"] = round(sp, 1) if np.isfinite(sp) else None
                    hit_post = [h for h in hits_by.get((em, eo), []) if tx <= h["t"] <= tk + KILL_SLACK_MS and h["gun"]]
                    r["hits_to_kill"] = len(hit_post)
                    r["heads_to_kill"] = sum(h["region"] == "head" for h in hit_post)
                else:
                    r["first_shot_ms"] = None
                bl = X.blinds.get(em, [])
                r["blinded"] = any(s0 <= tx <= s1 for s0, s1 in bl)
                # flash then peek: the opponent's latest blind onset at or before exposure,
                # and whether exposure falls inside that blind
                ob = [(s0, s1) for s0, s1 in X.blinds.get(eo, []) if s0 <= tx]
                r["opp_blinded"] = bool(ob) and ob[-1][0] <= tx <= ob[-1][1]
                r["opp_blind_onset_before_ms"] = float(tx - ob[-1][0]) if r["opp_blinded"] else None
            rows.append(r)
    print(f"{match[:8]}: {len(rows) // 2} kill duels in {time.time() - t0w:.0f} s", flush=True)
    return rows


# ----------------------------------------------------------------- value

def _boot_share(pairs: list[tuple[str, int]], n_boot: int = 1000, seed: int = 7) -> dict:
    """Share of y=1 over (match, y) pairs with a match bootstrap interval."""
    if not pairs:
        return {"n": 0}
    ms = sorted({m for m, _ in pairs})
    mi = {m: i for i, m in enumerate(ms)}
    k = np.zeros(len(ms))
    n = np.zeros(len(ms))
    for m, y in pairs:
        n[mi[m]] += 1
        k[mi[m]] += y
    rng = np.random.default_rng(seed)
    W = rng.multinomial(len(ms), np.full(len(ms), 1.0 / len(ms)), size=n_boot)
    bs = (W @ k) / np.maximum(W @ n, 1)
    return {"share": round(float(k.sum() / n.sum()), 4), "ci_lo": round(float(np.percentile(bs, 2.5)), 4),
            "ci_hi": round(float(np.percentile(bs, 97.5)), 4), "n": int(n.sum()), "matches": len(ms)}


def _band(d):
    return "lt10" if d < 10 else ("10to20" if d < 20 else "ge20")


def _tercile_diff(rows: list[dict], key: str, lower_better: bool) -> dict:
    from coaching_questions import _stratified
    v = np.array([r[key] for r in rows], float)
    lo, hi = np.percentile(v, [100 / 3, 200 / 3])
    out = []
    for r, x in zip(rows, v):
        if lo < x < hi or x == lo == hi:
            continue
        best = (x <= lo) if lower_better else (x >= hi)
        out.append({"m": r["match"], "z": _band(r.get("dist_m") or 0), "a": best, "y": r["won"]})
    s = _stratified(out)
    s.update({"t_lo": round(float(lo), 3), "t_hi": round(float(hi), 3)})
    return s


def _paired(rows: list[dict], key: str, lower_better: bool, tie: float = 0.0) -> dict:
    by = defaultdict(list)
    for r in rows:
        by[(r["match"], r["duel"])].append(r)
    pairs = []
    for (m, _d), rr in by.items():
        if len(rr) != 2 or any(r.get(key) is None for r in rr):
            continue
        x0, x1 = rr[0][key], rr[1][key]
        if abs(x0 - x1) <= tie:
            continue
        better = rr[0] if ((x0 < x1) == lower_better) else rr[1]
        pairs.append((m, int(better["won"])))
    return _boot_share(pairs)


def _binary(rows: list[dict], key: str) -> dict:
    from coaching_questions import _stratified
    out = [{"m": r["match"], "z": _band(r.get("dist_m") or 0), "a": bool(r[key]), "y": r["won"]}
           for r in rows if r.get(key) is not None]
    return _stratified(out)


def value(paths: list[Path]) -> dict:
    rows = []
    for p in paths:
        rows += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if not r["match"].startswith(HELD_OUT_PREFIX)]
    res = {"version": VERSION, "matches": len({r["match"] for r in rows}), "participants": len(rows),
           "duels": len({(r["match"], r["duel"]) for r in rows})}
    ex = [r for r in rows if r.get("exposure") is not None and not r.get("exposure_censored")]
    res["exposed_uncensored"] = len(ex)
    res["exposure_censored"] = sum(1 for r in rows if r.get("exposure_censored"))
    res["no_exposure"] = sum(1 for r in rows if r.get("exposure") is None)
    # EQ1 crosshair placement
    ce = [r for r in ex if r.get("err_deg") is not None]
    e = np.array([r["err_deg"] for r in ce])
    res["placement"] = {"n": len(ce), "p25": round(float(np.percentile(e, 25)), 2), "p50": round(float(np.median(e)), 2),
                        "p75": round(float(np.percentile(e, 75)), 2),
                        "yaw_p50": round(float(np.median([r["yaw_err_deg"] for r in ce if r.get("yaw_err_deg") is not None])), 2),
                        "p50_d0": round(float(np.nanmedian([r["err_deg_d0"] if r.get("err_deg_d0") is not None else np.nan for r in ce])), 2),
                        "p50_d100": round(float(np.nanmedian([r["err_deg_d100"] if r.get("err_deg_d100") is not None else np.nan for r in ce])), 2),
                        "paired": _paired(ce, "err_deg", True), "tercile": _tercile_diff(ce, "err_deg", True)}
    # EQ10: placement degraded to yaw only (Y0), then to the minimap cone's measured error (Y1)
    errs = [np.load(p) for p in sorted(OUT.glob("selfface_err_*.npy"))]
    y0 = [dict(r, y0=r["yaw_err_deg"]) for r in ce if r.get("yaw_err_deg") is not None]
    res["placement_yaw_only"] = {"n": len(y0), "paired": _paired(y0, "y0", True), "tercile": _tercile_diff(y0, "y0", True)}
    if errs:
        pool = np.concatenate(errs)
        rng = np.random.default_rng(7)
        y1 = []
        for r in y0:
            # the yaw error is unsigned; recover its sign from nothing, so add the cone's signed error to a random sign
            s = rng.choice((-1.0, 1.0))
            v = abs((((s * r["y0"] + rng.choice(pool)) + 180.0) % 360.0) - 180.0)
            y1.append(dict(r, y1=v))
        res["placement_cone"] = {"n": len(y1), "error_pool": int(pool.size),
                                 "paired": _paired(y1, "y1", True), "tercile": _tercile_diff(y1, "y1", True)}
    # EQ2 reaction
    rx = [r for r in ex if r.get("first_shot_ms") is not None]
    f = np.array([r["first_shot_ms"] for r in rx])
    res["reaction"] = {"n": len(rx), "p25": float(np.percentile(f, 25)), "p50": float(np.median(f)),
                       "p75": float(np.percentile(f, 75)),
                       "shot_share": round(len(rx) / max(len(ex), 1), 4),
                       "prefire_share": round(float(np.mean([bool(r.get("prefire")) for r in ex])), 4),
                       "paired": _paired(rx, "first_shot_ms", True), "tercile": _tercile_diff(rx, "first_shot_ms", True),
                       "prefire": _binary(ex, "prefire")}
    # EQ3 first bullet
    fb = [r for r in rx if r.get("first_hit") is not None]
    hit = [r for r in fb if r["first_hit"]]
    reg = Counter(r["first_region"] for r in hit)
    res["first_bullet"] = {"n": len(fb), "hit_share": round(len(hit) / max(len(fb), 1), 4),
                           "regions": dict(reg), "head_share_of_hits": round(reg.get("head", 0) / max(len(hit), 1), 4),
                           "hit": _binary(fb, "first_hit"),
                           "head": _binary([dict(r, head=(r.get("first_region") == "head")) for r in fb], "head")}
    # EQ4 counter-strafe
    sp = [r for r in rx if r.get("speed_cms") is not None]
    s = np.array([r["speed_cms"] for r in sp])
    st = [dict(r, still=True) for r in sp if r["speed_cms"] < STILL_CMS] + \
         [dict(r, still=False) for r in sp if r["speed_cms"] > MOVING_CMS]
    res["speed_at_shot"] = {"n": len(sp), "p50": round(float(np.median(s)), 1),
                            "still_share": round(float((s < STILL_CMS).mean()), 4),
                            "moving_share": round(float((s > MOVING_CMS).mean()), 4),
                            "still_vs_moving": _binary(st, "still"),
                            "first_hit_still": round(float(np.mean([r["first_hit"] for r in sp if r["speed_cms"] < STILL_CMS and r.get("first_hit") is not None])), 4),
                            "first_hit_moving": round(float(np.mean([r["first_hit"] for r in sp if r["speed_cms"] > MOVING_CMS and r.get("first_hit") is not None])), 4)}
    # EQ5 first hitter
    fh = [r for r in rows if r.get("first_hitter") in (r["who"],)]
    res["first_hitter"] = _boot_share([(r["match"], int(r["won"])) for r in fh])
    # EQ6 adjustment
    ot = [r for r in ex if r.get("on_target_ms") is not None]
    o = np.array([r["on_target_ms"] for r in ot])
    res["adjustment"] = {"n": len(ot), "p50": float(np.median(o)) if o.size else None,
                         "p25": float(np.percentile(o, 25)) if o.size else None,
                         "p75": float(np.percentile(o, 75)) if o.size else None,
                         "reached_winners": round(float(np.mean([r.get("on_target_ms") is not None for r in ex if r["won"]])), 4),
                         "reached_losers": round(float(np.mean([r.get("on_target_ms") is not None for r in ex if not r["won"]])), 4),
                         "at_exposure_share": round(float(np.mean([r.get("on_target_ms") == 0.0 for r in ex])), 4),
                         "paired": _paired(ot, "on_target_ms", True)}
    # EQ7 blinded
    bl = [r for r in ex if r.get("blinded") is not None]
    res["blinded"] = {"n": len(bl), "share": round(float(np.mean([r["blinded"] for r in bl])), 4),
                      "won_blinded": _boot_share([(r["match"], int(r["won"])) for r in bl if r["blinded"]]),
                      "diff": _binary(bl, "blinded")}
    # EQ7b: duels with exactly one participant blinded at exposure; the unblinded side's win share
    byd = defaultdict(list)
    for r in bl:
        byd[(r["match"], r["duel"])].append(r)
    one = [(m, int(next(x for x in rr if not x["blinded"])["won"]))
           for (m, _d), rr in byd.items() if len(rr) == 2 and sum(x["blinded"] for x in rr) == 1]
    res["blinded"]["unblinded_wins"] = _boot_share(one)
    # EQ7c: flash then peek, peeking a blinded opponent; timing after his blind onset
    fp = [r for r in bl if r.get("opp_blinded")]
    ft = np.array([r["opp_blind_onset_before_ms"] for r in fp])
    res["flash_peek"] = {"n": len(fp), "onset_to_exposure_p25": float(np.percentile(ft, 25)) if ft.size else None,
                         "onset_to_exposure_p50": float(np.median(ft)) if ft.size else None,
                         "onset_to_exposure_p75": float(np.percentile(ft, 75)) if ft.size else None,
                         "won": _boot_share([(r["match"], int(r["won"])) for r in fp]),
                         "early_won": _boot_share([(r["match"], int(r["won"])) for r in fp if r["opp_blind_onset_before_ms"] <= 500]),
                         "late_won": _boot_share([(r["match"], int(r["won"])) for r in fp if r["opp_blind_onset_before_ms"] > 500])}
    # spray: hits per shot to the kill for the winner
    w = [r for r in rx if r["won"] and r.get("shots_to_kill")]
    res["spray"] = {"n": len(w), "winner_hits_per_shot_p50": round(float(np.median([r["hits_to_kill"] / r["shots_to_kill"] for r in w])), 4),
                    "winner_shots_p50": float(np.median([r["shots_to_kill"] for r in w]))}
    return res


# ----------------------------------------------------------------- ladder

def ladder(n_boot: int = 1000) -> dict:
    import pyarrow.parquet as pq
    from coaching_questions import _stratified
    base = Path(DEFAULT_STORE) / "external" / "ladder" / "henrikdev" / "v4"
    M = pq.read_table(base / "parsed" / "ladder-parse-0.2.0" / "matches.parquet").to_pydict()
    keep = {m for m, h in zip(M["match_id"], M["holdout"]) if not h}
    seen, rows = set(), []
    for p in sorted((base / "raw").glob("*-history.json.gz")):
        d = json.load(gzip.open(p))
        for m in d.get("data") or []:
            mid = m["metadata"].get("match_id")
            if mid not in keep or mid in seen:
                continue
            seen.add(mid)
            for r in m.get("rounds") or []:
                wt = r.get("winning_team")
                for s in r.get("stats") or []:
                    st = s.get("stats") or {}
                    h, b, lg = st.get("headshots") or 0, st.get("bodyshots") or 0, st.get("legshots") or 0
                    n = h + b + lg
                    if n < 3:
                        continue
                    rows.append({"m": mid, "hs": h / n, "n": n, "y": s["player"]["team"] == wt})
    hs = np.array([r["hs"] for r in rows])
    lo, hi = np.percentile(hs, [100 / 3, 200 / 3])
    out = [{"m": r["m"], "z": ("3-5" if r["n"] <= 5 else ("6-9" if r["n"] <= 9 else "10+")),
            "a": r["hs"] >= hi, "y": r["y"]} for r in rows if not (lo < r["hs"] < hi)]
    if lo == hi:
        out = [{"m": r["m"], "z": ("3-5" if r["n"] <= 5 else ("6-9" if r["n"] <= 9 else "10+")),
                "a": r["hs"] > hi, "y": r["y"]} for r in rows]
    res = _stratified(out, n_boot=n_boot)
    res.update({"matches_used": len(seen), "player_rounds": len(rows), "hs_p50": round(float(np.median(hs)), 4),
                "t_lo": round(float(lo), 4), "t_hi": round(float(hi), 4)})
    return res


# ----------------------------------------------------------------- capture

def selfface(session: str, shift_ms: float = 0.0) -> dict:
    """team_vision self facing (teardrop, not interpolated) against the replay's
    self facing_px at the frame's replay time (replay layer `frames`), moved by
    `shift_ms` on the replay clock and read from the self's ticks (a clock
    diagnostic, as in `hudfire`)."""
    from reticle.replay_layer import load
    _refuse(session)
    L = load(session)
    E = L.entities
    me = [e for e in L.players() if E["is_me"][e] is True or E["is_me"][e] == "True"]
    if len(me) != 1:
        return {"session": session, "refused": "no single is_me player"}
    me = me[0]
    Fr = L.frames
    m = Fr["e"] == me
    if shift_ms:
        tr = L.track(me)
        tt = np.asarray(tr["t_rep"], float)
        q = np.clip(np.searchsorted(tt, Fr["t_rep"][m] + shift_ms), 1, tt.size - 1)
        q = np.where(np.abs(tt[q - 1] - (Fr["t_rep"][m] + shift_ms)) < np.abs(tt[q] - (Fr["t_rep"][m] + shift_ms)), q - 1, q)
        fp = np.asarray(tr["facing_px"], float)[q]
    else:
        fp = Fr["facing_px"][m]
    fi = dict(zip(Fr["frame_idx"][m].tolist(), np.asarray(fp, float).tolist()))
    al = dict(zip(Fr["frame_idx"][m].tolist(), Fr["alive"][m].tolist()))
    p = Path(DEFAULT_STORE) / "events" / "team_vision" / f"{session}.jsonl"
    err, n_rows, version = [], 0, None
    with p.open(encoding="utf-8") as fh:
        for line in fh:
            if '"self"' not in line:
                if version is None and '"version"' in line:
                    try:
                        version = json.loads(line).get("version")
                    except Exception:
                        pass
                continue
            r = json.loads(line)
            if r.get("kind") != "frame":
                continue
            for ic in r.get("icons") or []:
                if ic.get("role") != "self" or ic.get("facing") is None or ic.get("interpolated"):
                    continue
                pose = ic.get("pose") or {}
                if pose.get("origin") != "teardrop":
                    continue
                f = r.get("frame_idx")
                if f not in fi or fi[f] is None or not al.get(f) or not np.isfinite(fi[f]):
                    continue
                n_rows += 1
                err.append(((ic["facing"] - fi[f] + 180.0) % 360.0) - 180.0)
    e = np.array(err)
    if e.size == 0:
        return {"session": session, "n": 0, "team_vision": version}
    if not shift_ms:
        np.save(OUT / f"selfface_err_{session}.npy", e)
    a = np.abs(e)
    return {"session": session, "shift_ms": shift_ms, "team_vision": version, "n": int(e.size),
            "signed_p50": round(float(np.median(e)), 3), "abs_p50": round(float(np.median(a)), 3),
            "abs_p90": round(float(np.percentile(a, 90)), 3), "flip_share": round(float((a > 90).mean()), 4),
            "within_2": round(float((a <= 2).mean()), 4), "within_0_57": round(float((a <= 0.57).mean()), 4)}


def hudfire(session: str, shift_ms: float = 0.0) -> dict:
    """Own gunfire from the 2 Hz HUD magazine drop (reserve held, both reads
    confident, at most 0.75 s apart, the player alive) against truth shots by
    the capturing player in the same interval, on the capture clock. `shift_ms`
    moves the truth shots: a diagnostic of the layer's clock for self events
    (its offset is fitted on killfeed deaths), never a fit for a figure."""
    import glob
    import pyarrow.parquet as pq
    from reticle.replay_layer import load
    _refuse(session)
    L = load(session)
    E = L.entities
    me = [e for e in L.players() if E["is_me"][e] is True or E["is_me"][e] == "True"]
    if len(me) != 1:
        return {"session": session, "refused": "no single is_me player"}
    subj = str(E["subject"][me[0]])
    a_ms = float(L.head["a_ms"])
    X = Extras(L.head["match"])
    sh = X.shots.get(subj, np.array([])) + a_ms + shift_ms
    f = glob.glob(str(Path(DEFAULT_STORE) / "l1" / "hud" / "date=*" / f"session={session}" / "hud.parquet"))
    H = pq.read_table(f[0], columns=["t_ms", "ammo_mag", "ammo_reserve", "bottom_confidence"]).to_pydict()
    t = np.array(H["t_ms"], float)
    o = np.argsort(t)
    t = t[o]
    mag = np.array([np.nan if v is None else v for v in H["ammo_mag"]], float)[o]
    res = np.array([np.nan if v is None else v for v in H["ammo_reserve"]], float)[o]
    bc = np.array([np.nan if v is None else v for v in H["bottom_confidence"]], float)[o]
    ok = (np.isfinite(mag[:-1]) & np.isfinite(mag[1:]) & (bc[:-1] >= 0.82) & (bc[1:] >= 0.82)
          & (np.diff(t) <= 750) & np.isfinite(res[:-1]) & (res[:-1] == res[1:]))
    rd = L.rounds
    live = np.zeros(t.size - 1, bool)
    for s0, s1 in zip(rd["tcap_buy_end"], rd["tcap_end"]):
        if np.isfinite(s0) and np.isfinite(s1):
            live |= (t[:-1] >= s0) & (t[1:] <= s1)
    ok &= live
    # alive only: a dead player's HUD shows the spectated teammate's ammo
    lv = L.lives
    mine = np.zeros(t.size - 1, bool)
    for e_, s0, s1 in zip(lv["e"], lv["tcap_open"], lv["tcap_close"]):
        if int(e_) == me[0] and np.isfinite(s0) and np.isfinite(s1):
            mine |= (t[:-1] >= s0) & (t[1:] <= s1)
    ok &= mine
    hud_fire = (mag[1:] < mag[:-1])[ok]
    n_true = np.array([((sh > a) & (sh <= b)).sum() for a, b in zip(t[:-1][ok], t[1:][ok])])
    truth_fire = n_true > 0
    drop = (mag[:-1] - mag[1:])[ok]
    tp = int((hud_fire & truth_fire).sum())
    return {"session": session, "shift_ms": shift_ms, "intervals": int(ok.sum()), "truth_fire": int(truth_fire.sum()),
            "hud_fire": int(hud_fire.sum()), "tp": tp,
            "recall": round(tp / max(int(truth_fire.sum()), 1), 4),
            "precision": round(tp / max(int(hud_fire.sum()), 1), 4),
            "count_exact": round(float((drop[truth_fire & hud_fire] == n_true[truth_fire & hud_fire]).mean()), 4)
            if tp else None,
            "self_shots": int(sh.size)}


def windows(session: str, pre_ms: float = 1000.0, post_ms: float = 500.0) -> dict:
    """The capturing player's engagement windows on truth: the union of his
    duel episodes (any outcome) widened by `pre_ms` and `post_ms`, as a share
    of his living time; the dense reader's duty cycle under the fidelity rule."""
    from reticle.replay_layer import load
    _refuse(session)
    L = load(session)
    E = L.entities
    me = [e for e in L.players() if E["is_me"][e] is True or E["is_me"][e] == "True"]
    if len(me) != 1:
        return {"session": session, "refused": "no single is_me player"}
    subj = str(E["subject"][me[0]])
    eps = [r for r in ep.read_episodes(L.head["match"]) if r.get("row") == "episode" and r.get("kind") == "duel"
           and subj in (r["participants"]["a"], r["participants"]["b"])]
    iv = sorted((r["t_start_ms"] - pre_ms, r["t_end_ms"] + post_ms) for r in eps)
    tot, cur = 0.0, None
    for a, b in iv:
        if cur is None or a > cur[1]:
            if cur:
                tot += cur[1] - cur[0]
            cur = [a, b]
        else:
            cur[1] = max(cur[1], b)
    if cur:
        tot += cur[1] - cur[0]
    lv = L.lives
    live = sum(float(c - o) for e_, o, c in zip(lv["e"], lv["t_open"], lv["t_close"])
               if int(e_) == me[0] and np.isfinite(o) and np.isfinite(c))
    return {"session": session, "duels": len(eps), "window_s": round(tot / 1000.0, 1),
            "alive_s": round(live / 1000.0, 1), "share_of_alive": round(tot / live, 4) if live else None}


# ----------------------------------------------------------------- record

def _rec(part: str, session: str, values: dict, context: dict | None = None) -> None:
    from reticle.metrics import record
    flat = {}

    def walk(p, o):
        if isinstance(o, dict):
            for k, v in o.items():
                walk(f"{p}.{k}" if p else k, v)
        elif isinstance(o, (list, tuple)) and len(o) == 2 and p.endswith("ci"):
            flat[p + "_lo"], flat[p + "_hi"] = o
        elif isinstance(o, (int, float, bool)) and o is not None:
            flat[p] = o
    walk("", values)
    record("execution_questions", part=part, session=session, values=flat,
           deps={"version": VERSION, "episodes": ep.EPISODES_VERSION},
           context={"task": TASK, "flatten": "intervals as ci_lo/ci_hi", **(context or {})})


def main(argv=None) -> int:
    _idle()
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv else "help"
    rec = "--record" in argv
    argv = [a for a in argv if a != "--record"]
    shift = 0.0
    if "--shift" in argv:
        i = argv.index("--shift")
        shift = float(argv[i + 1])
        del argv[i:i + 2]
    OUT.mkdir(parents=True, exist_ok=True)
    if cmd == "fields":
        r = fields(argv[0])
        print(json.dumps(r, indent=1))
        if rec:
            _rec("truth/fields", argv[0], {"tick_dt_ms": r["tick_dt_ms"], "yaw_step_deg_min": r["yaw_step_deg_min"]})
        return 0
    if cmd == "check":
        out = {}
        for k in (argv or replay_matches()):
            m = _full(k)
            out[m] = Extras(m).check()
            print(m[:8], out[m], flush=True)
        (OUT / "check.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        if rec:
            for m, v in out.items():
                _rec("truth/check", m[:8], v)
            sh = [v["explained_share"] for v in out.values() if v["explained_share"] is not None]
            hb = [v["head_bone_share"] for v in out.values() if v["head_bone_share"] is not None]
            lb = [v["leg_bone_share"] for v in out.values() if v["leg_bone_share"] is not None]
            _rec("truth/check", "pooled17", {"replays": len(out), "explained_share_min": min(sh),
                                             "explained_share_ge_0977": sum(x >= 0.977 for x in sh),
                                             "head_bone_share_min": min(hb), "leg_bone_share_min": min(lb),
                                             "multi_steps": sum(v["multi_steps"] for v in out.values()),
                                             "replays_with_blinds": sum(v["blinds"] > 0 for v in out.values()),
                                             "blinds": sum(v["blinds"] for v in out.values()),
                                             "gun_hits": sum(v["gun_hits"] for v in out.values()),
                                             "explained": sum(v["explained"] for v in out.values()),
                                             "shots": sum(v["shots"] for v in out.values())})
        return 0
    if cmd == "duels":
        for k in (argv or replay_matches()):
            m = _full(k)
            p = OUT / "duels" / f"{m}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            rows = duel_rows(m)
            p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return 0
    if cmd == "value":
        paths = sorted((OUT / "duels").glob("*.jsonl"))
        if argv and argv[0] == "dev":
            paths = [p for p in paths if p.name[:8] in DEV]
        r = value(paths)
        tag = "dev3" if (argv and argv[0] == "dev") else f"pooled{r['matches']}"
        (OUT / f"value_{tag}.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps(r, indent=1))
        if rec:
            for k, v in r.items():
                if isinstance(v, dict):
                    _rec(f"value/{k}", tag, v)
            _rec("value/meta", tag, {k: v for k, v in r.items() if not isinstance(v, dict)})
        return 0
    if cmd == "ladder":
        r = ladder()
        (OUT / "ladder.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(json.dumps(r, indent=1))
        if rec:
            _rec("value/ladder_head_share", "ladder", r)
        return 0
    if cmd == "windows":
        out = {s: windows(s) for s in (argv or DEV_SESSIONS)}
        for s, v in out.items():
            print(json.dumps(v))
            if rec and v.get("alive_s"):
                _rec("capture/windows", s, v)
        (OUT / "windows.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        return 0
    if cmd in ("selfface", "hudfire"):
        fn = (lambda s_: selfface(s_, shift)) if cmd == "selfface" else (lambda s_: hudfire(s_, shift))
        tag = f"{cmd}_shift{int(shift)}" if shift else cmd
        out = {}
        for s in (argv or DEV_SESSIONS):
            out[s] = fn(s)
            print(json.dumps(out[s]), flush=True)
            if rec and out[s].get("n", out[s].get("intervals")):
                _rec(f"capture/{tag}", s, out[s])
        (OUT / f"{tag}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        return 0
    print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
