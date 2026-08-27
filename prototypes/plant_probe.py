"""Test the L1-only plant rule against the pixels, with free controls.

    .\\.venv\\Scripts\\python.exe prototypes\\plant_probe.py 9acf02f98283

The rule under test
-------------------
`rounds.spike_planted` currently catches a one-sample clock discontinuity and
finds **1 plant in 24 rounds** on a06f04a0059f, where the true figure is many
times that. CLAUDE.md names the fix: the spike graphic replaces the round timer
for the whole 45 s, so a plant is a PERSISTENT state, and a state that lasts
45 s is ~90 samples at 2 Hz.

The cheap version of that needs **no new ROI and no video re-read**: the spike
graphic sits exactly where the digits are, so a planted round has no clock to
read, and `clock_ms is None` is already stored in L1. The rule is therefore

    a plant is the longest run of unreadable clock inside a round, when that run
    is at least PLANT_MIN_MS long and reaches the round's end.

Measured over 24 rounds of 9acf02f98283, runs meeting it cluster at 21-41 s and
end 0.5-2 s before the scoreline climbs; rounds that miss it top out under 15 s.
That is a clean separation, and it is also exactly the kind of true-looking
measurement this project has been burned by, so it gets checked against pixels.

Where the controls come from
----------------------------
**A readable clock means the spike is NOT planted**, because the digits and the
graphic occupy the same pixels. So every frame with `clock_ms is not None` is a
free negative control whose truth comes from `ocr.py` -- a different extractor,
written long before this question -- rather than from my eye or from the rule
being tested. That is the non-circularity: the controls establish that the
reader can see this ROI at this magnification, and the open items then measure
the rule.

Sampled in three pools, shuffled together by `glance`:

    control    clock readable            truth `no-spike`
    open       inside a claimed window   the rule says planted
    open       unreadable, outside one   the rule says not planted

If the sheet comes back VOID the reading is worthless and the rule is untested.
If it comes back VALID, the open answers give the rule's precision and recall
against pixels, on one session, which is the number to quote.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle import glance                                        # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from reticle.rounds import round_bounds                           # noqa: E402

STORE = Path.home() / "reticle-store"

# The constants and the run scan live in `reticle.rounds` and are IMPORTED, not
# copied. The first draft of this file duplicated them, so it was validating a
# rule that no longer matched the one shipping -- exactly the kind of drift a
# probe exists to prevent.
from reticle.rounds import PLANT_MIN_MS, PLANT_TAIL_MS, _plant     # noqa: E402


def plant_windows(ts, clock, rounds):
    """Per round: the plant verdict and window, straight from `rounds._plant`."""
    out = []
    for r in rounds:
        a, z = r["t_start_ms"], r["t_end_ms"]
        planted, s0 = _plant(ts, clock, a, z)
        # The window runs from the plant to the round's end.
        out.append({**r, "run_ms": (z - s0) if s0 is not None else 0,
                    "run_start": s0, "run_end": z if s0 is not None else None,
                    "planted": planted})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--controls", type=int, default=6)
    ap.add_argument("--in-window", type=int, default=8)
    ap.add_argument("--out-window", type=int, default=6)
    ap.add_argument("--zoom", type=int, default=4)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--dir", default=None)
    a = ap.parse_args(argv)
    rng = random.Random(a.seed)

    man = json.loads((STORE / "manifests" / f"{a.session}.json").read_text())
    src = man["source"]
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    sx0, sy0, sx1, sy1 = next(r for r in prof.rois if r.name == "scoreline").pixels(W, H)

    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={a.session}/hud.parquet")))
    t = hud.column("t_ms").to_pylist()
    clock = hud.column("clock_ms").to_pylist()
    rounds = plant_windows(t, clock, round_bounds(t, hud.column("score_left").to_pylist(),
                                                  hud.column("score_right").to_pylist()))
    n_p = sum(r["planted"] for r in rounds)
    print(f"{len(rounds)} rounds, rule says {n_p} planted ({n_p / len(rounds):.0%})")
    print(f"  run lengths, planted:     {sorted(round(r['run_ms']/1000) for r in rounds if r['planted'])}")
    print(f"  run lengths, not planted: {sorted(round(r['run_ms']/1000) for r in rounds if not r['planted'])}")

    def in_any_window(tm):
        return any(r["planted"] and r["run_start"] <= tm <= r["run_end"] for r in rounds)

    readable = [i for i in range(len(t)) if clock[i] is not None]
    inwin = [i for i in range(len(t)) if clock[i] is None and in_any_window(t[i])]
    outwin = [i for i in range(len(t)) if clock[i] is None and not in_any_window(t[i])]
    print(f"  frames: {len(readable)} readable, {len(inwin)} unreadable-in-window, "
          f"{len(outwin)} unreadable-outside")

    picks = ([(i, "no-spike") for i in rng.sample(readable, min(a.controls, len(readable)))]
             + [(i, None) for i in rng.sample(inwin, min(a.in_window, len(inwin)))]
             + [(i, None) for i in rng.sample(outwin, min(a.out_window, len(outwin)))])

    cap = cv2.VideoCapture(src["path"])
    items, meta = [], {}
    for i, truth in sorted(picks, key=lambda p: t[p[0]]):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t[i] / 1000.0 * float(src["fps"]))))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[sy0:sy1, sx0:sx1]
        h, w = crop.shape[:2]
        # Ring the centre third, where the digits and the graphic both live.
        box = (w // 3, 0, w // 3, h)
        key = f"t={t[i]}"
        meta[key] = {"readable": clock[i] is not None, "in_window": in_any_window(t[i])}
        items.append(glance.Item(image=crop, box=box, key=key, truth=truth,
                                 note=f"{t[i] / 1000:.0f}s"))
    cap.release()

    sheet = glance.present(
        items,
        question=("Scoreline centre. Is the RED SPIKE GRAPHIC there (planted), "
                  "or the round timer / something else (not planted)?"),
        classes=["spike", "no-spike"], zoom=a.zoom, pad=6, cols=4,
        truth_source=f"ocr.py clock_ms readable => digits present => not planted ({a.session})",
        domain="rounds", seed=a.seed)
    png = sheet.write(Path(a.dir) if a.dir else None)
    (Path(png).parent / f"{sheet.sheet_id}.probe.json").write_text(
        json.dumps({"session": a.session, "rule": {"PLANT_MIN_MS": PLANT_MIN_MS,
                                                   "PLANT_TAIL_MS": PLANT_TAIL_MS},
                    "frames": meta}, indent=2), encoding="utf-8")
    print(f"\n{png}\nsheet {sheet.sheet_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
