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
   teardrop settles it. E3 read the teardrop: its facing is the missing input,
   and its apex is not the origin.
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

## E3: read the teardrop

`prototypes/teardrop_tip.py` (`teardrop-tip-0.1.0`) fits the self icon as a
shape: a pale ring round the portrait plus a lobe whose edges are tangent to
the ring and meet at the apex. It scores a soft silhouette against a continuous
yellowness, with no threshold, and searches centre and facing. One size serves
every frame: outer radius 11 px, apex 18 px from the centre, fitted on 24
held-out frames of this widget size. `sliver_error_model.py --experiment e3`
scores it (task `statistical-adjudicator-e3`; predictions logged after the
contact sheets and before any measurement).

| | Prediction | Result | Verdict |
|---|---|---|---|
| T1 | reads on at least 95% of held-out frames | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#read_rate=0.984] of [metric:sliver_error_model/teardrop-tip@e78e75b2d191#frames_detected=451] | held |
| T2 | stationary facing jitter at most 4 deg, tip at most 0.8 px | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#facing_jitter_rms20_deg=0.593] deg, [metric:sliver_error_model/teardrop-tip@e78e75b2d191#tip_jitter_rms_px=0.191] px over [metric:sliver_error_model/teardrop-tip@e78e75b2d191#stationary_frames=59] windows | held |
| T3 | facing against the light: spread at most 15 deg, flips at most 2% | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#light_spread_tip_deg=6.858] deg, [metric:sliver_error_model/teardrop-tip@e78e75b2d191#light_flip_tip=0.009] flipped (E1's facing: [metric:sliver_error_model/grouping-labels@all-labelled#sigma_deg=29.0] deg) | held |
| T4 | the ring fit sits at least 1.5 px off, toward the apex | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#ring_offset_median_px=4.433] px, cosine [metric:sliver_error_model/teardrop-tip@e78e75b2d191#ring_offset_cos_median=0.986] | held |
| T5 | apex cone: precision no worse, clear recall +0.03 over the centre cone | precision [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_tip=0.588] against [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_centre=0.636]; recall [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_tip_clear=0.397] against [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_centre_clear=0.518] | failed |
| T6 | apex cone explains 40.65 and 43.35 s, not 36.9 s | 43.35 s only (E [metric:sliver_error_model/teardrop-tip@e78e75b2d191#e_tip_43350=1.0], shifted poses [metric:sliver_error_model/teardrop-tip@e78e75b2d191#null_tip_43350=0.0]) | failed |

T2's first run measured a jitter of exactly zero: the minimap repeats an image
across cached frames, so the fit repeats too. The rerun collapses repeated fits
before measuring. The ring fit's raw facing points more than 90 degrees from the
read facing on [metric:sliver_error_model/teardrop-tip@e78e75b2d191#ring_flip_vs_tip=0.577]
of frames; `resolve_lobe` rescues most of them with the light, which is why the
bearing looked usable.

**E3b, exploratory, logged after T5 failed** (task `statistical-adjudicator-e3b`):
the same read facing cast from other origins on the same
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#frames=382] held-out frames.

| Origin, along the read facing | precision | clear recall | far recall |
|---|---|---|---|
| E2's centre cone (track position and bearing) | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_centre=0.636] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_centre_clear=0.518] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_centre_far=0.5] |
| track position, read facing | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_centre_tipdeg=0.703] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_centre_tipdeg_clear=0.604] | |
| teardrop centre | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_tip_facing=0.719] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_tip_facing_clear=0.648] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_tip_facing_far=0.609] |
| 8 px out | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_axis_8=0.687] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_axis_8_clear=0.555] | |
| 14 px out | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_axis_14=0.622] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_axis_14_clear=0.461] | |
| apex, 18 px out | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_tip=0.588] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_tip_clear=0.397] | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#recall_tip_far=0.466] |

Agreement falls at every step from the centre to the apex. From the teardrop
centre along the read facing, the cone explains 43.35 s (E
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#e_tip_facing_43350=0.955];
shifted poses explain the box
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#null_tip_facing_43350=0.0]
of the time), leaves 36.9 s closed and does not reach 40.65 s. It explains
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#lit_viewcones_tip_facing=13] of
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#lit_viewcones_tip_facing_scored=14]
lit viewcones; the read tip needs no track, so the 34.05-35.4 s cones now score.

**In plain words:** the teardrop reads cleanly, and its facing is what E1 and E2
lacked. At 43.35 s the track pointed the cone at
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#track_deg_43350=92.1] degrees
while the teardrop points at
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#tip_deg_43350=-137.0]: that
sliver was a flipped lobe, not a geometry error. At 40.65 s the drawn light is a
thin beam through a gap that a baked box-edge line closes, so it stays an
unexplained refusal for the geometry builder. The apex, however, is the worst
origin tested: with the half-angle held at 51.5 degrees, the drawn light fits a
cone cast from the icon's centre, contrary to the literal reading of the
player's spec [domain:minimap/cone-rays-stop-at-first-edge]. Either the rays
start at the centre and the teardrop only draws the cone's edges, or the angle
from the apex is wider; this session cannot tell them apart.

**Next.** Ask the player where the rays start, centre or point, before any
origin rule enters `cone`. Rerun E3b on a second session; if the read facing
from the centre wins there too, `team_vision` takes the read facing in place of
the ring fit's resolved lobe, under a new stamp, and the ring fit's centre gives
way to the teardrop's.

## E4: calibrate the origin and the angle

The player answered on 2026-09-28: the rays look to start at the icon's centre,
not the teardrop's point, and the exact point should be calibrated
[domain:minimap/cone-origin-near-centre]. `prototypes/cone_origin.py`
(`cone-origin-0.3.0`, task `statistical-adjudicator-e4`) fits the origin's
offset from the teardrop's centre, along the read facing and across it, jointly
with the half-angle: a grid of 1 px and 1 degree, scored by the pooled F1 of the
cone against the drawn light within 90 px, outside the icon's own pixels. The
first session is `e78e75b2d191` (Ascent, fit on even 3 s blocks, held out on
odd ones); the second is `5822b6646448` (Lotus, C:\Users\grant\Videos\2026-08-26
12-38-38.mp4), twenty 6 s windows spread over the match. Predictions were
logged first. The instrument reproduces E3b: the teardrop-centre cone at 51.5
degrees scores precision [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#instrument_precision=0.719]
on E3b's frames.

**The first witness failed on Lotus.** Every lit pixel in the region (`--witness
all`) is mostly teammates' cones there: the cone covers
[metric:cone_origin/e4@e78e75b2d191+5822b6646448#B_all_base_recall=0.333] of it,
and the half-angle profile climbs to the grid's edge. The rerun keeps only the
light joined to the self icon: lit components that touch a 3 px band round its
footprint. That uses no facing, so it favours no origin or angle.

| | Ascent fit half | Lotus |
|---|---|---|
| along the facing, px (95% block bootstrap) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_along=-5.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_along_lo=-10.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_along_hi=4.0]) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_along=0.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_along_lo=0.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_along_hi=2.0]) |
| across it, px | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_across=2.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_across_lo=1.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_across_hi=4.0]) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_across=0.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_across_lo=0.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_across_hi=0.0]) |
| half-angle, deg | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_half=46.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_half_lo=40.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_half_hi=56.0]) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_half=53.0] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_half_lo=52.0] to [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_half_hi=60.0]) |
| frames (blocks) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#frames_a_fit=121] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#blocks_a=7]) | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#frames_b=904] ([metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#blocks_b=7] windows fitted) |

| F1 against the joined light | (0, 0, 51.5) | Ascent fit | Lotus fit |
|---|---|---|---|
| Ascent held-out half | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#A_hold_base_f1=0.784] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#A_hold_fitA_f1=0.778] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#A_hold_fitB_f1=0.783] |
| Lotus, every frame | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#B_all_base_f1=0.588] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#B_all_fitA_f1=0.535] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#B_all_fitB_f1=0.592] |

The Ascent fit half's offset helps only its own frames: on the held-out half
and on Lotus it scores below the uncalibrated cone. Its interval is wide because
seven blocks of one short clip carry it. The held-out profiles agree with Lotus:
the best along-offset is [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_A_hold_along_peak=-1.0]
px on Ascent's held-out half (F1 [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_A_hold_along_peak_f1=0.788],
against [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_A_hold_along_0_f1=0.785] at the centre) and
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_B_all_along_peak=0.0] px on Lotus; the best half-angle is
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_A_hold_half_peak=50.0] and
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#profile_B_all_half_peak=55.0] degrees, on flat tops that hold 51.5.

**The facing on Lotus.** The teardrop is steady there: stationary jitter
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_facing_jitter_rms20_deg=1.233] degrees and
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_tip_jitter_rms_px=0.358] px over
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_stationary_frames=41] windows, and the ring fit sits
[metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_ring_offset_median_px=2.787] px off toward the apex.
It reads on [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_read_rate=0.8] of frames with a self
detection; the unread frames inspected are detections of a yellow ability icon
in a stack of teammates, which the shape rightly refuses. Its agreement with the
light is poor, and so is every witness's:

| Read facing against | Ascent | Lotus | ring fit, Lotus |
|---|---|---|---|
| raw light's bisector: spread, deg | [metric:sliver_error_model/teardrop-tip@e78e75b2d191#light_spread_tip_deg=6.858] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_light_spread_tip_deg=24.994] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_light_spread_ring_deg=25.598] |
| joined light's bisector: spread, deg | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_join_spread_tip_deg=6.846] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_join_spread_tip_deg=25.123] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_join_spread_ring_deg=24.47] |
| light-fitted facing: median difference, deg | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_lf_abs_median_tip_deg=1.875] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_lf_abs_median_tip_deg=10.75] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_lf_abs_median_ring_deg=55.654] |
| light-fitted facing: flipped | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#a_lf_flip_tip=0.014] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_lf_flip_tip=0.093] | [metric:cone_origin/e4b-joined@e78e75b2d191+5822b6646448#b_lf_flip_ring=0.4] |

The light-fitted facing is the facing whose cone from the teardrop centre best
matches the joined light; it was added after the bisectors failed, because the
inspected Lotus frames showed walls cutting one side of the cone. It did not
settle the question either. At 1287.7-1289.5 s on Lotus the read facing is +21
to +37 degrees and the light-fitted one about -27; the zoomed crops show the
lobe pointing right and down, and a lit wedge whose lower side a wall cuts,
which cones at either facing draw. Lotus's corridors and stacked teammates
leave the drawn light unable to tell a reader error from an occluded cone.

**In plain words:** the rays start at the teardrop's centre. No offset beats
it on held-out frames or on the second map, and the one offset fitted on
Ascent alone is noise. 51.5 degrees stays. The teardrop's facing beats the ring
fit on both sessions by every witness, but its precision on the second session
is not confirmed: on Lotus it agrees with the light to a median 10.8 degrees
where Ascent gives 1.9, and no light witness separates the reader from the
walls there.

**Should `team_vision` take them?** The origin, yes: cast from the teardrop's
centre, no offset, at 51.5 degrees; this retires the ring fit's centre, which
sits 2.8 to 4.4 px toward the apex. The facing, not yet: it needs the teardrop
read first, a fallback for the fifth of Lotus frames where the detector hands
it an ability icon, and a check against player labels of the facing on Lotus
frames, where the light cannot judge it. Both changes go in together, under a
new `team-vision` stamp, once the labels agree.

**The labels.** `prototypes/label_self_facing.py` asks the player, blind, for
the self icon's centre and tip on frames drawn from the crop cache in five
strata: where the teardrop and the light-fitted facing disagree most, where
they agree, where the teardrop refuses a self detection, read frames drawn
with no regard to the light, and Ascent control frames. Each item records why
it was drawn; the answers go to the store's
`labels/self_facing_lotus_20260928.jsonl`. `prototypes/self_facing_eval.py`
scores the teardrop and the ring fit against them. The predictions (L1-L5)
are logged in the store's `notes/predictions.jsonl` before any label exists.

**The player's answers.** On the [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_all_lotus_n=28] Lotus items the player
could read, the teardrop's facing errs a median [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_all_lotus_median_abs_deg=2.233]
degrees, flips on [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_all_lotus_flip=0.071] of them and lies within 10 degrees on
[metric:self_facing_eval/labels@5822b6646448+controls#teardrop_all_lotus_within10=0.893]. The ring fit's raw facing errs
[metric:self_facing_eval/labels@5822b6646448+controls#ring_all_lotus_median_abs_deg=105.498] and flips on [metric:self_facing_eval/labels@5822b6646448+controls#ring_all_lotus_flip=0.5]; E4's
light-fitted facing errs [metric:self_facing_eval/labels@5822b6646448+controls#light_all_lotus_median_abs_deg=4.01] and flips on
[metric:self_facing_eval/labels@5822b6646448+controls#light_all_lotus_flip=0.107]. On the [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_control_n=8] Ascent controls the
teardrop errs [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_control_median_abs_deg=1.82] with [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_control_flip=0.0]
flips. Where the teardrop and the light disagree, the label sides with the
teardrop [metric:self_facing_eval/labels@5822b6646448+controls#sides_teardrop=9] of [metric:self_facing_eval/labels@5822b6646448+controls#sides_n=11] times, and the clicked centre lies a
median [metric:self_facing_eval/labels@5822b6646448+controls#centre_click_vs_teardrop_px_median=0.804] px from the teardrop's. L1's median held and its flip clause (at most 5%) failed: both
flips fall in the `flip` stratum, drawn where the readers disagree, where the
teardrop flips on [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_flip_flip=0.4] of [metric:self_facing_eval/labels@5822b6646448+controls#teardrop_flip_n=5]. L2 as amended, L3 and L5 held. The teardrop reads
the facing on Lotus; most of the light's disagreement there was the walls.

## E5: `team_vision` casts the self cone from the teardrop

`team-vision-0.2.0` takes E4's origin and keeps the track's resolved facing.
`reticle/teardrop.py` (`teardrop-0.1.0`, owner of `self-cone-origin`) holds
the promoted fit; its grid correlates by `cv2.matchTemplate` and returns the
prototype's centre exactly on 69 sampled frames of both sessions, at a
twelfth of the time. Where the teardrop is unread the ring fit's centre stands
in, and each stored self icon's `origin` names the source and the reason.
`prototypes/vision_origin_eval.py` drives the chain on master's code and on
the branch and scores the self cone against E4's joined light, whose fit and
pixels did not move between the arms ([metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_witness_changed=0] and
[metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_witness_changed=0] frames changed). Ascent is E4's held-out half;
Lotus is E4's twenty windows, each warmed up 10 s through `team_vision.at`.

| Self cone against the joined light | before (ring fit) | after (teardrop) |
|---|---|---|
| Ascent precision | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_before_precision=0.681] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_precision=0.6773] |
| Ascent recall | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_before_recall=0.5392] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_recall=0.5556] |
| Ascent F1 | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_before_f1=0.6019] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_f1=0.6104] |
| Lotus precision | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_before_precision=0.7688] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_precision=0.7707] |
| Lotus recall | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_before_recall=0.4453] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_recall=0.4561] |
| Lotus F1 | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_before_f1=0.5639] | [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_f1=0.573] |

Recall counts the light of frames whose self bearing the track refused; on the
frames that cast in both arms, F1 rises from [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_before_cast_f1=0.6853] to
[metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_cast_f1=0.6936] on Ascent and from [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_before_cast_f1=0.624] to
[metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_cast_f1=0.6335] on Lotus. The teardrop supplies the origin on
[metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_teardrop_origin=134] of [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#e78e_after_cast_frames=134.0] cast cones on
Ascent and [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_teardrop_origin=632] of [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_cast_frames=718.0] on Lotus;
the ring fit stands in on [metric:vision_origin_eval/joined-light@e78e75b2d191+5822b6646448#lotus_after_fallback_origin=86].

Against the logged predictions: V2 and V3 held. V1 failed narrowly: Ascent's
F1 rose 0.009, not the 0.01 predicted, and its precision fell 0.004, inside
what one clip's 134 frames resolve. E3b's larger gain (precision
[metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_centre_tipdeg=0.703] to [metric:sliver_error_model/teardrop-tip@e78e75b2d191#precision_tip_facing=0.719]) cast along the teardrop's facing, which this change does not take; the
track's facing is the remaining error, and it waits on the player's Lotus
labels.

**The facing (0.3.0).** The labels settled the facing, so `team-vision-0.3.0`
casts the self cone along the teardrop's facing wherever the principal self
track is observed and the shape reads, whether or not the track resolved a
bearing. Where the teardrop is unread the cone falls back to the ring fit's
centre along the track's resolved lobe; the stored self icon's `self_cone`
names the origin and facing it used and keeps the track's bearing as
`track_deg`. `teardrop-0.2.0`'s `SelfConeReader` returns centre and facing
together. Against 0.2.0, on the same frames and the same witness
([metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_witness_changed=0] and [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_witness_changed=0] changed):

| Self cone against the joined light | 0.2.0 (track facing) | 0.3.0 (teardrop facing) |
|---|---|---|
| Ascent precision | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_precision=0.6773] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_precision=0.7435] |
| Ascent recall | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_recall=0.5556] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_recall=0.6556] |
| Ascent F1 | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_f1=0.6104] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_f1=0.6968] |
| Ascent cast cones | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_cast_all=134] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_cast_all=143] |
| Lotus precision | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_before_precision=0.7707] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_precision=0.7657] |
| Lotus recall | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_before_recall=0.4561] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_recall=0.4784] |
| Lotus F1 | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_before_f1=0.573] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_f1=0.5889] |
| Lotus cast cones | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_before_cast_all=718] | [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_cast_all=799] |

On the frames both versions cast, Ascent's F1 rises from
[metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_before_cast_f1=0.6936] to [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_cast_f1=0.7752] and Lotus's precision from
[metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_before_cast_precision=0.7707] to [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_cast_precision=0.7773]. Lotus's
pooled precision falls by 0.005 because the teardrop casts on frames whose
bearing the track refused, and those agree with the light less often. On
Lotus the teardrop supplies origin and facing on
[metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_src_teardrop_teardrop=713] cast cones and the ring fit and track on
[metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_src_ring_fit_track=86]; [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_src_bearing_refused=33] frames with light
still cast nothing. Against the logged predictions: F1 held (Ascent F1 +0.086,
precision +0.066), F2 held, F3 held.

**The stored vision and the slivers.** `reticle vision` stores 0.3.0 for
e78e75b2d191 and a06f04a0059f. `light_refusals` now refuses
[metric:vision_origin_eval/light-refusals@all-labelled#viewcone_refused=17] of [metric:vision_origin_eval/light-refusals@all-labelled#viewcone_n=19] viewcones, against
[metric:vision_origin_eval/light-refusals@all-labelled#viewcone_refused_before=16] under 0.1.0 and 0.2.0, and
[metric:vision_origin_eval/light-refusals@all-labelled#ability_refused=0] of [metric:vision_origin_eval/light-refusals@all-labelled#ability_n=34] abilities. The new refusal is the
43.35 s sliver, through the stored vision (share
[metric:vision_origin_eval/light-refusals@all-labelled#sliver_43350_vision_share=0.807]): the flipped lobe E3 found there no longer
turns the cone away. 36.9 s and 40.65 s still pass; the vision covers neither.
F4 failed in the direction it could not rule out.

## E6: ally and enemy teardrops

The labels settled the self facing: the teardrop read it to a median 2.2
degrees on Lotus, the ring fit flipped half the time. Teammates carry the same
ring fit (`minimap.ally_icons`, "the key reaches past the circle in ONE
direction"), and so does the prototype enemy ring (`minimap_ring_fit`).
`prototypes/icon_teardrop.py` (`icon-teardrop-0.1.0`, task
`icon-facing-20260928`) fits the same silhouette to both, with a colour key
and three radii per class, calibrated on held-out minutes (every fourth) of
5822b6646448 (Lotus, C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) and
a06f04a0059f (Ascent, C:\Users\grant\Videos\2026-08-26 09-56-37.mp4):

| class | key | r_in, r_out, apex (px) | refuses |
|---|---|---|---|
| ally | min(G, B) - R, off where B exceeds G | 8.5, 10.5, 19 | NCC under 0.5; a facing 90 degrees away within 0.05 |
| enemy | R - max(G, B) | 7.5, 10.5, 18 | the same, and under 40% of the ring keyed away from the lobe |

The ally ring turns pale, nearly white, on the side away from the lobe, so a
ring-coverage gate refused real teammates and the ally class has none; the
production detector's own gates and barrier rule stand in for it. The enemy
gate refuses spawn barriers and red map fills, which the enemy ring fit takes
for icons.

On 150 frames per session outside the calibration minutes:

| | Lotus | Ascent |
|---|---|---|
| ally read rate | [metric:icon_teardrop/stats@5822b6646448#ally_read_rate=0.894] | [metric:icon_teardrop/stats@a06f04a0059f#ally_read_rate=0.949] |
| ally: ring and teardrop over 90 deg apart | [metric:icon_teardrop/stats@5822b6646448#ally_ring_vs_teardrop_over90=0.207] | [metric:icon_teardrop/stats@a06f04a0059f#ally_ring_vs_teardrop_over90=0.136] |
| ally stationary jitter, teardrop / ring (deg) | [metric:icon_teardrop/stats@5822b6646448#ally_jitter_rms20_deg=0.6] / [metric:icon_teardrop/stats@5822b6646448#ally_ring_jitter_rms20_deg=2.02] | [metric:icon_teardrop/stats@a06f04a0059f#ally_jitter_rms20_deg=0.43] / [metric:icon_teardrop/stats@a06f04a0059f#ally_ring_jitter_rms20_deg=1.66] |
| enemy read rate | [metric:icon_teardrop/stats@5822b6646448#enemy_read_rate=0.511] | [metric:icon_teardrop/stats@a06f04a0059f#enemy_read_rate=0.26] |
| enemy: ring and teardrop over 90 deg apart | [metric:icon_teardrop/stats@5822b6646448#enemy_ring_vs_teardrop_over90=0.217] | [metric:icon_teardrop/stats@a06f04a0059f#enemy_ring_vs_teardrop_over90=0.231] |
| enemy stationary jitter, teardrop / ring (deg) | [metric:icon_teardrop/stats@5822b6646448#enemy_jitter_rms20_deg=1.33] / [metric:icon_teardrop/stats@5822b6646448#enemy_ring_jitter_rms20_deg=3.2] | [metric:icon_teardrop/stats@a06f04a0059f#enemy_jitter_rms20_deg=1.25] / [metric:icon_teardrop/stats@a06f04a0059f#enemy_ring_jitter_rms20_deg=4.67] |

The enemy read rate counts the enemy detector's false candidates in its
denominator; on the contact sheets most Ascent refusals are red floor, pings,
death marks and teammates the red key caught, not enemies. Contact sheets
show the teardrop on the lobe wherever the two readers disagree on a lone
icon; in stacks of three or more it sometimes fits another icon's lobe. The
jitter bounds precision, not accuracy: no light witness exists for enemies,
and the drawn light judged ally facings only through `resolve_lobe`.

**The labels.** `prototypes/label_icon_facing.py` asks the player, blind,
for the centre and tip of about 60 ally and enemy icons from both sessions,
drawn in strata: the two readers over 90 degrees apart, 20 to 90 apart, within
10, one reader refusing, uniform, stacked, and (allies) yellow at the lower
left where the carried spike is drawn. Answers go to the store's
`labels/icon_facing_20260928.jsonl`; `prototypes/icon_facing_eval.py` scores
the teardrop, the raw ring facing and (allies) the ring facing after
`resolve_lobe`, per class and stratum. Predictions C1-C4 and L1-L2 are logged
in the store's `notes/predictions.jsonl`.

**The scores (2026-09-29).** The player answered all 60 items: allies
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_answer_facing=25] facings,
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_answer_not_icon=2] not an icon and
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_answer_cant_tell=3] can't tell; enemies
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_answer_facing=19],
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_answer_not_icon=10] and
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_answer_cant_tell=1]. `icon_facing_eval`
recomputes each reader from the crop cache; the teardrop's facings match
the ones drawn when the items were prepared, to the degree, wherever both read.
Against the player's facing:

| reader | ally n | ally median error | ally flipped | enemy n | enemy median error | enemy flipped |
|---|---|---|---|---|---|---|
| teardrop | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_n=23] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_median_abs_deg=2.485] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_flip=0.0] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_all_n=17] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_all_median_abs_deg=1.685] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_all_flip=0.0] |
| raw ring | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_all_n=23] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_all_median_abs_deg=81.326] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_all_flip=0.478] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_ring_all_n=18] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_ring_all_median_abs_deg=69.651] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_ring_all_flip=0.389] |
| ring after `resolve_lobe` | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_lobe_all_n=23] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_lobe_all_median_abs_deg=26.581] | [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_lobe_all_flip=0.087] | | | |

Every teardrop facing lies within 10 degrees of the player's
([metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_within10=1.0] of allies,
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_all_within10=1.0] of enemies). Where the
two readers were drawn over 90 degrees apart, the ring flips on
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_flip_flip=1.0] of the
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_ring_flip_n=6] ally items and the
teardrop on none: the disagreements are the ring's errors. The teardrop read
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_read_not_icon=4] of the enemy items the
player called not an icon (a red ping disc, a portrait tile, red floor, red X
marks) and refused
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#enemy_teardrop_refused_not_icon=6]; its enemy
read rate still counts such candidates.

**Ability glyphs among the items.** The player said a few items were
abilities with the teardrop shape, one of which he marked anyway. The contact
sheet of all 60 crops shows four items marked with a centre and tip that are
not agent portraits: a white animal glyph on a dark disc in a red ring
(`a06f04a0059f` 104.2 s) and a blue orb in a teal ring (`5822b6646448`
623.9 s, 641.6 s and 1779.8 s). They are candidates, not answers: the store's
`labels/icon_facing_20260928/ability_candidates.json` lists them and
`ability_candidates.png` shows them for the player to confirm; the label
file is unchanged. With the four left out (`--exclude`), the teardrop errs
by [metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#ally_teardrop_all_median_abs_deg=2.16] on
[metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#ally_teardrop_all_n=20] allies with
[metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#ally_teardrop_all_flip=0.0] flipped, and on
enemies as before (the enemy candidate was one the teardrop refused); the raw
ring flips on [metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#ally_ring_all_flip=0.5] of allies
and [metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#enemy_ring_all_flip=0.412] of enemies.
The teardrop reads the three ally candidates as confidently as agents: it
does not tell a teardrop-shaped ability icon from a teammate.
Item #15 on the sheet (`5822b6646448` 758.4 s, answered not an icon, so
already out of scoring) shows the white creature glyph that Wingman's icon
carried at 404.5-408.5 s before it planted the spike
[domain:abilities/gekko-wingman-plant-minimap]: probably a Wingman glyph,
pending the player's confirmation.

*Superseded (2026-09-29):* the player answered every candidate. The three
blue orbs (#36, #58, #59) are Omen, a teammate; #36 and #58 overlap other
ally icons. #15 is Gekko's Wingman and #23 Skye's Trailblazer
[domain:abilities/skye-trailblazer-enemy-minimap-glyph], both ability glyphs.
His verdicts sit beside the candidates file in the store
(`ability_candidates_verdicts.jsonl`); the label file is unchanged. So the
valid ally figures are the all-items ones above (teardrop median
[metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_median_abs_deg=2.485]
on [metric:icon_facing_eval/labels@5822b6646448+a06f04a0059f#ally_teardrop_all_n=23]
allies, none flipped), and the "left out" ally figures, which dropped three
Omen icons, are superseded. For enemies the valid figures leave #23 out:
the teardrop's are unchanged, since it refused #23, and the raw ring flips on
[metric:icon_facing_eval/labels-excl@5822b6646448+a06f04a0059f#enemy_ring_all_flip=0.412]
of enemies. The teardrop did read the three Omen icons: it reads them as
agents because they are agents, and the sentence above that it cannot tell a
teardrop-shaped ability icon from a teammate rests on no confirmed example
among the labels. #15, a confirmed ability glyph, was read.

**A portrait gate (2026-09-29).** An agent icon holds the portrait of one of
its side's five agents; a ping, an X mark, floor, a portrait tile or an
ability glyph holds none. `prototypes/icon_portrait_gate.py`
(`icon-portrait-gate-0.1.0`) scores the portrait inside each teardrop fit
with the self icon's and teammate channel's rendered-art model
(`ally_portrait.align_icon` at the teardrop's centre, `portrait_features`,
`identity.rendered_art_fit`) against the side's lineup
(`identity.side_candidates`), and keeps the fit as an agent icon only where
the lineup explains the portrait. It rests on the lineup prior and names
nobody. Three rules were fixed before the labels were scored: A, the
owner's `teammate_fit_refusal` at its stored threshold; B, the fit at most
the 99th percentile of the stored self-icon frames' fit to their ally five,
[metric:icon_portrait_gate/calibration@self_icon-18#b_max=6.9994], over
[metric:icon_portrait_gate/calibration@self_icon-18#frames=5582] frames of
the other lineup sessions; C, the closest of all 29 rendered references lies
in the side's set, the other 24 standing only as the null a non-portrait
falls to.

On the labels (kept of each class):

| side, class | n | A | B | C |
|---|---|---|---|---|
| ally, agent icon | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_true_icon_n=24] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_true_icon_kept_A=24] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_true_icon_kept_B=24] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_true_icon_kept_C=24] |
| ally, not an icon | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_not_icon_n=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_not_icon_kept_A=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_not_icon_kept_B=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_not_icon_kept_C=1] |
| ally, ability glyph (#15) | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_ability_glyph_n=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_ability_glyph_kept_A=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_ability_glyph_kept_B=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#ally_ability_glyph_kept_C=0] |
| enemy, agent icon | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_true_icon_n=17] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_true_icon_kept_A=17] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_true_icon_kept_B=17] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_true_icon_kept_C=17] |
| enemy, not an icon | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_not_icon_n=10] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_not_icon_kept_A=10] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_not_icon_kept_B=10] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_not_icon_kept_C=2] |
| enemy, ability glyph (#23) | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_ability_glyph_n=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_ability_glyph_kept_A=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_ability_glyph_kept_B=1] | [metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_ability_glyph_kept_C=0] |

Of the four enemy not-icons the teardrop reads, C keeps
[metric:icon_portrait_gate/labels@5822b6646448+a06f04a0059f#enemy_not_icon_kept_C_td=0].
C keeps two red ping triangles and the ally not-icon. A and B reject
nothing: the self-icon calibration's tail sits above every not-icon, and
above A's own threshold. The score itself separates the labelled classes
where the gate reads it: at the teardrop's centre every agent icon fits
under every not-icon and glyph. That gap was seen on the labels and sets
no rule. At the detector's centre the enemy agent icons fit several times
worse, and the stored self-icon frames are fitted at the ring fit's
centre, which may explain their tail. On the same self frames rule C keeps
only [metric:icon_portrait_gate/calibration@self_icon-18#c_keep=0.5262].

On 40 unlabelled frames per session outside the calibration minutes, A and
B reject no ally fit, and C rejects
[metric:icon_portrait_gate/sample@5822b6646448#ally_reject_C=0.036] of the
Lotus and [metric:icon_portrait_gate/sample@a06f04a0059f#ally_reject_C=0.036]
of the Ascent ally fits: a Wingman glyph and red floor, and three teammates,
two of them carrying the spike glyph across the portrait. It keeps a red
ping disc. On 223d636bf8d2 (C:/Users/grant/Videos/2026-08-23 20-09-01.mp4)
the widget is 331 px, where the teardrop's constants do not hold: its
centres miss the portraits, and C rejects
[metric:icon_portrait_gate/sample@223d636bf8d2#ally_reject_C=0.821] of the
ally fits, nearly all teammates. The sheets are in the store's
`analysis/portrait-gate-20260929/` (`labels_sheet.png`,
`sample_rejected.png`, `sample_kept.png`). No rule is ready to wire; the
prototype carries `"wire": "no"`. Predictions G1-G7, their corrections and
the outcome are the `portrait-gate-20260929` rows of the store's
`notes/predictions.jsonl`: G1, G2 and G3 failed for B, G4-G6 passed, and the
falsifier was met.

The gate cannot work where the portrait is not seen: a stack or a carried
spike glyph over it, a widget size the teardrop was not fitted for, a widget
turned 180 degrees, whose portraits arrive upside down after the resample
[domain:minimap/upright-icons-on-turned-map] (not measured; the prototype
does not turn them), a red portrait [domain:minimap/red-portrait-states],
and a side whose lineup has a blind slot, where it abstains.

**Rule B at the teardrop's centre (B', 2026-09-29).** B' re-reads the
self frames at the self teardrop's centre (`teardrop.fit_teardrop` on the
crop cache, 60 frames per session) before taking the same percentile. Of
[metric:icon_portrait_gate/calibration-teardrop@self_icon-18#frames=884]
frames the teardrop reads, the fits' median is
[metric:icon_portrait_gate/calibration-teardrop@self_icon-18#fit_p50=0.883]
and the threshold
[metric:icon_portrait_gate/calibration-teardrop@self_icon-18#bt_max=3.8023],
half the first one and still above every labelled not-icon. B' keeps
[metric:icon_portrait_gate/labels-bt@5822b6646448+a06f04a0059f#ally_true_icon_kept_Bt=24]
ally and
[metric:icon_portrait_gate/labels-bt@5822b6646448+a06f04a0059f#enemy_true_icon_kept_Bt=17]
enemy agent icons, and also keeps
[metric:icon_portrait_gate/labels-bt@5822b6646448+a06f04a0059f#enemy_not_icon_kept_Bt=10]
of the ten enemy not-icons and both glyphs. On the Lotus and Ascent sample
it rejects
[metric:icon_portrait_gate/sample-bt@5822b6646448#ally_reject_Bt=0.0] of
the Lotus ally fits and one red-floor enemy fit, and it keeps the Wingman
glyph. The sheets are `sample_rejected-bt.png` and `sample_kept-bt.png`
in the same store folder. B1 and B2 failed, B3 passed, and the falsifier was met.

The tail explains why. On `calibration_teardrop_tail.png`, most of the 32
worst self frames carry the spike glyph across the portrait, and three
are teardrop fits off any icon. Real icons under the spike fit as badly as
pings and glyphs, so no per-frame threshold at a percentile of real icons
separates them. The spike reader already sees the glyph: cross-reference
it, flagging a carrier before the portrait is scored, and calibrate on
frames with no glyph near the icon. That is the next experiment, with
its own prediction.

**Carriers flagged, calibration spike-clean (Bs, 2026-09-29).** Bs reads
the stored spike rows (`spike-0.2.0`, the reading nearest in time within
half a second). It flags a fit as the spike's carrier where an accepted
carried glyph's carrier place (`spike.carrier_offset`) holds the fit's
detector centre, and keeps a flagged fit whatever its portrait fit: a
carried spike flags its carrier and never rejects it. The calibration
keeps B''s frames but leaves out any whose spike reading shows a glyph
near the icon. Of the 32 worst B' frames,
[metric:icon_portrait_gate/calibration-spike@self_icon-18#tail32_carrier=23]
are carriers and
[metric:icon_portrait_gate/calibration-spike@self_icon-18#tail32_near=3]
lie near a glyph. Over the
[metric:icon_portrait_gate/calibration-spike@self_icon-18#clean_frames=726]
clean frames the threshold is
[metric:icon_portrait_gate/calibration-spike@self_icon-18#bs_max=2.1578].

On the labels, scored once, Bs keeps
[metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#ally_true_icon_kept_Bs=24]
ally and
[metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#enemy_true_icon_kept_Bs=17]
enemy agent icons, all of them. It rejects the ally not-icon
([metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#ally_not_icon_kept_Bs=0]
kept) and Skye's Trailblazer
([metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#enemy_ability_glyph_kept_Bs=0]
kept). It keeps
[metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#enemy_not_icon_kept_Bs=5]
of the ten enemy not-icons, among them the two red ping triangles, and
[metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#ally_ability_glyph_kept_Bs=1]
Wingman glyph. Of the four enemy not-icons the teardrop reads, it keeps
[metric:icon_portrait_gate/labels-bs@5822b6646448+a06f04a0059f#enemy_not_icon_kept_Bs_td=1].
On the Lotus and Ascent sample it rejects
[metric:icon_portrait_gate/sample-bs@5822b6646448#ally_reject_Bs=0.0] of
the Lotus and [metric:icon_portrait_gate/sample-bs@a06f04a0059f#ally_reject_Bs=0.0]
of the Ascent ally fits. It rejects the red ping disc and the red floor
among the enemy fits. It flags four ally fits as carriers, the two Ascent
fits under the spike among them, and keeps the Wingman glyph. The sheets
are `sample_rejected-bs.png`, `sample_kept-bs.png` and
`labels_sheet_bs.png` in the same store folder.

Predictions S1-S5 passed, S2 at its bound, and the falsifier was not met.
Cross-referencing the spike reader did the work that tuning could not. It
took the carriers out of the calibration, not out of the gate: every
carrier in the sample already fit under the new threshold. What Bs still
keeps fits between 1.5 and 2.0, inside the range of real portraits, so a
portrait fit alone cannot reject it. The ping triangles, the X marks and
the Wingman glyph each need their own reader, from the match's kits and
the ping channel. [MINIMAP_OBJECTS_DESIGN.md](MINIMAP_OBJECTS_DESIGN.md)
designs that classifier and scores its first stage, which cross-references
the ping stream and X marks at stored deaths. The prototype stays `"wire": "no"`. Bs rests on 60
labels from two 465 px sessions; its threshold comes from the self icon,
not from enemies; and no 331 px or turned widget was scored.

**Bs off the 465 px widget (2026-09-29).** Bs ran unchanged on 40 frames
from each of three 331 px sessions and each half of the Iso capture
4f207c0c4e39 (C:/Users/grant/Videos/2026-09-27 19-40-58.mp4), whose widget
is drawn turned over before 1192767 ms. That widget arrives resampled into
a 331 px baked frame. Bs rejects
[metric:icon_portrait_gate/sample-bs-331@223d636bf8d2#ally_reject_Bs=0.051],
[metric:icon_portrait_gate/sample-bs-331@bfad2778a372#ally_reject_Bs=0.028]
and [metric:icon_portrait_gate/sample-bs-331@e37fdeca944f#ally_reject_Bs=0.057]
of the 331 px ally fits, and
[metric:icon_portrait_gate/sample-bs-iso@4f207c0c4e39-turned#ally_reject_Bs=0.182]
and [metric:icon_portrait_gate/sample-bs-iso@4f207c0c4e39-upright#ally_reject_Bs=0.382]
on the Iso halves. Every ally reject on the sheets is a teammate, many of
them Omen; the enemy rejects are floor. The rates look tolerable at 331 px,
but the kept fits sit close to the threshold, so the gate has no margin
there.

The teardrop's centre is the cause. Its ally and enemy constants are one
widget size's, 465 px. At 331 px its centre sits
[metric:icon_portrait_gate/centre-check@223d636bf8d2#centre_offset_px=6.2]
px from the ally ring fit's, against
[metric:icon_portrait_gate/centre-check@a06f04a0059f#centre_offset_px=1.2]
at 465 px. At the ring fit's centre, which scales with the widget, the
331 px portraits fit at a median
[metric:icon_portrait_gate/centre-check@223d636bf8d2#ring_median=0.6],
the 465 px level; at the teardrop's they fit at
[metric:icon_portrait_gate/centre-check@223d636bf8d2#teardrop_median=1.32].
The teardrop's ally and enemy constants need scaling by
`minimap.widget_scale`, as `reticle.teardrop` scales the self icon's, or a
fit per widget size.

The turned half confirms the domain fact once the portrait is centred
[domain:minimap/upright-icons-on-turned-map]. Scored at the teardrop's
centre, turning the portrait before scoring (`Bs_up`) did not help
([metric:icon_portrait_gate/sample-bs-iso@4f207c0c4e39-turned#ally_reject_Bs_up=0.25]
rejected). At the ring fit's centre, turning improves the fit on
[metric:icon_portrait_gate/orient-check@4f207c0c4e39-turned#turned_better=0.97]
of the turned half's icons, the median falling from
[metric:icon_portrait_gate/orient-check@4f207c0c4e39-turned#asis_median=1.22]
to [metric:icon_portrait_gate/orient-check@4f207c0c4e39-turned#turned_median=0.44].
It helps on only
[metric:icon_portrait_gate/orient-check@4f207c0c4e39-upright#turned_better=0.09]
of the upright half's. Predictions D2 and D5 passed. D1 failed on its
rate. D3 and D4 failed at the teardrop's centre, which confounded them. The
sheets are `sample_rejected-bs-331.png`, `sample_kept-bs-331.png`,
`sample_rejected-bs-iso.png`, `sample_kept-bs-iso.png` and
`sample_rejected-bs-iso-up.png` in the same store folder.

**Against the predictions.** L1 passed for both classes, with and without
the candidates. L2 passed. C1 and C3 passed on 2026-09-28 and the labels do
not bear on them. C2 failed: the ally read rate on Lotus fell under 0.90, the
enemy read rates under 0.60, and the teardrop refused 3 of the 4 labelled
red map fills, under the 80% claimed. C4 failed: the two readers were over 90
degrees apart on a fifth of ally frames, not the 30% predicted.

## E7: the team's error, by cause

The player's direction of 2026-09-29: team vision is a team signal, so the
whole team's joined cones must explain the lit area, or the product is useless
as a gate. He expected much of the remaining error to lie in pixel-level
geometry (one-pixel box edges, doorways, E1b), and smoke discs on the minimap
to occlude cones as walls do. `prototypes/team_vision_errors.py`
(`team-vision-errors-0.1.0`, task `vision-errors-20260929`, predictions T1-T7
logged first) scores the stored `team-vision-0.3.0` rows and gives every
disagreeing pixel one cause by ordered rules; its docstring states them. Two
arms: `prod`, the stored product (`observable`, the eligible cones), and
`any`, every stored bearing (`observable_all`, the lifecycle gate off). The
witness is `lighting.raw_lit` joined to any team icon, plus other lit
components that pass `lighting.clean_lit`. Sessions: e78e75b2d191 (Ascent
enlarged widget, C:\Users\grant\Videos\2026-09-03 19-16-07.mp4, E4's held-out
blocks, a spawn clip with no teammate drawn), 5822b6646448 (Lotus,
C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) and c40d950031bb (Ascent,
331 px, C:\Users\grant\Videos\2026-08-24 18-27-17.mp4), each on E4's twenty
6 s windows at every second cached frame. Intervals are 95% bootstraps over
windows. It reads the crop cache and stored rows only.

**The instrument.** The cones recast from the stored icons equal the stored
masks on every frame ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_mask_mismatch_px=0] and
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_mask_mismatch_px=0] pixels differ). On the frames where the product
casts a self cone, E4's self witness gives F1 [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_e5_cast_f1=0.7798] on
Ascent, beside E5's [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#e78e_after_cast_f1=0.7752],
and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_e5_cast_f1=0.6015] on Lotus: the stored rows reproduce E5. E5 drove
the chain and scored `resolved`, which the lifecycle does not gate; its Lotus
F1 of [metric:vision_origin_eval/joined-light-facing@e78e75b2d191+5822b6646448#lotus_after_f1=0.5889]
is the self cone with the gate off. The stored product scores
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_e5_f1=0.3552] on the same witness, because it casts the self cone on
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_self_frames=318] of [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_frames=700] scored Lotus frames, where the
stored bearings give one on [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_any_self_frames=498].

**The team against the self** (F1 against every lit pixel; the team-joined
light in brackets):

| | e78e75b2d191 | 5822b6646448 | c40d950031bb (331 px) |
|---|---|---|---|
| team, product | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_all_f1=0.6367] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_team_f1=0.6995]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_f1=0.4803] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_team_f1=0.5041]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_f1=0.3389] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_team_f1=0.3445]) |
| team, lifecycle off | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_any_team_all_f1=0.6367] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_any_team_all_f1=0.621] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_any_team_team_f1=0.6477]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_any_team_all_f1=0.4344] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_any_team_team_f1=0.4396]) |
| self only, product | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_self_all_f1=0.6367] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_self_all_f1=0.2097] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_self_all_f1=0.1636] |
| team precision / recall, product | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_all_precision=0.7074] / [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_all_recall=0.5788] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_precision=0.6573] / [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_recall=0.3784] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_precision=0.3562] / [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_recall=0.3233] |
| team F1 interval, product | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_all_f1_lo=0.4674] to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_team_all_f1_hi=0.7403] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_f1_lo=0.411] to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_f1_hi=0.5436] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_f1_lo=0.2555] to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_f1_hi=0.4245] |

The team explains far more light than the self cone does, but the product
still misses most of it on Lotus and at 331 px: its recall is
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_recall=0.3784] and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_recall=0.3233].

**The error by cause** (the product; share of false-lit pixels, FP, and of
missed lit pixels, FN, with intervals):

| cause | Lotus FP | Lotus FN | c40d FP | c40d FN | e78e FP | e78e FN |
|---|---|---|---|---|---|---|
| a geometry at pixel scale | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_a=0.1062] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_a_lo=0.0922]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_a_hi=0.1211]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_a=0.0063] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_a=0.102] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_a_lo=0.0848]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_a_hi=0.1298]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_a=0.0171] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fp_a=0.0587] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_a=0.0264] |
| b smoke not modelled | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_b=0.0277] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_b_lo=0.0007]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_b_hi=0.0725]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_b=0.0003] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_b=0.0695] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_b_lo=0.0015]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_b_hi=0.1348]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_b=0.0015] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fp_b=0.2643] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_b=0.0] |
| c ally ring-fit facing | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_c=0.0898] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_c_lo=0.0456]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_c_hi=0.1555]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_c=0.0341] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_c=0.0576] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_c_lo=0.0118]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_c_hi=0.1498]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_c=0.0173] | no allies | no allies |
| d angular edge | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_d=0.0926] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_d_lo=0.0738]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_d_hi=0.1185]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_d=0.0197] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_d=0.0692] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_d_lo=0.0533]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_d_hi=0.0924]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_d=0.0187] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fp_d=0.0529] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_d=0.0146] |
| e icon cast no cone | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e=0.6481] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e_lo=0.4999]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e_hi=0.7557]) | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e=0.7224] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e_lo=0.6129]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e_hi=0.7975]) | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_e=0.2596] |
| of e: lifecycle quarantined | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e_ineligible=0.4102] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e_ineligible=0.4611] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_e_ineligible=0.0] |
| of e: bearing refused | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e_no_facing=0.1235] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e_no_facing=0.2258] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_e_no_facing=0.0] |
| of e: detected, not tracked | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_e_untracked=0.1144] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_e_untracked=0.0355] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_e_untracked=0.2596] |
| f no plausible caster | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_f=0.1327] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_f_lo=0.0916]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_f_hi=0.1945]) | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_f=0.0685] | | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_f=0.4149] |
| g other | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_g=0.6837] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_g_lo=0.5822]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_g_hi=0.7484]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_g=0.1588] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_g=0.7018] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_g_lo=0.5769]-[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_g_hi=0.7946]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_g=0.1544] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fp_g=0.6242] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_g=0.2845] |

Missed light outweighs false light on Lotus ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_FN=1618329] pixels against
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_FP=513761]), so the FN column carries the error there: pixel-scale geometry holds [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_err_a=0.0303] of all
error pixels on Lotus, [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_err_a=0.0564] on c40d and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_err_a=0.0381] on
Ascent; uncast icons hold [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_err_e=0.4919] and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_err_e=0.3876]. With the
lifecycle gate off, geometry rises to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_any_err_a=0.0462] and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_any_err_a=0.0731]
and the unexplained share g to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_any_err_g=0.4438] and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_any_err_g=0.5988]. Rule
(a) comes first and takes the pixels along a wall of any wrong cone, so it
bounds pixel geometry from above.

**What the sheets show.** The sheets are in the store's
`analysis/team-vision-errors-20260929/` (`<session>_fp_<cause>.png`,
`<session>_fn_<cause>.png`, `<session>_whole.png`, `<session>_dark_frames.png`,
`c40d950031bb_self_flip.png`, `c40d950031bb_smoke_lit_lost.png`, and the
`peek_` sheets inspected before the run). Looking at them:

- *e, uncast icons*: clear teammates with clear teardrops and drawn light,
  outside the product. The quarantined bearings are the largest part.
- *g, false light*: whole cones turned the wrong way: a teammate in a stack,
  a self teardrop read at the threshold, and cones 10-30 degrees off, which
  (c) and (d) do not reach. A facing oracle that turns each cone up to 40
  degrees toward the light removes [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_facing_oracle_removed=0.1415]
  of the Lotus error and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_facing_oracle_removed=0.2194] of c40d's.
- *f, no caster*: light cut off from its icon by a stack, a spike glyph or a
  wall gap; light round a large yellow ability glyph on Lotus; and the map's
  own drawing.
- *a, geometry*: stair-stepped curved walls on Lotus and cones grazing a
  wall; most (a) pixels border a larger wrong cone.

**Where the witness or the product is wrong**, counted:

- *The map's drawing reads as light.* A site glyph on Ascent and hook marks on
  Lotus are lit in half or more of the frames with no caster: they are
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fn_f_static=0.3408] of the product's missed light on Ascent and
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_f_static=0.0978] on Lotus, none on c40d. The lighting reference
  calls these pixels known; the fix belongs in the baked geometry, not in a
  per-session mask.
- *Cones cast, no light.* On [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_dark_frames=35] c40d frames and
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_dark_frames=17] Lotus frames the cast cones find under 5% of their
  pixels lit: [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_dark=0.2123] of c40d's false light and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_dark=0.023]
  of Lotus's. The icons are teammates, several beside a smoke disc; the light
  is simply not drawn. Whether a teammate in an enemy smoke draws no cone
  [domain:minimap/enemy-smokes-block-cones], or something else hides it, is
  the player's to answer; the frames are on `<session>_dark_frames.png`.
- *The self teardrop at 331 px.* On c40d the self cone cast along a teardrop
  facing over 90 degrees from the track's bearing holds [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_g_self_flip=0.1489]
  of the false light, against [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_g_self_flip=0.0096] on Lotus. The sheet
  shows fits at NCC 0.50 to 0.61, just over the gate, several with the
  carried spike's yellow glyph over the portrait. The labels that settled the
  teardrop came from 465 px widgets; its precision at 331 px is
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_e5_cast_precision=0.3427] against E4's self witness.
- *Smoke discs are larger than their tracks.* The birth radius comes from a
  hatched component; the drawn edge lies [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_smoke_r_gain_mean=1.899] px further
  out on Lotus and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_smoke_r_gain_mean=1.4138] px on c40d, so the analysis
  measures each frame's edge with the owner's `grey_dark`.
- *Smoke walls cost light on c40d.* There, making discs walls lowers F1 by
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_smoke_walls_df1=-0.0163]: teammates standing inside a disc still
  draw their light. Whether a cone starts inside a team smoke is a player
  question.
- *Red icons and pings* are [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fp_red=0.0155] of Lotus's false light and
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fp_red=0.0114] of c40d's; saturated glyphs [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fn_sat=0.0035] and
  [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fn_sat=0.0127] of the missed light. The menu witness covers no scored
  frame on Lotus or c40d and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_menu_frames=15] on Ascent, whose error is not
  separated.

**The fixes, ranked** by the product's F1 change (error pixels removed, net,
in brackets). Oracles read the witness and bound a fix from above.

| fix | Lotus | c40d (331 px) | e78e |
|---|---|---|---|
| lifecycle gate off | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_lifecycle_off_df1=0.1407] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_lifecycle_off_removed=0.1653]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_lifecycle_off_df1=0.0954] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_lifecycle_off_removed=-0.0141]) | no quarantine |
| facing, oracle (each cone turned up to 40 deg) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_facing_oracle_df1=0.0572] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_facing_oracle_removed=0.1415]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_facing_oracle_df1=0.0687] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_facing_oracle_removed=0.2194]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_facing_oracle_df1=-0.0018] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_facing_oracle_removed=0.0155]) |
| uncast icons cast from their teardrops | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_cast_uncast_df1=0.0587] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_cast_uncast_removed=0.0369]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_cast_uncast_df1=0.0393] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_cast_uncast_removed=-0.0669]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_cast_uncast_df1=0.0611] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_cast_uncast_removed=0.1205]) |
| ally teardrop cones | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_ally_teardrop_df1=0.0206] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_ally_teardrop_removed=0.023]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_ally_teardrop_df1=-0.0226] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_ally_teardrop_removed=-0.0506]) | no allies |
| doorways, oracle | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_doorway_oracle_df1=0.0105] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_doorway_oracle_removed=-0.0115]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_doorway_oracle_df1=0.0299] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_doorway_oracle_removed=-0.0483]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_doorway_oracle_df1=0.0128] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_doorway_oracle_removed=-0.0449]) |
| smoke discs as walls | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_smoke_walls_df1=0.0016] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_smoke_walls_removed=0.0071]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_smoke_walls_df1=-0.0163] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_smoke_walls_removed=0.0143]) | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_smoke_walls_df1=0.0239] ([metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_smoke_walls_removed=0.0998]) |
| half-angle +4 deg | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_half_plus4_df1=0.0054] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_half_plus4_df1=0.0046] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_half_plus4_df1=-0.0073] |
| half-angle -4 deg | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_half_minus4_df1=-0.01] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_half_minus4_df1=-0.0078] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_half_minus4_df1=-0.0135] |
| every box edge passable | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_boxedge_open_df1=-0.1599] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_boxedge_open_df1=-0.087] | [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_boxedge_open_df1=-0.168] |

1. **Missing cones first.** The lifecycle's quarantine is the largest single
   loss: it drops teammates' and the player's own cones that the light
   confirms. Why it quarantines them is the lifecycle's `adjudication`
   row, which `team_vision` computes and does not store; read that reason
   before changing the gate. Casting refused and untracked icons
   from their teardrops adds the next share.
2. **Facing second.** A cone turned the wrong way is most of the false light.
   The ally teardrop recovers about a third of the facing oracle's F1 gain
   on Lotus and hurts at 331 px, where it reads [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_ally_td_read=0.6921] of ally cones
   (against [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_ally_td_read=0.9189]) with constants fitted at 465 px; the self
   teardrop misreads at 331 px. The teardrop needs a scale check at 331 px
   before any team cone takes it.
3. **Pixel geometry third.** Its bound is small: (a) holds 3-7% of the error,
   and opening only the box edges beside missed light gains at most
   [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_fix_doorway_oracle_df1=0.0105] and [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_fix_doorway_oracle_df1=0.0299]
   in F1. Opening every box edge floods the map.
4. **Smoke fourth.** Walls gain little on Lotus, a tenth of the error on the
   Ascent spawn clip, and cost light on c40d.
5. **The half-angle last.** Four degrees either way moves F1 by at most
   [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#e78e_prod_fix_half_minus4_df1=-0.0135]; 51.5 stays.

**Against the predictions.** T1 held (team over self by
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_team_all_f1=0.4803] to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#lotus_prod_self_all_f1=0.2097] and
[metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_team_all_f1=0.3389] to [metric:team_vision_errors/causes@e78e75b2d191+5822b6646448+c40d950031bb#c40d_prod_self_all_f1=0.1636]; equal on the spawn
clip). T2 held. T3 failed: uncast icons took about two-thirds of the missed
light, not 30-45%, and geometry, ally facing and the angular edge each took
far less than predicted. T4 failed: g, whole cones turned wrong, took about
70% of the false light. T5 held only in its "not a majority" clause:
geometry holds 3-6% of the error, under the 15% floor. T6 failed: the
lifecycle gate, which it did not name, ranks first; the ally teardrop removes
under 5%; opening box edges destroys precision. T7 failed: the map's drawing
and the frames with no drawn light exceed 5% of the error. The falsifier was
not met. The player's hypothesis that pixel-level geometry holds much of the
error is refuted on these three sessions at the stored product: missing and
misdirected cones hold most of it.

**Questions for the player**, each with its sheet: does a teammate inside a
team smoke still draw a cone (`c40d950031bb_smoke_lit_lost.png`); what hides
every cone on the `dark_frames` sheets (an enemy smoke, a death, a flash);
and is the large yellow glyph on Lotus that lights the floor round it an
ability (`5822b6646448_fn_f.png`, 1617.9 s).

## E8: why the lifecycle quarantines confirmed cones

E7 left one question unread: why `minimap_lifecycle` withholds cones the
drawn light confirms. `prototypes/vision_lifecycle.py`
(`vision-lifecycle-0.1.0`, task `vision-lifecycle-20260929`, predictions
L1-L5, G1-G4 and G1b-G4b logged first) replays `team_vision` over each
session's whole minimap crop cache with the masks off, keeps every
adjudication row with what the lifecycle saw when it decided, and reruns
the lifecycle from those stored inputs with no pixels. It reads the crop
cache and stored rows only. Sessions: 5822b6646448 (Lotus,
C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) and c40d950031bb (Ascent,
331 px, C:\Users\grant\Videos\2026-08-24 18-27-17.mp4).

**The instrument.** The replay's `eligible` flags equal the stored rows' on
every frame of both sessions, and the stored gate and the gate off reproduce
E7's F1 on E7's frames ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_stored_f1=0.4803] and [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_off_f1=0.621]
on Lotus, [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_stored_f1=0.3389] and [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_off_f1=0.4344] on c40d).

**The stored reason says nothing.** Every quarantined row carries the same
string, "origin or continuity needs corroboration" ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_reason_strings=1]
distinct reason on [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_quarantined_rows=5961] c40d rows and
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_reason_strings=1] on [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_quarantined_rows=9569] Lotus rows).
Read from what the lifecycle saw instead:

| role, refusal | c40d rows | c40d entries | Lotus rows | Lotus entries |
|---|---|---|---|---|
| ally, no live anchor of its role | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_no_live_anchor_of_role_rows=2274] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_no_live_anchor_of_role_entries=120] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_no_live_anchor_of_role_rows=1549] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_no_live_anchor_of_role_entries=72] |
| self, no live anchor of its role | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_self_no_live_anchor_of_role_rows=2210] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_self_no_live_anchor_of_role_entries=60] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_self_no_live_anchor_of_role_rows=4659] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_self_no_live_anchor_of_role_entries=159] |
| ally, live anchors, none within reach | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_beyond_reach_rows=1446] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_beyond_reach_entries=127] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_beyond_reach_rows=3330] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_beyond_reach_entries=233] |
| ally, own key jumped | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_jump_rows=21] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_jump_entries=7] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_jump_rows=5] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_jump_entries=4] |
| ally, ambiguous parents | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_ambiguous_rows=9] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_ally_ambiguous_entries=6] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_ambiguous_rows=24] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_ally_ambiguous_entries=7] |

An entry is the frame a key first goes ineligible; [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_inherited_share=0.9461]
of c40d's quarantined rows and [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_inherited_share=0.9502] of Lotus's are
inherited from one. **The quarantine cannot heal**, for two reasons in the
lifecycle's own rules:

1. A quarantined row is never an anchor ("persistence of a quarantined
   candidate cannot corroborate itself"), so its key stays quarantined for
   the life of its track, unless it walks within reach of another entity's
   anchor and takes that entity's id.
2. The boundary that admits appearances (`left_censored`) opens only when no
   eligible anchor of ANY role is live. An ally's anchors expire 500 ms after
   it is last seen, under a stack or the self icon; one live self anchor
   keeps the boundary shut, and the ally's next track is an unexplained
   appearance. The same holds for the self icon while any ally is eligible.

`reticle vision` passes no origin events (its coverage row says
`origin_events: 0`), so no round start or revive ever explains an
appearance. The pre-registered taxonomy failed here: `gap_reborn` took nearly
every entry, because a minutes-old eligible row is always within walking
reach; the table above is the refusal read from the same stored view.

**Does the light confirm the withheld cones?** On E7's scored frames a
quarantined cone is *confirmed* when half of its pixels (outside the
product's cones, where 30 or more remain) are lit:
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_light_confirmed=407] of [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_quarantined_icons=530] Lotus
icons ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_confirmed_share=0.814] of those with a cone) and
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_light_confirmed=203] of [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_quarantined_icons=472] c40d icons
([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_confirmed_share=0.5356]). L4 held on Lotus and failed on c40d, where
E7 found the 331 px facings poor.

**The sheets** (store `analysis/vision-lifecycle-20260929/`,
`<session>_<group>.png`; crop left, right the light in cyan, the product's
cones in green, the withheld cone and its icon in red):

- `*_ally_released_confirmed`: every tile a teammate's teardrop and portrait
  beside the light it draws. Wrong quarantines.
- `*_ally_released_not_confirmed`: teammates again, most in stacks with the
  cone turned away from the light (a facing error, E7's cause g); two are
  not icons: Lotus 1836.00 s (`ally:624`, bare floor) and c40d 808.83 s
  (`ally:358`, the void at the widget's edge).
- `*_ally_kept`: the ghosts the gate change keeps out (Lotus 304.98 s and
  1177.97 s over the roster's count, 1397.02 s and c40d 573.83 s bare
  floor), and stacked teammates it cannot admit because the self icon under
  the stack is unobserved.
- `*_self_released`: the player's yellow teardrop every time. Wrong.
- `*_self_kept_confirmed`, `*_self_kept_not_confirmed`: a yellow teardrop
  drawn and lit seconds after the killfeed's death of the player (Lotus
  1617.17 s, 7 s after the death at 1610.5 s; c40d 613.12 s). Whose icon it
  is waits on the player.

A Lotus death at 845.0 s the death adjudicator calls a second life (Run It
Back); the player's icon drew light at 850 s, so a second life is not a
death here.

**Cross-reference, and the gate change.** Other channels already count the
team, and none reads the minimap's light:

- the roster's living allies (`roster`, question `alive-count`), which
  `round_lifetimes.ally_capacity` turns into the ally icons it licenses;
- the death verdicts the killfeed marks as the player's own
  (`adjudication.death`, `kf_player_death`, less `is_second_life`), in the
  round the adjudicator assigns;
- the HUD's round bounds (`rounds.build_rounds`).

`CorroboratedLifecycle` runs the stock rules unchanged and admits only a row
they refuse as an unexplained appearance: an ally when every ally observed
this frame fits the roster's capacity (a frame with more admits none), and
the self icon when the roster reads five allies alive or the player has no
killfeed death this round. An admitted row keeps `refused_as` and names its
evidence in `admitted_by`, and becomes an anchor, so the key continues from
then on; nothing earlier is rewritten. The light gates nothing, so scoring
against the light stays independent. The `spectated` variant also admits the
self icon after the player's death while the roster reads an ally alive; it
rests on the unconfirmed reading that the yellow icon then belongs to the
spectated teammate.

**Team F1** (the stored gate; gain over it with a window bootstrap):

| windows | gate | c40d F1 | c40d gain | Lotus F1 | Lotus gain |
|---|---|---|---|---|---|
| E7's (design) | stored | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_stored_f1=0.3389] | | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_stored_f1=0.4803] | |
| | off | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_off_f1=0.4344] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_off_df1=0.0954] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_off_f1=0.621] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_off_df1=0.1407] |
| | corroborated | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_corroborated_f1=0.435] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_studied_corroborated_df1=0.0961] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_corroborated_f1=0.6079] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_studied_corroborated_df1=0.1276] |
| held-out, offset 0 | stored | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_stored_f1=0.3599] | | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_stored_f1=0.4743] | |
| | off | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_off_f1=0.4009] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_off_df1=0.041] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_off_f1=0.5893] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_off_df1=0.115] |
| | corroborated | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_corroborated_f1=0.3992] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_corroborated_df1=0.0394] ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_corroborated_df1_lo=-0.029] to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_corroborated_df1_hi=0.1367]) | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_corroborated_f1=0.5769] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_corroborated_df1=0.1026] ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_corroborated_df1_lo=0.0] to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_corroborated_df1_hi=0.2115]) |
| | spectated | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_spectated_f1=0.4024] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_spectated_df1=0.0426] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_spectated_f1=0.5889] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_spectated_df1=0.1146] |
| held-out, offsets 0.25, 0.75 | stored | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_stored_f1=0.265] | | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_stored_f1=0.565] | |
| | off | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_off_f1=0.3764] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_off_df1=0.1114] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_off_f1=0.6157] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_off_df1=0.0507] |
| | corroborated | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_f1=0.3636] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_df1=0.0986] ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_df1_lo=0.0566] to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_df1_hi=0.1419]) | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_f1=0.587] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_df1=0.022] ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_df1_lo=0.0061] to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_df1_hi=0.0455]) |
| | spectated | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_spectated_f1=0.3707] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_spectated_df1=0.1057] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_spectated_f1=0.6052] | [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_spectated_df1=0.0402] |

Precision under the change: c40d [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_stored_precision=0.4594] to
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout_corroborated_precision=0.4084] on the first held-out set and
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_stored_precision=0.3409] to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_precision=0.3833] on
the second; Lotus [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_stored_precision=0.586] to
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout_corroborated_precision=0.6362] and [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_stored_precision=0.6257]
to [metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_precision=0.6303]. The first held-out set scored 12
Lotus windows and the change touched three, so I widened it before scoring
the second (G1b-G4b logged first).

**Against the predictions.** L1, L2 and L5 held; L3 held as worded while its
taxonomy failed; L4 held on Lotus only. G1 failed (c40d gained under +0.05 on
the first held-out set and Lotus's interval touches zero); G2 failed on c40d's
first set; G3 and G4 held. On the widened set c40d gained
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#c40d_heldout2_corroborated_df1=0.0986] and kept its precision; Lotus gained only
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_corroborated_df1=0.022] against the gate off's
[metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_off_df1=0.0507] (G1b and G3b failed there), and the `spectated`
variant recovers most of the rest ([metric:vision_lifecycle/gate@c40d950031bb+5822b6646448#lotus_heldout2_spectated_df1=0.0402]). The
falsifier, a gain under +0.02, was not met.

**What the gate should become.** The ally rule keeps the right quarantines
(ghosts over the roster's count) and releases the wrong ones without the
light. The self rule is right while the player lives; after his killfeed
death the yellow icon still draws light, and that is the remaining loss on
Lotus. The quarantine's two structural faults deserve the owner's attention
before any threshold: a quarantined key can never heal on its own evidence,
and one role's anchor keeps another role's boundary shut.

**Proposed stored rows.** `team_vision`'s frame row gains `adjudication`, one
entry per observed icon joined to `icons` by `key` (`role:track_id`), in the
form `vision_lifecycle.adjudication_record` writes: `entity_id`, `state`
(adding `corroborated_appearance`), `eligible`, `reason_code`
(`no_live_anchor_of_role`, `beyond_reach`, `ambiguous`, `jump`, or
`persisting:<code>` for a key still quarantined since an earlier refusal),
the prose `reason`, `nearest_anchor` (`dist`, `dt_ms`, `excess`, `entity`),
`refused_as`, `admitted_by` (the rule and its evidence: roster reads, death
id, round start), `alternatives`, `light_state` and `conflict`. The coverage
row names the roster, death and HUD versions beside `lifecycle_version`. The
prototype writes these rows for every frame of both sessions to its work
directory; they come to about a third of the stored product's size.

**Questions for the player**, each with its sheet: after you die, whose icon
does the minimap draw in yellow, yours or the teammate you spectate
(`5822b6646448_self_kept_confirmed.png`, 1617.17 s and 2164.57 s;
`c40d950031bb_self_kept_not_confirmed.png`, 613.12 s)?

## E9: the cones pass the drawn walls

The player read `c40d950031bb_dark_frames.png` (E7): at 572.20 s and 928.07 s
the cones pass several walls. Task `cone-walls-20260929`, predictions W1-W5
logged first; `prototypes/cone_walls.py` (`cone-walls-0.1.0`) measures, and
`reticle/occluders.py` builds the fix. Sheets are in the store's
`analysis/cone-walls-20260929/`.

**The cause is the wall classes, not the raycast and not the placement.** A
ray stopped only at `labels == BOXEDGE`, and `labels` comes from the wiki
art, warped into widget pixels with one winner per pixel. The art's thin line
work covers under half of most widget pixels and loses them to the floor
beside it; the white lines the widget itself draws were FLOOR. The map's
border (`BORDER`) never stopped a ray either, and the floor mask's dilation
let rays run into the void beyond it. The player's reading
[domain:minimap/white-lines-are-walls] is right: on Ascent the line between B
main and B site was open.

- *The raycast is sound.* The vectorised cast equals the loop reference on
  every checked cone ([metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_loop_mismatch_px=0] pixels differ), and sealing
  diagonal steps changes the measured leak by under a hundredth.
- *The baked static sits on the drawn walls* at both widget sizes: best shift
  0, scale [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_scale_x=1.0], and [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_align_baked_drawn_within_1px=0.9733] of
  the drawn line pixels on c40d lie within 1 px of the static's lines
  ([metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#a06f_align_baked_drawn_within_1px=0.9896] on a06f04a0059f).
- *The art does not.* Within 1 px of the art's walls lie
  [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_align_art_drawn_within_1px=0.6142] of c40d's drawn line pixels at 331 px
  against [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#a06f_align_art_drawn_within_1px=0.9048] on a06f04a0059f at 465 px. At
  465 px most missing lines carry art line coverage of 0.25-0.5 (lost to the
  warp's winner); at 331 px most carry none, and the art's stored fit on
  `ascent__valorant-16x9` sits about 1% small in scale.
- *Boxes.* The static draws boxes as faint closed outlines; the art carries one
  or two of their sides. Of the closed outlines on
  `ascent__valorant-16x9-bigmap`, [metric:cone_walls/boxes@all-keys#ascent__valorant-16x9-bigmap_open_to_rays=13] of
  [metric:cone_walls/boxes@all-keys#ascent__valorant-16x9-bigmap_boxes=17] were open to a ray in the old grid; on
  `sunset__valorant-16x9-bigmap` [metric:cone_walls/boxes@all-keys#sunset__valorant-16x9-bigmap_open_to_rays=15] of
  [metric:cone_walls/boxes@all-keys#sunset__valorant-16x9-bigmap_boxes=18] (`boxes_worst.png`).

**The fix.** `occluders` reads the walls and boxes from the baked static
(the builder's one capture-derived array) into an additive occluder table,
`occ` and `box_id`, stamped `occ_built_by`; `cone.passable_from` stops rays at
it; a wall is a bright line or the art's border, a box a fitted closed shape
or a faint mark, and `cone.box_crossings` reports which boxes a cone crossed
[domain:minimap/boxes-block-unless-raised]. An origin on an occluder moves to
the nearest open pixel within 2 px (`cone.snap_origin`).

**The share of each cast cone beyond a drawn wall** (the instrument: each
frame's own lines that the frame half the session away also draws, icons and
light slivers removed):

| session | widget | before | walls | walls and boxes |
|---|---|---|---|---|
| c40d950031bb | 331 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_old_beyond_share=0.3266] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_walls_beyond_share=0.0289] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#c40d_walls_boxes_beyond_share=0.0007] |
| 9acf02f98283 | 331 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#9acf_old_beyond_share=0.2856] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#9acf_walls_beyond_share=0.0327] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#9acf_walls_boxes_beyond_share=0.0021] |
| 3694746e4e54 | 331 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#3694_old_beyond_share=0.3152] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#3694_walls_beyond_share=0.046] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#3694_walls_boxes_beyond_share=0.0021] |
| a06f04a0059f | 465 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#a06f_old_beyond_share=0.2334] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#a06f_walls_beyond_share=0.0397] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#a06f_walls_boxes_beyond_share=0.0006] |
| 5822b6646448 | 465 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#5822_old_beyond_share=0.1119] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#5822_walls_beyond_share=0.0208] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#5822_walls_boxes_beyond_share=0.0] |
| 7010b3d62460 | 465 | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#7010_old_beyond_share=0.1105] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#7010_walls_beyond_share=0.0235] | [metric:cone_walls/beyond@c40d950031bb+9acf02f98283+3694746e4e54+a06f04a0059f+5822b6646448+7010b3d62460#7010_walls_boxes_beyond_share=0.0046] |

The 331 px sessions leaked more because the art's warp loses more there. The
"walls" column leaves boxes open, and the instrument counts a drawn box
outline as a wall, so its remainder is box crossings.

**E7's team F1 on E7's frames** (the product's eligible cones recast; the
before column reproduces E7):

| | c40d950031bb | 5822b6646448 | e78e75b2d191 |
|---|---|---|---|
| before | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_old_f1=0.3389] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_old_f1=0.4803] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_old_f1=0.6367] |
| walls, boxes open | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_walls_f1=0.3488] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_walls_f1=0.4658] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_walls_f1=0.6568] |
| walls and boxes | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_walls_boxes_f1=0.3195] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_walls_boxes_f1=0.4661] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_walls_boxes_f1=0.6] |
| precision, before / after | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_old_precision=0.3562] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_walls_boxes_precision=0.7147] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_old_precision=0.6573] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_walls_boxes_precision=0.7394] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_old_precision=0.7074] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_walls_boxes_precision=0.8841] |
| recall, before / after | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_old_recall=0.3233] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_walls_boxes_recall=0.2058] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_old_recall=0.3784] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_walls_boxes_recall=0.3403] | [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_old_recall=0.5788] / [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_walls_boxes_recall=0.4541] |

Precision roughly doubles at 331 px and recall falls: a cone that ran through
walls took credit for light it could not see. Of the light the old cones
reached and the new ones do not, [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_lost_uncast_share=0.6747] on c40d and
[metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_lost_uncast_share=0.3808] on Lotus is joined to a teammate the product casts
no cone for (E7's cause e); the rest is light a misdirected leaking cone
covered by chance, or a doorway the classes close. Light beyond a crossed box
is lit at [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#c40d_box_beyond_lit_share=0.5631] on c40d,
[metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#5822_box_beyond_lit_share=0.2342] on Lotus and [metric:cone_walls/f1@c40d950031bb+5822b6646448+e78e75b2d191#e78e_box_beyond_lit_share=0.9667] on
the spawn clip, where most of it lies past one floor decal the builder calls a
box: the per-box pass rate varies from near 0 to near 1, which is the case
for a per-box prior.

**Against the predictions.** W1 held. W2 held. W3 held for the static and
failed for the art, which is misplaced at 331 px. W4 failed: every session
leaked, but the 331 px sessions leaked more. W5 failed on F1: the beyond-wall
share fell under 1% on every session, but recall fell by more than 0.05 on
c40d and e78e, and F1 fell with boxes closed.

**The enemy smoke at 572.20 s.** An enemy smoke sits in the B main choke,
and the teammates' drawn light stops at it
[domain:minimap/enemy-smokes-block-cones]. With the walls closed, the cast
cones there shrink to the choke; the missing light past it is evidence for the
enemy-smoke inference, not built here.

**Proposed, not built: a per-box pass rate.** Pool, per `(key, box_id)`, the
light found beyond the box over every crossing (`cone.box_crossings`), under
a new occluder stamp; E1's pooled box-edge transparency (0.12) is the prior's
starting point, and a box whose beyond-light is lit on most crossings (a
floor decal, a stair mark) becomes passable. A jump witness would be light
beyond a box on isolated frames of an otherwise blocking box; no channel shows
one yet.

### Proposed, not built: elevation in the raycast

The floor's shade is elevation [domain:minimap/floor-shade-is-elevation], and
the baked geometry already keeps it: `map_shade` quantises the map ART into
grey rungs and warps them into widget pixels as `shade_kind` (FLOOR, RAMP,
SHADOW) and `shade_step` (rungs above the base floor). No capture enters it,
so the drawn light, the widget's transparency and a session's lighting cannot
reach it. The fetched art shows 3 floor rungs on Abyss and Lotus, 6 on Ascent,
5 on Haven, 4 on Split and Summit and 2 on Sunset, besides ramps and shadow.
Three uses, none built:

1. *A raised caster sees over a low box.* A caster whose origin sits on a
   rung above a box's surrounding floor passes that box; the stored
   `boxes_crossed` and the light beyond each crossing test it frame by frame.
2. *An overhang hides the floor below from above.* Floor on a SHADOW (under an
   overhang, like A hell) is not lit by a caster on the rung above; the drawn
   light on those pixels confirms or refutes it.
3. *A step down is not a wall.* A ray crossing from a high rung to a low one
   continues; what it lights below a drop is the light's to confirm.

The drawn light can confirm (1) and (2) directly, since both predict light or
its absence at named pixels. It cannot see height itself, so a pass the light
shows with no rung difference is a jump or an error, and is stored apart. On
`ascent__valorant-16x9` the art's placement is about 1% small in scale, so a
rung boundary there may sit 1-2 px off.

## A team-vision over-light from the spike's "?"

`team_vision` lit a spot the enemy spike had left. On Ascent a06f04a0059f the
spike glyph became a yellow "?" at 184.067 s
[domain:minimap/enemy-spike-ground-vision], which puts the spot outside the
team's vision from 184.07 s; the stored `team_vision` marked it lit (about 0.75
of a 20x20 px neighbourhood) until 186.07 s, an over-light of about 2 s. This
case derives from the player's rule, not from a labelled frame, and no label
file holds it. It joins the cause tally of E7 as a lit-but-not-seen case to
test against a cone, a wall or a smoke, not as a mislabel of the light. The
enemy carrier's icon shows no spike
[domain:minimap/enemy-carrier-no-spike-overlay], and its death raises a
broadcast [domain:hud/enemy-carrier-death-broadcast], so the drop has other
witnesses when a spike read needs one.

## E10: the teardrop in every consumer

The player's direction of 2026-09-29: the ring fit no longer supplies an
icon's centre or facing, and the teardrop reaches every consumer; team vision
is a team signal, so teammates' cones come from it too. Task
`teardrop-everywhere-20260929`; its predictions were written in
`prototypes/team_vision_eval.py` before the first arm ran and logged in the
ledger only after the results, so they are not a pre-registration.

**The owner.** `reticle.teardrop` reads the ally and enemy teardrops
(`fit_icon`, `IconPoseReader`, `icon-teardrop-0.2.0`, owner of `icon-pose`)
with E6's keys, radii and gates, scaled by `minimap.widget_scale` as the self
teardrop's are; at scale 1.0 it is E6's fit exactly. `teardrop.posed` is the
one rule every consumer asks: the ring fit finds the icon, the teardrop gives
its centre where it reads and its facing where the reader gives one, and the
ring fit's values stay beside them under `ring`.

**The ally centre at 331 px** (`prototypes/icon_teardrop.py --centre-check`,
40 frames a session; the portrait fit is the aligned portrait's median
distance to its side's art, lower is better):

| session | offset from the ring fit, unscaled / scaled (px) | read rate, unscaled / scaled | portrait fit: ring / unscaled / scaled |
|---|---|---|---|
| 223d636bf8d2 | [metric:icon_teardrop/centre-scale@223d636bf8d2#old_offset_px=6.244] / [metric:icon_teardrop/centre-scale@223d636bf8d2#new_offset_px=1.729] | [metric:icon_teardrop/centre-scale@223d636bf8d2#old_read_rate=0.448] / [metric:icon_teardrop/centre-scale@223d636bf8d2#new_read_rate=0.908] | [metric:icon_teardrop/centre-scale@223d636bf8d2#ring_fit_median=0.648] / [metric:icon_teardrop/centre-scale@223d636bf8d2#old_fit_median=1.32] / [metric:icon_teardrop/centre-scale@223d636bf8d2#new_fit_median=0.564] |
| bfad2778a372 | [metric:icon_teardrop/centre-scale@bfad2778a372#old_offset_px=6.011] / [metric:icon_teardrop/centre-scale@bfad2778a372#new_offset_px=1.597] | [metric:icon_teardrop/centre-scale@bfad2778a372#old_read_rate=0.537] / [metric:icon_teardrop/centre-scale@bfad2778a372#new_read_rate=0.91] | [metric:icon_teardrop/centre-scale@bfad2778a372#ring_fit_median=0.673] / [metric:icon_teardrop/centre-scale@bfad2778a372#old_fit_median=1.513] / [metric:icon_teardrop/centre-scale@bfad2778a372#new_fit_median=0.497] |
| e37fdeca944f | [metric:icon_teardrop/centre-scale@e37fdeca944f#old_offset_px=6.458] / [metric:icon_teardrop/centre-scale@e37fdeca944f#new_offset_px=1.566] | [metric:icon_teardrop/centre-scale@e37fdeca944f#old_read_rate=0.473] / [metric:icon_teardrop/centre-scale@e37fdeca944f#new_read_rate=0.905] | [metric:icon_teardrop/centre-scale@e37fdeca944f#ring_fit_median=0.555] / [metric:icon_teardrop/centre-scale@e37fdeca944f#old_fit_median=1.356] / [metric:icon_teardrop/centre-scale@e37fdeca944f#new_fit_median=0.515] |

The unscaled teardrop sat about 6 px off; scaled, it reads twice as often and
the portrait aligned at its centre fits the art better than at the ring fit's.
At 465 px the scale is 1 and nothing moves (a06f04a0059f,
[metric:icon_teardrop/centre-scale@a06f04a0059f#new_offset_px=1.214] px either way).

**The self teardrop at 331 px.** E7 found the self teardrop misreads on
c40d950031bb. `prototypes/team_vision_eval.py --pose-check` compares each
ungated read with the ring fit's facing after `cone.resolve_lobe`, which chose
its lobe with the same light, so the check measures agreement, not accuracy.
Self reads at NCC 0.5-0.6 point more than 90 degrees from the lobe on
[metric:team_vision_eval/pose-check@c40d950031bb#self_ncc05_over90=0.289] of c40d950031bb's,
[metric:team_vision_eval/pose-check@223d636bf8d2#self_ncc05_over90=0.275] of 223d636bf8d2's (both 331 px) and
[metric:team_vision_eval/pose-check@5822b6646448#self_ncc05_over90=0.278] of Lotus's (465 px); from 0.6 up,
[metric:team_vision_eval/pose-check@c40d950031bb#self_ncc06_over90=0.176],
[metric:team_vision_eval/pose-check@223d636bf8d2#self_ncc06_over90=0.021] and
[metric:team_vision_eval/pose-check@5822b6646448#self_ncc06_over90=0.107]. The median self read sits at NCC
[metric:team_vision_eval/pose-check@c40d950031bb#self_ncc_median=0.558] on c40d950031bb and
[metric:team_vision_eval/pose-check@223d636bf8d2#self_ncc_median=0.606] on 223d636bf8d2, against
[metric:team_vision_eval/pose-check@5822b6646448#self_ncc_median=0.705] on Lotus. Leaving the blur and the ring
width unscaled raised the NCC at 331 px but not the agreement, so the model's
scaling is not the cause. At 465 px the player's labels do not support a gate:
of the two labelled reads under 0.6, an Ascent control is right and a Lotus
item flipped. So `SelfConeReader` (`teardrop-0.3.0`) gives the centre and no
facing under `SELF_FACING_MIN_NCC` only on a widget size the labels do not
cover (`LABELLED_SCALES`), with `facing_reason` `low_ncc_unlabelled_scale`,
and the known-answer check reads as before.

**Team vision (`team-vision-0.5.0`).** Every detection is posed before the
tracker sees it, so tracks, lifecycle positions and cones all take the
teardrop's centre, and a cone observed this frame faces this frame's teardrop
facing and stops at master's occluders (E9); `cone.resolve_lobe` sees only a
ring-fit facing. Each stored icon's `pose` names its origin, facing source
and the teardrop's reasons, beside E9's `boxes_crossed`. An icon whose
teardrop gives no facing casts nothing (`RING_FALLBACK` off): a cone cast the
wrong way discards real observations downstream.

`team_vision_eval.py` scores the eligible team union against the drawn light
joined to every team icon, with the chain on master's `team-vision-0.4.0`
(walls, ring-fit ally cones, the ungated self teardrop) as the before arm; the
witness is the same in both arms on every frame. The E4 witness places each
icon by its teardrop; `--footprint disc` places it without any facing, so the
witness cannot favour the teardrop.

| session | widget | witness | precision, 0.4.0 / 0.5.0 | recall, 0.4.0 / 0.5.0 | F1, 0.4.0 / 0.5.0 |
|---|---|---|---|---|---|
| e78e75b2d191 | 465 | E4 | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_before_eligible_precision=0.8705] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_after_eligible_precision=0.8746] | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_before_eligible_recall=0.5217] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_after_eligible_recall=0.5209] | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_before_eligible_f1=0.6524] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#e78e_after_eligible_f1=0.6529] |
| 5822b6646448 | 465 | E4 | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_before_eligible_precision=0.7637] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_after_eligible_precision=0.7871] | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_before_eligible_recall=0.476] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_after_eligible_recall=0.4691] | [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_before_eligible_f1=0.5865] / [metric:team_vision_eval/joined-team-light-teardrop@e78e75b2d191+5822b6646448#lotus_after_eligible_f1=0.5878] |
| 5822b6646448 | 465 | disc | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_before_eligible_precision=0.7632] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_after_eligible_precision=0.7846] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_before_eligible_recall=0.4661] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_after_eligible_recall=0.4609] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_before_eligible_f1=0.5787] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_after_eligible_f1=0.5807] |
| 223d636bf8d2 | 331 | disc | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_before_eligible_precision=0.7038] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_after_eligible_precision=0.6922] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_before_eligible_recall=0.3462] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_after_eligible_recall=0.3321] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_before_eligible_f1=0.4641] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_after_eligible_f1=0.4488] |
| c40d950031bb | 331 | disc | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_before_eligible_precision=0.6788] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_eligible_precision=0.6522] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_before_eligible_recall=0.2106] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_eligible_recall=0.1269] | [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_before_eligible_f1=0.3215] / [metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_eligible_f1=0.2125] |

At 465 px the teardrop raises precision and holds F1; at 331 px it lowers
both. Before the walls the teardrop raised precision on every session scored,
because the ring fit's leaking cones lost more; E9's walls took that loss
away, and on 331 px widgets the ring fit's clipped cones now score better
than the teardrop's. The ally cones carry the loss: ally precision on
c40d950031bb falls from
[metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_before_ally_precision=0.7599] to
[metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_ally_precision=0.6492], holds on 223d636bf8d2
([metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_before_ally_precision=0.6854] to
[metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#223d_after_ally_precision=0.6787]) and rises on Lotus
([metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_before_ally_precision=0.7454] to
[metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#lotus_after_ally_precision=0.7678]). An NCC gate would not
recover it: on c40d950031bb the union of cones read at NCC 0.7 or more is less
precise
([metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_ncc70_precision=0.5112])
than the whole
([metric:team_vision_eval/joined-team-light-disc@c40d950031bb+223d636bf8d2+5822b6646448#c40d_after_teardrop_only_precision=0.6522]), and ally reads
there disagree with the ring's lobe on
[metric:team_vision_eval/pose-check@c40d950031bb#ally_over90=0.214] of frames, against
[metric:team_vision_eval/pose-check@223d636bf8d2#ally_over90=0.084] on 223d636bf8d2. The self gate leaves
c40d950031bb almost no self cones, since most of its self reads fall under
NCC 0.6 (above). Only labels of the
ally facing at 331 px can say whether the teardrop or the ring's lobe is
right there.

**Against the predictions.** P1 (F1 at least 0.3.0's on both E4 sessions,
Lotus up by 0.02) failed: F1 held but rose by far less than 0.02, against
0.3.0 as against 0.4.0. P2 (ally precision rises) held on Lotus, the one E4
session with teammates. P3 (pooled recall moves under 0.03) held on both.
The predictions named only the E4 sessions; off them, on c40d950031bb, ally
precision fell and recall fell by more than 0.03.

**The ally icon and self icon streams.** `minimap.AllyIconReader`
(`ally-icon-0.6.0`) poses every shape-gated fit: the glyph check, the
separation, the published position and the portrait's alignment use the
teardrop's centre, and the published facing is the teardrop's where it gives
one. The descriptor's disc (composition, `map_diff`, `interior_too_thin`)
stays at the ring fit's centre, `interior_at`: on a 331 px widget that disc
sits on `appearance.MIN_PIXELS`, and cutting it at the teardrop's fractional
centre refused a sixth more teammates; kept at the ring fit's centre it
describes as many as before. `self_icon` (`self-icon-0.5.0`) cuts and aligns
the player's portrait at the self teardrop's centre on the 465 px widget,
where E6's rule B' and `--centre-check --centre-class self` find it fits the
art far better (Lotus:
[metric:icon_teardrop/centre-scale-self@5822b6646448#new_fit_median=0.474] against the ring fit's
[metric:icon_teardrop/centre-scale-self@5822b6646448#ring_fit_median=1.013]). On 331 px widgets the same check
is mixed: the teardrop's centre fits better on c40d950031bb
([metric:icon_teardrop/centre-scale-self@c40d950031bb#new_fit_median=1.143] against
[metric:icon_teardrop/centre-scale-self@c40d950031bb#ring_fit_median=1.286]) and e37fdeca944f
([metric:icon_teardrop/centre-scale-self@e37fdeca944f#new_fit_median=1.039] against
[metric:icon_teardrop/centre-scale-self@e37fdeca944f#ring_fit_median=1.414]), ties on 223d636bf8d2
([metric:icon_teardrop/centre-scale-self@223d636bf8d2#new_fit_median=0.871] against
[metric:icon_teardrop/centre-scale-self@223d636bf8d2#ring_fit_median=0.874]) and fits worse on bfad2778a372
([metric:icon_teardrop/centre-scale-self@bfad2778a372#new_fit_median=1.008] against
[metric:icon_teardrop/centre-scale-self@bfad2778a372#ring_fit_median=0.865]). So `teardrop.self_portrait_pose`
keeps the ring fit's centre there (`origin_reason` `unlabelled_scale`), for
the self icon stream and for the ally reader's self occluder alike.

**Where the ring fit stays.** The L1 self position (`pick_self`, the
`minimap` stream): switching estimators mid-track moves the point by the
ring's lobe bias whenever the read toggles, a step `filter_track`'s speed gate
may take for a jump, and it needs its own check. The spike carrier pairing
(`spike.read_frame`, `carrier_offset`), whose constants were measured from
ring-fit centres. `minimap_dark.occluded`, which masks an icon's pixels with a
margin. Each finds or masks an icon; none casts a cone.

**The tip highlight (2026-09-29).** The player saw the teardrop's tip drawn
lighter than its rim [domain:minimap/icon-tip-highlight].
`prototypes/tip_highlight.py` (`tip-highlight-0.1.0`, not wired) reads a
facing from brightness alone: round the ring fit's centre, the brightest
fifth of the class-hued pixels between the portrait and the apex, and their
circular mean angle. `hue_mass`, the mean angle of all hued pixels, is the
control that sees only the lobe's area. Against the labels:

| label set | highlight median / flipped | teardrop median / flipped | ring median / flipped |
|---|---|---|---|
| allies, 465 px | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_highlight_median_abs_deg=7.217] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_highlight_flip=0.0] | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_teardrop_median_abs_deg=2.485] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_teardrop_flip=0.0] | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_ring_median_abs_deg=81.326] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_ring_flip=0.478] |
| enemies, 465 px | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_highlight_median_abs_deg=34.279] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_highlight_flip=0.286] | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_teardrop_median_abs_deg=1.685] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_teardrop_flip=0.0] | [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_ring_median_abs_deg=69.651] / [metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#enemy_ring_flip=0.389] |
| self, Lotus | [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_highlight_median_abs_deg=6.949] / [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_highlight_flip=0.0] | [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_teardrop_median_abs_deg=2.233] / [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_teardrop_flip=0.071] | [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_ring_median_abs_deg=105.498] / [metric:tip_highlight_eval/self@5822b6646448+controls#lotus_ring_flip=0.5] |
| allies, 331 px | [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#highlight_median_abs_deg=7.24] / [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#highlight_flip=0.053] | [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#teardrop_median_abs_deg=4.603] / [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#teardrop_flip=0.079] | [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#ring_median_abs_deg=10.164] / [metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#ring_flip=0.237] |

On 331 px allies the ring's lobe flips on
[metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#ring_lobe_flip=0.395].
The control trails the highlight on every set (465 px allies
[metric:tip_highlight_eval/labels-465@5822b6646448+a06f04a0059f#ally_hue_mass_median_abs_deg=26.213]),
so brightness carries what the lobe's area does not. The highlight trails
the teardrop wherever both read, but it disagrees with the teardrop by over
45 degrees on three of the five labelled ally and self items where the
teardrop flips; the other two are stacks, where a teammate's rim lends a
second bright tip and both readers fail. On enemies the red hue takes the
portrait's skin and red X marks inside the band, and the sheet shows no
lighter tip. Grey floor and white walls carry no hue and caused no failure.
On the 40 items of the 331 px manifest the highlight lies within 30 degrees
of the teardrop on
[metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#consistency_teardrop_within30=0.875]
and of the raw ring on
[metric:tip_highlight_eval/labels-331@c40d950031bb+223d636bf8d2#consistency_ring_within30=0.775],
which is consistency, not accuracy. The sheets are in the store's
`analysis/tip-highlight-20260929/`; predictions H1-H6 and their outcome are
the `tip-highlight-20260929` rows of `notes/predictions.jsonl`.

**Does the cone light the tip? (2026-09-29).** The player asked whether the
viewcone, drawn from near the centre along the facing, adds light at the
tip, so that the ally highlight is partly the cone. `prototypes/tip_cone.py`
(`tip-cone-test-0.1.0`) places each labelled icon's zones from the owner's
silhouette at the teardrop's centre and the label's facing, not from hue:
the lobe's body (a pixel or more inside), the tip (the lobe's outer half,
edge included), the rim away from the cone, and the floor just past the tip
and behind the rim. The ally and self lobes are opaque: the body's pixels
over a baked wall are no brighter than over floor (465 px allies
[metric:tip_cone_test/ally-465@5822b6646448+a06f04a0059f#line_obs_diff=-1.0]
grey levels where the static differs by
[metric:tip_cone_test/ally-465@5822b6646448+a06f04a0059f#line_static_diff=77.0];
331 px
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#line_obs_diff=2.25]
of [metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#line_static_diff=77.0]).
The body is lighter than the rim with or without a cone: where the owner's
raycast along the label reaches under a fifth of the floor past the tip, the
body reads [metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#ctrl_median_y_lobe_int=207.25]
against [metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#cone_median_y_lobe_int=207.5]
with a cone (331 px,
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#n_ctrl=12] controls), and the self body
[metric:tip_cone_test/self-465@5822b6646448+e78e75b2d191#ctrl_median_y_lobe_int=243.0]
against [metric:tip_cone_test/self-465@5822b6646448+e78e75b2d191#cone_median_y_lobe_int=244.0].
So the highlight is the art. The cone reaches only the lobe's edge pixels,
which blend with the floor past them: on floor, the tip zone gains
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#floor_tip_per_lit=49.6424]
grey levels from unlit to fully lit at 331 px, the body
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#floor_lobe_int_per_lit=-1.0611].
At 331 px the tip is a few pixels, mostly edge, and its excess over the rim
falls from [metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#cone_median_tip_excess=36.5]
to [metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#ctrl_median_tip_excess=22.0]
without a cone (permutation p
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#ctrl_perm_p=0.2302]).
At 465 px only [metric:tip_cone_test/ally-465@5822b6646448+a06f04a0059f#n_ctrl=3]
allies have no cone, all facing the dark void, too few to compare. The
tip-highlight reader keeps the body: a median
[metric:tip_cone_test/ally-331@223d636bf8d2+c40d950031bb#median_hl_body_frac=0.8248]
of its kept pixels at 331 px and
[metric:tip_cone_test/ally-465@5822b6646448+a06f04a0059f#median_hl_body_frac=0.8025]
at 465 px lie inside it. The enemy is no cone-free control, because its lobe
is see-through: walls show through it on the sheet, and over a baked line it
reads [metric:tip_cone_test/enemy-465@5822b6646448+a06f04a0059f#line_obs_diff=51.0]
brighter where the static differs by
[metric:tip_cone_test/enemy-465@5822b6646448+a06f04a0059f#line_static_diff=105.0],
on [metric:tip_cone_test/enemy-465@5822b6646448+a06f04a0059f#line_icons=5] icons, so the
floor beneath, often a teammate's light, shows in its tip. The sheets are in the store's
`analysis/tip-cone-20260929/`; predictions C1-C4 and their outcome are the
`tip-cone-test-20260929` rows of `notes/predictions.jsonl`.

## E11: the light chose the ring's lobe, then scored it

E10 found the ring fit's ally cones more precise than the teardrop's on
331 px widgets, while the player's 331 px ally facing labels find the
teardrop right and the ring's lobe flipped. Task
`vision-331-diagnosis-20260929`; predictions H1-H5 and the self-gate
prediction were logged in the store's `notes/predictions.jsonl` before any
measurement. Sessions c40d950031bb (C:\Users\grant\Videos\2026-08-24
18-27-17.mp4) and 223d636bf8d2 (C:\Users\grant\Videos\2026-08-23
20-09-01.mp4), E10's disc witness, crop cache only.

**The instrument judges one cone fairly.** Cast along the player's label and
along its reverse from the labelled centre, the disc witness gives the
label's cone four to six times the reverse's precision on the 38 labelled
icons, isolated or clustered (the store's
`analysis/vision-331-diagnosis-20260929/label_cones.json`). No 465 px
constant misplaces the witness at 331 px: its radius and footprint scale
with `widget_scale`, its pad and join band are 3 px either way, the cone's
half-angle is an angle, its origin snap scales and its rays run to the
first wall (H1 fails).

**The ring arm chose its facing with the light it is scored against.**
0.4.0 resolved each ring-fit lobe per frame by its lit share
(`cone.resolve_lobe`), so each of its cones is the better of two opposite
cones on nearly the metric the witness applies. At 465 px the ring's axis
itself errs, and no lobe choice rescues it; at 331 px the axis is close and
only the lobe matters, so the choice alone decides the score.
`team_vision_eval.py --variant` changes one factor at a time (disc witness,
ally precision; the `ring-lobe` variant reproduces E10's 0.4.0 arm):

| arm | c40d950031bb | 223d636bf8d2 |
|---|---|---|
| ring fit, lobe by the light (0.4.0) | [metric:team_vision_eval/joined-team-light-disc-ringlobe@c40d950031bb+223d636bf8d2#c40d_before_ally_precision=0.7599] | [metric:team_vision_eval/joined-team-light-disc-ringlobe@c40d950031bb+223d636bf8d2#223d_before_ally_precision=0.6854] |
| ring fit, no light | [metric:team_vision_eval/joined-team-light-disc-ringraw@c40d950031bb+223d636bf8d2#c40d_before_ally_precision=0.5557] | [metric:team_vision_eval/joined-team-light-disc-ringraw@c40d950031bb+223d636bf8d2#223d_before_ally_precision=0.6233] |
| teardrop (0.5.0) | [metric:team_vision_eval/joined-team-light-disc-ringraw@c40d950031bb+223d636bf8d2#c40d_after_ally_precision=0.6492] | [metric:team_vision_eval/joined-team-light-disc-ringraw@c40d950031bb+223d636bf8d2#223d_after_ally_precision=0.6787] |
| teardrop, lobe by the light | [metric:team_vision_eval/joined-team-light-disc-tdlobe@c40d950031bb+223d636bf8d2#c40d_after_ally_precision=0.7965] | [metric:team_vision_eval/joined-team-light-disc-tdlobe@c40d950031bb+223d636bf8d2#223d_after_ally_precision=0.6602] |

Without the light the ring loses to the teardrop on both sessions; given
the light's choice, the teardrop beats the ring on c40d950031bb. Cone by
cone on the same ally detections (`--matched`, c40d950031bb), the
teardrop's centre changes nothing (ring centre, teardrop facing
[metric:team_vision_eval/matched@c40d950031bb#all_ring_td_precision=0.6783] against
[metric:team_vision_eval/matched@c40d950031bb#all_td_td_precision=0.673]); the light's lobe gives
[metric:team_vision_eval/matched@c40d950031bb#all_ring_lobe_precision=0.7635], the ring's raw facing
[metric:team_vision_eval/matched@c40d950031bb#all_ring_raw_precision=0.6001] and the teardrop's reverse
[metric:team_vision_eval/matched@c40d950031bb#all_td_rev_precision=0.1403]. The gain sits where the two
readers disagree, a set the light itself selects: there the teardrop scores
[metric:team_vision_eval/matched@c40d950031bb#disagree_td_td_precision=0.2235] and its reverse
[metric:team_vision_eval/matched@c40d950031bb#disagree_td_rev_precision=0.4418]. Twelve of those
disagreements drawn at random (the store's
`analysis/vision-331-diagnosis-20260929/disagree_c40d950031bb_*.png`) show
three kinds: stacked icons, where a neighbour's light lies behind the icon;
an icon against a wall its cone crosses in the raycast; and a cone the wall
ends inside the icon's footprint, which the witness does not score. The
lobe chooser also counts the icon's own pixels, which the light mask reads
as lit: on c40d950031bb's disagreements about a third of the lit pixels
behind the chosen lobe lie inside the icon's footprint disc, which the
witness excludes (the store's `analysis/vision-331-diagnosis-20260929/disagree_c40d950031bb.json`).

So the E10 comparison measured the lobe choice, not the facing. The
teardrop stays (`team-vision-0.5.0` unchanged). A comparison on this
witness must not let an arm choose a facing with its light; the labels,
not the light, decide facing.

**The self gate at 331 px.** `SELF_FACING_MIN_NCC` rested on the self
teardrop disagreeing with the light-resolved lobe, the comparison the ally
labels overturned. The witness scores the self teardrop against its own
reverse by NCC (`--matched`):

| self NCC | c40d950031bb teardrop / reverse | 223d636bf8d2 teardrop / reverse |
|---|---|---|
| under 0.55 | [metric:team_vision_eval/matched@c40d950031bb#self_lt55_td_precision=0.4985] / [metric:team_vision_eval/matched@c40d950031bb#self_lt55_rev_precision=0.3465] | [metric:team_vision_eval/matched@223d636bf8d2#self_lt55_td_precision=0.3055] / [metric:team_vision_eval/matched@223d636bf8d2#self_lt55_rev_precision=0.8235] |
| 0.55-0.6 | [metric:team_vision_eval/matched@c40d950031bb#self_55_60_td_precision=0.8599] / [metric:team_vision_eval/matched@c40d950031bb#self_55_60_rev_precision=0.319] | [metric:team_vision_eval/matched@223d636bf8d2#self_55_60_td_precision=0.6716] / [metric:team_vision_eval/matched@223d636bf8d2#self_55_60_rev_precision=0.4727] |
| 0.6-0.7 | [metric:team_vision_eval/matched@c40d950031bb#self_60_70_td_precision=0.8095] / [metric:team_vision_eval/matched@c40d950031bb#self_60_70_rev_precision=0.2059] | [metric:team_vision_eval/matched@223d636bf8d2#self_60_70_td_precision=0.8837] / [metric:team_vision_eval/matched@223d636bf8d2#self_60_70_rev_precision=0.0363] |

Under 0.55 the reads fail: on 223d636bf8d2 the reverse scores better. From
0.6 they separate on both sessions. Between 0.55 and 0.6 they separate on
c40d950031bb and weakly on 223d636bf8d2. Removing the gate
(`no-self-gate`) raises c40d950031bb's team F1 from
[metric:team_vision_eval/joined-team-light-disc-selfgate@c40d950031bb+223d636bf8d2#c40d_before_eligible_f1=0.2125] to
[metric:team_vision_eval/joined-team-light-disc-selfgate@c40d950031bb+223d636bf8d2#c40d_after_eligible_f1=0.2583] and lowers its self
precision from [metric:team_vision_eval/joined-team-light-disc-selfgate@c40d950031bb+223d636bf8d2#c40d_before_self_precision=0.8659] to
[metric:team_vision_eval/joined-team-light-disc-selfgate@c40d950031bb+223d636bf8d2#c40d_after_self_precision=0.5564]. The gate stays at 0.6
until the player labels 331 px self facing; the witness now supports it,
and 0.55 is the candidate the labels would test.

**Against the predictions.** H1 failed (nothing unscaled misplaces the
witness). H2 held for the lobe chooser, not the witness: the light mask
reads the icon's own pixels as lit and `resolve_lobe` counts them; the
witness excludes them. H3 held in part: 0.5.0 casts fewer cones (E10's
source counts), but matched on the same detections the light's lobe still
scores higher, so population does not explain the precision. H4 failed on
the labelled items: a neighbour's cone holds few of the reverse cones' hits,
though stacks recur among the population's disagreements. H5 held: without
the light 0.4.0's ally precision falls below 0.5.0's on both sessions. The
self-gate prediction held: removing the gate raises self recall and moves
team precision by under 0.03.

## E12: the icon and the light as two witnesses of one facing

The player (2026-09-29), on E11: the vision cone was meant to inform the ally
icon's orientation, and the orientation the cone. Task
`facing-fusion-20260929`; the constants and predictions F1-F6 were logged in
the store's `notes/predictions.jsonl` before any label was scored.
`prototypes/facing_fusion.py` (`facing-fusion-0.1.0`, not wired) recomputes
every reader from the crop cache at the labelled frames; the owner's teardrop
matches the stored readings on all three sets.

**The rule.** The prior is the icon's own readers: the teardrop's NCC at every
5-degree facing about its centre, 20 nats per unit NCC, and the tip highlight
as a von Mises of 12 degrees with 15% outlier mass. The evidence is the drawn
light joined to the icon, with every team icon's footprint disc, the cones
the neighbours cast along their own teardrop facings, and light nearer an
unread neighbour all excluded; each cone is raycast to the geometry's walls
and boxes, split into 12 sectors, and each sector's lit share enters as a
Bernoulli log-likelihood ratio (0.6 lit against 0.2 background), tempered by
a third. The fusion flips the teardrop's lobe only where the posterior holds
more than half its mass on the far side, and keeps the teardrop's angle
otherwise. Each item stores its lobe log-odds per witness, every witness
disagreement and `rests_on` (the store's `analysis/facing-fusion-20260929/`).

| label set | teardrop median / flipped | highlight median / flipped | fusion median / flipped | fusion fixed / broken |
|---|---|---|---|---|
| allies, 465 px | [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_teardrop_median_abs_deg=2.485] / [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_teardrop_flip=0.0] | [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_highlight_median_abs_deg=7.217] / [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_highlight_flip=0.0] | [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_fusion_median_abs_deg=2.485] / [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_fusion_flip=0.0] | [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_fusion_fixed=0] / [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_fusion_broken=0] |
| self, Lotus | [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_teardrop_median_abs_deg=2.2325] / [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_teardrop_flip=0.0714] | [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_highlight_median_abs_deg=6.9486] / [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_highlight_flip=0.0] | [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_fusion_median_abs_deg=2.1875] / [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_fusion_flip=0.0357] | [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_fusion_fixed=1] / [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_fusion_broken=0] |
| self, Ascent controls | [metric:facing_fusion_eval/self@5822b6646448+controls#control_teardrop_median_abs_deg=1.82] / [metric:facing_fusion_eval/self@5822b6646448+controls#control_teardrop_flip=0.0] | [metric:facing_fusion_eval/self@5822b6646448+controls#control_highlight_median_abs_deg=4.0305] / [metric:facing_fusion_eval/self@5822b6646448+controls#control_highlight_flip=0.0] | [metric:facing_fusion_eval/self@5822b6646448+controls#control_fusion_median_abs_deg=1.82] / [metric:facing_fusion_eval/self@5822b6646448+controls#control_fusion_flip=0.0] | [metric:facing_fusion_eval/self@5822b6646448+controls#control_fusion_fixed=0] / [metric:facing_fusion_eval/self@5822b6646448+controls#control_fusion_broken=0] |
| allies, 331 px | [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#teardrop_median_abs_deg=4.6025] / [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#teardrop_flip=0.0789] | [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#highlight_median_abs_deg=7.2401] / [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#highlight_flip=0.0526] | [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_median_abs_deg=4.6025] / [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_flip=0.0526] | [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_fixed=1] / [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_broken=0] |

The fusion fixes two of the teardrop's five flips and breaks none of the
correct reads. Each fix has one witness: on Lotus the highlight (the prior
alone fixes it, [metric:facing_fusion_eval/self@5822b6646448+controls#lotus_prior_fixed=1]),
at 331 px the light (teardrop and light alone fix it,
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_nohl_fixed=1]).
The light alone on the teardrop's axis fixes all
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_fixed=3]
331 px flips but breaks
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_broken=3]
correct reads there and
[metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_light_lobe_broken=3]
at 465 px; E10's chooser, which counts the icon's own pixels, breaks
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_raw_broken=10]
at 331 px. So the prior is what makes the light safe to use, and the
exclusions are what make it worth using at 331 px; at 465 px the old chooser
breaks only [metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_light_lobe_raw_broken=1].
Where the excluded light carries evidence it picks the labelled lobe on
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_with_evidence_right=31]
of [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_with_evidence_n=36]
331 px items; the old chooser, on
[metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_raw_right=28]
of [metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#light_lobe_raw_n=38].

**Why the other three flips stay.** The sheets (`sheet_331.png`,
`sheet_self.png` there) and `items.json` show all three beside teammates.
On Lotus at 2027.4 s and on 223d636bf8d2 at 202.0 s the light along the label
does not join the icon: the neighbours' footprint discs and predicted cones
cut it off, so the rule scores it neither lit nor dark (at 202.0 s the
reverse cone keeps no comparable pixel). On c40d950031bb at 783.9 s the
reverse cone reads 42% lit, near the rule's break-even, and the highlight
sides with the flipped teardrop, since a neighbour's rim lends it a tip. A
full-weight light
(temper 1, post hoc) fixes the second Lotus flip
([metric:facing_fusion_eval/self-posthoc-t1@5822b6646448+controls#lotus_fusion_fixed=2])
and none more at 331 px
([metric:facing_fusion_eval/labels-331-posthoc-t1@c40d950031bb+223d636bf8d2#fusion_fixed=1]),
still breaking nothing; the weight does not limit the 331 px set, the stacks do.
Moving the angle within the kept lobe (`fusion_adjust`) helps at 465 px
([metric:facing_fusion_eval/labels-465@5822b6646448+a06f04a0059f#ally_fusion_adjust_median_abs_deg=1.5582])
and hurts at 331 px
([metric:facing_fusion_eval/labels-331@c40d950031bb+223d636bf8d2#fusion_adjust_median_abs_deg=5.7378]),
so the rule keeps the teardrop's angle.

**The other direction, measured.** On the 100 labelled frames the team's
cones, cast along the fused facings, leave
[metric:facing_fusion_eval/missing-cones@223d636bf8d2+5822b6646448+a06f04a0059f+c40d950031bb+e78e75b2d191#missing_unexplained=82841]
of [metric:facing_fusion_eval/missing-cones@223d636bf8d2+5822b6646448+a06f04a0059f+c40d950031bb+e78e75b2d191#missing_joined=217340]
joined lit pixels unexplained. Of the blobs of 20 px or more, those nearest an
icon without a facing hold
[metric:facing_fusion_eval/missing-cones@223d636bf8d2+5822b6646448+a06f04a0059f+c40d950031bb+e78e75b2d191#missing_px_unfaced=7565]
px, against
[metric:facing_fusion_eval/missing-cones@223d636bf8d2+5822b6646448+a06f04a0059f+c40d950031bb+e78e75b2d191#missing_px_faced=69805]
beside faced icons: missing cones explain little. Most unexplained light
lies beside a cone already cast: the geometry's walls cut it short, or a box
it looks over.

**Against the predictions.** F1 failed: one of three 331 px flips fixed,
none broken. F2 held. F3 held. F4 held: the fusion's median moves under
1 degree on every set. F5 held pooled (the excluded light right on 84 of 94
items with evidence, the old chooser on 83 of 97) but not at 465 px, where
the old chooser picks better. F6 failed: about a tenth, not a quarter.

**Should it be wired?** Not yet. It never did worse than the teardrop on 97
labelled reads, but two fixes on five flips is too little evidence to
change `team-vision-0.5.0`. The fusion also costs 73 raycasts per icon per
frame. The 331 px set was drawn where the old light disagreed with the
teardrop, and the test the rule needs is stacks. Labels drawn by teardrop
margin, stacked or not, with no light in the draw, would settle it.

## E13: the 331 px self and enemy labels

The player labelled two blind sets on the 331 px widget (2026-09-29), drawn
by `prototypes/label_icon_facing.py` with each reader's facing frozen in a
hidden manifest and scored by `prototypes/icon_facing_eval.py --set <set>`.
Task `labels-331-results-20260929`; each set's predictions were logged
before its first label (the `self-facing-331-labels` and
`enemy-facing-331-labels` rows of the store's `notes/predictions.jsonl`),
and their outcomes follow them there.

**The self set** holds 40 self icons on c40d950031bb (C:\Users\grant\Videos\2026-08-24
18-27-17.mp4), 223d636bf8d2 (C:\Users\grant\Videos\2026-08-23 20-09-01.mp4),
bfad2778a372 and e37fdeca944f, drawn by the self teardrop's NCC before any
gate: twelve in each of three bands and four anchors above 0.65. The player
gave a facing on [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#answer_facing=37]. The self teardrop, the self
ring fit and the tip highlight against those facings:

| self NCC | n | teardrop median / flipped | ring flipped | highlight flipped |
|---|---|---|---|---|
| 0.50-0.55 | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n50_55_n=11] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n50_55_median_abs_deg=20.58] / [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n50_55_flip=0.455] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#ring_n50_55_flip=0.273] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#highlight_n50_55_flip=0.1] |
| 0.55-0.60 | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n55_60_n=11] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n55_60_median_abs_deg=2.915] / [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n55_60_flip=0.091] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#ring_n55_60_flip=0.091] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#highlight_n55_60_flip=0.0] |
| 0.60-0.65 | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n60_65_n=11] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n60_65_median_abs_deg=4.115] / [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n60_65_flip=0.0] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#ring_n60_65_flip=0.091] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#highlight_n60_65_flip=0.1] |
| anchors | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_anchor_n=4] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_anchor_median_abs_deg=6.045] / [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_anchor_flip=0.0] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#ring_anchor_flip=0.0] | [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#highlight_anchor_flip=0.0] |

Under 0.55 the teardrop flips on almost half its reads, and there the ring
fit and the highlight flip less often than it does. From 0.55 up it errs a few
degrees. A gate at 0.55 keeps
[metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#gate_055_admitted_share=0.703] of the labelled reads, which err a
median [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#gate_055_median_abs_deg=4.062] degrees and flip on
[metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#gate_055_flip=0.038] (one of [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#gate_055_n=26]); a gate
at 0.6 keeps [metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#gate_060_admitted_share=0.405] and flips on none.
The one flip at 0.55-0.60 lies on c40d950031bb, which also holds two of the
five under 0.55 ([metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n50_55_c40d950031bb_flip=0.667] of its
[metric:icon_facing_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_n50_55_c40d950031bb_n=3]); at three items a session and
band the labels cannot set a gate per session. E11's witness agrees: from
0.55 the self teardrop's cones beat their reverses on both 331 px sessions.

**The gate.** `teardrop-0.4.0` sets the 331 px self facing gate at 0.55
(`teardrop.SELF_FACING_GATES`, asked through `self_facing_gate`; a read
under it gives the centre and no facing, `facing_reason`
`low_ncc_labelled_gate`). The 465 px widget keeps no gate, and a widget size
no labels cover keeps `SELF_FACING_MIN_NCC`, 0.6
(`low_ncc_unlabelled_scale`). `team-vision-0.6.0` casts the self cone from
the reads the new gate admits. The ally icon and self icon streams do not
move: on a 331 px widget they cut the self portrait at the ring fit's centre
(`self_portrait_pose`) and take no self facing from the teardrop.

**The fusion on the self labels.** `prototypes/facing_fusion.py --sets
s331` runs E12's rule with its constants unchanged, recomputing every reader
from the crop cache at the labelled frames, seeded at the manifest's self
detection; the recomputed teardrop matches the frozen reading on every item
([metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#recomputed_vs_stored_teardrop_max_deg=0.0] degrees apart). Its
predictions S1-S4 are the `facing-fusion-self-331-20260929` rows of the
ledger, logged before the run. Fixed and broken count against the teardrop;
"light alone" takes the teardrop's axis and chooses its lobe by the excluded
light, "old chooser" by `cone.resolve_lobe` with the icon's own pixels
counted (E10):

| self NCC | teardrop flips | fusion fixed / broken | prior fixed | light alone fixed / broken | old chooser fixed / broken |
|---|---|---|---|---|---|
| 0.50-0.55 | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_teardrop_flips_n=5] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_fusion_fixed=3] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_fusion_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_prior_fixed=2] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_light_lobe_fixed=3] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_light_lobe_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_light_lobe_raw_fixed=5] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_light_lobe_raw_broken=0] |
| 0.55-0.60 | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_teardrop_flips_n=1] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_fusion_fixed=1] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_fusion_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_prior_fixed=1] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_light_lobe_fixed=1] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_light_lobe_broken=2] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_light_lobe_raw_fixed=1] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n55_60_light_lobe_raw_broken=1] |
| 0.60-0.65 | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_teardrop_flips_n=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_fusion_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_fusion_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_prior_fixed=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_light_lobe_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_light_lobe_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_light_lobe_raw_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n60_65_light_lobe_raw_broken=1] |
| anchors | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_teardrop_flips_n=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_fusion_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_fusion_broken=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_prior_fixed=0] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_light_lobe_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_light_lobe_broken=1] | [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_light_lobe_raw_fixed=0] / [metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#anchor_light_lobe_raw_broken=1] |

In the 0.50-0.55 band the fusion fixes three of the five flips and breaks
none of the six correct reads; the band then flips on
[metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_fusion_flip=0.1818] and errs a median
[metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#n50_55_fusion_median_abs_deg=9.875] degrees. The highlight and
the light each carry part of it: the prior alone fixes two, the teardrop and
light without the highlight one. Over all 37 reads the fusion flips on
[metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#fusion_flip=0.0541] against the teardrop's
[metric:facing_fusion_eval/labels-self-331@c40d950031bb+223d636bf8d2+bfad2778a372+e37fdeca944f#teardrop_flip=0.1622] and breaks nothing. The two flips it keeps
(c40d950031bb at 509.8 s, 223d636bf8d2 at 742.6 s) have teammates' cones
near the icon (`sheet_s331.png` in the store's
`analysis/facing-fusion-20260929/`), and on the second the highlight sides
with the flip. The old chooser fixes all five
flips in the band but breaks three correct reads above it.

By the rule logged with the predictions the fusion rescues the band (three
fixed, none broken in any band), yet the rescued band still flips on about
a fifth of its reads against one in 26 above the gate. The gate ships alone;
the fusion stays unwired (`facing-fusion-0.1.0`), and E12's case for stacked
labels stands. Against the predictions: S1 held, S2 held, S3 failed (the
light alone fixes more than the prior alone), S4 held.

**The enemy set** holds 44 candidates on c40d950031bb and 223d636bf8d2: 38
from the enemy portrait pool, stratified by teardrop NCC third and by what
lies under the icon, and six audit candidates the portrait gate rejected.
The player answered [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answer_facing=25] facing,
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answer_not_icon=17] not an icon and
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answer_cant_tell=2] can't tell. Where the enemy teardrop reads
(its gates passed) it errs a median
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_all_median_abs_deg=2.79] degrees and flips on
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_all_flip=0.133] of [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_all_n=15];
its best facing on every labelled icon errs
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_all_median_abs_deg=4.27] and flips on
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_all_flip=0.12] of [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_all_n=25].
The red ring fit errs [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#ring_all_median_abs_deg=7.8] and flips on
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#ring_all_flip=0.333]; the tip highlight errs
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#highlight_all_median_abs_deg=42.8], as the enemy lobe's
translucency predicts [domain:minimap/enemy-lobe-translucent].

A teammate's light behind an enemy icon costs the teardrop its lobe. Over a
lit background its best facing flips on
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_bg_lit_flip=0.286] of
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_bg_lit_n=7], over floor on
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_bg_floor_flip=0.0] of
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_bg_floor_n=7]; taken under the labelled lobe, lit
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_lobe_lit_flip=0.214] of
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_lobe_lit_n=14] against floor
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_lobe_floor_flip=0.0] of
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#teardrop_any_lobe_floor_n=8]; all three flips have lit floor
under the labelled lobe. This fits the translucent lobe: the light beneath
shows through it, and the red key cannot tell a lit wedge from the lobe. No
measurement here separates that cause from others.

The candidates' answers say what the finders find. The player called all
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_stratum_audit_not_icon=6] audit candidates not an icon,
so the portrait gate's rejections were right. Candidates the standard enemy
detector also found were [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_std_detector_True_facing=18]
icons to [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_std_detector_True_not_icon=3] not; those only
the red-key finder proposed were
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_std_detector_False_facing=7] icons to
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_std_detector_False_not_icon=14] not. The finder adds a
few enemies and mostly non-icons. The teardrop's own gate sorts them too:
where it reads, [metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_teardrop_read_True_facing=15] icons to
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_teardrop_read_True_not_icon=1]; where it refuses,
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_teardrop_read_False_facing=10] to
[metric:icon_facing_eval/labels-enemy-331@c40d950031bb+223d636bf8d2#answers_teardrop_read_False_not_icon=16].

**Against the predictions.** Self: P1 held; P2 failed on both halves, at two
or three items a session and band; P3 held; P4 held; P5 failed, since under
0.55 the ring fit flips less often than the teardrop. Enemy: P1 held; P2
held for the teardrop's best facing on every icon and failed on its gated
reads alone, whose median moved by less than the predicted 3 degrees; P3 failed narrowly (the
highlight flips on 0.19, under the predicted 0.2); P4, P5 and P6 held.

## What this plan does not settle

- The half-angle's interval is wide: E4's flat tops run from about 48 to 58
  degrees, and 51.5 sits inside both sessions' tops.
- The teardrop's facing is scored against 28 Lotus labels and 8 Ascent
  controls; the flips cluster where the readers disagree, and no other map
  or widget scale has labels.
- The ally and enemy teardrops are scored on one Lotus and one Ascent
  session; the teardrop reads the Wingman glyph as an agent, and no
  portrait gate rule rejects more than half the not-icons without losing
  teammates: Bs, calibrated clean of the spike, still keeps pings, X marks
  and the Wingman glyph that fit like portraits.
- Since `team-vision-0.5.0` no cone falls back to the ring fit: an icon whose
  teardrop gives no facing casts nothing, which costs recall wherever the
  teardrop reads less, as on c40d950031bb. The ring fit's ally cones scored
  more precise than the teardrop's there only because the light chose
  their lobe (E11).
- E12's fusion rests on five teardrop flips over 97 labelled reads; its
  constants were set once, before scoring, and never fitted. Stacks are
  where it fails, and no label set is drawn to test them.
- The 331 px self gate rests on 37 labels, three or so per session and NCC
  band (E13); it is one number for the widget size, and c40d950031bb holds
  most of the flips.
- The enemy teardrop has 331 px labels (E13) but no gate change: its gated
  reads still flip on about one in seven, each flip over a teammate's light.
- Wall edges (`BORDER`) were not perturbed; only box edges were.
- E2's near-line group holds only a handful of held-out frames.
- E1-E3 calibrated on one session and one map; E4 adds one Lotus session.
- The flip rate is a floor, because `resolve_lobe` chose each lobe with the
  same light the bisector reads.
- The facing spread is measured against the light's bisector, which a
  half-occluded cone biases; it is an upper bound on the fit's error.
- E7 scores three sessions and one 331 px widget; its causes rest on ordered
  rules, so an early rule (geometry) takes pixels a later cause (a wrong
  cone) produced.
- E8 reads the lifecycle's refusals on two sessions; its gate change is
  scored against the light on held-out windows of the same sessions, and
  the self icon after the player's death is unanswered.
