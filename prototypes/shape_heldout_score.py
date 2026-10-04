r"""The frozen shape channels (ability shapes, smokes) scored once on the held-out minimap labelling pass.

    .\.venv\Scripts\python.exe prototypes\shape_heldout_score.py run    [--only sid,sid]
    .\.venv\Scripts\python.exe prototypes\shape_heldout_score.py dev
    .\.venv\Scripts\python.exe prototypes\shape_heldout_score.py score

Why. The glyph matcher's held-out score (`minimap_glyph_eval.py heldout`,
<store>/analysis/minimap-heldout-score-20261004/heldout.json) put about 40 of
its 139 headline marks on shapes -- smoke discs, wall lines, small circles --
where a glyph matcher names at chance. This asks what the pipeline's own shape
channels say at those marks, unchanged.

`run` drives two frozen readers over each labelled demo's active spans from the
minimap crop cache (`passes.run_cached`; no decode):

- `ability_scan.AbilityShapeReader` as `shape_reader` builds it, 2 Hz, with
  `phase_at=None` and `supply=None` (`no_lineup`). `reticle scan <demo> --only
  ability` cannot run on a demo: `cli._live_phase_at` calls `store.read_hud`,
  which exits on a session with no HUD reads, though its docstring promises
  None and every sample read; `reticle hud` would decode. A demo has no lineup,
  so `ability_candidates.for_session` answers `no_lineup` and every gated
  sample takes the unnamed surprise path.
- `minimap_dark.DarkRegionReader` (4 Hz), then `adjudication.smokes.tracks`
  over its rows (menu None).

It writes runs/<sid>.json under the analysis directory and nothing to the
store's events: demos are not refreshed in the store (matches only).

`dev` runs the Astra star-to-smoke check on 223d636bf8d2 (Astra a teammate;
stored `smoke` tracks, all named Astra by `smoke_owner`'s team_smoke_agent):
at each track's birth + 1 s the proposer discs inside the smoke and the
frozen matcher's name for them over Astra's kit, and in the 10 s before the
birth any disc the matcher names Astra:X within the smoke's reach.

`score` scores once, with the rules fixed in the store's predictions.jsonl
(shape-heldout-score-20261004) before any run: per mark, a shape on it (teal
gate component, accepted surprise ring or beam) and a smoke on it; the
names each channel gives; the joint rules J1 (glyph if a glyph disc is
present, else shape), J2 (smoke first, else J1) and J3 (Astra: smoke names
Nebula, else the glyph). TOL is the matcher's SNAP_R (8 px x scale).

Wire: no. An evaluation of frozen readers on held-out labels; no rule is
promoted before the player confirms the glyph/shape split.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cv2  # noqa: E402
import numpy as np  # noqa: E402

cv2.setNumThreads(1)
if os.name == "nt":
    import ctypes
    ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x4000)

VERSION = "shape-heldout-score-0.1.0"
STORE = Path("C:/Users/grant/reticle-store")
OUT = STORE / "analysis" / "shape-heldout-score-20261004"
HELDOUT = STORE / "analysis" / "minimap-heldout-score-20261004" / "heldout.json"
LABEL_DIR = STORE / "labels" / "minimap_glyph_heldout"
DEV_ASTRA = "223d636bf8d2"
#: The matcher's snap reach (px at the 465 px widget), reused as every tolerance here; fixed before any run.
SNAP_R = 8.0
#: Nearest 2 Hz ability sample a mark may take, and the smoke track's slack at each end (one 4 Hz period).
ABILITY_DT_MS, SMOKE_SLACK_MS = 500.0, 250.0
#: DEV: the frame after a track's birth read for discs, and the window before it searched for a star.
DEV_AFTER_MS, DEV_BEFORE_MS = 1000.0, 10000.0


def _store():
    from reticle.store import Store
    return Store(str(STORE))


def _active(store, sid):
    man = store.read_manifest(sid)
    sp = store.read_spans(sid, man["ingested_at"][:10])
    return man, [(float(a), float(b)) for a, b, s in zip(sp.column("t_start_ms").to_pylist(),
                                                         sp.column("t_end_ms").to_pylist(),
                                                         sp.column("state").to_pylist()) if s == "active"]


def run_session(sid: str) -> dict:
    """Both frozen readers over one session's active spans, fed from the crop cache."""
    from reticle import geometry, lighting, passes, roi_cache
    from reticle.ability_candidates import for_session, values_digest
    from reticle.ability_scan import shape_reader
    from reticle.adjudication.smokes import tracks
    from reticle.minimap import minimap_roi_px
    from reticle.minimap_dark import dark_reader
    from reticle.profiles import get_profile
    from reticle import version as V
    store = _store()
    man, spans = _active(store, sid)
    profile = get_profile(man["source_profile"])
    ctx = passes.SessionContext(store=store, manifest=man, profile=profile, spans=spans)
    supply, why = for_session(sid, store)
    floor, sgray = ctx.floor(), ctx.sgray()
    bp = shape_reader(ctx, spans, phase_at=None, floor=floor, sgray=sgray, supply=supply,
                      supply_reason=why, values=values_digest())
    dp = dark_reader(ctx, spans, hz=4.0, floor=floor, sgray=sgray)
    readers = [r for r in (bp, dp) if r is not None]
    for r in readers:
        roi_cache.declare_set(r, "minimap", profile, ctx.wh)
    cache, cwhy = roi_cache.cache_for(STORE, man, profile, readers)
    if cache is None:
        return {"session_id": sid, "refused": f"no cache feed: {cwhy}"}
    box = list(minimap_roi_px(profile, *ctx.wh))
    rect = list(cache.rect_of("minimap"))
    t0 = time.time()
    n = passes.run_cached(ctx, readers, cache)
    out = {"session_id": sid, "version": VERSION, "capture": man["source"]["path"],
           "supply": None if supply is not None else why, "box": box, "cache_rect": rect,
           "frames_fed": n, "wall_s": round(time.time() - t0, 1),
           "stamps": {"ability_gate": V.ABILITY_GATE_VERSION, "ability_shape": V.ABILITY_SHAPE_VERSION,
                      "ability_fit": V.ABILITY_FIT_VERSION, "ability_wall": V.ABILITY_WALL_VERSION,
                      "minimap_dark": V.MINIMAP_DARK_VERSION, "smoke": V.SMOKE_VERSION},
           "crop_wh": [box[2] - box[0], box[3] - box[1]]}
    out["gate"] = [{k: r.get(k) for k in ("t_ms", "gate", "reason", "components")} for r in bp.gate_rows]
    out["surprise"] = [{k: r.get(k) for k in ("t_ms", "surprise_reason", "rings", "beam")} for r in bp.shape_rows]
    out["fit"], out["wall"] = bp.fit_rows, bp.wall_rows
    if dp is None:
        out["smoke"], out["smoke_refused"] = [], "no lighting reference"
    else:
        with np.load(geometry.path_of(sid, store.root)) as z:
            ref = lighting.reference(z)
        rows = [{"kind": "coverage", "hz": dp.hz}] + dp.rows
        out["smoke"] = tracks(rows, ref.known, None)
        out["dark_frames"] = len(dp.rows)
        out["dark_drawn"] = sum(r.get("widget_drawn") is True for r in dp.rows)
    return out


def cmd_run(args) -> None:
    (OUT / "runs").mkdir(parents=True, exist_ok=True)
    sids = sorted(p.stem for p in LABEL_DIR.glob("*.jsonl"))
    if args.only:
        sids = [s for s in sids if s in set(args.only.split(","))]
    for sid in sids:
        dst = OUT / "runs" / f"{sid}.json"
        if dst.is_file() and not args.force:
            print(f"  {sid}: kept {dst.name}")
            continue
        got = run_session(sid)
        json.dump(got, open(dst, "w"), default=float)
        print(f"  {sid}: {got.get('refused') or ''} fed {got.get('frames_fed')} gate {len(got.get('gate', []))} "
              f"surprise {len(got.get('surprise', []))} fit {len(got.get('fit', []))} "
              f"smokes {len(got.get('smoke', []))} {got.get('wall_s')} s", flush=True)


# ------------------------------------------------------------------ per-mark reads


def seg_dist(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    L = dx * dx + dy * dy
    u = 0.0 if L == 0 else max(0.0, min(1.0, ((px - x0) * dx + (py - y0) * dy) / L))
    return math.hypot(px - (x0 + u * dx), py - (y0 + u * dy))


def ability_on(run: dict, t: float, x: float, y: float, tol: float) -> dict:
    """What the ability reader holds at the sample nearest t, near (x, y)."""
    G = run["gate"]
    if not G:
        return {"sample": None}
    g = min(G, key=lambda r: abs(r["t_ms"] - t))
    if abs(g["t_ms"] - t) > ABILITY_DT_MS:
        return {"sample": None, "nearest_dt_ms": round(g["t_ms"] - t)}
    o = {"sample": g["t_ms"], "reason": g["reason"], "teal": False, "ring": False, "beam": False}
    for c in g.get("components") or []:
        cx0, cy0, w, h = c[:4]
        if cx0 - tol <= x <= cx0 + w + tol and cy0 - tol <= y <= cy0 + h + tol:
            o["teal"] = True
    s = next((r for r in run["surprise"] if r["t_ms"] == g["t_ms"]), None)
    if s is not None:
        o["ring"] = any(f["accepted"] and math.hypot(x - f["cx"], y - f["cy"]) <= f["r"] + tol for f in s["rings"])
        b = s.get("beam")
        o["beam"] = bool(b and b["accepted"] and seg_dist(x, y, b["x0"], b["y0"], b["x1"], b["y1"]) <= tol)
    f = next((r for r in run["fit"] if r["t_ms"] == g["t_ms"]), None)
    o["named"] = sorted({d["descriptor"] for d in (f or {}).get("fits", []) if d.get("found")})
    return o


def smoke_on(run: dict, t: float, x: float, y: float, tol: float) -> dict | None:
    hit = [s for s in run["smoke"] if s["first_ms"] - SMOKE_SLACK_MS <= t <= s["last_ms"] + SMOKE_SLACK_MS
           and math.hypot(x - s["cx"], y - s["cy"]) <= s["r"] + tol]
    if not hit:
        return None
    s = min(hit, key=lambda s: math.hypot(x - s["cx"], y - s["cy"]))
    return {"track": s["track"], "first_ms": s["first_ms"], "r": s["r"],
            "d": round(math.hypot(x - s["cx"], y - s["cy"]), 1)}


def smoke_name(agent: str | None) -> str | None:
    """The demo's one agent's smoke slot, `smoke_owner`'s team_smoke_agent with a one-agent side."""
    from reticle.adjudication.smoke_owner import SMOKE_ABILITY
    return f"{agent}:{SMOKE_ABILITY[agent][0]}" if agent in SMOKE_ABILITY else None


def cmd_score(args) -> None:
    H = json.load(open(HELDOUT))
    runs = {p.stem: json.load(open(p)) for p in (OUT / "runs").glob("*.json")}
    marks = []
    for m in H["marks"]:
        if m.get("class") != "named" or not m.get("truth"):
            continue
        run = runs.get(m["sid"])
        if run is None or run.get("refused"):
            marks.append({**{k: m.get(k) for k in ("item", "i", "sid", "truth", "subsets")}, "refused": "no_run"})
            continue
        assert run["box"] == run["cache_rect"], (m["sid"], run["box"], run["cache_rect"])
        tol = SNAP_R * m["scale"]
        x, y, t = m["x"], m["y"], m["t_held"]
        ab = ability_on(run, t, x, y, tol)
        sm = smoke_on(run, t, x, y, tol)
        in_span = any(a <= t <= b for a, b in _active(_store(), m["sid"])[1]) if args.spans else None
        shape_name = smoke_name(m["agent"]) if sm else (ab.get("named") or [None])[0]
        glyph = m.get("follow_pred")
        j1 = glyph if m.get("snapped") else shape_name
        j2 = smoke_name(m["agent"]) if (sm and smoke_name(m["agent"])) else j1
        j3 = ("Astra:E" if sm else glyph) if m["agent"] == "Astra" else glyph
        marks.append({k: m.get(k) for k in ("item", "i", "sid", "t_held", "agent", "truth", "truth_name", "subsets",
                                             "snapped", "follow_pred", "x", "y", "scale")}
                     | {"ability": ab, "smoke": sm, "in_active_span": in_span, "shape_name": shape_name,
                        "J1": j1, "J2": j2, "J3": j3})
    res = {"version": VERSION, "heldout": str(HELDOUT), "rules": "predictions.jsonl shape-heldout-score-20261004",
           "runs": {s: {k: r.get(k) for k in ("capture", "supply", "frames_fed", "wall_s", "stamps", "refused",
                                              "dark_frames", "dark_drawn")} | {"smokes": len(r.get("smoke", [])),
                                                                                 "surprise": len(r.get("surprise", [])),
                                                                                 "fit_rows": len(r.get("fit", []))}
                    for s, r in runs.items()}}
    for sub in ("headline", "dev_session", "near_tuned_label", "audit_only"):
        M = [m for m in marks if sub in (m.get("subsets") or []) and not m.get("refused")]
        per = defaultdict(Counter)
        for m in M:
            a = m["ability"]
            per[m["truth"]]["n"] += 1
            per[m["truth"]]["smoke"] += m["smoke"] is not None
            per[m["truth"]]["teal"] += bool(a.get("teal"))
            per[m["truth"]]["ring_or_beam"] += bool(a.get("ring") or a.get("beam"))
            per[m["truth"]]["no_ability_sample"] += a.get("sample") is None
            per[m["truth"]]["snapped"] += bool(m["snapped"])
            sn = m["shape_name"]
            per[m["truth"]]["shape_right" if sn == m["truth"] else "shape_wrong" if sn else "shape_none"] += 1
            for j in ("follow_pred", "J1", "J2", "J3"):
                per[m["truth"]][f"{j}_right"] += m[j] == m["truth"]
        tot = Counter()
        for c in per.values():
            tot.update(c)
        res[sub] = {"n": len(M), "total": dict(tot), "per_ability": {k: dict(v) for k, v in sorted(per.items())},
                    "smoke_off_slot": sorted({(m["truth"], m["item"]) for m in M if m["smoke"] is not None
                                              and smoke_name(m["agent"]) != m["truth"]}),
                    "named_by_ability_reader": sum(bool(m["ability"].get("named")) for m in M)}
    res["marks"] = marks
    OUT.mkdir(parents=True, exist_ok=True)
    json.dump(res, open(OUT / "score.json", "w"), indent=1, default=float)
    print(json.dumps({k: res[k] for k in ("headline", "dev_session")}, indent=1, default=str)[:6000])


# ------------------------------------------------------------------ DEV: Astra star to smoke


def cmd_dev(args) -> None:
    import minimap_glyph_eval as ge
    from reticle import ability_icons
    store = _store()
    ge.build_extra(ge.PROBE_STATES, answers=True)
    rows = store.read_events("smoke", DEV_ASTRA)
    own = {r["track"]: r for r in store.read_events("smoke_owner", DEV_ASTRA) if r.get("kind") == "smoke_owner"}
    trk = [r for r in rows if r.get("kind") == "track"]
    c, why, man = ge.crop_cache(DEV_ASTRA)
    cr = c.rect_of("minimap")
    h = np.asarray(c.holds(), float)
    keys = sorted(ge.kit("Astra"))
    plan = {}
    for tr in trk:
        a = h[np.argmin(np.abs(h - (tr["first_ms"] + DEV_AFTER_MS)))]
        pre = h[(h >= tr["first_ms"] - DEV_BEFORE_MS) & (h < tr["first_ms"])][::15]
        plan[tr["track"]] = (float(a), [float(t) for t in pre])
    need = sorted({t for a, p in plan.values() for t in [a, *p]})
    got = {s.t_ms: s.frame[cr[1]:cr[3], cr[0]:cr[2]].copy() for s in c.samples(need, rois=["minimap"])}
    out, tiles = [], []
    for tr in trk:
        a, pre = plan[tr["track"]]
        crop = got.get(a)
        rec = {"track": tr["track"], "first_ms": tr["first_ms"], "last_ms": tr["last_ms"], "cx": tr["cx"],
               "cy": tr["cy"], "r": tr["r"], "owner": own.get(tr["track"], {}).get("agent"), "after_ms": a}
        if crop is None:
            rec["refused"] = "no_frame"
            out.append(rec)
            continue
        scale = crop.shape[1] / 465.0
        tol = SNAP_R * scale
        terms = ge.icon_terms(DEV_ASTRA, crop.shape)
        Y = ge.luma(crop)

        def named(img, t):
            Yi = ge.luma(img)
            res = []
            for p in ability_icons.propose_icons(img, terms):
                d = math.hypot(p["cx"] - tr["cx"], p["cy"] - tr["cy"])
                if d <= tr["r"] + tol:
                    cl = ge.classify(Yi, float(p["cx"]), float(p["cy"]), keys, scale, rotate=True)
                    res.append({"t_ms": t, "cx": round(float(p["cx"]), 1), "cy": round(float(p["cy"]), 1),
                                "d": round(d, 1), "pred": cl and f"{cl['pred'][0]}:{cl['pred'][1]}",
                                "score": cl and round(cl["score"], 3), "margin": cl and round(cl["margin"], 3)})
            return res

        rec["after"] = named(crop, a)
        rec["before"] = [x for t in pre if t in got for x in named(got[t], t)]
        rec["star_before"] = any(x["pred"] == "Astra:X" for x in rec["before"])
        out.append(rec)
        k = 4
        x0, y0 = int(max(0, tr["cx"] - 24)), int(max(0, tr["cy"] - 24))
        def tile(img, txt):
            w = cv2.resize(img[y0:y0 + 48, x0:x0 + 48], None, fx=k, fy=k, interpolation=cv2.INTER_NEAREST)
            w = cv2.copyMakeBorder(w, 0, 0, 0, 192 - w.shape[1], cv2.BORDER_CONSTANT) if w.shape[1] < 192 else w
            w = cv2.copyMakeBorder(w, 0, 192 - w.shape[0], 0, 0, cv2.BORDER_CONSTANT) if w.shape[0] < 192 else w
            cv2.putText(w, txt, (3, 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 255), 1)
            return w
        row = [tile(got[t], f"{tr['track']} pre {(t - tr['first_ms']) / 1000:.1f}s") for t in pre[-3:] if t in got]
        row += [tile(crop, f"{tr['track']} +1s " + ",".join(x["pred"] or "-" for x in rec["after"]))]
        while len(row) < 4:
            row.insert(0, np.zeros((192, 192, 3), np.uint8))
        tiles.append(np.hstack(row))
    OUT.mkdir(parents=True, exist_ok=True)
    if tiles:
        cv2.imwrite(str(OUT / "dev_astra_tracks.png"), np.vstack(tiles))
    summ = {"session": DEV_ASTRA, "capture": man["source"]["path"], "tracks": len(trk),
            "owners": dict(Counter(r.get("owner") for r in out)),
            "with_disc_after": sum(bool(r.get("after")) for r in out),
            "after_names": dict(Counter(x["pred"] for r in out for x in r.get("after", []))),
            "star_before": sum(bool(r.get("star_before")) for r in out),
            "before_names": dict(Counter(x["pred"] for r in out for x in r.get("before", [])))}
    json.dump({"version": VERSION, "summary": summ, "tracks": out}, open(OUT / "dev_astra.json", "w"),
              indent=1, default=float)
    print(json.dumps(summ, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--only")
    r.add_argument("--force", action="store_true")
    sub.add_parser("dev")
    s = sub.add_parser("score")
    s.add_argument("--spans", action="store_true", help="also say whether each mark lies in an active span")
    a = ap.parse_args()
    {"run": cmd_run, "dev": cmd_dev, "score": cmd_score}[a.cmd](a)


if __name__ == "__main__":
    main()
