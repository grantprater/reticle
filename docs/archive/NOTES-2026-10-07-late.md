# Reticle working handoff

## Picking up

**2026-10-07, late.** Master stands at `4a71ffb`, pushed. The [backlog](BACKLOG.md) order holds: the enemy lane, reader and belief; the slot model; the execution readers. The earlier 10-07 handoff, with the real-reader schedule, reach and execution findings, is [archived](docs/archive/NOTES-2026-10-07.md). The bar stays QA5r3 against replay truth with T1d as the draw rule ([QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7).

### Enemy teardrop (merged, `4a71ffb`)

- A diagnosis of the T1d-drawn misses by stored refusal reason found the teardrop refusing visible enemy icons as `no_ring`, worst at the 331 px widget. The fit read icons at widget scale (0.712); icons follow the map zoom [domain:minimap/icons-follow-map-zoom], so the right scale on 9acf02f98283 is 0.637. `ring_cover` also binarised each bin before cutting the share.
- The fix reads icons at `geometry.MapScale`, scores the ring softly and cuts once, adds a `no_lobe` refusal, and hands a read on a confirmed ping (within `PING_OWN_PX`, 7 base px) or a shape-confirmed X to its owner. Ping 0.2.0 joins danger-ping runs across their white flash [domain:minimap/danger-ping-flash].
- On 9acf02f98283 the T1d hit rate rose from [metric:teardrop_refusals/lane/stored@9acf02f98283#hit_rate=0.442] to [metric:teardrop_refusals/lane/final@9acf02f98283#hit_rate=0.6313]; `no_ring` misses fell from [metric:teardrop_refusals/lane/stored@9acf02f98283#no_ring=767] to [metric:teardrop_refusals/lane/final@9acf02f98283#no_ring=27]. True false accepts end at [metric:teardrop_refusals/lane/r1@9acf02f98283#false_accepts=138], within the bar of 159. c817691bcd15 and d3dcfb182ab1 hold within their intervals.
- The 194 to 138 drop rests on pings reread from the crop cache; the production ping-0.2.0 stream is unmeasured. `PING_OWN_PX` was fitted on the development matches: no other session has replay truth, so it is unconfirmed out of sample.
- Most remaining extras are visible enemy icons T1d calls undrawn, a T1d finding. The true false accepts left: pink X marks the X classifier misses at 0.71 (tolerance under the 2 px chroma block [domain:capture/chroma-420]), enemy utility discs, Reyna's Leer [domain:abilities/reyna-leer-enemy-minimap-glyph].
- The `minimap_object`, `ping`, `enemy_track` and `death` streams are stale against the new stamps; `reticle plan` names them. They wait for the batched corpus rerun.
- The classes above are the agents' by eye, not the player's labels.

### The one transform (unmerged, `one-transform-rebased-20261007`)

The player's rule of 2026-09-30, one base set times widget scale times map zoom, reached only the ability readers (29863ff). Every other reader sized map-drawn things by widget scale alone. Every 331 px key reads widget 0.7118 times zoom 0.8951; every 465 px key reads zoom 1.0, so only 331 px captures moved.

- `f46a173` (rebased on `4a71ffb`) wires `MapScale` into the enemy, self, ally, ping, smoke, spike and cone readers, retires `SELF_FACING_GATES`, `LABELLED_SCALES` and `spike.ZOOM_RANGE`, and adds a doctor SCALE check with a reasoned allowlist (`doctor.SCALE_WIDGET_USES`).
- Measured on the pre-rebase `e283468`, 9acf02f98283: self recall 0.681 to 0.763, self median error 1.43 to 0.69 px, ally facing median 3.91 to 2.94 degrees; no intervals yet. The player's own clicked tips give a 331/465 ratio of 0.605, which supports the zoom. c817691bcd15 is unchanged, as zoom 1.0 predicts.
- The enemy lane's true false accepts rose to 240, above the bar. The agent's ablation ties the rise to rounding the search radius down at scale 0.637. `023a4a8` (WIP, unmeasured) searches inside the scaled band. Next: rerun, re-stamp, test, review, merge.
- Bumping `minimap-dark` makes `reticle smokes` refuse until `minimap_dark` is rescanned; whether it rereads from the cache is unchecked.
- Unwired: the X-mark input to the death stream, `floor_mask`, `site_mask`, the occluder bake.

### Unmerged branches

`one-transform-rebased-20261007` (above); `one-transform-readers-20261007` (its pre-rebase base, superseded). From earlier: `w1-ally-prior-score-20261006`, `w2-self-tracker-score-20261006` (negative results; w2 holds stamps the one transform skipped past); `one-pass-ingest-20261005`; held `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework `binding-rules-20261002`; WIP `luma-render-20261002`, `wip-vision-lifecycle-wiring`; plans `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; `enemy-fix-check-20260930`.

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
