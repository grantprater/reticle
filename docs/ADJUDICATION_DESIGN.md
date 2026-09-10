# Match-wide temporal adjudication

Date: 2026-09-09. Status: proposed design; no runtime behavior changed.

## Objective

Implementation sequencing and concrete contract defects are updated in
[PIPELINE_REVIEW.md](PIPELINE_REVIEW.md). Use its P0-P5 gates together with this
resolver design. In particular, distinguish measured appearance from operational
state and require actual coverage before treating sparse support as an interval.

Recover the most accurate defensible account of a recorded match from all available
observations. Resolve identity, state, transitions and uncertainty jointly across
time. Accuracy takes precedence over compute cost. Measure accuracy together with
coverage: refusing every difficult case is not success.

The unit of adjudication is a connected set of competing explanations, potentially
spanning a round or match. Individual detections and short events supply evidence;
they do not define the resolver's horizon. Persist alternatives until evidence
distinguishes them. A consistent story is not necessarily a correct story.

Extend [the entity model](minimap-entity-model.html),
[the product plan](IMPLEMENTATION_PLAN.md), and
[the economy design](ECONOMY_AND_PREDICTION_DESIGN.md).
Keep the existing origin, bearing, extent and per-parameter driver representation.

Ability-specific inference, property coverage and minimal supplemental recording
are specified in [ABILITY_ENTITY_INFERENCE_DESIGN.md](ABILITY_ENTITY_INFERENCE_DESIGN.md).

## Current implementation and the gap

Inspected `reconciliation.py`, `round_lifetimes.py`, `minimap_lifecycle.py`,
`artifacts.py`, their routed documentation and current handoff.

- `reconciliation.py` localizes score/roster/killfeed disagreement and resolves
  scoreboard credits within openings. Display-row grouping does not establish
  persistent identity, particularly when rows reorder during an opening.
- `RoundLifetimes.step` performs per-step assignment with short motion windows,
  comparative appearance reacquisition and roster capacity. Alternative parents
  are reported, but one assignment mutates the continuing entity representation.
  This cannot retain complete competing histories through an overlap.
- `Lifecycle.step` links positive origin evidence, lighting and geometric
  continuity. Expiring association anchors cannot establish that an entity died.
- The artifact registry already supports explicit dependencies. Readers and
  refinement already provide a shared-decode boundary worth preserving.
- `minimap.resolve_track` (2026-09-09, `belief-0.1.0`) supplies the position
  half of "render interpolation and prediction distinctly from observed
  coordinates" below. Each sampled instant gets a `Fix` carrying
  `observed`/`interpolated`/`held`/`unresolved`, a physical radius, and a
  refusal reason. `filter_track` stays exactly as it was and now shares the
  admission law through `_admit`, verified identical over 401,797 points on
  every stored session. It is a library channel; nothing stores a `Fix` yet
  and no consumer reads one. What it SHOULD consult, and what each
  channel would change, is *The position belief: a full accounting*
  below.
- The step law drops 8.7% of the current reader's own answers on
  `c40d950031bb` (699 of 8025). The `RUN_PX * 1.6` gate was calibrated against
  `minimap-0.4.0`, so it is owed a re-measurement against the fitted reader.

Pickup diagnostics: `doctor` reports six findings and zero errors; `status`
reports 52 sessions, 411 derived rounds and four stale minimap artifacts. These
are inventory checks, not an adjudication accuracy baseline. Historical Sunset
fragmentation counts in `NOTES.md` require current-provenance rerendering before
being used as acceptance measurements.

## Architecture

```text
immutable observations + coverage + ruleset + human evidence
                         |
                 attributed candidate claims
                         |
          temporal constraint graph / alternative histories
                         |
       adjudicated states + transitions + conflicts + revisions
                         |
             lifecycle events -> episodes -> coaching

unresolved graph component -> evidence request -> shared refinement
                                                -> new observations
```

One evidence store and one state ontology serve every channel. Local readers
remain context-free. Deterministic stage 02 remains unchanged. Optional learned
perception belongs in a separately versioned later stage and emits evidence into
the same graph. Human corrections form another immutable evidence stream.

An inference is never reintroduced as an independent observation. Constraint
messages may flow both ways; their provenance still terminates at original
evidence. Publish state projections only after adjudication, with evidence links.

## What the graph represents

Use sparse state intervals and event boundaries, not a copy of the entire world
at every video frame. Keep position observations at their native timestamps.

| Scope | Variables |
|---|---|
| Capture | source time, availability time, stall/gap, HUD regime, audio availability, coordinate transform, observed POV |
| Match | player identity, agent identity, team membership, patch/mode/ruleset, map/profile, side by round |
| Round | uncertain boundaries, buy/live/post-plant/terminal/settlement phase, score, clock, objective state |
| Player life | persistent player ID, life episode, alive/dead/temporary/unknown state, observed or feasible position, equipment and resource ranges |
| Team information | currently observed enemy, reveal, last-known marker, unobserved state, visibility bounds |
| Ability/object | owner alternatives, cast/activation parent, object instance, lifecycle phase, origin/bearing/extent and their drivers |
| Association | observation-to-entity alternatives, overlap membership, fragments, duplicated observations, clutter/missed-detection alternatives |
| Channel health | readable/missing/refused/stale/stalled state and correlated failure episodes |

Separate player, life episode, rendered icon and world object IDs. Death, revive,
POV switching, last-known markers and overlapping icons must not collapse these
identities. A player persists across rounds; life episodes and most local motion
constraints do not. Partial recordings begin with censored initial states.

Enemy world position and team knowledge are different variables. A last-known
marker constrains a past position; its current world position becomes a feasible
region. Render interpolation and prediction distinctly from observed coordinates.

## Evidence contracts

Adapt existing tables without rewriting them. Each normalized observation has:

```text
id, source_artifact_hash, producer/version, channel, source_record_key
observed_interval, available_at, frame/audio pointer, ROI, coordinate_frame
raw_value, candidates, quality, refusal_reason
capture_regime, coverage_ref, dependency_roots, shared_failure_groups
```

Claims add subject alternatives, predicate, value/domain, occurrence interval,
supporting and contradicting observation IDs, and claim-producer version.
Derived claims retain all transitive evidence roots. Never label a detector score
as a probability unless calibration supports that interpretation.

Coverage records state what could have been detected in an interval: widget
presence, sampling gaps, occlusion, audio masking, supported classes and calibration
regime. A successful empty read differs from a skipped or failed read.

Adjudications contain field-level values or domains, status, evidence and rule
IDs, alternatives, conflict IDs, occurrence bounds, available-at time, mode,
solver status, and revision/supersedes links. Useful statuses include resolved,
ambiguous, unobserved, refused, stale and conflicted; terminal is a domain state,
not a synonym for missing data. Resolution of existence need not resolve identity,
position or exact event time.

## Signal inventory and combinations

Every row is a factor family, not a claim that all readers already exist.
Availability below distinguishes shipped foundations from required expansion.

| Evidence family | Joint use | Availability / limitations |
|---|---|---|
| Score, clock, phase banners, barriers | Locate round transitions; constrain event order and legal phase | Score/clock/barriers exist; banners and boundary fusion need integration |
| Roster counts, portraits, readiness | Alive capacity, lineup and identity candidates, resource bounds | Counts exist; stable keyed identity claims remain incomplete; slots compact |
| Killfeed entries and portraits | Death/kill candidates, participants, weapon/ability, temporal linkage | Existing; entries can be delayed, duplicated, missing or temporary-life related |
| Scoreboard names, portraits, K/D/A, credits | Match identity and cumulative constraints across multiple rounds | Row observations/credit adjudication exist; row association and full ledger joins remain open |
| Local HUD HP, shield, ammo, weapon | Damage/shoot/reload/equipment hypotheses and POV continuity | Partial readers; attribute only after POV resolution |
| Ability tray, submenu, charges, ult points | Equip/cast/activation/termination and spend/recharge constraints | Existing/prototype evidence; semantics differ by ability phase |
| Minimap self, ally, enemy, portrait/shape | Position, identity association, overlap membership, visibility state | Existing channels; substantial association and coverage gaps |
| Observed lighting and cone lobes | Independent checks on icon role, bearing and observable area | Existing; geometry and common pixel failures must be modeled |
| Map art, barriers, doors, occluders | Movement reachability, phase restrictions, visibility bounds | Static geometry/barriers exist; dynamic geometry coverage incomplete |
| World view, outlines, hands, weapon effects | POV identity, objects, fire, damage and cast corroboration | Partial/prototype; screen distance is not map distance |
| Objective icon, carrier, plant/defuse HUD, sounds | Spike possession and legal objective transitions | Partial; missing clock alone cannot prove planting |
| Audio shots, steps, reloads, casts, announcements | Event timing and candidate class/owner corroboration | Prototypes; mix, audibility, fake cues and attribution limit certainty |
| Ability geometry and trajectories | Group fragments, distinguish preview/deployment, infer owner regions | Prototypes; one activation may create several objects or phases |
| Reactive utility motion/bearing | Constrain possible enemy regions/contact intervals | Proposed; usually a region, not exact enemy identity/position |
| Direct player/source review | Resolve concrete identity, grouping, timing and class questions | Existing review foundations; labels remain independent of predictions |

Seek different failure mechanisms, not merely more feature names. Two classifiers
on the same crop, repeated OCR of an unchanged glyph, or a cone reconstructed from
the icon it validates are not independent witnesses. Observed illumination can
add information, but it still shares capture/compositing failure with the icon.

Model shared crop, frame, template, source event and inferred-parent dependencies.
Collapse exact duplicates and frozen frames. Aggregate sustained reads into
episodes with saturation or a calibrated temporal likelihood; increasing frame
rate must not manufacture certainty. Introduce shared channel-failure hypotheses
so one bad geometry fit can explain many simultaneous residuals.

## Invariants and their applicability

Each versioned rule declares scope, patch/mode applicability, required evidence,
preconditions, allowed exceptions, hard/soft status, and a falsification fixture.
Unknown prerequisites yield `not_applicable` or `unknown`, never a veto.
Rules constrain latent game states; uncertain detector values remain hypotheses.

| Rule family | Constraint | Conditions and exceptions |
|---|---|---|
| Identity | One physical player cannot occupy two simultaneous positions in the same world frame | Rendered duplicates, proxies, decoys, POV changes and coordinate uncertainty stay separate |
| Overlap conservation | Entering life identities persist through a merged observation until explained departure/transition | Observation multiplicity may fall; death/revive, visibility loss and missed exit stay explicit |
| Life accounting | Alive state changes through legal transitions; cumulative scoreboard changes constrain candidate events | Revives, temporary lives, mode rules and delayed scoreboard updates prevent naive death counting |
| Association | A simple icon belongs to at most one life at a time | A composite blob may represent a set; several fragments may represent one object |
| Motion | Reachable region expands according to elapsed time, geometry and allowed motion modes | Dashes, teleport, displacement, map transitions and unknown abilities prevent unconditional speed rejection |
| Static parameters | A fixed origin stays fixed within measurement uncertainty | Bearing/extent can change; deployment and redeployment are separate phases |
| Origins | An interval has one causal origin relation or an explicitly unknown/censored origin | One cast can parent multiple entities; missing origin evidence does not prove clutter |
| Visibility | Observed enemy appearance must admit detection/reveal/reacquisition/relocation explanations | Conservative visible bounds, occluders, sampling gaps and reader misses are required |
| Information | A last-known marker cannot update world knowledge without new evidence | Animation and coordinate transforms can move rendered pixels |
| Ability resources | Spend and regeneration produce feasible charge/point ranges | Patch, mode, refund, recharge, sustained abilities and post-death permissions are explicit |
| Objective | Possession, drop, plant, defuse and detonation follow allowed transitions | Partial capture and uncertain phase leave boundary alternatives |
| Economy | Consecutive balances admit observed transactions and bounded unknown transactions | Cap, reset, rewards, purchases, refunds, drops and survival rules use the existing ledger |
| Round ordering | Score/phase progression obeys the selected ruleset | Capture skips, pauses, overtime, custom modes and delayed displays are modeled |

Important corrections to older prose: absence of detected audio does not prove
absence of teleport; sharing a cast does not make every fragment one object;
being dead does not prohibit every ability action; five players does not imply a
five-death ceiling. Agent lists and numeric timings belong in a patch-keyed rule
registry, not permanent Python assertions. Unknown recording patch selects the
intersection of safe rules or retains alternative rulesets.

For negative evidence, require a detection opportunity and measured miss behavior.
Even an observable, readable interval normally supplies a likelihood penalty,
not logical impossibility. Hard constraints are reserved for established game
laws under satisfied prerequisites. If the graph becomes infeasible, emit a
small conflicting rule/evidence set; preserve detector-error and unknown-mechanic
alternatives. Never silently weaken a rule until the graph becomes satisfiable.

## Inference procedure

Use a hybrid temporal factor graph: discrete identity/lifecycle/association
variables, interval resource domains, and conditional geometric feasibility.
This is a design choice, not a mandate to install a general inference framework.
The representation supports both exact small-component solving and bounded search.

1. Validate provenance, segment capture regimes, and construct uncertain round
   boundaries. Preserve boundary alternatives where phase readings conflict.
2. Generate inclusive candidates from stored observations, including clutter,
   missed detection, unknown identity/class/origin and censored capture. Fast
   trackers propose edges; their chosen paths are not authoritative evidence.
3. Apply sound domain pruning and interval propagation. Build temporal/spatial
   adjacency only where events can interact, retaining an unknown-mechanism edge
   when a ruleset or reader cannot justify exclusion.
4. Solve simple chains by dynamic programming and ordinary one-to-one assignment
   subproblems with the existing assignment machinery. Enumerate small overlap
   permutations exactly. Keep shared identity/resource variables between them.
5. Solve coupled components using branch-and-bound over discrete alternatives,
   with admissible bounds. A future integer solver can replace this backend after
   comparison; do not add a dependency for the schema alone. Avoid alternating
   irreversible identity and event decisions: proposals from either reopen both.
6. Carry multiple histories through ambiguous components. Round-end scoreboard,
   later portraits and resource observations send constraints backward. Match
   identity and ledgers connect adjacent rounds; uncertain boundaries connect
   local graphs until resolved.
7. Publish fields shared by all retained feasible histories when search is
   exhaustive. Under scored selection, require validated decision thresholds and
   an explicit competing-history margin; scores alone are not calibrated confidence.
8. Generate targeted evidence requests for unresolved distinctions. Add returned
   observations and recompute only the affected dependency closure.

A possible calibrated objective is the sum of observation-episode log likelihoods
and soft transition factors, subject to hard constraints. Dependencies require
joint factors or shared latent failure variables; multiplying each feature's
confidence is invalid. Before calibration exists, use feasibility, explicit
evidence tiers and unresolved alternatives. Do not invent posterior percentages.

Approximate inference must report completeness, explored/pruned alternatives,
best bound or unknown bound, termination reason and unresolved component size.
A beam's survivors are not the complete feasible set. Agreement among them cannot
certify a fact when discarded histories might disagree. Loopy message passing
can propose candidates, but does not certify a global optimum or calibrated
marginal. A timeout produces partial/ambiguous output, not a forced answer.

## Time and revision

Support two explicitly different projections:

- `online(as_of)`: use only evidence available by that time. Any calibration or
  identity fact learned later is excluded. Appropriate for prediction evaluation.
- `retrospective`: smooth across the complete available recording. Appropriate
  for annotated-match reconstruction and retrospective review.

Event occurrence is an interval, observation time is immutable, and availability
time records when the evidence could inform a consumer. A later scoreboard can
establish that a death occurred between snapshots without establishing its exact
time, killer or location. Preserve those unknowns.

Revisions append a new interpretation and mappings from old entity hypotheses.
Stable raw IDs survive every rebuild. Exported event/entity IDs are scoped to an
adjudication revision; explicit equivalence/split/merge links support consumers.
The renderer requests a revision and mode, so its labels cannot silently change
while a player is reviewing the footage.

## Worked ambiguity: icons entering an overlap

Two ally identities A and B enter one rendered blob. Store a composite observation
with membership alternatives `{A,B}` and any justified clutter alternative. Both
life identities remain alive; neither receives the blob's center as an exact
position. Maintain a feasible region for each.

Two icons emerge. Retain both A-left/B-right and B-left/A-right histories when
motion and appearance cannot distinguish them. A later independently attributed
portrait or killfeed-plus-death-location observation can select a history and
revise the earlier association. If one icon emerges and the roster drops, that
supports one death but does not identify the victim. A killfeed identity can
complete it. If coverage was missing, retain an unobserved exit alternative.

The same construction handles self hidden under an ally icon, temporary UI loss,
and fragmented ability shapes. Object grouping uses the ability's instance
cardinality and phase rules; it does not conserve raw blob count.

## Spending computation where it changes the answer

Run stored-data propagation before requesting new pixels. Prioritize unresolved
components by downstream error cost, expected discrimination between alternatives,
and evidence acquisition cost. These estimates start as explicit heuristics and
are calibrated from actual resolved requests; no claimed optimal policy yet.

Escalation options: nearby stored channels, wider temporal context, native-rate
shared decode, alternative deterministic crop reader, audio matching, specialized
later-stage model, then a focused human question with source windows. Select the
tool that can distinguish the actual alternatives; a broad semantic model is
poor evidence for an eight-pixel numeric read. Independent high-quality cues may
justify going directly to a more expensive method.

Model evidence records prompt/model/version, input windows and abstention.
Review crops should omit predicted labels where practical to reduce anchoring.
Multiple prompts or models sharing pixels are correlated evidence. Human review
records whether source alone or suggestions were shown, permits unknown, and
preserves disagreements. Follow the repository's labeling workflow before any
new labeling campaign.

The old approximately 1%-of-frames expensive-layer guideline becomes a monitored
cost diagnostic for this accuracy-first design, not a hard ceiling. Report
expensive-frame share and marginal accuracy/coverage gains. Preserve random audit
windows and no-contact examples alongside conflict-driven requests so gating
does not conceal shared errors or bias the evaluation set.

Stop acquisition when the distinction is resolved, available evidence cannot
distinguish it, or an explicit compute/review budget is exhausted. Record which
condition applies. Irrecoverable hidden information remains unknown.

## Efficiency without sacrificing correctness

- Share decoding across all readers and merge overlapping refinement requests.
  Rules never decode video. Persist reusable measurements and provenance.
- Sort once by source time; use interval indexes and spatial buckets to avoid
  all-pairs comparisons. With N observations and E plausible links, target
  O(N log N + E) graph construction; dense ambiguity can still make E quadratic.
- Use event boundaries and run-length states for phase/resources; retain native
  timing for motion. Frozen frames add neither graph nodes nor independent votes.
- Collapse equivalent histories by sufficient boundary state, including identity,
  life, resource domains and unresolved dependencies. Do not merge histories that
  future scoreboard or owner evidence could distinguish.
- Decompose by connected components, not arbitrary fixed windows. Large factors
  can reconnect rounds; carry separator domains rather than freezing summaries.
- Cache rule outputs by inputs, ruleset and producer hashes through `artifacts.py`.
  Corrections invalidate descendants only, including affected match-wide joins.
- Cache geometry-conditioned reachability and visibility bounds by transform and
  dynamic occluder state. Never reuse stale geometry or exact bearings across gaps.
- Keep large masks in existing artifacts; graph records reference them. Use lazy
  candidate expansion for difficult components, recording search incompleteness.

Combinatorial inference has no general cheap guarantee. Measure runtime, peak
memory, candidate counts, largest component, search completeness, recomputed
fraction, decoded seconds and review effort per recorded minute. Accuracy gains
are evaluated before trading them away for speed.

## Implementation boundaries and rollout

Proposed package `reticle/adjudication/`:

```text
schema.py       immutable evidence, claims, domains, result/revision contracts
adapters.py     normalize current tables; preserve raw pointers and timing
rules.py        versioned registry and applicability checks
factors/        identity, life, motion, visibility, abilities, objective, economy
graph.py        sparse variables, factors and connected components
solve.py        exact small problems, bounded search and solver diagnostics
project.py      online/retrospective state and lifecycle projections
requests.py     unresolved alternatives -> evidence/review requests
```

Keep `track.py` motion helpers and `economy.py` accounting as owners of their
existing definitions. Refactor a conflicting rule once with equivalence coverage;
do not duplicate it in the graph. Existing adjudicators initially remain baselines
and candidate producers. Stop feeding their resolved outputs as raw evidence.

Proposed stored outputs: observations/claims references, adjudication manifest,
states, associations, transitions, conflicts, requests and revision mappings.
Register independent factor and projection dependencies. Publish a manifest only
after all output tables are written and checked; readers see a complete revision.

Proposed CLI, not implemented:

```text
reticle adjudicate SESSION --mode retrospective
reticle adjudicate SESSION --mode online --as-of-ms TIME
reticle adjudicate SESSION --explain CLAIM_ID
reticle adjudicate SESSION --compare REVISION_A REVISION_B
```

| Milestone | Deliverable | Acceptance gate |
|---|---|---|
| 0 | Freeze current artifacts/commands and source-reviewed cases; inventory evidence coverage | Reproducible baseline with current geometry and explicit stale exclusions |
| 1 | Contracts, adapters, coverage and evidence lineage; shadow output | No raw mutation, lossless references, deterministic replay, no decoding |
| 2 | Persistent player/life identity and overlap hypotheses, joined to roster/killfeed/scoreboard | Fewer fragments and identity switches at matched coverage; ambiguous victim remains unknown |
| 3 | Phase/life/objective graph with whole-round smoothing and scoreboard deltas | Delayed events corrected without future leakage or invented exact timestamps |
| 4 | Lighting/visibility/motion and ability origins, phases, resource bounds | Measured false-birth reduction without losing legitimate reveals, relocations or multi-object casts |
| 5 | Cross-round identity and economy joins; later evidence propagation | Row reorder, side swap and censored snapshots retain correct attribution and uncertainty |
| 6 | Evidence acquisition and optional model/human resolution | Measured gain beyond deterministic fusion, including cost and unbiased audit cases |
| 7 | Annotated-match projection and downstream migration | Inspectable full rounds; evidence explanations and revisions; coaching consumes declared mode |

Begin with milestone 2's overlap problem after the contracts. It addresses a
documented failure and exercises the essential architecture: several channels,
conservation, multiple histories and later disambiguation. Add factor families
incrementally; full-match coupling should not delay this first measurable result.

## Validation and promotion

Use held-out complete matches with separately reviewed identity, timing and
grouping evidence. Split by match/session, not adjacent frames. Hold out maps,
capture regimes and patches where data permits; report untested regimes plainly.
Small existing labels do not establish universal accuracy.

Measure player identity switches, trajectory fragmentation, false entities per
minute, event precision/recall, timing interval coverage and width, resource-domain
coverage and width, and resolved-field coverage at a fixed error rate. Separate
observed positions from inferred regions and evaluate each appropriately.
Report calibration only for outputs with a probabilistic interpretation. Cluster
uncertainty by match. Track absolute source-reviewed error alongside invariants.

Required adversarial fixtures include overlap/split, self occlusion, row sorting,
roster compaction, POV switch, stall, missing widget, delayed/duplicate killfeed,
revive/temporary life, teleport/fake cue, reveal, dynamic occluder, one cast with
multiple objects, sustained ability, unknown patch, partial round and settlement.

Required properties: duplicated/frozen evidence does not increase confidence;
permuting independent input rows preserves results; missing channels cause
appropriate uncertainty; future evidence changes retrospective output but never
an earlier online projection; inconsistent evidence produces a visible conflict;
pruned search cannot claim exhaustive certainty; revision preserves raw evidence;
stored-only recomputation opens no media.

Compare current local adjudication, temporal-only, cross-channel-only and combined
resolution on the same cases. Ablate whole evidence families as well as rules.
Include consensus cases in source review: disagreement-only evaluation misses
shared errors. Track missed candidate generation separately from wrong resolution.

Promote each milestone only after its real command and annotated source windows
demonstrate the intended gain at matched coverage with no unexplained regression.
Set numeric thresholds from the measured baseline before tuning. Runtime tests
and mathematical invariants cannot substitute for perceptual accuracy checks.

## The position belief: a full accounting

One question: **where is the local player at a sampled instant, and how
tightly.** Existence, identity, bearing and ownership are separate answers this
one must not absorb. The families above are general; this section grounds them
in what bears on this question, what is stored today, and what each would
change. It is the target `minimap.resolve_track` is measured against, not a
description of what it does.

### What answers it today

`belief-0.1.0` consults three things: the self reads, the step law, and the ally
channel as a witness that the widget was drawn. On `c40d950031bb` that lifts the
answer from 75.0% of instants to 89.6%, at a median inferred radius of 5.7 px.
It is single-channel, and single-channel is exactly why it is wrong in the first
two rows below.

### Evidence that VOIDS the prior

| Evidence | Constraint on the belief | Status |
|---|---|---|
| Round boundary (`l2/rounds`) | A round start returns every player to spawn, so no belief may cross one | Stored, 18 sessions. Gated since `belief-0.2.0` |
| Self death | A dead player has no world position; holding one is a false claim | BLOCKED on self identity. Widget absence is a partial proxy, since the death screen removes the widget |
| Licensed teleport or displacement | A legal discontinuity; never draw a path through it | Wired, via `filter_track` motion spans and `track.Corroboration` |
| Camera wipe or POV change | The icon may stop being self | `tools/wipe_scout.py` locates wipes from stored reads |

### Evidence that BOUNDS the region

| Evidence | Constraint on the belief | Status |
|---|---|---|
| Map art floor (`store/geometry`) | The reachable set is walkable floor, not a disk | Cached per `<map>__<profile>`. A 47 px belief disk currently spans walls |
| Buy-phase barriers (`store/barriers`) | Closed doorways cut the reachable set during buy | Stored for two maps; see the backlog entry to bake them per map and side |
| Phase (`l2/rounds`, HUD clock) | During buy the player stands at spawn -- far tighter than any motion bound | Stored |
| Motion class (`track.admits`) | Sets how fast the region expands; dash and teleport widen it only with corroboration | Exists |

### Evidence that RESOLVES WHICH ICON is self

| Evidence | Constraint on the belief | Status |
|---|---|---|
| Ally icon centres | **Exclude nothing, in principle and in measurement.** The widget cannot resolve two players who touch, and it draws one above another on a different level at the same point, so distinct icons may be exactly coincident. Read self-ally pairs come as close as 0.7 px | Measured 2026-09-09 and REFUTED. Their one use is as a drawn-witness, in `absent_instants` |
| Self-key fragments at a refusal | Bound the centre tightly even when the ring fit refuses: within 12 px on every one of 137 bracketed refusals | Measured; `minimap_self_appearance.py --joint` |
| Viewcone and lighting | Independent check on icon role and bearing | Channels exist |

### Evidence that says WHETHER WE COULD SEE AT ALL

| Evidence | Constraint on the belief | Status |
|---|---|---|
| Widget drawn | Separates "refused" from "nobody was looking"; only the latter forbids a belief | **BLOCKED -- L1 writes the same NULL for both.** Interim ally cross-reference recovers 2016 of 2676 |
| Stalled capture | Those frames are not observations and must not count either way | `doctor` reports it per session |
| Sampling tier and gaps | A belief must never inflate observed coverage | Coverage is reported separately by `fidelity-check` |

### Evidence that CORROBORATES AFTERWARDS

| Evidence | Constraint on the belief | Status |
|---|---|---|
| Pings (`store/events/ping`) | A ping origin ties to a player position at a time | Stored |
| Killfeed | Locates participants at a time | Exists; for SELF it is blocked on identity |
| Roster alive counts | Bound how many icons should exist | `l1/roster`, per team rather than per player |
| Scoreboard | Cumulative constraints across rounds | Row observations exist; row association open |
| Audio | Event timing and owner corroboration | Proposed |

### What self identity unblocks

The session does not record which player is self. That single gap withholds
per-player alive state, self death, killfeed self-participation and scoreboard
row association -- so the layer's whole account of death currently rests on
widget absence, which is a proxy for the death screen and not the event. The
backlog entry is *Record which agent the player played, per session*. Nothing
downstream should model death until it lands.

### Rules the belief obeys whatever it consults

- A belief is never evidence. It cannot seed a template, feed a detector's
  prior, or count toward observed coverage.
- Observed and believed coverage are reported separately and never summed.
- It never crosses a void, and never claims a region the map forbids.
- Interpolation and prediction render distinctly from observed coordinates.
- `unresolved` carries a reason, and the reasons partition every unanswered
  instant.

### How we would know the accounting is honestly implemented

- No belief rests on evidence across a round boundary. Held: 0 on both
  current sessions, read from `Fix.rests_on` rather than reconstructed.
- No belief centre lies off walkable floor, and the bound is a reachable set
  rather than a disk.
- The observed count equals the admitted read count exactly.
- Every unanswered instant carries exactly one reason.
- Ablation: removing any one channel costs coverage and never precision. A
  channel that buys precision is either doing another channel's job or is
  being read as independent when it is not.

### Order of work

1. ~~Move the belief out of `minimap.py` and give it round bounds and the
   floor mask as inputs.~~ DONE, `belief-0.2.0`. It establishes the seam every
   later channel plugs into, and it cost coverage rather than buying it:
   88.7% -> 88.5% and 90.3% -> 90.0% believed, because both gates REFUSE.

       session          void gate        floor gate    believed
       c40d950031bb     relabels 87      refuses 28    88.7% -> 88.5%
       ff636d173b07     refuses 18       refuses 66    90.3% -> 90.0%

   The void gate changes nothing on `c40d950031bb`: every instant it would
   refuse was already unresolved as stale, so it only renames the reason. That
   is the honest shape of a correctness gate -- it buys nothing where the
   layer was already silent.
2. ~~Ally centres as a discriminator inside clusters.~~ CLOSED, measured
   negative. Two separate claims failed:

   - **Exclusion is refuted.** Gating a belief on distance to an ally would
     refuse 6.6% and 2.9% of the reader's own correct positions on the two
     current sessions, and the closest read pair sits 0.7 px apart. There is
     no separation to exploit, because `MIN_ICON_SEPARATION_PX` collapses
     fragments inside one key and says nothing across two.
   - **The overlap diagnosis is refuted outright.** Proximity to an ally
     lifts refusal only 1.2x-1.6x, and most refusals have no ally near them:

         session          nearest ally within 15 px
                          self read        self refused
         c40d950031bb     36.9%            43.9%
         ff636d173b07     19.3%            30.2%

     That test could only see one occluder, so `prototypes/minimap_occlusion.py`
     re-ran it naming none: it counts pixels near the self position that leave
     the geometry's measured lighting band, so enemies, ability entities,
     pings, the spike, markers and barriers all count without being read.
     Refused instants carry a foreign-content fraction of 0.481 against 0.454
     at read instants -- **a lift of 1.06x against a 1.5x bar**, and 0.99x at
     the widest margin.

     **Nothing is drawn over the icon when the ring refuses.** The standing
     candidate is already measured, over five sessions: the self key survives
     only over the LOWER HALF of the rim, present on 61-67% of bearings
     150-240 deg and 22-23% at 330-30. That is a screen-space dropout in the
     icon's own rendering, and it predicts refusals with no occluder. The next
     test is BEARING, not occlusion.

     Both tests are measurable only on BRACKETED refusals -- the isolated
     ones -- so the long runs remain untested either way.
3. A `widget_drawn` column, folded into the re-decode that rebuilds the 18
   sessions still on `minimap-0.4.0`.
4. Self identity, which unblocks death.
5. Ping and killfeed corroboration.

Steps 1 and 2 are recomputable from stored data. Step 3 needs a re-decode, and
steps 4 and 5 need it only if identity requires new reads.

## Reference basis

The factor-graph representation follows the decomposition of global inference
into local factors described by [Kschischang, Frey and Loeliger,
Factor Graphs and the Sum-Product Algorithm](https://www.isiweb.ee.ethz.ch/papers/arch/aloe-2001-1.pdf).
The solver strategy, evidence contracts and promotion gates above are proposals
for Reticle, not results established by that paper.

[Riot's Clove introduction](https://playvalorant.com/en-us/news/game-updates/clove-death-is-only-the-beginning/)
documents post-death ability use and self-revival, illustrating why life and cast
rules require agent-specific exceptions. It is historical evidence, not a current
complete mechanics registry. Verify mechanics against each recording's ruleset
before enabling hard constraints.
