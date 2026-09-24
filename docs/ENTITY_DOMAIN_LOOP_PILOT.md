# First entity and domain learning pilot

Status: prepared; launch after the user finishes scan fixes and gives the go-ahead.
Runner: GPT-6 Sol, medium reasoning effort, as requested by the user.
Parent design: [Entity mining and domain learning](ENTITY_DOMAIN_LEARNING_DESIGN.md).

## Outcome and scope

Connect the domain-hypothesis foundation to real stored observations, identity
verdicts and round lifetimes. Run one bounded discovery/retrieval pass and one
counterexample check on a frozen session slice. Return a source-linked review
bundle before repeated experiments, production fact promotion, or corpus expansion.

This handoff prepares work; it does not assert that the scan or track fixes have
finished. Read the latest code and artifacts at launch. Historical handoff prose
may lag the implementation. Keep ongoing detector and lifetime fixes with their
current session until the user declares them ready.

## Start prompt for the implementation session

> Run the bounded pilot in docs/ENTITY_DOMAIN_LOOP_PILOT.md using GPT-6 Sol at
> medium effort. The scan fixes are ready. Inspect current provenance and ownership,
> implement the real-store evidence resolver, then run one frozen session slice
> through exemplar and domain-hypothesis review. Preserve unknowns, counterexamples,
> and all rule/identity dependencies. Report at the first review checkpoint before
> wider experimentation or promoting domain facts. Follow the stop conditions.

Use this prompt only after the user confirms readiness. Preparation does not
launch an agent, rescan media, generate labels, or change production facts.

## Required reading and pickup

Read AGENTS.md, docs/WORKING_MAP.md, NOTES.md, the active BACKLOG.md task and
docs/tasks.json; then the parent design, docs/ROUND_ENTITIES.md,
docs/IDENTITY_EXEMPLAR_LOOP.md, and prototypes/CLAUDE.md. Read the relevant guide
sections on source review and sampling. Inspect the owner docstrings in
domain_learning, domain, round_lifetimes, track, adjudication.identity, store,
artifacts, and revisions before changing their boundaries.

Run with the repository venv:

```powershell
git status --short
.\.venv\Scripts\python.exe -m reticle doctor
.\.venv\Scripts\python.exe -m reticle status
.\.venv\Scripts\python.exe -m reticle ownership domain-hypothesis
.\.venv\Scripts\python.exe -m reticle ownership round-entity
.\.venv\Scripts\python.exe -m reticle ownership agent-identity
.\.venv\Scripts\python.exe -m reticle ownership domain-fact
```

Read each finding's cause. A global stale channel does not establish whether the
chosen slice is usable. Inspect the exact artifacts the pilot will consume.

## Readiness and frozen input manifest

Select a development session with current required observations and a checkable
source. Freeze a small contiguous round slice before mining. Reserve another
session for later transfer evaluation; do not tune on it during this pilot.
Choose by evidence availability and representative opportunities, not naming
success. Include a seeded random review selection alongside disagreements and
gaps; retain windows with no proposals.

Write a manifest with source fingerprint, session/round/window IDs, code commit
and dirty-state declaration, reader/descriptor versions, geometry key/revision,
identity and association versions, artifact revisions or content hashes, sampling
coverage, selection policy/seed, and known limitations. Verify required data are
complete and no writer is still replacing them. Recheck dependencies before
publication; if they changed, mark the run stale rather than mixing versions.
Pin observations by references/hashes; raw media stays at its original path.

Readiness means the selected question has adequate traceable evidence. Anonymous
tracks and explicit gaps are valid inputs. Unsupported joins or names cannot
become exemplars or independent domain support. If one required channel is absent,
report the exact missing input and what can still be reviewed.

## First implementation: resolve actual evidence

The current domain_learning validator compares revisions supplied by the proposal.
Its consumer graph is also supplied by the input. Add a resolver that obtains
actual revisions and evidence from the store and registered artifacts. A caller's
`current_revision` assertion cannot establish freshness. Resolve source observation
keys and transitive identity, association, selection, and rule dependencies.

Use existing ownership and artifact declarations. When an artifact has no immutable
revision, pin a verified content hash and its provenance through existing machinery.
Missing lineage stays unknown with a reason; never infer independence from an empty
dependency list whose producer does not actually record dependencies. Evidence
resolution should use stored data without decoding video.

Track IDs represent association hypotheses, not independent truth. Preserve alternate
histories, merges, gaps, refits and identity changes. A revision to association must
invalidate any exemplar or hypothesis that relied on that association. Appearance
used to join a track cannot independently corroborate that track's retrieved name.

Add an executable task contract once the actual adapter command and selected inputs
are known. Verify existing behavior first. Test missing/stale references, changed
association history, transitive circular support, incomplete lineage and retained
counterexamples. Run the actual adapter and inspect the generated bundle; a schema
test alone does not establish integration.

## Bounded learning pass

1. Inspect source for the selected slice and log falsifiable predictions before
   perceptual measurement. State which independent witness could label an exemplar
   and what would refute the proposed binding. Invoke the labelling-pass skill
   before labelling; if unavailable, report that specific missing capability and
   continue independent stored-data integration without fabricating labels.
2. Run a baseline with the frozen gallery. Harvest only appearances with independent
   identity witnesses and checkable instance binding. Exclude the query instance
   from its own references. Keep retrieved/dependent names ineligible as new seeds.
3. Run one adapted retrieval pass over unresolved instances through the identity
   arbiter. Record added, changed, refused and conflicting names with dependencies.
   Missing eligible exemplars is a valid explicit result, not a reason to loosen
   identity gates. Keep unknown families and rare candidates available for review.
4. Produce at most three concrete domain candidates supported by resolvable evidence.
   This is a workload cap, not a quota: zero defensible candidates is valid. Classify
   detector weaknesses as capability findings, not game facts. Scope each proposal
   and record its prediction, falsifier and intended owning consumer.
5. Search the frozen slice for counterexamples once. Report supporting, contradicting,
   dependent and unresolved evidence separately. Count distinct instances/rounds/
   sessions, with ambiguity explicit. Do not select only accepted tracks or names.
6. Render a review bundle using existing overlays/review tools where possible:
   contiguous source windows, track alternatives, raw appearances, gallery matches,
   arbiter verdicts, domain proposals and provenance. A review that reveals an
   upstream perceptual failure records the first failure and presents a player
   question; it does not start repeated threshold tuning.

The agent may complete bounded plumbing fixes needed for this pass. A new detector
experiment, broader rescan, second mining cycle, or expanded scope needs the next
checkpoint. No accepted domain files change during this pilot.

## Domain feedback checkpoint

Produce a proposed consumer impact report and withdrawal/rebuild preview. Show which
owner would consume each candidate, which dependent artifacts would change, and
whether stored inputs suffice to recompute them. Mark undeclared consumers unknown.

The canonical domain registry requires valid provenance for derived facts; evidence
IDs in the foundation's draft are not automatically valid domain fact references.
Describe or implement a schema-compatible provenance bridge with focused tests,
but keep the proposal unaccepted. Preserve measured versus inferred provenance and
never invent an observed/player fact to satisfy validation. Actual production
consumption follows reviewed promotion in a later checkpoint.

## Return to the user

Report the frozen inputs and readiness result; implementation changes and checks;
baseline versus adapted names with independent review coverage; candidate domain
claims and counterexamples; unresolved cases and first source-review failure;
artifact paths; and the smallest justified next step. Record measurements through
metrics and cite them in repository prose. Keep unmeasured accuracy and review
effort unknown. State clearly whether the result is plumbing validation, a
source-reviewed pilot, or a missing-evidence report.

Commit only verified owned changes and preserve unrelated work. Update the bounded
handoff/task contract without displacing any still-active parallel work. Stop after
this report. The model setting is an execution choice, not evidence: source ambiguity
requires better evidence or the player, even if reasoning effort increases.
