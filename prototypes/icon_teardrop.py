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
from.

**Promoted** to `reticle/teardrop.py` (`fit_icon`, `ICON_TEARDROP_VERSION`)
on 2026-09-29, which scales the radii by `minimap.widget_scale`; this module
re-exports it and stays the measuring instrument, at scale 1.0 unless a
caller passes `scale`. `--centre-check` measures the scaling on 331 px
widgets from the crop cache.

It reads the minimap crop cache only, decodes no video and writes nothing to
the store. `label_icon_facing.py` asks the player; `icon_facing_eval.py`
scores both readers against the answers.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)
import teardrop_tip as tt  # noqa: E402
from reticle import minimap  # noqa: E402
from reticle import teardrop as _td  # noqa: E402

VERSION = "icon-teardrop-0.2.0"
LOTUS, ASCENT = "5822b6646448", "a06f04a0059f"
SESSIONS = (LOTUS, ASCENT)
CAL_EVERY_MIN = 4             # minute m is held out for calibration when m % 4 == 3
MARGIN_DEG = _td.MARGIN_DEG   # facing grid for the ambiguity margin


# 0.2.0: the keys, the class table and the fit live in `reticle.teardrop`
# (ICON_TEARDROP_VERSION) and this module re-exports them; `fit` takes the
# widget's `scale`, and at scale 1.0 it is 0.1.0's fit exactly.
tealness, redness, ring_cover = _td.tealness, _td.redness, _td.ring_cover
IconClass = _td.IconClass

# The self row is teardrop_tip's, unchanged. The ally and enemy rows are the
# promoted reader's (`reticle.teardrop.ICON_CLASSES`), the `--calibrate`
# plateau on held-out minutes of both sessions:
#   ally, `--calibrate ally --n 30`: 100 detections of held-out minutes (48
#   Lotus, 52 Ascent) that the provisional self geometry fitted at NCC >= 0.4
#   (the read gate came later); mean NCC 0.766 at these values, a plateau over
#   ring width 1.5-2 and L 18-20 (0.760-0.766) at r_out 10.5; the best at
#   r_out 10 and 11 is 0.757 and 0.760, at 9.5 0.727.
#   enemy, `--calibrate enemy --n 200`: 53 read detections (23 Lotus, 30
#   Ascent); mean NCC 0.741 at these values, a ridge along r_in 7-7.5 for
#   r_out 10.5-11 (0.741-0.742) and L 18-19. The red ring reads thicker than
#   the teal one: the portrait's rim is dark red.
CLASSES = {
    "self": IconClass("self", tt.yellowness, tt.R_IN, tt.R_OUT, tt.L, tt.MIN_NCC, 0.0, 0.0),
    **_td.ICON_CLASSES,
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


def fit(crop: np.ndarray | None, cls: str, cx0: float, cy0: float, *,
        key: np.ndarray | None = None, r_in: float | None = None,
        r_out: float | None = None, L_: float | None = None, scale: float = 1.0) -> dict:
    """The class's teardrop nearest `(cx0, cy0)`: `reticle.teardrop.fit_icon`.

    Returns `x`, `y`, `deg`, `tip_x`, `tip_y`, `ncc`, `margin`,
    `ring_cover`, `cls` and `read`; an unread fit has `reason` and no `deg`
    a caller may use. `scale` is `minimap.widget_scale`; `r_in`, `r_out`
    and `L_` override the scaled radii in px, for `--calibrate`.
    """
    return _td.fit_icon(crop, CLASSES[cls], cx0, cy0, scale=scale, key=key,
                        r_in=r_in, r_out=r_out, L_=L_)


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


#: 331 px widgets (scale 0.712) and a 465 px control.
CENTRE_SESSIONS = ("223d636bf8d2", "bfad2778a372", "e37fdeca944f", ASCENT)


def centre_check(sid: str, n: int, sheet_path: Path | None = None, cls: str = "ally") -> dict:
    """The `cls` teardrop's centre at scale 1.0 (0.1.0) and at the widget's scale (0.2.0).

    On `n` frames outside the calibration minutes, every `cls` detection is
    read three ways: the ring fit's centre, the teardrop at scale 1.0 and
    the teardrop at `widget_scale`. Reports each teardrop's median distance
    from the ring fit's centre and, the independent witness, the median
    rendered-art fit of the portrait aligned at each centre to the side's
    lineup (`icon_portrait_gate.features_at`, lower is better; it rests on
    the lineup prior and names nobody). Crop cache only; writes nothing.
    """
    import icon_portrait_gate as ipg
    from reticle.adjudication.identity import load_ally_portrait_references, rendered_art_fit
    from reticle.lineup import load_lineup

    s = ipg.Lite(sid)
    refs = load_ally_portrait_references(ipg.STORE)
    names, why = ipg.side_gallery(load_lineup(sid, ipg.STORE), "ally")
    rows, tiles = [], []
    width = None
    for t, crop in s.crops(sample_times(s, n, calibration=False)):
        width = int(crop.shape[1])
        sc = minimap.widget_scale(width)
        key = CLASSES[cls].key(crop)
        for d in detections(crop, cls, s):
            old = fit(None, cls, d["cx"], d["cy"], key=key)
            new = fit(None, cls, d["cx"], d["cy"], key=key, scale=sc)
            row = {"t_ms": float(t), "old_read": bool(old.get("read")), "new_read": bool(new.get("read")),
                   "new_ncc": new.get("ncc")}
            for arm, f in (("ring", {"x": d["cx"], "y": d["cy"], "read": True}), ("old", old), ("new", new)):
                if f.get("read"):
                    got = rendered_art_fit(ipg.features_at(crop, f["x"], f["y"]), names, refs) if names else None
                    row[f"{arm}_fit"] = None if got is None else float(got[0])
                    if arm != "ring":
                        row[f"{arm}_offset"] = float(math.hypot(f["x"] - d["cx"], f["y"] - d["cy"]))
                        row[f"{arm}_deg"] = float(f["deg"])
            rows.append(row)
            if sheet_path is not None and len(tiles) < 24:
                tiles.append(_centre_tile(crop, d, old, new))
    if sheet_path is not None and tiles:
        blank = np.zeros_like(tiles[0])
        grid = [np.hstack(tiles[i:i + 6] + [blank] * (6 - len(tiles[i:i + 6])))
                for i in range(0, len(tiles), 6)]
        cv2.imwrite(str(sheet_path), np.vstack(grid))

    def med(k, where=lambda r: True):
        v = [r[k] for r in rows if r.get(k) is not None and where(r)]
        return round(float(np.median(v)), 3) if v else None
    both = lambda r: r.get("old_fit") is not None and r.get("new_fit") is not None  # noqa: E731
    dd = [abs(float(sem._signed_deg(r["new_deg"] - r["old_deg"]))) for r in rows
          if r.get("new_deg") is not None and r.get("old_deg") is not None]
    return {"width": width, "detections": len(rows), "gallery": len(names), "gallery_reason": why,
            "old_read_rate": round(float(np.mean([r["old_read"] for r in rows])), 3) if rows else None,
            "new_read_rate": round(float(np.mean([r["new_read"] for r in rows])), 3) if rows else None,
            "old_offset_px": med("old_offset"), "new_offset_px": med("new_offset"),
            "ring_fit_median": med("ring_fit"), "old_fit_median": med("old_fit"),
            "new_fit_median": med("new_fit"), "old_fit_median_both": med("old_fit", both),
            "new_fit_median_both": med("new_fit", both),
            "new_better_than_old": (round(float(np.mean([r["new_fit"] < r["old_fit"] for r in rows if both(r)])), 3)
                                    if any(both(r) for r in rows) else None),
            "facing_change_median_deg": round(float(np.median(dd)), 2) if dd else None,
            "facing_change_over90": round(float(np.mean(np.asarray(dd) > 90)), 3) if dd else None,
            "new_ncc_median": med("new_ncc", lambda r: r["new_read"]),
            # Portrait fit by the scaled read's NCC: does a low-NCC read still centre the portrait?
            "new_fit_median_ncc_under60": med("new_fit", lambda r: r["new_read"] and r["new_ncc"] < 0.6),
            "ring_fit_median_ncc_under60": med("ring_fit", lambda r: r["new_read"] and r["new_ncc"] < 0.6),
            "new_fit_median_ncc_60up": med("new_fit", lambda r: r["new_read"] and r["new_ncc"] >= 0.6),
            "ring_fit_median_ncc_60up": med("ring_fit", lambda r: r["new_read"] and r["new_ncc"] >= 0.6)}


def _centre_tile(crop, d, old, new, K: int = 16, Z: int = 8) -> np.ndarray:
    """Magenta the ring fit's centre, grey the scale-1.0 teardrop, green the scaled one."""
    x0, y0 = int(round(d["cx"])) - K, int(round(d["cy"])) - K
    pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
    big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                     interpolation=cv2.INTER_NEAREST)

    def P(x, y):
        return int(round((x - x0 + 0.5) * Z)), int(round((y - y0 + 0.5) * Z))
    cv2.drawMarker(big, P(d["cx"], d["cy"]), (255, 0, 255), cv2.MARKER_CROSS, 14, 2)
    for f, col in ((old, (160, 160, 160)), (new, (0, 220, 0))):
        if "x" in f:
            cv2.circle(big, P(f["x"], f["y"]), 5, col, -1 if f.get("read") else 1)
            cv2.line(big, P(f["x"], f["y"]), P(f["tip_x"], f["tip_y"]), col, 1)
    return big


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
    ap.add_argument("--centre-check", action="store_true",
                    help="the ally centre at scale 1.0 and at widget scale, on CENTRE_SESSIONS")
    ap.add_argument("--centre-class", choices=("ally", "self"), default="ally")
    ap.add_argument("--centre-sessions", nargs="+", default=list(CENTRE_SESSIONS))
    ap.add_argument("--sheet-dir", type=Path, help="--centre-check: write a contact sheet per session here")
    args = ap.parse_args(argv)
    sem._below_normal()
    if args.centre_check:
        values = {}
        for sid in args.centre_sessions:
            got = centre_check(sid, args.n, None if args.sheet_dir is None
                               else args.sheet_dir / f"centre_check_{args.centre_class}_{sid}.png",
                               cls=args.centre_class)
            print(sid, got, flush=True)
            values[sid] = got
        if args.record:
            from reticle import metrics
            from reticle.version import ICON_TEARDROP_VERSION
            for sid, got in values.items():
                metrics.record("icon_teardrop", part="centre-scale" + ("" if args.centre_class == "ally"
                                                                      else "-" + args.centre_class),
                               session=sid,
                               values={k: v for k, v in got.items() if k != "gallery_reason"},
                               deps={"version": VERSION, "reader": ICON_TEARDROP_VERSION, "n": args.n,
                                     "before": "icon-teardrop-0.1.0 (scale 1.0)"},
                               note="ally teardrop centre and portrait fit at scale 1.0 and at widget_scale")
        return 0
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
