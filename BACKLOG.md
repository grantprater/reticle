# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Active: death-refusals

- **Output:** a source-checked diagnosis of the five remaining identity refusals in `a06f04a0059f` round 4, with the first independent evidence gap identified and a bounded next fix or player question path.
- **Dependency:** the [two-name portrait review](teststore/death-round4-portraits/review-summary.md), stored portrait observations, and refused lineup rivals. Do not promote a best guess or loosen the portrait gate from its own output.
- **Completion:** account for all five refusals against source and stored witnesses, record disagreement and missing-observation counts, and keep the seven-event, two-correct-name baseline intact. Use the `death-refusals` contract.

## Completed

- **`death-portraits` (2026-09-23):** 3,392 raw portrait observations persisted on the shared scan, two source-verified named victims (Reyna and Phoenix), five identity refusals, zero wrong names or verified locations. [Review and comparison](teststore/death-round4-portraits/review-summary.md); [contract](docs/tasks.json).
- **`death-round4` (2026-09-23):** seven source-reviewed deaths, zero misses or extras in the fixed set, one named Phoenix victim, six identity refusals, and zero verified locations. [Review and before/after comparison](teststore/death-round4-v3/review-summary.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
