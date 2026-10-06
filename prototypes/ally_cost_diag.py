"""Attribute the ally-icon reader's per-frame cost (ally-cost-diag-0.1.0, not wired).

Feeds `AllyIconReader` (built as `trial` builds it) the minimap crop cache's
frames over 300-frame windows of stored drawn frames, and records per frame
and per named step both wall (`perf_counter_ns`) and this thread's CPU
(`thread_time_ns`), with the frame's work: crop width, raw self and ally
fits, whether the stacked-icon search ran, and its members. Writes nothing to
the store; prints one JSON line per window and a summary.

Windows per session: `stack`, the 300 consecutive stored drawn frames with
the most frames whose stored `stack_reason` is None (the search ran), and
`rand0`, `rand1`, seeded starts (seed 20261005), as ally-vectorise-20261004
chose its nine.

Run single-threaded at idle priority:
    OMP_NUM_THREADS=1 python prototypes/ally_cost_diag.py SID [SID ...] --out FILE
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

VERSION = "ally-cost-diag-0.1.0"
STORE = Path(r"C:\Users\grant\reticle-store")
WIN = 300
SEED = 20261005

_STEPS: dict[str, list[int]] = {}


def _patch_steps():
    """Make `usage.step` also accumulate thread CPU and wall per path,
    whether or not a usage sink is active. `step` has slots, so the open
    steps live on a stack here, not on the instance."""
    from reticle import usage
    orig_enter, orig_exit = usage.step.__enter__, usage.step.__exit__
    stack: list[tuple[str, int, int]] = []

    def enter(self):
        path = f"{stack[-1][0]}/{self.name}" if stack else self.name
        r = orig_enter(self)
        stack.append((path, time.perf_counter_ns(), time.thread_time_ns()))
        return r

    def exit_(self, *exc):
        w1, c1 = time.perf_counter_ns(), time.thread_time_ns()
        path, w0, c0 = stack.pop()
        acc = _STEPS.setdefault(path, [0, 0, 0])
        acc[0] += 1
        acc[1] += w1 - w0
        acc[2] += c1 - c0
        return orig_exit(self, *exc)

    usage.step.__enter__, usage.step.__exit__ = enter, exit_


def windows(rows: list[dict], rng, outside_spans=None):
    """`outside_spans` (a list of (t0, t1) ms): keep only drawn frames outside
    them, the frames a cache clipped to rounds lacks (the buy phase)."""
    drawn = [r for r in rows if r.get("widget_drawn")]
    if outside_spans is not None:
        sp = np.asarray(outside_spans, float).reshape(-1, 2)
        t = np.array([float(r["t_ms"]) for r in drawn])
        inside = np.zeros(len(t), bool)
        for a, b in sp:
            inside |= (t >= a) & (t <= b)
        drawn = [r for r, i in zip(drawn, inside) if not i]
    drawn.sort(key=lambda r: r["t_ms"])
    if len(drawn) < WIN:
        return {}
    ran = np.array([("stack_reason" in r and r["stack_reason"] is None) for r in drawn], float)
    c = np.convolve(ran, np.ones(WIN), "valid")
    out = {"stack": int(np.argmax(c))}
    starts = rng.choice(len(drawn) - WIN, size=2, replace=False)
    out["rand0"], out["rand1"] = int(starts[0]), int(starts[1])
    return {k: [float(r["t_ms"]) for r in drawn[s:s + WIN]] for k, s in out.items()}, \
        {k: float(c[s] / WIN) for k, s in out.items()}, float(ran.mean())


def _video_frames(media, want, box):
    """The capture's frames at `want` (software decode, one thread), each
    kept as its minimap crop only; `_full` pastes one back into a reused
    frame before its feed."""
    from reticle.decode import seek_at
    x0, y0, x1, y1 = box
    out = []
    for smp in seek_at(str(media), want, 60.0):
        crop = smp.frame[y0:y1, x0:x1].copy()
        out.append((smp, crop))
        smp.frame = None
    return out


def run_session(sid: str, only: list[str] | None, out, start_at: float | None = None,
                source: str = "cache"):
    import cv2
    from reticle.minimap import ally_icon_reader
    from reticle.passes import SessionContext
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    from reticle.trial import TRIAL_ROIS
    cv2.setNumThreads(1)
    store = Store(STORE)
    manifest = store.read_manifest(sid)
    profile = get_profile(manifest["source_profile"])
    ctx = SessionContext(store=store, manifest=manifest, profile=profile)
    rows = [r for r in store.read_events_kind("ally_icon", sid, "frame") if r.get("kind") == "frame"]
    rng = np.random.default_rng(SEED)
    cache, why = RoiCache.load(store.root, manifest, profile, "minimap")
    if source == "video-outside":
        rec = cache.record
        spans = [(s["t0_ms"], s["t1_ms"]) if isinstance(s, dict) else tuple(s[:2])
                 for s in rec["spans"]]
        wins, stored_ran, ran_all = windows(rows, rng, outside_spans=spans)
        wins = {f"out_{k}": v for k, v in wins.items()}
        stored_ran = {f"out_{k}": v for k, v in stored_ran.items()}
    else:
        wins, stored_ran, ran_all = windows(rows, rng)
    idx = {float(r["t_ms"]): int(r["frame_idx"]) for r in rows}
    if cache is None and source == "cache":
        print(json.dumps({"session": sid, "refused": why}), file=out, flush=True)
        return
    for name, want in wins.items():
        if only and name not in only:
            continue
        reader = ally_icon_reader(ctx)          # fresh: pose priors start cold, as a window does
        if source == "cache":
            frames = [(smp, None) for smp in cache.samples(want, rois=TRIAL_ROIS["ally_icon"])]
        else:
            frames = _video_frames(ctx.media, want, reader.box)
        full = np.zeros((int(ctx.wh[1]), int(ctx.wh[0]), 3), np.uint8)
        if start_at is not None:            # concurrent runs feed together
            late = time.time() - start_at
            time.sleep(max(0.0, -late))
            start_at = None
        _STEPS.clear()
        per = []
        w_all, c_all = time.perf_counter_ns(), time.thread_time_ns()
        for smp, crop in frames:
            if crop is not None:
                x0, y0, x1, y1 = reader.box
                full[y0:y1, x0:x1] = crop
                smp.frame = full
            smp.frame_idx = idx.get(float(smp.t_ms), smp.frame_idx)
            nc0 = len(reader.candidates)
            w0, c0 = time.perf_counter_ns(), time.thread_time_ns()
            reader.feed(smp)
            w1, c1 = time.perf_counter_ns(), time.thread_time_ns()
            new = reader.candidates[nc0:]
            fr = reader.frames[-1]
            per.append({"wall_ns": w1 - w0, "cpu_ns": c1 - c0,
                        "self": sum(c["channel"] == "self" for c in new),
                        "ally": sum(c["channel"] == "ally" for c in new),
                        "stack_members": sum(c["channel"] == "stack" for c in new),
                        "stack_ran": fr.get("stack_reason", "x") is None,
                        "stack_reason": str(fr.get("stack_reason")),
                        "icons": fr.get("icons", 0)})
        w_all, c_all = time.perf_counter_ns() - w_all, time.thread_time_ns() - c_all
        n = len(per)
        reasons = sorted({p["stack_reason"] for p in per})
        by_reason = {r: {"frames": sum(p["stack_reason"] == r for p in per),
                         "cpu_ms": round(float(np.mean([p["cpu_ns"] for p in per
                                                        if p["stack_reason"] == r])) / 1e6, 3)}
                     for r in reasons}
        a = {k: np.array([p[k] for p in per], float) for k in per[0] if k != "stack_reason"}             if per else {}
        crop_w = int(reader.box[2] - reader.box[0])
        rec = {"version": VERSION, "session": sid, "profile": manifest["source_profile"],
               "window": name, "source": source, "ballast_rows": len(_BALLAST), "t0_s": want[0] / 1e3, "t1_s": want[-1] / 1e3,
               "frames": n, "asked": len(want), "crop_w": crop_w,
               "stored_stack_ran_share": round(stored_ran[name], 4),
               "session_stored_stack_ran_share": round(ran_all, 4),
               "wall_ms_per_frame": round(w_all / 1e6 / max(n, 1), 3),
               "cpu_ms_per_frame": round(c_all / 1e6 / max(n, 1), 3),
               "work": {k: round(float(v.mean()), 4) for k, v in a.items()
                        if k not in ("wall_ns", "cpu_ns")},
               "steps": {p: {"calls": v[0], "wall_ms_per_frame": round(v[1] / 1e6 / max(n, 1), 3),
                             "cpu_ms_per_frame": round(v[2] / 1e6 / max(n, 1), 3)}
                         for p, v in sorted(_STEPS.items())},
               "by_stack_reason": by_reason,
               "stack_ran_cpu_ms": (round(float(a["cpu_ns"][a["stack_ran"] > 0].mean() / 1e6), 3)
                                    if n and (a["stack_ran"] > 0).any() else None),
               "stack_idle_cpu_ms": (round(float(a["cpu_ns"][a["stack_ran"] == 0].mean() / 1e6), 3)
                                     if n and (a["stack_ran"] == 0).any() else None)}
        print(json.dumps(rec), file=out, flush=True)


def _idle() -> None:
    """Idle priority for this process (Windows `IDLE_PRIORITY_CLASS`);
    children inherit it."""
    import ctypes
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    if not k.SetPriorityClass(k.GetCurrentProcess(), 0x40):
        raise OSError("SetPriorityClass failed")


_BALLAST: list = []


def _ballast(n: int) -> None:
    """Hold `n` candidate-like rows alive, as a whole-capture pass holds its
    accumulated `candidates` (c817691bcd15 stored 605 MB of them): a dict of
    30 keys with three lists of 20 floats each, about 90 objects a row."""
    for i in range(n):
        _BALLAST.append({**{f"k{j}": float(j) for j in range(30)},
                         "a": [float(j) for j in range(20)], "b": [float(j) for j in range(20)],
                         "c": [[float(j), float(i)] for j in range(20)]})


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "--model":
        mp = argparse.ArgumentParser()
        mp.add_argument("--model", nargs="+", type=Path, required=True)
        mp.add_argument("--sessions", nargs="+", required=True)
        mp.add_argument("--record", action="store_true")
        a = mp.parse_args(argv)
        model(a.model, a.sessions, a.record)
        return 0
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--only", nargs="*", default=None, help="window names")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--source", choices=("cache", "video-outside"), default="cache",
                    help="video-outside: decode windows of drawn frames outside the "
                         "cache's round spans (the buy phase)")
    ap.add_argument("--ballast", type=int, default=0,
                    help="candidate-like rows to hold alive before feeding (GC load)")
    ap.add_argument("--start-at", type=float, default=None,
                    help="epoch seconds at which the first window starts feeding")
    args = ap.parse_args(argv)
    _idle()
    _patch_steps()
    if args.ballast:
        import gc
        t0 = time.perf_counter()
        _ballast(args.ballast)
        print(f"ballast {args.ballast} rows, {len(gc.get_objects())} tracked objects, "
              f"{time.perf_counter() - t0:.1f} s", file=sys.stderr)
    with args.out.open("a", encoding="utf-8") as out:
        for sid in args.sessions:
            run_session(sid, args.only, out, args.start_at, args.source)
    return 0




# --- the attribution model: `python prototypes/ally_cost_diag.py --model FILE ... --record`

UNDRAWN_MS = {"valorant-16x9": 0.35, "valorant-16x9-bigmap": 0.65}   # widget step, bench walls


def _category_costs(recs: list[dict]) -> dict:
    """Frame-weighted CPU ms per drawn frame by stack reason, per profile,
    over the cache windows (in-round frames)."""
    acc: dict = {}
    for r in recs:
        if r.get("source", "cache") != "cache" or not r.get("frames") or r.get("ballast_rows"):
            continue
        for reason, v in r["by_stack_reason"].items():
            a = acc.setdefault(r["profile"], {}).setdefault(reason, [0, 0.0])
            a[0] += v["frames"]
            a[1] += v["frames"] * v["cpu_ms"]
    return {p: {k: round(s / n, 3) for k, (n, s) in d.items() if n} for p, d in acc.items()}


def _mix(store, sid: str, spans) -> tuple[dict, dict]:
    """Stored frame rows by category, inside and outside `spans`."""
    from collections import Counter
    rows = [r for r in store.read_events_kind("ally_icon", sid, "frame") if r.get("kind") == "frame"]
    sp = np.asarray(spans, float).reshape(-1, 2)
    t = np.array([float(r["t_ms"]) for r in rows])
    inside = np.zeros(len(t), bool)
    for a, b in sp:
        inside |= (t >= a) & (t <= b)
    cat = lambda r: "undrawn" if not r.get("widget_drawn") else str(r.get("stack_reason"))
    return (dict(Counter(cat(r) for r, i in zip(rows, inside) if i)),
            dict(Counter(cat(r) for r, i in zip(rows, inside) if not i)))


def model(files: list[Path], sessions: list[str], record: bool) -> list[dict]:
    from reticle import metrics, usage
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    recs = [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]
    costs = _category_costs(recs)
    buy = [r for r in recs if r.get("source") == "video-outside" and r["window"] != "out_stack"]
    buy_ms = (sum(r["cpu_ms_per_frame"] * r["frames"] for r in buy) / sum(r["frames"] for r in buy)
              if buy else None)
    store = Store(STORE)
    out = []
    for sid in sessions:
        m = store.read_manifest(sid)
        prof = m["source_profile"]
        cache, _ = RoiCache.load(store.root, m, get_profile(prof), "minimap")
        spans = [tuple(s[:2]) if not isinstance(s, dict) else (s["t0_ms"], s["t1_ms"])
                 for s in cache.record["spans"]]
        mix_in, mix_out = _mix(store, sid, spans)
        c = costs[prof]
        unknown = [k for k in mix_in if k != "undrawn" and k not in c]
        cost = lambda k: UNDRAWN_MS[prof] if k == "undrawn" else c.get(k, c.get("at_capacity"))
        in_s = sum(n * cost(k) for k, n in mix_in.items()) / 1e3
        n_in = sum(mix_in.values())
        drawn_out = sum(n for k, n in mix_out.items() if k != "undrawn")
        out_s = ((drawn_out * buy_ms + mix_out.get("undrawn", 0) * UNDRAWN_MS[prof]) / 1e3
                 if mix_out else 0.0)
        n_out = sum(mix_out.values())
        u = [r for r in usage.load(STORE, sid) if r.get("kind") != "command"
             and (r.get("readers") or {}).get("ally_icon")]
        feed_s = u[-1]["readers"]["ally_icon"]["feed"]["total_ns"] / 1e9 if u else None
        fed = u[-1]["readers"]["ally_icon"]["feed"]["count"] if u else None
        v = {"frames_in_round": n_in, "frames_outside": n_out,
             "model_in_round_s": round(in_s, 1),
             "model_in_round_ms_per_frame": round(in_s * 1e3 / max(n_in, 1), 2),
             "model_outside_s": round(out_s, 1),
             "model_total_s": round(in_s + out_s, 1),
             "model_ms_per_fed_frame": round((in_s + out_s) * 1e3 / max(n_in + n_out, 1), 2),
             "buy_phase_ms_per_drawn_frame": round(buy_ms, 2) if buy_ms else None,
             "stored_feed_s": round(feed_s, 1) if feed_s else None,
             "stored_fed_frames": fed,
             "residual_factor": round(feed_s / (in_s + out_s), 3) if feed_s else None}
        row = {"session": sid, "profile": prof, "values": v, "costs": c,
               "mix_in": mix_in, "mix_out": mix_out, "unknown_categories": unknown}
        out.append(row)
        print(json.dumps(row))
        if record:
            metrics.record("ally_cost_diag", part="model", session=sid,
                           values={k: x for k, x in v.items() if x is not None},
                           deps={"version": VERSION, "inputs": [str(f) for f in files]},
                           context={"costs_ms": c, "mix_in": mix_in, "mix_out": mix_out,
                                    "note": "stored_feed_s is the latest usage record's "
                                            "ally_icon feed; on cache-fed sessions it ran "
                                            "on older code (see its code_revision)"})
    if record:
        for r in recs:
            if not r.get("frames"):
                continue
            metrics.record("ally_cost_diag", part=f"{r.get('source', 'cache')}/{r['window']}"
                           + (f"/ballast{r['ballast_rows']}" if r.get("ballast_rows") else ""),
                           session=r["session"],
                           values={"cpu_ms_per_frame": r["cpu_ms_per_frame"],
                                   "wall_ms_per_frame": r["wall_ms_per_frame"],
                                   "frames": r["frames"], "asked": r["asked"],
                                   "stack_ran_share": r["work"]["stack_ran"],
                                   "ally_fits_per_frame": r["work"]["ally"]},
                           deps={"version": VERSION, "t0_s": r["t0_s"], "t1_s": r["t1_s"]},
                           context={"profile": r["profile"], "by_stack_reason": r["by_stack_reason"]})
    return out


if __name__ == "__main__":
    raise SystemExit(main())
