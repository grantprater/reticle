"""One-off: montage every session's ally roster portraits, to eyeball for a Cypher.

    .\\.venv\\Scripts\\python.exe prototypes\\roster_scan.py [--out sheet.png]

Recorded 2026-09-02, asked whether any session has an ALLY Cypher (the cams
would need no reveal mechanic, and are "likely set up in the pre-round") --
nothing has ever identified agents on the ally side of the roster, only the
enemy side (needed for icon identification). Rather than build that pipeline,
just crop `hud_roster` from one early active frame per session and look: five
portraits at high zoom is enough to recognise Cypher's mask-and-coat silhouette
by eye, the same way agent identity was first read off the Tab scoreboard.
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
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"
ZOOM = 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    a = ap.parse_args()

    sessions = sorted(p.stem for p in (STORE / "manifests").glob("*.json"))
    rows = []
    for sid in sessions:
        man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
        src = man["source"]
        try:
            prof = get_profile(man["source_profile"])
        except Exception as ex:
            print(f"{sid}: skip ({ex})")
            continue
        roi = next((r for r in prof.rois if r.name == "hud_roster"), None)
        if roi is None:
            print(f"{sid}: no hud_roster ROI in {prof.name}")
            continue
        w, h = int(src["width"]), int(src["height"])
        x0, y0, x1, y1 = roi.pixels(w, h)

        spans_path = next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet"), None)
        t_ms = 30_000.0
        if spans_path is not None:
            tbl = pq.read_table(spans_path)
            starts = [s for s, state in zip(tbl.column("t_start_ms").to_pylist(),
                                            tbl.column("state").to_pylist()) if state == "active"]
            if starts:
                t_ms = starts[0] + 20000.0

        media = Path(src["path"])
        if not media.is_file():
            print(f"{sid}: source media missing ({media})")
            continue
        cap = cv2.VideoCapture(str(media))
        cap.set(cv2.CAP_PROP_POS_MSEC, t_ms)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            print(f"{sid}: could not decode at {t_ms:.0f}ms")
            continue
        crop = frame[y0:y1, x0:x1]
        rows.append((sid, prof.name, crop))
        print(f"{sid}: {prof.name}  {crop.shape[1]}x{crop.shape[0]} @ {t_ms/1000:.0f}s")

    if not rows:
        raise SystemExit("nothing decoded")

    cw = max(c.shape[1] for _s, _p, c in rows) * ZOOM
    ch = max(c.shape[0] for _s, _p, c in rows) * ZOOM
    pad, label_h = 6, 18
    sheet = np.full((len(rows) * (ch + label_h + pad) + pad, cw + 2 * pad, 3), 255, dtype=np.uint8)
    for i, (sid, prof_name, crop) in enumerate(rows):
        big = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_NEAREST)
        y = pad + i * (ch + label_h + pad)
        cv2.putText(sheet, f"{sid}  ({prof_name})", (pad, y + 12),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 0), 1, cv2.LINE_AA)
        sheet[y + label_h:y + label_h + ch, pad:pad + cw] = big

    out = Path(a.out) if a.out else Path.cwd() / "roster_scan.png"
    cv2.imwrite(str(out), sheet)
    print(f"\nwrote {out}  ({len(rows)} sessions, {ZOOM}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
