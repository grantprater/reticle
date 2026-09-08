"""Versioned cross-channel evidence for contiguous minimap review.

These are consistency measurements, never labels or accuracy estimates. Unknown
lighting is excluded from denominators. No observation is deleted by this module.
"""
from __future__ import annotations

import numpy as np

from .minimap import R_MAX

DIAGNOSTICS_VERSION = "minimap-diagnostics-0.4.0"

#: Outer edge of the annulus support is counted over, widget px at scale 1.0.
SUPPORT_OUTER_PX = 26.0

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
