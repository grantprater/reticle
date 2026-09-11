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

Owns [owns:scoreboard-row].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import cv2

from .ocr import Templates, _raw_components, normalise
from .version import SCOREBOARD_VERSION

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
# Credits render as ``<currency mark> N,NNN``. The mark and comma fall outside
# the digit envelope below, so the existing digit templates read the value.
# These fractions were measured after inspecting fully expanded 1080p boards
# at 542s and 1568s of session 7010b3d62460.
CREDITS_X = 0.880
CREDITS_HALF = 0.035
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
    credits: int | None = None
    credits_reason: str | None = None
    credits_confidence: float | None = None
    credits_margin: float | None = None
    credits_candidate: int | None = None

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


def _block(mask: np.ndarray, merge_gap: int = BLOCK_GAP) -> tuple[int, int] | None:
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
    # Join runs the player's tinted row split apart. Only the ally block can
    # contain that row. On the enemy colour, merging nearby runs can swallow
    # the red round-history marks between the teams and shift all five rows.
    merged: list[list[int]] = []
    for run in runs:
        if merged and run[0] - merged[-1][1] <= merge_gap:
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


def _read_cell_detail(gray: np.ndarray, templates: Templates,
                      min_conf: float, min_margin: float,
                      maximum: int) -> tuple[int | None, str | None,
                                              float | None, float | None,
                                              int | None]:
    """One numeric cell plus the reason an answer was refused."""
    binary, raw = _raw_components(gray)
    keep = []
    for x, y, w, h, area in raw:
        if D_MIN_H <= h <= D_MAX_H and w <= D_MAX_W and area >= D_MIN_AREA:
            keep.append((x, y, w, h))
    if not keep:
        return None, "no_digits", None, None, None
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
        reason = ("not_a_number" if not text.isdigit() else
                  "low_confidence" if worst < min_conf else "low_margin")
        candidate = int(text) if text.isdigit() else None
        return None, reason, worst, margin, candidate
    value = int(text)
    if not 0 <= value <= maximum:
        return None, "out_of_range", worst, margin, value
    return value, None, worst, margin, value


def _read_cell(gray: np.ndarray, templates: Templates,
               min_conf: float, min_margin: float) -> int | None:
    """One K/D/A cell, read against this table's own digit envelope."""
    return _read_cell_detail(gray, templates, min_conf, min_margin, 99)[0]


def read_scoreboard(
    frame: np.ndarray,
    templates: Templates,
    min_confidence: float = 0.80,
    min_margin: float = 0.04,
) -> ScoreboardRead:
    """Read every row's K/D/A, and say which row is the local player's."""
    H, W = frame.shape[:2]
    green, red = _slabs(frame)
    ally, enemy = _block(green), _block(red, merge_gap=0)
    if ally is None or enemy is None:
        return ScoreboardRead(False)
    if enemy[0] < ally[0]:            # ally block always sits above the enemy one
        return ScoreboardRead(False)
    # The red match-history strip can be connected to the enemy slab by its
    # own marks, so even an unmerged red run may begin too high. Both teams use
    # the same five-row geometry in one animation state; anchor the enemy rows
    # at the bottom of the red slab and take their height from the ally block.
    team_h = ally[1] - ally[0]
    if enemy[1] - enemy[0] != team_h:
        enemy = (enemy[1] - team_h, enemy[1])

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
        cx = x0 + int(CREDITS_X * tw)
        hw = max(10, int(CREDITS_HALF * tw))
        credit_cell = frame[a + 2:z - 2, cx - hw:cx + hw]
        if credit_cell.size:
            credit, credit_reason, credit_conf, credit_margin, credit_candidate = _read_cell_detail(
                cv2.cvtColor(credit_cell, cv2.COLOR_BGR2GRAY), templates,
                min_confidence, min_margin, 9000)
            if credit_candidate is not None and credit_candidate % 50:
                credit, credit_reason = None, "not_credit_increment"
        else:
            credit, credit_reason, credit_conf, credit_margin, credit_candidate = (
                None, "empty_cell", None, None, None)
        rows.append(Row(team=team, y0=int(a), y1=int(z),
                        kills=vals[0], deaths=vals[1], assists=vals[2],
                        is_player=outlined(a) and outlined(z), credits=credit,
                        credits_reason=credit_reason,
                        credits_confidence=credit_conf,
                        credits_margin=credit_margin,
                        credits_candidate=credit_candidate))
    return ScoreboardRead(True, tuple(rows), x0, x1)


def portrait_observations(frame: np.ndarray, board: ScoreboardRead) -> list[dict]:
    """Context-free colour evidence for each scoreboard portrait.

    The detector emits the descriptor and source box, never an agent identity.
    Cross-channel identity belongs to reconciliation.
    """
    if not board.open_ or not board.rows:
        return []
    row_h = board.rows[0].y1 - board.rows[0].y0
    width = max(4, int(round(row_h * 0.79)))
    lo = max(0, board.x0 - 2 * row_h)
    hi = min(frame.shape[1], board.x0 + 3 * row_h)
    if hi - lo < width + 4:
        return []
    profile = np.zeros(hi - lo, np.float32)
    # A row whose band has no pixels is not evidence, and it used to be a
    # CRASH: `cvtColor` asserts on an empty Mat, so one degenerate row killed
    # the whole scan mid-corpus (c62c2b06bcfb, 2026-09-09). `row_h` is taken
    # from the FIRST row, so nothing here guarantees the others have height.
    # The per-row loop below already refuses the same shape; this is that guard
    # moved to where the exception actually came from.
    used = 0
    for row in board.rows:
        band = frame[row.y0 + 1:row.y1 - 1, lo:hi]
        if band.shape[0] < 1 or band.shape[1] < 1:
            continue
        gray = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
        profile += np.abs(cv2.Sobel(
            gray.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)).mean(0)
        used += 1
    if not used:
        return []
    profile /= used
    profile = np.convolve(profile, np.ones(3) / 3, "same")
    start = max(0, board.x0 - lo + int(0.6 * width))
    stop = min(len(profile), board.x0 + 2 * row_h - lo)
    if stop - start < 6:
        return []
    gap = start + int(np.argmin(profile[start:stop]))
    x0 = max(lo, lo + gap - width)
    result = []
    for index, row in enumerate(board.rows):
        art = frame[row.y0:row.y1, x0:x0 + width]
        if art.shape[0] <= 4 or art.shape[1] <= 4:
            continue
        gray = cv2.cvtColor(art, cv2.COLOR_BGR2GRAY).astype(np.float32)
        detail = float(np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).mean())
        hsv = cv2.cvtColor(art, cv2.COLOR_BGR2HSV)
        hb = (hsv[:, :, 0].astype(int) * 10 // 180).clip(0, 9)
        sb = (hsv[:, :, 1].astype(int) * 3 // 256).clip(0, 2)
        vb = (hsv[:, :, 2].astype(int) * 3 // 256).clip(0, 2)
        hist = np.bincount(((hb * 3 + sb) * 3 + vb).ravel(),
                           minlength=90).astype(np.float32)
        hist /= max(1.0, float(hist.sum()))
        result.append({"display_row": index, "portrait_x0": x0,
                       "portrait_y0": row.y0, "portrait_x1": x0 + width,
                       "portrait_y1": row.y1, "portrait_detail": detail,
                       "portrait_composition": hist.tolist()})
    return result


class ScoreboardReader:
    """Sparse context-free scoreboard observations for a shared decode pass."""

    def __init__(self, profile_name: str, hz: float = 2.0, spans=None,
                 min_confidence: float = 0.80, min_margin: float = 0.04):
        self.name, self.hz, self.spans = "scoreboard", hz, spans
        self.templates = Templates.load(profile_name)
        self.min_confidence, self.min_margin = min_confidence, min_margin
        self.frames_offered = 0
        self.frames_open = 0
        self.rows: list[dict] = []

    def feed(self, sample) -> None:
        self.frames_offered += 1
        board = read_scoreboard(sample.frame, self.templates,
                                self.min_confidence, self.min_margin)
        if not board.open_:
            return
        self.frames_open += 1
        portraits = {r["display_row"]: r for r in portrait_observations(sample.frame, board)}
        for index, row in enumerate(board.rows):
            self.rows.append({
                "frame_idx": int(sample.frame_idx), "t_ms": float(sample.t_ms),
                "display_row": index, "team": row.team,
                "row_y0": row.y0, "row_y1": row.y1,
                "table_x0": board.x0, "table_x1": board.x1,
                "kills": row.kills, "deaths": row.deaths, "assists": row.assists,
                "is_player": row.is_player, "credits": row.credits,
                "credits_candidate": row.credits_candidate,
                "credits_reason": row.credits_reason,
                "credits_confidence": row.credits_confidence,
                "credits_margin": row.credits_margin,
                **portraits.get(index, {
                    "portrait_x0": None, "portrait_y0": None,
                    "portrait_x1": None, "portrait_y1": None,
                    "portrait_detail": None, "portrait_composition": None,
                }),
            })

    def events(self, session_id: str) -> list[dict]:
        common = {"session_id": session_id, "scoreboard_version": SCOREBOARD_VERSION,
                  "source": "scoreboard"}
        coverage = {**common, "kind": "coverage", "frames_offered": self.frames_offered,
                    "frames_open": self.frames_open}
        return [coverage] + [{**common, "kind": "row_observation",
                              "observation_key":
                                  f"{session_id}:{r['frame_idx']}:{r['display_row']}",
                              **r} for r in self.rows]
