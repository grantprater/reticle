# Reticle task queue

Each open item carries an `Acceptance:` command and an `Evidence:` standard. Earlier full texts are in the [10-09](docs/archive/BACKLOG-through-2026-10-09.md), [10-07](docs/archive/BACKLOG-through-2026-10-07.md), [10-06](docs/archive/BACKLOG-through-2026-10-06.md) and [10-05](docs/archive/BACKLOG-through-2026-10-05.md) archives. Capture paths for every session named here are in [NOTES](NOTES.md).

## Agreed order (2026-10-05, revised 2026-10-09)

Standing rules: replays may fit reader parameters offline with scoring matches held out ([policy](docs/EXTERNAL_GROUND_TRUTH.md)); no full corpus rerun runs until training on the replay data is finished; fidelity follows the question (AGENTS.md), judged by QA5r3 against replay truth ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7), with T1d as the draw rule. Split: development 9acf02f98283, c817691bcd15, d3dcfb182ab1; held-out cea8ecbc94ab (bd7efa02), scored once per version, never by a candidate that already failed. Rereads run only on the three 2026-10-07 sessions, cadaadeb2d8b, 066741deafe5 and 9912c382130b; ask before each.

**1. Convert every reader to opportunity gating and the slot model, abilities included.** The ratchets (CONVERT, ROUNDSCOPE, strict PROMOTE, ABILITY) and the per-frame gate hook are merged; the ally pass reads through ally gate 0.3.0, off by default. `status` prints the counts. The ability-entities plan joins this item, not a fourth, because the queue holds three.
- Score the gated ally pass once on the held-out match; the player decides the default switch.
- Convert reader by reader: the ability readers next, under their opportunity and audio gates, then the rest of `CONVERT_LEGACY`. Each conversion shrinks the list.
- ROUNDSCOPE: fix the 31 audited sites; review the 92 unreviewed detector sites.
- [ABILITY_ENTITIES.md](docs/ABILITY_ENTITIES.md) steps 2 to 7: the player's own children and effects; the team's children and `ability-owner`; the enemy's children; kits for every slot; the ability readers' gates (step 6, the conversion above); close with `ABILITY_LEGACY` empty. Each step carries its own acceptance command in the plan. The mechanics sheet's answers feed the lifecycles.
Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor` (CONVERT, ROUNDSCOPE, PROMOTE, ABILITY), then `.\.venv\Scripts\python.exe prototypes\real_reader_schedule.py hook SESSION...` and `hook-report --record` on each gated arm, and each plan step's own command.
Evidence: read share and CPU per session beside the 15 Hz arm; per question, slot and ability class, the loss with its interval under QA5r3 on the development matches, then once on the held-out match; each list shorter, never longer.

**2. Enemy lane, reader and belief.** The real enemy lane rarely places the killer, so join questions collapse on real reads.
- Residuals after the portrait gate, each to its owner or a named per-ability cue: finds on nothing (most in 066741deafe5), X marks read as enemies, wrongly named finds. Confirm `PING_OWN_PX` on the production ping stream. Soft rim coverage stays opt-in until a second 331 px replay match.
- Promote the T1d grid into `reticle/acceptance.py` (it needs `coaching_questions.Match`, `real_reader_schedule.RealMatch` and the `replay_truth` lag constants), then fold in the other scorers: `enemy_lane_check`, `real_reader_schedule`, `t1_draw_rule`, `execution_questions`.
- Then the reachable-set belief (`prototypes/coaching_belief.py`) as the enemy lane's carried state, so the killer holds a region at each death.
Acceptance: `.\.venv\Scripts\python.exe prototypes\question_acceptance.py lane --tag pgb2` on the 2026-10-07 sessions and `lane --tag pgb` on the development matches, then `.\.venv\Scripts\python.exe -m reticle acceptance summary`, which gains each subcommand as the grid moves.
Evidence: the `pgb` and `pgb2` arms reproduce; per class, outcomes summing to the finds with round-bootstrap intervals; `nothing_there` and the X-mark share fall; `join_death` accuracy on V15h against T1.

**3. Slot model** (QUESTION_ACCEPTANCE B1-B3). B1 is merged: `reticle/slot_state.py` owns `position-belief`.
- Walk reach: the gate and the belief use a Euclidean disc. Walk reach needs a walk graph baked into the geometry; run `reticle plan` for the streams it stales and ask the player before the bake.
- Reconcile the `resolve` and `beliefs` rules into one.
- B2-B3: the timeline shape change and the harness; missed reads modelled as runs; beliefs carry reach and region, not metres; a region builder cuts regions at chokepoints on the walk graph and splits height platforms.
Acceptance: `.\.venv\Scripts\python.exe prototypes\entity_state.py replay SESSION --binding causal --record` per development match, then the QUESTION_ACCEPTANCE harness once the vision timeline exists.
Evidence: calibration per match beside B1's; each logged prediction marked pass or fail; per question, accuracy against T1d beside the 15 Hz arm with its interval and read cost; the region builder's crossing rate, misdating, question loss and border width beside the callout regions'.

## Waiting

- **Execution readers**: placement and angle clearing from the stored cone facing, counter-strafe and first shot from a window-gated centre-crop reader (ask before its decode), head share from the combat report. Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands, plus a reader trial on the development matches. Evidence: each measurement's error against replay truth and the duel value it keeps.
- **Spray discipline**: replay truth can test it. Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands. Evidence: duel value with an interval.
- **Utility response**: vrfkit leaves `CausingActor` in raw bits. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: each utility's causer named and checked against casts on two replays.
- **"?" fade conflict**: the widget's 3.0 s lifetime [domain:minimap/last-known-mark-widget-lifetime] against the measured fade [domain:minimap/last-known-mark-timing]. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist`. Evidence: the timer's start named, or both starts refuted.
- **9acf02f98283's persistence tail**, possibly reveals. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist 9acf02f98283`. Evidence: each long swap classed by eye with its cause.
- **Smoke geometry** [domain:abilities/minimap-vision-cone-blockers] and **unmodelled walls** (Blaze, Toxic Screen, Cosmic Divide, Sage, Iso, Neon, Harbor, Vyse). Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py smokes` and `lane`. Evidence: each shape from its game file or fact; misses and extras against T1d before and after.
- **Self-entry defect**: d3dcfb182ab1 reads K/D 12/19, the replay 13/17; account-name captures name the player Deadlock. Acceptance: `.\.venv\Scripts\python.exe -m reticle self-entries d3dcfb182ab1`. Evidence: K/D equal to the replay's on every replay session.
- **Crop caches with every frame a key frame** (`-g 1`), the player's call: cheaper gated fetches, every cache stale. Acceptance: `.\.venv\Scripts\python.exe -m reticle scan cadaadeb2d8b --only roi_cache --cache-roi minimap --cache-hz 15 --cache-live` (a decode the player starts; the old caches were deleted 2026-10-09), then `.\.venv\Scripts\python.exe -m reticle usage cadaadeb2d8b`. Evidence: fetch CPU per read beside the current caches; crops byte-identical.
- **Ingest wiring**: older `combat_report_rows` lack the coverage row `plan` reads; thread caps leak; readers and caches need one 15 Hz grid. Acceptance: `.\.venv\Scripts\python.exe -m reticle plan cadaadeb2d8b` and `frame-join c817691bcd15`. Evidence: plan names only real gaps; join rate 1.0 exact.
- **Replay-layer defects**: `lives` keeps departed players alive; the walk graph drops cells along barriers and doors and lacks jump and drop edges; `cast` row order varies by build. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: departed players dead; two builds byte-identical.
- **Carried** (dated in the archives): ally-icon cost; the spelling owner's remainder; killfeed residuals, with in-round stall gaps by the [roster difference](docs/STALL_ROSTER_DIFFERENCE.md); tray grid; glyph follow-ups; Clove; origin-fact wording; player questions; pickup returns; game assets; restated round windows; 0f08b3dc3777 naming; audio-fit residuals; icon descriptors; reader resampling; death binding at sighting gaps; duplicate Chamber death at bfad2778a372; scene model; economy ledger; the statistical adjudicator; the geometry stamp's raw-byte hash. Acceptance: each item's own command in the [10-09](docs/archive/BACKLOG-through-2026-10-09.md) or [10-05](docs/archive/BACKLOG-through-2026-10-05.md) archive. Evidence: as there.

## Completed

- **`gate-crop-seek-20261009` (2026-10-09):** ally gate 0.3.0; the crop fetch seeks with PyAV for sparse reads and keeps OpenCV for dense ones.
- **`gate-hook-20261009` (2026-10-09):** the per-frame gate hook in `passes` and the gated ally pass, off by default.
- **`teardrop-new-sessions-20261009` (2026-10-09):** the enemy lane scored on the 2026-10-07 sessions (tag `pgb2`).
- **`ability-entities-step1-20261009` (2026-10-09):** the ABILITY ratchet, `CHANNELS`, ability ownership and contract rejections.
- **`harness-promote-20261009` (2026-10-09):** the acceptance core moves to `reticle/acceptance.py`.

Earlier entries: [10-09 archive](docs/archive/BACKLOG-through-2026-10-09.md).
