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

# Rays for reading the facing triangle: for each angle, how far past the ring
# does red reach. The triangle is the only thing outside the circle, so the
# angle where red reaches furthest IS the facing.
N_FACE = 32
_FACE_TH = np.arange(N_FACE) / N_FACE * 2 * np.pi


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
            "inner_red": inner_red, "inner_v": inner_v,
            "facing": _facing(red, x0, y0, r),
            "lobe": _lobe(red, x0, y0, r)}


def _lobe(red, cx, cy, r):
    """How far the largest lobe reaches past the ring, as a fraction of r.

    Reported separately from `facing` because it answers a different question:
    `facing` is WHERE the triangle points, `lobe` is WHETHER there is one. A
    Cypher cam is a perfect circle, so a lobe near zero is evidence against a
    player independent of any rotation measurement.
    """
    h, w = red.shape
    best = 0.0
    for th in _FACE_TH:
        dx, dy = np.cos(th), np.sin(th)
        for rr in np.arange(r + 1, r * 1.9, 0.7):
            x, y = int(round(cx + dx * rr)), int(round(cy + dy * rr))
            if not (0 <= x < w and 0 <= y < h):
                break
            if red[y, x]:
                best = max(best, rr - r)
    return float(best / r) if r else 0.0


# Minimum lobe height, as a fraction of the fitted radius, for a facing to be
# reported at all. Below this the "triangle" is ring roughness and the angle it
# produces is noise -- which matters because a Cypher cam is a PERFECT CIRCLE and
# would otherwise yield a confident, meaningless bearing.
LOBE_MIN_FRAC = 0.22


def _facing(red, cx, cy, r):
    """Bearing of the facing triangle, or None if no real lobe stands out.

    Grant, correcting an earlier claim of mine that a placed ability never
    turns: **a Cypher cam rotates.** It is a perfect circle that never
    translates, and it is the only other moving icon on the widget -- its
    rotation is shown by the camera glyph turning INSIDE the ring, with no lobe
    at all.

    Two consequences, pulling opposite ways:

    * a cam's real rotation is INVISIBLE to this function, because this reads
      the lobe and a cam has none. So rotation measured here cannot be trusted
      to reject a cam -- any value it returns for one is ring roughness. The
      discriminator that does hold against a cam is TRANSLATION;
    * but the absence of a lobe is itself a positive discriminator: a player
      icon has a triangle and a cam does not.

    So `LOBE_MIN_FRAC` is load-bearing, not cosmetic. Without it a perfect
    circle yields a confident bearing from noise, and the motion filter's
    rotation branch would pass exactly the object it most needs to reject.

    Read by rays rather than from the blob's shape: the triangle is the only
    part of the icon outside the fitted circle, so "how far past r does red
    reach at this angle" isolates it without needing the ring to be connected
    to it.
    """
    h, w = red.shape
    reach = np.zeros(N_FACE)
    for k, th in enumerate(_FACE_TH):
        dx, dy = np.cos(th), np.sin(th)
        for rr in np.arange(r + 1, r * 1.9, 0.7):
            x, y = int(round(cx + dx * rr)), int(round(cy + dy * rr))
            if not (0 <= x < w and 0 <= y < h):
                break
            if red[y, x]:
                reach[k] = rr - r
    if reach.max() < LOBE_MIN_FRAC * r:
        return None
    # Weighted mean over the contiguous peak, so the answer is not quantised to
    # one of 32 bins -- rotation is the signal, and a bin width of 11 degrees
    # would swallow most of it.
    k = int(np.argmax(reach))
    ws, xs_, ys_ = 0.0, 0.0, 0.0
    for d in (-2, -1, 0, 1, 2):
        kk = (k + d) % N_FACE
        wgt = reach[kk]
        if wgt <= 0:
            continue
        ws += wgt
        xs_ += wgt * np.cos(_FACE_TH[kk])
        ys_ += wgt * np.sin(_FACE_TH[kk])
    if ws == 0:
        return None
    return float(np.degrees(np.arctan2(ys_, xs_)))


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
# Swept against 164 hand labels on a06f04a0059f, pre-kill pool, at
# inner_red <= 0.25 (which dominates 0.35 and 0.50 on both axes):
#
#     cov_min   recall   precision
#       0.20     86.3%     38.7%
#       0.30     80.8%     54.6%      <- default, with persistence behind it
#       0.35     76.7%     60.9%
#       0.42     54.8%     63.5%
#       0.60     32.9%     77.4%
#
# 0.30 rather than something tighter because PERSISTENCE recovers the precision
# far more cheaply than the threshold does -- at len>=3 this point becomes
# 76.7% / 70.0%, which beats every per-frame cut on both axes at once. Tightening
# `cov` throws away recall that cannot be recovered; letting a track vouch for
# the blob throws away false positives that can.
#
# inner_red 0.25 beats both 0.35 and 0.50 everywhere, and 0.08/0.15 collapse
# recall (38% / 68%) -- the portrait is not uniformly dark, so demanding almost
# no red inside rejects real icons.
#
# Fitted to ONE session. Provisional until a second exists.
COV_MIN, INNER_RED_MAX = 0.30, 0.25
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
