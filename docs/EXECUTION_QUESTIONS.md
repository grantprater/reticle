# Execution questions: what to ask, whether truth answers it, whether it matters, and what a capture can see

Status: findings, 2026-10-07. Rules live in [AGENTS.md](../AGENTS.md);
commands in [WORKING_MAP.md](WORKING_MAP.md). This answers the player's
direction of 2026-10-07: coaching splits into decision and execution; the
catalogue of [COACHING_QUESTIONS.md](COACHING_QUESTIONS.md) is mostly
decisions read from the minimap; define the execution (mechanics) questions,
and measure how well and how cheaply the pipeline can answer them. The code
is `prototypes/execution_questions.py` (execution-questions-0.1.0).
Predictions EQ0-EQ10 sit in the store's `notes/predictions.jsonl` (task
`execution-questions-20261007`), registered before each run. Nothing here
reads the held-out match bd7efa02 (capture cea8ecbc94ab), decodes video,
writes a stored stream or fits a threshold on an evaluation set; nothing is
wired.

## Conclusion

- **The replay answers almost every execution question exactly.** Beyond
  the 128 Hz view and position stream, it records every shot fired, hit or
  miss [domain:replay/vrf-shots-from-magazine], each hit's body region and
  zoom [domain:replay/vrf-damage-hit-region], at the server tick, with view
  angles in 0.0055 degree steps [domain:replay/vrf-view-angle-resolution].
  Adjustment and reaction times are measurable to one 8 ms tick. Blinds are
  decoded on only two replays [domain:replay/vrf-blinds-on-recent-builds],
  so utility response has no truth yet.
- **Three execution quantities carry duel value; reaction speed does not.**
  In [metric:execution_questions/value/meta@pooled17#duels=2445] kill duels
  on 17 replays: the participant whose crosshair sits closer to the enemy's
  head when the line of sight opens wins
  [metric:execution_questions/value/placement@pooled17#paired.share=0.6135]
  of them; a first shot that hits lifts the win share by
  [metric:execution_questions/value/first_bullet@pooled17#hit.diff=0.3087]
  (a head hit by [metric:execution_questions/value/first_bullet@pooled17#head.diff=0.4115]);
  shooting still rather than moving lifts it by
  [metric:execution_questions/value/speed_at_shot@pooled17#still_vs_moving.diff=0.0745].
  Shooting first does not win: the first to fire after exposure wins only
  [metric:execution_questions/value/reaction@pooled17#paired.share=0.4496].
  The first to hit wins [metric:execution_questions/value/first_hitter@pooled17#share=0.8011].
- **Today's capture measures almost none of it.** No reader sees the
  crosshair, a shot, a hit, or the view angle. The pieces that exist: the
  minimap cone's self facing (median error
  [metric:execution_questions/capture/selfface@c817691bcd15#abs_p50=1.685]
  degrees against the replay's yaw), a 2 Hz HUD magazine drop that finds the
  half-seconds the player fired (recall
  [metric:execution_questions/capture/hudfire_shift-450@c817691bcd15#recall=0.9104],
  precision [metric:execution_questions/capture/hudfire_shift-450@c817691bcd15#precision=0.9531]),
  and the combat report's per-round head, body and leg hit counts.
- **Crosshair placement from the map works coarsely, and coarse is most of
  its value.** Placement scored on yaw alone keeps the paired share at
  [metric:execution_questions/value/placement_yaw_only@pooled17#paired.share=0.601];
  with the cone's measured error added it keeps
  [metric:execution_questions/value/placement_cone@pooled17#paired.share=0.5831]
  against the full [metric:execution_questions/value/placement@pooled17#paired.share=0.6135]
  (enemy-position error not yet modelled). Sub-degree placement, pitch,
  first-shot timing and counter-strafe need the screen: an enemy detector
  near the crosshair and a view-rotation estimate, read densely only inside
  the player's engagement windows, which hold 5-11% of his living time.
- **Build first:** head share of hits from the combat report (reader exists,
  value [metric:execution_questions/value/ladder_head_share@ladder#diff=0.123]
  per player-round on 140 ladder matches); coarse placement and angle
  clearing from the stored cone facing; then a gated screen reader for
  first-shot outcome and counter-strafe (section 5).

## 1. The catalogue

Each question is a quantity per participant of an engagement, computable on
truth as defined here. **Exposure** is the first 8 ms tick, at or before the
duel's contact onset less 1 s at the earliest, at which the segment from the
participant's eye to the enemy's eye is clear (`line_of_sight`), inside the
clear run that holds the window's first clear tick; the eye sits
[domain:game_data/character-eye-height] above the capsule centre. The
**target** is the enemy's eye 50 ms earlier, RENDER_DELAY's constant prior,
so the error is against what the participant was shown.

| Group (what it coaches) | Question | Definition | On truth here |
|---|---|---|---|
| Aim placement | Crosshair placement at exposure | angle between the view vector (yaw, pitch) and the vector to the target at exposure; yaw-only beside it | computed |
| Aim placement | Angles checked while clearing | for each callout region entered, the share of its sightline-visible approach angles that came within the player's view (yaw within 10 degrees) before he crossed it, and their order | defined, not computed |
| Reaction | Reaction time | first shot at or after exposure less exposure; a shot in the 300 ms before exposure marks a prefire | computed |
| Reaction | Adjustment time | first tick at or after exposure where the placement error is at most atan(15 cm / distance), less exposure | computed |
| Shot execution | First-bullet outcome | does the first shot after exposure hit the enemy (a damage call by the shooter on him within 16 ms), and in which region | computed |
| Shot execution | Counter-strafe | horizontal speed at the first shot, central difference over 16 ms; still below 100 cm/s, moving above 250 cm/s | computed |
| Shot execution | Spray and burst discipline | shots and hits from exposure to the kill; burst length and pause per engagement | hits per shot computed; burst shape not |
| Shot execution | Head share of hits | head hits over all hits, per player-round | ladder, and per duel on truth |
| Duel | First hit | who lands the first damage of a kill duel (episode `first_hitter`) | computed |
| Duel | Peek: who moved into the angle | peeker against holder at contact (COACHING_QUESTIONS CQ17) | measured there: no edge |
| Duel | Time to kill, damage trade | winner's first shot to the kill; net damage of the duel | not valued here |
| Utility | Blinded at exposure | an `ActiveBlinds` entry covers exposure | 2 of 17 replays only |
| Utility | Flash then peek | a teammate's flash blinds the enemy within 0-500 ms before the participant's exposure | defined, not computed |
| Utility | Response to enemy utility | time from an enemy cast landing near the player to his leaving its area or turning to it | defined, not computed |

## 2. Truth: what the replay and the match records hold

`execution_questions.py fields` on c817691bcd15's replay, `check` on all 17:

| Field | Where | Rate and timing | Precision | Serves |
|---|---|---|---|---|
| Position x, y, z | layer `ticks` | server tick: median [metric:execution_questions/truth/fields@c817691bcd15#tick_dt_ms.p50=8.0] ms, [metric:execution_questions/truth/fields@c817691bcd15#tick_dt_ms.share_le_8=0.9945] of steps at 8 ms or less | cm | speed at the shot (counter-strafe), exposure geometry |
| View yaw, pitch | layer `ticks` | the same tick | [metric:execution_questions/truth/fields@c817691bcd15#yaw_step_deg_min=0.0054931640625] degree steps | placement, adjustment, clearing |
| Velocity | not stored | derived from position | tick-level; a 16 ms central difference | counter-strafe |
| Shots fired | vrfkit `fields`: the gun's magazine falls by one per shot | the tick; equal to the hit's damage-call ms | [metric:execution_questions/truth/check@pooled17#explained=8276] of [metric:execution_questions/truth/check@pooled17#gun_hits=8397] gun hits on players matched within 16 ms; [metric:execution_questions/truth/check@pooled17#shots=45872] shots | reaction, first bullet, spray |
| Hits and damage | layer `events` `damage`; region and zoom from the raw call | the tick | dealt, taken, impact point, wallbang; region head/body/legs | first bullet, head share, first hit |
| Weapon | layer `state` `equipped`; the damage call's equippable | on change | class | stratifying by gun |
| Ability casts | layer `events` `cast` | the cast record | ms | utility timing |
| Blinds | vrfkit `BlindManagerComponent` | on change | start and duration | utility response; 2 replays only |
| Riot and HenrikDev ladder records | per player-round: head, body, leg hit counts and damage per opponent | per round, no times | counts | head share against round win, large n |

Not in the layer today: shots, hit regions and blinds. The prototype reads
them from vrfkit's export; keeping them belongs in `replay_layer` events
(`shot`, `damage.region`, `blind`) if the player wants them kept. The
ladder carries no shots fired, so accuracy (hits over shots) exists only on
the replays.

## 3. Value: do they matter?

Instances: both participants of each kill duel with sight on the 17
replays but bd7efa02 ([metric:execution_questions/value/meta@pooled17#participants=4936]
participants; exposure fell before the 3 s search window for
[metric:execution_questions/value/meta@pooled17#exposure_censored=38]).
**Paired** is the share of duels the participant better on the quantity
wins, with a 1000-draw match bootstrap; **tercile** is the stratified win
difference between the best and worst third of participants (strata:
distance under 10, 10-20, 20 m and more; COACHING_QUESTIONS's estimator).
Each is an association within the player's lobbies, not a causal effect.

| Question | Typical value | Paired [95%] | Best against worst third, or yes against no [95%] | Reading |
|---|---|---|---|---|
| Crosshair placement at exposure | median [metric:execution_questions/value/placement@pooled17#p50=5.56] degrees (yaw only [metric:execution_questions/value/placement@pooled17#yaw_p50=4.8]) | [metric:execution_questions/value/placement@pooled17#paired.share=0.6135] [[metric:execution_questions/value/placement@pooled17#paired.ci_lo=0.5999], [metric:execution_questions/value/placement@pooled17#paired.ci_hi=0.6279]] (n [metric:execution_questions/value/placement@pooled17#paired.n=2406]) | under [metric:execution_questions/value/placement@pooled17#tercile.t_lo=3.155] against over [metric:execution_questions/value/placement@pooled17#tercile.t_hi=10.77] degrees: [metric:execution_questions/value/placement@pooled17#tercile.diff=0.2005] [[metric:execution_questions/value/placement@pooled17#tercile.ci_lo=0.1693], [metric:execution_questions/value/placement@pooled17#tercile.ci_hi=0.2319]] | the strongest controllable mechanic; robust to the render-delay prior (median [metric:execution_questions/value/placement@pooled17#p50_d0=5.34] at 0 ms, [metric:execution_questions/value/placement@pooled17#p50_d100=5.82] at 100 ms) |
| First-bullet outcome | hits on [metric:execution_questions/value/first_bullet@pooled17#hit_share=0.3354] of first shots; head on [metric:execution_questions/value/first_bullet@pooled17#head_share_of_hits=0.3146] of those hits | | hit [metric:execution_questions/value/first_bullet@pooled17#hit.diff=0.3087] [[metric:execution_questions/value/first_bullet@pooled17#hit.ci_lo=0.2798], [metric:execution_questions/value/first_bullet@pooled17#hit.ci_hi=0.3353]]; head [metric:execution_questions/value/first_bullet@pooled17#head.diff=0.4115] [[metric:execution_questions/value/first_bullet@pooled17#head.ci_lo=0.3901], [metric:execution_questions/value/first_bullet@pooled17#head.ci_hi=0.4286]] | a first head hit wins [metric:execution_questions/value/first_bullet@pooled17#head.y_a1=0.9639]; partly an outcome of placement |
| Counter-strafe | median [metric:execution_questions/value/speed_at_shot@pooled17#p50=34.9] cm/s at the first shot; still on [metric:execution_questions/value/speed_at_shot@pooled17#still_share=0.6438] | | still against moving [metric:execution_questions/value/speed_at_shot@pooled17#still_vs_moving.diff=0.0745] [[metric:execution_questions/value/speed_at_shot@pooled17#still_vs_moving.ci_lo=0.0362], [metric:execution_questions/value/speed_at_shot@pooled17#still_vs_moving.ci_hi=0.1162]] | the first shot hits [metric:execution_questions/value/speed_at_shot@pooled17#first_hit_still=0.4009] still against [metric:execution_questions/value/speed_at_shot@pooled17#first_hit_moving=0.2183] moving |
| Adjustment time | median [metric:execution_questions/value/adjustment@pooled17#p50=392.0] ms where reached | [metric:execution_questions/value/adjustment@pooled17#paired.share=0.5553] [[metric:execution_questions/value/adjustment@pooled17#paired.ci_lo=0.523], [metric:execution_questions/value/adjustment@pooled17#paired.ci_hi=0.5827]] (n [metric:execution_questions/value/adjustment@pooled17#paired.n=796]) | reached before the kill by [metric:execution_questions/value/adjustment@pooled17#reached_winners=0.6341] of winners, [metric:execution_questions/value/adjustment@pooled17#reached_losers=0.4671] of losers | weak; the head tolerance is strict, and winners often kill on body hits |
| Reaction time (first shot) | median [metric:execution_questions/value/reaction@pooled17#p50=399.0] ms | [metric:execution_questions/value/reaction@pooled17#paired.share=0.4496] [[metric:execution_questions/value/reaction@pooled17#paired.ci_lo=0.4264], [metric:execution_questions/value/reaction@pooled17#paired.ci_hi=0.4697]] | fastest against slowest third [metric:execution_questions/value/reaction@pooled17#tercile.diff=-0.0373] [[metric:execution_questions/value/reaction@pooled17#tercile.ci_lo=-0.0641], [metric:execution_questions/value/reaction@pooled17#tercile.ci_hi=-0.0143]] | shooting first loses slightly: a fast miss costs; prefire (on [metric:execution_questions/value/reaction@pooled17#prefire_share=0.0561]) [metric:execution_questions/value/reaction@pooled17#prefire.diff=-0.1309] |
| First hit | | [metric:execution_questions/value/first_hitter@pooled17#share=0.8011] [[metric:execution_questions/value/first_hitter@pooled17#ci_lo=0.7897], [metric:execution_questions/value/first_hitter@pooled17#ci_hi=0.8118]] | | the duel's result in miniature: reaction and accuracy combined |
| Spray | the winner lands [metric:execution_questions/value/spray@pooled17#winner_hits_per_shot_p50=0.6] hits per shot over a median [metric:execution_questions/value/spray@pooled17#winner_shots_p50=3.0] shots | | | not valued; a burst-shape definition needs the player |
| Blinded at exposure | [metric:execution_questions/value/blinded@pooled17#share=0.0018] of participants | | blinded won [metric:execution_questions/value/blinded@pooled17#won_blinded.share=0.2222] of [metric:execution_questions/value/blinded@pooled17#won_blinded.n=9] | no truth on 15 replays; unvalued |
| Head share of hits (ladder) | median [metric:execution_questions/value/ladder_head_share@ladder#hs_p50=0.1667] per player-round with 3 or more hits | | 0.25 or more against none: round win [metric:execution_questions/value/ladder_head_share@ladder#y_a1=0.6384] against [metric:execution_questions/value/ladder_head_share@ladder#y_a0=0.5206], [metric:execution_questions/value/ladder_head_share@ladder#diff=0.123] [[metric:execution_questions/value/ladder_head_share@ladder#ci_lo=0.1011], [metric:execution_questions/value/ladder_head_share@ladder#ci_hi=0.1438]] (n [metric:execution_questions/value/ladder_head_share@ladder#n=9100], [metric:execution_questions/value/ladder_head_share@ladder#matches=140] matches) | confounded with skill and with winning the round's fights |

A kill duel's value reaches the round through the opening duel and trades
(COACHING_QUESTIONS section 2): an opening kill moves round win by 0.36 on
the ladder. Each player fights about 29 kill duels a match (2445 over 17
matches, two participants of ten). Placement and the first shot are
execution habits the player carries into every one.

Peeker against holder and wide against tight peeks showed no edge
(COACHING_QUESTIONS sections 2.2-2.3); this study adds none. Clearing, flash
timing and utility response stay defined and unvalued: clearing needs a
per-region angle set from the sightline table, and utility needs blinds,
which truth holds on two replays.

## 4. Capture: what the pipeline reads, how well, and at what cost

### 4.1 Today's readers

| Reader | Output | Rate | Bears on |
|---|---|---|---|
| `teardrop` self cone, stored in `events/team_vision` | self x, y and facing (degrees, image frame) | 15 Hz over round time | yaw only: coarse placement, clearing |
| `hud_reader` (`l1/hud`) | hp, shield, magazine, reserve | 2 Hz | own firing by half-second; damage taken |
| `combat_report` | per round and enemy: damage each way, head/body/leg hit counts, KILLED flags | 1 Hz while shown | head share of hits, damage trade |
| killfeed (`adjudication.weapon`) | weapon, wallbang; the headshot mark is masked, never read | 2 Hz | kill-shot weapon |
| `screen.outline_candidates` | red-outline boxes on the game screen | prototype only, not wired | enemy on screen near the crosshair |
| `blinds` | spans where a flash's wash hides the HUD | 5 Hz | own blindness |
| `primitives` `center` crop | luma, edge, hash of the crosshair region | 5 Hz | nothing aim-related yet |

No reader estimates the view angle from the screen, detects a shot or a
hit marker, or reads audio gunfire.

### 4.2 Measured against truth (development sessions)

**Self facing from the minimap cone** (`selfface`: teardrop facing in
`team_vision`, not interpolated, against the replay's self yaw at the same
frame; the layer's frame clock already applies the minimap lag):

| Session | n | Median error | p90 | Flips (over 90 degrees) | Within 0.57 degrees |
|---|---|---|---|---|---|
| c817691bcd15 | [metric:execution_questions/capture/selfface@c817691bcd15#n=6603] | [metric:execution_questions/capture/selfface@c817691bcd15#abs_p50=1.685] | [metric:execution_questions/capture/selfface@c817691bcd15#abs_p90=18.093] | [metric:execution_questions/capture/selfface@c817691bcd15#flip_share=0.0669] | [metric:execution_questions/capture/selfface@c817691bcd15#within_0_57=0.1829] |
| d3dcfb182ab1 | [metric:execution_questions/capture/selfface@d3dcfb182ab1#n=6894] | [metric:execution_questions/capture/selfface@d3dcfb182ab1#abs_p50=1.666] | [metric:execution_questions/capture/selfface@d3dcfb182ab1#abs_p90=19.946] | [metric:execution_questions/capture/selfface@d3dcfb182ab1#flip_share=0.0541] | [metric:execution_questions/capture/selfface@d3dcfb182ab1#within_0_57=0.186] |
| 9acf02f98283 (team-vision-0.6.0, small minimap) | [metric:execution_questions/capture/selfface@9acf02f98283#n=4190] | [metric:execution_questions/capture/selfface@9acf02f98283#abs_p50=5.454] | [metric:execution_questions/capture/selfface@9acf02f98283#abs_p90=28.77] | [metric:execution_questions/capture/selfface@9acf02f98283#flip_share=0.0737] | [metric:execution_questions/capture/selfface@9acf02f98283#within_0_57=0.0525] |

A head 15 cm across at 15 m subtends 0.57 degrees; the cone reaches it on
under a fifth of frames. It has no pitch, and its tail (p90 near 20
degrees, flips near 6%) needs a flip guard before any per-duel answer.

**Own firing from the HUD** (`hudfire`: a magazine drop between confident
2 Hz reads with the reserve held, the player alive, against truth shots in
the same interval; truth shots placed on the screen's clock by the existing
`replay_source.MINIMAP_LAG_MS`):

| Session | Recall | Precision | Drop equals the shot count |
|---|---|---|---|
| 9acf02f98283 | [metric:execution_questions/capture/hudfire_shift-450@9acf02f98283#recall=0.9155] | [metric:execution_questions/capture/hudfire_shift-450@9acf02f98283#precision=0.8667] | [metric:execution_questions/capture/hudfire_shift-450@9acf02f98283#count_exact=0.6308] |
| c817691bcd15 | [metric:execution_questions/capture/hudfire_shift-450@c817691bcd15#recall=0.9104] | [metric:execution_questions/capture/hudfire_shift-450@c817691bcd15#precision=0.9531] | [metric:execution_questions/capture/hudfire_shift-450@c817691bcd15#count_exact=0.7213] |
| d3dcfb182ab1 | [metric:execution_questions/capture/hudfire_shift-450@d3dcfb182ab1#recall=0.9524] | [metric:execution_questions/capture/hudfire_shift-450@d3dcfb182ab1#precision=0.9756] | [metric:execution_questions/capture/hudfire_shift-450@d3dcfb182ab1#count_exact=0.8] |

The 2 Hz drop says that the player fired in a half-second, not when: a
first-shot time needs the magazine at frame rate inside the window (a digit
crop, cheap) or the audio onset of his own gunfire.

**Engagement windows** (`windows`: the union of the player's duel episodes,
1 s before to 0.5 s after, over his living time): [metric:execution_questions/capture/windows@9acf02f98283#share_of_alive=0.054],
[metric:execution_questions/capture/windows@c817691bcd15#share_of_alive=0.0607] and
[metric:execution_questions/capture/windows@d3dcfb182ab1#share_of_alive=0.1059].
A dense screen reader gated to them runs on a tenth of the frames or less.

### 4.3 Crosshair relative to the map and the enemy: three signals, priced

The crosshair is fixed at the screen centre, so "where the crosshair is"
means "where the view points", and placement needs the target too.

1. **The minimap cone's yaw, against the drawn enemy's position.** Stored
   today at 15 Hz; no new decode. Degrading truth placement to yaw only and
   adding the cone's measured error keeps most of the value (EQ10): paired
   [metric:execution_questions/value/placement_cone@pooled17#paired.share=0.5831]
   [[metric:execution_questions/value/placement_cone@pooled17#paired.ci_lo=0.5678],
   [metric:execution_questions/value/placement_cone@pooled17#paired.ci_hi=0.5976]],
   best against worst third
   [metric:execution_questions/value/placement_cone@pooled17#tercile.diff=0.1683]
   against truth's [metric:execution_questions/value/placement@pooled17#tercile.diff=0.2005].
   The arm leaves out the enemy icon's position error, the remote lag and
   whether the enemy is drawn at exposure, so it bounds the route from
   above. Answers: "was the crosshair on the angle he came from" (degrees),
   angles checked while clearing. Cannot answer: head level, pitch,
   sub-degree placement, adjustment.
2. **Screen-space enemy detection near the centre.** The enemy's pixel
   offset from the screen centre is the placement error directly, yaw and
   pitch: with the 103 degree field of view episodes assumes (`PARAMS`
   `HFOV_DEG`, the player's answer Q1) a 1920 px frame puts about 0.075
   degrees in a pixel at the centre. `screen.outline_candidates` finds red
   outlines at 0.91 recall and 0.41-0.49 precision on 149 frames of one
   session (its prototype's own figures, one outline colour). It answers
   placement, adjustment time and first-bullet aim to sub-degree, when the
   outline shows. New reader: a centre crop (for instance 640 x 360, about
   plus or minus 18 degrees) read at capture rate inside engagement windows
   only. Cost not measured; a colour threshold and connected components on
   that crop is a few milliseconds per frame on this CPU, times the window
   share above, so well under 1 ms per captured frame averaged. It needs a
   window-gated decode, which is a proposed step, not run here.
3. **View rotation from optical flow.** The camera's yaw and pitch rates
   from the global image shift (phase correlation on a downscaled frame,
   OpenCV) give flick speed, settle time and adjustment without seeing the
   enemy; at a quarter resolution one pixel is about 0.3 degrees. It is
   checkable against the replay's self yaw at 128 Hz on the three
   development sessions before any wiring. Cost not measured; a quarter
   resolution phase correlation is about a millisecond per frame, inside
   windows only.

Counter-strafe needs the player's own speed at the shot to 100 cm/s.
The minimap self position at 15 Hz is too coarse for a 16 ms speed;
candidates are optical-flow translation, footstep audio, and the dynamic
crosshair's spread if the player's settings draw it (a question for him).

### 4.4 Per question: today's measurement and the reader it needs

| Question | Today's best capture measurement | Its error against truth | New reader | Rough cost |
|---|---|---|---|---|
| Crosshair placement | cone yaw against the drawn enemy | yaw median 1.7-5.5 degrees, p90 18-29; no pitch | screen enemy near the centre, gated | a few ms per window frame |
| Angles checked while clearing | cone yaw (stored) | as above; angles differ by tens of degrees | none: a recompute over stored rows and the sightline table | negligible |
| Reaction time | none (the 2 Hz HUD drop says fired, not when) | half-second resolution | magazine digit at frame rate in windows, or own-gunfire audio onset | under 1 ms per window frame |
| Adjustment time | none | | optical-flow view rotation plus screen enemy | about 1-5 ms per window frame |
| First-bullet outcome | combat report: hits per round and enemy, no order | unmeasured here | screen enemy at the first shot; a hit cue (a hit marker or sound, if the game draws one: a question for the player) | as above |
| Head share of hits | combat report hit split, 1 Hz | not scored here: rows exist for 9acf02f98283 only | none: run the reader on every session | none new |
| Counter-strafe | none | | optical-flow translation, or crosshair spread | about 1 ms per window frame |
| First hit, damage trade | combat report (per round), killfeed (kills) | | none for the round-level answer | none new |
| Blinded, flash-then-peek | `blinds` own wash at 5 Hz; minimap flashes partly | unmeasured | ability timing from the audio bank and minimap | existing passes |

## 5. Ranked recommendation

Ranked by value over measurement cost:

1. **Head share of hits per round, the player's own**, from the combat
   report. Value: [metric:execution_questions/value/ladder_head_share@ladder#diff=0.123]
   per player-round on the ladder; the reader exists and costs nothing new.
   Next step: run the combat-report reader on the development sessions
   and score its hit splits against the replay's regions.
2. **Coarse crosshair placement and angle clearing from the stored cone.**
   Value: placement is the strongest controllable mechanic, and the cone
   keeps most of it on truth; cost: a recompute over stored `team_vision`
   rows. Next step: add the enemy icon's position error and the drawn gate
   to the EQ10 arm, then define the per-region angle sets for clearing and
   value them on truth.
3. **First-bullet outcome and counter-strafe, from a gated screen reader.**
   Value: the largest duel differences measured (first hit +0.31, still
   +0.07); cost: a window-gated decode of a centre crop plus a view-rotation
   estimate. Next step, proposed and not run: decode the player's engagement
   windows on c817691bcd15 (about 6% of his living time), run
   `screen.outline_candidates` and phase correlation on the centre crop,
   and score placement, first-shot aim and speed against the replay.
4. **Adjustment time.** Weak value (paired 0.56); it rides on reader 3.
5. **Reaction time alone: do not coach.** Shooting first without hitting
   loses; the first hit, which reader 3 serves, is the useful form.
6. **Utility response and flash timing: wait for truth.** Blinds are decoded
   on two replays; the next replays kept from current builds will carry them.

## 6. Questions for the player

1. Which mechanics do you want coached: placement, first-shot discipline,
   counter-strafing, spray control, clearing, utility timing? The ranking
   above assumes all are wanted.
2. Do you want per-duel feedback (this fight, this angle) or habits over a
   match (your placement median, your first-shot hit rate)? Habits need far
   fewer reads.
3. Which crosshair do you play with: does it show movement or firing error,
   and its colour and outline? A dynamic crosshair would read counter-strafe
   from the screen directly.
4. Does the game draw a hit marker or play a distinct hit or headshot sound
   in your settings? Either would give first-bullet outcome without seeing
   the enemy.
5. What enemy highlight colour do you use? `screen.outline_candidates`
   depends on it.
6. For clearing: which angles on each site do you consider must-check, or
   should the sightline table define them?
7. Is a spray "disciplined" by burst length, by pause, or by hits per
   shot? The data hold all three.

## 7. Predictions and outcomes

Registered in the store's `notes/predictions.jsonl` (task
`execution-questions-20261007`) before each run; outcome rows follow.

| Ref | Prediction (short) | Outcome |
|---|---|---|
| EQ0a | shots explain at least 0.97 of gun hits on every replay | **failed** narrowly: 16 of 17 at 0.977 or more, 75111fd9 at 0.966 |
| EQ0b | region 1 names head bones on 0.95; region 2 leg bones on 0.9 | head held (1.0); legs **failed** on my bone list (0.86-1.0), an instrument limit |
| EQ1a-b | placement median 5-20 degrees; the better placed wins 0.52-0.62 | held: 5.56; 0.614 |
| EQ1c | tercile difference 0.05-0.20 | **failed** narrowly, above: 0.2005 |
| EQ2a, c | reaction median 250-600 ms; prefire 0.05-0.20 | held: 399 ms; 0.056 |
| EQ2b | the first to shoot wins 0.55-0.70 | **failed**, opposite sign: 0.450 |
| EQ3a-b | first shot hits 0.20-0.45; head share 0.15-0.40 | held: 0.335; 0.315 |
| EQ3c | a first-shot hit lifts the win share 0.10-0.30 | **failed** narrowly, above: 0.309 |
| EQ4a-b | still at the shot 0.40-0.75; still wins 0.03-0.15 more | held: 0.644; 0.075 |
| EQ5a | the first hitter wins 0.65-0.80 | **failed** narrowly, above: 0.801 |
| EQ6a-c | adjustment median 150-400 ms; reached by more winners; faster wins 0.55-0.70 | held: 392 ms; 0.63 against 0.47; 0.555 |
| EQ7a | blinded wins at most 0.35 | figures hold (0.22 of 9) but untestable: blinds on 2 replays |
| EQ8a | ladder head share difference 0.02-0.10 | **failed**, above: 0.123 |
| EQ9a | cone facing median 1.5-4 degrees per session | held on two (1.69, 1.67); **failed** on 9acf02f98283 (5.45) |
| EQ9b | p90 5-15 degrees; flips at most 0.10 | p90 **failed** (18-29); flips held (0.05-0.07) |
| EQ9c | the cone's median at least 3 times the 0.57 degree need | held on 9acf02f98283; **failed** narrowly on the others (2.9 times) |
| EQ10a | yaw-only placement keeps paired 0.58-0.62 | held: 0.601 |
| EQ10b | the cone arm: paired 0.54-0.59, tercile 0.08-0.16 | paired held (0.583); tercile **failed**, above (0.168): the cone keeps more than believed |

A correction row records my own clock error: the first HUD-fire run placed
truth shots at the killfeed-fitted offset and found recall near 0.6; the
screen shows replay time with the existing minimap lag, and on that clock
recall rose to 0.91-0.95.

## 8. What was not done

- No video decode and no new reader: every capture figure comes from stored
  rows (`team_vision`, `l1/hud`). The screen and optical-flow costs are
  estimates, not measurements.
- The cone arm models self-facing error only, not the enemy icon's error,
  the remote lag or whether the enemy is drawn at exposure.
- The combat report's hit splits were not scored against the replay's
  regions; only 9acf02f98283 has stored rows.
- Crouching moves the eye; exposure and the target use the standing eye
  height for everyone.
- Clearing, flash timing, utility response, time to kill and spray shape are
  defined and not valued.
- Duel ids repeat within a match in a few cases (2445 distinct of 2468); the
  paired statistics drop those duels.
- Value is association: placement and first hits mark better players as
  well as better habits; nothing here is causal.
- The ladder figure stratifies by hit count, not by side or economy.
