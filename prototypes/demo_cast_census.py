r"""What each ability cast draws on the minimap in the solo demos: a census.

    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py cache [--session S] [--check]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py casts [--record]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py residual [--key K ...] [--record]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py montage
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py read [--add ROWS.jsonl]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py table [--record]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py label [--dry-run]

Why this exists
---------------
The minimap channel needs to know what the player's own cast draws, and for
how long, before it can bind a drawn object to a cast. The domain facts
covered a dozen abilities; the solo demos exercise over a hundred. This is
a census of those casts for the player to confirm, not a detector.

What each step does
-------------------
`cache` gives each solo demo the production whole-capture minimap crop cache
(`reticle scan <sid> --only roi_cache --cache-roi minimap --cache-hz 15`,
NVDEC, Idle priority, one scan at a time) and checks three samples per demo
against decoded frames. Everything after it reads only those crops.

`casts` reads the tray at 2 Hz with `reticle.tray`, its owner, compares the
drops with the stored cast caches, and keeps the verdicts I gave, by eye from
the tray strips, on every doubtful drop (`TRAY_VERDICTS`). A drop judged a
wash over a full bar leaves the census. `reticle tray` cannot run here: it
needs the HUD and rounds tables a demo lacks.

`residual` measures, per cast, what changed on the minimap against the -1 s
frame, on baked geometry only, and summarises each component's onset, peak
and censored lifetime. Its class is a crude rule fixed before the blind read.

`montage` draws a blind and a keyed image per cast; `read` appends the blind
read; `table` opens the key only after every blind row exists and tabulates
per ability against the residual and the ledger's prior; `label` lets the
player correct each class on the keyed montage.

What it does not do
-------------------
It writes no events and no labels. It names no enemy or ally ability: a solo
demo has one player. It does not fit shapes; `reticle.ability_shapes` owns
that for the three forms it knows. The residual's hue bins follow the world's
tint through the translucent widget, so a hue-only class is weak evidence.

Rests on: the baked `(map, profile)` geometry (`reticle.geometry`,
`reticle.lighting`, `passes.SessionContext.floor`), `reticle.tray`,
`ability_shapes.teal`, and `minimap.widget_drawn`/`self_icons`. Findings and
the appearance table: `docs/DEMO_CAST_CENSUS.md`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, metrics  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import ROI_CACHE_VERSION, RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "demo-cast-census"
VERSION = "demo-cast-census-0.1.0"
TOOL = "demo_cast_census"
#: The demo that predates the custom-game tags; it is still a solo demo.
EXTRA_DEMOS = ("2ba870ccbd50",)
CACHE_HZ = 15.0
IDLE = 0x40


def idle() -> None:
    """Run this process at Idle priority: the CPU is shared with the player's jobs.

    The handle types are declared: with ctypes' default `int`, the pseudo-handle
    of `GetCurrentProcess` reaches `SetPriorityClass` truncated to 32 bits on
    x64 and the call fails silently, leaving the process at Normal.
    """
    if os.name != "nt":
        return
    k = ctypes.windll.kernel32
    k.GetCurrentProcess.restype = ctypes.c_void_p
    k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    k.GetPriorityClass.argtypes = [ctypes.c_void_p]
    if not k.SetPriorityClass(k.GetCurrentProcess(), IDLE):
        raise SystemExit("could not lower this process to Idle priority")


def _man(sid: str) -> dict:
    return geometry.manifest(sid, STORE)


def _agents() -> dict[str, str]:
    """Tag spelling -> catalogue agent name (`kayo` -> `KAY/O`)."""
    ref = json.loads((STORE / "reference" / "abilities.json").read_text(encoding="utf-8"))
    return {name.lower().replace("/", ""): name for name in ref["agents"]}


def demos() -> list[tuple[str, str]]:
    """(session, catalogue agent) for every solo demo, in session order."""
    names = _agents()
    out = []
    for f in sorted((STORE / "manifests").glob("*.json")):
        tags = json.loads(f.read_text(encoding="utf-8")).get("tags") or []
        if "ability-demo" not in tags and f.stem not in EXTRA_DEMOS:
            continue
        agent = next((names[t] for t in tags if t in names), None)
        out.append((f.stem, agent))
    return out


def open_cache(sid: str) -> tuple[RoiCache | None, str | None]:
    man = _man(sid)
    return RoiCache.load(STORE, man, get_profile(man["source_profile"]), "minimap")


def _usage_row(sid: str) -> dict | None:
    from reticle.usage import load
    rows = load(STORE, sid)
    return rows[-1] if rows else None


def check_crops(sid: str, n: int = 3) -> dict:
    """Read `n` cached samples back and compare each rect to the decoded frame."""
    import cv2
    cache, why = open_cache(sid)
    if cache is None:
        return {"refused": why}
    man = _man(sid)
    ts = np.unique(cache.t_ms)
    pick = [float(ts[int(i)]) for i in np.linspace(len(ts) // 5, len(ts) - 3, n)]
    cap = cv2.VideoCapture(man["source"]["path"])
    same = total = 0
    try:
        for smp in cache.samples(pick):
            cap.set(cv2.CAP_PROP_POS_FRAMES, smp.frame_idx)
            ok, fr = cap.read()
            for x0, y0, x1, y1 in cache.record["rects"]:
                total += 1
                same += bool(ok) and np.array_equal(smp.frame[y0:y1, x0:x1], fr[y0:y1, x0:x1])
    finally:
        cap.release()
    return {"rects_identical": same, "rects_checked": total}


def cmd_cache(args) -> int:
    """Write each demo's whole-capture minimap crop cache, one scan at a time."""
    todo = [(s, a) for s, a in demos() if not args.session or s in args.session]
    refusals_path = OUT / "cache_refusals.json"
    refusals = (json.loads(refusals_path.read_text(encoding="utf-8"))
                if refusals_path.is_file() else {})
    for sid, agent in todo:
        cache, _why = open_cache(sid)
        have = (cache is not None and cache.record.get("spans") is None
                and float(cache.record["hz"]) == CACHE_HZ)
        wall = None
        if not have or args.force:
            env = dict(os.environ, RETICLE_DECODE=args.decode, OMP_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", PYTHONUTF8="1")
            cmd = [sys.executable, "-m", "reticle", "scan", sid, "--only", "roi_cache",
                   "--cache-roi", "minimap", "--cache-hz", f"{CACHE_HZ:g}"]
            if args.force:
                cmd.append("--force")
            t0 = time.perf_counter()
            p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                               creationflags=IDLE if os.name == "nt" else 0)
            wall = time.perf_counter() - t0
            if p.returncode != 0:
                refusals[sid] = {"agent": agent, "returncode": p.returncode,
                                 "stderr": p.stderr[-2000:], "stdout": p.stdout[-2000:]}
                OUT.mkdir(parents=True, exist_ok=True)
                refusals_path.write_text(json.dumps(refusals, indent=1), encoding="utf-8")
                print(f"{sid} {agent}: scan refused ({p.returncode}): "
                      f"{(p.stderr or p.stdout).strip().splitlines()[-1:]}", flush=True)
                continue
            cache, _why = open_cache(sid)
        elif not args.record_existing:
            print(f"{sid} {agent}: cache current, skipped", flush=True)
            continue
        use = _usage_row(sid) or {}
        rec = cache.record
        values = {"frames": int(rec["frames"]), "bytes": int(rec["bytes"]),
                  "mb": round(rec["bytes"] / 2**20, 1),
                  "pass_s": round(use.get("pass_ns", 0) / 1e9, 2),
                  "source_s": round((use.get("source_calls") or {}).get("total_ns", 0) / 1e9, 2)}
        if wall is not None:
            values["wall_s"] = round(wall, 1)
        if args.check:
            values.update(check_crops(sid))
        metrics.record(TOOL, part="cache", session=sid, values=values,
                       deps={"roi_cache": ROI_CACHE_VERSION, "hz": CACHE_HZ,
                             "decode": args.decode, "version": VERSION},
                       context={"agent": agent, "usage_run": use.get("run_id")},
                       note="whole-capture minimap+hud_abilities crop cache of a solo demo")
        print(f"{sid} {agent}: {values}", flush=True)
    return 0


# ------------------------------------------------------------------ casts

TRAY_STEP_S = 0.5
#: A stored cast and a drop read here are the same cast within this many seconds.
MATCH_S = 0.75
SLOTS = ("C", "Q", "E", "X")


def tray_reader():
    """The tray's owner, `reticle.tray`, and its version stamp."""
    from reticle import tray
    from reticle.version import TRAY_VERSION
    return tray, f"reticle.tray {TRAY_VERSION}"


def cache_grid(t_ms, t0: float, t1: float, step_s: float) -> list[float]:
    """Cached times nearest a regular grid inside [t0, t1]: `reticle tray`'s grid."""
    from reticle.cli import _cache_grid
    return _cache_grid(t_ms, t0, t1, step_s)


def kit(agent: str | None) -> dict[str, dict]:
    """{slot: {name, deployment, functions, charges}} from the catalogue."""
    if agent is None:
        return {}
    ref = json.loads((STORE / "reference" / "abilities.json").read_text(encoding="utf-8"))
    entry = ref["agents"].get(agent) or {}
    return {a["key"]: {"name": a["name"],
                       "deployment": (a.get("infobox") or {}).get("Deployment Type"),
                       "functions": a.get("functions"), "charges": a.get("charges")}
            for a in entry.get("abilities", []) if a.get("key")}


def stored_casts(sid: str) -> list[list] | None:
    """The older prototype reader's cast cache, or None if the demo has none."""
    got = sorted((STORE / "casts").glob(f"{sid}.step0.5.*.json"))
    return json.loads(got[0].read_text(encoding="utf-8")) if got else None


def read_tray(sid: str, reader) -> dict:
    """Slot counts at 2 Hz from the cached tray crops, and every cached time."""
    cache, why = open_cache(sid)
    if cache is None:
        return {"refused": why}
    grid = cache_grid(cache.t_ms, 0.0, float(cache.t_ms.max()), TRAY_STEP_S)
    ts, counts, clean = [], [], []
    for smp in cache.samples(grid, rois=["hud_abilities"]):
        c, ok = reader.slot_counts(smp.frame)
        ts.append(float(smp.t_ms))
        counts.append(c)
        clean.append(ok)
    return {"cache": cache, "ts": ts, "counts": np.asarray(counts, float),
            "clean": np.asarray(clean, bool)}


def refine(cache, reader, t_prev: float, t_drop: float, slot: str, ref: np.ndarray,
           frm: float) -> float | None:
    """The first cached sample in (t_prev, t_drop] where the slot has fallen.

    The 2 Hz drop says only that the charge fell in the half second before the
    sample; the cache holds every sample in between, read with the same reader
    against the same per-slot reference.
    """
    k = SLOTS.index(slot)
    t = np.unique(cache.t_ms)
    between = [float(x) for x in t[(t > t_prev) & (t <= t_drop)]]
    for smp in cache.samples(between, rois=["hud_abilities"]):
        c, ok = reader.slot_counts(smp.frame)
        if ok and frm - c[k] / max(ref[k], 1.0) >= reader.CAST_DROP:
            return float(smp.t_ms)
    return None


def match(mine: list[dict], stored: list[list]) -> tuple[list, list, list]:
    """One-to-one same-slot pairs within MATCH_S, nearest first."""
    pairs = sorted(((abs(m["t_ms"] / 1000.0 - s[0]), i, j)
                    for i, m in enumerate(mine) for j, s in enumerate(stored)
                    if m["slot"] == s[1] and abs(m["t_ms"] / 1000.0 - s[0]) <= MATCH_S))
    used_i, used_j, out = set(), set(), []
    for _d, i, j in pairs:
        if i not in used_i and j not in used_j:
            used_i.add(i)
            used_j.add(j)
            out.append((i, j))
    added = [i for i in range(len(mine)) if i not in used_i]
    missing = [j for j in range(len(stored)) if j not in used_j]
    return out, added, missing


#: A drop is looked at by eye when the stored cast cache disagrees with it, or
#: when its slot starts above CHECK_FROM or stays above CHECK_TO of the slot's
#: reference: a wash or glow over the tray, not a spent charge.
CHECK_FROM, CHECK_TO = 1.05, 0.7
#: Verdicts read from the cached tray crops (`casts --strips` renders them to
#: OUT/tray_strips/tray_<sid>_<t>.png), keyed `sid:slot:t` with t the 2 Hz drop
#: time in seconds. `false`: the slot's bar never fell. The census reads every
#: drop not judged false.
TRAY_VERDICTS = {
    "02cf738b1c8f:E:14.50": ("false", "E full 13.0-15.3 s; the bow's cyan glow lifts E"),
    "02cf738b1c8f:Q:15.03": ("false", "Q full 13.0-15.3 s; the bow's glow lifts Q to 978"),
    "02cf738b1c8f:Q:16.53": ("false", "the glow lifts Q at the 16.03 s sample, counted clean; "
                                      "the half drop is 15.5 s"),
    "02cf738b1c8f:E:23.07": ("real", "E full under the bow's glow to 22.07 s, empty at 22.15 s; "
                                     "read across the refused samples"),
    "33db0d21fa32:C:17.07": ("real", "C full to 16.23 s, empty from 16.30 s"),
    "ad6b67cdf91d:C:14.50": ("real", "C falls from one charge to none between 14.10 and 14.17 s"),
    "f9703a4b5a47:C:12.50": ("false", "C holds one charge 11.0-12.83 s; a dark overlay at the "
                                      "11.50 s sample reads 0.85 and counts clean; C falls at "
                                      "12.90 s (the 13.03 s row)"),
    "ff19748eea8c:Q:13.03": ("real", "Q full to 12.43 s, empty at 12.70 s after a cyan gust"),
    "2ba870ccbd50:X:10.03": ("false", "X full throughout; a teal wash lifts X at 9.5 s"),
    "2ba870ccbd50:E:22.57": ("false", "a white-yellow flood 22.0-25.2 s; E reads three "
                                      "charges before and after"),
    "29eff6920e8f:C:12.03": ("real", "C full to 11.83 s, empty at 11.90 s"),
    "29eff6920e8f:Q:24.57": ("real", "Q falls from two charges to one at 24.57 s"),
    "29eff6920e8f:Q:33.55": ("real", "Q falls from one charge to none at 33.40 s"),
    "29eff6920e8f:E:41.52": ("real", "E full to 41.45 s, empty at 41.52 s"),
    "29eff6920e8f:X:45.55": ("real", "X full to 45.20 s, empty at 45.27 s"),
    "afa5bc60b935:C:7.50": ("real", "C full to 7.00 s, empty at 7.08 s"),
    "afa5bc60b935:Q:18.57": ("real", "Q bar full to 18.07 s, grey at 18.15 s; the icon stays "
                                     "white while the cloud is out"),
    "afa5bc60b935:E:37.02": ("real", "E full to 36.88 s, empty at 36.95 s"),
    "afa5bc60b935:X:90.52": ("real", "X bar and pips empty from 90.15 s; all four icons dim at "
                                     "once, 3 s before the capture ends"),
    "2f4ef4e8da23:E:29.57": ("false", "E empty before and after; a white-teal wave over the tray"),
    "2f4ef4e8da23:X:32.50": ("real", "X full with pips at 32.07 s, empty at 33.13 s once the "
                                     "overlay clears"),
    "5a63cc4fecfc:E:25.57": ("false", "E holds one charge 24.2-25.8 s; a teal ghost lifts E at "
                                      "25.07 s; the drop is 25.9 s"),
    "6ab7a9e99235:E:17.57": ("real", "E falls from two charges to one between 17.23 and 17.32 s"),
    "6bb88dba5d2c:X:42.55": ("false", "a green screen wash; X stays full until 44.0 s"),
    "ad6b67cdf91d:C:7.00": ("real", "C falls from two charges to one at 6.6 s"),
    "ad6b67cdf91d:C:12.50": ("false", "C holds one charge 11.0-13.3 s; teal sweeps over the tray"),
    "ad6b67cdf91d:X:38.05": ("false", "a green wash 36.5-37.9 s; X stays full until 45.0 s"),
    "b9558488a607:X:14.50": ("false", "X full 13.0-15.3 s; a pale blue flash lifts X at 14.03 s"),
    "f1cf160b213d:E:22.57": ("false", "E full from 21.82 s to 23.3 s; a blue streak lifts E"),
    "f9703a4b5a47:X:19.07": ("false", "a blue-teal wash 17.98-18.48 s; X stays full"),
}
#: Stored casts no drop here matched, judged the same way.
STORED_VERDICTS = {
    "481336df9adb:X:29.50": ("false", "X full through 30.2 s under orange flame; X falls at 34.5 s"),
    "6ab7a9e99235:X:22.50": ("false", "X full 21.1-23.2 s; E falls at 21.73 s, which both read"),
    "ad6b67cdf91d:Q:12.50": ("false", "Q full 11.0-13.3 s; teal sweeps over the tray"),
    "e78e75b2d191:E:18.50": ("false", "E holds both charges 17.1-19.2 s under the purple "
                                      "placement view; E falls at 19.8 s"),
}
STRIPS = OUT / "tray_strips"


def vkey(sid: str, slot: str, t_s: float) -> str:
    return f"{sid}:{slot}:{t_s:.2f}"


def needs_eye(c: dict) -> bool:
    return c["stored"] is None or c["from"] > CHECK_FROM or c["to"] >= CHECK_TO


def tray_strip(cache, reader, t_s: float, path: Path) -> None:
    """The cached tray crops from t-1.5 s to t+0.8 s, each with its slot counts."""
    import cv2
    t0 = t_s * 1000.0
    tt = np.unique(cache.t_ms)
    sel = [float(x) for x in tt[(tt >= t0 - 1500) & (tt <= t0 + 800)]]
    tx0, ty0, tx1, ty1 = cache.rect_of("hud_abilities")
    rows = []
    for smp in cache.samples(sel, rois=["hud_abilities"]):
        c, ok = reader.slot_counts(smp.frame)
        crop = smp.frame[ty0:ty1, tx0:tx1]
        pad = np.zeros((crop.shape[0], 330, 3), np.uint8)
        _label(pad, f"{smp.t_ms / 1000:6.2f}s {'' if ok else 'UNCLEAN'}", (4, 20), 0.55)
        _label(pad, " ".join(f"{k}{v}" for k, v in zip(SLOTS, c)), (4, 45), 0.55)
        rows.append(np.hstack([pad, crop]))
    half = (len(rows) + 1) // 2
    left, right = rows[:half], rows[half:]
    right += [np.zeros_like(rows[0])] * (len(left) - len(right))
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.hstack([np.vstack(left), np.vstack(right)]))


def cmd_casts(args) -> int:
    """Tray drops from the cached crops, compared with the stored cast caches."""
    reader, name = tray_reader()
    rows, per = [], {}
    tot = {"demos": 0, "drops": 0, "suspect": 0, "stored": 0, "matched": 0, "added": 0,
           "missing": 0, "refined": 0}
    unjudged = []
    for sid, agent in demos():
        got = read_tray(sid, reader)
        if "refused" in got:
            print(f"{sid} {agent}: no cache ({got['refused']})")
            continue
        ts, counts, clean = got["ts"], got["counts"], got["clean"]
        if hasattr(reader, "drops"):
            dr = reader.drops(ts, counts, clean)
        else:
            dr = [{"t_ms": t * 1000.0, "slot": k, "from": a, "to": b, "suspect": s}
                  for t, k, a, b, s in reader.casts([t / 1000.0 for t in ts], counts, clean)]
        f = reader.fills(counts, clean)
        with np.errstate(divide="ignore", invalid="ignore"):
            r = np.where(f > 0, counts / np.where(f > 0, f, 1), np.nan)
        ref = np.nanmax(np.where(np.isfinite(r), r, np.nan), axis=0)
        ref = np.where(np.isfinite(ref), ref, 1.0)
        k_kit = kit(agent)
        mine = []
        for d in dr:
            i = ts.index(d["t_ms"])
            back = 3.5 if d.get("across_gap") else TRAY_STEP_S + 0.1
            t_prev = max(ts[0] - 1, d["t_ms"] - back * 1000.0)
            t_ref = refine(got["cache"], reader, t_prev, d["t_ms"], d["slot"], ref, d["from"])
            mine.append({"sid": sid, "agent": agent, "slot": d["slot"],
                         "ability": (k_kit.get(d["slot"]) or {}).get("name"),
                         "deployment": (k_kit.get(d["slot"]) or {}).get("deployment"),
                         "t_ms": float(d["t_ms"]), "t_refined_ms": t_ref,
                         "from": float(d["from"]), "to": float(d["to"]),
                         "suspect": bool(d["suspect"]),
                         **{k: bool(d[k]) for k in ("forced", "cooccur", "across_gap") if k in d},
                         "sample_index": i, "source_reader": name})
        st = stored_casts(sid)
        pairs, added, missing = match(mine, st or [])
        for i, j in pairs:
            mine[i]["stored"] = st[j]
        for i in added:
            mine[i]["stored"] = None
        for m in mine:
            m["stored_cache"] = st is not None
            v = TRAY_VERDICTS.get(vkey(sid, m["slot"], m["t_ms"] / 1000.0))
            m["tray_verdict"], m["tray_verdict_reason"] = v if v else (None, None)
            m["census"] = m["tray_verdict"] != "false"
            if needs_eye(m) and v is None:
                unjudged.append(vkey(sid, m["slot"], m["t_ms"] / 1000.0))
        miss = []
        for j in missing:
            v = STORED_VERDICTS.get(vkey(sid, st[j][1], st[j][0]))
            miss.append({"stored": st[j], "tray_verdict": v[0] if v else None,
                         "tray_verdict_reason": v[1] if v else None})
            if v is None:
                unjudged.append("stored " + vkey(sid, st[j][1], st[j][0]))
        if args.strips:
            for t_s in ([m["t_ms"] / 1000.0 for m in mine if needs_eye(m)]
                        + [st[j][0] for j in missing]):
                tray_strip(got["cache"], reader, t_s, STRIPS / f"tray_{sid}_{t_s:.2f}.png")
        per[sid] = {"agent": agent, "drops": len(mine), "stored": None if st is None else len(st),
                    "matched": len(pairs), "added": [mine[i]["t_ms"] / 1000.0 for i in added],
                    "added_slots": [mine[i]["slot"] for i in added],
                    "missing": miss, "samples": len(ts), "clean": int(clean.sum())}
        tot["demos"] += 1
        tot["drops"] += len(mine)
        tot["suspect"] += sum(m["suspect"] for m in mine)
        tot["refined"] += sum(m["t_refined_ms"] is not None for m in mine)
        if st is not None:
            tot["stored"] += len(st)
            tot["matched"] += len(pairs)
            tot["added"] += len(added)
            tot["missing"] += len(missing)
        rows += mine
        print(f"{sid} {agent:<9} drops {len(mine):2d} stored {'-' if st is None else len(st):>2} "
              f"matched {len(pairs):2d} added {per[sid]['added']} {per[sid]['added_slots']} "
              f"missing {per[sid]['missing']}")
    eyed = [m for m in rows if needs_eye(m)]
    tot.update({
        "eyed": len(eyed),
        "eyed_false": sum(m["tray_verdict"] == "false" for m in eyed),
        "added_real": sum(m["stored_cache"] and m["stored"] is None
                          and m["tray_verdict"] == "real" for m in rows),
        "added_false": sum(m["stored_cache"] and m["stored"] is None
                           and m["tray_verdict"] == "false" for m in rows),
        "no_stored_cache_demos": sum(p["stored"] is None for p in per.values()),
        "no_stored_cache_real": sum(not m["stored_cache"] and m["tray_verdict"] == "real"
                                    for m in rows),
        "no_stored_cache_false": sum(not m["stored_cache"] and m["tray_verdict"] == "false"
                                     for m in rows),
        "matched_false": sum(m["stored"] is not None and m["tray_verdict"] == "false"
                             for m in rows),
        "missing_false": sum(x["tray_verdict"] == "false" for p in per.values()
                             for x in p["missing"]),
        "stays_full": sum(m["to"] >= 0.8 for m in rows),
        "stays_full_false": sum(m["to"] >= 0.8 and m["tray_verdict"] == "false" for m in rows),
        "census": sum(m["census"] for m in rows),
        "unjudged": len(unjudged)})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "casts.json").write_text(json.dumps({"version": VERSION, "source_reader": name,
                                                "step_s": TRAY_STEP_S, "match_s": MATCH_S,
                                                "check": {"from_above": CHECK_FROM,
                                                          "to_at_least": CHECK_TO},
                                                "per_demo": per, "casts": rows}, indent=1),
                                    encoding="utf-8")
    print(tot)
    if unjudged:
        print("look at these by eye (casts --strips):", unjudged)
    if args.record:
        metrics.record(TOOL, part="casts", session="demos", values=tot,
                       deps={"reader": name, "step_s": TRAY_STEP_S, "match_s": MATCH_S,
                             "roi_cache": ROI_CACHE_VERSION, "version": VERSION},
                       note="tray drops from cached hud_abilities crops against casts/*.step0.5.*.json")
    return 0


# --------------------------------------------------------------- residual

#: The per-cast window, relative to the cast; the frame at BASE_S is the
#: baseline every other frame is DIFFERENCED against (never a background map).
WINDOW_S = (-2.0, 12.0)
BASE_S = -1.0
#: Frames in this range give the pre-cast level of each component.
PRE_S = (-2.0, -0.25)
#: Onset is searched from here: the drop time is refined to one cache step.
ONSET_FROM_S = -0.25
#: A component is on when its new pixels exceed the pre-cast maximum by this
#: many px for PERSIST_N consecutive drawn frames. 40 px is a disc of radius
#: 3.6 px, an eighth of the self icon's area (r 10).
MARGIN_PX = 40
PERSIST_N = 2
#: A component that stays below its threshold for this long has ended.
GONE_S = 1.0
#: Colour rules. Teal is `ability_shapes.teal`'s weight cut here; white is
#: bright and achromatic; the other hues are saturated pixels outside the teal
#: hue band (`ability_shapes.TEAL_H`) and the self key.
TEAL_W_MIN = 0.3
WHITE_S_MAX, WHITE_V_MIN = 40, 200
HUE_S_MIN, HUE_V_MIN = 70, 90
#: The art footprint grown by this many px is the support (the art's own
#: search dilation, `ability_shapes.SUPPORT_DILATE`).
SUPPORT_DILATE = 9
#: White and hue are read on the baked floor eroded this many px.
FLOOR_ERODE = 2
HUE_BINS = tuple(range(0, 360, 30))
COMPONENTS = (("dark", "lit", "teal", "teal_all", "white")
              + tuple(f"hue{d:03d}" for d in HUE_BINS))
#: Components a residual class may rest on; `lit` is the player's own cone.
CLASSED = tuple(c for c in COMPONENTS if c != "lit")
MONTAGE_S = (-1.0, 0.0, 0.5, 1.0, 2.0, 4.0, 8.0)
#: Mask groups kept at the montage frames for the keyed overlay.
OVERLAY = {"dark": ("dark",), "teal": ("teal_all",), "white": ("white",),
           "hue": tuple(f"hue{d:03d}" for d in HUE_BINS)}
CLASSES = ("nothing", "dark_disc", "teal_ring", "teal_line", "wall_segments",
           "compact_icon", "pale_region", "brief_flash", "other", "unsure")


def teal_weight(crop):
    """The ally teal's weight per pixel: `ability_shapes.teal`, its owner."""
    from reticle.ability_shapes import teal
    return teal(crop)


class Geo:
    """A session's baked (map, profile) geometry: never its own pixels."""

    def __init__(self, sid: str):
        import cv2

        from reticle import lighting, passes
        from reticle.store import Store
        man = _man(sid)
        ctx = passes.SessionContext(store=Store(STORE), manifest=man,
                                    profile=get_profile(man["source_profile"]))
        self.key = geometry.key_of(sid, STORE)
        with np.load(geometry.path_of(sid, STORE)) as z:
            self.ref = lighting.reference(z)
        self.floor = ctx.floor()
        self.sgray = ctx.sgray()
        H, W = self.floor.shape
        self.support = geometry.footprint(sid, STORE, dilate=SUPPORT_DILATE, shape=(H, W))
        if self.support is None:
            raise SystemExit(f"{sid}: no art footprint for {self.key}")
        from reticle.ability_shapes import widget
        _R, self.disc = widget((H, W))
        self.k3 = np.ones((3, 3), np.uint8)
        # The floor's anti-aliased rim lets the world's tint through and moves
        # with the camera; white and hue are read inside it.
        self.floor_in = cv2.erode(self.floor.astype(np.uint8), self.k3,
                                  iterations=FLOOR_ERODE).astype(bool)
        self.cv2 = cv2


def frame_masks(crop, geo: Geo) -> tuple[bool, dict, dict | None]:
    """(widget drawn, {component: mask}, self icon) for one minimap crop."""
    from reticle import lighting, minimap
    from reticle.minimap_dark import SELF_MARGIN_PX
    cv2 = geo.cv2
    if not minimap.widget_drawn(crop, geo.sgray, geo.floor):
        return False, {}, None
    selfs = minimap.self_icons(crop, geo.floor, require_facing=False)
    me = max(selfs, key=lambda s: s["cov"]) if selfs else None
    off = np.zeros(crop.shape[:2], np.uint8)
    if me is not None:
        cv2.circle(off, (int(round(me["cx"])), int(round(me["cy"]))),
                   int(me["r"]) + SELF_MARGIN_PX, 1, -1)
    off = off.astype(bool)
    keep = geo.support & ~off
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    tw = teal_weight(crop) >= TEAL_W_MIN
    from reticle.ability_shapes import TEAL_H
    in_teal = (h >= TEAL_H[0]) & (h <= TEAL_H[1])
    lit = lighting.raw_lit(crop, geo.ref) & ~off
    # White and the other hues are read on the baked floor only: the void
    # shows the world through the widget, and the world changes every frame.
    on_floor = geo.floor_in & ~off
    m = {"dark": lighting.raw_dark(crop, geo.ref) & ~off,
         "lit": lit,
         "teal": tw & keep,
         "teal_all": tw & geo.disc & ~off,
         "white": (s < WHITE_S_MAX) & (v >= WHITE_V_MIN) & on_floor & ~lit}
    sat = (s >= HUE_S_MIN) & (v >= HUE_V_MIN) & ~in_teal & ~minimap.self_mask(crop) & on_floor
    deg = h.astype(np.int32) * 2
    for d in HUE_BINS:
        m[f"hue{d:03d}"] = sat & (deg >= d) & (deg < d + 30)
    return True, m, me


def largest(mask, geo: Geo, me: dict | None) -> list[float]:
    """[area, cx, cy, w, h, touches_self] of the largest connected component."""
    n, lbl, st, cen = geo.cv2.connectedComponentsWithStats(mask.astype(np.uint8), 8)
    if n <= 1:
        return [0, np.nan, np.nan, 0, 0, 0]
    i = 1 + int(np.argmax(st[1:, 4]))
    touch = 0
    if me is not None:
        ys, xs = np.nonzero(lbl == i)
        d = np.hypot(xs - me["cx"], ys - me["cy"]).min()
        touch = int(d <= me["r"] + 8)
    return [int(st[i, 4]), float(cen[i][0]), float(cen[i][1]), int(st[i, 2]), int(st[i, 3]), touch]


def component_summary(t: np.ndarray, drawn: np.ndarray, new: np.ndarray,
                      big: np.ndarray, t_end: float, end_reason: str) -> dict:
    """Onset, peak, lifetime and censoring of one component's new-pixel series."""
    pre = drawn & (t >= PRE_S[0]) & (t < PRE_S[1]) & (np.abs(t - BASE_S) > 1e-6)
    pre_max = float(new[pre].max()) if pre.any() else 0.0
    thr = pre_max + MARGIN_PX
    on = drawn & (new > thr)
    idx = np.nonzero((t >= ONSET_FROM_S) & (t <= t_end))[0]
    onset = None
    for a, b in zip(idx, idx[1:]):
        if on[a] and on[b] and b == a + 1:
            onset = int(a)
            break
    out = {"pre_max": pre_max, "threshold": thr, "onset_s": None}
    if onset is None:
        return out
    gap_before = bool((~drawn[(t >= ONSET_FROM_S) & (t < t[onset])]).any())
    last, end, reason = onset, None, None
    for j in range(onset + 1, len(t)):
        if t[j] > t_end:
            reason = end_reason
            break
        if not drawn[j]:
            reason = "widget_not_drawn"
            break
        if on[j]:
            last = j
        elif t[j] - t[last] >= GONE_S:
            end = last
            break
    else:
        reason = end_reason
    alive = slice(onset, (end if end is not None else last) + 1)
    pk = onset + int(np.argmax(new[alive]))
    out.update({"onset_s": round(float(t[onset]), 3), "onset_after_gap": gap_before,
                "peak_px": int(new[pk]), "peak_s": round(float(t[pk]), 3),
                "last_on_s": round(float(t[last]), 3),
                "life_s": round(float(t[last] - t[onset]), 3),
                "censored": end is None, "censor_reason": None if end is not None else reason,
                "largest": {"area": int(big[pk, 0]), "cx": big[pk, 1], "cy": big[pk, 2],
                            "w": int(big[pk, 3]), "h": int(big[pk, 4]),
                            "touches_self": bool(big[pk, 5])}})
    return out


def residual_class(summary: dict) -> tuple[str, str | None]:
    """A crude class from the residual, fixed before any result was seen.

    Dark first (a disc or, elongated, wall segments), then teal (a line when
    elongated, a ring when hollow, a region when large, else an icon), then
    white, then any other hue. A component that ends inside 0.5 s is a flash.
    """
    comp = {c: s for c, s in summary.items() if c in CLASSED and s.get("onset_s") is not None
            and s["onset_s"] <= 8.0}
    if not comp:
        return "nothing", None
    pick = None
    if "dark" in comp and comp["dark"]["peak_px"] >= 150:
        pick = "dark"
    elif "teal" in comp or "teal_all" in comp:
        pick = max((c for c in ("teal", "teal_all") if c in comp),
                   key=lambda c: comp[c]["peak_px"])
    elif "white" in comp:
        pick = "white"
    else:
        pick = max(comp, key=lambda c: comp[c]["peak_px"])
    s = comp[pick]
    if not s["censored"] and s["life_s"] < 0.5:
        return "brief_flash", pick
    g = s["largest"]
    w, h, a = max(g["w"], 1), max(g["h"], 1), g["area"]
    aspect, fill = max(w, h) / min(w, h), a / (w * h)
    if pick == "dark":
        return ("wall_segments" if aspect >= 3 else "dark_disc"), pick
    if pick.startswith("teal"):
        if aspect >= 3.5:
            return "teal_line", pick
        if fill < 0.35 and min(w, h) >= 24:
            return "teal_ring", pick
        return ("pale_region" if a >= 1500 else "compact_icon"), pick
    if pick == "white":
        return ("compact_icon" if a < 600 else "pale_region"), pick
    return ("compact_icon" if a < 600 else "other"), pick


def cast_key(c: dict) -> str:
    return f"{c['sid']}:{int(round(c['t_ms']))}:{c['slot']}"


def cast_time_ms(c: dict) -> float:
    return c["t_refined_ms"] if c.get("t_refined_ms") is not None else c["t_ms"]


def load_casts() -> list[dict]:
    """The census casts: every drop not judged a wash over a full bar."""
    rows = json.loads((OUT / "casts.json").read_text(encoding="utf-8"))["casts"]
    return [c for c in rows if c["census"]]


def next_cast_ms(c: dict, casts: list[dict]) -> float | None:
    """The demo's next drop at least 0.3 s after this one (any slot)."""
    t0 = cast_time_ms(c)
    later = [cast_time_ms(o) for o in casts if o["sid"] == c["sid"] and cast_time_ms(o) > t0 + 300]
    return min(later) if later else None


def residual_one(c: dict, casts: list[dict], cache, geo: Geo) -> dict:
    """Feature series and summary for one cast, streamed from the cache."""
    t0 = cast_time_ms(c)
    tt = np.unique(cache.t_ms)
    t_last = float(tt.max())
    x0, y0, x1, y1 = cache.rect_of("minimap")
    win = tt[(tt >= t0 + WINDOW_S[0] * 1000) & (tt <= t0 + WINDOW_S[1] * 1000)]
    base_t = float(win[np.abs(win - (t0 + BASE_S * 1000)).argmin()])
    base = next(cache.samples([base_t], rois=["minimap"])).frame[y0:y1, x0:x1]
    ok, bm, _ = frame_masks(base, geo)
    if not ok:
        return {"refused": "widget_not_drawn_at_baseline", "base_t_ms": base_t}
    grow = {k: geo.cv2.dilate(v.astype(np.uint8), geo.k3).astype(bool) for k, v in bm.items()}
    nxt = next_cast_ms(c, casts)
    ends = [(t0 + WINDOW_S[1] * 1000, "window_end"), (t_last, "end_of_file")]
    if nxt is not None:
        ends.append((nxt, "next_cast"))
    t_end_ms, end_reason = min(ends)
    mont_t = [float(win[np.abs(win - (t0 + s * 1000)).argmin()]) if len(win) else None
              for s in MONTAGE_S]
    n, nc = len(win), len(COMPONENTS)
    raw = np.zeros((n, nc), np.int32)
    new = np.zeros((n, nc), np.int32)
    big = np.zeros((n, nc, 6), np.float32)
    drawn = np.zeros(n, bool)
    selfxy = np.full((n, 3), np.nan, np.float32)
    H, W = y1 - y0, x1 - x0
    over = {g: np.zeros((len(MONTAGE_S), H, W), bool) for g in OVERLAY}
    for i, smp in enumerate(cache.samples([float(x) for x in win], rois=["minimap"])):
        crop = smp.frame[y0:y1, x0:x1]
        ok, m, me = frame_masks(crop, geo)
        drawn[i] = ok
        if not ok:
            continue
        if me is not None:
            selfxy[i] = (me["cx"], me["cy"], me["r"])
        nm = {}
        for j, k in enumerate(COMPONENTS):
            nm[k] = m[k] & ~grow[k]
            raw[i, j] = int(m[k].sum())
            new[i, j] = int(nm[k].sum())
            if new[i, j] > 0:
                big[i, j] = largest(nm[k], geo, me)
        for p, tm in enumerate(mont_t):
            if tm is not None and float(smp.t_ms) == tm:
                for g, ks in OVERLAY.items():
                    over[g][p] = np.logical_or.reduce([nm[k] for k in ks])
    t_rel = (win - t0) / 1000.0
    t_end = (t_end_ms - t0) / 1000.0
    summ = {k: component_summary(t_rel, drawn, new[:, j].astype(float), big[:, j],
                                 t_end, end_reason) for j, k in enumerate(COMPONENTS)}
    cls, pick = residual_class(summ)
    hidden = (~drawn) & (t_rel >= ONSET_FROM_S) & (t_rel <= t_end)
    step = float(np.median(np.diff(t_rel))) if n > 1 else 0.0
    feat = OUT / "features" / f"{c['sid']}_{int(round(c['t_ms']))}_{c['slot']}.npz"
    feat.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(feat, t_rel=t_rel, t_ms=win, drawn=drawn, raw=raw, new=new, largest=big,
                        self=selfxy, components=np.array(COMPONENTS),
                        montage_t_ms=np.array([np.nan if x is None else x for x in mont_t]),
                        **{f"overlay_{g}": np.packbits(v, axis=None) for g, v in over.items()},
                        overlay_shape=np.array([len(MONTAGE_S), H, W]))
    return {"key": cast_key(c), "sid": c["sid"], "slot": c["slot"], "t_ms": c["t_ms"],
            "t_cast_ms": t0, "base_t_ms": base_t, "frames": n,
            "drawn_frames": int(drawn.sum()), "hidden_s": round(float(hidden.sum()) * step, 2),
            "hidden_at_cast": bool(((~drawn) & (np.abs(t_rel) <= 0.5)).any()),
            "t_end_s": round(t_end, 3), "end_reason": end_reason,
            "residual_class": cls, "residual_component": pick,
            "components": summ, "features": str(feat)}


def cmd_residual(args) -> int:
    """Per-cast residual series against the baked geometry, one demo at a time."""
    casts = load_casts()
    want = set(args.key or [])
    out_p = OUT / "residual.json"
    done = (json.loads(out_p.read_text(encoding="utf-8")) if out_p.is_file() and not args.fresh
            else {})
    by_sid: dict[str, list[dict]] = {}
    for c in casts:
        if want and cast_key(c) not in want:
            continue
        by_sid.setdefault(c["sid"], []).append(c)
    for sid, cs in by_sid.items():
        cache, why = open_cache(sid)
        if cache is None:
            print(f"{sid}: no cache ({why})")
            continue
        geo = Geo(sid)
        for c in cs:
            t = time.perf_counter()
            r = residual_one(c, casts, cache, geo)
            done[cast_key(c)] = r
            if args.show:
                print(json.dumps(r, indent=1, default=float))
            print(f"{cast_key(c)}  {time.perf_counter() - t:5.1f}s  frames {r.get('frames')}",
                  flush=True)
        out_p.write_text(json.dumps(done, indent=1, default=float), encoding="utf-8")
    if args.record:
        record_residual(done, casts)
    return 0


def record_residual(done: dict, casts: list[dict]) -> dict:
    """Counts over the stored residual rows, recorded as `residual@demos`."""
    keys = {cast_key(c) for c in casts}
    rows = [r for k, r in done.items() if k in keys]
    ok = [r for r in rows if "residual_class" in r]
    vals = {"casts": len(keys), "rows": len(rows), "refused": len(rows) - len(ok),
            "hidden_at_cast": sum(r["hidden_at_cast"] for r in ok),
            "end_next_cast": sum(r["end_reason"] == "next_cast" for r in ok),
            "end_of_file": sum(r["end_reason"] == "end_of_file" for r in ok)}
    for cls in CLASSES:
        vals[f"class_{cls}"] = sum(r["residual_class"] == cls for r in ok)
    for comp in ("dark", "teal", "teal_all", "white"):
        vals[f"onset_{comp}"] = sum(r["components"][comp].get("onset_s") is not None for r in ok)
    vals["onset_any_hue"] = sum(any(r["components"][f"hue{d:03d}"].get("onset_s") is not None
                                    for d in HUE_BINS) for r in ok)
    print(json.dumps(vals))
    metrics.record(TOOL, part="residual", session="demos", values=vals,
                   deps={"census": VERSION, "geometry": "baked (map, profile)",
                         "lighting": "reticle.lighting", "teal": "reticle.ability_shapes.teal"},
                   note="per-cast minimap residual over [-2, +12] s against the -1 s frame, "
                        "censored at the next drop, end of file or widget not drawn; "
                        "white and hue on the eroded baked floor")
    return vals


# ---------------------------------------------------------------- montage

MONTAGE = OUT / "montage"
KEY_FILE = OUT / "key.json"
#: Overlay colours (BGR) for the keyed montage, by mask group.
OVERLAY_BGR = {"dark": (255, 0, 255), "teal": (255, 255, 0), "white": (0, 255, 255),
               "hue": (0, 140, 255)}
LEGEND_PX = 40


def numbering(casts: list[dict]) -> dict[str, int]:
    """Cast number per key: a salted hash order, so a number says nothing of a demo."""
    import hashlib
    keys = sorted({cast_key(c) for c in casts},
                  key=lambda k: hashlib.sha1(f"census:{k}".encode()).hexdigest())
    return {k: i + 1 for i, k in enumerate(keys)}


def _label(img, text, org, scale=0.6, color=(255, 255, 255)):
    cv2 = __import__("cv2")
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)


def montage_one(c: dict, casts: list[dict], cache, geo: Geo, num: int,
                res: dict | None) -> tuple[np.ndarray, np.ndarray]:
    """(blind, keyed) images: seven minimap frames and the tray round the cast."""
    import cv2
    from reticle import minimap
    t0 = cast_time_ms(c)
    tt = np.unique(cache.t_ms)
    x0, y0, x1, y1 = cache.rect_of("minimap")
    tx0, ty0, tx1, ty1 = cache.rect_of("hud_abilities")
    H, W = y1 - y0, x1 - x0
    want = []
    for s in MONTAGE_S:
        t = t0 + s * 1000
        j = int(np.abs(tt - t).argmin())
        want.append(float(tt[j]) if abs(tt[j] - t) <= 150 else None)
    tray_s = (-1.0, 0.0, 0.5)
    tray_t = [float(tt[int(np.abs(tt - (t0 + s * 1000)).argmin())]) for s in tray_s]
    need = sorted({t for t in want + tray_t if t is not None})
    got = {float(s.t_ms): s.frame for s in cache.samples(need)}
    nxt = next_cast_ms(c, casts)
    over = None
    if res and res.get("features") and Path(res["features"]).is_file():
        with np.load(res["features"]) as z:
            shp = tuple(int(v) for v in z["overlay_shape"])
            over = {g: np.unpackbits(z[f"overlay_{g}"])[:np.prod(shp)].reshape(shp).astype(bool)
                    for g in OVERLAY}
    tiles_b, tiles_k = [], []
    for p, (s, t) in enumerate(zip(MONTAGE_S, want)):
        if t is None or t not in got:
            im = np.full((H, W, 3), 60, np.uint8)
            _label(im, "no frame", (W // 2 - 50, H // 2))
        else:
            im = got[t][y0:y1, x0:x1].copy()
        note = f"{s:+.1f} s"
        if nxt is not None and t is not None and t >= nxt:
            note += "  after next drop"
        if t is not None and t in got and not minimap.widget_drawn(im, geo.sgray, geo.floor):
            note += "  widget not drawn"
        kim = im.copy()
        if over is not None:
            for g, col in OVERLAY_BGR.items():
                cs, _ = cv2.findContours(over[g][p].astype(np.uint8), cv2.RETR_EXTERNAL,
                                         cv2.CHAIN_APPROX_NONE)
                cv2.drawContours(kim, cs, -1, col, 1)
        for img in (im, kim):
            _label(img, note, (6, 20))
        tiles_b.append(im)
        tiles_k.append(kim)
    tray = np.zeros((H, W, 3), np.uint8)
    y, slot_h = 4, (H - 4) // len(tray_s)
    for s, t in zip(tray_s, tray_t):
        crop = got[t][ty0:ty1, tx0:tx1]
        ch, cw = crop.shape[:2]
        f = min(1.0, W / cw, (slot_h - 26) / ch)
        if f < 1.0:
            crop = cv2.resize(crop, (int(cw * f), int(ch * f)), interpolation=cv2.INTER_AREA)
            ch, cw = crop.shape[:2]
        _label(tray, f"tray {s:+.1f} s", (6, y + 16))
        tray[y + 22:y + 22 + ch, :cw] = crop
        y += slot_h
    tiles_b.append(tray)
    tiles_k.append(tray.copy())

    def grid(tiles):
        return np.vstack([np.hstack(tiles[:4]), np.hstack(tiles[4:])])

    b, k = grid(tiles_b), grid(tiles_k)
    bar_b = np.zeros((LEGEND_PX, b.shape[1], 3), np.uint8)
    bar_k = bar_b.copy()
    _label(bar_b, f"cast {num:03d}", (8, 27), 0.8)
    txt = (f"cast {num:03d} | {c['agent']} {c['slot']} {c['ability']} | {c['sid']} "
           f"{c['t_ms'] / 1000:.2f}s (cast {t0 / 1000:.2f}s) | drop {c['from']:.2f}->{c['to']:.2f}"
           f"{' suspect' if c['suspect'] else ''}")
    if res and "residual_class" in res:
        comp = res["components"].get(res["residual_component"] or "", {})
        txt += (f" | residual {res['residual_class']}"
                + (f" ({res['residual_component']} on {comp.get('onset_s')}s, "
                   f"life {comp.get('life_s')}s{' cens' if comp.get('censored') else ''})"
                   if comp.get("onset_s") is not None else ""))
    _label(bar_k, txt, (8, 17), 0.5)
    _label(bar_k, "overlay: dark magenta, teal cyan, white yellow, other hue orange",
           (8, 35), 0.45)
    return np.vstack([bar_b, b]), np.vstack([bar_k, k])


def cmd_montage(args) -> int:
    """Blind and keyed montages per cast; the key goes to its own file."""
    import cv2
    casts = load_casts()
    nums = numbering(casts)
    res_p = OUT / "residual.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.is_file() else {}
    MONTAGE.mkdir(parents=True, exist_ok=True)
    KEY_FILE.write_text(json.dumps({"version": VERSION, "key": {f"{n:03d}": k for k, n in
                                                                sorted(nums.items(), key=lambda kv: kv[1])}},
                                   indent=1), encoding="utf-8")
    by_sid: dict[str, list[dict]] = {}
    for c in casts:
        by_sid.setdefault(c["sid"], []).append(c)
    n = 0
    for sid, cs in by_sid.items():
        cache, why = open_cache(sid)
        if cache is None:
            continue
        geo = Geo(sid)
        for c in cs:
            num = nums[cast_key(c)]
            b, k = montage_one(c, casts, cache, geo, num, res.get(cast_key(c)))
            cv2.imwrite(str(MONTAGE / f"blind_{num:03d}.png"), b)
            cv2.imwrite(str(MONTAGE / f"keyed_{num:03d}.png"), k)
            n += 1
    print(f"{n} casts -> {MONTAGE} (key in {KEY_FILE.name}; not printed)")
    return 0


# ---------------------------------------------------------------- blind read

BLIND_READ = OUT / "blind_read.jsonl"
#: Written by `table`, the first command that opens the key: `read --add`
#: refuses afterwards, so every blind row predates the key.
UNBLINDED = OUT / "unblinded.json"
TABLE = OUT / "table.json"
LEDGER = STORE / "notes" / "predictions.jsonl"
FRAME_NAMES = ("-1", "0", "+0.5", "+1", "+2", "+4", "+8")
PLAYER_TRAY_LABELS = STORE / "labels" / "tray_object"


def blind_nums() -> list[int]:
    return sorted(int(p.stem.split("_")[1]) for p in MONTAGE.glob("blind_*.png"))


def blind_rows() -> dict[int, dict]:
    """The blind read, last row per cast number winning."""
    out: dict[int, dict] = {}
    if BLIND_READ.is_file():
        for line in BLIND_READ.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[int(r["num"])] = r
    return out


def check_read_row(r: dict, nums: set[int]) -> str | None:
    """Why a blind row is malformed, or None."""
    if int(r.get("num", -1)) not in nums:
        return "no such montage"
    if r.get("class") not in CLASSES:
        return f"class not in {CLASSES}"
    drawn = r["class"] not in ("nothing", "unsure")
    if drawn and r.get("onset_frame") not in FRAME_NAMES:
        return f"onset_frame not in {FRAME_NAMES}"
    if drawn and r.get("gone_by_frame") not in FRAME_NAMES + ("persists",):
        return "gone_by_frame must name a frame or persists"
    if not drawn and (r.get("onset_frame") or r.get("gone_by_frame")):
        return "nothing and unsure carry no onset or end"
    if not isinstance(r.get("desc"), str) or not r["desc"].strip():
        return "desc is required"
    return None


def cmd_read(args) -> int:
    """List the unread blind montages, or append validated blind rows."""
    nums = blind_nums()
    have = blind_rows()
    if args.add:
        if UNBLINDED.is_file():
            raise SystemExit(f"the key was opened ({UNBLINDED.name}); a row now is not blind")
        rows = [json.loads(x) for x in Path(args.add).read_text(encoding="utf-8").splitlines()
                if x.strip()]
        bad = [(r.get("num"), why) for r in rows
               if (why := check_read_row(r, set(nums))) is not None]
        again = [r["num"] for r in rows if int(r["num"]) in have and not args.redo]
        if bad or again:
            raise SystemExit(f"refused: malformed {bad}; already read {again}")
        at = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(BLIND_READ, "a", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps({"num": int(r["num"]), "class": r["class"],
                                    "onset_frame": r.get("onset_frame"),
                                    "gone_by_frame": r.get("gone_by_frame"),
                                    "desc": r["desc"].strip(),
                                    "self_ring": bool(r.get("self_ring", False)),
                                    "seen_before": bool(r.get("seen_before", False)),
                                    "by": "claude-blind", "at": at, "version": VERSION}) + "\n")
        have = blind_rows()
        print(f"added {len(rows)}; read {len(have)} of {len(nums)}")
        return 0
    todo = [n for n in nums if n not in have]
    print(f"read {len(have)} of {len(nums)}; next: {' '.join(f'{n:03d}' for n in todo[:args.n])}")
    return 0


def ledger_prior() -> dict:
    """The census's own prediction row: the per-ability prior and its lists."""
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        if r.get("task") == "demo-cast-census" and r.get("kind") == "prediction":
            return r
    raise SystemExit("no demo-cast-census prediction in the ledger")


def player_tray_objects() -> dict[str, Counter]:
    """The player's tray-object answers per 'Agent:Ability', from match sessions.

    Another population (matches, not demos), and another question: whether the
    cast put an object on the minimap. It is read only after the blind read.
    """
    out: dict[str, Counter] = {}
    for p in PLAYER_TRAY_LABELS.glob("*.jsonl"):
        last = {}
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
        for r in last.values():
            out.setdefault(f"{r['agent']}:{r['ability']}", Counter())[r["class"]] += 1
    return out


def ability_of(c: dict) -> str:
    return f"{c['agent']}:{c['ability']}"


def cmd_table(args) -> int:
    """Open the key, join the blind read, the residual and the prior per ability."""
    nums = blind_nums()
    have = blind_rows()
    missing = [n for n in nums if n not in have]
    if missing and not args.partial:
        raise SystemExit(f"{len(missing)} montages unread; the key stays shut")
    if not UNBLINDED.is_file():
        UNBLINDED.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                         "read": len(have), "montages": len(nums)}),
                             encoding="utf-8")
    key = json.loads(KEY_FILE.read_text(encoding="utf-8"))["key"]
    casts = {cast_key(c): c for c in load_casts()}
    res_p = OUT / "residual.json"
    res = json.loads(res_p.read_text(encoding="utf-8")) if res_p.is_file() else {}
    led = ledger_prior()
    prior, selfs = led["per_ability"], set(led["self_abilities"])
    rows = []
    for n in nums:
        k = key[f"{n:03d}"]
        c, b, r = casts[k], have.get(n), res.get(k, {})
        ab = ability_of(c)
        rows.append({"num": n, "key": k, "sid": c["sid"], "agent": c["agent"],
                     "slot": c["slot"], "ability": c["ability"], "ab": ab,
                     "blind": b["class"] if b else None,
                     "onset_frame": b and b.get("onset_frame"),
                     "gone_by_frame": b and b.get("gone_by_frame"),
                     "desc": b and b["desc"], "self_ring": bool(b and b.get("self_ring")),
                     "seen_before": bool(b and b.get("seen_before")),
                     "residual": r.get("residual_class"),
                     "residual_refused": r.get("refused"),
                     "prior": prior.get(ab, {}).get("class"),
                     "self_ability": ab in selfs, "suspect": c["suspect"]})
    player = player_tray_objects()
    table: dict[str, dict] = {}
    for x in rows:
        t = table.setdefault(x["ab"], {"agent": x["agent"], "slot": x["slot"],
                                       "ability": x["ability"], "n": 0, "votes": Counter(),
                                       "onset": Counter(), "gone": Counter(),
                                       "residual": Counter(), "prior": x["prior"],
                                       "agree_residual": 0, "agree_prior": 0,
                                       "self_ring": 0, "nums": []})
        t["n"] += 1
        t["nums"].append(x["num"])
        t["votes"][x["blind"]] += 1
        t["residual"][x["residual"] or f"refused:{x['residual_refused']}"] += 1
        if x["onset_frame"]:
            t["onset"][x["onset_frame"]] += 1
        if x["gone_by_frame"]:
            t["gone"][x["gone_by_frame"]] += 1
        t["agree_residual"] += x["blind"] == x["residual"]
        t["agree_prior"] += x["blind"] == x["prior"]
        t["self_ring"] += x["self_ring"]
    for ab, t in table.items():
        t["player_tray_objects"] = dict(player.get(ab, {}))
        top, k = t["votes"].most_common(1)[0]
        t["majority"] = top if k * 2 > t["n"] else "split"
    read = [x for x in rows if x["blind"] is not None]
    drawn = [x for x in read if x["blind"] not in ("nothing", "unsure")]
    # C2's stated exceptions: a toggle after the throw, and pips empty at equip.
    late_ok = {"Viper:Poison Cloud", "Deadlock:Annihilation"}
    early_n = [x for x in drawn if x["ab"] not in late_ok]
    early = [x for x in early_n if x["onset_frame"] in ("-1", "0", "+0.5", "+1")]
    self_rows = [x for x in read if x["self_ability"]]
    vals = {"montages": len(nums), "read": len(read),
            "blind_nothing": sum(x["blind"] == "nothing" for x in read),
            "blind_unsure": sum(x["blind"] == "unsure" for x in read),
            "blind_drawn": len(drawn), "drawn_by_1s": len(early), "drawn_timed": len(early_n),
            "self_casts": len(self_rows),
            "self_blind_nothing": sum(x["blind"] == "nothing" for x in self_rows),
            "self_residual_nothing": sum(x["residual"] == "nothing" for x in self_rows),
            "agree_residual": sum(x["blind"] == x["residual"] for x in read),
            "residual_rows": sum(x["residual"] is not None for x in read),
            "agree_prior": sum(x["blind"] == x["prior"] for x in read),
            "prior_rows": sum(x["prior"] is not None for x in read),
            "self_ring": sum(x["self_ring"] for x in read),
            "abilities": len(table)}
    for cls in CLASSES:
        vals[f"blind_{cls}"] = sum(x["blind"] == cls for x in read)
    out = {"version": VERSION, "values": vals, "rows": rows,
           "abilities": {ab: {**t, "votes": dict(t["votes"]), "onset": dict(t["onset"]),
                              "gone": dict(t["gone"]), "residual": dict(t["residual"])}
                         for ab, t in sorted(table.items())},
           "disagree_residual": [x for x in read if x["blind"] != x["residual"]],
           "disagree_prior": [x for x in read if x["blind"] != x["prior"]]}
    TABLE.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps(vals))
    print("| ability | slot | n | blind votes | onset | gone by | residual | prior | player (matches) |")
    print("|---|---|---|---|---|---|---|---|---|")
    fmt = lambda d: ", ".join(f"{k} {v}" for k, v in sorted(d.items(), key=lambda kv: -kv[1]))
    for ab, t in sorted(table.items()):
        print(f"| {ab} | {t['slot']} | {t['n']} | {fmt(t['votes'])} | {fmt(t['onset'])} | "
              f"{fmt(t['gone'])} | {fmt(t['residual'])} | {t['prior']} | "
              f"{fmt(t['player_tray_objects'])} |")
    if args.record:
        metrics.record(TOOL, part="table", session="demos", values=vals,
                       deps={"census": VERSION, "blind_read": str(BLIND_READ.name),
                             "residual": "residual.json", "prior": "ledger demo-cast-census"},
                       note="blind montage classes joined to the key after every blind row "
                            "was written; agreement with the residual class and the prior")
    return 0


# ---------------------------------------------------------------- label tool

LABEL_KIND = "demo_cast_class"
#: Digit keys, in CLASSES order; unsure is U, as in every labeller here.
LABEL_KEYS = {str(i): cls for i, cls in enumerate(CLASSES[:-1])}


def label_rows() -> dict[str, dict]:
    out = {}
    for p in (STORE / "labels" / LABEL_KIND).glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def cmd_label(args) -> int:
    """The player's check of each cast's class on the KEYED montage.

    Digits pick a class, U unsure, A back one cast, Q or ESC quit. Rows append
    to `<store>/labels/demo_cast_class/<sid>.jsonl`, keyed sid:t_ms:slot; the
    last row for a key wins, so A then a new answer corrects one. Answered
    casts are skipped, so a pass resumes. `--dry-run` prints each row instead
    of writing it, and `--keys` plays a key sequence and quits.
    """
    import base64
    import tkinter as tk

    import cv2
    nums = blind_nums()
    key = json.loads(KEY_FILE.read_text(encoding="utf-8"))["key"]
    casts = {cast_key(c): c for c in load_casts()}
    done = label_rows()
    order = [n for n in nums if key[f"{n:03d}"] not in done]
    print(f"{len(nums)} casts, {len(nums) - len(order)} answered", flush=True)
    if not order:
        return 0
    root = tk.Tk()
    root.title("What did this cast draw on the minimap?")
    scale = min(1.0, (root.winfo_screenheight() - 160) / 1010)
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None, "wrote": 0}
    help_ = "   ".join(f"{d} {c}" for d, c in LABEL_KEYS.items()) + "   U unsure   A back   Q quit"

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        n = order[state["k"]]
        c = casts[key[f"{n:03d}"]]
        im = cv2.imread(str(MONTAGE / f"keyed_{n:03d}.png"))
        if scale < 1.0:
            im = cv2.resize(im, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", im)[1].tobytes()))
        state["img"] = img                         # keep a reference, or Tk blanks it
        canvas.configure(width=im.shape[1], height=im.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, image=img, anchor="nw")
        info.configure(text=(f"{state['k'] + 1}/{len(order)}   cast {n:03d}   {c['agent']}  "
                             f"{c['slot']}  {c['ability']}   {c['sid']}  "
                             f"{cast_time_ms(c) / 1000:.2f} s\n{help_}"))

    def write(cls):
        n = order[state["k"]]
        k = key[f"{n:03d}"]
        c = casts[k]
        row = {"key": k, "session_id": c["sid"], "t_ms": c["t_ms"], "t_cast_ms": cast_time_ms(c),
               "slot": c["slot"], "agent": c["agent"], "ability": c["ability"], "num": n,
               "class": cls, "uncertain": cls == "unsure", "by": "player",
               "compared_against_derived": True, "shown": f"montage/keyed_{n:03d}.png",
               "version": VERSION, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        if args.dry_run:
            print("dry run, not written:", json.dumps(row), flush=True)
        else:
            d = STORE / "labels" / LABEL_KIND
            d.mkdir(parents=True, exist_ok=True)
            with open(d / f"{c['sid']}.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps(row) + "\n")
        state["wrote"] += 1
        state["k"] += 1
        show()

    def back():
        state["k"] = max(0, state["k"] - 1)
        show()

    handlers = {d: (lambda cls=cls: write(cls)) for d, cls in LABEL_KEYS.items()}
    handlers.update({"u": lambda: write("unsure"), "a": back, "q": root.destroy,
                     "Escape": root.destroy})
    for k, fn in handlers.items():
        root.bind(f"<{k}>" if k == "Escape" else k, lambda e, fn=fn: fn())
    show()
    if args.keys:
        seq = args.keys.split(",")
        for i, k in enumerate(seq):
            root.after(400 * (i + 1), handlers[k.lower() if k != "Escape" else k])
    root.mainloop()
    print(f"{state['wrote']} answers {'shown' if args.dry_run else 'written'}")
    return 0


def main(argv=None) -> int:
    idle()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("cache", help="write each demo's minimap crop cache")
    c.add_argument("--session", nargs="*")
    c.add_argument("--decode", default="nvdec", choices=("nvdec", "auto", "cpu"))
    c.add_argument("--force", action="store_true")
    c.add_argument("--check", action="store_true", help="compare three crops to decoded frames")
    c.add_argument("--record-existing", action="store_true",
                   help="record the metric for a cache already written")
    c = sub.add_parser("casts", help="tray drops at 2 Hz from the cached tray crops")
    c.add_argument("--record", action="store_true")
    c.add_argument("--strips", action="store_true",
                   help="render the tray crops round every drop that needs an eye")
    c = sub.add_parser("residual", help="per-cast minimap residual against baked geometry")
    c.add_argument("--key", nargs="*", help="only these sid:t_ms:slot keys")
    c.add_argument("--show", action="store_true", help="print each summary (unblinds the cast)")
    c.add_argument("--fresh", action="store_true")
    c.add_argument("--record", action="store_true", help="record the counts as residual@demos")
    sub.add_parser("montage", help="blind and keyed montages per cast")
    c = sub.add_parser("read", help="list unread blind montages or append blind rows")
    c.add_argument("--add", help="a JSONL file of blind rows to validate and append")
    c.add_argument("--redo", action="store_true", help="allow a second row for a cast")
    c.add_argument("-n", type=int, default=20, help="how many unread numbers to list")
    c = sub.add_parser("table", help="open the key and tabulate per ability")
    c.add_argument("--partial", action="store_true", help="tabulate before every cast is read")
    c.add_argument("--record", action="store_true")
    c = sub.add_parser("label", help="the player's class per cast on the keyed montage")
    c.add_argument("--dry-run", action="store_true", help="print rows; write nothing")
    c.add_argument("--keys", help="comma-separated keys to play, e.g. 5,a,u,q (testing)")
    args = ap.parse_args(argv)
    return {"cache": cmd_cache, "casts": cmd_casts, "residual": cmd_residual,
            "montage": cmd_montage, "read": cmd_read, "table": cmd_table,
            "label": cmd_label}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
