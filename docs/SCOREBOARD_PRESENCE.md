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

From `scoreboard-agent-0.4.0` a sample whose slab read the reader anchored on
the strip (the stored `anchor` is `strip`, from `scoreboard-0.8.0`) is
`both_anchored`, not `both`: the slab test placed its blocks where the strip
said, so the read rests on the strip and is no second witness beside it.
Only a read placed by the tallest runs counts as `both`. The counts above
come from `scoreboard-0.6.0` rows, which carry no anchor, and read the same
under 0.4.0. After a rescan the reader consults the strip at every
1920x1080 frame, so almost every `both` sample becomes `both_anchored`;
`both` remains only where the reader did not consult the strip (another
frame size), and the slab test witnesses the board independently only on
`slab_only` samples, where the strip reads absent. The boards the anchor
opens move from `strip_only` to `both_anchored`, so `strip_only` falls. The
slab-alone counts (`coverage.slab`) then include reads that rest on the
strip and no longer measure what the strip adds.

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
- Where no red run of block height begins at the lower line, the line
  places the enemy rows anyway (`scoreboard-0.9.0`, "The line places, the
  slab confirms"). A red run over half the ally height inside the span the
  line predicts confirms them (`red_overlap`); failing that, each of the five
  portraits at those rows must score at least `PORTRAIT_CONFIRM_MIN`
  (`portraits`).
- A block the strip does not bound, or that nothing confirms, refuses the
  board as `green_not_at_strip`, `red_not_at_strip` or `red_short_at_strip`.

Where the strip is absent or unreadable, or the frame is not 1920x1080, the
tallest runs decide as at 0.7.0: the strip's marker lines are frame rows at
that size, and the reader scales none of its own pixel constants. Each
sample row stores `anchor`, `strip`, `edges` and `confirm`, and the coverage
row counts the anchors and confirmations of open boards.

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

### The line places, the slab confirms

0.8.0 refused a board wherever the red run did not begin at the lower line,
and a montage showed those boards fully expanded: over a pale sky, a grey
wall, a dark model or a violet effect the translucent enemy slab's top rows
fail the red test. Once the strip bounds the block, the colour test has only
to confirm a slab in the span the line predicts. Two confirmations were
measured on the boards 0.8.0 refused at the strip in its before and after
decode ([metric:scoreboard/line-confirm@a06f04a0059f#measure_open_present_refused=23] open at 0.7.0,
[metric:scoreboard/line-confirm@a06f04a0059f#measure_closed_present_refused=26] closed), with the rows placed at the
line:

- (a) a red run over half the ally height inside the span: from the stored
  runs, [metric:scoreboard/line-confirm@a06f04a0059f#measure_open_present_rule_a=8] and
  [metric:scoreboard/line-confirm@a06f04a0059f#measure_closed_present_rule_a=4].
- (b) each of the five enemy portraits scoring at least 0.81, a threshold
  fixed from the stored openings before any refused board was scored: the
  weakest enemy portrait of an accepted opening reaches
  [metric:scoreboard/portrait-confirm@all-sessions#enemy_min_p5=0.8165] on 95 % of the [metric:scoreboard/portrait-confirm@all-sessions#accepted=6018] accepted
  openings. One CPU decode of those [metric:scoreboard/line-confirm@a06f04a0059f#measure_frames_decoded=49] frames:
  [metric:scoreboard/line-confirm@a06f04a0059f#measure_open_present_rule_b=20] and [metric:scoreboard/line-confirm@a06f04a0059f#measure_closed_present_rule_b=25],
  and (a) accepts none that (b) refuses ([metric:scoreboard/line-confirm@a06f04a0059f#measure_rule_a_not_b=0]).

The scores fall in two groups, at least [metric:scoreboard/line-confirm@a06f04a0059f#measure_confirmed_enemy_min_score_min=0.8796]
and at most [metric:scoreboard/line-confirm@a06f04a0059f#refused_enemy_min_score_max=0.4042]. A montage of all
[metric:scoreboard/line-confirm@a06f04a0059f#montage_frames=49] frames, viewed by eye, shows the line's enemy boxes on
the five enemy rows on every one, the refused ones included. Those
[metric:scoreboard/line-confirm@a06f04a0059f#measure_still_refused_x0_wrong=4] have a wrong table left edge (frame x 0
or 304, not 572): the world left of the board passes the green test, the
portrait boxes miss the portraits, and ally portraits score as low as enemy ones.

`scoreboard-0.9.0` adopts both: a red run confirms first (`red_overlap`),
the portraits second (`portraits`). The portrait scores are locally
shift-invariant (`portrait_agent` searches around the box), so they confirm
art at the rows, not the rows to the pixel; the line places them. A board
confirmed by its portraits rests on them: the openings gate's portrait
scores are no second witness of its rows.

Another decode of the whole selection compared 0.8.0 with 0.9.0
([metric:scoreboard/line-confirm@a06f04a0059f#frames_decoded=300] frames, every centre crop equal to the cached one):

| Frames | 0.8.0 open | 0.9.0 open | recovered by `red_overlap` | by `portraits` | 0.8.0 opens unchanged |
|---|---|---|---|---|---|
| Strip present, 0.7.0 closed | [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_before_open=70] | [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_after_open=95] | [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_recovered_red_overlap=4] | [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_recovered_portraits=21] | [metric:scoreboard/line-confirm@a06f04a0059f#closed_present_before_open_unchanged=70] |
| Strip present, 0.7.0 open | [metric:scoreboard/line-confirm@a06f04a0059f#open_present_before_open=77] | [metric:scoreboard/line-confirm@a06f04a0059f#open_present_after_open=97] | [metric:scoreboard/line-confirm@a06f04a0059f#open_present_recovered_red_overlap=8] | [metric:scoreboard/line-confirm@a06f04a0059f#open_present_recovered_portraits=12] | [metric:scoreboard/line-confirm@a06f04a0059f#open_present_before_open_unchanged=77] |
| Strip absent | [metric:scoreboard/line-confirm@a06f04a0059f#absent_before_open=5] | [metric:scoreboard/line-confirm@a06f04a0059f#absent_after_open=5] | 0 | 0 | [metric:scoreboard/line-confirm@a06f04a0059f#absent_before_open_unchanged=5] |

Every recovered board has its enemy rows at the board
([metric:scoreboard/line-confirm@a06f04a0059f#recovered_at_board=45] of [metric:scoreboard/line-confirm@a06f04a0059f#recovered=45]); their enemy portraits score
a median [metric:scoreboard/line-confirm@a06f04a0059f#recovered_enemy_portrait_median=0.913] and read K/D on
[metric:scoreboard/line-confirm@a06f04a0059f#recovered_enemy_kd_read=116] of [metric:scoreboard/line-confirm@a06f04a0059f#recovered_enemy_rows=225] rows. The
three accepted stored openings 0.8.0 refused come back: two with 0.7.0's
rows and one 2 px lower with the same reads and agents
([metric:scoreboard/line-confirm@a06f04a0059f#stored_accepted_recovered=3] recovered). Without agent icons only a red
run confirms, and the reader differs from 0.8.0 on
[metric:scoreboard/line-confirm@a06f04a0059f#noicons_changed_total=12] frames, the `red_overlap` boards.

### Held out on a second map

`bfad2778a372`, another map, held the rule out with nothing refitted: one
CPU decode of the seeded selection's [metric:scoreboard/holdout@bfad2778a372#closed_present_n=50] closed_present and
[metric:scoreboard/holdout@bfad2778a372#open_present_n=50] open_present frames (`random.Random(20260927)`), every centre
crop and strip verdict equal to the stored ones ([metric:scoreboard/holdout@bfad2778a372#crop_equal=100],
[metric:scoreboard/holdout@bfad2778a372#strip_equal=100]).

| Frames | 0.7.0 open | 0.8.0 open | 0.9.0 open | `red_run` | `red_overlap` | `portraits` | 0.8.0 opens unchanged |
|---|---|---|---|---|---|---|---|
| Strip present, 0.7.0 closed | [metric:scoreboard/holdout@bfad2778a372#closed_present_070_open=0] | [metric:scoreboard/holdout@bfad2778a372#closed_present_080_open=18] | [metric:scoreboard/holdout@bfad2778a372#closed_present_090_open=28] | [metric:scoreboard/holdout@bfad2778a372#closed_present_090_confirm_red_run=18] | [metric:scoreboard/holdout@bfad2778a372#closed_present_090_confirm_red_overlap=2] | [metric:scoreboard/holdout@bfad2778a372#closed_present_090_confirm_portraits=8] | [metric:scoreboard/holdout@bfad2778a372#closed_present_080_open_090_unchanged=18] |
| Strip present, 0.7.0 open | [metric:scoreboard/holdout@bfad2778a372#open_present_070_open=50] | [metric:scoreboard/holdout@bfad2778a372#open_present_080_open=39] | [metric:scoreboard/holdout@bfad2778a372#open_present_090_open=50] | [metric:scoreboard/holdout@bfad2778a372#open_present_090_confirm_red_run=39] | [metric:scoreboard/holdout@bfad2778a372#open_present_090_confirm_red_overlap=10] | [metric:scoreboard/holdout@bfad2778a372#open_present_090_confirm_portraits=1] | [metric:scoreboard/holdout@bfad2778a372#open_present_080_open_090_unchanged=39] |

Every board 0.9.0 opens has its enemy rows at the board. Of the
[metric:scoreboard/holdout@bfad2778a372#open_present_070_at_board=37] boards whose 0.7.0 enemy rows sat at the board, 0.9.0 keeps the
reads on [metric:scoreboard/holdout@bfad2778a372#open_present_070_at_board_090_same_reads=37] and the rows on [metric:scoreboard/holdout@bfad2778a372#open_present_070_at_board_090_same_rows=36]; one moves 2 px. It
moves all [metric:scoreboard/holdout@bfad2778a372#open_present_070_off_board=13] boards 0.7.0 read off the board onto it
([metric:scoreboard/holdout@bfad2778a372#open_present_070_off_board_090_at_board=13]). A montage of the [metric:scoreboard/holdout@bfad2778a372#changed_viewed=21] boards 0.9.0 reads
differently from 0.8.0, viewed by eye, shows the five enemy boxes on the
five enemy rows on all of them. The predicted 40 closed_present opens fail:
0.9.0 closes [metric:scoreboard/holdout@bfad2778a372#closed_present_090_closed_green_tall=9] as `green_tall`, and
[metric:scoreboard/holdout@bfad2778a372#closed_present_090_closed_red_short_at_strip=7] + [metric:scoreboard/holdout@bfad2778a372#closed_present_090_closed_red_not_at_strip=6] at the strip. The run kept no image of the
closed boards, so why those strip refusals fail both confirmations is
unmeasured.

The table's left edge is wrong on [metric:scoreboard/holdout@bfad2778a372#open_x0_wrong=9] of the [metric:scoreboard/holdout@bfad2778a372#open_090=78] boards 0.9.0
opens, [metric:scoreboard/holdout@bfad2778a372#open_x0_wrong_changed=1] of them new: `red_overlap` confirms 69030 with its left edge at
frame x 38. No weakest enemy portrait on those boards scores above
[metric:scoreboard/holdout@bfad2778a372#open_x0_wrong_enemy_min_max=0.4514], so the openings gate refuses each (`row_refused`). The right
edge lies past the board on [metric:scoreboard/holdout@bfad2778a372#open_x1_wrong=31] of the [metric:scoreboard/holdout@bfad2778a372#open_090=78].

### What still fails

The table's left edge. Where the world left of the board passes the green
test, the ally block's dense columns reach frame x 0 or 304, the portrait
boxes miss the portraits and the line's rows go unconfirmed
([metric:scoreboard/line-confirm@a06f04a0059f#still_refused=4] boards of the selection, all fully expanded). A green
world above the ally block still closes boards as `green_tall`, and the
strip cannot anchor a board over a black world, where it is unreadable. The
K/D cells scale with the table's width, so a wrong right edge (x1 past the
board on [metric:scoreboard/line-confirm@a06f04a0059f#recovered_x1_wrong=4] recovered boards) misplaces them.

The earlier predictions (ledger task `scoreboard-anchor`): SA2, SA5 and SA6
hold; SA1 holds across sessions but not on a06f04a0059f's own frames, where
the enemy edge lay within 2 px on [metric:scoreboard/strip-geometry@a06f04a0059f#enemy_start_within_2px=29] of
[metric:scoreboard/strip-geometry@a06f04a0059f#enemy_start_measured=35], not 0.95; SA3 and SA4 fail on the refusals
0.9.0 now recovers; SA7 holds except for an ally portrait threshold set
above what open boards score. SA8 to SA12 and the holdout's SH1 to SH3 are
in the ledger.

### The edges in storage

The store holds `scoreboard-0.9.0` rows for all 19 lineup sessions: a scan
wrote them on 2026-09-28, so the table's edges can be counted without a
decode. Of the [metric:scoreboard/stored-edges@all-sessions#boards_open=20751] open boards, [metric:scoreboard/stored-edges@all-sessions#x0_wrong=2904] have a
left edge outside frame x 572 or 574: [metric:scoreboard/stored-edges@all-sessions#x0_wrong_at_0=739] at x 0,
[metric:scoreboard/stored-edges@all-sessions#x0_wrong_left=2185] left of the board in all and [metric:scoreboard/stored-edges@all-sessions#x0_wrong_right=675]
right of it. The openings gate refuses [metric:scoreboard/stored-edges@all-sessions#x0_wrong_refused=2813] of them and
accepts [metric:scoreboard/stored-edges@all-sessions#x0_wrong_accepted=91], each within 30 px of the board's edge
([metric:scoreboard/stored-edges@all-sessions#x0_wrong_within_30px_accepted=91]). The portrait boxes are the
cross-reference: a wrong left edge moves them off the portraits, and the gate
refuses the board rather than naming from it. So the defect costs coverage,
not names. Every session has some, from [metric:scoreboard/stored-edges@all-sessions#x0_wrong_session_min=31] to
[metric:scoreboard/stored-edges@all-sessions#x0_wrong_session_max=313]; the right edge lies outside x 1345 or 1347 on
[metric:scoreboard/stored-edges@all-sessions#x1_wrong=4099].

The stored rows keep the edges but no pixels. The crop cache holds the centre
crop (frame x 883-1037), not the table's frame, and the holdout run kept
thumbnails of two of its nine wrong boards, annotated and cropped. A fit of
the table's frame therefore needed frames decoded ("The table's frame").

### The table's frame

One CPU seek decode stored [metric:scoreboard/table-frame@fixture#boards=456] boards as lossless crops of frame
rows 150-899 at full width in the store fixture `fixtures/scoreboard_edges`
(`index.jsonl` names each board's session, frame, group and the 0.9.0 read),
chosen by `random.Random(20260928)` from the stored rows: boards with the left
edge at x 0, left of the board, right of it, at the board, and at the board
with a wrong right edge. Six sessions are held out (`223d636bf8d2`,
`5822b6646448`, `96aa1ae9b96f`, `bfad2778a372` with the holdout's nine boards,
`c40d950031bb`, `ff636d173b07`). Every decoded read equals the stored one. On
[metric:scoreboard/table-frame@fixture#evaluable=414] boards the reader reads the crop pasted into a black frame as it
reads the decoded frame; the rest had rows outside the crop and are not scored.

Contact sheets (`notes/pictures/scoreboard_edges_fit_*.png`) show every board
at frame x 572-1347. A speaker-icon column (x 540-571) lies outside the slab;
a 4 px plate stripe, the portrait column and the row plates follow, and the
ping plate ends the table. The green test's dense columns fail both ways: a
green world beside the board passes the test over the ally rows, and the
portrait column fails it over a pale world (x0 near 600). Some stored opens
show no board at all.

Colour classes did not fix it. Requiring the enemy rows red where the ally
rows are green put x0 right on [metric:scoreboard/table-frame@fixture#fit_colour_both_x0_right_zero_left=69] of [metric:scoreboard/table-frame@fixture#fit_colour_both_zero_left_n=103] fit boards at x 0 or
left, and lost x0 on [metric:scoreboard/table-frame@fixture#fit_colour_both_ok_x0_lost=13] correct ones; a fixed-width colour fit
corrected [metric:scoreboard/table-frame@fixture#fit_colour_fixed_x0_right=35] of [metric:scoreboard/table-frame@fixture#fit_colour_fixed_x0_right_n=45] boards right of the board. The row separators are no
cleaner: over a washed world only the player's outline shows.

The edges are colour steps. The median, over the rows of both blocks, of the
change from one column to the next peaks at x 572 and 1348 on every board.
`scoreboard-0.10.0` fits the frame as the pair of steps `TABLE_W` (776)
columns apart, within 2, whose sum is largest, with its left edge within 32
px of the place the strip's centre predicts (`_frame_edges`). A frame whose
steps sum under 36 closes the board as `no_table_frame`: stored opens without
a board sum at most [metric:scoreboard/table-frame@fixture#fit_frame_score_noboard_max=20] on the fit sessions and boards at least
[metric:scoreboard/table-frame@fixture#fit_frame_score_board_min=53] ([metric:scoreboard/table-frame@fixture#holdout_frame_score_board_min=64] held out). Without the strip's rectangle the dense
columns still decide.

| Boards | Edges right, 0.9.0 | Edges right, 0.10.0 | Closed, no board | Gate accepts, 0.9.0 | Gate accepts, 0.10.0 |
|---|---|---|---|---|---|
| Fit, x0 wrong | [metric:scoreboard/table-frame@fixture#fit_x0_wrong_edges_right_before=0] of [metric:scoreboard/table-frame@fixture#fit_x0_wrong_n=151] | [metric:scoreboard/table-frame@fixture#fit_x0_wrong_edges_right_after=148] | [metric:scoreboard/table-frame@fixture#fit_x0_wrong_closed_no_frame=3] | [metric:scoreboard/table-frame@fixture#fit_x0_wrong_accepted_before=3] | [metric:scoreboard/table-frame@fixture#fit_x0_wrong_accepted_after=119] |
| Held out, x0 wrong | [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_edges_right_before=0] of [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_n=71] | [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_edges_right_after=68] | [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_closed_no_frame=3] | [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_accepted_before=2] | [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_accepted_after=49] |

The K/D/A cells scale with the table's width, so the right edge matters as
much: on boards with only x1 wrong, 0.10.0 puts it right on
[metric:scoreboard/table-frame@fixture#fit_x1_wrong_x1_right_after=40] of [metric:scoreboard/table-frame@fixture#fit_x1_wrong_n=40] and [metric:scoreboard/table-frame@fixture#holdout_x1_wrong_x1_right_after=20] of [metric:scoreboard/table-frame@fixture#holdout_x1_wrong_n=20], and the cells read rise from
[metric:scoreboard/table-frame@fixture#holdout_x1_wrong_kda_read_before=165] to [metric:scoreboard/table-frame@fixture#holdout_x1_wrong_kda_read_after=456] held out; on the x0-wrong boards from
[metric:scoreboard/table-frame@fixture#holdout_x0_wrong_kda_read_before=365] to [metric:scoreboard/table-frame@fixture#holdout_x0_wrong_kda_read_after=1398]. On boards 0.9.0 read with the right edges
([metric:scoreboard/table-frame@fixture#fit_ok_n=80] fit, [metric:scoreboard/table-frame@fixture#holdout_ok_n=50] held out) no row and no gate verdict changes
([metric:scoreboard/table-frame@fixture#fit_ok_rows_changed=0], [metric:scoreboard/table-frame@fixture#holdout_ok_rows_changed=0]); the edges move by at most [metric:scoreboard/table-frame@fixture#holdout_ok_edge_shift_max_px=2] px, x0 574 to 572 or
x1 1347 to 1346. No accepted opening is lost ([metric:scoreboard/table-frame@fixture#fit_accepted_lost=0], [metric:scoreboard/table-frame@fixture#holdout_accepted_lost=0]), and none
opens that 0.9.0 closed ([metric:scoreboard/table-frame@fixture#opened_now=0]). The [metric:scoreboard/table-frame@fixture#closed_no_frame_all=13] boards 0.10.0 closes all
show no board (`notes/pictures/scoreboard_edges_closed_no_frame.png`).
Predictions E1 and E4 hold; E2 and E3, the colour rules, fail (ledger task
`scoreboard-edges`).

### A portrait-confirmed board counts once

Where the portraits alone confirmed the enemy rows (`confirm ==
"portraits"`), the openings gate accepts the board on the same scores, so its
acceptance says which agents the board shows and nothing more about where the
rows lie. From `scoreboard-agent-0.5.0` each opening says where its enemy rows
come from (`enemy_rows_from`, `slab` or `portraits`), the presence rows carry
it as `opening_enemy_rows_from`, and the coverage row counts
`openings_accepted_enemy_rows_from_portraits`. The gate's verdicts do not
change: from the stored 0.9.0 rows, 0.4.0 and 0.5.0 both accept
[metric:scoreboard/openings-confirm@all-sessions#accepted=16421] of [metric:scoreboard/openings-confirm@all-sessions#openings=25620] openings
([metric:scoreboard/openings-confirm@all-sessions#accepted_before=16421] before). Of those accepted,
[metric:scoreboard/openings-confirm@all-sessions#accepted_enemy_rows_from_slab=13108] have enemy rows from the slab
([metric:scoreboard/openings-confirm@all-sessions#accepted_confirm_red_run=12229] by a red run,
[metric:scoreboard/openings-confirm@all-sessions#accepted_confirm_red_overlap=834] by a red overlap,
[metric:scoreboard/openings-confirm@all-sessions#accepted_tallest_run=45] by the tallest runs) and
[metric:scoreboard/openings-confirm@all-sessions#accepted_enemy_rows_from_portraits=3313] from the portraits alone. The
presence rows stored before counted
[metric:scoreboard/portrait-confirm@all-sessions#accepted=6018] accepted
openings over the older 0.6.0 rows; the 0.9.0 scan, not this change, moved
that count.

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

- The table's left and right edges come from the ally block's dense green
  columns, and a green world beside the board moves them (see "What still
  fails"). Ask what else observes the table's columns before tuning the
  green test.
- Keep an image of every board the holdout refuses at the strip, and view
  them before changing either confirmation: on `bfad2778a372` the run kept
  none (see "Held out on a second map").
- Rescan the scoreboard at `scoreboard-0.10.0` (the player's call): the
  stored 0.9.0 rows keep the dense columns' edges ("The edges in storage").
  A scoreboard ROI in the crop cache, written by that rescan, would let
  later reader changes rerun without a decode.
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
