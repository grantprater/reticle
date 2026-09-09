# Ability entities: inference and minimal capture design

Date: 2026-09-09. Status: milestones A-F implemented; annotation and new capture have
not been run for this document. Extends [ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md).

## Outcome

Infer which ability was used, by whom, when, which objects or effects it created,
and how their properties evolve. Resolve each property separately from evidence.
A confidently identified cast may have unknown destination, target or outcome.
An observed smoke may have known geometry but ambiguous ability and owner.

Use the existing demos first. Request additional footage only after identifying a
specific property that existing pixels, audio, reference material and match
footage cannot establish. Minimize new recorded seconds and repeat attempts,
while preserving enough context to answer the question reliably.

## Evidence available now

Read-only manifest inventory on 2026-09-09 found 28 `ability-demo` clips, about
1,199 seconds total, representing 27 tagged agents with two Omen clips. These are
mostly large-minimap Ascent recordings. Older labeled clips are additional
evidence; searching by `ability-demo` alone misses them. The reference catalogue
is harvested 2026-09-04 and contains 29 agents, including mixed-mode and passive
entries. It is a candidate vocabulary, not a complete verified mechanics database.

Current anchors worth using:

| Evidence | Use first | Limitation |
|---|---|---|
| Existing demo tray, submenu and world-view reads | Agent/slot, equip, commit and activation candidates | Validate semantics per ability; a drop can reflect sustain ending, a mode switch or a read error |
| Recorded cast census in `BACKLOG.md` | Route to existing windows; historical census found 119 C/Q/E/X drops across 27 demos | Not 119 newly verified casts; observed drops and true uses differ |
| Omen `b9558488a607`, 83.4 s | Existing isolated equip/cast examples and repeated C/E uses | Historical tray/audio agreement is six casts, not general validation |
| Six files in `reference/assets/ability_sfx` | Reuse source-linked Omen audio references | Q/E filenames are slot-based; reconcile names through the catalogue and source before promotion |
| Ultimate voiceline assets | Test existing ally/enemy audio references before requesting any new ones | Perspective, language, patch, masking and playback variants still require validation |
| `ability_series.py` and stored series | Native-time evolution and appearance evidence | A fixed sample point does not follow a moving object |
| Candidate/ability/paint labels | Existing positives, negatives and geometry supervision | Candidate labels do not establish object grouping or an entire cast's coverage |
| Existing match footage | Check ordinary HUD scale, team/enemy rendering and clutter | A missed cue cannot establish that an ability was absent |

The tagged set includes neither Cypher nor Deadlock; this is a manifest coverage
gap, not a request to record both. Cypher already has older labeled material.
Search the full manifest/label/reference inventory before assigning any new take.

Superseded claims must not drive collection: some `infinite-abilities` tags describe
setup toggles, not the state during casts; tray ultimates are readable in many
demos; basic sound references now exist for Omen. The Vyse candidate failure in
`64d0fb783be2` is a detector problem recorded in the handoff, not proof that its
source footage needs replacing. Static map geometry now comes from the keyed
geometry/art pipeline, not a short demo's median.

This inventory establishes file availability only. It does not establish usable
source coverage or new accuracy figures.

## Entity and property model

Separate the following linked records:

1. **Ability definition:** patch-keyed agent/ability ID, slot mappings, modes,
   legal state transitions, prerequisites and property domains. A slot is not
   itself an identity, and catalogue order is not recording order.
2. **Use episode:** equip/aim/preview, commit, activation/re-use, cancel and end
   relations. An equipped preview can be cancelled without creating a world object.
3. **Entity instance:** projectile, device, region, beam, summoned actor, marker,
   temporary weapon or status effect. One use may create zero spatial objects,
   several siblings, or a chain of different objects.
4. **Observation component:** glyph, ring, cone, wall segment, pulse or screen
   effect attributed to an entity. A radius ring is a representation of a device's
   property, not necessarily another independently acting device.

Distinguish `same_instance`, `part_of`, `spawned_by`, `phase_of`, `replaces`,
`recovered_as_resource`, `redeployed_from` and `affects`. Recovering a resource and
casting again need not preserve physical-object identity. An activation may
resume the same deployed device. Declare this per mechanic; retain alternatives
where the recording cannot distinguish them. Instant effects can have a temporal
entity record with no inferred minimap position.

Every property has a value/domain, units and coordinate frame, time interval,
status, supporting/contradicting evidence, source kind, and rule/version. Source
kinds include observed, inferred, reference-derived and assumed-for-experiment.
The last kind cannot be promoted as a measured game fact.

| Property group | Fields and interpretation |
|---|---|
| Identity | Ability candidates, agent candidates, persistent owner/life candidates, team, semantic family, mode; anonymous identity remains valid |
| Causality | Use/activation parent, child cardinality domain, predecessor/successor, target alternatives and affected entities |
| Time | Equip, commit, spawn, travel, arm, activation, pulse, deactivation and termination intervals; natural versus interrupted ending; censoring |
| Geometry | Origin, footprint/mask, center, endpoints/polyline, orientation or absent bearing, radius/length/width, cone angle, height/layer if observable |
| Motion | Origin/bearing/extent driver separately; velocity/acceleration ranges, path, bounce/attachment/pursuit behavior, deployment movement versus active movement |
| Function | Blocking vision/movement/projectiles, damage/heal/slow/blind/suppress/reveal, control mode and affected-team rules; reference capability differs from observed effect |
| State | Preview, flying, deploying, armed, active, dormant, possessed, recalled, destroyed, expired, consumed, unknown; per-ability subset and transitions |
| Resources | Charges, fuel, cooldown, activation count, ultimate points, recoverability; ranges when incomplete; cheat/reset intervals excluded from normal accounting |
| Durability | Nominal health from rules; observed damage/destruction evidence; current health unknown without an adequate read or damage ledger |
| Observation | Channel/perspective-specific rendering, icon/region mode, animation phase, visibility/reveal state, audio signature family and coverage |
| Uncertainty | Existence, class, owner, grouping, position and termination confidence separately; calibrated probability only where validated |

Minimap pixels do not directly establish meters, elevation, collision volume,
damage radius or effective range. Use a verified transform or keep pixel units.
A drawn radius may show placement/control range rather than effect range. A
rendered footprint is not automatically a collision boundary. A fitted 2D track
cannot certify a 3D ballistic law. Keep operationally relevant but unobservable
properties explicitly unknown instead of demanding impossible footage.

## Build a property-level coverage matrix first

One row per `(ability, mode, transition/property, perspective, capture regime)`:

```text
reference_rule/version; source windows; castability prerequisites
cast evidence; coverage intervals; labeled/derived evidence; independence roots
status: supported | weak | conflicting | censored | not_exercised |
        uncastable_in_setup | unrepresentative | unreadable | not_applicable
remaining alternatives; cheapest discriminating observation; capture_request_id
```

These categories prevent a common error: no icon in a solo clip can mean no cast,
no minimap representation, a missed representation, or inappropriate setup.
None are equivalent. A no-icon conclusion applies only to a verified use, phase,
perspective and readable interval; it does not establish no effect or no audio.

Do not enumerate only four casts per agent: alternate fire, secondary activation,
passives, cancellation, recovery and combined catalogue entries need explicit
subcases. Start from the cached catalogue and reconcile against the recording's
patch and visible UI. Unknown or newer mechanics retain an open-set class.

## Inference procedure over the existing corpus

### 1. Preserve and inspect sources

Inventory manifests, source availability, labels, cast caches, series and assets
by source hash. Associate old labels using source coordinates/times and preserved
legacy keys. Never rescan into the label-key namespace of `2ba870ccbd50`,
`eb10db50b1fb`, `d95cfad5693a` or `79a706a7ce4c`. New measurements receive separate
artifact IDs; do not overwrite evidence or copy raw media.

Check actual profile, geometry freshness, orientation, HUD and audio coverage.
Inspect representative full-frame source windows before measuring a perceptual
hypothesis. Log its falsifiable prediction as required by repository conventions.
This design does not perform a labeling pass; invoke the repository's
`.claude/skills/labelling-pass/SKILL.md` before one is started.

### 2. Construct a use timeline independently of minimap candidates

Resolve local agent/POV with manifest as a prior and portrait/tray/world evidence
as checks. Read slot identity, submenu, selected state, charge/pip changes, hand
animation and audio. Align timestamps with measured uncertainty. Build competing
equip/commit/activation/end interpretations using ability-specific semantics.

Use recording order as a weak prior only after independently checking it. An
ordered set of visible icons is a subsequence of uses, not a one-to-one index.
Do not label a template by order and then use that template to certify the order.
Do not require a tray drop: retain audio/world-only uses, passive transitions,
cheat-replenished uses and explicit unknown-use intervals.

### 3. Join a shared native-rate pass where stored evidence is insufficient

The entire tagged corpus is about 20 minutes; one sequential native-frame pass
is a reasonable initial accuracy-first option if current stored data lacks the
needed timing. Reuse valid cached data; batch HUD, minimap, world crops and audio
readers on merged source intervals. Avoid per-candidate seeking. Dense sampling
is gated by possible use/opportunity and includes no-icon/control intervals.

Keep the ability itself, nearby baseline map, observed illumination, self/other
icons and relevant world-view/HUD context. Candidates must cover compact glyphs,
thin segments, large regions, low-saturation tints, moving objects and brief
transients. Cones and near-player pixels remain candidate components. Avoid a
universal floor-only mask for objects whose representation can cross walls or
encode projected effects. Geometry constrains the relevant ability phase.

### 4. Generate competing object explanations

For each use, consider all compatible entity families and cardinalities. Associate
components using shared onset intervals, spatial support, appearance, per-parameter
motion, phase transitions and expected rendering. Fit line/arc/region hypotheses
to the supporting pixels, not to the first candidate center or a bounding box.

Maintain alternatives such as one wall with several segments, two independent
deployments, repeated pulses of one effect, or a device plus its range indicator.
Spatial proximity and a shared cast are insufficient to merge. Distinct activation
indices handle several shots within one ultimate. Periodic visibility does not
create a new physical entity on every pulse.

Preview association spans the observed equip episode, even if the hold is long.
Only the portion consistent with the commit and placement geometry constrains the
deployed location. Time out a search budget with unresolved status; do not turn
the historical two-second search heuristic into a game law.

### 5. Resolve identity and measure properties jointly

Combine cast identity, observed mode, origin relative to owner, cardinality,
appearance over time, geometry, motion, sound and allowed transitions using the
adjudication graph. Agent-in-solo is useful owner evidence after setup validation;
it is not proof every residual is that agent's ability. Clutter, pings, self-cone
fragments and unsupported effects remain alternatives.

Compare appearance against galleries by phase and perspective, not one average
template per ability. Shared appearances such as generic smoke keep a family
identity until owner/use evidence distinguishes the exact ability. For match
footage, jointly match several plausible casters/uses; nearest cast in time is
not an attribution rule. Local preview ownership applies only to a verified local
POV and actual preview, including special ability UI modes.

Condition parameter estimation on identity alternatives, then compare histories.
Fit static origins across frames, estimate bearings with circular uncertainty,
track moving origins, and model changing extent separately. Do not average over
incompatible identities or deployment phases. Use intervals for onset, duration
and speed under sampling/occlusion. Clip end supplies right censoring, not expiry.

### 6. Test candidate explanations against original evidence

Use a restrained forward rendering model: hypothesize glyph/region/animation and
predict its pixel support over the known background and illumination. Fit allowed
transform/opacity/phase nuisance parameters, with complexity penalties and a
clutter/unmodeled residual. The rendering model must not absorb arbitrary scenery
and call it an ability. Compare explanations on withheld times/regions where
possible, and verify performance against independent labels.

For audio, start with the existing voicelines and source-linked Omen cuts. Test
matched references on independently anchored uses and negative windows. Preserve
temporal structure; fixed spectral templates or a flexible mixture alone can
explain unrelated sounds. A future convolutional/time-sequence dictionary can
handle overlap if it improves held-out recognition. Synthetic mixtures test code
and propose augmentations; they do not validate real HRTF, occlusion or game mixing.
No silent-audio veto without demonstrated audibility and reader sensitivity.

Residuals can propose missed entities, but a synthesized residual is not an
independent confirming channel. Repeated templates, related features and a
template's own training cast cannot multiply confidence.

### 7. Review only the unresolved distinctions and test transfer

First inspect current windows with full widget, native-scale pixels, magnified
detail, timeline and synchronized HUD/world/audio context. When perception cannot
derive grouping, ask which components are one object, allowing none/unknown and
independent additions. Do not show only the detector's candidates: whole-use
windows are needed to discover omissions. Preserve corrections separately.

Reserve complete uses, clips and sessions for evaluation. If an ability has only
one cast, it may supply an exemplar but cannot also provide independent validation
of that exemplar. Source-reviewed ordinary match windows test transfer to clutter,
small minimaps and other perspectives before collecting more clean demos.

## Which existing clips answer which questions

This is a routing list, not newly inspected per-property coverage.

| Family / existing sources | Attempt from the demos | Likely remaining discriminator |
|---|---|---|
| Omen: `b9558488a607`, `e78e75b2d191` | Equip/cast audio, teleport use, smoke phase and origin | Other-player perspective, masked audio, cancelled/alternate transitions |
| Killjoy: `dae6f33f3f48` | Preview/device/range-ring/cone separation; fixed origin versus turning bearing | Controlled enemy entry, trigger/destruction and any visibility-dependent rendering |
| Viper: `6bb88dba5d2c`; Harbor: `2f4ef4e8da23`; Sage: `33db0d21fa32` | Extended regions, segments, activation phases, origin/extent | Natural ending if clipped; reactivation versus new cast; specific gated branches |
| Sova: `02cf738b1c8f`; Skye: `6ab7a9e99235`; Fade: `5abe77b9953f`; Tejo: `c0b63335e635` | Moving entities, piloting, beam/region children and deployment phases | Target-reactive/hit-confirm/seek behavior not exercised in solo |
| Yoru: `5a63cc4fecfc`; Chamber: `ccff4a11ff5a`; Veto: `f9703a4b5a47`; Waylay: `b588ea1a6dd5` | Proxy/device/player separation and relocation-associated changes | Fake versus real transitions, opponent perception or missing secondary modes |
| Gekko: `fc9ec5c86a26` | Spawn, travel, dormant/recovery representations where exercised | Target or objective-dependent branches and re-use if absent |
| Clove: `28f53bfddbbe`; Reyna: `af09094c0729`; Sage/Skye | All actually demonstrated modes | Damage, kill, death, ally or live-target prerequisites; verify each branch separately |
| Vyse: `64d0fb783be2` | Reinspect source with illumination/tint and cross-channel cues | Capture only after proving a source-coverage failure |
| Remaining tagged agents and older labels | Exhaust use timelines and explicit no-icon cases | Only unresolved properties; no default request for another full-kit clip |

Do not copy old restrictions such as “Sage healing requires an ally” into the
coverage matrix without checking the specific mode: self-heal and ally-heal are
different branches. Likewise, player-guided and autonomous portions of one ability
can have different solo representativeness. References and source behavior must
agree before promoting driver or castability rules.

## Minimal additional-footage policy

A request is justified only if it names the surviving alternatives, the property
they disagree on, why existing sources fail, and an action expected to separate
them. Do not ask for another clip merely because a detector scored poorly.

Rank requests by expected reduction in consequential uncertainty per total effort:

```text
value = expected useful distinctions resolved * downstream importance
        / (setup time + recorded time + review time + expected redo time)
```

Estimate success conservatively from prerequisite availability, prior protocol
success, signal visibility and contamination. These are planning estimates, not
measured probabilities. Also report recorded duration separately, since that is
the user's requested quantity. Avoid saving ten seconds by creating a fragile take
that is likely to require another session.

Batch requests sharing agent, map, target setup and camera into a short take, but
keep unrelated casts from overlapping. Choose a set that covers outstanding
property rows with minimum expected cost; a greedy gain-per-cost schedule with
setup reuse is sufficient initially. Exact optimization is unnecessary before
the coverage matrix exists. Retain one baseline and one discriminating transition
per take, adding repetitions only if they can resolve uncertainty.

### Preflight and one-use protocol

1. Prepare the requested location, agent, charges and target state before the
   take. Record patch, mode, map, HUD scale, key mappings, language/audio settings
   and participant roles. If cheats prepare resources, disable state-altering
   cheats for the measured interval and record the transition. Normal rules are
   required when measuring duration, recharge, death or damage behavior.
2. Make one short pilot recording after settings change. Use
   `prototypes/clip_preflight.py` with a valid compatible donor, inspect actual
   frames and confirm audio/stalls. It checks widget size/orientation/obstruction;
   it does not certify all audio, timing or gameplay prerequisites. Do not batch
   the remaining takes until the first one is usable.
3. Keep the existing fixed, always-same, uncentered minimap profile, normal full
   HUD, centered crosshair and unobstructed widget. Record native 60 fps when
   available and unchanged game audio, preferably 48 kHz. Match ordinary capture
   settings for transfer tests; no rescaling or added overlays over evidence.
4. Record a roughly two-second readable baseline. State the take ID/ability before
   the quiet interval or on a separate microphone track, not over the ability cue.
   Keep the caster stationary for an audio reference; use the prescribed movement
   only for a movement test. Reuse keyed map geometry rather than estimating it
   from the stationary take.
5. Equip and briefly hold until its distinct phase is observable, then perform
   the single scripted action. Hold the relevant POV until the transition of
   interest and about two seconds of post-transition context are captured. For
   audio, wait until the cue has finished before starting another trial.
6. Verify the success condition immediately. Log actual action and failure if the
   action was cancelled, the target was invalid, or a cue overlapped. Do not label
   success from the intended script alone. Retry only the failed step.

The two-second margins are starting recording allowances, not mechanic timings.
Increase them if the source cannot establish baseline or ending. Duration is
`baseline + equip/hold + time to required transition + post-context`. Do not record
an entire natural lifetime when only artwork is missing. When natural lifetime is
the question, capture the full uninterrupted lifetime; accelerated time, cuts and
resetting destroy that evidence. Persistent-until-destroyed objects need a
controlled ending test, not an arbitrary long wait.

### Capture cards, issued only for demonstrated gaps

Times below are planning allowances per usable take, exclude lobby/setup, and
depend on the mechanic's actual lifetime. They are not promised completion times.

| Missing property | Minimum setup and actions | Success condition | Recording allowance |
|---|---|---|---|
| Clean local cue or cast-to-object identity | Solo; quiet baseline, equip/hold, one commit, let cue finish | Independent visible commit and isolated sound/object onset | Commonly 8–15 s; longer cue uses formula |
| Preview versus deployed mode | Solo; hold, adjust aim once, commit; optional separate cancel trial | Preview follows input, commit is observed, deployed behavior distinguished | 10–20 s; cancel only if unresolved |
| Origin/bearing/extent driver | Solo; one prescribed straight movement and one turn, or rotate a stationary device control | Which parameter changes is visible with known input | 10–20 s plus deployment |
| Fixed versus owner-attached region | Solo; cast, then move owner away along a short known path | Object origin and owner motion separate with readable map | 8–15 s plus deployment |
| Multi-object versus segmented/pulsing object | Solo where castable; isolated use, all scheduled activations, keep whole footprint visible | Parent use, sibling/segment geometry and at least two disputed pulses/activations visible | Full distinguishing sequence + 4–6 s |
| Recall/redeploy versus resume activation | Solo; deploy, activate/deactivate or recall, then prescribed re-use | Resource/UI transition and object continuity are both visible | 15–30 s plus required cooldown; skip wait if not measuring cooldown |
| Reactive target behavior | Caster + cooperating opponent; target starts outside range, crosses once, then exits or turns | Baseline, entry, response and target position visible | 12–20 s plus arming/travel |
| Damage/heal/hit-confirm gate | Required target/owner state established; capture pre-state, one effect, post-state | HUD or target-view state change corroborates the effect | 8–15 s plus effect duration |
| Kill/death/revive branch | Appropriate opposing/ally participants; record prerequisite and immediate ability use continuously | Kill/death/target state and resulting transition are visible under normal rules | 15–30 s plus mandatory delays |
| Objective-specific branch | Caster and required spike/site state ready; record possession, command and completion | Actor, objective state and completion/interruption are attributable | Full required sequence + 4–6 s |
| Expiry versus destruction | Separate clean natural-ending and deliberate-destruction cases only if both missing | Termination cause independently visible; no early round end | Natural lifetime + 4–6 s, or short destruction take |
| Enemy/team rendering or hearing | Two player POVs recorded simultaneously; one known use and controlled line of sight/distance | Same use appears in synchronized caster and receiver recordings | 10–20 s plus deployment; more perspectives only if needed |
| Audio detectability boundary | Fixed cue, controlled near/far or clear/occluded receiver positions; pilot then bracket | Positive and missed-cue opportunities tied to known casts and settings | Two short uses initially; adaptive bracket only if required |
| Ordinary scale/clutter transfer | Reuse match windows first; if absent, one representative use in normal capture profile with controlled distractor | Known use remains source-verifiable under changed rendering | 10–20 s plus effect; one changed factor at a time |

For ally healing/revival, an ally is required for that branch. A damaged self may
suffice for an actual self-targeted branch; verify the specific mechanic. For a
reliable adversarial damage/death setup, three participants may be needed: caster,
ally target and opponent. Use two only when they can establish all prerequisites
without changing the measured rules. Bots are suitable only after confirming they
exercise the same mechanic and rendering; range footage is not automatically a
substitute for match minimap behavior.

Record both relevant player POVs in one interaction where possible. Synchronize
with a shared observable event and estimate remaining offset/drift; file creation
time is not synchronization. Receiving-player evidence is evaluation truth for
that test, not a channel Reticle can assume exists in ordinary single-POV VODs.
Do not use a spectator view as a substitute for enemy/team player visibility.

A clean reference and one independent repeat at a different position/orientation
are an initial check, not a statistical guarantee. First reuse another existing
cast for the repeat. Add a new repeat only if missing or conflicting, then stop
collection when the specific distinction is resolved. Lifetime/range bounds require
appropriate boundary tests; two examples cannot establish a universal maximum.

### Initial request order after the corpus audit

1. Source review/grouping on the existing demos, including no-icon uses and the
   Omen cuts. This may resolve the largest gaps with zero new recording.
2. Missing solo alternate transitions or clipped endings, one ability at a time.
   Do not rerecord complete agent kits.
3. Shared target session for reactive utility and kill/death/ally-gated branches.
   Group by compatible participant roles and map setup; issue exact cards from
   the matrix, not a speculative request to demonstrate every interaction.
4. Simultaneous receiver POV for untested team/enemy representations and audio.
   Combine with step 3 when it adds no gameplay duration.
5. Minimal held-out ordinary-profile use only where the existing match corpus
   cannot validate transfer.

No unconditional new-footage request is justified by this design-only audit.
The likely supplemental categories are clear; exact abilities and total seconds
require inspecting which transitions the existing source actually contains.

## Implementation and acceptance

Add ability factors to the shared adjudication package, not an independent final
classifier. Proposed artifacts are `ability_definitions`, `ability_use_claims`,
`ability_entity_hypotheses`, `ability_properties`, `ability_coverage` and
`ability_capture_requests`, each separately versioned with source dependencies.

Reuse `ability_hud`, `ability_cast`, `ability_series`, `ability_reference`,
`audio_events`, the geometry/lighting readers and `track` motion definitions as
evidence providers. Treat `ability_corpus` onset/distance grouping and
`ability_extent` bearing grouping as competing baselines, not established truth.
Historical sample-count/lifetime/self-distance gates cannot universally exclude
short effects, objects present at capture start, or valid objects near the owner.

| Step | Deliverable | Gate |
|---|---|---|
| A | Read-only property coverage inventory and source window index | Every catalogue mode has explicit coverage status; legacy labels preserved |
| B | Use timeline from independent HUD/world/audio anchors | Reviewed cast/equip/cancel/end distinctions, including missing tray/no-icon cases |
| C | Entity grouping and property factors in the shared graph | Correct parent/child and phase relations on reviewed full-use windows |
| D | Appearance/audio galleries and conditional parameter fitting | Gains over current baselines on held-out uses, no self-training evaluation |
| E | Ordinary-match validation and targeted capture queue | Each requested second addresses a named missing discriminator |
| F | Execute accepted capture cards through existing ingest/review flow | Immediate success check, independent evidence, partial failures retained |

### Execution record

Milestone A landed as `reticle ability-coverage`. It is stored-data-only and
writes a source-hashed bundle under `analysis/ability-coverage`: definitions,
demo sessions, source windows, property coverage, conflicts and a manifest.
It preserves legacy label coordinates and does not modify source evidence.

First real run on 2026-09-09: 121 definitions across 29 agents, 28 tagged demos
(1,199.0 seconds), 197 property-linked source windows, 1,210 coverage rows and
zero reference/slot or named-label conflicts. The source windows comprise 24
cached tray-cast candidates and 173 human ability labels. Eighteen abilities have
human-supported identity and observation coverage (36 property rows); another 65
property rows have weak tray-cast support. The remaining 1,109 are explicitly
`not_exercised`, not negative conclusions. All 52 manifests are hashed because
the demo set and tag-derived agent identities depend on that inventory.

These are coverage counts, not accuracy measurements. The historical 119-drop
census is larger than the 24 current cached windows; milestone B must recompute or
materialize use timelines without treating the historical prose as evidence.

Milestone B landed as `reticle ability-timeline --materialize`. The materializer
uses the existing tray reader and writes reader-hash-keyed caches; ordinary timeline
rebuilds then read stored evidence only. Each drop becomes a bounded use claim with
unresolved commit/activation/mode-transition/end semantics, source roots, suspect
state, temporal label candidates and available audio references. Equivalent rows
from old and current reader caches collapse into one game-event candidate while
retaining both evidence roots; different interpretations remain separate conflicts.

First real run on all 28 demos: 127 distinct use claims across 27 sessions, 94
clean and 33 suspect, split C=33, Q=33, E=35, X=26, with zero conflicting cache
interpretations. The Brimstone demo produced no tray claim; absence remains
uninformative. Normalized agent tags also fixed `kayo` failing to reach catalogue
identity `KAY/O`. Source-linked audio cuts match four claims and remain reference
availability rather than independent recognition. The current reader result
supersedes the historical 119-drop prose for inventory purposes; it is still a
candidate count, not source-reviewed use accuracy.

Milestone C landed as `reticle ability-entities`. It reads stored evidence only and
writes `component_claims`, `entity_hypotheses`, `properties` and `review` beside the
timeline it consumes. Grouping offers competing alternatives -- a null hypothesis that
the use has no observed minimap child, onset/distance groups, and bearing groups for
abilities the parameter rules call extending -- and every multi-component group carries
`grouping_resolved: false`. Human component identity supports a parent edge; it never
promotes a group, because naming a component does not prove two components are one
physical entity.

First real run: 1,410 components against 127 use claims, 939 candidate parent edges of
which 21 are human-supported, 806 entity hypotheses (127 null, 672 onset, 7 bearing),
3,007 property claims and 279 unresolved review windows. The parameter rules are written
as `domain_hypothesis_needs_patch_validation` and are not fitted values.

Cross-referencing the human label channel against the use channel found two gaps, and
neither is repaired by widening the parent window. First, 146 of 449 ability labels never
joined a detector candidate on the exact source coordinate, so milestone C had been
dropping them silently; 88 of the named ones are the Deadlock, Omen and Reyna labels in
the two real matches `a06f04a0059f` and `5822b6646448`, which have no candidate file at
all. A label the detector never reproduced is still a human observation, so labels now
become components in their own right with `origin: human_label`; the exact-key join is
kept rather than loosened, so detector corroboration stays distinguishable from a label
standing alone. Second, `79a706a7ce4c`, `d95cfad5693a` and `eb10db50b1fb` carry 19 named
Cypher labels but are not tagged `ability-demo`, so the timeline never reads them and no
use claim can exist. That is milestone A's inventory to correct; milestone C only reports
it as `no_use_claims_in_session`.

An unparented component therefore records why: 130 `no_use_claims_in_session`, 289
`outside_parent_window` with the nearest same-ability delta stored so the width question
stays answerable from data, and 4 `only_contradicted_parents`. A component a human called
clutter is answered rather than orphaned, which removed 59 components from a queue they
did not belong in. Orphan clusters raise their own review windows -- 155 of the 279 -- so
the queue is not biased toward the sessions where the tray already fired.

129 of the 150 human-named components still have no supported parent. That is the gate
measurement for milestone C and it is not yet passed: the reviewed full-use windows
needed for correct parent/child and phase relations are queued, not answered. `.step`
parsing also treated the reader hash in `demo.step0.5.84229831.json` as part of the
sampling interval; that is fixed and covered by a test.

Milestone D landed as `reticle ability-gallery`. Galleries are per `(ability_id, phase)`
over `pre`/`onset`/`early`/`sustained` bins, never one average template per ability.
Parameters are fitted conditioned on each identity alternative: origins across every
member with their spread, bearings as a resultant vector with circular SD so that 350
and 10 degrees do not average to 180, and lifetimes that reach the clip end marked
right censored rather than reported as an expiry.

Two rules decide what may be scored, and they matter more than the classifier. Training
happens across sessions and testing within one, so a model cannot win by learning the map
or the capture profile; and every class must also occur in a training session, so the
reader is never scored against its own neighbouring frames. Under those rules the corpus
admits exactly one contrast -- `deadlock:sonic sensor` against `deadlock:barrier mesh`,
tested in each match in turn -- and the other ten are excluded with reasons recorded: 8
for `fewer_than_two_classes_in_one_session` and 2 for `class_occurs_in_no_other_session`.

The shuffled-label control had to change form. A 95th percentile is structurally 1.0 on a
two-class split, because a shuffled fit collapses both centroids toward the pooled median
and then scores perfectly whenever they happen to fall in the right order, which is about
half the time. No observed score could ever clear it. The permutation p-value -- the
fraction of shuffles reaching the observed score -- states the same caution without that
degeneracy, and a test pins the degeneracy so it cannot come back.

Balanced accuracy is the reported score. The majority prior reaches 0.9057 accuracy on
`a06f04a0059f` and 0.7188 on `5822b6646448` while being useless; both sit at 0.5 balanced.

The corpus turned out to be split so that appearance features and held-out evaluability
are disjoint. Detector scalar summaries -- area, aspect, colour fraction -- exist only in
the demo sessions, where every ability appears once and nothing can be held out. The two
real matches that do support a held-out split have no ability candidate file at all, so
they carry no scalar features. The scalar baseline this milestone was meant to beat
therefore cannot be computed on the only contrast that exists, which falsified the
prediction logged for it. Series traces reach those sessions because `--from-labels` keys
on label coordinates and needs no candidate join; the two matches were decoded in a plus
or minus ten second window per query for that reason.

Audio remains a reference inventory and is not scored. All six source-linked cuts come
from one session and no other session holds a labelled use of the same ability with
decoded audio, so any score would be a template recognising its own training cast.

**Milestone D's gate is not passed, and the negative result is the finding.** With
series decoded for both matches, all 85 Deadlock components carry traces and 36 features
survive the shared-feature intersection. Testing on `5822b6646448` scores 0.5749 balanced
at permutation p=0.3085; testing on `a06f04a0059f` scores 0.4646, below the shuffled
median, at p=0.6368. Neither clears chance. Per-class recall flips with the direction of
the split -- 0.889/0.261 one way against 0.200/0.729 the other -- which is a classifier
tracking a session offset rather than an ability, and is precisely what the controls
exist to catch. Phase-binned temporal shape does not separate a Deadlock sensor from a
Deadlock wall across two matches on this evidence.

Two defects had to be fixed before that number meant anything, and both had been quietly
producing a wrong answer. `self_d` is NaN wherever the self track did not fit, and a
median over an array holding one NaN is NaN, so every trace feature was non-finite for
some example and the whole block was refused with a message blaming a missing feature.
Non-finite samples are now dropped as absence of evidence, matching what the series module
already says about failed fits. The refusal message now distinguishes an empty
intersection from too few classes, rather than asserting one reason for every refusal.

Milestone E landed as `reticle ability-capture`. Its first draft issued 406 cards asking
for 6,174 recorded seconds and 32 hours of total effort, which is the ability catalogue
enumerated rather than a set of demonstrated gaps, and the design forbids exactly that.
Three rules fixed it. A card is issued only where the corpus already holds a
disagreement. A dispute that lives on footage already recorded is review work, because
the design orders source review ahead of every request, and it escalates to a card only
when a reviewer records that the source cannot settle it. An ability nobody has observed
gets nothing at all, since absence of evidence is not a surviving alternative.

What survives is 8 cards and 120 recorded seconds, beside 997 review items that ask for
no recording whatsoever and 89 deferred requests that say why they are not being made.
Every card names its own discriminator rather than a generic one: seven abilities appear
in a single session so no session can be held out, while `cypher:trapwire` appears in
three but shares a session with only one other labelled Cypher ability, which itself
occurs nowhere else -- a different gap needing a different take.

Milestone F landed as the take log and `--record-take`. A take is appended and never
rewritten, and it never certifies itself: the operator's claimed success is checked
against evidence the take could not assert into being. For a transfer card that evidence
is whether the ability actually became held-out evaluable, which requires labelled uses in
the newly ingested session. A claimed success with no ingested session stays `unverified`;
one whose use was captured and labelled but still leaves the contrast unevaluable is
`partial`; only the structural change earns `verified`. A batch that failed partway keeps
its successful claims and records the failure reason, so only the failed step is redone.
Exercised end to end with a deliberately unbacked claim, the flow refused it and returned
`partial`, and the synthetic take was then removed rather than left in the store.

Measure use identity/owner precision and recall, unknown coverage, grouping
over-merges and splits, entity false positives/misses per use, phase and termination
accuracy, timing interval coverage/width, and geometric error at supported units.
Separate cast detection, minimap representation recall and world-effect inference.
Evaluate event-level performance, not repeated-frame counts. Report per-family and
per-perspective transfer; preserve open-set errors and uncastable opportunities.

Measure property coverage gained per new recorded minute, usable-take fraction,
redo/setup/review time, decoded seconds and compute cost. Synthetic fixtures test
grouping mechanics; they cannot certify ability rendering. Ablate identity anchors,
temporal constraints, visual features and audio independently. Inspect consensus
and no-detection cases as well as disagreements.

The completion criterion is a visually checkable ability timeline with supported
properties and explicit gaps, plus the smallest justified capture queue. It is
not a populated table of guessed parameters or a claim that all solo behavior
transfers to a live match.

## Entity phases: an ability transforms, and stays itself

Added 2026-09-09, after the player read a dim Deadlock sensor off the labelling pass:
*this is a phase shift of the ability conditioned on other game state. The
ability does not move, it transforms. This is a general pattern that I had hoped
to capture and thought we already had.*

It was not captured. This document said "phase transitions" once, in section 4,
as one associating cue among several. `ability_timeline` carries unresolved
transition alternatives for the CAST. The gallery's `pre/onset/early/sustained`
are time bins relative to an observation and its own limits say they are not
lifecycle phases. Nothing modelled a deployed entity changing state and
remaining one entity, and two consequences were live in the pipeline:

* onset-and-distance grouping keys on a fresh appearance, so a device that dims
  reads as a NEW object at the same place;
* an interval that stops when the bright pixels stop reports a destruction that
  did not happen. That is a third termination story, and the capture matrix
  offers only expiry and destruction.

`reticle ability-phases` implements it from stored series alone. An entity holds
an ordered list of phases; a phase is an interval plus an appearance mode; a
transition between consecutive phases carries candidate causes from a closed
set, and is flagged when none of them has evidence:

    owner_death            an ally died near the transition   killfeed
    owner_left_radius      REVERSIBLE -- Killjoy, maybe Chamber   needs owner track
    owner_returned_radius  the reverse of it
    triggered_activation   Vyse's vines becoming a circle
    destroyed / expired    endings, with and without a cause

That mirrors the ORIGIN EVENT model in `prototypes/CLAUDE.md`: a birth comes
from a closed set, so an unexplained birth is a flag rather than a silent row.
A transition is the same claim applied to the middle of a life. Two rules are
structural and asserted by tests -- a phase change never creates a second
entity, and a lifetime spans every phase rather than ending at a boundary.

First run over the 142 named entities that carry a series trace: 81 transform,
174 transitions split 90 live-to-dim and 84 dim-to-live, 14 resolved by a
supporting ally death and **160 unexplained**. The unexplained majority is the
honest state rather than a defect: the dim-to-live direction has no cause this
corpus can currently supply, because the radius test needs an owner track that
does not exist for a non-local player, and that cause is listed as `unavailable`
with its reason rather than omitted.

Segmentation had one defect worth recording, caught by reading the first real
output: absorbing a sub-threshold flicker left the runs either side of it
adjacent and in the same mode, and appending regardless turned one steady sensor
into four phases and reported `live->live` as a transition. A transition between
two runs of one mode is not a transition, and a test now asserts it cannot recur.

**Still owed: grouping does not consume this yet.** Milestone C continues to
group on onset and distance, so it can still split one transforming entity in
two. The phase records exist beside it rather than inside it, and joining them
is the next structural step.

## Sources and mechanics policy

Repository findings above come from the current manifests/assets and the owning
prototype documentation; historical measurements are identified as such.
The cached ability catalogue includes third-party mirrors and must retain their
provenance rather than being described as wholly official.

[Riot's Sage page](https://playvalorant.com/en-us/agents/sage/) describes resurrection
as acting on a dead ally, supporting the need for a prerequisite-specific capture.
[Riot's Skye page](https://playvalorant.com/en-us/agents/skye/) describes controlled
Trailblazer movement and Guiding Light steering/hit confirmation, illustrating
why movement and target-response evidence need separate coverage rows. These
pages are examples, not a full patch-specific mechanics specification. Verify
numeric limits and alternate branches for the recording's patch before using
them as hard constraints.
