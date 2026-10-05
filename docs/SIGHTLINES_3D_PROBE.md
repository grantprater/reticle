# 3D sightlines from the game files: feasibility probe

Status: findings, recorded 2026-10-04. Code: `prototypes/sightlines_3d.py`
(the probe ran `sightlines-3d-0.1.0` on Ascent and Split; `sightlines-3d-0.2.0`
built all 13 maps of the player's history, see "Every map in the player's
history"); predictions `sightline-3d-20261004` S1-S5 in the store's
`notes/predictions.jsonl`. It serves the coaching question of
[COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md): whether a teammate
can swing, trade or support from where he stands.

## Answer

Yes. The extracted collision gives a true 3D sightline map of Ascent on one
core in seconds, and it agrees with the kills far better than the minimap.

- The extractor dumps every placed mesh of Ascent's 43 sublevels in 6 s;
  the build keeps [metric:sightlines_3d/build/ascent#placements_kept=6220]
  placements and [metric:sightlines_3d/build/ascent#n_weapon_tris=1932946]
  triangles that block the Weapon trace channel.
- A 1 m standing grid holds [metric:sightlines_3d/build/ascent#n_cells=9516]
  cells; all [metric:sightlines_3d/build/ascent#pairs=45272370] cell pairs cast
  in [metric:sightlines_3d/build/ascent~2026-10-04T20:46:21#seconds_table=10.4] s and the whole
  compact file is [metric:sightlines_3d/build/ascent~2026-10-04T20:46:21#bytes=17481575] bytes.
- Riot positions are UE world (X, Y) unchanged:
  [metric:sightlines_3d/gate/ascent#frame_identity_on_floor=0.993] of them
  stand on a floor of the geometry, against
  [metric:sightlines_3d/gate/ascent#frame_swap_on_floor=0.008] with the axes
  swapped.
- [metric:sightlines_3d/gate/ascent#los3d_share=0.869] of the development
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
[metric:sightlines_3d/gate/ascent#multi_level_share=0.153] of positions
(Split [metric:sightlines_3d/gate/split#multi_level_share=0.475]), most in
the A site, A link, B site, back B and market callouts, where tall callout
volumes hold roofs and canopies above the floor. The pre-registered rule takes the lowest
floor. Two post hoc rules bound the choice: the floor joined to the largest
walkable component gives
[metric:sightlines_3d/gate/ascent#los3d_component_floor_share=0.876], and the
best of every floor pair gives
[metric:sightlines_3d/gate/ascent#los3d_any_pair_share=0.898]. A movement
model, or replay heights scored as truth, settles it.

## The disagreements

[metric:sightlines_3d/gate/ascent#d3clear_d2blocked=254] kills are clear in
3D and blocked on the minimap;
[metric:sightlines_3d/gate/ascent#d3blocked_d2clear=21] go the other way.
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
  under a placeholder eye height, the lowest-floor rule, or a wallbang.

Post hoc: tracing render triangles for every mesh moves 3D line of sight to
87.2%; aiming at the victim's head instead of the chest gives
[metric:sightlines_3d/gate/ascent#los3d_head_share=0.898]. Split, built as a
second map and not pre-registered, gives
[metric:sightlines_3d/gate/split#los3d_share=0.911] in 3D against
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
| Abyss | 46.7 MB | [metric:sightlines_3d/build/abyss#bytes=26679301] | [metric:sightlines_3d/build/abyss#seconds_table=50.6] (60) | [metric:sightlines_3d/build/abyss#n_cells=17846] | development | [metric:sightlines_3d/gate/abyss#los3d_share=0.907] of 86 | [metric:sightlines_3d/gate/abyss#los2d_share=0.651] | [metric:sightlines_3d/gate/abyss#control_los3d_share=0.079] (2D [metric:sightlines_3d/gate/abyss#control_los2d_share=0.069]) |
| Ascent | 35.8 MB | [metric:sightlines_3d/build/ascent#bytes=17583594] | [metric:sightlines_3d/build/ascent#seconds_table=14.0] (22) | [metric:sightlines_3d/build/ascent#n_cells=9516] | development | [metric:sightlines_3d/gate/ascent#los3d_share=0.869] of 727 | [metric:sightlines_3d/gate/ascent#los2d_share=0.549] | [metric:sightlines_3d/gate/ascent#control_los3d_share=0.076] (2D [metric:sightlines_3d/gate/ascent#control_los2d_share=0.068]) |
| Haven | 30.6 MB | [metric:sightlines_3d/build/haven#bytes=19421705] | [metric:sightlines_3d/build/haven#seconds_table=12.2] (20) | [metric:sightlines_3d/build/haven#n_cells=7979] | development | [metric:sightlines_3d/gate/haven#los3d_share=0.888] of 466 | [metric:sightlines_3d/gate/haven#los2d_share=0.646] | [metric:sightlines_3d/gate/haven#control_los3d_share=0.083] (2D [metric:sightlines_3d/gate/haven#control_los2d_share=0.069]) |
| Lotus | 25.2 MB | [metric:sightlines_3d/build/lotus#bytes=10723383] | [metric:sightlines_3d/build/lotus#seconds_table=14.1] (18) | [metric:sightlines_3d/build/lotus#n_cells=9271] | development | [metric:sightlines_3d/gate/lotus#los3d_share=0.909] of 596 | [metric:sightlines_3d/gate/lotus#los2d_share=0.750] | [metric:sightlines_3d/gate/lotus#control_los3d_share=0.088] (2D [metric:sightlines_3d/gate/lotus#control_los2d_share=0.070]) |
| Split | 32.5 MB | [metric:sightlines_3d/build/split#bytes=14255580] | [metric:sightlines_3d/build/split#seconds_table=32.3] (40) | [metric:sightlines_3d/build/split#n_cells=13893] | development | [metric:sightlines_3d/gate/split#los3d_share=0.911] of 631 | [metric:sightlines_3d/gate/split#los2d_share=0.707] | [metric:sightlines_3d/gate/split#control_los3d_share=0.085] (2D [metric:sightlines_3d/gate/split#control_los2d_share=0.070]) |
| Summit | 46.8 MB | [metric:sightlines_3d/build/summit#bytes=24365963] | [metric:sightlines_3d/build/summit#seconds_table=9.3] (17) | [metric:sightlines_3d/build/summit#n_cells=7037] | development | [metric:sightlines_3d/gate/summit#los3d_share=0.897] of 465 | [metric:sightlines_3d/gate/summit#los2d_share=0.767] (3D on the same 330: [metric:sightlines_3d/gate/summit#los3d_share_on_2d_set=0.882]) | [metric:sightlines_3d/gate/summit#control_los3d_share=0.071] (2D [metric:sightlines_3d/gate/summit#control_los2d_share=0.052]) |
| Sunset | 32.8 MB | [metric:sightlines_3d/build/sunset#bytes=19731613] | [metric:sightlines_3d/build/sunset#seconds_table=9.3] (17) | [metric:sightlines_3d/build/sunset#n_cells=7598] | development | [metric:sightlines_3d/gate/sunset#los3d_share=0.947] of 376 | [metric:sightlines_3d/gate/sunset#los2d_share=0.779] | [metric:sightlines_3d/gate/sunset#control_los3d_share=0.080] (2D [metric:sightlines_3d/gate/sunset#control_los2d_share=0.067]) |
| Bind | 27.9 MB | [metric:sightlines_3d/build/bind#bytes=12575753] | [metric:sightlines_3d/build/bind#seconds_table=10.6] (17) | [metric:sightlines_3d/build/bind#n_cells=8287] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/bind#los3d_share=0.926] of 1690 | no 2D table | [metric:sightlines_3d/gate_confirm/bind#control_los3d_share=0.113] |
| Breeze | 26.8 MB | [metric:sightlines_3d/build/breeze#bytes=10973428] | [metric:sightlines_3d/build/breeze#seconds_table=29.8] (36) | [metric:sightlines_3d/build/breeze#n_cells=13436] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/breeze#los3d_share=0.925] of 333 | no 2D table | [metric:sightlines_3d/gate_confirm/breeze#control_los3d_share=0.065] |
| Corrode | 44.1 MB | [metric:sightlines_3d/build/corrode#bytes=22593046] | [metric:sightlines_3d/build/corrode#seconds_table=8.7] (16) | [metric:sightlines_3d/build/corrode#n_cells=7456] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/corrode#los3d_share=0.905] of 1190 | no 2D table | [metric:sightlines_3d/gate_confirm/corrode#control_los3d_share=0.077] |
| Fracture | 26.4 MB | [metric:sightlines_3d/build/fracture#bytes=15549819] | [metric:sightlines_3d/build/fracture#seconds_table=24.5] (31) | [metric:sightlines_3d/build/fracture#n_cells=11455] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/fracture#los3d_share=0.836] of 780 | no 2D table | [metric:sightlines_3d/gate_confirm/fracture#control_los3d_share=0.067] |
| Icebox | 26.3 MB | [metric:sightlines_3d/build/icebox#bytes=10731147] | [metric:sightlines_3d/build/icebox#seconds_table=19.7] (25) | [metric:sightlines_3d/build/icebox#n_cells=10606] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/icebox#los3d_share=0.848] of 467 | no 2D table | [metric:sightlines_3d/gate_confirm/icebox#control_los3d_share=0.070] |
| Pearl | 32.6 MB | [metric:sightlines_3d/build/pearl#bytes=13193692] | [metric:sightlines_3d/build/pearl#seconds_table=8.9] (15) | [metric:sightlines_3d/build/pearl#n_cells=7547] | confirmation, instrument check | [metric:sightlines_3d/gate_confirm/pearl#los3d_share=0.918] of 1398 | no 2D table | [metric:sightlines_3d/gate_confirm/pearl#control_los3d_share=0.080] |

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

## Blockers and questions for the player

- **Eye height, crouch height, walkable slope and jump height.** The game
  files serialise only `NavAgentProps` (radius 42, height 196, step 45 cm);
  the rest are native defaults. Searched again for the all-maps build:
  `BasePlayerCharacter`'s movement component (`CharMoveComp`) holds speeds,
  friction and jump-landing slow, no walkable angle, crouch height or jump
  velocity; its capsule is native; no `ShooterGame/Config/*.ini` sets them.
  The step (45 cm) is the game's; the rest stay placeholders: eye 160 cm,
  chest 120 cm, crouch room 100 cm, UE's default 44.8 degree slope, 120 cm
  jump. Two values in the files are not the player's and are not used: the
  character's `TargetEyeHeightProportion` 0.7 (the files do not say of what)
  and `DefaultEngine.ini`'s `RecastNavMesh` agent for bots (height 144, max
  height 160, slope 44 degrees, step 35 cm). The player could answer: his
  eye height standing and crouched, and his jump height.
- **Props of uncertain state** kept as static: Corrode's
  `RadianiteSaltCrystal_C` and `InstancedRadianiteSaltCrystal_C`, Summit's
  `DescentBox_v5_C`, Bind's `BP_Pot_1_C` and `BP_Pot_3_C`. Do any of them
  break or move in a round?
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
.\.venv\Scripts\python.exe prototypes\sightlines.py choose --record
```

Each map uses its game folder (`sightlines_3d.CODENAMES`: Split is Bonsai,
Haven Triad, Bind Duality, Icebox Port, Breeze Foxtrot, Fracture Canyon,
Pearl Pitt, Lotus Jam, Sunset Juliett, Abyss Infinity, Summit Plummet,
Corrode Rook). Check that no VALORANT process runs before each extraction.

The caster is `embreex` 4.4.0 with `trimesh` 5.1.1, installed into the venv
for this probe.
