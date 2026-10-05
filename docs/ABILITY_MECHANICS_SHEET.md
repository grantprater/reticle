# Ability mechanics sheet

One row per ability of every agent in the catalogue, for the player to fill.
Mechanics are unique per ability [domain:abilities/ability-rules-are-unique]:
nothing here is inferred from a sibling ability. A cell holds a value only
where a source says it, with the domain fact or the census beside it; every
other cell is `?`. Replace a `?` with the answer, or answer in chat by agent
and ability; each answer becomes a fact in `domain/abilities.toml` or
`domain/hud.toml`. No script writes this sheet: whoever records a fact edits
its cell by hand, from those files, the catalogue or the census.

The game's own data names each ability's states, sounds, minimap textures and
views; [ABILITY_STATES_GAMEDATA.md](ABILITY_STATES_GAMEDATA.md) says where, and its
questions sit in the cells below.

Columns. *Deployment* comes from the catalogue
(`<store>/reference/abilities.json`, harvested from the wiki on 2026-09-04,
sometimes wrong). *Charges* for C, Q and E are the catalogue's counts, which
the player confirmed [domain:abilities/catalogue-charge-counts-confirmed];
a per-ability fact stands beside each count the player gave one by one.
*Restock* is how a spent charge returns within a round, over time or on
kills, a fact per ability [domain:abilities/recharge-kinds].

The Restock column of C, Q and E and the Charges column of X hold the
catalogue's values, which the player confirmed on 2026-09-29
[domain:abilities/catalogue-restock-and-ult-points-confirmed]: a C, Q or E
slot's restock (`none` where the catalogue lists none), or an X slot's
ultimate points, from the catalogue's `cost`. They were 72 restock and 28
ultimate-point questions; Astra's X has no catalogue cost.

*Description says* is derived from the in-game description's capitalised
verbs (EQUIP, FIRE, HOLD FIRE to channel, extend or guide, ACTIVATE, REUSE,
REACTIVATE, RE-USE at the cost of fuel) and phrases such as "take control"
or "when an enemy crosses" [domain:abilities/ability-description-verbs]: a
hypothesis fitted to the player's classifications of 2026-09-26, never an
answer. *Activation* is the answer, the input model: instant on cast, placed
then a second press, placed then enemy proximity, piloted, channelled,
guided while held, toggled by hand or by fuel running out
[domain:abilities/placed-then-activated] [domain:abilities/viper-fuel-toggle].
*Minimap* is what the widget draws for the caster, in the player's
vocabulary: an icon; an icon with a pale ring of a fixed radius or a pale
box [domain:abilities/minimap-icon-pale-region]; a disc; a straight line; a
curve the icon traces along its path [domain:abilities/wall-icon-path-curve];
a dash or teleport trace [domain:abilities/minimap-dash-or-teleport-trace];
nothing. The census value is the blind read's majority over the solo demos,
with the vote count. *Overlay* is any tint or edge effect on the caster's
screen while the ability runs [domain:hud/controlled-entity-view-tint].
*Duration* is the ability's life. *Notes* hold sounds, tray behaviour and open
questions.

Open questions span rows. Every piloted drone has its own vision cone
[domain:abilities/piloted-drones-have-cones]. Which drones, and does a
drone's cone light the floor like a player's? The minimap draws a self audio
circle round the self icon [domain:minimap/self-audio-circle] on every
sound, at the fixed audio range. How long does it linger after a sound? Is
the large white circle round the Lotus A-site stack at 5822b6646448 49.50 s
this circle? At that frame Gekko's icon is drawn without its cone
[domain:minimap/ally-icon-without-cone]. Why? A dead Clove's smoke menu
draws a range circle round the Clove's death location
[domain:abilities/clove-dead-smoke-range-circle]. What is its radius?
No ability but Clove's is cast while its owner is dead
[domain:abilities/no-cast-while-dead]. Thirteen placed abilities persist
after their owner dies (their Duration cells); the list may be incomplete.
Which others persist? Where a Notes cell asks whether a placed one can be
activated after its owner dies, the question is a second press on a device
placed while the owner lived, as Vyse's Arc Rose placed and then flashed.
Dashes and teleports move an agent farther than running
[domain:abilities/movement-abilities-are-dashes-and-teleports]; the Notes
cells that ask it are candidates from the catalogue's wiki function tags
and descriptions, for the player to confirm or strike. Grenades that
launch, and abilities that move other agents, are left out. On 2026-10-04
the player confirmed the teleports and dashes whose cells cite a fact;
`track.motion_for` reads them. Veto's teleport is Crosscut
[domain:abilities/veto-crosscut-teleports]. Both of Lightspeed's dashes can
be horizontal [domain:abilities/waylay-lightspeed-dashes]. Refract draws no
teleport: the player believes it carries Waylay back continuously on
others' minimaps [domain:abilities/waylay-refract-minimap], so `track`
licenses nothing for it. No player, teammate or enemy, disappears mid-round
[domain:rounds/no-mid-round-disappearance].
Killjoy, Cypher and Chamber pick up deployed utility
[domain:abilities/killjoy-deployed-util-pickup]
[domain:abilities/cypher-deployed-util-pickup]
[domain:abilities/chamber-deployed-util-pickup], and the charge
returns after a cooldown [domain:abilities/deployed-pickup-returns-charge].
The tray draws a numeral timer on the cooling charge
[domain:hud/ability-tray-cooling-charge-timer].
Which of their abilities count is a fact per agent
[domain:abilities/killjoy-pickup-abilities-gamefile]
[domain:abilities/cypher-pickup-abilities-gamefile]
[domain:abilities/chamber-pickup-abilities-gamefile].

The tray draws a charge that comes back during the round gold, not teal, on
Recon Bolt and Guiding Light [domain:hud/ability-tray-restocked-charge-gold],
and gold was also seen on Jett's Tailwind, Phoenix's Curveball, Clove's
Ruse and Skye's Regrowth [domain:hud/ability-tray-gold-on-other-kits]. The
player reads gold as a charge present on a slot partly spent or recharged
[domain:hud/ability-tray-gold-charge-meaning], and a Phoenix blind can turn a
bar gold [domain:hud/ability-tray-gold-under-a-blind]. What recharges each of
these abilities: time, kills, or something else? On Regrowth gold marks a
partly spent pool, and a gold Regrowth bar going empty spends the rest of it
[domain:abilities/skye-regrowth-gold-bar-partly-spent]. When
does a gold segment turn teal again? A white numeral above a slot counts down to Recon Bolt's and
Guiding Light's return [domain:hud/ability-tray-restock-countdown]; numerals
also showed over Skye's Q ('100', '30'), over a slot C counting down from
'60' (223d636bf8d2 248.5 s) and over a slot Q from '14' (5822b6646448 419.6 s)
[domain:hud/ability-tray-restock-countdown-font]. What does the numeral count
on each ability where it was seen? With two Guiding Light charges spent, which
charge's return does the numeral count (c62c2b06bcfb 216.0 s returned a charge
while it read '27')?

## Killfeed icons

Which of an agent's abilities can draw a killfeed icon? The player's rule:
any damaging ability can draw a kill's weapon-slot icon
[domain:killfeed/damaging-ability-kill-icon], and any disabling ability an
assist icon [domain:killfeed/disabling-ability-assist-icon]; a passive draws
no icon [domain:abilities/passive-abilities-draw-no-ui].
`adjudication.killfeed_kits` applies the rule to each ability's reference
description, beside the icons the facts name: Breach's Aftershock
[domain:killfeed/ability-kill-icon]; Chamber's Headhunter and Tour De Force
[domain:killfeed/chamber-gun-shaped-abilities]; Jett's Blade Storm
[domain:killfeed/jett-blade-storm-icon]; Sage's Resurrection, Clove's Not
Dead Yet and KAY/O's NULL/cmd in a revive [domain:killfeed/revive-entries]
[domain:killfeed/kayo-downed-entry]. The player answered on 2026-10-01 every
damage question the rule left open
([metric:killfeed_kits/derivation@reference#player_decided=19] abilities,
`killfeed_kits.PLAYER_ANSWERS`); of
[metric:killfeed_kits/derivation@reference#abilities=121] reference entries,
[metric:killfeed_kits/derivation@reference#damage_undecided=0] stay open.
Iso's Kill Contract is the player's belief, not confirmed: it "might show the
icon if he kills them in it". Does it?

The mined weapon-slot gallery holds one exemplar the player labelled
Curveball, though the description names a flash and no damage: b3b9defb6fd7
at 1731.5 s, a Phoenix kill. Its stored box sits in the weapon slot, between
the killer's name and the victim's, not in the assist panel
(`<store>/analysis/killfeed-openset-20261001/curveball_boxes.png`); the icon
is a flame. Is that icon Curveball or Hot Hands, and can a non-damaging
ability draw a kill's weapon-slot icon?

The assist list is not yet read by any owner. For each row: can the ability
draw an assist icon? And can a damaging ability draw one?

| Agent | Ability | Why the rule cannot decide | Description excerpt |
|---|---|---|---|
| Astra | Astral Form / Cosmic Divide | 'blocks bullets' with no status effect | "Cosmic Divide blocks bullets and sound." |
| Cypher | Spycam | 'Reveal' with no status effect | "This dart will Reveal the location of any player struck by the dart." |
| Cypher | Neural Theft | 'Revealed' with no status effect | "After a brief delay, the location of all living enemy players will be Revealed twice." |
| Deadlock | Barrier Mesh | 'Barrier' with no status effect | "EQUIP a Barrier Mesh disc." |
| Fade | Haunt | 'Revealing' with no status effect | "The watcher lashes out on impact, Revealing enemies in its line of sight and creating terror trails to them." |
| Iso | Contingency | 'wall of energy' with no status effect | "FIRE to push an indestructible wall of energy forward that blocks bullets." |
| Sage | Barrier Orb | 'barrier' with no status effect | "EQUIP a barrier orb." |
| Sova | Recon Bolt | 'Revealing' with no status effect | "FIRE to send the recon bolt forward, activating upon collision and Revealing the location of nearby enemies caught in the line of sight of the bolt." |
| Sova | Owl Drone | 'Reveal' with no status effect | "This dart will Reveal the location of any player struck by the dart." |
| Sova | Hunter's Fury | 'Revealing' with no status effect | "FIRE to release an energy blast in a line in front of Sova, dealing damage and Revealing the location of enemies caught in the line." |
| Vyse | Shear | 'wall trap' with no status effect | "FIRE to place a hidden wall trap." |

## Astra

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Gravity Well | Targeted | shared stars [domain:abilities/astra-stars-shared] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph]; the placed, inactive star draws the black passive icon, the hovered star the gold one, and the turned star this ability's icon [domain:abilities/astra-star-minimap-states] | other (census 1) | ? | the placed star persists after Astra dies [domain:abilities/astra-placed-stars-persist-after-death] | can a placed one be activated after its owner dies? |
| Q | Nova Pulse | ? | shared stars [domain:abilities/astra-stars-shared] | ? | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph]; the placed, inactive star draws the black passive icon, the hovered star the gold one, and the turned star this ability's icon [domain:abilities/astra-star-minimap-states] | nothing (census 1) | ? | the placed star persists after Astra dies [domain:abilities/astra-placed-stars-persist-after-death] | can a placed one be activated after its owner dies? |
| E | Nebula  / Dissipate | ? | shared stars [domain:abilities/astra-stars-shared] | ? | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph]; the placed, inactive star draws the black passive icon, the hovered star the gold one, and the turned star this ability's icon [domain:abilities/astra-star-minimap-states] | dark disc [domain:abilities/astra-nebula-minimap-disc]; on a teammate's minimap the star's disc becomes a larger grey disc [domain:abilities/astra-star-ally-minimap-glyph] | ? | the placed star persists after Astra dies [domain:abilities/astra-placed-stars-persist-after-death] | global placement [domain:abilities/astra-nebula-global-placement]; can a placed one be activated after its owner dies? |
| X | Astral Form / Cosmic Divide | ? | ? | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE) | places the stars: a placed, inactive star draws the black passive icon, gold while she hovers it [domain:abilities/astra-star-minimap-states] | nothing (census 1) | ? | game data: up duration 16 s [domain:game_data/astra-astral-form-cosmic-divide-game-data] | Game data (`ability-states-gamedata-0.2.0`): Astral Form places the stars, and only Astra's own client draws the star she aims at yellow (TX_Astra_Minimap_PassiveGold) [domain:abilities/astra-star-hover-yellow]. Does a teammate, or a spectator watching Astra, see the yellow star? Which input turns a placed star into Dissipate's fake smoke (the data names only the star's use action)? |

## Breach

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Aftershock | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Flashpoint | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 2) | ? | game data: flash max duration 2.25 s, initial life span 3 s [domain:game_data/breach-flashpoint-game-data] | ? |
| E | Fault Line | Grounded AoE | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s, or 60.0 s under the server toggle DesignerToggleC; a disagreement a timed restock decides [domain:game_data/ability-restock-times] | charged (HOLD FIRE) | ? | nothing (census 1) | ? | ? | ? |
| X | Rolling Thunder | Grounded AoE | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | wall segments (census 1) | ? | game data: end delay 4 s [domain:game_data/breach-rolling-thunder-game-data] | ? |

## Brimstone

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Stim Beacon | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | ? | ? | game data: stim beacon duration 12 s, zone lifetime 12 s [domain:game_data/brimstone-stim-beacon-game-data] | ? |
| Q | Incendiary | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | ? | ? | game data: fire active duration 8 s [domain:game_data/brimstone-incendiary-game-data] | ? |
| E | Sky Smoke | ? | 3 [domain:abilities/brimstone-sky-smoke-charges] | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | ? | ? | game data: smoke duration 19.25 s [domain:game_data/brimstone-sky-smoke-game-data] | ? |
| X | Orbital Strike | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | ? | ? | ? | ? |

## Chamber

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Trademark | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | white-tinted area, mostly circular [domain:abilities/chamber-trademark-minimap-white-area]; compact icon (census 1) | ? | the round; persists deactivated after Chamber dies [domain:abilities/chamber-trademark-persists-after-death] | the player's trip, confirmed as Trademark at Sunset e37fdeca944f 1795.08 s, top mid [domain:abilities/chamber-trademark-minimap-white-area]. The area's radius? Recall restocks after 30 s [domain:abilities/chamber-trademark-recall-cooldown]; its RECALL usable is not distance-limited (5000 units) [domain:abilities/chamber-trademark-recall-distance], and Chamber need not be close (player 2026-10-04) [domain:abilities/chamber-trademark-recall-any-distance]. |
| Q | Headhunter | Hitscan | 8 [domain:abilities/chamber-headhunter-charges] | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
| E | Rendezvous | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REACTIVATE); movement | ? | nothing (census 1) | ? | the round; persists deactivated after Chamber dies [domain:abilities/chamber-rendezvous-persists-after-death] | a teleport [domain:abilities/chamber-rendezvous-teleports]. Recall restocks after 30 s [domain:abilities/chamber-rendezvous-recall-cooldown]; its RECALL usable is not distance-limited (6000 units) [domain:abilities/chamber-rendezvous-recall-distance], and Chamber need not be close (player 2026-10-04) [domain:abilities/chamber-rendezvous-recall-any-distance]. |
| X | Tour De Force | Hitscan | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | equipping spends the ult, buy phase included [domain:abilities/chamber-tour-de-force-equip-spends-ult]; allies hear the line at the equip [domain:abilities/chamber-tour-de-force-ally-line-at-equip], enemies at the barrier drop [domain:abilities/chamber-tour-de-force-enemy-line-at-drop]. Does Tour De Force carry into the next round when Chamber survives? |

## Clove

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Pick-me-up | ? | 1 [domain:abilities/clove-pick-me-up-charges] | none within a round [domain:abilities/clove-pick-me-up-charges] | second press (ACTIVATE); triggers on enemies | ? | ? | ? | game data: buff active timer length 13 s [domain:game_data/clove-pick-me-up-game-data] | not castable in the range [domain:abilities/clove-c-and-x-need-a-target] |
| Q | Meddle | Class 3 Projectile | 1 [domain:abilities/clove-meddle-charges] | none within a round [domain:abilities/clove-meddle-charges] | cast on FIRE | ? | nothing [domain:abilities/clove-rouse] | ? | game data: initial life span 10 s [domain:game_data/clove-meddle-game-data] | ? |
| E | Ruse | Placement | 2 | 40 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | one bounded dark disc per cloud, at its placement [domain:abilities/clove-rouse]; while dead, the open menu draws a range circle round the death location [domain:abilities/clove-dead-smoke-range-circle] | ? | about 15 s on the minimap [domain:abilities/clove-ruse-minimap-duration] | placeable after death [domain:abilities/clove-smokes-after-death]. The range circle's radius? |
| X | Not Dead Yet | Self-targeted | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE, REACTIVATE) | ? | ? | ? | ? | not castable in the range [domain:abilities/clove-c-and-x-need-a-target]; does Clove dim on the scoreboard before it? [domain:rounds/scoreboard-dim-is-dead] |

## Cypher

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Trapwire | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | two anchor discs and a wire [domain:abilities/cypher-trapwire]; the icon turns with the direction it is placed, the player says [domain:abilities/cypher-trapwire-minimap-glyph-turns-belief] | ? | persists after Cypher dies [domain:abilities/cypher-trapwire-persists-after-death] | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/cypher-trapwire-reveal-belief]. Pickup within 2700 units, no cooldown in the blueprint, a temporary charge after RoundStarting [domain:abilities/cypher-trapwire-pickup-distance]; the player confirmed the distance [domain:abilities/cypher-trapwire-pickup-distance-confirmed]. A wire picked up in the round is placeable again at once; its temporary charge goes away at the round's end and is bought again [domain:abilities/cypher-trapwire-temporary-charge]. |
| Q | Cyber Cage | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); instant | ? | nothing (census 3); the icon turns with placement, the player believes [domain:abilities/cypher-cyber-cage-minimap-glyph-turns-belief] | ? | game data: sustain time 6.4 s [domain:game_data/cypher-cyber-cage-game-data] | can a placed one be activated after its owner dies? Pickup: the game files allow it only in RoundStarting, within 400 units [domain:abilities/cypher-cyber-cage-pickup-distance]; the player confirmed the buy phase only [domain:abilities/cypher-cyber-cage-pickup-buy-phase-only]. How close must Cypher be in the buy phase? |
| E | Spycam | Placement (Setup) Possession (Post-setup) Missile (Dart) | 1 | 60 s (Destroyed); 15 s (Recalled) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | piloted; second press (RE-USE) | ? | nothing (census 3) | ? | persists after Cypher dies [domain:abilities/cypher-spycam-persists-after-death] | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/cypher-spycam-dart-reveal]; can a placed one be activated after its owner dies? Pickup within 2500 units [domain:abilities/cypher-spycam-pickup-distance], confirmed by the player [domain:abilities/cypher-spycam-pickup-distance-confirmed]; 15 s cooldown [domain:abilities/cypher-spycam-pickup-cooldown]. |
| X | Neural Theft | Targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 3) | ? | ? | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/cypher-neural-theft-reveal] |

## Deadlock

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Mesh | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1) | ? | game data: life duration 30 s [domain:game_data/deadlock-barrier-mesh-game-data] | ? |
| Q | Sonic Sensor | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | ? | white-tinted area, mostly circular [domain:abilities/deadlock-sonic-sensor-minimap-white-area]; split {'compact_icon': 1, 'nothing': 1} (census 2) | ? | persists after Deadlock dies [domain:abilities/deadlock-sonic-sensor-persists-after-death] | the area's radius? Does a dim sensor keep it? |
| E | GravNet | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s; a disagreement a timed restock decides [domain:game_data/ability-restock-times] | cast on FIRE | ? | yellow disc under 0.3 s at detonation [domain:abilities/deadlock-gravnet-detonation-flash] | ? | game data: fire active duration 3 s [domain:game_data/deadlock-gravnet-game-data] | ? |
| X | Annihilation | Beam | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | only on a hit, or a very brief flash? [domain:abilities/deadlock-annihilation-minimap] | ? | game data: spline duration 7 s [domain:game_data/deadlock-annihilation-game-data] | X pips empty at equip [domain:abilities/deadlock-ult-tray-drop-at-equip] |

## Fade

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Prowler | Grounded Object | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE) | steered by the player: held, or piloted? [domain:abilities/fade-prowler-steered] | travelling icon [domain:abilities/fade-prowler-minimap-icon] | ? | game data: duration 2.5 s [domain:game_data/fade-prowler-game-data] | ? |
| Q | Seize | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE) | ? | nothing (census 1) | ? | game data: initial life span 5.2 s [domain:game_data/fade-seize-game-data] | ? |
| E | Haunt | Class 2 Projectile | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s (its 60.0 s DPT value cannot apply under its tuning tag); a disagreement a timed restock decides [domain:game_data/ability-restock-times] | second press (RE-USE) | ? | a brief ring at the pulse [domain:abilities/pulse-scan-abilities] | ? | game data: duration 1.5 s [domain:game_data/fade-haunt-game-data] | a pulse scan, as Recon Bolt and the Stealth Drone [domain:abilities/pulse-scan-abilities] |
| X | Nightfall | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | wall segments (census 1) | ? | game data: end delay 12 s [domain:game_data/fade-nightfall-game-data] | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/fade-nightfall-reveal] |

## Gekko

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Mosh Pit | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | 20 s (granted by Globules) [domain:abilities/catalogue-restock-and-ult-points-confirmed]; also a pickup Gekko collects to restock within the round (a later change; it used to drop nothing) [domain:abilities/gekko-mosh-pit-drops-pickup]; game data: 15.0 s, or 20.0 s under the server toggle DesignPlaytest [domain:game_data/ability-restock-times] | cast on FIRE | ? | compact icon (census 1) | ? | game data: fire active duration 4 s [domain:game_data/gekko-mosh-pit-game-data] | ? |
| Q | Wingman | ? | 1 | Gekko recharges it by picking the used Wingman up (the harvest's "none" is withdrawn; all four Gekko abilities drop a pickup [domain:abilities/gekko-abilities-drop-pickups]) [domain:abilities/gekko-wingman-reclaim-or-expire] | cast on FIRE | ? | compact icon (census 1); planting, it carries the spike symbol, then a yellow pick-up disc [domain:abilities/gekko-wingman-plant-minimap] | ? | the used Wingman expires on a timer unless picked up (length unknown) [domain:abilities/gekko-wingman-reclaim-or-expire] | can plant the spike [domain:abilities/gekko-wingman-plants-spike] |
| E | Dizzy | ? | 1 | Gekko restocks it by picking up the thing it drops (the harvest's "none" is withdrawn) [domain:abilities/gekko-dizzy-drops-pickup] | triggers on enemies | ? | compact icon (census 1) | ? | game data: initial life span 10 s [domain:game_data/gekko-dizzy-game-data] | ? |
| X | Thrash | Possession | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips]; Gekko also restocks it by picking up the thing it drops [domain:abilities/gekko-thrash-drops-pickup]; game data: 15.0 s on its cooldown component, against the catalogue's 20 s; a timed restock decides [domain:game_data/ability-restock-times] | second press (ACTIVATE) | ? | compact icon (census 1) | ? | game data: lifetime duration 6 s [domain:game_data/gekko-thrash-game-data] | ? |

## Harbor

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Storm Surge | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | brief flash (census 1) | ? | ? | ? |
| Q | High Tide | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE); ends early on a press | ? | wall segments (census 1) | ? | game data: wall duration 15 s [domain:game_data/harbor-high-tide-game-data] | ? |
| E | Cove | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed]; the game files give a 30.0 s cooldown whose use is unread [domain:game_data/ability-restock-times] | second press (ACTIVATE, REACTIVATE) | ? | dark disc (census 1) | ? | game data: smoke duration 19.25 s [domain:game_data/harbor-cove-game-data] | ? |
| X | Reckoning | ? | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | wall segments (census 1) | ? | game data: wall linger state countdown time 7 s [domain:game_data/harbor-reckoning-game-data] | ? |

## Iso

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Contingency | Grounded Object | 1 [domain:abilities/iso-contingency-charges] | none within a round [domain:abilities/iso-contingency-charges] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Undercut | Missile | 1 [domain:abilities/iso-undercut-charges] | none within a round [domain:abilities/iso-undercut-charges] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| E | Double Tap | Self-targeted | 1 [domain:abilities/iso-double-tap-charges] | none within a round [domain:abilities/iso-double-tap-charges] | instant | ? | unsure (census 1) | ? | game data: orb initial life span 3 s [domain:game_data/iso-double-tap-game-data] | ? |
| X | Kill Contract | Grounded AoE | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | game data: initial life span 4 s, duel timeout duration 13 s [domain:game_data/iso-kill-contract-game-data] | ? |

## Jett

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Cloudburst | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE); instant | ? | dark disc (census 2) | ? | see [domain:abilities/jett-cloudburst-duration] | ? |
| Q | Updraft | Self-targeted | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant; movement | ? | nothing (census 1) | ? | ? | vertical, no horizontal step [domain:abilities/jett-updraft-is-vertical] |
| E | Tailwind | Self-targeted | 1 | 2 kills (1 in Escalation) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE, RE-USE); movement | ? | nothing (census 1) | ? | ? | a horizontal dash [domain:abilities/jett-tailwind-is-a-horizontal-dash] |
| X | Blade Storm | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | no line heard in a buy phase [domain:abilities/jett-blade-storm-line-not-in-buy-phase]. Can Blade Storm be cast in the buy phase, and if so, when do allies and enemies hear its line? |

## KAY/O

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | FRAG/ment | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | FLASH/drive | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | travelling icon [domain:abilities/kayo-flashdrive-minimap-icon] | ? | game data: flash max duration 2.25 s [domain:game_data/kayo-flash-drive-game-data] | ? |
| E | ZERO/point | Class 4 Projectile | 1 | 60 s (Restock removed in Replication) [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s, or 60.0 s under the server toggle DesignerToggleC; a disagreement a timed restock decides [domain:game_data/ability-restock-times] | cast on FIRE | ? | teal ring (census 1) | ? | game data: initial life span 15 s [domain:game_data/kayo-zero-point-game-data] | ? |
| X | NULL/cmd | Self-targeted (Buffs) Emission (Pulses) | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 1) | ? | game data: wait for downed timer length 12 s [domain:game_data/kayo-null-cmd-game-data] | does a downed KAY/O dim on the scoreboard? [domain:rounds/scoreboard-dim-is-dead] While KAY/O lies downed his tray empties or shows an overlay, the player believes [domain:abilities/kayo-null-cmd-downed-tray-belief]; a stabilised KAY/O gets his kit back as before the down, unrefilled [domain:abilities/kayo-null-cmd-stabilise-restores-kit]. Which, empty or overlay, on a capture? |

## Killjoy

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Nanoswarm | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon, white triangle [domain:abilities/killjoy-nanoswarm-minimap-icon] | ? | the round; persists deactivated after Killjoy dies [domain:abilities/killjoy-nanoswarm-persists-after-death] | can a placed one be activated after its owner dies? Game data (`ability-states-gamedata-0.1.0`): the minimap component names only `TX_UI_Minimap_Killjoy_C_InActive`; `_Active` and `_Selected` belong to the in-world icon (Comp_InWorldIcon). Does the minimap icon change when the swarm activates, or when you aim at it? Pickup: the game files allow it only in RoundStarting, within 400 units [domain:abilities/killjoy-nanoswarm-pickup-distance]; the player confirmed the buy phase only [domain:abilities/killjoy-nanoswarm-pickup-buy-phase-only]. How close must Killjoy be in the buy phase? |
| Q | ALARMBOT | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; recallable | ? | dark disc with line art [domain:abilities/killjoy-alarmbot] | ? | the round; persists deactivated after Killjoy dies [domain:abilities/killjoy-alarmbot-persists-after-death] | recall restocks after 20 s [domain:abilities/killjoy-alarmbot-recall-cooldown]; the game data holds no pickup distance, and the player does not know it, believing it shorter than Cypher's [domain:abilities/killjoy-alarmbot-pickup-distance-player]. The distance awaits a measurement. |
| E | TURRET | Placement | 1 | 60 s (Destroyed); 20 s (Recalled) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; recallable | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | nothing (census 1) | ? | the round; persists deactivated after Killjoy dies [domain:abilities/killjoy-turret-persists-after-death] | Game data (`ability-states-gamedata-0.1.0`): the turret's minimap component names `TX_UI_Minimap_Killjoy_E_InActive`; `_Active` appears only in FXC_Killjoy_E_Turret_HasTarget, which no exported blueprint names. Does the turret's minimap icon change while it fires at a target? Recall restocks after 20 s [domain:abilities/killjoy-turret-recall-cooldown]; the game data holds no pickup distance, and the player does not know it, believing it shorter than Cypher's [domain:abilities/killjoy-turret-pickup-distance-player]. The distance awaits a measurement. |
| X | Lockdown | ? | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | compact icon (census 1) | ? | game data: shockwave initial life span 8 s [domain:game_data/killjoy-lockdown-game-data] | ? |

## Miks

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | M-pulse | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 2) | ? | game data: thump duration 2 s [domain:game_data/miks-m-pulse-game-data] | ? |
| Q | Harmonize | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | game data: buff duration 8 s [domain:game_data/miks-harmonize-game-data] | ? |
| E | Waveform | Placement | 2 | 40 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | dark disc [domain:abilities/miks-smoke-minimap-disc] | ? | game data: smoke duration 16.25 s after a 1.0 s delay, then a 1.0 s contraction, 18.25 s in all [domain:game_data/miks-waveform-game-data]; the player's 16.75 s is superseded [domain:abilities/miks-smoke-duration] | ? |
| X | Bassquake | Grounded AoE | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | a wedge of fixed radius [domain:abilities/miks-bassquake-minimap-wedge]; census 1 saw nothing | ? | ? | ? |

## Neon

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Fast Lane | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | wall segments (census 1) | ? | game data: wall duration 4 s [domain:game_data/neon-fast-lane-game-data] | ? |
| Q | Relay Bolt | Class 5 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | compact icon (census 1) | ? | ? | ? |
| E | High Gear | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant; movement | ? | nothing (census 2) | an edge overlay, this or Overdrive? [domain:hud/neon-edge-overlay] | ? | runs faster than normal, not a dash [domain:abilities/neon-high-gear-is-speed-not-dash]; how much faster? |
| X | Overdrive | Hitscan | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | movement | ? | nothing (census 1) | an edge overlay, this or High Gear? [domain:hud/neon-edge-overlay] | ? | moves its agent farther than running? (candidate, possible; regains a slide charge) [domain:abilities/movement-abilities-are-dashes-and-teleports] |

## Omen

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Shrouded Step | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 4, {'nothing': 3, 'unsure': 1}) | ? | ? | a teleport [domain:abilities/omen-shrouded-step-teleports] |
| Q | Paranoia | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | travelling icon [domain:abilities/omen-paranoia-minimap-icon] | ? | ? | ? |
| E | Dark Cover | Missile | 2 | 40 s after use [domain:abilities/omen-dark-cover-restock] | cast on FIRE | ? | dark disc in phases [domain:abilities/omen-dark-cover-minimap-phases] | ? | game data: smoke duration 14.7 s, initial life span 16 s [domain:game_data/omen-dark-cover-game-data] | global placement [domain:abilities/omen-dark-cover-global-placement] |
| X | From the Shadows | Placement | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | movement | ? | other (census 2) | ? | ? | a teleport [domain:abilities/omen-from-the-shadows-teleports] |

## Phoenix

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Blaze | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE) | ? | orange wall [domain:abilities/phoenix-blaze], no icon (disputed) [domain:abilities/phoenix-blaze-no-minimap-icon] | ? | 8 s, from the cast or the wall's completion? [domain:abilities/phoenix-blaze-duration] | ongoing sound [domain:abilities/ability-sound-phases] |
| Q | Hot Hands | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 [domain:abilities/phoenix-hot-hands-charges] | none within a round [domain:abilities/phoenix-hot-hands-charges] | cast on FIRE | ? | nothing (census 2) | ? | game data: fire active duration 4.2 s [domain:game_data/phoenix-hot-hands-game-data] | ongoing sound on the ground [domain:abilities/ability-sound-phases] |
| E | Curveball | Missile | 2 [domain:abilities/phoenix-curveball-charges] | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing [domain:abilities/phoenix-minimap-objects] | ? | ? | ? |
| X | Run it Back | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 1) | ? | about 10 s [domain:abilities/phoenix-run-it-back-expiry-flash] | X pips never fall; timer bar under the crosshair [domain:hud/ability-timer-bar]; a teleport back to the cast point [domain:abilities/phoenix-run-it-back-teleports] [domain:rounds/phoenix-run-it-back-returns-to-cast-point] |

## Raze

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Boom Bot | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1) | ? | game data: duration 5 s [domain:game_data/raze-boom-bot-game-data] | ? |
| Q | Blast Pack | Class 1 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE); instant | ? | nothing (census 2) | ? | game data: initial life span 5 s [domain:game_data/raze-blast-pack-game-data] | can act as a dash, an impulse from the satchel's angle and her velocity [domain:abilities/raze-blast-pack-acts-as-dash] |
| E | Paint Shells | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | game data: initial life span 2 s [domain:game_data/raze-paint-shells-game-data] | ? |
| X | Showstopper | Missile | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Reyna

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Leer | Missile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); triggers on enemies | ? | travelling icon [domain:abilities/reyna-leer-minimap-icon] | ? | game data: initial life span 2 s [domain:game_data/reyna-leer-game-data] | ? |
| Q | Devour | ? | ? | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; instant | ? | nothing (census 1) | ? | game data: soul orb orb lifetime duration 3 s [domain:game_data/reyna-devour-game-data] | ? |
| E | Dismiss | ? | ? | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | nothing (census 1) | ? | game data: invis and invuln buff timer length 1.5 s [domain:game_data/reyna-dismiss-game-data] | ? |
| X | Empress | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | ? | ? | ? | no line heard in a buy phase [domain:abilities/reyna-empress-line-not-in-buy-phase]. Can Empress be cast in the buy phase, and if so, does its timer start at the cast or the drop? |

## Sage

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Orb | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | a four-segment line [domain:abilities/sage-barrier-orb-segments]; census 1 saw nothing | ? | game data: segment life duration 40 s [domain:game_data/sage-barrier-orb-game-data] | ? |
| Q | Slow Orb | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 2) | ? | game data: maixmum lifetime 7 s [domain:game_data/sage-slow-orb-game-data] | ? |
| E | Healing Orb | Targeted (Ally cast) Self-targeted (Self cast) | 1 | 45 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| X | Resurrection | Targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Skye

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Regrowth | ? | a resource bar [domain:abilities/skye-regrowth-resource-bar] | the pool does not refill [domain:abilities/skye-regrowth-resource-bar] | channelled (HOLD FIRE) | channelled [domain:abilities/skye-regrowth-channelled] | teal ring round Skye [domain:abilities/skye-regrowth-minimap-ring] | ? | ? | no tray drop [domain:abilities/skye-regrowth-no-tray-drop]. One purchase is a fixed total of healing [domain:abilities/skye-regrowth-pool-per-purchase]; a gold bar is a partly spent pool, and a gold bar going empty spends the rest of it, no new purchase [domain:abilities/skye-regrowth-gold-bar-partly-spent] |
| Q | Trailblazer | Possession | 1 [domain:abilities/skye-trailblazer-charges] | none within a round [domain:abilities/skye-trailblazer-charges] | piloted | controlled by the player, as the Owl Drone [domain:abilities/skye-trailblazer-piloted] | compact icon (census 2) | green view, shows through the minimap void [domain:hud/controlled-entity-view-tint] | game data: possess duration timer length 6 s [domain:game_data/skye-trailblazer-game-data] | is it born at Skye's position, as the Owl Drone and Stealth Drone are [domain:abilities/sova-owl-drone-origin-at-caster]? |
| E | Guiding Light | Missile | 2 [domain:abilities/skye-guiding-light-charges] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s; a disagreement a timed restock decides [domain:game_data/ability-restock-times] | guided path (HOLD FIRE); second press (RE-USE) | steered by the player: held, or piloted? [domain:abilities/skye-guiding-light-steered] | travelling bird icon [domain:abilities/skye-guiding-light-minimap-icon] | ? | game data: duration 2 s [domain:game_data/skye-guiding-light-game-data] | activation sound distinct from the cast [domain:abilities/ability-sound-phases]. Is it born at Skye's position? |
| X | Seekers | Grounded Object | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | tracks its enemy by itself [domain:abilities/skye-seekers-track-and-blind] | unsure (census 1); the icon turns with placement, the player believes [domain:abilities/skye-seekers-minimap-glyph-turns-belief] | ? | until destroyed or it reaches its enemy, who is blinded [domain:abilities/skye-seekers-track-and-blind]; despawns when its enemy dies? | one Seeker per living enemy [domain:abilities/skye-seekers-one-per-living-enemy]. The large circle at Sunset e37fdeca944f 1795.08 s, once believed the ult's [domain:abilities/skye-seekers-minimap-large-circle-belief], the player now gives to a dead Clove's smoke range [domain:abilities/clove-dead-smoke-range-circle] |

## Sova

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Owl Drone | ? | 1 [domain:abilities/sova-owl-drone-charges] | none within a round [domain:abilities/sova-owl-drone-charges] | piloted | piloted [domain:abilities/sova-owl-drone-piloted] | compact icon (census 2) | player: some; crop measured no hue shift [domain:hud/controlled-entity-view-tint] | game data: drone duration timer length 7 s [domain:game_data/sova-owl-drone-game-data] | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/sova-owl-drone-dart-reveal] |
| Q | Shock Bolt | ? | 2 [domain:abilities/sova-shock-bolt-charges] | none within a round [domain:abilities/sova-shock-bolt-charges] | charged (HOLD FIRE) | ? | nothing [domain:abilities/sova-shock-bolt-minimap-none] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce] |
| E | Recon Bolt | Class 2/3/4/5 Projectile (based on charge) | 1 [domain:abilities/sova-recon-bolt-charges] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed]; game data: 50.0 s (its 60.0 s DPT value cannot apply under its tuning tag); a disagreement a timed restock decides [domain:game_data/ability-restock-times] | charged (HOLD FIRE); triggers on enemies | ? | icon with a teal ring of the reveal range, kept the whole time [domain:abilities/sova-recon-bolt-minimap-ring] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce]; a pulse scan, 2 pulses over a few seconds [domain:abilities/pulse-scan-abilities]; the revealed enemy shows as its icon, no light [domain:minimap/reveal-draws-no-light] |
| X | Hunter's Fury | Beam | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (RE-USED); triggers on enemies | ? | teal line from Sova [domain:abilities/sova-hunters-fury-minimap-beam] | ? | game data: laser active timed state timer length 6 s [domain:game_data/sova-hunters-fury-game-data] | the enemy it reveals or marks shows anywhere, for a time [domain:abilities/sova-hunters-fury-reveal] |

## Tejo

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Stealth Drone | Possession | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | piloted | piloted [domain:abilities/tejo-stealth-drone-piloted] | travelling icon; a brief ring at the pulse [domain:abilities/pulse-scan-abilities] | brown view; teal weight unmoved [domain:hud/controlled-entity-view-tint] | game data: drone lifetime 6 s [domain:game_data/tejo-stealth-drone-game-data] | a pulse scan, as Recon Bolt and Haunt [domain:abilities/pulse-scan-abilities] |
| Q | Special Delivery | Class 5 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | Guided Salvo | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | rings [domain:abilities/tejo-guided-salvo-minimap-rings] | ? | ? | ? |
| X | Armageddon | ? | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | pale region (census 1) | ? | game data: initial life span 8 s [domain:game_data/tejo-armageddon-game-data] | ? |

## Veto

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Crosscut | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); movement | ? | split {'nothing': 1, 'compact_icon': 1} (census 2) | ? | ? | a teleport [domain:abilities/veto-crosscut-teleports] |
| Q | Chokehold | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | ? | white-tinted area, mostly circular [domain:abilities/veto-chokehold-minimap-white-area]; compact icon (census 1) | ? | persists after Veto dies [domain:abilities/veto-chokehold-persists-after-death] | the player's trip, confirmed as Chokehold [domain:abilities/veto-chokehold-minimap-white-area]. The area's radius? |
| E | Interceptor | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE) | ? | nothing (census 1) | ? | game data: deployable lifetime 9 s [domain:game_data/veto-interceptor-game-data] | ? |
| X | Evolution | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | ? | ? | ? | ? |

## Viper

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Snake Bite | Class 3 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 2) | ? | game data: fire active duration 6.5 s [domain:game_data/viper-snake-bite-game-data] | ? |
| Q | Poison Cloud | ? | 1 | fuel refills over time [domain:abilities/viper-fuel-bar-recharges] | toggle (RE-USE, RE-USED, fuel) | placed, toggled on and off [domain:abilities/viper-poison-cloud-toggle] | dark disc; emitter outline while off [domain:abilities/viper-poison-cloud-emitter-outline] | ? | persists after Viper dies [domain:abilities/viper-poison-cloud-persists-after-death] | can a placed one be activated after its owner dies? |
| E | Toxic Screen | Class 6 Projectile | 1 | fuel refills over time [domain:abilities/viper-fuel-bar-recharges] | toggle (RE-USE, RE-USED, fuel) | ? | wall that grows [domain:abilities/viper-toxic-screen-minimap-growth] | ? | persists after Viper dies [domain:abilities/viper-toxic-screen-persists-after-death] | can a placed one be activated after its owner dies? |
| X | Viper's Pit | Placement | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | ends early on a press | ? | nothing (census 2) | green tint inside [domain:abilities/viper-pit-tint] | ? | ? |

## Vyse

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Razorvine | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATED) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon near Vyse [domain:abilities/vyse-razorvine-minimap-icon] | ? | persists after Vyse dies [domain:abilities/vyse-razorvine-persists-after-death] | can a placed one be activated after its owner dies? |
| Q | Shear | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | other (census 1) | ? | game data: actor life time 6 s [domain:game_data/vyse-shear-game-data] | ? |
| E | Arc Rose | Placement | 1 | 20 s (per use or recalled); 60 s (destroyed) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REUSE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | teal ring (census 1) | ? | ? | can a placed one be activated after its owner dies? |
| X | Steel Garden | Emission | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | game data: end jam timer 8 s, life time 15 s [domain:game_data/vyse-steel-garden-game-data] | ? |

## Waylay

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Saturate | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | game data: initial life span 10 s [domain:game_data/waylay-saturate-game-data] | ? |
| Q | Lightspeed | Self-targeted | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 1) | ? | ? | two dashes, both can be horizontal, only the first vertical [domain:abilities/waylay-lightspeed-dashes] |
| E | Refract | Self-targeted | 1 | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REACTIVATE); instant; movement | ? | nothing (census 1) | ? | game data: record for duration can rewind state timer length 8 s [domain:game_data/waylay-refract-game-data] | blinds her own minimap; on others' minimaps carries her back continuously, by the player's belief; no teleport, so `track` licenses nothing [domain:abilities/waylay-refract-minimap] |
| X | Convergent Paths | Grounded AoE Self-targeted (Buff) | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | wall segments (census 1) | ? | game data: initial life span 3 s [domain:game_data/waylay-convergent-paths-game-data] | ? |

## Yoru

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | FAKEOUT | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1); an extra player icon [domain:abilities/yoru-fakeout-player-icon] | ? | game data: duration 10 s [domain:game_data/yoru-fakeout-game-data] | ? |
| Q | BLINDSIDE | Class 3 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | GATECRASH | Grounded Object (Mobile tether) Placement (Stationary tether) | 2 | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); movement | ? | travelling icon [domain:abilities/yoru-gatecrash-minimap-icon] | ? | game data: duration 20 s [domain:game_data/yoru-gatecrash-game-data] | a teleport [domain:abilities/yoru-gatecrash-teleports] |
| X | DIMENSIONAL DRIFT | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (REACTIVATE) | ? | nothing (census 1) | ? | game data: cloak buff timer length 10 s [domain:game_data/yoru-dimensional-drift-game-data] | a teleport [domain:abilities/yoru-dimensional-drift-teleports] |

## Game data

The extracted game files of build 13.06 hold class-default values for each
ability: lifetimes, sizes, angles, ranges, speeds and caster movement, each
cited to its asset and field in `domain/game_data.toml`. A value there is
the designers' default, not a measurement of play; where a player's answer
above differs, the answer stands. The Duration cells marked *game data*
were open (`?`) and now cite those facts; no answered cell changed. Each
row below names what its fact holds; an empty cell is a value the files
did not give, listed in the fact's `exceptions`. *Size* counts only
lengths of the ability's own shape; *Angle* holds cone and vision angles,
and *Unconfirmed length* a path cap the files leave open between the
wall's length and the throw's range (Toxic Screen, High Tide, Fast Lane). Character
speeds and heights live beside them:
[domain:game_data/character-movement-speeds],
[domain:game_data/weapon-run-speed-multipliers],
[domain:game_data/character-eye-height], in the unit
[domain:game_data/game-units-centimetres].
`prototypes/game_data_facts.py` regenerates the facts file; its
`--sheet` option prints this table and any Duration cell it would fill,
and writes nothing here.

| Agent | Slot | Ability | Life | Size | Angle | Range | Unconfirmed length | Speed | Moves caster | Minimap size | Fact |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Astra | C | Gravity Well | yes | yes |  |  |  |  |  |  | [domain:game_data/astra-gravity-well-game-data] |
| Astra | Q | Nova Pulse |  | yes |  |  |  |  |  |  | [domain:game_data/astra-nova-pulse-game-data] |
| Astra | E | Nebula / Dissipate | yes | yes |  |  |  |  |  | yes | [domain:game_data/astra-nebula-dissipate-game-data] |
| Astra | X | Astral Form / Cosmic Divide | yes |  |  | yes |  |  |  | yes | [domain:game_data/astra-astral-form-cosmic-divide-game-data] |
| Breach | C | Aftershock |  | yes |  | yes |  | yes |  |  | [domain:game_data/breach-aftershock-game-data] |
| Breach | Q | Flashpoint | yes |  |  | yes |  | yes |  |  | [domain:game_data/breach-flashpoint-game-data] |
| Breach | E | Fault Line |  |  |  |  |  | yes |  | yes | [domain:game_data/breach-fault-line-game-data] |
| Breach | X | Rolling Thunder | yes | yes |  | yes |  |  |  |  | [domain:game_data/breach-rolling-thunder-game-data] |
| Brimstone | C | Stim Beacon | yes | yes |  |  |  | yes |  |  | [domain:game_data/brimstone-stim-beacon-game-data] |
| Brimstone | Q | Incendiary | yes | yes |  |  |  | yes |  |  | [domain:game_data/brimstone-incendiary-game-data] |
| Brimstone | E | Sky Smoke | yes | yes |  | yes |  |  |  |  | [domain:game_data/brimstone-sky-smoke-game-data] |
| Brimstone | X | Orbital Strike |  | yes |  | yes |  |  |  |  | [domain:game_data/brimstone-orbital-strike-game-data] |
| Chamber | C | Trademark | yes | yes |  | yes |  |  |  | yes | [domain:game_data/chamber-trademark-game-data] |
| Chamber | E | Rendezvous |  |  |  | yes |  |  | yes | yes | [domain:game_data/chamber-rendezvous-game-data] |
| Chamber | Q | Headhunter |  |  |  |  |  |  |  |  | [domain:game_data/chamber-headhunter-game-data] |
| Chamber | X | Tour De Force |  |  |  |  |  |  |  |  | [domain:game_data/chamber-tour-de-force-game-data] |
| Clove | C | Pick-me-up | yes |  |  |  |  |  |  |  | [domain:game_data/clove-pick-me-up-game-data] |
| Clove | Q | Meddle | yes | yes |  |  |  | yes |  |  | [domain:game_data/clove-meddle-game-data] |
| Clove | E | Ruse | yes | yes |  | yes |  |  |  |  | [domain:game_data/clove-ruse-game-data] |
| Clove | X | Not Dead Yet |  |  |  |  |  |  |  |  | [domain:game_data/clove-not-dead-yet-game-data] |
| Cypher | C | Trapwire |  | yes |  | yes |  |  |  |  | [domain:game_data/cypher-trapwire-game-data] |
| Cypher | E | Spycam |  |  |  | yes |  | yes |  |  | [domain:game_data/cypher-spycam-game-data] |
| Cypher | Q | Cyber Cage | yes | yes |  |  |  | yes |  |  | [domain:game_data/cypher-cyber-cage-game-data] |
| Cypher | X | Neural Theft |  |  |  | yes |  |  |  |  | [domain:game_data/cypher-neural-theft-game-data] |
| Deadlock | C | Barrier Mesh | yes | yes |  |  |  | yes |  |  | [domain:game_data/deadlock-barrier-mesh-game-data] |
| Deadlock | E | GravNet | yes | yes |  |  |  | yes |  |  | [domain:game_data/deadlock-gravnet-game-data] |
| Deadlock | Q | Sonic Sensor |  | yes |  | yes |  |  |  |  | [domain:game_data/deadlock-sonic-sensor-game-data] |
| Deadlock | X | Annihilation | yes | yes |  | yes |  | yes |  |  | [domain:game_data/deadlock-annihilation-game-data] |
| Fade | C | Prowler | yes | yes |  | yes |  | yes |  |  | [domain:game_data/fade-prowler-game-data] |
| Fade | E | Haunt | yes | yes |  |  |  | yes |  | yes | [domain:game_data/fade-haunt-game-data] |
| Fade | Q | Seize | yes | yes |  |  |  | yes |  |  | [domain:game_data/fade-seize-game-data] |
| Fade | X | Nightfall | yes |  |  | yes |  |  |  |  | [domain:game_data/fade-nightfall-game-data] |
| Gekko | C | Mosh Pit | yes | yes |  |  |  | yes |  |  | [domain:game_data/gekko-mosh-pit-game-data] |
| Gekko | E | Dizzy | yes | yes |  | yes |  | yes |  |  | [domain:game_data/gekko-dizzy-game-data] |
| Gekko | Q | Wingman | yes | yes |  | yes |  | yes |  |  | [domain:game_data/gekko-wingman-game-data] |
| Gekko | X | Thrash | yes | yes |  |  |  | yes |  |  | [domain:game_data/gekko-thrash-game-data] |
| Harbor | C | Storm Surge |  | yes |  |  |  | yes |  | yes | [domain:game_data/harbor-storm-surge-game-data] |
| Harbor | E | Cove | yes | yes |  | yes |  | yes |  |  | [domain:game_data/harbor-cove-game-data] |
| Harbor | Q | High Tide | yes |  |  |  | yes | yes |  |  | [domain:game_data/harbor-high-tide-game-data] |
| Harbor | X | Reckoning | yes | yes |  |  |  | yes |  |  | [domain:game_data/harbor-reckoning-game-data] |
| Iso | C | Contingency |  | yes |  |  |  |  |  | yes | [domain:game_data/iso-contingency-game-data] |
| Iso | Q | Undercut |  | yes |  | yes |  | yes |  |  | [domain:game_data/iso-undercut-game-data] |
| Iso | E | Double Tap | yes | yes |  |  |  |  |  |  | [domain:game_data/iso-double-tap-game-data] |
| Iso | X | Kill Contract | yes | yes |  |  |  |  |  | yes | [domain:game_data/iso-kill-contract-game-data] |
| Jett | C | Cloudburst | yes | yes |  |  |  | yes |  | yes | [domain:game_data/jett-cloudburst-game-data] |
| Jett | Q | Updraft |  |  |  |  |  |  | yes |  | [domain:game_data/jett-updraft-game-data] |
| Jett | E | Tailwind |  |  |  |  |  |  | yes |  | [domain:game_data/jett-tailwind-game-data] |
| Jett | X | Blade Storm |  |  |  |  |  |  |  |  | [domain:game_data/jett-blade-storm-game-data] |
| KAY/O | C | FRAG/ment |  | yes |  |  |  | yes |  |  | [domain:game_data/kayo-frag-ment-game-data] |
| KAY/O | Q | FLASH/drive | yes |  |  |  |  | yes |  |  | [domain:game_data/kayo-flash-drive-game-data] |
| KAY/O | E | ZERO/point | yes | yes |  |  |  | yes |  |  | [domain:game_data/kayo-zero-point-game-data] |
| KAY/O | X | NULL/cmd | yes | yes |  |  |  |  |  |  | [domain:game_data/kayo-null-cmd-game-data] |
| Killjoy | C | Nanoswarm | yes | yes |  |  |  | yes |  |  | [domain:game_data/killjoy-nanoswarm-game-data] |
| Killjoy | Q | ALARMBOT |  | yes |  | yes |  | yes |  | yes | [domain:game_data/killjoy-alarmbot-game-data] |
| Killjoy | E | TURRET |  |  | yes | yes |  |  |  |  | [domain:game_data/killjoy-turret-game-data] |
| Killjoy | X | Lockdown | yes | yes |  |  |  |  |  | yes | [domain:game_data/killjoy-lockdown-game-data] |
| Miks | C | M-pulse | yes | yes |  |  |  | yes |  | yes | [domain:game_data/miks-m-pulse-game-data] |
| Miks | E | Waveform | yes | yes |  | yes |  |  |  |  | [domain:game_data/miks-waveform-game-data] |
| Miks | Q | Harmonize | yes |  |  |  |  |  |  |  | [domain:game_data/miks-harmonize-game-data] |
| Miks | X | Bassquake |  | yes | yes |  |  |  |  |  | [domain:game_data/miks-bassquake-game-data] |
| Neon | C | Fast Lane | yes | yes |  |  | yes | yes |  |  | [domain:game_data/neon-fast-lane-game-data] |
| Neon | Q | Relay Bolt |  | yes |  | yes |  | yes |  |  | [domain:game_data/neon-relay-bolt-game-data] |
| Neon | E | High Gear |  |  |  |  |  |  | yes |  | [domain:game_data/neon-high-gear-game-data] |
| Neon | X | Overdrive |  |  |  |  |  |  |  |  | [domain:game_data/neon-overdrive-game-data] |
| Omen | C | Shrouded Step |  |  |  | yes |  |  | yes |  | [domain:game_data/omen-shrouded-step-game-data] |
| Omen | Q | Paranoia |  | yes |  | yes |  | yes |  |  | [domain:game_data/omen-paranoia-game-data] |
| Omen | E | Dark Cover | yes | yes |  | yes |  | yes |  |  | [domain:game_data/omen-dark-cover-game-data] |
| Omen | X | From the Shadows |  |  |  |  |  |  |  |  | [domain:game_data/omen-from-the-shadows-game-data] |
| Phoenix | C | Blaze | yes |  |  |  |  | yes |  |  | [domain:game_data/phoenix-blaze-game-data] |
| Phoenix | Q | Hot Hands | yes | yes |  |  |  | yes |  |  | [domain:game_data/phoenix-hot-hands-game-data] |
| Phoenix | E | Curveball |  |  |  |  |  | yes |  |  | [domain:game_data/phoenix-curveball-game-data] |
| Phoenix | X | Run it Back | yes |  |  |  |  |  |  |  | [domain:game_data/phoenix-run-it-back-game-data] |
| Raze | C | Boom Bot | yes | yes | yes | yes |  | yes |  |  | [domain:game_data/raze-boom-bot-game-data] |
| Raze | Q | Blast Pack | yes | yes |  |  |  | yes | yes |  | [domain:game_data/raze-blast-pack-game-data] |
| Raze | E | Paint Shells | yes | yes |  |  |  | yes |  |  | [domain:game_data/raze-paint-shells-game-data] |
| Raze | X | Showstopper |  | yes |  |  |  | yes |  |  | [domain:game_data/raze-showstopper-game-data] |
| Reyna | C | Leer | yes | yes |  | yes |  | yes |  |  | [domain:game_data/reyna-leer-game-data] |
| Reyna | Q | Devour | yes |  |  | yes |  |  |  |  | [domain:game_data/reyna-devour-game-data] |
| Reyna | E | Dismiss | yes |  |  |  |  |  |  |  | [domain:game_data/reyna-dismiss-game-data] |
| Reyna | X | Empress |  |  |  |  |  |  |  |  | [domain:game_data/reyna-empress-game-data] |
| Sage | C | Barrier Orb | yes | yes |  | yes |  |  |  |  | [domain:game_data/sage-barrier-orb-game-data] |
| Sage | Q | Slow Orb | yes | yes |  |  |  | yes |  |  | [domain:game_data/sage-slow-orb-game-data] |
| Sage | E | Healing Orb |  |  |  | yes |  |  |  |  | [domain:game_data/sage-healing-orb-game-data] |
| Sage | X | Resurrection |  |  |  | yes |  |  |  |  | [domain:game_data/sage-resurrection-game-data] |
| Skye | C | Regrowth |  | yes |  |  |  |  |  | yes | [domain:game_data/skye-regrowth-game-data] |
| Skye | Q | Trailblazer | yes | yes |  | yes |  | yes |  |  | [domain:game_data/skye-trailblazer-game-data] |
| Skye | E | Guiding Light | yes | yes |  |  |  | yes |  |  | [domain:game_data/skye-guiding-light-game-data] |
| Skye | X | Seekers | yes |  |  |  |  | yes |  |  | [domain:game_data/skye-seekers-game-data] |
| Sova | C | Owl Drone | yes |  |  |  |  | yes |  |  | [domain:game_data/sova-owl-drone-game-data] |
| Sova | Q | Shock Bolt |  | yes |  |  |  | yes |  |  | [domain:game_data/sova-shock-bolt-game-data] |
| Sova | E | Recon Bolt |  | yes |  |  |  | yes |  | yes | [domain:game_data/sova-recon-bolt-game-data] |
| Sova | X | Hunter's Fury | yes | yes |  |  |  |  |  |  | [domain:game_data/sova-hunters-fury-game-data] |
| Tejo | C | Stealth Drone | yes | yes |  | yes |  | yes |  |  | [domain:game_data/tejo-stealth-drone-game-data] |
| Tejo | Q | Special Delivery |  | yes |  |  |  | yes |  |  | [domain:game_data/tejo-special-delivery-game-data] |
| Tejo | E | Guided Salvo |  | yes |  | yes |  |  |  | yes | [domain:game_data/tejo-guided-salvo-game-data] |
| Tejo | X | Armageddon | yes | yes |  | yes |  |  |  | yes | [domain:game_data/tejo-armageddon-game-data] |
| Veto | C | Crosscut |  |  |  | yes |  |  | yes | yes | [domain:game_data/veto-crosscut-game-data] |
| Veto | E | Interceptor | yes |  |  | yes |  | yes |  | yes | [domain:game_data/veto-interceptor-game-data] |
| Veto | Q | Chokehold | yes | yes |  |  |  |  |  | yes | [domain:game_data/veto-chokehold-game-data] |
| Veto | X | Evolution |  |  |  |  |  |  |  |  | [domain:game_data/veto-evolution-game-data] |
| Viper | C | Snake Bite | yes | yes |  | yes |  | yes |  |  | [domain:game_data/viper-snake-bite-game-data] |
| Viper | Q | Poison Cloud |  | yes |  |  |  |  |  | yes | [domain:game_data/viper-poison-cloud-game-data] |
| Viper | E | Toxic Screen |  |  |  |  | yes | yes |  |  | [domain:game_data/viper-toxic-screen-game-data] |
| Viper | X | Viper's Pit |  |  |  | yes |  |  |  |  | [domain:game_data/viper-vipers-pit-game-data] |
| Vyse | C | Razorvine | yes | yes |  | yes |  | yes |  |  | [domain:game_data/vyse-razorvine-game-data] |
| Vyse | E | Arc Rose |  |  |  | yes |  |  |  |  | [domain:game_data/vyse-arc-rose-game-data] |
| Vyse | Q | Shear | yes | yes |  | yes |  |  |  |  | [domain:game_data/vyse-shear-game-data] |
| Vyse | X | Steel Garden | yes | yes |  |  |  |  |  |  | [domain:game_data/vyse-steel-garden-game-data] |
| Waylay | C | Saturate | yes | yes |  |  |  | yes |  |  | [domain:game_data/waylay-saturate-game-data] |
| Waylay | E | Refract | yes |  |  |  |  |  |  |  | [domain:game_data/waylay-refract-game-data] |
| Waylay | Q | Lightspeed |  |  |  |  |  |  | yes |  | [domain:game_data/waylay-lightspeed-game-data] |
| Waylay | X | Convergent Paths | yes | yes |  |  |  |  |  | yes | [domain:game_data/waylay-convergent-paths-game-data] |
| Yoru | C | FAKEOUT | yes |  | yes |  |  | yes |  |  | [domain:game_data/yoru-fakeout-game-data] |
| Yoru | Q | BLINDSIDE |  |  |  |  |  | yes |  |  | [domain:game_data/yoru-blindside-game-data] |
| Yoru | E | GATECRASH | yes |  |  | yes |  | yes |  |  | [domain:game_data/yoru-gatecrash-game-data] |
| Yoru | X | DIMENSIONAL DRIFT | yes |  |  |  |  |  |  |  | [domain:game_data/yoru-dimensional-drift-game-data] |
