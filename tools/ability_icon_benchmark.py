r"""The dark-icon proposer scored on the player's icon labels and the null crops.

    .\.venv\Scripts\python.exe tools\ability_icon_benchmark.py [--out DIR] [--record]

The acceptance of stage 3 of `docs/ABILITY_DETECTION.md`. It runs
`reticle.ability_icons.propose_icons` (the reader's own code, radius step 1) on
crops of the minimap crop cache, decoding nothing:

- targets: the tray-object icon marks (`labels/tray_object`, class `object`,
  not the outline abilities Recon Bolt, Regrowth and Hunter's Fury, nor
  Blaze), the painted frames' icons (`labels/ability_paint`, not `self`), and
  the round viewer's ability marks (`labels/round_review`, `wrong_here` on
  the `ability` layer, not retracted). A target is hit when a candidate lies
  within max(6 px, its radius) of the mark, on the cached crop nearest the
  mark's time (within 70 ms);
- null crops: the frozen list in the store's
  `analysis/ability-icon-benchmark/null_crops.json` (130 live crops of Sova
  and Skye sessions away from the player's shape casts); the count is
  candidates per crop.

Cost: the full search's milliseconds per crop by widget width, and the
verify of each null crop's own candidates. The standard: at least 123 of
151 hits, at most 6 candidates per null crop, and the full search at most
20% dearer than section 5 ([metric:ability_detection/icon-verify@223d636bf8d2#full_ms=47.3]
ms at 331 px, [metric:ability_detection/icon-verify@a06f04a0059f#full_ms=128.2]
ms at 465 px). Single-threaded, Below Normal priority. `--record` writes
the numbers to the store's metrics as `ability_icons/bench@player-labels`.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import ability_icons as I  # noqa: E402
from reticle import geometry, minimap  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402
from reticle.version import ABILITY_ICON_VERSION  # noqa: E402

#: Abilities whose tray-object marks outline a drawing rather than an icon.
OUTLINE = {"Recon Bolt", "Regrowth", "Hunter's Fury", "Blaze"}
#: A mark's crop is the cached one nearest its time, within this.
NEAR_MS = 70.0
#: The round viewer's inset (`round_view.render`): the widget at INSET_K, its
#: top-left at (W - INSET_K w - 16, H - INSET_K h - 150).
INSET_K = 2
#: Section 5's full-search cost per crop, by widget width, and its tolerance:
#: the search may cost at most this much more (a cheaper one keeps section
#: 6's estimate an upper bound).
REF_FULL_MS = {331: 47.3, 465: 128.2}
COST_TOL = 0.2


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def _inset_point(x, y, rect, frame_wh=(1920, 1080)):
    w, h = rect[2] - rect[0], rect[3] - rect[1]
    ix, iy = frame_wh[0] - INSET_K * w - 16, frame_wh[1] - INSET_K * h - 150
    return (x - ix) / INSET_K, (y - iy) / INSET_K


class _Session:
    """A session's minimap crop cache and its proposer terms on the baked slab."""

    def __init__(self, store, sid):
        man = store.read_manifest(sid)
        self.cache, _ = RoiCache.load(store.root, man, get_profile(man["source_profile"]),
                                      "minimap")
        self.rect = self.cache.rect_of("minimap")
        self.ts = np.asarray(self.cache.t_ms, float)
        self.slab = minimap.slab_mask(geometry.reference_static(sid, store.root))
        self.terms = None

    def crop(self, t):
        k = int(np.argmin(np.abs(self.ts - t)))
        if abs(self.ts[k] - t) > NEAR_MS:
            return None, None
        x0, y0, x1, y1 = self.rect
        s = next(iter(self.cache.samples([float(self.ts[k])], rois=["minimap"])), None)
        if s is None:
            return None, None
        img = s.frame[y0:y1, x0:x1]
        if img.shape[:2] != self.slab.shape[:2]:
            return None, None
        if self.terms is None:
            self.terms = I.IconTerms(self.slab, img.shape[1] / 2.0)
        return img, float(s.t_ms)


def _lines(p: Path):
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]


def targets(store):
    """(sid, t_ms, [(x, y)], source, ability) per labelled time."""
    lab = store.root / "labels"
    for f in sorted((lab / "tray_object").glob("*.jsonl")):
        for r in _lines(f):
            if r.get("class") != "object" or r["ability"] in OUTLINE:
                continue
            by = defaultdict(list)
            for m in r["marks"]:
                by[float(m["t_ms"])].append((float(m["x"]), float(m["y"])))
            for t, pts in sorted(by.items()):
                yield f.stem, t, pts, "tray_object", r["ability"]
    for f in sorted((lab / "ability_paint").glob("*.jsonl")):
        for r in _lines(f):
            for i in r.get("icons", []):
                if i.get("ability") != "self":
                    yield (f.stem, float(r["t_ms"]), [(float(i["x"]), float(i["y"]))], "paint",
                           i["ability"])
    for f in sorted((lab / "round_review").glob("*.jsonl")):
        marks = _lines(f)
        gone = {m["mark_id"] for m in marks if m["kind"] == "retract"}
        for m in marks:
            if m["kind"] == "wrong_here" and m.get("layer") == "ability" and m["mark_id"] not in gone:
                yield f.stem, float(m["t_ms"]), ("inset", m["point"]["x"], m["point"]["y"]), \
                    "round_review", "unnamed"


def run(store) -> dict:
    sessions: dict = {}

    def sess(sid):
        if sid not in sessions:
            sessions[sid] = _Session(store, sid)
        return sessions[sid]

    full_ms = defaultdict(list)
    rows = []
    for sid, t, pts, source, ability in targets(store):
        S = sess(sid)
        if isinstance(pts, tuple):
            pts = [_inset_point(pts[1], pts[2], S.rect)]
        img, tt = S.crop(t)
        if img is None:
            rows.append({"sid": sid, "source": source, "ability": ability, "t_ms": t,
                         "hit": None, "reason": "no_cached_crop"})
            continue
        t0 = time.perf_counter()
        cands = I.propose_icons(img, S.terms)
        full_ms[img.shape[1]].append(1000 * (time.perf_counter() - t0))
        for p in pts:
            d = sorted(((float(np.hypot(c["cx"] - p[0], c["cy"] - p[1])), c) for c in cands),
                       key=lambda z: z[0])
            hit = bool(d) and d[0][0] <= max(6.0, d[0][1]["r"])
            rows.append({"sid": sid, "source": source, "ability": ability, "t_ms": tt,
                         "hit": hit, "near_px": d[0][0] if d else None, "cands": len(cands),
                         "glyph_white": d[0][1]["glyph_white"] if hit else None})
    null_doc = json.loads((store.root / "analysis" / "ability-icon-benchmark" / "null_crops.json")
                          .read_text(encoding="utf-8"))
    null, verify_ms = [], defaultdict(list)
    for r in null_doc["crops"]:
        S = sess(r["sid"])
        img, tt = S.crop(float(r["t_ms"]))
        if img is None:
            null.append({"sid": r["sid"], "t_ms": r["t_ms"], "cands": None})
            continue
        t0 = time.perf_counter()
        cands = I.propose_icons(img, S.terms)
        full_ms[img.shape[1]].append(1000 * (time.perf_counter() - t0))
        t0 = time.perf_counter()
        I.verify_icons(img, S.terms, cands)
        verify_ms[img.shape[1]].append(1000 * (time.perf_counter() - t0))
        null.append({"sid": r["sid"], "t_ms": tt, "cands": len(cands)})
    return {"targets": rows, "null": null, "full_ms": full_ms, "verify_ms": verify_ms}


def summary(res) -> dict:
    t = [r for r in res["targets"] if r["hit"] is not None]
    by = defaultdict(lambda: [0, 0])
    for r in t:
        by[r["source"]][0] += r["hit"]
        by[r["source"]][1] += 1
    nc = [r["cands"] for r in res["null"] if r["cands"] is not None]
    out = {"targets": len(t), "unread_targets": len(res["targets"]) - len(t),
           "hits": sum(r["hit"] for r in t),
           "by_source": {k: {"hit": v[0], "n": v[1]} for k, v in sorted(by.items())},
           "hit_white_glyph": sum(1 for r in t if r["hit"] and r["glyph_white"] > 0),
           "null_crops": len(nc), "null_cands_mean": round(float(np.mean(nc)), 2) if nc else None,
           "null_cands_median": float(np.median(nc)) if nc else None,
           "full_ms": {}, "verify_ms_per_crop": {}}
    for w, v in sorted(res["full_ms"].items()):
        med = float(np.median(v))
        ref = REF_FULL_MS.get(int(w))
        out["full_ms"][str(w)] = {"median": round(med, 1), "mean": round(float(np.mean(v)), 1),
                                  "n": len(v), "ref": ref,
                                  "within": None if ref is None else med <= (1 + COST_TOL) * ref}
    for w, v in sorted(res["verify_ms"].items()):
        out["verify_ms_per_crop"][str(w)] = round(float(np.median(v)), 2)
    cost_ok = all(v["within"] is not False for v in out["full_ms"].values())
    out["holds"] = bool(out["hits"] >= 123 and out["null_cands_mean"] is not None
                        and out["null_cands_mean"] <= 6 and cost_ok)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--out", type=Path, default=None, help="write the per-target rows here")
    ap.add_argument("--record", action="store_true", help="record the numbers in the metrics")
    ap.add_argument("--store", default=None)
    a = ap.parse_args(argv)
    below_normal()
    cv2.setNumThreads(1)
    store = Store(a.store) if a.store else Store()
    res = run(store)
    s = summary(res)
    print(json.dumps(s, indent=1))
    if a.out is not None:
        a.out.mkdir(parents=True, exist_ok=True)
        (a.out / "rows.json").write_text(json.dumps({k: res[k] for k in ("targets", "null")},
                                                    default=str), encoding="utf-8")
    if a.record:
        from reticle import metrics
        vals = {"targets": s["targets"], "hits": s["hits"],
                "hit_white_glyph": s["hit_white_glyph"], "null_crops": s["null_crops"],
                "null_cands_mean": s["null_cands_mean"],
                **{f"{k}_hit": v["hit"] for k, v in s["by_source"].items()},
                **{f"{k}_n": v["n"] for k, v in s["by_source"].items()},
                **{f"full_ms_{w}": v["median"] for w, v in s["full_ms"].items()},
                **{f"verify_ms_{w}": v for w, v in s["verify_ms_per_crop"].items()}}
        metrics.record("ability_icons", part="bench", session="player-labels", values=vals,
                       deps={"ability_icon_version": ABILITY_ICON_VERSION,
                             "radius_step": I.RADIUS_STEP},
                       context={"threads": 1, "priority": "below normal",
                                "tool": "tools/ability_icon_benchmark.py"},
                       note="stage 3 acceptance of docs/ABILITY_DETECTION.md")
    print("HOLDS" if s["holds"] else "FAILS")
    return 0 if s["holds"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
