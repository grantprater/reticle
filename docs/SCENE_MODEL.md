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
built and scored (`prototypes/scene_stack.py`, section 8); it fails at the 331 px widget.

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

1. **Stacks** (built, below): touching icons fitted jointly in the owners'
   class keys over the baked static's keys, portraits key-neutral, no light.
2. **Cones and light**: render each fitted icon's cone as light over the
   floor, stopping at `occluders`; the light becomes evidence for facing
   inside the same fit, which E12 did as a separate fusion.
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

## What this plan does not settle

- The draw order between icons is fitted, not known; stage 1 does not
  check it against the player.
- The portraits are key-neutral discs in stage 1; no identity enters, and
  a portrait whose colours match its class key costs a constant.
- The enemy lobe's opacity (0.5) and the gains' bounds were set by eye on
  unlabelled frames, not measured; the shared-gain variant was tried after
  the labelled scores were seen, so it is post hoc.
- How to render the portrait: from art for the side's five, or masked out
  of the comparison at 331 px. The next step is one of the two, scored on
  the same sets before any new label is spent.
- No audio-video offset is measured, and no chat reader exists.
