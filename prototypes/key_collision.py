r"""What ELSE lives in a colour key, read off label sheets already on disk.

    .\.venv\Scripts\python.exe prototypes\key_collision.py c40d950031bb
    .\.venv\Scripts\python.exe prototypes\key_collision.py c40d950031bb --radius 5

Why this exists
---------------
`self_mask` is named for the local player and is not a self key. It is a
YELLOW key, and the widget draws several yellow things: the player's ring, the
dropped spike, the planted spike, the carried-spike badge and the site paint.
The self reader's 8.13% wrong-object rate is what that collision costs, and
until each of those has a reader of its own no channel can say which one a fit
landed on. `docs/MINIMAP_APPEARANCE_MATCHING.md` plans the readers; this
measures the collision they exist to resolve.

It needs no decode. `label_self_fit.py` writes its candidate sheets as
`INTER_NEAREST` x5 crops with no colour transform, so sampling every fifth
pixel recovers the source frame exactly. The player has already said what each
one is. So the keyed share of a disc at each labelled position is free, and it
is measured per ANSWER: how much of the self key does a spike hold, against
how much the player holds.

The disc stops short of the annotation ring. That ring is drawn at
`11 * scale` source px in `RING = (70, 240, 250)`, which passes `self_mask` --
so a radius at or past it would measure the annotation instead of the game.
`--radius` defaults to 5 for that reason and refuses to go past 7.

What it cannot say
------------------
The disc is centred on the ACCEPTED FIT, not on the object, and the player's
key is an annulus at r 6-9 while the spike's is filled. So a small disc
undercounts the player by construction, and the comparison is a lower bound on
the collision rather than a fair contest of shape. Settling shape needs the
radial profile, which needs the frames the annotation ring covers.

Diagnostic only. It labels nothing, changes no reader, and selects no
threshold -- `c40d950031bb` is the frozen self-fit evaluation set.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle.minimap import ally_mask, self_mask  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

#: `label_self_fit.sheet` builds every sheet with these. Restated rather than
#: imported because that module opens a video at import-time argument parsing;
#: the assertion below fails loudly if the sheet layout ever moves.
HALF, ZOOM, BAR_H, PAD = 34, 5, 26, 6
RING = (70, 240, 250)


def asked_panel(img: np.ndarray, n: int = 3) -> tuple[int, int]:
    """The panel bordered in `RING` is the instant the player answered."""
    w = img.shape[1] // n
    best, best_hits = 0, -1
    for i in range(n):
        col = img[BAR_H:BAR_H + 6, i * w + PAD:i * w + PAD + 8]
        hits = int((np.abs(col.astype(int) - RING).sum(axis=2) < 40).sum())
        if hits > best_hits:
            best, best_hits = i, hits
    return best, w


def source_patch(img: np.ndarray, x: float, y: float, r: int) -> np.ndarray:
    """The (2r+1)^2 SOURCE pixels around the ringed position of the asked panel."""
    idx, w = asked_panel(img)
    # `sheet` clamps the crop origin at 0 and magnifies from there, so the ring
    # sits at `(x - x0) * ZOOM` rather than always at the panel's centre.
    x0, y0 = max(0, int(x) - HALF), max(0, int(y) - HALF)
    cx = idx * w + PAD + int((x - x0) * ZOOM)
    cy = BAR_H + int((y - y0) * ZOOM)
    n = 2 * r + 1
    out = np.zeros((n, n, 3), np.uint8)
    for j in range(n):
        yy = cy + (j - r) * ZOOM + ZOOM // 2
        for i in range(n):
            xx = cx + (i - r) * ZOOM + ZOOM // 2
            if 0 <= yy < img.shape[0] and 0 <= xx < img.shape[1]:
                out[j, i] = img[yy, xx]
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--set", default="self_fit", help="label set under <store>/labels")
    ap.add_argument("--radius", type=int, default=5,
                    help="disc radius in SOURCE px; must stay inside the annotation ring")
    args = ap.parse_args()
    if not 1 <= args.radius <= 7:
        print("--radius must be 1-7: the annotation ring sits at about 7.8 px "
              "and keys as self.", file=sys.stderr)
        return 2

    root = Path(args.store) / "labels" / args.set
    rows = [json.loads(l) for l in
            (root / f"{args.session}.jsonl").read_text(encoding="utf-8").splitlines()
            if l.strip()]
    r = args.radius
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    circ = (yy ** 2 + xx ** 2) <= r * r

    by: dict[str, list[tuple[float, float]]] = collections.defaultdict(list)
    missing = 0
    for row in rows:
        img_path = root / args.session / row.get("image", "")
        if not img_path.exists():
            missing += 1
            continue
        img = cv2.imread(str(img_path))
        if img is None:
            missing += 1
            continue
        patch = source_patch(img, row["x"], row["y"], r)
        by[row["answer"]].append((
            float(((self_mask(patch) > 0) & circ).sum() / circ.sum()),
            float(((ally_mask(patch) > 0) & circ).sum() / circ.sum())))

    print(f"{args.session}   disc r={r} px   {sum(len(v) for v in by.values())} "
          f"labelled positions" + (f"   ({missing} sheets missing)" if missing else ""))
    print(f"\n{'answer':14s} {'n':>4s}  {'self key: mean  med':>22s}  "
          f"{'ally key: mean  med':>22s}")
    for k, v in sorted(by.items(), key=lambda kv: -len(kv[1])):
        s = np.array([a for a, _ in v])
        a = np.array([b for _, b in v])
        print(f"{k:14s} {len(v):4d}  {s.mean():11.3f} {np.median(s):8.3f}  "
              f"{a.mean():11.3f} {np.median(a):8.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
