r"""Select the review population for scoring a lifecycle quarantine.

    .\.venv\Scripts\python.exe prototypes\quarantine_sample.py SIDECAR.minimap.jsonl OUT.jsonl

**The point of this file is that the selection is not the review tool's
business.** A page that knew which candidates were quarantined could show it,
and an answer given after seeing the pipeline's own opinion is worth less than
one given blind -- the seeding mistake in another costume.

So the population is chosen here and written out as plain `{t_ms,x,y}`:

* EVERY quarantined observation, because that is the thing being scored;
* a seeded random sample of the eligible ones, because a page holding only
  refusals is answered "nothing" all the way down and measures nothing. With
  both in it the pass yields a false-refusal rate AND a missed-phantom rate;
* shuffled together, so the order carries no signal either.

The seed is recorded in the output's first line so the draw can be repeated.
"""
from __future__ import annotations

import argparse
import json
import random
from pathlib import Path


def select(sidecar: Path, out: Path, controls: int = 25, seed: int = 20260908) -> dict:
    rows = [json.loads(line) for line in sidecar.read_text(encoding="utf-8").splitlines()]
    quarantined, eligible = [], []
    for row in rows[1:]:
        for adjudicated in row.get("adjudication", []):
            key = {"t_ms": row["t_ms"], "x": adjudicated["x"], "y": adjudicated["y"]}
            (eligible if adjudicated["eligible"] else quarantined).append(key)
    rng = random.Random(seed)
    # Dedupe the controls by position: 120 frames of one stationary icon is one
    # question asked 120 times, and the player's time is the scarce thing.
    seen, unique = set(), []
    for e in eligible:
        at = (e["x"], e["y"])
        if at not in seen:
            seen.add(at)
            unique.append(e)
    picked = rng.sample(unique, min(controls, len(unique)))
    population = quarantined + picked
    rng.shuffle(population)
    with out.open("w", encoding="utf-8") as f:
        for row in population:
            f.write(json.dumps(row) + "\n")
    return {"quarantined": len(quarantined), "controls": len(picked),
            "eligible_total": len(eligible), "seed": seed, "out": str(out)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sidecar", type=Path)
    ap.add_argument("out", type=Path)
    ap.add_argument("--controls", type=int, default=25)
    ap.add_argument("--seed", type=int, default=20260908)
    args = ap.parse_args()
    print(json.dumps(select(args.sidecar, args.out, args.controls, args.seed), indent=2))
