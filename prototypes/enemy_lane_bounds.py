r"""Two fixes the 331 px queue asked for: the candidate's bounds, and a map gate.

    .\.venv\Scripts\python.exe prototypes\enemy_lane_bounds.py --bounds [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_bounds.py --gate [--record]
    .\.venv\Scripts\python.exe prototypes\enemy_lane_bounds.py --check-queue
    .\.venv\Scripts\python.exe prototypes\enemy_lane_bounds.py --score-check [--labels FILE] [--record]

The player labelled the 331 px queue (`enemy_lane_score.py --queue331`) and
noted two faults: the unsure rows are mostly enemy icons the ring cuts, often
at the tip, and many "nothing" rows are rust void just off the map
[domain:minimap/transparency]. Predictions FA1-FA4 and FB1-FB3 (task
`enemy-lane-score-20260930`) were logged before this ran.

**(a) Bounds.** The queue drew a fixed ring, 11 * scale px, round the red
blob's centroid (`adjudication.death.extract_minimap_death_marks`) or the
ring fit's centre (`icon_teardrop.detections`). An enemy icon's red sits
mostly in its lobe, so the centroid slides toward the tip. The fix fits the
enemy teardrop (`teardrop.fit_icon`) from the candidate and takes its centre;
an `ambiguous_facing` fit keeps its centre as position only. The box is
centred there with radius the fitted tip distance plus 1.5 * scale, which
holds the tip at either facing. Truth is the player's centre and tip:
`labels/enemy_facing_331_20260929.jsonl` (331 px) and the enemy rows of
`labels/icon_facing_20260928.jsonl` (465 px).

**(b) The map gate.** `extract_minimap_death_marks` masks red by
`floor_mask`, whose 9 px overhang admits the void round the map. Two gates
from baked geometry only (`team_vision.load_inputs`: slab and floor from the
geometry's reference static, never session pixels
[domain:capture/session-pixels-are-not-the-map]):

    centre     the candidate's centre lies on the slab dilated by ICON_PX * scale
    red_share  of `teardrop.redness` within ICON_PX * scale of the candidate,
               at least RED_SHARE lies on the slab

Both are scored on the player's void rows and on every labelled enemy, X and
"?" mark at both scales; a gate must drop none of those.

**(c) The held-out check** (task `enemy-fix-check-20260930`, CK1-CK6 logged
before the sample). Both fixes were tuned on the labels above, and the gate's
abstain clause came after FB3 failed. `--check-queue` samples five match
sessions no earlier label file names (Lotus and Sunset at 465 px; Haven,
Summit and Abyss at 331 px), freezes both fixes' calls on every red
opportunity in `labels/enemy_fix_check_20260930/calls.json`, the drops
included, and draws a fixed-seed queue: 6 uniform, then gate_drop, edge_keep,
boxed and refused strata. `label_enemy_fix_check.py` asks the player;
`--score-check` scores the answers.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import enemy_lane_score as els  # noqa: E402
import icon_portrait_gate as gate_  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import minimap_objects as m1  # noqa: E402
import minimap_objects_s2 as s2  # noqa: E402
from reticle import teardrop  # noqa: E402
from reticle.adjudication.death import extract_minimap_death_marks  # noqa: E402
from reticle.minimap import widget_drawn, widget_scale  # noqa: E402

VERSION = "enemy-lane-bounds-0.1.0"
STORE = els.STORE
OUT = els.OUT / "bounds"
RING = 11.0            # the queue's ring radius, * scale (label_enemy_lane_331.compose)
TIP_PAD = 1.5          # the fixed box's pad past the fitted tip, * scale
RED_SHARE = 0.25       # the red_share gate's floor
NEAR = 2.0             # a candidate belongs to a labelled icon within NEAR * ICON_PX * scale
POSITION_OK = (None, "ambiguous_facing")


# ------------------------------------------------------------------ helpers

class Geo:
    """One session's crops and baked masks, loaded once."""

    def __init__(self, sid: str):
        self.s = gate_.Lite(sid)
        self.slab = self.s.inputs.slab.astype(bool)
        self.floor = self.s.floor
        self.read = els.geometry_read(sid)
        self._dil = {}

    def slab_dilated(self, r: float) -> np.ndarray:
        k = int(round(r))
        if k not in self._dil:
            ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1))
            self._dil[k] = cv2.dilate(self.slab.astype(np.uint8), ker).astype(bool)
        return self._dil[k]

    def crop(self, t: float):
        tc = m1._cache_near(self.s, t)
        if tc is None:
            return None, None
        return tc, dict(self.s.crops([tc]))[tc]


def fitted(crop, x: float, y: float, sc: float) -> dict:
    """The enemy teardrop from (x, y): centre, tip distance, reason; position only when ambiguous."""
    f = teardrop.fit_icon(crop, "enemy", x, y, scale=sc)
    if "x" not in f:
        return {"ok": False, "reason": f.get("reason")}
    ok = f.get("reason") in POSITION_OK
    return {"ok": ok, "reason": f.get("reason"), "x": float(f["x"]), "y": float(f["y"]),
            "tip_d": float(math.hypot(f["tip_x"] - f["x"], f["tip_y"] - f["y"])),
            "tip_x": float(f["tip_x"]), "tip_y": float(f["tip_y"])}


def box_fixed(crop, x, y, sc) -> tuple[float, float, float, dict]:
    """The fix's box: fitted centre and tip-reaching radius, else the queue's ring unchanged."""
    f = fitted(crop, x, y, sc)
    if f["ok"]:
        return f["x"], f["y"], f["tip_d"] + TIP_PAD * sc, f
    return x, y, RING * sc, f


def red_share(crop, slab, x, y, sc) -> float | None:
    r = s2.ICON_PX * sc
    red = teardrop.redness(crop)
    h, w = red.shape
    yy, xx = np.mgrid[0:h, 0:w]
    disc = np.hypot(xx - x, yy - y) <= r
    tot = float(red[disc].sum())
    if tot <= 0:
        return None
    return float(red[disc & slab].sum()) / tot


def gates(g: Geo, crop, x, y, sc) -> dict:
    xi, yi = int(round(x)), int(round(y))
    h, w = g.slab.shape
    inside = 0 <= xi < w and 0 <= yi < h
    centre = bool(inside and g.slab_dilated(s2.ICON_PX * sc)[yi, xi])
    share = red_share(crop, g.slab, x, y, sc)
    # No red in the disc: the gate has nothing to judge and abstains (keeps).
    # Amended after the first run, where the only labelled mark dropped was a
    # blue X (c62c2b06bcfb 480.9 s) with no red at all.
    return {"centre": centre, "red_share": share, "red_keep": share is None or share >= RED_SHARE}


def _med(v):
    return None if not v else round(float(np.median(v)), 2)


# ------------------------------------------------------------------ (a) bounds

def facing_truth() -> list[dict]:
    rows = []
    for line in (STORE / "labels" / "enemy_facing_331_20260929.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows.append({**r, "scale_set": "331"})
    for line in (STORE / "labels" / "icon_facing_20260928.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("cls") == "enemy":
                rows.append({**r, "scale_set": "465"})
    last = {}
    for r in rows:
        last[(r["scale_set"], r["key"])] = r        # the last row for a key wins
    return [r for r in last.values() if r.get("answer") == "facing" and r.get("centre_x") is not None]


def run_bounds(record: bool) -> int:
    geos, out = {}, []
    for r in facing_truth():
        sid = r["session"]
        g = geos.get(sid) or geos.setdefault(sid, Geo(sid))
        tc, crop = g.crop(r["t_ms"])
        if crop is None:
            out.append({"scale_set": r["scale_set"], "why": "no_frame"})
            continue
        sc = widget_scale(crop.shape[1])
        cx, cy, tx, ty = r["centre_x"], r["centre_y"], r["tip_x"], r["tip_y"]
        near = NEAR * s2.ICON_PX * sc
        blobs = [(bx, by) for _a, bx, by in extract_minimap_death_marks(crop, g.floor)[1]]
        rings = [(d["cx"], d["cy"]) for d in it_.detections(crop, "enemy", g.s)]
        row = {"scale_set": r["scale_set"], "key": r["key"], "sc": sc,
               "tip_d_player": math.hypot(tx - cx, ty - cy)}
        for name, pts in (("blob", blobs), ("ring", rings), ("label", [(r["ring_x"], r["ring_y"])])):
            best = min(pts, key=lambda p: math.hypot(p[0] - cx, p[1] - cy), default=None)
            if best is None or math.hypot(best[0] - cx, best[1] - cy) > near:
                row[name] = None
                continue
            x, y = best
            fx, fy, fr, f = box_fixed(crop, x, y, sc)
            row[name] = {"err": math.hypot(x - cx, y - cy), "tip_in": math.hypot(tx - x, ty - y) <= RING * sc,
                         "fix_err": math.hypot(fx - cx, fy - cy), "fix_tip_in": math.hypot(tx - fx, ty - fy) <= fr,
                         "fix_r": fr, "fit_ok": f["ok"], "fit_reason": f.get("reason"),
                         "fit_tip_err": (math.hypot(f["tip_x"] - tx, f["tip_y"] - ty)
                                         if f["ok"] and f["reason"] is None else None)}
        out.append(row)
    values = {}
    for ss in ("331", "465"):
        rs = [o for o in out if o.get("scale_set") == ss and "key" in o]
        values[f"{ss}_n"] = len(rs)
        values[f"{ss}_tip_d_player_median"] = _med([o["tip_d_player"] for o in rs])
        for name in ("blob", "ring", "label"):
            got = [o[name] for o in rs if o.get(name)]
            fit = [c for c in got if c["fit_ok"]]
            values[f"{ss}_{name}_n"] = len(got)
            values[f"{ss}_{name}_err_median"] = _med([c["err"] for c in got])
            values[f"{ss}_{name}_tip_in"] = sum(c["tip_in"] for c in got)
            values[f"{ss}_{name}_fit_ok"] = len(fit)
            values[f"{ss}_{name}_fit_ambiguous"] = sum(c["fit_reason"] == "ambiguous_facing" for c in fit)
            values[f"{ss}_{name}_fix_err_median"] = _med([c["fix_err"] for c in got])
            values[f"{ss}_{name}_fix_err_median_fitted"] = _med([c["fix_err"] for c in fit])
            values[f"{ss}_{name}_fix_tip_in"] = sum(c["fix_tip_in"] for c in got)
            values[f"{ss}_{name}_fix_tip_in_fitted"] = sum(c["fix_tip_in"] for c in fit)
            values[f"{ss}_{name}_fit_tip_err_median"] = _med([c["fit_tip_err"] for c in fit
                                                              if c["fit_tip_err"] is not None])
            for why, n in Counter(str(c["fit_reason"]) for c in got if not c["fit_ok"]).items():
                values[f"{ss}_{name}_unfit_{why}"] = n
    print(els._j(values), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "bounds.json").write_text(els._j(out), encoding="utf-8")
    queue_u = run_queue_shift(geos)
    values.update(queue_u)
    print(els._j(queue_u), flush=True)
    if record:
        els._record("bounds", "c40d950031bb+223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372", values,
                    {"bounds": VERSION, "geometry": {sid: g.read for sid, g in geos.items()}},
                    "candidate box against the player's enemy centre and tip; fixed ring vs teardrop fit")
    return 0


def queue_rows() -> list[dict]:
    base = STORE / "labels" / els.SET331
    idx = {i["key"]: i for i in json.loads((base / "index.json").read_text(encoding="utf-8"))["items"]}
    q = json.loads((base / "queue.json").read_text(encoding="utf-8"))["items"]
    ask = {a["key"]: a for a in json.loads((base / "ask.json").read_text(encoding="utf-8"))["items"]}
    ans = {}
    for line in (STORE / "labels" / f"{els.SET331}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            ans[r["key"]] = r
    out = []
    for it in q:
        a = ans.get(it["key"])
        if a is None:
            continue
        lab = "unsure" if a.get("uncertain") else a["answer"]
        out.append({**idx[it["key"]], "stratum": it["stratum"], "label": lab,
                    "patch": ask[it["key"]]["patch"]})
    return out


def run_queue_shift(geos: dict) -> dict:
    """Where the fit moves each queue candidate the player called unsure."""
    vals = {}
    shifts = []
    for r in queue_rows():
        if r["label"] != "unsure":
            continue
        g = geos.get(r["session"]) or geos.setdefault(r["session"], Geo(r["session"]))
        _tc, crop = g.crop(r["t_ms"])
        sc = widget_scale(crop.shape[1])
        fx, fy, fr, f = box_fixed(crop, r["x"], r["y"], sc)
        d = math.hypot(fx - r["x"], fy - r["y"])
        shifts.append(d)
        print("unsure", r["patch"], r["source"], f"shift {d:.1f} px r {fr:.1f}", f.get("reason"), flush=True)
        r.update(fix_x=fx, fix_y=fy, fix_r=fr, fit_reason=f.get("reason"))
        _sheet_tile(crop, r, sc)
    vals["queue_unsure_n"] = len(shifts)
    vals["queue_unsure_shift_ge2"] = sum(d >= 2.0 for d in shifts)
    vals["queue_unsure_shift_median"] = _med(shifts)
    return vals


def _sheet_tile(crop, r, sc):
    """The queue's ring (green) and the fix's box (magenta), 12x, for one row."""
    h, f = 20, 12
    pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT)
    xi, yi = int(round(r["x"])), int(round(r["y"]))
    t = cv2.resize(pad[yi:yi + 2 * h + 1, xi:xi + 2 * h + 1], None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
    def at(x, y):
        return int((h + 0.5 + x - xi) * f), int((h + 0.5 + y - yi) * f)
    cv2.circle(t, at(r["x"], r["y"]), int(RING * sc * f), (0, 255, 0), 2)
    cv2.circle(t, at(r["fix_x"], r["fix_y"]), int(r["fix_r"] * f), (255, 0, 255), 2)
    cv2.putText(t, f"{r['patch']} {r['fit_reason']}", (4, 22), 0, 0.7, (255, 255, 255), 2)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"unsure_{r['patch']}"), t)


# ------------------------------------------------------------------ (b) the gate

def marks_465() -> list[dict]:
    """The player's labelled enemy, X, "?" and other-red marks at 465 px, in crop pixels."""
    pts = []
    for sid in els.SESSIONS:
        for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("uncertain"):
                continue
            for mk in r.get("marks", []):
                if mk["kind"] in ("enemy", "question", "other_red"):
                    pts.append({"set": "minimap", "session": sid, "t_ms": float(r["t_ms"]),
                                "x": float(mk["x"]), "y": float(mk["y"]), "cls": mk["kind"], "roi": r.get("roi")})
    for p in sorted((STORE / "labels" / "minimap_dynamic").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "x_mark" and r.get("by") == "human" and not r.get("uncertain"):
                pts.append({"set": "dynamic", "session": r["session_id"], "t_ms": float(r["t_ms"]),
                            "x": float(r["x"]), "y": float(r["y"]), "cls": "x_mark", "roi": r.get("roi")})
    for line in (STORE / "labels" / "icon_facing_20260928.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r.get("cls") == "enemy" and r.get("answer") == "facing":
                pts.append({"set": "icon_facing", "session": r["session"], "t_ms": float(r["t_ms"]),
                            "x": float(r["centre_x"]), "y": float(r["centre_y"]), "cls": "enemy", "roi": None})
    return pts


def run_gate(record: bool) -> int:
    geos, values, drops = {}, Counter(), []
    def score(tag, sid, t, x, y, roi=None):
        g = geos.get(sid) or geos.setdefault(sid, Geo(sid))
        if roi is not None and list(roi) != list(g.s.box):
            values[f"{tag}_roi_mismatch"] += 1
            return None
        _tc, crop = g.crop(t)
        if crop is None:
            values[f"{tag}_no_frame"] += 1
            return None
        sc = widget_scale(crop.shape[1])
        gt = gates(g, crop, x, y, sc)
        values[f"{tag}_n"] += 1
        values[f"{tag}_centre_drop"] += not gt["centre"]
        values[f"{tag}_red_drop"] += not gt["red_keep"]
        return gt
    for p in marks_465():
        gt = score(f"465_{p['cls']}", p["session"], p["t_ms"], p["x"], p["y"], p["roi"])
        if gt and p["cls"] != "other_red" and not (gt["centre"] and gt["red_keep"]):
            drops.append({**p, **gt})
    shares = {}
    for r in queue_rows():
        tag = f"331_{r['label']}"
        gt = score(tag, r["session"], r["t_ms"], r["x"], r["y"])
        if gt is None:
            continue
        shares[r["patch"]] = (r["label"], None if gt["red_share"] is None else round(gt["red_share"], 2),
                              gt["centre"], gt["red_keep"])
        if r["label"] in ("enemy_icon", "x_mark", "question") and not (gt["centre"] and gt["red_keep"]):
            drops.append({**{k: r[k] for k in ("session", "t_ms", "x", "y", "patch")}, "cls": r["label"], **gt})
    for k, v in sorted(shares.items(), key=lambda kv: str(kv[1])):
        print(k, v, flush=True)
    values = dict(values)
    print(els._j(values), flush=True)
    print("labelled marks dropped:", els._j(drops), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "gate.json").write_text(els._j({"values": values, "drops": drops, "queue": shares}), encoding="utf-8")
    if record:
        els._record("map-gate", "c40d950031bb+223d636bf8d2+bfad2778a372+5822b6646448+a06f04a0059f+c62c2b06bcfb",
                    {**values, "labelled_dropped": len(drops)},
                    {"bounds": VERSION, "red_share_min": RED_SHARE,
                     "geometry": {sid: g.read for sid, g in geos.items()}},
                    "baked-slab map gates on the void rows and on every labelled enemy, X and '?' mark")
    return 0


# ------------------------------------------------------------------ (c) the held-out check
#
# Both fixes were tuned on the labels they were scored on, and FB3's abstain
# clause was added after it failed. `--check-queue` samples five match
# sessions that no minimap, facing, enemy-lane or stage-2 label file names
# (`held_out_audit` proves it), freezes both fixes' calls on every red
# opportunity, and draws a stratified queue; `label_enemy_fix_check.py` asks
# the player; `--score-check` scores the answers against CK1-CK6 (task
# `enemy-fix-check-20260930`, logged before the queue existed).

CHECK_TASK = "enemy-fix-check-20260930"
CHECK_SET = "enemy_fix_check_20260930"
CHECK_SESSIONS = ("587c15b07779", "a1a995e6b19b",                  # 465 px: Lotus, Sunset
                  "96aa1ae9b96f", "b3b9defb6fd7", "75a55a296d3b")  # 331 px: Haven, Summit, Abyss
CHECK_FRAMES = 36            # drawn cache frames per session
CHECK_SEED = 20260930        # the frame sample; the queue draws with CHECK_SEED + 1
CHECK_UNIFORM = 6
CHECK_STRATA = (("gate_drop", 15), ("edge_keep", 12), ("boxed", 15), ("refused", 12))
VOIDISH = ("void", "nothing")
# Label files whose (session, t_ms) the check must not reuse: the 331 px queue,
# the facing sets, and every file the 465 px stage-2 scorer reads.
USED_LABELS = ("enemy_lane_331_20260930.jsonl", "enemy_facing_331_20260929.jsonl",
               "ally_facing_331_20260929.jsonl", "self_facing_331_20260929.jsonl",
               "self_facing_lotus_20260928.jsonl", "icon_facing_20260928.jsonl",
               "minimap/*.jsonl", "minimap_dynamic/*.jsonl", "minimap_agent/*.jsonl", "enemies/*.jsonl")


def check_dir() -> Path:
    return STORE / "labels" / CHECK_SET


def held_out_audit() -> dict:
    """Every (session, t_ms) the earlier label files hold, and whether a check session is among them."""
    used, files = set(), {}
    for pat in USED_LABELS:
        for p in sorted((STORE / "labels").glob(pat)):
            n = 0
            for line in p.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                r = json.loads(line)
                sid = r.get("session") or r.get("session_id") or (str(r.get("key", "")).split("|")[0] or p.stem)
                t = r.get("t_ms")
                used.add((sid, None if t is None else round(float(t))))
                n += 1
            files[str(p.relative_to(STORE))] = n
    sessions = sorted({s for s, _t in used})
    clash = sorted(set(CHECK_SESSIONS) & set(sessions))
    return {"files": files, "rows": sum(files.values()), "pairs": len(used), "sessions_used": sessions,
            "check_sessions_in_used": clash, "_pairs": used}


def match_sessions_ok() -> dict:
    """Each check session's duration (a match lasts over 15 minutes) and baked map."""
    out = {}
    for sid in CHECK_SESSIONS:
        m = json.loads((STORE / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
        out[sid] = {"duration_min": round(m["source"]["duration_ms"] / 60000, 1),
                    "map": next((t[4:] for t in m.get("tags", []) if t.startswith("map:")), None),
                    "profile": m["source_profile"]}
        if out[sid]["duration_min"] <= 15:
            raise SystemExit(f"{sid} is not a match ({out[sid]['duration_min']} min)")
    return out


def edge_distance(g: Geo) -> np.ndarray:
    """Each pixel's distance to the nearest off-slab pixel (0 off the slab), from the baked slab."""
    if not hasattr(g, "_edge"):
        g._edge = cv2.distanceTransform(g.slab.astype(np.uint8), cv2.DIST_L2, 5)
    return g._edge


def check_calls(g: Geo, crop, x: float, y: float, sc: float) -> dict:
    """Both fixes' calls on one opportunity, as the prototype makes them."""
    gt = gates(g, crop, x, y, sc)
    fx, fy, fr, f = box_fixed(crop, x, y, sc)
    xi, yi = int(round(x)), int(round(y))
    h, w = g.slab.shape
    d_edge = float(edge_distance(g)[yi, xi]) if (0 <= xi < w and 0 <= yi < h) else 0.0
    # The gate read at the fitted centre too, in case the wiring gates after the fit (reported, not predicted).
    gt_fit = gates(g, crop, fx, fy, sc) if f["ok"] else gt
    return {"gate": {"red_share": gt["red_share"], "keep": gt["red_keep"], "abstain": gt["red_share"] is None,
                     "centre": gt["centre"]},
            "gate_at_fit": {"red_share": gt_fit["red_share"], "keep": gt_fit["red_keep"]},
            "fit": {"ok": f["ok"], "reason": f.get("reason")},
            "box": {"x": round(fx, 2), "y": round(fy, 2), "r": round(fr, 2), "fitted": f["ok"]},
            "edge_px": round(d_edge, 2), "near_edge": d_edge <= s2.ICON_PX * sc}


def stratum_of(c: dict) -> str | None:
    """The first stratum an opportunity qualifies for, in CHECK_STRATA's order."""
    if not c["gate"]["keep"]:
        return "gate_drop"
    if c["near_edge"] and not c["gate"]["abstain"]:
        return "edge_keep"
    return "boxed" if c["fit"]["ok"] else "refused"


def run_check_queue() -> int:
    base = check_dir()
    if (base / "calls.json").exists():
        raise SystemExit(f"{base / 'calls.json'} exists; the calls are frozen.")
    audit = held_out_audit()
    if audit["check_sessions_in_used"]:
        raise SystemExit(f"not held out: {audit['check_sessions_in_used']}")
    matches = match_sessions_ok()
    print("held out:", len(audit["files"]), "label files,", audit["pairs"], "(session, t_ms) pairs over",
          len(audit["sessions_used"]), "sessions; none is a check session", flush=True)
    rng = random.Random(CHECK_SEED)
    geos, sample, calls, geo_read = {}, [], {}, {}
    for sid in CHECK_SESSIONS:
        g = geos.setdefault(sid, Geo(sid))
        geo_read[sid] = g.read
        s = g.s
        sgray = cv2.cvtColor(s.inputs.static, cv2.COLOR_BGR2GRAY).astype(np.float64)
        T = list(s.cache_t)
        cand = sorted(rng.sample(T, min(len(T), CHECK_FRAMES * 3)))
        drawn = [float(t) for t, crop in s.crops(cand) if widget_drawn(crop, sgray, s.floor)]
        pick = sorted(rng.sample(drawn, min(len(drawn), CHECK_FRAMES)))
        n0 = len(sample)
        for t, crop in s.crops(pick):
            if (sid, round(float(t))) in audit["_pairs"]:
                raise SystemExit(f"{sid} {t} is in an earlier label file")
            sc = widget_scale(crop.shape[1])
            opps = [{"x": round(float(bx), 1), "y": round(float(by), 1), "source": "red_blob"}
                    for _a, bx, by in extract_minimap_death_marks(crop, s.floor)[1]]
            for d in it_.detections(crop, "enemy", s):
                if all(math.hypot(d["cx"] - o["x"], d["cy"] - o["y"]) > els.SAME_PX * sc for o in opps):
                    opps.append({"x": round(float(d["cx"]), 1), "y": round(float(d["cy"]), 1), "source": "ring_fit"})
            for o in opps:
                key = f"{sid}|{float(t):.1f}|{o['x']:.1f},{o['y']:.1f}"
                sample.append({"key": key, "session": sid, "t_ms": float(t), "x": o["x"], "y": o["y"],
                               "source": o["source"], "width": int(crop.shape[1]), "map": matches[sid]["map"]})
                c = check_calls(g, crop, o["x"], o["y"], sc)
                c["stratum_pool"] = stratum_of(c)
                calls[key] = c
        print(sid, matches[sid]["map"], "frames", len(pick), "opportunities", len(sample) - n0, flush=True)
    base.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    (base / "index.json").write_text(els._j({
        "set": CHECK_SET, "task": CHECK_TASK, "prototype": VERSION, "seed": CHECK_SEED,
        "frames_per_session": CHECK_FRAMES, "sessions": matches, "geometry": geo_read, "written": now,
        "held_out": {k: v for k, v in audit.items() if k != "_pairs"}, "items": sample}), encoding="utf-8")
    (base / "calls.json").write_text(els._j({
        "prototype": VERSION, "frozen": now, "ring": RING, "tip_pad": TIP_PAD, "red_share_min": RED_SHARE,
        "icon_px": s2.ICON_PX, "calls": calls}), encoding="utf-8")
    # The queue: uniform first, then each stratum round-robin over sessions; shortfall topped up uniformly.
    rng2 = random.Random(CHECK_SEED + 1)
    keys = [it["key"] for it in sample]
    queue, taken = [], set()
    for k in rng2.sample(keys, min(CHECK_UNIFORM, len(keys))):
        queue.append({"key": k, "stratum": "uniform"})
        taken.add(k)
    short = 0
    for name, n in CHECK_STRATA:
        per = defaultdict(list)
        for k in rng2.sample(keys, len(keys)):
            if calls[k]["stratum_pool"] == name and k not in taken:
                per[k.split("|")[0]].append(k)
        got = []
        while len(got) < n and any(per.values()):
            for sid in CHECK_SESSIONS:
                if per[sid] and len(got) < n:
                    got.append(per[sid].pop())
        short += n - len(got)
        for k in got:
            queue.append({"key": k, "stratum": name})
            taken.add(k)
    rest = [k for k in keys if k not in taken]
    for k in rng2.sample(rest, min(short, len(rest))):
        queue.append({"key": k, "stratum": "uniform_fill"})
    rng2.shuffle(queue)
    (base / "queue.json").write_text(els._j({"seed": CHECK_SEED + 1, "uniform": CHECK_UNIFORM,
                                             "strata": dict(CHECK_STRATA), "items": queue}), encoding="utf-8")
    print("pools", Counter(c["stratum_pool"] for c in calls.values()),
          "queue", Counter(q["stratum"] for q in queue), flush=True)
    return 0


def _answers(p: Path) -> dict:
    ans = {}
    for line in (p.read_text(encoding="utf-8").splitlines() if p.exists() else []):
        if line.strip():
            r = json.loads(line)
            ans[r["key"]] = r                       # the last row for a key wins
    return ans


def _frac_check(num: int, den: int, op: str, thr: float) -> dict:
    if den == 0:
        return {"n": 0, "of": 0, "verdict": "no_data"}
    f = num / den
    ok = f >= thr if op == ">=" else f <= thr if op == "<=" else f < thr
    return {"n": num, "of": den, "frac": round(f, 3), "verdict": "held" if ok else "failed"}


def run_score_check(labels: str | None, record: bool) -> int:
    """The frozen calls against the player's answers: CK1-CK6."""
    base = check_dir()
    calls = json.loads((base / "calls.json").read_text(encoding="utf-8"))["calls"]
    queue = json.loads((base / "queue.json").read_text(encoding="utf-8"))["items"]
    path = Path(labels) if labels else STORE / "labels" / f"{CHECK_SET}.jsonl"
    ans = _answers(path)
    rows = []
    for q in queue:
        a = ans.get(q["key"])
        if a is not None:
            rows.append({**q, "a": a, "c": calls[q["key"]]})
    sure = [r for r in rows if not r["a"].get("uncertain")]
    values = {"queue": len(queue), "answered": len(rows), "unsure": len(rows) - len(sure)}
    for r in sure:
        k = f"{r['stratum']}_{r['a']['answer']}"
        values[k] = values.get(k, 0) + 1
    marks = ("enemy_icon", "x_mark", "question")
    dropped = [r for r in sure if not r["c"]["gate"]["keep"]]
    ck = {}
    bad = [r["key"] for r in dropped if r["a"]["answer"] in marks]
    ck["CK1"] = {"n": len(bad), "of": len(dropped), "keys": bad,
                 "verdict": "no_data" if not dropped else "held" if not bad else "failed"}
    st = lambda name: [r for r in sure if r["stratum"] == name]  # noqa: E731
    gd, ek, rf = st("gate_drop"), st("edge_keep"), st("refused")
    ck["CK2"] = _frac_check(sum(r["a"]["answer"] in VOIDISH for r in gd), len(gd), ">=", 0.75)
    ck["CK3"] = _frac_check(sum(r["a"]["answer"] in VOIDISH for r in ek), len(ek), "<=", 0.30)
    boxed = [r for r in sure if r["c"]["fit"]["ok"] and r["a"]["answer"] == "enemy_icon"
             and r["a"].get("box") in ("holds", "cuts")]
    ck["CK4"] = _frac_check(sum(r["a"]["box"] == "holds" for r in boxed), len(boxed), ">=", 0.85)
    ck["CK5"] = _frac_check(sum(r["a"]["answer"] == "enemy_icon" for r in rf), len(rf), "<", 0.5)
    unfit = [r for r in sure if not r["c"]["fit"]["ok"] and r["a"]["answer"] == "enemy_icon"
             and r["a"].get("box") in ("holds", "cuts")]
    ck["CK6"] = _frac_check(sum(r["a"]["box"] == "cuts" for r in unfit), len(unfit), ">=", 0.5)
    # Reported, not predicted: the gate read at the fitted centre, and the box by stratum and scale.
    values["gate_at_fit_drops_marks"] = sum(1 for r in sure if not r["c"]["gate_at_fit"]["keep"]
                                            and r["a"]["answer"] in marks)
    values["gate_drops_answered"] = len(dropped)
    for w in (331, 465):
        sub = [r for r in boxed if _width(r["key"]) == w]
        values[f"box_holds_{w}"] = sum(r["a"]["box"] == "holds" for r in sub)
        values[f"box_answers_{w}"] = len(sub)
    for r in sure:
        if not r["c"]["fit"]["ok"]:
            k = f"refused_{r['c']['fit']['reason']}_{r['a']['answer']}"
            values[k] = values.get(k, 0) + 1
    print(els._j(values), flush=True)
    print(els._j(ck), flush=True)
    if record:
        flat = {**values, **{f"{k}_{f}": v[f] for k, v in ck.items() for f in ("n", "of") if f in v}}
        els._record("fix-check", "+".join(CHECK_SESSIONS), flat,
                    {"bounds": VERSION, "calls": str(base / "calls.json"), "labels": str(path)},
                    "held-out check of the teardrop box and the baked-slab gate against the player's answers",
                    context={k: v["verdict"] for k, v in ck.items()})
    return 0


_WIDTHS: dict = {}


def _width(key: str) -> int | None:
    if not _WIDTHS:
        for it in json.loads((check_dir() / "index.json").read_text(encoding="utf-8"))["items"]:
            _WIDTHS[it["key"]] = it["width"]
    return _WIDTHS.get(key)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bounds", action="store_true")
    ap.add_argument("--gate", action="store_true")
    ap.add_argument("--check-queue", action="store_true")
    ap.add_argument("--score-check", action="store_true")
    ap.add_argument("--labels", help="--score-check: an answers file other than the store's (a test run)")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    els.below_normal()
    if args.check_queue:
        return run_check_queue()
    if args.score_check:
        return run_score_check(args.labels, args.record)
    if args.bounds:
        return run_bounds(args.record)
    if args.gate:
        return run_gate(args.record)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
