r"""The enemy lane's error budget: one cause per miss and per extra, ranked.

Task `enemy-error-budget-20261007` (rows EB in the store's
`notes/predictions.jsonl`). The enemy lane (`minimap_object` rows reread by
`teardrop_refusals.py reread`) scored against T1d (`t1_draw_rule`, through
`teardrop_refusals.py score`) leaves misses (T1d-drawn enemies with no
accepted icon within 3 m) and extras (accepted icons with no T1d-drawn living
enemy within 3 m). This prototype gives each exactly one cause class, counts
the classes per match and pooled with round-bootstrap intervals, and draws
crops for the eye check and a stratified sample for the player's labelling
pass. The player's framing: "Systematic error explanation is basically the
hotspot analysis of accuracy increase."

* `feats SESSION --tag TAG` -- per miss and per extra (and 800 sampled hits,
  the pixel cuts' calibration), the candidate funnel at the place from the
  tag's frame rows (accepted, refused with its stored reason, "?" marks,
  other red blobs, X marks, in widget px, in the frame and two frames either
  side), the stored pings and smokes, truth context from replay truth
  (`t1_draw_rule.RealDrawMatch`, rule T1d: sight onset, tail and run, raw and
  smoke-filtered sight, death times, every living player's place, the
  frame-to-grid join offset and the truth place at the frame's own time),
  and the pixels at the place from the minimap roi_cache: soft redness,
  violet, departure from the baked reference grey, and the widget's tint.
  Written to `OUT/TAG/feats_SESSION.jsonl`.
* `budget --tag TAG [SESSION ...]` -- the classes (`MISS_ORDER`,
  `EXTRA_ORDER`: the first that holds, so assignment is deterministic), the
  Pareto per match and pooled with 95% intervals from a bootstrap over rounds
  (stratified by match); the counts must sum to the scorer's misses and
  extras or the run stops. `--record` writes the metrics ledger (series
  `enemy_error_budget`, part `budget/TAG`).
* `eye --tag TAG` -- up to `EYE_N` native-resolution crops per class at or
  above `EYE_SHARE` in any scope, spread over the matches, ranked by a hash
  of each row's identity (a class's crops move only where its membership
  does): `OUT/TAG/eye/SET__CLASS/` holds each window raw (`*_native.png`)
  and a sheet beside a nearest-neighbour enlargement with the overlays
  (display only): the row's truth place magenta, other enemies' places
  purple, allies' blue squares, accepted icons green, refused candidates
  yellow X, "?" orange squares, red X marks red crosses, pings cyan.
* `eye-score --tag TAG` -- the agent's verdicts (`OUT/TAG/eye_verdicts.json`:
  reader, truth, ambiguous, mislabelled per crop) per class, the reader
  share with a Wilson interval and weighted to class size per match.
* `levers --tag TAG` -- each lever's class group (`LEVERS`) and its bound on
  the hit rate or the extras if fully fixed, and weighted by the eye check.
* `sample --tag TAG` -- the stratified label sample (`SAMPLE_PLAN`, no
  labels) for the player's labelling pass.
* `peek --tag TAG --expr EXPR --name NAME` -- crops of rows a Python filter
  over the feature row picks (exploration only).

Classes are the agent's, by rule and by eye, never the player's labels.
Stored rows, replay truth and the minimap roi_cache only; no decode. The
held-out capture (cea8ecbc94ab) is refused before any row is read. Not wired
(`"wire": "no"`): an evaluation over replay truth; the levers it names live
in `reticle/minimap_objects.py`, `reticle/teardrop.py` and the T1d rule.

    python prototypes/enemy_error_budget.py feats 9acf02f98283 --tag v0
    python prototypes/enemy_error_budget.py budget 9acf02f98283 --tag v0
    python prototypes/enemy_error_budget.py feats 9acf02f98283 c817691bcd15 d3dcfb182ab1 --tag b1
    python prototypes/enemy_error_budget.py budget --tag b1 --record
    python prototypes/enemy_error_budget.py eye --tag b1
    python prototypes/enemy_error_budget.py eye-score --tag b1 --record
    python prototypes/enemy_error_budget.py levers --tag b1 --record
    python prototypes/enemy_error_budget.py sample --tag b1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

#: 0.2.0: the miss order puts the pixels at the place first, after the first
#: eye check; `red_glyph`, `hidden_under_ally`; `icon_offset` needs the icon
#: nearest this enemy; `red_poor_icon` (the Omen portrait); `tinted_widget`.
VERSION = "enemy-error-budget-0.2.0"
TASK = "enemy-error-budget-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
SRC = tr.OUT                       # the scored tags' rows and sets
DEV = tr.DEV
HELD_OUT = tr.HELD_OUT
N_BOOT = 4000
SEED = 20261007
NEAR_CM = tr.NEAR_CM               # the scorer's hit radius
ADJ_FRAMES = 2                     # neighbour frames searched for the icon
SHIFT_MS = 250.0                   # truth shifted this far either way (join offset)


def refuse(sid: str) -> None:
    tr.refuse(sid)


def _r(v, n=2):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


# ----------------------------------------------------------------- features

def _frames(tag: str, sid: str) -> tuple[dict, list[dict]]:
    """The tag's head row and its frame rows in file order."""
    head, fr = None, []
    for line in tr.rows_path(tag, sid).open(encoding="utf-8"):
        r = json.loads(line)
        if head is None:
            head = r
            continue
        if r.get("kind") == "frame":
            fr.append(r)
    return head, fr


def _pts(fr: dict | None, what: str):
    """(x, y, label) points of one kind in one frame row."""
    if fr is None or fr.get("reason") is not None:
        return []
    if what == "acc":
        return [(e["x"], e["y"], "acc") for e in fr.get("enemies") or []]
    if what == "refused":
        out = []
        for q in fr.get("refused") or []:
            rs = q["reason"]
            sub = rs.split(": ")[-1] if rs.startswith(("teardrop", "owned")) else rs.split(":")[0]
            out.append((q["x"], q["y"], f"{q['cls']}:{rs.split(':')[0]}:{sub}"
                        if rs.startswith("teardrop") else f"{q['cls']}:{rs.split(':')[0]}"))
        return out
    if what == "question":
        return [(q["x"], q["y"], "question") for q in fr.get("questions") or []]
    if what == "red_other":
        return [(q["x"], q["y"], f"red_other:{q['reason']}") for q in fr.get("red_other") or []]
    if what in ("x_red", "x_blue"):
        return [(q["x"], q["y"], what) for q in (fr.get("x_marks") or {}).get(what[2:], [])]
    raise KeyError(what)


def _nearest(pts, x, y):
    if not pts:
        return None, None
    d = [math.hypot(a - x, b - y) for a, b, _ in pts]
    i = int(np.argmin(d))
    return d[i], pts[i][2]


def _disc_stats(crop: np.ndarray, x: float, y: float, r: float, sgray: np.ndarray | None = None) -> dict:
    """Redness and teal over the disc of radius r about (x, y) in one crop,
    scored softly (`teardrop.redness`'s ramp); the disc is cut at r. With the
    baked reference grey `sgray` (`object_context`), `fg_sum`: the summed
    soft departure of the crop's grey from it (|d| ramped over 15..45 grey
    levels), the drawn area over the map whatever its colour."""
    import cv2

    from reticle import teardrop
    h, w = crop.shape[:2]
    x0, x1 = int(max(0, math.floor(x - r))), int(min(w, math.ceil(x + r) + 1))
    y0, y1 = int(max(0, math.floor(y - r))), int(min(h, math.ceil(y + r) + 1))
    if x1 <= x0 or y1 <= y0:
        return {"red_max": None, "red_sum": None, "red_n50": None, "teal_sum": None, "in_crop": False,
                "disc_px": 0, "fg_sum": None}
    win = crop[y0:y1, x0:x1]
    yy, xx = np.mgrid[y0:y1, x0:x1]
    m = np.hypot(xx - x, yy - y) <= r
    red = teardrop.redness(win)[m]
    c = win.astype(np.float32)
    teal = np.clip((np.minimum(c[..., 0], c[..., 1]) - c[..., 2] - 15.0) / 50.0, 0.0, 1.0)[m]
    out = {"red_max": round(float(red.max()), 3) if red.size else 0.0,
           "red_sum": round(float(red.sum()), 2), "red_n50": int((red >= 0.5).sum()),
           "teal_sum": round(float(teal.sum()), 2), "in_crop": True, "disc_px": int(m.sum())}
    if sgray is not None:
        g = cv2.cvtColor(np.ascontiguousarray(win), cv2.COLOR_BGR2GRAY).astype(np.float64)
        dg = np.abs(g - sgray[y0:y1, x0:x1])
        out["fg_sum"] = round(float(np.clip((dg[m] - 15.0) / 30.0, 0.0, 1.0).sum()), 2)
    # the inner disc (0.6 r): an agent portrait is mid-grey skin and hair; a
    # device glyph is white on black
    gi = cv2.cvtColor(np.ascontiguousarray(win), cv2.COLOR_BGR2GRAY).astype(np.float64)
    mi = np.hypot(xx - x, yy - y) <= 0.6 * r
    # violet over the disc: the Omen portrait carries almost no red. Violet
    # has blue over green and red over green; a blue X mark (red under
    # green) and an ally's teal (green over blue) score none
    cb = win.astype(np.float32)
    blue = (np.clip((cb[..., 0] - cb[..., 1] - 30.0) / 40.0, 0.0, 1.0)
            * np.clip((cb[..., 2] - cb[..., 1] - 5.0) / 20.0, 0.0, 1.0) * (cb[..., 0] > 90))
    out["blue_sum"] = round(float(blue[m].sum()), 2)
    if mi.any():
        out["dark_inner"] = round(float((gi[mi] < 40).mean()), 3)
        out["white_inner"] = round(float((gi[mi] > 200).mean()), 3)
    return out


def feats(sid: str, tag: str, n_hits: int = 800) -> int:
    """Features per miss and per extra (and a sample of hits for calibration)."""
    import enemy_lane_check as elc
    import replay_truth as rt
    import t1_draw_rule as tdr
    import entity_state as es
    from reticle import minimap_objects as mo
    from reticle.replay_source import to_px
    from reticle.store import Store

    refuse(sid)
    t0 = time.perf_counter()
    sets = SRC / tag / f"sets_{sid}.jsonl"
    if not sets.is_file():
        raise SystemExit(f"{sid}: no scored sets at {sets}; run teardrop_refusals.py score {sid} --tag {tag}")
    P = [json.loads(ln) for ln in sets.open(encoding="utf-8")]
    head, FR = _frames(tag, sid)
    fidx = {r["frame_idx"]: i for i, r in enumerate(FR)}
    scale = float(head["scale"])
    isc = float(head.get("icon_scale", scale))
    r_disc = 0.9 * mo.ICON_PX * isc
    # truth
    tr._point_store(tag)
    M = tdr.RealDrawMatch(sid, rule="T1d")
    dr = M.drawn(M.C)
    alive = M.alive_grid()
    raw = M.sees[M.ci].any(axis=0)
    smk = M.sees_smoked()[M.ci].any(axis=0)
    (mf, _to_m, mpp), _ = es.world_frame(sid)
    PX, PY = to_px(mf, M.X, M.Y)
    px_per_m = 1.0 / mpp
    K = M.G.size
    rnd = M.G_round
    ptag = tag if tr.ping_path(tag, sid).is_file() else None
    pings = tr._pings(sid, ptag)
    smokes = elc.smoke_tracks(sid)
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(why)
    slab = ctx["slab"]
    floor = ctx["floor"]
    H, W = slab.shape[:2]

    def last_true(v, k, j):
        """ms since v[j] last held at or before k in k's round; None if never."""
        lo = k
        while lo >= 0 and rnd[lo] == rnd[k]:
            if v[j, lo]:
                return float(M.G[k] - M.G[lo])
            lo -= 1
        return None

    def next_true(v, k, j):
        hi = k
        while hi < K and rnd[hi] == rnd[k]:
            if v[j, hi]:
                return float(M.G[hi] - M.G[k])
            hi += 1
        return None

    def ms_to_death(j, k):
        hi = k
        while hi < K and rnd[hi] == rnd[k]:
            if not alive[j, hi]:
                return float(M.G[hi] - M.G[k])
            hi += 1
        return None

    def at_time(j, t_rep):
        """Truth px of j at replay time t_rep, linear between grid samples."""
        i = int(np.searchsorted(M.G, t_rep))
        i0, i1 = max(0, i - 1), min(K - 1, i)
        if i0 == i1 or M.G[i1] == M.G[i0]:
            return float(PX[j, i0]), float(PY[j, i0])
        u = float(np.clip((t_rep - M.G[i0]) / (M.G[i1] - M.G[i0]), 0, 1))
        return (float((1 - u) * PX[j, i0] + u * PX[j, i1]), float((1 - u) * PY[j, i0] + u * PY[j, i1]))

    def shift_best(j, k, pts):
        """The least distance (px) from any accepted icon to j's truth over
        samples within SHIFT_MS of k in k's round, and the shift (ms)."""
        if not pts:
            return None, None
        n = int(round(SHIFT_MS / (M.G[1] - M.G[0]))) if K > 1 else 0
        best, bs = None, None
        for kk in range(max(0, k - n), min(K, k + n + 1)):
            if rnd[kk] != rnd[k] or not np.isfinite(PX[j, kk]):
                continue
            d = min(math.hypot(a - PX[j, kk], b - PY[j, kk]) for a, b, _ in pts)
            if best is None or d < best:
                best, bs = d, float(M.G[kk] - M.G[k])
        return best, bs

    def ally_icons_px(k, x, y):
        a = [math.hypot(PX[c, k] - x, PY[c, k] - y) for c in M.ci if alive[c, k] and np.isfinite(PX[c, k])]
        return min(a) if a else None

    near_px = NEAR_CM / 100.0 * px_per_m
    rows = []
    rng = np.random.default_rng(SEED)
    hits = [r for r in P if r["set"] == "hit"]
    hit_pick = set(rng.permutation(len(hits))[:n_hits].tolist())
    rows += [r for r in P if r["set"] != "hit"]
    rows += [hits[i] for i in sorted(hit_pick)]
    out = []
    for r in rows:
        s = r["set"]
        k = int(r["k"])
        fi = fidx.get(r["frame_idx"])
        fr = FR[fi] if fi is not None else None
        t_fr_rep = float(M.to_rep(np.array([r["t_cap"]]), rt.REMOTE_LAG_MS)[0])
        f = {"set": s, "session": sid, "round": r["round"], "k": k, "frame_idx": r["frame_idx"],
             "t_cap": r["t_cap"], "t_rep": r["t_rep"], "join_dt_ms": _r(t_fr_rep - M.G[k], 1)}
        if s in ("miss", "hit"):
            j = int(r["j"])
            x, y = r["px"]
            f.update({"j": j, "agent": r["agent"], "px": [x, y], "concurrent": r["concurrent"],
                      "ms_since_sight": r["ms_since_sight"], "ms_since_onset": r["ms_since_onset"],
                      "run_ms": r["run_ms"], "smoke_on_line": r["smoke_on_line"],
                      "centre_blocked": r["centre_blocked"], "seer_self": r["seer_self"],
                      "n_seers": r["n_seers"], "seer_dist_m": r["seer_dist_m"],
                      "since_live_s": r["since_live_s"], "ally_px": r["ally_px"],
                      "other_enemy_px": r["other_enemy_px"], "icon_m": r["icon_m"], "near_3m": r["near"]})
            xf, yf = at_time(j, t_fr_rep)
            f["px_at_frame"] = [round(xf, 1), round(yf, 1)]
            f["raw_last_ms"] = _r(last_true(raw, k, j), 1)
            f["ms_to_death"] = _r(ms_to_death(j, k), 1)
            f["ms_to_raw_sight"] = _r(next_true(raw, k, j), 1)
            sp = []
            for kk in (k - 1, k + 1):
                if 0 <= kk < K and rnd[kk] == rnd[k] and np.isfinite(PX[j, kk]):
                    sp.append(math.hypot(PX[j, kk] - x, PY[j, kk] - y) / (abs(M.G[kk] - M.G[k]) / 1000.0))
            f["speed_px_s"] = _r(max(sp), 1) if sp else None
        else:
            x, y = r["icon_px"]
            j = int(r["nearest_enemy"])
            f.update({"icon_px": [x, y], "cls_scorer": r["cls"], "nearest_enemy": j,
                      "nearest_enemy_m": r["nearest_enemy_m"], "nearest_enemy_alive": r["nearest_enemy_alive"],
                      "nearest_enemy_drawn": r["nearest_enemy_drawn"], "nearest_drawn_m": r["nearest_drawn_m"],
                      "nearest_ally_m": r["nearest_ally_m"], "ms_since_sight_t1": r["ms_since_sight"],
                      "ms_to_sight_t1": r["ms_to_sight"], "subj": r["subj"]})
            f["nearest_px"] = _r(math.hypot(PX[j, k] - x, PY[j, k] - y), 1) if np.isfinite(PX[j, k]) else None
            f["raw_last_ms"] = _r(last_true(raw, k, j), 1)
            f["smk_last_ms"] = _r(last_true(smk, k, j), 1)
            f["ms_to_raw_sight"] = _r(next_true(raw, k, j), 1)
            f["ms_to_drawn"] = _r(next_true(dr, k, j), 1)
            f["drawn_last_ms"] = _r(last_true(dr, k, j), 1)
            f["ms_to_death"] = _r(ms_to_death(j, k), 1)
            f["ally_px"] = _r(ally_icons_px(k, x, y), 1)
            # the enemy's truth at the frame's own time and within SHIFT_MS
            xf, yf = at_time(j, t_fr_rep)
            f["nearest_px_at_frame"] = _r(math.hypot(xf - x, yf - y), 1)
            sb, ss = shift_best(j, k, [(x, y, "icon")])
            f["nearest_px_shift"], f["shift_ms"] = _r(sb, 1), ss
            f["ms_since_death"] = (None if alive[j, k] else _r(last_true(alive, k, j), 1))
            f["p_ms"] = M._p_meas
            # any other living enemy (drawn or not) and its px distance
            dd = [(math.hypot(PX[e, k] - x, PY[e, k] - y), int(e)) for e in M.ei
                  if alive[e, k] and np.isfinite(PX[e, k])]
            f["nearest_alive_px"] = _r(min(dd)[0], 1) if dd else None
        # every living player's truth place at k, for the crops
        f["enemies_px"] = [[round(float(PX[e, k]), 1), round(float(PY[e, k]), 1), bool(dr[e, k])]
                           for e in M.ei if alive[e, k] and np.isfinite(PX[e, k]) and int(e) != j]
        f["allies_px"] = [[round(float(PX[c, k]), 1), round(float(PY[c, k]), 1)]
                          for c in M.ci if alive[c, k] and np.isfinite(PX[c, k])]
        # the funnel in this frame (widget px)
        for what in ("acc", "refused", "question", "red_other", "x_red", "x_blue"):
            d, lab = _nearest(_pts(fr, what), x, y)
            f[f"d_{what}"] = _r(d, 1)
            if what == "refused":
                f["refused_label"] = lab
                lab2 = sorted({p[2] for p in _pts(fr, what) if math.hypot(p[0] - x, p[1] - y) <= near_px})
                f["refused_near"] = lab2
        f["frame_read"] = fr is not None and fr.get("reason") is None
        f["frame_reason"] = None if fr is None else fr.get("reason")
        if s in ("miss", "hit"):
            acc = _pts(fr, "acc")
            f["d_acc_at_frame_time"] = _r(_nearest(acc, *f["px_at_frame"])[0], 1)
            if acc:
                a0 = min(acc, key=lambda q: math.hypot(q[0] - x, q[1] - y))
                f["acc_xy"] = [a0[0], a0[1]]
                # is the nearest accepted icon nearer another living enemy than this one?
                oth = [math.hypot(a0[0] - ex, a0[1] - ey) for ex, ey, _ in f["enemies_px"]]
                f["acc_other_nearer"] = bool(oth and min(oth) < math.hypot(a0[0] - x, a0[1] - y))
            sb, ss = shift_best(j, k, acc)
            f["d_acc_shift"], f["shift_ms"] = _r(sb, 1), ss
            adj = []
            for dfi in range(-ADJ_FRAMES, ADJ_FRAMES + 1):
                if dfi == 0 or fi is None or not (0 <= fi + dfi < len(FR)):
                    continue
                d, _ = _nearest(_pts(FR[fi + dfi], "acc"), x, y)
                if d is not None:
                    adj.append(d)
            f["d_acc_adj"] = _r(min(adj), 1) if adj else None
            qa = []
            for dfi in range(-ADJ_FRAMES, ADJ_FRAMES + 1):
                if fi is None or not (0 <= fi + dfi < len(FR)):
                    continue
                d, _ = _nearest(_pts(FR[fi + dfi], "question"), x, y)
                if d is not None:
                    qa.append(d)
            f["d_question_adj"] = _r(min(qa), 1) if qa else None
        # pings, smokes, widget
        t = r["t_cap"]
        if pings.size:
            on = (pings[:, 0] <= t) & (t <= pings[:, 1])
            f["d_ping"] = _r(np.hypot(pings[on, 2] - x, pings[on, 3] - y).min(), 1) if on.any() else None
        else:
            f["d_ping"] = None
        if smokes.size:
            act = (smokes[:, 0] <= t) & (t <= smokes[:, 1])
            f["in_smoke_disc"] = bool(act.any() and (np.hypot(smokes[act, 2] - x, smokes[act, 3] - y)
                                                     <= smokes[act, 4]).any())
        else:
            f["in_smoke_disc"] = False
        xi, yi = int(round(x)), int(round(y))
        inside = 0 <= xi < W and 0 <= yi < H
        f["in_widget"] = bool(inside)
        f["edge_px"] = _r(min(x, y, W - 1 - x, H - 1 - y), 1)
        f["on_slab"] = bool(slab[yi, xi]) if inside else False
        f["on_floor"] = bool(floor[yi, xi]) if inside else False
        f["near_px"] = round(near_px, 2)
        f["r_disc"] = round(r_disc, 2)
        out.append(f)
    # pixels at the place (miss/hit: truth at the frame's time; extra: the icon)
    by_t = defaultdict(list)
    for i, f in enumerate(out):
        if f["frame_read"]:
            by_t[float(f["t_cap"])].append(i)
    held = np.sort(np.asarray(ctx["cache"].holds(), float))
    tmap = {}
    for t in by_t:
        h = float(held[np.argmin(np.abs(held - t))])
        if abs(h - t) <= 1.0:
            tmap.setdefault(h, []).extend(by_t[t])
    x0, y0, x1, y1 = ctx["rect"]
    n_px = 0
    for smp in ctx["cache"].samples(sorted(tmap), rois=["minimap"]):
        crop = smp.frame[y0:y1, x0:x1]
        # the widget's tint: the median of R - G over the baked slab (grey
        # floor reads near 0; a full-screen pink wash lifts it)
        c32 = crop.astype(np.float32)
        tint = round(float(np.median((c32[..., 2] - c32[..., 1])[slab])), 1)
        for i in tmap[float(smp.t_ms)]:
            f = out[i]
            f["tint"] = tint
            if f["set"] == "extra":
                f.update(_disc_stats(crop, *f["icon_px"], r_disc, ctx["sgray"]))
            else:
                f.update(_disc_stats(crop, *f["px_at_frame"], r_disc, ctx["sgray"]))
                st = _disc_stats(crop, *f["px"], r_disc)
                f["red_sum_k"] = st["red_sum"]
            n_px += 1
    p = OUT / tag / f"feats_{sid}.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        for f in out:
            fh.write(json.dumps(f) + "\n")
    c = Counter(f["set"] for f in out)
    print(f"{sid} {tag}: {dict(c)} feature rows, {n_px} with pixels, px/m {px_per_m:.2f}, "
          f"near {near_px:.1f} px, disc {r_disc:.1f} px; {time.perf_counter() - t0:.0f} s -> {p}", flush=True)
    return 0


# ----------------------------------------------------------------- classes

#: Pixel cuts on the disc at the place, as shares of the disc (the redness's
#: soft sum over the disc's pixel count), fixed from the sampled hits: their
#: 5th percentile lies at 0.25 on 9acf02f98283 and d3dcfb182ab1 and their
#: 10th at 0.15 on c817691bcd15, whose Cypher portrait is mostly black.
RED_ICON = 0.10      # at or above: an icon's worth of red at the place
RED_NONE = 0.02      # below: nothing red drawn there
STACK_R = 2.0        # another icon within STACK_R * r_disc overlaps the place
PING_R = 1.5         # a confirmed ping within PING_R * r_disc covers the place
OFFSET_K = 2.0       # an accepted icon within OFFSET_K * near_px: found, off-place
TAIL_SPLIT_MS = 250.0
TINT = 8.0           # at or above: a pink wash; no sampled hit reaches it, 75 misses do
BLUE_ICON = 0.04     # at or above: a violet portrait; c817691bcd15's Omen hits sit at 0.049
                     # and above (5th percentile), every other sampled agent's 95th at 0.024 or under
FG_ICON = 0.30       # below: the place departs too little from the map for a portrait
                     # (the sampled hits' 2nd percentile is 0.37 to 0.48)

#: Each miss's cause: the first that holds, in this order. The order puts
#: what the pixels hold at the place first, as the eye check found it
#: decides the verdict: nothing red there (the game drew no icon: the truth
#: side, split by the sight timing T1d used), else the context drawn over
#: the place (icons, pings, X marks), else the funnel's stored answer.
#: Revised once after the first eye check (`eye_verdicts.json` keeps both):
#: 0.1.0 put the context classes first, and its `enemy_stack`, `ally_stack`
#: and `icon_offset` held empty places beside visible icons.
MISS_ORDER = (
    "off_widget",          # truth outside the widget or off the baked slab
    "tinted_widget",       # the whole widget washed pink (median R - G over the slab >= TINT)
    "red_poor_icon",       # a violet portrait (BLUE_ICON) with little red: the Omen icon, unread
    "hidden_under_ally",   # no red (or that portrait); a living ally (truth) within r_disc: an icon drawn over the place
    "undrawn_smoke",       # no red; a stored smoke on the sightline or over the place
    "undrawn_onset",       # no red; in sight, under 250 ms since the sight began
    "undrawn_glimpse",     # no red; a sight run under 250 ms
    "undrawn_tail",        # no red; in T1d's persistence tail after the sight ended
    "undrawn_in_sight",    # no red; in sight 250 ms or more
    "enemy_stack",         # red; another drawn living enemy within STACK_R * r_disc
    "icon_offset",         # red; an accepted icon within OFFSET_K * near (or near of truth +-250 ms), nearest this enemy
    "ally_stack",          # red; a living ally (truth) within STACK_R * r_disc
    "ping_cover",          # red; a confirmed ping within PING_R * r_disc, or a ping-owned refusal within near
    "x_mark_cover",        # red; a red X within near, or an X-owned refusal within near
    "red_glyph",           # red without a portrait's departure from the map (fg < FG_ICON): a "?" or a glyph
    "teardrop_refused",    # icon red; the teardrop refused a ring within near
    "slab_refused",        # icon red; the slab gate refused a candidate within near
    "question_on_icon",    # icon red; the reader's "?" within near
    "ring_unproposed",     # icon red; no candidate of any kind within near
    "question_faint",      # faint red; the reader's "?" within near
    "faint_red",           # faint red; the rest
    "unexplained",
)

#: Each extra's cause, the first that holds. The scorer's classes
#: (`teardrop_refusals.score`) come first and are split: a living enemy within
#: 3 m that T1d leaves undrawn, by why; one 3-8 m off, by whether a shifted
#: truth or a paired miss explains it; then the true false accepts.
EXTRA_ORDER = (
    "vu_smoke_filtered",   # visible_undrawn: raw sight within P, T1d's smoke filter removed it
    "vu_pre_onset",        # visible_undrawn: T1d draws him within 500 ms after
    "vu_long_tail",        # visible_undrawn: last sight P..3000 ms before
    "vu_unseen",           # visible_undrawn: no sight within 3 s before or 500 ms after
    "e38_time_shift",      # enemy_3_8m: his truth within +-250 ms lies within near
    "e38_paired_miss",     # enemy_3_8m: a miss of a drawn enemy in the frame lies within 8 m (one icon, two errors)
    "e38_other",           # enemy_3_8m: the rest
    "dead_enemy",          # the scorer's: the nearest enemy within 3 m is dead
    "ping",                # the scorer's: a confirmed ping there
    "x_mark",              # the scorer's: a red X there
    "other_ally_stack",    # other: a living ally within STACK_R * r_disc
    "other",               # other: the rest
)


def _miss_class(f: dict) -> str:
    near, rd = f["near_px"], f["r_disc"]
    rf = None if f.get("red_sum") is None else f["red_sum"] / max(f["disc_px"], 1)
    fg = None if f.get("fg_sum") is None else f["fg_sum"] / max(f["disc_px"], 1)
    lab = f.get("refused_near") or []
    if not f["in_widget"] or not f["on_slab"]:
        return "off_widget"
    if rf is None:
        return "unexplained"
    if (f.get("tint") or 0.0) >= TINT:
        return "tinted_widget"
    bf = (f.get("blue_sum") or 0.0) / max(f["disc_px"], 1)
    if rf < RED_ICON and bf >= BLUE_ICON:
        if f["ally_px"] is not None and f["ally_px"] <= rd:
            return "hidden_under_ally"
        return "red_poor_icon"
    if rf < RED_NONE:
        if f["ally_px"] is not None and f["ally_px"] <= rd:
            return "hidden_under_ally"
        if f["smoke_on_line"] or f["in_smoke_disc"]:
            return "undrawn_smoke"
        if f["concurrent"] and f["ms_since_onset"] is not None and f["ms_since_onset"] < TAIL_SPLIT_MS:
            return "undrawn_onset"
        if f["run_ms"] is not None and f["run_ms"] < TAIL_SPLIT_MS:
            return "undrawn_glimpse"
        if not f["concurrent"]:
            return "undrawn_tail"
        return "undrawn_in_sight"
    if f["other_enemy_px"] is not None and f["other_enemy_px"] <= STACK_R * rd:
        return "enemy_stack"
    if (((f["d_acc"] is not None and f["d_acc"] <= OFFSET_K * near)
         or (f["d_acc_shift"] is not None and f["d_acc_shift"] <= near))
            and not f.get("acc_other_nearer")):
        return "icon_offset"
    if f["ally_px"] is not None and f["ally_px"] <= STACK_R * rd:
        return "ally_stack"
    if (f["d_ping"] is not None and f["d_ping"] <= PING_R * rd) or any(t.startswith("ping:") for t in lab):
        return "ping_cover"
    if (f["d_x_red"] is not None and f["d_x_red"] <= near) or any(t.startswith("x_mark:") for t in lab):
        return "x_mark_cover"
    if fg is not None and fg < FG_ICON:
        return "red_glyph"
    q = f["d_question"] is not None and f["d_question"] <= near
    if rf >= RED_ICON:
        if any(t.startswith("enemy:teardrop") for t in lab):
            return "teardrop_refused"
        if any(t.endswith("off_slab") for t in lab):
            return "slab_refused"
        if q:
            return "question_on_icon"
        return "ring_unproposed"
    return "question_faint" if q else "faint_red"


def _extra_class(f: dict) -> str:
    c = f["cls_scorer"]
    p = f.get("p_ms") or 562.5
    if c == "visible_undrawn":
        raw, smk = f["raw_last_ms"], f["smk_last_ms"]
        if raw is not None and raw <= p and (smk is None or smk > p):
            return "vu_smoke_filtered"
        if f["ms_to_drawn"] is not None and f["ms_to_drawn"] <= 500:
            return "vu_pre_onset"
        if smk is not None and smk <= 3000:
            return "vu_long_tail"
        return "vu_unseen"
    if c == "enemy_3_8m":
        if f["nearest_px_shift"] is not None and f["nearest_px_shift"] <= f["near_px"]:
            return "e38_time_shift"
        if f.get("paired_miss"):
            return "e38_paired_miss"
        return "e38_other"
    if c in ("dead_enemy", "ping", "x_mark"):
        return c
    if f["ally_px"] is not None and f["ally_px"] <= STACK_R * f["r_disc"]:
        return "other_ally_stack"
    return "other"


def classify(F: list[dict]) -> list[dict]:
    """Each miss and extra of one match's feature rows with its class
    (`cls`); hits are dropped. An extra is `paired_miss` where a miss of the
    same frame lies within the scorer's 8 m offset of it."""
    by_fr = defaultdict(list)
    for f in F:
        if f["set"] == "miss":
            by_fr[f["frame_idx"]].append(f["px"])
    out = []
    for f in F:
        if f["set"] == "miss":
            out.append(dict(f, cls=_miss_class(f)))
        elif f["set"] == "extra":
            lim = f["near_px"] * tr.OFFSET_CM / tr.NEAR_CM
            f = dict(f, paired_miss=any(math.hypot(a - f["icon_px"][0], b - f["icon_px"][1]) <= lim
                                        for a, b in by_fr.get(f["frame_idx"], [])))
            out.append(dict(f, cls=_extra_class(f)))
    return out


def _boot(rounds_by_sid: dict, cnt_by_sid: dict, den_by_sid: dict, n=N_BOOT, seed=SEED):
    """Count and share intervals from a bootstrap over rounds, stratified by
    match (each match's rounds resampled within it, then summed)."""
    rng = np.random.default_rng(seed)
    tot_c = np.zeros(n)
    tot_d = np.zeros(n)
    for sid, rounds in rounds_by_sid.items():
        idx = rng.integers(0, len(rounds), (n, len(rounds)))
        tot_c += cnt_by_sid[sid][idx].sum(1)
        tot_d += den_by_sid[sid][idx].sum(1)
    sh = tot_c / np.maximum(tot_d, 1)
    return ([int(np.percentile(tot_c, 2.5)), int(np.percentile(tot_c, 97.5))],
            [round(float(np.percentile(sh, 2.5)), 4), round(float(np.percentile(sh, 97.5)), 4)])


def budget(tag: str, sessions: list[str], record: bool = False) -> dict:
    """The budget per match and pooled over `sessions`, printed as Pareto
    tables, written to `OUT/TAG/budget.json` and the classed rows to
    `OUT/TAG/classed_SESSION.jsonl`."""
    C = {}
    for sid in sessions:
        C[sid] = classify(_load_feats(tag, sid))
        sc = json.loads((SRC / tag / f"score_{sid}.json").read_text(encoding="utf-8"))
        got = Counter(f["set"] for f in C[sid])
        if got["miss"] != sc["misses"] or got["extra"] != sc["extras"]:
            raise SystemExit(f"{sid} {tag}: classed {got['miss']} misses and {got['extra']} extras against "
                             f"the scorer's {sc['misses']} and {sc['extras']}")
        with open(OUT / tag / f"classed_{sid}.jsonl", "w", encoding="utf-8") as fh:
            for f in C[sid]:
                fh.write(json.dumps(f) + "\n")
    res = {"version": VERSION, "tag": tag, "sessions": sessions,
           "order": {"miss": list(MISS_ORDER), "extra": list(EXTRA_ORDER)},
           "cuts": {"RED_ICON": RED_ICON, "RED_NONE": RED_NONE, "FG_ICON": FG_ICON, "BLUE_ICON": BLUE_ICON, "TINT": TINT, "STACK_R": STACK_R,
                    "PING_R": PING_R,
                    "OFFSET_K": OFFSET_K, "TAIL_SPLIT_MS": TAIL_SPLIT_MS},
           "boot": f"{N_BOOT} round resamples within each match, seed {SEED}", "tables": {}}
    scopes = [(sid, [sid]) for sid in sessions] + ([("pooled", sessions)] if len(sessions) > 1 else [])
    for scope, sids in scopes:
        res["tables"][scope] = {}
        for st, order in (("miss", MISS_ORDER), ("extra", EXTRA_ORDER)):
            rounds = {s: sorted({f["round"] for f in C[s]}) for s in sids}
            ri = {s: {r: i for i, r in enumerate(rounds[s])} for s in sids}
            den = {s: np.zeros(len(rounds[s])) for s in sids}
            cnt = {c: {s: np.zeros(len(rounds[s])) for s in sids} for c in order}
            for s in sids:
                for f in C[s]:
                    if f["set"] == st:
                        den[s][ri[s][f["round"]]] += 1
                        cnt[f["cls"]][s][ri[s][f["round"]]] += 1
            N = int(sum(d.sum() for d in den.values()))
            rows = []
            for c in order:
                n = int(sum(v.sum() for v in cnt[c].values()))
                ci_n, ci_s = _boot(rounds, cnt[c], den)
                rows.append({"cls": c, "n": n, "share": round(n / N, 4) if N else None,
                             "n_ci": ci_n, "share_ci": ci_s})
            rows.sort(key=lambda r: -r["n"])
            cum = 0
            for r in rows:
                cum += r["n"]
                r["cum_share"] = round(cum / N, 4) if N else None
            res["tables"][scope][st] = {"total": N, "rows": rows}
            print(f"\n{scope} {st}es: {N}" if st == "miss" else f"\n{scope} extras: {N}")
            print(f"  {'class':20s} {'n':>5s} {'[95%]':>12s} {'share':>7s} {'[95%]':>16s} {'cum':>6s}")
            for r in rows:
                if r["n"]:
                    print(f"  {r['cls']:20s} {r['n']:5d} [{r['n_ci'][0]:4d},{r['n_ci'][1]:4d}] {r['share']:7.3f} "
                          f"[{r['share_ci'][0]:.3f},{r['share_ci'][1]:.3f}] {r['cum_share']:6.3f}")
    p = OUT / tag / ("budget.json" if len(sessions) > 1 else f"budget_{sessions[0]}.json")
    p.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(f"\n-> {p}", flush=True)
    if record:
        from reticle.metrics import record as rec
        for scope, tb in res["tables"].items():
            vals, ci = {}, {}
            for st in ("miss", "extra"):
                vals[f"{st}.total"] = tb[st]["total"]
                for r in tb[st]["rows"]:
                    vals[f"{st}.{r['cls']}.n"] = r["n"]
                    vals[f"{st}.{r['cls']}.share"] = r["share"]
                    ci[f"{st}.{r['cls']}.n"] = r["n_ci"]
                    ci[f"{st}.{r['cls']}.share"] = r["share_ci"]
            rec("enemy_error_budget", part=f"budget/{tag}",
                session=scope if scope != "pooled" else "dev3", values=vals, ci=ci,
                deps={"version": VERSION, "rule": "T1d", "scorer": tr.VERSION, "cuts": res["cuts"],
                      "order_miss": list(MISS_ORDER), "order_extra": list(EXTRA_ORDER)},
                context={"task": TASK, "boot": res["boot"], "sessions": sessions},
                note="one cause per T1d miss and per extra of the enemy lane; classes by rule over stored "
                     "rows, replay truth and roi_cache pixels; not player labels")
    return res


# ----------------------------------------------------------------- crops

def _load_feats(tag: str, sid: str) -> list[dict]:
    refuse(sid)
    p = OUT / tag / f"feats_{sid}.jsonl"
    if not p.is_file():
        raise SystemExit(f"{sid}: no features at {p}; run `feats {sid} --tag {tag}`")
    return [json.loads(ln) for ln in p.open(encoding="utf-8")]


def draw_crops(tag: str, picks: list[dict], name: str, half: int = 22, zoom: int = 6) -> Path:
    """For each picked feature row: the native-resolution window about the
    place (truth for a miss, the icon for an extra), saved raw, and a sheet
    of display enlargements (nearest neighbour, display only) with the
    overlays: truth places of every enemy (magenta cross; the row's enemy
    larger), accepted icons (green circle), refused candidates (yellow X),
    "?" marks (orange square), red X marks (red +), pings (cyan diamond)."""
    import cv2

    from reticle import minimap_objects as mo
    from reticle.store import Store

    d = OUT / tag / "crops" / name
    d.mkdir(parents=True, exist_ok=True)
    tiles = []
    by_sid = defaultdict(list)
    for i, f in enumerate(picks):
        by_sid[f["session"]].append((i, f))
    out_tiles = {}
    for sid, items in by_sid.items():
        refuse(sid)
        _head, FR = _frames(tag, sid)
        fidx = {r["frame_idx"]: r for r in FR}
        ctx, why = mo.object_context(Store(STORE), sid)
        if ctx is None:
            raise SystemExit(why)
        x0, y0, x1, y1 = ctx["rect"]
        held = np.sort(np.asarray(ctx["cache"].holds(), float))
        tmap = defaultdict(list)
        for i, f in items:
            tmap[float(held[np.argmin(np.abs(held - f["t_cap"]))])].append((i, f))
        ptag = tag if tr.ping_path(tag, sid).is_file() else None
        pings = tr._pings(sid, ptag)
        for smp in ctx["cache"].samples(sorted(tmap), rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            for i, f in tmap[float(smp.t_ms)]:
                cx, cy = (f["icon_px"] if f["set"] == "extra" else f["px_at_frame"])
                cxi, cyi = int(round(cx)), int(round(cy))
                pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT, value=(40, 40, 40))
                win = pad[cyi:cyi + 2 * half + 1, cxi:cxi + 2 * half + 1].copy()
                stem = f"{i:03d}_{sid[:6]}_r{f['round']}_t{f['t_cap']:.0f}_{f['set']}"
                raw_p = d / f"{stem}_native.png"
                cv2.imwrite(str(raw_p), win)
                big = cv2.resize(win, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)  # display only
                ov = big.copy()

                def P2(x, y):
                    return int(round((x - cxi + half + 0.5) * zoom - 0.5)), int(round((y - cyi + half + 0.5) * zoom - 0.5))
                fr = fidx.get(f["frame_idx"], {})
                for e in fr.get("enemies") or []:
                    cv2.circle(ov, P2(e["x"], e["y"]), int(6 * zoom * f["r_disc"] / 6), (0, 255, 0), 2)
                for q in fr.get("refused") or []:
                    cv2.drawMarker(ov, P2(q["x"], q["y"]), (0, 255, 255), cv2.MARKER_TILTED_CROSS, 18, 2)
                for q in fr.get("questions") or []:
                    p_ = P2(q["x"], q["y"])
                    cv2.rectangle(ov, (p_[0] - 9, p_[1] - 9), (p_[0] + 9, p_[1] + 9), (0, 140, 255), 2)
                for q in (fr.get("x_marks") or {}).get("red", []):
                    cv2.drawMarker(ov, P2(q["x"], q["y"]), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
                if pings.size:
                    on = (pings[:, 0] <= f["t_cap"]) & (f["t_cap"] <= pings[:, 1])
                    for q in pings[on]:
                        cv2.drawMarker(ov, P2(q[2], q[3]), (255, 255, 0), cv2.MARKER_DIAMOND, 18, 2)
                for (tx, ty, drawn) in f.get("enemies_px", []):
                    cv2.drawMarker(ov, P2(tx, ty), (255, 0, 255) if drawn else (160, 60, 120),
                                   cv2.MARKER_CROSS, 14, 2 if drawn else 1)
                for (tx, ty) in f.get("allies_px", []):
                    cv2.drawMarker(ov, P2(tx, ty), (255, 200, 0), cv2.MARKER_SQUARE, 10, 1)
                if f["set"] != "extra":
                    cv2.drawMarker(ov, P2(*f["px_at_frame"]), (255, 0, 255), cv2.MARKER_CROSS, 22, 2)
                    cv2.circle(ov, P2(*f["px_at_frame"]), int(f["near_px"] * zoom), (255, 0, 255), 1)
                else:
                    cv2.circle(ov, P2(*f["icon_px"]), int(f["near_px"] * zoom), (255, 255, 255), 1)
                t = np.concatenate([big, np.full((big.shape[0], 4, 3), 255, np.uint8), ov], 1)
                lab = f"{i} {sid[:6]} r{f['round']} {f['t_cap'] / 1000:.2f}s {f.get('cls', '')}"
                cv2.putText(t, lab, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 2)
                cv2.putText(t, lab, (4, 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
                out_tiles[i] = t
    tiles = [out_tiles[i] for i in sorted(out_tiles)]
    Hm = max(t.shape[0] for t in tiles)
    Wm = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, Hm - t.shape[0], 0, Wm - t.shape[1], cv2.BORDER_CONSTANT,
                                value=(255, 255, 255)) for t in tiles]
    cols = 2
    while len(tiles) % cols:
        tiles.append(np.full((Hm, Wm, 3), 255, np.uint8))
    rows_ = [np.concatenate([tiles[i], np.full((Hm, 10, 3), 255, np.uint8), tiles[i + 1]], 1)
             for i in range(0, len(tiles), cols)]
    img = np.concatenate(sum([[r_, np.full((10, r_.shape[1], 3), 255, np.uint8)] for r_ in rows_], [])[:-1], 0)
    sp = d / "sheet.png"
    cv2.imwrite(str(sp), img)
    with open(d / "picks.jsonl", "w", encoding="utf-8") as fh:
        for i, f in enumerate(picks):
            fh.write(json.dumps({"i": i, **f}) + "\n")
    print(f"{len(picks)} crops -> {d} (sheet {sp})", flush=True)
    return sp


# ----------------------------------------------------------------- the eye check

EYE_SHARE = 0.03      # a class at or above this share in any scope is checked by eye
EYE_N = 12            # crops per class, spread evenly over the matches
VERDICTS = ("reader", "truth", "ambiguous", "mislabelled")


def eye_crops(tag: str, n: int = EYE_N, only: list[str] | None = None, out: str = "eye") -> int:
    """Draw `n` crops per class at or above EYE_SHARE in any scope of the
    budget, spread evenly over the matches, to `OUT/TAG/eye/SET__CLASS/`.
    The agent's verdicts go to `OUT/TAG/eye_verdicts.json` by hand, one of
    VERDICTS per crop index; `eye-score` reads them."""
    b = json.loads((OUT / tag / "budget.json").read_text(encoding="utf-8"))
    C = {sid: [json.loads(ln) for ln in (OUT / tag / f"classed_{sid}.jsonl").open(encoding="utf-8")]
         for sid in b["sessions"]}
    want = set()
    for scope, tb in b["tables"].items():
        for st in ("miss", "extra"):
            for r in tb[st]["rows"]:
                if r["share"] is not None and r["share"] >= EYE_SHARE:
                    want.add((st, r["cls"]))
    if only:
        want = {tuple(k.split("__")) for k in only}
    for st, cls in sorted(want):
        # Bottom-k by a hash of each row's identity, per match: a row keeps
        # its rank when other rows join or leave its class, so a class's
        # crops move only where its membership does.
        def rank(f):
            ident = f"{f['session']}|{f['set']}|{f['k']}|{f.get('j')}|{f.get('icon_px')}"
            return zlib.crc32(f"{SEED}|{ident}".encode())
        pools = {sid: sorted((f for f in C[sid] if f["set"] == st and f["cls"] == cls), key=rank,
                             reverse=True) for sid in C}
        pools = {k: v for k, v in pools.items() if v}
        pick = []
        while len(pick) < n and any(pools.values()):
            for sid in list(pools):
                if pools[sid] and len(pick) < n:
                    pick.append(pools[sid].pop())
        pick.sort(key=lambda f: (f["session"], f["t_cap"]))
        draw_crops(tag, pick, f"../{out}/{st}__{cls}")
    return 0


def eye_score(tag: str, record: bool = False) -> dict:
    """Per checked class: the verdict counts, the reader-error share with a
    Wilson 95% interval over the crops, and the share weighted to the
    class's size in each match (each crop stands for its match's rows of the
    class over that match's crops), from the agent's verdicts by eye (not
    player labels)."""
    from reticle.metrics import wilson

    V = json.loads((OUT / tag / "eye_verdicts.json").read_text(encoding="utf-8"))
    b = json.loads((OUT / tag / "budget.json").read_text(encoding="utf-8"))
    out = {}
    for key, v in V["classes"].items():
        st, cls = key.split("__")
        picks = [json.loads(ln) for ln in (OUT / tag / "eye" / key / "picks.jsonl").open(encoding="utf-8")]
        if len(picks) != len(v["crops"]):
            raise SystemExit(f"{key}: {len(v['crops'])} verdicts for {len(picks)} crops")
        n_in = {sid: next(r["n"] for r in b["tables"][sid][st]["rows"] if r["cls"] == cls)
                for sid in b["sessions"]}
        per = Counter(p["session"] for p in picks)
        w = np.array([n_in[p["session"]] / per[p["session"]] for p in picks])
        verd = [x["verdict"] for x in v["crops"]]
        c = Counter(verd)
        n = len(verd)
        lo, hi = wilson(c["reader"], n)
        ws = {k: round(float(w[[x == k for x in verd]].sum() / w.sum()), 3) for k in VERDICTS}
        out[key] = {"n": n, **{k: c[k] for k in VERDICTS}, "reader_share": round(c["reader"] / n, 3),
                    "reader_ci": [round(lo, 3), round(hi, 3)], "weighted": ws,
                    "summary": v.get("summary")}
        print(f"{key:28s} n {n:2d} " + " ".join(f"{k[:5]} {c[k]:2d}" for k in VERDICTS)
              + f"  reader {out[key]['reader_share']:.2f} [{lo:.2f},{hi:.2f}] weighted "
              + " ".join(f"{k[:5]} {ws[k]:.2f}" for k in VERDICTS))
    (OUT / tag / "eye_score.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        vals = {}
        for key, o in out.items():
            vals[f"{key}.n"] = o["n"]
            for k in VERDICTS:
                vals[f"{key}.{k}"] = o[k]
                vals[f"{key}.weighted.{k}"] = o["weighted"][k]
            vals[f"{key}.reader_share"] = o["reader_share"]
        rec("enemy_error_budget", part=f"eye/{tag}", session="dev3", values=vals,
            ci={f"{k}.reader_share": o["reader_ci"] for k, o in out.items()},
            deps={"version": VERSION, "verdicts": str(OUT / tag / "eye_verdicts.json")},
            context={"task": TASK, "by": "the agent, by eye; not player labels"},
            note="eye-check verdicts per class over up to 12 native-resolution crops; weighted to class size per match")
    return out

# ----------------------------------------------------------------- levers

#: The cheapest lever per group of classes: (kind, set, classes, effect).
#: `effect`: "hit" turns the misses into hits (a reader fix); "undraw" takes
#: them out of T1d's drawn set (a T1d fix); "draw" adds the extras to T1d's
#: drawn set as hits (a T1d fix); "unaccept" removes the extras (a reader
#: fix or gate). Each bound is the change if every row of the classes were
#: fixed, and again weighted by the eye check's share of the matching verdict.
LEVERS = {
    "T1 onset latency": ("truth-rule fix", "miss", ("undrawn_onset", "undrawn_glimpse"), "undraw"),
    "T2 sight the game does not draw": ("cross-reference gate (stored team vision) + player label",
                                        "miss", ("undrawn_in_sight",), "undraw"),
    "T3 persistence spread": ("truth-rule fix", "miss", ("undrawn_tail", "red_glyph", "faint_red"), "undraw"),
    "T4 smoke model": ("truth-rule fix", "miss", ("undrawn_smoke",), "undraw"),
    "R1 ring search misses visible icons": ("reader change (continue the prior)", "miss",
                                            ("ring_unproposed", "enemy_stack", "ally_stack"), "hit"),
    "R2 red-poor portrait (Omen)": ("reader change", "miss", ("red_poor_icon",), "hit"),
    "R3 teardrop refuses visible icons": ("reader change", "miss", ("teardrop_refused",), "hit"),
    "R4 '?' called on a visible icon": ("reader change", "miss", ("question_on_icon",), "hit"),
    "G1 utility glyphs accepted": ("cross-reference gate (ability glyph owner, the match's lineup)", "extra",
                                   ("other", "e38_other", "e38_paired_miss", "other_ally_stack"), "unaccept"),
    "T5 reveals and long persistence undrawn": ("truth-rule fix + player label (reveals)", "extra",
                                                ("vu_unseen", "vu_long_tail"), "draw"),
    "T6 smoke filter over-blocks": ("truth-rule fix", "extra", ("vu_smoke_filtered",), "draw"),
    "T7 early icons and death timing": ("truth-rule fix", "extra", ("vu_pre_onset", "dead_enemy"), "draw"),
    # the sums, for scale (the levers' bounds do not add: each moves the denominator)
    "SUM-T misses T1d draws undrawn": ("sum of T1-T4", "miss", ("undrawn_onset", "undrawn_glimpse",
                                       "undrawn_in_sight", "undrawn_tail", "red_glyph", "faint_red",
                                       "undrawn_smoke"), "undraw"),
    "SUM-R misses the reader leaves": ("sum of R1-R4", "miss", ("ring_unproposed", "enemy_stack", "ally_stack",
                                       "red_poor_icon", "teardrop_refused", "question_on_icon"), "hit"),
}
#: The scorer's true false accepts (`teardrop_refusals.score`): its `ping`,
#: `x_mark` and `other` extras; `other` splits here into `other` and
#: `other_ally_stack`.
FALSE_ACCEPT = ("ping", "x_mark", "other", "other_ally_stack")


def levers(tag: str, record: bool = False) -> dict:
    """Upper bounds on the hit rate and the true false accepts per lever,
    per match and pooled, from `budget.json` and the eye check."""
    b = json.loads((OUT / tag / "budget.json").read_text(encoding="utf-8"))
    eye_p = OUT / tag / "eye_score.json"
    E = json.loads(eye_p.read_text(encoding="utf-8")) if eye_p.is_file() else {}
    base = {}
    for sid in b["sessions"]:
        sc = json.loads((SRC / tag / f"score_{sid}.json").read_text(encoding="utf-8"))
        base[sid] = {"hits": sc["hits"], "drawn": sc["hits"] + sc["misses"], "false_accepts": sc["false_accepts"]}
    base["pooled"] = {k: sum(base[s][k] for s in b["sessions"]) for k in ("hits", "drawn", "false_accepts")}
    out = {}
    for name, (kind, st, classes, eff) in LEVERS.items():
        want = "reader" if eff in ("hit", "unaccept") else "truth"
        out[name] = {"kind": kind, "set": st, "classes": list(classes), "effect": eff, "scopes": {}}
        for scope, tb in b["tables"].items():
            rows = {r["cls"]: r["n"] for r in tb[st]["rows"]}
            n = sum(rows.get(c, 0) for c in classes)
            ne = sum(rows.get(c, 0) * E.get(f"{st}__{c}", {}).get("weighted", {}).get(want, 0.0)
                     for c in classes if rows.get(c, 0))
            h, d, fa = base[scope]["hits"], base[scope]["drawn"], base[scope]["false_accepts"]
            r0 = h / d
            if eff == "hit":
                hr, hre, fd, fde = (h + n) / d, (h + ne) / d, 0, 0
            elif eff == "undraw":
                hr, hre, fd, fde = h / (d - n), h / (d - ne), 0, 0
            elif eff == "draw":
                hr, hre, fd, fde = (h + n) / (d + n), (h + ne) / (d + ne), 0, 0
            else:
                fa_c = [c for c in classes if c in FALSE_ACCEPT]
                fn = sum(rows.get(c, 0) for c in fa_c)
                fne = sum(rows.get(c, 0) * E.get(f"{st}__{c}", {}).get("weighted", {}).get(want, 0.0)
                          for c in fa_c if rows.get(c, 0))
                hr, hre, fd, fde = r0, r0, -fn, -round(fne)
            out[name]["scopes"][scope] = {"n": n, "n_eye": round(ne, 1), "hit_rate": round(r0, 4),
                                          "hit_rate_bound": round(hr, 4), "d_hit_rate": round(hr - r0, 4),
                                          "hit_rate_eye": round(hre, 4), "d_hit_rate_eye": round(hre - r0, 4),
                                          "false_accepts": fa, "d_false_accepts": fd, "d_false_accepts_eye": fde}
        pl = out[name]["scopes"].get("pooled") or next(iter(out[name]["scopes"].values()))
        print(f"{name:42s} {kind[:40]:40s} n {pl['n']:5d} eye {pl['n_eye']:7.1f}  hit rate {pl['hit_rate']:.3f} -> "
              f"<= {pl['hit_rate_bound']:.3f} ({pl['d_hit_rate']:+.3f}; eye {pl['d_hit_rate_eye']:+.3f})"
              + (f"  extras -{pl['n']} (eye -{pl['n_eye']:.0f}); true false accepts {pl['false_accepts']} "
                 f"{pl['d_false_accepts']:+d} (eye {pl['d_false_accepts_eye']:+d})"
                 if eff == "unaccept" else ""))
    (OUT / tag / "levers.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        for scope in b["tables"]:
            vals = {}
            for name, L in out.items():
                key = name.split(" ")[0].replace("-", "_")
                for k in ("n", "n_eye", "hit_rate_bound", "d_hit_rate", "hit_rate_eye", "d_hit_rate_eye",
                          "d_false_accepts", "d_false_accepts_eye"):
                    vals[f"{key}.{k}"] = L["scopes"][scope][k]
            rec("enemy_error_budget", part=f"levers/{tag}", session=scope if scope != "pooled" else "dev3",
                values=vals, deps={"version": VERSION, "rule": "T1d", "levers": {k: list(v[2]) for k, v in LEVERS.items()}},
                context={"task": TASK, "eye": "the agent's verdicts by eye, weighted to class size per match"},
                note="upper bounds per lever if its classes were fully fixed; eye: weighted by the eye check's verdict share")
    return out


# ----------------------------------------------------------------- the label sample

#: Items per class for the player's labelling pass, weighted to the classes
#: whose eye check is mixed or ambiguous (`question_on_icon`, `enemy_stack`,
#: `other_ally_stack`, `dead_enemy`, `faint_red`, `ring_unproposed`), then to
#: the large T1d-side classes whose verdict falsifies the truth rule, then to
#: the clear classes, a few each as controls.
SAMPLE_PLAN = {
    "miss": {"question_on_icon": 30, "enemy_stack": 24, "ring_unproposed": 20, "faint_red": 16,
             "red_poor_icon": 8, "undrawn_in_sight": 20, "undrawn_onset": 12, "undrawn_tail": 8,
             "red_glyph": 8, "undrawn_smoke": 8, "undrawn_glimpse": 4, "teardrop_refused": 8,
             "ally_stack": 8},
    "extra": {"other_ally_stack": 24, "dead_enemy": 20, "vu_unseen": 12, "vu_long_tail": 8,
              "vu_smoke_filtered": 6, "vu_pre_onset": 4, "other": 8, "e38_other": 8, "e38_paired_miss": 4},
}
CAPTURES = {"9acf02f98283": r"C:\Users\grant\Videos\2026-08-24 11-55-34.mp4",
            "c817691bcd15": r"C:\Users\grant\Videos\2026-10-05 13-10-55.mp4",
            "d3dcfb182ab1": r"C:\Users\grant\Videos\2026-10-05 18-13-01.mp4"}


def label_sample(tag: str) -> Path:
    """The stratified sample (no labels): per class, its planned count spread
    over the matches by class size (largest remainder), at most one item per
    (match, round, enemy) before any repeat, ranked by a hash of the row's
    identity seeded apart from the eye check's; rows the eye check viewed
    are left out."""
    b = json.loads((OUT / tag / "budget.json").read_text(encoding="utf-8"))
    C = {sid: [json.loads(ln) for ln in (OUT / tag / f"classed_{sid}.jsonl").open(encoding="utf-8")]
         for sid in b["sessions"]}

    def ident(f):
        return (f["session"], f["set"], f["k"], f.get("j"), str(f.get("icon_px")))

    def rank(f):
        return zlib.crc32(f"{SEED + 1}|{'|'.join(map(str, ident(f)))}".encode())

    eyed = set()
    for d in (OUT / tag / "eye").glob("*/picks.jsonl"):
        for ln in d.open(encoding="utf-8"):
            eyed.add(ident(json.loads(ln)))
    items = []
    for st, plan in SAMPLE_PLAN.items():
        for cls, want in plan.items():
            rows = {sid: [f for f in C[sid] if f["set"] == st and f["cls"] == cls and ident(f) not in eyed]
                    for sid in C}
            tot = sum(len(v) for v in rows.values())
            if not tot:
                continue
            quota = {sid: want * len(v) / tot for sid, v in rows.items()}
            alloc = {sid: int(q) for sid, q in quota.items()}
            for sid in sorted(quota, key=lambda s_: quota[s_] - alloc[s_], reverse=True)[:want - sum(alloc.values())]:
                alloc[sid] += 1
            for sid, v in rows.items():
                v = sorted(v, key=rank)
                seen, pick = set(), []
                for f in v:
                    key = (f["round"], f.get("j", f.get("nearest_enemy")))
                    if key not in seen and len(pick) < alloc[sid]:
                        seen.add(key)
                        pick.append(f)
                for f in v:
                    if len(pick) >= alloc[sid]:
                        break
                    if f not in pick:
                        pick.append(f)
                for f in pick:
                    xy = f["px_at_frame"] if st == "miss" else f["icon_px"]
                    if st == "miss":
                        reader = {"call": "no enemy icon within 3 m", "nearest_accepted_px": f["d_acc"],
                                  "refused_near": f.get("refused_near"), "question_mark_px": f["d_question"]}
                        truth = {"call": "drawn", "agent": f["agent"], "concurrent_sight": f["concurrent"],
                                 "ms_since_sight": f["ms_since_sight"], "ms_since_onset": f["ms_since_onset"]}
                        ask = "Is an enemy agent icon drawn at the marked place?"
                    else:
                        reader = {"call": "enemy icon", "xy": f["icon_px"]}
                        truth = {"call": "no T1d-drawn living enemy within 3 m",
                                 "nearest_enemy_m": f["nearest_enemy_m"],
                                 "nearest_enemy_alive": f["nearest_enemy_alive"],
                                 "nearest_enemy_drawn": f["nearest_enemy_drawn"]}
                        ask = "Is the object at the marked place an enemy agent icon?"
                    items.append({"session": sid, "capture": CAPTURES[sid], "set": st, "cls": cls,
                                  "t_cap_ms": f["t_cap"], "frame_idx": f["frame_idx"], "round": f["round"],
                                  "widget_xy": [round(xy[0], 1), round(xy[1], 1)],
                                  "reader": reader, "t1d": truth, "ask": ask,
                                  "weight": round(len(v) / max(alloc[sid], 1), 2)})
    out = {"version": VERSION, "task": TASK, "tag": tag, "made": time.strftime("%Y-%m-%d"),
           "note": "a stratified sample for the player's labelling pass; no labels. widget_xy is in "
                   "the minimap crop's coordinates (roi_cache 'minimap' ROI as RoiCache.samples "
                   "normalises it, the frame rows' coordinates); t_cap_ms is capture time. weight: "
                   "the class's rows in the match over the items drawn from it. Rows the eye check "
                   "viewed are left out.",
           "plan": SAMPLE_PLAN, "n": len(items),
           "by_class": dict(Counter(f"{i['set']}__{i['cls']}" for i in items)),
           "by_session": dict(Counter(i["session"] for i in items)), "items": items}
    p = OUT / f"label_sample_{tag}.json"
    p.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"{len(items)} items -> {p}\n  {out['by_class']}\n  {out['by_session']}", flush=True)
    return p


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("feats")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p = sub.add_parser("budget")
    p.add_argument("sessions", nargs="*", default=list(DEV))
    p.add_argument("--tag", required=True)
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("eye")
    p.add_argument("--tag", required=True)
    p.add_argument("--n", type=int, default=EYE_N)
    p.add_argument("--only", help="SET__CLASS,... to draw (default: every class at or above EYE_SHARE)")
    p.add_argument("--out", default="eye")
    p = sub.add_parser("sample")
    p.add_argument("--tag", required=True)
    p = sub.add_parser("levers")
    p.add_argument("--tag", required=True)
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("eye-score")
    p.add_argument("--tag", required=True)
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("peek")
    p.add_argument("--tag", required=True)
    p.add_argument("--sessions", default=",".join(DEV))
    p.add_argument("--set", default="miss")
    p.add_argument("--expr", default="True", help="a Python filter over the feature row f (exploration)")
    p.add_argument("--n", type=int, default=12)
    p.add_argument("--name", required=True)
    a = ap.parse_args(argv)
    tr._idle()
    if a.cmd == "peek":
        rng = np.random.default_rng(SEED)
        rows = []
        for sid in a.sessions.split(","):
            rows += [f for f in _load_feats(a.tag, sid) if f["set"] == a.set and eval(a.expr, {"f": f})]
        print(f"{len(rows)} rows match", flush=True)
        pick = [rows[i] for i in sorted(rng.permutation(len(rows))[:a.n])]
        draw_crops(a.tag, pick, a.name)
        return 0
    if a.cmd == "budget":
        for s in a.sessions:
            refuse(s)
        budget(a.tag, a.sessions or list(DEV), a.record)
        return 0
    if a.cmd == "eye":
        return eye_crops(a.tag, a.n, a.only.split(",") if a.only else None, a.out)
    if a.cmd == "sample":
        label_sample(a.tag)
        return 0
    if a.cmd == "levers":
        levers(a.tag, a.record)
        return 0
    if a.cmd == "eye-score":
        eye_score(a.tag, a.record)
        return 0
    if a.cmd == "feats":
        for s in a.sessions:
            feats(s, a.tag)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
