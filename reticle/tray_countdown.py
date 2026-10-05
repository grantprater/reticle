r"""Stage 02: the restock countdown numeral above an ability tray slot, read from
the game's own font.

    .\.venv\Scripts\python.exe -m reticle tray <session>     (stored crops, no decode)

Owns [owns:tray-restock-countdown].

After a spend of an ability whose charge comes back by itself, the tray draws a
white numeral above the right of the slot's icon that counts down to the
return [domain:hud/ability-tray-restock-countdown]: whole seconds above one
second, tenths below. This module reads the numeral; what it counts on each
ability is the player's to say, so a read stores what is drawn and nothing
about its meaning.

**The font.** Every DIN Next weight the game files hold, at every em from 10
to 24 px, was fitted to the nine hand reads the domain fact records
(`9acf02f98283` '50', '10', '1'; `043bafca271a` '50', '0.4'; `bfad2778a372`
'50'; `c62c2b06bcfb` '0.6', '0.7', '0.1'), each scored as `killfeed_numeral`
scores its numeral. DIN Next Regular at 16 px fitted best, mean
[metric:tray_countdown/font@nine-hand-reads#regular_16_mean=0.9] and least
[metric:tray_countdown/font@nine-hand-reads#regular_16_min=0.87], ahead of
Medium ([metric:tray_countdown/font@nine-hand-reads#medium_16_mean=0.848]) and
Heavy, the killfeed's weight
([metric:tray_countdown/font@nine-hand-reads#heavy_15_mean=0.695]). 16 px is
12 points at Slate's 96/72 px per point. The font file is loaded from the
store's game-file reference (`FONT_RELPATH`), never copied into this
repository. The choice is in-sample on those nine reads
[domain:hud/ability-tray-restock-countdown-font].

**The placement.** The numeral is centred: '50', '49', '48', '47' and '0.7'
sat with their centres 35.5 to 36.0 px right of slot E's centre and 980 to
980.5 px down, so a read searches `SEARCH_X` and `SEARCH_Y` px about
(`NUMERAL_DX`, `NUMERAL_CY`). The placement was measured over slot E (Recon
Bolt and Guiding Light); the same offset is read over C and Q, and a read
there `rests_on` that measurement. Over Skye's Q a numeral sits further
right [domain:hud/ability-tray-restock-countdown]; this read does not search
there.

**The read, soft until the cut.** Every candidate string (`NUMERALS`: tenths
0.1 to 0.9 and whole numbers 1 to 100, the largest seen above a slot) is
rendered at `PHASES` x `PHASES` sub-pixel phases into one common box, centred,
so ink beside a short numeral counts against it: '9' does not read inside
'49'. The slot's whiteness (`killfeed_numeral.slot_whiteness`) is scored
against every candidate and phase at every placement in one matrix product
(`killfeed_numeral.fit_scores`); the empty template scores 0. A numeral reads
at `READ_MIN_SCORE` with `READ_MIN_MARGIN` over the next candidate, the empty
one included; the empty read needs every candidate at most `EMPTY_MAX_SCORE`.
Otherwise the numeral is None with its reason. The candidate set is the full
set, not a prediction from the spend: the read is scored against the gold
returns, so it must not rest on the spend's time.

**Against the returns.** On the 21 Riot-paired sessions the half classes
showed [metric:tray_countdown/returns@riot-21#gold_rises=130] gold rises, a read came within 3 s
before [metric:tray_countdown/returns@riot-21#watched=70] of them, and the last read was under one
second on [metric:tray_countdown/returns@riot-21#last_read_under_1s_within_1s=46]. Of the
[metric:tray_countdown/returns@riot-21#live_returns_watched=14] the state model calls live returns
(Recon Bolt and Guiding Light, the player's own kit) the last read was under
one second on [metric:tray_countdown/returns@riot-21#live_returns_last_read_under_1s_within_1s=12],
and the numeral's zero fell inside the return's sample interval on
[metric:tray_countdown/returns@riot-21#live_returns_agree_interval=11]. The other rises are other
kits' gold, spectated kits, and a second Guiding Light charge returning while
the numeral counted the first spend's ('27' on c62c2b06bcfb at 215.5 s): the
numeral is not a clock for every gold rise.

**The opportunity.** A slot is read only where the read can find a numeral:
a C, Q or E slot one of whose halves reads empty (`tray.segment_index`), so
the slot is empty or partly spent, and whose numeral box is lit (its
brightest whiteness at `LIT_MIN` or more).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from . import killfeed_numeral as kn
from . import tray

#: The font file, relative to the store root. Game files stay in the store.
FONT_RELPATH = ("reference/game-files/release-13.06-shipping-18-5590001/fonts/"
                "ShooterGame/Content/UI/Fonts/FinalFonts/DINNext_Regular.ttf")
#: The em at 1080p: 12 points at Slate's 96/72 px per point.
FONT_PT = 12.0
FONT_PX = FONT_PT * kn.SLATE_PX_PER_PT
#: Sub-pixel phases per axis, as the killfeed numeral.
PHASES = kn.PHASES
#: The candidate strings: tenths below one second, whole numbers above.
NUMERALS = tuple(f"0.{d}" for d in range(1, 10)) + tuple(str(n) for n in range(1, 101))
#: The empty read.
EMPTY = ""
#: The numeral's centre less the slot's centre (x), and its row, at 1080p.
NUMERAL_DX = 36.0
NUMERAL_CY = 980.5
#: The search about that centre, px either side.
SEARCH_X, SEARCH_Y = 2, 2
#: Empty px about the widest candidate's ink in the common box.
PAD_X, PAD_Y = 4, 1
#: The slots read: the ult's bar holds pips and draws no restock.
READ_SLOTS = tray.SLOT_KEYS[:3]
#: The least whiteness the numeral box's brightest pixel needs for a read.
LIT_MIN = 0.6
#: A numeral read needs this score and this margin over the next candidate.
READ_MIN_SCORE = 0.5
READ_MIN_MARGIN = 0.1
#: An empty read needs every candidate's score at most this.
EMPTY_MAX_SCORE = 0.0

REFUSE_NO_FONT = "no_font"
REFUSE_WEAK = "weak_fit"
REFUSE_AMBIGUOUS = "ambiguous"


def font_path(store_root) -> Path:
    """The game font, in the store's game-file reference."""
    return Path(store_root) / FONT_RELPATH


def store_font(store_root) -> str | None:
    """The font's path when the store holds it, else None (reads refuse `no_font`)."""
    p = font_path(store_root)
    return str(p) if p.is_file() else None


@lru_cache(maxsize=2)
def templates(font_file: str) -> np.ndarray:
    """(len(NUMERALS) * PHASES**2, h, w) float32: every candidate at every
    sub-pixel phase, centred in one box that holds the widest candidate's
    ink with `PAD_X`, `PAD_Y` empty px about it. Rendered once per font."""
    inks = [[kn._ink(text, font_file, FONT_PX, i / PHASES, j / PHASES)
             for j in range(PHASES) for i in range(PHASES)] for text in NUMERALS]
    boxes = []
    for stack in inks:
        s = np.stack(stack)
        ys, xs = np.nonzero((s > 0.02).any(axis=0))
        boxes.append(s[:, ys.min():ys.max() + 1, xs.min():xs.max() + 1])
    h = max(b.shape[1] for b in boxes) + 2 * PAD_Y
    w = max(b.shape[2] for b in boxes) + 2 * PAD_X
    out = np.zeros((len(NUMERALS), PHASES * PHASES, h, w), np.float32)
    for n, b in enumerate(boxes):
        y0, x0 = (h - b.shape[1]) // 2, (w - b.shape[2]) // 2
        out[n, :, y0:y0 + b.shape[1], x0:x0 + b.shape[2]] = b
    return out.reshape(-1, h, w)


def value_s(numeral: str | None) -> float | None:
    """The seconds a read numeral states, or None."""
    return None if not numeral else float(numeral)


def _numeral_box(slot: str, temps: np.ndarray) -> tuple[int, int, int, int]:
    """The search window (x0, y0, x1, y1) of `slot` at 1080p."""
    th, tw = temps.shape[1:]
    cx = tray.SLOT_X0 + tray.SLOT_DX * tray.SLOT_KEYS.index(slot) + NUMERAL_DX
    x0 = int(np.floor(cx - tw / 2.0)) - SEARCH_X
    y0 = int(np.floor(NUMERAL_CY - th / 2.0)) - SEARCH_Y
    return x0, y0, x0 + tw + 2 * SEARCH_X, y0 + th + 2 * SEARCH_Y


def opportunity(halves) -> list[str]:
    """The slots worth reading on one sample: C, Q or E with a half read
    empty (`halves`: the sample's 4 x 2 class indices, `tray.segment_index`)."""
    h = np.asarray(halves)
    return [s for k, s in enumerate(READ_SLOTS) if (h[k] == tray.SEG_CLASSES.index("empty")).any()]


def read_slot(frame: np.ndarray, slot: str, temps: np.ndarray) -> dict | None:
    """The numeral over `slot` in `frame` (1920x1080 BGR), or None where its
    box is not lit (`LIT_MIN`): no read. Scores every candidate and phase at
    every placement in one product, cuts once."""
    x0, y0, x1, y1 = _numeral_box(slot, temps)
    white = kn.slot_whiteness(frame[y0:y1, x0:x1])
    if float(white.max()) < LIT_MIN:
        return None
    sc, _best = kn.fit_scores(white, temps)                   # (n * phases, py, px)
    n = len(NUMERALS)
    flat = sc.reshape(n, PHASES * PHASES, -1)
    per = flat.max(axis=(1, 2))                                 # best per candidate
    order = np.argsort(-per)
    top, second = int(order[0]), int(order[1])
    s1, s2 = float(per[top]), float(per[second])
    scores = {EMPTY: 0.0, NUMERALS[top]: round(s1, 4), NUMERALS[second]: round(s2, 4)}
    if s1 <= EMPTY_MAX_SCORE:
        numeral, why, best, runner, score, margin = EMPTY, None, EMPTY, NUMERALS[top], 0.0, -s1
    else:
        runner_s = max(s2, 0.0)
        best, score = NUMERALS[top], s1
        runner = NUMERALS[second] if s2 > 0.0 else EMPTY
        margin = s1 - runner_s
        numeral, why = ((None, REFUSE_WEAK) if s1 < READ_MIN_SCORE
                        else (None, REFUSE_AMBIGUOUS) if margin < READ_MIN_MARGIN
                        else (best, None))
    k = int(np.argmax(flat[top].max(axis=1)))
    p = int(np.argmax(flat[top, k]))
    py, px = divmod(p, sc.shape[2])
    th, tw = temps.shape[1:]
    return {"slot": slot, "numeral": numeral, "value_s": value_s(numeral), "reason": why,
            "best": best, "runner_up": runner, "score": round(score, 4),
            "margin": round(float(margin), 4), "scores": scores,
            "at": {"x": round(x0 + px + tw / 2.0, 2), "y": round(y0 + py + th / 2.0, 2),
                   "phase": [k % PHASES, k // PHASES]},
            "rests_on": [{"prior": "placement_measured_on_slot_E", "dx": NUMERAL_DX,
                          "cy": NUMERAL_CY}]}


def read_sample(frame: np.ndarray, halves, font_file: str | None) -> list[dict]:
    """The reads of one sample: each slot `opportunity` names whose box is
    lit, or a `no_font` refusal per such slot where the store holds no font."""
    slots = opportunity(halves)
    if not slots:
        return []
    if font_file is None:
        return [{"slot": s, "numeral": None, "value_s": None, "reason": REFUSE_NO_FONT}
                for s in slots]
    temps = templates(font_file)
    return [r for s in slots if (r := read_slot(frame, s, temps)) is not None]


def gold_rises(ts_ms, halves, real, step_s: float) -> list[dict]:
    """The samples at which a C, Q or E slot shows more gold halves than the
    sample before it, both samples' halves all readable and one grid step
    apart within a span (`real`), as `{"slot", "t_ms", "t_before_ms"}`: the
    returns `score_against_returns` dates. `halves` are class indices
    (n x 4 x 2, `tray.segment_index`)."""
    ts = np.asarray(ts_ms, float)
    h = np.asarray(halves)[:, :len(READ_SLOTS)]
    real = np.asarray(real, bool)
    gold = (h == tray.SEG_CLASSES.index("gold")).sum(axis=2)
    ok = (h < len(tray.SEG_CLASSES)).all(axis=2) & real[:, None]
    near = np.diff(ts) <= 1000.0 * step_s * 1.1
    rise = ok[1:] & ok[:-1] & near[:, None] & (gold[1:] > gold[:-1])
    return [{"slot": READ_SLOTS[k], "t_ms": float(ts[i + 1]), "t_before_ms": float(ts[i])}
            for i, k in zip(*np.nonzero(rise))]


def score_against_returns(reads: list[dict], returns: list[dict]) -> list[dict]:
    """Each gold return (`{"slot", "t_ms", "t_before_ms"}`: the first sample
    a gold half shows and the last sample before it) against the slot's last
    read numeral before it. A numeral v drawn at t says the return lies in
    (t + v - unit, t + v], the unit a second for whole numbers and a tenth
    below one second; the return lies in (`t_before_ms`, `t_ms`]. `agrees`
    where the two intervals meet, and `lag_ms` is the first gold sample less
    t + v. Pure over stored rows."""
    out = []
    for g in returns:
        prior = [r for r in reads if r["slot"] == g["slot"] and r.get("value_s") is not None
                 and r["t_ms"] < g["t_ms"]]
        if not prior:
            out.append({**g, "read": None, "zero_ms": None, "lag_ms": None, "agrees": None})
            continue
        last = max(prior, key=lambda r: r["t_ms"])
        v = float(last["value_s"])
        hi = last["t_ms"] + 1000.0 * v
        lo = hi - (1000.0 if v >= 1.0 else 100.0)
        out.append({**g, "read": {k: last[k] for k in ("t_ms", "numeral", "value_s")},
                    "zero_ms": [lo, hi], "lag_ms": g["t_ms"] - hi,
                    "agrees": lo < g["t_ms"] and hi > g["t_before_ms"]})
    return out
