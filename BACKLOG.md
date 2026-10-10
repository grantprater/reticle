# Reticle task queue

Each open item carries an `Acceptance:` command and an `Evidence:` standard. Earlier full texts are in the [10-09 late](docs/archive/BACKLOG-through-2026-10-09-late.md), [10-09](docs/archive/BACKLOG-through-2026-10-09.md), [10-07](docs/archive/BACKLOG-through-2026-10-07.md) and [10-05](docs/archive/BACKLOG-through-2026-10-05.md) archives. Capture paths for every session named here are in [NOTES](NOTES.md).

## Agreed order (2026-10-05, revised 2026-10-09 close)

Standing rules: replays may fit reader parameters offline with scoring matches held out ([policy](docs/EXTERNAL_GROUND_TRUTH.md)); no full corpus rerun runs until training on the replay data is finished; fidelity follows the question (AGENTS.md), judged by QA5r3 against replay truth ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7), with T1d as the draw rule. Split (`reticle/dev_set.py`): development cadaadeb2d8b, 066741deafe5, 9912c382130b (pool `new3`, every harness subcommand's default); held-out none until the next capture with a replay, then scored once per version, never by a candidate that already failed. Frozen at their stored versions and reported only as stale history: 9acf02f98283, c817691bcd15, d3dcfb182ab1 (pool `dev3`) and cea8ecbc94ab (bd7efa02); none is reread. Rereads run only on the three development sessions; ask before each. Every scorer runs as `.\.venv\Scripts\python.exe -m reticle acceptance <sub>`.

**1. Convert every reader to opportunity gating and the slot model; raise ability accuracy.** The ratchets (CONVERT, ROUNDSCOPE, strict PROMOTE, ABILITY) and the per-frame gate hook are merged; the ally pass reads through ally gate 0.3.0, off by default. One ability builder covers every slot, and the lane is scored per side and class ([ABILITY_ENTITIES.md](docs/ABILITY_ENTITIES.md) steps 0 to 3, step 4 in part).
- Refresh the development sessions first: rebuild each crop cache from video, one decode at a time, then rescan the glyph reader; the disabled-state change left their glyph streams stale. `reticle plan <sid>` names the commands; ask before each decode.
- Ability accuracy: team false opens and enemy and witnessed-object recall. Class every false loss by cause before tuning: covers, missed dimmed drawings, the in-view estimator. Dimmed drawings: the game files dim only the Sonic Sensor [domain:game_data/stealthing-trap-disabled-minimap-opacity]; search for a shared parent-class value covering Chamber's, Cypher's and Killjoy's devices. `prototypes/device_deactivation.py`, mined from captures, stays unwired.
- Plan steps 5 to 7: kits for every slot; the ability readers' gates (step 6); close with `ABILITY_LEGACY` empty. The mechanics sheet's answers feed the lifecycles.
- Score the gated ally pass once on the next held-out capture; the player decides the default switch.
- Convert reader by reader, the ability readers next, then the rest of `CONVERT_LEGACY`; each conversion shrinks the list.
- ROUNDSCOPE: fix the 31 audited sites; review the 92 unreviewed detector sites.
Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor` (CONVERT, ROUNDSCOPE, PROMOTE, ABILITY, KINDS), then `.\.venv\Scripts\python.exe -m reticle acceptance ability-lane --side all --tag TAG` and `.\.venv\Scripts\python.exe -m reticle acceptance false-loss --tag TAG` on the development set, and `.\.venv\Scripts\python.exe -m reticle acceptance hook-report --record` on each gated arm.
Evidence: per side and class, outcomes summing to the finds, recall and false opens with round intervals; witnessed-object end-cause agreement; false losses by cause; read share and CPU per session beside the 15 Hz arm; per question, the loss with its interval under QA5r3 on the development set, then once on the held-out match; each ratchet list shorter, never longer.

**2. Enemy lane residuals.** The real enemy lane rarely places the killer, so join questions collapse on real reads.
- Residuals after the portrait gate, each to its owner or a named per-ability cue: finds on nothing (most in 066741deafe5), X marks read as enemies, wrongly named finds. Confirm `PING_OWN_PX` on the production ping stream. Soft rim coverage stays opt-in until a second 331 px replay match.
- Then the reachable-set belief (`prototypes/coaching_belief.py`) as the enemy lane's carried state, so the killer holds a region at each death.
Acceptance: `.\.venv\Scripts\python.exe -m reticle acceptance lane --tag pgb2` on the development set, then `.\.venv\Scripts\python.exe -m reticle acceptance summary --tag pgb2` and `.\.venv\Scripts\python.exe -m reticle acceptance budget`.
Evidence: the `pgb2` arm reproduces; per class, outcomes summing to the finds with round-bootstrap intervals; `nothing_there` and the X-mark share fall; `join_death` accuracy on V15h against T1.

**3. Slot model** (QUESTION_ACCEPTANCE B1-B3). `reticle/slot_state.py` owns `position-belief` for both sides, with the spawn anchor on at slot-state 0.4.0.
- Walk reach: the gate and the belief use a Euclidean disc. Walk reach needs a walk graph baked into the geometry; run `reticle plan` for the streams it stales and ask the player before the bake. The walk-component bridge (`map_regions.BRIDGE_GRID_STEPS`) is a placeholder; check the spawn areas on Abyss and Summit.
- Reconcile the `resolve` and `beliefs` rules into one.
- B2-B3: missed reads modelled as runs; beliefs carry reach and region, not metres; a region builder cuts regions at chokepoints on the walk graph and splits height platforms.
Acceptance: `.\.venv\Scripts\python.exe -m reticle acceptance slots --record` on the development set.
Evidence: calibration and unanchored share per side and match beside slot-state 0.4.0's; each logged prediction marked pass or fail; per question, accuracy against T1d beside the 15 Hz arm with its interval and read cost; the region builder's crossing rate, misdating, question loss and border width beside the callout regions'.

## Waiting

- **Utility response**: vrfkit leaves `CausingActor` in raw bits. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: each utility's causer named and checked against casts on two replays.
- **"?" fade conflict**: the widget's 3.0 s lifetime [domain:minimap/last-known-mark-widget-lifetime] against the measured fade [domain:minimap/last-known-mark-timing]. Acceptance: `.\.venv\Scripts\python.exe -m reticle acceptance draw-persist`. Evidence: the timer's start named, or both starts refuted.
- **Smoke geometry** [domain:abilities/minimap-vision-cone-blockers] and **unmodelled walls** (Blaze, Toxic Screen, Cosmic Divide, Sage, Iso, Neon, Harbor, Vyse). Acceptance: `.\.venv\Scripts\python.exe -m reticle acceptance draw-smokes` and `.\.venv\Scripts\python.exe -m reticle acceptance lane --tag pgb2`. Evidence: each shape from its game file or fact; misses and extras against T1d before and after.
- **Self-entry defect**: account-name captures name the player Deadlock; d3dcfb182ab1's K/D disagrees with its replay. Acceptance: `.\.venv\Scripts\python.exe -m reticle self-entries SESSION` per development session. Evidence: K/D equal to the replay's on every development session.
- **Ingest wiring**: older `combat_report_rows` lack the coverage row `plan` reads; thread caps leak; readers and caches need one 15 Hz grid. Acceptance: `.\.venv\Scripts\python.exe -m reticle plan cadaadeb2d8b` and `frame-join cadaadeb2d8b`. Evidence: plan names only real gaps; join rate 1.0 exact.
- **Replay-layer defects**: `lives` keeps departed players alive; the walk graph drops cells along barriers and doors and lacks jump and drop edges; `cast` row order varies by build. Acceptance: `.\.venv\Scripts\python.exe -m reticle replay-layer --all`. Evidence: departed players dead; two builds byte-identical.
- **Carried** (dated in the archives): execution readers and spray discipline (their scorer, `execution_questions`, is declined in the ledger); ally-icon cost; the spelling owner's remainder; killfeed residuals, with in-round stall gaps by the [roster difference](docs/STALL_ROSTER_DIFFERENCE.md); tray grid; glyph follow-ups; Clove; origin-fact wording; player questions; pickup returns; game assets; restated round windows; 0f08b3dc3777 naming; audio-fit residuals; icon descriptors; reader resampling; death binding at sighting gaps; duplicate Chamber death at bfad2778a372; scene model; economy ledger; the statistical adjudicator; the geometry stamp's raw-byte hash. Acceptance: each item's own command in the [10-09 late](docs/archive/BACKLOG-through-2026-10-09-late.md), [10-09](docs/archive/BACKLOG-through-2026-10-09.md) or [10-05](docs/archive/BACKLOG-through-2026-10-05.md) archive, run on the development set. Evidence: as there.

## Completed

- **`disabled-state-20261009` (2026-10-09):** owner death disables deployed utility that never expires; the node stays open and draws dimmer.
- **`replay-actor-end-20261009` (2026-10-09):** replay layer 0.3.1 records the disable as a state and takes true ends from kill, destroy and mid-round close markers.
- **`drawing-loss-in-view-20261009` (2026-10-09):** a lost drawing ends an object only in view, by the `team_vision` in-view estimate.
- **`dev-set-new3-20261009` (2026-10-09):** the 2026-10-07 sessions become the development set; the old ones are frozen.
- **`ability-tree-step3-20261009` (2026-10-09):** one ability builder for every slot; spawned objects as tree nodes.

Earlier entries: [10-09 late archive](docs/archive/BACKLOG-through-2026-10-09-late.md).
