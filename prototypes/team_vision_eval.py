r"""Score `team_vision`'s team cones against the drawn light joined to the team's icons.

    .\.venv\Scripts\python.exe prototypes\team_vision_eval.py --arm NAME
    .\.venv\Scripts\python.exe prototypes\team_vision_eval.py --compare BEFORE AFTER [--record]

The measurement behind `team-vision-0.4.0`, which casts every teammate's cone
from the ally teardrop's centre along its facing (`reticle.teardrop.
IconPoseReader`), as 0.3.0 cast the self cone. `vision_origin_eval.py` scored
the self cone alone; teammates are a team signal, so this scores the union.

**The chain is the owner's.** Each arm drives `team_vision.TeamVision` over
the frames as the code on disk has it and keeps the frame's cast cones:
`observable` (the eligible union, what `reticle vision` stores as the team's
vision), `observable_all` (every tracked bearing), and, where the frame
reports each cone's source (`VisionFrame.origins`), the eligible union less
the cones a ring fit or a track supplied (`teardrop_only`), which is what the
chain would cast if it refused to fall back.

**The witness does not move between arms.** Every team icon is placed from
the pixels alone: the self icon by `teardrop_tip.fit` from its best
detection, each ally detection (`icon_teardrop.detections`) by the ally
teardrop at the widget's scale where it reads and by a disc of the detector's
radius where it does not. The light is `lighting.raw_lit` on known floor
within `cone_origin.R_EVAL` px of any icon, outside every icon's footprint
(`cone_origin._footprint`, grown by `cone_origin.PAD`); the witness keeps the
lit components that touch a `cone_origin.JOIN_PX` band round any footprint.
It uses no facing. Precision is the share of cone pixels in the region that
the witness holds; recall the share of the witness the cones cover; both pool
pixels over frames, and a frame that casts nothing counts its light in recall.

Frames are `vision_origin_eval`'s: e78e75b2d191's held-out odd 3 s blocks
outside the sliver neighbourhoods, through one chain; 5822b6646448's twenty
6 s windows through `team_vision.at` with a 10 s warm-up. Frames need at
least `cone_origin.MIN_LIT` witness pixels; consecutive identical witnesses
collapse. It reads the minimap crop cache only, decodes no video, and writes
to the store only with `--record` (one `metrics` row).

**Predictions** (2026-09-29, before the after arm ran): on both sessions the
eligible union's F1 under 0.4.0 is at least 0.3.0's, and Lotus's rises by at
least 0.02, since the ally ring's lobe-resolved facing errs a median 27
degrees and flips on a tenth of the labels where the teardrop errs 2.5 and
never flips; ally precision rises; pooled recall moves by under 0.03. The
falsifier is a lower F1 on either session.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import cone_origin as co  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import teardrop_tip as tt  # noqa: E402
import vision_origin_eval as voe  # noqa: E402
from reticle import cone, lighting, metrics  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "team-vision-eval-0.1.0"
UNIONS = ("eligible", "all", "teardrop_only")


def icons_of(s, crop) -> list[dict]:
    """Every team icon's footprint seed, from the pixels alone: `{"x", "y", "deg"|None, "r"}`."""
    out = []
    det = tt.self_start(crop, s.floor)
    if det is not None:
        tf = tt.fit(crop, det["cx"], det["cy"])
        if tf.get("read"):
            out.append({"x": tf["x"], "y": tf["y"], "deg": tf["deg"], "role": "self"})
    sc = widget_scale(crop.shape[1])
    key = it_.CLASSES["ally"].key(crop)
    for d in it_.detections(crop, "ally", s):
        f = it_.fit(None, "ally", d["cx"], d["cy"], key=key, scale=sc)
        if f.get("read"):
            out.append({"x": f["x"], "y": f["y"], "deg": f["deg"], "role": "ally"})
        else:
            out.append({"x": d["cx"], "y": d["cy"], "deg": None, "r": float(d["r"]), "role": "ally"})
    return out


def footprints(shape, icons) -> np.ndarray:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    fp = np.zeros(shape, bool)
    for ic in icons:
        if ic["deg"] is not None:
            fp |= co._footprint(shape, ic)
        else:
            fp |= np.hypot(xx - ic["x"], yy - ic["y"]) <= ic["r"] + co.PAD
    return fp


def witness(s, crop, icons):
    """`(region, joined light)` round every team icon, or None when no icon is placed."""
    import cv2
    if not icons:
        return None
    h, w = s.passable.shape
    yy, xx = np.mgrid[0:h, 0:w]
    near = np.zeros((h, w), bool)
    for ic in icons:
        near |= np.hypot(xx - ic["x"], yy - ic["y"]) <= co.R_EVAL
    fp = footprints((h, w), icons)
    region = near & s.ref.known & ~fp
    raw = lighting.raw_lit(crop, s.ref)
    lit = (raw & region).astype(np.uint8)
    band = cv2.dilate(fp.astype(np.uint8),
                      cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * co.JOIN_PX + 1,) * 2)) > 0
    n, lab = cv2.connectedComponents(lit, connectivity=8)
    keep = np.unique(lab[band & (lit > 0)])
    keep = keep[keep > 0]
    wit = np.isin(lab, keep) if len(keep) else np.zeros((h, w), bool)
    return region, wit


def unions(s, fr) -> dict:
    """The frame's cast cones as masks, per union, and per role for the eligible one."""
    shape = s.passable.shape
    empty = np.zeros(shape, bool)
    if fr.widget != "drawn" or fr.observable is None:
        return {u: empty for u in UNIONS} | {"self": empty, "ally": empty, "sources": {}}
    out = {"eligible": fr.observable, "all": fr.observable_all}
    origins = getattr(fr, "origins", None) or []
    keep = []
    by_role = {"self": empty.copy(), "ally": empty.copy()}
    sources: dict[str, int] = {}
    cones = fr.cones or []
    for i, ((role, tr), (_x, _y, adj, _c)) in enumerate(zip(fr.tracked, fr.adjudicated_resolved)):
        if adj is None or i >= len(cones) or cones[i] is None:
            continue
        src = source_of(fr, i, role, origins)
        sources[src] = sources.get(src, 0) + 1
        by_role[role] |= cones[i]
        if src == "teardrop/teardrop":
            keep.append(cones[i])
    out["teardrop_only"] = cone.union(keep, shape) if keep else empty
    return out | by_role | {"sources": sources}


def source_of(fr, i: int, role: str, origins) -> str:
    """`origin/facing` of cone `i`: the frame's own record where it keeps one."""
    rec = None
    poses = getattr(fr, "poses", None)
    if poses:
        rec = poses[i]
    elif role == "self":
        rec = getattr(fr, "self_cone", None)
    if rec is not None:
        return f"{rec.get('origin')}/{rec.get('facing')}"
    return f"{origins[i][2] if i < len(origins) else 'ring_fit'}/track"


def arm(sid: str) -> dict:
    s = sem.Session(sid)
    rows, prev, why = [], None, {}
    for t, crop, fr in voe.frames_of(s, sid):
        icons = icons_of(s, crop)
        got = witness(s, crop, icons)
        if got is None:
            why["no_icon"] = why.get("no_icon", 0) + 1
            continue
        region, wit = got
        key = (int(wit.sum()), tuple(sorted((round(i["x"], 2), round(i["y"], 2)) for i in icons)))
        if key == prev:
            continue
        prev = key
        if int(wit.sum()) < co.MIN_LIT:
            why["little_light"] = why.get("little_light", 0) + 1
            continue
        u = unions(s, fr)
        row = {"t": t, "lit": int(wit.sum()), "sources": u["sources"],
               "icons": len(icons), "allies_placed": sum(1 for i in icons if i["role"] == "ally")}
        for name in UNIONS + ("self", "ally"):
            m = u[name]
            row[name] = {"hits": int((m & wit).sum()), "n": int((m & region).sum())}
        rows.append(row)
    return {"rows": rows, "why": why}


def pool(rows, name: str) -> dict:
    h = sum(r[name]["hits"] for r in rows)
    n = sum(r[name]["n"] for r in rows)
    lit = sum(r["lit"] for r in rows)
    return {"frames": len(rows), "precision": h / n if n else None,
            "recall": h / lit if lit else None, "f1": 2 * h / (n + lit) if (n + lit) else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arm", help="run the code on disk and save it under this name")
    ap.add_argument("--compare", nargs=2, metavar=("BEFORE", "AFTER"),
                    help="score two saved arms on their common frames")
    ap.add_argument("--record", action="store_true", help="with --compare: one metrics row")
    ap.add_argument("--out", type=Path, default=Path(sem.tempfile.gettempdir()) / "team-vision-eval")
    ap.add_argument("--sessions", nargs="+", default=[sem.DEMO, voe.LOTUS])
    ap.add_argument("--no-fallback", action="store_true",
                    help="with --arm: the chain casts nothing where the teardrop is unread "
                         "(`TeamVision(ring_fallback=False)`)")
    args = ap.parse_args(argv)
    sem._below_normal()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.no_fallback:
        from reticle import team_vision
        base = team_vision.TeamVision.from_inputs.__func__
        team_vision.TeamVision.from_inputs = classmethod(
            lambda cls, inputs, origin_events=(), **kw: base(cls, inputs, origin_events,
                                                             ring_fallback=False, **kw))
    if args.arm:
        res = {sid: arm(sid) for sid in args.sessions}
        (args.out / f"{args.arm}.json").write_text(json.dumps(res), encoding="utf-8")
        for sid, r in res.items():
            print(args.arm, sid, {u: pool(r["rows"], u) for u in UNIONS}, "skipped", r["why"], flush=True)
    if args.compare:
        nb, na = args.compare
        b = json.loads((args.out / f"{nb}.json").read_text(encoding="utf-8"))
        a = json.loads((args.out / f"{na}.json").read_text(encoding="utf-8"))
        values = {}
        for sid in args.sessions:
            tag = "e78e" if sid == sem.DEMO else "lotus"
            rb = {r["t"]: r for r in b[sid]["rows"]}
            ra = {r["t"]: r for r in a[sid]["rows"]}
            common = sorted(set(rb) & set(ra))
            for arm_name, rows in (("before", [rb[t] for t in common]), ("after", [ra[t] for t in common])):
                for u in UNIONS + ("self", "ally"):
                    p = pool(rows, u)
                    print(sid, arm_name, u, {k: (round(v, 4) if isinstance(v, float) else v)
                                             for k, v in p.items()})
                    for k in ("precision", "recall", "f1"):
                        if p[k] is not None and (u in ("eligible", "teardrop_only") or k == "precision"):
                            values[f"{tag}_{arm_name}_{u}_{k}"] = round(float(p[k]), 4)
                srcs: dict[str, int] = {}
                for r in rows:
                    for k, v in r["sources"].items():
                        srcs[k] = srcs.get(k, 0) + v
                print(sid, arm_name, "cone sources", srcs)
                for k, v in srcs.items():
                    values[f"{tag}_{arm_name}_src_{k.replace('/', '_')}"] = v
            values[f"{tag}_frames"] = len(common)
            values[f"{tag}_witness_changed"] = sum(1 for t in common if ra[t]["lit"] != rb[t]["lit"])
        print(json.dumps(values, indent=1))
        if args.record:
            from reticle.version import ICON_TEARDROP_VERSION, TEAM_VISION_VERSION
            metrics.record("team_vision_eval", part="joined-team-light", session=f"{sem.DEMO}+{voe.LOTUS}",
                           values=values,
                           deps={"prototype": VERSION, "witness": co.VERSION, "reader": it_.VERSION,
                                 "lighting": lighting.LIGHTING_VERSION, "before": nb, "after": na,
                                 "team_vision": TEAM_VISION_VERSION, "icon_teardrop": ICON_TEARDROP_VERSION,
                                 "warmup_ms_lotus": voe.WARMUP_MS})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
