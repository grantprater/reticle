# 3D sightlines from the game files: feasibility probe

Status: findings, recorded 2026-10-04. Code: `prototypes/sightlines_3d.py`
(`sightlines-3d-0.1.0`); predictions `sightline-3d-20261004` S1-S5 in the
store's `notes/predictions.jsonl`. It serves the coaching question of
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
  in [metric:sightlines_3d/build/ascent#seconds_table=10.4] s and the whole
  compact file is [metric:sightlines_3d/build/ascent#bytes=17481575] bytes.
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

`game-extract meshes` (added to the store's extractor, build
release-13.06-shipping-18-5590001) writes each StaticMeshComponent and each
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

## Cost for every map in the player's history

The player's history holds 13 maps in 168 matches (the 2 held-out replay
matches listed in it excluded; the other 12 held-out matches and the 22
captured ones are not in that table). Every one of the 13 has a callout
volume level in the build. Split took
[metric:sightlines_3d/build/split#seconds_table=27.4] s for
[metric:sightlines_3d/build/split#n_cells=13893] cells and wrote
[metric:sightlines_3d/build/split#bytes=14049033] bytes. All 13 maps at 1 m:
about 10 minutes of one core and 0.25 GB in the store; raw dumps (33 MB a
map) are deleted once the compact file exists. A 0.5 m grid multiplies pairs
by 16: about 7 minutes and 0.1 GB a map.

## Blockers and questions for the player

- **Eye height, crouch height, walkable slope and jump height.** The game
  files serialise only `NavAgentProps` (radius 42, height 196, step 45 cm);
  the rest are native defaults. Placeholders: eye 160 cm, chest 120 cm,
  crouch room 100 cm, UE's default 44.8 degree slope, 120 cm jump.
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
```

The caster is `embreex` 4.4.0 with `trimesh` 5.1.1, installed into the venv
for this probe.
