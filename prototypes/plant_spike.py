r"""Detect the plant POSITIVELY, off the spike graphic, and bisect for its instant.

    .\.venv\Scripts\python.exe prototypes\plant_spike.py <session> [--bisect]
    .\.venv\Scripts\python.exe prototypes\plant_spike.py <session> --sheet out.png

Why this exists
---------------
`rounds._plant` defines a plant as *the longest run of unreadable clock that
reaches the round's end*. So the shipped plant rate is a function of an OCR
FAILURE, not of the spike -- and `hud-0.11.0` added `clock_reason` precisely to
separate "nothing was there" from "something was there and could not be
matched", which `_plant` ignores. Gating on `no_glyphs` alone moves the corpus
rate from 183/369 (50%) to 98/369 (27%), and nothing in the repo could say
which was right.

Worse, the rule's own validation was circular. `plant_probe.py` draws its
negative controls from frames where the clock READ -- which is the
contrapositive of the rule under test -- so its controls come from the easy,
unoccluded, digit-bearing population while every open item comes from frames
where the clock did not read. A perfect measurement over the wrong population,
which is the trap `CLAUDE.md` names as *0 of 55 hand-marked icons have aspect
>= 2.0*.

**CLAUDE.md already named the fix and nobody had built it**: when the spike is
planted the round timer is replaced by a red spike graphic, centre-screen, for
the whole post-plant window -- inside an ROI already being cropped. That is a
POSITIVE detection of the thing itself, and it needs no new ROI.

What it looks like, and why the test is structural
--------------------------------------------------
Rendered before anything was measured (the standing rule): the graphic is a
large solid red triangle with a hexagonal core, occupying the centre of the
scoreline ROI where the digits go. It is unmissable by eye, and the first
render already showed the null-clock rule getting one wrong -- a round it calls
CLEAN at 612 s is plainly displaying the spike.

The standing convention forbids an absolute level here, because the scoreline
is composited over live scenery and warm walls sit behind it (two of the eight
probes rendered have orange scenery right through the ROI). So the test is
**coverage of a connected shape**, with colour only deciding what to count:

    red mask -> largest connected component -> what fraction of the CENTRE BOX
    does it cover

A warm wall gives a diffuse, ragged mask that does not form one large
component filling the box; the graphic gives one that does. Structure answers
"is this a solid shape sitting where the timer goes", colour answers "is it the
red we mean" -- which is exactly the division CLAUDE.md prescribes.

Cost, which is the reason this is affordable at all
----------------------------------------------------
the question: can this be done by binary search rather than a corpus
re-read? Yes, and the rate needs no search at all.

* **the RATE is a handful of probes per round.** A plant is a step function --
  once the graphic is up it stays until the round ends or the spike is defused
  -- so four samples in the round's second half answer "was it planted". 369
  rounds at 4 probes is ~1500 SEEKS across the corpus, against a corpus `hud`
  re-read that decodes every frame of every capture and re-runs three
  extractors over it;
* **the INSTANT is a bisection**, and only for rounds that came back planted.
  ~11 seeks localises the transition in a 100 s round to a second.

**One caveat that decides the design, and it is already recorded in this repo:**
`decode.py` says OpenCV's frame-exact H.264 seeking is unreliable, which is why
`ability_series` decodes sequentially. So bisection is not run down to the
frame. It narrows to a `BISECT_STOP_MS` bracket with seeks, and the caller may
then decode that one short stretch sequentially for a frame-exact edge. Seeks
for the coarse work, sequential decode for the last half-second.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.profiles import get_profile                          # noqa: E402
from reticle.rounds import build_rounds                           # noqa: E402
from reticle.store import Store                                   # noqa: E402

#: The centre of the scoreline ROI, where the timer digits and the spike
#: graphic both live. Fractions of the ROI, not of the frame.
CENTRE = (0.34, 0.00, 0.66, 1.00)
#: OpenCV hue. The graphic is a saturated pure red; the band is deliberately
#: tight because STRUCTURE is doing the separating, not this.
HUE_LO, HUE_HI = 168, 12
SAT_MIN, VAL_MIN = 120, 90
#: What fraction of the centre box the largest red component must cover.
COVER_MIN = 0.10
#: Probes per round, spread over the window a plant can be visible in.
PROBE_FRACS = (0.55, 0.70, 0.82, 0.94)
#: Bisection stops here and hands off to a sequential decode -- see the
#: docstring on why it does not go to the frame.
BISECT_STOP_MS = 500.0


def centre_box(roi: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = roi
    w, h = x1 - x0, y1 - y0
    return (x0 + int(w * CENTRE[0]), y0 + int(h * CENTRE[1]),
            x0 + int(w * CENTRE[2]), y0 + int(h * CENTRE[3]))


def spike_cover(frame: np.ndarray, box: tuple[int, int, int, int]) -> float:
    """Fraction of the centre box covered by the largest red component.

    Coverage of ONE component, not a red pixel count: warm scenery through the
    semi-transparent HUD produces plenty of red pixels and no single solid
    shape, which is the whole reason this is not a threshold on redness.
    """
    x0, y0, x1, y1 = box
    crop = frame[y0:y1, x0:x1]
    if crop.size == 0:
        return 0.0
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    m = (((hh >= HUE_LO) | (hh <= HUE_HI)) & (ss > SAT_MIN)
         & (vv > VAL_MIN)).astype(np.uint8)
    n, _lab, st, _cen = cv2.connectedComponentsWithStats(m, 8)
    if n <= 1:
        return 0.0
    return float(st[1:, 4].max()) / float(crop.shape[0] * crop.shape[1])


class Prober:
    """Cover score at an arbitrary instant, by SEEKING, on one open capture.

    **This deliberately uses the pattern `decode.sample_at` was written to
    abolish, and the reason is that its argument does not apply here.** That
    docstring is about *hundreds to thousands* of samples per session, where
    re-finding a keyframe every time pinned every core for an hour;
    `sample_at` answers it with one forward decode bounded by the last target.

    Two things make that the wrong primitive for this question:

    * **the targets are FEW and SCATTERED.** Eighty probes per session, spread
      across a 31-minute capture. One forward decode costs a grab-through of
      the whole file (~95 s here); eighty seeks cost seconds;
    * **bisection cannot use it at all.** Each probe depends on the previous
      answer, so a forward-decode primitive would decode from the start of the
      file once per bisection step -- which is what the first version of this
      did, and it was still running after ten minutes on twenty rounds.

    Accuracy is the other half of the argument. `decode.py` warns that
    frame-exact H.264 seeking is unreliable, and it is -- but nothing here
    needs a frame. "Was the spike up in the second half of this round" tolerates
    a second; the bisection stops at `BISECT_STOP_MS` and hands a bracket to a
    sequential decode if a frame-exact edge is ever wanted. Seeks for coarse
    work, sequential decode for exact work.
    """

    def __init__(self, path, box):
        self.cap = cv2.VideoCapture(str(path))
        if not self.cap.isOpened():
            raise SystemExit(f"could not open {path}")
        self.box = box
        self.n = 0

    def at(self, t_ms: float) -> float:
        self.cap.set(cv2.CAP_PROP_POS_MSEC, float(t_ms))
        ok, fr = self.cap.read()
        self.n += 1
        return spike_cover(fr, self.box) if ok else 0.0

    def close(self):
        self.cap.release()


def bisect_edge(probe, lo: float, hi: float, want_hi: bool,
                stop_ms: float = BISECT_STOP_MS) -> float:
    """Instant of the transition in [lo, hi], to within `stop_ms`.

    `probe(t) -> bool`. Assumes the predicate is MONOTONE across the bracket:
    false-then-true when `want_hi`, true-then-false otherwise. That assumption
    is the whole risk -- a PULSING object (Tejo's E and X pulse, per
    `prototypes/CLAUDE.md`) is not monotone and this would return an arbitrary
    pulse edge with full confidence -- so callers must establish monotonicity
    before using it, never assume it.
    """
    while hi - lo > stop_ms:
        mid = (lo + hi) / 2.0
        if probe(mid) == want_hi:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2.0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--date", default=None)
    ap.add_argument("--bisect", action="store_true",
                    help="also localise the plant instant, for planted rounds")
    ap.add_argument("--cover-min", type=float, default=COVER_MIN)
    a = ap.parse_args(argv)

    store = Store()
    man = store.read_manifest(a.session)
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    roi = next(r for r in prof.rois
               if r.name == "scoreline").pixels(int(src["width"]),
                                                int(src["height"]))
    box = centre_box(roi)

    date = a.date
    if date is None:
        import glob
        hits = glob.glob(str(store.root / "l1" / "hud" / "date=*" /
                             f"session={a.session}" / "hud.parquet"))
        if not hits:
            raise SystemExit(f"no stored HUD for {a.session}")
        date = Path(hits[0]).parts[-3].split("=", 1)[1]

    import pyarrow.parquet as pq
    rounds = build_rounds(pq.read_table(store.hud_path(a.session, date)))
    print(f"session    {a.session}   {len(rounds)} rounds")
    print(f"scoreline  {roi}   centre box {box}")
    print()
    pr = Prober(src["path"], box)
    print(f"{'#':>3}{'start':>9}{'end':>9}  {'null-clock':<11}"
          f"{'cover (probes)':<34}{'spike':<7} agree")

    agree = disagree = 0
    n_spike = 0
    rows = []
    for i, r in enumerate(rounds):
        a0, z0 = r["t_start_ms"], r["t_end_ms"]
        times = [a0 + (z0 - a0) * f for f in PROBE_FRACS]
        cov = [pr.at(t) for t in times]
        planted = max(cov) >= a.cover_min
        n_spike += planted
        old = bool(r["spike_planted"])
        ok = planted == old
        agree += ok
        disagree += not ok
        rows.append((i, r, planted, cov))
        print(f"{i:>3}{a0/1000:9.0f}{z0/1000:9.0f}  {str(old):<11}"
              f"{' '.join(f'{c:.2f}' for c in cov):<34}{str(planted):<7}"
              f"{'' if ok else '   <-- DISAGREE'}")

    print()
    print(f"spike rule {n_spike}/{len(rounds)} planted "
          f"({n_spike/max(1,len(rounds))*100:.0f}%)")
    print(f"null-clock {sum(1 for _i, r, _p, _c in rows if r['spike_planted'])}"
          f"/{len(rounds)}")
    print(f"agree      {agree}/{len(rounds)}, disagree {disagree}")

    if a.bisect:
        print()
        print("plant instant, by bisection (seeks only, to +/- "
              f"{BISECT_STOP_MS:.0f} ms)")
        for i, r, planted, cov in rows:
            if not planted:
                continue
            a0, z0 = r["t_start_ms"], r["t_end_ms"]
            # Monotonicity is ESTABLISHED, not assumed: bisect only between a
            # probe known clean and the first probe known planted, so the
            # bracket contains one rising edge by construction.
            first = next(j for j, c in enumerate(cov) if c >= a.cover_min)
            lo = a0 if first == 0 else a0 + (z0 - a0) * PROBE_FRACS[first - 1]
            hi = a0 + (z0 - a0) * PROBE_FRACS[first]
            n = [0]

            def probe(t):
                n[0] += 1
                return pr.at(t) >= a.cover_min

            t = bisect_edge(probe, lo, hi, want_hi=True)
            print(f"{i:>3}  planted at {t/1000:8.1f}s   "
                  f"({(t-a0)/1000:5.1f}s into the round, {n[0]} seeks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
