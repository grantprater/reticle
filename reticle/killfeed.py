"""Stage 02: killfeed detection (design doc SS3).

The killfeed is the only place the game states outright who killed whom, which
makes it the anchor for duel boundaries and the confirmation that health alone
cannot give: when the player dies the whole bottom HUD vanishes, so health never
reads zero, it just stops being readable.

Nothing here reads names. Each entry is a pair of coloured plates -- the killer's
side and the victim's, one green (ally) and one red (enemy) -- laid out in fixed
slots, and that structure is enough to count entries and time them. An entry the
local player is part of carries a thin lime border, and which half of the entry
the border sits on says whether the player did the killing or the dying.

Toggled HUD overlays
--------------------
Valorant has a set of optional on-screen readouts (shooting error, performance
graphs) that the player can toggle and position, and they can land inside this
ROI -- Grant's captures put the shooting-error box squarely in it. Because the
killfeed's own content is *transient*, anything that stays put across many
frames is by definition not a killfeed entry, so the occluding mask is derived
from the footage rather than hardcoded. That generalises to whatever the player
has switched on.

This reasoning does not transfer to the HUD ROIs, where the content is static by
nature: masking persistent pixels there would erase the digits. Those rely on
the per-frame occlusion guards in ocr.py instead.

Validation status
-----------------
Entry detection is solid: exact on an 11-frame hand-labelled set spanning empty
feeds and 1-3 concurrent entries, and it survives the tan-background false
positives that a brightness-only detector produced. Requiring *both* plate
colours is what makes it specific -- an empty feed scores 0.0% on each.

Player attribution (`player_kill` / `player_death`) is NOT trustworthy yet.
The lime border does mark the local player's entries, and the side it sits on
does say kill from death -- both verified on every labelled case. But swept
across a whole session the lime fraction is unimodal with a long tail rather
than bimodal, so there is no threshold that cleanly separates a highlighted
entry from a background that happens to be warm-coloured. The consequence,
measured on all three sessions: kills land in a plausible range while deaths
over-count by roughly 2x against the independent estimate from health going
unreadable mid-round (21-35 killfeed deaths against 11-13 from health).

Do not build on these two fields until that is resolved. Candidate fixes, none
tried: match the border's *shape* (it is a closed rectangle, not scattered
pixels) rather than its pixel count; require the border to persist across the
frames an entry is visible; or drop the colour approach and template-match the
agent portrait at the entry's left edge against the player's own agent, which
is what the design doc means by "killfeed template matching".

Deaths per round is deliberately NOT used as a check anywhere: Sage
resurrection and Clove self-revive both let a player die more than once in a
round, so any such invariant would fire on legitimate footage.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

import cv2

from .profiles import Profile, Roi

# Entry slots, in ROI pixels at 1080p. Entries are a fixed pitch apart and the
# feed holds at most six.
SLOT0_Y, SLOT_PITCH, SLOT_HALF = 30, 40, 13
MAX_SLOTS = 6

# Plate colours, measured off real footage. Every entry shows both an ally plate
# and an enemy plate, which is a far more specific signature than "bright text":
# an empty feed scores 0.0% on both, while an entry scores 10-43% on each.
GREEN_H = (60, 95)
GREEN_S = (40, 170)
RED_H_LO, RED_H_HI = 12, 168
RED_S_MIN = 60
PLATE_V_MIN = 140
PLATE_MIN_FRAC = 0.05

# The border marking an entry the local player is part of. Pale lime, and thin --
# about 1-5% of the band, against 0.0-0.35% for an entry they are not in.
LIME_MIN_FRAC = 0.004

# A pixel white in this share of sampled frames is an overlay, not an entry.
PERSIST_FRAC = 0.85


@dataclass(frozen=True)
class KillfeedRead:
    """One frame's killfeed."""

    entries: int
    slots: tuple[int, ...]
    player_kill: bool
    player_death: bool

    @property
    def player_involved(self) -> bool:
        return self.player_kill or self.player_death


def killfeed_roi(profile: Profile) -> Roi | None:
    for r in profile.rois:
        if r.name == "killfeed":
            return r
    return None


def overlay_mask(
    frames: list[np.ndarray], roi: Roi, width: int, height: int
) -> np.ndarray:
    """Derive the mask of toggled overlays sitting inside the killfeed ROI.

    Killfeed entries are transient, so a pixel that is bright in most sampled
    frames belongs to something else -- a shooting-error box, a performance
    graph. Returns a boolean mask of usable pixels.
    """
    x0, y0, x1, y1 = roi.pixels(width, height)
    acc = None
    n = 0
    for f in frames:
        hsv = cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_BGR2HSV)
        w = ((hsv[:, :, 2] > 225) & (hsv[:, :, 1] < 60)).astype(np.float32)
        acc = w if acc is None else acc + w
        n += 1
    if acc is None or n == 0:
        return np.ones((y1 - y0, x1 - x0), dtype=bool)
    persistent = (acc / n) > PERSIST_FRAC
    # Grow it a little: these boxes have soft edges and drop shadows.
    grown = cv2.dilate(persistent.astype(np.uint8), np.ones((9, 9), np.uint8)) > 0
    return ~grown


def read_killfeed(
    frame: np.ndarray,
    roi: Roi,
    width: int,
    height: int,
    mask: np.ndarray | None = None,
) -> KillfeedRead:
    """Count killfeed entries and say whether the player is in one."""
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh = hsv[:, :, 0].astype(np.int16)
    ss = hsv[:, :, 1].astype(np.int16)
    vv = hsv[:, :, 2].astype(np.int16)
    green = (hh > GREEN_H[0]) & (hh < GREEN_H[1]) & (ss > GREEN_S[0]) & (ss < GREEN_S[1]) & (vv > PLATE_V_MIN)
    red = ((hh < RED_H_LO) | (hh > RED_H_HI)) & (ss > RED_S_MIN) & (vv > PLATE_V_MIN)

    b = crop[:, :, 0].astype(np.int16)
    g = crop[:, :, 1].astype(np.int16)
    r = crop[:, :, 2].astype(np.int16)
    lime = (g > 170) & (r > 170) & (b < 150) & ((g - b) > 55) & ((r - b) > 45)

    slots: list[int] = []
    kill = death = False
    for k in range(MAX_SLOTS):
        c = SLOT0_Y + SLOT_PITCH * k
        a, z = max(0, c - SLOT_HALF), min(h, c + SLOT_HALF)
        m = mask[a:z]
        if m.sum() < 500:            # too much of this slot is masked to judge
            continue
        plate = (green[a:z] | red[a:z]) & m
        if (green[a:z] & m).sum() / m.sum() < PLATE_MIN_FRAC:
            continue
        if (red[a:z] & m).sum() / m.sum() < PLATE_MIN_FRAC:
            continue
        slots.append(k)

        # Split on the *entry's* own midpoint, not the ROI's. Entries are
        # right-aligned and their width varies with how long the two names are,
        # so a short entry sits entirely right of the ROI centre and would read
        # as a death no matter who killed whom.
        cols = np.where(plate.sum(axis=0) > plate.shape[0] * 0.4)[0]
        if cols.size == 0:
            continue
        xa, xb = int(cols.min()), int(cols.max())
        entry_mid = (xa + xb) // 2
        band_lime = lime[a:z]
        left = int(band_lime[:, xa:entry_mid].sum())
        right = int(band_lime[:, entry_mid : xb + 1].sum())
        area = max(1, (xb - xa + 1) * (z - a))
        if max(left, right) / area >= LIME_MIN_FRAC:
            # The border wraps the player's own side of the entry: on the left
            # they are the killer, on the right they are the victim.
            if left > right:
                kill = True
            else:
                death = True

    return KillfeedRead(
        entries=len(slots),
        slots=tuple(slots),
        player_kill=kill,
        player_death=death,
    )
