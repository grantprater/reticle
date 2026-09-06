r"""Does the self track's jump rate SPLIT once identity constrains it?

    .\.venv\Scripts\python.exe prototypes\jump_census.py [<session> ...]

The first test the identity-conditional model has to pass (design doc §6), and
it needs no new data. `prototypes/CLAUDE.md` quotes **jumps > 60 px/s at
5.0% / 3.3% / 3.8%** across the geometry-validated sessions and reads it as the
track's residual error rate -- while recording elsewhere that the figure
conflates tracking error, teleports and dashes, of which only the first is a
defect. `reticle/track.py` makes that computable.

Three results, and the second falsifies part of the model
-----------------------------------------------------------
Measured over 102,239 raw steps on the five sessions with an `l1/minimap`
table (Ascent ×2, Lotus ×2, Split).

**1. The speed distribution has no dash mode, so `walker_dash` cannot
currently be validated.** 11.1% of raw steps exceed `RUN_PX`, and above the
ceiling the distribution is a smooth decay rather than bimodal:

    45-60 px/s   40.7% of refused steps
    60-80        26.8%
    80-100       12.3%
    100-140       8.9%
    140-180       1.8%
    >800          5.7%     <- physically impossible; 8218 px/s at the max

75.2% of refused steps sit within 2× the walk ceiling. That is the signature of
**jitter around a threshold**, not of a distinct fast behaviour. At
`DASH_PX_S = 4 × RUN_PX` the dash class absorbed 90.5% of all refusals, which
is a bound explaining everything rather than a model explaining something. It
is reported here as UNMEASURABLE rather than as a count. Tightening the bound
does not help: there is no gap to put it in.

**2. `filter_track` cannot tell a teleport from a phantom, and the stake is
6,341 observations.** The filter rejects above `RUN_PX × 1.6` (72 px/s), and
of the 11,599 raw observations it drops across these sessions, **54.7% are at
teleport distance** (≥ 200 widget px) from the last surviving point.

That is a CEILING, not a count of teleports -- most are certainly gross
misdetections, since 5.7% of refusals are at physically impossible speeds. The
finding is that **the two are indistinguishable to a fixed threshold**, which
is precisely what identity is for: if the agent cannot teleport, every one of
those is a phantom and the filter is right; if the agent can, the filter is
destroying real positions and no downstream number knows.

**3. The binding input is not in the store.** None of the five sessions
records which agent the player played. So the model cannot be applied to real data
today, and the gap is one ingest tag plus a read that already half exists --
`minimap_portrait.bootstrap` names the enemy lineup from scoreboard art, and
the same machinery over the ally side would name his own.

What this file therefore reports
--------------------------------
The RAW distribution, and what the filter drops. It deliberately does not
print a "defect rate": with no dash mode and no agent, the split between
`dash`, `teleport` and `unexplained` is not yet a measurement of anything, and
quoting one would be the confident-wrongness this repo keeps paying for.
"""
from __future__ import annotations

import argparse
import collections
import glob
import math
import pathlib
import sys

import pyarrow.parquet as pq

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from reticle import track                                        # noqa: E402
from reticle.minimap import (RUN_PX, filter_track, minimap_roi_px,  # noqa: E402
                             widget_scale)
from reticle.profiles import get_profile                         # noqa: E402
from reticle.store import Store                                  # noqa: E402

#: The rate the record quotes, reproduced before anything is split.
LEGACY_PX_S = 60.0
#: Histogram edges, widget px/s. Chosen to straddle the walk ceiling and to
#: separate "just over" from "impossible" -- the two ends that turned out to
#: matter.
EDGES = (60, 80, 100, 140, 180, 250, 400, 800, float("inf"))


def steps(t_ms, xs, ys):
    """Consecutive OBSERVED pairs. A null breaks the chain rather than
    bridging it -- interpolating across a hole and then measuring the step is
    how a gap becomes a fake jump."""
    prev = None
    for t, x, y in zip(t_ms, xs, ys):
        if x is None or y is None:
            prev = None
            continue
        if prev is not None:
            dt = (t - prev[0]) / 1000.0
            if dt > 0:
                yield dt, math.dist(prev[1:], (x, y))
        prev = (t, x, y)


def sessions(store, want):
    for f in sorted(glob.glob(str(store.root / "l1" / "minimap" / "date=*" /
                                  "session=*" / "minimap.parquet"))):
        parts = pathlib.Path(f).parts
        sid = parts[-2].split("=", 1)[1]
        if want and sid not in want:
            continue
        yield sid, f


#: The classes worth crossing against the default gate: everything a PLAYER
#: might be. The rest of `track.CLASSES` describes placed objects, which never
#: reach `filter_track` -- it filters the self track.
MOTION_CLASSES = ["walker", "walker_dash", "walker_teleport"]


def motion_cost(store, rows) -> int:
    """What opting a session in to a motion class costs and buys, per class.

    The parameter landed on 2026-09-06 and this is the number that says what
    taking it up would do. It is a KEEP RATE, not a defect rate: none of these
    sessions records which agent was played, so no column here is the right
    one -- the point is the size and the SIGN of each move.
    """
    print("observations kept by `filter_track`, default gate vs a motion class."
          "\nThe default is RUN_PX x 1.6; `admits` has no such slack.\n")
    print(f"{'session':<14}{'obs':>7}{'default':>9}"
          + "".join(f"{c:>17}" for c in MOTION_CLASSES))
    agg = {c: 0 for c in MOTION_CLASSES}
    tot_obs = tot_def = 0
    for sid, f in rows:
        man = store.read_manifest(sid)
        src = man["source"]
        prof = get_profile(man["source_profile"])
        x0, _, x1, _ = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
        sc = widget_scale(x1 - x0)
        tb = pq.read_table(f)
        raw = list(zip(tb.column("t_ms").to_pylist(),
                       tb.column("self_x").to_pylist(),
                       tb.column("self_y").to_pylist()))
        obs = {round(p[0], 3) for p in raw if p[1] is not None}
        step_ms = (raw[1][0] - raw[0][0]) if len(raw) > 1 else 66.0

        def measured(pts):
            return sum(1 for q in pts if round(q[0], 3) in obs)

        base = measured(filter_track(raw, step_ms, sc))
        tot_obs += len(obs)
        tot_def += base
        cells = []
        for c in MOTION_CLASSES:
            k = measured(filter_track(raw, step_ms, sc, motion=c))
            agg[c] += k
            cells.append(f"{k:>10} {k - base:+6d}")
        print(f"{sid:<14}{len(obs):>7}{base:>9}" + "".join(cells))
    print(f"\n{'POOLED':<14}{tot_obs:>7}{tot_def:>9}"
          + "".join(f"{agg[c]:>10} {agg[c] - tot_def:+6d}" for c in MOTION_CLASSES))
    print(f"{'':<14}{'':>7}{tot_def / tot_obs * 100:>8.1f}%"
          + "".join(f"{agg[c] / tot_obs * 100:>16.1f}%" for c in MOTION_CLASSES))
    print("\nRead the deltas as a CASCADE, not as a count of events. A refusal\n"
          "re-anchors the comparison to the last KEPT point, so admitting one\n"
          "jump changes every comparison after it -- `walker_teleport` +835 is\n"
          "not 835 teleports.")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("sessions", nargs="*")
    ap.add_argument("--motion", action="store_true",
                    help="cross the default gate against each motion class")
    a = ap.parse_args(argv)

    store = Store()
    rows = list(sessions(store, a.sessions))
    if not rows:
        raise SystemExit("no l1/minimap tables -- run `reticle scan` first")

    if a.motion:
        return motion_cost(store, rows)

    speeds, hist = [], collections.Counter()
    tot_drop = tot_tele = tot_obs = 0
    print(f"filter_track rejects above RUN_PX x 1.6 = {RUN_PX * 1.6:g} px/s; "
          f"a teleport is >= {track.TELEPORT_PX:g} widget px\n")
    print(f"{'session':<14}{'steps':>8}{'>60px/s':>9}{'obs':>8}{'kept':>8}"
          f"{'dropped':>9}{'tele-consistent':>17}")
    for sid, f in rows:
        man = store.read_manifest(sid)
        src = man["source"]
        prof = get_profile(man["source_profile"])
        x0, _, x1, _ = minimap_roi_px(prof, int(src["width"]), int(src["height"]))
        sc = widget_scale(x1 - x0)
        tb = pq.read_table(f)
        t_ms = tb.column("t_ms").to_pylist()
        xs = tb.column("self_x").to_pylist()
        ys = tb.column("self_y").to_pylist()

        n = legacy = 0
        for dt, d in steps(t_ms, xs, ys):
            v = d / dt / sc
            n += 1
            speeds.append(v)
            if v > LEGACY_PX_S:
                legacy += 1
            if v > RUN_PX:
                for e in EDGES:
                    if v <= e:
                        hist[e] += 1
                        break

        raw = list(zip(t_ms, xs, ys))
        obs = [p for p in raw if p[1] is not None]
        step_ms = (raw[1][0] - raw[0][0]) if len(raw) > 1 else 66.0
        kept = filter_track(raw, step_ms, sc)
        keptset = {round(p[0], 3) for p in kept}
        drop = tele = 0
        last = None
        for t, x, y in obs:
            if round(t, 3) in keptset:
                last = (t, x, y)
                continue
            drop += 1
            if last is not None and math.dist(last[1:], (x, y)) >= track.TELEPORT_PX * sc:
                tele += 1
        tot_drop += drop
        tot_tele += tele
        tot_obs += len(obs)
        print(f"{sid:<14}{n:>8}{legacy / max(1, n) * 100:>8.1f}%{len(obs):>8}"
              f"{len(kept):>8}{drop:>9}{tele:>13} "
              f"({tele / max(1, drop) * 100:>3.0f}%)")

    speeds.sort()
    n = len(speeds)
    print(f"\npooled {n} steps, {tot_obs} observations, "
          f"{tot_drop} dropped by the filter")
    print(f"  speed percentiles (widget px/s, RUN_PX={RUN_PX:g}):")
    for q in (50, 90, 95, 99, 99.9):
        print(f"    p{q:<5} {speeds[int(n * q / 100)]:8.1f}")
    print(f"    max    {speeds[-1]:8.1f}")

    above = sum(hist.values())
    print(f"\n  above the walk ceiling: {above} ({above / n * 100:.1f}% of steps)")
    prev = RUN_PX
    for e in EDGES:
        if hist[e]:
            lab = f"{prev:g}-{e:g}" if e != float("inf") else f">{prev:g}"
            print(f"    {lab:>10} {hist[e]:6d}  {hist[e] / above * 100:5.1f}%")
        prev = e
    # Counted from the speeds themselves, not summed from buckets -- the 80-100
    # bucket straddles 2x the ceiling, so reading this off the histogram gave
    # 67.6% where the exact count is 75.2%. Seven points of drift between two
    # printings of one quantity, which is the disease this repo keeps treating.
    near = sum(1 for v in speeds if RUN_PX < v <= 2 * RUN_PX)
    print(f"\n  within 2x the ceiling: {near} ({near / above * 100:.1f}% of refused)"
          f"  -- a smooth decay, no dash mode")
    print(f"  dropped by the filter at teleport distance: {tot_tele} "
          f"({tot_tele / max(1, tot_drop) * 100:.1f}%)")
    print("\nNo defect rate is printed. With no dash mode and no agent recorded\n"
          "for any of these sessions, the split is not yet a measurement.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
