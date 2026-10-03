# Killfeed portrait separability

Findings of `prototypes/killfeed_portrait_separability.py`
(`portrait-separability-0.1.0`, `wire: no`), 2026-10-03. Predictions and
outcome: `killfeed-portrait-separability-20261003` in the store's
`notes/predictions.jsonl`.

## Question

The stored portrait descriptor (`appearance.hsv_composition`, scored by
`adjudication.identity` against the official art) keeps the palette and
discards the layout. It confused Fade with Iso, Clove with Reyna and
Brimstone with Breach. Which descriptor separates every agent pair widely,
and at what cost?

## Method

Riot's match records label the stored deaths' bound portrait views. The
labels come from unambiguous rows paired by time, scored by
`prototypes/riot_ground_truth.py` against master's `death-adjudication-0.28.0`
streams. Tiles come from the HUD ROI crop cache, with no decode, on 21
matches. Every trained descriptor is fitted leave-one-session-out.

## Results

Each cell gives top-1 within the side's five, on clean views.

| descriptor | killer | victim | killer, all 29 agents | killer z-margin median / p5 | killer entries wrong | Fade/Iso gallery |
|---|---|---|---|---|---|---|
| current | [metric:portrait_separability/current#clean_killer_side5=0.9304] | [metric:portrait_separability/current#clean_victim_side5=0.9299] | [metric:portrait_separability/current#clean_killer_all=0.7411] | [metric:portrait_separability/current#clean_killer_zmargin_med=2.45] / [metric:portrait_separability/current#clean_killer_zmargin_p5=-0.26] | [metric:portrait_separability/current#entries_killer_wrong=168] | [metric:portrait_separability/current#gallery_fade_iso_right=0] |
| art ZNCC, inner | [metric:portrait_separability/zncc_inner#clean_killer_side5=0.9998] | [metric:portrait_separability/zncc_inner#clean_victim_side5=0.9996] | [metric:portrait_separability/zncc_inner#clean_killer_all=0.9997] | [metric:portrait_separability/zncc_inner#clean_killer_zmargin_med=26.28] / [metric:portrait_separability/zncc_inner#clean_killer_zmargin_p5=19.38] | [metric:portrait_separability/zncc_inner#entries_killer_wrong=31] | [metric:portrait_separability/zncc_inner#gallery_fade_iso_right=11] |
| LDA fingerprint | [metric:portrait_separability/lda#clean_killer_side5=1.0] | [metric:portrait_separability/lda#clean_victim_side5=0.9996] | [metric:portrait_separability/lda#clean_killer_all=0.9996] | [metric:portrait_separability/lda#clean_killer_zmargin_med=42.73] / [metric:portrait_separability/lda#clean_killer_zmargin_p5=30.24] | [metric:portrait_separability/lda#entries_killer_wrong=68] | [metric:portrait_separability/lda#gallery_fade_iso_right=11] |
| pHash | [metric:portrait_separability/phash#clean_killer_side5=0.9961] | [metric:portrait_separability/phash#clean_victim_side5=0.9959] | [metric:portrait_separability/phash#clean_killer_all=0.9883] | [metric:portrait_separability/phash#clean_killer_zmargin_med=6.3] / [metric:portrait_separability/phash#clean_killer_zmargin_p5=3.46] | [metric:portrait_separability/phash#entries_killer_wrong=66] | [metric:portrait_separability/phash#gallery_fade_iso_right=11] |

Every layout-keeping descriptor separates the three confused pairs. The
current scorer's worst pairs are Brimstone/Breach and Fade/Iso, both with
negative median margins. The killer entries the art ZNCC still gets wrong
are entries whose portrait lies outside the searched strip, so no agent
correlates.

The table omits the other rows: the art ZNCC searched about the box, about
the anchor and over the whole strip, the Lab grid, the gradient grid, and
both grids combined. They are in the run log.

### Three geometry facts the art ZNCC needed

- **Victim portraits are the art mirrored.** On every clean view of four
  matches, the flipped strip scored higher for victims and the unflipped
  strip for killers.
- **The feed is right-aligned.** The victim art's last column sits at ROI
  column `roi_w - 11` on almost every victim view, while the stored victim
  box wanders over about 20 px. With the stored box, victim top-1 is
  [metric:portrait_separability/zncc_box#clean_victim_side5=0.4539]; with
  the anchor it is
  [metric:portrait_separability/zncc_anchor#clean_victim_side5=0.9996].
- **The player's own portrait carries a yellow frame**
  [domain:killfeed/self-yellow-frame], over the art's outer rows. With the
  frame weighted, the player's own entries correlated near 0.5. With the
  art's 4 px border unweighted (`zncc_inner`), the killer z-margin median
  rose from
  [metric:portrait_separability/zncc_wide#clean_killer_zmargin_med=8.37] to
  [metric:portrait_separability/zncc_inner#clean_killer_zmargin_med=26.28].

### The claim, simulated

Each view's posterior over the side's five uses the Gaussian LLR form of
`identity.portrait_llr`, with a "none of them" hypothesis at LLR 0, and
names at 0.9. An entry is named when two or more views name and all of them
agree. Under that rule, `zncc_inner` named no unambiguous entry wrongly:

- killer: [metric:portrait_separability/claims/zncc_inner+none/killer#right=2671]
  right, [metric:portrait_separability/claims/zncc_inner+none/killer#refused=64]
  refused;
- victim: [metric:portrait_separability/claims/zncc_inner+none/victim#right=2712]
  right, [metric:portrait_separability/claims/zncc_inner+none/victim#refused=27]
  refused.

The current scorer under the same rule:

- killer: [metric:portrait_separability/claims/current/killer#wrong=56]
  wrong, [metric:portrait_separability/claims/current/killer#refused=387]
  refused;
- victim: [metric:portrait_separability/claims/current/victim#wrong=58]
  wrong, [metric:portrait_separability/claims/current/victim#refused=391]
  refused.

Exemplars and the other channels are not simulated.

### Cost

On one CPU thread:

- the art ZNCC over 5 candidates and 15 shifts takes
  [metric:portrait_separability/timing#zncc5_search15_cpu=631.9] µs per tile;
- the current path takes
  [metric:portrait_separability/timing#current_5shift_5agents=588.4] µs;
- the LDA projection and scores take
  [metric:portrait_separability/timing#lda_project_and_score5=0.9] µs, but
  its gradient grid input takes
  [metric:portrait_separability/timing#hog=496.1] µs.

The timings varied by about 30% between runs.

## Reading

The art is the fingerprint the player described. Every agent's portrait is
one fixed picture, so correlating against it needs no training. It also
reaches agents absent from the corpus (Harbor, Veto, Viper), though none of
them was measured.

The learned LDA separates seen agents widely, but it fails on any agent
unseen in training. The perceptual hash is as fast as the LDA, but it
separates less widely and scores worse against all 29 agents.

The per-pair overlays (`fingerprint`) put the weight on hair, the eyes and
the beard, not on the plate.
