# 3D sightlines from the game files: feasibility probe

Status: findings, recorded 2026-10-04. Code: `prototypes/sightlines_3d.py`
(the probe ran `sightlines-3d-0.1.0` on Ascent and Split; `sightlines-3d-0.2.0`
built all 13 maps of the player's history, see "Every map in the player's
history"; both used placeholder body heights; `sightlines-3d-0.3.0` rebuilt
the 13 with the game's, see "Body heights (0.3.0)"; `sightlines-3d-0.4.0`
rebuilt Summit and Bind without their state-changing props, see
"State-changing props (0.4.0)"); predictions
`sightline-3d-20261004` S1-S5, `sightline-3d-heights-20261004` H1-H5 and
`sightline-3d-props-20261005` P1-P5 and `wallbang-probe-20261005` W1-W5
(`prototypes/wallbang_probe.py`, see "Wallbangs (wallbang-probe-0.1.0)") in the
store's `notes/predictions.jsonl`. The figures in the sections before
"Body heights (0.3.0)" are 0.1.0 and 0.2.0 runs under the placeholders: eye
160 cm, chest 120 cm, crouch room 100 cm, jump 120 cm. It serves the coaching question of
[COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md): whether a teammate
can swing, trade or support from where he stands.

## Answer

Yes. The extracted collision gives a true 3D sightline map of Ascent on one
core in seconds, and it agrees with the kills far better than the minimap.

- The extractor dumps every placed mesh of Ascent's 43 sublevels in 6 s;
  the build keeps [metric:sightlines_3d/build/ascent#placements_kept=6220]
  placements and [metric:sightlines_3d/build/ascent#n_weapon_tris=1932946]
  triangles that block the Weapon trace channel.
- A 1 m standing grid holds [metric:sightlines_3d/build/ascent~2026-10-04T22:03:17#n_cells=9516]
  cells; all [metric:sightlines_3d/build/ascent~2026-10-04T22:03:17#pairs=45272370] cell pairs cast
  in [metric:sightlines_3d/build/ascent~2026-10-04T20:46:21#seconds_table=10.4] s and the whole
  compact file is [metric:sightlines_3d/build/ascent~2026-10-04T20:46:21#bytes=17481575] bytes.
- Riot positions are UE world (X, Y) unchanged:
  [metric:sightlines_3d/gate/ascent#frame_identity_on_floor=0.993] of them
  stand on a floor of the geometry, against
  [metric:sightlines_3d/gate/ascent#frame_swap_on_floor=0.008] with the axes
  swapped.
- [metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_share=0.869] of the development
  set's gun kills on Ascent have 3D line of sight from the killer's eye to the
  victim's chest; the minimap's 2D walls give
  [metric:sightlines_3d/gate/ascent#los2d_share=0.549]. Against every other
  living opponent at the same instant (post hoc control), 3D gives
  [metric:sightlines_3d/gate/ascent#control_los3d_share=0.076]: the 3D map
  separates the man who was shot from the men who were not.

## What was exported, and what was left out

`game-extract meshes` (added to the store's extractor at its commit
92fab56, build release-13.06-shipping-18-5590001; each 0.2.0 table's
provenance names the commit) writes each StaticMeshComponent and each
instance of an instanced component with its world matrix, its BodyInstance
and those of its archetypes, `bUseDefaultCollision`, and each mesh's trace
flag, default collision, simple shapes and collision-LOD triangles.

- **Blocks sight**: a component whose collision answers queries and whose
  response to the Weapon channel (`GameTraceChannel1` in
  `DefaultEngine.ini`, default Block) is Block. Meshes flagged
  `CTF_UseComplexAsSimple` (most art) trace their render triangles; the rest
  trace their simple shapes.
- **Kept**: every always-loaded sublevel and the bomb-mode level. Glass,
  foliage and invisible walls stay in or out by their own collision profile:
  `InvisibleWall` and `WorldInvisibleCollision` ignore Weapon and drop out.
- **Left out**: `Gameplay_Dynamic` (Ascent's roll-up doors, the switch, a
  breakable window, armour plates: their state changes inside a round),
  `Greybox` (not streamed in a match), the other mode levels and the spawn
  barriers (they fall when the round starts). Bullet penetration is not
  modelled: a wallbang is a gun kill without line of sight.
- **State-changing props on other maps**: maps without a `Gameplay_Dynamic`
  level keep doors, switches and breakables in always-loaded levels. Their
  actor classes, read off each map's dump, leave them out: `TimedDoorEvac_C`
  (Bind, Breeze, Fracture), `Drawbridge_C`, `Switch_HiddenTemple_C` and
  `RespawningWallPlate_C` (Lotus), `DroppableDoorCover_C`,
  `RespawningPlummetShootable_C` and `BP_Breakable_Simple_Rockman_C`
  (Summit), `BP_Breakable_Simple_Saltman_Helmet_C` (Corrode),
  `BP_Destructible_BASE_C` (Icebox, Fracture), `Switch_BlackMarket_2_C` and
  `WindowShield_C` (Sunset), `RespawningWallPlate_C` (Haven, Abyss). Spawn
  barriers in the `Barriers` levels of Abyss, Sunset and Summit leave by the
  `SpawnBarrier` prefix. Ascent's and Split's 0.2.0 tables equal their 0.1.0
  tables array for array.
- **Floors** use the Pawn channel's blockers. A floor is an up-facing
  walkable face with crouch room above it, inside one of the map's callout
  volumes: the game's own named playable regions. Without that limit the
  first grid stood on a pawn lid 35 m up.

## The frame and multi-level spots

Riot records give 2D positions. Each position's column is cast from above
and every standable floor recorded.
[metric:sightlines_3d/gate/ascent#within_1m_identity=0.998] of positions
have a floor within 1 m. Ascent has two or more standable floors under
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#multi_level_share=0.153] of positions
(Split [metric:sightlines_3d/gate/split~2026-10-04T22:11:22#multi_level_share=0.475]), most in
the A site, A link, B site, back B and market callouts, where tall callout
volumes hold roofs and canopies above the floor. The pre-registered rule takes the lowest
floor. Two post hoc rules bound the choice: the floor joined to the largest
walkable component gives
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_component_floor_share=0.876], and the
best of every floor pair gives
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_any_pair_share=0.898]. A movement
model, or replay heights scored as truth, settles it.

## The disagreements

[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#d3clear_d2blocked=254] kills are clear in
3D and blocked on the minimap;
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#d3blocked_d2clear=21] go the other way.
Ten inspected (seven and three):

- Clear in 3D, blocked in 2D: no blocking triangle lies on any of the seven
  eye-to-chest lines; a cast through every placement on three of them met
  only volumes. The 2D line crosses minimap wall pixels: positions beside
  corners, shots between heights (median gap 1 m against 0 m where the two
  agree) and long lines (median 19.9 m against 14.5 m). Boxes explain one of
  the seven, and 53 of the 254. Whether the minimap frame misplaces some of
  these positions was not settled.
- Blocked in 3D, clear in 2D: crates on A site, the B-site platform between
  two players 1.2 m apart on different floors, and a box on B site. Box cover
  under the placeholder eye height, the lowest-floor rule, or a wallbang.

Post hoc: tracing render triangles for every mesh moves 3D line of sight to
87.2%; aiming at the victim's head instead of the chest gives
[metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_head_share=0.898]. Split, built as a
second map and not pre-registered, gives
[metric:sightlines_3d/gate/split~2026-10-04T22:11:22#los3d_share=0.911] in 3D against
[metric:sightlines_3d/gate/split#los2d_share=0.707] in 2D.

## Predictions

S1 held (identity frame). S2 failed: multi-level spots are 15%, not under
10%. S3 held. S4 failed narrowly: 2D line of sight is 54.9%, below the
predicted 55-80%, in the predicted direction. S5 failed on the cell count
(9516, below 10k) and held on time and size.

## Every map in the player's history

The player's history holds 13 maps in 168 matches (the 2 held-out replay
matches listed in it excluded; the other 12 held-out matches and the 22
captured ones are not in that table). The probe estimated them from Split,
[metric:sightlines_3d/build/split~2026-10-04T20:46:54#seconds_table=27.4] s
and [metric:sightlines_3d/build/split~2026-10-04T20:46:54#bytes=14049033]
bytes. `sightlines-3d-0.2.0` built all 13 on one core at Below Normal while
other work shared the CPU, with the probe's method: static meshes that block
the Weapon channel through the game's collision profiles, doors, breakables
and state-changing props out, Riot positions as world (X, Y).

The gate is the probe's: line of sight from the killer's eye to the
victim's chest at exact positions, gun kills, lowest-floor rule; the control
is the killer against every other living opponent at the same instant (post
hoc). Maps with development kills are gated on them, against the 2D map on
the same kills. The six maps without development kills (and without baked 2D
geometry) are gated on the confirmation history's kills as an instrument
check only: no hypothesis is scored, and the held-out replay, captured and
ladder `holdout` matches stay out. Build seconds are the visibility table's,
then the whole build's.

| Map | Dump | Table bytes | Build s | Cells | Gate set | 3D line of sight | 2D line of sight | 3D control |
|---|---|---|---|---|---|---|---|---|
| Abyss | 46.7 MB | [metric:sightlines_3d/build/abyss~2026-10-04T22:09:51#bytes=26679301] | [metric:sightlines_3d/build/abyss~2026-10-04T22:09:51#seconds_table=50.6] (60) | [metric:sightlines_3d/build/abyss~2026-10-04T22:09:51#n_cells=17846] | development | [metric:sightlines_3d/gate/abyss~2026-10-04T22:11:29#los3d_share=0.907] of 86 | [metric:sightlines_3d/gate/abyss#los2d_share=0.651] | [metric:sightlines_3d/gate/abyss#control_los3d_share=0.079] (2D [metric:sightlines_3d/gate/abyss#control_los2d_share=0.069]) |
| Ascent | 35.8 MB | [metric:sightlines_3d/build/ascent~2026-10-04T22:03:17#bytes=17583594] | [metric:sightlines_3d/build/ascent~2026-10-04T22:03:17#seconds_table=14.0] (22) | [metric:sightlines_3d/build/ascent~2026-10-04T22:03:17#n_cells=9516] | development | [metric:sightlines_3d/gate/ascent~2026-10-04T22:11:13#los3d_share=0.869] of 727 | [metric:sightlines_3d/gate/ascent#los2d_share=0.549] | [metric:sightlines_3d/gate/ascent#control_los3d_share=0.076] (2D [metric:sightlines_3d/gate/ascent#control_los2d_share=0.068]) |
| Haven | 30.6 MB | [metric:sightlines_3d/build/haven~2026-10-04T22:04:58#bytes=19421705] | [metric:sightlines_3d/build/haven~2026-10-04T22:04:58#seconds_table=12.2] (20) | [metric:sightlines_3d/build/haven~2026-10-04T22:04:58#n_cells=7979] | development | [metric:sightlines_3d/gate/haven~2026-10-04T22:11:37#los3d_share=0.888] of 466 | [metric:sightlines_3d/gate/haven#los2d_share=0.646] | [metric:sightlines_3d/gate/haven~2026-10-04T22:11:37#control_los3d_share=0.083] (2D [metric:sightlines_3d/gate/haven#control_los2d_share=0.069]) |
| Lotus | 25.2 MB | [metric:sightlines_3d/build/lotus~2026-10-04T22:08:16#bytes=10723383] | [metric:sightlines_3d/build/lotus~2026-10-04T22:08:16#seconds_table=14.1] (18) | [metric:sightlines_3d/build/lotus~2026-10-04T22:08:16#n_cells=9271] | development | [metric:sightlines_3d/gate/lotus~2026-10-04T22:11:42#los3d_share=0.909] of 596 | [metric:sightlines_3d/gate/lotus#los2d_share=0.750] | [metric:sightlines_3d/gate/lotus~2026-10-04T22:11:42#control_los3d_share=0.088] (2D [metric:sightlines_3d/gate/lotus#control_los2d_share=0.070]) |
| Split | 32.5 MB | [metric:sightlines_3d/build/split~2026-10-04T22:04:26#bytes=14255580] | [metric:sightlines_3d/build/split~2026-10-04T22:04:26#seconds_table=32.3] (40) | [metric:sightlines_3d/build/split~2026-10-04T22:04:26#n_cells=13893] | development | [metric:sightlines_3d/gate/split~2026-10-04T22:11:22#los3d_share=0.911] of 631 | [metric:sightlines_3d/gate/split#los2d_share=0.707] | [metric:sightlines_3d/gate/split#control_los3d_share=0.085] (2D [metric:sightlines_3d/gate/split#control_los2d_share=0.070]) |
| Summit | 46.8 MB | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#bytes=24365963] | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#seconds_table=9.3] (17) | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#n_cells=7037] | development | [metric:sightlines_3d/gate/summit~2026-10-04T22:11:48#los3d_share=0.897] of 465 | [metric:sightlines_3d/gate/summit~2026-10-04T22:11:48#los2d_share=0.767] (3D on the same 330: [metric:sightlines_3d/gate/summit~2026-10-04T22:11:48#los3d_share_on_2d_set=0.882]) | [metric:sightlines_3d/gate/summit~2026-10-04T22:11:48#control_los3d_share=0.071] (2D [metric:sightlines_3d/gate/summit~2026-10-04T22:11:48#control_los2d_share=0.052]) |
| Sunset | 32.8 MB | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#bytes=19731613] | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#seconds_table=9.3] (17) | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#n_cells=7598] | development | [metric:sightlines_3d/gate/sunset~2026-10-04T22:11:55#los3d_share=0.947] of 376 | [metric:sightlines_3d/gate/sunset#los2d_share=0.779] | [metric:sightlines_3d/gate/sunset#control_los3d_share=0.080] (2D [metric:sightlines_3d/gate/sunset#control_los2d_share=0.067]) |
| Bind | 27.9 MB | [metric:sightlines_3d/build/bind~2026-10-04T22:05:24#bytes=12575753] | [metric:sightlines_3d/build/bind~2026-10-04T22:05:24#seconds_table=10.6] (17) | [metric:sightlines_3d/build/bind~2026-10-04T22:05:24#n_cells=8287] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T22:12:10#los3d_share=0.926] of 1690 | no 2D table | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T22:12:10#control_los3d_share=0.113] |
| Breeze | 26.8 MB | [metric:sightlines_3d/build/breeze~2026-10-04T22:06:47#bytes=10973428] | [metric:sightlines_3d/build/breeze~2026-10-04T22:06:47#seconds_table=29.8] (36) | [metric:sightlines_3d/build/breeze~2026-10-04T22:06:47#n_cells=13436] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/breeze~2026-10-04T22:12:15#los3d_share=0.925] of 333 | no 2D table | [metric:sightlines_3d/gate_confirm/breeze#control_los3d_share=0.065] |
| Corrode | 44.1 MB | [metric:sightlines_3d/build/corrode~2026-10-04T22:10:45#bytes=22593046] | [metric:sightlines_3d/build/corrode~2026-10-04T22:10:45#seconds_table=8.7] (16) | [metric:sightlines_3d/build/corrode~2026-10-04T22:10:45#n_cells=7456] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/corrode~2026-10-04T22:12:23#los3d_share=0.905] of 1190 | no 2D table | [metric:sightlines_3d/gate_confirm/corrode~2026-10-04T22:12:23#control_los3d_share=0.077] |
| Fracture | 26.4 MB | [metric:sightlines_3d/build/fracture~2026-10-04T22:07:26#bytes=15549819] | [metric:sightlines_3d/build/fracture~2026-10-04T22:07:26#seconds_table=24.5] (31) | [metric:sightlines_3d/build/fracture~2026-10-04T22:07:26#n_cells=11455] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/fracture~2026-10-04T22:12:32#los3d_share=0.836] of 780 | no 2D table | [metric:sightlines_3d/gate_confirm/fracture~2026-10-04T22:12:32#control_los3d_share=0.067] |
| Icebox | 26.3 MB | [metric:sightlines_3d/build/icebox~2026-10-04T22:05:58#bytes=10731147] | [metric:sightlines_3d/build/icebox~2026-10-04T22:05:58#seconds_table=19.7] (25) | [metric:sightlines_3d/build/icebox~2026-10-04T22:05:58#n_cells=10606] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/icebox~2026-10-04T22:12:40#los3d_share=0.848] of 467 | no 2D table | [metric:sightlines_3d/gate_confirm/icebox#control_los3d_share=0.070] |
| Pearl | 32.6 MB | [metric:sightlines_3d/build/pearl~2026-10-04T22:07:51#bytes=13193692] | [metric:sightlines_3d/build/pearl~2026-10-04T22:07:51#seconds_table=8.9] (15) | [metric:sightlines_3d/build/pearl~2026-10-04T22:07:51#n_cells=7547] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/pearl~2026-10-04T22:12:50#los3d_share=0.918] of 1398 | no 2D table | [metric:sightlines_3d/gate_confirm/pearl#control_los3d_share=0.080] |

- The 13 tables total 218 MB in `<store>/sightlines/`, beside the 2D tables;
  each raw dump was deleted once its table existed. The walk graph's edges
  are cached in each table (3.3 MB uncompressed for all 13), well under the
  200 MB limit; the all-pairs path distances are not cached (N x N uint16,
  about 100-640 MB a map) and are rebuilt in memory when a table loads.
- 3D beats 2D on every map with development kills, so
  `sightlines.py choose` picks 3D for all 13 (`<store>/sightlines/choice.json`,
  ledger `sightlines/choice`); `sightlines.load` reads that choice and falls
  back to 2D where a map has no 3D table or a gate that does not favour it.
- The 3D control is higher than the 2D control on every development map
  (Ascent 0.076 against 0.068): 3D sees more of the other opponents too. Its
  hit-minus-control margin is still the wider one on every map.
- Abyss rests on one development match (86 gun kills), and nearly all of
  its positions stand over two or more floors
  ([metric:sightlines_3d/gate/abyss#multi_level_share=0.99]): the lowest-floor
  rule matters most there. Fracture has the most walk components
  (991, largest 40% of cells); its ziplines and one-way drops are not modelled.
- Instrument checks on confirmation kills are not development numbers: the
  confirmation set scored REACH1-REACH6 and is spent; no hypothesis was
  scored on these maps. New matches the player records are the next
  confirmation set.

## Body heights (0.3.0)

0.1.0 and 0.2.0 searched only `BasePlayerCharacter` and concluded the files
hold no eye height. Its parent `BasePawn` holds them. `sightlines-3d-0.3.0`
reads them from the game-data facts at import:

| Value | 0.2.0 placeholder | 0.3.0 | From |
|---|---|---|---|
| Eye above the floor | 160 cm | 175 cm | CapsuleHalfHeight + BaseEyeHeight [domain:game_data/character-eye-height] |
| Target on the victim | 120 cm (chest) | 98 cm (capsule centre) | CapsuleHalfHeight [domain:game_data/character-eye-height] |
| Free height a floor needs | 100 cm | 56 cm | 2 x CrouchedHalfHeight [domain:game_data/character-eye-height] |
| Largest floor step the walk graph joins | 120 cm | 115 cm | DefaultJumpTuning.MaxJumpHeight [domain:game_data/character-jump] |
| Walkable floor | 44.8 degrees | 44.8 degrees, still a placeholder | UE's engine default; no field [domain:game_data/character-jump] |

The eye omits StandingEyeOffset (-22 cm), whose use is unread; with it the
eye would stand at 153 cm. No field names a chest, so the target is the body's
centre. No crouched eye is used: under a ceiling lower than the eye, the eye
sits 5 cm below it. `rebuild` made each table from its 0.2.0 table's stored
blockers and callout volumes, which no height touches, so nothing was
extracted again; rebuilding Ascent at 0.2.0's heights this way reproduced
every stored array. One table at a time, one core, Below Normal, other work
on the CPU:

| Map | Cells (0.2.0) | Table MB | Build s, table (all) | Gate set | 3D line of sight (0.2.0) | Head | 3D control (0.2.0) |
|---|---|---|---|---|---|---|---|
| Abyss | [metric:sightlines_3d/build/abyss#n_cells=18067] (17846) | 26.7 | [metric:sightlines_3d/build/abyss#seconds_table=47.1] (52) | development | [metric:sightlines_3d/gate/abyss#los3d_share=0.895] of 86 (0.907) | [metric:sightlines_3d/gate/abyss#los3d_head_share=0.907] | [metric:sightlines_3d/gate/abyss#control_los3d_share=0.079] (0.079) |
| Ascent | [metric:sightlines_3d/build/ascent#n_cells=9650] (9516) | 17.6 | [metric:sightlines_3d/build/ascent#seconds_table=11.2] (14) | development | [metric:sightlines_3d/gate/ascent#los3d_share=0.858] of 727 (0.869) | [metric:sightlines_3d/gate/ascent#los3d_head_share=0.906] | [metric:sightlines_3d/gate/ascent#control_los3d_share=0.076] (0.076) |
| Haven | [metric:sightlines_3d/build/haven#n_cells=8287] (7979) | 19.5 | [metric:sightlines_3d/build/haven#seconds_table=10.7] (14) | development | [metric:sightlines_3d/gate/haven#los3d_share=0.873] of 466 (0.888) | [metric:sightlines_3d/gate/haven#los3d_head_share=0.921] | [metric:sightlines_3d/gate/haven#control_los3d_share=0.082] (0.083) |
| Lotus | [metric:sightlines_3d/build/lotus#n_cells=9398] (9271) | 10.8 | [metric:sightlines_3d/build/lotus#seconds_table=11.4] (13) | development | [metric:sightlines_3d/gate/lotus#los3d_share=0.906] of 596 (0.909) | [metric:sightlines_3d/gate/lotus#los3d_head_share=0.955] | [metric:sightlines_3d/gate/lotus#control_los3d_share=0.086] (0.088) |
| Split | [metric:sightlines_3d/build/split#n_cells=14143] (13893) | 14.3 | [metric:sightlines_3d/build/split#seconds_table=23.8] (27) | development | [metric:sightlines_3d/gate/split#los3d_share=0.905] of 631 (0.911) | [metric:sightlines_3d/gate/split#los3d_head_share=0.933] | [metric:sightlines_3d/gate/split#control_los3d_share=0.085] (0.085) |
| Summit | [metric:sightlines_3d/build/summit~2026-10-04T23:25:16#n_cells=7107] (7037) | 24.4 | [metric:sightlines_3d/build/summit~2026-10-04T23:25:16#seconds_table=7.7] (11) | development | [metric:sightlines_3d/gate/summit~2026-10-04T23:28:51#los3d_share=0.897] of 465 (0.897) | [metric:sightlines_3d/gate/summit~2026-10-04T23:28:51#los3d_head_share=0.897] | [metric:sightlines_3d/gate/summit~2026-10-04T23:28:51#control_los3d_share=0.071] (0.071) |
| Sunset | [metric:sightlines_3d/build/sunset#n_cells=7622] (7598) | 19.7 | [metric:sightlines_3d/build/sunset#seconds_table=7.4] (11) | development | [metric:sightlines_3d/gate/sunset#los3d_share=0.944] of 376 (0.947) | [metric:sightlines_3d/gate/sunset#los3d_head_share=0.965] | [metric:sightlines_3d/gate/sunset#control_los3d_share=0.080] (0.080) |
| Bind | [metric:sightlines_3d/build/bind~2026-10-04T23:26:25#n_cells=8570] (8287) | 12.6 | [metric:sightlines_3d/build/bind~2026-10-04T23:26:25#seconds_table=10.6] (14) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T23:29:11#los3d_share=0.921] of 1690 (0.926) | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T23:29:11#los3d_head_share=0.949] | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T23:29:11#control_los3d_share=0.112] (0.113) |
| Breeze | [metric:sightlines_3d/build/breeze#n_cells=13632] (13436) | 11.0 | [metric:sightlines_3d/build/breeze#seconds_table=27.6] (30) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/breeze#los3d_share=0.922] of 333 (0.925) | [metric:sightlines_3d/gate_confirm/breeze#los3d_head_share=0.940] | [metric:sightlines_3d/gate_confirm/breeze#control_los3d_share=0.065] (0.065) |
| Corrode | [metric:sightlines_3d/build/corrode#n_cells=7528] (7456) | 22.6 | [metric:sightlines_3d/build/corrode#seconds_table=8.8] (12) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/corrode#los3d_share=0.887] of 1190 (0.905) | [metric:sightlines_3d/gate_confirm/corrode#los3d_head_share=0.945] | [metric:sightlines_3d/gate_confirm/corrode#control_los3d_share=0.075] (0.077) |
| Fracture | [metric:sightlines_3d/build/fracture#n_cells=11738] (11455) | 15.6 | [metric:sightlines_3d/build/fracture#seconds_table=22.4] (26) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/fracture#los3d_share=0.823] of 780 (0.836) | [metric:sightlines_3d/gate_confirm/fracture#los3d_head_share=0.855] | [metric:sightlines_3d/gate_confirm/fracture#control_los3d_share=0.064] (0.067) |
| Icebox | [metric:sightlines_3d/build/icebox#n_cells=10785] (10606) | 10.8 | [metric:sightlines_3d/build/icebox#seconds_table=17.7] (21) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/icebox#los3d_share=0.839] of 467 (0.848) | [metric:sightlines_3d/gate_confirm/icebox#los3d_head_share=0.876] | [metric:sightlines_3d/gate_confirm/icebox#control_los3d_share=0.070] (0.070) |
| Pearl | [metric:sightlines_3d/build/pearl#n_cells=7607] (7547) | 13.2 | [metric:sightlines_3d/build/pearl#seconds_table=8.7] (12) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/pearl#los3d_share=0.907] of 1398 (0.918) | [metric:sightlines_3d/gate_confirm/pearl#los3d_head_share=0.933] | [metric:sightlines_3d/gate_confirm/pearl#control_los3d_share=0.080] (0.080) |

- Cells rise on every map (crouch room 56 cm admits floors under low
  ceilings), by 0.3% (Sunset) to 3.9% (Haven); tables grow by under 0.1 MB.
  The 13 0.3.0 tables total 218.9 MB beside the 0.2.0 tables' 218.4 MB, kept
  as evidence: 437 MB in all.
- 3D line of sight to the victim falls on 12 maps and holds on Summit: the
  lower target sits behind more cover. The largest fall is Corrode's 0.018
  (an instrument check); Ascent falls 0.011. Line of sight to the head rises
  on most maps with the higher eye. The control moves by 0.003 at most, so
  hit minus control stays 0.76-0.86.
- `sightlines.py choose` still picks 3D on all 13 maps; the 0.2.0 choice is
  kept as `<store>/sightlines/choice__sightlines-3d-0.2.0.json`.
- H1-H5 held. The REACH rerun at 0.3.0 is in
  [COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md) section 9.

## State-changing props (0.4.0)

The 0.3.0 class-name test missed two props named for their art: Summit's
DescentBox_v5_C, on the native AresDoor and tagged CollapsibleDoor, which
starts open and drops 300 cm over 1.75 s each round with a crush box; and
Bind's BP_Pot_1_C and BP_Pot_3_C, children of BP_Destructible_BASE_C, whose
ReceiveAnyDamage calls Break. `state_changing` now also walks each placed
class's parents through the class exports under the store's
`reference/game-files/<build>/props/`. Every blueprint class kept in the 13
0.3.0 tables has an export and a chain that reaches a native class;
`state-props` over those tables leaves out 6 placements on Summit (1878
triangles) and 4 on Bind (1800) and nothing on the other 11 maps. Only
Summit and Bind were rebuilt, from their 0.3.0 tables' blockers; the other
maps' 0.3.0 tables stand for 0.4.0 (`table_version`). The 0.3.0 tables stay.

| Map | Cells (0.3.0) | Table bytes (0.3.0) | Build s, table | Gate set | 3D line of sight (0.3.0) | 3D control (0.3.0) |
|---|---|---|---|---|---|---|
| Summit | [metric:sightlines_3d/build/summit~2026-10-05T00:20:51#n_cells=7061] (7107) | [metric:sightlines_3d/build/summit~2026-10-05T00:20:51#bytes=24378984] (24378780) | [metric:sightlines_3d/build/summit~2026-10-05T00:20:51#seconds_table=8.9] (7.7) | development | [metric:sightlines_3d/gate/summit~2026-10-05T00:21:28#los3d_share=0.955] of 465 (0.897); on the 2D set [metric:sightlines_3d/gate/summit~2026-10-05T00:21:28#los3d_share_on_2d_set=0.945] (0.882) | [metric:sightlines_3d/gate/summit~2026-10-05T00:21:28#control_los3d_share=0.078] (0.071) |
| Bind | [metric:sightlines_3d/build/bind~2026-10-05T00:21:07#n_cells=8563] (8570) | [metric:sightlines_3d/build/bind~2026-10-05T00:21:07#bytes=12601148] (12620121) | [metric:sightlines_3d/build/bind~2026-10-05T00:21:07#seconds_table=11.0] (10.6) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind~2026-10-05T00:21:44#los3d_share=0.921] of 1690 (0.921) | [metric:sightlines_3d/gate_confirm/bind~2026-10-05T00:21:44#control_los3d_share=0.112] (0.112) |

- Summit's line of sight rose 0.058 against a P3 prediction of under 0.01:
  the descent boxes stood across 27 of the 465 kills' sightlines. The
  control rose 0.007, so hit minus control widens to 0.88. Bind's pots stand
  across none of its 1690 kills.
- Cells fell by 46 on Summit and 7 on Bind.
- `sightlines.py choose` still picks 3D on all 13 maps; the 0.3.0 choice is
  kept as `<store>/sightlines/choice__sightlines-3d-0.3.0.json`.

## Wallbangs (wallbang-probe-0.1.0)

The player asked whether these tables account for wallbangs. They do not,
and the reach model hardly needs them to. `prototypes/wallbang_probe.py`
took every gun kill the gate calls blocked (killer eye to victim body
centre, exact positions, lowest floor) and asked why; predictions
`wallbang-probe-20261005` W1-W5 in the store's `notes/predictions.jsonl`.

**Answer.** Of [metric:wallbang_probe/classify/dev#gun_resolved=3281]
development gun kills, [metric:wallbang_probe/classify/dev#blocked=323]
have no line of sight. Only
[metric:wallbang_probe/classify/dev#primary_a=11] of them
([metric:wallbang_probe/classify/dev#primary_a_share=0.034]) are wallbangs
that nothing else explains:
[metric:wallbang_probe/classify/dev#a_share_of_gun_kills=0.0034] of all
gun kills. The confirmation history, an instrument check, agrees:
[metric:wallbang_probe/classify/confirm#primary_a=14] of
[metric:wallbang_probe/classify/confirm#blocked=622] blocked,
[metric:wallbang_probe/classify/confirm#a_share_of_gun_kills=0.0024] of
gun kills. The blocked kills are near misses, not hidden duels.

**The game's penetration data.** WallPenGlobals maps each physical surface
to a penetration class with an EnergyReductionMultiplier
[domain:game_data/wall-penetration-surfaces]; each gun's projectile scales
its budget by a stopping and a power multiplier
[domain:game_data/wall-penetration-weapons]. A crossing's surface comes from
the hit triangle's collision section, its material's PhysMaterial and that
material's SurfaceType; every mesh a stored line crosses, with its
material chain, is exported to the store's
`reference/game-files/<build>/wallpen-meshes/`. The surface stays
unread on [metric:wallbang_probe/classify/dev#unread_crossing_share=0.0098]
of crossings. No export gives the base distance the multipliers scale, so
`D0` (a Medium gun through a surface of multiplier 1) is a placeholder,
100 cm, swept below.

**Classes**, by fixed precedence, each also computed alone: (e) not a gun,
by Riot's damage type or a damage item outside the gun list, excluded
first; (b) posture or height: another killer eye height (crouch, standing
with offset, jump apex) to another victim target (crouched, head,
mid-jump), or any standable floor pair; (c) position error: killer and
victim each moved up to 42 cm, the capsule radius
[domain:game_data/character-eye-height], at the recorded floor height, a
move kept only when the Pawn set leaves it open; (a) wallbang at D0; (d) the
table, by eye on renders; (f) the rest. Excluded (e) on the development
set: [metric:wallbang_probe/classify/dev#e.Ability=80] ability,
[metric:wallbang_probe/classify/dev#e.Bomb=12] spike,
[metric:wallbang_probe/classify/dev#e.Melee=2] knife and
[metric:wallbang_probe/classify/dev#e.weapon_item_not_a_gun=66] Weapon kills
whose item is no gun.

| Map | Set | Gun kills | Blocked | (b) | (c) | (a) | (d) | (f) | (a) alone | Control (a) alone |
|---|---|---|---|---|---|---|---|---|---|---|
| Abyss | dev | [metric:wallbang_probe/classify/abyss#gun_resolved=82] | [metric:wallbang_probe/classify/abyss#blocked=9] | [metric:wallbang_probe/classify/abyss#primary_b=9] | [metric:wallbang_probe/classify/abyss#primary_c=0] | [metric:wallbang_probe/classify/abyss#primary_a=0] | [metric:wallbang_probe/classify/abyss#primary_d=0] | [metric:wallbang_probe/classify/abyss#primary_f=0] | [metric:wallbang_probe/classify/abyss#alone_a=8] | [metric:wallbang_probe/classify/abyss#control_alone_a=10] of [metric:wallbang_probe/classify/abyss#control_n=178] |
| Ascent | dev | [metric:wallbang_probe/classify/ascent#gun_resolved=711] | [metric:wallbang_probe/classify/ascent#blocked=101] | [metric:wallbang_probe/classify/ascent#primary_b=65] | [metric:wallbang_probe/classify/ascent#primary_c=28] | [metric:wallbang_probe/classify/ascent#primary_a=4] | [metric:wallbang_probe/classify/ascent#primary_d=0] | [metric:wallbang_probe/classify/ascent#primary_f=4] | [metric:wallbang_probe/classify/ascent#alone_a=92] | [metric:wallbang_probe/classify/ascent#control_alone_a=145] of [metric:wallbang_probe/classify/ascent#control_n=1516] |
| Haven | dev | [metric:wallbang_probe/classify/haven#gun_resolved=458] | [metric:wallbang_probe/classify/haven#blocked=58] | [metric:wallbang_probe/classify/haven#primary_b=34] | [metric:wallbang_probe/classify/haven#primary_c=21] | [metric:wallbang_probe/classify/haven#primary_a=1] | [metric:wallbang_probe/classify/haven#primary_d=0] | [metric:wallbang_probe/classify/haven#primary_f=2] | [metric:wallbang_probe/classify/haven#alone_a=52] | [metric:wallbang_probe/classify/haven#control_alone_a=119] of [metric:wallbang_probe/classify/haven#control_n=985] |
| Lotus | dev | [metric:wallbang_probe/classify/lotus#gun_resolved=584] | [metric:wallbang_probe/classify/lotus#blocked=54] | [metric:wallbang_probe/classify/lotus#primary_b=37] | [metric:wallbang_probe/classify/lotus#primary_c=14] | [metric:wallbang_probe/classify/lotus#primary_a=2] | [metric:wallbang_probe/classify/lotus#primary_d=0] | [metric:wallbang_probe/classify/lotus#primary_f=1] | [metric:wallbang_probe/classify/lotus#alone_a=53] | [metric:wallbang_probe/classify/lotus#control_alone_a=62] of [metric:wallbang_probe/classify/lotus#control_n=1225] |
| Split | dev | [metric:wallbang_probe/classify/split#gun_resolved=623] | [metric:wallbang_probe/classify/split#blocked=59] | [metric:wallbang_probe/classify/split#primary_b=34] | [metric:wallbang_probe/classify/split#primary_c=17] | [metric:wallbang_probe/classify/split#primary_a=2] | [metric:wallbang_probe/classify/split#primary_d=4] | [metric:wallbang_probe/classify/split#primary_f=2] | [metric:wallbang_probe/classify/split#alone_a=49] | [metric:wallbang_probe/classify/split#control_alone_a=65] of [metric:wallbang_probe/classify/split#control_n=1326] |
| Summit | dev | [metric:wallbang_probe/classify/summit#gun_resolved=465] | [metric:wallbang_probe/classify/summit#blocked=21] | [metric:wallbang_probe/classify/summit#primary_b=4] | [metric:wallbang_probe/classify/summit#primary_c=16] | [metric:wallbang_probe/classify/summit#primary_a=1] | [metric:wallbang_probe/classify/summit#primary_d=0] | [metric:wallbang_probe/classify/summit#primary_f=0] | [metric:wallbang_probe/classify/summit#alone_a=20] | [metric:wallbang_probe/classify/summit#control_alone_a=61] of [metric:wallbang_probe/classify/summit#control_n=991] |
| Sunset | dev | [metric:wallbang_probe/classify/sunset#gun_resolved=358] | [metric:wallbang_probe/classify/sunset#blocked=21] | [metric:wallbang_probe/classify/sunset#primary_b=10] | [metric:wallbang_probe/classify/sunset#primary_c=10] | [metric:wallbang_probe/classify/sunset#primary_a=1] | [metric:wallbang_probe/classify/sunset#primary_d=0] | [metric:wallbang_probe/classify/sunset#primary_f=0] | [metric:wallbang_probe/classify/sunset#alone_a=19] | [metric:wallbang_probe/classify/sunset#control_alone_a=25] of [metric:wallbang_probe/classify/sunset#control_n=757] |
| Bind | confirm | [metric:wallbang_probe/classify/bind#gun_resolved=1676] | [metric:wallbang_probe/classify/bind#blocked=133] | [metric:wallbang_probe/classify/bind#primary_b=89] | [metric:wallbang_probe/classify/bind#primary_c=37] | [metric:wallbang_probe/classify/bind#primary_a=4] | [metric:wallbang_probe/classify/bind#primary_d=0] | [metric:wallbang_probe/classify/bind#primary_f=3] | [metric:wallbang_probe/classify/bind#alone_a=124] | [metric:wallbang_probe/classify/bind#control_alone_a=262] of [metric:wallbang_probe/classify/bind#control_n=2000] |
| Breeze | confirm | [metric:wallbang_probe/classify/breeze#gun_resolved=325] | [metric:wallbang_probe/classify/breeze#blocked=25] | [metric:wallbang_probe/classify/breeze#primary_b=15] | [metric:wallbang_probe/classify/breeze#primary_c=7] | [metric:wallbang_probe/classify/breeze#primary_a=1] | [metric:wallbang_probe/classify/breeze#primary_d=0] | [metric:wallbang_probe/classify/breeze#primary_f=2] | [metric:wallbang_probe/classify/breeze#alone_a=19] | [metric:wallbang_probe/classify/breeze#control_alone_a=46] of [metric:wallbang_probe/classify/breeze#control_n=696] |
| Corrode | confirm | [metric:wallbang_probe/classify/corrode#gun_resolved=1170] | [metric:wallbang_probe/classify/corrode#blocked=135] | [metric:wallbang_probe/classify/corrode#primary_b=96] | [metric:wallbang_probe/classify/corrode#primary_c=36] | [metric:wallbang_probe/classify/corrode#primary_a=1] | [metric:wallbang_probe/classify/corrode#primary_d=0] | [metric:wallbang_probe/classify/corrode#primary_f=2] | [metric:wallbang_probe/classify/corrode#alone_a=125] | [metric:wallbang_probe/classify/corrode#control_alone_a=169] of [metric:wallbang_probe/classify/corrode#control_n=2000] |
| Fracture | confirm | [metric:wallbang_probe/classify/fracture#gun_resolved=758] | [metric:wallbang_probe/classify/fracture#blocked=132] | [metric:wallbang_probe/classify/fracture#primary_b=106] | [metric:wallbang_probe/classify/fracture#primary_c=17] | [metric:wallbang_probe/classify/fracture#primary_a=2] | [metric:wallbang_probe/classify/fracture#primary_d=0] | [metric:wallbang_probe/classify/fracture#primary_f=7] | [metric:wallbang_probe/classify/fracture#alone_a=64] | [metric:wallbang_probe/classify/fracture#control_alone_a=91] of [metric:wallbang_probe/classify/fracture#control_n=1671] |
| Icebox | confirm | [metric:wallbang_probe/classify/icebox#gun_resolved=459] | [metric:wallbang_probe/classify/icebox#blocked=74] | [metric:wallbang_probe/classify/icebox#primary_b=55] | [metric:wallbang_probe/classify/icebox#primary_c=10] | [metric:wallbang_probe/classify/icebox#primary_a=4] | [metric:wallbang_probe/classify/icebox#primary_d=0] | [metric:wallbang_probe/classify/icebox#primary_f=5] | [metric:wallbang_probe/classify/icebox#alone_a=52] | [metric:wallbang_probe/classify/icebox#control_alone_a=43] of [metric:wallbang_probe/classify/icebox#control_n=990] |
| Pearl | confirm | [metric:wallbang_probe/classify/pearl#gun_resolved=1362] | [metric:wallbang_probe/classify/pearl#blocked=123] | [metric:wallbang_probe/classify/pearl#primary_b=65] | [metric:wallbang_probe/classify/pearl#primary_c=42] | [metric:wallbang_probe/classify/pearl#primary_a=2] | [metric:wallbang_probe/classify/pearl#primary_d=0] | [metric:wallbang_probe/classify/pearl#primary_f=14] | [metric:wallbang_probe/classify/pearl#alone_a=95] | [metric:wallbang_probe/classify/pearl#control_alone_a=144] of [metric:wallbang_probe/classify/pearl#control_n=2000] |

- On the development set (b) explains
  [metric:wallbang_probe/classify/dev#primary_b_share=0.598], (c)
  [metric:wallbang_probe/classify/dev#primary_c_share=0.328], (d)
  [metric:wallbang_probe/classify/dev#primary_d=4] kills and (f)
  [metric:wallbang_probe/classify/dev#primary_f=9]. Alone, the wallbang test
  passes on [metric:wallbang_probe/classify/dev#alone_a_share=0.907] of
  blocked kills against
  [metric:wallbang_probe/classify/dev#control_alone_a_share=0.070] of the
  blocked control pairs (the killer against every other living opponent):
  the occluder between a killer and his victim is thin, because the victim
  was nearly visible. Among the kills and controls that posture and position
  do not explain, it passes on
  [metric:wallbang_probe/classify/dev#residual_a_share=0.458] against
  [metric:wallbang_probe/classify/dev#control_residual_a_share=0.038], so
  the eleven are wallbangs more than chance thin walls (fewer than one
  expected by chance).
- The placeholder moves the count, not the conclusion. Wallbangs as primary
  class at D0 25, 50, 100, 200 and 400 cm:
  [metric:wallbang_probe/classify/dev#d25.a_primary=2],
  [metric:wallbang_probe/classify/dev#d50.a_primary=3],
  [metric:wallbang_probe/classify/dev#d100.a_primary=11],
  [metric:wallbang_probe/classify/dev#d200.a_primary=17] and
  [metric:wallbang_probe/classify/dev#d400.a_primary=20] of 323; control
  pairs [metric:wallbang_probe/classify/dev#d25.control_a_primary=24],
  [metric:wallbang_probe/classify/dev#d50.control_a_primary=73],
  [metric:wallbang_probe/classify/dev#d100.control_a_primary=242],
  [metric:wallbang_probe/classify/dev#d200.control_a_primary=630] and
  [metric:wallbang_probe/classify/dev#d400.control_a_primary=1444] of
  [metric:wallbang_probe/classify/dev#control_n=6978].
- Weapons by wallbang share of their gun kills (development, D0 100 cm):
  Bandit [metric:wallbang_probe/classify/dev#weapon.Bandit.a_primary=3] of
  [metric:wallbang_probe/classify/dev#weapon.Bandit.gun_kills=93], Odin
  [metric:wallbang_probe/classify/dev#weapon.Odin.a_primary=1] of
  [metric:wallbang_probe/classify/dev#weapon.Odin.gun_kills=45], Classic
  [metric:wallbang_probe/classify/dev#weapon.Classic.a_primary=1] of
  [metric:wallbang_probe/classify/dev#weapon.Classic.gun_kills=148], Vandal
  [metric:wallbang_probe/classify/dev#weapon.Vandal.a_primary=5] of
  [metric:wallbang_probe/classify/dev#weapon.Vandal.gun_kills=1596], Phantom
  [metric:wallbang_probe/classify/dev#weapon.Phantom.a_primary=1] of
  [metric:wallbang_probe/classify/dev#weapon.Phantom.gun_kills=608]; every
  other gun none. Confirmation: Odin
  [metric:wallbang_probe/classify/confirm#weapon.Odin.a_primary=1] of
  [metric:wallbang_probe/classify/confirm#weapon.Odin.gun_kills=79], Guardian
  [metric:wallbang_probe/classify/confirm#weapon.Guardian.a_primary=1] of
  [metric:wallbang_probe/classify/confirm#weapon.Guardian.gun_kills=135],
  Vandal [metric:wallbang_probe/classify/confirm#weapon.Vandal.a_primary=11]
  of [metric:wallbang_probe/classify/confirm#weapon.Vandal.gun_kills=2909],
  Ghost [metric:wallbang_probe/classify/confirm#weapon.Ghost.a_primary=1] of
  [metric:wallbang_probe/classify/confirm#weapon.Ghost.gun_kills=329]. Counts
  this small rank nothing.
- Twelve renders (`render`: plan and section of the line over the Weapon
  set) cover every development kill left after (b), (c) and (a), and one
  (a). Four Split kills sit beside the A-tower ascender rope, the rope side
  on the lower floor and the other on the upper; raising the rope side's
  feet partway between the floors clears every line: a player on the rope,
  a height the floor model cannot hold. They are (d). The rest are near
  misses the move does not reach: a victim recorded inside a cover box or
  wall face (three), a line clipping a wall corner (two), a long line
  through a crate stack, a line through the Ascent A-site scaffold from
  above, a B-main wall bearing a metal cover that may be a window the table
  keeps closed, and a Split B-tower ledge. None shows a missing or extra
  occluder that a rebuild would fix.

**Recommendation: no penetrable layer.** Wallbangs that nothing else
explains are a third of a percent of gun kills. Post hoc, scoring "line of
sight or penetrable" lifts the kills' share from
[metric:wallbang_probe/classify/dev#sep.kill_los=0.902] to
[metric:wallbang_probe/classify/dev#sep.kill_los_or_pen=0.991] and the
controls' from [metric:wallbang_probe/classify/dev#sep.control_los=0.082] to
[metric:wallbang_probe/classify/dev#sep.control_los_or_pen=0.146]: the
separation gains [metric:wallbang_probe/classify/dev#sep.gain=0.025] on the
development set and [metric:wallbang_probe/classify/confirm#sep.gain=0.009]
on the confirmation history
([metric:wallbang_probe/classify/confirm#sep.kill_los=0.892] to
[metric:wallbang_probe/classify/confirm#sep.kill_los_or_pen=0.975];
controls [metric:wallbang_probe/classify/confirm#sep.control_los=0.085] to
[metric:wallbang_probe/classify/confirm#sep.control_los_or_pen=0.159]),
and it comes from thin cover at near misses, which posture and position
already explain. The layer would cost, on Ascent
([metric:wallbang_probe/cost/ascent#cells=9650] cells,
[metric:wallbang_probe/cost/ascent#pairs=46556425] pairs,
[metric:wallbang_probe/cost/ascent#blocked_share=0.808] blocked; a seeded
sample of [metric:wallbang_probe/cost/ascent#sample_pairs=199980] pairs,
one core, Below Normal, other work on the CPU):

- build: [metric:wallbang_probe/cost/ascent#layer_build_seconds=1368] s
  against [metric:wallbang_probe/cost/ascent#table_build_seconds_same_rate=39]
  s for the visibility table at the same rate
  ([metric:wallbang_probe/cost/ascent#layer_over_table=35] times). On the
  sample the crossing march took
  [metric:wallbang_probe/cost/ascent#seconds_crossings_sample=2.4] s and the
  surface lookup [metric:wallbang_probe/cost/ascent#seconds_surfaces_sample=3.4]
  s, most of it reading mesh exports, which a per-triangle surface array
  removes; [metric:wallbang_probe/cost/ascent#crossings_per_blocked_pair=9.2]
  crossings per blocked pair.
- bytes: a 2-bit tier mask (penetrable by Low, Medium, High)
  [metric:wallbang_probe/cost/ascent#bytes_tier_mask_2bit=11639106], twice
  the visibility bits'
  [metric:wallbang_probe/cost/ascent#vis_bits_bytes=5819554]; one byte of
  effective thickness per pair
  [metric:wallbang_probe/cost/ascent#bytes_uint8_cost=46556425], about
  [metric:wallbang_probe/cost/ascent#bytes_uint8_cost_zlib_estimate=30321972]
  compressed.
- exports: the map's [metric:wallbang_probe/cost/ascent#weapon_meshes=893]
  Weapon-set meshes with their materials, of which
  [metric:wallbang_probe/cost/ascent#weapon_meshes_exported=342] are
  exported now.

If coaching wants "this wall is penetrable to your gun", store one surface
byte per Weapon triangle with each table and test the few lines a question
asks on demand (`classify_line`). The larger gaps this probe found are in the
floor model: Split's ropes, and players at heights between floors.

**Predictions.** W1 failed: wallbangs are
[metric:wallbang_probe/classify/dev#primary_a_share=0.034] of blocked kills,
not 10-30%. W2 held: posture or height dominates. W3 held: the wallbang test
alone passes [metric:wallbang_probe/classify/dev#a_enrichment=13.0] times as
often on blocked kills as on blocked controls. W4 held:
[metric:wallbang_probe/classify/dev#primary_f_share=0.028] unexplained. W5
failed: the Bandit, a Medium gun, leads on
[metric:wallbang_probe/classify/dev#weapon.Bandit.a_primary=3] kills. Three
changes followed the first results and renders, before the recorded run:
solid path length pairs crossings along the whole ray, not within one
placement, and an unpaired crossing adds nothing (the first rule read
single-sided floors as slabs metres thick); a moved point keeps the
recorded floor height; and (d) holds the four rope kills.

**Not done.** The base stopping distance and High's multiplier stay
placeholders; component-level material overrides were not read; the
confirmation set's (f) kills were not rendered. The killfeed draws a
wallbang mark on the killer's plate (`reticle/killfeed.py` sees past it but
stores nothing): that independent witness on the captured matches would
replace the D0 placeholder with a count, and is the next step if wallbangs
matter.

## Blockers and questions for the player

- **Body heights come from the files.** That 0.1.0 and 0.2.0 found no eye
  height was wrong: `BasePawn`, the parent of `BasePlayerCharacter`, holds the
  eye, capsule and crouch fields [domain:game_data/character-eye-height] and
  the jump tuning [domain:game_data/character-jump]. See "Body heights
  (0.3.0)". The walkable angle stays UE's default, a placeholder: no class
  in the chain serialises it and the native parent's defaults are in no
  export. Nothing about body heights is left to ask the player.
- **Props once of uncertain state: the files answer.** The 0.3.0 tables
  keep five prop classes as static. Their class exports (build 13.06,
  `game-extract export` with `--script`, under the store's
  `reference/game-files/<build>/props/` with a manifest) settle each:
  - Corrode's `RadianiteSaltCrystal_C` (a `StaticMeshActor`) and
    `InstancedRadianiteSaltCrystal_C` (an `Actor` on a Static scene root)
    neither move nor break. They carry no destructible, movable, physics or
    damage component and no movement curve; their one component,
    `ImpactEffectsOverrideComponent`, swaps the hit effect
    (`FXC_RadianiteSaltCrystalImpact`). Static is right.
  - Summit's `DescentBox_v5_C` moves. It derives from the native `AresDoor`,
    is tagged `CollapsibleDoor`, starts open, drops by `FallingOffset`
    (Z -300 cm) along the curve `DescentBoxMovementNormalized` over
    `DoorCloseTime` 1.75 s and resets each round; it carries a crush box, a
    `DamageableComponent` and a `GameObjectDestructionComponent`.
  - Bind's `BP_Pot_1_C` and `BP_Pot_3_C` break. Both derive from
    `BP_Destructible_BASE_C` (exported beside them), whose `ReceiveAnyDamage`
    calls `Break`: the graph hides the actor and plays a break sound. It
    changes no collision; whether a hidden pot still blocks is native code,
    unread. The unbroken mesh uses `BlockAll`.
  - **Follow-up for the tables (not rebuilt):** leave out `DescentBox_v5_C`
    and the subclasses of `BP_Destructible_BASE_C`. `STATE_CHANGING_CLASS`
    matches class names, so it misses a door named `DescentBox` and a
    destructible's subclasses; test the class chain instead, then rebuild
    Summit and Bind.
- **Doors and dynamic objects**: their state per round is in no Riot record.
- **Wallbangs**: see "Wallbangs (wallbang-probe-0.1.0)"; the base stopping
  distance the game's multipliers scale is native and in no export.
- **Simple or complex traces**: which the game's weapon trace uses is not in
  the files; the sensitivity above is small.
- **Multi-level choice**: see above.
- **Patches**: geometry is keyed by build; a new patch reruns the dump.

## Reproduce

```
game-extract meshes "ShooterGame/Content/Maps/Ascent/Ascent*.umap" --out <dump>
game-extract export "ShooterGame/Content/Maps/Ascent/Ascent.umap" --out <json>
game-extract export "ShooterGame/Config/DefaultEngine.ini" --out <ini>
game-extract export --paths <prop list> --out <store>/reference/game-files/<build>/props --manifest <props>/manifest.jsonl --script
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py build --dump <dump> --ini <ini>\...\DefaultEngine.ini --persistent <json>\...\Ascent.json --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py gate --map ascent --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py gate --map pearl --set confirm --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py rebuild --map ascent --source <store>\sightlines\ascent__sightlines-3d-0.2.0.npz --record
.\.venv\Scripts\python.exe prototypes\sightlines.py choose --record
.\.venv\Scripts\python.exe prototypes\wallbang_probe.py rays --map ascent [--set confirm]
.\.venv\Scripts\python.exe prototypes\wallbang_probe.py meshes --export
.\.venv\Scripts\python.exe prototypes\wallbang_probe.py classify --record
.\.venv\Scripts\python.exe prototypes\wallbang_probe.py render --map split --kill 19 --out <png>
.\.venv\Scripts\python.exe prototypes\wallbang_probe.py cost --map ascent --pairs 200000 --record
```

Each map uses its game folder (`sightlines_3d.CODENAMES`: Split is Bonsai,
Haven Triad, Bind Duality, Icebox Port, Breeze Foxtrot, Fracture Canyon,
Pearl Pitt, Lotus Jam, Sunset Juliett, Abyss Infinity, Summit Plummet,
Corrode Rook). Check that no VALORANT process runs before each extraction.

The caster is `embreex` 4.4.0 with `trimesh` 5.1.1, installed into the venv
for this probe.
