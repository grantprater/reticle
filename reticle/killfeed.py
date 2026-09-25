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
ROI -- the captures put the shooting-error box squarely in it. Because the
killfeed's own content is *transient*, anything that stays put across many
frames is by definition not a killfeed entry, so the occluding mask is derived
from the footage rather than hardcoded. That generalises to whatever the player
has switched on.

This reasoning does not transfer to the HUD ROIs, where the content is static by
nature: masking persistent pixels there would erase the digits. Those rely on
the per-frame occlusion guards in ocr.py instead.

What a camera wipe does to this, and what is still wrong
-------------------------------------------------------
`_entry_bands` decides an entry from PLATE COLOUR alone, and splits a tall run
into `round(h / PITCH)` of them. A respawn or camera wipe paints the ROI in
both plate colours across a tall region, so the split manufactures three to six
bands out of one wash. Measured on `c40d950031bb` against two source-reviewed
wipes (503.4-505.6 s and 858.0-861.2 s, every frame inspected at 200 ms): at
native rate the reader claimed entries at 13 instants a reviewer recorded as
EMPTY, with up to six in a single frame.

Roughly half of that is now refused, by cross-reference rather than by
threshold. Every entry is drawn with the same furniture -- two portraits, an
icon between the names, and the names -- and this function already computes
whether the band has any of it, so a band we can see that returns `no_ink`,
`no_icon` or `no_glyphs` is not an entry, whatever colour it is. See
`EMPTY_BAND_REFUSALS`. It leaves `kf_player_kill`/`kf_player_death` untouched by
construction, because such a band could only ever have been `unparsed`, and
`c40d950031bb` re-scans to 2/7, still exact against the scoreboard.

What it costs, measured rather than assumed: confuser false-positive instants
fall from 11 to 3 at 15 Hz and 5 to 3 at 2 Hz, presence recall holds at 1.0000
at 5 Hz and above, and at 2 Hz it falls from 0.9545 to 0.9091 -- a 2 Hz sampler
can land on the one or two frames of an entry's SLIDE-IN, where the plate is
drawn before its content and there is genuinely no icon yet. At native rate the
count is unchanged at 11, so this is not the fix; it is the half of it that
needs no threshold.

**The rest is still open, and BLUR is the lead.** The survivors return
`no_divider`, a class real entries also reach. But a wipe is soft-edged and its
sub-bands are slices of one rectangle, so they share horizontal bounds -- while
real entries differ in width by more than two to one, which `_row_profile`
already relies on. Over 1,298 bands here, mean horizontal Sobel magnitude inside
the band's own plate extent runs 45.6 (p05) to 70.6 (p95) on real activity
against a maximum of 28.2 on one wipe and 13.1 on the other, and slide-in
frames keep the sharp edge. Among frames holding several bands the widths agree
within 4 px in 20% of real frames, 55% of one wipe and 100% of the other.
Those numbers were measured ON the frozen P3 windows, so a threshold must be
fitted somewhere else before `fidelity-check` can score it. See `BACKLOG.md`.

PERSISTENCE is the stronger rule, and it now lives in `checks.track_entries`
where it belongs: this function reads one frame and must keep reporting what it
saw in it, so only a walk across frames can say a band never persisted. Over
the frozen windows at native rate the two classes do not come close --

    real entries    eleven tracks spanning 4733-8017 ms
    wipe bands      eleven tracks spanning 0-667 ms, and not one kill or death
                    verdict among them

-- and `checks.entry_presence`, which is the entry count of record, takes the
confuser false-positive instants from eleven to zero at native rate and from
three to zero at 2 Hz without costing one instant of presence recall. The
count is the same eleven at every rate from native to 2 Hz.

`kf_entries` is still what one frame held, and on a wiped frame that is a guess
dressed as a count. Read it as the reader's own claim, never as the number of
entries on screen.

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
  recorded figure. the Run It Back deaths reach the killfeed and never
  the scoreboard.

* bfad2778a372 is the same rule from the other side: one kill more than the
  board, all 20 read correctly, and the extra is a kill on an *enemy* Phoenix
  inside Run It Back. `board` agrees at all ~50 openings and the killfeed holds
  exactly 18 by the last one at 39:27; the two that follow are both "Me (Vandal)
  BiGDonut101" eight seconds apart, the victim taking a kill in between because
  the ult returned the player, and the first carries the mark. the player confirmed 19/15.

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

Owns [owns:killfeed-event], [owns:killfeed-portrait], [owns:killfeed-second-life-badge]
and [owns:killfeed-weapon-descriptor].
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import numpy as np

import cv2

from . import appearance
from .census import Census
from .profiles import Profile, Roi, template_key

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
# The weapon icon: far wider and taller than a glyph. A small icon -- a pistol,
# an ability mark -- can miss the size test, so an area test runs BESIDE it,
# in a SECOND TIER that is only reached when no size-passer works.
#
# It used to be a fallback taken only when the size test found *nothing*, and
# that is a different thing: the killer portrait at the ROI edge passes the
# size test on every entry, so the fallback never ran and a small weapon icon
# was never a candidate at all. The band then had exactly one icon -- the
# portrait, with no name to its left -- and went `no_divider`. Twenty-one bands
# on c40d950031bb, of which the multi-frame ones are real entries: the pistol
# kill at 6:34 reads `SJK (Classic)(headshot) HungryHamster5` perfectly by eye
# and its icon is 27x21, four columns under ICON_MIN_W.
#
# **Tiers, not a union, and that was measured rather than argued.** A plain
# union re-decided three bands on that session as well as recovering eight,
# because an area-passer can outweigh a size-passer and the loop takes the
# largest first: at 3:33 the divider moved from the rifle at 218 to a blob at
# 131 *inside the killer's own name*. Tiering restores the old preference
# exactly -- every size-passer is tried before any area-only one -- so a band
# the old rule could parse parses identically, and only a band it refused can
# change. Re-measured: 8 recovered, 0 lost, 0 re-decided.
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
# Reading the victim's team off the plate under their name. The margin is what
# keeps a half-occluded band from being guessed at: the two colours have to be
# decisively apart, not merely unequal.
# Columns of one plate colour needed before it counts as a plate rather than
# noise or the edge of a mark. The victim's plate is the last such run.
MIN_PLATE_RUN = 18
# Share of the band's height a column must be plate-coloured to count as plate.
PLATE_COL_FRAC = 0.45

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
    # Which team each entry's victim was on, parallel to `entry_ys`.
    entry_ally: tuple[object, ...] = ()
    # Plate-coloured bands carrying none of an entry's furniture -- no icon, no
    # glyphs, no ink -- which are therefore not entries. Several at once means
    # something is painting the ROI: a respawn or camera wipe crosses it in both
    # plate colours and `_entry_bands` splits that wash into `round(h/PITCH)`
    # bands. Counted rather than discarded so a frame can say "the killfeed was
    # unreadable here" instead of "empty".
    empty_bands: int = 0
    empty_band_reason: str | None = None
    # Bands this frame held that could not be parsed at all, and which guard
    # refused the first of them. Separate from `unattributed`, which counts
    # entries that WERE parsed and could not be attributed -- the two are
    # different failures and were indistinguishable in L1 until now.
    # `no_divider` is the ability-kill signature; see BAND_REFUSALS.
    unparsed: int = 0
    unparsed_reason: str | None = None
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
    def ally_mask(self) -> int:
        """Slots whose entry killed an *ally*. With `enemy_mask` this is what
        turns the feed into both teams' alive counts. A slot in `entry_mask` but
        in neither is an entry whose plate could not be read -- rare, and left
        unresolved rather than assigned to a side."""
        return mask_of_ys([y for y, al in zip(self.entry_ys, self.entry_ally) if al is True])

    @property
    def enemy_mask(self) -> int:
        return mask_of_ys([y for y, al in zip(self.entry_ys, self.entry_ally) if al is False])

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


def me_template_path(profile_name: str) -> Path:
    """Resolve path to the 'Me' template .npz in reticle-store or fallback to package templates."""
    filename = f"{template_key(profile_name)}-killfeed.npz"
    try:
        from .store import Store
        store_path = Store().root / "reference" / "templates" / filename
        if store_path.is_file():
            return store_path
    except Exception:
        pass
    return Path(__file__).with_name("templates") / filename


def me_template(profile_name: str) -> np.ndarray | None:
    """The rendered "Me" bitmap, mined from footage and committed per profile.

    Mined rather than drawn from a font, for the same reason the digit templates
    are (see ocr.py): what matters is how this build renders at this resolution.
    """
    if profile_name not in _ME_CACHE:
        path = me_template_path(profile_name)
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


#: Why `_band_text` refused a band, in the order the guards run. Each is a
#: different *kind* of failure and they do not deserve one name between them:
#:
#:   no_ink      no component above MIN_COMP_AREA -- an empty or dark band
#:   no_icon     ink, but nothing icon-shaped to divide the two names at
#:   no_glyphs   ink, but nothing glyph-shaped: no name on either side
#:   no_divider  no icon with a name on BOTH sides AND no unambiguous plate
#:               seam either -- both dividers refused. An entry with no weapon
#:               icon at all (an ability kill) reaches the second of these and
#:               usually parses; what is left here is a band with two seams or
#:               none, which is a band this module does not model.
#:   no_baseline glyphs, but none within BASELINE_TOL of the modal baseline
BAND_REFUSALS = ("no_ink", "no_icon", "no_glyphs", "no_divider", "no_baseline")

# Three of those refusals are positive evidence that the band holds NO ENTRY, and
# the rest are not. Every entry is drawn with the same furniture -- two
# portraits, an icon between the names, and the two names -- and an ABILITY kill
# is no exception: `c40d950031bb` 13:14 renders `HungryHamster5 [ability] Me`
# with both portraits and the ability mark where the weapon icon goes. So a band
# we can see that has no icon-sized component, or no glyph-sized ink, or no ink
# at all, is a plate with nothing on it.
#
# `no_icon` was first left out of this list on the belief that it was the
# ability-kill signature. It is not: measured band by band across that kill at
# native rate, the entry reads `death` continuously for 1.6 s and returns
# `no_icon` only on the two frames of its slide-in, before the content draws,
# and on one frame a wipe crosses it. Nothing persistent is lost by refusing it,
# which the frozen comparison checks rather than assumes.
#
# `no_divider` and `no_baseline` stay entries: both have an icon AND glyphs and
# only failed to be split. `occluded` stays too -- that is the mask admitting it
# could not look, and absence of a reading is not absence of an entry.
EMPTY_BAND_REFUSALS = ("no_ink", "no_icon", "no_glyphs")


def plate_seam(green_band: np.ndarray, red_band: np.ndarray) -> int | None:
    """The column where the killer's plate ends and the victim's begins.

    A divider that needs **no icon at all**, which is the whole point: it is the
    only one that can split an ability kill. `c40d950031bb` 13:14,
    `HungryHamster5 (x) Me`, is the one read error left in stage 02 -- there is
    no weapon icon, and the ability mark fragments under the white-text cut into
    pieces too small to be a divider candidate, so the band goes unparsed and
    the death is lost. The two plate colours are still perfectly separated
    there: `R(29,143) R(209,383) G(383,419)`, seam at 383.

    Both plates are always drawn and they are always different colours -- that
    is what `_entry_bands` is built on and what makes an entry specific in the
    first place -- so this exists on every entry, whatever is drawn inside it.
    What it costs is precision of a different kind: the seam sits *past* the
    weapon icon and any mark after it, at the start of the victim's name, so it
    splits killer-plus-marks from victim rather than killer from victim. That is
    fine for attribution, because `_match_me` already searches several runs per
    side for exactly that reason, and it is *better* for `victim_is_ally`, whose
    sample then starts at the victim's plate rather than at the weapon icon.

    Returned only when the seam is UNAMBIGUOUS: exactly one place where two
    wide runs of opposite colour touch. Two such places means the band holds
    something this function does not model -- most likely two entries merged --
    and guessing between them is how a death gets read as a kill. The rule of
    this module is never to guess a value.

    Reuses `victim_is_ally`'s run finder verbatim rather than a second copy,
    which is also why the constants are shared: coverage, not mere colour.
    """
    runs = _plate_runs(green_band, red_band)
    seams = [b[1] for a, b in zip(runs, runs[1:])
             if a[0] != b[0] and a[2] == b[1]]
    return int(seams[0]) if len(seams) == 1 else None


def _band_text(
    white: np.ndarray, usable: np.ndarray | None = None, plates=None
):
    """Isolate the band's name text and locate the weapon icon dividing it.

    Returns (text_mask, wx0, wx1) on success, otherwise a **string naming the
    guard that refused**: "occluded" when a toggled overlay covers enough of one
    name that a match there would fail for the wrong reason, and one of
    `BAND_REFUSALS` when the band cannot be parsed at all.

    The occluded/unparsed distinction matters: an occluded victim name silently
    looks like "not the player", turning a missed death into a confident wrong
    answer. The *reason* matters for the same kind of reason one level down.
    Five guards here all produced the single word "unparsed", so the one known
    read error left in this stage -- c40d950031bb 13:14, an ability kill with no
    weapon icon -- was indistinguishable in every summary from a band of empty
    scenery. `no_divider` says which of the five it is, and it is the one that
    can be fixed without a list of icons.

    The text mask keeps only glyph-sized components sharing the text baseline.
    Two other bright things in a band would otherwise be taken for a name: the
    headshot icon, which sits between the weapon icon and the victim's name and
    is about as wide as "Me", and the portraits at either end.
    """
    wb = white.astype(np.uint8)
    n, lab, st, _cen = cv2.connectedComponentsWithStats(wb, 8)
    idx = [i for i in range(1, n) if st[i, 4] >= MIN_COMP_AREA]
    if not idx:
        return "no_ink"
    big = [i for i in idx if st[i, 2] >= ICON_MIN_W and st[i, 3] >= ICON_MIN_H]
    small = [i for i in idx if st[i, 4] >= ICON_MIN_AREA and i not in set(big)]
    if not big and not small:
        return "no_icon"
    cand = [
        i for i in idx
        if GLYPH_W[0] <= st[i, 2] <= GLYPH_W[1] and GLYPH_H[0] <= st[i, 3] <= GLYPH_H[1]
    ]
    if not cand:
        return "no_glyphs"
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
    for tier in (big, small):
        for i in sorted(tier, key=lambda i: -st[i, 4]):
            a0, a1 = int(st[i, 0]), int(st[i, 0] + st[i, 2])
            if (glyph_cols < a0).any() and (glyph_cols > a1).any():
                wep = i
                break
        if wep is not None:
            break
    if wep is None:
        # Nothing icon-shaped divides two names. The plates still do -- see
        # `plate_seam`, which is what reads an ability kill. Last resort on
        # purpose: the seam is a *coarser* split than the icon (marks fall on
        # the killer's side of it), so it is only right to prefer it where
        # there is no icon to be had.
        seam = plate_seam(*plates) if plates is not None else None
        if seam is None:
            return "no_divider"
        wx0 = wx1 = seam
    else:
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
        return "no_baseline"
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
    # Which team the victim was on: True ally, False enemy, None undecidable.
    # Every entry is a death, so this is what gives both teams' alive counts.
    victim_ally: bool | None = None
    # "kill" | "death" | "other" | "occluded" | "unparsed" | "tie"
    verdict: str = "unparsed"
    # Which guard refused, when the verdict is "unparsed": one of
    # `BAND_REFUSALS`, or a band-level reason when the band never reached
    # `_band_text` at all. Empty when nothing refused.
    reason: str = ""


def victim_is_ally(green, red, a: int, z: int, wx1: int) -> bool | None:
    """Which team the victim was on, from the colour of the plate they sit on.

    Every killfeed entry is a death, so this is what turns the feed into alive
    counts for *both* teams -- the state a win-probability model is built on.
    Until now the module only ever asked whether an entry involved the local
    player, and the other eight players' deaths were detected and discarded.

    Plate colour is the right thing to key on: band detection is built on it,
    requiring *both* colours is what makes an entry specific, and unlike every
    brightness test here it has survived the HUD's transparency everywhere it
    has been used.

    Read as the *last wide run of one colour*, not from any text run. Two
    earlier attempts failed on the same geometry from opposite ends. Sampling
    the first ink run past the divider reads a headshot or wallbang mark, and
    those are drawn on the *killer's* plate -- so a marked entry came out
    backwards. Sampling the last run instead reads fragments of the victim's
    portrait, which sits past the plate, so it refused far more often and was
    wrong more often too. The plate is a wide contiguous band and the portrait
    is drawn *over* it, which makes the plate the thing to find and the text
    beside the point.

    Returns None when no run is wide enough to be a plate, which is the honest
    answer for a band that is half occluded.
    """
    W = green.shape[1]
    if wx1 >= W - MIN_PLATE_RUN:
        return None
    runs = _plate_runs(green[a:z, wx1:], red[a:z, wx1:])
    return bool(runs[-1][0] > 0) if runs else None


def _plate_runs(green_band: np.ndarray, red_band: np.ndarray) -> list[tuple[int, int, int]]:
    """Wide contiguous runs of one plate colour: `(+1 green | -1 red, x0, x1)`.

    A plate column is *covered*, not merely coloured. Past the entry's right
    edge the ROI is open scenery, and warm scenery reads as the enemy plate's
    red -- the same thing that used to merge background into the band above.
    A real plate spans most of the band's height; background never does.
    """
    h = green_band.shape[0]
    g = green_band.sum(axis=0)
    r = red_band.sum(axis=0)
    live = (g + r) >= PLATE_COL_FRAC * h
    colour = np.where(g > r, 1, -1) * live          # 1 green, -1 red, 0 nothing
    runs, i = [], 0
    while i < len(colour):
        if colour[i] == 0:
            i += 1
            continue
        j = i
        while j < len(colour) and colour[j] == colour[i]:
            j += 1
        if j - i >= MIN_PLATE_RUN:
            runs.append((int(colour[i]), i, j))
        i = j
    return runs


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
    census: "Census | None" = None,
    t_ms: float | None = None,
) -> list[EntryView]:
    """Per-entry detail for one frame. `read_killfeed` is a summary of this.

    `census`, when given, is told about every band this function discards and
    every band it keeps but cannot read. **The returned views are unchanged by
    it** -- the two band-level guards below still `continue`, and a dropped band
    is still absent from `views` and from `entries`. That is deliberate: every
    number in this module's docstring was measured with those bands absent, and
    admitting them as views would move all of them at once without anyone having
    re-scored a session. The census makes the rate *visible* first; whether a
    dropped band should have been a view is then a question with evidence
    behind it rather than a guess. See `reticle.census`.
    """
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
        where = (round(t_ms / 1000.0, 2) if t_ms is not None else None, slot)
        if census is not None:
            census.saw("bands")
        if mask[a:z].sum() < 500:        # too much of this band is occluded
            if census is not None:
                census.drop("band_masked_out", where)
            continue
        # Both plate colours must be present: that is what rejects warm scenery.
        if green[a:z].mean() < PLATE_MIN_FRAC or red[a:z].mean() < PLATE_MIN_FRAC:
            if census is not None:
                census.drop("band_one_plate_colour", where)
            continue
        parsed = _band_text(white[a:z] > 0, mask[a:z], (green[a:z], red[a:z]))
        if isinstance(parsed, str):
            if census is not None:
                census.drop(parsed, where)
            # CROSS-REFERENCE, not a threshold. `_entry_bands` says "entry" from
            # plate colour alone and splits a tall run into `round(h/PITCH)` of
            # them; the text reader, in this same function, says the band holds
            # no name. When they disagree that way the band is not an entry, and
            # a camera wipe is where they disagree: a respawn wipe paints both
            # plate colours across the ROI, the split manufactures three to six
            # bands from it, and not one of them carries an entry's furniture.
            # Measured on c40d950031bb over two source-reviewed wipes -- 13
            # phantom instants at native rate, up to six entries in a single
            # frame -- against zero in either audit window. Nothing here tunes
            # PLATE_ROW_FRAC or the plate masks; the evidence was already being
            # computed and thrown away.
            # Returned in band order with every other view, and excluded from
            # the entry count by `read_killfeed`. Kept rather than dropped so
            # the count of them stays readable: several at once is the signature
            # of something painting the ROI, which is worth seeing, not hiding.
            if parsed in EMPTY_BAND_REFUSALS:
                views.append(EntryView(slot, int(a), int(z),
                                       verdict="empty_band", reason=parsed))
                continue
            verdict = "occluded" if parsed == "occluded" else "unparsed"
            views.append(EntryView(slot, int(a), int(z),
                                   verdict=verdict, reason=parsed))
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
                               killer_run=krun, victim_run=vrun,
                               kill_score=k_score, death_score=d_score,
                               verdict=verdict,
                               victim_ally=victim_is_ally(green, red, a, z, wx1)))
    return views


#: The official killfeed portrait art is 256x128 -- TWO band heights wide. Taken
#: from the asset, not fitted to a session, which is why it is a ratio and not a
#: pixel count: the band height already carries the widget's scale.
PORTRAIT_ASPECT = 2.0
# 0.3.0 (2026-09-24): also stores a `second_life_observation` per read player
# death entry: whether it carries the Run It Back / downed badge.
KILLFEED_PORTRAIT_VERSION = "killfeed-portrait-0.3.0"

#: How many columns must stay clear of plate and text before a gap is the
#: portrait rather than the space inside a letter.
PORTRAIT_MIN_RUN = 4

#: A column with this much white ink is text, and text sits ON the plate. Lower
#: than `TEXT_V_MIN`'s per-pixel test because this one is per column.
PORTRAIT_TEXT_FRAC = 0.15


def _entry_columns(green_band, red_band, white_band, bh: int) -> np.ndarray:
    """Per column: is this the entry's own furniture -- plate, or text on it?"""
    covered = ((green_band.sum(axis=0) + red_band.sum(axis=0))
               >= PLATE_COL_FRAC * bh)
    text = white_band.sum(axis=0) >= PORTRAIT_TEXT_FRAC * bh * 255
    return covered | text


def _portrait_edge(on: np.ndarray, start: int, step: int, w: int,
                   max_walk: int | None = None) -> int | None:
    """Walk out from a name to the first sustained gap in the entry's furniture.

    That gap is the portrait, and the walk stops there rather than continuing,
    which is what keeps the scenery out. Past the entry the ROI is open world
    and warm scenery reads as the enemy plate's red, so any rule that looks for
    the LARGEST plate run, or the last one, runs off the end of the entry --
    both were tried, and both put the box on the weapon icon or the wall.

    ``max_walk`` bounds the search. Walking further than ``max_walk`` columns
    (e.g. into assist icons) indicates the portrait art itself was plate-coloured
    and the gap was stepped over; in that case the portrait abuts ``start`` directly.
    """
    x = start
    steps = 0
    while 0 <= x < w:
        if max_walk is not None and steps > max_walk:
            return start
        if not on[x]:
            ahead = [x + step * d for d in range(PORTRAIT_MIN_RUN)]
            if all(0 <= p < w for p in ahead) and not any(on[p] for p in ahead):
                return x
        x += step
        steps += 1
    return None


def portrait_observations(frame: np.ndarray, roi: Roi, width: int, height: int,
                          views: "list[EntryView] | None" = None,
                          mask: np.ndarray | None = None,
                          profile_name: str = "valorant-16x9") -> list[dict]:
    """Context-free appearance evidence for each entry's two agent portraits.

    **The killfeed draws the agent, and nothing has ever looked at it.** Every
    entry carries the killer's portrait and the victim's, the reference art for
    all 29 is already in the store, and this module has only ever used those
    portraits as landmarks -- the thing at the ROI edge that is not a name. So
    the one channel that names agents on BOTH teams, and that fires on a death
    rather than only while a side is at five alive, has been discarded on every
    frame.

    Like `scoreboard.portrait_observations`, this emits the descriptor and the
    box and NEVER an agent. Turning a descriptor into a name needs the lineup to
    say which five agents that side may hold, and that belongs to an
    adjudicator; a reader that borrowed the lineup's conclusion would make two
    channels into one witness.

    The plate is masked OUT of the descriptor. Agent art is drawn over a
    team-coloured plate, and unmasked every ally portrait would resemble every
    other ally portrait rather than the agent it shows.

    `clipped` is the fraction of the portrait's expected width that falls
    outside the ROI. The victim's portrait sits at the entry's right end and is
    routinely cut by a few pixels; a consumer weighing two claims should know
    which one saw a whole face.
    """
    if views is None:
        views = analyse_killfeed(frame, roi, width, height, mask=mask,
                                 profile_name=profile_name)
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)
    green, red, white = _plate_masks(crop, mask)

    out: list[dict] = []
    for view in views:
        if not (view.killer_run and view.victim_run):
            continue
        bh = view.y1 - view.y0
        if bh < 8:
            continue
        band = crop[view.y0:view.y1]
        on = _entry_columns(green[view.y0:view.y1], red[view.y0:view.y1],
                            white[view.y0:view.y1], bh)
        furniture = (green[view.y0:view.y1] | red[view.y0:view.y1]
                     | (white[view.y0:view.y1] > 0))
        wide = int(round(PORTRAIT_ASPECT * bh))
        for role, start, step in (("killer", view.killer_run[0] - 1, -1),
                                  ("victim", view.victim_run[1] + 1, +1)):
            if role == "killer":
                # In Valorant's layout [killer portrait][killer name], the killer
                # portrait abuts the name run directly. Walking left with _portrait_edge
                # steps into the portrait art itself (hair/shadows) or into assist icons.
                edge = start
            else:
                edge = _portrait_edge(on, start, step, w)
            if edge is None:
                out.append({"slot": view.slot, "role": role,
                            "reason": "no gap past the name"})
                continue
            outer = edge + step * wide
            px0, px1 = sorted((edge, outer))
            px0, px1 = max(0, px0), min(w, px1)
            art = band[:, px0:px1]
            keep = ~furniture[:, px0:px1]

            # Sample bounded candidate offsets for spatial crop uncertainty search
            shifts = {}
            for dx in (-4, -2, 0, 2, 4):
                sx0 = max(0, min(w - wide, px0 + dx))
                sx1 = min(w, sx0 + wide)
                art_s = band[:, sx0:sx1]
                keep_s = ~furniture[:, sx0:sx1]
                shifts[dx] = appearance.hsv_composition(art_s, keep_s).tolist()

            out.append({
                "slot": view.slot, "role": role,
                "x0": int(px0), "x1": int(px1),
                "y0": int(view.y0), "y1": int(view.y1),
                "clipped": round(1.0 - (px1 - px0) / max(1, wide), 4),
                "art_fraction": round(float(keep.mean()) if keep.size else 0.0, 4),
                "detail": round(appearance.detail(art), 3),
                "composition": appearance.hsv_composition(art, keep).tolist(),
                "shifts": shifts,
                # Which team this portrait belongs to. The killer and the victim
                # are on opposite sides of every entry, and `victim_ally` is
                # read from the plate the VICTIM's name sits on.
                "ally": None if view.victim_ally is None else
                        (view.victim_ally if role == "victim"
                         else not view.victim_ally),
                "reason": "",
            })
    return out


# --------------------------------------------------------------------------- second life
# The circular badge a second-life death carries (Phoenix Run It Back, a downed
# KAY/O) [domain:rounds/resurrection-mechanics]. Read here, in the reader
# that already crops every entry; `adjudication.death` re-exports it.

SECOND_LIFE_WHITE_V_MIN = 190
SECOND_LIFE_WHITE_S_MAX = 70
SECOND_LIFE_R_FRAC = (0.26, 0.42)
SECOND_LIFE_CX_FRAC = 0.45
SECOND_LIFE_N_THETA = 64
SECOND_LIFE_RUN_MIN = 0.29


def _white_mask(bgr: np.ndarray) -> np.ndarray:
    """Mask white line art: bright and near-zero saturation against plate backgrounds."""
    import cv2
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return (hsv[:, :, 2] >= SECOND_LIFE_WHITE_V_MIN) & (hsv[:, :, 1] <= SECOND_LIFE_WHITE_S_MAX)


def _longest_circular_run(hit: np.ndarray) -> int:
    """Longest circular run of consecutive True samples along a circumference."""
    n = len(hit)
    if hit.all():
        return n
    best = run = 0
    for k in range(2 * n):
        if hit[k % n]:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return min(best, n)


def fit_arc(mask: np.ndarray, cx0: float) -> tuple[float, float, float, float]:
    """Best (coverage, longest_run, cx, r) over a circular arc search.

    Ported from `prototypes/revive_mark.py`. Coverage alone was measured not to
    separate: a fitted circle's coverage reads 0.59-0.69 on the badge and 0.64
    on a plain headshot crosshair (four bars around a point), and 0.28-0.34 on
    letters. A ring is one unbroken arc and a crosshair four short runs, so the
    discriminator is the longest circular run of white along the circumference,
    selected on first, with coverage kept beside it.
    """
    h, w = mask.shape
    best = (0.0, 0.0, cx0, 0.0)
    th = np.linspace(0.0, 2.0 * np.pi, SECOND_LIFE_N_THETA, endpoint=False)
    ct, stt = np.cos(th), np.sin(th)
    cy = (h - 1) / 2.0
    for r in np.arange(SECOND_LIFE_R_FRAC[0] * h, SECOND_LIFE_R_FRAC[1] * h, 0.5):
        for cx in np.arange(cx0 - SECOND_LIFE_CX_FRAC * h, cx0 + SECOND_LIFE_CX_FRAC * h, 1.0):
            xs = np.rint(cx + r * ct).astype(int)
            ys = np.rint(cy + r * stt).astype(int)
            ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
            if ok.sum() < SECOND_LIFE_N_THETA:
                continue
            hit = mask[ys, xs]
            run = _longest_circular_run(hit) / float(SECOND_LIFE_N_THETA)
            if run > best[1]:
                best = (float(hit.mean()), float(run), float(cx), float(r))
    return best


def detect_second_life_badge(
    crop: np.ndarray,
    victim_x: float | None = None,
    run_min: float = SECOND_LIFE_RUN_MIN,
) -> tuple[bool, dict]:
    """Detect circular second-life badge (e.g. Phoenix Run It Back / KAY/O downed) on an entry crop.

    When `victim_x` is supplied, `crop` is the full entry band and the search
    window is centered on `victim_x` with a width equal to twice the band height.
    When `victim_x` is None, `crop` is assumed to already be centered on the badge boundary.

    Returns:
        tuple (has_badge, metrics_dict) where metrics_dict contains coverage, run, cx, r.
    """
    if crop is None or crop.size == 0 or crop.shape[0] < 10:
        return False, {"coverage": 0.0, "run": 0.0, "cx": 0.0, "r": 0.0, "has_badge": False}

    bh = crop.shape[0]
    if victim_x is not None:
        x0 = max(0, int(victim_x) - bh)
        x1 = min(crop.shape[1], int(victim_x) + bh)
        sub = crop[:, x0:x1]
        if sub.shape[1] < 8:
            return False, {"coverage": 0.0, "run": 0.0, "cx": 0.0, "r": 0.0, "has_badge": False}
        cx0 = float(int(victim_x) - x0)
        cov, run, cx, r = fit_arc(_white_mask(sub), cx0)
        has_badge = run >= run_min
        return has_badge, {
            "coverage": round(cov, 3),
            "run": round(run, 3),
            "cx": round(cx + x0, 1),
            "r": round(r, 1),
            "has_badge": has_badge,
        }
    else:
        cx0 = float(crop.shape[1] / 2.0)
        cov, run, cx, r = fit_arc(_white_mask(crop), cx0)
        has_badge = run >= run_min
        return has_badge, {
            "coverage": round(cov, 3),
            "run": round(run, 3),
            "cx": round(cx, 1),
            "r": round(r, 1),
            "has_badge": has_badge,
        }


KILLFEED_WEAPON_VERSION = "killfeed-weapon-0.1.0"

#: White mask cut for the weapon slot's line art against a coloured plate. The
#: icon is drawn at V >= 240 and S < 20; the translucent green plate over a
#: bright scene reaches S 50-75 at V 185-200, and a cut of (185, 75) admitted it,
#: inflating the tight box and splitting one Vandal into three groups on
#: a06f04a0059f (prototypes/weapon_icons.py).
ICON_WHITE_V_MIN = 220
ICON_WHITE_S_MAX = 45
ICON_GRID = (16, 64)          # h, w of a tight icon mask resized to one height
ICON_MIN_TIGHT_W = 12         # narrower than any gun or ability icon


def icon_white_mask(crop: np.ndarray) -> np.ndarray:
    """The weapon slot's white line art, without the neighbouring slots' edges."""
    h = crop.shape[0]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 2] > ICON_WHITE_V_MIN) & (hsv[:, :, 1] < ICON_WHITE_S_MAX)
    # A thin run along the top or bottom edge is the next entry's plate bleeding in.
    if h >= 25 and white.any():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8))
        if n > 2:
            max_area = stats[1:, cv2.CC_STAT_AREA].max()
            clean = np.zeros_like(white)
            for k in range(1, n):
                top, ch = stats[k, cv2.CC_STAT_TOP], stats[k, cv2.CC_STAT_HEIGHT]
                if ((top <= 1 or top + ch >= h - 1) and ch <= 3
                        and stats[k, cv2.CC_STAT_AREA] < max_area * 0.4):
                    continue
                clean[labels == k] = True
            if clean.any():
                white = clean
    return white


def icon_grid(white_mask: np.ndarray) -> tuple[np.ndarray, float] | None:
    """A white mask cut to its tight box and resized to ICON_GRID, with the box's
    aspect; None when too little is white to be an icon."""
    ys, xs = np.nonzero(white_mask)
    if len(xs) < 10 or xs.max() - xs.min() + 1 < ICON_MIN_TIGHT_W:
        return None
    tight = white_mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    grid = cv2.resize(tight.astype(np.uint8), ICON_GRID[::-1], interpolation=cv2.INTER_AREA)
    return grid, tight.shape[1] / tight.shape[0]


def weapon_icon_observations(frame: np.ndarray, roi: Roi, width: int, height: int,
                             views: "list[EntryView]") -> list[dict]:
    """Each entry's weapon-slot descriptor: the packed grid and aspect, never a name.

    Naming the icon is `adjudication.weapon`'s; a consumer binds these rows to an
    entry by slot, time and divider column and asks the owner from storage.
    """
    x0, y0, _, _ = roi.pixels(width, height)
    out = []
    for v in views:
        if v.wx1 <= v.wx0 or v.y1 <= v.y0:
            continue
        crop = frame[y0 + v.y0:y0 + v.y1, x0 + v.wx0:x0 + v.wx1]
        cut = icon_grid(icon_white_mask(crop))
        row = {"slot": v.slot, "y0": int(v.y0), "y1": int(v.y1), "wx0": int(v.wx0),
               "wx1": int(v.wx1), "verdict": v.verdict}
        if cut is None:
            out.append({**row, "grid": None, "aspect": None, "reason": "no_icon"})
        else:
            out.append({**row, "grid": np.packbits(cut[0].astype(bool)).tobytes().hex(),
                        "aspect": round(float(cut[1]), 4), "reason": None})
    return out


def unpack_icon_grid(packed: str) -> np.ndarray:
    """A stored `grid` back to the ICON_GRID array `icon_grid` produced."""
    bits = np.unpackbits(np.frombuffer(bytes.fromhex(packed), np.uint8))
    return bits[:ICON_GRID[0] * ICON_GRID[1]].reshape(ICON_GRID).astype(np.uint8)


class KillfeedPortraitReader:
    """Persist context-free portrait observations from the shared HUD pass.

    This reader does not name an agent. It stores the descriptor, role, side
    evidence and source coordinates so `adjudication.identity` can later join
    it to a lineup without reopening the video.
    """

    def __init__(self, profile, wh, mask=None, hz=2.0, spans=None):
        self.profile = profile
        self.w, self.h = wh
        self.mask = mask
        self.roi = killfeed_roi(profile)
        self.name = "killfeed_portrait"
        self.hz = hz
        self.spans = spans
        self.rows: list[dict] = []
        self.badges: list[dict] = []
        self.weapons: list[dict] = []
        self.frames_offered = 0

    def feed(self, smp) -> None:
        self.frames_offered += 1
        if self.roi is None:
            return
        views = analyse_killfeed(
            smp.frame, self.roi, self.w, self.h, self.mask,
            self.profile.name)
        # The player's own deaths: does the entry carry the second-life badge?
        # Stored for every such entry, badge or not, so a consumer can tell a
        # Run It Back death from a death, and both from an entry never read.
        x0, y0, x1, y1 = self.roi.pixels(self.w, self.h)
        for view in views:
            if view.verdict != "death" or not view.victim_run or view.y1 - view.y0 < 10:
                continue
            band = smp.frame[y0 + view.y0:y0 + view.y1, x0:x1]
            has_badge, metrics = detect_second_life_badge(band, view.victim_run[0])
            self.badges.append({"frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms),
                                "slot": view.slot, "y0": int(view.y0), "y1": int(view.y1),
                                "victim_x": int(view.victim_run[0]),
                                "has_badge": bool(has_badge), **metrics})
        for row in weapon_icon_observations(smp.frame, self.roi, self.w, self.h, views):
            self.weapons.append({"frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms), **row})
        for observation in portrait_observations(
                smp.frame, self.roi, self.w, self.h, views=views,
                mask=self.mask, profile_name=self.profile.name):
            self.rows.append({
                "frame_idx": int(smp.frame_idx),
                "t_ms": float(smp.t_ms),
                **observation,
            })

    def events(self, session_id: str) -> list[dict]:
        """Return JSONL-ready raw observations, never identity verdicts.

        The coverage row carries the REFUSALS and their reasons, not only the
        count of what was read. A rate needs both halves, and a reason nobody
        tallies is a guard that fires eleven times more often on one session
        than another with nothing to show it -- which is `census`'s whole
        argument, applied to the file this reader writes.
        """
        common = {
            "session_id": session_id,
            "source": "killfeed",
            "killfeed_portrait_version": KILLFEED_PORTRAIT_VERSION,
        }
        refused = Counter(row["reason"] for row in self.rows if row.get("reason"))
        coverage = {
            **common,
            "kind": "coverage",
            "frames_offered": self.frames_offered,
            "observations": len(self.rows),
            "described": len(self.rows) - sum(refused.values()),
            "refused": sum(refused.values()),
            "refused_reasons": dict(sorted(refused.items())),
        }
        rows = []
        for row in self.rows:
            out = dict(row)
            # The descriptor is two thirds of the stored row at full float
            # repr, and the gate it feeds is measured in hundredths. Five
            # decimals is three orders of magnitude below the finest margin
            # anything compares.
            if out.get("composition") is not None:
                out["composition"] = [round(v, 5) for v in out["composition"]]
            if out.get("shifts") is not None:
                out["shifts"] = {str(k): [round(v, 5) for v in comp]
                                 for k, comp in out["shifts"].items()}
            rows.append({
                **common,
                "kind": "portrait_observation",
                "observation_key":
                    f"{session_id}:{row['frame_idx']}:{row['slot']}:{row['role']}",
                **out,
            })
        coverage["second_life_observations"] = len(self.badges)
        coverage["second_life_badges"] = sum(b["has_badge"] for b in self.badges)
        badges = [{**common, "kind": "second_life_observation", **b} for b in self.badges]
        return [coverage] + rows + badges

    def weapon_events(self, session_id: str) -> list[dict]:
        """The `killfeed_weapon` stream: a coverage row with its refusals, then
        one descriptor row per entry per frame. Its own stamp, so the weapon
        descriptor can change without restating the portraits."""
        common = {"session_id": session_id, "source": "killfeed",
                  "killfeed_weapon_version": KILLFEED_WEAPON_VERSION}
        refused = Counter(r["reason"] for r in self.weapons if r["reason"])
        coverage = {**common, "kind": "coverage", "frames_offered": self.frames_offered,
                    "observations": len(self.weapons),
                    "described": len(self.weapons) - sum(refused.values()),
                    "refused_reasons": dict(sorted(refused.items()))}
        return [coverage] + [{**common, "kind": "weapon_icon_observation", **r}
                             for r in self.weapons]


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
    census: "Census | None" = None,
    t_ms: float | None = None,
) -> KillfeedRead:
    """Count killfeed entries and attribute any the local player is in."""
    seen = analyse_killfeed(frame, roi, width, height, mask, profile_name,
                            census, t_ms)
    # An empty band is a plate-coloured region carrying none of an entry's
    # furniture. It is not an entry and it does not enter the stack, so nothing
    # that tracks entry movement is handed one. It is still counted, because
    # several in one frame says the ROI is being painted over.
    views = [v for v in seen if v.verdict != "empty_band"]
    empty = [v for v in seen if v.verdict == "empty_band"]
    kills = [v for v in views if v.verdict == "kill"]
    deaths = [v for v in views if v.verdict == "death"]
    return KillfeedRead(
        entries=len(views),
        slots=tuple(v.slot for v in views),
        entry_ys=tuple(v.y0 for v in views),
        empty_bands=len(empty),
        empty_band_reason=next((v.reason for v in empty if v.reason), None),
        player_kill=bool(kills),
        player_death=bool(deaths),
        kill_slots=tuple(v.slot for v in kills),
        death_slots=tuple(v.slot for v in deaths),
        kill_ys=tuple(v.y0 for v in kills),
        death_ys=tuple(v.y0 for v in deaths),
        entry_wxs=tuple(_trusted_wx(v) for v in views),
        entry_ally=tuple(v.victim_ally for v in views),
        kill_wxs=tuple(_trusted_wx(v) for v in kills),
        death_wxs=tuple(_trusted_wx(v) for v in deaths),
        unattributed=sum(1 for v in views if v.verdict in ("occluded", "tie")),
        unparsed=sum(1 for v in views if v.verdict == "unparsed"),
        unparsed_reason=next((v.reason for v in views
                              if v.verdict == "unparsed" and v.reason), None),
    )
