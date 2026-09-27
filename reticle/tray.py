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


def slot_counts(frame: np.ndarray) -> tuple[list[int], bool]:
    """Teal pixel count per charge bar, and whether the frame is trustworthy
    (no screen-wide green bleeding into the guard rows)."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    teal = ((h > TEAL_H[0]) & (h < TEAL_H[1]) & (s > TEAL_S_MIN) & (v > TEAL_V_MIN))
    out, bleed = [], 0.0
    for k in range(4):
        cx = SLOT_X0 + SLOT_DX * k
        sl = slice(cx - BAR_HALF, cx + BAR_HALF)
        out.append(int(teal[BAR_Y0:BAR_Y1, sl].sum()))
        bar = teal[BAR_Y0:BAR_Y1, sl].mean()
        g = max(teal[a:b, sl].mean() for a, b in GUARD_Y)
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


def flag_suspect(ev: list[tuple]) -> list[tuple]:
    """Mark drops that co-occur across slots within SUSPECT_S, or were forced.
    Flagged, not deleted: a player can cast twice in two seconds."""
    out = []
    for i, (t, k, a, b, forced) in enumerate(ev):
        near = sum(1 for j, (t2, k2, _a, _b, _f) in enumerate(ev)
                   if j != i and abs(t2 - t) <= SUSPECT_S and k2 != k)
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
