# Reticle task queue

Each open item carries an `Acceptance:` command and an `Evidence:` standard. Earlier full texts are in the [10-06](docs/archive/BACKLOG-through-2026-10-06.md), [10-05](docs/archive/BACKLOG-through-2026-10-05.md), [10-04](docs/archive/BACKLOG-through-2026-10-04.md) and [10-03](docs/archive/BACKLOG-through-2026-10-03.md) archives. Capture paths for every session named here are in [NOTES](NOTES.md).

## Agreed order (2026-10-05, revised 2026-10-06)

The player reversed the order to 3, 2, 1, retired every capture without a replay, and set two rules: replays may fit reader parameters offline with scoring matches held out ([policy](docs/EXTERNAL_GROUND_TRUTH.md)), and no full corpus rerun runs until training on the replay data is finished (AGENTS.md). On 2026-10-06 the player set the frame for all three: fidelity follows the question (AGENTS.md), judged by coaching and summary answers against replay answers ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md)), with a stretch goal under 1 ms per frame.

**1. Build the slot model to answer the catalogued questions.** The questions are ranked ([COACHING_QUESTIONS.md](docs/COACHING_QUESTIONS.md)) and the schedule chosen (`Lp0.5-250w5`, 0.0484 of today's reads on truth); the timing model is [RENDER_DELAY.md](docs/RENDER_DELAY.md). Next: QUESTION_ACCEPTANCE's build list from B1 (ENTITY_STATE step 1, `slot_state` from stored rows, measured against today's numbers), then B2-B3, the timeline shape change and the harness; then the gated readers and the gate's own cue, priced. Split: development 9acf02f98283, c817691bcd15, d3dcfb182ab1; held-out cea8ecbc94ab (bd7efa02), scored once per version, never by a candidate that already failed.
Acceptance: `.\.venv\Scripts\python.exe prototypes\replay_truth.py score SESSION --record` per development match, then the QUESTION_ACCEPTANCE harness once the vision timeline exists.
Evidence: each logged prediction marked pass or fail; worst cases beside located shares; per question, answer agreement against replay and masked truth with its read cost.

**2. The ally-icon cost, by fidelity.** On c817691bcd15 `ally_icon` at 15 Hz ran about 94 ms per frame, 54% of the ingest. The rate decision now follows item 1's degradation results rather than a fixed reduced rate; ally-rate-0.1.0 (`2da7536`) drops its outcome-gated death cue. Still open: the 94 against 61 ms gap; parallel readers on idle cores; `one-pass-ingest-20261005` (`8aa279b`), whose equivalence check never ran.
Acceptance: `.\.venv\Scripts\python.exe -m reticle usage c817691bcd15` and `.\.venv\Scripts\python.exe -m reticle trial --reader ally_icon SESSION` on the vectorise windows (`2b921f7`).
Evidence: the gap attributed to named causes with CPU and wall time apart; any rate change judged on item 1's question answers; parallel passes reproduce serial outputs.

**3. The spelling owner's remainder, then rerun c817691bcd15 from storage.** `reticle/agent_names.py` owns spellings (merged). Left: prototype spelling rules; the hud and ally_icon rereads `plan` names, then `deaths`; the rounds K/D rule (10/28 against 10/24), which `adjudication.self_entry` now counts as 10/25; the census TypeError. Judge the ingest.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan c817691bcd15` naming nothing.
Evidence: each c817 defect fixed or classified with its stored reason; no agent-name comparison outside the owner.

## Waiting

- **Ingest wiring** (2026-10-06): `plan` omits a new capture's never-run steps; `replay_layer` needs Riot for the player (replay-truth 0.3.0 reads it from the replay); thread caps leak (FFV1 cache decodes run near 3x wall); c817691bcd15's `ally_icon` and minimap cache sit at different 15 Hz phases, so readers and caches need one grid (`reticle frame-join SESSION` checks).
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan d3dcfb182ab1` and `.\.venv\Scripts\python.exe -m reticle frame-join c817691bcd15`. Evidence: never-run steps listed; join rate 1.0 exact; CPU near wall time.
- **Self-entry follow-ups** (2026-10-06): rounds and combat report still count K/D from "Me" (cea8ecbc94ab reads 0/0; self-entry reads 8/15, the scoreboard's); on account-name captures the player's name clusters are named Deadlock, mislabelling the player's kills and deaths; a covered readout slot could read the killer side.
Acceptance: `.\.venv\Scripts\python.exe -m reticle self-entries cea8ecbc94ab`. Evidence: rounds K/D equal to self-entry; no cluster names the player another agent.
- **Replay-layer defects** (2026-10-06): `lives` keeps departed players alive (7498df5e, 2c387cb6); the sightline walk graph drops cells along barriers and doors and lacks jump and drop edges; `cast` rows vary in order between builds.
Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: departed players dead from their departure; walk-graph edges listed; two builds byte-identical.
- **Killfeed residuals** (2026-10-05): the single-frame Blade Storm kill at b3b9defb6fd7 1339.5 s refuses victim and weapon; 59c70f1ef720 1153.0 s refuses the killer on both codes; 59c70f1ef720 1271.0 s misplaces a band at rows 0-38 and now refuses rather than reading two entries; wallbang precision 6 of 6 by eye, recall unmeasured. Carried: the killer-anchor cases, ff636d173b07 1247.5-1248.5 s, the unread mark at 96aa1ae9b96f 770.5 s; in-round stall gaps by the [roster difference](docs/STALL_ROSTER_DIFFERENCE.md).
Acceptance: `.\.venv\Scripts\python.exe -m reticle dev-sample` plus `trial` on these windows. Evidence: each case fixed or refused with its stored reason; wallbang recall against Riot.
- **Tray grid** (2026-10-05): the tray r1 rect is kept only on the 0.5 s grid (roi-grid-thin-0.1.0) and an off-grid read raises `ThinnedOut`; `prototypes/live_load.py`, `prototypes/own_cast_residuals.py` (near line 811) and `prototypes/tray_suspect_reasons.py` (near line 232) read off it. Regrid or retire each.
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_tray_grid_cache.py` and each prototype's run. Evidence: no `ThinnedOut`; outputs equal to pre-thinning ones or the difference explained.
- **Glyph follow-ups** (2026-10-05): stage 3 surprise rows must use `above_bank_cut`; rerun the stage 3 marks arm at ability-glyph-name 0.3.0; a mirror-match own-caster rule; revise gate 6 with the origin facts (needs base px per metre per map); gate 4 fresh labels (c817691bcd15 a held-out candidate); the Omen rule's scale; rerun 7010b3d62460's stale stage 3 rows from storage. Gate 3 paint frames, which the player runs: `.\.venv\Scripts\python.exe prototypes\paint_icons.py dae6f33f3f48 --frames 12` and `.\.venv\Scripts\python.exe prototypes\paint_icons.py d95cfad5693a --frames 24`.
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_ability_glyph.py tests\test_ability_glyph_name.py`. Evidence: each gate's score in [the plan](docs/MINIMAP_GLYPH_CHANNEL.md) on held-out labels.
- **Clove** (2026-10-05): `ability_state` consumes `dead_ruse_cast`; `smoke_owner`'s dead-circle reach uses `post_death_map_range` 42.5 m; hedge `clove-dead-ruse-recharges`; export the player's OnPostDeathPossess answers into the game_data exceptions; settle what Riot's Ruse count means.
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_ability_state.py tests\test_smoke_owner.py tests\test_clove_circle.py`. Evidence: Clove casts against Riot's count, each difference explained.
- **Origin-fact wording** (2026-10-05, judge, low): `reyna-leer-origin-set-distance` should say her aim sets the direction and pitch the distance; `chamber-rendezvous-replace-repeatedly-belief`, that the recall cooldown applies outside RoundStarting.
Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`. Evidence: DOMAIN clean; the player's answers unchanged in substance.
- **Player questions** (2026-10-05): the conflict sweep's open questions are the [mechanics sheet](docs/ABILITY_MECHANICS_SHEET.md)'s `?` cells and question sentences; no separate list exists. Not in the sheet: minimap icon rotation and the Blade Storm kunai (demo probe, [10-04 NOTES archive](docs/archive/NOTES-2026-10-04-to-10-05.md)); the player's Sova audio remap, which dev refuted 86 to 68 of 98 (same archive).
Acceptance: `.\.venv\Scripts\python.exe -m reticle domain`. Evidence: each answer recorded with its date, nothing inferred by analogy.
- **Pickup returns in the charge model** (2026-10-04): a `pickup` transition and a `cooldown` mode in `adjudication.ability_state` [domain:abilities/deployed-pickup-returns-charge].
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_ability_state.py`, then `.\.venv\Scripts\python.exe -m reticle ability-state --all --record`. Evidence: each Killjoy, Cypher and Chamber rise named pickup or recharge with its witness.
- **Game assets, remainder** (2026-10-04): the game composite for self, ally and stacked icons (render-and-compare in place of the analytic teardrop; test a fixed draw order; Lotus 1 px y bias); combat-report words in Tungsten-Bold (old 2(d)) and the killfeed "Me"; scoreboard thumbnails; the geometry builder reading caches instead of video; ult voice lines in production if `plan` names `ult_line`; residual soft-digit refusals and `normalise` re-binarising.
Acceptance: `.\.venv\Scripts\python.exe -m reticle trial --reader <reader> SESSION` on a06f04a0059f, 5822b6646448 and 4f207c0c4e39. Evidence: each reader names its game-file source; same-or-better against labels and Riot.
- **Restated round windows in prototypes** (2026-10-05): eight prototypes test `t_start_ms <= t <= t_end_ms` instead of asking `rounds.round_containing`.
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests`. Evidence: every moved event listed and explained.
- **0f08b3dc3777 naming** (2026-10-05): prototypes and `profiles.py` comments call it Abyss; its Riot record says Summit. Acceptance: `git grep 0f08b3dc3777`. Evidence: every mention says Summit or removed.
- **Carried** (dated in the archives): `ability-audio-fit` residuals (masking causes 12 of 15 held misses; the gate refuses 26 of 120 verified casts, 20 as `equip_release`); ability identification pass; icon descriptors; reader resampling; death binding at sighting gaps (`binding-rules-20261002`); ability candidate follow-ups; duplicate Chamber death at bfad2778a372; scene model; economy ledger; minimap identity; the statistical adjudicator; the geometry stamp's raw-byte hash; nothing links `docs/SCOREBOARD_LINEUP.md`.
Acceptance: each item's own command in the [10-05 archive](docs/archive/BACKLOG-through-2026-10-05.md). Evidence: as there.

## Completed

- **`fidelity-principle-20261006` (2026-10-06):** the AGENTS.md rule; two precedents archived.
- **`killfeed-robust-20261006` (2026-10-06):** `adjudication.self_entry` (side plus bound agent's portrait, "Me" second); the Shooting Error readout [domain:hud/shooting-error-readout] refuses covered slots (hud-0.27.0); cea8ecbc94ab reads 8/15 against the scoreboard.
- **`frame-join-20261006` (2026-10-06):** `reticle/frame_join.py` (grid joins refuse below 0.99; sampled state with age); c817691bcd15 W1 and W2 rescored, no verdict changed.
- **`agent-replay-self-id-20261006` (2026-10-06):** replay-truth-0.3.0 names the player from the replay; agrees with Riot on 2 of 2.
- **`agent-spelling-owner-20261006` (2026-10-06):** `reticle/agent_names.py`; KAY/O bound on c817691bcd15 and d3dcfb182ab1.

Full entries: [10-06 archive](docs/archive/BACKLOG-through-2026-10-06.md).

Archived 2026-10-07 (late):

- **`fidelity-principle-20261006` (2026-10-06):** the AGENTS.md rule; two precedents archived.

Archived 2026-10-07 (night):

- **`teardrop-review-fixes-20261007` (2026-10-07):** enemy icons read at the map's zoom, the ring scored softly with one cut, danger pings handed to the ping owner; 9acf02f98283's T1d hit rate 0.442 to 0.6313 (NOTES).
- **`execution-questions-20261007` (2026-10-07):** [EXECUTION_QUESTIONS.md](docs/EXECUTION_QUESTIONS.md); placement, first-shot hit and counter-strafe carry duel value; shooting first does not.
- **`t1-draw-rule-20261007` (2026-10-07):** T1d (measured persistence, both teams' smokes, no dead enemies) in `prototypes/t1_draw_rule.py`.
- **`enemy-lane-check-20261007` (2026-10-07):** most T1-drawn misses are T1 errors; `prototypes/enemy_lane_check.py`.
- **`real-reader-schedule-20261007` (2026-10-07):** `Vgate` passes QA5r3 post hoc; reach questions; `prototypes/real_reader_schedule.py`.
- **`one-transform-rebased-20261007` (2026-10-07):** every map-drawn size at base x widget scale x map zoom; the enemy search alone keeps the inward radius band.
- **`restate-check-20261007` (2026-10-07):** doctor RESTATE.
- **`owning-layer-rules-20261007` (2026-10-07):** acceptance on emitted events; the detection-reality question.
- **`match-arc-20261007` (2026-10-07):** `prototypes/match_arc.py`.
- **`replay-every-entity-rule-20261007` (2026-10-07):** AGENTS.md, replay truth covers every entity.

Item 1 as it stood before the night handoff:

- Finish the one transform: rerun `one-transform-rebased-20261007` (`023a4a8`, the search-radius fix) on the development matches, re-stamp, test, review and merge. The enemy lane's true false accepts on 9acf02f98283 must return within the bar (159); self and ally gains must hold with intervals. Then wire the X-mark input, `floor_mask`, `site_mask` and the occluder bake, and say whether `minimap_dark` rereads from the cache.
- `minimap_objects` residuals after `4a71ffb`: pink X marks at 0.71 (the X classifier's tolerance), enemy utility discs and Reyna's Leer, each by its owner or a named per-ability cue; proposals inside stacks; `low_ncc` misses at scale 1.0; confirm `PING_OWN_PX` on the production ping-0.2.0 stream.
- **Event-level acceptance harness** (2026-10-07): `prototypes/question_acceptance.py`, QUESTION_ACCEPTANCE B7 begun early, scores the enemy lane's emitted tracks, and later the slot beliefs, per question against T1d on the development matches. It reuses the existing truth join (`t1_draw_rule.RealDrawMatch(rule="T1d")`, `enemy_lane_check.build_sets`, `real_reader_schedule.RealMatch.enemy_reads`), not a sixth scorer; runs `enemy_tracks.build` over a tagged arm's rows, never the stored stream; and reports the reader's classes beside it as diagnostics. First measurement: of the `pgb` arm's pooled true false accepts [metric:enemy_portrait_gate/paired/pgb-vs-b1@dev3#false_accepts=167] (`enemy-portrait-gate-20261007`), how many the lane leaves unnamed, names off the enemy team, or keeps under a name. Then the class-aware harness (AGENTS.md, "Replay truth covers every entity"): (1) record the six drone and creature facts (done 2026-10-07, `domain/abilities.toml`); (2) `truth_under` over every replay entity class, with T0 carrying the children; (3) a class-aware lane that reproduces today's numbers under the old definition as a control; then ally finds, smokes, glyphs, X and "?" marks, and folding `replay_truth score` and `replay_abilities score` onto the layer. Acceptance: `.\.venv\Scripts\python.exe prototypes\question_acceptance.py lane --tag pgb` on the three development matches. Evidence: per match and pooled, false accepts by lane outcome with a round-bootstrap interval; per question, track-level accuracy against T1d beside the reader's hit rate.

Archived 2026-10-07 (night, second):

- **`detection-reality-20261007` (2026-10-07):** `round_lifetimes.detection_reality` refuses enemy tracks on a placed ability glyph; drone and creature facts.
- **`event-harness-20261007` (2026-10-07):** `prototypes/question_acceptance.py lane` scores the enemy lane's emitted tracks against T1d.
- **`enemy-portrait-gate-20261007` (2026-10-07):** ring peaks kept only where they fit the match's enemy five (NOTES).
