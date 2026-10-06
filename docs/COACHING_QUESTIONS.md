# Coaching questions on truth: which questions matter, and what fidelity they need

Status: in progress, 2026-10-06. This checkpoint holds the inventory, the
registered predictions, the runs made and the steps left; the findings
sections replace it when the belief, prior and attention runs finish.

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

## Checkpoint

### Registered predictions (store `notes/predictions.jsonl`, task `coaching-questions-20261006`)

- CQ0-CQ8 (19:07:32Z): stored-count checks, decision value, degradation arms, the player's 95% claim (CQ8).
- CQ9 (19:19:18Z): post hoc base reads (`Lp` arms) on the 14 confirmation replays.
- CQ10 (19:20:47Z): gate onset and lead.
- CQ11-CQ13 (19:59:18Z): last-seen reachable set, priors from previous rounds, attention-budget arm.
- CQ11-revision-1 and CQ13-revision-1 (20:00:09Z): saturation per map; player-first window ranking.
- CQ14-CQ16 (20:01:37Z): vision-pruned set and collapse by formation; map control and holes; pose fidelity.
- CQ11-CQ14-revision-2 (20:06:46Z): instrument fault in the walk graph; augmented directed graph, reach speed 6.75 m/s x 1.25, single masked hops.

### Runs made (store `analysis/coaching-questions-20261006/`)

- `degrade.jsonl`: every arm on all 17 replays, both perspectives (1088 rows); pooled in `degrade_pooled.json`, report `report_all17.txt`.
- `degrade_dev3.jsonl`, `degrade_posthoc_dev.jsonl`: development replays; `degrade_confirm14.jsonl`, `report_confirm14.txt`: the 14 confirmation replays (CQ9).
- `degrade_exec.jsonl`, `degrade_exec_pooled.json`, `report_exec.txt`: the execute-commitment band.
- `value.json`: decision value on the ladder (140 matches) and replays (17).
- Ledger: `coaching_questions` series `inventory/*@store`, `degrade/<arm>@pooled17`, `@pooled17-exec`, `@confirm14`, `value/*@pooled`.

### Steps left

1. `prototypes/coaching_belief.py` (CQ11, CQ14-CQ16): revision-2 graph coded; re-test containment on b03fecd3, run all 17 at idle, write `report`, record.
2. CQ12 priors; CQ13 attention arm in `coaching_questions.py`; run, record.
3. Cost target: today's ms per captured 60 Hz frame from `reticle usage`; each arm's implied budget against 1 ms.
4. This document's findings; QUESTION_ACCEPTANCE.md sections 1, 5, 6, 7, 9, 10; QA5r and QA6r revision rows; outcome rows CQ0-CQ16.
5. `reticle doctor`, commit, push.
