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

Owns [owns:map-occluders].
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import cv2
import numpy as np

from . import geometry as G
from . import metrics
from .cone import OCC_BOX as BOX, OCC_OPEN as OPEN, OCC_WALL as WALL
from .minimap import BORDER, BOXEDGE, HOLE, PLANT, VOID, _odd, widget_scale
from .store import DEFAULT_STORE

OCC_NAMES = {OPEN: "open", WALL: "wall", BOX: "box"}

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


def bake(gkey: str, store: Path | str = DEFAULT_STORE, write: bool = True) -> dict:
    """Classify one key's baked arrays and add the table to its npz.

    Every other array is written back unchanged, through a temporary file and
    a rename, so a failed write leaves the old npz. `write=False` classifies
    and writes nothing. Returns `classify`'s info.
    """
    p = G.path(gkey, store)
    with np.load(p, allow_pickle=False) as z:
        arrays = {k: z[k].copy() for k in z.files}
    occ, box_id, info = classify(arrays["static"], arrays["labels"])
    if write:
        arrays.update(occ=occ, box_id=box_id, occ_built_by=np.array(occluder_stamp()))
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
