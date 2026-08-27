"""Cross-session sheet for the colour-free channel: fit on one map, read on another.

    .\\.venv\\Scripts\\python.exe prototypes\\glance_dynamic.py 5822b6646448 --fit a06f04a0059f

Why this exists
---------------
The handoff's next step is *fit the ability classifier, then take it to a second
session* -- Lotus or Split, fitted on one and scored on the other. That needs
labels on the second map, and the second map has none, so the step begins with
250 more questions for Grant.

This asks a cheaper question first: **can the second map be read at all, by me,
before his time is spent?** And unlike `glance_cams.py`, the controls here are
strong. They come from Grant's 251 `minimap_dynamic` rows on the fit session --
the SAME detector, the SAME channel, the SAME question ("what is this
colour-free blob"), differing only in map. That is close to a ceiling test
rather than the floor the cam sheets got, and the failure it can actually catch
is the one this project's history keeps predicting: **a new map is where these
break** (`bdfdcf009dba` killed glyph-counting, `9acf02f98283` killed unanchored
template matching).

Read the verdict, not the answers:

* **VALID** -- the channel survives the map change at this magnification, and my
  answers are worth putting to Grant as a pre-screen rather than a label set;
* **VOID** -- the map changed the question. Then the honest next move is the
  labeller, and the finding is worth more than 250 of my guesses would have been.

Either way the answers are a PROPOSAL. They are never written to
`labels/minimap_dynamic/` -- that file takes Grant's answers only, and seeding it
with mine is the exact mistake that made a measured 93.0% circular.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import glance                                        # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_temporal import usable                               # noqa: E402
from label_dynamic import KINDS, active_times                     # noqa: E402

STORE = Path.home() / "reticle-store"

# The answer vocabulary is `label_dynamic`'s class list, unchanged, so a sheet
# answer and a label row are the same string. `warning_ping` is NEW, from Grant
# 2026-08-27: the pink triangle on a ring in the red channel is a warning ping,
# which means pings appear in BOTH channels and `6 = ping` ("a pond ripple,
# white and bluish") only ever named one of them. Kept here because a
# colour-free fragment of one is possible; see CLAUDE.md.
CLASSES = [*dict.fromkeys(KINDS.values()), "warning_ping"]


def setup(session: str):
    """Everything a sweep needs. Mirrors `label_dynamic.main`, deliberately."""
    man = json.loads((STORE / "manifests" / f"{session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(session)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    return {
        "path": src["path"], "fps": float(src["fps"]),
        "roi": (mx0, my0, mx1, my1),
        "sgray": sgray,
        "ok_area": md.searchable(labels, static=static),
        "floor": labels != md.VOID,
    }


def sweep(session: str, frames: int, diff: int):
    """Detect colour-free candidates over `frames` frames of active play."""
    s = setup(session)
    mx0, my0, mx1, my1 = s["roi"]
    cap = cv2.VideoCapture(s["path"])
    if not cap.isOpened():
        raise SystemExit(f"cannot open {s['path']}")
    cands, seen_frames, unusable = [], 0, 0
    for t in active_times(session, frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * s["fps"])))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[my0:my1, mx0:mx1]
        if not usable(crop, s["floor"]):
            unusable += 1
            continue
        seen_frames += 1
        for d in md.detect(crop, s["sgray"], s["ok_area"], diff):
            if d["colour"] != "none":
                continue
            cands.append({"t_ms": round(t), "crop": crop, **d})
    cap.release()
    return cands, seen_frames, unusable


def controls_from(fit: str, n: int, rng, per_class_max: int = 2):
    """Grant's rows on the fit session, re-cropped from its video.

    Only `by == grant` rows are eligible, and `uncertain` ones are skipped --
    a control whose truth Grant himself hedged measures nothing. Spread across
    classes so the sheet cannot be passed by guessing the majority class.
    """
    p = STORE / "labels" / "minimap_dynamic" / f"{fit}.jsonl"
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
    last: dict = {}
    for r in rows:                       # last write wins, the file's convention
        last[(r["t_ms"], r["x"], r["y"])] = r
    pool = [r for r in last.values()
            if r.get("by") == "grant" and not r.get("uncertain")]
    by_class: dict = {}
    for r in pool:
        by_class.setdefault(r["kind"], []).append(r)

    picks = []
    for kind in sorted(by_class, key=lambda k: -len(by_class[k])):
        if len(picks) >= n:
            break
        picks += rng.sample(by_class[kind], min(per_class_max, len(by_class[kind])))
    picks = picks[:n]

    s = setup(fit)
    mx0, my0, mx1, my1 = s["roi"]
    cap = cv2.VideoCapture(s["path"])
    out = []
    for r in sorted(picks, key=lambda d: d["t_ms"]):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * s["fps"])))
        ok, fr = cap.read()
        if not ok:
            continue
        out.append((fr[my0:my1, mx0:mx1], r))
    cap.release()
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session", help="the NEW map, whose blobs are the open question")
    ap.add_argument("--fit", default="a06f04a0059f", help="session the controls come from")
    ap.add_argument("--n", type=int, default=16, help="open items")
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--frames", type=int, default=120)
    ap.add_argument("--diff", type=int, default=md.DIFF_MIN)
    ap.add_argument("--zoom", type=int, default=8)
    ap.add_argument("--pad", type=int, default=14)
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--seed", type=int, default=17)
    ap.add_argument("--dir", default=None)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)

    print(f"sweeping {a.session} over {a.frames} frames...")
    cands, seen, unusable = sweep(a.session, a.frames, a.diff)
    print(f"  {len(cands)} colour-free candidates from {seen} usable frames "
          f"({unusable} unusable), {len(cands) / max(1, seen):.1f} per frame")
    if not cands:
        print("nothing to ask about")
        return 1

    items = []
    for c in rng.sample(cands, min(a.n, len(cands))):
        x, y = int(c["xy"][0]), int(c["xy"][1])
        bx, by, bw, bh = c["box"]
        items.append(glance.Item(image=c["crop"], box=(bx, by, bw, bh),
                                 key=f"{a.session} t={c['t_ms']} x={x} y={y}",
                                 note=f"{c['t_ms'] / 1000:.0f}s"))

    for crop, r in controls_from(a.fit, a.controls, rng):
        bx, by, bw, bh = r["box"]
        items.append(glance.Item(image=crop, box=(bx, by, bw, bh),
                                 key=f"{a.fit} t={r['t_ms']} x={r['x']} y={r['y']}",
                                 truth=r["kind"], note=f"{r['t_ms'] / 1000:.0f}s"))

    n_ctrl = sum(1 for i in items if i.is_control)
    print(f"  {len(items) - n_ctrl} open + {n_ctrl} controls "
          f"({Counter(i.truth for i in items if i.is_control)})")

    sheet = glance.present(
        items,
        question=(f"Colour-free minimap blobs. What is the ringed thing? "
                  f"Detection only -- not which ability."),
        classes=CLASSES, zoom=a.zoom, pad=a.pad, cols=a.cols,
        truth_source=f"grant, labels/minimap_dynamic/{a.fit}.jsonl (by=grant, not uncertain)",
        domain="minimap", seed=a.seed)
    png = sheet.write(Path(a.dir) if a.dir else None)
    print(f"\n{png}\nsheet {sheet.sheet_id}")
    print(f"  python -m reticle.glance answer {sheet.sheet_id} --confidence 0.6 --answers ...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
