# Reticle working handoff

## Picking up

**2026-10-07, night.** Master stands at the merge of `handoff-20261007-3`, pushed. The [backlog](BACKLOG.md) order holds: the enemy lane, reader and belief; the slot model; the execution readers. The late 10-07 handoff, with the teardrop fix and the one transform's first measurements, is [archived](docs/archive/NOTES-2026-10-07-late.md). The bar is now the owning layer's emitted events scored per question against replay truth, every entity class included (AGENTS.md), with T1d as the draw rule.

### Merged today

- **One transform** (`a015c85`): every map-drawn size reads at base times widget scale times map zoom. On 9acf02f98283 self recall rose from [metric:one_transform_check/truth/m1@9acf02f98283#self_recall=0.6809] to [metric:one_transform_check/truth/b1@9acf02f98283#self_recall=0.7627]; the enemy lane's true false accepts end at [metric:teardrop_refusals/lane/b1@9acf02f98283#false_accepts=145], within the bar of 159, because only the enemy search keeps the inward radius band. The single self-facing gate now cuts some correct 465 px reads (`32b837e`).
- **Enemy portrait gate** (`a0824c8`, minimap-object-0.8.0): every ring peak is proposed and kept only where its interior fits one of the match's enemy five. True false accepts on 9acf02f98283 fell from [metric:teardrop_refusals/lane/b1@9acf02f98283#false_accepts=145] to [metric:teardrop_refusals/lane/pgb@9acf02f98283#false_accepts=30]. Soft rim coverage stays opt-in until a second 331 px replay match exists.
- **Owning-layer rules, doctor RESTATE, the event harness** (`851f99b`, `25b7287`, `1d0e135`): `prototypes/question_acceptance.py` scores the enemy lane's emitted tracks. The lane names [metric:question_acceptance/lane/pgb@dev3#fa_named=157] of the reader's false accepts.
- **Detection reality** (`530e613`): `round_lifetimes.detection_reality` refuses an enemy track that lies on a placed ability glyph. Seven drone and creature facts joined `domain/abilities.toml`, with the Prowler [domain:abilities/fade-prowler-lock-on] and Devour [domain:abilities/reyna-devour-not-on-minimap] [domain:abilities/reyna-devour-tether] facts after.
- **Class-aware harness** (`54f61a3`): T0 carries every replay ability child. Of the old true false accepts, 126 of 167 lie on another real entity, most on Tejo's Stealth Drone; the players-only control reproduces exactly.
- **K/D from the self-entry owner** (`a60c191`, hud-0.28.0): status, rounds and the combat report ask `adjudication.self_entry`; the "Me" matcher no longer reads "Mga Yawa"; `plan` lists never-run steps. `match_arc` (`75261e7`) measures the player's arc over a match from Riot records.

### New sessions

Three 465 px captures with replays kept and Riot records wrapped: cadaadeb2d8b Ascent, 066741deafe5 Sunset, 9912c382130b Sunset. K/D agrees with the replay on all three. Ult lines and ult casts are written; ability light wrote nothing, because no `ability_candidates` file exists (the `scan_ability_clip` decode makes one). Comms are off from this date.

### Open

- d3dcfb182ab1 reads K/D 12/19 against the replay's 13/17: a `self_entry` defect.
- `plan` still names `combat_report_identity` (an empty file reads as never run) and `dead_ruse_cast` (written only for a Clove player); each needs a plan or writer fix.
- Three `tests/test_riot_economy.py` failures predate `b5011c0`, possibly from the 62 new Riot records.
- The enemy reader names many finds wrong and reads X marks as enemies; enemy recall stays low (counts on the error-budget branch, unrecorded). The labelling tool `prototypes/label_enemy_disagree.py` waits on `enemy-labels-20261007`; the error budget on `enemy-error-budget-20261007`. Neither is merged.
- Harness steps 5 to 8 (ally finds, smokes, glyphs, X and "?" marks) and step 9 (folding `replay_truth score` and `replay_abilities score` onto the layer) wait for the player's approval.
- The `PROJECT_GUIDE.md` split is queued. Check the subagent context floor with a probe.
- Stale streams: every older session's hud (its output is identical) and `minimap_object` and `enemy_track` elsewhere wait for the batched corpus rerun.

### Unmerged branches

`enemy-labels-20261007`, `enemy-error-budget-20261007`. From earlier: `w1-ally-prior-score-20261006`, `w2-self-tracker-score-20261006` (negative results); `one-pass-ingest-20261005`; held `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework `binding-rules-20261002`; WIP `luma-render-20261002`, `wip-vision-lifecycle-wiring`; plans `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; `enemy-fix-check-20260930`.

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`; cadaadeb2d8b `C:\Users\grant\Videos\2026-10-07 12-29-01.mp4`; 066741deafe5 `C:\Users\grant\Videos\2026-10-07 13-06-26.mp4`; 9912c382130b `C:\Users\grant\Videos\2026-10-07 13-41-20.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
