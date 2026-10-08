r"""Why real enemy icons sit on a third of T1's drawn share.

A diagnosis over stored rows (task `enemy-lane-check-20261007`, rows EL1 in
the store's `notes/predictions.jsonl`). On the capturing team's live-phase
sight grid, joined to read `minimap_object` frames as
`real_reader_schedule.RealMatch.real_gate` joins them, it builds:

* the miss set: (sample, enemy) pairs T1 calls drawn (`Match.drawn`: a living
  capture-team player saw him within the last `P_MS`) with no stored enemy
  icon within `NEAR_CM` of his truth xy;
* the extra set: stored enemy icons with no T1-drawn living enemy within
  `NEAR_CM`, and no live child of any class within the gate (pending
  harness step 2);

and characterises both from stored rows: the T1 condition (concurrent sight
or the tail, ms since the last sight, which allies saw, their distance and
off-axis angle, whether the body centre or only the eye was clear, whether a
stored smoke disc crossed the sightline), ms since the round went live, the
nearest ally in widget px, the stored refused candidates, "?" marks and red
blobs near the enemy's projected place, and the hit rate of every bin
against the hits (drawn pairs with an icon within `NEAR_CM`).

`pixels` reads a stratified sample of at most `N_PER_MATCH` frames per match
from the minimap crop cache (no decode) and writes overlays of T1's projected
enemies, truth allies and the reader's stored candidates (accepted and
refused) beside the raw crop, with the drawn light (`lighting.lit_mask`)
tinted, for classification by eye.

    python prototypes/enemy_lane_check.py sets SESSION [SESSION ...]
    python prototypes/enemy_lane_check.py report
    python prototypes/enemy_lane_check.py pixels SESSION [SESSION ...]
    python prototypes/enemy_lane_check.py classes
    python prototypes/enemy_lane_check.py lit SESSION [SESSION ...]

`classes` weights the agent's by-eye classes of the montages
(`pixels/agent_classes.json` in the outputs; not player labels) by each
stratum's size and bootstraps over tiles; it also scores a post hoc candidate
draw rule (`t1_revised`). `lit` reads the drawn light about each drawn enemy
on the sample's frames only, a cross-reference for "nothing drawn".

Stored data only; the crop sample is the only pixel read. The held-out
capture (cea8ecbc94ab, replay bd7efa02) is refused before any row is read.
Outputs: `<store>/analysis/enemy-lane-check-20261007/`. Not wired
(`"wire": "no"`): an evaluation over replay truth.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import coaching_questions as cq  # noqa: E402
import real_reader_schedule as rrs  # noqa: E402
import replay_truth as rt  # noqa: E402
import entity_state as es  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "enemy-lane-check-0.1.0"
TASK = "enemy-lane-check-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
DEV = ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1")
NEAR_CM = 300.0          # an icon "at" an enemy
OFFSET_CM = 800.0        # an icon 3-8 m away: a possible position or clock offset
N_PER_MATCH = 60         # the pixel sample's cap per match
N_EXTRA = 12             # of which extra icons
SEED = 20261007


def refuse(name: str) -> None:
    rrs.refuse(name)


def _log(msg: str) -> None:
    print(msg, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    with (OUT / "run.log").open("a", encoding="utf-8") as f:
        f.write(time.strftime("%H:%M:%S ") + msg + "\n")


def _wrap_deg(a):
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


# ----------------------------------------------------------------- stored frame rows

def mo_frames(sid: str) -> list[dict]:
    """Each `minimap_object` frame row, in file order (the order
    `replay_truth.load_minimap_object` indexes), reduced to what this check
    reads: refused candidates, "?" marks, other red blobs and red X marks."""
    refuse(sid)
    out = []
    with (STORE / "events" / "minimap_object" / f"{sid}.jsonl").open(encoding="utf-8") as f:
        for line in f:
            r = json.loads(line)
            if r.get("kind") != "frame":
                continue
            if r.get("reason") is not None:
                out.append({"t": r["t_ms"], "fi": r["frame_idx"], "read": False})
                continue
            out.append({"t": r["t_ms"], "fi": r["frame_idx"], "read": True,
                        "enemies": [(e["x"], e["y"]) for e in r.get("enemies") or []],
                        "refused": [(x["x"], x["y"], f"{x['cls']}:{x['reason'].split(' ')[0].rstrip(':')}"
                                     + (f":{x['reason'].split(': ')[-1]}" if x["reason"].startswith(("teardrop", "owned"))
                                        else ""))
                                    for x in r.get("refused") or []],
                        "questions": [(q["x"], q["y"]) for q in r.get("questions") or []],
                        "red_other": [(q["x"], q["y"], q["reason"]) for q in r.get("red_other") or []],
                        "x_red": [(q["x"], q["y"]) for q in (r.get("x_marks") or {}).get("red") or []]})
    return out


def smoke_tracks(sid: str) -> np.ndarray:
    """Stored smoke tracks (capture ms first, end bound, cx, cy, r px)."""
    p = STORE / "events" / "smoke" / f"{sid}.jsonl"
    rows = []
    if p.is_file():
        with p.open(encoding="utf-8") as f:
            for line in f:
                if '"kind":"track"' not in line[:400] and '"kind": "track"' not in line[:400]:
                    continue
                r = json.loads(line)
                rows.append((r["first_ms"], r.get("end_bound_ms") or r["last_ms"], r["cx"], r["cy"], r["r"]))
    return np.asarray(rows, float).reshape(-1, 5)


def _seg_disc(ax, ay, bx, by, cx, cy, r):
    """True where segment a-b passes within r of c (broadcast)."""
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    with np.errstate(invalid="ignore", divide="ignore"):
        u = np.clip(((cx - ax) * dx + (cy - ay) * dy) / np.where(L2 > 0, L2, 1.0), 0.0, 1.0)
    px, py = ax + u * dx, ay + u * dy
    return np.hypot(px - cx, py - cy) <= r


# ----------------------------------------------------------------- the sets

def live_samples(M) -> tuple[np.ndarray, np.ndarray]:
    """The grid samples inside a round's live play (from `t_live` to the
    round's end, or the next round's start), and each one's `t_live`."""
    K = M.G.size
    live = np.zeros(K, bool)
    t_live_of = np.full(K, np.nan)
    for r in M.rounds:
        if r["t_live"] is not None:
            hi = r["t_end"] if r["t_end"] is not None else r["t_next"]
            m = (M.G_round == r["round"]) & (M.G >= r["t_live"]) & (M.G <= hi)
            live |= m
            t_live_of[m] = r["t_live"]
    return live, t_live_of


def build_sets(sid: str, M=None) -> dict:
    """The miss and extra sets of one development match, with attributes.
    `M` (default `real_reader_schedule.RealMatch(sid)`) supplies the draw
    rule through `M.drawn`; `t1_draw_rule` passes its own."""
    from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM
    from reticle.replay_source import to_px

    refuse(sid)
    if sid not in DEV:
        raise SystemExit(f"{sid}: not a development match of this check")
    t0 = time.time()
    M = M if M is not None else rrs.RealMatch(sid)
    E = M.enemy_reads()
    if E is None:
        raise SystemExit(f"{sid}: no minimap_object or enemy_track")
    drawn = M.drawn(M.C)
    (mf, to_m, _mpp), _why = es.world_frame(sid)
    upm = es.units_per_m()
    MO = E["MO"]
    FR = mo_frames(sid)
    if len(FR) != MO["frame_idx"].size or any(int(a["fi"]) != int(b) for a, b in zip(FR, MO["frame_idx"])):
        raise SystemExit(f"{sid}: frame order differs from load_minimap_object")
    K = M.G.size
    # the join, as real_gate builds it
    t_fr = M.to_rep(MO["t_ms"], rt.REMOTE_LAG_MS)
    g_cap = M.to_cap(M.G, rt.REMOTE_LAG_MS)
    gi = np.flatnonzero(M.in_spans(g_cap))
    inrun, J, _rate = rrs.join_runs(M.G[gi], t_fr)
    p_of = np.full(K, -1, np.int64)
    p_of[gi[inrun]] = J.index
    read_frame = np.array([r is None for r in MO["reason"]], bool)
    live, t_live_of = live_samples(M)
    valid = live & (p_of >= 0)
    valid[valid] = read_frame[p_of[valid]]
    alive = M.tl0._alive_fn(M.G)
    ci, ei = M.ci, M.ei
    me = M.sid.index(M.me)
    scale = float(json.loads(open(STORE / "events" / "minimap_object" / f"{sid}.jsonl",
                                  encoding="utf-8").readline())["scale"])
    # projections of truth into widget px
    PX, PY = to_px(mf, M.X, M.Y)
    # icons per frame position
    ip = E["icon_p"]
    nfr = MO["frame_idx"].size
    start = np.searchsorted(ip, np.arange(nfr + 1))

    def per_frame_pts(pts_of):
        """Flatten per-frame point lists onto the valid samples: (ks, x_cm, y_cm, tag)."""
        ks, xs, ys, tags = [], [], [], []
        for k in np.flatnonzero(valid):
            for q in pts_of(FR[p_of[k]]):
                ks.append(k)
                xs.append(q[0])
                ys.append(q[1])
                tags.append(q[2] if len(q) > 2 else "")
        ks = np.asarray(ks, np.int64)
        if ks.size:
            mx, my = to_m(np.asarray(xs, float), np.asarray(ys, float))
            return ks, mx * upm, my * upm, np.asarray(tags, dtype=object), np.asarray(xs), np.asarray(ys)
        z = np.zeros(0)
        return ks, z, z, np.zeros(0, dtype=object), z, z

    def min_dist(ks, x, y, rows):
        """min distance (cm) per (row j, sample k) to the points at k; inf where none."""
        D = np.full((len(rows), K), np.inf)
        for a, j in enumerate(rows):
            d = np.hypot(M.X[j, ks] - x, M.Y[j, ks] - y)
            d = np.where(np.isfinite(d), d, np.inf)
            np.minimum.at(D[a], ks, d)
        return D

    # accepted icons on valid samples
    vk = np.flatnonzero(valid)
    n_at = np.zeros(K, np.int64)
    n_at[vk] = start[p_of[vk] + 1] - start[p_of[vk]]
    ks_i = np.repeat(np.arange(K), n_at)
    off = np.arange(ks_i.size) - np.repeat(np.cumsum(n_at) - n_at, n_at)
    ic = np.repeat(start[np.clip(p_of, 0, None)], n_at) + off
    ix, iy = E["icon_x"][ic], E["icon_y"][ic]
    Dicon = min_dist(ks_i, ix, iy, list(ei))
    # refused and red candidates
    cand = {
        "refused": per_frame_pts(lambda fr: fr["refused"]),
        "question": per_frame_pts(lambda fr: fr["questions"]),
        "red_other": per_frame_pts(lambda fr: [(a, b, f"red_other:{c}") for a, b, c in fr["red_other"]]),
        "x_red": per_frame_pts(lambda fr: fr["x_red"]),
    }
    near_tags = {}
    for name, (ks, x, y, tags, _px, _py) in cand.items():
        if name == "refused":
            for tag in sorted(set(tags.tolist())):
                m = tags == tag
                near_tags[tag] = min_dist(ks[m], x[m], y[m], list(ei)) <= NEAR_CM
        else:
            near_tags[name if name != "red_other" else "red_other"] = (
                min_dist(ks, x, y, list(ei)) <= NEAR_CM)
    # sight attributes
    vis = M.sees[ci].any(axis=0)                       # (S, K)
    newr = np.r_[True, M.G_round[1:] != M.G_round[:-1]]
    rstart = np.maximum.accumulate(np.where(newr, np.arange(K), 0))
    last = np.maximum.accumulate(np.where(vis, np.arange(K)[None, :], -1), axis=1)
    last = np.where(last >= rstart[None, :], last, -1)
    # the sight run holding the last sight: its onset and its end
    prev = np.concatenate([np.zeros((vis.shape[0], 1), bool), vis[:, :-1]], axis=1) & ~newr[None, :]
    onset = np.maximum.accumulate(np.where(vis & ~prev, np.arange(K)[None, :], -1), axis=1)
    nxt_ = np.concatenate([vis[:, 1:], np.zeros((vis.shape[0], 1), bool)], axis=1) & ~np.r_[newr[1:], True][None, :]
    endi = np.where(vis & ~nxt_, np.arange(K)[None, :], K)
    endi = np.minimum.accumulate(endi[:, ::-1], axis=1)[:, ::-1]
    dr = drawn[ei] & valid[None, :]
    dead = ~alive[ei]
    hit = dr & (Dicon <= NEAR_CM)
    miss = dr & (Dicon > NEAR_CM)
    # pairs
    rows = []
    smokes = smoke_tracks(sid)
    for kind, mask in (("hit", hit), ("miss", miss)):
        a, k = np.nonzero(mask)
        j = ei[a]
        kl = last[j, k]
        conc = vis[j, k]
        ok = kl >= 0
        klc = np.clip(kl, 0, None)
        seers = M.sees[ci][:, j, klc] & ok[None, :]          # (n_ci, P)
        dx = M.X[j, klc][None, :] - M.X[ci][:, klc]
        dy = M.Y[j, klc][None, :] - M.Y[ci][:, klc]
        dist = np.where(seers, np.hypot(dx, dy), np.inf)
        ang = np.abs(_wrap_deg(np.degrees(np.arctan2(dy, dx)) - M.YAW[ci][:, klc]))
        ang = np.where(seers, ang, np.inf)
        # centre visible from the nearest seer's eye (the eye-only case)
        sn = np.argmin(dist, axis=0)
        s_idx = ci[sn]
        eye = np.stack([M.X[s_idx, klc], M.Y[s_idx, klc], M.Z[s_idx, klc] + EYE_ABOVE_CENTRE_CM], 1)
        cen = np.stack([M.X[j, klc], M.Y[j, klc], M.Z[j, klc]], 1)
        cblk = M.occ.blocked(eye, cen) if eye.shape[0] else np.zeros(0, bool)
        # stored smoke on the nearest seer's sightline at the last sight
        tcap = M.to_cap(M.G[klc], rt.REMOTE_LAG_MS)
        smoked = np.zeros(j.size, bool)
        if smokes.size and j.size:
            act = (smokes[None, :, 0] <= tcap[:, None]) & (tcap[:, None] <= smokes[None, :, 1])
            sm = _seg_disc(PX[s_idx, klc][:, None], PY[s_idx, klc][:, None],
                           PX[j, klc][:, None], PY[j, klc][:, None],
                           smokes[None, :, 2], smokes[None, :, 3], smokes[None, :, 4])
            smoked = (act & sm).any(axis=1)
        # nearest living ally and other drawn enemy in px at k
        apx = np.where(alive[ci][:, k], np.hypot(PX[ci][:, k] - PX[j, k], PY[ci][:, k] - PY[j, k]), np.inf)
        oth = np.where((drawn[ei][:, k] & alive[ei][:, k]) & (ei[:, None] != j[None, :]),
                       np.hypot(PX[ei][:, k] - PX[j, k], PY[ei][:, k] - PY[j, k]), np.inf)
        for q in range(j.size):
            kk = int(k[q])
            near = sorted(t for t, D in near_tags.items() if D[a[q], kk])
            rows.append({
                "set": kind, "k": kk, "j": int(j[q]), "agent": M.agent.get(M.sid[j[q]]),
                "round": int(M.G_round[kk]), "t_rep": round(float(M.G[kk]), 1),
                "t_cap": round(float(MO["t_ms"][p_of[kk]]), 1), "frame_idx": int(MO["frame_idx"][p_of[kk]]),
                "enemy_dead": bool(dead[a[q], kk]), "concurrent": bool(conc[q]),
                "ms_since_sight": None if kl[q] < 0 else round(float(M.G[kk] - M.G[kl[q]]), 1),
                "ms_since_onset": None if kl[q] < 0 else round(float(M.G[kk] - M.G[onset[j[q], kl[q]]]), 1),
                "run_ms": None if kl[q] < 0 else round(float(M.G[min(endi[j[q], kl[q]], K - 1)]
                                                             - M.G[onset[j[q], kl[q]]]) + cq.SIGHT_MS, 1),
                "seer_self": bool(seers[list(ci).index(me), q]) if me in ci else None,
                "n_seers": int(seers[:, q].sum()),
                "seer_dist_m": None if not np.isfinite(dist[:, q].min()) else round(float(dist[:, q].min()) / 100, 2),
                "seer_angle_deg": None if not np.isfinite(ang[:, q].min()) else round(float(ang[:, q].min()), 1),
                "centre_blocked": bool(cblk[q]), "smoke_on_line": bool(smoked[q]),
                "since_live_s": round(float(M.G[kk] - t_live_of[kk]) / 1000, 2),
                "ally_px": None if not np.isfinite(apx[:, q].min()) else round(float(apx[:, q].min()), 1),
                "other_enemy_px": None if not np.isfinite(oth[:, q].min()) else round(float(oth[:, q].min()), 1),
                "icon_m": None if not np.isfinite(Dicon[a[q], kk]) else round(float(Dicon[a[q], kk]) / 100, 2),
                "near": near, "px": [round(float(PX[j[q], kk]), 1), round(float(PY[j[q], kk]), 1)]})
    # extras: icons with no drawn living enemy within NEAR_CM
    ext = []
    dl = drawn[ei] & alive[ei]
    for q in range(ic.size):
        k = int(ks_i[q])
        d = np.hypot(M.X[ei, k] - ix[q], M.Y[ei, k] - iy[q])
        d = np.where(np.isfinite(d), d, np.inf)
        dd = np.where(dl[:, k], d, np.inf)
        if dd.min() <= NEAR_CM:
            continue
        da = np.where(alive[ci, k], np.hypot(M.X[ci, k] - ix[q], M.Y[ci, k] - iy[q]), np.inf)
        jn = int(np.argmin(d))
        j = int(ei[jn])
        # ms to the next sight of the nearest enemy, and since its last
        kl = int(last[j, k])
        nxt = np.flatnonzero(vis[j, k:] & (M.G_round[k:] == M.G_round[k]))
        ext.append({"set": "extra", "k": k, "round": int(M.G_round[k]), "t_rep": round(float(M.G[k]), 1),
                    "t_cap": round(float(MO["t_ms"][p_of[k]]), 1), "frame_idx": int(MO["frame_idx"][p_of[k]]),
                    "icon_px": [round(float(E["MO"]["enemy_x"][ic[q]]), 1), round(float(E["MO"]["enemy_y"][ic[q]]), 1)],
                    "nearest_enemy_m": None if not np.isfinite(d.min()) else round(float(d.min()) / 100, 2),
                    "nearest_enemy": j, "nearest_enemy_alive": bool(alive[j, k]),
                    "nearest_enemy_drawn": bool(drawn[j, k]),
                    "nearest_drawn_m": None if not np.isfinite(dd.min()) else round(float(dd.min()) / 100, 2),
                    "nearest_ally_m": None if not np.isfinite(da.min()) else round(float(da.min()) / 100, 2),
                    "ms_since_sight": None if kl < 0 else round(float(M.G[k] - M.G[kl]), 1),
                    "ms_to_sight": None if nxt.size == 0 else round(float(M.G[k + nxt[0]] - M.G[k]), 1),
                    "subj": int(E["icon_subj"][ic[q]]), "icon": int(ic[q])})
    # any-enemy sample level, for the share gap itself
    t1any = (drawn[ei] & valid[None, :]).any(axis=0)
    realany = n_at > 0
    t1conc = (vis[ei] & valid[None, :]).any(axis=0)
    t1alive = (drawn[ei] & alive[ei] & valid[None, :]).any(axis=0)
    lv = valid
    samples = {"valid_live_samples": int(lv.sum()),
               "t1_any": float(t1any[lv].mean()), "t1_any_alive": float(t1alive[lv].mean()),
               "t1_any_concurrent": float(t1conc[lv].mean()), "real_any": float(realany[lv].mean()),
               "t1_any_real_none": float((t1any & ~realany)[lv].mean()),
               "real_any_t1_none": float((realany & ~t1any)[lv].mean())}
    info = {"session": sid, "version": VERSION, "scale": scale, "team": M.C, "me": M.me,
            "minimap_object_version": MO["stamp"].get("minimap_object_version"),
            "clock": M.clock, "samples": samples, "secs": round(time.time() - t0, 1),
            "icons_valid": int(ic.size), "extras": len(ext),
            "px_per_m": float(mf.px_per_unit * upm),
            "widget_rotations": _widget_placement(sid)}
    # the join itself, for scorers over the same samples (question_acceptance):
    # each accepted icon on a valid sample (ks: sample, ic: icon index into
    # E's icons), the draw rule and the reads
    join = {"ks": ks_i, "ic": ic, "valid": valid, "p_of": p_of, "drawn": drawn,
            "alive": alive, "reads": E}
    return {"info": info, "pairs": rows, "extras": ext, "join": join}


def _widget_placement(sid: str) -> dict:
    """The stored widget placement (a variant placement could turn the widget,
    which the projection does not follow); `none` reads the baked placement."""
    with (STORE / "events" / "minimap_object" / f"{sid}.jsonl").open(encoding="utf-8") as f:
        head = json.loads(f.readline())
    return {"widget_placement": head.get("widget_placement")}


def run_sets(sessions: list[str]) -> int:
    cq._idle()
    OUT.mkdir(parents=True, exist_ok=True)
    for sid in sessions:
        refuse(sid)
        R = build_sets(sid)
        with (OUT / f"pairs_{sid}.jsonl").open("w", encoding="utf-8") as f:
            for r in R["pairs"] + R["extras"]:
                f.write(json.dumps(r) + "\n")
        (OUT / f"info_{sid}.json").write_text(json.dumps(R["info"], indent=1), encoding="utf-8")
        _log(f"{sid}: {json.dumps(R['info'])}")
    return 0


# ----------------------------------------------------------------- report over the sets

def _load(sid):
    refuse(sid)
    P = [json.loads(x) for x in (OUT / f"pairs_{sid}.jsonl").read_text(encoding="utf-8").splitlines()]
    return P


def _ci(k, n):
    """`metrics.wilson`, rounded; None for an empty bin."""
    from reticle.metrics import wilson
    if n == 0:
        return None
    lo, hi = wilson(k, n)
    return [round(lo, 4), round(hi, 4)]


#: Each miss pair's primary cause from stored rows, the first that holds
#: (order fixed after the first look at the bins, before any pixel was read).
PRIMARY = ("dead_tail", "question_near", "tail_over_500ms", "smoke_on_line", "refused_near",
           "offset_3_8m", "onset_under_250ms", "short_run_under_250ms", "unexplained")


def primary(r) -> str:
    if r["enemy_dead"]:
        return "dead_tail"
    if "question" in r["near"]:
        return "question_near"
    if not r["concurrent"] and r["ms_since_sight"] > 500:
        return "tail_over_500ms"
    if r["smoke_on_line"]:
        return "smoke_on_line"
    if any(t.startswith(("enemy:", "x_mark:")) for t in r["near"]):
        return "refused_near"
    if r["icon_m"] is not None and r["icon_m"] * 100 <= OFFSET_CM:
        return "offset_3_8m"
    if r.get("ms_since_onset") is not None and r["ms_since_onset"] < 250:
        return "onset_under_250ms"
    if r.get("run_ms") is not None and r["run_ms"] < 250:
        return "short_run_under_250ms"
    return "unexplained"


def _bins(P):
    """Hit rate and the miss share per attribute bin."""
    def cond(r):
        if r["enemy_dead"]:
            return "dead_tail"
        if r["concurrent"]:
            return "concurrent"
        s = r["ms_since_sight"]
        return "tail_0-250" if s <= 250 else "tail_250-500" if s <= 500 else "tail_500-1000"

    def b(v, edges, unit=""):
        if v is None:
            return "none"
        for e in edges:
            if v < e:
                return f"<{e}{unit}"
        return f">={edges[-1]}{unit}"

    keys = {
        "condition": cond,
        "seer": lambda r: "none" if r["seer_self"] is None else
        ("self+team" if r["seer_self"] and r["n_seers"] > 1 else "self" if r["seer_self"] else "team"),
        "seer_dist_m": lambda r: b(r["seer_dist_m"], (10, 20, 30, 45), "m"),
        "seer_angle_deg": lambda r: b(r["seer_angle_deg"], (15, 30, 40, 46, 52), "d"),
        "centre_blocked": lambda r: str(r["centre_blocked"]),
        "smoke_on_line": lambda r: str(r["smoke_on_line"]),
        "since_live_s": lambda r: b(r["since_live_s"], (15, 30, 60, 90), "s"),
        "ally_px": lambda r: b(r["ally_px"], (6, 12, 20), "px"),
        "other_enemy_px": lambda r: b(r["other_enemy_px"], (6, 12, 20), "px"),
        "near_refused": lambda r: ",".join(t for t in r["near"] if t.startswith(("enemy:", "x_mark:", "red_blob:"))) or "none",
        "near_question": lambda r: str("question" in r["near"]),
        "near_red_other": lambda r: str("red_other" in r["near"]),
        "offset_3_8m": lambda r: str(r["icon_m"] is not None and r["icon_m"] * 100 <= OFFSET_CM),
        "onset_ms_concurrent": lambda r: "n/a" if not r["concurrent"] or r["enemy_dead"] else
        b(r.get("ms_since_onset"), (125, 250, 500, 1000, 2000), "ms"),
        "run_ms_alive": lambda r: "n/a" if r["enemy_dead"] else b(r.get("run_ms"), (125, 250, 500, 1000, 2000), "ms"),
        "primary_if_miss": lambda r: primary(r),
    }
    out = {}
    nm = sum(r["set"] == "miss" for r in P)
    for name, f in keys.items():
        c = defaultdict(Counter)
        for r in P:
            if r["set"] in ("hit", "miss"):
                c[f(r)][r["set"]] += 1
        out[name] = {k: {"hit": v["hit"], "miss": v["miss"],
                         "hit_rate": round(v["hit"] / (v["hit"] + v["miss"]), 4),
                         "hit_rate_ci": _ci(v["hit"], v["hit"] + v["miss"]),
                         "miss_share": round(v["miss"] / nm, 4) if nm else None}
                     for k, v in sorted(c.items())}
    return out


def _extras(P):
    X = [r for r in P if r["set"] == "extra"]
    n_icons = None

    def cls(r):
        if r["nearest_enemy_m"] is not None and r["nearest_enemy_m"] <= 3:
            if not r["nearest_enemy_alive"]:
                return "near_dead_enemy"
            s, t = r["ms_since_sight"], r["ms_to_sight"]
            if t is not None and t <= 1000:
                return "near_undrawn_enemy:seen_within_1s_after"
            if s is not None and s <= 5000:
                return "near_undrawn_enemy:seen_1-5s_before"
            return "near_undrawn_enemy:unseen"
        if r["nearest_drawn_m"] is not None and r["nearest_drawn_m"] <= 8:
            return "drawn_enemy_3-8m"
        if r["nearest_ally_m"] is not None and r["nearest_ally_m"] <= 3:
            return "near_ally_only"
        return "nothing_within_3m"
    c = Counter(cls(r) for r in X)
    return {"extras": len(X), "classes": dict(c.most_common()), "_n_icons": n_icons}


def report() -> int:
    allP, summ = [], {"version": VERSION, "per_match": {}}
    for sid in DEV:
        p = OUT / f"pairs_{sid}.jsonl"
        if not p.is_file():
            continue
        P = _load(sid)
        info = json.loads((OUT / f"info_{sid}.json").read_text(encoding="utf-8"))
        nh = sum(r["set"] == "hit" for r in P)
        nm = sum(r["set"] == "miss" for r in P)
        ex = _extras(P)
        summ["per_match"][sid] = {"info": info, "hits": nh, "misses": nm,
                                  "miss_share_of_drawn": round(nm / (nh + nm), 4),
                                  "extras": ex, "extra_share_of_icons": round(ex["extras"] / info["icons_valid"], 4),
                                  "bins": _bins(P)}
        allP += P
    nh = sum(r["set"] == "hit" for r in allP)
    nm = sum(r["set"] == "miss" for r in allP)
    icons = sum(v["info"]["icons_valid"] for v in summ["per_match"].values())
    ex = _extras(allP)
    summ["pooled"] = {"hits": nh, "misses": nm, "miss_share_of_drawn": round(nm / (nh + nm), 4),
                      "extras": ex, "extra_share_of_icons": round(ex["extras"] / icons, 4),
                      "extra_ci": _ci(ex["extras"], icons), "bins": _bins(allP)}
    (OUT / "summary.json").write_text(json.dumps(summ, indent=1), encoding="utf-8")
    print(json.dumps(summ["pooled"], indent=1))
    return 0


# ----------------------------------------------------------------- the pixel sample

def choose(P: list[dict], rng) -> list[dict]:
    """At most N_PER_MATCH - N_EXTRA miss frames, equal per stratum
    (each miss pair's `primary` cause from stored rows), one per (round,
    enemy), then N_EXTRA extras; each pick carries its stratum's size."""
    M = [r for r in P if r["set"] == "miss"]
    st = defaultdict(list)
    for r in M:
        st[(primary(r),)].append(r)
    per = (N_PER_MATCH - N_EXTRA) // max(1, len(st))
    picks = []
    for key in sorted(st):
        rows = st[key]
        order = rng.permutation(len(rows))
        seen = set()
        got = []
        for i in order:
            r = rows[i]
            u = (r["round"], r["j"])
            if u in seen:
                continue
            seen.add(u)
            got.append(dict(r, stratum="/".join(key), stratum_n=len(rows)))
            if len(got) >= per:
                break
        picks += got
    X = [r for r in P if r["set"] == "extra"]
    order = rng.permutation(len(X))
    seen = set()
    for i in order:
        r = X[i]
        u = (r["round"], r["nearest_enemy"])
        if u in seen:
            continue
        seen.add(u)
        picks.append(dict(r, stratum="extra", stratum_n=len(X)))
        if sum(p["stratum"] == "extra" for p in picks) >= N_EXTRA:
            break
    return picks


def pixels(sid: str) -> int:
    import cv2

    from reticle import geometry, lighting
    from reticle.minimap_objects import object_context
    from reticle.replay_source import to_px
    from reticle.store import Store

    cq._idle()
    refuse(sid)
    P = _load(sid)
    rng = np.random.default_rng(SEED + int(sid[:6], 16) % 1000)
    picks = choose(P, rng)
    ctx, why = object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(f"{sid}: {why}")
    with np.load(geometry.path_of(sid, STORE)) as z:
        ref = lighting.reference(z)
    FR = {r["fi"]: r for r in mo_frames(sid)}
    # truth positions of every slot at each pick's grid sample
    M = rrs.RealMatch(sid)
    (mf, _to_m, _mpp), _ = es.world_frame(sid)
    PX, PY = to_px(mf, M.X, M.Y)
    drawn = M.drawn(M.C)
    alive = M.tl0._alive_fn(M.G)
    cache = ctx["cache"]
    x0, y0, x1, y1 = ctx["rect"]
    sc = ctx["scale"]
    half = int(round(40 * sc))
    Z = 4
    odir = OUT / "pixels" / sid
    odir.mkdir(parents=True, exist_ok=True)
    tiles, index = [], []
    held = np.asarray(cache.holds(), float)
    want = {}
    for p in picks:
        i = int(np.argmin(np.abs(held - p["t_cap"])))
        if abs(held[i] - p["t_cap"]) < 1.0:
            want[round(p["t_cap"], 1)] = float(held[i])
    byt = {}
    for smp in cache.samples(sorted(set(want.values())), rois=["minimap"]):
        byt[float(smp.t_ms)] = smp.frame[y0:y1, x0:x1].copy()
    for n, p in enumerate(picks):
        crop = byt.get(want.get(round(p["t_cap"], 1), -1.0))
        if crop is None:
            index.append(dict(p, tile=None, note="crop not held"))
            continue
        k = p["k"]
        cx, cy = (p["px"] if p["set"] == "miss" else p["icon_px"])
        lit = lighting.lit_mask(crop, ref) if ref is not None else np.zeros(crop.shape[:2], bool)
        yy, xx = np.mgrid[0:crop.shape[0], 0:crop.shape[1]]
        disc = np.hypot(xx - cx, yy - cy) <= 14 * sc
        known = ref.known & disc if ref is not None else disc & False
        lit_share = float(lit[known].mean()) if known.any() else None
        X0, Y0 = int(round(cx)) - half, int(round(cy)) - half
        pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT, value=(40, 40, 40))
        win = pad[Y0 + half:Y0 + 3 * half, X0 + half:X0 + 3 * half]
        litw = np.pad(lit, half)[Y0 + half:Y0 + 3 * half, X0 + half:X0 + 3 * half]
        raw = cv2.resize(win, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)  # display only
        ann = raw.copy()
        tint = np.zeros_like(ann)
        tint[cv2.resize(litw.astype(np.uint8), None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST) > 0] = (90, 60, 0)
        ann = cv2.addWeighted(ann, 1.0, tint, 0.6, 0)

        def P2(x, y):
            return int(round((x - X0) * Z)), int(round((y - Y0) * Z))
        pxm = float(mf.px_per_unit * es.units_per_m())
        for s in range(len(M.sid)):
            if not alive[s, k] or not np.isfinite(PX[s, k]):
                continue
            q = P2(PX[s, k], PY[s, k])
            if M.team[s] == M.C:
                cv2.circle(ann, q, 4, (255, 255, 0), -1)
            else:
                col = (255, 0, 255) if drawn[s, k] else (160, 160, 160)
                cv2.drawMarker(ann, q, col, cv2.MARKER_CROSS, 14, 2)
        if p["set"] == "miss":
            cv2.circle(ann, P2(cx, cy), int(3.0 * pxm * Z), (255, 0, 255), 1)
        fr = FR.get(p["frame_idx"], {})
        for ex, ey in fr.get("enemies", []):
            cv2.circle(ann, P2(ex, ey), int(10 * sc * Z), (0, 255, 0), 2)
        for ex, ey, tag in fr.get("refused", []):
            q = P2(ex, ey)
            cv2.drawMarker(ann, q, (0, 255, 255), cv2.MARKER_TILTED_CROSS, 12, 2)
            cv2.putText(ann, tag.split(":")[0][0] + (tag.split(":")[-1][:3] if "teardrop" in tag else "o"),
                        (q[0] + 6, q[1] - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1)
        for ex, ey in fr.get("questions", []):
            q = P2(ex, ey)
            cv2.rectangle(ann, (q[0] - 8, q[1] - 8), (q[0] + 8, q[1] + 8), (0, 140, 255), 2)
        for ex, ey, _w in fr.get("red_other", []):
            cv2.circle(ann, P2(ex, ey), 5, (0, 0, 255), 1)
        tile = np.concatenate([raw, np.full((raw.shape[0], 6, 3), 255, np.uint8), ann], axis=1)
        cap = np.full((44, tile.shape[1], 3), 255, np.uint8)
        if p["set"] == "miss":
            l1 = (f"#{n} {p['stratum']} r{p['round']} t{p['t_cap'] / 1000:.2f}s {p['agent']} "
                  f"{'conc' if p['concurrent'] else 'tail %dms' % p['ms_since_sight']}")
            l2 = (f"seer {'self' if p['seer_self'] else 'team'} {p['seer_dist_m']}m {p['seer_angle_deg']}d "
                  f"lit {lit_share if lit_share is None else round(lit_share, 2)} icon {p['icon_m']}m")
        else:
            l1 = f"#{n} extra r{p['round']} t{p['t_cap'] / 1000:.2f}s nearest enemy {p['nearest_enemy_m']}m"
            l2 = (f"drawn {p['nearest_enemy_drawn']} since {p['ms_since_sight']} to {p['ms_to_sight']} "
                  f"ally {p['nearest_ally_m']}m lit {lit_share if lit_share is None else round(lit_share, 2)}")
        cv2.putText(cap, l1, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        cv2.putText(cap, l2, (4, 37), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)
        tiles.append(np.concatenate([cap, tile], axis=0))
        index.append(dict(p, tile=n, lit_share=lit_share))
    # montages of 8 tiles (2 columns x 4 rows)
    names = []
    for m0 in range(0, len(tiles), 8):
        grp = tiles[m0:m0 + 8]
        while len(grp) % 2:
            grp.append(np.full_like(grp[0], 255))
        rows = [np.concatenate([grp[i], np.full((grp[i].shape[0], 10, 3), 255, np.uint8), grp[i + 1]], axis=1)
                for i in range(0, len(grp), 2)]
        img = np.concatenate([np.concatenate([r, np.full((10, r.shape[1], 3), 255, np.uint8)], 0) for r in rows], 0)
        name = odir / f"montage_{m0 // 8:02d}.png"
        cv2.imwrite(str(name), img)
        names.append(str(name))
    (odir / "index.jsonl").write_text("\n".join(json.dumps(r) for r in index) + "\n", encoding="utf-8")
    _log(f"{sid}: pixels {len(tiles)} tiles, montages {len(names)} in {odir}")
    return 0


CAUSE = {"N_dead": "t1_rule", "Nq": "t1_rule", "N": "t1_rule", "V_ref": "reader", "V_np": "reader",
         "P_ref": "reader", "P_np": "reader", "O": "offset", "U": "unclassified"}


def t1_revised(r) -> bool:
    """A candidate draw rule read off the bins (post hoc): the enemy alive,
    seen now or within 500 ms, and no stored smoke on the last sightline."""
    return (not r["enemy_dead"] and (r["concurrent"] or (r["ms_since_sight"] or 1e9) <= 500)
            and not r["smoke_on_line"])


def classes(n_boot: int = 2000) -> int:
    """Weighted class shares of the miss set from the agent's pixel classes:
    each stratum (primary cause) weighted by its size, bootstrapped over
    tiles within each (match, stratum)."""
    lab = json.loads((OUT / "pixels" / "agent_classes.json").read_text(encoding="utf-8"))
    rng = np.random.default_rng(SEED)
    out = {"per_match": {}, "extras": {}}
    tiles = {}
    for sid in DEV:
        idx = [json.loads(x) for x in (OUT / "pixels" / sid / "index.jsonl").read_text(encoding="utf-8").splitlines()]
        L = lab[sid]
        P = _load(sid)
        nm = sum(r["set"] == "miss" for r in P)
        st = defaultdict(list)
        ex = Counter()
        for r in idx:
            if r.get("tile") is None:
                continue
            c = L[str(r["tile"])]
            if r["stratum"] == "extra":
                ex[c] += 1
            else:
                st[r["stratum"]].append((c, r["stratum_n"]))
        tiles[sid] = (nm, st)
        out["extras"][sid] = dict(ex)
    names = list(CAUSE) + sorted(set(CAUSE.values()))

    def est(sample):
        acc = Counter()
        tot = 0
        for sid, (nm, st) in sample.items():
            for s, rows in st.items():
                w = rows[0][1]
                for c in CAUSE:
                    f = sum(x[0] == c for x in rows) / len(rows)
                    acc[c] += w * f
                    acc[CAUSE[c]] += w * f
            tot += sum(rows[0][1] for rows in st.values())
        return {k: acc[k] / tot for k in names}, tot

    point, tot = est(tiles)
    boots = []
    for _ in range(n_boot):
        smp = {sid: (nm, {s: [rows[i] for i in rng.integers(0, len(rows), len(rows))] for s, rows in st.items()})
               for sid, (nm, st) in tiles.items()}
        boots.append(est(smp)[0])
    out["pooled"] = {k: {"share": round(point[k], 4), "ci": [round(float(np.percentile([b[k] for b in boots], 2.5)), 4),
                                                              round(float(np.percentile([b[k] for b in boots], 97.5)), 4)],
                         "pairs": int(round(point[k] * tot))} for k in names}
    out["misses"] = tot
    for sid in DEV:
        p, t = est({sid: tiles[sid]})
        out["per_match"][sid] = {k: round(p[k], 4) for k in names}
        out["per_match"][sid]["misses"] = t
    # the candidate rule's drawn share and hit rate, from the stored pairs
    rev = {}
    for sid in DEV:
        P = _load(sid)
        info = json.loads((OUT / f"info_{sid}.json").read_text(encoding="utf-8"))
        n = info["samples"]["valid_live_samples"]
        D = [r for r in P if r["set"] in ("hit", "miss") and t1_revised(r)]
        ks = {r["k"] for r in D}
        rev[sid] = {"t1_any": info["samples"]["t1_any"], "real_any": info["samples"]["real_any"],
                    "t1rev_any": round(len(ks) / n, 4),
                    "t1rev_pairs": len(D), "t1rev_hit_rate": round(sum(r["set"] == "hit" for r in D) / len(D), 4),
                    "t1_hit_rate": round(sum(r["set"] == "hit" for r in P) / sum(r["set"] in ("hit", "miss") for r in P), 4)}
    out["t1_revised"] = rev
    (OUT / "classes.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(out, indent=1))
    return 0


def lit_check(sid: str) -> dict:
    """The drawn light (`lighting.lit_mask`, the vision gate's own channel)
    at drawn enemies, on the pixel sample's frames only: every hit and miss
    pair at those frames, lit share in the annulus 12-22 px * scale about
    the projected place (outside the icon, which covers the floor). A cross-reference: the game draws an enemy inside its drawn team
    vision [domain:minimap/vision-gate]."""
    from reticle import geometry, lighting
    from reticle.minimap_objects import object_context
    from reticle.store import Store

    cq._idle()
    refuse(sid)
    P = _load(sid)
    idx = [json.loads(x) for x in (OUT / "pixels" / sid / "index.jsonl").read_text(encoding="utf-8").splitlines()]
    lab = json.loads((OUT / "pixels" / "agent_classes.json").read_text(encoding="utf-8"))[sid]
    ks = {r["k"]: r["t_cap"] for r in idx if r.get("tile") is not None}
    ctx, why = object_context(Store(STORE), sid)
    with np.load(geometry.path_of(sid, STORE)) as z:
        ref = lighting.reference(z)
    cache = ctx["cache"]
    x0, y0, x1, y1 = ctx["rect"]
    sc = ctx["scale"]
    held = np.asarray(cache.holds(), float)
    want = {k: float(held[int(np.argmin(np.abs(held - t)))]) for k, t in ks.items()}
    crops = {float(s.t_ms): s.frame[y0:y1, x0:x1].copy()
             for s in cache.samples(sorted(set(want.values())), rois=["minimap"])}
    tile_cls = {r["k"]: lab[str(r["tile"])] for r in idx if r.get("tile") is not None and r["stratum"] != "extra"}
    rows = []
    for k, t in want.items():
        crop = crops.get(t)
        if crop is None:
            continue
        lit = lighting.lit_mask(crop, ref)
        yy, xx = np.mgrid[0:crop.shape[0], 0:crop.shape[1]]
        for r in P:
            if r["k"] != k or r["set"] not in ("hit", "miss") or r["enemy_dead"]:
                continue
            cx, cy = r["px"]
            d = np.hypot(xx - cx, yy - cy)
            known = ref.known & (d >= 12 * sc) & (d <= 22 * sc)   # an annulus outside the icon
            rows.append({"set": r["set"], "concurrent": r["concurrent"],
                         "lit": float(lit[known].mean()) if known.any() else None,
                         "cls": tile_cls.get(k) if r["set"] == "miss" else None})
    return {"session": sid, "rows": rows}


def run_lit(sessions) -> int:
    out = {}
    for sid in sessions:
        R = lit_check(sid)
        out[sid] = R["rows"]
    allr = [r for v in out.values() for r in v]

    def summ(sel):
        v = [r["lit"] for r in allr if sel(r) and r["lit"] is not None]
        if not v:
            return None
        v = np.asarray(v)
        return {"n": int(v.size), "median": round(float(np.median(v)), 3),
                "share_lit_ge_0.2": round(float((v >= 0.2).mean()), 3)}
    res = {"hits": summ(lambda r: r["set"] == "hit"),
           "hits_concurrent": summ(lambda r: r["set"] == "hit" and r["concurrent"]),
           "misses_concurrent_cls_N": summ(lambda r: r["set"] == "miss" and r["concurrent"] and r["cls"] == "N"),
           "misses_concurrent_reader": summ(lambda r: r["set"] == "miss" and r["concurrent"]
                                            and (r["cls"] or "").startswith(("V_", "P_"))),
           "misses_concurrent_all_on_sample_frames": summ(lambda r: r["set"] == "miss" and r["concurrent"])}
    (OUT / "lit_check.json").write_text(json.dumps({"summary": res, "rows": out}, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("sets")
    a.add_argument("sessions", nargs="+")
    b = sub.add_parser("pixels")
    b.add_argument("sessions", nargs="+")
    sub.add_parser("report")
    sub.add_parser("classes")
    c = sub.add_parser("lit")
    c.add_argument("sessions", nargs="+")
    args = ap.parse_args(argv)
    if args.cmd == "lit":
        return run_lit(args.sessions)
    if args.cmd == "classes":
        return classes()
    if args.cmd == "sets":
        return run_sets(args.sessions)
    if args.cmd == "pixels":
        for s in args.sessions:
            pixels(s)
        return 0
    return report()


if __name__ == "__main__":
    raise SystemExit(main())
