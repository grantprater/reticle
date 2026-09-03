"""Find the dark disc every ability ICON is drawn on, and score it as a candidate proposer.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_disc.py <session>... [--sweep]

Why a disc, and why this is the detector rather than another feature
---------------------------------------------------------------------
`ability_templates.py` rendered the real artwork at every labelled ability and
the answer was structural: `cypher:trapwire`, `cypher:spycam`,
`deadlock:sonic sensor` and `deadlock:barrier mesh` are all **a near-black disc
carrying white line art**. The two things that vary between instances of a class
vary INSIDE the disc, not in it:

* **rotation** -- the trapwire's dumbbell sits at a different angle nearly every
  time, while the disc around it does not change;
* **mode** -- both spycam instances are TEAL rather than black, captured while
  the player was viewing through the cam, and the disc is still a disc.

So the disc is the invariant the player asked for, and it splits the problem the way
every earlier attempt failed to: **detect the disc (rotation-free, mode-free,
common to all four icon classes), then identify by the glyph inside.**
`brimstone:orbital strike` is deliberately NOT a target here -- it is a REGION,
a large translucent tint, and pooling it with icons is what dragged every
threshold in `ability_cone.py` around.

The primitive: a black-hat, not a threshold
--------------------------------------------
Two thresholding attempts were tried while measuring the disc and both failed
the same way: Otsu inside a patch merges the icon with any adjacent dark map,
returning a "disc" the size of the whole patch. That is not a tuning problem. The
minimap has plenty of large dark areas -- the void, shadowed geometry -- so
**no global level distinguishes a small dark disc from a big dark region.**

A **black-hat** does, by construction:

    blackhat = closing(g, K) - g

It responds only to dark structures SMALLER than the structuring element, and it
measures them against their own local surroundings. Three things follow, and
each one is a defect in the existing channel that this removes rather than tunes:

* it is **relative**, so it never becomes an absolute level tested against a HUD
  composited over live scenery -- CLAUDE.md's one never-wrong rule;
* it is **scale-selective**, so a large dark region cannot masquerade as an icon
  and the icon cannot merge into one. Same bound that sets `TOPHAT_K`: larger
  than an icon, smaller than a viewcone;
* it is **immune to the viewcone**, because a cone is a large-scale BRIGHT
  feature and a black-hat only sees small dark ones. That is the direct fix for
  the hole `ability_cone.py` measured -- **27% of labelled positives are
  invisible to `detect`'s two-state interval test** because ink on lit ground can
  fall inside `[lo, hi]`. A black-hat never asks what state the pixel should
  rest in, so the question does not arise.

How it is scored, and the one thing this evaluation CANNOT say
---------------------------------------------------------------
Labels exist only at positions the OLD detector proposed, so:

* **recall is honest** -- a labelled real object is real whoever proposed it, so
  "did this detector fire within `MATCH_PX` of it" is a fair question;
* **hits on labelled negatives are honest** -- does it re-propose the known junk;
* **precision is NOT measurable here.** A detection somewhere nobody has labelled
  is unscored. Stream size (candidates per frame) is the proxy, and a small
  stream at full recall is suggestive, not proof.

The way to close that gap is a fresh labelling pass over THIS stream, which is
the loop `review_candidates.py` + `label_ability.py` already implement. Do not
quote a precision figure from this file.

What it does, 2026-09-03 (4 sessions, 21 icon objects, 92 known negatives)
---------------------------------------------------------------------------
At `k=27, blackhat >= 130`:

    recall                 85.7%  (18/21)
    known negatives re-proposed   10/92  (11%)
    candidates per frame          2.4    against detect's 6.8

    by class:  sonic sensor 5/5   barrier mesh 4/4
               trapwire     8/10  spycam       1/2

**The stream is 2.8x smaller than `minimap_dynamic.detect`'s at higher recall on
the icon classes**, which is the point: this is meant to hand identification a
pool that is mostly signal rather than a pool that needs four more filters.

The response itself is strong and was measured before the detector was tuned --
at the labelled positions, black-hat medians are 206-228 for positives against
54-102 for negatives across every kernel from 15 to 81, a 3-4x separation. So
the primitive is sound independently of where the gates end up.

**The operating point is a RIDGE, not a plateau, and that is a real fragility.**
Recall is non-monotonic in the threshold -- 57%, 76%, 29%, 10% at k=15 for
bh = 100/130/160/190 -- which a threshold should never be on its own. The cause
is the AREA gate downstream: lowering the floor grows the mask until neighbouring
responses MERGE, the component blows past `AREA_MAX`, and the icon is discarded
whole. That is the same merge failure this repo has hit four times, arriving
once more.

So `BH_MIN = 130` is not "the level that separates ink from noise" -- it is the
level at which blobs happen not to merge on these four sessions, and it will not
transfer on that basis. **The principled fix is to stop thresholding: take local
maxima of the response at the disc scale (or a watershed) instead of a global cut
plus an area filter.** Until then, treat the number as fitted.

The three misses are worth naming rather than averaging away: two trapwires and
one spycam, and the spycam miss is the teal one -- a mode that is not dark at
all, which a *black*-hat cannot be expected to see. The mode-invariance claim in
the header holds for shape and not for this operator; a teal disc needs the same
treatment on a colour channel.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import metrics                                       # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from ability_eval import label_rows, collapse, _sha, STORE        # noqa: E402
import minimap_dynamic as md                                      # noqa: E402

#: Structuring element for the black-hat. Must exceed the icon (~25 px bbox) so
#: the whole disc is smaller than the kernel, and stay well under a viewcone.
BH_K = 27

#: Response floor. Relative in nature (a black-hat is already a local contrast),
#: so this is a floor on CONTRAST, not on brightness.
BH_MIN = 130

#: A disc's area at the measured icon size, generously bounded.
AREA_MIN, AREA_MAX = 40, 900

#: 4*pi*A/P^2. **Was 0.45 on the reasoning that a disc scores near 1.0, and that
#: was wrong** -- caught by the first exhaustively painted frames (`paint_eval.py`).
#: The black-hat does not return a filled disc; it returns the icon's dark EDGE
#: structure, whose perimeter is ragged, so a real icon scores far below a
#: circle. At 0.45 the gate was rejecting real icons and recall against painted
#: ground truth was 54.5%; at 0.15 it is 90.9% for the SAME precision. The area
#: gate turned out to be inert here (900/1600/3000 give identical numbers), so
#: shape was doing all the damage and none of the work.
CIRC_MIN = 0.15

#: A detection this close to a labelled object is that object.
MATCH_PX = 8


def disc_response(gray, k=BH_K):
    """Dark structures smaller than `k`, against their own local background."""
    se = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    return cv2.morphologyEx(gray, cv2.MORPH_BLACKHAT, se)


def find_discs(gray, ok, k=BH_K, bh_min=BH_MIN, area=(AREA_MIN, AREA_MAX),
               circ_min=CIRC_MIN):
    """Disc candidates: (x, y, score, area, circularity)."""
    resp = disc_response(gray, k)
    m = ((resp > bh_min) & ok).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lbl, st, cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for i in range(1, n):
        a = int(st[i, cv2.CC_STAT_AREA])
        if not (area[0] <= a <= area[1]):
            continue
        comp = (lbl == i).astype(np.uint8)
        cnt, _ = cv2.findContours(comp, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not cnt:
            continue
        per = cv2.arcLength(cnt[0], True)
        c = 4 * np.pi * a / max(1e-6, per * per)
        if c < circ_min:
            continue
        out.append((float(cen[i][0]), float(cen[i][1]),
                    float(resp[comp > 0].mean()), a, float(c)))
    return out


def frame_iter(sid, rows):
    """Decode each labelled timestamp once, yielding (t, gray, ok, rows)."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    ok = md.searchable(labels, static=static)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    lo, hi = md.load_two_state(sid)
    cap = cv2.VideoCapture(src["path"])
    byt: dict = defaultdict(list)
    for r in rows:
        byt[r["t_ms"]].append(r)
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        if g.shape != ok.shape:
            break
        yield t, crop, g, ok, sgray, lo, hi, rs
    cap.release()


#: Region classes, excluded from the icon target set on purpose.
REGION = {"brimstone:orbital strike"}


def klass(r):
    return f"{(r['_agent'] or '?').lower()}:{(r['_ability'] or '?').lower()}"


def evaluate(sessions, k=BH_K, bh_min=BH_MIN, quiet=False):
    """Recall on icon objects, hits on negatives, and stream size per frame."""
    tp = fn = neg_hit = neg_tot = 0
    stream = md_stream = 0
    frames = 0
    per_class: dict = defaultdict(lambda: [0, 0])
    missed = []
    for sid in sessions:
        rows, _d = label_rows(sid)
        if not rows:
            continue
        rows = collapse(rows)
        for r in rows:
            r["_sid"] = sid
        for t, crop, g, ok, sgray, lo, hi, rs in frame_iter(sid, rows):
            frames += 1
            det = find_discs(g, ok, k, bh_min)
            stream += len(det)
            md_stream += len(md.detect(crop, sgray, ok, static_gray2=hi) or [])
            for r in rs:
                near = any((d[0] - r["x"]) ** 2 + (d[1] - r["y"]) ** 2 <= MATCH_PX ** 2
                           for d in det)
                if r["_true"]:
                    kk = klass(r)
                    if kk in REGION:
                        continue
                    per_class[kk][1] += 1
                    if near:
                        tp += 1
                        per_class[kk][0] += 1
                    else:
                        fn += 1
                        missed.append((sid, t, r["x"], r["y"], kk))
                else:
                    neg_tot += 1
                    neg_hit += near
    rec = tp / max(1, tp + fn)
    if not quiet:
        print(f"   k={k:3d} bh>={bh_min:3d}   recall {rec * 100:5.1f}% ({tp}/{tp + fn})   "
              f"re-proposes {neg_hit}/{neg_tot} known negatives   "
              f"{stream / max(1, frames):5.1f} cand/frame "
              f"(detect: {md_stream / max(1, frames):5.1f})")
    return {"recall": round(rec, 4), "tp": tp, "fn": fn,
            "neg_hit": neg_hit, "neg_tot": neg_tot,
            "cand_per_frame": round(stream / max(1, frames), 2),
            "detect_per_frame": round(md_stream / max(1, frames), 2),
            "frames": frames}, per_class, missed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("-k", type=int, default=BH_K)
    ap.add_argument("--bh-min", type=int, default=BH_MIN)
    args = ap.parse_args()

    if args.sweep:
        print("   kernel / contrast-floor sweep:")
        for k in (15, 21, 27, 41):
            for bh in (100, 130, 160, 190):
                evaluate(args.sessions, k, bh)
        return 0

    print(f"   disc detector, k={args.k}, blackhat floor {args.bh_min}:")
    got, per_class, missed = evaluate(args.sessions, args.k, args.bh_min)
    print("\n   recall by ICON class (regions excluded on purpose):")
    for kk, (hit, tot) in sorted(per_class.items(), key=lambda kv: -kv[1][1]):
        print(f"      {kk:<28} {hit}/{tot}")
    if missed:
        print("\n   missed:")
        for sid, t, x, y, kk in missed:
            print(f"      {sid[:6]} {t / 1000:7.1f}s ({x:3d},{y:3d})  {kk}")
    print("\n   NOTE: precision is not measurable here -- a detection where nobody")
    print("   has labelled is unscored. cand/frame is the proxy; closing the gap")
    print("   needs a fresh labelling pass over THIS stream.")
    metrics.record(
        "ability_disc", part="icons", session="+".join(args.sessions),
        values=got,
        deps={"detector": metrics.fingerprint(disc_response, find_discs, evaluate,
                                              BH_K=args.k, BH_MIN=args.bh_min,
                                              AREA=(AREA_MIN, AREA_MAX),
                                              CIRC_MIN=CIRC_MIN, MATCH_PX=MATCH_PX),
              "regions_excluded": ",".join(sorted(REGION)),
              "labels_sha": "+".join(_sha(STORE / "labels" / "ability" / f"{s}.jsonl")
                                     for s in args.sessions)},
        context={"n_icon_objects": got["tp"] + got["fn"], "frames": got["frames"]},
    )
    print()
    print(metrics.report(tool="ability_disc"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
