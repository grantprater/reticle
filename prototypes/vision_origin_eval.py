r"""Score `team_vision`'s self cone against the drawn light joined to the self icon.

    .\.venv\Scripts\python.exe prototypes\vision_origin_eval.py --arm before|after [--compare]

The measurement behind `team-vision-0.2.0`, which casts the self cone from the
teardrop's centre (`reticle.teardrop`) instead of the ring fit's centre. E4 of
[the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md) found the
rays start at the teardrop's centre with no offset; this checks that the
promoted chain reproduces the gain on the same frames.

**The chain is the owner's.** Each arm drives `team_vision.TeamVision` over
the frames as the code on disk has it -- `before` on master's code, `after` on
the branch -- and scores the self cone it cast: `cone.observable` on the self
entry of `resolved`, from the origin the frame reports (`VisionFrame.origins`
where present, the track's position otherwise).

**The witness is E4's and does not move between arms**: the prototype
teardrop fit (`teardrop_tip.fit`, seeded from the best self detection) places
the icon's footprint, and `cone_origin.joined` keeps the lit components that
touch a band round it, within 90 px, on known floor, outside the footprint.
Frames need a read teardrop and at least `cone_origin.MIN_LIT` joined pixels;
consecutive identical fits collapse. Precision, recall and F1 pool pixels over
frames. A frame whose self cone is refused counts its light in recall.

Frames: `e78e75b2d191`, every cached frame through one chain, scored on E4's
held-out odd 3 s blocks outside the sliver neighbourhoods; `5822b6646448`,
E4's twenty 6 s windows through `team_vision.at` with a 10 s warm-up. It reads
the minimap crop cache only, decodes no video, and writes to the store only
with `--compare` (one `metrics` row).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import cone_origin as co  # noqa: E402
import teardrop_tip as tt  # noqa: E402
from reticle import cone, lighting, metrics, team_vision  # noqa: E402

VERSION = "vision-origin-eval-0.1.0"
LOTUS = "5822b6646448"
WARMUP_MS = 10000.0


def frames_of(s: sem.Session, sid: str):
    """`[(t, crop, VisionFrame)]` for the arm's frame set."""
    x0, y0, x1, y1 = s.box
    if sid == sem.DEMO:
        chain = team_vision.TeamVision.from_inputs(s.inputs, distance_diagnostics=False)
        out = []
        for smp in s.cache.samples([float(t) for t in s.cache_t], rois=["minimap"]):
            crop = smp.frame[y0:y1, x0:x1]
            fr = chain.step(crop, smp.t_ms)
            t = float(smp.t_ms)
            if (t // co.BLOCK_MS) % 2 == 1 and all(abs(t - h) > sem.HOLDOUT_MS for h in sem.SLIVERS):
                out.append((t, crop.copy(), fr))
        return out
    times = sorted(float(t) for _, sel in co.windows(s) for t in sel)
    got = team_vision.at(s.cache, s.inputs, times, warmup_ms=WARMUP_MS, distance_diagnostics=False)
    want = set(times)
    frames = {float(fr.t_ms): fr for _, fr in got if float(fr.t_ms) in want}
    return [(t, crop.copy(), frames[t]) for t, crop in s.crops(sorted(frames))]


def self_cone(s: sem.Session, fr):
    """The self cone the frame cast, its origin source, or (None, reason)."""
    if fr.widget != "drawn":
        return None, "widget_" + fr.widget
    idx = [i for i, (role, _tr) in enumerate(fr.tracked) if role == "self"]
    if not idx:
        return None, "no_self_track"
    i = idx[0]
    x, y, deg, _c = fr.resolved[i]
    if deg is None:
        return None, "bearing_refused"
    origins = getattr(fr, "origins", None)
    ox, oy = (origins[i][0], origins[i][1]) if origins else (x, y)
    src = origins[i][2] if origins else "ring_fit"
    _agg, per = cone.observable(s.passable, [(ox, oy, deg)], visible=s.floor)
    return per[0], src


def arm(sid: str) -> dict:
    s = sem.Session(sid)
    rows, prev, why = [], None, {}
    for t, crop, fr in frames_of(s, sid):
        det = tt.self_start(crop, s.floor)
        tf = tt.fit(crop, det["cx"], det["cy"]) if det else None
        if not tf or not tf.get("read"):
            why["teardrop_unread"] = why.get("teardrop_unread", 0) + 1
            continue
        key = (round(tf["x"], 3), round(tf["y"], 3), round(tf["deg"], 2))
        if key == prev:
            continue
        prev = key
        raw = lighting.raw_lit(crop, s.ref)
        reg = co.region_of(s, tf)
        wit = co.joined(raw, reg, tf)
        if int(wit.sum()) < co.MIN_LIT:
            why["little_light"] = why.get("little_light", 0) + 1
            continue
        m, src = self_cone(s, fr)
        if m is None:
            why[src] = why.get(src, 0) + 1
            rows.append({"t": t, "cast": False, "src": src, "hits": 0, "n": 0, "lit": int(wit.sum())})
            continue
        rows.append({"t": t, "cast": True, "src": src, "hits": int((m & wit).sum()),
                     "n": int((m & reg).sum()), "lit": int(wit.sum())})
    return {"rows": rows, "why": why}


def pool(rows) -> dict:
    h = sum(r["hits"] for r in rows)
    n = sum(r["n"] for r in rows)
    lit = sum(r["lit"] for r in rows)
    return {"frames": len(rows), "precision": h / n if n else None,
            "recall": h / lit if lit else None, "f1": 2 * h / (n + lit) if (n + lit) else None}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--arm", choices=("before", "after"))
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--out", type=Path, default=Path(sem.tempfile.gettempdir()) / "vision-origin")
    ap.add_argument("--sessions", nargs="+", default=[sem.DEMO, LOTUS])
    args = ap.parse_args(argv)
    sem._below_normal()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.arm:
        res = {sid: arm(sid) for sid in args.sessions}
        (args.out / f"{args.arm}.json").write_text(json.dumps(res), encoding="utf-8")
        for sid, r in res.items():
            print(args.arm, sid, pool(r["rows"]), "skipped", r["why"],
                  "origins", {k: sum(1 for x in r["rows"] if x["src"] == k)
                              for k in {x["src"] for x in r["rows"]}}, flush=True)
    if args.compare:
        b = json.loads((args.out / "before.json").read_text(encoding="utf-8"))
        a = json.loads((args.out / "after.json").read_text(encoding="utf-8"))
        values = {}
        for sid in args.sessions:
            tag = "e78e" if sid == sem.DEMO else "lotus"
            rb = {r["t"]: r for r in b[sid]["rows"]}
            ra = {r["t"]: r for r in a[sid]["rows"]}
            common = sorted(set(rb) & set(ra))
            both = [t for t in common if rb[t]["cast"] and ra[t]["cast"]]
            for name, rows in (("before", [rb[t] for t in common]), ("after", [ra[t] for t in common]),
                               ("before_cast", [rb[t] for t in both]), ("after_cast", [ra[t] for t in both])):
                p = pool(rows)
                print(sid, name, p)
                for k in ("precision", "recall", "f1", "frames"):
                    if p[k] is not None:
                        values[f"{tag}_{name}_{k}"] = round(float(p[k]), 4)
            # The witness depends on the crop and the teardrop fit only; its size
            # must not move between arms.
            values[f"{tag}_witness_changed"] = sum(1 for t in common if ra[t]["lit"] != rb[t]["lit"])
            values[f"{tag}_after_teardrop_origin"] = sum(1 for t in common if ra[t]["src"] == "teardrop")
            values[f"{tag}_after_fallback_origin"] = sum(1 for t in common if ra[t]["src"] == "ring_fit")
        print(json.dumps(values, indent=1))
        from reticle.version import TEAM_VISION_VERSION
        metrics.record("vision_origin_eval", part="joined-light", session=f"{sem.DEMO}+{LOTUS}",
                       values=values,
                       deps={"prototype": VERSION, "witness": co.VERSION, "reader": tt.VERSION,
                             "lighting": lighting.LIGHTING_VERSION, "before": "team-vision-0.1.0",
                             "after": TEAM_VISION_VERSION, "warmup_ms_lotus": WARMUP_MS,
                             "fact": "minimap/cone-origin-near-centre"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
