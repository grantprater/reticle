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
2 Hz, over eight sessions:

    b3b9defb6fd7    14 / 18   vs  14 / 18     exact
    bdfdcf009dba    17 / 13   vs  17 / 14     +0 / -1
    223d636bf8d2    21 / 15   vs  25 / 15     -4 / +0
    9acf02f98283    11 / 12   vs  13 / 16     -2 / -4
    b7d24102a6f6    10 / 12   vs  10 / 12     exact
    75a55a296d3b     5 /  5   vs   5 /  5     exact
    59c70f1ef720    15 / 14   vs  15 / 16     +0 / -2
    bfad2778a372    19 / 13   vs  19 / 15     +0 / -2

15 events off across 229. ME_MATCH_MIN was swept on the first five; the last
three were never used to tune anything. Per-band precision was checked by eye:
32 of 32 hand-inspected detections were correct.

The error is one-directional -- these counts under-report and do not invent
events. It is also lopsided by side: kills are exact on seven of nine sessions,
deaths short on six. Two causes are now confirmed rather than suspected, both
found by hunting the three missing deaths in c40d950031bb, a 16-minute match
with only two kills in it:

* **An entry with no weapon icon.** At 13:14, "HungryHamster5 (X) Me" -- the
  weapon slot holds a small crossed-circle mark, not a gun. ICON_MIN_AREA=150
  rejects it, so the killer/victim split never happens and the entry goes
  unattributed. Lowering the floor to 95 does find the icon, but the victim run
  then measures 26 px instead of 18 and "Me" still only scores 0.26, so
  something else is inside that run. Not fixed.
* **Clipping at the ROI's top edge.** At 15:12, "pan (rifle) Me" scores 0.41
  against a 0.65 bar, on a band reported at y0-37: the newest entry is still
  sliding into place and its glyph tops are cut off by the ROI boundary.
  Reading 24 rows above the ROI was tried and rejected -- it recovers nothing,
  and it *loses* the 15:12 bands altogether, because the taller crop changes
  what the plate row-profile resolves. The ROI itself may need to move, which
  costs an EXTRACTOR_VERSION bump and a re-ingest of every session.
* **A washed-out entry.** ff636d173b07 at 11:44, "Me (rifle) MommysMethpipe",
  a plain kill scoring 0.00. The killfeed is drawn over the scene, and against a
  bright background the *plate* clears TEXT_V_MIN and fuses with the glyphs:
  band median value 215, white mask filling 20.4% of the band with a largest
  component of 1285 px, against 6-10% and ~20 glyph-sized components on a
  healthy band. Thresholding each band by Otsu on its own value channel was
  tried and does not fix it -- with a dark portrait at one end and a bright
  plate at the other, Otsu splits dark from bright rather than plate from text.
  Something local, or a colour distance from the plate rather than a brightness
  cut, is probably what this needs.

Every attempted fix above was reverted rather than left half-working. What they
establish is the shape of the problem: the gap is not one bug but several, each
worth a couple of events, and the three found so far are independent of each
other. Precision is not in question -- c40d950031bb holds only two real kills
and reports exactly two.

* Entry formats this parser does not model. It requires a weapon icon dividing
  two names, which a normal kill always has. A death with no killer -- spike
  detonation, fall damage -- and the resurrection entries (Sage, Clove) are laid
  out differently, and a death is far likelier than a kill to take one of those
  forms. That asymmetry matches the one in the numbers.
* Entries never resolved into a band at all. Scanning an 11-minute stretch of
  bfad2778a372 with two known-missing deaths turned up no near misses on the
  victim side: the width gate correctly rejected short names ("Raze", 30-32 px)
  at 0.00 and every real "Me" scored 18 px. So the missing deaths are not
  marginal matches, they are absent.

Thin tracks -- entries seen in 4 or fewer of a possible ~12 frames -- are the
leading indicator, and an observation count *above* ~12 means the opposite: two
entries merged into one track. 30 of 214 are thin.

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
    entry_ys: tuple[int, ...] = ()
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


def _entry_bands(plate: np.ndarray, usable: np.ndarray | None = None) -> list[tuple[int, int]]:
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
    # Measure plate density over the pixels that are actually visible. A toggled
    # overlay blanks part of a row, and dividing by the full ROI width instead
    # would drag that row under PLATE_ROW_FRAC and dissolve the band -- so an
    # entry sitting behind the shooting-error box was not reported occluded, it
    # simply never existed. Two of six on-screen entries were being lost that way.
    if usable is None:
        prof = plate.mean(axis=1)
    else:
        seen = usable.sum(axis=1)
        prof = np.divide(plate.sum(axis=1), seen, out=np.zeros(plate.shape[0]),
                         where=seen > 0)
    on = prof > PLATE_ROW_FRAC
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
    """Width of this side's name run, and how well "Me" matches inside it.

    Matching is confined to the name run rather than swept across the whole
    region, so a long name cannot contribute a lucky substring: its run is far
    too wide to be "Me" and is rejected on width before any matching happens.
    """
    if tpl_info is None:
        return 0, 0.0
    tpl, t0, t1 = tpl_info
    run = name_run(region, side)
    if run is None:
        return 0, 0.0
    width = run[1] - run[0] + 1
    if not (ME_W[0] <= width <= ME_W[1]):
        return width, 0.0
    # Widen the run by the patch's own padding so the match can line up.
    lo = max(0, run[0] - t0)
    hi = min(region.shape[1], run[1] + 1 + (tpl.shape[1] - 1 - t1))
    sub = region[:, lo:hi]
    if sub.shape[0] < tpl.shape[0] or sub.shape[1] < tpl.shape[1]:
        return width, 0.0
    return width, float(cv2.matchTemplate(sub, tpl, cv2.TM_CCOEFF_NORMED).max())


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
    wep = max(icons, key=lambda i: st[i, 4])
    wx0, wx1 = int(st[wep, 0]), int(st[wep, 0] + st[wep, 2])
    if usable is not None:
        for lo, hi in ((0, wx0), (wx1, usable.shape[1])):
            if hi - lo <= 0:
                continue
            if (~usable[:, lo:hi]).mean() > OCCLUDED_NAME_FRAC:
                return "occluded"

    cand = [
        i for i in idx
        if GLYPH_W[0] <= st[i, 2] <= GLYPH_W[1] and GLYPH_H[0] <= st[i, 3] <= GLYPH_H[1]
    ]
    if not cand:
        return None
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
    for (a, z) in _entry_bands(green | red, mask):
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
        unattributed=sum(1 for v in views if v.verdict in ("occluded", "tie")),
    )
