# Scoreboard round marks: the history strip against the stored scoreline

`prototypes/scoreboard_round_marks.py` reads the round markers on the Tab
board's history strip [domain:hud/scoreboard-round-history-strip] and checks
them against the rounds `reticle.rounds.build_rounds` derives from the stored
scoreline (ledger task `scoreboard-round-marks`, predictions M1 to M5). It
decodes no video: every pixel comes from the `hud` crop cache's `center`
crop, frame x 883-1037 and y 486-594 at 1920x1080. It takes the first sample
the slab test reads open in each 10 s of the [metric:scoreboard/round-marks@all-sessions#sessions=19] lineup sessions:
[metric:scoreboard/round-marks@all-sessions#samples=2155] samples, of which the witness in `prototypes/scoreboard_strip.py`
reads [metric:scoreboard/round-marks@all-sessions#verdict_present=1925] present. The board opens only while the player holds
Tab [domain:hud/scoreboard-tab-hold], so the samples fall where the player
looked, not evenly over a match.

## What the columns hold over a match

The strip is a match history, one column per round, with the second half
right of a separator column. The crop sees rounds 11 and 12, the separator,
and rounds 13 to 17: the lattice column nearest frame x 888 holds round 11 on
every session, at the 21.6 px pitch and at 22.4 px on `b3b9defb6fd7`.

- Through round 10 every column in view carries a black dot on both lines.
- A decided round's column carries the winner's icon, teal on the upper
  (ally) line or red on the lower (enemy) line, and a black dot on the
  loser's line. The icons take several shapes (a crossed square, a pincer,
  an hourglass), not only the crossed circle the domain fact names.
- The separator carries no dot: two thin pale ticks, one from the ally block
  to the upper line and one from the lower line to the enemy block.
- Yellow triangles above and below one column mark the round in play once
  it is in view.
- Each line carries one yellow dot, on the column of round 13 plus the other
  team's total. At 0-0 both sit on round 13, and each round the other team
  wins moves the dot one column right. That column is the earliest round the
  line's team could win the match [domain:rounds/match-end].

The strip records a round at the snap to the next buy phase, not when the
score increments [domain:rounds/post-round-period]. On the column of the round
the scoreline last decided, timed against the next round's clock reset, the
icon shows on [metric:scoreboard/round-marks@all-sessions#decided_col_before_3s_icon=6] of [metric:scoreboard/round-marks@all-sessions#decided_col_before_3s=39]
samples more than 3 s before it, [metric:scoreboard/round-marks@all-sessions#decided_col_last_3s_icon=28] of
[metric:scoreboard/round-marks@all-sessions#decided_col_last_3s=35] in the last 3 s, and [metric:scoreboard/round-marks@all-sessions#decided_col_after_icon=389] of
[metric:scoreboard/round-marks@all-sessions#decided_col_after=391] after it. The triangles stay on that column until the
snap: [metric:scoreboard/round-marks@all-sessions#decided_col_before_3s_triangles=34], [metric:scoreboard/round-marks@all-sessions#decided_col_last_3s_triangles=7]
and [metric:scoreboard/round-marks@all-sessions#decided_col_after_triangles=0] samples in the same three windows.

## The reader

Per column and line, the first rule that matches names the mark:

1. an icon: at least 12 teal or red pixels, by the strip prototype's colour
   rule, within 7 px of the mark, and at most half as many in the ring out
   to 11 px, so a coloured wall or block is not an icon;
2. the separator: a vertical line at least 12 grey levels brighter than the
   band 3 px to either side on at least 0.7 of the tick rows; it outranks the
   dot rules, because its ticks cast a false dark dot and warm a false yellow
   one;
3. a yellow dot, then a black dot (the strip prototype's dark rule);
4. `other`, `unreadable` (a band too dark for a black dot), or `empty`.

A column is current when a triangle window beyond either line holds at least
4 yellow pixels and its flanks at most a quarter as many; the flank test
rejects the local player's yellow row outline, which runs the full width. The
module docstring gives each constant's basis. No constant came from the
rounds, and none is set per session. The store's
`notes/scoreboard-round-marks-samples.jsonl` holds every sample with its
lattice pitch and phase.

## Agreement

Column c holds round c + 11 before the separator and c + 10 after it: the
offsets (11, 10) registered before measuring. Under them
[metric:scoreboard/round-marks@all-sessions#pred_icon_agree=4737] of [metric:scoreboard/round-marks@all-sessions#pred_icon_n_with_sep=4782] icon columns name the stored
winner ([metric:scoreboard/round-marks@all-sessions#pred_agree_frac_with_sep=0.9906]). The misses are [metric:scoreboard/round-marks@all-sessions#pred_icon_icon_unplayed=32]
icons on columns the store has not decided, [metric:scoreboard/round-marks@all-sessions#sep_cols_icon=8] on the separator
column and [metric:scoreboard/round-marks@all-sessions#pred_icon_disagree=5] naming the loser. Of decided columns in view,
[metric:scoreboard/round-marks@all-sessions#played_cols_icon_right=4737] of [metric:scoreboard/round-marks@all-sessions#played_cols=4822] show the winner's icon
([metric:scoreboard/round-marks@all-sessions#played_icon_right_frac=0.9824]), and the loser's line reads black on
[metric:scoreboard/round-marks@all-sessions#loser_line_black=4731]. Of undecided columns away from a stored round end,
[metric:scoreboard/round-marks@all-sessions#unplayed_cols_far_icon=29] of [metric:scoreboard/round-marks@all-sessions#unplayed_cols_far=8037] read an icon
([metric:scoreboard/round-marks@all-sessions#unplayed_far_icon_frac=0.0036]). The lowest session, `96aa1ae9b96f`, agrees on
[metric:scoreboard/round-marks@all-sessions#pred_agree_frac_min_session=0.9714] of its icon columns, over the
[metric:scoreboard/round-marks@all-sessions#sessions_with_20_icon_cols=17] sessions with at least 20.

Fitted per session on icon columns alone, as M1 registered, the best pairs
agree on [metric:scoreboard/round-marks@all-sessions#icons_fit_agree=4741] of [metric:scoreboard/round-marks@all-sessions#icons_fit_n=4782] ([metric:scoreboard/round-marks@all-sessions#icons_fit_agree_frac=0.9914]),
but that fit cannot place the offsets: a shifted pair moves an early or
misread icon onto a decided round and loses nothing on the columns without
an icon. It keeps (11, 10) among its best pairs on
[metric:scoreboard/round-marks@all-sessions#sessions_icons_fit_pred_among_ties=15] sessions. On `3694746e4e54`,
`96aa1ae9b96f`, `bdfdcf009dba` and `e37fdeca944f` a shifted pair wins by one
column. Fitted on every visible column, where a decided round's column with
no icon counts against a pair, (11, 10) is the unique best on
[metric:scoreboard/round-marks@all-sessions#sessions_full_fit_pred_unique=17] sessions and agrees on [metric:scoreboard/round-marks@all-sessions#full_fit_agree=15149] of
[metric:scoreboard/round-marks@all-sessions#full_fit_n=15274] columns ([metric:scoreboard/round-marks@all-sessions#full_fit_agree_frac=0.9918]). It ties on
[metric:scoreboard/round-marks@all-sessions#sessions_full_fit_tied=2]: `75a55a296d3b` and `c40d950031bb`, where few rounds
past the tenth were played. `b3b9defb6fd7`, at its own pitch and phase, fits
(11, 10) uniquely. Column 2 reads separator on [metric:scoreboard/round-marks@all-sessions#sep_cols_separator=1878] of
[metric:scoreboard/round-marks@all-sessions#sep_cols=1925] present samples ([metric:scoreboard/round-marks@all-sessions#sep_separator_frac=0.9756]).

| Session | Icon columns naming the stored winner |
|---|---|
| `043bafca271a` | [metric:scoreboard/round-marks@all-sessions#s_043bafca271a_icon_agree=225] of [metric:scoreboard/round-marks@all-sessions#s_043bafca271a_icon_cols=226] |
| `223d636bf8d2` | [metric:scoreboard/round-marks@all-sessions#s_223d636bf8d2_icon_agree=502] of [metric:scoreboard/round-marks@all-sessions#s_223d636bf8d2_icon_cols=508] |
| `3694746e4e54` | [metric:scoreboard/round-marks@all-sessions#s_3694746e4e54_icon_agree=168] of [metric:scoreboard/round-marks@all-sessions#s_3694746e4e54_icon_cols=170] |
| `5822b6646448` | [metric:scoreboard/round-marks@all-sessions#s_5822b6646448_icon_agree=335] of [metric:scoreboard/round-marks@all-sessions#s_5822b6646448_icon_cols=340] |
| `587c15b07779` | [metric:scoreboard/round-marks@all-sessions#s_587c15b07779_icon_agree=238] of [metric:scoreboard/round-marks@all-sessions#s_587c15b07779_icon_cols=240] |
| `59c70f1ef720` | [metric:scoreboard/round-marks@all-sessions#s_59c70f1ef720_icon_agree=364] of [metric:scoreboard/round-marks@all-sessions#s_59c70f1ef720_icon_cols=366] |
| `7010b3d62460` | [metric:scoreboard/round-marks@all-sessions#s_7010b3d62460_icon_agree=132] of [metric:scoreboard/round-marks@all-sessions#s_7010b3d62460_icon_cols=134] |
| `75a55a296d3b` | [metric:scoreboard/round-marks@all-sessions#s_75a55a296d3b_icon_agree=7] of [metric:scoreboard/round-marks@all-sessions#s_75a55a296d3b_icon_cols=7] |
| `96aa1ae9b96f` | [metric:scoreboard/round-marks@all-sessions#s_96aa1ae9b96f_icon_agree=68] of [metric:scoreboard/round-marks@all-sessions#s_96aa1ae9b96f_icon_cols=70] |
| `9acf02f98283` | [metric:scoreboard/round-marks@all-sessions#s_9acf02f98283_icon_agree=295] of [metric:scoreboard/round-marks@all-sessions#s_9acf02f98283_icon_cols=296] |
| `a06f04a0059f` | [metric:scoreboard/round-marks@all-sessions#s_a06f04a0059f_icon_agree=432] of [metric:scoreboard/round-marks@all-sessions#s_a06f04a0059f_icon_cols=439] |
| `a1a995e6b19b` | [metric:scoreboard/round-marks@all-sessions#s_a1a995e6b19b_icon_agree=294] of [metric:scoreboard/round-marks@all-sessions#s_a1a995e6b19b_icon_cols=296] |
| `b3b9defb6fd7` | [metric:scoreboard/round-marks@all-sessions#s_b3b9defb6fd7_icon_agree=119] of [metric:scoreboard/round-marks@all-sessions#s_b3b9defb6fd7_icon_cols=119] |
| `b7d24102a6f6` | [metric:scoreboard/round-marks@all-sessions#s_b7d24102a6f6_icon_agree=179] of [metric:scoreboard/round-marks@all-sessions#s_b7d24102a6f6_icon_cols=179] |
| `bdfdcf009dba` | [metric:scoreboard/round-marks@all-sessions#s_bdfdcf009dba_icon_agree=168] of [metric:scoreboard/round-marks@all-sessions#s_bdfdcf009dba_icon_cols=169] |
| `bfad2778a372` | [metric:scoreboard/round-marks@all-sessions#s_bfad2778a372_icon_agree=367] of [metric:scoreboard/round-marks@all-sessions#s_bfad2778a372_icon_cols=369] |
| `c40d950031bb` | [metric:scoreboard/round-marks@all-sessions#s_c40d950031bb_icon_agree=0] of [metric:scoreboard/round-marks@all-sessions#s_c40d950031bb_icon_cols=1] |
| `e37fdeca944f` | [metric:scoreboard/round-marks@all-sessions#s_e37fdeca944f_icon_agree=398] of [metric:scoreboard/round-marks@all-sessions#s_e37fdeca944f_icon_cols=403] |
| `ff636d173b07` | [metric:scoreboard/round-marks@all-sessions#s_ff636d173b07_icon_agree=446] of [metric:scoreboard/round-marks@all-sessions#s_ff636d173b07_icon_cols=450] |

## Disagreements

A montage of 12 icon disagreements, drawn by the `montage` command, shows
four causes:

- World colour behind the strip, on 8: a character's red and teal parts,
  red-and-white awnings, red and magenta ability streaks, fire, and an orange
  speckled surface pass the icon colour rules on an undecided column or on
  the loser's line.
- The crop edge, on 2: the winner's icon on column 0 or column 7 sits half
  outside the crop.
- The end-of-match board, on 1: red and teal blocks fill the band.
- Board lag, on 1: at `e37fdeca944f` 1455 s the store has decided round 15,
  and the board still shows it undecided with the triangles on it.

At halftime on `3694746e4e54` (1221 s) and `bdfdcf009dba` (1321.5 s) the
board shows round 12's icon before the store decides round 12; there the
store takes round 13's start from the score increment, not a clock reset.

## The yellow dot and the triangles

[metric:scoreboard/round-marks@all-sessions#yellow_at_13_plus_other=1673] of [metric:scoreboard/round-marks@all-sessions#yellow_cells=1786] yellow cells sit at 13 plus
the other team's total ([metric:scoreboard/round-marks@all-sessions#yellow_13_plus_other_frac=0.9367]). Where that column
differs from 13 plus the line's own total, [metric:scoreboard/round-marks@all-sessions#yellow_only_13_plus_other=1342] cells
sit on the first and [metric:scoreboard/round-marks@all-sessions#yellow_only_13_plus_own=19] on the second;
[metric:scoreboard/round-marks@all-sessions#yellow_at_current=4] sit on the current round's column.

[metric:scoreboard/round-marks@all-sessions#current_at_current=522] of [metric:scoreboard/round-marks@all-sessions#current_cols=589] triangle columns sit on the round
after the last one the store decided ([metric:scoreboard/round-marks@all-sessions#current_at_current_frac=0.8862]). Outside
the post-round period, [metric:scoreboard/round-marks@all-sessions#live_current_at_current=491] of [metric:scoreboard/round-marks@all-sessions#live_current_cols=516] do
([metric:scoreboard/round-marks@all-sessions#live_current_at_current_frac=0.9516]); in it the triangles stay on the round just
decided until the buy-phase snap.

## Predictions

- M1, icon team against the stored winner at 0.9 or better: holds.
- M2, one offset pair (11, 10) on every session: refuted as registered,
  because the icons-only fit shifts on four sessions; the fit on every
  column confirms (11, 10) wherever rounds past the tenth were played, and
  the separator holds.
- M3, the yellow dot at 13 plus the other team's total: holds by its
  falsifier; its "never" clause fails on the few cells above.
- M4, triangles on the current round at 0.9 or better: refuted, because the
  strip lags the score through the post-round period.
- M5, icons on under 0.02 of undecided columns: holds.

The prototype stays unwired (ledger decision, `"wire": "no"`). The strip
repeats stored round outcomes while the player holds Tab and lags them until
the buy phase, so it can check the scoreline but adds no round the
scoreline lacks.
