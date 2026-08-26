"""Find everything that MOVES on the minimap, without assuming a colour.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_dynamic.py <session> [--sweep]

The finder this project has works by masking red. That was the right first
move -- an enemy is red and red is rare on a grey widget -- but it has a hard
ceiling that no tuning reaches: Grant, looking at footage, reports that **some
ability icons are pure black and white with no team colour at all**. A red mask
cannot see those. They are not confounders being misclassified; they are
undetected, and no threshold in `minimap_ring_fit` will ever find them.

The alternative needs no colour. Every icon, ability and viewcone is by
definition what DIFFERS from the static map, and `minimap_geometry` now supplies
both the static map and the labels needed to keep the difference honest:

* **the white lines are where the false positives live.** A 1-2 px line between
  two very different levels shifts slightly frame to frame and lights up under
  any difference threshold. On `c62c2b06bcfb` that was most of 107 blobs
  against the red mask's 7 over the same six frames. The geometry map locates
  those lines exactly, so they are excluded BY CONSTRUCTION rather than by
  another threshold;
* **the void is not part of the map.** The widget is semi-transparent, so
  outside the floor plan the world churns behind it -- the failure that killed
  five earlier content-based approaches in `minimap_position.py`. Restricting to
  the footprint is the same fix, taken from the geometry rather than guessed;
* **a viewcone is dynamic too, and that is a feature.** It is large and diffuse
  where an icon is small and compact, so size separates them, and the cone is
  worth having: it is what your team can currently SEE.

RESULT: as a replacement for the red finder this LOSES, decisively
------------------------------------------------------------------
Scored on Grant's 164 labelled frames, and only on blobs this calls red so it
is comparable rather than flattered by also finding allies:

    dynamic difference, best of 18 configurations   55.6% / 29.6%
    minimap_ring_fit at its shipped point           80.8% / 54.6%

The failure is structural, not a threshold. Tracing every hand-marked enemy
icon through the filters:

    blob area < 30, fragmented        32
    kept and called red               29
    blob area > 1200, merged          11
    no blob at all                     5
    span > 40                          1

**Differencing an annulus gives a broken annulus.** The raw signal is not the
problem -- peak difference at a mark has a median of 147 and 96% of marks carry
ample over-threshold pixels -- but a ring 1-2 px thick over most of its
circumference falls apart into fragments of median area 57 and p10 of SIX. Every
repair makes it worse: closing at 3 px takes recall from 55.6% to 21.8%, because
the radius that reconnects a broken ring is the radius that merges adjacent
icons. That is the same trap recorded in `minimap_icons` and `minimap_position`,
met for the third time, and it is why `minimap_ring_fit` FITS a circle instead
of trying to repair one.

Two other guesses died on the way, both worth keeping because both were
reasonable:

* **guarding box edges as well as borders** left 25.2% of the widget searchable
  and cut recall to 38.9%. Box edges run all through the interior, so guarding
  them deletes the floor the icons stand on. Borders only;
* **the viewcone merging icons into itself** looked like the cause -- 60% of a
  16 px window around a mark is "dynamic" -- so the difference was top-hatted
  with a kernel larger than an icon and smaller than a cone. It bought 2 points
  (30.2% to 32.5%). The merge case is real but it is 11 marks, not the 32 that
  fragmentation costs.

So this is NOT the enemy detector, and expecting it to be was the error: the red
ring fit is better at finding red rings and should keep that job. What this
channel uniquely does is see what has NO colour at all -- the pure black-and-
white ability glyphs a red mask is blind to by construction. That is a different
job and it is the one worth pursuing here.

**Blocked on labels.** Nothing in the store says where an ability icon is, so
the one thing this channel is for cannot be scored at all. `blob_colour`
already reports 1300-3900 `none` blobs per sweep against 200-300 red ones, and
without labels there is no way to tell which of those are ability glyphs and
which are noise. A labelling pass over dynamic candidates is the next step, and
it needs Grant.

Colour is read from the blob rather than assumed, into the palette Grant gave:
red enemy, blue ally, yellow self, green ally ability, and none for the pure
black-and-white glyphs. Grant, refining it further: **the team-coloured
abilities look like the CONTROLLED ones** -- Skye's bird and dog, Fade's eye --
while ordinary placed utility is black and white, and Reyna's Leer is placed and
carries no colour. If that holds it is a useful pairing, because a controlled
entity is also the kind that MOVES, so colour and motion would agree.
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
from minimap_geometry import BORDER, BOXEDGE, VOID                # noqa: E402
from minimap_temporal import usable                               # noqa: E402

STORE = Path.home() / "reticle-store"

# How far the white lines' influence reaches. A line is 1-2 px and the
# difference it produces smears by antialiasing, so this clears both.
LINE_GUARD = 3
# Difference in grey levels that counts as dynamic. Swept below.
DIFF_MIN = 28
# Blob geometry. An icon on the enlarged widget fits a ring of radius 8-13, so
# it spans roughly 16-27 px; a viewcone is hundreds of px across, and a
# leftover line fragment is a few. Both bounds are doing real work.
AREA_MIN, AREA_MAX = 30, 1200
SPAN_MIN, SPAN_MAX = 6, 40

# Grant's palette. Hue bands in OpenCV's 0-179 space.
#   red enemy, blue ally, yellow self, green ally ability.
# `none` is not a gap in this list -- it is the answer for a pure black-and-white
# glyph, and finding those is the point of the exercise.
BANDS = {"red": [(0, 8), (168, 180)], "yellow": [(20, 35)],
         "green": [(40, 85)], "blue": [(90, 130)]}
COLOUR_SAT, COLOUR_VAL = 90, 80


def blob_colour(bgr, mask):
    """Which team colour a blob carries, or `none` for black and white."""
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    lit = mask & (s > COLOUR_SAT) & (v > COLOUR_VAL)
    n = int(lit.sum())
    if n < 4:
        return "none", 0.0
    best, frac = "none", 0.0
    for name, spans in BANDS.items():
        m = np.zeros(h.shape, bool)
        for lo, hi in spans:
            m |= (h >= lo) & (h <= hi)
        f = float((m & lit).sum()) / max(1, int(mask.sum()))
        if f > frac:
            best, frac = name, f
    # A blob whose coloured pixels are a trickle is black and white with a
    # little bleed from whatever it sits on, not a coloured icon.
    return (best, frac) if frac >= 0.08 else ("none", frac)


def searchable(labels, guard_px=LINE_GUARD, guard_boxedges=False):
    """Where a detection is allowed to be: the footprint, minus the lines.

    `guard_boxedges` defaults FALSE, measured rather than cautious. Guarding box
    edges as well as borders is the obvious reading of "the lines are where the
    false positives live", and it is far too expensive: box edges run all
    through the interior, so a 3 px guard around them left only 25.2% of the
    widget searchable -- 16.3% given up -- and recall fell to 38.9% against the
    red finder's 80.8%. Most of what it excluded was ordinary floor with icons
    standing on it.
    """
    lines = (labels == BORDER)
    if guard_boxedges:
        lines = lines | (labels == BOXEDGE)
    if guard_px:
        lines = cv2.dilate(lines.astype(np.uint8),
                           np.ones((2 * guard_px + 1,) * 2, np.uint8)) > 0
    return (labels != VOID) & ~lines


# Top-hat kernel, in pixels. Must be comfortably LARGER than an icon (16-27 px
# across on the enlarged widget) and smaller than a viewcone.
TOPHAT_K = 31


def detect(crop, static_gray, ok_area, diff_min=DIFF_MIN, tophat=True):
    """Dynamic blobs: what differs from the static map, inside the footprint.

    The difference is TOP-HATTED before thresholding, and without that this does
    not work at all. Measured at Grant's enemy marks: the raw difference peaks
    at a median of 147 and 96% of marks carry ample over-threshold pixels, so
    the icons light up plainly -- and yet recall came out at 30% against the red
    finder's 80.8%. The reason is that 60% of a 16 px window around a mark is
    also "dynamic": **the viewcone is an enormous dynamic region**, and
    connected components merges the icon into it, so the blob blows past
    AREA_MAX and is discarded. The icon was found and then thrown away for being
    attached to something bigger.

    A top-hat with a kernel larger than an icon and smaller than a cone keeps
    what is locally bright and removes what is broadly bright, which is exactly
    the icon-versus-cone distinction. It is the same instrument the screen
    detector uses at the enemy rim, for the same reason.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.int16)
    raw = np.abs(g - static_gray).astype(np.uint8)
    if tophat:
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (TOPHAT_K, TOPHAT_K))
        raw = cv2.morphologyEx(raw, cv2.MORPH_TOPHAT, k)
    d = (raw > diff_min) & ok_area
    d = cv2.morphologyEx(d.astype(np.uint8), cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))
    n, lbl, st, cen = cv2.connectedComponentsWithStats(d, 8)
    out = []
    for i in range(1, n):
        x, y, w, h, area = st[i]
        if not (AREA_MIN <= area <= AREA_MAX):
            continue
        if not (SPAN_MIN <= max(w, h) <= SPAN_MAX):
            continue
        m = lbl == i
        col, frac = blob_colour(crop, m)
        out.append({"xy": (float(cen[i][0]), float(cen[i][1])), "area": int(area),
                    "box": (int(x), int(y), int(w), int(h)),
                    "colour": col, "colour_frac": float(frac)})
    return out


def load_geometry(sid):
    p = STORE / "geometry" / f"{sid}.npz"
    if not p.is_file():
        raise SystemExit(f"no geometry for {sid} -- run minimap_geometry.py first")
    z = np.load(p)
    return z["labels"], z["static"]


def labelled_frames(sid):
    """Grant's minimap marks, keyed by time. Red things only -- that is all he
    was asked to mark, so allies must never be scored as false positives."""
    rows = {}
    for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["t_ms"]] = r
    return {t: r for t, r in rows.items() if not r.get("uncertain")}


HIT_PX = 16


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--sweep", action="store_true")
    ap.add_argument("--no-tophat", action="store_true",
                    help="threshold the raw difference, to show what the top-hat buys")
    ap.add_argument("--sheet")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = load_geometry(args.session)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    floor = labels != VOID

    rows = labelled_frames(args.session)
    cap = cv2.VideoCapture(src["path"])
    frames = {}
    for t in sorted(rows):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if ok:
            frames[t] = fr[y0:y1, x0:x1].copy()
    cap.release()
    print(f"{len(frames)} labelled frames decoded")

    thresholds = (16, 22, 28, 36) if args.sweep else (DIFF_MIN,)
    guards = ((3, False), (1, False), (0, False)) if args.sweep else ((LINE_GUARD, False),)
    print(f"\n{'diff':>5} {'recall':>8} {'prec':>8} {'red/frame':>10} "
          f"{'all/frame':>10}  colours found")
    for (gpx, gbox) in guards:
      ok_area = searchable(labels, gpx, gbox)
      for th in thresholds:
        tp = fn = fp = 0
        nred = nall = nframe = 0
        palette = {}
        for t, r in rows.items():
            crop = frames.get(t)
            if crop is None or not usable(crop, floor):
                continue
            nframe += 1
            dets = detect(crop, sgray, ok_area, th, tophat=not args.no_tophat)
            nall += len(dets)
            for d in dets:
                palette[d["colour"]] = palette.get(d["colour"], 0) + 1
            red = [d for d in dets if d["colour"] == "red"]
            nred += len(red)
            marks = [m for m in r["marks"]]      # every red thing Grant marked
            used = set()
            for m in marks:
                hit = None
                for i, d in enumerate(red):
                    if i in used:
                        continue
                    if np.hypot(d["xy"][0] - m["x"], d["xy"][1] - m["y"]) <= HIT_PX:
                        hit = i
                        break
                if hit is None:
                    fn += 1
                else:
                    used.add(hit)
                    tp += 1
            fp += len(red) - len(used)
        rec = tp / max(1, tp + fn)
        pre = tp / max(1, tp + fp)
        top = ", ".join(f"{k} {v}" for k, v in
                        sorted(palette.items(), key=lambda kv: -kv[1]))
        tag = f"{gpx}px{'+box' if gbox else ''}"
        print(f"{tag:>10} search {ok_area.mean()*100:5.1f}% diff {th:3d} "
              f"rec {rec*100:5.1f}% prec {pre*100:5.1f}% red/fr {nred/max(1,nframe):5.2f}  {top}")
    print("\nred finder at its shipped point, for comparison: 80.8% / 54.6%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
