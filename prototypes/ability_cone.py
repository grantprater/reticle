"""Measure the residual against the state a pixel SHOULD be in, not against the interval it may be in.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_cone.py <session>... [--cone]

The defect this attacks
------------------------
`minimap_dynamic.detect` calls a pixel dynamic only when it falls OUTSIDE the
interval its two legitimate resting colours span:

    raw = max(lo - g, g - hi, 0)

That was the right fix for the thing it was built for -- a cone edge sweeping a
pixel passes through intermediate values, and the earlier "far from the nearer
reference" test flagged those transition midpoints as dynamic. But it buys that
at a price nobody had measured: **ink drawn on LIT ground can land inside
[lo, hi] and become invisible.** `lo` is the unlit resting value, and a glyph
over lit floor need only be darker than *lit* floor, not darker than *unlit*
floor. Both excursions are then zero and the icon is not dynamic at all.

That is the mechanism behind `ability_signed.py`'s measured failure. Per object,
`dark > bright` holds for 100% of Cypher trapwires (median dark 102, bright 10 --
they sit on unlit floor) and only 60% of Deadlock sonic sensors (median dark 105
**and** bright 101 -- ink and lift in the same window).

The fix, and why it is not the raycast
---------------------------------------
If you know which state a pixel *should* be resting in, you compare against a
SINGLE reference instead of an interval, and ink on lit ground reads as a full
`hi - g` excursion instead of vanishing.

The principled source for that is `minimap_cone.py`'s raycast. It is not the
practical one: its own docstring records a usable facing fit on **4 of 50** real
candidate positions, because `LOBE_MIN_FRAC` refuses to guess a bearing. A
mechanism that answers on 8% of frames cannot be the shipped one. `--cone`
measures it anyway, on whatever subset it does answer for, because "the cone is
better where it works" and "the cone is usable" are different claims and only
the second one is a plan.

The practical source is **the local background**. A viewcone is large and smooth;
an ability icon is small. So a heavy median filter estimates what the map under
this pixel looks like without the icon, and whichever resting state that
estimate is nearer is the state the pixel should be in. That is the same
reasoning that set `minimap_dynamic.TOPHAT_K = 31` -- a kernel larger than an
icon and smaller than a viewcone -- reused to pick a REFERENCE rather than to
subtract a background.

    B        = median(g, BG_K)              the map without the icon
    lit      = |B - hi| < |B - lo|          which state that implies
    expected = hi where lit, else lo
    dark_e   = max(expected - g, 0)         ink, measured against the right state
    bright_e = max(g - expected, 0)

`dark_e` is the quantity `dark` was trying to be. Note it is strictly more
permissive than the interval test, so it must be paired with a floor -- it is
not a drop-in replacement for `detect`'s gate, it is a better FEATURE for
scoring a candidate that some other gate has already proposed.

What it found, 2026-09-03: the diagnosis is right and the fix does not work
--------------------------------------------------------------------------
**The mechanism is confirmed. 6 of 22 labelled positives (27%) are invisible to
the interval test at their own pixel** -- both excursions exactly zero, so
`detect` cannot see them however the threshold is set. 12 of 22 stand on ground
the background estimate calls lit. That is a real, previously unmeasured hole in
the two-state gate.

**Changing the reference does not close it.** Neither alternative dominates the
plain interval residual, over 22 objects and 90 negatives:

    rule                       recall   precision
    dark   >= 10  (interval)    95.5%     43.8%
    dark_e >= 10  (expected)   100.0%     35.5%
    dark_e >= 46  (expected)    77.3%     38.6%

and on the 92 objects the raycast answered for, at matched recall:

    dark_c >= 30  (raycast)     93.8%     34.1%
    dark   >= 10  (interval)    93.8%     38.5%

The reason is simple and should have been predictable: a more permissive
reference lifts the noise as much as the signal. `dark_e` sees the 27% the
interval misses, and it also sees more of the map, so the threshold that
controls false positives rises to 46 and starts cutting real objects.

**What the class breakdown says instead, and this is the finding worth keeping:**

    ability                    n   median dark
    deadlock:sonic sensor      5           105
    cypher:trapwire            7           102
    deadlock:barrier mesh      4            95
    brimstone:orbital strike   6            13

**The classes differ by ~8x in contrast.** Brimstone's Orbital Strike marker is
faint by construction -- it was already measured at gray 114 against an unlit
reference of 117 -- and any global floor tuned to keep the three strong classes
deletes it (17% recall at `dark_e >= 46`). This is not a reference problem and
it is not a threshold that needs better fitting. **A single absolute floor
cannot serve this class list**, which is the same conclusion CLAUDE.md reaches
about every absolute level tested against this HUD. The next thing to try is
normalising the excursion by the LOCAL NOISE -- the per-pixel temporal SD map
already measured (7.4 on white lines, 16.9 on the slab, 42.5 in the void) --
so that "faint against quiet ground" and "strong against noisy ground" can both
pass.

Incidental correction, and it reopens a parked line
-----------------------------------------------------
**The vision cone is usable far more often than recorded.** `prototypes/
CLAUDE.md` says `icon_facing` returned a usable cone on **4 of 50** candidate
positions and concludes the cone "is not yet a tool you can point at an
arbitrary frame and expect an answer from". Seeding `minimap_cone.self_cone`
from the largest ring `reticle.minimap.self_rings` returns:

    2ba870ccbd50   22/22 frames   100%
    79a706a7ce4c   54/55           98%
    a06f04a0059f   40/42           95%
    eb10db50b1fb   18/32           56%     <- the session 4-of-50 was measured on

89% pooled. Even on the session that produced the original figure the yield is
56%, not 8%, so the difference is in how the fit is SEEDED rather than in
`LOBE_MIN_FRAC` refusing. That matters beyond this file: the two parked
hypotheses -- cone-termination proximity and local sliver/thinness -- were
shelved *because* of the yield, and they are affordable again.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import metrics                                       # noqa: E402
from reticle import geometry as _G                                  # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from reticle import minimap as mm                                 # noqa: E402
from ability_eval import label_rows, collapse, _sha, STORE        # noqa: E402
from minimap_icons import floor_mask                              # noqa: E402
import minimap_cone as mc                                         # noqa: E402

#: Median kernel for the background estimate. Larger than an icon, smaller than
#: a viewcone -- the same bound that sets `minimap_dynamic.TOPHAT_K`.
BG_K = 31

#: Half-width of the sampling window, matching `ability_signed.WIN` so the two
#: measurements are comparable.
WIN = 2


def expected_state(g, lo, hi, bg_k=BG_K):
    """Per-pixel expected resting value, and the lit mask that chose it."""
    b = cv2.medianBlur(g.astype(np.uint8), bg_k).astype(np.int16)
    lit = np.abs(b - hi) < np.abs(b - lo)
    return np.where(lit, hi, lo).astype(np.int16), lit


def features_at(sid, rows, use_cone=False):
    """Add interval and expected-state excursions to each row, in place.

    Both are read as a max over the same window, so the only thing that differs
    between `dark` and `dark_e` is what they are measured AGAINST.
    """
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    z = np.load(_G.require(sid, STORE))
    lo, hi = z["lo_gray"].astype(np.int16), z["hi_gray"].astype(np.int16)
    labels, static = z["labels"], z["static"]
    floor = floor_mask(static, dilate=1)

    cap = cv2.VideoCapture(src["path"])
    byt: dict = {}
    for r in rows:
        byt.setdefault(r["t_ms"], []).append(r)
    n_cone = 0
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.int16)
        if g.shape != lo.shape:
            break
        exp, lit = expected_state(g, lo, hi)

        cone = None
        if use_cone:
            rings = mm.self_rings(crop, floor)
            if rings:
                _a, sx, sy = max(rings, key=lambda r: r[0])
                try:
                    cone = mc.self_cone(crop, floor, labels, int(sx), int(sy))
                except Exception:
                    cone = None
            if cone is not None:
                n_cone += 1
                exp_c = np.where(cone, hi, lo).astype(np.int16)

        dark_i = np.maximum(lo - g, 0)
        bright_i = np.maximum(g - hi, 0)
        dark_e = np.maximum(exp - g, 0)
        bright_e = np.maximum(g - exp, 0)
        for r in rs:
            x, y = int(r["x"]), int(r["y"])
            sl = (slice(max(0, y - WIN), y + WIN + 1),
                  slice(max(0, x - WIN), x + WIN + 1))
            r["dark"] = int(dark_i[sl].max())
            r["bright"] = int(bright_i[sl].max())
            r["dark_e"] = int(dark_e[sl].max())
            r["bright_e"] = int(bright_e[sl].max())
            # Pixel-exact interval test: is this position invisible to `detect`?
            r["inside_interval"] = bool(dark_i[y, x] == 0 and bright_i[y, x] == 0)
            r["lit"] = bool(lit[y, x])
            if use_cone and cone is not None:
                dc = np.maximum(exp_c - g, 0)
                r["dark_c"] = int(dc[sl].max())
                r["cone_ok"] = True
            else:
                r["cone_ok"] = False
    cap.release()
    return [r for r in rows if "dark_e" in r], n_cone, len(byt)


def sc(name, rows, keep):
    tp = sum(1 for r in rows if r["_true"] and keep(r))
    fp = sum(1 for r in rows if not r["_true"] and keep(r))
    fn = sum(1 for r in rows if r["_true"] and not keep(r))
    rec = tp / (tp + fn) if (tp + fn) else float("nan")
    pr = tp / (tp + fp) if (tp + fp) else float("nan")
    print(f"   {name:<40} TP {tp:3d} FP {fp:3d}  recall {rec * 100:5.1f}%  "
          f"prec {pr * 100:5.1f}%")
    return {"tp": tp, "fp": fp, "recall": round(rec, 4), "precision": round(pr, 4)}


def at_matched_precision(rows, field, target_fp):
    """Highest recall this field reaches without exceeding `target_fp` false
    positives. Comparing two features at a matched FP count is the only way to
    say one is better; comparing their best F1 points compares two different
    operating points."""
    best = None
    for T in range(0, 201, 2):
        fp = sum(1 for r in rows if not r["_true"] and r.get(field, 0) >= T)
        if fp <= target_fp:
            tp = sum(1 for r in rows if r["_true"] and r.get(field, 0) >= T)
            pos = sum(1 for r in rows if r["_true"])
            if best is None or tp > best[1]:
                best = (T, tp, fp, tp / pos if pos else float("nan"))
    return best


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--cone", action="store_true",
                    help="also try the raycast reference where facing fits")
    ap.add_argument("--by-position", action="store_true", default=True)
    args = ap.parse_args()

    pool, cone_ok, cone_tot = [], 0, 0
    for sid in args.sessions:
        rows, diag = label_rows(sid)
        if diag["n_pos"] == 0:
            print(f"=== {sid} === no positives")
            continue
        rows, nc, nt = features_at(sid, rows, args.cone)
        cone_ok += nc
        cone_tot += nt
        if args.by_position:
            rows = collapse(rows)
        for r in rows:
            r["_sid"] = sid
        pool += rows
        print(f"=== {sid} ===  {sum(1 for r in rows if r['_true'])} real, "
              f"{sum(1 for r in rows if not r['_true'])} not")

    pos = [r for r in pool if r["_true"]]
    neg = [r for r in pool if not r["_true"]]
    print(f"\n=== POOLED ===  {len(pos)} real objects, {len(neg)} not")

    inside = sum(1 for r in pos if r["inside_interval"])
    print(f"\n   positives INVISIBLE to the interval test at their own pixel: "
          f"{inside}/{len(pos)} ({inside / len(pos) * 100:.0f}%)")
    print(f"   positives on ground the background estimate calls LIT: "
          f"{sum(1 for r in pos if r['lit'])}/{len(pos)}")

    if args.cone:
        print(f"\n   cone raycast usable on {cone_ok}/{cone_tot} frames "
              f"({cone_ok / max(1, cone_tot) * 100:.0f}%)")

    print("\n   operating points, objects:")
    sc("no filter", pool, lambda r: True)
    sc("dark > bright        (interval)", pool, lambda r: r["dark"] > r["bright"])
    sc("dark_e > bright_e    (expected)", pool, lambda r: r["dark_e"] > r["bright_e"])
    for T in (10, 20, 30, 50):
        sc(f"dark   >= {T:<3}         (interval)", pool, lambda r, T=T: r["dark"] >= T)
    for T in (10, 20, 30, 50):
        sc(f"dark_e >= {T:<3}         (expected)", pool, lambda r, T=T: r["dark_e"] >= T)

    if args.cone:
        sub = [r for r in pool if r.get("cone_ok")]
        sp = sum(1 for r in sub if r["_true"])
        print(f"\n   RAYCAST reference, on the {len(sub)} objects it answered for "
              f"({sp} real):")
        if sp:
            for T in (10, 20, 30, 50):
                sc(f"dark_c >= {T:<3}         (raycast)", sub,
                   lambda r, T=T: r.get("dark_c", 0) >= T)
            print("   the same objects under the other two references, for comparison:")
            for T in (10, 46):
                sc(f"dark   >= {T:<3}         (interval)", sub,
                   lambda r, T=T: r["dark"] >= T)
                sc(f"dark_e >= {T:<3}         (expected)", sub,
                   lambda r, T=T: r["dark_e"] >= T)

    print("\n   matched-precision comparison (same FP budget, best recall):")
    for fpb in (20, 27, 40):
        a = at_matched_precision(pool, "dark", fpb)
        b = at_matched_precision(pool, "dark_e", fpb)
        if a and b:
            print(f"      <= {fpb:3d} FP:  dark >= {a[0]:3d} -> recall {a[3] * 100:5.1f}%   |   "
                  f"dark_e >= {b[0]:3d} -> recall {b[3] * 100:5.1f}%")

    print("\n   per ABILITY CLASS, recall of each rule at its own <=27 FP point:")
    ta = at_matched_precision(pool, "dark", 27)
    tb = at_matched_precision(pool, "dark_e", 27)
    byab: dict = {}
    for r in pos:
        byab.setdefault(f"{(r['_agent'] or '?').lower()}:{(r['_ability'] or '?').lower()}",
                        []).append(r)
    print(f"   {'ability':<28}{'n':>4}{'interval':>10}{'expected':>10}"
          f"{'med dark':>10}{'med dark_e':>12}")
    for k, g in sorted(byab.items(), key=lambda kv: -len(kv[1])):
        ra = sum(1 for r in g if r["dark"] >= ta[0]) / len(g)
        rb = sum(1 for r in g if r["dark_e"] >= tb[0]) / len(g)
        print(f"   {k:<28}{len(g):>4}{ra * 100:>9.0f}%{rb * 100:>9.0f}%"
              f"{int(np.median([r['dark'] for r in g])):>10}"
              f"{int(np.median([r['dark_e'] for r in g])):>12}")

    got = sc("\n   RECORDED: dark_e >= %d" % tb[0], pool,
             lambda r: r["dark_e"] >= tb[0])
    metrics.record(
        "ability_cone", part="objects", session="+".join(args.sessions),
        values=got,
        deps={"features": metrics.fingerprint(expected_state, features_at, BG_K=BG_K,
                                              WIN=WIN),
              "rule": f"dark_e>={tb[0]}", "unit": "objects",
              "labels_sha": "+".join(
                  _sha(STORE / "labels" / "ability" / f"{s}.jsonl")
                  for s in args.sessions)},
        context={"n_pos": len(pos), "n_neg": len(neg)},
    )
    print()
    print(metrics.report(tool="ability_cone"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
