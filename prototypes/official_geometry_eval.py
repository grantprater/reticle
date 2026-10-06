r"""Official geometry against the capture geometry it replaces, field by field, and recorded.

    .\.venv\Scripts\python.exe prototypes\official_geometry_eval.py [--record] [--images DIR]
    .\.venv\Scripts\python.exe prototypes\official_geometry_eval.py --riot BASE.json OFFICIAL.json [--record]
    .\.venv\Scripts\python.exe prototypes\official_geometry_eval.py --world BASE.json OFFICIAL0.json [--record]

What it measures
----------------
`reticle/map_asset.py` draws every `(map, profile)` key from the game's
textures; `<store>/geometry/` holds the capture-median geometry each key was
built from before 2026-10-05, read only. For every key with both, and for the
textures themselves:

* `assets`: the valorant-api display icon and the wiki art against the fog
  and revealed textures, grey MAD over opaque texels. The art is the fog
  texture when the first is under a level or two and the second near 60;
* `placement`: a free similarity fit of the fog texture on each capture
  static (`minimap_geometry.free_place`) against its profile's fitted
  transform, in widget px and per cent of scale. The four training keys sit in
  the mean by construction; the seven others test it;
* `photometry`: on flat opaque floor, the capture static minus the drawn fog
  texture, per key; a map layer that hides the world gives a constant;
* `fields`: per key, the sub-pixel shift between the two statics (phase
  correlation over the map), static MAE on the map and in the void, `lo_gray`
  on flat floor, `hi_gray` where the two resting states differ by 25 levels
  or more, `minimap.floor_mask` IoU, the label classes' IoU and the line
  classes' share within one pixel, the art footprint's IoU and shade
  agreement.

`--riot` pairs two `prototypes/riot_ground_truth.py --json` outputs, one run
on capture geometry and one on official, by victim row (session, time,
agent), and reports the paired change in position error per profile with a
session bootstrap. Riot positions reach widget px through `shade_fit`, so this
measures where the geometry puts the WORLD, which the static fields cannot.

`--world` scores each map's world offset (`map_asset.world_offset`) held out:
OFFICIAL0 is a Riot run on official geometry with no offset; each match takes
the offset fitted on its map's other matches and is paired with BASE.

Reads stored arrays only; decodes nothing.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import geometry as G                                 # noqa: E402
from reticle import map_asset as A                                # noqa: E402
from reticle import metrics                                       # noqa: E402
from reticle.minimap import (BORDER, BOXEDGE, FLOOR, HOLE, PLANT,  # noqa: E402
                             VOID, art_floor, floor_mask)

STORE = Path.home() / "reticle-store"
TOOL = "official_geometry"
EVAL_VERSION = "official-geometry-eval-0.2.0"


def _iou(x, y) -> float:
    return float((x & y).sum() / max((x | y).sum(), 1))


def assets() -> dict:
    """Grey MAD of the api icon and the wiki art against both textures."""
    rows = {}
    for m in sorted(A.maps(STORE)):
        try:
            tx = A.textures(m, STORE)
        except SystemExit:
            continue
        fog, rev = (A.read_bgra(tx[k], STORE) for k in ("fog", "rev"))
        for src, p in (("api", STORE / "external" / "valorant-api" / f"map_{m}.png"),
                       ("wiki", STORE / "reference" / "maps" / f"{m}.png")):
            im = cv2.imread(str(p), cv2.IMREAD_UNCHANGED)
            if im is None or im.ndim != 3 or im.shape[2] != 4:
                continue
            if im.shape[:2] != fog.shape[:2]:
                im = cv2.resize(im, fog.shape[1::-1], interpolation=cv2.INTER_AREA)
            on = (im[..., 3] > 250) & (fog[..., 3] > 250)
            gi = cv2.cvtColor(im[..., :3], cv2.COLOR_BGR2GRAY).astype(np.float32)
            rows[f"{m}:{src}"] = {
                "vs_fog": round(float(np.abs(gi - cv2.cvtColor(fog[..., :3], cv2.COLOR_BGR2GRAY))[on].mean()), 2),
                "vs_revealed": round(float(np.abs(gi - cv2.cvtColor(rev[..., :3], cv2.COLOR_BGR2GRAY))[on].mean()), 2)}
    return rows


def key_fields(k: str, images: Path | None) -> dict:
    """Every field of one key, official against capture."""
    import minimap_geometry as MG
    m, prof = G.parse(k)
    b = dict(np.load(G.capture_dir(STORE) / f"{k}.npz", allow_pickle=False))
    o = A.render(m, prof, STORE)
    P = A.transform(prof)
    on_map = (o["labels"] != VOID) & (o["labels"] != HOLE)
    gb = cv2.cvtColor(b["static"], cv2.COLOR_BGR2GRAY).astype(np.float32)
    go = cv2.cvtColor(o["static"], cv2.COLOR_BGR2GRAY).astype(np.float32)
    w = cv2.createHanningWindow(gb.shape[::-1], cv2.CV_32F)
    msk = cv2.dilate(on_map.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(np.float32)
    (sx, sy), _ = cv2.phaseCorrelate(gb * msk, go * msk, w)
    d = np.abs(b["static"].astype(np.float32) - o["static"].astype(np.float32)).mean(2)
    flat = (o["labels"] == FLOOR) & (cv2.erode(on_map.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0)
    two = flat & ((b["hi_gray"] - b["lo_gray"]) >= 25)
    fog, _rev, _M, _r, _t = A.drawn_layers(m, prof, STORE, P)
    fg = cv2.cvtColor(fog[..., :3] * 255.0, cv2.COLOR_BGR2GRAY)
    core = cv2.erode((fog[..., 3] > 0.999).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    pure = core & (np.abs(cv2.Laplacian(fg, cv2.CV_32F)) < 2)
    fb, fo = floor_mask(b["static"], sd=b["sd_lo"]), floor_mask(o["static"], sd=o["sd_lo"])
    lb, lo = b["labels"], o["labels"]
    ground = lambda L: np.isin(L, (FLOOR, PLANT))                   # noqa: E731
    line = lambda L: np.isin(L, (BORDER, BOXEDGE))                  # noqa: E731
    near = cv2.dilate(line(lo).astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    sc, cx, cy = MG.free_place(b["static"], m, P)
    union = (b["shade_kind"] > 0) | (o["shade_kind"] > 0)
    both_floor = (b["shade_kind"] == 1) & (o["shade_kind"] == 1)
    r = {"train": k in A.TRAIN_KEYS,
         "centre_dev_px": round(float(np.hypot(cx - P["centre"][0], cy - P["centre"][1])), 3),
         "scale_dev_pct": round(float(100 * abs(sc / P["scale"] - 1)), 3),
         "flat_static_minus_fog": round(float(np.median(gb[pure] - fg[pure])), 2),
         "reg_px": round(float(np.hypot(sx, sy)), 3),
         "static_mae_map": round(float(d[on_map].mean()), 2),
         "static_p95_map": round(float(np.percentile(d[on_map], 95)), 1),
         "static_mae_void": round(float(d[~on_map].mean()), 1),
         "lo_mae_flat": round(float(np.abs(b["lo_gray"] - o["lo_gray"])[flat].mean()), 2),
         "hi_mae_two": round(float(np.abs(b["hi_gray"] - o["hi_gray"])[two].mean()), 2),
         "floor_mask_iou": round(_iou(fb, fo), 4),
         "labels_ground_iou": round(_iou(ground(lb), ground(lo)), 4),
         "labels_line_within1": round(float(near[line(lb)].mean()), 3) if line(lb).any() else None,
         "footprint_iou": round(_iou(art_floor(b["shade_kind"]), art_floor(o["shade_kind"])), 4),
         "shade_kind_agree": round(float((b["shade_kind"] == o["shade_kind"])[union].mean()), 4),
         "shade_step_agree": round(float((b["shade_step"] == o["shade_step"])[both_floor].mean()), 4)}
    if images:
        images.mkdir(parents=True, exist_ok=True)
        err = cv2.applyColorMap(np.clip(d * 6, 0, 255).astype(np.uint8), cv2.COLORMAP_JET)
        fm = np.zeros_like(b["static"])
        fm[fb & fo] = (200, 200, 200)
        fm[fb & ~fo] = (0, 0, 255)
        fm[fo & ~fb] = (255, 128, 0)
        cv2.imwrite(str(images / f"{k}_cmp.png"),
                    np.vstack([np.hstack([b["static"], o["static"]]), np.hstack([err, fm])]))
    return r


def riot(base: Path, official: Path, seed: int = 0) -> dict:
    """Paired change in Riot victim position error, per profile, with a session bootstrap."""
    rows = {}
    for tag, p in (("base", base), ("official", official)):
        for s in json.loads(p.read_text(encoding="utf-8"))["sessions"]:
            for v in (s.get("minimap") or {}).get("victim_rows") or []:
                if v.get("piece_px") and v.get("truth_px"):
                    rows.setdefault((s["session"], v["t_ms"], v["agent"]), {})[tag] = (
                        float(v["dist_px"]), s["profile"])
    pairs = [(r["base"][0], r["official"][0], r["base"][1], k[0]) for k, r in rows.items()
             if "base" in r and "official" in r and r["base"][0] < 8 and r["official"][0] < 8]
    rng = np.random.default_rng(seed)
    out = {}
    for prof in sorted({p[2] for p in pairs}) + ["all"]:
        P = [p for p in pairs if prof == "all" or p[2] == prof]
        a, b = np.array([p[0] for p in P]), np.array([p[1] for p in P])
        sess = np.array([p[3] for p in P])
        us = np.unique(sess)
        idx_of = {u: np.where(sess == u)[0] for u in us}
        boot = []
        for _ in range(2000):
            idx = np.concatenate([idx_of[u] for u in rng.choice(us, len(us))])
            boot.append((b[idx] - a[idx]).mean())
        lo, hi = np.percentile(boot, [2.5, 97.5])
        out[prof] = {"n": len(P), "sessions": len(us),
                     "median_base": round(float(np.median(a)), 3),
                     "median_official": round(float(np.median(b)), 3),
                     "mean_change": round(float((b - a).mean()), 3),
                     "mean_change_lo": round(float(lo), 3), "mean_change_hi": round(float(hi), 3)}
    return out


def riot_world_lomo(base: Path, official: Path, seed: int = 0) -> dict:
    """Each map's world offset scored leave-one-match-out: for every session,
    the offset is fitted on the OTHER sessions of its map
    (`minimap_geometry.fit_world`) and applied to its own victim rows. Rows are
    paired with the capture-geometry run `base`; `official` is a run on
    official geometry with no world offset. Per profile: medians, the mean
    paired change against both, with a session bootstrap."""
    import minimap_geometry as MG
    res = MG.world_residuals(official)

    def rows(p):
        out = {}
        for s_ in json.loads(Path(p).read_text(encoding="utf-8"))["sessions"]:
            for v in (s_.get("minimap") or {}).get("victim_rows") or []:
                if v.get("piece_px") and v.get("truth_px"):
                    out[(s_["session"], v["t_ms"], v["agent"])] = (
                        s_["profile"], np.subtract(v["piece_px"], v["truth_px"]))
        return out
    B, O = rows(base), rows(official)
    lomo, per_session = {}, {}
    for sid, r in res.items():
        m = r["map"]
        off = np.asarray(MG.fit_world(res, exclude={sid}).get(m, (0.0, 0.0)))
        P = A.transform(r["profile"])
        lomo[sid] = A.map_affine(A.rotation(m), P["scale"], P["centre"])[:, :2] @ off
        per_session[sid] = {"map": m, "profile": r["profile"], "offset_tex_px": off.round(3).tolist(),
                            "fitted_on_other_matches": bool(np.any(off))}
    triples = []
    for k, (prof, ro) in O.items():
        if k not in B or k[0] not in lomo:
            continue
        rb = B[k][1]
        if np.hypot(*rb) >= 8 or np.hypot(*ro) >= 8:
            continue
        triples.append((k[0], prof, float(np.hypot(*rb)), float(np.hypot(*ro)),
                        float(np.hypot(*(ro - lomo[k[0]])))))
    sess = np.array([t[0] for t in triples])
    prof_ = np.array([t[1] for t in triples])
    R = np.array([t[2:] for t in triples])
    for sid in per_session:
        mm = sess == sid
        if mm.any():
            per_session[sid].update(n=int(mm.sum()), mean_base=round(float(R[mm, 0].mean()), 3),
                                    mean_official=round(float(R[mm, 1].mean()), 3),
                                    mean_offset=round(float(R[mm, 2].mean()), 3))
    rng = np.random.default_rng(seed)
    summary = {}
    for prof in sorted(set(prof_)) + ["all"]:
        mm = np.ones(len(R), bool) if prof == "all" else prof_ == prof
        us = np.unique(sess[mm])
        idx_of = {u: np.where(mm & (sess == u))[0] for u in us}
        boot = []
        for _ in range(2000):
            idx = np.concatenate([idx_of[u] for u in rng.choice(us, len(us))])
            boot.append(((R[idx, 2] - R[idx, 0]).mean(), (R[idx, 2] - R[idx, 1]).mean()))
        boot = np.array(boot)
        summary[prof] = {"n": int(mm.sum()), "sessions": len(us),
                         "median_base": round(float(np.median(R[mm, 0])), 3),
                         "median_official": round(float(np.median(R[mm, 1])), 3),
                         "median_offset": round(float(np.median(R[mm, 2])), 3),
                         "change_vs_base": round(float((R[mm, 2] - R[mm, 0]).mean()), 3),
                         "change_vs_base_lo": round(float(np.percentile(boot[:, 0], 2.5)), 3),
                         "change_vs_base_hi": round(float(np.percentile(boot[:, 0], 97.5)), 3),
                         "change_vs_official": round(float((R[mm, 2] - R[mm, 1]).mean()), 3),
                         "change_vs_official_lo": round(float(np.percentile(boot[:, 1], 2.5)), 3),
                         "change_vs_official_hi": round(float(np.percentile(boot[:, 1], 97.5)), 3)}
    return {"summary": summary, "sessions": per_session}


def _deps() -> dict:
    import hashlib

    def sha(p: Path) -> str:
        return hashlib.sha256("\n".join(p.read_text(encoding="utf-8").splitlines()).encode()).hexdigest()
    return {"map_asset": sha(Path(A.__file__)), "profiles": sha(A.PROFILES_FILE),
            "build": A.BUILD, "eval": EVAL_VERSION}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--images", default=None, help="write one comparison PNG per key here")
    ap.add_argument("--riot", nargs=2, metavar=("BASE_JSON", "OFFICIAL_JSON"))
    ap.add_argument("--world", nargs=2, metavar=("BASE_JSON", "OFFICIAL_NO_OFFSET_JSON"),
                    help="score each map's world offset leave-one-match-out on Riot victim rows")
    a = ap.parse_args(argv)
    deps = _deps()
    if a.world:
        got = riot_world_lomo(Path(a.world[0]), Path(a.world[1]))
        for sid, v in sorted(got["sessions"].items()):
            print(f"  {sid} {json.dumps(v)}")
        for prof, v in got["summary"].items():
            print(f"  {prof:22s} {json.dumps(v)}")
            if a.record:
                metrics.record(TOOL, part=f"world_lomo/{prof}", values=v, deps=deps,
                               context={"base": a.world[0], "official": a.world[1]})
        return 0
    if a.riot:
        got = riot(Path(a.riot[0]), Path(a.riot[1]))
        for prof, v in got.items():
            print(f"  {prof:22s} {json.dumps(v)}")
            if a.record:
                metrics.record(TOOL, part=f"riot_world/{prof}", values=v, deps=deps,
                               context={"base": a.riot[0], "official": a.riot[1]})
        return 0
    rows = assets()
    for k, v in rows.items():
        print(f"  {k:16s} {v}")
    summary = {"api_vs_fog_mad_max": max(v["vs_fog"] for v in rows.values()),
               "api_vs_revealed_mad_min": min(v["vs_revealed"] for v in rows.values())}
    if a.record:
        metrics.record(TOOL, part="assets", values=summary, deps=deps)
    keys = sorted(p.stem for p in G.capture_dir(STORE).glob("*.npz")
                  if G.SEP in p.stem and G.drawable(p.stem, STORE))
    per = {}
    for k in keys:
        per[k] = key_fields(k, Path(a.images) if a.images else None)
        print(f"  {k:34s} {json.dumps(per[k])}")
        if a.record:
            metrics.record(TOOL, part=f"fields/{k}", values=per[k], deps=deps)
    test = [v for v in per.values() if not v["train"]]
    agg = {"keys": len(per), "test_keys": len(test),
           "centre_dev_max_px": max(v["centre_dev_px"] for v in per.values()),
           "scale_dev_max_pct": max(v["scale_dev_pct"] for v in per.values()),
           "flat_static_minus_fog_median": float(np.median([v["flat_static_minus_fog"] for v in per.values()])),
           "flat_static_minus_fog_min": min(v["flat_static_minus_fog"] for v in per.values()),
           "flat_static_minus_fog_max": max(v["flat_static_minus_fog"] for v in per.values()),
           "reg_max_px": max(v["reg_px"] for v in per.values()),
           "lo_mae_flat_max": max(v["lo_mae_flat"] for v in per.values()),
           "hi_mae_two_max": max(v["hi_mae_two"] for v in per.values()),
           "floor_mask_iou_min": min(v["floor_mask_iou"] for v in per.values()),
           "footprint_iou_min": min(v["footprint_iou"] for v in per.values())}
    print(f"  all {json.dumps(agg)}")
    if a.record:
        metrics.record(TOOL, part="all", values=agg, deps=deps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
