"""The drawn viewcone, read off the widget: which floor pixels are LIT.

The game shades the ground your team can currently see a step lighter. Every
pixel of solid floor therefore has two resting values, and `minimap_geometry`
already stores them per (map, profile) as `lo_gray`/`hi_gray` with their own
per-state noise scales. Classifying a frame is then a per-pixel question with
no global threshold in it: is this grey nearer the lit state or the unlit one,
measured in that state's own sigma?

Promoted from `prototypes/cone_lit.py` on 2026-09-07 because shipped code needs
it. `cone.resolve_lobe` uses it to settle the 180-degree bearing ambiguity, and
that is a CROSS-REFERENCE rather than a better fit: the cone is the thing the
icon is pointing at, so the light is independent evidence about the bearing in
a way no amount of tuning the ring fit can be.

**What this is NOT is ground truth.** It is a second detector over the same
pixels, and it has a documented failure mode of its own: any map object whose
resting state is the bright one inverts the two-state fit and reads permanently
lit. Blacked-out frames did that to a third of Lotus until 2026-09-07; the
mechanical doors on Ascent and Lotus still do it, at 188 and ~360 px. Scoring
one channel against this and calling the result precision implies a truth that
does not exist here. Use it to corroborate, and record disagreements.

Thresholds, and why each is where it is
----------------------------------------
`SEP_MIN` and `SPAN_MIN` gate which pixels may be classified at all: a pixel
whose two states are not separated cannot answer the question, and saying so is
better than a coin flip. `OPEN_PX` and `MIN_BLOB_PX` are spatial coherence --
a cone is a large connected region and the residue is speckle. Both are widget
quantities and scale accordingly: a length linearly, an area by the square.
Getting that pair the wrong way round is a defect this repo has already paid
for twice.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .minimap import FLOOR, PLANT, _odd, widget_scale

#: Minimum separation between the two states, in the smaller state's sigma.
SEP_MIN = 4.0
#: Minimum separation in raw grey levels, so a pixel with tiny but consistent
#: noise cannot pass `SEP_MIN` on a difference nothing could see.
SPAN_MIN = 6.0
#: Morphological open, a LENGTH in widget pixels.
OPEN_PX = 3
#: Smallest connected lit region kept, an AREA in widget pixels.
MIN_BLOB_PX = 150

LIGHTING_VERSION = "lighting-0.1.0"


@dataclass
class Lighting:
    """The per-(map, profile) lighting reference, ready to classify frames."""

    lo: np.ndarray
    hi: np.ndarray
    sd_lo: np.ndarray
    sd_hi: np.ndarray
    usable: np.ndarray
    scale: float

    @property
    def version(self) -> str:
        return LIGHTING_VERSION


def reference(z) -> Lighting | None:
    """Build the reference from an open geometry npz, or None if it predates it.

    `z` is the mapping `np.load` returns for `store/geometry/<map>__<profile>.npz`.
    Returns None rather than raising: a caller without a lighting reference
    falls back to whatever it did before, which is the upgrade-path convention
    the rest of the minimap channel uses.
    """
    need = ("lo_gray", "hi_gray", "sd_lo", "sd_hi", "labels")
    if any(k not in getattr(z, "files", z) for k in need):
        return None
    lo = z["lo_gray"].astype(np.float64)
    hi = z["hi_gray"].astype(np.float64)
    sd_lo = np.maximum(z["sd_lo"].astype(np.float64), 0.5)
    sd_hi = np.maximum(z["sd_hi"].astype(np.float64), 0.5)
    labels = z["labels"]
    solid = (labels == FLOOR) | (labels == PLANT)
    sep = (hi - lo) / np.minimum(sd_lo, sd_hi)
    usable = solid & (sep > SEP_MIN) & (hi - lo > SPAN_MIN)
    return Lighting(lo, hi, sd_lo, sd_hi, usable, widget_scale(labels.shape[1]))


def lit_mask(crop: np.ndarray, ref: Lighting) -> np.ndarray:
    """Which usable floor pixels this frame draws in the LIT state.

    `crop` is the widget ROI, BGR, at the geometry's own size. The per-pixel
    decision is nearest-state in noise units; everything after it is spatial
    coherence, because the per-pixel test has none and a cone does.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)
    lit = ref.usable & (np.abs(g - ref.hi) / ref.sd_hi
                        < np.abs(g - ref.lo) / ref.sd_lo)
    k = _odd(OPEN_PX * ref.scale)
    lit = cv2.morphologyEx(lit.astype(np.uint8), cv2.MORPH_OPEN,
                           np.ones((k, k), np.uint8))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(lit, 8)
    keep_px = MIN_BLOB_PX * ref.scale * ref.scale
    keep = np.array([False] + [st[i, 4] >= keep_px for i in range(1, n)])
    return keep[lbl]
