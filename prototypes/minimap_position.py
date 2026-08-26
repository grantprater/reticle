"""PROTOTYPE, not wired into the pipeline: player position off the minimap.

Run it directly; it writes nothing to the store.

    .\\.venv\\Scripts\\python.exe prototypes\\minimap_position.py <session> <from_s> <to_s> <hz> [out.png]

Measured on 9acf02f98283, 60 s at 10 Hz: 86% of frames yield a position, 92%
coverage after filtering and interpolation, 1.5% of steps physically
implausible. Earlier variants are recorded at the bottom -- every one of them
traded recall against jumps without beating this, and knowing which ones failed
is most of the value here.

Why this shape
--------------
The widget is semi-transparent *only over the void*. The walkable floor slab is
opaque, and icons only ever stand on floor, so masking to the floor removes the
churn that defeats every content-based approach: when the player turns, the
world behind the void moves and the whole widget changes.

Per-frame detection does not have to be good, because movement is physically
bounded. A step implying more than RUN_PX px/s is a misdetection whatever the
blob looked like, and gaps shorter than GAP_MS interpolate cleanly. Filtering
the trajectory is worth more than any amount of per-frame tuning.

The static map falls out for free as a per-pixel median across the session --
icons move, map furniture does not. That same image is the occlusion grid a
visibility metric needs, so one extraction serves both.

Known limits
------------
* No elevation. The floorplan is a 2D silhouette, so a bridge and the floor
  beneath it are one region. This is the standing limit on any geometry work.
* Enemies appear on the minimap only while a teammate can see them or a recon
  ability has revealed them, plus red X marks for last-known positions. So the
  minimap carries *what the team knows*, which is the right basis for judging a
  decision even though it is not ground truth.
* Two things on the widget are unread and both are worth more than the player
  dot. Enemy icons carry a **vision arrow**, so the minimap gives enemy *facing*
  as well as position -- which is what "were they holding this angle" needs, and
  it is not available anywhere else. And allies project **vision cones** marking
  the ground the team can actually see.

  The cones are the prize. They are a direct, geometric readout of team vision:
  which angles are covered and which are not, drawn by the game itself. Peeking
  into an angle nobody is watching is a different decision from peeking with a
  teammate covering it, and this distinguishes them without any inference from
  the floorplan. Where dA/ds says how much a peek exposes, the cones say how much
  of that exposure the team already had eyes on.

  Icons come in **states, and the difference between them is time**: a solid icon
  means somebody can see them *now*; a **question mark** means recently revealed,
  shown for a while after vision is lost; an **X marks a death**, red for an
  enemy and blue for an ally.

  The X marks **decay**, so they are not a running tally and cannot serve as the
  alive-count cross-check they first look like -- measured against the killfeed
  at four moments on 9acf02f98283: 4 blue against 4 ally deaths, but 0 red
  against 1 enemy death, 1 red against 5, and 3 red against 5. What they do give
  is *where* a death happened, which the killfeed cannot say at all, plus an
  independent death-event stream whose timing can be checked against it.
  So the minimap does not just say what the team knows, it says how *stale* that
  knowledge is -- and staleness is the whole point for judging a peek. Taking an
  angle where an enemy is visible right now, where one was seen five seconds ago,
  and where one has never been seen are three different decisions, and this is
  the only thing in the capture that separates them.

  Neither needs hand labels: an enemy icon must disappear when that enemy dies,
  and per-team alive counts come from the killfeed, so the detector has an
  external anchor. Hand-labelling should be spent only where no anchor exists.
* Scale is roughly 0.2 m per pixel, from map extent rather than calibration.

Confirming screen detections from the minimap
---------------------------------------------
The minimap shows an enemy while ANY teammate can see them, and the local player
is a teammate -- so **an enemy on screen implies an enemy icon on the minimap**.
The contrapositive is a free precision gate: no enemy icons means every screen
detection in that frame is a false positive. That attacks whole frames rather
than individual blobs, which matters because blob-level filters have run out at
48.8% precision.

**The premise checks out.** Measured against the 46 hand labels on 9acf02f98283:
0 of 43 frames carrying a labelled on-screen enemy had zero red on the minimap.

**A red-pixel count does not implement it.** First attempt scored a median of
3.0 red blobs whether or not an enemy was visible -- no information whatsoever.
The widget is composited over live scenery and transparent everywhere but the
floor, so the count was measuring the wall the player was facing; one frame
scored 39 "blobs", every one a contour on the world behind. Masking to the floor
slab -- the fix this file already carried, and which should have been reused
immediately -- separates the medians to 3.0 against 2.0 and lifts the gate from
11.3% to 16.0% of empty frames dropped at no cost to enemy frames.

**16% is the ceiling for counting; icon discrimination is the requirement.**
Red on the floor is not the same as an enemy being visible: X marks from past
deaths and question marks from stale reveals persist long after the enemy is
gone and keep permitting empty frames. Separating a solid circle-with-portrait
from an X or a question mark is a shape test on a small, opaque, fixed-scale
glyph -- the same problem the killfeed templates already solve.

That classifier is also prerequisite #1 for the stronger version, **bearing
confirmation**: given the player's position and facing and an enemy's position,
the angle to that enemy predicts a screen column, and a detection nowhere near
any real bearing is a false positive. Three notes on feasibility:

* **bearing needs no metric calibration.** It is atan2 of pixel differences on a
  uniform top-down projection, so the shaky 0.2 m/px estimate above never enters;
* **facing must be read from the vision cone**, which renders as a clear white
  wedge. It is not implicitly "up" -- see the capture setting below;
* **it is a coarse gate.** A 2 px position error is ~2 degrees of bearing at 10 m
  but ~8 degrees at 3 m -- roughly 40 px against 140 px of screen. Good for
  rejecting a detection on the wrong side of the screen, not for confirming one
  to the pixel.

**The fixed orientation is a SETTING, not a property of the game.** Grant set the
minimap to fixed -- not rotating with the player, and not swapping sides between
attack and defence -- deliberately, to make parsing tractable. Valorant's
defaults do both. Two consequences:

* it is what makes map geometry genuinely shareable between sessions on the same
  map, and bearings comparable across rounds, which the note above only hoped for;
* a capture recorded with defaults breaks every assumption here **silently** --
  the extractor would still return positions, just rotated or mirrored. It must
  be verified per session, not assumed, and it belongs with the enemy-outline
  colour in the pre-ingest checklist.
* Map identity is unknown. Geometry should be shared between sessions on the
  same map rather than re-derived, which needs a label at ingest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.profiles import get_profile           # noqa: E402

STORE = Path.home() / "reticle-store"
# Top speed of a real track, px/s, measured rather than derived: every filtered
# track sits under it and every misdetection blew far past it.
RUN_PX = 45.0
GAP_MS = 1000.0
# The pale yellow-green the game rings the local player with -- the same colour
# scoreboard.py keys the player's own row on, and it transfers unchanged.
SELF_G_MIN, SELF_R_MIN, SELF_B_UNDER_G = 200, 140, 45
ALLY_H, ALLY_S_MIN, ALLY_V_MIN = (75, 100), 90, 140
MIN_ICON_AREA = 10


def _roi_px(prof, w, h):
    return next(r for r in prof.rois if r.name == "minimap").pixels(w, h)


def static_map(cap, fps, spans, box, n=120):
    """The map with every icon removed, as a per-pixel median."""
    x0, y0, x1, y1 = box
    total = sum(b - a for a, b in spans)
    stride = total / n
    frames = []
    for a, b in spans:
        t = a
        while t < b:
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
            ok, fr = cap.read()
            if ok:
                frames.append(fr[y0:y1, x0:x1])
            t += stride
    return np.median(np.stack(frames), axis=0).astype(np.uint8)


def floor_mask(med):
    """The opaque walkable slab. Everything else is see-through and churns."""
    hsv = cv2.cvtColor(med, cv2.COLOR_BGR2HSV)
    m = (hsv[:, :, 1] < 60) & (hsv[:, :, 2] > 110)
    return cv2.dilate(m.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0


def _rings(mask, floor):
    m = cv2.morphologyEx((mask & floor).astype(np.uint8), cv2.MORPH_CLOSE,
                         np.ones((3, 3), np.uint8))
    n, _lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    return [(int(st[i, 4]), float(cen[i][0]), float(cen[i][1]))
            for i in range(1, n) if st[i, 4] >= MIN_ICON_AREA]


def self_rings(crop, floor):
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    return _rings((g > SELF_G_MIN) & (r > SELF_R_MIN)
                  & ((g - b) > SELF_B_UNDER_G), floor)


def ally_rings(crop, floor):
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = (hsv[:, :, i].astype(np.int16) for i in range(3))
    return _rings((hh > ALLY_H[0]) & (hh < ALLY_H[1])
                  & (ss > ALLY_S_MIN) & (vv > ALLY_V_MIN), floor)


def filter_track(found, step):
    """Drop impossible steps, then interpolate the short gaps they leave."""
    keep = []
    for p in found:
        if keep:
            dt = (p[0] - keep[-1][0]) / 1000.0
            if dt > 0 and np.hypot(p[1] - keep[-1][1], p[2] - keep[-1][2]) / dt > RUN_PX * 1.6:
                continue
        keep.append(p)
    out = []
    for a, b in zip(keep, keep[1:]):
        out.append(a)
        gap = b[0] - a[0]
        if step < gap <= GAP_MS:
            k = int(round(gap / step)) - 1
            for j in range(1, k + 1):
                f = j / (k + 1)
                out.append((a[0] + gap * f, a[1] + (b[1] - a[1]) * f, a[2] + (b[2] - a[2]) * f))
    if keep:
        out.append(keep[-1])
    return out


def main() -> int:
    sid, t0, t1, hz = sys.argv[1], float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h, fps = int(src["width"]), int(src["height"]), float(src["fps"])
    box = _roi_px(prof, w, h)
    x0, y0, x1, y1 = box

    tbl = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    spans = [(a, b) for a, b, s in zip(tbl.column("t_start_ms").to_pylist(),
                                       tbl.column("t_end_ms").to_pylist(),
                                       tbl.column("state").to_pylist()) if s == "active"]

    cap = cv2.VideoCapture(str(src["path"]))
    med = static_map(cap, fps, spans, box)
    floor = floor_mask(med)
    print(f"walkable floor {floor.mean() * 100:.1f}% of the widget")

    step = 1000.0 / hz
    raw, prev, base = [], None, None
    t = t0 * 1000
    while t <= t1 * 1000:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            break
        crop = fr[y0:y1, x0:x1]
        if base is None:
            base = crop.copy()
        cands = self_rings(crop, floor)
        pick = None
        if cands:
            if prev is not None:
                lim = RUN_PX * (step / 1000.0) * 2.0
                near = [c for c in cands if np.hypot(c[1] - prev[0], c[2] - prev[1]) <= lim]
                pick = max(near, key=lambda c: c[0]) if near else None
            if pick is None:
                pick = max(cands, key=lambda c: c[0])
        if pick:
            prev = (pick[1], pick[2])
        raw.append((t, pick[1], pick[2]) if pick else (t, None, None))
        t += step
    cap.release()

    found = [p for p in raw if p[1] is not None]
    track = filter_track(found, step)
    print(f"raw    {len(found)}/{len(raw)} ({len(found) / len(raw) * 100:.1f}%)")
    print(f"filter {len(track)} points ({len(track) / len(raw) * 100:.1f}% coverage)")
    sp = np.array([np.hypot(b[1] - a[1], b[2] - a[2]) / ((b[0] - a[0]) / 1000.0)
                   for a, b in zip(track, track[1:]) if 0 < b[0] - a[0] <= 1.5 * step])
    if sp.size:
        print(f"       px/s median {np.median(sp):.1f}  p95 {np.percentile(sp, 95):.1f}  "
              f"max {sp.max():.1f}   jumps>60: {(sp > 60).mean() * 100:.1f}%")

    if len(sys.argv) > 5:
        vis = cv2.resize(base, None, fx=3, fy=3, interpolation=cv2.INTER_NEAREST)
        for a, b in zip(track, track[1:]):
            cv2.line(vis, (int(a[1] * 3), int(a[2] * 3)), (int(b[1] * 3), int(b[2] * 3)),
                     (0, 255, 255), 2, cv2.LINE_AA)
        for p in track:
            cv2.circle(vis, (int(p[1] * 3), int(p[2] * 3)), 2, (0, 0, 255), -1)
        cv2.imwrite(sys.argv[5], vis)
        print("wrote", sys.argv[5])
    return 0


# What was tried and rejected, measured on the same 60 s window
# -------------------------------------------------------------
#   colour, largest blob             90% found, many jumps -- the A/B site
#                                    boxes are the *same* pale yellow-green as
#                                    the player's ring and are far larger.
#   + size gate                      68%. The ring fragments under the widget's
#                                    transparency, so real icons fail it too.
#   + centroid hole test             18%. A ring has a hole and a site box does
#                                    not, but at 10 px a partial arc's centroid
#                                    lands on ink and the test rejects it.
#   + interior-fill test             31%. Same defect, relaxed and still wrong.
#   persistence mask                 0.0% of the widget marked static. The trick
#                                    that finds the killfeed's overlay boxes
#                                    fails here: transparency makes the site
#                                    boxes' colour swim with the world behind.
#   background differencing          4-7%. The blobs it finds are median BGR
#                                    (40,40,50) -- the world moving behind the
#                                    void, not icons. Fatal for the same reason.
if __name__ == "__main__":
    raise SystemExit(main())
