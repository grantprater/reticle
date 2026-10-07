r"""Where the enemy ring search loses icons the error budget calls `ring_unproposed`.

Task `enemy-proposal-fix-20261007` (rows EP in the store's
`notes/predictions.jsonl`). The error budget
(`prototypes/enemy_error_budget.py`, tag `b1`) classes a T1d miss
`ring_unproposed` where the place is red like an icon and the reader stored
no candidate of any kind there. This prototype replays the enemy search's
stages on the minimap roi_cache crop of each sampled row, with the stored
code path and the stored icon scale, and names the first stage that loses
the icon:

    replay_hit   the replay accepts an icon within near (instrument check)
    mask         keyed red (`enemy_red_mask` & floor) in the icon disc is
                 under the component minimum area
    blob_small   no closed component touching the disc reaches the minimum area
    unsupported  every such component misses the slab
    seed_off     every such component's ring fit (`minimap.fit_ring`, seeded
                 at the component centroid, +-SEARCH px) lands beyond near
    cov_gate     a fit within near covers under COV_MIN of its circumference
    inner_gate   a fit within near holds over INNER_RED_MAX keyed interior
    nms          a fit within near passes the gates and loses the separation
                 rule to a better-covered fit
    downstream   a proposal within near survives the ring search; the
                 teardrop or a gate moves or drops it

Each stage is the library's own call (`minimap_objects.enemy_red_mask`,
`minimap.fit_ring`, `minimap.icons(gates=False)`, `minimap._gated`,
`minimap.coverage_surface`, `minimap_objects.read_frame`); the closed
components are recomputed only to say which blob a fit came from, and every
row checks that the per-component fits equal `icons(gates=False)`'s.

Each row also carries the other seeds' gated proposals at the place (`cf`),
the soft-redness ring score there, and, where the stored reader accepted the
icon within +-2 frames, the miss frame traced again at that accepted place
beside the hit frame (the intermittency pairs). `trace` replays
`read_frame` without a prior, so it reproduces the stored rows only under
the code that wrote them: the run kept as `funnel/trace_master.jsonl` is
a015c85's (minimap-object-0.5.0). `extras` diffs two scored tags' true
false accepts and hits and draws the new false accepts.

    python prototypes/enemy_proposal_funnel.py trace --n 25
    python prototypes/enemy_proposal_funnel.py table
    python prototypes/enemy_proposal_funnel.py sheet
    python prototypes/enemy_proposal_funnel.py extras --base b1 --tag pk1

Stored rows, replay truth's stored places and the roi_cache only; no
decode. The held-out capture is refused. Not wired (`"wire": "no"`).
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "enemy-proposal-funnel-0.1.0"
STORE = Path(DEFAULT_STORE)
BUDGET = STORE / "analysis" / "enemy-error-budget-20261007"
SEED = 20261007
ADJ = 2
STAGES = ("replay_hit", "mask", "blob_small", "unsupported", "seed_off", "cov_gate",
          "inner_gate", "nms", "downstream")


def _r(v, n=2):
    return None if v is None or not np.isfinite(v) else round(float(v), n)


def _rows_by_frame(tag: str, sid: str):
    fr = []
    for i, line in enumerate(tr.rows_path(tag, sid).open(encoding="utf-8")):
        if i == 0:
            continue
        r = json.loads(line)
        if r.get("kind") == "frame":
            fr.append(r)
    fr.sort(key=lambda r: r["t_ms"])
    return fr, {r["frame_idx"]: i for i, r in enumerate(fr)}


def _bands(sc: float):
    """The ring radii `icons(radii="inside")` searches (instrument-checked)."""
    from reticle import minimap as mm
    return (max(3, int(np.ceil(mm.R_MIN * sc - 1e-9))), max(4, int(np.floor(mm.R_MAX * sc + 1e-9))))


def trace_place(crop, ctx, sc, x, y, near, *, t_ms=None, turn=False, stored=None):
    """Every stage of the enemy ring search at the place (x, y)."""
    import cv2

    from reticle import minimap as mm
    from reticle import minimap_objects as mo

    floor, slab = ctx["floor"], ctx["slab"]
    mask = mo.enemy_red_mask(crop)
    keyed = mask & floor
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    H, W = keyed.shape
    yy, xx = np.mgrid[0:H, 0:W]
    r_disc = 0.9 * mo.ICON_PX * sc
    disc = np.hypot(xx - x, yy - y) <= r_disc
    min_area = max(4, int(round(mm.MIN_ICON_AREA * sc * sc)))
    r_min, r_max = _bands(sc)
    m = cv2.morphologyEx(keyed.astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((mm._odd(3 * sc), mm._odd(3 * sc)), np.uint8))
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, 8)
    supported = set(np.unique(lbl[(m > 0) & slab]).tolist())
    fits = {}
    for i in range(1, n):
        if st[i, 4] < min_area or i not in supported:
            continue
        f = mm.fit_ring(keyed, grey, cen[i][0], cen[i][1], r_min, r_max)
        if f is not None:
            fits[i] = f
    raw = mm.icons(mask, crop, floor, cov_min=mo.COV_MIN, inner_max=mo.INNER_RED_MAX,
                   require_facing=False, support=slab, seed="centroid", scale=sc,
                   radii="inside", gates=False)
    mine = sorted((round(f["cx"], 2), round(f["cy"], 2), int(f["r"]), round(f["cov"], 4)) for f in fits.values())
    theirs = sorted((round(f["cx"], 2), round(f["cy"], 2), int(f["r"]), round(f["cov"], 4)) for f in raw)
    pre = mm._gated(raw, sc, cov_min=mo.COV_MIN, inner_max=mo.INNER_RED_MAX,
                    require_facing=False, separation_px=0)
    post = mm._gated(raw, sc, cov_min=mo.COV_MIN, inner_max=mo.INNER_RED_MAX,
                     require_facing=False)
    touch = [i for i in np.unique(lbl[(m > 0) & disc]).tolist() if i]
    comps = []
    for i in touch:
        f = fits.get(i)
        comps.append({"label": i, "area": int(st[i, 4]), "supported": i in supported,
                      "d_centroid": _r(math.hypot(cen[i][0] - x, cen[i][1] - y)),
                      "fit": None if f is None else {
                          "cx": f["cx"], "cy": f["cy"], "r": int(f["r"]), "cov": _r(f["cov"], 3),
                          "inner": _r(f["inner_red"], 3), "d": _r(math.hypot(f["cx"] - x, f["cy"] - y))}})
    # The ring at the place itself: the best circumference coverage within
    # 1.5 px of it, over the searched radii (`coverage_surface`).
    surf, srad = mm.coverage_surface(keyed, r_min, r_max)
    near_pl = np.hypot(xx - x, yy - y) <= 1.5
    k = int(np.argmax(np.where(near_pl, surf, -1.0)))
    cov_place, r_place = float(surf.flat[k]), int(srad.flat[k])
    # The same score over the teardrop's soft redness (no cut before the
    # ring): the mean redness along the circle.
    from reticle import teardrop
    soft = teardrop.redness(crop) * floor
    ssurf, _ = mm.coverage_surface(soft, r_min, r_max)
    soft_place = float(np.where(near_pl, ssurf, -1.0).max())
    rep = mo.read_frame(crop, ctx, scale=sc, turn=turn, t_ms=t_ms)
    acc = [math.hypot(e["x"] - x, e["y"] - y) for e in rep["enemies"]]
    reproduced = None
    if stored is not None:
        reproduced = (sorted((e["x"], e["y"]) for e in rep["enemies"])
                      == sorted((e["x"], e["y"]) for e in stored.get("enemies", [])))
    out = {"n_mask": int((mask & disc).sum()), "n_keyed": int((keyed & disc).sum()),
           "min_area": min_area, "r_band": [r_min, r_max], "comps": comps,
           "fits_match_icons": mine == theirs, "cov_place": _r(cov_place, 3), "r_place": r_place,
           "soft_cov_place": _r(soft_place, 3),
           "d_acc": _r(min(acc)) if acc else None, "reproduced": reproduced}
    # first losing stage
    if acc and min(acc) <= near:
        stage = "replay_hit"
    elif out["n_keyed"] < min_area:
        stage = "mask"
    elif not any(c["area"] >= min_area for c in comps):
        stage = "blob_small"
    elif not any(c["area"] >= min_area and c["supported"] for c in comps):
        stage = "unsupported"
    else:
        nearfits = [c["fit"] for c in comps if c["fit"] is not None and c["fit"]["d"] <= near]
        if not nearfits:
            # a fit from another component may still land here
            nearfits = [{"cx": f["cx"], "cy": f["cy"], "r": f["r"], "cov": _r(f["cov"], 3),
                         "inner": _r(f["inner"], 3), "d": _r(math.hypot(f["cx"] - x, f["cy"] - y))}
                        for f in raw if math.hypot(f["cx"] - x, f["cy"] - y) <= near]
        if not nearfits:
            stage = "seed_off"
        elif all(f["cov"] < mo.COV_MIN for f in nearfits):
            stage = "cov_gate"
        elif all(f["cov"] < mo.COV_MIN or f["inner"] > mo.INNER_RED_MAX for f in nearfits):
            stage = "inner_gate"
        elif not any(math.hypot(f["cx"] - x, f["cy"] - y) <= near for f in post):
            stage = "nms"
            sup = [g for g in post if any(math.hypot(g["cx"] - f["cx"], g["cy"] - f["cy"])
                                          < mm.MIN_ICON_SEPARATION_PX * sc for f in nearfits)]
            out["suppressor"] = [{"cx": g["cx"], "cy": g["cy"], "cov": _r(g["cov"], 3),
                                  "d": _r(math.hypot(g["cx"] - x, g["cy"] - y))} for g in sup]
        else:
            stage = "downstream"
            out["refused_near"] = [q for q in rep["refused"]
                                   if math.hypot(q["x"] - x, q["y"] - y) <= near]
        out["nearfits"] = nearfits
    out["stage"] = stage
    out["n_pre"] = sum(math.hypot(f["cx"] - x, f["cy"] - y) <= near for f in pre)
    # Counterfactual proposals: the other seeds of `minimap.icons`, gated.
    cf = {}
    for sd in ("surface", "peaks"):
        g = mm.icons(mask, crop, floor, cov_min=mo.COV_MIN, inner_max=mo.INNER_RED_MAX,
                     require_facing=False, support=slab, seed=sd, scale=sc, radii="inside")
        d = [math.hypot(f["cx"] - x, f["cy"] - y) for f in g]
        cf[sd] = {"n": len(g), "d": _r(min(d)) if d else None,
                  "hit": bool(d) and min(d) <= near}
    cf["centroid"] = {"n": len(post), "hit": any(math.hypot(f["cx"] - x, f["cy"] - y) <= near
                                                  for f in post)}
    out["cf"] = cf
    return out


def _sample(n_per: int) -> list[dict]:
    """The eye sheet's rows (visible ones flagged) plus `n_per` random
    `ring_unproposed` rows per match, seeded."""
    picks = [json.loads(ln) for ln in
             (BUDGET / "b1" / "eye" / "miss__ring_unproposed" / "picks.jsonl").open(encoding="utf-8")]
    out, seen = [], set()
    VISIBLE = {1, 2, 3, 5, 6, 7, 8, 10, 11}   # the orchestrator's eye check of sheet.png
    for p in picks:
        key = (p["session"], p["frame_idx"], p["j"])
        seen.add(key)
        out.append(dict(p, src="eye", visible=p["i"] in VISIBLE))
    rng = np.random.default_rng(SEED)
    for sid in tr.DEV:
        F = [json.loads(ln) for ln in (BUDGET / "b1" / f"classed_{sid}.jsonl").open(encoding="utf-8")]
        F = [f for f in F if f.get("cls") == "ring_unproposed"
             and (f["session"], f["frame_idx"], f["j"]) not in seen]
        for i in rng.permutation(len(F))[:n_per]:
            out.append(dict(F[int(i)], src="random", visible=None))
    return out


def trace(n_per: int, out_dir: Path) -> int:
    from reticle import minimap_objects as mo
    from reticle.store import Store

    rows = _sample(n_per)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    by_sid = defaultdict(list)
    for r in rows:
        tr.refuse(r["session"])
        by_sid[r["session"]].append(r)
    for sid, R in by_sid.items():
        ctx, why = mo.object_context(tr._PingStore(Store(STORE), "b1"), sid)
        if ctx is None:
            raise SystemExit(f"{sid}: {why}")
        sc = float(ctx["icon_scale"])
        FR, fidx = _rows_by_frame("b1", sid)
        need = {}
        for r in R:
            i = fidx[r["frame_idx"]]
            for d in range(-ADJ, ADJ + 1):
                if 0 <= i + d < len(FR):
                    need[FR[i + d]["t_ms"]] = FR[i + d]
        crops = {}
        x0, y0, x1, y1 = ctx["rect"]
        for smp in ctx["cache"].samples(sorted(need), rois=["minimap"]):
            crops[float(smp.t_ms)] = np.ascontiguousarray(smp.frame[y0:y1, x0:x1])
        for r in R:
            i = fidx[r["frame_idx"]]
            x, y = r["px"]
            near = float(r["near_px"])
            row = {"session": sid, "round": r["round"], "frame_idx": r["frame_idx"], "j": r["j"],
                   "agent": r["agent"], "src": r["src"], "visible": r["visible"], "eye_i": r.get("i"),
                   "px": r["px"], "near_px": near, "icon_scale": sc, "red_sum": r.get("red_sum"),
                   "d_acc_adj": r.get("d_acc_adj"), "frames": {}}
            for d in range(-ADJ, ADJ + 1):
                if not 0 <= i + d < len(FR):
                    continue
                fr = FR[i + d]
                crop = crops.get(float(fr["t_ms"]))
                if crop is None or fr.get("reason") is not None:
                    row["frames"][str(d)] = {"reason": fr.get("reason") or "not_cached"}
                    continue
                seg = ctx["cache"].widget.at(fr["t_ms"]) if ctx["cache"].widget is not None else None
                turn = bool(seg) and int(seg.get("rotation", 0)) == 180
                st_acc = [math.hypot(e["x"] - x, e["y"] - y) for e in fr.get("enemies", [])]
                t = trace_place(crop, ctx, sc, x, y, near, t_ms=float(fr["t_ms"]), turn=turn, stored=fr)
                t["stored_d_acc"] = _r(min(st_acc)) if st_acc else None
                t["stored_hit"] = bool(st_acc) and min(st_acc) <= near
                if t["stored_hit"]:
                    # the accepted icon's own place, for the paired comparison
                    e = min(fr["enemies"], key=lambda e: math.hypot(e["x"] - x, e["y"] - y))
                    t["acc_xy"] = [e["x"], e["y"]]
                    t["acc_ring"] = e.get("ring")
                row["frames"][str(d)] = t
            # the miss frame traced again at the neighbours' accepted place
            hits = [row["frames"][k] for k in row["frames"] if k != "0"
                    and row["frames"][k].get("stored_hit")]
            if hits and "stage" in row["frames"]["0"]:
                h = min(hits, key=lambda t: t["stored_d_acc"])
                ax, ay = h["acc_xy"]
                fr = FR[i]
                crop = crops[float(fr["t_ms"])]
                row["at_acc"] = trace_place(crop, ctx, sc, ax, ay, near, t_ms=float(fr["t_ms"]))
                row["at_acc"]["xy"] = [ax, ay]
                row["at_acc"]["hit_ring"] = h.get("acc_ring")
                k0 = [k for k in row["frames"] if row["frames"][k] is h][0]
                fr2 = FR[i + int(k0)]
                row["hit_at_acc"] = trace_place(crops[float(fr2["t_ms"])], ctx, sc, ax, ay, near,
                                                t_ms=float(fr2["t_ms"]))
                row["hit_at_acc"]["dk"] = int(k0)
            res.append(row)
            f0 = row["frames"].get("0", {})
            print(f"{sid} r{r['round']} f{r['frame_idx']} {r['agent']:<9} vis={r['visible']} "
                  f"stage={f0.get('stage')} keyed={f0.get('n_keyed')} cov@place={f0.get('cov_place')} "
                  f"repro={f0.get('reproduced')} icons_eq={f0.get('fits_match_icons')}", flush=True)
    p = out_dir / "trace.jsonl"
    with open(p, "w", encoding="utf-8") as f:
        for r in res:
            f.write(json.dumps(r, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
    print(f"{len(res)} rows -> {p}")
    return 0


def _ci95(k, n):
    """`reticle.rounds._wilson`, rounded; None for no rows."""
    from reticle.rounds import _wilson as w
    return [None, None] if n == 0 else [round(v, 3) for v in w(k, n)]


def table(out_dir: Path) -> int:
    R = [json.loads(ln) for ln in (out_dir / "trace.jsonl").open(encoding="utf-8")]
    groups = {"all": R, "visible (eye)": [r for r in R if r["visible"]],
              "random": [r for r in R if r["src"] == "random"]}
    for sid in tr.DEV:
        groups[f"random {sid}"] = [r for r in R if r["src"] == "random" and r["session"] == sid]
    out = {}
    for g, rs in groups.items():
        c = Counter(r["frames"]["0"].get("stage") for r in rs)
        n = len(rs)
        out[g] = {"n": n, "stages": {s: {"k": c[s], "share": _r(c[s] / n, 3) if n else None,
                                         "ci95": _ci95(c[s], n)} for s in STAGES if c[s]}}
        print(f"\n{g}: n={n}")
        for s in STAGES:
            if c[s]:
                print(f"  {s:<12} {c[s]:>3}  {c[s] / n:.2f} {_ci95(c[s], n)}")
    # counterfactual seeds: a gated proposal within near on the miss frame,
    # and on the neighbouring frames the stored reader accepted (kept?)
    out["cf"] = {}
    for g, rs in groups.items():
        line = {}
        for sd in ("centroid", "surface", "peaks"):
            k = sum(r["frames"]["0"].get("cf", {}).get(sd, {}).get("hit", False) for r in rs)
            hf = [f for r in rs for kk, f in r["frames"].items() if kk != "0" and f.get("stored_hit")]
            kh = sum(f.get("cf", {}).get(sd, {}).get("hit", False) for f in hf)
            nprop = [f.get("cf", {}).get(sd, {}).get("n", 0) for r in rs for f in r["frames"].values()
                     if "cf" in f]
            line[sd] = {"miss_proposed": k, "of": len(rs), "ci95": _ci95(k, len(rs)),
                        "hit_frames_proposed": kh, "hit_frames": len(hf),
                        "proposals_per_frame": _r(np.mean(nprop), 2) if nprop else None}
        out["cf"][g] = line
        print(f"\ncf {g}: " + "; ".join(f"{sd} miss {v['miss_proposed']}/{v['of']} {v['ci95']} "
                                         f"hitfr {v['hit_frames_proposed']}/{v['hit_frames']} "
                                         f"prop/fr {v['proposals_per_frame']}" for sd, v in line.items()))
        if g == "all":
            st = Counter((r["frames"]["0"].get("stage"), r["frames"]["0"].get("cf", {}).get("peaks", {}).get("hit"))
                         for r in rs)
            print("  stage x peaks-proposed:", dict(st))
    inst = Counter((r["frames"]["0"].get("reproduced"), r["frames"]["0"].get("fits_match_icons")) for r in R)
    print("\ninstrument (reproduced, fits==icons):", dict(inst))
    out["instrument"] = {str(k): v for k, v in inst.items()}
    # the paired comparison: the miss frame and a neighbouring hit frame at the accepted place
    pairs = [r for r in R if "at_acc" in r]
    print(f"\npaired miss/hit frames at the neighbour's accepted place: {len(pairs)}")
    rows = []
    for r in pairs:
        a, b = r["at_acc"], r["hit_at_acc"]
        rows.append((a["stage"], a["n_keyed"], b["n_keyed"], a["cov_place"], b["cov_place"],
                     a["r_place"], b["r_place"], (r.get("at_acc", {}).get("hit_ring") or {}).get("r")))
    for x in rows:
        print("  miss stage=%-11s keyed %3s vs %3s  cov@place %.3f vs %.3f  r@place %s vs %s  hit ring r %s" % x)
    out["paired"] = {"n": len(pairs), "miss_stage": dict(Counter(x[0] for x in rows)),
                     "keyed_miss_med": _r(np.median([x[1] for x in rows])) if rows else None,
                     "keyed_hit_med": _r(np.median([x[2] for x in rows])) if rows else None,
                     "cov_miss_med": _r(np.median([x[3] for x in rows]), 3) if rows else None,
                     "cov_hit_med": _r(np.median([x[4] for x in rows]), 3) if rows else None}
    (out_dir / "table.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    return 0


def sheet(out_dir: Path, per: int = 4) -> int:
    """Per stage, up to `per` rows: the crop, the HSV key, the closed
    components, and each component's ring fit (display only, nearest)."""
    import cv2

    from reticle import minimap as mm
    from reticle import minimap_objects as mo
    from reticle.store import Store

    R = [json.loads(ln) for ln in (out_dir / "trace.jsonl").open(encoding="utf-8")]
    by = defaultdict(list)
    for r in sorted(R, key=lambda r: (not r["visible"], r["session"], r["frame_idx"])):
        by[r["frames"]["0"].get("stage")].append(r)
    for stage, rs in by.items():
        rs = rs[:per]
        tiles = []
        for r in rs:
            sid = r["session"]
            ctx, _ = mo.object_context(tr._PingStore(Store(STORE), "b1"), sid)
            FR, fidx = _rows_by_frame("b1", sid)
            fr = FR[fidx[r["frame_idx"]]]
            x0, y0, x1, y1 = ctx["rect"]
            smp = next(iter(ctx["cache"].samples([fr["t_ms"]], rois=["minimap"])))
            crop = np.ascontiguousarray(smp.frame[y0:y1, x0:x1])
            sc = r["icon_scale"]
            x, y = r["px"]
            keyed = mo.enemy_red_mask(crop) & ctx["floor"]
            m = cv2.morphologyEx(keyed.astype(np.uint8), cv2.MORPH_CLOSE,
                                 np.ones((mm._odd(3 * sc), mm._odd(3 * sc)), np.uint8))
            half = int(round(22 * sc)) + 4
            cx, cy = int(round(x)), int(round(y))
            H, W = keyed.shape
            a, b, c, d = max(0, cy - half), min(H, cy + half), max(0, cx - half), min(W, cx + half)
            z = max(4, int(round(8 / sc)))
            win = cv2.resize(crop[a:b, c:d], None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)  # display only
            km = np.zeros_like(crop[a:b, c:d])
            km[keyed[a:b, c:d]] = (0, 0, 255)
            km[(m[a:b, c:d] > 0) & ~keyed[a:b, c:d]] = (0, 140, 255)
            km = cv2.resize(km, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)  # display only
            for img in (win, km):
                P = lambda u, v: (int((u - c + 0.5) * z), int((v - a + 0.5) * z))
                cv2.circle(img, P(x, y), int(r["near_px"] * z), (255, 0, 255), 1)
                for comp in r["frames"]["0"].get("comps", []):
                    f = comp["fit"]
                    if f:
                        col = (0, 255, 0) if f["cov"] >= mo.COV_MIN else (0, 255, 255)
                        cv2.circle(img, P(f["cx"], f["cy"]), int(f["r"] * z), col, 1)
            f0 = r["frames"]["0"]
            lab = (f"{sid[:6]} r{r['round']} {r['agent']} {stage} keyed {f0['n_keyed']} "
                   f"cov@pl {f0['cov_place']}")
            fits = "; ".join(f"a{cc['area']} cov{cc['fit']['cov']} d{cc['fit']['d']}"
                             for cc in f0.get("comps", []) if cc["fit"])
            tile = np.hstack([win, np.full((win.shape[0], 4, 3), 255, np.uint8), km])
            bar = np.zeros((34, tile.shape[1], 3), np.uint8)
            cv2.putText(bar, lab[:70], (3, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
            cv2.putText(bar, fits[:80], (3, 29), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
            tiles.append(np.vstack([bar, tile]))
        w = max(t.shape[1] for t in tiles)
        tiles = [np.pad(t, ((0, 6), (0, w - t.shape[1]), (0, 0))) for t in tiles]
        p = out_dir / f"stage_{stage}.png"
        cv2.imwrite(str(p), np.vstack(tiles))
        print(p)
    return 0


def _tag_rows(tag: str, sid: str) -> dict:
    d = {}
    for i, line in enumerate(tr.rows_path(tag, sid).open(encoding="utf-8")):
        if i == 0:
            continue
        r = json.loads(line)
        if r.get("kind") == "frame":
            d[r["frame_idx"]] = r
    return d


def new_extras(sid: str, base: str, tag: str, out_dir: Path, n: int = 16) -> int:
    """The true false accepts (`other`) of `tag` with no accepted icon of
    `base` within 2 px in the same frame, and the hits `tag` adds: teardrop
    scores beside each, and a sheet of `n` false accepts (native crop and a
    nearest enlargement, display only)."""
    import cv2

    from reticle import minimap_objects as mo
    from reticle.store import Store

    tr.refuse(sid)
    S = lambda t: [json.loads(ln) for ln in (tr.OUT / t / f"sets_{sid}.jsonl").open(encoding="utf-8")]
    Sb, St = S(base), S(tag)
    Rb, Rt = _tag_rows(base, sid), _tag_rows(tag, sid)

    def acc(R, fi, xy, tol):
        es = R.get(fi, {}).get("enemies", [])
        e = min(es, key=lambda e: math.hypot(e["x"] - xy[0], e["y"] - xy[1])) if es else None
        return e if e is not None and math.hypot(e["x"] - xy[0], e["y"] - xy[1]) <= tol else None

    new_fa = [e for e in St if e["set"] == "extra" and e["cls"] == "other"
              and acc(Rb, e["frame_idx"], e["icon_px"], 2.0) is None]
    hb = {(h["frame_idx"], h["j"]) for h in Sb if h["set"] == "hit"}
    new_hit = [h for h in St if h["set"] == "hit" and (h["frame_idx"], h["j"]) not in hb]
    rows = []
    for e in new_fa:
        a = acc(Rt, e["frame_idx"], e["icon_px"], 0.5)
        rows.append({"set": "new_false_accept", "frame_idx": e["frame_idx"], "round": e["round"],
                     "xy": e["icon_px"], "ncc": a and a["ncc"], "margin": a and a["margin"],
                     "ring": a and a["ring"]})
    for h in new_hit:
        fi = h["frame_idx"]
        es = Rt.get(fi, {}).get("enemies", [])
        a = min(es, key=lambda e: math.hypot(e["x"] - h["px"][0], e["y"] - h["px"][1])) if es else None
        rows.append({"set": "new_hit", "frame_idx": fi, "round": h["round"], "xy": h["px"],
                     "ncc": a and a["ncc"], "margin": a and a["margin"], "ring": a and a["ring"]})
    out_dir.mkdir(parents=True, exist_ok=True)
    with open(out_dir / f"new_{tag}_vs_{base}_{sid}.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    for s in ("new_false_accept", "new_hit"):
        v = np.array([r["ncc"] for r in rows if r["set"] == s and r["ncc"] is not None], float)
        if v.size:
            print(f"{s}: n={v.size} ncc q10/25/50/75 {np.percentile(v, [10, 25, 50, 75]).round(3)}")
    ctx, _ = mo.object_context(Store(STORE), sid)
    x0, y0, x1, y1 = ctx["rect"]
    t_of = {fi: r["t_ms"] for fi, r in Rt.items()}
    pick = sorted(new_fa, key=lambda e: zlib_hash(e))[:n]
    tiles = []
    smp = {float(s.t_ms): s for s in ctx["cache"].samples(sorted({t_of[e["frame_idx"]] for e in pick}),
                                                          rois=["minimap"])}
    for e in pick:
        crop = smp[float(t_of[e["frame_idx"]])].frame[y0:y1, x0:x1]
        cx, cy = (int(round(v)) for v in e["icon_px"])
        H, W = crop.shape[:2]
        a, b, c, d = max(0, cy - 18), min(H, cy + 18), max(0, cx - 18), min(W, cx + 18)
        win = np.zeros((36, 36, 3), np.uint8)
        win[:b - a, :d - c] = crop[a:b, c:d]
        big = cv2.resize(win, None, fx=7, fy=7, interpolation=cv2.INTER_NEAREST)  # display only
        ac = acc(Rt, e["frame_idx"], e["icon_px"], 0.5)
        cv2.circle(big, (int((e["icon_px"][0] - c + 0.5) * 7), int((e["icon_px"][1] - a + 0.5) * 7)),
                   int(ac["r"] * 7) if ac else 40, (0, 255, 0), 1)
        cv2.putText(big, f"r{e['round']} f{e['frame_idx']} ncc {ac and ac['ncc']}", (3, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
        tiles.append(big)
    while len(tiles) % 4:
        tiles.append(np.zeros_like(tiles[0]))
    sheet = np.vstack([np.hstack(tiles[i:i + 4]) for i in range(0, len(tiles), 4)])
    p = out_dir / f"new_false_accepts_{tag}_vs_{base}_{sid}.png"
    cv2.imwrite(str(p), sheet)
    print(f"{len(new_fa)} new false accepts, {len(new_hit)} new hits -> {p}")
    return 0


def zlib_hash(e) -> int:
    import zlib
    return zlib.crc32(f"{e['frame_idx']}:{e['icon_px']}".encode())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=("trace", "table", "sheet", "extras"))
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--session", default="9acf02f98283")
    ap.add_argument("--base", default="b1")
    ap.add_argument("--tag", default="pk1")
    ap.add_argument("--out", default=str(STORE / "analysis" / "enemy-proposal-fix-20261007" / "funnel"))
    a = ap.parse_args(argv)
    out = Path(a.out)
    if a.cmd == "trace":
        return trace(a.n, out)
    if a.cmd == "table":
        return table(out)
    if a.cmd == "extras":
        return new_extras(a.session, a.base, a.tag, out.parent / "extras")
    return sheet(out)


if __name__ == "__main__":
    raise SystemExit(main())
