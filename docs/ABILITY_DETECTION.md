# Ability detection for every caster

A plan, proposed 2026-09-30. It builds nothing in `reticle/`. Its
measurements come from `prototypes/ability_shape_fast.py` and scratch checks
over the minimap crop cache; nothing decoded a capture.

## 1. What the plan delivers

The entity channel should show every ability on the minimap, the player's,
the teammates' and the enemies', as an identity-bearing track: where it
appears, how it moves, how it ends, and who cast it. Today only the player's
tray casts are fitted, one crop after each drop (`ability_shapes`), and smokes
are tracked from a whole-floor grey search (`minimap_dark`,
`adjudication.smokes`).

The plan has five parts:

- One reader pass over the minimap crop cache per session. Smokes, the drawn
  shapes and the dark ability icons are read in the same pass, and each keeps
  its own stream and version.
- Tracks and lifecycles are built from storage, one rule per ability.
- Names go through the arbiter.
- Events go to an `ability` lane, and the viewer reads that lane.
- The first acceptance metric is recall of unnamed ability entities.

Smokes come out identical to today's reader. The joint scene model stays out
of the pass.

## 2. Owners today

| Question (`reticle ownership`) | Owner | State |
|---|---|---|
| `ability-shape`: Regrowth, Recon Bolt and Hunter's Fury drawings after a tray cast | `ability_shapes` | partial; one crop per cast |
| `ability-detection`: where in the frame an ability entity is | `minimap.detect_ability_*` | partial; fails at 331 px (section 3) |
| `ability-hypothesis`: which components form one entity | `adjudication.ability` | partial |
| `ability-phase`: an entity's phase and its cause | `adjudication.phases` | partial |
| `ability-appearance`: what an ability looks like | `adjudication.gallery` | partial; unwired; its glyph classifier is hand thresholds scored in-sample |
| `ability-owner`: who cast it | none | unowned |
| `minimap-smoke`, `smoke-owner` | `adjudication.smokes`, `smoke_owner` | shipped; the lifecycle and identity precedents |

## 3. What was measured

Every figure below is a recorded run.

**Faster shape fits, same objective.**

- The free ring search costs
  [metric:ability_shape_fast/cost@timing-40#free_ring_s_median=1.6] s per
  331 px crop.
- An exact FFT surface of the same score costs
  [metric:ability_shape_fast/cost@timing-40#exact_surface_s=0.4] s and
  differs from it by at most
  [metric:ability_shape_fast/cost@timing-40#exact_max_abs_diff=1.6e-7].
- A coarse-to-fine version costs
  [metric:ability_shape_fast/cost@timing-40#c2f_s=0.11] s.
- An angular sweep of the beam score costs
  [metric:ability_shape_fast/cost@timing-40#sweep_s=0.012] s, against
  [metric:ability_shape_fast/cost@timing-40#seeded_beam_s_median=0.21] s for
  the seeded fit.
- Accuracy on the player's marks is unchanged:
  - Regrowth: [metric:ability_shape_fast/marks@tray-object-marks#regrowth_c2f=14] of [metric:ability_shape_fast/marks@tray-object-marks#regrowth_n=16]
  - Recon Bolt: [metric:ability_shape_fast/marks@tray-object-marks#recon_c2f=8] of [metric:ability_shape_fast/marks@tray-object-marks#recon_n=8]
  - Fury: [metric:ability_shape_fast/marks@tray-object-marks#fury_sweep=21] of [metric:ability_shape_fast/marks@tray-object-marks#fury_n=21]
  - Pre-cast panels found: [metric:ability_shape_fast/marks@tray-object-marks#pre_found=0] of [metric:ability_shape_fast/marks@tray-object-marks#pre_n=10]
- On the null crops, the best non-Recon ring scores
  [metric:ability_shape_fast/null@sova-skye-null#ring_c2f_max=0.182], below
  the 0.2 acceptance.
- The teal-component gate passes
  [metric:ability_shape_fast/marks@tray-object-marks#gate_post=45] of
  [metric:ability_shape_fast/marks@tray-object-marks#gate_post_n=45]
  post-cast panels,
  [metric:ability_shape_fast/marks@tray-object-marks#gate_pre=0] pre-cast
  panels, and
  [metric:ability_shape_fast/null@sova-skye-null#gate_pass=16] of
  [metric:ability_shape_fast/null@sova-skye-null#crops=130] null crops.

**Shapes from casters other than the player.**

`223d636bf8d2` (player Sova, ally Skye, 331 px) was scanned over every live
sample at 2 Hz: [metric:ability_shape_fast/scan@223d636bf8d2#samples=2821]
samples, of which [metric:ability_shape_fast/scan@223d636bf8d2#gate_pass=261]
passed the gate.

- Ring episodes:
  [metric:ability_shape_fast/scan@223d636bf8d2#ring_episodes=23].
- [metric:ability_shape_fast/scan@223d636bf8d2#ring_player_cast=12] of them
  follow the player's casts, covering
  [metric:ability_shape_fast/scan@223d636bf8d2#recon_casts_found=12] of
  [metric:ability_shape_fast/scan@223d636bf8d2#recon_casts=13] Recon casts.
- [metric:ability_shape_fast/scan@223d636bf8d2#regrowth_at_skye=4] are teal
  rings centred on the ally Skye.
- [metric:ability_shape_fast/scan@223d636bf8d2#recon_refused_drop=4] are
  Recon rings whose tray drops the cast owner refused.
- [metric:ability_shape_fast/scan@223d636bf8d2#ring_off_map=3] are false
  rings centred off the map.
- Beam episodes:
  [metric:ability_shape_fast/scan@223d636bf8d2#beam_episodes=6], all at
  [metric:ability_shape_fast/scan@223d636bf8d2#fury_casts_found=3] of
  [metric:ability_shape_fast/scan@223d636bf8d2#fury_casts=3] Fury casts.

On `a06f04a0059f` (465 px, no Sova or Skye on the player's side) the scan
found [metric:ability_shape_fast/scan@a06f04a0059f#ring_episodes=1] ring,
off the map, and
[metric:ability_shape_fast/scan@a06f04a0059f#beam_episodes=0] beams.

So the shape fitter already finds a teammate's drawing. Its one false class
is a ring centred off the map, which a centre-on-footprint gate removes.

**The generic detectors fail at 331 px.**

- `detect_ability_discs` finds
  [metric:ability_shape_fast/generic@player-labels#discs_paint_hit=26] of
  [metric:ability_shape_fast/generic@player-labels#paint_icons=69] painted
  icons,
  [metric:ability_shape_fast/generic@player-labels#tray_icon_disc_hit=3] of
  [metric:ability_shape_fast/generic@player-labels#tray_icon_targets=66]
  tray-object icons, and
  [metric:ability_shape_fast/generic@player-labels#review_discs_hit=0] of
  [metric:ability_shape_fast/generic@player-labels#review_ability_marks=16]
  review marks on `bfad2778a372`.
- Only
  [metric:ability_shape_fast/generic@player-labels#review_teal_marks=3] of
  those review marks point at teal drawings. The rest are dark icons, smoke
  discs and white areas.

**A dark-icon proposer.** It scores the dark share (V < 75) of a disc of
radius 0.025R-0.075R minus that of a band outside it, on the baked slab only.

- Version 0.1.0, without the slab, hits
  [metric:ability_shape_fast/icons@player-labels#hit_010=112] targets with
  [metric:ability_shape_fast/icons@player-labels#null_cands_per_crop_010=61]
  candidates per null crop.
- Version 0.2.0 hits
  [metric:ability_shape_fast/icons@player-labels#hit_020=123] of
  [metric:ability_shape_fast/icons@player-labels#targets=151] labelled icons
  with [metric:ability_shape_fast/icons@player-labels#null_cands_mean_020=5.8]
  candidates per null crop. By source:
  - tray objects: [metric:ability_shape_fast/icons@player-labels#tray_hit_020=48] of [metric:ability_shape_fast/icons@player-labels#tray_n=66]
  - painted frames: [metric:ability_shape_fast/icons@player-labels#paint_hit_020=64] of [metric:ability_shape_fast/icons@player-labels#paint_n=69]
  - review marks: [metric:ability_shape_fast/icons@player-labels#review_hit_020=11] of [metric:ability_shape_fast/icons@player-labels#review_n=16]
- The weakest abilities:
  - Seekers: [metric:ability_shape_fast/icons@player-labels#seekers=21] of [metric:ability_shape_fast/icons@player-labels#seekers_n=34]
  - Sonic Sensor: [metric:ability_shape_fast/icons@player-labels#sonic_sensor=13] of [metric:ability_shape_fast/icons@player-labels#sonic_sensor_n=18]
  - Trailblazer: [metric:ability_shape_fast/icons@player-labels#trailblazer=12] of [metric:ability_shape_fast/icons@player-labels#trailblazer_n=16]
- [metric:ability_shape_fast/icons@player-labels#hit_white_glyph=116] hits
  carry a white glyph, the cue the classifier will use.
- Reading the radii at 1 px costs
  [metric:ability_shape_fast/icons@player-labels#s_crop_step1=0.034] s per
  crop, against
  [metric:ability_shape_fast/icons@player-labels#s_crop_020=0.15] s, and
  loses no hits: [metric:ability_shape_fast/icons@player-labels#hit_step1=123].

**Smokes from the cache.** `minimap_dark` was fed from the crop cache over
the stored pass's spans, and its rows were compared with the stored rows,
which a video decode wrote.

| Session | Read per sample | Reader per sample | Masks identical at shared instants | Smoke tracks (stored) | Within 250 ms |
|---|---|---|---|---|---|
| `c40d950031bb` | [metric:ability_detection/smoke-cache@c40d950031bb#read_ms=1.7] ms | [metric:ability_detection/smoke-cache@c40d950031bb#feed_ms=8.1] ms | [metric:ability_detection/smoke-cache@c40d950031bb#same=335] of [metric:ability_detection/smoke-cache@c40d950031bb#shared=335] | [metric:ability_detection/smoke-cache@c40d950031bb#tracks=17] ([metric:ability_detection/smoke-cache@c40d950031bb#tracks_stored=17]) | [metric:ability_detection/smoke-cache@c40d950031bb#within_250=16] |
| `a06f04a0059f` | [metric:ability_detection/smoke-cache@a06f04a0059f#read_ms=1.9] ms | [metric:ability_detection/smoke-cache@a06f04a0059f#feed_ms=14.0] ms | [metric:ability_detection/smoke-cache@a06f04a0059f#same=638] of [metric:ability_detection/smoke-cache@a06f04a0059f#shared=638] | [metric:ability_detection/smoke-cache@a06f04a0059f#tracks=31] ([metric:ability_detection/smoke-cache@a06f04a0059f#tracks_stored=31]) | [metric:ability_detection/smoke-cache@a06f04a0059f#within_250=28] |

The few tracks beyond 250 ms come from sampling instants: the cache grid
holds other instants than the decode's stride (the `minimap_dark` docstring
says so).

Cache-fed `minimap_dark` passes took:

- [metric:scan_usage/minimap_dark/cache/serial/cv12@223d636bf8d2~c1d939e0fb5b#pass_s=57.073] s
  on `223d636bf8d2`
  ([metric:scan_usage/minimap_dark/cache/serial/cv12@223d636bf8d2~c1d939e0fb5b#frames=5904] frames);
- [metric:scan_usage/minimap_dark/cache/serial/cv12@ff636d173b07~0e6016cb0e84#pass_s=70.958] s
  on `ff636d173b07`.

The decoding pass on `c40d950031bb` took
[metric:scan_usage/minimap_dark/video/serial/cv12@c40d950031bb~957cdb351545#pass_s=123.69] s.
The cache-fed run there took
[metric:ability_detection/smoke-cache@c40d950031bb#read_s=3.9] s to read and
[metric:ability_detection/smoke-cache@c40d950031bb#feed_s=18.2] s to feed:
**about 5.6 times faster, with the same masks.**

Inside the reader, the player-icon fits are the largest part (section 5), and
identical output forbids skipping them. Sharing the HSV conversion saves
under 2% of the reader's time. No cheaper version gives identical rows.

## 4. The unified pass

The pass follows the predict-verify-widen pattern of
[PRIOR_DRIVEN_READERS.md](PRIOR_DRIVEN_READERS.md), section 2, with its seven
guards. This section states only what is particular to abilities.

**One read, separate definitions.** One `passes.Reader` group reads the
minimap crop cache once per session. A shared decode pass is an execution
optimisation, not a shared definition (`AGENTS.md`), so each detector writes
its own stream with its own stamp:

| Stream | Grid | Work | Version |
|---|---|---|---|
| `minimap_dark` | 4 Hz, spans as today | unchanged | `minimap-dark-0.1.0`, not restamped |
| `ability_gate` | 2 Hz live samples, every other 4 Hz sample | teal components | `ability-gate-0.1.0` |
| `ability_shape_scan` | gated samples | `ability_shapes` ring and beam objective, coarse to fine and swept | `ability-shape-0.2.0` (stage 1) |
| `ability_icon` | 2 Hz live samples | full proposer search on its schedule; verify rows for tracked icons | `icon-proposer-0.2.0` |
| `ability_audit` | fixed cadence (section 4, audits) | full search, stored apart | the detector's own version |

The ability grid sits on the 4 Hz grid, so the shared read costs nothing
extra. A change to the icon proposer restamps `ability_icon` alone. The
smoke stream keeps its stamp, and `reticle plan` names no smoke rerun.

**Priors, and where each one lives.**

- *Opportunity gate (in the reader).* The fits run only where teal forms a
  component at least 0.2R across. The gate needs no other stream, so it
  cannot go stale.
- *Tracking (in the reader, from its own earlier samples, guard 7).* A
  tracked icon is verified where the last sample put it. The full search runs
  on a fixed schedule and on surprise. A verify that fails (the icon lost) is
  a stored surprise row.
- *Births near a caster.* A thrown icon leaves its caster within 0.5 s
  [domain:abilities/minimap-thrown-ability-icon]. The pass computes the
  player's and teammates' icon fits once per sample for `minimap_dark`'s
  occlusion, so the same fits seed the births without reading another stream.
- *Kit (in the owner, not the reader).* The lineup says whose kit draws a
  ring or a beam. Guard 7 keeps cross-stream priors out of a reader. The cost
  agrees: gating the fits on the lineup would save only
  [metric:ability_detection/cost-model@corpus-21#fits_min=11.2] minus
  [metric:ability_detection/cost-model@corpus-21#fits_kit_min=8.0] minutes
  over the corpus. So the reader fits every gated sample. The kit enters at
  identity, where it is declared as `depends_on`.
- *Explaining away.* A candidate on a player icon's fit is labelled, not
  skipped, because the saving is nil (section 5).

**What it absorbs from PRIOR_DRIVEN_READERS.** Of the five ranked
opportunities it absorbs none. Ally icons, self position, pings, spike and
scoreboard remain their own readers. It closes the gap that section 4 of that
document names: "nothing searches near where abilities land." Landing points
become a stored stream (`ability_track` end points), which `smoke_owner` and
`adjudication.smokes` may read from storage. `minimap_dark` itself keeps
searching the whole floor, so its rows stay identical. It also adds a row
the inventory lacked: the ability reader, tracked and audited.

**Audits, bounded.** Each prior gets a full search on opportunity-gated
samples at a cadence fixed in advance, stored apart. It runs only until the
prior's efficacy is statistically significant (`AGENTS.md`, 2026-09-30).

- The test is a one-sided exact binomial on the prior's miss rate against a
  tolerance p0 at alpha 0.05. The audit stops when the Clopper-Pearson upper
  bound falls below p0.
- With p0 = 2% and no misses, that takes 149 audit units; with one miss, 236.
  With p0 = 1% it takes 299.
- Units and cost, one-off per widget size:
  - **Teal gate.** The unit is one ungated live sample of a session with a
    Sova or Skye, given full fits. A miss is an accepted shape the player
    confirms. 149 units cost 149 x
    [metric:ability_detection/profile@223d636bf8d2#fits_ms_gated=151] ms,
    about 23 s, at 331 px, and 149 x
    [metric:ability_detection/profile@a06f04a0059f#fits_ms_gated=188] ms,
    about 28 s, at 465 px.
  - **Icon tracking.** The unit is an icon birth that the scheduled full
    search sees on a sample the tracked path skipped. A miss is a birth the
    tracked path never finds, because the icon lived less than the schedule's
    interval. The audit runs the full search on every skipped sample, which
    costs the difference between the full and tracked schedules: about 53 s
    per 331 px session and 161 s per 465 px session (section 6). It continues
    until 149 classified births, so its length in sessions follows from the
    birth rate the first session measures.
- The cadence is every 10th live 2 Hz sample plus the first sample of each
  round, chosen before any data.

## 5. Does a mesh gain efficiency, or only accuracy?

Measured on 40 evenly spaced live samples per session (stream
`ability_detection/profile`).

**(a) A shared read saves little.**

- The cache read costs
  [metric:ability_detection/smoke-cache@c40d950031bb#read_ms=1.7] to
  [metric:ability_detection/smoke-cache@a06f04a0059f#read_ms=1.9] ms per
  sample.
- In `bfad2778a372`'s ally_icon cache pass, `source_s` was
  [metric:scan_usage/ally_icon/cache/serial/cv12@bfad2778a372~8b1a902fd6c3#source_s=22.562]
  of
  [metric:scan_usage/ally_icon/cache/serial/cv12@bfad2778a372~8b1a902fd6c3#pass_s=922.334]
  s.
- A separate pass per detector would add about 11 s per session.

**(b) Shared intermediates save little, except one.**

- The crop's HSV conversion runs
  [metric:ability_detection/profile@223d636bf8d2#hsv_calls=4] times per
  sample, in grey_dark, ally_icons, the gate and the proposer.
- All colour conversions together cost
  [metric:ability_detection/profile@223d636bf8d2#cvt_all_ms=1.23] of
  [metric:ability_detection/profile@223d636bf8d2#detector_ms=59.8] ms at
  331 px, and
  [metric:ability_detection/profile@a06f04a0059f#cvt_all_ms=2.49] of
  [metric:ability_detection/profile@a06f04a0059f#detector_ms=160.1] ms at
  465 px: about 2%.
- The one large shared intermediate is the player-icon fits:
  [metric:ability_detection/profile@223d636bf8d2#player_icons_ms=6.4] of
  [metric:ability_detection/profile@223d636bf8d2#dark_ms=8.7] ms of
  `minimap_dark` at 331 px, and
  [metric:ability_detection/profile@a06f04a0059f#player_icons_ms=9.4] of
  [metric:ability_detection/profile@a06f04a0059f#dark_ms=13.5] ms at 465 px.
  The pass computes them once and lends them to the icon births and labels.

**(c) Priors: gating pays, explaining away does not, tracking pays only as a
pointwise verify.**

- *Gating.* The teal gate passed
  [metric:ability_shape_fast/scan@223d636bf8d2#gate_pass=261] of
  [metric:ability_shape_fast/scan@223d636bf8d2#samples=2821] live samples on
  `223d636bf8d2` and
  [metric:ability_shape_fast/scan@a06f04a0059f#gate_pass=180] of
  [metric:ability_shape_fast/scan@a06f04a0059f#samples=2990] on
  `a06f04a0059f`. A fit costs
  [metric:ability_detection/profile@223d636bf8d2#fits_ms_gated=151] ms where
  the gate costs
  [metric:ability_detection/profile@223d636bf8d2#gate_ms=3.1] ms, so the gate
  removes over 90% of the fit cost. The lineup gate adds little (section 4).
- *Explaining away.* The reader's own player-icon fits explain
  [metric:ability_detection/profile@223d636bf8d2#cands_explained=1] of
  [metric:ability_detection/profile@223d636bf8d2#cands=366] proposer
  candidates at 331 px and
  [metric:ability_detection/profile@a06f04a0059f#cands_explained=9] of
  [metric:ability_detection/profile@a06f04a0059f#cands=105] at 465 px. They
  cover [metric:ability_detection/profile@223d636bf8d2#slab_explained=0.016]
  of the slab. Explaining away is a label, not a saving.
- *Tracking by window search fails on cost.* Windows of 0.25R round each
  player icon, plus windows of 0.08R round each candidate from 500 ms earlier,
  keep [metric:ability_detection/icon-windows@player-labels#keeps_025_008=120]
  of the [metric:ability_detection/icon-windows@player-labels#full_keeps=120]
  labelled hits the full search keeps. They cost
  [metric:ability_detection/icon-windows@player-labels#ms_025_008=46.8] ms,
  against [metric:ability_detection/icon-windows@player-labels#ms_full=47.1]
  ms for the full search, because each window carries a kernel margin.
- *Tracking by pointwise verify works.* Rescoring each tracked icon at
  centres within 2 px and its own radius and the two beside it costs
  [metric:ability_detection/icon-verify@223d636bf8d2#verify_ms=3.2] ms per
  sample, against
  [metric:ability_detection/icon-verify@223d636bf8d2#full_ms=47.3] ms, at
  331 px. At 465 px it costs
  [metric:ability_detection/icon-verify@a06f04a0059f#verify_ms=1.5] ms
  against [metric:ability_detection/icon-verify@a06f04a0059f#full_ms=128.2]
  ms.
- It reproduces
  [metric:ability_detection/icon-verify@223d636bf8d2#reproduced=284] of
  [metric:ability_detection/icon-verify@223d636bf8d2#continuing=318]
  continuing candidates exactly and
  [metric:ability_detection/icon-verify@223d636bf8d2#within1=310] within
  1 px. At 465 px it reproduces
  [metric:ability_detection/icon-verify@a06f04a0059f#reproduced=35] of
  [metric:ability_detection/icon-verify@a06f04a0059f#continuing=35].
- Births still need the full search:
  [metric:ability_detection/icon-verify@223d636bf8d2#births=70] of
  [metric:ability_detection/icon-verify@223d636bf8d2#cur=388] candidates per
  pair were new at 331 px. Most are not ability icons; they are dark discs
  that come and go. So the plan runs the full search at 1 Hz and the verify
  at 2 Hz. This halves the proposer's cost, and the audit measures what the
  1 Hz schedule misses.

**(d) The joint fit stays out of the pass.**

- The scene model fits one labelled icon with its neighbours in a median
  [metric:scene_stack_eval/331-self@223d636bf8d2+bfad2778a372+c40d950031bb+e37fdeca944f#fit_s_median=0.031]
  to
  [metric:scene_stack_eval/465-ally@5822b6646448+a06f04a0059f#fit_s_median=0.695]
  s on the GPU, and its stacks were its weakest case.
- The player has fixed how a stack is read: as a stable draw order plus each
  icon's occlusion state, carried by tracking
  [domain:minimap/icon-stack-order-is-stable].
- The pass therefore has no joint widening. Its widening is the full
  proposer search and the free shape fit, both measured above. The efficient
  design is cheap proposals, gating and pointwise tracking. A mesh gains
  efficiency through shared player-icon fits and shared tracks, not through
  a joint render.

## 6. Cost per session, and the corpus run

The costs below are per-sample measurements at `223d636bf8d2` (331 px) and
`a06f04a0059f` (465 px). Each session's cost is scaled by its cached frame
count. All run single-threaded at Below Normal priority. This is an
estimate, not a corpus run.

| | 331 px session | 465 px session |
|---|---|---|
| Smokes alone (`minimap_dark`, from the cache) | [metric:scan_usage/minimap_dark/cache/serial/cv12@223d636bf8d2~c1d939e0fb5b#pass_s=57.073] s | [metric:ability_detection/smoke-cache@a06f04a0059f#read_s=11.5] + [metric:ability_detection/smoke-cache@a06f04a0059f#feed_s=86.6] s (this task's run) |
| Unified, full icon search at 2 Hz | [metric:ability_detection/cost-model@corpus-21#ref331_full_s=230] s | [metric:ability_detection/cost-model@corpus-21#ref465_full_s=486] s |
| Unified, icons tracked (full 1 Hz, verify 2 Hz) | [metric:ability_detection/cost-model@corpus-21#ref331_tracked_s=177] s | [metric:ability_detection/cost-model@corpus-21#ref465_tracked_s=325] s |

**The 21 match sessions with a cache**
([metric:ability_detection/cost-model@corpus-21#sessions_331=15] at 331 px,
[metric:ability_detection/cost-model@corpus-21#sessions_465=6] at 465 px):

| Part | Minutes, whole corpus |
|---|---|
| Smokes alone | [metric:ability_detection/cost-model@corpus-21#dark_min=20.4] |
| Teal gate | [metric:ability_detection/cost-model@corpus-21#gate_min=3.8] |
| Shape fits | [metric:ability_detection/cost-model@corpus-21#fits_min=11.2] |
| Icons, full at 2 Hz | [metric:ability_detection/cost-model@corpus-21#icons_full_min=54.6] |
| Icons, tracked | [metric:ability_detection/cost-model@corpus-21#icons_tracked_min=29.6] |
| **Unified, full icons** | [metric:ability_detection/cost-model@corpus-21#full_min=90.0] |
| **Unified, tracked icons** | [metric:ability_detection/cost-model@corpus-21#tracked_min=61.8] |

The tracked total applies the lineup gate to the fits. Without it, the total
is about 3 minutes more.

The brief names 22 sessions, and the store has 21 cached match sessions. If
the 22nd is a 465 px session, it adds at most about 8 minutes. **One corpus
run therefore costs about 1 to 1.6 hours**, against about 20 minutes for
smokes alone. The icon proposer is the largest part, the shape fits come
next, and smokes are the smallest.

**Measured after stage 3.** The unified pass with the full 2 Hz icon search
took [metric:ability_scan/unified-pass@a06f04a0059f#unified_s=463.9] s on
`a06f04a0059f`, against the estimate of
[metric:ability_scan/unified-pass@a06f04a0059f#ref465_full_s=486] s, with
other agents' jobs sharing the machine. One 465 px session confirms the
model there; no 331 px session was timed.

The first run should use the full 2 Hz icon search. It doubles as the
tracking prior's audit: the tracked schedule can be replayed from its rows,
and the miss rate counted, with no second pass.

## 7. Smoke acceptance

Smokes must come out identical to the current reader on `a06f04a0059f` and
`c40d950031bb`. Identity means two things.

1. **Byte-identical to the current reader fed from the same cache grid.**
   The unified pass's `minimap_dark` rows must equal
   `reticle scan SID --only minimap_dark` run from the cache, and
   `reticle smokes SID` over them must give the same tracks. This holds by
   construction if `minimap_dark` keeps its code and version, and the check
   enforces it.
2. **Against the stored, video-decoded rows,** as this task measured:
   - masks identical at every shared instant
     ([metric:ability_detection/smoke-cache@c40d950031bb#same=335] and
     [metric:ability_detection/smoke-cache@a06f04a0059f#same=638]);
   - the same track counts;
   - every track's first and last sighting within one 4 Hz sample, except
     where the two grids hold different instants.

   Each exception is listed by track, not averaged.

## 8. Per-ability candidates, from facts only

Each ability's minimap drawing, lifecycle and inputs are its own
[domain:abilities/ability-rules-are-unique]. The table names only what a
fact states. Everything else waits on the mechanics sheet
([ABILITY_MECHANICS_SHEET.md](ABILITY_MECHANICS_SHEET.md)).

| Ability | Parametric candidate | Lifecycle the fact gives | Fact |
|---|---|---|---|
| Regrowth | teal ring centred on Skye | while channelled; no tray drop | [domain:abilities/skye-regrowth-minimap-ring] [domain:abilities/skye-regrowth-channelled] [domain:abilities/skye-regrowth-no-tray-drop] |
| Recon Bolt | teal ring at the landing, the bolt's icon at its centre | kept while it pulses two or three times | [domain:abilities/sova-recon-bolt-minimap-ring] [domain:abilities/pulse-scan-abilities] |
| Hunter's Fury | straight teal line from Sova's icon | turns between samples while up | [domain:abilities/sova-hunters-fury-minimap-beam] |
| Haunt, Stealth Drone | ring of the range | brief, at the pulse | [domain:abilities/pulse-scan-abilities] |
| Thrown icons (Guiding Light, Prowler, Leer and others) | dark disc 16-24 px, white glyph, some teal-rimmed | leaves the caster within 0.5 s, gone on landing or expiry | [domain:abilities/minimap-thrown-ability-icon] [domain:abilities/skye-guiding-light-minimap-icon] [domain:abilities/fade-prowler-minimap-icon] [domain:abilities/reyna-leer-minimap-icon] |
| Razorvine, Nanoswarm | dark icon with a white glyph near the caster | stays; placed, then activated | [domain:abilities/vyse-razorvine-minimap-icon] [domain:abilities/killjoy-nanoswarm-minimap-icon] [domain:abilities/placed-then-activated] |
| Sonic Sensor, Storm Surge, Cove and others | compact icon with a pale ring or box | placed | [domain:abilities/minimap-icon-pale-region] |
| Trademark | white-rimmed circle round its icon | placed | [domain:abilities/chamber-trademark-minimap-white-area] |
| Enemy Trailblazer, enemy Leer | red ring, white glyph | drawn on the player's minimap | [domain:abilities/skye-trailblazer-enemy-minimap-glyph] [domain:abilities/reyna-leer-enemy-minimap-glyph] |
| Shock Bolt | nothing | -- | [domain:abilities/sova-shock-bolt-minimap-none] |
| Aim previews | the player's own band or line | not an object; gone at the cast | [domain:abilities/minimap-aim-preview] |

**Whose drawings the player's minimap shows (the player, 2026-09-30).**

- Every drawing in the table draws for both sides except smokes
  [domain:minimap/ability-drawings-both-sides]. Enemy smokes are not drawn
  [domain:abilities/enemy-smokes-not-on-minimap].
- Colour follows the side, never self against ally
  [domain:minimap/ability-drawing-colour-by-side]. A teammate's ring, line or
  icon is therefore the player's own model, and the
  [metric:ability_shape_fast/scan@223d636bf8d2#regrowth_at_skye=4] teal rings
  at the ally Skye on `223d636bf8d2` are what it predicts.
- An enemy's drawing shows inside team vision [domain:minimap/vision-gate].
  Some take a red theme; which ones, and their red models, are per ability
  [domain:abilities/ability-rules-are-unique], so no teal model is recoloured
  by analogy.
- A few enemy casts show whatever the vision. The always-visible set:
  - certain: Leer [domain:abilities/reyna-leer-global-minimap] and Haunt
    [domain:abilities/fade-haunt-global-minimap];
  - believed, unverified: Recon Bolt
    [domain:minimap/ability-drawings-both-sides], Lockdown
    [domain:abilities/killjoy-lockdown-global-minimap], Thrash
    [domain:abilities/gekko-thrash-global-minimap], Barrier Orb
    [domain:abilities/sage-barrier-orb-global-minimap], Barrier Mesh
    [domain:abilities/deadlock-barrier-mesh-global-minimap], Hunter's Fury
    [domain:abilities/sova-hunters-fury-global-minimap], Orbital Strike
    [domain:abilities/brimstone-orbital-strike-global-minimap], Cosmic Divide
    [domain:abilities/astra-cosmic-divide-global-minimap] and Toxic Screen
    [domain:abilities/viper-toxic-screen-global-minimap].

So enemy shapes and icons are in scope. The reader searches the whole widget
on every gated sample whichever side cast, and stores what it finds. The
side and the vision test belong to the owners downstream (section 14). Stages
1-3 build no per-ability detector for the always-visible set. Each one's
drawing waits on its own fact or a targeted demo.

## 9. Pure computer vision: the recommendation and its obstacles

Use the measured objective with fast exact search. Do not use generic
detectors.

- **Rings and beams.** Use the coarse-to-fine ring and the swept beam on
  `ability_shapes`' own score (stage 1). Hough finds
  [metric:ability_shape_fast/marks@tray-object-marks#regrowth_hough=10] of 16
  Regrowth rings even after rescoring. Translucent and broken rings defeat
  the gradient vote, while the coverage score tolerates them
  [domain:minimap/fit-not-repair].
- **Icons.** Use the slab-gated dark-disc proposer with radii at 1 px, then a
  classifier over its rim colour, radius, glyph, motion and lifetime.
- **Obstacles, stated honestly:**
  - Rings over the void give false rings centred off the map. Gate the
    centre on the baked footprint, which is geometry, not session pixels
    [domain:capture/session-pixels-are-not-the-map].
  - Pale regions and white areas are not dark discs. The proposer cannot see
    them, so they need their own parametric fits, one per fact.
  - Seekers' recall is the lowest of the labelled abilities (section 3).
  - Enemy drawings show inside team vision, and the always-visible set of
    section 8 outside it. A red rim is faint at 331 px
    [domain:minimap/enemy-rim-faint-at-small-widget].
  - Icons may be exactly coincident [domain:minimap/coincident-icons].
  - The proposer's null rate (about 6 candidates per crop) is mostly dark
    floor discs that come and go. Tracking and the classifier, not the
    proposer, must reject them.
  - The gallery's glyph classifier is scored only in-sample.

## 10. Recall first

The first acceptance metric is recall of **unnamed** ability entities: is
every ability on the minimap found and tracked, whatever its name?

- **Entity recall.** An entity counts as found when one of its tracks covers
  any labelled frame of it. Required: at least 0.9, with a one-sided 95%
  Clopper-Pearson lower bound of at least 0.8. That needs at least 60
  labelled entities per widget size (54 of 60 gives a bound of 0.81).
- **Frame recall** is reported, at least 0.7, because the viewer draws
  frames.
- **Truth comes from an exhaustive labelling pass.** Frames are taken at a
  cadence fixed in advance (every 20th live 2 Hz sample) from sessions chosen
  before the run, with each widget size apart. The player marks every
  ability-made thing on each frame, through the `labelling-pass` skill's
  tool. Today's labels are cast-seeded or painted, so they cannot measure
  recall: they hold only what someone looked for.
- **Specificity** is measured on the same frames: proposals that no label
  explains, per frame.

## 11. The labelling loop

The coverage numbers set the loop. Paint frames reach
[metric:ability_shape_fast/icons@player-labels#paint_hit_020=64] of 69, tray
objects 48 of 66, and review marks 11 of 16. So most unnamed entities will
be found, and naming is the larger task.

1. **Pass 1, recall.** The exhaustive frames of section 10, 60 entities per
   widget size. Output: recall, and the misses as surprise rows.
2. **Pass 2, naming.** Tracks are clustered by rim colour, radius, glyph
   features, motion (static, moving, attached to an icon) and lifetime. The
   player names one exemplar per cluster through the labelling tool. Each
   answer becomes a fact in `domain/abilities.toml` and a mechanics-sheet
   cell, plus a gallery exemplar per ability and phase.
3. **Pass 3, held out.** Classify tracks on sessions that passes 1 and 2 did
   not use. The player confirms 60 per widget size.

The plan expects three passes. *Falsifier:* if pass 2 leaves more than 20%
of tracks in clusters the player cannot name from one exemplar, the cluster
features are wrong. A fourth pass then adds the gallery's glyph features.

## 12. Icons and the gallery

`adjudication.gallery` (`ability-appearance`) is unwired, and its
`classify_ability_glyph` uses hand thresholds scored in-sample on 21 crops.
The plan feeds it pass 2's exemplars per ability and phase and scores it
held out in pass 3. Only then does it name a kind. A kind the gallery cannot
separate stays `unknown`, with its alternatives.

The candidate set is the lineup's agents whose kit draws that class. The
full catalogue is the surprise path and must be justified.

## 13. Tracking and lifecycle, per ability

- **Tracks.** `adjudication.ability` (`ability-hypothesis`) groups stored
  `ability_icon`, `ability_shape_scan` and `minimap_dark` observations into
  tracks. It adds no new owner. Births, moves and ends are observations;
  `began` and `ended` stay inferred and censored, as `adjudication.smokes`
  keeps them.
- **Lifecycles.** `adjudication.phases` applies each ability's rule only
  where a fact gives it (section 8): Recon Bolt's ring for its pulses,
  Guiding Light gone by 4 s, Nanoswarm placed and staying. An ability with no
  fact keeps the generic states (observed, lost, censored) and never borrows
  a sibling's rule [domain:abilities/ability-rules-are-unique].
- **Stacks.**
  - A stack is a stable draw order plus each icon's occlusion state: fully
    visible, partly visible, or mostly or completely obscured
    [domain:minimap/icon-stack-order-is-stable].
  - A change of top icon while the icons still overlap is a stored surprise
    and the fact's falsifier.
  - A shape under an icon is read the same way. The icon's fitted disc is
    excluded from the ring's or beam's mask, and the shape carries a
    "partly occluded" state rather than a lower score.
- **A cheap test of the stack belief, from stored data.**
  - The data: `ally_icon` rows store each icon's ring coverage (`cov`) at
    15 Hz, and `round_entity` links them to tracks.
  - Take pairs of teammate tracks whose centres stay within r1 + r2 for at
    least 3 frames. Call the icon with higher coverage the top one, with a
    0.15 margin, and count changes of top during each overlap run.
  - The control is pairs at 1.0-1.5 (r1 + r2), where no draw order applies.
    Their flip rate is the instrument's noise.
  - The belief predicts an overlap flip rate no higher than the control.
    Flips above it, confirmed on a sheet of the flip frames, falsify it.
  - The test costs seconds and decodes nothing. It was not run.

## 14. Identity

- **Claims.** Each `ability_track` publishes an `identity_claim` to
  `adjudication.identity`, per entity and side.
- **Side** comes from the drawing's colour, which changes by side and never
  self against ally [domain:minimap/ability-drawing-colour-by-side]: teal for
  the player's side, red for the enemy's where the ability takes a red theme
  [domain:abilities/skye-trailblazer-enemy-minimap-glyph]. A drawing whose
  ability keeps one colour for both sides gets its side from other evidence
  (a birth at a teammate's icon, the vision test below) or stays `unknown`.
- **The vision test.** An enemy track outside team vision is a surprise
  unless its ability is in the always-visible set of section 8
  [domain:minimap/ability-drawings-both-sides]
  [domain:abilities/reyna-leer-global-minimap]
  [domain:abilities/fade-haunt-global-minimap]. The surprise is stored with
  the track, never dropped. The set's believed members carry their facts'
  `known` level into the claim, so a track resting on an unverified belief
  says so.
- **Candidates** are the side's agents from the lineup whose kit has the
  track's class: the player's side's five for a teal track, the enemy's five
  for a red one. The claim declares `depends_on` the lineup slots, so the
  lineup is never counted again as a witness.
- **The caster** comes from a birth at a teammate's icon
  [domain:abilities/minimap-thrown-ability-icon], which is a witness that
  `depends_on` that icon's track identity. The `ability-owner` question gets
  its owner: a new `adjudication.ability_owner` that binds tracks to
  witnesses and asks the arbiter. It never names an agent itself.
  [ARBITER_ARCHITECTURE.md](ARBITER_ARCHITECTURE.md) makes it the
  aggregator's ability-owner stage, under the per-ability facts on casting
  while dead and persisting after the owner's death.

## 15. Events and the viewer

- **The lane.** An `ability` lane joins `docs/ENTITY_EVENTS.md`'s order 2,
  minimap channel. Its inputs are `ability_track`,
  `ability_track_identity` and `rounds`.
- **The events.** Family `ability_object`; kind is the catalogue id or
  `unknown`; side; round; observed and inferred lifetime bounds; the path;
  phases; and the occlusion state.
- **The viewer.** `reticle view` reads only the lane. It draws each track,
  its phase and its name, and an unknown kind as "?". A missing field goes
  into the owner's event, never into the viewer.

## 16. Stages and build order

Each stage commits when its evidence holds.

1. **Fast fits.** Move coarse-to-fine and the sweep into `ability_shapes`
   as `ability-shape-0.2.0`, with the centre-on-footprint gate.
   Acceptance: `.\.venv\Scripts\python.exe prototypes\ability_shape_eval.py`
   and its null run. Evidence: Fury 21/21, Regrowth at least 14/16, Recon
   8/8, pre-cast 0/10, the null maximum below 0.2, and at most 0.15 s per
   crop.
2. **Unified pass with smokes identical.** Write a `reticle/ability_scan.py`
   reader group, `reticle scan SID --only ability`, with `minimap_dark`
   unchanged plus the gate and shape streams. Acceptance:
   `.\.venv\Scripts\python.exe tools\smoke_identity.py a06f04a0059f c40d950031bb`,
   built from this task's check. Evidence: section 7's two identities, and
   no smoke restamp in `reticle plan`. Held on 2026-09-30: rows and tracks
   byte-identical, masks identical at
   [metric:ability_scan/smoke-identity@a06f04a0059f#same=638] of
   [metric:ability_scan/smoke-identity@a06f04a0059f#shared=638] and
   [metric:ability_scan/smoke-identity@c40d950031bb#same=65] of
   [metric:ability_scan/smoke-identity@c40d950031bb#shared=65] shared
   instants, and
   [metric:ability_scan/smoke-identity@a06f04a0059f#within_250=27] and
   [metric:ability_scan/smoke-identity@c40d950031bb#within_250=16] tracks
   within 250 ms; every exception lies at a stored instant the cache grid
   lacks.
3. **Icon proposer.** Add `ability_icon` with `icon-proposer-0.2.0` at
   radius step 1, a full search at 2 Hz, and verify rows. Acceptance: the
   proposer's label scoring as a `tools/` benchmark. Evidence: at least 123
   of 151 hits, at most 6 candidates per null crop, and cost within 20% of
   section 5. Held on 2026-09-30 (`reticle/ability_icons.py`,
   `tools/ability_icon_benchmark.py`):
   [metric:ability_icons/bench@player-labels#hits=123] of
   [metric:ability_icons/bench@player-labels#targets=151] hits,
   [metric:ability_icons/bench@player-labels#null_cands_mean=5.82]
   candidates per null crop, and a full search of
   [metric:ability_icons/bench@player-labels#full_ms_331=46.2] ms at 331 px
   and [metric:ability_icons/bench@player-labels#full_ms_465=125.1] ms at
   465 px. The benchmark reads the cost bound one-sided: a cheaper search
   passes. Other agents' jobs shared the machine, unmeasured; an earlier
   run of the same code was about a quarter faster.
4. **Recall pass.** The player labels section 10's frames. Acceptance:
   `.\.venv\Scripts\python.exe tools\ability_recall.py`, built in this
   stage over the recall labels. Evidence: entity recall and its lower bound, per widget size.
5. **Tracks and lifecycles.** `adjudication.ability` tracks and
   `adjudication.phases` rules per fact. Acceptance:
   `.\.venv\Scripts\python.exe -m reticle ability-entities SID` on the
   recall sessions. Evidence: entity recall at least 0.9 with a lower bound
   of at least 0.8; stack surprises stored; the tracked schedule replayed
   from the full rows within the audit's tolerance.
6. **Naming loop and gallery.** Passes 2 and 3. Acceptance:
   `.\.venv\Scripts\python.exe -m reticle ability-gallery`, scored held out.
   Evidence: 60 confirmed per widget size, with unknown kinds kept.
7. **Identity, lane and viewer.** Acceptance:
   `.\.venv\Scripts\python.exe -m reticle project SID --lane ability` then
   `reticle view`. Evidence: the drop rule passes, and the player checks the
   viewer on one round per widget size.

The order is fast fits, then the unified pass, then icons, then recall,
then tracks, then naming, then identity and viewer. The corpus run (section
6) belongs after stage 3, once the player approves its cost.

## 17. Questions for the player

These were checked against `domain/*.toml` and the private domain notes
first. The player answered the first four on 2026-09-30; the answers are
facts, cited here rather than restated.

1. *A teammate's Recon Bolt ring, Hunter's Fury line or Regrowth ring.*
   Answered: a teammate's drawing is the player's own, because colour changes
   by side and never self against ally
   [domain:minimap/ability-drawing-colour-by-side].
2. *An enemy's Recon ring or Fury line.* Answered: every drawing but smokes
   draws for both sides, an enemy's inside team vision, and a few always
   [domain:minimap/ability-drawings-both-sides]. Hunter's Fury is believed to
   be among those [domain:abilities/sova-hunters-fury-global-minimap]; section
   8 lists the always-visible set.
3. *Teammates' thrown icons.* Answered by the same fact: every team-owned
   entity always shows [domain:minimap/ability-drawings-both-sides].
4. *Smokes and recall.* Answered: smokes stay out of the recall target and
   keep their own lane (`minimap_dark`, `adjudication.smokes`).
5. The bfad review marks include a pale-halo icon with a target glyph. Name
   it, and the others, through the labelling tool in pass 2, not in chat.
   Open.

The stack belief [domain:minimap/icon-stack-order-is-stable] stands as
section 13 uses it; its cheap test is still unrun.

## 18. Not measured

- No corpus run was made; section 6 is an estimate.
- The tracked icon schedule was not run end to end. Its recall loss is
  unknown until the first run's replay.
- Icon recall for teammates' and enemies' casts is unmeasured: the targets
  are mostly the player's casts and painted devices.
- The stack-order test of section 13 was not run.
- The 22nd session of the brief is not identified.
- The cached-terms proposer differed from 0.2.0 on 40 of 130 null crops,
  and the cause was not found. Step 1.0 is the measured variant used here.
