# Two concurrent bootstrap experiments

Status: prepared, not launched. Start after the user's readiness signal.
Parent: [experiment program](EXPERIMENT_PROGRAM.md).

## Split and first checkpoint

| Lane | Runner | Question | First bounded deliverable |
|---|---|---|---|
| A: independent evaluation | Separate user-started session | Can we detect a false success, including self-confirming learning? | E1 event audit and an independent evaluation contract for E8 |
| B: grounded learning | Fresh GPT-6 Sol subagent, medium effort | Can unlabelled experience produce one defensible new binding? | Existing domain pilot, real evidence resolution, one anchored learning pass and withdrawal test |

These are complementary experiments, not statistically interchangeable arms.
The frozen-baseline versus adapted-learner comparison happens within B; A checks
its eventual result independently. Neither lane waits for the other to finish.
E2-E4 defects become explicit readiness findings, not automatic scope expansion.
E6 performance promotion, broad E9 question-policy evaluation and E7 full-match
acceptance follow the combined checkpoint. Both lanes measure their own costs.

## Isolation and launch protocol

At launch, inspect the current handoff, dirty work, doctor and status again.
The current checkout may change before launch. Pin the actual code and data used;
do not assume the design's commit is the eventual experimental baseline.

Use separate worktrees under `C:/Users/grant/reticle-worktrees/` if writable, or
another permitted directory outside the primary checkout. Use branches
`experiment/bootstrap-a` and `experiment/bootstrap-b`, with unique suffixes if
they already exist. Never reset or reuse another worker's dirty worktree. If
required fixes remain uncommitted, report the precise missing baseline and do
independent preparation; do not copy a moving checkout into an experiment.

Use the repository venv by absolute path from the worktree; confirm that Python
imports that worktree's `reticle`, not the primary checkout. Link fixtures where
needed without copying raw media. Do not change the shared environment.

Treat production store inputs as read-only. Each lane gets its own experiment
store/output root and unique run IDs. Inspect Store/CLI path handling before
running any writer. Use supported store overrides or a lane-local adapter; do
not assume that a worktree redirects an external store. If a reader needs a
missing observation, issue an acquisition request describing source, interval,
reader and reason; do not overwrite shared observations or rebuild shared geometry.
The coordinator merges overlapping acquisition needs into one later decode pass.

Log predictions to each lane's experiment store `notes/predictions.jsonl`, with
its source-store references in the manifest. Keep metrics and review artifacts
lane-local too. Share references/hashes, not mutable current pointers. Verify
input hashes again before publishing; changed inputs invalidate the comparison.

Lane A owns new `tools/bootstrap_a_*`, `tests/test_bootstrap_a_*`, and
`docs/experiments/bootstrap-a/` files. Lane B owns new `tools/bootstrap_b_*`,
`tests/test_bootstrap_b_*`, `docs/experiments/bootstrap-b/`, and bounded changes to
`reticle/domain_learning.py` and its focused tests if the pilot requires them.
Both call existing decision owners; neither duplicates their rules in an adapter.

Each may add necessary architecture/ownership declarations in its own worktree;
list those edits for reconciliation. Shared CLI, identity, detector, geometry,
domain-fact and storage changes are out of scope for this first split. Propose
an exact patch or missing contract if one is essential, then complete unaffected
work. Neither lane rewrites root NOTES, BACKLOG or docs/tasks.json. Write a
lane-local task contract and handoff; the coordinator integrates them later.

Commit verified owned changes in the lane branch. Do not merge branches, promote
facts, publish new production galleries or mutate the other lane's artifacts.
Preserve the user's `prototypes/mechanics_eval.py` and all unrelated work.

## A: independent evaluation

Read AGENTS, WORKING_MAP, current NOTES/BACKLOG/tasks, the relevant guide sections,
EXPERIMENT_PROGRAM E1/E7/E8, and the death/combat-report/identity owner docstrings.
Run ownership queries before implementing any decision.

1. Inventory current stored evidence and choose a bounded contiguous development
   slice with both agreeing and disagreeing opportunities where available. Read
   every refusal reason. Reserve a distinct session for transfer evaluation;
   do not present a frequently studied session as unseen.
2. Pin a baseline manifest and write the executable local task contract. Log
   predictions before perceptual measurements; inspect source before measuring.
3. Build or reuse one-to-one event comparison and source-linked review. Audit
   death correspondence rather than round totals. Include false matches,
   duplicate-plus-miss cancellation, null properties, timing bounds and missing
   coverage in evaluator tests. Synthetic cases test the evaluator only.
4. Compare the frozen death output with cross-channel evidence, including an
   ablation where a corroborating witness is withheld. Preserve disagreements;
   do not pick the majority as truth. Report source-reviewed errors separately
   from consistency checks. Do not repair production detectors in this lane.
5. Produce a versioned evaluation specification usable by B's later candidate:
   property denominators, event matching, observability, source-selection policy,
   leakage checks and minimum provenance requirements. Existing outputs are
   enough to exercise it; do not wait for B's candidate.

Invoke labelling-pass before creating labels. If unavailable, preserve the exact
missing capability, build the review/question bundle and complete stored-data
and synthetic work. Do not invent source truth. Evaluation labels stay sealed
from learning; publish only the evaluation specification and partition manifest
until B freezes its candidate.

Stop after one bounded audit and its review checkpoint. No corpus-wide rescans.

## B: grounded learning

Read AGENTS, WORKING_MAP, current NOTES/BACKLOG/tasks, EXPERIMENT_PROGRAM E5/E8/E9,
and ENTITY_DOMAIN_LOOP_PILOT with its required reading. Follow that pilot's
readiness and first-review boundaries; the user's launch signal permits this
bounded execution, not production fact promotion or repeated mining cycles.

1. Pin one usable development slice and a distinct transfer session or report
   precisely why transfer evidence is unavailable. Prefer existing current
   observations. Build a manifest and concrete local task contract.
2. Implement the pilot's actual evidence/revision resolver as needed. Check
   transitive selection, association, identity and rule dependencies. Missing
   lineage is unknown independence, not independent evidence.
3. Freeze the original gallery and baseline. Harvest only independently anchored
   exemplars with supported instance bindings. Run one deterministic adapted
   retrieval pass through the identity arbiter, keeping unknown candidates and
   no-proposal windows. Target one defensible new binding; zero is a valid result.
4. Freeze that candidate before transfer evaluation. Exclude the query instance
   and its descendants from teaching it. Do not read A's sealed evaluation truth.
   If no shared partition was available at launch, mark local transfer results
   provisional; A can later select a genuinely untouched evaluation session.
5. Run one counterexample search and an anchor-withdrawal test. Keep any domain
   proposals unaccepted. Test wrong-anchor propagation only in an isolated
   synthetic fixture. Distinguish plumbing, retrieval, source validation and
   transfer outcomes in the report.
6. Produce the pilot's source-linked review and smallest player question for the
   first unresolved perceptual distinction. Invoke labelling-pass before labels.
   Missing review capability limits the empirical claim, not independent resolver
   and replay work. No automatic cluster-wide relabelling from one answer.

Do not fix unrelated scan/track defects or implement a general learner. Stop
after one baseline/adapted pass, withdrawal check and review bundle.

## Result exchange and integration

Each lane writes `handoff.md` and `result.json` under its owned docs directory.
Include branch/commit, manifest and artifact paths, file ownership, exact commands,
test outcomes, first failure/refusal reasons, open questions, measured costs and
the smallest next action. Large/private evidence stays in the experiment store;
repository reports contain allowed public facts and metric citations only.

Use these common result fields (null plus reason for unmeasured values):

```json
{
  "schema_version": 1,
  "lane": "A or B",
  "status": "accepted | review_pending | missing_evidence | failed",
  "commit": null,
  "input_manifest": null,
  "baseline_revision": null,
  "candidate_revision": null,
  "training_sessions": [],
  "evaluation_sessions": [],
  "evaluation_truth_used_for_learning": false,
  "reviewed_scope": null,
  "metrics_artifact": null,
  "cost_artifact": null,
  "first_failure": null,
  "questions": [],
  "next_action": null
}
```

The coordinator reads B's delivered report directly and A's returned handoff
through the user. Compare manifests before combining results. If sessions,
rules, property definitions or input revisions differ, report separate results;
do not manufacture a paired comparison. Integrate verified patches deliberately,
then run A's evaluator on B's frozen candidate with independent source truth.
Only this combined checkpoint can justify the next bootstrap iteration.

## Prompt for the separate session (A)

> Run lane A in `docs/BOOTSTRAP_PARALLEL_RUN.md`: independent evaluation of the
> bootstrap loop. The loose ends are ready for this bounded run. Read the current
> repository guidance and follow the lane's isolation, file ownership, frozen
> evidence, source-review and stop rules. Work in your own worktree and lane-local
> experiment store. Complete one event-correspondence audit and a reusable
> evaluation specification without waiting for lane B. Keep evaluation truth out
> of learning. Do not repair shared production readers or launch subagents.
> Commit verified owned work and return `docs/experiments/bootstrap-a/handoff.md`,
> `result.json`, your branch/commit and artifact paths so I can relay them to the
> coordinating session. Distinguish source-validated results from plumbing and
> consistency checks. Stop at the first bounded review checkpoint.

## Coordinator launch brief (B)

On the user's explicit start signal, spawn one fresh agent with:

```text
task_name: bootstrap_b
model: gpt-6-sol
reasoning_effort: medium
fork_turns: none
```

Supply this self-contained message:

> You are lane B for Reticle at `C:/Users/grant/reticle`. The user has signalled
> readiness for the bounded experiment. Read `AGENTS.md` and
> `docs/BOOTSTRAP_PARALLEL_RUN.md`, then execute lane B and its required existing
> pilot guidance. The goal is to test whether unlabelled experience yields one
> independently grounded new binding, with a frozen baseline, one adapted pass,
> counterexample search and anchor withdrawal. Use your own worktree and
> experiment store, respect file ownership, preserve shared evidence and ongoing
> work, and do not spawn further agents. Complete unaffected work when an input
> is missing; report its exact reason. Stop at the bounded source-review checkpoint
> without promoting production facts or galleries. Commit verified owned changes
> and return your lane-local handoff.md, result.json, branch/commit, artifact paths,
> tests, first failure and player questions. The parent will receive your final
> result; you need not wait for lane A or request repeated status checks.

After dispatch, the coordinator yields the turn. Do not enter a sleep/poll loop
or repeatedly call wait_agent/list_agents. Use the delivered completion message;
if it does not initiate a parent turn, review it on the next user turn. Check
status only when the user requests it or a concrete integration task requires it.
