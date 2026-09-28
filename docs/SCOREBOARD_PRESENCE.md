# Scoreboard presence: the round-history strip as a witness

`reticle.scoreboard.read_scoreboard` opens the Tab board on its two translucent
team slabs. Between the two blocks the game draws two lines of round markers
[domain:hud/scoreboard-round-history-strip]. `prototypes/scoreboard_strip.py`
reads those markers from stored crops and scores the slab test against them
(ledger task `scoreboard-presence`, predictions S1, S2 and S3). It decodes no
video: every pixel comes from the `hud` crop cache's `center` crop, frame x
883-1037 and y 486-594 at 1920x1080, one crop every 30 frames.

Since 2026-09-27 the witness is a reader: `reticle/scoreboard_strip.py`
(`scoreboard-strip-0.1.0`, the prototype's 0.2.0 rule unchanged) stores it at
every cached frame (`reticle strip`), `read_scoreboard` stores the test that
closed each board (`scoreboard-0.7.0`), and `adjudication.scoreboard`
reconciles the two per sample (`reticle openings`). The prototype stays the
experiment record and imports the reader.

## What the crop shows

The inspection before measuring took open, hole and far-closed samples
from twelve sessions. The crop holds the strip whole. The ally block's last row fills its
top 22 rows and the enemy block's first row starts 83 rows down; between them
lies a dark translucent band with the world showing through. The two marker
lines sit at frame y 527 and 551. A column repeats every 21.6-21.7 px on 18
sessions and every 22.4 px, at another phase, on `b3b9defb6fd7`, so the crop
holds seven or eight columns. Every column carries a mark on both lines: a
black dot with a 2x2 core, a pale yellow-green dot, or a round icon about 12 px
across, teal on the upper (ally) line and red on the lower (enemy) line. One
column may carry a thin pale vertical separator instead, and yellow triangles
mark one column on some boards. The white crosshair sits between the lines.
Over a black world the band turns near black and the black dots vanish.

## The witness

`read_strip` finds black dots (a compact spot at least 15 grey levels under
its 9x9 mean), yellow dots and icons within 3 px of either line, then fits one
column lattice (pitch 20.5-23.5 px, phase free) that puts the most marks in
distinct cells. The strip is `present` when the lattice fills at least six
cells, two on each line, with two columns marked on both lines. The band is
`unreadable` when its median is darker than grey 24, where a black dot cannot
show; otherwise the strip is `absent`. Each sample stores its verdict, reason,
cell counts and mark counts per line and kind in the store's
`notes/scoreboard-strip-samples.jsonl`, disagreements included. No constant is
set per session.

Version 0.1.0 called a dark band `unreadable` only when it held no yellow dot
or icon. It missed [metric:scoreboard/strip-witness@all-sessions#v010_slab_open_absent_at_board=31]
real boards, [metric:scoreboard/strip-witness@all-sessions#v010_misses_dark_band=23]
of them over a near-black band; 0.2.0 reads every dark band as unreadable.

## Results

The run scored [metric:scoreboard/strip-witness@all-sessions#samples_scored=8139]
crops on the 19 lineup sessions: every hole and every single-sample run with
both neighbours, and a seeded sample of open samples and of closed samples
outside any run.

| Samples | Scored | Present | Absent | Unreadable |
|---|---|---|---|---|
| Slab test open (seeded) | [metric:scoreboard/strip-witness@all-sessions#open_n=760] | [metric:scoreboard/strip-witness@all-sessions#open_present=717] | [metric:scoreboard/strip-witness@all-sessions#open_absent=39] | [metric:scoreboard/strip-witness@all-sessions#open_unreadable=4] |
| Closed, 5+ samples from any open one | [metric:scoreboard/strip-witness@all-sessions#far_n=815] | [metric:scoreboard/strip-witness@all-sessions#far_present=127] | [metric:scoreboard/strip-witness@all-sessions#far_absent=668] | [metric:scoreboard/strip-witness@all-sessions#far_unreadable=20] |
| Closed, 1-4 samples from an open one | [metric:scoreboard/strip-witness@all-sessions#near_n=325] | [metric:scoreboard/strip-witness@all-sessions#near_present=107] | [metric:scoreboard/strip-witness@all-sessions#near_absent=215] | [metric:scoreboard/strip-witness@all-sessions#near_unreadable=3] |
| Holes | [metric:scoreboard/strip-witness@all-sessions#hole_n=841] | [metric:scoreboard/strip-witness@all-sessions#hole_present=467] | [metric:scoreboard/strip-witness@all-sessions#hole_absent=367] | [metric:scoreboard/strip-witness@all-sessions#hole_unreadable=7] |
| Single-sample runs | [metric:scoreboard/strip-witness@all-sessions#single_n=1360] | [metric:scoreboard/strip-witness@all-sessions#single_present=1144] | [metric:scoreboard/strip-witness@all-sessions#single_absent=204] | [metric:scoreboard/strip-witness@all-sessions#single_unreadable=12] |

The disagreements are mostly the slab test's, not the witness's. A montage
of each kind, checked by eye:

- **Closed samples the witness reads present are boards.** A montage showed a
  board on [metric:scoreboard/strip-witness@all-sessions#inspect_closed_present_board=24]
  of [metric:scoreboard/strip-witness@all-sessions#inspect_closed_present=24] closed presents, and on [metric:scoreboard/strip-witness@all-sessions#inspect_far_present_board=38]
  of [metric:scoreboard/strip-witness@all-sessions#inspect_far_present=40] far ones; the two false presents sat at the rule's margin (at most
  eight cells or three paired columns), a class that holds only
  [metric:scoreboard/strip-witness@all-sessions#far_present_weak=3] far presents.
- **Open samples the witness reads absent are false opens.** Of the
  slab-open samples scored, the witness reads
  [metric:scoreboard/strip-witness@all-sessions#slab_open_absent=312] absent,
  and only [metric:scoreboard/strip-witness@all-sessions#slab_open_absent_at_board=8]
  of those carry stored slab rows at the full board's place (ally block ending
  near frame y 509, table starting near x 572); a montage of [metric:scoreboard/strip-witness@all-sessions#inspect_open_absent=24] showed a board
  on [metric:scoreboard/strip-witness@all-sessions#inspect_open_absent_board=2].
  The rest show the world or a menu screen with the mouse cursor.
- **Many holes are real closures.** At
  [metric:scoreboard/strip-witness@all-sessions#hole_closed_between_boards=306]
  holes the witness reads the board at both neighbours and nothing between;
  two montages of such crops showed a board on
  [metric:scoreboard/strip-witness@all-sessions#inspect_hole_absent_board=1] of [metric:scoreboard/strip-witness@all-sessions#inspect_hole_absent=48].
  The board left the screen for under a second inside one Tab hold: the
  player holds Tab to open the board and releases it to close, and the game
  never opens or closes it [domain:hud/scoreboard-tab-hold], so each such
  hole is a release and a re-press.

## Why the slab test closes a board

`read_scoreboard` now names the branch that closed each board (`reason`). One
bounded decode of `a06f04a0059f` read [metric:scoreboard/close-reasons@a06f04a0059f#frames_decoded=300] frames the
prototype had scored; every decoded crop equals the cache's crop and every
verdict equals the stored one. Of
[metric:scoreboard/close-reasons@a06f04a0059f#closed_present_n=100] frames where the strip sees the board and the slab
test closed it, [metric:scoreboard/close-reasons@a06f04a0059f#closed_present_red_tall=68] close as `red_tall`,
[metric:scoreboard/close-reasons@a06f04a0059f#closed_present_red_short=17] as `red_short`,
[metric:scoreboard/close-reasons@a06f04a0059f#closed_present_enemy_overlaps_ally=7] as `enemy_overlaps_ally` and
[metric:scoreboard/close-reasons@a06f04a0059f#closed_present_green_tall=7] as `green_tall`. Of
[metric:scoreboard/close-reasons@a06f04a0059f#absent_n=100] frames the strip reads absent,
[metric:scoreboard/close-reasons@a06f04a0059f#absent_green_no_rows=80] close as `green_no_rows`.

A montage of [metric:scoreboard/close-reasons@a06f04a0059f#montage_frames=16] of those closed frames shows a fully
expanded, still board on [metric:scoreboard/close-reasons@a06f04a0059f#montage_board_expanded=16]. On
[metric:scoreboard/close-reasons@a06f04a0059f#montage_world_passes_colour=13] the WORLD passes the slab colour test and
joins the block's run: warm walls, sky and floor pass the red test, so the
tallest red run starts at the history band (rows 500-519) on
[metric:scoreboard/close-reasons@a06f04a0059f#red_tall_run_from_history_band=36] `red_tall` frames and runs to the frame
bottom on [metric:scoreboard/close-reasons@a06f04a0059f#red_tall_run_to_frame_bottom=43]. `_block` keeps the tallest
run, so a real enemy block beside it is lost. A green glass wall or a teal
effect makes `green_tall` the same way. Only on
[metric:scoreboard/close-reasons@a06f04a0059f#montage_slab_fails_colour=3] does the slab itself fail the test: a
lavender haze pulls the translucent enemy slab out of the red hues.

The same flaw reaches open boards. On
[metric:scoreboard/close-reasons@a06f04a0059f#open_present_enemy_bottom_off_board=51] of [metric:scoreboard/close-reasons@a06f04a0059f#open_present_n=100] open
frames the red run ends on the world below the board, and the enemy rows are
anchored there. Their portraits score a median
[metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_off_board_portrait_score_median=0.521] against
[metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_at_board_portrait_score_median=0.91] at the board's place, and
K/D reads on [metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_off_board_kd_read=3] of
[metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_off_board=255] rows against
[metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_at_board_kd_read=133] of [metric:scoreboard/close-reasons@a06f04a0059f#enemy_rows_at_board=245].

## Both witnesses, stored

`reticle strip --all` read [metric:scoreboard/strip@all-sessions#frames=83374] cached frames on
[metric:scoreboard/strip@all-sessions#sessions=20] sessions in [metric:scoreboard/strip@all-sessions#wall_s=301.7] s at Idle priority. At the
[metric:scoreboard/strip@all-sessions#prototype_rows=8139] frames the prototype scored, the stored rows equal
its rows on every field ([metric:scoreboard/strip@all-sessions#prototype_rows_equal=8139]).

`reticle openings --all` reconciles the two on the 19 lineup sessions. The
board is present where the slab test opened it or the strip reads present.
Before, the slab test alone: [metric:scoreboard/openings@all-sessions-slab-only#samples_open=10269] open samples,
[metric:scoreboard/openings@all-sessions-slab-only#runs=3111] holds, [metric:scoreboard/openings@all-sessions-slab-only#runs_single_sample=1360] single-sample holds and
[metric:scoreboard/openings@all-sessions-slab-only#holes=841] holes. Combined: [metric:scoreboard/openings@all-sessions#samples_open=25620] present samples,
[metric:scoreboard/openings@all-sessions#runs=3682] holds, [metric:scoreboard/openings@all-sessions#runs_single_sample=963] single-sample holds and
[metric:scoreboard/openings@all-sessions#holes=1381] holes. The witnesses agree on [metric:scoreboard/openings@all-sessions#witness_both=9725]
samples; the slab test alone opens [metric:scoreboard/openings@all-sessions#witness_slab_only=479], the strip alone
sees [metric:scoreboard/openings@all-sessions#witness_strip_only=15351], and the strip cannot read
[metric:scoreboard/openings@all-sessions#witness_unreadable=1061]. Accepted openings stay
[metric:scoreboard/openings@all-sessions#openings_accepted=6018]: only the slab test reads rows, so a strip-only
sample is an opening refused as `strip_only_no_rows`.

The holes rose because the strip finds holds the slab test missed, and a hold
broken by a Tab release leaves a one-sample hole. Of the combined holes,
[metric:scoreboard/openings@all-sessions#holes_neither=1304] have neither witness seeing the board and
[metric:scoreboard/openings@all-sessions#holes_unreadable=77] an unreadable strip; a montage of
[metric:scoreboard/openings@all-sessions#inspect_holes_in_strip_holds=22] holes inside strip-only holds showed a
board on [metric:scoreboard/openings@all-sessions#inspect_holes_in_strip_holds_board=0]. A hole counts a reader
miss only where some witness saw the board at that sample.

## Predictions

- **S1 is refuted on both clauses.** The witness finds the strip on
  [metric:scoreboard/strip-witness@all-sessions#hole_present_frac=0.5553] of the
  [metric:scoreboard/openings@all-sessions-slab-only#holes=841] holes, not 0.9, because
  many holes are real closures. On closed samples outside any run it finds the
  strip on [metric:scoreboard/strip-witness@all-sessions#closed_out_present_frac=0.2053],
  not under 0.02, because the slab test misses whole holds. Extrapolated from
  the sample, about [metric:scoreboard/strip-witness@all-sessions#est_board_samples_slab_closed=13559]
  closed samples show the board, against
  [metric:scoreboard/openings@all-sessions-slab-only#samples_open=10269] the slab test opens.
- **S2 holds.** The witness extends
  [metric:scoreboard/strip-witness@all-sessions#singles_extended=827] of the
  [metric:scoreboard/openings@all-sessions-slab-only#runs_single_sample=1360] single-sample
  runs by at least one sample. It sees the board at the single sample alone on
  [metric:scoreboard/strip-witness@all-sessions#singles_board_seen_once=347]:
  holds shorter than a second, a bound on taps shorter than 0.5 s that 2 Hz
  sampling cannot tighten. The single samples it reads absent are false opens.
- **S3 holds in part.** The witness reads the strip on
  [metric:scoreboard/strip-witness@all-sessions#open_present_frac=0.9434] of
  open samples, above the predicted 0.85, and the open samples it rejects are
  false opens, as predicted. It reads the strip on
  [metric:scoreboard/strip-witness@all-sessions#far_present_frac=0.1558] of far
  closed samples, not under 0.01, and those are missed boards.

## Next

- The slab test keeps the TALLEST red run. Cross-reference before tuning: the
  strip's marker lines sit between the blocks, so an enemy block could be
  sought as the run starting just below them, and a block the strip does not
  bound refused. Measure it against the stored close reasons.
- Rescan the scoreboard (`scoreboard-0.7.0`) to store a `sample` row per
  frame; the openings now infer closed samples from the offered frames.
  `lineup.load_lineup` applies no board until then.
- The player reads the strip as round outcomes: a circle with an X per round
  of the half, green for an ally win and red for an enemy win, and a yellow
  dot on the right for the opponents' round total
  [domain:hud/scoreboard-round-history-strip]. The witness's teal and red
  icons are those circles. Read them as a round-outcome witness and
  cross-check them against the scoreline; the yellow-green dot the witness
  finds in one column per board is not yet reconciled with one dot on the
  right, and the crop shows only the middle columns.
- The witness misses a board where world detail runs along a marker line and
  where a player card covers the strip; it cannot read a band over a black
  world at all.
