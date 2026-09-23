# Streamlining LLM development

Date: 2026-09-23. Status: implemented; archived after the fixed-round source review. The next three bounded tasks should be evaluated through the standing working-map guidance.

Implementation record: the active route was reduced by about 84% in word count
for the selected death task; `NOTES.md` has one short handoff and `BACKLOG.md`
one active contract. Deliberate structural violations are caught by tests, and
`doctor` returned its baseline 11 findings and zero errors. The fixed-round
pilot passed its repeatable command and review: seven visible deaths, zero
misses or extras in that reviewed set, one source-verified name, six identity
refusals and seven location refusals. The next task follows the first observed
failure: missing stored killfeed portrait observations. See the local
`teststore/death-round4-v3/review-summary.md` for the bounded comparison.

## Outcome and boundaries

Make a fresh development session able to identify one current task, find its
required evidence, and finish a reviewable pipeline increment without rebuilding
the project's history. Success requires both less mandatory context and an
integrated result. Shorter documentation alone is insufficient.

This is a temporary implementation plan, not another standing authority. On
completion, archive it and remove its startup links. Implement the guidance in
existing files and tools. Do not add a workflow engine, agent orchestrator,
documentation registry, new telemetry service, or another task schema.

This plan does not authorize a pipeline rewrite, detector retuning, media copying,
cache cleanup, or changes to the deterministic observation boundary. Preserve
provenance, explicit unknowns, independent evidence, and baked map geometry.

## Evidence and limits

Read-only inspection found:

- `NOTES.md`: 3,700 lines, about 34,000 words, with multiple current-looking
  handoffs alongside superseded entries.
- `BACKLOG.md`: 2,196 lines, about 20,000 words, mixing queued work, completed
  work, and historical arguments.
- `docs/WORKING_MAP.md`: startup routing through several plans and guides.
- `docs/ARCHITECTURE_PLAN.md`: short handoffs and bounded work packets already
  prescribed. `docs/tasks.json` and `tools/task_check.py` already implement
  contracts, command execution, and append-only check logs.
- A search of `reticle/` found `adjudicate_round_deaths` defined without a
  production caller; tests call it. Verify the actual command path before
  concluding that integration is absent.
- `doctor`: 11 findings, zero errors. `status` failed to launch its interpreter
  with access denied. Runtime health and perceptual accuracy are not established
  by this inspection. Recheck the environment before implementation baselines.

Existing task-runner limits matter: `evidence` contains prose requirements, not
verified artifacts; `passed` means commands exited successfully. Read fragments
are not validated as section anchors. Elapsed time measures checks, not agent
labor. Do not report any of these as stronger evidence than they are.

## Standing guidelines and how to verify them

| Guideline | Existing home | Verification |
|---|---|---|
| One current objective and next action | `NOTES.md` | Exactly one `Picking up` section; at most 100 lines and 1,000 words in the file; named task, baseline, first unresolved failure, next action, and evidence pointers |
| At most three ordered active tasks | `BACKLOG.md` | Each active entry has an ID, output, dependency if any, and completion condition; deferred items have a concrete reactivation trigger |
| One definition of each executable task | `docs/tasks.json` | Active IDs resolve to contracts; existing runner validates files and command arrays; handoff and backlog refer to IDs rather than copying contracts |
| Load context by task | `docs/WORKING_MAP.md`, contract `reads` | Startup requires only root instructions, routing, current handoff, and selected task; required subsystem rules remain reachable; no unconditional reading of historical plans |
| Completion requires the intended output | Contract `acceptance` and `evidence` | Real command runs on fixed input, comparison is recorded, and output is inspected; unit-test success alone cannot close an integration or perceptual task |
| Scope follows the observed failure | Current handoff and task | Any expansion names the failing acceptance condition and the evidence requiring it; unrelated findings go to deferred work |
| Historical findings cannot direct current work | Existing guides and archive | Current routes identify history explicitly; moved sections retain discoverable references; obsolete imperatives are absent from active guidance |

The size limits are review tripwires. They must not cause omission of a critical
safety or evidence rule. Move detailed material to its owning reference and link
it. If a limit proves impractical, revise it explicitly after the pilot rather
than silently allowing growth.

## Implementation sequence

### 1. Establish the baseline and reconcile authority

Files: `AGENTS.md`, `CLAUDE.md`, `docs/WORKING_MAP.md`, `NOTES.md`,
`BACKLOG.md`, and the plans they currently route through.

1. Preserve the existing untracked `prototypes/mechanics_eval.py` and other user
   work. Record the starting commit and working-tree state.
2. Run the repository venv's `doctor` and `status`. Record failures as environment
   limitations, not detector failures; resolve interpreter access before claiming
   an executable baseline. Do not substitute a different Python environment.
3. Assign authority: roots hold global constraints; working map routes; notes
   hold current execution state; backlog orders work; contracts specify checks;
   subsystem references hold technical facts. Plans retain design rationale and
   acceptance boundaries without competing as live task queues.
4. Reconcile the root files' differing north-star and workflow wording using the
   user's current direction. Both must preserve identity-bearing observations
   and the visually checkable annotated match. Keep the roots consistent without
   a generator or new synchronization tool.

Acceptance: a file-by-file diff preserves the global constraints and makes each
authority explicit. No detector, store, or runtime behavior changes in this step.

### 2. Reduce active context by moving history

1. Move historical handoffs and superseded backlog arguments into dated files
   under `docs/archive/`. Preserve technical evidence and its provenance; keep
   private attribution outside the public repository. Do not copy sensitive
   material into a new public archive.
2. Replace `NOTES.md` with one current handoff meeting the limits above. Reconcile
   its statements against code and current evidence, not just the newest heading.
3. Rebuild `BACKLOG.md` as a short ordered queue plus deferred one-line entries
   with triggers and links. Archive closed discussions. Target at most 200 lines
   and 2,000 words; do not duplicate the contracts' acceptance commands.
4. Update the working map's startup route. Keep design documents available on
   demand. For prototype work, make `prototypes/CLAUDE.md` a concise rule/router
   document by moving historical experiments to referenced subsystem material.
   Preserve all applicable domain constraints and the private-notes route.
5. Repair references to moved sections. Leave a short redirect where an old
   anchor is externally useful. Do not retain whole obsolete sections for links.

Acceptance: one current handoff, no more than three active tasks, and the stated
size limits. Review moved content against the original to catch lost facts.
Check changed links and paths. Measure startup plus selected-task required text
before and after for the same task; target at least a 70% word reduction. This is
a text-volume measure, not a token or productivity claim. Review mandatory
subsystem guidance separately so the reduction cannot hide required rules.

### 3. Use existing contracts to govern one bounded increment

1. Keep the existing schema and runner. Retain useful maintenance contracts; an
   available contract is not automatically an active backlog item.
2. Add one pilot contract with a concrete objective, owning files, selective
   `reads`, exact command arrays, and evidence requirements. Put frozen input
   identifiers, expected output, baseline comparison, and stop conditions in
   existing fields. Do not introduce placeholder commands that can pass.
3. Choose exact commands after tracing the existing entry point. If no usable
   command exists, implementing the smallest integration path is part of the
   task and must have a real command before closure.
4. Use the existing development log for command results. Store visual evidence
   and brief review notes with the existing store artifacts and reference them
   from the handoff. Keep human review distinct from the runner's `passed` flag.

Acceptance: the runner prints and validates the selected contract; its commands
produce the declared output. A reviewer can follow the evidence to the source
window. An unrelated full test suite cannot stand in for the task's outcome.

### 4. Add only cheap checks for recurring structural failures

Extend existing `doctor`/task-contract checks only where the predicate is exact:
handoff heading count and size, active queue count and resolvable IDs, and missing
contract paths. Use a small documented heading/ID convention in the existing
Markdown, not a second structured task registry. Initially report warnings so
the migration can be reviewed before any blocking policy is introduced.

Test each implemented predicate with a passing and failing fixture. Do not add
automated claims about semantic freshness, perceptual correctness, link meaning,
or whether arbitrary code is genuinely integrated. Those require the task's
real run and review. If implementing a check requires a general Markdown parser
or broad new machinery, keep that check manual for the pilot.

Acceptance: deliberately duplicated handoffs, oversized active notes, and invalid
active IDs are reported; compliant fixtures pass. Existing diagnostic behavior
does not regress. Structural warnings never imply product correctness.

### 5. Pilot on the death-event path

Proposed task: one frozen round produces reviewable death events with identity,
location or an explicit reason for refusal, and source evidence.

Before editing, trace the production call path and inspect candidate source
windows. Select the round and observation versions before measuring changes;
retain ambiguous cases. Log falsifiable perceptual predictions in the existing
store prediction log if the task includes a perceptual experiment.

Acceptance must include:

- One repeatable command produces the event output and its review view using
  existing tools wherever possible.
- The frozen window's independently reviewed deaths are accounted for as
  resolved, unresolved, or missed; extra detections are counted too. Report
  identity/location coverage as well as errors. All-null output does not qualify
  as successful integration: require at least one source-verified named death.
- Events preserve observation times, inferred timing where applicable, versions,
  refusal reasons, and source pointers. Inspect stack shifts and identity binding
  where present; do not assert coverage of cases absent from the chosen round.
- A before/after comparison and visual review support the claimed improvement.
  No unsupported accuracy claim is generalized from one round.

Stop at the first upstream failure that prevents this output. Record its actual
reason and source evidence. Address the smallest necessary dependency; when
perception cannot be derived, use the required player-question/labeling procedure.
Do not broaden the pilot into a general identity solver or coaching redesign.

## Review, rollout, and removal

Commit independently verified steps separately: context migration, contract and
small checks, then pilot integration. Use `git diff --check`, changed-reference
review, focused tests for implemented checks, and the actual pilot command as
appropriate. Documentation moves do not require a full detector test run.

Evaluate the next three comparable bounded tasks using existing evidence:
accepted or blocked outcome, required context volume, recorded corrections, and
whether a real output was reviewed. Record orientation time only if measured;
historical agent time and missing correction counts remain unknown. Three tasks
can establish usability, not a statistically reliable productivity gain.

The rollout is complete when a fresh session can identify the active task and
its check without historical reconstruction, structural checks catch deliberate
violations, the pilot output is reviewed, and active context meets the reduction
target. If these fail, repair routing or task scope before adding rules.

After the pilot, remove unused requirements/checks and archive this plan. Keep
only the short standing guidelines in their existing homes. Archive old plans'
execution narratives where they still compete with current direction, preserving
design references. The final result should require fewer documents to start work
and leave no new permanent planning layer.
