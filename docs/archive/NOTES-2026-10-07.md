# Reticle working handoff

## Picking up

**2026-10-07.** Master stands at `26c2d33`, pushed. The [backlog](BACKLOG.md) order: the enemy lane, reader and belief; the slot model, revised by this session's reach findings; the execution readers. The last handoff of 10-06 is [archived](docs/archive/NOTES-2026-10-06-night.md).

### The frame

Fidelity follows the question (AGENTS.md); [COACHING_QUESTIONS.md](docs/COACHING_QUESTIONS.md) ranks the decision questions, [EXECUTION_QUESTIONS.md](docs/EXECUTION_QUESTIONS.md) the mechanics questions, and [QUESTION_ACCEPTANCE.md](docs/QUESTION_ACCEPTANCE.md) section 7 holds the bar. The bar is now QA5r3 (player, 2026-10-07): each arm is scored against replay truth (T1) beside the 15 Hz real-read arm on the same instances; a sight question fails only when its 95% interval lies wholly below a 5-point loss; read share at most 0.06.

### Real-reader schedule (`prototypes/real_reader_schedule.py`, merged)

- `Vgate` (the real gate over real ally reads) passes QA5r3 post hoc at a read share of [metric:real_reader_schedule/qa5r3/Vgate@dev2#share=0.0283]. Its losses run from [metric:real_reader_schedule/qa5r3/Vgate@dev2#contact_C.loss=-0.0072] on contacts and [metric:real_reader_schedule/qa5r3/Vgate@dev2#duel_C.loss=-0.0123] on duels to [metric:real_reader_schedule/qa5r3/Vgate@dev2#opening_first_seer.loss=-0.0625] on the opening first seer, [metric:real_reader_schedule/qa5r3/Vgate@dev2#first_sight_support.loss=-0.0833] on first-sight support and [metric:real_reader_schedule/qa5r3/Vgate@dev2#spacing_death.loss=-0.0807] on spacing at death.
- The cheap fixes recover little. Retrying lost reads (`Vgate-r`) nearly doubles the share to [metric:real_reader_schedule/qa5r3/Vgate-r@dev2#share=0.0515] and leaves spacing at death at [metric:real_reader_schedule/qa5r3/Vgate-r@dev2#spacing_death.loss=-0.0807]; moving reads to frames where the widget is drawn (`Vgate-d`) gives [metric:real_reader_schedule/qa5r3/Vgate-d@dev2#spacing_death.loss=-0.0683]. The residual loss is 0.5 Hz interpolation.
- Lost ally reads fall on frames with the widget undrawn or beside another icon, and come in runs.
- Sparse rebinding keeps dense binding's slot on [metric:real_reader_schedule/rr6@c817691bcd15#same_slot_share=0.9633] and [metric:real_reader_schedule/rr6@d3dcfb182ab1#same_slot_share=0.9737] of fits.
- The red-pixel gate cue fires on [metric:real_reader_schedule/cost@c817691bcd15#cue_positive_share=0.9967] of crops; its red comes from icons and X marks drawn over the map, never from the baked map ([metric:real_reader_schedule/cue_residual@c817691bcd15#red_sources_no_enemy_share.baked_map_art=0.0]).

### Reach questions

- `join_death` (a teammate can reach, within 5 m of walk on `coaching_belief`'s grid, a cell that sees the killer) loses [metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#join_death.loss=-0.0062] under `Vgate`.
- `spacing_region` (callout relation) loses less than metre spacing: [metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#spacing_region.loss=-0.0497] against [metric:real_reader_schedule/reach/Vgate_vs_V15h@dev2#spacing_death.loss=-0.0807], and [metric:real_reader_schedule/reach/Vgate_vs_V15h@dev3#spacing_region.loss=-0.0717] against [metric:real_reader_schedule/reach/Vgate_vs_V15h@dev3#spacing_death.loss=-0.0802].
- Region-border crossings come rarer than metre-cut crossings ([metric:real_reader_schedule/reach/crossings@dev2#region_per_s=0.1627] against [metric:real_reader_schedule/reach/crossings@dev2#metre_per_s=0.2184] per player-second) and interpolation misdates fewer ([metric:real_reader_schedule/reach/crossings@dev2#region_dated_wrong=0.1881] against [metric:real_reader_schedule/reach/crossings@dev2#metre_dated_wrong=0.2714]).
- Only [metric:real_reader_schedule/reach/borders@dev-maps#narrower=14] of [metric:real_reader_schedule/reach/borders@dev-maps#borders=71] callout borders are narrower than their regions: callouts are not chokepoints.
- Trade rate rises with the joinable count: [metric:real_reader_schedule/reach/value@replays17#joinable0.trade_rate=0.1086], [metric:real_reader_schedule/reach/value@replays17#joinable1.trade_rate=0.3247], [metric:real_reader_schedule/reach/value@replays17#joinable2.trade_rate=0.4389] for none, one, two.
- The gate's 20 m radius over-reaches by walk distance.
- Join questions collapse on full-rate real reads because the real enemy lane rarely places the killer: `join_death` holds [metric:real_reader_schedule/reach/V15h_vs_T1@dev2#join_death.acc=0.6335] with real enemies, [metric:real_reader_schedule/reach/V15t_vs_T1@dev2#join_death.acc=0.913] with truth enemies.

### Enemy lane and the T1 draw rule

- `prototypes/enemy_lane_check.py`: most T1-drawn misses are T1 errors, not reader misses; the classes are the agent's by eye, not the player's labels.
- `prototypes/t1_draw_rule.py` builds T1d: persistence measured at [metric:t1_draw_rule/persistence@dev3#smoke_clean.median_ms=548.4] ms [domain:minimap/vision-trailing-persistence], both teams' smokes block sight [domain:abilities/minimap-vision-cone-blockers], and dead enemies are never drawn. On c817691bcd15 the reader's hit rate rises from [metric:t1_draw_rule/lane/T1@c817691bcd15#hit_rate=0.3021] under T1 to [metric:t1_draw_rule/lane/T1d@c817691bcd15#hit_rate=0.5626] under T1d.
- Rederived on T1d: the gate opens at onset on [metric:t1_draw_rule/truth/T1d/gate_onset@pooled17#open_0=0.8657] (T1 [metric:t1_draw_rule/truth/T1/gate_onset@pooled17#open_0=0.9211]), the local gate on [metric:t1_draw_rule/truth/T1d/gate_onset@pooled17#local_open=0.8152], median lead [metric:t1_draw_rule/truth/T1d/gate_onset@pooled17#lead_ms_p50=476.5] ms; `Lp0.5-250w5` reads [metric:t1_draw_rule/truth/T1d/Lp0.5-250w5@pooled17#share=0.0386] (T1 [metric:t1_draw_rule/truth/T1/Lp0.5-250w5@pooled17#share=0.0484]); schedule agreement barely moves. The minimap's ceiling against full truth falls.
- T1d supersedes T1's draw rule for later scoring.

### Execution questions ([EXECUTION_QUESTIONS.md](docs/EXECUTION_QUESTIONS.md), merged)

- The replay carries shots, hit regions and view angles on the 8 ms tick, and blinds on [metric:execution_questions/truth/check@pooled17#replays_with_blinds=14] replays.
- Duel value: the better-placed crosshair wins [metric:execution_questions/value/placement@pooled17#paired.share=0.6135]; a first shot that hits lifts the win share by [metric:execution_questions/value/first_bullet@pooled17#hit.diff=0.3087]; shooting still lifts it by [metric:execution_questions/value/speed_at_shot@pooled17#still_vs_moving.diff=0.0745]. Shooting first does not win ([metric:execution_questions/value/reaction@pooled17#paired.share=0.4496]).
- Placement from the minimap cone keeps [metric:execution_questions/value/placement_cone@pooled17#paired.share=0.5831], an upper bound.
- Priority (player, 2026-10-07): crosshair placement and movement first; aim only if particularly bad; spray discipline open. Capture settings are domain facts [domain:capture/crosshair-white-cross] [domain:hud/hit-yellow-flash] [domain:capture/enemy-highlight-red].

### Unmerged branches

`w1-ally-prior-score-20261006`, `w2-self-tracker-score-20261006` (negative results). Carried: `one-pass-ingest-20261005`; held `whitened-weapon-20261003`, `whitened-weapon-null-20261004`; rework `binding-rules-20261002`; WIP `luma-render-20261002`, `wip-vision-lifecycle-wiring`; plans `killfeed-prior-design-20261002`, `killfeed-prior-step1-20261002`; `enemy-fix-check-20260930`; stale leftovers in the [10-05 archive](docs/archive/NOTES-2026-10-05-to-10-06.md).

Capture paths: 043bafca271a `C:\Users\grant\Videos\2026-08-25 13-59-44.mp4`; 0f08b3dc3777 `C:\Users\grant\Videos\2026-08-23 16-51-47.mp4`; 223d636bf8d2 `C:\Users\grant\Videos\2026-08-23 20-09-01.mp4`; 3694746e4e54 `C:\Users\grant\Videos\2026-08-25 14-42-25.mp4`; 4f207c0c4e39 `C:\Users\grant\Videos\2026-09-27 19-40-58.mp4`; 5822b6646448 `C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`; 587c15b07779 `C:\Users\grant\Videos\2026-09-05 19-21-29.mp4`; 59c70f1ef720 `C:\Users\grant\Videos\2026-08-24 13-58-11.mp4`; 7010b3d62460 `C:\Users\grant\Videos\2026-09-07 19-46-44.mp4`; 75a55a296d3b `C:\Users\grant\Videos\2026-08-24 13-34-38.mp4`; 96aa1ae9b96f `C:\Users\grant\Videos\2026-08-24 17-51-06.mp4`; 9acf02f98283 `C:\Users\grant\Videos\2026-08-24 11-55-34.mp4`; a06f04a0059f `C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`; a1a995e6b19b `C:\Users\grant\Videos\2026-09-08 13-09-13.mp4`; b3b9defb6fd7 `C:\Users\grant\Videos\2026-08-23 18-24-15.mp4`; b7d24102a6f6 `C:\Users\grant\Videos\2026-08-24 12-37-04.mp4`; bdfdcf009dba `C:\Users\grant\Videos\2026-08-23 19-25-23.mp4`; bfad2778a372 `C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`; c40d950031bb `C:\Users\grant\Videos\2026-08-24 18-27-17.mp4`; c62c2b06bcfb `C:\Users\grant\Videos\2026-08-26 13-18-48.mp4`; c817691bcd15 `C:\Users\grant\Videos\2026-10-05 13-10-55.mp4`; d95cfad5693a `C:\Users\grant\Videos\2026-09-02 16-08-43.mp4`; dae6f33f3f48 `C:\Users\grant\Videos\2026-09-03 19-10-11.mp4`; e37fdeca944f `C:\Users\grant\Videos\2026-08-25 13-17-45.mp4`; ff636d173b07 `C:\Users\grant\Videos\2026-08-24 18-47-51.mp4`; d3dcfb182ab1 `C:\Users\grant\Videos\2026-10-05 18-13-01.mp4`; cea8ecbc94ab `C:\Users\grant\Videos\2026-10-05 19-18-53.mp4`.

The untracked `prototypes/mechanics_eval.py` belongs to the user; leave it untouched.
