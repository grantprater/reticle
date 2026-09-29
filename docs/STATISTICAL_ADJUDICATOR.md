# The statistical adjudicator

Plan, proposed 2026-09-28, for the player's priority of 2026-09-23: an
adjudicator that carries each measurement with its uncertainty and asks,
cheaply, whether a plausible measurement error explains another observation.
It sits inside the match-wide frame of [ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md)
and consumes `team_vision` (`team-vision-0.1.0`), which stores the team's
adjudicated vision per cached frame. The first experiment is `prototypes/sliver_error_model.py`.

## The question

A deterministic rule casts one cone from one position and one bearing and asks
whether it covers a pixel. The inputs are measurements: the icon centre, the
facing, the map's walls and the lit-region reader each carry an error, and a
sliver of light sits below their precision. The adjudicator asks instead: *how
probable is an error in the inputs large enough to make the cone cover this
observation?* It explains the observation when that probability is not
negligible, and it keeps the observation unexplained -- a refusal with its
reason -- when no plausible error reaches it. An error model that explains
everything explains nothing, so every explanation is also scored against a
null: the same observation with inputs taken from another moment, at least 3 s
away. The true inputs must explain it better than that base rate.

## The evidence: labels and slivers

- **Grouping labels:** `labels/ability_grouping/*.jsonl` in the store, last row
  per key, unsure answers excluded, joined to components by
  `adjudication.ability._components`. 19 answers are `viewcone_fragment`, all in
  `e78e75b2d191` (`C:\Users\grant\Videos\2026-09-03 19-16-07.mp4`, the Omen demo
  on Ascent); 34 are abilities: 22 in `a06f04a0059f`
  (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`), 10 in `e78e75b2d191` and
  2 in `5822b6646448` (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`).
- **The three slivers** are the viewcone answers `lighting.clean_lit` misses, all
  in `e78e75b2d191`: 36.9 s (box 320,182 5x8), 40.65 s (box 266,48 15x24) and
  43.35 s (box 278,48 7x20). The 2026-09-23 ledger rows in
  `notes/predictions.jsonl` (task `ability-candidate-light-gate`) name them.
- **Stored inputs:** the minimap crop cache (`roi_cache/minimap`, 15 Hz,
  lossless), the baked `ascent__valorant-16x9-bigmap` geometry, and the
  `ability_light` raw decision stored at each component's time. Nothing here
  decodes video.

## The removed sliver search, and why its every-viewcone result was not evidence

`adjudication.ability.light_refusals` now (`ability-light-refusal-0.3.0`)
refuses
[metric:sliver_error_model/grouping-labels@all-labelled#owner_viewcones_refused=16]
of 19 viewcones and
[metric:sliver_error_model/grouping-labels@all-labelled#owner_abilities_refused=0]
abilities; the stored team vision covers none of the three slivers. Until
0.3.0 it also carried a sliver search from `prototypes/adjudicator_statistical.py`
(2026-09-23, prediction and confirmation logged together) that refused every
viewcone. The team-vision merge removed it for restating the self raycast.
Reading it against the owners finds three defects:

1. **It reads a distance as a bearing.** It takes the series column `self_d` as
   the self facing, but `prototypes/ability_series.py` writes `self_d` as the
   distance from the self fit to query `c0` at (252, 66). At 40.65 s its
   "bearing" of 100.2 degrees is that distance in pixels.
2. **It lets rays through walls.** It builds passability as `labels != VOID`
   dilated by a pixel, so rays cross `BORDER` walls and boxes. `cone.passable_from`
   owns that composition; the restated rule drifted from it.
3. **Its budget was assumed, then graded on the cases it was built for.** Plus
   or minus 2 px and 10 degrees over both lobes, any draw covering 20% of the
   box. The ability clause rests on the `raw_dark` gate, not on geometry.

It also takes its position from the series, whose self point sits
[metric:sliver_error_model/segment-transparency@e78e75b2d191#series_offset_px_min=5.8]
to [metric:sliver_error_model/segment-transparency@e78e75b2d191#series_offset_px_max=7.8]
px from the icon centre `self_icons` fits at the three slivers. The time-shift
null below measures the result: given the pose of a moment at least 3 s away,
the wired search still "explains" each sliver box
[metric:sliver_error_model/grouping-labels@all-labelled#null_wired_min_rate=70%]
to [metric:sliver_error_model/grouping-labels@all-labelled#null_wired_max_rate=77%]
of the time. It explained nearly anything near the player; its removal stands on
measurement as well as on ownership.

## Candidate formulations

### A. Error-budget interval test

Give each input an interval, k standard deviations of its measured error, and
call the observation explained when some input inside the box reproduces it.
Run as a search for the *smallest* error that reproduces it, the test states its
answer in the player's own words: "the position must move 2.5 px, or the facing
40 degrees".

- **Stores:** one sigma per input (position, facing, lobe flip, half-angle, wall
  edge) and the chosen k.
- **Cost:** a grid or line search of raycasts; hundreds per observation.
- **Fails when** the box grows with the number of inputs: five inputs at k = 2
  hold a point that explains most things, and the joint probability of being at
  a corner of the box is far below any single input's. It has no competing
  hypothesis, so it cannot weigh a sliver against a device. The rule wired
  today is this formulation with an assumed budget.
- **Best use:** a diagnostic stored beside each decision -- the smallest error,
  in sigma units, that explains the observation.

### B. Per-frame likelihood with a measurement-noise model

Treat the cone as a probability per pixel. The bearing is a mixture: a wrapped
normal about the track bearing with the measured jitter, plus the opposite lobe
at the measured flip rate. The angular part of P(pixel in cone) is then a
difference of two normal CDFs; the occlusion part is the raycast at the point
estimate, softened by the position error. The lit-region reader already stores
a two-state reference per pixel (`lighting.Lighting`: `lo`, `hi`, `sd_lo`,
`sd_hi`), which gives P(grey | lit) and P(grey | unlit), so a component earns a
log-likelihood ratio between "drawn light" and "something else".

- **Stores:** the same sigmas; the lighting reference, which exists.
- **Cost:** one raycast and a closed form per pixel; the cheapest.
- **Fails where the slivers live.** Visibility is not smooth in position: a
  ray through a doorway flips from blocked to open over a pixel, so softening
  the point-estimate raycast misstates exactly the thin passages that make
  slivers. Summing per-pixel ratios also treats neighbouring pixels as
  independent and overcounts large components.

### C. Sampling over pose and geometry

Draw poses from the measured error model -- a bearing from the track's window
of per-frame bearings, jitter, a lobe flip at the measured rate, a position
offset -- and draw geometry from its own uncertainty: each BOXEDGE segment open
at its measured transparency, each wall edge moved by a pixel at its measured
rate. Raycast each draw with `cone.raycast`. E, the share of draws whose cone
covers the observation, is the probability that a measurement error explains
it. Extended in time, the same draws become particles on a track: facing
continuity, lifecycle and carried positions enter as transition likelihoods
instead of the gates `track.Track.resolved_facing` and `Tracker.principal`
apply today.

- **Stores:** the sigmas, a transparency per BOXEDGE segment, the pose window
  per frame (from the team-vision product), and the draw count and seed with
  every decision so a rerun reproduces it.
- **Cost:** N raycasts per observation (N = 200 here); a particle filter adds N
  per frame per track. Gate the sampling on opportunity -- a candidate the
  point estimate already explains, or one with no light in it, needs no draws.
- **Fails when** E is small: Monte Carlo error at E = 0.05 with N = 200 is
  about 0.015. E is a coverage probability, not a posterior; a decision needs
  a competing hypothesis or a specificity null. Its answer is only as good as
  the sigmas, and a sigma measured as jitter misses a systematic bias.

## What each measurement must carry

| Measurement | Uncertainty | Estimated from existing data | Stored where |
|---|---|---|---|
| Icon centre | jitter sigma; bias against an independent centre | fit residual about a +/-2 frame median on held-out frames; bias against the disc centre or the ring of a second detector | team-vision product: per frame `(x, y, r, cov)`; sigma in a versioned calibration table per profile |
| Facing | within-lobe sigma; lobe flip rate | per-frame bearing against the bisector of the drawn light around the icon, on held-out frames | the per-frame raw and lobe-resolved bearings and the track window, not only the gated mean |
| Track facing | the window's spread | `resolved_facing`'s resultant; the window itself | the window of bearings, so a low resultant becomes a wide distribution instead of a refusal |
| Which track is self | two live candidates | `Tracker.principal` refusing between tracks | both candidates, so the adjudicator draws from a mixture |
| Half-angle | an interval | 51.5 degrees is an engine constant from a web source; the repo measured 50-65 (`cone.CONE_HALF_ANGLE_DEG`); the lit wedge's edges on held-out frames would measure it | calibration table |
| BOXEDGE segment | transparency | lit rate of floor reached only through a box edge, scaled between the lit rate outside every cone and inside the cone | geometry builder, pooled across sessions, per segment, under a new geometry stamp |
| Wall edge | a pixel either way | lit pixels one pixel past a wall at the point estimate, pooled | geometry builder, same stamp |
| Lit reader | per-pixel two-state noise | exists: `lighting.reference` | geometry npz |
| Observation time | up to half a cache frame | the crop cache is 15 Hz; the stored `ability_light` frame is exact | the component's `observed_t_ms` beside the pose frame's time |

Geometry refinements follow the player's rule: evidence pools across sessions
into the geometry builder under a new stamp, never a per-session correction,
and a refinement is scored on held-out slivers or an independent witness.

## First experiment: does a measured error explain the slivers, and only them?

`prototypes/sliver_error_model.py` implements formulation C on stored data.
Predictions were logged in `notes/predictions.jsonl` (task
`statistical-adjudicator-e1`) after inspecting the three sliver crops and before
any pose or score was computed.

**Pose.** `team_vision.TeamVision`, the owner of the chain
(`minimap.self_icons`, then `cone.resolve_lobe` against `lighting.lit_mask`,
then `track.Tracker`), driven over every cached frame of `e78e75b2d191`. The
prototype reads the principal track's position and its 200 ms window of
lobe-resolved bearings, which the stored rows do not keep. Where the track
refuses the self bearing -- 36.9 and 43.35 s, resultant under 0.5 -- the stored
product casts no cone; the sampler draws from the window instead.

**Calibration, from held-out frames** (every frame more than 1.5 s from a sliver):

| Input | Estimator | Measured |
|---|---|---|
| Position jitter | RMS residual of the fit centre about a +/-2 frame median | [metric:sliver_error_model/grouping-labels@all-labelled#sigma_pos_px=0.72] px |
| Facing, within lobe | robust spread of the per-frame bearing about the bisector of the drawn light, over [metric:sliver_error_model/grouping-labels@all-labelled#facing_frames=399] frames | [metric:sliver_error_model/grouping-labels@all-labelled#sigma_deg=29.0] degrees |
| Lobe flip after `resolve_lobe` | share of those frames more than 90 degrees off the bisector (a floor: `resolve_lobe` saw the same light) | [metric:sliver_error_model/grouping-labels@all-labelled#flip_rate=2%] |
| BOXEDGE transparency, all segments | lit rate of floor reached only through a box edge, between the lit rate outside every cone and inside the cone | [metric:sliver_error_model/grouping-labels@all-labelled#boxedge_q=0.12] |

**Scoring.** O is the stored raw-lit floor in a component's box. Each of 200
draws takes a bearing from the window plus jitter, flips the lobe at the flip
rate, offsets the position by the jitter and, in M2, opens each BOXEDGE segment
at the transparency; E is the share of draws whose `cone.raycast` covers half of
O. A component is explained at E >= 0.05. M0 is the track's point estimate and
M1 is pose error alone. Fewer than 3 raw-lit pixels is `no_light`; no principal
track is `no_pose`. Specificity is the time-shift null: the same box and O,
scored from the poses of 60 frames at least 3 s away.

### Results against the predictions

| | Prediction | Result | Verdict |
|---|---|---|---|
| P1 | position 0.5-3 px; facing 4-25 deg; flip at most 15%; transparency 0.1-0.7 | facing spread above its bound; the rest inside | partly failed |
| P2 | M0 explains at most 1 of 3 | [metric:sliver_error_model/grouping-labels@all-labelled#slivers_explained_m0=0] | held |
| P3 | M1 explains at least 2 of 3 | [metric:sliver_error_model/grouping-labels@all-labelled#slivers_explained_m1=0] | failed |
| P4 | M2 explains 3 of 3 | [metric:sliver_error_model/grouping-labels@all-labelled#slivers_explained_m2=1] (E = [metric:sliver_error_model/grouping-labels@all-labelled#e_m2_36900=0.045], [metric:sliver_error_model/grouping-labels@all-labelled#e_m2_40650=0.095], [metric:sliver_error_model/grouping-labels@all-labelled#e_m2_43350=0.03]) | failed |
| P5 | shifted poses explain each box at most 20% of the time; the true pose beats 90% of them | [metric:sliver_error_model/grouping-labels@all-labelled#null_m2_40650=23%] and [metric:sliver_error_model/grouping-labels@all-labelled#null_m2_43350=28%] for the later two, more often than the true pose | failed |
| P6 | the wired search explains at least half the shifted poses | [metric:sliver_error_model/grouping-labels@all-labelled#null_wired_min_rate=70%] or more | held |
| P7 | M2 explains at least 13 lit viewcones | [metric:sliver_error_model/grouping-labels@all-labelled#lit_viewcones_explained_m2=9] of [metric:sliver_error_model/grouping-labels@all-labelled#lit_viewcones_scored=9] scored; the other 7 of [metric:sliver_error_model/grouping-labels@all-labelled#lit_viewcones_n=16] (34.05-35.4 s) have no pose because `Tracker.principal` refuses between two tracks | failed as worded; all scored ones explained |
| P8 | no ability explained with light observed | [metric:sliver_error_model/grouping-labels@all-labelled#abilities_explained_m2=6] of [metric:sliver_error_model/grouping-labels@all-labelled#abilities_scored=22] scored (of [metric:sliver_error_model/grouping-labels@all-labelled#abilities_n=34]), all in `e78e75b2d191` at 16.2, 26.55 and 29.25 s | failed |

**In plain words:** measured pose error does not explain the slivers. The icon
centre jitters under a pixel; the facing spread is wide, but the slivers sit
inside the cone's angle already. Something blocks the ray. Poses from other moments
light the 40.65 and 43.35 s boxes more often than the true pose does, because
the player stood elsewhere and lit them; the recorded pose is the worst case for
those boxes, which points at its surroundings rather than its noise. A diagnostic run
beside the pre-registered test (formulation A: the smallest offset, up to 4 px,
at which a cone aimed at O covers it) found no offset that works for 36.9 or
40.65 s with the map as built ([metric:sliver_error_model/required-error@e78e75b2d191#g0_offset_px_36900=-1.0] and
[metric:sliver_error_model/required-error@e78e75b2d191#g0_offset_px_40650=-1.0], where -1 means none up to 4 px),
[metric:sliver_error_model/required-error@e78e75b2d191#g0_offset_px_43350=2.5] px for 43.35 s, and zero error for all
three once BOXEDGE lines are passable ([metric:sliver_error_model/required-error@e78e75b2d191#g1_offset_px_36900=0.0],
[metric:sliver_error_model/required-error@e78e75b2d191#g1_offset_px_40650=0.0], [metric:sliver_error_model/required-error@e78e75b2d191#g1_offset_px_43350=0.0] px). Box-edge lines were the suspect.

P8's failure is a design lesson rather than a defect: a device sitting inside the
lit cone has lit floor in its box, and the cone explains that floor. Explaining
the light around a component does not explain the component. The rule must
explain the evidence that made the candidate fire -- a dark device is not
explained by light -- which is formulation B's two-state likelihood, not a
coverage share.

### Follow-up E1b: is a box edge a doorway?

Logged before running (task `statistical-adjudicator-e1b`): each sliver has one
BOXEDGE segment whose opening alone lets the cone reach it, and those segments
pass light in held-out frames (transparency at least 0.5).

- A single blocker exists for
  [metric:sliver_error_model/segment-transparency@e78e75b2d191#blockers_found=2]
  of 3: segment 7 at 40.65 s and segment 6 at 43.35 s. No single segment opens
  36.9 s.
- On held-out frames both blockers score transparency
  [metric:sliver_error_model/segment-transparency@e78e75b2d191#blocker_q_max=0.0],
  against [metric:sliver_error_model/segment-transparency@e78e75b2d191#global_q=0.12]
  for all segments pooled, over tens of thousands of reach-only pixels. They
  are opaque everywhere else.
- M3, with those measured transparencies, explains
  [metric:sliver_error_model/segment-transparency@e78e75b2d191#slivers_explained_m3=0]
  slivers and changes
  [metric:sliver_error_model/segment-transparency@e78e75b2d191#changed_vs_m2=0]
  other outcomes.

The held-out witness refuted the whole-segment story, and the crops show why. At
40.65 and 43.35 s the blocking line runs through the self icon's own footprint:
the fitted centre sits on or beside a one-pixel box edge, so every ray dies at
its origin, while the game draws the light from a player standing past that
edge. At 36.9 s a box-edge line closes a doorway between the lit corridor and the
passage holding the sliver. The uncertainty that matters is local: which side of
a one-pixel line the cone's origin lies on, and whether a stretch of line is a
doorway. Neither is a whole segment, and neither is pose jitter.

## Recommendation

**Build formulation C, the sampler, with B's lighting likelihood for appearance
and A's smallest-error search stored beside every decision.** Sampling is the
only formulation that handles a ray through a doorway, where visibility jumps
over a pixel, and it extends to tracks as particles. B supplies the competing
hypothesis the sampler lacks: the per-pixel two-state reference says whether a
component's pixels are brighter than unlit floor (light can explain them) or
darker (it cannot). A turns each decision into the sentence the player asked
for -- "the origin would have to move
[metric:sliver_error_model/required-error@e78e75b2d191#g0_offset_px_43350=2.5] px" -- and is the audit trail.

The experiment reorders the work:

1. **Keep the slivers unexplained until a model explains them specifically.**
   `ability-light-refusal-0.3.0` already does: it removed the sliver search,
   which explained the slivers only because it explained almost any pose. No
   local error search returns; the error model sits in, or consumes, the
   owners of track facing and geometry.
2. **The origin before pose noise.** Measured position jitter is under a
   pixel and does not matter; where the eye sits relative to the lines near the
   icon does. E2 below found that neither the open side of a line nor a derived
   teardrop settles it; E3 reads the teardrop.
3. **Store what the sampler needs in `team_vision`.** Its rows keep each
   icon's position and gated bearing. Add per frame and track: the fitted
   radius, the raw and lobe-resolved per-frame bearings, the 200 ms window and
   the resultant, under a new `team-vision` stamp.
   Where `Tracker.principal` refuses, both candidate tracks, so the sampler
   draws from a mixture instead of reporting no pose, as it did for the lit
   viewcones at 34.05-35.4 s.
4. **Calibrate per profile, not per session.** Position jitter, facing spread
   and flip rate go in one versioned calibration table; the time-shift null is
   its acceptance test, run when the table changes rather than per decision.
5. **Geometry refinements go to the geometry builder.** Evidence pools across
   sessions under a new geometry stamp, per pixel of line rather than per
   segment, and is scored on held-out slivers or on held-out frames, as E1b
   was.

## E2: the origin on an occluder

The player answered the mechanics question on 2026-09-28: a box edge the player
stands at does block the player's own sight, and the ray stops exactly at the
edge or corner, as the cone spec of 2026-09-02 described
[domain:minimap/cone-rays-stop-at-first-edge]. That spec also puts the cone's
origin at the icon's teardrop point, not its centre. So no edge becomes
transparent; the open question is where the eye is. E2 (task
`statistical-adjudicator-e2`, `--experiment e2`) tested two origin rules with
E1's pose noise and no geometry noise, predictions logged first:

- **side:** when a drawn origin lies within a pixel of an impassable pixel, move
  it to the passable pixel within three sigma ([metric:sliver_error_model/origin-side@e78e75b2d191#side_radius_px=2.15] px)
  that lies furthest along the drawn bearing;
- **teardrop:** place the origin one fitted icon radius along the drawn bearing.

| | centre | side | teardrop |
|---|---|---|---|
| E at 36.9 s (the doorway) | [metric:sliver_error_model/origin-side@e78e75b2d191#e_centre_36900=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_side_36900=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_teardrop_36900=0.0] |
| E at 40.65 s | [metric:sliver_error_model/origin-side@e78e75b2d191#e_centre_40650=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_side_40650=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_teardrop_40650=0.13] |
| E at 43.35 s | [metric:sliver_error_model/origin-side@e78e75b2d191#e_centre_43350=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_side_43350=0.0] | [metric:sliver_error_model/origin-side@e78e75b2d191#e_teardrop_43350=0.225] |
| shifted poses explaining 40.65 / 43.35 s | | | [metric:sliver_error_model/origin-side@e78e75b2d191#null_teardrop_40650=22%] / [metric:sliver_error_model/origin-side@e78e75b2d191#null_teardrop_43350=18%] |
| true E's percentile among them | | | [metric:sliver_error_model/origin-side@e78e75b2d191#pct_teardrop_40650=0.883] / [metric:sliver_error_model/origin-side@e78e75b2d191#pct_teardrop_43350=0.933] |
| held-out cone precision (raw-lit share) | [metric:sliver_error_model/origin-side@e78e75b2d191#precision_centre=0.639] | [metric:sliver_error_model/origin-side@e78e75b2d191#precision_side=0.639] | [metric:sliver_error_model/origin-side@e78e75b2d191#precision_teardrop=0.59] |
| held-out recall, clear frames | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_centre_clear=0.52] | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_side_clear=0.52] | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_teardrop_clear=0.383] |
| held-out recall, frames with the centre on a line | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_centre_near=0.308] | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_side_near=0.272] | [metric:sliver_error_model/origin-side@e78e75b2d191#recall_teardrop_near=0.157] |
| lit viewcones explained, of [metric:sliver_error_model/origin-side@e78e75b2d191#lit_viewcones_scored=9] | [metric:sliver_error_model/origin-side@e78e75b2d191#lit_viewcones_centre=9] | [metric:sliver_error_model/origin-side@e78e75b2d191#lit_viewcones_side=9] | [metric:sliver_error_model/origin-side@e78e75b2d191#lit_viewcones_teardrop=8] |

Against the predictions: R1 failed -- the side rule explains no sliver, and the
fitted centre sits on a line only at 43.35 s and in
[metric:sliver_error_model/origin-side@e78e75b2d191#frames_near=4] of the held-out frames; at 40.65 s the rays die a few
pixels out, not at the origin. R2 held -- the teardrop explains 40.65 and 43.35
s and the 36.9 s doorway stays closed. R3 held for 43.35 s and missed for 40.65
s, whose true E beats 88% of shifted poses against a bar of 90%. R4 failed: on
held-out frames the teardrop cone covers less of the drawn light than the
centre cone. An exploratory reread beyond three icon radii, added after R4
failed to rule out the icon's own glow, keeps the gap
([metric:sliver_error_model/origin-side@e78e75b2d191#recall_teardrop_far=0.407] against [metric:sliver_error_model/origin-side@e78e75b2d191#recall_centre_far=0.502]).

**In plain words:** moving the eye within the measured position error does not
explain the slivers. Moving it to the teardrop does explain the two past the
icon, and keeps the doorway closed, but the same move makes the cone agree
worse with the drawn light everywhere else. An explanation that the held-out
frames contradict grades its own homework, so the slivers stay unexplained
refusals. The likely reason is the bearing: with a
[metric:sliver_error_model/grouping-labels@all-labelled#sigma_deg=29.0] degree
spread, a teardrop placed from the fitted centre and the drawn bearing lands
beside the true tip.

## Next experiment, E3: read the teardrop

Read the teardrop tip from pixels, as its own witness of origin and facing,
instead of deriving it from the ring fit. Pre-register that a cone cast from
the read tip, along the tip's direction, covers more of the held-out drawn light
than the centre cone does, and only then rescore the three slivers. If the tip
cannot be read reliably, build the labeller that asks the player to click it on
the three sliver frames and a held-out sample.

## What this plan does not settle

- The half-angle stays at 51.5 degrees; its interval was not measured.
- Wall edges (`BORDER`) were not perturbed; only box edges were.
- E2's near-line group holds only a handful of held-out frames.
- Calibration used one session and one map.
- The flip rate is a floor, because `resolve_lobe` chose each lobe with the
  same light the bisector reads.
- The facing spread is measured against the light's bisector, which a
  half-occluded cone biases; it is an upper bound on the fit's error.
