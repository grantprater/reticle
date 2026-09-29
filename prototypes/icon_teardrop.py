r"""Read an ally's or an enemy's minimap icon as a teardrop: its centre and facing.

    .\.venv\Scripts\python.exe prototypes\icon_teardrop.py --calibrate ally|enemy
    .\.venv\Scripts\python.exe prototypes\icon_teardrop.py --stats [--jitter]
    .\.venv\Scripts\python.exe prototypes\icon_teardrop.py --sheet ally|enemy PATH

`teardrop_tip.py` reads the self icon as a shape: a ring round the portrait
plus a filled lobe whose edges are tangent to the ring and meet at the apex,
scored by normalised correlation against a continuous colour, with no
threshold. Against the player's labels on Lotus it read the self facing to a
median 2.2 degrees where the ring fit (`minimap.fit_ring` plus `_facing`)
flipped half the time. Teammates and enemies wear the same teardrop in other
colours, and the ally channel reads its bearing with the same ring fit.

**What changes per class** is the colour key and the three radii, nothing else.
The contact sheets of 2026-09-28 (Lotus 5822b6646448 and Ascent a06f04a0059f)
show the ally teardrop as a 1-2 px teal ring plus a filled teal lobe, the size
of the self glyph; the enemy's is a thinner red ring and lobe, slightly
smaller. The keys, ramped like `teardrop_tip.yellowness`:

    ally    min(G, B) - R, off where B exceeds G (the blue death X is not teal)
    enemy   R - max(G, B)

Measured on keyed icon pixels over 80 frames per session, the ally key's
median is 74-76 and the enemy key's 70-87, both 0 on the floor beside them.

**The fit** is `teardrop_tip.fit` with the class's key and radii, started from
the class's detector: `minimap.ally_icons` for allies, `minimap.icons` over the
enemy red key with the enemy ring's gates (`minimap_ring_fit`) for enemies.
It refuses, with a reason, rather than guess:

    low_ncc           the silhouette explains too little of the colour
    ambiguous_facing  a facing 90 degrees or more from the best scores within
                      `min_margin` of it, so the lobe is not seen
    no_ring           under `min_ring` of the ring away from the lobe is keyed:
                      a spawn barrier or a red map fill, not an icon
    no_key            no keyed pixel near the detector's centre

**The constants** are one widget size's geometry, fitted by `--calibrate` on
held-out minutes (`held_out`) that the labeller and the jitter never draw
from. `widget_scale` is not handled.

It reads the minimap crop cache only, decodes no video and writes nothing to
the store. `label_icon_facing.py` asks the player; `icon_facing_eval.py`
scores both readers against the answers.
"""
from __future__ import annotations

import argparse
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import teardrop_tip as tt  # noqa: E402
from reticle import minimap  # noqa: E402
# `teardrop_tip` 0.2.0 moved its correlation to the promoted reader, which owns it.
from reticle.teardrop import _correlation  # noqa: E402

VERSION = "icon-teardrop-0.1.0"
LOTUS, ASCENT = "5822b6646448", "a06f04a0059f"
SESSIONS = (LOTUS, ASCENT)
CAL_EVERY_MIN = 4             # minute m is held out for calibration when m % 4 == 3
MARGIN_DEG = 5.0              # facing grid for the ambiguity margin


def tealness(crop: np.ndarray) -> np.ndarray:
    """How teal each pixel is, in [0, 1]: min(G, B) - R, ramped over 10..60,
    faded out where B exceeds G by more than 10 (the blue death X, the blue
    ability glyphs). Keyed ally pixels sit at G - B of 20 to 50."""
    c = crop.astype(np.float32)
    b, g, r = c[..., 0], c[..., 1], c[..., 2]
    y = np.clip((np.minimum(g, b) - r - 10.0) / 50.0, 0.0, 1.0)
    return y * np.clip((g - b + 30.0) / 20.0, 0.0, 1.0)


def redness(crop: np.ndarray) -> np.ndarray:
    """How red each pixel is, in [0, 1]: R - max(G, B), ramped over 15..65."""
    c = crop.astype(np.float32)
    y = c[..., 2] - np.maximum(c[..., 0], c[..., 1])
    return np.clip((y - 15.0) / 50.0, 0.0, 1.0)


@dataclass(frozen=True)
class IconClass:
    name: str
    key: Callable[[np.ndarray], np.ndarray]
    r_in: float
    r_out: float
    L: float
    min_ncc: float
    min_margin: float
    min_ring: float


# The self row is teardrop_tip's, unchanged. The ally and enemy rows are the
# `--calibrate` plateau on held-out minutes of both sessions; see the comments.
CLASSES = {
    "self": IconClass("self", tt.yellowness, tt.R_IN, tt.R_OUT, tt.L, tt.MIN_NCC, 0.0, 0.0),
    # `--calibrate ally --n 30`: 100 detections of held-out minutes (48 Lotus,
    # 52 Ascent) that the provisional self geometry fitted at NCC >= 0.4 (the
    # read gate came later); mean NCC 0.766 at these values, a plateau over
    # ring width 1.5-2 and L 18-20 (0.760-0.766) at r_out 10.5; the best at
    # r_out 10 and 11 is 0.757 and 0.760, at 9.5 0.727.
    "ally": IconClass("ally", tealness, 8.5, 10.5, 19.0, 0.5, 0.05, 0.0),
    # `--calibrate enemy --n 200`: 53 read detections (23 Lotus, 30 Ascent);
    # mean NCC 0.741 at these values, a ridge along r_in 7-7.5 for r_out
    # 10.5-11 (0.741-0.742) and L 18-19. The red ring reads thicker than the
    # teal one: the portrait's rim is dark red.
    "enemy": IconClass("enemy", redness, 7.5, 10.5, 18.0, 0.5, 0.05, 0.4),
}


def held_out(t_ms: float) -> bool:
    """True in the minutes `--calibrate` fits on; nothing else draws from them."""
    return int(t_ms // 60000) % CAL_EVERY_MIN == CAL_EVERY_MIN - 1


def detections(crop: np.ndarray, cls: str, s) -> list[dict]:
    """The class's own detector: the ring fit whose facing the teardrop is scored against.

    Allies: `minimap.ally_icons` as `team_vision` calls it (bearing refused is
    kept). Enemies: `minimap.icons` over the enemy red key with the enemy
    ring's gates, `minimap_ring_fit.COV_MIN` and `INNER_RED_MAX`, and the
    slab support rule. Self: `teardrop_tip.self_start`.
    """
    if cls == "ally":
        return minimap.ally_icons(crop, s.floor, require_facing=False,
                                  support=s.inputs.slab, static=s.inputs.static)
    if cls == "enemy":
        import minimap_ring_fit as mrf
        from minimap_icons import red_mask
        return minimap.icons(red_mask(crop), crop, s.floor, cov_min=mrf.COV_MIN,
                             inner_max=mrf.INNER_RED_MAX, require_facing=False,
                             support=s.inputs.slab, seed="centroid")
    d = tt.self_start(crop, s.floor)
    return [] if d is None else [d]


def _window(key: np.ndarray, cx0: float, cy0: float, reach: float):
    h, w = key.shape
    x0, x1 = max(0, int(cx0 - reach)), min(w, int(cx0 + reach) + 1)
    y0, y1 = max(0, int(cy0 - reach)), min(h, int(cy0 + reach) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    keep = np.hypot(xx - cx0, yy - cy0) <= reach
    px, py = xx[keep].astype(np.float32), yy[keep].astype(np.float32)
    return px, py, key[py.astype(int), px.astype(int)]


def fit(crop: np.ndarray | None, cls: str, cx0: float, cy0: float, *,
        key: np.ndarray | None = None, r_in: float | None = None,
        r_out: float | None = None, L_: float | None = None) -> dict:
    """The class's teardrop nearest `(cx0, cy0)`.

    Returns `teardrop_tip.fit`'s fields (`x`, `y`, `deg`, `tip_x`, `tip_y`,
    `ncc`) plus `margin` (best NCC less the best NCC at any facing 90 degrees
    or more away, at the fitted centre), `cls`, and `read`; an unread fit has
    `reason` and no `deg` a caller may use.
    """
    c = CLASSES[cls]
    r_in = c.r_in if r_in is None else r_in
    r_out = c.r_out if r_out is None else r_out
    L_ = c.L if L_ is None else L_
    key = c.key(crop) if key is None else key
    f = tt.fit(None, cx0, cy0, r_in=r_in, r_out=r_out, L_=L_, yel=key)
    f["cls"] = cls
    if "x" not in f:
        return {"cls": cls, "read": False, "reason": "no_key"}
    px, py, obs = _window(key, f["x"], f["y"], L_ + tt.WINDOW)
    ths = np.radians(np.arange(0.0, 360.0, MARGIN_DEG, dtype=np.float32))
    sc = _correlation(obs, tt.render(px[None, :] - f["x"], py[None, :] - f["y"], ths[:, None],
                                r_in, r_out, L_))
    far = np.abs(sem._signed_deg(np.degrees(ths) - f["deg"])) >= 90.0
    f["margin"] = float(f["ncc"] - sc[far].max())
    f["ring_cover"] = ring_cover(key, f["x"], f["y"], f["deg"], r_in, r_out)
    f["read"] = True
    f.pop("reason", None)
    if f["ncc"] < c.min_ncc:
        f.update(read=False, reason="low_ncc")
    elif f["ring_cover"] < c.min_ring:
        f.update(read=False, reason="no_ring")
    elif f["margin"] < c.min_margin:
        f.update(read=False, reason="ambiguous_facing")
    return f


def ring_cover(key: np.ndarray, x: float, y: float, deg: float, r_in: float, r_out: float,
               n_bins: int = 36, away_deg: float = 60.0, min_key: float = 0.5) -> float:
    """Share of the ring's angular bins, away from the lobe, whose annulus is keyed.

    The ring is what a spawn barrier, a map fill or a stray glyph lacks: a
    straight red bar crosses the annulus twice and scores the lobe's NCC
    well enough. Bins within `away_deg` of the facing hold the lobe and are
    skipped; a bin is covered when the brightest key in the annulus
    `[r_in - 0.5, r_out + 0.5]` within it reaches `min_key`. The brightest,
    not the mean: the teal ring is 1-2 px of a 3 px band whose inner edge is
    the portrait's dark rim, and a mean refused a quarter of real teammates
    on the first contact sheet.
    """
    h, w = key.shape
    R = int(math.ceil(r_out + 1))
    x0, x1 = max(0, int(x) - R), min(w, int(x) + R + 2)
    y0, y1 = max(0, int(y) - R), min(h, int(y) + R + 2)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    rho = np.hypot(xx - x, yy - y)
    ang = np.degrees(np.arctan2(yy - y, xx - x))
    band = (rho >= r_in - 0.5) & (rho <= r_out + 0.5)
    rel = np.abs(sem._signed_deg(ang - deg))
    keep = band & (rel >= away_deg)
    if not keep.any():
        return 0.0
    b = ((ang[keep] + 180.0) / 360.0 * n_bins).astype(int) % n_bins
    v = key[y0:y1, x0:x1][keep]
    peak = np.full(n_bins, -1.0)
    np.maximum.at(peak, b, v)
    used = peak >= 0
    return float(np.mean(peak[used] >= min_key))


# ------------------------------------------------------------- measurement

def sample_times(s, n: int, *, calibration: bool, seed: int = 20260928) -> list[float]:
    """`n` distinct cached times, from the held-out minutes or from the others."""
    T = np.array([t for t in s.cache_t if held_out(t) == calibration])
    return sorted(float(t) for t in T[np.linspace(0, len(T) - 1, n).astype(int)])


def calibrate(cls: str, n: int, grid: dict) -> list[tuple]:
    """Mean NCC over held-out detections for each (r_out, width, L).

    Only detections the provisional constants read (every refusal gate
    passed) enter, so spawn barriers, red map fills and stray glyphs do not
    vote on an icon's geometry.
    """
    frames = []
    for sid in SESSIONS:
        s = sem.Session(sid)
        for t, crop in s.crops(sample_times(s, n, calibration=True)):
            key = CLASSES[cls].key(crop)
            for d in detections(crop, cls, s):
                f0 = fit(None, cls, d["cx"], d["cy"], key=key)
                if f0.get("read"):
                    frames.append((key, f0["x"], f0["y"]))
        print(f"{sid}: {len(frames)} {cls} detections so far", flush=True)
    # Each combination starts from the provisional fit's centre and searches
    # +/-1 px round it before refining, a ninth of the full search's cost.
    rows = []
    search, tt.SEARCH_PX = tt.SEARCH_PX, 1
    try:
        for r_out in grid["r_out"]:
            for width in grid["width"]:
                for L_ in grid["L"]:
                    m = float(np.mean([tt.fit(None, x, y, r_in=r_out - width, r_out=r_out, L_=L_,
                                              yel=k)["ncc"] for k, x, y in frames]))
                    rows.append((m, r_out, width, L_))
                    print(f"r_out {r_out} width {width} L {L_}: mean ncc {m:.4f}", flush=True)
    finally:
        tt.SEARCH_PX = search
    rows.sort(reverse=True)
    print("best five", rows[:5])
    return rows


def read_frames(s, times, classes=("ally", "enemy")) -> dict:
    """Every detection of each class at `times`, with its ring facing and teardrop fit."""
    out = {c: [] for c in classes}
    for t, crop in s.crops(times):
        for cls in classes:
            key = CLASSES[cls].key(crop)
            for d in detections(crop, cls, s):
                f = fit(None, cls, d["cx"], d["cy"], key=key)
                out[cls].append({"t_ms": float(t), "det_x": float(d["cx"]), "det_y": float(d["cy"]),
                                 "det_r": int(d["r"]), "cov": float(d["cov"]),
                                 "ring_deg": d.get("facing"), **{k: f.get(k) for k in (
                                     "x", "y", "deg", "ncc", "margin", "ring_cover", "read", "reason")}})
    return out


def jitter(rows: list[dict]) -> dict:
    """Stationary facing jitter per class, E3's rule on linked tracks.

    Within a run of consecutive cached frames, each read fit links to the
    nearest read fit of the previous distinct frame within 3 px. Repeated
    images (identical fits) collapse first. A frame is stationary when every
    centre in its +/-2 window lies within 0.75 px of the window's median; its
    residual is its facing about the window's median. Turning in place still
    counts, so the figure bounds the reader's noise from above.
    """
    by_t: dict[float, list[dict]] = {}
    for r in rows:
        if r["read"]:
            by_t.setdefault(r["t_ms"], []).append(r)
    tracks: list[list[dict]] = []
    live: list[list[dict]] = []
    prev_t, prev_sig = None, None
    for t in sorted(by_t):
        sig = tuple(sorted((round(r["x"], 3), round(r["y"], 3), round(r["deg"], 2)) for r in by_t[t]))
        if sig == prev_sig:
            continue
        if prev_t is not None and t - prev_t > 200.0:
            live = []
        nxt = []
        for r in by_t[t]:
            best = min(live, key=lambda tr: math.hypot(tr[-1]["x"] - r["x"], tr[-1]["y"] - r["y"]),
                       default=None)
            if best is not None and math.hypot(best[-1]["x"] - r["x"], best[-1]["y"] - r["y"]) <= 3.0 \
                    and best not in nxt:
                best.append(r)
                nxt.append(best)
            else:
                tr = [r]
                tracks.append(tr)
                nxt.append(tr)
        live, prev_t, prev_sig = nxt, t, sig
    fac, ring = [], []
    for tr in tracks:
        X = np.array([r["x"] for r in tr]); Y = np.array([r["y"] for r in tr])
        D = np.array([r["deg"] for r in tr])
        RD = np.array([np.nan if r["ring_deg"] is None else r["ring_deg"] for r in tr])
        for i in range(2, len(tr) - 2):
            sl = slice(i - 2, i + 3)
            if max(np.hypot(X[sl] - np.median(X[sl]), Y[sl] - np.median(Y[sl]))) > 0.75:
                continue
            fac.append(float(-np.median(sem._signed_deg(D[sl] - D[i]))))
            if not np.isnan(RD[sl]).any():
                ring.append(float(-np.median(sem._signed_deg(RD[sl] - RD[i]))))

    def rms20(v):
        v = np.asarray(v, float)
        v = v[np.abs(v) <= 20.0]
        return float(np.sqrt(np.mean(v ** 2))) if len(v) else None
    return {"tracks": len(tracks), "stationary_frames": len(fac),
            "facing_jitter_rms20_deg": rms20(fac),
            "facing_jitter_robust_sd_deg": sem._robust_sd(fac) if fac else None,
            "over20_share": float(np.mean(np.abs(fac) > 20)) if fac else None,
            "ring_stationary_frames": len(ring), "ring_jitter_rms20_deg": rms20(ring),
            "ring_over20_share": float(np.mean(np.abs(ring) > 20)) if ring else None}


def stats(rows: list[dict]) -> dict:
    """Read rate, refusal reasons and the ring fit's disagreement with the teardrop."""
    read = [r for r in rows if r["read"]]
    both = [r for r in read if r["ring_deg"] is not None]
    dis = np.abs(sem._signed_deg(np.array([r["ring_deg"] - r["deg"] for r in both], float)))
    reasons: dict[str, int] = {}
    for r in rows:
        if not r["read"]:
            reasons[r["reason"]] = reasons.get(r["reason"], 0) + 1
    return {"detections": len(rows), "read": len(read),
            "read_rate": len(read) / len(rows) if rows else None, "refused": reasons,
            "ring_unread": sum(r["ring_deg"] is None for r in rows),
            "both_read": len(both),
            "ring_vs_teardrop_over90": float(np.mean(dis > 90)) if len(dis) else None,
            "ring_vs_teardrop_20_90": float(np.mean((dis > 20) & (dis <= 90))) if len(dis) else None,
            "ring_vs_teardrop_median_deg": float(np.median(dis)) if len(dis) else None,
            "ncc_quartiles": np.percentile([r["ncc"] for r in rows if r["ncc"] is not None],
                                           [25, 50, 75]).round(3).tolist()}


def sheet(path: Path, cls: str, n: int, sid: str) -> None:
    """Contact sheet of one class: magenta the ring fit and its facing, green the
    teardrop and its facing (grey where refused), red dot the tip."""
    s = sem.Session(sid)
    K, Z = 20, 8
    c = CLASSES[cls]
    tiles = []
    for t, crop in s.crops(sample_times(s, n, calibration=False)):
        key = c.key(crop)
        for d in detections(crop, cls, s)[:2]:
            f = fit(None, cls, d["cx"], d["cy"], key=key)
            x0, y0 = int(round(d["cx"])) - K, int(round(d["cy"])) - K
            pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
            big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                             interpolation=cv2.INTER_NEAREST)

            def P(x, y):
                return int(round((x - x0 + 0.5) * Z)), int(round((y - y0 + 0.5) * Z))
            cv2.circle(big, P(d["cx"], d["cy"]), int(d["r"] * Z), (255, 0, 255), 1)
            if d.get("facing") is not None:
                a = math.radians(d["facing"])
                cv2.line(big, P(d["cx"], d["cy"]), P(d["cx"] + 1.8 * d["r"] * math.cos(a),
                                                      d["cy"] + 1.8 * d["r"] * math.sin(a)), (255, 0, 255), 1)
            label = f"{t / 1000:.1f}s"
            if "x" in f:
                col = (0, 220, 0) if f["read"] else (160, 160, 160)
                cv2.circle(big, P(f["x"], f["y"]), int(c.r_out * Z), col, 1)
                cv2.line(big, P(f["x"], f["y"]), P(f["tip_x"], f["tip_y"]), col, 2)
                cv2.circle(big, P(f["tip_x"], f["tip_y"]), 4, (0, 0, 255), -1)
                label += f" n{f['ncc']:.2f} m{f['margin']:.2f} c{f['ring_cover']:.2f}" + ("" if f["read"] else " X")
            cv2.putText(big, label, (4, 16), 0, .5, (255, 255, 255), 1)
            tiles.append(big)
    tiles = tiles[:36]
    blank = np.zeros_like(tiles[0])
    rows = [np.hstack(tiles[i:i + 6] + [blank] * (6 - len(tiles[i:i + 6]))) for i in range(0, len(tiles), 6)]
    cv2.imwrite(str(path), np.vstack(rows))
    print("wrote", path)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--calibrate", choices=("ally", "enemy"))
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--jitter", action="store_true", help="with --stats: runs of consecutive frames too")
    ap.add_argument("--record", action="store_true", help="with --stats: append the run to the metrics log")
    ap.add_argument("--sheet", nargs=2, metavar=("CLASS", "PATH"))
    ap.add_argument("--session", default=LOTUS)
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--runs", type=int, default=12, help="--jitter: runs per session")
    ap.add_argument("--run-len", type=int, default=30, help="--jitter: frames per run")
    ap.add_argument("--r-out", type=float, nargs="+", default=[9.5, 10.0, 10.5, 11.0, 11.5])
    ap.add_argument("--width", type=float, nargs="+", default=[1.0, 1.5, 2.0, 2.5])
    ap.add_argument("--length", type=float, nargs="+", default=[15.0, 16.0, 17.0, 18.0, 19.0, 20.0])
    args = ap.parse_args(argv)
    sem._below_normal()
    if args.calibrate:
        calibrate(args.calibrate, args.n, {"r_out": args.r_out, "width": args.width, "L": args.length})
        return 0
    if args.sheet:
        sheet(Path(args.sheet[1]), args.sheet[0], args.n, args.session)
        return 0
    if args.stats:
        for sid in SESSIONS:
            s = sem.Session(sid)
            got = read_frames(s, sample_times(s, args.n, calibration=False))
            values = {}
            for cls, rows in got.items():
                st = stats(rows)
                print(sid, cls, st, flush=True)
                values.update({f"{cls}_detections": st["detections"], f"{cls}_read_rate": round(st["read_rate"], 3),
                               f"{cls}_ring_vs_teardrop_over90": round(st["ring_vs_teardrop_over90"], 3),
                               f"{cls}_ring_vs_teardrop_20_90": round(st["ring_vs_teardrop_20_90"], 3)})
            if args.jitter:
                # Runs of consecutive cached frames centred on sampled frames
                # where the class reads, so a class seen briefly (enemies)
                # still yields stationary windows.
                T = np.array([t for t in s.cache_t if not held_out(t)])
                for cls, rows in got.items():
                    anchors = sorted({r["t_ms"] for r in rows if r["read"]})
                    anchors = [anchors[i] for i in np.linspace(0, len(anchors) - 1,
                                                               min(args.runs, len(anchors))).astype(int)]
                    times = sorted({float(t) for a in anchors
                                    for t in T[max(0, np.searchsorted(T, a) - args.run_len // 2):
                                               np.searchsorted(T, a) + args.run_len // 2]})
                    j = jitter(read_frames(s, times, (cls,))[cls])
                    print(sid, cls, "jitter", j, flush=True)
                    values.update({f"{cls}_stationary_frames": j["stationary_frames"],
                                   f"{cls}_jitter_rms20_deg": None if j["facing_jitter_rms20_deg"] is None
                                   else round(j["facing_jitter_rms20_deg"], 2),
                                   f"{cls}_ring_jitter_rms20_deg": None if j["ring_jitter_rms20_deg"] is None
                                   else round(j["ring_jitter_rms20_deg"], 2)})
            if args.record:
                from reticle import metrics
                metrics.record("icon_teardrop", part="stats", session=sid, values=values,
                               deps={"version": VERSION, "n": args.n, "runs": args.runs, "run_len": args.run_len,
                                     "classes": {k: [c.r_in, c.r_out, c.L, c.min_ncc, c.min_margin, c.min_ring]
                                                 for k, c in CLASSES.items() if k != "self"}},
                               note="ally/enemy teardrop read rate, ring disagreement and stationary jitter")
                print("recorded", values)
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
