# Ability mechanics sheet

One row per ability of every agent in the catalogue, for the player to fill.
Mechanics are unique per ability [domain:abilities/ability-rules-are-unique]:
nothing here is inferred from a sibling ability. A cell holds a value only
where a source says it, with the domain fact or the census beside it; every
other cell is `?`. Replace a `?` with the answer, or answer in chat by agent
and ability; each answer becomes a fact in `domain/abilities.toml` or
`domain/hud.toml`. No script writes this sheet: whoever records a fact edits
its cell by hand, from those files, the catalogue or the census.

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

One open question spans rows: every piloted drone has its own vision cone
[domain:abilities/piloted-drones-have-cones]. Which drones, and does a
drone's cone light the floor like a player's?

## Astra

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Gravity Well | Targeted | shared stars [domain:abilities/astra-stars-shared] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph] | other (census 1) | ? | ? | ? |
| Q | Nova Pulse | ? | shared stars [domain:abilities/astra-stars-shared] | ? | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph] | nothing (census 1) | ? | ? | ? |
| E | Nebula  / Dissipate | ? | shared stars [domain:abilities/astra-stars-shared] | ? | second press (ACTIVATE) | a placed star turned into this [domain:abilities/astra-star-placed-then-turned]; a teammate sees the placed star as a black disc with a white ring and notch [domain:abilities/astra-star-ally-minimap-glyph] | dark disc [domain:abilities/astra-nebula-minimap-disc]; on a teammate's minimap the star's disc becomes a larger grey disc [domain:abilities/astra-star-ally-minimap-glyph] | ? | ? | ? |
| X | Astral Form / Cosmic Divide | ? | ? | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |

## Breach

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Aftershock | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Flashpoint | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 2) | ? | ? | ? |
| E | Fault Line | Grounded AoE | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | charged (HOLD FIRE) | ? | nothing (census 1) | ? | ? | ? |
| X | Rolling Thunder | Grounded AoE | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |

## Brimstone

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Stim Beacon | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | ? | ? | ? | ? |
| Q | Incendiary | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | ? | ? | ? | ? |
| E | Sky Smoke | ? | 3 [domain:abilities/brimstone-sky-smoke-charges] | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | ? | ? | ? | ? |
| X | Orbital Strike | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | ? | ? | ? | ? |

## Chamber

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Trademark | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | white-tinted area, mostly circular [domain:abilities/chamber-trademark-minimap-white-area]; compact icon (census 1) | ? | ? | the player called it Chamber's trip: is that Trademark? The area's radius? |
| Q | Headhunter | Hitscan | 8 [domain:abilities/chamber-headhunter-charges] | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
| E | Rendezvous | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REACTIVATE); movement | ? | nothing (census 1) | ? | ? | ? |
| X | Tour De Force | Hitscan | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |

## Clove

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Pick-me-up | ? | 1 [domain:abilities/clove-pick-me-up-charges] | none within a round [domain:abilities/clove-pick-me-up-charges] | second press (ACTIVATE); triggers on enemies | ? | ? | ? | ? | not castable in the range [domain:abilities/clove-c-and-x-need-a-target] |
| Q | Meddle | Class 3 Projectile | 1 [domain:abilities/clove-meddle-charges] | none within a round [domain:abilities/clove-meddle-charges] | cast on FIRE | ? | nothing [domain:abilities/clove-rouse] | ? | ? | ? |
| E | Ruse | Placement | 2 | 40 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | one bounded dark disc per cloud, at its placement [domain:abilities/clove-rouse] | ? | about 15 s on the minimap [domain:abilities/clove-ruse-minimap-duration] | ? |
| X | Not Dead Yet | Self-targeted | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (ACTIVATE, REACTIVATE) | ? | ? | ? | ? | not castable in the range [domain:abilities/clove-c-and-x-need-a-target]; does Clove dim on the scoreboard before it? [domain:rounds/scoreboard-dim-is-dead] |

## Cypher

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Trapwire | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | two anchor discs and a wire [domain:abilities/cypher-trapwire] | ? | ? | ? |
| Q | Cyber Cage | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); instant | ? | nothing (census 3) | ? | ? | ? |
| E | Spycam | Placement (Setup) Possession (Post-setup) Missile (Dart) | 1 | 60 s (Destroyed); 15 s (Recalled) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | piloted; second press (RE-USE) | ? | nothing (census 3) | ? | ? | ? |
| X | Neural Theft | Targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 3) | ? | ? | ? |

## Deadlock

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Mesh | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Sonic Sensor | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | ? | white-tinted area, mostly circular [domain:abilities/deadlock-sonic-sensor-minimap-white-area]; split {'compact_icon': 1, 'nothing': 1} (census 2) | ? | ? | the area's radius? Does a dim sensor keep it? |
| E | GravNet | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | yellow disc under 0.3 s at detonation [domain:abilities/deadlock-gravnet-detonation-flash] | ? | ? | ? |
| X | Annihilation | Beam | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | only on a hit, or a very brief flash? [domain:abilities/deadlock-annihilation-minimap] | ? | ? | X pips empty at equip [domain:abilities/deadlock-ult-tray-drop-at-equip] |

## Fade

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Prowler | Grounded Object | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE) | steered by the player: held, or piloted? [domain:abilities/fade-prowler-steered] | travelling icon [domain:abilities/fade-prowler-minimap-icon] | ? | ? | ? |
| Q | Seize | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE) | ? | nothing (census 1) | ? | ? | ? |
| E | Haunt | Class 2 Projectile | 1 | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE) | ? | a brief ring at the pulse [domain:abilities/pulse-scan-abilities] | ? | ? | a pulse scan, as Recon Bolt and the Stealth Drone [domain:abilities/pulse-scan-abilities] |
| X | Nightfall | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | wall segments (census 1) | ? | ? | ? |

## Gekko

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Mosh Pit | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | 20 s (granted by Globules) [domain:abilities/catalogue-restock-and-ult-points-confirmed]; also a pickup Gekko collects to restock within the round (a later change; it used to drop nothing) [domain:abilities/gekko-mosh-pit-drops-pickup] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Wingman | ? | 1 | Gekko recharges it by picking the used Wingman up (the harvest's "none" is withdrawn; all four Gekko abilities drop a pickup [domain:abilities/gekko-abilities-drop-pickups]) [domain:abilities/gekko-wingman-reclaim-or-expire] | cast on FIRE | ? | compact icon (census 1); planting, it carries the spike symbol, then a yellow pick-up disc [domain:abilities/gekko-wingman-plant-minimap] | ? | the used Wingman expires on a timer unless picked up (length unknown) [domain:abilities/gekko-wingman-reclaim-or-expire] | can plant the spike [domain:abilities/gekko-wingman-plants-spike] |
| E | Dizzy | ? | 1 | Gekko restocks it by picking up the thing it drops (the harvest's "none" is withdrawn) [domain:abilities/gekko-dizzy-drops-pickup] | triggers on enemies | ? | compact icon (census 1) | ? | ? | ? |
| X | Thrash | Possession | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips]; Gekko also restocks it by picking up the thing it drops [domain:abilities/gekko-thrash-drops-pickup] | second press (ACTIVATE) | ? | compact icon (census 1) | ? | ? | ? |

## Harbor

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Storm Surge | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | brief flash (census 1) | ? | ? | ? |
| Q | High Tide | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE); ends early on a press | ? | wall segments (census 1) | ? | ? | ? |
| E | Cove | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE, REACTIVATE) | ? | dark disc (census 1) | ? | ? | ? |
| X | Reckoning | ? | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | wall segments (census 1) | ? | ? | ? |

## Iso

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Contingency | Grounded Object | 1 [domain:abilities/iso-contingency-charges] | none within a round [domain:abilities/iso-contingency-charges] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Undercut | Missile | 1 [domain:abilities/iso-undercut-charges] | none within a round [domain:abilities/iso-undercut-charges] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| E | Double Tap | Self-targeted | 1 [domain:abilities/iso-double-tap-charges] | none within a round [domain:abilities/iso-double-tap-charges] | instant | ? | unsure (census 1) | ? | ? | ? |
| X | Kill Contract | Grounded AoE | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Jett

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Cloudburst | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE); instant | ? | dark disc (census 2) | ? | see [domain:abilities/jett-cloudburst-duration] | ? |
| Q | Updraft | Self-targeted | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant; movement | ? | nothing (census 1) | ? | ? | ? |
| E | Tailwind | Self-targeted | 1 | 2 kills (1 in Escalation) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE, RE-USE); movement | ? | nothing (census 1) | ? | ? | ? |
| X | Blade Storm | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## KAY/O

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | FRAG/ment | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | FLASH/drive | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | travelling icon [domain:abilities/kayo-flashdrive-minimap-icon] | ? | ? | ? |
| E | ZERO/point | Class 4 Projectile | 1 | 60 s (Restock removed in Replication) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | teal ring (census 1) | ? | ? | ? |
| X | NULL/cmd | Self-targeted (Buffs) Emission (Pulses) | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 1) | ? | ? | does a downed KAY/O dim on the scoreboard? [domain:rounds/scoreboard-dim-is-dead] |

## Killjoy

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Nanoswarm | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon, white triangle [domain:abilities/killjoy-nanoswarm-minimap-icon] | ? | ? | ? |
| Q | ALARMBOT | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; recallable | ? | dark disc with line art [domain:abilities/killjoy-alarmbot] | ? | ? | ? |
| E | TURRET | Placement | 1 | 60 s (Destroyed); 20 s (Recalled) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; recallable | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | nothing (census 1) | ? | ? | ? |
| X | Lockdown | ? | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | triggers on enemies | ? | compact icon (census 1) | ? | ? | ? |

## Miks

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | M-pulse | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 2) | ? | ? | ? |
| Q | Harmonize | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | Waveform | Placement | 2 | 40 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | dark disc [domain:abilities/miks-smoke-minimap-disc] | ? | see [domain:abilities/miks-smoke-duration] | ? |
| X | Bassquake | Grounded AoE | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Neon

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Fast Lane | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |
| Q | Relay Bolt | Class 5 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | compact icon (census 1) | ? | ? | ? |
| E | High Gear | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant; movement | ? | nothing (census 2) | an edge overlay, this or Overdrive? [domain:hud/neon-edge-overlay] | ? | ? |
| X | Overdrive | Hitscan | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | movement | ? | nothing (census 1) | an edge overlay, this or High Gear? [domain:hud/neon-edge-overlay] | ? | ? |

## Omen

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Shrouded Step | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 4, {'nothing': 3, 'unsure': 1}) | ? | ? | ? |
| Q | Paranoia | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | travelling icon [domain:abilities/omen-paranoia-minimap-icon] | ? | ? | ? |
| E | Dark Cover | Missile | 2 | 40 s after use [domain:abilities/omen-dark-cover-restock] | cast on FIRE | ? | dark disc in phases [domain:abilities/omen-dark-cover-minimap-phases] | ? | ? | ? |
| X | From the Shadows | Placement | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | movement | ? | other (census 2) | ? | ? | ? |

## Phoenix

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Blaze | Missile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE) | ? | orange wall [domain:abilities/phoenix-blaze] | ? | 8 s, from the cast or the wall's completion? [domain:abilities/phoenix-blaze-duration] | ongoing sound [domain:abilities/ability-sound-phases] |
| Q | Hot Hands | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 [domain:abilities/phoenix-hot-hands-charges] | none within a round [domain:abilities/phoenix-hot-hands-charges] | cast on FIRE | ? | nothing (census 2) | ? | ? | ongoing sound on the ground [domain:abilities/ability-sound-phases] |
| E | Curveball | Missile | 2 [domain:abilities/phoenix-curveball-charges] | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing [domain:abilities/phoenix-minimap-objects] | ? | ? | ? |
| X | Run it Back | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | nothing (census 1) | ? | about 10 s [domain:abilities/phoenix-run-it-back-expiry-flash] | X pips never fall; timer bar under the crosshair [domain:hud/ability-timer-bar] |

## Raze

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Boom Bot | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Blast Pack | Class 1 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE); instant | ? | nothing (census 2) | ? | ? | ? |
| E | Paint Shells | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| X | Showstopper | Missile | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Reyna

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Leer | Missile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); triggers on enemies | ? | travelling icon [domain:abilities/reyna-leer-minimap-icon] | ? | ? | ? |
| Q | Devour | ? | ? | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies; instant | ? | nothing (census 1) | ? | ? | ? |
| E | Dismiss | ? | ? | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | instant | ? | nothing (census 1) | ? | ? | ? |
| X | Empress | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | ? | ? | ? | ? |

## Sage

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Orb | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Slow Orb | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 2) | ? | ? | ? |
| E | Healing Orb | Targeted (Ally cast) Self-targeted (Self cast) | 1 | 45 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| X | Resurrection | Targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Skye

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Regrowth | ? | a resource bar [domain:abilities/skye-regrowth-resource-bar] | the pool does not refill [domain:abilities/skye-regrowth-resource-bar] | channelled (HOLD FIRE) | channelled [domain:abilities/skye-regrowth-channelled] | teal ring round Skye [domain:abilities/skye-regrowth-minimap-ring] | ? | ? | no tray drop [domain:abilities/skye-regrowth-no-tray-drop] |
| Q | Trailblazer | Possession | 1 [domain:abilities/skye-trailblazer-charges] | none within a round [domain:abilities/skye-trailblazer-charges] | piloted | controlled by the player, as the Owl Drone [domain:abilities/skye-trailblazer-piloted] | compact icon (census 2) | green view, shows through the minimap void [domain:hud/controlled-entity-view-tint] | ? | ? |
| E | Guiding Light | Missile | 2 [domain:abilities/skye-guiding-light-charges] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | guided path (HOLD FIRE); second press (RE-USE) | steered by the player: held, or piloted? [domain:abilities/skye-guiding-light-steered] | travelling bird icon [domain:abilities/skye-guiding-light-minimap-icon] | ? | ? | activation sound distinct from the cast [domain:abilities/ability-sound-phases] |
| X | Seekers | Grounded Object | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | tracks its enemy by itself [domain:abilities/skye-seekers-track-and-blind] | unsure (census 1) | ? | until destroyed or it reaches its enemy, who is blinded [domain:abilities/skye-seekers-track-and-blind]; despawns when its enemy dies? | one Seeker per living enemy [domain:abilities/skye-seekers-one-per-living-enemy] |

## Sova

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Owl Drone | ? | 1 [domain:abilities/sova-owl-drone-charges] | none within a round [domain:abilities/sova-owl-drone-charges] | piloted | piloted [domain:abilities/sova-owl-drone-piloted] | compact icon (census 2) | player: some; crop measured no hue shift [domain:hud/controlled-entity-view-tint] | ? | ? |
| Q | Shock Bolt | ? | 2 [domain:abilities/sova-shock-bolt-charges] | none within a round [domain:abilities/sova-shock-bolt-charges] | charged (HOLD FIRE) | ? | nothing [domain:abilities/sova-shock-bolt-minimap-none] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce] |
| E | Recon Bolt | Class 2/3/4/5 Projectile (based on charge) | 1 [domain:abilities/sova-recon-bolt-charges] | 60 s [domain:abilities/catalogue-restock-and-ult-points-confirmed] | charged (HOLD FIRE); triggers on enemies | ? | icon with a teal ring of the reveal range, kept the whole time [domain:abilities/sova-recon-bolt-minimap-ring] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce]; a pulse scan, 2 or 3 pulses over a few seconds [domain:abilities/pulse-scan-abilities] |
| X | Hunter's Fury | Beam | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (RE-USED); triggers on enemies | ? | teal line from Sova [domain:abilities/sova-hunters-fury-minimap-beam] | ? | ? | ? |

## Tejo

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Stealth Drone | Possession | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | piloted | piloted [domain:abilities/tejo-stealth-drone-piloted] | travelling icon; a brief ring at the pulse [domain:abilities/pulse-scan-abilities] | brown view; teal weight unmoved [domain:hud/controlled-entity-view-tint] | ? | a pulse scan, as Recon Bolt and Haunt [domain:abilities/pulse-scan-abilities] |
| Q | Special Delivery | Class 5 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | Guided Salvo | ? | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | rings [domain:abilities/tejo-guided-salvo-minimap-rings] | ? | ? | ? |
| X | Armageddon | ? | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | pale region (census 1) | ? | ? | ? |

## Veto

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Crosscut | Placement | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); movement | ? | split {'nothing': 1, 'compact_icon': 1} (census 2) | ? | ? | ? |
| Q | Chokehold | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | ? | white-tinted area, mostly circular [domain:abilities/veto-chokehold-minimap-white-area]; compact icon (census 1) | ? | ? | the player called it Veto's trip: is that Chokehold? The area's radius? |
| E | Interceptor | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (RE-USE) | ? | nothing (census 1) | ? | ? | ? |
| X | Evolution | Self-targeted | 7 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | instant | ? | ? | ? | ? | ? |

## Viper

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Snake Bite | Class 3 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 2) | ? | ? | ? |
| Q | Poison Cloud | ? | 1 | fuel refills over time [domain:abilities/viper-fuel-bar-recharges] | toggle (RE-USE, RE-USED, fuel) | placed, toggled on and off [domain:abilities/viper-poison-cloud-toggle] | dark disc; emitter outline while off [domain:abilities/viper-poison-cloud-emitter-outline] | ? | ? | ? |
| E | Toxic Screen | Class 6 Projectile | 1 | fuel refills over time [domain:abilities/viper-fuel-bar-recharges] | toggle (RE-USE, RE-USED, fuel) | ? | wall that grows [domain:abilities/viper-toxic-screen-minimap-growth] | ? | ? | ? |
| X | Viper's Pit | Placement | 9 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | ends early on a press | ? | nothing (census 2) | green tint inside [domain:abilities/viper-pit-tint] | ? | ? |

## Vyse

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Razorvine | Class 3 Projectile | 2 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATED) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon near Vyse [domain:abilities/vyse-razorvine-minimap-icon] | ? | ? | ? |
| Q | Shear | Placement | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | other (census 1) | ? | ? | ? |
| E | Arc Rose | Placement | 1 | 20 s (per use or recalled); 60 s (destroyed) [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REUSE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | teal ring (census 1) | ? | ? | ? |
| X | Steel Garden | Emission | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Waylay

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | Saturate | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Lightspeed | Self-targeted | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | movement | ? | nothing (census 1) | ? | ? | ? |
| E | Refract | Self-targeted | 1 | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (REACTIVATE); instant; movement | ? | nothing (census 1) | ? | ? | ? |
| X | Convergent Paths | Grounded AoE Self-targeted (Buff) | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |

## Yoru

| Slot | Ability | Deployment | Charges | Restock | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|---|
| C | FAKEOUT | ? | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | BLINDSIDE | Class 3 Projectile | 1 | none [domain:abilities/catalogue-restock-and-ult-points-confirmed] | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | GATECRASH | Grounded Object (Mobile tether) Placement (Stationary tether) | 2 | 2 kills [domain:abilities/catalogue-restock-and-ult-points-confirmed] | second press (ACTIVATE); movement | ? | travelling icon [domain:abilities/yoru-gatecrash-minimap-icon] | ? | ? | ? |
| X | DIMENSIONAL DRIFT | ? | 8 ult points [domain:abilities/catalogue-restock-and-ult-points-confirmed] | ult pips [domain:abilities/ult-charge-pips] | second press (REACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
