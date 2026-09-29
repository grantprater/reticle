# Ally icons from the minimap cache at 2 Hz

2026-09-29. `AllyIconReader` now declares `cache_resample = "nearest"`: fed
from the 15 Hz minimap crop cache, it reads the cached frame nearest each
instant of the decode's 2 Hz stride (`roi_cache.nearest_times`), phased at the
start of each span it asked for, as `decode.sample_multi` phases it. It
records `frames_from` and, when clipped to the cache's rounds, `spans_clip`
in its coverage row, as `minimap_dark` does; the stamp stays
`ally-icon-0.5.0`. `reticle trial --reader ally_icon` rereads the stored
frames from the cache, and `reticle plan` names that trial.

`--from auto` never clips the reader (`clip_on_auto = False`); only
`--from cache` does. The reason is the buy phase, below.

Sessions: `a06f04a0059f` (C:\Users\grant\Videos\2026-08-26 09-56-37.mp4,
Ascent, 465 px widget), `5822b6646448` (C:\Users\grant\Videos\2026-08-26
12-38-38.mp4, Lotus, 465 px), `75a55a296d3b` (C:\Users\grant\Videos\2026-08-24
13-34-38.mp4, Abyss, 331 px). No video was decoded. Outputs, sheets and
scripts: `~/reticle-store/analysis/ally-icon-resample-20260929/`.

## The reference

No decoded ally_icon stream exists at a usable stamp: the stored streams are
`ally-icon-0.4.0` at 15 Hz, written from the minimap cache
(`notes/usage.jsonl`, source `cache:roi-cache-0.1.0`). The decode's 2 Hz
instants were therefore simulated from the capture's 60 fps timeline with
`sample_multi`'s stride rule. The simulator reproduces every cached frame of
all three caches
([metric:ally_icon_resample/instants@a06f04a0059f#sim15_equals_cache=1]) and
all [metric:ally_icon_resample/buy-phase@a06f04a0059f#old_frames=4145] frames of the 2026-09-23 decoded 2 Hz stream of `a06f04a0059f`, but
only with the decoder's timestamp arithmetic, `idx * (1/60) * 1000`; with
`idx / 60 * 1000` it failed both checks. That float rounding is also why the
"15 Hz" cache holds every 4th or 5th frame, about 13.4 Hz.

The reader reads each frame alone, so on a frame both sources hold it writes
the same rows. `A` is the new path; `R15` is the current reader on every
cached frame; `A`'s rows equal `R15`'s at every one of `A`'s instants
([metric:ally_icon_resample/degradation@a06f04a0059f#rows_equal_r15=3095]),
and `scan --only ally_icon --from cache --check` wrote byte-equal serial and
staged files on `75a55a296d3b`, equal to the driver's stream. The decode
differs from `A` only in when it looks.

## When it looks

| session | decode instants in cache | read exactly | median offset | max offset |
|---|---|---|---|---|
| a06f04a0059f | [metric:ally_icon_resample/instants@a06f04a0059f#decode_in_cache=3095] | [metric:ally_icon_resample/instants@a06f04a0059f#exact=866] | [metric:ally_icon_resample/instants@a06f04a0059f#median_offset_ms=16.7] ms | [metric:ally_icon_resample/instants@a06f04a0059f#max_offset_ms=66.7] ms |
| 5822b6646448 | [metric:ally_icon_resample/instants@5822b6646448#decode_in_cache=2816] | [metric:ally_icon_resample/instants@5822b6646448#exact=774] | [metric:ally_icon_resample/instants@5822b6646448#median_offset_ms=16.7] ms | [metric:ally_icon_resample/instants@5822b6646448#max_offset_ms=66.7] ms |
| 75a55a296d3b | [metric:ally_icon_resample/instants@75a55a296d3b#decode_in_cache=1261] | [metric:ally_icon_resample/instants@75a55a296d3b#exact=591] | [metric:ally_icon_resample/instants@75a55a296d3b#median_offset_ms=16.7] ms | [metric:ally_icon_resample/instants@75a55a296d3b#max_offset_ms=33.3] ms |

`A` reads one frame per decode instant. `minimap_dark`'s rule
(`grid_times`, first cached frame at or after a grid restarted at the clipped
span) would sit a median
[metric:ally_icon_resample/instants@a06f04a0059f#grid_times_median_offset_ms=100.0]
ms from the decode's instants on `a06f04a0059f`; hence the separate rule.

## The buy phase: a loss the cache causes, not the resample

The minimap cache starts each round just before the barrier drops. The
active spans a decode reads start earlier. Of the decode's 2 Hz instants,
[metric:ally_icon_resample/instants@a06f04a0059f#round_not_cache=1050] of
[metric:ally_icon_resample/instants@a06f04a0059f#decode_instants=4145] on
`a06f04a0059f` lie inside the rounds `lifetimes` reads and outside the cache
([metric:ally_icon_resample/instants@5822b6646448#round_not_cache=907] of
[metric:ally_icon_resample/instants@5822b6646448#decode_instants=3723];
[metric:ally_icon_resample/instants@75a55a296d3b#round_not_cache=563] of
[metric:ally_icon_resample/instants@75a55a296d3b#decode_instants=1856]). In
the 2026-09-23 decoded stream (`ally-icon-0.1.0`)
[metric:ally_icon_resample/buy-phase@a06f04a0059f#old_icons_round_not_cache=4814]
of its [metric:ally_icon_resample/buy-phase@a06f04a0059f#old_icons=9925] icons sat
there. A clipped pass records that time as `spans_skipped`, unread, but it
reads none of it. The stored 15 Hz streams, fed from the same cache, already
lack it. So `--from auto` keeps decoding the ally reader; `--from cache` is
the explicit choice to read the rounds only.

## Degradation inside the cache's rounds

The decode's frame lies between two cached frames: `A` reads the nearer, `B`
the other, 67-83 ms from `A`. `B` bounds the timing effect from the far side.

| session | icons per drawn frame, A / B | paired A-B (95% CI) | centre moved, median | facing moved, median | facing over 45 deg |
|---|---|---|---|---|---|
| a06f04a0059f | [metric:ally_icon_resample/degradation@a06f04a0059f#icons_per_drawn_A=1.8373] / [metric:ally_icon_resample/degradation@a06f04a0059f#icons_per_drawn_B=1.8425] | [metric:ally_icon_resample/degradation@a06f04a0059f#icons_A_minus_B=-0.0065] (-0.021, 0.008) | [metric:ally_icon_resample/degradation@a06f04a0059f#disp_median_px=1.0] px | [metric:ally_icon_resample/degradation@a06f04a0059f#facing_median_deg=3.4] | [metric:ally_icon_resample/degradation@a06f04a0059f#facing_over45=514] of [metric:ally_icon_resample/degradation@a06f04a0059f#matched=3710] |
| 5822b6646448 | [metric:ally_icon_resample/degradation@5822b6646448#icons_per_drawn_A=2.063] / [metric:ally_icon_resample/degradation@5822b6646448#icons_per_drawn_B=2.0597] | [metric:ally_icon_resample/degradation@5822b6646448#icons_A_minus_B=0.0005] (-0.017, 0.020) | [metric:ally_icon_resample/degradation@5822b6646448#disp_median_px=1.0] px | [metric:ally_icon_resample/degradation@5822b6646448#facing_median_deg=3.3] | [metric:ally_icon_resample/degradation@5822b6646448#facing_over45=565] of [metric:ally_icon_resample/degradation@5822b6646448#matched=4031] |
| 75a55a296d3b | [metric:ally_icon_resample/degradation@75a55a296d3b#icons_per_drawn_A=1.8657] / [metric:ally_icon_resample/degradation@75a55a296d3b#icons_per_drawn_B=1.8674] | [metric:ally_icon_resample/degradation@75a55a296d3b#icons_A_minus_B=-0.0031] (-0.068, 0.063) | [metric:ally_icon_resample/degradation@75a55a296d3b#disp_median_px=1.0] px | [metric:ally_icon_resample/degradation@75a55a296d3b#facing_median_deg=7.4] | [metric:ally_icon_resample/degradation@75a55a296d3b#facing_over45=179] of [metric:ally_icon_resample/degradation@75a55a296d3b#matched=805] |

Every disagreement is stored (`disagreements_<sid>.jsonl`:
[metric:ally_icon_resample/degradation@a06f04a0059f#disagreements=621],
[metric:ally_icon_resample/degradation@5822b6646448#disagreements=743] and
[metric:ally_icon_resample/degradation@75a55a296d3b#disagreements=353]). The
sheets of the largest (`disagreements_<sid>.png`) show frame-to-frame reader
noise, not a better source: false fits on the teal void behind the widget
[domain:minimap/transparency], on screen-effect overlays and on round-end
screens, which come and go between frames 70 ms apart; neither frame is the
right one. The facing flips are the ring fit's, on stacked icons.

## Identity and lifetimes

`lifetimes` on `A`, `B`, `R15` shifted by one or two cached frames, and the
decode's phase moved 100-400 ms (nine alternatives, each a valid 2 Hz sample):

| session | named share, A (alternatives min-median-max) | named observation share, A (min-median-max) | rank of A, low to high |
|---|---|---|---|
| a06f04a0059f | [metric:ally_icon_resample/lifetimes@a06f04a0059f#named_share_A=0.8829] (0.872-0.883-0.901) | [metric:ally_icon_resample/lifetimes@a06f04a0059f#named_obs_share_A=0.9487] (0.945-0.962-0.979) | [metric:ally_icon_resample/lifetimes@a06f04a0059f#named_obs_rank_from_low=2] of 10 |
| 5822b6646448 | [metric:ally_icon_resample/lifetimes@5822b6646448#named_share_A=0.898] (0.883-0.898-0.927) | [metric:ally_icon_resample/lifetimes@5822b6646448#named_obs_share_A=0.8908] (0.889-0.907-0.928) | [metric:ally_icon_resample/lifetimes@5822b6646448#named_obs_rank_from_low=2] of 10 |
| 75a55a296d3b | [metric:ally_icon_resample/lifetimes@75a55a296d3b#named_share_A=0.6324] (0.643-0.661-0.688) | [metric:ally_icon_resample/lifetimes@75a55a296d3b#named_obs_share_A=0.759] (0.784-0.811-0.824) | [metric:ally_icon_resample/lifetimes@75a55a296d3b#named_obs_rank_from_low=1] of 10 |

Naming is phase-sensitive: a whole piece is named or refused, and which
rounds lose a piece changes with the phase. `A` sits at the low end of the
named-observation share on all three sessions. The decode reads `A`'s phase,
so this is no evidence against the cache; it is unexplained. One hypothesis
failed: `A`'s instants do not fall on the HUD's 500 ms grid, which the roster
and death times use
([metric:ally_icon_resample/buy-phase@a06f04a0059f#a_on_hud_grid_75a55a296d3b=0]
of [metric:ally_icon_resample/buy-phase@a06f04a0059f#a_frames_75a55a296d3b=1261]
on `75a55a296d3b`). Matched observation by
observation, `A` and `B` give different names to
[metric:ally_icon_resample/identity@a06f04a0059f#different=69] observations on
`a06f04a0059f` against
[metric:ally_icon_resample/identity@a06f04a0059f#same=4525] the same, and `B`
alone names [metric:ally_icon_resample/identity@a06f04a0059f#only_B=120]
against `A` alone [metric:ally_icon_resample/identity@a06f04a0059f#only_A=44].
Round 4 of `a06f04a0059f` names Breach, Deadlock, Miks and Reyna in every
stream, all inside the oracle's allies (`tests/test_round_identity_e2e.py`).

## Labels

The player's ally facing labels (`labels/icon_facing_20260928.jsonl`; frame
within 300 ms, centre within 6 px, facing within 20 degrees): on
`a06f04a0059f` `A` finds
[metric:ally_icon_resample/labels@a06f04a0059f#found_A=12] of
[metric:ally_icon_resample/labels@a06f04a0059f#facing_labels=13] and reads
[metric:ally_icon_resample/labels@a06f04a0059f#right_A=7] right, as `B` does;
`R15` at the labelled frame itself reads
[metric:ally_icon_resample/labels@a06f04a0059f#right_R15=5]. On
`5822b6646448` `A` finds
[metric:ally_icon_resample/labels@5822b6646448#found_A=10] of
[metric:ally_icon_resample/labels@5822b6646448#facing_labels=12], reads
[metric:ally_icon_resample/labels@5822b6646448#right_A=2] right, and accepts
both labelled not-icons, as `B` and `R15` do. `labels/minimap` marks enemies
only, and `75a55a296d3b` has no ally labels.

## Speed

One OpenCV thread, Idle priority, the 2 Hz pass then the 15 Hz pass:

| session | 2 Hz s | 15 Hz s | wall speedup | CPU speedup |
|---|---|---|---|---|
| a06f04a0059f | [metric:ally_icon_resample/speed@a06f04a0059f#pass_s_2hz=101.64] | [metric:ally_icon_resample/speed@a06f04a0059f#pass_s_15hz=460.49] | [metric:ally_icon_resample/speed@a06f04a0059f#speedup_wall=4.53] | [metric:ally_icon_resample/speed@a06f04a0059f#speedup_cpu=2.55] |
| 5822b6646448 | [metric:ally_icon_resample/speed@5822b6646448#pass_s_2hz=99.12] | [metric:ally_icon_resample/speed@5822b6646448#pass_s_15hz=477.63] | [metric:ally_icon_resample/speed@5822b6646448#speedup_wall=4.82] | [metric:ally_icon_resample/speed@5822b6646448#speedup_cpu=2.81] |
| 75a55a296d3b | [metric:ally_icon_resample/speed@75a55a296d3b#pass_s_2hz=29.8] | [metric:ally_icon_resample/speed@75a55a296d3b#pass_s_15hz=148.27] | [metric:ally_icon_resample/speed@75a55a296d3b#speedup_wall=4.98] | [metric:ally_icon_resample/speed@75a55a296d3b#speedup_cpu=2.91] |

The 2 Hz pass still grabs every cached frame between samples
(`roi_cache.GRAB_MAX`), and the FFV1 decoder spreads that over its own
threads, so CPU falls less than wall. A decode was not timed.
