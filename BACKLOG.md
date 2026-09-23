# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Active: death-portraits

- **Output:** versioned stored killfeed portrait observations for `a06f04a0059f` round 4 and a rebuilt death-event review with at least two source-verified named victims.
- **Dependency:** the reviewed [one-name baseline](teststore/death-round4-v3/review-summary.md); source portraits must be observed before identity promotion. Preserve refused lineup rivals, unknowns, event provenance, and the shared HUD decode pass.
- **Completion:** the `death-portraits` contract passes and source review finds no new wrong name, missed death, or extra event. Record identity and location coverage, including refusals. Stop at the first upstream observation failure.

## Completed

- **`death-round4` (2026-09-23):** seven source-reviewed deaths, zero misses or extras in the fixed set, one named Phoenix victim, six identity refusals, and zero verified locations. [Review and before/after comparison](teststore/death-round4-v3/review-summary.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.