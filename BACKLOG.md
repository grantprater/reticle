# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Active: death-scoreboard-binding

- **Output:** a stored, versioned scoreboard or top-bar witness that binds and correctly names at least one additional death in `a06f04a0059f` round 4.
- **Dependency:** the [five-refusal diagnosis](docs/DEATH_ROUND4_REFUSALS.md) identifies refused lineup slots, absent repeat views, and two wrong portrait best matches. The player reviewed all five source portraits; those answers check output and cannot serve as detector input.
- **Completion:** establish a row/binding baseline before changing a reader, then rerun the real seven-death command and source review with at least three correct machine names, zero new wrong names or extras, and explicit location refusals. Use the `death-scoreboard-binding` contract. If the independent binding cannot be derived, record the first failure and ask the player.

## Completed

- **`death-refusals` (2026-09-23):** all five refusals traced to raw portrait views, accepted/refused lineup candidates, count-only roster shrinks, and source composites. Player review identified Deadlock, Jett, Miks, Skye, and Iso; two portrait best matches disagree with source. Machine output remains seven deaths, two correct names, five refusals, zero verified locations. [Diagnosis](docs/DEATH_ROUND4_REFUSALS.md); [contract](docs/tasks.json).
- **`death-portraits` (2026-09-23):** 3,392 raw portrait observations persisted on the shared scan, two source-verified named victims (Reyna and Phoenix), five identity refusals, zero wrong names or verified locations. [Review and comparison](teststore/death-round4-portraits/review-summary.md); [contract](docs/tasks.json).
- **`death-round4` (2026-09-23):** seven source-reviewed deaths, zero misses or extras in the fixed set, one named Phoenix victim, six identity refusals, and zero verified locations. [Review and before/after comparison](teststore/death-round4-v3/review-summary.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
