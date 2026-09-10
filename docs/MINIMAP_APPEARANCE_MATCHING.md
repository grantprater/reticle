# Minimap appearance matching: design and implementation plan

Date: 2026-09-09. Status: Step 1 measured and shipped. Step 2 is CLOSED as a
measured negative result: both its standalone and its joint appearance/geometry
paths are implemented and measured, and neither is wired into the reader. Step 3
directional geometry is next; Steps 4-6 remain proposed.

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
The immediate target is the self-ring fragmentation in `../NOTES.md`.

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
| 3. Add directional geometry | Shared-centre angle search, then directional chamfer if needed; existing bearing/overlay path | Reviewed centre and bearing error, angular ambiguity, overlap and no-icon negatives; improvement beyond appearance-only baseline |
| 4. Add region representation | Existing ability observation path, reliable background references and bounded tint/shape fits | Held-out static/expanding regions; geometry and presence accuracy; illumination/confuser tests; ambiguous ownership preserved |
| 5. Add phase sequence matching | Existing appearance-state and lifecycle contracts; timestamped phase gallery | Phase/order errors, onset intervals, pulse grouping, missed-frame and occlusion cases; benefit over independent frame matching |
| 6. Integrate and gate | Existing reader CLI, annotated overlay, capability/provenance checks | Real-command replay and visually checkable sequences; held-out transfer, acceptable runtime and no silently lost eligible observations |

Steps 1-3 address the current P3 minimap defect first. Steps 4-5 are subsequent
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
themselves only 137 of 1594 (8.60%): the refusal mass is LONG RUNS during
portrait overlap, which neither a bracket nor a recent template reaches. A
recent-template channel is structurally the wrong instrument for it, however
well it scores on the isolated refusals it can see.

Step 2 therefore closes. The frozen windows were never opened for the joint
rule, and `JOINT_RESIDUAL_SCORE_MIN` stays unselected so no threshold is chosen
after the fact. Step 3 inherits the useful parts: `match_at`, the permissive
proposal call, and the finding that overlap is the thing to model. Detailed
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
