# Reticle task queue

Each open item carries an `Acceptance:` command and an `Evidence:` standard. Earlier full texts are in the [10-07](docs/archive/BACKLOG-through-2026-10-07.md), [10-06](docs/archive/BACKLOG-through-2026-10-06.md), [10-05](docs/archive/BACKLOG-through-2026-10-05.md) and [10-04](docs/archive/BACKLOG-through-2026-10-04.md) archives. Capture paths for every session named here are in [NOTES](NOTES.md).

## Agreed order (2026-10-05, revised 2026-10-07)

Standing rules: replays may fit reader parameters offline with scoring matches held out ([policy](docs/EXTERNAL_GROUND_TRUTH.md)); no full corpus rerun runs until training on the replay data is finished; fidelity follows the question (AGENTS.md), judged by QA5r3 against replay truth ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7), with T1d as the draw rule. Split: development 9acf02f98283, c817691bcd15, d3dcfb182ab1; held-out cea8ecbc94ab (bd7efa02), scored once per version, never by a candidate that already failed.

**1. Enemy lane, reader and belief.** The real enemy lane rarely places the killer, so join questions collapse on real reads (NOTES).
- `minimap_objects`: propose candidates inside stacks; stop the teardrop refusing visible icons (`no_ring`, `low_ncc`), worst at widget scale 0.71; reject enemy utility and ping icons; stop the "?" witness taking an unread icon's pointer for a "?".
- Then the reachable-set belief (`prototypes/coaching_belief.py`) as the enemy lane's carried state, so the killer holds a region at each death.
Acceptance: `.\.venv\Scripts\python.exe prototypes\enemy_lane_check.py sets SESSION` rerun against T1d, plus `.\.venv\Scripts\python.exe prototypes\real_reader_schedule.py reach` on the development matches.
Evidence: per match, the reader's share of misses and its extras against T1d; `join_death` accuracy on V15h against T1.

**2. Slot model** (QUESTION_ACCEPTANCE B1-B3, revised 2026-10-07). B1 is ENTITY_STATE step 1, `slot_state` from stored rows; then B2-B3, the timeline shape change and the harness; then the gated readers and the gate's cue, priced.
- Missed reads come in runs; model them so.
- Beliefs carry reach and region, not metres.
- The gate uses walk reach, not a 20 m radius.
- A region builder cuts regions at chokepoints on the walk graph and splits height platforms (player, 2026-10-07), tested as the callout regions were: crossing rate, interpolation misdating, question loss, border width.
- The held-out match is scored once per version.
Acceptance: `.\.venv\Scripts\python.exe prototypes\replay_truth.py score SESSION --record` per development match, then the QUESTION_ACCEPTANCE harness once the vision timeline exists.
Evidence: each logged prediction marked pass or fail; worst cases beside located shares; per question, accuracy against T1d beside the 15 Hz real-read arm with its interval and read cost; the region builder's four tests beside the callout regions'.

**3. Execution readers**, in the player's order ([EXECUTION_QUESTIONS.md](docs/EXECUTION_QUESTIONS.md)).
- Coarse placement and angle clearing from the stored cone facing, must-check angles from the sightline tables, with the enemy icon's error modelled.
- Counter-strafe and first-shot outcome from a window-gated screen reader on the centre crop [domain:capture/crosshair-white-cross] [domain:hud/hit-yellow-flash] [domain:capture/enemy-highlight-red]. It needs a decode of engagement windows: ask the player first.
- Head share from the combat report as the bad-aim alarm [domain:hud/no-distinct-headshot-sound-belief].
Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands, plus a reader trial on the development matches.
Evidence: each measurement's error against replay truth and the duel value it keeps.

## Waiting

- **Spray discipline** (2026-10-07): replay truth can test it; the player left it open. Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands. Evidence: duel value with an interval.
- **Utility response** (2026-10-07): vrfkit leaves `CausingActor` in raw bits. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: each utility's causer named and checked against casts on two replays.
- **"?" fade conflict** (2026-10-07): the widget's 3.0 s lifetime [domain:minimap/last-known-mark-widget-lifetime] against the measured fade [domain:minimap/last-known-mark-timing]. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist`. Evidence: the timer's start named, or both starts refuted.
- **9acf02f98283's persistence tail** (2026-10-07), possibly reveals. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist 9acf02f98283`. Evidence: each long swap classed by eye with its cause.
- **Smoke geometry** (2026-10-07): sphere centres, Viper's toggle, Cypher's capsule [domain:abilities/minimap-vision-cone-blockers]. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py smokes`. Evidence: each shape from its game file or fact, checked on frames.
- **Unmodelled walls** (2026-10-07): Blaze, Toxic Screen, Cosmic Divide, Sage, Iso, Neon, Harbor, Vyse. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py lane`. Evidence: misses and extras against T1d before and after.
- **Ally-icon cost** (2026-10-06, was item 2): the 94 against 61 ms gap, parallel readers, `one-pass-ingest-20261005`. Acceptance and evidence in the [10-07 archive](docs/archive/BACKLOG-through-2026-10-07.md).
- **Spelling owner's remainder** (2026-10-06, was item 3): prototype spellings, c817691bcd15 rereads, the rounds K/D rule. Acceptance: `.\.venv\Scripts\python.exe -m reticle plan c817691bcd15` naming nothing. Evidence: as in the 10-07 archive.
- **Ingest wiring** (2026-10-06): `plan` omits never-run steps; thread caps leak; readers and caches need one 15 Hz grid. Acceptance: `.\.venv\Scripts\python.exe -m reticle frame-join c817691bcd15`. Evidence: join rate 1.0 exact; CPU near wall time.
- **Self-entry follow-ups** (2026-10-06): rounds and combat report count K/D from "Me"; account-name captures name the player Deadlock. Acceptance: `.\.venv\Scripts\python.exe -m reticle self-entries cea8ecbc94ab`. Evidence: rounds K/D equal to self-entry.
- **Replay-layer defects** (2026-10-06): `lives` keeps departed players alive; the walk graph drops cells along barriers and doors and lacks jump and drop edges; `cast` row order varies by build. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: departed players dead; two builds byte-identical.
- **Killfeed residuals** (2026-10-05): the cases in the 10-07 archive, and in-round stall gaps by the [roster difference](docs/STALL_ROSTER_DIFFERENCE.md). Acceptance: `.\.venv\Scripts\python.exe -m reticle dev-sample` plus `trial` on those windows. Evidence: each fixed or refused with its stored reason.
- **Tray grid** (2026-10-05): three prototypes read off the 0.5 s grid. Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_tray_grid_cache.py`. Evidence: no `ThinnedOut`.
- **Glyph follow-ups**, **Clove**, **origin-fact wording**, **player questions**, **pickup returns**, **game assets**, **restated round windows**, **0f08b3dc3777 naming** (2026-10-04 to 10-05). Acceptance and evidence per item in the 10-07 archive.
- **Carried** (dated in the archives): audio-fit residuals; ability identification; icon descriptors; reader resampling; death binding at sighting gaps; duplicate Chamber death at bfad2778a372; scene model; economy ledger; minimap identity; the statistical adjudicator; the geometry stamp's raw-byte hash. Acceptance: each item's own command in the [10-05 archive](docs/archive/BACKLOG-through-2026-10-05.md). Evidence: as there.

## Completed

- **`execution-questions-20261007` (2026-10-07):** [EXECUTION_QUESTIONS.md](docs/EXECUTION_QUESTIONS.md); placement, first-shot hit and counter-strafe carry duel value; shooting first does not.
- **`t1-draw-rule-20261007` (2026-10-07):** T1d (measured persistence, both teams' smokes, no dead enemies) in `prototypes/t1_draw_rule.py`.
- **`enemy-lane-check-20261007` (2026-10-07):** most T1-drawn misses are T1 errors; `prototypes/enemy_lane_check.py`.
- **`real-reader-schedule-20261007` (2026-10-07):** `Vgate` passes QA5r3 post hoc; reach questions; `prototypes/real_reader_schedule.py`.
- **`fidelity-principle-20261006` (2026-10-06):** the AGENTS.md rule; two precedents archived.

Earlier entries: [10-07 archive](docs/archive/BACKLOG-through-2026-10-07.md).
