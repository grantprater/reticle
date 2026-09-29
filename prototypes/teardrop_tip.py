r"""Read the self icon's teardrop tip as a shape: the cone's origin and facing.

    .\.venv\Scripts\python.exe prototypes\teardrop_tip.py [--sheet PATH] [--calibrate]

E3 of [the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md). The
player's cone spec of 2026-09-02 put the cone's origin at the icon's teardrop
point; he withdrew that on 2026-09-28 for about the icon's centre
[domain:minimap/cone-origin-near-centre], and E4 (`cone_origin.py`) found no
offset from this fit's centre that beats it. `minimap.icons` fits a circle to
the thresholded self key and reads the facing from how far the key reaches past
it; E2 placed a teardrop one fitted radius along that facing and the cone agreed
worse with the drawn light. The E3 contact sheet shows why: the circle fit sits
two to four pixels off the portrait's centre, toward the tip, and its facing is
often flipped or off by tens of degrees.

**The shape.** The self icon is a pale yellow ring round the portrait plus a
filled lobe whose two edges are tangent to the ring's outer circle and meet at
the apex. The model renders that silhouette -- the teardrop of outer radius
`R_OUT` and apex distance `L`, less the portrait disc of radius `R_IN` -- with
a soft edge, and scores it by normalised correlation against a continuous
yellowness (`yellowness`, no threshold) over a fixed window round the
detector's centre. The fit searches centre and facing on a grid, then refines
by a compass search to a twentieth of a pixel and a quarter degree. The tip is
the centre plus `L` along the facing. The facing needs no lobe resolution: the
teardrop points one way.

**The constants** (`R_IN`, `R_OUT`, `L`) are one widget size's geometry, not a
game fact; `--calibrate` fits them on a sample of held-out frames by the mean
correlation, and scales with `minimap.widget_scale` are not handled.

It reads the minimap crop cache only, decodes no video and writes nothing to
the store. `sliver_error_model.py --experiment e3` consumes it.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import minimap  # noqa: E402

VERSION = "teardrop-tip-0.1.0"
# Fitted by `--calibrate` on 24 held-out frames of e78e75b2d191 (enlarged widget):
# mean correlation 0.846 at these values, a plateau over L 18-19 and ring width
# 1.5-2 px; 0.70 at the first guess (8, 10.5, 16).
R_IN, R_OUT, L = 9.5, 11.0, 18.0
EDGE = 1.5            # soft edge width, px: chroma is subsampled 2x2
WINDOW = 4.0          # the scoring window reaches this far past the apex
SEARCH_PX = 4         # centre grid half-width round the detector's centre
GRID_DEG = 10.0
MIN_NCC = 0.5         # below this the shape is not read


def yellowness(crop: np.ndarray) -> np.ndarray:
    """How yellow each pixel is, in [0, 1]: min(G, R) - B, ramped over 10..60.

    Continuous, so the fit sees the anti-aliased and chroma-blurred edge rather
    than a threshold's staircase. Lit floor sits near 10, the ring near 70-90.
    """
    c = crop.astype(np.float32)
    y = np.minimum(c[..., 1], c[..., 2]) - c[..., 0]
    return np.clip((y - 10.0) / 50.0, 0.0, 1.0)


def render(dx, dy, th, r_in=R_IN, r_out=R_OUT, L_=L, edge=EDGE):
    """Soft yellow silhouette at offsets (dx, dy) from the centre, facing `th` radians.

    Broadcasts: `dx`, `dy` shaped (..., P) and `th` shaped (..., 1).
    """
    c, s = np.cos(th), np.sin(th)
    u = dx * c + dy * s
    v = -dx * s + dy * c
    rho = np.hypot(dx, dy)
    ca = r_out / L_
    sa = math.sqrt(max(0.0, 1.0 - ca * ca))
    d_wedge = u * ca + np.abs(v) * sa - r_out
    d_tri = np.maximum(d_wedge, np.maximum(r_out * ca - u, u - L_))
    d_tear = np.minimum(rho - r_out, d_tri)
    d = np.maximum(d_tear, r_in - rho)
    return np.clip(0.5 - d / edge, 0.0, 1.0)


def _ncc(obs, model):
    """Normalised correlation of `obs` (P,) with each model row (..., P)."""
    o = obs - obs.mean()
    m = model - model.mean(axis=-1, keepdims=True)
    den = np.sqrt((o * o).sum() * (m * m).sum(axis=-1))
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(den > 0, (m * o).sum(axis=-1) / den, -1.0)


def fit(crop: np.ndarray, cx0: float, cy0: float, *, r_in=R_IN, r_out=R_OUT, L_=L,
        yel: np.ndarray | None = None) -> dict:
    """The teardrop nearest the detector's centre `(cx0, cy0)`.

    Returns `x`, `y` (the ring's centre), `deg` (facing, image degrees, y down),
    `tip_x`, `tip_y`, `ncc`, and `read` (False with a `reason` below MIN_NCC).
    """
    yel = yellowness(crop) if yel is None else yel
    h, w = yel.shape
    rad = L_ + WINDOW + SEARCH_PX
    x0, x1 = max(0, int(cx0 - rad)), min(w, int(cx0 + rad) + 1)
    y0, y1 = max(0, int(cy0 - rad)), min(h, int(cy0 + rad) + 1)
    yy, xx = np.mgrid[y0:y1, x0:x1]
    keep = np.hypot(xx - cx0, yy - cy0) <= rad
    px, py = xx[keep].astype(np.float32), yy[keep].astype(np.float32)
    obs = yel[py.astype(int), px.astype(int)]
    if obs.max() <= 0:
        return {"read": False, "reason": "no_yellow"}

    offs = np.arange(-SEARCH_PX, SEARCH_PX + 1, dtype=np.float32)
    ths = np.radians(np.arange(0.0, 360.0, GRID_DEG, dtype=np.float32))
    best = (-2.0, 0.0, 0.0, 0.0)
    for oy in offs:
        cxs = (cx0 + offs)[:, None, None]                      # (X, 1, 1)
        dx = px[None, None, :] - cxs
        dy = py[None, None, :] - (cy0 + oy)
        sc = _ncc(obs, render(dx, dy, ths[None, :, None], r_in, r_out, L_))   # (X, T)
        i = np.unravel_index(int(np.argmax(sc)), sc.shape)
        if sc[i] > best[0]:
            best = (float(sc[i]), float(cx0 + offs[i[0]]), float(cy0 + oy), float(ths[i[1]]))

    def score(x, y, t):
        return float(_ncc(obs, render(px - x, py - y, t, r_in, r_out, L_)))

    sc, x, y, t = best
    step_p, step_t = 0.5, math.radians(3.0)
    while step_p >= 0.05:
        moved = False
        for ddx, ddy, ddt in ((step_p, 0, 0), (-step_p, 0, 0), (0, step_p, 0), (0, -step_p, 0),
                              (0, 0, step_t), (0, 0, -step_t)):
            s2 = score(x + ddx, y + ddy, t + ddt)
            if s2 > sc:
                sc, x, y, t, moved = s2, x + ddx, y + ddy, t + ddt, True
                break
        if not moved:
            step_p, step_t = step_p / 2, step_t / 2
    deg = (math.degrees(t) + 180.0) % 360.0 - 180.0
    out = {"x": x, "y": y, "deg": deg, "ncc": sc,
           "tip_x": x + L_ * math.cos(t), "tip_y": y + L_ * math.sin(t),
           "read": sc >= MIN_NCC}
    if not out["read"]:
        out["reason"] = "low_ncc"
    return out


def self_start(crop: np.ndarray, floor: np.ndarray):
    """The detector's best self fit, the fit's starting point, or None."""
    dets = minimap.self_icons(crop, floor, require_facing=False)
    return max(dets, key=lambda d: d["cov"], default=None)


def sheet(path: Path, items, K: int = 20, Z: int = 8, cols: int = 6) -> None:
    """Contact sheet: each item is (t, crop, det, tip-fit). Magenta: ring fit;
    green: the fitted teardrop and its facing; red dot: the tip."""
    tiles = []
    for t, crop, det, tf in items:
        if det is None and not (tf and "x" in tf):
            tile = np.zeros((2 * K * Z, 2 * K * Z, 3), np.uint8)
            cv2.putText(tile, f"{t / 1000:.2f}s no fit", (4, 16), 0, .5, (255, 255, 255), 1)
            tiles.append(tile)
            continue
        cx, cy = (det["cx"], det["cy"]) if det else (tf["x"], tf["y"])
        x0, y0 = int(round(cx)) - K, int(round(cy)) - K
        pad = cv2.copyMakeBorder(crop, K, K, K, K, cv2.BORDER_CONSTANT)
        big = cv2.resize(pad[y0 + K:y0 + 3 * K, x0 + K:x0 + 3 * K], None, fx=Z, fy=Z,
                         interpolation=cv2.INTER_NEAREST)

        def P(x, y):
            return int(round((x - x0 + 0.5) * Z)), int(round((y - y0 + 0.5) * Z))
        if det:
            cv2.circle(big, P(det["cx"], det["cy"]), int(det["r"] * Z), (255, 0, 255), 1)
            if det.get("facing") is not None:
                a = math.radians(det["facing"])
                cv2.line(big, P(det["cx"], det["cy"]),
                         P(det["cx"] + 1.8 * det["r"] * math.cos(a), det["cy"] + 1.8 * det["r"] * math.sin(a)),
                         (255, 0, 255), 1)
        label = f"{t / 1000:.2f}s"
        if tf and "x" in tf:
            cv2.circle(big, P(tf["x"], tf["y"]), int(R_OUT * Z), (0, 220, 0), 1)
            cv2.circle(big, P(tf["x"], tf["y"]), int(R_IN * Z), (0, 220, 0), 1)
            cv2.line(big, P(tf["x"], tf["y"]), P(tf["tip_x"], tf["tip_y"]), (0, 220, 0), 1)
            cv2.circle(big, P(tf["tip_x"], tf["tip_y"]), 4, (0, 0, 255), -1)
            label += f" ncc{tf['ncc']:.2f} d{tf['deg']:.0f}"
        cv2.putText(big, label, (4, 16), 0, .5, (255, 255, 255), 1)
        tiles.append(big)
    blank = np.zeros_like(tiles[0])
    rows = [np.hstack(tiles[i:i + cols] + [blank] * (cols - len(tiles[i:i + cols])))
            for i in range(0, len(tiles), cols)]
    cv2.imwrite(str(path), np.vstack(rows))


def main(argv=None) -> int:
    import sliver_error_model as sem
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sheet", type=Path)
    ap.add_argument("--calibrate", action="store_true")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--r-out", type=float, nargs="+", default=[9.5, 10.0, 10.5, 11.0, 11.5])
    ap.add_argument("--width", type=float, nargs="+", default=[1.5, 2.0, 2.5, 3.0])
    ap.add_argument("--length", type=float, nargs="+", default=[14.0, 16.0, 18.0, 20.0])
    args = ap.parse_args(argv)
    sem._below_normal()
    s = sem.Session(sem.DEMO)
    T = np.asarray(s.cache_t)
    held = [t for t in T if all(abs(t - h) > sem.HOLDOUT_MS for h in sem.SLIVERS)]
    pick = [held[i] for i in np.linspace(0, len(held) - 1, args.n).astype(int)]
    if args.calibrate:
        frames = [(crop, self_start(crop, s.floor)) for _, crop in s.crops(pick)]
        frames = [(yellowness(c), d) for c, d in frames if d is not None]
        rows = []
        for r_out in args.r_out:
            for width in args.width:
                for L_ in args.length:
                    m = np.mean([fit(None, d["cx"], d["cy"], r_in=r_out - width, r_out=r_out, L_=L_,
                                     yel=y)["ncc"] for y, d in frames])
                    rows.append((m, r_out, width, L_))
                    print(f"r_out {r_out} width {width} L {L_}: mean ncc {m:.4f}", flush=True)
        print("best", max(rows))
        return 0
    if args.sheet:
        times = list(sem.SLIVERS) + pick
        times = [float(T[np.argmin(np.abs(T - t))]) for t in times]
        items = []
        for t, crop in s.crops(times):
            det = self_start(crop, s.floor)
            tf = fit(crop, det["cx"], det["cy"]) if det else None
            items.append((t, crop, det, tf))
        sheet(args.sheet, items)
        print("wrote", args.sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
