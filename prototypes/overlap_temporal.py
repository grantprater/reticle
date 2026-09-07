r"""Is an overlap TRANSIENT? the claim, tested before anything is built on it.

    .\.venv\Scripts\python.exe prototypes\overlap_temporal.py <session> [--n 8]

Recorded 2026-09-06: :

> For truly overlapping icons, in the vast majority of cases there was probably
> an instant where they were not overlapping. This is how we can get a
> causal/temporal model to have much higher accuracy than a naive snapshot
> model.

If that holds it reframes the grouping problem entirely. `widget_objects.py`
measured, three ways, that **no per-object shape feature separates a ping from
an ally icon at any grouping distance** -- n_fragments, extent and area all
overlap -- and concluded the answer has to come from constraints rather than
appearance. This is a third source: not appearance, not constraints, but TIME.
A ping is placed ON a teammate, so the two collide in space; but the ping
*arrives*, and before it arrived the ally was alone on those pixels.

Why it is worth testing rather than assuming
----------------------------------------------
It is the most attractive kind of claim -- it explains a measured failure, it
costs nothing to believe, and it would justify a lot of building. This repo's
own judgement log says claims at that level (`ontology`) score 0.38 accuracy
with a -0.46 confidence gap and cost a session each when wrong. So it gets a
measurement first, and the measurement has to be able to say NO.

What is measured
----------------
For each stored ping event, decode a window around its onset and, at every
sampled frame, find the object nearest the event's position and record its
EXTENT. The prediction is specific and falsifiable:

* if the overlap is transient, extent over the window is BIMODAL -- small while
  the ally is alone, large once the ping lands on it -- so `max - min` is large
  and the small values cluster before onset;
* if the two are simply always coincident, extent is flat across the window and
  the temporal idea buys nothing here.

`sep_frac` is the share of sampled frames whose object is within 1.4x of the
window's smallest -- i.e. how much of the window offers a clean look. That is
the number a labelling pass would actually spend: a pass that shows the player the
separated instant instead of the merged one is asking an easier question about
the same objects.

**A caveat that must not be dropped**: the object nearest a position is not
necessarily the same object across frames. Nothing here does identity, so a
small extent could be a DIFFERENT nearby object rather than the same one seen
alone. That is why the render exists -- the numbers say where to look and the
picture says whether it is the same thing.

RESULT, 2026-09-06 on 587c15b07779, 10 events, +/-3s at 100 ms
---------------------------------------------------------------
**The claim holds on this population.**

    extent max/min over the window   median 4.75   range 1.60 - 51.62
    frames offering a clean look     median 12%
    events with ratio >= 3.0         9 of 10

Only event #9 (ratio 1.60) is the always-coincident case where time buys
nothing. Nine of ten spend part of the window separated, and roughly one
sampled frame in eight is a clean look at the same position.

Rendered for event #7 (ratio 19.00) and it is visible rather than inferred:
two teal ally icons are ONE object at onset (extent 36) and TWO objects
0.3 s later (extent 16, then 14). Same pixels, same pair, an easier question
one third of a second away.

Two things the render also showed, neither weakening the result: that event is
probably one of the ping/ally false positives `ping_match_eval` counted (what
is pictured is ally icons, not a ping), and the middle of its window is a
widget-absent stretch that `drawn()` would refuse.

**The consequence for the plan is a re-ordering, not a tweak.** A grouping
labelling pass over single frames asks the hardest available version of the
question, and the answer is often on screen a fraction of a second away. So
identity across frames -- the motion model, plan item 07 -- is a PREREQUISITE
for the grouping pass rather than a successor to it, and the pass should
present a WINDOW and let the player answer at the instant the objects are apart.

What this does NOT establish: that the small-extent object is the same object,
which needs the tracker that does not exist yet. The measurement is consistent
with transient overlap and equally consistent with a large dynamic region (a
viewcone) sweeping past a stationary icon -- and note those are the same
phenomenon from the labelling pass's point of view, since both make the clean
instant the one worth asking about.
"""
from __future__ import annotations

import argparse
import io
import contextlib
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
with contextlib.redirect_stdout(io.StringIO()):
    import minimap_dynamic as md
    import widget_objects as wo
from reticle.decode import sample_at                             # noqa: E402
from reticle.minimap import floor_mask, minimap_roi_px, widget_scale  # noqa: E402
from reticle.profiles import get_profile                         # noqa: E402
from reticle.store import Store                                  # noqa: E402

#: Window around an event's onset, ms. Wide enough to hold the before-state:
#: a ping's lifetime is 7.0 s (10.0 s for danger), so 3 s before onset is
#: comfortably outside the previous one and inside the same round.
BEFORE_MS, AFTER_MS, STEP_MS = 3000, 1000, 100
#: An object counts as SEPARATED when its extent is within this factor of the
#: smallest seen in the window. Not a detector threshold -- it only decides
#: what gets counted as "a clean look" in the reported fraction.
SEP_FACTOR = 1.4


def objects_near(crop, floor, free, xy, scale):
    """The object nearest `xy`, or None. No identity across frames -- see the
    caveat in the module docstring."""
    objs = wo.group(wo.segment(crop, floor, free), scale, wo.GAP_PX)
    if not objs:
        return None
    x, y = xy
    return min(objs, key=lambda o: (o.centroid[0] - x) ** 2
                                   + (o.centroid[1] - y) ** 2)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=8, help="events to test")
    ap.add_argument("--free", action="store_true",
                    help="fuse the colour-free channel too")
    ap.add_argument("--render", metavar="DIR")
    a = ap.parse_args(argv)

    store = Store()
    man = store.read_manifest(a.session)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
    floor = floor_mask(store.read_static_map(a.session))
    scale = widget_scale(x1 - x0)

    free_ctx = None
    if a.free:
        labels, gstatic = md.load_geometry(a.session)
        sgray = cv2.cvtColor(gstatic, cv2.COLOR_BGR2GRAY).astype(np.int16)
        ok = md.searchable(labels, static=gstatic)
        lo, hi = md.load_two_state(a.session)
        if lo is not None:
            sgray, hi = lo.astype(np.int16), hi.astype(np.int16)
        free_ctx = (sgray, ok, hi)

    rows = store.read_events("ping", a.session)
    if not rows:
        raise SystemExit(f"no ping events -- run `reticle scan {a.session}`")
    rows = rows[:a.n]

    times = []
    for r in rows:
        t = r["t_ms"]
        times += [t - BEFORE_MS + k * STEP_MS
                  for k in range((BEFORE_MS + AFTER_MS) // STEP_MS + 1)]
    frames = {}
    for smp in sample_at(src["path"], sorted(set(times)), float(src["fps"])):
        frames[round(smp.t_ms / STEP_MS)] = smp.frame[y0:y1, x0:x1].copy()

    print(f"{len(rows)} events, +/-{BEFORE_MS}/{AFTER_MS} ms at {STEP_MS} ms, "
          f"colour-free {'ON' if a.free else 'off'}\n")
    print(f"{'#':>3} {'kind':<12}{'extent min':>11}{'max':>6}{'at onset':>10}"
          f"{'ratio':>7}{'sep_frac':>10}")
    ratios, sep_fracs = [], []
    for i, r in enumerate(rows):
        ext, at_onset = [], None
        for k in range((BEFORE_MS + AFTER_MS) // STEP_MS + 1):
            t = r["t_ms"] - BEFORE_MS + k * STEP_MS
            f = frames.get(round(t / STEP_MS))
            if f is None:
                continue
            free = None
            if free_ctx is not None:
                sg, ok, hi = free_ctx
                free = md.dynamic_mask(f, sg, ok, md.DIFF_MIN,
                                       static_gray2=hi.astype(np.int16)
                                       if hi is not None else None)
            o = objects_near(f, floor, free, (r["x"], r["y"]), scale)
            if o is None:
                continue
            ext.append(o.extent)
            if t >= r["t_ms"] and at_onset is None:
                at_onset = o.extent
        if len(ext) < 5:
            print(f"{i:>3} {r['kind']:<12}  too few frames")
            continue
        lo_e, hi_e = min(ext), max(ext)
        ratio = hi_e / max(1, lo_e)
        sep = sum(1 for e in ext if e <= lo_e * SEP_FACTOR) / len(ext)
        ratios.append(ratio)
        sep_fracs.append(sep)
        print(f"{i:>3} {r['kind']:<12}{lo_e:>11}{hi_e:>6}"
              f"{'-' if at_onset is None else at_onset:>10}{ratio:>7.2f}"
              f"{sep * 100:>9.0f}%")

    if ratios:
        ratios.sort()
        print(f"\nextent max/min over the window: median {ratios[len(ratios)//2]:.2f}, "
              f"range {ratios[0]:.2f}-{ratios[-1]:.2f}")
        print(f"frames offering a clean look:   median "
              f"{sorted(sep_fracs)[len(sep_fracs)//2] * 100:.0f}%")
        print("\nA ratio near 1.0 on most events would FALSIFY the claim for "
              "this population:\nthe objects would be coincident throughout "
              "and time would buy nothing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
