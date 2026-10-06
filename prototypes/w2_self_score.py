r"""Plan candidate W2: guard 6 and the self-spike tracker against replay truth.

    .\.venv\Scripts\python.exe prototypes\w2_self_score.py reread SESSION
    .\.venv\Scripts\python.exe prototypes\w2_self_score.py score SESSION [--candidate] [--out NAME]

Task `minimap-replay-plan-20261005`, candidate W2 (store
`notes/predictions.jsonl`, pre-registered 2026-10-06T02:19). It scores
`self-spike-tracker-20260929`'s two pieces, merged onto master on branch
`w2-self-tracker-score-20261006`:

* **guard 6**: `adjudication.spectate.stored_intervals`, the player's dead
  intervals from the death owner's verdicts (and the roster-gated spectate
  switch where no verdict exists), applied to a self stream by removing every
  fit inside an interval;
* **icon_prior**: `icon_prior.SelfTracker`, the minimap reader's self client
  (minimap-0.8.0), which masks the dropped spike glyph before the self fit
  and picks under the self-position owner's prior (`pick_self_declared`).

`reread` drives `cli._MinimapPass` (minimap-0.8.0) over every frame of the
session's 15 Hz minimap crop cache, one thread, Idle priority, and writes its
`l1/minimap` table and `minimap_prior` events into a scratch store under
`<store>/analysis/w2-self-20261006/scratch/`. It decodes no video and writes
nothing else.

`score` reads the replay through `replay_truth.session_context`
(replay-truth-0.3.0: the player named from the replay, Riot as cross-check)
and scores these self streams on `replay_truth.score`'s frame grid
(`ally_icon` frames inside the crop cache's spans with the widget drawn):

* `ally_icon`: the stored `ally_icon` frame `self` (what replay_truth scores);
* `minimap`: the stored `l1/minimap` self (minimap-0.7.0 on master);
* with `--candidate`, `tracker`: the scratch minimap-0.8.0 self.

Each stream is scored raw and under guard 6 (`+g6`: intervals from the
stored minimap self; the tracker's own self for `tracker+g6`), and, for
comparison only, under master's own player-death rule
(`round_entities.player_dead_spans`, which cuts the round_entity self piece;
`+re`). Definitions, fixed before any candidate number was read:

* alive/dead: the replay player's life at the frame's replay time
  (`replay_truth.truth_px`'s living mask), the denominator replay_truth uses;
* recall (alive coverage): alive frames whose fit lies within the 8 m gate of
  the player, over alive frames;
* error: px from the player's mapped position, alive frames with a fit;
* dead fits: fits on frames where the player is dead; a guard's P1 share is
  the dead fits it removes over the stream's raw dead fits; its alive clause
  counts the alive fits it removes (none is the pass), split into those
  within the gate (correct points lost) and beyond;
* worst cases: phantom self after death (dead fits kept), split into those
  within 8 m of a living teammate (a spectated view) and elsewhere;
  wrong-player self (alive fits beyond the gate of the player and within it
  of another living teammate); flips (alive fit-to-fit changes between on
  the player and on another teammate, in time order). Facing is not scored:
  neither stream carries one;
* each kept dead fit gets one cause, in order: `no_interval_in_round` (the
  guard holds no interval in the fit's replay round), `before_interval`
  (an interval of that round opens after the fit: the killfeed's lag behind
  the replay death), else `outside_interval`;
* each removed alive fit gets one cause: `next_round` (the fit's replay round
  differs from the interval's opening round: the interval outlasts the
  respawn) else `same_round` (a false or early death, or a revive the guard
  missed).

`wire: no` -- an evaluation script; `reticle/` never imports it.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "OPENCV_FOR_THREADS_NUM"):
    os.environ.setdefault(_k, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))

import replay_truth as rt  # noqa: E402
from reticle import replay_source as src  # noqa: E402
from reticle.adjudication import spectate  # noqa: E402
from reticle.store import Store  # noqa: E402

VERSION = "w2-self-score-0.1.0"
STORE = Store()
OUT = STORE.root / "analysis" / "w2-self-20261006"
SCRATCH = OUT / "scratch"


def idle() -> None:
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)
    except Exception:
        pass
    cv2.setNumThreads(1)


def _date(man: dict) -> str:
    from reticle.cli import _date_of
    return _date_of(man)


def reread(sid: str) -> None:
    """minimap-0.8.0 over the session's 15 Hz minimap crop cache, into SCRATCH."""
    from reticle.cli import _FP, _MinimapPass
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.version import MINIMAP_VERSION
    man = STORE.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    mm, why = RoiCache.load(STORE.root, man, prof, "minimap")
    if mm is None:
        raise SystemExit(f"{sid}: no minimap crop cache ({why})")
    if float(mm.record["hz"]) != 15.0:
        raise SystemExit(f"{sid}: cache at {mm.record['hz']} Hz, not 15")
    mp = _MinimapPass(STORE, man, prof, None, SimpleNamespace(minimap_hz=15.0))
    mp.frames_from = mm.record["version"]
    times = mm.holds()
    t0, c0 = time.perf_counter(), time.process_time()
    for i, smp in enumerate(mm.samples(times, rois=["minimap"])):
        mp.feed(smp)
        if i and i % 3000 == 0:
            print(f"  {sid} {i}/{len(times)} {time.perf_counter() - t0:.0f}s", flush=True)
    out = Store(SCRATCH)
    path = out.write_minimap(mp.rows, _FP(man["source"], sid), prof.name, _date(man),
                             frames_from=mp.frames_from)
    ev = out.write_events("minimap_prior", sid, mp.prior_events(sid))
    wall, cpu = time.perf_counter() - t0, time.process_time() - c0
    print(f"{sid}: {MINIMAP_VERSION} {len(mp.rows)} rows, wall {wall:.0f}s cpu {cpu:.0f}s "
          f"-> {path}, {ev}")


def _minimap_self(store: Store, sid: str, date: str) -> tuple[dict, list, str]:
    tb = store.read_minimap(sid, date)
    ver = (tb.schema.metadata or {}).get(b"minimap_version", b"").decode()
    fi = tb.column("frame_idx").to_pylist()
    t = tb.column("t_ms").to_pylist()
    x, y = tb.column("self_x").to_pylist(), tb.column("self_y").to_pylist()
    by = {int(f): (xx, yy) for f, xx, yy in zip(fi, x, y) if xx is not None}
    selves = sorted(zip(t, x, y))
    return by, selves, ver


def _on_grid(by: dict, S_idx) -> tuple[np.ndarray, np.ndarray]:
    fx = np.array([by.get(int(f), (np.nan, np.nan))[0] for f in S_idx], float)
    fy = np.array([by.get(int(f), (np.nan, np.nan))[1] for f in S_idx], float)
    return fx, fy


def _master_spans(sid: str, date: str) -> list[tuple]:
    """round_entities.player_dead_spans per stored round, as master's
    round_entity applies it (the round's end closes a span)."""
    from reticle.round_entities import player_dead_spans
    lu = STORE.root / "lineups" / f"{sid}.json"
    player_agent = None
    if lu.is_file():
        player_agent = (json.loads(lu.read_text(encoding="utf-8")).get("player") or {}).get("agent")
    deaths = STORE.read_events("death", sid)
    out = []
    for r in STORE.read_rounds(sid, date).to_pylist():
        rd = [d for d in deaths if d.get("kind") == "death_verdict"
              and d.get("round_no") == r["round_no"] and d.get("side") == "ally"]
        for _d, t0, t1 in player_dead_spans(rd, player_agent, float(r["t_end_ms"])):
            out.append((t0, t1))
    return out


def _inside(t, spans) -> np.ndarray:
    m = np.zeros(np.asarray(t).shape, bool)
    for t0, t1 in spans:
        m |= (t >= t0) & (t < t1)
    return m


def stream_block(fx, fy, sx, sy, me_live, OX, OY, OL, gate, cm_per_px, rnd) -> dict:
    """The self block for one stream on the scored grid (definitions above)."""
    has = np.isfinite(fx)
    e = np.hypot(sx - fx, sy - fy)
    alive = has & me_live
    dead = has & ~me_live
    on_me = alive & (e <= gate)
    # nearest other living teammate, each frame
    if OX.shape[1]:
        do = np.hypot(OX - fx[:, None], OY - fy[:, None])
        do = np.where(OL, do, np.inf)
        dmin = np.min(do, axis=1)
    else:
        dmin = np.full(fx.shape, np.inf)
    on_other = dmin <= gate
    wrong_player = alive & (e > gate) & on_other
    # flips: alive fits in time order, on-me vs on-other
    lab = np.where(on_me, 1, np.where(wrong_player, 2, 0))[alive]
    rr = rnd[alive]
    seq = lab[lab > 0]
    rs = rr[lab > 0]
    flips = int(np.sum((seq[1:] != seq[:-1]) & (rs[1:] == rs[:-1]))) if seq.size > 1 else 0
    return {"fits": int(has.sum()), "fits_alive": int(alive.sum()), "fits_dead": int(dead.sum()),
            "living_frames": int(me_live.sum()),
            "located_within_gate": int(on_me.sum()),
            "recall": round(float(on_me.sum() / max(1, me_live.sum())), 4),
            "err_px": src.sample_stats(e[alive]), "err_cm": src.sample_stats(e[alive] * cm_per_px, 0),
            "beyond_gate": int(np.sum(alive & (e > gate))),
            "wrong_player_alive": int(wrong_player.sum()),
            "flips_alive": flips,
            "dead_on_teammate": int(np.sum(dead & on_other)),
            "dead_elsewhere": int(np.sum(dead & ~on_other))}


def guard_block(raw: dict, fx, fy, keep, sx, sy, me_live, OX, OY, OL, gate, cm_per_px, rnd,
                S_t, spans, span_rnd) -> dict:
    """The guarded stream's block, with what the guard removed and kept."""
    gx, gy = np.where(keep, fx, np.nan), np.where(keep, fy, np.nan)
    blk = stream_block(gx, gy, sx, sy, me_live, OX, OY, OL, gate, cm_per_px, rnd)
    has = np.isfinite(fx)
    removed = has & ~keep
    e = np.hypot(sx - fx, sy - fy)
    rem_alive = removed & me_live
    rem_dead = removed & ~me_live
    kept_dead = has & keep & ~me_live
    # causes of kept dead fits
    starts = np.array([s[0] for s in spans], float) if spans else np.zeros(0)
    srnd = np.asarray(span_rnd, np.int64) if spans else np.zeros(0, np.int64)
    kd = np.flatnonzero(kept_dead)
    cause = Counter()
    for i in kd:
        same = srnd == rnd[i]
        if not same.any():
            cause["no_interval_in_round"] += 1
        elif np.any(same & (starts > S_t[i])):
            cause["before_interval"] += 1
        else:
            cause["outside_interval"] += 1
    # causes of removed alive fits
    ra = np.flatnonzero(rem_alive)
    acause = Counter()
    for i in ra:
        k = [j for j, (t0, t1) in enumerate(spans) if t0 <= S_t[i] < t1]
        acause["next_round" if k and srnd[k[0]] != rnd[i] else "same_round"] += 1
    blk.update({
        "removed_dead": int(rem_dead.sum()),
        "removed_dead_share": round(float(rem_dead.sum() / max(1, raw["fits_dead"])), 4),
        "removed_alive": int(rem_alive.sum()),
        "removed_alive_within_gate": int(np.sum(rem_alive & (e <= gate))),
        "removed_alive_causes": dict(acause),
        "kept_dead": int(kept_dead.sum()),
        "kept_dead_causes": dict(cause),
        "intervals": len(spans)})
    return blk


def score(sid: str, candidate: bool) -> dict:
    from reticle import roi_cache
    ctx = rt.session_context(sid)
    out = {"version": VERSION, "session": sid,
           "replay_truth_version": rt.REPLAY_TRUTH_VERSION,
           "self_identity_used": (ctx["out"].get("self_identity") or {}).get("used")}
    if "refused" in ctx["out"]:
        out["refused"] = ctx["out"]["refused"]
        return out
    rp, mf, a, me = ctx["rp"], ctx["mf"], ctx["a"], ctx["me"]
    allies, gate, cm_per_px = ctx["allies"], ctx["gate"], ctx["cm_per_px"]
    AI = ctx["AI"]
    rec = roi_cache.stored_record(STORE.root, sid, "minimap")
    spans_c = (rec or {}).get("spans") or []
    sc = roi_cache.spans_mask(AI["t_ms"], spans_c) & AI["drawn"]
    S_idx, S_t = AI["frame_idx"][sc], AI["t_ms"][sc]
    S_rep = src.frames_to_replay(S_t, a, rt.rg.MINIMAP_LAG_MS)
    mates = list(allies)
    c_me = mates.index(me)
    TX, TY, _YAW, TL = rt.truth_px(rp, mf, mates, S_rep)
    me_live = TL[:, c_me]
    sx, sy = TX[:, c_me], TY[:, c_me]
    others = [c for c in range(len(mates)) if c != c_me]
    OX, OY, OL = TX[:, others], TY[:, others], TL[:, others]
    rs = rp.round_starts()
    rnd = np.searchsorted(rs, S_rep, side="right") - 1
    out["frames_scored"] = int(S_idx.size)
    out["gate_px"] = round(float(gate), 2)

    man = STORE.read_manifest(sid)
    date = _date(man)
    from reticle.minimap import widget_scale
    from reticle.minimap import minimap_roi_px
    from reticle.profiles import get_profile
    x0, _y0, x1, _y1 = minimap_roi_px(get_profile(man["source_profile"]),
                                     int(man["source"]["width"]), int(man["source"]["height"]))
    wscale = widget_scale(x1 - x0)

    def rep_round(t_cap):
        tr = src.frames_to_replay(np.asarray([t_cap], float), a, rt.rg.MINIMAP_LAG_MS)
        return int(np.searchsorted(rs, tr, side="right")[0] - 1)

    mm_by, mm_selves, mm_ver = _minimap_self(STORE, sid, date)
    streams = {"ally_icon": (AI["self_x"][sc], AI["self_y"][sc]),
               "minimap": _on_grid(mm_by, S_idx)}
    versions = {"ally_icon": AI["stamp"].get("ally_icon_version"), "minimap": mm_ver}
    selves_for = {"ally_icon": mm_selves, "minimap": mm_selves}
    if candidate:
        tr_by, tr_selves, tr_ver = _minimap_self(Store(SCRATCH), sid, date)
        streams["tracker"] = _on_grid(tr_by, S_idx)
        versions["tracker"] = tr_ver
        selves_for["tracker"] = tr_selves
    out["stream_versions"] = versions

    ivs_cache = {}
    master_spans = _master_spans(sid, date)
    blocks = {}
    for name, (fx, fy) in streams.items():
        raw = stream_block(fx, fy, sx, sy, me_live, OX, OY, OL, gate, cm_per_px, rnd)
        blocks[name] = raw
        key = id(selves_for[name])
        if key not in ivs_cache:
            ivs, stamps = spectate.stored_intervals(STORE, sid, date, wscale,
                                                    selves=selves_for[name])
            ivs_cache[key] = (ivs, stamps)
        ivs, stamps = ivs_cache[key]
        spans = [(iv.t0_ms, iv.t1_ms) for iv in ivs]
        keep = ~_inside(S_t, spans)
        g = guard_block(raw, fx, fy, keep, sx, sy, me_live, OX, OY, OL, gate, cm_per_px, rnd,
                        S_t, spans, [rep_round(s[0]) for s in spans])
        g["intervals_by_basis"] = dict(Counter(iv.rests_on for iv in ivs))
        g["spectate_inputs"] = stamps
        blocks[f"{name}+g6"] = g
        keep_re = ~_inside(S_t, master_spans)
        blocks[f"{name}+re"] = guard_block(raw, fx, fy, keep_re, sx, sy, me_live, OX, OY, OL,
                                           gate, cm_per_px, rnd, S_t, master_spans,
                                           [rep_round(s[0]) for s in master_spans])
    out["streams"] = blocks
    # replay deaths of the player inside the scored rounds, for the record
    lives = np.diff(np.r_[0, me_live.astype(np.int8)])
    out["player_replay_deaths_on_grid"] = int(np.sum(lives < 0))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reread")
    p.add_argument("session")
    p = sub.add_parser("score")
    p.add_argument("session")
    p.add_argument("--candidate", action="store_true")
    p.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    idle()
    if args.cmd == "reread":
        reread(args.session)
        return 0
    res = score(args.session, args.candidate)
    OUT.mkdir(parents=True, exist_ok=True)
    name = args.out or (f"{args.session}.candidate" if args.candidate else f"{args.session}.baseline")
    path = OUT / f"{name}.json"
    if path.exists():
        raise SystemExit(f"{path} exists; pass another --out (evidence is never overwritten)")
    path.write_text(json.dumps(res, indent=1, default=float), encoding="utf-8")
    brief = {k: {kk: v.get(kk) for kk in ("fits_dead", "removed_dead_share", "removed_alive",
                                         "kept_dead", "recall", "beyond_gate",
                                         "wrong_player_alive", "flips_alive") if kk in v}
                | {"p95": (v.get("err_px") or {}).get("p95")}
             for k, v in res.get("streams", {}).items()}
    print(json.dumps({"session": args.session, "refused": res.get("refused"),
                      "frames": res.get("frames_scored"), "streams": brief}, indent=1))
    print(f"-> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
