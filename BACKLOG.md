# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Agreed order (2026-09-23)

Steps 1 to 5 are done; steps 3 to 5 are recorded under Completed. Step 1 measured scoreboard availability from stored rows: 33 of 52 sessions have no scoreboard rows, and in the 17 with rows and rounds, 326 of 348 rounds have at least two separate Tab holds. Usable openings around each death remain unmeasured outside `a06f04a0059f`.

6. **Minimap identity:** name minimap icons over the five candidates per side; the stored minimap for `a06f04a0059f` is stale (`minimap-0.4.0`).

The player answered the dimming question: dimmed means currently dead, a Sage revive lights the row again, and Run It Back is not expected to dim [domain:rounds/scoreboard-dim-is-dead]. Clove before Not Dead Yet and a downed KAY/O remain unknown; capture one of each and ask when it occurs.

**Roster defect:** `roster.resolve` reads 1 on a wiped side ([details](docs/BOARD_ALIVE_SETS.md#results)).

**Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes the file's raw bytes, so a CRLF checkout (any fresh worktree here, `core.autocrlf=true`) reports all 12 geometry npz stale. Normalising the bytes edits the stamped file, which itself forces a rebuild; schedule it with the next geometry rebuild.

**Remaining identity drift to retire:** `Lineup.player` still combines the tray, self icon and top bar itself before publishing claims (the `player-agent` exit).

## Completed

- **`death-killers` (2026-09-23):** the killer is now entity `<death_id>:killer`, named by `adjudication.identity` from the player HUD and the stored killer portraits over the board-constrained side. Round 4 names 5 of 7 killers, all matching source; two refuse on a thin margin and a single view. [Results](docs/DEATH_KILLERS.md).
- **`board-alive-sets` (2026-09-23):** `reconciliation.audit_board_alive` compares each accepted opening's lit rows with the roster count at the same sample: 11926 of 11958 side-openings agree across 19 sessions. 22 of the 32 disagreements are the board relighting after the top bar at a round start [domain:rounds/scoreboard-relights-after-top-bar] and 6 are the roster reading 1 on a wiped side. The death witness skips contradicted openings; round 4 still names seven. [Results](docs/BOARD_ALIVE_SETS.md).
- **`ability-detection` (2026-09-23):** Promoted scale-selective local contrast disc detection (`detect_ability_discs`) into `reticle/minimap.py`, claiming `[owns:ability-detection]`. POV benchmark corroborates HUD tray charge drops against minimap disc appearances, achieving 9/9 true positives (100% recall) and 0 false positives across five solo ability demo sessions. Added unit tests in `tests/test_minimap_discs.py`.
- **`scoreboard-corpus` (2026-09-23):** rescanned the other 17 scoreboard sessions at `scoreboard-0.5.0`. All 17 name both sides from one agreeing set per side; the constrained lineup names 170 of 170 slots against 113 for the top bar. The board changed six top-bar names and a source crop shows all six are corrections. [Results](docs/SCOREBOARD_LINEUP.md#corpus-at-scoreboard-050).
- **`scoreboard-lineup` (2026-09-23):** `scoreboard-0.3.0` stores every agent's score per row; `identity.board_side_sets` names each side from agreeing openings and `identity.lineup_with_board` restricts the top-bar assignment to that set. Both tested sessions name all ten slots, matching source; the top bar's accepted Clove in `a06f04a0059f` was Jett's slot. Round 4 names all seven deaths correctly; Jett by scoreboard elimination with zero independent channels recorded. [Results](docs/SCOREBOARD_LINEUP.md); [contract](docs/tasks.json).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
