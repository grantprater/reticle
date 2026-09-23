# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Agreed order (2026-09-23)

Steps 1 and 2 are done. Step 1 measured scoreboard availability from stored rows: 33 of 52 sessions have no scoreboard rows, and in the 17 with rows and rounds, 326 of 348 rounds have at least two separate Tab holds. Usable openings around each death remain unmeasured outside `a06f04a0059f`.

3. **Corpus rescan.** `scoreboard-0.5.0` fixes the reader placing the enemy block on the ally block ([details](docs/SCOREBOARD_LINEUP.md#reader-defect-found)). Rescan the other 15 scoreboard sessions (about 10 minutes each) and record board-constrained lineups against the top bar across the corpus. Check each changed name against source before trusting the corpus figure.
4. **Named alive sets:** check roster counts and death verdicts against each accepted opening's lit and dim sets.
5. **Killers:** every death verdict has `killer: null`. The killfeed stores killer portraits; compare them over the board-constrained candidates through `adjudication.identity`.
6. **Minimap identity:** name minimap icons over the five candidates per side; the stored minimap for `a06f04a0059f` is stale (`minimap-0.4.0`).

The player answered the dimming question: dimmed means currently dead, a Sage revive lights the row again, and Run It Back is not expected to dim [domain:rounds/scoreboard-dim-is-dead]. Clove before Not Dead Yet and a downed KAY/O remain unknown; capture one of each and ask when it occurs.

**Remaining identity drift to retire:** `Lineup.player` still combines the tray, self icon and top bar itself before publishing claims (the `player-agent` exit).

## Completed

- **`scoreboard-lineup` (2026-09-23):** `scoreboard-0.3.0` stores every agent's score per row; `identity.board_side_sets` names each side from agreeing openings and `identity.lineup_with_board` restricts the top-bar assignment to that set. Both tested sessions name all ten slots, matching source; the top bar's accepted Clove in `a06f04a0059f` was Jett's slot. Round 4 names all seven deaths correctly; Jett by scoreboard elimination with zero independent channels recorded. [Results](docs/SCOREBOARD_LINEUP.md); [contract](docs/tasks.json).
- **`death-scoreboard-binding` (2026-09-23):** the stored scoreboard portrait box was inside the slab. `scoreboard-0.2.0` scores the table-edge cell against official agent art; `scoreboard-agent-0.1.0` gates whole openings and reads dimmed rows as dead. The `scoreboard_dim` death witness names Deadlock (281500) and Miks (295000, by elimination). The real round has seven deaths, four correct names, three enemy refusals with reasons, and zero wrong names or extras. [Resolution](docs/DEATH_SCOREBOARD_BINDING.md#resolution--scoreboard-agent-and-dimming-witness); [contract](docs/tasks.json).
- **`death-refusals` (2026-09-23):** all five refusals traced to raw portrait views, accepted/refused lineup candidates, count-only roster shrinks, and source composites. Player review identified Deadlock, Jett, Miks, Skye, and Iso; two portrait best matches disagree with source. Machine output remains seven deaths, two correct names, five refusals, zero verified locations. [Diagnosis](docs/DEATH_ROUND4_REFUSALS.md); [contract](docs/tasks.json).
- **`death-portraits` (2026-09-23):** 3,392 raw portrait observations persisted on the shared scan, two source-verified named victims (Reyna and Phoenix), five identity refusals, zero wrong names or verified locations. [Review and comparison](teststore/death-round4-portraits/review-summary.md); [contract](docs/tasks.json).
- **`death-round4` (2026-09-23):** seven source-reviewed deaths, zero misses or extras in the fixed set, one named Phoenix victim, six identity refusals, and zero verified locations. [Review and before/after comparison](teststore/death-round4-v3/review-summary.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Ability entity detection:** Reactivate after diverse acquisition is scored and a player-reviewed label set includes ordinary match footage. [History](docs/archive/BACKLOG-through-2026-09-23.md#reticle-has-no-ability-detector-and-the-five-prototypes-are-triaged).
- **Domain fact subject:** Reactivate when a concrete inference requires a machine-readable subject or condition. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-fact-registry-has-no-subject-so-it-is-a-list-rather-than-a-graph).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
