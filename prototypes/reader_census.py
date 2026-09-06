r"""How much each reader throws away, and under which guard.

    .\.venv\Scripts\python.exe prototypes\reader_census.py e37fdeca944f
    .\.venv\Scripts\python.exe prototypes\reader_census.py c40d950031bb --from 13:00 --to 13:30
    ... --dump probe_census        # render the frames behind one reason

Why this exists
---------------
NOTES.md, 2026-09-05: *every real gain today came from finding something
discarded without a word*. Three of them -- the both-class label check,
`casts()` looping `range(3)`, `drawn()` refusing an all-spent tray -- were
guards doing exactly what they said, whose RATE was the finding. The audit
item this implements is "the other readers carry guards of the same shape".

A guard that never fires and a guard that eats a third of the session look
identical in the code and identical in L1. This prints the difference.

What it does NOT do
-------------------
It does not change what the readers return. `analyse_killfeed` still drops the
same bands; the census is an observer threaded in as an argument. So this can
be run against a session without invalidating a single stored number, which is
the only reason it is safe to run against all of them.

Reading the output
------------------
Every reason is named for the guard, not for the symptom, so a count is
actionable without opening the file. The killfeed's five band refusals are in
`killfeed.BAND_REFUSALS` with what each one means. Two matter most:

  no_divider   an entry with glyphs on both sides but no icon between them --
               the ability-kill signature. This is the one known read error
               left in stage 02 (c40d950031bb 13:14) and the count says
               whether it is one entry or a category.
  band_one_plate_colour
               a band found by the row profile that then failed the both-
               colours test. High here means the profile is finding scenery;
               it is also where a half-occluded real entry would go.

`--dump` writes the ROI crop of the first few frames behind a reason, because
a count that surprises you has to be *looked at* before it is believed. That
rule has three recorded recurrences in this repo, all expensive.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.census import Census                                 # noqa: E402
from reticle.decode import sample_frames                          # noqa: E402
from reticle.killfeed import (                                    # noqa: E402
    BAND_REFUSALS, analyse_killfeed, killfeed_roi, overlay_mask,
)
from reticle.ocr import (                                         # noqa: E402
    Templates, crop_gray, read_scoreline, scoreline_roi,
)
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"


def parse_ts(s: str | None) -> float | None:
    """`13:14`, `13:14.5` or plain seconds, to ms."""
    if s is None:
        return None
    if ":" in s:
        m, sec = s.split(":", 1)
        return (int(m) * 60 + float(sec)) * 1000.0
    return float(s) * 1000.0


def clusters(locators, gap_s: float) -> list[str]:
    """Collapse (t_s, slot) drops into entries.

    A killfeed entry lives for several seconds, so at 2 Hz one refused entry
    appears as ten consecutive drops. Counting bands answers "how much of the
    ROI is unreadable"; counting entries answers "how many events did this
    guard cost", and only the second is comparable with a scoreboard delta.

    The slot is part of the key because the stack slides: two entries can share
    a slot in turn, and the same entry moves down a slot as older ones expire.
    Neither is separable here, so a cluster is bounded on both -- which splits
    one sliding entry into two and is the conservative direction: it can only
    over-count events, never hide one.
    """
    by_slot: dict[int, list[float]] = {}
    for t, slot in locators:
        if t is None:
            continue
        by_slot.setdefault(slot, []).append(t)
    out = []
    for slot, ts in sorted(by_slot.items()):
        ts.sort()
        run = [ts[0]]
        for t in ts[1:]:
            if t - run[-1] > gap_s:
                out.append((run[0], run[-1], slot, len(run)))
                run = []
            run.append(t)
        out.append((run[0], run[-1], slot, len(run)))
    out.sort()
    return [f"slot {slot}  {int(a0 // 60)}:{a0 % 60:05.2f}"
            f"-{int(z0 // 60)}:{z0 % 60:05.2f}  ({n} frames)"
            for a0, z0, slot, n in out]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--hz", type=float, default=2.0,
                    help="sample rate; 2 Hz is what `reticle hud` stores")
    ap.add_argument("--from", dest="start", default=None, help="mm:ss")
    ap.add_argument("--to", dest="end", default=None, help="mm:ss")
    ap.add_argument("--dump", default=None, help="directory for example crops")
    ap.add_argument("--dump-reason", default=None,
                    help="only dump this reason (default: every one)")
    ap.add_argument("--keep", type=int, default=400,
                    help="locators retained per reason, for the cluster view")
    ap.add_argument("--gap", type=float, default=3.0,
                    help="seconds of quiet that ends a cluster (default 3)")
    a = ap.parse_args(argv)

    man = json.loads((STORE / "manifests" / f"{a.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    kf_roi = killfeed_roi(prof)
    if kf_roi is None:
        print("this profile has no killfeed ROI")
        return 1
    media = Path(src["path"])
    if not media.is_file():
        raise SystemExit(f"source media has moved: {media}")

    t0, t1 = parse_ts(a.start), parse_ts(a.end)

    # The overlay mask is calibrated exactly as `cmd_hud` does it -- from the
    # WHOLE capture, never from the window. A mask measured over thirty seconds
    # would call the killfeed itself persistent and mask out the entries.
    cap = cv2.VideoCapture(str(media))
    cal = []
    try:
        step = max(1, int((src["duration_ms"] or 0) / 40))
        for ms in range(0, int(src["duration_ms"] or 0), step):
            cap.set(cv2.CAP_PROP_POS_MSEC, ms)
            ok, fr = cap.read()
            if ok:
                cal.append(fr)
    finally:
        cap.release()
    kf_mask = overlay_mask(cal, kf_roi, W, H) if cal else None
    if kf_mask is not None:
        print(f"mask       {len(cal)} frames, "
              f"{(~kf_mask).mean() * 100:.1f}% of the ROI masked out")

    cen = Census(name=f"killfeed {a.session}", keep=a.keep)
    # The scoreline reader gets its own census in the same pass -- the decode is
    # 93% of the cost, so a second reader riding along is nearly free, and the
    # two rates are only comparable when they come from the same frames.
    ocr_cen = Census(name=f"scoreline {a.session}", keep=a.keep)
    templates = Templates.load(prof.name)
    sroi = scoreline_roi(prof)
    kept = {}
    dump = Path(a.dump) if a.dump else None
    x0, y0, x1, y1 = kf_roi.pixels(W, H)
    n_frames = 0
    for smp in sample_frames(str(media), a.hz, src["fps"], None):
        if t0 is not None and smp.t_ms < t0:
            continue
        if t1 is not None and smp.t_ms > t1:
            break
        n_frames += 1
        cen.saw("frames")
        before = dict(cen.counts)
        views = analyse_killfeed(smp.frame, kf_roi, W, H, kf_mask, prof.name,
                                 cen, smp.t_ms)
        read_scoreline(crop_gray(smp.frame, sroi, W, H), templates,
                       census=ocr_cen, t_ms=smp.t_ms)
        for v in views:
            kept[v.verdict] = kept.get(v.verdict, 0) + 1
        if dump is not None:
            for reason, n in cen.counts.items():
                if n == before.get(reason, 0):
                    continue
                if a.dump_reason and reason != a.dump_reason:
                    continue
                seen = len(list(dump.glob(f"{reason}_*.png"))) if dump.is_dir() else 0
                if seen >= 8:
                    continue
                dump.mkdir(parents=True, exist_ok=True)
                ts = f"{int(smp.t_ms // 60000):02d}-{smp.t_ms % 60000 / 1000:05.2f}"
                cv2.imwrite(str(dump / f"{reason}_{ts}.png"),
                            smp.frame[y0:y1, x0:x1])

    print(f"frames     {n_frames} at {a.hz:g} Hz")
    print()
    print(cen.table("bands"))
    print()
    print(f"as EVENTS -- consecutive drops of one reason within {a.gap:g}s and")
    print("one slot are ONE entry refused over several sampled frames, which is")
    print("the unit a missing kill is counted in:")
    for reason, _n in cen.counts.most_common():
        for line in clusters(cen.examples.get(reason, []), a.gap):
            print(f"           {reason:24s} {line}")

    print()
    print("kept as views, by verdict:")
    for k, n in sorted(kept.items(), key=lambda kv: -kv[1]):
        print(f"           {n:6d}  {k}")
    print()
    print("band refusals in guard order:", ", ".join(BAND_REFUSALS))
    print()
    for field in ("clock", "score_left", "score_right"):
        seen = ocr_cen.seen.get(field, 0)
        drops = {k.split(":", 1)[1]: v for k, v in ocr_cen.counts.items()
                 if k.startswith(field + ":")}
        got = seen - sum(drops.values())
        print(f"{field:12s} read {got}/{seen} "
              f"({got / seen * 100:.1f}%)" if seen else f"{field:12s} not seen")
        for reason, n in sorted(drops.items(), key=lambda kv: -kv[1]):
            print(f"             {n / seen * 100:5.1f}%  {n:6d}  {reason}")
    if dump is not None:
        print(f"crops      {dump}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
