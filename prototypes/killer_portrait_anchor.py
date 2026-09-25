r"""Where the killer's name begins, and so where the killer's portrait ends.

    .\.venv\Scripts\python.exe prototypes\killer_portrait_anchor.py eval SESSION [--sheet N]

`killfeed.portrait_observations` anchors the killer's portrait at the first
column of the killer's name run. `_band_text` keeps only glyphs on the name's
baseline, so a descender (y, g, p, j, q) drops out of the text mask; the gap
it leaves exceeds `NAME_GAP`, `name_run` takes the last run, and the run
starts mid-name ("na" of "Reyna" at a06f04a0059f 228.5 s). The box then sits
on the name and the face lies left of it.

`killfeed.killer_name_start` (killfeed-portrait-0.5.0, wired from here)
walks left from the run over glyph-sized white components inside the name's
text rows, descenders allowed, each within `NAME_GAP` of the last. `eval` reruns the killfeed reader from the `hud` ROI crop cache
over one session, counts anchors that move, and writes a sheet of moved
entries (old box yellow, new box green). Decodes nothing. Predictions are
`killer-portrait-anchor` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import killfeed as kf  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

OUT = Store().root / "analysis" / "killer_portrait_anchor"
name_start = kf.killer_name_start


def _views(sid: str):
    store = Store()
    man = store.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, prof, "killfeed")
    if cache is None:
        raise SystemExit(f"{sid}: no crop cache ({why})")
    roi = kf.killfeed_roi(prof)
    W, H = int(man["source"]["width"]), int(man["source"]["height"])
    x0, y0, x1, y1 = cache.rect_of("killfeed")
    ts = sorted({float(r["t_ms"]) for r in store.read_events("killfeed_portrait", sid)
                 if r.get("kind") == "portrait_observation"})
    for smp in cache.samples(ts, rois="killfeed"):
        crop = smp.frame[y0:y1, x0:x1]
        _g, _r, white = kf._plate_masks(crop, np.ones(crop.shape[:2], bool))
        for v in kf.analyse_killfeed(smp.frame, roi, W, H, profile_name=prof.name):
            if v.killer_run and v.victim_run and v.y1 - v.y0 >= 8:
                yield smp.t_ms, v, crop, white


def evaluate(sid: str, sheet: int) -> None:
    moved, total, tiles = [], 0, []
    for t, v, crop, white in _views(sid):
        total += 1
        new = name_start(white[v.y0:v.y1], v.killer_run)
        if new != v.killer_run[0]:
            moved.append((t, v, crop, new))
    print(f"{sid}: {len(moved)} of {total} killer anchors move "
          f"({100 * len(moved) / max(1, total):.1f}%); shift px "
          f"{sorted(v.killer_run[0] - n for _t, v, _c, n in moved)[:: max(1, len(moved) // 20)]}")
    random.Random(20260925).shuffle(moved)
    for t, v, crop, new in sorted(moved[:sheet], key=lambda m: m[0]):
        wide = int(round(kf.PORTRAIT_ASPECT * (v.y1 - v.y0)))
        b = crop[max(0, v.y0 - 3):v.y1 + 3, :v.wx0 + 4].copy()
        for s, col in ((v.killer_run[0] - 1, (0, 255, 255)), (new - 1, (0, 255, 0))):
            cv2.rectangle(b, (s - wide, 2 if col[2] else 4), (s, b.shape[0] - (3 if col[2] else 5)),
                          col, 1)
        tile = np.full((b.shape[0] + 12, 500, 3), 20, np.uint8)
        tile[12:, :min(500, b.shape[1])] = b[:, :500]
        cv2.putText(tile, f"{t / 1000:.1f}s slot{v.slot} {v.killer_run[0]}->{new}", (2, 10),
                    0, 0.35, (255, 255, 255), 1)
        tiles.append(tile)
    if tiles:
        OUT.mkdir(parents=True, exist_ok=True)
        img = cv2.resize(np.vstack(tiles), None, fx=1.5, fy=1.5, interpolation=cv2.INTER_NEAREST)
        path = OUT / f"{sid}_moved.png"
        cv2.imwrite(str(path), img)
        print(f"sheet -> {path}")


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("eval")
    e.add_argument("session")
    e.add_argument("--sheet", type=int, default=30)
    a = ap.parse_args()
    if a.cmd == "eval":
        evaluate(a.session, a.sheet)


if __name__ == "__main__":
    main()
