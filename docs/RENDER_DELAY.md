# Render delay: server time and client time in the entity layer

A plan, proposed 2026-10-06; nothing here is wired. The player asked whether
the entity layer can account for the minimap's remote-player delay
[domain:capture/minimap-remote-player-lag] systematically and get closer to
real time, with no replay at inference. Rules live in [AGENTS.md](../AGENTS.md);
this plan cites them. It amends [ENTITY_STATE.md](ENTITY_STATE.md) (section 6
here) and reads the fidelity column of
[QUESTION_ACCEPTANCE.md](QUESTION_ACCEPTANCE.md) section 1. The measurements
are `prototypes/render_delay.py`; predictions and outcomes sit in the store's
`notes/predictions.jsonl` under task `render-delay-estimator-20261006`
(rows `render-delay-estimator-*`, `peek-advantage-*`, `sight-geometry-*`).
Section 4a tests the player's ping hypothesis (`prototypes/render_delay_ping.py`,
task `render-delay-ping-20261006`).

## Summary

1. **Two clocks, both stored.** The capture shows the player's client: its
   time is the client's view, exact, and stays every observation's time.
   Server time is an estimate per belief: render time less a per-class delay,
   with a band. Questions about what the player could know read client time
   and need no correction. Questions that order events between players read
   server time.
2. **Fidelity decides the correction, and most questions need none.** The
   delay moves a remote icon by speed times delay: at a run, a third of a
   metre to a metre, inside one icon radius
   ([metric:render_delay/estimate@c817691bcd15#r_icon_m=2.62] m on
   c817691bcd15). Still players carry no error at all. Region, phase, trade
   and rotation questions sit far above it; the 1 m reach cell and duel order
   sit at it.
3. **No capture-only estimator recovers the delay per match.** Five
   candidates were registered and measured on the development matches; each
   compares a remote icon with the self icon at an instant whose true relation
   the capture cannot see (formation, behaviour) or seldom shows (deaths,
   plants). Where the replay supplies that relation, the residual equals the
   delay, so the model holds. The recommendation is a prior with a band wide
   enough for 9acf02f98283.
4. **Ping does not set the delay.** The replay carries every player's ping.
   The lobby's highest ping is
   [metric:render_delay/ping@9acf02f98283#lobby_max=59.0] ms on the match
   with the largest delay and
   [metric:render_delay/ping@d3dcfb182ab1#lobby_max=150.0] ms on one with a
   small delay; neither the highest, the mean nor the player's own ping
   orders the delay between matches or tracks it within one (section 4a).
   The prior stays a constant, and a ping reader is no witness of the delay.
5. **Duel order is geometry first, netcode second.** With bodies of the
   agent's width, the player closer to the occluding edge sees later in
   [metric:render_delay/sight_geometry@dev3#closer_sees_later=0.921] of
   duels, by a median
   [metric:render_delay/sight_geometry@dev3#closer_minus_farther_median_ms=70.3]
   ms; peekers are the closer player in
   [metric:render_delay/sight_geometry@dev3#peeker_is_closer=0.786] of clean
   peeks. Netcode then shifts each side's client view by its match's remote
   delay, the same size. Peek or hold, distance to the edge and the match's
   delay are the duel's attributes; a server-time first-sight instant is not.

## 1. The timing model

### Clocks

- **Render time** `t_render`: the capture's frame time, the client's view.
  Stored timestamps stay observation times (AGENTS.md); this is that time.
- **Server time** `t_server`: when the server held the state an observation
  shows. The self icon is the reference: the client predicts the player, so
  the self icon leads the server by a small constant no capture can see, and
  every in-capture ordering is unaffected by it. Define
  `t_server = t_render - d(class)`, with `d(self) = 0`.
- **Capture rate drift**, about 1e-4 against the replay, matters only when
  joining a capture to a replay. Within one capture every channel shares the
  capture clock: a 100 s round drifts 10 ms against the server, below every
  tolerance in section 3. The HUD clock cannot resolve it either: the within
  round slope of the 2 Hz, 1 s clock reads
  [metric:render_delay/estimate@c817691bcd15#e6_drift=0.000221] on
  c817691bcd15 with an interval as wide as the effect, and misreads break the
  fit on the other two matches. No inference question needs it.

### Per-class delays, against the self icon

| Class | Channel and rate | Delay `d` against the self icon | Jitter |
|---|---|---|---|
| Self | `ally_icon` self fit, 15 Hz | 0 by definition | frame period |
| Remote players (teammates, enemies alike) | `round_entity`, `minimap_object`, 15 Hz | the match's remote delay [domain:capture/minimap-remote-player-lag] | per-round spread of the paired gap, tens of ms |
| Killfeed entries | `death` verdicts, the first 2 Hz sample | about `-replay_source.MINIMAP_LAG_MS`, plus up to 500 ms of sampling; it moved by about 80 ms between matches (teammate-lag outcome) | uniform over the 2 Hz period |
| Death X marks | `minimap_object` `x_marks`, 15 Hz | arrives one frame after the dying icon's last fit on the c817691bcd15 deaths inspected | frame period |
| HUD round clock, plant graphic | `rounds`, 2 Hz | uncalibrated | uniform over the 2 Hz period |

The killfeed's offset, not the remote delay, dominates any question that puts
a kill instant against positions: at a run it is metres. Its 2 Hz sampling
adds a uniform 0-500 ms on top. The X mark is a finer death clock where the
minimap is drawn; 9acf02f98283 stores no `minimap_object` stream, so it has
none.

### What a slot belief carries

Each fit keeps `t_render`. Its belief gains:

- `t_server = t_render - d_hat(class)` and a band `[t_render - d_hi, t_render - d_lo]`;
- the **bound** is ENTITY_STATE's reach disc anchored at the band's earliest
  server time, `t_render - d_hi`: queried at a self-clock instant `t`, it
  grows `v_max * (t - t_render + d_hi) + r_fit`. A remote fit at its own
  frame thus carries `v_max * d_hi` more radius than a self fit: 1.5 m at
  `d_hi` = 200 ms and `v_max` [domain:game_data/character-movement-speeds];
- the **point** may be carried forward to the self clock by the slot's own
  velocity, `x + v * d_hat`, stored apart (`x_now`); it predicts and never
  narrows the region, as ENTITY_STATE's "no velocity in the region" requires.
  For a still slot it does not move, and the error it corrects is zero.

The error a wrong delay leaves is the slot's speed times the delay's error.
The radius term uses `v_max` because a region is a bound; the point's sigma
may use the slot's measured speed.

## 2. Which questions need which clock

**Client time (what the player could know when deciding).** Did the player
have the enemy's minimap icon, the teammate's position, the killfeed entry,
when he chose to peek, rotate or call? How long from an enemy drawn on his
screen to his shot? These read the capture as it is: render time is the
client clock, so no correction applies. The remote delay is itself an
attribute here: it says how late the player's client drew moving enemies in
that match, which is the peeker's advantage held against him.

**Server time (what happened between players).** Kill and trade order, who
dealt first damage, spacing at a kill instant, an execute's entry spread,
plant and defuse against positions, acceptance against the replay (T0 of
QUESTION_ACCEPTANCE). These need each class's delay, and the killfeed's offset
most of all.

**Both, never collapsed.** Store `t_render` per observation and derive
`t_server` per belief with the delay table's version; a consumer names the
clock it reads.

### Duels: peek or hold, the edge, and each side's view

The player's input (2026-10-06): lag compensation registers hits on what the
shooter's client saw, so peekers gain; server-time sight gaps are usually
under 100 ms; and the player closer to the corner sees later. Measured on the
666 truth duels of the development replays:

- **Point targets tie by construction.** `episodes.sight` tests the
  target's centre or eye from the viewer's eye, which is the same segment
  both ways: onsets tie at 128 Hz in
  [metric:render_delay/sight_geometry@dev3#point_ties=0.896] of mutual duels.
  That is the instrument's symmetry, not the game.
- **With body width the tie breaks and geometry orders sight.** Seeing any
  of six points of a 42 cm-radius body
  [domain:movement/game-units-are-centimetres], ties fall to
  [metric:render_delay/sight_geometry@dev3#body_ties=0.04]. The player closer
  to the occluding edge sees later in
  [metric:render_delay/sight_geometry@dev3#closer_sees_later=0.921] of
  [metric:render_delay/sight_geometry@dev3#edge_split_nonzero=546] duels, by
  a median [metric:render_delay/sight_geometry@dev3#closer_minus_farther_median_ms=70.3]
  ms (90th percentile
  [metric:render_delay/sight_geometry@dev3#closer_minus_farther_p90_ms=148.4]
  ms), growing with the distance asymmetry (Spearman
  [metric:render_delay/sight_geometry@dev3#gap_vs_ratio_rho=0.543]; median
  [metric:render_delay/sight_geometry@dev3#median_ms_ratio_0-0.2=15.6] ms when
  both stand about as far,
  [metric:render_delay/sight_geometry@dev3#median_ms_ratio_0.5-1.01=78.1] ms
  when one stands more than three times as far). About 0.72 of gaps are under
  100 ms, as the player said.
- **Peekers hug the corner and lose the geometry.** Movement in the 300 ms
  before sight labels a clean peek (one player at 2+ m/s, the other at most
  1 m/s) in [metric:render_delay/peek@dev3#clean_share=0.251] of duels; the
  rest are both moving (jiggles, swings, trades) or mixed. The peeker is the
  closer player in [metric:render_delay/sight_geometry@dev3#peeker_is_closer=0.786]
  of clean peeks, and the body-model first seer is the peeker in only
  [metric:render_delay/sight_geometry@dev3#clean_body_first_seer_is_peeker=0.234].
  The peeker deals first damage
  [metric:render_delay/sight_geometry@dev3#peeker_first_damage_when_closer=0.421]
  when closer and
  [metric:render_delay/sight_geometry@dev3#peeker_first_damage_when_farther=0.613]
  when farther, the wide-swing advice in numbers (the intervals touch;
  n 114 and 31). Overall the peeker deals first damage
  [metric:render_delay/peek@dev3#peeker_first_damage=0.449] of clean peeks on
  these matches.
- **Netcode acts in client time, by the match's delay.** The holder's client
  draws the moving peeker late by the remote delay; the peeker sees a still
  holder where he stands. So each side's client-view gap is the geometric gap
  shifted by about the match's delay: on the October matches the two are of
  a size, on 9acf02f98283 the delay is the larger. This is a model; the
  replay holds server state only, so it cannot be measured here.

What follows for duel questions:

- **First seer at 62.5 ms (QUESTION_ACCEPTANCE's "duel" row) is the wrong
  attribute.** Replace it with three the vision layer can supply: the role
  (peek, hold, both moving) from movement before contact, each player's
  distance to the occluding edge at contact (the sightline table and the
  slot's position, region fidelity suffices), and the match's remote delay.
  Server-time order then follows from geometry within tens of ms, and each
  side's client view from the delay.
- **Peek or hold needs speed, not timing.** Speed over 300 ms at the 15 Hz
  grid is a 2 m against 1 m/s cut, far above the delay's error (a uniform
  shift of the whole remote track changes no speed).
- **Server time remains for**: kill and trade order (the killfeed and X
  marks give it, to their sampling), first damage (no vision source reads
  damage at all; QUESTION_ACCEPTANCE), and acceptance against the replay.

## 3. Precision per question

The delay's displacement is `v * d`. At a run
[domain:game_data/character-movement-speeds] it is about 0.3 m on the
October matches and 1.1 m on 9acf02f98283; zero for a still player. After
the prior correction (section 5) the worst case is 9acf02f98283's residual,
about 0.8 m at a run. The fit radius already holds one icon radius, 2.5-2.9 m
([metric:render_delay/estimate@9acf02f98283#r_icon_m=2.92],
[metric:render_delay/estimate@d3dcfb182ab1#r_icon_m=2.54] m), and a frame's
travel.

| Question (QUESTION_ACCEPTANCE §1) | Clock | Fidelity it needs | Delay error at a run, uncorrected | Correction matters? |
|---|---|---|---|---|
| Round phases and result | server, HUD events | 0.5 s | none (no positions) | no; 2 Hz HUD sampling dominates |
| Attacking team | either | centroid to 10 m | 0.3-1.1 m | no |
| Contact (sight) | server | about 1.5 m, both located | 0.3-1.1 m | marginal on high-delay matches; the prior suffices |
| Duel (kill, killer, victim) | server | kill time 0.5 s | none | no; the killfeed's 2 Hz sampling and offset dominate |
| Duel first seer | see section 2 | was 62.5 ms | the delay is one to three samples | replaced by role, edge distance and the match's delay |
| Engagement | server | as duels | as duels | no |
| Trade | server | kill times 0.5 s; positions at t1 to 1.5 m | 0.3-1.1 m | the killfeed's offset matters more (metres); the delay marginally |
| Execute, region membership | server | radius below the distance to the volume's edge | 0.3-1.1 m against a 2.5+ m radius | only at volume edges |
| Retake, rotation, lurk | server | super-region, 3 s dwell | 0.3-1.1 m | no |
| Trade spacing at a kill | server | 1.5 m | 0.3-1.1 m | as trade |
| Reach: swing 2 m, trade 5 m (1 m cells) | server | the cell | 0.3-1.1 m, one cell on high-delay matches | yes for moving players at kill instants; the prior and band carry it |
| Rotation lag from a cue | client (the cue as drawn) | exit within 0.5 s | none | no |
| Holds and duplicate holds | either | 7.6 px, facing 15 degrees | zero (still players) | no |
| What the player could know | client | the frame | none: render time is the client clock | no correction by definition |

## 4. Capture-only estimators, measured

Registered before measuring (`render-delay-estimator-20261006-prediction`);
two instrument faults fixed after the first run on c817691bcd15 are recorded
as revision 1 (the stored round start is the buy phase's start, not the
barrier drop; the self grid steps 67 or 83 ms). Truth is the replay's paired
gap: [metric:render_delay/estimate@9acf02f98283#truth_delta=168.2],
[metric:render_delay/estimate@c817691bcd15#truth_delta=47.0] and
[metric:render_delay/estimate@d3dcfb182ab1#truth_delta=55.3] ms
(9acf02f98283, c817691bcd15, d3dcfb182ab1). An estimator recovers a match
within 30 ms with a 90% interval under 80 ms.

| Estimator | Witness | 9acf02f98283 | c817691bcd15 | d3dcfb182ab1 | Why it fails |
|---|---|---|---|---|---|
| E0 prior | 50 ms | misses by 118 ms | recovers | recovers | a constant |
| E1 lockstep | a teammate moving with the player trails by `v * d` | no co-moving pair | [metric:render_delay/estimate@c817691bcd15#e1_est=989.4] ms over [metric:render_delay/estimate@c817691bcd15#e1_episodes=13] episodes | [metric:render_delay/estimate@d3dcfb182ab1#e1_est=-1639.2] ms, [metric:render_delay/estimate@d3dcfb182ab1#e1_episodes=1] episode | where the teammate truly walks: formation bias [metric:render_delay/estimate@c817691bcd15#e1_truth_formation_bias=946.5] ms on c817691bcd15; capture minus truth [metric:render_delay/estimate@c817691bcd15#e1_capture_minus_truth=50.1] ms, the delay itself |
| E2 death X | the X arrives before the drawn icon reaches it; teammates less self | no X stream | [metric:render_delay/estimate@c817691bcd15#e2_est=73.7] ms ([metric:render_delay/estimate@c817691bcd15#e2_n_ally=6] and [metric:render_delay/estimate@c817691bcd15#e2_n_self=4] moving deaths) | [metric:render_delay/estimate@d3dcfb182ab1#e2_est=-58.4] ms ([metric:render_delay/estimate@d3dcfb182ab1#e2_n_ally=9] and [metric:render_delay/estimate@d3dcfb182ab1#e2_n_self=1]) | few moving deaths, the player's fewest |
| E3 plant | the planter stops 4 s before the plant graphic | refused | refused | refused | one to four attacking plants a match, under three per class |
| E4 barrier | the earliest teammate's onset less the player's at the barrier drop | [metric:render_delay/estimate@9acf02f98283#e4_est=165.4] ms from [metric:render_delay/estimate@9acf02f98283#e4_rounds=1] round | [metric:render_delay/estimate@c817691bcd15#e4_est=1170.2] ms, [metric:render_delay/estimate@c817691bcd15#e4_rounds=9] rounds | [metric:render_delay/estimate@d3dcfb182ab1#e4_est=-299.2] ms, [metric:render_delay/estimate@d3dcfb182ab1#e4_rounds=4] rounds | when each player chose to move: behaviour [metric:render_delay/estimate@c817691bcd15#e4_truth_behaviour=542.4] ms on c817691bcd15; capture minus truth [metric:render_delay/estimate@c817691bcd15#e4_capture_minus_truth=62.5] ms. 9acf02f98283's one round matches by chance: its behaviour term alone is [metric:render_delay/estimate@9acf02f98283#e4_truth_behaviour=170.6] ms |
| E5 ping | every player's ping (replay; scoreboard PING column) | lobby max [metric:render_delay/ping@9acf02f98283#lobby_max=59.0] ms | [metric:render_delay/ping@c817691bcd15#lobby_max=57.0] ms | [metric:render_delay/ping@d3dcfb182ab1#lobby_max=150.0] ms | no ping orders the matches' delays (section 4a) |
| E6 clock | HUD round clock against capture time | drift unresolved | drift unresolved | fit broken by misreads | estimates drift, which inference never needs |

No estimator recovers any match with more than one sample, none separates
9acf02f98283, and none converges within a match. E2 on c817691bcd15 stays
within 30 ms of truth from round 18 (30.5 capture minutes) but its interval
spans 150 ms. The capture-minus-truth rows say the delay model holds where
truth removes formation or behaviour; the capture alone sees the delay only
as 1-2 widget pixels mixed with metres of human variation.

## 4a. Ping does not set the delay

The player's hypothesis (2026-10-06): the delay follows the highest ping in
the lobby. Registered as `render-delay-ping-20261006-prediction`; measured by
`prototypes/render_delay_ping.py`.

**The field.** vrfkit's `fields.parquet` holds every player's ping:
group `BombPlayerState.BombPlayerState_C`, field `Ping`, 16 bits in
`value_i64`, in ms, each player state named by its `Subject` field. All ten
players carry it on every development match
([metric:render_delay/ping@9acf02f98283#ping_rows=28586],
[metric:render_delay/ping@c817691bcd15#ping_rows=34888] and
[metric:render_delay/ping@d3dcfb182ab1#ping_rows=21511] rows). The player's
own median reproduces the teammate-lag study's 37, 30 and 35 ms. The replay
layer does not expose it yet.

**Between matches.**

| Match | Delta (ms) | Lobby max | Lobby mean | Own |
|---|---|---|---|---|
| 9acf02f98283 | [metric:render_delay/ping@9acf02f98283#delta=168.2] | [metric:render_delay/ping@9acf02f98283#lobby_max=59.0] | [metric:render_delay/ping@9acf02f98283#lobby_mean=32.5] | [metric:render_delay/ping@9acf02f98283#own_ping=37.0] |
| c817691bcd15 | [metric:render_delay/ping@c817691bcd15#delta=47.0] | [metric:render_delay/ping@c817691bcd15#lobby_max=57.0] | [metric:render_delay/ping@c817691bcd15#lobby_mean=38.1] | [metric:render_delay/ping@c817691bcd15#own_ping=30.0] |
| d3dcfb182ab1 | [metric:render_delay/ping@d3dcfb182ab1#delta=55.3] | [metric:render_delay/ping@d3dcfb182ab1#lobby_max=150.0] | [metric:render_delay/ping@d3dcfb182ab1#lobby_mean=40.2] | [metric:render_delay/ping@d3dcfb182ab1#own_ping=35.0] |

d3dcfb182ab1 has an enemy at 150 ms and a delay within 8 ms of
c817691bcd15's; 9acf02f98283 has c817691bcd15's lobby max and three times
its delay. Three matches cannot fit a law, but one counterexample on each side
breaks this one. Fitting Delta = c + k * max over all 61 rounds gives
k = [metric:render_delay/ping_fit@dev3#k=-0.5]
([metric:render_delay/ping_fit@dev3#k_lo=-0.6] to
[metric:render_delay/ping_fit@dev3#k_hi=-0.397]) and
c = [metric:render_delay/ping_fit@dev3#c=131.1] ms: the wrong sign,
carried by the two contrasts above.

**Within matches.** The lobby's maximum barely moves within a match: its
10th to 90th percentile over rounds spans
[metric:render_delay/ping@9acf02f98283#lobby_max_p10=58.0] to
[metric:render_delay/ping@9acf02f98283#lobby_max_p90=60.0],
[metric:render_delay/ping@c817691bcd15#lobby_max_p10=57.0] to
[metric:render_delay/ping@c817691bcd15#lobby_max_p90=58.0] and
[metric:render_delay/ping@d3dcfb182ab1#lobby_max_p10=150.0] to
[metric:render_delay/ping@d3dcfb182ab1#lobby_max_p90=151.0] ms, so the
within-match test has almost no lever. Spearman rho of per-round Delta on
per-round lobby max: [metric:render_delay/ping@9acf02f98283#rho_max=-0.33]
([metric:render_delay/ping@9acf02f98283#rho_max_lo=-0.638] to
[metric:render_delay/ping@9acf02f98283#rho_max_hi=0.058]),
[metric:render_delay/ping@c817691bcd15#rho_max=-0.184]
([metric:render_delay/ping@c817691bcd15#rho_max_lo=-0.549] to
[metric:render_delay/ping@c817691bcd15#rho_max_hi=0.228]) and
[metric:render_delay/ping@d3dcfb182ab1#rho_max=0.369]
([metric:render_delay/ping@d3dcfb182ab1#rho_max_lo=-0.082] to
[metric:render_delay/ping@d3dcfb182ab1#rho_max_hi=0.731]). Mean and own
ping fare no better; the one interval clear of zero, own ping on
c817691bcd15 ([metric:render_delay/ping@c817691bcd15#rho_own=0.409]),
rests on two late rounds where the player's ping fell from 30 to 29 ms.

**Per player.** A teammate's lag less the player's does not follow that
teammate's ping, round by round (rho
[metric:render_delay/ping@9acf02f98283#mate_rho_ping=-0.095],
[metric:render_delay/ping@c817691bcd15#mate_rho_ping=0.041],
[metric:render_delay/ping@d3dcfb182ab1#mate_rho_ping=0.014]), nor over the
match: 9acf02f98283's 59 ms teammate trails by
[metric:render_delay/ping@9acf02f98283#top_ping_gap=169.4] ms against
[metric:render_delay/ping@9acf02f98283#same_side_gap_min=165.0] to
[metric:render_delay/ping@9acf02f98283#same_side_gap_max=187.8] ms for the
others. Enemies leave one lead open: on both October matches the
highest-ping enemy is drawn latest, by
[metric:render_delay/ping@c817691bcd15#top_ping_gap=92.7] ms
([metric:render_delay/ping@c817691bcd15#top_ping_gap_lo=69.9] to
[metric:render_delay/ping@c817691bcd15#top_ping_gap_hi=123.3]) against
[metric:render_delay/ping@c817691bcd15#same_side_gap_min=39.5] to
[metric:render_delay/ping@c817691bcd15#same_side_gap_max=58.8] ms, and
[metric:render_delay/ping@d3dcfb182ab1#top_ping_gap=69.9] ms
([metric:render_delay/ping@d3dcfb182ab1#top_ping_gap_lo=43.4] to
[metric:render_delay/ping@d3dcfb182ab1#top_ping_gap_hi=90.3]) against
[metric:render_delay/ping@d3dcfb182ab1#same_side_gap_min=30.6] to
[metric:render_delay/ping@d3dcfb182ab1#same_side_gap_max=62.7] ms. Each
rests on 70-160 moving enemy icons, and a 151 ms ping adds about 15 ms, far
less than the ping: a per-player term, if it holds, is small beside the
match's delay.

**The scoreboard reads no ping.** `scoreboard.py` reads K, D, A and credits.
The PING column stands at the table's right edge, inside the stored crop
cache's rectangle; in a 50-frame sample of c817691bcd15's cache every one of
the 40 boards inspected shows it legibly as two digits. The player's own row
reads 24-25 there against the replay's 30 ms, while teammates read within a
few ms of their replay values (by eye), which suggests the board shows the
player's own client-side figure rather than the replicated field. The board
stands open
[metric:render_delay/ping@9acf02f98283#sb_open_s_per_round=24.2],
[metric:render_delay/ping@c817691bcd15#sb_open_s_per_round=31.9] and
[metric:render_delay/ping@d3dcfb182ab1#sb_open_s_per_round=26.2] s per
round. A reader would be one more `BOARD_FIELDS`
entry with its pens measured at the right edge, as credits were; it was not
built, since ping is no witness of the delay.

**What explains 9acf02f98283, then.** Not ping. It differs from the October
matches in build (13.04 against 13.06), capture date and minimap profile
(teammate-lag outcome). A client setting, the build's interpolation or the
small profile's draw path remain the candidates; another 13.04-era
replay-backed capture separates build from date.

## 5. Recommendation

1. **Prior with a band.** `d_hat(remote) = 50 ms`, band `[30, 200] ms`, per
   match, version-stamped as `source = prior`. It recovers the October
   matches and bounds 9acf02f98283; its radius cost is `v_max * d_hi`, 1.5 m,
   inside one icon radius. Every remote belief carries it (section 1).
2. **Flag what the band crosses.** A question whose tolerance the band's
   width times the slot's speed exceeds (the reach cell for a moving player,
   a contact at the 1.5 m limit) reports `delay_band_limited` with the
   attribute, never a silent answer.
3. **No ping-based prior.** Neither the lobby's highest, mean nor the
   player's own ping predicts the delay (section 4a), so the prior does not
   depend on ping, and neither the scoreboard's PING column nor the
   performance-stats RTT (the player's own ping) is worth a reader for this
   purpose. The ribbon's packet-loss field stays untested.
4. **Calibrate from replays where they exist.** A replay-backed capture
   measures its own delay exactly (`prototypes/minimap_lag.py --posthoc`);
   post-match coaching may use it, labelled `source = replay`. Each such
   match also widens the prior's sample, today three matches.
5. **Correct the killfeed first.** For kill-instant questions the killfeed's
   offset and 2 Hz sampling outweigh the remote delay; the X mark's 15 Hz
   death time, where the minimap is drawn, is the cheaper gain.

## 6. ENTITY_STATE changes this implies

- **§2 Exact form.** Add a "Timing" item: a fit keeps `t_render`; the reach
  anchor `t_anchor` is server time, the band's earliest (`t_render - d_hi`);
  `R(t)` is unchanged in form, so a remote fit's region at the self clock
  already holds `v_max * d_hi`. `r_fit` keeps its frame term. The point's
  forward carry `x_now = x + v * d_hat` is a prediction stored apart; the
  "no velocity in the region" rule stands.
- **§4 Per-frame arrays.** No per-slot-frame bytes: the npz header gains a
  delay table per class (`self`, `remote`, `killfeed`, `xmark`, `hud`): `d_hat`,
  `d_lo`, `d_hi` in ms, `source` (`prior`, `replay`, `estimate`) and the
  table's version. `t_anchor`'s meaning changes to the server clock. Estimate
  rows and lane events (`open`, `close`, `relocation`) carry `t_render_ms`
  and `t_server_ms` with its band.
- **§4 Provenance.** A `render-delay` owner (a future `reticle/render_delay.py`,
  declared in `ownership.toml`) produces the per-session table; it is not
  for positions or names. A change to its prior restamps the slot state.
- **§5 Queries.** A query names its clock: client-time queries read
  `t_render`, server-time queries `t_server`; reach features at a kill instant
  place the kill by the killfeed's class offset.
- **§8 Evaluation.** Truth is read per class at server time, as
  replay-truth-0.4.0 already does; slot scoring reports error by speed bin,
  since a still slot carries no delay error.
- **QUESTION_ACCEPTANCE §1.** The duel row's "first seer: contact onset to
  62.5 ms" becomes role, edge distance and the match's delay (section 2).

## 7. What this does not do

- It wires nothing; the delay table, its owner and the slot fields wait for
  ENTITY_STATE step 1.
- It measures no client-time sight: the replay holds server state only.
- Its body model is six points on a cylinder, not the game's hitbox.
- It scores three matches; the prior's band rests on them, and the held-out
  match was not read.
- It builds no ping or network-readout reader and decodes no video; the
  scoreboard sample read 50 stored crops.
