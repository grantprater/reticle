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
#: Interior holes smaller than this are filled after the blob filter. A cone is
#: a solid region; a two-pixel gap inside one is the reader stuttering, not the
#: game drawing a hole. Measured 2026-09-07: the open and blob filters alone
#: were punching 30-36% of the holes seen inside a lit region's own envelope.
CLOSE_PX = 5
#: Smallest number of measured pixels a terrain class needs before its median
#: is trusted as that class's unlit level.
GROUP_MIN_PX = 40

LIGHTING_VERSION = "lighting-0.2.0"


@dataclass
class Lighting:
    """The per-(map, profile) lighting reference, ready to classify frames.

    `usable` is where the two states were MEASURED from footage. `known` is the
    wider set this can classify at all, because a pixel that never presented an
    unlit state still has one -- see `reference`. `unknown` is the remainder and
    is a third answer, not a quiet "unlit": conflating them biases every recall
    figure downward, since the denominator then contains floor nobody could
    read.
    """

    lo: np.ndarray
    hi: np.ndarray
    sd_lo: np.ndarray
    sd_hi: np.ndarray
    usable: np.ndarray
    scale: float
    known: np.ndarray = None
    solid: np.ndarray = None

    @property
    def unknown(self) -> np.ndarray:
        return self.solid & ~self.known

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

    # FILL the pixels that never presented two states, per terrain CLASS.
    #
    # **A pixel that was never observed unlit still has an unlit level.** The
    # two-state fit splits each pixel's samples at their largest gap, so ground
    # that is lit in nearly every sampled frame -- attacker spawn above all --
    # or whose brightness is a continuum rather than two levels, collapses and
    # is refused. That was 17.3% of Ascent's solid floor and 28.8% of Lotus's,
    # in whole rooms rather than speckle, and it is where the rendered viewcone
    # went patchy and stopped dead at raised platforms (91-97% of Lotus's +2
    # and +3 shade rungs were refused).
    #
    # The art knows what it cannot: `shade_kind`/`shade_step` name the terrain
    # LEVEL, and a level's unlit grey is a property of the level. Fitting an
    # affine on the art's rendered GREY fails -- held out, MAE 8.1-10.4 against
    # a constant's 5.3-9.8, slopes near zero, so the rendered value carries
    # almost nothing. Grouping by (kind, step) and taking the class median
    # works: held-out MAE 7.7-14.0 against a constant baseline of 18.1-30.5,
    # for a lit lift of 50-59. Two to three times better than a constant, and
    # roughly a seventh of the signal it has to resolve.
    #
    # It is a FILL, not a replacement: a measured pixel keeps its measurement,
    # so nothing that already worked moves.
    known = usable.copy()
    if "shade_kind" in getattr(z, "files", z) and "shade_step" in getattr(z, "files", z):
        kind = np.asarray(z["shade_kind"]).astype(np.int32)
        step = np.asarray(z["shade_step"]).astype(np.int32)
        grp = kind * 100 + (step + 20)
        lift = float(np.median((hi - lo)[usable])) if usable.any() else 0.0
        need = solid & ~usable
        if lift > SPAN_MIN and need.any() and usable.any():
            for g in np.unique(grp[need]):
                src = usable & (grp == g)
                if int(src.sum()) < GROUP_MIN_PX:
                    continue
                tgt = need & (grp == g)
                lo_g = float(np.median(lo[src]))
                lo[tgt] = lo_g
                hi[tgt] = lo_g + lift
                sd_lo[tgt] = float(np.median(sd_lo[src]))
                sd_hi[tgt] = float(np.median(sd_hi[src]))
                known |= tgt
    return Lighting(lo, hi, sd_lo, sd_hi, usable,
                    widget_scale(labels.shape[1]), known=known, solid=solid)


def lit_mask(crop: np.ndarray, ref: Lighting) -> np.ndarray:
    """Which usable floor pixels this frame draws in the LIT state.

    `crop` is the widget ROI, BGR, at the geometry's own size. The per-pixel
    decision is nearest-state in noise units; everything after it is spatial
    coherence, because the per-pixel test has none and a cone does.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float64)
    lit = ref.known & (np.abs(g - ref.hi) / ref.sd_hi
                       < np.abs(g - ref.lo) / ref.sd_lo)
    k = _odd(OPEN_PX * ref.scale)
    lit = cv2.morphologyEx(lit.astype(np.uint8), cv2.MORPH_OPEN,
                           np.ones((k, k), np.uint8))
    n, lbl, st, _ = cv2.connectedComponentsWithStats(lit, 8)
    keep_px = MIN_BLOB_PX * ref.scale * ref.scale
    keep = np.array([False] + [st[i, 4] >= keep_px for i in range(1, n)])
    lit = keep[lbl].astype(np.uint8)
    # Then CLOSE, because the two filters above remove speckle and also chew
    # holes in the interior of a real cone -- a third of every hole measured.
    c = _odd(CLOSE_PX * ref.scale)
    lit = cv2.morphologyEx(lit, cv2.MORPH_CLOSE, np.ones((c, c), np.uint8))
    return (lit > 0) & ref.known
