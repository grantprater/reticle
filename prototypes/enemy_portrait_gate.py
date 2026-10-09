r"""Does a portrait gate let the enemy ring search propose every peak?

Task `enemy-portrait-gate-20261007` (rows PG in the store's
`notes/predictions.jsonl`). The proposal diagnosis
(`prototypes/enemy_proposal_funnel.py`) found that the ring search's one
circle per red blob slides off an icon whose faint rim touches a red
neighbour, and that the 331 px rim keys under the coverage cut. Proposing
every gated peak recovers icons and adds red-rimmed utility discs, triangles
and faint X marks. This prototype measures the cross-reference that the
reader now applies: a find is an enemy icon only where its interior fits one
of the match's enemy agents' rendered minimap portraits.

* `separation` -- offline, from stored reread rows and their T1d sets: the
  gate score (`identity.rendered_art_fit` over the match's enemy five, from
  `lineup.portrait_candidates`) of every accepted enemy, split into T1d hits,
  true false accepts and the rest; AUC and the keep rates at given cuts.
* `softcal` -- on a seeded sample of 9acf02f98283's T1d pairs, the binary
  key's and the soft redness's ring coverage at each true icon place
  (`minimap.coverage_surface`) and at the reread's true false accepts.
* `paired --tag TAG [--base b1]` -- per match and pooled, Delta hits and
  Delta true false accepts against the base tag, with a paired bootstrap over
  rounds (the same rounds; truth is unchanged between tags).

Stored rows, the T1d sets `teardrop_refusals.py score` wrote, and the
roi_cache only; no decode. The held-out capture is refused. Not wired
(`"wire": "no"`): an evaluation; the gate lives in `reticle/minimap_objects.py`.

    python prototypes/enemy_portrait_gate.py separation --tag b1
    python prototypes/enemy_portrait_gate.py softcal --n 300
    python prototypes/enemy_portrait_gate.py paired --tag pg1
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "enemy-portrait-gate-eval-0.1.0"
TASK = "enemy-portrait-gate-20261007"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / TASK
SEED = 20261007
N_BOOT = 4000
TRUE_FA = ("ping", "x_mark", "other")


def _frames(tag: str, sid: str) -> dict:
    out = {}
    for i, line in enumerate(tr.rows_path(tag, sid).open(encoding="utf-8")):
        if i == 0:
            continue
        r = json.loads(line)
        if r.get("kind") == "frame":
            out[r["frame_idx"]] = r
    return out


def _sets(tag: str, sid: str) -> list[dict]:
    p = tr.OUT / tag / f"sets_{sid}.jsonl"
    if not p.is_file():
        raise SystemExit(f"{sid}: no sets at {p}; run teardrop_refusals.py score {sid} --tag {tag}")
    return [json.loads(ln) for ln in p.open(encoding="utf-8")]


def _auc(pos, neg) -> float | None:
    """P(a positive scores LOWER, i.e. fits better, than a negative)."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    if not len(pos) or not len(neg):
        return None
    allv = np.concatenate([pos, neg])
    from scipy.stats import rankdata
    rk = rankdata(allv)
    r_pos = rk[:len(pos)].sum()
    u = r_pos - len(pos) * (len(pos) + 1) / 2
    return round(1.0 - u / (len(pos) * len(neg)), 4)


def separation(tag: str, cuts: list[float], record: bool = False) -> int:
    from reticle import lineup
    from reticle.adjudication import identity

    refs = identity.load_ally_portrait_references(STORE)
    fit_max = (refs.get("teammate_fit") or {}).get("fit_max")
    res = {"tag": tag, "version": VERSION, "fit_max_owner": fit_max, "sessions": {}}
    for sid in tr.DEV:
        tr.refuse(sid)
        cands, stamp = lineup.portrait_candidates(sid, STORE)
        five = (cands or {}).get("enemy") or []
        F = _frames(tag, sid)
        near = None
        groups = defaultdict(list)
        for r in _sets(tag, sid):
            fr = F.get(r["frame_idx"])
            if fr is None:
                continue
            if r["set"] == "hit":
                x, y = r["px"]
                cls = "hit"
            elif r["set"] == "extra":
                x, y = r["icon_px"]
                cls = r["cls"]
            else:
                continue
            es = fr.get("enemies") or []
            if not es:
                continue
            e = min(es, key=lambda e: math.hypot(e["x"] - x, e["y"] - y))
            d = math.hypot(e["x"] - x, e["y"] - y)
            if cls != "hit" and d > 0.5:
                continue
            fit = identity.rendered_art_fit(e.get("portrait_features"), five, refs)
            if fit is None:
                groups["no_features"].append(None)
                continue
            groups[cls].append(fit[0])
        tfa = sum((groups[c] for c in TRUE_FA), [])
        S = {"five": five, "lineup": stamp,
             "n": {k: len(v) for k, v in groups.items()},
             "median": {k: round(float(np.median(v)), 3) for k, v in groups.items()
                        if v and v[0] is not None},
             "auc_hit_vs_true_fa": _auc(groups["hit"], tfa),
             "hit_fit_p99": (round(float(np.percentile(groups["hit"], 99)), 3)
                             if groups["hit"] else None),
             "keep": {}}
        for c in cuts + ([fit_max] if fit_max else []):
            S["keep"][f"{c:.3f}"] = {
                "hit": round(float(np.mean(np.asarray(groups["hit"]) <= c)), 4) if groups["hit"] else None,
                "true_fa": round(float(np.mean(np.asarray(tfa) <= c)), 4) if tfa else None,
                "visible_undrawn": (round(float(np.mean(np.asarray(groups["visible_undrawn"]) <= c)), 4)
                                    if groups["visible_undrawn"] else None)}
        res["sessions"][sid] = S
        print(sid, json.dumps(S), flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"separation_{tag}.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        for sid, S in res["sessions"].items():
            vals = {"hit_fit_p99": S["hit_fit_p99"], "auc_hit_vs_true_fa": S["auc_hit_vs_true_fa"]}
            vals.update({f"median_{k}": v for k, v in S["median"].items()})
            for c, kv in S["keep"].items():
                vals[f"keep_hit@{c}"] = kv["hit"]
                vals[f"keep_true_fa@{c}"] = kv["true_fa"]
            rec("enemy_portrait_gate", part=f"separation/{tag}", session=sid, values=vals,
                deps={"version": VERSION, "rule": "T1d", "lineup": S["lineup"],
                      "portrait_refs": "ally-portrait-refs-1.0.0"},
                context={"task": TASK, "five": S["five"]},
                note="identity.rendered_art_fit of each accepted enemy's stored portrait_features "
                     "to the closest of the lineup's enemy five; T1d hits against true false accepts")
    return 0


# ------------------------------------------------------------------ soft cut

def softcal(n: int, record: bool = False, sid: str = "9acf02f98283") -> int:
    """Binary and soft ring coverage at T1d pair places on one match."""
    import cv2

    from reticle import minimap as mm
    from reticle import minimap_objects as mo
    from reticle import teardrop
    from reticle.store import Store

    tr.refuse(sid)
    ctx, why = mo.object_context(tr._PingStore(Store(STORE), "b1"), sid)
    if ctx is None:
        raise SystemExit(why)
    sc = float(ctx["icon_scale"])
    r_min = max(3, int(np.ceil(mm.R_MIN * sc - 1e-9)))
    r_max = max(4, int(np.floor(mm.R_MAX * sc + 1e-9)))
    S = _sets("b1", sid)
    classed = {}
    bp = STORE / "analysis" / "enemy-error-budget-20261007" / "b1" / f"classed_{sid}.jsonl"
    for ln in bp.open(encoding="utf-8"):
        c = json.loads(ln)
        if c.get("set") == "miss":
            classed[(c["frame_idx"], c["j"])] = c.get("cls")
    items = []
    for r in S:
        if r["set"] == "hit":
            items.append(("hit", r["frame_idx"], r["px"]))
        elif r["set"] == "miss":
            items.append((classed.get((r["frame_idx"], r["j"]), "miss"), r["frame_idx"], r["px"]))
        elif r["set"] == "extra" and r["cls"] in TRUE_FA:
            items.append(("true_fa", r["frame_idx"], r["icon_px"]))
    rng = np.random.default_rng(SEED)
    keep = [items[int(i)] for i in rng.permutation(len(items))[:n]]
    F = _frames("b1", sid)
    want = sorted({F[f]["t_ms"] for _c, f, _p in keep if f in F})
    x0, y0, x1, y1 = ctx["rect"]
    crops = {}
    for smp in ctx["cache"].samples(want, rois=["minimap"]):
        crops[float(smp.t_ms)] = np.ascontiguousarray(smp.frame[y0:y1, x0:x1])
    floor = ctx["floor"]
    rows = []
    surf = {}
    for cls, f, (x, y) in keep:
        fr = F.get(f)
        if fr is None or fr.get("reason") is not None:
            continue
        crop = crops.get(float(fr["t_ms"]))
        if crop is None:
            continue
        if f not in surf:
            key = mo.enemy_red_mask(crop) & floor
            soft = teardrop.redness(crop) * floor
            surf[f] = (mm.coverage_surface(key, r_min, r_max)[0],
                       mm.coverage_surface(soft, r_min, r_max)[0])
        b, s = surf[f]
        H, W = b.shape
        yy, xx = np.mgrid[0:H, 0:W]
        near = np.hypot(xx - x, yy - y) <= 1.5
        if not near.any():
            continue
        rows.append({"cls": cls, "frame_idx": f, "bin": round(float(b[near].max()), 3),
                     "soft": round(float(s[near].max()), 3)})
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / f"softcal_{sid}.jsonl", "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r) + "\n")
    by = defaultdict(list)
    for r in rows:
        by[r["cls"]].append(r)
    vals = {}
    for c, R in sorted(by.items(), key=lambda kv: -len(kv[1])):
        vals[f"bin_median_{c}"] = round(float(np.median([r["bin"] for r in R])), 3)
        vals[f"soft_median_{c}"] = round(float(np.median([r["soft"] for r in R])), 3)
        vals[f"n_{c}"] = len(R)
        b = np.array([r["bin"] for r in R])
        s = np.array([r["soft"] for r in R])
        print(f"{c:22s} n={len(R):4d} bin q25/50/75 {np.round(np.percentile(b, [25, 50, 75]), 3)} "
              f"soft {np.round(np.percentile(s, [25, 50, 75]), 3)} "
              f"median(soft-bin) {np.median(s - b):+.3f} "
              f"pass bin>=.30 {np.mean(b >= 0.30):.2f} "
              + " ".join(f"soft>={c2:.2f} {np.mean(s >= c2):.2f}" for c2 in (0.15, 0.2, 0.25, 0.3)),
              flush=True)
        vals[f"soft_pass030_{c}"] = round(float(np.mean(s >= 0.30)), 3)
        vals[f"bin_pass030_{c}"] = round(float(np.mean(b >= 0.30)), 3)
    if record:
        from reticle.metrics import record as rec
        rec("enemy_portrait_gate", part="softcal", session=sid, values=vals,
            deps={"version": VERSION, "rule": "T1d", "classes": "enemy_error_budget b1"},
            context={"task": TASK, "n": n, "seed": SEED},
            note="best ring coverage within 1.5 px of each sampled T1d place: the HSV key's share "
                 "and the mean teardrop.redness, both on the floor, over the searched radii")
    return 0


# ------------------------------------------------------------------ paired

def _per_round(tag: str, sid: str):
    hits, fa = defaultdict(int), defaultdict(int)
    rounds = set()
    for r in _sets(tag, sid):
        rounds.add(r["round"])
        if r["set"] == "hit":
            hits[r["round"]] += 1
        elif r["set"] == "extra" and r.get("cls") in TRUE_FA:
            fa[r["round"]] += 1
    return rounds, hits, fa


def paired(tag: str, base: str, record: bool) -> int:
    rng = np.random.default_rng(SEED)
    out = {"tag": tag, "base": base, "version": VERSION, "boot": f"{N_BOOT} round resamples, seed {SEED}",
           "sessions": {}}
    pooled_dh, pooled_df = [], []
    for sid in tr.DEV:
        if not (tr.OUT / tag / f"sets_{sid}.jsonl").is_file():
            print(f"{sid}: {tag} not scored")
            continue
        r0, h0, f0 = _per_round(base, sid)
        r1, h1, f1 = _per_round(tag, sid)
        rounds = sorted(r0 | r1)
        dh = np.array([h1[r] - h0[r] for r in rounds], float)
        df = np.array([f1[r] - f0[r] for r in rounds], float)
        idx = rng.integers(0, len(rounds), (N_BOOT, len(rounds)))
        bh, bf = dh[idx].sum(1), df[idx].sum(1)
        s1 = json.loads((tr.OUT / tag / f"score_{sid}.json").read_text(encoding="utf-8"))
        s0 = json.loads((tr.OUT / base / f"score_{sid}.json").read_text(encoding="utf-8"))
        S = {"hits": s1["hits"], "hit_rate": s1["hit_rate"], "hit_rate_ci": s1["hit_rate_ci"],
             "false_accepts": s1["false_accepts"], "false_accepts_ci": s1["false_accepts_ci"],
             "base_hits": s0["hits"], "base_hit_rate": s0["hit_rate"], "base_false_accepts": s0["false_accepts"],
             "d_hits": int(dh.sum()), "d_hits_ci": [int(np.percentile(bh, 2.5)), int(np.percentile(bh, 97.5))],
             "d_fa": int(df.sum()), "d_fa_ci": [int(np.percentile(bf, 2.5)), int(np.percentile(bf, 97.5))],
             "extras_by_class": s1["extras_by_class"], "minimap_object_version": s1["minimap_object_version"],
             "rounds": len(rounds)}
        out["sessions"][sid] = S
        pooled_dh.append(dh)
        pooled_df.append(df)
        print(f"{sid} {tag}: hit rate {S['hit_rate']:.4f} {S['hit_rate_ci']} (b {S['base_hit_rate']:.4f}) "
              f"FA {S['false_accepts']} {S['false_accepts_ci']} (b {S['base_false_accepts']}) "
              f"dHits {S['d_hits']:+d} {S['d_hits_ci']} dFA {S['d_fa']:+d} {S['d_fa_ci']}", flush=True)
    if len(pooled_dh) == len(tr.DEV):
        # pooled: rounds resampled within each match, the sums added
        tot_h = np.zeros(N_BOOT)
        tot_f = np.zeros(N_BOOT)
        for dh, df in zip(pooled_dh, pooled_df):
            idx = rng.integers(0, len(dh), (N_BOOT, len(dh)))
            tot_h += dh[idx].sum(1)
            tot_f += df[idx].sum(1)
        hits = sum(s["hits"] for s in out["sessions"].values())
        drawn = sum(json.loads((tr.OUT / tag / f"score_{sid}.json").read_text(encoding="utf-8"))["hits"]
                    + json.loads((tr.OUT / tag / f"score_{sid}.json").read_text(encoding="utf-8"))["misses"]
                    for sid in tr.DEV)
        bh = sum(s["base_hits"] for s in out["sessions"].values())
        P = {"hits": hits, "hit_rate": round(hits / drawn, 4), "base_hit_rate": round(bh / drawn, 4),
             "false_accepts": sum(s["false_accepts"] for s in out["sessions"].values()),
             "base_false_accepts": sum(s["base_false_accepts"] for s in out["sessions"].values()),
             "d_hits": int(sum(d.sum() for d in pooled_dh)),
             "d_hits_ci": [int(np.percentile(tot_h, 2.5)), int(np.percentile(tot_h, 97.5))],
             "d_fa": int(sum(d.sum() for d in pooled_df)),
             "d_fa_ci": [int(np.percentile(tot_f, 2.5)), int(np.percentile(tot_f, 97.5))]}
        out["pooled"] = P
        print(f"pooled {tag}: hit rate {P['hit_rate']:.4f} (b {P['base_hit_rate']:.4f}) FA {P['false_accepts']} "
              f"(b {P['base_false_accepts']}) dHits {P['d_hits']:+d} {P['d_hits_ci']} "
              f"dFA {P['d_fa']:+d} {P['d_fa_ci']}", flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"paired_{tag}_vs_{base}.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    if record:
        from reticle.metrics import record as rec
        for sid, S in out["sessions"].items():
            vals = {k: S[k] for k in ("hits", "hit_rate", "false_accepts", "d_hits", "d_fa")}
            vals.update({"d_hits_lo": S["d_hits_ci"][0], "d_hits_hi": S["d_hits_ci"][1],
                         "d_fa_lo": S["d_fa_ci"][0], "d_fa_hi": S["d_fa_ci"][1]})
            rec("enemy_portrait_gate", part=f"paired/{tag}-vs-{base}", session=sid, values=vals,
                deps={"version": VERSION, "rule": "T1d",
                      "minimap_object_version": S["minimap_object_version"]},
                context={"task": TASK, "boot": out["boot"]},
                note="T1d sets of teardrop_refusals.py score; true false accepts = ping + x_mark + other")
        if "pooled" in out:
            P = out["pooled"]
            vals = {k: P[k] for k in ("hits", "hit_rate", "false_accepts", "d_hits", "d_fa")}
            vals.update({"d_hits_lo": P["d_hits_ci"][0], "d_hits_hi": P["d_hits_ci"][1],
                         "d_fa_lo": P["d_fa_ci"][0], "d_fa_hi": P["d_fa_ci"][1]})
            rec("enemy_portrait_gate", part=f"paired/{tag}-vs-{base}", session=tr.pool_name(tr.DEV), values=vals,
                deps={"version": VERSION, "rule": "T1d"}, context={"task": TASK, "boot": out["boot"]},
                note="pooled over the three development matches; rounds resampled within each match")
    return 0


def _near_refusal(fr, x, y, near, prefix):
    for q in (fr or {}).get("refused") or []:
        if q["reason"].startswith(prefix) and math.hypot(q["x"] - x, q["y"] - y) <= near:
            return q
    return None


def sheet(sid: str, tag: str, base: str, per: int) -> int:
    """Native crops (display enlarged with nearest) of four sets on one match:
    `new_hit` (base miss, tag hit), `lost_hit` (base hit, tag miss),
    `gate_refused_miss` (a tag miss with a `not_a_portrait` refusal within
    near) and `true_fa` (the tag's true false accepts). Green: accepted
    icons; yellow: gate refusals; magenta: the truth place."""
    import cv2

    from reticle import minimap_objects as mo
    from reticle.store import Store

    tr.refuse(sid)
    ctx, why = mo.object_context(Store(STORE), sid)
    if ctx is None:
        raise SystemExit(why)
    sc = float(ctx["icon_scale"])
    near = mo.ICON_PX * sc
    A = {(r["k"], r["j"]): r for r in _sets(base, sid) if r["set"] in ("hit", "miss")}
    B = {(r["k"], r["j"]): r for r in _sets(tag, sid) if r["set"] in ("hit", "miss")}
    FB = _frames(tag, sid)
    sets = {"new_hit": [B[k] for k in B if B[k]["set"] == "hit" and A.get(k, {}).get("set") == "miss"],
            "lost_hit": [B[k] for k in B if B[k]["set"] == "miss" and A.get(k, {}).get("set") == "hit"],
            "gate_refused_miss": [r for r in B.values() if r["set"] == "miss" and _near_refusal(
                FB.get(r["frame_idx"]), r["px"][0], r["px"][1], near, "not_a_portrait")],
            "true_fa": [dict(r, px=r["icon_px"]) for r in _sets(tag, sid)
                        if r["set"] == "extra" and r["cls"] in TRUE_FA]}
    rng = np.random.default_rng(SEED)
    picks = {n: [R[int(i)] for i in rng.permutation(len(R))[:per]] for n, R in sets.items()}
    want = sorted({FB[r["frame_idx"]]["t_ms"] for R in picks.values() for r in R if r["frame_idx"] in FB})
    x0, y0, x1, y1 = ctx["rect"]
    crops = {}
    for smp in ctx["cache"].samples(want, rois=["minimap"]):
        crops[float(smp.t_ms)] = np.ascontiguousarray(smp.frame[y0:y1, x0:x1])
    half, up = int(round(2.5 * near)), 6
    out_dir = OUT / f"sheet_{tag}_vs_{base}"
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name, R in picks.items():
        tiles = []
        for r in R:
            fr = FB.get(r["frame_idx"])
            if fr is None or float(fr["t_ms"]) not in crops:
                continue
            crop = crops[float(fr["t_ms"])]
            x, y = r["px"]
            ix, iy = int(round(x)), int(round(y))
            pad = cv2.copyMakeBorder(crop, half, half, half, half, cv2.BORDER_CONSTANT)
            win = pad[iy:iy + 2 * half + 1, ix:ix + 2 * half + 1]
            big = cv2.resize(win, None, fx=up, fy=up, interpolation=cv2.INTER_NEAREST)  # display only
            def to(px, py):
                return (int((px - ix + half + 0.5) * up), int((py - iy + half + 0.5) * up))
            for e in fr.get("enemies") or []:
                cv2.circle(big, to(e["x"], e["y"]), int(near * up * 0.8), (0, 255, 0), 1)
            for q in fr.get("refused") or []:
                if q["reason"].startswith("not_a_portrait"):
                    cv2.drawMarker(big, to(q["x"], q["y"]), (0, 255, 255), cv2.MARKER_TILTED_CROSS, 14, 1)
            cv2.drawMarker(big, to(x, y), (255, 0, 255), cv2.MARKER_CROSS, 10, 1)
            cv2.imwrite(str(out_dir / f"{name}_{r['frame_idx']}_{ix}_{iy}_native.png"), win)
            tiles.append(big)
            q = _near_refusal(fr, x, y, near, "not_a_portrait")
            acc = [e for e in fr.get("enemies") or [] if math.hypot(e["x"] - x, e["y"] - y) <= near]
            meta.setdefault(name, []).append({
                "frame_idx": r["frame_idx"], "px": [x, y], "agent": r.get("agent"), "cls": r.get("cls"),
                "acc_fit": acc[0].get("portrait_fit") if acc else None,
                "refused_fit": q.get("portrait_fit") if q else None})
        if tiles:
            n = len(tiles)
            cols = min(6, n)
            rows_ = (n + cols - 1) // cols
            h, w = tiles[0].shape[:2]
            canvas = np.zeros((rows_ * (h + 4), cols * (w + 4), 3), np.uint8)
            for i, t in enumerate(tiles):
                rr, cc = divmod(i, cols)
                canvas[rr * (h + 4):rr * (h + 4) + h, cc * (w + 4):cc * (w + 4) + w] = t
            cv2.imwrite(str(out_dir / f"{sid}_{name}.png"), canvas)
        print(f"{sid} {name}: {len(sets[name])} rows, {len(tiles)} drawn", flush=True)
    (out_dir / f"{sid}_meta.json").write_text(json.dumps(
        {"counts": {n: len(R) for n, R in sets.items()}, "picks": meta}, indent=1), encoding="utf-8")
    return 0


def reread(sid: str, tag: str, ptag: str, sets: list[str], off: list[str]) -> int:
    """`teardrop_refusals.reread` with module parameters set (`NAME=VALUE`,
    e.g. RING_COVER=soft) and fixes turned off: the ablation arms. The head
    records the parameters; the stamp, the switches and the fixes."""
    from reticle import minimap_objects as mo

    for kv in sets:
        k, _, v = kv.partition("=")
        if not hasattr(mo, k):
            raise SystemExit(f"minimap_objects has no {k}")
        cur = getattr(mo, k)
        setattr(mo, k, type(cur)(v) if not isinstance(cur, bool) else v.lower() in ("1", "true"))
    for f in off:
        if f not in mo.ENABLED:
            raise SystemExit(f"no fix {f}")
        mo.ENABLED[f] = False
    return tr.reread(sid, tag, ptag)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reread")
    p.add_argument("sessions", nargs="+")
    p.add_argument("--tag", required=True)
    p.add_argument("--pings", default="b1")
    p.add_argument("--set", action="append", default=[])
    p.add_argument("--off", action="append", default=[])
    p = sub.add_parser("sheet")
    p.add_argument("session")
    p.add_argument("--tag", required=True)
    p.add_argument("--base", default="b1")
    p.add_argument("--per", type=int, default=12)
    p = sub.add_parser("separation")
    p.add_argument("--tag", required=True)
    p.add_argument("--cuts", default="1,1.5,2,3,4")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("softcal")
    p.add_argument("--n", type=int, default=300)
    p.add_argument("--session", default="9acf02f98283")
    p.add_argument("--record", action="store_true")
    p = sub.add_parser("paired")
    p.add_argument("--tag", required=True)
    p.add_argument("--base", default="b1")
    p.add_argument("--record", action="store_true")
    a = ap.parse_args(argv)
    tr._idle()
    if a.cmd == "reread":
        for sid in a.sessions:
            reread(sid, a.tag, a.pings, a.set, a.off)
        return 0
    if a.cmd == "sheet":
        return sheet(a.session, a.tag, a.base, a.per)
    if a.cmd == "separation":
        return separation(a.tag, [float(c) for c in a.cuts.split(",")], a.record)
    if a.cmd == "softcal":
        return softcal(a.n, a.record, a.session)
    return paired(a.tag, a.base, a.record)


if __name__ == "__main__":
    raise SystemExit(main())
