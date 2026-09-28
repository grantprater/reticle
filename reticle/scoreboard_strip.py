r"""The round-history strip: a second witness that the Tab scoreboard is on screen.

    .\.venv\Scripts\python.exe -m reticle strip <session> | --all     (stored crops, no decode)

Owns [owns:scoreboard-strip].

Ported from `prototypes/scoreboard_strip.py` at its 0.2.0, whose docstring and
`docs/SCOREBOARD_PRESENCE.md` hold the measurements behind every constant; the
rule and the constants are the prototype's, unchanged, so the stored verdicts
reproduce its counts. The prototype stays as the experiment record and
imports this reader.

What it reads. Between the ally and enemy blocks of the Tab board the game
draws two lines of round markers [domain:hud/scoreboard-round-history-strip].
The `hud` crop cache's `center` crop (frame x 883-1037, y 486-594 at
1920x1080) holds the strip whole: two marker lines at frame y 527 and 551, a
column every 21.6-22.4 px, each column marked on both lines by a dark dot, a
pale yellow-green dot or a round-result icon (teal on the upper line, red on
the lower).

Rule. Find dark dots (a compact spot at least DARK_CONTRAST darker than its
9x9 mean), yellow dots and icons whose centres lie within ROW_TOL of a
marker line. Fit one column lattice (pitch in PITCH_RANGE, phase free) that
puts the most marks in distinct (line, column) cells within ALIGN_TOL. The
strip is `present` when the lattice fills at least MIN_CELLS cells, at least
MIN_PER_LINE on each line and MIN_PAIRED columns on both lines: two lines of
marks in register, 24 px apart, which world texture does not draw. It is
`unreadable` when the crop is missing, or when it is not present and the
band is darker than MIN_BACKGROUND, where a dark dot could not show; it is
`absent` otherwise. Every verdict carries its reason and its counts.

What it is not. It does not read the rows, name an agent, or decide when the
board opened: `adjudication.scoreboard` reconciles it with the slab test
(`scoreboard.read_scoreboard`) sample by sample. The icons are round
outcomes; reading them as such is not this module's question.
"""
from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from .scoreboard import HL_B_UNDER_G, HL_LINE_FRAC, HL_MIN_G, HL_MIN_R
from .version import SCOREBOARD_STRIP_VERSION

#: The `hud` cache ROI the strip is read from.
ROI = "center"
ROW_Y = (527, 551)
ROW_TOL = 3
PITCH_RANGE = (20.5, 23.5)
PITCH_STEP = 0.1
ALIGN_TOL = 2.0
DARK_CONTRAST = 15
DARK_MAX_AREA, DARK_MAX_SIDE = 12, 4
YELLOW_CONTRAST, YELLOW_G_OVER_B, YELLOW_R_OVER_B = 40, 25, 20
YELLOW_AREA, YELLOW_MAX_SIDE = (3, 25), 6
ICON_OVER, ICON_OVER2 = 50, 40
ICON_AREA, ICON_SIDE = (15, 220), (6, 16)
MIN_CELLS, MIN_PER_LINE, MIN_PAIRED = 6, 2, 2
MIN_BACKGROUND = 24
BLUR = 9
#: The frame size the constants were measured at.
MEASURED_WH = (1920, 1080)


def _blob_centres(mask: np.ndarray, area: tuple[int, int], side: tuple[int, int]):
    """Centres (x, y) of the 8-connected components within the size bounds."""
    n, _, st, cen = cv2.connectedComponentsWithStats(mask.astype(np.uint8), connectivity=8)
    out = []
    for i in range(1, n):
        w, h, a = int(st[i][2]), int(st[i][3]), int(st[i][4])
        if area[0] <= a <= area[1] and side[0] <= max(w, h) <= side[1]:
            out.append((float(cen[i][0]), float(cen[i][1])))
    return out


def _marks(crop: np.ndarray, rows: tuple[int, int]):
    """Dark dots, yellow dots and icons near each marker line, as (line, x, kind)."""
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    loc = cv2.blur(g, (BLUR, BLUR))
    b, gg, r = (crop[:, :, k].astype(np.int16) for k in range(3))
    dark = (loc - g) >= DARK_CONTRAST
    yellow = (((g - loc) >= YELLOW_CONTRAST) & ((gg - b) >= YELLOW_G_OVER_B)
              & ((r - b) >= YELLOW_R_OVER_B))
    teal = ((gg - r) >= ICON_OVER) & ((b - r) >= ICON_OVER2)
    red = ((r - gg) >= ICON_OVER) & ((r - b) >= ICON_OVER2)
    found = []
    for kind, mask, area, side in (
            ("dark", dark, (1, DARK_MAX_AREA), (1, DARK_MAX_SIDE)),
            ("yellow", yellow, YELLOW_AREA, (1, YELLOW_MAX_SIDE)),
            ("teal", teal, ICON_AREA, ICON_SIDE),
            ("red", red, ICON_AREA, ICON_SIDE)):
        for x, y in _blob_centres(mask, area, side):
            for line, ry in enumerate(rows):
                if abs(y - ry) <= ROW_TOL:
                    found.append((line, x, kind))
    return found


def _lattice(marks):
    """The (pitch, phase) that puts the most marks in distinct (line, column)
    cells, and those cells; ties go to the smaller mean offset."""
    if not marks:
        return 0, float("inf"), None, None, {}
    lines = np.array([m[0] for m in marks])
    xs = np.array([m[1] for m in marks])
    best = (0, float("inf"), None, None)
    for pitch in np.arange(PITCH_RANGE[0], PITCH_RANGE[1] + 1e-9, PITCH_STEP):
        phases = np.unique(np.round(xs % pitch, 2))
        k = np.round((xs[None, :] - phases[:, None]) / pitch)
        d = np.abs(xs[None, :] - (phases[:, None] + k * pitch))
        ok = d <= ALIGN_TOL
        # distinct (line, column) cells per phase
        key = np.where(ok, lines[None, :] * 1000 + (k + 500), -1)
        key.sort(axis=1)
        n = ((np.diff(key, axis=1) != 0) & (key[:, 1:] >= 0)).sum(axis=1) + (key[:, 0] >= 0)
        mean = np.where(ok, d, 0).sum(axis=1) / np.maximum(1, ok.sum(axis=1))
        j = int(np.lexsort((mean, -n))[0])
        if n[j] > best[0] or (n[j] == best[0] and mean[j] < best[1]):
            best = (int(n[j]), float(mean[j]), float(pitch), float(phases[j]))
    n, mean, pitch, phase = best
    cells: dict[tuple[int, int], list] = {}
    if pitch is not None:
        for line, x, kind in marks:
            k = round((x - phase) / pitch)
            if abs(x - (phase + k * pitch)) <= ALIGN_TOL:
                cells.setdefault((line, k), []).append(kind)
    return n, mean, pitch, phase, cells


def read_strip(crop: np.ndarray | None, rect) -> dict:
    """`present`, `absent` or `unreadable` for one centre crop, with the reason
    and the counts it rests on. `rect` is the crop's frame rectangle."""
    if crop is None:
        return {"verdict": "unreadable", "reason": "no_crop"}
    x0, y0 = int(rect[0]), int(rect[1])
    rows = tuple(y - y0 for y in ROW_Y)
    if min(rows) - ROW_TOL < 0 or max(rows) + ROW_TOL >= crop.shape[0]:
        return {"verdict": "unreadable", "reason": "marker_lines_outside_crop"}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    background = float(np.median(np.concatenate(
        [g[ry - ROW_TOL:ry + ROW_TOL + 1].ravel() for ry in rows])))
    # Diagnostic only: the frame row, just above the strip, that carries the
    # scoreboard's own local-player outline test (`scoreboard`); it marks the
    # player on the last ally row. The verdict does not use it.
    b, gg, r = (crop[:, :, k].astype(np.int16) for k in range(3))
    hl = ((gg > HL_MIN_G) & (r > HL_MIN_R) & (b < gg - HL_B_UNDER_G)).mean(axis=1)
    top = hl[:max(0, rows[0] - 2 * ROW_TOL)]
    outline_y = int(np.argmax(top)) + y0 if top.size and top.max() > HL_LINE_FRAC else None
    marks = _marks(crop, rows)
    n, err, pitch, phase, cells = _lattice(marks)
    per_line = [sum(1 for (line, _) in cells if line == j) for j in (0, 1)]
    cols = Counter(k for (_, k) in cells)
    paired = sum(1 for c in cols.values() if c == 2)
    kinds = Counter()
    for (line, _), ks in cells.items():
        kinds[f"{ks[0]}_{line}"] += 1
    raw = Counter(f"{kind}_{line}" for line, _, kind in marks)
    ev = {"background": round(background, 1), "cells": n, "per_line": per_line,
          "paired": paired, "pitch": None if pitch is None else round(pitch, 2),
          "phase": None if phase is None else round(phase + x0, 2),
          "offset": None if pitch is None else round(err, 3),
          "marks": len(marks), "outline_y": outline_y,
          "aligned": dict(sorted(kinds.items())), "found": dict(sorted(raw.items()))}
    if n >= MIN_CELLS and min(per_line) >= MIN_PER_LINE and paired >= MIN_PAIRED:
        return {"verdict": "present", "reason": None, **ev}
    if background < MIN_BACKGROUND:
        return {"verdict": "unreadable", "reason": "band_too_dark_for_dark_dots", **ev}
    why = ("too_few_cells" if n < MIN_CELLS else
           "one_line_empty" if min(per_line) < MIN_PER_LINE else "lines_not_in_register")
    return {"verdict": "absent", "reason": why, **ev}


def strip_events(session_id: str, reads, rect, roi_cache_version: str) -> list[dict]:
    """A coverage row, then one `sample` row per cached frame.

    `reads` is `(frame_idx, t_ms, read_strip(...))` per cached frame, in frame
    order; `rect` is the centre crop's frame rectangle."""
    common = {"session_id": session_id, "scoreboard_strip_version": SCOREBOARD_STRIP_VERSION,
              "roi_cache_version": roi_cache_version, "source": "scoreboard_strip"}
    rows = [{**common, "kind": "sample", "frame_idx": int(f), "t_ms": float(t), **got}
            for f, t, got in reads]
    verdicts = Counter(r["verdict"] for r in rows)
    reasons = Counter(r["reason"] for r in rows if r["reason"] is not None)
    coverage = {**common, "kind": "coverage", "roi": ROI, "rect": [int(v) for v in rect],
                "frames": len(rows),
                "verdicts": {v: verdicts.get(v, 0) for v in ("present", "absent", "unreadable")},
                "reasons": dict(sorted(reasons.items()))}
    return [coverage] + rows
