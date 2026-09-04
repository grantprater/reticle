r"""Check a freshly recorded ability-demo clip BEFORE it is ingested.

    .\.venv\Scripts\python.exe prototypes\clip_preflight.py <video>... [--donor a06f04a0059f]

Why this exists, 2026-09-03
-----------------------------
the player records a sitting of one-agent demo clips back to back, and CLAUDE.md's
"Before ingesting any new capture" checklist is a list of settings that break
things SILENTLY -- extraction still returns answers, they are merely wrong. The
first clip of this sitting proved it: minimap orientation was left on
side-based, so the whole widget was rotated 180 degrees and nothing downstream
would have said so. A per-clip check costs seconds; finding it later costs the
sitting.

What it checks, and how each one is decided rather than eyeballed:

    widget size    the map's white line-work, measured inside the minimap ROI,
                   must span the same rows as a KNOWN bigmap session. The small
                   widget stops ~150 px higher. Restricted to the ROI because
                   anything bright elsewhere on screen is not this test's
                   business -- see ROI's comment.
    orientation    normalised cross-correlation of the clip's median map
                   against the donor's, and against the donor rotated 180.
                   Whichever wins IS the orientation -- a bounding box cannot
                   answer this, because a roughly centred map has nearly the
                   same box either way.
    top-left ROI   anything drawn over the minimap (the shooting-error readout
                   landed there on this account) shows as line-work reaching
                   further left than the donor's.

The median over sampled frames is what makes all three readable at all: the
widget is SEMI-TRANSPARENT over live scenery, so a single frame carries the
world moving behind it. Same trick `minimap_geometry` uses.

Reports, never fixes. A failure here is a capture setting, not a code change.

One limit, stated because the output can mislead: the correlation is not
alignment-invariant. It rotates the donor about the CROP centre rather than the
widget centre, and it cannot absorb a translation, so a clip whose widget sits
somewhere else scores low BOTH ways and reports "cannot tell" rather than
naming the rotation. That is the honest answer -- such a clip has already
failed the size and ROI checks -- but do not read "cannot tell" as "upright".
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

STORE = Path.home() / "reticle-store"
# The minimap ROI of valorant-16x9-bigmap, in pixels at 1080p, plus a small
# margin. Measuring INSIDE it is not a convenience: the Neon clip drew a bright
# vertical band down the frame's left edge, outside the widget entirely, and a
# whole-corner bounding box read that as the map growing 73 rows taller. A
# check that fires on content it was never asked about costs a re-record.
ROI = (15, 14, 480, 500)
W = H = 560
N = 41
ROT_MARGIN = 0.02      # ncc difference below this is "cannot tell"


def median_corner(path: str, n: int = N):
    cap = cv2.VideoCapture(str(path))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    buf = []
    for i in np.linspace(tot * 0.05, tot * 0.95, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            buf.append(fr[:H, :W])
    cap.release()
    if not buf:
        raise SystemExit(f"{path}: decoded no frames")
    return np.median(np.stack(buf), 0).astype(np.uint8)


def linework_bbox(med):
    """Bounding box of the map's white line-work, measured INSIDE the ROI.

    Returned in full-frame coordinates so it stays comparable to the donor's.
    """
    x0, y0, x1, y1 = ROI
    g = cv2.cvtColor(med[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    m = (g > np.percentile(g, 99.0)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return (int(xs.min()) + x0, int(ys.min()) + y0,
            int(xs.max()) + x0, int(ys.max()) + y0)


def ncc(a, b):
    a = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY).astype(np.float32)
    a, b = a - a.mean(), b - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float((a * b).sum() / d) if d else 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--donor", default="a06f04a0059f",
                    help="ingested session on the SAME map to compare against")
    ap.add_argument("--n", type=int, default=N)
    a = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{a.donor}.json").read_text())
    donor = median_corner(man["source"]["path"], a.n)
    dbb = linework_bbox(donor)
    print(f"donor {a.donor} [{man['source_profile']}]  linework bbox {dbb}\n")

    bad = 0
    for v in a.videos:
        med = median_corner(v, a.n)
        bb = linework_bbox(med)
        up, down = ncc(med, donor), ncc(med, cv2.rotate(donor, cv2.ROTATE_180))
        rows_ok = abs(bb[1] - dbb[1]) <= 6 and abs(bb[3] - dbb[3]) <= 6
        left_ok = bb[0] >= dbb[0] - 6
        if abs(up - down) < ROT_MARGIN:
            orient = f"CANNOT TELL  (ncc {up:+.3f} vs rot180 {down:+.3f})"
            ok_o = False
        elif up > down:
            orient, ok_o = f"upright      (ncc {up:+.3f} vs rot180 {down:+.3f})", True
        else:
            orient, ok_o = f"ROTATED 180  (ncc {up:+.3f} vs rot180 {down:+.3f})", False

        print(f"{Path(v).name}")
        print(f"   linework bbox {bb}")
        print(f"   [{'ok' if rows_ok else 'FAIL'}] widget size   rows {bb[1]}..{bb[3]} "
              f"vs donor {dbb[1]}..{dbb[3]}"
              f"{'' if rows_ok else '   <- small widget, or a different minimap size'}")
        print(f"   [{'ok' if ok_o else 'FAIL'}] orientation   {orient}")
        print(f"   [{'ok' if left_ok else 'FAIL'}] top-left ROI  left edge {bb[0]} "
              f"vs donor {dbb[0]}"
              f"{'' if left_ok else '   <- something is drawn over the minimap'}")
        if not (rows_ok and ok_o and left_ok):
            bad += 1
        print()
    print(f"{len(a.videos) - bad}/{len(a.videos)} clips pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
