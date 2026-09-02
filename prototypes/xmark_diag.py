"""Why does the fixed t+1.5s X-mark snapshot miss ~9-20% of teammate deaths?

    .\\.venv\\Scripts\\python.exe prototypes\\xmark_diag.py <session>

For every teammate death `xmark_eval.py` scored as "no X detected", scan a
wider window (0.3s to 4.5s after death, every 0.3s) and report whether a blue
blob shows up ANYWHERE in it -- and if so, when. Distinguishes "the fixed
offset was just wrong" from "the detector genuinely can't see this one".
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.profiles import get_profile                          # noqa: E402
import minimap_position as mp                                     # noqa: E402
from xmark_eval import teammate_deaths, xmark_blob                # noqa: E402

STORE = Path.home() / "reticle-store"


def main() -> int:
    sid = sys.argv[1]
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    box = mp._roi_px(prof, w, h)
    x0, y0, x1, y1 = box

    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    deaths = teammate_deaths(hud)

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]

    cap = cv2.VideoCapture(str(src["path"]))
    med = mp.static_map(cap, fps, spans, box)
    floor = mp.floor_mask(med)

    def frame_at(tm):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(tm / 1000.0 * fps)))
        ok, fr = cap.read()
        return fr[y0:y1, x0:x1] if ok else None

    out_dir = Path.cwd() / f"xmark_diag_{sid}"
    out_dir.mkdir(exist_ok=True)
    n_miss_at_15, n_found_wider, n_truly_missing = 0, 0, 0
    for a in deaths:
        td = a["t_first"]
        xb15 = xmark_blob(frame_at(td + 1500.0), floor)
        if xb15 is not None:
            continue
        n_miss_at_15 += 1
        found_at = None
        dt = 300.0
        while dt <= 4500.0:
            crop = frame_at(td + dt)
            if crop is not None:
                xb = xmark_blob(crop, floor)
                if xb is not None:
                    found_at = dt
                    break
            dt += 300.0
        if found_at is not None:
            n_found_wider += 1
            print(f"  t={td/1000:7.1f}s  MISSED at 1.5s, found at {found_at/1000:.1f}s "
                  f"(area {xb[0]})")
        else:
            n_truly_missing += 1
            print(f"  t={td/1000:7.1f}s  no blue blob anywhere in 0.3-4.5s window")
            # dump a few frames of the genuinely-missing ones for a look
            for dt2 in (500, 1500, 3000):
                crop = frame_at(td + dt2)
                if crop is not None:
                    up = cv2.resize(crop, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
                    cv2.imwrite(str(out_dir / f"t{td/1000:.0f}_p{dt2/1000:.1f}.png"), up)
    cap.release()

    print(f"\n{n_miss_at_15} missed at the fixed 1.5s offset")
    print(f"  {n_found_wider} found somewhere else in 0.3-4.5s (offset problem)")
    print(f"  {n_truly_missing} not found anywhere in that window (dumped to {out_dir})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
