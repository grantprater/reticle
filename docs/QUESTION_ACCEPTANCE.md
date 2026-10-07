# Question acceptance: episodes from gated, variable-rate readers

Status: plan, proposed 2026-10-06 and revised the same day with the
player's answers (section 9) and the truth-side fidelity test of
[COACHING_QUESTIONS.md](COACHING_QUESTIONS.md); nothing here is built. Rules live in
[AGENTS.md](../AGENTS.md); commands in [WORKING_MAP.md](WORKING_MAP.md). It
rests on [ENTITY_STATE.md](ENTITY_STATE.md) (the slot model),
[EPISODES.md](EPISODES.md) (the questions), [REPLAY_LAYER.md](REPLAY_LAYER.md)
(the truth) and [EXTERNAL_GROUND_TRUTH.md](EXTERNAL_GROUND_TRUTH.md) (the use
policy). Predictions QA0-QA7 sit in the store's `notes/predictions.jsonl`
(task `question-acceptance-20261006`), registered before anything was built.

## Summary

The player set the direction on 2026-10-06: minimap readers become
opportunistic and variable-rate, coarse (region-level) most of the time and
at full rate and precision around duels and engagements. The gate opens on
engagement opportunity (enemy reveals within reach, gunfire and ability
audio, the player's own HUD damage, round phase, pings, chat spot messages)
and never on a kill. The timeline may change shape; the questions answered
may not lose the fidelity they need. The acceptance test answers the
coaching and summary questions from a vision timeline built on the gated
readers and compares the answers with the replay timeline's.

**The player's answers (2026-10-06)** revise the plan in four places:

- **Damage-only fights are in scope.** The player's combat report is their
  vision source; section 1 says what it gives per engagement and what it
  cannot.
- **The gate's primary input is an enemy drawn on the minimap.** The other
  inputs of section 5 are secondary. A death with no enemy drawn is itself
  an observation, stored on the death, never a gate input.
- **Enemy-side rotations, lurks and executes are beliefs.** They are
  reported with their standing and left out of the acceptance test.
- **The cost bound is of the order the player expects**: about a twentieth
  of today's 15 Hz slot reads, not 0.60 (QA5r, section 7).
  [COACHING_QUESTIONS.md](COACHING_QUESTIONS.md) names the questions that
  matter, measures their decision value on the stored data, and measures on
  truth alone what each loses under such a schedule.

1. **The vision timeline is the slot-state timeline.** ENTITY_STATE's slots
   own every player's state; the per-sample standing, age and precision this
   plan adds is each slot's belief; the gate and the variable rate are
   per-slot read scheduling; a stack's edge is assignment among the slots
   sharing a blob. Slot state is not built in `reticle/` (stage 1 and the
   causal binding exist as `prototypes/entity_state.py` and
   `prototypes/entity_binding.py`, allies only). No vision `Timeline`
   exists either. So ENTITY_STATE steps 1-3 head the build list.
2. **Each question declares the fidelity it needs**, and the timeline
   reports, per sample, whether it can meet it: `standing` (observed,
   carried, inferred, unknown), `age_ms` and `radius_cm`. Life comes apart
   from location. Episodes report the standing they rest on, and an
   attribute an unknown input decides is null with its reason.
3. **The comparison separates reader error from censoring** with a ladder
   of truth timelines: the replay (T0); the replay masked to what the
   capturing team could see (T1); T1 cut to the fields and rates any minimap
   reader can supply (T2). Vision arms run against T2 for reader error and
   against T0 end to end.
4. **The gate is scored on its own**: the share of true engagement onsets
   (the first damage or kill in the replay) at which it was already open,
   and its lead.

## 1. The questions, and what each consumes

Every question below is answered today by `episodes.derive_episodes` over a
`Timeline` (episodes-0.3.0), or is a coaching measure of
[COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md) and
[COACHING_ROTATIONS_LURKS.md](COACHING_ROTATIONS_LURKS.md) built on the same
state. The rate column is what the code samples; the fidelity column is
what the answer needs from a vision source.

| Question | Consumes (code) | Rate and window | Fidelity it needs | Vision source today |
|---|---|---|---|---|
| Round phases and result | `round_start`, `buy_end`, `plant`, `defuse`, `round_end`; `alive` at `t_end` + `END_SETTLE_MS` 100 ms | events | event time within 0.5 s; life per slot | `rounds`, `plant_graphic` (2 Hz), `round_outcome`, roster (2 Hz), death lane |
| Attacking team | living players' x, y over the buy phase's second half, 9 samples | 9 samples | team centroid to 10 m | allies' slots; enemies are invisible behind barriers (the timeline's `side` or `rounds.side_in_round` must serve) |
| Contact (sight) | x, y, z, yaw, pitch of both players; `sight()` | `SIGHT_HZ` 16; joins across `CONTACT_MERGE_MS` 500 ms | position within about 1.5 m, z on the right floor, yaw within the frustum's slack; both players located | allies' fits; enemies only while drawn [domain:minimap/vision-gate]; no pitch |
| Duel | damage and death acts, contacts; `classify_acts` needs eye and hit positions | acts; `DUEL_GAP_MS` 3 s; `SIGHT_AT_KILL_MS` 1 s | kill: killer, victim, time to 0.5 s; first seer: contact onset to 62.5 ms | death lane (killfeed 2 Hz); no damage events |
| Engagement | duels, contacts | `ENGAGE_JOIN_MS` 5 s | as duels | as duels |
| Trade | kills; `trader_saw_killer_at_t1` (sight at three 16 Hz samples); `trader_distance_m` at the nearest 16 Hz sample | `TRADE_WINDOW_MS` 5 s | kill times to 0.5 s; trader's and killer's positions at t1 for the two fields | death lane; slots |
| Execute (site attempt) | attackers' site-callout codes at `REGION_HZ` 4; contacts; acts; plant | `COMMIT_DWELL_MS` 2 s, `ATTEMPT_HOLD_MS` 5 s, `REGION_HOLD_MS` 1 s | region membership, which needs the radius smaller than the distance to the volume's edge, and z for the 3D volume | allies' slots when the capturing team attacks; revealed enemies when it defends |
| Retake, contested plant | plant position; living defenders' super-region at the plant; entry | 4 Hz | super-region; the absence of a defender on site, which unknown cannot give | spike lane (planted glyph), slots |
| Rotation | per-player super-region (Link volumes held by none) at 4 Hz | `ROTATION_MIN_DWELL_MS` 3 s | super-region | as executes |
| Lurk | attackers' super-regions around an attempt's peak | 4 Hz; `LURK_MIN_MS` 5 s | super-region; the lurker's identity | as executes |
| Trade spacing (decision value §1) | nearest living teammate's distance at each kill instant | kill instants | 1.5 m; teammates only | allies' slots |
| Reach: swing 2 m, trade 5 m, outnumbered deaths (§9 there) | both teams' cells against the walk and sight tables | kill instants | the cell (1 m) for both teams | allies; enemies censored (the decision context admits enemy features only as observed) |
| Rotation lag from a cue (rotations §2.3) | cue times (deaths, pings, sightings, plant); exit time | events; 2 Hz exits suffice | exit time within 0.5 s | death lane, pings, slots |
| Holds and duplicate holds (rotations §2.1) | position and facing of a still teammate | 2 Hz to detect stillness | 7.6 px, facing within 15 degrees | allies' slots, `team_vision` |

What follows from the table:

- **Damage-only fights are in scope; the combat report is their only
  vision source, and it covers the player alone** (player, 2026-10-06).
  On the development matches, kill-free engagements are
  [metric:question_acceptance_probe/truth_base_rates@9acf02f98283#engagements_no_kill_share=0.16]
  and [metric:question_acceptance_probe/truth_base_rates@c817691bcd15#engagements_no_kill_share=0.1474]
  of engagements, and kills end
  [metric:question_acceptance_probe/truth_base_rates@9acf02f98283#duels_kill=180] of
  [metric:question_acceptance_probe/truth_base_rates@9acf02f98283#duels=248] duels on
  9acf02f98283. The report gives, per enemy the player engaged in the
  round, damage both ways with head, body and leg hits and a KILLED flag
  [domain:combat_report/panel-layout], shown at his death and frozen until
  the round ends [domain:combat_report/appears-on-death]
  [domain:combat_report/frozen-after-death], and as a round summary at the
  round's end, also for a round he survived
  [domain:combat_report/round-summary]. It cannot give a bout's time (a row
  sums the round), the order of rows within a merged pair beyond newest
  first [domain:combat_report/rows-newest-first], any teammate's fights, or
  a row at all when the player hides it with N
  [domain:combat_report/toggle-into-next-buy-phase]. On the 11 replays
  holding the player, he fought
  [metric:coaching_questions/value/extra/combat_report@pooled#player_kill_free_bouts=104]
  of his team's
  [metric:coaching_questions/value/extra/combat_report@pooled#team_kill_free_bouts=577]
  kill-free bouts
  ([metric:coaching_questions/value/extra/combat_report@pooled#player_share_of_team_kill_free=0.1802]);
  [metric:coaching_questions/value/extra/combat_report@pooled#rows_merging_share=0.087]
  of his rows merge two or more bouts with one enemy. The rest of the
  team's damage-only fights stay outside every vision source: a field
  limit, not reader error, which T2 carries. The round-level damage
  balance is the answer the report serves
  ([COACHING_QUESTIONS.md](COACHING_QUESTIONS.md), section 2).
- **Enemy-side spatial questions are censored at the source.** An enemy is
  drawn only inside team vision, briefly after it
  [domain:minimap/vision-trailing-persistence], then as a "?"
  [domain:minimap/last-known-mark]. Rotations, lurks and executes of the
  enemy team, and the enemy's half of reach, are beliefs with a standing,
  reported and never accepted (player, 2026-10-06): on truth, the drawn
  enemy alone recovers
  [metric:coaching_questions/degrade/T1@pooled17#vs_T0.execute_E=0.3949] of
  enemy executes, [metric:coaching_questions/degrade/T1@pooled17#vs_T0.rotation_E=0.0164]
  of enemy rotations and
  [metric:coaching_questions/degrade/T1@pooled17#vs_T0.lurk_E=0.2383] of
  enemy lurks (strict agreement). The acceptance test (section 6) scores
  the capturing team's questions only; the enemy's reachable set and its
  habits ([COACHING_QUESTIONS.md](COACHING_QUESTIONS.md), section 4) are
  the belief's form.
- **First seer is biased by construction.** An enemy who sees an ally
  first is drawn only if another ally sees him. Of single-seer duels in the
  replay the enemy saw first in
  [metric:question_acceptance_probe/truth_base_rates@9acf02f98283#enemy_first_share_of_single=0.4773]
  (9acf02f98283) and
  [metric:question_acceptance_probe/truth_base_rates@c817691bcd15#enemy_first_share_of_single=0.6522]
  (c817691bcd15); the minimap can see few of them.
- **Region tests need z.** `map_regions` looks points up in 3D callout
  volumes; a minimap position has no z, so the slot's `level` (ENTITY_STATE
  §4) must supply it, or the sample's region is unknown.

## 2. The timeline's shape change

### Per sample

`Timeline.sample(t)` keeps every array it returns today and adds three, per
slot and time:

| Array | Values | Truth | Vision |
|---|---|---|---|
| `standing` | `observed` (a read at this time placed the slot), `carried` (no read now; the last read stands, its belief grown), `inferred` (a belief from another witness: a crowd's host, a reach region, a "?" mark, a death's X), `unknown` | `observed` | the slot's belief kind (section 4) |
| `age_ms` | t less the time of the read the sample rests on; NaN where unknown | 0 | from `frame_join.sampled_state` |
| `radius_cm` | the position's bound: the truth lies within it | 0 | `r_fit` for a fit, `r_fit + v_max * age` once carried unchecked, the region's for a region |

and splits life from location:

- `alive` comes from the slot's lifecycle alone (deaths, revives, rounds),
  never from whether a position was read. Today `ArrayTimeline` returns
  `alive & isfinite(x)`, so an unread position kills the slot for the round
  result and the retake gate. Even in truth, alive samples with no tick
  inside `max_gap_ms` are
  [metric:question_acceptance_probe/truth_alive_unlocated@9acf02f98283#alive_unlocated_share=0.00422]
  of living samples on 9acf02f98283 and
  [metric:question_acceptance_probe/truth_alive_unlocated@c817691bcd15#alive_unlocated_share=0.00068]
  on c817691bcd15.
- `located(question)` is `alive` and a position that meets the question's
  fidelity (below). Sight, regions and distances read `located`; life reads
  `alive`.
- z carries its own basis: `truth`; `floor` (the slot's `level` names one
  standable layer at x, y); `ambiguous` (several layers, z NaN). Pitch is
  NaN with reason `unread` from vision; the frustum's vertical test then
  passes rather than guesses.

### Per question

`PARAMS` gains `FIDELITY`, one entry per consumer of positions, each a
standing set, a `max_age_ms` and a `max_radius_cm`. A sample outside its
question's entry is unknown to that question only.

| Question | Standings admitted | `max_age_ms` | `max_radius_cm` |
|---|---|---|---|
| sight (contacts, first seer, `trader_saw_killer_at_t1`) | observed, carried | 250 | 150 |
| region (executes, retakes, rotations, lurks) | observed, carried, inferred | 2000 | the sample's distance to its volume's edge, so a region read is never ambiguous |
| distance (`trader_distance_m`, spacing, `spread_m`) | observed, carried | 500 | 300 |
| attack team | observed, carried | 1000 | 1000 |

The values are defaults stated before any vision run, from the questions'
own windows (the sight grid's 62.5 ms, `REGION_HOLD_MS`, the 5 m trade
reach); none is fitted to an outcome. Truth passes every entry.

### What changes in `episodes.py`

The minimal change, as episodes-0.4.0:

1. `ArrayTimeline` takes optional per-track `standing`, `t_obs` and
   `radius_cm` arrays; without them every sample is observed, age 0, radius
   0, so a truth timeline builds as before. Inside `max_gap_ms` it still
   interpolates between two observed samples. Across a wider gap it asks
   `frame_join.sampled_state` (branch `frame-join-20261006`; the owner of
   "the latest read at t, its age, and `stale` past a max age") instead of
   returning NaN, and reports the carried sample with its age; past the
   question's `max_age_ms` the state is null with reason `stale`.
2. `sample(t, fidelity=None)` returns the new arrays and, given a fidelity
   entry, the `located` mask. `sight`, `_region_series`, `_trades` and
   `attack_teams` pass their entry; `_round_result` and the retake's living
   defenders read `alive`.
3. `_region_series` keeps three codes apart: a volume, `-1` outside every
   volume (holds the last code, as now) and `-3` unknown (holds nothing).
   A retake, contested plant, execute close or lurk that an unknown sample
   would decide is `undetermined`, with the slots it lacked.
4. `attack_teams` decides from one team's spawn lean when the other
   team's is unknown (enemies behind their barrier are never drawn), and
   takes the timeline's `side` first, as now; a vision timeline sets it on
   `round_start` from `rounds.infer_player_side`.
5. Every episode gains `standing`: the shares of its participants' samples
   over its interval that were observed, carried, inferred and unknown under
   its question's entry, and `rests_on_unknown` (the count). EPISODES §7
   asks for exactly this field.
6. Vision episodes write to `<store>/analysis/episodes/vision/<session>.jsonl`;
   an experiment's arms write under `--out`.

QA0 holds the change to its word: truth rebuilt through 0.4.0 equals the
stored 0.3.0 rows except where a truth slot is alive and unlocated.

### The frame-join owner

The comparison joins streams that sample at different rates, so it asks
`frame_join` and restates none of its rules:

- **Grid streams** (the 15 Hz `ally_icon` frames, the crop cache, the replay
  layer's `frames` table at the stored frames): `grid_join`, nearest frame
  within half a sample, refused below `MIN_JOIN_RATE` 0.99.
- **Sampled streams** (a gated slot's reads, the 2 Hz HUD, the killfeed's
  first-seen times, the plant graphic, pings): `sampled_state` with the
  question's `max_age_ms`; a carried read declares `rests_on`.

## 3. The vision timeline is the slot timeline

`slot_state` (ENTITY_STATE §4) writes one struct-of-arrays per session; its
`entity_slot` lane is what consumers read (`EntityEvents.slots_at`). A thin
adapter, `from_slot_state(session)`, turns the lane into a `Timeline` with
`source = vision`:

- slots: the ten `<session>:<team>:slot:<k>` keys; `team` is `ally` or
  `enemy`, never a side;
- per slot: x, y from the belief point through the world frame (the inverse
  of `replay_source.MapFrame`, baked with the geometry as ENTITY_STATE's
  stage 1 requires); z from `level`; yaw from `facing`; standing, age and
  radius from the belief (section 4);
- events: deaths and revives from the death lane (killer and victim by
  slot, through the arbiter), the plant from the spike lane and
  `plant_graphic`, phases from `rounds`, the result from `round_outcome`;
  no damage events, so `first_hitter` stays null with `no_damage_events`.

Truth entities are the replay layer's `entities`: the players and their
ability children (AGENTS.md, "Replay truth covers every entity"). Scoring
maps a vision slot to the truth player of its agent and team (evaluation
only, as ENTITY_STATE §8 does); every other find maps to the truth entity
under it, of any class, through the class-aware outcomes of section 6. T1
masks each child by its class's drawn-ness fact in `domain/abilities.toml`.
A slot the arbiter left unnamed scores under `slot_unnamed`.
Until enemy slots exist (ENTITY_STATE step 5), enemy samples come from the
enemy lane as observed fits only, with the "?" as `inferred` and no reach
region.

## 4. Where ENTITY_STATE changes for variable-rate beliefs

ENTITY_STATE assumes one fit attempt per slot per 15 Hz frame. Under a
schedule most frames read no slot, and the design changes in seven places:

1. **§4 arrays.** The frame axis stays the crop cache's 15 Hz grid (the
   cache is captured at that rate during play); each slot-frame gains `read`
   (`full`, `local`, `cheap_check`, `skipped`, `audit`), `t_obs` (the time
   of the read the belief rests on) and `rate` (`coarse`, `fine`). Standing
   follows: a `fit` or `held` read this frame is observed; `held` or `fit`
   from an earlier frame is carried; `crowd`, `reach`, `last_known` and
   `spawn` are inferred; `unanchored` is unknown.
2. **§2 `held`.** Today `held` means the cheap check found the icon's
   pixels unchanged. A slot the schedule skips was checked by nothing, so
   its belief must grow: `held` only on frames whose cheap check ran and
   held; otherwise `reach` from the last fit, `R = r_fit + v_max * age`
   [domain:game_data/character-movement-speeds]. The radius is a bound; the
   scorers measure it (QA7).
3. **A coarse read.** The schedule's coarse mode reads a slot to region
   precision: a cheap check at the held pose (the teal change of
   `prototypes/ally_rate.py`) that either holds (`held`) or forces a full
   read. A new belief kind is not needed; a coarse read that holds is
   `held` with its check's radius.
4. **Negative evidence.** §2 already suspends it while the widget is
   absent or a menu is open. A frame the schedule did not read for a slot
   gives no look either: exclusions come only from frames read in full.
5. **The assignment (§2, stage 2a).** With sparse reads the motion gate
   between a slot's last fit and a new one grows with age, ambiguity rises,
   and the binding margin must be scored by age stratum. A blob's mass
   change, a crowd entry or a crowd split is an opportunity that forces a
   full read of every slot sharing the blob: the stack edge is decided
   among those slots, never by carrying.
6. **The schedule is stored.** Each frame's per-slot decision, with the
   inputs that opened or closed the gate, is its own stream, so every
   carried sample names why it was not read. Audit reads at a cadence fixed
   in advance are stored apart and never update the gate (AGENTS.md,
   "Continue the prior").
7. **§6 and step 4.** Prior-first reading (step 4) and the gate are one
   scheduler: the belief predicts where to look, the gate decides whether
   to look. The 2 Hz `estimate` rows of the ally lane do not suffice for
   sight at 16 Hz; the timeline reads the lane's npz sidecar.

## 5. The gate

**The primary input is an enemy drawn on the minimap** (player,
2026-10-06); the rows below it are secondary and are added only where they
lift the open-at-onset share. On truth (17 replays), a gate open while any
enemy is drawn is open at
[metric:coaching_questions/value/extra/gate_onset@pooled#open_0=0.9211]
of [metric:coaching_questions/value/extra/gate_onset@pooled#n=3560]
engagement onsets, with a median lead of
[metric:coaching_questions/value/extra/gate_onset@pooled#lead_ms_p50=672.5] ms;
one open only for the slots that see a drawn enemy or stand within 20 m of
one is open at
[metric:coaching_questions/value/extra/gate_onset@pooled#local_open=0.859];
[metric:coaching_questions/value/extra/gate_onset@pooled#miss_enemy_first=0.669]
of its misses are enemy-first acts no input of this table could see sooner.

**A death with no enemy drawn is an observation**, stored on the death as
`blind` (no living teammate saw the killer in the 2 s before it) with its
standing, and never a gate input: it is an outcome. On the replays
[metric:coaching_questions/value/replays/blind_death@pooled#n_a1=259] of
[metric:coaching_questions/value/replays/blind_death@pooled#n=2571]
deaths are blind; they are traded at
[metric:coaching_questions/value/replays/blind_death@pooled#traded_a1=0.1236]
against [metric:coaching_questions/value/replays/blind_death@pooled#traded_a0=0.1912],
and their round-win difference
([metric:coaching_questions/value/replays/blind_death@pooled#diff=-0.0424],
interval [metric:coaching_questions/value/replays/blind_death@pooled#ci_lo=-0.0805]
to [metric:coaching_questions/value/replays/blind_death@pooled#ci_hi=0.0165])
spans zero.

A slot runs `fine` (read every frame, full fit) while any opportunity input
holds near it, and `coarse` otherwise. Fidelity also schedules: a slot is
read whenever its carried radius would pass the tightest `max_radius_cm` a
live question needs at its position, so precision, not an outcome, sets the
rate when no opportunity holds.

| Input | Witness | Stored today | Cost |
|---|---|---|---|
| Enemy drawn within reach of a living ally | red in the minimap slab within a distance the sightline table gives (any ally cell with a sightline to the red) | crop cache; `minimap_objects` reads it at 15 Hz | a red-pixel test on the crop, no fit; to measure |
| A "?" last-known mark near an ally | the same red test | as above | same pass |
| A ping near an ally | `ping` events | yes | none |
| The player's own HUD damage or firing | HP or shield falling, magazine falling | `hud` at 2 Hz | none |
| Round phase | barrier drop; the plant | `rounds`, `plant_graphic` | none |
| A teammate's teal change | `ally_rate`'s cue | crop cache | 0.12-0.18 ms per frame (ally-rate outcome R6) |
| Gunfire and ability audio | onsets in the retained audio | no gunfire reader; `ability_audio` for the player's kit | a reader to build |
| Chat spot messages [domain:hud/chat-broadcasts-callouts] | the chat line's text | no reader | a reader to build |

**Excluded inputs.** A killfeed death, a round's result and anything the
death owner adjudicates are outcomes. `ally-rate-0.1.0`'s death cue reads
every teammate for 1.5 s after a death; arm (b) therefore runs its
`nodeath` variant. The outcome row showed the cue gained nothing (ally-rate
R3).

## 6. The comparison

### The ladder

| Timeline | Built from | What it isolates |
|---|---|---|
| **T0** truth | `episodes.from_replay_layer` | the answer |
| **T1** masked | T0 with every enemy position, yaw and pitch unknown while no living capturing-team player sees him (`episodes.sight` at 16 Hz), held for a persistence P after the last sight; events kept | inherent censoring: T1 against T0 |
| **T2** field-limited | T1 sampled where and as the readers sample: positions at the stored minimap frames (the layer's `frames` table, at the minimap lag `frames_to_replay` applies), z from the floor layer, no pitch, no damage events, deaths at the killfeed's first 2 Hz sample at or after the kill, the plant at `plant_graphic`'s | what an ideal minimap reader could give: T2 against T1 |
| **T2g** ideal gated | T2 at the reads a gated schedule made | the schedule's sampling loss, apart from reading error |
| **V15** arm (a) | `from_slot_state` on today's 15 Hz stored streams | reader error: V15 against T2 |
| **Vrate** arm (b) | slot state under `ally_rate`'s `nodeath` schedule (2 Hz base, tau 0.10), carried samples standing `carried` | the rate cut alone |
| **Vgate** arm (c) | slot state under the opportunity gate of section 5 | the proposal |

P is unmeasured [domain:minimap/vision-trailing-persistence]; T1 runs at
0, 1 and 2 s, and 1 s heads the predictions. T1 counts reveals by sight
alone; reveal abilities show more enemies, which only a vision arm will
have, and each such sample is listed. Arms (b) and (c) start as
simulations over stored 15 Hz rows: a read at a frame returns that frame's
stored fit, a skipped frame carries. The real gated reader (step B12)
replaces the simulation and is rescored.

Every arm runs through the same `derive_episodes` (episodes-0.4.0) with the
same `PARAMS` and `FIDELITY`, on the same rounds.

### Matching, per kind

A truth episode and a vision episode match one to one, on the capture
clock (the layer's `a_ms`), by the rule below; ties go to the larger
interval overlap.

| Kind | Match rule | Attributes compared |
|---|---|---|
| phase | round number and kind | each boundary's time error; `end_reason`, `winner`, `attack_team` |
| duel | killed: (killer, victim) and kill times within 1.5 s (`replay_source.MATCH_TOL_MS`); not killed: the pair and overlapping intervals | outcome, `first_seer`, `mutual`, `sight_at_kill`, `opening`, `kill_class` (gun or ability; the killfeed weapon), `wallbang` (the killfeed's mark) |
| engagement | kill sets with Jaccard at least 0.5; kill-free ones by shared combatants and overlap | winner, kills and deaths per team, survivors |
| trade | (traded, killer, trader) and t1 within 1.5 s | lag, `same_engagement`, `trader_saw_killer_at_t1`, `trader_distance_m` |
| execute | round, site and overlapping intervals | result, committed count, trigger, `join_ms`, the committed slots |
| retake, contested plant | round | result, `entry_ms`, defenders on site |
| rotation | rotator, round, from and to site, overlap | start and end times, duration |
| lurk | lurker, round, overlap | start and end, `first_event`, `with_committed_teammate` |
| contact | the pair and overlap | onset, `first_seer`, `mutual` |
| find | the live truth entity of any class within the gate at the find's frame (`truth_under`, planned) | right entity, other entity (class), nothing there, coverage gap (unmapped actor, by class) |

**Metrics.** Per kind and arm: precision, recall and F1 with Wilson
intervals (`metrics.wilson`); start and end error, median and p90, on
matched episodes; agreement on each attribute; and the miss's class, in
this order: `censored` (T1 lacks it), `field` (T2 lacks it), `schedule`
(T2g lacks it), `reader` (the arm lacks it, T2g has it). A vision episode no
truth episode matches is a `phantom` with its standing. Strata: the
capturing team's side; standing of the episode (observed share above and
below 0.8); age at the decisive sample. Coaching measures compare per kill
instant: nearest living teammate's distance (absolute error), the 5 m trade
reach as a boolean, swing and trade counts per team.

**Cost.** Minimap reading time per drawn frame (`ally_icon`,
`minimap_objects`, the gate's cue), priced for a simulation by each stage's
profiled cycles as `ally_rate.py cpu` does, and measured by `reticle usage`
once a gated reader runs. For scale: the stored ally reader spent
[metric:scan_usage/ally_icon/cache/serial/cv12@9acf02f98283~e5c119ba#feed_s_ally_icon=1028.085] s
over [metric:scan_usage/ally_icon/cache/serial/cv12@9acf02f98283~e5c119ba#frames=20620]
frames on 9acf02f98283. The gate's duty cycle (the share of live-phase
slot-frames in `fine`) is reported beside it.

**The cost target** (player, 2026-10-06): real time with no noticeable
cost; the stretch goal is under 1 ms average processing per captured
frame. The basis is the captured frame: the development captures run at
[metric:coaching_questions/cost/today@9acf02f98283#capture_fps=60.0] fps,
so today's 15 Hz reading touches one captured frame in four. Today the two
15 Hz minimap readers cost
[metric:coaching_questions/cost/today@9acf02f98283#cv4.per_read_ms=29.744] ms
per read frame on the least contended stored pass (`ally_icon`
[metric:coaching_questions/cost/today@9acf02f98283#cv4.ally_icon_ms_per_read=26.421] ms,
`minimap` [metric:coaching_questions/cost/today@9acf02f98283#minimap_ms_per_read=3.322] ms),
that is
[metric:coaching_questions/cost/today@9acf02f98283#cv4.per_captured_ms=7.436] ms
per captured frame, and
[metric:coaching_questions/cost/today@9acf02f98283#cv12.per_captured_ms=14.243] ms
on a contended one. A schedule's implied cost is that figure times its slot
share; COACHING_QUESTIONS.md section 6 gives it per arm. The 1 ms target
therefore needs a slot share of at most about 0.13 (1 over 7.4) of today's, before
the gate's own per-frame cue, which must stay a red-pixel test.

### The gate's own metric

For every T0 engagement, its **onset** is its earliest act (damage or kill)
in the replay; every engagement has a capturing-team combatant. On the
capture clock through the layer's frame mapping:

- **Open at onset**: the share of onsets at which some capturing-team
  combatant's slot was `fine`; again at onset less 250 ms and 500 ms.
- **Lead**: onset less the start of the `fine` run that holds it; median
  and p10.
- **Miss classes**: no ally saw the enemy before the act (enemy first, a
  wallbang, an ability), the enemy unrevealed, or a gate input unread.
- **Waste**: `fine` slot-time with no T0 contact or act within 3 s.

The same is reported for contact onsets (the first sight of a pair), since
the first seer needs the gate open before the first damage.

### Sets

Development: 9acf02f98283 (b03fecd3), c817691bcd15 (60c7f1e0) and
d3dcfb182ab1 (16a475cb). d3dcfb182ab1's layer has no capture clock and no
self until `replay_layer` names the player without Riot (BACKLOG, "Ingest
wiring"); it joins when that lands, and if it never does development is the
two Ascent matches. Held out: cea8ecbc94ab (bd7efa02), which no design
reads, scored once per version at the end. Its killfeed prints the account
name and its shooting-error readout covers killfeed slots 3 and 4, so its
death lane is impaired; its score reports the kill-anchored kinds apart.

## 7. Predictions

Registered as task `question-acceptance-20261006`, rows QA0-QA7, before any
part was built. Pooled over development unless stated; P = 1 s. Each row
states its falsifier.

| Ref | Comparison | Prediction |
|---|---|---|
| QA0 | T0 through 0.4.0 against stored 0.3.0 | equal on every episode, act and contact except those resting on an alive, unlocated truth sample; those at most 1% of episodes per match, each listed |
| QA1 | T1 against T0 (censoring) | phases, trades and kill duels exact; enemy-first share of single-seer duels at most half T0's; contact recall 0.65-0.90, precision at least 0.97; capturing-team rotations and lurks recall at least 0.98, enemy rotations 0.10-0.50, enemy lurks at most 0.40; executes recall at least 0.98 when the capturing team attacks, 0.50-0.90 when it defends; no determined retake or contested plant label differs from T0's |
| QA2 | T2 against T1 (fields and rates) | duel recall 0.66-0.78 per match; engagement recall 0.78-0.92, at least 0.7 of the misses kill-free; trades precision and recall at least 0.95; plant time error p90 at most 600 ms; end reason and winner at least 0.98 |
| QA3 | V15 against T2 (reader error) | trades F1 0.80-0.95; kill duels recall 0.88-0.98, precision 0.90-0.99; phase boundaries within 1 s on at least 0.95 of rounds, result at least 0.95; attack team at least 0.95; capturing-team rotations F1 0.55-0.85, lurks F1 0.50-0.85 with the lurker right on at least 0.85 of matches; attack-round executes recall 0.70-0.92, committed count exact on 0.45-0.75; ally-enemy contacts recall 0.40-0.75, precision 0.55-0.85; teammate distance at capturing-team deaths median error at most 1.5 m, 5 m reach agreeing on at least 0.85; minimap reading at least 40 ms per drawn frame |
| QA4 | Vrate against V15 | every kind but contacts within 0.03 F1 of V15; contacts lose 0.02-0.10 F1, failing the tolerance; ally reading cost at most 0.70 of V15's |
| QA5 | Vgate against V15 (the tolerance) | every kind's F1 at least V15's less 0.02, contacts and first seer less 0.03; timing error p90 no more than 250 ms worse; minimap reading cost at most 0.60 of V15's per drawn frame; duty cycle at most 0.45 |
| QA6 | the gate on T0 onsets | open at onset on at least 0.85 of engagement onsets, at onset less 250 ms on at least 0.75; median lead at least 400 ms; at least half the misses have no ally sight before the act |
| QA7 | Vgate standing | carried samples hold the truth within `radius_cm` on 0.93-0.99; coarse reads that held hold it on at least 0.95 |

QA5 is the acceptance: a gated reader passes when it meets QA5 on
development and then once on the held-out match.

**Revisions of 2026-10-06** (the player's answers), appended as `kind:
"revision"` rows that point at the originals, which stand unedited:

| Ref | Revises | Prediction |
|---|---|---|
| QA5r | QA5 | Vgate against V15 on the capturing team's questions only (enemy-side kinds reported as beliefs, never scored): opening first seer, the 5 m spacing boolean, first-sight support, trades, duels, contacts and the execute committed band agree on at least 0.95 of instances (strict for instants, contacts and trades; F1 for executes, rotations and lurks); slot-read share at most 0.06 of V15's 15 Hz reads; minimap reading at most 1 ms average per captured 60 Hz frame on an uncontended pass (`reticle usage`), the gate's cue included |
| QA6r | QA6 | the drawn-enemy gate alone opens at onset on 0.85-0.92 of engagement onsets (the truth ideal is 0.921, the ceiling) and its median lead is at least 400 ms; every death with no enemy drawn in the 2 s before it carries `blind` with its standing, and no gate input reads a death |

The truth-side test behind QA5r (COACHING_QUESTIONS.md, section 3): the
live-phase local gate at 0.5 Hz base (`Lp0.5-250w5`) reads
[metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#share=0.0484] of
today's slot reads and agrees with T1 on at least 0.95 of the sight
questions; strict execute and rotation timing fall below it.

**Revision of 2026-10-07** (the player): agreement between two noisy
timelines measures consistency, not accuracy, so QA5r2 scores each
scheduled arm against T1 and compares it with the 15 Hz real-read arm on
the same instances. The bar was set after the pilot
`prototypes/real_reader_schedule.py` (task `real-reader-schedule-20261007`)
had run, so its verdicts on those arms are post hoc. Under it, `Vgate-d`
(the real gate, each read moved off frames whose widget is not drawn) reads
[metric:real_reader_schedule/qa5r2/Vgate-d@dev2#share=0.0409] of the 15 Hz
slot reads. It holds contacts within the bar
([metric:real_reader_schedule/qa5r2/Vgate-d@dev2#contact_C.loss=-0.0072])
but loses
[metric:real_reader_schedule/qa5r2/Vgate-d@dev2#first_sight_support.loss=-0.0833]
on first-sight support and
[metric:real_reader_schedule/qa5r2/Vgate-d@dev2#opening_first_seer.loss=-0.0625]
on the opening first seer. No arm yet passes.
Under QA5r3, the interval rule the player chose after seeing these numbers,
the real-gate `Vgate` passes post hoc at a read share of
[metric:real_reader_schedule/qa5r3/Vgate@dev2#share=0.0283], its
spacing-at-death loss of
[metric:real_reader_schedule/qa5r3/Vgate@dev2#spacing_death.loss=-0.0807]
having an interval that ends at
[metric:real_reader_schedule/qa5r3/Vgate@dev2#spacing_death.ci_hi=-0.0305].
The reach questions that replace radius spacing, on the enemy belief's walk
model (`join_death`, teammates who can reach a cell seeing the killer within
5 m; `join_choice`, whether such a teammate joined within 5 s; and
`spacing_region`, the nearest teammate's callout region against the
victim's), lose
[metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#join_death.loss=-0.0062],
[metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#join_choice.loss=-0.0471]
and
[metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#spacing_region.loss=-0.0497]
under `Vgate` against
[metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#spacing_death.loss=-0.0807]
for spacing at death.
The enemy lane's misses against T1 are mostly T1 errors, not reader misses
(`prototypes/enemy_lane_check.py`, classed by eye): on c817691bcd15 the
stored icons' hit rate rises from
[metric:t1_draw_rule/lane/T1@c817691bcd15#hit_rate=0.3021] under T1 to
[metric:t1_draw_rule/lane/T1d@c817691bcd15#hit_rate=0.5626] under T1d
(`prototypes/t1_draw_rule.py`: measured persistence, both teams' smokes, no
dead enemies), and T1d supersedes T1's draw rule for later scoring.

| Ref | Revises | Prediction |
|---|---|---|
| QA5r2 | QA5r | per sight question, the arm's accuracy against T1 is at most 0.03 below the 15 Hz real-read arm's on the same instances (the loss from paired flips, point estimate; a 95% paired bootstrap interval over rounds reported beside); read share at most 0.06 of the stored 15 Hz reads |
| QA5r3 | QA5r2 | the same accuracy, loss and interval; a sight question fails only when the interval's upper end lies below -0.05; the point estimate is reported beside; read share at most 0.06 of the stored 15 Hz reads |

## 8. Build list, in order

Costs are agent sessions (one contained implementation each) and compute,
single-threaded at idle priority, one heavy process at a time. No step
decodes video; the crop caches and stored rows suffice until B12.

| Step | Work | Acceptance | Cost |
|---|---|---|---|
| B1 | **ENTITY_STATE step 1**: `reticle/slot_state.py` from stored rows (`ally_icon`, `round_entity`, deaths, lineup, roster, rounds), promoted from `entity_state.py` with the causal binding; the world frame baked into the geometry; section 4's fields (`read`, `t_obs`, `rate`) written from the start, all `full` at 15 Hz | ENTITY_STATE §8 on the same rows: Riot kill instants on its held-out six reproduce the prototype (causal calibration [metric:entity_state/riot_pool@heldout6es_causal#calibration=0.9689]); the replay scorer on the three development matches against the stored `round_entity` recall on the same frames (W1 baseline row) | 2 sessions; minutes per match from storage |
| B2 | **ENTITY_STATE step 2**: the assignment in `adjudication.identity`; deaths close slots; the `entity_slot` lane and `slots_at` | `reticle project SESSION` validated by `entity_contract`; binding share at least the stored pieces' on unambiguous pairs | 2-3 sessions; per-session reruns from storage on nine sessions |
| B3 | **ENTITY_STATE step 3**: `round_entity` as a view over slots, the id migration of identity claims and death bindings | the Riot scorer's counts reproduce from the view within the pairing's ties | 1-2 sessions; `lifetimes` from storage on the nine; the corpus rerun waits for replay training |
| B4 | Enemy samples from the enemy lane into the enemy slots, observed only, the "?" inferred | the replay scorer's enemy phantoms unchanged | half a session |
| B5 | episodes-0.4.0: section 2's shape change | QA0 on development; the episodes tests | 1 session; truth episodes for three matches under `--out`, minutes each (to time) |
| B6 | `from_slot_state` and the events adapter, on `frame_join` once merged | a vision episodes file per development session; every unread attribute null with its reason | 1 session; seconds per match |
| B7 | `prototypes/question_acceptance.py`: T1, T2, T2g, matching, metrics, recording; QA1-QA3 | QA1-QA3 marked on development | 1-2 sessions; five derivations per match, under an hour in all |
| B8 | `replay_layer` names the player without Riot (replay-truth 0.3.0's pick), so d3dcfb182ab1 has a capture clock and sides | `reticle replay-layer d3dcfb182ab1` writes `a_ms` and `side_rel` | half a session; a layer rebuild |
| B9 | Arm (b): `ally_rate`'s `nodeath` schedule into slot state as carried samples; QA4 | QA4 marked | 1 session; one crop-cache pass per match for the cue |
| B10 | The gate (section 5) from stored inputs plus a red-pixel cue on the crop cache; the per-slot schedule stored; arm (c) simulated; QA5-QA7 | QA5-QA7 marked on development | 2 sessions; one crop-cache pass per match |
| B11 | Cost: per-stage profiles priced per decision, then `reticle usage` on the real readers | ms per drawn frame with CPU and wall apart | half a session; the profiled windows only |
| B12 | **ENTITY_STATE step 4** under the scheduler: `AllyIconReader` prior-first from slot beliefs, `minimap_objects` gated on red; rescore arm (c); then the held-out match once | QA5 on the real reader, development then held out | 3 or more sessions; one full read per development match from its crop cache, the heaviest step (about 50 ms per frame at 15 Hz on 9acf02f98283, section 6) |
| B13 | Later gate inputs: a gunfire-onset reader on the retained audio; a chat spot-message reader | each with its own predictions, then QA6 rerun | 2 sessions each |
| B14 | ENTITY_STATE step 5, enemy slots, replacing B4 | enemy containment at Riot kill instants; QA1-QA3 rerun | per ENTITY_STATE |

B1-B3 come first because every arm reads slots, and their own scores
measure the slot model against today's numbers before any rate changes.

## 9. Questions for the player, answered

The player answered all three on 2026-10-06:

1. **Damage-only fights**: in scope; the combat report carries damage both
   ways (section 1 says what it gives).
2. **Enemy-side questions**: beliefs with their standing, outside the
   acceptance (section 1). The gate's primary input is an enemy drawn, and
   a death with no enemy drawn is an observation (section 5).
3. **The margin**: savings of 95% or more over today's 15 Hz reading at
   barely any loss on the questions that matter, and real time with no
   noticeable cost, under 1 ms average processing per captured frame as
   the stretch goal. QA5r and the cost target (section 7) restate QA5 so;
   [COACHING_QUESTIONS.md](COACHING_QUESTIONS.md) names the questions and
   tests the claim on truth.

The player answered the catalogue's two on 2026-10-06:

4. **Execute and rotation timing**: coaching needs only that a team execute
   or rotation happened and how many went, not its start within 1 s; the
   live-phase local gate at 0.5 Hz base (`Lp0.5-250w5`) is the schedule to
   build.
5. **Whose fights**: coaching is about the player, with teammates as
   context. An engagement the player is not in is coached only through the
   player's position relative to it, role in the round and opportunity
   cost; attention ranks the player's own engagement first.

## 10. What this plan does not do

- It builds nothing: no slot state, no shape change, no harness, no gate.
- It reads no held-out truth; it read stored development truth episodes
  for the base rates cited above and ran two stored-data checks, recorded
  as `question_acceptance_probe` in `notes/metrics.jsonl`.
- It models neither reveal abilities nor smokes in T1; T1 counts reveals by
  sight, and smokes are absent from sight as in EPISODES §6.
- It measures no gate input's cost; the red-pixel cue's cost is B10's.
- It fixes no player parameter; EPISODES §5's defaults stand.
- Its truth-side fidelity test (COACHING_QUESTIONS.md) simulates schedules
  on truth only; it models no reader error, no minimap lag and no field
  limit (T2), which remain B7's and B10's.
- It reads the combat report nowhere yet; the report's reader exists
  (`reticle combat-report`), and its answers join the timeline in B6.
