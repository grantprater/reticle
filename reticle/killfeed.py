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
"Me", whoever they are. Attribution therefore works on the name text, split at
the weapon icon: the killer's name ends at the icon and the victim's begins
after it, so whichever side reads "Me" says which role the player had.

Reading it takes three steps, and each one is there because the two simpler
versions of this failed on real footage:

1. Keep only glyph-sized components sharing the text baseline. This is what
   excludes the portraits at either end of an entry and, on the victim side, the
   headshot icon -- which sits between the weapon icon and the name and is about
   as wide as "Me".
2. Split the remaining text into runs separated by NAME_GAP blank columns, and
   take the run abutting the weapon icon. That run is the name.
3. Gate on the run's width, then match the mined "Me" bitmap inside it.

Rejected: counting glyphs. "Me" is two baseline components, and a Riot ID game
name is 3-16 characters, so two looks decisive. But trimming the portraits'
stray components (by plate colour, or by distance to the name) trims real
letters too, because the plates have slanted ends that leave a name's leading
letters barely on plate. A five-letter name then counts as two. This survived
one session whose lobby had long names and fabricated 31 kills against a true 17
on the next, whose players were called "Clove" and "Evan".

Rejected: matching the bitmap anywhere in the name region. The patch then finds
the "Mo" of "Monzuko" and the "Mr" of "MrTaco" at 0.62-0.78 against 0.82-0.87
for a real "Me" -- close enough that no threshold separates them. Confining the
match to one name run and gating on ME_W fixes it structurally rather than by
threshold: those names are a single run four times too wide to be "Me", so they
are rejected before any matching happens.

An earlier attempt keyed on the pale lime border Valorant draws around the
player's own portrait. The border is real and it does mark the right entries,
but swept across a session its pixel fraction is unimodal with a long tail, so
no threshold separated a highlighted entry from a warm-coloured background.

Entry bands are found, not assumed
----------------------------------
Entries are ENTRY_H tall at a PITCH stride, but the stack slides vertically as
older entries expire, so a fixed comb of bands clips entries and -- worse -- lets
one entry satisfy two adjacent bands and be counted twice. Bands are therefore
read off the row profile of plate-coloured pixels, a run tall enough to hold
several entries is divided by PITCH, and a run shorter than ENTRY_H is padded
back out to it. See `_entry_bands`: the padding is what keeps an entry visible
while the stack is mid-slide, and it was worth 15 of the 26 events this stage
was missing.

What that profile measures is itself load-bearing, and getting it wrong loses an
entry *silently* -- not misread, absent. It is a density taken inside each row's
own entry and requiring both plate colours, for reasons `_row_profile` sets out.
Neither property is an optimisation: between them they were four of the events
this stage was missing on one session alone.

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

Attribution is scored against the scoreboard K/D in `checks.KNOWN_KD`. Tracked
entries versus scoreboard, at 2 Hz, over ten sessions. **These numbers are from
hud-0.6.0 and predate the row-profile and divider fixes below; nothing has been
re-run against them yet.** They are kept as the baseline to beat:

    b3b9defb6fd7    14 / 18   vs  14 / 18     exact
    bdfdcf009dba    17 / 13   vs  17 / 14     +0 / -1
    223d636bf8d2    21 / 15   vs  25 / 15     -4 / +0
    9acf02f98283    11 / 13   vs  13 / 16     -2 / -3
    b7d24102a6f6    10 / 12   vs  10 / 12     exact
    75a55a296d3b     5 /  5   vs   5 /  5     exact
    59c70f1ef720    15 / 15   vs  15 / 16     +0 / -1
    bfad2778a372    19 / 13   vs  19 / 15     +0 / -2
    c40d950031bb     2 /  4   vs   2 /  7     +0 / -3
    ff636d173b07    23 / 24   vs  27 / 20     -4 / +4

24 events off across 285, against 22 before the icon work -- but the total hides
what moved. ff636d173b07 is a Phoenix game and is not a clean comparison: a
death inside Run It Back appears in the killfeed and is never counted on the
scoreboard, so its +4 deaths are as likely to be entries now read correctly as
errors. Setting that session aside, the error fell from 18 to 16, two sessions
improved, none regressed, and the one misattribution in the set was removed.

Every remaining delta is a miss. Nothing in these ten sessions is now counted
as the wrong *kind* of event, and c40d950031bb still holds exactly two real
kills and reports two.

hud-0.8.0 then gave `checks.track_entries` each entry's divider column (see
`divider_of_ys`), which is what finally separates two entries that occupy one
slot in turn. Every track longer than an entry can exist -- seven of them across
the set, at 17 to 20 observations against a ceiling near 12 -- is gone, and none
was a real entry wrongly cut: 223d636bf8d2 went exact, and ff636d173b07's kills
went from -3 to exact at 27. Scored:

    b3b9defb6fd7    14 / 18   vs  14 / 18     exact
    bdfdcf009dba    17 / 14   vs  17 / 14     exact
    223d636bf8d2    25 / 15   vs  25 / 15     exact
    9acf02f98283    13 / 16   vs  13 / 16     exact
    b7d24102a6f6    10 / 12   vs  10 / 12     exact
    75a55a296d3b     5 /  5   vs   5 /  5     exact
    59c70f1ef720    15 / 16   vs  15 / 16     exact
    bfad2778a372    20 / 15   vs  19 / 15     +1 / +0
    c40d950031bb     2 /  6   vs   2 /  7     +0 / -1
    ff636d173b07    27 / 24   vs  27 / 20     +0 / +4   (hud-0.8.1)

Seven exact, nine of ten exact on kills, and no long tracks left anywhere.
Exactly one of the six remaining events is a read error -- c40d950031bb 13:14.
The other five are entries read correctly that the scoreboard does not count,
and all five are Run It Back.

The two that are not exact are both about what the *scoreboard* counts, not
about reading pixels:

* ff636d173b07 is the Phoenix game, and its +4 deaths are now *verified* rather
  than assumed. All 24 tracked deaths are read correctly and exactly four carry
  the Phoenix ult mark -- 13:21, 20:00, 29:13, 38:20 -- so 24 - 4 = 20, the
  recorded figure. Grant's own Run It Back deaths reach the killfeed and never
  the scoreboard.

* bfad2778a372 is the same rule from the other side: one kill more than the
  board, all 20 read correctly, and the extra is a kill on an *enemy* Phoenix
  inside Run It Back. `board` agrees at all ~50 openings and the killfeed holds
  exactly 18 by the last one at 39:27; the two that follow are both "Me (Vandal)
  BiGDonut101" eight seconds apart, the victim taking a kill in between because
  the ult returned him, and the first carries the mark. Grant confirmed 19/15.

  So five of the six remaining events have one cause, and it is *visible in the
  killfeed itself*. That is what makes reading the mark worth doing: one
  detector -- a circular badge in the mark slot, right of the weapon icon --
  reconciles both sessions exactly, and it is a coachable category in its own
  right rather than only a counting fix.

What was known about hud-0.7.0 is five hand-found misses on 9acf02f98283
-- 4:27, 20:32, 24:35, 31:22 and 32:22 -- of which four were entries the old
profile caught in a *single* sampled frame, one short of KF_MIN_OBS, and the
fifth it never caught at all. Every one now holds for five to ten frames. Two
are kills and three are deaths, and the scoreboard delta at that session's last
Tab opening was -2 kills and -3 deaths, so on this session the arithmetic closes
exactly. That is suggestive, not proof: a re-score could still lose events
elsewhere that these gained.

Against 300 frames the same session stored as an empty feed, the new profile
finds 11 bands and 5 player verdicts; all five were checked by eye and all five
are real events the old profile dropped. Also a spot check, not a re-score.

Known defects, in the order worth attacking
-------------------------------------------
1. **A mark can hide the name behind it.** Valorant draws extra icons between
   the weapon and the victim's name -- a headshot crosshair, a wallbang arrow.
   The headshot icon fragments off the text baseline and is filtered upstream,
   but the wallbang arrow is one solid baseline-aligned run and impersonates the
   name. `_match_me` therefore tries several runs per side rather than only the
   one abutting the icon. Every such mark sits on the *victim* side, which is
   why kills were near-exact while deaths ran short, and fixing it made
   59c70f1ef720 exact and recovered a death on 9acf02f98283.

   **There is no full list of these icons.** Two are known; how many exist is an
   open question and the single most useful thing to find out.

2. **Fixed: a non-weapon mark in the weapon slot split the entry wrongly.**
   c40d950031bb 13:14, "HungryHamster5 (X) Me", was read as a *kill*. There is
   no weapon icon on that entry at all, so the largest-blob rule took the
   victim's portrait at the ROI edge for the divider and put "Me" on the killer
   side. The divider must now have a *name* on both sides of it -- glyph-sized
   components, which a portrait does not have -- so the entry goes unparsed
   instead of wrong. Neither this nor defect 1 needed a list of icons: an icon
   is one solid shape where a name is several glyphs, and a divider has names on
   both sides. Both are properties of what a name *is*, not of which icons exist.

   The same rule tested on *ink* rather than glyphs until 9acf02f98283 4:26,
   where bright sky inside the band made a 115 px blob left of the entry, won
   the divider on size, and put the killer's "Me" on the victim's side. Scenery
   makes blobs; it does not make glyphs.

3. **Fixed: a narrow entry fell out of the row profile.** Entries differ in
   width by more than two to one, and plate density measured across the whole
   ROI fell under PLATE_ROW_FRAC on the narrow ones -- "Me (Bandit) exile" at
   9acf02f98283 4:27 -- exactly in the rows where the glyphs are tallest. The
   run shattered into pieces shorter than MIN_BAND_H and the entry was never
   reported at all. Measuring density inside the row's own entry makes it
   width-invariant.

4. **Fixed: warm scenery merged into the entry above it.** Bright tan and pink
   surfaces clear the enemy plate's colour test, and those rows joined the
   topmost entry's run from above until it exceeded MAX_BAND_H, at which point
   the run was discarded whole. Requiring both plate colours per row -- the test
   the band already applied, moved a step earlier -- keeps them out. Because new
   entries arrive at the top of the stack, this always cost the newest event:
   the death at 9acf02f98283 20:32.

5. **Clipping at the ROI's top edge.** c40d950031bb 15:12, "pan (rifle) Me"
   scoring 0.41 against a 0.65 bar on a band at y0-37: the newest entry is still
   sliding into place and its glyph tops are cut off by the ROI boundary.
   Reading 24 rows above the ROI was tried and rejected -- it recovers nothing
   and loses those bands outright, because the taller crop changes what the
   plate row-profile resolves. Moving the ROI costs an EXTRACTOR_VERSION bump
   and a re-ingest.

6. **A washed-out entry.** ff636d173b07 11:44, "Me (rifle) MommysMethpipe",
   scoring 0.00: against a bright background the plate itself clears TEXT_V_MIN
   and fuses with the glyphs -- band median value 215, white mask filling 20.4%
   of the band against 6-10% on a healthy one. Per-band Otsu was tried and does
   not fix it; with a dark portrait at one end and a bright plate at the other
   it splits dark from bright rather than plate from text. A colour distance
   from the plate, rather than a brightness cut, is the likelier primitive.

Precision is otherwise not in question: c40d950031bb holds two real kills and
the tracker never invents an event out of nothing -- defect 2 mislabels an
entry that genuinely exists.

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
# Both plate colours must also show up in each *row* of an entry, at this share
# of the row. Same specificity test, one step earlier -- see `_row_profile`.
ROW_COLOUR_FRAC = 0.01
# Plate columns outside this percentile of a row are ignored when measuring how
# wide that row's entry is, so one stray pixel cannot stretch the span.
EXTENT_TRIM = 0.05

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
# Match score at which a name run is accepted as reading "Me". Swept against the
# scoreboard K/D of five sessions: 0.60-0.70 is a flat plateau at the same total
# error, so 0.65 sits in the middle of a stable region rather than on an edge.
ME_MATCH_MIN = 0.65
# Blank columns that separate one run of text from the next. Letters within a
# name sit 1-3 px apart; the gap from a name to the portrait beyond it measured
# 8-41 px across a session, so this splits name from portrait reliably.
NAME_GAP = 6
# Width of the "Me" ink run, measured at 18-19 px over a session. The gate this
# gives is what makes the match specific: matching the patch anywhere in a name
# region also finds the "Mo" of "Monzuko" and the "Mr" of "MrTaco" at 0.62-0.78,
# but those names are one ~84 px run, so the width rejects them outright.
ME_W = (14, 26)
# How many text runs to try on one side before giving up. Two is enough for the
# marks seen so far (headshot, wallbang); a third covers one more appearing.
MAX_NAME_RUNS = 3
# A name is *text*: several separate glyphs on a shared baseline. "Me" is two
# components. The marks that sit beside a name -- a wallbang arrow, an ability
# icon -- are single solid shapes. That difference identifies an icon without
# knowing which icon it is, which matters because no complete list of them
# exists and enumerating them would be endless: abilities alone cover mollies,
# shock darts, turrets and whatever ships next patch.
MIN_NAME_PARTS = 2

# A pixel white in this share of sampled frames is an overlay, not an entry.
PERSIST_FRAC = 0.85

# Per-entry divider column, packed one field per stack slot. Nine bits holds
# 0-511 and the ROI is 489 px wide, so six slots fit in 54 bits of an int64.
# Zero means no entry in that slot: a real divider needs a name on both sides,
# so its left edge is never column 0.
WX_BITS = 9
WX_MAX = (1 << WX_BITS) - 1


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
    entry_ys: tuple[int, ...] = ()
    # Each entry's weapon-icon divider column, parallel to the `_ys` above.
    # This is what tells one entry from the next when both sit in the same
    # slot -- see `divider_of_ys`.
    kill_wxs: tuple[int, ...] = ()
    death_wxs: tuple[int, ...] = ()
    entry_wxs: tuple[int, ...] = ()
    # Entries whose killer or victim name was covered by a toggled overlay. They
    # are neither kills nor deaths *nor* confirmed non-player entries -- a
    # non-zero count here is a capture problem, not a code one.
    unattributed: int = 0

    @property
    def player_involved(self) -> bool:
        return self.player_kill or self.player_death

    @property
    def entry_mask(self) -> int:
        """Absolute-slot bitmask of every entry, player or not.

        Recorded because the player's own entries are not enough to follow one
        across frames: when an entry expires the whole stack shifts up by one,
        and only the full occupancy shows that happening. See `checks._count`.
        """
        return mask_of_ys(self.entry_ys)

    @property
    def kill_mask(self) -> int:
        """Absolute-slot bitmask of the player's kill entries, for storage."""
        return mask_of_ys(self.kill_ys)

    @property
    def death_mask(self) -> int:
        return mask_of_ys(self.death_ys)

    @property
    def entry_dividers(self) -> int:
        """Slot-keyed divider columns for every entry, player or not."""
        return divider_of_ys(self.entry_ys, self.entry_wxs)

    @property
    def kill_dividers(self) -> int:
        return divider_of_ys(self.kill_ys, self.kill_wxs)

    @property
    def death_dividers(self) -> int:
        return divider_of_ys(self.death_ys, self.death_wxs)

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


def divider_of_ys(ys, wxs) -> int:
    """Pack each entry's divider column into one integer, keyed by stack slot.

    Packed rather than listed so it reads like the masks beside it and needs no
    agreement about ordering: slot `s` always lives at bits [WX_BITS*s, +WX_BITS),
    and a slot with no entry is zero. `wx_at` unpacks one.

    Why store this at all: an entry's divider sits at a *fixed* column for its
    whole life on screen, because the feed is right-aligned and the victim's
    name width sets where the icon lands. Measured across a session it does not
    move by more than 3 px, while two different entries in the same slot are
    tens of pixels apart -- 217 against 187 for the two kills at 223d636bf8d2
    32:06 that the tracker currently welds into one. It is the cheapest thing
    on an entry that says *which* entry it is, and unlike the stack position it
    survives the entry rising as the ones above it expire.

    It identifies an entry; it does not name one. Two entries with the same
    killer, victim and weapon render at the same column -- a Sage or Clove
    revive can produce exactly that. So a difference proves two detections are
    different entries, while sameness proves nothing. `checks.track_entries`
    only ever uses the first direction.
    """
    v = 0
    for y, wx in zip(ys, wxs):
        v |= (min(int(wx), WX_MAX) & WX_MAX) << (WX_BITS * absolute_slot(y))
    return v


def wx_at(packed, slot: int) -> int | None:
    """The divider column recorded for `slot`, or None if nothing was there."""
    if packed is None:
        return None
    return ((int(packed) >> (WX_BITS * slot)) & WX_MAX) or None


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


def _row_profile(
    green: np.ndarray, red: np.ndarray, usable: np.ndarray | None = None
) -> np.ndarray:
    """How solidly each row is filled by an entry's two plates.

    Density is measured inside the row's *own* entry rather than across the ROI,
    because entries differ in width by more than two to one -- "Me (Bandit)
    exile" against "MrTaco (Classic) Monzuko" -- and the glyphs punch holes in
    the plate. A fraction taken over the full ROI width therefore drops under
    PLATE_ROW_FRAC on the narrow entries exactly where the letters are tallest,
    the run shatters into pieces shorter than MIN_BAND_H, and the entry is lost
    outright rather than read badly. That is how the kill at 9acf02f98283 4:27
    went missing: short names either side of a narrow pistol icon.

    A row must also show *both* plate colours. That is the test the band already
    applies, moved a step earlier, and it is what keeps bright warm scenery out
    of the profile: read as the enemy plate's red, those rows joined the topmost
    entry's run from above and carried it past MAX_BAND_H, which discards the
    run whole. The newest entry is the one at the top, so what it costs is
    always the most recent event -- the death at 9acf02f98283 20:32.

    Density is measured over pixels that are actually *visible*. A toggled
    overlay blanks part of a row, and counting the blanked columns against it
    would drag the row under PLATE_ROW_FRAC and dissolve the band -- so an entry
    sitting behind the shooting-error box was not reported occluded, it simply
    never existed. Two of six on-screen entries were being lost that way.
    """
    plate = (green | red).astype(np.int32)
    rows = np.arange(plate.shape[0])
    total = plate.sum(axis=1)
    cum = plate.cumsum(axis=1)
    # The trimmed column span of this row's plate pixels: where its entry is.
    lo_n = np.maximum(1, np.ceil(EXTENT_TRIM * total)).astype(np.int32)
    hi_n = np.maximum(1, np.ceil((1.0 - EXTENT_TRIM) * total)).astype(np.int32)
    lo = (cum >= lo_n[:, None]).argmax(axis=1)
    hi = (cum >= hi_n[:, None]).argmax(axis=1)
    inside = cum[rows, hi] - cum[rows, lo] + plate[rows, lo]
    if usable is None:
        seen = (hi - lo + 1).astype(np.float64)
    else:
        vis = usable.astype(np.int32).cumsum(axis=1)
        seen = (vis[rows, hi] - vis[rows, lo] + usable[rows, lo]).astype(np.float64)
    prof = np.divide(inside, seen, out=np.zeros(plate.shape[0]), where=seen > 0)
    both = (
        (green.mean(axis=1) > ROW_COLOUR_FRAC)
        & (red.mean(axis=1) > ROW_COLOUR_FRAC)
    )
    return np.where(both, prof, 0.0)


def _entry_bands(
    green: np.ndarray, red: np.ndarray, usable: np.ndarray | None = None
) -> list[tuple[int, int]]:
    """Row spans holding one entry each, read off the plate row profile.

    Three things happen here, and the third is the one that matters most:

    * contiguous runs of plate-coloured rows are the candidate entries;
    * a run tall enough for several stacked entries is split by PITCH, so
      neighbours whose plates touch stay separate entries;
    * a run *shorter* than ENTRY_H is padded back out to it.

    The padding is not cosmetic. While the stack slides -- which it does every
    time an entry above expires -- a band's plate only partly clears
    PLATE_ROW_FRAC, so the run comes back 21 rows instead of 34 and the names
    inside it are cut off mid-glyph. The text is still perfectly legible to a
    human, but a template has no whole letters to correlate against, so the
    match craters (0.81 -> 0.34 across one such slide) and the entry vanishes
    for two or three frames. That reads downstream as two entries rather than
    one. Padding is bounded by the neighbouring runs, so it can never annex a
    neighbour's text.
    """
    on = _row_profile(green, red, usable) > PLATE_ROW_FRAC
    limit = len(on)

    runs: list[tuple[int, int]] = []
    i = 0
    while i < limit:
        if not on[i]:
            i += 1
            continue
        j = i
        while j < limit and on[j]:
            j += 1
        runs.append((i, j))
        i = j

    split: list[tuple[int, int]] = []
    for (a, z) in runs:
        h = z - a
        k = max(1, int(round(h / PITCH)))
        if k == 1:
            if MIN_BAND_H <= h <= MAX_BAND_H:
                split.append((a, z))
        else:
            step = h / k
            for m in range(k):
                a2 = a + int(round(m * step))
                z2 = a + int(round((m + 1) * step))
                if MIN_BAND_H <= z2 - a2 <= MAX_BAND_H:
                    split.append((a2, z2))

    bands: list[tuple[int, int]] = []
    for idx, (a, z) in enumerate(split):
        short = ENTRY_H - (z - a)
        if short > 0:
            up = short // 2
            floor = split[idx - 1][1] if idx else 0
            ceil = split[idx + 1][0] if idx + 1 < len(split) else limit
            a = max(0, floor, a - up)
            z = min(limit, ceil, z + (short - up))
        bands.append((a, z))
    return bands[:MAX_SLOTS]


_ME_CACHE: dict[str, tuple] = {}


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
                tpl = (z["me"] > 0).astype(np.uint8) * 255
            cols = np.where(tpl.any(axis=0))[0]
            # The ink span inside the patch: the patch is padded, and isolation
            # has to be measured from the letters, not from the patch edge.
            _ME_CACHE[profile_name] = (tpl, int(cols.min()), int(cols.max()))
    return _ME_CACHE[profile_name]


def _ink_runs(region: np.ndarray) -> list[tuple[int, int]]:
    """Column spans of text, split where NAME_GAP blank columns intervene."""
    xs = np.where((region > 0).any(axis=0))[0]
    if xs.size == 0:
        return []
    runs, start, prev = [], int(xs[0]), int(xs[0])
    for x in xs[1:]:
        x = int(x)
        if x - prev > NAME_GAP:
            runs.append((start, prev))
            start = x
        prev = x
    runs.append((start, prev))
    return runs


def name_run(region: np.ndarray, side: int) -> tuple[int, int] | None:
    """The text run holding this side's name: the one abutting the weapon icon.

    `side` is -1 for the killer's name, which ends at the icon, so the last run
    wins; +1 for the victim's, which begins after it, so the first does.
    """
    runs = _ink_runs(region)
    if not runs:
        return None
    return runs[-1] if side < 0 else runs[0]


def _match_me(region: np.ndarray, tpl_info, side: int) -> tuple[int, float]:
    """Best "Me" match among the text runs on this side, with that run's width.

    Not just the run nearest the weapon icon. Valorant draws extra marks between
    the weapon and the victim's name -- a headshot crosshair, and a wallbang
    arrow for a kill through a surface. The headshot icon breaks into fragments
    that scatter off the text baseline and is filtered out upstream, but the
    wallbang arrow is one solid baseline-aligned shape, so it survives as a run
    and impersonates the name: "Sakiko (rifle)(arrow) Me" gave a first run 14 px
    wide against the 18 px of "Me", and the death went unattributed.

    Every mark of this kind sits on the *victim* side, which is exactly why
    kills have been near-exact while deaths ran short.

    Each candidate run is still gated on ME_W and still has to match the
    template, so widening the search does not weaken the test -- it only stops
    an icon from hiding the name behind it.
    """
    if tpl_info is None:
        return 0, 0.0
    tpl, t0, t1 = tpl_info
    runs = _ink_runs(region)
    if not runs:
        return 0, 0.0
    # Nearest the weapon icon first, then outward past any marks.
    ordered = list(reversed(runs)) if side < 0 else runs
    first_w = ordered[0][1] - ordered[0][0] + 1
    best_w, best_s = first_w, 0.0
    for run in ordered[:MAX_NAME_RUNS]:
        width = run[1] - run[0] + 1
        if not (ME_W[0] <= width <= ME_W[1]):
            continue
        parts = cv2.connectedComponents(
            (region[:, run[0]:run[1] + 1] > 0).astype(np.uint8), 8)[0] - 1
        if parts < MIN_NAME_PARTS:
            continue          # one solid shape: a mark, not a name
        lo = max(0, run[0] - t0)
        hi = min(region.shape[1], run[1] + 1 + (tpl.shape[1] - 1 - t1))
        sub = region[:, lo:hi]
        if sub.shape[0] < tpl.shape[0] or sub.shape[1] < tpl.shape[1]:
            continue
        score = float(cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED).max())
        if score > best_s:
            best_s, best_w = score, width
    return best_w, best_s


def _band_text(
    white: np.ndarray, usable: np.ndarray | None = None
):
    """Isolate the band's name text and locate the weapon icon dividing it.

    Returns (text_mask, wx0, wx1), or None when the band cannot be parsed, or
    "occluded" when a toggled overlay covers enough of one name that a match
    there would fail for the wrong reason. That distinction matters: an occluded
    victim name silently looks like "not the player", turning a missed death
    into a confident wrong answer.

    The text mask keeps only glyph-sized components sharing the text baseline.
    Two other bright things in a band would otherwise be taken for a name: the
    headshot icon, which sits between the weapon icon and the victim's name and
    is about as wide as "Me", and the portraits at either end.
    """
    wb = white.astype(np.uint8)
    n, lab, st, _cen = cv2.connectedComponentsWithStats(wb, 8)
    idx = [i for i in range(1, n) if st[i, 4] >= MIN_COMP_AREA]
    if not idx:
        return None
    icons = [i for i in idx if st[i, 2] >= ICON_MIN_W and st[i, 3] >= ICON_MIN_H]
    if not icons:
        icons = [i for i in idx if st[i, 4] >= ICON_MIN_AREA]
    if not icons:
        return None
    cand = [
        i for i in idx
        if GLYPH_W[0] <= st[i, 2] <= GLYPH_W[1] and GLYPH_H[0] <= st[i, 3] <= GLYPH_H[1]
    ]
    if not cand:
        return None
    # The divider separates two names, so it must have a *name* on both sides of
    # it -- glyph-sized components, not merely ink. Without any such test the
    # largest blob wins outright, and on an entry with no weapon icon at all --
    # an ability kill -- that blob is the victim's portrait at the ROI edge. The
    # split then lands beyond the victim's name and reads a death as a kill,
    # which is worse than not answering.
    #
    # Ink alone is not enough, because the band is a full-width strip of the ROI
    # and the scenery either side of the entry lands in it. Bright sky at
    # 9acf02f98283 4:26 formed a 115 px blob left of the entry, was taken for the
    # weapon icon on size, and put the killer's "Me" on the victim's side -- a
    # kill reported as a death. Scenery makes blobs; it does not make glyphs.
    glyph_cols = np.array([st[i, 0] + st[i, 2] // 2 for i in cand])
    wep = None
    for i in sorted(icons, key=lambda i: -st[i, 4]):
        a0, a1 = int(st[i, 0]), int(st[i, 0] + st[i, 2])
        if (glyph_cols < a0).any() and (glyph_cols > a1).any():
            wep = i
            break
    if wep is None:
        return None
    wx0, wx1 = int(st[wep, 0]), int(st[wep, 0] + st[wep, 2])
    if usable is not None:
        for lo, hi in ((0, wx0), (wx1, usable.shape[1])):
            if hi - lo <= 0:
                continue
            if (~usable[:, lo:hi]).mean() > OCCLUDED_NAME_FRAC:
                return "occluded"

    # Glyphs of one name share a bottom edge; the headshot icon's pieces do not.
    base = int(np.bincount(np.array([st[i, 1] + st[i, 3] for i in cand])).argmax())
    keep = np.zeros(n, dtype=bool)
    for i in cand:
        if abs(int(st[i, 1] + st[i, 3]) - base) <= BASELINE_TOL:
            keep[i] = True
    if not keep.any():
        return None
    # Copy the glyph pixels themselves -- filling their bounding boxes instead
    # would leave the template nothing of the letter shapes to correlate with.
    return keep[lab].astype(np.uint8) * 255, wx0, wx1


@dataclass(frozen=True)
class EntryView:
    """Everything the extractor decided about one killfeed entry.

    Exists so the overlay renderer can show what the code actually saw rather
    than a second implementation of it -- a debug view that can disagree with
    the extractor is worse than none.
    """

    slot: int                      # absolute stack position
    y0: int                        # band bounds, ROI pixels
    y1: int
    wx0: int = 0                   # weapon icon column bounds, ROI pixels
    wx1: int = 0
    killer_run: tuple[int, int] | None = None   # name run column span
    victim_run: tuple[int, int] | None = None
    kill_score: float = 0.0
    death_score: float = 0.0
    # "kill" | "death" | "other" | "occluded" | "unparsed" | "tie"
    verdict: str = "unparsed"


def _plate_masks(crop: np.ndarray, mask: np.ndarray):
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
    return green, red, white


def analyse_killfeed(
    frame: np.ndarray,
    roi: Roi,
    width: int,
    height: int,
    mask: np.ndarray | None = None,
    profile_name: str = "valorant-16x9",
) -> list[EntryView]:
    """Per-entry detail for one frame. `read_killfeed` is a summary of this."""
    tpl = me_template(profile_name)
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)
    green, red, white = _plate_masks(crop, mask)

    views: list[EntryView] = []
    for (a, z) in _entry_bands(green, red, mask):
        slot = absolute_slot(a)
        if mask[a:z].sum() < 500:        # too much of this band is occluded
            continue
        # Both plate colours must be present: that is what rejects warm scenery.
        if green[a:z].mean() < PLATE_MIN_FRAC or red[a:z].mean() < PLATE_MIN_FRAC:
            continue
        parsed = _band_text(white[a:z] > 0, mask[a:z])
        if parsed is None:
            views.append(EntryView(slot, int(a), int(z), verdict="unparsed"))
            continue
        if parsed == "occluded":
            views.append(EntryView(slot, int(a), int(z), verdict="occluded"))
            continue
        band, wx0, wx1 = parsed
        # Match "Me" against each name region. The killer's name ends at the
        # weapon icon and the victim's begins after it, so the side carrying the
        # match says which role the player had.
        left, right = band[:, :wx0], band[:, wx1:]
        _kw, k_score = _match_me(left, tpl, -1)
        _dw, d_score = _match_me(right, tpl, +1)
        krun = name_run(left, -1)
        vrun = name_run(right, +1)
        if vrun is not None:
            vrun = (vrun[0] + wx1, vrun[1] + wx1)   # back to band coordinates
        if max(k_score, d_score) < ME_MATCH_MIN:
            verdict = "other"
        elif k_score > d_score:
            verdict = "kill"
        elif d_score > k_score:
            verdict = "death"
        else:
            # Only one side can be the player, so a tie is a parse failure.
            verdict = "tie"
        views.append(EntryView(slot, int(a), int(z), int(wx0), int(wx1),
                               krun, vrun, k_score, d_score, verdict))
    return views


def _trusted_wx(view: "EntryView") -> int:
    """This entry's divider column, or 0 meaning "do not use it".

    A divider is only believable when there is a name on *both* sides of it,
    which is the same test that chose it. While an entry is sliding into the
    stack its band is half-formed for a frame or two, and the split can land
    far left with no killer name beyond it at all -- ff636d173b07 10:18 read
    151 and 150 for two frames before settling at 253 for the next eight. The
    tracker takes a moved divider as proof of a different entry, so those two
    frames split one death into two tracks and it was counted twice.

    Recording 0 rather than a doubtful number keeps that frame on slot-and-time
    matching, which is what the rest of the module does with a value it cannot
    read: never guess one.
    """
    return view.wx0 if (view.killer_run and view.victim_run) else 0


def read_killfeed(
    frame: np.ndarray,
    roi: Roi,
    width: int,
    height: int,
    mask: np.ndarray | None = None,
    profile_name: str = "valorant-16x9",
) -> KillfeedRead:
    """Count killfeed entries and attribute any the local player is in."""
    views = analyse_killfeed(frame, roi, width, height, mask, profile_name)
    kills = [v for v in views if v.verdict == "kill"]
    deaths = [v for v in views if v.verdict == "death"]
    return KillfeedRead(
        entries=len(views),
        slots=tuple(v.slot for v in views),
        entry_ys=tuple(v.y0 for v in views),
        player_kill=bool(kills),
        player_death=bool(deaths),
        kill_slots=tuple(v.slot for v in kills),
        death_slots=tuple(v.slot for v in deaths),
        kill_ys=tuple(v.y0 for v in kills),
        death_ys=tuple(v.y0 for v in deaths),
        entry_wxs=tuple(_trusted_wx(v) for v in views),
        kill_wxs=tuple(_trusted_wx(v) for v in kills),
        death_wxs=tuple(_trusted_wx(v) for v in deaths),
        unattributed=sum(1 for v in views if v.verdict in ("occluded", "tie")),
    )
