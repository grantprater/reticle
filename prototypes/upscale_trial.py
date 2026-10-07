r"""Does the ally-icon reader score better on smoothly enlarged minimap crops?

    .\.venv\Scripts\python.exe prototypes\upscale_trial.py run SESSION --scale S [--between T0 T1] [--labels]
    .\.venv\Scripts\python.exe prototypes\upscale_trial.py score SESSION [--labels]
    .\.venv\Scripts\python.exe prototypes\upscale_trial.py explain SESSION --between T0 T1 --scale S
    .\.venv\Scripts\python.exe prototypes\upscale_trial.py sheet SESSION --at T_MS [--scale S]

The player watches captures in VLC, which shows the 1080p frame about 1.2x
larger through a smooth GPU filter, and the ~13 px minimap icons look crisp
there. Enlarging adds no information, so a reader that already interpolates
should gain nothing; only a step that resamples nearest-neighbour, shrinks
with linear interpolation or hard-thresholds a thin rim could. Task
`upscale-trial-20261001` in the store's `notes/predictions.jsonl`.

**Conditions** (`run --scale`), all from the minimap crop cache, no decode:

* ``1.0`` (A): the native crop and `minimap.ally_icon_reader` as `scan` builds it.
* ``1.2`` / ``2.0`` (B, C): the widget crop enlarged with `cv2.INTER_LANCZOS4`.
  The reader takes every geometry constant from its `scale`, the map's
  (`geometry.drawn_scale`: widget x map zoom), so the enlarged crop reads at
  that scale x S with no value table. The baked static map is enlarged the
  same way, the floor and slab masks bilinearly and cut at one half. Three
  values the reader does not derive from the scale are scaled by a hook
  (`_scaled`), here and nowhere else: `appearance.MIN_PIXELS` (a pixel count,
  x S^2), `ally_portrait.RAW` (the raw window side, x S) and `minimap.SEARCH`
  (the self channel's centroid search, x S). The self facing gate is one NCC
  at every scale since teardrop-0.5.0, and the per-size portrait table
  (`teardrop.labelled_scale`) is gone, so neither is hooked. `_reach`'s ray start and
  step stay in pixels. Every stored position maps back to native pixels by
  pixel centre, `(x + 0.5) / S - 0.5`, as `cv2.resize` aligns them.
* ``1.2rt`` (D, the resampling null): enlarged 1.2x with Lanczos, then shrunk
  back to the native size with `INTER_AREA`. The grid and every constant are
  A's; only resampling moved the pixels. |D - A| is how far resampling alone
  moves a score.
* ``1.0r7`` (control): the native crop with the ring fit's radius floor
  `minimap.R_MIN` at 7 base px instead of 8, to test whether B's gain on a
  331 px widget comes from the finer radius grid rather than the smoothing.

No reader version stamp changes and nothing is written to the store's tables;
each run writes one JSON file under `analysis/upscale-trial-20261001/`.

**Timeline.** The stored `ally_icon` stream's frames with the widget drawn
(as `reticle trial --reader ally_icon --windows occupied`), inside
`--between T0 T1` (seconds, as `reticle trial`); a session with no stored stream reads every cached frame. With
`--labels`, each player label's frame and the five cached frames before it
(so the 0.7.0 pose prior runs as in a scan): `labels/icon_facing_20260928`,
`labels/ally_facing_331_20260929` (class ally) and `labels/prior_ally/`.

**Score** (`score`). The ally channel's existing benchmark is the roster
(`round_lifetimes.ally_capacity`, as `prototypes/ally_prior_search.py`
counts it): on in-round frames (`rounds.build_rounds`) where the STORED
stream saw the widget drawn and a self fit and the latest roster read is
read, each condition's accepted non-barrier icons less the capacity is the
frame's residual. Reported per condition: mean residual, mean |residual|,
exact, under and over shares. A session with no roster (a solo demo) has no
teammate to draw, so every accepted non-barrier icon is a phantom. The
noise bound on a B - A difference is the larger of the 95% paired block
bootstrap half-width (10 s blocks, 2000 draws, seed 7) and |D - A|. On
labels: an accepted icon within 4 native px of a facing label's centre is a
hit, with its centre and facing error; on `prior_ally`, an icon within 6 px
of a `teammate` answer is a hit and of a `not_teammate` answer a false alarm.

**Explain** (`explain`). On 40 frames (seed 7) whose residual differs between
A and a condition, it names, for each icon one accepts and the other does
not, what the other did with its nearest fit.

Unwired (`"wire": "no"`): a measurement, not a reader.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "2"

import argparse  # noqa: E402
import bisect  # noqa: E402
import contextlib  # noqa: E402
import ctypes  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import ally_portrait, appearance, minimap  # noqa: E402
from reticle.decode import Sample  # noqa: E402
from reticle.minimap import AllyIconReader, ally_icon_reader  # noqa: E402
from reticle.passes import SessionContext  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.round_lifetimes import ally_capacity  # noqa: E402
from reticle.rounds import build_rounds  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.version import ALLY_ICON_VERSION  # noqa: E402

VERSION = "upscale-trial-0.1.0"
TASK = "upscale-trial-20261001"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
CONDITIONS = ("1.0", "1.2", "2.0", "1.2rt", "1.0r7")
LABEL_CONTEXT = 5          # cached frames read before each labelled frame
HIT_PX, PRIOR_HIT_PX = 4.0, 6.0
BLOCK_MS, DRAWS, SEED = 10_000.0, 2000, 7


def _idle() -> None:
    cv2.setNumThreads(2)
    try:
        k = ctypes.windll.kernel32
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)  # IDLE_PRIORITY_CLASS
    except Exception:
        pass


def _session(sid: str):
    store = Store(STORE)
    man = json.loads((store.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    profile = get_profile(man["source_profile"])
    return store, man, profile, SessionContext(store=store, manifest=man, profile=profile)


def _factor(cond: str) -> float:
    return float(cond.replace("rt", "").replace("r7", ""))


def _r_min(cond: str) -> int | None:
    """``1.0r7``: native crops with `minimap.R_MIN` 7, so the 331 px widget's
    radius floor rounds to 5 (7 x 0.712 = 4.98) where 8 rounds to 6."""
    return 7 if cond.endswith("r7") else None


def _resize_crop(crop: np.ndarray, cond: str) -> np.ndarray:
    s = _factor(cond)
    if s == 1.0:
        return crop
    h, w = crop.shape[:2]
    big = cv2.resize(crop, (round(w * s), round(h * s)), interpolation=cv2.INTER_LANCZOS4)
    if cond.endswith("rt"):
        return cv2.resize(big, (w, h), interpolation=cv2.INTER_AREA)
    return big


def _native(x: float, s: float) -> float:
    """An enlarged crop's coordinate in native px. `cv2.resize` aligns pixel
    centres, so native x = (x + 0.5) / s - 0.5, not x / s."""
    return (x + 0.5) / s - 0.5


def _resize_mask(m: np.ndarray, s: float) -> np.ndarray:
    h, w = m.shape[:2]
    up = cv2.resize(m.astype(np.uint8) * 255, (round(w * s), round(h * s)),
                    interpolation=cv2.INTER_LINEAR)
    return up >= 128


@contextlib.contextmanager
def _scaled(s: float, r_min: int | None = None):
    """The values the reader does not derive from the crop's width, scaled by
    the enlargement `s` for the duration: a pixel count by s^2, a window side
    and the centroid search (`minimap.SEARCH`) by s. `r_min` replaces
    `minimap.R_MIN` (the native radius-floor control, condition ``1.0r7``)."""
    saved = (appearance.MIN_PIXELS, ally_portrait.RAW, minimap.SEARCH, minimap.R_MIN)
    if s != 1.0:
        appearance.MIN_PIXELS = int(round(saved[0] * s * s))
        ally_portrait.RAW = 2 * int(round((saved[1] // 2) * s)) + 1
        minimap.SEARCH = int(round(saved[2] * s))
    if r_min is not None:
        minimap.R_MIN = r_min
    try:
        yield {"MIN_PIXELS": appearance.MIN_PIXELS, "RAW": ally_portrait.RAW,
               "SEARCH": minimap.SEARCH, "R_MIN": minimap.R_MIN}
    finally:
        (appearance.MIN_PIXELS, ally_portrait.RAW, minimap.SEARCH, minimap.R_MIN) = saved


def _reader(ctx, cond: str):
    """A's reader as `scan` builds it, or the same baked geometry enlarged."""
    base = ally_icon_reader(ctx)
    s = _factor(cond)
    if s == 1.0 or cond.endswith("rt"):
        return base, base.box
    x0, y0, x1, y1 = base.box
    h, w = y1 - y0, x1 - x0
    static = cv2.resize(base.static, (round(w * s), round(h * s)),
                        interpolation=cv2.INTER_LANCZOS4)
    # The map's scale, enlarged with the crop; a reader without one reads the
    # enlarged crop's widget scale, which `drawn_scale` documents.
    sc = None if base.scale is None else base.scale * s
    r = AllyIconReader(floor=_resize_mask(base.floor, s), slab=_resize_mask(base.slab, s),
                       static=static, box=(0, 0, static.shape[1], static.shape[0]),
                       hz=base.hz, scale=sc,
                       scale_source=f"{base.scale_source} x {s:g} (upscale_trial)")
    return r, base.box


# ------------------------------------------------------------------ timelines
def _labels(sid: str) -> list[dict]:
    L = STORE / "labels"
    out = []
    for name in ("icon_facing_20260928.jsonl", "ally_facing_331_20260929.jsonl"):
        p = L / name
        if not p.is_file():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("session") == sid and r.get("cls") == "ally":
                out.append({"src": name.split(".")[0], "t_ms": float(r["t_ms"]),
                            "answer": r["answer"], "x": r.get("centre_x", r["ring_x"]),
                            "y": r.get("centre_y", r["ring_y"]),
                            "facing": r.get("facing_deg")})
    p = L / "prior_ally" / f"{sid}.jsonl"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                c = r.get("centre") or [r["x"], r["y"]]
                out.append({"src": "prior_ally", "t_ms": float(r["t_ms"]), "answer": r["answer"],
                            "x": float(c[0]), "y": float(c[1]), "facing": None})
    return out


def _timeline(store, sid: str, cache: RoiCache, between, labels: bool):
    held = cache.holds()
    if labels:
        want = set()
        for lab in _labels(sid):
            i = bisect.bisect_left(held, lab["t_ms"] - 1e-3)
            if i < len(held) and abs(held[i] - lab["t_ms"]) < 1e-3:
                want.update(held[max(0, i - LABEL_CONTEXT):i + 1])
        return sorted(want), {}, "labels"
    frames = ([r for r in store.read_events_kind("ally_icon", sid, "frame")
               if r.get("kind") == "frame"] if store.has_events("ally_icon", sid) else [])
    if frames:
        want = [float(r["t_ms"]) for r in frames if r.get("widget_drawn")]
        idx = {float(r["t_ms"]): r["frame_idx"] for r in frames}
        src = "stored_ally_icon_drawn"
    else:
        want, idx, src = list(held), {}, "every_cached_frame"
    if between:
        want = [t for t in want if between[0] * 1000.0 <= t <= between[1] * 1000.0]
    return want, idx, src


# ------------------------------------------------------------------ run
def run_condition(sid: str, cond: str, between=None, labels: bool = False, limit: int | None = None) -> Path:
    from reticle.trial import _ally_rows, diff
    store, man, profile, ctx = _session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(f"{sid}: no usable minimap crop cache ({why}); not decoding")
    want, stored_idx, src = _timeline(store, sid, cache, between, labels)
    if limit:
        want = want[:limit]
    s = _factor(cond)
    r, box = _reader(ctx, cond)
    x0, y0, x1, y1 = box
    t0 = time.perf_counter()
    n = 0
    with _scaled(1.0 if cond.endswith("rt") else s, _r_min(cond)) as hooks:
        for smp in cache.samples(want, rois=("minimap",)):
            crop = _resize_crop(smp.frame[y0:y1, x0:x1], cond)
            if r.box[0] == 0 and r.box[1] == 0 and r.box[2] == crop.shape[1]:
                frame = crop
            else:
                frame = smp.frame.copy()
                frame[y0:y1, x0:x1] = crop
            idx = int(stored_idx.get(smp.t_ms, smp.frame_idx))
            r.feed(Sample(frame_idx=idx, t_ms=float(smp.t_ms), frame=frame))
            n += 1
        rows = json.loads(json.dumps(_ally_rows(r, sid)["ally_icon"], allow_nan=False))
    seconds = time.perf_counter() - t0
    back = 1.0 if cond.endswith("rt") else s
    frames = [{"t_ms": f["t_ms"], "frame_idx": f["frame_idx"], "widget_drawn": f["widget_drawn"],
               "self": None if not f.get("self") else [_native(v, back) for v in f["self"][:2]]
               + [f["self"][2] / back]}
              for f in rows if f["kind"] == "frame"]
    icons = []
    for e in rows:
        if e["kind"] != "icon":
            continue
        pose = e.get("pose") or {}
        icons.append({"t_ms": e["t_ms"], "frame_idx": e["frame_idx"], "cx": _native(e["cx"], back),
                      "cy": _native(e["cy"], back), "r": e["r"] / back, "facing": e["facing"],
                      "reason": e["reason"], "family": e.get("family"),
                      "pose_origin": pose.get("origin"), "search": pose.get("search")})
    out = {"version": VERSION, "task": TASK, "session_id": sid, "condition": cond,
           "coords": "pixel_centre",
           "factor": s, "ally_icon_version": ALLY_ICON_VERSION, "hooks": hooks,
           "timeline": src, "between": between, "labels": labels, "asked": len(want),
           "frames": n, "seconds": round(seconds, 1),
           "widget_px": [x1 - x0, round((x1 - x0) * s) if not cond.endswith("rt") else x1 - x0],
           "frames_rows": frames, "icons": icons}
    if cond == "1.0" and src == "stored_ally_icon_drawn":
        # The instrument check: A must reproduce the stored stream at its frames.
        at = {float(f["t_ms"]) for f in frames}
        d = diff(rows, store.read_events("ally_icon", sid), at)
        out["stored_diff"] = {k: d[k] for k in ("trial_rows", "stored_rows", "same",
                                                "only_trial", "only_stored")}
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "labels" if labels else (f"{int(between[0])}-{int(between[1])}" if between else "all")
    path = OUT / f"{sid}_{tag}_{cond}.json"
    path.write_text(json.dumps(out), encoding="utf-8")
    keys = ("session_id", "condition", "timeline", "asked", "frames", "seconds", "widget_px",
            "hooks", "stored_diff")
    print(json.dumps({k: out[k] for k in keys if k in out}))
    print(f"wrote {path}")
    return path


# ------------------------------------------------------------------ score
def _load(sid: str, tag: str) -> dict:
    got = {}
    for cond in CONDITIONS:
        p = OUT / f"{sid}_{tag}_{cond}.json"
        if p.is_file():
            g = got[cond] = json.loads(p.read_text(encoding="utf-8"))
            back = 1.0 if cond.endswith("rt") else g["factor"]
            if g.get("coords") != "pixel_centre" and back != 1.0:
                # Files written before the fix hold x / s: add 0.5 / s - 0.5.
                d = 0.5 / back - 0.5
                for i in g["icons"]:
                    i["cx"], i["cy"] = i["cx"] + d, i["cy"] + d
                for f in g["frames_rows"]:
                    if f["self"]:
                        f["self"] = [f["self"][0] + d, f["self"][1] + d, f["self"][2]]
                g["coords"] = "pixel_centre (corrected on load)"
    if "1.0" not in got:
        raise SystemExit(f"no condition 1.0 file for {sid} {tag} in {OUT}")
    return got


def _population(store, sid: str, at: list[float]):
    """{t: capacity} on in-round frames where the stored stream saw the widget
    drawn and a self fit and the roster is read; None when the session has no
    roster (no teammate to draw: capacity 0 on every drawn frame)."""
    man = json.loads((store.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    try:
        t = store.read_roster(sid, man["ingested_at"][:10])
    except SystemExit:
        return None
    rt, ra = t.column("t_ms").to_pylist(), t.column("alive_ally").to_pylist()
    rounds = build_rounds(store.read_hud(sid, man["ingested_at"][:10]))
    stored = {float(r["t_ms"]): r for r in store.read_events_kind("ally_icon", sid, "frame")
              if r.get("kind") == "frame"}
    pop = {}
    for x in at:
        f = stored.get(x)
        if not f or not f.get("widget_drawn") or not f.get("self"):
            continue
        if not any(r["t_start_ms"] <= x < r["t_end_ms"] for r in rounds):
            continue
        i = bisect.bisect_right(rt, x) - 1
        cap = ally_capacity(ra[i], True) if i >= 0 else None
        if cap is not None:
            pop[x] = cap
    return pop


def _metrics(res: dict[float, int]) -> dict:
    v = np.array(list(res.values()), float)
    if not len(v):
        return {"n": 0}
    return {"n": int(len(v)), "mean_residual": round(float(v.mean()), 4),
            "mae": round(float(np.abs(v).mean()), 4), "exact": round(float((v == 0).mean()), 4),
            "under": round(float((v < 0).mean()), 4), "over": round(float((v > 0).mean()), 4)}


def _boot(a: dict[float, int], b: dict[float, int], fn) -> tuple[float, float, float]:
    """B - A of fn over frames, with its 95% paired block-bootstrap interval."""
    ts = sorted(set(a) & set(b))
    blocks = defaultdict(list)
    for t in ts:
        blocks[int(t // BLOCK_MS)].append(t)
    keys = list(blocks)
    rng = np.random.default_rng(SEED)
    da = np.array([fn(np.array([a[t] for t in blocks[k]])) for k in keys])
    db = np.array([fn(np.array([b[t] for t in blocks[k]])) for k in keys])
    w = np.array([len(blocks[k]) for k in keys], float)
    point = float(((db - da) * w).sum() / w.sum())
    draws = []
    for _ in range(DRAWS):
        j = rng.integers(0, len(keys), len(keys))
        draws.append(float(((db[j] - da[j]) * w[j]).sum() / w[j].sum()))
    lo, hi = np.percentile(draws, [2.5, 97.5])
    return round(point, 4), round(float(lo), 4), round(float(hi), 4)


def score(sid: str, tag: str) -> dict:
    store = Store(STORE)
    got = _load(sid, tag)
    common = set.intersection(*[{f["t_ms"] for f in g["frames_rows"]} for g in got.values()])
    pop = _population(store, sid, sorted(common))
    if pop is None:   # no roster: every drawn frame of every condition, capacity 0
        drawn = set.intersection(*[{f["t_ms"] for f in g["frames_rows"] if f["widget_drawn"]}
                                   for g in got.values()])
        pop, basis = {t: 0 for t in drawn}, "no_roster_capacity_0"
    else:
        basis = "roster_capacity"
    res, out = {}, {"session_id": sid, "tag": tag, "basis": basis, "conditions": {}}
    for cond, g in got.items():
        n = Counter(i["t_ms"] for i in g["icons"] if i["family"] != "barrier")
        res[cond] = {t: n.get(t, 0) - c for t, c in pop.items()}
        reasons = Counter(i["reason"] or "described" for i in g["icons"]
                          if i["t_ms"] in pop)
        drawn = Counter(f["widget_drawn"] for f in g["frames_rows"])
        out["conditions"][cond] = {**_metrics(res[cond]), "frames": g["frames"],
                                   "widget_drawn": drawn.get(True, 0),
                                   "self_seen": sum(1 for f in g["frames_rows"] if f["self"]),
                                   "icon_reasons": dict(reasons), "seconds": g["seconds"],
                                   "stored_diff": g.get("stored_diff")}
    mae = lambda v: float(np.abs(v).mean())
    exact = lambda v: float((v == 0).mean())
    null = {}
    if "1.2rt" in res:
        null = {"mae": _boot(res["1.0"], res["1.2rt"], mae)[0],
                "exact": _boot(res["1.0"], res["1.2rt"], exact)[0]}
    out["vs_A"] = {}
    for cond in got:
        if cond == "1.0":
            continue
        d_mae, d_exact = _boot(res["1.0"], res[cond], mae), _boot(res["1.0"], res[cond], exact)
        bound_mae = max((d_mae[2] - d_mae[1]) / 2, abs(null.get("mae", 0.0)))
        bound_exact = max((d_exact[2] - d_exact[1]) / 2, abs(null.get("exact", 0.0)))
        out["vs_A"][cond] = {
            "d_mae": d_mae, "d_exact": d_exact, "noise_bound_mae": round(bound_mae, 4),
            "noise_bound_exact": round(bound_exact, 4),
            "improves_beyond_noise": bool(-d_mae[0] > bound_mae or d_exact[0] > bound_exact),
            "frames_differ": sum(res[cond][t] != res["1.0"][t] for t in pop),
            **_moved(got["1.0"], got[cond], pop)}
    out["null_1.2rt"] = null
    return out


def _moved(a: dict, b: dict, pop) -> dict:
    """How far B's accepted icons sit from A's, in native px, on the population."""
    by_t = defaultdict(list)
    for i in a["icons"]:
        if i["t_ms"] in pop and i["family"] != "barrier":
            by_t[i["t_ms"]].append(i)
    d, df = [], []
    for i in b["icons"]:
        if i["t_ms"] not in pop or i["family"] == "barrier" or not by_t[i["t_ms"]]:
            continue
        j = min(by_t[i["t_ms"]], key=lambda k: math.hypot(k["cx"] - i["cx"], k["cy"] - i["cy"]))
        dist = math.hypot(j["cx"] - i["cx"], j["cy"] - i["cy"])
        if dist <= HIT_PX:
            d.append(dist)
            if i["facing"] is not None and j["facing"] is not None:
                df.append(abs((i["facing"] - j["facing"] + 180) % 360 - 180))
    q = lambda v, p: round(float(np.percentile(v, p)), 3) if v else None
    return {"matched_icons": len(d), "centre_shift_px_p50": q(d, 50), "centre_shift_px_p90": q(d, 90),
            "facing_shift_deg_p50": q(df, 50), "facing_shift_deg_p90": q(df, 90)}


def score_labels(sid: str) -> dict:
    got = _load(sid, "labels")
    labs = _labels(sid)
    out = {"session_id": sid, "labels": Counter(f"{l['src']}:{l['answer']}" for l in labs),
           "conditions": {}}
    for cond, g in got.items():
        by_t = defaultdict(list)
        for i in g["icons"]:
            if i["family"] != "barrier":
                by_t[i["t_ms"]].append(i)
        held = {f["t_ms"] for f in g["frames_rows"]}
        hits = miss = fa = tm_hit = tm_n = nt_n = 0
        cerr, ferr = [], []
        for lab in labs:
            t = next((x for x in held if abs(x - lab["t_ms"]) < 1e-3), None)
            if t is None:
                continue
            near = [(math.hypot(i["cx"] - lab["x"], i["cy"] - lab["y"]), i) for i in by_t[t]]
            best = min(near, key=lambda z: z[0]) if near else (math.inf, None)
            if lab["src"] == "prior_ally":
                if lab["answer"] == "teammate":
                    tm_n += 1
                    tm_hit += best[0] <= PRIOR_HIT_PX
                elif lab["answer"] == "not_teammate":
                    nt_n += 1
                    fa += best[0] <= PRIOR_HIT_PX
                continue
            if lab["answer"] != "facing":
                continue
            if best[0] <= HIT_PX:
                hits += 1
                cerr.append(best[0])
                if best[1]["facing"] is not None and lab["facing"] is not None:
                    ferr.append(abs((best[1]["facing"] - lab["facing"] + 180) % 360 - 180))
            else:
                miss += 1
        q = lambda v, p: round(float(np.percentile(v, p)), 3) if v else None
        out["conditions"][cond] = {
            "facing_labels_hit": hits, "facing_labels_missed": miss,
            "centre_err_px_p50": q(cerr, 50), "centre_err_px_p90": q(cerr, 90),
            "facing_err_deg_p50": q(ferr, 50), "facing_err_deg_p90": q(ferr, 90),
            "facing_flips_gt90": sum(e > 90 for e in ferr),
            "prior_teammate_hit": f"{tm_hit}/{tm_n}", "prior_not_teammate_false_alarm": f"{fa}/{nt_n}"}
    return out


def _candidates(sid: str, cond: str, want: list[float], stored_idx: dict) -> list[dict]:
    """Every fitted candidate of `cond` at `want`, with the stored decision
    rule's verdict, in native px."""
    from reticle.adjudication.minimap_candidates import ally_decisions
    store, man, profile, ctx = _session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    s = _factor(cond)
    back = 1.0 if cond.endswith("rt") else s
    r, box = _reader(ctx, cond)
    x0, y0, x1, y1 = box
    with _scaled(back, _r_min(cond)):
        for smp in cache.samples(want, rois=("minimap",)):
            crop = _resize_crop(smp.frame[y0:y1, x0:x1], cond)
            frame = crop if r.box[:2] == (0, 0) and r.box[2] == crop.shape[1] else smp.frame
            if frame is smp.frame:
                frame = smp.frame.copy()
                frame[y0:y1, x0:x1] = crop
            r.feed(Sample(frame_idx=int(stored_idx.get(smp.t_ms, smp.frame_idx)),
                          t_ms=float(smp.t_ms), frame=frame))
    rows = json.loads(json.dumps(r.candidate_rows(sid), allow_nan=False))
    dec = {d["candidate_key"]: d for d in ally_decisions(rows)}
    return [{"t_ms": c["t_ms"], "channel": c["channel"], "cx": _native(c["cx"], back),
             "cy": _native(c["cy"], back), "r": c["r"] / back, "cov": c["cov"], "inner": c["inner"],
             "area": c["area"] / back ** 2, "facing": c["facing"],
             "reason": dec[c["candidate_key"]]["reason"], "family": dec[c["candidate_key"]]["family"]}
            for c in rows]


def _self_summary(rows: list[dict], pick: list[float]) -> dict:
    """Per frame, the self channel's best-covered fit: how many frames hold
    none, and the median cov, inner and native radius of the best."""
    best = {}
    for c in rows:
        if c["t_ms"] not in best or c["cov"] > best[c["t_ms"]]["cov"]:
            best[c["t_ms"]] = c
    b = list(best.values())
    med = lambda k: round(float(np.median([c[k] for c in b])), 3) if b else None
    return {"frames": len(pick), "no_fit": len(pick) - len(b), "cov_p50": med("cov"),
            "inner_p50": med("inner"), "r_p50": med("r"),
            "reasons": dict(Counter(c["reason"] for c in b))}


def explain_diff(sid: str, between, n: int = 40, cond: str = "1.2") -> dict:
    """On up to `n` population frames whose residual differs between A and
    `cond` (fixed seed), each with its `LABEL_CONTEXT` cached frames before it,
    say for every icon one condition accepts and the other does not what the
    other did with the nearest fit: the decision reason, or no fit at all."""
    store = Store(STORE)
    tag = f"{int(between[0])}-{int(between[1])}"
    got = _load(sid, tag)
    a, b = got["1.0"], got[cond]
    pop = _population(store, sid, sorted({f["t_ms"] for f in a["frames_rows"]}))
    cnt = lambda g: Counter(i["t_ms"] for i in g["icons"] if i["family"] != "barrier")
    na, nb = cnt(a), cnt(b)
    diff_t = sorted(t for t in pop if na.get(t, 0) != nb.get(t, 0))
    rng = np.random.default_rng(SEED)
    pick = sorted(rng.choice(diff_t, size=min(n, len(diff_t)), replace=False).tolist())
    _, man, profile, _ = _session(sid)
    cache, _ = RoiCache.load(store.root, man, profile, "minimap")
    held = cache.holds()
    want = set()
    for t in pick:
        i = bisect.bisect_left(held, t - 1e-3)
        want.update(held[max(0, i - LABEL_CONTEXT):i + 1])
    want = sorted(want)
    stored_idx = {float(f["t_ms"]): f["frame_idx"] for f in a["frames_rows"]}
    ca, cb = _candidates(sid, "1.0", want, stored_idx), _candidates(sid, cond, want, stored_idx)
    out = Counter()
    examples = []
    for t in pick:
        for mine, other, side in ((cb, ca, f"{cond}_only"), (ca, cb, "1.0_only")):
            acc = [c for c in mine if c["t_ms"] == t and c["channel"] == "ally"
                   and c["reason"] == "eligible"]
            oth = [c for c in other if c["t_ms"] == t and c["channel"] == "ally"]
            oacc = [c for c in oth if c["reason"] == "eligible"]
            for c in acc:
                if any(math.hypot(c["cx"] - o["cx"], c["cy"] - o["cy"]) <= HIT_PX for o in oacc):
                    continue
                near = min(oth, key=lambda o: math.hypot(c["cx"] - o["cx"], c["cy"] - o["cy"]),
                           default=None)
                d = None if near is None else math.hypot(c["cx"] - near["cx"], c["cy"] - near["cy"])
                why = ("no_fit" if near is None or d > 2 * HIT_PX else near["reason"])
                if why == "shape_gate":
                    why += (":cov" if near["cov"] < 0.25 else ":inner")
                out[f"{side}: other {why}"] += 1
                if len(examples) < 12:
                    examples.append({"t_ms": t, "side": side, "fit": {k: round(c[k], 3) if
                                     isinstance(c[k], float) else c[k] for k in
                                     ("cx", "cy", "r", "cov", "inner", "area")},
                                     "other": None if near is None else {
                                         k: round(near[k], 3) if isinstance(near[k], float)
                                         else near[k] for k in
                                         ("cx", "cy", "r", "cov", "inner", "area", "reason")}})
    sa = [c for c in ca if c["channel"] == "self" and c["t_ms"] in pick]
    sb = [c for c in cb if c["channel"] == "self" and c["t_ms"] in pick]
    return {"session_id": sid, "condition": cond, "differing_frames": len(diff_t),
            "explained_frames": len(pick), "causes": dict(out.most_common()),
            "self_accepted": {"1.0": sum(c["reason"] == "eligible" for c in sa),
                              cond: sum(c["reason"] == "eligible" for c in sb)},
            "self_best_fit": {k: _self_summary(v, pick) for k, v in (("1.0", sa), (cond, sb))},
            "examples": examples}


def _record(res: dict, labels: bool) -> None:
    """One `metrics` row per score: series `upscale_trial/roster` or
    `upscale_trial/labels`, fields `<metric>_<condition>` with the condition's
    dot dropped (`mae_1p2`, `d_mae_2p0`)."""
    from reticle import metrics
    tag = lambda c: c.replace(".", "p")
    values = {}
    for cond, m in res["conditions"].items():
        for k, v in m.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                values[f"{k}_{tag(cond)}"] = v
            elif isinstance(v, str) and "/" in v:
                hit, n = v.split("/")
                values[f"{k}_{tag(cond)}"] = int(hit)
                values[f"{k}_n_{tag(cond)}"] = int(n)
    for cond, d in res.get("vs_A", {}).items():
        for k in ("d_mae", "d_exact"):
            values[f"{k}_{tag(cond)}"], values[f"{k}_lo_{tag(cond)}"], \
                values[f"{k}_hi_{tag(cond)}"] = d[k]
        for k in ("noise_bound_mae", "noise_bound_exact", "frames_differ", "matched_icons",
                  "centre_shift_px_p50", "centre_shift_px_p90", "facing_shift_deg_p50"):
            if d.get(k) is not None:
                values[f"{k}_{tag(cond)}"] = d[k]
    metrics.record("upscale_trial", part="labels" if labels else "roster",
                   session=res["session_id"], values=values,
                   deps={"version": VERSION, "ally_icon_version": ALLY_ICON_VERSION,
                         "conditions": sorted(res["conditions"])},
                   context={"tag": res.get("tag", "labels"), "basis": res.get("basis")},
                   note=f"task {TASK}; files analysis/{TASK}/")


# ------------------------------------------------------------------ sheet
def sheet(sid: str, t_ms: float, scale: float = 1.2, zoom: int = 6) -> Path:
    """The widget crop at `t_ms`, native and Lanczos-enlarged, plus each
    stored icon's neighbourhood at both, magnified nearest-neighbour so the
    pixels show as they are."""
    store, man, profile, ctx = _session(sid)
    cache, why = RoiCache.load(store.root, man, profile, "minimap")
    if cache is None:
        raise SystemExit(why)
    held = cache.holds()
    t = held[min(range(len(held)), key=lambda i: abs(held[i] - t_ms))]
    smp = next(cache.samples([t], rois=("minimap",)))
    x0, y0, x1, y1 = ally_icon_reader(ctx).box
    crop = smp.frame[y0:y1, x0:x1]
    big = _resize_crop(crop, f"{scale:g}")
    icons = [r for r in store.read_events_kind("ally_icon", sid, "icon")
             if r.get("kind") == "icon" and abs(float(r["t_ms"]) - t) < 1e-3] \
        if store.has_events("ally_icon", sid) else []
    tiles = []
    for ic in icons[:6]:
        cx, cy = ic["cx"], ic["cy"]
        n = crop[max(0, int(cy) - 12):int(cy) + 13, max(0, int(cx) - 12):int(cx) + 13]
        bx, by = cx * scale, cy * scale
        h2 = int(12 * scale)
        e = big[max(0, int(by) - h2):int(by) + h2 + 1, max(0, int(bx) - h2):int(bx) + h2 + 1]
        a = cv2.resize(n, None, fx=zoom * scale, fy=zoom * scale, interpolation=cv2.INTER_NEAREST)
        b = cv2.resize(e, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        hh = max(a.shape[0], b.shape[0])
        pad = lambda m: cv2.copyMakeBorder(m, 0, hh - m.shape[0], 0, 4, cv2.BORDER_CONSTANT)
        tiles.append(np.hstack([pad(a), pad(b)]))
    OUT.mkdir(parents=True, exist_ok=True)
    p1 = OUT / f"sheet_{sid}_{int(t)}_widget.png"
    cv2.imwrite(str(p1), np.hstack([cv2.resize(crop, (big.shape[1], big.shape[0]),
                                               interpolation=cv2.INTER_NEAREST), big]))
    if tiles:
        w = max(x.shape[1] for x in tiles)
        cv2.imwrite(str(OUT / f"sheet_{sid}_{int(t)}_icons.png"),
                    np.vstack([cv2.copyMakeBorder(x, 0, 4, 0, w - x.shape[1], cv2.BORDER_CONSTANT)
                               for x in tiles]))
    print(f"t={t} icons={len(icons)} wrote {p1}")
    return p1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("run")
    a.add_argument("session")
    a.add_argument("--scale", choices=CONDITIONS, required=True)
    a.add_argument("--between", nargs=2, type=float, help="seconds")
    a.add_argument("--labels", action="store_true")
    a.add_argument("--limit", type=int, help="first N frames only (a timing probe)")
    b = sub.add_parser("score")
    b.add_argument("session")
    b.add_argument("--between", nargs=2, type=float, help="seconds")
    b.add_argument("--labels", action="store_true")
    b.add_argument("--record", action="store_true", help="append a metrics row")
    e = sub.add_parser("explain")
    e.add_argument("session")
    e.add_argument("--between", nargs=2, type=float, required=True, help="seconds")
    e.add_argument("--scale", choices=CONDITIONS, default="1.2")
    e.add_argument("-n", type=int, default=40)
    c = sub.add_parser("sheet")
    c.add_argument("session")
    c.add_argument("--at", type=float, required=True)
    c.add_argument("--scale", type=float, default=1.2)
    args = ap.parse_args(argv)
    _idle()
    if args.cmd == "run":
        run_condition(args.session, args.scale, args.between, args.labels, args.limit)
    elif args.cmd == "score":
        if args.labels:
            res = score_labels(args.session)
        else:
            tag = f"{int(args.between[0])}-{int(args.between[1])}" if args.between else "all"
            res = score(args.session, tag)
        print(json.dumps(res, indent=1, default=str))
        if args.record:
            _record(res, args.labels)
        OUT.mkdir(parents=True, exist_ok=True)
        name = "labels" if args.labels else tag
        (OUT / f"score_{args.session}_{name}.json").write_text(
            json.dumps(res, indent=1, default=str), encoding="utf-8")
    elif args.cmd == "explain":
        res = explain_diff(args.session, args.between, args.n, args.scale)
        print(json.dumps(res, indent=1))
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"explain_{args.session}_{int(args.between[0])}-{int(args.between[1])}"
               f"_{args.scale}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    else:
        sheet(args.session, args.at, args.scale)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
