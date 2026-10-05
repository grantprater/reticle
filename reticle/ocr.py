"""Stage 02: deterministic HUD extraction (design doc SS3).

The design doc is explicit about the rule this module exists to honour:

    The HUD is structured data rendered as pixels -- parsed against templated
    regions, never inferred by a model.

So there is no OCR engine here and no learned component. Valorant renders the
scoreline in a fixed font at a fixed size for a given resolution, which makes
per-glyph template matching both exact and free. The pipeline is:

    threshold -> connected components -> filter by glyph geometry
              -> normalise each blob to a fixed grid -> nearest template

The two score fields replace the fixed threshold with white-ink coverage
against their own plate (`score_field`), since scenery behind the plate can
lift it past the clock's cut.

The scoreline, health, shield and magazine match against templates rendered
from the game's own font files (`game_font_templates`), one set per field: the widget
data names each field's face and point size, and the store's game-file
reference holds the fonts. Each digit is drawn at 8x, shrunk with
`INTER_AREA` at 4x4 sub-pixel phases, and cut at four coverage levels that
stand for the 190 luma cut over plates of different luma; each cut glyph then
passes through `normalise` as a captured glyph does. The mined set
(`Templates.load`, `reticle glyphs`) remains for the ammo reserve
(`RESERVE_FONT`), the scoreboard and the combat report. `prototypes/game_font_digits.py`
fits each field's face and size and compares the two sets on stored crops.

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

# Luma above which a pixel is treated as glyph. The scoreline is near-white on a
# translucent plate; 190 separates cleanly on every frame sampled so far.
THRESHOLD = 190

# The two score fields do not use that cut. Their plates sit at the screen's
# top edge, where sky and pale walls show through the semi-transparent plate
# [domain:minimap/transparency] and lift its luma past 190: the cut then
# fuses scenery and digits into full-height masses (266x59 px, area 10316)
# that the blocker rule refused as `occluded` over fully legible scores, for
# 4.5-43 s before a round's end on 11 of 439 Riot-recorded rounds
# [metric:unread_reset_causes/riot-21-occluded-recheck#occluded_samples_graphic_absent=161].
# The digits are near-opaque white (cores at luma 249-255 over any plate),
# so a pixel of luma I over a plate of luma b shows ink coverage
# (I - b) / (255 - b) -- the model the font templates are rendered by. `b` is
# the plate's own local background: a grey opening with a square wider than a
# stroke (~3 px) and narrower than the plate's scenery, which removes the
# digits and keeps both bright scenery and the dark chrome lines.
SCORE_BG_KERNEL = 9
#: The ROI height (1080p) SCORE_BG_KERNEL is measured at; it scales with it.
SCORE_BG_AT_H = 59
#: Coverage above which a pixel is ink: one cut, inside the template set's
#: FONT_COVER_CUTS (0.4-0.85); over a plate of luma 100 it is the 190 cut.
SCORE_INK_CUT = 0.55
#: A component is white ink only where its core reaches both this coverage
#: and SCORE_INK_WHITE luma. Digit cores read luma 249-255 and coverage
#: 0.88-1.0 over plates up to luma 230; the ROI's bright left rim peaks at
#: coverage 0.58 (luma 188), and pale scenery pieces that read 5 as 15 and 1
#: as 11 peak at 0.82 and luma 241 and 232 (a06f04a0059f 1376.0 s,
#: c40d950031bb 843.5 s).
SCORE_INK_PEAK = 0.8
SCORE_INK_WHITE = 245
#: The score digits stand 19-21 px tall at 1080p (DIN Next 22 pt); taller
#: ink is a digit fused with scenery, and blocks: a 7 fused with a door's
#: lit edge stood 11x30 and matched 1 (e37fdeca944f 908.0 s).
SCORE_MAX_H = 24
#: A plate within this much luma of white cannot show a white digit: a field
#: whose digit rows hold such a plate refuses `low_contrast`, since a digit
#: there could stand unseen beside the ones read.
SCORE_CONTRAST_MIN = 16.0
#: The score digits' rows, as fractions of the ROI height.
SCORE_BAND_Y = (0.25, 0.80)
#: A component that passes the cut but is no white ink, of a digit's height,
#: whose top and bottom sit within MAX_EDGE_SPREAD of a read digit's and whose
#: box lies within this many px of it, may be a digit too faint to trust: the
#: field refuses `faint_digit` rather than read 11 as 1.
SCORE_FAINT_GAP = 8
#: A field's components are cut from its columns and this share of the ROI's
#: width either side, so a digit at a field's edge stays whole.
FIELD_PAD = 0.05

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
    """Scale a binary glyph patch into the fixed grid."""
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


def score_field(gray: np.ndarray, lo: float, hi: float
                ) -> tuple[list[Glyph], list[tuple[float, float]], bool, bool]:
    """One score field of the scoreline ROI `gray`, spanning [lo, hi) of its
    width: glyphs and blockers cut once from `ink_cover` at SCORE_INK_CUT,
    under `_components`' geometry rule, with positions in the ROI's frame;
    and whether its digit rows hold a plate too near white for a white digit
    to show (SCORE_CONTRAST_MIN); and whether a faint digit-shaped component
    stands beside a digit (SCORE_FAINT_GAP). Only components whose core
    reaches SCORE_INK_PEAK and SCORE_INK_WHITE are ink, so a blocker here is
    white ink no digit's shape explains: a mass over the field, or two
    digits fused. Any oversize ink of MIN_AREA blocks,
    not only BLOCKER_MIN_AREA: a white streak fused with a thin 1 makes a
    7x42 mass of area 102, and dropping it read 11 as 1 (4f207c0c4e39
    2038.0 s). The cover is taken over the field and FIELD_PAD of the ROI's
    width either side."""
    h, w = gray.shape
    x0 = max(0, int((lo - FIELD_PAD) * w))
    x1 = min(w, int(np.ceil((hi + FIELD_PAD) * w)))
    cover, room = ink_cover(gray[:, x0:x1])
    binary = (cover > SCORE_INK_CUT).astype(np.uint8) * 255
    count, labels, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    core = np.zeros(count, bool)
    core[labels[cover >= SCORE_INK_PEAK]] = True
    white = np.zeros(count, bool)
    white[labels[gray[:, x0:x1] >= SCORE_INK_WHITE]] = True
    ink = core & white
    ink[0] = False
    raw = [tuple(int(v) for v in stats[i]) for i in np.nonzero(ink)[0]]
    glyphs, blockers = _split(binary, raw, w, x0, blocker_min_area=MIN_AREA,
                              max_h=SCORE_MAX_H)
    band = room[int(SCORE_BAND_Y[0] * h):int(np.ceil(SCORE_BAND_Y[1] * h)),
                max(0, int(lo * w) - x0):int(np.ceil(hi * w)) - x0]
    pale = bool(band.size) and float(band.min()) < SCORE_CONTRAST_MIN
    read = [g for g in glyphs if lo <= g.cx / max(1, w) < hi]
    faint = False
    for i in np.nonzero(~ink[1:])[0] + 1:
        x, y, fw, fh, area = (int(v) for v in stats[i])
        if not (MIN_H <= fh <= SCORE_MAX_H) or area < MIN_AREA:
            continue
        x += x0
        faint |= any(abs(y - g.y) <= MAX_EDGE_SPREAD and abs(y + fh - g.y - g.h) <= MAX_EDGE_SPREAD
                     and max(x - g.x - g.w, g.x - x - fw) <= SCORE_FAINT_GAP for g in read)
    return glyphs, blockers, pale, faint


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
}
#: The reserve's font: DIN Next Regular 16 pt. Not read with it yet: the
#: reserve's 1 (4x14 px, 19 lit) falls under MIN_AREA, and the rendered 3
#: then reads 31 as 3 with confidence where the mined set refuses
#: (4f207c0c4e39 128.0 and 1208.0 s), so the reserve keeps the mined set.
RESERVE_FONT = ("DINNext_Regular.ttf", 16.0)
#: Glyphs are drawn this many times larger, then shrunk with `INTER_AREA`.
FONT_SUPERSAMPLE = 8
#: Sub-pixel phases per axis.
FONT_PHASES = 4
#: Coverage above which a rendered pixel is glyph. White text over a plate of
#: luma b passes the 190 cut where coverage exceeds (190 - b) / (255 - b);
#: these four cover plates from about 100 (0.4) to 170 (0.85).
FONT_COVER_CUTS = (0.4, 0.55, 0.7, 0.85)
#: A rendered digit whose largest piece is shorter than this share of its ink
#: is broken by the cut and makes no template.
BROKEN_GLYPH_H = 0.85


def _font_cover(ch: str, font_file: str, px: float, dx: float, dy: float) -> np.ndarray:
    """`ch` white on black at `px` px per em, offset (dx, dy) px, as float32
    coverage: drawn FONT_SUPERSAMPLE times larger, shrunk with INTER_AREA."""
    from PIL import Image, ImageDraw, ImageFont
    ss = FONT_SUPERSAMPLE
    font = ImageFont.truetype(font_file, px * ss, layout_engine=ImageFont.Layout.BASIC)
    left, top, right, bottom = font.getbbox(ch)
    pad = 2 * ss
    w = int(np.ceil((right - left + 2 * pad) / ss)) * ss
    h = int(np.ceil((bottom - top + 2 * pad) / ss)) * ss
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((pad - left + dx * ss, pad - top + dy * ss), ch, fill=255, font=font)
    a = np.asarray(im, np.float32) / 255.0
    return cv2.resize(a, (w // ss, h // ss), interpolation=cv2.INTER_AREA)


def _cut_glyph(cover: np.ndarray, cut: float) -> np.ndarray | None:
    """A rendered glyph as the reader sees one: cut once, its largest
    component's box, `normalise`. None where the cut breaks the digit: a
    largest piece shorter than BROKEN_GLYPH_H of the ink's height is a
    fragment, and a fragment template would let a cut-off digit match."""
    binary = (cover > cut).astype(np.uint8) * 255
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, 8)
    if n < 2:
        return None
    i = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    x, y, w, h = (int(v) for v in stats[i, :4])
    rows = np.nonzero(binary.any(axis=1))[0]
    if h < BROKEN_GLYPH_H * (rows[-1] - rows[0] + 1):
        return None
    return normalise(binary[y:y + h, x:x + w])


@lru_cache(maxsize=None)
def font_digit_templates(font_file: str, pt: float) -> Templates:
    """Digits 0-9 of one font file at `pt` points: every distinct glyph over
    FONT_PHASES x FONT_PHASES phases and FONT_COVER_CUTS."""
    px = pt * SLATE_PX_PER_PT
    labels: list[str] = []
    maps: list[np.ndarray] = []
    seen: set[tuple[str, bytes]] = set()
    for d in "0123456789":
        for j in range(FONT_PHASES):
            for i in range(FONT_PHASES):
                cover = _font_cover(d, font_file, px, i / FONT_PHASES, j / FONT_PHASES)
                for cut in FONT_COVER_CUTS:
                    bm = _cut_glyph(cover, cut)
                    if bm is None or (d, bm.tobytes()) in seen:
                        continue
                    seen.add((d, bm.tobytes()))
                    labels.append(d)
                    maps.append(bm)
    return Templates(labels, np.array(maps, np.float32))


class FieldTemplates:
    """One `Templates` per field, rendered from the game's font files; a
    field with no font set reads `default` (the mined set). `files` names the
    font files read, for provenance."""

    def __init__(self, by_field: dict[str, Templates], files: tuple[str, ...],
                 default: Templates | None = None):
        self.by_field = dict(by_field)
        self.files = files
        self.default = default

    def __getitem__(self, field: str) -> Templates:
        if field in self.by_field:
            return self.by_field[field]
        if self.default is None:
            raise KeyError(f"no templates for field {field!r}")
        return self.default


def font_dir(store_root=None) -> Path:
    if store_root is None:
        from .store import Store
        store_root = Store().root
    return Path(store_root) / FONT_DIR


def game_font_templates(store_root=None, default: Templates | None = None) -> FieldTemplates:
    """Each `FIELD_FONTS` field's templates from the store's game fonts, and
    `default` for every other field. A missing font stops the reader: no
    mined fallback is read under the font's version."""
    root = font_dir(store_root)
    by_field, files = {}, set()
    for field, (name, pt) in FIELD_FONTS.items():
        path = root / name
        if not path.is_file():
            raise SystemExit(f"game font missing: {path}\n"
                             "extract the game's fonts into the store's game-file reference")
        by_field[field] = font_digit_templates(str(path), pt)
        files.add(str(path))
    return FieldTemplates(by_field, tuple(sorted(files)), default)


def templates_for(templates: "Templates | FieldTemplates", field: str) -> Templates:
    """The templates one field reads against: its own from a `FieldTemplates`,
    else the one set every field shares."""
    return templates[field] if isinstance(templates, FieldTemplates) else templates


def _leading_zero(text: str) -> bool:
    """A number this HUD draws never starts with 0 unless it is 0: two zeros
    read where a bright mass swallowed the leading 1 of 100 (a06f04a0059f
    31.5 s) are no reading."""
    return len(text) > 1 and text[0] == "0"


#: Digits one TextBlock draws share their top and bottom rows. A glyph whose
#: top and bottom both sit more than this (1080p px) off its siblings' is
#: displaced debris: a 7x22 stripe at the scoreline ROI's edge, 3 px low at
#: its top and 5 px at its bottom, read 9 as 19 (a06f04a0059f 1689.5 s). Bloom
#: on a digit moves one edge only, so either edge alone refuses nothing.
MAX_EDGE_SPREAD = 2


def _misaligned(glyphs: list[Glyph]) -> bool:
    if len(glyphs) < 2:
        return False
    tops = [g.y for g in glyphs]
    bottoms = [g.y + g.h for g in glyphs]
    return (max(tops) - min(tops) > MAX_EDGE_SPREAD
            and max(bottoms) - min(bottoms) > MAX_EDGE_SPREAD)


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


def drop_odd_siblings(glyphs: list[Glyph]) -> list[Glyph]:
    """Remove glyphs whose height disagrees with the field's median height.

    A no-op for a field of one glyph, and for the normal case where every digit
    in a field is the same size. What it removes is fragments left behind when
    a bright mass merges with a digit.
    """
    if len(glyphs) < 2:
        return glyphs
    median = float(np.median([g.h for g in glyphs]))
    if median <= 0:
        return glyphs
    return [
        g for g in glyphs
        if SIBLING_MIN_RATIO <= g.h / median <= SIBLING_MAX_RATIO
    ]


def _digits(glyphs: list[Glyph], templates: Templates) -> tuple[str, float, float]:
    """Concatenated labels plus the weakest score and weakest margin seen."""
    if not glyphs:
        return "", 1.0, 1.0
    labels, scores, margins = templates.match_many(np.stack([g.bitmap for g in glyphs]))
    return ("".join(labels), min(1.0, float(scores.min())), min(1.0, float(margins.min())))


def read_scoreline(
    frame_gray_roi: np.ndarray,
    templates: "Templates | FieldTemplates",
    min_confidence: float = 0.82,
    min_margin: float = 0.05,
    census: "Census | None" = None,
    t_ms: float | None = None,
) -> ScorelineRead:
    """Read clock and both scores out of an already-cropped scoreline ROI.

    Every field is validated against what Valorant can actually display before
    it is returned. A clock of 7:41 or a score of 87 is a misread, not a fact,
    and is dropped rather than passed downstream for stage 05 to catch.

    `census`, when given, is told WHICH guard refused each field. Six of them
    return `None` here and every one of them reads identically downstream --
    the field is simply absent -- so the clock read rate of 33-60% that this
    stage has reported since it was built says nothing at all about its cause.
    CLAUDE.md's standing hypothesis is that some large share of it is the spike
    graphic occupying the digits' pixels, i.e. frames with nothing to read
    rather than frames misread. `occluded` against `few_glyphs` separates those
    two, and nothing else does. The reader is unchanged by it; see
    `reticle.census`.
    """
    # The clock reads the 190 cut over its own columns; each score field reads
    # ink against its plate (`score_field`).
    width = frame_gray_roi.shape[1]
    lo, hi = FIELD_BOUNDS["clock"]
    c0 = max(0, int((lo - FIELD_PAD) * width))
    c1 = min(width, int(np.ceil((hi + FIELD_PAD) * width)))
    source = {"clock": _components(frame_gray_roi[:, c0:c1], x0=c0, width=width)}
    pale: set[str] = set()
    faint: set[str] = set()
    for name in SCORE_FIELDS:
        g, b, low, dim = score_field(frame_gray_roi, *FIELD_BOUNDS[name])
        source[name] = (g, b)
        if low:
            pale.add(name)
        if dim:
            faint.add(name)

    buckets: dict[str, list[Glyph]] = {}
    for name, (lo, hi) in FIELD_BOUNDS.items():
        buckets[name] = [g for g in source[name][0] if lo <= g.cx / max(1, width) < hi]
    glyphs = [g for v in buckets.values() for g in v]

    # Discard debris before any counting, so the digit-count rules below are
    # applied to glyphs that are actually digits.
    buckets = {k: drop_odd_siblings(v) for k, v in buckets.items()}

    # A field with an oversize mass across it may be missing a digit that got
    # fused into the mass, which reads as a confident but wrong smaller number.
    occluded = tuple(
        name
        for name, (lo, hi) in FIELD_BOUNDS.items()
        if any(bx0 < hi and bx1 > lo for bx0, bx1 in source[name][1])
    )
    # A score plate too near white to show a digit may hide one beside the
    # digits read: a `pale` field refuses `low_contrast`.

    confidences: list[float] = []

    reasons: dict[str, str] = {}

    def refuse(field: str, reason: str) -> None:
        reasons[field] = reason
        if census is not None:
            census.drop(f"{field}:{reason}",
                        round(t_ms / 1000.0, 2) if t_ms is not None else None)

    def read_int(name: str, lo: int, hi: int) -> int | None:
        if census is not None:
            census.saw(name)
        if name in occluded:
            refuse(name, "occluded")
            return None
        if name in pale:
            refuse(name, "low_contrast")
            return None
        if name in faint:
            refuse(name, "faint_digit")
            return None
        text, worst, margin = _digits(buckets[name], templates_for(templates, name))
        if not text or not text.isdigit():
            refuse(name, "no_digits" if not text else "not_a_number")
            return None
        if _leading_zero(text):
            refuse(name, "leading_zero")
            return None
        if _misaligned(buckets[name]):
            refuse(name, "misaligned")
            return None
        if worst < min_confidence:
            refuse(name, "low_confidence")
            return None
        if margin < min_margin:
            refuse(name, "low_margin")
            return None
        value = int(text)
        if not (lo <= value <= hi):
            refuse(name, "out_of_range")
            return None
        confidences.append(worst)
        return value

    # Round scores. 13 wins a normal match; overtime can climb, so the ceiling
    # is loose. Two digits maximum.
    def read_score(name: str) -> int | None:
        # More than two glyphs in a score field is not a number this game can
        # show, so it is refused before any matching. It is ALSO the signature
        # of the live defect in CLAUDE.md -- 9acf02f98283 reads `1 -> 11 -> 1`
        # within half a second, a spurious leading digit -- so the rate here is
        # the measurement that defect needs, and it was invisible before.
        if len(buckets[name]) > 2:
            if census is not None:
                census.saw(name)
            refuse(name, "too_many_glyphs")
            return None
        return read_int(name, 0, 30)

    score_left = read_score("score_left")
    score_right = read_score("score_right")

    # Clock is M:SS -- one minute digit, two second digits. A round starts at
    # 1:40 and buy at 0:30, so minutes never exceed 1 in normal play.
    #
    # The fixed three-digit format also settles occlusion for this field without
    # having to refuse it. A mass that merges with a digit absorbs that digit
    # into itself, so the digit disappears and only two glyphs remain -- meaning
    # three well-formed glyphs are self-evidently a complete read, whatever else
    # is bright nearby. (A digit corrupted without merging is caught by the
    # margin gate instead.) The score fields get no such guarantee: 1 or 2 digits
    # are both legal, so a missing one is indistinguishable from a short score,
    # and there the conservative refusal stands.
    clock_ms: int | None = None
    clock_glyphs = buckets["clock"]
    if census is not None:
        census.saw("clock")
    if len(clock_glyphs) != 3:
        # The clock is always M:SS, so anything but three glyphs is not a clock.
        # Distinguishing NONE from SOME is what tests CLAUDE.md's hypothesis
        # that much of the 33-60% read rate is the spike graphic standing where
        # the digits go -- a planted round has nothing to read, and that is not
        # the same failure as a clock that was there and could not be matched.
        refuse("clock", "no_glyphs" if not clock_glyphs else
               f"{len(clock_glyphs)}_glyphs")
    else:
        text, worst, margin = _digits(clock_glyphs, templates_for(templates, "clock"))
        if not text.isdigit():
            refuse("clock", "not_a_number")
        elif _misaligned(clock_glyphs):
            refuse("clock", "misaligned")
        elif worst < min_confidence:
            refuse("clock", "low_confidence")
        elif margin < min_margin:
            refuse("clock", "low_margin")
        else:
            minutes, seconds = int(text[0]), int(text[1:])
            if minutes > 1 or seconds > 59:
                refuse("clock", "out_of_range")
            else:
                clock_ms = (minutes * 60 + seconds) * 1000
                confidences.append(worst)

    return ScorelineRead(
        clock_ms=clock_ms,
        score_left=score_left,
        score_right=score_right,
        confidence=min(confidences) if confidences else 0.0,
        n_glyphs=len(glyphs),
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


def read_subfields(
    gray_roi: np.ndarray,
    fields: list[SubField],
    templates: "Templates | FieldTemplates",
    min_confidence: float = 0.82,
    min_margin: float = 0.05,
) -> tuple[dict[str, int | None], tuple[str, ...], float]:
    """Read every sub-field of one ROI. Returns (values, occluded, confidence)."""
    binary, raw = _raw_components(gray_roi)
    h_roi = max(1, gray_roi.shape[0])
    w_roi = max(1, gray_roi.shape[1])

    values: dict[str, int | None] = {}
    occluded: list[str] = []
    confidences: list[float] = []

    for spec in fields:
        candidates: list[Glyph] = []
        blocked = False
        for x, y, w, h, area in raw:
            cx = (x + w / 2.0) / w_roi
            if not (spec.x0 <= cx < spec.x1):
                continue
            hf = h / h_roi
            in_band = spec.h_lo <= hf <= spec.h_hi
            if in_band and area >= MIN_AREA and w / max(1, h) <= MAX_ASPECT:
                candidates.append(
                    Glyph(x=x, y=y, w=w, h=h, bitmap=normalise(binary[y : y + h, x : x + w]))
                )
            elif area >= BLOCKER_MIN_AREA:
                # Something substantial overlaps this field that is not a digit:
                # a mass covering it, or two digits fused into one blob. Either
                # way a digit may be missing, so refuse rather than report what
                # the survivors spell.
                blocked = True

        if blocked:
            occluded.append(spec.name)
            values[spec.name] = None
            continue

        candidates.sort(key=lambda g: g.x)
        candidates = drop_odd_siblings(candidates)
        if not candidates or len(candidates) > spec.max_digits:
            values[spec.name] = None
            continue

        text, worst, margin = _digits(candidates, templates_for(templates, spec.name))
        if (not text.isdigit() or _leading_zero(text) or _misaligned(candidates)
                or worst < min_confidence
                or margin < min_margin):
            values[spec.name] = None
            continue
        value = int(text)
        if not (spec.lo <= value <= spec.hi):
            values[spec.name] = None
            continue
        confidences.append(worst)
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

    for roi_name, fields in BOTTOM_FIELDS.items():
        roi = by_name.get(roi_name)
        if roi is None:
            continue
        vals, occ, conf = read_subfields(
            crop_gray(frame, roi, width, height), fields, templates,
            min_confidence, min_margin,
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
    )
