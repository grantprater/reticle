# E1: agreeing totals concealed binding errors — 2026-09-28

**Outcome: the prediction held.** Agreeing totals did not establish event
correspondence. In two rounds where the killfeed, the combat report and the
scoreboard agreed, the owner left the player's death panel unbound; fixing that
exposed four panels elsewhere bound to the wrong killer. Each error was a
binding, which totals cannot see. The player has not yet
reviewed the agreeing rounds against source, so nothing is promoted but one
owner fix. The experiment is E1 of [the experiment program](EXPERIMENT_PROGRAM.md).

## Question and prediction

Can agreement of the three channels' per-round kill and death counts conceal a
wrong event history? Ledger entry `e1-agreement-2026-09-27` (revised as
`e1-agreement-2026-09-28` after the fix below) predicted that it can: the
channels localise errors, but agreeing totals do not establish that each death
binds to its true witness, identity and life episode.

## The pin and the replay

The pin names 18 sessions (`checks.KNOWN_KD`) and the reader stamps; the runner
refuses any session whose stamps differ. `0f08b3dc3777` stores no HUD, rounds,
death, report or scoreboard data and was refused.
`prototypes/e1_agreement.py --replay` decodes no video. Per round it reads the
killfeed's player kills and deaths, the combat report's verdict, and the
scoreboard's outlined player row differenced across the round. It writes, under
the store's `analysis/e1-agreement/`, `disagreements.json` (every round where
two channels differ, with each channel's stored reason) and `agreeing.json`
(the three-way rounds, each kill and death bound to its killfeed entry,
identity verdict and life episode, and the report's panels bound through
`adjudication.combat_report`). `tests/test_e1_agreement.py` tests the
duplicate-plus-miss check on synthetic rounds, never counted as evidence.

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
leave a kill victim or a KILLED row unnamed, so agreeing totals leave names open.

## Flagged rounds and the owner fix

`223d636bf8d2` round 6 (panel 719.0 s, death 721.0 s) and `c40d950031bb`
round 6 (panel 701.0 s, death 703.5 s): each panel opened before its killfeed
entry. The owner called each panel at-death by one window and refused to bind it
by another. The fix gives both rules one window, `near_death`
(combat-report-round-0.9.0); both rounds now bind
([metric:e1_agreement/replay@c40d950031bb#flagged=0] flagged on `c40d950031bb`
at 0.9.0; `223d636bf8d2` holds only its 0.8.0 row,
[metric:e1_agreement/replay@223d636bf8d2#flagged=1]).

The narrower lookback exposed four panels from killed, revived and killed-again
rounds (`a1a995e6b19b` 638 s, `b3b9defb6fd7` 891 s and 1308 s, `b7d24102a6f6`
1912 s). Each shows two KILLED YOU rows, and the old rule bound both to the
later death's killer: one wrong binding each. A row now binds only as its
panel's one KILLED YOU row, so those rows bind neither. `reticle combat-report`
reran from storage on 20 sessions with no round row, panel or verdict changed.
Ledger: `e1-binding-window-2026-09-28`, `e1-double-binding-2026-09-28`.

No flagged round hid a duplicate beside a miss: each held the deaths the
channels counted, and the errors were bindings.

## Withholding

Without the killfeed portraits and death bindings, the report loses
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_lost=24] of
[metric:e1_agreement/replay@pinned-18#rows_no_killfeed_entities=60] row names.
Without the scoreboard,
[metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_changed=54] death
verdicts change, [metric:e1_agreement/replay@pinned-18#deaths_no_scoreboard_player_changed=7]
of them the player's: the scoreboard is a load-bearing identity witness, not a
corroborator. The control rerun with every channel changed
[metric:e1_agreement/replay@pinned-18#deaths_control_changed=0] verdicts.

## Disagreements by stored reason

- The killfeed missed a death that the report and the scoreboard both saw
  (`e37fdeca944f` round 5), and deaths the report alone saw (`e37fdeca944f`
  round 1, `5822b6646448` round 19).
- `5822b6646448` round 16: the report counts the real death after a Run It Back
  death; the killfeed books a second life and counts none
  [domain:rounds/run-it-back-in-report].
- `bfad2778a372` round 23: the killfeed counts a kill on an enemy Phoenix
  inside Run It Back, which the report and the known K/D do not credit (the
  `checks.KNOWN_KD` comment).
- `c62c2b06bcfb` round 12: the known Killjoy death the killfeed never counted.
- The scoreboard reads the outlined player row sparsely:
  [metric:e1_agreement/replay@pinned-18#player_reads_with_kd=1214] of
  [metric:e1_agreement/replay@pinned-18#player_reads=4836] reads carry both K
  and D, and [metric:e1_agreement/replay@pinned-18#boundaries_read=126] of
  [metric:e1_agreement/replay@pinned-18#boundaries=370] boundaries read. Two
  boundaries rest on one misread row with shifted columns (`b7d24102a6f6`
  boundary 11, which splits rounds 11 and 12; `bdfdcf009dba` boundary 17).

The combat-report verdict equals `checks.KNOWN_KD` on all 17 sessions
([metric:e1_agreement/replay@pinned-18#verdict_sessions_off_known=0] off).

## Conclusion

Withholding localises dependence and the stored reasons localise every
disagreement, but agreement is not an acceptance test: rounds whose totals
agree carried unbound deaths, and their fix exposed wrong bindings
elsewhere. Score events one to one.

## For the player to review

The acceptance's Evidence line requires source review of the seeded agreeing
rounds before promotion; `agreeing.json` lists them. Also confirm why a death
panel opens 2 to 2.5 s before its killfeed entry; the comment above
`near_death` in `reticle/adjudication/combat_report.py` states the belief that
the death flash washes the killfeed plates.

## Open

1. The recorded corpus replay at scoreboard-0.9.0 under a new pin, after the
   scoreboard rescan; `043bafca271a` and `223d636bf8d2` have no 0.9.0 row.
2. Bind the right row in a two-killer panel, with `depends_on` the killfeed
   portraits.
3. Two bindings the 5 s lookback lost (`5822b6646448` round 12, `59c70f1ef720`
   round 16): the death stream's onset sits 5.5 s before the panel, and on
   `59c70f1ef720` the HUD death time is 6 s after the onset, a question for the
   death owner.
4. A two-read rule for the scoreboard player row, predicted before it is built.
