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
number of visible rows changes while it animates in. Where the strip's
rectangle is known, the profile counts slab pixels only in the table's
columns (`table_columns`): green or red world beside the board once moved
the rows and closed boards. Every pixel the reader reads then lies in
`reader_roi`, so the board reads the same pasted into black.

The world shows through the slabs and around them, and warm walls, sky and
floor pass the red test, so the tallest red run is often the world below the
board. Where the round-history strip witness (`scoreboard_strip`) sees its
two marker lines, the blocks are instead the runs that meet the strip: the
ally block ends just above the upper line and the enemy block begins just
below the lower one. Where no red run begins at the lower line, the line
still places the enemy rows, and a red run inside that span or the five
portraits there must confirm a slab. A block the strip does not bound, or
does not confirm, is refused. Where the strip is absent or unreadable, the
tallest runs decide, as they did at 0.7.0.

The table's left and right edges are its frame: in every row of both blocks
the row plates begin and end with a colour step, whatever world lies behind.
Where the profile gives the strip's rectangle, the reader fits the two steps
a table's width apart near the place the strip's centre predicts
(`_frame_edges`) and closes a board with no such frame; the green test's
dense columns decide only where no rectangle is known.

The local player's row is the one the game outlines in yellow, and its name
renders as the literal string "Me" -- the same convention the killfeed uses.
The outline is what this keys on: it needs no template and no name reading.

Numbers
-------
Kills, deaths, assists and credits read soft, as the scoreline does
(`ocr.read_layouts`): white-ink coverage against the row's local plate,
compared with DIN Next Medium 11 cells, the font and size the player card's
TextBlocks name, at the places those centred TextBlocks put one, two, three
or four digits (BOARD_PENS). A dead player's row draws its numbers grey;
each number is decided again at the tint its brightest cell shows. Every
unread number names its reason (`Row.kills_reason` and the rest).
Nothing here reads names: a name would need an alphabet this project has no
templates for. Each portrait is scored against the official agent art, raw and
unnamed; `adjudication.scoreboard` decides which agent a row holds and whether
the game has dimmed it as dead. The scoring is promoted from the measured
prototype `scoreboard_agent`.

Owns [owns:scoreboard-row].
"""

from __future__ import annotations

from collections import Counter, OrderedDict
from dataclasses import dataclass
import os

import numpy as np

import cv2

from . import appearance
from . import ocr
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
# A row of the frame belongs to a block when this many of its pixels are slab:
# of the table's TABLE_W columns where the strip's rectangle places them
# (`table_columns`), of the whole frame width where nothing places them.
MIN_TABLE_W = 500
# Plausible height for a whole five-row block at 1080p.
MIN_BLOCK_H, MAX_BLOCK_H = 90, 300
# The local player's row is tinted, which breaks its team's colour run in two.
# Runs separated by less than this are the same block.
BLOCK_GAP = 44
# Where the strip's marker lines (`scoreboard_strip.ROW_Y`) bound the blocks.
# Measured as the slab colour test's edge in the stored centre crop on the 19
# lineup sessions, at every sample the strip reads present and the slab test
# open: the ally slab ends at frame y 510 (median, [metric:scoreboard/strip-geometry@all-sessions#ally_end_median=510.0]),
# 17 rows above the upper line, and the enemy slab begins at y 568 (median, [metric:scoreboard/strip-geometry@all-sessions#enemy_start_median=568.0]),
# 17 rows below the lower line. Each edge lies within 2 px of that place on
# [metric:scoreboard/strip-geometry@all-sessions#ally_end_within_2px_frac=0.946] and
# [metric:scoreboard/strip-geometry@all-sessions#enemy_start_within_2px_frac=0.941] of the samples that show it
# (y 508 is the ally edge on some sessions). The tolerance is twice that spread.
STRIP_ALLY_GAP = 17
STRIP_ENEMY_GAP = 17
STRIP_TOL = 4
# Where no red run begins at the lower line, the line still places the enemy
# rows, and the colour test has only to confirm a slab in the span it
# predicts. The translucent slab's top rows fail the red test over pale sky,
# grey walls, dark models and violet effects. A red run over at least half
# the ally height inside the span confirms it; failing that, the five
# portraits at those rows must each score at least PORTRAIT_CONFIRM_MIN,
# fixed before any refused board was scored: the weakest enemy portrait of
# an accepted opening scores at least
# [metric:scoreboard/portrait-confirm@all-sessions#enemy_min_p5=0.8165] on 95 % of the
# [metric:scoreboard/portrait-confirm@all-sessions#accepted=6018] openings the openings gate accepts on the 19 lineup
# sessions. On the boards 0.8.0 refused at the strip in one decode of
# a06f04a0059f the scores fall in two groups: at least
# [metric:scoreboard/line-confirm@a06f04a0059f#measure_confirmed_enemy_min_score_min=0.8796] where the rows lie on the
# board, at most [metric:scoreboard/line-confirm@a06f04a0059f#refused_enemy_min_score_max=0.4042] where the table's
# left edge is wrong and the portrait boxes miss.
STRIP_RED_OVERLAP = 0.5
PORTRAIT_CONFIRM_MIN = 0.81
# The table's frame (`_frame_edges`). Its left and right edges are vertical
# steps in every row of both blocks: the row plates begin at the portrait
# column and end after the ping plate, over whatever world lies behind. At
# 1920x1080 the table spans frame x 572-1347 (TABLE_W columns), centred on
# the round-history strip; the green test's dense columns reach past it where
# the world beside the board passes the test, and stop short where the
# portrait column fails it over a pale world. The fit searches FRAME_SEARCH
# columns either side of the place the strip's centre predicts, lets the
# width vary by FRAME_W_TOL, and refuses a frame whose two steps sum under
# FRAME_STEP_MIN grey levels: on the fixture's fit sessions, stored opens
# without a board sum at most [metric:scoreboard/table-frame@fixture#fit_frame_score_noboard_max=20] and boards at least [metric:scoreboard/table-frame@fixture#fit_frame_score_board_min=53]; on the
# held-out ones [metric:scoreboard/table-frame@fixture#holdout_frame_score_noboard_max=20] and [metric:scoreboard/table-frame@fixture#holdout_frame_score_board_min=64] (docs/SCOREBOARD_PRESENCE.md,
# "The table's frame").
TABLE_W = 776
FRAME_W_TOL = 2
FRAME_SEARCH = 32
FRAME_STEP_MIN = 36.0

#: The numbers a row reads, and the largest value each may hold.
BOARD_FIELDS = {"kills": 99, "deaths": 99, "assists": 99, "credits": 9000}
#: Where each number's digits stand: pen x in px right of the table's left
#: edge at 1080p, one layout per digit count, per team. The player card's
#: TextBlocks (`scoreboardPlayerCardAllyExtended3` and its enemy twin:
#: killsText, deathsText, assistsText, currentMoneyText) are DIN Next
#: Medium 11 and stand centred, so each digit count has its own places;
#: credits draw a comma before the hundreds. The enemy card stands 0.5-1.5
#: px left of the ally card. Measured on the dev half's rows
#: scoreboard-0.13.0 read (every other row of 120 boards a session): each
#: pen's median, the 5th to 95th percentile within a quarter pixel. No
#: enemy credit of one to three digits was read; those places are the ally's
#: less the 0.75 px the four-digit layouts differ by.
BOARD_PENS = {
    "ally": {
        "kills": ((377.5,), (373.0, 381.25)),
        "deaths": ((417.25,), (413.5, 421.75)),
        "assists": ((457.75,), (453.5, 461.5)),
        "credits": ((678.25,), (674.75, 682.75), (670.0, 678.25, 686.5),
                    (664.0, 676.0, 684.25, 692.5)),
    },
    "enemy": {
        "kills": ((376.75,), (372.5, 380.5)),
        "deaths": ((416.5,), (412.0, 420.25)),
        "assists": ((456.25,), (452.5, 460.75)),
        "credits": ((677.5,), (674.0, 682.0), (669.25, 677.5, 685.75),
                    (663.25, 675.25, 683.5, 691.75)),
    },
}
#: The digits' baseline, px below the row's top at 1080p, on a settled
#: board (19.75-23.75 from the 5th to the 95th percentile). While the board
#: slides in, a row's band can stand 8 px off its digits (b7d24102a6f6
#: 1338.0 s, bfad2778a372 1255.5 s), so each row's baseline is fitted
#: (`_row_baseline`) and this stands only where its K/D/A columns hold no ink.
BOARD_BASELINE = 21.75
#: A second digit-tall window in a row's band holding this share of the
#: best window's ink is another row's numbers (`_row_baseline`).
ROW_RIVAL = 0.5
#: Half the columns, px at 1080p, a number's ink centroid is taken over
#: (`_row_shift`): two digits and a pixel either side; and the most a row's
#: numbers may stand off their pens.
BOARD_SHIFT_SPAN = 10.0
BOARD_SHIFT_MAX = 4.0
#: Whole px at 1080p each cell is searched beyond its pen, across and down
#: from the fitted baseline: the table's edge is fitted per frame to a pixel.
BOARD_REACH = (1, 1)
#: Which digit (`ocr.slot_verdict`, `ocr.Slot.margin` read in the distance
#: between two digits): the board's own cut, a cell at least 0.65 of the way
#: from the nearest other digit to its label. At 11 pt the cells blur
#: towards their neighbours: on the dev half (120 boards a session) no read
#: at any cut from 0 to 0.5 changed from scoreboard-0.13.0's or stood more
#: than 2 off Riot's running count, and ocr.LABEL_SPLIT's 0.5 refused 6 %
#: of kills and 18 % of credits that 0.3 reads.
BOARD_LABEL_SPLIT = 0.3
#: A digit's residual (`ocr.Slot.fit`) cut: on the dev half 99 % of read
#: cells leave at most 0.114 of their energy; a 9 and a 6 placed 3 px off
#: their baseline (587c15b07779 638.5 s, bfad2778a372 1873.5 s, before each
#: row's baseline was fitted) left 0.37 and 0.46.
BOARD_FIT = 0.25
#: Rows of the frame read above and below a row's band.
BOARD_PAD = 4
#: The table's left edge is the board's to the session: once
#: BOARD_EDGE_PRIOR_N open boards have fitted it, their mode is the prior,
#: and a board whose fitted edge stands more than BOARD_EDGE_TOL px (1080p)
#: off it is a surprise whose numbers refuse `edge_surprise`. At 8 px off
#: (a06f04a0059f 1892.0 s, 580 against 572) the centred pens read every
#: two-digit number as its units digit.
BOARD_EDGE_PRIOR_N = 5
BOARD_EDGE_TOL = 2.0
#: The local plate's opening square at 1080p (`ocr.ink_cover`): wider than
#: a stroke, narrower than nothing the board draws behind its digits.
BOARD_PLATE_KERNEL = 7
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

#: Why `read_scoreboard` closed a board, one per refusal branch, in the order
#: it tests them. A slab block is a run of frame rows holding more than
#: MIN_TABLE_W slab pixels in the table's columns (the whole width where the
#: strip's rectangle is unknown): the tallest such run, or where the strip is
#: present the run that meets the strip. `no_rows` means no such row, `short`
#: and `tall` a run outside MIN_BLOCK_H-MAX_BLOCK_H. Enemy rows whose height
#: differs from the ally block's are re-anchored, not refused; the refusal is
#: the overlap that re-anchoring can cause.
CLOSE_REASONS = (
    "green_no_rows", "green_short", "green_tall",   # the ally block
    "red_no_rows", "red_short", "red_tall",         # the enemy block, below it
    "green_not_at_strip",                           # strip present; no green run meets its upper line
    "red_not_at_strip",                             # strip present; no red run meets its lower line
    "red_short_at_strip",                           # the red run from the strip is shorter than MIN_BLOCK_H
    "enemy_overlaps_ally",                          # anchored enemy rows rise into the ally block
    "no_dense_columns",                             # no column of the ally block is half green
    "no_table_frame",                               # strip rectangle known; no frame steps where it predicts
    "table_narrow",                                 # its dense columns span under MIN_TABLE_W
)

#: Which rule placed the blocks: the tallest runs (0.7.0, and wherever the
#: strip is absent, unreadable or not consulted), or the runs that meet the
#: strip's marker lines.
ANCHORS = ("tallest_run", "strip")

#: What confirmed the enemy block on the strip rule: a red run from the lower
#: line (`red_run`), a red run over half the ally height inside the span the
#: line predicts (`red_overlap`), or the five portraits at the line's rows
#: (`portraits`). A board confirmed by its portraits rests on them, so the
#: openings gate's portrait scores are not a second witness of its rows.
#: `red_not_at_strip` and `red_short_at_strip` close a board nothing confirms;
#: the portraits are tested after the table's edges, so those two reasons can
#: follow `no_dense_columns` and `table_narrow` in the order of tests.
CONFIRMS = ("red_run", "red_overlap", "portraits")


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
    # WHY each of K, D and A is None (`read_numbers`), or None when read.
    kills_reason: str | None = None
    deaths_reason: str | None = None
    assists_reason: str | None = None

    @property
    def complete(self) -> bool:
        return None not in (self.kills, self.deaths, self.assists)


@dataclass(frozen=True)
class ScoreboardRead:
    """One frame's scoreboard, or `open_` False when none is on screen.

    A closed read names the test that closed it in `reason`, one per refusal
    branch of `read_scoreboard` (`CLOSE_REASONS`); an open one carries None.
    `anchor` names the rule that placed the blocks (`ANCHORS`), `strip` the
    strip witness's verdict at this frame (None when it was not consulted),
    and `edges`, on the strip rule, which edge placed each block: the ally
    block's own end (`run`) or the upper line (`strip`), and the enemy run's
    bottom (`run`) or the lower line (`strip`). `confirm`, on an open board
    placed by the strip, names what confirmed the enemy block (`CONFIRMS`).
    """

    open_: bool
    rows: tuple[Row, ...] = ()
    x0: int = 0
    x1: int = 0
    reason: str | None = None
    anchor: str | None = None
    strip: str | None = None
    edges: tuple[str, str] | None = None
    confirm: str | None = None

    @property
    def player(self) -> Row | None:
        return next((r for r in self.rows if r.is_player), None)


def table_columns(strip_rect: tuple[int, int, int, int]) -> tuple[int, int]:
    """The frame columns `[x0, x1)` of a table centred on the strip's
    rectangle, TABLE_W wide: frame x 572-1347 at 1920x1080. The frame fit
    (`_frame_edges`) searches FRAME_SEARCH either side of this place."""
    x0 = (strip_rect[0] + strip_rect[2]) // 2 - TABLE_W // 2
    return x0, x0 + TABLE_W


def reader_roi(strip_rect: tuple[int, int, int, int], height: int
               ) -> tuple[int, int, int, int]:
    """Every frame pixel `read_scoreboard` and `portrait_observations` read
    where the strip's rectangle is known, as `(x0, y0, x1, y1)`, x1 and y1
    exclusive: frame x 535-1382 over the whole height at 1920x1080.

    The row test counts the table's columns (`table_columns`). The frame fit
    (`_frame_edges`) reads FRAME_SEARCH either side of them, one column more
    on the left for the step into its first column, and FRAME_W_TOL more on
    the right, where the width may vary. The table's edges fall inside that
    search, and the portrait search reaches AGENT_PAD left of the left edge.
    Every cell, the outline and the strip lie between the edges. Rows are
    wherever the blocks lie, so the region spans the frame's height."""
    x0, x1 = table_columns(strip_rect)
    left = x0 - FRAME_SEARCH - max(1, AGENT_PAD)
    right = x1 + FRAME_SEARCH + FRAME_W_TOL + 1
    return left, 0, right, height


def _slabs(frame: np.ndarray, cols: tuple[int, int] | None = None):
    """The green and red slab masks, frame-shaped. With `cols`, only those
    columns `[x0, x1)` are tested and every other column is False."""
    if cols is None:
        part = frame
    else:
        a, z = max(0, cols[0]), min(frame.shape[1], cols[1])
        part = frame[:, a:z]
    hsv = cv2.cvtColor(part, cv2.COLOR_BGR2HSV)
    h = hsv[:, :, 0].astype(np.int16)
    s = hsv[:, :, 1].astype(np.int16)
    v = hsv[:, :, 2].astype(np.int16)
    green = (h > GREEN_H[0]) & (h < GREEN_H[1]) & (s > SLAB_S_MIN) & (v > SLAB_V_MIN)
    red = ((h < RED_H_LO) | (h > RED_H_HI)) & (s > SLAB_S_MIN) & (v > SLAB_V_MIN)
    if cols is None:
        return green, red
    full_g = np.zeros(frame.shape[:2], bool)
    full_r = np.zeros(frame.shape[:2], bool)
    full_g[:, a:z], full_r[:, a:z] = green, red
    return full_g, full_r


def _block(mask: np.ndarray, merge_gap: int = BLOCK_GAP) -> tuple[int, int] | None:
    """The tallest run of frame rows that are slab across a table's width."""
    return _block_why(mask, merge_gap)[0]


def _runs(mask: np.ndarray, merge_gap: int) -> list[list[int]]:
    """Runs `[start, end)` of frame rows holding more than MIN_TABLE_W slab
    pixels, joining runs `merge_gap` rows apart or closer. The caller decides
    which columns count: `read_scoreboard` passes masks that are slab only
    in the table's columns where the strip's rectangle is known."""
    on = (mask.sum(axis=1) > MIN_TABLE_W).astype(np.int8)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], on, [0]))))
    merged: list[list[int]] = []
    for a, z in zip(edges[::2].tolist(), edges[1::2].tolist()):
        if merged and a - merged[-1][1] <= merge_gap:
            merged[-1][1] = z
        else:
            merged.append([a, z])
    return merged


def _block_why(mask: np.ndarray, merge_gap: int = BLOCK_GAP
               ) -> tuple[tuple[int, int] | None, str | None]:
    """`_block`, and why it found none: `no_rows` when no frame row holds more
    than MIN_TABLE_W slab pixels, `short` or `tall` when the tallest run falls
    outside MIN_BLOCK_H-MAX_BLOCK_H."""
    # Join runs the player's tinted row split apart. Only the ally block can
    # contain that row. On the enemy colour, merging nearby runs can swallow
    # the red round-history marks between the teams and shift all five rows.
    merged = _runs(mask, merge_gap)
    best = None
    for a, z in merged:
        if best is None or (z - a) > (best[1] - best[0]):
            best = (a, z)
    if best is None:
        return None, "no_rows"
    if best[1] - best[0] < MIN_BLOCK_H:
        return None, "short"
    if best[1] - best[0] > MAX_BLOCK_H:
        return None, "tall"
    return best, None


def strip_rect(profile_name: str, width: int, height: int) -> tuple[int, int, int, int] | None:
    """The frame rectangle the strip witness reads for this profile, or None
    where the profile has no such ROI or the frame is not the size the strip
    was measured at: its marker lines are frame rows at that size, and this
    reader does not scale its own pixel constants either."""
    from . import scoreboard_strip as strip
    from .profiles import PROFILES

    profile = PROFILES.get(profile_name)
    if profile is None or (width, height) != strip.MEASURED_WH:
        return None
    roi = next((r for r in profile.rois if r.name == strip.ROI), None)
    return None if roi is None else roi.pixels(width, height)


def _strip_blocks(green: np.ndarray, red: np.ndarray, rows: tuple[int, int]):
    """The ally and enemy blocks bounded by the strip's marker lines `rows`,
    as `(ally, enemy, edges, confirm, reason)`; `reason` names the refusal.

    The ally block is the merged green run that reaches within STRIP_TOL of
    its measured end above the upper line. Where the run goes on into the
    band, the world there passed the green test and the line ends the block.
    The enemy block is the red run that reaches the rows just below the lower
    line, at least MIN_BLOCK_H tall from the block's top, with the ally
    block's height. Its rows sit on the run's bottom where that bottom lies
    where the ally height puts it, as the tallest-run rule placed them;
    elsewhere the world below passed the red test, or the slab failed it,
    and the line places them.

    Where no red run of block height begins at the line, the line places the
    rows anyway. A red run over STRIP_RED_OVERLAP of the ally height inside
    that span confirms them (`red_overlap`); otherwise they come back
    unconfirmed (`confirm` None) with the refusal as `reason`, for the
    portraits to confirm."""
    ally_end = rows[0] - STRIP_ALLY_GAP
    near = [r for r in _runs(green, BLOCK_GAP)
            if r[0] < ally_end + STRIP_TOL and r[1] > ally_end - STRIP_TOL]
    if not near:
        return None, None, None, None, "green_not_at_strip"
    a, z = min(near, key=lambda r: abs(r[1] - ally_end))
    ally_edge = "run" if z <= ally_end + STRIP_TOL else "strip"
    ally = (a, z if ally_edge == "run" else ally_end)
    if ally[1] - ally[0] < MIN_BLOCK_H:
        return None, None, None, None, "green_short"
    if ally[1] - ally[0] > MAX_BLOCK_H:
        return None, None, None, None, "green_tall"
    team_h = ally[1] - ally[0]
    top = rows[1] + STRIP_ENEMY_GAP
    below = red.copy()
    below[:ally[1]] = False
    runs = _runs(below, 0)
    near = [r for r in runs if r[0] <= top + STRIP_TOL and r[1] > top + STRIP_TOL]
    why = "red_not_at_strip"
    if near:
        a, z = near[0]
        if a >= top - STRIP_TOL:
            top = a
        why = "red_short_at_strip"
        if z - top >= MIN_BLOCK_H:
            if abs(z - (top + team_h)) <= STRIP_TOL:
                return ally, (z - team_h, z), (ally_edge, "run"), "red_run", None
            return ally, (top, top + team_h), (ally_edge, "strip"), "red_run", None
    top = rows[1] + STRIP_ENEMY_GAP
    enemy = (top, top + team_h)
    span_end = enemy[1] + STRIP_TOL
    overlap = max((min(z, span_end) - max(a, top) for a, z in runs), default=0)
    if overlap >= STRIP_RED_OVERLAP * team_h:
        return ally, enemy, (ally_edge, "strip"), "red_overlap", None
    return ally, enemy, (ally_edge, "strip"), None, why


def _table_edges(green: np.ndarray, red: np.ndarray, ally: tuple[int, int],
                 enemy: tuple[int, int]) -> tuple[int, int] | None:
    """The table's left and right edge columns, or None where nothing marks them.

    From the ally block's own dense columns, which are cleaner than a
    whole-frame profile that also catches the team bars up top."""
    dense = np.where(green[ally[0]:ally[1]].mean(axis=0) > 0.5)[0]
    if dense.size == 0:
        return None
    return int(dense.min()), int(dense.max())


def _frame_edges(frame: np.ndarray, ally: tuple[int, int], enemy: tuple[int, int],
                 centre: int) -> tuple[int, int] | None:
    """The table's left and right edge columns from its frame, or None where no
    frame steps near the place `centre` (the strip's centre column) predicts.

    A column's step is the median, over the rows of both blocks, of the
    colour change from its left neighbour. The frame is the pair of steps
    TABLE_W apart (within FRAME_W_TOL) with the largest sum, its left edge
    within FRAME_SEARCH of `centre - TABLE_W // 2`."""
    lo = centre - TABLE_W // 2 - FRAME_SEARCH
    hi = centre - TABLE_W // 2 + FRAME_SEARCH
    rows = np.r_[ally[0]:ally[1], enemy[0]:enemy[1]]
    W = frame.shape[1]
    if lo < 1 or hi + TABLE_W + FRAME_W_TOL >= W or rows.size == 0:
        return None

    def steps(a: int, b: int) -> np.ndarray:
        # step[i] is the change from column a + i - 1 to column a + i
        px = frame[rows, a - 1:b + 1].astype(np.int16)
        return np.median(np.abs(np.diff(px, axis=1)).sum(axis=2), axis=0)

    left = steps(lo, hi)
    right = steps(lo + TABLE_W - FRAME_W_TOL, hi + TABLE_W + FRAME_W_TOL)
    best = None
    for i in range(hi - lo + 1):
        win = right[i:i + 2 * FRAME_W_TOL + 1]
        j = int(np.argmax(win))
        score = float(left[i] + win[j])
        if best is None or score > best[0]:
            best = (score, lo + i, lo + i + TABLE_W - FRAME_W_TOL + j - 1)
    if best[0] < FRAME_STEP_MIN:
        return None
    return best[1], best[2]


def _split(block: tuple[int, int]) -> list[tuple[int, int]]:
    a, z = block
    step = (z - a) / TEAM_ROWS
    return [(int(round(a + step * k)), int(round(a + step * (k + 1))))
            for k in range(TEAM_ROWS)]


@dataclass(frozen=True)
class Number:
    """One number of one row: its value, or None and the reason
    (`ocr.read_layouts`' refusals, `low_contrast`, `leading_zero`,
    `out_of_range`, `not_credit_increment`, `empty_cell`). `candidate` is
    the text the cells read where a rule after them refused it;
    `confidence` the worst cell's 1 - fit, `margin` its worst label margin."""

    value: int | None
    reason: str | None
    candidate: int | None = None
    confidence: float | None = None
    margin: float | None = None


def _row_baseline(cover: np.ndarray, cells: "ocr.GlyphCells", a: int, z: int,
                  shift: float, scale: float, pens: dict) -> tuple[float, str | None]:
    """The row's digit baseline in `cover` rows: the bottom of the digit-tall
    window of rows holding the most ink across the K/D/A columns, net of
    each row's median (the row hairlines), the window inside the band a..z;
    BOARD_BASELINE below `a` where they hold none. The reason is
    `two_rows` where a second window clear of the first holds at least
    ROW_RIVAL of its ink: the band spans two rows' numbers (a board still
    sliding in), and nothing says which is this row's."""
    tall = cells.base - ocr.CELL_MARGIN
    pens = [p + shift for f in ("kills", "deaths", "assists") for lay in pens[f] for p in lay]
    c0, c1 = max(0, int(min(pens) * scale)), int(np.ceil(max(pens) * scale)) + cells.w
    band = cover[:, c0:c1].astype(np.float64)
    # A row hairline crosses every column; the digits leave most columns of
    # the span empty, so each row's median coverage is line, not digit.
    prof = band.sum(axis=1) - band.shape[1] * np.median(band, axis=1)
    if len(prof) < tall:
        return a + BOARD_BASELINE * scale, None
    win = np.convolve(prof, np.ones(tall), "valid")       # rows i .. i+tall-1
    lo, hi = max(0, a - 1), max(0, min(len(win), z + 2 - tall))
    if hi <= lo or win[lo:hi].max() <= ocr.NO_INK * cells.digit_energy.mean():
        return a + BOARD_BASELINE * scale, None
    j = lo + int(np.argmax(win[lo:hi]))
    rest = win[lo:hi].copy()
    rest[max(0, j - lo - tall):j - lo + tall + 1] = -np.inf
    why = "two_rows" if rest.size and rest.max() >= ROW_RIVAL * win[j] else None
    return float(j + tall), why


def _centre(pens: dict, name: str, cells: "ocr.GlyphCells", scale: float) -> float:
    """Where a centred number's ink centres, px right of the table's edge
    at 1080p: its one-digit layout's middle."""
    return pens[name][0][0] + cells.advance["0"] / 2.0 / scale


def _row_shift(cover: np.ndarray, cells: "ocr.GlyphCells", base: float, shift: float,
               scale: float, pens: dict) -> float:
    """How far right of BOARD_PENS this row's numbers stand, px at 1080p:
    each K/D/A number is centred, so its ink's centroid stands at its
    column's centre whatever its digit count; the median over the columns
    holding ink, quarter-pixel, within BOARD_SHIFT_MAX. The table's edge is
    fitted per frame to a few px (4f207c0c4e39 1682.5 s stood 3.5 px off),
    more than a cell's search reaches. This rule and its two constants were
    added after viewing that board, a held one: the held board numbers rest
    on it and are not clean."""
    r1 = int(round(base))
    r0 = max(0, r1 - (cells.base - ocr.CELL_MARGIN))
    got = []
    half = BOARD_SHIFT_SPAN * scale
    for name in ("kills", "deaths", "assists"):
        c = (_centre(pens, name, cells, scale) + shift) * scale
        c0, c1 = max(0, int(np.floor(c - half))), int(np.ceil(c + half))
        win = cover[r0:r1, c0:c1].astype(np.float64)
        col = win.sum(axis=0)
        if col.sum() < ocr.NO_INK * cells.digit_energy.mean():
            continue
        got.append((float((col * np.arange(c0, c0 + len(col))).sum() / col.sum()) + 0.5 - c) / scale)
    if not got:
        return 0.0
    dx = float(np.median(got))
    return float(np.clip(np.round(dx * 4.0) / 4.0, -BOARD_SHIFT_MAX, BOARD_SHIFT_MAX))


def read_numbers(gray: np.ndarray, x0: int, a: int, z: int,
                 cells: "ocr.GlyphCells", scale: float = 1.0,
                 team: str = "ally") -> dict[str, Number]:
    """Every BOARD_FIELDS number of the row whose band is frame rows a..z of
    `gray`, the table's left edge at frame column `x0`, on `team`'s card
    (`BOARD_PENS`): white-ink coverage
    against the row's plate (`ocr.ink_cover`), read at BOARD_PENS by
    `ocr.read_layouts`, tinted (a dead player's grey row) and searched
    BOARD_REACH about each pen and the row's fitted baseline
    (`_row_baseline`). A number whose cells stand over a plate too near
    white refuses `low_contrast`."""
    H, W = gray.shape[:2]
    pad = int(round(BOARD_PAD * scale))
    top, bot = max(0, a - pad), min(H, z + pad)
    left = max(0, x0)
    card = BOARD_PENS[team]
    reach_x = max(p for lays in card.values() for lay in lays for p in lay)
    right = min(W, x0 + int(np.ceil(reach_x * scale)) + 2 * cells.w)
    strip = gray[top:bot, left:right]
    out: dict[str, Number] = {}
    if strip.size == 0 or bot - top < cells.h:
        return {name: Number(None, "empty_cell") for name in BOARD_FIELDS}
    kernel = max(3, int(round(BOARD_PLATE_KERNEL * scale)) | 1)
    cover, room = ocr.ink_cover(strip, kernel)
    pc, _px, _py = ocr.pad_cover(cover.astype(np.float32), cells)
    shift = (x0 - left) / scale
    base, two = _row_baseline(cover, cells, a - top, z - top, shift, scale, card)
    if two is not None:
        return {name: Number(None, two) for name in BOARD_FIELDS}
    shift += _row_shift(cover, cells, base, shift, scale, card)
    base /= scale
    for name, most in BOARD_FIELDS.items():
        layouts = tuple(tuple(p + shift for p in lay) for lay in card[name])
        pens = [p for lay in layouts for p in lay]
        r0 = max(0, int(base * scale) - cells.base)
        c0 = max(0, int(min(pens) * scale))
        band = room[r0:r0 + cells.h, c0:int(np.ceil(max(pens) * scale)) + cells.w]
        if band.size == 0:
            out[name] = Number(None, "empty_cell")
            continue
        if float(band.min()) < ocr.SCORE_CONTRAST_MIN:
            out[name] = Number(None, "low_contrast")
            continue
        text, slots, why = ocr.read_layouts(pc, cells, layouts, base, scale, tinted=True,
                                            reach=BOARD_REACH, label_margin=BOARD_LABEL_SPLIT,
                                            # The credit sign stands left of
                                            # every credit layout.
                                            beside=name != "credits", fit_cut=BOARD_FIT,
                                            ends=True)
        if why is not None:
            out[name] = Number(None, why)
            continue
        conf = min(1.0 - v.fit for v in slots)
        margin = min(v.margin for v in slots)
        if len(text) > 1 and text[0] == "0":
            out[name] = Number(None, "leading_zero", None, conf, margin)
            continue
        value = int(text)
        if value > most:
            out[name] = Number(None, "out_of_range", value, conf, margin)
        elif name == "credits" and value % 50:
            out[name] = Number(None, "not_credit_increment", value, conf, margin)
        else:
            out[name] = Number(value, None, value, conf, margin)
    return out


def read_scoreboard(
    frame: np.ndarray,
    templates: "ocr.FieldTemplates",
    min_confidence: float = 0.80,
    min_margin: float = 0.04,
    strip_rect: tuple[int, int, int, int] | None = None,
    icons: dict | None = None,
    cache: "PortraitCache | None" = None,
    x0_prior: int | None = None,
) -> ScoreboardRead:
    """Read every row's K/D/A, and say which row is the local player's.

    `strip_rect` is the frame rectangle the round-history strip witness reads
    (`strip_rect()`); where it reads the strip present, the blocks are the
    runs that meet the strip's marker lines. Without it, or where the strip
    is absent or unreadable, they are the tallest runs. With it, the runs
    count slab pixels only in the table's columns (`table_columns`), and the
    read depends only on the pixels in `reader_roi`. Enemy rows the line
    places without a red run to confirm them open only when every one of
    their portraits scores at least PORTRAIT_CONFIRM_MIN against `icons`
    (`load_agent_icons`); without `icons` such a board closes. A closed board
    says which test closed it (`ScoreboardRead.reason`). `cache`
    (`PortraitCache`) reuses the scores of a portrait already scored.
    `x0_prior` is the session's table edge (`ScoreboardReader`): a fitted
    edge more than BOARD_EDGE_TOL px off it reads no number, each refusing
    `edge_surprise`.
    `templates` carries the board's font (`ocr.game_font_templates`);
    `min_confidence` and `min_margin` belonged to the mined digit set and
    bind no soft read."""
    H, W = frame.shape[:2]
    # The strip's rectangle places the table's columns, and the row test
    # counts only those: world beside the board is not the board.
    green, red = _slabs(frame, None if strip_rect is None else table_columns(strip_rect))
    seen = None
    if strip_rect is not None:
        from . import scoreboard_strip as strip

        sx0, sy0, sx1, sy1 = strip_rect
        seen = strip.read_strip(frame[sy0:sy1, sx0:sx1], strip_rect)["verdict"]
    closed = {"strip": seen}
    confirm = unconfirmed = None
    if seen == "present":
        closed["anchor"] = "strip"
        ally, enemy, edges, confirm, why = _strip_blocks(green, red, strip.ROW_Y)
        if enemy is None:
            return ScoreboardRead(False, reason=why, **closed)
        unconfirmed = why
    else:
        closed["anchor"], edges = "tallest_run", None
        ally, why = _block_why(green)
        if ally is None:
            return ScoreboardRead(False, reason=f"green_{why}", **closed)
        # The ally block always sits above the enemy one, so the enemy block is
        # searched for BELOW it. The translucent ally slab over a purple backdrop
        # also passes the red test: at 1999000 ms of a06f04a0059f the tallest red
        # run lay inside the ally block, and five enemy rows were read off the
        # ally portraits. A faint real enemy slab now closes the board instead.
        below = red.copy()
        below[:ally[1]] = False
        enemy, why = _block_why(below, merge_gap=0)
        if enemy is None:
            return ScoreboardRead(False, reason=f"red_{why}", **closed)
        # The red match-history strip can be connected to the enemy slab by its
        # own marks, so even an unmerged red run may begin too high. Both teams use
        # the same five-row geometry in one animation state; anchor the enemy rows
        # at the bottom of the red slab and take their height from the ally block.
        team_h = ally[1] - ally[0]
        if enemy[1] - enemy[0] != team_h:
            enemy = (enemy[1] - team_h, enemy[1])
    # Anchoring can lift the enemy rows into the ally block when the two
    # geometries disagree: a short red run at the ally bottom (a06f04a0059f
    # 305500 ms), or an ally block that swallowed the history strip
    # (7010b3d62460 102000 ms). Nothing here knows which block is right, so
    # the board is not read.
    if enemy[0] < ally[1]:
        return ScoreboardRead(False, reason="enemy_overlaps_ally", **closed)

    if strip_rect is not None:
        # The strip's rectangle says where the table lies; fit its frame there.
        got = _frame_edges(frame, ally, enemy, (strip_rect[0] + strip_rect[2]) // 2)
        if got is None:
            return ScoreboardRead(False, reason="no_table_frame", **closed)
    else:
        got = _table_edges(green, red, ally, enemy)
        if got is None:
            return ScoreboardRead(False, reason="no_dense_columns", **closed)
    x0, x1 = got
    tw = x1 - x0
    if tw < MIN_TABLE_W:
        return ScoreboardRead(False, reason="table_narrow", **closed)
    if unconfirmed is not None:
        # The line placed the enemy rows and no red run confirmed them. The
        # portraits sit where `portrait_observations` scores them, and every
        # one must match agent art as accepted openings do.
        if not icons:
            return ScoreboardRead(False, reason=unconfirmed, **closed)
        px = max(0, x0)
        boxes = [(px, a, px + (z - a), z) for a, z in _split(enemy)]
        # With a cache the ally portraits ride in the same batch, and
        # `portrait_observations` finds all ten there: one GPU launch and
        # one copy back a frame. The ally scores decide nothing here.
        ahead = [(px, a, px + (z - a), z) for a, z in _split(ally)] if cache is not None else []
        scores = [got["portrait_agent_score"] for got in
                  portrait_agents(frame, boxes + ahead, icons, cache)[:len(boxes)]]
        if None in scores or min(scores) < PORTRAIT_CONFIRM_MIN:
            return ScoreboardRead(False, reason=unconfirmed, **closed)
        confirm = "portraits"

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
    scale = H / 1080.0
    cells = templates.cells("board", scale)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    surprise = x0_prior is not None and abs(x0 - x0_prior) > BOARD_EDGE_TOL * scale
    for a, z, team in bands:
        n = ({name: Number(None, "edge_surprise") for name in BOARD_FIELDS} if surprise
             else read_numbers(gray, x0, a, z, cells, scale, team))
        cr = n["credits"]
        rows.append(Row(team=team, y0=int(a), y1=int(z),
                        kills=n["kills"].value, deaths=n["deaths"].value,
                        assists=n["assists"].value,
                        is_player=outlined(a) and outlined(z), credits=cr.value,
                        credits_reason=cr.reason,
                        credits_confidence=cr.confidence,
                        credits_margin=cr.margin,
                        credits_candidate=cr.candidate,
                        kills_reason=n["kills"].reason,
                        deaths_reason=n["deaths"].reason,
                        assists_reason=n["assists"].reason))
    return ScoreboardRead(True, tuple(rows), x0, x1, edges=edges, confirm=confirm, **closed)


#: Search around the portrait box for the agent drawing, in pixels and in
#: drawn size. Row height is ~34 px at 1080p and the art fills the row.
AGENT_PAD = 5
AGENT_SCALES = tuple(range(30, 42, 2))


def load_agent_icons(root) -> dict[str, tuple[list, list]]:
    """Every official square `agent_icon`, resized to each search scale.

    The scoreboard portrait IS this drawing at row height, so the comparison is
    pixels on one surface -- not the cross-surface colour histogram the stored
    descriptor was, which ranked an enemy row first for an ally victim.
    """
    import glob
    import os
    out = {}
    pattern = os.path.join(str(root), "reference", "assets", "agents", "*_agent_icon.png")
    for f in sorted(glob.glob(pattern)):
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        if im is None or im.ndim != 3 or im.shape[2] != 4:
            continue
        ims, masks = [], []
        for s in AGENT_SCALES:
            r = cv2.resize(im, (s, s), interpolation=cv2.INTER_AREA)
            ims.append(np.ascontiguousarray(r[:, :, :3]))
            masks.append(np.repeat((r[:, :, 3:4] > 200).astype(np.uint8), 3, 2))
        # `KAY_O_agent_icon.png` -- strip the SUFFIX, never split on "_".
        out[os.path.basename(f)[: -len("_agent_icon.png")]] = (ims, masks)
    return out


class PortraitCache:
    """Portrait scores already computed, keyed on the exact pixels scored.

    While a board stays open its portraits rarely change, and the enemy rows
    a line-placed board confirms are scored again as observations. The key
    is the scored window's shape and bytes, which scorer ran, and the agent
    art: an exact match returns the same result, so a hit is
    indistinguishable from a rescore. A cache belongs to one reader, and so
    to one session, and holds at most `size` windows, least recently used
    first out.
    """

    def __init__(self, size: int = 64):
        self.size, self.hits, self.misses = size, 0, 0
        self._icons = None
        self._held: OrderedDict = OrderedDict()

    def get(self, key, icons: dict):
        if icons is not self._icons:
            # Other agent art scores differently: nothing held applies.
            self._icons = icons
            self._held.clear()
        got = self._held.get(key)
        if got is None:
            self.misses += 1
            return None
        self.hits += 1
        self._held.move_to_end(key)
        return _copied(got)

    def put(self, key, result: dict) -> None:
        self._held[key] = _copied(result)
        while len(self._held) > self.size:
            self._held.popitem(last=False)


def _copied(result: dict) -> dict:
    """A result whose nested scores a caller may change without reaching the cache."""
    scores = result.get("portrait_agent_scores")
    return result if scores is None else {**result, "portrait_agent_scores": dict(scores)}


_EMPTY = {"portrait_agent_best": None, "portrait_agent_score": None,
          "portrait_agent_second": None, "portrait_agent_margin": None,
          "portrait_gain": None, "portrait_agent_scores": None}


def portrait_agent(frame: np.ndarray, box: tuple[int, int, int, int],
                   icons: dict, cache: PortraitCache | None = None) -> dict:
    """Raw agent-art scores for one portrait box, and its brightness gain.

    Context-free: every agent in the gallery is scored and nothing is named.
    `portrait_gain` is the least-squares slope of the row's pixels on the
    matched art's pixels. The game dims a dead player's portrait, which lowers
    that slope while the normalised correlation holds; a naturally dark agent
    keeps a slope near one. Adjudication decides whether a board is expanded
    enough to trust either number. `cache` returns the result for a window
    scored before, pixel for pixel, with the same scorer and art.
    """
    return portrait_agents(frame, [box], icons, cache)[0]


def portrait_agents(frame: np.ndarray, boxes, icons: dict,
                    cache: PortraitCache | None = None) -> list[dict]:
    """`portrait_agent` for each box of one frame, scored together.

    On the GPU every window the cache does not hold goes to one kernel
    launch with one copy back (`_art_scores_gpu_batch`). A window's result
    depends only on its own pixels, so each equals `portrait_agent` on its
    box alone, whatever else shares the batch. Identical windows are scored
    once.
    """
    if not icons:
        return [{**_EMPTY, "portrait_agent_reason": "no_agent_icons"} for _ in boxes]
    gallery = _gpu_gallery(icons)
    wins = [_portrait_window(frame, box) for box in boxes]
    out: list = [None] * len(wins)
    todo: dict = {}                     # key -> the indices of the windows it scores
    for k, win in enumerate(wins):
        key = k
        if cache is not None:
            key = (gallery is not None, win.shape, win.dtype.str, win.tobytes())
            got = cache.get(key, icons)
            if got is not None:
                out[k] = got
                continue
        todo.setdefault(key, []).append(k)
    first = [ks[0] for ks in todo.values()]
    scored = (_art_scores_gpu_batch([wins[k] for k in first], gallery) if gallery is not None
              else [_art_scores_cpu(wins[k], icons) for k in first])
    for (key, ks), (scores, where) in zip(todo.items(), scored):
        got = _portrait_result(wins[ks[0]], icons, scores, where)
        for j in ks:
            out[j] = _copied(got)
        if cache is not None:
            cache.put(key, got)
    return out


def _portrait_window(frame: np.ndarray, box: tuple[int, int, int, int]) -> np.ndarray:
    """The pixels searched for the agent art: the box grown by AGENT_PAD."""
    x0, y0, x1, y1 = box
    return frame[max(0, y0 - AGENT_PAD):max(0, y1 + AGENT_PAD),
                 max(0, x0 - AGENT_PAD):max(0, x1 + AGENT_PAD)]


def _portrait_result(win: np.ndarray, icons: dict, scores: dict, where: dict) -> dict:
    """`portrait_agent`'s result from every agent's best score and place."""
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if len(ranked) < 2 or where[ranked[0][0]] is None:
        return {**_EMPTY, "portrait_agent_reason": "portrait_box_smaller_than_art"}
    name = ranked[0][0]
    i, (x, y) = where[name]
    t, m = icons[name][0][i], icons[name][1][i][:, :, 0] > 0
    art = t[m].astype(np.float64).ravel()
    seen = win[y:y + t.shape[0], x:x + t.shape[1]][m].astype(np.float64).ravel()
    return {"portrait_agent_best": name,
            "portrait_agent_score": round(ranked[0][1], 4),
            "portrait_agent_second": ranked[1][0],
            "portrait_agent_margin": round(ranked[0][1] - ranked[1][1], 4),
            "portrait_gain": round(float(np.polyfit(art, seen, 1)[0]), 4),
            # Every agent's score, so a whole side can be ASSIGNED downstream
            # (`identity.assign_side`) instead of read as five argmaxes.
            "portrait_agent_scores": {k: round(v, 4) for k, v in sorted(scores.items())},
            "portrait_agent_reason": None}


def _art_scores_cpu(win: np.ndarray, icons: dict) -> tuple[dict, dict]:
    """Each agent's best masked TM_CCOEFF_NORMED over its scales, by OpenCV."""
    scores, where = {}, {}
    for name, (ims, masks) in icons.items():
        best = (-1.0, None)
        for i, (t, m) in enumerate(zip(ims, masks)):
            if t.shape[0] > win.shape[0] or t.shape[1] > win.shape[1]:
                continue
            r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED, mask=m)
            r = np.nan_to_num(r, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, v, _, loc = cv2.minMaxLoc(r)
            if v > best[0]:
                best = (float(v), (i, loc))
        scores[name], where[name] = best
    return scores, where


# `RETICLE_SCOREBOARD=cpu` forces OpenCV; `=gpu` refuses to fall back; `auto`
# (the default) scores on the GPU when cupy and a CUDA device are present.
# The galleries of the last few agent-art dicts stay on the GPU, each kept
# with its dict so a reused id() never returns another dict's art.
_GPU_GALLERIES: OrderedDict = OrderedDict()
_GPU_GALLERIES_HELD = 4
_GPU_KERNEL = None
_GPU_THREADS = 128

# One block per (window, scale, agent); its threads walk the window's
# placements. Every masked sum is over integers (pixels and art are 0-255),
# held exactly in int32; only the per-placement finish is in float64. The
# block keeps the largest score and, among equal scores, the first
# placement in row-major order, as `cv2.minMaxLoc` does.
_GPU_SOURCE = r"""
#define THREADS %d
extern "C" __global__
void portrait_scores(const unsigned char* img, const int* hw, const unsigned char* art,
                     const unsigned char* mask, const int* scale, const double* mean,
                     const double* area, const double* tnorm, int S, int A, int Hm, int Wm,
                     double* out)
{
    int a = blockIdx.x %% A, s = (blockIdx.x / A) %% S, k = blockIdx.x / (A * S);
    int th = scale[4 * s], tw = scale[4 * s + 1];
    const unsigned char* t = art + scale[4 * s + 2] + (size_t)a * th * tw * 3;
    const unsigned char* m = mask + scale[4 * s + 3] + (size_t)a * th * tw;
    const unsigned char* im = img + (size_t)k * Hm * Wm * 3;
    int ny = hw[2 * k] - th + 1, nx = hw[2 * k + 1] - tw + 1;
    int npos = (ny > 0 && nx > 0) ? ny * nx : 0;
    int sa = s * A + a;
    double ar = area[sa], tn = tnorm[sa];
    double mu0 = mean[3 * sa], mu1 = mean[3 * sa + 1], mu2 = mean[3 * sa + 2];
    double best = -2.0;
    int where = 0x7fffffff;
    for (int p = threadIdx.x; p < npos; p += THREADS) {
        int y = p / nx, x = p %% nx;
        int s10 = 0, s11 = 0, s12 = 0, s20 = 0, s21 = 0, s22 = 0, v0 = 0, v1 = 0, v2 = 0;
        for (int i = 0; i < th; ++i) {
            const unsigned char* row = im + ((size_t)(y + i) * Wm + x) * 3;
            for (int j = 0; j < tw; ++j) {
                if (!m[i * tw + j]) continue;
                const unsigned char* q = row + 3 * j;
                const unsigned char* u = t + 3 * (i * tw + j);
                int c0 = q[0], c1 = q[1], c2 = q[2];
                s10 += c0; s11 += c1; s12 += c2;
                s20 += c0 * c0; s21 += c1 * c1; s22 += c2 * c2;
                v0 += c0 * u[0]; v1 += c1 * u[1]; v2 += c2 * u[2];
            }
        }
        double num = ((double)v0 - mu0 * s10) + ((double)v1 - mu1 * s11)
                   + ((double)v2 - mu2 * s12);
        double var = ((double)s20 - (double)s10 * s10 / ar)
                   + ((double)s21 - (double)s11 * s11 / ar)
                   + ((double)s22 - (double)s12 * s12 / ar);
        double den = sqrt(fmax(var, 0.0) * tn);
        double r = den > 0 ? num / den : -1.0;
        if (r > best) { best = r; where = p; }
    }
    __shared__ double vb[THREADS];
    __shared__ int wb[THREADS];
    vb[threadIdx.x] = best;
    wb[threadIdx.x] = where;
    __syncthreads();
    for (int h = THREADS / 2; h > 0; h >>= 1) {
        if (threadIdx.x < h) {
            double ov = vb[threadIdx.x + h];
            int ow = wb[threadIdx.x + h];
            if (ov > vb[threadIdx.x] || (ov == vb[threadIdx.x] && ow < wb[threadIdx.x])) {
                vb[threadIdx.x] = ov;
                wb[threadIdx.x] = ow;
            }
        }
        __syncthreads();
    }
    if (threadIdx.x == 0) {
        out[2 * blockIdx.x] = vb[0];
        out[2 * blockIdx.x + 1] = npos ? (double)wb[0] : -1.0;
    }
}
""" % _GPU_THREADS


def portrait_scorer() -> str:
    """Which scorer `portrait_agent` uses in this process, for provenance."""
    return "cupy-exact" if _gpu_gallery(None) is not None else "opencv-float32"


def _gpu_gallery(icons: dict | None):
    """The agent art on the GPU, or None to score on the CPU.

    `icons=None` asks only whether the GPU path is available. The gallery
    holds every scale's art and mask as bytes, and each agent's masked mean,
    masked area and zero-mean art norm per scale, computed in float64. It is
    built once per icons dict; the last `_GPU_GALLERIES_HELD` stay.
    """
    mode = os.environ.get("RETICLE_SCOREBOARD", "auto").lower()
    if mode not in ("auto", "cpu", "gpu"):
        raise ValueError(f"RETICLE_SCOREBOARD must be auto, cpu or gpu, not {mode!r}")
    if mode == "cpu":
        return None
    try:
        import cupy as cp
        if cp.cuda.runtime.getDeviceCount() < 1:
            raise RuntimeError("no CUDA device")
    except Exception:
        if mode == "gpu":
            raise
        return None
    if icons is None:
        return True
    held = _GPU_GALLERIES.get(id(icons))
    if held is not None and held[0] is icons:
        _GPU_GALLERIES.move_to_end(id(icons))
        return held[1]
    names = list(icons)
    arts, masks, scales, means, areas, norms = [], [], [], [], [], []
    art_at = mask_at = 0
    for i in range(min(len(ims) for ims, _ in icons.values())):
        t = np.ascontiguousarray(np.stack([icons[n][0][i] for n in names]), dtype=np.uint8)
        m = np.stack([icons[n][1][i][:, :, 0] for n in names]) > 0    # (agents, th, tw)
        th, tw = t.shape[1:3]
        # A masked sum of pixel products must fit the kernel's int32.
        if 255 * 255 * th * tw >= 2 ** 31:
            raise ValueError(f"agent art {th}x{tw} is too large for the GPU scorer")
        scales.append((th, tw, art_at, mask_at))
        arts.append(t.ravel())
        masks.append(m.astype(np.uint8).ravel())
        art_at, mask_at = art_at + t.size, mask_at + m.size
        tf, mf = t.astype(np.float64), m[..., None].astype(np.float64)
        area = np.maximum(m.sum(axis=(1, 2)), 1).astype(np.float64)   # (agents,)
        mean = (tf * mf).sum(axis=(1, 2)) / area[:, None]             # (agents, 3)
        means.append(mean)
        areas.append(area)
        norms.append((((tf - mean[:, None, None, :]) * mf) ** 2).sum(axis=(1, 2, 3)))
    arrays = {"art": cp.asarray(np.concatenate(arts)),
              "mask": cp.asarray(np.concatenate(masks)),
              "scale": cp.asarray(np.array(scales, dtype=np.int32).ravel()),
              "mean": cp.asarray(np.array(means)), "area": cp.asarray(np.array(areas)),
              "tnorm": cp.asarray(np.array(norms))}
    gallery = (names, [(th, tw) for th, tw, _, _ in scales], arrays)
    _GPU_GALLERIES[id(icons)] = (icons, gallery)
    while len(_GPU_GALLERIES) > _GPU_GALLERIES_HELD:
        _GPU_GALLERIES.popitem(last=False)
    return gallery


def _art_scores_gpu(win: np.ndarray, gallery) -> tuple[dict, dict]:
    """`_art_scores_cpu` on the GPU for one window (`_art_scores_gpu_batch`)."""
    return _art_scores_gpu_batch([win], gallery)[0]


def _art_scores_gpu_batch(wins: list, gallery) -> list[tuple[dict, dict]]:
    """`_art_scores_cpu` for every window at once: one kernel, one copy back.

    The same masked normalised correlation, summed over the three channels
    as OpenCV sums them: sum((I - mean_I) * (T - mean_T)) over the mask,
    over the root of both masked variances. Written as sum(I*T) - mean_T *
    sum(I) and sum(I*I) - sum(I)^2 / area, every masked sum is a sum of
    integers and exact, so no summation order can move it; the finish is in
    float64. A window's scores therefore depend only on its own pixels, not
    on the batch, and equal the float64 scorer of 0.6.0-0.11.0 to about
    1e-14 (docs/SCOREBOARD_PRESENCE.md, "Portrait scoring time"). A zero
    variance scores -1, as OpenCV's NaN does after `nan_to_num`. The first
    maximum in row-major order wins, as in `cv2.minMaxLoc`, and a later
    scale must beat an earlier one strictly.
    """
    import cupy as cp
    global _GPU_KERNEL
    names, sizes, arrays = gallery
    empty = ({n: -1.0 for n in names}, {n: None for n in names})
    fit = [k for k, w in enumerate(wins)
           if any(th <= w.shape[0] and tw <= w.shape[1] for th, tw in sizes)]
    out = [empty] * len(wins)
    if not fit:
        return out
    for k in fit:
        if wins[k].dtype != np.uint8 or wins[k].ndim != 3 or wins[k].shape[2] != 3:
            raise ValueError("the GPU scorer reads 8-bit three-channel windows")
    if _GPU_KERNEL is None:
        _GPU_KERNEL = cp.RawKernel(_GPU_SOURCE, "portrait_scores")
    n, S, A = len(fit), len(sizes), len(names)
    Hm = max(wins[k].shape[0] for k in fit)
    Wm = max(wins[k].shape[1] for k in fit)
    host = np.zeros((n, Hm, Wm, 3), np.uint8)
    for j, k in enumerate(fit):
        host[j, :wins[k].shape[0], :wins[k].shape[1]] = wins[k]
    hw = np.array([wins[k].shape[:2] for k in fit], dtype=np.int32)
    got = cp.empty(n * S * A * 2, dtype=cp.float64)
    _GPU_KERNEL((n * S * A,), (_GPU_THREADS,),
                (cp.asarray(host), cp.asarray(hw), arrays["art"], arrays["mask"],
                 arrays["scale"], arrays["mean"], arrays["area"], arrays["tnorm"],
                 np.int32(S), np.int32(A), np.int32(Hm), np.int32(Wm), got))
    got = cp.asnumpy(got).reshape(n, S, A, 2)
    for j, k in enumerate(fit):
        h, w = wins[k].shape[:2]
        scores, where = {}, {}
        for a, name in enumerate(names):
            best = (-1.0, None)
            for i, (th, tw) in enumerate(sizes):
                if th > h or tw > w:
                    continue
                if float(got[j, i, a, 0]) > best[0]:
                    y, x = divmod(int(got[j, i, a, 1]), w - tw + 1)
                    best = (float(got[j, i, a, 0]), (i, (x, y)))
            scores[name], where[name] = best
        out[k] = (scores, where)
    return out


def portrait_observations(frame: np.ndarray, board: ScoreboardRead,
                          icons: dict | None = None,
                          cache: PortraitCache | None = None) -> list[dict]:
    """Context-free evidence for each scoreboard portrait.

    The portrait is the square cell at the table's left edge, one row high.
    Source review of `a06f04a0059f` showed that the earlier locator, a
    structural trough searched right of `x0`, landed 9-41 px inside the slab
    and moved between openings on one table, so the descriptor mostly measured
    the row colour. The detector emits descriptors, raw agent-art scores and
    the source box, never an agent identity. Cross-channel identity belongs to
    reconciliation.
    """
    if not board.open_ or not board.rows:
        return []
    result, boxes = [], []
    for index, row in enumerate(board.rows):
        height = row.y1 - row.y0
        x0 = max(0, board.x0)
        art = frame[max(0, row.y0):max(0, row.y1), x0:x0 + max(0, height)]
        # A row whose band has no pixels is not evidence, and it used to be a
        # CRASH: `cvtColor` asserts on an empty Mat, so one degenerate row
        # killed the whole scan mid-corpus (c62c2b06bcfb, 2026-09-09).
        if art.shape[0] <= 4 or art.shape[1] <= 4:
            continue
        # The histogram lives in `appearance` so the killfeed can describe its
        # own portraits with the SAME function. Two copies of it was the fork
        # this repo has a checker for.
        result.append({"display_row": index, "portrait_x0": x0,
                       "portrait_y0": row.y0, "portrait_x1": x0 + art.shape[1],
                       "portrait_y1": row.y1,
                       "portrait_detail": appearance.detail(art),
                       "portrait_composition": appearance.hsv_composition(art).tolist()})
        boxes.append((x0, row.y0, x0 + height, row.y1))
    if icons is not None:
        # Every portrait of the board in one batch (`portrait_agents`).
        for got, scored in zip(result, portrait_agents(frame, boxes, icons, cache)):
            got.update(scored)
    return result


class ScoreboardReader:
    """Sparse context-free scoreboard observations for a shared decode pass."""

    #: The frame region every read depends on (`reader_roi`), set at the
    #: first frame, or None where no strip rectangle places the table and the
    #: whole frame counts. The coverage row carries it.
    roi: list[int] | None = None

    def __init__(self, profile_name: str, hz: float = 2.0, spans=None,
                 min_confidence: float = 0.80, min_margin: float = 0.04,
                 icons_root=None, fonts_root=None):
        self.name, self.hz, self.spans = "scoreboard", hz, spans
        self.profile_name = profile_name
        # The board's font from the game files in `fonts_root`, the default
        # store where None, as the mined set before it was.
        self.templates = ocr.game_font_templates(fonts_root)
        self.icons = load_agent_icons(icons_root) if icons_root is not None else {}
        # Scores of portraits already seen this session, reused on an exact
        # pixel match; `hits` and `misses` count them.
        self.portrait_cache = PortraitCache()
        self.min_confidence, self.min_margin = min_confidence, min_margin
        self.frames_offered = 0
        self.frames_open = 0
        self.rows: list[dict] = []
        # One per frame offered, open or closed, with the test that closed it:
        # a closed board is an observation too, and a second presence witness
        # (`scoreboard_strip`) is reconciled with it sample by sample.
        self.samples: list[dict] = []
        # The table edges open boards fitted, for the edge prior.
        self.edges_seen: Counter = Counter()

    def feed(self, sample) -> None:
        self.frames_offered += 1
        h, w = sample.frame.shape[:2]
        rect = strip_rect(self.profile_name, w, h)
        if rect is not None and self.roi is None:
            self.roi = [int(v) for v in reader_roi(rect, h)]
        prior = (self.edges_seen.most_common(1)[0][0]
                 if sum(self.edges_seen.values()) >= BOARD_EDGE_PRIOR_N else None)
        board = read_scoreboard(sample.frame, self.templates,
                                self.min_confidence, self.min_margin, rect, self.icons,
                                self.portrait_cache, x0_prior=prior)
        if board.open_:
            self.edges_seen[board.x0] += 1
        self.samples.append({"frame_idx": int(sample.frame_idx), "t_ms": float(sample.t_ms),
                             "open": board.open_, "reason": board.reason,
                             "anchor": board.anchor, "strip": board.strip,
                             "edges": None if board.edges is None else list(board.edges),
                             "confirm": board.confirm})
        if not board.open_:
            return
        self.frames_open += 1
        portraits = {r["display_row"]: r for r in
                     portrait_observations(sample.frame, board, self.icons,
                                           self.portrait_cache)}
        for index, row in enumerate(board.rows):
            self.rows.append({
                "frame_idx": int(sample.frame_idx), "t_ms": float(sample.t_ms),
                "display_row": index, "team": row.team, "anchor": board.anchor,
                "confirm": board.confirm,
                "row_y0": row.y0, "row_y1": row.y1,
                "table_x0": board.x0, "table_x1": board.x1,
                "kills": row.kills, "deaths": row.deaths, "assists": row.assists,
                "kills_reason": row.kills_reason, "deaths_reason": row.deaths_reason,
                "assists_reason": row.assists_reason,
                "is_player": row.is_player, "credits": row.credits,
                "credits_candidate": row.credits_candidate,
                "credits_reason": row.credits_reason,
                "credits_confidence": row.credits_confidence,
                "credits_margin": row.credits_margin,
                **portraits.get(index, {
                    "portrait_x0": None, "portrait_y0": None,
                    "portrait_x1": None, "portrait_y1": None,
                    "portrait_detail": None, "portrait_composition": None,
                    "portrait_agent_best": None, "portrait_agent_score": None,
                    "portrait_agent_second": None, "portrait_agent_margin": None,
                    "portrait_gain": None, "portrait_agent_scores": None,
                    "portrait_agent_reason": "no_portrait_box",
                }),
            })

    def events(self, session_id: str) -> list[dict]:
        common = {"session_id": session_id, "scoreboard_version": SCOREBOARD_VERSION,
                  "source": "scoreboard"}
        # The two scorers agree to the third decimal, not the fourth: which
        # one wrote these scores is provenance.
        closed = Counter(s["reason"] for s in self.samples if not s["open"])
        anchors = Counter(s["anchor"] for s in self.samples if s["open"])
        confirms = Counter(str(s["confirm"]) for s in self.samples if s["open"])
        coverage = {**common, "kind": "coverage", "frames_offered": self.frames_offered,
                    "frames_open": self.frames_open, "portrait_scorer": portrait_scorer(),
                    "closed_reasons": dict(sorted(closed.items())),
                    "open_anchors": dict(sorted(anchors.items())),
                    "open_confirms": dict(sorted(confirms.items())),
                    "roi": self.roi}
        return ([coverage]
                + [{**common, "kind": "row_observation",
                    "observation_key": f"{session_id}:{r['frame_idx']}:{r['display_row']}",
                    **r} for r in self.rows]
                + [{**common, "kind": "sample", **s} for s in self.samples])
