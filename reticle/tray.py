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
the bar). The drops and fills stay teal (TRAY_VERSION); the classes carry
their own stamp (TRAY_SEGMENT_VERSION) and are stored as run-length
`segments` rows (`segment_runs`), which the state model reads to count a gold
charge and to tell a returned charge from a streak.

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


def segment_classes(scores: np.ndarray) -> list[list[str]]:
    """The class of each half from `segment_scores`: the best-scoring class at
    `SEG_MIN` or more, else `unreadable`. The one cut."""
    pick = np.where(scores.max(axis=-1) >= SEG_MIN, scores.argmax(axis=-1), len(SEG_CLASSES))
    return _SEG_NAMES[pick].tolist()


_SEG_NAMES = np.array(SEG_CLASSES + (SEG_UNREADABLE,))


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


def drawn(f_row: np.ndarray) -> bool:
    """Is the tray rendered at all? Refuses rather than reporting zero charges."""
    return bool((f_row > DRAWN_MIN_FRAC).any())


def casts(ts, counts: np.ndarray, clean: np.ndarray | None = None) -> list[tuple]:
    """Charge drops as (t, slot, from_fill, to_fill, suspect), skipping unusable
    samples. A slot emptying on the first undrawn sample after a drawn one is
    still compared and flagged suspect: a player who has spent everything
    (Sova's ult after C, Q and E) looks like an undrawn tray. Refused samples
    that still show the tray are bridged for up to GAP_S; an undrawn tray is
    a gap, never a drop."""
    f = fills(counts, clean)
    out = []
    prev, prev_t, bridged = None, None, False
    for i, (t, row) in enumerate(zip(ts, f)):
        ok = clean is None or bool(clean[i])
        near = prev is not None and (not bridged or t - prev_t <= GAP_S)
        if not drawn(row) or not ok:
            if near and ok:
                for k in range(4):
                    if prev[k] - row[k] >= CAST_DROP:
                        out.append((t, SLOT_KEYS[k], round(float(prev[k]), 2),
                                    round(float(row[k]), 2), True))
            if ok or not drawn(row):
                prev = None                # a gap is not a drop
            else:
                bridged = True             # a flash over a drawn tray
            continue
        if near:
            for k in range(4):
                if prev[k] - row[k] >= CAST_DROP:
                    out.append((t, SLOT_KEYS[k], round(float(prev[k]), 2),
                                round(float(row[k]), 2), False))
        prev, prev_t, bridged = row, t, False
    return flag_suspect(out)


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


def drops(ts_ms, counts: np.ndarray, clean: np.ndarray) -> list[dict]:
    """`casts` as rows, with the two reasons a drop is suspect kept apart:
    `forced` (the sample itself is undrawn) and `cooccur` (another slot
    dropped within SUSPECT_S), and `across_gap` for a drop compared across
    refused samples."""
    ts = [t / 1000.0 for t in ts_ms]
    ev = casts(ts, counts, clean)
    f = fills(counts, clean)
    idx = {round(float(t), 3): i for i, t in enumerate(ts)}
    near = flag_suspect([(t, k, a, b, False) for t, k, a, b, _s in ev])
    out = []
    for (t, k, a, b, sus), (*_x, co) in zip(ev, near):
        i = idx[round(float(t), 3)]
        out.append({"t_ms": float(ts_ms[i]), "slot": k, "from": a, "to": b,
                    "suspect": sus, "forced": not drawn(f[i]), "cooccur": co,
                    "across_gap": bool(i > 0 and not clean[i - 1])})
    return out
