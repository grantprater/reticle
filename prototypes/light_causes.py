r"""Attribute scene-stack-0.3.0's unexplained light to named causes, one cause per pixel.

    .\.venv\Scripts\python.exe prototypes\light_causes.py [--record] [--limit N]

`unexplained_light.py` (unexplained-light-0.1.0) rebuilds each of the 99
fitted items of the store's `analysis/scene-light-20260929/items.json` and
marks UNEXPLAINED LIGHT: compared known floor read lit where no team cone
reaches. This tool reuses its rebuild (`unexplained_light.measure`) and gives
each unexplained pixel at most one cause, in a fixed order:

1. HALO: the pixel lies within `HALO_PX` (scale 1.0, times
   `minimap.widget_scale`) of an icon's drawn silhouette. Posed icons (the
   scene's fitted poses, the frame's outside team icons with a teardrop
   facing) take their silhouette from `scene_stack.layers`, the renderer's own
   teardrop at the class radii; an icon with no facing takes a disc of its
   class `r_out`. A halo pixel is an icon's rim, glow or edge read as lit
   floor, or floor light that hugs the icon; the sheet shows which, and the
   halo's mean class keys (`scene_stack.keys`: teal, yellow, red) are set
   beside the residual's and the control's, since a rim or glow carries its
   icon's key and floor does not.
2. ABILITY: the pixel lies inside a stored ability observation's area. The
   store holds no ability detector stream for these sessions; the stored
   observations are the player's labels and the smoke tracks, read, never
   recomputed:
   - `labels/ability/<sid>.jsonl` (named points), `labels/minimap_dynamic`
     rows of kind `ability` (points) and `labels/ability_paint` icons: a disc
     of `ABILITY_R` (scale 1.0) round the point. The player says several
     abilities draw a white-tinted, mostly circular area
     [domain:abilities/minimap-icon-pale-region]; its radius is unmeasured
     per ability, so `ABILITY_R` is swept;
   - `labels/minimap_dynamic` rows of kind `area` (a smoke, wall or ult
     footprint): the labelled box;
   - `events/smoke/<sid>.jsonl` tracks (`adjudication.smokes`): a disc of the
     stored `r` over `[first_ms, last_ms]`.
   A point or box counts when observed within `WINDOW_MS` of the item;
   `PERSIST_MS` is the variant that assumes a device stays where it was seen.
   Unreviewed detector candidates (`labels/ability_candidates` with no label)
   are left out: a candidate proposed from the residual may be the light.
3. LINGERING: an earlier team cone (0.1.0's cones at t-250 and t-500 ms).
4. RESIDUAL: what the three leave.

The CONTROL is compared known floor predicted unlit that reads unlit; each
cause's share of the unexplained pixels is set beside the same mask's share
of the control, attributed in the same order. The player's answers of
2026-09-29 bound the causes: no teammate lights a circle of floor beyond its
cone [domain:minimap/no-teammate-floor-circle], and piloted drones cast their
own cones [domain:abilities/piloted-drones-have-cones], which no stored
stream here observes.

Two sheets (`SHEET_RULE`, fixed before rendering): the residual and the halo,
each at 6x nearest-neighbour beside the whole widget. GPU first (the
renderer is `scene_stack`'s torch), crop cache only, no decode, no store
stream writes; `--record` writes `metrics` series `light_causes`; rows and
sheets go to the store's `analysis/light-causes-20260929/`. Not wired:
nothing in `reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import facing_fusion as ff  # noqa: E402
import scene_stack as ss  # noqa: E402
import unexplained_light as ul  # noqa: E402
from reticle.adjudication.ability import _jsonl  # noqa: E402

VERSION = "light-causes-0.1.0"
SERIES = "light_causes"
OUT = ss.sem.STORE / "analysis" / "light-causes-20260929"
HALO_PX = 2.0                       # scale 1.0 (465 px widget)
HALO_SWEEP = (1.0, 2.0, 3.0)
ABILITY_R = 24.0                    # scale 1.0; the pale area's radius is unmeasured per ability
ABILITY_R_SWEEP = (12.0, 24.0, 40.0)
WINDOW_MS = 1000.0
PERSIST_MS = 30000.0
ZOOM = 6
WIN = 48                            # zoom window, px at scale 1.0
SHEET_RULE = ("per sheet, the 8 items with the most pixels of that cause (residual; halo), at most 2 per session, "
              "4 per widget size where the size has them; the zoom window centres on the item's largest "
              "connected component of that cause")
CAUSES = ("halo", "ability", "lingering", "residual")

# BGR
CYAN, MAGENTA, YELLOW, GREEN, WHITE = (255, 255, 0), (255, 0, 255), (0, 220, 255), (80, 255, 80), (255, 255, 255)


# ---------------------------------------------------------------- causes

def silhouette(shape, icons_posed, icons_unposed, sc) -> np.ndarray:
    """Pixels the renderer draws an icon over: `scene_stack.layers` for posed icons, a disc of `r_out` else."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    out = np.zeros((h, w), bool)
    px = ss.torch.tensor(xx.ravel(), dtype=ss.torch.float32, device=ss.DEV)
    py = ss.torch.tensor(yy.ravel(), dtype=ss.torch.float32, device=ss.DEV)
    for cls, x, y, deg in icons_posed:
        t = lambda v: ss.torch.tensor([[float(v)]], dtype=ss.torch.float32, device=ss.DEV)  # noqa: E731
        O, _ring, lobe = ss.layers(cls, sc, px, py, t(x), t(y), t(math.radians(deg)))
        if cls == "enemy":
            O = O + (1.0 - ss.ENEMY_LOBE_ALPHA) * lobe
        out |= (O[0] > 0.5).cpu().numpy().reshape(h, w)
    for cls, x, y in icons_unposed:
        out |= np.hypot(xx - x, yy - y) <= ss.CLASS_RADII[cls][1] * sc
    return out


def icon_sets(b) -> tuple[list, list]:
    posed, unposed = [], []
    for i, ic in enumerate(b["icons"]):
        p = b["poses"].get(i)
        if p is None:
            unposed.append((ic["cls"], ic["x0"], ic["y0"]))
        else:
            posed.append((ic["cls"], p[0], p[1], p[2]))
    for o in b["outside"]:
        cls = "self" if o.get("role") == "self" else "ally"
        if o.get("deg") is None:
            unposed.append((cls, o["x"], o["y"]))
        else:
            posed.append((cls, o["x"], o["y"], o["deg"]))
    return posed, unposed


def halo_dist(shape, b) -> np.ndarray:
    """Distance in px from each pixel to the nearest drawn icon silhouette (0 inside)."""
    posed, unposed = icon_sets(b)
    sil = silhouette(shape, posed, unposed, b["sc"])
    if not sil.any():
        return np.full(shape, np.inf, np.float32)
    return cv2.distanceTransform((~sil).astype(np.uint8), cv2.DIST_L2, 5)


def ability_sources(sid: str) -> list[dict]:
    """Every stored ability observation of a session: `{kind, t0, t1, x, y, box|r, name, source}`."""
    root = ss.sem.STORE
    out = []
    for r in _jsonl(root / "labels" / "ability" / f"{sid}.jsonl"):
        if r.get("not_ability"):
            continue
        out.append({"kind": "point", "t0": float(r["t_ms"]), "t1": float(r["t_ms"]), "x": r["x"], "y": r["y"],
                    "name": r.get("category_id") or "ability (unnamed)", "source": "labels/ability"})
    for r in _jsonl(root / "labels" / "minimap_dynamic" / f"{sid}.jsonl"):
        if r.get("kind") == "ability":
            out.append({"kind": "point", "t0": float(r["t_ms"]), "t1": float(r["t_ms"]), "x": r["x"], "y": r["y"],
                        "name": "ability (minimap_dynamic)", "source": "labels/minimap_dynamic"})
        elif r.get("kind") == "area" and r.get("box"):
            out.append({"kind": "box", "t0": float(r["t_ms"]), "t1": float(r["t_ms"]), "box": r["box"],
                        "x": r["x"], "y": r["y"], "name": "area (smoke/wall/ult)",
                        "source": "labels/minimap_dynamic"})
    for r in _jsonl(root / "labels" / "ability_paint" / f"{sid}.jsonl"):
        for ic in r.get("icons") or []:
            out.append({"kind": "point", "t0": float(r["t_ms"]), "t1": float(r["t_ms"]), "x": ic["x"],
                        "y": ic["y"], "name": ic.get("category_id") or "ability (painted)",
                        "source": "labels/ability_paint"})
    for r in _jsonl(root / "events" / "smoke" / f"{sid}.jsonl"):
        if r.get("kind") == "track":
            out.append({"kind": "disc", "t0": float(r["first_ms"]), "t1": float(r["last_ms"]), "x": r["cx"],
                        "y": r["cy"], "r": float(r["r"]), "name": "smoke track", "source": "events/smoke"})
    return out


def ability_mask(shape, srcs, t_ms, win_ms, R, sc) -> tuple[np.ndarray, list[dict]]:
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w]
    m = np.zeros(shape, bool)
    used = []
    for s in srcs:
        if not (s["t0"] - win_ms <= t_ms <= s["t1"] + win_ms):
            continue
        if s["kind"] == "point":
            a = np.hypot(xx - s["x"], yy - s["y"]) <= R * sc
        elif s["kind"] == "disc":
            a = np.hypot(xx - s["x"], yy - s["y"]) <= s["r"]
        else:
            bx, by, bw, bh = s["box"]
            a = np.zeros(shape, bool)
            a[max(0, by):by + bh, max(0, bx):bx + bw] = True
        m |= a
        used.append((s, a))
    return m, used


# ---------------------------------------------------------------- one item

def attribute(U, C, masks):
    """Sequential attribution of U and C to `masks` in order; returns per-cause counts."""
    left_u, left_c = U.copy(), C.copy()
    cu, cc, maps = {}, {}, {}
    for name, m in masks:
        tu, tc = left_u & m, left_c & m
        cu[name], cc[name], maps[name] = int(tu.sum()), int(tc.sum()), tu
        left_u &= ~m
        left_c &= ~m
    cu["residual"], cc["residual"], maps["residual"] = int(left_u.sum()), int(left_c.sum()), left_u
    return cu, cc, maps


def measure(s, r, tracks, srcs):
    row0, draw = ul.measure(s, r, tracks)
    b = draw["b"]
    shape = draw["crop"].shape[:2]
    sc = b["sc"]
    U, C = b["unex"], b["ctrl"]
    dist = halo_dist(shape, b)
    halo = dist <= HALO_PX * sc
    t = float(r["t_ms"])
    abil, used = ability_mask(shape, srcs, t, WINDOW_MS, ABILITY_R, sc)
    early = draw["either"]
    cu, cc, maps = attribute(U, C, [("halo", halo), ("ability", abil), ("lingering", early)])
    row = {k: row0[k] for k in ("key", "set", "session", "t_ms", "size", "stacked", "floor_n",
                                "unexplained_n", "control_n", "unexplained_share", "stored_unexplained_n")}
    row["U"] = cu
    row["C"] = cc
    # sweeps: raw (not sequential) coverage of U and C
    row["halo_sweep"] = {str(m): [int((U & (dist <= m * sc)).sum()), int((C & (dist <= m * sc)).sum())]
                         for m in HALO_SWEEP}
    sweep = {}
    for win in (WINDOW_MS, PERSIST_MS):
        for R in ABILITY_R_SWEEP:
            am, _u = ability_mask(shape, srcs, t, win, R, sc)
            sweep[f"{int(win)}ms_R{int(R)}"] = [int((U & am).sum()), int((C & am).sum()),
                                                int((U & am & ~halo).sum()), int((C & am & ~halo).sum())]
    row["ability_sweep"] = sweep
    row["ability_sources_1s"] = len(used)
    row["ability_names_1s"] = sorted({u["name"] for u, _a in used})
    row["ability_names_hit_U"] = sorted({u["name"] for u, a in used if (a & U).any()})
    near30 = [x for x in srcs if x["t0"] - PERSIST_MS <= t <= x["t1"] + PERSIST_MS]
    row["ability_sources_30s"] = len(near30)
    row["ability_names_30s"] = sorted({x["name"] for x in near30})
    row["lingering_raw"] = [int((U & early).sum()), int((C & early).sum())]
    kk = ss.keys(draw["crop"])                     # teal, yellow, red: an icon's rim or glow carries its key
    row["keys"] = {name: ([round(float(kk[j][m].sum()), 2) for j in range(3)] + [int(m.sum())])
                   for name, m in (("U_halo", maps["halo"]), ("U_residual", maps["residual"]),
                                   ("C_halo", C & halo), ("C_rest", C & ~halo))}
    draw.update({"halo": halo, "abil": abil, "early": early, "maps": maps, "used": used})
    return row, draw


# ---------------------------------------------------------------- summary

def summarise(rows):
    U = sum(r["unexplained_n"] for r in rows)
    C = sum(r["control_n"] for r in rows)
    out = {"n": len(rows), "unexplained_px": U, "control_px": C,
           "reproduced_n": sum(r["unexplained_n"] == r["stored_unexplained_n"] for r in rows)}
    for c in CAUSES:
        u = sum(r["U"][c] for r in rows)
        cc = sum(r["C"][c] for r in rows)
        out[f"{c}_share"] = round(u / max(U, 1), 4)
        out[f"{c}_share_control"] = round(cc / max(C, 1), 4)
    for m in HALO_SWEEP:
        k = str(m)
        out[f"halo_raw_M{int(m)}_share"] = round(sum(r["halo_sweep"][k][0] for r in rows) / max(U, 1), 4)
        out[f"halo_raw_M{int(m)}_share_control"] = round(sum(r["halo_sweep"][k][1] for r in rows) / max(C, 1), 4)
    for k in rows[0]["ability_sweep"] if rows else []:
        have = [r for r in rows if r["ability_sweep"][k][0] + r["ability_sweep"][k][1] > 0
                or (r["ability_sources_1s"] if k.startswith(str(int(WINDOW_MS))) else r["ability_sources_30s"]) > 0]
        uu = sum(r["unexplained_n"] for r in have)
        cc = sum(r["control_n"] for r in have)
        out[f"ability_{k}_items"] = len(have)
        out[f"ability_{k}_share"] = round(sum(r["ability_sweep"][k][0] for r in rows) / max(U, 1), 4)
        out[f"ability_{k}_share_control"] = round(sum(r["ability_sweep"][k][1] for r in rows) / max(C, 1), 4)
        out[f"ability_{k}_after_halo_share"] = round(sum(r["ability_sweep"][k][2] for r in rows) / max(U, 1), 4)
        out[f"ability_{k}_items_share"] = round(sum(r["ability_sweep"][k][0] for r in have) / max(uu, 1), 4)
        out[f"ability_{k}_items_share_control"] = round(sum(r["ability_sweep"][k][1] for r in have) / max(cc, 1), 4)
    out["items_ability_1s"] = sum(r["ability_sources_1s"] > 0 for r in rows)
    out["items_ability_30s"] = sum(r["ability_sources_30s"] > 0 for r in rows)
    for name in ("U_halo", "U_residual", "C_halo", "C_rest"):
        n = sum(r["keys"][name][3] for r in rows)
        for j, key in enumerate(("teal", "yellow", "red")):
            out[f"key_{key}_{name}"] = round(sum(r["keys"][name][j] for r in rows) / max(n, 1), 4)
    out["lingering_raw_share"] =round(sum(r["lingering_raw"][0] for r in rows) / max(U, 1), 4)
    out["lingering_raw_share_control"] = round(sum(r["lingering_raw"][1] for r in rows) / max(C, 1), 4)
    return out


# ---------------------------------------------------------------- sheets

def _up(img, z):
    return cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)


def _outline(big, mask, z, col, ox=0, oy=0):
    if not mask.any():
        return
    m = _up(mask.astype(np.uint8) * 255, z)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(big, cs, -1, col, 1)


def select(rows, draws, cause):
    """`SHEET_RULE` for one cause."""
    picked = []
    for size in sorted({r["size"] for r in rows}):
        per_sess = Counter()
        cand = sorted([r for r in rows if r["size"] == size and r["U"][cause] > 0], key=lambda r: -r["U"][cause])
        take = []
        for r in cand:
            if per_sess[r["session"]] >= 2:
                continue
            take.append(r)
            per_sess[r["session"]] += 1
            if len(take) == 4:
                break
        picked += take
    return picked[:8]


def tile(row, draw, cause, capture):
    crop = draw["crop"]
    h, w = crop.shape[:2]
    sc = draw["b"]["sc"]
    m = draw["maps"][cause]
    n, lab, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    k = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA])) if n > 1 else 0
    cx, cy = (cen[k] if n > 1 else (w / 2, h / 2))
    half = int(round(WIN * sc / 2))
    x0 = int(np.clip(round(cx) - half, 0, w - 2 * half))
    y0 = int(np.clip(round(cy) - half, 0, h - 2 * half))
    sl = (slice(y0, y0 + 2 * half), slice(x0, x0 + 2 * half))
    raw = _up(crop[sl], ZOOM)
    ann = raw.copy()
    for name, col in (("halo", MAGENTA), ("ability", YELLOW), ("lingering", GREEN), ("residual", CYAN)):
        _outline(ann, draw["maps"][name][sl], ZOOM, col)
    _outline(ann, draw["b"]["keep"][sl], ZOOM, WHITE)
    ctx = _up(crop, 2 if w < 400 else 1)
    zc = ctx.shape[1] / w
    cv2.rectangle(ctx, (int(x0 * zc), int(y0 * zc)), (int((x0 + 2 * half) * zc), int((y0 + 2 * half) * zc)),
                  CYAN, 1)
    Hh = max(raw.shape[0], ctx.shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, Hh - im.shape[0], 0, 6, cv2.BORDER_CONSTANT, value=(40, 40, 40))  # noqa: E731
    body = np.hstack([pad(raw), pad(ann), pad(ctx)])
    lines = [f"{row['session']}  {capture}  t {row['t_ms'] / 1000:.2f} s  widget {row['size']} px  {row['set']}  "
             f"{'STACKED' if row['stacked'] else 'isolated'}  zoom box x{x0}-{x0 + 2 * half} y{y0}-{y0 + 2 * half}",
             f"unexplained {row['unexplained_n']} px: halo {row['U']['halo']}, ability {row['U']['ability']}, "
             f"lingering {row['U']['lingering']}, residual {row['U']['residual']}; abilities within 1 s: "
             f"{', '.join(row['ability_names_1s']) or 'none'}"]
    head = np.zeros((22 * len(lines) + 6, body.shape[1], 3), np.uint8)
    for i, s_ in enumerate(lines):
        cv2.putText(head, s_, (4, 18 + 22 * i), 0, 0.5, WHITE, 1)
    return np.vstack([head, body, np.full((8, body.shape[1], 3), 90, np.uint8)])


def sheet(rows, draws, cause, captures, path):
    picked = select(rows, draws, cause)
    if not picked:
        return None
    tiles = [tile(r, draws[id(r)], cause, captures[r["session"]]) for r in picked]
    W = max(t.shape[1] for t in tiles)
    tiles = [cv2.copyMakeBorder(t, 0, 0, 0, W - t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]
    leg = np.zeros((30, W, 3), np.uint8)
    cv2.putText(leg, f"{VERSION} {cause.upper()} sheet. Left: raw crop x{ZOOM} nearest. Middle: outlines -- "
                f"magenta halo, yellow ability area, green lingering cone, cyan residual, white compared region. "
                f"Right: whole widget, cyan box = zoom.", (4, 20), 0, 0.5, WHITE, 1)
    cv2.imwrite(str(path), np.vstack([leg] + tiles))
    return [(r["session"], r["t_ms"]) for r in picked]


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N items (a smoke run; never recorded)")
    args = ap.parse_args(argv)
    ss._idle()
    ss.CAL = json.loads(ss.CAL_PATH.read_text(encoding="utf-8"))
    ss.LCAL = json.loads(ss.LIGHT_CAL_PATH.read_text(encoding="utf-8"))
    data = json.loads(ul.ITEMS.read_text(encoding="utf-8"))
    if data["version"] != ss.VERSION:
        raise SystemExit(f"{ul.ITEMS} is {data['version']}, not {ss.VERSION}")
    items = [r for rows in data["sets"].values() for r in rows if r.get("light") and r.get("joint") is not None]
    if args.limit:
        items = items[:args.limit]
    sess = ff._sessions()
    need = defaultdict(list)
    for r in items:
        need[r["session"]].append(float(r["t_ms"]))
    tracks = {sid: ss.TrackIndex(sid, ts) for sid, ts in need.items()}
    for sid, ts in need.items():
        got = dict(sess(sid).crops(sorted(set(ts))))
        for r in items:
            if r["session"] == sid:
                r["_crop"] = got[float(r["t_ms"])]
    srcs = {sid: ability_sources(sid) for sid in need}
    from reticle import geometry
    captures = {sid: geometry.manifest(sid, ss.sem.STORE)["source"]["path"].replace("\\", "/") for sid in need}
    rows, draws = [], {}
    for i, r in enumerate(items):
        row, draw = measure(sess(r["session"]), r, tracks[r["session"]], srcs[r["session"]])
        rows.append(row)
        draws[id(row)] = draw
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(items)}", flush=True)
    bad = [r for r in rows if r["unexplained_n"] != r["stored_unexplained_n"]]
    for r in bad:
        print(f"NOT REPRODUCED {r['set']} {r['session']} {r['t_ms']}")
    parts = {"331": [r for r in rows if r["size"] == 331], "465": [r for r in rows if r["size"] == 465],
             "pooled": rows}
    res = {k: summarise(v) for k, v in parts.items() if v}
    for k, v in res.items():
        print(f"== {k}: {json.dumps(v)}")
    hits = Counter(n for r in rows for n in r["ability_names_hit_U"])
    print("abilities whose area meets unexplained px (1 s window, R=24):", dict(hits))
    OUT.mkdir(parents=True, exist_ok=True)
    sheets = {}
    for cause in ("residual", "halo"):
        p = OUT / f"sheet_{cause}.png"
        sheets[cause] = sheet(rows, draws, cause, captures, p)
        print("wrote", p)
    (OUT / "items.json").write_text(json.dumps({"version": VERSION, "unexplained_light": ul.VERSION,
                                                "scene_stack": ss.VERSION, "sheet_rule": SHEET_RULE,
                                                "halo_px": HALO_PX, "ability_r": ABILITY_R,
                                                "window_ms": WINDOW_MS, "persist_ms": PERSIST_MS,
                                                "summary": res, "ability_hits": dict(hits), "rows": rows,
                                                "sheets": sheets}, indent=1), encoding="utf-8")
    print("wrote", OUT / "items.json")
    if args.record and not args.limit:
        from reticle import metrics
        deps = {"prototype": VERSION, "unexplained_light": ul.VERSION, "scene_stack": ss.VERSION,
                "items": str(ul.ITEMS), "halo_px": HALO_PX, "ability_r": ABILITY_R, "window_ms": WINDOW_MS,
                "persist_ms": PERSIST_MS, "order": list(CAUSES)}
        for k, v in res.items():
            sids = sorted({r["session"] for r in parts[k]})
            metrics.record(SERIES, part=k, session="+".join(sids), values=v, deps=deps)
            print("recorded", k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
