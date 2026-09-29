# Backlog retired 2026-09-28 (evening)

The queue `BACKLOG.md` held before the 2026-09-29 rewrite, verbatim as committed at `2410764`. The rewrite proposed three new active items (player inputs, decodes waiting on the player, identity follow-ups), moved the former active items and the still-open waiting items to Waiting, closed what the 2026-09-28 merges finished, kept the five latest completed tasks, and retired the stale Deferred section.

## The queue as of 2410764


This file orders work and says why a task is active; each open item carries an `Acceptance:` command and an `Evidence:` standard. Historical arguments and completed items are in the dated backlog archives; the queue as it stood before 2026-09-28, with every item's full text, is [here](docs/archive/BACKLOG-through-2026-09-28.md).

## Agreed order (2026-09-28)

Steps 1 to 5 are done ([archive](docs/archive/BACKLOG-through-2026-09-26.md)). Three items are active; the rest wait below in their former order.

**Killfeed attribution first (player, 2026-09-24).** In order: (0) the victim edge: the reader reads Jett's white hair as name text and cuts the victim box past her portrait (`a06f04a0059f` 284.5 s), so her victim vote rests on a minority of views; (1) exemplar source mismatch: in-session exemplars outscore official art, so on `7010b3d62460` Chamber reads Brimstone; compare exemplar scores only with exemplar scores; (2) `agent-alive`, a new owner: which agents live per side and round, a statistical model over killfeed deaths, revives, the roster count and survivor portraits; (3) the branching banner reader, then trades and baiting ([design](docs/BEHAVIOUR_MODEL_DESIGN.md)); (4) assist panels [domain:killfeed/assist-panel] [domain:killfeed/assist-panel-layout]: the player re-answers 8 (`prototypes/label_assists.py label --redo`), then a panel reader; (5) `scoreboard_dim` named two Brimstone victims Chamber (`7010b3d62460` 605.0 s, 820.5 s); (7) a plate revive names no reviver, and the name reader misses victim text on one-colour banners.
Acceptance: `.\.venv\Scripts\python.exe prototypes\round_identity_eval.py a06f04a0059f --round 4 --verbose` names Jett the 284.5 s victim on a majority of her views, and `.\.venv\Scripts\python.exe -m unittest tests.test_round_identity_e2e` passes.
Evidence: crops of every view of the 284.5 s entry show the victim box ending at Jett's portrait before any threshold changes; later steps each name their labelled sample first.

**Roster follow-ups (2026-09-28).** `roster-split-0.3.1` reads a wiped bar over scenery as 0 ([results](docs/BOARD_ALIVE_SETS.md)). Open: (1) scenery behind the first empty slot counts as a portrait: `4f207c0c4e39` 2170.5 s reads 4 of 3; (2) a bar with a crisp slot but no winning split reads 0 under a drawn HUD and should refuse; (3) [metric:roster_split/bar-floor#wiped_bar_max_ge_13=13] of [metric:roster_split/bar-floor#wiped_sides=2197] board-wiped sides have scenery at 13 or more. Round entities and deaths read the stored ungated columns: rerun them from storage after the fix.
Acceptance: `.\.venv\Scripts\python.exe -m unittest tests.test_reconciliation` passes with cases for (1) and (2), and `.\.venv\Scripts\python.exe -m reticle status` keeps [metric:roster_split/bar-floor-known-kd#exact=13] of 17 exact against `KNOWN_KD`.
Evidence: crops of each changed side, `4f207c0c4e39` 2170.5 s first, checked against the scoreboard's openings before the stamp moves; no board agreement lost, recorded through `reticle.metrics`.

**Ability identification on the demos (2026-09-26).** (0) The player labels five unlabelled Sova C refusals (`043bafca271a` 1499.05 s; `3694746e4e54` 775.05 s and 1082.0 s; `59c70f1ef720` 2543.5 s; `c40d950031bb` 267.57 s) and confirms no Shock Bolt at `75a55a296d3b` 274.1 s, where the bridged-drop refusal is correct; (1) the census answers ([answers](docs/DEMO_CAST_CENSUS.md#the-players-answers-2026-09-26-later)) and the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md) become domain facts [domain:abilities/ability-rules-are-unique]; (2) read the HUD the pipeline ignores: the ability timer bar [domain:hud/ability-timer-bar], cooldown counters, Viper's fuel meter [domain:abilities/viper-fuel-toggle], the location label, the chat box [domain:hud/chat-broadcasts-callouts]; (3) guard the minimap readers and `reticle tray` against the menu [domain:hud/menu-dims-tray] and the Trailblazer view [domain:hud/controlled-entity-view-tint] by the tray's Q drop and the self portrait; fit the ring [domain:minimap/widget-ring]; (5) rebuild the bank ([re-recorded](docs/AUDIO_ABILITY_BANK.md#re-recorded-references-2026-09-26)); (6) the ult-ready scorer ([doc](docs/ULT_READY_LINES.md)), a lineup stamp for `plan`, a pip reader for X, labels for refused drops, a guard for a flash beside one emptied slot (`223d636bf8d2` 750.0 s), then cast lines [domain:abilities/cast-lines-vary] and the [audio gate](docs/AUDIO_GATE.md); (7) which Fury lines are blasts. `reticle plan` names storage reruns of `tray`, `ability-shapes`, `ult-cast`, `ability-state` and `openings`.
Acceptance: `.\.venv\Scripts\python.exe -m reticle ability-state --all --record` records the labelled casts after the player's answers, and `reticle plan` names no ability stream.
Evidence: the player's labels for the five refusals stand in the label file before any gate changes; every new fact cites the player or a source.

## Waiting

In former order; each item's full text and argument is in [the 09-28 archive](docs/archive/BACKLOG-through-2026-09-28.md).

- **Minimap identity, ally slice first** ([results](docs/ALLY_MINIMAP_IDENTITY.md), [lifetimes](docs/ROUND_ENTITIES.md)): (a) the player labels overlapping icons (`labelling-pass` skill), then an overlap refusal; (b) session exemplars from named ally deaths, with `depends_on`; (c) a track key per teammate. Enemy icons later, from `prototypes/minimap_portrait.py`.
- **The adjudicator as a statistical model (player, 2026-09-23):** carry each measurement with its uncertainty and make the rules likelihoods; ideate first, then a falsifiable experiment on the grouping labels and the three slivers. Geometry refinements pool across sessions under a new stamp and are scored on held-out slivers.
- **Tiered verification (player, 2026-09-23):** a few sessions with known answers, run in minutes; start with `e78e75b2d191` and a slice of `a06f04a0059f`.
- **Store the team's adjudicated vision:** the `overlay` chain becomes a stored product with an owner and stamp, then feeds `adjudication.ability.light_refusals`.
- **Smoke attribution:** the player's rules [domain:abilities/smoke-attribution] as identity claims through `adjudication.identity`; measure the disc lifetime per smoke agent first [domain:abilities/miks-smoke-minimap-disc].
- **Scoreboard presence** ([results](docs/SCOREBOARD_PRESENCE.md)): the table's edges, the openings gate counting a confirmed board once, prototype callers passing icons, then the rescan (the player's call).
- **Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes raw bytes.
- **Combat report follow-ups:** the verdict equals `KNOWN_KD` on every known session ([metric:combat_report/acceptance@b3b9defb6fd7#deaths_verdict=18]). Read the row identity disagreements first; then the killfeed errors the report exposed, weapon identity, ally rows, the second-life gate in `reticle lifetimes`, and the `7010b3d62460` death panels.
- **Identity drift:** `Lineup.player` still combines the tray, self icon and top bar before publishing claims.
- **Pub/sub** ([measurements](docs/PUBSUB_MEASUREMENTS.md)): a process shard of ally_icon; a warmed-up `--check`; repeat m6 without load. A failed commit leaves partly moved files. Unbuilt: L1's selecting producer, L2, L5, L7.
- **E1: can agreement conceal a wrong event history?** ([program](docs/EXPERIMENT_PROGRAM.md), ledger `e1-agreement-2026-09-27`). Acceptance: `.\.venv\Scripts\python.exe prototypes\e1_agreement.py --replay` writes both lists from storage and records `e1_agreement/replay`. Evidence: the player reviews the seeded agreeing rounds against source first.

## Completed

- **`roster-wiped-bar` (2026-09-28):** `roster-split-0.3.1`; a wiped bar over scenery reads 0, not 1.
- **`e2e-identity-fixture` (2026-09-28):** the round 4 fixture lives in the store; the ally oracle names Breach and Miks.
- **`tray-whole-capture` (2026-09-28):** a whole-capture cache reads as one span, refused as `no_rounds`.
- **`pubsub-fixes` (2026-09-28):** truncated events read as incomplete; a scan publishes whole under a run id.
- **`ability-state-step1` (2026-09-27):** the player's kit as a state per slot.

Full entries: [09-28 archive](docs/archive/BACKLOG-through-2026-09-28.md), [09-27 archive](docs/archive/BACKLOG-through-2026-09-27.md).

## Deferred

- **Killfeed HUD work:** the double analysis per frame ([history](docs/archive/BACKLOG-through-2026-09-23.md#the-hud-pass-analyses-the-killfeed-twice-per-frame)).
- **Remaining minimap, audio, geometry and coaching work:** [historical queue](docs/archive/BACKLOG-through-2026-09-23.md) and [pipeline gates](docs/PIPELINE_REVIEW.md).
