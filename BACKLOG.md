# Reticle task queue

`docs/tasks.json` defines executable checks. This file orders work and records why a task is active. Historical arguments and completed items are in [the dated backlog archive](docs/archive/BACKLOG-through-2026-09-23.md).

## Agreed order (2026-09-23)

Steps 1 to 5 are done; steps 3 to 5 are recorded under Completed. Step 1 measured scoreboard availability from stored rows: 33 of 52 sessions have no scoreboard rows, and in the 17 with rows and rounds, 326 of 348 rounds have at least two separate Tab holds. Usable openings around each death remain unmeasured outside `a06f04a0059f`.

6. **Minimap identity, ally slice first.** First slice built and measured ([results](docs/ALLY_MINIMAP_IDENTITY.md)): `scan --only ally_icon` stores a descriptor per ally icon at 2 Hz (`ally-icon-0.1.0`), refusing spawn barriers by their interior's match to the baked map, and `identity.claims_from_ally_icons` names each frame's icons with `assign_side` over the board's ally set minus the player. On `a06f04a0059f` it names 63% of described icons; the source check found 2 wrong of 40, one over the predicted limit, both on overlapping icons. `reticle lifetimes` now runs `round_lifetimes` over stored 15 Hz ally icons ([results](docs/ROUND_ENTITIES.md)); its open list (lobe-centred fits, missed icons, merged state, start/end events, names per segment) is the order the player agreed on 2026-09-23 and comes before (a)-(c). Then: (a) ask the player to label a sample of overlapping and non-overlapping icons (`labelling-pass` skill), then measure an overlap refusal against it; (b) session exemplars from named ally deaths, with `depends_on`; (c) a track key so claims accumulate per teammate. Enemy icons are a later, separate promotion from `prototypes/minimap_portrait.py`, whose 93% leave-one-out was partly scored against provisional labels; read `prototypes/CLAUDE.md` first.

The player answered the dimming question: dimmed means currently dead, a Sage revive lights the row again, and Run It Back is not expected to dim [domain:rounds/scoreboard-dim-is-dead]. Clove before Not Dead Yet and a downed KAY/O remain unknown; capture one of each and ask when it occurs.

**Store the team's adjudicated vision, then feed it to ability refusal (next, 2026-09-23).** The chain the player built -- `cone.resolve_lobe` per frame, `track` resolved facing, `minimap_lifecycle` eligibility, `cone.observable` union (`adjudicated_agg`) -- runs only inside `overlay` and stores nothing, so no adjudicator can consume it. Make it a stored product with its own owner entry and stamp, reached by `scan` or a stored-data command, and delete its items from `uncalled_debt.toml`. Then `adjudication.ability.light_refusals` consumes it for the three cone slivers `lit_mask` misses, without restating any stage; score against the grouping labels (16 of 19 viewcones refused today, 0 of 31 abilities). Decide the order of adjudicators explicitly: a smoke blocks the drawn light while the light refuses ability candidates, so that loop needs breaking by time (the previous frame's accepted entities) or a bounded fixed point over stored data.

**Roster defect:** `roster.resolve` reads 1 on a wiped side ([details](docs/BOARD_ALIVE_SETS.md#results)).

**Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes the file's raw bytes, so a CRLF checkout (any fresh worktree here, `core.autocrlf=true`) reports all 12 geometry npz stale. Normalising the bytes edits the stamped file, which itself forces a rebuild; schedule it with the next geometry rebuild.

**Killer crop with assist icons:** at 284500 in `a06f04a0059f` icons left of the killer portrait likely corrupt its descriptor ([details](docs/IDENTITY_EXEMPLAR_LOOP.md#open)); `killfeed` owns the crop.

**Remaining identity drift to retire:** `Lineup.player` still combines the tray, self icon and top bar itself before publishing claims (the `player-agent` exit).

## Completed

- **`identity-exemplar-loop` (2026-09-23):** killfeed portraits also score against this session's portraits labelled by the scoreboard or the player HUD, only where the official art refuses, with `depends_on` on the labelling death. Across 24 rounds of `a06f04a0059f` it adds 32 names (12 of 12 source-checked correct), zero disagreements. [Results](docs/IDENTITY_EXEMPLAR_LOOP.md).
- **`death-killers` (2026-09-23):** the killer is now entity `<death_id>:killer`, named by `adjudication.identity` from the player HUD and the stored killer portraits over the board-constrained side. Round 4 names 5 of 7 killers, all matching source; two refuse on a thin margin and a single view. [Results](docs/DEATH_KILLERS.md).
- **`board-alive-sets` (2026-09-23):** `reconciliation.audit_board_alive` compares each accepted opening's lit rows with the roster count at the same sample: 11926 of 11958 side-openings agree across 19 sessions. 22 of the 32 disagreements are the board relighting after the top bar at a round start [domain:rounds/scoreboard-relights-after-top-bar] and 6 are the roster reading 1 on a wiped side. The death witness skips contradicted openings; round 4 still names seven. [Results](docs/BOARD_ALIVE_SETS.md).
- **`ability-detection` (2026-09-23):** Promoted scale-selective local contrast disc detection (`detect_ability_discs`) into `reticle/minimap.py`, claiming `[owns:ability-detection]`. POV benchmark corroborates HUD tray charge drops against minimap disc appearances, achieving 9/9 true positives (100% recall) and 0 false positives across five solo ability demo sessions. Added unit tests in `tests/test_minimap_discs.py`.
- **`scoreboard-corpus` (2026-09-23):** rescanned the other 17 scoreboard sessions at `scoreboard-0.5.0`. All 17 name both sides from one agreeing set per side; the constrained lineup names 170 of 170 slots against 113 for the top bar. The board changed six top-bar names and a source crop shows all six are corrections. [Results](docs/SCOREBOARD_LINEUP.md#corpus-at-scoreboard-050).

## Deferred

- **Killfeed HUD work:** Revisit the double analysis per frame when a profile shows that cost or an entry-key failure in `death-portraits`. [History](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame).
- **Remaining minimap, audio, geometry, and coaching work:** Select a bounded task after the active task closes or identifies an upstream blocker. [Historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md) retain the detail.
