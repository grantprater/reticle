"""Versioned cross-channel evidence for contiguous minimap review.

These are consistency measurements, never labels or accuracy estimates. Unknown
lighting is excluded from denominators. No observation is deleted by this module.
"""
from __future__ import annotations

import numpy as np

from .minimap import R_MAX

DIAGNOSTICS_VERSION = "minimap-diagnostics-0.3.0"

#: Outer edge of the annulus support is counted over, widget px at scale 1.0.
SUPPORT_OUTER_PX = 26.0

#: Mean absolute luma difference between consecutive minimap crops, below
#: which the SOURCE is not advancing and the frame carries no new observation.
#:
#: **A frozen recording is the most confident-looking tracking in a session**,
#: and nothing was distinguishing it: the detector reads the same positions
#: every frame, every track holds, and the channel reports a world it is not
#: observing. `CLAUDE.md` already requires stale input to stay distinguishable
#: from a real reading; this is the missing half.
#:
#: Measured over five rendered windows, mean |luma difference| per frame pair:
#:
#:     window                   p05     median    p95    pairs under 0.10
#:     haven 421-428 (frozen)  0.000    0.052    0.722     383 / 419
#:     haven 259-266           0.334    3.130   13.305       2 / 419
#:     ascent 298-300          0.773    7.835   21.722       0 / 119
#:     lotus 298-300           0.276    1.244    6.380       0 / 119
#:
#: Inside the stall itself nothing exceeds 0.061, and the lowest 5th percentile
#: of live play is 0.276, so 0.15 sits in an empty gap. It is not zero because
#: a lossy codec re-encodes a static scene slightly differently each frame --
#: the luma of the first 2.5 s IS pixel-identical, and the rest is that noise.
#: The measured delta is stored per frame so this can be re-cut without
#: decoding again.
STALE_DELTA = 0.15

#: How long the round clock must hold, in ms, before its stillness is evidence
#: of a stall rather than of the second not having ticked yet. The clock has
#: 1 s resolution, so it can REFUTE a stall instantly -- a clock that advanced
#: proves the source did -- but can only corroborate one over a longer hold.
CLOCK_HELD_MS = 1500.0


def stale_source(delta, clock_ms, clock_held_ms):
    """Is the source not advancing? `(stale, evidence)`; evidence names the witness.

    **The clock is asked first, and it is the better witness**, which the
    player named: a round clock that ticks proves the capture advanced, whatever
    the pixels look like, and one held across seconds while the picture does not
    change is a stall rather than a quiet moment. It is not always there --
    post-plant the round clock is replaced by the spike timer, and the player
    reports a stall at 11:46-11:51 in exactly that state -- so the pixel delta
    stays as the fallback and the answer says which witness it rests on.
    """
    if delta is None:
        return (False, "no previous frame")
    quiet = delta < STALE_DELTA
    if clock_ms is None:
        return (quiet, "pixels only, no clock")
    if clock_held_ms is not None and clock_held_ms < CLOCK_HELD_MS:
        # The clock moved recently, so the capture was advancing recently.
        return (False, "clock advancing")
    return (quiet, "clock held and pixels static" if quiet else "clock held, pixels moving")


def source_delta(crop, previous):
    """Mean |luma difference| against the previous crop, or None if there is none."""
    if previous is None or crop.shape != previous.shape:
        return None
    return float(np.abs(crop.astype(np.int16) - previous.astype(np.int16)).mean())


def light_support(x, y, lit, known, scale=1.0):
    """Count adjacent known floor, excluding the icon's opaque interior.

    **The inner edge is the detector's radius BOUND, not the fit's own
    radius**, and the difference decides arguments. Two candidate fits of the
    same icon can disagree about the radius by 4 px, and scoring each on
    `d > r` scores them on different annuli -- so the one that fitted a larger
    circle counts less of its own dark surroundings and reads as better lit.
    In the Ascent window that artefact alone separates two fit modes by 0.13 of
    adjacent-lit fraction, in the direction that would have promoted the weaker
    fit. `R_MAX` bounds every icon this detector can find, so excluding it
    excludes the interior for all of them and the numbers compare.
    """
    if lit is None or known is None:
        return {"lit": None, "known": None, "fraction": None,
                "reason": "lighting unavailable"}
    yy, xx = np.ogrid[:lit.shape[0], :lit.shape[1]]
    d2 = (xx - x) ** 2 + (yy - y) ** 2
    region = known & (d2 > (R_MAX * scale) ** 2) & (d2 <= (SUPPORT_OUTER_PX * scale) ** 2)
    n = int(region.sum())
    k = int((region & lit).sum())
    return {"lit": k, "known": n, "fraction": k / n if n else None,
            "reason": None if n else "no readable adjacent floor"}


def distance_agreement(predicted, lit, known, origins, scale=1.0):
    """Raw overlap counts by nearest emitter distance; ratios are recomputable.

    Nearest-emitter bins partition pixels exactly once, even with overlapping
    cones. No emitters and unreadable lighting are explicit missing states.
    """
    if lit is None or known is None:
        return {"reason": "lighting unavailable", "bins": []}
    if not origins:
        return {"reason": "no fresh emitters", "bins": []}
    yy, xx = np.ogrid[:lit.shape[0], :lit.shape[1]]
    dist = np.full(lit.shape, np.inf)
    for x, y in origins:
        dist = np.minimum(dist, np.hypot(xx - x, yy - y) / scale)
    rows = []
    edges = (0, 20, 40, 60, 100, float("inf"))
    for lo, hi in zip(edges, edges[1:]):
        region = known & (dist >= lo) & (dist < hi)
        p, l = predicted & region, lit & region
        rows.append({"from_px": lo, "to_px": hi if np.isfinite(hi) else None,
                     "known": int(region.sum()), "predicted": int(p.sum()),
                     "lit": int(l.sum()), "overlap": int((p & l).sum()),
                     "predicted_only": int((p & ~l).sum()),
                     "lit_only": int((l & ~p).sum())})
    return {"reason": None, "bins": rows}
