# Backlog entries retired on 2026-09-27

Completed entries as `BACKLOG.md` held them before the pub/sub branch filed its open work. `plan-derived-chain` left the list to keep its five latest; the other four stay there as one line each, and their full text is here.

- **`demo-cast-census` (2026-09-26):** crop caches for 33 demos; of 147 drops, 19 are the menu and 55 of 128 casts draw nothing; 15 observed facts; a labelling tool.
- **`audio-ability-bank` (2026-09-26):** demo references name 39 of 120 labelled match casts, 64 by correlation after re-recording; not wired.
- **`ability-shape-wiring` (2026-09-26):** `reticle tray` and `reticle ability-shapes` store the player's casts and drawn shapes from the crop cache; on the player's marks Fury 21/21, Regrowth 14/16, Recon Bolt 8/8.
- **`revive-plate-witness` (2026-09-26):** a one-colour banner with an unnamed icon, a fielded reviver and two names is a revive (`death-adjudication-0.14.0`).
- **`plan-derived-chain` (2026-09-25):** `plan` stales the round table on a moved HUD or portrait input and the deaths behind it; each round table records its portrait stamp. Rebuilding all 20 changed no round.

## Superseded backlog text (2026-09-28, master merge)

Spans cut verbatim from open items when the ability-identification branch merged into master; the numbers and facts in them stay in `NOTES.md`, a results document, or here.

- Scoreboard presence (player, 2026-09-27): the slab test alone closed the board inside 626 of 3111 Tab holds ([metric:scoreboard/openings@all-sessions-slab-only#holes=841] samples); with the strip witness ([results](docs/SCOREBOARD_PRESENCE.md)) the board is seen on [metric:scoreboard/openings@all-sessions#samples_open=25620] samples, but only slab-read samples name rows ([metric:scoreboard/openings@all-sessions#openings_accepted=6018] accepted openings). `scoreboard-0.9.0` places the enemy rows from the strip's lines and confirms them by red or by the portraits ([metric:scoreboard/line-confirm@a06f04a0059f#closed_present_after_open=95] of 100 closed boards open, [metric:scoreboard/line-confirm@a06f04a0059f#open_present_after_open=97] of 100 open stay open; held out on `bfad2778a372`, [metric:scoreboard/holdout@bfad2778a372#closed_present_090_open=28] of 50 closed open). Next:
- Killfeed attribution first (player, 2026-09-24): uniform killer coverage is 0.856 (`death-adjudication-0.12.0`).
- Ability identification on the demos (next, 2026-09-26), item (6): are ported (`reticle ult-lines`, `reticle ult-cast`); the Iso game-only match (`4f207c0c4e39`) selects [metric:ult_lines/ult-cast@4f207c0c4e39#selected=6] peaks, [metric:ult_lines/ult-cast@4f207c0c4e39#class_impossible=3] impossible [domain:capture/game-audio-track-only]; its minimap is larger than baked and side-based and its killfeed prints no `Me`; the player reverts the settings;
- Ability identification on the demos (next, 2026-09-26), item (6): the gate is `player-cast-0.6.0`; the [ability state model](docs/ABILITY_STATE_MODEL.md) step 1 is built; the player gave every charge count [domain:abilities/recharge-kinds]; the wiki harvest is the prior below the facts (`ability-state-0.3.0`; Astra Q and E, Reyna Q and E, Brimstone E and Chamber Q have none); the tray's icons are a kit witness (`tray-kit-0.1.0`);
- Pub/sub branch `pubsub-20260927`, item (7), which this merge settles: (7) Merging the two `NOTES.md` needs a decision.
- Pub/sub branch lead: `(2026-09-27, unmerged)` became `(2026-09-27)`, since `pubsub-20260927` is an ancestor of master.

## Completed entries shortened at the master merge (2026-09-28)

`BACKLOG.md` keeps each as one line; the full text is here.

- **`ability-state-step1` (2026-09-27):** `reticle ability-state` stores the player's kit as a state per slot from storage (`ability-state-0.1.0`); every testable invariant is zero on 20 sessions.
- **`scoreboard-presence` (2026-09-27):** the round-history strip is a second presence witness (`reticle strip`, `reticle openings`); the slab test stores its close reason (`scoreboard-0.7.0`).
- **`ult-voice-lines` (2026-09-27):** whitened correlation against the 56 official ultimate lines is ported as `reticle ult-lines` and `ult-cast`, its threshold held out and own lines bound to the tray.
