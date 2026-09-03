"""Read the ability tray: how many charges of each ability the player has, and when one is spent.

    .\\.venv\\Scripts\\python.exe prototypes\\ability_hud.py <session> [--from S] [--to S]

Why this exists
---------------
`profiles.py` has ROIs for the scoreline, both roster bands, HP, ammo, the
killfeed, the minimap and the crosshair centre -- and none for the bottom-left
ability tray. Nothing has ever read it. That is the cheapest exact "the local
player cast ability X at time T" available anywhere in the capture, and it is
the same trick `store.py` already uses for the one below it: **`ammo_mag`
falling between samples is a shot fired**, so a charge bar falling is a cast.

It arrived on the critical path by elimination. `audio_probe.py` set out to use
audio onsets as a free supervisor for minimap ability detection and found the
clips are saturated with onsets (null median flux rank 0.99 at +/-0.3 s), so a
matched filter is needed instead -- and a matched filter needs a reference cut
at a KNOWN cast time. This is where a known cast time comes from.

Geometry, measured at 1920x1080 on `a06f04a0059f`
--------------------------------------------------
Teal charge bars occupy **y 1032..1051**, and the three basic-ability bars sit
at x 754..824, 868..937, 980..1050 -- a clean pitch of 113 px:

    slot k centre x = SLOT_X0 + SLOT_DX * k        k = 0,1,2,3  ->  C, Q, E, X

The predicted 4th centre (1128) lands on the measured ult run at 1130, which is
the check that the pitch is real rather than fitted to three points. Slot 3 is
the ULTIMATE and reads differently -- its charge is drawn as a row of pips
above the bar, not as bar segments -- so it is read but not treated as a cast
source here.

Like every other widget except the minimap, the tray is anchored to the screen
edge, so `valorant-16x9` and `valorant-16x9-bigmap` share this geometry (see
`prototypes/CLAUDE.md`: *ONLY the minimap ROI moves*).

What a reading means, and the one that must never be guessed
-------------------------------------------------------------
Charges are read as the FILL of the bar against that session's own observed
maximum for that slot, not as an absolute pixel count -- CLAUDE.md's standing
rule, since the tray is composited over live scenery and an absolute level
would eventually measure the world. Measured on `a06f04a0059f`, a two-charge
slot reads ~780 full, **~365 at one charge** and 0 at none: the levels are
sharply separated, which is what makes a ratio safe.

**Zero is not the same as not-drawn, and conflating them is exactly the defect
`hp` already has** (*Health is not a death signal* -- it also goes unreadable in
buy phase, while scoped, and while spectating). The tray disappears on the death
screen, in the buy menu and in the settings overlay. So when EVERY slot reads
near zero the frame is refused and the reading is `None`, never "no charges".
`reticle` never guesses a value.

Known limit, found the hard way, 2026-09-03
--------------------------------------------
**On the controlled ability clips the tray is useless, because infinite
charges are on.** Tracked across all of `eb10db50b1fb`, the C slot holds ~734
teal pixels for the entire clip and never halves, despite four labelled trapwire
placements; the only zero is the settings overlay at t=40 s. A custom game with
cheats enabled does not spend charges.

That inverts the obvious assumption -- that a deliberate demo clip is the ideal
place to read casts. It is the worst place. The tray is a REAL-MATCH instrument,
and the 17 ingested matches are where it works. If a controlled clip is ever
wanted for cast timing, it has to be recorded with infinite abilities OFF.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

STORE = Path.home() / "reticle-store"

#: Measured at 1920x1080. Slot 3 is the ultimate.
SLOT_X0, SLOT_DX = 789, 113
BAR_Y0, BAR_Y1 = 1032, 1052
BAR_HALF = 38
SLOT_KEYS = ("C", "Q", "E", "X")

#: The tray's teal. Same family as `reticle.minimap.ALLY_H`, widened slightly
#: because the bar is drawn brighter than an ally ring.
TEAL_H = (70, 100)
TEAL_S_MIN, TEAL_V_MIN = 80, 120

#: Below this fraction of the slot's own reference, on EVERY slot at once, the
#: tray is not drawn -- death screen, buy menu, settings overlay.
DRAWN_MIN_FRAC = 0.12

#: Rows immediately above and below the bar. The bar is a band of FIXED height
#: with sharp edges; a screen-wide green ability tint is not. If the guard rows
#: are as teal as the bar rows, the mask is measuring the world and the frame is
#: refused. Found at `a06f04a0059f` t=664.5, where a green screen effect flooded
#: the C and Q boxes to 1520 px against a true full bar of ~780 -- CLAUDE.md's
#: one never-wrong rule: measure inside the structure, require coverage, compare
#: relatively.
GUARD_Y = ((1008, 1028), (1056, 1076))
GUARD_MAX_RATIO = 0.6

#: A fall of at least this much of a slot's maximum, between consecutive
#: samples, is a spent charge. A two-charge slot steps by ~0.5 and a one-charge
#: slot by ~1.0, so 0.25 sits in an empty gap rather than on a fitted edge.
CAST_DROP = 0.25


def slot_counts(frame) -> tuple[list[int], bool]:
    """Teal pixel count per charge bar, and whether the frame is trustworthy.

    The second value is False when a screen-wide green effect is bleeding into
    the tray. It is decided per frame from the guard rows, not per slot, because
    the contaminating effects seen so far cover a large part of the screen.
    """
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


def scan(sid, t_from=None, t_to=None, step_s=0.5):
    """Sample the tray over a session. Returns (times, counts-per-slot)."""
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    cap = cv2.VideoCapture(src["path"])
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    t0 = 0.0 if t_from is None else t_from
    t1 = n / fps if t_to is None else min(t_to, n / fps)
    ts, rows = [], []
    t = t0
    while t < t1:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, fr = cap.read()
        if not ok:
            break
        if fr.shape[1] != 1920:
            raise SystemExit(f"{sid}: geometry is measured at 1920 wide, got {fr.shape[1]}")
        c, clean = slot_counts(fr)
        rows.append(c + [1.0 if clean else 0.0])
        ts.append(round(t, 2))
        t += step_s
    cap.release()
    a = np.array(rows, dtype=float) if rows else np.zeros((0, 5))
    return ts, a[:, :4], a[:, 4].astype(bool) if len(a) else np.zeros(0, bool)


def fills(counts, clean=None):
    """Counts as a fraction of each slot's own reference level.

    Relative, not absolute -- the tray is composited over live scenery, and
    CLAUDE.md's one never-wrong rule is to measure inside the structure and
    compare relatively.

    The reference is the **p90 of that slot's non-trivial CLEAN samples**, not
    the maximum. The maximum was the first thing tried and it was wrong: one
    green screen effect at `a06f04a0059f` t=664.5 doubled it, so every ordinary
    full bar then read as 0.50 and the levels collapsed. p90 over clean frames
    is unmoved by a handful of contaminated ones while still landing on "full",
    which is a slot's most common state by a wide margin.
    """
    if not len(counts):
        return counts
    ref = np.ones(counts.shape[1])
    for k in range(counts.shape[1]):
        col = counts[:, k]
        sel = col[clean] if clean is not None and clean.any() else col
        sel = sel[sel > 0.05 * max(col.max(), 1.0)]
        ref[k] = np.percentile(sel, 90) if len(sel) else 1.0
    return counts / np.maximum(ref, 1.0)


def drawn(f_row) -> bool:
    """Is the tray rendered at all in this frame?

    Refuses rather than reporting zero charges. The death screen, the buy menu
    and the settings overlay all blank it, and a confident `0` there would be
    the `hp`-as-a-death-signal defect repeated in a new widget.
    """
    return bool((f_row > DRAWN_MIN_FRAC).any())


def casts(ts, counts, clean=None):
    """Charge drops: (t, slot, from_fill, to_fill), skipping unusable frames."""
    f = fills(counts, clean)
    out = []
    prev = None
    for i, (t, row) in enumerate(zip(ts, f)):
        if not drawn(row) or (clean is not None and not clean[i]):
            prev = None                    # a gap is not a drop
            continue
        if prev is not None:
            for k in range(3):             # slot 3 is the ult; pips, not segments
                if prev[k] - row[k] >= CAST_DROP:
                    out.append((t, SLOT_KEYS[k], round(float(prev[k]), 2),
                                round(float(row[k]), 2)))
        prev = row
    return flag_suspect(out)


#: Two slots dropping within this window is not two casts -- it is the tray
#: changing whose it is.
SUSPECT_S = 1.5


def flag_suspect(ev):
    """Mark drops that co-occur across slots. They are probably not casts.

    **A dead player spectates, so the main view is not theirs** -- CLAUDE.md's
    standing defect, and the tray inherits it: on the death screen the tray
    switches to the spectated teammate's kit, with different abilities at
    different charges, and the switch reads as several slots emptying at once.
    Seen at `a06f04a0059f` 850.0-852.0, four "casts" in two seconds, and again
    around 689.

    Flagged rather than deleted, because a player genuinely can cast twice in
    two seconds and silently dropping those would cost real events with no way
    to notice. `suspect` is a column, not a filter -- the same treatment
    CLAUDE.md gives Run It Back deaths and wallbangs: a category on the event,
    decided per metric later.
    """
    out = []
    for i, (t, k, a, b) in enumerate(ev):
        near = sum(1 for j, (t2, k2, _a, _b) in enumerate(ev)
                   if j != i and abs(t2 - t) <= SUSPECT_S and k2 != k)
        out.append((t, k, a, b, near > 0))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--from", dest="t_from", type=float, default=None)
    ap.add_argument("--to", dest="t_to", type=float, default=None)
    ap.add_argument("--step", type=float, default=0.5)
    args = ap.parse_args()

    ts, counts, clean = scan(args.session, args.t_from, args.t_to, args.step)
    if not len(ts):
        raise SystemExit("no frames sampled")
    f = fills(counts, clean)
    ok = np.array([drawn(r) for r in f]) & clean
    print(f"{args.session}: {len(ts)} samples, {clean.sum()} clean of bleed, "
          f"{ok.sum()} usable ({ok.mean() * 100:.1f}%)")
    print("   per-slot reference (p90 of clean):",
          [int(x) for x in np.percentile(counts[clean] if clean.any() else counts,
                                         90, axis=0)])
    for k in range(4):
        lv = np.round(f[ok, k] * 4) / 4
        u, c = np.unique(lv, return_counts=True)
        print(f"   slot {SLOT_KEYS[k]}: fill levels "
              + ", ".join(f"{a:.2f}x{b}" for a, b in zip(u, c)))
    ev = casts(ts, counts, clean)
    solo = [e for e in ev if not e[4]]
    print(f"\n   {len(ev)} charge drops -- {len(solo)} clean, "
          f"{len(ev) - len(solo)} SUSPECT (co-occurring, probably a spectate swap):")
    for t, k, a, b, sus in ev:
        print(f"      {t:8.2f}s  {k}  {a:.2f} -> {b:.2f}"
              f"{'   SUSPECT' if sus else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
