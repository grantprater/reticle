r"""Ask the player which way ally and enemy minimap icons point, to score the teardrop facing.

    .\.venv\Scripts\python.exe prototypes\label_icon_facing.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_icon_facing.py

The self icon's labels (`label_self_facing.py`) scored the teardrop
(`teardrop_tip.py`) at a median 2.2 degrees with 7% flipped on Lotus, and the
ring fit's facing at 105.5 degrees with half flipped. Teammates carry the same
ring fit (`minimap.ally_icons`), and the enemy ring (`minimap_ring_fit`) reads
its facing the same way. `icon_teardrop.py` extends the teardrop to both
classes; this asks the player, blind, where each icon points, and
`icon_facing_eval.py` scores both readers against the answers.

**Prepare** reads the minimap crop cache (no decode) every `STRIDE`-th frame of
5822b6646448 (Lotus, C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) and
a06f04a0059f (Ascent, C:\Users\grant\Videos\2026-08-26 09-56-37.mp4), outside
the minutes `icon_teardrop` calibrates on. For every ally and enemy detection
it runs the class's ring fit and the teardrop, then draws `QUOTA` items per
class, half from each session where the pool allows, each at least `GAP_MS`
from the others of its class:

    flip      ring and teardrop facing differ by over 90 degrees
    disagree  they differ by 20 to 90 degrees
    agree     they differ by at most `AGREE_DEG`
    refused   one reader refuses: the teardrop (a reason) or the ring fit
              (no lobe past `LOBE_MIN_FRAC`), the other reads
    random    detections drawn with no regard to either reader
    stacked   another icon of any class within `STACK_PX` of the centre
    spike     an ally with yellow at its lower left, where the carried spike
              is drawn (a sampling cue only; Killjoy's glyphs are yellow too)

`index.json` holds each item and why it was drawn; `readings.json` every pooled
detection. The labeller shows neither: it rings the candidate at the teardrop's
centre where it reads, the detector's where it refuses, and asks blind.

**Ask.** Two panels: the icon at 10x and the map round it at 3x, the same place
ringed in both. Click in either panel.

    left-click   first the CENTRE of the portrait, then the TIP it points to
    right-click  undo the last mark
    SPACE / D    save and advance (needs both marks)
    U            can't tell -- recorded, kept OUT of scoring
    N            the ringed thing is NOT an ally or enemy icon
    A            back one (re-answer; the last row for a key wins)
    Q / ESC      save and quit

Answers append to the store's `labels/icon_facing_20260928.jsonl`, keyed by
session, time and ring position, flushed per row; a restart skips answered
keys. Rows hold the clicks in crop pixels and the facing in image degrees
(y down), and no reader value. Never seed this file; `--labels` points a test
run at a scratch file.

**The 331 px ally set** (`--set ally_facing_331_20260929`). E10 found the
teardrop (`teardrop.IconPoseReader`) and the ring fit's lobe
(`cone.resolve_lobe`) point more than 90 degrees apart on a fifth of ally
reads on c40d950031bb (331 px, C:\Users\grant\Videos\2026-08-24 18-27-17.mp4)
and a twelfth on 223d636bf8d2; no labels cover that widget size.

    .\.venv\Scripts\python.exe prototypes\label_icon_facing.py --set ally_facing_331_20260929 --prepare
    .\.venv\Scripts\python.exe prototypes\label_icon_facing.py --set ally_facing_331_20260929

Prepare reads every `STRIDE_331`-th cached frame (crop cache, no decode) whose
`gametime` phase is `round_live` or `post_plant` on an unstalled source, and
runs `team_vision_eval.pose_check` on them: the widget gate (`widget_drawn`),
the ally detector, the teardrop at the widget's scale and the ring fit's
lobe. From the icons both readers face it draws, per session (`QUOTA_331`),
half `flip` (over 90 degrees apart) and half `agree` (within
`AGREE_331_DEG`), each stratum spread round-robin over the session's NCC
terciles, each item at least `GAP_MS_331` from the others of its session.
The ring and the patch sit at the midpoint of the two readers' centres,
rounded to a pixel, so neither reader places them. `index.json` holds only
what the labeller shows; `manifest.json` (never shown) holds each item's
readers, centres, NCC and stratum, and `readings.json` the whole pool.
Answers go to the store's `labels/ally_facing_331_20260929.jsonl`;
`icon_facing_eval.py --set ally_facing_331_20260929` scores them.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import icon_teardrop as it_  # noqa: E402
import label_self_facing as lsf  # noqa: E402
import teardrop_tip as tt  # noqa: E402

VERSION = "label-icon-facing-0.1.0"
CLASS_SET = "icon_facing-1"
NAME = "icon_facing_20260928"
SESSIONS = it_.SESSIONS
STRIDE = 20                  # every 20th cached frame, about one every two seconds
GAP_MS = 4000.0              # items of one class at least this far apart within a session
AGREE_DEG = 10.0
MID_DEG = (20.0, 90.0)
STACK_PX = 22.0              # two icon centres nearer than two outer radii overlap
SPIKE_BOX = (-22, -4, 4, 22)  # dx0, dx1, dy0, dy1 from an ally's centre: the carried glyph
SPIKE_MIN_PX = 25
QUOTA = {
    "ally": {"flip": 7, "disagree": 6, "agree": 5, "refused": 4, "random": 4, "stacked": 2, "spike": 2},
    "enemy": {"flip": 7, "disagree": 6, "agree": 5, "refused": 5, "random": 4, "stacked": 3},
}
SEED = 20260928


# The 331 px ally set: the widget size E10 left unlabelled.
SET_331 = "ally_facing_331_20260929"
SETS = (NAME, SET_331)
VERSION_331 = "label-ally-facing-331-0.1.0"
CLASS_SET_331 = "ally_facing_331-1"
QUOTA_331 = {"c40d950031bb": {"flip": 15, "agree": 15}, "223d636bf8d2": {"flip": 5, "agree": 5}}
STRIDE_331 = {"c40d950031bb": 10, "223d636bf8d2": 25}   # about one live frame a second / 2.5 s
LIVE_PHASES = ("round_live", "post_plant")
AGREE_331_DEG = 30.0
FLIP_DEG = 90.0
GAP_MS_331 = 3000.0
SEED_331 = 20260929
#: The 331 px icon is 0.71 of the 465 px one: zoom closer, ring tighter.
VIEW_331 = {"zh": 18, "zf": 15, "ring_r": 17.0}


def items_dir(store: Path, name: str = NAME) -> Path:
    return store / "labels" / name


def labels_path(store: Path, name: str = NAME) -> Path:
    return store / "labels" / f"{name}.jsonl"


def item_key(sid: str, t_ms: float, x: float, y: float) -> str:
    return f"{sid}|{float(t_ms):.1f}|{x:.1f},{y:.1f}"


load_answers = lsf.load_answers


# ---------------------------------------------------------------- prepare

def read_pool(s, times) -> list[dict]:
    """Every ally and enemy detection at `times`, both readers, and the context cues."""
    pool = []
    prev: dict[str, tuple] = {}
    for t, crop in s.crops(times):
        yel = tt.yellowness(crop)
        selves = it_.detections(crop, "self", s)
        dets = {cls: it_.detections(crop, cls, s) for cls in ("ally", "enemy")}
        centres = [(d["cx"], d["cy"]) for d in selves] + \
                  [(d["cx"], d["cy"]) for c in dets.values() for d in c]
        for cls, ds in dets.items():
            key = it_.CLASSES[cls].key(crop)
            rows = []
            for d in ds:
                f = it_.fit(None, cls, d["cx"], d["cy"], key=key)
                row = {"session": s.sid, "t_ms": float(t), "cls": cls,
                       "det_x": float(d["cx"]), "det_y": float(d["cy"]), "det_r": int(d["r"]),
                       "ring_deg": d.get("facing"), "read": bool(f.get("read")),
                       "reason": f.get("reason"), "ncc": f.get("ncc"), "margin": f.get("margin"),
                       "ring_cover": f.get("ring_cover")}
                if "x" in f:
                    row.update(tip_x=f["x"], tip_y=f["y"], tip_deg=f["deg"])
                row["stacked"] = any(0.5 < math.hypot(cx - d["cx"], cy - d["cy"]) < STACK_PX
                                     for cx, cy in centres)
                if cls == "ally":
                    row["spike_px"] = spike_px(yel, d, selves)
                if row["read"] and row["ring_deg"] is not None:
                    row["diff_deg"] = float(abs(sem._signed_deg(row["ring_deg"] - row["tip_deg"])))
                rows.append(row)
            # The minimap repeats an image across cached frames; keep one of each.
            sig = tuple(sorted((round(r["det_x"], 2), round(r["det_y"], 2)) for r in rows))
            if rows and sig == prev.get(cls):
                continue
            prev[cls] = sig
            pool += rows
    return pool


def spike_px(yel: np.ndarray, d: dict, selves) -> int:
    """Yellow pixels in the box at an ally's lower left, less the self icon's disc."""
    dx0, dx1, dy0, dy1 = SPIKE_BOX
    h, w = yel.shape
    x0, x1 = max(0, int(d["cx"] + dx0)), min(w, int(d["cx"] + dx1))
    y0, y1 = max(0, int(d["cy"] + dy0)), min(h, int(d["cy"] + dy1))
    if x1 <= x0 or y1 <= y0:
        return 0
    m = yel[y0:y1, x0:x1] >= 0.5
    yy, xx = np.mgrid[y0:y1, x0:x1]
    for sd in selves:
        m &= np.hypot(xx - sd["cx"], yy - sd["cy"]) > tt.L
    return int(m.sum())


def spaced(cands, n, taken, rng):
    """Up to `n` of `cands`, alternating sessions where both have some, each
    `GAP_MS` from every taken item of its class in its session."""
    by = {sid: [c for c in cands if c["session"] == sid] for sid in SESSIONS}
    for v in by.values():
        rng.shuffle(v)
    out = []
    order = [sid for sid in SESSIONS if by[sid]]
    i = 0
    while len(out) < n and any(by[sid] for sid in order):
        sid = order[i % len(order)]
        i += 1
        while by[sid]:
            c = by[sid].pop()
            if all(c["session"] != o["session"] or c["cls"] != o["cls"]
                   or abs(c["t_ms"] - o["t_ms"]) >= GAP_MS for o in taken + out):
                out.append(c)
                break
    return out


def select(pool: list[dict]) -> list[dict]:
    rng = random.Random(SEED)
    taken: list[dict] = []
    lo, hi = MID_DEG
    for cls, quota in QUOTA.items():
        mine = [r for r in pool if r["cls"] == cls]
        both = [r for r in mine if "diff_deg" in r]
        rules = {
            "flip": ([r for r in both if r["diff_deg"] > 90.0],
                     lambda r: f"ring and teardrop facing differ by {r['diff_deg']:.0f} deg (over 90)"),
            "disagree": ([r for r in both if lo < r["diff_deg"] <= hi],
                         lambda r: f"ring and teardrop facing differ by {r['diff_deg']:.0f} deg ({lo:.0f}-{hi:.0f})"),
            "agree": ([r for r in both if r["diff_deg"] <= AGREE_DEG],
                      lambda r: f"ring and teardrop facing within {AGREE_DEG:.0f} deg ({r['diff_deg']:.1f})"),
            "refused": ([r for r in mine if r["read"] != (r["ring_deg"] is not None)],
                        lambda r: (f"teardrop refuses ({r['reason']}, ncc {r['ncc']}), ring reads" if not r["read"]
                                   else "ring fit has no lobe, teardrop reads")),
            "random": (mine, lambda r: "detection drawn uniformly, readers ignored"),
            "stacked": ([r for r in mine if r["stacked"]],
                        lambda r: f"another icon within {STACK_PX:.0f} px"),
            "spike": ([r for r in mine if r.get("spike_px", 0) >= SPIKE_MIN_PX],
                      lambda r: f"{r['spike_px']} yellow px at the lower left (spike carrier cue)"),
        }
        for st, n in quota.items():
            cands, why = rules[st]
            if st == "refused":
                # Up to half where the ring fit refuses (rare), the rest where
                # the teardrop does.
                b = spaced([r for r in cands if r["read"]], n // 2, taken, rng)
                a = spaced([r for r in cands if not r["read"]], n - len(b), taken + b, rng)
                got = a + b
            else:
                got = spaced(cands, n, taken, rng)
            for r in got:
                r["stratum"], r["why"] = st, why(r)
            taken += got
    rng.shuffle(taken)
    return taken


def prepare(store: Path, reuse: Path | None = None) -> int:
    sem._below_normal()
    out = items_dir(store)
    if (out / "index.json").is_file():
        raise SystemExit(f"{out / 'index.json'} exists; a new item set needs a new NAME")
    sessions, pools = {}, {}
    if reuse is not None:
        old = json.loads(reuse.read_text(encoding="utf-8"))
        if old["meta"]["version"] != VERSION or old["meta"]["teardrop"] != it_.VERSION \
                or old["meta"]["stride"] != STRIDE:
            raise SystemExit(f"{reuse}: read by another version or stride")
    for sid in SESSIONS:
        s = sem.Session(sid)
        sessions[sid] = s
        if reuse is not None:
            pools[sid] = old["pool"][sid]
            continue
        T = np.unique(np.asarray(s.cache_t, float))
        times = [t for t in T[::STRIDE] if not it_.held_out(t)]
        print(f"{sid}: reading {len(times)} of {len(T)} cached frames", flush=True)
        pools[sid] = read_pool(s, times)
        p = pools[sid]
        for cls in ("ally", "enemy"):
            c = [r for r in p if r["cls"] == cls]
            print(f"  {cls}: {len(c)} detections, {sum(r['read'] for r in c)} teardrop read, "
                  f"{sum(r['ring_deg'] is not None for r in c)} ring read, "
                  f"{sum(r.get('diff_deg', 0) > 90 for r in c)} over 90 deg apart", flush=True)
    items = select([r for sid in SESSIONS for r in pools[sid]])
    (out / "patches").mkdir(parents=True, exist_ok=True)
    for sid in SESSIONS:
        mine = sorted((r for r in items if r["session"] == sid), key=lambda r: r["t_ms"])
        times = sorted({r["t_ms"] for r in mine})
        crops = dict(sessions[sid].crops(times))
        for r in mine:
            crop = crops[r["t_ms"]]
            cx, cy = (r["tip_x"], r["tip_y"]) if r["read"] else (r["det_x"], r["det_y"])
            patch, x0, y0 = lsf.patch_of(crop, cx, cy)
            name = f"{sid}_{int(round(r['t_ms']))}_{int(round(cx))}_{int(round(cy))}.png"
            cv2.imwrite(str(out / "patches" / name), patch)
            r.update(key=item_key(sid, r["t_ms"], cx, cy), ring_x=cx, ring_y=cy, patch=name,
                     patch_x0=x0, patch_y0=y0)
    index = [{k: r[k] for k in ("key", "session", "t_ms", "cls", "det_x", "det_y", "ring_x", "ring_y",
                                "patch", "patch_x0", "patch_y0", "stratum", "why", "stacked")}
             for r in items]
    meta = {"version": VERSION, "teardrop": it_.VERSION, "class_set": CLASS_SET, "stride": STRIDE,
            "gap_ms": GAP_MS, "agree_deg": AGREE_DEG, "mid_deg": MID_DEG, "stack_px": STACK_PX,
            "quota": QUOTA, "seed": SEED, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "index.json").write_text(json.dumps({"meta": meta, "items": index}, indent=1), encoding="utf-8")
    (out / "readings.json").write_text(json.dumps({"meta": meta, "pool": pools}, indent=0), encoding="utf-8")
    for cls in QUOTA:
        counts = {k: sum(r["cls"] == cls and r["stratum"] == k for r in index) for k in QUOTA[cls]}
        per_sid = {sid: sum(r["cls"] == cls and r["session"] == sid for r in index) for sid in SESSIONS}
        print(f"{cls}: {sum(counts.values())} items {counts} {per_sid}")
    print(f"prepared {len(index)} items -> {out}")
    return 0


# ---------------------------------------------------------------- prepare, 331 px allies

def idle() -> None:
    """Idle priority: the player's own jobs come first."""
    try:
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x40)   # IDLE_PRIORITY_CLASS
    except Exception:
        pass


def live_times(sid: str, cache_t, stride: int) -> tuple[list[float], dict]:
    """Every `stride`-th cached frame in a live phase (`gametime.get_phase`) on an
    unstalled source, and the counts that say what the gate dropped."""
    from reticle import gametime, geometry, stalls
    from reticle.store import Store
    st = Store(sem.STORE)
    date = geometry.manifest(sid, sem.STORE)["ingested_at"][:10]
    rs, hud = st.read_rounds(sid, date), st.read_hud(sid, date)
    if rs is None or hud is None:
        raise SystemExit(f"{sid}: no stored rounds or HUD; the phase gate cannot run")
    gt = gametime.build_session_gametime(sid, hud, rs.to_pylist(),
                                         stall_list=stalls.for_session(st, sid, date))
    T = np.unique(np.asarray(cache_t, float))
    phases = [gt.game_time_at(float(t)).phase for t in T]
    live = [float(t) for t, ph in zip(T, phases) if ph in LIVE_PHASES and not gt.is_stalled_at(float(t))]
    return live[::stride], {"cached": int(len(T)), "phases": dict(Counter(phases)), "live": len(live),
                            "read": len(live[::stride])}


def select_331(pool: dict) -> list[dict]:
    """Per session and stratum, round-robin over the session's NCC terciles,
    each item `GAP_MS_331` from every other item of its session."""
    rng = random.Random(SEED_331)
    taken: list[dict] = []
    for sid, quota in QUOTA_331.items():
        both = [r for r in pool[sid] if r.get("dis") is not None]
        cuts = [float(v) for v in np.percentile([r["ncc"] for r in both], [100 / 3, 200 / 3])]
        for r in both:
            r["ncc_bin"] = int(np.searchsorted(cuts, r["ncc"], side="right"))
        strata = {"flip": [r for r in both if r["dis"] > FLIP_DEG],
                  "agree": [r for r in both if r["dis"] <= AGREE_331_DEG]}
        for st, n in quota.items():
            bins = {b: [r for r in strata[st] if r["ncc_bin"] == b] for b in range(3)}
            for v in bins.values():
                rng.shuffle(v)
            got, b = [], 0
            while len(got) < n and any(bins.values()):
                cand = bins[b % 3]
                b += 1
                while cand:
                    c = cand.pop()
                    if all(c["session"] != o["session"] or abs(c["t"] - o["t"]) >= GAP_MS_331
                           for o in taken + got):
                        got.append(dict(c, stratum=st, ncc_cuts=cuts))
                        break
            if len(got) < n:
                print(f"  {sid} {st}: only {len(got)} of {n} spaced candidates")
            taken += got
    return taken


def prepare_331(store: Path, limit: int | None = None) -> int:
    """`limit` caps the frames read per session: a timing run, which writes nothing."""
    import team_vision_eval as tve
    idle()
    out = items_dir(store, SET_331)
    if limit is None and (out / "index.json").is_file():
        raise SystemExit(f"{out / 'index.json'} exists; a new item set needs a new name")
    pool, gates = {}, {}
    for sid in QUOTA_331:
        s = tve.Sess(sid)
        times, gates[sid] = live_times(sid, s.cache_t, STRIDE_331[sid])
        if limit is not None:
            times = times[:limit]
        print(f"{sid}: {gates[sid]}; reading {len(times)} live frames", flush=True)
        res = tve.pose_check(sid, times=times)
        by_t: dict[float, list] = {}
        for r in res["rows"]:
            if r["role"] == "ally":
                by_t.setdefault(r["t"], []).append(r)
        rows, prev = [], None
        for t in sorted(by_t):
            rs = by_t[t]
            # The minimap repeats an image across cached frames; keep one of each.
            sig = tuple(sorted((round(r["det_x"], 2), round(r["det_y"], 2)) for r in rs))
            if sig == prev:
                continue
            prev = sig
            for r in rs:
                r["session"] = sid
                r["stacked"] = any(0.5 < math.hypot(o["det_x"] - r["det_x"], o["det_y"] - r["det_y"]) < STACK_PX
                                   for o in rs if o is not r)
                if r.get("dis") is not None and r["ring"] is not None:
                    r["dis_raw"] = abs(float(sem._signed_deg(r["deg"] - r["ring"])))
            rows += rs
        pool[sid] = rows
        both = [r for r in rows if r.get("dis") is not None]
        print(f"  {len(rows)} ally reads, {len(both)} with both facings, "
              f"{sum(r['dis'] > FLIP_DEG for r in both)} over {FLIP_DEG:.0f} deg apart, "
              f"{sum(r['dis'] <= AGREE_331_DEG for r in both)} within {AGREE_331_DEG:.0f}", flush=True)
    if limit is not None:
        print("timing run: nothing written")
        return 0
    items = select_331(pool)
    (out / "patches").mkdir(parents=True, exist_ok=True)
    index, manifest = [], []
    for sid in QUOTA_331:
        mine = sorted((r for r in items if r["session"] == sid), key=lambda r: r["t"])
        crops = dict(tve.Sess(sid).crops(sorted({r["t"] for r in mine})))
        for r in mine:
            # Neither reader places the ring: the midpoint of their centres, to a pixel.
            rx = float(round((r["x"] + r["det_x"]) / 2.0))
            ry = float(round((r["y"] + r["det_y"]) / 2.0))
            patch, x0, y0 = lsf.patch_of(crops[r["t"]], rx, ry)
            name = f"{sid}_{int(round(r['t']))}_{int(rx)}_{int(ry)}.png"
            cv2.imwrite(str(out / "patches" / name), patch)
            key = item_key(sid, r["t"], rx, ry)
            index.append({"key": key, "session": sid, "t_ms": float(r["t"]), "cls": "ally",
                          "ring_x": rx, "ring_y": ry, "patch": name, "patch_x0": x0, "patch_y0": y0})
            manifest.append({"key": key, "session": sid, "t_ms": float(r["t"]), "stratum": r["stratum"],
                             "ring_x": rx, "ring_y": ry, "stacked": r["stacked"],
                             "teardrop_deg": r["deg"], "teardrop_x": r["x"], "teardrop_y": r["y"],
                             "ncc": r["ncc"], "ncc_bin": r["ncc_bin"], "ncc_cuts": r["ncc_cuts"],
                             "ring_deg": r["ring"], "ring_lobe_deg": r["lobe"],
                             "det_x": r["det_x"], "det_y": r["det_y"], "det_r": r["r"],
                             "dis_lobe_deg": r["dis"], "dis_raw_deg": r.get("dis_raw"),
                             "lit_teardrop": r.get("lit_teardrop"), "lit_lobe": r.get("lit_lobe")})
    # The labeller's order mixes sessions and strata.
    random.Random(SEED_331 + 1).shuffle(index)
    from reticle.version import ALLY_ICON_VERSION, ICON_TEARDROP_VERSION
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {"version": VERSION_331, "class_set": CLASS_SET_331, "teardrop": ICON_TEARDROP_VERSION,
            "ally_icon": ALLY_ICON_VERSION, "instrument": tve.VERSION, "stride": STRIDE_331,
            "phases": LIVE_PHASES, "gap_ms": GAP_MS_331, "agree_deg": AGREE_331_DEG, "flip_deg": FLIP_DEG,
            "quota": QUOTA_331, "seed": SEED_331, "stack_px": STACK_PX, "view": VIEW_331,
            "ring_at": "midpoint of the teardrop's and the ring fit's centres, rounded to a pixel", "at": at}
    blind = {"version": VERSION_331, "class_set": CLASS_SET_331, "view": VIEW_331, "at": at}
    (out / "index.json").write_text(json.dumps({"meta": blind, "items": index}, indent=1), encoding="utf-8")
    (out / "manifest.json").write_text(json.dumps({"meta": meta, "gates": gates, "items": manifest},
                                                  indent=1), encoding="utf-8")
    (out / "readings.json").write_text(json.dumps({"meta": meta, "pool": pool}, indent=0), encoding="utf-8")
    for sid in QUOTA_331:
        m = [r for r in manifest if r["session"] == sid]
        print(f"{sid}: {len(m)} items, strata {dict(Counter(r['stratum'] for r in m))}, "
              f"NCC terciles {dict(Counter(r['ncc_bin'] for r in m))}")
    print(f"prepared {len(index)} items -> {out}")
    return 0


# ---------------------------------------------------------------- ask

def ask(args, store: Path) -> int:
    import tkinter as tk
    idir = items_dir(store, args.set)
    blob = json.loads((idir / "index.json").read_text(encoding="utf-8"))
    index = blob["items"]
    # The 331 px set zooms closer; the first set used the self labeller's view.
    view = blob["meta"].get("view") or {"zh": lsf.ZH, "zf": lsf.ZF, "ring_r": lsf.RING_R}
    zh, zf = view["zh"], view["zf"]
    tool, class_set = ((VERSION_331, CLASS_SET_331) if args.set == SET_331 else (VERSION, CLASS_SET))
    question = ("Click the ringed TEAMMATE icon's centre, then the tip it points to." if args.set == SET_331
                else "Is the ringed thing a teammate's or an enemy's icon? Click its centre, then its tip.")
    target = Path(args.labels) if args.labels else labels_path(store, args.set)
    done = load_answers(target)
    todo = [c for c in index if c["key"] not in done]
    print(f"{len(index)} items, {len(done)} answered, {len(todo)} left -> {target}")
    if not todo:
        print("nothing left to label")
        return 0
    handle = None if args.screenshot else target.open("a", encoding="utf-8")
    st = {"i": 0, "marks": []}
    keep = {}

    root = tk.Tk()
    root.title("which way does the ringed icon point")
    zw = (2 * zh + 1) * zf
    W = zw + lsf.GAP_PX + (2 * lsf.CTX + 1) * lsf.CF
    H = max(zw, (2 * lsf.CTX + 1) * lsf.CF)
    canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bg="#121212", cursor="crosshair")
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left", anchor="w")
    status.pack(fill="x")

    def draw_marks():
        canvas.delete("mark")
        pts = [lsf.patch_to_screens(*m, zh=zh, zf=zf) for m in st["marks"]]
        for panel in (0, 1):
            if len(pts) == 2:
                (x1, y1), (x2, y2) = pts[0][panel], pts[1][panel]
                canvas.create_line(x1, y1, x2, y2, fill="#00ff66", width=2, arrow="last", tags="mark")
            for j, p in enumerate(pts):
                x, y = p[panel]
                r = 6 if panel == 0 else 4
                canvas.create_oval(x - r, y - r, x + r, y + r, outline="#00ffff" if j == 0 else "#ff3030",
                                   width=2, tags="mark")
        c = todo[st["i"]]
        marks = ("click the CENTRE of the portrait" if not st["marks"] else
                 "click the TIP it points to" if len(st["marks"]) == 1 else "SPACE to save")
        status.configure(text=(
            f"{st['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f}s   -- {marks}\n"
            f"{question}  right-click undo\n"
            "SPACE/D save   U can't tell   N not an icon   A back   Q/ESC quit"))

    def show():
        if st["i"] >= len(todo):
            root.quit()
            return
        c = todo[st["i"]]
        patch = cv2.imread(str(idir / "patches" / c["patch"]), cv2.IMREAD_COLOR)
        ok, png = cv2.imencode(".png", lsf.compose(patch, zh=zh, zf=zf, ring_r=view["ring_r"]))
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))   # keep the reference
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        st["marks"] = []
        draw_marks()

    def write(answer, extra=None):
        c = todo[st["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"], "cls": c["cls"],
               "ring_x": c["ring_x"], "ring_y": c["ring_y"], "answer": answer, **(extra or {}),
               "by": args.by, "class_set": class_set, "tool": tool,
               "compared_against_derived": False,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if handle is not None:
            handle.write(json.dumps(row) + "\n")
            handle.flush()          # read the file as it fills
        st["i"] += 1
        show()

    def click(e):
        p = lsf.screen_to_patch(e.x, e.y, zh=zh, zf=zf)
        if p is None:
            return
        if len(st["marks"]) < 2:
            st["marks"].append(p)
        else:
            st["marks"][1] = p
        draw_marks()

    def undo(_e):
        if st["marks"]:
            st["marks"].pop()
            draw_marks()

    def save(_e):
        if len(st["marks"]) < 2:
            root.bell()
            return
        c = todo[st["i"]]
        (px, py), (qx, qy) = st["marks"]
        cx, cy = px + c["patch_x0"], py + c["patch_y0"]
        tx, ty = qx + c["patch_x0"], qy + c["patch_y0"]
        if math.hypot(tx - cx, ty - cy) < 1.0:
            root.bell()
            return
        write("facing", {"centre_x": round(cx, 2), "centre_y": round(cy, 2),
                         "tip_x": round(tx, 2), "tip_y": round(ty, 2),
                         "facing_deg": round(math.degrees(math.atan2(ty - cy, tx - cx)), 2)})

    def back(_e):
        st["i"] = max(0, st["i"] - 1)
        show()

    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    for k in ("<space>", "d", "D"):
        root.bind(k, save)
    for k in ("u", "U"):
        root.bind(k, lambda _e: write("cant_tell"))
    for k in ("n", "N"):
        root.bind(k, lambda _e: write("not_icon"))
    for k in ("a", "A"):
        root.bind(k, back)
    for k in ("q", "Q", "<Escape>"):
        root.bind(k, lambda _e: root.quit())
    show()
    if args.screenshot:
        # Two arbitrary marks, only to show how they draw; nothing is written.
        # `--bare` leaves them off, to see what the player first sees.
        C = lsf.CTX
        st["i"] = min(args.start, len(todo) - 1)
        show()
        if not args.bare:
            root.after(400, lambda: (st["marks"].extend([(C - 3.0, C + 2.0), (C + 14.0, C - 9.0)]),
                                     draw_marks()))
        root.after(1200, lambda: (lsf.grab(root, Path(args.screenshot)), root.quit()))
    root.mainloop()
    root.destroy()
    if handle is not None:
        handle.close()
        print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(sem.STORE))
    ap.add_argument("--set", choices=SETS, default=NAME,
                    help=f"item set (default {NAME}; {SET_331} is the 331 px ally set)")
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--limit", type=int, help=f"{SET_331} --prepare: read this many frames a session, "
                                              "time the run and write nothing")
    ap.add_argument("--labels", help="answers file (default: the store's labels/<set>.jsonl)")
    ap.add_argument("--screenshot", help="render an item, save the window as PNG, write nothing")
    ap.add_argument("--start", type=int, default=0, help="--screenshot: which unanswered item")
    ap.add_argument("--bare", action="store_true", help="--screenshot: draw no example marks")
    ap.add_argument("--reuse-readings", type=Path, help="prepare from a readings.json this version wrote")
    ap.add_argument("--by", default="player")
    args = ap.parse_args(argv)
    store = Path(args.store)
    if args.prepare:
        if args.set == SET_331:
            return prepare_331(store, args.limit)
        return prepare(store, args.reuse_readings)
    return ask(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
