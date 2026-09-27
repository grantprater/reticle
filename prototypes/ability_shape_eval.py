r"""Score parametric minimap ability shapes against the player's marks.

    .\.venv\Scripts\python.exe prototypes\ability_shape_eval.py [--png DIR]

Why. `entity_mining_statistical` (a disc) and `beam_mining_statistical` (a
beam from the caster) fitted shapes on two demo clips from video, scored by
their own consistency. The player has since traced the shapes on match
sessions (`label_tray_objects.py`: points on the inner edge of Regrowth and
Recon Bolt, points along each Hunter's Fury blast), so the fits can now be
scored against ground truth, on the 15 Hz minimap crop cache (no decode).

The models are `reticle.ability_shapes`, imported rather than copied, so what
is scored is what ships. They were fixed before any mark was read (predictions
`ability-shape-fit`); the module's docstring states them. `SHAPE_COLOUR=ally`
scores the minimap owner's stricter ally key in place of the teal weight;
`SHAPE_SUPPORT=widget` drops the map's art footprint, so no beam is placed.

Truth. Per labelled panel: a least-squares circle through the Regrowth marks;
for Recon Bolt a RANSAC circle (4 px), because each panel also carries one mark
on the bolt itself; a principal-axis line through the Fury marks. The player
traced inside the drawn ring, 0-15 px (outcome of `ability-shape-fit`), so the
marks are a centre and angle truth, not a radius truth.

Specificity. Each labelled cast's panel 1.0 s before the drop has no object
yet; the fit must not be found there.
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle import ability_shapes as S_  # noqa: E402
from reticle import geometry, minimap  # noqa: E402
from reticle.cli import _date_of  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
SHAPES = {"Regrowth": "ring_self", "Recon Bolt": "ring_free", "Hunter's Fury": "beam"}


def colour_switch():
    """`SHAPE_COLOUR=ally` scores `minimap.ally_mask` in place of the teal weight."""
    if os.environ.get("SHAPE_COLOUR") == "ally":
        S_.teal = lambda crop: minimap.ally_mask(crop).astype(np.float32)


# ---------------------------------------------------------------- truth

def lsq_circle(pts):
    x, y = pts[:, 0], pts[:, 1]
    c, *_ = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x * x + y * y, rcond=None)
    return c[0], c[1], float(np.sqrt(c[2] + c[0] ** 2 + c[1] ** 2))


def ransac_circle(pts, tol=4.0):
    best = None
    for tri in itertools.combinations(range(len(pts)), 3):
        try:
            cx, cy, r = lsq_circle(pts[list(tri)])
        except np.linalg.LinAlgError:
            continue
        if not np.isfinite(r) or r > 150:
            continue
        inl = np.abs(np.hypot(pts[:, 0] - cx, pts[:, 1] - cy) - r) < tol
        if best is None or inl.sum() > best.sum():
            best = inl
    return lsq_circle(pts[best])


def axis(pts):
    m = pts.mean(0)
    _, _, vt = np.linalg.svd(pts - m)
    return m, vt[0]


def ang_err(a, b):
    d = abs(a - b) % 180.0
    return min(d, 180.0 - d)


# ---------------------------------------------------------------- data

def labels() -> dict:
    last = {}
    for p in (STORE.root / "labels" / "tray_object").glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                last[r["key"]] = r
    return last


class Session:
    def __init__(self, sid):
        man = STORE.read_manifest(sid)
        self.cache, _ = RoiCache.load(STORE.root, man, get_profile(man["source_profile"]), "minimap")
        self.rect = self.cache.rect_of("minimap")
        self.static = geometry.reference_static(sid)
        x0, y0, x1, y1 = self.rect
        self.support = (None if os.environ.get("SHAPE_SUPPORT") == "widget" else
                        geometry.footprint(sid, STORE.root, dilate=S_.SUPPORT_DILATE,
                                           shape=(y1 - y0, x1 - x0)))
        mm = STORE.read_minimap(sid, _date_of(man)).to_pydict()
        self.mt = np.asarray(mm["t_ms"], float)
        self.sx, self.sy = mm["self_x"], mm["self_y"]

    def crop(self, t):
        x0, y0, x1, y1 = self.rect
        s = next(iter(self.cache.samples([t], rois=["minimap"])), None)
        return (None, None) if s is None else (s.frame[y0:y1, x0:x1], s.t_ms)

    def self_at(self, t):
        i = int(np.abs(self.mt - t).argmin())
        if abs(self.mt[i] - t) > 100 or self.sx[i] is None:
            return None
        return float(self.sx[i]), float(self.sy[i])


def fit_for(kind, img, me, support=None):
    """The production observation, in the field names the scoring reads."""
    ability = {"ring_self": "Regrowth", "ring_free": "Recon Bolt", "beam": "Hunter's Fury"}[kind]
    f = S_.fit_shape(img, ability, me, support)
    if "theta_deg" in f:
        f["theta"], f["p0"], f["p1"] = f["theta_deg"], (f["x0"], f["y0"]), (f["x1"], f["y1"])
    if f.get("reason") and not f.get("found") and "score" not in f:
        f["refused"] = f["reason"]
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--png", type=Path)
    ap.add_argument("--null", action="store_true",
                    help="score live-phase crops away from the player's casts instead")
    a = ap.parse_args()
    if a.null:
        colour_switch()
        res = null_sample()
        rows_out = os.environ.get("SHAPE_ROWS")
        if rows_out:
            Path(rows_out).write_text(json.dumps(res["rows"], indent=0), encoding="utf-8")
        print(json.dumps({k: res[k] for k in ("ring_summary", "beam_summary")}, indent=1))
        return 0
    colour_switch()
    labs = [r for r in labels().values() if r.get("ability") in SHAPES and r.get("class") == "object"]
    sessions, rows = {}, []
    for r in sorted(labs, key=lambda r: r["key"]):
        sid, kind = r["session_id"], SHAPES[r["ability"]]
        S = sessions.setdefault(sid, Session(sid))
        by = defaultdict(list)
        for m in r["marks"]:
            by[m["panel"]].append(m)
        t_drop = float(r["key"].split(":")[1])
        img, _ = S.crop(t_drop - 1000.0)
        pre = (fit_for(kind, img, S.self_at(t_drop - 1000.0), S.support) if img is not None
               else {"refused": "no_crop"})
        rows.append({"key": r["key"], "ability": r["ability"], "panel": "pre", "fit": pre})
        for pan, ms in sorted(by.items()):
            pts = np.array([[m["x"], m["y"]] for m in ms], float)
            if pan == 0 or (kind != "beam" and len(pts) < 5) or len(pts) < 3:
                continue
            t = ms[0]["t_ms"]
            img, _ = S.crop(t)
            me = S.self_at(t)
            fit = fit_for(kind, img, me, S.support) if img is not None else {"refused": "no_crop"}
            row = {"key": r["key"], "ability": r["ability"], "panel": pan, "fit": fit,
                   "self": me}
            if kind == "beam":
                m0, d = axis(pts)
                row["truth_theta"] = float(np.degrees(np.arctan2(d[1], d[0])) % 180)
                row["self_perp"] = (None if me is None else
                                    float(abs(d[0] * (me[1] - m0[1]) - d[1] * (me[0] - m0[0]))))
                if "theta" in fit:
                    row["angle_err"] = ang_err(fit["theta"], row["truth_theta"])
                    q = np.array(fit["p0"]), np.array(fit["p1"])
                    u = (q[1] - q[0]) / max(np.hypot(*(q[1] - q[0])), 1e-6)
                    row["mark_perp_max"] = float(max(abs(u[0] * (p[1] - q[0][1]) - u[1] * (p[0] - q[0][0]))
                                                     for p in pts))
            else:
                cx, cy, rr = lsq_circle(pts) if kind == "ring_self" else ransac_circle(pts)
                row["truth"] = (float(cx), float(cy), rr)
                if fit.get("cx") is not None:
                    row["centre_err"] = float(np.hypot(fit["cx"] - cx, fit["cy"] - cy))
                    row["radius_err"] = float(fit["r"] - rr)
            rows.append(row)
            if a.png:
                a.png.mkdir(parents=True, exist_ok=True)
                v = img.copy()
                for p in pts:
                    cv2.circle(v, (int(p[0]), int(p[1])), 2, (255, 0, 255), -1)
                if kind != "beam" and fit.get("cx") is not None:
                    cv2.circle(v, (fit["cx"], fit["cy"]), int(round(fit["r"])), (0, 255, 255), 1)
                elif "p0" in fit:
                    cv2.line(v, tuple(int(c) for c in fit["p0"]), tuple(int(c) for c in fit["p1"]),
                             (0, 255, 255), 1)
                cv2.imwrite(str(a.png / f"{r['key'].replace(':', '_')}_p{pan}.png"),
                            cv2.resize(v, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST))
    print(json.dumps(summary(rows), indent=1, default=str))
    out = Path(os.environ.get("SHAPE_ROWS", "")) if os.environ.get("SHAPE_ROWS") else None
    if out:
        out.write_text(json.dumps(rows, default=str, indent=0), encoding="utf-8")
    return 0


def null_sample(per_session: int = 10, gap_s: float = 10.0) -> dict:
    """Ring and beam statistics on live-phase crops away from the player's casts.

    Sessions: the player is Sova or Skye (the lineup owner's stored answer).
    Times: hashed, in `gametime`'s round_live or post_plant, at least `gap_s` from any
    of the player's tray drops in a slot that draws a shape. Teammates' own
    abilities stay in, so the tail is what the reader meets at a cast time.
    """
    import hashlib
    import pickle

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import tray_suspect_reasons as tsr
    from reticle import gametime, stalls

    slots = {"Sova": ("E", "X"), "Skye": ("C",)}
    out = {"ring": [], "beam": [], "rows": []}
    for pk in sorted(tsr.WORK.glob("*.pkl")):
        sid = pk.stem
        lp = STORE.root / "lineups" / f"{sid}.json"
        agent = ((json.loads(lp.read_text(encoding="utf-8")).get("player") or {}).get("agent")
                 if lp.exists() else None)
        if agent not in slots:
            continue
        with open(pk, "rb") as f:
            d = pickle.load(f)
        drops = [r["t"] * 1000.0 for r in tsr.drops(d) if r["slot"] in slots[agent]]
        man = STORE.read_manifest(sid)
        date = _date_of(man)
        gt = gametime.build_session_gametime(
            sid, STORE.read_hud(sid, date), STORE.read_rounds(sid, date).to_pylist(),
            stall_list=stalls.for_session(STORE, sid, date))
        S = Session(sid)
        ts = [float(t) for t in S.cache.t_ms]
        picked, k = [], 0
        while len(picked) < per_session and k < 5000:
            h = int(hashlib.sha1(f"{sid}:{k}".encode()).hexdigest()[:8], 16)
            k += 1
            t = ts[h % len(ts)]
            if gt.game_time_at(t).phase not in ("round_live", "post_plant") or any(abs(t - x) < gap_s * 1000 for x in drops):
                continue
            picked.append(t)
        for t in sorted(picked):
            img, _ = S.crop(t)
            if img is None:
                continue
            me = S.self_at(t)
            tl = S_.teal(img)
            R, mask = S_.widget(img.shape)
            ring = S_.fit_ring(tl, mask, R, step=3)["score"]
            if me is not None:
                ring = max(ring, S_.fit_ring(tl, mask, R, me, S_.RING_SEED_HALF * R)["score"])
            # Only a beam the reader could accept counts: one whose run is on the map.
            placed = lambda f: (S.support is None or
                                S_.on_map(f, S.support) >= S_.BEAM_ON_MAP)
            beam = -1.0
            if me is not None:
                f = S_.fit_beam(tl, mask, me[0], me[1], R)
                beam = f["score"] if placed(f) else -1.0
            if S_.longest_segment(tl, mask, R, S.support) is not None:
                wide = S_.fit_shape(img, "Hunter's Fury", None, S.support)
                if wide.get("score") is not None and wide.get("on_map", 1.0) >= S_.BEAM_ON_MAP:
                    beam = max(beam, wide["score"])
            out["ring"].append(ring)
            out["beam"].append(beam)
            out["rows"].append({"sid": sid, "agent": agent, "t_ms": t, "ring": ring, "beam": beam})
        print(sid, agent, len(picked), flush=True)
    for k in ("ring", "beam"):
        v = np.array(out[k])
        out[k + "_summary"] = {"n": len(v), "max": float(v.max()), "p99": float(np.percentile(v, 99)),
                               "p90": float(np.percentile(v, 90)), "median": float(np.median(v))}
    return out


def summary(rows) -> dict:
    post = [r for r in rows if r["panel"] != "pre"]
    reg = [r for r in post if r["ability"] == "Regrowth"]
    rec = [r for r in post if r["ability"] == "Recon Bolt"]
    fury = [r for r in post if r["ability"] == "Hunter's Fury"]
    ok_ring = lambda r: r.get("centre_err", 99) <= 5 and abs(r.get("radius_err", 99)) <= 4
    on = [r for r in fury if r["self_perp"] is not None and r["self_perp"] <= 10]
    off = [r for r in fury if r not in on]
    pre = [r for r in rows if r["panel"] == "pre"]
    real_pre = [r for r in pre if "no_crop" not in (r["fit"].get("reason"), r["fit"].get("refused"))]
    return {
        "C1_regrowth": f"{sum(map(ok_ring, reg))}/{len(reg)}",
        "C1_centre_only": f"{sum(r.get('centre_err', 99) <= 5 for r in reg)}/{len(reg)}",
        "C2_recon": f"{sum(map(ok_ring, rec))}/{len(rec)}",
        "C2_centre_only": f"{sum(r.get('centre_err', 99) <= 5 for r in rec)}/{len(rec)}",
        "found_post": {a: f"{sum(bool(r['fit'].get('found')) for r in g)}/{len(g)}"
                       for a, g in (("Regrowth", reg), ("Recon Bolt", rec), ("Hunter's Fury", fury))},
        "B1_fury_self_on_line": f"{sum(r.get('angle_err', 99) <= 3 for r in on)}/{len(on)}",
        "B2_fury_self_off": {
            "seeded_below": f"{sum(r['fit'].get('path') == 'widened' for r in off)}/{len(off)}",
            "angle_ok": f"{sum(r.get('angle_err', 99) <= 3 for r in off)}/{len(off)}"},
        "S1_pre_not_found": f"{sum(not r['fit'].get('found') for r in real_pre)}/{len(real_pre)}",
        "pre_no_crop": len(pre) - len(real_pre),
        "panels": [{k: (round(v, 2) if isinstance(v, float) else v) for k, v in
                    {"key": r["key"], "p": r["panel"], "score": r["fit"].get("score"),
                     "path": r["fit"].get("path"), "c_err": r.get("centre_err"),
                     "r_err": r.get("radius_err"), "a_err": r.get("angle_err"),
                     "self_perp": r.get("self_perp"), "perp_max": r.get("mark_perp_max"),
                     "len": r["fit"].get("length"), "refused": r["fit"].get("refused"),
                     "found": r["fit"].get("found"), "r": r["fit"].get("r"),
                     "seeded": r["fit"].get("seeded")}.items()}
                   for r in rows],
    }


if __name__ == "__main__":
    if os.name == "nt":                       # idle priority: the user's scans come first
        import ctypes
        ctypes.windll.kernel32.SetPriorityClass(ctypes.windll.kernel32.GetCurrentProcess(), 0x40)
    else:
        os.nice(19)
    raise SystemExit(main())
