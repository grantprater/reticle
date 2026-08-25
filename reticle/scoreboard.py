"""Stage 02: the Tab scoreboard (design doc SS3).

The scoreboard is the only place the game states every player's kills, deaths
and assists at once, which makes it the check the killfeed cannot provide for
itself: killfeed attribution is inferred from pixels one entry at a time, and
this is the game telling you the running total outright. Open it once a round
and a divergence localises to a single round rather than a whole match.

Layout
------
A centred, semi-transparent table. Five ally rows over a round-history strip
over five enemy rows, each row a coloured slab -- green for the player's team,
red for the other -- carrying NAME, ULTIMATE, K, D, A, LOADOUT, CREDS, PING.
Rows are found from the slab row-profile rather than assumed at fixed offsets,
because the table is centred but the frame it sits on is not fixed and the
number of visible rows changes while it animates in.

The local player's row is the one the game outlines in yellow, and its name
renders as the literal string "Me" -- the same convention the killfeed uses.
The outline is what this keys on: it needs no template and no name reading.

Digit size
----------
These digits are h~11 at 1080p, *smaller* than either the scoreline (h~20-26)
or the bottom HUD (h~33), so they fall outside the geometry band in `ocr.py`
and are read against a band of their own. That is what `_raw_components` is for.
Nothing here reads names: identity comes from row position and the highlight,
and a name would need an alphabet this project has no templates for.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import cv2

from .ocr import Templates, _raw_components, normalise

# Slab colours. The table is semi-transparent, so these are far weaker than the
# killfeed's plates and the value floor has to sit low.
GREEN_H = (55, 100)
RED_H_LO, RED_H_HI = 12, 168
SLAB_S_MIN = 18
SLAB_V_MIN = 45
# A team's five rows render as one continuous slab -- the separators between
# them are hairlines that never break the colour. So each block is found whole
# and then divided by five, which the game guarantees: Valorant is always 5v5.
TEAM_ROWS = 5
# A row of the frame belongs to a block when this many of its pixels are slab.
MIN_TABLE_W = 500
# Plausible height for a whole five-row block at 1080p.
MIN_BLOCK_H, MAX_BLOCK_H = 90, 300
# The local player's row is tinted, which breaks its team's colour run in two.
# Runs separated by less than this are the same block.
BLOCK_GAP = 44

# Digit envelope for this table specifically. The area floor has to stay low:
# a "1" here is a 3x10 stroke of only 13 lit pixels, and an 18-pixel floor
# silently dropped it, turning every 15 into a 5 and every 16 into a 6 -- a
# leading digit lost without any drop in confidence. Height carries the
# rejection of specks instead.
D_MIN_H, D_MAX_H = 8, 16
D_MAX_W, D_MIN_AREA = 14, 10

# K, D and A cell centres as a fraction of table width, with a half-width.
KDA_X = (0.490, 0.542, 0.594)
KDA_HALF = 0.024
# The local player's row is outlined in a 2 px pale yellow-green line, measured
# at BGR (188, 243, 214). Blue is *high* in absolute terms, so the test that
# separates it from the slab is blue sitting well below green, not blue being
# dark. A whole line of it is what marks the row, hence the per-line test.
HL_MIN_G, HL_MIN_R, HL_B_UNDER_G = 200, 140, 45
HL_LINE_FRAC = 0.55
# The outline brackets one row, so its two lines each fall inside a neighbour's
# search window as well. Requiring a line at *both* edges is what picks out the
# row they belong to rather than the two beside it.
HL_SEARCH = 3


@dataclass(frozen=True)
class Row:
    """One scoreboard row. Any field may be None when it could not be read."""

    team: str                 # "ally" | "enemy"
    y0: int
    y1: int
    kills: int | None
    deaths: int | None
    assists: int | None
    is_player: bool           # the row the game outlines as yours

    @property
    def complete(self) -> bool:
        return None not in (self.kills, self.deaths, self.assists)


@dataclass(frozen=True)
class ScoreboardRead:
    """One frame's scoreboard, or `open_` False when none is on screen."""

    open_: bool
    rows: tuple[Row, ...] = ()
    x0: int = 0
    x1: int = 0

    @property
    def player(self) -> Row | None:
        return next((r for r in self.rows if r.is_player), None)


def _slabs(frame: np.ndarray):
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.int16)
    s = hsv[:, :, 1].astype(np.int16)
    v = hsv[:, :, 2].astype(np.int16)
    green = (h > GREEN_H[0]) & (h < GREEN_H[1]) & (s > SLAB_S_MIN) & (v > SLAB_V_MIN)
    red = ((h < RED_H_LO) | (h > RED_H_HI)) & (s > SLAB_S_MIN) & (v > SLAB_V_MIN)
    return green, red


def _block(mask: np.ndarray) -> tuple[int, int] | None:
    """The tallest run of frame rows that are slab across a table's width."""
    counts = mask.sum(axis=1)
    on = counts > MIN_TABLE_W
    runs, i, n = [], 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        runs.append([i, j])
        i = j
    # Join runs the player's tinted row split apart.
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= BLOCK_GAP:
            merged[-1][1] = run[1]
        else:
            merged.append(run)
    best = None
    for a, z in merged:
        if best is None or (z - a) > (best[1] - best[0]):
            best = (a, z)
    if best is None:
        return None
    return best if MIN_BLOCK_H <= best[1] - best[0] <= MAX_BLOCK_H else None


def _split(block: tuple[int, int]) -> list[tuple[int, int]]:
    a, z = block
    step = (z - a) / TEAM_ROWS
    return [(int(round(a + step * k)), int(round(a + step * (k + 1))))
            for k in range(TEAM_ROWS)]


def _read_cell(gray: np.ndarray, templates: Templates,
               min_conf: float, min_margin: float) -> int | None:
    """One K/D/A cell, read against this table's own digit envelope."""
    binary, raw = _raw_components(gray)
    keep = []
    for x, y, w, h, area in raw:
        if D_MIN_H <= h <= D_MAX_H and w <= D_MAX_W and area >= D_MIN_AREA:
            keep.append((x, y, w, h))
    if not keep:
        return None
    keep.sort(key=lambda c: c[0])
    text, worst, margin = "", 1.0, 1.0
    for x, y, w, h in keep:
        label, conf, mar = templates.match(
            type("G", (), {"bitmap": normalise(binary[y:y + h, x:x + w])})()
        )
        text += label
        worst = min(worst, conf)
        margin = min(margin, mar)
    if not text.isdigit() or worst < min_conf or margin < min_margin:
        return None
    value = int(text)
    # Nobody finishes a match with three digits of anything on this table.
    return value if 0 <= value <= 99 else None


def read_scoreboard(
    frame: np.ndarray,
    templates: Templates,
    min_confidence: float = 0.80,
    min_margin: float = 0.04,
) -> ScoreboardRead:
    """Read every row's K/D/A, and say which row is the local player's."""
    H, W = frame.shape[:2]
    green, red = _slabs(frame)
    ally, enemy = _block(green), _block(red)
    if ally is None or enemy is None:
        return ScoreboardRead(False)
    if enemy[0] < ally[0]:            # ally block always sits above the enemy one
        return ScoreboardRead(False)

    # Table edges from the ally block's own dense columns, which are cleaner
    # than a whole-frame profile that also catches the team bars up top.
    dense = np.where(green[ally[0]:ally[1]].mean(axis=0) > 0.5)[0]
    if dense.size == 0:
        return ScoreboardRead(False)
    x0, x1 = int(dense.min()), int(dense.max())
    tw = x1 - x0
    if tw < MIN_TABLE_W:
        return ScoreboardRead(False)

    bands = [(a, z, "ally") for a, z in _split(ally)]
    bands += [(a, z, "enemy") for a, z in _split(enemy)]

    b, g, r = (frame[:, :, 0].astype(np.int16), frame[:, :, 1].astype(np.int16),
               frame[:, :, 2].astype(np.int16))
    highlight = (g > HL_MIN_G) & (r > HL_MIN_R) & (b < g - HL_B_UNDER_G)
    inner = slice(x0 + 40, max(x0 + 41, x1 - 40))
    hl_line = highlight[:, inner].mean(axis=1)

    def outlined(y: int) -> bool:
        lo, hi = max(0, y - HL_SEARCH), min(len(hl_line), y + HL_SEARCH + 1)
        return bool(hi > lo and hl_line[lo:hi].max() > HL_LINE_FRAC)

    rows: list[Row] = []
    for a, z, team in bands:
        vals = []
        for fx in KDA_X:
            cx = x0 + int(fx * tw)
            hw = max(6, int(KDA_HALF * tw))
            cell = frame[a + 2:z - 2, cx - hw:cx + hw]
            if cell.size == 0:
                vals.append(None)
                continue
            vals.append(_read_cell(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY),
                                   templates, min_confidence, min_margin))
        rows.append(Row(team=team, y0=int(a), y1=int(z),
                        kills=vals[0], deaths=vals[1], assists=vals[2],
                        is_player=outlined(a) and outlined(z)))
    return ScoreboardRead(True, tuple(rows), x0, x1)
