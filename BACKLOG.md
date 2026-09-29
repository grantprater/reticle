# Reticle task queue

This file orders work and says why a task is active; each open item carries an `Acceptance:` command and an `Evidence:` standard. Historical arguments and completed items are in the dated backlog archives; the queue as it stood at the end of 2026-09-28, with every item's full text, is [here](docs/archive/BACKLOG-through-2026-09-28b.md).

## Agreed order (2026-09-29)

The 2026-09-28 queue is merged. The three items below are proposals: each waits on the player, who evaluates next steps after this queue.

**Player inputs waiting (2026-09-28).** (1) Label the ally and enemy facings: `.\.venv\Scripts\python.exe prototypes\label_icon_facing.py` asks, blind, for the centre and tip of about 60 icons ([E6](docs/STATISTICAL_ADJUDICATOR.md#e6-ally-and-enemy-teardrops)); predictions C1-C4 and L1-L2 are logged. (2) Answer the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md)'s `harvest: ...?` cells, the catalogue's restock and ult-cost values he has not confirmed. (3) Name the two unknown minimap glyphs: `5822b6646448` (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) 409 s and `223d636bf8d2` (`C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`) 630 s. (4) Say whether a Seeker despawns when its target dies [domain:abilities/skye-seekers-track-and-blind].
Acceptance: `.\.venv\Scripts\python.exe prototypes\icon_facing_eval.py` scores the teardrop against `labels/icon_facing_20260928.jsonl` for both classes, and `.\.venv\Scripts\python.exe -m reticle doctor` passes DOMAIN with each answer recorded as a fact.
Evidence: the player's answers stand in the label file and in `domain/*.toml`, citing him, before any reader or gate changes; a failed prediction is recorded, not refitted.

**Decodes waiting on the player (2026-09-28).** Each decodes video, so each waits for his go-ahead. (1) The `scoreboard-0.10.0` rescan, a decode of about two hours; `deaths`, `openings`, `ult-cast` and `ability-state` rerun from storage after it ([results](docs/SCOREBOARD_PRESENCE.md)). (2) The ally_icon rescan. It renumbers the `unnamed_piece` label keys, so migrate the labels (`prototypes/label_unnamed_pieces.py`) first. (3) `team_vision` for the sessions beyond `e78e75b2d191` and `a06f04a0059f`, a run of minutes per session.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan` names no stream stale on the scoreboard or ally_icon input, and `.\.venv\Scripts\python.exe -m reticle verify --tier fast` passes.
Evidence: the player approves each decode; every migrated label key points at the same piece before and after, checked on crops; the death summary before and after the rescan is recorded through `reticle.metrics`.

**Identity follow-ups (2026-09-28).** (1) [metric:e1_agreement/landing@store-20#contested_after=18] contested deaths need an outside witness, the player HUD or a minimap track (`death-adjudication-0.17.0`). (2) Three `223d636bf8d2` names stay wrong: two name crops miss their clusters, and one killer reads no name at any view ([E1](docs/E1_AGREEMENT.md#open)). (3) The Shooting Error box hides an entry until the stack rises; the combat report panel's open time is the other witness. (4) On the Iso capture `4f207c0c4e39` (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`) the spike reader names a carrier on nearly every round, which looks wrong, and the self icon does not score Iso. (5) `--from auto` and buy-phase rows for span readers: the player's call. (6) The `fixtures/scoreboard_edges` fixture fills most of each frame; the player decides whether to crop it to the table (x 572-1347) or delete it.
Acceptance: `.\.venv\Scripts\python.exe -m reticle deaths` over the 20 death sessions stores fewer contested deaths, each confirmed through the arbiter, and `.\.venv\Scripts\python.exe -m reticle verify --tier fast` passes.
Evidence: crops of the outside witness for each confirmed death, and of each renamed `223d636bf8d2` entry, before any rule changes; the carrier rows checked against the roster marker by eye.

## Waiting

In former order; each item's full text is in the [09-28 evening archive](docs/archive/BACKLOG-through-2026-09-28b.md).

- **Killfeed attribution** (player, 2026-09-24; the victim edge is done): (1) exemplar source mismatch, `7010b3d62460` Chamber read as Brimstone; (2) `agent-alive`, a statistical owner of the living agents per side and round; (3) the branching banner reader, then trades and baiting ([design](docs/BEHAVIOUR_MODEL_DESIGN.md)); (4) assist panels [domain:killfeed/assist-panel]: the player re-answers 8, then a panel reader; (5) `scoreboard_dim` names two Brimstone victims Chamber; (7) a plate revive names no reviver.
- **Ability identification on the demos** (2026-09-26): the five unlabelled Sova C refusals and the Shock Bolt check at `75a55a296d3b` 274.1 s; census answers as facts; the HUD the pipeline ignores (ability timer bar, cooldown counters, Viper's fuel, location label, chat); the Trailblazer view guard; the bank rebuild; the ult-ready scorer, a lineup stamp for `plan`, a pip reader for X; which Fury lines are blasts.
- **Minimap identity, ally slice first** ([results](docs/ALLY_MINIMAP_IDENTITY.md)): overlap labels and refusal; session exemplars from named ally deaths, with `depends_on`; a track key per teammate. Enemy icons later.
- **The statistical adjudicator** ([plan](docs/STATISTICAL_ADJUDICATOR.md)): E1-E6 ran; open are the half-angle's wide interval, teammates' cones still cast from their ring fits, wall edges never perturbed, and one session per map.
- **Geometry stamp reads line endings:** `minimap_geometry.source_stamp` hashes raw bytes.
- **Combat report follow-ups:** the row identity disagreements; weapon identity, ally rows, the second-life gate in `reticle lifetimes`, the `7010b3d62460` death panels; `cli._combat_report_identity` tracks entries without `sides`.
- **Pub/sub** ([measurements](docs/PUBSUB_MEASUREMENTS.md)): a process shard of ally_icon; a warmed-up `--check`; repeat m6 without load. A failed commit leaves partly moved files. Unbuilt: L1's selecting producer, L2, L5, L7.

## Completed

Also closed on 2026-09-28: roster follow-ups (`roster-0.3.0`, `roster-split-0.4.0`), smoke attribution (`smoke-owner-0.1.0`, `smoke-0.4.0`), the menu guard (`menu-0.1.0`) and the stored team vision.

- **`fast-tier` (2026-09-28):** `reticle verify --tier fast`, seven checks with no decode, the self facing scored against the player's labels.
- **`e1-agreement` (2026-09-28):** E1 landed (`death-adjudication-0.19.0`, `hud-0.16.0`) and the player reviewed its list.
- **`team-vision-facing` (2026-09-28):** `team-vision-0.3.0` casts the self cone from the teardrop's centre along its facing.
- **`scoreboard-edges` (2026-09-28):** `scoreboard-0.10.0` fits the table's frame; the rescan waits.
- **`player-agent` (2026-09-28):** the arbiter names the player's agent from tray and self-icon claims.

Full entries: [09-28 evening archive](docs/archive/BACKLOG-through-2026-09-28b.md), [09-28 archive](docs/archive/BACKLOG-through-2026-09-28.md).
