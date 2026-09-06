r"""Score the ping detector on MATCH footage, against what the tiles really are.

    .\.venv\Scripts\python.exe prototypes\ping_match_eval.py <session>

The clip said 15 of 15. A real match says 8 of 31, and the gap is the whole
result -- so this file exists to keep the number reproducible and to hold the
two hypotheses that were tested against it, one of which died.

What happened
-------------
`reticle scan 587c15b07779` (Lotus, 31 minutes, `hud-0.11.0`) confirmed **31**
pings. Rendered as a contact sheet (`ping_scan.py <sid> --session --sheet`) and
read tile by tile, **8 are real** -- 7 cyan diamonds and one orange flag --
for 26% precision against the clip's 100%.

**Every false-positive class is something the spam clip could not contain.**
the player recorded it alone in a custom game, so the widget held pings and nothing
else; a real minimap is full of small saturated glyphs, and four of the five
classes below are ping-coloured by coincidence rather than by any failure of
the detector:

    ally icon (teal ring + portrait + cone)      13   hue 78-81, vs standard's 82
    warm world scenery at the widget's edge       4   hue 14-15, vs need_help's 17
    another minimap icon (yellow triangle)        3   hue 24-35
    red X death mark                              2   hue 174-175, vs danger's 174
    a red team bar across the map                 1   hue 177

So **the lifetime gate is not sufficient on match footage**, and the clip could
not have shown that. It was sufficient there because nothing else on the widget
lasted 7.0 s. Here, an ally holding an angle for seven seconds is ordinary play
and is indistinguishable from a standard ping on hue and lifetime alone.

DEAD: reuse `ally_rings` to subtract the ally class
---------------------------------------------------
The obvious fix, and the one this repo's conventions point at -- do not invent
a threshold, reuse the detector that already finds exactly those icons. It does
not work, and the measurement is unambiguous. Distance from each hit to the
nearest `self_rings`/`ally_rings` centre:

    class     n    min   median    max
    ping      8    0.4      0.9   19.2
    ally     13    1.8      4.0    7.5

**`ally_rings` fires on the cyan ping harder than it fires on allies**, which
in hindsight is what it is built to do: a standard ping is a cyan blob of icon
size, and that is the whole test. Gating at any radius keeps 1 of 8 pings.
Worth stating plainly because the hypothesis was reasonable and the reasoning
that produced it -- reuse, do not re-threshold -- is still right.

LIVE, and NOT applied: the ally icon is HOLLOW and a ping is SOLID
------------------------------------------------------------------
Blob geometry at each hit, `area / (w * h)`:

    class          n      w        h       area        fill
    clip pings    15   6-12     6-12      24-77   0.36-0.77
    match pings    8   6-12     8-12      38-63   0.44-0.79
    ally          13   8-20     8-18      40-73   0.25-0.53
    world          4   9-14     5-12     44-109   0.63-1.00

The mechanism is structural rather than fitted: an ally icon is a RING drawn
around a portrait, so its component is an annulus or an arc of one, while every
ping glyph is a filled shape. That is the shape of test this repo's fixes keep
having, and it is the one to try next.

**It is deliberately not shipped, and the reason matters more than the gate.**
The 0.44-0.53 overlap would have to be resolved per GLYPH -- the clip's flag
and eye run down to 0.36, because a flag on a pole is a sparse bounding box --
and fitting that needs labels. **The labels above are my own reading of a
contact sheet**, which `glance.answer()` refuses as a control by design and
CLAUDE.md refuses by convention: a threshold fitted to them would be scored
against itself. What this measurement licenses is a labelling pass, not a
constant.

Also unresolved, and a different problem from the ally class: the four `world`
rows are at the widget's extreme edge, where `floor_mask`'s 9 px dilation
reaches off the map body and the semi-transparent void shows live scenery. They
are the Sunset failure recorded in `reticle/ping.py`'s opening, arriving on
Lotus exactly as that section predicted -- and they are SOLID, so the fill test
above does nothing for them.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import ping as P                                      # noqa: E402
from reticle.decode import sample_at                               # noqa: E402
from reticle.minimap import (ally_rings, floor_mask,               # noqa: E402
                             minimap_roi_px, self_rings)
from reticle.profiles import get_profile                           # noqa: E402
from reticle.store import Store                                    # noqa: E402

#: Read off `587c15b07779`'s sheet by eye, 2026-09-05, tile order = hit order.
#: `p` is a real ping glyph; the rest name what the tile actually shows.
#: CLAUDE-PROVENANCE -- usable to describe a population, NOT to fit a gate.
TRUTH_587c15b07779 = (
    ["ally"] * 6 + ["p"] + ["ally"] * 3 + ["p"] + ["ally"] * 2
    + ["world", "ally", "world", "world", "world", "p", "icon", "xmark",
       "bar", "p", "ally", "icon", "p", "p", "icon", "xmark", "p", "p"])


def blobs(crop, floor):
    """Every candidate with its full geometry, not just centre and hue.

    `ping.sightings` returns what the detector needs; this returns what a
    QUESTION about the detector needs, which is why it is here and not there.
    """
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    m = (floor & (hsv[:, :, 1] > P.SAT_MIN)
         & (hsv[:, :, 2] > P.VAL_MIN)).astype(np.uint8)
    n, lab, st, cen = cv2.connectedComponentsWithStats(m, 8)
    out = []
    for k in range(1, n):
        w, h, a = int(st[k, 2]), int(st[k, 3]), int(st[k, 4])
        if not (P.AREA[0] <= a <= P.AREA[1]):
            continue
        if not (P.SIDE[0] <= w <= P.SIDE[1] and P.SIDE[0] <= h <= P.SIDE[1]):
            continue
        out.append((int(cen[k][0]), int(cen[k][1]), w, h, a, a / float(w * h),
                    int(np.median(hsv[:, :, 0][lab == k]))))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    a = ap.parse_args(argv)

    truth = globals().get(f"TRUTH_{a.session}")
    store = Store()
    man = store.read_manifest(a.session)
    src = man["source"]
    x0, y0, x1, y1 = minimap_roi_px(get_profile(man["source_profile"]),
                                    int(src["width"]), int(src["height"]))
    floor = floor_mask(store.read_static_map(a.session))
    rows = store.read_events("ping", a.session)
    if not rows:
        print(f"no ping events -- run `reticle scan {a.session}`")
        return 1
    if truth is not None and len(truth) != len(rows):
        print(f"! {len(rows)} events against {len(truth)} labels -- the sheet "
              f"was read against a different run, so the labels are orphaned")
        truth = None

    # A second after the birth frame: the glyph is settled, same as the sheet.
    frames = {}
    for s in sample_at(src["path"], sorted(r["t_ms"] + 1000 for r in rows),
                       float(src["fps"])):
        frames[round(s.t_ms / 1000.0, 1)] = s.frame[y0:y1, x0:x1].copy()

    by: dict[str, list] = {}
    print(f"{'#':>3} {'kind':<14}{'truth':<7}{'w':>4}{'h':>4}{'area':>6}"
          f"{'fill':>7}{'hue':>5}{'ring_d':>8}")
    for i, r in enumerate(rows):
        f = frames.get(round((r["t_ms"] + 1000) / 1000.0, 1))
        if f is None:
            continue
        cls = truth[i] if truth else "?"
        rings = list(self_rings(f, floor)) + list(ally_rings(f, floor))
        rd = min((float(np.hypot(r["x"] - c[1], r["y"] - c[2])) for c in rings),
                 default=999.0)
        cand = blobs(f, floor)
        if not cand:
            continue
        b = min(cand, key=lambda c: np.hypot(c[0] - r["x"], c[1] - r["y"]))
        if np.hypot(b[0] - r["x"], b[1] - r["y"]) > 10:
            continue
        by.setdefault(cls, []).append((b, rd))
        print(f"{i:>3} {r['kind']:<14}{cls:<7}{b[2]:4d}{b[3]:4d}{b[4]:6d}"
              f"{b[5]:7.2f}{b[6]:5d}{rd:8.1f}")

    print(f"\n{'class':<8}{'n':>4}{'w':>12}{'h':>12}{'area':>14}{'fill':>14}"
          f"{'ring_d':>18}")
    for cls, v in sorted(by.items()):
        def rng(j):
            s = sorted(x[0][j] for x in v)
            return f"{s[0]}-{s[-1]}"
        fills = sorted(x[0][5] for x in v)
        rds = sorted(x[1] for x in v)
        print(f"{cls:<8}{len(v):>4}{rng(2):>12}{rng(3):>12}{rng(4):>14}"
              f"{f'{fills[0]:.2f}-{fills[-1]:.2f}':>14}"
              f"{f'{rds[0]:.1f}/{rds[len(rds) // 2]:.1f}/{rds[-1]:.1f}':>18}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
