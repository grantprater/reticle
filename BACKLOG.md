# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Active: death-round4

- **Output:** `a06f04a0059f` round 4 death events and a review view that accounts for named, unresolved, missed, and extra deaths, with identity, location or refusal reason, and source evidence.
- **Dependency:** Inspect the real stored lineup and source windows; the oracle round harness is only a test fixture. Use the existing death adjudicator and event schema. No broader identity redesign.
- **Completion:** The `death-round4` contract runs a repeatable real command on the frozen window; a human review confirms at least one source-verified named death, coverage and errors, and a before/after comparison. Record the first failed perceptual dependency before expanding scope.

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in the death pilot. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after `death-round4` closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.