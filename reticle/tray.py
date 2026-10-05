r"""Read the ability tray: each slot's charge fill, and the drops between samples.

    .\.venv\Scripts\python.exe -m reticle tray <session>     (stored crops, no decode)

Owns [owns:tray-drop].

Ported from `prototypes/ability_hud.py` (geometry, colour, guard rows, fills,
drops and the co-occurrence flag), whose docstring holds the measurements
behind every constant, with one change: a drop across a cast's flash (below); `prototypes/tray_suspect_reasons.py` measured the drops
on the match sessions and `prototypes/label_tray_objects.py` asked the player
what each gated drop drew. A charge bar falling between samples is a spent
charge, as `ammo_mag` falling is a shot.

Geometry, at 1920x1080. Teal charge bars sit on y 1032-1051 at a 113 px pitch,
slot k centred at SLOT_X0 + SLOT_DX * k for C, Q, E and X. The tray is anchored
to the screen edge, so the 16:9 profiles share it. Slot X's ult pips desaturate
with the bar, so the same mask reads the ult.

A reading, and the one never guessed. A fill is a slot's teal count over that
session's p90 clean count, so the tray's composited scenery cancels. Every slot
near zero means the tray is not drawn (death screen, buy menu, settings), and
the row is refused rather than read as no charges. A green screen effect that
floods the guard rows above and below the bar refuses the frame.

A cast's own animation. Sova's bow glows cyan over the tray while a bolt is
drawn (`75a55a296d3b` 337.1 s), flooding the guard rows on the sample where the
charge falls, and the prototype never compared across a refused sample, so the
cast disappeared: 202 falls on the 19 match sessions, 64 of them Sova's Recon
Bolt and 33 Shock Bolt, against 31 Recon Bolt casts stored (`tray-guard-gap`
in the store's `notes/predictions.jsonl`). Across refused samples that still
show the tray, the last clean sample is compared with the next one if it comes
within GAP_S, and the drop says `across_gap`.

A bridged drop beside a direct one. The glow also lifts a neighbouring bar on
a clean sample and fades, which reads as a direct drop within SUSPECT_S of
the bridged one, and co-occurrence refuses it. Bridging refuses
[metric:tray/bridged-partner@all-sessions#direct_refused_by_bridged=6] direct
drops the gate kept without it, and by eye all
[metric:tray/bridged-partner@all-sessions#direct_refused_glow_by_eye=6] are
the glow on a bar whose level never changed. At `75a55a296d3b` 274.1 s the Q
bar holds one segment throughout, and a streak lifts it to
[metric:tray/bridged-partner@all-sessions#q_75a55a296d3b_273_567_from=1.03]
on one sample before it reads
[metric:tray/bridged-partner@all-sessions#q_75a55a296d3b_274_067_to=0.47]
again. So a bridged drop keeps its vote. It carries the time of the next
clean sample: that Recon Bolt emptied E at
[metric:tray/bridged-partner@all-sessions#e_75a55a296d3b_fell_at_s=273.067] s
and is stamped
[metric:tray/bridged-partner@all-sessions#e_75a55a296d3b_stamped_s=273.567] s.

Two charges. An ability with two charges draws its bar as two segments
[domain:hud/ability-tray-charge-segments], so the fill reads 1.0, 0.5 and 0,
and a spent charge falls by 0.5, above CAST_DROP; no charge count per
ability is needed. The four two-charge slots on the 19 lineup sessions gave
[metric:tray/segments@all-sessions#half_from_full=89] drops from full to half
and [metric:tray/segments@all-sessions#empty_from_half=43] from half to empty.
A drop that leaves the slot at its full level
([metric:tray/segments@all-sessions#full_after=68] of 493 accepted) is added
teal released, an ability equipped and not used (player, 2026-09-27); the
cast owner (`ability_timeline.player_tray_casts`) decides what a drop is.

The bar's colour, by halves. A charge that comes back during the round is
drawn gold, not teal [domain:hud/ability-tray-restocked-charge-gold], so the
teal count never rises for it. `segment_scores` scores each half of each bar
softly against teal, gold and the empty bar's grey, and `segment_classes`
cuts once: a half is teal, gold, empty or unreadable (a streak or flash over
the bar). The fills stay teal (TRAY_FILL_VERSION); the classes carry
their own stamp (TRAY_SEGMENT_VERSION) and are stored as run-length
`segments` rows (`segment_runs`), which the state model reads to count a gold
charge and to tell a returned charge from a streak.

Drops by halves (TRAY_VERSION 0.2.0). Spending a gold charge moves no teal,
so a drop read from the fill alone missed it, and the state model saw a
gold half fall with no drop. A drop now also fires where a C, Q or E half
read teal or gold goes empty (`_events`), and its row names what fired it
(`by`) and both samples' half classes as evidence. The classes also keep an
all-spent tray drawn (`drawn_mask`), where the teal fill read it as not
drawn and hid the gold return onto it. On the 21 Riot-paired sessions,
against Riot's per-player cast counts and through the unchanged gate, the
player's own casts covered
[metric:tray/half-drops@riot-21#covered_before=500] of
[metric:tray/half-drops@riot-21#riot_casts=610] before and
[metric:tray/half-drops@riot-21#covered_after=526] after, with
[metric:tray/half-drops@riot-21#excess_before=5] and
[metric:tray/half-drops@riot-21#excess_after=8] casts beyond Riot's counts;
two of the three new ones are gold falls on Skye's Regrowth, a resource bar
[domain:abilities/skye-regrowth-resource-bar].

A witness for gold (TRAY_VERSION 0.3.0). Recall is scored per ability as the
lesser of our count and Riot's, so a false cast that fills a missed one
scores as a gain, and two of the gold-only drops behind that gain were
bright objects behind an empty bar. A drop by gold halves alone now fires
only where the restock countdown or the slot icon saw the spend
(`gold_witness`); the refused ones are stored as `unwitnessed_drop` rows.
Of the [metric:tray/gold-witness@riot-21#gold_only_gate_passed=14] gold-only drops the gate passed on the
21 Riot-paired sessions, the witness kept [metric:tray/gold-witness@riot-21#gate_passed_witnessed=8], each a
gold charge going empty by eye, and refused
[metric:tray/gold-witness@riot-21#gate_passed_refused=6]: the [metric:tray/gold-witness@riot-21#eye_refused_false=2] misreads and
[metric:tray/gold-witness@riot-21#eye_refused_real=4] real spends of a gold Phoenix charge beside a teal
one, which leave the icon lit and draw no numeral. The player's casts
covered [metric:tray/gold-witness@riot-21#covered_after=521] of [metric:tray/gold-witness@riot-21#riot_casts=610], with
[metric:tray/gold-witness@riot-21#excess_after=8] beyond Riot's counts.

Persistence as a third witness (TRAY_VERSION 0.4.0). A cream half is a
charge partly spent or recharged [domain:hud/ability-tray-gold-charge-meaning],
and Phoenix spends one beside a teal half with no numeral and the icon lit,
so the countdown and icon witnesses refused
[metric:tray/gold-persist@riot-21#eye_refused_real_before=4] real Curveball
spends. A misread is a sample long; a held charge is not. A gold-only drop now
also fires where the spent half read gold on GOLD_PERSIST_MIN readable samples
in a row before it (`persisted`). On the 21 Riot-paired sessions it admitted
[metric:tray/gold-persist@riot-21#newly_admitted=16] of the
[metric:tray/gold-persist@riot-21#refused_before=20] refused drops; the gate
passed the four Curveball spends and refused the rest, of which
[metric:tray/gold-persist@riot-21#admitted_kit_or_round_switch=8] are by eye
the tray switching kits or rounds over a real gold half, a transition the
gate owns. Own casts covered
[metric:tray/gold-persist@riot-21#covered_after=525] of 610 with
[metric:tray/gold-persist@riot-21#excess_after=8] beyond Riot's counts; k was
chosen on the same drops, so the figures are in-sample.

What a drop is not. A drop is a transition, not a cast: after the player dies
the tray shows a spectated teammate's kit, and its switch reads as several
slots emptying at once. `casts` flags a drop that lands on the first refused
frame after a drawn one (`forced`) or co-occurs with another slot's drop within
SUSPECT_S. Which drops are the player's casts is `ability_timeline`'s question.
"""
from __future__ import annotations

import cv2
import numpy as np

#: Measured at 1920x1080. Slot 3 is the ultimate.
SLOT_X0, SLOT_DX = 789, 113
BAR_Y0, BAR_Y1 = 1032, 1052
BAR_HALF = 38
SLOT_KEYS = ("C", "Q", "E", "X")
#: The tray's teal, drawn brighter than an ally ring.
TEAL_H = (70, 100)
TEAL_S_MIN, TEAL_V_MIN = 80, 120
#: Below this fraction of the slot's reference on EVERY slot, the tray is not drawn.
DRAWN_MIN_FRAC = 0.12
#: Rows just above and below the bar; as teal as the bar means the world is teal.
GUARD_Y = ((1008, 1028), (1056, 1076))
GUARD_MAX_RATIO = 0.6
#: A fall of this much of a slot's reference between samples is a spent charge.
CAST_DROP = 0.25
#: Two slots dropping within this window is the tray changing whose it is.
SUSPECT_S = 1.5
#: The longest run of refused but drawn samples a comparison bridges. The bow
#: glows for as long as Sova aims; the falls across such runs number 166, 186,
#: 202, 206 and 209 at limits of 1.5, 2, 3, 5 and 10 s, so 3 s is fitted there.
GAP_S = 3.0
#: A gold-only drop's witness (`gold_witness`): the window after the drop in
#: which the countdown must show or the icon dim, and the window before the
#: gold sample whose last numeral a restart must exceed.
WITNESS_AFTER_S = 1.5
WITNESS_BEFORE_S = GAP_S
#: The slot icon's brightness (`tray_icons.slot_brightness`: the patch's 95th
#: percentile grey, 0-255) at which it is lit, and at or below which it is
#: dim. On the 14 gold-only drops the gate passed on the 21 Riot-paired
#: sessions, the icon on the gold sample read
#: [metric:tray/gold-witness@riot-21#icon_on_gold_real_min=237] or more on the
#: twelve real spends and at most
#: [metric:tray/gold-witness@riot-21#icon_on_gold_false_max=136] on the two
#: misread empty bars; on the slots spent to empty it fell to
#: [metric:tray/gold-witness@riot-21#icon_dimmed_after_max=135] or less within
#: 1.5 s.
ICON_LIT_MIN = 200.0
ICON_DIM_MAX = 160.0
#: The persistence witness (`gold_witness`, `_gold_runs`): the fewest
#: consecutive readable samples on which the spent half read gold, ending at
#: its gold sample. Chosen in-sample on the
#: [metric:tray/gold-persist@riot-21#gold_only_candidates=83] gold-only drops of
#: the 21 Riot-paired sessions as one more than the longest run of a gold
#: reading false by eye: the four such misreads (a warm flash or a bright
#: object behind an empty bar) each read gold on
#: [metric:tray/gold-persist@riot-21#false_reading_run_max=1] sample, and the
#: shortest real cream spend the other witnesses refused read gold on
#: [metric:tray/gold-persist@riot-21#real_refused_run_min=2]
#: (ff636d173b07 1052.5 s).
GOLD_PERSIST_MIN = 2


#: The strip `slot_counts` reads: the four bars and their guard rows, from the
#: geometry above. The tray module reads 1920x1080 only, so nothing scales.
STRIP_Y = (min(BAR_Y0, *(a for a, _ in GUARD_Y)), max(BAR_Y1, *(b for _, b in GUARD_Y)))
STRIP_X = (SLOT_X0 - BAR_HALF, SLOT_X0 + SLOT_DX * (len(SLOT_KEYS) - 1) + BAR_HALF)

#: The bar's halves, read by colour (`segment_scores`). The core of each half:
#: rows 1041-1049 and 4 to 26 px either side of the slot centre, inside the
#: trapezoid's narrowest row and clear of the gap between two segments.
SEG_Y = (1041, 1050)
SEG_DX = (4, 26)
#: The classes a half is scored against, and their colour in CIE Lab (L 0-100).
#: Teal and gold are the medians of the halves' median colour on the drawn,
#: clean samples of seven sessions (3694746e4e54, a06f04a0059f, bdfdcf009dba,
#: 96aa1ae9b96f, e37fdeca944f, bfad2778a372, 9acf02f98283; 103,572 halves),
#: whose (a, b) histogram holds three clusters: teal (72,735 halves, p5 to p95
#: within one unit), gold (the returned charge
#: [domain:hud/ability-tray-restocked-charge-gold]) and the empty bar's grey.
#: The empty bar is translucent: over orange, sand or blue scenery it takes
#: the tint (L 55-82, b up to 14), so its centre sits at the grey's middle and
#: its spread is wide. Swept on five sessions' 11,735 drawn samples, the
#: grey's spread (L, a, b) of (14, 7, 7) left 5.3% of C, Q and E halves
#: unreadable, (18, 10, 10) 2.0% and (20, 12, 12) 1.4%; the gold count (1,360
#: halves) and the halves whose teal disagrees with the fill (36 of 35,149
#: unequipped slot-samples) did not move.
SEG_CLASSES = ("teal", "gold", "empty")
SEG_LAB = np.array([[90.7, -55.7, 22.2], [91.3, -2.3, 25.7], [68.0, 2.0, 4.0]], np.float32)
#: Each class's spread per Lab axis: a pixel's membership is
#: exp(-0.5 * sum(((lab - centre) / sigma) ** 2)), so a pixel one sigma off on
#: every axis keeps 0.22.
SEG_SIGMA = np.array([[10.0, 10.0, 10.0], [10.0, 8.0, 8.0], [20.0, 12.0, 12.0]], np.float32)
#: The scenery rows just above the bar, and the lightness (Lab L) at which
#: gold is half believed. The empty bar is translucent, so a bright warm
#: flash behind it reads as gold: on 043bafca271a 940.5 s and c40d950031bb
#: 900.0 s and 901.5 s an explosion lit the scenery above slot E to L 87-99
#: while its countdown still ran, and the empty halves scored gold 0.54-0.72;
#: above the six returned charges cropped by hand the scenery read L 2-48
#: and the gold 0.95-0.99. Gold is weighed by a logistic in that lightness
#: (`SEG_GUARD_SPAN` wide), as the guard rows refuse a teal-flooded frame.
SEG_GUARD_Y = (1030, 1037)
SEG_GUARD_L = 80.0
SEG_GUARD_SPAN = 5.0
#: The least winning score (a half's mean membership) read as a class; below
#: it the half is `unreadable` (a screen streak or flash over the bar).
SEG_MIN = 0.5
SEG_UNREADABLE = "unreadable"


def _half_columns() -> np.ndarray:
    """The frame columns of the eight half cores, slot by slot, left then right."""
    w = np.arange(SEG_DX[0], SEG_DX[1] + 1)
    return np.concatenate([c for k in range(len(SLOT_KEYS))
                           for c in (SLOT_X0 + SLOT_DX * k - w[::-1], SLOT_X0 + SLOT_DX * k + w)])


_SEG_COLS = _half_columns()
_SEG_X = (int(_SEG_COLS.min()), int(_SEG_COLS.max()) + 1)


def segment_scores(frame: np.ndarray) -> np.ndarray:
    """Each bar half's soft score against `SEG_CLASSES`: a (4, 2, 3) array of
    slot x half (left, right) x class, each the mean over the half's core of
    the pixels' membership (`SEG_SIGMA`). Nothing is thresholded before the
    mean; `segment_classes` cuts once, at the decision. Reads the cores as
    float Lab, with no resample."""
    strip = frame[SEG_GUARD_Y[0]:SEG_Y[1], _SEG_X[0]:_SEG_X[1]]
    both = np.ascontiguousarray(strip[:, _SEG_COLS - _SEG_X[0]], dtype=np.float32)
    lab = cv2.cvtColor(both * np.float32(1.0 / 255.0), cv2.COLOR_BGR2Lab)
    guard, lab = lab[:SEG_GUARD_Y[1] - SEG_GUARD_Y[0]], lab[SEG_Y[0] - SEG_GUARD_Y[0]:]
    z = (lab[None, :, :, :] - SEG_LAB[:, None, None, :]) / SEG_SIGMA[:, None, None, :]
    member = np.exp(-0.5 * np.einsum("cyxk,cyxk->cyx", z, z)).mean(axis=1)  # (class, column)
    out = member.reshape(len(SEG_CLASSES), len(SLOT_KEYS), 2, -1).mean(axis=-1).transpose(1, 2, 0)
    # The scenery above each half: bright scenery behind the translucent empty
    # bar reads as gold, so gold is weighed by how dim the scenery is.
    light = guard[:, :, 0].mean(axis=0).reshape(len(SLOT_KEYS), 2, -1).mean(axis=-1)
    out[:, :, 1] /= 1.0 + np.exp((light - SEG_GUARD_L) / SEG_GUARD_SPAN)
    return out


def segment_index(scores) -> np.ndarray:
    """The class index of each half (into `SEG_CLASSES`, `len(SEG_CLASSES)`
    for `unreadable`) from `segment_scores`, over any leading axes: the
    best-scoring class at `SEG_MIN` or more. The one cut."""
    scores = np.asarray(scores)
    return np.where(scores.max(axis=-1) >= SEG_MIN, scores.argmax(axis=-1), len(SEG_CLASSES))


def segment_classes(scores) -> list:
    """The class name of each half from `segment_scores` (`segment_index`):
    nested lists in the scores' leading shape, one sample's (4, 2, 3) or many
    samples' (n, 4, 2, 3) at once."""
    return _SEG_NAMES[segment_index(scores)].tolist()


_SEG_NAMES = np.array(SEG_CLASSES + (SEG_UNREADABLE,))
_TEAL, _GOLD, _EMPTY = (SEG_CLASSES.index(c) for c in ("teal", "gold", "empty"))
#: The slots whose halves are charges; the ult's bar holds pips.
_CHARGE_SLOTS = 3
#: The half classes whose going empty is a drop by halves (`_events`).
HALF_DROP_FROM = ("teal", "gold")
_HALF_DROP_FROM = np.array([SEG_CLASSES.index(c) for c in HALF_DROP_FROM])


def segment_runs(ts_ms, scores: np.ndarray, real) -> list[dict]:
    """The half classes as stored rows: per slot, one `segments` row per run of
    real samples whose two halves keep their classes, with the run's median
    score per class and half and its least winning score per half. `scores`
    are `segment_scores` per sample (n x 4 x 2 x 3); a sample whose `real` is
    False (a span separator) ends every run. The classes per sample are
    recoverable from the runs; the scores are summarised."""
    ts = np.asarray(ts_ms, float)
    real = np.asarray(real, bool)
    sc = np.asarray(scores, float).reshape(len(ts), len(SLOT_KEYS), 2, len(SEG_CLASSES))
    pick = np.where(sc.max(axis=-1) >= SEG_MIN, sc.argmax(axis=-1), len(SEG_CLASSES))
    out = []
    for k, slot in enumerate(SLOT_KEYS):
        key = np.where(real, pick[:, k, 0] * 8 + pick[:, k, 1], -1)
        cut = np.flatnonzero(np.diff(key)) + 1
        for a, b in zip(np.r_[0, cut], np.r_[cut, len(key)]):
            if key[a] < 0:
                continue
            run = sc[a:b, k]
            win = run.max(axis=-1)
            out.append({"kind": "segments", "slot": slot, "t_first_ms": float(ts[a]),
                        "t_last_ms": float(ts[b - 1]), "samples": int(b - a),
                        "halves": _SEG_NAMES[pick[a, k]].tolist(),
                        "score_median": {c: np.round(np.median(run[:, :, i], axis=0), 3).tolist()
                                         for i, c in enumerate(SEG_CLASSES)},
                        "win_min": np.round(win.min(axis=0), 3).tolist()})
    out.sort(key=lambda r: (r["t_first_ms"], SLOT_KEYS.index(r["slot"])))
    return out


def slot_counts(frame: np.ndarray) -> tuple[list[int], bool]:
    """Teal pixel count per charge bar, and whether the frame is trustworthy
    (no screen-wide green bleeding into the guard rows).

    Crops the strip (`STRIP_Y`, `STRIP_X`) before converting: converting and
    masking the whole frame to read 68 rows cost 8 ms a sample."""
    y0, x0 = STRIP_Y[0], STRIP_X[0]
    hsv = cv2.cvtColor(np.ascontiguousarray(frame[y0:STRIP_Y[1], x0:STRIP_X[1]]),
                       cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    teal = ((h > TEAL_H[0]) & (h < TEAL_H[1]) & (s > TEAL_S_MIN) & (v > TEAL_V_MIN))
    out, bleed = [], 0.0
    for k in range(4):
        cx = SLOT_X0 + SLOT_DX * k - x0
        sl = slice(cx - BAR_HALF, cx + BAR_HALF)
        out.append(int(teal[BAR_Y0 - y0:BAR_Y1 - y0, sl].sum()))
        bar = teal[BAR_Y0 - y0:BAR_Y1 - y0, sl].mean()
        g = max(teal[a - y0:b - y0, sl].mean() for a, b in GUARD_Y)
        if bar > 0.05:
            bleed = max(bleed, g / bar)
    return out, bleed <= GUARD_MAX_RATIO


def fills(counts: np.ndarray, clean: np.ndarray | None = None) -> np.ndarray:
    """Counts over each slot's p90 non-trivial clean count. The p90, not the
    maximum: one green flash once doubled the maximum."""
    if not len(counts):
        return counts
    ref = np.ones(counts.shape[1])
    for k in range(counts.shape[1]):
        col = counts[:, k]
        sel = col[clean] if clean is not None and clean.any() else col
        sel = sel[sel > 0.05 * max(col.max(), 1.0)]
        ref[k] = np.percentile(sel, 90) if len(sel) else 1.0
    return counts / np.maximum(ref, 1.0)


def drawn(f_row: np.ndarray, halves=None, icons=None) -> bool:
    """Is the tray rendered at all? Refuses rather than reporting zero charges.
    `halves` are the sample's half class indices (`segment_index`, 4 x 2) and
    `icons` whether its slot icons were read; without both the teal fill
    decides alone (`drawn_mask`)."""
    f_row = np.asarray(f_row, float)[None]
    return bool(drawn_mask(f_row, None if halves is None else np.asarray(halves)[None],
                           None if icons is None else np.asarray([icons], bool))[0])


def halves_readable(halves) -> np.ndarray:
    """Per sample: every C, Q and E half reads as teal, gold or empty
    (`halves`: n x 4 x 2 class indices). The samples whose slot icons
    `drawn_mask` asks for, where the teal fill finds no tray."""
    return (np.asarray(halves)[:, :_CHARGE_SLOTS] < len(SEG_CLASSES)).all(axis=(1, 2))


def drawn_mask(f: np.ndarray, halves=None, icons=None) -> np.ndarray:
    """`drawn` per sample: some slot's teal fill above `DRAWN_MIN_FRAC`, or
    every C, Q and E half read as the bar's own class (`halves_readable`)
    while the slot icons witness the tray (`icons`, n booleans).

    An all-spent tray (C, Q and E empty, the ult dark) holds no teal, and a
    tray of returned charges only gold, so the fill calls both undrawn and
    hides a gold return (3694746e4e54 778.5-828.5 s). Their halves read as
    the bar's classes. The halves alone are not enough: the empty bar is
    translucent and its class wide, so bright, even scenery behind an
    undrawn tray (the death camera) reads empty on all six halves. On the 21
    Riot-paired sessions the halves added
    [metric:tray/drawn-icons@riot-21#halves_gained=3229] drawn samples, and the slot
    icons (`tray_icons`, any agent's at `tray_kit.SLOT_READ_MIN` on
    `tray_kit.MIN_READ_SLOTS` slots) read on
    [metric:tray/drawn-icons@riot-21#icons_on_gained=3137] of them. By eye
    [metric:tray/drawn-icons@riot-21#eye_no_icons_drawn=2] of
    [metric:tray/drawn-icons@riot-21#eye_no_icons_checked=10] gained samples without
    icons showed a tray, and
    [metric:tray/drawn-icons@riot-21#eye_icons_drawn=16] of
    [metric:tray/drawn-icons@riot-21#eye_icons_checked=16] with icons did. Icons read on
    [metric:tray/drawn-icons@riot-21#icons_on_fill_drawn=1246] of
    [metric:tray/drawn-icons@riot-21#fill_drawn_sampled=1260] samples the fill calls
    drawn and on [metric:tray/drawn-icons@riot-21#icons_on_neither=131] of
    [metric:tray/drawn-icons@riot-21#neither_sampled=1260] that neither rule does.
    `halves` without `icons` adds nothing."""
    f = np.asarray(f, float)
    out = (f > DRAWN_MIN_FRAC).any(axis=1)
    if halves is not None and icons is not None:
        out |= halves_readable(halves) & np.asarray(icons, bool)
    return out


def _compare_pairs(ts, dr: np.ndarray, clean: np.ndarray) -> tuple:
    """The samples a drop compares: (earlier, later) index arrays. A drawn,
    clean sample is compared with the last such sample before it, unless an
    undrawn sample came between (a gap is not a drop) or refused samples that
    still show the tray (a flash over it) came between and the two lie more
    than GAP_S apart. An undrawn sample is compared too, where it is clean,
    and ends the run: a slot emptying on the first undrawn sample after a
    drawn one is still a drop, flagged `forced`."""
    ts = np.asarray(ts, float)
    n = len(ts)
    idx = np.arange(n)

    def last_before(m):
        a = np.maximum.accumulate(np.where(m, idx, -1)) if n else idx
        return np.r_[-1, a[:-1]] if n else a

    good = dr & clean
    p = last_before(good)
    near = (p > last_before(~dr)) & (
        (last_before(dr & ~clean) < p) | (ts - ts[np.maximum(p, 0)] <= GAP_S))
    later = np.flatnonzero(near & clean)
    return p[later], later


def _held_halves(ts, h: np.ndarray, good: np.ndarray, dr: np.ndarray) -> tuple:
    """(held, src): each sample's half classes, an unreadable half holding its
    class from the last drawn, clean sample that read it, at most GAP_S
    earlier and with no undrawn sample between, else unreadable; and the
    index of the sample each held class was read on (-1 where none).
    `_events` holds gold only."""
    n = len(h)
    flat = np.asarray(h).reshape(n, -1)
    idx = np.arange(n)
    ok = (flat < len(SEG_CLASSES)) & good[:, None]
    last = np.maximum.accumulate(np.where(ok, idx[:, None], -1), axis=0)
    reset = np.maximum.accumulate(np.where(~dr, idx, -1))
    ts = np.asarray(ts, float)
    src = np.maximum(last, 0)
    valid = (last > reset[:, None]) & (ts[:, None] - ts[src] <= GAP_S)
    held = np.where(valid, np.take_along_axis(flat, src, axis=0), len(SEG_CLASSES))
    return held.reshape(h.shape), np.where(valid, src, -1).reshape(h.shape)


def _gold_runs(ts, h: np.ndarray, good: np.ndarray, dr: np.ndarray) -> np.ndarray:
    """Per sample and half, the length of the run of readable samples on
    which the half read gold, ending at that sample (0 where it does not read
    gold). A readable sample is clean and drawn (`good`) with the half read as
    teal, gold or empty; a sample where the half is unreadable is skipped. An
    undrawn sample, another class, or a gap of more than GAP_S between
    readable samples ends the run."""
    n = len(h)
    flat = np.asarray(h).reshape(n, -1)
    idx = np.arange(n)[:, None]
    ts = np.asarray(ts, float)
    readable = good[:, None] & (flat < len(SEG_CLASSES))
    gold = readable & (flat == _GOLD)
    cum = np.cumsum(gold, axis=0)
    prev = np.maximum.accumulate(np.where(readable, idx, -1), axis=0)
    prev = np.vstack([np.full((1, flat.shape[1]), -1), prev[:-1]])
    gap = readable & (prev >= 0) & (ts[:, None] - ts[np.maximum(prev, 0)] > GAP_S)
    hard = (readable & ~gold) | (~dr)[:, None]
    brk = hard | gap
    # A run counts the gold after a hard break, and from a gap break on.
    base = np.where(hard, cum, cum - gold)
    last = np.maximum.accumulate(np.where(brk, idx, -1), axis=0)
    floor = np.where(last >= 0, np.take_along_axis(base, np.maximum(last, 0), axis=0), 0)
    return np.where(gold, cum - floor, 0).reshape(h.shape)


def _events(ts, f: np.ndarray, clean: np.ndarray, halves=None, icons=None) -> list[dict]:
    """The drops between the compared samples (`_compare_pairs`), in time and
    slot order: a slot whose teal fill fell by `CAST_DROP` or more (`by` fill),
    and, where `halves` are given, a C, Q or E slot of which a teal or gold
    half (`HALF_DROP_FROM`) went empty (`by` halves). Each drop carries the
    sample indices and, with halves, both samples' half classes and the
    classes that went empty. `icons` are the slot icon witness `drawn_mask`
    reads. A drop by halves alone of which no teal half went empty is
    `gold_only`, and carries `g`, the sample its gold last read on: it fires
    only on a witness (`gold_witness`, `drops`), and carries `run`, the
    longest gold run (`_gold_runs`) of a spent gold half, ending at the
    sample its gold last read on.

    A gold half compares as it last read (`_held_halves`): Sova's bow glow
    leaves a half unreadable on the sample before the spend
    (3694746e4e54 830.5 s), and gold has no fill to fall across it. A teal
    half compares as the earlier sample read it: its spend lowers the fill,
    which the fill rule already compares across refused samples. On the 21
    Riot-paired sessions a teal half going empty added
    [metric:tray/half-drops@riot-21#teal_half_only_drops=0] drops the fill
    missed, and holding teal halves too added
    [metric:tray/half-drops@riot-21#teal_hold_extra_excess=46] casts beyond
    Riot's counts."""
    dr = drawn_mask(f, halves, icons)
    a, b = _compare_pairs(ts, dr, clean)
    by_fill = (f[a] - f[b]) >= CAST_DROP                        # (pairs, 4)
    by_half = np.zeros_like(by_fill)
    if halves is not None:
        h = np.asarray(halves)
        held, src = _held_halves(ts, h, dr & clean, dr)
        h_from = np.where(held == _GOLD, held, h)                # gold held, else as read
        g_from = np.where(held == _GOLD, src, np.arange(len(h))[:, None, None])
        runs = _gold_runs(ts, h, dr & clean, dr)
        went = (h[b] == _EMPTY) & np.isin(h_from[a], _HALF_DROP_FROM)  # (pairs, 4, 2)
        by_half[:, :_CHARGE_SLOTS] = went[:, :_CHARGE_SLOTS].any(axis=-1)
    out = []
    for j, k in zip(*np.nonzero(by_fill | by_half)):
        i, p = int(b[j]), int(a[j])
        ev = {"i": i, "p": p, "slot": SLOT_KEYS[k], "from": round(float(f[p, k]), 2),
              "to": round(float(f[i, k]), 2), "forced": not bool(dr[i]),
              "by": [w for w, on in (("fill", by_fill[j, k]), ("halves", by_half[j, k])) if on]}
        if halves is not None:
            hp, hi = h_from[p, k], h[i, k]
            spent = (hi == _EMPTY) & (hp < _EMPTY)
            ev.update({"halves_from": _SEG_NAMES[hp].tolist(),
                       "halves_to": _SEG_NAMES[hi].tolist(),
                       "spent_halves": _SEG_NAMES[hp[spent]].tolist()})
            if ev["by"] == ["halves"] and not (spent & (hp == _TEAL)).any():
                ev["gold_only"] = True
                gs = spent & (hp == _GOLD)
                ev["g"] = int(g_from[p, k][gs].max())
                ev["run"] = int(runs[g_from[p, k][gs], k, np.nonzero(gs)[0]].max())
        out.append(ev)
    return out


def casts(ts, counts: np.ndarray, clean: np.ndarray | None = None, halves=None,
          icons=None) -> list[tuple]:
    """Charge drops as (t, slot, from_fill, to_fill, suspect), skipping unusable
    samples (`_compare_pairs`): a fall of the teal fill, or, with `halves`, a
    teal or gold half going empty (`_events`). A slot emptying on the first undrawn sample after
    a drawn one is still compared and flagged suspect: a player who has spent
    everything (Sova's ult after C, Q and E) can look like an undrawn tray.
    Refused samples that still show the tray are bridged for up to GAP_S; an
    undrawn tray is a gap, never a drop."""
    f = fills(counts, clean)
    ok = np.ones(len(f), bool) if clean is None else np.asarray(clean, bool)
    return flag_suspect([(ts[e["i"]], e["slot"], e["from"], e["to"], e["forced"])
                         for e in _events(ts, f, ok, halves, icons)])


def flag_suspect(ev: list[tuple], quiet=None) -> list[tuple]:
    """Mark drops that co-occur across slots within SUSPECT_S, or were forced.
    Flagged, not deleted: a player can cast twice in two seconds. A drop whose
    `quiet` entry is true is still marked but marks no other drop; the caller
    names those drops (`ability_timeline.player_tray_casts`)."""
    quiet = list(quiet) if quiet is not None else [False] * len(ev)
    out = []
    for i, (t, k, a, b, forced) in enumerate(ev):
        near = sum(1 for j, (t2, k2, _a, _b, _f) in enumerate(ev)
                   if j != i and not quiet[j] and abs(t2 - t) <= SUSPECT_S and k2 != k)
        out.append((t, k, a, b, bool(near) or bool(forced)))
    return out


def gold_candidates(ts_ms, counts: np.ndarray, clean: np.ndarray, scores,
                    icons=None) -> list[dict]:
    """The gold-only drops (`_events`) that wait on a witness, as
    `{"t_ms", "slot", "t_before_ms", "t_gold_ms", "gold_run", "halves_from",
    "halves_to", "spent_halves"}`: the drop's sample, the sample it compares
    with, the sample its gold half last read on, and the readable samples in a
    row that read it gold up to there (`_gold_runs`). `gold_witness` judges
    each and `drops` fires the witnessed ones."""
    ts = [t / 1000.0 for t in ts_ms]
    clean = np.asarray(clean, bool)
    ev = _events(ts, fills(counts, clean), clean, segment_index(scores), icons)
    return [{"t_ms": float(ts_ms[e["i"]]), "slot": e["slot"],
             "t_before_ms": float(ts_ms[e["p"]]), "t_gold_ms": float(ts_ms[e["g"]]),
             "gold_run": e["run"],
             **{k: e[k] for k in ("halves_from", "halves_to", "spent_halves")}}
            for e in ev if e.get("gold_only")]


def gold_witness(cand: dict, reads: list[dict], icon: dict) -> dict:
    """Whether a second channel saw the spend a gold-only drop
    (`gold_candidates`) reads. Pure over stored observations: the restock
    countdown's reads (`tray_countdown` rows: `t_ms`, `slot`, `numeral`,
    `value_s`) and the slot icons' brightness (`icon`, `{t_ms: [C, Q, E, X]}`
    from `tray_icons.slot_brightness` on the candidate's gold sample and on
    the samples up to `WITNESS_AFTER_S` after the drop).

    The empty bar is translucent, so a bright warm object behind it reads
    gold for a sample: an orange weapon over Skye's spent Guiding Light while
    its countdown ran 27, 26, 25 (c62c2b06bcfb 216.0 s), and a yellow wall
    behind Clove's spent Meddle (a1a995e6b19b 1297.0 s). Neither a numeral
    nor the icon moved. A spend shows on one of them:

    - `countdown`: a numeral read over the slot within `WITNESS_AFTER_S` after
      the earlier sample is larger than the last numeral read from
      `WITNESS_BEFORE_S` before the gold sample to the earlier sample
      (`restarted`; e37fdeca944f 426.6 s read 0.2, then 49), or no numeral
      and no refused read came before (`appeared`). A numeral that keeps
      counting is `continued`; none after is `no_numeral_after`.
    - `icon`: the slot's icon is lit on the gold sample (`ICON_LIT_MIN`), as
      a slot holding a charge draws it, and dims (`ICON_DIM_MAX`) within
      `WITNESS_AFTER_S` after the drop, as a slot spent to empty draws it.

    - `persisted`: the spent half read gold on `GOLD_PERSIST_MIN` or more
      readable samples in a row ending at its gold sample (`gold_run`,
      `_gold_runs`). A gold charge spent beside a teal one leaves the icon
      lit, and Phoenix's Curveball draws no numeral after it
      (587c15b07779 1140.0 s); a returned charge reads gold for as long as it
      is held, and a bright object passing behind an empty bar reads gold for
      a sample.

    Any one witness fires the drop. Each channel is cut once, here."""
    k = SLOT_KEYS.index(cand["slot"])
    t, tb, tg = cand["t_ms"], cand["t_before_ms"], cand["t_gold_ms"]
    mine = sorted((r for r in reads if r["slot"] == cand["slot"]), key=lambda r: r["t_ms"])
    before = [r for r in mine if tg - 1000.0 * WITNESS_BEFORE_S <= r["t_ms"] <= tb]
    after = [r for r in mine if tb < r["t_ms"] <= t + 1000.0 * WITNESS_AFTER_S]
    last = next((r for r in reversed(before) if r.get("value_s") is not None), None)
    first = next((r for r in after if r.get("value_s") is not None), None)
    if first is None:
        cd = "no_numeral_after"
    elif last is not None:
        cd = "restarted" if first["value_s"] > last["value_s"] else "continued"
    elif any(r.get("numeral") is None for r in before):
        cd = "unread_before"
    else:
        cd = "appeared"
    on_gold = icon.get(tg)
    on_gold = None if on_gold is None or on_gold[k] is None else float(on_gold[k])
    later = [float(v[k]) for tt, v in icon.items()
             if t <= tt <= t + 1000.0 * WITNESS_AFTER_S and v[k] is not None]
    least = min(later) if later else None
    if on_gold is None or least is None:
        ic = "unread"
    elif on_gold < ICON_LIT_MIN:
        ic = "dim_on_gold"
    else:
        ic = "dimmed" if least <= ICON_DIM_MAX else "stayed_lit"
    run = cand.get("gold_run")
    by = [w for w, on in (("countdown", cd in ("restarted", "appeared")),
                          ("icon", ic == "dimmed"),
                          ("persisted", run is not None and run >= GOLD_PERSIST_MIN)) if on]
    return {"witnessed": bool(by), "by": by, "countdown": cd, "gold_run": run,
            "numeral_before": None if last is None else last["numeral"],
            "numeral_after": None if first is None else first["numeral"],
            "icon": ic, "icon_on_gold": on_gold, "icon_least_after": least}


def drops(ts_ms, counts: np.ndarray, clean: np.ndarray, scores=None, icons=None,
          witness: dict | None = None) -> list[dict]:
    """`casts` as rows, with the two reasons a drop is suspect kept apart:
    `forced` (the sample itself is undrawn) and `cooccur` (another slot
    dropped within SUSPECT_S), and `across_gap` for a drop compared across
    refused samples. With `scores` (`segment_scores` per sample, n x 4 x 2 x
    3), the half classes join the reading (`segment_index`): a teal or gold
    half going empty is a drop, readable halves under read slot icons
    (`icons`, per sample) keep the tray drawn (`drawn_mask`), and each row
    carries `by` (fill, halves or both), both samples' half classes
    (`halves_from`, `halves_to`) and the classes that went empty
    (`spent_halves`) as its evidence.

    A gold-only drop (`gold_candidates`) fires only where `witness`, keyed by
    `(t_ms, slot)`, holds a `gold_witness` that saw the spend, and carries it
    as `witness`; without one it is no drop and marks no other drop
    `cooccur`. The caller stores the unwitnessed candidates apart."""
    ts = [t / 1000.0 for t in ts_ms]
    clean = np.asarray(clean, bool)
    f = fills(counts, clean)
    halves = None if scores is None else segment_index(scores)
    witness = witness or {}
    ev = []
    for e in _events(ts, f, clean, halves, icons):
        if e.get("gold_only"):
            w = witness.get((float(ts_ms[e["i"]]), e["slot"]))
            if not (w and w.get("witnessed")):
                continue
            e = {**e, "witness": w}
        ev.append(e)
    sus = flag_suspect([(ts[e["i"]], e["slot"], e["from"], e["to"], e["forced"]) for e in ev])
    near = flag_suspect([(ts[e["i"]], e["slot"], e["from"], e["to"], False) for e in ev])
    out = []
    for e, (*_x, s), (*_y, co) in zip(ev, sus, near):
        i = e["i"]
        row = {"t_ms": float(ts_ms[i]), "slot": e["slot"], "from": e["from"], "to": e["to"],
               "suspect": s, "forced": e["forced"], "cooccur": co,
               "across_gap": bool(i > 0 and not clean[i - 1])}
        if halves is not None:
            row.update({k: e[k] for k in ("by", "halves_from", "halves_to", "spent_halves")})
        if "witness" in e:
            row["witness"] = e["witness"]
        out.append(row)
    return out
