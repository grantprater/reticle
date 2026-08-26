"""Validate the facing readout against the camera, using the player's own icon.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_self_check.py <session> [--from 12:00] [--seconds 60]

Grant's idea, and it supplies something this project almost never gets: a
**label-free, continuous ground truth** for the feature the icon finder now
leans on hardest.

The argument. Rotation is what separates a player icon from a placed ability --
a Cypher cam never turns -- so `minimap_ring_fit._facing` is now load-bearing,
and it was validated on exactly one hand-checked icon. But the local player's
own icon is on the widget in every frame, is definitionally a player icon, and
its facing is *independently observable from the screen*: turn the mouse and the
world pans. Phase correlation on the main view gives camera yaw per frame, and
if `_facing` is measuring what it claims, the icon's triangle must rotate with
it.

That makes this a test with a known-correct answer, available on every session
ever recorded, with no labelling at all -- the same class of check as the
killfeed anchor, and for the same reason it is worth more than another
threshold sweep.

It also doubles as the training/control case Grant suggested: the own icon is a
guaranteed positive for "this is a player icon", so anything measured on it
(ring coverage, radius, how often the triangle is readable) is a floor on what
the finder should manage on an enemy, under identical capture conditions.

What it cannot do. The own icon is drawn in the self colour, not enemy red, so
this validates the GEOMETRY -- ring fit, triangle angle, rotation tracking -- and
not the red mask. And a stationary player rotates the camera without moving,
which is the case that matters here anyway.

RESULT (2026-08-26, three windows chosen for having real camera motion)
-----------------------------------------------------------------------
                     corr(signed)    icon rotation: camera still -> turning
    26:20               -0.00             9.0 deg -> 35.9 deg
    15:40               -0.04             8.3 deg -> 43.0 deg
    29:40               -0.07             2.2 deg -> 16.6 deg

**Magnitude is validated; direction is not.** Turning the camera reliably makes
the icon's triangle move four to five times as much as holding it still, across
every window. That is precisely the use the finder makes of it -- `rot >= 15 deg`
as evidence that a blob is a player rather than a Cypher cam -- so the feature
the motion filter depends on now has a label-free check behind it, on a signal
present in every session ever recorded.

The SIGNED direction does not correlate at all, so `facing` must NOT yet be used
as a bearing -- "which way is this enemy looking" is not supported by this
evidence, and that was one of the hoped-for downstream uses. The likeliest cause
is the reference, not the icon: phase correlation on a 4x-downscaled patch
aliases once the pan between samples is large, so its sign goes unreliable while
its magnitude still says "a lot of motion". Testing that needs a yaw estimate
that does not wrap, which this does not attempt.

A first attempt at this measured nothing at all (corr -0.03) because the window
picked had NO camera motion in it -- pan of +/-0.1 px, the player standing
still. Check the pan distribution before believing a null result here. That run
did establish the noise floor, which is worth having: at rest the facing reads
80 deg +/- 5.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
import minimap_ring_fit as rf                                      # noqa: E402
from minimap_icons import floor_mask, static_map                   # noqa: E402
from minimap_position import SELF_B_UNDER_G, SELF_G_MIN, SELF_R_MIN  # noqa: E402
from reticle.profiles import get_profile                           # noqa: E402

STORE = Path.home() / "reticle-store"


def self_mask(crop):
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    return (g > SELF_G_MIN) & (r > SELF_R_MIN) & ((g - b) > SELF_B_UNDER_G)


def camera_yaw(prev_grey, grey):
    """Horizontal pan between two frames, in pixels, by phase correlation.

    World only: the HUD does not move with the camera and including it drags the
    estimate toward zero. Same patch and same reasoning as the screen tracker's
    `_world_grey`, which had this exact measurement working already.
    """
    (dx, _dy), _resp = cv2.phaseCorrelate(prev_grey, grey)
    return float(dx)


def _world_grey(fr):
    h, w = fr.shape[:2]
    g = cv2.cvtColor(fr[int(0.20 * h):int(0.75 * h), int(0.15 * w):int(0.85 * w)],
                     cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (g.shape[1] // 4, g.shape[0] // 4), interpolation=cv2.INTER_AREA)
    return np.float32(g) * cv2.createHanningWindow((g.shape[1], g.shape[0]), cv2.CV_32F)


def parse_t(s):
    if ":" in s:
        m, sec = s.split(":")
        return int(m) * 60 + float(sec)
    return float(s)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--from", dest="t0", default="12:00")
    ap.add_argument("--seconds", type=float, default=60.0)
    ap.add_argument("--hz", type=float, default=10.0)
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    r = next(x for x in prof.rois if x.name == "minimap")
    x0, y0, x1, y1 = r.pixels(int(src["width"]), int(src["height"]))

    cap = cv2.VideoCapture(str(src["path"]))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    med = []
    for i in np.linspace(0, tot - 1, 150).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            med.append(fr[y0:y1, x0:x1])
    floor = floor_mask(static_map(med))

    t0 = parse_t(args.t0)
    step_f = max(1, int(round(fps / args.hz)))
    n = int(args.seconds * args.hz)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t0 * fps)))

    prev_g, rows = None, []
    for k in range(n):
        ok, fr = cap.read()
        if not ok:
            break
        for _ in range(step_f - 1):
            cap.read()
        g = _world_grey(fr)
        dx = camera_yaw(prev_g, g) if prev_g is not None else None
        prev_g = g
        crop = fr[y0:y1, x0:x1]
        m = (self_mask(crop) & floor)
        nn, lbl, st, cen = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
        cand = [i for i in range(1, nn) if st[i, 4] >= 25]
        face = None
        if cand:
            i = max(cand, key=lambda i: st[i, 4])
            f = rf.fit_ring(m, cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY),
                            cen[i][0], cen[i][1])
            if f is not None:
                face = f["facing"]
        rows.append((t0 + k / args.hz, dx, face))
    cap.release()

    got = sum(1 for _t, _d, f in rows if f is not None)
    print(f"{args.session} {args.t0} +{args.seconds:.0f}s at {args.hz:g} Hz: "
          f"{len(rows)} frames, own icon facing read in {got} ({got/max(len(rows),1)*100:.0f}%)")

    pairs = []
    for (ta, da, fa), (tb, db, fb) in zip(rows, rows[1:]):
        if fa is None or fb is None or db is None:
            continue
        pairs.append((db, (fb - fa + 180) % 360 - 180))
    if len(pairs) < 10:
        print("not enough paired samples")
        return 1
    P = np.array(pairs)
    cam, rot = P[:, 0], P[:, 1]
    # Phase correlation wraps on large pans and the icon angle wraps at +/-180;
    # drop the frames where either is near its wrap so the correlation measures
    # agreement rather than aliasing.
    ok = (np.abs(cam) < 60) & (np.abs(rot) < 150)
    cam, rot = cam[ok], rot[ok]
    print(f"paired samples {len(P)}, usable after wrap-guard {len(cam)}")
    if len(cam) >= 10:
        cc = float(np.corrcoef(cam, rot)[0, 1])
        k = float(np.polyfit(cam, rot, 1)[0])
        print(f"\ncorr(camera pan px, icon rotation deg) = {cc:+.3f}")
        print(f"slope = {k:+.2f} deg of icon per px of pan")
        print(f"\n  camera still (|pan|<2 px): icon rotation "
              f"median {np.median(np.abs(rot[np.abs(cam) < 2])):.1f} deg")
        big = np.abs(cam) > 8
        if big.any():
            print(f"  camera turning (|pan|>8 px): icon rotation "
                  f"median {np.median(np.abs(rot[big])):.1f} deg")
        print("\nA strong positive correlation validates _facing against a signal")
        print("that needs no labels and exists in every session ever recorded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
