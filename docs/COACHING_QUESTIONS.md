# Coaching questions on truth: which matter, and what fidelity they need

Status: findings, 2026-10-06. Rules live in [AGENTS.md](../AGENTS.md);
commands in [WORKING_MAP.md](WORKING_MAP.md). This answers the player's
direction of 2026-10-06 for [QUESTION_ACCEPTANCE.md](QUESTION_ACCEPTANCE.md):
define the questions that matter from the replay and API data already held,
and test on truth the expectation of 95% or more savings over today's 15 Hz
reading at barely any loss. The code is `prototypes/coaching_questions.py`
(coaching-questions-0.1.0: inventory, decision value, the degradation
sweep, the attention arm, cost) and `prototypes/coaching_belief.py`
(coaching-belief-0.1.0: reachable sets, map control, holes, priors).
Predictions CQ0-CQ16 and their revisions sit in the store's
`notes/predictions.jsonl` (task `coaching-questions-20261006`), registered
before each run. Nothing here reads the held-out match bd7efa02, decodes
video or fits a threshold on an evaluation set; nothing is wired.

## Conclusion

- **The player's 95% expectation holds on truth for the questions that
  matter, and the 1 ms stretch goal is within reach.** The six
  highest-stake questions (trades, the opening duel, map control, the buy,
  blind deaths, execute commitment) need no teammate position at all, or
  keep at least 0.95 agreement (map control: within a hundredth) at a
  twentieth of today's slot reads. The live-phase local
  gate with 0.5 Hz base reads (`Lp0.5-250w5`) reads
  [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#share=0.0484] of
  today's slot reads and agrees with the full-rate truth on every sight
  question at 0.95 or more; its implied cost is about a third of a
  millisecond per captured frame (section 6). The loss falls on strict
  timing of team executes and rotations, not on whether they happened.
- **Event-only questions dominate the value.** Being traded and winning the
  opening duel carry most of the measurable round-win stake; the
  killfeed and economy answer them without the minimap.
- **Damage-only fights matter, and the combat report sees a fifth of
  them.** A team-round's net damage in kill-free bouts moves round win; the
  player's own report covers his bouts only.
- **Enemy-side questions are beliefs, and the belief is short-lived.**
  The drawn enemy alone recovers a third of enemy executes and almost no
  enemy rotations. A last-seen reachable set holds him about 97% of the
  time but covers the map within about 14 s; pruning by the team's vision
  barely delays that, and habits from earlier rounds predict little
  (section 4).
- **Map control and holes carry value at base-rate cost.** The team's
  control share tracks round wins, deaths come faster through open flanks,
  and both need only 0.5 Hz teammate poses.
- **A human's attention budget is not a reader's.** One focus window loses
  the overlapping fight; every window at 5 Hz is cheaper than two at 15 Hz
  (section 5).
- **Peeker against holder and corner distance need the onset read, and
  show no measured edge.** The lone mover wins about half his kill duels;
  the far-from-corner side does not win more (sections 2.2-2.3).


## 1. The data held

`coaching_questions.py inventory` counted every source
([metric:coaching_questions/inventory/replays@store#layers_read=17] replay
layers read; the held-out bd7efa02 is dropped by name before any file opens).

| Source | Holds | Size | Answers | Cannot answer |
|---|---|---|---|---|
| Parsed replays (replay layer, truth episodes `analysis/episodes/truth/`) | all ten players at server-tick rate, view, life, every damage call, kills, plants, casts, ability actors | [metric:coaching_questions/inventory/replays@store#rounds=345] rounds, [metric:coaching_questions/inventory/replays@store#kill_acts=2579] kills, [metric:coaching_questions/inventory/replays@store#duels=3425] duels, [metric:coaching_questions/inventory/replays@store#contacts=6784] contacts, [metric:coaching_questions/inventory/replays@store#executes=382] executes, [metric:coaching_questions/inventory/replays@store#rotations=809] rotations, [metric:coaching_questions/inventory/replays@store#lurks=207] lurks, [metric:coaching_questions/inventory/replays@store#retakes=52] retakes | every continuous-time question: sight, contacts, damage-only fights, executes, rotations, lurks, retakes, spacing at any instant; and every fidelity test (section 3) | rank-band baselines (one player's lobbies); small n per round-level question (two perspectives per round) |
| Riot match records (`external/riot/`) | the 23 captured matches: kills with every living player's position and view, economy, plants | [metric:coaching_questions/inventory/riot@store#records=23] records, [metric:coaching_questions/inventory/riot@store#rounds=495] rounds, [metric:coaching_questions/inventory/riot@store#kills=3660] kills | kill-instant questions on the captured matches; reader scoring | positions between kills; they evaluate and never fit (EXTERNAL_GROUND_TRUTH use policy); not used for value here |
| Riot PD v1 (`external/riot-pd-v1`) | the fetch kit's records of the player's accounts | [metric:coaching_questions/inventory/riot_pd_v1@store#records=16] records, [metric:coaching_questions/inventory/riot_pd_v1@store#in_ladder=15] also in the ladder | the same as the ladder for those matches | nothing new: a cross-check of the ladder's relay |
| Ladder (`external/ladder`, HenrikDev v4, ladder-parse-0.2.0) | the player's competitive history: kills with every living player's position, rounds, plants, economy | [metric:coaching_questions/inventory/ladder@store#matches=170] matches ([metric:coaching_questions/inventory/ladder@store#holdout=30] flagged holdout, left out here), [metric:coaching_questions/inventory/ladder@store#rounds=3525] rounds, [metric:coaching_questions/inventory/ladder@store#kills=26204] kills, [metric:coaching_questions/inventory/ladder@store#positions=165544] kill-instant positions | kill-instant and economy questions with large n: opening, trades, spacing at death, buys | anything between kills: sight, damage-only fights, executes, rotations |
| CS (`external/cs`) | ESTA demos (trajectories), Kaggle matchmaking damage | [metric:coaching_questions/inventory/cs@store#esta_demos=100] demos, [metric:coaching_questions/inventory/cs@store#esta.rounds=2570] rounds; [metric:coaching_questions/inventory/cs@store#kaggle_mm.damage=955466] damage rows | shape only (COACHING_DECISION_VALUE §3): trade decay with spacing, damage before duels | any VALORANT value; not used here |
| valorant-api (`external/valorant-api`) | maps, callouts, agents, weapons | [metric:coaching_questions/inventory/valorant_api@store#maps_with_callouts=16] maps with callouts | region labels, spawns | nothing measured |
| Coaching work already done | win probability (`winprob_reference`), engagement reach (REACH1-6), player profile | COACHING_DECISION_VALUE §9 | that positions add about a thousandth of a nat to fight outcomes; reach matters most for trades | causal effects; teammates' choices |

## 2. The catalogue, ranked

Each question's **decision value** is the round-win difference between its
two answers, stratified (deaths by living players on each side and the
plant; round questions by side), with a 1000-draw match bootstrap for the
95% interval. Its **stake** is the absolute difference times its instances
per team-match; **stake lo** uses the interval's end nearer 0, so a
question whose interval spans 0 has stake lo 0. A difference is an
association in the player's lobbies, not a causal effect: a traded death
may mark a team already winning. The ladder (140 non-held-out matches,
[metric:coaching_questions/value/meta@pooled#ladder.rounds=2891] rounds)
answers kill-instant and economy questions; the replays
([metric:coaching_questions/value/meta@pooled#replays.matches=17] matches,
[metric:coaching_questions/value/meta@pooled#replays.rounds=345] rounds)
answer everything continuous, with small n per round-level question.

"Observable" names what a capture can read; "fidelity" names the cheapest
schedule of section 3 that keeps the answer at 0.95 agreement with the
full-rate reader (T1).

| Rank | Question | Decision it informs | Computed from truth | Difference [95%] (n) | Per team-match | Stake [lo] | Observable from a capture | Fidelity it needs |
|---|---|---|---|---|---|---|---|---|
| 1 | Traded within 5 s | stay in trade reach of the entry; swing to trade | a death's killer dies within 5 s to the victim's team (truth `trade` episodes; ladder kills) | [metric:coaching_questions/value/ladder/traded_death@pooled#diff=0.2162] [[metric:coaching_questions/value/ladder/traded_death@pooled#ci_lo=0.1944], [metric:coaching_questions/value/ladder/traded_death@pooled#ci_hi=0.2381]] ([metric:coaching_questions/value/ladder/traded_death@pooled#n=21491]); replays [metric:coaching_questions/value/replays/traded_death@pooled#diff=0.1846] | [metric:coaching_questions/value/ladder/traded_death@pooled#per_team_match=76.754] deaths | [metric:coaching_questions/value/ladder/traded_death@pooled#stake=16.594] [[metric:coaching_questions/value/ladder/traded_death@pooled#stake_lo=14.921]] | team side, both teams' deaths: the killfeed | none for the label; trader sight and distance agree at [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.trade_C=0.9853] under `Lp0.25-250w5` |
| 2 | Opening duel won | take or deny the first fight; who peeks first | the round's first kill's team | [metric:coaching_questions/value/ladder/opening_kill@pooled#diff=0.3553] [[metric:coaching_questions/value/ladder/opening_kill@pooled#ci_lo=0.3203], [metric:coaching_questions/value/ladder/opening_kill@pooled#ci_hi=0.3897]] ([metric:coaching_questions/value/ladder/opening_kill@pooled#n=5782]) | [metric:coaching_questions/value/ladder/opening_kill@pooled#per_team_match=20.65] rounds | [metric:coaching_questions/value/ladder/opening_kill@pooled#stake=7.337] [[metric:coaching_questions/value/ladder/opening_kill@pooled#stake_lo=6.614]] | the killfeed; its first seer needs the drawn enemy and the teammate (the seer wins [metric:coaching_questions/value/extra/opening_first_seer@pooled#seer_won=0.8043], n [metric:coaching_questions/value/extra/opening_first_seer@pooled#n=46], too small for an interval) | label: none; first seer [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.opening_first_seer=0.9754] under `Lp0.25-250w5` |
| 3 | Map control at 20 s | hold space or concede it; where to send the next player | the share of the map no living enemy's vision-pruned belief holds, 20 s after buy end, top against bottom third within side (section 4.3) | [metric:coaching_belief/control_value@pooled17#diff=0.2348] (interval [metric:coaching_belief/control_value@pooled17#ci_lo=0.1362] to [metric:coaching_belief/control_value@pooled17#ci_hi=0.3346]; n [metric:coaching_belief/control_value@pooled17#n=460]) | [metric:coaching_questions/value/replays/first_sight_support@pooled#per_team_match=20.294] rounds | 4.76 [2.76] | team side: teammates' position and facing, and the drawn enemies | 0.5 Hz teammate poses (section 4.4) |
| 4 | Full buy | buy, save or force with the team | team loadout at buy end (ladder economy) | [metric:coaching_questions/value/ladder/full_buy@pooled#diff=0.1793] [[metric:coaching_questions/value/ladder/full_buy@pooled#ci_lo=0.1542], [metric:coaching_questions/value/ladder/full_buy@pooled#ci_hi=0.2039]] ([metric:coaching_questions/value/ladder/full_buy@pooled#n=5230]) | [metric:coaching_questions/value/ladder/full_buy@pooled#per_team_match=18.679] rounds | [metric:coaching_questions/value/ladder/full_buy@pooled#stake=3.349] [[metric:coaching_questions/value/ladder/full_buy@pooled#stake_lo=2.88]] | the scoreboard and HUD; no minimap | none |
| 5 | Blind death | where to look; when to fall back | no living teammate saw the killer in the 2 s before the death | [metric:coaching_questions/value/replays/blind_death@pooled#diff=-0.0424] [[metric:coaching_questions/value/replays/blind_death@pooled#ci_lo=-0.0805], [metric:coaching_questions/value/replays/blind_death@pooled#ci_hi=0.0165]] ([metric:coaching_questions/value/replays/blind_death@pooled#n=2571]); traded [metric:coaching_questions/value/replays/blind_death@pooled#traded_a1=0.1236] against [metric:coaching_questions/value/replays/blind_death@pooled#traded_a0=0.1912] | [metric:coaching_questions/value/replays/blind_death@pooled#per_team_match=75.618] deaths | [metric:coaching_questions/value/replays/blind_death@pooled#stake=3.206] [0] | the drawn enemy and the killfeed: the gate's own cue | none beyond the per-frame cue |
| 6 | Execute commitment | commit three or more to the site, or not at all | the attack round's largest attempt committed at least 3 against at most 1 (truth `execute`) | [metric:coaching_questions/value/replays/execute_commit3@pooled#diff=0.3807] [[metric:coaching_questions/value/replays/execute_commit3@pooled#ci_lo=0.2475], [metric:coaching_questions/value/replays/execute_commit3@pooled#ci_hi=0.5084]] ([metric:coaching_questions/value/replays/execute_commit3@pooled#n=242]) | [metric:coaching_questions/value/replays/execute_commit3@pooled#per_team_match=7.118] attack rounds | [metric:coaching_questions/value/replays/execute_commit3@pooled#stake=2.71] [[metric:coaching_questions/value/replays/execute_commit3@pooled#stake_lo=1.762]] | team side when attacking; teammates' regions | the committed band at [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17-exec#vs_T1.execute_commit_band=0.9536] under `Lp0.5-250w5` |
| 7 | Damage-only balance | take or avoid chip fights | a team-round's net damage in kill-free bouts, top against bottom tercile within side | [metric:coaching_questions/value/replays/dmg_only_net_top@pooled#diff=0.1644] [[metric:coaching_questions/value/replays/dmg_only_net_top@pooled#ci_lo=0.0453], [metric:coaching_questions/value/replays/dmg_only_net_top@pooled#ci_hi=0.2817]] ([metric:coaching_questions/value/replays/dmg_only_net_top@pooled#n=460]) | [metric:coaching_questions/value/replays/dmg_only_net_top@pooled#per_team_match=13.529] team-rounds | [metric:coaching_questions/value/replays/dmg_only_net_top@pooled#stake=2.224] [[metric:coaching_questions/value/replays/dmg_only_net_top@pooled#stake_lo=0.613]] | the player's own bouts only, from the combat report (section 2.1) | none: no minimap |
| 8 | Spacing at death | stand within 5 m of a teammate when contact is likely | the nearest living teammate's distance at the death, at most 5 m against over 10 m | ladder [metric:coaching_questions/value/ladder/spacing_near@pooled#diff=-0.0019] [[metric:coaching_questions/value/ladder/spacing_near@pooled#ci_lo=-0.0212], [metric:coaching_questions/value/ladder/spacing_near@pooled#ci_hi=0.0166]] ([metric:coaching_questions/value/ladder/spacing_near@pooled#n=15055]); its value runs through trades: traded [metric:coaching_questions/value/ladder/spacing_near@pooled#traded_a1=0.4126] against [metric:coaching_questions/value/ladder/spacing_near@pooled#traded_a0=0.1521] | [metric:coaching_questions/value/ladder/spacing_near@pooled#per_team_match=53.768] deaths | [metric:coaching_questions/value/replays/spacing_near@pooled#stake=1.3] (replays) [0] | teammates' positions at the death | 5 m boolean [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.spacing_5m=0.9733] under `Lp0.25-250w5`; the bucket needs `Lp0.5-250w5` ([metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.spacing_death=0.9506]) |
| 9 | Own lurk present | send a lurker or not | an attack round holds a capturing-team lurk episode | [metric:coaching_questions/value/replays/lurk_present@pooled#diff=0.088] [[metric:coaching_questions/value/replays/lurk_present@pooled#ci_lo=-0.0077], [metric:coaching_questions/value/replays/lurk_present@pooled#ci_hi=0.1991]] ([metric:coaching_questions/value/replays/lurk_present@pooled#n=345]) | [metric:coaching_questions/value/replays/lurk_present@pooled#per_team_match=10.147] | [metric:coaching_questions/value/replays/lurk_present@pooled#stake=0.893] [0] | team side; teammates' super-regions | strict [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.lurk_C=0.9481] under `Lp0.5-250w5`, F1 [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.lurk_C.f1=0.9734] |
| 10 | First-sight support | have a teammate within 10 m when first seen | a living teammate within 10 m of the first capturing-team player an enemy sees | [metric:coaching_questions/value/replays/first_sight_support@pooled#diff=0.0345] [[metric:coaching_questions/value/replays/first_sight_support@pooled#ci_lo=-0.0459], [metric:coaching_questions/value/replays/first_sight_support@pooled#ci_hi=0.114]] ([metric:coaching_questions/value/replays/first_sight_support@pooled#n=690]) | [metric:coaching_questions/value/replays/first_sight_support@pooled#per_team_match=20.294] | [metric:coaching_questions/value/replays/first_sight_support@pooled#stake=0.7] [0] | teammates' positions at a drawn enemy's first sight | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.first_sight_support=0.9638] under `Lp0.5-250w5` |
| 11 | Defender rotation | rotate early or hold | a defence round holds a capturing-team rotation episode | [metric:coaching_questions/value/replays/defender_rotation@pooled#diff=-0.0633] [[metric:coaching_questions/value/replays/defender_rotation@pooled#ci_lo=-0.2078], [metric:coaching_questions/value/replays/defender_rotation@pooled#ci_hi=0.1362]] ([metric:coaching_questions/value/replays/defender_rotation@pooled#n=345]) | [metric:coaching_questions/value/replays/defender_rotation@pooled#per_team_match=10.147] | [metric:coaching_questions/value/replays/defender_rotation@pooled#stake=0.642] [0] | team side; teammates' super-regions | strict [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.rotation_C=0.984] under `Lp1-250w5`; F1 [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.rotation_C.f1=0.974] under `Lp0.5-250w5` |

Below the ten: buy coordination
([metric:coaching_questions/value/ladder/buy_sync@pooled#diff=0.0303],
interval [metric:coaching_questions/value/ladder/buy_sync@pooled#ci_lo=-0.0438]
to [metric:coaching_questions/value/ladder/buy_sync@pooled#ci_hi=0.1072];
only [metric:coaching_questions/value/ladder/buy_sync@pooled#n_a0=213]
split buys) and refragging into a teammate's killer's sightline
([metric:coaching_questions/value/replays/refrag_sight@pooled#diff=-0.0014],
though it lifts the trade share from
[metric:coaching_questions/value/replays/refrag_sight@pooled#traded_a0=0.1654]
to [metric:coaching_questions/value/replays/refrag_sight@pooled#traded_a1=0.462]).
Ranks 8-11 have intervals spanning 0: their n is too small on 17 replays,
or the effect runs through another question (spacing and refragging
through trades). Context the ranking leaves out: a planted round goes to
the attack
[metric:coaching_questions/value/extra/plant@pooled#attack_win_after_plant=0.708]
of [metric:coaching_questions/value/extra/plant@pooled#planted_rounds=1873]
times; a two-player lead converts
[metric:coaching_questions/value/extra/two_player_lead@pooled#converted=0.8832]
of [metric:coaching_questions/value/extra/two_player_lead@pooled#n=2826]
times; a duelist who took 30 damage or more in the 10 s before a kill duel
wins it [metric:coaching_questions/value/extra/chip@pooled#won_chipped=0.3535]
of [metric:coaching_questions/value/extra/chip@pooled#n_chipped=611] times
against [metric:coaching_questions/value/extra/chip@pooled#won_clean=0.5197];
the [metric:coaching_questions/value/extra/retake@pooled#n=52] retakes are
too few to value.

### 2.1 What the combat report gives

Damage-only fights are frequent:
[metric:coaching_questions/value/meta@pooled#replays.team_rounds_with_dmg_only=604]
of [metric:coaching_questions/value/meta@pooled#replays.team_rounds=690]
team-rounds hold one. Per engagement the report gives, for each enemy the
player fought in the round, damage both ways with its hit split and a
KILLED flag [domain:combat_report/panel-layout]; it freezes at his death
[domain:combat_report/frozen-after-death] and closes as a round summary
[domain:combat_report/round-summary]. It cannot give a bout's time, split
a row that merges several bouts with one enemy, or see any teammate's
fight. On the
[metric:coaching_questions/value/extra/combat_report@pooled#matches=11]
replays holding the player, he fought
[metric:coaching_questions/value/extra/combat_report@pooled#player_kill_free_bouts=104]
of his team's
[metric:coaching_questions/value/extra/combat_report@pooled#team_kill_free_bouts=577]
kill-free bouts; of his
[metric:coaching_questions/value/extra/combat_report@pooled#player_rows=391]
(round, enemy) rows,
[metric:coaching_questions/value/extra/combat_report@pooled#player_rows_merging_bouts=34]
merge bouts and
[metric:coaching_questions/value/extra/combat_report@pooled#player_rows_kill_free_only=70]
hold only kill-free bouts. Question 6 is therefore answerable for the
player's own share of the balance and for no one else's.

### 2.2 Peeker against holder

The player's point (2026-10-06): lag compensation favours the shooter, so
"who saw first" is often "who was swinging"; rank the duel by who moved
into the angle. CQ17 classes each participant of a kill duel with sight as
a peeker when his mean horizontal speed over the half second about the
contact onset is at least 2 m/s, else a holder.

- **On truth the mover does not win more.** Of
  [metric:coaching_questions/value/extra/peek@pooled17-attn#duels=2468]
  kill duels with sight, both participants move in
  [metric:coaching_questions/value/extra/peek@pooled17-attn#both_peek=0.5235]
  and exactly one in
  [metric:coaching_questions/value/extra/peek@pooled17-attn#one_peeker=0.4417];
  in those [metric:coaching_questions/value/extra/peek@pooled17-attn#n_one_peeker=1090]
  the peeker wins
  [metric:coaching_questions/value/extra/peek@pooled17-attn#peeker_won=0.5101]
  (interval [metric:coaching_questions/value/extra/peek@pooled17-attn#ci_lo=0.4834]
  to [metric:coaching_questions/value/extra/peek@pooled17-attn#ci_hi=0.5356]).
  Speed is a coarse proxy for a peek: it cannot tell a swing from a
  reposition, and moving inaccuracy may cancel the timing gain. The
  render-delay study owns the timing model; this result does not test it.
- **The state needs gate fidelity, not less.** Peeker state agrees with T1
  at [metric:coaching_questions/degrade/B1@pooled17-attn#vs_T1.peek_C=0.7024]
  under 1 Hz base reads (interpolation over a second hides a half-second
  swing) and at
  [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17-attn#vs_T1.peek_C=0.9651]
  under `Lp0.5-250w5`, whose window opens with the drawn enemy. The
  enemy's swing before he is drawn is censored: the pair's states agree
  T1 against truth at
  [metric:coaching_questions/degrade/T1@pooled17-attn#vs_T0.peek_pair=0.859].

### 2.3 Distance to the occluding corner

The player's point (2026-10-06): the player nearer the occluding corner
sees later, modestly, and a long angle is peeked with a wide swing. CQ18
(revision 1) measures it at each kill duel's contact onset: for each
participant, rays from his eye turned 2, 4, 8 and 16 degrees off the line
to the other; his corner distance is the first hit of the smallest-angle
ray blocked within the pair's distance and within 1 m of the sightline.
The far side is the participant farther from his corner by 50 cm or more.

- **A corner is found for both on**
  [metric:coaching_questions/value/extra/corner@pooled17-corner#both_found=0.9433]
  of [metric:coaching_questions/value/extra/corner@pooled17-corner#duels=2468]
  kill duels with sight.
- **The far side does not win more.** It wins
  [metric:coaching_questions/value/extra/corner@pooled17-corner#far_won=0.4793]
  of [metric:coaching_questions/value/extra/corner@pooled17-corner#n_far_near=2218];
  stratified by both participants' peek states the difference is
  [metric:coaching_questions/value/extra/corner@pooled17-corner#far_vs_near.diff=-0.0389]
  (interval [metric:coaching_questions/value/extra/corner@pooled17-corner#far_vs_near.ci_lo=-0.0777]
  to [metric:coaching_questions/value/extra/corner@pooled17-corner#far_vs_near.ci_hi=0.003]).
- **Wide against tight is not measurable with this proxy.** With 2 m as
  the line,
  [metric:coaching_questions/value/extra/corner@pooled17-corner#wide_vs_tight.n_a1=1365]
  of [metric:coaching_questions/value/extra/corner@pooled17-corner#wide_vs_tight.n=1426]
  long-angle peekers count as wide, and so do
  [metric:coaching_questions/value/extra/corner@pooled17-corner#player_wide_share=0.9457]
  of the player's
  [metric:coaching_questions/value/extra/corner@pooled17-corner#player_long_peeks=92];
  the 61 tight ones are too few (difference
  [metric:coaching_questions/value/extra/corner@pooled17-corner#wide_vs_tight.diff=-0.0719],
  interval [metric:coaching_questions/value/extra/corner@pooled17-corner#wide_vs_tight.ci_lo=-0.185]
  to [metric:coaching_questions/value/extra/corner@pooled17-corner#wide_vs_tight.ci_hi=0.0307]).
  The ray proxy finds the nearest blocking surface, which on a long angle
  is often not the corner the peek rounds; the corner the peeker swung
  around is better found from his path before the onset, which a capture
  holds only for teammates. The question stays in the catalogue with its
  value unmeasured.
- **Its fidelity need is position at the onset**, as the player said, but
  the onset position must be read, not interpolated: the far-or-near
  label agrees with T1 at
  [metric:coaching_questions/degrade/B1@pooled17-corner#vs_T1.corner_C=0.8259]
  under 1 Hz base reads and at
  [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17-corner#vs_T1.corner_C=0.987]
  under `Lp0.5-250w5`, whose window holds the onset.

## 3. The 95% hypothesis on truth

The player's expectation, registered as CQ8 before the sweep: some
schedule reading at most 0.05 of today's 15 Hz slot reads agrees with the
full-rate reader (T1) on at least 0.95 of instances of every one of the
top five questions. The sweep degrades the truth timeline and asks what
each question loses.

### 3.1 The arms

Every arm runs the same `episodes.derive_episodes` (episodes-0.3.0, its
`PARAMS`) on the same rounds, and `answers()` reads the catalogue's answers
from its episodes and its timeline. Each replay is scored twice, once with
each team as the capturing team.

- **T0**, the truth (`episodes.from_replay_layer`). Rebuilt here, it equals
  the stored episodes' kind counts on all 17 replays (CQ0a).
- **T1**, the field limit: T0 with each enemy known only while drawn,
  meaning a living capturing-team player saw him (`episodes.sight`, 16 Hz)
  within the last P = 1 s, at his true position. Life comes from the
  lifecycle, never from whether a position was read, and each round carries
  its side, as a capture knows it. T1 reads teammates at full rate, so it is
  today's 15 Hz reader with perfect reading.
- **Degraded arms**: T1 with each capturing-team slot known only at the
  frames a schedule reads, interpolated between reads (the analysis runs
  after the round, so the next read is known) and the last read held to the
  life's end.
  - *Base* reads every living slot at b Hz, phase-locked to the round's
    start (`B<b>`), or only from buy end to round end (`Lp...`, post hoc).
  - *Gate* windows read at wr Hz on the 15 Hz frame grid. The window opens
    `lead` ms before an enemy is drawn: a retroactive read of buffered
    frames, which offline analysis has. The **global** gate (`G`) reads every
    living teammate while any enemy is drawn; the **local** gate (`L`) reads
    slot s while a drawn enemy is seen by s or stands within 20 m of him.
  - *Region-level* coarse reads (`...r`) move each base read's x, y to the
    centre of the callout volume holding it.
- **Read share**: slot reads over 15 Hz times the living capturing-team
  slot-time from round start to the next round's start. The gate's
  red-pixel test runs on every frame and is counted apart; its cost is the
  QA plan's B10. The frame share (frames with any slot read) is reported
  beside it, for a reader whose cost is per frame rather than per slot.

**Agreement.** Against T1 (what the rate costs) and against T0 (end to
end). An instant question agrees when its answer is equal (spacing by
bucket: under 5, 5-10, 10-20, 20 m and over; the 5 m boolean apart). An
episode question is scored strictly: matched one to one (contacts by pair
and overlap, duels by kill event, trades by their two kills, executes by
round and site, rotations by rotator, round, origin and destination, lurks
by lurker and round), and a match counts only with equal attributes
(executes: committed count, result and entry spread within 1 s; rotations:
start within 1 s; contacts: onset within 125 ms and the first seer's team;
duels: the first seer's team; trades: the trader's sight and distance
bucket; engagements: kills and deaths per team). Strict agreement is that
count over truth plus arm instances less the matched; detection F1 is given
beside it.


### 3.2 Results

The sweep ran on 3 development replays first, then on all 17 (34
perspectives); the post hoc `Lp` arms, chosen after the development run,
were confirmed on the 14 replays the choice never saw (CQ9). Agreement
with T1, strict:

| Arm | Slot share | Frame share | first seer | 5 m | bucket | support | contacts | duels | trades | executes | rotations | lurks |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `B0.5` | [metric:coaching_questions/degrade/B0.5@pooled17#share=0.0329] | [metric:coaching_questions/degrade/B0.5@pooled17#frame_share=0.0337] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.opening_first_seer=0.7254] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.spacing_5m=0.9275] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.spacing_death=0.8269] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.first_sight_support=0.6783] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.contact_C=0.511] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.duel_C=0.7503] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.trade_C=0.9032] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.execute_C=0.849] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.rotation_C=0.908] | [metric:coaching_questions/degrade/B0.5@pooled17#vs_T1.lurk_C=0.9395] |
| `B1` | [metric:coaching_questions/degrade/B1@pooled17#share=0.0661] | [metric:coaching_questions/degrade/B1@pooled17#frame_share=0.067] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.opening_first_seer=0.8642] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.spacing_5m=0.9608] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.spacing_death=0.9119] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.first_sight_support=0.8232] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.contact_C=0.7198] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.duel_C=0.8834] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.trade_C=0.9558] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.execute_C=0.9219] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.rotation_C=0.9889] | [metric:coaching_questions/degrade/B1@pooled17#vs_T1.lurk_C=0.9952] |
| `B1r` | [metric:coaching_questions/degrade/B1r@pooled17#share=0.0661] | [metric:coaching_questions/degrade/B1r@pooled17#frame_share=0.067] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.opening_first_seer=0.4566] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.spacing_5m=0.7819] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.spacing_death=0.5937] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.first_sight_support=0.3899] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.contact_C=0.2436] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.duel_C=0.4579] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.trade_C=0.5853] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.execute_C=0.8538] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.rotation_C=0.9489] | [metric:coaching_questions/degrade/B1r@pooled17#vs_T1.lurk_C=0.9159] |
| `Lp0.25-250w5` | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#share=0.0399] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#frame_share=0.1007] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.opening_first_seer=0.9754] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.spacing_5m=0.9733] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.spacing_death=0.9341] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.first_sight_support=0.942] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.contact_C=0.9426] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.duel_C=0.9802] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.trade_C=0.9853] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.execute_C=0.8364] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.rotation_C=0.8026] | [metric:coaching_questions/degrade/Lp0.25-250w5@pooled17#vs_T1.lurk_C=0.9028] |
| `Lp0.5-250w5` | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#share=0.0484] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#frame_share=0.1095] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.opening_first_seer=0.9769] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.spacing_5m=0.9742] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.spacing_death=0.9506] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.first_sight_support=0.9638] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.contact_C=0.9514] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.duel_C=0.9814] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.trade_C=0.9853] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.execute_C=0.9191] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.rotation_C=0.9239] | [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.lurk_C=0.9481] |
| `Lp1-250w5` | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#share=0.0652] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#frame_share=0.127] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.opening_first_seer=0.9783] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.spacing_5m=0.9777] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.spacing_death=0.9631] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.first_sight_support=0.9754] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.contact_C=0.9589] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.duel_C=0.983] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.trade_C=0.9916] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.execute_C=0.9479] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.rotation_C=0.984] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17#vs_T1.lurk_C=0.9904] |
| `L1-250w5` | [metric:coaching_questions/degrade/L1-250w5@pooled17#share=0.095] | [metric:coaching_questions/degrade/L1-250w5@pooled17#frame_share=0.1519] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.opening_first_seer=0.9798] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.spacing_5m=0.9777] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.spacing_death=0.9622] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.first_sight_support=0.9783] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.contact_C=0.9601] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.duel_C=0.9827] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.trade_C=0.9874] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.execute_C=0.9506] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.rotation_C=0.9889] | [metric:coaching_questions/degrade/L1-250w5@pooled17#vs_T1.lurk_C=0.9905] |
| `L1-0` | [metric:coaching_questions/degrade/L1-0@pooled17#share=0.1387] | [metric:coaching_questions/degrade/L1-0@pooled17#frame_share=0.2409] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.opening_first_seer=0.9942] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.spacing_5m=0.9818] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.spacing_death=0.9693] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.first_sight_support=0.9797] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.contact_C=0.9665] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.duel_C=0.9937] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.trade_C=0.9853] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.execute_C=0.9557] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.rotation_C=0.9889] | [metric:coaching_questions/degrade/L1-0@pooled17#vs_T1.lurk_C=0.9904] |
| `G1-0` | [metric:coaching_questions/degrade/G1-0@pooled17#share=0.2584] | [metric:coaching_questions/degrade/G1-0@pooled17#frame_share=0.2859] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.opening_first_seer=0.9957] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.spacing_5m=0.9853] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.spacing_death=0.9786] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.first_sight_support=0.9942] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.contact_C=0.9896] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.duel_C=0.9953] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.trade_C=0.9916] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.execute_C=0.9634] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.rotation_C=0.9901] | [metric:coaching_questions/degrade/G1-0@pooled17#vs_T1.lurk_C=0.9952] |

F1 beside strict, Lp0.5-250w5: executes [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.execute_C.f1=0.9934], rotations [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.rotation_C.f1=0.974], lurks [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.lurk_C.f1=0.9734], contacts [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17#vs_T1.contact_C.f1=0.9885]

What the table says:

- **Base reads alone fail the sight questions.** At 1 Hz (`B1`, a
  fifteenth of today's reads) contacts agree at
  [metric:coaching_questions/degrade/B1@pooled17#vs_T1.contact_C=0.7198]
  and the opening duel's first seer at
  [metric:coaching_questions/degrade/B1@pooled17#vs_T1.opening_first_seer=0.8642]:
  sight needs the teammate's pose at the moment, which interpolation over
  a second misses. Region-level coarse reads (`B1r`) are worse
  everywhere: a callout volume's centre is too far from the player for
  sight or spacing.
- **A gate opened by the drawn enemy restores them cheaply.** The local
  gate reads only the slots that see a drawn enemy or stand within 20 m
  of one; with 250 ms of buffered frames and 5 Hz inside the window, its
  live-phase variants keep every sight question at 0.95 or more from
  `Lp0.5-250w5` on, at under a twentieth of today's reads.
- **The residual loss is strict timing of team movement.** Under
  `Lp0.5-250w5`, executes, rotations and lurks are detected (F1 at or above
  0.97) but their start time or committed count misses the 1 s tolerance
  on 5-8% of them; `Lp1-250w5` closes most of the gap at
  [metric:coaching_questions/degrade/Lp1-250w5@pooled17#share=0.0652] of
  today's reads. The valued execute answer, the committed band, holds at
  [metric:coaching_questions/degrade/Lp0.5-250w5@pooled17-exec#vs_T1.execute_commit_band=0.9536].
- **The lead buys little.** From 0 to 1000 ms of buffered frames, local
  gate contacts rise by about 0.02 and executes by about 0.01 (CQ4a failed
  narrowly); the lead's main cost is reads.
- **The confirmation replays reproduce it.** On the 14 replays the post
  hoc choice never saw, `Lp0.5-250w5` reads
  [metric:coaching_questions/degrade/Lp0.5-250w5@confirm14#share=0.0481]
  and `Lp1-250w5`
  [metric:coaching_questions/degrade/Lp1-250w5@confirm14#share=0.0649],
  with the same pattern (CQ9a-c held).

**Censoring is the larger loss, and no rate recovers it.** T1 against the
truth T0: the opening duel's first seer agrees at
[metric:coaching_questions/degrade/T1@pooled17#vs_T0.opening_first_seer=0.9408]
(an enemy who sees first is drawn only if another teammate sees him),
contacts strict at
[metric:coaching_questions/degrade/T1@pooled17#vs_T0.contact_C=0.9041]
(F1 [metric:coaching_questions/degrade/T1@pooled17#vs_T0.contact_C.f1=0.9722]),
trades at [metric:coaching_questions/degrade/T1@pooled17#vs_T0.trade_C=0.9221];
team executes, rotations and lurks at 0.99 or more. Enemy executes agree
at [metric:coaching_questions/degrade/T1@pooled17#vs_T0.execute_E=0.3949],
enemy rotations at
[metric:coaching_questions/degrade/T1@pooled17#vs_T0.rotation_E=0.0164]
and enemy lurks at
[metric:coaching_questions/degrade/T1@pooled17#vs_T0.lurk_E=0.2383]: they
are beliefs (section 4). Round results agree at
[metric:coaching_questions/degrade/T1@pooled17#vs_T0.round_result=0.9797]
only because the replay layer keeps two departed players alive (section 9).

### 3.3 Verdict on the 95% claim

**It holds for the questions that matter.** Of the top six, three need no
teammate position (trades as labels, the opening duel's winner, the buy),
one needs only the drawn enemy the gate's cue reads on every frame (blind
deaths), map control needs teammate poses at 0.5 Hz (its share moves by
0.0099 on average, section 4.4; it was added after CQ8 was registered and
is not scored as agreement), and execute commitment holds its band at
0.954 under `Lp0.5-250w5` at a slot share of 0.048. Every position-dependent question
in the top ten holds 0.95 strict under the same arm except the strict
timing of team executes, rotations and lurks, which hold as detections and
need `Lp1-250w5` (0.065) for timing. The claim fails for a schedule
without a gate: no base-only arm at 0.05 or less holds the sight
questions (CQ8b).

## 4. Beliefs about the unseen enemy

The player's model of attention (2026-10-06): an unseen enemy is held as
his last-seen position plus a reachable set that grows with time, pruned by
what the team watches, and as priors from earlier rounds; once the set
covers the map the belief is "unknown". `coaching_belief.py` measures each
on truth, from the capturing team's side, on the 17 replays.

**The instrument.** Each map's 3D sightline table gives walkable cells a
metre apart, their walk edges and cell-to-cell visibility. Two faults
surfaced on development data before any registered figure was read, and
both are registered revisions: the table carries no jump-up or drop edges
(revision 2 adds them within 1.5 m in plan, up to the game's jump height
[domain:game_data/character-jump] both ways, drops of up to 6 m one way),
and it leaves out one row of cells along barriers and doors, cutting
Ascent's attacker spawn from the map (revision 4 bridges cells 1.5-2.15 m
apart that see each other). The reach speed is the game's top run speed
[domain:game_data/character-movement-speeds] times 1.25, the path factor
of b03fecd3's one-second moves over the graph. The pruned belief advances
by single masked hops (two, then one, per 0.25 s step), so it never jumps
a watched choke; a cell is watched when a living teammate's cell sees it
within his 103 degree horizontal view. Smokes, doors, abilities and
teleporters are not modelled.

### 4.1 The last-seen reachable set

From each drawn run's last sight, the exact set of cells within the reach
speed times the time since (CQ11):

| Since the last sight | n | Truth inside, top speed | Truth inside, half speed | Set's share of the map |
|---|---|---|---|---|
| 1 s | [metric:coaching_belief/reach/dt1@pooled17#n=6291] | [metric:coaching_belief/reach/dt1@pooled17#in_full=0.9646] | [metric:coaching_belief/reach/dt1@pooled17#in_half=0.7638] | [metric:coaching_belief/reach/dt1@pooled17#size_full=0.0262] |
| 2 s | [metric:coaching_belief/reach/dt2@pooled17#n=5130] | [metric:coaching_belief/reach/dt2@pooled17#in_full=0.9696] | [metric:coaching_belief/reach/dt2@pooled17#in_half=0.786] | [metric:coaching_belief/reach/dt2@pooled17#size_full=0.0648] |
| 5 s | [metric:coaching_belief/reach/dt5@pooled17#n=3408] | [metric:coaching_belief/reach/dt5@pooled17#in_full=0.9704] | [metric:coaching_belief/reach/dt5@pooled17#in_half=0.8096] | [metric:coaching_belief/reach/dt5@pooled17#size_full=0.2359] |
| 8 s | [metric:coaching_belief/reach/dt8@pooled17#n=2548] | [metric:coaching_belief/reach/dt8@pooled17#in_full=0.8854] | [metric:coaching_belief/reach/dt8@pooled17#in_half=0.7637] | [metric:coaching_belief/reach/dt8@pooled17#size_full=0.4775] |
| 10 s | [metric:coaching_belief/reach/dt10@pooled17#n=2204] | [metric:coaching_belief/reach/dt10@pooled17#in_full=0.8884] | [metric:coaching_belief/reach/dt10@pooled17#in_half=0.7373] | [metric:coaching_belief/reach/dt10@pooled17#size_full=0.6451] |
| 20 s | [metric:coaching_belief/reach/dt20@pooled17#n=1372] | [metric:coaching_belief/reach/dt20@pooled17#in_full=0.9803] | [metric:coaching_belief/reach/dt20@pooled17#in_half=0.7638] | [metric:coaching_belief/reach/dt20@pooled17#size_full=0.9989] |

- **The set is right about 97% of the time for the first 5 s and grows
  fast**: a quarter of the map by 5 s, two thirds by 10 s. The dip at
  8-12 s falls on the enemies who stay unseen that long; teleporters,
  dashes and ropes, which the walk graph lacks, are the likely cause. I
  did not check it.
- **Half the unseen intervals end within**
  [metric:coaching_belief/unseen@pooled17#km_p50=2.9375] s (Kaplan-Meier
  over [metric:coaching_belief/unseen@pooled17#n=8791] intervals, the
  enemy re-drawn or dead), so most of the belief's life is spent while the
  set is still small.
- **Saturation**: the set covers 0.9 of the map's reachable cells a median
  [metric:coaching_belief/unseen@pooled17#saturation_all_p50=13.82] s after
  the last sight, from
  [metric:coaching_belief/saturation/haven@pooled17#sat_p50=11.26] s on
  Haven to [metric:coaching_belief/saturation/split@pooled17#sat_p50=16.8] s
  on Split. Counted by callout regions it saturates only 4-20% sooner
  (Bind [metric:coaching_belief/saturation/bind@pooled17#region_sooner=0.0399],
  Ascent [metric:coaching_belief/saturation/ascent@pooled17#region_sooner=0.1956]).
  Beyond about 14 s the last sight says nothing the map does not: the
  belief is "unknown".

### 4.2 Pruned by the team's vision

The propagated belief, dilated per step and less every cell a living
teammate watches (CQ14), holds the true enemy on
[metric:coaching_belief/belief/rate4.0@pooled17#in_pruned_sight=0.9698] of
undrawn steps after a sight, against
[metric:coaching_belief/belief/rate4.0@pooled17#in_unpruned_sight=0.9778]
unpruned. Pruning keeps the set smaller while it matters: 5 s after a
sight it holds
[metric:coaching_belief/unseen@pooled17#pruned_over_unpruned_5s=0.756] of
the unpruned set's cells. It still collapses: the pruned set covers 0.9 of
the unwatched cells a median
[metric:coaching_belief/collapse@pooled17#km_p50=13.0] s after the last
sight (Kaplan-Meier), close to the unpruned saturation.

**Collapse by formation**, at the last sight:

| Formation | Intervals | Collapses | Median collapse |
|---|---|---|---|
| two or fewer teammates alive | [metric:coaching_belief/collapse@pooled17#mates_le2.n=16604] | [metric:coaching_belief/collapse@pooled17#mates_le2.events=412] | [metric:coaching_belief/collapse@pooled17#mates_le2.km_p50=12.0] s |
| three or four | [metric:coaching_belief/collapse@pooled17#mates_3to4.n=32588] | [metric:coaching_belief/collapse@pooled17#mates_3to4.events=645] | [metric:coaching_belief/collapse@pooled17#mates_3to4.km_p50=13.25] s |
| five | [metric:coaching_belief/collapse@pooled17#mates_5.n=24204] | [metric:coaching_belief/collapse@pooled17#mates_5.events=295] | [metric:coaching_belief/collapse@pooled17#mates_5.km_p50=14.25] s |
| team watches the least of the map (bottom third) | [metric:coaching_belief/collapse@pooled17#obs_low.n=24467] | [metric:coaching_belief/collapse@pooled17#obs_low.events=607] | [metric:coaching_belief/collapse@pooled17#obs_low.km_p50=12.25] s |
| the most (top third) | [metric:coaching_belief/collapse@pooled17#obs_high.n=24450] | [metric:coaching_belief/collapse@pooled17#obs_high.events=340] | [metric:coaching_belief/collapse@pooled17#obs_high.km_p50=14.25] s |

A full team that watches more holds an enemy's belief about 2 s longer.
The team watches little of the map at any step (the middle third's upper
edge is [metric:coaching_belief/collapse@pooled17#obs_mid.obs_max=0.087]
of its cells), which is why pruning delays collapse so little.

### 4.3 Map control and holes

**Map control** is the share of the map no living enemy's pruned belief
holds. Twenty seconds after buy end its median is low
([metric:coaching_belief/control_value@pooled17#control_p50.attack=0.079]
attacking, [metric:coaching_belief/control_value@pooled17#control_p50.defence=0.1014]
defending), and it tracks the round: the top third within side wins
[metric:coaching_belief/control_value@pooled17#y_a1=0.5826] against the
bottom third's [metric:coaching_belief/control_value@pooled17#y_a0=0.3478],
a difference of [metric:coaching_belief/control_value@pooled17#diff=0.2348]
(interval [metric:coaching_belief/control_value@pooled17#ci_lo=0.1362] to
[metric:coaching_belief/control_value@pooled17#ci_hi=0.3346],
[metric:coaching_belief/control_value@pooled17#n=460] team-rounds). As
with every value here this is association: control may follow from kills
already made.

**Holes.** A teammate's flank is open when some enemy's pruned belief
reaches within 10 m walk of him. It is open on
[metric:coaching_belief/holes@pooled17#open_share=0.6856] of living
steps; a hole stays open a median
[metric:coaching_belief/holes@pooled17#p50_s=7.0] s (p90
[metric:coaching_belief/holes@pooled17#p90_s=37.0] s). Deaths come
through holes more than chance: a teammate dies at
[metric:coaching_belief/flank_hazard@pooled17#rate_ratio=1.5505] times
the per-second rate while his flank is open (interval
[metric:coaching_belief/flank_hazard@pooled17#ci_lo=1.3671] to
[metric:coaching_belief/flank_hazard@pooled17#ci_hi=1.7758];
[metric:coaching_belief/flank_hazard@pooled17#deaths_open=1954] deaths
open, [metric:coaching_belief/flank_hazard@pooled17#deaths_closed=578]
closed). "Open" is so common that the measure is coarse; a hole's value
as coaching is the long-open one, the p90 tail.

### 4.4 The teammate fidelity the belief needs

The belief needs teammates' position and facing to prune. Rebuilt from
teammate poses read at lower rates (positions interpolated, facing from
the nearer read):

| Teammate pose rate | Truth in the pruned set | Control error (mean absolute) | Open-flank agreement with 4 Hz |
|---|---|---|---|
| 4 Hz | [metric:coaching_belief/belief/rate4.0@pooled17#in_pruned_sight=0.9698] | reference | reference |
| 1 Hz | [metric:coaching_belief/belief/rate1.0@pooled17#in_pruned_sight=0.968] | [metric:coaching_belief/belief/rate1.0@pooled17#control_mae=0.0058] | [metric:coaching_belief/belief/rate1.0@pooled17#flank_agree=0.9856] |
| 0.5 Hz | [metric:coaching_belief/belief/rate0.5@pooled17#in_pruned_sight=0.9648] | [metric:coaching_belief/belief/rate0.5@pooled17#control_mae=0.0099] | [metric:coaching_belief/belief/rate0.5@pooled17#flank_agree=0.9734] |
| 0.25 Hz | [metric:coaching_belief/belief/rate0.25@pooled17#in_pruned_sight=0.9545] | [metric:coaching_belief/belief/rate0.25@pooled17#control_mae=0.0154] | [metric:coaching_belief/belief/rate0.25@pooled17#flank_agree=0.9547] |

**Map control and holes need only the base rate**: 0.5 Hz teammate poses
keep control within a hundredth and flank state on 0.97 of steps, so the
belief costs no reads beyond the schedule of section 3. Facing matters
most right after a sight, where the 0.25 Hz belief drops to
[metric:coaching_belief/belief/rate0.25@pooled17#sight_0s.in_pruned=0.9094]
in the first second.

### 4.5 Priors from earlier rounds

Habits from earlier rounds of the same match predict little on these 17
matches (CQ12):

- **Where a player is 20 s after buy end**, by the mode of his own earlier
  rounds on that side (at least three): right on
  [metric:coaching_belief/priors@pooled17#region_own.acc=0.422]
  (n [metric:coaching_belief/priors@pooled17#region_own.n=1796]), against
  [metric:coaching_belief/priors@pooled17#region_team.acc=0.4154] for his
  team's mode and
  [metric:coaching_belief/priors@pooled17#region_overall.acc=0.4014] for
  the side's overall mode.
- **The first execute's site** by the team's earlier attack rounds: right
  on [metric:coaching_belief/priors@pooled17#site.acc=0.4915]
  (n [metric:coaching_belief/priors@pooled17#site.n=236]) against a chance
  of [metric:coaching_belief/priors@pooled17#site.chance=0.4859]: no better
  than guessing.
- **Lurking**, by a player's earlier lurk share: AUC
  [metric:coaching_belief/priors@pooled17#lurk_auc.auc=0.5811]
  (interval [metric:coaching_belief/priors@pooled17#lurk_auc.ci_lo=0.5129]
  to [metric:coaching_belief/priors@pooled17#lurk_auc.ci_hi=0.6339]), a
  weak habit.
- **What the capturing team can know of it**: the enemy is drawn within
  2 s of the probe on [metric:coaching_belief/priors@pooled17#censor.seen_share=0.3615]
  of his rounds, and a mode built from those sightings alone is right on
  [metric:coaching_belief/priors@pooled17#censor.own_cens_acc=0.4156], as
  good as the full history.

A within-match prior is worth holding as a weak belief, ranked below the
reachable set; across matches (the ladder's 140) it may do better, which
this did not test.


## 5. An attention budget

The player's model: one full-fidelity focus at a time, the player's own
engagement first, then by proximity (CQ13, revision 1). The arm `A<b>K<k>`
groups the drawn enemies into windows (single linkage within 20 m) at each
16 Hz sample; a window involves the teammates who see a member or stand
within 20 m of one. Windows involving the player rank first, then by the
player's distance to the window. The top K windows read at full fidelity
(their teammates at 15 Hz with 250 ms of buffered frames, their enemies at
every sample); every other drawn enemy is known only at the base samples,
and every teammate at the base rate b from buy end. The player is the
account's subject on the
[metric:coaching_questions/degrade/A1K1@pooled17-attn#concurrency.subject_perspectives=11]
perspectives that hold one, else the team's first slot.

**Concurrency is low.** Two or more windows are open on
[metric:coaching_questions/degrade/A1K1@pooled17-attn#concurrency.ge2=0.0925]
of drawn time and three or more on
[metric:coaching_questions/degrade/A1K1@pooled17-attn#concurrency.ge3=0.0033].

| Arm | Slot share | Contacts | First seer | Support | Duels | Trades | Peeker state | Executes |
|---|---|---|---|---|---|---|---|---|
| `A0.5K1` | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#share=0.102] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.contact_C=0.8987] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.opening_first_seer=0.9595] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.first_sight_support=0.9696] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.duel_C=0.9632] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.trade_C=0.9684] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.peek_C=0.9424] | [metric:coaching_questions/degrade/A0.5K1@pooled17-attn#vs_T1.execute_C=0.9269] |
| `A0.5K2` | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#share=0.1053] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.contact_C=0.9732] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.opening_first_seer=0.9928] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.first_sight_support=0.9696] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.duel_C=0.9924] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.trade_C=0.9895] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.peek_C=0.9819] | [metric:coaching_questions/degrade/A0.5K2@pooled17-attn#vs_T1.execute_C=0.9269] |
| `A1K1` | [metric:coaching_questions/degrade/A1K1@pooled17-attn#share=0.117] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.contact_C=0.8988] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.opening_first_seer=0.9697] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.first_sight_support=0.9812] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.duel_C=0.9729] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.trade_C=0.9705] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.peek_C=0.9517] | [metric:coaching_questions/degrade/A1K1@pooled17-attn#vs_T1.execute_C=0.9557] |
| `A1K2` | [metric:coaching_questions/degrade/A1K2@pooled17-attn#share=0.1202] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.contact_C=0.979] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.opening_first_seer=0.9942] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.first_sight_support=0.9812] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.duel_C=0.993] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.trade_C=0.9916] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.peek_C=0.9855] | [metric:coaching_questions/degrade/A1K2@pooled17-attn#vs_T1.execute_C=0.9557] |
| `Lp1-250w5`, every window at 5 Hz | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#share=0.0652] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.contact_C=0.9589] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.opening_first_seer=0.9783] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.first_sight_support=0.9754] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.duel_C=0.983] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.trade_C=0.9916] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.peek_C=0.9697] | [metric:coaching_questions/degrade/Lp1-250w5@pooled17-attn#vs_T1.execute_C=0.9479] |

What it says:

- **One focus window loses the second fight.** With K = 1, contacts fall
  to 0.90 though two windows are open less than a tenth of the time: the
  fights that overlap are the ones a second window holds. K = 2 restores
  everything (contacts 0.98).
- **The budget is spent on rate, not on windows.** A focus window read at
  15 Hz costs about twice the local gate's 5 Hz windows, which read every
  window: `A1K2` reads 0.12 of today's slot reads against `Lp1-250w5`'s
  0.065 for about the same answers. Inside a window, 5 Hz suffices; the
  scarce resource is not the number of windows. The player's attention
  model fits a human (one fight at a time); a reader can afford every
  window at 5 Hz.

## 6. The cost target

The target (player, 2026-10-06): real time with no noticeable cost,
stretch goal under 1 ms average processing per captured frame. The basis
is the captured frame at
[metric:coaching_questions/cost/today@9acf02f98283#capture_fps=60.0] fps
(the development captures' rate; every manifest checked says 60). Today,
from `reticle usage`'s stored runs on 9acf02f98283, the two 15 Hz minimap
readers cost
[metric:coaching_questions/cost/today@9acf02f98283#cv4.per_read_ms=29.744] ms
per read frame on the least contended pass (`ally_icon`
[metric:coaching_questions/cost/today@9acf02f98283#cv4.ally_icon_ms_per_read=26.421] ms
over [metric:coaching_questions/cost/today@9acf02f98283#cv4.ally_icon_fed=19163]
fed frames; `minimap`
[metric:coaching_questions/cost/today@9acf02f98283#minimap_ms_per_read=3.322] ms),
that is [metric:coaching_questions/cost/today@9acf02f98283#cv4.per_captured_ms=7.436] ms
per captured frame; a contended pass doubles it
([metric:coaching_questions/cost/today@9acf02f98283#cv12.per_captured_ms=14.243] ms).
These are feed times on the dispatcher thread, decode excluded.

Each arm's implied cost per captured frame scales today's by its share:
on the slot basis (the ally reader fits each slot it reads) and on the
frame basis (a reader whose cost is per frame read, a bound from above):

| Arm | Slot share | ms per captured frame, slot basis (uncontended) | frame basis (uncontended) | slot basis (contended) |
|---|---|---|---|---|
| `B0.5` | [metric:coaching_questions/cost/B0.5@pooled17#share=0.0329] | [metric:coaching_questions/cost/B0.5@pooled17#cv4.slot_ms=0.245] | [metric:coaching_questions/cost/B0.5@pooled17#cv4.frame_ms=0.25] | [metric:coaching_questions/cost/B0.5@pooled17#cv12.slot_ms=0.469] |
| `B1` | [metric:coaching_questions/cost/B1@pooled17#share=0.0661] | [metric:coaching_questions/cost/B1@pooled17#cv4.slot_ms=0.491] | [metric:coaching_questions/cost/B1@pooled17#cv4.frame_ms=0.498] | [metric:coaching_questions/cost/B1@pooled17#cv12.slot_ms=0.941] |
| `Lp0.25-250w5` | [metric:coaching_questions/cost/Lp0.25-250w5@pooled17#share=0.0399] | [metric:coaching_questions/cost/Lp0.25-250w5@pooled17#cv4.slot_ms=0.297] | [metric:coaching_questions/cost/Lp0.25-250w5@pooled17#cv4.frame_ms=0.749] | [metric:coaching_questions/cost/Lp0.25-250w5@pooled17#cv12.slot_ms=0.569] |
| `Lp0.5-250w5` | [metric:coaching_questions/cost/Lp0.5-250w5@pooled17#share=0.0484] | [metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv4.slot_ms=0.36] | [metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv4.frame_ms=0.814] | [metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv12.slot_ms=0.689] |
| `Lp1-250w5` | [metric:coaching_questions/cost/Lp1-250w5@pooled17#share=0.0652] | [metric:coaching_questions/cost/Lp1-250w5@pooled17#cv4.slot_ms=0.485] | [metric:coaching_questions/cost/Lp1-250w5@pooled17#cv4.frame_ms=0.944] | [metric:coaching_questions/cost/Lp1-250w5@pooled17#cv12.slot_ms=0.929] |
| `L1-250w5` | [metric:coaching_questions/cost/L1-250w5@pooled17#share=0.095] | [metric:coaching_questions/cost/L1-250w5@pooled17#cv4.slot_ms=0.706] | [metric:coaching_questions/cost/L1-250w5@pooled17#cv4.frame_ms=1.129] | [metric:coaching_questions/cost/L1-250w5@pooled17#cv12.slot_ms=1.353] |
| `L1-0` | [metric:coaching_questions/cost/L1-0@pooled17#share=0.1387] | [metric:coaching_questions/cost/L1-0@pooled17#cv4.slot_ms=1.032] | [metric:coaching_questions/cost/L1-0@pooled17#cv4.frame_ms=1.791] | [metric:coaching_questions/cost/L1-0@pooled17#cv12.slot_ms=1.976] |
| `G1-0` | [metric:coaching_questions/cost/G1-0@pooled17#share=0.2584] | [metric:coaching_questions/cost/G1-0@pooled17#cv4.slot_ms=1.921] | [metric:coaching_questions/cost/G1-0@pooled17#cv4.frame_ms=2.126] | [metric:coaching_questions/cost/G1-0@pooled17#cv12.slot_ms=3.68] |
| `A0.5K1` | [metric:coaching_questions/cost/A0.5K1@pooled17#share=0.102] | [metric:coaching_questions/cost/A0.5K1@pooled17#cv4.slot_ms=0.758] | [metric:coaching_questions/cost/A0.5K1@pooled17#cv4.frame_ms=1.665] | [metric:coaching_questions/cost/A0.5K1@pooled17#cv12.slot_ms=1.453] |
| `A1K1` | [metric:coaching_questions/cost/A1K1@pooled17#share=0.117] | [metric:coaching_questions/cost/A1K1@pooled17#cv4.slot_ms=0.87] | [metric:coaching_questions/cost/A1K1@pooled17#cv4.frame_ms=1.766] | [metric:coaching_questions/cost/A1K1@pooled17#cv12.slot_ms=1.666] |
| `A1K2` | [metric:coaching_questions/cost/A1K2@pooled17#share=0.1202] | [metric:coaching_questions/cost/A1K2@pooled17#cv4.slot_ms=0.894] | [metric:coaching_questions/cost/A1K2@pooled17#cv4.frame_ms=1.779] | [metric:coaching_questions/cost/A1K2@pooled17#cv12.slot_ms=1.712] |

**The live-phase local gate meets the stretch goal on the slot basis**,
`Lp0.5-250w5` at
[metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv4.slot_ms=0.36] ms
uncontended and
[metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv12.slot_ms=0.689] ms
contended, and on the frame basis uncontended
([metric:coaching_questions/cost/Lp0.5-250w5@pooled17#cv4.frame_ms=0.814] ms).
The attention arms and the 1 Hz global gate do not. Not counted: the gate's
own red-pixel test on every frame, which must fit in the remainder (about
0.6 ms per captured frame, so about 2.5 ms per 15 Hz frame), and the crop
decode.

## 7. Predictions and outcomes

Registered in the store's `notes/predictions.jsonl` (task
`coaching-questions-20261006`) before each run; outcome rows are appended
there. A failed prediction revises the belief it tested.

| Ref | Prediction (short) | Outcome |
|---|---|---|
| CQ0a | T0 through the harness reproduces the stored kind counts | held, 17 of 17 |
| CQ0b | T1 round results and attack teams equal T0's | **failed**: 14 of 690 team-rounds differ in end reason, winners agree; the replay layer keeps two departed players alive (section 9), an instrument fault |
| CQ1a | the top three questions are event-only | held on the catalogue as registered (trades, opening duel, buy); map control, added later, ranks third and needs teammate poses |
| CQ1b | a position-dependent question in the top six | held: execute commitment (and map control) |
| CQ2a | opening kill 0.20-0.35 | **failed**: 0.355, above the band |
| CQ2b | traded death 0.05-0.15 | **failed**: 0.216, far above; trades matter more than believed |
| CQ2c | traded share near (5 m) at least 1.5 times far (10 m) | held: 2.7 times |
| CQ2d | execute commitment 0.10-0.35 | **failed**: 0.381, above |
| CQ2e | blind deaths 0.10-0.25 of deaths, traded at least 0.05 less | held: 0.101; 0.124 against 0.191 |
| CQ2f | damage-only balance 0.05-0.20; chipped duelist wins at most 0.45 | held: 0.164; 0.354 |
| CQ3a-c | global 1 Hz share 0.20-0.45; local 0.10-0.25; local w5 0.05-0.12 | held: 0.258, 0.139, 0.063 |
| CQ3d | no gated arm reads at most 0.05 | **failed**: `L0.25-250w5` reads 0.047 |
| CQ4a | the lead moves agreement by at most 0.01 | **failed** narrowly: local contacts +0.017, global executes +0.013 |
| CQ4b | the lead raises the share by 0.01-0.06 | held except `G0.5`, +0.061 |
| CQ5a | at 1 Hz base, rotations and lurks F1 0.80-0.95 | **failed**: F1 0.996 and 0.998; region questions need less than believed |
| CQ5b | at 1 Hz base, spacing bucket 0.70-0.90, contacts and first seer low | spacing **failed** (0.912, above); contacts and first seer held |
| CQ6a-b | the 1 Hz gates keep the sight questions | held |
| CQ7a | T1: first seer 0.55-0.85; contacts recall 0.65-0.90 | **failed**: 0.941 and 0.951; censoring costs less than believed |
| CQ7b | T1: team executes exact; enemy rotations recall 0.10-0.50; enemy lurks at most 0.40 | executes held; enemy rotations **failed** (0.059, below); enemy lurks held (0.27) |
| CQ8 claim | the player's: some schedule at 0.05 or less holds the top five at 0.95 | **holds** (section 3.3) |
| CQ8a | the claim holds because most of the five read no position | held |
| CQ8b | no schedule at 0.05 or less holds every position question of the top ten; base 0.5 Hz holds the region questions | first clause held for strict timing; second **failed**: `B0.5` misses the region questions too |
| CQ8c | a local gate with wr 5 at 0.15 or less holds them all | held: `L1-250w5`, 0.095 |
| CQ9a-c | post hoc `Lp` arms on the 14 confirmation replays | held |
| CQ10a | the drawn-enemy gate open at onset 0.80-0.92 | **failed** narrowly: 0.921; lead and the 250 ms clause held |
| CQ10b-c | local gate 0.70-0.90; misses enemy-first at least 0.6 | held: 0.859; 0.669 |
| CQ11a | exact reach holds the truth on at least 0.97 at every dt | **failed**: 0.965-0.972 at 1-5 s, 0.885-0.914 at 8-12 s |
| CQ11b | at half speed, 0.55-0.85 at 5 s | held: 0.810 |
| CQ11c | set size: 2 s 0.01-0.06, 5 s 0.05-0.25, 10 s 0.20-0.55 | 5 s held (0.236); 2 s **failed** narrowly (0.065); 10 s **failed** (0.645): the set grows faster |
| CQ11d | half the unseen intervals end within 3-10 s | **failed** narrowly: 2.94 s |
| CQ11e | median saturation 12-35 s per map; regions 20-60% sooner | **failed**: Haven and Lotus under 12 s; regions only 4-20% sooner |
| CQ11f | containment beyond saturation at least 0.97 | held |
| CQ12a | own-history mode 0.40-0.65 and 0.10 above the team prior | **failed**: 0.422, only 0.007 above |
| CQ12b | first-execute site 0.40-0.65 against chance 0.33-0.50 | in band (0.492) but equal to chance (0.486): no signal |
| CQ12c | lurk habit AUC 0.55-0.75 | held: 0.581 |
| CQ12d | censored history holds the enemy's region on at most 0.25 | **failed**: 0.36 |
| CQ13a-d | `A1` share 0.04-0.08; A1 holds first seer, trades, 5 m; contacts 0.80-0.94; `A0.5` share 0.03-0.06 | shares **failed** (0.117, 0.102: 15 Hz focus windows cost more than 5 Hz gate windows); the answers held, but support (0.981) is above its band |
| CQ13e | two or more windows on 0.15-0.40 of drawn time; three or more at most 0.15 | first **failed** (0.093); second held (0.003) |
| CQ13f | A1K1 contacts 0.80-0.94; A1K2 within 0.02 of `Lp1-250w5` | held: 0.899; A1K2 at or above `Lp1-250w5` on every team question |
| CQ14a | pruned containment 0.85-0.97, unpruned at least 0.97 | held: 0.970, 0.978 |
| CQ14b | at 5 s the pruned set holds 0.40-0.80 of the unpruned | held: 0.756 |
| CQ14c | collapse later than unpruned saturation by 20-80%; two or fewer teammates at least 25% sooner than five | **failed**: 13.0 s against 13.8 s; 16% sooner |
| CQ15a | control's top against bottom tercile 0.05-0.25 | held: 0.235 |
| CQ15b | death rate with the flank open 1.5-4 times closed | held: 1.55 |
| CQ15c-d | median hole 2-10 s; flank open on 0.30-0.70 of steps | held: 7.0 s; 0.686 |
| CQ16a | 1 Hz poses: control error at most 0.03, flank agreement at least 0.90, containment within 0.02 | held |
| CQ16b | 0.25 Hz: flank agreement 0.75-0.90, containment at least 0.03 lower | **failed**: 0.955 and 0.015 lower; the belief needs less than believed |
| CQ17a | the lone peeker wins 0.52-0.65 | **failed**: 0.510 [0.483, 0.536] |
| CQ17b | peeker state at least 0.95 under `B1`, at least 0.97 under `Lp0.5-250w5` | **failed**: 0.702 and 0.965: it needs gate fidelity |
| CQ17c | the pair's states, T1 against truth, 0.70-0.90 | held: 0.859 |
| CQ17d | at least one participant moving in 0.70 of kill duels | held: 0.965 |
| CQ18a | both corner distances found on 0.50-0.85 of kill duels | **failed**: 0.943 |
| CQ18b | the far side wins 0.50-0.60; stratified difference 0.00-0.10 | **failed**: 0.479; -0.039, interval spanning 0 |
| CQ18c | wide long-angle peeks win 0.03-0.15 more than tight | **failed**: -0.072 on 61 tight peeks; the proxy cannot separate them |
| CQ18d | the far-or-near label 0.85-0.95 under `B1`, at least 0.97 under `Lp0.5-250w5` | `B1` **failed** narrowly (0.826); `Lp0.5-250w5` held (0.987) |

## 8. Questions for the player

Only what the data cannot answer:

1. **Timing or occurrence.** Under `Lp0.5-250w5` a team execute, rotation
   or lurk is found (F1 0.97 or more) but its start lands outside 1 s, or
   its committed count is off, on 5-8% of them; `Lp1-250w5` fixes most of
   that for a third more reads. Does a coaching answer need the start
   within a second, or only that the move happened and how many went?
2. **Whose fights.** The attention arm serves the player's own engagement
   first. Is the coaching about you, with teammates as context, or about
   the team's fights equally? The answer sets K, the number of windows
   read at full fidelity.

## 9. What was not done, and side findings

- **No reader, no reader error.** Every arm schedules reads of truth
  positions; none models minimap lag, fit error, a missed icon, or the
  field limits of T2 (no z, no pitch). QA plan steps B7 and B10 measure
  those.
- **The gate's own cue is not costed.** The drawn-enemy test runs on
  every frame; the cost figures of section 6 leave it out. The teal-change
  cue costs 0.12-0.18 ms per 15 Hz frame (QUESTION_ACCEPTANCE section 5),
  a guide, not a measurement of the red test.
- **The belief ignores movement abilities, teleporters, smokes and
  doors.** Bind's teleporters and dashes take an enemy out of his set;
  containment says how often. Vision ignores smokes, so the pruned set
  over-prunes behind them.
- **Value is association.** The round-win differences are stratified, not
  causal; ranks 7-10 have intervals spanning zero on 17 replays.
- **The post hoc arms** (`Lp`) were chosen after the development run and
  confirmed on the 14 others; the attention arm's ranking rule was fixed
  before it ran.
- **No held-out read, no fit.** Nothing read bd7efa02; no threshold was
  chosen on the replays a figure is quoted from, except the belief's speed
  factor and hop schedule, taken from b03fecd3 (development) and reported
  on all 17.
- **Side finding: the replay layer keeps departed players alive.** In
  7498df5e and 2c387cb6 a player leaves the match and `replay_layer`'s
  `lives` keeps him alive with no ticks (from round 7 in 7498df5e, rounds
  23-24 in 2c387cb6), so a lifecycle-based life says time or detonation
  where the truth says elimination (CQ0b).
- **Side finding: the 3D sightline table's walk graph is cut.** It leaves
  out one row of cells along barriers and doors, so on Ascent the
  attackers' spawn is a separate component, and it carries no jump-up or
  drop edges. The belief adds both from the table's own visibility bits
  (revisions 2 and 4); `sightlines_3d` itself is unchanged.
