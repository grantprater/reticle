# Ult-ready voice lines

Does the match audio say whose ultimate is ready? An agent announces a ready
ultimate in a fixed line of its own [domain:abilities/ult-ready-lines], and
the wiki lists that line as one reply of the Ultimate Status radio command
[domain:abilities/ult-ready-line-is-a-radio-reply]. The player's review of
the ultimate voice-line sheet ([VOICE_LINES.md](VOICE_LINES.md)) found such a
line scoring just under the cast threshold on a cast template. A ready line
is therefore two things: a false alarm the cast templates must survive, and a
witness that the speaker's ultimate is ready. The prototype is
`prototypes/ult_ready_lines.py`; it emits no events, writes nothing under
`events/` or `labels/`, and `reticle/` does not import it.

## Data, all stored

- Templates: the ready reply of every agent's quotes page, two takes each,
  harvested by `voice_line_harvest.py ult-ready` into the store's
  `reference/assets/voicelines/ult_ready/` ([VOICE_LINE_ASSETS.md](VOICE_LINE_ASSETS.md#ult-ready-lines)).
- Sessions: the captures `reticle ult-cast --record` read, every capture with
  audio (the `ult_lines/ult-cast@all-sessions` run's `session_ids`).
- Lineups, the player's agent, live time, rounds and own X casts:
  `voice_lines.session_context`, the cast lines' own context
  ([VOICE_LINES.md](VOICE_LINES.md#data-all-stored)).
- Cast peaks: the reader's stored rows, `events/ult_line/<sid>.jsonl`; the
  adjudicator's threshold, `adjudication.ult_cast.THRESHOLD`.
- Tray drops: `events/tray_drop/<sid>.jsonl`, a coverage row and one row per
  drop. It stores no fill.

## Method

- **Scoring.** One template per take, cut by the reader's own rule
  (`ult_lines.build_templates`). Each capture's audio stream is decoded in
  memory (`ult_lines.decode_mono`) and correlated with whitened waveform
  correlation (`ult_lines.read_capture`, F-B), on the GPU. Every peak at or
  above its template's 99th percentile stays, none within one template length
  of a higher peak of the same template: the reader's rule. Rows go to
  `<store>/analysis/ult-ready-lines/0.1.0/peaks/<sid>.jsonl` in the reader's
  row shape, one session at a time; nothing else is written.
- **One detection per line.** Both takes of a line may peak on one utterance.
  A peak falls when a higher peak of the same agent's other take lies within
  the agent's longer take (`voice_lines.suppress`).
- **Classing.** Each agent is classed per session from the identity arbiter's
  lineup, by asking `voice_lines.template_class` for both cast variants:
  `own` (the player's agent), `ally_named` and `enemy_named` (that side's cast
  template is possible: the agent is named there or is a refused slot's
  candidate), `absent` (the lineup puts the agent on neither complete side) and
  `unknown`. A ready line has no side variant, and the lineup leaves the agent
  of the one line the player heard possible on the enemy side (see "The heard
  line"). Only `absent` is therefore a false alarm. The literal ally-side classing, which counts an
  enemy's line as impossible, gets its own threshold beside it.
- **Operating point.** The cast lines' rule (`voice_lines.operating_tau`): the
  lowest threshold at which `absent` detections in live time run at most
  `voice_lines.OP_RATE` per live minute, pooled over the sessions with a
  lineup. A threshold below every template's floor would count unstored
  peaks; the run records whether the threshold clears the highest floor.
- **R3 without fills.** The tray reader stores drops, not fills, so no fill
  is dated and "within 3 s of the charge becoming full" cannot be measured.
  Each accepted own X cast closes one fill interval, opened by the previous
  own X cast or the first round's start. The test counts the player's own
  ready detections inside those intervals against the share of the timeline
  they cover, and the intervals holding one against detections placed at
  random over the timeline. A line voiced at every fill would put one in
  nearly every interval.
- **R4.** Every ready detection at the operating point, live or not, against
  the stored cast peaks: a collision is a cast peak at or above the
  adjudicator's threshold within 0.5 s; a near miss is one below it.
- **Cross-talk.** The share of live `absent` detections with a higher ready
  detection of another agent within `voice_lines.SUPPRESS_S`: one line firing
  several agents' templates.

## Predictions

Recorded in the store's `notes/predictions.jsonl` under task
`ult-ready-lines` before any run.

| Id | Prediction | Confidence |
|---|---|---|
| R1 | The wiki quote pages carry an ultimate-ready line section for at least 25 of the 28 agents with an ult asset. | 0.6 |
| R2 | Scored with F-B over the 25 sessions, ally ult-ready templates fire (at the cast templates' floor rule) for agents the lineup names at least four times as often as for agents it excludes. | 0.6 |
| R3 | The player's own agent's ult-ready line is heard: on Sova and Skye sessions it fires within 3 s of the tray's X charge becoming full on at least half of the fills the tray reader can date. | 0.45 |
| R4 | Ult-ready lines collide with cast templates: across 25 sessions at most one ult-ready onset per session also scores >= 0.0443 on any cast template (row 21 of the sheet was 0.0441). | 0.55 |

## Results

Run on 2026-09-27; every figure cites the recorded run
`ult_ready_lines/evaluate-0.1.0` over all matches, whose rows sit under
`<store>/analysis/ult-ready-lines/0.1.0/` (`peaks/`, `summary.json`,
`evaluate.json`).

### What ran

- Templates: [metric:ult_ready_lines/evaluate-0.1.0@all-matches#templates=58] takes of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#agents=29] agents, the harvest's [metric:voice_line_harvest/ult-ready@wiki#files=58] files.
- Sessions: [metric:ult_ready_lines/evaluate-0.1.0@all-matches#sessions_scored=25] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#sessions=25] scored, none refused; [metric:ult_ready_lines/evaluate-0.1.0@all-matches#sessions_lineup=19] carry a lineup. [metric:ult_ready_lines/evaluate-0.1.0@all-matches#peaks=200143] peaks stored.
- Seconds per session, min / median / max: decode [metric:ult_ready_lines/evaluate-0.1.0@all-matches#decode_s_min=0.3] / [metric:ult_ready_lines/evaluate-0.1.0@all-matches#decode_s_median=21.3] / [metric:ult_ready_lines/evaluate-0.1.0@all-matches#decode_s_max=37.3], score [metric:ult_ready_lines/evaluate-0.1.0@all-matches#score_s_min=0.1] / [metric:ult_ready_lines/evaluate-0.1.0@all-matches#score_s_median=2.2] / [metric:ult_ready_lines/evaluate-0.1.0@all-matches#score_s_max=3.4], on the GPU. Decoding the audio stream takes most of the time.
- Live time on the sessions with a lineup: [metric:ult_ready_lines/evaluate-0.1.0@all-matches#live_minutes=385.5] minutes.

### Operating point

The cast lines' rule puts the threshold at [metric:ult_ready_lines/evaluate-0.1.0@all-matches#tau=0.0509], where [metric:ult_ready_lines/evaluate-0.1.0@all-matches#absent_n=38] absent detections run [metric:ult_ready_lines/evaluate-0.1.0@all-matches#absent_per_live_min=0.099] per live minute. It clears the highest template floor, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#floor_max=0.0169], so every peak it counts was stored. The literal ally-side classing sets [metric:ult_ready_lines/evaluate-0.1.0@all-matches#tau_ally_side=0.0522]. Both sit above the cast threshold, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#cast_threshold=0.0443].

### R2: named against absent agents

| Class | Detections | Agent-minutes | Per agent-minute |
|---|---|---|---|
| Own agent | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#own_n=36] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#own_agent_minutes=385.5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#own_per_agent_min=0.09339] |
| Ally, named | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_named_n=63] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_named_agent_minutes=1541.9] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_named_per_agent_min=0.04086] |
| Enemy, named | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#enemy_named_n=11] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#enemy_named_agent_minutes=1466.6] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#enemy_named_per_agent_min=0.0075] |
| On neither side | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#absent_n=38] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#absent_agent_minutes=7784.6] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#absent_per_agent_min=0.00488] |

Named allies fire [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_ally_to_absent=8.37] times as often per agent-minute as absent agents; named enemies [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_enemy_to_absent=1.54] times; all named agents together [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_named_to_absent=5.04] times. The ally-side classing, which counts an enemy's line as impossible, gives [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_side_ratio=9.16] ([metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_side_possible_n=58] possible against [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ally_side_impossible_n=38] impossible detections). The templates hear the lines of the player's team; an enemy's fires barely above the false-alarm rate.

Cross-talk: [metric:ult_ready_lines/evaluate-0.1.0@all-matches#crosstalk_beside_higher=25] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#crosstalk_absent=38] absent detections sit within 1.2 s of a higher ready detection of another agent, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#crosstalk_beside_absent=20] of them beside another absent agent, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#crosstalk_beside_enemy_named=3] beside a named enemy and [metric:ult_ready_lines/evaluate-0.1.0@all-matches#crosstalk_beside_ally_named=2] beside a named ally. Most false alarms are one sound firing several agents' templates, not one agent's line mistaken for another's.

### R3: the player's own line against fills

`events/tray_drop` holds [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_tray_fill_rows=0] fill rows: the tray reader computes the charge per sample and stores only its drops, so no fill is dated and R3 as stated cannot be measured. Over [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_sessions=19] sessions, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_casts=45] accepted own X casts each close a fill interval.

| Player's agent | Sessions | Own detections | Inside an interval | Expected by chance | Intervals | Intervals holding one | Expected by chance |
|---|---|---|---|---|---|---|---|
| Sova | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_sessions=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_det=15] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_inside=12] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_expected=12.09] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_casts=19] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_intervals_hit=12] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Sova_intervals_hit_expected=9.93] |
| Skye | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_sessions=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_det=10] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_inside=10] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_expected=8.6] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_casts=15] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_intervals_hit=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Skye_intervals_hit_expected=6.76] |
| Phoenix | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_sessions=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_det=11] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_inside=6] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_expected=5.9] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_casts=10] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_intervals_hit=4] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Phoenix_intervals_hit_expected=4.66] |
| Clove | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_sessions=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_det=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_inside=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_expected=0.53] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_casts=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_intervals_hit=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_Clove_intervals_hit_expected=0.53] |
| All | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_sessions=19] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_det=37] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_inside=29] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_expected=27.11] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_casts=45] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_intervals_hit=25] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_intervals_hit_expected=21.87] |

The counts sit at chance: a line voiced at every fill would put one in nearly every interval, and [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_intervals_hit=25] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_casts=45] hold one. Where a detection falls inside its interval is not chance: [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_u_late=23] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_inside=29] sit in the later half (binomial tail [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_u_late_p=0.0012], median place [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_u_median=0.83]), a median [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_lead_median_s=104.6] s before the next cast (quartiles [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_lead_q25_s=59.9] s and [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_lead_q75_s=424.9] s). A line voiced at the fill would sit late if a charge fills late and is held before the cast; no stored channel dates either, and the test was chosen after the first look at the data.

### R4: ready onsets against the cast templates

[metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide=93] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ready=261] ready onsets have a cast peak at or above the cast threshold within 0.5 s, against [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide_expected=3.49] expected by chance; [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_near=111] more have one below it. In live time, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_live_collide=46] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_live_ready=167]. [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_sessions_over_one=14] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#sessions=25] sessions hold more than one collision; the median session holds [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_median_per_session=2.0] and the most [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_max_per_session=19]. The cast agent is the ready agent in [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_same_agent=3] collisions. A separate recount from the stored rows, sharing no code with the prototype, gives the same [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ready=261] onsets and [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide=93] collisions, session by session.

Each collision, crossed by the ready agent's class and the cast template's lineup class:

| Ready agent | Cast template impossible | Cast template possible | No lineup |
|---|---|---|---|
| Own agent | none | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_own_possible=1] | none |
| Ally, named | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_ally_named_impossible=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_ally_named_possible=3] | none |
| Enemy, named | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_enemy_named_impossible=14] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_enemy_named_possible=2] | none |
| On neither side | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_absent_impossible=45] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_absent_possible=12] | none |
| No lineup | none | none | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_unknown_unknown=8] |

Most collisions pair a cast template the lineup rules out, which the adjudicator refuses; [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_pair_absent_impossible=45] pair two agents the lineup excludes, one sound firing both template sets. Only the pairs with a possible cast template could reach an event. They include a cast line firing ready templates (a strong Clove enemy cast beside Reyna's ready take on `ff636d173b07`) as well as the reverse, and the stored scores cannot tell the two apart.

| Session | Ready onsets | Collisions | Near misses |
|---|---|---|---|
| `043bafca271a` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_043bafca271a_ready=6] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_043bafca271a_collide=2] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_043bafca271a_near=1] |
| `0c6c52a65b9e` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_0c6c52a65b9e_ready=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_0c6c52a65b9e_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_0c6c52a65b9e_near=0] |
| `223d636bf8d2` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_223d636bf8d2_ready=11] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_223d636bf8d2_collide=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_223d636bf8d2_near=3] |
| `3694746e4e54` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_3694746e4e54_ready=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_3694746e4e54_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_3694746e4e54_near=2] |
| `5822b6646448` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_5822b6646448_ready=41] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_5822b6646448_collide=19] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_5822b6646448_near=20] |
| `587c15b07779` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_587c15b07779_ready=4] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_587c15b07779_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_587c15b07779_near=3] |
| `59c70f1ef720` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_59c70f1ef720_ready=25] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_59c70f1ef720_collide=13] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_59c70f1ef720_near=11] |
| `6ab7a9e99235` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6ab7a9e99235_ready=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6ab7a9e99235_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6ab7a9e99235_near=0] |
| `6afc32cb46b4` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6afc32cb46b4_ready=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6afc32cb46b4_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_6afc32cb46b4_near=0] |
| `7010b3d62460` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_7010b3d62460_ready=2] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_7010b3d62460_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_7010b3d62460_near=1] |
| `75a55a296d3b` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_75a55a296d3b_ready=13] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_75a55a296d3b_collide=4] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_75a55a296d3b_near=6] |
| `96aa1ae9b96f` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_96aa1ae9b96f_ready=14] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_96aa1ae9b96f_collide=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_96aa1ae9b96f_near=5] |
| `9acf02f98283` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_9acf02f98283_ready=14] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_9acf02f98283_collide=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_9acf02f98283_near=6] |
| `a06f04a0059f` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a06f04a0059f_ready=10] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a06f04a0059f_collide=3] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a06f04a0059f_near=5] |
| `a1a995e6b19b` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a1a995e6b19b_ready=4] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a1a995e6b19b_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_a1a995e6b19b_near=2] |
| `aab12e41dcfc` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_aab12e41dcfc_ready=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_aab12e41dcfc_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_aab12e41dcfc_near=0] |
| `b3b9defb6fd7` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b3b9defb6fd7_ready=22] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b3b9defb6fd7_collide=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b3b9defb6fd7_near=10] |
| `b7d24102a6f6` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b7d24102a6f6_ready=10] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b7d24102a6f6_collide=2] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_b7d24102a6f6_near=6] |
| `bdfdcf009dba` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bdfdcf009dba_ready=19] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bdfdcf009dba_collide=7] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bdfdcf009dba_near=5] |
| `bfad2778a372` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bfad2778a372_ready=7] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bfad2778a372_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_bfad2778a372_near=5] |
| `c40d950031bb` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c40d950031bb_ready=12] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c40d950031bb_collide=5] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c40d950031bb_near=1] |
| `c62c2b06bcfb` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c62c2b06bcfb_ready=19] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c62c2b06bcfb_collide=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_c62c2b06bcfb_near=6] |
| `e37fdeca944f` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_e37fdeca944f_ready=8] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_e37fdeca944f_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_e37fdeca944f_near=6] |
| `fc02a2c1ac01` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_fc02a2c1ac01_ready=1] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_fc02a2c1ac01_collide=0] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_fc02a2c1ac01_near=0] |
| `ff636d173b07` | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ff636d173b07_ready=14] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ff636d173b07_collide=7] | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ff636d173b07_near=7] |

### The heard line

The player heard a Skye ready line on `c40d950031bb` at 678.1 s. Skye's best take peaks [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_offset_s=0.33] s later at [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_score=0.0506], under the threshold, and ranks [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_rank=5] of the [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_agents_at_onset=29] agents with a stored peak within 0.5 s of it. Miks's take scores highest there, [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_top_score=0.0587], and is detected. The lineup names Miks on the player's team and no Skye among the five allies;
it refuses enemy slot 0 between Breach and Skye (margin 0.031, below 0.07), so
Skye is possible on the enemy side, not named. The templates say the line was
Miks's, where the player says Skye's; [domain:abilities/ult-ready-lines] leaves
the hearer open. The best cast peak beside it is Killjoy's enemy line at [metric:ult_ready_lines/evaluate-0.1.0@all-matches#heard_c40d950031bb_cast_max=0.0574], which the adjudicator refuses as impossible. The disagreement is stored, not resolved: only the player's ear can name the speaker.

### Outcomes

Measured values beside each prediction; the orchestrator judges them. The
ledger's outcome rows under task `ult-ready-lines` carry the same numbers.

| Id | Prediction (abridged) | Measured |
|---|---|---|
| R1 | a ready-line section for >= 25 of the 28 agents with an ult asset | [metric:voice_line_harvest/ult-ready@wiki#agents_with_ult_asset_covered=28] of [metric:voice_line_harvest/ult-ready@wiki#agents_with_ult_asset=28], all under the Ultimate Status radio reply ([VOICE_LINE_ASSETS.md](VOICE_LINE_ASSETS.md#ult-ready-lines)) |
| R2 | named agents fire >= 4x as often as excluded agents at the cast lines' rule | named allies [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_ally_to_absent=8.37]x, all named [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_named_to_absent=5.04]x, named enemies [metric:ult_ready_lines/evaluate-0.1.0@all-matches#ratio_enemy_to_absent=1.54]x the absent rate per agent-minute |
| R3 | own line within 3 s of the X charge becoming full on >= half the dated fills | no fill dated ([metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_tray_fill_rows=0] fill rows); [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_intervals_hit=25] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_casts=45] fill intervals hold an own detection against [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_intervals_hit_expected=21.87] by chance; [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_u_late=23] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r3_inside=29] sit in an interval's later half |
| R4 | at most one ready onset per session also scores >= 0.0443 on a cast template | [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_sessions_over_one=14] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#sessions=25] sessions hold more than one; [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide=93] of [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_ready=261] onsets collide against [metric:ult_ready_lines/evaluate-0.1.0@all-matches#r4_collide_expected=3.49] by chance |

### What was not done

- No fill is dated. The tray reader stores drops, not fills; R3's test
  needs a stored fill time, which is a change to `reticle.tray`.
- The not-ready and almost-ready replies were neither fetched nor scored.
  They are the control that separates a radio reply from an unprompted line.
- The threshold is set and evaluated on the same sessions; none is held out.
- The heard line is not resolved: nobody has listened to the Miks and Skye
  takes against the capture.
- No events: the prototype writes nothing under `events/` or `labels/`, feeds
  nothing to the cast adjudicator, and `reticle/` does not import it.
- `architecture.toml` declares layers for `reticle/` modules only, so the
  prototype has no placement there.
