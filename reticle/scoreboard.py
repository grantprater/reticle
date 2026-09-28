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

The local player's row is the one the game outlines in yellow, and its name
renders as the literal string "Me" -- the same convention the killfeed uses.
The outline is what this keys on: it needs no template and no name reading.

Digit size
----------
These digits are h~11 at 1080p, *smaller* than either the scoreline (h~20-26)
or the bottom HUD (h~33), so they fall outside the geometry band in `ocr.py`
and are read against a band of their own. That is what `_raw_components` is for.
Nothing here reads names: a name would need an alphabet this project has no
templates for. Each portrait is scored against the official agent art, raw and
unnamed; `adjudication.scoreboard` decides which agent a row holds and whether
the game has dimmed it as dead. The scoring is promoted from the measured
prototype `scoreboard_agent`.

Owns [owns:scoreboard-row].
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import os

import numpy as np

import cv2

from . import appearance
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

#: Why `read_scoreboard` closed a board, one per refusal branch, in the order
#: it tests them. A slab block is a run of frame rows holding more than
#: MIN_TABLE_W slab pixels: the tallest such run, or where the strip is
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
    return _block_why(mask, merge_gap)[0]


def _runs(mask: np.ndarray, merge_gap: int) -> list[list[int]]:
    """Runs `[start, end)` of frame rows holding more than MIN_TABLE_W slab
    pixels, joining runs `merge_gap` rows apart or closer."""
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
    strip_rect: tuple[int, int, int, int] | None = None,
    icons: dict | None = None,
) -> ScoreboardRead:
    """Read every row's K/D/A, and say which row is the local player's.

    `strip_rect` is the frame rectangle the round-history strip witness reads
    (`strip_rect()`); where it reads the strip present, the blocks are the
    runs that meet the strip's marker lines. Without it, or where the strip
    is absent or unreadable, they are the tallest runs. Enemy rows the line
    places without a red run to confirm them open only when every one of
    their portraits scores at least PORTRAIT_CONFIRM_MIN against `icons`
    (`load_agent_icons`); without `icons` such a board closes. A closed board
    says which test closed it (`ScoreboardRead.reason`)."""
    H, W = frame.shape[:2]
    green, red = _slabs(frame)
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

    # Table edges from the ally block's own dense columns, which are cleaner
    # than a whole-frame profile that also catches the team bars up top.
    dense = np.where(green[ally[0]:ally[1]].mean(axis=0) > 0.5)[0]
    if dense.size == 0:
        return ScoreboardRead(False, reason="no_dense_columns", **closed)
    x0, x1 = int(dense.min()), int(dense.max())
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
        scores = [portrait_agent(frame, (px, a, px + (z - a), z), icons)["portrait_agent_score"]
                  for a, z in _split(enemy)]
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


def portrait_agent(frame: np.ndarray, box: tuple[int, int, int, int],
                   icons: dict) -> dict:
    """Raw agent-art scores for one portrait box, and its brightness gain.

    Context-free: every agent in the gallery is scored and nothing is named.
    `portrait_gain` is the least-squares slope of the row's pixels on the
    matched art's pixels. The game dims a dead player's portrait, which lowers
    that slope while the normalised correlation holds; a naturally dark agent
    keeps a slope near one. Adjudication decides whether a board is expanded
    enough to trust either number.
    """
    empty = {"portrait_agent_best": None, "portrait_agent_score": None,
             "portrait_agent_second": None, "portrait_agent_margin": None,
             "portrait_gain": None, "portrait_agent_scores": None}
    if not icons:
        return {**empty, "portrait_agent_reason": "no_agent_icons"}
    x0, y0, x1, y1 = box
    win = frame[max(0, y0 - AGENT_PAD):max(0, y1 + AGENT_PAD),
                max(0, x0 - AGENT_PAD):max(0, x1 + AGENT_PAD)]
    gallery = _gpu_gallery(icons)
    scores, where = (_art_scores_gpu(win, gallery) if gallery is not None
                     else _art_scores_cpu(win, icons))
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if len(ranked) < 2 or where[ranked[0][0]] is None:
        return {**empty, "portrait_agent_reason": "portrait_box_smaller_than_art"}
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
_GPU_GALLERIES: dict[int, tuple[dict, object]] = {}


def portrait_scorer() -> str:
    """Which scorer `portrait_agent` uses in this process, for provenance."""
    return "cupy-float64" if _gpu_gallery(None) is not None else "opencv-float32"


def _gpu_gallery(icons: dict | None):
    """The agent art stacked per scale on the GPU, or None to score on the CPU.

    `icons=None` asks only whether the GPU path is available. The gallery is
    built once per icons dict and kept with it.
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
        return held[1]
    names = list(icons)
    per_scale = []
    for i in range(min(len(ims) for ims, _ in icons.values())):
        t = np.stack([icons[n][0][i] for n in names]).astype(np.float64)
        m = np.stack([icons[n][1][i] for n in names]).astype(np.float64)
        area = np.maximum(m.sum(axis=(1, 2)), 1)                    # (agents, 3)
        mean = (t * m).sum(axis=(1, 2)) / area
        tz = (t - mean[:, None, None, :]) * m                       # zero-mean art
        per_scale.append((t.shape[1], t.shape[2], cp.asarray(tz), cp.asarray(m),
                          cp.asarray(area), cp.asarray((tz ** 2).sum(axis=(1, 2, 3)))))
    gallery = (names, per_scale)
    _GPU_GALLERIES[id(icons)] = (icons, gallery)
    return gallery


def _art_scores_gpu(win: np.ndarray, gallery) -> tuple[dict, dict]:
    """`_art_scores_cpu` in float64 on the GPU, every agent of a scale at once.

    The same masked normalised correlation: sum((I - mean_I) * (T - mean_T))
    over the mask, over the root of both masked variances, summed over the
    three channels as OpenCV sums them. OpenCV accumulates in float32, so
    scores differ from it in the fourth decimal: 9 of 4640 rounded scores on
    7010b3d62460, by at most 0.0007, with the same best agent on 160 of 160
    rows; over the whole session 1033 of 95294, at most 0.0047 on a weak
    score, with the same best agent on 3310 of 3310 rows. A zero variance scores -1, as OpenCV's NaN does after
    `nan_to_num`. The first maximum in row-major order wins, as in
    `cv2.minMaxLoc`, and a later scale must beat an earlier one strictly.
    """
    import cupy as cp
    names, per_scale = gallery
    img = cp.asarray(win, dtype=cp.float64)
    found = []
    for i, (th, tw, tz, m, area, tnorm) in enumerate(per_scale):
        if th > win.shape[0] or tw > win.shape[1]:
            continue
        v = cp.lib.stride_tricks.sliding_window_view(img, (th, tw, 3))[:, :, 0]
        num = cp.einsum("yxijc,aijc->ayx", v, tz)
        s1 = cp.einsum("yxijc,aijc->ayxc", v, m)
        s2 = cp.einsum("yxijc,aijc->ayxc", v * v, m)
        var = (s2 - s1 * s1 / area[:, None, None, :]).sum(-1)
        den = cp.sqrt(cp.maximum(var, 0) * tnorm[:, None, None])
        r = cp.where(den > 0, num / cp.where(den > 0, den, 1.0), -1.0)
        flat = r.reshape(len(names), -1)
        arg = flat.argmax(axis=1)
        found.append((i, r.shape[2], cp.asnumpy(flat[cp.arange(len(names)), arg]),
                      cp.asnumpy(arg)))
    scores, where = {}, {}
    for a, name in enumerate(names):
        best = (-1.0, None)
        for i, width, vals, args in found:
            if float(vals[a]) > best[0]:
                y, x = divmod(int(args[a]), width)
                best = (float(vals[a]), (i, (x, y)))
        scores[name], where[name] = best
    return scores, where


def portrait_observations(frame: np.ndarray, board: ScoreboardRead,
                          icons: dict | None = None) -> list[dict]:
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
    result = []
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
        got = {"display_row": index, "portrait_x0": x0,
               "portrait_y0": row.y0, "portrait_x1": x0 + art.shape[1],
               "portrait_y1": row.y1,
               "portrait_detail": appearance.detail(art),
               "portrait_composition": appearance.hsv_composition(art).tolist()}
        if icons is not None:
            got.update(portrait_agent(frame, (x0, row.y0, x0 + height, row.y1), icons))
        result.append(got)
    return result


class ScoreboardReader:
    """Sparse context-free scoreboard observations for a shared decode pass."""

    def __init__(self, profile_name: str, hz: float = 2.0, spans=None,
                 min_confidence: float = 0.80, min_margin: float = 0.04,
                 icons_root=None):
        self.name, self.hz, self.spans = "scoreboard", hz, spans
        self.profile_name = profile_name
        self.templates = Templates.load(profile_name)
        self.icons = load_agent_icons(icons_root) if icons_root is not None else {}
        self.min_confidence, self.min_margin = min_confidence, min_margin
        self.frames_offered = 0
        self.frames_open = 0
        self.rows: list[dict] = []
        # One per frame offered, open or closed, with the test that closed it:
        # a closed board is an observation too, and a second presence witness
        # (`scoreboard_strip`) is reconciled with it sample by sample.
        self.samples: list[dict] = []

    def feed(self, sample) -> None:
        self.frames_offered += 1
        h, w = sample.frame.shape[:2]
        board = read_scoreboard(sample.frame, self.templates,
                                self.min_confidence, self.min_margin,
                                strip_rect(self.profile_name, w, h), self.icons)
        self.samples.append({"frame_idx": int(sample.frame_idx), "t_ms": float(sample.t_ms),
                             "open": board.open_, "reason": board.reason,
                             "anchor": board.anchor, "strip": board.strip,
                             "edges": None if board.edges is None else list(board.edges),
                             "confirm": board.confirm})
        if not board.open_:
            return
        self.frames_open += 1
        portraits = {r["display_row"]: r for r in
                     portrait_observations(sample.frame, board, self.icons)}
        for index, row in enumerate(board.rows):
            self.rows.append({
                "frame_idx": int(sample.frame_idx), "t_ms": float(sample.t_ms),
                "display_row": index, "team": row.team, "anchor": board.anchor,
                "confirm": board.confirm,
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
                    "open_confirms": dict(sorted(confirms.items()))}
        return ([coverage]
                + [{**common, "kind": "row_observation",
                    "observation_key": f"{session_id}:{r['frame_idx']}:{r['display_row']}",
                    **r} for r in self.rows]
                + [{**common, "kind": "sample", **s} for s in self.samples])
