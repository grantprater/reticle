r"""Classify the baked static's drawn lines as walls or raised edges.

    .\.venv\Scripts\python.exe prototypes\raised_edges.py classify [--record]
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label

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
    os.environ[_k] = "4"

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
from reticle.minimap import PLANT, widget_scale  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

VERSION = "raised-edges-0.2.0"
SERIES = "raised_edges"
STORE = Path(DEFAULT_STORE)
OUT = STORE / "analysis" / "raised-edges-20260930"
KEYS = ("ascent__valorant-16x9-bigmap", "ascent__valorant-16x9")

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
SIDE_FLOOR, SIDE_VOID, SIDE_LINE = 1, 2, 3


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


def sides(cls: np.ndarray, line: np.ndarray, nx, ny, sc: float):
    """For each line pixel, what lies directly beyond the line on each side along the normal.

    Returns `(ys, xs, a, b, ya, xa, yb, xb)`: side classes and the first read pixel per side."""
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
                for j in range(1, READ_PX):
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


def classify(key: str) -> dict:
    g = load(key)
    static, labels = g["static"], g["labels"]
    sc = widget_scale(static.shape[1])
    bright, faint = occluders.lines(static, labels)       # the owner's line rule
    line = bright | faint
    cls = region_classes(static, labels, line)
    nx, ny = normals(line, sc)
    ys, xs, a, b, ya, xa, yb, xb = sides(cls, line, nx, ny, sc)
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
    return {"key": key, "scale": sc, "shape": list(line.shape), "counts": dict(counts), "pieces": pieces,
            "_line": line, "_bright": bright, "_sm": sm, "_raw": raw, "_pid": pid, "_static": static, "_cls": cls, "_kind": g["shade_kind"],
            "_shade": step, "_shade_differs": shade_differs, "_boxlike": boxlike,
            "_shade_fit": g["shade_fit"]}


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
    cv2.putText(band, f"{r['key']}  {VERSION}  red: wall (void directly beyond one side)   "
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
                     "shape": "loop" if kind == "loop" else "stroke",
                     "class_share": round(float(cnts.max() / cnts.sum()), 3),
                     "x": int(xx.min()), "y": int(yy.min()), "w": int(xx.max() - xx.min() + 1),
                     "h": int(yy.max() - yy.min() + 1),
                     "end_a": [int(pts[0][1]), int(pts[0][0])], "end_b": [int(pts[-1][1]), int(pts[-1][0])]})
        remap[k] = len(segs)
    r["segments"] = segs
    r["_sid"] = remap[sid]
    r["_skeleton"] = sk


def classify_keys() -> dict:
    res = {k: classify(k) for k in KEYS}
    big, small = res[KEYS[0]], res[KEYS[1]]
    T = fit_profiles(big, small)
    agree = profile_agreement(big, small, T)
    places = {KEYS[0]: place_classes(big), KEYS[1]: place_classes(small, T)}
    heavens = {}
    for k, r in res.items():
        heavens[k] = shade_heavens(r)
        annotate_pieces(r, heavens[k])
        segments(r)
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
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    got = classify_keys()
    summary = {"version": VERSION, "transform_331_to_465": got["T"], "profile_agreement": got["agree"],
               "keys": {}}
    for k, r in got["res"].items():
        pl = got["places"][k]
        hv = got["heavens"][k]
        summary["keys"][k] = {"counts": r["counts"], "places": pl, "pieces": r["pieces"],
                              "segments": r["segments"],
                              "shade_heavens": [{a: b for a, b in d.items() if a != "_mask"} for d in hv]}
        cv2.imwrite(str(OUT / f"sheet_{k}.png"), sheet(r, pl, hv))
        for d in hv:
            print("   H%d +%d px %d at (%d,%d) %dx%d ring rung %s ramp %.2f walls %d raised %d pieces %s" % (
                d["id"], d["rung"], d["px"], d["x"], d["y"], d["w"], d["h"], d["ring_rung"],
                d["ring_ramp_share"], d["ring_wall_px"], d["ring_raised_px"], d["raised_pieces"]))
        print(k, json.dumps(r["counts"]))
        for name, v in pl.items():
            print("  ", name, v["majority"], "expected", v["expected"], v["classes"],
                  "shade_differs", v["shade_differs_share"], "pieces", v["pieces"])
    print("331->465", got["T"], "agreement", got["agree"]["same_share"], "of", got["agree"]["matched_px"])
    (OUT / "classify.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
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
                           deps={"version": VERSION, "occluders": occluders.occluder_stamp(),
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
