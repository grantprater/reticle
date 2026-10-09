# Ally icons keyed by luma and fitted by a render

Archived 2026-10-09 from `luma-render-20261002` (19c2a0a, tag
`archive/luma-render-20261002`). The work is unverified: four E2 slices never
ran, and `prototypes/scene_stack.py` is the render path now. The prototypes it
names survive only at the tag.

2026-10-02. [CAPTURE_PSF.md](CAPTURE_PSF.md) measured the capture's blur:
luma nearly pixel-sharp, chroma in 2x2 blocks [domain:capture/chroma-420].
The ally reader keys the teal rim on HSV (`minimap.ally_mask`), that is on
the blocky chroma, so a one-pixel rim loses saturation to the floor beside
it. Two prototypes test whether the sharp luma recovers what the chroma
loses: `prototypes/luma_render.py` (E1, a key fed to the stored ring fit)
and `prototypes/luma_render_e2.py` (E2, a YCbCr render-and-compare over the
reader's candidates). Both read only the minimap crop cache; no video was
decoded, no reader stamp moved, and `reticle/` is unchanged. Task
`luma-render-20261002` in the store's `notes/predictions.jsonl` holds every
prediction, amendment and outcome; files sit in the store's
`analysis/luma-render-20261002/`.

**E2_SUMMARY**

The blur is a per-source input. `luma_render.Source` carries the chroma
block (2 for H.264 4:2:0, 1 for a 4:4:4 live frame) and the luma sigma; E2's
`RAMP` carries the luma edge ramp per source and switches the 4:2:0 chroma
model off for 4:4:4. Every session scored here is H.264 4:2:0. The lossless
capture `C:\Users\grant\Videos\2026-08-26 09-16-10.avi` (4:4:4), the proxy
for live frames, is not ingested, and its map matches none of the twelve
baked `(map, profile)` keys, so no static exists to measure its PSF or run
E1 against [domain:capture/session-pixels-are-not-the-map]; it was skipped.

Test slices: 223d636bf8d2 1250-1410 s (C:\Users\grant\Videos\2026-08-23
20-09-01.mp4, Haven, 331 px), 3694746e4e54 884-1044 s
(C:\Users\grant\Videos\2026-08-25 14-42-25.mp4, Ascent, 331 px),
a06f04a0059f 600-760 s (C:\Users\grant\Videos\2026-08-26 09-56-37.mp4,
Ascent, 465 px), e78e75b2d191 all cached frames
(C:\Users\grant\Videos\2026-09-03 19-16-07.mp4, a solo demo, capacity 0).
Calibration slices: 223d636bf8d2 1090-1250 s, a06f04a0059f 440-600 s.
Score: `upscale_trial.score`'s roster residual (icons less alive teammates),
condition `1.0` the stored reader rerun (it reproduces the stored stream);
bounds are the 95% paired block-bootstrap half-width.

## E1: a luma-shaped key (`luma`)

Shape from luma against the baked static less a lighting opening; teal from
the 2x2 chroma block unmixed by luma coverage; one soft score cut once.

| roster MAE | A (stored reader) | `luma` | `luma2` (E1b) |
|---|---|---|---|
| 223d636bf8d2 | [metric:luma_render/e1@223d636bf8d2#mae_1p0=0.6266] | [metric:luma_render/e1@223d636bf8d2#mae_luma=1.1004] | [metric:luma_render/e1@223d636bf8d2#mae_luma2=0.6289] (bound [metric:luma_render/e1@223d636bf8d2#noise_bound_mae_luma2=0.1073]) |
| 3694746e4e54 | [metric:luma_render/e1@3694746e4e54#mae_1p0=0.5455] | [metric:luma_render/e1@3694746e4e54#mae_luma=0.8002] | [metric:luma_render/e1@3694746e4e54#mae_luma2=0.2246] (bound [metric:luma_render/e1@3694746e4e54#noise_bound_mae_luma2=0.1364]) |
| a06f04a0059f | [metric:luma_render/e1@a06f04a0059f#mae_1p0=0.2763] | [metric:luma_render/e1@a06f04a0059f#mae_luma=1.1405] | [metric:luma_render/e1@a06f04a0059f#mae_luma2=0.2677] (bound [metric:luma_render/e1@a06f04a0059f#noise_bound_mae_luma2=0.2024]) |
| e78e75b2d191 (phantoms per frame) | [metric:luma_render/e1@e78e75b2d191#mae_1p0=0.0213] | [metric:luma_render/e1@e78e75b2d191#mae_luma=0.7098] | [metric:luma_render/e1@e78e75b2d191#mae_luma2=0.0475] |

- **`luma` failed everywhere.** It recovered under-counted teammates
  (3694746e4e54's under-count fell from
  [metric:luma_render/e1@3694746e4e54#under_1p0=0.3799] to
  [metric:luma_render/e1@3694746e4e54#under_luma=0.0362]) but made more
  phantoms than it recovered. The sheets showed why: unmixing divides small
  chroma differences by a small luma coverage, so lit floor with a faint
  teal cast, teal ability lines and green scenery seen through the widget
  all key; where the floor is as bright as the ring, the key falls back to
  that amplified chroma. The fatter key also fills portraits (the inner
  gate refuses) and joins touching icons.
- **E1b, `luma2`, an amendment logged after `luma` failed:** the HSV key
  seeds, and grows by at most 2 px into pixels whose luma rises and whose
  raw block chroma is teal. No component starts outside the HSV key.
  - 3694746e4e54 improves beyond the bound: d MAE
    [metric:luma_render/e1@3694746e4e54#d_mae_luma2=-0.3209], interval
    [metric:luma_render/e1@3694746e4e54#d_mae_lo_luma2=-0.4585] to
    [metric:luma_render/e1@3694746e4e54#d_mae_hi_luma2=-0.1858]; exact frames
    rise from [metric:luma_render/e1@3694746e4e54#exact_1p0=0.5735] to
    [metric:luma_render/e1@3694746e4e54#exact_luma2=0.823]. Ten of twelve
    sheeted added icons are real teammates whose pale rim the HSV key
    fragments; seven of twelve lost icons are fits on teal ability beams.
  - 223d636bf8d2 and a06f04a0059f do not change beyond the bound. On Haven
    half the added icons sit on teal ability arcs, which the grow lengthens;
    on the 465 px widget the grow fattens the lobe, and eleven of twelve lost
    icons are real.
  - e78e75b2d191 rises by [metric:luma_render/e1@e78e75b2d191#d_mae_luma2=0.0262]
    phantoms per frame, on five frames in the first 19 s where teal scenery
    fills the widget and the stored reader already reads up to seven
    phantoms. That exceeds the logged 0.043 limit, so the falsifier is met.

## E2: render and compare

E2_BODY

## Rerun

```powershell
.\.venv\Scripts\python.exe prototypes\luma_render.py e1-run 3694746e4e54 --between 884 1044 --cond luma2
.\.venv\Scripts\python.exe prototypes\luma_render.py e1-score 3694746e4e54 --between 884 1044
.\.venv\Scripts\python.exe prototypes\luma_render_e2.py cands 223d636bf8d2 --between 1250 1410
.\.venv\Scripts\python.exe prototypes\luma_render_e2.py fit 223d636bf8d2 --between 1250 1410
.\.venv\Scripts\python.exe prototypes\luma_render_e2.py score --calib 223d636bf8d2:1090-1250 a06f04a0059f:440-600 --test 223d636bf8d2:1250-1410 3694746e4e54:884-1044 a06f04a0059f:600-760 e78e75b2d191:all
```

`e1-run --cond 1.0` must exist for every slice before `e1-score` or E2's
`score`.
