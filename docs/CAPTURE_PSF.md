# The capture's blur on the minimap

2026-10-02. The player's hypothesis: every minimap element passes through one
nearly fixed blur (the game's anti-aliased draw, OBS's downscale, 4:2:0
chroma [domain:capture/chroma-420], H.264), and a fit through that blur
recovers an icon at sub-pixel precision. `prototypes/capture_psf.py` measured
the blur on the baked map's wall lines (stage 1) and fitted ally icons through
it (stage 2). It read only the minimap crop cache; no video was decoded and no
reader stamp moved. Task `capture-psf-20261001` in the store's
`notes/predictions.jsonl` holds the selection rule, the predictions, one
amendment and both outcomes.

**The blur is one narrow luma PSF, fixed in capture pixels, with no ringing.
Fitting ally icons through it gave the right size but no steadier centre than
the stored pose, and as a verifier it worsened the roster score.**

Sessions: `a06f04a0059f` (C:\Users\grant\Videos\2026-08-26 09-56-37.mp4,
Ascent, 465 px), `223d636bf8d2` (C:\Users\grant\Videos\2026-08-23
20-09-01.mp4, Haven, 331 px), `043bafca271a` (C:\Users\grant\Videos\2026-08-25
13-59-44.mp4, Haven, 331 px; its key's static was built from `223d636bf8d2`,
so it is the held-out session).

## Stage 1: the PSF

Edges come from the key's baked static only
[domain:capture/session-pixels-are-not-the-map]: axis-aligned wall lines cut
into 8 px chunks with opaque map on both sides. A frame counts for a chunk
only when its plateaus match the static; the transition pixels are never
gated. Each profile is three flat levels seen through a Gaussian whose sigma
includes the pixel aperture. 500 cached frames per session.

| Session | chunks | luma sigma | vertical | horizontal | chroma step v / h | aligned 2x2 chroma blocks constant |
|---|---|---|---|---|---|---|
| a06f04a0059f | [metric:capture_psf/stage1@a06f04a0059f#chunks=216] | [metric:capture_psf/stage1@a06f04a0059f#luma_sigma=0.245] | [metric:capture_psf/stage1@a06f04a0059f#luma_sigma_v=0.23] | [metric:capture_psf/stage1@a06f04a0059f#luma_sigma_h=0.25] | [metric:capture_psf/stage1@a06f04a0059f#chroma_step_sigma_v=1.21] / [metric:capture_psf/stage1@a06f04a0059f#chroma_step_sigma_h=1.24] | [metric:capture_psf/stage1@a06f04a0059f#block_aligned=0.9864] |
| 223d636bf8d2 | [metric:capture_psf/stage1@223d636bf8d2#chunks=60] | [metric:capture_psf/stage1@223d636bf8d2#luma_sigma=0.25] | [metric:capture_psf/stage1@223d636bf8d2#luma_sigma_v=0.25] | [metric:capture_psf/stage1@223d636bf8d2#luma_sigma_h=0.25] | [metric:capture_psf/stage1@223d636bf8d2#chroma_step_sigma_v=1.59] / [metric:capture_psf/stage1@223d636bf8d2#chroma_step_sigma_h=1.15] | [metric:capture_psf/stage1@223d636bf8d2#block_aligned=0.9903] |
| 043bafca271a | [metric:capture_psf/stage1@043bafca271a#chunks=60] | [metric:capture_psf/stage1@043bafca271a#luma_sigma=0.255] | [metric:capture_psf/stage1@043bafca271a#luma_sigma_v=0.285] | [metric:capture_psf/stage1@043bafca271a#luma_sigma_h=0.245] | [metric:capture_psf/stage1@043bafca271a#chroma_step_sigma_v=1.83] / [metric:capture_psf/stage1@043bafca271a#chroma_step_sigma_h=1.31] | [metric:capture_psf/stage1@043bafca271a#block_aligned=0.9931] |

Sigma is in native capture px; medians over chunks.

- **One form fits all three.** The tolerance, fixed before the second and
  third sessions were measured, was the within-session half-IQR on
  `a06f04a0059f`, [metric:capture_psf/stage1@a06f04a0059f#luma_sigma_half_iqr=0.0912]
  px; the largest gap between sessions, in vertical width, stays inside it.
  Dividing by the widget scale would separate the two widget sizes far beyond
  it, so the blur belongs to the capture, not to the drawn map.
- **The PSF is narrower than predicted.** A pixel box plus a small Gaussian
  fits as well as the Gaussian (horizontal extra sigma
  [metric:capture_psf/stage1@a06f04a0059f#boxgauss_sigma_h=0.17] on
  `a06f04a0059f`, [metric:capture_psf/stage1@043bafca271a#boxgauss_sigma_h=0.09]
  on `043bafca271a`): edges are close to pixel-sharp.
- **No ringing.** The mean residual past the edge stays within
  [metric:capture_psf/stage1@223d636bf8d2#ringing_max_abs=0.0014] of the
  contrast.
- **Chroma is 4:2:0 duplicated in pairs aligned to even frame coordinates.**
  Aligned 2x2 blocks are constant (table); blocks offset by one pixel in x
  are constant only [metric:capture_psf/stage1@a06f04a0059f#block_off_x=0.4497]
  of the time. A left-sited [1 2 1]/4 filter fits the horizontal profiles
  better than a pair mean, as H.264's default siting predicts; an odd-aligned
  model fits worst. A free Gaussian is a bad instrument on chroma (it reads
  the staircase as sharp steps); the single-step width in the table is the
  effective chroma blur.
- **The static is placed right.** Line centres sit within
  [metric:capture_psf/stage1@043bafca271a#offset_mid_v=-0.0075] px of the
  static's on the held-out session.

## Stage 2: ally icons through the PSF

The ally teardrop (`teardrop.ICON_CLASSES['ally']`) times `geometry.map_scale`
times a free scale, rendered through the stage-1 PSF (luma) and the 4:2:0
model (chroma), at each stored `ally-icon-0.7.0` detection. Colours are
solved linearly, so nothing is thresholded before the decision. The first
sheet showed a dark rim outside the ring, so a one-pixel rim layer was added
before any score was computed (amendment record).

| | 223d636bf8d2 1250-1410 s | a06f04a0059f 600-760 s |
|---|---|---|
| median r_out, px | [metric:capture_psf/icons@223d636bf8d2#r_out=6.5259] (map scale [metric:capture_psf/icons@223d636bf8d2#map_scale_r_out=6.679], widget scale [metric:capture_psf/icons@223d636bf8d2#widget_scale_r_out=7.474]) | [metric:capture_psf/icons@a06f04a0059f#r_out=10.4803] |
| changed stationary pairs | [metric:capture_psf/icons@223d636bf8d2#changed_pairs=666] | [metric:capture_psf/icons@a06f04a0059f#changed_pairs=1118] |
| centre step, mean px: PSF / stored pose / ring | [metric:capture_psf/icons@223d636bf8d2#psf_changed_mean=0.274] / [metric:capture_psf/icons@223d636bf8d2#stored_changed_mean=0.1249] / [metric:capture_psf/icons@223d636bf8d2#ring_changed_mean=0.2257] | [metric:capture_psf/icons@a06f04a0059f#psf_changed_mean=0.0941] / [metric:capture_psf/icons@a06f04a0059f#stored_changed_mean=0.0733] / [metric:capture_psf/icons@a06f04a0059f#ring_changed_mean=0.294] |
| span RMS, median px: PSF / stored / ring | [metric:capture_psf/icons@223d636bf8d2#psf_span_rms_median=0.0629] / [metric:capture_psf/icons@223d636bf8d2#stored_span_rms_median=0.0425] / [metric:capture_psf/icons@223d636bf8d2#ring_span_rms_median=0.0] | [metric:capture_psf/icons@a06f04a0059f#psf_span_rms_median=0.0617] / [metric:capture_psf/icons@a06f04a0059f#stored_span_rms_median=0.0545] / [metric:capture_psf/icons@a06f04a0059f#ring_span_rms_median=0.1176] |
| roster MAE, stored | [metric:capture_psf/icons@223d636bf8d2#mae_stored=0.6266] | [metric:capture_psf/icons@a06f04a0059f#mae_stored=0.2763] |
| roster MAE, PSF verifier | [metric:capture_psf/icons@223d636bf8d2#mae_verifier=0.8553] | [metric:capture_psf/icons@a06f04a0059f#mae_verifier=0.3171] |

- **Size held.** On the 331 px widget the fitted icon matches the map-scale
  size, not the widget-scale one; on the 465 px widget the free scale stays
  at one.
- **Jitter failed.** The PSF centre moves less than 0.15 px between
  stationary frames, but never half as little as the stored pose. The stored
  pose sits on a 1/16 px grid and the ring fit on whole pixels; both hold
  still when the pixels barely change, which the stationarity rule (luma
  inside the portrait unchanged) cannot tell from a truly fixed icon. The
  comparison therefore rewards quantisation; it does not show the PSF fit
  noisier.
- **The verifier failed.** The likelihood cut, calibrated on 223d636bf8d2
  1090-1250 s and a06f04a0059f 440-600 s, accepts every icon; only the teal
  gate acts, and it refuses real teammates whose fitted ring is pale on the
  331 px widget, raising the under-count.
- **Sheets** (`icon_sheet_*` in the analysis folder). On clean icons the
  render matches the observed teardrop and the three centres agree within
  about 0.1 px. Refusals are two overlapping icons fitted as one, and a
  stored pose on empty floor. The residual lies on the portrait and on lit
  floor, which a static background with one gain cannot model.

Multi-frame portrait reconstruction was not assessed.

## Rerun

```powershell
.\.venv\Scripts\python.exe prototypes\capture_psf.py measure a06f04a0059f
.\.venv\Scripts\python.exe prototypes\capture_psf.py compare a06f04a0059f 223d636bf8d2 043bafca271a
.\.venv\Scripts\python.exe prototypes\capture_psf.py plot a06f04a0059f 223d636bf8d2 043bafca271a
.\.venv\Scripts\python.exe prototypes\capture_psf.py icons 223d636bf8d2 --between 1250 1410
.\.venv\Scripts\python.exe prototypes\capture_psf.py icon-score --calib 223d636bf8d2:1090-1250 a06f04a0059f:440-600 --test 223d636bf8d2:1250-1410 a06f04a0059f:600-760
.\.venv\Scripts\python.exe prototypes\capture_psf.py record a06f04a0059f 223d636bf8d2 043bafca271a
```

`icon-score` needs `icons` run on all four slices first. Outputs land in
`<store>/analysis/capture-psf-20261001/`.

## Caveats

- The walls are static, so H.264 refines them over many frames; a moving
  icon may be blurred more than a wall.
- Stage 1 measures axis-aligned walls only; a diagonal or curved edge was not
  measured.
- The scale and the rim layer were fitted on two sessions only.
