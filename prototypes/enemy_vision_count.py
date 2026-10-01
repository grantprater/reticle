"""Where enemy marks sit against the team's drawn light, on one session.

    .\\.venv\\Scripts\\python.exe prototypes\\enemy_vision_count.py [--session a06f04a0059f] [--record]

The first measurement of `docs/ENEMY_VISION_COUPLING.md` (section 5). Read
only: the minimap crop cache, the baked geometry's lighting reference
(`lighting.lit_mask`, the drawn light [domain:minimap/vision-gate]), the
player's enemy and "?" marks in `labels/minimap/<session>.jsonl`, and the
`enemy_track` stream's first observations. It decodes no capture, reads no
cone and writes nothing but the metric row (`--record`).

Each point is classed by the drawn light in an annulus of R_IN to R_OUT px
round it, over floor the lighting reference can read, with saturated pixels
(icons, teardrop tips, marks) dilated and excluded: the enemy lobe is
translucent [domain:minimap/enemy-lobe-translucent] and its rim is not floor.

    unknown   under KNOWN_MIN of the annulus readable
    inside    lit share >= INSIDE
    edge      lit share > EDGE
    near      lit share <= EDGE, but a lit pixel within NEAR px
    dark      no lit pixel within NEAR px

"Newly lit" is a lit share at least NEWLY above the frame PRIOR_MS earlier.
Track first observations are detector output, so they measure consistency,
not accuracy.
"""
from __future__ import annotations

import argparse
import ctypes
import json
import math
import os
import sys
from collections import Counter
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import lighting, metrics  # noqa: E402
from reticle.enemy_tracks import ENEMY_TRACK_VERSION  # noqa: E402
from reticle.minimap import widget_drawn  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import ROI_CACHE_VERSION, RoiCache  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402
from reticle.team_vision import load_inputs  # noqa: E402

VERSION = "enemy-vision-count-0.1.0"
R_IN, R_OUT, NEAR = 10.0, 22.0, 30.0
SAT_MIN, VAL_MIN, SAT_DILATE = 90, 60, 5
KNOWN_MIN, INSIDE, EDGE, NEWLY = 0.4, 0.85, 0.1, 0.3
PRIOR_MS = 500.0
SAME_MS, SAME_PX = 2000.0, 25.0     # two marks are one instance within both
CLASSES = ("inside", "edge", "near", "dark", "unknown")


def _below_normal() -> None:
    try:
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.SetPriorityClass.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)  # BELOW_NORMAL_PRIORITY_CLASS
    except Exception:
        pass


class Light:
    """The drawn light and the overlay pixels of cached frames, memoised."""

    def __init__(self, store, sid):
        man = next(s for s in store.sessions() if s["session_id"] == sid)
        profile = get_profile(man["source_profile"])
        w, h = int(man["source"]["width"]), int(man["source"]["height"])
        self.cache, why = RoiCache.load(store.root, man, profile, "minimap")
        if self.cache is None:
            raise SystemExit(f"{sid}: no minimap crop cache ({why})")
        self.inputs, why = load_inputs(store.root, sid, profile, w, h)
        if self.inputs is None or self.inputs.light is None:
            raise SystemExit(f"{sid}: no lighting reference ({why})")
        self.ref = self.inputs.light
        self.T = np.asarray(sorted({float(t) for t in self.cache.t_ms}))
        H, W = self.ref.known.shape
        self.yy, self.xx = np.mgrid[0:H, 0:W]
        self._got = {}

    def nearest(self, t):
        i = int(np.searchsorted(self.T, t))
        j = min((j for j in (i - 1, i) if 0 <= j < self.T.size), key=lambda j: abs(self.T[j] - t))
        return float(self.T[j])

    def at(self, t):
        if t not in self._got:
            x0, y0, x1, y1 = self.inputs.box
            smp = next(self.cache.samples([t], rois=["minimap"]), None)
            got = None
            if smp is not None:
                crop = smp.frame[y0:y1, x0:x1]
                if widget_drawn(crop, self.inputs.sgray, self.inputs.floor):
                    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
                    ov = ((hsv[..., 1] > SAT_MIN) & (hsv[..., 2] > VAL_MIN)).astype(np.uint8)
                    ov = cv2.dilate(ov, np.ones((SAT_DILATE, SAT_DILATE), np.uint8)) > 0
                    got = (lighting.lit_mask(crop, self.ref), ov)
            self._got[t] = got
        return self._got[t]

    def classify(self, t, x, y) -> dict:
        got = self.at(t)
        if got is None:
            return {"cls": "no_frame"}
        lit, ov = got
        d = np.hypot(self.xx - x, self.yy - y)
        ann = (d >= R_IN) & (d <= R_OUT)
        known = ann & self.ref.known & ~ov
        ks = float(known.sum() / max(ann.sum(), 1))
        if ks < KNOWN_MIN:
            return {"cls": "unknown", "known_share": round(ks, 3)}
        ls = float((lit & known).sum() / known.sum())
        near = bool((lit & (d <= NEAR) & (d >= R_IN)).any())
        cls = ("inside" if ls >= INSIDE else "edge" if ls > EDGE else "near" if near else "dark")
        return {"cls": cls, "lit_share": round(ls, 3), "known_share": round(ks, 3)}

    def point(self, t_ms, x, y) -> dict:
        t = self.nearest(float(t_ms))
        now = self.classify(t, float(x), float(y))
        prev = self.classify(self.nearest(t - PRIOR_MS), float(x), float(y))
        newly = (now.get("lit_share") is not None and prev.get("lit_share") is not None
                 and now["lit_share"] - prev["lit_share"] >= NEWLY)
        return {**now, "frame_t": t, "newly_lit": newly}


def label_marks(store, sid, box):
    last = {}
    for line in (store.root / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            last[r["t_ms"]] = r
    for r in sorted(last.values(), key=lambda r: r["t_ms"]):
        if r.get("uncertain") or list(r.get("roi") or []) != list(box):
            continue
        for m in r.get("marks", []):
            if m["kind"] in ("enemy", "question"):
                yield {"kind": m["kind"], "t_ms": float(r["t_ms"]), "x": m["x"], "y": m["y"],
                       "pool": r.get("pool")}


def instances(rows):
    groups = []
    for r in sorted(rows, key=lambda r: r["t_ms"]):
        for g in groups:
            q = g[-1]
            if r["t_ms"] - q["t_ms"] <= SAME_MS and math.hypot(r["x"] - q["x"], r["y"] - q["y"]) <= SAME_PX:
                g.append(r)
                break
        else:
            groups.append([r])
    return groups


def counts(prefix, rows, dedupe=False) -> dict:
    c = Counter(r["cls"] for r in rows)
    out = {f"{prefix}_n": len(rows)}
    out.update({f"{prefix}_{k}": c.get(k, 0) for k in CLASSES})
    out[f"{prefix}_readable"] = sum(c.get(k, 0) for k in CLASSES if k != "unknown")
    out[f"{prefix}_no_frame"] = c.get("no_frame", 0)
    if dedupe:
        g = instances(rows)
        gc = Counter(x[0]["cls"] for x in g)
        out[f"{prefix}_instances"] = len(g)
        out.update({f"{prefix}_instances_{k}": gc.get(k, 0) for k in CLASSES})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--session", default="a06f04a0059f")
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    _below_normal()
    store = Store(DEFAULT_STORE)
    sid = args.session
    light = Light(store, sid)

    marks = [{**m, **light.point(m["t_ms"], m["x"], m["y"])}
             for m in label_marks(store, sid, light.inputs.box)]
    firsts = []
    for line in store.events_path("enemy_track", sid).read_text(encoding="utf-8").splitlines():
        if '"first_observed"' in line:
            o = json.loads(line)
            if o.get("kind") == "observation" and o.get("state") == "first_observed":
                firsts.append({"t_ms": float(o["t_ms"]), "x": o["x"], "y": o["y"],
                               **light.point(o["t_ms"], o["x"], o["y"])})

    enemy = [m for m in marks if m["kind"] == "enemy"]
    quest = [m for m in marks if m["kind"] == "question"]
    values = {**counts("label_enemy", enemy, dedupe=True),
              **counts("label_question", quest, dedupe=True),
              **counts("track_first", firsts)}
    values["label_enemy_prekill"] = sum(m["pool"] == "prekill" for m in enemy)
    values["label_enemy_uniform"] = sum(m["pool"] == "uniform" for m in enemy)
    values["track_first_newly_lit"] = sum(f["newly_lit"] for f in firsts)
    values["track_first_edge_or_newly"] = sum(
        f["cls"] != "unknown" and f["cls"] != "no_frame" and (f["cls"] == "edge" or f["newly_lit"])
        for f in firsts)
    print(json.dumps(values, indent=1))
    if args.record:
        row = metrics.record(
            "enemy_vision_coupling", part="first-count", session=sid, values=values,
            deps={"tool": "prototypes/enemy_vision_count.py", "version": VERSION,
                  "lighting_version": lighting.LIGHTING_VERSION,
                  "geometry_key": light.inputs.geometry_key,
                  "roi_cache_version": ROI_CACHE_VERSION,
                  "enemy_track_version": ENEMY_TRACK_VERSION,
                  "labels": f"labels/minimap/{sid}.jsonl"},
            context={"annulus_px": [R_IN, R_OUT], "near_px": NEAR, "inside_min": INSIDE,
                     "edge_min": EDGE, "known_min": KNOWN_MIN, "newly_min": NEWLY,
                     "prior_ms": PRIOR_MS, "saturated": [SAT_MIN, VAL_MIN, SAT_DILATE],
                     "instance": [SAME_MS, SAME_PX],
                     "track_first": "detector output; consistency, not accuracy",
                     "team_vision": "not read (stale on this session)"},
            note="docs/ENEMY_VISION_COUPLING.md section 5")
        print("recorded", row["tool"], row["part"], row["session"], row["at"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
