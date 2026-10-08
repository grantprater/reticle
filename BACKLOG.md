# Reticle task queue

Each open item carries an `Acceptance:` command and an `Evidence:` standard. Earlier full texts are in the [10-07](docs/archive/BACKLOG-through-2026-10-07.md), [10-06](docs/archive/BACKLOG-through-2026-10-06.md), [10-05](docs/archive/BACKLOG-through-2026-10-05.md) and [10-04](docs/archive/BACKLOG-through-2026-10-04.md) archives. Capture paths for every session named here are in [NOTES](NOTES.md).

## Agreed order (2026-10-05, revised 2026-10-07 night)

Standing rules: replays may fit reader parameters offline with scoring matches held out ([policy](docs/EXTERNAL_GROUND_TRUTH.md)); no full corpus rerun runs until training on the replay data is finished; fidelity follows the question (AGENTS.md), judged by QA5r3 against replay truth ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7), with T1d as the draw rule. Split: development 9acf02f98283, c817691bcd15, d3dcfb182ab1; held-out cea8ecbc94ab (bd7efa02), scored once per version, never by a candidate that already failed.

**1. Wire the read reductions** (player, 2026-10-07). Production reads every drawn frame: ally icons, self, team vision and enemy objects at 15 Hz, pings at 10 Hz, ability icons and glyphs at 2 Hz with no gate. Only Clove's circle reads in opportunity windows; no audio or cast gate reaches a video reader; the pass has no per-frame skip hook (`reticle/passes.py`). `Vgate` read [metric:real_reader_schedule/qa5r3/Vgate@dev2#share=0.0283] of the 15 Hz reads and passed QA5r3 post hoc, on slot reads only, never the abilities; nothing in `reticle/` imports it.
- Close the PROMOTE loophole (the player approved, 2026-10-07): a passed pilot whose change is meant for production may not carry `"wire": "no"`; it is wired, or names the backlog item that wires it, and doctor errors when that item is missing or closes unwired. `reticle status` lists passed-but-unwired pilots at pickup. Audit every existing `"wire": "no"` row.
- Add a per-frame gate hook to `passes.run` and `passes.run_cached`; put the ally pass under the real-reader schedule and the ability readers under their opportunity and audio gates; confirm once on the held-out cea8ecbc94ab.
- First, cheap and byte-identical: count stack candidates per frame instead of scanning every candidate (`reticle/minimap.py:1658`, quadratic in session length).
- Rereads run only on the three 2026-10-07 sessions and one earlier replay session, never an archived one.
Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor` with the strict PROMOTE, then `.\.venv\Scripts\python.exe prototypes\question_acceptance.py lane --tag TAG` on a gated arm.
Evidence: read share and CPU per session beside the 15 Hz arm; per question, slot and ability, the loss with its interval under QA5r3 on the development matches, then once on the held-out match.

**2. Enemy lane, reader and belief.** The real enemy lane rarely places the killer, so join questions collapse on real reads (NOTES).
- The one transform's remainder (merged `a015c85`): wire the X-mark input, `floor_mask`, `site_mask` and the occluder bake, and say whether `minimap_dark` rereads from the cache.
- `minimap_objects` residuals after the portrait gate (`a0824c8`): X marks read as enemies, wrongly named finds, low recall; the error budget and the labeller are merged (`78a1f5b`), their labels from the pre-gate `b1` reader. Each residual goes to its owner or a named per-ability cue; confirm `PING_OWN_PX` on the production ping stream. Soft rim coverage stays opt-in until a second 331 px replay match.
- **Class-aware harness**, step 9 (steps 1 to 8 merged, `85608af`): fold `replay_truth score` and `replay_abilities score` onto the layer; move `prototypes/enemy_error_budget.py` in as subcommands whose extras start from `truth_under`; rebuild the stale inputs steps 5 to 8 scored (`ally_icon`, the ability scan, `minimap_dark`) after asking the player. Acceptance: `.\.venv\Scripts\python.exe prototypes\question_acceptance.py lane --tag pgb` on the three development matches, plus each step's subcommand. Evidence: the 0.3.0 control reproduces; per class, outcomes with round-bootstrap intervals; each stale input named or rebuilt.
- Then the reachable-set belief (`prototypes/coaching_belief.py`) as the enemy lane's carried state, so the killer holds a region at each death.
Acceptance: `.\.venv\Scripts\python.exe prototypes\enemy_lane_check.py sets SESSION` rerun against T1d, plus `.\.venv\Scripts\python.exe prototypes\real_reader_schedule.py reach` on the development matches.
Evidence: per match, the reader's share of misses and its extras against T1d; `join_death` accuracy on V15h against T1.

**3. Slot model** (QUESTION_ACCEPTANCE B1-B3, revised 2026-10-07). B1 is ENTITY_STATE step 1, `slot_state` from stored rows; then B2-B3, the timeline shape change and the harness; then the gated readers and the gate's cue, priced.
- Missed reads come in runs; model them so.
- Beliefs carry reach and region, not metres.
- The gate uses walk reach, not a 20 m radius.
- A region builder cuts regions at chokepoints on the walk graph and splits height platforms (player, 2026-10-07), tested as the callout regions were: crossing rate, interpolation misdating, question loss, border width.
- The held-out match is scored once per version.
Acceptance: `.\.venv\Scripts\python.exe prototypes\replay_truth.py score SESSION --record` per development match, then the QUESTION_ACCEPTANCE harness once the vision timeline exists.
Evidence: each logged prediction marked pass or fail; worst cases beside located shares; per question, accuracy against T1d beside the 15 Hz real-read arm with its interval and read cost; the region builder's four tests beside the callout regions'.

## Waiting

- **Execution readers** (2026-10-07, was item 3; moved behind the read reductions): placement and angle clearing from the stored cone facing, counter-strafe and first shot from a window-gated centre-crop reader (ask before its decode), head share from the combat report. Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands, plus a reader trial on the development matches. Evidence: each measurement's error against replay truth and the duel value it keeps.
- **Spray discipline** (2026-10-07): replay truth can test it; the player left it open. Acceptance: `.\.venv\Scripts\python.exe prototypes\execution_questions.py` value commands. Evidence: duel value with an interval.
- **Utility response** (2026-10-07): vrfkit leaves `CausingActor` in raw bits. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: each utility's causer named and checked against casts on two replays.
- **"?" fade conflict** (2026-10-07): the widget's 3.0 s lifetime [domain:minimap/last-known-mark-widget-lifetime] against the measured fade [domain:minimap/last-known-mark-timing]. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist`. Evidence: the timer's start named, or both starts refuted.
- **9acf02f98283's persistence tail** (2026-10-07), possibly reveals. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py persist 9acf02f98283`. Evidence: each long swap classed by eye with its cause.
- **Smoke geometry** (2026-10-07): sphere centres, Viper's toggle, Cypher's capsule [domain:abilities/minimap-vision-cone-blockers]. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py smokes`. Evidence: each shape from its game file or fact, checked on frames.
- **Unmodelled walls** (2026-10-07): Blaze, Toxic Screen, Cosmic Divide, Sage, Iso, Neon, Harbor, Vyse. Acceptance: `.\.venv\Scripts\python.exe prototypes\t1_draw_rule.py lane`. Evidence: misses and extras against T1d before and after.
- **Ally-icon cost** (2026-10-06, was item 2): the 94 against 61 ms gap, parallel readers, `one-pass-ingest-20261005`. Acceptance and evidence in the [10-07 archive](docs/archive/BACKLOG-through-2026-10-07.md).
- **Spelling owner's remainder** (2026-10-06, was item 3): prototype spellings, c817691bcd15 rereads, the rounds K/D rule. Acceptance: `.\.venv\Scripts\python.exe -m reticle plan c817691bcd15` naming nothing. Evidence: as in the 10-07 archive.
- **Ingest wiring** (2026-10-06, revised 2026-10-07): older `combat_report_rows` lack the coverage row `plan` reads; the other identity streams may hide empty runs; thread caps leak; readers and caches need one 15 Hz grid. Acceptance: `.\.venv\Scripts\python.exe -m reticle plan cadaadeb2d8b` and `frame-join c817691bcd15`. Evidence: plan names only real gaps; join rate 1.0 exact; CPU near wall time.
- **Self-entry defect** (2026-10-07): d3dcfb182ab1 reads K/D 12/19, the replay 13/17; account-name captures name the player Deadlock. Acceptance: `.\.venv\Scripts\python.exe -m reticle self-entries d3dcfb182ab1`. Evidence: K/D equal to the replay's on every replay session.
- **Replay-layer defects** (2026-10-06): `lives` keeps departed players alive; the walk graph drops cells along barriers and doors and lacks jump and drop edges; `cast` row order varies by build. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: departed players dead; two builds byte-identical.
- **Killfeed residuals** (2026-10-05): the cases in the 10-07 archive, and in-round stall gaps by the [roster difference](docs/STALL_ROSTER_DIFFERENCE.md). Acceptance: `.\.venv\Scripts\python.exe -m reticle dev-sample` plus `trial` on those windows. Evidence: each fixed or refused with its stored reason.
- **Tray grid** (2026-10-05): three prototypes read off the 0.5 s grid. Acceptance: `.\.venv\Scripts\python.exe -m pytest tests\test_tray_grid_cache.py`. Evidence: no `ThinnedOut`.
- **Glyph follow-ups**, **Clove**, **origin-fact wording**, **player questions**, **pickup returns**, **game assets**, **restated round windows**, **0f08b3dc3777 naming** (2026-10-04 to 10-05). Acceptance and evidence per item in the 10-07 archive.
- **Carried** (dated in the archives): audio-fit residuals; ability identification; icon descriptors; reader resampling; death binding at sighting gaps; duplicate Chamber death at bfad2778a372; scene model; economy ledger; minimap identity; the statistical adjudicator; the geometry stamp's raw-byte hash. Acceptance: each item's own command in the [10-05 archive](docs/archive/BACKLOG-through-2026-10-05.md). Evidence: as there.

## Completed

- **`harness-steps-5-8-20261007` (2026-10-07):** teammates, smokes, glyphs and X and "?" marks scored against every replay entity (question_acceptance 0.7.0).
- **`plan-riot-fixes-20261007` (2026-10-07):** `plan` tells an empty run and an inapplicable stream from a never-run one; Riot economy tests assert rates.
- **`enemy-labels-20261007-rebased` (2026-10-07):** the enemy error budget and the disagreement labeller.
- **`self-entry-plan-20261007` (2026-10-07):** K/D from `adjudication.self_entry`; "Mga Yawa" no longer reads as "Me"; `plan` names never-run steps.
- **`class-aware-harness-20261007` (2026-10-07):** T0 carries every replay ability child; 126 of 167 old true false accepts lie on another real entity.

Earlier entries: [10-07 archive](docs/archive/BACKLOG-through-2026-10-07.md).
