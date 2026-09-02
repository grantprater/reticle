"""Feasibility check: does the stored killfeed divider column crop a weapon icon?

    .\\.venv\\Scripts\\python.exe prototypes\\weapon_icon_scan.py <session> [--n 30] [--out sheet.png]

Nothing in this repo has ever read WHICH weapon killed anyone -- `killfeed.py`
only locates the icon well enough to use it as a divider between the killer's
name and the victim's (see `divider_of_ys`, `_band_text`). This is step zero,
per "look at the image before measuring": crop what the stored geometry
implies is the icon and put it in front of an eye before writing any matcher,
clusterer or template miner.

What is stored and what is guessed
-----------------------------------
`kf_entry_wx` packs each live entry's divider column (`wx0`, the icon's LEFT
edge -- see `killfeed.divider_of_ys`) but not `wx1`, so the icon's right edge
was never persisted. This script guesses a fixed crop width (`ICON_CROP_W`)
rather than re-deriving `wx1` from pixels, on purpose: if the guess is too
narrow or too wide, that will be obvious on the contact sheet, and that
observation is worth more than a second detector built before anyone has
looked at a single crop.

Ability kills have no weapon icon at all (`killfeed.py`'s open defects list:
"There is no weapon icon" for `c40d950031bb` 13:14) -- expect some crops here
to be garbage for that reason, not a sign the geometry is wrong.
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
from reticle import decode                                        # noqa: E402
from reticle.checks import track_entries                          # noqa: E402
from reticle.killfeed import ENTRY_H, FIRST_Y, PITCH, killfeed_roi  # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"
ICON_CROP_W = 42  # ICON_MIN_W (34) plus margin -- a guess, see module docstring
ZOOM = 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    sid = a.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h = int(src["width"]), int(src["height"])
    kf_roi = killfeed_roi(prof)
    if kf_roi is None:
        raise SystemExit(f"profile {prof.name} has no killfeed ROI")
    rx0, ry0, rx1, ry1 = kf_roi.pixels(w, h)

    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    t = hud.column("t_ms").to_pylist()
    masks = hud.column("kf_entry_mask").to_pylist()
    dividers = hud.column("kf_entry_wx").to_pylist() if "kf_entry_wx" in hud.column_names else None
    entries = [e for e in track_entries(t, masks, dividers) if e["counted"] and e["sig"]]
    print(f"{len(entries)} counted entries with a recorded divider, "
          f"of {sum(1 for e in track_entries(t, masks, dividers) if e['counted'])} total")

    entries = entries[:: max(1, len(entries) // a.n)][:a.n]
    targets = sorted((e["t_first"] + e["t_last"]) / 2.0 for e in entries)
    by_t = {(e["t_first"] + e["t_last"]) / 2.0: e for e in entries}

    crops = []
    for target, sample in zip(targets, decode.sample_at(str(src["path"]), targets, src["fps"])):
        e = by_t[target]
        wx0 = e["sig"]  # already the unpacked divider column for this entry's slot
        y0 = ry0 + FIRST_Y + e["slot"] * PITCH
        y1 = y0 + ENTRY_H
        x0 = rx0 + int(wx0)
        x1 = x0 + ICON_CROP_W
        crop = sample.frame[y0:y1, x0:x1]
        if crop.size:
            crops.append((e["t_first"], crop))

    if not crops:
        raise SystemExit("no crops decoded -- check the session has HUD L1 with dividers")

    ch = max(c.shape[0] for _t, c in crops) * ZOOM
    cw = max(c.shape[1] for _t, c in crops) * ZOOM
    pad = 4
    cols = 8
    rows = (len(crops) + cols - 1) // cols
    sheet = np.full((rows * (ch + pad) + pad, cols * (cw + pad) + pad, 3), 255, dtype=np.uint8)
    for i, (t_ms, crop) in enumerate(crops):
        big = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_NEAREST)
        r, c = divmod(i, cols)
        y = pad + r * (ch + pad)
        x = pad + c * (cw + pad)
        sheet[y:y + ch, x:x + cw] = big
        cv2.putText(sheet, f"{t_ms/1000:.0f}s", (x + 2, y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 0), 1, cv2.LINE_AA)

    out = Path(a.out) if a.out else Path.cwd() / f"weapon_icons_{sid}.png"
    cv2.imwrite(str(out), sheet)
    print(f"wrote {out}  ({len(crops)} crops, {ICON_CROP_W}px guessed width, {ZOOM}x)")
    print("PREDICT BEFORE YOU LOOK: is the icon fully inside the crop, cut off, "
          "or is this the wrong region entirely?")
    return 0


if __name__ == "__main__":
    sys.exit(main())
