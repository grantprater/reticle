"""Stage 02: the killfeed killstreak numeral, read from the game's own font.

A killer on a streak within the round carries a roman numeral left of the
killer's portrait [domain:killfeed/killstreak-indicator]: which kill of the
round this entry is for that player. The numeral is text, not a texture: the
row widget (`KillFeedRow`) draws `KillNumberText`, a size-10 TextBlock,
centred on a 32x16 backer at the bottom of the `LeftOverhang` box beside the
killer portrait. The assist panel [domain:killfeed/assist-panel] draws at the
top of the same box, so both can show at once
[domain:killfeed/assist-panel-layout].

**What this reads.** For each killer portrait row `killfeed.portrait_observations`
placed, the slot is placed from that row's art window (the entry anchor
`EntryAnchors` carried, else the art window) and the band's bottom, times the
capture scale, and nothing else: the numeral is never searched for over the
row. The slot's soft whiteness (each pixel's least channel over 255: white
text is high on the green and the red backer alike) is scored against
templates of II through X, rendered from DIN Next Heavy at `FONT_PT` points
(Slate draws a point as 96/72 px) at `SUPERSAMPLE` times and shrunk with
`INTER_AREA` to the capture scale, at `PHASES` x `PHASES` sub-pixel phases.

**Absence is a reading.** Each template's score is the fraction of its local
window's whiteness variance a `background + contrast * template` fit
explains, the contrast held at no less than `TEXT_MIN_CONTRAST` (white text
over a backer). The empty template is the fit with no text: it explains
nothing, so it scores 0. A numeral the window does not hold at that contrast
scores below 0, and the empty template wins. So `numeral` is a numeral, the
empty string (the slot holds none), or None with a `reason`; each row stores
every template's `scores`, the read's `score` and `margin`, and `rests_on`
the anchor that placed the slot.

The font was chosen on three badges of 59c70f1ef720 (III, IV, V at 2079.5,
2091.0 and 2111.0 s): DIN Next Heavy at 13 px against every exported game font
and size, in-sample; the slot offsets were measured there too.

VI draws [domain:killfeed/killstreak-numeral-six]; whether VII or higher
does is not known, and the setter's logic is not exported, so the reader
scores through X and records what it sees.

The font is loaded from the store's game-file reference (`FONT_RELPATH`),
never copied into this repository.

Owns [owns:killfeed-killstreak-numeral].
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

import cv2

# 0.1.0 (2026-10-03): first reader.
KILLFEED_NUMERAL_VERSION = "killfeed-numeral-0.1.0"

#: The numerals scored. The domain fact says the numeral starts at III; II is
#: scored so a II, if drawn, reads as one and not as III.
NUMERALS = ("II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X")
#: The empty template's key in `scores`, and the empty reading.
EMPTY = ""

#: The font file, relative to the store root. Game files stay in the store.
FONT_RELPATH = ("reference/game-files/release-13.06-shipping-18-5590001/fonts/"
                "ShooterGame/Content/UI/Fonts/FinalFonts/DINNext_Heavy.ttf")
#: `KillNumberText`'s Font.Size (points), and Slate's 96/72 px per point.
FONT_PT = 10.0
SLATE_PX_PER_PT = 96.0 / 72.0
#: The em in px at 1080p: `FONT_PT` * 96/72 = 13.33. The probe's integer
#: sizes put 13 best of 9-17 on the three fitting badges; 13.33 scores as
#: well there (III 0.950, IV 0.909, V 0.917 against 0.944, 0.910, 0.905).
FONT_PX = FONT_PT * SLATE_PX_PER_PT
#: Glyphs are drawn this many times larger, then shrunk with `INTER_AREA`.
SUPERSAMPLE = 8
#: Sub-pixel phases per axis (1/PHASES px steps).
PHASES = 4
#: Empty columns (x) and rows (y) about the ink, base px: ink beside the
#: string counts against it.
TEMPLATE_PAD_X, TEMPLATE_PAD_Y = 3, 1

# --- slot geometry, base px at 1080 ------------------------------------------
# Measured on the three fitting badges (59c70f1ef720 2079.5, 2091.0, 2111.0 s):
# the best template's centre sat -10.5, -11.0 and -11.25 px from the killer
# art's left edge and -8.5, -8.5 and -8.0 px from the art window's bottom.
#: The numeral's centre column less the killer art's left edge.
SLOT_CX = -11.0
#: The numeral's centre row less the killer art window's bottom edge.
SLOT_CY = -8.5
#: The search about the predicted centre: columns and rows either side.
SLOT_SEARCH_X, SLOT_SEARCH_Y = 3, 3

#: Least contrast (whiteness units, 0..1) a numeral's fit may use: white text
#: over the side's backer. Below it, the fit is held at this value.
TEXT_MIN_CONTRAST = 0.25
#: A numeral read needs this score, and this margin over the next template,
#: the empty one included.
READ_MIN_SCORE = 0.5
READ_MIN_MARGIN = 0.1
#: An empty read needs every numeral's score at most this.
EMPTY_MAX_SCORE = 0.0

#: Refusals.
REFUSE_NO_ANCHOR = "no_killer_art"
REFUSE_CUT = "slot_cut_by_roi"
REFUSE_WEAK = "weak_fit"
REFUSE_AMBIGUOUS = "ambiguous"
REFUSE_NO_FONT = "no_font"


def font_path(store_root) -> Path:
    """The game font, in the store's game-file reference."""
    return Path(store_root) / FONT_RELPATH


def store_font(store_root) -> str | None:
    """The game font's path when the store holds it, else None (the reader
    then refuses each killer row as `no_font`)."""
    p = font_path(store_root)
    return str(p) if p.is_file() else None


def _ink(text: str, font_file: str, px: float, dx: float, dy: float) -> np.ndarray:
    """`text` drawn white on black at `px` capture px per em, offset (dx, dy)
    px, as float32 ink 0..1: drawn at SUPERSAMPLE times, then shrunk with
    `INTER_AREA`."""
    from PIL import Image, ImageDraw, ImageFont
    ss = SUPERSAMPLE
    font = ImageFont.truetype(font_file, px * ss, layout_engine=ImageFont.Layout.BASIC)
    left, top, right, bottom = font.getbbox(text)
    pad = 2 * ss
    w = int(np.ceil((right - left + 2 * pad) / ss)) * ss
    h = int(np.ceil((bottom - top + 2 * pad) / ss)) * ss
    im = Image.new("L", (w, h), 0)
    ImageDraw.Draw(im).text((pad - left + dx * ss, pad - top + dy * ss), text, fill=255,
                            font=font)
    a = np.asarray(im, np.float32) / 255.0
    return cv2.resize(a, (w // ss, h // ss), interpolation=cv2.INTER_AREA)


@lru_cache(maxsize=8)
def templates(font_file: str, scale: float = 1.0) -> dict[str, np.ndarray]:
    """{numeral: (PHASES**2, h, w) float32 templates}: each numeral at every
    sub-pixel phase, cut to one box per numeral (the union of the phases' ink)
    and padded by `TEMPLATE_PAD_X`/`TEMPLATE_PAD_Y` empty px at the capture
    `scale`. Rendered once per font and scale."""
    px = FONT_PX * float(scale)
    pad_x = max(1, int(round(TEMPLATE_PAD_X * scale)))
    pad_y = max(1, int(round(TEMPLATE_PAD_Y * scale)))
    out = {}
    for text in NUMERALS:
        inks = [_ink(text, font_file, px, i / PHASES, j / PHASES)
                for j in range(PHASES) for i in range(PHASES)]
        stack = np.stack(inks)
        any_ink = (stack > 0.02).any(axis=0)
        ys, xs = np.nonzero(any_ink)
        stack = stack[:, ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        out[text] = np.ascontiguousarray(
            np.pad(stack, ((0, 0), (pad_y, pad_y), (pad_x, pad_x))), np.float32)
    return out


def slot_whiteness(bgr: np.ndarray) -> np.ndarray:
    """Each pixel's least channel over 255: soft, high only where all three
    channels are, so white text is high on the green and the red backer."""
    b, g, r = cv2.split(np.ascontiguousarray(bgr))
    return cv2.min(cv2.min(b, g), r).astype(np.float32) * np.float32(1.0 / 255.0)


def fit_scores(window: np.ndarray, temps: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Score one numeral's phase templates `temps` (n, th, tw) at every
    placement inside `window` (h, w): the fraction of each placement's local
    whiteness variance that `background + contrast * template` explains,
    the contrast held at least `TEXT_MIN_CONTRAST`. Returns (scores, best):
    scores (n, h - th + 1, w - tw + 1); best (phase, y, x) of the highest.

    With r the local ZNCC and t = TEXT_MIN_CONTRAST * sd(template) /
    sd(window), the least-squares fit explains r**2 when its contrast
    r * sd(window) / sd(template) reaches the floor, else 2 t r - t**2.
    Every placement and phase in one matrix product: the window's patches
    (`sliding_window_view`) against the centred templates."""
    n, th, tw = temps.shape
    win = np.asarray(window, np.float32)
    hh, ww = win.shape[0] - th + 1, win.shape[1] - tw + 1
    patches = np.lib.stride_tricks.sliding_window_view(win, (th, tw)).reshape(hh * ww, th * tw)
    pc = patches - patches.mean(axis=1, keepdims=True)
    sd_w = np.sqrt((pc * pc).mean(axis=1)) + 1e-6                       # (P,)
    tc = temps.reshape(n, -1)
    tc = tc - tc.mean(axis=1, keepdims=True)
    sd_t = np.sqrt((tc * tc).mean(axis=1)) + 1e-9                       # (n,)
    r = (tc @ pc.T) / (th * tw * sd_t[:, None] * sd_w[None, :])        # (n, P)
    t = TEXT_MIN_CONTRAST * sd_t[:, None] / sd_w[None, :]
    out = np.maximum(np.where(r >= t, r * r, 2.0 * t * r - t * t), -1.0)
    out = out.reshape(n, hh, ww).astype(np.float32)
    best = np.unravel_index(int(np.argmax(out)), out.shape)
    return out, best


def slot_windows(crop: np.ndarray, art_x: float, art_bottom: float, scale: float,
                 temps: dict[str, np.ndarray]) -> dict[str, tuple[np.ndarray, int, int]] | None:
    """Each template's search window: the whiteness (`slot_whiteness`) about the
    predicted numeral centre (`SLOT_CX`, `SLOT_CY` from the killer art's left
    edge and bottom), the template's extent plus `SLOT_SEARCH_X` /
    `SLOT_SEARCH_Y` either side; {numeral: (window, x0, y0)} in ROI px, or
    None when the ROI's edge cuts any of them. `crop` is the ROI (BGR); only
    the slot's pixels are converted."""
    h, w = crop.shape[:2]
    cx = art_x + SLOT_CX * scale
    cy = art_bottom + SLOT_CY * scale
    sx, sy = SLOT_SEARCH_X * scale, SLOT_SEARCH_Y * scale
    boxes = {}
    for text, ts in temps.items():
        th, tw = ts.shape[1:]
        box = (int(np.floor(cx - tw / 2.0 - sx)), int(np.floor(cy - th / 2.0 - sy)),
               int(np.ceil(cx + tw / 2.0 + sx)) + 1, int(np.ceil(cy + th / 2.0 + sy)) + 1)
        if box[0] < 0 or box[1] < 0 or box[2] > w or box[3] > h:
            return None
        boxes[text] = box
    ux0, uy0 = min(b[0] for b in boxes.values()), min(b[1] for b in boxes.values())
    ux1, uy1 = max(b[2] for b in boxes.values()), max(b[3] for b in boxes.values())
    white = slot_whiteness(crop[uy0:uy1, ux0:ux1])
    return {text: (white[y0 - uy0:y1 - uy0, x0 - ux0:x1 - ux0], x0, y0)
            for text, (x0, y0, x1, y1) in boxes.items()}


def read_slot(windows: dict[str, tuple[np.ndarray, int, int]],
              temps: dict[str, np.ndarray]) -> dict:
    """Score every numeral in its window (`slot_windows`) and the empty
    template; the reading and its evidence. Pure over the windows."""
    scores = {EMPTY: 0.0}
    where = {}
    for text, ts in temps.items():
        win, wx0, wy0 = windows[text]
        sc, (k, y, x) = fit_scores(win, ts)
        scores[text] = round(float(sc[k, y, x]), 4)
        where[text] = (int(k), int(y) + wy0, int(x) + wx0)
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    (top, s1), (_, s2) = ranked[0], ranked[1]
    margin = round(s1 - s2, 4)
    best_numeral = max((v for k, v in scores.items() if k != EMPTY), default=0.0)
    row = {"scores": scores, "score": round(s1, 4), "margin": margin, "best": top}
    if top == EMPTY:
        ok = best_numeral <= EMPTY_MAX_SCORE
        row.update(numeral=EMPTY if ok else None, reason=None if ok else REFUSE_AMBIGUOUS)
    elif s1 < READ_MIN_SCORE:
        row.update(numeral=None, reason=REFUSE_WEAK)
    elif margin < READ_MIN_MARGIN:
        row.update(numeral=None, reason=REFUSE_AMBIGUOUS)
    else:
        row.update(numeral=top, reason=None)
    k, y, x = where[ranked[0][0] if top != EMPTY else ranked[1][0]]
    th, tw = temps[ranked[0][0] if top != EMPTY else ranked[1][0]].shape[1:]
    # where the best numeral template sat (ROI px), read or not
    row["at"] = {"x": x, "y": y, "w": int(tw), "h": int(th),
                 "phase": [k % PHASES, k // PHASES]}
    return row


def numeral_observations(crop: np.ndarray, portraits: list[dict], font_file: str | None,
                         scale: float = 1.0, art_h: float = 34.0) -> list[dict]:
    """One row per killer portrait row of this frame: the numeral beside that
    killer's art, or None with a reason. `crop` is the killfeed ROI (BGR);
    `portraits` are `portrait_observations` rows of the same frame; `art_h`
    the art window's height in capture px. The slot is placed from the row's
    entry anchor when it holds one, else its art window; `rests_on` names
    which."""
    killers = [p for p in portraits if p.get("role") == "killer"]
    if not killers:
        return []

    def base(p):
        return {"slot": p["slot"], "entry": p.get("entry"), "killer_ally": p.get("ally")}

    if font_file is None:
        return [{**base(p), "numeral": None, "reason": REFUSE_NO_FONT} for p in killers]
    temps = templates(font_file, round(float(scale), 6))
    out = []
    for p in killers:
        if p.get("art_y0") is None or p.get("art_x0") is None:
            out.append({**base(p), "numeral": None, "reason": REFUSE_NO_ANCHOR})
            continue
        if p.get("entry_anchor") is not None:
            ax, src = float(p["entry_anchor"]), "entry_anchor"
        else:
            ax, src = float(p["art_x0"]), "art_window"
        bottom = float(p["art_y0"]) + float(art_h)
        rests = {"prior": src, "x": round(ax, 2), "art_bottom": round(bottom, 2)}
        if p.get("entry") is not None:
            rests["entry"] = p["entry"]
        wins = slot_windows(crop, ax, bottom, scale, temps)
        if wins is None:
            out.append({**base(p), "numeral": None, "reason": REFUSE_CUT, "rests_on": [rests]})
            continue
        out.append({**base(p), **read_slot(wins, temps), "rests_on": [rests]})
    return out
