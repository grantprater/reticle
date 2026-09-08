# Architecture and development efficiency

Owner: repository maintainers. Started 2026-09-07. This is an execution plan;
`IMPLEMENTATION_PLAN.md` remains the product plan, `BACKLOG.md` the deferred queue,
and `NOTES.md` the short live handoff. Update the status table when evidence lands.

## Objective and constraints

Reduce the context needed for a correct change, the number of places edited,
and the total cost of delegation including review/rework. Preserve observations,
detector meanings, refusal behavior, private attribution boundaries and existing
public entry points. No new runtime dependencies, broad rescans or detector tuning.
Token counts are unknown unless the runner actually exposes them; file bytes and
lines are context-size proxies, not measured token savings.

## Sequence and acceptance

| ID | Change | Status | Acceptance evidence |
|---|---|---|---|
| A1 | Short eager orientation; detailed guide loaded on demand | done | `PROJECT_GUIDE.md` holds the former 1523-line guide verbatim (no line of the old `CLAUDE.md` is absent); root file is 71 lines; all global rules retained; `WORKING_MAP.md` links resolve |
| A2 | Extract HUD reader from CLI | done | `hud_reader.py` imports no CLI; CLI keeps the alias; the fixed 14s review `ea445110508b26f12d4e` re-emits 840 native rows byte-identical to the pre-change artifact (only `producer_sha256` differs) |
| A3 | Central artifact dependency declarations | done | One declaration shared by fingerprint writers and stale-input checks; missing/extra/changed producer files refuse; doc-only edits invalidate nothing; affected-artifact queries tested (`test_artifacts.py`, `test_refinement.py`) |
| A4 | Executable task contracts | done | `tools/task_check.py` validates a contract, resolves the venv, runs argument arrays without a shell, and appends a result; three contracts in `docs/tasks.json` pass; a failing check returns nonzero (`test_task_check.py`) |
| A5 | Measure delegation cost before selecting models | partial | The runner records model, elapsed check seconds, pass/fail, corrections and tokens per attempt to the external `notes/development.jsonl`; no attempts are logged with a model yet, so no default is chosen. Fields stay null unless measured |
| A6 | Fine-grained rebuilds and narrow producer modules | deferred | Trigger: dependency registry has real invalidation examples; compare outputs and rebuild cost before replacing existing orchestration |

## A1: context as a routing problem

Keep root `CLAUDE.md` short with global constraints and task routes. Preserve the
long guide as a source of domain facts and rationale; move content without deleting
history or pretending old measurements are current. Keep its path references clear.
`WORKING_MAP.md` routes to modules and checks; it must not become another handoff.
Future task contracts should name the smallest relevant reads, not require loading
every guide. Do not reduce context by hiding the rules that prevent known failures.

## A2: reusable readers, thin command adapters

Move `_HudPass` into a reader module, keeping a CLI import alias during migration.
The reader continues using shipped OCR and killfeed functions. Preserve the setup
signature first; replacing argparse-shaped configuration is a later, separately
verified change. Next candidates are the minimap reader and refinement execution,
only after their behavior is protected. One architectural step per equivalence check.

## A3: explicit artifact boundaries

Use a small declaration registry, not a new workflow engine. Distinguish code
dependencies, source tables and explanatory context. Share declarations between
fingerprint writers and stale-input checkers. Include transitive registered parents
when asking which artifacts a changed path could affect. Report candidates; do not
automatically rewrite stores. Existing whole-file hashes remain conservative:
splitting a module later can narrow invalidation without unsafe AST heuristics.

Do not confuse artifact reproducibility hashes with metric-definition versions.
`metrics.py` already distinguishes invalidating definitions from comparison context;
retain that model. Data/asset hashes remain per-run evidence, not global constants.

## A4: small executable work packets

A checked-in task contract names an objective, owning files, required reads,
acceptance argument arrays and an evidence destination. A runner resolves the venv,
runs commands without shell interpolation, captures exit status and logs results.
It validates the contract before running it. No generic plugin system or automatic
agent spawning: the orchestrator chooses an agent and sends only that packet.
Start with reader extraction, artifact dependencies and orientation checks.

## A5: optimize total cost, not model size

Use `gpt-5.6-luna` for isolated mechanical edits and small tests; escalate tasks
that repeatedly miss behavioral requirements. Record actual attempts and corrections,
including failed attempts. Do not invent token counts, dollar costs or retroactive
timings. Keep operational logs in the external store, not public source control.
Compare acceptance-on-first-attempt and review effort before choosing a default.

## A6: later architecture experiments

- Separate review rendering from review selection so wording changes do not stale
  event inference. First collect actual invalidation/rebuild examples with A3.
- Materialized projections: immutable observations feed cheap versioned derived
  views. Human corrections can become a separate evidence stream once real review
  disagreements exist; never rewrite the detector's original answer.
- Context budgets per task: fail an optional contract check when required reads
  exceed a declared byte budget. Budget the packet, not the entire repository.
- Extract shared session calibration only after proving cached and uncached
  readers equivalent; avoid an abstract reader factory until there are two users.

## Validation baseline and rollback

Baseline on 2026-09-07: 41 tests; coaching has 543 events, 342 review windows,
26 eligible rounds across two sessions, insufficient probability data. The fixed
14-second review `ea445110508b26f12d4e` previously emitted 840 native HUD rows.
Preserve baseline artifacts under ignored `teststore/architecture-before` and use
the existing dense evidence artifact for comparison. Revert a failed structural
step independently; do not fix a detector while claiming a behavior-only refactor.

## Execution record

Implementation started with separate small-agent reader and read-only orientation
tasks; parent owns integration, dependency declarations and acceptance review.

2026-09-07, A1-A4 accepted together after the delegated run stopped mid-sequence.
Evidence actually rerun at acceptance, not carried over: 50 tests pass (41 at
baseline, +9 for the reader, dependency registry and contract runner); all three
contracts in `docs/tasks.json` pass through the runner; `git diff --check` clean;
the 840-row refinement window is unchanged. `doctor` is unchanged from baseline
at four findings / one stale-geometry error -- pre-existing, not a waived
regression. Elapsed times in the development log are check execution only;
tokens and corrections remain null because this run did not measure them.
A5 remains partial and A6 deferred; neither was started.
