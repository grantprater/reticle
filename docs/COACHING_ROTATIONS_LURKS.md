# Coaching module 1: rotations and lurks

Date: 2026-10-04. Status: proposed plan; nothing here is built. Rules stay in
[AGENTS.md](../AGENTS.md); commands stay in [WORKING_MAP.md](WORKING_MAP.md).
The research this builds on is
[WIN_PROBABILITY_RESEARCH.md](WIN_PROBABILITY_RESEARCH.md); the behaviour framing is
[BEHAVIOUR_MODEL_DESIGN.md](BEHAVIOUR_MODEL_DESIGN.md), whose candidate
signatures name the lurker and the anchor.

The player chose rotations and lurks as the first coaching question. Asked
how to judge the module, he answered "probably my rating initially, though
that is a bad metric" (the player, 2026-10-04 (chat)). Section 0 states the
position values he gave.

## Summary

1. **Ally positions, team vision, deaths, rounds and alive counts are stored
   for 21 of the 22 match captures; several other inputs are missing or
   thin.** Ally and self positions (`round_entity`), team vision and facing
   (`team_vision`), deaths, rounds, plant times, alive counts, the spike
   glyph and lineups cover those 21; 0f08b3dc3777 has no `round_entity`
   file. Pings cover 20, smokes 4, and enemy tracks and projected entity
   lanes 3. No owner answers "which callout is this position in"; no stored
   event holds the plant site; the killer's position is null on every
   stored verdict checked; facing is not keyed to the entity (section 1.1).
2. **Callout points make poor regions.** Nearest-point cells built from the
   valorant-api callouts put a fifth of ally positions about the ally
   reader's p95 error from a boundary, and still allies sit there more often
   (section 3). Regions need drawn polygons and a dead band. Whether 2 Hz
   then suffices is stage 1's test R2; the measurement here cannot separate
   rate from boundary flicker.
3. **Allies are observable; enemies are censored.** Ally rotations and lurks
   can be defined on observed tracks. Enemy rotations exist only between
   sightings, so every enemy-dependent feature is a belief until in-client
   Replays supply truth.
4. **The smallest prototype needs no decode and no new reader**: super-region
   presence with hysteresis over stored ally tracks, rotation and lurk
   candidates, scored against Riot's kill-instant positions and rated by the
   player (section 5, stage 1).
5. **Nothing reaches the player before the match ends.** Post-round results
   are computed and stored, and shown only after the match (section 6).

## 0. What the player values in a position

Coaching values a position relative to the teammates' held angles and the
enemy kit's utility, not as raw coordinates. In the player's words, after the
research found raw positions add nothing measurable to round win
probability: "positions probably matter in general much less than
context-dependent positions: not holding the exact same angle your teammate
already is, not choosing the same rat angle when the enemy team has flashes
and stuns, things like that which is much harder to model" (the player,
2026-10-04 (chat)).

The module's position features therefore score relations rather than
coordinates alone: a hold against the holds of living teammates (`duplicate_hold`, section 2.1),
and an off-angle against the disables the enemy lineup carries
(`off_angle_repeat`, section 2.2). Position precision is judged by whether
these relations flip, not by coordinate error.

## 1. Definitions as events

### 1.1 What the store holds

Each row names a stream the module would read, the field it uses, and where
the field was checked (session a06f04a0059f, 2026-10-04, unless stated).
The store holds 22 match captures, each with a Riot record. "21" means the
stream exists for 21 of them; 0f08b3dc3777 (Summit) has no `round_entity`
file ([metric:coaching_inputs/pose_join@a06f04a0059f#round_entity_files=21]
of [metric:coaching_inputs/pose_join@a06f04a0059f#riot_records=22]). "3"
means only 5822b6646448, a06f04a0059f and bfad2778a372.

| Need | Stream / file | Fields checked | Sessions | Owner |
|---|---|---|---|---|
| Ally and self position | `events/round_entity` `observation` rows | `entity_id`, `family` (ally, self and barrier; the module reads ally and self), `t_ms`, `frame_idx`, `x`, `y`, `state`, `identity_status` | 21 | `round-entity-session` |
| Same, in the consumer schema | `events/entity_round_entity` `pose` rows | `position.frame` (`baked:<geometry key>`), `x`, `y`; `orientation` null, reason "no pose owner keys a facing by this observation" | 3 | `entity-event` |
| Ally facing and team vision | `events/team_vision` `frame` rows, 15 Hz | `icons[]`: `role`, `track_id`, `x`, `y`, `facing`, `eligible`, `casts`, `pose`; `observable` (packed union of eligible cones), `observable_all` | 21 | `team-vision` |
| Enemy sightings | `events/enemy_track` `observation`, `entity`, `mark` rows | `x`, `y`, `r`, `facing`; entity `agent`, `last_seen_ms`, `end_reason`, `mark_id`; mark `onset_ms`, `last_ms` | 3 | `enemy-track-session`, `last-known-mark` |
| Deaths | `events/death` `death_verdict` rows | `t_ms`, `round_no`, `side`, `victim`, `killer`, `weapon`, `location` (non-null for 84 of 184), `killer_location` (null for all 184) | 21 | `death-victim` |
| Rounds, side, plant | `l2/rounds/.../rounds.parquet` | `t_start_ms`, `t_end_ms`, `won`, `player_side`, `map`, `spike_planted`, `plant_t_ms`, `post_plant_ms` | 21 | `round-bounds` |
| Plant site | `events/entity_spike` | `position` null, reason "rounds stores no plant site" | 3 | none |
| Round end reason | `events/round_outcome` `round_outcome_claim` | `end_reason`, `winner`, `t_end_ms` | 21 | `round-outcome` |
| Alive counts | `l1/roster/.../roster.parquet`, about 2 Hz | `alive_ally`, `alive_enemy` | 21 | `alive-count` |
| Spike on the minimap | `events/spike` `frame` rows, a sampled grid (1,691 frames) | `glyphs[]`: `cx`, `cy`, `state` (carried, dropped; no planted state stored) | 21 | `spike-observation` |
| Team pings | `events/ping` | `kind` (standard, danger, need_help, on_my_way), `t_ms`, `x`, `y`, `frame` = `widget` | 20 | `ping-event` |
| Ultimates, both sides | `events/ult_cast` `cast` rows | `t_ms`, `round`, `side`, `agent`, `class` | 27 files | `ult-cast` |
| Allied smokes | `events/smoke` `track` rows | `first_ms`, `last_ms`, `cx`, `cy`, `r` | 4 | `minimap-smoke` |
| Lineups | `lineups/<sid>.json` | `sides`, `player` | 21 | `agent-identity` (sides), `agent-from-slot` |
| Ability functions | `reference/abilities.json` | per ability `functions` (Blind, Flash, Concuss, Nearsight, Detain, ...), harvested from valorant-api and the wiki on 2026-09-04 | all agents | none (catalogue) |
| Callouts | `external/valorant-api/maps.json` | per map `callouts[]`: `regionName`, `superRegionName`, `location` (game units); `xMultiplier`, `yMultiplier`, `xScalarToAdd`, `yScalarToAdd` | [metric:coaching_inputs/pose_join@a06f04a0059f#maps_with_callouts=16] maps, District, Drift and Kasbah among them | none |
| Riot match records | `external/riot/*.json` `match` | `roundResults[]`: `plantSite`, `plantRoundTime`, `plantLocation`, `defuseRoundTime`, `winningTeam`, `playerStats[].kills[]` with `playerLocations[]` (`location`, `viewRadians`), `victimLocation`, `assistants`; `playerStats[]`: `stayedInSpawn`, `wasAfk`, `economy` | 22 records | scored by `prototypes/riot_ground_truth.py` (wire: no) |

`prototypes/riot_ground_truth.py` (`MapFrame`, `game_to_uv`, `art_affine`)
already carries Riot game units into the baked frame through the geometry's
`shade_fit`; the same transform places the callout points.

**Gaps that block or weaken the module.** Each belongs in its owner's event,
never in a recomputing consumer:

- *Regions.* No owner. Section 3 shows point cells are not enough.
- *Plant site.* `round-bounds` owns the plant and stores no site;
  `entity_spike.position` is null with that reason. The last carried or
  dropped glyph before `plant_t_ms`, or the planted icon
  [domain:minimap/spike-planted-icon], which no reader matches, could supply
  it. Riot's `plantSite` scores it.
- *Ally facing on the entity.* `team_vision` icons carry `track_id`, not the
  `round_entity` `entity_id`; the entity pose stores no orientation. The data
  supports the join: on a06f04a0059f,
  [metric:coaching_inputs/pose_join@a06f04a0059f#tv_icons_joined=37254] of
  [metric:coaching_inputs/pose_join@a06f04a0059f#tv_icons_with_facing=51445]
  icons with a facing match a `round_entity` observation exactly on frame, x
  and y. The gap is ownership: events are the interface, so no consumer may
  make that join; the pose owner must key facing by entity.
- *Killer position.* Null on every stored verdict here.
- *Enemy tracks* exist for 3 sessions; `minimap_objects` has run on 3.
- *Sound.* No stored event holds enemy footsteps or ability sounds; voice
  lines (`ult_line`, `ult_cast`) are the only stored sounds of other
  players. Chat callouts [domain:hud/chat-broadcasts-callouts] sit in an
  unread HUD region; spotted callouts draw nothing on the minimap
  [domain:minimap/spotted-callouts-draw-nothing].
- *Assists.* The killfeed draws the disabling ability that assisted a kill
  [domain:killfeed/disabling-ability-assist-icon]; no stored stream reads
  it.
- *Team voice.* Whether the capture holds the team's voice chat is not
  known.

### 1.2 The event layer

The module reads emitted entity lanes (`reticle project SESSION --lane
round_entity --lane death --lane spike --lane enemy`, stored data only) and
emits its own events. It never reads a reader, tracker or adjudicator. Each
event carries `entity_id` and the lane's identity reference, never an agent
name of its own (`adjudication.identity` decides names). Every threshold below
is a parameter to set with the player, stored with the event's version.

**`region_presence`** (per entity, an interval). The entity is in region R
(callout) and super-region S (A, B, C, Mid, Attacker Side, Defender Side, as
valorant-api names them) from `t_enter_ms` to `t_exit_ms`. A change needs the
position to sit inside the new region by a dead band (proposed: twice the
reader's p95 error, [metric:riot_truth/minimap/all#pos_err_px_p95=3.8] px,
so 7.6 px) for at least two samples. Gaps keep the interval open with a
reason; a death closes it. Enemy intervals open at a sighting and close at
the last sighting, right-censored, with the last-known mark as a place and a
time [domain:minimap/last-known-mark], never a presence.

**`team_commit`** (per round). The attacking team's commitment to a site:
the first instant at which a set share of the living attackers (proposed:
three, or all if fewer live) stand in one site super-region, or the plant,
whichever comes first. On defence, the retake commit: the first instant a set
share of living defenders enters the planted site after the plant. Fields:
`site`, `t_ms`, `members`, `trigger` (`presence` or `plant`).

**`rotation`** (per entity). A move from one site super-region to another,
directly or through Mid: `from_site`, `to_site`, `t_exit_ms` (last sample in
the origin), `t_arrive_ms` (first sample in the destination; null with a
reason if the player died or the round ended en route), `path` (region
sequence), `duration_ms`, `died_en_route`. A group rotation joins rotations
of two or more allies whose exits fall within a set window. Context fields,
each an explicit list with evidence links:

- `cues`: every stored information event in a set window before
  `t_exit_ms`, with its lag: a death (time from the killfeed, place from the
  X mark when placed), an enemy sighting or last-known mark, the spike
  sighted or its "?" [domain:minimap/enemy-spike-ground-vision], a ping, the
  plant, an ult cast. The list states co-occurrence, never cause; an empty
  list stores `no_cue_observed` with the window searched.
- `relative`: lag from the plant, from the team commit, from the round's
  first death; alive counts at exit and arrival.
- `outcome`: arrived before or after the plant; kills and deaths of the
  rotator in the destination within a set window; the round's result.

**`lurk`** (per attacking entity). During the team commit, an ally stands in
a different super-region from the commit's site, or beyond a set geodesic
distance from the committed members, for at least a set time. Fields:
`entity_id`, `regions`, `t_start_ms`, `t_end_ms`, `t_from_commit_ms`,
`distance_m`, `first_contact_ms` (the lurker's first kill or death, or an
enemy sighting within a set radius), `outcome` (kills, death, whether the
kill fell within a set window of the commit's first fight, round result).
A defender holding off-site after a plant is a different event
(`offsite_hold`), not a lurk; the player decides whether it exists.

**`hold`** (per entity). The entity stays within a set radius and keeps its
facing within a set arc for a set time. Fields: position, mean facing and
its spread, region, and the footprint: the cone's raycast against baked
occluders by the `viewcone` owner (`cone.py`) from the stored pose, never a
session-built mask [domain:capture/session-pixels-are-not-the-map]. The
footprint under-claims where rays stop [domain:minimap/cone-rays-stop-at-first-edge];
an icon with no cone [domain:minimap/ally-icon-without-cone] stores a hold
with no footprint and its reason.

**`duplicate_hold`** (pairs). Two allied holds overlap in time and in the
entry they cover, and stand close with a small angle between their lines to
that entry. Two players covering one entry from widely separated angles form
a crossfire, which the event must not flag. Fields: both hold ids, footprint
overlap, angular separation, the covered entry, `outcome` (both died within a
trade window, one peek killed both).

**`off_angle_repeat`** (per entity). A hold at a position the corpus rarely
uses (a low-density place among stored holds on that map and side), repeated
in a later round of the same match against the same enemy lineup. Fields:
both holds, the rounds, the outcome of each, and `enemy_kit` (section 2.2).

### 1.3 What is observable, allies against enemies

| Quantity | Allies and self | Enemies |
|---|---|---|
| Position | every living ally placed at 49-51% of grid instants (research doc, section 3); [metric:riot_truth/minimap/all#matched=8366] of [metric:riot_truth/minimap/all#riot_allies=10445] Riot ally positions matched | only inside team vision [domain:minimap/vision-gate], drawn briefly after vision ends [domain:minimap/vision-trailing-persistence], then a "?" for about 3 s [domain:minimap/last-known-mark-timing] |
| Facing | teardrop facing within 30° on [metric:riot_truth/minimap/all#facing_within_30=0.878] of matched allies | `enemy_track` stores `facing` per sighting |
| Rotation | observed, start and end | inferred between sightings; censored |
| Lurk | observed | not defined; an enemy lurk is a belief |
| Death | time, side, victim, killer, weapon; place when the X mark is placed | same |
| Abilities | allied smokes on the minimap; the player's casts from the tray and audio | ultimates by voice line; enemy smokes are not drawn [domain:abilities/enemy-smokes-not-on-minimap]; other casts only as killfeed weapons or rare drawn glyphs |
| Information held | the team's minimap is shared; the player's own audio and screen | none |

## 2. Context features

### 2.1 Not holding the angle a teammate holds

From `hold` and `duplicate_hold`. The footprint comes from the stored pose
and the `viewcone` raycast; `team_vision.observable` is the union over all
eligible cones and cannot split it per ally. A duplicate needs a definition
of "the same angle", and the player's call decides it: overlapping
footprints alone also flag crossfires. Proposed measure: the share of each
footprint's entry pixels (floor pixels on a choke between regions) the other
covers, gated by angular separation under a set value (proposed 30°) and
distance under a set value. Facing accuracy suffices: the error against the
player's labels is a median 2.5° (research doc, section 6b), and 30° is the
gate.

### 2.2 Not taking the same off-angle into an enemy kit

The enemy kit is a candidate set, not an observation. The match's enemy
agents come from `agent-identity`'s side assignment (`lineups/<sid>.json`).
Each agent's abilities and their harvested `functions` come from
`reference/abilities.json`. Ability mechanics are unique per ability
[domain:abilities/ability-rules-are-unique], so the catalogue's labels
choose which abilities to ask about; they never stand for how an ability
behaves. Per round, `enemy_kit` carries:

- `agents_with_disables`: enemy agents whose kits list Blind, Flash,
  Concuss, Nearsight, Detain, Cripple or Hinder, by ability, with the
  catalogue as source;
- `observed_this_round`: casts witnessed this round (killfeed weapon names,
  ult casts, assist icons once read), each linked to its event;
- `charges`: unknown, `null` with reason "enemy purchases are hidden"
  [domain:rounds/scoreboard-credit-snapshot], until an economy ledger
  supplies a bounded belief.

`off_angle_repeat` then reports the repeat, the kit present and what was
observed, and lets the player judge. Whether the player was blinded is
observable on his own screen for some abilities
[domain:abilities/phoenix-curveball-blind-screen]
[domain:abilities/skye-guiding-light-blind-screen]; no reader reads it.
Coaching must not profile named opponents across matches (research doc,
section 2); the kit is agent-level and per match.

### 2.3 Rotation timing against information

The question is: when the team knew something, how soon did the rotator
move? The cue list (section 1.2) gives each information event and its lag.
Information time is observation time: a death enters at its first killfeed
sample (2 Hz), a sighting at its first drawn frame. Two timing measures
follow:

- **Reaction lag**: from the earliest cue in the window to `t_exit_ms`.
- **Arrival margin**: `t_arrive_ms` against the plant, or against the
  destination site's first enemy contact.

Neither proves the cue caused the move; teammates' voice calls are
unobserved. The event stores both measures and the cue list; a review
window lets the player judge.

## 3. Fidelity

### 3.1 Callout precision, measured

Predictions C1-C3 were logged in `notes/predictions.jsonl` before measuring.
On a06f04a0059f (Ascent, 465 px widget, 22 callout points, 35,653 stored ally
observations), with nearest-point cells:

- Median spacing between callout points: [metric:coaching_callouts/ascent@a06f04a0059f#nn_px_median=53.6]
  px, [metric:coaching_callouts/ascent@a06f04a0059f#nn_m_median=16.6] m
  (C1 held).
- Ally observations whose second-nearest callout lies less than 7.6 px
  farther than the nearest (a gap under twice the reader's p95 error; the
  boundary lies at least half the gap away, about 3.8 px near the line
  joining the two callouts):
  [metric:coaching_callouts/ascent@a06f04a0059f#boundary_share_7p6px=0.2185]
  (C2 failed; predicted under 0.10). Among still allies (under 0.5 m/s
  between 2 Hz samples), [metric:coaching_callouts/ascent@a06f04a0059f#boundary_share_still_7p6px=0.2996],
  post hoc: allies hold angles at chokes between callouts.
- Debounced visits shorter than 0.5 s:
  [metric:coaching_callouts/ascent@a06f04a0059f#visits_under_half_s=0.3421]
  (C3 failed; predicted under 0.05). The instrument broke runs at gaps over
  100 ms, so detector gaps fragment visits; tolerating gaps up to 1 s gives
  [metric:coaching_callouts/ascent@a06f04a0059f#gap1s_visits_under_half_s=0.1397]
  (post hoc).
- Sampled at 2 Hz without a dead band, the cells change
  [metric:coaching_callouts/ascent@a06f04a0059f#cell_changes_2hz=405] times
  against [metric:coaching_callouts/ascent@a06f04a0059f#cell_changes_15hz_debounced=363]
  debounced 15 Hz changes. This compares 2 Hz without a dead band against
  15 Hz with short visits removed, so it cannot separate rate from boundary
  flicker; and 14% of visits under 0.5 s means 2 Hz can miss short visits.
  R2 (stage 1) tests 2 Hz against 15 Hz with the same dead band.

The surprise revises the plan: regions must be drawn polygons with a dead
band, and the 2 Hz test must run on those regions. The run is recorded in
`notes/metrics.jsonl` (tool `coaching_callouts`); one session, one map.

### 3.2 Rate and precision per feature

The player believes a check about twice a second at callout precision is
probably enough for a still teammate out of contact (the player, 2026-10-04
(chat)). The table states what each feature needs; stage 1 tests the 2 Hz
belief.

| Feature | Variable | Precision | Rate | Raise on (opportunity, never outcome) |
|---|---|---|---|---|
| Region presence, still ally out of contact | position | region with a 7.6 px dead band | 2 Hz | icons converging, an enemy icon or "?" near, a ping near, the spike phase reaching a site |
| Rotation exit and arrival | position | super-region | 2 Hz | none; timing error under 0.5 s suffices for lags in seconds |
| Team commit | positions of the living attackers | super-region | 1-2 Hz | plant |
| Lurk distance | positions | geodesic metres at region scale | 1 Hz | an enemy near the lurker |
| Hold and its footprint | position and facing | 7.6 px, facing within 15° | 2 Hz to detect stillness | an enemy near; the hold about to be peeked needs full rate (open question for the player) |
| Duplicate hold | two footprints | footprint overlap | per hold, not per frame | none |
| Cues | deaths, sightings, marks, spike, pings, ults | event time | as read: killfeed and roster at 2 Hz, minimap 15 Hz where red appears | none |
| Enemy kit | lineup, casts | per agent, per round | per match and per event | none |

### 3.3 Readers and their rates

| Reader | Today | For this module | Note |
|---|---|---|---|
| `ally_icon` / `round_entity` | 15 Hz, about 108 ms a frame on a06f04a0059f, contended (research doc, section 4) | 2 Hz change test per icon; 15 Hz near contact, stacks or surprise | the largest saving; [docs/ALLY_RATE.md](ALLY_RATE.md) found 5 Hz names as well |
| `team_vision` | 15 Hz, refits poses `ally_icon` stored | reads stored poses at the hold rate | duplicate work today |
| `minimap_objects` (enemies, marks) | 15 Hz on 3 sessions | 15 Hz where red appears in the slab, else off | gate on opportunity |
| `spike` glyph | a sampled grid | 2 Hz; add the planted state | |
| killfeed, roster | 2 Hz | unchanged | alive-count lag of 0.5 s costs little (research doc, section 5) |
| `ping` | per event | unchanged | widget frame; map through `widget_frame` before a region lookup |
| `ult_lines` | audio, GPU | unchanged | |

**Over-investment beside the gaps.** A 15 Hz pose fit on a still ally out of
contact spends work this module does not use; a 0.05 px compass refinement
spends precision no region test needs. The gaps are regions, plant site,
facing keyed by entity, and enemy coverage.

### 3.4 Running during play

The player allows analysis to run during play on the same PC and will sit
for a frame-time measurement; of the cost he said "I would probably give up
20% of FPS I guess" (the player, 2026-10-04 (chat)). The module itself is pure
stored-data work after each round; its readers are the cost. The plan:
measure the budget first (research doc, section 4, blocker 2: PresentMon,
five conditions in the Range), then run readers at the rates above under it.
Until that measurement, readers cache ROIs during play and read after.

## 4. Evaluation

1. **The player's rating, first.** Surfaced moments go to the player as
   review windows (`review.py` builds windows into source media with
   provenance) and his answers are stored through the `review-question`
   owner (`glance.py`). Each rating stores the moment's event ids and
   version. A fixed share of the windows are ordinary controls chosen without
   regard to outcome, so a rating of surfaced moments can be compared with a
   rating of unsurfaced ones.
2. **Proxies against Riot's records** (22 records, positions at kills,
   plants and defuses only, which over-sample fights):
   - region accuracy: each ally's super-region at Riot kill instants against
     the `region_presence` interval covering that instant;
   - lurk outcome: kills, deaths and round result by lurk, with Riot's kill
     list as truth for who killed whom and when;
   - trade timing: Riot kills give trades within 3 s and 5 s; a duplicate
     hold should show more double deaths within a trade window than a
     crossfire;
   - retake timing: Riot's `plantRoundTime`, `plantSite` and
     `defuseRoundTime` against the defenders' rotation arrivals;
   - plant site: Riot's `plantSite` scores the site the module infers.
3. **Win-probability swings**, once the round filter exists (stage 1 of the
   research roadmap): the change in estimated win probability around a
   rotation or lurk ranks moments, never judges them.
4. **Replays for enemy-dependent features.** In-client Replays show all ten
   players with no fog (research doc, section 4). The player will capture a
   current-patch Replay of a match he also captured (the player, 2026-10-04
   (chat)); a probe is running on another branch. Aligned by kills to the
   live capture, a Replay supplies continuous enemy positions: truth for
   enemy rotations, for where enemy disablers stood relative to an
   off-angle, and for the POV belief's calibration. Replays expire at the
   next patch and need the game client open; reticle never opens it.

### 4.1 Parsed replays as evaluation truth

Branch `replay-truth-20261004` is parsing saved replay files; nothing it
produces is merged, and what a parsed file holds is unverified here. If it
yields every player's position over time, rotations gain a truth for all ten
players, not only at Riot's kill instants:

- **Ally events** score against it: `region_presence` intervals, rotation
  exits and arrivals, and lurk distance, at every instant rather than at
  fights, which removes the kill-instant over-sampling of item 2.
- **Enemy events**, which the minimap censors, gain truth for the first
  time: an enemy rotation inferred between sightings checks against the
  enemy's actual path, and an off-angle checks against where the enemy's
  disablers stood.
- **Holds** score against teammates' true positions, so a missed
  `duplicate_hold` shows as a pair the parse places together and the module
  did not flag.

The parse is truth only, never a reader input. No reader, prior, owner or
coaching event reads it; it enters only the evaluation, stored apart and
stamped with its own version, so an evaluation never scores the module
against its own inputs. Positions in game units would carry into the baked
frame through `MapFrame`, as Riot's kill positions do. Each parsed
match must also have a live capture, aligned by kills, before it scores
anything.

## 5. Staged plan

Compute rules apply throughout: one heavy process, single-threaded, Below
Normal, stored data first, no decode without the player's go-ahead.

**Stage 0. Questions for the player.** Each definition's thresholds;
whether "the same angle" means position and facing or the covered entry;
whether a defender's off-site hold is a lurk; whether the hold about to be
peeked needs full rate; whether the capture holds team voice.

**Stage 1. Smallest prototype on stored data** (`prototypes/rotations.py`,
`wire: no` until an owner adopts it). Inputs: stored `round_entity`
observations, `rounds`, `death`, roster alive counts and the spike glyph for
the 21 matches that have them. The prototype reads the `round_entity` event
stream directly because projected lanes (section 1.2) exist for 3 sessions;
the module proper reads projected lanes once stage 3 projects all 21.
Super-regions come from valorant-api callout points carried by
`MapFrame`, as nearest-point cells within super-region, with the 7.6 px dead
band. Outputs to `analysis/coaching-rotations-0.1.0/`: `region_presence`,
`team_commit`, `rotation` and `lurk` candidates with cues, and 20 review
windows (15 surfaced, 5 controls) for the player. Log before measuring:

- R1: at Riot kill instants, the super-region of matched allies agrees
  with `region_presence` at 0.90 or more. Falsifier: under 0.90.
- R2: super-region changes sampled at 2 Hz with the dead band fall within
  10% of the debounced 15 Hz count, with a median time error of 0.5 s or
  less. Falsifier: either bound exceeded.
- R3: on attack rounds with four or more alive at the commit, an ally
  stands outside the commit's super-region in 20-60% of rounds. Falsifier:
  outside that range.
- R4: 70% or more of rotations have a stored cue within 10 s before exit.
  Falsifier: under 70%.
- R5: the player marks 8 or more of the 15 surfaced moments worth review,
  and more surfaced than control moments. Falsifier: fewer than 8, or
  controls rated as high.

Acceptance: one `metrics.record` run; one number reruns identically; the
player's ratings stored; `reticle doctor` clean. Evidence: R1-R5 with
match-bootstrap intervals where a rate is quoted.

**Stage 2. A region owner.** A baked `(map, profile)` region table: callout
and super-region polygons on the floor, partitioned along walls from the
occluders, with the dead band. Source: extracted game files if they hold
callout volumes (unchecked; extraction is allowed while the game is
closed), else the valorant-api points with the player's correction.
Acceptance: an ownership entry and tests; R1 rerun. Evidence: agreement
with Riot same or better than stage 1, and boundary share among still
allies under 0.10.

**Stage 3. The missing event fields.** The plant site into the plant event
(`round-bounds`, with the planted icon read by `spike-observation`); facing
keyed by entity in the entity pose; enemy lanes projected for the 21
matches. Acceptance: `reticle project` on the fixed handful. Evidence:
plant site against Riot `plantSite`; pose orientation non-null where
`team_vision` holds a facing.

**Stage 4. Holds and duplicates.** `hold` and `duplicate_hold` from stored
poses and the `viewcone` raycast. Acceptance: a labelled set of duplicate
and crossfire pairs from the player (`labelling-pass`). Evidence: agreement
with his labels; double deaths within a trade window by class.

**Stage 5. Enemy kit and off-angles.** `enemy_kit` per round and
`off_angle_repeat`; assist icons read when a reader exists. Acceptance and
evidence: the player's ratings; outcome by repeat.

**Stage 6. Replay truth.** Align a captured Replay to its live capture;
score enemy-dependent features. Needs an observer-HUD profile and
`clip_preflight`.

**Stage 7. Live footprint.** The PresentMon session, then readers at the
section 3.3 rates during play. Acceptance: the frame rate with readers
running falls by no more than the 20% of FPS the player offered.

## 6. What must not be shown during a match

Riot bars "drawing conclusions for you during gameplay" and asks that no
software harm the player's experience from pressing Play to logging off
(research doc, section 2, quoting Riot's Third Party Applications article,
updated 2025-02-10). The player wants some analysis after each round and
most after the game, with a match folded into the corpus only after the game
(the player, 2026-10-04 (chat)). Therefore:

- **Compute after each round, display after the match.** Post-round events
  are written to the store during the next buy phase; no window, overlay,
  sound, notification, tray badge or second-screen view reports them before
  the match ends. A viewer refuses to open a match whose end is not stored.
- **Fold into the corpus after the match.** Corpus statistics, priors and
  off-angle densities update only from completed matches; a running match
  never reads its own partial corpus contribution.
- **No live position, timer or ult alert.** The cue list includes ult casts
  and enemy sightings; shown live they would be "global ult alerts" or
  intelligence the game did not give, so they exist only in stored events.
- **No opponent profiles.** Kits are per agent and per match; no event
  names an enemy account or carries a history across matches.
- **Concurrent readers must prove no frame-time harm** (section 3.4) before
  they run during play.

## Open questions for the player

1. What makes a lurk for you: distance, a different site, timing against the
   commit, or all three? And what makes a rotation late?
2. Does "the same angle" mean the same position and facing, or the same
   entry watched from anywhere? Is a crossfire on one entry good?
3. What is an off-angle: a position few players use, or one close to the
   enemy's entry?
4. Is a defender holding off-site after a plant a lurk, or a separate
   question?
5. Does a still teammate holding an angle about to be peeked need more than
   2 Hz?
6. Does the capture record the team's voice chat?

## What this plan did not do

It built no prototype, owner or event. It measured callout precision on one
session and one map, with nearest-point cells; R1-R5 are not run. It did not
open the game files for callout volumes, view a Replay, read the assist
panel, project entity lanes for the other 18 matches, or measure frame time.
It did not revise the plant-credit domain fact or record the player's other
answers as domain facts.
