# Reticle: review and execution plan

Date: 2026-09-07. Status: first implementation milestone completed and validated;
detector and coaching expansion milestones remain open.

## Product direction

Deliver a traceable coaching loop: observation -> event -> contextual estimate
-> supporting and contradicting footage -> player/coach review -> correction.
The first useful release should retrieve reviewable moments and expose data
quality. It should not wait for a perfect minimap, or prescribe changes from
an unvalidated probability model. Mindset is a player annotation, not a label
that pixels or a loss streak establish.

## Findings from the repository

- Strong foundations: separated raw pointers and derived tables, shared decode
  passes, detector versioning, independent scoreboard checks, and visual overlays.
- The implementation is concentrated in stage 02. Player kill/death tracking
  and round outcomes already exist, but there is no unified player-event table
  connecting them to a evaluated state model and retrievable video windows.
- `doctor` currently fails: 35/36 geometry caches are stale. One lacks shade;
  one manifest has contradictory widget-size metadata. Rebuilding geometry
  discards shade arrays. Do not consume these tracks for coaching yet.
- The roster's undrawn `(0,0)` defect is documented and still present. HUD
  changes in a spectated view cannot be attributed to the local player.
- `rounds._plant` infers planting from future missing-clock runs. This cannot
  be a prediction-time phase feature. Score increments also locate round ends
  late, and round 1 may include menus or a partial capture.
- `Store.write_rounds` drops plant timing and inference provenance and lacks a
  round-definition version. That breaks downstream reconstruction/comparability.
- Existing statistical prose overstates independence: ten states of one round
  still share one outcome. WPA describes a model's state change, not the causal
  effect of a decision; economy, opponent strength and team actions confound it.
- Documentation disagrees with code (overlay coverage, roster wiring, capture
  settings). Replace obsolete claims at the point of use rather than add another
  competing handoff. No broad rewrite or deletion of prototypes is necessary.

## Execute now: bounded first milestone

1. Save this plan; record baseline diagnostics and preserve existing work.
2. Add a versioned, stored-data-only coaching analysis command. Persist player
   kill/death observations, source provenance, round association, review windows,
   explicit quality flags, and round-state observations. Do not label ammo drops
   as local shooting without a reliable POV gate.
3. Add a small regularized probability baseline using only contemporaneously
   observed alive counts and clock. Exclude unknown/undrawn, terminal and stale
   observations. Do not derive attack/defence from left/right UI placement.
   Evaluate by held-out session, weight rounds equally, compare against a
   training-only base rate, and report calibration plus session-cluster uncertainty.
   Keep model outputs exploratory; lack of data is a reportable result.
4. Join event before/after states with bounded time windows, using the same
   held-out model on both sides. Null the delta when either state is missing.
   Supply clip pointers, not claims that a model delta measures personal credit.
5. Fix round persistence/versioning and ambiguous session-prefix resolution.
6. Test leakage, stale-input refusal, nulls, gaps, terminal states, repeated
   observations, storage round trips and CLI execution. Run on the existing
   corpus without decoding or modifying L1, then inspect results and revise.
7. Save measured results and remaining limitations here, update NOTES, and
   commit verified changes. No publication or media upload.

## Subsequent milestones and acceptance gates

### Detection correctness before richer model features

- Rebuild geometry with dependent shade restoration as one operation; validate
  independent X-mark labels before rereading the minimap corpus in shared passes.
  Resolve the contradictory profile by inspecting its source frame first.
- Continue the BASE/ANNOTATIONS/light decomposition already specified in NOTES.
  Validate bearings and identity on unseen sessions and continuous overlays,
  including occlusion, M-key, deaths, teleports and crowded icons. Count agreement
  alone cannot validate identity or cones. No threshold tuning on evaluation data.
- Build a drawn/undrawn roster gate and explicit POV/life-interval reader. Preserve
  real zero counts and revives. Compare at least two capture regimes, with known
  menus and genuine team wipes, before changing the extractor stamp.
- Read the persistent planted icon, attack/defence and economy; reconcile round
  starts/ends using clock, score and scoreboard. Store observations separately
  from adjudicated events and record disagreements rather than overwrite evidence.

### Event coverage and coaching

- After POV is trustworthy, propose shot/damage/contact episodes including
  no-kill and no-contact opportunities. Ability equip is not cast; persist both
  and unknown identity. Every event needs source intervals and a correction key.
- Clip refinement decodes merged contiguous windows only. Produce examples,
  counterexamples and ordinary controls, with diverse rounds, not only high-|WPA|
  moments. Measure review usefulness with the player/coach.
- Add correction history and rebuild only dependent artifacts. Keep explicit
  observation, inference and coaching hypothesis fields.

### Statistical progression

- Freeze feature definitions and evaluate on later complete sessions using
  actual capture chronology (not ingest time). Group repeated captures of one
  match together. Leave-session-out is an initial diagnostic, not a prospective
  performance claim. Never split frames of a round across train and test.
- Add economy, phase, side, map and agent only after coverage/quality audits;
  use shrinkage/partial pooling rather than a cross-product of thin cells.
- Compare Brier/log loss and reliability bins to simple baselines; retain counts
  of matches and rounds, cluster uncertainty by match/session, and abstain on
  unsupported contexts. Tune only inside training folds.
- Estimate longitudinal change under fixed definitions; account for patch,
  rank, role, opponent and missingness changes. Treat discovered patterns as
  hypotheses for deliberate practice, then test on future sessions.

## Efficiency and scope

Reuse stored L1 for all inference work here; no new dependencies or full video
passes. Prefer a few reliable event classes over broad uncalibrated detections.
Measure decode time separately from detector time before optimizing. Keep batch
VOD analysis as the delivery target; streaming can wait for a proven coaching loop.

## Method references

Grouped and temporal validation rationale:
https://scikit-learn.org/stable/modules/cross_validation.html

Probability assessment (Brier measures more than calibration; inspect reliability
bins as well): https://scikit-learn.org/stable/modules/calibration.html

These references guide validation; implementation uses existing NumPy only.

## Execution results

Implemented `reticle coach`, a stored-data-only pipeline producing events,
eligible states, held-out predictions, a quality/provenance report and linked
review windows. Source and code SHA-256 hashes make each run reproducible;
single-session output uses a separate directory. Current source data is retained.

Full-corpus execution, repeated with byte-identical output bundles:

| Measurement | Result |
|---|---:|
| Manifests inspected | 50 |
| Sessions with current HUD | 18 |
| Derived round intervals | 369 |
| Player killfeed observations | 543 (271 kills, 272 deaths) |
| Events flagged near uncertain round boundaries | 111 |
| Events without a resolved round | 7 |
| Sessions with current roster | 1 |
| Eligible state observations / rounds | 107 / 7 |
| Probability evaluation | insufficient data; all event probabilities null |

The remaining 32 manifests have no HUD table; they are reported, not silently
treated as zero-event matches. No new decoding was necessary. The stored bundle
is at `~/reticle-store/analysis/coaching/`. Reproduce with
`.\.venv\Scripts\python.exe -m reticle coach`.

Fixed two independent correctness defects: ambiguous session prefixes previously
selected the first match; they now refuse and list the matches. Round persistence
now retains plant timing, side-check fields and map, and records its own definition
version plus the actual source HUD version/content key (never stamps old source
data as current). Existing round files can be rebuilt with `reticle rounds`.

Validation: 11 unittest checks pass, covering held-out-label independence,
repeated-state weighting, insufficient-data abstention, as-of joins, missing and
terminal reads, frozen/buy clocks, timestamp ordering, killfeed deduplication,
clip bounds, cross-round/gap refusal, storage provenance, prefix ambiguity,
stale/mismatched input refusal and deterministic bundle regeneration.
`git diff --check` passes. `doctor` remains at the baseline five findings and
one error: stale geometry. No new structural findings.

### Self-critique and next decision

This is an event/review foundation, not a validated coaching model. The executable
model has meaningful synthetic behavioral tests but no multi-session real-data
performance result. Its phase gate is a deliberately conservative heuristic, not
ground truth. Seven eligible rounds from one match cannot establish calibration,
and adding a sophisticated model would not change that.

The large count of boundary-flagged events makes round timing a concrete priority.
Before expanding the corpus, validate roster presence/absence and round/POV gates
on at least two sessions; then populate roster through the existing shared pass.
Do not launch a broad re-scan merely to satisfy the model's minimum sample count.
After gates are validated, collect complete independent sessions and run the
unchanged baseline. The session-bootstrap interval, when available, describes
held-out losses and omits uncertainty from overlapping training sets; it is not
a confidence interval for a causal effect or a production-readiness certificate.

Review windows are coarse source pointers, not refined exported clips. They are
selected one per round chronologically for initial inspection, not representative
samples of all opportunities. No-kill engagement coverage, ability integration,
correction workflows, minimap repair and actual coaching conclusions remain the
subsequent milestones above. No thresholds were tuned against this corpus and no
new claims about detector accuracy were made.
