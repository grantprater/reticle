"""Locate camera wipes in STORED killfeed reads, so a frozen window can be cut
without watching the video first.

Freezing an evaluation on a second session needs confuser windows, and a
confuser is a moment the reader gets wrong for a reason a person can name. A
camera wipe is that: it paints both killfeed plate colours across the tray, so
`read_killfeed` claims entries on a frame holding none.

**The selector is a disagreement, not a threshold.** `kf_entries` is what one
frame held; `checks.entry_presence` is what persisted across frames. A wipe is
where they disagree -- the reader claims a row, the walk refuses it -- and
`kf_empty_bands` ranks the survivors, because a wash that paints plate colour
with no name text in it is the wipe's own signature.

Validated on `c40d950031bb`, whose two wipes were reviewed frame by frame
before this existed. Over 1945 stored rows it returns FOUR candidate instants,
and the two ranked highest are 504.0 s and 859.0 s -- the reviewed windows
`w5-confuser-wipe` (503.4-505.6 s) and `w6-confuser-wipe` (858.0-861.2 s). The
prediction was logged in `notes/predictions.jsonl` before the run.

What it does NOT do: say a candidate IS a wipe. Two of the four on that session
are unreviewed, carry no empty band, and could as easily be a short real entry
the 2 Hz walk refused. This narrows a 40-minute session to a handful of
instants to look at; the looking is still the review.

Reads stored data only. Never opens media.

    python tools/wipe_scout.py SESSION [--gap-ms 3000] [--top 12]
"""
import argparse
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.checks import entry_presence, sample_step_ms   # noqa: E402
from reticle.cli import _date_of, _dividers                 # noqa: E402
from reticle.store import Store                             # noqa: E402


def candidates(table, gap_ms: float = 3000.0) -> list[dict]:
    """Instants the reader claimed an entry and the walk refused, clustered."""
    times = table.column("t_ms").to_pylist()
    per_frame = table.column("kf_entries").to_pylist()
    empty = table.column("kf_empty_bands").to_pylist()
    adjudicated = {r["t_ms"]: r["entries"] for r in entry_presence(
        times, table.column("kf_entry_mask").to_pylist(),
        _dividers(table, "kf_entry_wx"))}

    refused = [(t, pf, empty[i] or 0)
               for i, (t, pf) in enumerate(zip(times, per_frame))
               if pf > 0 and adjudicated[t] == 0]
    out: list[dict] = []
    run: list[tuple] = []
    for row in refused:
        if run and row[0] - run[-1][0] > gap_ms:
            out.append(run)
            run = []
        run.append(row)
    if run:
        out.append(run)
    return sorted(
        ({"t0_ms": c[0][0], "t1_ms": c[-1][0], "n_instants": len(c),
          "max_claimed": max(r[1] for r in c),
          "empty_bands": sum(r[2] for r in c)} for c in out),
        key=lambda w: (w["empty_bands"], w["n_instants"]), reverse=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("session")
    ap.add_argument("--store", default=None)
    ap.add_argument("--gap-ms", type=float, default=3000.0,
                    help="instants further apart than this are separate windows")
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args(argv)

    store = Store(args.store) if args.store else Store()
    manifest = store.read_manifest(args.session)
    table = store.read_hud(args.session, _date_of(manifest))
    if table is None:
        raise SystemExit(f"no HUD reads for {args.session} -- run: reticle scan "
                         f"{args.session}")
    times = table.column("t_ms").to_pylist()
    step = sample_step_ms(times)
    found = candidates(table, args.gap_ms)

    print(f"session    {args.session}  ({manifest['source']['filename']})")
    print(f"reads      {len(times)} rows at {1000 / step:.1f} Hz, "
          f"{np.max(times) / 60000:.0f} min")
    print(f"candidates {len(found)} instants the walk refused a claimed entry\n")
    if not found:
        print("none. This session offers no confuser window at this rate.")
        return 0
    print(f"  {'window (s)':>21s} {'inst':>4s} {'claimed':>7s} {'empty':>5s}")
    for w in found[:args.top]:
        print(f"  {w['t0_ms'] / 1000:9.1f}-{w['t1_ms'] / 1000:9.1f} "
              f"{w['n_instants']:4d} {w['max_claimed']:7d} {w['empty_bands']:5d}")
    print("\nA candidate carrying empty bands is a wipe by signature. One without\n"
          "them may be a short real entry the walk refused -- look at both before\n"
          "freezing either as a confuser.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
