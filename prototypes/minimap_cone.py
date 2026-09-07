"""The ally/self vision cone: origin, facing, and a raycast visibility mask.

Built 2026-09-02 from a real spec the player gave after playing with cones
deliberately visible: the cone originates at the icon's own teardrop point,
covers a fixed angular span centred on the direction that teardrop points,
and each ray within that span terminates at the first wall it hits -- no
reflection, plain 2D raycasting. This module is exactly that, plus what it
took to make "the icon's own teardrop point" a real measurement instead of
an assumption.

Why this exists instead of differencing the widget
----------------------------------------------------
Every other dynamic-detection channel in this project (`minimap_dynamic.py`)
works by diffing a frame against a stored reference, and that is exactly what
broke twice on 2026-09-02 for the ability-candidate scan: a self-derived
reference bakes a persistent object into its own "empty floor," and a
cross-session reference drifts in brightness/gamma between recordings. The
cone needs neither. Once origin + facing + angular width are known, the mask
is pure geometry -- a raycast through `floor_mask`, a property of the MAP, not
of any particular recording. That is the whole reason this is worth building
carefully rather than continuing to patch the diff-based approach.

Facing: the naive version is wrong, and the fix is provable
-------------------------------------------------------------
The first attempt took `minimap.self_rings()`'s largest connected component as
the icon's centre and estimated radius from its area, then ray-cast outward
for the triangle exactly the way `minimap_ring_fit._facing` does for enemies.
It produced a confident, wrong answer -- roughly 180 degrees off, verified by
rendering the actual mask: the self-colour ring fragments into 2-3
disconnected blobs on real footage (the connecting arcs fail the strict
colour threshold), so the "largest fragment" is off-centre and the ray-cast
locks onto a SECOND stray fragment instead of the true triangle.

The fix is `minimap_ring_fit.fit_ring()`, unchanged, pointed at the
self/ally-colour mask instead of red. It searches over small centre offsets
and a radius range for whichever circle has the best CIRCUMFERENCE COVERAGE --
which tolerates exactly this kind of fragmentation, since coverage does not
care whether the arc is connected. Verified by rendering the fitted circle
and the resulting facing arrow against the raw magenta-highlighted mask on two
frames: both arrows land exactly on the visible bulge. `R_MIN, R_MAX = 8, 13`
(tuned for the enemy ring) transferred without adjustment -- same icon size.

Angular width: measured on a fixed-radius ring, not by differencing
----------------------------------------------------------------------
Differencing a frame against this session's own static reference to find the
cone's brightness lift was tried and is NOT clean enough to read an edge from:
rendering it showed a UI decoration -- a ping/detection-range ring centred on
the player -- dominating the signal, since it persists at every position the
player ever stood during the sampling window far more consistently than the
cone lights any one pixel. A second confound, caught by the player before it went
into a number: an absolute-brightness read on a single frame near the "A"
bomb site read the PLANTABLE zone's own yellow tint as cone illumination.

What worked: sample grayscale value around a full 360-degree circle at a
SMALL fixed radius (16px, chosen to sit inside typical wall distance) from the
fitted centre, filtered to samples the geometry itself calls plain `FLOOR`
(rejecting anything landing on `PLANT`, `HOLE`, `BOXEDGE`, or off-map), then
take the contiguous run of "brighter than local baseline" samples that
CONTAINS the facing direction -- not just any lit angle, which a stray light
source elsewhere in the frame can trigger. This needs no cross-frame
reference at all: the comparison is angle-to-angle within one instant, so
static room lighting and the ping-ring artifact (which sits at a much larger
radius) can't contaminate it.

Over 23 open-space samples (`dist-to-wall >= 18px`, so the near-origin ring
can't itself be clipped by a wall) from one Ascent clip, most cluster tightly:
a run of 7 consecutive samples gave half-angle 50-65 degrees on each side.
Several clear outliers were EXCLUDED for a stated reason, not discarded
blind: a few had an unusually dark or bright local baseline (same class of
contamination as the plant-zone catch), which widens or shrinks the "brighter
than baseline" test independent of the real cone edge. Working estimate:

    CONE_HALF_ANGLE_DEG = 56   # ~112 degrees full angle

This is ONE clip, ONE map. Treat it as a working default, not a constant to
build downstream logic on before a second clip confirms it holds.

The player is not the only cone source
------------------------------------------------------------------------------
the stated fact, not yet independently measured: controllable deployable
recon abilities emanate a vision cone on the minimap too -- Sova's Owl Drone,
Tejo's Stealth Drone, Skye's Trailblazer, Fade's Prowler (Gekko's Wingman and
Thrash are player-steered and worth checking on the same pass). the player expects
the same half-angle but is explicitly NOT sure, so do not reuse
`CONE_HALF_ANGLE_DEG` for a deployable without measuring it -- if a drone's
cone reads a different angle that is a finding about FOV, not an outlier to
exclude, and the exclusion rules above (local-baseline contamination) are the
only ones that license dropping a sample.

**The turret's angle is ANSWERED, and it is not the player's.** Killjoy's TURRET
description in `reference/abilities.json` says it *fires at enemies in a 100
degree cone* -- so 100 degrees full, against the player's measured ~112. Close
enough to look identical by eye, different enough that reusing
`CONE_HALF_ANGLE_DEG` for it would be wrong. It came from the reference rather
than a measurement, which is the cheapest possible answer; check the other
cone-emitting deployables the same way before measuring them. Note the reference
names an angle for exactly ONE ability, so the rest still need measuring.

Two consequences, both of which cost nothing extra to collect:

* the box/wall idea below wants "many more cone observations than one clip
  supplies". A deployable is a SECOND cone in the same clip, moving through
  the map on a path the player never takes -- exactly the independent
  observations that pass needs, without new footage;
* `self_cone()` seeds from the self ring and so structurally cannot see these.
  Whatever finds a deployable cone needs its own seed; the ability candidates
  are the obvious source, and the two threads meet there.

Boxes: pass-through is the stated fact, not yet independently measured
------------------------------------------------------------------------------
the player, describing the cone from having watched it directly: it does not
illuminate boxes, and a ray can produce a very thin sliver where it barely
clips a doorway edge. The doorway behaviour is independently confirmed here --
`cone_mask()` rendered on a real doorway frame splits into two thin fingers
through the gap and re-expands beyond it, unprompted, purely from raycasting
against the floor mask. The box behaviour is coded (`pass_boxedge=True` skips
`BOXEDGE`-labelled pixels rather than stopping the ray there) but the one real
test case tried -- a frame where a boxedge cluster sat within the cone's reach
-- produced an IDENTICAL mask whether boxes blocked or not, because no cast
ray actually crossed that particular cluster's pixels. Not yet a confirmed
behaviour, just an implemented one.

**The idea worth pursuing, raised by the player and not yet built**: this is a
label-free signal for fixing `minimap_geometry`'s box/wall classification,
which is already known to be poor -- "some remaining 'box edge' pixels are
legitimately walls/map edges rather than small boxes" (prototypes/CLAUDE.md).
Across many cone instances, a boxedge segment that light ever passes BOTH
sides of in the same frame is a real low obstacle; one that is never lit past
is a full wall mislabelled as a box. This needs many more cone observations
than one clip supplies -- a real pass, not a coda to this one.
"""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle import minimap as mm                                  # noqa: E402
import minimap_ring_fit as rf                                       # noqa: E402
from minimap_geometry import BOXEDGE                                 # noqa: E402

CONE_HALF_ANGLE_DEG = 56.0  # ~112 degrees full -- see module docstring, one clip


def icon_facing(colour_mask, grey, seed_cx, seed_cy):
    """Fit a circle to `colour_mask` and return its centre + facing, or None.

    `colour_mask` is any single-colour boolean mask -- self (yellow-green) or
    one ally colour -- built the same way `minimap.self_rings`/`ally_rings`
    build theirs. Reuses `minimap_ring_fit.fit_ring`, built for the red enemy
    ring: circumference-coverage fitting tolerates the fragmentation a strict
    colour threshold produces, where a naive connected-component centroid
    does not. Returns None below `LOBE_MIN_FRAC` coverage, i.e. no confident
    triangle -- same refusal-over-guessing rule `_facing` already uses.
    """
    fit = rf.fit_ring(colour_mask, grey, seed_cx, seed_cy)
    if fit is None or fit["facing"] is None:
        return None
    return fit["cx"], fit["cy"], fit["r"], fit["facing"]


def cone_mask(labels, floor, cx, cy, facing_deg, half_angle_deg=CONE_HALF_ANGLE_DEG,
              pass_boxedge=True, n_rays=240, max_r=None):
    """Raycast visibility wedge: every floor pixel a ray from (cx,cy) reaches.

    Plain 2D raycasting per the spec -- no reflection, each ray stops at
    the first non-floor pixel. `pass_boxedge` skips `BOXEDGE`-labelled pixels
    rather than stopping there (boxes are not illuminated), which is
    coded but not yet independently confirmed -- see the module docstring.
    """
    h, w = floor.shape
    if max_r is None:
        max_r = max(h, w)
    mask = np.zeros((h, w), dtype=bool)
    facing = np.radians(facing_deg)
    half = np.radians(half_angle_deg)
    for i in range(n_rays):
        theta = facing - half + (2 * half) * i / (n_rays - 1)
        dx, dy = np.cos(theta), np.sin(theta)
        x, y = float(cx), float(cy)
        for _ in range(int(max_r)):
            xi, yi = int(round(x)), int(round(y))
            if not (0 <= xi < w and 0 <= yi < h):
                break
            blocked = not floor[yi, xi]
            if blocked and pass_boxedge and labels[yi, xi] == BOXEDGE:
                blocked = False
            if blocked:
                break
            mask[yi, xi] = True
            x += dx
            y += dy
    return mask


def self_cone(crop, floor, labels, seed_cx, seed_cy, half_angle_deg=CONE_HALF_ANGLE_DEG):
    """Convenience: self-colour mask -> facing -> cone, in one call."""
    b, g, r = (crop[:, :, i].astype(np.int16) for i in range(3))
    colour_mask = ((g > mm.SELF_G_MIN) & (r > mm.SELF_R_MIN)
                   & ((g - b) > mm.SELF_B_UNDER_G))
    grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    facing = icon_facing(colour_mask, grey, seed_cx, seed_cy)
    if facing is None:
        return None
    cx, cy, _r, ang = facing
    return cone_mask(labels, floor, cx, cy, ang, half_angle_deg)
