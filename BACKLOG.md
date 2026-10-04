# Reticle task queue

This file orders work; each open item carries an `Acceptance:` command and an `Evidence:` standard. Full texts of earlier items and completed work are in the [10-04](docs/archive/BACKLOG-through-2026-10-04.md), [10-03](docs/archive/BACKLOG-through-2026-10-03.md), [10-02](docs/archive/BACKLOG-through-2026-10-02.md) and [10-01](docs/archive/BACKLOG-through-2026-10-01.md) archives.

## Agreed order (2026-10-04)

**1. Close the remaining failures against Riot's match records.** Pooled over 21 matches the store misses [metric:riot_truth/deaths#missed=3] kills, cannot observe [metric:riot_truth/deaths#unobservable=12] inside a stall and holds [metric:riot_truth/deaths#false_deaths=7] false deaths; [metric:riot_truth/deaths#victim_refused=25] victims, [metric:riot_truth/deaths#killer_refused=28] killers and [metric:riot_truth/deaths#weapon_refused=65] weapons stay refused. Riot records [metric:riot_truth/rounds#plant_riot_only=27] plants the store lacks, [metric:riot_truth/rounds#plant_riot_only_post_decision=18] after the round was decided [domain:rounds/post-round-plant-no-graphic]. Read each refusal's stored reason before changing a reader. Threads:
- `riot-residuals-20261004` (unmerged, `death-adjudication-0.35.1`, `killfeed-name-cluster-0.5.1`, `riot-truth-0.5.2`) fixes the name split at bfad2778a372, the split track across a revive at 9acf02f98283 968.5 s, the shared roster drop at b7d24102a6f6 1582.0 s and bdfdcf009dba 1704.5 s, and pairs deaths drawn at a stall's release; its commit body carries the before and after and the cause of every residual.
- In-round stall gaps: the roster-difference design and its predictions are in [STALL_ROSTER_DIFFERENCE.md](docs/STALL_ROSTER_DIFFERENCE.md).
- The entry at 223d636bf8d2 (`C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`) 1206 s: the Shooting Error graph covers slot 4's victim plate; the track reads the wrong side and name.
- a06f04a0059f (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`) 1768-1771 s: Skye's blind screen [domain:abilities/skye-guiding-light-blind-screen] hides the killfeed for 2.5 s; the tracker drops the one-sample onset and restarts the entry on a faded frame that reads the wrong side. The tracker needs blind spans as it has stall spans [domain:abilities/phoenix-curveball-blind-screen].
- The Not Dead Yet expiry at ff636d173b07 (`C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`) 1246.6 s: the one-colour band reader drops the entry on every sample (`one_colour:no_divider`, `one_colour:no_icon`).
- The killstreak numeral [domain:killfeed/killstreak-indicator] flags an extra Reyna kill at 4f207c0c4e39 (`C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`) 2195 s.
- Declare the `killstreak_witness` stream in `plan`.
- Earlier threads (killfeed box crop faults, KAY/O downs, the queue follow, post-round plants) keep their texts in the [10-04 archive](docs/archive/BACKLOG-through-2026-10-04.md).
Acceptance: `.\.venv\Scripts\python.exe prototypes\riot_ground_truth.py --all --offline --record`, its pooled numbers cited with `metric:` tokens.
Evidence: every residual failure classified by cause (instrument fault, reader refusal with its stored reason, adjudication, or out of scope such as a post-decision plant), never a count alone; each fix's before and after on the 21 matches, with no session losing a match.

**2. Game assets throughout production.** The player's directive (recorded 2026-10-04): every reader that matches game art or sound uses the extracted game files (the store's `reference/game-files/`). Ranked inventory:
- (a) the game's minimap ability markers as a caster-naming channel; an earlier probe named 164 of 192 held-out labels, the gallery 2 of 192; the wiring plan is [MINIMAP_GLYPH_CHANNEL.md](docs/MINIMAP_GLYPH_CHANNEL.md);
- (b) the game composite (container, tint, layers) for self, ally and stacked icons, replacing the calibration in `ally-portrait-refs-1.0.0`, whose art already equals the game textures;
- (c) ult voice lines (`game-vo-20261003`, in progress);
- (d) fonts (Tungsten-Bold, DINNext_Bold) for OCR digits, combat-report words and the killfeed "Me";
- (e) scoreboard thumbnails (6 of 31 exported);
- (f) base map and floor-mask checks, through the geometry builder only.
- *Identity on 4f207c0c4e39:* the player is Iso, but the arbiter refuses (`conflicting_claims`). The tray votes Iso 96 of 145, with spectated kits voting after death: count tray identity votes only while the player lives. `self_icon` votes Phoenix on flat scores (1.453 against Raze 1.446): refuse a pairwise tie, and place the 1.15x variant widget.
- *Audio:* `ability-audio-fit-20261004` fits seven agents and calibrates the margin (`ability-audio-params-0.2.1`, held ECE 0.039). Open: masking causes 12 of 15 held misses; the gate refuses 26 of the 120 verified casts (20 as `equip_release`); the player questions in the outcome row. Unmapped folders and clipped references are in NOTES.
- *Weapon:* the whitened open-set null (`whitened-weapon-20261003`, held).
Acceptance: per reader, `.\.venv\Scripts\python.exe -m reticle trial --reader <reader> SESSION` on a06f04a0059f, 5822b6646448 and 4f207c0c4e39 before and after the switch, then the Riot scorer above.
Evidence: each switched reader names its game-file source and version; same-or-better agreement with the player's labels and Riot, every changed verdict listed with its reason; 4f207c0c4e39 names Iso with no conflicting claim.

**3. Stacked ally icons and runtime.** Merge `stack-spike-merge-20261004` (stack-fit and game-spike together, `ally-icon-0.11.0`), then replace its analytic teardrop with render-and-compare against the game's icon art, and cut its +28 to 64 ms per frame. One fixed stacking order per match explained 186 of 199 overlapping pairs; the player does not know the cause, so test it as a draw-order prior. Lotus carries a 1 px y bias. Keep the runtime thread: `ally_icon` costs about twice as much per call on six sessions (587c15b07779, 5822b6646448, 7010b3d62460, a06f04a0059f, a1a995e6b19b, c62c2b06bcfb; paths in the 10-04 archive); model ms/call from stored poses by `search` and `surprise`.
Acceptance: `python prototypes/stack_fit.py labels --out <dir>` plus `size` on 223d636bf8d2 1250-1410, 3694746e4e54 884-1044, bfad2778a372 1259-1419, a06f04a0059f 600-760, then the Riot scorer's minimap block.
Evidence: zero labelled icons lost; Riot misses in stacks fall with phantoms no higher than at merge; per-frame cost below the merged branch's +28 to 64 ms; the slow six's cause named from stored data.

## Waiting

Full texts are in the dated archives.

- **Ability identification pass** (2026-10-03): name the ability behind a killfeed weapon-slot icon, then ability attribution generally; remove `classify_killfeed_icon`'s `active_agent` narrowing. Riot ability kills now match [metric:riot_truth/deaths#matched_kind_ability=75] of [metric:riot_truth/deaths#riot_kind_ability=77].
- **Icon descriptors, proven on the killfeed first** (2026-10-01).
- **Reader resampling** (2026-10-01), killfeed weapon first.
- **Death binding at sighting gaps** (2026-10-02): `binding-rules-20261002` (NOTES).
- **Ability candidate follow-ups** (2026-10-01); **duplicate Chamber death** on bfad2778a372 at 1017.0 s and 1018.5 s.
- **Scene model** (2026-09-29, [SCENE_MODEL.md](docs/SCENE_MODEL.md)); **economy ledger** (2026-10-03).
- **Player inputs**: the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md)'s open cells, plus the demo probe's questions in NOTES.
- **LAYER gap:** `lineup._composition` puts `prototypes/` on `sys.path`, and doctor does not flag it.
- **Minimap identity** ([results](docs/ALLY_MINIMAP_IDENTITY.md)); **the statistical adjudicator** ([plan](docs/STATISTICAL_ADJUDICATOR.md)); the geometry stamp's raw-byte hash; `docs/WORKING_MAP.md` and `PROJECT_GUIDE.md` over their word budgets; nothing links `docs/SCOREBOARD_LINEUP.md`.

## Completed

- **`whitened-audio-20261003` (2026-10-03):** own casts scored against the kit's whitened game sounds (`ability-audio-0.1.0`); tray gate `player-cast-0.8.0`.
- **`game-killicons-20261003` (2026-10-03):** game kill icons in the weapon gallery (`0.7.0`); killfeed pitch 39 px (`hud-0.20.0`).
- **`round-outcome-20261003` (2026-10-03):** `round-outcome-0.1.0`; stall deaths inferred (`death-adjudication-0.34.0`); listed in `plan` and `status`.
- **`one-colour-band-20261003` and `killstreak-numeral-20261003` (2026-10-03):** one-colour entries (`hud-0.19.0`); the killstreak numeral and witness.
- **`corpus-rerun-20261003` (2026-10-03):** the 21 matches from the crop cache and storage; `plan` names nothing on a match.

Full entries: [10-04 archive](docs/archive/BACKLOG-through-2026-10-04.md), [10-03 archive](docs/archive/BACKLOG-through-2026-10-03.md).
