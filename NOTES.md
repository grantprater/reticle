# Reticle working handoff

## Picking up

**2026-10-04.** The [backlog](BACKLOG.md) holds three active items: close the remaining failures against Riot's match records, put the extracted game files into every reader that matches game art or sound, and fit stacked ally icons. The previous handoff is [archived](docs/archive/NOTES-2026-10-03-to-10-04.md).

### What the Riot scorer says

`prototypes/riot_ground_truth.py --all --offline --record` (`riot-truth-0.3.3`) rescored the 21 matches on 2026-10-04, after the corpus rerun:

- **Deaths:** recall [metric:riot_truth/deaths#recall=0.9955], precision [metric:riot_truth/deaths#precision=0.9979]; of named fields, victim [metric:riot_truth/deaths#victim_right_of_named=0.9988], killer [metric:riot_truth/deaths#killer_right_of_named=0.9994], weapon [metric:riot_truth/deaths#weapon_right_of_named=0.9997]. Pooled, the store misses [metric:riot_truth/deaths#missed=3] kills, cannot observe [metric:riot_truth/deaths#unobservable=12] inside a stall, and holds [metric:riot_truth/deaths#false_deaths=7] false deaths. The stall deaths `infer_stall_deaths` adds score apart: 8 rows, 6 paired, all 6 with the victim right, none false (the scorer prints these but records no token).
- **Rounds:** winner right on [metric:riot_truth/rounds#winner_right=439] of [metric:riot_truth/rounds#riot_rounds=439]; plants on both sides [metric:riot_truth/rounds#plant_both=251], Riot only [metric:riot_truth/rounds#plant_riot_only=27].
- **K/D:** known players agree on [metric:riot_truth/kd#known_agree=18] of [metric:riot_truth/kd#known_scored=18]; tracked exact on [metric:riot_truth/kd#tracked_exact=15] of [metric:riot_truth/kd#tracked_scored=21].
- **Minimap allies at kill instants:** [metric:riot_truth/minimap/all#matched=8366] matched, [metric:riot_truth/minimap/all#phantom=362] phantoms, [metric:riot_truth/minimap/all#missed_stacked=1002] misses in stacks, the reader alone [metric:riot_truth/minimap/all#reader_matched=7647]. The previous handoff's 7272 / 1453 / 792 came from `riot-truth-0.1.0`; the scorer changed since, so the old and new minimap figures do not compare.

### Corpus rerun, 2026-10-03

On the 21 matches, from the crop cache and storage, no decode, 137.5 min: `round-outcome` on each match, `scan --only hud --from cache`, then the steps `plan` named: vision, rounds, deaths (`death-adjudication-0.31.0` -> `0.34.0`), lifetimes, combat-report, tray, ult-cast, ability-shapes, ability-state (`0.3.0` -> `0.5.0`), `scan --only ability`, enemy-tracks and project. `plan` now names nothing on a match. The demos stay stale (vision, tray, ult-cast); the matches-only rule skips them.

### Merged this session

Each commit body carries its measurements (`git log --no-merges ec20d71..f6e494c`).

- **Game files.** A headless CUE4Parse extractor in the store's `tools/game-extract` exports build `release-13.06-shipping-18-5590001` to the store's `reference/game-files/`; ability audio sits in `reference/game-files/audio` (`ability-audio-ref-0.2.0`, 4,083 FLACs). About 660 of them peak at 0 dBFS and clip slightly (at most 1.4%). Unmapped audio folders: Tejo `Cashew/Abil_X`, Deadlock `Abil_E`, Neon `Slide`, Cypher `Abil_Q`, Jett `Grenade`; Miks has no Grenade data.
- **Killstreak.** `killfeed-numeral-0.1.0` reads the numeral in the game font (DIN Next Heavy); `killstreak-witness-0.1.0` runs through `reticle killstreak`. `plan` does not yet declare the `killstreak_witness` stream.
- **Round outcome.** `round-outcome-0.1.0` and its claim reader: 417 rounds right, 0 wrong, 22 refused. `death-adjudication-0.34.0` adds `infer_stall_deaths`. `plan` and `status` list `round_outcome`; its column fit sits in `NOT_INPUTS`.
- **One-colour band.** `hud-0.19.0` reads spike, self, team and Not Dead Yet kills and Paint Shells; it found 11 of the 12 targeted Riot misses.
- **Game kill icons.** The weapon gallery holds the game's kill icons (`weapon-gallery-0.7.0`, adjudication `1.3.0`); the killfeed pitch is the game's 39 px (`hud-0.20.0`); the killfeed layout became domain facts.
- **Whitened audio.** `ability-audio-0.1.0` and `ability-audio-params-0.1.1` (Sova, Skye, Iso); kit-owner gate `player-cast-0.8.0`; ability-state `0.5.0`. Identity does not pool the audio claim.

### Unmerged branches

- **`stack-spike-merge-20261004`**, merge next: merges `stack-fit-wire-20261003` (`stack-fit-0.3.0`, the stacked-icon fitter where ring fits fall short of roster capacity; an analytic teardrop, not game art; +28 to 64 ms per frame) and `game-spike-20261003` (`spike-0.3.0`, the minimap spike glyph drawn from `Minimap_BombIcon`; the roster marker keeps its mined template). `ally-icon-0.11.0` covers both. Rerun from the crop cache on 3694746e4e54, a06f04a0059f and bdfdcf009dba (streams now stored at 0.11.0 / spike-0.3.0), Riot minimap allies: matched 1173 -> 1233, phantoms 33 -> 52, missed in stacks 126 -> 102, identity refused 66 -> 109; spike_carrier disagreements 113 -> 100. The corpus still needs the ally_icon and spike rerun.
- **`whitened-weapon-20261003`** (`9e64eeb`), held: no gain over the overlap (IoU) gate (Riot 531/0/15 both ways, held-out 949/949). It names Paint Shells on 4f207c0c4e39 at 1759 s, which the overlap gate refuses as `new`. It pays off only with a whitened open-set null fitted leave-one-icon-out on dev.
- **`game-vo-20261003`** (`a527233`), unmerged: the game's en-US ability-cast voice lines are in the store at `reference/game-files/vo` (`vo-ref-0.1.0`, 447 FLACs, 29 agents); `ult_lines` reads them (`ult-line-0.2.0`); 57 of 58 templates are the wiki recordings; on stored features Riot ult recall rises 0.548 to 0.574 with own recall unchanged. The production `ult_line` stream needs an audio-only decode rerun (`reticle ult-lines --all`, then `ult-cast`), which needs the player's go-ahead.
- **`ability-audio-fit-20261004`**, merge next: `reticle ability-audio-fit` fits `ability-audio-params-0.2.1` (in the store): declared split, pooled whitener, neighbour-cut windows (`ability-audio-0.2.0`), shared Sova files out, the player's Skye remap and Owl Drone correction in. Held top-1: Sova 87/94, Skye 93/97, Phoenix 30/34, Clove 22/22, Iso 12/13; demos 31/35. Dev refuted the player's Sova remap (86 to 68 of 98); ask again. `ability-state` is stale.
- **`binding-rules-20261002`** (`round-entity-0.15.0`): cuts a piece where a sighting gap spans its teammate's death, but demotes correct bindings. Rework after the stacked icons through `death_rank`; the revive at 96aa1ae9b96f 849.5 s names no victim.
- **`ally-ring-subpixel-20261001`** (shelved, a negative result) and **`stacked-icons-20261002`** (superseded by `stack-fit-wire`).
- **`luma-render-20261002`** (WIP, tabled); **`killfeed-prior-design-20261002`** and **`killfeed-prior-step1-20261002`** (the queue-follow plan and its unwired step 1).
- `self-spike-tracker-20260929` (the player-dead owner and guard 6 can merge with bumped versions); `wip-vision-lifecycle-wiring` (WIP, do not merge); `enemy-fix-check-20260930`. Delete `decodes-20260929` when convenient.

### Side findings

- **LAYER:** `lineup._composition` inserts `prototypes/` into `sys.path` (`reticle/lineup.py` line 99), which AGENTS forbids; find out why doctor's LAYER check misses it.
- **Open player questions** from the visual demo probe, for the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md): minimap icon rotation; the Killjoy turret before its E drop, and a mislabelled crop; Cypher's teal discs; restock time (game data says 50 s against the catalogue's 60 s on 7 of 11 abilities) and Neon's costs; the Blade Storm kunai, absent from the export.

Riot's match records sit in the store under `external/riot/` ([EXTERNAL_GROUND_TRUTH.md](docs/EXTERNAL_GROUND_TRUTH.md)).

Capture paths: 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
