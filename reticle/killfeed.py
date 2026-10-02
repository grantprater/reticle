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
   the band already applied, moved a step earlier -- keeps them out. It cost
   the topmost entry, which is the oldest on screen, since new entries arrive
   at the bottom [domain:killfeed/stack-order]: here the death at
   9acf02f98283 20:32.

5. **Clipping at the ROI's top edge.** c40d950031bb 15:12, "pan (rifle) Me"
   scoring 0.41 against a 0.65 bar on a band at y0-37: the entry has risen into
   the top slot and its glyph tops are cut off by the ROI boundary. It arrived
   below another entry at 908.5 s and rose at 910.0 s, as the stack does
   [domain:killfeed/stack-order].
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

Owns [owns:killfeed-event], [owns:killfeed-portrait], [owns:killfeed-second-life-badge],
[owns:killfeed-weapon-descriptor] and [owns:killfeed-name-descriptor].
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from itertools import chain
from pathlib import Path
import warnings

import numpy as np

import cv2

from . import appearance
from .census import Census
from .profiles import Profile, Roi, template_key
from .usage import step as usage_step

#: The capture height every length constant in this module was measured at.
BASE_HEIGHT = 1080


class KillfeedScale:
    """The one transform from a base length (ROI px at 1080p) to this
    capture's ROI px: `scale` = capture height / BASE_HEIGHT. Readers write
    `s.px(BASE)` (or `s.n` where an integer is required, `s.area` for pixel
    counts), never a per-size constant; dimensionless ratios (plate shares,
    whiteness cuts, PORTRAIT_ASPECT) stay as they are.

    The killfeed has no size setting of its own; only the minimap scales apart
    from resolution [domain:hud/hud-scales-with-resolution], so resolution is
    the whole transform and no profile factor applies. The minimap's widget
    scale (`geometry.MapScale`) was measured at 1080p only; whether it composes
    with resolution is untested (the player expects it does).

    The capture sets the scale, never a session's pixels: `scale_check`
    compares a session's measured plate height against `px(ENTRY_H)` and
    reports the disagreement; it never replaces the scale. At scale 1.0 every
    length is the base value itself, so a 1080p capture reads exactly as
    before the transform existed.
    """

    __slots__ = ("scale", "source")

    def __init__(self, scale: float, source: str):
        self.scale, self.source = float(scale), source

    @classmethod
    def for_capture(cls, width: int, height: int) -> "KillfeedScale":
        """The transform for a capture of this size: its height over 1080."""
        if int(height) == BASE_HEIGHT:
            return UNIT_SCALE
        return cls(int(height) / BASE_HEIGHT, "capture_height")

    @classmethod
    def at(cls, scale: float, source: str = "given") -> "KillfeedScale":
        """A transform of a stated scale, for synthetic crops and tests."""
        return cls(scale, source)

    def px(self, base: float) -> float:
        """A base length in this capture's px; exactly `base` at scale 1."""
        return float(base) if self.scale == 1.0 else round(float(base) * self.scale, 6)

    def n(self, base: float) -> int:
        """A base length rounded to whole px, where a slice or kernel needs one."""
        return int(round(self.px(base)))

    def area(self, base: float) -> float:
        """A base area or pixel count in this capture's px^2."""
        return float(base) if self.scale == 1.0 else round(float(base) * self.scale ** 2, 6)

    def base(self, px: float) -> int:
        """A capture px length back to whole base px, for storage keyed in base px."""
        return int(px) if self.scale == 1.0 else int(round(float(px) / self.scale))

    def provenance(self) -> dict:
        return {"scale": round(self.scale, 6), "source": self.source,
                "base_height": BASE_HEIGHT}

    def __repr__(self) -> str:
        return f"KillfeedScale({self.provenance()})"


#: Scale 1.0: a 1080p capture, and the default of every helper below.
UNIT_SCALE = KillfeedScale(1.0, "capture_height")

#: How far a session's median plate height may sit from `px(ENTRY_H)` before
#: `scale_check` reports the scale and the capture disagreeing.
SCALE_CHECK_TOL = 0.1


def plate_height(green_band: np.ndarray, red_band: np.ndarray) -> int:
    """Rows of one entry band that its plate fills: rows whose plate share,
    across the band's plate-covered columns, reaches PLATE_ROW_FRAC. A
    measurement of the capture, for `scale_check` and for comparing two
    placements of one band; never a length to read by."""
    plate = green_band | red_band
    cols = plate.any(axis=0)
    if not cols.any():
        return 0
    return int((plate[:, cols].mean(axis=1) >= PLATE_ROW_FRAC).sum())


def scale_check(heights, s: "KillfeedScale") -> dict:
    """A session's measured plate heights (`plate_height` of resting entries)
    against the scale's `px(ENTRY_H)`. It reports; it never sets the scale."""
    h = [int(v) for v in heights if v]
    expected = s.px(ENTRY_H)
    if not h:
        return {"expected": expected, "measured_median": None, "n": 0,
                "ratio": None, "agrees": None, "reason": "no_plate_rows"}
    med = float(np.median(h))
    ratio = round(med / expected, 4)
    return {"expected": expected, "measured_median": med, "n": len(h), "ratio": ratio,
            "agrees": bool(abs(ratio - 1.0) <= SCALE_CHECK_TOL), "reason": None}

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

# A band with fewer visible (unmasked) pixels than this is dropped as occluded.
BAND_VISIBLE_MIN = 500

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
# An icon is line art: pure white strokes. A pale victim plate (a green ally
# plate lightening toward the portrait) passes the text mask too, merges with
# the victim's letters into one blob, and outweighs a ringed ult icon whose
# ring breaks into two narrow arcs: 043bafca271a 944.0 s took the plate at
# 346-412 over Not Dead Yet's butterfly. There the plate's median V was 217
# and every icon stroke's 252-255. Letters merged along a pale victim plate
# are brighter (V 242-244 at 59c70f1ef720 498.5 s) but tinted (median S
# 26-32), where guns and butterflies read S 4-15. A candidate inside both
# bars is tried before any that is not.
ICON_V_MED_MIN, ICON_S_MED_MAX = 250, 20
# Jett's Blade Storm knife [domain:killfeed/jett-blade-storm-icon] is 19x19 px
# and 92 px of ink at 59c70f1ef720 2080.0 s, under both tiers above, and so
# is Not Dead Yet's butterfly when its ring splits off; line art that small
# is a candidate only in the first pass (see `_band_text`).
KNIFE_MIN_AREA, KNIFE_MIN_H = 60, 12
# An ability icon drawn in thin strokes breaks under the text cut into pieces
# no tier above admits: Neon's Overdrive (75a55a296d3b 1205.5 s) into a 22x10
# and a 23x5 bar two rows apart, plus two 8x3 ticks, 201 px of ink in all.
# `_stroke_groups` joins line-art pieces off the name baseline that lie within
# this many base px of each other, plus any line art inside the group's box,
# and offers the group as one icon at the knife's bar, in a last pass.
STROKE_JOIN = 3
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
# How far (a square kernel's side, base px) the overlay mask grows.
OVERLAY_GROW = 9
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
    # Which team each entry's killer was on, read behind the weapon icon
    # (`killer_is_ally`), parallel to `entry_ys`.
    entry_killer_ally: tuple[object, ...] = ()
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
    # The capture's `KillfeedScale`: rows are in this capture's px, the stored
    # slot masks and divider columns in base px (`absolute_slot`, `divider_of_ys`).
    scale: float = 1.0

    @property
    def _s(self) -> "KillfeedScale":
        return UNIT_SCALE if self.scale == 1.0 else KillfeedScale.at(self.scale, "capture_height")

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
        return mask_of_ys(self.entry_ys, self._s)

    @property
    def kill_mask(self) -> int:
        """Absolute-slot bitmask of the player's kill entries, for storage."""
        return mask_of_ys(self.kill_ys, self._s)

    @property
    def death_mask(self) -> int:
        return mask_of_ys(self.death_ys, self._s)

    @property
    def ally_mask(self) -> int:
        """Slots whose entry killed an *ally*. With `enemy_mask` this is what
        turns the feed into both teams' alive counts. A slot in `entry_mask` but
        in neither is an entry whose plate could not be read -- rare, and left
        unresolved rather than assigned to a side."""
        return mask_of_ys([y for y, al in zip(self.entry_ys, self.entry_ally) if al is True], self._s)

    @property
    def enemy_mask(self) -> int:
        return mask_of_ys([y for y, al in zip(self.entry_ys, self.entry_ally) if al is False], self._s)

    @property
    def same_side_mask(self) -> int:
        """Slots whose killer and victim plates read one side: a revive, an
        environmental self entry or a team kill [domain:killfeed/revive-entries].
        A slot whose killer or victim plate went unread is not in it."""
        killers = self.entry_killer_ally or (None,) * len(self.entry_ys)
        return mask_of_ys([y for y, al, ka in zip(self.entry_ys, self.entry_ally, killers)
                           if al is not None and ka is not None and al == ka], self._s)

    @property
    def entry_dividers(self) -> int:
        """Slot-keyed divider columns for every entry, player or not."""
        return divider_of_ys(self.entry_ys, self.entry_wxs, self._s)

    @property
    def kill_dividers(self) -> int:
        return divider_of_ys(self.kill_ys, self.kill_wxs, self._s)

    @property
    def death_dividers(self) -> int:
        return divider_of_ys(self.death_ys, self.death_wxs, self._s)

    @staticmethod
    def slots_of(mask) -> tuple[int, ...]:
        """Unpack a stored bitmask back to absolute slot indices."""
        if mask is None:
            return ()
        return tuple(s for s in range(MAX_SLOTS) if int(mask) & (1 << s))


def absolute_slot(y: int, s: "KillfeedScale" = UNIT_SCALE) -> int:
    """Which stack position a band at row `y` occupies.

    This is deliberately *not* the index of the band among those detected: that
    index shifts whenever a band above happens to be missed, which breaks any
    attempt to follow one entry across frames. Quantising the row instead gives
    a position that means the same thing in every frame.
    """
    return max(0, min(MAX_SLOTS - 1, int(round((y - s.px(FIRST_Y)) / s.px(PITCH)))))


def mask_of_ys(ys, s: "KillfeedScale" = UNIT_SCALE) -> int:
    m = 0
    for y in ys:
        m |= 1 << absolute_slot(y, s)
    return m


def divider_of_ys(ys, wxs, s: "KillfeedScale" = UNIT_SCALE) -> int:
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

    Columns are stored in base px (`KillfeedScale.base`), so they mean the
    same at every capture size and fit WX_BITS: a 1440p ROI is 652 px wide.
    """
    v = 0
    for y, wx in zip(ys, wxs):
        v |= (min(s.base(wx), WX_MAX) & WX_MAX) << (WX_BITS * absolute_slot(y, s))
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
    k = KillfeedScale.for_capture(width, height).n(OVERLAY_GROW)
    grown = cv2.dilate(persistent.astype(np.uint8), np.ones((k, k), np.uint8)) > 0
    return ~grown


def _row_profile(
    green: np.ndarray, red: np.ndarray, usable: np.ndarray | None = None,
    usable_prefix: np.ndarray | None = None,
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
    run whole. What it costs is the topmost entry, the oldest on screen
    [domain:killfeed/stack-order] -- the death at 9acf02f98283 20:32.

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
        vis = (usable_prefix if usable_prefix is not None
               else usable.astype(np.int32).cumsum(axis=1))
        seen = (vis[rows, hi] - vis[rows, lo] + usable[rows, lo]).astype(np.float64)
    prof = np.divide(inside, seen, out=np.zeros(plate.shape[0]), where=seen > 0)
    both = (
        (green.mean(axis=1) > ROW_COLOUR_FRAC)
        & (red.mean(axis=1) > ROW_COLOUR_FRAC)
    )
    return np.where(both, prof, 0.0)


def _join_split_runs(runs: list[tuple[int, int]],
                     s: "KillfeedScale" = UNIT_SCALE) -> list[tuple[int, int]]:
    """Rejoin one entry whose plate run broke in two at its text rows.

    The name glyphs and the weapon icon are white, so they punch the plate
    rows through their middle. Over a dark wall the translucent plate's darker
    end also fails the plate colour there, and a toggled overlay can hide one
    plate across those rows. The profile then drops under PLATE_ROW_FRAC for a
    few rows mid-entry, the run breaks in two, each piece is shorter than
    MIN_BAND_H, and both are discarded: the entry is absent, not misread. At
    c40d950031bb the player's death entry stood on screen from 701.0 s and read
    first at 703.5 s (runs of 12 and 18 rows); at 223d636bf8d2 the Shooting
    Error box split the player's death entry from 719.0 s to 720.5 s (runs of
    8 and 10 rows), and it read first at 721.0 s, after the combat report
    panel had opened.

    The rule fits the entry's shape rather than closing a gap of fixed radius:
    two adjacent runs, each too short to be an entry, are one entry when
    together they fit in one (MAX_BAND_H) and their plate covers at least half
    a minimum band. No run long enough to stand alone is joined. `_band_text`
    still decides whether the joined band holds an entry's names; a joined band
    with none is an empty band, not an entry.
    """
    out: list[tuple[int, int]] = []
    lo, hi = s.px(MIN_BAND_H), s.px(MAX_BAND_H)
    for a, z in runs:
        if out:
            pa, pz = out[-1]
            if (pz - pa < lo and z - a < lo and z - pa <= hi
                    and (pz - pa) + (z - a) >= s.n(MIN_BAND_H) // 2):
                out[-1] = (pa, z)
                continue
        out.append((a, z))
    return out


def _entry_bands(
    green: np.ndarray, red: np.ndarray, usable: np.ndarray | None = None,
    usable_prefix: np.ndarray | None = None, s: "KillfeedScale" = UNIT_SCALE,
) -> list[tuple[int, int]]:
    """Row spans holding one entry each, read off the plate row profile.

    Three things happen here, and the third is the one that matters most:

    * contiguous runs of plate-coloured rows are the candidate entries, and
      two short runs that one entry's text rows broke apart are rejoined
      (`_join_split_runs`);
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
    on = _row_profile(green, red, usable, usable_prefix) > PLATE_ROW_FRAC
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
    runs = _join_split_runs(runs, s)

    split: list[tuple[int, int]] = []
    lo, hi = s.px(MIN_BAND_H), s.px(MAX_BAND_H)
    for (a, z) in runs:
        h = z - a
        k = max(1, int(round(h / s.px(PITCH))))
        if k == 1:
            if lo <= h <= hi:
                split.append((a, z))
        else:
            step = h / k
            for m in range(k):
                a2 = a + int(round(m * step))
                z2 = a + int(round((m + 1) * step))
                if lo <= z2 - a2 <= hi:
                    split.append((a2, z2))

    bands: list[tuple[int, int]] = []
    for idx, (a, z) in enumerate(split):
        short = s.n(ENTRY_H) - (z - a)
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


def scaled_me_template(tpl_info, s: "KillfeedScale" = UNIT_SCALE):
    """The "Me" template resampled to this capture's scale. Mined at 1080p, so
    at scale 1 it is returned untouched; elsewhere it is an area resample of
    rendered text, an approximation (text rasterises nonlinearly)."""
    if tpl_info is None or s.scale == 1.0:
        return tpl_info
    tpl, _t0, _t1 = tpl_info
    h, w = tpl.shape
    big = cv2.resize(tpl.astype(np.float32), (max(1, s.n(w)), max(1, s.n(h))),
                     interpolation=cv2.INTER_AREA if s.scale < 1 else cv2.INTER_LINEAR)
    out = (big >= 127.5).astype(np.uint8) * 255
    cols = np.where(out.any(axis=0))[0]
    if cols.size == 0:
        return None
    return out, int(cols.min()), int(cols.max())


def _ink_runs(region: np.ndarray, s: "KillfeedScale" = UNIT_SCALE) -> list[tuple[int, int]]:
    """Column spans of text, split where NAME_GAP blank columns intervene."""
    xs = np.where((region > 0).any(axis=0))[0]
    if xs.size == 0:
        return []
    runs, start, prev = [], int(xs[0]), int(xs[0])
    gap = s.px(NAME_GAP)
    for x in xs[1:]:
        x = int(x)
        if x - prev > gap:
            runs.append((start, prev))
            start = x
        prev = x
    runs.append((start, prev))
    return runs


def name_run(region: np.ndarray, side: int,
             s: "KillfeedScale" = UNIT_SCALE) -> tuple[int, int] | None:
    """The text run holding this side's name: the one abutting the weapon icon.

    `side` is -1 for the killer's name, which ends at the icon, so the last run
    wins; +1 for the victim's, which begins after it, so the first does.
    """
    runs = _ink_runs(region, s)
    if not runs:
        return None
    return runs[-1] if side < 0 else runs[0]


def _match_me(region: np.ndarray, tpl_info, side: int,
              s: "KillfeedScale" = UNIT_SCALE) -> tuple[int, float]:
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
    runs = _ink_runs(region, s)
    if not runs:
        return 0, 0.0
    # Nearest the weapon icon first, then outward past any marks.
    ordered = list(reversed(runs)) if side < 0 else runs
    first_w = ordered[0][1] - ordered[0][0] + 1
    best_w, best_s = first_w, 0.0
    for run in ordered[:MAX_NAME_RUNS]:
        width = run[1] - run[0] + 1
        if not (s.px(ME_W[0]) <= width <= s.px(ME_W[1])):
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


def plate_seam(green_band: np.ndarray, red_band: np.ndarray,
               s: "KillfeedScale" = UNIT_SCALE) -> int | None:
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
    runs = _plate_runs(green_band, red_band, s)
    seams = [b[1] for a, b in zip(runs, runs[1:])
             if a[0] != b[0] and a[2] == b[1]]
    return int(seams[0]) if len(seams) == 1 else None


def _line_art(px: np.ndarray) -> bool:
    """Whether a component's HSV pixels read as the icon's white strokes."""
    return (np.median(px[:, 2]) >= ICON_V_MED_MIN
            and np.median(px[:, 1]) <= ICON_S_MED_MAX)


def _stroke_groups(st: np.ndarray, art: set, on_line, s: "KillfeedScale") -> list[np.ndarray]:
    """Line-art pieces of one icon joined into one box, as `cv2` stats rows.

    A group grows from a piece that is not a name glyph (`on_line(i)` false)
    by two rules until neither adds a piece: another such piece within
    `STROKE_JOIN` base px of the group's box, or any line-art piece inside the
    box widened by one px (an icon's inner strokes can be glyph-sized and sit
    on the baseline, as Showstopper's do). A name's letters join only from
    inside the box, so a group never runs along a name. A group is kept when
    it holds two or more pieces and reaches the knife's bar
    (`KNIFE_MIN_AREA`, `KNIFE_MIN_H`); one piece is already a candidate."""
    gap = s.px(STROKE_JOIN)
    free = sorted(art, key=lambda i: -st[i, 4])
    used: set = set()
    out = []
    for seed in free:
        if seed in used or on_line(seed):
            continue
        members = {seed}
        x0, y0 = st[seed, 0], st[seed, 1]
        x1, y1 = x0 + st[seed, 2], y0 + st[seed, 3]
        grew = True
        while grew:
            grew = False
            for i in free:
                if i in members or i in used:
                    continue
                a0, b0 = st[i, 0], st[i, 1]
                a1, b1 = a0 + st[i, 2], b0 + st[i, 3]
                inside = a0 >= x0 - 1 and b0 >= y0 - 1 and a1 <= x1 + 1 and b1 <= y1 + 1
                near = (not on_line(i) and a0 <= x1 + gap and a1 >= x0 - gap
                        and b0 <= y1 + gap and b1 >= y0 - gap)
                if inside or near:
                    members.add(i)
                    x0, y0, x1, y1 = min(x0, a0), min(y0, b0), max(x1, a1), max(y1, b1)
                    grew = True
        area = int(sum(st[i, 4] for i in members))
        if (len(members) >= 2 and area >= s.area(KNIFE_MIN_AREA)
                and y1 - y0 >= s.px(KNIFE_MIN_H)):
            used |= members
            out.append(np.array([x0, y0, x1 - x0, y1 - y0, area], dtype=st.dtype))
    return out


def _band_text(
    white: np.ndarray, usable: np.ndarray | None = None, plates=None,
    value: np.ndarray | None = None, s: "KillfeedScale" = UNIT_SCALE,
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
    idx = [i for i in range(1, n) if st[i, 4] >= s.area(MIN_COMP_AREA)]
    if not idx:
        return "no_ink"
    big = [i for i in idx if st[i, 2] >= s.px(ICON_MIN_W) and st[i, 3] >= s.px(ICON_MIN_H)]
    small = [i for i in idx if st[i, 4] >= s.area(ICON_MIN_AREA) and i not in set(big)]
    tiers = [big, small]
    tiny_pool = [i for i in idx if i not in set(big + small)
                 and st[i, 4] >= s.area(KNIFE_MIN_AREA) and st[i, 3] >= s.px(KNIFE_MIN_H)]
    if value is not None:
        # Line art first (ICON_V_MED_MIN, ICON_S_MED_MAX; `value` is the band's
        # HSV), then the old
        # tiers: an entry fading in or out dims its icon below the bar too
        # (043bafca271a 1058.5 s, a Vandal), and it must still divide the names.
        art = {i for i in big + small + tiny_pool if _line_art(value[lab == i])}
        tiers = [[i for i in big if i in art], [i for i in small if i in art],
                 [i for i in big if i not in art], [i for i in small if i not in art]]
        tiers.append([i for i in tiny_pool if i in art])
    gw, gh = (s.px(GLYPH_W[0]), s.px(GLYPH_W[1])), (s.px(GLYPH_H[0]), s.px(GLYPH_H[1]))
    cand = [
        i for i in idx
        if gw[0] <= st[i, 2] <= gw[1] and gh[0] <= st[i, 3] <= gh[1]
    ]
    groups, soft = [], []
    if value is not None and cand:
        # An ability icon in thin strokes breaks into pieces no tier admits
        # (`STROKE_JOIN`); join them. A piece on the name baseline is a glyph.
        line0 = int(np.bincount(np.array([st[i, 1] + st[i, 3] for i in cand])).argmax())
        glyph = set(cand)
        on_line = lambda i: (i in glyph
                             and abs(int(st[i, 1] + st[i, 3]) - line0) <= s.px(BASELINE_TOL))
        pieces = {i for i in idx if _line_art(value[lab == i])}
        groups = _stroke_groups(st, pieces, on_line, s)
        # Thin strokes blend with the plate: Showstopper's mark at
        # 75a55a296d3b 504.5 s reads median V 244, S 30, under the line-art
        # bar, as the names on a red plate do. Pieces of any tint group too,
        # for the last pass only.
        soft = _stroke_groups(st, set(idx), on_line, s)
        if groups or soft:
            st = np.vstack([st] + groups + soft)
    group_ids = list(range(n, n + len(groups)))
    soft_ids = list(range(n + len(groups), n + len(groups) + len(soft)))
    # `no_icon` once meant "nothing passes the size or area tier", and the
    # knife-sized line art the first pass admits (Showstopper's 19x19 mark at
    # 75a55a296d3b 504.5 s, Hot Hands' 12x18 flame) was never reached: 45 of
    # 56 ability and spike kills Riot records and the store missed were
    # refused here. Now it means no candidate of any tier or group.
    if not big and not small and not (value is not None and (tiny_pool or groups or soft)):
        return "no_icon"
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
    # Two passes, most trusted first. (1) Line art, down to the knife, with name
    # glyphs ON the baseline to its left: the killstreak numeral left of the
    # killer's portrait (III, IV) [domain:killfeed/killstreak-indicator] is
    # glyph-sized but sits below it, and made the portrait a divider at
    # 59c70f1ef720 2080.0 s. The victim's side takes
    # any glyph, since a pale plate can swallow a name. (2) Today's rule, line
    # art first, any glyph either side: a pale plate can swallow the KILLER's
    # name too (043bafca271a 820.0 s).
    bottoms = np.array([st[i, 1] + st[i, 3] for i in cand])
    line = int(np.bincount(bottoms).argmax())
    named = glyph_cols[np.abs(bottoms - line) <= s.px(BASELINE_TOL)]
    divides = lambda i, left, right: ((left < st[i, 0]).any()
                                      and (right > st[i, 0] + st[i, 2]).any())
    # (3) A line-art stroke group (`_stroke_groups`) with name glyphs on the
    # baseline to its left. (4) Last, a knife-sized piece or a group of any
    # tint, with name glyphs on the baseline on BOTH sides, so a piece of a
    # portrait cannot divide. Both take only candidates taller than any name
    # glyph, so two kerned letters merged into one piece cannot divide a name.
    # Both run only where every earlier pass failed, so no band an earlier
    # pass divides moves; a band the plate seam split now splits at its icon.
    # CROSS-REFERENCE: the icon is drawn on the killer's plate, so where the
    # plates meet at one seam (`plate_seam`) a late candidate must end by it.
    # A tall piece of the victim's portrait divided "CEOofTree [Paint Shells]
    # aatrox" inside the victim's plate at 4f207c0c4e39 1759.0 s without it.
    art_set = set(tiers[4]) if value is not None else set()
    seam = plate_seam(*plates, s=s) if plates is not None else None
    tall = lambda ids: [i for i in ids if st[i, 3] > gh[1]
                        and (seam is None or st[i, 0] + st[i, 2] <= seam + s.px(BASELINE_TOL))]
    late = ([([tall(group_ids)], named, glyph_cols)] if group_ids else []) + (
        [([tall(i for i in tiny_pool if i not in art_set), tall(soft_ids)], named, named)]
        if value is not None else [])
    passes = ([([tiers[0], tiers[1], tiers[4]], named, glyph_cols)] if value is not None
              else []) + [(tiers[:4], glyph_cols, glyph_cols)] + late
    wep = None
    for group, left, right in passes:
        for tier in group:
            wep = next((i for i in sorted(tier, key=lambda i: -st[i, 4])
                        if divides(i, left, right)), None)
            if wep is not None:
                break
        if wep is not None:
            break
    if wep is None:
        # Nothing icon-shaped divides two names. The plates still do -- see
        # `plate_seam`, which is what reads an ability kill. Last resort on
        # purpose: the seam is a *coarser* split than the icon (marks fall on
        # the killer's side of it), so it is only right to prefer it where
        # there is no icon to be had.
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
        if abs(int(st[i, 1] + st[i, 3]) - base) <= s.px(BASELINE_TOL):
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
    # Which team the killer was on, from the plate behind the weapon icon
    # (`killer_is_ally`); equal to `victim_ally` on a one-colour banner.
    killer_ally: bool | None = None
    # "kill" | "death" | "other" | "occluded" | "unparsed" | "tie"
    verdict: str = "unparsed"
    # Which guard refused, when the verdict is "unparsed": one of
    # `BAND_REFUSALS`, or a band-level reason when the band never reached
    # `_band_text` at all. Empty when nothing refused.
    reason: str = ""
    # The weapon-slot icon's column bounds (`icon_extent`): wx0..wx1 is one
    # piece, the divider; this is the element it points at, every piece of the
    # icon and nothing beside it. Only the `killfeed_weapon` descriptor reads
    # it. Zero when there is no icon.
    ix0: int = 0
    ix1: int = 0


def victim_is_ally(green, red, a: int, z: int, wx1: int, wx0: int | None = None,
                   s: "KillfeedScale" = UNIT_SCALE) -> bool | None:
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

    The last wide run is not always the plate either: a victim portrait with
    warm art (Sage's lips, Gekko's skin) forms a red run past a green plate, and
    10 of 105 player-labelled killers read the victim's side backwards
    (2026-09-25). The context that cannot be art is the plate behind the weapon
    icon, `wx0..wx1`: bright, plain and always the KILLER's, running to the
    chevron seam. Given `wx0`, the killer's colour is the one that holds at
    least twice the other's pixels there, and the victim's plate is the first
    run past the icon of the other colour -- or the killer's own colour when
    none differs, a one-colour revive or team kill. The name runs are no
    context: the killer's plate fades dark under the name, runs left of the
    icon are the killer portrait's art, and the victim's run can land on the
    headshot mark. The last run is kept where the icon decides no colour.

    Returns None when no run is wide enough to be a plate, which is the honest
    answer for a band that is half occluded.
    """
    W = green.shape[1]
    if wx1 >= W - s.px(MIN_PLATE_RUN):
        return None
    runs = _plate_runs(green[a:z, wx1:], red[a:z, wx1:], s)
    if not runs:
        return None
    killer_ally = killer_is_ally(green, red, a, z, wx0, wx1) if wx0 is not None else None
    if killer_ally is not None:
        killer = 1 if killer_ally else -1
        other = next((run for run in runs if run[0] != killer), None)
        return bool((other[0] if other else killer) > 0)
    return bool(runs[-1][0] > 0)


#: How many times the other colour's pixels the killer's colour must hold
#: behind the weapon icon to decide it.
ICON_PLATE_RATIO = 2


def killer_is_ally(green, red, a: int, z: int, wx0: int, wx1: int) -> bool | None:
    """Which team the killer was on, from the plate behind the weapon icon.

    The plate behind the icon is the killer's, bright and plain, and runs to
    the chevron seam (`victim_is_ally`). Its colour decides when it holds at
    least `ICON_PLATE_RATIO` times the other colour's pixels; otherwise None.
    A revive banner is one colour, so there this equals the victim's side
    [domain:killfeed/revive-entries]. Measured on the player's labels before
    it was stored: 20 of 22 revives and 2 of 72 named weapons (both
    Environmental) read killer and victim on one side
    (`prototypes/revive_plate_witness.py`).
    """
    if wx1 <= wx0:
        return None
    g, r = int(green[a:z, wx0:wx1].sum()), int(red[a:z, wx0:wx1].sum())
    if max(g, r) == 0 or max(g, r) < ICON_PLATE_RATIO * min(g, r):
        return None
    return g > r


def _plate_runs(green_band: np.ndarray, red_band: np.ndarray,
                s: "KillfeedScale" = UNIT_SCALE) -> list[tuple[int, int, int]]:
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
        if j - i >= s.px(MIN_PLATE_RUN):
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
    *,
    mask_prefix: np.ndarray | None = None,
    scale: "KillfeedScale | None" = None,
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
    s = scale or KillfeedScale.for_capture(width, height)
    tpl = scaled_me_template(me_template(profile_name), s)
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    h, w = crop.shape[:2]
    if mask is None:
        mask = np.ones((h, w), dtype=bool)
    green, red, white = _plate_masks(crop, mask)
    value = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)   # `_band_text` tests line art on it

    views: list[EntryView] = []
    for (a, z) in _entry_bands(green, red, mask, mask_prefix, s):
        slot = absolute_slot(a, s)
        where = (round(t_ms / 1000.0, 2) if t_ms is not None else None, slot)
        if census is not None:
            census.saw("bands")
        if mask[a:z].sum() < s.area(BAND_VISIBLE_MIN):   # too much of this band is occluded
            if census is not None:
                census.drop("band_masked_out", where)
            continue
        # Both plate colours must be present: that is what rejects warm scenery.
        if green[a:z].mean() < PLATE_MIN_FRAC or red[a:z].mean() < PLATE_MIN_FRAC:
            if census is not None:
                census.drop("band_one_plate_colour", where)
            continue
        parsed = _band_text(white[a:z] > 0, mask[a:z], (green[a:z], red[a:z]), value[a:z], s)
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
        _kw, k_score = _match_me(left, tpl, -1, s)
        _dw, d_score = _match_me(right, tpl, +1, s)
        krun = name_run(left, -1, s)
        vrun = name_run(right, +1, s)
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
        ix0, ix1 = icon_extent(white[a:z] > 0,
                               slot_white_mask(crop[a:z], green[a:z], red[a:z], s) & mask[a:z],
                               wx0, wx1, krun[1] + 1 if krun else 0, vrun[0] if vrun else w, s)
        views.append(EntryView(slot, int(a), int(z), int(wx0), int(wx1),
                               killer_run=krun, victim_run=vrun,
                               kill_score=k_score, death_score=d_score,
                               verdict=verdict,
                               victim_ally=victim_is_ally(green, red, a, z, wx1, wx0, s),
                               killer_ally=killer_is_ally(green, red, a, z, wx0, wx1),
                               ix0=int(ix0), ix1=int(ix1)))
    return views


#: The official killfeed portrait art is 256x128 -- TWO band heights wide. Taken
#: from the asset, not fitted to a session, which is why it is a ratio and not a
#: pixel count: the band height already carries the widget's scale.
PORTRAIT_ASPECT = 2.0
# 0.3.0 (2026-09-24): also stores a `second_life_observation` per read player
# death entry: whether it carries the Run It Back / downed badge.
# 0.4.0 (2026-09-25): the divider that splits killer from victim moved
# (`_band_text` line art), so the portrait crops beside it move too.
# 0.5.0 (2026-09-25): the killer's crop anchors at the name's first letter,
# descenders included (`killer_name_start`), not at the last baseline run.
# 0.6.0 (2026-09-25): two touching kerned letters ("Vy", "KA") count as one
# glyph in that walk (`_glyph_pair`), so the crop no longer stops a pair short;
# and the portrait rows follow the names' baseline when both names say the
# padded entry band landed low (`band_shift`, stored per row).
# 0.7.0 (2026-09-25): each portrait's `ally` follows `victim_is_ally`, which
# now reads the killer's colour behind the weapon icon.
# 0.8.0 (2026-09-28): the victim's walk starts at the name's end
# (`victim_name_end`: descenders, word spaces, merged letters, past a
# second-life badge) and counts as text only white ink that begins by then
# (`own_ink`), so white hair no longer carries the box past the portrait.
# 0.9.0 (2026-09-28): `_join_split_runs` reads an entry whose plate run
# broke at its text rows, so an entry can be observed samples earlier.
# 0.10.0 (2026-10-02): `_band_text` admits ability icons it refused as `no_icon`: knife-sized
# pieces of any tint and joined thin strokes (`_stroke_groups`), gated on the plate seam.
KILLFEED_PORTRAIT_VERSION = "killfeed-portrait-0.10.0"

#: How many columns must stay clear of plate and text before a gap is the
#: portrait rather than the space inside a letter.
PORTRAIT_MIN_RUN = 4
#: Bands shorter than this hold no portrait to describe.
PORTRAIT_MIN_BAND_H = 8
#: The crop offsets (base px) whose compositions `shifts` stores, keyed by
#: the base offset at every scale.
PORTRAIT_SHIFTS = (-4, -2, 0, 2, 4)

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
                   max_walk: int | None = None, s: "KillfeedScale" = UNIT_SCALE) -> int | None:
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
            ahead = [x + step * d for d in range(s.n(PORTRAIT_MIN_RUN))]
            if all(0 <= p < w for p in ahead) and not any(on[p] for p in ahead):
                return x
        x += step
        steps += 1
    return None


#: How far below the name's baseline a descender reaches, and how far above
#: it a letter's bottom may sit, in pixels.
NAME_DESCENDER = 5
NAME_BASE_TOL = 2

#: The most ink a column may carry where two kerned letters touch.
PAIR_BRIDGE_PX = 2


def _glyph_pair(lab: np.ndarray, st: np.ndarray, i: int,
                s: "KillfeedScale" = UNIT_SCALE) -> bool:
    """Is component `i` two kerned letters that touch -- the V and y of
    "Vyse", the K and A of "KAY/O" -- rather than portrait art? True when a
    column of at most `PAIR_BRIDGE_PX` ink splits it into two parts each a
    letter's width. A hidden name prints the agent's, so a touching pair
    recurs on every entry that agent's player makes."""
    x, y, w, h = (int(v) for v in st[i, :4])
    g0, g1 = s.px(GLYPH_W[0]), s.px(GLYPH_W[1])
    if not g1 < w <= 2 * g1:
        return False
    cols = (lab[y:y + h, x:x + w] == i).sum(axis=0)
    return any(cols[c] <= s.px(PAIR_BRIDGE_PX) and g0 <= c <= g1
               and g0 <= w - c - 1 <= g1 for c in range(1, w - 1))


def _name_glyphs(white_band: np.ndarray, run: tuple[int, int] | None,
                 s: "KillfeedScale" = UNIT_SCALE):
    """The band's glyph-sized white components, and the baseline row of those
    inside `run` (None when the run holds none)."""
    wb = (white_band > 0).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(wb, 8)
    glyph = [i for i in range(1, n) if st[i, 4] >= s.area(MIN_COMP_AREA)
             and (s.px(GLYPH_W[0]) <= st[i, 2] <= s.px(GLYPH_W[1]) or _glyph_pair(lab, st, i, s))
             and s.px(GLYPH_H[0]) <= st[i, 3] <= s.px(GLYPH_H[1]) + s.px(NAME_DESCENDER)]
    inside = [i for i in glyph if run and st[i, 0] >= run[0] and st[i, 0] + st[i, 2] - 1 <= run[1]]
    base = int(np.median([st[i, 1] + st[i, 3] for i in inside])) if inside else None
    return st, glyph, base


#: The names' baseline row inside a correctly placed entry band: the median
#: over 146 player-labelled killer crops, whose rows 22-24 all fit the face.
NAME_BASE_ROW = 23
#: How far both names' baselines must sit from `NAME_BASE_ROW` before the
#: band is taken to be misplaced, and how closely the two must agree.
BAND_SHIFT_MIN = 3
BAND_SHIFT_AGREE = 1


def band_shift(white_band: np.ndarray, killer_run, victim_run,
               s: "KillfeedScale" = UNIT_SCALE) -> int:
    """Rows to move an entry band so its names sit on `NAME_BASE_ROW`, or 0.

    `_entry_bands` pads a short plate run equally at both ends; when a slide or
    a highlight hides only the plate's top rows, the padded band lands 7 rows
    low and the portrait crop cuts the chin (seen on 6 of 146 labelled
    killers). The names do not move inside an entry, so their baseline says
    where the entry is. Both names must agree: one run on portrait art (a
    Clove whose killer run sat on her earrings read 14 against the victim's
    20) moves nothing.
    """
    kb = _name_glyphs(white_band, killer_run, s)[2]
    vb = _name_glyphs(white_band, victim_run, s)[2]
    if kb is None or vb is None or abs(kb - vb) > s.px(BAND_SHIFT_AGREE):
        return 0
    off = kb - s.n(NAME_BASE_ROW)
    return off if abs(off) >= s.px(BAND_SHIFT_MIN) else 0


def killer_name_start(white_band: np.ndarray, run: tuple[int, int],
                      s: "KillfeedScale" = UNIT_SCALE) -> int:
    """The first column of the killer's name, which the killer's portrait abuts.

    `_band_text` keeps only glyphs on the name's baseline, so a descender (the
    y of "Reyna") drops out of the text mask; the gap it leaves exceeds
    `NAME_GAP`, `name_run` takes the last run, and the run starts mid-name
    ("na" at a06f04a0059f 228.5 s). The portrait crop then sat on "Rey" with
    the face left of it. This walks left from the run over glyph-sized white
    components whose bottom reaches the name's baseline, descenders allowed,
    each within `NAME_GAP` of the last. A cap line taken from the run fails
    when the run is one lowercase letter (the e of "Sage", 96aa1ae9b96f
    372.0 s). Two kerned letters that touch count as one glyph
    (`_glyph_pair`); without that the walk stopped one pair short and the crop
    cut a hidden Vyse's face in half. The kill/death reading keeps the
    baseline run.
    """
    st, glyph, base = _name_glyphs(white_band, run, s)
    if base is None:
        return run[0]
    tol, desc = s.px(NAME_BASE_TOL), s.px(NAME_DESCENDER)
    rows = [i for i in glyph
            if base - tol <= st[i, 1] + st[i, 3] <= base + desc]
    x = run[0]
    while True:
        prev = [i for i in rows if st[i, 0] < x and x - (st[i, 0] + st[i, 2]) <= s.px(NAME_GAP)]
        if not prev:
            return x
        x = min(int(st[i, 0]) for i in prev)


def victim_name_end(white_band: np.ndarray, run: tuple[int, int],
                    mark_end: int | None = None, s: "KillfeedScale" = UNIT_SCALE) -> int:
    """The last column of the victim's name, which the victim's portrait
    follows across a stretch of bare plate.

    `killer_name_start` mirrored: walks right from the run over white
    components of a glyph's height on the name's baseline, descenders
    allowed, each within `NAME_GAP` of the last, and over a word space
    (`NAME_WORD_GAP`) to a glyph sitting ON the baseline. Width is not
    tested: letters that touch merge wider than `_glyph_pair` admits (the
    "me" of "jesussavedme", 59c70f1ef720 1866.0 s). `name_run` stops at the first space, so "Daddy
    Darkrai" ended at "Daddy" and the walk cut the box into "Darkrai"
    (5822b6646448 867.0 s).

    `mark_end` is the right edge of a second-life badge
    (`detect_second_life_badge`) fitted around the run: the run is then the
    badge's emblem, and the name begins at the first glyph past the ring,
    within a band height of it (a06f04a0059f 1576.0 s, bfad2778a372 2394.0 s).
    """
    st, glyph, base = _name_glyphs(white_band, run, s)
    if base is None:
        return run[1]
    right = lambda i: int(st[i, 0] + st[i, 2] - 1)
    bottom = lambda i: int(st[i, 1] + st[i, 3])
    tol, desc = s.px(NAME_BASE_TOL), s.px(NAME_DESCENDER)
    rows = [i for i in glyph if base - tol <= bottom(i) <= base + desc]
    line = [i for i in rows if abs(bottom(i) - base) <= tol]
    text = [i for i in range(1, st.shape[0]) if st[i, 4] >= s.area(MIN_COMP_AREA)
            and s.px(GLYPH_H[0]) <= st[i, 3] <= s.px(GLYPH_H[1]) + desc
            and base - tol <= bottom(i) <= base + desc]
    x = run[1]
    if mark_end is not None and mark_end >= x:
        past = [i for i in rows if mark_end < st[i, 0] <= mark_end + white_band.shape[0]]
        if past:
            x = right(min(past, key=lambda i: st[i, 0]))
    while True:
        ends = ([right(i) for i in text if right(i) > x and st[i, 0] - x <= s.px(NAME_GAP)]
                + [right(i) for i in line if right(i) > x and st[i, 0] - x <= s.px(NAME_WORD_GAP)])
        if not ends:
            return x
        x = max(ends)


def own_ink(white_band: np.ndarray, x: int) -> np.ndarray:
    """The white ink of components that begin at or before column `x`, the
    victim's name end: the name, and any mark the name run sits in.

    Portrait art is white too. Counted as text, Jett's white hair made every
    column of her portrait read as furniture, the walk in `_portrait_edge`
    crossed her face, and the box landed on the plate's end past it
    (a06f04a0059f 284.5 s: all 10 views at x 471-473, her portrait at 425).
    Her hair begins past a stretch of bare plate after the name. A mark does
    not: a second-life badge's ring encloses the emblem that holds the run
    (1576.0 s), its right arc starts before the run ends, and "Me" follows it
    on the plate. Dropping all white ink past the name stopped the walk
    inside that ring.
    """
    n, lab, st, _ = cv2.connectedComponentsWithStats((white_band > 0).astype(np.uint8), 8)
    keep = st[:, 0] <= x
    keep[0] = False
    return np.where(keep[lab], white_band, 0).astype(white_band.dtype)


def portrait_observations(frame: np.ndarray, roi: Roi, width: int, height: int,
                          views: "list[EntryView] | None" = None,
                          mask: np.ndarray | None = None,
                          profile_name: str = "valorant-16x9", *,
                          scale: "KillfeedScale | None" = None) -> list[dict]:
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
    s = scale or KillfeedScale.for_capture(width, height)
    if views is None:
        views = analyse_killfeed(frame, roi, width, height, mask=mask,
                                 profile_name=profile_name, scale=s)
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
        if bh < s.px(PORTRAIT_MIN_BAND_H):
            continue
        # The plate, and white ink that begins by the victim's name end
        # (`own_ink`); portrait art begins past it.
        badge, fit = detect_second_life_badge(crop[view.y0:view.y1], view.victim_run[0], s=s)
        name1 = victim_name_end(white[view.y0:view.y1], view.victim_run,
                                int(fit["cx"] + fit["r"]) if badge else None, s)
        on = _entry_columns(green[view.y0:view.y1], red[view.y0:view.y1],
                            own_ink(white[view.y0:view.y1], name1), bh)
        # The portraits are cut from the rows the names place the entry at
        # (`band_shift`); the columns stay read from the band as found.
        dy = band_shift(white[view.y0:view.y1], view.killer_run, view.victim_run, s)
        py0 = min(max(0, view.y0 + dy), max(0, h - bh))
        py1 = py0 + bh
        band = crop[py0:py1]
        furniture = green[py0:py1] | red[py0:py1] | (white[py0:py1] > 0)
        wide = int(round(PORTRAIT_ASPECT * bh))
        name0 = killer_name_start(white[view.y0:view.y1], view.killer_run, s)
        for role, start, step in (("killer", name0 - 1, -1),
                                  ("victim", name1 + 1, +1)):
            if role == "killer":
                # In Valorant's layout [killer portrait][killer name], the killer
                # portrait abuts the name run directly. Walking left with _portrait_edge
                # steps into the portrait art itself (hair/shadows) or into assist icons.
                edge = start
            else:
                edge = _portrait_edge(on, start, step, w, s=s)
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
            for dx in PORTRAIT_SHIFTS:
                sx0 = max(0, min(w - wide, px0 + s.n(dx)))
                sx1 = min(w, sx0 + wide)
                art_s = band[:, sx0:sx1]
                keep_s = ~furniture[:, sx0:sx1]
                shifts[dx] = appearance.hsv_composition(art_s, keep_s).tolist()

            out.append({
                "slot": view.slot, "role": role,
                "x0": int(px0), "x1": int(px1),
                "y0": int(py0), "y1": int(py1), "band_shift": int(py0 - view.y0),
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
# The second-life badge reader [domain:rounds/resurrection-mechanics]. It
# fits a ring beside the victim's name and names no icon. It is
# probably unspecific: the player expects it to fire on the KAY/O down icon
# [domain:killfeed/kayo-downed-entry] and on other icons beside the name.
# Whether it fires on the KAY/O icon is unmeasured: 4f207c0c4e39 fields
# KAY/O, but its down is not the player's, so no second-life row reads it. A badge read is evidence of some icon beside the victim's
# name, not of Run It Back. Read here, in the reader
# that already crops every entry; `adjudication.death` re-exports it.

SECOND_LIFE_WHITE_V_MIN = 190
SECOND_LIFE_WHITE_S_MAX = 70
SECOND_LIFE_R_FRAC = (0.26, 0.42)
SECOND_LIFE_CX_FRAC = 0.45
SECOND_LIFE_N_THETA = 64
SECOND_LIFE_RUN_MIN = 0.29
#: Base px: a band shorter, or a search window narrower, holds no badge.
SECOND_LIFE_MIN_BAND_H = 10
SECOND_LIFE_MIN_W = 8


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
    for value in chain(hit, hit):
        if value:
            run += 1
            if run > best:
                best = run
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
    s: "KillfeedScale" = UNIT_SCALE,
) -> tuple[bool, dict]:
    """Detect a ring-shaped icon beside the victim's name on an entry crop.

    The detector fits a ring beside the victim's name and names no icon. It is
    probably unspecific: the player expects it to fire on the KAY/O down icon
    [domain:killfeed/kayo-downed-entry] and on other icons beside the name.
    Whether it fires on the KAY/O icon is unmeasured: 4f207c0c4e39 fields
    KAY/O, but its down is not the player's, so no second-life row reads it. A badge read is evidence of some icon beside the victim's
    name, not of Run It Back.

    When `victim_x` is supplied, `crop` is the full entry band and the search
    window is centered on `victim_x` with a width equal to twice the band height.
    When `victim_x` is None, `crop` is assumed to already be centered on the badge boundary.

    Returns:
        tuple (has_badge, metrics_dict) where metrics_dict contains coverage, run, cx, r.
    """
    if crop is None or crop.size == 0 or crop.shape[0] < s.px(SECOND_LIFE_MIN_BAND_H):
        return False, {"coverage": 0.0, "run": 0.0, "cx": 0.0, "r": 0.0, "has_badge": False}

    bh = crop.shape[0]
    if victim_x is not None:
        x0 = max(0, int(victim_x) - bh)
        x1 = min(crop.shape[1], int(victim_x) + bh)
        sub = crop[:, x0:x1]
        if sub.shape[1] < s.px(SECOND_LIFE_MIN_W):
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


# 0.2.0 (2026-09-25): the weapon-slot box finds ringed ult icons and the
# Blade Storm knife [domain:killfeed/jett-blade-storm-icon] (`_band_text`).
# 0.3.0 (2026-09-28): more bands read (`_join_split_runs`); see the portrait stamp.
# 0.4.0 (2026-10-01): the descriptor is cut from the whole icon (`icon_extent`,
# ix0..ix1) rather than the divider piece alone; wx0..wx1 are unchanged.
# 0.5.0 (2026-10-01): line art is judged against the entry's own plate
# (`slot_white_mask`), the icon is the element the divider points at, split
# from names and marks by measured spacing (ELEMENT_GAP), and a revive's ring
# is fitted, stripped and published as `ringed` (`ring_fit`).
# 0.6.0 (2026-10-01): beside the unchanged grid, each row stores the soft
# glyph at native size (`soft`: plate-relative whiteness of the slot box,
# uint8, zlib), the slot geometry in base px with the capture's scale
# (`slot_geom`), whether the ring was stripped (`ring_stripped`) and the
# icon's sub-pixel centroid (`centroid`); the coverage row carries the
# scale and `scale_check`. Every 0.5.0 field is unchanged.
# 0.7.0 (2026-10-01): the slot is cut from the rows the entry's names place
# it at (`band_shift`, stored as `band_shift`), and a divider wholly outside
# the band's plate runs refuses as `off_plate_run`.
# 0.8.0 (2026-10-02): ability entries refused as `no_icon` are read; see the
# portrait stamp.
KILLFEED_WEAPON_VERSION = "killfeed-weapon-0.8.0"

#: White mask cut for the weapon slot's line art against a coloured plate. The
#: icon is drawn at V >= 240 and S < 20; the translucent green plate over a
#: bright scene reaches S 50-75 at V 185-200, and a cut of (185, 75) admitted it,
#: inflating the tight box and splitting one Vandal into three groups on
#: a06f04a0059f (prototypes/weapon_icons.py).
ICON_WHITE_V_MIN = 220
ICON_WHITE_S_MAX = 45
ICON_GRID = (16, 64)          # h, w of a tight icon mask resized to one height
ICON_MIN_TIGHT_W = 12         # narrower than any gun or ability icon
ICON_MIN_PX = 10              # fewer white pixels than any icon
#: The next entry's plate bleeding in along a crop's top or bottom edge: a run
#: at most BLEED_MAX_H tall, looked for only in crops BLEED_MIN_H or taller.
BLEED_MIN_H = 25
BLEED_MAX_H = 3


def icon_white_mask(crop: np.ndarray, s: "KillfeedScale" = UNIT_SCALE) -> np.ndarray:
    """The weapon slot's white line art, without the neighbouring slots' edges."""
    h = crop.shape[0]
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    white = (hsv[:, :, 2] > ICON_WHITE_V_MIN) & (hsv[:, :, 1] < ICON_WHITE_S_MAX)
    # A thin run along the top or bottom edge is the next entry's plate bleeding in.
    if h >= s.px(BLEED_MIN_H) and white.any():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(white.astype(np.uint8))
        if n > 2:
            max_area = stats[1:, cv2.CC_STAT_AREA].max()
            clean = np.zeros_like(white)
            for k in range(1, n):
                top, ch = stats[k, cv2.CC_STAT_TOP], stats[k, cv2.CC_STAT_HEIGHT]
                if ((top <= s.px(1) or top + ch >= h - s.px(1)) and ch <= s.px(BLEED_MAX_H)
                        and stats[k, cv2.CC_STAT_AREA] < max_area * 0.4):
                    continue
                clean[labels == k] = True
            if clean.any():
                white = clean
    return white


def icon_grid(white_mask: np.ndarray,
              s: "KillfeedScale" = UNIT_SCALE) -> tuple[np.ndarray, float] | None:
    """A white mask cut to its tight box and resized to ICON_GRID, with the box's
    aspect; None when too little is white to be an icon."""
    ys, xs = np.nonzero(white_mask)
    if len(xs) < s.area(ICON_MIN_PX) or xs.max() - xs.min() + 1 < s.px(ICON_MIN_TIGHT_W):
        return None
    tight = white_mask[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    grid = cv2.resize(tight.astype(np.uint8), ICON_GRID[::-1], interpolation=cv2.INTER_AREA)
    return grid, tight.shape[1] / tight.shape[0]


#: Plate-relative whiteness. The weapon-slot icon is semi-transparent white over
#: a red or teal plate, so a pixel's colour is (1 - a) * plate + a * white and
#: `plate_whiteness` recovers a, the share of the way from the local plate
#: colour to white. Measured on 349 parsed entries over 10 sessions (stored
#: crops; the icon cut's cores, eroded 3x3, against plate pixels 2 px or more
#: from any white ink): glyph cores median 0.989 (1st percentile 0.79), plate
#: 99th percentile 0.136. The cut is half the core value, the half-coverage
#: point of an anti-aliased edge: a thin tinted stroke the fixed V/S cut drops
#: (a Vandal's barrel, a pistol's slide) passes it.
PLATE_WHITE_CUT = 0.5
#: A column's plate colour is the median of its plate-coloured pixels when it
#: has this many; otherwise the nearest such column within PLATE_FILL px.
PLATE_MIN_PX = 2
PLATE_FILL = 12

#: Columns of background that separate two killfeed elements (portrait, name,
#: weapon-slot icon, headshot mark, name, portrait). Measured on the
#: plate-relative mask over 347 parsed entries in 10 sessions: within a name,
#: glyphs sit 1-3 px apart (1633 of 1683 gaps; 1410 of 1410 in victim names
#: within 4); killer name to icon 10-12, 20-22 or 29 px (7 of 302 at 6-7);
#: icon to the next element at least 10 px; the headshot mark to the victim's
#: name 19-20 px [domain:killfeed/killfeed-element-spacing]. A gap of 6 or more
#: separates elements.
ELEMENT_GAP = 6


def plate_colour(band: np.ndarray, green_band: np.ndarray, red_band: np.ndarray,
                 s: "KillfeedScale" = UNIT_SCALE):
    """Per column, the plate colour behind a band (BGR float) and whether it is known."""
    plate = (green_band | red_band)[:, :, None]
    px = np.where(plate, band.astype(np.float32), np.nan)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        P = np.nanmedian(px, axis=0)
    have = plate[:, :, 0].sum(axis=0) >= s.px(PLATE_MIN_PX)
    P[~have] = np.nan
    idx = np.nonzero(have)[0]
    if idx.size == 0:
        return P, have
    cols = np.arange(band.shape[1])
    k = np.clip(np.searchsorted(idx, cols), 1, max(idx.size - 1, 1))
    left, right = idx[np.clip(k - 1, 0, idx.size - 1)], idx[np.clip(k, 0, idx.size - 1)]
    near = np.where(np.abs(cols - left) <= np.abs(right - cols), left, right)
    ok = np.abs(near - cols) <= s.px(PLATE_FILL)
    return np.where(ok[:, None], P[near], np.nan), ok


def plate_whiteness(band: np.ndarray, green_band: np.ndarray, red_band: np.ndarray,
                    s: "KillfeedScale" = UNIT_SCALE):
    """(whiteness per pixel, columns with a known plate): the share of the way
    from the local plate colour to white, an estimate of the overlay's alpha."""
    P, ok = plate_colour(band, green_band, red_band, s)
    d = 255.0 - P[None, :, :]
    v = band.astype(np.float32) - P[None, :, :]
    with np.errstate(invalid="ignore", divide="ignore"):
        w = (v * d).sum(axis=2) / (d * d).sum(axis=2)
    return np.nan_to_num(w, nan=0.0), ok


def slot_white_mask(band: np.ndarray, green_band: np.ndarray, red_band: np.ndarray,
                    s: "KillfeedScale" = UNIT_SCALE, whiteness=None) -> np.ndarray:
    """The band's white line art judged against its own plate (PLATE_WHITE_CUT);
    the fixed `icon_white_mask` cut where no plate colour is known. `whiteness`
    is `plate_whiteness`'s result when the caller already holds it."""
    w, ok = whiteness if whiteness is not None else plate_whiteness(band, green_band, red_band, s)
    return np.where(ok[None, :], w >= PLATE_WHITE_CUT, icon_white_mask(band, s))


def _divider_rows(white_band: np.ndarray, wx0: int, wx1: int) -> tuple[int, int] | None:
    n, _lab, st, _ = cv2.connectedComponentsWithStats(white_band.astype(np.uint8), 8)
    rows = [(int(st[i, 1]), int(st[i, 1] + st[i, 3])) for i in range(1, n)
            if st[i, 0] == wx0 and st[i, 0] + st[i, 2] == wx1]
    if not rows:
        return None
    return min(r[0] for r in rows), max(r[1] for r in rows)


def _slot_pieces(icon_band: np.ndarray, rows: tuple[int, int], lo: int, hi: int,
                 s: "KillfeedScale" = UNIT_SCALE):
    r0, r1 = rows
    n, lab, st, _ = cv2.connectedComponentsWithStats(icon_band.astype(np.uint8), 8)
    keep = [i for i in range(1, n)
            if st[i, 4] >= s.area(MIN_COMP_AREA) and st[i, 0] >= lo and st[i, 0] + st[i, 2] <= hi
            and min(int(st[i, 1] + st[i, 3]), r1) > max(int(st[i, 1]), r0)]
    return lab, st, keep


def icon_extent(white_band: np.ndarray, icon_band: np.ndarray, wx0: int, wx1: int,
                lo: int, hi: int, s: "KillfeedScale" = UNIT_SCALE) -> tuple[int, int]:
    """The weapon-slot icon's columns: the element the divider points at.

    `_band_text` divides the names at ONE connected component of the text cut,
    which may be one piece of an icon drawn in several (a ringed ult, a
    dimmed icon broken by a fade) or, over a washed-out plate, a name and the
    icon merged. The descriptor needs the icon alone, so this is a separate box.

    The rule is structural. Take the pieces of `icon_band` (`slot_white_mask`)
    that share a row with the divider piece and lie within lo..hi (after the
    killer's name run, before the victim's). Group them into killfeed
    elements: pieces less than ELEMENT_GAP columns apart are one element. The
    icon is the element with the most ink among those overlapping wx0..wx1.
    The spacing [domain:killfeed/killfeed-element-spacing] keeps out the
    headshot mark [domain:killfeed/headshot-icon], the names, the portraits
    and the killstreak numeral; sharing a row keeps out the next entry's plate
    along the band's edge. The plate-seam fallback (wx0 == wx1) returns the seam.
    """
    if wx1 <= wx0:
        return wx0, wx1
    rows = _divider_rows(white_band, wx0, wx1)
    if rows is None:
        return wx0, wx1
    _lab, st, keep = _slot_pieces(icon_band, rows, lo, hi, s)
    els: list[list] = []
    for i in sorted(keep, key=lambda i: st[i, 0]):
        p0, p1 = int(st[i, 0]), int(st[i, 0] + st[i, 2])
        if els and p0 - els[-1][1] < s.px(ELEMENT_GAP):
            els[-1][1] = max(els[-1][1], p1)
            els[-1][2] += int(st[i, 4])
        else:
            els.append([p0, p1, int(st[i, 4])])
    over = [e for e in els if e[0] < wx1 and e[1] > wx0]
    if not over:
        return wx0, wx1
    best = max(over, key=lambda e: e[2])
    return best[0], best[1]


#: The ring a revive entry draws round its weapon-slot icon
#: [domain:killfeed/revive-ring]: a circle of radius 0.40-0.60 of the band's
#: height, searched round the icon's centre (`ring_fit`). Measured on the
#: player-labelled entries (stored crops): all 22 revives (Not Dead Yet,
#: Resurrection, the KAY/O revive at 4f207c0c4e39 799.5 s) cover the ring's
#: visible arc fully (1.0) with at most 0.021 ink just inside it; of the 115
#: named non-revive entries 114 cover at most 0.80 and one, a box over a
#: portrait (a06f04a0059f 410.0 s), 0.84. RING_COVER_MIN sits between; a full
#: circle filled inside (scenery, g022) is no ring (RING_INNER_MAX, between
#: 0.021 and the 0.49 such blobs show).
RING_R = (0.40, 0.60)
RING_ANGLES = 36
RING_TOL = 1.2
RING_COVER_MIN = 0.9
RING_INNER_MAX = 0.25
#: At or below this cover a ring is absent; between it and RING_COVER_MIN the
#: fit is uncertain and `ringed` stays None.
RING_ABSENT_MAX = 0.8
#: The glyph inside a ring lies within r - RING_STRIP: the middle of the
#: annulus r-4..r-2 that every revive leaves empty.
RING_STRIP = 3.0
#: The annulus (r - 4 .. r - 2, base px) `inner_ink` measures, and how far
#: from the band's middle row the ring's centre is searched.
RING_INNER = (4.0, 2.0)
RING_CY_SEARCH = 3.0
#: An icon is drawn on the killer's plate, so at least this share of the
#: divider's columns hold plate-coloured pixels (PLATE_MIN_PX or more). Measured
#: on 463 parsed entries in 8 sessions: never below 0.56 (1st percentile 0.74);
#: the player-labelled boxes off the entry (crop faults g015, g020, g022, g023)
#: hold 0-0.25. Below it the descriptor refuses (`no_plate`).
PLATE_BEHIND_MIN = 0.5


def ring_fit(icon_band: np.ndarray, cx0: float, height: int,
             usable: np.ndarray | None = None, s: "KillfeedScale" = UNIT_SCALE) -> dict | None:
    """The circle round a weapon-slot icon that the most angles of ink lie on.

    A shape fit, not morphology: centre within half a band height of `cx0`
    and 3 rows of the band's middle, radius RING_R of `height`. Cover counts
    only the angles whose circle point falls inside the band (and `usable`),
    since the band clips the ring's top and bottom. None when too little ink.
    """
    h, w = icon_band.shape
    L, R = int(max(0, cx0 - height)), int(min(w, cx0 + height + 1))
    ys, xs = np.nonzero(icon_band[:, L:R])
    if len(xs) < RING_ANGLES // 3:
        return None
    xs = xs + L
    th = np.radians(np.arange(RING_ANGLES) * 360 / RING_ANGLES + 180 / RING_ANGLES)
    radii = np.arange(RING_R[0] * height, RING_R[1] * height + 0.01, 0.5)
    best = None
    dy = s.px(RING_CY_SEARCH)
    for cy in np.arange(h / 2 - dy, h / 2 + dy + 0.01, 1.0):
        for cx in np.arange(cx0 - height // 2, cx0 + height // 2 + 0.01, 1.0):
            d = np.hypot(xs - cx, ys - cy)
            a = ((np.arctan2(ys - cy, xs - cx) % (2 * np.pi)) / (2 * np.pi) * RING_ANGLES).astype(int) % RING_ANGLES
            on = np.abs(d[None, :] - radii[:, None]) <= s.px(RING_TOL)    # radii x points
            hit = np.zeros((len(radii), RING_ANGLES), bool)
            ri, pi = np.nonzero(on)
            hit[ri, a[pi]] = True
            py = cy + radii[:, None] * np.sin(th)[None, :]
            px = cx + radii[:, None] * np.cos(th)[None, :]
            valid = (py >= 0.5) & (py <= h - 1.5) & (px >= 0) & (px <= w - 1)
            if usable is not None:
                yy = np.clip(py.astype(int), 0, h - 1); xx = np.clip(px.astype(int), 0, w - 1)
                valid &= usable[yy, xx]
            n = valid.sum(axis=1)
            cov = np.where(n >= RING_ANGLES // 3, (hit & valid).sum(axis=1) / np.maximum(n, 1), -1.0)
            # Equal cover breaks toward the circle with more ink on it.
            score = cov + 1e-5 * on.sum(axis=1)
            k = int(np.argmax(score))
            if cov[k] >= 0 and (best is None or score[k] > best["_score"]):
                best = {"cx": float(cx), "cy": float(cy), "r": float(radii[k]),
                        "cover": float(cov[k]), "_score": float(score[k])}
    if best is None:
        return None
    best.pop("_score")
    YY, XX = np.mgrid[0:h, 0:w]
    D = np.hypot(XX - best["cx"], YY - best["cy"])
    inner = (D >= best["r"] - s.px(RING_INNER[0])) & (D < best["r"] - s.px(RING_INNER[1]))
    best["inner_ink"] = float(icon_band[inner].mean()) if inner.any() else 1.0
    return best


def ring_verdict(fit: dict | None) -> tuple[bool | None, str | None]:
    """(ringed, reason): True on a confident ring, False on a confident
    absence, None with the reason otherwise; never a guess."""
    if fit is None:
        return None, "too_little_ink"
    if fit["cover"] >= RING_COVER_MIN:
        return (True, None) if fit["inner_ink"] <= RING_INNER_MAX else (None, "filled_circle")
    if fit["cover"] <= RING_ABSENT_MAX:
        return False, None
    return None, "uncertain_fit"


#: Columns (base px) of the band kept either side of the slot box in `soft`,
#: so a later variant can re-cut the box without a reread.
SOFT_MARGIN = 3


def soft_patch(w: np.ndarray, ok: np.ndarray, c0: int, c1: int) -> dict:
    """A band's plate-relative whiteness over columns c0..c1 at native px:
    clipped to 0..1, quantised to uint8 (`round(255 w)`), zlib-compressed and
    base64-encoded, with the columns whose plate colour was known (packed
    bits) and the patch's ROI column origin. `unpack_soft` inverts it."""
    import base64
    import zlib
    patch = np.ascontiguousarray(np.round(np.clip(w[:, c0:c1], 0.0, 1.0) * 255).astype(np.uint8))
    return {"x0": int(c0), "shape": [int(patch.shape[0]), int(patch.shape[1])],
            "w": base64.b64encode(zlib.compress(patch.tobytes(), 9)).decode("ascii"),
            "plate_known": np.packbits(ok[c0:c1].astype(bool)).tobytes().hex()}


def unpack_soft(soft: dict) -> tuple[np.ndarray, np.ndarray]:
    """A stored `soft` back to (whiteness uint8 h x w, plate-known columns)."""
    import base64
    import zlib
    h, w = soft["shape"]
    patch = np.frombuffer(zlib.decompress(base64.b64decode(soft["w"])), np.uint8).reshape(h, w)
    known = np.unpackbits(np.frombuffer(bytes.fromhex(soft["plate_known"]), np.uint8))[:w].astype(bool)
    return patch, known


def _centroid(w: np.ndarray, piece: np.ndarray) -> list[float] | None:
    """The whiteness-weighted centroid (x, y; band px) of the icon's pieces:
    the icon's own sub-pixel position, which is fractional horizontally and
    whole vertically [domain:killfeed/subpixel-placement]."""
    if not piece.any():
        return None
    wt = np.where(piece, np.clip(w, 0.0, 1.0), 0.0)
    tot = float(wt.sum())
    if tot <= 0:
        return None
    ys, xs = np.mgrid[0:w.shape[0], 0:w.shape[1]]
    return [round(float((wt * xs).sum() / tot), 3), round(float((wt * ys).sum() / tot), 3)]


#: The 0.6.0 fields of a row refused before its slot pieces are cut.
NO_SOFT = {"ring_stripped": None, "soft": None, "centroid": None, "slot_geom": None}


def weapon_icon_observations(frame: np.ndarray, roi: Roi, width: int, height: int,
                             views: "list[EntryView]", *,
                             scale: "KillfeedScale | None" = None) -> list[dict]:
    """Each entry's weapon-slot descriptor: the packed grid and aspect, never a name.

    Naming the icon is `adjudication.weapon`'s; a consumer binds these rows to an
    entry by slot, time and divider column and asks the owner from storage.
    The descriptor is cut from the icon's pieces in ix0..ix1 (`icon_extent`)
    on the plate-relative mask (`slot_white_mask`); wx0..wx1 stays the divider
    piece, the column and width consumers bind by. A confident ring
    (`ring_fit`, `ring_verdict`) is stripped and published as `ringed`, a
    witness of a revive entry [domain:killfeed/revive-ring] for the entry-type
    owner; the grid is then the glyph inside it.

    Beside the grid each described row keeps what a later descriptor needs
    without rereading the video: `soft`, the plate-relative whiteness of the
    slot box at native px (`soft_patch`, SOFT_MARGIN columns either side);
    `slot_geom`, the band height, the box and the measured plate height in
    base px with the capture's scale; `ring_stripped`; and `centroid`, the
    icon's sub-pixel position (ROI column, band row). A row refused before its
    pieces are cut carries these fields as null.

    The slot is cut from the rows the entry's names place it at
    (`band_shift`, the portrait reader's rule): a wash that paints both plate
    colours down from the ROI's top starts the plate run at row 0, and the
    PITCH split then cuts the entry 13 rows high (4f207c0c4e39 460.0 s, the
    rifle's lower half). `y0..y1` stay the view's rows, which consumers bind
    by; `band_shift` says how far the cut moved. The move stands only when
    the moved band holds at least the view band's plate rows (`plate_height`):
    a portrait's art and the headshot mark can pass for two agreeing names.

    The icon sits on the killer's plate, between the two names. A divider
    wholly outside the span of the band's plate runs (`_plate_runs`) is
    portrait art or scenery, and refuses as `off_plate_run`: the killer's
    portrait and its agent badge left of an unread killer name
    (4f207c0c4e39 892.5 s), or the wash's red art under a band the split made
    from an entry's lower half (460.0 s, slot 1).
    """
    s = scale or KillfeedScale.for_capture(width, height)
    x0, y0, x1, y1 = roi.pixels(width, height)
    out = []
    for v in views:
        if v.wx1 <= v.wx0 or v.y1 <= v.y0:
            continue
        band = frame[y0 + v.y0:y0 + v.y1, x0:x1]
        green, red, white = _plate_masks(band, np.ones(band.shape[:2], bool))
        dy = (band_shift(white > 0, v.killer_run, v.victim_run, s)
              if v.killer_run and v.victim_run else 0)
        if dy:
            bh = v.y1 - v.y0
            ry0 = min(max(0, v.y0 + dy), max(0, (y1 - y0) - bh))
            moved = frame[y0 + ry0:y0 + ry0 + bh, x0:x1]
            mg, mr, mw = _plate_masks(moved, np.ones(moved.shape[:2], bool))
            # The plate checks the names: a move that loses plate rows left
            # the entry, and the runs were not names (5822b6646448 1417.0 s,
            # slot 2: portrait art and the headshot mark agreed 10 rows high).
            if plate_height(mg, mr) >= plate_height(green, red):
                dy = ry0 - v.y0
                band, green, red, white = moved, mg, mr, mw
            else:
                dy = 0
        crop = band[:, v.wx0:v.wx1]
        cut = icon_grid(icon_white_mask(crop, s), s)
        row = {"slot": v.slot, "y0": int(v.y0), "y1": int(v.y1), "wx0": int(v.wx0),
               "wx1": int(v.wx1), "verdict": v.verdict, "band_shift": int(dy)}
        # A divider piece too small to be an icon stays refused: its
        # neighbours are a portrait edge or a name, never the missing icon
        # (a06f04a0059f 1969.0 s, a portrait's edge, gained a grid otherwise).
        if cut is None:
            out.append({**row, "ix0": int(v.wx0), "ix1": int(v.wx1), "grid": None,
                        "aspect": None, "reason": "no_icon", "ringed": None,
                        "ring_reason": "no_icon", "ring": None, **NO_SOFT})
            continue
        behind = ((green | red)[:, v.wx0:v.wx1].sum(axis=0) >= s.px(PLATE_MIN_PX)).mean()
        if behind < PLATE_BEHIND_MIN:
            out.append({**row, "ix0": int(v.wx0), "ix1": int(v.wx1), "grid": None,
                        "aspect": None, "reason": "no_plate", "ringed": None,
                        "ring_reason": "no_plate", "ring": None, **NO_SOFT})
            continue
        runs = _plate_runs(green, red, s)
        if not runs or v.wx1 <= runs[0][1] or v.wx0 >= runs[-1][2]:
            out.append({**row, "ix0": int(v.wx0), "ix1": int(v.wx1), "grid": None,
                        "aspect": None, "reason": "off_plate_run", "ringed": None,
                        "ring_reason": "off_plate_run", "ring": None, **NO_SOFT})
            continue
        w, ok = plate_whiteness(band, green, red, s)
        icon = slot_white_mask(band, green, red, s, whiteness=(w, ok))
        ix0, ix1 = (v.ix0, v.ix1) if v.ix1 > v.ix0 else (v.wx0, v.wx1)
        rows = _divider_rows(white > 0, v.wx0, v.wx1)
        piece = np.zeros_like(icon)
        if rows is not None:
            lab, _st, keep = _slot_pieces(icon, rows, ix0, ix1, s)
            piece = np.isin(lab, keep)
        fit = ring_fit(icon, (ix0 + ix1) / 2, v.y1 - v.y0, s=s)
        ringed, why = ring_verdict(fit)
        stripped = False
        if ringed:
            YY, XX = np.mgrid[0:icon.shape[0], 0:icon.shape[1]]
            glyph = icon & (np.hypot(XX - fit["cx"], YY - fit["cy"]) < fit["r"] - s.px(RING_STRIP))
            if glyph.any():
                piece = glyph
                stripped = True
        if piece.any():
            xs = np.nonzero(piece.any(axis=0))[0]
            ix0, ix1 = int(xs[0]), int(xs[-1]) + 1
            cut = icon_grid(piece[:, ix0:ix1], s)
        else:
            ix0, ix1 = v.wx0, v.wx1
        row.update({"ix0": int(ix0), "ix1": int(ix1), "ringed": ringed, "ring_reason": why,
                    "ring": ({k: round(val, 3) for k, val in fit.items()} if fit else None)})
        m = s.n(SOFT_MARGIN)
        extra = {"ring_stripped": stripped,
                 "soft": soft_patch(w, ok, max(0, ix0 - m), min(band.shape[1], ix1 + m)),
                 "centroid": _centroid(w, piece),
                 "slot_geom": {"band_h": round((v.y1 - v.y0) / s.scale, 3),
                               "box": [round(c / s.scale, 3) for c in (ix0, v.y0 + dy, ix1, v.y1 + dy)],
                               "plate_h": round(plate_height(green, red) / s.scale, 3),
                               "scale": s.provenance()}}
        if cut is None:
            out.append({**row, "grid": None, "aspect": None, "reason": "no_icon", **extra})
        else:
            out.append({**row, "grid": np.packbits(cut[0].astype(bool)).tobytes().hex(),
                        "aspect": round(float(cut[1]), 4), "reason": None, **extra})
    return out


# --------------------------------------------------------------------------- names
# 0.1.0 (2026-09-26): each entry role's whole player name, cut between its
# portrait and the weapon icon, stored as the band's whiteness (lossless
# uint8, zlib) for `adjudication.killfeed_names` to compare. Measured in
# `prototypes/killfeed_name_continuity.py`.
# 0.2.0 (2026-09-28): more bands read (`_join_split_runs`); see the portrait stamp.
# 0.3.0 (2026-10-02): ability entries refused as `no_icon` are read; see the
# portrait stamp.
KILLFEED_NAME_VERSION = "killfeed-name-0.3.0"

#: Names measured at most 14 px tall, the headshot crosshair 16-17 px.
NAME_MAX_TEXT_H = 15
#: A group is text when this share of its ink lies on the text line; a
#: portrait's white art runs above and below it.
NAME_TEXT_SHARE = 0.8
#: Narrower than this is portrait art at the victim's bound, not a name; the
#: shortest names seen measure about 29 px.
NAME_MIN_W = 12
#: Words of one name sit this close; `NAME_GAP` splits "A Whif and A Lot" into
#: five groups, and the last word alone merged it with "Whiff A Lot".
NAME_WORD_GAP = 12
#: Base px: a text row holds at least NAME_ROW_MIN_PX white pixels; the text
#: line is cut NAME_LINE_PAD rows above and below the killer's text rows; a
#: group is at least NAME_GROUP_MIN_W wide and ends NAME_EDGE_CLEAR before the
#: cut's far bound.
NAME_ROW_MIN_PX = 2
NAME_LINE_PAD = (2, 4)
NAME_GROUP_MIN_W = 3
NAME_EDGE_CLEAR = 2


def _name_groups(cols: np.ndarray, s: "KillfeedScale" = UNIT_SCALE) -> list[tuple[int, int]]:
    xs = np.where(cols)[0]
    if xs.size == 0:
        return []
    out, start = [], xs[0]
    for a, b in zip(xs[:-1], xs[1:]):
        if b - a > s.px(NAME_GAP):
            out.append((int(start), int(a) + 1))
            start = b
    out.append((int(start), int(xs[-1]) + 1))
    return out


def _name_text_rows(white: np.ndarray, a: int, z: int,
                    s: "KillfeedScale" = UNIT_SCALE) -> tuple[int, int] | None:
    """The rows the killer's name occupies: the band's text line."""
    rows = np.where((white[:, max(a, 0):max(z, 0)] > 0).sum(axis=1) >= s.px(NAME_ROW_MIN_PX))[0]
    return (int(rows[0]), int(rows[-1]) + 1) if rows.size else None


def _name_cut(white: np.ndarray, a: int, z: int, rows,
              s: "KillfeedScale" = UNIT_SCALE) -> tuple[int, int] | None:
    """The name's columns inside [a, z), band-relative: the last text group and
    the words before it (`NAME_WORD_GAP`), or None."""
    a, z = max(a, 0), max(z, 0)
    full = white[:, a:z] > 0
    line = np.zeros_like(full)
    r0, r1 = max(rows[0] - s.n(NAME_LINE_PAD[0]), 0), rows[1] + s.n(NAME_LINE_PAD[1])
    line[r0:r1] = full[r0:r1]
    keep = [g for g in _name_groups(line.any(axis=0), s)
            if g[1] - g[0] >= s.px(NAME_GROUP_MIN_W) and g[1] <= (z - a) - s.px(NAME_EDGE_CLEAR)
            and np.ptp(np.where(line[:, g[0]:g[1]].any(axis=1))[0]) < s.px(NAME_MAX_TEXT_H)
            and line[:, g[0]:g[1]].sum() >= NAME_TEXT_SHARE * max(1, full[:, g[0]:g[1]].sum())]
    if not keep:
        return None
    g0, g1 = keep[-1]
    for h0, h1 in reversed(keep[:-1]):
        if g0 - h1 > s.px(NAME_WORD_GAP):
            break
        g0 = h0
    return (a + g0, a + g1) if g1 - g0 >= s.px(NAME_MIN_W) else None


def name_observations(frame: np.ndarray, roi: Roi, width: int, height: int,
                      views: "list[EntryView]", portraits: list[dict],
                      mask: np.ndarray | None = None, *,
                      scale: "KillfeedScale | None" = None) -> list[dict]:
    """Each entry role's player-name crop: a descriptor, never a player or agent.

    The killer's name runs from its portrait to the weapon icon, the victim's
    from the icon to its portrait (`portraits`, this frame's
    `portrait_observations`, bounds it). Both are cut on the killer name's text
    line and keep the last text group with the words before it, so a headshot
    or wallbang mark is dropped. The crop is the band's whiteness (the minimum
    over BGR) at full band height, so a consumer can remove the plate behind
    it. `me` marks the player's own role, which prints "Me".
    """
    import base64
    import zlib
    s = scale or KillfeedScale.for_capture(width, height)
    x0, y0, x1, y1 = roi.pixels(width, height)
    crop = frame[y0:y1, x0:x1]
    if mask is None:
        mask = np.ones(crop.shape[:2], dtype=bool)
    white = None
    bounds = {(p["slot"], p["role"]): p.get("x0") for p in portraits if "x0" in p}
    out = []
    for v in views:
        if v.wx1 <= v.wx0:
            continue
        base = {"slot": v.slot, "y0": int(v.y0), "y1": int(v.y1)}
        me = {"killer": v.verdict == "kill", "victim": v.verdict == "death"}
        if not v.killer_run:
            out.extend({**base, "role": r, "me": me[r], "gray": None,
                        "reason": "no_killer_name_run"} for r in ("killer", "victim"))
            continue
        if white is None:
            white = _plate_masks(crop, mask)[2]
        band = white[v.y0:v.y1]
        rows = _name_text_rows(band, *v.killer_run, s)
        for role in ("killer", "victim"):
            row = {**base, "role": role, "me": me[role]}
            if rows is None:
                out.append({**row, "gray": None, "reason": "no_text_line"})
                continue
            if role == "killer":
                cut = _name_cut(band, 0, v.wx0 - 1, rows, s)
            else:
                z = bounds.get((v.slot, "victim"))
                cut = _name_cut(band, v.wx1 + 1, band.shape[1] if z is None else z, rows, s)
            if cut is None:
                out.append({**row, "gray": None, "reason": "no_name_text"})
                continue
            gray = np.ascontiguousarray(crop[v.y0:v.y1, cut[0]:cut[1]].min(axis=2))
            out.append({**row, "x0": int(cut[0]), "x1": int(cut[1]),
                        "shape": [int(gray.shape[0]), int(gray.shape[1])],
                        "gray": base64.b64encode(zlib.compress(gray.tobytes(), 6)).decode("ascii"),
                        "reason": None})
    return out


def unpack_name_gray(row: dict) -> np.ndarray | None:
    """A stored name row's `gray` back to the uint8 whiteness it was cut from."""
    import base64
    import zlib
    if not row.get("gray"):
        return None
    h, w = row["shape"]
    return np.frombuffer(zlib.decompress(base64.b64decode(row["gray"])), np.uint8).reshape(h, w)


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
        self.mask_prefix = mask.astype(np.int32).cumsum(axis=1) if mask is not None else None
        self.roi = killfeed_roi(profile)
        self.name = "killfeed_portrait"
        self.hz = hz
        self.spans = spans
        # Every pixel it reads is inside the `killfeed` ROI, so a pass of
        # only such readers can be fed from the ROI crop cache
        # (`passes.run_cached`); a trial from the cache reproduced its rows.
        self.cache_set = "killfeed"
        # What fed it: "video", or the cache's version (set by the runner).
        self.frames_from = "video"
        self.rows: list[dict] = []
        self.badges: list[dict] = []
        self.weapons: list[dict] = []
        self.names: list[dict] = []
        self.frames_offered = 0

    def feed(self, smp) -> None:
        self.frames_offered += 1
        if self.roi is None:
            return
        # One scale for the capture, handed to every reader of this frame.
        s = KillfeedScale.for_capture(self.w, self.h)
        # The named steps (`usage.step`) time this feed for `reticle usage`.
        with usage_step("entries"):
            views = analyse_killfeed(
                smp.frame, self.roi, self.w, self.h, self.mask,
                self.profile.name, mask_prefix=self.mask_prefix, scale=s)
        # The player's own deaths: does the entry carry the second-life badge?
        # Stored for every such entry, badge or not, so a consumer can tell a
        # Run It Back death from a death, and both from an entry never read.
        x0, y0, x1, y1 = self.roi.pixels(self.w, self.h)
        with usage_step("second_life"):
            for view in views:
                if (view.verdict != "death" or not view.victim_run
                        or view.y1 - view.y0 < s.px(SECOND_LIFE_MIN_BAND_H)):
                    continue
                band = smp.frame[y0 + view.y0:y0 + view.y1, x0:x1]
                has_badge, metrics = detect_second_life_badge(band, view.victim_run[0], s=s)
                self.badges.append({"frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms),
                                    "slot": view.slot, "y0": int(view.y0), "y1": int(view.y1),
                                    "victim_x": int(view.victim_run[0]),
                                    "has_badge": bool(has_badge), **metrics})
        with usage_step("weapon"):
            for row in weapon_icon_observations(smp.frame, self.roi, self.w, self.h, views,
                                                scale=s):
                self.weapons.append({"frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms),
                                     **row})
        with usage_step("portraits"):
            portraits = portrait_observations(
                smp.frame, self.roi, self.w, self.h, views=views,
                mask=self.mask, profile_name=self.profile.name, scale=s)
            for observation in portraits:
                self.rows.append({
                    "frame_idx": int(smp.frame_idx),
                    "t_ms": float(smp.t_ms),
                    **observation,
                })
        with usage_step("names"):
            for row in name_observations(smp.frame, self.roi, self.w, self.h, views,
                                         portraits, mask=self.mask, scale=s):
                self.names.append({"frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms),
                                   **row})

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
            "frames_from": self.frames_from,
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
        s = KillfeedScale.for_capture(self.w, self.h)
        coverage = {**common, "kind": "coverage", "frames_offered": self.frames_offered,
                    "frames_from": self.frames_from,
                    "observations": len(self.weapons),
                    "described": len(self.weapons) - sum(refused.values()),
                    "refused_reasons": dict(sorted(refused.items())),
                    "scale": s.provenance(),
                    "scale_check": scale_check(
                        [r["slot_geom"]["plate_h"] * s.scale for r in self.weapons
                         if r.get("slot_geom")], s)}
        return [coverage] + [{**common, "kind": "weapon_icon_observation", **r}
                             for r in self.weapons]

    def name_events(self, session_id: str) -> list[dict]:
        """The `killfeed_name` stream: a coverage row with its refusals, then
        one name crop per entry role per frame, keyed like the portraits
        (`sid:frame:slot:role`). Its own stamp, so the cut can change without
        restating the portraits."""
        common = {"session_id": session_id, "source": "killfeed",
                  "killfeed_name_version": KILLFEED_NAME_VERSION}
        refused = Counter(r["reason"] for r in self.names if r["reason"])
        coverage = {**common, "kind": "coverage", "frames_offered": self.frames_offered,
                    "frames_from": self.frames_from,
                    "observations": len(self.names),
                    "described": len(self.names) - sum(refused.values()),
                    "refused_reasons": dict(sorted(refused.items()))}
        return [coverage] + [
            {**common, "kind": "name_observation",
             "observation_key": f"{session_id}:{r['frame_idx']}:{r['slot']}:{r['role']}", **r}
            for r in self.names]


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
        entry_killer_ally=tuple(v.killer_ally for v in views),
        kill_wxs=tuple(_trusted_wx(v) for v in kills),
        death_wxs=tuple(_trusted_wx(v) for v in deaths),
        unattributed=sum(1 for v in views if v.verdict in ("occluded", "tie")),
        unparsed=sum(1 for v in views if v.verdict == "unparsed"),
        unparsed_reason=next((v.reason for v in views
                              if v.verdict == "unparsed" and v.reason), None),
        scale=KillfeedScale.for_capture(width, height).scale,
    )
