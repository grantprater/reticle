r"""Why the enemy teardrop refused visible enemy icons, and what its fix moves.

Task `teardrop-refusals-20261007` (rows TR in the store's
`notes/predictions.jsonl`). On the development matches the enemy lane scored
against T1d (`t1_draw_rule.RealDrawMatch(rule="T1d")`, through
`enemy_lane_check.build_sets`) missed hundreds of drawn enemies beside a
candidate the teardrop refused as `no_ring` or `low_ncc`.

* `refit SESSION` -- the falsifier: each teardrop-tagged miss's refused
  candidate refitted at its stored seed and as the best NCC over a 7x7 seed
  lattice 2 px apart, from the minimap roi_cache. The centring plan failed
  (TR1, TR2); the stored refusal reproduced (TR3).
* `reread SESSION --tag TAG` -- `minimap_objects.read_session` over the
  roi_cache with the code as checked out, written to `OUT/TAG/SESSION.jsonl`,
  never to the store's stream.
* `score SESSION --tag TAG` -- T1d sets over those rows (the stored rows when
  TAG is `stored`): hits, misses, the hit rate with a 95% interval from a
  bootstrap over rounds, the misses beside a `no_ring` or `low_ncc` refusal,
  the "?" marks beside a drawn enemy, and the extras by class.
* `pings SESSION --tag TAG` -- the ping owner (`ping.PingReader`, the code as
  checked out) over the minimap roi_cache at the scan's 10 Hz phase, its
  events written to `OUT/TAG/ping/SESSION.jsonl`, never to the store.
* `reread ... --pings TAG` and `score ... --pings TAG` -- read the owner gate's
  pings, and class the extras, from that reread instead of the stored stream.
* `reread ... --ping-own-px R` and `reread ... --no-owner-gate` -- the ping
  gate's reach set to R base px (the head records it), or the gate off.
* `gate --off TAG --tags A,B` -- per match, the real enemies (T1d hits) and
  the true false accepts each gated tag removed against the gate-off tag,
  and the base-px distance each `owned_by_ping` refusal links to its ping,
  split by whether a T1d miss names it.
* `compare --tags A,B` -- the table over the three development matches.
* `sheet --tags A,B` -- a before/after contact sheet of misses recovered.

**Extras classes** (truth is replay truth on the replay clock; the classes
are the agent's, by eye and by rule, never the player's labels):
`visible_undrawn` -- a living enemy within `NEAR_CM` that T1d calls undrawn
(a T1d finding, not a reader error); `enemy_3_8m` -- a living enemy within
`OFFSET_CM`; `dead_enemy` -- the nearest enemy, within `NEAR_CM`, is dead
(an icon at a death, by the replay's clock); then, with no living enemy that
near, class each extra first by the replay entity under it; `ping` (a
confirmed ping of the stored `ping` stream drawn there then), `x_mark` (a
stored X mark of the same row within `X_OWN_PX`) and `other` apply only where
no replay entity of any class lies within the gate (pending harness step 2).
The last three are the true false accepts.

The scorer reads the reread rows by giving the prototypes' `STORE` a path
whose `events/minimap_object` resolves to the tag's folder (`_Redirect`);
every other input is the store's own.

Stored data and the roi_cache only; no decode. The held-out capture
(cea8ecbc94ab) is refused before any row is read. Not wired (`"wire":
"no"`): an evaluation over replay truth; the fix it measures lives in
`reticle/teardrop.py` and `reticle/minimap_objects.py`.

    python prototypes/teardrop_refusals.py refit 9acf02f98283 --n 200
    python prototypes/teardrop_refusals.py reread 9acf02f98283 --tag after
    python prototypes/teardrop_refusals.py score 9acf02f98283 --tag after
    python prototypes/teardrop_refusals.py compare --tags stored,after
    python prototypes/teardrop_refusals.py record --tags stored,after
    python prototypes/teardrop_refusals.py sheet --tags stored,after --out SHEET.png
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from reticle.store import DEFAULT_STORE  # noqa: E402

#: 0.2.0 (task teardrop-confusers-20261007): `pings`, `--pings`.
#: 0.3.0 (task teardrop-review-fixes-20261007): `--ping-own-px`,
#: `--no-owner-gate`, `gate`.
VERSION = "teardrop-refusals-0.3.0"
TASK = "teardrop-refusals-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
DEV = ("9acf02f98283", "c817691bcd15", "d3dcfb182ab1")
HELD_OUT = "cea8ecbc94ab"
# The harness's gates and bootstrap live in its core (one definition).
from reticle.acceptance import N_BOOT, NEAR_CM, OFFSET_CM, SEED  # noqa: E402,F401


def _idle() -> None:
    """Idle priority, one thread (the machine's compute rules; no psutil)."""
    try:
        # The pseudo-handle is a 64-bit HANDLE; without argtypes ctypes passes
        # it as a 32-bit int, the call fails (ERROR_INVALID_HANDLE) and the
        # process stays at Normal.
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = ctypes.c_void_p
        k32.SetPriorityClass.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
        if not k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40):
            raise OSError(ctypes.get_last_error())
    except Exception:
        pass
    try:
        import cv2
        cv2.setNumThreads(1)
    except Exception:
        pass


def refuse(sid: str) -> None:
    if sid == HELD_OUT:
        raise SystemExit(f"{sid}: the held-out match is never read by this task")
    if sid not in DEV:
        raise SystemExit(f"{sid}: not a development match")


# ----------------------------------------------------------------- reread

def rows_path(tag: str, sid: str) -> Path:
    return (STORE / "events" / "minimap_object" / f"{sid}.jsonl" if tag == "stored"
            else OUT / tag / f"{sid}.jsonl")


PING_HZ = 10.0


def ping_path(ptag: str, sid: str) -> Path:
    return OUT / ptag / "ping" / f"{sid}.jsonl"


class _PingStore:
    """A store whose `ping` events are a reread's (`pings`); everything else
    is the store's own."""

    def __init__(self, store, ptag: str):
        self._s, self._ptag = store, ptag

    def read_events(self, stream, sid):
        if stream != "ping":
            return self._s.read_events(stream, sid)
        p = ping_path(self._ptag, sid)
        if not p.is_file():
            raise SystemExit(f"{sid}: no reread pings at {p}; run `pings {sid} --tag {self._ptag}`")
        return [json.loads(ln) for ln in p.open(encoding="utf-8")]

    def __getattr__(self, k):
        return getattr(self._s, k)


def pings(sid: str, tag: str) -> int:
    """The ping owner over the minimap roi_cache, at the scan's `--ping-hz`
    phase (a frame is fed when it is at least 1/hz after the last fed)."""
    from reticle import minimap_objects as mo
    from reticle.ping import PING_VERSION, PingReader
    from reticle.store import Store

    refuse(sid)
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(why)
    # The scan's phase is a next-timestamp on a fixed 1/hz grid
    # (`sample_multi`): each grid time takes the first held frame at or after
    # it. A gap-from-last-fed rule would read a 13.3 Hz cache at about 7 Hz.
    held = np.sort(np.asarray(ctx["cache"].holds(), float))
    grid = np.arange(held[0], held[-1] + 1e-6, 1000.0 / PING_HZ)
    k = np.searchsorted(held, grid - 1e-6)
    k = k[k < len(held)]
    fed = [float(t) for t in np.unique(held[k])]
    r = PingReader(floor=ctx["floor"], box=ctx["rect"], sgray=ctx["sgray"], hz=PING_HZ,
                   scale=ctx["icon_scale"])
    t0 = time.perf_counter()
    for smp in ctx["cache"].samples(fed, rois=["minimap"]):
        r.feed(smp)
    r.finish()
    ev = r.events(sid)
    p = ping_path(tag, sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        for e in ev:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")
    kinds = Counter(h[0] for h in r.hits)
    print(f"{sid}: {PING_VERSION} {len(r.hits)} confirmed {dict(kinds)}, {len(r.unconfirmed)} unconfirmed, "
          f"{len(r.rejected)} rejected over {len(r.ts)} frames ({r.n_absent} absent); "
          f"{time.perf_counter() - t0:.0f} s -> {p}", flush=True)
    return 0


def reread(sid: str, tag: str, ptag: str | None = None, ping_own_px: float | None = None,
           owner_gate: bool = True) -> int:
    """`minimap_objects.read_session` from the roi_cache into OUT/tag; with
    `ptag`, the owner gate reads that `pings` reread; `ping_own_px` sets the
    ping gate's reach (base px), `owner_gate` False turns the gate off."""
    from reticle import minimap_objects as mo
    from reticle.store import Store

    refuse(sid)
    if tag == "stored":
        raise SystemExit("`stored` names the store's own stream; pick another tag")
    t0 = time.perf_counter()
    store = Store(STORE) if ptag is None else _PingStore(Store(STORE), ptag)
    if ping_own_px is not None:
        mo.PING_OWN_PX = float(ping_own_px)
    res = mo.read_session(store, sid, dict(mo.ENABLED, owner_gate=owner_gate))
    if "skipped" in res:
        raise SystemExit(f"{sid}: {res['skipped']}")
    head = res["rows"][0]
    head["checks"] = {"wall_s": round(time.perf_counter() - t0, 1)}
    head["reread_by"] = VERSION
    head["pings_from"] = "store" if ptag is None else str(ping_path(ptag, sid))
    p = rows_path(tag, sid)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for r in res["rows"]:
            f.write(json.dumps(r, separators=(",", ":")) + "\n")
    os.replace(tmp, p)
    print(f"{sid}: {head['minimap_object_version']} {head['enemies']} enemies, "
          f"{head['questions']} '?', refused {head['candidates_refused']}; "
          f"{head['checks']['wall_s']} s -> {p}", flush=True)
    return 0


# ----------------------------------------------------------------- scoring

class _Redirect(type(Path())):
    """A store root whose `events/minimap_object` is another folder, and whose
    other `events/<stream>` folders named in `streams` are others too
    (`question_acceptance` points `enemy_track` at the tracks it built)."""

    target: Path | None = None
    streams: dict = {}

    def with_segments(self, *segs):
        p = type(self)(*segs)
        if len(p.parts) >= 2 and p.parts[-2] == "events" and Path(*p.parts[:-2]) == STORE:
            if p.parts[-1] == "minimap_object" and _Redirect.target is not None:
                return Path(_Redirect.target)
            if p.parts[-1] in _Redirect.streams:
                return Path(_Redirect.streams[p.parts[-1]])
        return p


def _point_store(tag: str):
    """Point the scoring prototypes' STORE at the tag's rows."""
    import enemy_lane_check as elc
    import real_reader_schedule as rrs
    import replay_truth as rt
    import t1_draw_rule as tdr

    _Redirect.target = None if tag == "stored" else rows_path(tag, DEV[0]).parent
    root = _Redirect(STORE)
    for m in (elc, rrs, rt, tdr):
        m.STORE = root


from reticle.acceptance import boot_count as _boot_count  # noqa: E402
from reticle.acceptance import boot_share as _boot_share  # noqa: E402


def _pings(sid: str, ptag: str | None = None) -> np.ndarray:
    """Confirmed pings (t0, t1, x, y) in capture ms and widget px: the stored
    stream, or with `ptag` that `pings` reread."""
    p = STORE / "events" / "ping" / f"{sid}.jsonl" if ptag is None else ping_path(ptag, sid)
    on, out = {}, []
    if p.is_file():
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if r.get("event_kind") == "entity_state":
                on[r["entity_id"]] = (r["t_ms"], r["position"])
            elif r.get("event_kind") == "entity_deleted" and r["entity_id"] in on:
                t0, (x, y) = on.pop(r["entity_id"])
                out.append((t0, r["t_ms"], x, y))
    return np.asarray(out, float).reshape(-1, 4)


def miss_cause(r) -> str | None:
    """`no_ring` or `low_ncc` where a refused teardrop candidate lies beside the miss."""
    td = [t for t in r["near"] if "teardrop" in t]
    if any(t.endswith("no_ring") for t in td):
        return "no_ring"
    if any(t.endswith("low_ncc") for t in td):
        return "low_ncc"
    return None


#: The extras classes that are true false accepts (no living enemy near).
TRUE_FA = ("ping", "x_mark", "other")


def class_extras(sid: str, tag: str, R: dict, ptag: str | None = None) -> list[dict]:
    """`R["extras"]` (from `enemy_lane_check.build_sets`), each with its class
    `cls` (the module docstring's extras classes) from the tag's rows and the
    confirmed pings (the stored stream, or with `ptag` that reread)."""
    from reticle import minimap_objects as mo

    scale = float(R["info"]["scale"])
    pings = _pings(sid, ptag)
    frames = {}
    want = {e["frame_idx"] for e in R["extras"]}
    for line in rows_path(tag, sid).open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") == "frame" and r["frame_idx"] in want:
            frames[r["frame_idx"]] = r
    near_px = mo.ICON_PX * scale
    out = []
    for e in R["extras"]:
        d = e["nearest_enemy_m"]
        alive = e["nearest_enemy_alive"]
        x, y = e["icon_px"]
        if alive and d is not None and d * 100 <= NEAR_CM:
            c = "visible_undrawn"
        elif alive and d is not None and d * 100 <= OFFSET_CM:
            c = "enemy_3_8m"
        elif not alive and d is not None and d * 100 <= NEAR_CM:
            c = "dead_enemy"
        else:
            t = e["t_cap"]
            on = (pings[:, 0] <= t) & (t <= pings[:, 1]) if pings.size else np.zeros(0, bool)
            fr = frames.get(e["frame_idx"], {})
            xs = [(q["x"], q["y"]) for col in ("blue", "red")
                  for q in (fr.get("x_marks") or {}).get(col, [])]
            if on.any() and np.hypot(pings[on, 2] - x, pings[on, 3] - y).min() <= near_px:
                c = "ping"
            elif any(math.hypot(a - x, b - y) <= mo.X_OWN_PX * scale for a, b in xs):
                c = "x_mark"
            else:
                c = "other"
        out.append(dict(e, cls=c))
    return out


def score(sid: str, tag: str, write: bool = True, ptag: str | None = None) -> dict:
    import enemy_lane_check as elc
    import t1_draw_rule as tdr
    from reticle import minimap_objects as mo

    refuse(sid)
    _point_store(tag)
    rp = rows_path(tag, sid)
    if not rp.is_file():
        raise SystemExit(f"{sid}: no rows at {rp}; run `reread {sid} --tag {tag}`")
    M = tdr.RealDrawMatch(sid, rule="T1d")
    R = elc.build_sets(sid, M=M)
    info = R["info"]
    scale = float(info["scale"])
    pairs = R["pairs"]
    rounds = sorted({r["round"] for r in pairs} | {r["round"] for r in R["extras"]})
    ri = {rn: i for i, rn in enumerate(rounds)}
    nr = len(rounds)
    drawn = np.zeros(nr)
    hit = np.zeros(nr)
    cause = {c: np.zeros(nr) for c in ("no_ring", "low_ncc")}
    q_miss = np.zeros(nr)
    q_hit = np.zeros(nr)
    for r in pairs:
        i = ri[r["round"]]
        drawn[i] += 1
        if r["set"] == "hit":
            hit[i] += 1
            q_hit[i] += "question" in r["near"]
        else:
            c = miss_cause(r)
            if c:
                cause[c][i] += 1
            q_miss[i] += "question" in r["near"]
    # extras by class
    classes = ("visible_undrawn", "enemy_3_8m", "dead_enemy", "ping", "x_mark", "other")
    ext = {c: np.zeros(nr) for c in classes}
    ext_rows = class_extras(sid, tag, R, ptag)
    for e in ext_rows:
        ext[e["cls"]][ri[e["round"]]] += 1
    nh, nd = int(hit.sum()), int(drawn.sum())
    false_acc = sum(ext[c] for c in TRUE_FA)
    out = {"session": sid, "tag": tag, "version": VERSION, "rule": "T1d", "p_ms": M._p_meas,
           "minimap_object_version": info.get("minimap_object_version"), "scale": scale,
           "rounds": nr, "hits": nh, "misses": nd - nh, "hit_rate": round(nh / nd, 4),
           "hit_rate_ci": _boot_share(rounds, hit, drawn),
           "no_ring": int(cause["no_ring"].sum()), "no_ring_ci": _boot_count(rounds, cause["no_ring"]),
           "low_ncc": int(cause["low_ncc"].sum()), "low_ncc_ci": _boot_count(rounds, cause["low_ncc"]),
           "question_at_miss": int(q_miss.sum()), "question_at_hit": int(q_hit.sum()),
           "extras": len(R["extras"]),
           "extras_ci": _boot_count(rounds, sum(ext.values())),
           "extras_by_class": {c: int(v.sum()) for c, v in ext.items()},
           "extras_by_class_ci": {c: _boot_count(rounds, v) for c, v in ext.items()},
           "false_accepts": int(false_acc.sum()), "false_accepts_ci": _boot_count(rounds, false_acc),
           "icons_valid": info["icons_valid"], "pings_from": "store" if ptag is None else ptag}
    if write:
        d = OUT / ("stored" if tag == "stored" else tag)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"score_{sid}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
        with open(d / f"sets_{sid}.jsonl", "w", encoding="utf-8") as f:
            for r in pairs + ext_rows:
                f.write(json.dumps(r) + "\n")
    print(json.dumps({k: out[k] for k in ("session", "tag", "hits", "misses", "hit_rate", "hit_rate_ci",
                                          "no_ring", "low_ncc", "question_at_miss", "question_at_hit",
                                          "extras", "extras_ci", "false_accepts", "false_accepts_ci")}),
          flush=True)
    print("   extras by class", out["extras_by_class"], flush=True)
    return out


def gate(off: str, tags: list[str], write: bool = True) -> int:
    """The ping gate's cost and gain per gated tag against the gate-off tag
    `off`, each scored first (`score`): the real enemies it refused (T1d hits
    lost) and the true false accepts it removed, with the base-px distance
    each `owned_by_ping` refusal links to its ping, split by whether a T1d
    miss in its frame names a ping refusal (the nearest to the miss's place)."""
    from reticle.metrics import record as rec

    pooled = {}
    for sid in DEV:
        p0 = OUT / off / f"score_{sid}.json"
        if not p0.is_file():
            print(f"{sid} {off}: not scored")
            continue
        s0 = json.loads(p0.read_text(encoding="utf-8"))
        for tag in tags:
            pt = OUT / tag / f"score_{sid}.json"
            if not pt.is_file():
                print(f"{sid} {tag}: not scored")
                continue
            st = json.loads(pt.read_text(encoding="utf-8"))
            head, refs = None, {}
            for line in rows_path(tag, sid).open(encoding="utf-8"):
                r = json.loads(line)
                if head is None:
                    head = r
                    continue
                pr = [x for x in r.get("refused", []) if x.get("cls") == "ping"]
                if pr:
                    refs[r["frame_idx"]] = pr
            isc = float(head["icon_scale"])
            reach = head["parameters"].get("PING_OWN_PX", head["parameters"]["ICON_PX"])
            real = set()
            for line in (OUT / tag / f"sets_{sid}.jsonl").open(encoding="utf-8"):
                r = json.loads(line)
                if r["set"] != "miss" or not any(t.startswith("ping:owned_by_ping") for t in r["near"]):
                    continue
                pr = refs.get(r["frame_idx"], [])
                if pr:
                    q = min(range(len(pr)), key=lambda i: math.hypot(pr[i]["x"] - r["px"][0],
                                                                     pr[i]["y"] - r["px"][1]))
                    real.add((r["frame_idx"], q))
            d_real, d_other = [], []
            for fi, pr in refs.items():
                for q, x in enumerate(pr):
                    d = (x.get("evidence") or [{}])[0].get("d_px")
                    if d is not None:
                        ((d_real if (fi, q) in real else d_other)).append(d / isc)
            out = {"session": sid, "tag": tag, "off": off, "reach_base_px": reach,
                   "refused_real": s0["hits"] - st["hits"],
                   "removed_false": s0["false_accepts"] - st["false_accepts"],
                   "hit_rate": st["hit_rate"], "hit_rate_off": s0["hit_rate"],
                   "ping_refusals": sum(len(v) for v in refs.values()),
                   "d_real_base_px_p50": round(float(np.median(d_real)), 2) if d_real else None,
                   "d_other_base_px_p50": round(float(np.median(d_other)), 2) if d_other else None,
                   "d_other_base_px_p90": round(float(np.percentile(d_other, 90)), 2) if d_other else None,
                   "n_real_linked": len(d_real), "n_other": len(d_other)}
            print(json.dumps(out), flush=True)
            pl = pooled.setdefault(tag, {"refused_real": 0, "removed_false": 0, "reach": reach,
                                         "sessions": []})
            pl["refused_real"] += out["refused_real"]
            pl["removed_false"] += out["removed_false"]
            pl["sessions"].append(sid)
            if write:
                vals = {k: v for k, v in out.items()
                        if isinstance(v, (int, float)) and not isinstance(v, bool)}
                rec("teardrop_refusals", part=f"gate/{tag}", session=sid, values=vals,
                    deps={"version": VERSION, "rule": "T1d", "off": off,
                          "minimap_object_version": st["minimap_object_version"]},
                    context={"task": TASK},
                    note="the ping gate's cost (T1d hits lost) and gain (true false accepts "
                         "removed) against the gate-off reread; distances from the refusals' links")
    for tag, pl in pooled.items():
        print(f"pooled {tag} (reach {pl['reach']} base px): refused_real {pl['refused_real']}, "
              f"removed_false {pl['removed_false']} over {pl['sessions']}", flush=True)
        if write and len(pl["sessions"]) == len(DEV):
            rec("teardrop_refusals", part=f"gate/{tag}", session="dev3",
                values={"refused_real": pl["refused_real"], "removed_false": pl["removed_false"],
                        "reach_base_px": pl["reach"]},
                deps={"version": VERSION, "rule": "T1d", "off": off},
                context={"task": TASK, "sessions": pl["sessions"]},
                note="the ping gate summed over the three development matches")
    return 0


def compare(tags: list[str]) -> int:
    print(f"{'session':14s} {'tag':8s} {'hit rate [95%]':24s} {'no_ring':>8s} {'low_ncc':>8s} "
          f"{'extras [95%]':18s} {'false acc [95%]':18s} {'?@miss':>7s} {'?@hit':>6s}")
    for sid in DEV:
        for tag in tags:
            p = OUT / tag / f"score_{sid}.json"
            if not p.is_file():
                print(f"{sid} {tag}: not scored")
                continue
            s = json.loads(p.read_text(encoding="utf-8"))
            print(f"{sid:14s} {tag:8s} {s['hit_rate']:.4f} [{s['hit_rate_ci'][0]:.4f},{s['hit_rate_ci'][1]:.4f}]"
                  f"  {s['no_ring']:8d} {s['low_ncc']:8d} {s['extras']:5d} [{s['extras_ci'][0]},{s['extras_ci'][1]}]"
                  f"     {s['false_accepts']:5d} [{s['false_accepts_ci'][0]},{s['false_accepts_ci'][1]}]"
                  f"     {s['question_at_miss']:6d} {s['question_at_hit']:6d}  {s['extras_by_class']}")
    return 0


def record_metrics(tags: list[str]) -> int:
    """Record each tag's score per match in the metrics ledger, series
    `teardrop_refusals`, part `lane/<tag>`."""
    from reticle.metrics import record as rec

    for tag in tags:
        for sid in DEV:
            p = OUT / tag / f"score_{sid}.json"
            if not p.is_file():
                continue
            sc = json.loads(p.read_text(encoding="utf-8"))
            vals = {k: sc[k] for k in ("hits", "misses", "hit_rate", "no_ring", "low_ncc", "extras",
                                       "false_accepts", "question_at_miss", "question_at_hit")}
            for k in ("hit_rate_ci", "extras_ci", "false_accepts_ci", "no_ring_ci", "low_ncc_ci"):
                vals[f"{k}_lo"], vals[f"{k}_hi"] = sc[k]
            for c, v in sc["extras_by_class"].items():
                vals[f"extras.{c}"] = v
            rec("teardrop_refusals", part=f"lane/{tag}", session=sid, values=vals,
                deps={"version": VERSION, "rule": "T1d", "p_ms": sc["p_ms"],
                      "minimap_object_version": sc["minimap_object_version"]},
                context={"task": TASK, "boot": f"{N_BOOT} round resamples, seed {SEED}"},
                note="T1d sets over minimap_object rows reread from the roi_cache (tag) or stored; "
                     "extras classes by rule, not player labels")
    return 0


# ----------------------------------------------------------------- the falsifier

def refit(sid: str, n: int) -> int:
    """TR1-TR3 over `n` of the session's teardrop-tagged T1d misses (stored rows)."""
    from reticle import minimap_objects as mo
    from reticle import teardrop
    from reticle.store import Store

    refuse(sid)
    p = OUT / "stored" / f"sets_{sid}.jsonl"
    if not p.is_file():
        score(sid, "stored")
    P = [json.loads(ln) for ln in p.open(encoding="utf-8")]
    Mi = [r for r in P if r["set"] == "miss" and miss_cause(r)]
    rng = np.random.default_rng(11)
    Mi = [Mi[i] for i in rng.permutation(len(Mi))[:n]]
    want = {r["frame_idx"] for r in Mi}
    FR = {}
    for line in rows_path("stored", sid).open(encoding="utf-8"):
        r = json.loads(line)
        if r.get("kind") == "frame" and r["frame_idx"] in want:
            FR[r["frame_idx"]] = r
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(why)
    sc = ctx["scale"]
    x0, y0, x1, y1 = ctx["rect"]
    ts = {}
    for r in Mi:
        ts.setdefault(FR[r["frame_idx"]]["t_ms"], []).append(r)
    res = []
    for s in ctx["cache"].samples(sorted(ts), rois=["minimap"]):
        crop = s.frame[y0:y1, x0:x1]
        red = teardrop.redness(crop)
        for r in ts[float(s.t_ms)]:
            px, py = r["px"]
            ref = [q for q in FR[r["frame_idx"]]["refused"] if q["reason"].startswith("teardrop")]
            q = min(ref, key=lambda q: math.hypot(q["x"] - px, q["y"] - py))
            tag = q["reason"].split(": ")[-1]
            f0 = teardrop.fit_icon(None, "enemy", q["x"], q["y"], scale=sc, key=red)
            seeds = [(q["x"] + dx, q["y"] + dy) for dx in range(-6, 7, 2) for dy in range(-6, 7, 2)]
            fits = [teardrop.fit_icon(None, "enemy", a, b, scale=sc, key=red) for a, b in seeds]
            best = max((f for f in fits if "ncc" in f), key=lambda f: f["ncc"])
            res.append({"tag": tag, "reproduced": f0.get("reason") == tag, "wide_read": bool(best["read"]),
                        "offset": math.hypot(best["x"] - q["x"], best["y"] - q["y"])})
    for tag in ("no_ring", "low_ncc", "all"):
        S = [x for x in res if tag == "all" or x["tag"] == tag]
        if S:
            off = np.array([x["offset"] for x in S])
            print(f"{tag:8s} n {len(S):3d} TR3 reproduced {np.mean([x['reproduced'] for x in S]):.3f} "
                  f"TR1 wide read {np.mean([x['wide_read'] for x in S]):.3f} "
                  f"TR2 offset>=2px {np.mean(off >= 2):.3f} (median {np.median(off):.2f} px)")
    return 0


# ----------------------------------------------------------------- the sheet

def sheet(tags: list[str], out_png: str, per: int = 4) -> int:
    """Misses of tag A that tag B hits, beside the rows of both, per match."""
    import cv2

    from reticle import minimap_objects as mo
    from reticle.store import Store

    a, b = tags
    tiles = []
    rng = np.random.default_rng(SEED)
    for sid in DEV:
        A = {(r["k"], r["j"]): r for r in map(json.loads, (OUT / a / f"sets_{sid}.jsonl").open())
             if r["set"] in ("hit", "miss")}
        B = {(r["k"], r["j"]): r for r in map(json.loads, (OUT / b / f"sets_{sid}.jsonl").open())
             if r["set"] in ("hit", "miss")}
        rec = [k for k, r in A.items() if r["set"] == "miss" and miss_cause(r) and B.get(k, {}).get("set") == "hit"]
        pick = [rec[i] for i in rng.permutation(len(rec))[:per]]
        rows = {}
        for tg in (a, b):
            want = {A[k]["frame_idx"] for k in pick}
            for line in rows_path(tg, sid).open(encoding="utf-8"):
                r = json.loads(line)
                if r.get("kind") == "frame" and r["frame_idx"] in want:
                    rows[(tg, r["frame_idx"])] = r
        ctx, _ = mo.object_context(Store(STORE), sid)
        sc = ctx["scale"]
        x0, y0, x1, y1 = ctx["rect"]
        byt = {A[k]["t_cap"]: k for k in pick}
        held = np.asarray(ctx["cache"].holds(), float)
        tmap = {float(held[np.argmin(np.abs(held - t))]): k for t, k in byt.items()}
        H = int(round(28 * sc))
        Z = max(4, int(round(6 / sc)))
        for s in ctx["cache"].samples(sorted(tmap), rois=["minimap"]):
            k = tmap[float(s.t_ms)]
            r = A[k]
            crop = s.frame[y0:y1, x0:x1]
            cx, cy = int(round(r["px"][0])), int(round(r["px"][1]))
            pad = cv2.copyMakeBorder(crop, H, H, H, H, cv2.BORDER_CONSTANT, value=(40, 40, 40))
            win = pad[cy:cy + 2 * H + 1, cx:cx + 2 * H + 1]
            pan = []
            for tg in (a, b):
                img = cv2.resize(win, None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)  # display only
                fr = rows.get((tg, r["frame_idx"]), {})

                def P2(x, y):
                    return int(round((x - cx + H + 0.5) * Z)), int(round((y - cy + H + 0.5) * Z))
                cv2.drawMarker(img, P2(*r["px"]), (255, 0, 255), cv2.MARKER_CROSS, 16, 2)
                for e in fr.get("enemies", []):
                    cv2.circle(img, P2(e["x"], e["y"]), int(e["r"] * Z), (0, 255, 0), 2)
                for q in fr.get("refused", []):
                    cv2.drawMarker(img, P2(q["x"], q["y"]), (0, 255, 255), cv2.MARKER_TILTED_CROSS, 14, 2)
                for q in fr.get("questions", []):
                    p_ = P2(q["x"], q["y"])
                    cv2.rectangle(img, (p_[0] - 8, p_[1] - 8), (p_[0] + 8, p_[1] + 8), (0, 140, 255), 2)
                cv2.putText(img, f"{tg} {sid[:6]} {s.t_ms / 1000:.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (255, 255, 255), 2)
                cv2.putText(img, f"{tg} {sid[:6]} {s.t_ms / 1000:.1f}s", (4, 16), cv2.FONT_HERSHEY_SIMPLEX,
                            0.5, (0, 0, 0), 1)
                pan.append(img)
            t = np.concatenate([pan[0], np.full((pan[0].shape[0], 6, 3), 255, np.uint8), pan[1]], 1)
            tiles.append(t)
    Hm = max(t.shape[0] for t in tiles)
    Wm = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, Hm - t.shape[0], 0, Wm - t.shape[1], cv2.BORDER_CONSTANT,
                                value=(255, 255, 255)) for t in tiles]
    cols = 3
    while len(tiles) % cols:
        tiles.append(np.full((Hm, Wm, 3), 255, np.uint8))
    img = np.concatenate([np.concatenate(sum([[t, np.full((Hm, 12, 3), 255, np.uint8)]
                                              for t in tiles[i:i + cols]], [])[:-1], 1)
                          for i in range(0, len(tiles), cols)], 0)
    cv2.imwrite(out_png, img)
    print(out_png, img.shape)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("refit")
    p.add_argument("session")
    p.add_argument("--n", type=int, default=200)
    p = sub.add_parser("pings")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p = sub.add_parser("reread")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", help="the owner gate reads this `pings` reread")
    p.add_argument("--ping-own-px", type=float, help="the ping gate's reach, base px")
    p.add_argument("--no-owner-gate", action="store_true", help="turn the owner gate off")
    p = sub.add_parser("gate")
    p.add_argument("--off", required=True, help="the gate-off tag")
    p.add_argument("--tags", required=True)
    p.add_argument("--no-record", action="store_true")
    p = sub.add_parser("score")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", help="class extras by this `pings` reread")
    p = sub.add_parser("compare")
    p.add_argument("--tags", required=True)
    p = sub.add_parser("record")
    p.add_argument("--tags", required=True)
    p = sub.add_parser("sheet")
    p.add_argument("--tags", required=True)
    p.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    _idle()
    if a.cmd == "refit":
        return refit(a.session, a.n)
    if a.cmd == "pings":
        for s in a.sessions:
            pings(s, a.tag)
        return 0
    if a.cmd == "reread":
        for s in a.sessions:
            reread(s, a.tag, a.pings, a.ping_own_px, not a.no_owner_gate)
        return 0
    if a.cmd == "gate":
        return gate(a.off, a.tags.split(","), not a.no_record)
    if a.cmd == "score":
        for s in a.sessions:
            score(s, a.tag, ptag=a.pings)
        return 0
    if a.cmd == "compare":
        return compare(a.tags.split(","))
    if a.cmd == "record":
        return record_metrics(a.tags.split(","))
    return sheet(a.tags.split(","), a.out)


if __name__ == "__main__":
    sys.exit(main())
