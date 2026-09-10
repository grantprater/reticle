# Minimap appearance matching: design and implementation plan

Date: 2026-09-09, extended 2026-09-10 to every icon the widget draws. Status:
Step 1 measured and shipped. Step 2 is CLOSED as a measured negative result:
both its standalone and its joint appearance/geometry paths are implemented and
measured, and neither is wired into the reader. Steps 4-6 remain proposed.

**The 2026-09-10 extension changes what this plan is for.** It fitted ONE icon
family and treated the rest of the widget as background, and the self reader's
first accuracy figure says that is the wrong axis: 8.13% of its accepted
positions are a different OBJECT, and the largest single confuser has no reader
at all. Fitting the self icon better cannot answer *which yellow thing is
this*. So the plan now carries an inventory of every icon that can be taken for
another, a contract each of their readers must meet, and an order over them.
The glyph track (G1-G5) runs before Step 3 and G1 is the spike.

Step 1 result: `minimap-0.5.0` feeds fitted `self_icons` to `pick_self`, accepts
a supported centre with unknown bearing, requires opaque-slab support and has no
blob fallback. On the frozen one-session gate, agreement moved from
0.9363/0.9438/0.8816/0.9085 to 0.9917/0.9885/0.9849/0.9939 at 15/10/5/2 Hz.
Eligible coverage is 0.7237 at native and 0.7101-0.7301 at candidate tiers, so
the expected roughly 27.7% refusal remains. `fidelity-0.2.0` reports coverage
separately; this consistency result does not establish independent accuracy or
sufficient coverage. Measurements live in the store's
`notes/appearance-step1-{baseline,after}.json`.

## Purpose and scope

Recognize minimap portraits, glyphs, tinted regions and animations by fitting
their appearance over the map. Estimate centre, geometry and bearing together
where they share evidence, while preserving unknown identity, owner and phase.
The immediate target is the confuser inventory below: naming the other things
the self key holds. The self-ring fragmentation that opened this plan is fixed
and shipped in `minimap-0.5.0`.

This extends [MINIMAP_DETECTION_PLAN.md](MINIMAP_DETECTION_PLAN.md) and implements
the visual hypothesis-testing portion of
[ABILITY_ENTITY_INFERENCE_DESIGN.md](ABILITY_ENTITY_INFERENCE_DESIGN.md).
Those documents own temporal association, origins, attribution and collection.
[PIPELINE_REVIEW.md](PIPELINE_REVIEW.md) continues to own P0-P5 ordering. This
plan does not authorize skipping the remaining P3 gates or starting P4/P5.
Stage 02 remains deterministic: geometry, signal processing and mined exemplars.

## Evidence and corrections to carry forward

- The current notes report that ring fits improve cross-rate self agreement,
  but refuse 1975/7131 frames (27.7%). Agreement is a consistency measurement,
  not independently established position accuracy. Retaining only easy frames
  cannot establish success.
- Thin colour rings are vulnerable to 4:2:0 subsampling; the roughly 11-pixel
  portrait interior retains full-resolution luma structure. This motivates an
  appearance channel, not a claim that luma solves every icon.
- `prototypes/minimap_portrait.py` reports 93.0% nearest-exemplar versus 70.4%
  median-template recognition on provisional labels derived from clustering.
  These are exploratory results, not independent recognition accuracy. Preserve
  multiple appearance modes and test that choice on independently reviewed uses.
- The domain notes specify upright agent portraits and rotating facing geometry.
  Do not rotate an entire portrait crop to synthesize facing changes. Other glyphs
  may rotate as a whole; the transformation belongs to the representation.
- Normalized correlation can amplify nearly flat patches into apparent matches.
  Keep absolute contrast and residual evidence; a question-mark glyph needs its
  own appearance family rather than a forced agent assignment.
- Region representations can cross walls, cover icons, and change family during
  deployment. A universal floor mask, circle fit or immutable representation
  family would exclude valid ability evidence.

## The occluder inventory

### `self_mask` is not a self key

**Measured 2026-09-10, no decode, `prototypes/key_collision.py c40d950031bb`.**
The self-fit label sheets are `INTER_NEAREST` x5 crops with no colour
transform, so every fifth pixel is a source pixel and the player has already
said what each position is. The share of a 5 px disc that `self_mask` keys,
by the player's own answer:

    answer            n     self key mean / med    ally key mean / med
    local_player    179       0.074   0.062          0.007   0.000
    spike            10       0.112   0.117          0.006   0.000
    teammate          3       0.070   0.099          0.004   0.000
    nothing           3       0.074   0.086          0.000   0.000
    coincident        7       0.053   0.012          0.000   0.000

**The spike fills the self key harder than the player does**, and this is a
lower bound on the collision: the disc is centred on the accepted fit, the
player's key is an annulus at r 6-9 px and the spike's is filled, so the
geometry of the test favours the player. Shrinking the disc widens the gap the
way an annulus predicts -- at r = 4 px the player's median falls to 0.000 and
the spike's holds at 0.133 -- which is prediction 1 below, seen through the one
band the annotation ring leaves clear. With the site paint already measured
at 19.85% of self fits against 10.26% of ally fits, `self_mask` is a YELLOW
key holding at least five things -- the player's ring, the dropped spike, the
planted spike, the carried badge, and the plantable-site paint.

That is the general shape, not a fact about yellow. A key is a colour; an icon
is a colour plus a shape plus a motion law plus a lifetime, and every reader
built so far has stopped at the colour. The inventory below lists what that
leaves unresolved.

The measurement was not predeclared in `notes/predictions.jsonl`. It re-reads
stored labels and proposes no detection, so there was nothing to bias; the G1
predictions below are predeclared, and they are perceptual.

### Every icon the widget draws

Families use `round_lifetimes.NAME_KIND`; the parameter triple is the entity
model's `origin` / `bearing` / `extent`, as `ping.py` states it.

| Icon | Key | Shape, parameters and evidence | Read today | Independent witnesses | Taken for |
|---|---|---|---|---|---|
| Local player | self (yellow) | Ring + upright portrait + facing lobe. moves / present / none | `minimap-0.5.0`, `self_icons` | roster alive, pings, killfeed (blocked on self identity) | -- |
| Teammate | ally (teal) | Filled teardrop + portrait. moves / present / none | `ally_icons` | roster alive, chat spot lines | the player |
| Enemy | enemy (red) | Ring. moves / present / none. **Drawn only inside team vision** -- see the gate below | nothing in `reticle/`; `prototypes/enemy_detect_eval.py` and 300 labels | the drawn light, killfeed, chat spot lines, enemy roster alive | the player, a death mark |
| **Dropped spike** | **self, yellow (measured)** | Filled glyph, no ring, no portrait. **Slightly LARGER than carried, with one edge pointing straight UP.** fixed / absent / none | **nothing** | the drawn light where it is enemy-side; the carrier's death in the killfeed; the announcer's *spike down <location>* | **the player** |
| **Carried-spike badge** | **self, yellow -- ally-carried too** | The same glyph inverted: **slightly SMALLER, one edge pointing straight DOWN**, beside the carrier's portrait, 3.2 px to its bottom left. follows a player / absent / none | nothing | it moves with a player icon, which a dropped spike never does | the player's own centre, by a fixed offset |
| **Planted spike** | **self, yellow (measured)** | Compact glyph, dark core, on site paint. fixed / absent / none, plant to defuse or detonate | HUD only: `rounds.spike_planted`, and `prototypes/plant_spike.py` unwired | the HUD spike graphic replacing the clock; the site letter; the beep interval | the player |
| Death mark | team colour (unknown) | X glyph. fixed / absent / none, short life (unmeasured) | nothing; `world:x_mark` in the paint bank | **the killfeed names owner and time** | the player, an enemy |
| Last-known mark | team colour (unknown) | Question-mark glyph. fixed / absent / none, short life (unmeasured) | nothing; `world:question_mark` | that enemy's last read; chat spot lines | an enemy |
| Ping | per type | Glyph, no growth phase. fixed / absent / none, **7.0 s or 10.0 s exactly** | `ping-0.1.0` | the player who placed it, at their position | an ability icon |
| Ability icon | per agent | Disc or glyph. fixed / absent / none, per-ability life | `prototypes/ability_disc.py`; `ability` and `ability_paint` labels | killfeed ability icons (owner + time, on kills only), HUD ability tray charges | the player, a ping |
| Ability region | per agent | Smoke, wall, mesh. fixed / absent / **extent** | Step 4, proposed | as above | background; it OCCLUDES rather than confuses |
| Buy-phase barrier | barrier | Line. fixed / absent / extent, buy phase only | `store/barriers`, two maps | the round phase | background |
| Audio ring | unknown | Ring; the spike's detonation radius | nothing; `world:audio_ring` | plant state | an ability region |
| Site paint | **self (measured)** | Static map art, not an icon at all | `minimap.site_mask`, from the static map, no decode | it cannot move, and it is in the static median | **the player** |

Rows in bold are the ones inside the self key, which is why the spike goes
first. Map lettering and widget furniture are already excluded by the
opaque-slab support rule in `icons`.

### The spike, as the domain states it

Recorded 2026-09-10. These are game rules, not measurements, and they are what
G1 is designed against.

- **It is yellow in every state, including carried by a teammate.** The ally
  key holds no spike. So the whole spike lives in the self key, which is what
  makes it the self reader's confuser and nobody else's.
- **It INVERTS on pickup.** On the ground it is slightly larger with one edge
  pointing straight up; carried, slightly smaller with one edge pointing
  straight down. **The transition takes one frame.**
- **A round may hold unboundedly many pickups and drops.** So the spike is ONE
  entity alternating between two states, not a new entity per drop, and a
  lifetime model that opens a track on each appearance will miscount it. At
  2 Hz the transitions are unobservable, so state is read per frame and never
  from a transition.
- **The enemy team has no carried state on our minimap.** An enemy carrying
  the spike draws nothing. The icon exists only while the spike is on the
  ground.
- **An enemy-side spike on the ground obeys the vision gate below.** Absence is
  therefore not evidence of possession: no glyph may mean carried, or may mean
  nobody is looking at it.
- **A carrier's death drops it, and the announcer says *spike down
  <location>*** -- mid, A, B, C, spawn and others. That is an audio event with
  a coarse position, and it is the only witness the dropped spike has.

Two questions the domain has not answered, worth asking before G1 is scored:
whether an own-team spike on the ground is exempt from the vision gate, and
whether a reveal ability that shows an enemy also shows a spike on the ground.

### The vision gate on enemy-team entities

**An enemy-team entity is drawn on our minimap only where our team can see
it.** That is a game rule rather than a tendency, and it applies to the enemy
player icons and to the enemy-side spike on the ground alike. The repo already
uses the weak form of it -- *an ally icon with no lit pixels beside it is not
an ally* is a standing constraint in `../CLAUDE.md` -- but for allies the light
is only a correlate. For enemy-team entities it is a NECESSARY CONDITION, which
is a far stronger gate, and nothing consumes it today.

**The instrument is the DRAWN light, not the reconstructed cone.**
`reticle/lighting.py` classifies each floor pixel against the map's own
`lo_gray`/`hi_gray` resting states, so it reads what the game actually shaded.
`reticle/cone.py` raycasts a wedge instead, and its area over-claims by roughly
3x against what the game draws -- a gate that wide refuses almost nothing,
which is why the gate was fair to leave out while that was the only instrument
available. The drawn light removes that objection. The collective-viewcone
backlog entry records the same thing from the other side: *the interior-
appearance invariant is not wired to anything. The area exists; nothing
consumes it yet.*

How the gate is allowed to be used:

- **It refuses, it does not confirm.** An enemy-team detection on unlit floor
  is a false positive. A detection on lit floor is merely permitted.
- **Absence outside the light says nothing.** The gate cannot raise recall and
  must never be read as one, or coverage becomes biased by where the team was
  looking.
- **It has an exception class, and the exception is already a backlog entry.**
  A reveal ability shows an enemy without our team having sight of them -- *A
  RECON DART PULSE is a legal origin for an enemy appearance*. So an unlit
  enemy icon is a refusal OR a reveal, and the two are separated by the ability
  channel, not by the light. Store the disagreement; do not delete the
  detection.
- **`lighting.py` is not ground truth.** Its own docstring names the failure:
  any map object whose resting state is the bright one reads permanently lit,
  and the mechanical doors on Ascent and Lotus still do. Scoring a channel
  against it and calling the result precision implies a truth that is not there.
- **Unknown light is never counted as unlit.** That rule is already in
  `MINIMAP_DETECTION_PLAN.md`, and it is what keeps this gate from refusing on
  pixels that simply could not be classified.

**The safe direction of error is the opposite of the entity model's.**
`minimap-entity-model.html` argues the collective viewcone should be built to
UNDER-claim, because its enemy-half invariants are about disappearance: an area
that is too large says we could see a place we could not, so a legitimate
vanishing reads as an error and the read is discarded. This gate runs the other
way. It refuses DETECTIONS on unlit floor, so an area that is too large
under-refuses and merely wastes the gate, while one that under-claims deletes
real enemies. Both instruments are used by both, so neither error direction can
be tuned away for one without hurting the other -- which is a reason to keep the
gate as a stored disagreement rather than a silent filter, and to report what it
refused alongside what it kept.

This gate is a prerequisite of G3 and it is what makes the enemy channel
cheap: the hard part of reading a red ring off a translucent widget is the
false positives, and a necessary condition removes them without touching the
detector. It is the `ally_icons`-against-the-roster precedent again, on a class
where the constraint is a rule rather than a correlation.

### What each new reader must carry

A reader joins this inventory when it does all five. The first four are the
repo's standing rules applied to a class rather than to a channel; the fifth is
what this plan adds.

1. **Name its key, and what else is in it.** `key_collision.py` is the cheap
   version wherever labels already exist.
2. **Declare `origin` / `bearing` / `extent` and a lifetime**, in the entity
   model's own vocabulary, before fitting anything. `ping.py` is the worked
   example: its identity is a glyph and a constant lifetime, and that is what
   made it cheap.
3. **Name at least one independent witness, and store the disagreements.** The
   witness column is the standing cross-reference rule made specific. A class
   with no witness -- the dropped spike today -- is the argument for building
   it first, not for skipping the requirement.
4. **Be scored on exhaustively painted frames**, `prototypes/paint_icons.py`,
   whose `WORLD` bank already holds `world:spike`, `world:x_mark`,
   `world:question_mark` and `world:audio_ring`. Candidate-anchored labels
   cannot measure precision, and they bias recall toward one detector's output.
5. **Select no threshold on `c40d950031bb` or `ff636d173b07`.** Those carry the
   frozen self-fit labels. Measuring on them is fine; choosing a cut from them
   makes the test set the training set.

### The draw order is unknown, and it is measurable

`BACKLOG.md` records that neither the repo nor the player knows whether the
widget has a priority between players, the spike, abilities and marks. It is
not derivable from stored data, because nothing stores what was underneath --
but it is derivable from the VIDEO, and the instants are already named. The
seven `coincident` labels and the ten `spike` labels are the frames where two
things share a place. Step over one at native rate; the surviving glyph says
which draws on top.

The answer is a constraint either way. If a player always draws over the spike,
a fit that is a spike proves the player is elsewhere. If not, it proves
nothing, and the co-located case stays ambiguous by construction -- which is
what `8 = coincident` exists to record.

## Icon-class order of work

Ordered by witnesses unblocked, per the bootstrapping floor in
[ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md), rather than by defect size.
These interleave with the numbered steps below: **G1 runs before Step 3**,
because Step 3's directional geometry is one more improvement to the self
reader, and the self reader's ceiling is set by G1.

| Step | Class | Why here | Promotion gate |
|---|---|---|---|
| G1 | The spike, all three states | The largest labelled confuser, inside the self key, with no witness anywhere | Stated below |
| G2 | Death and last-known marks | The killfeed already names owner and time for a death mark, so the witness exists before the reader does | Presence and position against painted frames; every mark reconciled against a killfeed entry, or held as a disagreement |
| G3 | Enemies, **gated on the drawn light** | 300 labels and a prototype exist; it closes the last player-shaped confuser and feeds the roster and killfeed channels. The vision gate is a necessary condition here, so it removes false positives without touching the detector | Precision and recall on painted frames, not on the existing candidate-anchored labels; every unlit detection resolved as a refusal or a reveal and stored either way |
| G4 | Ability icons | Owner comes free on kills from the killfeed ability-icon channel; identity needs mined templates | Held-out casts; ambiguous ownership preserved rather than forced |
| G5 | Regions and animations | The existing Steps 4-5 | As stated there |

Re-measure the self reader's accuracy after each of G1-G3. An accuracy figure
from before a neighbour existed does not carry forward.

### G1: the spike

**Three states, one glyph family, and they do not share evidence.** The state
that is easy has a witness and is not the confuser; the state that is the
confuser has no witness. Do not wire the easy half and call the entry closed.

    state      confuses the self reader?   witness available
    planted    yes, measured               yes: the HUD graphic, already built
    dropped    yes, measured, and it is    the announcer's "spike down <loc>",
               where the self fit drifts   and the drawn light when enemy-side
    carried    no -- it IS the player,     yes: it moves with a player icon
               offset by 3.2 px

**The orientation flip is the whole discriminator, if it survives our scale.**
Ground and carried are the same glyph inverted, so one per-frame shape test
separates a fixed object from a badge on a player -- no association, no
temporal reasoning, no second channel. Nothing else in this inventory is that
cheap. Everything below is about getting the glyph into a form that can be
asked the question.

Built and not wired, to check before writing anything new:

- `prototypes/plant_spike.py` detects the plant POSITIVELY off the HUD spike
  graphic and bisects for its instant. `rounds.spike_planted` still infers a
  plant from a run of unreadable clock.
- `icons` already returns `inner`, the inner-disc fill fraction, and
  `self_fit_eval.py --features` already caches it per labelled fit. Nothing
  prints it and nothing uses it.
- `paint_icons.py` carries `world:spike` in its bank, and no frame has used it.
- `prototypes/refusal_clip.py` renders the annotated runs that found this.

**An already-cached feature the shipped gate never binds on.** Recomputed from
`notes/self-fit-features-c40d950031bb.json`:

    answer            n   inner median [p10-p90]
    local_player    178   0.000 [0.000-0.112]
    spike             9   0.156 [0.018-0.244]

The shipped `inner_max` is 0.25 and 100% of both classes pass it, so it refuses
nothing. Every labelled spike also sits below `cov` 0.35, so as a REFUSAL
`inner` is redundant with the arc-coverage gate already proposed: it catches no
spike that coverage misses. Its value lies elsewhere -- `inner` and `cov` are
uncorrelated on the player at r = 0.025, so a joint rule may refuse the same
spikes while keeping more real positions than coverage can alone. **Choose no
cut here.** These are the frozen labels; the cut is chosen on another session.

**RUN 2026-09-10, pre-registered, and it failed on the instrument.** Three
predictions were logged in `notes/predictions.jsonl` -- that the flip is
readable at this scale, that the ground glyph is larger, and that a carried
glyph is adjacent to a player icon. All ten spike-labelled instants on
`c40d950031bb` were sought at native rate and read as raw widget pixels with no
annotation on them. **None of the three could be scored, because `self_mask`
does not deliver the glyph as an object:**

    keyed components within 8 px of the labelled spike   1 to 5
    positions where it is a single component             2 of 10
    largest component                                    8-36 px
    nearest component to the fit centre is a 1-4 px speck 4 of 10

The glyph is plainly visible in the raw pixels at 0.712 scale, so this is a KEY
problem and not a resolution one: `self_mask` catches a broken rim and drops the
body. Suggestive, and not evidence: the largest component is a wide short bar in
five of ten -- 4x9 px three times, 6x10 and 6x12 -- which is what a flat
horizontal edge leaves behind. The keyed mass also sits ABOVE the fitted centre
on 6 of 10, so the ring fit is not centred on the glyph it accepted.

**So G1 is not built on `self_mask` connected components.** It needs the
glyph's own colour band or a masked appearance fit over luma, which is the
framework this plan already describes for portraits. Rebuild the three
predictions once the glyph arrives as one object.

Two further things that pass must supply, and neither is optional:

- **Per-case state truth.** The ten labelled positions record `spike` and not
  which state, so even a working reader has nothing to be scored against.
  An exhaustive paint pass with `world:spike` supplies it, split by state.
- **Frames spanning a pickup.** The flip is a one-frame transition and a round
  holds unboundedly many, so a window that catches one is the only place the
  two states are known to be the same physical spike.

Still to predeclare, unchanged by the run above:

1. A dropped spike does not move. Over its life its fitted centre stays within
   the fit's own error; the self icon's does not.
2. The planted spike is co-located with the HUD plant window and a site zone,
   so a minimap spike glyph outside a plant window is dropped or carried.
3. The carried badge sits at a fixed offset from a player icon, and the offset
   is the same for every carrier.
4. An enemy-side ground spike appears only on lit floor, per the vision gate.

Promotion gate: presence precision and recall on exhaustively painted frames
over at least two sessions, with the spike state reported separately; position
error at painted positions; the plant-window agreement in prediction 3 stored
as a disagreement when it fails rather than resolved; and a re-measured
self-reader accuracy on a session that is not `c40d950031bb`.

## Shared fitting framework

Each matcher proposes an explanation of observed pixels, with a bounded set of
parameters. Share background handling, coordinate transforms, reliability masks,
candidate scoring interfaces and provenance. Use specialized representations:

| Representation | Parameters and evidence | First method |
|---|---|---|
| Portrait | Upright exemplar, centre, supported HUD scale, visible interior | Masked luma residual/correlation with a contrast check |
| Directional icon or glyph | Centre, angle, extent, expected edge arrangement | Explicit angle bank with tolerant directional edge matching |
| Tinted region | Shape, position, angle, dimensions, tint and opacity | Background-composited region fit using interior and boundary |
| Repeatable animation | Spatial parameters, onset interval, phase | Phase-indexed exemplar sequence and constrained progression |
| Irregular animation | Extent, persistence, spatial and temporal statistics | Regional change/texture descriptors, only if simpler methods fail |

Conceptually minimize a robust appearance residual plus geometric and temporal
costs over valid hypotheses, including background-only and unmodeled clutter.
This is a proposed score, not a calibrated probability. Record component scores
and their dependence: luma, edges and a rendered residual from the same pixels
are not independent corroborating observations. Fit thresholds, score scales
and any weights on development data only.

### Background and sampling

Use geometry's `lo_gray`/`hi_gray` and lighting state where reliable. These are
grayscale references, not an existing clean RGB background or alpha matte. Region
colour fitting may need a separately versioned colour reference from eligible
observations; verify that source support before implementing it. Unknown lighting
or scenery behind the translucent void remains unknown background.

An initial region hypothesis can use `I_hat = (1-alpha) B + alpha C` inside a
shape, with a soft boundary; textured icons substitute an appearance for `C`.
This is an approximation to validate against capture pixels, not a claim about
the game's exact rendering pipeline. Bound tint/opacity freedom, compare against
illumination-only alternatives, and penalize excess flexibility. Do not optimize
an arbitrary per-pixel overlay that can explain any scene. Subtracting `B` alone
does not recover a background-independent translucent foreground.

Align map coordinates before comparing frames. Use shared decode passes and
actual timestamps. Reuse stored observations for subsequent scoring. Preserve
persistent differences from the map as well as inter-frame changes: a stationary
active effect may have zero frame difference. Do not let an adaptive background
silently absorb an active ability. Apply representation-specific visibility and
background reliability masks without deleting cross-wall support a priori.

### Portraits and bearing

Fit a shared centre with separate upright portrait and rotating ring/triangle
parts. Begin with multiple real exemplars and small translation searches at the
known widget scale. Add subpixel sampling only if measured centre errors justify
it. Avoid repeated rotations of an already tiny raster; when synthesizing
geometry, render from a stable source and sample once at capture resolution.

Start rotation search with an explicit angle bank, then refine supported peaks.
Choose angular spacing on development data relative to pixel displacement and
required bearing precision. Keep multiple peaks for symmetric or occluded shapes.
A readable portrait can establish centre/identity with unknown bearing.

Directional chamfer matching scores the distance from expected edges to nearby
observed edges, with orientation compatibility. Cap outlier costs for missing
arcs, but also score unexplained support/negative evidence so arbitrary clutter
does not win merely by containing many edges. Compare it with luma matching alone.
LINEMOD-style gradient orientation matching is an alternative if hard edge
extraction is unstable. Polar correlation is a later option for circular facing
geometry; centre error and interpolation at this scale may outweigh its benefit.

Candidate acquisition must include frames without a ring fit. Use existing fits
as proposals, then evaluate bounded appearance searches in eligible regions and
independently supported temporal neighbourhoods. A previous track may constrain
search, but cannot turn a missing current match into a fresh observed position.
Do not restore the fragmented-blob centroid fallback as an accepted icon.

### Regions and animations

Fit a small family of supported shapes (for example circle, rectangle, segment
or polygon), using both interior colour transformation and boundary support.
Do not infer exact ability identity from shape alone. Generic smoke-like regions
retain family identity until other evidence distinguishes the ability and owner.

For repeatable animations, preserve phase exemplars rather than average frames.
Match sequences with an unknown onset and physically supported phase progression.
Start with interpretable descriptors such as extent, radius, boundary brightness,
tint, expansion or sweep direction and pulse timing. Short sequence templates or
motion-history summaries are alternatives when phase snapshots are insufficient.
Missed frames advance elapsed phase; unrestricted time warping must not turn an
unrelated sequence into a match. Clip boundaries and hidden onsets are censored.

Pulses can belong to one continuing entity. A moving icon can transition into a
deploying animation and then a persistent region. Preserve representation phase
separately from entity identity; leave sibling/grouping alternatives unresolved
when one cast produces multiple components. Do not infer lifetime or new casts
solely from visual disappearances and reappearances.

For irregular textures, compare temporal statistics rather than exact pixels.
Dynamic-texture methods are a deferred escalation, not the first implementation.
Any future learned matcher requires an explicit architecture decision about the
Stage 02 no-model constraint; it is outside this implementation plan.

## Observation and gallery contract

Extend existing appearance/gallery and observation contracts after inspecting
their owning modules; do not introduce a parallel entity store. Proposed records
must carry:

- Source/session/frame or time interval, coordinate transform and producer version.
- Representation family, exemplar/gallery revision and background dependencies.
- Observed support, centre/extent alternatives, angular peaks and phase alternatives.
- Component residuals, usable evidence fraction and rejection/unknown reasons.
- Separate support for existence, identity, centre, bearing, phase and owner.
- Links from later adjudication to raw observations and independent HUD/audio cues.

Scores remain uncalibrated until validated. An ambiguous best match or weak
contrast can refuse identity without discarding supported geometry. Keep raw
observations separate from temporal and origin adjudication.

Mine candidate exemplars from independently anchored use windows and forced
correspondences, not only detector-selected clean frames. A forced correspondence
can establish association under verified conditions; it does not independently
name an agent or prove that a sole candidate is a real icon. Keep label provenance
explicit and never seed player answers from clustering. Split whole tracks/uses
and sessions before mining; adjacent frames must not leak between gallery and test.

## Implementation sequence and gates

Each step is a bounded increment. Log falsifiable predictions in the store's
`notes/predictions.jsonl` before a perceptual experiment, inspect source images,
and measure the existing baseline. On the first failed perceptual approach, build
or use the player review tool under the `labelling-pass` skill. No perceptual
experiment was run as part of writing this document.

| Step | Work and likely integration point | Required evidence before promotion |
|---|---|---|
| 0. Freeze evaluation inputs | Existing fidelity windows plus disjoint development and held-out sessions; existing source review tools | Independent labels/provenance, eligible-frame denominators, ring-refusal subset, baseline errors and runtime |
| 1. Established 2026-09-09 | `reticle/minimap.py` and `pick_self` callers use `self_icons` without blob fallback; `fidelity-0.2.0` reports coverage | Consistency and refusal reproduced as recorded above; independent centre accuracy and coverage remain Step 2 gates |
| 2. Closed 2026-09-09 | Measured in `prototypes/`; nothing wired. Appearance-only failed tier transfer, joint appearance/geometry failed coverage | Both required comparisons ran. Precision was recoverable; the answerable share of refusals was not, so no predeclared budget was met |
| 3. Add directional geometry, AFTER G1 | Shared-centre angle search, then directional chamfer if needed; existing bearing/overlay path | Reviewed centre and bearing error, angular ambiguity, overlap and no-icon negatives; improvement beyond appearance-only baseline |
| 4. Add region representation | Existing ability observation path, reliable background references and bounded tint/shape fits | Held-out static/expanding regions; geometry and presence accuracy; illumination/confuser tests; ambiguous ownership preserved |
| 5. Add phase sequence matching | Existing appearance-state and lifecycle contracts; timestamped phase gallery | Phase/order errors, onset intervals, pulse grouping, missed-frame and occlusion cases; benefit over independent frame matching |
| 6. Integrate and gate | Existing reader CLI, annotated overlay, capability/provenance checks | Real-command replay and visually checkable sequences; held-out transfer, acceptable runtime and no silently lost eligible observations |

Steps 1-3 address the current P3 minimap defect first, and Step 3 now
follows G1: the self reader is bounded by the confuser, not by its own
bearing search. Steps 4-5 are subsequent
ability-reader increments governed by existing pipeline gates, not prerequisites
for fixing self position. Inspect owning modules before deciding new filenames or
schema migrations. Wire verified paths into actual readers; an isolated successful
prototype is not completion.

Step 2 source inspection uses `prototypes/minimap_self_appearance.py`. It renders
native-rate accepted fits and refused frames bracketed by nearby fitted centres;
its `--evaluate` mode compares the production descriptor's exposed luma channels
on a development interval before the frozen run. It does not label or change the
reader. Extend it rather than creating another one-off portrait experiment.

The resulting `prototypes/minimap_appearance.py` uses an 11x11 upright interior,
masks the self colour, exposes raw luma and the geometry background-midpoint
residual, and uses masked normalized correlation. Its causal recovery state
requires two consecutive, physically compatible ring fits to certify the newer
descriptor. A recovery never becomes a descriptor source, and widget absence
clears trust.

The broad 64-exemplar gallery failed on development data: luma/residual/mean
localized 69.34%/68.61%/70.07% of 137 bracketed refusals within 3 px, and its
wrong offsets remained confident. A recent fitted descriptor was much stronger.
The development-selected residual rule (score >=0.7325, contrast >=10) answered
76/137 opportunities at 97.37%. On the frozen native-rate windows it answered
111/198 at 99.10%, with 0.67 px median error.

That apparent win did not survive the reader's real temporal tiers. At
15/10/5/2 Hz the unchanged rule answered 20/45, 19/41, 8/16 and 2/13 available
forced brackets, but only 80.00%, 68.42%, 12.50% and 0/2 answers were within
3 px. Accepted wrong offsets still exceeded the fixed score threshold. The
descriptor was validated between adjacent native frames; at tier-sized gaps its
physical search disk expands while compositing and overlap change. Therefore the
standalone matcher remains in `prototypes/` and is not wired into `_MinimapPass`;
`MINIMAP_VERSION` remains 0.5.0.

### The joint fit, and why Step 2 closes

The table's required joint comparison then ran on the development interval
alone. `icons` gained an optional `separation_px` so a caller can ask for
PROPOSALS rather than detections, `--joint` scores appearance only at permissive
current-frame ring fits (`cov_min=0`, `inner_max=1`, slab support), and
`match_at` replaces the disk enumeration that `match_near` performs.

**It fixed precision and could not fix coverage.** Of 137 bracketed
opportunities, 97.92% of ungated answers were within 3 px at 1.00 px median
error, and every score gate at or above 0.1254 was exact over 27.74% of
opportunities. That is the confident-error population gone: a wrong offset must
now also explain self-coloured ring pixels, which an arbitrary disk position
need not. Against this, the predeclared budgets failed. A proposal lay within
3 px in only 57.66% of opportunities against a 60% bar, and the rule answered
35.04% against a 40% bar.

What caps it is availability, not scoring:

- 85 of 137 opportunities had no trusted anchor, because a refusal breaks the
  consecutive-fit pair and refusals arrive in runs.
- Where an anchor existed the path was nearly exhaustive. 51 of 52 anchored
  opportunities were offered a correct proposal, and the motion gate admitted
  all 51 -- it excluded none, so the reach floor is not the limit.
- Ceiling misses are displaced fragments, not other icons: 25 at 3-6 px, 26 at
  6-12 px, and NONE beyond 12 px. That displacement is the self portrait
  overlapping adjacent ally portraits, which is also what refused the ring.
- Deduplication costs 11 points of ceiling, 46.72% against 57.66%, because it
  keeps the best ARC rather than the fragment nearest the true centre.

The decisive number is the denominator. The joint path can answer 164 of 1594
drawn refusals (10.29%) before any accuracy gate, so at its own perfect
precision it moves eligible coverage about two points. Bracketed refusals are
themselves only 137 of 1594 (8.60%): the refusal mass is LONG RUNS, which
neither a bracket nor a recent template reaches. A
recent-template channel is structurally the wrong instrument for it, however
well it scores on the isolated refusals it can see.

Step 2 therefore closes. The frozen windows were never opened for the joint
rule, and `JOINT_RESIDUAL_SCORE_MIN` stays unselected so no threshold is chosen
after the fact. Step 3 inherits the useful parts: `match_at`, the permissive
proposal call. It does NOT inherit the overlap story that was written here:
that came from inspecting a contact sheet, and two later measurements refuted
it. Ally proximity lifts refusal only 1.2x-1.6x, and `prototypes/minimap_occlusion.py`
-- which names no occluder and so covers enemies, abilities, pings, the spike
and barriers alike -- finds foreign content near the self position at 1.06x on
refused instants against read ones. **Nothing is drawn over the icon when the
ring refuses.** The standing candidate is the self key's own screen-space
dropout over the upper rim, already measured over five sessions in
`BACKLOG.md`. Detailed
predictions and outcomes are in the store's `notes/predictions.jsonl`; artifacts
are `notes/self-appearance-step2-{frozen,tiers}.json` and
`notes/self-appearance-step2-joint-dev{,-proposals}.{json,png}`.

### Evaluation contract

Choose numerical acceptance budgets before tuning, based on the requesting
capability's tolerances and baseline. Existing cross-rate fidelity thresholds
remain regression checks, not a substitute for independent accuracy.

Report presence precision/recall and refusal coverage over all eligible frames;
centre error at reviewed positions; identity confusion including unknown and `?`;
bearing error and ambiguous/refused rate; region boundary/overlap error; phase,
grouping and onset/termination interval errors. Separate unreadable widget,
unknown background, overlap and ring-refused subsets. Track consistency/fragmentation
is diagnostic unless correspondences were independently reviewed.

Use whole held-out casts/sessions and ordinary no-event windows. Include lit/unlit
transitions, scenery bleed, neighbouring icons, pings, large overlays, low contrast,
occlusion, cancelled previews, clipped sequences and stalled capture. Where only
one use exists, it can supply an exemplar but cannot validate its own transfer.

Run ablations: appearance only, shape only, joint fit; background handling on/off;
single-frame versus phase sequence. Report matching time separately from decoding
and candidate count, plus end-to-end replay cost. Add focused tests for transform
composition, timestamps, uncertainty and provenance; synthetic images validate
those mechanics, not real recognition accuracy. Rerun the real CLI and relevant
existing tests before versioning/promoting a detector, and inspect the overlay.

## Technique references

These establish available methods; their suitability for Reticle is a hypothesis.

- [OpenCV masked template matching](https://docs.opencv.org/4.x/de/da9/tutorial_template_matching.html).
- [Liu et al., Fast Directional Chamfer Matching](https://pure.johnshopkins.edu/en/publications/fast-directional-chamfer-matching).
- [OpenCV LINEMOD implementation](https://github.com/opencv/opencv_contrib/blob/4.x/modules/rgbd/src/linemod.cpp).
- [scikit-image polar/log-polar registration](https://scikit-image.org/docs/stable/auto_examples/registration/plot_register_rotation.html).
- [Davis/Bobick temporal-template research index](https://www.cs.cmu.edu/~vsam/FREcached/vismod.www.media.mit.edu/darpa-vsam/index.html).
- [Quan et al., Dynamic Texture Recognition](https://openaccess.thecvf.com/content_iccv_2015/papers/Quan_Dynamic_Texture_Recognition_ICCV_2015_paper.pdf).
- [Cohen/Welling, Group Equivariant Convolutional Networks](https://arxiv.org/abs/1602.07576): future learned alternative, outside deterministic Stage 02.
