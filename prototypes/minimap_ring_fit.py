"""Find the enemy icon by FITTING its ring, not by requiring the ring to close.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_ring_fit.py <video> [--prekill <session>]

Why this exists. The seal test -- does the red blob enclose a hole -- works on a
lossless capture (hole_frac 0.69) and collapses at 4:2:0 (0.00-0.09), so the
finder fired on 1 of 21 pre-kill minimaps on the standard-settings match.

Grant's observation explains it, and the geometry is measured. The ring is a
**teardrop, not an annulus**: thickness by angle from the facing triangle, on
the lossless icon, is

    at the triangle   7.3 px
    +/-30 deg         4.1 / 1.9
    +/-45..90 deg     2.3 / 2.4
    +/-105..180 deg   1.1 - 2.0 px

So over most of its circumference the ring is ONE TO TWO PIXELS. Closure is a
topological property: it needs every pixel of that thin arc to survive, and a
single break loses it entirely. Half-resolution chroma is precisely what a
1-2 px colour feature does not survive, so the seal was always going to be the
first thing to go -- and it takes the whole detection with it.

The fix is to stop asking for a property that fragile. A broken arc still lies
on a circle, so: brute-force the circle whose circumference is most covered by
red, then test the disc it encloses. That needs no closing kernel -- which is
what merged adjacent icons in every earlier attempt -- degrades gracefully as
the arc breaks up, and survives the icon being partly occluded.

Occlusion is not hypothetical. Grant found the local player's icon drawing ON
TOP of an enemy's when they overlap, which happens at exactly the range a duel
happens: at 13:00 in `a06f04a0059f` only 18 px of a 7x4 sliver of the enemy ring
survives under it. A closure test cannot see that at all; an arc-coverage test
degrades to a low score instead of a silent zero, which is the difference
between a miss and a measurable one.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from minimap_icons import ROI, floor_mask, red_mask, static_map      # noqa: E402

# Radii to try, in pixels. Kept NARROW on purpose. Coverage is a fraction of
# circumference, so a small circle threaded through one surviving fragment
# scores better than a correctly-sized circle that is mostly gap -- with the
# range open to 6 the fit collapsed to r=6 on nearly every 4:2:0 miss and the
# coverage it reported meant nothing. The widget size is fixed, so the icon
# radius is very nearly a constant (measured ~9-10 on the enlarged widget) and
# letting it float was giving away the strongest prior available.
#
# This is per-widget-size and must be re-measured if Grant changes the slider.
R_MIN, R_MAX = 8, 13
# How far the true centre may sit from the blob's centroid. The triangle drags
# the centroid toward itself by several pixels, which is the same effect that
# reported the facing 180 degrees out before it was measured from the hole.
SEARCH = 5
N_THETA = 48


def _circle_offsets():
    """Precomputed integer ring offsets per radius, and the disc per radius."""
    ring, disc = {}, {}
    th = np.arange(N_THETA) / N_THETA * 2 * np.pi
    for r in range(R_MIN, R_MAX + 1):
        pts = np.unique(np.stack([np.round(r * np.cos(th)),
                                  np.round(r * np.sin(th))], 1).astype(int), axis=0)
        ring[r] = pts
        yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
        inner = (yy ** 2 + xx ** 2) <= (r * 0.62) ** 2
        disc[r] = np.stack([xx[inner], yy[inner]], 1)
    return ring, disc


RING, DISC = _circle_offsets()


def fit_ring(red, grey, cx, cy):
    """Best (coverage, cx, cy, r, interior stats) over centres and radii.

    Coverage is the share of the circle's circumference that is red. A whole
    icon scores high even with the arc broken in several places, which is the
    entire point -- unlike a hole test, it does not care whether the breaks
    happen to disconnect the ring.
    """
    h, w = red.shape
    best = None
    for dy in range(-SEARCH, SEARCH + 1):
        for dx in range(-SEARCH, SEARCH + 1):
            y0, x0 = int(round(cy + dy)), int(round(cx + dx))
            for r in range(R_MIN, R_MAX + 1):
                pts = RING[r]
                xs, ys = x0 + pts[:, 0], y0 + pts[:, 1]
                ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
                if ok.sum() < len(pts) * 0.75:
                    continue
                cov = float(red[ys[ok], xs[ok]].mean())
                if best is None or cov > best[0]:
                    best = (cov, x0, y0, r)
    if best is None:
        return None
    cov, x0, y0, r = best
    d = DISC[r]
    xs, ys = x0 + d[:, 0], y0 + d[:, 1]
    ok = (xs >= 0) & (ys >= 0) & (xs < w) & (ys < h)
    if not ok.any():
        return None
    inner_red = float(red[ys[ok], xs[ok]].mean())
    inner_v = float(grey[ys[ok], xs[ok]].mean())
    return {"cov": cov, "cx": x0, "cy": y0, "r": r,
            "inner_red": inner_red, "inner_v": inner_v}


# An icon is a well-covered ring around a NON-red interior. Both halves are
# needed and measured, on the same lossless frame:
#
#   enemy icon   cov 0.85  r 10  inner_red 0.00     ring around a portrait
#   red X mark   cov 0.33  r  6  inner_red 0.67     solid throughout
#
# Ranking by coverage alone picks solid red things, because a disc's
# circumference is fully red -- inner_red is what rejects them, and it is the
# same interior-versus-rim test the screen detector already applies.
#
# The radius floor matters as much: at R_MIN a small fragment always fits
# *something*, so unbounded-below fits collapse to r=6 with a meaningless
# coverage. A real icon on the enlarged widget sits at r 8-13.
#
# COV_MIN swept against Grant's 96 hand labels on a06f04a0059f, prekill pool:
#
#     cov_min   recall   precision
#       0.35     79.1%     61.8%      <- default
#       0.42     60.5%     68.4%
#       0.50     55.8%     70.6%
#       0.60     37.2%     76.2%      <- the first guess, and much too tight
#       0.80      9.3%    100.0%
#
# 0.35 is chosen because this is a FEATURE, not a veto: the premise measurement
# below caps what a gate could ever be worth, so recall is what matters and
# precision is cheap to recover downstream. It is also the edge of the swept
# range and may want to go lower -- and it is fitted to 96 labels on ONE
# session, so treat it as provisional until a second session exists.
COV_MIN, INNER_RED_MAX = 0.35, 0.35
R_ICON = (8, 13)


def is_icon(f):
    return (f["cov"] >= COV_MIN and f["inner_red"] <= INNER_RED_MAX
            and R_ICON[0] <= f["r"] <= R_ICON[1])


def find(crop, floor, sat_min=100, min_area=25):
    """Ring-fit every red blob big enough to be part of an icon."""
    red = (red_mask(crop, sat_min) & floor)
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    n, lbl, st, cen = cv2.connectedComponentsWithStats(red.astype(np.uint8), 8)
    out, seen = [], []
    for i in range(1, n):
        if st[i, 4] < min_area:
            continue
        f = fit_ring(red, grey, cen[i][0], cen[i][1])
        if f is None:
            continue
        # Two fragments of one broken ring fit the SAME circle, so dedupe by
        # centre -- otherwise a badly broken icon counts as several detections
        # and precision is scored against a phantom.
        if any(np.hypot(f["cx"] - p[0], f["cy"] - p[1]) < 8 for p in seen):
            continue
        seen.append((f["cx"], f["cy"]))
        f["area"] = int(st[i, 4])
        out.append(f)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", nargs="?")
    ap.add_argument("--prekill", help="session id: test at its killfeed kills")
    ap.add_argument("--sat", type=int, default=100)
    args = ap.parse_args()

    STORE = Path.home() / "reticle-store"
    if args.prekill:
        from reticle.checks import track_entries
        from reticle.profiles import get_profile
        import pyarrow.parquet as pq
        sid = args.prekill
        man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
        src = man["source"]
        fps = float(src["fps"])
        prof = get_profile(man["source_profile"])
        r = next(x for x in prof.rois if x.name == "minimap")
        x0, y0, x1, y1 = r.pixels(int(src["width"]), int(src["height"]))
        hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
        t = hud.column("t_ms").to_pylist()
        dv = lambda c: hud.column(c).to_pylist() if c in hud.column_names else None
        kills = [e["t_first"] for e in track_entries(
            t, hud.column("kf_kill_mask").to_pylist(), dv("kf_kill_wx")) if e["counted"]]
        path = src["path"]
        times = [k - 800 for k in kills]
    else:
        path, times = args.video, None
        x0, y0, x1, y1 = ROI

    cap = cv2.VideoCapture(str(path))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = float(cap.get(cv2.CAP_PROP_FPS))
    med = []
    for i in np.linspace(0, tot - 1, 150).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            med.append(fr[y0:y1, x0:x1])
    floor = floor_mask(static_map(med))
    if times is None:
        times = list(np.linspace(0, tot - 1, 120) / fps * 1000)

    print(f"{Path(path).name}: floor {floor.mean()*100:.1f}%, {len(times)} frames")
    print(f"  {'time':>7s}  {'cov':>5s} {'r':>3s} {'in_red':>7s} {'in_v':>6s}  n")
    covs = []
    for tm in times:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(tm / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        fs = find(fr[y0:y1, x0:x1], floor, args.sat)
        icons = sorted((f for f in fs if is_icon(f)), key=lambda f: -f["cov"])
        b = icons[0] if icons else None
        covs.append(1 if b else 0)
        s = int(tm) // 1000
        if b:
            print(f"  {s//60:2d}:{s%60:02d}  {b['cov']:5.2f} {b['r']:3d} "
                  f"{b['inner_red']:7.2f} {b['inner_v']:6.1f}  "
                  f"{len(icons)} icon of {len(fs)} blobs")
        else:
            # Say WHY it missed. "MISS" alone would send me back to sweeping;
            # the best rejected fit says which half of the criterion failed.
            best = max(fs, key=lambda f: f["cov"], default=None)
            why = (f"best cov {best['cov']:.2f} r{best['r']} "
                   f"in_red {best['inner_red']:.2f}") if best else "no blob at all"
            print(f"  {s//60:2d}:{s%60:02d}   MISS   ({why})")
    if covs:
        a = np.array(covs)
        print(f"\nframes with an icon: {int(a.sum())}/{len(a)} ({a.mean()*100:.0f}%)")
    cap.release()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
