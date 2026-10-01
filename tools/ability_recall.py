r"""Recall of unnamed ability entities, scored against the player's exhaustive labels.

    .\.venv\Scripts\python.exe tools\ability_recall.py --select
    .\.venv\Scripts\python.exe tools\ability_recall.py [--out DIR] [--record]
    .\.venv\Scripts\python.exe tools\ability_recall.py --groups 137,170 [--out DIR]
    .\.venv\Scripts\python.exe tools\ability_recall.py --review --out DIR

Stage 4 of `docs/ABILITY_DETECTION.md` (sections 10 and 11, pass 1).

**Select** (`--select`) fixes the frames before any ability pass runs. For
each session of `SESSIONS` it builds the shape reader exactly as `reticle
scan SID --only ability --from cache` builds it, clips its spans to the
minimap crop cache's rounds (`roi_cache.choose_source`) and takes the pass's
own 2 Hz grid (`passes.cache_feed`). A sample is live where `gametime` puts
it in a live phase (`ability_scan.LIVE_PHASES`), the reader's own test.
Every CADENCE-th live sample, from the first, is a frame. It reads the
cache's index and the stored rounds only: nothing is decoded and no pixel is
read, so the choice cannot rest on what the pass will find. The list goes to
the store's `labels/ability_recall_20260930/selection/<sid>.json`.

**Score** (the default) reads the player's answers from
`labels/ability_recall_20260930/<sid>.jsonl` (the last row for a time wins;
`prototypes/label_ability_recall.py` writes them) and the stored
`ability_icon`, `ability_fit`, `ability_wall` and `ability_shape_scan`
streams. Per widget size it prints:

- *Entity recall.* Each frame's marks are grouped first (`frame_entities`),
  by the player's convention: a ring is its centre icon, when there is one,
  and two or more kind-2 points on its perimeter; an area is many kind-4
  points filling it; a line or beam is kind-3 points along one smooth curve
  (a broken wall stays one [domain:abilities/sage-barrier-orb-segments]);
  an icon with no ring is its own entity. The
  instances are then linked across frames (`entities`): on consecutive
  selected frames of one round when `same_entity` holds (centre icons within
  LINK_PX, one circle, one curve, touching areas), or by the same free-text
  name in one round. Every threshold is in px at the 465 px widget, scaled.
  An entity is found when a proposal explains any of its marks. The
  one-sided 95% Clopper-Pearson lower bound goes beside it (`cp_lower`).
  Until stage 5 builds tracks, a proposal on a labelled frame stands for
  the track that would cover it. `--groups` prints and draws the grouping
  without reading a stream.
- *Frame recall.* The share of entity instances (an entity on one frame)
  that a proposal on the same frame explains; the share of marks goes
  beside it, though an area's many fill points weigh it.
- *Specificity.* Proposals on a labelled frame that explain no mark, per
  frame, by proposal type, over every labelled frame and over the frames the
  player answered "nothing here".
- *Misses* as surprise rows (`misses.jsonl` in `--out`): each unexplained
  target mark, with the stream's reason at that time and the nearest
  proposal.

What counts. Smokes stay out of the recall target and keep their own lane
(section 17, answer 4), and so do marks of kind `unsure`; both still explain
proposals, so a proposer's hit on a smoke is not charged to specificity. A
frame the player answered unsure is out of every count. A proposal is an
icon candidate of `ability_icon` (every stored candidate: the proposer's
output is the candidate set the tracker will read), a candidate's ring or
beam (`ability_fit`) or wall or curve (`ability_wall`) the owner found, or a
ring or beam of the surprise path (`ability_shape_scan`) the owner accepted
(`--all-shapes` adds the rejected ones and lone wall pieces). A hit is
counted by type and path (`ring/candidate`, `ring/surprise`). Explaining
(`explains`): an icon explains a mark within its radius plus TOL_PX of its
centre; a ring, a mark within TOL_PX or a quarter of its radius of its
centre, or within TOL_PX of its rim; a beam or wall, a mark within TOL_PX of
its segment; a curve, a mark within TOL_PX of its fitted polyline. The
player marks an icon, ring or area at its centre and a line anywhere along
it. The surprise rate (gated samples where no ring or beam candidate was
accepted) comes from the `ability_fit` head.

Not for. Naming (pass 2), tracks (stage 5), or smokes (`tools/smoke_identity.py`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

TOOL = "ability-recall-0.3.0"
SET = "ability_recall_20260930"
#: Every CADENCE-th live 2 Hz sample is a frame (section 10, fixed in advance).
CADENCE = 20
#: The chosen sessions per widget size, in blocks: label block 1 whole, then
#: block 2 whole if block 1 holds fewer than MIN_ENTITIES entities; stop at
#: the end of a block, never at a count (section 10).
SESSIONS = {
    331: (("043bafca271a", 1), ("59c70f1ef720", 2)),
    465: (("c62c2b06bcfb", 1), ("587c15b07779", 2)),
}
MIN_ENTITIES = 60
#: Mark kinds the player can give; the recall target leaves out NOT_TARGET.
KINDS = ("icon", "ring", "line", "area", "smoke", "unsure")
NOT_TARGET = ("smoke", "unsure")
#: Explaining tolerance, px of the crop.
TOL_PX = 3.0
#: Instances this close (px at 465, scaled) on consecutive frames of a round
#: are one entity (`same_entity`).
LINK_PX = 6.0
ALPHA = 0.05
#: Grouping one frame's marks (`frame_entities`), from the player's
#: convention and the widget's scale, never from the recall they give. Every
#: px value is at the 465 px widget, scaled by widget / WIDGET_REF.
WIDGET_REF = 465.0
#: A kind-2 mark this close to an icon is a ring marked at its centre (the
#: player's first frames), and belongs to that icon.
RING_CENTRE_PX = 4.0
#: Perimeter points belong to one icon when their distances from it agree
#: within 2 TOL_PX + RING_REL x radius: each click lands within TOL_PX of a
#: rim drawn 2-3 px wide, and the icon need not sit exactly at the centre.
RING_REL = 0.1
#: An icon-free circle takes points within TOL_PX + CIRCLE_REL x radius of
#: its fitted rim, needs CIRCLE_MIN of them (any three points lie on some
#: circle, so only a fourth is evidence), and is at most half the widget.
CIRCLE_REL = 0.05
CIRCLE_MIN = 4
#: Ring points left over form one centreless ring per cluster at this gap:
#: two points of one ring lie within its diameter, at most the widget's half.
RING_PAIR_PX = WIDGET_REF / 2.0
#: Kind-3 points along one curve: a step of at most a fifth of the widget
#: (the player marks a long beam with two far points) and a turn of at most
#: LINE_TURN_DEG between steps (a smooth curve, not a corner).
LINE_GAP_PX = 0.2 * WIDGET_REF
LINE_TURN_DEG = 60.0
#: Kind-4 points filling one area: single linkage at a tenth of the widget,
#: about twice the fill spacing the player used.
AREA_GAP_PX = 0.1 * WIDGET_REF


def below_normal() -> None:
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.SetPriorityClass(k.GetCurrentProcess(), 0x4000)
    else:
        os.nice(10)


def set_dir(store: Path) -> Path:
    return store / "labels" / SET


# --- statistics -----------------------------------------------------------------

def _binom_sf(k: int, n: int, p: float) -> float:
    """P(X >= k) for X ~ Binomial(n, p)."""
    if k <= 0:
        return 1.0
    if p <= 0.0:
        return 0.0
    if p >= 1.0:
        return 1.0
    lp, lq = math.log(p), math.log1p(-p)
    return min(1.0, sum(math.exp(math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
                                 + i * lp + (n - i) * lq) for i in range(k, n + 1)))


def cp_lower(k: int, n: int, alpha: float = ALPHA) -> float | None:
    """The one-sided (1 - alpha) Clopper-Pearson lower bound on a rate from
    k of n: the p at which P(X >= k) = alpha. None for n = 0."""
    if n <= 0:
        return None
    if k <= 0:
        return 0.0
    lo, hi = 0.0, 1.0
    for _ in range(80):
        mid = (lo + hi) / 2.0
        if _binom_sf(k, n, mid) < alpha:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


# --- labels ---------------------------------------------------------------------

def load_answers(path: Path) -> dict[float, dict]:
    """The answer per frame time; the last row for a time wins."""
    out: dict[float, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[float(r["t_ms"])] = r
    return out


def _fit_circle(pts: list[tuple[float, float]]) -> tuple[float, float, float] | None:
    """The least-squares (Kasa) circle through three or more points, or None
    when they are collinear."""
    import numpy as np
    a = np.array([[x, y, 1.0] for x, y in pts])
    b = np.array([-(x * x + y * y) for x, y in pts])
    sol, *_ = np.linalg.lstsq(a, b, rcond=None)
    cx, cy = -sol[0] / 2.0, -sol[1] / 2.0
    r2 = cx * cx + cy * cy - sol[2]
    if not np.isfinite(r2) or r2 <= 0:
        return None
    return float(cx), float(cy), float(math.sqrt(r2))


def _icon_group(icon: dict, pts: list[dict], scale: float) -> list[int]:
    """The ring points that belong to `icon`: those within RING_CENTRE_PX of
    it (a ring marked at its centre), and the largest set whose distances
    from it agree within 2 TOL_PX + RING_REL x radius (two or more)."""
    near = [i for i, p in enumerate(pts)
            if math.hypot(p["x"] - icon["x"], p["y"] - icon["y"]) <= RING_CENTRE_PX * scale]
    rest = sorted((math.hypot(p["x"] - icon["x"], p["y"] - icon["y"]), i)
                  for i, p in enumerate(pts) if i not in near)
    best: list[int] = []
    for a in range(len(rest)):
        grp = [i for d, i in rest[a:] if d - rest[a][0] <= 2 * TOL_PX + RING_REL * rest[a][0]]
        if len(grp) >= 2 and len(grp) > len(best):
            best = grp
    return near + best


def _circle_group(pts: list[dict], scale: float) -> tuple[list[int], tuple] | None:
    """The icon-free circle through the most ring points, seeded from every
    triple and refitted through its inliers, with radius at most half the
    widget; among equal counts, the smallest residual relative to the
    radius wins (two rings' points can share a loose circle)."""
    from itertools import combinations
    best = None
    for tri in combinations(range(len(pts)), 3):
        c = _fit_circle([(pts[i]["x"], pts[i]["y"]) for i in tri])
        if c is None or c[2] > WIDGET_REF / 2.0 * scale:
            continue
        inl = [i for i, p in enumerate(pts)
               if abs(math.hypot(p["x"] - c[0], p["y"] - c[1]) - c[2]) <= TOL_PX + CIRCLE_REL * c[2]]
        fit = _fit_circle([(pts[i]["x"], pts[i]["y"]) for i in inl]) or c
        res = max(abs(math.hypot(pts[i]["x"] - fit[0], pts[i]["y"] - fit[1]) - fit[2])
                  for i in inl) / fit[2]
        if best is None or (len(inl), -res) > (len(best[0]), -best[2]):
            best = (inl, fit, res)
    return None if best is None else (best[0], best[1])


def _rings(icons: list[dict], pts: list[dict], scale: float) -> tuple[list[dict], list[dict]]:
    """One frame's rings: (ring instances, icons left alone).

    Greedily, the group of most marks first: an icon with the ring points
    that lie on a circle about it (the icon counts as a mark), or an
    icon-free circle through CIRCLE_MIN or more points; a tie goes to the
    icon. Ring points left over form one
    centreless ring per RING_PAIR_PX cluster, since the player marks a ring
    with at least two points on its perimeter."""
    icons, pts = list(icons), list(pts)
    out = []
    while pts:
        cand = []
        for k, ic in enumerate(icons):
            g = _icon_group(ic, pts, scale)
            if g:
                cand.append((len(g) + 1, 1, "icon", k, g, None))
        cg = _circle_group(pts, scale)
        if cg is not None and len(cg[0]) >= CIRCLE_MIN:
            cand.append((len(cg[0]), 0, "circle", None, cg[0], cg[1]))
        if not cand:
            break
        n, _pri, how, k, g, circ = max(cand, key=lambda c: (c[0], c[1]))
        members = [pts[i] for i in g]
        if how == "icon":
            ic = icons.pop(k)
            rim = [m for m in members
                   if math.hypot(m["x"] - ic["x"], m["y"] - ic["y"]) > RING_CENTRE_PX * scale]
            r = (sum(math.hypot(m["x"] - ic["x"], m["y"] - ic["y"]) for m in rim) / len(rim)
                 if rim else None)
            out.append({"kind": "ring", "marks": [ic] + members, "icon": (ic["x"], ic["y"]),
                        "centre": (ic["x"], ic["y"]), "r": r})
        else:
            out.append({"kind": "ring", "marks": members, "icon": None,
                        "centre": (circ[0], circ[1]), "r": circ[2]})
        pts = [p for i, p in enumerate(pts) if i not in set(g)]
    for cl in _clusters(pts, RING_PAIR_PX * scale):
        out.append({"kind": "ring", "marks": cl, "icon": None, "centre": None, "r": None})
    return out, icons


def _clusters(pts: list[dict], gap: float) -> list[list[dict]]:
    """Single-linkage clusters of marks at `gap` px."""
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if math.hypot(pts[i]["x"] - pts[j]["x"], pts[i]["y"] - pts[j]["y"]) <= gap:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(pts)):
        groups.setdefault(find(i), []).append(pts[i])
    return list(groups.values())


def _curves(pts: list[dict], scale: float) -> list[list[dict]]:
    """Kind-3 points split into smooth curves: a LINE_GAP_PX cluster ordered
    along its principal axis, cut where a step exceeds LINE_GAP_PX or the
    path turns by more than LINE_TURN_DEG."""
    import numpy as np
    out = []
    for cl in _clusters(pts, LINE_GAP_PX * scale):
        if len(cl) <= 2:
            out.append(cl)
            continue
        xy = np.array([[m["x"], m["y"]] for m in cl], float)
        mu = xy.mean(axis=0)
        _u, _s, vt = np.linalg.svd(xy - mu)
        order = np.argsort((xy - mu) @ vt[0])
        run = [cl[order[0]]]
        for a in range(1, len(order)):
            m = cl[order[a]]
            step = math.hypot(m["x"] - run[-1]["x"], m["y"] - run[-1]["y"])
            turn = 0.0
            if len(run) >= 2:
                h0 = math.atan2(run[-1]["y"] - run[-2]["y"], run[-1]["x"] - run[-2]["x"])
                h1 = math.atan2(m["y"] - run[-1]["y"], m["x"] - run[-1]["x"])
                turn = abs((math.degrees(h1 - h0) + 180.0) % 360.0 - 180.0)
            if step > LINE_GAP_PX * scale or turn > LINE_TURN_DEG:
                out.append(run)
                run = [m]
            else:
                run.append(m)
        out.append(run)
    return out


def frame_entities(marks: list[dict], scale: float = 1.0) -> list[dict]:
    """One frame's target marks grouped into entity instances, by the
    player's convention: a ring is its centre icon (when there is one) and
    two or more kind-2 points on its perimeter; an area is many kind-4
    points filling it; a line or beam is kind-3 points along one smooth
    curve; an icon with no ring is its own entity.

    Returns instances as {"kind", "marks", "icon", "centre", "r"}: `icon`
    the centre icon's place or None, `centre` and `r` the circle when one is
    known."""
    by = {k: [m for m in marks if m.get("kind") == k] for k in ("icon", "ring", "line", "area")}
    out, lone = _rings(by["icon"], by["ring"], scale)
    for ic in lone:
        out.append({"kind": "icon", "marks": [ic], "icon": (ic["x"], ic["y"]),
                    "centre": (ic["x"], ic["y"]), "r": None})
    for run in _curves(by["line"], scale):
        out.append({"kind": "line", "marks": run, "icon": None, "centre": None, "r": None})
    for cl in _clusters(by["area"], AREA_GAP_PX * scale):
        out.append({"kind": "area", "marks": cl, "icon": None, "centre": None, "r": None})
    return out


def _seg_dist(x: float, y: float, a: dict, b: dict) -> float:
    dx, dy = b["x"] - a["x"], b["y"] - a["y"]
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - a["x"]) * dx + (y - a["y"]) * dy) / L2))
    return math.hypot(x - (a["x"] + t * dx), y - (a["y"] + t * dy))


def _poly_dist(m: dict, run: list[dict]) -> float:
    if len(run) == 1:
        return math.hypot(m["x"] - run[0]["x"], m["y"] - run[0]["y"])
    return min(_seg_dist(m["x"], m["y"], run[i], run[i + 1]) for i in range(len(run) - 1))


def same_entity(a: dict, b: dict, scale: float = 1.0) -> bool:
    """Whether instances `a` and `b`, on consecutive frames of one round,
    are one entity: their centre icons within LINK_PX; rings with one
    circle; lines whose points all lie within LINK_PX of the other's curve;
    areas within AREA_GAP_PX of each other."""
    link = LINK_PX * scale
    if a["icon"] is not None and b["icon"] is not None:
        return math.hypot(a["icon"][0] - b["icon"][0], a["icon"][1] - b["icon"][1]) <= link
    if a["kind"] != b["kind"]:
        return False
    if a["kind"] == "ring":
        if a["r"] is not None and b["r"] is not None:
            return (math.hypot(a["centre"][0] - b["centre"][0], a["centre"][1] - b["centre"][1])
                    <= max(link, 0.15 * max(a["r"], b["r"]))
                    and abs(a["r"] - b["r"]) <= 2 * TOL_PX + RING_REL * max(a["r"], b["r"]))
        for p, q in ((a, b), (b, a)):
            if p["r"] is not None:
                return all(abs(math.hypot(m["x"] - p["centre"][0], m["y"] - p["centre"][1]) - p["r"])
                           <= TOL_PX + RING_REL * p["r"] for m in q["marks"])
        return any(math.hypot(m["x"] - n["x"], m["y"] - n["y"]) <= link
                   for m in a["marks"] for n in b["marks"])
    if a["kind"] == "line":
        return (all(_poly_dist(m, b["marks"]) <= link for m in a["marks"])
                or all(_poly_dist(m, a["marks"]) <= link for m in b["marks"]))
    if a["kind"] == "area":
        return any(math.hypot(m["x"] - n["x"], m["y"] - n["y"]) <= AREA_GAP_PX * scale
                   for m in a["marks"] for n in b["marks"])
    return False


def entities(frames: list[dict], answers: dict[float, dict], scale: float = 1.0) -> list[dict]:
    """Target marks grouped into entities.

    `frames` are a session's selected frames in order (`t_ms`, `index` (the
    position in the selection), `round_no`); `answers` the player's rows by
    time. Each frame's marks are grouped into instances (`frame_entities`);
    two instances are one entity when they lie on frames `index` k and k + 1
    of one round and `same_entity` holds, or carry the same non-empty name
    in one round. Returns entities as {"id", "kind", "round_no", "instances":
    [(t_ms, instance)], "marks": [(t_ms, mark)]}; a ring's kind wins over its
    icon's when an entity holds both."""
    inst = []
    for f in frames:
        a = answers.get(float(f["t_ms"]))
        if a is None or a.get("answer") != "marks":
            continue
        ms = [m for m in a.get("marks") or () if m.get("kind") not in NOT_TARGET]
        for e in frame_entities(ms, scale):
            inst.append((f, e))
    parent = list(range(len(inst)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def names(e):
        return {(m.get("name") or "").strip().lower() for m in e["marks"]} - {""}

    for i, (fi, ei) in enumerate(inst):
        for j in range(i + 1, len(inst)):
            fj, ej = inst[j]
            if fi.get("round_no") != fj.get("round_no"):
                continue
            if (names(ei) & names(ej)) or (abs(fi["index"] - fj["index"]) == 1
                                           and same_entity(ei, ej, scale)):
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i in range(len(inst)):
        groups.setdefault(find(i), []).append(i)
    out = []
    for n, idx in enumerate(sorted(groups.values(), key=lambda g: g[0])):
        kinds = {inst[i][1]["kind"] for i in idx}
        kind = "ring" if "ring" in kinds else inst[idx[0]][1]["kind"]
        out.append({"id": n, "kind": kind, "round_no": inst[idx[0]][0].get("round_no"),
                    "instances": [(float(inst[i][0]["t_ms"]), inst[i][1]) for i in idx],
                    "marks": [(float(inst[i][0]["t_ms"]), m) for i in idx
                              for m in inst[i][1]["marks"]]})
    return out


# --- proposals ------------------------------------------------------------------

#: The proposal types, in the order they print.
TYPES = ("icon", "ring", "beam", "wall", "curve")


def proposals(icon_row: dict | None, shape_row: dict | None, all_shapes: bool = False,
              fit_row: dict | None = None, wall_row: dict | None = None) -> list[dict]:
    """The proposals stored for one sample: icon candidates; the candidate
    fits (`ability_fit` rings and beams, `ability_wall` walls and curves)
    the owner found; and the surprise path's accepted rings and beam
    (`ability_shape_scan`). `all_shapes` adds every rejected fit and piece."""
    out = []
    for c in (icon_row or {}).get("candidates") or ():
        out.append({"type": "icon", "cx": float(c["cx"]), "cy": float(c["cy"]), "r": float(c["r"])})
    if shape_row:
        for g in shape_row.get("rings") or ():
            if all_shapes or g.get("accepted"):
                out.append({"type": "ring", "cx": float(g["cx"]), "cy": float(g["cy"]),
                            "r": float(g["r"]), "path": "surprise"})
        b = shape_row.get("beam")
        if b and (all_shapes or b.get("accepted")):
            out.append({"type": "beam", "x0": b["x0"], "y0": b["y0"], "x1": b["x1"], "y1": b["y1"],
                        "path": "surprise"})
    for f in (fit_row or {}).get("fits") or ():
        if not (all_shapes or f.get("found")):
            continue
        if f.get("shape") == "ring" and f.get("cx") is not None:
            out.append({"type": "ring", "cx": float(f["cx"]), "cy": float(f["cy"]),
                        "r": float(f["r"]), "path": "candidate", "descriptor": f["descriptor"]})
        elif f.get("shape") == "beam" and f.get("x0") is not None:
            out.append({"type": "beam", "x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
                        "path": "candidate", "descriptor": f["descriptor"]})
    for f in (wall_row or {}).get("walls") or ():
        if not (all_shapes or f.get("found")) or f.get("x0") is None:
            continue
        if f.get("shape") == "curve" and f.get("points"):
            out.append({"type": "curve", "points": f["points"], "path": "candidate",
                        "descriptor": f["descriptor"]})
        else:
            out.append({"type": "wall", "x0": f["x0"], "y0": f["y0"], "x1": f["x1"], "y1": f["y1"],
                        "path": "candidate", "descriptor": f["descriptor"]})
    return out


def _segment(x: float, y: float, ax: float, ay: float, bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    L2 = dx * dx + dy * dy
    t = 0.0 if L2 == 0 else max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / L2))
    return math.hypot(x - (ax + t * dx), y - (ay + t * dy))


def distance(mark: dict, p: dict) -> float:
    """How far a mark lies outside what proposal `p` explains, in px (0 or
    less is inside the tolerance's reach before TOL_PX)."""
    x, y = float(mark["x"]), float(mark["y"])
    if p["type"] == "icon":
        return math.hypot(x - p["cx"], y - p["cy"]) - p["r"]
    if p["type"] == "ring":
        d = math.hypot(x - p["cx"], y - p["cy"])
        return min(d - max(0.0, 0.25 * p["r"] - TOL_PX), abs(d - p["r"]))
    if p["type"] == "curve":
        q = p["points"]
        return min(_segment(x, y, *q[i], *q[i + 1]) for i in range(len(q) - 1))
    return _segment(x, y, p["x0"], p["y0"], p["x1"], p["y1"])


def explains(mark: dict, p: dict) -> bool:
    return distance(mark, p) <= TOL_PX


# --- scoring --------------------------------------------------------------------

def score_session(sid: str, frames: list[dict], answers: dict[float, dict], icon_rows: dict,
                  shape_rows: dict, scale: float, all_shapes: bool = False,
                  fit_rows: dict | None = None, wall_rows: dict | None = None) -> dict:
    """Counts for one session, and its miss rows.

    `icon_rows`, `shape_rows`, `fit_rows` and `wall_rows` map a stored sample
    time to its row; a frame with no icon row has no proposals, and its
    misses say so."""
    fit_rows, wall_rows = fit_rows or {}, wall_rows or {}
    labelled = [f for f in frames if float(f["t_ms"]) in answers
                and answers[float(f["t_ms"])].get("answer") in ("marks", "nothing")]
    props = {float(f["t_ms"]): proposals(icon_rows.get(float(f["t_ms"])),
                                         shape_rows.get(float(f["t_ms"])), all_shapes,
                                         fit_rows.get(float(f["t_ms"])),
                                         wall_rows.get(float(f["t_ms"])))
             for f in labelled}
    ents = entities(labelled, answers, scale)
    index_of = {float(f["t_ms"]): f.get("index") for f in labelled}
    misses, found, mk_n, mk_hit, in_n, in_hit = [], 0, 0, 0, 0, 0
    by_kind: dict[str, dict] = {}
    for e in ents:
        hit, by = False, None
        for t, ins in e["instances"]:
            in_n += 1
            ok_ins = False
            for m in ins["marks"]:
                mk_n += 1
                p_ok = next((p for p in props[t] if explains(m, p)), None)
                mk_hit += p_ok is not None
                if p_ok is not None:
                    ok_ins = True
                    by = by or (p_ok["type"] + (f"/{p_ok['path']}" if p_ok.get("path") else ""))
            in_hit += ok_ins
            hit |= ok_ins
        found += hit
        bk = by_kind.setdefault(e["kind"], {"entities": 0, "found": 0, "found_by": {}})
        bk["entities"] += 1
        bk["found"] += hit
        if hit:
            bk["found_by"][by] = bk["found_by"].get(by, 0) + 1
        else:
            for t, ins in e["instances"]:
                row = icon_rows.get(t)
                near = min(((distance(m, p), n) for m in ins["marks"]
                            for n, p in enumerate(props[t])), default=None)
                rep = ins["icon"] or ins["centre"] or (ins["marks"][0]["x"], ins["marks"][0]["y"])
                misses.append({"kind": "surprise", "surprise": "ability_recall_miss",
                               "session_id": sid, "t_ms": t, "index": index_of.get(t),
                               "entity": e["id"], "entity_kind": e["kind"],
                               "round_no": e["round_no"], "x": rep[0], "y": rep[1],
                               "mark_kind": ins["kind"],
                               "marks": [{"x": m["x"], "y": m["y"], "kind": m["kind"]}
                                         for m in ins["marks"]],
                               "name": next((m.get("name") for m in ins["marks"] if m.get("name")),
                                            None),
                               "stream_reason": ("no_row" if row is None else row.get("reason")),
                               "nearest": None if near is None else
                               {"px": round(near[0], 1), **props[t][near[1]]}})
    unexplained = {t: 0 for t in TYPES}
    nothing_frames, nothing_unexplained = 0, 0
    for f in labelled:
        t = float(f["t_ms"])
        a = answers[t]
        ms = a.get("marks") or () if a.get("answer") == "marks" else ()
        n_un = 0
        for p in props[t]:
            if not any(explains(m, p) for m in ms):
                unexplained[p["type"]] += 1
                n_un += 1
        if a.get("answer") == "nothing":
            nothing_frames += 1
            nothing_unexplained += n_un
    return {"session_id": sid, "frames": len(frames), "labelled": len(labelled),
            "unsure_frames": sum(1 for f in frames
                                 if answers.get(float(f["t_ms"]), {}).get("answer") == "unsure"),
            "entities": len(ents), "found": found, "by_kind": by_kind,
            "instances": in_n, "instances_hit": in_hit, "marks": mk_n, "marks_hit": mk_hit,
            "unexplained": unexplained, "nothing_frames": nothing_frames,
            "nothing_unexplained": nothing_unexplained, "misses": misses}


def combine(parts: list[dict]) -> dict:
    """One widget size's totals from its sessions' counts."""
    n = sum(p["entities"] for p in parts)
    k = sum(p["found"] for p in parts)
    mn, mh = sum(p["marks"] for p in parts), sum(p["marks_hit"] for p in parts)
    fr = sum(p["labelled"] for p in parts)
    un = {t: sum(p["unexplained"][t] for p in parts) for t in TYPES}
    gated = sum(p.get("gated") or 0 for p in parts)
    surprise = sum(p.get("surprise") or 0 for p in parts)
    nf = sum(p["nothing_frames"] for p in parts)
    nu = sum(p["nothing_unexplained"] for p in parts)
    inn, inh = sum(p["instances"] for p in parts), sum(p["instances_hit"] for p in parts)
    by_kind: dict[str, dict] = {}
    for p in parts:
        for kind, c in p["by_kind"].items():
            b = by_kind.setdefault(kind, {"entities": 0, "found": 0, "found_by": {}})
            b["entities"] += c["entities"]
            b["found"] += c["found"]
            for t, v in c["found_by"].items():
                b["found_by"][t] = b["found_by"].get(t, 0) + v
    return {"sessions": [p["session_id"] for p in parts], "frames_labelled": fr,
            "entities": n, "found": k, "entity_recall": (k / n) if n else None,
            "entity_recall_lower95": cp_lower(k, n), "by_kind": by_kind,
            "instances": inn, "instances_hit": inh,
            "frame_recall": (inh / inn) if inn else None,
            "marks": mn, "marks_hit": mh, "mark_recall": (mh / mn) if mn else None,
            "unexplained_per_frame": {t: (v / fr) if fr else None for t, v in un.items()},
            "unexplained_per_frame_all": (sum(un.values()) / fr) if fr else None,
            "nothing_frames": nf,
            "unexplained_per_nothing_frame": (nu / nf) if nf else None,
            "gated": gated, "surprise": surprise,
            "surprise_rate": (surprise / gated) if gated else None,
            "misses": sum(len(p["misses"]) for p in parts)}


# --- selection ------------------------------------------------------------------

def select_session(store, sid: str) -> dict:
    """The fixed frames of one session: every CADENCE-th live sample of the
    ability pass's own 2 Hz grid over the minimap crop cache."""
    from reticle import gametime, stalls
    from reticle.ability_scan import LIVE_PHASES, shape_reader
    from reticle.cli import _active_spans, _date_of, _live_round_spans
    from reticle.minimap import minimap_roi_px
    from reticle.passes import SessionContext, cache_feed
    from reticle.profiles import get_profile
    from reticle.roi_cache import choose_source, declare_set

    man = store.read_manifest(sid)
    dur_min = float(man["source"]["duration_ms"]) / 60000.0
    if dur_min <= 15.0:
        raise SystemExit(f"{sid}: {dur_min:.1f} min is not a match (needs > 15)")
    date = _date_of(man)
    profile = get_profile(man["source_profile"])
    spans = _active_spans(store, sid, date)
    ctx = SessionContext(store=store, manifest=man, profile=profile, spans=spans)
    bp = shape_reader(ctx, spans)
    declare_set(bp, "minimap", profile, ctx.wh)

    def live_rounds():
        try:
            return _live_round_spans(store, sid, date), None
        except SystemExit as exc:
            return None, str(exc)
    cache, why, _notes = choose_source(store.root, man, profile, [bp], "cache", live_rounds)
    if cache is None:
        raise SystemExit(f"{sid}: no minimap crop cache feeds the ability pass ({why}); "
                         f"drop it, never decode")
    every, _want = cache_feed([bp], cache)
    rs, hud = store.read_rounds(sid, date), store.read_hud(sid, date)
    gt = gametime.build_session_gametime(sid, hud, rs.to_pylist(),
                                         stall_list=stalls.for_session(store, sid, date))
    live = []
    for t in every:
        g = gt.game_time_at(float(t))
        if g.phase in LIVE_PHASES:
            live.append((float(t), int(g.round_no), g.phase))
    picked = live[::CADENCE]
    box = minimap_roi_px(profile, *ctx.wh)
    return {"session_id": sid, "set": SET, "tool": TOOL, "cadence": CADENCE,
            "grid_hz": bp.hz, "live_phases": list(LIVE_PHASES), "live_samples": len(live),
            "widget_px": int(box[2] - box[0]), "roi": [int(v) for v in box],
            "capture": man["source"]["path"], "duration_min": round(dur_min, 1),
            "cache": cache.record["version"], "spans_clip": getattr(bp, "spans_clip", None),
            "selected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "frames": [{"index": i, "t_ms": t, "round_no": r, "phase": ph}
                       for i, (t, r, ph) in enumerate(picked)]}


def load_selection(store_root: Path, sid: str) -> dict | None:
    p = set_dir(store_root) / "selection" / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def _by_t(rows: list[dict]) -> dict[float, dict]:
    return {float(r["t_ms"]): r for r in rows if r.get("kind") == "frame"}


# --- sheets ---------------------------------------------------------------------

_PALETTE = [(0, 0, 255), (0, 200, 255), (255, 0, 255), (0, 255, 0), (255, 128, 0),
            (255, 255, 0), (128, 0, 255), (0, 128, 255), (255, 0, 128), (128, 255, 128)]


def _crop(root: Path, sid: str, index: int):
    import cv2
    return cv2.imread(str(set_dir(root) / "crops" / sid / f"{index:03d}_0.png"), cv2.IMREAD_COLOR)


def _draw_instance(img, ins: dict, z: float, col, label: str) -> None:
    import cv2
    import numpy as np

    def P(x, y):
        return int(round((x + 0.5) * z)), int(round((y + 0.5) * z))
    ms = ins["marks"]
    if ins["kind"] == "ring" and ins.get("r"):
        cv2.circle(img, P(*ins["centre"]), int(round(ins["r"] * z)), col, 1, cv2.LINE_AA)
    if ins["kind"] == "line" and len(ms) > 1:
        cv2.polylines(img, [np.array([P(m["x"], m["y"]) for m in ms], np.int32)], False, col, 1,
                      cv2.LINE_AA)
    if ins["kind"] == "area" and len(ms) > 2:
        hull = cv2.convexHull(np.array([P(m["x"], m["y"]) for m in ms], np.int32))
        cv2.polylines(img, [hull], True, col, 1, cv2.LINE_AA)
    for m in ms:
        c = P(m["x"], m["y"])
        cv2.circle(img, c, 5, (0, 0, 0), -1)
        cv2.circle(img, c, 3, col, -1)
        if m["kind"] == "icon":
            cv2.circle(img, c, 8, col, 1)
    x, y = ms[0]["x"], ms[0]["y"]
    cv2.putText(img, label, (P(x, y)[0] + 8, P(x, y)[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                (0, 0, 0), 3, cv2.LINE_AA)
    cv2.putText(img, label, (P(x, y)[0] + 8, P(x, y)[1] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                col, 1, cv2.LINE_AA)


def _caption(img, text: str):
    import cv2
    import numpy as np
    bar = np.full((28, img.shape[1], 3), 20, np.uint8)
    cv2.putText(bar, text, (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (240, 240, 240), 1,
                cv2.LINE_AA)
    return np.vstack([bar, img])


def group_sheet(root: Path, lab: Path, block: int, spec: str, out: Path) -> int:
    """Print each block frame's entity instances, and draw the asked frames
    (1-based, in block order) with one colour per instance. Reads the
    answers and the crops only."""
    import cv2
    items = []
    for w, ss in SESSIONS.items():
        for sid, blk in ss:
            if blk != block:
                continue
            sel = load_selection(root, sid)
            answers = load_answers(lab / f"{sid}.jsonl")
            for f in (sel or {}).get("frames", ()):
                items.append((w, sid, f, answers.get(float(f["t_ms"]))))
    want = None if spec == "all" else {int(v) for v in spec.split(",") if v.strip()}
    if want:
        out.mkdir(parents=True, exist_ok=True)
    for n, (w, sid, f, a) in enumerate(items, start=1):
        if want is not None and n not in want:
            continue
        if a is None or a.get("answer") != "marks":
            print(f"{n:3d} {sid} {f['index']:3d} r{f['round_no']}: "
                  f"{'unlabelled' if a is None else a.get('answer')}")
            continue
        ms = [m for m in a["marks"] if m.get("kind") not in NOT_TARGET]
        ins = frame_entities(ms, w / WIDGET_REF)
        desc = []
        for e in ins:
            c = {}
            for m in e["marks"]:
                c[m["kind"]] = c.get(m["kind"], 0) + 1
            desc.append(e["kind"] + "(" + "+".join(f"{v} {k}" for k, v in c.items())
                        + (f", r {e['r']:.0f}" if e.get("r") else "") + ")")
        n_smoke = sum(m.get("kind") == "smoke" for m in a["marks"])
        print(f"{n:3d} {sid} {f['index']:3d} r{f['round_no']}: {len(ins)} entities  "
              + "  ".join(desc) + (f"  [+{n_smoke} smoke]" if n_smoke else ""))
        if want:
            img = _crop(root, sid, f["index"])
            z = 3.0 if w < 400 else 2.0
            big = cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
            for k, e in enumerate(ins):
                _draw_instance(big, e, z, _PALETTE[k % len(_PALETTE)], str(k + 1))
            big = _caption(big, f"frame {n} of block {block}: {sid} #{f['index']} round "
                                f"{f['round_no']}  {len(ins)} entities")
            cv2.imwrite(str(out / f"f{n:03d}_{sid}_{f['index']:03d}.png"), big)
    if want:
        print(f"images -> {out}")
    return 0


def review_sheet(root: Path, out_dir: Path, per_page: int = 6) -> int:
    """Draw every miss of `out_dir`'s misses.jsonl on its raw crop: the
    missed instance's marks in red, the nearest proposal in cyan with its
    distance. One page per session and `per_page` frames."""
    import cv2
    import numpy as np
    rows = [json.loads(line) for line in (out_dir / "misses.jsonl").read_text(
        encoding="utf-8").splitlines() if line.strip()]
    by: dict[tuple, list] = {}
    for r in rows:
        by.setdefault((r["session_id"], r["index"]), []).append(r)
    pages = []
    for sid in dict.fromkeys(k[0] for k in by):
        keys = sorted(k for k in by if k[0] == sid)
        tiles = []
        for key in keys:
            img = _crop(root, sid, key[1])
            z = 2.0 if img.shape[1] < 400 else 1.5
            big = cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)

            def P(x, y):
                return int(round((x + 0.5) * z)), int(round((y + 0.5) * z))
            notes = []
            for r in by[key]:
                ins = {"kind": r["mark_kind"], "marks": r["marks"], "centre": (r["x"], r["y"]),
                       "r": None}
                _draw_instance(big, ins, z, (0, 0, 255), f"e{r['entity']}")
                p = r.get("nearest")
                if p:
                    cyan = (255, 255, 0)
                    if p["type"] in ("icon", "ring"):
                        cv2.circle(big, P(p["cx"], p["cy"]), max(2, int(round(p["r"] * z))), cyan,
                                   1, cv2.LINE_AA)
                    elif p["type"] == "curve":
                        for a, b in zip(p["points"], p["points"][1:]):
                            cv2.line(big, P(*a), P(*b), cyan, 2, cv2.LINE_AA)
                    else:
                        cv2.line(big, P(p["x0"], p["y0"]), P(p["x1"], p["y1"]), cyan, 2,
                                 cv2.LINE_AA)
                notes.append(f"e{r['entity']} {r['mark_kind']}"
                             + (f" near {p['type']} {p['px']:.0f}px" if p else " no proposal")
                             + (f" ({r['stream_reason']})" if r.get("stream_reason") else ""))
            tiles.append(_caption(big, f"{sid} #{key[1]} r{by[key][0]['round_no']}: "
                                       + "; ".join(notes)))
        for s in range(0, len(tiles), per_page):
            chunk = tiles[s:s + per_page]
            h = max(t.shape[0] for t in chunk)
            w = max(t.shape[1] for t in chunk)
            chunk = [np.pad(t, ((0, h - t.shape[0]), (0, w - t.shape[1]), (0, 0)))
                     for t in chunk]
            while len(chunk) % 3:
                chunk.append(np.zeros_like(chunk[0]))
            grid = np.vstack([np.hstack(chunk[i:i + 3]) for i in range(0, len(chunk), 3)])
            p = out_dir / f"misses_{sid}_p{s // per_page + 1}.png"
            cv2.imwrite(str(p), grid)
            pages.append(p)
    for p in pages:
        print(p)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(Path.home() / "reticle-store"))
    ap.add_argument("--select", action="store_true", help="fix the frames (no decode, no pixels)")
    ap.add_argument("--force", action="store_true", help="with --select, overwrite a selection")
    ap.add_argument("--labels", help="the answers directory (default the set's)")
    ap.add_argument("--all-shapes", action="store_true", help="count rejected rings and beams too")
    ap.add_argument("--out", help="where misses.jsonl and summary.json go")
    ap.add_argument("--groups", help="the grouping sheet, no stream read: comma-separated frame "
                    "numbers in block order (1-based), or 'all' for counts only")
    ap.add_argument("--block", type=int, default=1, help="with --groups, the block")
    ap.add_argument("--record", action="store_true", help="record each widget's numbers in "
                    "the metrics as ability_recall/block<N>@<sessions>")
    ap.add_argument("--tag", help="with --record, append -TAG to the part, so a run of another "
                    "pass version keeps its own series")
    ap.add_argument("--review", action="store_true",
                    help="draw --out's misses.jsonl on the raw crops (misses.png per session)")
    args = ap.parse_args(argv)
    below_normal()
    from reticle.store import Store
    store = Store(args.store)
    root = Path(args.store)
    sessions = [(w, sid, blk) for w, ss in SESSIONS.items() for sid, blk in ss]

    if args.select:
        d = set_dir(root) / "selection"
        d.mkdir(parents=True, exist_ok=True)
        for w, sid, blk in sessions:
            p = d / f"{sid}.json"
            if p.exists() and not args.force:
                print(f"{sid}: selection exists, kept ({p})")
                continue
            sel = select_session(store, sid)
            if sel["widget_px"] != w:
                raise SystemExit(f"{sid}: widget {sel['widget_px']} px, listed under {w}")
            sel["block"] = blk
            p.write_text(json.dumps(sel, indent=1), encoding="utf-8")
            print(f"{sid}  {w} px  block {blk}  {sel['live_samples']} live samples -> "
                  f"{len(sel['frames'])} frames  {sel['capture']}")
        return 0

    lab = Path(args.labels) if args.labels else set_dir(root)
    out_dir = Path(args.out) if args.out else (
        root / "analysis" / f"ability-recall-{datetime.now().strftime('%Y%m%d')}")
    if args.groups is not None:
        return group_sheet(root, lab, args.block, args.groups, out_dir / "groups")
    if args.review:
        return review_sheet(root, out_dir)
    summary, all_misses = {}, []
    for w in SESSIONS:
        parts = []
        for ww, sid, blk in sessions:
            if ww != w:
                continue
            sel = load_selection(root, sid)
            answers = load_answers(lab / f"{sid}.jsonl")
            if sel is None or not answers:
                print(f"{sid}: {'no selection' if sel is None else 'no answers'}; skipped")
                continue
            icon = store.read_events("ability_icon", sid)
            shape = store.read_events("ability_shape_scan", sid)
            if not icon:
                print(f"{sid}: no ability_icon stream; run reticle scan {sid} --only ability "
                      f"--from cache; skipped")
                continue
            fit = store.read_events("ability_fit", sid)
            wall = store.read_events("ability_wall", sid)
            part = score_session(sid, sel["frames"], answers, _by_t(icon), _by_t(shape),
                                 scale=w / 465.0, all_shapes=args.all_shapes,
                                 fit_rows=_by_t(fit), wall_rows=_by_t(wall))
            fh = next((r for r in fit if r.get("kind") == "coverage"), {})
            part["gated"], part["surprise"] = fh.get("gated"), fh.get("surprise")
            part["block"] = blk
            parts.append(part)
            all_misses.extend(part["misses"])
        if not parts:
            continue
        s = combine(parts)
        summary[str(w)] = s
        lb = s["entity_recall_lower95"]
        print(f"{w} px  sessions {', '.join(s['sessions'])}  frames {s['frames_labelled']}")
        print(f"  entity recall {s['found']}/{s['entities']}"
              + ("" if s["entity_recall"] is None else
                 f" = {s['entity_recall']:.3f}, one-sided 95% lower bound {lb:.3f}"))
        if s["entities"] < MIN_ENTITIES:
            print(f"  fewer than {MIN_ENTITIES} entities: label the next block whole")
        for kind, c in sorted(s["by_kind"].items()):
            print(f"    {kind:5s} {c['found']}/{c['entities']}  found by "
                  + (", ".join(f"{t} {v}" for t, v in sorted(c["found_by"].items())) or "-"))
        if s["frame_recall"] is not None:
            print(f"  frame recall {s['instances_hit']}/{s['instances']} = {s['frame_recall']:.3f}"
                  f" (entity instances per frame; marks {s['marks_hit']}/{s['marks']})")
        up = s["unexplained_per_frame"]
        print("  unexplained proposals per frame: "
              + "  ".join(f"{t} {v:.2f}" for t, v in up.items() if v is not None)
              + (f"; per 'nothing' frame {s['unexplained_per_nothing_frame']:.2f}"
                 if s["unexplained_per_nothing_frame"] is not None else ""))
        if s["surprise_rate"] is not None:
            print(f"  surprise path on {s['surprise']}/{s['gated']} gated samples = "
                  f"{s['surprise_rate']:.3f} (no ring or beam candidate accepted)")
        print(f"  misses {s['misses']} rows")
    if not summary:
        print("no labelled session to score")
        return 1
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "misses.jsonl").open("w", encoding="utf-8") as fh:
        for m in all_misses:
            fh.write(json.dumps(m) + "\n")
    (out_dir / "summary.json").write_text(json.dumps(
        {"tool": TOOL, "set": SET, "tol_px": TOL_PX, "link_px": LINK_PX,
         "grouping": {"ring_centre_px": RING_CENTRE_PX, "ring_rel": RING_REL,
                      "circle_rel": CIRCLE_REL, "circle_min": CIRCLE_MIN, "ring_pair_px": RING_PAIR_PX,
                      "line_gap_px": LINE_GAP_PX, "line_turn_deg": LINE_TURN_DEG,
                      "area_gap_px": AREA_GAP_PX, "at_widget_px": WIDGET_REF},
         "all_shapes": bool(args.all_shapes), "by_widget": summary}, indent=1), encoding="utf-8")
    print(f"misses and summary -> {out_dir}")
    if args.record:
        from reticle import metrics
        for w, s in summary.items():
            blocks = sorted({blk for ww, sid, blk in sessions
                             if str(ww) == w and sid in s["sessions"]})
            r3 = lambda v: None if v is None else round(v, 3)  # noqa: E731
            vals = {"frames": s["frames_labelled"], "entities": s["entities"],
                    "found": s["found"], "entity_recall": r3(s["entity_recall"]),
                    "lower95": r3(s["entity_recall_lower95"]),
                    "instances": s["instances"], "instances_hit": s["instances_hit"],
                    "frame_recall": r3(s["frame_recall"]),
                    "marks": s["marks"], "marks_hit": s["marks_hit"],
                    **{f"unexplained_{t}": r3(v) for t, v in s["unexplained_per_frame"].items()},
                    "unexplained_all": r3(s["unexplained_per_frame_all"]),
                    "unexplained_nothing": r3(s["unexplained_per_nothing_frame"]),
                    "surprise_rate": r3(s["surprise_rate"]),
                    **{f"{k}_n": c["entities"] for k, c in s["by_kind"].items()},
                    **{f"{k}_found": c["found"] for k, c in s["by_kind"].items()}}
            part = "block" + "+".join(map(str, blocks)) + (f"-{args.tag}" if args.tag else "")
            metrics.record("ability_recall", part=part,
                           session="+".join(s["sessions"]), values=vals,
                           deps={"tool": TOOL, "tol_px": TOL_PX, "link_px": LINK_PX,
                                 "all_shapes": bool(args.all_shapes), "widget_px": int(w)},
                           context={"labels": str(lab), "out": str(out_dir)},
                           note="stage 4 recall of docs/ABILITY_DETECTION.md section 10")
            print(f"recorded ability_recall/{part}@{'+'.join(s['sessions'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
