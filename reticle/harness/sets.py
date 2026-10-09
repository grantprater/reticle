r"""The T1d join: (sample, enemy) pairs and the extras of a scored match.

Moved from `prototypes/enemy_lane_check.py` on 2026-10-09 (task
`harness-t1d-20261009`). `build_sets(sid, M)` joins the stored
`minimap_object` frames to the truth grid inside the crop cache's spans
(`schedule.join_runs`), on live samples only (`live_samples`), and returns the
miss and hit pairs, the extras (accepted icons with no drawn living enemy
within `NEAR_CM`) and the join (`ks`, `ic`, `valid`, `drawn`, `alive`) the
acceptance core scores.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from reticle import slot_state as es
from reticle.store import DEFAULT_STORE

from . import clock as rt
from . import extras as tr
from . import match as cq
from . import schedule as rrs


#: 0.1.1 (task teardrop-new-sessions-20261009): `build_sets` admits
#: `teardrop_refusals.SCORED`, the development matches and the 2026-10-07
#: replay captures; the report loops stay on `DEV`.
VERSION = "enemy-lane-check-0.1.1"


STORE = Path(DEFAULT_STORE)


NEAR_CM = 300.0          # an icon "at" an enemy


def refuse(name: str) -> None:
    rrs.refuse(name)


def _wrap_deg(a):
    return (np.asarray(a, float) + 180.0) % 360.0 - 180.0


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
    """The miss and extra sets of one scored match (`extras.SCORED`),
    with attributes.
    `M` (default `real_reader_schedule.RealMatch(sid)`) supplies the draw
    rule through `M.drawn`; `t1_draw_rule` passes its own."""
    from reticle.line_of_sight import EYE_ABOVE_CENTRE_CM
    from reticle.replay_source import to_px

    refuse(sid)
    tr.refuse(sid)
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
    # every icon at once: (enemy, icon) and (ally, icon) distances at the icon's sample
    D_e = np.hypot(M.X[ei][:, ks_i] - ix[None, :], M.Y[ei][:, ks_i] - iy[None, :])
    D_e = np.where(np.isfinite(D_e), D_e, np.inf)
    DD_e = np.where(dl[:, ks_i], D_e, np.inf)
    D_a = np.where(alive[ci][:, ks_i], np.hypot(M.X[ci][:, ks_i] - ix[None, :], M.Y[ci][:, ks_i] - iy[None, :]),
                   np.inf)
    J_n = ei[np.argmin(D_e, axis=0)] if ic.size else np.zeros(0, np.int64)
    # the first sight at or after each sample; a round's samples are contiguous
    # on the grid, so a next sight in a later round means none in this one
    nv = np.where(vis, np.arange(K)[None, :], K)
    nv = np.minimum.accumulate(nv[:, ::-1], axis=1)[:, ::-1]
    for q in np.flatnonzero(~(DD_e.min(axis=0, initial=np.inf) <= NEAR_CM)):
        k = int(ks_i[q])
        d, dd, da = D_e[:, q], DD_e[:, q], D_a[:, q]
        j = int(J_n[q])
        # ms to the next sight of the nearest enemy, and since its last
        kl = int(last[j, k])
        n_ = int(nv[j, k])
        nxt = np.array([n_ - k]) if n_ < K and M.G_round[n_] == M.G_round[k] else np.zeros(0, np.int64)
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
