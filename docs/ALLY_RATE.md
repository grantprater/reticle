# Ally icon sampling rate: 15, 5 or 2 Hz

2026-09-29. The player asked whether 2 Hz still degrades ally tracking and the
detection of invariant violations now that classification is better (the
teardrop, `agent-identity-0.9.0`, `death-adjudication-0.19.0`), and whether 5 Hz
matches 15 Hz. The 2026-09-25 run (`minimap-fidelity` in the store's
`notes/predictions.jsonl`) gave segment identity 0.57-0.62 from 5 to 15 Hz and
0.42 at 2 Hz.

**Answer.** 5 Hz names teammates as well as 15 Hz does. It finds about half of
the reachability breaks that 15 Hz finds, and those breaks are real errors.
2 Hz stays ruled out: it names fewer of the player's labelled icons, and it
misses most reachability breaks. Its tracker also loses real teammates at
stacks and mints them again.

Outputs, sheets and scripts: `~/reticle-store/analysis/ally-rate-20260929/`.
Predictions and outcome: `ally-rate-20260929` in the store's
`notes/predictions.jsonl`.

## Method

Sessions: `a06f04a0059f` (C:\Users\grant\Videos\2026-08-26 09-56-37.mp4,
Ascent, 465 px), `5822b6646448` (C:\Users\grant\Videos\2026-08-26 12-38-38.mp4,
Lotus, 465 px), `a1a995e6b19b` (C:\Users\grant\Videos\2026-09-08 13-09-13.mp4,
Sunset, 465 px), `75a55a296d3b` (C:\Users\grant\Videos\2026-08-24 13-34-38.mp4,
Abyss, 331 px) and `223d636bf8d2` (C:\Users\grant\Videos\2026-08-23 20-09-01.mp4,
Haven, 331 px). No video was decoded.

1. The current reader (`ally-icon-0.5.0`) read every cached round frame of
   each session once, at 15 Hz, from the minimap crop cache (`--from cache`)
   into a scratch store.
2. The reader reads each frame on its own, so a 5 or 2 Hz stream is the
   subset of rows at the cached times `roi_cache.nearest_times` picks for the
   decode grid. On `a06f04a0059f` a direct 5 Hz cache run wrote the same
   [metric:ally_rate/verify@a06f04a0059f#frame_rows=7733] frame rows
   ([metric:ally_rate/verify@a06f04a0059f#frames_equal=1]) and
   [metric:ally_rate/verify@a06f04a0059f#icon_rows=13737] icon rows
   ([metric:ally_rate/verify@a06f04a0059f#icons_equal=1]) as the subset. Every
   comparison below pairs the rates on the same frames.
3. `prototypes/minimap_fidelity.py` builds the round entities for each rate
   with `session_lifetimes` and the same inputs `reticle lifetimes` passes it.
   It builds each rate twice. The production build uses the stored death
   verdicts. The independent build omits them and is scored against the
   killfeed: exactly one ally segment must end within [-500, +700] ms of a
   teammate's death, and the player's own deaths are excluded. It then counts
   invariant violations per round, scores the player's `labels/death_icon`
   answers and bootstraps rounds, paired across rates (2000 draws; 95%
   intervals in brackets).

The violation checks run on the production build. A flag of one kind, round
and agent within 1 s of another counts once, so a faster rate gets no extra
count for looking more often.

- `reach`: consecutive observations of one named teammate farther apart than
  `RUN_PX` allows over the interval, plus `REFIT_SEPARATION_PX` and twice
  `FIT_ERR_PX`, all scaled.
- `swap`: one segment whose pieces carry different names.
- `overlap`: one agent's pieces overlapping in time.
- `dup_frame`: one agent on two icons in one frame.
- `orphan_birth`: a mid-round birth far from every track end in the last 3 s
  and from every icon.
- `over_capacity`: more ally icons than the roster licenses.
- `death_no_end`: a teammate death with no segment ending near it.

## Results

Five sessions, 112 rounds.

| measure | 15 Hz | 5 Hz | 2 Hz | 15 - 5 | 15 - 2 |
|---|---|---|---|---|---|
| ally segments per round | [metric:ally_rate/structure@five-sessions#segments_per_round_15=9.625] | [metric:ally_rate/structure@five-sessions#segments_per_round_5=7.696] | [metric:ally_rate/structure@five-sessions#segments_per_round_2=7.08] | [metric:ally_rate/structure@five-sessions#segments_per_round_d15_5=1.929] (1.46, 2.42) | [metric:ally_rate/structure@five-sessions#segments_per_round_d15_2=2.545] (1.86, 3.32) |
| ally pieces per round | [metric:ally_rate/structure@five-sessions#pieces_per_round_15=17.821] | [metric:ally_rate/structure@five-sessions#pieces_per_round_5=13.857] | [metric:ally_rate/structure@five-sessions#pieces_per_round_2=11.455] | [metric:ally_rate/structure@five-sessions#pieces_per_round_d15_5=3.964] (3.01, 4.91) | [metric:ally_rate/structure@five-sessions#pieces_per_round_d15_2=6.366] (5.03, 7.76) |
| named share of ally observations | [metric:ally_rate/structure@five-sessions#named_obs_share_15=0.631] | [metric:ally_rate/structure@five-sessions#named_obs_share_5=0.633] | [metric:ally_rate/structure@five-sessions#named_obs_share_2=0.632] | [metric:ally_rate/structure@five-sessions#named_obs_share_d15_5=-0.002] (-0.013, 0.010) | [metric:ally_rate/structure@five-sessions#named_obs_share_d15_2=-0.001] (-0.013, 0.011) |
| named share of pieces | [metric:ally_rate/structure@five-sessions#named_piece_share_15=0.484] | [metric:ally_rate/structure@five-sessions#named_piece_share_5=0.533] | [metric:ally_rate/structure@five-sessions#named_piece_share_2=0.579] | [metric:ally_rate/structure@five-sessions#named_piece_share_d15_5=-0.049] (-0.069, -0.029) | [metric:ally_rate/structure@five-sessions#named_piece_share_d15_2=-0.095] (-0.121, -0.069) |
| killfeed: segment right, of scored | [metric:ally_rate/killfeed@five-sessions#right_of_scored_15=0.8] | [metric:ally_rate/killfeed@five-sessions#right_of_scored_5=0.765] | [metric:ally_rate/killfeed@five-sessions#right_of_scored_2=0.656] | [metric:ally_rate/killfeed@five-sessions#right_of_scored_d15_5=0.035] (-0.015, 0.089) | [metric:ally_rate/killfeed@five-sessions#right_of_scored_d15_2=0.144] (0.041, 0.253) |
| killfeed: deaths bound to one segment end | [metric:ally_rate/killfeed@five-sessions#bound_share_15=0.498] | [metric:ally_rate/killfeed@five-sessions#bound_share_5=0.426] | [metric:ally_rate/killfeed@five-sessions#bound_share_2=0.3] | [metric:ally_rate/killfeed@five-sessions#bound_share_d15_5=0.073] (0.032, 0.115) | [metric:ally_rate/killfeed@five-sessions#bound_share_d15_2=0.199] (0.137, 0.261) |
| killfeed, window widened one step: right, of scored | [metric:ally_rate/killfeed@five-sessions#wide_right_of_scored_15=0.836] | [metric:ally_rate/killfeed@five-sessions#wide_right_of_scored_5=0.827] | [metric:ally_rate/killfeed@five-sessions#wide_right_of_scored_2=0.786] | [metric:ally_rate/killfeed@five-sessions#wide_right_of_scored_d15_5=0.009] (-0.030, 0.053) | [metric:ally_rate/killfeed@five-sessions#wide_right_of_scored_d15_2=0.05] (0.001, 0.106) |
| killfeed, window widened: bound | [metric:ally_rate/killfeed@five-sessions#wide_bound_share_15=0.533] | [metric:ally_rate/killfeed@five-sessions#wide_bound_share_5=0.552] | [metric:ally_rate/killfeed@five-sessions#wide_bound_share_2=0.511] | [metric:ally_rate/killfeed@five-sessions#wide_bound_share_d15_5=-0.019] (-0.059, 0.021) | [metric:ally_rate/killfeed@five-sessions#wide_bound_share_d15_2=0.022] (-0.033, 0.074) |
| player's death-icon labels named right, of [metric:ally_rate/labels@five-sessions#labels=57] | [metric:ally_rate/labels@five-sessions#right_15=40] | [metric:ally_rate/labels@five-sessions#right_5=40] | [metric:ally_rate/labels@five-sessions#right_2=35] | [metric:ally_rate/labels@five-sessions#right_d15_5=0] (-3, 3) | [metric:ally_rate/labels@five-sessions#right_d15_2=5] (0, 11) |

The killfeed rows count [metric:ally_rate/killfeed_counts@five-sessions#deaths_15=317]
teammate deaths. With the fixed window, 15 Hz scores
[metric:ally_rate/killfeed_counts@five-sessions#scored_15=115] of them, 5 Hz
[metric:ally_rate/killfeed_counts@five-sessions#scored_5=98] and 2 Hz
[metric:ally_rate/killfeed_counts@five-sessions#scored_2=61]. A slower rate
last sees the dying icon up to one step earlier, so the fixed window drops its
deaths. Moving the window's early edge back by one step (67, 200 or 500 ms)
closes the 5 Hz gap entirely and most of the 2 Hz gap. On the
[metric:ally_rate/killfeed_common@five-sessions#n=65] deaths that all three
rates bind, 15 Hz and 5 Hz name
[metric:ally_rate/killfeed_common@five-sessions#right_15=33] and
[metric:ally_rate/killfeed_common@five-sessions#right_5=33] right, and 2 Hz
names [metric:ally_rate/killfeed_common@five-sessions#right_2=30].

For the labels, the production build names none wrong at 15 or 2 Hz, and
[metric:ally_rate/labels@five-sessions#wrong_5=1] wrong at 5 Hz: a Neon on
`75a55a296d3b` at 1124 s named Raze. It leaves
[metric:ally_rate/labels@five-sessions#unnamed_15=17],
[metric:ally_rate/labels@five-sessions#unnamed_5=16] and
[metric:ally_rate/labels@five-sessions#unnamed_2=22] unnamed. Seven labels that
15 and 5 Hz name are unnamed at 2 Hz, and two that 15 Hz leaves unnamed are
named at 2 Hz.

The lower rates make fewer segments, but not because they track better. Each
extra 15 Hz segment is a transient false fit, or a second track on one icon,
that a sparser rate never reads.

### Invariant violations, episodes per round

| check | 15 Hz | 5 Hz | 2 Hz | 15 - 5 | 15 - 2 |
|---|---|---|---|---|---|
| reach | [metric:ally_rate/violations@five-sessions#reach_15=0.473] | [metric:ally_rate/violations@five-sessions#reach_5=0.348] | [metric:ally_rate/violations@five-sessions#reach_2=0.125] | [metric:ally_rate/violations@five-sessions#reach_d15_5=0.125] (-0.009, 0.259) | [metric:ally_rate/violations@five-sessions#reach_d15_2=0.348] (0.214, 0.491) |
| swap | [metric:ally_rate/violations@five-sessions#swap_15=1.893] | [metric:ally_rate/violations@five-sessions#swap_5=1.821] | [metric:ally_rate/violations@five-sessions#swap_2=1.58] | [metric:ally_rate/violations@five-sessions#swap_d15_5=0.071] (-0.277, 0.420) | [metric:ally_rate/violations@five-sessions#swap_d15_2=0.312] (-0.098, 0.741) |
| overlap | [metric:ally_rate/violations@five-sessions#overlap_15=0.893] | [metric:ally_rate/violations@five-sessions#overlap_5=0.464] | [metric:ally_rate/violations@five-sessions#overlap_2=0.277] | [metric:ally_rate/violations@five-sessions#overlap_d15_5=0.429] (0.223, 0.643) | [metric:ally_rate/violations@five-sessions#overlap_d15_2=0.616] (0.420, 0.821) |
| orphan_birth | [metric:ally_rate/violations@five-sessions#orphan_birth_15=1.42] | [metric:ally_rate/violations@five-sessions#orphan_birth_5=1.018] | [metric:ally_rate/violations@five-sessions#orphan_birth_2=0.821] | [metric:ally_rate/violations@five-sessions#orphan_birth_d15_5=0.402] (0.223, 0.598) | [metric:ally_rate/violations@five-sessions#orphan_birth_d15_2=0.598] (0.375, 0.830) |
| over_capacity | [metric:ally_rate/violations@five-sessions#over_capacity_15=1.429] | [metric:ally_rate/violations@five-sessions#over_capacity_5=0.946] | [metric:ally_rate/violations@five-sessions#over_capacity_2=0.545] | [metric:ally_rate/violations@five-sessions#over_capacity_d15_5=0.482] (0.312, 0.670) | [metric:ally_rate/violations@five-sessions#over_capacity_d15_2=0.884] (0.652, 1.125) |
| death_no_end | [metric:ally_rate/violations@five-sessions#death_no_end_15=1.143] | [metric:ally_rate/violations@five-sessions#death_no_end_5=1.438] | [metric:ally_rate/violations@five-sessions#death_no_end_2=1.857] | [metric:ally_rate/violations@five-sessions#death_no_end_d15_5=-0.295] (-0.402, -0.196) | [metric:ally_rate/violations@five-sessions#death_no_end_d15_2=-0.714] (-0.857, -0.562) |

No frame at any rate names one agent on two icons (`dup_frame`), because the
piece assignment forbids it.

Flags matched across rates (same round, within 1 s, same agent or within 30 px):

| check | 15 Hz flags 5 Hz misses | 15 Hz flags 2 Hz misses | 5 Hz flags 15 Hz misses | 2 Hz flags 15 Hz misses |
|---|---|---|---|---|
| reach | [metric:ally_rate/matching@five-sessions#reach_15_not_5=26] (matched [metric:ally_rate/matching@five-sessions#reach_15_and_5=27]) | [metric:ally_rate/matching@five-sessions#reach_15_not_2=42] (matched [metric:ally_rate/matching@five-sessions#reach_15_and_2=11]) | [metric:ally_rate/matching@five-sessions#reach_5_not_15=12] | [metric:ally_rate/matching@five-sessions#reach_2_not_15=4] |
| orphan_birth | [metric:ally_rate/matching@five-sessions#orphan_birth_15_not_5=73] | [metric:ally_rate/matching@five-sessions#orphan_birth_15_not_2=113] | [metric:ally_rate/matching@five-sessions#orphan_birth_5_not_15=28] | [metric:ally_rate/matching@five-sessions#orphan_birth_2_not_15=46] |
| overlap | [metric:ally_rate/matching@five-sessions#overlap_15_not_5=87] | [metric:ally_rate/matching@five-sessions#overlap_15_not_2=95] | [metric:ally_rate/matching@five-sessions#overlap_5_not_15=39] | [metric:ally_rate/matching@five-sessions#overlap_2_not_15=26] |
| swap | [metric:ally_rate/matching@five-sessions#swap_15_not_5=126] | [metric:ally_rate/matching@five-sessions#swap_15_not_2=151] | [metric:ally_rate/matching@five-sessions#swap_5_not_15=118] | [metric:ally_rate/matching@five-sessions#swap_2_not_15=115] |

### What the sheets show

The contact sheets, `sheet_<check>_<a>_not_<b>.png`, show eight sampled flags
per check and pair. Each row shows the cached minimap three times, with each
15 Hz observation's name in yellow.

- **reach, 15 Hz only (vs 2 and vs 5 Hz).** All eight 15-not-2 flags are
  real errors. Three are a teammate's name passing to another teammate
  (Raze and Neon on `75a55a296d3b`, Reyna and Skye on `223d636bf8d2`). Two are
  confusions inside a stack. Three are a name on a false fit: an empty map
  spot on `a1a995e6b19b`, the void behind the widget on `5822b6646448`, and
  one Raze on `75a55a296d3b`. Among the 15-not-5 flags, a Chamber name lands
  on a Chamber device. Two flags may be real movement, not errors: Omen
  moving 44 px in 250 ms on `5822b6646448`, and Neon beside a stack. The
  sheets cannot tell; the player can.
- **reach, 2 or 5 Hz only.** These are real errors in that rate's own names:
  the Chamber icon named Astra at 2 Hz, a device named Sage, and names on
  false fits at the end of a blue line drawn across the map. They are not
  false alarms.
- **swap, 15 Hz only.** Every sampled flag is a segment passing through a
  stack of two or three icons, where the Viterbi split changes the name.
  These are real identity hazards, and the split is not always wrong.
- **overlap, 15 Hz only.** Most are two concurrent tracks on one icon, or a
  stack. The name is right, and the fault is fragmentation, not identity.
- **orphan_birth, 15 Hz only.** Six of eight are false fits on the void or on
  screen effects behind the transparent widget
  [domain:minimap/transparency], seen in one or two frames. Two are a real
  Chamber icon reacquired after a miss.
- **orphan_birth, 2 Hz only.** Seven of eight are real teammates reborn beside
  a stack or another icon, where 500 ms association lost them. This is the
  tracking loss the earlier run reported.
- **over_capacity.** Mixed. Some are false fits on the void. The sheet rings
  the frame's first icon, not the extra one, so it cannot say which fit is
  surplus.
- **death_no_end** has no position, so it has no sheet. It rises at lower
  rates because the fixed window misses their earlier last look.

## Confounders

**The run's checkout predated the rescan's reader.** The player's scoreboard
rescan wrote `scoreboard-0.13.0` on several sessions today. This run's code
(82e8499) knew only `scoreboard-0.12.0`, so `load_lineup` refused those
boards as `stale_version scoreboard-0.13.0 != scoreboard-0.12.0` and fell
back to the top bar alone. The top bar refuses Breach and Deadlock on
`a06f04a0059f` (margins 0.008 and 0.011), three slots on `5822b6646448` and
Jett on `75a55a296d3b`. The rescan changed no lineup: from storage, on every
session with both streams, the 0.9.0 and the rescanned boards give the same
five agents per side and the same name and margin in every slot, and current
code names all ten slots on those three sessions, round 4's oracle included
(`lineup.load_lineup` now reports such a board as `code_older_than_store`).
This run names only Miks and Reyna on `a06f04a0059f`, at every rate, with
nothing outside the oracle. The refusal hits every rate alike, so the
comparison stays paired, but it caps the named share.
On the two sessions whose lineups name all four teammates (`223d636bf8d2`,
`a1a995e6b19b`):

- The named share of observations is
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#named_obs_share_15=0.918],
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#named_obs_share_5=0.923]
  and
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#named_obs_share_2=0.924].
- Widened-window killfeed identity is
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#wide_right_of_scored_15=0.892],
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#wide_right_of_scored_5=0.886]
  and
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#wide_right_of_scored_2=0.851].
- Reach breaks per round are
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#reach_15=0.423],
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#reach_5=0.308] and
  [metric:ally_rate/full_lineup@223d636bf8d2+a1a995e6b19b#reach_2=0.058].

The ranking is the same.

**The killfeed window.** It suited 15 Hz, as noted above.

## Speed

Measured on `a06f04a0059f`, one OpenCV thread, Idle priority, while the player
played. The 15 Hz cache pass took
[metric:ally_rate/speed@a06f04a0059f#pass_s_15hz=505.01] s and the direct 5 Hz
pass [metric:ally_rate/speed@a06f04a0059f#pass_s_5hz=224.65] s. That is
[metric:ally_rate/speed@a06f04a0059f#speedup_wall=2.25] times faster by wall
time and [metric:ally_rate/speed@a06f04a0059f#speedup_cpu=1.74] times by CPU,
not the estimated 170 s against 460 s: the cache grabs every frame between
samples. Building the entities costs little beside the pass: 149 s for all
five sessions at 15 Hz, 51 s at 5 Hz.

## Recommendation

Read ally icons at 5 Hz by default. It matches 15 Hz on every identity
measure: the labels, the killfeed with the window widened one step, the named
share, and the deaths every rate binds. It also halves the pass and removes
most transient false-fit segments.

Keep 15 Hz where invariant checks matter. 15 Hz finds more reachability
breaks per round than 5 Hz, and the difference is not significant (interval
-0.009 to 0.259). In the matching, 5 Hz misses about half of the breaks
15 Hz flags, and the sampled misses were real name swaps and named false fits.

2 Hz stays ruled out. It names five fewer labelled icons (interval 0 to 11).
Its widened-window killfeed identity falls 5 points (interval 0.001 to
0.106). It misses most of the 15 Hz reach breaks, and its own extra births
are real teammates lost at stacks. What changed since 2026-09-25 is the
cause: the new classifiers name 2 Hz icons as well as 15 Hz icons (equal
named share, 30 of 65 against 33 on common deaths). 2 Hz now loses on
tracking through stacks and on detecting violations, not on per-icon identity.

## Not done

- The rates were not run on all 20 cached sessions; this is five.
- No decode was run and no decode was timed.
- No new player labels were collected. The `icon_facing` labels test the
  reader on one frame, not the rate, and were not rescored. `labels/minimap`
  holds no ally labels.
- The reach check does not classify dash and teleport agents, so a
  legitimate Omen or Neon move counts as a break.
- The over-capacity sheet does not mark the surplus fit.
- `reticle lifetimes` was not run as a command against a scratch store,
  because its inputs live in the real store. The prototype calls
  `session_lifetimes` with the same arguments and writes each rate's
  `round_entity` rows to a scratch store.
