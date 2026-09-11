"""What a crop LOOKS like, as one number vector, defined once.

Two readers draw the same agent art in different places -- the scoreboard row
and the killfeed entry -- and an adjudicator that wants to ask *are these the
same agent* needs both described by the same function. `scoreboard` computed
this histogram inline, and a second copy in `killfeed` would be the `floor_mask`
fork again: two definitions, the same name, free to drift for ten days.

**Composition, not pixels.** `minimap_portrait` established that colour
composition transfers across surfaces where pixel matching scores below chance,
and a histogram is layout-free, so a mirrored or rescaled drawing of one agent
still lands in the same place.

Why the name is qualified
--------------------------
A bare `composition` already means something else here: `lineup._composition`
reaches into `prototypes/minimap_portrait.py` for a DIFFERENT histogram, and the
agent gallery -- every lineup score and margin -- is built with that one. This
one shipped as `composition` for about ten minutes before `doctor`'s DUPLICATE
check named it a fork, which is what that check is for. Two different things may
not share a name; the fix is the name, not an exemption.

They stay two features on purpose. Every measured lineup result rests on the
prototype one, and swapping it would move all of them at once with nobody having
re-scored a session. `BACKLOG.md` carries the unification and what would trigger
it.

`mask` is what makes this usable on a HUD
------------------------------------------
Agent art on the killfeed is drawn OVER a team-coloured plate, and the plate is
a strong saturated colour. Unmasked, every ally portrait would look like every
other ally portrait, because the plate would dominate the histogram. So the
caller passes the pixels it believes are art, and the pixels it knows are
furniture stay out of the vector.

Owns [owns:portrait-descriptor].
"""
from __future__ import annotations

import cv2
import numpy as np

#: Hue x saturation x value, 10 x 3 x 3. Coarse on purpose: the drawings differ
#: in scale, compression and the light behind them, and a fine histogram would
#: separate two renderings of one agent as readily as two agents.
H_BINS, S_BINS, V_BINS = 10, 3, 3
BINS = H_BINS * S_BINS * V_BINS

#: Below this many art pixels the histogram is noise rather than a description.
MIN_PIXELS = 64


def hsv_composition(bgr: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Normalized HSV composition of a crop, or an empty vector when too thin.

    Returns a length-`BINS` float32 vector summing to 1, so two of them may be
    compared by histogram intersection -- `np.minimum(a, b).sum()` -- which is
    what the agent gallery is scored with.
    """
    if bgr is None or bgr.size == 0 or bgr.ndim != 3:
        return np.zeros(0, np.float32)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    hb = (hsv[:, :, 0].astype(int) * H_BINS // 180).clip(0, H_BINS - 1)
    sb = (hsv[:, :, 1].astype(int) * S_BINS // 256).clip(0, S_BINS - 1)
    vb = (hsv[:, :, 2].astype(int) * V_BINS // 256).clip(0, V_BINS - 1)
    index = ((hb * S_BINS + sb) * V_BINS + vb)
    if mask is not None:
        index = index[mask.astype(bool)]
    index = np.asarray(index).ravel()
    if index.size < MIN_PIXELS:
        return np.zeros(0, np.float32)
    hist = np.bincount(index, minlength=BINS).astype(np.float32)
    return hist / max(1.0, float(hist.sum()))


def detail(bgr: np.ndarray) -> float:
    """Vertical edge energy: how much drawing is in the crop at all.

    A flat plate and a portrait differ here by far more than they differ in
    colour, so this is the cheap guard against describing furniture.
    """
    if bgr is None or bgr.size == 0:
        return 0.0
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    return float(np.abs(cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)).mean())


def agrees(a, b) -> float:
    """Histogram intersection of two compositions; 0.0 when either is empty."""
    a = np.asarray(a, np.float32).ravel()
    b = np.asarray(b, np.float32).ravel()
    if a.size != b.size or a.size == 0:
        return 0.0
    return float(np.minimum(a, b).sum())
