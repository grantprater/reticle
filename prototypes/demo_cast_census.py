r"""What each ability cast draws on the minimap in the solo demos: a census.

    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py cache [--session S] [--check]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py casts [--record]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py residual [--key K ...]
    .\.venv\Scripts\python.exe prototypes\demo_cast_census.py montage

`cache` gives each of the 33 solo demos the production whole-capture minimap
crop cache (`reticle scan <sid> --only roi_cache --cache-roi minimap
--cache-hz 15`, NVDEC, Idle priority, one scan at a time) and checks three
samples per demo against decoded frames. The rest of this file reads only
those crops. Findings and the appearance table: `docs/DEMO_CAST_CENSUS.md`.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import time
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
    """The promoted tray reader if this checkout has it, else the prototype."""
    try:
        from reticle import tray
        return tray, "reticle.tray"
    except ImportError:
        sys.path.insert(0, str(ROOT / "prototypes"))
        import ability_hud
        return ability_hud, "prototypes.ability_hud"


def cache_grid(t_ms, t0: float, t1: float, step_s: float) -> list[float]:
    """Cached times nearest a regular grid inside [t0, t1] (`reticle tray`'s grid)."""
    try:
        from reticle.cli import _cache_grid
        return _cache_grid(t_ms, t0, t1, step_s)
    except ImportError:
        t = np.unique(np.asarray(t_ms, float))
        t = t[(t >= t0) & (t <= t1)]
        if not len(t):
            return []
        want = np.arange(t[0], t[-1] + 1, step_s * 1000.0)
        return [float(x) for x in t[np.unique(np.searchsorted(t, want).clip(0, len(t) - 1))]]


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


def cmd_casts(args) -> int:
    """Tray drops from the cached crops, compared with the stored cast caches."""
    reader, name = tray_reader()
    rows, per = [], {}
    tot = {"demos": 0, "drops": 0, "suspect": 0, "stored": 0, "matched": 0, "added": 0,
           "missing": 0, "refined": 0}
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
        per[sid] = {"agent": agent, "drops": len(mine), "stored": None if st is None else len(st),
                    "matched": len(pairs), "added": [mine[i]["t_ms"] / 1000.0 for i in added],
                    "added_slots": [mine[i]["slot"] for i in added],
                    "missing": [st[j] for j in missing] if st else [],
                    "samples": len(ts), "clean": int(clean.sum())}
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
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "casts.json").write_text(json.dumps({"version": VERSION, "source_reader": name,
                                                "step_s": TRAY_STEP_S, "match_s": MATCH_S,
                                                "per_demo": per, "casts": rows}, indent=1),
                                    encoding="utf-8")
    print(tot)
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
#: Colour rules. Teal is `ability_shapes.teal`'s (hue 75-105, sat >= 70,
#: weighted by value) cut at this weight; white is bright and achromatic;
#: the other hues are saturated pixels outside teal and the self key.
TEAL_W_MIN = 0.3
TEAL_H, TEAL_S_MIN = (75, 105), 70
WHITE_S_MAX, WHITE_V_MIN = 40, 200
HUE_S_MIN, HUE_V_MIN = 70, 90
#: The art footprint grown by this many px is the support (the art's own
#: search dilation, `ability_shapes.SUPPORT_DILATE`).
SUPPORT_DILATE = 9
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
    """`ability_shapes.teal` when this checkout has it; the same rule otherwise."""
    try:
        from reticle.ability_shapes import teal
        return teal(crop)
    except ImportError:
        import cv2
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
        return (((h >= TEAL_H[0]) & (h <= TEAL_H[1]) & (s >= TEAL_S_MIN))
                .astype(np.float32) * (v / np.float32(255.0)))


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
        yy, xx = np.mgrid[0:H, 0:W]
        self.disc = np.hypot(xx - (W - 1) / 2, yy - (H - 1) / 2) <= min(H, W) / 2
        self.k3 = np.ones((3, 3), np.uint8)
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
    in_teal = (h >= TEAL_H[0]) & (h <= TEAL_H[1])
    m = {"dark": lighting.raw_dark(crop, geo.ref) & ~off,
         "lit": lighting.raw_lit(crop, geo.ref) & ~off,
         "teal": tw & keep,
         "teal_all": tw & geo.disc & ~off,
         "white": (s < WHITE_S_MAX) & (v >= WHITE_V_MIN) & keep}
    sat = (s >= HUE_S_MIN) & (v >= HUE_V_MIN) & ~in_teal & ~minimap.self_mask(crop) & keep
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
    return json.loads((OUT / "casts.json").read_text(encoding="utf-8"))["casts"]


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
    return 0


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
    y = 10
    for s, t in zip(tray_s, tray_t):
        crop = got[t][ty0:ty1, tx0:tx1]
        ch, cw = crop.shape[:2]
        if cw > W:
            crop = cv2.resize(crop, (W, int(ch * W / cw)), interpolation=cv2.INTER_AREA)
            ch, cw = crop.shape[:2]
        _label(tray, f"tray {s:+.1f} s", (6, y + 16))
        tray[y + 22:y + 22 + ch, :cw] = crop
        y += ch + 40
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
    c = sub.add_parser("residual", help="per-cast minimap residual against baked geometry")
    c.add_argument("--key", nargs="*", help="only these sid:t_ms:slot keys")
    c.add_argument("--show", action="store_true", help="print each summary (unblinds the cast)")
    c.add_argument("--fresh", action="store_true")
    sub.add_parser("montage", help="blind and keyed montages per cast")
    args = ap.parse_args(argv)
    return {"cache": cmd_cache, "casts": cmd_casts, "residual": cmd_residual,
            "montage": cmd_montage}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
