r"""The killfeed assist panel, read from the ROI crop cache.

    .\.venv\Scripts\python.exe prototypes\assist_panel.py sheet [--per 12] [--sessions N]

An assisted kill draws the assisters' portraits, each with an ability icon to
its right, left of the killer's portrait and smaller
[domain:killfeed/assist-panel]; the killstreak numeral uses the same space
[domain:killfeed/killstreak-indicator]. `sheet` frames the region left of the
killer's portrait (anchored by `killfeed.killer_name_start`) for entries drawn
uniformly (seeded) from each session's stored killfeed frames, enlarged, so the
layout is read from pixels before any detector exists; what it showed is
[domain:killfeed/assist-panel-layout]. `edge_columns` flags columns carrying
the panel's top and bottom edges; it finds portrait cells, not icon cells,
and cannot count assisters, so it only stratifies `label_assists.py`'s
sample. Decodes nothing.
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

OUT = Store().root / "analysis" / "assist_panel"
SEED = 20260925
#: Columns left of the killer portrait's left edge that the sheet shows.
LEFT = 120
#: The panel's height as a fraction of the band: 18 rows of 34, measured on
#: four assisted entries (a06f04a0059f 185.0 s, 223d636bf8d2 823.5 s,
#: 3694746e4e54 602.5 s, bdfdcf009dba 210.0 s).
PANEL_FRAC = 18 / 34
#: An edge column: summed BGR step across the panel's top or bottom row.
EDGE_MIN = 60
#: The world below the panel must be this many times smoother than the edge.
EDGE_OVER_WORLD = 2.5
#: Unflagged columns a panel run may bridge, and how far its right end may sit
#: from the killer portrait's left edge.
RUN_GAP = 4
RIGHT_TOL = (-14, 4)


def edge_columns(crop: np.ndarray, y0: int, y1: int, a: int, b: int) -> np.ndarray:
    """Per column in [a, b): does it carry the panel's top and bottom edges?"""
    img = crop.astype(np.int32)
    p = int(round(PANEL_FRAC * (y1 - y0)))
    if y0 < 1 or y0 + p + 2 > img.shape[0]:
        return np.zeros(b - a, bool)
    step = lambda r: np.abs(img[r, a:b] - img[r + 1, a:b]).sum(axis=1)
    top, bottom, world = step(y0 - 1), step(y0 + p - 1), step(y0 + p)
    return ((top >= EDGE_MIN) & (bottom >= EDGE_MIN)
            & (bottom >= EDGE_OVER_WORLD * np.maximum(world, 8)))


def panel_extent(crop: np.ndarray, y0: int, y1: int, left: int) -> tuple[int, int] | None:
    """The assist panel's columns [x0, x1), or None when no panel abuts `left`."""
    a = max(0, left - LEFT)
    on = edge_columns(crop, y0, y1, a, max(a, left + RIGHT_TOL[1]))
    xs = np.flatnonzero(on) + a
    if not len(xs) or not (left + RIGHT_TOL[0] <= xs[-1] < left + RIGHT_TOL[1]):
        return None
    x0 = xs[-1]
    for x in xs[::-1]:
        if x0 - x > RUN_GAP + 1:
            break
        x0 = x
    return (int(x0), int(xs[-1]) + 1)


def entries(sid: str, n: int):
    """(t_ms, view, crop, portrait_left) for up to `n` entries, one frame each."""
    store = Store()
    man = store.read_manifest(sid)
    prof = get_profile(man["source_profile"])
    cache, why = RoiCache.load(store.root, man, prof, "killfeed")
    if cache is None:
        return
    roi = kf.killfeed_roi(prof)
    W, H = int(man["source"]["width"]), int(man["source"]["height"])
    x0, y0, x1, y1 = cache.rect_of("killfeed")
    by_t = {}
    for r in store.read_events("killfeed_portrait", sid):
        if r.get("kind") == "portrait_observation" and r.get("role") == "killer":
            by_t.setdefault(float(r["t_ms"]), []).append(int(r["slot"]))
    picks = [(t, s) for t, ss in by_t.items() for s in ss]
    random.Random(SEED).shuffle(picks)
    picks = sorted(picks[:n])
    for smp in cache.samples(sorted({t for t, _ in picks}), rois="killfeed"):
        crop = smp.frame[y0:y1, x0:x1]
        _g, _r, white = kf._plate_masks(crop, np.ones(crop.shape[:2], bool))
        want = {s for t, s in picks if t == smp.t_ms}
        for v in kf.analyse_killfeed(smp.frame, roi, W, H, profile_name=prof.name):
            if v.slot in want and v.killer_run and v.victim_run and v.y1 - v.y0 >= 8:
                name0 = kf.killer_name_start(white[v.y0:v.y1], v.killer_run)
                left = name0 - int(round(kf.PORTRAIT_ASPECT * (v.y1 - v.y0)))
                yield smp.t_ms, v, crop, left


def sheet(per: int, sessions: int) -> None:
    sids = sorted(p.stem for p in (Store().root / "roi_cache" / "hud").glob("*/*.json"))
    tiles = []
    for sid in sids[:sessions]:
        for t, v, crop, left in entries(sid, per):
            if left < 0:                       # the killer's portrait is clipped
                continue
            pad = np.pad(crop[v.y0:v.y1], ((0, 0), (LEFT, 20), (0, 0)))
            tile = pad[:, left:left + LEFT + 20].copy()
            tile = cv2.resize(tile, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
            cv2.line(tile, (3 * LEFT, 0), (3 * LEFT, 6), (0, 255, 255), 1)
            ext = panel_extent(crop, v.y0, v.y1, left)
            if ext is not None:
                p = int(round(PANEL_FRAC * (v.y1 - v.y0)))
                cv2.rectangle(tile, (3 * (ext[0] - left + LEFT), 1),
                              (3 * (ext[1] - left + LEFT) - 1, 3 * p - 1), (0, 255, 0), 1)
            lab = np.full((14, tile.shape[1], 3), 20, np.uint8)
            cv2.putText(lab, f"{sid} {t / 1000:.1f}s s{v.slot}", (2, 11), 0, 0.4,
                        (255, 255, 255), 1)
            tiles.append(np.vstack([lab, tile]))
    OUT.mkdir(parents=True, exist_ok=True)
    cols = 3
    th = max(t.shape[0] for t in tiles)
    tiles = [np.vstack([t, np.full((th - t.shape[0], t.shape[1], 3), 20, np.uint8)]) for t in tiles]
    tiles += [np.zeros_like(tiles[0])] * (-len(tiles) % cols)
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    for k in range(0, len(rows), 12):
        path = OUT / f"sheet_{k // 12}.png"
        cv2.imwrite(str(path), np.vstack(rows[k:k + 12]))
        print(path)


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sheet")
    s.add_argument("--per", type=int, default=12)
    s.add_argument("--sessions", type=int, default=20)
    a = ap.parse_args()
    if a.cmd == "sheet":
        sheet(a.per, a.sessions)


if __name__ == "__main__":
    main()
