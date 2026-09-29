r"""Stage 2 of the minimap object classifier: the witnesses stage 1 lacked.

    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --x [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --question [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --lag [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --ping [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --glyph [--record]
    .\.venv\Scripts\python.exe prototypes\minimap_objects_s2.py --combined [--record]

docs/MINIMAP_OBJECTS_DESIGN.md names the parts. Each reads the minimap crop
cache and stored rows only, decodes no video, and writes to the store only
its sheets, a JSON of its rows beside them, and with `--record` a `metrics`
row. Every part is unwired (`"wire": "no"`, task `minimap-objects-c-20260929`
in the store's `notes/predictions.jsonl`).

1. **X by shape and order** (`--x`). The death owner's colour extractor
   (`adjudication.death.extract_minimap_death_marks`) proposes blobs; a
   shape test keeps those whose pixels lie on two crossing diagonals with
   four arms. A stored death is bound to an X that is born at its killfeed
   time where an icon of the victim's side ended at or before the X's first
   frame [domain:minimap/death-icon-becomes-mark]. The X then holds its
   place to the round's end [domain:minimap/death-mark-persistence]. An
   enemy killed by utility with no X at its time is searched for later in
   its round [domain:minimap/unseen-utility-death-mark].
2. **The "?" witness** (`--question`). A red blob, not X-shaped, where an
   enemy icon ended in the frame before its run began, and at most
   Q_GONE_MS old [domain:minimap/last-known-mark-timing].
2b. **The trailing time** (`--lag`). On the measured "?" instances, the time
   from the icon's place leaving the joined team vision (`team_vision`
   0.3.0 `observable`) to the icon's last frame
   [domain:minimap/vision-trailing-persistence].
3. **Ping kinds** (`--ping`). The ping owner's rule (`ping.sightings`,
   `Grouper`, `resolve`) over the whole crop cache, frames the stored
   `team_vision` rows call widget-drawn only; danger groups the pulses split
   [domain:minimap/danger-ping-pulses] are joined into one candidate where
   they cover about a danger ping's life at one place.
4. **Glyph templates** (`--glyph`). One template per glyph fact, mined from
   the capture the fact cites: Reyna's Leer on the enemy side
   [domain:abilities/reyna-leer-enemy-minimap-glyph], Wingman on the ally
   side [domain:abilities/gekko-wingman-minimap-icon], Skye's Trailblazer
   on the enemy side [domain:abilities/skye-trailblazer-enemy-minimap-glyph]
   and Astra's placed star on the ally side
   [domain:abilities/astra-star-ally-minimap-glyph]. A template is matched
   only in a session whose lineup puts its agent on the side that draws it,
   and at the widget width it was mined at.

`--combined` applies all four to the portrait gate's fits (rule Bs of
`icon_portrait_gate`) on the labels and on the gate's own sample. It names
no agent; a glyph class names an ability of the side's lineup, which rests on
the lineup prior once.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import icon_portrait_gate as gate_  # noqa: E402
import icon_teardrop as it_  # noqa: E402
import minimap_objects as m1  # noqa: E402
from reticle import lighting, ping  # noqa: E402
from reticle.adjudication.death import extract_minimap_death_marks  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "minimap-objects-s2-0.1.0"
STORE = gate_.STORE
OUT = STORE / "analysis" / "minimap-objects-c-20260929"
LOTUS, ASCENT = gate_.LOTUS, gate_.ASCENT
SESSIONS = (LOTUS, ASCENT)
ASTRA = "223d636bf8d2"

# --- 1. X shape ------------------------------------------------------------
X_R = 9.0           # the patch half-size round a blob (px at scale 1)
DIAG_PX = 1.6       # a pixel lies on a diagonal within this
DIAG_MIN = 0.75     # share of the blob's pixels on the two diagonals
ARM_MIN = 0.12      # each of the four arms' share of the arm pixels
EXT = (3.5, 9.0)    # the 90th-percentile radius
X_PX = 10.0         # a fit or a label lies on an X within this
ICON_PX = 10.0
X_WINDOW_MS = 3000.0
X_BORN_MS = (-2000.0, 1000.0)
ICON_BEFORE_MS = 1500.0
ORDER_TOL_MS = 70.0  # one cache frame: the icon's last frame may share the X's first
LATE_STEP_MS = 1000.0

# --- 2. "?" -----------------------------------------------------------------
Q_GONE_MS = 3300.0   # the measured gone time's maximum (3.28 s), rounded up
Q_SWAP_MS = 200.0    # the icon's last frame lies this near the run's first
PLACE_PX = 6.0
GAP_FRAMES = 2
MARK_PX = 8.0

# --- 2b. trailing time ----------------------------------------------------
LAG_BACK_MS = 6000.0
TRACK_PX = 10.0
VISION_PX = 3

# --- 3. pings ---------------------------------------------------------------
JOIN_PX = 2.0 * ping.SAME_PX
JOIN_GAP_S = 1.5
JOIN_SPAN_S = (8.5, 11.0)
JOIN_COVER = 0.4

# --- 4. glyphs --------------------------------------------------------------
GLYPH_NCC = 0.7
#: name -> agent, side that draws it, source (session, t_ms, x, y), mask
#: radius (px at the source's width), ring key checked at radius 9-11 or None,
#: and the fact it rests on.
GLYPHS = {
    "leer": ("Reyna", "enemy", (LOTUS, 277800.0, 424.0, 184.0), 9.0, "red",
             "abilities/reyna-leer-enemy-minimap-glyph"),
    "wingman": ("Gekko", "ally", (LOTUS, 405000.0, 77.0, 259.0), 7.0, "teal",
                "abilities/gekko-wingman-minimap-icon"),
    "trailblazer": ("Skye", "enemy", (ASCENT, 104166.7, 119.0, 248.0), 7.0, "red",
                    "abilities/skye-trailblazer-enemy-minimap-glyph"),
    "astra_star": ("Astra", "ally", (ASTRA, 629766.0, 239.0, 109.0), 5.5, None,
                   "abilities/astra-star-ally-minimap-glyph"),
}


def _j(obj) -> str:
    return json.dumps(obj, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))


def rednum(c: np.ndarray) -> np.ndarray:
    c = c.astype(np.float32)
    return c[..., 2] - np.maximum(c[..., 0], c[..., 1])


def keymask(patch: np.ndarray, colour: str) -> np.ndarray:
    c = patch.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    if colour == "red":
        return (r - np.maximum(b, g)) > 40
    return ((b - r) > 50) & (b >= g - 10)


def crops_at(s, times) -> dict:
    return dict(s.crops(sorted({float(t) for t in times})))


def window(s, t0: float, t1: float, stride: int = 1) -> list[float]:
    return [float(t) for t in s.cache_t if t0 <= t <= t1][::stride]


# ===================================================================== 1. X

def x_shape(crop: np.ndarray, colour: str, x: float, y: float, sc: float) -> dict:
    """Is the blob of `colour` nearest (x, y) an X: its pixels on two crossing
    diagonals, four arms, and an X's size?"""
    R = int(round(X_R * sc))
    h, w = crop.shape[:2]
    x0, y0 = max(0, int(round(x)) - R), max(0, int(round(y)) - R)
    x1, y1 = min(w, int(round(x)) + R + 1), min(h, int(round(y)) + R + 1)
    m = keymask(crop[y0:y1, x0:x1], colour).astype(np.uint8)
    n, lab = cv2.connectedComponents(m, connectivity=8)
    if n <= 1:
        return {"x": False, "why": "no_pixels"}
    ys, xs = np.nonzero(lab)
    k = np.argmin(np.hypot(xs + x0 - x, ys + y0 - y))
    comp = lab == lab[ys[k], xs[k]]
    py, px = np.nonzero(comp)
    if len(px) < 10 * sc * sc:
        return {"x": False, "why": "small", "n": int(len(px))}
    cx, cy = px.mean(), py.mean()
    dx, dy = px - cx, py - cy
    d = np.minimum(np.abs(dx - dy), np.abs(dx + dy)) / math.sqrt(2)
    on = d <= DIAG_PX * sc
    r = np.hypot(dx, dy)
    ext = float(np.percentile(r, 90))
    arm = on & (r >= 2.5 * sc)
    na = max(1, int(arm.sum()))
    q = [int((arm & ((dx > 0) == a) & ((dy > 0) == b)).sum()) / na
         for a in (False, True) for b in (False, True)]
    ok = (on.mean() >= DIAG_MIN and min(q) >= ARM_MIN and EXT[0] * sc <= ext <= EXT[1] * sc)
    return {"x": bool(ok), "frac": round(float(on.mean()), 3), "arms": round(min(q), 3),
            "ext": round(ext, 2), "n": int(len(px)), "cx": round(float(cx + x0), 1),
            "cy": round(float(cy + y0), 1), "why": None if ok else "shape"}


def x_marks(crop: np.ndarray, floor: np.ndarray, colour: str, sc: float) -> list[dict]:
    """Shape-confirmed X marks of one colour: the owner's blobs, then the shape test."""
    blue, red = extract_minimap_death_marks(crop, floor)
    out = []
    for a, bx, by in (blue if colour == "blue" else red):
        t = x_shape(crop, colour, bx, by, sc)
        if t["x"]:
            out.append({"x": t["cx"], "y": t["cy"], "area": a, "frac": t["frac"], "arms": t["arms"]})
    return out


def icons_of(crop: np.ndarray, side: str, s) -> list[dict]:
    if side == "ally":
        return it_.detections(crop, "ally", s) + it_.detections(crop, "self", s)
    return it_.detections(crop, "enemy", s)


def bind_death(s, d: dict) -> dict:
    """One stored death: shape-confirmed X marks born at its time, each with
    the last frame of a same-side icon at its place before it."""
    td, side = float(d["t_ms"]), d["side"]
    colour = "blue" if side == "ally" else "red"
    T = window(s, td - X_WINDOW_MS, td + X_WINDOW_MS)
    if len(T) < 10:
        return {"status": "no_frames", "born": []}
    cr = crops_at(s, T)
    T = [t for t in T if t in cr]
    sc = widget_scale(cr[T[0]].shape[1])
    xs = {t: x_marks(cr[t], s.floor, colour, sc) for t in T}
    clusters = []
    for t in T:
        for q in xs[t]:
            c = next((c for c in clusters if math.hypot(c["x"] - q["x"], c["y"] - q["y"]) <= 4 * sc), None)
            if c is None:
                clusters.append({"x": q["x"], "y": q["y"], "seen": [t]})
            else:
                c["seen"].append(t)
    born = []
    for c in clusters:
        first = min(c["seen"])
        if not X_BORN_MS[0] <= first - td <= X_BORN_MS[1]:
            continue
        after = [t for t in T if t >= first]
        before = [t for t in T if t <= first - 300.0]
        seen = set(c["seen"])
        fa = sum(t in seen for t in after) / max(1, len(after))
        fb = sum(t in seen for t in before) / len(before) if before else 0.0
        if fa < 0.5 or fb > 0.2:
            continue
        icon_last = None
        for t in T:
            if first - ICON_BEFORE_MS <= t <= first + ORDER_TOL_MS:
                if any(math.hypot(i["cx"] - c["x"], i["cy"] - c["y"]) <= ICON_PX * sc
                       for i in icons_of(cr[t], side, s)):
                    icon_last = t
        born.append({"x": c["x"], "y": c["y"], "first_ms": first, "frac_after": round(fa, 2),
                     "icon_last_ms": icon_last,
                     "order": None if icon_last is None else round(first - icon_last, 1)})
    with_icon = [b for b in born if b["icon_last_ms"] is not None]
    status = ("placed" if len(with_icon) == 1 else "ambiguous" if with_icon
              else "x_without_icon" if born else "no_x_at_time")
    return {"status": status, "born": born, "place": with_icon[0] if len(with_icon) == 1 else None}


def late_search(s, d: dict, rounds: list[dict], taken: list[dict]) -> dict:
    """The utility edge case: an enemy killed off a teammate's view may leave
    its X only when the place is seen. Red X marks first confirmed later in
    the round, at places no bound death holds."""
    r = next((r for r in rounds if int(r["round_no"]) == int(d.get("round_no") or -1)), None)
    if r is None:
        return {"status": "no_round"}
    end = r.get("t_close_ms") or r.get("t_end_ms")
    T = window(s, float(d["t_ms"]) - 1000.0, end)
    step = max(1, int(round(LATE_STEP_MS / 66.7)))
    T = T[::step]
    cr = crops_at(s, T)
    sc = widget_scale(next(iter(cr.values())).shape[1]) if cr else 1.0
    firsts = []
    for t in T:
        if t not in cr:
            continue
        for q in x_marks(cr[t], s.floor, "red", sc):
            if any(math.hypot(q["x"] - p["x"], q["y"] - p["y"]) <= X_PX * sc for p in taken):
                continue
            f = next((f for f in firsts if math.hypot(f["x"] - q["x"], f["y"] - q["y"]) <= 4 * sc), None)
            if f is None:
                firsts.append({"x": q["x"], "y": q["y"], "first_ms": t, "n": 1})
            else:
                f["n"] += 1
    new = [f for f in firsts if f["first_ms"] > float(d["t_ms"]) + 1000.0 and f["n"] >= 2]
    return {"status": "placed_late" if len(new) == 1 else "ambiguous_late" if new else "no_x_in_round",
            "late": new}


def run_x(record: bool) -> int:
    lites = {sid: gate_.Lite(sid) for sid in SESSIONS}
    results = {}
    for sid in SESSIONS:
        s = lites[sid]
        deaths, dver = m1.load_deaths(sid)
        rounds = m1.load_rounds(sid)
        rows = []
        for d in deaths:
            b = bind_death(s, d)
            rows.append({"death_id": d["death_id"], "t_ms": float(d["t_ms"]), "side": d["side"],
                         "round_no": d.get("round_no"), "victim": d.get("victim"),
                         "death_cause": d.get("death_cause"), **b})
        for r in rows:
            if r["side"] == "enemy" and r["status"] == "no_x_at_time" and r["death_cause"] not in ("gun", None):
                taken = [x["place"] for x in rows if x["round_no"] == r["round_no"] and x.get("place")]
                r["late"] = late_search(s, r, rounds, taken)
        results[sid] = rows
        print(sid, Counter((r["side"], r["status"]) for r in rows), flush=True)
    # The shape test on the player's labels.
    lab = x_label_rows(lites)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "x_deaths.json").write_text(_j(results), encoding="utf-8")
    (OUT / "x_labels.json").write_text(_j([{k: v for k, v in r.items() if k != "_crop"} for r in lab]),
                                       encoding="utf-8")
    tab = Counter((r["set"], r["class"], r["x_here"]) for r in lab)
    for k in sorted(tab, key=str):
        print(k, tab[k])
    for sid in SESSIONS:
        placed = [r for r in results[sid] if r["status"] == "placed"]
        x_death_sheet(OUT / f"x_deaths_{sid}.png", lites[sid], placed[:36])
    write_label_sheet(OUT / "x_labels_sheet.png",
                      [r for r in lab if r["x_here"] or r["class"] in ("x_mark", "other_red")][:72])
    if record:
        from reticle import metrics
        for sid in SESSIONS:
            values = {}
            for side in ("ally", "enemy"):
                sub = [r for r in results[sid] if r["side"] == side]
                c = Counter(r["status"] for r in sub)
                values[f"{side}_n"] = len(sub)
                for k in ("placed", "ambiguous", "x_without_icon", "no_x_at_time", "no_frames"):
                    values[f"{side}_{k}"] = c.get(k, 0)
                values[f"{side}_placed_frac"] = round(c.get("placed", 0) / max(1, len(sub)), 3)
                late = Counter(r["late"]["status"] for r in sub if r.get("late"))
                for k, v in late.items():
                    values[f"{side}_late_{k}"] = v
            metrics.record("minimap_objects_s2", part="x-deaths", session=sid, values=values,
                           deps={"prototype": VERSION, "diag_min": DIAG_MIN, "arm_min": ARM_MIN,
                                 "x_born_ms": list(X_BORN_MS), "icon_before_ms": ICON_BEFORE_MS},
                           context={"capture": lites[sid].capture},
                           note="stored deaths bound to a shape-confirmed X where a same-side icon ended")
        values = {}
        for (st, cl, xh), n in tab.items():
            values[f"{st}_{cl}_{'x' if xh else 'not_x'}"] = n
        metrics.record("minimap_objects_s2", part="x-labels", session="+".join(SESSIONS) + "+c62c2b06bcfb",
                       values=values, deps={"prototype": VERSION, "diag_min": DIAG_MIN, "arm_min": ARM_MIN},
                       note="the X shape test at the player's labelled points")
    return 0


def x_label_rows(lites: dict) -> list[dict]:
    """At each of the player's labelled points: is a shape-confirmed X of
    either colour within X_PX? Sets: icon_facing items (by answer and the
    verdicts file), labels/minimap marks (enemy, question, other_red),
    labels/minimap_dynamic x_mark and ping (by human)."""
    pts = []
    answers = gate_.lif.load_answers(gate_.lif.labels_path(STORE))
    index = json.loads((gate_.lif.items_dir(STORE) / "index.json").read_text(encoding="utf-8"))["items"]
    cands, named_icons, glyphs = gate_.candidate_keys()
    for it in index:
        a = answers.get(it["key"])
        if a is None:
            continue
        cl = gate_.item_class(it, a, cands, None, glyphs)
        pts.append({"set": "icon_facing", "session": it["session"], "t_ms": it["t_ms"],
                    "x": it["det_x"], "y": it["det_y"], "class": cl, "key": it["key"]})
    for sid in SESSIONS:
        for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("uncertain") or list(r.get("roi") or []) != list(lites[sid].box):
                continue
            for mk in r.get("marks", []):
                pts.append({"set": "minimap", "session": sid, "t_ms": float(r["t_ms"]), "x": float(mk["x"]),
                            "y": float(mk["y"]), "class": mk["kind"]})
    for p in sorted((STORE / "labels" / "minimap_dynamic").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") in ("x_mark", "ping") and r.get("by") == "human" and not r.get("uncertain"):
                pts.append({"set": "dynamic", "session": r["session_id"], "t_ms": float(r["t_ms"]),
                            "x": float(r["x"]), "y": float(r["y"]), "class": r["kind"]})
    out = []
    by = {}
    for p in pts:
        by.setdefault(p["session"], []).append(p)
    for sid, ps in by.items():
        try:
            s = lites.get(sid) or gate_.Lite(sid)
        except SystemExit as e:
            out.extend({**p, "x_here": None, "why": f"no_session_inputs: {e}"} for p in ps)
            continue
        lites[sid] = s
        snap = {p["t_ms"]: m1._cache_near(s, p["t_ms"]) for p in ps}
        cr = crops_at(s, [v for v in snap.values() if v is not None])
        for p in ps:
            tc = snap[p["t_ms"]]
            if tc is None or tc not in cr:
                out.append({**p, "x_here": None, "why": "no_cache_frame"})
                continue
            crop = cr[tc]
            sc = widget_scale(crop.shape[1])
            got = [dict(q, colour=c) for c in ("red", "blue") for q in x_marks(crop, s.floor, c, sc)
                   if math.hypot(q["x"] - p["x"], q["y"] - p["y"]) <= X_PX * sc]
            out.append({**p, "t_cache": tc, "x_here": bool(got), "x_colour": got[0]["colour"] if got else None,
                        "_crop": crop})
    return out


def _tile(crop, x, y, lines, marks=(), K=22, Z=5):
    pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
    xi, yi = int(round(x)), int(round(y))
    t = cv2.resize(pad[yi:yi + 2 * K, xi:xi + 2 * K], None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
    cv2.circle(t, (K * Z, K * Z), int(X_PX * Z), (0, 220, 0), 1)
    for mx, my, col in marks:
        cv2.circle(t, (int((mx - xi + K + 0.5) * Z), int((my - yi + K + 0.5) * Z)), 3 * Z, col, 2)
    for i, s in enumerate(lines):
        cv2.putText(t, s, (3, 13 + 14 * i), 0, 0.4, (0, 0, 0), 3)
        cv2.putText(t, s, (3, 13 + 14 * i), 0, 0.4, (255, 255, 255), 1)
    return t


def _sheet_grid(path: Path, tiles: list, cols: int = 6) -> None:
    if not tiles:
        print("nothing for", path)
        return
    blank = np.zeros_like(tiles[0])
    rows = [np.hstack(tiles[i:i + cols] + [blank] * (cols - len(tiles[i:i + cols])))
            for i in range(0, len(tiles), cols)]
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), np.vstack(rows))
    print("wrote", path, len(tiles), "tiles")


def write_label_sheet(path: Path, rows: list[dict]) -> None:
    _sheet_grid(path, [_tile(r["_crop"], r["x"], r["y"],
                       [f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r['set'][:5]}",
                        f"{r['class']}", f"X {'yes ' + str(r['x_colour']) if r['x_here'] else 'no'}"])
                 for r in rows if r.get("_crop") is not None])


def x_death_sheet(path: Path, s, placed: list[dict]) -> None:
    want = {}
    for d in placed:
        p = d["place"]
        t = m1._cache_near(s, p["first_ms"] + 700.0) or p["first_ms"]
        want.setdefault(t, []).append(d)
    cr = crops_at(s, want)
    tiles = []
    for t in sorted(want):
        for d in want[t]:
            p = d["place"]
            tiles.append(_tile(cr[t], p["x"], p["y"],
                               [f"{s.sid[:4]} {d['t_ms'] / 1000:.1f}s {d['side'][0]} r{d['round_no']}",
                                f"X of {d['victim']} {d['death_cause']}",
                                f"icon->X {p['order']}ms"]))
    _sheet_grid(path, tiles)


# ================================================================= 2. "?"

class Lazy:
    """Per-frame red blobs and enemy detections over one window, each computed once."""

    def __init__(self, s, cr: dict):
        self.s, self.cr, self._red, self._det = s, cr, {}, {}

    def red(self, t):
        if t not in self._red:
            self._red[t] = extract_minimap_death_marks(self.cr[t], self.s.floor)[1]
        return self._red[t]

    def icons(self, t):
        if t not in self._det:
            self._det[t] = it_.detections(self.cr[t], "enemy", self.s)
        return self._det[t]


def question_at(s, t: float, cr: dict, T: list[float], sc: float) -> list[dict]:
    """"?" marks at frame t: red blobs, not X-shaped and under no enemy icon now,
    whose red run, walked back frame by frame, ends at an enemy icon at the
    place: the icon's last frame lies at most Q_SWAP_MS before the run's first
    red frame, and that first frame at most Q_GONE_MS before t."""
    L = Lazy(s, cr)
    crop = cr[t]
    out = []
    idx = T.index(t)
    for a, bx, by in L.red(t):
        if x_shape(crop, "red", bx, by, sc)["x"]:
            continue
        if any(math.hypot(i["cx"] - bx, i["cy"] - by) <= ICON_PX * sc for i in L.icons(t)):
            continue
        on, miss, k, icon_last = t, 0, idx, None
        while k - 1 >= 0 and t - T[k - 1] <= Q_GONE_MS + Q_SWAP_MS + 200.0:
            k -= 1
            tk = T[k]
            if any(math.hypot(i["cx"] - bx, i["cy"] - by) <= ICON_PX * sc for i in L.icons(tk)):
                icon_last = tk
                break
            if any(math.hypot(x - bx, y - by) <= PLACE_PX * sc for _a, x, y in L.red(tk)):
                on, miss = tk, 0
            else:
                miss += 1
                if miss > GAP_FRAMES:
                    break
        if icon_last is None or on - icon_last > Q_SWAP_MS or t - on > Q_GONE_MS:
            continue
        out.append({"x": round(bx, 1), "y": round(by, 1), "onset_ms": on, "icon_last_ms": icon_last,
                    "age_ms": round(t - on, 1)})
    return out


def question_frames(s, times: list[float]) -> dict:
    """"?" candidates at each of `times` (cache times)."""
    out = {}
    for t in times:
        T = window(s, t - Q_GONE_MS - Q_SWAP_MS - 400.0, t)
        cr = crops_at(s, T)
        T = [u for u in T if u in cr]
        if t not in cr:
            out[t] = None
            continue
        out[t] = question_at(s, t, cr, T, widget_scale(cr[t].shape[1]))
    return out


def run_question(record: bool, n_sample: int) -> int:
    lites = {sid: gate_.Lite(sid) for sid in SESSIONS}
    rows, cand_rows = [], []
    for sid in SESSIONS:
        s = lites[sid]
        frames = []
        for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("uncertain") and list(r.get("roi") or []) == list(s.box):
                    frames.append(r)
        last = {}
        for r in frames:
            last[r["t_ms"]] = r
        frames = sorted(last.values(), key=lambda r: r["t_ms"])
        snap = {r["t_ms"]: m1._cache_near(s, float(r["t_ms"])) for r in frames}
        q = question_frames(s, [v for v in snap.values() if v is not None])
        for r in frames:
            tc = snap[r["t_ms"]]
            got = q.get(tc) if tc is not None else None
            if got is None:
                continue
            sc = 1.0
            used = set()
            for mk in r.get("marks", []):
                hit = next((i for i, c in enumerate(got) if math.hypot(c["x"] - mk["x"], c["y"] - mk["y"])
                            <= MARK_PX), None)
                if hit is not None:
                    used.add(hit)
                rows.append({"session": sid, "t_ms": tc, "mark": mk["kind"], "x": mk["x"], "y": mk["y"],
                             "witness": hit is not None})
            for i, c in enumerate(got):
                if i not in used:
                    cand_rows.append({"session": sid, "t_ms": tc, "set": "labels_unmarked", **c})
                else:
                    cand_rows.append({"session": sid, "t_ms": tc, "set": "labels_marked", **c})
        # The gate's sample frames.
        st = it_.sample_times(s, n_sample, calibration=False)
        qs = question_frames(s, st)
        for t, got in qs.items():
            for c in got or []:
                cand_rows.append({"session": sid, "t_ms": t, "set": "sample", **c})
        print(sid, "question done", flush=True)
    tab = Counter((r["mark"], r["witness"]) for r in rows)
    for k in sorted(tab, key=str):
        print(k, tab[k])
    print("candidates by set", Counter(c["set"] for c in cand_rows))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "question_witness.json").write_text(_j({"labels": rows, "candidates": cand_rows}), encoding="utf-8")
    # Sheets: every sample and unmarked candidate, and misses of labelled '?'.
    tiles = []
    for c in [c for c in cand_rows if c["set"] != "labels_marked"][:60]:
        s = lites[c["session"]]
        crop = crops_at(s, [c["t_ms"]])[c["t_ms"]]
        tiles.append(_tile(crop, c["x"], c["y"], [f"{c['session'][:4]} {c['t_ms'] / 1000:.1f}s {c['set'][:8]}",
                                                  f"age {c['age_ms'] / 1000:.2f}s",
                                                  f"icon {(c['onset_ms'] - c['icon_last_ms']):.0f}ms before"]))
    _sheet_grid(OUT / "question_candidates.png", tiles)
    tiles = []
    for r in [r for r in rows if r["mark"] == "question" and not r["witness"]][:36]:
        s = lites[r["session"]]
        crop = crops_at(s, [r["t_ms"]])[r["t_ms"]]
        tiles.append(_tile(crop, r["x"], r["y"], [f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s", "missed ?"]))
    _sheet_grid(OUT / "question_missed.png", tiles)
    if record:
        from reticle import metrics
        values = {}
        for mk in ("question", "enemy", "other_red"):
            sub = [r for r in rows if r["mark"] == mk]
            values[f"{mk}_n"] = len(sub)
            values[f"{mk}_witness"] = sum(r["witness"] for r in sub)
        for k, v in Counter(c["set"] for c in cand_rows).items():
            values[f"candidates_{k}"] = v
        metrics.record("minimap_objects_s2", part="question", session="+".join(SESSIONS), values=values,
                       deps={"prototype": VERSION, "q_gone_ms": Q_GONE_MS, "q_swap_ms": Q_SWAP_MS,
                             "labels": "labels/minimap", "n_sample": n_sample},
                       note="the '?' witness at the player's labelled marks and on the gate's sample")
    return 0


# ======================================================= 2b. trailing time

class Vision:
    """A session's stored team_vision frames: the joined observable mask by time."""

    def __init__(self, sid: str):
        p = STORE / "events" / "team_vision" / f"{sid}.jsonl"
        self.rows, self.version = {}, None
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            if r.get("kind") == "coverage":
                self.version = r.get("team_vision_version")
            elif r.get("kind") == "frame":
                self.rows[round(float(r["t_ms"]), 1)] = r
        self.t = np.array(sorted(self.rows))

    def at(self, t: float):
        i = int(np.searchsorted(self.t, t))
        k = min((j for j in (i - 1, i) if 0 <= j < len(self.t)), key=lambda j: abs(self.t[j] - t))
        if abs(self.t[k] - t) > 40.0:
            return None, "no_row"
        r = self.rows[self.t[k]]
        if r.get("widget") != "drawn" or not r.get("observable"):
            return None, r.get("reason") or r.get("widget") or "no_observable"
        obs = r["observable"]
        return lighting.unpack_mask(json.loads(obs) if isinstance(obs, str) else obs), None


def run_lag(record: bool) -> int:
    src = STORE / "analysis" / "minimap-objects-b-20260929" / "question_marks.json"
    inst = [r for r in json.loads(src.read_text(encoding="utf-8")) if r["status"] == "measured"
            and r.get("last_icon_ms") is not None]
    rows = []
    for sid in SESSIONS:
        s = gate_.Lite(sid)
        V = Vision(sid)
        for r in [r for r in inst if r["session"] == sid]:
            tl = float(r["last_icon_ms"])
            T = window(s, tl - LAG_BACK_MS, tl + 200.0)
            cr = crops_at(s, T)
            T = [t for t in T if t in cr]
            sc = widget_scale(cr[T[0]].shape[1])
            # Track the icon back from its last frame.
            pos = {}
            cur = (float(r["x"]), float(r["y"]))
            miss = 0
            for t in reversed([t for t in T if t <= tl]):
                ds = it_.detections(cr[t], "enemy", s)
                d = min(ds, key=lambda d: math.hypot(d["cx"] - cur[0], d["cy"] - cur[1]), default=None)
                if d is not None and math.hypot(d["cx"] - cur[0], d["cy"] - cur[1]) <= TRACK_PX * sc:
                    cur, miss = (d["cx"], d["cy"]), 0
                    pos[t] = cur
                else:
                    miss += 1
                    if miss > 3:
                        break
            seq = []
            for t in sorted(pos):
                m, why = V.at(t)
                if m is None:
                    seq.append((t, None, why))
                    continue
                x, y = int(round(pos[t][0])), int(round(pos[t][1]))
                v = bool(m[max(0, y - VISION_PX):y + VISION_PX + 1, max(0, x - VISION_PX):x + VISION_PX + 1].any())
                seq.append((t, v, None))
            read = [q for q in seq if q[1] is not None]
            inside = [q[0] for q in read if q[1]]
            if not read:
                status, lag = "no_vision_rows", None
            elif read[-1][1]:
                status, lag = "in_vision_at_last_frame", 0.0
            elif not inside:
                status, lag = "not_in_vision_in_track", None
            else:
                status, lag = "measured", round(tl - max(inside), 1)
            rows.append({"session": sid, "anchor_ms": r["t_ms"], "last_icon_ms": tl, "status": status,
                         "lag_ms": lag, "tracked_s": round((max(pos) - min(pos)) / 1000.0, 2) if pos else 0,
                         "unread": sum(q[1] is None for q in seq), "x": r["x"], "y": r["y"],
                         "_seq": seq, "_pos": pos, "_cr": cr})
            print(sid, round(r["t_ms"] / 1000, 1), status, lag, flush=True)
    lags = [r["lag_ms"] / 1000 for r in rows if r["status"] == "measured"]
    summary = {"instances": len(rows), "status": dict(Counter(r["status"] for r in rows)),
               "lag_s": m_dist(lags), "vision_version": "team-vision-0.3.0"}
    print(json.dumps(summary, indent=1))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "trailing_lag.json").write_text(_j([{k: v for k, v in r.items() if not k.startswith("_")}
                                               for r in rows]), encoding="utf-8")
    vis = {sid: Vision(sid) for sid in SESSIONS}
    lag_sheet(OUT / "trailing_lag_1.png", rows[:15], vis)
    lag_sheet(OUT / "trailing_lag_2.png", rows[15:], vis)
    if record:
        from reticle import metrics
        values = {"instances": len(rows)} | {f"status_{k}": v for k, v in summary["status"].items()}
        values |= {f"lag_{k}": v for k, v in summary["lag_s"].items()}
        metrics.record("minimap_objects_s2", part="trailing-lag", session="+".join(SESSIONS), values=values,
                       deps={"prototype": VERSION, "team_vision": "team-vision-0.3.0", "vision_px": VISION_PX,
                             "track_px": TRACK_PX, "instances": "last-known-marks-0.1.0 question_marks.json"},
                       note="time from an enemy icon's place leaving the joined team vision to the icon's last frame")
    return 0


def m_dist(v: list[float]) -> dict:
    if not v:
        return {"n": 0}
    a = np.asarray(v, float)
    return {"n": len(a), "min": round(float(a.min()), 3), "p25": round(float(np.percentile(a, 25)), 3),
            "median": round(float(np.median(a)), 3), "p75": round(float(np.percentile(a, 75)), 3),
            "max": round(float(a.max()), 3)}


def lag_sheet(path: Path, rows: list[dict], vis: dict) -> None:
    """Per instance: frames from before the last in-vision frame to the "?",
    the joined observable mask tinted green, the icon ringed."""
    strips = []
    for r in rows:
        seq, cr, pos = r["_seq"], r["_cr"], r["_pos"]
        if not seq:
            continue
        tl = r["last_icon_ms"]
        inside = [q[0] for q in seq if q[1]]
        t_in = max(inside) if inside else seq[0][0]
        T = sorted(cr)
        pick = [t for t in T if t_in - 300 <= t <= t_in + 200]
        pick += [t for t in T if tl - 150 <= t <= tl + 150]
        pick = sorted(set(pick))[:10]
        tiles = []
        V = vis[r["session"]]
        for t in pick:
            c = cr[t].copy()
            m, _why = V.at(t)
            if m is not None:  # the joined observable mask, tinted green
                c[m] = (0.6 * c[m] + 0.4 * np.array([0, 255, 0])).astype(np.uint8)
            p = pos.get(t) or (r["x"], r["y"])
            K, Z = 30, 4
            pad = cv2.copyMakeBorder(c, K, K, K, K, cv2.BORDER_CONSTANT)
            xi, yi = int(round(p[0])), int(round(p[1]))
            tile = cv2.resize(pad[yi:yi + 2 * K, xi:xi + 2 * K], None, fx=Z, fy=Z, interpolation=cv2.INTER_NEAREST)
            v = next((q for q in seq if q[0] == t), None)
            lab = "in" if v and v[1] else "out" if v and v[1] is False else "-"
            cv2.circle(tile, (K * Z, K * Z), int(ICON_PX * Z), (0, 220, 0) if lab == "in" else (0, 0, 230), 1)
            txt = f"{(t - tl) / 1000:+.2f} {lab}"
            cv2.putText(tile, txt, (2, 12), 0, 0.4, (0, 0, 0), 3)
            cv2.putText(tile, txt, (2, 12), 0, 0.4, (255, 255, 255), 1)
            tiles.append(tile)
        if not tiles:
            continue
        row = np.hstack(tiles + [np.zeros_like(tiles[0])] * (10 - len(tiles)))
        head = np.zeros((16, row.shape[1], 3), np.uint8)
        lg = "-" if r["lag_ms"] is None else f"{r['lag_ms'] / 1000:.2f}s"
        cv2.putText(head, f"{r['session'][:4]} ? at {r['anchor_ms'] / 1000:.1f}s lag {lg} {r['status']}",
                    (3, 12), 0, 0.42, (255, 255, 255), 1)
        strips.append(np.vstack([head, row]))
    if strips:
        path.parent.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(path), np.vstack(strips))
        print("wrote", path)


# ================================================================ 3. pings

def ping_scan(sid: str) -> dict:
    """The ping owner's rule over the whole crop cache, widget-drawn frames only
    (the stored team_vision rows' `widget`), then danger groups joined."""
    s = gate_.Lite(sid)
    V = Vision(sid)
    drawn = {t for t, r in V.rows.items() if r.get("widget") == "drawn"}
    T = [float(t) for t in s.cache_t if round(float(t), 1) in drawn]
    hz = 1000.0 / float(np.median(np.diff(T)))
    g, ts, sc = None, [], 1.0
    for k in range(0, len(T), 400):
        for t, crop in s.crops(T[k:k + 400]):
            if g is None:
                sc = widget_scale(crop.shape[1])
                g = ping.Grouper(hz, scale=sc)
            ts.append(t / 1000.0)
            for px, py, hue in ping.sightings(crop, s.floor):
                g.add(t / 1000.0, px, py, hue)
    conf, unconf, rej = ping.resolve(g, ts, hz)
    rows = ([dict(zip(("kind", "t0", "t1", "x", "y", "hue", "n"), r), status="confirmed") for r in conf]
            + [dict(zip(("kind", "t0", "t1", "x", "y", "hue", "n"), r), status="unconfirmed") for r in unconf]
            + [dict(zip(("kind", "t0", "t1", "x", "y", "hue", "n"), r), status="rejected") for r in rej])
    danger = sorted([r for r in rows if r["kind"] == "danger"], key=lambda r: r["t0"])
    joined, used = [], set()
    for i, r in enumerate(danger):
        if i in used:
            continue
        chain = [i]
        for j in range(i + 1, len(danger)):
            q, last = danger[j], danger[chain[-1]]
            if j in used or q["t0"] - last["t1"] > JOIN_GAP_S:
                continue
            if math.hypot(q["x"] - r["x"], q["y"] - r["y"]) <= JOIN_PX * sc:
                chain.append(j)
        span = danger[chain[-1]]["t1"] - r["t0"]
        cover = sum(danger[k]["n"] for k in chain) / hz / max(span, 1e-6)
        if JOIN_SPAN_S[0] <= span <= JOIN_SPAN_S[1] and cover >= JOIN_COVER and (
                len(chain) > 1 or r["status"] == "confirmed"):
            used.update(chain)
            joined.append({"kind": "danger", "t0": r["t0"], "t1": danger[chain[-1]]["t1"], "x": r["x"],
                           "y": r["y"], "groups": len(chain), "span_s": round(span, 2),
                           "cover": round(cover, 2), "statuses": dict(Counter(danger[k]["status"] for k in chain))})
    return {"hz": round(hz, 2), "frames": len(T), "scale": sc, "rows": rows, "danger_joined": joined}


def run_ping(record: bool) -> int:
    res = {}
    for sid in SESSIONS:
        res[sid] = ping_scan(sid)
        c = Counter((r["kind"], r["status"]) for r in res[sid]["rows"])
        print(sid, res[sid]["frames"], "frames;", dict(c), "; joined danger", len(res[sid]["danger_joined"]),
              flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "ping_scan.json").write_text(_j(res), encoding="utf-8")
    # Against the stored stream.
    cmp_rows = []
    for sid in SESSIONS:
        stored, _v = m1.load_pings(sid)
        conf = [r for r in res[sid]["rows"] if r["status"] == "confirmed"]
        for p in stored:
            same = [r for r in conf + res[sid]["danger_joined"] if r["kind"] == p["kind"]
                    and abs(r["t0"] * 1000 - p["t0"]) <= 1000 and math.hypot(r["x"] - p["x"], r["y"] - p["y"]) <= 8]
            cmp_rows.append({"session": sid, "kind": p["kind"], "t0": p["t0"], "refound": bool(same)})
    print("stored refound", Counter((r["kind"], r["refound"]) for r in cmp_rows))
    # Labelled items.
    lab = []
    lab_pts = [(LOTUS, 757066.7, 269.0, 246.0, "danger_triangle"), (LOTUS, 761150.0, 272.0, 244.0, "danger_triangle")]
    for p in sorted((STORE / "labels" / "minimap_dynamic").glob("*.jsonl")):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("kind") == "ping" and r.get("by") == "human" and r["session_id"] in SESSIONS:
                    lab_pts.append((r["session_id"], float(r["t_ms"]), float(r["x"]), float(r["y"]), "ping_label"))
    for sid, t, x, y, what in lab_pts:
        hits = [r for r in res[sid]["rows"] + res[sid]["danger_joined"]
                if r["t0"] * 1000 - 200 <= t <= r["t1"] * 1000 + 200 and math.hypot(r["x"] - x, r["y"] - y) <= 10]
        lab.append({"session": sid, "t_ms": t, "x": x, "y": y, "what": what,
                    "hits": [(h["kind"], h.get("status", "joined"), h.get("groups")) for h in hits]})
        print(" label", sid, round(t / 1000, 1), what, lab[-1]["hits"])
    # Enemy icons as danger: labelled true enemy icons that lie on a joined candidate.
    rows_icon = json.loads((STORE / "analysis" / "portrait-gate-20260929" / "labels_rows_bs.json").read_text())
    icon_on = [r["key"] for r in rows_icon if r["side"] == "enemy" and r["class"] == "true_icon"
               and any(j["t0"] * 1000 <= r["t_ms"] <= j["t1"] * 1000 and
                       math.hypot(j["x"] - r["x"], j["y"] - r["y"]) <= 10 for j in res[r["session"]]["danger_joined"])]
    print("true enemy icons on a joined danger candidate:", icon_on)
    ping_sheet(OUT / "ping_danger_joined.png", res)
    if record:
        from reticle import metrics
        for sid in SESSIONS:
            c = Counter((r["kind"], r["status"]) for r in res[sid]["rows"])
            values = {f"{k}_{st}": v for (k, st), v in c.items()}
            values["danger_joined"] = len(res[sid]["danger_joined"])
            values["frames"] = res[sid]["frames"]
            sub = [r for r in cmp_rows if r["session"] == sid]
            values["stored_n"] = len(sub)
            values["stored_refound"] = sum(r["refound"] for r in sub)
            values["labels_hit"] = sum(bool(r["hits"]) for r in lab if r["session"] == sid)
            values["labels_n"] = sum(1 for r in lab if r["session"] == sid)
            values["true_enemy_icons_on_joined"] = sum(k.startswith(sid) for k in icon_on)
            metrics.record("minimap_objects_s2", part="ping", session=sid, values=values,
                           deps={"prototype": VERSION, "ping": ping.__name__, "join_px": JOIN_PX,
                                 "join_gap_s": JOIN_GAP_S, "join_span_s": list(JOIN_SPAN_S), "join_cover": JOIN_COVER},
                           note="the ping owner's rule over the crop cache, with pulse-split danger groups joined")
    return 0


def ping_sheet(path: Path, res: dict) -> None:
    tiles = []
    for sid in SESSIONS:
        s = gate_.Lite(sid)
        for j in res[sid]["danger_joined"][:24]:
            ts = [m1._cache_near(s, j["t0"] * 1000 + d) for d in (500.0, (j["t1"] - j["t0"]) * 500, (j["t1"] - j["t0"]) * 1000 - 500)]
            ts = [t for t in ts if t is not None]
            cr = crops_at(s, ts)
            for k, t in enumerate(ts):
                tiles.append(_tile(cr[t], j["x"], j["y"], [f"{sid[:4]} {t / 1000:.1f}s", f"danger {j['span_s']}s",
                                                           f"g{j['groups']} cover {j['cover']}"]))
    _sheet_grid(path, tiles, cols=6)


# ================================================================ 4. glyphs

def mine_glyph_template(name: str, lites: dict) -> dict:
    agent, side, (sid, t, x, y), rad, ring, fact = GLYPHS[name]
    s = lites.setdefault(sid, gate_.Lite(sid))
    tc = m1._cache_near(s, t)
    crop = crops_at(s, [tc])[tc]
    R = int(math.ceil(rad)) + 1
    xi, yi = int(round(x)), int(round(y))
    tpl = crop[yi - R:yi + R + 1, xi - R:xi + R + 1].copy()
    yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
    mask = (np.hypot(xx, yy) <= rad).astype(np.uint8)
    OUT.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(OUT / f"template_{name}.png"), cv2.resize(tpl, None, fx=8, fy=8, interpolation=cv2.INTER_NEAREST))
    return {"name": name, "agent": agent, "side": side, "tpl": tpl, "mask": np.dstack([mask] * 3),
            "width": crop.shape[1], "ring": ring, "R": R, "source": [sid, tc, x, y], "fact": fact}


def ring_ok(crop, x, y, colour, sc) -> bool | None:
    if colour is None:
        return None
    h, w = crop.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    rr = np.hypot(xx - x, yy - y)
    ann = (rr >= 9 * sc) & (rr <= 11 * sc)
    if colour == "red":
        k = rednum(crop) > 40
    else:
        c = crop.astype(np.float32)
        k = (np.minimum(c[..., 0], c[..., 1]) - c[..., 2]) > 40
    return bool(k[ann].mean() >= 0.4) if ann.any() else None


def admitted(lineup: dict | None, tp: dict) -> bool:
    names, _why = gate_.side_gallery(lineup, tp["side"])
    return tp["agent"] in names


def glyph_matches(crop: np.ndarray, floor, templates: list[dict]) -> list[dict]:
    out = []
    sc = widget_scale(crop.shape[1])
    for tp in templates:
        if crop.shape[1] != tp["width"]:
            continue
        res = cv2.matchTemplate(crop, tp["tpl"], cv2.TM_CCOEFF_NORMED, mask=tp["mask"])
        res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
        peak = (res >= GLYPH_NCC) & (res == cv2.dilate(res, np.ones((7, 7), np.uint8)))
        for py, px in zip(*np.nonzero(peak)):
            x, y = px + tp["R"], py + tp["R"]
            if not floor[min(y, floor.shape[0] - 1), min(x, floor.shape[1] - 1)]:
                continue
            ro = ring_ok(crop, x, y, tp["ring"], sc)
            if ro is False:
                continue
            out.append({"glyph": tp["name"], "x": float(x), "y": float(y), "ncc": round(float(res[py, px]), 3),
                        "ring": ro})
    return out


def run_glyph(record: bool, n_sample: int) -> int:
    lites = {}
    templates = [mine_glyph_template(n, lites) for n in GLYPHS]
    admit = {}
    for sid in SESSIONS + (ASTRA,):
        lites.setdefault(sid, gate_.Lite(sid))
        lu = load_lineup(sid, STORE)
        admit[sid] = [tp for tp in templates if admitted(lu, tp)]
        print(sid, "admits", [tp["name"] for tp in admit[sid]])
    rows = []
    # The labelled items: icon_facing (the verdicts name #15 Wingman and #23 Trailblazer).
    answers = gate_.lif.load_answers(gate_.lif.labels_path(STORE))
    index = json.loads((gate_.lif.items_dir(STORE) / "index.json").read_text(encoding="utf-8"))["items"]
    cands, named_icons, glyphs = gate_.candidate_keys()
    for sid in SESSIONS:
        s = lites[sid]
        its = [it for it in index if it["session"] == sid and it["key"] in answers]
        cr = crops_at(s, [it["t_ms"] for it in its])
        for it in its:
            crop = cr[it["t_ms"]]
            ms = glyph_matches(crop, s.floor, admit[sid])
            near = [m for m in ms if math.hypot(m["x"] - it["det_x"], m["y"] - it["det_y"]) <= MARK_PX]
            cl = gate_.item_class(it, answers[it["key"]], cands, None, glyphs)
            rows.append({"set": "icon_facing", "session": sid, "t_ms": it["t_ms"], "x": it["det_x"],
                         "y": it["det_y"], "class": cl, "key": it["key"], "glyphs": near, "_crop": crop})
    # The player's labels/minimap marks as negatives (enemy, "?") and other-red.
    for sid in SESSIONS:
        s = lites[sid]
        frames = {}
        for line in (STORE / "labels" / "minimap" / f"{sid}.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if not r.get("uncertain") and list(r.get("roi") or []) == list(s.box):
                    frames[r["t_ms"]] = r
        snap = {t: m1._cache_near(s, float(t)) for t in frames}
        cr = crops_at(s, [v for v in snap.values() if v is not None])
        for t, r in frames.items():
            if snap[t] is None:
                continue
            ms = glyph_matches(cr[snap[t]], s.floor, admit[sid])
            for mk in r.get("marks", []):
                near = [m for m in ms if math.hypot(m["x"] - mk["x"], m["y"] - mk["y"]) <= MARK_PX]
                rows.append({"set": "minimap", "session": sid, "t_ms": snap[t], "x": mk["x"], "y": mk["y"],
                             "class": mk["kind"], "glyphs": near, "_crop": cr[snap[t]] if near else None})
    # The Leer held-out instance is item 5822b6646448|1773166.7 (in icon_facing).
    # Astra: the two A stars and the C star in 223d636bf8d2, 612-640 s at 1 Hz.
    s = lites[ASTRA]
    T = [m1._cache_near(s, t) for t in np.arange(612000.0, 641000.0, 1000.0)]
    cr = crops_at(s, [t for t in T if t is not None])
    astra = []
    for t in sorted(cr):
        ms = glyph_matches(cr[t], s.floor, admit[ASTRA])
        astra.append({"t_ms": t, "matches": ms})
    # The gate's sample frames: every match, for the sheet.
    sample = []
    for sid in SESSIONS + (ASTRA,):
        s = lites[sid]
        st = it_.sample_times(s, n_sample, calibration=False)
        for t, crop in s.crops(st):
            for mt in glyph_matches(crop, s.floor, admit[sid]):
                sample.append({"session": sid, "t_ms": float(t), **mt, "_crop": crop})
    tab = Counter((r["set"], r["class"], tuple(sorted({g["glyph"] for g in r["glyphs"]}))) for r in rows)
    for k in sorted(tab, key=str):
        print(k, tab[k])
    print("astra frames with a star match:", sum(bool(a["matches"]) for a in astra), "of", len(astra),
          Counter(len(a["matches"]) for a in astra))
    print("sample matches:", Counter((m["session"], m["glyph"]) for m in sample))
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "glyph_rows.json").write_text(_j({"labels": [{k: v for k, v in r.items() if k != "_crop"} for r in rows],
                                             "astra": astra,
                                             "sample": [{k: v for k, v in m.items() if k != "_crop"} for m in sample]}),
                                         encoding="utf-8")
    tiles = [_tile(r["_crop"], r["x"], r["y"], [f"{r['session'][:4]} {r['t_ms'] / 1000:.1f}s {r['set'][:5]}",
                                               r["class"], ",".join(f"{g['glyph']} {g['ncc']}" for g in r["glyphs"]) or "-"])
             for r in rows if r.get("_crop") is not None and (r["glyphs"] or r["class"] in ("ability_glyph", "not_icon"))]
    _sheet_grid(OUT / "glyph_labels.png", tiles)
    tiles = [_tile(m["_crop"], m["x"], m["y"], [f"{m['session'][:4]} {m['t_ms'] / 1000:.1f}s", m["glyph"],
                                               f"ncc {m['ncc']}"]) for m in sample[:60]]
    _sheet_grid(OUT / "glyph_sample.png", tiles)
    s = lites[ASTRA]
    tiles = []
    for a in astra[::3]:
        crop = cr[a["t_ms"]]
        for mt in a["matches"][:3]:
            tiles.append(_tile(crop, mt["x"], mt["y"], [f"223d {a['t_ms'] / 1000:.1f}s", "astra_star", f"ncc {mt['ncc']}"]))
    _sheet_grid(OUT / "glyph_astra.png", tiles)
    if record:
        from reticle import metrics
        values = {}
        for (st, cl, gs), n in tab.items():
            values[f"{st}_{cl}_{'+'.join(gs) or 'none'}"] = n
        values["astra_frames"] = len(astra)
        values["astra_frames_matched"] = sum(bool(a["matches"]) for a in astra)
        for (sid, gname), n in Counter((m["session"], m["glyph"]) for m in sample).items():
            values[f"sample_{sid}_{gname}"] = n
        metrics.record("minimap_objects_s2", part="glyph", session="+".join(SESSIONS) + "+" + ASTRA, values=values,
                       deps={"prototype": VERSION, "ncc": GLYPH_NCC,
                             "templates": {k: [str(v) for v in GLYPHS[k][2]] for k in GLYPHS}},
                       note="glyph templates from the cited captures, gated by the lineup, at labelled points")
    return 0


# ============================================================== combined

def run_combined(record: bool, n_sample: int) -> int:
    cal = gate_.load_calibration()
    lites = {sid: gate_.Lite(sid) for sid in SESSIONS}
    xd = json.loads((OUT / "x_deaths.json").read_text(encoding="utf-8"))
    ps = json.loads((OUT / "ping_scan.json").read_text(encoding="utf-8"))
    templates = [mine_glyph_template(n, {}) for n in GLYPHS]
    admit = {sid: [tp for tp in templates if admitted(load_lineup(sid, STORE), tp)] for sid in SESSIONS}
    rounds = {sid: m1.load_rounds(sid) for sid in SESSIONS}
    stored = {sid: m1.load_pings(sid)[0] for sid in SESSIONS}
    out = []
    for part, rows in (("labels", gate_.label_rows(cal["b_max"], cal.get("bt_max"), cal.get("bs_max"))),
                       ("sample", gate_.sample_rows(n_sample, cal["b_max"], cal.get("bt_max"), SESSIONS,
                                                    cal.get("bs_max"))[0])):
        for r in rows:
            s, crop = lites[r["session"]], r["_crop"]
            sc = widget_scale(crop.shape[1])
            colour = "red" if r["side"] == "enemy" else "blue"
            wit = {}
            xs = [q for q in x_marks(crop, s.floor, colour, sc)
                  if math.hypot(q["x"] - r["x"], q["y"] - r["y"]) <= X_PX * sc]
            if xs:
                rnd = m1.round_of(rounds[r["session"]], r["t_ms"])
                bound = [d["death_id"] for d in xd[r["session"]] if d.get("place") and d["round_no"] == rnd
                         and d["t_ms"] <= r["t_ms"] + 500 and d["side"] == r["side"]
                         and math.hypot(d["place"]["x"] - xs[0]["x"], d["place"]["y"] - xs[0]["y"]) <= X_PX * sc]
                wit["death_mark"] = {"bound": bound}
            if r["side"] == "enemy":
                T = window(s, r["t_ms"] - Q_GONE_MS - Q_SWAP_MS - 400.0, r["t_ms"])
                cr = crops_at(s, T)
                T = [t for t in T if t in cr]
                if r["t_ms"] in cr:
                    qs = [q for q in question_at(s, r["t_ms"], cr, T, sc)
                          if math.hypot(q["x"] - r["x"], q["y"] - r["y"]) <= MARK_PX * sc]
                    if qs:
                        wit["last_known"] = qs[0]
            pk = [p for p in m1.pings_at(stored[r["session"]], r["t_ms"], r["x"], r["y"], sc)
                  if m1.PING_SIDE.get(p["kind"]) == r["side"]]
            pj = [j for j in ps[r["session"]]["danger_joined"] if r["side"] == "enemy"
                  and j["t0"] * 1000 - 200 <= r["t_ms"] <= j["t1"] * 1000 + 200
                  and math.hypot(j["x"] - r["x"], j["y"] - r["y"]) <= m1.PING_PX * sc]
            if pk or pj:
                wit["ping"] = {"stored": [p["kind"] for p in pk], "joined": len(pj)}
            gm = [g for g in glyph_matches(crop, s.floor, admit[r["session"]])
                  if math.hypot(g["x"] - r["x"], g["y"] - r["y"]) <= MARK_PX * sc
                  and next(tp for tp in templates if tp["name"] == g["glyph"])["side"] == r["side"]]
            if gm:
                wit["glyph"] = gm[0]["glyph"]
            names = [("death_mark" if k == "death_mark" else "last_known" if k == "last_known"
                      else "ping:danger" if k == "ping" and r["side"] == "enemy" else
                      "ping:standard" if k == "ping" else f"glyph:{v}") for k, v in wit.items()]
            icon = f"agent_icon:{r['side']}"
            if len(names) > 1:
                cls = "disputed"
            elif names:
                cls = names[0]
            else:
                cls = icon if r.get("Bs") else "unknown"
            out.append({"part": part, "session": r["session"], "t_ms": r["t_ms"], "side": r["side"],
                        "x": r["x"], "y": r["y"], "class": r.get("class"), "key": r.get("key"), "Bs": r.get("Bs"),
                        "fit_side": r.get("fit_side"), "witnesses": wit, "verdict": cls,
                        "alternatives": names + ([icon] if r.get("Bs") and names else []), "_crop": crop})
    tab = Counter((o["part"], o["side"], o["class"] or "-", o["verdict"]) for o in out)
    for k in sorted(tab, key=str):
        print(k, tab[k])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "combined_rows.json").write_text(_j([{k: v for k, v in o.items() if k != "_crop"} for o in out]),
                                            encoding="utf-8")
    odd = [o for o in out if o["verdict"] != f"agent_icon:{o['side']}" or (o["class"] not in (None, "true_icon"))]
    _sheet_grid(OUT / "combined_sheet.png",
          [_tile(o["_crop"], o["x"], o["y"], [f"{o['session'][:4]} {o['t_ms'] / 1000:.1f}s {o['side'][0]} {o['part']}",
                                               f"{o['class'] or ''} Bs{'+' if o['Bs'] else '-'}",
                                               f"-> {o['verdict']}"]) for o in odd][:90])
    if record:
        from reticle import metrics
        values = {}
        for (part, side, cl, v), n in tab.items():
            values[f"{part}_{side}_{cl}_{v.replace(':', '_')}"] = n
        metrics.record("minimap_objects_s2", part="combined", session="+".join(SESSIONS), values=values,
                       deps={"prototype": VERSION, "gate": gate_.VERSION, "n_sample": n_sample},
                       note="stage-2 verdicts of the portrait gate's fits: X shape, '?', ping kinds and glyphs")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    for k in ("x", "question", "lag", "ping", "glyph", "combined"):
        ap.add_argument(f"--{k}", action="store_true")
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--record", action="store_true")
    args = ap.parse_args(argv)
    gate_._idle()
    if args.x:
        return run_x(args.record)
    if args.question:
        return run_question(args.record, args.n)
    if args.lag:
        return run_lag(args.record)
    if args.ping:
        return run_ping(args.record)
    if args.glyph:
        return run_glyph(args.record, args.n)
    if args.combined:
        return run_combined(args.record, args.n)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
