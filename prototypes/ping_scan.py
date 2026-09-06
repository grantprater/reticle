r"""Run the ping detector over a bare video file, and render what it found.

    .\.venv\Scripts\python.exe prototypes\ping_scan.py <video> [--sheet out.png]

**The detector is not here.** It is `reticle/ping.py`, because a reader that
ships is a reader that rides a pass -- see that module's opening and the "a new
reader joins the PASS" convention in `CLAUDE.md`. On a session, pings come off
`reticle scan` for free; this file is what remains once that is true:

* a **video path** entry point, for a clip the player recorded that is not a session
  and does not need to be one;
* the **contact sheet**, which is the only way to check a hit by eye.

`scan()` here holds every crop so it can build its own static map -- the median
does not exist until the pass is over. That is affordable for a 65 s clip and
is exactly what does not scale, which is why `PingReader` takes a floor mask
instead of deriving one. Keep this path for clips.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.decode import sample_at, sample_frames                # noqa: E402
from reticle.minimap import floor_mask                             # noqa: E402
from reticle.ping import (LIFETIME_S, Grouper, resolve,            # noqa: E402
                          sightings)
from reticle.store import Store                                    # noqa: E402

#: The `valorant-16x9-bigmap` minimap ROI at 1080p, as pixels. A session takes
#: this from its profile (`minimap.minimap_roi_px`); a bare clip has no
#: manifest to ask, so the widget size is an assumption here and nowhere else.
MINIMAP_ROI = (15, 15, 480, 500)


def scan(path: str, roi=MINIMAP_ROI, hz: float = 10.0, fps: float = 60.0):
    """[(kind, t0, t1, x, y, hue, n_frames)] for every ping in a video file.

    One sequential decode of its own, which is what a bare clip costs. The
    detection is `reticle.ping`'s, called frame by frame exactly as the reader
    calls it, so there is one definition of what a ping is and this path cannot
    drift from the shipped one.
    """
    x0, y0, x1, y1 = roi
    frames, ts = [], []
    for smp in sample_frames(path, hz, fps, None):
        frames.append(smp.frame[y0:y1, x0:x1].copy())
        ts.append(smp.t_ms / 1000.0)
    if not frames:
        return [], None
    med = np.median(np.stack(frames[::3]), axis=0).astype(np.uint8)
    floor = floor_mask(med)
    g = Grouper()
    for t, c in zip(ts, frames):
        for x, y, hue in sightings(c, floor):
            g.add(t, x, y, hue)
    hits, unconfirmed, rejected = resolve(g, ts, hz)
    return hits, (med, floor, unconfirmed, rejected)


def sheet(path: str, hits, out_path: str, hz: float, roi=MINIMAP_ROI) -> None:
    """Every hit, magnified 8x, one second after it appears.

    One second in rather than at the birth frame: the glyph is settled by then,
    and a sheet is worth exactly what a glance can take off it.
    """
    x0, y0, x1, y1 = roi
    frames: dict[float, np.ndarray] = {}
    for s in sample_at(path, sorted((h[1] + 1.0) * 1000 for h in hits), 60.0):
        frames.setdefault(round(s.t_ms / 1000.0, 1), s.frame[y0:y1, x0:x1].copy())
    tiles = []
    R, Z = 20, 8
    for kind, t0, _t1, x, y, _hue, n in hits:
        f = frames.get(round(t0 + 1.0, 1))
        if f is None:
            continue
        cy0, cy1 = max(0, y - R), min(f.shape[0], y + R)
        cx0, cx1 = max(0, x - R), min(f.shape[1], x + R)
        tl = cv2.resize(f[cy0:cy1, cx0:cx1], (Z * (cx1 - cx0), Z * (cy1 - cy0)),
                        interpolation=cv2.INTER_NEAREST)
        cv2.putText(tl, f"{kind} {n / hz:.1f}s", (3, 16),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 255), 1)
        tiles.append(tl)
    if not tiles:
        return
    h = max(t.shape[0] for t in tiles)
    w = max(t.shape[1] for t in tiles)

    def pad(t):
        o = np.zeros((h, w, 3), np.uint8)
        o[:t.shape[0], :t.shape[1]] = t
        return o

    tiles = [pad(t) for t in tiles]
    cols = 5
    while len(tiles) % cols:
        tiles.append(np.zeros((h, w, 3), np.uint8))
    grid = np.vstack([np.hstack(tiles[i:i + cols])
                      for i in range(0, len(tiles), cols)])
    cv2.imwrite(out_path, grid)


def session_sheet(session: str, out_path: str, store=None) -> int:
    """The same sheet, over pings `reticle scan` already emitted for a session.

    The check that matters on match footage, and the reason it is here rather
    than in the package: `scan` writes events without ever rendering one, so
    without this nobody has looked at a single match ping.
    """
    store = store or Store()
    man = store.read_manifest(session)
    rows = store.read_events("ping", session)
    if not rows:
        print(f"no ping events for {session} -- run `reticle scan {session}`")
        return 1
    from reticle.minimap import minimap_roi_px
    from reticle.profiles import get_profile

    src = man["source"]
    roi = minimap_roi_px(get_profile(man["source_profile"]),
                         int(src["width"]), int(src["height"]))
    hits = [(r["kind"], r["t_ms"] / 1000.0, None, r["x"], r["y"], r["hue"],
             int(round(r["lifetime_s"] * 10))) for r in rows]
    sheet(src["path"], hits, out_path, 10.0, roi)
    print(f"{len(hits)} pings -> {out_path}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", help="a video path, or --session's id")
    ap.add_argument("--session", action="store_true",
                    help="treat the argument as a session id and render the "
                         "pings `reticle scan` already emitted for it")
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--sheet", default=None, help="render every hit, magnified")
    a = ap.parse_args(argv)

    if a.session:
        return session_sheet(a.video, a.sheet or f"pings_{a.video}.png")

    hits, aux = scan(a.video, hz=a.hz)
    unconfirmed = aux[2] if aux else []
    rejected = aux[3] if aux else []
    print(f"{len(hits)} pings, {len(unconfirmed)} unconfirmed (clip ended), "
          f"{len(rejected)} refused on lifetime\n")
    print(f"{'kind':<15}{'t0':>7}{'life':>7}{'pos':>12}{'hue':>5}  class life")
    for kind, t0, _t1, x, y, hue, n in hits:
        print(f"{kind:<15}{t0:7.1f}{n / a.hz:7.1f}{f'({x},{y})':>12}{hue:5d}"
              f"  {LIFETIME_S[kind]:g}s")
    for kind, t0, _t1, x, y, hue, n in unconfirmed:
        print(f"{kind:<15}{t0:7.1f}{n / a.hz:7.1f}{f'({x},{y})':>12}{hue:5d}"
              f"  UNCONFIRMED, clip ended")
    if rejected:
        lives = sorted(round(n / a.hz, 1) for *_r, n in rejected)
        by: dict[str, int] = {}
        for kind, *_r in rejected:
            by[kind] = by.get(kind, 0) + 1
        print(f"\nrefused        {len(rejected)}, lifetimes {lives[0]}-{lives[-1]}s"
              f"   " + ", ".join(f"{k} x{v}" for k, v in sorted(by.items())))

    if a.sheet:
        sheet(a.video, hits, a.sheet, a.hz)
        print(f"\nsheet   {a.sheet}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
