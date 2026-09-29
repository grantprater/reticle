r"""Do team vision's cones pass the minimap's walls, and why.

    .\.venv\Scripts\python.exe prototypes\cone_walls.py beyond [--sessions SID ...] [--n 150]
    .\.venv\Scripts\python.exe prototypes\cone_walls.py f1 [--sessions SID ...]
    .\.venv\Scripts\python.exe prototypes\cone_walls.py boxes
    .\.venv\Scripts\python.exe prototypes\cone_walls.py sheet SID T [T ...]
    ... [--record]

Task `cone-walls-20260929`, predictions W1-W5 in the store's
`notes/predictions.jsonl`. The player read `c40d950031bb_dark_frames.png`
(E7 of docs/STATISTICAL_ADJUDICATOR.md): at 572.20 s and 928.07 s the cones
pass several walls.

**The instrument is the drawn wall of each scored frame**, read from that
frame's cached crop with the builder's own line rule
(`occluders.line_mask`). It is one frame, never a median: it measures
what the frame drew and builds no map value
[domain:capture/session-pixels-are-not-the-map]; the product's walls come
from the baked static alone. On the geometry key's reference session the two
come from the same capture, so the independent check is a session that is
not its key's reference (c40d950031bb, 9acf02f98283, 3694746e4e54 on
`ascent__valorant-16x9`, whose reference is 59c70f1ef720). An icon's own
white rim reads as a line too; it counts against every arm alike.

A frame's drawn walls are its line pixels that are also line pixels on the
sampled frame half the session away: two frames, never a median, and what
moves (an icon's rim, a ping, a sliver of light) is not in both.

`beyond`: for each stored cast cone (`team_vision` rows, the product's
eligible cones at their stored origins and facings), the share of its pixels
that lie beyond a drawn wall along the ray from the origin: the cone minus
the same cone recast with the drawn walls closed. Drawn walls within
`ORIGIN_CLEAR_PX` (scaled) of the origin are ignored, because the icon is
drawn over them and a player stands against a wall; E1b found that one-pixel
question open. Arms: the old grid (`labels` BOXEDGE only), walls from `occ`
with the boxes open, and walls and boxes closed.

`f1`: E7's team F1 against the drawn light, on E7's frames and witness
(`team_vision_errors.frame_errors`), recasting every product cone under each
arm; and the light found beyond each crossed box (`cone.box_crossings`).

`boxes`: per map, the boxes the baked static draws as closed outlines, and
how much of each outline the old labels carry; a box whose interior the old
grid joins to the floor outside it is open to a ray.

Reads stored rows, the crop cache and baked geometry; decodes nothing.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import team_vision_errors as tve  # noqa: E402
from reticle import cone, geometry, lighting, metrics, minimap  # noqa: E402
from reticle import occluders as mo  # noqa: E402
from reticle.minimap import BORDER, BOXEDGE  # noqa: E402

VERSION = "cone-walls-0.1.0"
STORE = tve.STORE
SESS_331 = ("c40d950031bb", "9acf02f98283", "3694746e4e54")
SESS_465 = ("a06f04a0059f", "5822b6646448", "7010b3d62460")
ORIGIN_CLEAR_PX = 2.0
ICON_R_PX = 10.0
DRAWN_MIN_SHARE = 1 / 3
LIT_LINE_V = 190
HALF = cone.CONE_HALF_ANGLE_DEG
OUT = STORE / "analysis" / "cone-walls-20260929"
ARMS = ("old", "walls", "walls_boxes", "walls_boxes_nosnap", "walls_boxes_clear")
#: The grid each arm casts over. `old` is the stored product: the art's box
#: edges, no origin snap. The new arms snap an origin that sits on an
#: occluder to the nearest open pixel (`cone.snap_origin`), except `_nosnap`;
#: `_clear` instead lets a ray cross occluders within ORIGIN_CLEAR_PX of it.
GRID = {"old": "old", "walls": "walls", "walls_boxes": "walls_boxes",
        "walls_boxes_nosnap": "walls_boxes", "walls_boxes_clear": "walls_boxes"}


def cast(grids, arm, x, y, deg, floor, sc):
    clear = ORIGIN_CLEAR_PX * sc if arm.endswith("_clear") else 0.0
    snap = 0 if arm in ("old", "walls_boxes_nosnap", "walls_boxes_clear") else None
    return cone.raycast(grids[GRID[arm]], x, y, deg, HALF, floor, clear_px=clear,
                        snap_px=snap)


def log(msg):
    print(msg, flush=True)


def occ_of(sid):
    """`(labels, static, occ, box_id)` for the session's key: the baked `occ`
    where the npz has it, else the builder's rule over the same baked arrays."""
    with np.load(geometry.path_of(sid, STORE)) as z:
        labels, static = z["labels"].copy(), z["static"].copy()
        if "occ" in z.files and z.get("occ_built_by") is not None and \
                str(z["occ_built_by"]) == mo.occluder_stamp():
            return labels, static, z["occ"].copy(), z["box_id"].copy()
    occ, box_id, _info = mo.classify(static, labels)
    return labels, static, occ, box_id


class Grids:
    """The three passable grids for one session."""

    def __init__(self, sid):
        self.s = tve.Sess(sid, times_wanted=[])
        s = self.s
        self.labels, self.static, self.occ, self.box_id = occ_of(sid)
        self.floor = s.floor
        self.p = {"old": cone.passable_from(self.labels, s.floor),
                  "walls": cone.passable_from(self.labels, s.floor, self.occ, boxes_block=False),
                  "walls_boxes": cone.passable_from(self.labels, s.floor, self.occ)}
        self.baked_lines = mo.line_mask(self.static, self.labels)
        self.art_lines = np.isin(self.labels, (BORDER, BOXEDGE))

    def drawn(self, crop, icons=(), sealed=True):
        """This frame's drawn walls: the builder's line rule on the crop itself.

        One frame, never a median: the instrument measures what this frame
        drew and builds no map value. Two things on a frame read as a line and
        are not walls, and both are removed: an icon's white rim (a disc of
        `ICON_R_PX`, scaled, round every stored icon and every icon the
        owners' readers detect on the frame) and a thin sliver of
        drawn light (a line pixel beside the frame's raw light that is dimmer
        than `LIT_LINE_V`; light is additive, so a wall under it is brighter).
        """
        if sealed:
            m = mo.line_mask(crop, self.labels)
        else:
            orig = mo.seal_diagonals
            try:
                mo.seal_diagonals = lambda x: x
                m = mo.line_mask(crop, self.labels)
            finally:
                mo.seal_diagonals = orig
        v = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[:, :, 2]
        lit = tve.dilate(lighting.raw_lit(crop, self.s.ref), 1)
        m &= ~(lit & (v < LIT_LINE_V))
        r = ICON_R_PX * self.s.sc
        # Every icon the owners detect on this frame, stored or not: a
        # teammate in a stack is often untracked, and its rim is no wall.
        inp = self.s.inputs
        det = minimap.ally_icons(crop, self.floor, require_facing=False, support=inp.slab,
                                 static=inp.static) + \
            minimap.self_icons(crop, self.floor, require_facing=False, support=inp.slab)
        for x, y in list(icons) + [(d["cx"], d["cy"]) for d in det]:
            m &= ~clear_disc(m.shape, x, y, r)
        return m


def alignment(g: Grids, crops) -> dict:
    """Each frame's drawn lines against the baked static's and the art's, pooled."""
    out = {}
    for name, ref in (("baked", g.baked_lines), ("art", g.art_lines)):
        dist = cv2.distanceTransform((~ref).astype(np.uint8), cv2.DIST_L2, 3)
        shifts = np.zeros((7, 7))
        within, over, n = 0, 0, 0
        for dc in crops:
            for i, dy in enumerate(range(-3, 4)):
                for j, dx in enumerate(range(-3, 4)):
                    r = np.roll(np.roll(ref, dy, 0), dx, 1)
                    shifts[i, j] += float((dc & r).sum()) / max(1, int((dc | r).sum()))
            d = dist[dc]
            within += int((d <= 1.0).sum())
            over += int((d > 2.0).sum())
            n += d.size
        i, j = np.unravel_index(np.argmax(shifts), shifts.shape)
        out[name] = {"iou": round(float(shifts[i, j]) / len(crops), 4),
                     "best_dx": int(j) - 3, "best_dy": int(i) - 3,
                     "iou_at_0": round(float(shifts[3, 3]) / len(crops), 4),
                     "drawn_within_1px": round(within / max(1, n), 4),
                     "drawn_over_2px": round(over / max(1, n), 4)}
    # Scale: the drawn lines' extent against the baked lines', per frame.
    def bbox(m):
        ys, xs = np.where(m)
        return xs.min(), ys.min(), xs.max(), ys.max()
    b = bbox(g.baked_lines)
    sx, sy = [], []
    for dc in crops:
        a = bbox(dc)
        sx.append((a[2] - a[0]) / max(1, b[2] - b[0]))
        sy.append((a[3] - a[1]) / max(1, b[3] - b[1]))
    out["scale_x"], out["scale_y"] = round(float(np.median(sx)), 4), round(float(np.median(sy)), 4)
    return out


def vision_rows(sid, n):
    """`n` stored frame rows spread over the session, each with a cast cone."""
    path = tve.Store(STORE).events_path("team_vision", sid)
    rows = []
    with open(path, encoding="utf-8") as f:
        for ln in f:
            if '"kind":"frame"' not in ln[:200] or '"casts":true' not in ln:
                continue
            rows.append(ln)
    pick = np.linspace(0, len(rows) - 1, min(n, len(rows))).astype(int)
    return [json.loads(rows[i]) for i in pick], len(rows)


def clear_disc(shape, x, y, r):
    yy, xx = np.ogrid[:shape[0], :shape[1]]
    return (xx - x) ** 2 + (yy - y) ** 2 <= r * r


def beyond_session(sid, n) -> dict:
    t0 = time.time()
    g = Grids(sid)
    sc = g.s.sc
    rows, total = vision_rows(sid, n)
    by_t = {float(r["t_ms"]): r for r in rows}
    frames = list(g.s.crops(sorted(by_t)))
    acc = {a: {"cone_px": 0, "beyond_px": 0, "beyond_unsealed_px": 0, "cones": 0,
               "cones_over_5pct": 0, "origin_on_occluder": 0, "empty": 0} for a in ARMS}
    acc_loop = 0
    per_cone = {a: [] for a in ARMS}
    per = []
    for t, crop in frames:
        icons, _ = tve.icons_of(by_t[float(t)])
        xy = [(c["x"], c["y"]) for c in icons] + [(c["ox"], c["oy"]) for c in icons]
        per.append((g.drawn(crop, xy), g.drawn(crop, xy, sealed=False)))
    # A frame that draws under a third of the baked lines is not a drawn map
    # (a fade, a menu, a death screen): it measures nothing and is skipped.
    readable = [int(d.sum()) >= DRAWN_MIN_SHARE * int(g.baked_lines.sum()) for d, _u in per]
    keep = [i for i, ok in enumerate(readable) if ok]
    frames = [frames[i] for i in keep]
    per = [per[i] for i in keep]
    unreadable = len(readable) - len(keep)
    drawn_all = [d for d, _u in per]
    for i, (t, crop) in enumerate(frames):
        row = by_t[float(t)]
        icons, _ = tve.icons_of(row)
        # A wall is drawn on this frame AND on the sampled frame half the
        # session away: an icon, a ping or a sliver of light is not in both.
        j = (i + len(frames) // 2) % len(frames)
        drawn, drawn_u = per[i][0] & per[j][0], per[i][1] & per[j][1]
        for ic in icons:
            if ic["why"] is not None or ic["deg"] is None:
                continue
            ox, oy, deg = ic["ox"], ic["oy"], ic["deg"]
            clear = clear_disc(g.floor.shape, ox, oy, ORIGIN_CLEAR_PX * sc)
            for arm in ARMS:
                p = g.p[GRID[arm]]
                m = cast(g.p, arm, ox, oy, deg, g.floor, sc)
                a = acc[arm]
                a["cones"] += 1
                if not p[int(round(oy)), int(round(ox))]:
                    a["origin_on_occluder"] += 1
                if not m.any():
                    a["empty"] += 1
                    continue
                # The reference starts where the arm's own cast started.
                sx, sy = (cone.snap_origin(p, ox, oy, deg) or (ox, oy)) \
                    if arm in ("walls", "walls_boxes") else (ox, oy)
                ref = cone.raycast(p & ~(drawn & ~clear), sx, sy, deg, HALF, g.floor, snap_px=0)
                ref_u = cone.raycast(p & ~(drawn_u & ~clear), sx, sy, deg, HALF, g.floor,
                                     snap_px=0)
                b = int((m & ~ref).sum())
                a["cone_px"] += int(m.sum())
                a["beyond_px"] += b
                a["beyond_unsealed_px"] += int((m & ~ref_u).sum())
                a["cones_over_5pct"] += int(b > 0.05 * m.sum())
                per_cone[arm].append(b / m.sum())
                if arm == "old" and acc_loop < 20:
                    lp = cone._raycast_loop(p, ox, oy, deg, HALF, g.floor)
                    acc["old"].setdefault("loop_mismatch_px", 0)
                    acc["old"]["loop_mismatch_px"] += int((lp ^ m).sum())
                    acc_loop += 1
    out = {"sid": sid, "width": g.s.width, "capture": g.s.capture, "rows": len(frames),
           "unreadable_frames": unreadable,
           "rows_with_cast": total, "align": alignment(g, drawn_all)}
    for arm in ARMS:
        a = acc[arm]
        a["beyond_share"] = round(a["beyond_px"] / max(1, a["cone_px"]), 4)
        a["beyond_unsealed_share"] = round(a["beyond_unsealed_px"] / max(1, a["cone_px"]), 4)
        pc = per_cone[arm]
        a["cone_median_share"] = round(float(np.median(pc)), 4) if pc else None
        out[arm] = a
    log(f"{sid} ({g.s.width} px): {json.dumps(out)}  [{time.time() - t0:.0f} s]")
    return out


def f1_session(sid, step=2) -> dict:
    """E7's frames and witness; every product cone recast under each arm."""
    t0 = time.time()
    tve.ORACLE_STEPS = (0.0,)          # the facing oracle is not scored here
    plan = tve.plan_of(tve.cache_times(sid), step)
    s = tve.Sess(sid, times_wanted=[t for _w, t in plan])
    s.smokes, s.smoke_source = [], "not read (no cause is scored)"
    labels, _static, occ, box_id = occ_of(sid)
    grids = {"old": cone.passable_from(labels, s.floor),
             "walls": cone.passable_from(labels, s.floor, occ, boxes_block=False),
             "walls_boxes": cone.passable_from(labels, s.floor, occ)}
    assert (grids["old"] == s.passable).all(), "Sess.passable is not the old grid"
    tp = {a: [0, 0, 0] for a in ARMS + ("stored",)}
    box_lit, box_px, box_n = 0, 0, 0
    diag = {"lost_px": 0, "lost_uncast_px": 0, "dead_origin_cones": 0, "cones": 0}
    worst = []
    per_box = {}
    frames = 0
    for t, crop in s.crops([t for _w, t in plan]):
        row = s.vision.get(float(t))
        if row is None or row["widget"] != "drawn" or row.get("observable") is None:
            continue
        r = tve.frame_errors(s, float(t), crop, row, keep=True)
        m = r["_m"]
        W, casters = m["W_all"], m["casters"]
        region = s.ref.known & s.floor & ~cone.union(
            [c["fp"] for c in casters + m["uncast"]], s.floor.shape)
        frames += 1
        Ps = {}
        for arm in ARMS:
            P = cone.union([cast(grids, arm, c["ox"], c["oy"], c["deg"], s.floor, s.sc)
                            for c in casters], s.floor.shape) & region
            Ps[arm] = P
            k = tve.counts(P, W)
            for i in range(3):
                tp[arm][i] += k[i]
        # The light the old grid reached and the new grid does not: is it the
        # light of a teammate the product casts no cone for (E7's cause e)?
        lost = Ps["old"] & W & ~Ps["walls_boxes"]
        un = [c["fp"] for c in m["uncast"]]
        near_un = tve.components_touching(W, tve.dilate(cone.union(un, s.floor.shape),
                                                        tve.co.JOIN_PX)) if un else \
            np.zeros(W.shape, bool)
        lost_n = int(lost.sum())
        diag["lost_px"] += lost_n
        diag["lost_uncast_px"] += int((lost & near_un).sum())
        dead = [c for c in casters if not grids["walls_boxes"][int(round(c["oy"])), int(round(c["ox"]))]]
        diag["dead_origin_cones"] += len(dead)
        diag["cones"] += len(casters)
        if lost_n:
            worst.append((lost_n, float(t)))
        k = tve.counts(m["P"], W)
        for i in range(3):
            tp["stored"][i] += k[i]
        blocked_all = cone.union([cone.raycast(grids["walls_boxes"], c["ox"], c["oy"], c["deg"],
                                               HALF, s.floor) for c in casters], s.floor.shape)
        for c in casters:
            _b, beyond = cone.box_crossings(grids["walls"], box_id, c["ox"], c["oy"], c["deg"],
                                            HALF, s.floor)
            for bid, bm in beyond.items():
                bm = bm & region & ~blocked_all
                n = int(bm.sum())
                if not n:
                    continue
                lit = int((bm & W).sum())
                box_n += 1
                box_px += n
                box_lit += lit
                e = per_box.setdefault(int(bid), [0, 0, 0])
                e[0] += 1
                e[1] += n
                e[2] += lit
    out = {"sid": sid, "frames": frames, "width": s.width, "capture": s.capture}
    for arm, (a, b, c) in tp.items():
        out[arm] = {"tp": a, "fp": b, "fn": c, **dict(zip(("precision", "recall", "f1"),
                                                         tve.prf(a, b, c)))}
    out["box_crossings"] = box_n
    out["box_beyond_px"] = box_px
    out["box_beyond_lit_share"] = round(box_lit / box_px, 4) if box_px else None
    out["per_box"] = {str(k): v for k, v in sorted(per_box.items())}
    out["lost"] = diag
    out["lost_worst_t"] = [t for _n, t in sorted(worst, reverse=True)[:8]]
    log(f"{sid}: {json.dumps({k: v for k, v in out.items() if k != 'per_box'})} "
        f"[{time.time() - t0:.0f} s]")
    return out


def boxes_report(keys=None) -> dict:
    """Per map: boxes the static draws closed, and how much the old labels carry."""
    keys = keys or geometry.keys_in_store(STORE)
    out = {}
    for k in keys:
        p = geometry.path(k, STORE)
        if not p.is_file():
            continue
        with np.load(p) as z:
            labels, static = z["labels"].copy(), z["static"].copy()
        occ, box_id, info = mo.classify(static, labels)
        old_wall = np.isin(labels, (BORDER, BOXEDGE))
        floor = minimap.floor_mask(static)
        old_pass = floor & ~(labels == BOXEDGE)
        n, reg = cv2.connectedComponents(old_pass.astype(np.uint8), connectivity=4)
        main = np.bincount(reg[old_pass]).argmax() if old_pass.any() else -1
        rows = []
        for b in info["boxes"]:
            m = box_id == b["id"]
            if not m.any():
                continue
            ring = cv2.dilate(m.astype(np.uint8), np.ones((3, 3), np.uint8)) > 0
            outline = ring & ~cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
            carried = float((outline & cv2.dilate(old_wall.astype(np.uint8),
                                                  np.ones((3, 3), np.uint8)).astype(bool)).sum()
                            ) / max(1, int(outline.sum()))
            inner = cv2.erode(m.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & old_pass
            open_ = bool(inner.any() and (reg[inner] == main).any())
            rows.append({**b, "outline_carried": round(carried, 3), "open_to_rays": open_})
        # The player's question is about the boxes the static draws as a
        # closed outline; blobs and faint marks are counted apart.
        drawn = [r for r in rows if r["drawn"] == "outline"]
        n_open = sum(r["open_to_rays"] for r in drawn)
        out[k] = {"boxes": len(drawn), "open_to_rays": n_open,
                  "outline_under_half": sum(r["outline_carried"] < 0.5 for r in drawn),
                  "blobs": sum(r["drawn"] == "blob" for r in rows),
                  "faint": sum(r["drawn"] == "faint" for r in rows),
                  "wall_px_old": int(old_wall.sum()), "wall_px_new": int((occ == mo.WALL).sum()),
                  "line_px": info["line_px"],
                  "line_px_passable_old": int((mo.line_mask(static, labels) & old_pass).sum()),
                  "rows": rows}
        log(f"{k}: {len(drawn)} closed outlines, {n_open} open to rays in the old grid, "
            f"{out[k]['outline_under_half']} with under half their outline labelled; "
                     f"{out[k]['line_px_passable_old']} of {info['line_px']} line px passable before; "
            f"{out[k]['blobs']} blobs, {out[k]['faint']} faint marks")
    return out


def sheet(sid, times, path) -> str:
    """Per frame: the crop; the old grid's cones over the drawn walls; the new."""
    g = Grids(sid)
    ct = g.s.cache_t
    ts = [float(ct[np.argmin(np.abs(ct - t * 1000))]) for t in times]
    g.s.vision = {}
    with open(tve.Store(STORE).events_path("team_vision", sid), encoding="utf-8") as f:
        for ln in f:
            if '"kind":"frame"' in ln[:200]:
                r = json.loads(ln)
                if float(r["t_ms"]) in ts:
                    g.s.vision[float(r["t_ms"])] = r
    tiles = []
    z = 3
    for t, crop in g.s.crops(ts):
        row = g.s.vision.get(float(t))
        icons, _ = tve.icons_of(row) if row else ([], None)
        panels = [cv2.resize(crop, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)]
        for arm in ("old", "walls_boxes"):
            p = g.p[arm]
            ov = crop.copy()
            ov[~p] = (ov[~p] * 0.5 + np.array([90, 30, 0]) * 0.5).astype(np.uint8)
            for ic in icons:
                if ic["deg"] is None or ic["why"] is not None:
                    continue
                m = cone.raycast(p, ic["ox"], ic["oy"], ic["deg"], HALF, g.floor)
                ov[m] = (ov[m] * 0.35 + np.array([0, 0, 255]) * 0.65).astype(np.uint8)
            xy = [(c['x'], c['y']) for c in icons] + [(c['ox'], c['oy']) for c in icons]
            ov[g.drawn(crop, xy) & p] = (255, 0, 255)    # drawn wall the ray may cross
            if arm == "old":
                ov[g.labels == BOXEDGE] = (0, 200, 255)
            else:
                ov[g.occ == mo.BOX] = (0, 140, 255)
            big = cv2.resize(ov, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
            for ic in icons:
                if ic["deg"] is not None and ic["why"] is None:
                    cv2.circle(big, (int(ic["ox"] * z), int(ic["oy"] * z)), 7, (0, 255, 0), 2)
            cv2.putText(big, arm, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            panels.append(big)
        tile = np.hstack(panels)
        cv2.putText(tile, f"{sid} {t / 1000:.2f}s  magenta: drawn wall the grid lets a ray "
                          f"cross; blue: closed; orange: art box edge / box",
                    (8, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        tiles.append(tile)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(tiles))
    return str(path)


def box_sheet(report: dict, path, n=12) -> str:
    """The boxes the old grid left most open, per map, beside the fitted shapes."""
    worst = []
    for k, r in report.items():
        for b in r["rows"]:
            if b["drawn"] == "outline":
                worst.append((b["outline_carried"], k, b))
    worst.sort(key=lambda w: w[0])
    tiles = []
    for carried, k, b in worst[:n]:
        with np.load(geometry.path(k, STORE)) as z:
            labels, static = z["labels"].copy(), z["static"].copy()
        occ, box_id, _ = mo.classify(static, labels)
        pad = 8
        y0, y1 = max(0, b["y"] - pad), min(static.shape[0], b["y"] + b["h"] + pad)
        x0, x1 = max(0, b["x"] - pad), min(static.shape[1], b["x"] + b["w"] + pad)
        a = static[y0:y1, x0:x1].copy()
        o = a.copy()
        o[labels[y0:y1, x0:x1] == BOXEDGE] = (0, 200, 255)
        o[labels[y0:y1, x0:x1] == BORDER] = (255, 0, 255)
        nb = a.copy()
        nb[occ[y0:y1, x0:x1] == mo.WALL] = (255, 255, 0)
        nb[occ[y0:y1, x0:x1] == mo.BOX] = (0, 140, 255)
        f = 8
        t = np.hstack([cv2.resize(x, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)
                       for x in (a, o, nb)])
        t = cv2.copyMakeBorder(t, 24, 4, 0, 0, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        cv2.putText(t, f"{k} box {b['id']} at ({b['x']},{b['y']}) outline carried "
                       f"{carried:.0%} open={b['open_to_rays']}", (4, 17),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        tiles.append(t)
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 0, 0, W - t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]
    cv2.imwrite(str(path), np.vstack(tiles))
    return str(path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("beyond", "f1", "boxes", "sheet"))
    ap.add_argument("args", nargs="*")
    ap.add_argument("--sessions", nargs="+")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--tag", default="")
    ap.add_argument("--load", action="store_true",
                    help="record the saved result of an earlier run with the same --tag")
    a = ap.parse_args(argv)
    tve.idle()
    OUT.mkdir(parents=True, exist_ok=True)
    if a.cmd == "sheet":
        sid, times = a.args[0], [float(x) for x in a.args[1:]]
        print(sheet(sid, times, OUT / f"{sid}_walls{a.tag}.png"))
        return 0
    if a.cmd == "boxes":
        r = boxes_report()
        (OUT / "boxes.json").write_text(json.dumps(r, indent=1), encoding="utf-8")
        print(box_sheet(r, OUT / "boxes_worst.png"))
        if a.record:
            vals = {}
            for k, v in r.items():
                for f in ("boxes", "open_to_rays", "outline_under_half", "blobs", "faint", "line_px",
                          "line_px_passable_old", "wall_px_old", "wall_px_new"):
                    vals[f"{k}_{f}"] = v[f]
            metrics.record("cone_walls", part="boxes", session="all-keys", values=vals,
                           deps={"prototype": VERSION, "occluders": mo.occluder_stamp()[:12]})
        return 0
    sessions = a.sessions or (SESS_331 + SESS_465 if a.cmd == "beyond"
                              else ("c40d950031bb", "5822b6646448", "e78e75b2d191"))
    saved = OUT / f"{a.cmd}{a.tag}.json"
    if a.load:
        res = json.loads(saved.read_text(encoding="utf-8"))
    else:
        res = {}
        for sid in sessions:
            res[sid] = beyond_session(sid, a.n) if a.cmd == "beyond" else f1_session(sid)
        saved.write_text(json.dumps(res, indent=1), encoding="utf-8")
    if a.record:
        vals = {}
        for sid, r in res.items():
            t = sid[:4]
            if a.cmd == "beyond":
                for arm in ARMS:
                    for f in ("beyond_share", "beyond_unsealed_share", "cone_median_share",
                              "cones", "cones_over_5pct", "origin_on_occluder", "empty"):
                        vals[f"{t}_{arm}_{f}"] = r[arm][f]
                vals[f"{t}_loop_mismatch_px"] = r["old"].get("loop_mismatch_px")
                for ref in ("baked", "art"):
                    for f in ("iou", "iou_at_0", "best_dx", "best_dy", "drawn_within_1px",
                              "drawn_over_2px"):
                        vals[f"{t}_align_{ref}_{f}"] = r["align"][ref][f]
                vals[f"{t}_scale_x"], vals[f"{t}_scale_y"] = r["align"]["scale_x"], r["align"]["scale_y"]
            else:
                for arm in ARMS + ("stored",):
                    for f in ("precision", "recall", "f1"):
                        vals[f"{t}_{arm}_{f}"] = round(r[arm][f], 4)
                for f in ("lost_px", "lost_uncast_px", "dead_origin_cones", "cones"):
                    vals[f"{t}_lost_{f}"] = r["lost"][f]
                vals[f"{t}_lost_uncast_share"] = round(
                    r["lost"]["lost_uncast_px"] / max(1, r["lost"]["lost_px"]), 4)
                vals[f"{t}_frames"] = r["frames"]
                vals[f"{t}_box_crossings"] = r["box_crossings"]
                vals[f"{t}_box_beyond_px"] = r["box_beyond_px"]
                vals[f"{t}_box_beyond_lit_share"] = r["box_beyond_lit_share"]
        metrics.record("cone_walls", part=a.cmd, session="+".join(res), values=vals,
                       deps={"prototype": VERSION, "occluders": mo.occluder_stamp()[:12],
                             "origin_clear_px": ORIGIN_CLEAR_PX, "n": a.n},
                       context={"captures": {s: res[s]["capture"] for s in res}})
        print(f"recorded metrics row cone_walls/{a.cmd}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
