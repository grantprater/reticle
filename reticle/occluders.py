r"""The map's occluders from the baked static: full-height walls and boxes.

    .\.venv\Scripts\python.exe -m reticle occluders --all          # bake every key
    .\.venv\Scripts\python.exe -m reticle occluders KEY --dry-run  # classify, write nothing

**Part of the geometry builder.** The occluder table is baked `(map, profile)`
geometry that `cone` consumes, so it is built here, in `reticle/`, and read
from the geometry npz by `team_vision` and `barriers`. It reads the key's
baked arrays only -- never a session's pixels, never a video.

Why this exists
---------------
`cone.passable_from` stopped a ray only at `labels == BOXEDGE`, and `labels`
comes from the wiki art (`minimap_geometry.classify_art`), warped into widget
pixels by `map_shade.shade_arrays` with one winner per pixel. The art's line
work is a few art pixels wide and the warp shrinks it five to seven times, so
a line covers under half of most widget pixels and loses them to the floor or
the site paint beside it. On `ascent__valorant-16x9` 37% of the static's
bright-white pixels are labelled FLOOR: the line between B main and B site,
the far sides of most boxes. The player, 2026-09-29: the bright white lines
on the minimap are walls [domain:minimap/white-lines-are-walls], and many
boxes carry only one or two of their edges.

The in-game widget draws its own walls, pixel-exact, and the baked `static`
already holds them: it is the geometry key's reference median, the one
capture-derived array the builder is allowed to keep
[domain:capture/session-pixels-are-not-the-map]. This reads the walls from it
and writes them into the geometry npz ADDITIVELY, as `map_shade` does:

    occ            uint8   OPEN 0, WALL 1, BOX 2
    box_id         int16   0, or the box a BOX pixel belongs to (1..n)
    occ_built_by   str     hash of this file and the functions it calls

`labels`, `static` and the rest are untouched, so `minimap_geometry`'s stamp
does not move and no geometry needs a rebuild from video: this reads stored
arrays only and takes seconds. `doctor`'s OCCLUDERS check compares each npz's
`occ_built_by` with `occluder_stamp`.

The classes
-----------
**A line** is a thin light structure in the static: low saturation, at least
V 150, and brighter than its own neighbourhood's opening (a white top-hat), so
a ramp or a lighter floor shade -- a broad region -- is not a line however
bright. A line is BRIGHT where it reaches V 185 (or is the antialiased
shoulder of a pixel that does) and FAINT elsewhere: the walls are drawn
bright, the box outlines and the floor marks (a stair, a drop, a dashed edge)
faint. Diagonal steps are sealed to 4-connected, because `cone.raycast`
rounds each step to the nearest pixel and passes between two pixels that
touch only at a corner. The paint between a site letter's strokes passes the
line test and is dropped.

**A box** is a closed shape with its own id, FITTED rather than repaired with a
closing radius [domain:minimap/fit-not-repair]: a small light region the
lines enclose, grown into its outline and filled; a line component too small
to leave an interior; or any other faint line, which is not a wall and so
blocks by default like a box while the light decides.

**A wall** is every bright line, plus the art's BORDER and BOXEDGE away from a
box (the art still knows where a wall is where the median washed it out). A
bright line stays a wall where it bounds a box: a box against a wall.

What this leaves open, measured on the sheets: the faint class also holds the
faint shoulders beside some walls, a rotating door's dashed arc on Lotus, and
floor marks whose height the minimap does not show; each is a box, blocks by
default, and its pass rate is the light's to learn.

A wall always stops a ray. A box stops it by default and may pass light when
the caster jumps or stands higher (the player, 2026-09-29): `cone.box_crossings`
reports which boxes each cone crossed, so the drawn light can decide.

occluders-2.0.0: the sorted line classes decide
-----------------------------------------------
The rule above calls every bright line a wall and every faint line a box, so
a ramp or elevation line, a heaven edge and an overhang start stopped rays
that cross them in the game [domain:minimap/raised-edge-lines]
[domain:minimap/overhang-start-line]. `prototypes/line_classes.py` bakes the
line sorter's verdict (`prototypes/raised_edges.py`, raised-edges-0.3.0),
overridden by the player's segment answers where they exist, into the npz:

    line_cls        uint8   LINE_NONE 0, WALL 1, BOX 2, RAMP 3, OTHER 4, UNREAD 5
    line_src        uint8   where each line pixel's class came from (SRC_*)
    line_hints      str     JSON: height hints (the player's notes, domain/heights)
    lines_built_by  str     the baker's stamp; lines_static_sha the static it read

`apply_lines` then rewrites the table: a WALL line is WALL, a BOX line BOX, a
RAMP or OTHER line OPEN, an UNREAD line keeps the rule above. A box whose
outline is mostly non-occluding loses its fill, and an art WALL pixel beside
a non-occluding line and no occluding one is cleared (the overhang-start line
left 47 such pixels). `bake` writes three more arrays:

    box_height      uint8   H_NONE 0, UNKNOWN 1, SHORT 2, TALL 3, BY_FLOOR 4
    occ_boxes       str     JSON: each box's height class and its source
    occ_lines       str     the `lines_built_by` the table was built over, or
                            "absent: ...", "refused: ...", "stale: ..."
    occ_validation  str     "labels" where the player's answers validate the
                            key's classes, "unvalidated" where only the
                            sorter's generalisation stands, or "no line classes"

A box's height is a hint's, never a guess: SHORT blocks a standing viewer and
not a jumping one, TALL blocks both [domain:minimap/boxes-block-unless-raised],
BY_FLOOR depends on the caster's floor (the heights file says which), and
every box no hint names is UNKNOWN. WALL, BOX and `box_id` keep their meaning,
so `cone.box_crossings` and every reader of `occ` work unchanged.

A key without line classes, or whose `lines_static_sha` or line mask no
longer matches its static, keeps the rule above and says why in `occ_lines`;
`doctor` LINES reports it.

occluders-2.1.0: walls at the void, and fitted shapes
----------------------------------------------------
The player reviewed Haven's 2.0.0 sheet on 2026-09-30. Two rules came of it:

- A line with void directly beyond it is a wall, on every key
  [domain:minimap/void-border-lines-are-walls]. `prototypes/line_classes.py`
  (line-classes-1.1.0) writes it into `line_cls` last, so `apply_lines` needs
  nothing new: 2.0.0 had opened the perimeter walls the sorter read as ramps.
- Occluders the outline rule misses are fitted as shapes
  [domain:minimap/occluder-shapes], `shapes()`, and `apply_lines` writes each as
  one box, of UNKNOWN height, never over a WALL. `raised_boxes` fits a region
  the art shades one rung above everything round it: the diagonal box, the T,
  and the box its static draws by one top line. `doorways` fits the faint
  diagonal leaves drawn in a straight wall's gap. `info["lines"]["shapes"]`
  lists each with its class (`diagonal`, `non_rectangular`, `partly_drawn`).

A general faint-diagonal-stroke search fired on every stair, ramp edge and
box corner; the doorway rule is the narrow one kept, and it finds Haven's
Garage leaves and one gap on Summit.

Owns [owns:map-occluders].
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import cv2
import numpy as np

from . import geometry as G
from . import metrics
from .cone import OCC_BOX as BOX, OCC_OPEN as OPEN, OCC_WALL as WALL
from .minimap import BORDER, BOXEDGE, HOLE, PLANT, VOID, _odd, widget_scale
from .store import DEFAULT_STORE

OCC_NAMES = {OPEN: "open", WALL: "wall", BOX: "box"}
OCCLUDER_VERSION = "occluders-2.1.0"

#: The baked line classes (`line_cls`), as `prototypes/line_classes.py` writes them.
LINE_NONE, LINE_WALL, LINE_BOX, LINE_RAMP, LINE_OTHER, LINE_UNREAD = 0, 1, 2, 3, 4, 5
LINE_NAMES = {LINE_WALL: "wall", LINE_BOX: "box", LINE_RAMP: "ramp_or_elevation_line",
              LINE_OTHER: "other", LINE_UNREAD: "unread"}
#: Where a line pixel's class came from (`line_src`): a sorter segment, a connector (rule G),
#: a fragment, the nearest classed line pixel, the player's answer, the player's 0.1.0 answer
#: carried to a segment, nothing (UNREAD), or the void-border rule, which makes a line pixel with
#: void directly beyond it a WALL whatever it was [domain:minimap/void-border-lines-are-walls].
(SRC_NONE, SRC_SEGMENT, SRC_CONNECTOR, SRC_FRAGMENT, SRC_NEAREST, SRC_PLAYER, SRC_CARRIED,
 SRC_UNREAD, SRC_VOID_BORDER) = range(9)
SRC_NAMES = {SRC_SEGMENT: "sorter_segment", SRC_CONNECTOR: "sorter_connector",
             SRC_FRAGMENT: "sorter_fragment", SRC_NEAREST: "nearest_classed_line",
             SRC_PLAYER: "player_answer", SRC_CARRIED: "player_answer_carried_0.1.0",
             SRC_UNREAD: "unread", SRC_VOID_BORDER: "void_border_wall"}
#: A box's height class (`box_height`, per pixel).
H_NONE, H_UNKNOWN, H_SHORT, H_TALL, H_BY_FLOOR = 0, 1, 2, 3, 4
HEIGHT_NAMES = {H_UNKNOWN: "unknown", H_SHORT: "short", H_TALL: "tall", H_BY_FLOOR: "by_floor"}
HEIGHT_CODES = {v: k for k, v in HEIGHT_NAMES.items()}
#: An art WALL pixel within this many px of a non-occluding line, and of no occluding one, is
#: cleared; a box fill is cleared when more than FILL_OPEN_SHARE of its outline is non-occluding.
RING_PX = 1
FILL_OPEN_SHARE = 0.5
#: A new BOX pixel within this many px of a kept box joins it; else its component is a new box.
BOX_JOIN_PX = 2
#: A `bbox` height hint names a box when at least this share of the box's pixels lies inside it.
HINT_AREA_SHARE = 0.5
#: ...and only when the boxes it names fill at least this share of its bbox. 0: no gate. At 0.25
#: it dropped Split's b-far-left-box, whose heights row names its baked box (box 17 covers 0.035
#: of the row's bbox); the Lotus C Mound, a region drawn as a wall, names no box by the area
#: share alone.
HINT_COVER_MIN = 0.0

#: The art's `shade_kind` codes, as `prototypes/map_shade.py` writes them.
KIND_VOID, KIND_FLOOR, KIND_RAMP, KIND_SHADOW, KIND_LINE, KIND_SITE = 0, 1, 2, 3, 4, 5
#: A raised box (`raised_boxes`): the ring read round the region (px), and the least share of
#: that ring's non-void pixels drawn as an edge.
RAISED_RING_PX = 2
RAISED_EDGE_SHARE = 0.25
#: ...and a rung is significant in that ring from this share of its floor pixels: one significant
#: lower rung at most, and at most this share at the region's rung or above (the warp's noise).
RAISED_RUNG_SHARE = 0.15
#: ...and a box is partly drawn when the static's lines cover less than this share of that ring:
#: the shading, not the lines, gives the rest of its extent.
PARTLY_DRAWN_SHARE = 0.5
#: A door leaf (`doorways`): grey pixels this much brighter than their neighbourhood's opening,
#: in a wall gap DOOR_GAP_MIN..DOOR_GAP_MAX long between stubs at least DOOR_STUB_PX long, within
#: DOOR_BAND_PX of the wall's line, spanning DOOR_SPAN_SHARE of the gap (px at 465, scaled).
STROKE_TOPHAT_MIN = 18
DOOR_GAP_MIN = 6.0
DOOR_GAP_MAX = 16.0
DOOR_STUB_PX = 6.0
DOOR_BAND_PX = 4.0
DOOR_SPAN_SHARE = 0.5
#: Shape classes (`shape_features`): a rotated rectangle this many degrees off both axes is
#: diagonal; an outline notched this deep (px at 465, scaled) is not a rectangle.
DIAGONAL_DEG = 15.0
DIAGONAL_MIN_LEN = 10.0
NOTCH_PX = 3.0

#: A line pixel is grey: the site paint sits at saturation 43-58 and is broad,
#: the lines at 0-20.
LINE_S_MAX = 40
#: The site letter is dark paint, and the paint between its strokes is thin
#: and bright, so it passes the line test: a line pixel within this (scaled)
#: of the letter is dropped.
LETTER_V_MAX = 100
LETTER_PAD_PX = 3
#: ...bright: the floor rung is V 117 and the lightest terrain rung under 165.
#: A line's CORE is at least LINE_CORE_V; a pixel down to LINE_V_MIN is kept
#: only beside a core pixel, as the line's antialiased shoulder, so a faint
#: grey floor mark (a stair, a drop) is not a wall.
LINE_V_MIN = 150
LINE_CORE_V = 185
#: ...and thin: at least this much brighter than the opening of its
#: neighbourhood (`LINE_OPEN_PX`, scaled), so a lighter floor shade, which is
#: a broad region, is never a line.
LINE_TOPHAT_MIN = 25
LINE_OPEN_PX = 5
#: Line components smaller than this (scaled by area) are glyph specks.
LINE_MIN_AREA = 6
#: A box is an enclosed region at most this large (px at 465, scaled by area)
#: and at least this large; smaller is a glyph ring (an orb, a spawn mark).
BOX_MAX_AREA = 900
BOX_MIN_AREA = 2
#: A whole line component that fits in a square this wide (px at 465, scaled)
#: and touches no hole is a box drawn solid.
BOX_BLOB_PX = 12
#: An enclosed region darker than this (median V) is a pillar or a hole.
BOX_V_MIN = 100


def lines(static: np.ndarray, labels: np.ndarray):
    """`(bright, faint)`: the static's thin light structure inside the map.

    A pixel is a line when it is grey, at least LINE_V_MIN, and brighter than
    the opening of its neighbourhood by LINE_TOPHAT_MIN. It is BRIGHT when it
    reaches LINE_CORE_V or is the antialiased shoulder of a pixel that does;
    the rest is FAINT. Walls are drawn bright; box outlines and floor marks
    (a stair, a drop, a dashed edge) are drawn faint. Both are 4-connected
    (`seal_diagonals`), and neither holds a pixel beside a site letter.
    """
    sc = widget_scale(static.shape[1])
    hsv = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    k = _odd(LINE_OPEN_PX * sc)
    opened = cv2.morphologyEx(v, cv2.MORPH_OPEN, np.ones((k, k), np.uint8))
    tophat = v.astype(np.int16) - opened.astype(np.int16)
    foot = cv2.dilate((labels != VOID).astype(np.uint8), np.ones((7, 7), np.uint8)) > 0
    cand = foot & (s <= LINE_S_MAX) & (v >= LINE_V_MIN) & (tophat >= LINE_TOPHAT_MIN)
    letter = (labels == PLANT) & (v <= LETTER_V_MAX)
    kl = _odd(2 * LETTER_PAD_PX * sc + 1)
    cand &= ~(cv2.dilate(letter.astype(np.uint8), np.ones((kl, kl), np.uint8)) > 0)
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, 4] >= max(2, LINE_MIN_AREA * sc * sc)
    cand = keep[lab]
    core = cand & (v >= LINE_CORE_V)
    bright = core | (cand & (cv2.dilate(core.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0))
    bright = seal_diagonals(bright)
    every = seal_diagonals(cand | bright)
    return bright, every & ~bright


def line_mask(static: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Every line, bright and faint: what the widget draws as an edge."""
    bright, faint = lines(static, labels)
    return bright | faint


def seal_diagonals(m: np.ndarray) -> np.ndarray:
    """Add a pixel wherever two line pixels touch only at a corner.

    Not a closing: it adds exactly the one pixel a 4-connected raster line
    needs, and leaves every gap of a whole pixel open.
    """
    m = m.copy()
    a = m[:-1, :-1]
    b = m[:-1, 1:]
    c = m[1:, :-1]
    d = m[1:, 1:]
    # a and d touch diagonally with b and c both empty: fill b.
    fill_b = a & d & ~b & ~c
    # b and c touch diagonally with a and d both empty: fill a.
    fill_a = b & c & ~a & ~d
    m[:-1, 1:] |= fill_b
    m[:-1, :-1] |= fill_a
    return m


def _fill(m: np.ndarray) -> np.ndarray:
    """The outer contour of `m`, filled: the fitted closed shape."""
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    poly = np.zeros(m.shape, np.uint8)
    cv2.drawContours(poly, cs, -1, 1, thickness=-1)
    return poly > 0


def classify(static: np.ndarray, labels: np.ndarray):
    """`(occ, box_id, info)` for one geometry. Pure over baked arrays.

    Boxes, in order, each a closed shape with its own id:

    1. `outline`: a small, light region the lines enclose (4-connected, so an
       8-connected line seals it), with its outline -- the region grown by
       one pixel into the lines, filled;
    2. `blob`: a whole line component inside a BOX_BLOB_PX square that touches
       no hole or void -- a box drawn too small to leave an interior;
    3. `faint`: every other faint line component. It encloses nothing the
       rules above accept, and it is not a wall, so it blocks by default like
       a box and the light decides.

    A bright line is a WALL everywhere, including where it bounds a box (a box
    against a wall). The art's BORDER and BOXEDGE are WALL too, except inside
    or beside a box shape.
    """
    sc = widget_scale(static.shape[1])
    bright, faint = lines(static, labels)
    line = bright | faint
    v = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)[:, :, 2]
    dark = np.isin(labels, (VOID, HOLE))
    n, reg, st, _ = cv2.connectedComponentsWithStats((~line).astype(np.uint8), 4)
    border_ids = set(np.unique(np.r_[reg[0], reg[-1], reg[:, 0], reg[:, -1]]).tolist())
    box_id = np.zeros(labels.shape, np.int16)
    boxes = []

    def add(poly, kind, x, y, bw, bh, interior=0):
        poly = poly & (box_id == 0)
        if not poly.any():
            return
        box_id[poly] = len(boxes) + 1
        boxes.append({"id": len(boxes) + 1, "x": int(x), "y": int(y), "w": int(bw),
                      "h": int(bh), "interior_px": int(interior), "px": int(poly.sum()),
                      "drawn": kind})

    amax, amin = BOX_MAX_AREA * sc * sc, max(2.0, BOX_MIN_AREA * sc * sc)
    for i in range(1, n):
        a = int(st[i, 4])
        if i in border_ids or a > amax or a < amin:
            continue
        m = reg == i
        if float(np.median(v[m])) < BOX_V_MIN or dark[m].mean() > 0.5:
            continue
        grown = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
        add(_fill(grown & (line | m)), "outline", *st[i, :4], interior=a)
    near_dark = cv2.dilate(dark.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    nl, llab, lst, _ = cv2.connectedComponentsWithStats(line.astype(np.uint8), 8)
    side = BOX_BLOB_PX * sc
    for j in range(1, nl):
        if max(lst[j, 2], lst[j, 3]) > side:
            continue
        m = llab == j
        if (m & near_dark).any() or (box_id[m] > 0).any():
            continue
        add(_fill(m), "blob", *lst[j, :4])
    nf, flab, fst, _ = cv2.connectedComponentsWithStats((faint & (box_id == 0)).astype(np.uint8), 8)
    for j in range(1, nf):
        add(flab == j, "faint", *fst[j, :4])

    in_box = box_id > 0
    beside_box = cv2.dilate(in_box.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
    art = np.isin(labels, (BORDER, BOXEDGE)) & ~beside_box
    occ = np.zeros(labels.shape, np.uint8)
    occ[in_box] = BOX
    occ[bright | art] = WALL
    box_id[occ != BOX] = 0
    info = {"bright_px": int(bright.sum()), "faint_px": int(faint.sum()),
            "line_px": int(line.sum()), "wall_px": int((occ == WALL).sum()),
            "box_px": int((occ == BOX).sum()),
            "boxes": [b for b in boxes if (box_id == b["id"]).any()]}
    return occ, box_id, info


def occluder_stamp() -> str:
    """This module and the scale helpers it calls: the table's `occ_built_by`."""
    return hashlib.sha256(
        Path(__file__).read_bytes()
        + metrics.fingerprint(widget_scale, _odd).encode()).hexdigest()


def static_sha(static: np.ndarray) -> str:
    """The hash `lines_static_sha` records: the static's shape and bytes."""
    return hashlib.sha256(str(static.shape).encode() + np.ascontiguousarray(static).tobytes()).hexdigest()


def read_lines(arrays: dict) -> tuple[np.ndarray | None, list, str]:
    """`(line_cls, hints, occ_lines)` from one npz's arrays: the baked line classes, or None
    with the reason in `occ_lines` ("absent: ...", "refused: ...", "stale: ...").

    Stale is checked, not assumed: the classes must have been read from this static
    (`lines_static_sha`) and must cover exactly this module's line mask (`lines`)."""
    if "lines_refused" in arrays:
        return None, [], f"refused: {arrays['lines_refused']}"
    if "line_cls" not in arrays:
        return None, [], "absent: no line_cls in the npz (prototypes/line_classes.py bake)"
    static, labels, cls = arrays["static"], arrays["labels"], arrays["line_cls"]
    if str(arrays.get("lines_static_sha", "")) != static_sha(static):
        return None, [], "stale: line_cls was read from another static"
    if cls.shape != labels.shape or not np.array_equal(cls > 0, line_mask(static, labels)):
        return None, [], "stale: line_cls does not cover this module's line mask"
    hints = json.loads(str(arrays["line_hints"])) if "line_hints" in arrays else []
    return cls, hints, str(arrays.get("lines_built_by", "unstamped"))


def _dilated(m: np.ndarray, px: int) -> np.ndarray:
    k = 2 * px + 1
    return cv2.dilate(m.astype(np.uint8), np.ones((k, k), np.uint8)) > 0


def apply_lines(occ: np.ndarray, box_id: np.ndarray, line_cls: np.ndarray, hints: list = (),
                shape_list: list = ()):
    """`(occ, box_id, box_height, info)`: the shape table (`classify`) rewritten by the baked
    line classes. Pure over its arguments.

    1. A WALL line pixel is WALL, a BOX line pixel BOX, a RAMP or OTHER line pixel OPEN; an
       UNREAD line pixel keeps its `classify` class.
    2. A box's fill (its pixels off the lines) stays BOX unless more than FILL_OPEN_SHARE of
       the line pixels round it are non-occluding.
    3. Any other occluder pixel off the lines (the art's BORDER and BOXEDGE, a cleared fill)
       within RING_PX of a non-occluding line pixel and of no occluding one is OPEN.
    4. Box ids: a pixel that stays BOX keeps its id; a new BOX pixel within BOX_JOIN_PX of a kept
       box joins the nearest; the rest are new boxes, one per 8-connected component.
    5. Each box's height class comes from `hints` (`prototypes/line_classes.py`): a `segment`
       hint names every box within one pixel of its pixels, a `bbox` hint every box with at
       least HINT_AREA_SHARE of its pixels inside, when those boxes fill HINT_COVER_MIN of the
       bbox. One class names the box; none, or hints that disagree, leave it UNKNOWN. A
       `does_not_block` hint changes no class; `info` reports what still occludes under it.
    """
    line = line_cls > 0
    occl = np.isin(line_cls, (LINE_WALL, LINE_BOX))
    open_ = np.isin(line_cls, (LINE_RAMP, LINE_OTHER))
    new = occ.copy()
    new[line_cls == LINE_WALL] = WALL
    new[line_cls == LINE_BOX] = BOX
    new[open_] = OPEN
    h, w = occ.shape
    cleared_fills, fill_px = [], 0
    for b in np.unique(box_id[box_id > 0]):
        ys, xs = np.nonzero(box_id == b)
        y0, y1, x0, x1 = max(0, ys.min() - 2), min(h, ys.max() + 3), max(0, xs.min() - 2), min(w, xs.max() + 3)
        m = box_id[y0:y1, x0:x1] == b
        rim = _dilated(m, 1) & line[y0:y1, x0:x1]
        n_rim = int(rim.sum())
        share = float(open_[y0:y1, x0:x1][rim].sum()) / n_rim if n_rim else 0.0
        if share > FILL_OPEN_SHARE:
            fill = m & ~line[y0:y1, x0:x1]
            new[y0:y1, x0:x1][fill] = OPEN
            fill_px += int(fill.sum())
            cleared_fills.append(int(b))
    ring = (new > 0) & ~line & _dilated(open_, RING_PX) & ~_dilated(occl, RING_PX)
    new[ring] = OPEN
    # the fitted shapes (`shapes`): after the clearing, so a shape's fill is never cleared
    shape_rows = []
    if len(shape_list):
        shape_bid = box_id.astype(np.int32).copy()
        shape_bid[new != BOX] = 0
        shape_rows = _add_shapes(new, shape_bid, shape_list)
        box_id = np.where(new == BOX, shape_bid, 0).astype(np.int32)
    # box ids
    newbox = new == BOX
    bid = np.where(newbox & (box_id > 0), box_id, 0).astype(np.int16)
    orphan = newbox & (bid == 0)
    if orphan.any() and (bid > 0).any():
        dist, lab = cv2.distanceTransformWithLabels((bid == 0).astype(np.uint8), cv2.DIST_L2, 5,
                                                    labelType=cv2.DIST_LABEL_PIXEL)
        zy, zx = np.nonzero(bid > 0)
        lut = np.zeros(lab.max() + 1, np.int16)
        lut[lab[zy, zx]] = bid[zy, zx]
        join = orphan & (dist <= BOX_JOIN_PX)
        bid[join] = lut[lab[join]]
    orphan = newbox & (bid == 0)
    n, comp = cv2.connectedComponents(orphan.astype(np.uint8), connectivity=8)
    top = int(max(bid.max(), box_id.max()))
    bid[orphan] = (comp[orphan] + top).astype(np.int16)
    # heights
    height = np.where(newbox, H_UNKNOWN, H_NONE).astype(np.uint8)
    names = {}
    seg_masks = []
    for hn in hints:
        if hn["kind"] == "segment":
            m = np.zeros(occ.shape, bool)
            pts = np.array(hn["px"], int).reshape(-1, 2)
            m[pts[:, 1], pts[:, 0]] = True
            seg_masks.append((hn, _dilated(m, 1)))
    ids = [int(b) for b in np.unique(bid[bid > 0])]
    # a bbox hint names the boxes mostly inside it, and only when they fill HINT_COVER_MIN of it:
    # a hint that is a region (the Lotus C Mound, drawn as a wall) names none of the boxes on it
    by_bbox, hint_report = {}, []
    for hn in hints:
        if hn["kind"] != "bbox" or hn["class"] not in HEIGHT_CODES:
            continue
        x0, y0, x1, y1 = hn["bbox"]
        sub = bid[y0:y1 + 1, x0:x1 + 1]
        cand, cover = [], np.zeros(sub.shape, bool)
        for b in np.unique(sub[sub > 0]):
            ys, xs = np.nonzero(bid == b)
            inside = (xs >= x0) & (xs <= x1) & (ys >= y0) & (ys <= y1)
            if inside.mean() >= HINT_AREA_SHARE:
                cand.append(int(b))
                cover[max(0, ys.min() - y0):ys.max() - y0 + 1, max(0, xs.min() - x0):xs.max() - x0 + 1] = True
        share = float(cover.mean()) if cover.size else 0.0
        named = cand if share >= HINT_COVER_MIN else []
        for b in named:
            by_bbox.setdefault(b, []).append(hn)
        hint_report.append({"id": hn["id"], "class": hn["class"], "boxes": named,
                            "candidates": cand, "cover": round(share, 3)})
    for hn, near in seg_masks:
        hint_report.append({"id": hn["id"], "class": hn["class"],
                            "boxes": sorted({int(v) for v in bid[near & (bid > 0)]})})
    boxes = []
    for b in ids:
        m = bid == b
        got = [hn for hn, near in seg_masks if (m & near).any()] + by_bbox.get(b, [])
        ys, xs = np.nonzero(m)
        classes = sorted({g["class"] for g in got if g["class"] in HEIGHT_CODES})
        row = {"id": int(b), "px": int(m.sum()), "x": int(xs.min()), "y": int(ys.min()),
               "w": int(xs.max() - xs.min() + 1), "h": int(ys.max() - ys.min() + 1),
               "height": "unknown", "hints": [g["id"] for g in got]}
        if len(classes) == 1:
            row["height"] = classes[0]
            height[m] = HEIGHT_CODES[classes[0]]
            by = [g for g in got if g["class"] == classes[0]]
            row["source"] = sorted({g["source"] for g in by})
            if any("class_by_floor" in g for g in by):
                row["class_by_floor"] = next(g["class_by_floor"] for g in by if "class_by_floor" in g)
        elif len(classes) > 1:
            row["reason"] = f"hints disagree: {classes}"
        if len(classes) or got:
            names[int(b)] = row["height"]
        boxes.append(row)
    passes = []
    for hn in hints:
        if hn["class"] == "does_not_block":
            if hn["kind"] == "bbox":
                x0, y0, x1, y1 = hn["bbox"]
                sub = new[y0:y1 + 1, x0:x1 + 1]
            else:
                sub = new[[p[1] for p in hn["px"]], [p[0] for p in hn["px"]]]
            passes.append({"id": hn["id"], "occluding_px_left": int((sub > 0).sum()),
                           "wall_px": int((sub == WALL).sum()), "box_px": int((sub == BOX).sum())})
    info = {"line_px": int(line.sum()), "unread_line_px": int((line_cls == LINE_UNREAD).sum()),
            "opened_line_px": int((open_ & (occ > 0)).sum()),
            "cleared_fills": cleared_fills, "cleared_fill_px": fill_px, "cleared_ring_px": int(ring.sum()),
            "wall_px": int((new == WALL).sum()), "box_px": int((new == BOX).sum()),
            "boxes": boxes, "box_height_px": {HEIGHT_NAMES[c]: int((height == c).sum())
                                              for c in HEIGHT_NAMES},
            "named_boxes": names, "hints": hint_report, "does_not_block_hints": passes,
            "shapes": shape_rows}
    return new, bid, height, info


def _ring(m: np.ndarray, px: int = 1, conn4: bool = False) -> np.ndarray:
    k = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], np.uint8) if conn4 else np.ones((3, 3), np.uint8)
    return (cv2.dilate(m.astype(np.uint8), k, iterations=px) > 0) & ~m


def shape_features(m: np.ndarray) -> dict:
    """A fitted shape's geometry, for the shape classes.

    `non_rectangular`: its outline has a concavity at least NOTCH_PX deep (scaled) -- a T, an L
    -- so it is not one rectangle at any angle. `diagonal`: a shape with no such notch, at least
    1.5 times longer than wide and DIAGONAL_MIN_LEN long (scaled), whose long axis (PCA) lies at
    least DIAGONAL_DEG off both image axes; a smaller or squarer shape has no angle to read."""
    sc = widget_scale(m.shape[1])
    ys, xs = np.nonzero(m)
    pts = np.stack([xs, ys], 1).astype(np.float64)
    c = pts.mean(0)
    ev, evec = np.linalg.eigh(np.cov((pts - c).T)) if len(pts) > 2 else (np.ones(2), np.eye(2))
    elong = bool(ev[1] >= 2.25 * max(ev[0], 1e-6))
    off = float(_off_axis(np.degrees(np.arctan2(evec[1, 1], evec[0, 1])))) if elong else 0.0
    length = float(np.ptp((pts - c) @ evec[:, 1])) + 1.0 if len(pts) > 2 else 1.0
    cs, _ = cv2.findContours(m.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    notch = 0.0
    for cnt in cs:
        if len(cnt) < 4:
            continue
        hull = cv2.convexHull(cnt, returnPoints=False)
        try:
            d = cv2.convexityDefects(cnt, hull)
        except cv2.error:
            d = None
        if d is not None and len(d):
            notch = max(notch, float(d.reshape(-1, 4)[:, 3].max()) / 256.0)
    nonrect = notch >= NOTCH_PX * sc
    return {"angle_off_axis": round(off, 1), "notch_px": round(notch, 2),
            "diagonal": bool(elong and length >= DIAGONAL_MIN_LEN * sc and off >= DIAGONAL_DEG
                             and not nonrect),
            "non_rectangular": bool(nonrect)}


def raised_boxes(labels: np.ndarray, shade_kind: np.ndarray, shade_step: np.ndarray,
                 line: np.ndarray) -> list[dict]:
    """Boxes fitted from the art's floor shading: each a small floor region drawn a rung above
    everything round it, with no ramp beside it. Pure over baked arrays.

    The art draws a box's top a rung lighter than the floor it stands on
    [domain:minimap/floor-shade-is-elevation], and its shaded region is the box's whole extent
    whatever the lines draw of it: a diagonal box, a T, or a box drawn by its top line alone,
    whose other sides meet a wall or the site paint. The region is the fitted shape
    [domain:minimap/fit-not-repair]; no closing joins anything.

    A region (4-connected FLOOR pixels of one `shade_step` s >= 1) is a box when
    - its area lies between the `classify` box bounds (BOX_MIN_AREA, BOX_MAX_AREA, scaled);
    - the FLOOR pixels in its RAISED_RING_PX ring stand on one significant lower rung (no stair
      of intermediate rungs; a rung is significant from RAISED_RUNG_SHARE of them, and at most
      that share, the warp's noise, may stand at the region's rung or above), and no RAMP or
      SHADOW pixel is in that ring: a raised floor a player walks onto is elevation, not a box;
    - drawn edges (the static's lines or the art's LINE) make at least RAISED_EDGE_SHARE of the
      non-void pixels touching it.
    Each box's `mask` is its region grown one pixel into the lines round it and filled;
    `edge` is the static's line pixels that touch the region (its drawn outline), and the box is
    `partly_drawn` when they cover less than PARTLY_DRAWN_SHARE of the pixels touching it.
    """
    sc = widget_scale(labels.shape[1])
    amax, amin = BOX_MAX_AREA * sc * sc, max(2.0, BOX_MIN_AREA * sc * sc)
    floor = shade_kind == KIND_FLOOR
    drawn = line | (shade_kind == KIND_LINE)
    out = []
    for s in sorted({int(v) for v in np.unique(shade_step[floor]) if v >= 1}):
        n, lab, st, _ = cv2.connectedComponentsWithStats((floor & (shade_step == s)).astype(np.uint8), 4)
        for i in range(1, n):
            a = int(st[i, 4])
            if a < amin or a > amax:
                continue
            x, y, w, h = (int(v) for v in st[i, :4])
            pad = RAISED_RING_PX + 2
            y0, y1, x0, x1 = max(0, y - pad), min(labels.shape[0], y + h + pad), max(0, x - pad), min(labels.shape[1], x + w + pad)
            m = lab[y0:y1, x0:x1] == i
            ring = _ring(m, RAISED_RING_PX)
            k, stp = shade_kind[y0:y1, x0:x1], shade_step[y0:y1, x0:x1]
            if (ring & np.isin(k, (KIND_RAMP, KIND_SHADOW))).any():
                continue
            rf = stp[ring & (k == KIND_FLOOR)].astype(int)
            vals, cnt = np.unique(rf, return_counts=True)
            sig = {int(v) for v, c in zip(vals, cnt) if c >= RAISED_RUNG_SHARE * len(rf)}
            if len(sig) > 1 or (rf >= s).sum() > RAISED_RUNG_SHARE * len(rf):
                continue
            below = sig
            edge1 = _ring(m, 1)
            solid = edge1 & (k != KIND_VOID)
            share = float((solid & drawn[y0:y1, x0:x1]).sum()) / max(1, int(solid.sum()))
            outline = float((solid & line[y0:y1, x0:x1]).sum()) / max(1, int(solid.sum()))
            if share < RAISED_EDGE_SHARE:
                continue
            ln = line[y0:y1, x0:x1]
            grown = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            fill = _fill(grown & (m | ln | (k == KIND_LINE)))
            mask = np.zeros(labels.shape, bool)
            mask[y0:y1, x0:x1] = fill
            edge = np.zeros(labels.shape, bool)
            edge[y0:y1, x0:x1] = _ring(m, 1) & ln
            out.append({"drawn": "raised", "step": s, "base": (min(below) if below else None),
                        "x": x, "y": y, "w": w, "h": h, "region_px": a, "px": int(mask.sum()),
                        "edge_share": round(share, 3), "outline_drawn": round(outline, 3),
                        "partly_drawn": bool(outline < PARTLY_DRAWN_SHARE), "mask": mask, "edge": edge,
                        **shape_features(mask)})
    return out


def _off_axis(deg):
    """Degrees off the nearer image axis, 0..45."""
    return np.abs(((np.asarray(deg, float) + 45.0) % 90.0) - 45.0)


def _line_ends(bright: np.ndarray, dx: int, dy: int) -> tuple[np.ndarray, np.ndarray]:
    """`(stops, starts)`: bright pixels where a line stops running in +(dx, dy) (bright behind,
    nothing for two pixels ahead), and where one starts (the mirror)."""
    h, w = bright.shape
    b = np.pad(bright, 2)

    def at(ox, oy):
        return b[2 + oy:2 + oy + h, 2 + ox:2 + ox + w]
    stops = bright & at(-dx, -dy) & ~at(dx, dy) & ~at(2 * dx, 2 * dy)
    starts = bright & at(dx, dy) & ~at(-dx, -dy) & ~at(-2 * dx, -2 * dy)
    return stops, starts


def doorways(static: np.ndarray, labels: np.ndarray) -> list[dict]:
    """Door leaves drawn across a doorway: faint diagonal strokes in a gap of a wall.

    A door leaf drawn at an angle is antialiased across two pixels, so it rarely reaches
    LINE_V_MIN and `lines` keeps at most a faint piece of it. A search for faint diagonal strokes
    anywhere fires on every stair, ramp edge and box corner; a doorway is narrower than that: a
    straight wall that stops and resumes on the same row (or column, within one pixel) after a
    gap of DOOR_GAP_MIN..DOOR_GAP_MAX px, each stub at least DOOR_STUB_PX long, no bright pixel in
    the gap, the gap on the map. The gap holds a door when grey pixels at least STROKE_TOPHAT_MIN
    brighter than their neighbourhood's opening, within DOOR_BAND_PX of the wall's line, span
    DOOR_SPAN_SHARE of the gap and run at least DIAGONAL_DEG off both axes (PCA, elongated).
    The leaf is those pixels, diagonals sealed so a ray cannot pass between them; nothing is
    closed or extended. Lengths are px at 465, scaled.
    """
    sc = widget_scale(static.shape[1])
    hsv = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    k = _odd(LINE_OPEN_PX * sc)
    tophat = v.astype(np.int16) - cv2.morphologyEx(v, cv2.MORPH_OPEN, np.ones((k, k), np.uint8)).astype(np.int16)
    bright, _ = lines(static, labels)
    cand = (tophat >= STROKE_TOPHAT_MIN) & (s <= LINE_S_MAX) & (labels != VOID) & ~bright
    h, w = bright.shape
    lo, hi = int(round(DOOR_GAP_MIN * sc)), int(round(DOOR_GAP_MAX * sc))
    stub, band = int(round(DOOR_STUB_PX * sc)), int(round(DOOR_BAND_PX * sc)) + 1
    out, seen = [], set()
    for axis in (0, 1):
        dx, dy = (1, 0) if axis == 0 else (0, 1)
        stops, starts = _line_ends(bright, dx, dy)
        for y, x in zip(*np.nonzero(stops)):
            hit = None
            for g in range(lo, hi + 1):
                for o in (0, -1, 1):
                    xb, yb = (x + g, y + o) if axis == 0 else (x + o, y + g)
                    if 0 <= xb < w and 0 <= yb < h and starts[yb, xb]:
                        hit = (g, xb, yb)
                        break
                if hit:
                    break
            if not hit:
                continue
            g, xb, yb = hit
            if axis == 0:
                ok = (x - stub + 1 >= 0 and xb + stub <= w
                      and bright[max(0, y - 1):y + 2, x - stub + 1:x + 1].any(0).all()
                      and bright[max(0, yb - 1):yb + 2, xb:xb + stub].any(0).all())
                x0, x1, y0, y1 = x + 1, xb, max(0, min(y, yb) - band), max(y, yb) + band + 1
                inner = bright[min(y, yb):max(y, yb) + 1, x0:x1]
            else:
                ok = (y - stub + 1 >= 0 and yb + stub <= h
                      and bright[y - stub + 1:y + 1, max(0, x - 1):x + 2].any(1).all()
                      and bright[yb:yb + stub, max(0, xb - 1):xb + 2].any(1).all())
                x0, x1, y0, y1 = max(0, min(x, xb) - band), max(x, xb) + band + 1, y + 1, yb
                inner = bright[y0:y1, min(x, xb):max(x, xb) + 1]
            if not ok or inner.any() or (x0, y0, x1, y1) in seen:
                continue
            box = cand[y0:y1, x0:x1]
            if box.size == 0 or (labels[y0:y1, x0:x1] == VOID).mean() > 0.2:
                continue
            ys, xs = np.nonzero(box)
            if len(xs) < 4:
                continue
            span = float(box.any(0 if axis == 0 else 1).mean())
            pts = np.stack([xs, ys], 1).astype(np.float64)
            ev, evec = np.linalg.eigh(np.cov((pts - pts.mean(0)).T))
            off = float(_off_axis(np.degrees(np.arctan2(evec[1, 1], evec[0, 1]))))
            if span < DOOR_SPAN_SHARE or off < DIAGONAL_DEG or ev[1] < 2.25 * max(ev[0], 1e-6):
                continue
            seen.add((x0, y0, x1, y1))
            m = np.zeros(labels.shape, bool)
            m[y0:y1, x0:x1] = seal_diagonals(box)
            m &= labels != VOID
            out.append({"drawn": "doorway", "x": int(x0), "y": int(y0), "w": int(x1 - x0),
                        "h": int(y1 - y0), "gap_px": int(g), "px": int(m.sum()),
                        "span": round(span, 2), "angle_off_axis": round(off, 1),
                        "diagonal": True, "non_rectangular": False,
                        "mask": m, "edge": np.zeros(labels.shape, bool)})
    return out


def shapes(arrays: dict, line: np.ndarray | None = None) -> list[dict]:
    """Every fitted shape `apply_lines` adds to the table: the raised boxes, then the door
    leaves. Needs the npz's `static`, `labels`, `shade_kind` and `shade_step`."""
    if line is None:
        line = line_mask(arrays["static"], arrays["labels"])
    out = []
    if "shade_kind" in arrays and "shade_step" in arrays:
        out += raised_boxes(arrays["labels"], arrays["shade_kind"], arrays["shade_step"], line)
    out += doorways(arrays["static"], arrays["labels"])
    return out


def _add_shapes(new: np.ndarray, bid: np.ndarray, shape_list) -> list[dict]:
    """Write each fitted shape into the table as one box: its pixels off a WALL become BOX, and
    it takes a new id, absorbing every box at least half of whose pixels lie within one pixel
    of it. Returns each shape's report row."""
    rows = []
    for s in shape_list:
        m = s["mask"] & (new != WALL)
        if not m.any():
            continue
        new[m] = BOX
        near = _dilated(m, 1)
        top = int(bid.max()) + 1
        for b in np.unique(bid[near & (bid > 0)]):
            bm = bid == b
            if float((bm & near).sum()) / max(1, int(bm.sum())) >= 0.5:
                bid[bm] = top
        bid[m] = top
        rows.append(dict({k: v for k, v in s.items() if k not in ("mask", "edge")}, box=top))
    return rows


def bake(gkey: str, store: Path | str = DEFAULT_STORE, write: bool = True,
         path: Path | str | None = None) -> dict:
    """Classify one key's baked arrays and add the table to its npz.

    The shape table (`classify`) is rewritten by the baked line classes where the npz carries
    current ones (`read_lines`, `apply_lines`, with the fitted `shapes`); otherwise it stands,
    every box UNKNOWN, and `occ_lines` says why. Every other array is written back unchanged,
    through a temporary file and a rename, so a failed write leaves the old npz. `write=False`
    classifies and writes nothing; `path` reads and writes that npz instead of the store's (a
    staging copy). Returns `classify`'s info, with `apply_lines`' under `lines` and `occ_lines`.
    """
    p = Path(path) if path is not None else G.path(gkey, store)
    with np.load(p, allow_pickle=False) as z:
        arrays = {k: z[k].copy() for k in z.files}
    occ, box_id, info = classify(arrays["static"], arrays["labels"])
    cls, hints, occ_lines = read_lines(arrays)
    if cls is not None:
        occ, box_id, height, linfo = apply_lines(occ, box_id, cls, hints, shapes(arrays, cls > 0))
        info = dict(info, wall_px=linfo["wall_px"], box_px=linfo["box_px"], lines=linfo,
                    boxes=linfo["boxes"])
        boxes = linfo["boxes"]
    else:
        height = np.where(occ == BOX, H_UNKNOWN, H_NONE).astype(np.uint8)
        boxes = [{"id": b["id"], "px": b["px"], "height": "unknown", "hints": []} for b in info["boxes"]]
    info["occ_lines"] = occ_lines
    meta = json.loads(str(arrays["lines_meta"])) if "lines_meta" in arrays else {}
    info["occ_validation"] = ((meta.get("validation") or {}).get("status", "unrecorded")
                              if cls is not None else "no line classes")
    if write:
        arrays.update(occ=occ, box_id=box_id, box_height=height,
                      occ_boxes=np.array(json.dumps(boxes)), occ_lines=np.array(occ_lines),
                      occ_validation=np.array(info["occ_validation"]),
                      occ_version=np.array(OCCLUDER_VERSION), occ_built_by=np.array(occluder_stamp()))
        tmp = p.with_suffix(".tmp.npz")
        np.savez_compressed(tmp, **arrays)
        tmp.replace(p)
    return info


def render(static, labels, occ, zoom=3) -> np.ndarray:
    """The static beside it with walls cyan, boxes orange, and the art's box
    edges the table does not call a wall red."""
    ov = static.copy()
    ov[occ == WALL] = (255, 255, 0)
    ov[occ == BOX] = (0, 140, 255)
    ov[(labels == BOXEDGE) & (occ != WALL)] = (0, 0, 255)
    a = cv2.resize(static, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    b = cv2.resize(ov, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    return np.hstack([a, b])
