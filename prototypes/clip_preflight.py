r"""Check a freshly recorded capture BEFORE it is ingested.

    .\.venv\Scripts\python.exe prototypes\clip_preflight.py <video>... [--map lotus] [--n 15]

Why this exists, 2026-09-03
-----------------------------
the player records a sitting of one-agent demo clips back to back, and CLAUDE.md's
"Before ingesting any new capture" checklist is a list of settings that break
things SILENTLY -- extraction still returns answers, they are merely wrong. The
first clip of this sitting proved it: minimap orientation was left on
side-based, so the whole widget was rotated 180 degrees and nothing downstream
would have said so. A per-clip check costs seconds; finding it later costs the
sitting.

What it compares against, 2026-10-05
------------------------------------
Each map's asset drawn through each fitted profile's transform
(`reticle/map_asset.py`), not one donor capture. The donor was one Ascent
match; two Lotus captures at the same settings failed it on widget rows, left
edge and correlation, because Lotus is not Ascent. Each candidate static is
fitted to the capture's median corner by `reticle.widget_frame.fit_crop`
(rotation, scale, translation): the transform that places the capture's widget
over the map's asset. The best fit names the map and profile. `--map` names the map the player recorded;
a better fit on another map is then reported as a mismatch.

What it checks:

    map            the named map's fit against the best other map's
    widget size    the fitted scale is 1 and the widget's corner sits on the
                   profile's ROI corner: the capture draws a fitted profile
    orientation    the fitted rotation is 0 (180 is a side-based widget)
    top-left ROI   the capture's white line-work reaches no further left than
                   the reference's: nothing is drawn over the minimap

The capture median makes the checks readable at all: the widget is
SEMI-TRANSPARENT over live scenery, so a single frame carries the world moving
behind it. WARNING: this is the sole non-builder capture median allowlisted
by `doctor`. It may set only the widget's size, placement and orientation; it
must never become a floor mask, lighting reference, detector background or
cached base map.

Reports, never fixes. A failure here is a capture setting, not a code change.
The per-frame placement segments it prints (`--placements`) are what
`reticle widget-fit --write` stores on the manifest after ingest.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
STORE = Path.home() / "reticle-store"
W = H = 560
N = 15
#: Fitted scale and corner within these of the profile's own: a fitted profile.
SCALE_TOL = 0.02
CORNER_TOL = 6
#: A named map loses when another map fits better by more than this ncc.
MAP_MARGIN = 0.03


def corner_frames(path: str, n: int = N, meta: dict | None = None):
    """`(t_ms, top-left corner)` of `n` frames spread over the capture.

    `meta`, when given, receives the frame count, fps and decoded indices."""
    cap = cv2.VideoCapture(str(path))
    tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 60.0
    out, idx = [], []
    for i in np.linspace(tot * 0.05, tot * 0.95, n).astype(int):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
        ok, fr = cap.read()
        if ok:
            out.append((i * 1000.0 / fps, fr[:H, :W].copy()))
            idx.append(int(i))
    cap.release()
    if not out:
        raise SystemExit(f"{path}: decoded no frames")
    if meta is not None:
        meta.update(frame_count=tot, fps=fps, frame_indices=idx,
                    t_ms=[float(t) for t, _ in out])
    return out


def median_corner(path: str, n: int = N, frames=None):
    """Capture median for widget geometry checks only; never map extraction."""
    buf = [f for _, f in (frames or corner_frames(path, n))]
    return np.median(np.stack(buf), 0).astype(np.uint8)


def drawn_static(key: str) -> np.ndarray:
    """The key's static, drawn from the map's asset through the profile's transform."""
    from reticle import geometry as G
    return G.reference_for_key(key, STORE)


def roi_of(profile: str) -> tuple[int, int, int, int]:
    from reticle.profiles import get_profile
    return next(r for r in get_profile(profile).rois if r.name == "minimap").pixels(1920, 1080)


def candidates(map_name: str | None) -> list[str]:
    """Every key the game's files can draw: each map with textures and a
    rotation, at each fitted profile."""
    from reticle import geometry as G
    from reticle import map_asset as A
    maps = [map_name] if map_name else sorted(A.maps(STORE))
    return [k for m in maps for prof in sorted(A.transforms())
            if G.drawable(k := G.key(m, prof), STORE)]


def fit_key(med, key: str) -> dict | None:
    """`fit_crop` of the key's official static on the median corner, in frame px."""
    from reticle import widget_frame as wf
    f = wf.fit_crop(drawn_static(key), med, (0, 0))
    if f is None:
        return None
    a = np.asarray(f["affine"])
    return dict(f, key=key, corner=(float(a[0, 2]), float(a[1, 2])))


def placements(frames, key: str):
    """The widget's placement segments against `key`'s official static, fitted
    per frame (`reticle.widget_frame`), in full-frame pixels."""
    from reticle import widget_frame as wf
    static = drawn_static(key)
    fits = [(t, wf.fit_crop(static, f, (0, 0))) for t, f in frames]
    return wf.placement_segments(fits), static.shape[:2]


def reference_corner(key: str, fill) -> np.ndarray:
    """The official static pasted where its profile draws it, on `fill`."""
    from reticle import geometry as G
    st = drawn_static(key)
    x0, y0, _x1, _y1 = roi_of(G.parse(key)[1])
    out = np.empty((H, W, 3), np.uint8)
    out[:] = fill
    h, w = min(st.shape[0], H - y0), min(st.shape[1], W - x0)
    out[y0:y0 + h, x0:x0 + w] = st[:h, :w]
    return out


def linework_bbox(med, roi):
    """Bounding box of the map's white line-work, measured INSIDE `roi`, in
    full-frame coordinates. Inside, because the Neon clip drew a bright band
    down the frame's left edge, outside the widget entirely."""
    x0, y0, x1, y1 = roi
    g = cv2.cvtColor(med[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    m = (g > np.percentile(g, 99.0)).astype(np.uint8)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    return (int(xs.min()) + x0, int(ys.min()) + y0,
            int(xs.max()) + x0, int(ys.max()) + y0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("videos", nargs="+")
    ap.add_argument("--map", default=None, help="the map the player recorded")
    ap.add_argument("--n", type=int, default=N, help="frames to decode per video")
    ap.add_argument("--placements", action="store_true",
                    help="also fit the placement per decoded frame against the best key")
    a = ap.parse_args()
    from reticle import geometry as G

    allkeys = candidates(None)
    bad = 0
    for v in a.videos:
        frames = corner_frames(v, a.n)
        med = median_corner(v, a.n, frames)
        fits = sorted((f for f in (fit_key(med, k) for k in allkeys) if f),
                      key=lambda f: -f["ncc"])
        print(f"{Path(v).name}   ({len(frames)} frames decoded)")
        if not fits:
            print("   FAIL  no official key fits the widget at all\n")
            bad += 1
            continue
        for f in fits[:4]:
            print(f"   fit  {f['key']:34s} ncc {f['ncc']:+.3f}  rotation {f['rotation']}  "
                  f"scale {f['scale']:.3f}  corner ({f['corner'][0]:.1f}, {f['corner'][1]:.1f})")
        best = fits[0]
        if a.map:
            pick = next((f for f in fits if G.parse(f["key"])[0] == a.map), None)
            other = next((f for f in fits if G.parse(f["key"])[0] != a.map), None)
            map_ok = pick is not None and (other is None or other["ncc"] - pick["ncc"] <= MAP_MARGIN)
            print(f"   [{'ok' if map_ok else 'FAIL'}] map           named {a.map} "
                  f"{'no fit' if pick is None else format(pick['ncc'], '+.3f')}; best other "
                  f"{other['key'] if other else 'none at fit_crop MIN_NCC'} "
                  f"{format(other['ncc'], '+.3f') if other else ''}")
            best = pick or best
        else:
            map_ok = True
            print(f"   [--] map           unnamed; best fit {G.parse(best['key'])[0]}")
        prof = G.parse(best["key"])[1]
        rx0, ry0, rx1, ry1 = roi_of(prof)
        size_ok = (abs(best["scale"] - 1.0) <= SCALE_TOL
                   and abs(best["corner"][0] - rx0) <= CORNER_TOL
                   and abs(best["corner"][1] - ry0) <= CORNER_TOL)
        ok_o = best["rotation"] == 0
        roi = (rx0, ry0, min(rx1, W), min(ry1, H))
        bb = linework_bbox(med, roi)
        fill = np.median(med[roi[1]:roi[3], roi[0]:roi[2]].reshape(-1, 3), 0)
        rb = linework_bbox(reference_corner(best["key"], fill), roi)
        left_ok = bb is not None and rb is not None and bb[0] >= rb[0] - CORNER_TOL
        print(f"   [{'ok' if size_ok else 'FAIL'}] widget size   {prof}: scale {best['scale']:.3f}, "
              f"corner ({best['corner'][0]:.1f}, {best['corner'][1]:.1f}) vs ROI ({rx0}, {ry0})"
              f"{'' if size_ok else '   <- a variant placement: widget-fit stores it'}")
        print(f"   [{'ok' if ok_o else 'FAIL'}] orientation   rotation {best['rotation']}"
              f"{'' if ok_o else '   <- side-based minimap'}")
        print(f"   [{'ok' if left_ok else 'FAIL'}] top-left ROI  line-work left edge "
              f"{bb[0] if bb else None} vs the reference's {rb[0] if rb else None}"
              f"{'' if left_ok else '   <- something is drawn over the minimap'}")
        if a.placements:
            segs, _shape = placements(frames, best["key"])
            for sg in segs:
                m = np.asarray(sg["affine"])
                print(f"   placement     from {sg['t0_ms']} ms: rotation {sg['rotation']}, "
                      f"scale {sg['scale']:.3f}, corner ({m[0, 2]:.1f}, {m[1, 2]:.1f}), "
                      f"{sg['n']} frames")
        if not (map_ok and size_ok and ok_o and left_ok):
            bad += 1
        print()
    print(f"{len(a.videos) - bad}/{len(a.videos)} captures pass")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
