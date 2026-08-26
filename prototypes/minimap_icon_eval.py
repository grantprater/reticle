"""Score the minimap icon finder against hand labels, and test the premise.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_icon_eval.py <session> [--premise-only]

Two questions, and the FIRST needs no detector at all.

1. **Does an enemy icon actually appear when an enemy provably exists?**
   Answered from the labels alone, by counting how many `prekill` frames carry
   at least one enemy mark. This is the premise the whole minimap-as-a-gate idea
   rests on, and it has never been tested in the form that matters. What was
   verified earlier is that no enemy frame had *zero red pixels* on the minimap
   -- but red pixels include X death marks, Reyna blinds, Cypher cams and pings.
   "There is red somewhere" and "there is a ring-with-a-triangle icon" are
   different claims, and only a proof gate built on the second one means
   anything.

   If the pre-kill rate is far below 100%, the gate is dead however good the
   finder gets, and that is worth knowing before any more work on the finder.

2. **Given the icon is there, does the finder find it?** Recall and precision
   against the marks, reported separately for the `prekill` and `uniform`
   pools -- never pooled. The pre-kill set is the easy end (a kill usually means
   a close, clearly visible enemy) and quoting a blended number would flatter
   it, in the same way the screen detector's centre-biased corpus flatters a
   centre prior.

`other_red` marks -- the X marks and abilities that are NOT enemies -- are
scored as what they are: a detection landing on one is a false positive with a
named cause, which is far more useful than an anonymous count.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from minimap_icons import floor_mask, static_map                   # noqa: E402
from minimap_icon_scan import candidates                          # noqa: E402
import minimap_ring_fit as ringfit                                # noqa: E402

STORE = Path.home() / "reticle-store"
# A mark is credited to a detection whose box contains it, or which lands within
# this many pixels of it -- icons are ~25 px across and a click lands near the
# centre, so this is tolerant of an imprecise click without crediting a
# detection on the next icon along.
HIT_PX = 16


def hits(mx, my, c):
    x, y, w, h = c["box"]
    if x - 4 <= mx <= x + w + 4 and y - 4 <= my <= y + h + 4:
        return True
    return np.hypot(c["xy"][0] - mx, c["xy"][1] - my) <= HIT_PX


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--premise-only", action="store_true")
    ap.add_argument("--sat", type=int, default=100)
    ap.add_argument("--finder", choices=("seal", "ring"), default="seal",
                    help="seal = hole test (minimap_icon_scan); "
                         "ring = arc-coverage fit (minimap_ring_fit)")
    args = ap.parse_args()

    lab_path = STORE / "labels" / "minimap" / f"{args.session}.jsonl"
    if not lab_path.is_file():
        print(f"no labels at {lab_path} -- run label_minimap.py first")
        return 1
    rows = {}
    for line in lab_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["t_ms"]] = r                    # last row for a timestamp wins
    rows = [r for r in rows.values() if not r.get("uncertain")]
    if not rows:
        print("every labelled frame is marked uncertain")
        return 1

    # ---- 1. the premise, from labels alone -------------------------------
    print(f"{len(rows)} labelled frames\n")
    print("PREMISE: does an enemy icon appear when an enemy provably existed?")
    for pool in ("prekill", "uniform"):
        ps = [r for r in rows if r["pool"] == pool]
        if not ps:
            continue
        with_icon = sum(1 for r in ps
                        if any(m["kind"] == "enemy" for m in r["marks"]))
        n_icons = sum(sum(1 for m in r["marks"] if m["kind"] == "enemy") for r in ps)
        n_q = sum(sum(1 for m in r["marks"] if m["kind"] == "question") for r in ps)
        n_other = sum(sum(1 for m in r["marks"]
                          if m["kind"] not in ("enemy", "question")) for r in ps)
        print(f"  {pool:8s} {with_icon:4d}/{len(ps):4d} frames carry an enemy icon "
              f"({with_icon/len(ps)*100:5.1f}%)   "
              f"{n_icons} icons, {n_q} question marks, {n_other} other-red")
    print("\n  prekill is a CEILING: a kill means a close, clearly visible enemy.")
    print("  The window straddles the kill, so some frames are legitimately empty.")
    if args.premise_only:
        return 0

    # ---- 2. the finder ---------------------------------------------------
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

    st = {p: dict(tp=0, fn=0, fp=0, fp_named=0, on_q=0, n_q=0)
          for p in ("prekill", "uniform")}
    for n, r in enumerate(rows):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        if args.finder == "ring":
            cs = [{"box": (f["cx"] - f["r"], f["cy"] - f["r"], 2 * f["r"], 2 * f["r"]),
                   "xy": (f["cx"], f["cy"])}
                  for f in ringfit.find(fr[y0:y1, x0:x1], floor, sat_min=args.sat)
                  if ringfit.is_icon(f)]
        else:
            cs = candidates(fr[y0:y1, x0:x1], floor, sat_min=args.sat)
        pool = st[r["pool"]]
        used = set()
        for m in [m for m in r["marks"] if m["kind"] == "enemy"]:
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is None:
                pool["fn"] += 1
            else:
                pool["tp"] += 1
                used.add(j)
        # Question marks are counted SEPARATELY and are neither credited nor
        # penalised. A `?` is a real enemy position gone stale, and whether a
        # detection on one is right depends on the use: a proof gate wants only
        # enemies visible now, bearing work wants the stale position too.
        # Folding them either way here would bake that choice into the number.
        for m in [m for m in r["marks"] if m["kind"] == "question"]:
            pool["n_q"] += 1
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is not None:
                used.add(j)
                pool["on_q"] += 1
        for m in [m for m in r["marks"] if m["kind"] not in ("enemy", "question")]:
            j = next((j for j, c in enumerate(cs)
                      if j not in used and hits(m["x"], m["y"], c)), None)
            if j is not None:
                used.add(j)
                pool["fp_named"] += 1
        pool["fp"] += len(cs) - len(used)
        if (n + 1) % 50 == 0:
            print(f"  ... {n+1}/{len(rows)}", flush=True)
    cap.release()

    print("\nFINDER (ring + triangle), per pool -- never pool these")
    for p, s in st.items():
        if not (s["tp"] + s["fn"] + s["fp"]):
            continue
        rec = s["tp"] / max(s["tp"] + s["fn"], 1)
        pre = s["tp"] / max(s["tp"] + s["fp"] + s["fp_named"], 1)
        print(f"  {p:8s} TP {s['tp']:3d}  FN {s['fn']:3d}  FP {s['fp']:3d} "
              f"(+{s['fp_named']} on a marked non-enemy)   "
              f"recall {rec*100:5.1f}%  precision {pre*100:5.1f}%")
        if s["n_q"]:
            print(f"  {'':8s} question marks: {s['on_q']}/{s['n_q']} fired on -- "
                  f"counted neither way, see the code comment")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
