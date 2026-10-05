"""Stage 02: deterministic HUD extraction (design doc SS3).

The design doc is explicit about the rule this module exists to honour:

    The HUD is structured data rendered as pixels -- parsed against templated
    regions, never inferred by a model.

So there is no OCR engine here and no learned component. Valorant renders the
HUD's digits in DIN Next at a fixed size for a given resolution
[domain:hud/digit-fonts], which makes matching against the font itself both
exact and free.

The scoreline reads soft. Its plates are semi-transparent, so each pixel's
white-ink coverage against its local plate (`ink_cover`) is what the game's
glyphs lay down; the font's cells (`GlyphCells`), drawn 8x from the game's
font file at the widget's size and pitch and shrunk with `INTER_AREA` at 4x4
sub-pixel phases, are compared with it at the places the centred TextBlocks
put their digits (`SCORE_PENS`, `CLOCK_PENS`). Each cell is decided once,
digit or empty, and which digit (`slot_verdict`); nothing is cut before
that decision. On the 21 Riot-recorded matches it reads
[metric:soft_digits/scoreline-final-all#new_reads=165216] scores with
[metric:soft_digits/scoreline-final-all#new_full_off=0] full reads off Riot's
round scores, and [metric:soft_digits/scoreline-final-all#new_clock=67684]
clocks.

The bottom HUD reads the same way (`read_subfields`): health, shield,
magazine and reserve each have measured pen places per digit count
(`BOTTOM_PENS`), the layout explaining the most ink wins, and a field drawn
at a lower tint (low-health pink) is decided again at that tint. Every
refusal names its reason (`BottomRead.*_reason`). On the same matches health
reads [metric:soft_digits/bottom-all#hp_new_reads=75288] frames, shield
[metric:soft_digits/bottom-all#shield_new_reads=56292], magazine
[metric:soft_digits/bottom-all#ammo_mag_new_reads=39823] and reserve
[metric:soft_digits/bottom-all#ammo_reserve_new_reads=39474]. The mined
binary set (`Templates.load`, `reticle glyphs`) remains for the scoreboard
and the combat report.

What this reads: the top-centre scoreline (the round clock and both team
scores) and the bottom HUD (health, shield, magazine, reserve).

Owns [owns:scoreline].
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy.spatial.distance import cdist

import cv2

from .census import Census
from .profiles import Profile, Roi, template_key

# Normalised glyph grid. Every blob is scaled into this box before matching, so
# the score digits (h~20px at 1080p) and the larger clock digits (h~26px) share
# one template set.
GLYPH_H, GLYPH_W = 20, 12

# Glyph geometry filters, in ROI pixels at 1080p. These reject the specks that
# bright backgrounds punch through the threshold, and the occasional weapon or
# VFX blob that overlaps the scoreline.
MIN_H, MAX_H = 12, 32
MIN_AREA, MAX_W = 25, 34

# A component too big to be a glyph is not merely ignorable. Bright bloom behind
# the HUD can pass the threshold and *merge* with a digit -- observed at 1080p
# as a 12x51 mass fusing with the trailing "1" of a score of 11, leaving a
# lone "1" that reads as a perfectly confident 1. Any oversize mass overlapping
# a field means that field is occluded, and the honest answer is None.
BLOCKER_MIN_AREA = 150

# Digits inside one HUD field are rendered at a single size, so a glyph whose
# height disagrees with its siblings is not a digit -- it is debris. This
# matters because a blocker does not always swallow a digit cleanly: observed at
# 1080p as a mass absorbing the leading "0" of a 0:11 clock but leaving a 14x13
# fragment behind, which passed the height filter, matched "1" and turned the
# read into 1:11. Counting glyphs alone cannot catch that; comparing them to
# each other can.
SIBLING_MIN_RATIO, SIBLING_MAX_RATIO = 0.70, 1.40

# Two adjacent digits can fuse into a single component -- observed at 1080p as a
# 31x21 blob where "18" should be, which normalises into the glyph grid and
# matches "1" at 0.86 confidence with a healthy margin. Neither the confidence
# gate nor the margin gate sees anything wrong, because the blob genuinely does
# resemble one digit once squashed. Its shape gives it away: a single digit
# never gets close to as wide as it is tall (p99 of glyphs in cleanly-read
# frames is 0.68), while a fused pair lands above 1.1.
MAX_ASPECT = 0.75

# Luma above which a pixel is treated as glyph by the readers still on binary
# sets (the bottom HUD, the scoreboard, the combat report).
THRESHOLD = 190

# The scoreline reads no cut luma. Its plates are
# semi-transparent [domain:minimap/transparency]: at the screen's top edge sky
# and pale walls lift a score plate past 190, and the cut then fused scenery
# and digits into full-height masses (266x59 px, area 10316) refused as
# `occluded` over legible scores, for 4.5-43 s before a round's end on 11 of
# 439 Riot-recorded rounds
# [metric:unread_reset_causes/riot-21-occluded-recheck#occluded_samples_graphic_absent=161].
# The digits are near-opaque white (cores at luma 249-255 over any plate), so
# a pixel of luma I over a plate of luma b shows ink coverage
# (I - b) / (255 - b) (`ink_cover`), the quantity the font's cells hold. `b`
# is the plate's own local background: a grey opening with a square wider
# than a stroke and narrower than the plate's scenery, which removes the
# digits and keeps both bright scenery and the dark chrome lines.
SCORE_BG_KERNEL = 9
#: The ROI height (1080p) SCORE_BG_KERNEL is measured at; it scales with it.
SCORE_BG_AT_H = 59
#: A plate within this much luma of white cannot show a white digit: a field
#: whose digit rows hold such a plate refuses `low_contrast`, since a digit
#: there could stand unseen beside the ones read.
SCORE_CONTRAST_MIN = 16.0
#: The score digits' rows, as fractions of the ROI height.
SCORE_BAND_Y = (0.25, 0.80)

TEMPLATE_DIR = Path(__file__).parent / "templates"


@dataclass(frozen=True)
class Glyph:
    """One connected component that passed the geometry filter."""

    x: int
    y: int
    w: int
    h: int
    bitmap: np.ndarray  # GLYPH_H x GLYPH_W, float32 in 0..1

    @property
    def cx(self) -> float:
        return self.x + self.w / 2.0


def normalise(patch: np.ndarray) -> np.ndarray:
    """Scale a binary glyph patch into the fixed grid.

    The INTER_AREA shrink is re-binarised (> 0) before the binary template
    match: binarising before matching, against the rule to read pixels as
    samples of a smooth image. Inherited debt for the readers still on
    binary sets (the bottom HUD, the scoreboard, the combat report); the
    scoreline reads soft cells (`GlyphCells`)."""
    resized = cv2.resize(
        patch.astype(np.uint8), (GLYPH_W, GLYPH_H), interpolation=cv2.INTER_AREA
    )
    return (resized > 0).astype(np.float32)


def _raw_components(
    gray: np.ndarray, threshold: int = THRESHOLD
) -> tuple[np.ndarray, list[tuple[int, int, int, int, int]]]:
    """Threshold and return every connected component, unfiltered.

    The scoreline and the bottom HUD render digits at different sizes, so they
    cannot share one absolute geometry filter -- the bottom HUD's health digits
    (h~33 at 1080p) are taller than the scoreline's tallest. Each caller applies
    its own bands to this raw list.
    """
    _, binary = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
    count, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    out = []
    for i in range(1, count):
        x, y, w, h, area = (int(v) for v in stats[i])
        out.append((x, y, w, h, area))
    return binary, out


def _components(
    gray: np.ndarray, threshold: int = THRESHOLD, x0: int = 0, width: int | None = None
) -> tuple[list[Glyph], list[tuple[float, float]]]:
    """Split thresholded components into glyphs and occlusion blockers.

    Returns (glyphs sorted left to right, blocker x-spans as ROI-width
    fractions). Deliberately geometric rather than clever: anything outside the
    height, width and area envelope of a HUD digit is not a glyph. The colon in
    the clock fails the height test and is dropped too -- field assignment uses
    x position, not the colon, so nothing depends on it.

    `gray` may be a column slice of the ROI starting at `x0`, of an ROI
    `width` wide; positions come back in the ROI's frame.
    """
    binary, raw = _raw_components(gray, threshold)
    return _split(binary, raw, gray.shape[1] if width is None else width, x0)


def _split(binary: np.ndarray, raw: list[tuple[int, int, int, int, int]],
           width: int, x0: int = 0, blocker_min_area: int = BLOCKER_MIN_AREA,
           max_h: int = MAX_H) -> tuple[list[Glyph], list[tuple[float, float]]]:
    """`_components`' geometry rule over one binary mask and its components,
    the mask's column 0 standing at ROI column `x0` of an ROI `width` wide."""
    width = max(1, width)
    glyphs: list[Glyph] = []
    blockers: list[tuple[float, float]] = []
    for x, y, w, h, area in raw:
        oversize = (h > max_h or w > MAX_W) and area >= blocker_min_area
        fused = h >= MIN_H and w / max(1, h) > MAX_ASPECT
        if oversize or fused:
            # Either way a digit is missing from this field -- swallowed by the
            # mass, or fused into the blob. Mark the span so the field refuses
            # rather than reporting whatever the survivors happen to spell.
            blockers.append(((x + x0) / width, (x + x0 + w) / width))
            continue
        if not (MIN_H <= h <= max_h) or w > MAX_W or area < MIN_AREA:
            continue
        glyphs.append(Glyph(x=x + x0, y=y, w=w, h=h,
                            bitmap=normalise(binary[y : y + h, x : x + w])))

    glyphs.sort(key=lambda g: g.x)
    return glyphs, blockers


def segment_glyphs(gray: np.ndarray, threshold: int = THRESHOLD) -> list[Glyph]:
    """Glyph-shaped components in a grayscale ROI, left to right."""
    return _components(gray, threshold)[0]


def ink_cover(gray: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """White-ink coverage of every pixel against its local plate, and the
    plate's room below white (255 - plate luma), both float32.

    The plate is the grey opening of `gray` by a square of SCORE_BG_KERNEL px
    at a SCORE_BG_AT_H px tall ROI, scaled with the ROI's height; the
    coverage divides by at least SCORE_CONTRAST_MIN, so a near-white plate
    does not turn noise into ink."""
    k = max(3, int(round(SCORE_BG_KERNEL * gray.shape[0] / SCORE_BG_AT_H)) | 1)
    square = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
    plate = cv2.morphologyEx(gray, cv2.MORPH_OPEN, square).astype(np.float32)
    room = 255.0 - plate
    cover = (gray.astype(np.float32) - plate) / np.maximum(room, SCORE_CONTRAST_MIN)
    return np.clip(cover, 0.0, 1.0), room


class Templates:
    """Labelled glyph bitmaps, and nearest-template matching against them."""

    def __init__(self, labels: list[str], bitmaps: np.ndarray):
        if len(labels) != len(bitmaps):
            raise ValueError("labels and bitmaps must be the same length")
        self.labels = list(labels)
        self.bitmaps = np.asarray(bitmaps, dtype=np.float32)
        self._flat = self.bitmaps.reshape(len(self.labels), -1)
        # Templates grouped by label, so one `np.minimum.reduceat` gives each
        # label's nearest template; the rival is the second-nearest label.
        uniq, codes = np.unique(np.array(self.labels, dtype=str), return_inverse=True)
        order = np.argsort(codes, kind="stable")
        self._uniq = [str(u) for u in uniq]
        # float64 for `cdist`, which computes in float64.
        self._grouped = self._flat[order].astype(np.float64)
        self._starts = np.searchsorted(codes[order], np.arange(len(uniq)))

    def __len__(self) -> int:
        return len(self.labels)

    def match_many(self, bitmaps: np.ndarray) -> tuple[list[str], np.ndarray, np.ndarray]:
        """`match` for a stack of normalised glyph bitmaps at once: labels,
        scores and margins, one per glyph, as the HUD fields read them.

        Distances are summed exactly (`cdist` in float64 over 0/1 bitmaps
        gives integer sums) and divided once, so a margin equal to the cut is
        exactly the cut and passes; `match`'s float32 mean put a 12/240
        margin either side of 0.05 by rounding. A tie between labels takes
        the first label in sort order, at margin 0."""
        g = np.asarray(bitmaps, dtype=np.float64).reshape(len(bitmaps), -1)
        if len(g) == 0:
            return [], np.zeros(0), np.zeros(0)
        n = g.shape[1]
        s = cdist(g, self._grouped, "cityblock")
        per_label = np.minimum.reduceat(s, self._starts, axis=1)
        best = np.argmin(per_label, axis=1)
        best_s = per_label[np.arange(len(g)), best]
        if per_label.shape[1] > 1:
            rival_s = np.partition(per_label, 1, axis=1)[:, 1]
        elif s.shape[1] > 1:
            # One label only: the rival is the next template of that label.
            rival_s = np.partition(s, 1, axis=1)[:, 1]
        else:
            rival_s = best_s
        return ([self._uniq[i] for i in best], 1.0 - best_s / n, (rival_s - best_s) / n)

    def match(self, glyph: Glyph) -> tuple[str, float, float]:
        """Nearest template by mean absolute difference.

        Returns (label, score, margin).

        `score` is 1.0 for a pixel-exact match and falls toward 0 as the glyph
        diverges. `margin` is how much closer the winning digit is than the
        nearest *different* digit, and is the more discriminating of the two:
        a glyph corrupted by background wash can sit close to one template by
        accident and score well, but it is then near-equally close to several
        others. Observed on a "0" that filled in against a blown-out background
        and matched "8" at score 0.85 -- its margin was 0.017, against 0.16-0.29
        for clean glyphs.
        """
        # The scoreboard and the combat report read through this float32
        # mean under their own versions; the HUD fields read `match_many`.
        d = np.abs(self._flat - glyph.bitmap.reshape(1, -1)).mean(axis=1)
        order = np.argsort(d)
        best = int(order[0])
        label = self.labels[best]
        rival = next(
            (int(k) for k in order[1:] if self.labels[int(k)] != label),
            int(order[1]) if len(order) > 1 else best,
        )
        return label, float(1.0 - d[best]), float(d[rival] - d[best])

    # ---------- persistence ----------

    @classmethod
    def path_for(cls, profile_name: str) -> Path:
        filename = f"{template_key(profile_name)}-digits.npz"
        try:
            from .store import Store
            store_path = Store().root / "reference" / "templates" / filename
            if store_path.is_file():
                return store_path
        except Exception:
            pass
        return TEMPLATE_DIR / filename

    @classmethod
    def load(cls, profile_name: str) -> "Templates":
        path = cls.path_for(profile_name)
        if not path.is_file():
            raise SystemExit(
                f"no digit templates for profile {profile_name!r} at {path}\n"
                f"mine and label them first:  reticle glyphs <video>"
            )
        z = np.load(path, allow_pickle=False)
        return cls([str(s) for s in z["labels"]], z["bitmaps"])

    def save(self, profile_name: str) -> Path:
        filename = f"{template_key(profile_name)}-digits.npz"
        out_dir = TEMPLATE_DIR
        try:
            from .store import Store
            store_dir = Store().root / "reference" / "templates"
            if store_dir.is_dir():
                out_dir = store_dir
        except Exception:
            pass
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / filename
        np.savez_compressed(
            path, labels=np.array(self.labels, dtype="U2"), bitmaps=self.bitmaps
        )
        return path


# --------------------------------------------------------------------------- game font

#: The game's font files, relative to the store root; they stay in the store.
FONT_DIR = ("reference/game-files/release-13.06-shipping-18-5590001/fonts/"
            "ShooterGame/Content/UI/Fonts/FinalFonts")
#: Slate draws a point as 96/72 px; the UI scale is 1.0 at 1080p.
SLATE_PX_PER_PT = 96.0 / 72.0
#: Each field's font file and point size [domain:hud/digit-fonts]. Every
#: widget names DINNext_Font's face ('Default' is its first, Regular) and a
#: size; the shield's widget is not exported and its size is fitted.
FIELD_FONTS = {
    "clock": ("DINNext_Regular.ttf", 28.0),
    "score_left": ("DINNext_Regular.ttf", 22.0),
    "score_right": ("DINNext_Regular.ttf", 22.0),
    "hp": ("DINNext_Medium.ttf", 36.0),
    "shield": ("DINNext_Medium.ttf", 14.0),
    "ammo_mag": ("DINNext_Medium.ttf", 36.0),
    "ammo_reserve": ("DINNext_Regular.ttf", 16.0),
}
#: Each field's tracking, px at 1080p, from its TextBlock's `Font.Tracking`
#: in the widget data (TimerLine1 -2, HealthText -2, LoadedAmmo -2,
#: ReserveAmmo -1; TeamScore none). Slate's own unit would be 1/1000 em
#: (-0.07 px on the clock); the clock's seconds digits stand 18.0-18.25 px
#: apart against an advance of 20.25 on the dev crops, and health's 24.0-24.25
#: against 26.38, so the value reads as px. The readers place cells at
#: measured pens (SCORE_PENS, CLOCK_PENS, BOTTOM_PENS); the pitch serves the
#: layout searches that measure them.
FIELD_TRACKING = {"clock": -2.0, "hp": -2.0, "ammo_mag": -2.0, "ammo_reserve": -1.0}
#: Glyphs are drawn this many times larger, then shrunk with `INTER_AREA`.
FONT_SUPERSAMPLE = 8
#: Sub-pixel phases per axis.
FONT_PHASES = 4
#: Empty rows a soft cell keeps above the digits' top and below their baseline.
CELL_MARGIN = 1


class FieldTemplates:
    """Each HUD field's game font: `fonts` maps a field to its font file and
    point size, read as soft cells (`cells`). `files` names the font files
    read, for provenance."""

    def __init__(self, fonts: dict[str, tuple[str, float]], files: tuple[str, ...]):
        self.fonts = dict(fonts)
        self.files = files

    def cells(self, field: str, scale: float = 1.0, chars: str = "0123456789") -> GlyphCells:
        """`field`'s font at its widget's size times `scale` (the HUD's
        size against 1080p), as soft cells of `chars`."""
        path, pt = self.fonts[field]
        return font_cells(path, round(pt * SLATE_PX_PER_PT * scale, 3), chars,
                          round(FIELD_TRACKING.get(field, 0.0) * scale, 3))


def font_dir(store_root=None) -> Path:
    if store_root is None:
        from .store import Store
        store_root = Store().root
    return Path(store_root) / FONT_DIR


def game_font_templates(store_root=None) -> FieldTemplates:
    """Each `FIELD_FONTS` field's font from the store's game fonts. A
    missing font stops the reader: no mined fallback is read under the
    font's version."""
    root = font_dir(store_root)
    fonts, files = {}, set()
    for field, (name, pt) in FIELD_FONTS.items():
        path = root / name
        if not path.is_file():
            raise SystemExit(f"game font missing: {path}\n"
                             "extract the game's fonts into the store's game-file reference")
        fonts[field] = (str(path), pt)
        files.add(str(path))
    return FieldTemplates(fonts, tuple(sorted(files)))


class GlyphCells:
    """Soft coverage cells of one font at one size: every glyph of `chars`
    drawn white on black FONT_SUPERSAMPLE times larger with its pen at
    FONT_PHASES x FONT_PHASES sub-pixel phases, shrunk with INTER_AREA into
    a cell one advance wide (plus a column for the phase) and CELL_MARGIN
    rows above the digits' top and below their baseline. Nothing is cut: a
    cell is the coverage the game's glyph lays on the screen's pixels.

    Phase p = j * FONT_PHASES + i puts the pen at (i, j) / FONT_PHASES px
    right of and below the cell's integer pen `(0, base)`."""

    def __init__(self, font_file: str, px: float, chars: str, tracking: float = 0.0):
        from PIL import Image, ImageDraw, ImageFont
        ss, ph = FONT_SUPERSAMPLE, FONT_PHASES
        font = ImageFont.truetype(font_file, px * ss, layout_engine=ImageFont.Layout.BASIC)
        # Rows from the digits' top (with overshoot) to their baseline.
        tops = [font.getbbox(d, anchor="ls")[1] / ss for d in "0123456789"]
        bots = [font.getbbox(d, anchor="ls")[3] / ss for d in "0123456789"]
        self.base = int(np.ceil(-min(tops))) + CELL_MARGIN
        self.h = self.base + int(np.ceil(max(bots))) + CELL_MARGIN + 1
        self.px = px
        self.chars = chars
        self.advance: dict[str, float] = {}
        #: Pen to pen: the advance plus the widget's tracking, in px.
        self.pitch: dict[str, float] = {}
        self.cells: dict[str, np.ndarray] = {}
        for c in chars:
            adv = font.getlength(c) / ss
            w = int(np.ceil(adv)) + 1
            stack = []
            for j in range(ph):
                for i in range(ph):
                    im = Image.new("L", (w * ss, self.h * ss), 0)
                    ImageDraw.Draw(im).text(((i / ph) * ss, (self.base + j / ph) * ss), c,
                                            fill=255, font=font, anchor="ls")
                    a = np.asarray(im, np.float32) / 255.0
                    stack.append(cv2.resize(a, (w, self.h), interpolation=cv2.INTER_AREA))
            self.advance[c] = adv
            self.pitch[c] = adv + tracking
            self.cells[c] = np.stack(stack)
        digits = [c for c in chars if c.isdigit()]
        self.digits = digits
        if digits:
            widths = {self.cells[d].shape[2] for d in digits}
            if len(widths) != 1:
                raise ValueError("digit cells differ in width: the font is not tabular")
            self.w = widths.pop()
            p = ph * ph
            self.flat = np.concatenate([self.cells[d].reshape(p, -1) for d in digits]).astype(np.float64)
            self.energy = (self.flat ** 2).sum(axis=1)
            self.digit_energy = self.energy.reshape(len(digits), p).mean(axis=1)


@lru_cache(maxsize=None)
def font_cells(font_file: str, px: float, chars: str = "0123456789",
               tracking: float = 0.0) -> GlyphCells:
    return GlyphCells(font_file, px, chars, tracking)


@dataclass(frozen=True)
class Slot:
    """One digit cell decided against every digit and the empty cell, on the
    soft coverage. Costs are sums of squared coverage differences over the
    cell, each divided by the winning digit's ink energy sum(T^2)."""

    x: float          # pen, sub-pixel, in the cover's frame
    y: float          # baseline
    label: str        # the best digit
    gain: float       # sum(C T) / sum(T^2): the coverage the best digit is drawn at, 1 full, 0 absent
    margin: float     # (second digit cost - best digit cost) / energy
    fit: float        # best digit cost / energy: the residual the digit leaves
    ink: float        # the cell's ink sum(C^2) / energy: an empty cell's residual
    energy: float     # the best digit's sum(T^2)

    @property
    def explained(self) -> float:
        """Ink the digit explains over an empty cell, sum(C^2) - cost."""
        return (self.ink - self.fit) * self.energy


def slot_at(cover: np.ndarray, cells: GlyphCells, x0: int, y0: int,
            reach: int = 0, tint: float = 1.0) -> Slot | None:
    """The slot whose integer cell top-left is near (x0, y0): every digit at
    every phase over the cells at x0-1-reach..x0+reach and y0-1..y0, the
    best placement per digit. `tint` is the coverage the text is drawn at
    (1 for white): the cells are scaled by it, so every Slot measure is
    relative to text of that tint. None where every cell leaves the cover."""
    h, w = cells.h, cells.w
    H, W = cover.shape
    wins, where = [], []
    for dy in (-1, 0):
        for dx in range(-1 - reach, 1 + reach):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + h > H or x + w > W:
                continue
            wins.append(cover[y:y + h, x:x + w].reshape(-1))
            where.append((x, y))
    if not wins:
        return None
    win = np.asarray(wins, np.float64)
    wsq = (win * win).sum(axis=1)
    energy = cells.energy * (tint * tint)
    cost = wsq[:, None] - 2.0 * tint * (win @ cells.flat.T) + energy[None, :]
    nd, p = len(cells.digits), FONT_PHASES * FONT_PHASES
    per = cost.reshape(len(wins), nd, p).transpose(1, 0, 2).reshape(nd, -1)
    arg = per.argmin(axis=1)
    best = per[np.arange(nd), arg]
    order = np.argsort(best, kind="stable")
    d0 = int(order[0])
    wi, ph = divmod(int(arg[d0]), p)
    e = float(energy.reshape(nd, p)[d0, ph])
    j, i = divmod(ph, FONT_PHASES)
    x, y = where[wi]
    return Slot(x=x + i / FONT_PHASES, y=y + cells.base + j / FONT_PHASES,
                label=cells.digits[d0],
                gain=float((wsq[wi] - best[d0] + e) / (2.0 * e)),
                margin=float((best[order[1]] - best[d0]) / e) if nd > 1 else 1.0,
                fit=float(best[d0] / e), ink=float(wsq[wi] / e), energy=e)


#: The one decision on a slot, digit or empty, is cut at gain 0.5 (a digit
#: drawn at half coverage is as near either) with this margin either side:
#: a digit stands at gain >= 0.75 (`Slot.gain`, the coverage the best digit
#: is drawn at), an empty cell at <= 0.25, and a cell between holds a digit
#: too faint to read or to rule out (`faint_digit`). On the dev half of the
#: Riot-recorded matches 99 % of digit cells stand above gain 0.8.
SOFT_MARGIN = 0.25
#: Which digit: the best must beat the next by this share of its energy
#: (`Slot.margin`). 8 lies nearest 3, 6, 9 and 0: on the dev half every
#: digit cell whose label agreed with hud-0.22.0's read had margin >= 0.187
#: at its 0.1 % quantile, and none disagreed.
LABEL_MARGIN = 0.15
#: A decided cell's residual must stay under this share of the winning
#: digit's energy (`Slot.fit`; for an empty cell, its ink `Slot.ink`): more
#: is ink the decision does not explain.
SOFT_FIT = 0.5
#: A score field whose digit rows hold less ink than this share of a mean
#: digit's energy shows no digit at all.
NO_INK = 0.25

#: What a slot holds, and the field refusal each non-digit verdict names:
#: `low_margin` a digit no single label explains; `fused` a digit with ink
#: its cell does not explain beside it; `faint_digit` ink between a digit
#: and an empty cell (a dimmed digit, or pale scenery); `occluded` bright
#: ink that is neither a digit nor empty.
SLOT_VERDICTS = ("digit", "empty", "low_margin", "fused", "faint_digit", "occluded")


def slot_verdict(s: "Slot | None") -> str:
    """The decision on one slot: digit or empty at gain 0.5 +- SOFT_MARGIN,
    the digit's label at LABEL_MARGIN, either's residual at SOFT_FIT."""
    if s is None:
        return "empty"
    if s.gain >= 0.5 + SOFT_MARGIN:
        if s.margin < LABEL_MARGIN:
            return "low_margin"
        return "fused" if s.fit > SOFT_FIT else "digit"
    if s.gain <= 0.5 - SOFT_MARGIN:
        return "empty" if s.ink <= SOFT_FIT else "occluded"
    return "faint_digit"


def _top_left(pen: float, offset: int) -> int:
    """The integer cell origin whose `slot_at` search (origins o-1..o,
    phases 0..0.75) centres on a pen at `pen`; `offset` is the pen's place
    in the cell (0 across, `GlyphCells.base` down)."""
    return int(np.floor(pen - offset + 0.125 + 0.5))


def pad_cover(cover: np.ndarray, cells: GlyphCells) -> tuple[np.ndarray, int, int]:
    """`cover` inside a border of empty coverage one cell wide and tall, so
    a slot at the ROI's edge is still decided; returns it and the border."""
    py, px = cells.h, cells.w
    return cv2.copyMakeBorder(cover, py, py, px, px, cv2.BORDER_CONSTANT, value=0.0), px, py


#: Where the scoreline's digits stand, pen x and baseline y in px of the
#: scoreline ROI at 1080p, scaled with it. Every TextBlock there is centred
#: (`ETextJustify::Center`) in a box the widget fixes, so a one-digit and a
#: two-digit score stand at different places, and M:SS at one. Measured on
#: the dev half's read digit cells (every 20th crop): each pen within a
#: quarter pixel of these from the 1st to the 99th percentile.
SCORE_PENS = {
    "score_left": ((9.25,), (1.75, 17.5)),
    "score_right": ((284.5,), (276.25, 292.0)),
}
CLOCK_PENS = (121.75, 146.5, 164.5)
#: Below the round's last seconds the clock draws seconds and hundredths
#: (SS.hh) [domain:hud/low-clock-red-plate], four digits centred: measured
#: on 100 dev crops hud-0.22.0 refused as `4_glyphs`, every pen within a
#: quarter pixel of these from the 5th to the 95th percentile.
HUNDREDTHS_PENS = (112.75, 130.75, 155.5, 173.5)
#: The colon's pen: one digit pitch right of the minute's.
COLON_PEN = 140.0
FIELD_BASELINE = {"score_left": 39.0, "score_right": 38.25, "clock": 38.75}
#: Whole pixels, at 1080p, a slot's cell origin is searched beyond the two
#: origins about its pen (`slot_at` reach): 0 searches the pen within
#: about 0.9 px either way at quarter-pixel phases, where the measured pens
#: stand within a quarter pixel.
PEN_REACH = 0


def _slot(cover: np.ndarray, cells: GlyphCells, pad: tuple[int, int], pen: float,
          baseline: float, scale: float, tint: float = 1.0) -> Slot | None:
    px, py = pad
    return slot_at(cover, cells, _top_left(pen * scale + px, 0),
                   _top_left(baseline * scale + py, cells.base),
                   max(0, int(round(PEN_REACH * scale))), tint)


def read_layouts(cover: np.ndarray, cells: GlyphCells, layouts, baseline: float,
                 scale: float, tinted: bool = False, guards=()) -> tuple[str, list[Slot], str | None]:
    """One field over the padded cover: every layout's cells at their
    measured pens (px at 1080p, a layout per digit count), the layout that
    explains the most ink taken and its cells decided (`slot_verdict`).

    Returns the text, the layout's slots and the refusal or None:
    `no_digits` where no layout explains any ink; `faint_digit` where a cell
    a pitch or more beside the layout taken (where a left- or
    right-justified number grows) is faint; `low_margin` where another
    layout explains within LABEL_MARGIN of a digit's energy as much; the
    first verdict of the layout taken that is neither digit nor empty; else
    `missing_digit` (a digit at a place whose layout needs a partner that
    stands empty) or `no_digits`.

    `tinted` admits text drawn in a tint, as the game draws health in pink
    under low health: the layout taken at white sets the tint, the highest
    gain among its cells (at least TINT_MIN), and every cell is decided
    again against cells drawn at that tint. One TextBlock draws one colour,
    so a cell fainter than its siblings stays faint.

    `guards` are pens no layout uses; ink drawn as fully as a digit at one
    (gain at least 0.5 + SOFT_MARGIN, whatever its label) means the
    widget draws the number elsewhere, and the field refuses
    `beyond_layout`."""
    pad = (cells.w, cells.h)
    pens = sorted({p for lay in layouts for p in lay})
    at = {p: _slot(cover, cells, pad, p, baseline, scale) for p in pens}
    if any(v is None for v in at.values()):
        return "", [], "no_digits"
    ex = [sum(at[p].explained for p in lay) for lay in layouts]
    k = int(np.argmax(ex))
    tint = 1.0
    if tinted:
        got = min(1.0, max(at[p].gain for p in layouts[k]))
        if TINT_MIN <= got < 1.0 - SOFT_MARGIN:
            tint = got
            at = {p: _slot(cover, cells, pad, p, baseline, scale, tint) for p in pens}
            ex = [sum(at[p].explained for p in lay) for lay in layouts]
            k = int(np.argmax(ex))
    lay = [at[p] for p in layouts[k]]
    if ex[k] <= 0:
        return "", lay, "no_digits"
    pitch = cells.pitch[cells.digits[0]] / scale
    for g in guards:
        gs = _slot(cover, cells, pad, g, baseline, scale, tint)
        if gs is not None and gs.gain >= 0.5 + SOFT_MARGIN:
            return "", lay, "beyond_layout"
    beside = [at[p] for p in pens if all(abs(p - q) >= 0.8 * pitch for q in layouts[k])]
    if any(slot_verdict(v) == "faint_digit" for v in beside):
        return "", lay, "faint_digit"
    rival = max((e for i, e in enumerate(ex) if i != k), default=-np.inf)
    if ex[k] - rival < LABEL_MARGIN * float(cells.digit_energy.mean()):
        return "", lay, "low_margin"
    verdicts = [slot_verdict(v) for v in lay]
    bad = next((v for v in verdicts if v not in ("digit", "empty")), None)
    if bad is not None:
        return "", lay, bad
    if "empty" in verdicts:
        # A digit at a place whose layout needs a partner: the text is
        # centred or justified, so its partner is drawn and unseen.
        return "", lay, "no_digits" if "digit" not in verdicts else "missing_digit"
    return "".join(v.label for v in lay), lay, None


def read_score_slots(cover: np.ndarray, cells: GlyphCells, field: str, scale: float
                     ) -> tuple[str, list[Slot], str | None]:
    """One score field over the padded cover: the one-digit cell and the
    two-digit pair at their measured places (SCORE_PENS), as
    `read_layouts` decides them."""
    return read_layouts(cover, cells, SCORE_PENS[field], FIELD_BASELINE[field], scale)


def char_presence(cover: np.ndarray, cells: GlyphCells, ch: str, x0: int, y0: int,
                  reach: int = 0) -> tuple[float, float]:
    """One non-digit glyph's (gain, fit) at the cell origins
    x0-1-reach..x0+reach, y0-1..y0 and every phase, in its own energy, as
    `Slot` measures them; the placement of the highest gain."""
    stack = cells.cells[ch]
    p, h, w = stack.shape
    H, W = cover.shape
    best = None
    flat = stack.reshape(p, -1).astype(np.float64)
    energy = (flat ** 2).sum(axis=1)
    for dy in (-1, 0):
        for dx in range(-1 - reach, 1 + reach):
            y, x = y0 + dy, x0 + dx
            if y < 0 or x < 0 or y + h > H or x + w > W:
                continue
            win = cover[y:y + h, x:x + w].reshape(-1).astype(np.float64)
            corr = flat @ win
            k = int(np.argmax(corr / energy))
            e0 = float(win @ win)
            got = (corr[k] / energy[k], (e0 - 2.0 * corr[k] + energy[k]) / energy[k])
            if best is None or got[0] > best[0]:
                best = got
    return best if best is not None else (0.0, 1.0)


def read_clock_slots(cover: np.ndarray, cells: GlyphCells, scale: float
                     ) -> tuple[str, list[Slot], str | None]:
    """The clock's M:SS over the padded cover: three digit cells and the
    colon at their measured places (CLOCK_PENS, COLON_PEN), each digit cell
    decided (`slot_verdict`). Returns the three digits' text, their slots
    and the refusal or None: `hundredths` where the four cells of the
    seconds-and-hundredths form (HUNDREDTHS_PENS) all hold digits;
    `no_glyphs` where no M:SS cell holds a digit (the planted spike's
    graphic stands there, or nothing); `no_colon` where three digits stand
    without the colon's gain reaching 0.5 + SOFT_MARGIN; `{n}_glyphs` where
    n cells hold a digit and the rest are empty; else the first non-digit
    verdict."""
    pad = (cells.w, cells.h)
    base = FIELD_BASELINE["clock"]
    slots = [_slot(cover, cells, pad, p, base, scale) for p in CLOCK_PENS]
    verdicts = [slot_verdict(s) for s in slots]
    digits = sum(v == "digit" for v in verdicts)
    if digits == 3:
        gain, _fit = char_presence(cover, cells, ":", _top_left(COLON_PEN * scale + pad[0], 0),
                                   _top_left(base * scale + pad[1], cells.base),
                                   max(0, int(round(PEN_REACH * scale))))
        # Gain alone: the colon is two dots in a cell an advance wide, so
        # plate texture weighs heavily against its small energy in a
        # residual; its gain asks only whether both dots stand there, and a
        # period's one dot draws half of it.
        if gain >= 0.5 + SOFT_MARGIN:
            return "".join(s.label for s in slots), slots, None
    low = [_slot(cover, cells, pad, p, base, scale) for p in HUNDREDTHS_PENS]
    if all(slot_verdict(s) == "digit" for s in low):
        return "", low, "hundredths"
    if digits == 3:
        return "", slots, "no_colon"
    if digits == 0:
        return "", [], "no_glyphs"
    bad = next((v for v in verdicts if v not in ("digit", "empty")), None)
    if bad is not None:
        return "", [s for s in slots if s is not None], bad
    return "", [s for s, v in zip(slots, verdicts) if v == "digit"], f"{digits}_glyphs"


def _leading_zero(text: str) -> bool:
    """A number this HUD draws never starts with 0 unless it is 0: two zeros
    read where a bright mass swallowed the leading 1 of 100 (a06f04a0059f
    31.5 s) are no reading."""
    return len(text) > 1 and text[0] == "0"


# --------------------------------------------------------------------------- fields

# Where each scoreline field sits, as a fraction of the ROI width. Measured off
# 1080p footage: left score ~0.06, clock 0.40-0.59, right score ~0.91-0.98.
FIELD_BOUNDS = {
    "score_left": (0.00, 0.25),
    "clock": (0.30, 0.70),
    "score_right": (0.75, 1.00),
}
SCORE_FIELDS = ("score_left", "score_right")


@dataclass(frozen=True)
class ScorelineRead:
    """One frame's scoreline. Any field may be None when it could not be read."""

    clock_ms: int | None
    score_left: int | None
    score_right: int | None
    confidence: float  # weakest glyph match backing a populated field, else 0.0
    n_glyphs: int
    occluded: tuple[str, ...] = ()  # fields refused because something covered them
    # WHICH guard refused each field, or None when the field was read. Six
    # guards return None above and they are not the same failure: `no_glyphs`
    # is an empty field (the spike graphic stands where the clock's digits go)
    # and `low_confidence` is a clock that was there and could not be matched.
    # Carried on the read, not only in an optional census, because it goes to
    # L1 -- a null with no reason beside it is a number nobody can act on, and
    # this stage has reported a 33-60% clock read rate on exactly that basis
    # since it was built.
    clock_reason: str | None = None
    score_left_reason: str | None = None
    score_right_reason: str | None = None

    @property
    def complete(self) -> bool:
        return (
            self.clock_ms is not None
            and self.score_left is not None
            and self.score_right is not None
        )


def _soft_templates(templates: "FieldTemplates | None") -> FieldTemplates:
    """`templates` where it carries the game fonts, else the store's."""
    if isinstance(templates, FieldTemplates) and templates.fonts:
        return templates
    return _store_font_templates()


@lru_cache(maxsize=1)
def _store_font_templates() -> FieldTemplates:
    return game_font_templates()


def read_scoreline(
    frame_gray_roi: np.ndarray,
    templates: "Templates | FieldTemplates",
    min_confidence: float = 0.82,
    min_margin: float = 0.05,
    census: "Census | None" = None,
    t_ms: float | None = None,
    detail: dict | None = None,
) -> ScorelineRead:
    """Read clock and both scores out of an already-cropped scoreline ROI.

    Every field reads soft: the ROI's white-ink coverage against its local
    plate (`ink_cover`) is compared with the game font's cells
    (`GlyphCells`) at the widget's size, and each digit cell is decided
    once, against every digit and the empty cell (`slot_verdict`), at
    SOFT_MARGIN and SOFT_FIT. Nothing is binarised before that decision.
    `min_confidence` and `min_margin` belong to the binary sets and bind no
    field here. Each TextBlock is centred in a fixed box, so its cells stand
    at measured places: a score is its one-digit cell or its two-digit pair,
    whichever explains more ink (`read_score_slots`); the clock is three
    digit cells and the colon (`read_clock_slots`).

    Every field is validated against what Valorant can actually display before
    it is returned. A clock of 7:41 or a score of 87 is a misread, not a fact,
    and is dropped rather than passed downstream for stage 05 to catch.

    Each refusal names its cause (`ScorelineRead`): `no_widget` where a
    score field with a plate dark enough to show a digit holds no ink in
    its digit rows -- the scoreline draws a score in both fields whenever
    it is drawn, so the widget is absent and every field refuses so;
    `low_contrast` a plate too near white; a slot verdict (`low_margin`,
    `fused`, `faint_digit`, `occluded`); `no_digits`, `leading_zero`,
    `out_of_range`; and for the clock `no_glyphs` (the
    planted spike's graphic stands where the digits go), `no_colon` and
    `{n}_glyphs`. `census`, when given, is told each one; `detail`, when
    given, receives each field's slots.
    """
    ft = _soft_templates(templates)
    h, w = frame_gray_roi.shape
    scale = h / SCORE_BG_AT_H
    cover, room = ink_cover(frame_gray_roi)
    cover = cover.astype(np.float32)

    reasons: dict[str, str] = {}
    values: dict[str, int | None] = {}
    confidences: list[float] = []
    n_glyphs = 0

    def refuse(field: str, reason: str) -> None:
        reasons[field] = reason
        values[field] = None
        if census is not None:
            census.drop(f"{field}:{reason}",
                        round(t_ms / 1000.0, 2) if t_ms is not None else None)

    r0, r1 = int(SCORE_BAND_Y[0] * h), int(np.ceil(SCORE_BAND_Y[1] * h))
    pale, empty = {}, {}
    for name in SCORE_FIELDS:
        lo, hi = FIELD_BOUNDS[name]
        c0, c1 = int(lo * w), int(np.ceil(hi * w))
        band = room[r0:r1, c0:c1]
        pale[name] = bool(band.size) and float(band.min()) < SCORE_CONTRAST_MIN
        cells = ft.cells(name, scale)
        ink = float((cover[r0:r1, c0:c1].astype(np.float64) ** 2).sum())
        empty[name] = ink < NO_INK * float(cells.digit_energy.mean())
    absent = any(empty[n] and not pale[n] for n in SCORE_FIELDS)

    for name in ("score_left", "score_right", "clock"):
        if census is not None:
            census.saw(name)
    if absent:
        for name in ("score_left", "score_right", "clock"):
            refuse(name, "no_widget")
    else:
        for name in SCORE_FIELDS:
            if pale[name]:
                refuse(name, "low_contrast")
                continue
            cells = ft.cells(name, scale)
            pc, px, _py = pad_cover(cover, cells)
            text, slots, why = read_score_slots(pc, cells, name, scale)
            if detail is not None:
                detail[name], detail[name + "_off"] = slots, -px
            if why is not None:
                refuse(name, why)
                continue
            n_glyphs += len(slots)
            if _leading_zero(text):
                refuse(name, "leading_zero")
                continue
            value = int(text)
            if not 0 <= value <= 30:
                refuse(name, "out_of_range")
                continue
            values[name] = value
            confidences.append(min(1.0 - s.fit for s in slots))

        cells = ft.cells("clock", scale, "0123456789:")
        pc, px, _py = pad_cover(cover, cells)
        text, slots, why = read_clock_slots(pc, cells, scale)
        if detail is not None:
            detail["clock"], detail["clock_off"] = slots, -px
        if why is not None:
            refuse("clock", why)
        else:
            n_glyphs += 3
            minutes, seconds = int(text[0]), int(text[1:])
            if minutes > 1 or seconds > 59:
                refuse("clock", "out_of_range")
            else:
                values["clock"] = (minutes * 60 + seconds) * 1000
                confidences.append(min(1.0 - s.fit for s in slots))

    occluded = tuple(n for n in FIELD_BOUNDS if reasons.get(n) in ("occluded", "fused"))
    return ScorelineRead(
        clock_ms=values.get("clock"),
        score_left=values.get("score_left"),
        score_right=values.get("score_right"),
        confidence=min(confidences) if confidences else 0.0,
        n_glyphs=n_glyphs,
        occluded=occluded,
        clock_reason=reasons.get("clock"),
        score_left_reason=reasons.get("score_left"),
        score_right_reason=reasons.get("score_right"),
    )


def scoreline_roi(profile: Profile) -> Roi:
    for r in profile.rois:
        if r.name == "scoreline":
            return r
    raise SystemExit(f"profile {profile.name} has no 'scoreline' ROI")


def crop_gray(frame: np.ndarray, roi: Roi, width: int, height: int) -> np.ndarray:
    x0, y0, x1, y1 = roi.pixels(width, height)
    return cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)


# --------------------------------------------------------------------------- mining

def cluster_glyphs(glyphs: list[Glyph], tol: float = 0.06) -> list[tuple[np.ndarray, int]]:
    """Greedy cluster of normalised glyph bitmaps, for template bootstrapping.

    Returns (centroid, count) sorted by count descending. The point is to turn
    thousands of sampled glyphs into a handful of exemplars a human can label in
    one pass.
    """
    centroids: list[np.ndarray] = []
    sums: list[np.ndarray] = []
    counts: list[int] = []

    for g in glyphs:
        b = g.bitmap
        if centroids:
            d = np.array([np.abs(c - b).mean() for c in centroids])
            i = int(np.argmin(d))
            if d[i] <= tol:
                sums[i] += b
                counts[i] += 1
                centroids[i] = (sums[i] / counts[i] > 0.5).astype(np.float32)
                continue
        centroids.append(b.copy())
        sums.append(b.copy())
        counts.append(1)

    order = np.argsort(counts)[::-1]
    return [(centroids[i], counts[i]) for i in order]


# --------------------------------------------------------------------------- bottom HUD

@dataclass(frozen=True)
class SubField:
    """One readable number inside a ROI.

    Positions are fractions of ROI width, heights fractions of ROI height, so a
    spec written against 1080p footage holds at any resolution with the same HUD
    layout. The height band is what separates the two type sizes Valorant uses
    in the bottom HUD -- and what keeps non-digit chrome out: the shield pip
    outline sits inside the shield's x-range, and the ammo separator bars sit
    inside the reserve's, but neither lands in a digit's height band.
    """

    name: str
    x0: float
    x1: float
    h_lo: float
    h_hi: float
    max_digits: int
    lo: int
    hi: int


BOTTOM_FIELDS: dict[str, list[SubField]] = {
    # Shield pip and health digits. Measured at 1080p: shield digits h~13 in a
    # 65px ROI, health digits h~33.
    "hud_hp": [
        SubField("shield", 0.12, 0.38, 0.17, 0.32, 3, 0, 50),
        SubField("hp", 0.38, 0.95, 0.40, 0.62, 3, 0, 100),
    ],
    # Magazine (large) and reserve (small). Magazine reaches three digits on an
    # Odin, which pushes it toward the separator, hence the generous x range.
    "hud_ammo": [
        SubField("ammo_mag", 0.03, 0.58, 0.40, 0.62, 3, 0, 100),
        SubField("ammo_reserve", 0.60, 0.99, 0.17, 0.32, 3, 0, 500),
    ],
}


@dataclass(frozen=True)
class BottomRead:
    """One frame's bottom HUD. Any field may be None when it could not be read."""

    hp: int | None = None
    shield: int | None = None
    ammo_mag: int | None = None
    ammo_reserve: int | None = None
    confidence: float = 0.0
    occluded: tuple[str, ...] = ()
    # WHY each field is None, as `read_subfields` names it, or None when read.
    hp_reason: str | None = None
    shield_reason: str | None = None
    ammo_mag_reason: str | None = None
    ammo_reserve_reason: str | None = None


#: The lowest tint a bottom field's text is read at (`read_layouts`): the
#: game draws health pink under low health, at gain 0.69 against white
#: cells (b7d24102a6f6 1453.5 s, 587c15b07779 1129.0 s, viewed).
TINT_MIN = 0.5
#: The bottom HUD's ROIs are this tall at 1080p; pens scale with them.
BOTTOM_AT_H = 65
#: Where each bottom field's digits stand, pen x in px of its ROI at 1080p
#: for one, two and three digits, and the baseline; measured on the dev
#: half's crops hud-0.23.0 read (every pen within a quarter pixel from the
#: 5th to the 95th percentile). Health and the shield are centred, the
#: magazine right-justified (`LoadedAmmo`, `ETextJustify::Right`; an Odin's
#: 100 starts left of the ROI, which cuts its 1), the reserve left-justified.
BOTTOM_PENS = {
    "hp": ((87.25,), (75.25, 99.25), (60.75, 84.75, 109.0)),
    "shield": ((34.75,), (29.5, 40.0)),
    "ammo_mag": ((45.25,), (21.25, 45.25), (-2.75, 21.25, 45.25)),
    "ammo_reserve": ((97.75,), (97.75, 107.5), (97.75, 107.5, 117.0)),
}
BOTTOM_BASELINE = {"hp": 51.75, "shield": 42.75, "ammo_mag": 52.5, "ammo_reserve": 43.75}
#: Pens where no layout of the field stands, checked for a digit
#: (`read_layouts` guards): some weapons draw the magazine a digit further
#: right with an icon in the reserve's place (a1a995e6b19b 739.0-742.0 s, a
#: 40 that the right-justified layouts read as 4). Elsewhere the guard
#: cell holds the separator bars, at gain 0.28 (dev, every 4th crop).
BOTTOM_GUARDS = {"ammo_mag": (69.5,)}


def read_subfields(
    gray_roi: np.ndarray,
    fields: list[SubField],
    templates: "Templates | FieldTemplates",
    min_confidence: float = 0.82,
    min_margin: float = 0.05,
    reasons: dict | None = None,
) -> tuple[dict[str, int | None], tuple[str, ...], float]:
    """Read every sub-field of one ROI. Returns (values, occluded, confidence).

    Each field reads soft, as the scoreline does: white-ink coverage against
    the local plate (`ink_cover`) compared with the field's DIN Next cells
    (`FieldTemplates.cells`) at its measured places (BOTTOM_PENS), decided
    by `read_layouts`. A field whose cells stand over a plate too near white
    refuses `low_contrast`. `reasons`, when given, receives each refused
    field's reason; `min_confidence` and `min_margin` bind no field."""
    ft = _soft_templates(templates)
    h = gray_roi.shape[0]
    scale = h / BOTTOM_AT_H
    cover, room = ink_cover(gray_roi)
    cover = cover.astype(np.float32)
    values: dict[str, int | None] = {}
    occluded: list[str] = []
    confidences: list[float] = []

    def refuse(name: str, why: str) -> None:
        values[name] = None
        if reasons is not None:
            reasons[name] = why
        if why in ("occluded", "fused"):
            occluded.append(name)

    for spec in fields:
        cells = ft.cells(spec.name, scale)
        pens = [p for lay in BOTTOM_PENS[spec.name] for p in lay]
        base = BOTTOM_BASELINE[spec.name] * scale
        r0, r1 = max(0, int(base) - cells.base), max(0, int(base) - cells.base + cells.h)
        c0 = max(0, int(min(pens) * scale))
        c1 = max(c0, int(np.ceil(max(pens) * scale)) + cells.w)
        band = room[r0:r1, c0:c1]
        if band.size and float(band.min()) < SCORE_CONTRAST_MIN:
            refuse(spec.name, "low_contrast")
            continue
        pc, _px, _py = pad_cover(cover, cells)
        text, slots, why = read_layouts(pc, cells, BOTTOM_PENS[spec.name][:spec.max_digits],
                                        BOTTOM_BASELINE[spec.name], scale, tinted=True,
                                        guards=BOTTOM_GUARDS.get(spec.name, ()))
        if why is not None:
            refuse(spec.name, why)
            continue
        if _leading_zero(text):
            refuse(spec.name, "leading_zero")
            continue
        value = int(text)
        if not (spec.lo <= value <= spec.hi):
            refuse(spec.name, "out_of_range")
            continue
        confidences.append(min(1.0 - v.fit for v in slots))
        values[spec.name] = value

    return values, tuple(occluded), (min(confidences) if confidences else 0.0)


def read_bottom_hud(
    frame: np.ndarray,
    profile: Profile,
    templates: "Templates | FieldTemplates",
    width: int,
    height: int,
    min_confidence: float = 0.82,
    min_margin: float = 0.05,
) -> BottomRead:
    """Read health, shield and ammunition out of a full frame.

    Ammunition is the point of this: a magazine count that falls between two
    samples is a shot fired, which is the event the aim metrics in SS4 are
    anchored to. Health falling is damage taken, and health reaching zero is a
    death -- the other end of a duel.
    """
    by_name = {r.name: r for r in profile.rois}
    values: dict[str, int | None] = {}
    occluded: list[str] = []
    confidences: list[float] = []
    reasons: dict[str, str] = {}

    for roi_name, fields in BOTTOM_FIELDS.items():
        roi = by_name.get(roi_name)
        if roi is None:
            continue
        vals, occ, conf = read_subfields(
            crop_gray(frame, roi, width, height), fields, templates,
            min_confidence, min_margin, reasons,
        )
        values.update(vals)
        occluded.extend(occ)
        if conf > 0:
            confidences.append(conf)

    return BottomRead(
        hp=values.get("hp"),
        shield=values.get("shield"),
        ammo_mag=values.get("ammo_mag"),
        ammo_reserve=values.get("ammo_reserve"),
        confidence=min(confidences) if confidences else 0.0,
        occluded=tuple(occluded),
        hp_reason=reasons.get("hp"),
        shield_reason=reasons.get("shield"),
        ammo_mag_reason=reasons.get("ammo_mag"),
        ammo_reserve_reason=reasons.get("ammo_reserve"),
    )
