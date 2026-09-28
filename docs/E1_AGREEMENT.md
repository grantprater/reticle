# E1: agreeing totals concealed binding errors — 2026-09-28

**Outcome: the prediction held.** In two rounds where the killfeed, the combat
report and the scoreboard agreed, the owner left the player's death panel
unbound; the fix exposed four panels bound to the wrong killer and a killfeed
track that merged an enemy's death into the player's. Totals cannot see a
binding, so agreement is no acceptance test: score events one to one. Only
the owner fixes are promoted before the player's source review. E1 belongs to
[the experiment program](EXPERIMENT_PROGRAM.md).

## Prediction and replay

Ledger entry `e1-agreement-2026-09-27` (revised as `e1-agreement-2026-09-28`)
predicted that agreeing per-round kill and death counts do not establish that
each death binds to its true witness, identity and life episode. The pin names
18 sessions (`checks.KNOWN_KD`) and the reader stamps, and refuses a session
whose stamps differ (`0f08b3dc3777`, which stores no HUD data).
`prototypes/e1_agreement.py --replay` compares the three channels per round
without decoding video. It writes `disagreements.json`, with each channel's
stored reason, and `agreeing.json`, each three-way round's kills and deaths
bound to killfeed entry, identity verdict, life episode and report panel.

## Results

Of [metric:e1_agreement/replay@pinned-18#rounds=353] rounds,
[metric:e1_agreement/replay@pinned-18#three_way=59] agreed three ways,
[metric:e1_agreement/replay@pinned-18#disagree=9] disagreed, and
[metric:e1_agreement/replay@pinned-18#unwitnessed=19] had fewer than two
channels. The seeded rounds hold
[metric:e1_agreement/replay@pinned-18#seeded_deaths=40] player deaths; the
report bound [metric:e1_agreement/replay@pinned-18#deaths_report_bound=38] of
them and flagged [metric:e1_agreement/replay@pinned-18#flagged=2] rounds.
[metric:e1_agreement/replay@pinned-18#names_unnamed=18] of the 59 seeded rounds
leave a kill victim or a KILLED row unnamed.

## Flagged rounds and the owner fix

In `223d636bf8d2` and `c40d950031bb` round 6 the death panel opened before the
killfeed entry; the owner called it at-death by one window and refused to bind
it by another. One window, `near_death` (combat-report-round-0.9.0), binds both
([metric:e1_agreement/replay@c40d950031bb#flagged=0] flagged on `c40d950031bb`;
`223d636bf8d2` holds only its 0.8.0 row,
[metric:e1_agreement/replay@223d636bf8d2#flagged=1]).

The narrower lookback exposed four killed, revived and killed-again panels
(`a1a995e6b19b` 638 s, `b3b9defb6fd7` 891 s and 1308 s, `b7d24102a6f6` 1912 s),
whose two KILLED YOU rows both bound to the later killer; at 0.9.0 neither
bound (ledger `e1-binding-window-2026-09-28`, `e1-double-binding-2026-09-28`).

At combat-report-round-0.10.0 the killer's killfeed portrait names a KILLED YOU
row only when it is its panel's one. In a two-row panel a row binds by the
portrait cluster an earlier panel bound, the other to the death left, both with
`depends_on`; all eight bind. A repeated read with no later death is a reopen
(`5822b6646448` 1093 s, `587c15b07779` 1386 s). Over 20 sessions no verdict K/D
or round count moved; `b7d24102a6f6` cluster 4, a Raze resting on the wrong
claim, became a Raze and Reyna disagreement. The prediction missed the
`587c15b07779` fold, so the ledger records it as not held
(`e1-report-naming-2026-09-28`).

No flagged round hid a duplicate beside a miss; the errors were bindings.

## The merged killfeed track

`59c70f1ef720` round 16 bound no death because one killfeed track held an
enemy-victim entry (slot 0, 1619.5 to 1624.0 s) and, after one missed sample,
an ally-victim entry at 1625.0 s. The player's death took the key
`death:59c70f1ef720:1619500:0`, the enemy side, a teammate (Sage) as killer,
and an onset outside the panel's window. E1 stops at an upstream identity
failure, so the fix went to the hud-invariant owner
(death-adjudication-0.15.0): `checks.track_entries`, given sides by
`adjudication.death.session_entries` alone, ends a track where the victim plate
changes side, unless the track has read a one-colour revive plate.

Walked read-only over the 21 HUD sessions, the split changed no counted kill or
death and added 41 entry tracks in 16 sessions. The 59c7 death moves to
`1625000:0`, ally side; player kills on `3694746e4e54` (1344.5 to 1355.5 s) and
`bfad2778a372` (1436.5 to 1443.0 s) move to enemy-victim entries;
`a06f04a0059f`'s kill onset moves from 412.0 to 411.0 s, unchecked. The
ledger's prediction row (`e1-entry-side-split-2026-09-28`) postdates the
measurement: the measuring agent could not write to the store and stated the
prediction in its report first. The store rerun waits (Open 1).

## Withholding

Without the killfeed portraits and death bindings, the report loses
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_lost=24] of
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_entities=60] row names.
Without the scoreboard,
[metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_changed=54] death
verdicts change, [metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_player_changed=7]
of them the player's: the scoreboard is a load-bearing identity witness. The
control rerun changed
[metric:e1_agreement/replay@pinned-18#deaths_control_changed=0] verdicts.

## Disagreements by stored reason

- Killfeed misses: `e37fdeca944f` rounds 1 and 5 and `5822b6646448` round 19,
  deaths the report saw; `c62c2b06bcfb` round 12, the known Killjoy death.
- Run It Back: in `5822b6646448` round 16 the killfeed books a second life
  [domain:rounds/run-it-back-in-report]; in `bfad2778a372` round 23 it credits
  a kill that the report and the known K/D do not.
- The scoreboard reads the player row sparsely:
  [metric:e1_agreement/replay@pinned-18#player_reads_with_kd=1214] of
  [metric:e1_agreement/replay@pinned-18#player_reads=4836] reads carry K and D,
  and [metric:e1_agreement/replay@pinned-18#boundaries_read=126] of
  [metric:e1_agreement/replay@pinned-18#boundaries=370] boundaries read; two
  rest on one misread row (`b7d24102a6f6` boundary 11, `bdfdcf009dba`
  boundary 17).

The combat-report verdict equals `checks.KNOWN_KD` on all 17 sessions
([metric:e1_agreement/replay@pinned-18#verdict_sessions_off_known=0] off).

## For the player to review

Against source, before promotion:

1. The 59 seeded agreeing rounds in `agreeing.json`.
2. The eight cluster-bound rows, which rest on an earlier panel's binding and
   the portrait clustering, and the two folded panels.
3. The `59c70f1ef720` death at 1625 s, whose killer no stored verdict now names.
4. Why a death panel opens 2 to 2.5 s before its killfeed entry; the comment on
   `near_death` believes the death flash washes the killfeed plates.

## Open

1. The store rerun, in order: `reticle deaths` on the 20 sessions with a death
   stream (every HUD session but `4f207c0c4e39`); `reticle combat-report` on
   the same 20, whose identity step drops death rows stamped other than the
   code's; a new pin (combat-report-round-0.10.0, death-adjudication-0.15.0,
   scoreboard-0.9.0); one recorded `--replay`. It waits for another session,
   whose scoreboard rescan rewrites the `events/scoreboard` that
   `reticle deaths` reads and whose ult-cast and ability-state streams depend
   on the death stamp. The old pin refuses every session.
2. `3694746e4e54` and `a06f04a0059f` each still carry one player death owned by
   an enemy-victim entry.
3. The `scoreboard_kd` claim still names both rows of a two-row panel whose
   bound holds one agent; it fired on none of the 20 sessions.
4. A two-read rule for the scoreboard player row, predicted before it is built.
5. The `a06f04a0059f` kill onset at 411 s.
