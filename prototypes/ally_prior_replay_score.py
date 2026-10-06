r"""W1: the prior-first ally reader's per-frame output, scored by replay truth.

    .\.venv\Scripts\python.exe prototypes\ally_prior_replay_score.py SESSION [--own]

Candidate W1 of task `minimap-replay-plan-20261005` in the store's
`notes/predictions.jsonl`. It runs `ally_prior.run_session` (the reader its
`replay` subcommand runs, unchanged) once per session over the minimap crop
cache, caches the result, and hands its rows to `replay_truth.score` in place
of the stored `round_entity` teammate observations. The stored self
observations stay, so only the ally class differs from the baseline.

Two candidate streams, both scored by replay-truth's 8 m one-to-one rule:

- `carried`: the reader's per-track rows outside a crowd (fit, held, cover,
  predicted), each at the position it states;
- `located`: the same plus every crowd member, placed at its crowd's centroid
  on that frame (the reader states a region, not a point, for a member).

Beside replay-truth's report this adds what its names block omits: the
named-right share on frames within `replay_truth.STACK_LEAVE_MS` after a
teammate left a stack, and emergence identity (continuity, stored verdict,
arbiter) against the replay's teammate at the emerger's place. `--own` also
runs `ally_prior.score_replay` on the cached result (needs a Riot record).

Evaluation only: nothing in `reticle/` reads this file. Reports go to
`<store>/analysis/ally-prior-w1-20261006/<W1_VERSION>/` (0.1.0's sit one level
up), so a version never overwrites another's evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from collections import Counter
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
           "OPENCV_FOR_THREADS_NUM"):
    os.environ.setdefault(_v, "1")

import cv2
import numpy as np

cv2.setNumThreads(1)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ally_prior as ap  # noqa: E402
import replay_truth as rt  # noqa: E402
import riot_ground_truth as rg  # noqa: E402

#: 0.2.0 (2026-10-06): the reader is ally-prior-0.4.0, whose frame clock joins
#: the crop cache by nearest time (`frame_join`); 0.1.0 read only the frames
#: whose time the cache held exactly, 13,087 of c817691bcd15's 26,156. The
#: report stores the clock's join stamp.
W1_VERSION = "ally-prior-w1-score-0.2.0"
OUT = rt.STORE / "analysis" / "ally-prior-w1-20261006" / W1_VERSION
#: Track ids enter replay-truth's entity codes above the stored ones.
TRACK_BASE = 1_000_000


def reader_output(sid: str) -> tuple[dict, dict]:
    """`ally_prior.run_session` on `sid`, cached; (R, timing)."""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"R_{sid}.pkl"
    if path.exists():
        with path.open("rb") as f:
            blob = pickle.load(f)
        return blob["R"], blob["timing"]
    w0, c0 = time.perf_counter(), time.process_time()
    S, S_all, px, iso = ap._setup(sid)
    frame_join = getattr(px, "frame_join", None)
    w1, c1 = time.perf_counter(), time.process_time()
    R = ap.run_session(S, px, iso, S_all=S_all)
    w2, c2 = time.perf_counter(), time.process_time()
    timing = {"setup_wall_s": round(w1 - w0, 1), "setup_cpu_s": round(c1 - c0, 1),
              "run_wall_s": round(w2 - w1, 1), "run_cpu_s": round(c2 - c1, 1),
              "frames": R["frames"], "ally_prior_version": ap.ALLY_PRIOR_VERSION,
              "ally_icon_version": S.ally_icon_version,
              "round_entity_ally_icon": S.round_entity_inputs.get("ally_icon"),
              "ally_icon_stale": S.ally_icon_stale, "frame_join": frame_join}
    with path.open("wb") as f:
        pickle.dump({"R": R, "timing": timing}, f)
    return R, timing


def candidate_entities(sid: str, R: dict, with_crowds: bool) -> dict:
    """A `load_round_entity`-shaped dict: the stored self observations plus the
    reader's ally rows (crowd members at their crowd's centroid when
    `with_crowds`, else left out)."""
    base = STORED_RE(sid)
    keep = base["family"] == "self"
    cen = {(c["fidx"], c["crowd"]): (c["cx"], c["cy"]) for c in R["crowd_rows"]
           if c.get("cx") is not None and "end" not in c}
    f, t, x, y, e, a = [], [], [], [], [], []
    codes: dict[str, int] = {}
    crowd = ap.STATUSES.index("crowd")
    for (fidx, tm, tid, name, x_, y_, st, cid, _key) in R["rows"]:
        if st == crowd:
            if not with_crowds:
                continue
            x_, y_ = cen.get((fidx, cid), (x_, y_))
        f.append(fidx)
        t.append(tm)
        x.append(x_)
        y.append(y_)
        e.append(TRACK_BASE + codes.setdefault(tid, len(codes)))
        a.append(name)
    n = len(f)
    return {"frame_idx": np.r_[base["frame_idx"][keep], np.asarray(f, np.int64)],
            "t_ms": np.r_[base["t_ms"][keep], np.asarray(t, float)],
            "x": np.r_[base["x"][keep], np.asarray(x, float)],
            "y": np.r_[base["y"][keep], np.asarray(y, float)],
            "entity": np.r_[base["entity"][keep], np.asarray(e, np.int64)],
            "agent": np.r_[base["agent"][keep], np.asarray(a, dtype=object)],
            "family": np.r_[base["family"][keep], np.asarray(["ally"] * n, dtype=object)],
            "stamp": {"source": ap.ALLY_PRIOR_VERSION, "crowds": with_crowds,
                      "self_from": base["stamp"]}}


STORED_RE = rt.load_round_entity


def score_with(sid: str, RE: dict | None, keep_t=None) -> dict:
    """`replay_truth.score` with `RE` in place of the stored round_entity and,
    when `keep_t` is given, the scored frames cut to those capture times (the
    frames the prior-first reader read), through the one `spans_mask` call
    that sets replay-truth's denominator."""
    from reticle import roi_cache
    spans_mask = roi_cache.spans_mask
    rt.load_round_entity = (lambda _sid: RE) if RE is not None else STORED_RE
    if keep_t is not None:
        roi_cache.spans_mask = lambda t, spans: spans_mask(t, spans) & np.isin(t, keep_t)
    try:
        return rt.score(sid)
    finally:
        rt.load_round_entity = STORED_RE
        roi_cache.spans_mask = spans_mask


def prior_frame_times(sid: str, R: dict) -> np.ndarray:
    """Capture times of the `ally_icon` frames the reader read
    (`ally_prior`'s frame clock: drawn frames in the crop cache's spans that
    join a cache frame by nearest time)."""
    AI = rt.load_ally_icon(sid)
    return AI["t_ms"][np.isin(AI["frame_idx"], np.fromiter(R["frame_kind"], np.int64))]


def leaving_stack_names(sid: str, RE: dict, keep_t=None) -> dict:
    """Names on located ally frames by stack state: stacked, within
    `STACK_LEAVE_MS` after leaving a stack, and clear; the same rules as
    `replay_truth.score`'s names block, which counts only the wrong ones."""
    from reticle import roi_cache
    ctx = rt.session_context(sid)
    rp, mf, a, me, agent = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"], ctx["agent"]
    AI, gate, r_icon = ctx["AI"], ctx["gate"], float(mf.icon_px)
    rec = roi_cache.stored_record(rt.STORE, sid, "minimap")
    sc = roi_cache.spans_mask(AI["t_ms"], (rec or {}).get("spans") or []) & AI["drawn"]
    if keep_t is not None:
        sc &= np.isin(AI["t_ms"], keep_t)
    S_idx, S_t = AI["frame_idx"][sc], AI["t_ms"][sc]
    S_rep = rt._frames_to_replay(S_t, a, rg.MINIMAP_LAG_MS)
    mates = list(ctx["allies"])
    c_me = mates.index(me)
    TX, TY, _yaw, TL = rt.truth_px(rp, mf, mates, S_rep)
    dd = np.hypot(TX[:, :, None] - TX[:, None, :], TY[:, :, None] - TY[:, None, :])
    dd[:, np.arange(len(mates)), np.arange(len(mates))] = np.inf
    stacked = TL & (np.nanmin(np.where(np.isfinite(dd), dd, np.inf), axis=2) <= 2.0 * r_icon)
    last = np.maximum.accumulate(np.where(stacked, S_t[:, None], -np.inf), axis=0)
    since = S_t[:, None] - last
    k = np.clip(np.searchsorted(S_idx, RE["frame_idx"]), 0, S_idx.size - 1)
    ok = S_idx[k] == RE["frame_idx"]
    rows = k[ok]
    D = np.hypot(TX[rows] - RE["x"][ok][:, None], TY[rows] - RE["y"][ok][:, None])
    j, _d = rt._assign(rows, D, gate)
    hit = (j >= 0) & (j != c_me) & (RE["family"][ok] == "ally")
    jc = np.clip(j, 0, None)
    name = RE["agent"][ok]
    truth = np.array([agent.get(mates[c]) for c in jc], dtype=object)
    named = hit & np.array([g is not None for g in name], bool)
    right = named & np.array([rg.canon(g) == rg.canon(t_) for g, t_ in zip(name, truth)], bool)
    st = stacked[rows, jc]
    left = ~st & (since[rows, jc] <= rt.STACK_LEAVE_MS)
    out = {}
    for lab, m in (("stacked", st), ("left_stack_within_1s", left), ("clear", ~st & ~left),
                   ("all", np.ones(st.shape, bool))):
        h, nm, rr = int((hit & m).sum()), int((named & m).sum()), int((right & m).sum())
        out[lab] = {"located": h, "named": nm, "right": rr, "wrong": nm - rr,
                    "refused": h - nm,
                    "right_of_named": round(rr / nm, 4) if nm else None,
                    "right_of_located": round(rr / h, 4) if h else None}
    return out


def emergence_identity(sid: str, R: dict) -> dict:
    """Each emergence's three names against the replay teammate nearest the
    emerger within the 8 m gate, as `ally_prior.score_replay` scores them, on
    replay-truth's context (no Riot record needed)."""
    E = R["emergences"]
    if not E:
        return {}
    ctx = rt.session_context(sid)
    rp, mf, a, agent = ctx["rp"], ctx["mf"], ctx["a"], ctx["agent"]
    mates = list(ctx["allies"])
    et = np.asarray([e["t"] for e in E], float)
    X, Y, _yaw, _L = rt.truth_px(rp, mf, mates, rt._frames_to_replay(et, a, rg.MINIMAP_LAG_MS))
    Dm = np.hypot(X - np.asarray([e["x"] for e in E])[:, None],
                  Y - np.asarray([e["y"] for e in E])[:, None])
    Dm = np.where(np.isfinite(Dm), Dm, np.inf)
    jj = Dm.argmin(axis=1)
    dd = Dm[np.arange(et.size), jj]
    tru = [agent.get(mates[j]) if d <= ctx["gate"] else None for j, d in zip(jj, dd)]

    def outcome(names):
        return dict(Counter("no_truth" if t_ is None else "refused" if n is None else
                            "right" if rg.canon(n) == rg.canon(t_) else "wrong"
                            for n, t_ in zip(names, tru)))
    return {"n": len(E),
            "arbiter": outcome([e["agent"] for e in E]),
            "stored_verdict_only": outcome([e["stored_agent"] for e in E]),
            "continuity_only": outcome([None if e["ambiguous"] else e["member_name"] for e in E])}


def summary(s: dict) -> dict:
    """The teammate numbers W1 compares, from one replay-truth report."""
    tm = s["teammates"]
    out = {}
    for c in ("ally", "pooled"):
        b = tm[c]
        out[c] = {k: b[k] for k in ("living_truth_frames", "matched", "recall", "observations",
                                    "phantom", "phantom_share", "duplicate", "within_r_icon")}
        out[c]["err_cm_median"] = (b.get("err_cm") or {}).get("median")
        tr = tm["tracks"][c]
        out[c]["tracks"] = {k: tr[k] for k in ("idf1", "switches_per_truth_minute",
                                               "fragments_per_matched_life", "switches_flagged")}
        mb = tm["misses"][c]
        out[c]["misses"] = {"missed": mb["missed"], **mb["shares"]}
    out["names"] = {k: tm["names"][k] for k in ("named", "right", "wrong", "refused", "agreement",
                                                "wrong_stacked", "wrong_within_1s_of_leaving_stack",
                                                "wrong_stack_share")}
    out["names"]["top_wrong"] = tm["names"]["wrong_pairs_truth_got"][:5]
    fac = (s.get("facing") or {}).get("ally_ally_icon") or {}
    out["ally_facing_flip_share"] = fac.get("flip_share", fac.get("share_above_135"))
    return out


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("session")
    p.add_argument("--own", action="store_true", help="also run ally_prior.score_replay")
    args = p.parse_args(argv)
    sid = args.session
    R, timing = reader_output(sid)
    keep_t = prior_frame_times(sid, R)
    base_all = score_with(sid, None)
    if "refused" in base_all:
        print(json.dumps(base_all, indent=1, default=rt._default))
        return 2
    base = score_with(sid, None, keep_t)
    rep = {"session": sid, "w1_version": W1_VERSION, "replay_truth_version": rt.REPLAY_TRUTH_VERSION,
           "ally_prior_version": ap.ALLY_PRIOR_VERSION, "reader_run": timing,
           "stamps": base["stamps"], "frames_all": base_all["frames"],
           "frames_same": base["frames"], "prior_frames": int(keep_t.size),
           "self_identity": base.get("self_identity"),
           "baseline_all_frames": summary(base_all), "baseline": summary(base),
           "baseline_names_by_stack": leaving_stack_names(sid, STORED_RE(sid), keep_t)}
    for lab, crowds in (("carried", False), ("located", True)):
        RE = candidate_entities(sid, R, crowds)
        rep[lab] = summary(score_with(sid, RE, keep_t))
        rep[lab + "_names_by_stack"] = leaving_stack_names(sid, RE, keep_t)
    rep["status_rows"] = dict(Counter(ap.STATUSES[r[6]] for r in R["rows"]))
    rep["decisions"] = R["decisions"]
    rep["guard"] = R["guard"]
    rep["surprises"] = dict(Counter(s_["why"] for s_ in R["surprises"]))
    rep["cheap_frame_share"] = ap.cheap_share(R)
    rep["emergence_identity"] = emergence_identity(sid, R)
    if args.own:
        ap.ANALYSIS = OUT
        S_all_R = R
        ap.run_session = lambda *a_, **k_: S_all_R
        try:
            own = ap.score_replay(sid)
            rep["ally_prior_own"] = {k: own[k] for k in ("counts", "position_error_m",
                                                         "emergence_identity", "frames_scored")
                                     if k in own}
        except Exception as exc:  # no Riot record: the prior's own scorer needs one
            rep["ally_prior_own"] = {"refused": f"{type(exc).__name__}: {exc}"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"w1_{sid}.json").write_text(json.dumps(rep, indent=1, default=rt._default),
                                        encoding="utf-8")
    print(json.dumps(rep, indent=1, default=rt._default))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
