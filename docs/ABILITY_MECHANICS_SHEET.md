# Ability mechanics sheet

One row per ability of every agent in the catalogue, for the player to fill.
Mechanics are unique per ability [domain:abilities/ability-rules-are-unique]:
nothing here is inferred from a sibling ability. A cell holds a value only
where a source says it, with the domain fact or the census beside it; every
other cell is `?`. Replace a `?` with the answer, or answer in chat by agent
and ability; each answer becomes a fact in `domain/abilities.toml` or
`domain/hud.toml`, and this sheet is regenerated from them.

Columns. *Deployment* and *charges* come from the catalogue
(`<store>/reference/abilities.json`, web-sourced, sometimes wrong).
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

## Astra

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Gravity Well | Targeted | 1 | second press (ACTIVATE) | ? | other (census 1) | ? | ? | ? |
| Q | Nova Pulse | ? | ? | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
| E | Nebula  / Dissipate | ? | ? | second press (ACTIVATE) | ? | dark disc [domain:abilities/astra-nebula-minimap-disc] | ? | ? | ? |
| X | Astral Form / Cosmic Divide | ? | ? | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |

## Breach

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Aftershock | Placement | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Flashpoint | Placement | 2 | cast on FIRE | ? | nothing (census 2) | ? | ? | ? |
| E | Fault Line | Grounded AoE | 1 | charged (HOLD FIRE) | ? | nothing (census 1) | ? | ? | ? |
| X | Rolling Thunder | Grounded AoE | ? | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |

## Brimstone

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Stim Beacon | ? | 1 | instant | ? | ? | ? | ? | ? |
| Q | Incendiary | ? | 1 | cast on FIRE | ? | ? | ? | ? | ? |
| E | Sky Smoke | ? | 3 | cast on FIRE | ? | ? | ? | ? | ? |
| X | Orbital Strike | ? | ? | cast on FIRE | ? | ? | ? | ? | ? |

## Chamber

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Trademark | ? | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Headhunter | Hitscan | 8 | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
| E | Rendezvous | ? | 1 | second press (REACTIVATE); movement | ? | nothing (census 1) | ? | ? | ? |
| X | Tour De Force | Hitscan | ? | second press (ACTIVATE) | ? | nothing (census 1) | ? | ? | ? |

## Clove

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Pick-me-up | ? | 1 | second press (ACTIVATE); triggers on enemies | ? | ? | ? | ? | not castable in the range [domain:abilities/clove-c-and-x-need-a-target] |
| Q | Meddle | Class 3 Projectile | 1 | cast on FIRE | ? | nothing [domain:abilities/clove-rouse] | ? | ? | ? |
| E | Ruse | Placement | 2 | cast on FIRE | ? | bounded dark discs [domain:abilities/clove-rouse] | ? | about 15 s on the minimap [domain:abilities/clove-ruse-minimap-duration] | ? |
| X | Not Dead Yet | Self-targeted | ? | second press (ACTIVATE, REACTIVATE) | ? | ? | ? | ? | not castable in the range [domain:abilities/clove-c-and-x-need-a-target]; does Clove dim on the scoreboard before it? [domain:rounds/scoreboard-dim-is-dead] |

## Cypher

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Trapwire | Placement | 2 | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | two anchor discs and a wire [domain:abilities/cypher-trapwire] | ? | ? | ? |
| Q | Cyber Cage | ? | 2 | second press (ACTIVATE); instant | ? | nothing (census 3) | ? | ? | ? |
| E | Spycam | Placement (Setup) Possession (Post-setup) Missile (Dart) | 1 | piloted; second press (RE-USE) | ? | nothing (census 3) | ? | ? | ? |
| X | Neural Theft | Targeted | ? | instant | ? | nothing (census 3) | ? | ? | ? |

## Deadlock

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Mesh | ? | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Sonic Sensor | ? | 2 | triggers on enemies | ? | split {'compact_icon': 1, 'nothing': 1} (census 2) | ? | ? | ? |
| E | GravNet | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | cast on FIRE | ? | yellow disc under 0.3 s at detonation [domain:abilities/deadlock-gravnet-detonation-flash] | ? | ? | ? |
| X | Annihilation | Beam | ? | cast on FIRE | ? | only on a hit, or a very brief flash? [domain:abilities/deadlock-annihilation-minimap] | ? | ? | X pips empty at equip [domain:abilities/deadlock-ult-tray-drop-at-equip] |

## Fade

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Prowler | Grounded Object | 2 | guided path (HOLD FIRE) | ? | travelling icon [domain:abilities/fade-prowler-minimap-icon] | ? | ? | ? |
| Q | Seize | ? | 1 | second press (RE-USE) | ? | nothing (census 1) | ? | ? | ? |
| E | Haunt | Class 2 Projectile | 1 | second press (RE-USE) | ? | nothing (census 1) | ? | ? | ? |
| X | Nightfall | ? | ? | triggers on enemies | ? | wall segments (census 1) | ? | ? | ? |

## Gekko

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Mosh Pit | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Wingman | ? | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| E | Dizzy | ? | 1 | triggers on enemies | ? | compact icon (census 1) | ? | ? | ? |
| X | Thrash | Possession | ? | second press (ACTIVATE) | ? | compact icon (census 1) | ? | ? | ? |

## Harbor

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Storm Surge | ? | 1 | cast on FIRE | ? | brief flash (census 1) | ? | ? | ? |
| Q | High Tide | Missile | 1 | guided path (HOLD FIRE); ends early on a press | ? | wall segments (census 1) | ? | ? | ? |
| E | Cove | ? | 1 | second press (ACTIVATE, REACTIVATE) | ? | dark disc (census 1) | ? | ? | ? |
| X | Reckoning | ? | ? | triggers on enemies | ? | wall segments (census 1) | ? | ? | ? |

## Iso

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Contingency | Grounded Object | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Undercut | Missile | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| E | Double Tap | Self-targeted | 1 | instant | ? | unsure (census 1) | ? | ? | ? |
| X | Kill Contract | Grounded AoE | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Jett

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Cloudburst | ? | 2 | guided path (HOLD FIRE); instant | ? | dark disc (census 2) | ? | see [domain:abilities/jett-cloudburst-duration] | ? |
| Q | Updraft | Self-targeted | 1 | instant; movement | ? | nothing (census 1) | ? | ? | ? |
| E | Tailwind | Self-targeted | 1 | second press (ACTIVATE, RE-USE); movement | ? | nothing (census 1) | ? | ? | ? |
| X | Blade Storm | ? | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## KAY/O

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | FRAG/ment | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | FLASH/drive | ? | 2 | cast on FIRE | ? | travelling icon [domain:abilities/kayo-flashdrive-minimap-icon] | ? | ? | ? |
| E | ZERO/point | Class 4 Projectile | 1 | cast on FIRE | ? | teal ring (census 1) | ? | ? | ? |
| X | NULL/cmd | Self-targeted (Buffs) Emission (Pulses) | ? | instant | ? | nothing (census 1) | ? | ? | does a downed KAY/O dim on the scoreboard? [domain:rounds/scoreboard-dim-is-dead] |

## Killjoy

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Nanoswarm | ? | 2 | second press (ACTIVATE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon, white triangle [domain:abilities/killjoy-nanoswarm-minimap-icon] | ? | ? | ? |
| Q | ALARMBOT | ? | 1 | triggers on enemies; recallable | ? | dark disc with line art [domain:abilities/killjoy-alarmbot] | ? | ? | ? |
| E | TURRET | Placement | 1 | triggers on enemies; recallable | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | nothing (census 1) | ? | ? | ? |
| X | Lockdown | ? | ? | triggers on enemies | ? | compact icon (census 1) | ? | ? | ? |

## Miks

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | M-pulse | Class 3 Projectile | 2 | cast on FIRE | ? | compact icon (census 2) | ? | ? | ? |
| Q | Harmonize | ? | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | Waveform | Placement | 2 | cast on FIRE | ? | dark disc [domain:abilities/miks-smoke-minimap-disc] | ? | see [domain:abilities/miks-smoke-duration] | ? |
| X | Bassquake | Grounded AoE | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Neon

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Fast Lane | Missile | 1 | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |
| Q | Relay Bolt | Class 5 Projectile | 1 | instant | ? | compact icon (census 1) | ? | ? | ? |
| E | High Gear | ? | 1 | instant; movement | ? | nothing (census 2) | an edge overlay, this or Overdrive? [domain:hud/neon-edge-overlay] | ? | ? |
| X | Overdrive | Hitscan | ? | movement | ? | nothing (census 1) | an edge overlay, this or High Gear? [domain:hud/neon-edge-overlay] | ? | ? |

## Omen

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Shrouded Step | Placement | 2 | movement | ? | nothing (census 4, {'nothing': 3, 'unsure': 1}) | ? | ? | ? |
| Q | Paranoia | Missile | 1 | cast on FIRE | ? | travelling icon [domain:abilities/omen-paranoia-minimap-icon] | ? | ? | ? |
| E | Dark Cover | Missile | 2 | cast on FIRE | ? | dark disc in phases [domain:abilities/omen-dark-cover-minimap-phases] | ? | ? | ? |
| X | From the Shadows | Placement | ? | movement | ? | other (census 2) | ? | ? | ? |

## Phoenix

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Blaze | Missile | 1 | guided path (HOLD FIRE) | ? | orange wall [domain:abilities/phoenix-blaze] | ? | 8 s, from the cast or the wall's completion? [domain:abilities/phoenix-blaze-duration] | ongoing sound [domain:abilities/ability-sound-phases] |
| Q | Hot Hands | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | cast on FIRE | ? | nothing (census 2) | ? | ? | ongoing sound on the ground [domain:abilities/ability-sound-phases] |
| E | Curveball | Missile | 2 | cast on FIRE | ? | nothing [domain:abilities/phoenix-minimap-objects] | ? | ? | ? |
| X | Run it Back | Self-targeted | ? | instant | ? | nothing (census 1) | ? | about 10 s [domain:abilities/phoenix-run-it-back-expiry-flash] | X pips never fall; timer bar under the crosshair [domain:hud/ability-timer-bar] |

## Raze

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Boom Bot | ? | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | Blast Pack | Class 1 Projectile | 2 | second press (RE-USE); instant | ? | nothing (census 2) | ? | ? | ? |
| E | Paint Shells | ? | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| X | Showstopper | Missile | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Reyna

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Leer | Missile | 2 | second press (ACTIVATE); triggers on enemies | ? | travelling icon [domain:abilities/reyna-leer-minimap-icon] | ? | ? | ? |
| Q | Devour | ? | ? | triggers on enemies; instant | ? | nothing (census 1) | ? | ? | ? |
| E | Dismiss | ? | ? | instant | ? | nothing (census 1) | ? | ? | ? |
| X | Empress | Self-targeted | ? | instant | ? | ? | ? | ? | ? |

## Sage

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Barrier Orb | Placement | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Slow Orb | Class 3 Projectile | 2 | movement | ? | nothing (census 2) | ? | ? | ? |
| E | Healing Orb | Targeted (Ally cast) Self-targeted (Self cast) | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| X | Resurrection | Targeted | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Skye

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Regrowth | ? | 1 | channelled (HOLD FIRE) | channelled (player 2026-09-26) | teal ring round Skye [domain:abilities/skye-regrowth-minimap-ring] | ? | ? | no tray drop [domain:abilities/skye-regrowth-no-tray-drop] |
| Q | Trailblazer | Possession | 1 | piloted | piloted by the player | compact icon (census 2) | green view, shows through the minimap void [domain:hud/controlled-entity-view-tint] | ? | ? |
| E | Guiding Light | Missile | 2 | guided path (HOLD FIRE); second press (RE-USE) | ? | travelling bird icon [domain:abilities/skye-guiding-light-minimap-icon] | ? | ? | activation sound distinct from the cast [domain:abilities/ability-sound-phases] |
| X | Seekers | Grounded Object | ? | cast on FIRE | ? | unsure (census 1) | ? | ? | ? |

## Sova

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Owl Drone | ? | 1 | piloted | piloted by the player | compact icon (census 2) | player: some; crop measured no hue shift [domain:hud/controlled-entity-view-tint] | ? | ? |
| Q | Shock Bolt | ? | 2 | charged (HOLD FIRE) | ? | nothing [domain:abilities/sova-shock-bolt-minimap-none] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce] |
| E | Recon Bolt | Class 2/3/4/5 Projectile (based on charge) | 1 | charged (HOLD FIRE); triggers on enemies | ? | teal ring at the landing [domain:abilities/sova-recon-bolt-minimap-ring] | ? | ? | charged, bounce toggled [domain:abilities/sova-bolt-charge-and-bounce] |
| X | Hunter's Fury | Beam | ? | second press (RE-USED); triggers on enemies | ? | teal line from Sova [domain:abilities/sova-hunters-fury-minimap-beam] | ? | ? | ? |

## Tejo

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Stealth Drone | Possession | 1 | piloted | piloted by the player | compact icon (census 1) | brown view; teal weight unmoved [domain:hud/controlled-entity-view-tint] | ? | ? |
| Q | Special Delivery | Class 5 Projectile | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | Guided Salvo | ? | 2 | cast on FIRE | ? | rings [domain:abilities/tejo-guided-salvo-minimap-rings] | ? | ? | ? |
| X | Armageddon | ? | ? | cast on FIRE | ? | pale region (census 1) | ? | ? | ? |

## Veto

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Crosscut | Placement | 2 | second press (ACTIVATE); movement | ? | split {'nothing': 1, 'compact_icon': 1} (census 2) | ? | ? | ? |
| Q | Chokehold | Class 2 Projectile Class 0.7 Projectile (Underhand) | 1 | triggers on enemies | ? | compact icon (census 1) | ? | ? | ? |
| E | Interceptor | ? | 1 | second press (RE-USE) | ? | nothing (census 1) | ? | ? | ? |
| X | Evolution | Self-targeted | ? | instant | ? | ? | ? | ? | ? |

## Viper

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Snake Bite | Class 3 Projectile | 1 | cast on FIRE | ? | nothing (census 2) | ? | ? | ? |
| Q | Poison Cloud | ? | 1 | toggle (RE-USE, RE-USED, fuel) | placed, toggled on and off [domain:abilities/viper-poison-cloud-toggle] | dark disc; emitter outline while off [domain:abilities/viper-poison-cloud-emitter-outline] | ? | ? | ? |
| E | Toxic Screen | Class 6 Projectile | 1 | toggle (RE-USE, RE-USED, fuel) | ? | wall that grows [domain:abilities/viper-toxic-screen-minimap-growth] | ? | ? | ? |
| X | Viper's Pit | Placement | ? | ends early on a press | ? | nothing (census 2) | green tint inside [domain:abilities/viper-pit-tint] | ? | ? |

## Vyse

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Razorvine | Class 3 Projectile | 2 | second press (ACTIVATED) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | dark icon near Vyse [domain:abilities/vyse-razorvine-minimap-icon] | ? | ? | ? |
| Q | Shear | Placement | 1 | triggers on enemies | placed; activates on enemy proximity (player 2026-09-26) [domain:abilities/placed-then-activated] | other (census 1) | ? | ? | ? |
| E | Arc Rose | Placement | 1 | second press (REUSE) | placed, then a second press activates (player 2026-09-26) [domain:abilities/placed-then-activated] | teal ring (census 1) | ? | ? | ? |
| X | Steel Garden | Emission | ? | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |

## Waylay

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | Saturate | ? | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| Q | Lightspeed | Self-targeted | 1 | movement | ? | nothing (census 1) | ? | ? | ? |
| E | Refract | Self-targeted | 1 | second press (REACTIVATE); instant; movement | ? | nothing (census 1) | ? | ? | ? |
| X | Convergent Paths | Grounded AoE Self-targeted (Buff) | ? | cast on FIRE | ? | wall segments (census 1) | ? | ? | ? |

## Yoru

| Slot | Ability | Deployment | Charges | Description says | Activation | Minimap | Overlay | Duration | Notes |
|---|---|---|---|---|---|---|---|---|---|
| C | FAKEOUT | ? | 1 | cast on FIRE | ? | compact icon (census 1) | ? | ? | ? |
| Q | BLINDSIDE | Class 3 Projectile | 1 | cast on FIRE | ? | nothing (census 1) | ? | ? | ? |
| E | GATECRASH | Grounded Object (Mobile tether) Placement (Stationary tether) | 2 | second press (ACTIVATE); movement | ? | travelling icon [domain:abilities/yoru-gatecrash-minimap-icon] | ? | ? | ? |
| X | DIMENSIONAL DRIFT | ? | ? | second press (REACTIVATE) | ? | nothing (census 1) | ? | ? | ? |
