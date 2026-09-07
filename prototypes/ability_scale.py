"""Measure the ability-icon radius per session, and find a ruler to calibrate it against.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_scale.py <session>...

Why the radius cannot be a constant
-------------------------------------
Recorded 2026-09-03: : **the minimap has a zoom slider**, so the rendered size of
everything on the widget is a per-session setting, not a property of the game.
`ability_disc.py` currently hard-codes `BH_K = 27`, `AREA_MIN/MAX = 40/900` and
`paint_icons.R0 = 7`, all eyeballed on one session -- which is CLAUDE.md's
standing rule ("never test an absolute level against this HUD") arriving as a
size rather than a brightness. A detector tuned to one zoom setting silently
mis-sizes its kernel on any other, and the failure looks like a bad threshold.

The second point is the useful half: **the SCALE varies, the RATIO should not.**
So the fix is not a better constant but a per-session calibration, and the
question this file answers is what to calibrate against.

The candidate ruler is the player's own icon
----------------------------------------------
It is present in almost every frame, it is already fitted by shipped code
(`reticle.minimap.self_rings`), and it is drawn at a fixed real-world size, so
its rendered radius is exactly the zoom factor made visible. If
`icon_radius / self_radius` is constant across sessions with different zoom,
then every size constant in `ability_disc` can be expressed as a multiple of a
number measured per session from one already-validated detector.

How the radius is measured, and why not the way that failed
-------------------------------------------------------------
Two earlier attempts measured icon size by thresholding a patch with Otsu and
both returned "a disc the size of the patch", because the minimap has large dark
regions and Otsu merges the icon into whichever one it touches.

The black-hat does not have that failure mode -- it responds only to dark
structures SMALLER than its kernel -- so the radius is measured from the
black-hat response instead: take its peak at the painted centre, threshold at
half that peak, and take the connected component containing the centre. Half-max
is a shape-free convention rather than a fitted level, which matters because a
level fitted here would reintroduce exactly the per-session constant this file
exists to remove.

Painted centres are what make this measurable at all: the earlier attempts had
to find the icon AND size it at once, and here the position is already known
exactly from `paint_icons.py`.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle import metrics                                       # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from reticle import minimap as mm                                 # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_icons import floor_mask                              # noqa: E402
from ability_disc import disc_response, BH_K                      # noqa: E402
from paint_icons import OUT_DIR, is_world, load_done                        # noqa: E402

STORE = Path.home() / "reticle-store"

#: Fraction of the local peak that bounds the icon. A convention, not a fitted
#: level -- half-maximum is how a width is read off any response profile.
HALF = 0.5


#: Radii sampled outward from a painted centre, in minimap pixels.
RMAX = 22


def icon_radius(g, x, y, rmax=RMAX):
    """Radius of the dark disc at (x, y), from a RADIAL INTENSITY PROFILE.

    **Read a profile before choosing a rule.** Four attempts failed first, and
    printing three real profiles settled it in one look -- the convention this
    repo already records ("in vision work, look at the image before measuring
    it"), ignored again here at the cost of four iterations. A sonic sensor:

        r:    0   1   2   3   4   5   6   7   8   9  10  11  12 ...
            72  86 193 240 179  95 117 107  52  21  29 100 151 ...
                 |white glyph|             |dark rim|   |background

    An ability icon is **bright line art INSIDE a dark rim**, so the profile is
    not monotonic and every rule that assumed it was got a wrong answer:
    half-max of the black-hat measured the rim's THICKNESS (1.1-6.7 px, no
    consistency between classes -- it responds to the edge, the same property
    that made `ability_disc.CIRC_MIN = 0.45` reject real icons), and a
    half-height crossing outward from the centre stopped at the glyph (1-2 px).

    What is well defined is the OUTER boundary: the largest radius still
    deviating from the surrounding map. So take the background from the outer
    ring, and return the outermost radius whose deviation is at least half the
    largest deviation seen. Half is a convention for reading a width, not a
    fitted level -- which matters, because a fitted level here would be exactly
    the per-session constant this file exists to remove.
    """
    h, w = g.shape
    prof = []
    for r in range(rmax + 1):
        if r == 0:
            prof.append(float(g[y, x]) if 0 <= y < h and 0 <= x < w else np.nan)
            continue
        th = np.linspace(0, 2 * np.pi, max(8, int(2 * np.pi * r)), endpoint=False)
        xs = np.clip((x + r * np.cos(th)).astype(int), 0, w - 1)
        ys = np.clip((y + r * np.sin(th)).astype(int), 0, h - 1)
        prof.append(float(g[ys, xs].mean()))
    prof = np.array(prof, float)
    back = float(np.nanmedian(prof[rmax - 5:]))       # the map around the icon
    dev = np.abs(prof - back)
    inner = dev[:rmax - 4]
    if not np.isfinite(back) or not len(inner) or np.nanmax(inner) < 20:
        return None, prof                            # no icon here to measure
    thr = HALF * float(np.nanmax(inner))
    sig = [r for r in range(len(inner)) if np.isfinite(inner[r]) and inner[r] >= thr]
    return (float(max(sig)), prof) if sig else (None, prof)


def measure(sid):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    floor = floor_mask(static, dilate=1)
    rows = {t: r for t, r in load_done(OUT_DIR / f"{sid}.jsonl").items()
            if r.get("exhaustive") and not r.get("unsure")}
    cap = cv2.VideoCapture(src["path"])
    icons, selves, by_class = [], [], {}
    for t, row in sorted(rows.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        if crop.shape[:2] != static.shape[:2]:
            continue
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        bh = disc_response(g, BH_K)
        rings = mm.self_rings(crop, floor)
        if rings:
            a = max(r[0] for r in rings)
            selves.append(float(np.sqrt(a / np.pi)))
        for ic in row["icons"]:
            if is_world(ic):
                continue
            r, _p = icon_radius(g, int(ic["x"]), int(ic["y"]))
            if r:
                icons.append(r)
                by_class.setdefault(ic.get("category_id", "?"), []).append(r)
    cap.release()
    return {"sid": sid, "widget_w": mx1 - mx0, "icons": icons, "selves": selves,
            "by_class": by_class}


def med(a):
    return float(np.median(a)) if len(a) else float("nan")


#: Measured 2026-09-03 on two sessions at different zoom: an ability icon's
#: outer radius is this multiple of the self icon's equivalent radius. The two
#: sessions agree to 2% (1.858 and 1.824) while their icon radii differ by 67%,
#: which is the evidence that the self icon is a valid ruler and that the size
#: is a per-session SETTING rather than a property of the game.
ICON_PER_SELF = 1.84

#: Derived from the shipped constants at the session they were eyeballed on
#: (`a06f04a0059f`, icon radius 10): BH_K 27 ~ 2.7r, AREA 40..900 ~ 0.4r^2..9r^2.
#: Expressing them as ratios is the whole point -- the numbers stay what they
#: were on that session and now move correctly on any other.
K_PER_R, AREA_LO_PER_R2, AREA_HI_PER_R2 = 2.7, 0.4, 9.0


def self_radius(sid, n_frames=24):
    """Median self-icon radius over sampled frames -- the per-session ruler.

    Uses `reticle.minimap.self_rings`, which is shipped and validated for a
    different job. Reusing a working detector to calibrate another is the one
    move that has repeatedly worked here (`self_icon_dist` is the same trick).
    """
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    _labels, static = md.load_geometry(sid)
    floor = floor_mask(static, dilate=1)
    cap = cv2.VideoCapture(src["path"])
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    rs = []
    for f in np.linspace(0, max(0, n - 2), n_frames):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        if crop.shape[:2] != static.shape[:2]:
            continue
        rings = mm.self_rings(crop, floor)
        if rings:
            rs.append(float(np.sqrt(max(r[0] for r in rings) / np.pi)))
    cap.release()
    return med(rs), len(rs)


def calibrate(sid):
    """Per-session icon geometry, derived rather than hard-coded.

    Returns None when the self icon was never found, so a caller falls back to
    the shipped constants rather than silently using a nonsense scale -- the
    `reticle` rule that a field which cannot be read stays null.
    """
    sr, n = self_radius(sid)
    if not np.isfinite(sr) or n < 4:
        return None
    r = sr * ICON_PER_SELF
    k = int(round(K_PER_R * r))
    return {"self_r": round(sr, 2), "icon_r": round(r, 2), "n_frames": n,
            "bh_k": k + 1 - k % 2,                    # morphology wants odd
            "area": (int(AREA_LO_PER_R2 * r * r), int(AREA_HI_PER_R2 * r * r))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="+")
    args = ap.parse_args()

    out = [measure(s) for s in args.sessions]
    print(f"\n   {'session':<16}{'widget':>8}{'n':>5}{'icon r':>9}{'self r':>9}"
          f"{'icon/self':>11}")
    for o in out:
        ir, sr = med(o["icons"]), med(o["selves"])
        print(f"   {o['sid']:<16}{o['widget_w']:>8}{len(o['icons']):>5}"
              f"{ir:>9.2f}{sr:>9.2f}{ir / sr if sr else float('nan'):>11.3f}")
    for o in out:
        print(f"\n   {o['sid']} by class:")
        for k, v in sorted(o["by_class"].items()):
            print(f"      {k:<28} n={len(v):3d}  median r = {med(v):.2f}"
                  f"   (p10 {np.percentile(v, 10):.2f}, p90 {np.percentile(v, 90):.2f})")

    if len(out) >= 2:
        a, b = out[0], out[1]
        ira, irb = med(a["icons"]), med(b["icons"])
        sra, srb = med(a["selves"]), med(b["selves"])
        print(f"\n   between-session ratios ({a['sid']} / {b['sid']}):")
        print(f"      icon radius   {ira / irb:6.3f}")
        print(f"      self radius   {sra / srb:6.3f}")
        print(f"      widget width  {a['widget_w'] / b['widget_w']:6.3f}")
        print(f"      icon/self     {(ira / sra) / (irb / srb):6.3f}"
              f"   <- 1.000 means the self icon is a valid per-session ruler")
        metrics.record(
            "ability_scale", part="ratio", session="+".join(args.sessions),
            values={"icon_r_a": round(ira, 3), "icon_r_b": round(irb, 3),
                    "self_r_a": round(sra, 3), "self_r_b": round(srb, 3),
                    "icon_ratio": round(ira / irb, 4),
                    "iconself_consistency": round((ira / sra) / (irb / srb), 4)},
            deps={"method": metrics.fingerprint(icon_radius, measure, HALF=HALF,
                                                BH_K=BH_K)},
            context={"n_a": len(a["icons"]), "n_b": len(b["icons"])},
        )
        print()
        print(metrics.report(tool="ability_scale"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
