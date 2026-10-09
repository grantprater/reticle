r"""The acceptance harness's old command: a thin wrapper over `reticle.harness.run`.

The harness runs in process from the pipeline since 2026-10-09 (task
`harness-t1d-20261009`):

    .\.venv\Scripts\python.exe -m reticle acceptance lane --tag pgb [SESSION ...]

and `label`, `ally`, `smoke`, `glyph`, `marks`, `replay-score`,
`replay-abilities`, `budget` (with `budget-feats`, `budget-eye`,
`budget-eye-score`, `budget-levers`, `budget-sample`, `budget-peek`),
`hook`, `hook-report`, `arms-report`, `draw-persist`, `draw-smokes`,
`slots`, `ability-lane` and `summary`. `reticle/harness/run.py` holds the commands and their record;
`reticle/acceptance.py` holds the core. This file forwards its old
subcommands there and keeps the names its callers and tests import.
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from reticle import acceptance as acc  # noqa: E402
from reticle.acceptance import (ACCEPTANCE_VERSION, AMBIG_CM, CLASS_OUTCOMES, DROPPED,  # noqa: E402,F401
                                LIFE_TAIL_MS, MEASURED_LIFE, NEAR_CM, NOT_JOINED, OUTCOMES, Q_MARK_MS,
                                WINDOW_MS, WINDOW_STEP_MS, ambiguous_classes, assign_one_to_one,
                                child_family, child_life, child_window_dist, claim_outcome, drawn_by_fact,
                                entity_key, frame_samples, hold_duplicate_marks, icon_outcomes,
                                lane_questions, nothing_derivation, outcome_of, short_reason)

# Moved into the acceptance harness (`reticle/harness/run.py`, task
# harness-t1d-20261009); these names stay for this module's callers.
from reticle.harness.run import (  # noqa: E402,F401
    _assigned, _boot_pooled, _boot_pooled_diff, _budget_tables, _census, _claim_key, _class_block,
    _class_lane, _dist, _empty_join, _finds, _finish_blocks, _frames_on_grid, _grid_finds,
    _instrument, _join_entities, _lane_rows, _live_rounds, _mark_truth, _metric_name,
    _metric_values, _norm, _pool_blocks, _pool_classes, _pool_lane, _pool_name, _pool_step,
    _prepare, _print, _print_blocks, _print_classes, _print_coverage, _print_replay,
    _ra_bolt_truth, _ra_cast_score, _ra_labels, _ra_pair, _ra_planted, _ra_shape, _ra_ults,
    _recall_children, _recall_marks, _recall_players, _record, _record_classes, _record_paired,
    _record_step, _refuse, _replay_enemies, _replay_spike, _score_finds, _session_census,
    _step_summary, _stream, _stream_stamp, _to_cm, _truth_ctx, _truth_under, _write_blocks,
    _write_doc, ARMS, budget_class, CLAIMERS, BUDGET_REFINED, build_lane, claims, DEV, FRAME_HALF_STEP, lane,
    FROZEN_DEV, main, OUT, record_replay_abilities, record_replay_score, replay_abilities_score,
    replay_ability_classes, REPLAY_CLAIMS, replay_classes, REPLAY_LEFT_OUT, replay_score,
    run_budget, run_budget_tool, run_label, run_lane, run_paired, run_replay_abilities,
    run_replay_score, run_slots, run_step, SCORED, slot_regions, SLOTS_VERSION, step_ally, STEP_FUNCS, step_glyph, step_marks, step_smoke,
    STEP_STREAMS, STORE, TASK, TASK9, truth_under, VERSION)

_player_desc = acc.player_desc
_child_desc = acc.child_desc
_death_and_swap_marks = acc.death_and_swap_marks
_median = acc.median_or_none


if __name__ == "__main__":
    raise SystemExit(main())
