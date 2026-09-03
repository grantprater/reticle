"""Drop two known-bad classes from a scan_ability_clip.py candidate file, in place.

    .\\.venv\\Scripts\\python.exe prototypes\\filter_ability_candidates.py <session>

STOPGAP, not a detector fix. `minimap_dynamic.detect()` itself still has both
bugs this works around -- see prototypes/CLAUDE.md, 2026-09-02, under the
Cypher-cam writeup. This only cleans the OUTPUT of a scan so the player is not
asked to label the same two false-positive classes over and over; it does not
change what any other session's candidates look like, and it should stop
being needed once the real fixes (exclude the player's own colour from the
saturation trigger; root-cause the geometry `--geometry-from` pixel-mismatch
drift) land.

Two filters, both verified by eye against the actual crops before writing
this, not assumed from the field values alone:

1. **Self-icon matches.** A candidate within `SELF_PX` of `self_rings()` at
   its own timestamp is the moving position marker, not a placed
   device -- confirmed against `eb10db50b1fb`, 7 of 20 original candidates.
2. **Line-shaped geometry artifacts.** A candidate with `colour` in
   `LINE_COLOURS` (the border/box-edge palette) AND `aspect` above
   `LINE_ASPECT_MIN` is a wall/box-edge line mis-flagged as dynamic by a
   brightness/gamma mismatch between this session's footage and the
   `--geometry-from` donor -- confirmed by eye: every colour=red/green
   candidate at aspect >= 2.0 in `eb10db50b1fb` rendered as a thin coloured
   bar across a doorway, never a circular icon. This does NOT catch every
   artifact (a colour=none, aspect<1.8 false positive still slipped through
   in that same session, `t=6600 (141,122)`, rendered as a plain wall corner
   with nothing on it) -- it only removes the two classes cheap enough to
   catch mechanically. The rest is still the call, same as ever.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import minimap as mm                                  # noqa: E402

STORE = Path.home() / "reticle-store"
SELF_PX = 12
LINE_COLOURS = {"red", "green"}
LINE_ASPECT_MIN = 1.8


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    sid = a.session

    path = STORE / "labels" / "ability_candidates" / f"{sid}.jsonl"
    rows = [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    geo = np.load(STORE / "geometry" / f"{sid}.npz", allow_pickle=True)
    floor = mm.floor_mask(geo["static"])

    cap = cv2.VideoCapture(src["path"])
    kept, dropped_self, dropped_line = [], 0, 0
    for r in rows:
        if r["colour"] in LINE_COLOURS and r["aspect"] >= LINE_ASPECT_MIN:
            dropped_line += 1
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * src["fps"])))
        ok, frame = cap.read()
        if ok:
            mx0, my0, mx1, my1 = r["roi"]
            crop = frame[my0:my1, mx0:mx1]
            cands = mm.self_rings(crop, floor)
            if any(np.hypot(c[1] - r["x"], c[2] - r["y"]) < SELF_PX for c in cands):
                dropped_self += 1
                continue
        kept.append(r)
    cap.release()

    print(f"{sid}: {len(rows)} candidates -> {len(kept)} kept "
          f"({dropped_self} self-icon, {dropped_line} line-artifact)")
    if not a.dry_run:
        backup = path.with_suffix(".prefilter.jsonl.bak")
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        path.write_text("\n".join(json.dumps(r) for r in kept) + "\n", encoding="utf-8")
        print(f"  wrote {path} (original backed up to {backup.name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
