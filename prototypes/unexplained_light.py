r"""Where scene-stack-0.3.0 reads lit floor no team cone reaches: a viewing sheet and two cause tests.

    .\.venv\Scripts\python.exe prototypes\unexplained_light.py [--record]

`scene_stack.py` (0.3.0) predicts the minimap floor lit where a team icon's
cone reaches it, and calls known floor that reads lit anyway UNEXPLAINED
LIGHT. It fires on nearly every fitted item. This tool shows the player the
whole widget round each such pixel, and tests two causes on all the fitted
items:

- LINGERING: the drawn light stays for a moment after a cone sweeps away.
  Earlier cones are the frame's team icons (`facing_fusion.team_icons`, the
  owner teardrop poses [owns:icon-pose]) at the cached frame nearest t-250 ms
  and t-500 ms (`EARLY_MS`; none when the nearest lies over `EARLY_TOL_MS`
  away). The player has not said whether light lingers.
- OFF-SCENE TEAMMATES: 0.3.0 casts the frame's team icons outside the scene,
  but `scene_stack.Light` casts only as far as the scene window's diagonal
  from each origin. Here they cast over the whole widget.

Every cone is `scene_stack.Light.cones` over the whole widget: the owner's
raycast (`cone.raycast`, [owns:viewcone]) cast once over 360 degrees from the
snapped origin and cut to the facing's wedge, against the baked `(map,
profile)` walls and floor (`team_vision.load_inputs`); session pixels only
show the widget. The unexplained pixels, the compared region and the
explained-dark control come from rebuilding each 0.3.0 scene
(`scene_stack.neighbourhood`, `RGBScene.full_images`) at the joint poses and
draw order stored in the store's `analysis/scene-light-20260929/items.json`;
the rebuild must reproduce the stored `unexplained_n` (P15). A cause is
tested against the CONTROL: compared known floor predicted unlit that reads
unlit. Lingering light predicts earlier cones cover unexplained pixels far
more often than they cover the control.

The player's two further candidates are beliefs, unverified: a teammate who
just died may light the floor for a moment
[domain:minimap/dead-teammate-light-belief], and the spike does not
[domain:minimap/spike-casts-no-light-belief]. Neither is tested here: no
death or spike reader joins this tool, so the sheet leaves them to the eye.

The sheet (`SHEET_RULE`, fixed before rendering): per widget size, in the
stacked and in the isolated items, the largest unexplained share and the item
nearest that group's median share; then the two items with the most
unexplained pixels not yet taken. Crop cache only, no decode, no store stream
writes; `--record` writes `metrics` series `unexplained_light`; the sheets
and per-item rows go to the store's `analysis/unexplained-light-20260929/`.
Not wired: nothing in `reticle/` reads it.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import math  # noqa: E402
import sys  # noqa: E402
from collections import defaultdict  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import facing_fusion as ff  # noqa: E402
import scene_stack as ss  # noqa: E402
from reticle.minimap import widget_scale  # noqa: E402

VERSION = "unexplained-light-0.1.0"
SERIES = "unexplained_light"
ITEMS = ss.sem.STORE / "analysis" / "scene-light-20260929" / "items.json"
OUT = ss.sem.STORE / "analysis" / "unexplained-light-20260929"
EARLY_MS = (250.0, 500.0)
EARLY_TOL_MS = 100.0       # a cached frame farther than this from t - dt is no earlier frame
SHEET_RULE = ("per widget size, in stacked and in isolated items: the largest unexplained share and the item "
              "nearest the group's median share; then the two items with the most unexplained px not yet taken")
ZOOM = {331: 3, 465: 2}

# BGR
CYAN, MAGENTA, WHITE = (255, 255, 0), (255, 0, 255), (255, 255, 255)
SCENE_CONE, OUT_CONE, EARLY_CONE = (0, 220, 255), (0, 140, 255), (80, 255, 80)
UNPOSED, ENEMY = (255, 120, 0), (60, 60, 255)


def size_of(crop) -> int:
    return int(crop.shape[1])


class WidgetLight:
    """`scene_stack.Light` over the whole widget: every cone reaches as far as the widget's diagonal."""

    def __init__(self, s, shape):
        h, w = shape
        self.light = ss.Light(s, (0, 0, w, h), [{"cls": "ally", "x0": 0.0, "y0": 0.0}], [], 1.0,
                              {"c_u": 0.0, "c_m": 0.0})
        self.shape = shape

    def cone(self, x, y, deg) -> np.ndarray:
        return self.light.cones(np.array([[x, y, deg]], np.float64))[0].cpu().numpy().reshape(self.shape)


def nearest_cached(s, t: float):
    ct = s.cache_t
    j = int(np.argmin(np.abs(ct - t)))
    return float(ct[j])


def crop_at(s, t: float):
    for _t, c in s.crops([t]):
        return c
    return None


def rebuild(s, r: dict, tracks) -> dict:
    """The 0.3.0 scene at the stored joint poses: full-widget masks of the compared region, the unexplained
    pixels and the explained-dark control, and the frame's other team icons."""
    crop = r["_crop"]
    sc = widget_scale(crop.shape[1])
    nb = ss.neighbourhood(s, crop, r, r["cls"], tracks, sc)
    team = ss.frame_team(s, r, sc)
    outside = ss.outside_icons(team, sc, nb["icons"])
    scene = ss.RGBScene(crop, s, nb["icons"], sc, ss.CAL, outside=outside, light_costs=ss.light_costs(sc))
    jg = r.get("joint_gains") or (0.0, 0.0)
    poses = {0: (r["joint_xy"][0], r["joint_xy"][1], r["joint"], jg[0], jg[1])}
    for i, p in enumerate(r.get("neighbour_poses") or [], start=1):
        poses[i] = tuple(p)
    order = list(r["order"])
    stats = scene.light_stats(order, poses)
    _P, _R, Wimg, Cimg = scene.full_images(order, poses, crop.shape[:2])
    h, w = crop.shape[:2]
    keep = np.zeros((h, w), bool)
    x0, y0, x1, y1 = scene.win
    keep[y0:y1, x0:x1] = scene.keep_np
    known = s.ref.known.astype(bool)
    comp = keep & (Wimg > 0.5) & known & (Cimg != 4)
    unex = comp & (Cimg == 2)
    ctrl = comp & (Cimg == 0)
    return {"scene": scene, "poses": poses, "icons": nb["icons"], "outside": outside, "stats": stats,
            "keep": keep, "comp": comp, "unex": unex, "ctrl": ctrl, "sc": sc}


def measure(s, r: dict, tracks) -> dict:
    b = rebuild(s, r, tracks)
    crop = r["_crop"]
    shape = crop.shape[:2]
    wl = WidgetLight(s, shape)
    scene_cones = []
    for i, ic in enumerate(b["icons"]):
        p = b["poses"].get(i)
        if ic["cls"] == "enemy" or p is None:
            continue
        scene_cones.append((p[0], p[1], p[2], wl.cone(p[0], p[1], p[2])))
    out_cones, unposed = [], []
    for o in b["outside"]:
        if o.get("deg") is None:
            unposed.append((o["x"], o["y"]))
        else:
            out_cones.append((o["x"], o["y"], o["deg"], wl.cone(o["x"], o["y"], o["deg"])))
    off = np.zeros(shape, bool)
    for *_xyz, m in out_cones:
        off |= m
    early = {}
    for dt in EARLY_MS:
        te = nearest_cached(s, float(r["t_ms"]) - dt)
        if abs(te - (float(r["t_ms"]) - dt)) > EARLY_TOL_MS:
            early[dt] = None
            continue
        ce = crop_at(s, te)
        icons = ff.team_icons(s, ce, b["sc"])
        cones = [(ic["x"], ic["y"], ic["deg"], wl.cone(ic["x"], ic["y"], ic["deg"])) for ic in icons
                 if ic["deg"] is not None]
        cov = np.zeros(shape, bool)
        for *_xyz, m in cones:
            cov |= m
        early[dt] = {"t_ms": te, "crop": ce, "cones": cones,
                     "unposed": [(ic["x"], ic["y"]) for ic in icons if ic["deg"] is None], "cov": cov}
    either = np.zeros(shape, bool)
    for e in early.values():
        if e is not None:
            either |= e["cov"]
    U, C = b["unex"], b["ctrl"]
    nU, nC = int(U.sum()), int(C.sum())

    def share(mask, base, n):
        return None if n == 0 else round(float((mask & base).sum()) / n, 4)
    row = {
        "key": r.get("key"), "set": r["set"], "session": r["session"], "t_ms": float(r["t_ms"]),
        "size": size_of(crop), "stacked": bool(r["stacked"]),
        "stored_unexplained_n": r["light"]["unexplained_n"], "stored_floor_n": r["light"]["floor_n"],
        "rebuilt": b["stats"], "floor_n": int(b["comp"].sum()), "unexplained_n": nU, "control_n": nC,
        "unexplained_share": round(nU / max(int(b["comp"].sum()), 1), 4),
        "early_t_ms": {str(int(dt)): (None if e is None else e["t_ms"]) for dt, e in early.items()},
        "n_outside_posed": len(out_cones), "n_outside_unposed": len(unposed),
        "n_outside_reach": sum(bool((m & b["comp"]).any()) for *_xyz, m in out_cones),
        "U_early_either": int((U & either).sum()), "C_early_either": int((C & either).sum()),
        "U_off": int((U & off).sum()), "C_off": int((C & off).sum()),
        "U_early_or_off": int((U & (either | off)).sum()),
    }
    for dt, e in early.items():
        k = str(int(dt))
        row[f"U_early_{k}"] = None if e is None else int((U & e["cov"]).sum())
        row[f"C_early_{k}"] = None if e is None else int((C & e["cov"]).sum())
    row["early_share"] = share(either, U, nU)
    row["early_share_control"] = share(either, C, nC)
    row["off_share"] = share(off, U, nU)
    row["off_share_control"] = share(off, C, nC)
    draw = {"crop": crop, "b": b, "scene_cones": scene_cones, "out_cones": out_cones, "unposed": unposed,
            "early": early, "either": either, "off": off}
    return row, draw


# ---------------------------------------------------------------- drawing

def _up(img, z):
    return cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)


def _outline(big, mask, z, col, th=1):
    if not mask.any():
        return
    m = _up(mask.astype(np.uint8) * 255, z)
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(big, cs, -1, col, th)


def _paint(big, mask, z, col):
    big[_up(mask.astype(np.uint8), z) > 0] = col


def _icon(big, x, y, deg, z, col):
    o = (int((x + 0.5) * z), int((y + 0.5) * z))
    cv2.circle(big, o, int(4 * z), col, 1)
    if deg is not None:
        a = math.radians(deg)
        cv2.line(big, o, (int(o[0] + 9 * z * math.cos(a)), int(o[1] + 9 * z * math.sin(a))), col, 1)


def panel(crop, z, comp_keep, U, cov, cones, unposed, enemies=(), cone_col=EARLY_CONE, out_cones=()):
    """The widget at `z`, cones outlined, the compared region white, U painted magenta where `cov` covers it
    and cyan elsewhere."""
    big = _up(crop, z)
    _paint(big, U & ~cov, z, CYAN)
    _paint(big, U & cov, z, MAGENTA)
    _outline(big, comp_keep, z, WHITE, 1)
    for x, y, deg, m in cones:
        _outline(big, m, z, cone_col, 2)
        _icon(big, x, y, deg, z, cone_col)
    for x, y, deg, m in out_cones:
        _outline(big, m, z, OUT_CONE, 2)
        _icon(big, x, y, deg, z, OUT_CONE)
    for x, y in unposed:
        _icon(big, x, y, None, z, UNPOSED)
    for x, y in enemies:
        _icon(big, x, y, None, z, ENEMY)
    return big


def caption(row, capture: str) -> list[str]:
    e = row["early_t_ms"]
    dts = ", ".join(f"-{k} ms at {(v - row['t_ms']):+.0f}" if v is not None else f"-{k} ms none"
                    for k, v in e.items())
    f = lambda v: "-" if v is None else f"{v:.2f}"  # noqa: E731
    return [
        f"{row['session']}  {capture}  t {row['t_ms'] / 1000:.2f} s  widget {row['size']} px  {row['set']}"
        f"  {'STACKED' if row['stacked'] else 'isolated'}",
        f"unexplained {row['unexplained_n']} px = {row['unexplained_share']:.3f} of {row['floor_n']} compared px;"
        f"  explained by an earlier cone (magenta) {f(row['early_share'])} (control {f(row['early_share_control'])});"
        f"  earlier frames: {dts}",
        f"team icons outside the scene: {row['n_outside_posed']} posed, {row['n_outside_unposed']} unread;"
        f" {row['n_outside_reach']} with a cone reaching the compared region; their cones explain"
        f" {f(row['off_share'])} (control {f(row['off_share_control'])})",
    ]


def render_row(row, draw, capture: str) -> np.ndarray:
    z = ZOOM.get(row["size"], 2)
    b = draw["b"]
    U = b["unex"]
    enemies = [(ic["x0"], ic["y0"]) for ic in b["icons"] if ic["cls"] == "enemy"]
    cones_t = [(x, y, d, m) for x, y, d, m in draw["scene_cones"]]
    panels = [panel(draw["crop"], z, b["keep"], U, draw["either"], cones_t, draw["unposed"], enemies,
                    cone_col=SCENE_CONE, out_cones=draw["out_cones"])]
    titles = [f"t: scene cones (fitted) yellow, other team icons' cones orange; cyan unexplained, magenta"
              f" covered by an earlier cone"]
    for dt in EARLY_MS:
        e = draw["early"][dt]
        if e is None:
            blank = np.zeros_like(panels[0])
            panels.append(blank)
            titles.append(f"t-{int(dt)} ms: no cached frame within {int(EARLY_TOL_MS)} ms")
            continue
        panels.append(panel(e["crop"], z, b["keep"], U, e["cov"], e["cones"], e["unposed"]))
        titles.append(f"t{e['t_ms'] - row['t_ms']:+.0f} ms: team cones (teardrop) green; magenta = unexplained at t"
                      f" that these cones cover")
    tiles = []
    for p, ttl in zip(panels, titles):
        bar = np.zeros((22, p.shape[1], 3), np.uint8)
        cv2.putText(bar, ttl, (4, 16), 0, 0.45, WHITE, 1)
        tiles.append(np.vstack([bar, p]))
    body = np.hstack([np.pad(t, ((0, 0), (0, 6), (0, 0)), constant_values=40) for t in tiles])
    lines = caption(row, capture)
    head = np.zeros((20 * len(lines) + 8, body.shape[1], 3), np.uint8)
    for k, s_ in enumerate(lines):
        cv2.putText(head, s_, (4, 18 + 20 * k), 0, 0.55, WHITE, 1)
    return np.vstack([head, body, np.full((8, body.shape[1], 3), 90, np.uint8)])


def legend(width: int) -> np.ndarray:
    bar = np.zeros((34, width, 3), np.uint8)
    cv2.putText(bar, f"{VERSION}. Whole minimap widget, nearest-neighbour upscale. White outline: the compared "
                f"region. Cyan: unexplained light at t. Magenta: unexplained at t that an earlier team cone covered. "
                f"Yellow: scene team cones (fitted pose). Orange: other team icons' cones (teardrop, whole widget). "
                f"Blue ring: unread team icon. Red ring: enemy.", (4, 22), 0, 0.5, WHITE, 1)
    return bar


# ---------------------------------------------------------------- selection and summary

def select(rows: list[dict]) -> list[dict]:
    """`SHEET_RULE`, over the per-item rows; fixed before any sheet is rendered."""
    picked = []
    for size in sorted({r["size"] for r in rows}):
        sub = [r for r in rows if r["size"] == size]
        take = []
        for stk in (True, False):
            g = sorted([r for r in sub if r["stacked"] == stk], key=lambda r: r["t_ms"])
            if not g:
                continue
            take.append(max(g, key=lambda r: r["unexplained_share"]))
            med = float(np.median([r["unexplained_share"] for r in g]))
            rest = [r for r in g if r not in take]
            if rest:
                take.append(min(rest, key=lambda r: abs(r["unexplained_share"] - med)))
        rest = sorted([r for r in sub if r not in take], key=lambda r: -r["unexplained_n"])
        take += rest[:6 - len(take)]
        picked += take
    return picked


def summarise(rows: list[dict]) -> dict:
    U = sum(r["unexplained_n"] for r in rows)
    C = sum(r["control_n"] for r in rows)
    ue, ce = sum(r["U_early_either"] for r in rows), sum(r["C_early_either"] for r in rows)
    uo, co = sum(r["U_off"] for r in rows), sum(r["C_off"] for r in rows)
    out = {"n": len(rows), "reproduced_n": sum(r["unexplained_n"] == r["stored_unexplained_n"] for r in rows),
           "unexplained_share_median": round(float(np.median([r["unexplained_share"] for r in rows])), 4),
           "unexplained_px": U, "control_px": C,
           "early_share": round(ue / max(U, 1), 4), "early_share_control": round(ce / max(C, 1), 4),
           "early_ratio": round((ue / max(U, 1)) / max(ce / max(C, 1), 1e-9), 3),
           "off_share": round(uo / max(U, 1), 4), "off_share_control": round(co / max(C, 1), 4),
           "early_or_off_share": round(sum(r["U_early_or_off"] for r in rows) / max(U, 1), 4),
           "items_outside_reach": sum(r["n_outside_reach"] > 0 for r in rows),
           "items_no_early_frame": sum(any(v is None for v in r["early_t_ms"].values()) for r in rows)}
    for dt in EARLY_MS:
        k = str(int(dt))
        have = [r for r in rows if r[f"U_early_{k}"] is not None]
        uu, cc = sum(r["unexplained_n"] for r in have), sum(r["control_n"] for r in have)
        out[f"early_{k}_share"] = round(sum(r[f"U_early_{k}"] for r in have) / max(uu, 1), 4)
        out[f"early_{k}_share_control"] = round(sum(r[f"C_early_{k}"] for r in have) / max(cc, 1), 4)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--record", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="first N items (a smoke run; never recorded)")
    args = ap.parse_args(argv)
    ss._idle()
    ss.CAL = json.loads(ss.CAL_PATH.read_text(encoding="utf-8"))
    ss.LCAL = json.loads(ss.LIGHT_CAL_PATH.read_text(encoding="utf-8"))
    data = json.loads(ITEMS.read_text(encoding="utf-8"))
    if data["version"] != ss.VERSION:
        raise SystemExit(f"{ITEMS} is {data['version']}, not {ss.VERSION}")
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
    from reticle import geometry
    captures = {sid: geometry.manifest(sid, ss.sem.STORE)["source"]["path"].replace("\\", "/") for sid in need}
    rows, draws = [], {}
    for i, r in enumerate(items):
        row, draw = measure(sess(r["session"]), r, tracks[r["session"]])
        rows.append(row)
        draws[id(row)] = draw
        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(items)}", flush=True)
    bad = [r for r in rows if r["unexplained_n"] != r["stored_unexplained_n"]
           or r["rebuilt"]["unexplained_n"] != r["stored_unexplained_n"]]
    for r in bad:
        print(f"NOT REPRODUCED {r['set']} {r['session']} {r['t_ms']}: stored {r['stored_unexplained_n']} "
              f"rebuilt {r['rebuilt']['unexplained_n']} mask {r['unexplained_n']}")
    parts = {"331": [r for r in rows if r["size"] == 331], "465": [r for r in rows if r["size"] == 465],
             "pooled": rows}
    res = {k: summarise(v) for k, v in parts.items() if v}
    for k, v in res.items():
        print(f"== {k}: {json.dumps(v)}")
    OUT.mkdir(parents=True, exist_ok=True)
    picked = select(rows)
    paths = []
    for size in sorted({r["size"] for r in picked}):
        tiles = [render_row(r, draws[id(r)], captures[r["session"]]) for r in picked if r["size"] == size]
        W = max(t.shape[1] for t in tiles)
        tiles = [cv2.copyMakeBorder(t, 0, 0, 0, W - t.shape[1], cv2.BORDER_CONSTANT) for t in tiles]
        p = OUT / f"sheet_{size}.png"
        cv2.imwrite(str(p), np.vstack([legend(W)] + tiles))
        paths.append(p)
        print("wrote", p)
    (OUT / "items.json").write_text(json.dumps({"version": VERSION, "scene_stack": ss.VERSION,
                                                "sheet_rule": SHEET_RULE, "summary": res, "rows": rows,
                                                "sheet": [(r["session"], r["t_ms"]) for r in picked]},
                                               indent=1), encoding="utf-8")
    print("wrote", OUT / "items.json")
    if args.record and not args.limit:
        from reticle import metrics
        deps = {"prototype": VERSION, "scene_stack": ss.VERSION, "items": str(ITEMS), "early_ms": list(EARLY_MS),
                "early_tol_ms": EARLY_TOL_MS, "light_rays": ss.LIGHT_RAYS, "cast": "whole widget",
                "early_poses": "facing_fusion.team_icons teardrop"}
        for k, v in res.items():
            sids = sorted({r["session"] for r in parts[k]})
            metrics.record(SERIES, part=k, session="+".join(sids), values=v, deps=deps)
            print("recorded", k)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
