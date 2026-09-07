r"""The SECOND-LIFE badge on a killfeed entry: find the arc, do not threshold it.

    .\.venv\Scripts\python.exe prototypes\revive_mark.py <session> [--sheet out.png]

Phoenix's Run It Back and Kayo's stabilise grant the second life BEFORE the
fact, so the death is a real killfeed entry that the scoreboard never counts and
that produces no roster change. `CLAUDE.md` records both consequences and the
position on them: **keep the events and TAG them**, because a duel lost inside
Run It Back is still a duel that was lost. Nothing has read the tag until now.

It is worth reading for a second reason found on 2026-09-07: three of the seven
unresolved windows in `analysis/reconciliation.json` are this and nothing else.

WHERE THE BADGE IS -- and it is not where the layout suggests
--------------------------------------------------------------
The band reads `[killer portrait][killer name][weapon icon][marks][victim name]`
so the obvious crop is `EntryView.wx1 .. victim_run[0]`. **That is the wrong
window**, measured before this was written: in every confirmed instance the
badge STRADDLES the victim-plate boundary, drawn across the colour change, and
`victim_run[0]` cuts through it. A reader keyed to the gap sees a sliver of arc.

So the window here is centred ON `victim_run[0]` and is as wide as the band is
tall. The headshot crosshair -- four bars around a centre -- lives in the gap
proper and is the COMMON occupant: it appears on badged and unbadged entries
alike, so the question is *is there an arc*, never *which mark is this*.

WHY A FIT AND NOT A THRESHOLD
-------------------------------
`prototypes/CLAUDE.md` records the same choice being forced three times on the
minimap: *a closing radius that reconnects a broken rim is the radius that
merges adjacent icons -- fit a shape, do not repair one*. The badge is a thin
white annulus over a two-colour background, which is the case a level test
cannot survive; `CLAUDE.md`'s standing rule is that nothing absolute may be
tested against this HUD. So the score is the fraction of a fitted circle's
CIRCUMFERENCE that is white, which is relative to the shape rather than to a
level, and the radius is searched rather than assumed.

HOW IT IS SCORED, and what the held-out session settles
--------------------------------------------------------
Seven positives, all confirmed by rendering:

    587c15b07779   209.5s  950.0s  1377.5s          DEVELOPMENT
    ff636d173b07   802s 1201s 1754s 2301s           HELD OUT

`ff636d173b07` was held out and carries an INDEPENDENT count: `CLAUDE.md`
records its killfeed at +4 deaths against `checks.KNOWN_KD`, all 24 tracked
deaths read correctly, and exactly four carrying this badge at 13:21, 20:00,
29:13 and 38:20 -- found by hand off a contact sheet, long before this existed.

**The gate `run >= 0.29` was fixed on the development session and written down
BEFORE the held-out session was scored.** It is the midpoint of that session's
gap (negatives 0.125-0.219, positives 0.359-0.422), not a swept value.

Scoring every one of the 24 counted death tracks on the held-out session:

    death tracks clearing the gate      4 of 24
    at                                  801.0s 1200.5s 1753.0s 2300.0s
    hand-recorded, independently        13:21  20:00   29:13   38:20
    24 - 4 = 20, which is exactly `KNOWN_KD`'s death count for the session

So the count, the timestamps and the scoreboard all agree, and none of them was
available to the gate. Read the limits with it: **7 positives on 2 sessions and
one agent.** Kayo is untested, the enemy-side case (`bfad2778a372`, +1 kill) is
untested, and 20 of the 22 negatives come from the held-out session's own death
tracks, so the negative class is one session's worth of ordinary entries.

WHY COVERAGE FAILED AND CONTINUITY WORKED -- do not retry the first
--------------------------------------------------------------------
The first version scored the fraction of the fitted circumference that is
white, and it does NOT separate:

    badge                     coverage 0.53-0.69
    plain headshot crosshair  coverage 0.64        <- higher than two badges
    the letters of a name     coverage 0.28-0.34   <- circles fitted to `Jett`

A crosshair is four bars arranged around a point, which is a circle sampled at
four places, so it scores like a ring on coverage. What differs is CONTINUITY:
the badge is one unbroken arc, the crosshair is four short runs separated by
four gaps. The longest circular run separates them 0.359-0.453 against
0.125-0.219 with nothing in between, on both sessions.

The fitted RADIUS is a second, unused signature pointing the same way -- the
badge fits 9.8-13.8 px against the crosshair's 8.8-9.8 -- and it is left unused
deliberately, because one statistic that separates cleanly is worth more than
two that have to be combined on seven positives.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys

import cv2
import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from reticle.killfeed import analyse_killfeed, killfeed_roi          # noqa: E402
from reticle.profiles import get_profile                             # noqa: E402
from reticle.store import Store                                      # noqa: E402

#: White line art: bright, and nearly colourless against either plate.
WHITE_V_MIN = 190
WHITE_S_MAX = 70
#: Radii to search, as a fraction of the band height. The badge is a fixed
#: asset, so this is narrow on purpose -- a wide search finds a circle anywhere.
R_FRAC = (0.26, 0.42)
#: How far the centre may sit from the plate boundary, again as a fraction of
#: band height. The badge is drawn ON the boundary.
CX_FRAC = 0.45
#: Circumference samples per candidate.
N_THETA = 64


def white_mask(bgr: np.ndarray) -> np.ndarray:
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)
    return ((hsv[:, :, 2] >= WHITE_V_MIN) & (hsv[:, :, 1] <= WHITE_S_MAX))


def _runs(hit) -> int:
    """Longest circular run of consecutive True samples."""
    n = len(hit)
    if hit.all():
        return n
    best = run = 0
    for k in range(2 * n):
        if hit[k % n]:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return min(best, n)


def fit_arc(mask, cx0):
    """Best (coverage, longest_run, cx, r) over a small circle search.

    TWO statistics, because coverage alone was MEASURED not to separate. The
    badge and the headshot crosshair both put white at one radius from a
    centre -- a crosshair is four bars arranged around a point, which is a
    circle sampled at four places -- so a fitted circle's coverage reads
    0.59-0.69 on the badge and 0.64 on a plain crosshair. It also fires on
    letters: circles were fitted to `Jett`, `Vyse` and `Me` at 0.28-0.34.

    What differs is CONTINUITY. A ring is one unbroken arc; a crosshair is
    four short runs separated by four gaps. So the discriminator is the
    longest circular run of white along the circumference, as a fraction of
    it, and coverage is kept beside it as the second aggregate this repo's
    own convention requires.

    Selection is on the RUN, not on coverage -- picking the circle with the
    most white and then measuring its continuity would let the crosshair pick
    the circle and then fail it.
    """
    h, w = mask.shape
    best = (0.0, 0.0, cx0, 0.0)
    th = np.linspace(0.0, 2.0 * np.pi, N_THETA, endpoint=False)
    ct, stt = np.cos(th), np.sin(th)
    cy = (h - 1) / 2.0
    for r in np.arange(R_FRAC[0] * h, R_FRAC[1] * h, 0.5):
        for cx in np.arange(cx0 - CX_FRAC * h, cx0 + CX_FRAC * h, 1.0):
            xs = np.rint(cx + r * ct).astype(int)
            ys = np.rint(cy + r * stt).astype(int)
            ok = (xs >= 0) & (xs < w) & (ys >= 0) & (ys < h)
            if ok.sum() < N_THETA:      # the whole circle must be in the crop
                continue
            hit = mask[ys, xs]
            run = _runs(hit) / float(N_THETA)
            if run > best[1]:
                best = (float(hit.mean()), run, float(cx), float(r))
    return best


def entry_marks(frame, roi, w, h, profile_name):
    """(slot, coverage, y0, y1, x0, x1) per parsed entry in this frame."""
    ents = analyse_killfeed(frame, roi, w, h, None, profile_name)
    if not isinstance(ents, (list, tuple)):
        ents = getattr(ents, "entries", None) or getattr(ents, "views", []) or []
    rx0, ry0, _, _ = roi.pixels(w, h)
    out = []
    for v in ents:
        vr = getattr(v, "victim_run", None)
        if vr is None:
            continue
        bh = v.y1 - v.y0
        if bh < 12:
            continue
        # Centred ON the plate boundary, one band-height either side.
        x0 = max(0, int(vr[0]) - bh)
        x1 = int(vr[0]) + bh
        crop = frame[ry0 + v.y0: ry0 + v.y1, rx0 + x0: rx0 + x1]
        if crop.size == 0 or crop.shape[1] < 8:
            continue
        cov, run, cx, r = fit_arc(white_mask(crop), float(int(vr[0]) - x0))
        out.append(dict(slot=v.slot, coverage=round(cov, 3),
                        run=round(run, 3),
                        y0=v.y0, y1=v.y1, x0=x0, x1=x1, cx=cx, r=r))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--at", help="comma-separated seconds to probe")
    ap.add_argument("--sheet", help="write a contact sheet here")
    a = ap.parse_args(argv)

    st = Store()
    man = json.load(open(pathlib.Path(st.root, "manifests", f"{a.session}.json")))
    prof = get_profile(man["source_profile"])
    cap = cv2.VideoCapture(man["source"]["path"])
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    roi = killfeed_roi(prof)
    times = [float(x) for x in a.at.split(",")] if a.at else []
    panels = []
    for t in times:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, fr = cap.read()
        if not ok:
            print(f"{t}s: no frame")
            continue
        for m in entry_marks(fr, roi, w, h, prof.name):
            print(f"  {t:8.1f}s slot {m['slot']}  run {m['run']:.3f}"
                  f"  coverage {m['coverage']:.3f}  r {m['r']:.1f}")
            if a.sheet:
                rx0, ry0, _, _ = roi.pixels(w, h)
                crop = fr[ry0 + m["y0"]: ry0 + m["y1"],
                          rx0 + m["x0"]: rx0 + m["x1"]].copy()
                cv2.circle(crop, (int(round(m["cx"])), (crop.shape[0] - 1) // 2),
                           int(round(m["r"])), (0, 255, 255), 1)
                big = cv2.resize(crop, None, fx=6, fy=6,
                                 interpolation=cv2.INTER_NEAREST)
                lab = np.zeros((big.shape[0], 200, 3), np.uint8)
                cv2.putText(lab, f"{t:.1f}s s{m['slot']}", (4, 20),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(lab, f"run {m['run']:.2f} cov {m['coverage']:.2f}", (4, 42),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 1)
                panels.append(np.hstack([lab, big]))
    if a.sheet and panels:
        W = max(p.shape[1] for p in panels)
        panels = [np.hstack([p, np.zeros((p.shape[0], W - p.shape[1], 3), np.uint8)])
                  for p in panels]
        cv2.imwrite(a.sheet, np.vstack(panels))
        print("wrote", a.sheet)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
