"""Stage 02: killfeed detection and player attribution (design doc SS3).

The killfeed is the only place the game states outright who killed whom, which
makes it the anchor for duel boundaries and the confirmation that health alone
cannot give: when the player dies the whole bottom HUD vanishes, so health never
reads zero, it just stops being readable.

Entry layout
------------
Every entry is laid out the same way, right-aligned in the ROI:

    [killer portrait][killer name][weapon icon]([headshot])[victim name][victim portrait]

The two name plates are coloured by side -- green for an ally, red for an enemy
-- and the weapon icon always sits inside the *killer's* plate. That last fact
matters twice over: a colour sample taken beside the icon reports the killer's
side and not the victim's, and the icon is a reliable divider between the names.

Attributing an entry to the local player
---------------------------------------
Valorant renders the local player's name in the killfeed as the literal string
"Me", whoever they are. Attribution is therefore a template match: the rendered
"Me" bitmap is matched against each of the two name regions, split at the weapon
icon, and the side that matches says which role the player had -- a match left
of the icon is a kill, right of it a death.

Counting glyphs instead does not work, and the reason is worth recording because
it looks like it should. Segment the white text, keep the components on the text
baseline, and "Me" is two of them -- specific, since a Riot ID game name is 3-16
characters. But the portraits at either end of an entry contribute bright
baseline-aligned components of their own, and trimming those (by plate colour,
or by the gap to the name) trims real letters too, because the plates have
slanted ends that leave a name's leading letters barely on plate. A five-letter
name then counts as two. That went unnoticed against one session whose lobby had
long names and broke immediately on a session with names like "Clove" and
"Evan". Matching the bitmap has no such dependence on how long anyone's name is.

An earlier attempt keyed on the pale lime border Valorant draws around the
player's own portrait. The border is real and it does mark the right entries,
but swept across a session its pixel fraction is unimodal with a long tail, so
no threshold separated a highlighted entry from a warm-coloured background.

Entry bands are found, not assumed
----------------------------------
Entries are ENTRY_H tall at a PITCH stride, but the stack slides vertically as
older entries expire, so a fixed comb of bands clips entries and -- worse -- lets
one entry satisfy two adjacent bands and be counted twice. Bands are therefore
read off the row profile of plate-coloured pixels, and a run tall enough to hold
several entries is divided by PITCH.

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

Attribution is scored against the scoreboard K/D in `checks.KNOWN_KD` -- the only
external ground truth in the project. Tracked entries versus scoreboard, at
2 Hz:

    b3b9defb6fd7    14 / 19   vs  14 / 18     +0 / +1
    bdfdcf009dba    14 / 11   vs  17 / 14     -3 / -3
    223d636bf8d2    26 / 17   vs  25 / 15     +1 / +2

ME_MATCH_MIN was swept on the first two; the third is held out and lands within
two. Per-band precision was checked separately by eye: 32 of 32 hand-inspected
detections were correct, kills and deaths alike.

The residual is recall, not precision -- bdfdcf009dba misses three of each. Two
candidates, neither chased down: entries whose band the plate row-profile never
resolves, and the tracker merging two entries of the same kind that overlap in
time. Anything built on these counts should treat them as +-3 per session, and
the per-frame flags as high-precision but incomplete.

Deaths per round is deliberately NOT used as a check anywhere: Sage
resurrection and Clove self-revive both let a player die more than once in a
round, so any such invariant would fire on legitimate footage.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

import cv2

from .profiles import Profile, Roi

# Entry geometry in ROI pixels at 1080p. Measured off the row profile across a
# full session: band heights pile up hard at 34, at a PITCH of 40, with the
# topmost entry starting at FIRST_Y.
ENTRY_H = 34
PITCH = 40
FIRST_Y = 15
MAX_SLOTS = 6
# A row belongs to an entry when this share of it is plate-coloured.
PLATE_ROW_FRAC = 0.30
# Runs outside this range are not entries -- HUD chrome, or a merged smear.
MIN_BAND_H, MAX_BAND_H = 20, 40

# Plate colours, measured off real footage. Every entry shows both an ally plate
# and an enemy plate, which is a far more specific signature than "bright text":
# an empty feed scores 0.0% on both, while an entry scores 10-43% on each.
GREEN_H = (60, 95)
GREEN_S = (40, 170)
RED_H_LO, RED_H_HI = 12, 168
RED_S_MIN = 60
PLATE_V_MIN = 140
PLATE_MIN_FRAC = 0.05

# White HUD text.
TEXT_V_MIN = 200
TEXT_S_MAX = 50
MIN_COMP_AREA = 6
# The weapon icon: far wider and taller than a glyph. Ability kills draw a
# smaller icon, so fall back to the largest blob above this area.
ICON_MIN_W, ICON_MIN_H, ICON_MIN_AREA = 34, 15, 150
# Name glyphs. The headshot icon's fragments pass the size test but scatter off
# the baseline, which is what excludes them.
GLYPH_W = (1, 16)
GLYPH_H = (5, 14)
BASELINE_TOL = 2
# Valorant renders the local player's name as "Me". Riot ID game names are
# 3-16 characters, so no other name can segment to two glyphs.
ME_GLYPHS = 2
# A name region this heavily covered by a toggled overlay is unreadable, and the
# entry is reported unattributed rather than assumed not to be the player's.
OCCLUDED_NAME_FRAC = 0.20
# Match score at which a name region is accepted as reading "Me". Swept against
# the scoreboard K/D of two sessions: 0.60-0.70 is a flat plateau, so this is a
# stable operating point rather than a knife edge.
ME_MATCH_MIN = 0.60

# A pixel white in this share of sampled frames is an overlay, not an entry.
PERSIST_FRAC = 0.85


@dataclass(frozen=True)
class KillfeedRead:
    """One frame's killfeed."""

    entries: int
    slots: tuple[int, ...]
    player_kill: bool
    player_death: bool
    # Which slots the player's own entries sit in, and the top row of each in
    # ROI pixels. Position is kept because an entry slides up the stack as older
    # ones expire, so tracking one across frames needs where it is, not just a
    # flag. Prefer `kill_ys` over `kill_slots` for that: the slot *index* counts
    # only the bands that were detected, so it shifts when a band above is
    # missed, while y is an absolute coordinate that does not.
    kill_slots: tuple[int, ...] = ()
    death_slots: tuple[int, ...] = ()
    kill_ys: tuple[int, ...] = ()
    death_ys: tuple[int, ...] = ()
    # Entries whose killer or victim name was covered by a toggled overlay. They
    # are neither kills nor deaths *nor* confirmed non-player entries -- a
    # non-zero count here is a capture problem, not a code one.
    unattributed: int = 0

    @property
    def player_involved(self) -> bool:
        return self.player_kill or self.player_death

    @property
    def kill_mask(self) -> int:
        """Absolute-slot bitmask of the player's kill entries, for storage."""
        return mask_of_ys(self.kill_ys)

    @property
    def death_mask(self) -> int:
        return mask_of_ys(self.death_ys)

    @staticmethod
    def slots_of(mask) -> tuple[int, ...]:
        """Unpack a stored bitmask back to absolute slot indices."""
        if mask is None:
            return ()
        return tuple(s for s in range(MAX_SLOTS) if int(mask) & (1 << s))


def absolute_slot(y: int) -> int:
    """Which stack position a band at row `y` occupies.

    This is deliberately *not* the index of the band among those detected: that
    index shifts whenever a band above happens to be missed, which breaks any
    attempt to follow one entry across frames. Quantising the row instead gives
    a position that means the same thing in every frame.
    """
    return max(0, min(MAX_SLOTS - 1, int(round((y - FIRST_Y) / PITCH))))


def mask_of_ys(ys) -> int:
    m = 0
    for y in ys:
        m |= 1 << absolute_slot(y)
    return m


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


def _entry_bands(plate: np.ndarray) -> list[tuple[int, int]]:
    """Row spans holding one entry each, read off the plate row profile.

    A run tall enough for several stacked entries is split by PITCH rather than
    returned whole, so neighbours whose plates touch stay separate entries.
    """
    prof = plate.mean(axis=1)
    on = prof > PLATE_ROW_FRAC
    bands: list[tuple[int, int]] = []
    i, n = 0, len(on)
    while i < n:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < n and on[j]:
            j += 1
        h = j - i
        k = max(1, int(round(h / PITCH)))
        if k == 1:
            if MIN_BAND_H <= h <= MAX_BAND_H:
                bands.append((i, j))
        else:
            step = h / k
            for m in range(k):
                a = i + int(round(m * step))
                z = i + int(round((m + 1) * step))
                if MIN_BAND_H <= z - a <= MAX_BAND_H:
                    bands.append((a, z))
        i = j
    return bands[:MAX_SLOTS]


_ME_CACHE: dict[str, np.ndarray] = {}


def me_template(profile_name: str) -> np.ndarray | None:
    """The rendered "Me" bitmap, mined from footage and committed per profile.

    Mined rather than drawn from a font, for the same reason the digit templates
    are (see ocr.py): what matters is how this build renders at this resolution.
    """
    if profile_name not in _ME_CACHE:
        path = Path(__file__).with_name("templates") / f"{profile_name}-killfeed.npz"
        if not path.is_file():
            _ME_CACHE[profile_name] = None
        else:
            with np.load(path) as z:
                _ME_CACHE[profile_name] = (z["me"] > 0).astype(np.uint8) * 255
    return _ME_CACHE[profile_name]


def _match_me(region: np.ndarray, tpl: np.ndarray) -> float:
    """Best normalised correlation of the "Me" bitmap anywhere in `region`."""
    if tpl is None or region.shape[0] < tpl.shape[0] or region.shape[1] < tpl.shape[1]:
        return 0.0
    return float(cv2.matchTemplate(region, tpl, cv2.TM_CCOEFF_NORMED).max())


def _split_sides(
    white: np.ndarray, usable: np.ndarray | None = None
) -> tuple[int, int] | None | str:
    """Column bounds of the weapon icon, which divides killer name from victim.

    Returns (wx0, wx1), or None when no icon is found, or "occluded" when a
    toggled overlay covers enough of one name that a match there would fail for
    the wrong reason. That distinction matters: an occluded victim name silently
    looks like "not the player", turning a missed death into a confident wrong
    answer.
    """
    wb = white.astype(np.uint8)
    n, _lab, st, _cen = cv2.connectedComponentsWithStats(wb, 8)
    comps = [
        (int(st[i, 0]), int(st[i, 1]), int(st[i, 2]), int(st[i, 3]), int(st[i, 4]))
        for i in range(1, n)
        if st[i, 4] >= MIN_COMP_AREA
    ]
    if not comps:
        return None
    icons = [c for c in comps if c[2] >= ICON_MIN_W and c[3] >= ICON_MIN_H]
    if not icons:
        icons = [c for c in comps if c[4] >= ICON_MIN_AREA]
    if not icons:
        return None
    wep = max(icons, key=lambda c: c[4])
    wx0, wx1 = wep[0], wep[0] + wep[2]
    if usable is not None:
        for lo, hi in ((0, wx0), (wx1, usable.shape[1])):
            if hi - lo <= 0:
                continue
            if (~usable[:, lo:hi]).mean() > OCCLUDED_NAME_FRAC:
                return "occluded"
    return wx0, wx1


def read_killfeed(
    frame: np.ndarray,
    roi: Roi,
    width: int,
    height: int,
    mask: np.ndarray | None = None,
    profile_name: str = "valorant-16x9",
) -> KillfeedRead:
    """Count killfeed entries and attribute any the local player is in."""
    tpl = me_template(profile_name)
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)

    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh = hsv[:, :, 0].astype(np.int16)
    ss = hsv[:, :, 1].astype(np.int16)
    vv = hsv[:, :, 2].astype(np.int16)
    green = (
        (hh > GREEN_H[0]) & (hh < GREEN_H[1])
        & (ss > GREEN_S[0]) & (ss < GREEN_S[1]) & (vv > PLATE_V_MIN)
    ) & mask
    red = (
        ((hh < RED_H_LO) | (hh > RED_H_HI)) & (ss > RED_S_MIN) & (vv > PLATE_V_MIN)
    ) & mask
    white = ((vv > TEXT_V_MIN) & (ss < TEXT_S_MAX) & mask).astype(np.uint8) * 255

    slots: list[int] = []
    kill_slots: list[int] = []
    death_slots: list[int] = []
    kill_ys: list[int] = []
    death_ys: list[int] = []
    unattributed = 0
    for k, (a, z) in enumerate(_entry_bands(green | red)):
        if mask[a:z].sum() < 500:        # too much of this band is occluded
            continue
        # Both plate colours must be present: that is what rejects warm scenery.
        if green[a:z].mean() < PLATE_MIN_FRAC or red[a:z].mean() < PLATE_MIN_FRAC:
            continue
        slots.append(k)
        sides = _split_sides(white[a:z] > 0, mask[a:z])
        if sides is None:
            continue
        if sides == "occluded":
            unattributed += 1
            continue
        wx0, wx1 = sides
        band = white[a:z]
        # Match "Me" against each name region. The killer's name ends at the
        # weapon icon and the victim's begins after it, so the side carrying the
        # match says which role the player had.
        k_score = _match_me(band[:, :wx0], tpl)
        d_score = _match_me(band[:, wx1:], tpl)
        if max(k_score, d_score) < ME_MATCH_MIN:
            continue
        # Only one side can be the player. If both score, take the stronger --
        # and if they tie, attribute neither rather than guessing.
        if k_score > d_score:
            kill_slots.append(k)
            kill_ys.append(int(a))
        elif d_score > k_score:
            death_slots.append(k)
            death_ys.append(int(a))

    return KillfeedRead(
        entries=len(slots),
        slots=tuple(slots),
        player_kill=bool(kill_slots),
        player_death=bool(death_slots),
        kill_slots=tuple(kill_slots),
        death_slots=tuple(death_slots),
        kill_ys=tuple(kill_ys),
        death_ys=tuple(death_ys),
        unattributed=unattributed,
    )
