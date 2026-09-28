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
experiment record and imports the reader. From `scoreboard-0.8.0` the slab
test asks the witness where the blocks lie ("Anchoring on the strip").

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

## Anchoring on the strip

`read_scoreboard` (`scoreboard-0.8.0`) asks the strip witness first. Where the
witness reads the strip present in the profile's centre crop, the reader
takes the slab runs that meet the marker lines instead of the tallest runs:

- The ally block is the merged green run that ends within `STRIP_TOL` of
  17 rows above the upper line. A run that goes on into the band is cut
  there: the world in the band passed the green test.
- The enemy block is the red run that reaches 17 rows below the lower line,
  at least `MIN_BLOCK_H` tall from there, with the ally block's height. Where
  the run ends where that height puts it, the rows sit on its bottom, as at
  0.7.0; where the world below joins the run, the line places them.
- A block the strip does not bound refuses the board as
  `green_not_at_strip`, `red_not_at_strip` or `red_short_at_strip`.

Where the strip is absent or unreadable, or the frame is not 1920x1080, the
tallest runs decide as at 0.7.0: the strip's marker lines are frame rows at
that size, and the reader scales none of its own pixel constants. Each
sample row stores `anchor`, `strip` and `edges`, and the coverage row counts
the anchors of open boards.

### Geometry

Measured before any decode, from stored centre crops, as the per-row share of
pixels that pass the slab colour test. At the [metric:scoreboard/strip-geometry@all-sessions#n=3140] samples the strip
reads present and the slab test open on the 19 lineup sessions, the ally
slab ends at frame y
[metric:scoreboard/strip-geometry@all-sessions#ally_end_median=510.0] and the enemy slab begins at y
[metric:scoreboard/strip-geometry@all-sessions#enemy_start_median=568.0], 17 rows above the upper line and 17 rows
below the lower one. The ally edge lies within 2 px of its place on
[metric:scoreboard/strip-geometry@all-sessions#ally_end_within_2px_frac=0.946] of the
[metric:scoreboard/strip-geometry@all-sessions#ally_end_measured=2880] samples that show it (y 508 on some
sessions), the enemy edge on
[metric:scoreboard/strip-geometry@all-sessions#enemy_start_within_2px_frac=0.941] of
[metric:scoreboard/strip-geometry@all-sessions#enemy_start_measured=1821]. On
[metric:scoreboard/strip-geometry@all-sessions#band_passes_red=732] samples the band between the lines passes
the red test and hides the enemy edge. `STRIP_TOL` is 4 px, twice that
spread. The decode agrees at full width: the ally run ends at y 510 on
[metric:scoreboard/anchored@a06f04a0059f#fullwidth_ally_end_510=94] of 100 open frames.

### Before and after

One CPU decode read the close-reasons selection again
([metric:scoreboard/anchored@a06f04a0059f#frames_decoded=300] frames of a06f04a0059f, `random.Random(20260927)`).
Every decoded centre crop equals the cached one
([metric:scoreboard/anchored@a06f04a0059f#crop_equal=300]), every strip verdict equals the stored one, and the
reader without the strip's rectangle equals 0.7.0 on
[metric:scoreboard/anchored@a06f04a0059f#fallback_equals_070=300] frames.

| Frames | 0.7.0 open | 0.8.0 open | `red_not_at_strip` | `red_short_at_strip` | `green_tall` |
|---|---|---|---|---|---|
| Strip present, slab test closed | [metric:scoreboard/anchored@a06f04a0059f#closed_present_before_open=0] | [metric:scoreboard/anchored@a06f04a0059f#closed_present_after_open=70] | [metric:scoreboard/anchored@a06f04a0059f#closed_present_after_red_not_at_strip=14] | [metric:scoreboard/anchored@a06f04a0059f#closed_present_after_red_short_at_strip=12] | [metric:scoreboard/anchored@a06f04a0059f#closed_present_after_green_tall=4] |
| Strip present, slab test open | [metric:scoreboard/anchored@a06f04a0059f#open_present_before_open=100] | [metric:scoreboard/anchored@a06f04a0059f#open_present_after_open=77] | [metric:scoreboard/anchored@a06f04a0059f#open_present_after_red_not_at_strip=16] | [metric:scoreboard/anchored@a06f04a0059f#open_present_after_red_short_at_strip=7] | 0 |
| Strip absent | [metric:scoreboard/anchored@a06f04a0059f#absent_before_open=5] | [metric:scoreboard/anchored@a06f04a0059f#absent_after_open=5] | 0 | 0 | 0 |

- **Closed boards open at the board.** All
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_opened_five_each=70] carry five rows per side where
  the board is: [metric:scoreboard/anchored@a06f04a0059f#closed_present_red_tall_opened=63] of
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_red_tall=68] `red_tall`,
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_enemy_overlaps_ally_opened=4] of
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_enemy_overlaps_ally=7] `enemy_overlaps_ally` and
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_green_tall_opened=3] of
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_green_tall=7] `green_tall`; none of the
  [metric:scoreboard/anchored@a06f04a0059f#closed_present_red_short=17] `red_short`. Their enemy portraits score
  a median [metric:scoreboard/anchored@a06f04a0059f#opened_enemy_portrait_median=0.911] and read K/D on
  [metric:scoreboard/anchored@a06f04a0059f#opened_enemy_kd_read=207] of [metric:scoreboard/anchored@a06f04a0059f#opened_enemy_rows=350] rows; their
  ally portraits score [metric:scoreboard/anchored@a06f04a0059f#opened_ally_portrait_median=0.84], as on boards
  0.7.0 opened ([metric:scoreboard/anchored@a06f04a0059f#open_present_ally_portrait_median_before=0.839]).
- **Enemy rows move onto the board.** Of
  [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_before=55] open boards whose enemy rows sat off
  the board, [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_moved_onto_board=35] now sit on it:
  portrait median [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_portrait_median_before=0.518] before and
  [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_portrait_median_after=0.91] after, K/D read on
  [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_kd_read_before=6] and
  [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_kd_read_after=85] of [metric:scoreboard/anchored@a06f04a0059f#moved_enemy_rows=175] rows. The
  other [metric:scoreboard/anchored@a06f04a0059f#open_present_off_board_refused=20] are refused. Of
  [metric:scoreboard/anchored@a06f04a0059f#open_present_at_board_before=45] boards with the enemy rows at the
  board, [metric:scoreboard/anchored@a06f04a0059f#open_present_at_board_changed=3] are refused and the rest keep
  every row.
- **The openings gate lost three boards.** At the
  [metric:scoreboard/anchored@a06f04a0059f#stored_accepted=45] open frames whose stored opening the gate accepts,
  0.8.0 writes the same rows on [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_same=41], the same reads
  6 px higher on [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_moved_same_reads=1] (0.7.0 had placed
  them 6 px low) and refuses [metric:scoreboard/anchored@a06f04a0059f#stored_accepted_refused_now=3]. On the 19
  sessions every accepted stored opening
  ([metric:scoreboard/stored-openings@all-sessions#accepted_at_board=6018])
  has its enemy rows at the board, so `SCOREBOARD_VERDICT_COMPATIBLE` keeps
  0.6.0 and 0.7.0: the stored openings a consumer applies are ones 0.8.0
  reproduces or refuses, never ones it reads as other agents.
- **Frames without the strip are unchanged**:
  [metric:scoreboard/anchored@a06f04a0059f#absent_equal_070=100] of 100, and the strip reads present on
  [metric:scoreboard/anchored@a06f04a0059f#absent_strip_present_decoded=0] of them.

A montage of [metric:scoreboard/anchored@a06f04a0059f#montage_frames=22] frames, before beside after with the
row boxes drawn, was checked by eye. On all
[metric:scoreboard/anchored@a06f04a0059f#montage_rows_on_board_after=12] boards 0.8.0 opened or moved, the five
enemy boxes lie on the five enemy rows; 0.7.0 had closed those boards or put
the boxes on the floor and the ability bar. All
[metric:scoreboard/anchored@a06f04a0059f#montage_refused_full_boards=10] boards 0.8.0 refused in it are fully
expanded boards.

### What still fails

The red colour test on the enemy slab. Over a pale sky, a grey wall, a dark
model or a violet effect, the translucent enemy slab's top rows leave the red
hues or fall under the value floor, so the red run starts late or breaks.
0.8.0 refuses these boards where 0.7.0 anchored rows on the world, and on the
three accepted boards above, where 0.7.0 found the right rows by the run's
bottom. A green world above the ally block still closes four boards as
`green_tall`. The strip cannot anchor a board over a black world, where it is
unreadable.

No second session was decoded. The geometry holds on every lineup session
(above); the reader's before and after have no held-out session yet.

The predictions (ledger task `scoreboard-anchor`): SA2, SA5 and SA6 hold;
SA1 holds across sessions but not on a06f04a0059f's own frames, where the
enemy edge lay within 2 px on [metric:scoreboard/strip-geometry@a06f04a0059f#enemy_start_within_2px=29] of
[metric:scoreboard/strip-geometry@a06f04a0059f#enemy_start_measured=35], not 0.95; SA3 and SA4 fail on the refusals
above; SA7 holds except for an ally portrait threshold set above what open
boards score.

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

- The enemy slab fails the red test over pale, grey and dark worlds, and
  0.8.0 refuses those boards (see "What still fails"). Where the strip places
  the block, ask what else observes its rows (the ten portraits the openings
  gate scores) before tuning the colour test.
- Hold the anchor out on a second session: decode a seeded selection of
  another map (50 frames per group from `notes/scoreboard-strip-samples.jsonl`,
  `random.Random(20260927)`) and compare, fitting nothing.
- Rescan the scoreboard (`scoreboard-0.8.0`) to store a `sample` row per
  frame and the anchored rows; the openings now infer closed samples from
  the offered frames. `lineup.load_lineup` applies the stored 0.6.0 and 0.7.0
  boards meanwhile (`version.SCOREBOARD_VERDICT_COMPATIBLE`), and
  `board_state.current` says the stamp is behind.
- The player reads the strip as round outcomes: a circle with an X per round
  of the half, green for an ally win and red for an enemy win, and a yellow
  dot on the right for the opponents' round total
  [domain:hud/scoreboard-round-history-strip]. The witness's teal and red
  icons are those circles. Read them as a round-outcome witness and
  cross-check them against the scoreline; the yellow-green dot the witness
  finds in one column per board is not yet reconciled with one dot on the
  right, and the crop shows only the middle columns. Read and measured in
  [SCOREBOARD_ROUND_MARKS.md](SCOREBOARD_ROUND_MARKS.md): the strip is
  match-long and the dot is the earliest match-winning round per team.
- The witness misses a board where world detail runs along a marker line and
  where a player card covers the strip; it cannot read a band over a black
  world at all.
