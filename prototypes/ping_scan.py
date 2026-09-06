r"""Find pings on the minimap, and emit them as events.

    .\.venv\Scripts\python.exe prototypes\ping_scan.py <video> [--emit <session>]
    .\.venv\Scripts\python.exe prototypes\ping_scan.py <video> --sheet out.png

What a ping actually is, measured 2026-09-05
--------------------------------------------
the player recorded two clips for this -- a 65 s spam of four types, and a second
clip for the fifth -- and the first thing they settled is what a ping is NOT.

**It does not expand.** At 60 Hz there is nothing at 7.133 s and a full-size
diamond at 7.150 s, which then sits static for its whole life. No growth phase,
no ring, no arcs. So the entity model needs no fourth `extent` value: a ping is
`origin=fixed, bearing=absent, extent=none`, the same parameter shape as a
deployed device. Its identity is in the GLYPH and its LIFETIME, and NOTES.md
carries why that matters for the object-grouping labelling pass.

**The lifetime is a constant, and it is the strongest feature here.** Over
fifteen instances every ping was drawn for either exactly 7.0 s or exactly
10.0 s, with no spread at all at a 10 Hz sample:

    standard        cyan diamond      hue  82     7.0 s   (n=6)
    need help       orange flag       hue  17-18  7.0 s   (n=4)
    watching here   purple eye        hue 145     7.0 s   (n=1)
    danger          red triangle      hue 174    10.0 s   (n=4)
    on my way       yellow stopwatch  hue  32     --      (its own clip)

Danger lasting longer than the rest is worth knowing before anyone tunes a
persistence window: a single threshold at "about 8 seconds" cuts exactly one
class in half.

Why colour is allowed here, given the standing rule
---------------------------------------------------
`CLAUDE.md`: *never test an absolute level against this HUD*, because it is
composited over live scenery. That rule is followed rather than broken, in the
form the same section prescribes -- **structure first, then colour for
identity**.

The structure is `minimap.floor_mask`: the opaque slab. The map body is grey
and nothing behind the widget shows through it, so a SATURATED object on the
floor is by construction something drawn on top. Hue then answers only "which
of the five is it", which is what the convention says level is for.

Take the structure away and this collapses immediately, and the clip proves
it: the warm Sunset scenery reads at hue 10-22 through the semi-transparent
void, the same band as the `need help` flag. A saturation threshold over the
whole widget returned 640 marks of which almost none were pings. **A ping
finder cannot be a colour threshold over the ROI.**

Limits, stated because the numbers look better than they are
-------------------------------------------------------------
* **one map, one widget size, one sitting.** Sunset, bigmap. The hues are of a
  glyph drawn over a grey slab so they ought to be stable, but that is an
  argument, not a measurement;
* **n=1 for `watching here`**, and `on my way` appears only in its own clip.
  The lifetimes of those two are assumed from the other three, not observed;
* ~~a ping over the VOID is invisible to this~~ -- **ANSWERED by the player,
  2026-09-05, and it is a guarantee rather than a limitation: YOU CANNOT PING
  INTO THE VOID.** *If you ping in a hole it snaps to the nearest minimap
  border; if you ping in the void outside the ping just doesn't work at all.*

  So every ping that exists is on the map body or snapped to its border, and
  the floor-mask gate this detector is built on is not merely convenient -- it
  is aligned with the game's own behaviour. There is no population of pings
  this cannot see, which was the largest unknown in the list above.

  The residue is narrower and worth keeping: a ping SNAPPED to a border sits on
  the white line-work, which `floor_mask` reaches only through its 9 px
  dilation and which is the noisiest part of the widget (BORDER carries the
  highest within-state SD of any class, and the player painted only ~47% of border
  pixels as searchable). Border-snapped pings are the ones to check first on
  match footage, not void pings -- those do not exist;
* **`on my way` (hue 32) sits closer to `need help` (17-22) than any other
  pair.** Those two are what to watch on a different map.

The lifetime is a GATE, and it had to become one
------------------------------------------------
The first run of this reported lifetime as a check beside the answer, and the
check turned out to be the detector. Hue alone found the 15 real pings and
**24 false ones**, every one of them warm Sunset scenery in the `need help`
band, seen through a part of the widget the floor mask does not quite exclude.
Every single false positive lasted under 5.1 s and 19 of the 24 under 2 s;
every true positive matched its class lifetime to within 0.1 s.

So a hue match is a CANDIDATE and the lifetime is what confirms it. That is
the shape this repo's fixes keep having -- the specific test is structural
(how long the game draws the thing), not a tighter threshold on the same
noisy quantity.

Two leaks in the first version of the gate, both worth keeping written down
because each one is a way a persistence test can be fooled:

* **one-sided.** `life >= want - tol` passed a red map bar drawn for 27.2 s
  against `danger`'s 10 s. A lifetime that is too LONG is as disqualifying as
  one that is too short;
* **not contiguous.** Scenery that flickers in and out across the whole clip
  accumulates 41 sightings over a 58 s span; counting frames rather than
  measuring the span called that a 4 s object. A ping is drawn CONTINUOUSLY, so
  the span it was seen over must equal the number of frames it was seen in.

A run truncated by the end of the clip is reported UNCONFIRMED rather than
either accepted or dropped -- its lifetime cannot be measured, so the strongest
feature is simply missing. That is not a technicality: with the gate as
described, 14 of the spam clip's 15 hits are correct by eye and **the single
false positive is exactly the truncated one**, yellow foliage 1.9 s before the
recording stopped. Reporting it as a ping would be the pipeline claiming more
than its evidence supports; dropping it silently would be the class of mistake
`reticle/census.py` exists to catch.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.decode import sample_at, sample_frames                # noqa: E402
from reticle.minimap import floor_mask                             # noqa: E402

STORE = Path.home() / "reticle-store"

#: Measured 2026-09-05; see the module docstring for n and for the limits.
#: `hue` is OpenCV's 0-179.
PING_TYPES = [
    ("standard",      (76, 90),   "cyan diamond"),
    ("need_help",     (13, 26),   "orange flag"),
    ("on_my_way",     (28, 38),   "yellow stopwatch"),
    ("watching_here", (138, 155), "purple eye"),
    ("danger",        (166, 179), "red triangle"),
]

#: How long a ping is drawn for. Two values, not one -- see the docstring.
LIFETIME_S = {"standard": 7.0, "need_help": 7.0, "watching_here": 7.0,
              "on_my_way": 7.0, "danger": 10.0}

SAT_MIN, VAL_MIN = 120, 120
AREA = (20, 250)
SIDE = (5, 22)
#: How far apart two sightings may be and still be the same ping.
SAME_PX = 8
#: A ping lasts seconds; fewer frames than this is a flicker, not a mark.
MIN_FRAMES = 5
#: How far an observed lifetime may fall short of the class's and still count.
#: Measured: true positives land within 0.1 s, the worst false positive at
#: 5.1 s against a 7 s class, so anything from 0.5 to 1.8 separates them.
LIFE_TOL_S = 1.0

MINIMAP_ROI = (15, 15, 480, 500)


def classify(hue: int) -> str | None:
    for name, (lo, hi), _ in PING_TYPES:
        if lo <= hue <= hi:
            return name
    return None


def scan(path: str, roi=MINIMAP_ROI, hz: float = 10.0, fps: float = 60.0):
    """[(kind, t0, t1, x, y, hue, n_frames)] for every ping found.

    One sequential decode. The static map is the per-pixel median of the
    sampled frames -- the same trick `minimap_geometry` uses and for the same
    reason: the widget is semi-transparent, so a single frame carries the
    world moving behind it.
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

    groups: list[list] = []
    for t, c in zip(ts, frames):
        hsv = cv2.cvtColor(c, cv2.COLOR_BGR2HSV)
        m = (floor & (hsv[:, :, 1] > SAT_MIN)
             & (hsv[:, :, 2] > VAL_MIN)).astype(np.uint8)
        n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
        for k in range(1, n):
            if not AREA[0] <= st[k, 4] <= AREA[1]:
                continue
            if not (SIDE[0] <= st[k, 2] <= SIDE[1]
                    and SIDE[0] <= st[k, 3] <= SIDE[1]):
                continue
            hue = int(np.median(hsv[:, :, 0][lab == k]))
            x, y = int(cen[k][0]), int(cen[k][1])
            for g in groups:
                if abs(x - g[0][1]) < SAME_PX and abs(y - g[0][2]) < SAME_PX:
                    g.append((t, x, y, hue))
                    break
            else:
                groups.append([(t, x, y, hue)])

    clip_end = ts[-1]
    out, unconfirmed, rejected = [], [], []
    for g in groups:
        if len(g) < MIN_FRAMES:
            continue
        hue = int(np.median([e[3] for e in g]))
        kind = classify(hue)
        if kind is None:
            continue
        t0, t1 = g[0][0], g[-1][0]
        row = (kind, t0, t1, g[0][1], g[0][2], hue, len(g))
        life = len(g) / hz
        want = LIFETIME_S[kind]
        # CONTIGUOUS: a ping is drawn continuously, so the span it was seen
        # over must equal the number of frames it was seen in. Scenery that
        # flickers in and out all clip has a 58 s span and a 4 s count, and it
        # was slipping through the truncation exemption below by happening to
        # be visible in the last frame.
        if (t1 - t0) > life + LIFE_TOL_S:
            rejected.append(row)
            continue
        # Still on screen when the recording stopped is not evidence against a
        # ping, so a truncated run is held to the upper bound only.
        truncated = (clip_end - t1) < LIFE_TOL_S
        if truncated:
            # The lifetime cannot be checked, so the strongest feature is
            # missing and the row is UNCONFIRMED rather than a ping. The one
            # false positive left on the spam clip is exactly here -- yellow
            # foliage at 63.2 s, 1.9 s before the recording stopped -- and
            # calling it a ping would be the pipeline reporting a number more
            # confident than its evidence.
            (unconfirmed if life <= want + LIFE_TOL_S else rejected).append(row)
        elif abs(life - want) <= LIFE_TOL_S:
            out.append(row)
        else:
            rejected.append(row)
    for lst in (out, unconfirmed, rejected):
        lst.sort(key=lambda r: r[1])
    return out, (med, floor, unconfirmed, rejected)


def sheet(path: str, hits, out_path: str, hz: float) -> None:
    """Every hit, magnified 8x, one second after it appears.

    One second in rather than at the birth frame: the glyph is settled by then,
    and a sheet is worth exactly what a glance can take off it.
    """
    x0, y0, x1, y1 = MINIMAP_ROI
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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--hz", type=float, default=10.0)
    ap.add_argument("--emit", default=None, metavar="SESSION",
                    help="write events to <store>/events/ping/<session>.jsonl")
    ap.add_argument("--sheet", default=None, help="render every hit, magnified")
    a = ap.parse_args(argv)

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

    if a.emit:
        d = STORE / "events" / "ping"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{a.emit}.jsonl"
        with open(p, "w", encoding="utf-8") as f:
            for kind, t0, _t1, x, y, hue, n in hits:
                f.write(json.dumps({
                    "session_id": a.emit,
                    "t_ms": int(t0 * 1000),
                    "source": "minimap",
                    "kind": kind,
                    "x": x, "y": y,
                    "frame": "widget",
                    "lifetime_s": round(n / a.hz, 1),
                    "expected_lifetime_s": LIFETIME_S[kind],
                    "hue": hue,
                    "drivers": {"origin": "fixed", "bearing": "absent",
                                "extent": "none"},
                }) + "\n")
        print(f"\nemitted {len(hits)} -> {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
