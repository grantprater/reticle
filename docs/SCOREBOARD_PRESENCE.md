# Scoreboard presence: the round-history strip as a witness

`reticle.scoreboard.read_scoreboard` opens the Tab board on its two translucent
team slabs. Between the two blocks the game draws two lines of round markers
[domain:hud/scoreboard-round-history-strip]. `prototypes/scoreboard_strip.py`
reads those markers from stored crops and scores the slab test against them
(ledger task `scoreboard-presence`, predictions S1, S2 and S3). It decodes no
video: every pixel comes from the `hud` crop cache's `center` crop, frame x
883-1037 and y 486-594 at 1920x1080, one crop every 30 frames.

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

## Predictions

- **S1 is refuted on both clauses.** The witness finds the strip on
  [metric:scoreboard/strip-witness@all-sessions#hole_present_frac=0.5553] of the
  [metric:scoreboard/openings@all-sessions#holes=841] holes, not 0.9, because
  many holes are real closures. On closed samples outside any run it finds the
  strip on [metric:scoreboard/strip-witness@all-sessions#closed_out_present_frac=0.2053],
  not under 0.02, because the slab test misses whole holds. Extrapolated from
  the sample, about [metric:scoreboard/strip-witness@all-sessions#est_board_samples_slab_closed=13559]
  closed samples show the board, against
  [metric:scoreboard/openings@all-sessions#samples_open=10269] the slab test opens.
- **S2 holds.** The witness extends
  [metric:scoreboard/strip-witness@all-sessions#singles_extended=827] of the
  [metric:scoreboard/openings@all-sessions#runs_single_sample=1360] single-sample
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

- `read_scoreboard` returns no reason when it closes a board, so its misses
  cannot be read from storage. Store the branch that closed each sample before
  tuning the slab test.
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
- Wiring is the orchestrator's decision; the ledger records `"wire": "no"`
  until then.
