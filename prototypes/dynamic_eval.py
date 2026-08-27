"""Score the colour-free channel against Grant's labels, and the mask against his painting.

    .\\.venv\\Scripts\\python.exe prototypes\\dynamic_eval.py <session> [<session>...]
    .\\.venv\\Scripts\\python.exe prototypes\\dynamic_eval.py --mask <session>...

Why this exists
---------------
Both of this session's results were computed in throwaway scripts, which is the
wrong place for the two numbers the next step is judged by. The fit for the
ability classifier is the FIRST thing the handoff asks for, and it should not
begin by rebuilding feature extraction from the commit message.

The two features it measures are not recorded by `minimap_dynamic.detect`, and
that is the finding rather than an oversight:

* **host span** -- the span of the RAW difference region a blob belongs to,
  BEFORE the top-hat. Grant, on candidate 149 of the first labelling run: *part
  of the vision cone barely clipping a corner and producing something that
  vaguely could look like an icon.* The top-hat is what shatters a viewcone into
  corner-clips, so it destroys the only evidence that a clip is part of
  something enormous. Median 24 px under a glyph against 127 under an artefact;
* **top-hat peak** in a 5x5 window at the blob. Median 132 against 63.

Both are recomputed here from `(t_ms, x, y)` rather than stored, so rows labelled
before the features existed cost nothing. That is worth preserving as the
pattern: a label row needs the ANSWER and enough to find the pixel again;
everything else can be recomputed.

Buy phase is split out because `reticle/segment.py` calls it `active` -- it has
no notion of round phase -- and 38% of the first run's questions landed in it,
where the minimap holds nothing but spawn barriers. Every rate is quoted twice
for that reason, and the live-play number is the honest one.

`--mask` scores `searchable(labels, static=...)` against a mask Grant painted
with `paint_map.py`. Ascent 91.3%, Lotus 92.8%, on paintings made without
looking at the derived mask. Re-run it on any newly painted map: a rule that
holds on two floor plans and fails on a third is the thing worth knowing early.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
import minimap_geometry as mg                                     # noqa: E402
from minimap_icons import floor_mask                              # noqa: E402

STORE = Path.home() / "reticle-store"

# Anything a person marked as a real object. `player`, `area` and `barrier` are
# real but are not glyphs, so they count against precision without counting as
# recall -- see `report`.
GLYPH = {"ability", "ping"}
BUY_S = 30.0                       # a Valorant buy phase, and it sits inside `active`


def load(sid):
    """Answered label rows, last write for a (t_ms, x, y) winning.

    The same convention as `minimap_portrait.load_agent_labels`, and it is what
    lets a correction be appended rather than edited in: two spawn barriers were
    fixed that way after `9 barrier` was added mid-run.
    """
    p = STORE / "labels" / "minimap_dynamic" / f"{sid}.jsonl"
    if not p.is_file():
        return []
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    return [r for r in {(r["t_ms"], r["x"], r["y"]): r for r in rows}.values() if r["kind"]]


def active_spans(sid):
    t = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    return sorted([(a, b) for a, b, s in zip(t.column("t_start_ms").to_pylist(),
                                             t.column("t_end_ms").to_pylist(),
                                             t.column("state").to_pylist()) if s == "active"])


def features(sid, rows):
    """Add host span, top-hat peak and seconds-into-span to each row, in place."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    ok = md.searchable(labels, static=static)
    kern = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (md.TOPHAT_K,) * 2)
    spans = active_spans(sid)
    cap = cv2.VideoCapture(src["path"])
    byt = {}
    for r in rows:
        byt.setdefault(r["t_ms"], []).append(r)
    for t, rs in sorted(byt.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        raw = np.abs(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.int16) - sgray)
        raw = raw.astype(np.uint8)
        # The raw region, closed only enough to bridge the 1 px gaps thresholding
        # leaves. NOT the opened/top-hatted mask `detect` uses -- the point is to
        # see the cone whole, before anything fragments it.
        rawm = cv2.morphologyEx(((raw > md.DIFF_MIN) & ok).astype(np.uint8),
                                cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
        n, lbl, st, _c = cv2.connectedComponentsWithStats(rawm, 8)
        top = cv2.morphologyEx(raw, cv2.MORPH_TOPHAT, kern)
        for r in rs:
            x, y = r["x"], r["y"]
            i = lbl[y, x]
            r["span"] = int(max(st[i, 2], st[i, 3])) if i else 0
            r["tophat"] = int(top[max(0, y - 2):y + 3, max(0, x - 2):x + 3].max())
            r["into"] = next(((r["t_ms"] - a) / 1000.0 for a, b in spans
                              if a <= r["t_ms"] <= b), None)
    cap.release()
    return rows


POINTS = ((999, 0), (80, 0), (40, 0), (999, 90), (60, 90), (40, 90), (40, 110))


def report(rows, name):
    pos = [r for r in rows if r["kind"] in GLYPH]
    neg = [r for r in rows if r["kind"] == "nothing"]
    oth = [r for r in rows if r["kind"] not in GLYPH and r["kind"] != "nothing"]
    if not pos:
        return
    print(f"\n{name}: {len(rows)} rows -- {len(pos)} glyph, {len(oth)} other real, "
          f"{len(neg)} nothing (baseline {len(pos) / len(rows) * 100:.0f}%)")
    print(f"   {'span<=':>7} {'tophat>=':>9} {'recall':>8} {'vs nothing':>11} {'vs all kept':>12}")
    for S, T in POINTS:
        kp = [r for r in pos if r["span"] <= S and r["tophat"] >= T]
        kn = [r for r in neg if r["span"] <= S and r["tophat"] >= T]
        ko = [r for r in oth if r["span"] <= S and r["tophat"] >= T]
        if not kp:
            continue
        print(f"   {S:>7} {T:>9} {len(kp) / len(pos) * 100:7.0f}% "
              f"{len(kp) / (len(kp) + len(kn)) * 100:10.0f}% "
              f"{len(kp) / (len(kp) + len(kn) + len(ko)) * 100:11.0f}%")


def score_mask(sid):
    p = STORE / "labels" / "map_mask" / f"{sid}.png"
    if not p.is_file():
        print(f"{sid}: no painted mask -- run paint_map.py")
        return
    meta = json.loads(p.with_suffix(".json").read_text())
    g = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) > 127
    labels, static = md.load_geometry(sid)
    d = md.searchable(labels, static=static)
    print(f"\n{sid}: painted {g.mean() * 100:.1f}%  derived {d.mean() * 100:.1f}%  "
          f"IoU {(g & d).sum() / max(1, (g | d).sum()) * 100:.1f}%  "
          f"(seeded={meta['compared_against_derived']})")
    for nm, m in (("lit slab", floor_mask(static, dilate=1)),
                  ("bomb sites", labels == mg.PLANT),
                  ("HOLE", labels == mg.HOLE),
                  ("exterior void", labels == mg.VOID),
                  ("BORDER line", labels == mg.BORDER),
                  ("BOXEDGE line", labels == mg.BOXEDGE)):
        if m.sum():
            print(f"      {nm:>14}: {g[m].mean() * 100:5.1f}% painted  ({int(m.sum()):6d} px)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    ap.add_argument("--mask", action="store_true",
                    help="score the searchable rule against the painted mask instead")
    args = ap.parse_args()
    for sid in args.sessions:
        if args.mask:
            score_mask(sid)
            continue
        rows = load(sid)
        if not rows:
            print(f"{sid}: no labels -- run label_dynamic.py --colour none")
            continue
        print(f"\n=== {sid} ===  {len(rows)} answered")
        print("  ", dict(Counter(r["kind"] for r in rows).most_common()))
        features(sid, rows)
        rows = [r for r in rows if "span" in r]
        report(rows, "ALL rows")
        report([r for r in rows if r["into"] is not None and r["into"] >= BUY_S],
               f"LIVE PLAY ({BUY_S:.0f}s+ into a span)")
        report([r for r in rows if r["into"] is not None and r["into"] < BUY_S],
               f"BUY PHASE (first {BUY_S:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
