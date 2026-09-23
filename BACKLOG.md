# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Next (no contract yet): scoreboard-lineup

- **Output:** use accepted scoreboard openings as an independent agent witness for `lineup`, then store each disagreement with the top bar.
- **Why:** on `a06f04a0059f` the board names enemy Killjoy where the lineup accepts Clove, and ally Breach where the lineup refuses a Raze slot. The enemy pair at 284500/295500 ms is `interval_unordered` {Jett, Skye}; 332500 ms has no accepted opening after it (337000 enemy rows misaligned).
- **Before starting:** write the contract in `docs/tasks.json`, measure the gates on a second session, and read `lineup`'s ownership entry.

## Completed

- **`death-scoreboard-binding` (2026-09-23):** the stored scoreboard portrait box was inside the slab. `scoreboard-0.2.0` scores the table-edge cell against official agent art; `scoreboard-agent-0.1.0` gates whole openings and reads dimmed rows as dead. The `scoreboard_dim` death witness names Deadlock (281500) and Miks (295000, by elimination). The real round has seven deaths, four correct names, three enemy refusals with reasons, and zero wrong names or extras. [Resolution](docs/DEATH_SCOREBOARD_BINDING.md#resolution--scoreboard-agent-and-dimming-witness); [contract](docs/tasks.json).
- **`death-refusals` (2026-09-23):** all five refusals traced to raw portrait views, accepted/refused lineup candidates, count-only roster shrinks, and source composites. Player review identified Deadlock, Jett, Miks, Skye, and Iso; two portrait best matches disagree with source. Machine output remains seven deaths, two correct names, five refusals, zero verified locations. [Diagnosis](docs/DEATH_ROUND4_REFUSALS.md); [contract](docs/tasks.json).
- **`death-portraits` (2026-09-23):** 3,392 raw portrait observations persisted on the shared scan, two source-verified named victims (Reyna and Phoenix), five identity refusals, zero wrong names or verified locations. [Review and comparison](teststore/death-round4-portraits/review-summary.md); [contract](docs/tasks.json).
- **`death-round4` (2026-09-23):** seven source-reviewed deaths, zero misses or extras in the fixed set, one named Phoenix victim, six identity refusals, and zero verified locations. [Review and before/after comparison](teststore/death-round4-v3/review-summary.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
