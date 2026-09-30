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

## What this plan does not settle

- The draw order between icons is fitted, not known; stage 1 does not
  check it against the player.
- No portrait art is drawn: 0.1.0 predicts a key-neutral disc, 0.2.0
  masks the disc out of the comparison. Art for the arbiter's agents
  (the player's agent, the side's five) is untried.
- The enemy lobe's opacity (0.5) and the gains' bounds were set by eye on
  unlabelled frames, not measured; the shared-gain variant was tried after
  the labelled scores were seen, so it is post hoc.
- The 331 px background: the floor's colour is mispredicted even where
  0.3.0 predicts its lit state right. The next step measures that mismatch
  on unlabelled frames (alignment, scaling, compression, the lit tint) and
  fixes it before any new label.
- Redundant light: a cone a neighbour's cone already covers, or one cast
  into a wall, is weak evidence, and 0.3.0 lets a stacked icon point it
  there. The cost of unexplained light is one rate per widget, not per
  place, and the cone's reach is uncapped inside the window.
- No audio-video offset is measured, and no chat reader exists.
