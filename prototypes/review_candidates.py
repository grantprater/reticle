"""Render every scan_ability_clip.py candidate to a contact sheet, and stamp
the file as reviewed -- the mechanical half of "look before you hand this to
the player."

    .\\.venv\\Scripts\\python.exe prototypes\\review_candidates.py <session>

Why this exists
----------------
2026-09-02: a labelling GUI was launched three times against candidate files
nobody had actually looked at first. Twice they were badly wrong (a
self-derived-geometry bug made real devices invisible and flagged the
player's own icon instead; a cross-session geometry borrow introduced pixel
mismatch that fragmented the viewcone into fake icon-sized blobs), and the player
caught both by spending his own time clicking through garbage. See
`prototypes/CLAUDE.md`, "verify before spending the time".

Writing "I ran the scanner" is not the same claim as "I looked at what it
found", and prose asking for the second one has already been skipped under
time pressure. So `label_ability.py`'s `candidates` source now REFUSES to
launch until a `.reviewed` stamp exists next to the candidates file, keyed to
that exact file's content -- rescan (new geometry, new detector code, more
frames) and the stamp goes stale automatically, no one has to remember to
delete it.

This script does not decide whether the candidates are GOOD. It only forces
the render to happen and to be looked at before the interactive tool will
run -- the actual judgement (is this really full of real objects, or still
noise) stays a human -- or a Claude actually looking at the PNG this writes,
not skimming the row count -- decision every time.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import cv2
import numpy as np

STORE = Path.home() / "reticle-store"
ZOOM = 8
PAD = 20
COLS = 5


def stamp_path(candidates_path: Path) -> Path:
    return candidates_path.with_suffix(".reviewed")


def content_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def is_reviewed(sid: str) -> bool:
    cand = STORE / "labels" / "ability_candidates" / f"{sid}.jsonl"
    stamp = stamp_path(cand)
    if not cand.is_file() or not stamp.is_file():
        return False
    return stamp.read_text(encoding="utf-8").strip() == content_hash(cand)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sid = a.session

    cand_path = STORE / "labels" / "ability_candidates" / f"{sid}.jsonl"
    if not cand_path.is_file():
        raise SystemExit(f"no candidates for {sid} -- run scan_ability_clip.py first")
    rows = [json.loads(l) for l in cand_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    rows = sorted(rows, key=lambda r: -r["n_observations"])

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    cap = cv2.VideoCapture(src["path"])
    tiles = []
    for r in rows:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(r["t_ms"] / 1000.0 * src["fps"])))
        ok, frame = cap.read()
        if not ok:
            continue
        mx0, my0, mx1, my1 = r["roi"]
        crop = frame[my0:my1, mx0:mx1]
        cx, cy = int(r["x"]), int(r["y"])
        tile = crop[max(0, cy - PAD):cy + PAD, max(0, cx - PAD):cx + PAD]
        big = cv2.resize(tile, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
        cv2.rectangle(big, (0, 0), (big.shape[1] - 1, big.shape[0] - 1), (0, 0, 255), 2)
        tiles.append((r, big))
    cap.release()
    if not tiles:
        raise SystemExit("nothing decoded -- is the source media still at its recorded path?")

    h = max(t.shape[0] for _r, t in tiles)
    w = max(t.shape[1] for _r, t in tiles)
    rows_n = (len(tiles) + COLS - 1) // COLS
    sheet = np.full((rows_n * (h + 30), COLS * (w + 10), 3), 255, np.uint8)
    for i, (r, t) in enumerate(tiles):
        rr, cc = divmod(i, COLS)
        y, x = rr * (h + 30) + 25, cc * (w + 10)
        sheet[y:y + t.shape[0], x:x + t.shape[1]] = t
        cv2.putText(sheet, f"n={r['n_observations']} c={r['colour']} a={r['aspect']:.1f}",
                    (x, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)

    out = Path(a.out) if a.out else Path.cwd() / f"review_{sid}.png"
    cv2.imwrite(str(out), sheet)
    stamp_path(cand_path).write_text(content_hash(cand_path), encoding="utf-8")
    print(f"wrote {out}  ({len(tiles)} candidates)")
    print(f"stamped {stamp_path(cand_path)} -- label_ability.py will now accept this file")
    print("LOOK AT THE IMAGE before running label_ability.py -- this script does not "
          "judge quality, it only unblocks the launch")
    return 0


if __name__ == "__main__":
    sys.exit(main())
