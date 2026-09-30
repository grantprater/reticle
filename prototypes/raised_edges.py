r"""Sort the baked static's drawn lines: wall, box, ramp or elevation line, other.

    .\.venv\Scripts\python.exe prototypes\raised_edges.py classify [--v2] [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py sorter [--v2] [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label --key lotus__valorant-16x9-bigmap

raised-edges-0.3.0 (this version; `--v2` or `classify(key, VERSION_V2)` reproduces 0.2.0). Each
rule is an invariant another map can falsify; the player's answers on a new key test them
(`label_raised_edges.py heldout`).

- Z. Every distance is in map-zoom px: px at the zoom of `ascent__valorant-16x9-bigmap` (`zoom`).
  No baked array stores the zoom, so it is `shade_fit`'s scale times the art's canvas side, from
  baked data only. Falsified if a structure of one world size (a box of one kind, a door) is drawn
  at a size that differs between keys by more than the zoom ratio; the art's own world scale is
  not modelled (Chamber's Trademark measures 13% larger on Split than on Ascent at one zoom).
- C. Floor and void colours are the key's own: the (V, S) cut that best separates its static on
  the art's terrain from its static on the art's VOID and HOLE (`colour_cuts`). Falsified if a
  key's cut passes more than 1% of its void or refuses more than 1% of its terrain.
- H. The art's HOLE beyond a line is void even where the static draws it floor grey: a line with a
  hole beyond it is a wall. Falsified by a line the player calls a ramp or box with art HOLE
  directly beyond it.
- D. A void region smaller than VOID_MIN_AREA that touches no image edge is a box's dark inside,
  not void. Falsified by a wall whose only void beyond is such a region.
- W. A line with void (large void or art HOLE) directly beyond one side or both is a wall, except a
  stroke at most BOX_ON_VOID_MAX long on a closed shape the owner's occluders fitted as a box
  (`occluders.classify`, drawn `outline` or `blob`). Falsified by a void-bounded line the player
  calls a ramp or other.
- B. A floor-bounded line is a box outline when it is short: a small closed loop, a small bent
  branch, a stroke at most BOX_SIDE_MAX long, a stroke at most BOX_CLOSED_MAX long on an occluder
  box, or a fragment no wider than SEG_SMALL_MAX_PX. Boxes are small; ramps and elevation lines
  run the length of the ramp. Falsified by a ramp line shorter than BOX_SIDE_MAX or a box side
  longer than BOX_CLOSED_MAX.
- R. Every other floor-bounded line is a ramp or elevation line [domain:minimap/raised-edge-lines].
  Heaven edges, overhang starts [domain:minimap/overhang-start-line] and thin interior walls
  with floor on both sides read here or as boxes; the sorter has no rule for them.
- G. A gap of unclaimed line pixels between two segment ends is one connector, a straight chord
  (bevel, or diagonal between axis strokes) or a circular arc, whichever fits the gap's pixels
  better; an arc needs a bulge of ARC_SAGITTA_MIN. What no connector claims becomes a fragment.
  Connectors take their neighbours' class where the two agree.

On the player's 221 Ascent segments 0.3.0 agrees on
[metric:raised-edge-sorter/segments-0.3.0@ascent__valorant-16x9-bigmap#agree=209] across the four
classes, with box recall
[metric:raised-edge-sorter/segments-0.3.0@ascent__valorant-16x9-bigmap#box_recall=0.9459] and ramp
precision
[metric:raised-edge-sorter/segments-0.3.0@ascent__valorant-16x9-bigmap#ramp_or_elevation_line_precision=0.7273];
0.2.0 agreed on 209 of 221 for wall against not wall only. The rules were tuned on Ascent; the
Lotus sample is held out (`notes/predictions.jsonl`, task line-sorter-0.3-lotus-20260930).

The rest of this docstring describes 0.1.0 and 0.2.0.

Reads baked geometry only. A drawn line with plain floor directly on its other side is a raised
edge, not a wall [domain:minimap/raised-edge-lines]: it bounds a ramp or an elevation change
that does not affect vision, light crosses it, and it carries no heaven meaning. A line with
void beyond it on one side is a wall [domain:minimap/white-lines-are-walls].

`classify` walks each line pixel's normal (structure tensor) past the line on both sides and
reads the static's own colour there; per-pixel classes are smoothed along the line and split
into pieces. On `ascent__valorant-16x9-bigmap` 7253 line px split 5606 wall, 1637 raised and 10
void on both sides (23 wall and 44 raised pieces); on `ascent__valorant-16x9` 3300 split 2534,
763 and 3. The two profiles agree on 0.947 of 3254 pixels matched through a fitted similarity
transform. The named places agree on the bigmap key: the strip under the self icon at e78e75b2d191
8.833 s and both A Link corridor indicators are raised, B Main's lines walls; the 331 px key
lacks the corridor indicators in its line mask.

Heaven candidates come from the shade rungs, not the lines (`shade_heavens`): 8-connected FLOOR
regions of one rung above the base, at least 150 px, higher than their surrounding ring. The
lines close no regions, so an edge-bounded heaven column was dropped. Shade is weak evidence of
a heaven, and the lines near those regions are not.

`classify` also draws both keys with classes, places and heaven candidates to
`<store>/analysis/raised-edges-20260930/`. `label_raised_edges.py` asks the player what each
segment is, unseeded, and scores the classifier against the answers.

Pieces and segments (0.2.0). A 0.1.0 piece is an 8-connected component of one class; it follows
the line network through junctions and corners, so walls round a room come out as one piece whose
box is the room, and the player could only answer unsure on them (23 of 67). `segments` thins the
line mask, cuts the skeleton at junctions (crossing number of at least 3), splits each branch where
its class changes and where a polyline fit turns, and keeps a small closed outline whole. On the
465 px key that gives 234 wall and raised segments. The 0.1.0 pieces stay, because the player's
0.1.0 answers are keyed to them. Scored against those answers, the wall / raised split agreed on
10 of 21 pieces the player called wall or ramp, and 17 of the 18 box outlines the player named
read raised: the floor-beyond rule reads a box's outline and many interior walls as raised edges.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "4")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import geometry, metrics, occluders  # noqa: E402
from reticle.minimap import HOLE, PLANT, VOID, widget_scale  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "raised-edges-0.3.0"
VERSION_V2 = "raised-edges-0.2.0"
SERIES = "raised_edges"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "raised-edges-20260930"
KEYS = ("ascent__valorant-16x9-bigmap", "ascent__valorant-16x9")
LOTUS_KEY = "lotus__valorant-16x9-bigmap"

#: A non-line pixel darker than this (static V) is void, whatever the art says: the static is the
#: widget's own pixel-exact drawing, and the art's warp loses thin gaps.
VOID_V_MAX = 95
FLOOR_S_MAX = 30
#: Steps along the normal (scale 1.0): the line is 1-3 px wide, so this clears it and reads what
#: lies directly beyond.
WALK_PX = 5.0
#: What is read beyond the line: this many pixels past its last line pixel.
READ_PX = 2
#: The structure tensor's smoothing, px at scale 1.0.
TENSOR_SIGMA = 1.2
#: Per-pixel classes are smoothed by majority over this window (scale 1.0) along the line.
SMOOTH_PX = 5
#: A piece shorter than this (px at scale 1.0) is not offered as a candidate.
MIN_PIECE_PX = 6

WALL, RAISED, VOIDSEP, JUNCTION = 1, 2, 3, 4
CLASS_NAMES = {WALL: "wall", RAISED: "raised_edge", VOIDSEP: "void_both", JUNCTION: "unread"}
SIDE_FLOOR, SIDE_VOID, SIDE_LINE, SIDE_DARK = 1, 2, 3, 4


def load(key: str) -> dict:
    with np.load(geometry.path(key, STORE)) as z:
        return {k: z[k].copy() for k in ("static", "labels", "occ", "box_id", "shade_step", "shade_kind", "shade_fit")}


def region_classes(static: np.ndarray, labels: np.ndarray, line: np.ndarray) -> np.ndarray:
    """Per pixel: SIDE_LINE on a drawn line, SIDE_FLOOR on grey floor or site paint, SIDE_VOID elsewhere.

    Read from the static's own colour, not the art's labels: the art's warp puts VOID on floor
    pixels beside a line. Measured on both Ascent keys, the art's FLOOR has saturation 0 and V
    116-151 (p1-p99); its VOID has median saturation 68-71 (the brown scenery behind the widget)
    and its HOLE V 35-130; the site paint (`labels == PLANT`) is saturated and is floor."""
    hsv = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    floor = ((s <= FLOOR_S_MAX) & (v > VOID_V_MAX)) | (labels == PLANT)
    out = np.full(labels.shape, SIDE_VOID, np.uint8)
    out[floor] = SIDE_FLOOR
    out[line] = SIDE_LINE
    return out


# --- 0.3.0: map-zoom units and per-key colour cuts ----------------------------------------------

#: The key whose map zoom is 1.0: the 465 px Ascent key every 0.2.0 constant was set on.
ZOOM_REF_KEY = "ascent__valorant-16x9-bigmap"
#: The canvas side the art is normalised to (`map_shade`: every fitted scale, normalised to a
#: 2048 px art canvas, is one per-profile constant).
ART_CANVAS = 2048
#: `shade_kind` codes, as `prototypes/map_shade.py` writes them (terrain: floor, ramp, shadow).
KIND_TERRAIN = (1, 2, 3)
#: The art classes read as terrain and void for the colour cuts are eroded this far (map-zoom px)
#: and kept this far from any line, so a cut is not set on antialiased edge pixels.
CUT_ERODE_PX, CUT_LINE_CLEAR_PX = 2, 2
#: A void region beyond a line smaller than this (map-zoom px^2) is a box's dark inside, not void.
VOID_MIN_AREA = 40


def zoom(key: str) -> dict:
    """The map's zoom in widget px per art-canvas px, relative to ZOOM_REF_KEY, from baked data only.

    No geometry field stores the map's zoom, and the store holds no world-to-minimap transform. The
    baked `shade_fit` scale is widget px per art px, and the art ships at 1024 or 2048 px per canvas
    side, so `shade_fit[1] * art_side / ART_CANVAS` is widget px per normalised canvas px: the map
    scaling slider times the widget size, per `(map, profile)`. The art's own world scale (metres
    per canvas px) is not in any baked array, so a per-map factor stays unmodelled: Chamber's
    Trademark, one world distance, measures 30.7 px at widget scale 1 on Split against 27.2 on
    Ascent (both 331 px keys) [domain:abilities/chamber-trademark-minimap-white-area], while this
    zoom puts the two keys 0.6% apart."""
    def canvas_scale(k: str) -> tuple[float, int, str]:
        with np.load(geometry.path(k, STORE)) as z:
            fit, name = z["shade_fit"], str(z["shade_map"])
        art = cv2.imread(str(STORE / "reference" / "maps" / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        side = int(max(art.shape[:2]))
        return float(fit[1]) * side / ART_CANVAS, side, name
    s, side, name = canvas_scale(key)
    s0, _, _ = canvas_scale(ZOOM_REF_KEY)
    with np.load(geometry.path(key, STORE)) as z:
        w = z["static"].shape[1]
    return {"zoom": round(s / s0, 4), "canvas_scale": round(s, 5), "ref_canvas_scale": round(s0, 5),
            "art_side": side, "map": name, "widget_scale": widget_scale(w),
            "source": "baked shade_fit[1] x art canvas side / 2048, relative to " + ZOOM_REF_KEY}


def colour_cuts(g: dict, line: np.ndarray) -> dict:
    """The key's floor / void colour cuts, from its own baked arrays: the static's V and S on the
    art's terrain (`shade_kind` floor, ramp, shadow) against the art's VOID and HOLE, both eroded
    and clear of lines. The cut pair (V above, S at most) minimises the balanced error; among
    equal errors the pair nearest the middle of the tied block is taken."""
    static, labels, kind = g["static"], g["labels"], g["shade_kind"]
    sc = widget_scale(static.shape[1])
    hsv = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)
    S, V = hsv[:, :, 1].astype(np.int16), hsv[:, :, 2].astype(np.int16)
    k3 = np.ones((3, 3), np.uint8)
    near = cv2.dilate(line.astype(np.uint8), k3, iterations=max(1, int(round(CUT_LINE_CLEAR_PX * sc)))) > 0
    it = max(1, int(round(CUT_ERODE_PX * sc)))
    terr = cv2.erode(np.isin(kind, KIND_TERRAIN).astype(np.uint8), k3, iterations=it).astype(bool) & ~near
    void = cv2.erode(np.isin(labels, (VOID, HOLE)).astype(np.uint8), k3, iterations=it).astype(bool) & ~near
    # 2-D histograms, then the balanced error of every (v, s) cut from cumulative sums
    ht = np.histogram2d(V[terr], S[terr], bins=256, range=[[0, 256], [0, 256]])[0]
    hv = np.histogram2d(V[void], S[void], bins=256, range=[[0, 256], [0, 256]])[0]
    # floor(v, s) = V > v and S <= s: pass counts from a reversed-V, forward-S cumulative sum
    ct = np.cumsum(np.cumsum(ht[::-1], 0), 1)[::-1]
    cv_ = np.cumsum(np.cumsum(hv[::-1], 0), 1)[::-1]
    # ct[v, s] counts V >= v and S <= s; the cut "V > v" is row v + 1
    pt = np.vstack([ct[1:], np.zeros((1, 256))]) / max(1, terr.sum())
    pv = np.vstack([cv_[1:], np.zeros((1, 256))]) / max(1, void.sum())
    err = 0.5 * ((1 - pt) + pv)
    e0 = err.min()
    vv, ss = np.nonzero(err <= e0 + 1e-9)
    vi, si = int(np.rint(np.median(vv))), int(np.rint(np.median(ss)))
    return {"void_v_max": vi, "floor_s_max": si, "balanced_error": round(float(e0), 4),
            "terrain_px": int(terr.sum()), "void_px": int(void.sum()),
            "terrain_pass": round(float(pt[vi, si]), 4), "void_pass": round(float(pv[vi, si]), 4),
            "tied_v": [int(vv.min()), int(vv.max())], "tied_s": [int(ss.min()), int(ss.max())]}


def region_classes_v3(static: np.ndarray, labels: np.ndarray, line: np.ndarray, cuts: dict,
                      zm: float) -> np.ndarray:
    """0.3.0 side classes. Floor is the key's own colour cut (`colour_cuts`) or site paint; the art's
    HOLE is void even where the static draws it floor grey; a void region smaller than
    VOID_MIN_AREA map-zoom px^2 that touches no image edge is SIDE_DARK, a box's dark inside."""
    hsv = cv2.cvtColor(static, cv2.COLOR_BGR2HSV)
    s, v = hsv[:, :, 1], hsv[:, :, 2]
    floor = (((s <= cuts["floor_s_max"]) & (v > cuts["void_v_max"])) | (labels == PLANT)) & (labels != HOLE)
    out = np.full(labels.shape, SIDE_VOID, np.uint8)
    out[floor] = SIDE_FLOOR
    out[line] = SIDE_LINE
    n, lab, st, _ = cv2.connectedComponentsWithStats((out == SIDE_VOID).astype(np.uint8), 8)
    edge = set(np.unique(np.r_[lab[0], lab[-1], lab[:, 0], lab[:, -1]]).tolist())
    small = np.array([i != 0 and i not in edge and st[i, 4] < VOID_MIN_AREA * zm * zm for i in range(n)])
    out[small[lab] & (out == SIDE_VOID)] = SIDE_DARK
    return out


def normals(line: np.ndarray, sc: float) -> tuple[np.ndarray, np.ndarray]:
    """Unit normal (nx, ny) across the line at each pixel, from the blurred mask's structure tensor."""
    f = cv2.GaussianBlur(line.astype(np.float32), (0, 0), TENSOR_SIGMA * sc)
    gx = cv2.Sobel(f, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(f, cv2.CV_32F, 0, 1, ksize=3)
    s = 1.5 * sc
    jxx = cv2.GaussianBlur(gx * gx, (0, 0), s)
    jxy = cv2.GaussianBlur(gx * gy, (0, 0), s)
    jyy = cv2.GaussianBlur(gy * gy, (0, 0), s)
    th = 0.5 * np.arctan2(2 * jxy, jxx - jyy)          # the major eigenvector: across the line
    return np.cos(th), np.sin(th)


def sides(cls: np.ndarray, line: np.ndarray, nx, ny, sc: float, read_px: int = READ_PX):
    """For each line pixel, what lies directly beyond the line on each side along the normal.

    Returns `(ys, xs, a, b, ya, xa, yb, xb)`: side classes and the first read pixel per side."""
    READ = read_px
    h, w = cls.shape
    ys, xs = np.nonzero(line)
    n = len(ys)
    res = []
    kmax = int(np.ceil(WALK_PX * sc)) + 1
    for sgn in (1.0, -1.0):
        side = np.full(n, SIDE_LINE, np.uint8)
        py = np.full(n, -1, np.int32)
        px = np.full(n, -1, np.int32)
        done = np.zeros(n, bool)
        dx, dy = sgn * nx[ys, xs], sgn * ny[ys, xs]
        for k in range(1, kmax + 1):
            x = np.rint(xs + dx * k).astype(int)
            y = np.rint(ys + dy * k).astype(int)
            out = (x < 0) | (y < 0) | (x >= w) | (y >= h)
            c = np.full(n, SIDE_VOID, np.uint8)
            ok = ~out
            c[ok] = cls[y[ok], x[ok]]
            hit = ~done & (c != SIDE_LINE)
            if hit.any():
                # read READ_PX pixels: void wins if any of them is void (a thin gap is a gap)
                cc = c[hit].copy()
                for j in range(1, READ):
                    x2 = np.rint(xs[hit] + dx[hit] * (k + j)).astype(int)
                    y2 = np.rint(ys[hit] + dy[hit] * (k + j)).astype(int)
                    o2 = (x2 < 0) | (y2 < 0) | (x2 >= w) | (y2 >= h)
                    c2 = np.full(len(x2), SIDE_VOID, np.uint8)
                    c2[~o2] = cls[y2[~o2], x2[~o2]]
                    cc = np.where(c2 == SIDE_VOID, SIDE_VOID, cc)
                side[hit] = cc
                py[hit] = np.clip(y[hit], 0, h - 1)
                px[hit] = np.clip(x[hit], 0, w - 1)
                done |= hit
        res.append((side, py, px))
    (a, ya, xa), (b, yb, xb) = res
    return ys, xs, a, b, ya, xa, yb, xb


def pixel_class(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    c = np.full(len(a), JUNCTION, np.uint8)
    fa, fb = a == SIDE_FLOOR, b == SIDE_FLOOR
    va, vb = a == SIDE_VOID, b == SIDE_VOID
    c[(fa & vb) | (va & fb)] = WALL
    c[fa & fb] = RAISED
    c[va & vb] = VOIDSEP
    return c


def smooth(cmap: np.ndarray, line: np.ndarray, sc: float) -> np.ndarray:
    """Majority class over line pixels in a SMOOTH_PX window; unread pixels take their neighbours'."""
    k = int(max(3, round(SMOOTH_PX * sc)) // 2 * 2 + 1)
    votes = []
    for c in (WALL, RAISED, VOIDSEP):
        votes.append(cv2.boxFilter(((cmap == c) & line).astype(np.float32), -1, (k, k), normalize=False))
    votes = np.stack(votes)
    best = np.array([WALL, RAISED, VOIDSEP], np.uint8)[np.argmax(votes, 0)]
    out = np.zeros_like(cmap)
    has = votes.max(0) > 0
    out[line & has] = best[line & has]
    out[line & ~has] = JUNCTION
    return out


def classify(key: str, version: str = VERSION) -> dict:
    """Per-pixel side classes and 0.1.0 pieces. `version` VERSION_V2 reproduces 0.2.0 exactly:
    widget-scaled distances, the fixed colour cuts, no HOLE or void-size rule."""
    g = load(key)
    static, labels = g["static"], g["labels"]
    bright, faint = occluders.lines(static, labels)       # the owner's line rule
    line = bright | faint
    if version == VERSION_V2:
        sc = widget_scale(static.shape[1])
        zm, cuts = None, {"void_v_max": VOID_V_MAX, "floor_s_max": FLOOR_S_MAX}
        cls = region_classes(static, labels, line)
        read_px = READ_PX
    else:
        zm = zoom(key)
        sc = zm["zoom"]
        cuts = colour_cuts(g, line)
        cls = region_classes_v3(static, labels, line, cuts, sc)
        read_px = max(1, int(round(READ_PX * sc)))
    nx, ny = normals(line, sc)
    ys, xs, a, b, ya, xa, yb, xb = sides(cls, line, nx, ny, sc, read_px)
    side_a = np.zeros(line.shape, np.uint8)
    side_b = np.zeros(line.shape, np.uint8)
    side_a[ys, xs], side_b[ys, xs] = a, b
    # a small dark region beyond a line is a box's dark inside, not void: floor for the wall test
    a = np.where(a == SIDE_DARK, SIDE_FLOOR, a)
    b = np.where(b == SIDE_DARK, SIDE_FLOOR, b)
    raw = np.zeros(line.shape, np.uint8)
    raw[ys, xs] = pixel_class(a, b)
    sm = smooth(raw, line, sc)
    # shade rungs either side, per pixel, where both sides are floor
    step = g["shade_step"].astype(np.int16)
    sa = np.where(ya >= 0, step[np.clip(ya, 0, None), np.clip(xa, 0, None)], -99)
    sb = np.where(yb >= 0, step[np.clip(yb, 0, None), np.clip(xb, 0, None)], -99)
    both_floor = (a == SIDE_FLOOR) & (b == SIDE_FLOOR)
    shade_differs = np.zeros(line.shape, bool)
    shade_differs[ys, xs] = (sa != sb) & both_floor
    # the far region's size: a small enclosed floor region beyond a line is box-like
    n_r, reg, rst, _ = cv2.connectedComponentsWithStats((~line).astype(np.uint8), 4)
    edge_ids = set(np.unique(np.r_[reg[0], reg[-1], reg[:, 0], reg[:, -1]]).tolist())
    amax = occluders.BOX_MAX_AREA * sc * sc
    small = np.array([(i not in edge_ids) and rst[i, 4] <= amax for i in range(n_r)])
    ra = np.where(ya >= 0, reg[np.clip(ya, 0, None), np.clip(xa, 0, None)], 0)
    rb = np.where(yb >= 0, reg[np.clip(yb, 0, None), np.clip(xb, 0, None)], 0)
    boxlike = np.zeros(line.shape, bool)
    boxlike[ys, xs] = both_floor & (small[ra] | small[rb])
    # pieces: 8-connected runs of one smoothed class
    pieces = []
    pid = np.zeros(line.shape, np.int32)
    min_px = MIN_PIECE_PX * sc
    for c in (WALL, RAISED, VOIDSEP):
        n, lab, st, cen = cv2.connectedComponentsWithStats(((sm == c) & line).astype(np.uint8), 8)
        for i in range(1, n):
            m = lab == i
            npx = int(st[i, 4])
            if npx < min_px:
                continue
            nr = max(1, int((raw[m] == RAISED).sum()))
            pieces.append({"id": len(pieces) + 1, "cls": CLASS_NAMES[c], "px": npx,
                           "x": int(st[i, 0]), "y": int(st[i, 1]), "w": int(st[i, 2]), "h": int(st[i, 3]),
                           "cx": round(float(cen[i, 0]), 1), "cy": round(float(cen[i, 1]), 1),
                           "bright_share": round(float(bright[m].mean()), 3),
                           "occ_wall_share": round(float((g["occ"][m] == 1).mean()), 3),
                           "occ_box_share": round(float((g["occ"][m] == 2).mean()), 3),
                           "shade_differs_share": round(float(shade_differs[m].sum()) / nr, 3),
                           "boxlike_share": round(float(boxlike[m].sum()) / nr, 3)})
            pid[m] = len(pieces)
    counts = Counter()
    for c in (WALL, RAISED, VOIDSEP, JUNCTION):
        counts[CLASS_NAMES[c] + "_px"] = int(((sm == c) & line).sum())
    counts["line_px"] = int(line.sum())
    for p in pieces:
        counts[p["cls"] + "_pieces"] += 1
        if p["cls"] == "raised_edge":
            counts["raised_shade_differs_pieces"] += int(p["shade_differs_share"] > 0.5)
            counts["raised_boxlike_pieces"] += int(p["boxlike_share"] > 0.5)
    return {"key": key, "version": version, "scale": sc, "zoom": zm, "cuts": cuts, "shape": list(line.shape),
            "counts": dict(counts), "pieces": pieces,
            "_line": line, "_bright": bright, "_sm": sm, "_raw": raw, "_pid": pid, "_static": static, "_cls": cls, "_kind": g["shade_kind"],
            "_shade": step, "_shade_differs": shade_differs, "_boxlike": boxlike,
            "_shade_fit": g["shade_fit"], "_side_a": side_a, "_side_b": side_b, "_labels": labels,
            "_occ": g["occ"]}


COL = {WALL: (60, 60, 255), RAISED: (255, 200, 0), VOIDSEP: (200, 0, 200), JUNCTION: (0, 200, 255)}


#: The places the player named (2026-09-30), as boxes (x0, y0, x1, y1) on the scale-1.0 key
#: `ascent__valorant-16x9-bigmap`, placed by reading e78e75b2d191's stored self position and the
#: light-diagnosis sheets: the line under the self at 8.833 s (self at 232, 104) where light
#: crossed into the strip below; the two inner lines of the corridor the self faces up at
#: 38.183 s (self at 332, 192), which is where this file places the A Link door corridor (the
#: door frame is the notch at y 150-157; the player has not confirmed the placement); and the
#: two lines, a void gap between them, that part B site from B Main.
PLACES = {
    "8833_under_self": (203, 105, 233, 111),
    "38183_alink_corridor_left": (322, 171, 327, 191),
    "38183_alink_corridor_right": (338, 171, 342, 191),
    "b_main_vs_b_site": (107, 192, 160, 202),
}
#: The places' expected class under the player's rule, as told (the 38.183 s corridor lines are
#: the A Link indicators, which show raised parts).
PLACE_EXPECT = {"8833_under_self": "raised_edge", "38183_alink_corridor_left": "raised_edge",
                "38183_alink_corridor_right": "raised_edge", "b_main_vs_b_site": "wall"}


def fit_profiles(big: dict, small: dict) -> dict:
    """Scale and shift taking the 331 px key's pixels onto the 465 px key's, fitted on the two
    line masks (both baked): the best overlap of the small key's lines, scaled, with the big key's
    lines dilated by one pixel."""
    D = cv2.distanceTransform((~big["_line"]).astype(np.uint8), cv2.DIST_L2, 3)
    D = np.minimum(D, 6.0)
    ys, xs = np.nonzero(small["_line"])

    def cost(s, dx, dy):
        X = np.rint(xs * s + dx).astype(int)
        Y = np.rint(ys * s + dy).astype(int)
        ok = (X >= 0) & (Y >= 0) & (X < D.shape[1]) & (Y < D.shape[0])
        return float(np.r_[D[Y[ok], X[ok]], np.full(int((~ok).sum()), 6.0)].mean())

    # Start from the two keys' own art fits (`shade_fit`: rot, scale, dx, dy): both draw the same
    # art, so art -> big composed with small -> art is the prior; the two keys draw the map at
    # different zooms (map scaling), not at the widget sizes' ratio.
    fb, fs = big["_shade_fit"], small["_shade_fit"]
    s0 = float(fb[1] / fs[1])
    dx0, dy0 = float(fb[2] - s0 * fs[2]), float(fb[3] - s0 * fs[3])
    best = (cost(s0, dx0, dy0), (s0, dx0, dy0))
    prior = {"s": round(s0, 4), "dx": round(dx0, 2), "dy": round(dy0, 2), "chamfer_px": round(best[0], 3)}
    for s in np.arange(s0 - 0.01, s0 + 0.0101, 0.001):
        for dx in np.arange(dx0 - 3, dx0 + 3.01, 0.25):
            for dy in np.arange(dy0 - 3, dy0 + 3.01, 0.25):
                c = cost(s, dx, dy)
                if c < best[0]:
                    best = (c, (float(s), float(dx), float(dy)))
    s, dx, dy = best[1]
    X = np.rint(xs * s + dx).astype(int)
    Y = np.rint(ys * s + dy).astype(int)
    ok = (X >= 0) & (Y >= 0) & (X < D.shape[1]) & (Y < D.shape[0])
    return {"s": round(s, 4), "dx": round(dx, 2), "dy": round(dy, 2), "chamfer_px": round(best[0], 3),
            "within_1px_share": round(float((D[Y[ok], X[ok]] <= 1.0).mean()), 4), "prior": prior}


def profile_agreement(big: dict, small: dict, T: dict) -> dict:
    """Class agreement per small-key line pixel whose mapped position lands on a big-key line pixel
    (within 1 px): the share with the same class."""
    ys, xs = np.nonzero(small["_line"])
    X = np.rint(xs * T["s"] + T["dx"]).astype(int)
    Y = np.rint(ys * T["s"] + T["dy"]).astype(int)
    h, w = big["_line"].shape
    same = n = 0
    conf = Counter()
    for x, y, cs in zip(X, Y, small["_sm"][ys, xs]):
        if not (1 <= x < w - 1 and 1 <= y < h - 1):
            continue
        win = big["_sm"][y - 1:y + 2, x - 1:x + 2][big["_line"][y - 1:y + 2, x - 1:x + 2]]
        if win.size == 0:
            continue
        cb = Counter(win.tolist()).most_common(1)[0][0]
        n += 1
        same += int(cb == cs)
        conf[f"{CLASS_NAMES.get(int(cs))}->{CLASS_NAMES.get(int(cb))}"] += 1
    return {"matched_px": n, "same_share": round(same / max(1, n), 4), "confusion": dict(conf)}


def place_classes(r: dict, T: dict | None = None) -> dict:
    """Per named place: line pixels in its box by smoothed class (the box mapped onto the 331 px key
    through the inverse of T), the majority, and the shade-rung disagreement across it."""
    out = {}
    for name, (x0, y0, x1, y1) in PLACES.items():
        if T is not None:
            x0, x1 = [int(np.floor((v - T["dx"]) / T["s"])) for v in (x0, x1)]
            y0, y1 = [int(np.floor((v - T["dy"]) / T["s"])) for v in (y0, y1)]
            x1, y1 = x1 + 1, y1 + 1
        m = np.zeros(r["_line"].shape, bool)
        m[y0:y1 + 1, x0:x1 + 1] = True
        m &= r["_line"]
        c = Counter(CLASS_NAMES[int(v)] for v in r["_sm"][m])
        # a place holding fewer line pixels than a piece's floor has no line the owner's rule draws
        maj = c.most_common(1)[0][0] if m.sum() >= MIN_PIECE_PX * r["scale"] else "not_in_line_mask"
        raised = m & (r["_raw"] == RAISED)
        out[name] = {"box": [x0, y0, x1, y1], "px": int(m.sum()), "classes": dict(c), "majority": maj,
                     "expected": PLACE_EXPECT[name], "agrees": maj == PLACE_EXPECT[name],
                     "shade_differs_share": round(float(r["_shade_differs"][raised].mean()), 3)
                     if raised.any() else None,
                     "pieces": sorted({int(v) for v in r["_pid"][m] if v})}
    return out


#: A shade region smaller than this (px at scale 1.0) is not listed as a candidate heaven: the
#: +2 rung's box-top squares are smaller.
REGION_MIN_PX = 150
#: The ring read outside a region: pixels this far (scale 1.0) beyond it.
RING_PX = 4
#: `shade_kind` codes, as `prototypes/map_shade.py` writes them.
KIND_FLOOR, KIND_RAMP = 1, 2


def shade_heavens(r: dict) -> list[dict]:
    """Candidate heavens from the baked shade rungs, not from the lines: every 8-connected region
    of one terrain rung (`shade_kind` FLOOR, `shade_step` >= 1) of at least REGION_MIN_PX whose
    surrounding ring of terrain sits on a lower rung. Shading usually marks an actual heaven, while
    a raised-edge line marks a ramp or elevation change that does not affect vision (the player,
    2026-09-30), so lines are only reported as touching a region, never used to make one.

    The first version built candidates from floor regions the lines close off. The lines mostly
    close none: on the 465 px key two regions besides the main floor exceed 600 px, and extending
    every raised-edge piece by up to 12 px along its own direction closed no more. The player's
    ramp answer then removed the premise."""
    sc = r["scale"]
    kind, step = r["_kind"], r["_shade"]
    k3 = np.ones((3, 3), np.uint8)
    out = []
    for s in sorted(int(v) for v in np.unique(step[kind == KIND_FLOOR]) if v >= 1):
        m_s = (kind == KIND_FLOOR) & (step == s)
        n, lab, st, cen = cv2.connectedComponentsWithStats(m_s.astype(np.uint8), 8)
        for i in range(1, n):
            if st[i, 4] < REGION_MIN_PX * sc * sc:
                continue
            m = lab == i
            ring = cv2.dilate(m.astype(np.uint8), k3, iterations=max(1, int(round(RING_PX * sc)))).astype(bool) & ~m
            terr = ring & np.isin(kind, (KIND_FLOOR, KIND_RAMP))
            below = float(np.median(step[terr])) if terr.any() else None
            lines = ring & r["_line"]
            out.append({"rung": s, "px": int(st[i, 4]), "x": int(st[i, 0]), "y": int(st[i, 1]),
                        "w": int(st[i, 2]), "h": int(st[i, 3]),
                        "cx": round(float(cen[i, 0]), 1), "cy": round(float(cen[i, 1]), 1),
                        "ring_rung": below, "above_ring": below is not None and s > below,
                        "ring_ramp_share": round(float((ring & (kind == KIND_RAMP)).sum()) / max(1, int(ring.sum())), 3),
                        "ring_wall_px": int((lines & (r["_sm"] == WALL)).sum()),
                        "ring_raised_px": int((lines & (r["_sm"] == RAISED)).sum()),
                        "raised_pieces": sorted({int(v) for v in r["_pid"][lines & (r["_sm"] == RAISED)] if v}),
                        "_mask": m})
    out = [d for d in out if d["above_ring"]]
    out.sort(key=lambda d: (-d["rung"], -d["px"]))
    for j, d in enumerate(out, 1):
        d["id"] = j
    return out


def overlay(r: dict, zoom: int = 3, ids: bool = False) -> np.ndarray:
    st = r["_static"]
    img = cv2.resize(st, None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
    img = (img * 0.55).astype(np.uint8)
    for c, col in COL.items():
        m = (r["_sm"] == c) & r["_line"]
        mz = cv2.resize(m.astype(np.uint8), None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST) > 0
        img[mz] = col
    if ids:
        for p in r["pieces"]:
            x, y = int(p["cx"] * zoom), int(p["cy"] * zoom)
            cv2.putText(img, str(p["id"]), (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 0, 0), 3)
            cv2.putText(img, str(p["id"]), (x + 3, y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (255, 255, 255), 1)
    return img


def sheet(r: dict, places: dict, heavens: list[dict] = (), zoom: int = 3) -> np.ndarray:
    """Every candidate line of one key, coloured wall (red) or raised edge (blue-cyan), with piece
    ids, the named places boxed in green and the shade-heaven candidates outlined in yellow."""
    img = overlay(r, zoom, ids=True)
    for d in heavens:
        mz = cv2.resize(d["_mask"].astype(np.uint8), None, fx=zoom, fy=zoom, interpolation=cv2.INTER_NEAREST)
        cs, _ = cv2.findContours(mz, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(img, cs, -1, (0, 230, 255), 1)
        cv2.putText(img, f"H{d['id']} +{d['rung']}", (int(d["cx"] * zoom) - 12, int(d["cy"] * zoom) + 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 230, 255), 1)
    for name, pl in places.items():
        x0, y0, x1, y1 = pl["box"]
        cv2.rectangle(img, (x0 * zoom - 2, y0 * zoom - 2), ((x1 + 1) * zoom + 1, (y1 + 1) * zoom + 1),
                      (0, 220, 0), 1)
        cv2.putText(img, name, (x0 * zoom, (y1 + 1) * zoom + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.38,
                    (0, 220, 0), 1)
    band = np.full((64, img.shape[1], 3), 255, np.uint8)
    c = r["counts"]
    cv2.putText(band, f"{r['key']}  {r['version']}  red: wall (void directly beyond one side)   "
                f"cyan: raised edge (floor directly beyond both sides)   magenta: void both sides",
                (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
    cv2.putText(band, f"line px {c['line_px']}: wall {c.get('wall_px', 0)}, raised {c.get('raised_edge_px', 0)}"
                f", void both {c.get('void_both_px', 0)}   pieces: wall {c.get('wall_pieces', 0)}, raised "
                f"{c.get('raised_edge_pieces', 0)}   green: the player's named places   yellow: shade-rung heaven "
                f"candidates (H id +rung)",
                (6, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1)
    return np.vstack([band, img])


def annotate_pieces(r: dict, heavens: list[dict], items: str = "pieces", ids: str = "_pid") -> None:
    """Per piece (or per segment, with items="segments", ids="_sid"): the share of its pixels with
    RAMP terrain (`shade_kind`) within RING_PX, and the shade-heaven candidates it touches. Neither
    is shown to the player."""
    k3 = np.ones((3, 3), np.uint8)
    it = max(1, int(round(RING_PX * r["scale"])))
    ramp_near = cv2.dilate((r["_kind"] == KIND_RAMP).astype(np.uint8), k3, iterations=it).astype(bool)
    hv = np.zeros(r["_line"].shape, np.int32)
    for d in heavens:
        hv[cv2.dilate(d["_mask"].astype(np.uint8), k3, iterations=it).astype(bool) & (hv == 0)] = d["id"]
    for p in r[items]:
        m = r[ids] == p["id"]
        p["ramp_near_share"] = round(float(ramp_near[m].mean()), 3)
        p["heavens"] = sorted({int(v) for v in hv[m] if v})


# --- segments (raised-edges-0.2.0) -------------------------------------------------------------
# The 0.1.0 pieces were 8-connected components of one smoothed class. A component follows the line
# network through every junction and corner, so walls that meet round a room come out as one piece
# whose bounding box is the room: on the 465 px key one wall piece spans 370 x 306 px. The player,
# asked about the line in such a box, could only answer unsure. A segment instead is one maximal
# run of skeleton between junctions, cut where its smoothed class changes and where a polyline fit
# turns a corner, so each segment is one straight (or gently curved) stroke of one class.

#: The polyline fit's tolerance, px at scale 1.0: a run bends into a new segment past this.
SEG_EPS_PX = 1.5
#: A class run shorter than this (px at scale 1.0, along the skeleton) joins its neighbour.
SEG_CLASS_MIN_PX = 4
#: A line pixel belongs to the nearest skeleton segment within this distance (px at scale 1.0).
SEG_ATTACH_PX = 3.0
#: A closed junction-free loop no wider than this (px at scale 1.0) is one segment, not split at
#: its corners: a small box's outline is one object, and its 4-6 px sides fall under MIN_PIECE_PX.
SEG_LOOP_MAX_PX = 24
#: 0.3.0: a bent junction-bounded branch no wider than this (map-zoom px) is kept whole (`small`).
SEG_SMALL_MAX_PX = 13


def thin(mask: np.ndarray) -> np.ndarray:
    """Zhang-Suen thinning of a binary mask to an 8-connected one-pixel skeleton."""
    img = np.pad(mask.astype(np.uint8), 1)
    while True:
        changed = False
        for step in (0, 1):
            p = img
            n = [np.roll(np.roll(p, dy, 0), dx, 1) for dy, dx in
                 ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))]
            # P2..P9 clockwise from north: roll by +1 in y brings the pixel above down
            P2, P3, P4, P5, P6, P7, P8, P9 = n
            B = sum(n)
            seq = [P2, P3, P4, P5, P6, P7, P8, P9, P2]
            A = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            if step == 0:
                c = (P2 * P4 * P6 == 0) & (P4 * P6 * P8 == 0)
            else:
                c = (P2 * P4 * P8 == 0) & (P2 * P6 * P8 == 0)
            kill = (p == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if kill.any():
                img = np.where(kill, 0, img).astype(np.uint8)
                changed = True
        if not changed:
            break
    return img[1:-1, 1:-1].astype(bool)


_N8 = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def _order(pix: set, sk_deg: dict) -> list[list[tuple[int, int]]]:
    """Order one junction-free branch's pixels into walks; a loop is opened at its first pixel."""
    left = set(pix)
    walks = []
    while left:
        ends = [q for q in left if sum((q[0] + dy, q[1] + dx) in left for dy, dx in _N8) <= 1]
        cur = min(ends) if ends else min(left)
        walk = [cur]
        left.discard(cur)
        while True:
            nb = [(cur[0] + dy, cur[1] + dx) for dy, dx in _N8 if (cur[0] + dy, cur[1] + dx) in left]
            if not nb:
                break
            # prefer the 4-neighbour, so a staircase is walked in order
            nb.sort(key=lambda q: abs(q[0] - cur[0]) + abs(q[1] - cur[1]))
            cur = nb[0]
            walk.append(cur)
            left.discard(cur)
        walks.append(walk)
    return walks


def segments(r: dict) -> None:
    """Split the line network into segments (see the section note) and set r["segments"] and
    r["_sid"] (segment id per line pixel, 0 where no segment claims it)."""
    sc, line, sm = r["scale"], r["_line"], r["_sm"]
    sk = thin(line)
    h, w = sk.shape
    # a junction is where three or more strokes meet: the crossing number (0-to-1 transitions round
    # the 8-neighbourhood) is at least 3. The neighbour count is not used, since it reads 3 at
    # every corner of an 8-connected stroke and cut each box outline into 5 px sides
    pad = np.pad(sk.astype(np.uint8), 1)
    ring = [np.roll(np.roll(pad, dy, 0), dx, 1) for dy, dx in
            ((1, 0), (1, -1), (0, -1), (-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1))]
    cross = sum(((ring[i] == 0) & (ring[(i + 1) % 8] == 1)).astype(np.uint8) for i in range(8))
    junction = sk & (cross[1:-1, 1:-1] >= 3)
    # a junction is a cluster: its pixels and their 8-neighbours on the skeleton cut the branches
    jz = cv2.dilate(junction.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & sk
    branches = sk & ~jz
    n, lab = cv2.connectedComponents(branches.astype(np.uint8), connectivity=8)
    eps = SEG_EPS_PX * sc
    cmin = max(2, int(round(SEG_CLASS_MIN_PX * sc)))
    runs = []                                   # (ordered pixels, class)
    for i in range(1, n):
        ys, xs = np.nonzero(lab == i)
        for walk in _order(set(zip(ys.tolist(), xs.tolist())), {}):
            wy, wx = [q[0] for q in walk], [q[1] for q in walk]
            closed = (len(walk) >= 8 and abs(walk[0][0] - walk[-1][0]) <= 1
                      and abs(walk[0][1] - walk[-1][1]) <= 1)
            if closed and max(max(wy) - min(wy), max(wx) - min(wx)) + 1 <= SEG_LOOP_MAX_PX * sc:
                runs.append((walk, "loop"))     # a small closed outline is one object: keep it whole
                continue
            ext = max(max(wy) - min(wy), max(wx) - min(wx)) + 1
            if (r.get("version") != VERSION_V2 and len(walk) >= MIN_PIECE_PX * sc
                    and ext <= SEG_SMALL_MAX_PX * sc and len(walk) > ext + 1):
                # 0.3.0: a small bent branch (a box's U or L against a wall) is one object; its
                # corners would cut it into sides shorter than MIN_PIECE_PX, which were dropped
                runs.append((walk, "small"))
                continue
            cl = [int(sm[y, x]) for y, x in walk]
            # class runs, short runs absorbed by the previous run (or the next, at the start)
            parts = []
            for k, c in enumerate(cl):
                if parts and parts[-1][1] == c:
                    parts[-1][0].append(k)
                else:
                    parts.append([[k], c])
            merged = []
            for idx, c in parts:
                if merged and (len(idx) < cmin or merged[-1][1] == c):
                    merged[-1][0].extend(idx)
                else:
                    merged.append([idx, c])
            if len(merged) > 1 and len(merged[0][0]) < cmin:
                merged[1][0][:0] = merged[0][0]
                merged.pop(0)
            for idx, _ in merged:
                pts = [walk[k] for k in idx]
                if len(pts) < 2:
                    runs.append((pts, None))
                    continue
                cnt = np.array([[x, y] for y, x in pts], np.int32).reshape(-1, 1, 2)
                ap = cv2.approxPolyDP(cnt, eps, False).reshape(-1, 2)
                # the vertices' indices along the walk; each consecutive pair bounds one stroke
                vi = [0]
                j = 0
                for vx, vy in ap[1:]:
                    while j < len(pts) - 1 and (pts[j][1], pts[j][0]) != (int(vx), int(vy)):
                        j += 1
                    vi.append(j)
                vi[-1] = len(pts) - 1
                for a, b in zip(vi[:-1], vi[1:]):
                    if b > a:
                        runs.append((pts[a:b + 1], None))
    # attach every line pixel to the nearest run's skeleton pixel within SEG_ATTACH_PX
    seed = np.zeros((h, w), np.int32)
    for k, (pts, _) in enumerate(runs, 1):
        for y, x in pts:
            seed[y, x] = k
    src = (seed == 0).astype(np.uint8)
    dist, lab2 = cv2.distanceTransformWithLabels(src, cv2.DIST_L2, 5, labelType=cv2.DIST_LABEL_PIXEL)
    # lab2 numbers the zero pixels of src; map each label to its seed's run id
    zy, zx = np.nonzero(src == 0)
    lut = np.zeros(lab2.max() + 1, np.int32)
    lut[lab2[zy, zx]] = seed[zy, zx]
    sid = np.where(line & (dist <= SEG_ATTACH_PX * sc), lut[lab2], 0).astype(np.int32)
    segs = []
    remap = np.zeros(len(runs) + 1, np.int32)
    min_px = MIN_PIECE_PX * sc
    for k, (pts, kind) in enumerate(runs, 1):
        m = sid == k
        npx = int(m.sum())
        if len(pts) < min_px or npx == 0:
            continue
        cls_px = sm[m]
        vals, cnts = np.unique(cls_px[cls_px != JUNCTION], return_counts=True)
        if len(vals) == 0:
            continue
        c = int(vals[np.argmax(cnts)])
        yy, xx = np.nonzero(m)
        segs.append({"id": len(segs) + 1, "cls": CLASS_NAMES[c], "px": npx, "skeleton_px": len(pts),
                     "shape": kind if kind in ("loop", "small") else "stroke",
                     "class_share": round(float(cnts.max() / cnts.sum()), 3),
                     "x": int(xx.min()), "y": int(yy.min()), "w": int(xx.max() - xx.min() + 1),
                     "h": int(yy.max() - yy.min() + 1),
                     "end_a": [int(pts[0][1]), int(pts[0][0])], "end_b": [int(pts[-1][1]), int(pts[-1][0])]})
        remap[k] = len(segs)
    r["segments"] = segs
    r["_sid"] = remap[sid]
    r["_skeleton"] = sk


# --- the 0.3.0 sorter: wall, box, ramp_or_elevation_line, other ------------------------------------

SORT_CLASSES = ("wall", "box", "ramp_or_elevation_line", "other")
#: The player's segment classes, as the sorter's classes: heaven edges, other marks and other lines
#: have no class of their own in the sorter.
PLAYER_TO_SORT = {"wall": "wall", "box_outline": "box", "ramp_or_elevation_line": "ramp_or_elevation_line",
                  "heaven_edge": "other", "other_mark": "other", "other": "other"}
#: A floor-bounded stroke this short or shorter (skeleton px, map-zoom units) is a box's side.
BOX_SIDE_MAX = 13
#: ...and a stroke up to this long is a box's side when it lies on a closed shape the owner's
#: occluders fitted as a box (`outline` or `blob`) along at least BOX_CLOSED_SHARE of its pixels.
BOX_CLOSED_MAX = 30
BOX_CLOSED_SHARE = 0.5
#: A void-bounded stroke this short or shorter on such a closed box is the box's side, not a wall.
BOX_ON_VOID_MAX = 9


def closed_boxes(r: dict) -> np.ndarray:
    """Pixels within one pixel of a box the owner fitted as a closed shape (`occluders.classify`,
    drawn `outline` or `blob`, not the `faint` catch-all), from the key's baked arrays."""
    _, _, info = occluders.classify(r["_static"], r["_labels"])
    m = np.zeros(r["_line"].shape, bool)
    # box_id keeps only BOX pixels and a bright side of a box is WALL, so a closed box is taken as
    # its line pixels within one pixel of its fitted bounding box (the enclosed region's for an
    # outline, the whole component's for a blob)
    h0, w0 = m.shape
    for b in info["boxes"]:
        if b["drawn"] in ("outline", "blob"):
            y0, y1 = max(0, b["y"] - 1), min(h0, b["y"] + b["h"] + 1)
            x0, x1 = max(0, b["x"] - 1), min(w0, b["x"] + b["w"] + 1)
            m[y0:y1, x0:x1] |= r["_line"][y0:y1, x0:x1]
    return m


def sort_segment(r3: dict, m: np.ndarray, skeleton_px: int, shape: str, closed: np.ndarray) -> dict:
    """One segment's 0.3.0 class from its pixels `m` in the 0.3.0 per-pixel reading `r3`.

    1. wall: most pixels have void (large void or art HOLE) directly beyond one side or both,
       unless the stroke is at most BOX_ON_VOID_MAX long and lies on a closed box shape;
    2. other: no pixel read on either side;
    3. box: floor on both sides and a small closed loop or small bent branch, a stroke at most
       BOX_SIDE_MAX long, a stroke at most BOX_CLOSED_MAX long on a closed box shape, or a
       fragment no wider than SEG_SMALL_MAX_PX;
    4. ramp_or_elevation_line: every other floor-bounded stroke."""
    zm = r3["scale"]
    sm = r3["_sm"][m]
    vals, cnts = np.unique(sm[sm != JUNCTION], return_counts=True)
    maj = int(vals[np.argmax(cnts)]) if len(vals) else JUNCTION
    length = skeleton_px / zm
    closed_share = float(closed[m].mean()) if m.any() else 0.0
    dark_share = float(((r3["_side_a"][m] == SIDE_DARK) | (r3["_side_b"][m] == SIDE_DARK)).mean()) if m.any() else 0.0
    yy, xx = np.nonzero(m)
    extent = (max(xx.max() - xx.min(), yy.max() - yy.min()) + 1) / zm if len(yy) else 0.0
    feats = {"majority": CLASS_NAMES[maj], "length": round(length, 1), "extent": round(float(extent), 1),
             "closed_share": round(closed_share, 3),
             "dark_share": round(dark_share, 3), "bright_share": round(float(r3["_bright"][m].mean()), 3)}
    on_box = closed_share >= BOX_CLOSED_SHARE
    if maj in (WALL, VOIDSEP):
        c = "box" if (on_box and length <= BOX_ON_VOID_MAX) else "wall"
    elif maj == JUNCTION:
        c = "other"
    elif (shape in ("loop", "small") or length <= BOX_SIDE_MAX or (on_box and length <= BOX_CLOSED_MAX)
          or (shape == "fragment" and extent <= SEG_SMALL_MAX_PX)):
        c = "box"
    else:
        c = "ramp_or_elevation_line"
    return dict(feats, cls3=c)


def sort_params() -> dict:
    """Every 0.3.0 parameter, for a metric's provenance (distances in map-zoom px)."""
    return {"walk_px": WALK_PX, "read_px": READ_PX, "tensor_sigma": TENSOR_SIGMA, "smooth_px": SMOOTH_PX,
            "min_piece_px": MIN_PIECE_PX, "seg_eps_px": SEG_EPS_PX, "seg_class_min_px": SEG_CLASS_MIN_PX,
            "seg_attach_px": SEG_ATTACH_PX, "seg_loop_max_px": SEG_LOOP_MAX_PX, "seg_small_max_px": SEG_SMALL_MAX_PX,
            "void_min_area": VOID_MIN_AREA, "cut_erode_px": CUT_ERODE_PX, "cut_line_clear_px": CUT_LINE_CLEAR_PX,
            "box_side_max": BOX_SIDE_MAX, "box_closed_max": BOX_CLOSED_MAX, "box_closed_share": BOX_CLOSED_SHARE,
            "box_on_void_max": BOX_ON_VOID_MAX, "gap_max_px": GAP_MAX_PX, "gap_reach_px": GAP_REACH_PX,
            "arc_sagitta_min": ARC_SAGITTA_MIN, "frag_min_px": FRAG_MIN_PX, "zoom_ref_key": ZOOM_REF_KEY}


def sort_all(r3: dict) -> None:
    """Set `cls3` and the sorter's features on every segment of a 0.3.0 reading, then fit the
    connectors across the gaps and class them."""
    closed = closed_boxes(r3)
    for s in r3["segments"]:
        s.update(sort_segment(r3, r3["_sid"] == s["id"], s["skeleton_px"], s["shape"], closed))
    connectors(r3, closed)


# --- connectors: bevels, diagonals and arcs across the gaps (0.3.0) -------------------------------
# Segments leave the line pixels round a junction or a tight bend unclaimed: a circular box came out
# as two or three arcs with 3-4 px between them. A connector joins the two nearest ends of distinct
# segments across such a gap with the shape that fits the gap's pixels best: a straight chord (a
# bevel, or a diagonal when both neighbours are axis strokes) or a circular arc.

#: An unclaimed cluster larger than this (px, map-zoom units) is not a gap.
GAP_MAX_PX = 16
#: A segment end within this distance (map-zoom px) of the cluster bounds the gap.
GAP_REACH_PX = 2.5
#: An arc is chosen over the chord when the gap bulges at least this far (map-zoom px) off the
#: chord and the arc's residual is lower.
ARC_SAGITTA_MIN = 1.0
#: The rest a connector leaves becomes a fragment segment when it holds at least this many px.
FRAG_MIN_PX = 4


def _circle(pts: np.ndarray) -> tuple[float, float, float]:
    """Least-squares circle (Kasa) through points (x, y): centre and radius."""
    x, y = pts[:, 0], pts[:, 1]
    A = np.c_[2 * x, 2 * y, np.ones(len(x))]
    sol, *_ = np.linalg.lstsq(A, x * x + y * y, rcond=None)
    cx, cy = sol[0], sol[1]
    return float(cx), float(cy), float(np.sqrt(max(0.0, sol[2] + cx * cx + cy * cy)))


def _seg_dist(p: np.ndarray, a: np.ndarray, b: np.ndarray) -> np.ndarray:
    ab = b - a
    t = np.clip(((p - a) @ ab) / max(1e-9, ab @ ab), 0, 1)
    return np.hypot(*(p - (a + t[:, None] * ab)).T)


def connectors(r: dict, closed: np.ndarray | None = None) -> list[dict]:
    """Fit a connector across every small gap of unclaimed line pixels that two segment ends
    bound; each becomes a segment of shape `bevel`, `diagonal` or `arc`, joined to both
    neighbours, and takes their class where they agree (else its own `sort_segment` class).
    Sets r["connectors"] and r["gap_px"] (unclaimed line px before and after)."""
    zm = r["scale"]
    sid, line = r["_sid"], r["_line"]
    un = line & (sid == 0)
    before = int(un.sum())
    ends = []                                     # (x, y, segment index)
    for i, s in enumerate(r["segments"]):
        if s["shape"] in ("stroke", "small"):
            ends.append((s["end_a"][0], s["end_a"][1], i))
            ends.append((s["end_b"][0], s["end_b"][1], i))
    E = np.array([(x, y) for x, y, _ in ends], float) if ends else np.zeros((0, 2))
    n, lab, st, _ = cv2.connectedComponentsWithStats(un.astype(np.uint8), 8)
    out = []
    for j in range(1, n):
        if st[j, 4] > GAP_MAX_PX * zm:
            continue
        yy, xx = np.nonzero(lab == j)
        P = np.c_[xx, yy].astype(float)
        if not len(E):
            break
        d = np.min(np.hypot(E[:, None, 0] - P[None, :, 0], E[:, None, 1] - P[None, :, 1]), 1)
        near = [k for k in np.argsort(d) if d[k] <= GAP_REACH_PX * zm]
        pair = None
        for k in near:
            for k2 in near:
                if ends[k2][2] != ends[k][2]:
                    pair = (k, k2)
                    break
            if pair:
                break
        if pair is None:
            continue
        a, b = E[pair[0]], E[pair[1]]
        chord_res = float(_seg_dist(P, a, b).mean())
        sag = float(_seg_dist(P, a, b).max())
        shape, radius, res = "bevel", None, chord_res
        if sag >= ARC_SAGITTA_MIN * zm and len(P) >= 2:
            cx, cy, R = _circle(np.vstack([P, a, b]))
            arc_res = float(np.abs(np.hypot(*(np.vstack([P, a, b]) - (cx, cy)).T) - R).mean())
            if arc_res < chord_res and R <= 4 * max(1.0, float(np.hypot(*(b - a)))):
                shape, radius, res = "arc", round(R, 2), arc_res
        s1, s2 = r["segments"][ends[pair[0]][2]], r["segments"][ends[pair[1]][2]]
        if shape == "bevel":
            def axis(s):
                return s["w"] <= 2 or s["h"] <= 2
            if axis(s1) and axis(s2) and abs(b[0] - a[0]) >= 1 and abs(b[1] - a[1]) >= 1:
                shape = "diagonal"
        m = lab == j
        c3 = s1.get("cls3") if s1.get("cls3") == s2.get("cls3") else None
        if c3 is None and closed is not None and "cls3" in s1:
            c3 = sort_segment(r, m, len(P), "stroke", closed)["cls3"]
        seg = {"id": len(r["segments"]) + 1, "cls": s1["cls"] if s1["cls"] == s2["cls"] else "mixed",
               "px": int(m.sum()), "skeleton_px": int(m.sum()), "shape": shape,
               "x": int(xx.min()), "y": int(yy.min()), "w": int(xx.max() - xx.min() + 1),
               "h": int(yy.max() - yy.min() + 1), "end_a": [int(a[0]), int(a[1])], "end_b": [int(b[0]), int(b[1])],
               "joins": [s1["id"], s2["id"]], "fit_resid": round(res, 3), "radius": radius,
               "chord_resid": round(chord_res, 3), "sagitta": round(sag, 2), "connector": True}
        if c3 is not None:
            seg["cls3"] = c3
        r["segments"].append(seg)
        sid[m] = seg["id"]
        out.append(seg)
    after = int((line & (sid == 0)).sum())
    # what no segment or connector claims: each 8-connected rest of at least FRAG_MIN_PX becomes a
    # `fragment` (a small box's sides between junctions, cut shorter than MIN_PIECE_PX)
    frags = []
    n, lab, st, _ = cv2.connectedComponentsWithStats((line & (sid == 0)).astype(np.uint8), 8)
    for j in range(1, n):
        if st[j, 4] < FRAG_MIN_PX * zm:
            continue
        m = lab == j
        yy, xx = np.nonzero(m)
        skel = int((r["_skeleton"] & m).sum()) or int(m.sum())
        seg = {"id": len(r["segments"]) + 1, "cls": "fragment", "px": int(m.sum()), "skeleton_px": skel,
               "shape": "fragment", "x": int(xx.min()), "y": int(yy.min()), "w": int(xx.max() - xx.min() + 1),
               "h": int(yy.max() - yy.min() + 1), "end_a": [int(xx[0]), int(yy[0])],
               "end_b": [int(xx[-1]), int(yy[-1])], "fragment": True}
        if closed is not None:
            seg.update(sort_segment(r, m, skel, "fragment", closed))
        r["segments"].append(seg)
        sid[m] = seg["id"]
        frags.append(seg)
    r["connectors"] = out
    r["fragments"] = frags
    r["gap_px"] = {"unclaimed_before": before, "unclaimed_after_connectors": after,
                   "unclaimed_after_fragments": int((line & (sid == 0)).sum()),
                   "connectors": len(out), "by_shape": dict(Counter(c["shape"] for c in out)),
                   "fragments": len(frags)}
    return out


def classify_keys(version: str = VERSION) -> dict:
    res = {k: classify(k, version) for k in KEYS}
    big, small = res[KEYS[0]], res[KEYS[1]]
    T = fit_profiles(big, small)
    agree = profile_agreement(big, small, T)
    places = {KEYS[0]: place_classes(big), KEYS[1]: place_classes(small, T)}
    heavens = {}
    for k, r in res.items():
        heavens[k] = shade_heavens(r)
        annotate_pieces(r, heavens[k])
        segments(r)
        if version != VERSION_V2:
            sort_all(r)
            for c in SORT_CLASSES:
                r["counts"][f"{c}_sorted"] = sum(int(p.get("cls3") == c) for p in r["segments"]
                                                 if not p.get("connector"))
        annotate_pieces(r, heavens[k], "segments", "_sid")
        for c in ("wall", "raised_edge", "void_both"):
            r["counts"][f"{c}_segments"] = sum(int(p["cls"] == c) for p in r["segments"])
        for c in ("wall", "raised_edge"):
            ps = [p for p in r["pieces"] if p["cls"] == c]
            r["counts"][f"{c}_ramp_near_pieces"] = sum(int(p["ramp_near_share"] > 0.5) for p in ps)
            r["counts"][f"{c}_heaven_touch_pieces"] = sum(int(bool(p["heavens"])) for p in ps)
        r["counts"]["shade_heavens"] = len(heavens[k])
    return {"res": res, "T": T, "agree": agree, "places": places, "heavens": heavens}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["classify"])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--v2", action="store_true", help="reproduce raised-edges-0.2.0")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    version = VERSION_V2 if a.v2 else VERSION
    got = classify_keys(version)
    summary = {"version": version, "transform_331_to_465": got["T"], "profile_agreement": got["agree"],
               "keys": {}}
    for k, r in got["res"].items():
        pl = got["places"][k]
        hv = got["heavens"][k]
        summary["keys"][k] = {"counts": r["counts"], "places": pl, "pieces": r["pieces"],
                              "segments": r["segments"],
                              "shade_heavens": [{a: b for a, b in d.items() if a != "_mask"} for d in hv]}
        cv2.imwrite(str(OUT / (f"sheet_{k}.png" if a.v2 else f"sheet_{k}_{version}.png")), sheet(r, pl, hv))
        for d in hv:
            print("   H%d +%d px %d at (%d,%d) %dx%d ring rung %s ramp %.2f walls %d raised %d pieces %s" % (
                d["id"], d["rung"], d["px"], d["x"], d["y"], d["w"], d["h"], d["ring_rung"],
                d["ring_ramp_share"], d["ring_wall_px"], d["ring_raised_px"], d["raised_pieces"]))
        print(k, json.dumps(r["counts"]))
        for name, v in pl.items():
            print("  ", name, v["majority"], "expected", v["expected"], v["classes"],
                  "shade_differs", v["shade_differs_share"], "pieces", v["pieces"])
    print("331->465", got["T"], "agreement", got["agree"]["same_share"], "of", got["agree"]["matched_px"])
    (OUT / ("classify.json" if a.v2 else f"classify_{version}.json")).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    if a.record and not a.v2:
        raise SystemExit("--record writes the 0.2.0 classify series only; score 0.3.0 with label_raised_edges.py sorter")
    if a.record:
        for k, r in got["res"].items():
            c = r["counts"]
            pl = got["places"][k]
            n_r = max(1, c.get("raised_edge_pieces", 0))
            vals = {"line_px": c["line_px"], "wall_px": c.get("wall_px", 0),
                    "raised_px": c.get("raised_edge_px", 0), "void_both_px": c.get("void_both_px", 0),
                    "raised_share": round(c.get("raised_edge_px", 0) / c["line_px"], 4),
                    "wall_share": round(c.get("wall_px", 0) / c["line_px"], 4),
                    "wall_pieces": c.get("wall_pieces", 0), "raised_pieces": c.get("raised_edge_pieces", 0),
                    "raised_shade_differs_pieces": c.get("raised_shade_differs_pieces", 0),
                    "raised_shade_differs_share": round(c.get("raised_shade_differs_pieces", 0) / n_r, 4),
                    "raised_boxlike_pieces": c.get("raised_boxlike_pieces", 0),
                    "places_agree": sum(int(v["agrees"]) for v in pl.values()), "places_n": len(pl),
                    "raised_ramp_near_pieces": c.get("raised_edge_ramp_near_pieces", 0),
                    "wall_ramp_near_pieces": c.get("wall_ramp_near_pieces", 0),
                    "raised_heaven_touch_pieces": c.get("raised_edge_heaven_touch_pieces", 0),
                    "wall_heaven_touch_pieces": c.get("wall_heaven_touch_pieces", 0),
                    "shade_heavens": c.get("shade_heavens", 0),
                    "wall_segments": c.get("wall_segments", 0),
                    "raised_segments": c.get("raised_edge_segments", 0),
                    "segment_claimed_share": round(float((r["_sid"] > 0).sum()) / c["line_px"], 4)}
            if k == KEYS[1]:
                vals.update(profile_same_share=got["agree"]["same_share"],
                            profile_matched_px=got["agree"]["matched_px"])
            metrics.record(SERIES, part="classify", session=k, values=vals,
                           deps={"version": VERSION_V2, "occluders": occluders.occluder_stamp(),
                                 "void_v_max": VOID_V_MAX, "floor_s_max": FLOOR_S_MAX, "walk_px": WALK_PX,
                                 "read_px": READ_PX, "smooth_px": SMOOTH_PX, "min_piece_px": MIN_PIECE_PX,
                                 "seg_eps_px": SEG_EPS_PX, "seg_class_min_px": SEG_CLASS_MIN_PX,
                                 "seg_attach_px": SEG_ATTACH_PX, "seg_loop_max_px": SEG_LOOP_MAX_PX},
                           context={"places": {n: v["box"] for n, v in pl.items()},
                                    "transform_331_to_465": got["T"]},
                           note="baked geometry only; no session pixels")
        print("recorded")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
