# The scene model

A plan, proposed 2026-09-29. The player named the end goal: one model that
takes everything already known -- what was detected before, and the game's
invariants -- together with the pixels, sound and text each channel reads,
and returns every entity's identity, position and facing, with the readers
and adjudicators of every channel woven into one mesh, audio included. This
document states that model: one shared state over time, and one
observation model per channel that scores the stored observations against
it. The minimap's render-and-compare model is the first observation model,
not the whole design. Stage 1, touching minimap icons fitted jointly, is
built and scored (`prototypes/scene_stack.py`, section 8): 0.2.0's RGB renderer matches the teardrop at
465 px on team icons and still loses to it at 331 px; 0.3.0 lights the floor
from the fitted pose (stage 2 inside stage 1) and beats the teardrop on
isolated 331 px self icons while losing on stacks.

The idea is old: analysis-by-synthesis, argued for icons and audio in the
backlog entry now archived in `docs/archive/BACKLOG-through-2026-09-23.md`
("Analysis-by-synthesis: hypothesise an event, render it, fit the
residual"); `prototypes/self_agent.py` still points at it, but `BACKLOG.md`
no longer carries it. Rules live in `AGENTS.md`; this plan cites them.

## 1. The state

One state per session over time, held by adjudication, never by a reader:

- **Players**, ten entities keyed per side and slot: agent name (decided
  only by `adjudication.identity`), side, alive, position, facing, and
  whether the player carries the spike. No health.
- **Objects**: the one spike (carried, dropped, planted), smokes and other
  ability drawings, devices, pings, death marks and last-known marks
  [domain:minimap/last-known-mark], each with an owner where known.
- **Events**: casts, deaths, plants and defuses, round phases.

Each field carries its standing: observed, inferred with its evidence, or
unknown with a reason. The state is what the channels explain; it is not
an observation, and nothing stores it back as one.

## 2. Observation models

An observation model is a deterministic likelihood of one channel's stored
observations given the state. Readers stay as they are: level-1 streams of
raw observations with versions. Adjudication stays pure over stored rows.
The scene model adds, per channel, the function that says how well a
candidate state explains what that channel stored, and a search over
states that the channels jointly explain best.

The minimap is the exception worth naming: its observation model needs
pixels, so the render-and-compare fit is a READER. It reads the crop cache
with the predicted state as its prior, stores its fit as observations with
`rests_on` naming that prior, and adjudication weighs the fit once
(section 6).

## 3. The minimap observation model

### Prediction

Each frame starts from the last frame's fitted state. `track` owns what a
track may do next ([owns:track-continuation], [owns:teleport-licence]);
`belief` owns where an unobserved player may be ([owns:position-belief]),
and a belief never becomes evidence. The invariants prune the hypotheses:
the roster's alive counts bound how many icons a side draws
([owns:alive-count]); one self icon; one spike ([owns:spike-carrier]); a
player stands on reachable floor of the baked geometry; an enemy is drawn
only inside the team's vision [domain:minimap/vision-gate]; a cone's rays
stop at the first wall or box [domain:minimap/cone-rays-stop-at-first-edge].

### The renderer

The background is the baked static keyed by `(map, profile)`, never a
session's pixels [domain:capture/session-pixels-are-not-the-map], behind a
widget that is transparent over the void [domain:minimap/transparency].
Over it the renderer composites sprites:

- an ally or self icon: `teardrop.render`'s silhouette at the class radii
  times `minimap.widget_scale`, opaque, its tip lighter
  [domain:minimap/icon-tip-highlight], its portrait upright on a turned map
  [domain:minimap/upright-icons-on-turned-map];
- an enemy icon: a faint rim [domain:minimap/enemy-rim-faint-at-small-widget]
  and a lobe that tints what lies beneath
  [domain:minimap/enemy-lobe-translucent];
- a cone: light over floor from the icon's centre
  [domain:minimap/cone-origin-near-centre], cast by `cone.raycast` against
  the walls and boxes `occluders` bakes, drawn with the two-state floor
  reference of `lighting`;
- a portrait: the art rendered by `ally_portrait.render_reference`, for the
  agents the context allows (the side's five from the arbiter's verdicts);
- marks, pings and the spike glyph, as `docs/MINIMAP_OBJECTS_DESIGN.md`
  classes them.

### Comparison and fit

The residual is the observed widget less the render, truncated so that
clutter no sprite models counts at a fixed cost; the geometry's per-state
noise (`sd_lo`, `sd_hi`) sets what counts as small. Sprites composite
bottom to top in a draw order the fit chooses, so each pixel is explained
by the entity on top of it and is evidence for one entity only. The
order is unknown and measurable (`docs/MINIMAP_APPEARANCE_MATCHING.md`,
"The draw order is unknown, and it is measurable").

Entities whose footprints cannot touch are fitted apart; a stack (a
connected group of touching footprints) is fitted jointly. The search
starts at the predicted pose and stays local: each entity's pose is
searched with its neighbours held, from each combination of its best and
far-lobe poses, and the lowest total residual wins. A pose's standing is
its margin: the loss its best far-lobe alternative adds.

### The surprise path and the audit

Residual the render leaves unexplained -- a keyed blob above the truncation
over more than a few pixels -- is a surprise. It triggers a wider search
in that region only: the existing detectors (`minimap.ally_icons`
[owns:ally-candidates], the enemy ring fit, `self_icons`) propose a birth,
and the proposal enters the state from the next frame. Separately, a full
search runs on opportunity-gated frames at a cadence fixed in advance,
stored apart; its disagreements with the tracked fit measure what the
prior hides. A surprise-triggered search is never an audit sample.

### Output

Per frame and entity: pose, margin, draw order, the pixels it owns, the
residual it leaves, and every unexplained blob; per frame: the version, the
prior it rests on (track ids, their frames and versions) and the geometry
key. Where the fit compares portrait hypotheses, it publishes
`identity.identity_claim`s on a channel of its own, with `depends_on` the
entities whose verdicts chose the gallery; `adjudication.identity`
([owns:agent-identity]) still decides every name, and the channel joins
`adjudication.reliability` like any other.

## 4. What existing owners become

| Piece | Owner today | In the scene model |
|---|---|---|
| Icon shape, centre, facing | `teardrop` ([owns:icon-pose], [owns:self-cone-origin]) | The sprite's silhouette, and the single-icon limit of the fit; kept as a comparison arm |
| Tip brightness; icon and light as two witnesses | `prototypes/tip_highlight.py`, `prototypes/facing_fusion.py` (E12) | The sprite's brightness term; the light becomes rendered evidence in stage 2 |
| Cone geometry | `cone` | The light renderer's raycast |
| Walls and boxes | `occluders` | The renderer's occluders |
| Floor light | `lighting` | The two-state reference the light render draws with |
| Team vision | `team_vision` ([owns:team-vision]) | A render of the fitted state: its lobe choice, tracker and lifecycle give way to the joint fit's poses |
| Track admissibility, position belief | `track`, `belief` | The prediction step |
| Icon finding, self position, widget state | `minimap` ([owns:ally-candidates], [owns:self-position], [owns:widget-drawn]) | The surprise path's proposals and the widget gate |
| Portrait features | `ally_portrait` ([owns:ally-portrait-features]) | Portrait sprites |
| Marks, pings | `docs/MINIMAP_OBJECTS_DESIGN.md` | Mark and ping sprites |
| Names | `adjudication.identity` | Unchanged |

## 5. Other channels

Each paragraph names what the channel observes, its rate and delay, the
reader and adjudicator that become its observation model, and how it gates
the others.

**Killfeed.** Kill entries: killer and victim portraits, names and sides,
weapon, headshot, the "Me" marker and the second-life badge. Read in the
shared HUD pass (2 Hz by default); an entry stays on screen over many
samples. `killfeed` ([owns:killfeed-event], [owns:killfeed-portrait]) reads;
`adjudication.death` binds deaths, and `identity.claim_from_killfeed_portrait`
names portraits against the lineup's side candidates. A death kills a player
in the state: the minimap stops predicting that icon and predicts an X mark
at its last position; the dead teammate is already barred from minimap
pieces (`identity.assign_ally_pieces`).

**Roster.** The alive strip: portraits drawn for living players only, so
per-side alive counts. 2 Hz, one sample late ([owns:alive-count]). It
bounds how many icons each side may draw and how many enemies may be
hypothesised; `adjudication.spike_carrier` already cross-checks it with the
minimap glyph and the plant.

**Tray.** The player's own ability charges; a drop marks a cast. About
2 Hz from stored crops, timed to about half a second ([owns:tray-drop]);
`adjudication.tray_kit` says whose kit is showing after death, and
`ability_timeline` owns casts. A cast predicts where and when the
minimap should draw the player's ability, which narrows that search to the
player's position and the next seconds.

**Chat and broadcasts.** No reader exists. The spike-carrier-killed
broadcast [domain:hud/enemy-carrier-death-broadcast] would witness a death
and a spike drop at once; it is named here so that a reader, when built,
arrives as an observation model rather than a special case.

**Scoreboard.** Per-player rows while Tab is held, 2 Hz, intermittent
([owns:scoreboard-row]; `adjudication.scoreboard`); the top-bar lineup
([owns:agent-from-slot]) accumulates each slot's agent over the match.
The lineup is the gallery every portrait comparison is allowed; the board's
alive sets constrain deaths per round.

**Audio.** Ult voice lines are in production: `ult_lines` ([owns:ult-line])
correlates templates against the capture's audio, and `adjudication.ult_cast`
([owns:ult-cast]) classes each line own, ally or enemy from the lineup and
binds own lines to tray drops. A line predicts a cast by a named agent in
the next seconds, which narrows where and when the minimap searches for
that ability. The generic sound gate stayed a prototype
(`docs/AUDIO_GATE.md`: not a switch for the expensive passes on its own).
Speculative and unmeasured: the self icon's facing with the stereo pan of a
sound could give a bearing to its source.

### Time

The channels run at different rates: the minimap crop cache at 15 Hz, the
HUD readers at 2 Hz, audio continuously. Every stored time is media time;
`gametime` ([owns:in-game-time]) maps it to the round clock. No audio-video
offset has been measured: the only figure is the tray-to-audio scatter in
`docs/AUDIO_GATE.md`, and the cast windows absorb it. The scene model
therefore compares each observation at its own time against the state
interpolated there, widens each channel's likelihood by its sampling
interval, and records the offset as an unknown it should estimate before
audio gates any pixel search.

### Weigh once

A channel whose reading was shaped by another declares it: a claim
`depends_on` the verdicts it used, and an observation `rests_on` the prior
that placed its search. The mesh counts each piece of evidence once. The
minimap fit that searched near a death predicted by the killfeed is not a
second witness of that death; the portrait comparison restricted to the
lineup's five does not re-confirm the lineup.

## 6. Keeping it honest

- **Raw observations apart.** Readers store; adjudication infers; the state
  is never stored back as an observation, and a late detector answer never
  becomes an event's origin.
- **Score on labels only.** The fit is scored against the player's labels,
  never against the light it rendered (E11 in
  `docs/STATISTICAL_ADJUDICATOR.md`), never against its own previous
  output, and never by agreement between channels, which is consistency.
- **Refuse rather than guess.** A pose with too small a margin is unread
  with its reason; the state keeps the belief with its standing instead.
- **Deterministic.** No learned model enters stage 02: silhouettes, art,
  baked geometry and residuals.

## 7. Compute

The CPU is the machine's bottleneck, so the render and the residual run on
the GPU (torch on CUDA): every candidate pose of one entity is one batched
render over its pixels. Stage 1 fits a labelled icon with its touching
neighbours in a median per set between
[metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#fit_s_median=0.031]
seconds (331 px self) and
[metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#fit_s_median=0.695]
seconds (465 px ally), from a cold start with a full search. Tracking from the last
frame's poses searches a few pixels and degrees instead, and a group that
did not move since the last frame needs no fit at all.

## 8. Staged plan

Each stage is scored on the player's labels before the next begins.

1. **Stacks** (built, below): touching icons fitted jointly; 0.1.0 in the
   owners' class keys, 0.2.0 in RGB over the two-state baked floor with
   the portrait disc masked, the light marginalised.
2. **Cones and light** (built into stage 1 as 0.3.0, below): render each
   fitted icon's cone as light over the floor, stopping at `occluders`; the
   light becomes evidence for facing inside the same fit, which E12 did as a
   separate fusion.
3. **The enemy tint**: the enemy lobe as a measured tint over the rendered
   background and light; its opacity measured on labels at both widget sizes.
4. **The whole widget**: portraits from art for the side's agents, marks,
   pings and the spike; tracking from frame to frame with the audit.
5. **The mesh**: the first cross-channel gate, the ult line narrowing the
   minimap's ability search, then killfeed deaths predicting X marks.
   Enemy icons against the team's vision are one strand, proposed in
   [`ENEMY_VISION_COUPLING.md`](ENEMY_VISION_COUPLING.md).
   [`ARBITER_ARCHITECTURE.md`](ARBITER_ARCHITECTURE.md) (proposed
   2026-09-30) would make this mesh, and section 1's state, the aggregator
   over one arbiter per channel; stages 1-4 stay the minimap's reader.

### Stage 1 results

| Set | Items | Teardrop median (deg) | Teardrop flips | Joint median (deg) | Joint flips | Fixed | Broken |
|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_n=24] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_teardrop_median_abs_deg=2.485] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_joint_median_abs_deg_on_td_read=2.21] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_joint_flips=1] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_joint_fixed=0] | [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#all_joint_broken=1] |
| 465 px enemy (E6) | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_n=18] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_teardrop_median_abs_deg=1.685] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_joint_median_abs_deg_on_td_read=3.03] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_joint_flips=2] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_joint_fixed=0] | [metric:scene_stack_eval/465-enemy@5822b6646448+a06f04a0059f#all_joint_broken=2] |
| Self, Ascent controls | [metric:scene_stack_eval/self-control@e78e75b2d191#all_n=8] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_teardrop_median_abs_deg=1.98] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_teardrop_flips=0] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_joint_median_abs_deg_on_td_read=2.15] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_joint_flips=1] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_joint_fixed=0] | [metric:scene_stack_eval/self-control@e78e75b2d191#all_joint_broken=0] |
| Self, Lotus | [metric:scene_stack_eval/self-lotus@5822b6646448#all_n=30] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_teardrop_median_abs_deg=2.2325] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_teardrop_flips=2] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_joint_median_abs_deg_on_td_read=3.02] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_joint_flips=2] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_joint_fixed=1] | [metric:scene_stack_eval/self-lotus@5822b6646448#all_joint_broken=0] |
| 331 px ally | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_n=38] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_teardrop_median_abs_deg=4.6025] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_teardrop_flips=3] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_joint_median_abs_deg_on_td_read=12.97] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_joint_flips=11] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_joint_fixed=1] | [metric:scene_stack_eval/331-ally@223d636bf8d2+c40d950031bb#all_joint_broken=9] |
| 331 px self | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_n=37] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_median_abs_deg=5.71] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_flips=6] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_median_abs_deg_on_td_read=129.02] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_flips=21] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_fixed=0] | [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_broken=15] |
| 331 px enemy | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_n=25] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_teardrop_median_abs_deg=2.79] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_teardrop_flips=2] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_joint_median_abs_deg_on_td_read=12.57] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_joint_flips=10] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_joint_fixed=0] | [metric:scene_stack_eval/331-enemy@223d636bf8d2+c40d950031bb#all_joint_broken=4] |
| Pooled, stacked | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_n=46] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_median_abs_deg=3.3175] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_flips=5] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_median_abs_deg_on_td_read=4.26] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_flips=11] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_fixed=1] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_broken=4] |
| Pooled, touching | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_n=87] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_teardrop_median_abs_deg=2.9975] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_teardrop_flips=9] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_median_abs_deg_on_td_read=7.575] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_flips=22] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_fixed=1] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_broken=10] |
| Pooled, isolated | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_n=93] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_median_abs_deg=2.6] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_flips=4] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_median_abs_deg_on_td_read=4.52] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_flips=26] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_fixed=1] | [metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=21] |

`scene_stack.py --record --sheet` over the five label sets, crop cache
only. The teardrop is `teardrop.fit_icon` at the label set's detector
centre; the joint fit is the labelled icon with its touching neighbours;
a flip errs by more than 90 degrees; fixed and broken count against the
teardrop where it reads; the joint median is taken where the teardrop
reads. Stacked means a neighbour within 22 px times the widget scale;
touching includes stacked; isolated has no touching neighbour, so the
joint fit there is the renderer alone. Predictions P1-P6 were logged
first (`notes/predictions.jsonl`, task `scene-stack-20260929`).

**Stage 1 fails at 331 px, and the fault is the renderer.** At 465 px the
joint fit matches the teardrop on stacks
([metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#stacked_joint_median_abs_deg_on_td_read=2.08]
against
[metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#stacked_teardrop_median_abs_deg=2.2725]
degrees, no flips) but is worse alone. At 331 px it flips far more than
the teardrop on every set, isolated icons included. On the flipped 331 px
items checked by hand, the renderer's loss is lower at its own wrong pose
than at the teardrop's pose, so the model is wrong there, not the search.
The flips go with ring and lobe gains held at the 0.2 bound and a centre
that wanders up to the 3 px search radius. The belief: at 331 px the ring
is about a pixel wide and carries little key, while the portrait, which
stage 1 draws key-neutral, keys strongly (self portraits wash yellow), so
a dimmed icon placed off-centre explains the portrait's key better than
the true pose. Joint over solo on touching items helped weakly
([metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_vs_solo_fixed=4]
fixed,
[metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#touching_joint_vs_solo_broken=2]
broken). A post hoc variant sharing one gain across ring and lobe did
worse: pooled joint flips
[metric:scene_stack_eval/pooled-posthoc-shared@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_joint_flips=59]
against
[metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_joint_flips=48].
The prototype is not wired.

**Too few stacked labels to decide.** The teardrop flips on only
[metric:scene_stack_eval/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_flips=5]
stacked items across every set, so a better renderer could fix at most
that many. The 331 px enemy set dropped every enemy within 15 px times the
scale of a team icon, so enemy-on-team stacks, the case the tint and the
joint fit exist for, are absent; its five stacked items are enemy on enemy
or just outside that radius, and the teardrop reads none of them. The
next label set, for the player: facing labels drawn from frames chosen by
stacking alone (a neighbour within 22 px times the scale), at both widget
sizes, all three classes, enemies over teammates included, the light
hidden in the labelling view.

### Stage 1, 0.2.0: the RGB renderer

`scene-stack-0.2.0` predicts the crop's RGB instead of class keys. Behind
the icons lies the baked static in two floor states: the static is the
unlit state, and on the lighting reference's known floor the lit state is
its colour scaled to `hi_gray`; per pixel the cheaper state wins, so the
drawn light is marginalised. Each icon has fixed ring, lobe-base, tip and
portrait colours per class and widget scale; the enemy ring and lobe are
translucent. Colours, enemy alphas, one blur per widget and the noise are
calibrated on unlabelled frames of the labelled sessions, at least 3 s from
any labelled instant, from isolated owner teardrops. No gain is free. The
portrait disc belongs to its icon and is left out of the comparison: no
art is drawn, because identity is not plumbed into this stage.

**The renderer alone, before any fit** (`scene_stack.py --check --record`):
the labelled icon alone, its best pose over the whole solo search ("flips
alone"), and the labelled facing against the reversed one with the centre
free within 1 px of the player's click.

| Set | Items | Teardrop flips | 0.1.0 keys: flips alone | 0.2.0 RGB: flips alone | RGB: label beats reversed |
|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_check/465-ally@5822b6646448+a06f04a0059f#all_n=24] | [metric:scene_stack_check/465-ally@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_check/465-ally@5822b6646448+a06f04a0059f#all_keys_global_flips=1] | [metric:scene_stack_check/465-ally@5822b6646448+a06f04a0059f#all_rgb_mask_global_flips=0] | [metric:scene_stack_check/465-ally@5822b6646448+a06f04a0059f#all_rgb_mask_lab_beats_rev=24] |
| 465 px enemy (E6) | [metric:scene_stack_check/465-enemy@5822b6646448+a06f04a0059f#all_n=18] | [metric:scene_stack_check/465-enemy@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_check/465-enemy@5822b6646448+a06f04a0059f#all_keys_global_flips=2] | [metric:scene_stack_check/465-enemy@5822b6646448+a06f04a0059f#all_rgb_mask_global_flips=4] | [metric:scene_stack_check/465-enemy@5822b6646448+a06f04a0059f#all_rgb_mask_lab_beats_rev=17] |
| Self, Ascent controls | [metric:scene_stack_check/self-control@e78e75b2d191#all_n=8] | [metric:scene_stack_check/self-control@e78e75b2d191#all_teardrop_flips=0] | [metric:scene_stack_check/self-control@e78e75b2d191#all_keys_global_flips=1] | [metric:scene_stack_check/self-control@e78e75b2d191#all_rgb_mask_global_flips=0] | [metric:scene_stack_check/self-control@e78e75b2d191#all_rgb_mask_lab_beats_rev=8] |
| Self, Lotus | [metric:scene_stack_check/self-lotus@5822b6646448#all_n=30] | [metric:scene_stack_check/self-lotus@5822b6646448#all_teardrop_flips=2] | [metric:scene_stack_check/self-lotus@5822b6646448#all_keys_global_flips=2] | [metric:scene_stack_check/self-lotus@5822b6646448#all_rgb_mask_global_flips=0] | [metric:scene_stack_check/self-lotus@5822b6646448#all_rgb_mask_lab_beats_rev=29] |
| 331 px ally | [metric:scene_stack_check/331-ally@223d636bf8d2+c40d950031bb#all_n=38] | [metric:scene_stack_check/331-ally@223d636bf8d2+c40d950031bb#all_teardrop_flips=3] | [metric:scene_stack_check/331-ally@223d636bf8d2+c40d950031bb#all_keys_global_flips=11] | [metric:scene_stack_check/331-ally@223d636bf8d2+c40d950031bb#all_rgb_mask_global_flips=14] | [metric:scene_stack_check/331-ally@223d636bf8d2+c40d950031bb#all_rgb_mask_lab_beats_rev=32] |
| 331 px self | [metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_n=37] | [metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_flips=6] | [metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_keys_global_flips=23] | [metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_rgb_mask_global_flips=7] | [metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_rgb_mask_lab_beats_rev=33] |
| 331 px enemy | [metric:scene_stack_check/331-enemy@223d636bf8d2+c40d950031bb#all_n=25] | [metric:scene_stack_check/331-enemy@223d636bf8d2+c40d950031bb#all_teardrop_flips=2] | [metric:scene_stack_check/331-enemy@223d636bf8d2+c40d950031bb#all_keys_global_flips=10] | [metric:scene_stack_check/331-enemy@223d636bf8d2+c40d950031bb#all_rgb_mask_global_flips=12] | [metric:scene_stack_check/331-enemy@223d636bf8d2+c40d950031bb#all_rgb_mask_lab_beats_rev=19] |

Two first beliefs failed. At the clicked centre 0.1.0's keys prefer the
labelled facing as often as RGB does; 0.1.0 failed in the search, where a
shifted centre let a wrong facing win. And the first RGB background, the
static alone, saturated the residual over most of the floor: the static is
the unlit state, and team icons stand in their own lit cones. On unlabelled
frames the two-state floor explains more floor pixels within 20 grey than
the static does: on c40d950031bb
[metric:scene_stack_background/floor-within-20@c40d950031bb#two_state=0.72]
against [metric:scene_stack_background/floor-within-20@c40d950031bb#static=0.5],
on bfad2778a372
[metric:scene_stack_background/floor-within-20@bfad2778a372#two_state=0.82]
against [metric:scene_stack_background/floor-within-20@bfad2778a372#static=0.64],
on 5822b6646448
[metric:scene_stack_background/floor-within-20@5822b6646448#two_state=0.83]
against [metric:scene_stack_background/floor-within-20@5822b6646448#static=0.6].
The table is the two-state renderer, and these checks were no longer blind
to the labels.

**The fit**, only where the renderer alone flips no more than one item
beyond the teardrop (`scene_stack.py --parts 465-ally,self-control,self-lotus,331-self --record --sheet`):

| Set | Items | Teardrop median (deg) | Teardrop flips | Joint median (deg) | Joint flips | Fixed | Broken |
|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_n=24] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_teardrop_median_abs_deg=2.485] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_joint_median_abs_deg_on_td_read=2.97] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_joint_flips=0] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_joint_fixed=0] | [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_joint_broken=0] |
| 465 px enemy (E6) | not fitted: the renderer check failed | | | | | | |
| Self, Ascent controls | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_n=8] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_teardrop_median_abs_deg=1.98] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_teardrop_flips=0] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_joint_median_abs_deg_on_td_read=1.85] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_joint_flips=0] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_joint_fixed=0] | [metric:scene_stack_eval_v2/self-control@e78e75b2d191#all_joint_broken=0] |
| Self, Lotus | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_n=30] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_teardrop_median_abs_deg=2.2325] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_teardrop_flips=2] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_joint_median_abs_deg_on_td_read=1.98] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_joint_flips=1] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_joint_fixed=2] | [metric:scene_stack_eval_v2/self-lotus@5822b6646448#all_joint_broken=1] |
| 331 px ally | not fitted: the renderer check failed | | | | | | |
| 331 px self | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_n=37] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_median_abs_deg=5.71] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_flips=6] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_median_abs_deg_on_td_read=9.83] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_flips=6] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_fixed=6] | [metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_broken=6] |
| 331 px enemy | not fitted: the renderer check failed | | | | | | |
| Pooled (fitted sets), stacked | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_n=26] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_median_abs_deg=3.31] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_flips=2] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_median_abs_deg_on_td_read=3.32] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_flips=1] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_fixed=2] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_broken=1] |
| Pooled (fitted sets), isolated | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_n=57] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_median_abs_deg=2.5625] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_flips=3] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_median_abs_deg_on_td_read=2.47] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_flips=5] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_fixed=3] | [metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=5] |

**Verdict per widget.** At 465 px the RGB renderer reads team icons as well
as the teardrop: no flip on allies, one of the two Lotus self flips fixed
net, stacked allies at [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#stacked_joint_median_abs_deg_on_td_read=2.485] degrees against the teardrop's
[metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#stacked_teardrop_median_abs_deg=2.2725]. It fails the enemy check, and the 465 px enemy
calibration rests on few isolated enemies. At 331 px RGB cuts the self
flips alone from 0.1.0's
[metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_keys_global_flips=23] to
[metric:scene_stack_check/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_rgb_mask_global_flips=7], but the joint fit breaks
as many self reads as it fixes and doubles the median, and on 331 px allies and enemies the renderer alone flips more than
0.1.0's keys. The residual there still saturates over much of the floor
(sheet `analysis/scene-stack-v2-20260929/sheet_s331_0.png` in the store):
where the background is mispredicted a lobe costs nothing extra, so a wrong
lobe hides in the mismatch. The hypothesis that the score space was the
fault holds for 331 px self icons and fails for 331 px allies and enemies.
Not wired.

### Stages 1 and 2 together, 0.3.0: the light from the pose

The 0.2.0 sheets showed why a wrong lobe cost nothing: each floor pixel
took whichever state fitted it, so any lobe explained the drawn light.
`scene-stack-0.3.0` predicts the state from the poses instead. A
known-floor pixel is lit iff a team icon's cone reaches it (`cone.raycast`,
the owner's half-angle, the baked walls and boxes), cast from the pose being
fitted for scene icons and from the teardrop pose for the frame's other team
icons; enemies cast nothing. The other state costs `2 ln((1-q)/q)`, where `q`
is the rate at which that state wins at confident owner poses on unlabelled
frames. That cost is the explicit term for light no visible icon casts.
`prototypes/clove_circle.py` measures one light source the render must draw:
the dead Clove's smoke-range circle [domain:abilities/clove-dead-smoke-range-circle].
`prototypes/audio_circle.py` measures another: the self audio circle
[domain:minimap/self-audio-circle], a ring round the player's own icon
drawn for about half a second per own footstep or reload, at two sizes: the
footstep's and a smaller reload's, which a step supersedes.
Sprites and colours are 0.2.0's. Predictions P9-P14 were logged first
(`notes/predictions.jsonl`, task `scene-light-20260929`).

**The instrument holds.** At confident owner poses on unlabelled frames the
icon's own cone reads lit on
[metric:scene_stack_light_cal/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#own_cone_lit_share=0.7925] of its floor at 331 px and
[metric:scene_stack_light_cal/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#own_cone_lit_share=0.925] at 465 px; floor no cone
reaches reads unlit on [metric:scene_stack_light_cal/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#no_cone_unlit_share=0.8073] and
[metric:scene_stack_light_cal/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#no_cone_unlit_share=0.8616]. Unexplained light is
common: [metric:scene_stack_light_cal/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#q_u=0.1965] of the unreached floor at 331 px
and [metric:scene_stack_light_cal/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#q_u=0.1344] at 465 px reads lit. For speed each
origin is cast once over 360 degrees and cut to each facing's wedge; the cut
disagrees with the owner's own cast on
[metric:scene_stack_light_cal/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#cut_disagree_share=0.056] and
[metric:scene_stack_light_cal/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#cut_disagree_share=0.0444] of the scored pixels. The
0.2.0 column below reproduces the recorded 0.2.0 check exactly.

**The renderer alone** (`scene_stack.py --check --record`): the labelled
icon's sprite, every other team icon's teardrop cone held; label against
reversed with the centre fixed at the teardrop's; the gate is 0.2.0's (flips
alone at most the teardrop's plus one).

| Set | Items | Teardrop flips | 0.2.0: flips alone | 0.3.0: flips alone | 0.2.0: label beats reversed | 0.3.0: label beats reversed | Gate |
|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_n=24] | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_rgb_mask_global_flips=0] | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_light_global_flips=1] | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_rgb_mask_td_lab_beats_rev=24] | [metric:scene_stack_check_v3/465-ally@5822b6646448+a06f04a0059f#all_light_td_lab_beats_rev=23] | pass |
| 465 px enemy (E6) | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_n=18] | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_rgb_mask_global_flips=4] | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_light_global_flips=4] | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_rgb_mask_td_lab_beats_rev=17] | [metric:scene_stack_check_v3/465-enemy@5822b6646448+a06f04a0059f#all_light_td_lab_beats_rev=17] | fail |
| Self, Ascent controls | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_n=8] | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_teardrop_flips=0] | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_rgb_mask_global_flips=0] | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_light_global_flips=0] | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_rgb_mask_td_lab_beats_rev=8] | [metric:scene_stack_check_v3/self-control@e78e75b2d191#all_light_td_lab_beats_rev=8] | pass |
| Self, Lotus | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_n=30] | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_teardrop_flips=2] | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_rgb_mask_global_flips=0] | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_light_global_flips=3] | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_rgb_mask_td_lab_beats_rev=29] | [metric:scene_stack_check_v3/self-lotus@5822b6646448#all_light_td_lab_beats_rev=29] | pass |
| 331 px ally | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_n=38] | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_teardrop_flips=3] | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_rgb_mask_global_flips=14] | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_light_global_flips=9] | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_rgb_mask_td_lab_beats_rev=33] | [metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_light_td_lab_beats_rev=34] | fail |
| 331 px self | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_n=37] | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_flips=6] | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_rgb_mask_global_flips=7] | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_global_flips=3] | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_rgb_mask_td_lab_beats_rev=34] | [metric:scene_stack_check_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_td_lab_beats_rev=35] | pass |
| 331 px enemy | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_n=25] | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_teardrop_flips=2] | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_rgb_mask_global_flips=12] | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_light_global_flips=13] | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_rgb_mask_td_lab_beats_rev=18] | [metric:scene_stack_check_v3/331-enemy@223d636bf8d2+c40d950031bb#all_light_td_lab_beats_rev=17] | fail |

**The fit**, on the sets that pass the gate (the same four as 0.2.0;
`scene_stack.py --parts 465-ally,self-control,self-lotus,331-self --record --sheet`):

| Set | Items | Teardrop median (deg) | Teardrop flips | Joint median (deg) | Joint flips | Fixed | Broken | Unexplained light, median share |
|---|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_n=24] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_teardrop_median_abs_deg=2.485] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_teardrop_flips=0] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_joint_median_abs_deg_on_td_read=2.53] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_joint_flips=2] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_joint_fixed=0] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_joint_broken=2] | [metric:scene_stack_eval_v3/465-ally@5822b6646448+a06f04a0059f#all_light_unexplained_share_median=0.0621] |
| 465 px enemy (E6) | not fitted: the renderer check failed | | | | | | | |
| Self, Ascent controls | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_n=8] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_teardrop_median_abs_deg=1.98] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_teardrop_flips=0] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_joint_median_abs_deg_on_td_read=1.85] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_joint_flips=0] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_joint_fixed=0] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_joint_broken=0] | [metric:scene_stack_eval_v3/self-control@e78e75b2d191#all_light_unexplained_share_median=0.0555] |
| Self, Lotus | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_n=30] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_teardrop_median_abs_deg=2.2325] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_teardrop_flips=2] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_joint_median_abs_deg_on_td_read=2.86] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_joint_flips=3] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_joint_fixed=1] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_joint_broken=2] | [metric:scene_stack_eval_v3/self-lotus@5822b6646448#all_light_unexplained_share_median=0.0716] |
| 331 px ally | not fitted: the renderer check failed | | | | | | | |
| 331 px self | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_n=37] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_median_abs_deg=5.71] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_teardrop_flips=6] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_median_abs_deg_on_td_read=5.24] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_flips=3] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_fixed=5] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_joint_broken=2] | [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_unexplained_share_median=0.0787] |
| 331 px enemy | not fitted: the renderer check failed | | | | | | | |
| Pooled (fitted sets), stacked | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_n=26] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_median_abs_deg=3.31] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_teardrop_flips=2] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_median_abs_deg_on_td_read=4.57] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_flips=3] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_fixed=1] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_broken=2] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_light_unexplained_share_median=0.0722] |
| Pooled (fitted sets), isolated | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_n=57] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_median_abs_deg=2.5625] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_teardrop_flips=3] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_median_abs_deg_on_td_read=2.425] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_flips=3] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_fixed=2] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=2] | [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_light_unexplained_share_median=0.0618] |

**The coupling fixes isolated 331 px self icons and hurts stacks.** On 331
px self the joint fit now beats the teardrop, where 0.2.0 broke as many
reads as it fixed: isolated flips [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_flips=1]
against the teardrop's [metric:scene_stack_eval_v3/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_teardrop_flips=2] (0.2.0:
[metric:scene_stack_eval_v2/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_flips=5]). The sheet
(`analysis/scene-light-20260929/sheet_s331_0.png` in the store) shows the
mechanism: a teardrop flipped by a stacked neighbour is turned back because
its cone must land on the lit floor. Pooled isolated breaks fell from
[metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=5] to [metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=2],
but stacks got worse: pooled stacked flips
[metric:scene_stack_eval_v3/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_flips=3] against 0.2.0's
[metric:scene_stack_eval_v2/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#stacked_joint_flips=1], Lotus stacked median
[metric:scene_stack_eval_v3/self-lotus@5822b6646448#stacked_joint_median_abs_deg_on_td_read=7.88] against the
teardrop's [metric:scene_stack_eval_v3/self-lotus@5822b6646448#stacked_teardrop_median_abs_deg=2.99]. In a stack a
neighbour's cone already lights the floor ahead, and a cone cast into a wall
predicts no light, so a reversed icon pays little. A redundant cone is no
evidence. At 331 px allies the coupling cuts flips alone from
[metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_rgb_mask_global_flips=14] to
[metric:scene_stack_check_v3/331-ally@223d636bf8d2+c40d950031bb#all_light_global_flips=9], short of the gate. The residual
still saturates over floor whose state the render gets right, so the 331 px
floor colour, not only its state, is mispredicted. Not wired.

The 465 px ally teardrop median is the same in 0.1.0 and 0.2.0 on the same
[metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_n=24] items: [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#all_teardrop_median_abs_deg=2.485]
over all, [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#stacked_teardrop_median_abs_deg=2.2725] over the stacked
ones. 0.2.0's stacked joint median, [metric:scene_stack_eval_v2/465-ally@5822b6646448+a06f04a0059f#stacked_joint_median_abs_deg_on_td_read=2.485],
only coincides with the first.

### Where the unexplained light comes from

`prototypes/unexplained_light.py` rebuilds each fitted 0.3.0 scene (all
[metric:unexplained_light/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#reproduced_n=99]
reproduce the stored count) and tests two causes against a control: compared
floor predicted unlit that reads unlit. Earlier cones are the frame's team
teardrops at t-250 and t-500 ms, cast over the whole widget. They cover
[metric:unexplained_light/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#early_share=0.1859]
of unexplained pixels against
[metric:unexplained_light/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#early_share_control=0.113]
of the control: some excess, too little to call lingering the main cause, and
a lower bound, since teardrops rarely read inside stacks. Team icons outside
the scene, recast over the whole widget, explain
[metric:unexplained_light/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#off_share=0.0058]:
not a cause. The player's other candidates, a teammate who just died
[domain:minimap/dead-teammate-light-belief] and the spike
[domain:minimap/spike-casts-no-light-belief], are untested; the store's
`analysis/unexplained-light-20260929/sheet_331.png` and `sheet_465.png`
show the whole widget for the player to judge. Not wired.

The player then ruled out a circle of floor round each teammate
[domain:minimap/no-teammate-floor-circle] and named two other sources:
abilities' white-tinted areas [domain:abilities/minimap-icon-pale-region]
and piloted drones' cones [domain:abilities/piloted-drones-have-cones].
`prototypes/light_causes.py` gives each unexplained pixel one cause, in
order. Within 2 px of an icon's silhouette (HALO) lie
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#halo_share=0.2509]
of them against
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#halo_share_control=0.1974]
of the control; those pixels carry the icons' teal and yellow, so they are
rim, not floor, and undecidable rather than lit. Stored ability observations
(the player's labels, smoke tracks) reach
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#items_ability_1s=11]
items within 1 s and explain
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#ability_share=0.0]
of the light; earlier cones then take
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#lingering_share=0.1248]
(control
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#lingering_share_control=0.0805]),
leaving
[metric:light_causes/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#residual_share=0.6244].
The store's `analysis/light-causes-20260929/sheet_residual.png` shows the
residual on ability icons no scene renders, inside a large white circle
round the Lotus A-site stack that no stored observation holds, along the
modelled cone's edge, and on site-tinted floor. The ability cause needs an
area detector or the player's labels on these frames. Not wired.

### Stage 2, 0.4.0: the other light sources

`scene-stack-0.4.0` draws the non-cone light the player named, each as a
circle fitted on the frame's own static-subtracted grey, never by analogy.
Predictions P15-P19 were logged first (`notes/predictions.jsonl`, task
`scene-sources-20260930`).

- **The self audio circle** [domain:minimap/self-audio-circle]: fitted round
  the stored self position per frame, the radius free. A fit counts when
  its ring clears `audio_circle`'s cuts, the exact fit is good and the rim
  raises every colour channel (the circle is white; a yellow ring round the
  self at 223d636bf8d2 1095.33 s failed that test). Drawn on
  [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_audio=31] labelled items.
- **The dead Clove's circle** [domain:abilities/clove-dead-smoke-range-circle]:
  sought only while the stored death data holds an ally Clove dead in the
  round. Six labelled items qualify, all 331 px self frames of e37fdeca944f;
  none shows the circle, so it is drawn on
  [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_clove=0].
- **Trademark, Chokehold, Sonic Sensor**: drawn only round a labelled icon
  within 1 s. One labelled item has one (a Sonic Sensor at 5822b6646448
  1695.75 s); its area is no circle, so none is drawn
  ([metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_ability=0] items). The Trademark area
  visible at e37fdeca944f 1795.08 s has no stored position.

**Predicting the disc lit failed the instrument.** The first design
predicted floor inside a disc lit. On unlabelled frames that floor reads
nearer the lit state on only [metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#source_lit_nearer_share=0.4637] at 331 px and
[metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#source_lit_nearer_share=0.4259] at 465 px: the disc tints either state white.
So 0.4.0 frees the disc instead (either state at no cost); a cone is
evidence only on floor no source explains. Outside the discs the costs
barely move: `q_u` [metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#q_u=0.1964] (without the sources [metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#q_u_nosrc=0.1965]) at
331 px, [metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#q_u=0.1249] ([metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#q_u_nosrc=0.1344]) at 465 px.

**The fit on every set**, teardrop and joint on identical items (both read),
0.3.0 rerun as the control on the same sets (`--no-sources`, series
`scene_stack_eval_v3_allsets`; it reproduces the recorded 0.3.0 numbers on
the four sets 0.3.0 fitted):

| Set | Identical items | Teardrop flips | 0.3.0 joint flips | 0.4.0 joint flips | 0.3.0 isolated broken | 0.4.0 isolated broken | Items with a drawn source | Unexplained light, pooled share: 0.3.0 | 0.4.0 |
|---|---|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_both_n=23] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v3_allsets/465-ally@5822b6646448+a06f04a0059f#all_both_joint_flips=2] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_both_joint_flips=1] | [metric:scene_stack_eval_v3_allsets/465-ally@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#isolated_joint_broken=0] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_items_with_source=4] | [metric:scene_stack_eval_v3_allsets/465-ally@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.0922] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.0646] |
| 465 px enemy (E6) | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_both_n=17] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v3_allsets/465-enemy@5822b6646448+a06f04a0059f#all_both_joint_flips=4] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_both_joint_flips=5] | [metric:scene_stack_eval_v3_allsets/465-enemy@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_items_with_source=5] | [metric:scene_stack_eval_v3_allsets/465-enemy@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.1517] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.1148] |
| Self, Ascent controls | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_both_n=7] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v3_allsets/self-control@e78e75b2d191#all_both_joint_flips=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_both_joint_flips=0] | [metric:scene_stack_eval_v3_allsets/self-control@e78e75b2d191#isolated_joint_broken=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#isolated_joint_broken=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_items_with_source=0] | [metric:scene_stack_eval_v3_allsets/self-control@e78e75b2d191#all_light_unexplained_share_pooled=0.0602] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_light_unexplained_share_pooled=0.06] |
| Self, Lotus | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_both_n=28] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_both_teardrop_flips=2] | [metric:scene_stack_eval_v3_allsets/self-lotus@5822b6646448#all_both_joint_flips=3] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_both_joint_flips=0] | [metric:scene_stack_eval_v3_allsets/self-lotus@5822b6646448#isolated_joint_broken=0] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#isolated_joint_broken=0] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_items_with_source=7] | [metric:scene_stack_eval_v3_allsets/self-lotus@5822b6646448#all_light_unexplained_share_pooled=0.0974] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_light_unexplained_share_pooled=0.0739] |
| 331 px ally | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_both_n=38] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_both_teardrop_flips=3] | [metric:scene_stack_eval_v3_allsets/331-ally@223d636bf8d2+c40d950031bb#all_both_joint_flips=10] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_both_joint_flips=9] | [metric:scene_stack_eval_v3_allsets/331-ally@223d636bf8d2+c40d950031bb#isolated_joint_broken=5] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#isolated_joint_broken=4] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_items_with_source=3] | [metric:scene_stack_eval_v3_allsets/331-ally@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1346] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1244] |
| 331 px self | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_n=37] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_teardrop_flips=6] | [metric:scene_stack_eval_v3_allsets/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_joint_flips=3] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_joint_flips=3] | [metric:scene_stack_eval_v3_allsets/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_broken=1] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_broken=1] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_items_with_source=6] | [metric:scene_stack_eval_v3_allsets/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_unexplained_share_pooled=0.0979] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_unexplained_share_pooled=0.0768] |
| 331 px enemy | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_both_n=15] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_both_teardrop_flips=2] | [metric:scene_stack_eval_v3_allsets/331-enemy@223d636bf8d2+c40d950031bb#all_both_joint_flips=5] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_both_joint_flips=5] | [metric:scene_stack_eval_v3_allsets/331-enemy@223d636bf8d2+c40d950031bb#isolated_joint_broken=2] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#isolated_joint_broken=2] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_items_with_source=6] | [metric:scene_stack_eval_v3_allsets/331-enemy@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1604] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.122] |
| Pooled | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_n=165] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_teardrop_flips=13] | [metric:scene_stack_eval_v3_allsets/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=27] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=23] | [metric:scene_stack_eval_v3_allsets/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=10] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=8] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_source=31] | [metric:scene_stack_eval_v3_allsets/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.1146] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.0905] |

**The disc removes the light term rather than explaining the light.** Pooled
unexplained light falls from
[metric:scene_stack_eval_v3_allsets/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.1146] to
[metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.0905] of 0.3.0's compared
floor, and on the [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_src_items_n=27] items a disc
covers, from [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_nosrc_share_pooled_src_items=0.2019]
to [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled_src_items=0.0074]. But the
disc (radius 67-109 px) covers the whole scene window on most of those items,
so the drop is floor taken out of the comparison, and the fit there is the
sprite alone. The flip changes follow: Lotus loses its three joint flips and
465 px ally one, where 0.3.0's light hurt stacks; the 331 px ally item
c40d950031bb 577.38 s stays broken (its window lies inside the self's
disc, so no light constrains it). Pooled joint flips on identical items
fall from [metric:scene_stack_eval_v3_allsets/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=27] to
[metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=23], still above the teardrop's
[metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_teardrop_flips=13]. The costs were remeasured too,
so part of the change is theirs. Not wired.

**Isolated items the joint fit breaks** (0.4.0, error over 90 degrees where
the teardrop's is not): 465 px enemy a06f04a0059f 33.07 s; 331 px ally
c40d950031bb 366.15 s and 577.38 s, 223d636bf8d2 1351.88 s and 1935.83 s;
331 px self bfad2778a372 2319.97 s; 331 px enemy c40d950031bb 562.38 s and
223d636bf8d2 318.90 s. Only 577.38 s carries a drawn source. 0.3.0 broke
these and two more, which 0.4.0 no longer breaks: 465 px ally a06f04a0059f
2307.23 s and 331 px ally c40d950031bb 190.17 s.

**The floor colour is right where the state is right.** On 0.3.0's compared
floor at unlabelled frames, the median RGB error is [metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#floor_err_median=5.53]
at 331 px and [metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#floor_err_median=3.46] at 465 px; on pixels whose predicted
state is also the nearer one ([metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#floor_right_share=0.804] and
[metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#floor_right_share=0.8769] of them) it is [metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#floor_err_right_median=3.98] and
[metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#floor_err_right_median=2.99], below the calibrated noise
([metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#noise_sigma_255=5.94] and [metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#noise_sigma_255=4.74]). The error lives on
the lit state ([metric:scene_stack_light_cal_v4/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#floor_err_lit_median=17.39] against
[metric:scene_stack_light_cal_v4/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#floor_err_lit_median=8.98]), which is wrong more often at 331 px. That
revises 0.3.0's reading that the 331 px floor colour is mispredicted where
the state is right: the state is what is wrong.

The sheet `analysis/scene-sources-20260930/sheet_sources_331_0.png` in the
store shows the drawn circles over the 331 px crops (audio white) and the
freed floor green.

**Open questions for the player.** Does the audio circle stay where the
sound was made (at e37fdeca944f 1795.08 s its centre lies about 17 px from
the self icon)? The circle has a footstep size and a smaller reload size
[domain:minimap/self-audio-circle]; the fits here hold per session (66.8 px
on Ascent c40d950031bb, 108.5 px on Lotus 5822b6646448), but one Sunset
match reads 74.7 and 96.8 px, a ratio no reload explains, and a few frames
fit 40-62 px circles round the self that may be other circles. How large is each ability's area, how
long does it last, what tint and shape does it have (the Sonic Sensor at
5822b6646448 1695.75 s shows a pale box, not a circle)? Where is the
Trademark at e37fdeca944f 1795.08 s? What is the faint ring round the
widget centre in every frame? And the audio disc should be rendered as a
white tint over either floor state, not freed: what is its opacity?

### Stage 2, 0.5.0: the sources as tints

`scene-stack-0.5.0` renders each drawn source as a measured tint,
`(1 - a) bg + a W`, over either floor state, so the cones keep predicting
the state inside it. Predictions P20-P24 were logged first (task
`scene-tint-20260930`). The player answered two questions of 0.4.0: the
audio circle follows the self icon, and its drawn size follows the map
scaling setting, not the widget size [domain:minimap/self-audio-circle]
[domain:capture/minimap-size-settings]; the faint ring round the widget is
its boundary [domain:minimap/widget-ring]. The player intends the largest
widget size and map scaling from 2026-09-30, believing the whole map then
shows [domain:capture/largest-scaling-shows-whole-map-belief].

**The 96.8 px circle at e37fdeca944f 1795.08 s is the dead Clove's.** At
native size the frame shows two circles: the audio circle (75.5 px, centred
1.9 px from the stored self) and a 96.8 px one centred 0.6 px from the last
position of stored ally track 612, which ends at the ally Clove's death at
1781.0 s in the stored death data. 0.4.0 fitted the larger one round the
self and called it audio. 0.5.0 seeks the Clove circle round the death point
(the stored death data hold no place, so the point is the end of the ally
track that ends then). On e37fdeca944f it finds the circle after
[metric:scene_stack_tint_cal_v5/clove-runs@e37fdeca944f#deaths_with_circle=7] of
[metric:scene_stack_tint_cal_v5/clove-runs@e37fdeca944f#deaths_with_point=19] ally Clove deaths with a
point, radius [metric:scene_stack_tint_cal_v5/clove-runs@e37fdeca944f#r_median=96.85] px, centred
[metric:scene_stack_tint_cal_v5/clove-runs@e37fdeca944f#off_death_median=1.67] px from it. One of those
runs (2 frames, 85.9 px, after 913.5 s) is doubtful. A Clove fit near a
death point the self stands on first found the self audio circle; radii
at the session's audio sizes now leave the Clove search, and a fit that
lands there is refused. Of the six labelled dead-Clove items, only 1795.08 s
draws the circle ([metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_clove=1] item).

**The audio fit is audio_circle's.** `audio_circle.frame_fit` replaces
0.4.0's wrapper. On the probe set both observe the same circle on
[metric:scene_stack_fit_agree_v5/all@223d636bf8d2+4f207c0c4e39+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f#both_same=204] of [metric:scene_stack_fit_agree_v5/all@223d636bf8d2+4f207c0c4e39+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f#both=205] frames where both
observe one; the one disagreement is 1795.08 s. A fit counts only centred
within 7 px (scale 1.0; 5.0 px at 331) of the stored self, the p99 of 200
Iso fits' offsets, and at the session's footstep size or its reload size
within 2 px. The six 0.4.0 audio items centred 12-31 px off the self fail
the centre test; audio is drawn on
[metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_audio=23] labelled items.

**The audio circle is a rim, not a disc.** On unlabelled on/off pairs the
interior (over 12 px inside the radius) takes alpha
[metric:scene_stack_tint_cal_v5/audio-scale-0.712@223d636bf8d2+4f207c0c4e39+bfad2778a372+c40d950031bb+e37fdeca944f#alpha_interior_unlit=0.0] at 331 px and
[metric:scene_stack_tint_cal_v5/audio-scale-1.000@5822b6646448+a06f04a0059f#alpha_interior_unlit=0.0] at 465 px; alpha rises to
about 0.15 within 2 px inside the radius and is gone 1 px outside. Over the
rim band, unlit floor takes [metric:scene_stack_tint_cal_v5/audio-scale-0.712@223d636bf8d2+4f207c0c4e39+bfad2778a372+c40d950031bb+e37fdeca944f#alpha_rim_unlit=0.137] and lit
floor [metric:scene_stack_tint_cal_v5/audio-scale-0.712@223d636bf8d2+4f207c0c4e39+bfad2778a372+c40d950031bb+e37fdeca944f#alpha_rim_lit=0.114] at 331 px, from
[metric:scene_stack_tint_cal_v5/audio-scale-0.712@223d636bf8d2+4f207c0c4e39+bfad2778a372+c40d950031bb+e37fdeca944f#pairs=101] pairs; the colour is near white. The Clove
circle is a disc: interior alpha [metric:scene_stack_tint_cal_v5/clove-scale-0.712@e37fdeca944f#alpha_interior_unlit=0.1612], rim
[metric:scene_stack_tint_cal_v5/clove-scale-0.712@e37fdeca944f#alpha_rim_unlit=0.5071], a pink tint
(BGR [metric:scene_stack_tint_cal_v5/clove-scale-0.712@e37fdeca944f#W_b=207.4],
[metric:scene_stack_tint_cal_v5/clove-scale-0.712@e37fdeca944f#W_g=172.0],
[metric:scene_stack_tint_cal_v5/clove-scale-0.712@e37fdeca944f#W_r=180.6]). The light costs return to
0.3.0's: `q_u` [metric:scene_stack_light_cal_v5/scale-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#q_u=0.196] at 331 px and
[metric:scene_stack_light_cal_v5/scale-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#q_u=0.1339] at 465 px.

**The fit on every set**, on the same identical items as 0.4.0:

| Set | Identical items | Teardrop flips | 0.4.0 joint flips | 0.5.0 joint flips | 0.4.0 isolated broken | 0.5.0 isolated broken | Items with a drawn source | Unexplained light, pooled share: 0.4.0 | 0.5.0 |
|---|---|---|---|---|---|---|---|---|---|
| 465 px ally (E6) | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#all_both_n=23] | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_both_joint_flips=1] | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#all_both_joint_flips=2] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#isolated_joint_broken=0] | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#all_items_with_source=2] | [metric:scene_stack_eval_v4/465-ally@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.0646] | [metric:scene_stack_eval_v5/465-ally@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.0921] |
| 465 px enemy (E6) | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#all_both_n=17] | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_both_joint_flips=5] | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#all_both_joint_flips=4] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#isolated_joint_broken=1] | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#all_items_with_source=4] | [metric:scene_stack_eval_v4/465-enemy@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.1148] | [metric:scene_stack_eval_v5/465-enemy@5822b6646448+a06f04a0059f#all_light_unexplained_share_pooled=0.1525] |
| Self, Ascent controls | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#all_both_n=7] | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#all_both_teardrop_flips=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_both_joint_flips=0] | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#all_both_joint_flips=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#isolated_joint_broken=0] | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#isolated_joint_broken=0] | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#all_items_with_source=0] | [metric:scene_stack_eval_v4/self-control@e78e75b2d191#all_light_unexplained_share_pooled=0.06] | [metric:scene_stack_eval_v5/self-control@e78e75b2d191#all_light_unexplained_share_pooled=0.0602] |
| Self, Lotus | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#all_both_n=28] | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#all_both_teardrop_flips=2] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_both_joint_flips=0] | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#all_both_joint_flips=3] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#isolated_joint_broken=0] | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#isolated_joint_broken=0] | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#all_items_with_source=5] | [metric:scene_stack_eval_v4/self-lotus@5822b6646448#all_light_unexplained_share_pooled=0.0739] | [metric:scene_stack_eval_v5/self-lotus@5822b6646448#all_light_unexplained_share_pooled=0.0976] |
| 331 px ally | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#all_both_n=38] | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#all_both_teardrop_flips=3] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_both_joint_flips=9] | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#all_both_joint_flips=10] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#isolated_joint_broken=4] | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#isolated_joint_broken=5] | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#all_items_with_source=3] | [metric:scene_stack_eval_v4/331-ally@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1244] | [metric:scene_stack_eval_v5/331-ally@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1346] |
| 331 px self | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_n=37] | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_teardrop_flips=6] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_joint_flips=3] | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_both_joint_flips=3] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_broken=1] | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#isolated_joint_broken=1] | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_items_with_source=5] | [metric:scene_stack_eval_v4/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_unexplained_share_pooled=0.0768] | [metric:scene_stack_eval_v5/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#all_light_unexplained_share_pooled=0.0975] |
| 331 px enemy | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#all_both_n=15] | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#all_both_teardrop_flips=2] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_both_joint_flips=5] | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#all_both_joint_flips=5] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#isolated_joint_broken=2] | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#isolated_joint_broken=2] | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#all_items_with_source=4] | [metric:scene_stack_eval_v4/331-enemy@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.122] | [metric:scene_stack_eval_v5/331-enemy@223d636bf8d2+c40d950031bb#all_light_unexplained_share_pooled=0.1567] |
| Pooled | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_n=165] | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_teardrop_flips=13] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=23] | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=27] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=8] | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#isolated_joint_broken=10] | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_items_with_source=23] | [metric:scene_stack_eval_v4/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.0905] | [metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.1143] |

**The tint explains almost none of the light, so 0.5.0 is 0.3.0 again.**
The scene window lies inside the audio circle, where alpha is zero, so the
floor there is compared as if nothing were drawn. Every set's joint flips
equal 0.3.0's, and the pooled unexplained share
([metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_light_unexplained_share_pooled=0.1143]) is 0.3.0's, with the circles' floor
back in the denominator. 0.4.0's gain came from taking that floor out of the
comparison. Pooled joint flips are
[metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_joint_flips=27] against the teardrop's
[metric:scene_stack_eval_v5/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#all_both_teardrop_flips=13]. P20-P22 and P24 held; P23 failed.
Not wired.

**Isolated items the joint fit breaks** (0.5.0): 0.4.0's eight
(a06f04a0059f 33.07 s; c40d950031bb 366.15 s and 577.38 s, 223d636bf8d2
1351.88 s and 1935.83 s; bfad2778a372 2319.97 s; c40d950031bb 562.38 s,
223d636bf8d2 318.90 s) and 0.3.0's two more, 465 px ally a06f04a0059f
2307.23 s and 331 px ally c40d950031bb 190.17 s.

The sheet `analysis/scene-tint-20260930/sheet_tint_331_*.png` in the store
shows the 331 px items where either version drew a source or an ally Clove
lay dead: circles in the widget view, tinted floor green.

**Open questions for the player.** Is the Clove circle a filled pink disc
with a brighter rim, as measured? How large is each ability's area, how
long does it last, what tint and shape does it have (the Sonic Sensor at
5822b6646448 1695.75 s shows a pale box)? Where is the Trademark at
e37fdeca944f 1795.08 s? What lights the floor no cone and no circle
explains?

### Where 0.5.0's unexplained light comes from

`prototypes/light_diagnosis.py` (not wired) asks the question in three steps:
the instrument first, then whether the light lags the pose, then one class per
unexplained pixel. The player's rules bound the causes: the drawn light is
binary, uniform and unlimited in range, stopping only at geometry or a
light-stopping obstacle [domain:minimap/vision-light-binary], and it does not
linger [domain:minimap/vision-trailing-persistence]. Predictions L1-L10 were
logged first; their outcomes are in the store's `notes/predictions.jsonl`.

**The instrument.** Certain-unlit floor is known floor at round start that no
team icon's 360-degree cast reaches; certain-lit floor is the core of a
confident teardrop's cone on unlabelled frames. The rule's per-pixel error:

| Set | Frames | Pixels | Per-pixel wrong | Regions | Regions wrong by majority |
|---|---|---|---|---|---|
| lit, 331 px | [metric:light_diagnosis/instrument-lit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#frames=29] | [metric:light_diagnosis/instrument-lit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#px=4928] | [metric:light_diagnosis/instrument-lit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#rule_wrong_share=0.1179] | [metric:light_diagnosis/instrument-lit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#regions=46] | [metric:light_diagnosis/instrument-lit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#region_wrong_share=0.1087] |
| lit, 465 px | [metric:light_diagnosis/instrument-lit-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#frames=29] | [metric:light_diagnosis/instrument-lit-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#px=8699] | [metric:light_diagnosis/instrument-lit-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#rule_wrong_share=0.1214] | [metric:light_diagnosis/instrument-lit-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#regions=43] | [metric:light_diagnosis/instrument-lit-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#region_wrong_share=0.1628] |
| unlit, 331 px | [metric:light_diagnosis/instrument-unlit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#frames=33] | [metric:light_diagnosis/instrument-unlit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#px=574201] | [metric:light_diagnosis/instrument-unlit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#rule_wrong_share=0.066] | [metric:light_diagnosis/instrument-unlit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#regions=364] | [metric:light_diagnosis/instrument-unlit-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#region_wrong_share=0.1319] |
| unlit, 465 px | [metric:light_diagnosis/instrument-unlit-1.000@5822b6646448+a06f04a0059f#frames=18] | [metric:light_diagnosis/instrument-unlit-1.000@5822b6646448+a06f04a0059f#px=872397] | [metric:light_diagnosis/instrument-unlit-1.000@5822b6646448+a06f04a0059f#rule_wrong_share=0.0541] | [metric:light_diagnosis/instrument-unlit-1.000@5822b6646448+a06f04a0059f#regions=184] | [metric:light_diagnosis/instrument-unlit-1.000@5822b6646448+a06f04a0059f#region_wrong_share=0.087] |

The logged stop rule (region error over 10%) fired on three sets. I checked
the instrument before accepting it. Each set's five worst regions are wrong
wholesale (85-100% of their pixels), not split as per-pixel noise would leave
them, and at native size the pixels agree with the classifier: light passes a
baked box outline in an ally's wedge (a06f04a0059f 626.000 s) and at a
corridor's end (223d636bf8d2 605.500 s); the self's cone is not drawn at all
(bfad2778a372 618.133 s); the model's cast crosses a wall the drawn light
stops at (a06f04a0059f 1400.017 s). The certain sets rest on the model's own
walls and poses, so these are truth-set errors. The classifier stands, with
5-12% per-pixel error as an upper bound, and the causes were tested.

**The lag.** For moving team icons, the light at frame t was compared with
cones cast from the teardrop pose at t-2 .. t+2 (15 Hz). Of
[metric:light_diagnosis/lag-moving-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#icons=34]
icons,
[metric:light_diagnosis/lag-moving-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#best_pos_n=19]
fit a LATER pose best,
[metric:light_diagnosis/lag-moving-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#best_neg_n=8]
an earlier one and
[metric:light_diagnosis/lag-moving-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#best_zero_n=7]
the same frame; the median gain is
[metric:light_diagnosis/lag-moving-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gain_share_median=0.0381]
of the union's pixels. Still icons fit the same frame on
[metric:light_diagnosis/lag-still-1.000@5822b6646448+a06f04a0059f#best_0_share=0.5]
of cases. The drawn light leads the teardrop read by one or two frames, or the
teardrop icon draws late: weak (sign test p about 0.05), and kept apart from
the classes below. L10 failed.

**The classes.** Each unexplained pixel of the 180 rebuilt labelled scenes
(every stored `unexplained_n` reproduced) and of 110 one-icon scenes on
unlabelled frames takes the first class that holds. NOISE comes first: floor
predicted unlit splits into cells bounded by the cone, the baked walls and
every cause mask, and a binomial test with the instrument's rates decides
each cell's one state; unexplained pixels in a cell decided unlit, or in one
under 4 px (scale squared), are noise. The rest are coherent light.

| Part | Scenes | Noise | Team vision | Utility | Occluder | of which boxes | Edge or range | Lingering | Residual |
|---|---|---|---|---|---|---|---|---|---|
| labelled, 331 px | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#scenes=100] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#noise_share=0.5] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#team_vision_share=0.2137] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#utility_share=0.0094] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#occluder_share=0.2085] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#occluder_box_share=0.0278] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#edge_range_share=0.0045] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#lingering_share=0.021] | [metric:light_diagnosis/classify-labelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#residual_share=0.0428] |
| labelled, 465 px | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#scenes=80] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#noise_share=0.5775] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#team_vision_share=0.1767] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#utility_share=0.0098] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#occluder_share=0.2104] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#occluder_box_share=0.0674] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#edge_range_share=0.0083] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#lingering_share=0.0127] | [metric:light_diagnosis/classify-labelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#residual_share=0.0046] |
| unlabelled, 331 px | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#scenes=58] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#noise_share=0.4426] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#team_vision_share=0.2444] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#utility_share=0.0] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#occluder_share=0.1259] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#occluder_box_share=0.0233] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#edge_range_share=0.008] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#lingering_share=0.0623] | [metric:light_diagnosis/classify-unlabelled-0.712@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#residual_share=0.1168] |
| unlabelled, 465 px | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#scenes=52] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#noise_share=0.5105] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#team_vision_share=0.1972] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#utility_share=0.0] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#occluder_share=0.2037] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#occluder_box_share=0.051] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#edge_range_share=0.0089] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#lingering_share=0.0062] | [metric:light_diagnosis/classify-unlabelled-1.000@5822b6646448+a06f04a0059f+e78e75b2d191#residual_share=0.0735] |
| pooled | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#scenes=290] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#noise_share=0.5222] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#team_vision_share=0.2012] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#utility_share=0.0063] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#occluder_share=0.1964] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#occluder_box_share=0.0463] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#edge_range_share=0.0073] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#lingering_share=0.0209] | [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#residual_share=0.0457] |

Read each class against the control (floor predicted unlit that reads unlit):

- **Noise is half of it.** Most unexplained pixels are the reader's per-pixel
  error inside cells whose state is unlit.
- **Team vision** is the largest coherent class: `team_vision`'s stored cones
  cover coherent light
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#raw_team_vision_ratio=3.22]
  times as often as the control. Its tracks place teammates the scene misses
  or poses them differently, as in stacks.
- **Occluders** split. Light past a baked box is enriched
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#raw_box_ratio=7.26]
  times. Light in a wedge past a baked wall is enriched only
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#raw_wall_ratio=1.4]
  times, so most of that class is residual in practice. The sheets show it as
  thin strips along wall lines, as if the baked walls sit a pixel or two off
  or a drawn line does not stop the light.
- **Edge and range** explain almost nothing. The scene's range cap removes no
  light, and the width holds: the lit share falls from
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#edge_lit_0_5=0.2674]
  within 5 degrees outside a wedge to
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#edge_lit_20_40=0.1299]
  at 20-40 degrees. That is the blurred edge, not a wider cone.
- **Lingering** decays as a lag would: team vision's cones from the last
  0.267 s cover coherent light
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#linger_267ms_ratio=2.88]
  times as often as the control, falling to
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#linger_1000ms_ratio=1.46]
  at 1 s and
  [metric:light_diagnosis/classify-pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#linger_3000ms_ratio=1.13]
  at 3 s. Those are another reader's poses at earlier frames, so the excess
  does not show that light lingers.
- **Utility** covers almost no floor: the store holds few spatial ability
  observations [domain:abilities/ability-rules-are-unique].

The twelve sheets `analysis/light-diagnosis-20260930/sheet_*.png` in the store
show the largest coherent cells, at most two per session. Four are residual,
and they are the player's questions: a lit square beside an ally and a
black-and-white ability icon (5822b6646448 1901.083 s); lit floor inside a
large circle round a black ability icon, at bfad2778a372 1682.250 s and
223d636bf8d2 882.300 s; lit floor by a red X and a teal icon above a stack
(c40d950031bb 205.500 s). At bfad2778a372 618.133 s the self icon casts no
drawn light. Not wired.

### The drawn areas and the raised edges

The player named three of those cells: the lit square at 5822b6646448
1901.083 s is two Sonic Sensors, and the circles at bfad2778a372 and
223d636bf8d2 are Chamber's Trademarks. `prototypes/drawn_areas.py` measured
each ability on its own instances, from the crop cache and baked geometry.

- **Sonic Sensor**: an axis-aligned square with the icon on the midpoint of
  one side, e.g.
  [metric:drawn_areas/sonic_sensor_94_182@a06f04a0059f#w=26.0] by
  [metric:drawn_areas/sonic_sensor_94_182@a06f04a0059f#h=29.0] px, a flat tint
  of alpha
  [metric:drawn_areas/sonic_sensor_94_182@a06f04a0059f#alpha_interior_floor=0.168]
  with no brighter rim
  [metric:drawn_areas/sonic_sensor_94_182@a06f04a0059f#alpha_rim_floor=0.196]
  [domain:abilities/deadlock-sonic-sensor-minimap-white-area].
- **Trademark**: a circle centred on the icon, rim alpha
  [metric:drawn_areas/trademark_82_234@bfad2778a372#alpha_rim_floor=0.428],
  interior
  [metric:drawn_areas/trademark_82_234@bfad2778a372#alpha_interior_floor=0.13].
  Its radius follows the map's zoom:
  [metric:drawn_areas/trademark_82_234@bfad2778a372#r_scale1=30.7] px at
  scale 1 on Split,
  [metric:drawn_areas/trademark_204_144@9acf02f98283#r_scale1=27.2] on Ascent
  [domain:abilities/chamber-trademark-minimap-white-area].
- **Neither lights the floor.** Over a minute round each instance, a cone
  crossing the area lifts the floor inside by a median
  [metric:drawn_areas/trademark_82_234@bfad2778a372#cone_interior_excess=40.2]
  levels against
  [metric:drawn_areas/trademark_82_234@bfad2778a372#cone_outer_excess=40.0]
  outside; floor already drawn lit could not rise. The renderer should draw
  both as tints over whatever lighting state the floor has, as 0.5.0 does for
  the audio circle. `team_vision`'s lighting reference learned the bfad
  Trademark's tint as lit floor, so its lit-position of
  [metric:drawn_areas/trademark_82_234@bfad2778a372#interior_lit_position=1.02]
  there is contamination, not light.
- **Detector** (minimap only; not wired): a dark icon disc, a glyph matching a
  template mined from another session, then the ability's area. On ten
  frames across each measured run it finds
  [metric:drawn_areas/detect_sonic_sensor@named-instances#recall=0.95] of
  sensors and
  [metric:drawn_areas/detect_trademark@named-instances#recall=0.875] of
  Trademarks, with
  [metric:drawn_areas/detect_trademark@named-instances#false_on_negatives=0]
  detections on 120 frames of four sessions whose lineup holds neither agent.
  The Trademark stages were revised after the Sunset and Ascent instances
  missed, so those two runs are not held out.

The player's rule for lines [domain:minimap/raised-edge-lines]:
`prototypes/raised_edges.py` splits Ascent's baked lines by what lies
directly beyond each. On the 465 px key
[metric:raised_edges/classify@ascent__valorant-16x9-bigmap#raised_share=0.2257]
of line pixels are raised edges and
[metric:raised_edges/classify@ascent__valorant-16x9-bigmap#places_agree=4]
of 4 named places agree. The occluders treat all of them as walls, so a cone
drawn across a ramp's line stops short in the render and leaves lit floor
unexplained beyond it. Heaven candidates come from the shade rungs, not the
lines. The occluder change is proposed, not made.

The player then labelled every segment on the 465 px key
(`prototypes/label_raised_edges.py sorter`; the last answer per segment
wins, so
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#rows=236]
rows give
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#segments=221]
segments). The sorter's walls are walls: precision
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#wall_precision=0.9706],
recall
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#wall_recall=0.9593].
Its raised edges are mostly box outlines: they catch every ramp line
(recall
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#raised_edge_as_ramp_recall=1.0])
but only
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#raised_edge_as_ramp_precision=0.1569]
of them are ramps, and
[metric:raised-edge-sorter/segments@ascent__valorant-16x9-bigmap#n_box_outline_as_raised_edge=33]
are box outlines. The floor-beyond rule therefore separates walls from
everything else, not ramps from boxes. The player's non-occluding lines
(ramp, heaven edge, other, and the overhang start
[domain:minimap/overhang-start-line]) hold
[metric:raised-edge-occluders/non-occluding-proposal@ascent__valorant-16x9-bigmap#total_occ_px=517]
baked occluder pixels, a share
[metric:raised-edge-occluders/non-occluding-proposal@ascent__valorant-16x9-bigmap#share_of_baked_occ=0.0571]
of the key's occluders. The player approved the change; occluders-2.0.0
below makes it.

### Stage 2, 0.6.0: the light as a binary raycast

`scene_stack.py` 0.6.0 adds four changes, each behind a flag. `--v5`
reproduces 0.5.0: six smoke items matched exactly. `--only` runs one change
alone.

- **cast.** Every teammate in the stored team_vision frame casts, at full
  range. A hidden icon keeps the teardrop of its last visible, isolated read
  and declares that read as `depends_on`.
- **regions.** Each region, bounded by the cone edges and the walls, takes
  one binary state. A binomial with light-diagnosis-0.1.0's per-pixel read
  rates decides it.
- **boxes.** Each caster is either standing or jumping, one state per
  caster [domain:minimap/boxes-block-unless-raised]. Jumping costs 2 ln 9
  and is not tuned.
- **dark.** A darkened minimap is refused with the reason
  `minimap-darkened` [domain:abilities/reyna-leer-darkens-minimap].

On the 165 items that the teardrop and every arm read, the joint flips are
as follows:

| Arm | Flips | Isolated broken | Unexplained share |
|---|---|---|---|
| teardrop | 13 | | |
| 0.5.0 | 27 | 10 | 0.1091 |
| 0.6.0 | 26 | 7 | 0.094 |
| cast only | 24 | 9 | 0.1045 |
| regions only | 26 | 7 | 0.108 |
| boxes only | 27 | 10 | 0.1009 |

The unexplained share is pooled per pixel.

- 0.6.0 cuts the pooled joint flips from
  [metric:scene_stack_compare_v6/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#050_flips=27]
  to
  [metric:scene_stack_compare_v6/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#060_flips=26],
  against the teardrop's
  [metric:scene_stack_compare_v6/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#teardrop_flips=13].
- The unexplained share falls from 0.1091 to
  [metric:scene_stack_compare_v6/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#060_unexplained_share_pooled=0.094].
- Four of the seven predictions failed:
  - cast, not regions, moves the flips most;
  - boxes, not cast, removes the most light;
  - the hidden-icon rule fires on 42 items;
  - jumping wins for 42 of 199 crossing casters.

Where a caster jumps, the pixels past the box read lit on 40 of the 43 boxes
the light decides. The light explains itself better, but the flips barely
move. The joint fit's loss to the teardrop is therefore not mainly a gap in
the light model.

No labelled item is darkened: c40d950031bb 205.5 s sits at the static's grey,
and its blind begins one cache frame later. The joint fit flips that item in
both versions.

Of the 42 jumping casters, 31 belong to a side whose lineup names no boost
agent. Each of those is stored as `pass-without-boost`: every box it crosses
must be short, or the model is wrong. Height classes wait on the Lotus
elevation measurement.

At bfad2778a372 618.133 s no track places Deadlock, so no hidden icon casts.
The joint fit instead turns the self to 15°, against the teardrop's −161°,
and makes it jump. The stored track angle is 19.9°. Which way the self faced
is a question for the player.

The sheets are the store's `analysis/scene-raycast-20260930/sheet_v6_*.png`.
Not wired.

### The sorted lines in the occluders (occluders-2.0.0)

The player approved rebuilding the occluders from the line labels and the
sorter. `prototypes/line_classes.py` (line-classes-1.0.0) bakes a class per
line pixel into each geometry npz: wall, box, ramp, other or unread, with its
source. The player's answers override the sorter (Ascent and Lotus at
465 px); the other ten keys carry the sorter's classes alone and are marked
unvalidated. `reticle/occluders.py` 2.0.0 reads the classes. Walls stop light at
every observer height and boxes by height class
[domain:minimap/boxes-block-unless-raised]; ramp, heaven-edge and
overhang-start lines never do. It also clears
art-wall pixels beside a line that no longer occludes. On Ascent's 465 px
key it opens
[metric:geometry-lines/occluders-2.0.0@ascent__valorant-16x9-bigmap#opened=655]
occluder pixels. A box keeps a height class only where a player note or a
heights file names one; every other box is unknown. On Ascent
[metric:geometry-lines/occluders-2.0.0@ascent__valorant-16x9-bigmap#box_px_tall=28]
box pixels are tall (the generator among them).

0.6.0 was rerun without changes, with the rebuilt geometry, on the same 165
items:

| Arm | Flips | Isolated broken | Unexplained share |
|---|---|---|---|
| teardrop | 13 | | |
| 0.6.0 | 26 | 7 | 0.094 |
| 0.6.0, rebuilt occluders | 28 | 9 | 0.0921 |

- The pooled unexplained share falls to
  [metric:scene_stack_compare_v6_lines/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#060_lines_unexplained_share_pooled=0.0921].
- The flips rise to
  [metric:scene_stack_compare_v6_lines/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#060_lines_flips=28].
  Two new flips are isolated 465 px enemies.
- Per map, the share falls on Ascent, to
  [metric:scene_stack_compare_v6_lines_by_map/ascent@a06f04a0059f+c40d950031bb+e78e75b2d191#060_lines_unexplained_share_pooled=0.0961],
  and on Split, to
  [metric:scene_stack_compare_v6_lines_by_map/split@bfad2778a372#060_lines_unexplained_share_pooled=0.1059].
- It rises on Haven, to
  [metric:scene_stack_compare_v6_lines_by_map/haven@223d636bf8d2#060_lines_unexplained_share_pooled=0.1186]
  from 0.1122. That falsifies prediction G4 on an unvalidated key.

Opening the lines explains a little more light, but it moves no flips
back. The joint fit's loss to the teardrop is not an occluder gap. Haven's
classes need the player's answers.

The sheets are the store's `analysis/geometry-lines-20260930/occ_*.png`.

### Stage 2, 0.6.1: the self role after the player's death

After the player dies, the self icon shows a spectated teammate, and no
self audio circle is drawn [domain:minimap/self-audio-circle]. 0.6.1 asks
the tray gate's owners whether the player lives (`ability_timeline.kit_windows`
over the stored killfeed deaths and kit changes, read per item through
`adjudication.ability_state`'s context). Where the player is dead, the item is
`spectating`: the audio circle is not sought, and the self role's boost
eligibility comes from `tray_kit.spectated_agent`, or is `unknown`. The self
role still casts light.

The gate covers
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_n=57]
of the 165 items. On them the teardrop flips
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_teardrop_flips=2],
and the joint fit flips
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_061_flips=11]
at 0.6.1, as at 0.6.0. The gate removed the audio circle from
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_audio_drawn_060=2]
items and changed
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_joint_changed=0]
joint readings. The pooled flips stay at
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#061_flips=26].
Refitted items outside the gate read exactly as at 0.6.0
([metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#ungated_check_identical=15]
of 15). Pass-without-boost surprises on gated items fall from
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_pass_without_boost_060=9]
to
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#gated_pass_without_boost_061=5].
Five self jumps became `unknown`. At c40d950031bb 411.15 s the kit witness
names the spectated Jett, so the ally set loses its only boost agent and one
ally jump becomes a new surprise. Four of the six sessions have no stored
`tray_kit` rows, so no spectated agent is named there.

The joint fit therefore loses to the teardrop mostly after the player's
death: 11 of its 26 flips fall on the gated items, against 2 of the
teardrop's 13. Neither the audio circle nor boost eligibility causes this.
Boost eligibility is a label written after the fit.

At bfad2778a372 618.133 s, 0.6.1 reads
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#bfad_618133_061_joint=15.0]
degrees with a jump, as 0.6.0 does, against the teardrop's
[metric:scene_stack_compare_v61/pooled@223d636bf8d2+5822b6646448+a06f04a0059f+bfad2778a372+c40d950031bb+e37fdeca944f+e78e75b2d191#bfad_618133_teardrop=-161.37].
0.6.0 drew no audio circle there, so neither changed term drove the 15°.
The player's account (Jett faced Ropes, then turned toward Deadlock) agrees
with the teardrop.

## What this plan does not settle

- The draw order between icons is fitted, not known; stage 1 does not
  check it against the player.
- No portrait art is drawn: 0.1.0 predicts a key-neutral disc, 0.2.0
  masks the disc out of the comparison. Art for the arbiter's agents
  (the player's agent, the side's five) is untried.
- The enemy lobe's opacity (0.5) and the gains' bounds were set by eye on
  unlabelled frames, not measured; the shared-gain variant was tried after
  the labelled scores were seen, so it is post hoc.
- The 331 px background: 0.4.0 measured the floor colour right where the
  state is right; the lit state is predicted wrong more often at 331 px.
- The audio circle is rendered as its measured rim tint; its interior is
  untinted floor, so it explains no light there.
- One labelled item shows a Clove circle and none an ability area, so
  neither is scored on its own.
- Redundant light: a cone a neighbour's cone already covers, or one cast
  into a wall, is weak evidence, and 0.3.0 lets a stacked icon point it
  there. The cost of unexplained light is one rate per widget, not per
  place, and the cone's reach is uncapped inside the window.
- No audio-video offset is measured, and no chat reader exists.
