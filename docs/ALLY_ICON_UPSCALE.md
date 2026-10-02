# Ally icons on smoothly enlarged crops

2026-10-01. The player watches captures in VLC, which shows the 1080p frame
about 1.2x larger through a smooth filter, and asked whether readers should
read pixels as displayed. `prototypes/upscale_trial.py` reran the ally-icon
reader (`ally-icon-0.7.0`) on minimap crop-cache frames enlarged with
`cv2.INTER_LANCZOS4`, with every value the reader takes from the crop's width
scaled by the same factor and the five it does not scaled by a prototype hook
(see its docstring). No video was decoded; no reader stamp moved.
Task `upscale-trial-20261001` in the store's `notes/predictions.jsonl`.

**Enlarging adds nothing the reader could not get at native size.** On the
465 px widget the roster score did not move beyond noise. On the 331 px widget
it improved by about the noise bound. Lowering the ring fit's radius floor
on native crops recovers most of that gain with no enlargement.

Sessions: `e78e75b2d191` (C:\Users\grant\Videos\2026-09-03 19-16-07.mp4, solo
Omen demo, Ascent, 465 px, all 658 cached frames), `a06f04a0059f`
(C:\Users\grant\Videos\2026-08-26 09-56-37.mp4, Ascent, 465 px, 600-760 s),
`223d636bf8d2` (C:\Users\grant\Videos\2026-08-23 20-09-01.mp4, Haven, 331 px,
1250-1410 s).

## The score

The roster residual the ally channel is benchmarked on
(`round_lifetimes.ally_capacity`): on in-round frames where the stored stream
saw the widget and a self fit and the roster is read, accepted non-barrier
icons less the capacity. Mean |residual| (MAE), lower is better:

| Session | A native | B 1.2x | C 2.0x | D 1.2x and back | native, floor 5 |
|---|---|---|---|---|---|
| a06f04a0059f | [metric:upscale_trial/roster@a06f04a0059f#mae_1p0=0.2763] | [metric:upscale_trial/roster@a06f04a0059f#mae_1p2=0.3022] | [metric:upscale_trial/roster@a06f04a0059f#mae_2p0=0.2794] | [metric:upscale_trial/roster@a06f04a0059f#mae_1p2rt=0.2739] | |
| 223d636bf8d2 | [metric:upscale_trial/roster@223d636bf8d2#mae_1p0=0.6266] | [metric:upscale_trial/roster@223d636bf8d2#mae_1p2=0.5753] | [metric:upscale_trial/roster@223d636bf8d2#mae_2p0=0.5566] | [metric:upscale_trial/roster@223d636bf8d2#mae_1p2rt=0.6744] | [metric:upscale_trial/roster@223d636bf8d2#mae_1p0r7=0.5811] |

Frames: [metric:upscale_trial/roster@a06f04a0059f#n_1p0=1274] and
[metric:upscale_trial/roster@223d636bf8d2#n_1p0=857]. On the solo demo every
accepted ally icon is a phantom: A reads
[metric:upscale_trial/roster@e78e75b2d191#mae_1p0=0.0213] per frame and B
[metric:upscale_trial/roster@e78e75b2d191#mae_1p2=0.0197].

**The noise bound** is the larger of the 95% paired block-bootstrap half-width
of B - A (10 s blocks) and |D - A|, the change resampling alone causes on A's
grid. The reader is deterministic, so a rerun on the same pixels moves
nothing. On a06f04a0059f B is worse by less than its bound
([metric:upscale_trial/roster@a06f04a0059f#noise_bound_mae_1p2=0.0361]). On
223d636bf8d2 B gains
[metric:upscale_trial/roster@223d636bf8d2#d_mae_1p2=-0.0513] against a bound
of [metric:upscale_trial/roster@223d636bf8d2#noise_bound_mae_1p2=0.0485]: the
pre-registered falsifier is met by a hair, while the bootstrap interval still
includes zero. C gains
[metric:upscale_trial/roster@223d636bf8d2#d_mae_2p0=-0.07] against a bound of
[metric:upscale_trial/roster@223d636bf8d2#noise_bound_mae_2p0=0.0629].
Resampling alone (D) worsens the same slice by
[metric:upscale_trial/roster@223d636bf8d2#d_mae_1p2rt=0.0478].

## Where the 331 px gain comes from

The ring fit searches integer radii from `int(round(R_MIN * sc))`
(`reticle/minimap.py:974`). `R_MIN` is 8 base px, 5.7 px on the 331 px
widget, so A's smallest radius is 6; B's grid reaches 7/1.2 = 5.83 native px.
`prototypes/upscale_trial.py explain` sampled 40 of the
[metric:upscale_trial/explain@223d636bf8d2#differing_frames_1p2=199] frames
whose residual differs. Of the
[metric:upscale_trial/explain@223d636bf8d2#cond_only_1p2=31] icons B accepts
and A does not,
[metric:upscale_trial/explain@223d636bf8d2#cond_only_a_cov_gate_1p2=8] are
fits A made at radius 6 or 7 that failed the coverage gate (0.225 against
`ALLY_COV_MIN` 0.25, `minimap.py:920`) where B's fit at 5.83 px passed, and
at [metric:upscale_trial/explain@223d636bf8d2#cond_only_a_no_fit_1p2=16] A
made no fit near the icon at all. A accepts
[metric:upscale_trial/explain@223d636bf8d2#a_only_1p2=19] icons B does not.

Native crops with `R_MIN` at 7 base px, a floor of 5 px (condition
`1.0r7`), gain [metric:upscale_trial/roster@223d636bf8d2#d_mae_1p0r7=-0.0455]
with no enlargement, about nine tenths of B's gain. Its icons that A refuses
are the same two kinds
([metric:upscale_trial/explain@223d636bf8d2#cond_only_a_cov_gate_1p0r7=19]
at the coverage gate,
[metric:upscale_trial/explain@223d636bf8d2#cond_only_a_no_fit_1p0r7=14] with
no fit in A). On the 465 px widget the floor is 8 px in A and C but rounds up
to 10/1.2 = 8.33 native px in B, which may explain why B alone scores worse
there; that is untested.

## What else moved

- The player's facing labels: every condition hits all
  [metric:upscale_trial/labels@a06f04a0059f#facing_labels_hit_1p0=13] on
  a06f04a0059f and all
  [metric:upscale_trial/labels@223d636bf8d2#facing_labels_hit_1p0=9] on
  223d636bf8d2, with median centre error within 0.1 px of A's. On
  223d636bf8d2 B reverses one of A's two facing flips. On a06f04a0059f's
  `prior_ally` answers B finds
  [metric:upscale_trial/labels@a06f04a0059f#prior_teammate_hit_1p2=11] of 12
  teammates where A finds
  [metric:upscale_trial/labels@a06f04a0059f#prior_teammate_hit_1p0=9]; C
  and D find 9. Counts this small decide nothing.
- On 223d636bf8d2 the portrait descriptor refuses as `interior_too_thin` on
  [metric:upscale_trial/interior@223d636bf8d2#interior_too_thin_share_1p2=0.8473]
  of B's accepted icons against
  [metric:upscale_trial/interior@223d636bf8d2#interior_too_thin_share_1p0=0.2337]
  of A's. The hook scales `appearance.MIN_PIXELS` by S^2, but the disc is cut
  at the ring fit's integer radius and on this widget sits on the 64-pixel
  floor (`AllyIconReader._posed`'s docstring), so the area threshold does not
  scale as an area. The refusal reaches identity, not the roster score.
- `minimap.SEARCH` (5 px, `minimap.py:535`), the self channel's centroid
  search, does not scale with the widget. The first run left it unscaled and
  lost the self icon on most frames at 2.0x; the files are kept under
  `analysis/upscale-trial-20261001/run1-search-unscaled/`. Scaled, B and C
  keep the self fit on
  [metric:upscale_trial/roster@e78e75b2d191#self_seen_1p2=528] and
  [metric:upscale_trial/roster@e78e75b2d191#self_seen_2p0=563] frames of the
  demo, against A's
  [metric:upscale_trial/roster@e78e75b2d191#self_seen_1p0=555].
- `_reach` marches rays from `r + 1` in 0.7 px steps (`minimap.py:657`);
  the hook does not scale it.

## Rerun

    .\.venv\Scripts\python.exe prototypes\upscale_trial.py run 223d636bf8d2 --scale 1.0 --between 1250 1410
    .\.venv\Scripts\python.exe prototypes\upscale_trial.py run 223d636bf8d2 --scale 1.2 --between 1250 1410
    .\.venv\Scripts\python.exe prototypes\upscale_trial.py score 223d636bf8d2 --between 1250 1410

Condition A reproduces the stored stream: on a06f04a0059f, 5942 of 5949 rows
agree, as `reticle trial --reader ally_icon` finds, and the seven that differ
move only the pose's prior fields at the slice's cold start.

[CAPTURE_PSF.md](CAPTURE_PSF.md) measures the capture's blur on the same
crops and fits ally icons through it on the same two slices.
