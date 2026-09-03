"""Cut the actual artwork at every labelled ability, grouped by class, and look at it.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_templates.py <session>... [--zoom 6]

Why this exists, and why it is a RENDER before it is a matcher
---------------------------------------------------------------
Template matching is the agreed direction, and it rests on a premise nobody in
this repo has checked: **that one ability looks the same every time it
appears.** Every generic-feature approach failed (`device_glyph_score`,
`host_span`, aspect, wall-distance, and the sign comparison), and the argument
for matching art instead is that an ability is a fixed asset drawn at a fixed
size. If that premise is false -- if the same ability varies with lighting,
mode, rotation or what it is drawn over -- then a template bank inherits the
same failure and it is better to know that from a picture than from a scored
run three days later.

So this cuts a patch at each of the labelled positives, groups by
`agent:ability`, and renders one row per class. It builds NO templates and
scores nothing. The question it answers is the one that decides whether the next
step is worth taking.

It is also the cheapest possible test of the taxonomy (2026-09-03, recorded
in this directory's CLAUDE.md): abilities are **icons** or **regions**, and a
region will not sit inside a fixed-size patch at all. If the region classes come
out as arbitrary crops of a larger thing while the icon classes come out as
repeatable little pictures, the taxonomy is visible in the rendering and the
bank should be split accordingly.

Reading the sheet
-----------------
One row per ability class, one panel per labelled instance, magnified at a
STATED factor (`glance.py`'s rule -- the artwork is ~12-20 px and a whole frame
downsamples below the point where it can be read). Panels within a row should
look like copies of each other if the premise holds.

What the first sheet showed, 2026-09-03 (5 sessions, 27 objects, 5 classes)
----------------------------------------------------------------------------
**The premise holds for icons, and the taxonomy is visible in the picture.**

* **`cypher:trapwire` (n=10), `deadlock:sonic sensor` (5), `deadlock:barrier
  mesh` (4), `cypher:spycam` (2) are all the same STRUCTURE**: a dark, near-black
  disc carrying white line art. Instances of a class look like copies of each
  other. These are template-able;
* **`brimstone:orbital strike` (n=6) is not an icon at all.** Every panel is a
  fragment of a large translucent red circle overflowing the patch -- an
  arbitrary crop of something much bigger. That is a REGION, and it is why its
  median `dark` excursion is 13 against 95-105 for the others
  (`ability_cone.py`): it is a tint, not ink. It should never have been scored
  in the same pool;
* **rotation is real and it is inside the glyph, not the disc.** The trapwire's
  dumbbell sits at a different angle in nearly every instance while the disc
  around it does not change;
* **modes change colour, not shape.** Both spycam instances are TEAL, not black
  -- they were captured while the player was viewing through the cam (the mechanic
  measured on 2026-09-02, H=76-77). The disc is still a disc.

**So the invariant the player asked for is the DISC**, and the design falls out of it:

    detection   find dark discs of the known radius -- rotation-invariant for
                free, mode-invariant (a teal cam is still a disc), and common to
                all four icon classes
    identity    match the glyph INSIDE the disc against a per-ability bank,
                where rotation has to be handled
    regions     a separate detector with a different primitive. Not this file.

**The quick geometry check is NOT evidence, and is recorded as a caution.**
Measuring the largest dark component per patch gives median equivalent radii of
10.6 / 10.8 / 11.9 / 14.9 px for the four icon classes -- consistent, as the eye
says -- but it gives Orbital Strike 12.3, right among them, so it does not
separate icon from region at all. It is also confounded by `PATCH`: at 14 the
patch is 29 px across and the icons measure ~25 px, so they nearly fill it and
the component is clipped. **Raise `PATCH` before quoting any size from this.**
The sheet is the finding here; the numbers are not ready.
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
from reticle.profiles import get_profile                          # noqa: E402
from ability_eval import label_rows, collapse, STORE              # noqa: E402

#: Half-width of the cut, in minimap pixels. Generous enough to hold an icon
#: plus its surround; a REGION will simply overflow it, which is the point.
PATCH = 14


def cut(sid, rows, patch=PATCH):
    """Add a `_patch` BGR crop to each row, in place."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    cap = cv2.VideoCapture(src["path"])
    byt: dict = {}
    for r in rows:
        byt.setdefault(r["t_ms"], []).append(r)
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        h, w = crop.shape[:2]
        for r in rs:
            x, y = int(r["x"]), int(r["y"])
            x0, y0 = x - patch, y - patch
            # Pad off-source with MAGENTA, never black: `glance.py`'s invariant,
            # so "no data" and "nothing here" cannot be confused by eye.
            p = np.full((2 * patch + 1, 2 * patch + 1, 3), (255, 0, 255), np.uint8)
            sx0, sy0 = max(0, x0), max(0, y0)
            sx1, sy1 = min(w, x0 + 2 * patch + 1), min(h, y0 + 2 * patch + 1)
            if sx1 > sx0 and sy1 > sy0:
                p[sy0 - y0:sy1 - y0, sx0 - x0:sx1 - x0] = crop[sy0:sy1, sx0:sx1]
            r["_patch"] = p
    cap.release()
    return [r for r in rows if "_patch" in r]


def sheet(rows, out: Path, zoom=6):
    """One row per ability class, one panel per instance."""
    byab: dict = {}
    for r in rows:
        k = f"{(r['_agent'] or '?').lower()}:{(r['_ability'] or '?').lower()}"
        byab.setdefault(k, []).append(r)
    n = 2 * PATCH + 1
    cell = n * zoom
    lines = []
    for k, g in sorted(byab.items(), key=lambda kv: -len(kv[1])):
        panels = []
        for r in g[:14]:
            p = cv2.resize(r["_patch"], (cell, cell), interpolation=cv2.INTER_NEAREST)
            cv2.rectangle(p, (0, 0), (cell - 1, cell - 1), (60, 60, 60), 1)
            # Ring the candidate in every panel -- the tile is not the object.
            cv2.circle(p, (cell // 2, cell // 2), int(6 * zoom), (0, 255, 255), 1)
            cv2.putText(p, f"{r['_sid'][:6]} {r['t_ms'] // 1000}s", (3, 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.32, (0, 255, 255), 1, cv2.LINE_AA)
            panels.append(p)
        strip = np.hstack(panels)
        label = np.full((cell, 260, 3), 20, np.uint8)
        cv2.putText(label, k[:30], (6, cell // 2 - 6), cv2.FONT_HERSHEY_SIMPLEX,
                    0.5, (255, 255, 255), 1, cv2.LINE_AA)
        cv2.putText(label, f"n={len(g)}", (6, cell // 2 + 16), cv2.FONT_HERSHEY_SIMPLEX,
                    0.45, (180, 180, 180), 1, cv2.LINE_AA)
        lines.append(np.hstack([label, strip]))
    w = max(l.shape[1] for l in lines)
    grid = np.vstack([np.hstack([l, np.full((l.shape[0], w - l.shape[1], 3), 20, np.uint8)])
                      for l in lines])
    foot = np.full((28, grid.shape[1], 3), 20, np.uint8)
    cv2.putText(foot, f"{zoom}x INTER_NEAREST, {n}px source patch, ring r=6px source; "
                      f"magenta = off-source", (6, 19),
                cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
    grid = np.vstack([grid, foot])
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), grid)
    return out, {k: len(v) for k, v in byab.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--zoom", type=int, default=6)
    ap.add_argument("--all-observations", action="store_true",
                    help="do not collapse to one row per object")
    args = ap.parse_args()

    pool = []
    for sid in args.sessions:
        rows, diag = label_rows(sid)
        pos = [r for r in rows if r["_true"]]
        if not pos:
            print(f"{sid}: no positives")
            continue
        if not args.all_observations:
            pos = [r for r in collapse(pos)]
        pos = cut(sid, pos)
        for r in pos:
            r["_sid"] = sid
        pool += pos
        print(f"{sid}: {len(pos)} patches")

    if not pool:
        raise SystemExit("nothing to render")
    out, counts = sheet(pool, STORE / "glances" / "ability-templates.png", args.zoom)
    print(f"\n   classes: {counts}")
    print(f"   wrote {out}")
    print("   LOOK AT IT. The question is whether panels within a row are copies")
    print("   of each other. If they are, a template bank is worth building; if a")
    print("   class varies, find the invariant part before building one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
