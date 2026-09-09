# Pipeline architecture review and revised delivery gates

2026-09-09. Status: design revision, not implemented runtime behavior.
This review governs the next pipeline increments; the development-workflow
history remains in [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md). The detailed
resolver contract remains in [ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md).

## Assessment and evidence boundary

Reticle has useful foundations: deterministic readers, shared decode, separate
observation and inference modules, refusal states, dependency declarations,
stored-data replay, and inspectable outputs. It does **not** yet implement a
complete semantic match model or an accuracy-controlled variable-fidelity
observer. More detector features alone will not close those gaps.

The proposed temporal adjudication design already addresses many of the right
issues. Implement its contracts and one bounded ambiguity case before building
a general solver. Avoid a second ontology or workflow framework.

Evidence in this review is source inspection, existing handoffs, read-only CLI
diagnostics, and synthetic contract probes. No source footage was relabeled or
rescanned. Historical perceptual findings below are identified as such; this
review does not establish new recognition accuracy or new game mechanics.

Baseline rerun: 251 tests pass; `doctor` has six findings and zero errors;
`status` reports 52 sessions, 411 rounds, four stale minimap datasets and 12/17
exact known K/D comparisons. Neither test success nor count agreement establishes
perceptual correctness. K/D differences require classification, not forced equality.

## 1. Semantics: represent independent facts independently

The coverage requirement is every meaningful state/event **family in scope**,
including an explicit unsupported or unobservable entry. It cannot mean recovering
hidden world facts from a single VOD. Maintain a machine-readable coverage matrix
by family, property, capture regime and ruleset: represented, reader available,
adjudicator available, source-validated, and downstream consumers. A reader or
schema existing is not evidence that the corresponding property works.

| Family | Required distinctions | Current support and next boundary |
|---|---|---|
| Capture and perspective | Source PTS, timestamp fallback, gaps/stalls, menus, widget regimes, POV/player/proxy, audio availability | Stall and profile foundations exist; unify regime/POV and coverage contracts before attributing HUD changes |
| Match and round | Player versus agent, team versus side, patch/mode, partial start/end, buy/live/settlement, score/clock | Rounds exist; uncertain boundaries and stable identities remain necessary for joint adjudication |
| Objective | Carried, dropped, planting, planted, defusing, defused, detonated; attempted/interrupted/completed actions | Partial evidence; complete transition model remains a gate, with unknown carrier/site/time permitted |
| Player life | Alive, dead, downed/temporary state where applicable, revive, new life episode, observed POV | Aggregate counts and killfeed exist; named player/life association is incomplete |
| Position and information | World location, map coordinates, screen coordinates, observed/revealed/last-known information, feasible region | Tracks and lighting exist; preserve knowledge changes separately from movement and entity existence |
| Abilities and objects | Equip/preview, use, projectile, deployment, activation, deactivation/reactivation, recall, destruction/expiry; one use to many objects | Timeline/entity/phase foundations exist, but gallery phases are relative time bins and do not consume entity phases |
| Combat and resources | Fire/burst, reload, weapon switch, damage/heal/shield, charge spend/refund/recharge, ultimate resources | Partial HUD and ability evidence; ammo/HP deltas require POV/equipment continuity and alternatives |
| Economy and equipment | Balance observation, purchase/sale/reward, inventory transfer/drop/pickup, bounded unknown transaction | Credit adjudication and ledger foundations exist; persistent row-to-player joins block automatic attribution |
| Environment and communication | Static art versus dynamic barrier/door/occluder, ping versus world object, sound cue versus actual action | Geometry/ping foundations exist; dynamic state and attributed audio remain incomplete |
| Episodes | Exposure opportunity, contact, no-contact peek, duel without kill, multi-direction contact, trade/contextual review | Coaching primarily adapts killfeed; broader episode definitions remain unimplemented |

These are ontology requirements, not claims that every listed transition applies
to every agent or mode. Rules declare applicability and unknown rulesets retain
alternatives. Do not encode mechanics by ability-name substring.

Use separate IDs for player, life, ability use, world object, rendered marker,
observation and hypothesis revision. A first detection is not a birth; losing
association is not death; a visibility marker is not the enemy's current position.
One cast can create several objects, and several fragments can describe one object.

Represent orthogonal dimensions instead of one overloaded `phase` enum:

```text
object existence:      present / ended / unknown, with censoring
operational state:     active / inactive / unknown, ability-specific domain
appearance:            measured contrast/shape + bright/dim candidate
visibility:            observed / occluded / outside coverage / unknown
knowledge:             current observation / last-known / inferred region
epistemic status:       resolved / ambiguous / refused / stale / conflicted
```

For example, a dim device can remain present, have uncertain operational state,
and have several proposed causes for its appearance change. `phases.segment`
currently names contrast above 203 `live`, and absorbs runs shorter than 700 ms.
Those are corpus-specific appearance heuristics, not general game-state laws.
Retain short-change evidence as unresolved; condition suppression on the class,
cadence and measured noise. A disappearing or dim object does not establish expiry.

`candidate_causes` marks `owner_death` supported when any nearby ally death exists,
while correctly disclosing that ownership is unknown. The structured predicate
must be equally precise: store `nearby_ally_death`, and keep owner-death causal
support conditional on an independently linked owner and applicable mechanics.
Keep photometric/capture changes and occlusion among competing explanations.

Keep three times: observation PTS, inferred occurrence bounds, evidence availability.
Offline smoothing can use later evidence; prediction-time views cannot. Sample
gaps widen occurrence bounds. Unknown, absent, skipped, failed and stale must
remain distinguishable at the field level, not only in a bundle's disclaimer.

## 2. Efficiency: fidelity chosen for the question

Current implementation is multi-rate, not generally adaptive. `passes.Reader`
requests one rate and span set; `sample_multi` shares full-resolution frames.
`refinement` selects bounded review windows and executes native-rate HUD reads.
It has no general per-property spatial resolution or error-controlled scheduler.
The existing adjudication design's evidence requests are the right extension point.

Create a deterministic planner above `passes`, leaving transport free of inference:

```text
stored observations + coverage -> claims and competing explanations
                  -> evidence request -> validated sampling plan
                  -> shared window decode -> reader observations + actual coverage
                  -> recompute affected claims -> pinned annotated revision
```

A request specifies subject/property and competing claims, source interval/ROI,
required timing and spatial tolerance, supported reader tiers, context margin,
trigger/evidence references, requested coverage, priority reason and budget.
A plan records policy/version, effective rate, ROI transform, pixel scale,
calibration key and planned cost. Results record actual PTS/frame IDs, actual
coverage, skipped/failed intervals, cost and which distinctions remain unresolved.

| Question | Least-cost useful tier | Escalation condition |
|---|---|---|
| Stable score/phase/credits | Cached observations; sparse reads of the relevant widget | Change, disagreement, missing coverage or uncertain boundary |
| Small glyph or portrait identity | Native-pixel ROI with surrounding context | Larger context or nearby clearer frames; enlarging pixels adds no evidence |
| Movement/overlap/contact timing | Moderate-rate map reads plus feasible motion regions | Association alternatives or error bounds exceed requested tolerance |
| Brief cast/projectile/pulse | Sentinel change evidence with buffered source context | Dense/native-rate interval containing onset and recovery |
| Map topology/background | Versioned static assets and regime-specific calibration | Transform, occluder state or background regime changes |
| Still-ambiguous source | Wider stored context or another observable channel | Focused source review when further pixel sampling cannot distinguish claims |

Do not set universal rates in the ontology. Select each reader's cheapest
validated tier meeting the requested error tolerance. For a continuously visible
event lasting at least d, a maximum sample gap strictly below d avoids a pure
between-samples miss; it does not guarantee detector recall. Brief or unsupported
duration classes require a sufficiently sensitive sentinel, native-rate coverage,
or an explicit coverage limitation. A sparse sampler cannot request refinement
for a transient it never notices. Include periodic/stratified audit windows outside
all triggers and source-reviewed no-event/no-contact controls.

For motion, use feasible displacement over elapsed time plus localization and
transform uncertainty; refine when that region exceeds the question's tolerance.
Teleport or unknown motion invalidates a walking bound. For event boundaries,
refine until occurrence bounds meet tolerance or the source cannot resolve them.
Use hysteresis/minimum dwell for scheduling to avoid switching tiers every frame;
these are execution controls and must not erase short semantic transitions.

Spatially, retain native source pixels and transforms. A coarse background mask
can serve a different purpose than a tiny portrait or narrow barrier. Downsampling
can erase exactly the feature needed to separate classes, so tiers need held-out
validation by object size and capture regime. Crop after shared decode for detector
savings; do not claim that an ROI avoids full-frame codec work.

`sample_multi` itself notes that `grab()` still decodes compressed frames; lower
sampling mostly avoids retrieval/conversion and detector work. Some older decode
prose calls this demux-only, which is not a safe cost assumption. Measure seek,
decode, retrieve, detector, inference, storage and review costs separately. Merge
nearby windows when measured seek/preroll cost exceeds processing the gap. Reuse
already decoded frames and cached measurements, with bounded memory. Audio is a
candidate trigger only where audibility and recognition coverage are validated.

Two lanes must coexist: opportunity-based observation for unbiased coverage and
conflict-driven refinement for resolving cases. Log selection reasons and audit
sampling probabilities. Do not evaluate event recall solely on selected windows
or silently treat refinement-enriched data as the original population.

Stop at resolution, source exhaustion or explicit budget exhaustion, recording
which occurred. Never lower fidelity silently to satisfy a budget. Promote an
adaptive policy only against the same reviewed windows at reference fidelity:
event recall/precision, timing-bound coverage/width, position error, identity
switches and resolved coverage must meet predeclared tolerances while cost falls.
Report by rare event and capture regime, not only an aggregate average.

## 3. Correctness: diagnose by the first failing contract

An error can have a primary class and downstream consequences. Each issue should
record source pointers, expected versus observed predicate, first failing stage,
evidence status, alternatives, affected outputs and a reproducible fixture.

| Class | Concrete evidence in this review | Correct response |
|---|---|---|
| Coverage/acquisition | Synthetic `sample_multi(..., {'empty': (2, [])})` emits three mock frames: `if spans else None` makes empty mean full capture | Define `None` = unrestricted, `[]` = no work; validate duplicate reader names and invalid requests before decoding |
| Temporal continuity | `segment([0,1000,10000,11000], [240,240,240,240])` returns one `live` interval over all 11 seconds | Carry max-gap/channel coverage; separate observed support from continuity hypothesis across the nine-second hole |
| Semantic/causal attribution | Bright contrast is labeled `live`; any ally death can support an owner-death candidate; string matches exclude mechanics | Separate appearance/state/cause; keyed ownership and ruleset prerequisites; preserve unknown applicability |
| Association/search | `RoundLifetimes.step` lists parents but updates one assigned entity and its appearance even when continuation is ambiguous | Preserve alternate histories and composite membership; appearance from an uncertain link must not contaminate every future identity decision |
| Calibration/geometry/perception | Doctor flags furniture and stalls; handoff reports doorway background contamination, unresolved barrier topology and stale historical renders | Verify source/regime and independent channels before tuning; calibrate by phase and rebuild dependent geometry before acceptance |
| Integration/dependency | Gallery imports relative `PHASES`, not entity-phase output; registry does not declare that dependency | Add the actual phase consumer and dependency together; compare held-out results without claiming improvement in advance |
| Persistence/provenance | `Store.write_hud` and other L1 writers write to the same destination; phase outputs use fixed filenames; atomic refinement replacement also replaces a prior result | Introduce immutable run/revision destinations and atomic manifest publication; atomicity alone is not historical preservation |
| Evaluation/data support | Handoff reports only one held-out ability contrast, absent scalar candidates in supporting real matches, and failed Milestone D separation | Report not-evaluable separately from failed recognition; acquire only missing discriminating evidence; phase-aware rerun may still fail |
| Definition mismatch | Killfeed versus scoreboard divergence can reflect different life/event definitions | Reconcile event types and applicability before counting a detection error |

The synthetic probes establish contract behavior, not its frequency in real VODs.
Historical fragmentation and classification numbers must not become today's
baseline without current-provenance replay. Stalls are capture defects, not
evidence of stationary players. A disagreement identifies a conflict; it does
not by itself identify which channel is wrong.

## 4. Expandability and finding bugs

Preserve the module boundaries already proposed: adapters, normalized evidence,
claims, applicable rules, alternative-history resolution, projections and requests.
Keep `track.py` and `economy.py` as owners of their definitions. Introduce only the
parts exercised by the first vertical slice, not empty abstractions for all factors.

Make the contracts executable:

- A capability declaration names each reader's properties, regimes, tiers,
  coordinate/time domains, negative-evidence limitations and artifact dependencies.
- Stable raw record keys and immutable observation-run manifests retain source,
  producer, assets, configuration and coverage hashes. Existing paths become
  compatibility pointers after a verified migration; do not rewrite old evidence.
- Derived revisions record input revisions, ruleset, alternatives, search
  completeness, conflicts and supersession. Publish only complete revisions.
- Add a factor through its input/output contract, applicability, falsifier and
  dependency declaration. A new channel emits evidence; it does not teach the CLI
  a second definition of death, cast or identity.
- A renderer consumes a pinned projection and shows observed versus inferred,
  ambiguous versus resolved, source gaps, and explanation links. Render early in
  each increment, not only after all factor families are finished.
- A correction records what a reviewer saw and which property they corrected.
  Rebuild the affected dependency closure; never feed a corrected inference back
  as an independent detector vote.

Debug output should answer: why this event, why this identity, why this interval,
why was this alternative rejected, and why was this region not observed? Preserve
the smallest conflicting component and a replay command. Register factors and
projections independently so rendering changes do not invalidate observations.
The current artifact registry is a foundation, not yet a complete provenance DAG.

## 5. Revised order and acceptance

| Gate | Bounded deliverable | Acceptance before promotion |
|---|---|---|
| P0: observable contracts | Coverage inventory; timestamp/empty-request/gap contracts; immutable run manifest design and minimal storage implementation | Empty request reads zero frames; missing/failed read differs from empty; gaps cannot assert continuous observation; failed publish preserves prior revision |
| P1: appearance and state | Phase-aware gallery integration with raw appearance retained; explicit cause prerequisites and unknown ownership | Bright/dim is not automatically active/inactive; unknown owner cannot resolve owner death; class-specific brief phases survive as evidence; held-out D rerun reports pass/fail/not-evaluable |
| P2: identity slice | Two-player overlap through split, roster/killfeed/portrait evidence, alternative histories and pinned replay overlay | Later evidence can revise the association; ambiguous victim stays unknown; fewer identity switches/fragments at matched coverage on current reviewed cases |
| P3: adaptive observer | Request planner driving existing shared readers; temporal tiers first, spatial tiers where validated | Equal-quality comparison to reference fidelity on trigger and audit windows; measured cost reduction; actual coverage and budget refusal preserved |
| P4: wider semantics | Add phase/life/objective transitions, cross-round identity/economy and ability rules incrementally | Ruleset exceptions, partial captures, POV changes, multi-object uses, no-kill/no-contact cases and causal uncertainty exercised in source-reviewed fixtures |
| P5: downstream migration | Coaching/episodes consume versioned state/event projections and correction history | No future leakage; every conclusion links to evidence and coverage; revision changes reproducible and explainable |

P0 is the first implementation priority. P1 can proceed over stored data after
its coverage contract is present. P2 demonstrates the resolver before a general
match-wide solver; P3 must not wait for every P4 reader. Each gate includes a
visually checkable output where pixels are relevant. Full-match annotation remains
the entity-channel acceptance target, with uncertainty visible throughout.

Tests should include missing channels, duplicate/frozen evidence, independent row
permutation, timestamp fallback and discontinuity, reordered scoreboard rows,
unknown ruleset, censored boundaries, incomplete search and failed publication.
Use source-reviewed fixtures for perception; synthetic invariants only test the
contracts. Freeze evaluation cases and tolerances before tuning. No architectural
gate is passed by a lower error count achieved solely by refusing more cases.

## Review verification

The diagnostic commands and all 251 existing tests were rerun for this review.
The two synthetic probes above reproduce the empty-span and gap behaviors without
opening media. Runtime fixes, new datasets, recognition improvements and adaptive
cost savings are **not** claimed by this documentation change.
