# Reticle working handoff

## Picking up

**2026-10-05.** Master stands at `a24376c`, pushed. The [backlog](BACKLOG.md) holds three active items: one owner for agent-name spellings, then rerun c817691bcd15 from storage; the ally-icon cost; batch-1 retirement with the unified acceptance corpus run. `reticle status` shows the 21 matches stale on hud until that run. The previous handoff is [archived](docs/archive/NOTES-2026-10-04-to-10-05.md).

### Merged since the 2026-10-04 handoff

Master took 116 merges (`git log --first-parent be4d8bc..a24376c`), each after a judge and a test merge; commit bodies carry the measurements.

- **Killfeed and deaths:** `riot-residuals`, `killfeed-residuals`, `assist-panel`, `killfeed-panel-cache`, `ability-kill-icons`, `wallbang-probe`, `weapon-binding` (weapon-adjudication to 1.8.0) and `killfeed-followups` (`8c036a8`). The follow-ups renumber onto hud-0.24.0: plate-seam divider hud-0.25.0, scenery-topped one-colour run hud-0.26.0, killfeed-portrait 0.24.0, killfeed-weapon 0.18.0 (wallbang field), killfeed-name 0.9.0, death-adjudication 0.42.0, weapon-adjudication 1.9.0. The fix commits still say provisional and name the old stamps; the merge commit maps them. Targeted windows: [metric:riot_truth_window/paired~kff-targets-20261005#fixed=3] fixed, [metric:riot_truth_window/paired~kff-targets-20261005#broken=0] broken; declared sample: [metric:riot_truth_window/paired~kff-sample-20261005#fixed=0] fixed, [metric:riot_truth_window/paired~kff-sample-20261005#broken=0] broken.
- **Digits and rounds:** `game-fonts`, `soft-digits` (hud-0.24.0, scoreboard-0.14.0), `scoreline-soft`, `topbar-pill`, `round-owner`, `rounds-reset`, `round-no-fix`, `round-filter`, `scoreboard-claims`, `scoreboard-reads`, `cache-gates`.
- **Glyph channel:** `minimap-glyphs`, `glyph-reader` (stage 2, ability-glyph to 0.5.0), `glyph-prereqs`, `glyph-tables`, `glyph-answers`, `glyph-stage3` (ability-glyph-name-0.3.0).
- **Allies:** `stack-spike-merge` (ally-icon-0.11.0, spike-0.3.0), `ally-vectorise` (`2b921f7`), `ally-waiver`, `entity-binding`, `vision-poses`.
- **Casts and audio:** `game-vo`, `ability-audio-fit`, `audio-others`, `ability-xchannel`, `ult-*`, `tray-gold`, `gold-persist`, `own-cast-residuals`, `own-cast-gate` (player-cast to 0.14.0, ult-cast to 0.6.0), `tray-2hz`, `clove-dead-ruse`, `clove-dead-answers`.
- **Domain facts:** `game-data`, `game-files-precedence`, `pickup-facts`, `slot-facts`, `economy-facts`, `restock-measure`, `player-answers`, `blaze-and-conflicts`, `ability-origin-facts` (`5846d25`: Astra stars, Trapwire, Spycam, Trademark, Rendezvous's one anchor, Leer through walls, Skye's dog and Trailblazer, Sova and Tejo drones).
- **Truth and strategy:** `replay-truth`, `replay-abilities`, `match-fetch-kit`, win-probability and coaching research, `engagement-reach` (3D sightlines), `runtime-budget`, `frametime-kit`.
- **Process:** `dev-sample` (`reticle dev-sample`), `test-audit`, `doc-budgets`, `layer-gap`.
- **Video retirement** (`0c04693`, `6791c19`): `reticle retire SID` stream-copies the audio, checks it packet by packet and through every audio reader, marks the manifest retired, never deletes, and refuses without `--commit`. `reticle/audio_source.py` owns where a session's audio lives; a retired session's scan reads the crop cache; `plan` lists uncacheable steps as `source_retired`; doctor checks SOURCE. Dry runs on c62c2b06bcfb and a06f04a0059f differed in no packet, sample, log-mel value, ult-line peak or ability-audio row. Retire refuses a dev-sample match without `--force-reason`. The scoreboard reader declares no cache set, so its reread still needs video. Label sets `ability_recall_20260930`, `minimap_dynamic` and `weapon_icon` stay unchecked.
- **Combat-report crops** (`de9316f`, `186ec60`): the `combat_report` crop set keeps one frame per distinct read (combat-report-frames-0.2.0) and reproduced kills, deaths, assists and sources on 96 of 96 kept rounds over five sessions. The set drops the death panel's timing, so `death_panel_tops`, `panel_aside` and identity naming refuse a thinned stream: keep the full stream and reread the set only when the reader changes. No whole-capture dry run yet; one 300 s window of 043bafca271a kept 2 frames.

### Store changes outside git

- Tray 2 Hz migration freed 7.51 GB (21 of 21 sessions, 140,514 rows, none differ); check files sit in `roi_cache/minimap/roi-cache-0.1.0.tray-thinning`. Scoreboard migration freed 2.32 GB (14 of 14).
- 0f08b3dc3777, a broken capture, was removed at the player's request; its manifest, primitives and spans sit in `backups/delete-0f08-20261005`. Prototypes and `profiles.py` comments still call it Abyss; its Riot record says Summit.
- `labels/minimap_glyph_questions/answers.jsonl` holds 477 rows after three Blaze rows revised earlier answers.

### c817691bcd15 ingest, 2026-10-05

Ascent, `valorant-16x9-bigmap`, 48:28; preflight passed against donor a06f04a0059f; 28 rounds, 207 deaths, 5 revives; caches 4.77 GB (hud 1.49, minimap 2.45 with the tray thinned to 94 MB, killfeed_panel 0.03, scoreboard 0.80). The replay `.vrf` sits in `external/replays` with a manifest entry (header fields null: the probe that filled them is not in the repo), parsed by vrfkit-0.2.5. The ingest's judge was stopped, so the ingest is unjudged. Defects:

- **Player unbound.** The player was KAY/O; `reticle/adjudication/identity.py` line 344 compares the tray's `KAY/O` with the lineup's `KAY_O` letter for letter. Commit `2e68ab4` fixed only the killfeed kits. So ult-cast found no own casts, the tray stayed unbound, ability-shapes skipped, and all 279 gated ability samples found no caster. 4f207c0c4e39 binds correctly.
- The lineup named an enemy Clove absent from the replay (3 of 5 named, one wrong).
- The rounds table's K/D says 10/28; the replay and the rounds' own died-in-round count say 10/24.
- `replay_abilities.py` census crashed with a TypeError.
- No Riot record: the client was logged out, and only the player runs [the fetch kit](docs/MATCH_FETCH_KIT.md). `riot_ground_truth` reads only wrapped files in `external/riot/`; a wrap step from `external/riot-pd-v1/raw/` is missing.
- **Cost** (`reticle usage c817691bcd15`): the video passes ran 6,850 s serially on about one core while 5.5 to 8.5 of 12 logical processors idled. `ally_icon` at 15 Hz took 3,722 s, 54% of the ingest, about 94 ms per frame (stack_fit 1,597 s, pose 1,262 s); the five NVDEC decodes took about 1,550 s. The minimap pass's recorded CPU time matches its wall time, which weakens the CPU-sharing explanation.

### Unmerged branches

- **`one-pass-ingest-20261005`** (`8aa279b`, pushed): stopped by the player 2026-10-05, unfinished; backlog item 2 holds it.
- Held: `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework: `binding-rules-20261002`; WIP: `luma-render-20261002`, `wip-vision-lifecycle-wiring` (do not merge); plans: `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; mergeable with bumped versions: `self-spike-tracker-20260929`; `enemy-fix-check-20260930`.
- Stale leftovers: `kff-old-20261005` (local; the pre-renumber killfeed follow-ups), `ally-ring-subpixel-20261001` (negative result), `stacked-icons-20261002` (superseded), `origin/decodes-20260929`, `experiment/bootstrap-*`, `wip-primary-20260926`, three `worktree-agent-*`, `origin/unmerged-census-20260926`, `origin/unmerged-glyph-refusal-20260923`.

### Side findings

- The LAYER gap closed: `196cd24` stopped `lineup` loading prototypes.
- Combat-report surprise against the player's statement that the report holds within a round: b7d24102a6f6 round 18 and 7010b3d62460 round 2 show two distinct reads; show the player those frames. 587c15b07779 round 8 drops its 672 s read (`reads_dropped`).

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
