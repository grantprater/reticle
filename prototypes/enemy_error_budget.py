r"""The enemy lane's error budget: one cause per miss and per extra, ranked.

Moved into the acceptance harness on 2026-10-09 (`reticle/harness/budget.py`,
task `harness-t1d-20261009`): every command, run as `reticle acceptance
budget` and `budget-*`. This file imports them back.

Task `enemy-error-budget-20261007` (rows EB in the store's
`notes/predictions.jsonl`). The enemy lane (`minimap_object` rows reread by
`teardrop_refusals.py reread`) scored against T1d (`t1_draw_rule`, through
`teardrop_refusals.py score`) leaves misses (T1d-drawn enemies with no
accepted icon within 3 m) and extras (accepted icons with no T1d-drawn living
enemy within 3 m). This prototype gives each exactly one cause class, counts
the classes per match and pooled with round-bootstrap intervals, and draws
crops for the eye check and a stratified sample for the player's labelling
pass. The player's framing: "Systematic error explanation is basically the
hotspot analysis of accuracy increase."

* `feats SESSION --tag TAG` -- per miss and per extra (and 800 sampled hits,
  the pixel cuts' calibration), the candidate funnel at the place from the
  tag's frame rows (accepted, refused with its stored reason, "?" marks,
  other red blobs, X marks, in widget px, in the frame and two frames either
  side), the stored pings and smokes, truth context from replay truth
  (`t1_draw_rule.RealDrawMatch`, rule T1d: sight onset, tail and run, raw and
  smoke-filtered sight, death times, every living player's place, the
  frame-to-grid join offset and the truth place at the frame's own time),
  and the pixels at the place from the minimap roi_cache: soft redness,
  violet, departure from the baked reference grey, and the widget's tint.
  Written to `OUT/TAG/feats_SESSION.jsonl`.
* `budget --tag TAG [SESSION ...]` -- the classes (`MISS_ORDER`,
  `EXTRA_ORDER`: the first that holds, so assignment is deterministic), the
  Pareto per match and pooled with 95% intervals from a bootstrap over rounds
  (stratified by match); the counts must sum to the scorer's misses and
  extras or the run stops. `--record` writes the metrics ledger (series
  `enemy_error_budget`, part `budget/TAG`).
* `eye --tag TAG` -- up to `EYE_N` native-resolution crops per class at or
  above `EYE_SHARE` in any scope, spread over the matches, ranked by a hash
  of each row's identity (a class's crops move only where its membership
  does): `OUT/TAG/eye/SET__CLASS/` holds each window raw (`*_native.png`)
  and a sheet beside a nearest-neighbour enlargement with the overlays
  (display only): the row's truth place magenta, other enemies' places
  purple, allies' blue squares, accepted icons green, refused candidates
  yellow X, "?" orange squares, red X marks red crosses, pings cyan.
* `eye-score --tag TAG` -- the agent's verdicts (`OUT/TAG/eye_verdicts.json`:
  reader, truth, ambiguous, mislabelled per crop) per class, the reader
  share with a Wilson interval and weighted to class size per match.
* `levers --tag TAG` -- each lever's class group (`LEVERS`) and its bound on
  the hit rate or the extras if fully fixed, and weighted by the eye check.
* `sample --tag TAG` -- the stratified label sample (`SAMPLE_PLAN`, no
  labels) for the player's labelling pass.
* `peek --tag TAG --expr EXPR --name NAME` -- crops of rows a Python filter
  over the feature row picks (exploration only).

Classes are the agent's, by rule and by eye, never the player's labels.
Stored rows, replay truth and the minimap roi_cache only; no decode. The
held-out capture (cea8ecbc94ab) is refused before any row is read. Not wired
(`"wire": "no"`): an evaluation over replay truth; the levers it names live
in `reticle/minimap_objects.py`, `reticle/teardrop.py` and the T1d rule.

The budget reads enemy players only (AGENTS.md, "Replay truth covers every
entity"). It inherits `teardrop_refusals.score`'s players-only sets and joins
no ability child, ally player or spike, so an extra of `other`, `e38_*`,
`other_ally_stack` or `dead_enemy` may lie on another real entity, such as
Tejo's Stealth Drone [domain:abilities/tejo-stealth-drone-enemy-minimap-icon].
`question_acceptance.py label` holds the class-aware join; read an extra's
entity there before charging the reader with it.

The commands moved into the one harness on 2026-10-09 (harness step 9):
`question_acceptance.py budget --tag TAG` starts each extra from
`truth_under` and keeps this players-only budget as its control; every
other command `X` here is `budget-X` there, and this module's `main`
forwards to it. The features, classes and crops below stay here as the
harness's library.

    python prototypes/enemy_error_budget.py feats 9acf02f98283 --tag v0
    python prototypes/enemy_error_budget.py budget 9acf02f98283 --tag v0
    python prototypes/enemy_error_budget.py feats 9acf02f98283 c817691bcd15 d3dcfb182ab1 --tag b1
    python prototypes/enemy_error_budget.py budget --tag b1 --record
    python prototypes/enemy_error_budget.py eye --tag b1
    python prototypes/enemy_error_budget.py eye-score --tag b1 --record
    python prototypes/enemy_error_budget.py levers --tag b1 --record
    python prototypes/enemy_error_budget.py sample --tag b1
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import zlib
from collections import Counter, defaultdict
from pathlib import Path

for _v in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_v, "1")

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

import teardrop_refusals as tr  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

# Moved into the acceptance harness (`reticle/harness/budget.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.budget import (  # noqa: E402,F401
    _boot, _disc_stats, _extra_class, _frames, _load_feats, _miss_class, _nearest, _pts, _r,
    ADJ_FRAMES, BLUE_ICON, budget, CAPTURES, classify, draw_crops, EXTRA_ORDER, eye_crops, EYE_N,
    eye_score, EYE_SHARE, FALSE_ACCEPT, feats, FG_ICON, label_sample, levers, LEVERS, MISS_ORDER,
    N_BOOT, NEAR_CM, OFFSET_K, OUT, PING_R, RED_ICON, RED_NONE, refuse, SAMPLE_PLAN, SEED,
    SHIFT_MS, SRC, STACK_R, STORE, TAIL_SPLIT_MS, TASK, TINT, VERDICTS, VERSION)

DEV = tr.DEV
FROZEN_DEV = tr.FROZEN_DEV


def main(argv=None) -> int:
    """The commands moved into the one harness (step 9): `budget` is
    `question_acceptance.py budget` (class-aware, with this players-only
    budget as its control); every other command `X` is `budget-X` there."""
    import question_acceptance as qa
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("feats", "eye", "sample", "levers", "eye-score", "peek"):
        argv[0] = "budget-" + argv[0]
    return qa.main(argv)


if __name__ == "__main__":
    sys.exit(main())
