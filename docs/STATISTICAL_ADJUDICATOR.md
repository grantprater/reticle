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
- The self cone's fallback (ring fit and track lobe) serves about a tenth of
  Lotus's cast cones; teammates' cones still start at their ring fits along
  their tracks' lobes.
- Wall edges (`BORDER`) were not perturbed; only box edges were.
- E2's near-line group holds only a handful of held-out frames.
- E1-E3 calibrated on one session and one map; E4 adds one Lotus session.
- The flip rate is a floor, because `resolve_lobe` chose each lobe with the
  same light the bisector reads.
- The facing spread is measured against the light's bisector, which a
  half-occluded cone biases; it is an upper bound on the fit's error.
