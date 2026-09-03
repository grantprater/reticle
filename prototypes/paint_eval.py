"""Score any detector against exhaustively painted frames -- real precision at last.

    .\\.venv\\Scripts\\python.exe prototypes\\paint_eval.py <session>...

Why this is different from every other eval here
--------------------------------------------------
`ability_eval.py` and `ability_disc.py` both had to refuse a precision figure,
for the same structural reason: every label in the store sits at a position some
detector already proposed, so a detection where nobody has labelled is unscored
and the best available proxy was candidates-per-frame.

`paint_icons.py` breaks that. A painted frame is declared EXHAUSTIVE, so every
pixel not marked is a true negative by construction, and a detection that lands
nowhere near a mark is a real false positive rather than an unknown. Precision
and recall are both computable, for any detector, without another labelling pass.

Three things this file is careful about
-----------------------------------------
**A detection inside a painted REGION is not a false positive, and not a true
positive either.** Regions are smokes, walls and ults -- real ability objects
with no centre to click. An icon detector firing inside one has found something
real that it was not asked to find, so those are reported in their own column
rather than being silently counted either way. Folding them into FP would
understate precision; folding them into TP would credit an icon detector for
finding a smoke.

**Only frames marked `exhaustive` and not `unsure` are scored.** An `unsure`
frame is recorded and kept out, the same contract every labeller here uses.

**The match radius comes from the painted mark, not from a constant.** the player
sets a radius per icon; a detection inside that disc (plus a little slack) is
that icon. A fixed `MATCH_PX` would be a second threshold to argue about.

First results, 2026-09-03 -- and why the perfect one means little
------------------------------------------------------------------
Two painted sessions, abilities-only scoring:

    d95cfad5693a  (small widget, Cypher clip)     recall  precision  on-world
      ability_disc                                 100.0%    100.0%       1
      minimap_dynamic.detect                        86.1%     67.4%      10

    a06f04a0059f  (bigmap, Ascent match)
      ability_disc                                  90.9%     30.3%       -
      minimap_dynamic.detect                        81.8%      9.5%       -

**Do not quote the 100%.** `d95cfad5693a`'s 36 painted ability icons are **3
distinct objects**, each seen exactly 12 times, across a **16-second** span --
a controlled clip where three Cypher devices sit still while 12 near-identical
frames are sampled 1.46 s apart. The effective n is 3, not 36. `a06f04a0059f` is
the informative session: 4 objects spread over 535 seconds of real play, and
there precision is 30.3%.

The gap between the two is mostly scene complexity, not detector quality -- a
custom game with three devices has almost nothing to false-positive on, while a
45-minute match has X marks, pings, enemy icons and utility everywhere.

**Sampling design note for the next pass**: a 17-second clip does not contain 12
independent frames, so painting one is expensive per unit of information. Paint
REAL MATCHES, and spread the frames.

**One difference that is real and not an artefact of object count**: the
`on-world` column. The disc detector fired on the player icon **1** time in 12
frames; `minimap_dynamic.detect` fired on it **10** times. Player icons are the
main confounder for anything disc-shaped, and this is direct evidence the
black-hat largely steps over them -- measured on the same frames, so object
count cannot explain it.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import metrics                                       # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from ability_disc import find_discs                               # noqa: E402
from paint_icons import OUT_DIR, load_done                        # noqa: E402

STORE = Path.home() / "reticle-store"

#: Slack added to a painted icon's own radius when matching a detection to it.
SLACK = 4


def region_mask(row, shape):
    """Union of the frame's painted regions, in full-frame coordinates."""
    m = np.zeros(shape, np.uint8)
    for rg in row.get("regions", []):
        x0, y0, bw, bh = rg["bbox"]
        sub = cv2.imdecode(np.frombuffer(base64.b64decode(rg["mask_png"]), np.uint8),
                           cv2.IMREAD_GRAYSCALE)
        if sub is not None:
            m[y0:y0 + bh, x0:x0 + bw] |= (sub > 127).astype(np.uint8)
    return m


def is_world(ic):
    """A painted non-ability object: player icons, X marks, the spike, the
    audio ring. `paint_icons.WORLD` writes these with agent 'world'."""
    return (ic.get("agent") or "").lower() == "world"


def score(sid, detector, name, abilities_only=False):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    ok = md.searchable(labels, static=static)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    _lo, hi = md.load_two_state(sid)
    rows = load_done(OUT_DIR / f"{sid}.jsonl")
    rows = {t: r for t, r in rows.items() if r.get("exhaustive") and not r.get("unsure")}
    if not rows:
        return None

    cap = cv2.VideoCapture(src["path"])
    tp = fn = fp = in_region = on_world = 0
    n_icons = frames = 0
    missed = []
    for t, row in sorted(rows.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        if crop.shape[:2] != ok.shape:
            continue
        frames += 1
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        det = detector(crop, g, ok, sgray, hi)
        rmask = region_mask(row, ok.shape)
        icons = row["icons"]
        # Targets are the painted ABILITY icons when `abilities_only`; painted
        # world objects then become their own column rather than either credit
        # or blame. A player icon IS a dark disc, so a disc detector finding one
        # is behaving correctly -- but it is not an ability, so counting it as a
        # true positive inflates precision (12 of d95cfad5693a's 48 painted
        # icons are `world:self`), and counting it as a false positive blames the
        # detector for succeeding. Its own column also answers the question
        # the player asked: how many of the false positives are player icons?
        targets = [ic for ic in icons if not (abilities_only and is_world(ic))]
        worlds = [ic for ic in icons if abilities_only and is_world(ic)]
        n_icons += len(targets)
        claimed = set()
        for d in det:
            dx, dy = d[0], d[1]
            hit = None
            for j, ic in enumerate(targets):
                rad = ic.get("r", 7) + SLACK
                if (dx - ic["x"]) ** 2 + (dy - ic["y"]) ** 2 <= rad * rad:
                    hit = j
                    break
            if hit is not None:
                claimed.add(hit)
                continue
            if any((dx - ic["x"]) ** 2 + (dy - ic["y"]) ** 2
                   <= (ic.get("r", 7) + SLACK) ** 2 for ic in worlds):
                on_world += 1
            elif rmask[min(ok.shape[0] - 1, max(0, int(dy))),
                       min(ok.shape[1] - 1, max(0, int(dx)))]:
                in_region += 1
            else:
                fp += 1
        tp += len(claimed)
        for j, ic in enumerate(targets):
            if j not in claimed:
                fn += 1
                missed.append((t, ic["x"], ic["y"], ic.get("ability", "?")))
    cap.release()
    rec = tp / max(1, tp + fn)
    prec = tp / max(1, tp + fp)
    print(f"   {name:<24} TP {tp:3d}  FP {fp:4d}  FN {fn:3d}  "
          f"on-world {on_world:3d}  in-region {in_region:3d}   "
          f"recall {rec * 100:5.1f}%   precision {prec * 100:5.1f}%")
    return {"tp": tp, "fp": fp, "fn": fn, "in_region": in_region,
            "on_world": on_world,
            "recall": round(rec, 4), "precision": round(prec, 4),
            "frames": frames, "n_icons": n_icons}, missed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    args = ap.parse_args()

    def disc(crop, g, ok, sgray, hi):
        return find_discs(g, ok)

    def dynamic(crop, g, ok, sgray, hi):
        return [(d["xy"][0], d["xy"][1]) for d in
                (md.detect(crop, sgray, ok, static_gray2=hi) or [])]

    for sid in args.sessions:
        print(f"\n=== {sid} ===  against exhaustively painted frames")
        print("   ALL painted icons as targets (a DISC detector's job):")
        score(sid, disc, "ability_disc")
        score(sid, dynamic, "minimap_dynamic.detect")
        print("   ABILITIES only -- world objects get their own column:")
        got = score(sid, disc, "ability_disc", abilities_only=True)
        score(sid, dynamic, "minimap_dynamic.detect", abilities_only=True)
        if got is None:
            print("   no exhaustive painted frames")
            continue
        vals, missed = got
        print(f"\n   {vals['frames']} frames, {vals['n_icons']} painted icons")
        if missed:
            print("   missed icons:")
            for t, x, y, ab in missed:
                print(f"      t={t / 1000:8.1f}s ({x:3d},{y:3d})  {ab}")
        print("\n   'in-region' = fired inside a painted smoke/wall/ult. Real object,")
        print("   not an icon -- counted neither as TP nor FP.")
        metrics.record(
            "paint_eval", part="icons", session=sid, values=vals,
            deps={"detector": metrics.fingerprint(find_discs, score, SLACK=SLACK),
                  "truth": "ability_paint/exhaustive"},
            context={"frames": vals["frames"], "n_icons": vals["n_icons"]},
        )
    print()
    print(metrics.report(tool="paint_eval"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
