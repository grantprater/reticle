# Ability states from game data

The player asked on 2026-10-04 for cast, ongoing, dissipation, activation and
the other ability states to be separated in the audio files, and for the
minimap tilesets' states to be modelled the same way. This document says where
the game defines those states, how `prototypes/ability_states_gamedata.py`
reads them into one table, what the table covers, and where it disagrees with
the audio manifest, the minimap inventory, the player's answers and the domain
facts. Mechanics stay unique per ability
[domain:abilities/ability-rules-are-unique]; the table reads each ability's own
data and infers nothing across abilities.

## Where the game defines states

All paths are under the store's
`reference/game-files/release-13.06-shipping-18-5590001/ability-states/`
(game-extract set `ability-states`, `--script --sounds`; tool commit
`26f9f2b`; provenance in the build's `provenance.json`).

- **Keys.** `ShooterGame/Config/DefaultInput.ini` binds `Activate_GrenadeAbility`,
  `Activate_Ability1`, `Activate_Ability2` and `Activate_Ultimate` to C, Q, E
  and X. The agent's `Characters/<Codename>/<Codename>_UIData` names, per
  `ECharacterAbilitySlot`, the ability's UIData class; the
  `AbilityPrimaryAsset_*` whose `UIData` is that class names the equippable,
  whose class default `EquippableSlot` (`EAresItemSlot::Ability1`, ...)
  confirms the slot. Folder letters and the `AbilityTuning.<Agent>.<letter>`
  tags never decide a key.
- **States.** The equippable's components: `EquippableStateMachineComponent`
  and the state components (`TimedStateComponent`, `EquipStateComponent`,
  `ProjectileThrowStateComponent`, `RespondToEventStateComponent`, ...), merged
  down the class chain (`Super`). Each names its effects in `StateEffects`
  (with `bOwnerEffectOnly`, `bStopEffectOnStateEnd`, ...) or
  `MultiStateEffects`; class defaults name more (`FXC_EquippedSettings`).
- **Entities.** Projectiles, game objects, pawns, buffs and damage types the
  ability spawns or names: `ProjectileClass`, `SpawnedActors`, `StateBuffs`,
  `Spawned*Class`, the `AbilityTuning_*` table's `ClassValue` rows, the
  blueprint classes of the equippable's own components (test branches, state
  helpers) and the bytecode. Each event function (`ReceiveBeginPlay`,
  `RevealExpire`, `OnDeath` delegates, timers) is walked through the
  ubergraph from its entry offset. A `*_PC` class outside the agent's root
  folder is a character form the ability spawns (Astra's
  `Rift_TargetingForm_PC`); its `StartingEquippableClasses` join the ability,
  or the ability whose `EquippableSlot` they carry.
- **Sounds.** `FXC_*` effect controllers: `Comp_FXC_AudioBasic` and its kin
  under `Audio/Core` (`PlayOnStart`, loop `StopEvent`, `PlayOnStart1P`,
  `PlayOnStart3PAlly`, `PlayOnStart3PEnemy`, `MuteThirdPerson`,
  `MuteFirstPerson`, `PlayWithAlliance`); montages' `Aud_AnimNotify` events at
  their `LinkValue` times; `EffectAbilityVOComponent` voice rows. Each
  `AkAudioEvent` lists its media debug names, which join the manifest's FLACs.
- **Icons.** Minimap components (`BaseMinimapComponent_Parent`,
  `AresFastMinimapIcon`, `Comp_Actor_AresFastMinimapPill`: `IconBrush`,
  `EnemyIcon`, `Image`, `Icon`) and the in-world icon `Comp_InWorldIcon`, whose
  `BaseTexture`, `HighlightedTexture` and `TriggeredTexture` are its Inactive,
  Selected and Active tiles; bytecode that swaps a brush (`UpdateBrush`).

## The table

Store `reference/ability-states/`, stamp `ability-states-gamedata-0.2.0`
(`0.1.0` stays beside it):

- `ability-states-gamedata-0.2.0.jsonl`: one row per cue (a sound, voice row,
  montage notify or texture) with agent, key, ability, owner, state, phase,
  perspective, `views`, the via chain, media and FLACs, and `rests_on`, the
  exported files that prove the row.
- `ability-states-gamedata-0.2.0.json`: per ability, its states with sounds,
  voice rows and icons, its entities, character forms and coverage; per agent,
  `entity_operations` and the hand readings (`entity_readings`).
- `audio-phases-ability-states-gamedata-0.2.0.jsonl`: per FLAC, the abilities,
  phases, states and events that play it.
- `checks-ability-states-gamedata-0.2.0.json` and
  `provenance-ability-states-gamedata-0.2.0.json`.

`phase` is lexical: the first phase word in the state's own name, else the
effect's, else the event's; `phase_basis` names the word. It reads the
designers' names and proves nothing about timing.

Rebuild: `.\.venv\Scripts\python.exe prototypes\ability_states_gamedata.py build --agents all`,
then `checks --record`.

## Views

Views are separate per ability, and a difference between them is a fact
[domain:abilities/views-separate-per-ability]. Each row carries `views`, a
true, false or null per viewer (self, teammate, enemy, spectator), and
`view_basis`:

- Sounds: `1P` or `bOwnerEffectOnly` is the caster's; `MuteFirstPerson` is
  everyone else's; perspective events split teammate from enemy;
  `PlayWithAlliance=Alliance_Enemy` is the enemy's. A component with no flag
  plays for every viewer, and Wwise picks the media per view by a switch the
  cooked event hides; each file's own `_1P`/`_3P` name sits beside it.
- Minimap: `IconBrush` on a spawned entity draws for the caster's side
  [domain:minimap/ability-drawing-colour-by-side]; `EnemyIcon` for enemies; a
  component on the held equippable for the caster only. Otherwise null.
- Spectator: copies self [domain:minimap/spectator-view-matches-self], unless
  a hand reading of the bytecode decides it. Only Astra's hovered star does
  ([metric:ability_states_gamedata/checks@all-agents#views_spectator_differs_from_self=18]
  rows).

`GameObjectVisibility.EnemyVisibility` is recorded, not applied. Where an
entity sets it to `Never`, the player still answered that enemies see a
drawing on
[metric:ability_states_gamedata/checks@all-agents#views_enemy_drawn_answers_beside_enemy_visibility_never=11]
abilities (Sage's wall, Cypher's tripwire); the setting does not hide a
minimap drawing. Of the player's sure teammate and enemy answers the data
decides, [metric:ability_states_gamedata/checks@all-agents#views_answers_agree=71]
of [metric:ability_states_gamedata/checks@all-agents#views_answers_compared=72]
agree; KAY/O's C (teammate: nothing; data: the projectile's icon) does not.

## Entities and operations

An entity one ability spawns and another names is operated on by the other.
The data finds
[metric:ability_states_gamedata/checks@all-agents#entities_operated_entities=4]:

- **Astra's star** (`GameObject_Rift_X_Markers`). X spawns it through
  `Rift_TargetingForm_PC` and `Ability_Rift_X_PlaceMarkers_WorldTargeting`;
  C, Q and E (`Ability_Rift_TransformRift_Parent`) take the tracker's best
  star as context, destroy it (`DestroyContextActorAfter`) and spawn their
  own object at its place. The hand reading (`entity_readings`) gives its
  states: forming, drawn (`TX_UI_Minimap_Rift_Passive_Default`, alpha 0.25
  when its owner is dead or it is unusable), hovered
  (`TX_Astra_Minimap_PassiveGold`), unhovered (`PassiveBlack`), consumed by
  C, Q or E, dissipated (the star's use action spawns the fake smoke),
  picked up (the same action in the buy phase refunds a charge) and
  deactivated. Hovered precedes consumed
  [domain:abilities/astra-star-hover-yellow], but only Astra's own client
  draws it: her tracker selects only for the local controller, and the
  selection is not replicated. A spectator therefore sees no yellow star,
  against the spectator belief; the mechanics sheet asks the player.
- Clove's X buff that C reads, Neon's E sprint buff that C and Q read, and
  Harbor's C slow that X names: buffs, not placed objects.

Shared components without a spawner sit in `checks.entities.shared`; Viper's
Q and E both carry `StateComponent_FuelSource` and
`StateComponent_HasFuelAmount`, the fuel. Sova's drone and Cypher's camera
live inside one ability each.

## Sova's bolt phases

The player's phases [domain:abilities/sova-shock-bolt-audio-phases]
[domain:abilities/sova-recon-bolt-audio-phases] map onto files as the event
data plays them (`audio-phases-*.jsonl`):

- Cast: `Hunter_AbilQ_Cast_01`-`_04` play from both bolts' fire states, so
  they witness neither [domain:abilities/sova-abilq-cast-is-shock-bolt].
- In flight: `Hunter_AbilQ_Missile_Sweetener_01` (both bolts, the parent
  projectile's `TravelFXC`); `Hunter_Abil4_Missile_Loop_01` (Shock Bolt's
  missile sound, 4.4 s); `Hunter_AbilQ_Missile_Sweetener_2400` (Recon Bolt's,
  0.6 s).
- Landing: Shock Bolt `Hunter_ShockDart_Hit_*`; Recon Bolt
  `Hunter_S0_AB_Q_Hit_*` and `_Hit_ArrowDebris_*`, an event Cypher's camera
  dart and Chamber's trap dart also play.
- Activation: Shock Bolt `Hunter_S0_AB_4_ShockBolt_Explode_01`-`_03` and
  `Hunter_S0_AB_4_Deployed_Start_1`; Recon Bolt's deployed loops
  (`Hunter_AbilQ_Deployed_Loop_01`, `_Deployed_Ally_`/`_Enemy_Swt_Loop`).
- Scan pulse: `Play_Hunter_Abil_SonarBolt_SonarPing_upd`, whose medium
  (`Abil_Joules_Q_Sonar_Ping_01`) the store's `audio-sfx-gaps-0.1.0` holds
  [domain:abilities/sova-recon-bolt-scan-pulse-media].

The cast cannot separate the bolts; the landing and activation files can.

## Coverage

All 29 agents,
[metric:ability_states_gamedata/checks@all-agents#table_abilities=116]
abilities, [metric:ability_states_gamedata/checks@all-agents#table_states=3932]
states, [metric:ability_states_gamedata/checks@all-agents#table_states_with_sound=1821]
with a sound and
[metric:ability_states_gamedata/checks@all-agents#table_states_with_icon=579]
with a texture. The method was proven on Sova, Skye, Phoenix, Clove, Iso,
Omen, Deadlock, Killjoy and Cypher first.

Every UIData ability name matches the mechanics sheet
([metric:ability_states_gamedata/checks@all-agents#keys_sheet_agree=116]).
`EquippableSlot` agrees with the UIData slot on
[metric:ability_states_gamedata/checks@all-agents#keys_item_slot_agree=109];
the other 7 C abilities set none.

Of the manifest's FLACs,
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_agree=3394]
agree with the data's single ability and
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_agree_shared=133]
are shared; the data names an ability for
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_unmapped_resolved_by_data=271]
of the 304 unmapped rows (5 more shared). The data reaches no event of
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_mapped_data_silent=202]
mapped and
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_unmapped_data_silent=28]
unmapped rows: Jett's passive (`AbilP`), Miks' `AbilC_Explosion` media,
Skye's `HawkFlash_Fly`, and hit confirms on damage types the walk leaves.
The export already holds a player for each of the 28: `FXC_Wushu_Glide` and
`_GlideLand` under `Ability_Wushu_Passive_Glide` (folder `S0/Glide`, outside
`Ability_*`), `FXC_Thumper_Slam_Concuss` and `_Heal` under the thumper game
objects, and Tejo's `FXC_Cashew_X_SelectLocation` and
`_ClearClickedLocations` under `Ability_Cashew_X_Airstrike`; the walk misses
them (the store's `game-files/release-13.06-shipping-18-5590001/gaps-0.1.0/`).

## Disagreements

The data and the other sources disagree on
[metric:ability_states_gamedata/checks@all-agents#audio_manifest_disagree=50]
manifest FLACs and
[metric:ability_states_gamedata/checks@all-agents#minimap_textures_player_disagree=7]
answered textures. The checks file lists each with its path; the main ones:

- Sova's cast event plays from both bolts; the player's fact names Shock Bolt
  alone. The shared equips match [domain:abilities/sova-bolt-equips-share-sounds].
- Skye's `Play_Guide_AbilE_ScoutExpire` plays when Trailblazer's pawn ends
  (`Pawn_Guide_Q_PossessableScout` `ReceiveEndPlay`); Guiding Light's timeout
  plays `Play_Guide_HawkFlash_TimeOut`. The player's fact says Guiding Light
  [domain:abilities/skye-scout-expire-is-guiding-light].
- Deadlock's `FishHook_Bullet_Impacts` play when bullets hit Barrier Mesh's
  root (`GameObject_CableJamRoot` `HitConfirmEffect`), not Annihilation.
- Harbor (22 FLACs), Veto (10) and Breach (5) folder letters name other
  abilities than the events' owners.
- Astra's star textures belong to X, the placer; the player answered four of
  them as another agent's.
- Phoenix's Blaze `ThroughWall` projectile draws
  `TX_UI_Minimap_Mage_HighTideActive`; the player answered Harbor.
- Miks' M-pulse thumpers draw `TX_UI_Minimap_Iris_C_InActive` and `_C2_`;
  the player answered Miks E.
- Gekko's `TX_UI_Minimap_Aggrobot_Q` belongs to Q in the data; the inventory
  proposed C.

## Open

The mechanics sheet asks the player about Killjoy's C and E icon states and
Astra's yellow star views and Dissipate input. The turret's active marker is
reached only through its behaviour tree, now exported in `ability-ai-widgets/`
[domain:abilities/killjoy-minimap-texture-referrers]; the walk does not read
behaviour trees yet. The same export pass added the two kill icons the
killfeed set lacked [domain:killfeed/blade-storm-and-mosh-pit-kill-icon-textures]
and the shared controllers behind the 44 `missing_fxc` cues (`shared-fxc/`).
Not derived: the order of state transitions outside the hand reading (the
state machine names states, not edges); AnimSequence notifies (only montages
are exported); the media a perspective switch selects; spectral or duration
matching of files to phases (names and event data only); and the minimap
meaning of `EnemyVisibility`.
