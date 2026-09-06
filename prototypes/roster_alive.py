r"""Validate the alive-count read against LABEL-FREE invariants, per round.

    .\.venv\Scripts\python.exe prototypes\roster_alive.py <session>

`reticle/roster.py` reads alive counts off the roster bars. Its detail
threshold was measured on six frames of one session, which is exactly the
evidence base this repo has been burned by before -- so it is checked here
against things that must be true of any correct reader, on every round of every
session, with no hand labels anywhere:

    starts at 5    a round opens with both teams whole
    non-increasing within a round -- with a NAMED exception, since Sage and
                   Clove revive and CLAUDE.md records that those deaths count
    <= 5           never more players than a team has
    readable       how often the read refuses, which is a cost not a fault

**Why per-round and not per-frame**: an alive count is only constrained inside
a round. Across a round boundary it resets to 5, and between rounds the bar
shows a buy phase, so a global monotonicity check would fail everywhere for
reasons that have nothing to do with the reader.

This uses SEEKS, like `plant_spike.py`, for the same reason: a handful of
scattered coarse probes per round, not thousands of dense ones. Validating the
reader costs no decode of any capture.
"""
from __future__ import annotations

import argparse
import glob
import pathlib
import sys

import cv2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from reticle.checks import track_entries                          # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402
from reticle.roster import alive_counts                           # noqa: E402
from reticle.rounds import build_rounds                           # noqa: E402
from reticle.store import Store                                   # noqa: E402

PROBES = 6


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--probes", type=int, default=PROBES)
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    store = Store()
    man = store.read_manifest(a.session)
    src = man["source"]
    prof = get_profile(man["source_profile"])
    w, h = int(src["width"]), int(src["height"])

    hits = glob.glob(str(store.root / "l1" / "hud" / "date=*" /
                         f"session={a.session}" / "hud.parquet"))
    if not hits:
        raise SystemExit(f"no stored HUD for {a.session}")
    date = pathlib.Path(hits[0]).parts[-3].split("=", 1)[1]
    import pyarrow.parquet as pq
    rounds = build_rounds(pq.read_table(store.hud_path(a.session, date)))

    cap = cv2.VideoCapture(src["path"])
    if not cap.isOpened():
        raise SystemExit(f"could not open {src['path']}")

    # ---- the CROSS-CHANNEL check ---------------------------------------
    # The roster is STATE and the killfeed is EVENTS, and they are read off
    # different pixels by different code. Deaths in a round must equal the
    # drop in the two alive counts -- an identity neither channel can satisfy
    # on its own, and the densest validity signal in the project: it checks
    # every round where the scoreboard offers at most fifty checks a match.
    #
    # DIRECTION, declared because it must not silently reverse: this run is a
    # CALIBRATION of the roster reader against the killfeed. Once calibrated
    # the roles swap and the killfeed becomes the audited channel. Using each
    # to validate the other in the same breath is the circularity that has
    # already cost this repo two results.
    tb = pq.read_table(store.hud_path(a.session, date))
    t_all = tb.column("t_ms").to_pylist()
    ent = track_entries(t_all, tb.column("kf_entry_mask").to_pylist(),
                        tb.column("kf_entry_wx").to_pylist()
                        if "kf_entry_wx" in tb.column_names else None)
    ent_t = [e["t_first"] for e in ent if e.get("counted")]

    n_probe = n_read = 0
    starts_ok = starts_seen = 0
    mono_bad = over_five = 0
    xc_ok = xc_seen = 0
    xc_diffs: list[int] = []
    if not a.quiet:
        print(f"{'#':>3}  {'ally':<26}{'enemy':<26}")
    for i, r in enumerate(rounds):
        a0, z0 = r["t_start_ms"], r["t_end_ms"]
        seq_a, seq_e = [], []
        for k in range(a.probes):
            # NOT from the round's first instant. `build_rounds` bounds a
            # round from the scoreline's step, which puts the buy phase and
            # the round transition inside it -- and the roster is not drawn
            # for the new round yet. The first pass at this probed from 0.06
            # and read "starts at 5" on 5 of 22 team-rounds, every failure
            # being probe 0; from 0.20 the same reader and the same frames
            # answer the invariant. Same defect as reading an ability series
            # against the whole axis instead of its own window.
            f = 0.20 + 0.72 * k / max(1, a.probes - 1)
            cap.set(cv2.CAP_PROP_POS_MSEC, a0 + (z0 - a0) * f)
            ok, fr = cap.read()
            n_probe += 1
            if not ok:
                seq_a.append(None); seq_e.append(None); continue
            ca, ce = alive_counts(fr, prof, w, h)
            n_read += (ca is not None) + (ce is not None)
            seq_a.append(ca); seq_e.append(ce)
        for seq in (seq_a, seq_e):
            v = [x for x in seq if x is not None]
            if not v:
                continue
            if seq[0] is not None:
                starts_seen += 1
                starts_ok += seq[0] == 5
            over_five += sum(1 for x in v if x > 5)
            mono_bad += sum(1 for p, q in zip(v, v[1:]) if q > p)
        # Deaths from the OTHER channel, aligned to EACH PROBE'S OWN INSTANT.
        #
        # The first version compared deaths over the WHOLE round against a
        # roster reading taken at 0.92 of it, and disagreed on 19 of 20 rounds
        # with the killfeed always ahead -- because a round frequently ends in
        # a wipe, and every death after the last probe was being counted
        # against a roster that had not seen it yet. The same span defect as
        # probing the buy phase for "starts at 5", and as butting a refinement
        # window against a run's measured end. Three times in one session, in
        # three different files: **align the window to the question before
        # reading anything out of it.**
        d = None
        for k, (ca, ce) in enumerate(zip(seq_a, seq_e)):
            if ca is None or ce is None:
                continue
            t_k = a0 + (z0 - a0) * (0.20 + 0.72 * k / max(1, a.probes - 1))
            # Count from the FIRST PROBE, not from the round's nominal start.
            # A killfeed entry stays on screen for seconds, so the previous
            # round's final kills are still displayed well into this one and
            # `t_first` puts them inside this round's window. The roster says
            # so itself: it reads 5/5 at the first probe in every round, so
            # anything the killfeed reports before that instant did not happen
            # in this round. Using one channel's own reading to bound the
            # other's window is legitimate here -- it is a TIME alignment, not
            # the quantity under test.
            t_lo = a0 + (z0 - a0) * 0.20
            deaths = sum(1 for t in ent_t if t_lo <= t <= t_k)
            d = deaths - ((5 - ca) + (5 - ce))
            xc_seen += 1
            xc_ok += d == 0
            xc_diffs.append(d)
        if not a.quiet:
            fmt = lambda s: " ".join("?" if x is None else str(x) for x in s)
            print(f"{i:>3}  {fmt(seq_a):<26}{fmt(seq_e):<26}"
                  f"last diff {'?' if d is None else f'{d:+d}'}")

    print()
    print(f"probes      {n_probe} frames, {n_read}/{n_probe * 2} slot-reads "
          f"answered ({n_read / max(1, n_probe * 2) * 100:.0f}%)")
    print(f"starts at 5 {starts_ok}/{starts_seen} team-rounds "
          f"({starts_ok / max(1, starts_seen) * 100:.0f}%)")
    print(f"increases   {mono_bad}   (a rise inside a round is a misread, "
          f"or a Sage/Clove revive)")
    print(f"over five   {over_five}")
    if xc_seen:
        import collections
        hist = collections.Counter(xc_diffs)
        print()
        print(f"cross-channel  killfeed deaths vs roster drop, per PROBE")
        print(f"  agree      {xc_ok}/{xc_seen} probes "
              f"({xc_ok / xc_seen * 100:.0f}%)")
        print(f"  diffs      " + ", ".join(f"{k:+d} x{v}"
                                           for k, v in sorted(hist.items())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
