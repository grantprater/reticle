# 3D sightlines from the game files: feasibility probe

Status: findings, recorded 2026-10-04. Code: `prototypes/sightlines_3d.py`
(the probe ran `sightlines-3d-0.1.0` on Ascent and Split; `sightlines-3d-0.2.0`
built all 13 maps of the player's history, see "Every map in the player's
history"; both used placeholder body heights; `sightlines-3d-0.3.0` rebuilt
the 13 with the game's, see "Body heights (0.3.0)"); predictions
`sightline-3d-20261004` S1-S5 and `sightline-3d-heights-20261004` H1-H5 in
the store's `notes/predictions.jsonl`. The figures in the sections before
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
| Summit | 46.8 MB | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#bytes=24365963] | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#seconds_table=9.3] (17) | [metric:sightlines_3d/build/summit~2026-10-04T22:10:20#n_cells=7037] | development | [metric:sightlines_3d/gate/summit#los3d_share=0.897] of 465 | [metric:sightlines_3d/gate/summit#los2d_share=0.767] (3D on the same 330: [metric:sightlines_3d/gate/summit#los3d_share_on_2d_set=0.882]) | [metric:sightlines_3d/gate/summit#control_los3d_share=0.071] (2D [metric:sightlines_3d/gate/summit#control_los2d_share=0.052]) |
| Sunset | 32.8 MB | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#bytes=19731613] | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#seconds_table=9.3] (17) | [metric:sightlines_3d/build/sunset~2026-10-04T22:08:42#n_cells=7598] | development | [metric:sightlines_3d/gate/sunset~2026-10-04T22:11:55#los3d_share=0.947] of 376 | [metric:sightlines_3d/gate/sunset#los2d_share=0.779] | [metric:sightlines_3d/gate/sunset#control_los3d_share=0.080] (2D [metric:sightlines_3d/gate/sunset#control_los2d_share=0.067]) |
| Bind | 27.9 MB | [metric:sightlines_3d/build/bind~2026-10-04T22:05:24#bytes=12575753] | [metric:sightlines_3d/build/bind#seconds_table=10.6] (17) | [metric:sightlines_3d/build/bind~2026-10-04T22:05:24#n_cells=8287] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T22:12:10#los3d_share=0.926] of 1690 | no 2D table | [metric:sightlines_3d/gate_confirm/bind~2026-10-04T22:12:10#control_los3d_share=0.113] |
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
| Summit | [metric:sightlines_3d/build/summit#n_cells=7107] (7037) | 24.4 | [metric:sightlines_3d/build/summit#seconds_table=7.7] (11) | development | [metric:sightlines_3d/gate/summit#los3d_share=0.897] of 465 (0.897) | [metric:sightlines_3d/gate/summit#los3d_head_share=0.897] | [metric:sightlines_3d/gate/summit#control_los3d_share=0.071] (0.071) |
| Sunset | [metric:sightlines_3d/build/sunset#n_cells=7622] (7598) | 19.7 | [metric:sightlines_3d/build/sunset#seconds_table=7.4] (11) | development | [metric:sightlines_3d/gate/sunset#los3d_share=0.944] of 376 (0.947) | [metric:sightlines_3d/gate/sunset#los3d_head_share=0.965] | [metric:sightlines_3d/gate/sunset#control_los3d_share=0.080] (0.080) |
| Bind | [metric:sightlines_3d/build/bind#n_cells=8570] (8287) | 12.6 | [metric:sightlines_3d/build/bind#seconds_table=10.6] (14) | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind#los3d_share=0.921] of 1690 (0.926) | [metric:sightlines_3d/gate_confirm/bind#los3d_head_share=0.949] | [metric:sightlines_3d/gate_confirm/bind#control_los3d_share=0.112] (0.113) |
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

## Blockers and questions for the player

- **Body heights come from the files.** That 0.1.0 and 0.2.0 found no eye
  height was wrong: `BasePawn`, the parent of `BasePlayerCharacter`, holds the
  eye, capsule and crouch fields [domain:game_data/character-eye-height] and
  the jump tuning [domain:game_data/character-jump]. See "Body heights
  (0.3.0)". The walkable angle stays UE's default, a placeholder: no class
  in the chain serialises it and the native parent's defaults are in no
  export. Nothing about body heights is left to ask the player.
- **Props of uncertain state** kept as static: Corrode's
  `RadianiteSaltCrystal_C` and `InstancedRadianiteSaltCrystal_C`, Summit's
  `DescentBox_v5_C`, Bind's `BP_Pot_1_C` and `BP_Pot_3_C`. Their class
  exports were not read: the extractor stays off while a Riot process runs,
  and Vanguard's tray (`vgtray.exe`) ran throughout. The game's index names
  hint: `DescentBox_v5` sits in `Plummet/Blueprints/DroppableDoor/` beside a
  movement curve (`DescentBoxMovementNormalized`) and a crush damage type
  (`DmgType_DescentBox_Crush`), so it likely moves; `RadianiteSaltCrystal`
  has an impact effect (`FXC_RadianiteSaltCrystalImpact`); `BP_Pot_1` sits
  under `VFX/Blueprint/`. Exporting the three classes and reading their
  components (a destructible or movement component) answers it from the
  files; until then the question stands: do any of them break or move in a
  round?
- **Doors and dynamic objects**: their state per round is in no Riot record.
- **Wallbangs**: penetration needs per-surface data not read here.
- **Simple or complex traces**: which the game's weapon trace uses is not in
  the files; the sensitivity above is small.
- **Multi-level choice**: see above.
- **Patches**: geometry is keyed by build; a new patch reruns the dump.

## Reproduce

```
game-extract meshes "ShooterGame/Content/Maps/Ascent/Ascent*.umap" --out <dump>
game-extract export "ShooterGame/Content/Maps/Ascent/Ascent.umap" --out <json>
game-extract export "ShooterGame/Config/DefaultEngine.ini" --out <ini>
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py build --dump <dump> --ini <ini>\...\DefaultEngine.ini --persistent <json>\...\Ascent.json --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py gate --map ascent --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py gate --map pearl --set confirm --record
.\.venv\Scripts\python.exe prototypes\sightlines_3d.py rebuild --map ascent --source <store>\sightlines\ascent__sightlines-3d-0.2.0.npz --record
.\.venv\Scripts\python.exe prototypes\sightlines.py choose --record
```

Each map uses its game folder (`sightlines_3d.CODENAMES`: Split is Bonsai,
Haven Triad, Bind Duality, Icebox Port, Breeze Foxtrot, Fracture Canyon,
Pearl Pitt, Lotus Jam, Sunset Juliett, Abyss Infinity, Summit Plummet,
Corrode Rook). Check that no VALORANT process runs before each extraction.

The caster is `embreex` 4.4.0 with `trimesh` 5.1.1, installed into the venv
for this probe.
