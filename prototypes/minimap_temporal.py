"""Persistence for minimap icons: keep only detections that hold across frames.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_temporal.py <session> [--step 100] [--half 400]

Per-frame ring fitting reaches ~77% recall at ~61% precision on the pre-kill
pool and ~0.3-0.6 false positives per frame. An enemy icon persists; a false
positive -- scenery flickering through the transparent part of the widget, a
momentary ability effect, a scrap of the map edge -- generally does not. That is
the same argument that made `track_filter()` worth 27% of the screen detector's
false positives at zero recall cost.

**It should work better here than it does on screen, for a structural reason.**
The screen tracker had to estimate camera motion by phase correlation and add it
to every prediction, and five attempts at recovering relative motion from a
fragmentary rim all failed because a broken contour's centroid wanders on its
own. The minimap has NO camera motion: Grant runs it fixed rotation, one
orientation, uncentered, so the widget and the map under it are stationary and an
icon moves only as the player moves. `minimap_position.py` already relies on
exactly that -- movement is physically bounded at RUN_PX px/s -- and it is what
made position tracking work where content-based approaches drowned.

So linking here is proximity with a speed bound and nothing else. No camera
estimate, no flow, no sign to get backwards.

Abstaining rather than guessing
-------------------------------
Two conditions make the widget unreadable and both are detected instead of being
tuned through:

* **Omen's ultimate** turns the minimap a fuzzy black for a few seconds, and
  Grant reports it is the only ability in the game that does this -- a bounded
  set, so detecting the *state* needs no ability taxonomy;
* **round transitions** fade the whole frame to black.

Both collapse the floor slab's brightness, and the separation is not marginal:
measured over 1400 frames of `a06f04a0059f`, floor mean is 121 at the median and
131 at p95, against 0-30 on the affected frames, with p01 at 39. `USABLE_MIN`
sits in the empty middle of that gap.

A frame that is unreadable should produce *no answer*, not a confident empty
one -- an enemy is on the minimap during an Omen ult, we simply cannot see it,
and reporting "no icons" there would be a false negative dressed as a fact.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import minimap_ring_fit as rf                                      # noqa: E402
from minimap_icons import floor_mask, static_map                   # noqa: E402
from minimap_icon_eval import hits                                 # noqa: E402
from minimap_ring_sweep import batch_of, load_labels               # noqa: E402

STORE = Path.home() / "reticle-store"
# Player run speed in minimap pixels per second, from minimap_position.py. An
# enemy icon obeys the same bound -- it is the same game moving the same body.
RUN_PX = 45.0
# Floor-slab mean brightness below which the widget is unreadable. The gap it
# sits in is 39 (p01) to 110 (p05), so this is not a tuned edge.
USABLE_MIN = 70.0


def usable(crop, floor):
    """Is the widget readable in this frame? See the module docstring."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    return float(g[floor].mean()) >= USABLE_MIN


def link(per_frame, step_ms, min_len, gate_scale=2.0):
    """Greedy nearest-neighbour tracks with a speed bound.

    Returns, per frame, the indices of detections belonging to a track of at
    least `min_len` observations. Gap tolerance is one frame: the fitter misses
    an icon intermittently and requiring contiguity shreds one icon into several
    short tracks, which is the bug that made the screen tracker report a median
    length of 6 for a detector firing 9 times in 11.
    """
    lim = RUN_PX * (step_ms / 1000.0) * gate_scale
    tracks = []
    for i, dets in enumerate(per_frame):
        if dets is None:                      # unusable frame: break every track
            for t in tracks:
                t["closed"] = True
            continue
        taken = set()
        for t in tracks:
            if t.get("closed"):
                continue
            gap = i - t["last"]
            if gap <= 0 or gap > 2:
                continue
            best, bd = None, lim * gap
            for j, d in enumerate(dets):
                if j in taken:
                    continue
                dist = np.hypot(d["cx"] - t["x"], d["cy"] - t["y"])
                if dist < bd:
                    best, bd = j, dist
            if best is not None:
                taken.add(best)
                t.update(x=dets[best]["cx"], y=dets[best]["cy"], last=i)
                t["idx"][i] = best
        for j, d in enumerate(dets):
            if j not in taken:
                tracks.append({"x": d["cx"], "y": d["cy"], "last": i,
                               "idx": {i: j}})
    keep = [set() for _ in per_frame]
    for t in tracks:
        if len(t["idx"]) >= min_len:
            for i, j in t["idx"].items():
                keep[i].add(j)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--step", type=int, default=100, help="ms between samples")
    ap.add_argument("--half", type=int, default=400, help="ms either side")
    ap.add_argument("--sat", type=int, default=100)
    args = ap.parse_args()

    rows = load_labels(args.session)
    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    x0, y0, x1, y1 = rows[0]["roi"]

    cap = cv2.VideoCapture(str(src["path"]))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    med = []
    for i in np.linspace(0, tot - 1, 150).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            med.append(fr[y0:y1, x0:x1])
    floor = floor_mask(static_map(med))

    offs = list(range(-args.half, args.half + 1, args.step))
    centre = offs.index(0)
    step_f = max(1, int(round(args.step / 1000.0 * fps)))
    span_f = step_f * (len(offs) - 1) + 1

    cache_path = (STORE / "labels" / "minimap" /
                  f"{args.session}.temporal_{args.step}_{args.half}.json")
    cache = json.loads(cache_path.read_text()) if cache_path.is_file() else {}
    todo = [r for r in rows if str(r["t_ms"]) not in cache]
    if todo:
        print(f"decoding {len(todo)} windows ({len(cache)} cached)")
        for n, r in enumerate(todo):
            start = int(round((r["t_ms"] - args.half) / 1000.0 * fps))
            if start < 0:
                continue
            cap.set(cv2.CAP_PROP_POS_FRAMES, start)
            seq = []
            for _ in range(span_f):
                ok, fr = cap.read()
                if not ok:
                    break
                seq.append(fr)
            if len(seq) < span_f:
                continue
            per = []
            for f in seq[::step_f]:
                crop = f[y0:y1, x0:x1]
                per.append(rf.find(crop, floor, args.sat)
                           if usable(crop, floor) else None)
            cache[str(r["t_ms"])] = per
            if (n + 1) % 20 == 0:
                print(f"  ... {n+1}/{len(todo)}", flush=True)
        cache_path.write_text(json.dumps(cache))
    cap.release()

    n_unusable = sum(1 for v in cache.values() if v[centre] is None)
    print(f"\n{len(rows)} labelled frames, window +/-{args.half}ms at {args.step}ms")
    print(f"centre frame unusable (Omen ult / fade) in {n_unusable}")

    for cov, ired in ((0.30, 0.25), (0.35, 0.25), (0.42, 0.25), (0.50, 0.25)):
        print(f"\ncov>={cov} inner_red<={ired}")
        for min_len in (1, 2, 3, 4):
            st = {}
            for r in rows:
                per = cache.get(str(r["t_ms"]))
                if per is None or per[centre] is None:
                    continue
                filt = [None if p is None else
                        [d for d in p if d["cov"] >= cov and d["inner_red"] <= ired]
                        for p in per]
                keep = link(filt, args.step, min_len)
                cs = [{"box": (d["cx"] - d["r"], d["cy"] - d["r"], 2 * d["r"], 2 * d["r"]),
                       "xy": (d["cx"], d["cy"])}
                      for j, d in enumerate(filt[centre]) if j in keep[centre]]
                b = st.setdefault(batch_of(r), dict(tp=0, fn=0, fp=0))
                used = set()
                for m in [m for m in r["marks"] if m["kind"] == "enemy"]:
                    j = next((j for j, c in enumerate(cs)
                              if j not in used and hits(m["x"], m["y"], c)), None)
                    if j is None:
                        b["fn"] += 1
                    else:
                        b["tp"] += 1
                        used.add(j)
                for m in [m for m in r["marks"] if m["kind"] != "enemy"]:
                    j = next((j for j, c in enumerate(cs)
                              if j not in used and hits(m["x"], m["y"], c)), None)
                    if j is not None:
                        used.add(j)
                b["fp"] += len(cs) - len(used)
            parts = []
            for name in sorted(st):
                s = st[name]
                if not (s["tp"] + s["fn"]):
                    continue
                parts.append(f"{name}: R {s['tp']/max(s['tp']+s['fn'],1)*100:5.1f}% "
                             f"P {s['tp']/max(s['tp']+s['fp'],1)*100:5.1f}% "
                             f"(TP{s['tp']:3d} FN{s['fn']:3d} FP{s['fp']:3d})")
            print(f"  len>={min_len}  " + "   ".join(parts))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
