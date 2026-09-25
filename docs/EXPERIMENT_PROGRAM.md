# Experiments toward a complete observable event record

2026-09-24. Proposed experiments, not measured results. This design extends
[pipeline acceptance](PIPELINE_REVIEW.md) and the
[bounded learning pilot](ENTITY_DOMAIN_LOOP_PILOT.md). It does not replace the
active backlog or launch that pilot.

The central hypothesis: an explicit belief about a reader, a discriminating
observation, and a recorded revision produce more useful progress per unit cost
than adding detector complexity. Cross-channel evidence accelerates this loop
when it supplies information the first channel lacks. Shared dependencies can
also make several channels confidently wrong together.

## Define the target before measuring

Target zero incorrect assertions and complete recovery of source-observable,
salient events on a frozen evaluation corpus. This is an acceptance target for
that corpus, not a guarantee about future captures. Count unknowns separately;
abstaining on everything cannot satisfy completeness.

Use the event families in PIPELINE_REVIEW rather than inventing another ontology.
For each family, declare required properties, applicable capture regimes,
source-observability criteria, timing/position tolerances, and salience before
running a detector. Start with deaths and life transitions, then entity identity
and continuity, ability uses and objects, objective transitions, combat/resource
changes, and information/contact opportunities. Keep uncovered families visible.

Score presence, identity, association, phase, location and time independently.
An observable death can have an unobservable location. An unreadable source and
a reader's refusal are different outcomes. Independent source review determines
observability; detector failure cannot redefine an event out of scope.

Report exact event matches, misses, extras, duplicates, wrong property assertions,
identity switches, unresolved observable properties, and unobservable properties.
Use one-to-one event matching with declared tolerances. Include whole-event
correctness, per-family denominators, and the fraction of complete rounds.
Never substitute matching round totals or frame accuracy for event accuracy.

## Common experimental contract

Before each run, freeze source pointers, contiguous windows, selection seed,
code and dirty-state hashes, observation/geometry/rule revisions, dependencies,
review truth revision, and the event-matching specification. Preserve old outputs.
Raw media stays in place. Inspect source images before perceptual measurement;
log predictions in the store's `notes/predictions.jsonl` before executing them.
These proposed cards become registered predictions only when inputs are pinned.

Each prediction states the belief, competing explanation, discriminating result,
confidence, falsifier, acceptance rule and next action for either outcome. Keep
beliefs about the instrument separate from beliefs about the environment.

Use contiguous development rounds, a held-out session, and later a held-out
map/profile. Existing frequently studied sessions are regression/development
material, not fresh transfer evidence. Include random time windows, no-event
controls, refusals, and regime transitions alongside disagreements. Record
selection probabilities; report targeted and random audits separately.

Invoke `labelling-pass` before creating labels. Use existing glance/review tools,
blind the reviewer to candidate verdicts where possible, and include independently
labelled controls. A failed control invalidates that review batch. On the first
failed perceptual approach, present the player with the source, alternatives and
an explicit cannot-tell option. Record the first failure before revising the reader.

Compare baseline and treatment on identical pinned inputs. Promote only a
source-verified improvement with no new wrong assertions and no hidden loss of
coverage. A correctness improvement that costs more can proceed as a separate
tradeoff; it does not count as a performance improvement. Store runs through
`reticle.metrics` and cite measured results with metric tokens.

## E1: Can agreement conceal a wrong event history?

**Prediction.** Killfeed, combat-report and scoreboard evidence will help localize
event errors, but agreement of totals will not establish event correspondence.

**Experiment.** Start with combat-report corpus acceptance from BACKLOG. Replay
current stored evidence first. Review every discrepancy by its stored reason,
then review seeded contiguous rounds whose totals agree. Bind each reviewed
death to its actual source witness, identity and life episode. Compare killfeed
alone with cross-channel adjudication; withhold each corroborating channel in
turn. Use controlled synthetic duplicate-plus-miss cases to test the evaluator,
without counting them as perceptual evidence.

**Falsifier.** Fusion makes an incorrect binding, or the evaluator accepts a
duplicate and a miss merely because their counts cancel. Any source error in an
agreeing round refutes agreement as a sufficient acceptance test.

**Decision.** Fix the earliest failing binding or event definition through its
owner. Pass requires exact source correspondence on the reviewed slice, retained
conflicts and nulls, and explicit corpus review coverage. This is the first task.

## E2: Do regime errors explain clustered detector failures?

**Prediction.** Explicit readable-widget and capture-regime evidence will reduce
false events around transitions without suppressing events in readable intervals.

**Experiment.** Use the menu-overlay and ring-fit cases named in NOTES as
development cases. Add independently selected normal, boundary, overlap and
capture-gap windows. Compare current readers with a gate based on separately
observed regime evidence. Test geometry placement against the visible ring;
static map values still come exclusively from baked `(map, profile)` geometry.

**Falsifier.** The gate hides a readable event, mistakes a gap for a negative, or
requires the detector's own accepted output to establish widget validity.

**Decision.** Publish valid observation intervals with reasons and boundary
uncertainty. Source-unreadable intervals retain censored lifetimes. Do not count
fewer emitted events as improved precision without independent review.

## E3: Can independent identity survive overlap and reappearance?

**Prediction.** Joint association using independent roster/identity witnesses
will reduce track fragmentation and identity switches relative to local matching.

**Experiment.** Freeze contiguous isolated-to-overlapping-to-separated icon
sequences plus separated controls. Compare current association, temporal-only
association, and temporal plus independent witnesses. Route all names through
`adjudication.identity`. Preserve competing associations; an ambiguous merged
appearance cannot update a named exemplar. Hide later frames for a causal run,
then allow them for a separately scored offline reconstruction.

**Falsifier.** A recovered identity changes to the wrong agent, depends on its own
retrieved exemplar, or trades fewer tracks for merged distinct entities.

**Decision.** Score switches, splits, merges, location error and unresolved duration
on the same source sequence. Render the competing histories. Prefer unresolved
membership over an invented continuity, while counting that unresolved coverage.

## E4: Which witness separates equip, use and object birth?

**Prediction.** Combining tray changes, audio and minimap appearances will resolve
some cases each channel leaves ambiguous; joint cast-object assignment will
outperform independent nearest-time assignment in crowded cases.

**Experiment.** Use existing solo demos for development and a separate session
for transfer. Include cancelled equips, ordinary weapon/knife sounds, masked
audio, repeated casts, overlapping objects and opportunities with no object.
Compare each channel alone, pairs and the joint result. Test candidate cardinality
rules only where registered domain facts support them. Keep actor identity and
cast-to-object binding as separate questions.

**Falsifier.** Audio promotes an equip to a use without a discriminating witness,
one object satisfies incompatible uses, or a channel contributes only evidence
derived from the verdict it is supposed to corroborate.

**Decision.** Score use detection, actor, object association and lifecycle bounds
separately. Read the `ability-owner` ownership gap before implementing attribution;
declare the owner and defer names to the arbiter. Preserve censored ends and
unsupported phase distinctions. Expand the reject class before tuning thresholds.

## E5: Does a learned rule predict independent evidence?

**Prediction.** A proposed environment rule will predict an independently observed
property in a held-out instance without using that rule to select or label it.

**Experiment.** Follow the existing bounded domain pilot and its readiness gate.
Resolve actual artifact revisions and transitive dependencies first. Mine on a
development slice; freeze the proposed rule; search held-out supporting,
contradicting and unresolved opportunities. Run with and without the rule. Withdraw
one seed witness and rebuild its dependency closure as an instrument test.

**Falsifier.** Support disappears when derived/self-labelled evidence is excluded,
a reviewed counterexample violates the stated scope, or dependent names survive
withdrawal without alternate independent support.

**Decision.** Separate a capability finding from a game fact. Keep proposals
unaccepted until the existing promotion requirements hold; archive failed beliefs
with their counterexamples. Do not repair a failed prediction by narrowing its
scope after seeing the held-out answer and calling that a successful test.

## E6: How much work can be removed without losing an event?

**Prediction.** Stored-data replay, shared decoding and opportunity-driven
refinement will lower end-to-end cost while preserving the reviewed event record.

**Experiment.** First establish a source-reviewed native-rate reference on bounded
windows; native-rate detector output itself is not truth. Compare fixed-rate,
opportunity-triggered, and opportunity-plus-conflict policies on identical source
windows, with random audit windows outside every trigger. Sweep sampling phase
as well as rate to expose between-sample misses. Replay policy decisions using
only evidence available at each decision time; score offline smoothing separately.

**Falsifier.** Any observable transient vanishes, a timing bound becomes falsely
precise, unresolved coverage rises, or savings disappear in end-to-end measurement.

**Decision.** Select the cheapest tested policy meeting every declared correctness
and coverage tolerance. Measure decode/seek, conversion, detector, adjudication,
storage, wall time, peak memory and player-review effort separately; report cold
and warm runs on the same hardware. Merge decode windows using measured costs.
ROI crops may reduce detector work without reducing codec work. Preserve each
reader's version. Budget exhaustion remains explicit. Sparse sentinels need
independent recall validation; a completely missed event cannot request refinement.

## E7: Does local success survive an entire unseen match?

**Prediction.** The frozen combined system will retain its event and property
accuracy across ordinary play, transitions and rare opportunities in an unseen
match within its declared capture regimes.

**Experiment.** Render a pinned event revision alongside the original source,
showing entity IDs, names, phase, timing bounds, uncertainty and evidence links.
Review contiguous playback across all in-scope families, including intervals
where the system emitted nothing. Correct the first failure, add its regression,
and evaluate a fresh held-out slice; the corrected match becomes development data.

**Falsifier.** Any wrong assertion, missed observable event, unsupported definite
boundary, hidden gap or identity switch fails the complete-record target.

**Decision.** Report exact results only for the reviewed scope. Publish remaining
unsupported families and regimes beside it. A zero-error sample warrants a bounded
empirical claim; correlated frames do not create independent proof of universal
accuracy. Broaden sessions and regimes before broadening the claim.

## Execution order and learning efficiency

The intended engine is bootstrapping from unlabelled experience. Labels are a
scarce calibration and evaluation resource, not the acquisition strategy.

### E8: Can unlabelled experience improve the next frozen learner?

**Prediction.** Adding unlabelled sessions will increase independently verified
resolved coverage on unseen sessions at fixed correctness, while reducing player
questions per observable event.

**Loop.** Ingest through shared deterministic readers; retain candidates,
rejections, coverage gaps and disagreements. Discover recurring appearances and
transitions without naming them. Seek independent anchors in existing channels;
propose instance bindings, exemplars and scoped rules. Replay through the owning
adjudicators, search for contradictions, then freeze a candidate revision. Test
that revision on the next unseen session before it can teach another revision.

A cluster establishes recurrence, not identity or semantics. A scoreboard or HUD
witness can teach appearance only when its binding to the instance is supported.
Temporal consistency supplies constraints, not independent labels. Agreement
between descendants of one anchor counts as one lineage. Retrieved identities
cannot become fresh independent seeds. Unanchored clusters stay anonymous and
remain useful for discovery and player questions.

**Comparison.** Start all arms with the same frozen readers, domain registry and
existing anchors. Compare a frozen baseline, additional unlabelled experience
with independently anchored exemplar learning, and that same learning plus
reviewed rule proposals. Give each arm the same incoming sessions and compute
budget. Evaluate before learning from each new session. Keep evaluation labels
sealed from mining, thresholds, selection and promotion. Run deterministic
template/constraint updates; Stage 02 remains model-free.

**Stress tests.** Remove an anchor, inject a wrong anchor in a synthetic isolated
fixture, introduce an unsupported class, and withhold a whole capture regime.
Check whether descendants retract, contradictions surface and unfamiliar cases
remain unresolved. Synthetic tests check containment; real held-out source
review checks recognition. Track error propagation depth and affected entities.

**Falsifier.** Unlabelled volume increases confident mistakes, improvements vanish
after excluding dependent support, unknown classes acquire familiar names, or
the loop needs growing player effort merely to maintain accuracy.

**Acceptance.** A learning revision adds source-verified resolved properties on
held-out experience with no new wrong assertions or missed events in the reviewed
set. Report learning curves against unlabelled hours, distinct independent
anchors, compute and player minutes. Count abstentions and unsupported regimes.
Zero eligible anchors is a useful failure: acquire a discriminating witness or
ask the player rather than loosen the gate. Retain frozen parent revisions so
failed learners can be withdrawn without deleting their observations.

### E9: Can the system choose the smallest useful player question?

**Prediction.** Questions selected for their ability to distinguish competing
explanations resolve more independently verified downstream properties per
player minute than random unresolved questions.

**Experiment.** Compare random unresolved questions with dependency-aware selection
at the same review budget. Select representative instances of recurring conflicts,
with source context and cannot-tell answers. Estimate how many distinct instances
a question could affect; deduplicate shared lineage so repeated frames do not
inflate its value. Reserve random audits of both confident and silent intervals.

**Falsifier.** Targeted questions improve only their own clusters, propagate wrong
bindings, or hide errors in populations the selector never asks about.

**Decision.** Route player answers as explicit evidence through existing owners;
never silently relabel a cluster from one answer. Validate each transfer and score
held-out improvement, review time, retractions and residual error discovery.
Keep evaluation review effort separate from learning questions. The first failed
perceptual approach still triggers the player-question path.

### Bootstrap milestones

1. One independently anchored exemplar resolves a different unlabelled instance,
   with full lineage and a source-verified binding.
2. A frozen learner transfers to an unseen session; withdrawing its anchor removes
   unsupported descendants.
3. Repeated unlabelled increments improve held-out coverage at fixed correctness
   and a bounded player-question budget.
4. The combined learner passes contiguous match review and retains the result
   under the cheaper acquisition policy.

E8 is the organizing experiment; E1-E5 establish its trustworthy observations,
bindings and feedback boundaries. E9 controls the human cost, E6 the compute cost,
and E7 tests the complete result. Reuse the existing domain pilot for the first
bounded loop rather than building another learning framework.

Run E1 first. E2 precedes affected minimap E3/E4 measurements. E5 follows the
existing pilot readiness contract. Measure cost during every experiment, but
promote E6 savings only against reviewed correctness. E7 closes each expanded
scope, starting with deaths rather than waiting for every family to exist.

At each checkpoint record the prior belief, observed surprise, instrument check,
revised belief, falsified alternative, remaining ambiguity and smallest useful
next experiment. Prioritize uncertainty with high downstream consequence and
cheap discriminating evidence. Estimate that priority prospectively; replace
estimates with measured resolved properties, corrected events, compute cost and
review time. Do not rank by novelty or agreement alone.

To test the development strategy itself, alternate comparable bounded questions
between cross-channel-first investigation and the existing baseline workflow.
Predeclare the work budget and success criterion. Compare independently verified
corrections and uncertainties resolved per total compute and human-review effort,
including failed attempts. Use this as a small operational comparison, not a
causal claim from unmatched tasks. Keep any safety/correctness gate identical.

This document is the design deliverable. Execution needs a selected experiment's
concrete task contract and pinned manifest. No new perceptual results, labels,
production rules or performance claims were produced while writing it.
