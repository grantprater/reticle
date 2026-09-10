r"""Score the self-fit labels: how often is an ACCEPTED fit the player.

    .\.venv\Scripts\python.exe prototypes\self_fit_eval.py c40d950031bb

The population is the reader's own accepted fits, sampled in two strata --
`crowded`, another read icon within 25 px, and `clear` -- at 100 each. The
strata are NOT equally common, so the sample rate is not the session rate:
every number here is reweighted by the stratum sizes recomputed from L1.

**Class provenance is unknown per row on the first pass.** The stamp meant to
record which class list a row was answered under never reached the writer, so
`spike` there may be a dropped spike or the carried badge, and site paint had
no class for most of the run. Later passes carry `class_set` and can say.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle.store import DEFAULT_STORE, Store  # noqa: E402

CROWD_PX = 25.0
#: `coincident` is not a failure and not a success: the ring holds two things
#: that cannot be separated, so there is no single right answer to score.
PLAYER = {"local_player"}
WRONG = {"teammate", "enemy", "spike", "spike_carried", "ability", "mark",
         "site_paint", "other", "nothing"}
AMBIGUOUS = {"coincident"}
EXCLUDED = {"unsure"}


def strata_sizes(rows: list[dict]) -> dict[str, int]:
    """How common each stratum is among ALL accepted fits, not in the sample."""
    counts = Counter()
    for r in rows:
        if r["self_x"] is None:
            continue
        near = any(
            r.get(f"ally{i}_x") is not None
            and np.hypot(r[f"ally{i}_x"] - r["self_x"],
                         r[f"ally{i}_y"] - r["self_y"]) <= CROWD_PX
            for i in range(4))
        counts["crowded" if near else "clear"] += 1
    return dict(counts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    args = ap.parse_args(argv)

    store = Store(args.store)
    path = next(p for p in Path(args.store).glob("l1/minimap/**/*.parquet")
                if args.session in str(p))
    rows = pq.read_table(path).to_pylist()
    sizes = strata_sizes(rows)
    total = sum(sizes.values())

    lp = Path(args.store) / "labels" / "self_fit" / f"{args.session}.jsonl"
    labels = {}
    for line in lp.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            labels[r["key"]] = r          # last row for a key wins
    print(f"{len(labels)} labelled candidates; "
          f"{total} accepted fits in the session")
    sets = Counter(r.get("class_set", "unstamped") for r in labels.values())
    print(f"class sets: {dict(sets)}")

    weighted = {"player": 0.0, "wrong": 0.0, "ambiguous": 0.0}
    print(f"\n{'stratum':9s} {'n':>4s} {'share':>7s}  "
          f"{'player':>8s} {'wrong':>8s} {'ambig':>8s}")
    for stratum in ("crowded", "clear"):
        sub = [r for r in labels.values()
               if r["stratum"] == stratum and r["answer"] not in EXCLUDED]
        if not sub:
            continue
        share = sizes.get(stratum, 0) / total
        c = Counter(r["answer"] for r in sub)
        p = sum(v for k, v in c.items() if k in PLAYER) / len(sub)
        w = sum(v for k, v in c.items() if k in WRONG) / len(sub)
        a = sum(v for k, v in c.items() if k in AMBIGUOUS) / len(sub)
        weighted["player"] += share * p
        weighted["wrong"] += share * w
        weighted["ambiguous"] += share * a
        print(f"{stratum:9s} {len(sub):4d} {share*100:6.1f}%  "
              f"{p*100:7.1f}% {w*100:7.1f}% {a*100:7.1f}%")

    print(f"\nreweighted over all accepted fits:")
    print(f"  the player            {weighted['player']*100:6.2f}%")
    print(f"  a DIFFERENT object    {weighted['wrong']*100:6.2f}%")
    print(f"  cannot be separated   {weighted['ambiguous']*100:6.2f}%")
    n = sum(1 for r in labels.values() if r["answer"] not in EXCLUDED)
    lo = weighted["wrong"] * (1 - 1.96 * np.sqrt(
        max(weighted["wrong"], 1e-9) * (1 - weighted["wrong"]) / n) /
        max(weighted["wrong"], 1e-9))
    hi = weighted["wrong"] + 1.96 * np.sqrt(
        weighted["wrong"] * (1 - weighted["wrong"]) / n)
    print(f"  wrong-object 95% interval roughly {max(0.0, lo)*100:.2f}"
          f"-{hi*100:.2f}% on n={n}")

    print("\nwhat the wrong ones were:")
    c = Counter(r["answer"] for r in labels.values() if r["answer"] in WRONG)
    for k, v in c.most_common():
        print(f"  {k:14s} {v:4d}")
    amb = [r for r in labels.values() if r["answer"] in AMBIGUOUS]
    if amb:
        print(f"\ncoincident, by stratum: "
              f"{dict(Counter(r['stratum'] for r in amb))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
