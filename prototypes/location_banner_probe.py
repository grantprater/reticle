"""First look: the "current location" text banner above the minimap widget.

    .\\.venv\\Scripts\\python.exe prototypes\\location_banner_probe.py <session> [--stride 4]

Purely exploratory. Samples frames across the session, crops a generous box
above the minimap ROI (no profile ROI exists for this yet -- margins are
hand-guessed from one frame and may want tightening once real samples are in
hand), masks to bright text pixels (removes the varying world behind it, same
reasoning as `floor_mask` in `minimap_position.py`), and greedily clusters by
mask IoU so near-identical renders of the same string collapse together.

No OCR library is installed (checked: no pytesseract, no easyocr), and Tesseract
needs a separate system install anyway. Given the closed set of named regions
per map is small (a dozen or so), this follows the project's established
pattern instead: mine templates from real footage, one human label per unique
cluster, then it's exact-match forever after -- same shape as `glyphs.py`'s
digit templates and the portrait/roster identification work, not general OCR.

This script only clusters and dumps one representative crop per cluster. It
does not read the text -- that's a human pass on the dump.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import decode                             # noqa: E402
from reticle.profiles import get_profile              # noqa: E402

STORE = Path.home() / "reticle-store"
TEXT_V_MIN = 200  # bright text against a varying world; same idea as killfeed's plate test
MASK_SIZE = (140, 28)  # resize target before comparing, so text position dominates over noise
IOU_SAME = 0.55


def banner_box(mm_box, w, h):
    x0, y0, x1, y1 = mm_box
    mm_w = x1 - x0
    bx0 = max(0, x0 - 40)
    bx1 = min(w, x0 + mm_w + 140)
    by0 = 0
    by1 = min(h, y0 + 15)
    return bx0, by0, bx1, by1


def text_mask(crop):
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    m = (gray > TEXT_V_MIN).astype(np.uint8)
    return cv2.resize(m, MASK_SIZE, interpolation=cv2.INTER_AREA)


def iou(a, b):
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return inter / union if union else (1.0 if inter == union else 0.0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--stride", type=float, default=4.0, help="seconds between samples")
    a = ap.parse_args()
    sid = a.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    mm_box = next(r for r in prof.rois if r.name == "minimap").pixels(w, h)
    bx0, by0, bx1, by1 = banner_box(mm_box, w, h)
    print(f"banner box: x {bx0}-{bx1}  y {by0}-{by1}  ({bx1-bx0}x{by1-by0})")

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(a_, b_) for a_, b_, s in zip(tbl.column("t_start_ms").to_pylist(),
                                           tbl.column("t_end_ms").to_pylist(),
                                           tbl.column("state").to_pylist()) if s == "active"]

    # One sequential decode.sample_at() pass over every stride timestamp,
    # instead of one cap.set() seek per sample -- see reticle/decode.py and
    # chokepoint_eval.py, which measured this pattern pinning every core for
    # ~50 min running three sessions back to back (2026-09-02).
    stride_ms = a.stride * 1000.0
    targets = []
    for s0, s1 in spans:
        t = s0
        while t < s1:
            targets.append(t)
            t += stride_ms

    clusters = []  # list of dicts: mask, count, first_t, sample_crop
    n_samples = 0
    for sample in decode.sample_at(str(src["path"]), targets, fps):
        n_samples += 1
        crop = sample.frame[by0:by1, bx0:bx1]
        m = text_mask(crop)
        if m.sum() < 15:  # essentially blank -- no banner text this frame
            continue
        best, best_iou = None, 0.0
        for c in clusters:
            v = iou(m, c["mask"])
            if v > best_iou:
                best, best_iou = c, v
        if best is not None and best_iou >= IOU_SAME:
            best["count"] += 1
        else:
            clusters.append({"mask": m, "count": 1, "first_t": sample.t_ms, "sample": crop.copy()})

    clusters.sort(key=lambda c: -c["count"])
    print(f"{n_samples} frames sampled, {len(clusters)} distinct clusters "
          f"(non-blank: {sum(c['count'] for c in clusters)})")
    out_dir = Path.cwd() / f"banner_{sid}"
    out_dir.mkdir(exist_ok=True)
    for i, c in enumerate(clusters):
        up = cv2.resize(c["sample"], None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
        name = f"cluster{i:02d}_n{c['count']}_t{c['first_t']/1000:.0f}s.png"
        cv2.imwrite(str(out_dir / name), up)
        print(f"  cluster {i:2d}  n={c['count']:4d}  first seen t={c['first_t']/1000:.0f}s  -> {name}")
    print(f"\nwrote {len(clusters)} representative crops to {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
