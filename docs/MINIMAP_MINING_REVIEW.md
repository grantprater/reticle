# Minimap mining critique and revised design

Date: 2026-09-10. Status: proposal acquisition audited on baked geometry, its
misses inspected, and two complementary channels measured and wired. This review
supersedes the mining interpretation and next-step sequence in
`MINIMAP_APPEARANCE_MATCHING.md`, not its recorded history.

## First implementation result: proposal acquisition is below floor

`prototypes/proposal_audit.py` now evaluates the color-free residual proposer
against existing exhaustive `ability_paint` frames. It uses one-to-one matching,
reports painted regions separately, and distinguishes missing residual support,
area rejection, fragmentation, and displaced/claimed centroids. It disables the
miner's interval-frequency subtraction because selected evaluation frames are not
an independent background sample.

The pre-registered recall prediction was at least 80% per session. It failed,
and the baked-geometry rerun that the mixed-dependency correction demanded
changes nothing:

| Session | Frames / icons | Proposals | Recall | Precision | Misses |
|---|---:|---:|---:|---:|---|
| `a06f04a0059f` | 12 / 11 | 244 | 72.7% | 3.3% | 2 oversized components, 1 undersized support |
| `d95cfad5693a` | 12 / 48 | 515 | 77.1% | 7.6% | 8 oversized components, 3 displaced/claimed centroids |

a06 fell from 254 proposals to 244 and gained 0.2 points of precision; every
other figure is identical, and d95 is unchanged because it already read baked
geometry. **The retired per-session static contributed nothing this measurement
could see.** The earlier figures were wrong in dependency, not in value.

All 14 false negatives overlap residual components; none lack residual support.
Nine targets are fragmented. Reducing each connected component to one area-gated
centroid loses targets, and the next section says exactly how.

## What the misses actually are

Inspecting all 14 misses at 4x, against the pixels and the labelled residual,
found ONE failure shape. Twelve of the 14 sit on a component whose area exceeds
the band while containing **exactly one** painted icon. The component is the
icon welded to something with extent: a spycam's viewcone, a trapwire's line, a
neighbouring icon, or bright map structure. The welds are 1-2 px necks. So the
area gate is rejecting an icon for its NEIGHBOUR's size, and neither the margin
nor the area band is the defect.

Two facts about the residual mask follow from the same inspection, and both are
load-bearing:

* **An icon is a ragged RING, not a disc.** The mask is
  `grey < lo - MARGIN | grey > hi + MARGIN`, and an icon's mid-grey interior
  falls INSIDE the lighting band. The icon contributes its edges and encloses a
  hole.
* **A ring therefore has no distance-transform core.** Peak dt within the
  painted radius is 2.0-3.0 px for matched icons and 2.2-3.2 px for missed ones
  on d95, 1.4-2.8 against 1.0-3.2 on a06 -- indistinguishable, while 9-47
  map-structure maxima per frame share the range. Fill the enclosed holes first
  and the icon becomes the disc it is.

## Two complementary channels, measured

`proposal-audit-0.3.0` scores an acquisition POOL. Every channel proposes over
the same residual mask and the same area band, differing only in the mask
TOPOLOGY it asks the band about:

* `base` -- one area-gated centroid per residual component, the original;
* `neck` -- a 3 px opening that cuts the weld, then the same area band. Three px
  is the smallest element that severs a 2 px neck: a geometric floor, not a fit;
* `core` -- non-max-suppressed distance-transform peaks on the HOLE-FILLED
  residual. It asks where the mask is locally thick rather than how large the
  component is, so a viewcone welded to a spycam costs the cone, not the spycam.

| Channel | d95 recall | d95 precision | d95 candidates | a06 recall | a06 candidates |
|---|---:|---:|---:|---:|---:|
| `base` | 77.1% | 7.6% | 515 | 72.7% | 244 |
| `neck` | 97.9% | 19.5% | 249 | 72.7% | 187 |
| `core` | **100.0%** | **66.7%** | **72** | 45.5% | 111 |
| pool of all three | 100.0% | 6.0% | 836 | 90.9% | 542 |

On d95 the core channel is 9x the base channel's precision at perfect recall,
with 6 candidates per frame against 43 and a median centre error of 1.207 px
against 0.757 px. On a06 it collapses, and `base` is the only channel that finds
seven of that session's ten. `mine_icons.propose` therefore proposes the UNION,
`POOL = ("base", "neck", "core")` -- a union cannot lower recall, so the change
is monotone for a miner, and proposals per frame on `c40d950031bb` rise from
23.7 to 44.4, which mining tolerates by design. **Replacing `base` with `core`
is measured and declined**: one session's six distinct objects do not justify
dropping the channel the other session depends on.

One defect is worth recording because it nearly buried the result. The first
`fill_holes` passed `4` positionally to `cv2.connectedComponents`, where it
binds to `labels` rather than connectivity. The background stayed 8-connected,
leaked diagonally through every thin ring, and filled nothing. With
`connectivity=4` -- an 8-connected outline seals a 4-connected interior -- the
core channel went from 89.6% to 100.0% on d95 and 27.3% to 45.5% on a06, with no
threshold touched.

## The area band was fitted on players, and cost 17 points of recall

The cap was the other half of the acquisition failure, and independent labels
settle it without touching the audit's own frames. `minimap_dynamic` is a
different human pass with a different proposer; over 831 rows on three
scale-1.0 sessions, box extent -- a property of the drawn icon rather than of
any mask -- separates the families:

| Family | n | p25 | median | p75 | p95 |
|---|---:|---:|---:|---:|---:|
| player | 104 | 11 | 13 | 19 | 37 |
| ability | 123 | 22 | **24** | 25 | 32 |
| region | 78 | 26 | 27 | 29 | 38 |
| negative | 434 | 10 | 16 | 25 | 37 |

`ICON_AREA_REF`'s cap of 400 reference px is a disc **22.6 px across**, below
the ability family's median. The band had been fitted where the evidence was --
on players, at 13 px -- and then applied to a miner whose whole purpose is the
families with no detector. 500 is the knee of the curve: it bounds 82% of the
233 labelled icons against 14% of regions admitted, where 600 admits 62% of
them.

Raising it to `(10, 500)` was pre-registered and confirmed on every clause:

| | before | after |
|---|---:|---:|
| d95 `base` recall | 77.1% | **93.8%** |
| d95 `base` precision | 7.6% | 9.1% |
| d95 candidates | 515 | 523 |
| d95 fragmented targets | 8 | 3 |
| a06 `base` recall | 72.7% | 72.7% |
| union recall, d95 / a06 | 100% / 90.9% | 100% / 90.9% |

Seven of d95's eight `component_too_large` misses sat on components of 205-251
px against a cap of 203. So the audited attribution was right, the cap really
was losing them, and recovering them cost 1.6% more candidates -- a claim no
threshold tuned against these same frames could have made. Note also that the
extent labels are RIGHT-CENSORED at 40 px: they justify a floor under the cap
and say nothing about the top of the ability tail.

`prototypes/object_proposals.py` held a forked copy of the same constant at
(10, 400) and now imports the one definition.

## Why a06 cannot score this yet

a06f04a0059f is the reference `valorant-16x9-bigmap` widget, and its icons are
drawn several times larger than d95's. Its missed components run 1189-1417 px --
a disc 39-42 px across, at or past the extent labels' 40 px censoring boundary --
and the painter marked r=7 discs on icons whose drawn radius is 20-25 px, so the
matching radius is smaller than the icon and the hand-clicked point need not sit
near the icon's thickest place. Raising the cap therefore moved a06 not at all,
exactly as predicted. Until a06 is repainted with radii that match its widget,
treat its figures as a lower bound on acquisition and an upper bound on nothing.

Widen the painted truth -- more maps, more agents, an a06 repaint -- and
re-audit before selecting a single channel or moving to the descriptor.

These labels have little class diversity: a06 contains nine Sonic Sensor and two
Barrier Mesh marks; d95 repeats three Cypher devices and the self icon. Precision
measures candidate volume here and is low enough to constrain any additional
channel. The result refutes this proposer as the sole acquisition mechanism; it
does not establish inventory-wide performance or select a replacement.

## Recommendation

Keep mining as an instrument for discovering recurring visual patterns, and
evaluate a hybrid extraction pipeline under a small, explicit labeling budget.
Compare a fuller deterministic baseline with a fine-tuned YOLO detector before
committing to more bespoke detection work. Cleaner clusters alone do not establish
complete or correct entity extraction.

Separate candidate acquisition, visual-family discovery, instance association,
and semantic/lifecycle inference. Preserve the existing observation/adjudication
boundary, provenance, refusal behavior, and independent corroboration regardless
of which detector wins. Generality belongs in the shared evidence contract;
small icons, regions, directional geometry, and animations need not use one
representation or matcher.

## Evidence and limits

The review inspected `prototypes/mine_icons.py`, `object_proposals.py`,
`minimap_appearance.py`, the appearance plan, recorded mining outcome, and
production lifecycle interfaces. Read-only `doctor` and `status` were run.
The mining experiment was not rerun, and cluster identities were not independently
validated in this review.

The recorded `mining-pass-first-run` outcome in the store's
`notes/predictions.jsonl` covers `c40d950031bb`, 330-430 s at 1 Hz:

| Measurement | Recorded result | What it establishes |
|---|---|---|
| Sample | 101 frames from one interval | A development sample, not session transfer |
| Proposals | 2,391; 23.7/frame; all describable | Execution and descriptor availability, not object recall |
| Static subtraction | 14 pixels removed | Little effect at this operating point |
| Clustering | 254 clusters; 67 recurring | An appearance partition, not validated classes |
| Rotation relations | 93 selected pairs | Candidate relations without a calibrated null |

Proposal recall, cluster purity, family coverage, and held-out transfer remain
unmeasured by these figures. The earlier 71-portrait mining result is encouraging
for already-localized portraits; it does not validate general object acquisition.

At review time `doctor` reported six findings and zero errors. `status` reported
all 20 stored minimap datasets stale against `minimap-0.6.0`. These are dated
diagnostics, not recognition accuracy. Future comparisons must identify input
and producer versions and refresh required stale inputs before trusting them.

## Implementation critique

### Residual components are not objects

`mine_icons.propose` thresholds grayscale outside `[lo_gray, hi_gray]` plus a
margin, then filters connected components by area. It can miss foreground with
grayscale inside that interval even when color differs, fragment one icon, or
merge touching icons into an oversized component that gets rejected. Component
centroids need not be icon centers. Large regions are deliberately excluded.

Removing dependence on a specific color key removes one bias, not all proposal
bias. Measure candidate coverage and centering before declaring the proposer
successful. An exhaustive acquisition audit must include objects that produced
no candidate, and distinguish icon proposals from region coverage.

### The descriptor omits discriminative glyph evidence

`minimap_appearance.describe` was designed for upright portrait interiors. It
samples `0.55 * radius`, resizes to 11x11, and uses a circular interior mask.
The miner supplies a fixed radius rather than component extent. At scale 0.712
this is approximately an 8x8 source patch resized to 11x11, with corners masked.
Outer silhouettes, arrow tips, and badge geometry may therefore be absent.

Matching uses background-residual NCC by default. Color and component shape are
discarded; stored area is not used in similarity. `describe` computes contrast
but does not reject low contrast. With the empty color mask, being describable
mostly establishes that the patch can be sampled. Clustering cannot recover
information the representation discarded.

### Position spread does not establish a class or origin

A correct glyph family appearing at many map locations should have large spread.
A fixed artifact, a deployed device, and a stationary player can all have small
spread. The reported spread and medoid contrast values are exploratory features,
not a demonstrated separator of entities and noise.

Use position and motion for provisional instance association. Use appearance
across instances for visual-family discovery. Do not put absolute position into
class clustering or infer an origin from concentration. Behavioral evidence is
useful when measured over time, with actual timestamps and uncertain associations.

### Persistence cannot identify furniture by itself

The static rule removes pixels foreign in more than half the selected frames.
The implementation measures the requested interval, not necessarily a session.
A persistent device, marker, or stationary player can satisfy this condition.
The code comment claiming a mostly stationary entity would not be an entity is
incorrect. Lowering the threshold could erase targets rather than remove clutter.

Use independently supported background observations, lighting state, round
boundaries, and foreground support. Preserve uncertainty where background cannot
be established. The inert result alone does not identify whether furniture was
present, whether geometry already explained it, or which statistic should replace
occupancy.

### Recurrence and clustering need stronger units of evidence

Leader clustering chooses the best matching fixed first-member leader. Leaders
never update; medoids are selected afterward for presentation. Results depend on
input order and early exemplars, and membership does not guarantee mutual
similarity. Eight frames of one artifact or one instance satisfy `MIN_MEMBERS`.

Count support over distinct tracks, rounds, and sessions as well as frames.
Keep rare and singleton candidates available for discovery. Check order stability
and inspect diverse members, not just medoids and early neighboring observations.
HDBSCAN is a useful challenger because it supports noise and an unfixed cluster
count, but representation quality still governs results and rare families can
be assigned to noise. [HDBSCAN documentation](https://scikit-learn.org/stable/modules/generated/sklearn.cluster.HDBSCAN.html)

### Contrast should initially rank, not erase

NCC normalizes amplitude, so contrast supplies useful additional evidence. The
reported medoid contrasts do not establish a safe hard gate. A gate can suppress
translucent effects, occluded icons, and small glyphs while retaining bright map
edges. Keep a sampled low-contrast review channel and measure lost recall before
promoting a cutoff.

### Rotation and event anchoring propose relationships

Sixty-seven medoids yield 2,211 pair comparisons. The 93 selected rotation pairs
need a matched null distribution and accounting for multiple comparisons.
Rotating a residual patch also rotates residual terrain structure. Compare
multiple exemplars with alignment and scale alternatives; retain ambiguity.

An observed transition or a carrier-relative association is stronger evidence
of carried/dropped states than transformed patch similarity alone. Likewise,
coincidence with a HUD plant or killfeed death is not a forced semantic label:
several visual changes can occur together. Require spatial, temporal, and
alternative-hypothesis evidence. `reticle/minimap_lifecycle.py:matching_events`
already requires spatially linked evidence and notes that a cast timestamp alone
cannot establish destination or caster; mining should preserve that standard.

### The prototype is not yet a reusable evidence dataset

The miner prints results and optionally writes a sheet, while descriptors and
members remain in memory. It retains all sampled crops; memory grows with both
sampling rate and interval duration. Repeated clustering currently entails a new
decode. A subsequent implementation should persist versioned candidate evidence
and source references through the existing artifact/store conventions, enabling
stored-data comparisons without another video pass. Do not create a parallel
entity store or copy raw media.

## Proposed extraction responsibilities

1. **Acquire candidate hypotheses.** Combine background residuals, color
   differences, generic edge/blob support, existing successful readers, and
   temporal changes. Preserve source-channel provenance and overlapping
   alternatives. Stationary differences remain eligible. Track unsupported slab
   edges and background-unknown areas as coverage limitations.
2. **Preserve full evidence.** Keep component support and extent, full glyph and
   interior appearances, color, edges, scale, background reliability, timestamps,
   and coordinate transforms. Different representations share one observation
   contract. Do not mistake a residual mask for a recovered alpha matte.
3. **Build conservative tracklets.** Associate obvious neighboring observations,
   retaining alternatives around crossings, overlap, and missing frames.
   Tracklets are provisional correspondences, not established world entities.
   Sparse sampling cannot resolve every short transition; use independently
   selected dense windows alongside broad discovery samples.
4. **Discover families across tracklets.** Compare multiple exemplars with bounded
   translation and scale alignment. Preserve orientation when it encodes state.
   Retain unknown patterns and rare candidates. Recurrence across independent
   uses is stronger than many adjacent samples of one use.
5. **Infer meaning and lifecycle separately.** Combine appearance, relative motion,
   event evidence, and lifecycle constraints. Keep existence, identity, center,
   bearing, phase, owner, and origin uncertainty distinct. A visible overlap can
   be a composite observation without becoming a new semantic entity class.

Small glyphs, tinted regions, directional geometry, and phase sequences should
use specialized representations within this framework. This does not require
a new handwritten detector for every named ability. Existing successful
specialists can contribute proposals or evidence through the common contract.

## Algorithm alternatives and labeling strategy

| Approach | Proposed role | Principal limitation |
|---|---|---|
| Mined exemplars plus geometry/templates | Low-label baseline for repeated artwork | Proposal recall and alignment |
| Fine-tuned YOLO | Broad localization and coarse visual families | Representative labels; no lifecycle semantics |
| Frozen visual embeddings | Candidate retrieval/clustering challenger | Tiny glyph details may be lost |
| Grounding DINO | Exploratory text-prompted proposals | Unverified transfer to game-specific tiny glyphs |
| SAM-style segmentation | Mask assistance and larger regions | Segmentation does not name or explain entities |

Standard COCO-pretrained YOLO weights cover 80 categories, not the minimap's
vocabulary. YOLO is a ready-made training framework here, not a validated
zero-shot solution. Custom datasets are supported directly.
[Ultralytics detection documentation](https://docs.ultralytics.com/datasets/detect)

Benchmark a modest fine-tuned model on minimap crops before resizing, preserving
useful icon resolution. Initially target coarse visual families; use appearance
and temporal evidence for finer identity and state. Test crowded overlaps and
suppression of neighboring detections explicitly. Upscaling does not restore
information absent from the source.

Grounding DINO supports text-conditioned open-set detection; SAM 2 supports
promptable image/video segmentation. Their published capabilities do not establish
Reticle accuracy. Their proposed exploratory/annotation roles, and the suitability
of frozen embeddings, are hypotheses to test against the deterministic baseline.
[Grounding DINO](https://arxiv.org/abs/2303.05499),
[SAM 2](https://arxiv.org/abs/2408.00714)

Minimal supervision is preferable to assuming zero-label semantics: review diverse
cluster members, uncertain associations, rare patterns, detector disagreements,
and random frames with no proposals. One name per medoid cannot detect mixed
clusters or missed objects. Apply the project's labeling workflow when conducting
an actual labeling pass; this review creates no labels.

Semi-supervised training is a later option once a reviewed seed works. Keep
pseudo-labels distinct from independent truth and prevent confidently repeated
detector mistakes from becoming evaluation evidence. Pseudo-label bias is an
established concern in semi-supervised object detection.
[Unbiased Teacher](https://arxiv.org/abs/2102.09480)

The existing Stage 02 no-model rule remains in force for implementation. This
review proposes an explicit architecture expansion to permit versioned learned
observation producers in a controlled comparison, while keeping adjudication
recomputable and uncertainty explicit. It does not silently amend the global
constraint or authorize a training run, installation, or production integration.

## Next work and acceptance

1. **Freeze evaluation scope and inputs.** Split whole sessions and uses before
   mining or tuning. Include ordinary no-event windows and backgrounds, lighting
   transitions, rare families, overlaps, region effects, and actual sampling tiers.
   The first-run interval remains development evidence. Verify annotation scope:
   existing painted frames are exhaustive only for categories their instructions
   asked the reviewer to mark.
2. **Audit proposal recall and centering first.** Attribute failures to acquisition,
   component splitting/merging, localization, representation, or classification.
   Include visible objects with no candidate and report unsupported regions.
3. **Compare three candidates on common evidence.** Preserve the current miner as
   baseline; compare a fuller deterministic representation with tracklet-based
   mining; include fine-tuned YOLO after the architecture decision. Compare learned
   and classical variants at stated annotation budgets, not unequal supervision.
4. **Spend labels on coverage and distinct failures.** Mix diversity/disagreement
   selection with random audits. Keep test labels out of galleries, background
   calibration, threshold choice, and pseudo-label generation.
5. **Choose by usable extraction per human effort.** Report per-family presence
   precision/recall, center error, identity confusion, unknown/refusal coverage,
   fragmentation, and region/phase errors where relevant. Report annotation
   minutes, candidate count, matching time, and end-to-end cost. Cluster count
   and channel agreement remain diagnostics. Use independent sessions/uses as
   uncertainty units rather than treating neighboring frames as independent.

Predeclare numerical budgets and falsifiable predictions before experiments,
using the requesting capability's tolerance and measured baseline. Inspect source
images and use the existing review tools. Persist versioned evidence so comparisons
can be repeated without unnecessary decoding. Promotion requires a visually
checkable annotated sequence, held-out benefit, provenance, and integration through
the existing observation/lifecycle contracts. No candidate is selected as winner
by this design review.
