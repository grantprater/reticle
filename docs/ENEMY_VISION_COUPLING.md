# Enemy icons and team vision

A plan, proposed 2026-09-30. It builds nothing.

The request: use the team's vision as a prior for where an enemy icon
appears (at a cone's edge, in floor just lit, inside a reveal), keep a
whole-widget search for drawings that show whatever the vision, and let
enemy detections, the drawn light and the ally poses correct one another
through shared invariants, as icon pose and drawn cone do for one facing
(E12 in `docs/STATISTICAL_ADJUDICATOR.md`).

No reader does this today: `minimap_objects` searches the whole slab, and
neither `lighting` nor `team_vision` sees an enemy.

## 1. The invariants

Each invariant cites a fact or names a question for the player (section 6).
"The light" means the drawn light, never the raycast
[domain:minimap/vision-gate].

- **I1, the gate.** An enemy is drawn only inside team vision, inside a
  reveal, or for a while after it leaves vision
  [domain:minimap/vision-gate] [domain:minimap/vision-trailing-persistence].
  That while, W, is unmeasured, and no rule may assume it.
- **I2, entry.** A new enemy track begins at the light's frontier, in floor
  just lit, or inside a reveal. This is derived from I1 and continuous
  motion, not a game fact; a teleport breaks it
  [domain:abilities/minimap-dash-or-teleport-trace].
- **I3, exit.** An enemy that leaves vision becomes a red "?" at its last
  place one frame after its icon ends [domain:minimap/last-known-mark]
  [domain:minimap/last-known-mark-timing]. The light left that place about
  W before the swap. An icon that ends with its place still lit and no "?"
  is a death or a reader's miss.
- **I4, death.** A gunfire kill says a teammate saw the victim, and an enemy X
  shows only while its place is in vision [domain:minimap/enemy-death-mark]
  [domain:minimap/death-mark-persistence]. The icon becomes the X
  [domain:minimap/death-icon-becomes-mark]. Utility kills of a "?" may leave
  no X until the place is seen [domain:minimap/unseen-utility-death-mark].
- **I5, other point witnesses.** A dropped spike shows only in vision and
  otherwise becomes a yellow "?" [domain:minimap/enemy-spike-ground-vision];
  a "spotted" callout places an enemy and draws nothing
  [domain:minimap/spotted-callouts-draw-nothing].
- **I6, enemy drawings.** An enemy's ability drawing shows inside vision,
  plus the ten always-visible drawings everywhere
  [domain:minimap/ability-drawings-both-sides]
  [domain:abilities/killjoy-lockdown-global-minimap]
  [domain:abilities/reyna-leer-global-minimap]
  [domain:abilities/fade-haunt-global-minimap]
  [domain:abilities/gekko-thrash-global-minimap]
  [domain:abilities/sage-barrier-orb-global-minimap]
  [domain:abilities/deadlock-barrier-mesh-global-minimap]
  [domain:abilities/sova-hunters-fury-global-minimap]
  [domain:abilities/brimstone-orbital-strike-global-minimap]
  [domain:abilities/astra-cosmic-divide-global-minimap]
  [domain:abilities/viper-toxic-screen-global-minimap],
  in each side's colour [domain:minimap/ability-drawing-colour-by-side].
  A reveal shows players only
  [domain:minimap/vision-gate]. Enemy smokes are never drawn and cut the
  team's light [domain:abilities/enemy-smokes-not-on-minimap]
  [domain:minimap/enemy-smokes-block-cones].
- **I7, facing.** A cone spans a fixed angle about the teardrop's facing
  from about the icon's centre, each ray stopping at the first edge
  [domain:minimap/cone-rays-stop-at-first-edge]
  [domain:minimap/cone-origin-near-centre], and the light is binary with no
  range limit [domain:minimap/vision-light-binary]. An enemy that appears on
  one ally's edge ray, with no other source of light there, bounds that
  ally's facing. Whether an enemy's body stops a ray is Q1.
- **I8, reveals.** Recon Bolt, Haunt and the Stealth Drone pulse and reveal
  the enemies in the device's line of sight within the range their ring
  draws [domain:abilities/pulse-scan-abilities]
  [domain:abilities/sova-recon-bolt-minimap-ring]. The reveal area is the
  ring's disc cut by a raycast from the device over the baked geometry. The
  catalogue says other abilities reveal too; each is its own question
  [domain:abilities/ability-rules-are-unique] (Q3).
- **I9, dark floor.** An enemy drawn on floor read dark, beyond W and outside
  every known reveal, means an unrecorded reveal, light the vision reader
  missed, or a false enemy. The enemy lobe is translucent
  [domain:minimap/enemy-lobe-translucent], so the light read beside an enemy
  needs the icon's own pixels masked.

## 2. Both directions

| Observation | Predicts | A violation implicates |
|---|---|---|
| Enemy at p, t | p lit within [t - W, t], or in a reveal (I1) | the light reader, the enemy reader, or an unknown reveal (I9) |
| Floor newly lit, or the frontier | where the enemy search looks first (I2) | nothing: a prior narrows a search and confirms nothing |
| Track born deep in old light | an earlier miss by the enemy reader (I2) | the enemy reader, at the time the floor lit |
| Icon ends in light, no "?" | an X, a killfeed death (I3, I4) | the enemy reader, the death owner, or the light |
| "?" onset at p | p went dark about W earlier (I3) | the light reader if p stays lit; it also measures W |
| Enemy X or spike glyph shown | its place lit (I4, I5) | the light reader if the place reads dark |
| Enemy on one ally's edge ray | that ally's facing (I7) | the teardrop, if the prior and the light agree against it |

Each violation stores one row: point, time, the light now and over the
preceding window, candidate reveals, the ally cones reaching the point,
each witness's version, and the class. Agreements are counted, never
scored: they are consistency, not accuracy.

## 3. The circularity guard

E11 let the light choose the ring fit's lobe and then scored the lobe
against the same light. Here the same error has three forms, each barred:

1. **A prior that places a search never confirms what it predicted.** An
   enemy found by a search narrowed to the frontier `rests_on` the vision
   it read. It is no witness of that light, and the facing term (I7) may
   not use it for the ally whose cone shaped the search. Only detections
   from the audit path count as independent.
2. **The audit is fixed in advance.** A whole-widget search runs on
   opportunity-gated samples at a cadence chosen before any run, stored
   apart, until the prior's efficacy is significant (`AGENTS.md`, "Continue
   the prior"). A search triggered by surprise is no audit sample. The
   always-visible drawings (I6) keep the whole-widget search for good.
3. **Weigh once.** Each witness pair enters one likelihood once. A facing
   that the light already informed (E12's fusion) does not count the
   enemy's frontier as new evidence when the frontier is that same light.

Scores come only from the player's held-out labels: the enemy and "?" marks
in `labels/minimap`, `enemy_lane_331_20260930` and
`enemy_fix_check_20260930`, and the facing sets of 2026-09-29. A label set
drawn with the light in its draw cannot score the light.

## 4. Where it lives

- **Readers stay raw.** `minimap_objects`, `lighting`, `team_vision` and the
  death owner keep their outputs and stamps; none reads the coupling.
- **One adjudicator**, pure over stored streams, with its own version stamp,
  ownership entry and layer. It reads `minimap_object`, `enemy_track`,
  `team_vision`, `death`, the spike and ability observations, and writes
  the violation rows and per-track standings. It names nobody.
- **A prerequisite.** `team_vision` stores the cones' union, not the drawn
  light, so a stored drawn-light product (the raw decision
  `lighting.clean_lit` rebuilds) comes first.
- **The prior is a reader input, ordered by time.** The enemy search at
  frame t reads the adjudicated vision of earlier frames only, as
  `team_vision` orders its smoke input; nothing iterates to a fixed point.
- **No joint fit.** The coupling is a prior plus a surprise path with
  disagreements stored, the form `docs/PRIOR_DRIVEN_READERS.md` gives a
  full-search reader. It is one strand of `docs/SCENE_MODEL.md`'s stage 5
  mesh and needs no stage 3 tint.

## 5. First measurement

Session a06f04a0059f (`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`),
Ascent, 465 px widget; crop cache only, nothing written to the store.

**Inputs.** `reticle plan` reports `team_vision` stale here (stored
`team-vision-0.3.0`, current `team-vision-0.6.0`). It was not refreshed,
and the run reads no cone: it reads the drawn light (`lighting-0.3.0`,
current) from the crop cache. The player's enemy and "?" marks for this
session lie in `labels/minimap`; the 2026-09-30 enemy label files hold none.
No reveal observation is stored here (no resolved scanner on the team;
`ability_shape` ran for the self agent only), so the reveal class is null
with that reason.

**Method.** For each mark, the light in an annulus of 10 to 22 px round it,
saturated pixels (icons, tips, marks) dilated and excluded, over floor the
lighting reference can read. Classes: inside (lit share at least 0.85),
edge (lit share above 0.1), near (lit within 30 px), dark, and unknown
(under 0.4 of the annulus readable). "Newly lit" compares the frame
0.5 s earlier. The same classes apply to every `enemy_track` first
observation, which is detector output and so measures consistency only.

**Predictions, stated before the run.** P1: at most a fifth of readable
enemy marks are dark. P2: at most half of readable "?" marks are inside.
P3: at least three in five readable first appearances are on an edge or
newly lit. They are not yet logged in `notes/predictions.jsonl`.

**Instrument.** The first pass counted each icon's rim and tip as unlit
floor, which capped every lit share. Masking saturated pixels removed the
cap; inspected crops show the light's edge crossing the labelled icon.

**Result.** P1, P2 and P3 held. The surprise: almost no labelled enemy
stood deep inside light; most stood on a lit edge, and no "?" stood inside.
Many marks sat on floor the reference cannot read. Both dark labelled
enemies stand on site-tinted floor, where `docs/SCENE_MODEL.md` already
finds unexplained light. The run was not recorded as a metric, so this
document quotes no figure; a recorded run comes before any decision.

**Next.** Measure W from the "?" marks: the time from each place's last
lit frame to its swap (I3).

## 6. Questions for the player

No fact answers these.

- **Q1.** Does an enemy's body stop a teammate's drawn light? The first
  measurement found labelled enemies on a light edge far more often than
  inside.
- **Q2.** Is a revealed enemy's place drawn as light? How long does a
  revealed enemy stay drawn after the pulse?
- **Q3.** The catalogue says Trapwire, Neural Theft, Hunter's Fury, the
  Spycam's and Owl Drone's darts, and Nightfall's marks reveal or mark
  enemies. For each: does the enemy show on our minimap, where, and for how
  long?

W itself is measured, not asked (section 5, "Next"). Whether a drone's cone
lights the floor is already asked on `docs/ABILITY_MECHANICS_SHEET.md`
[domain:abilities/piloted-drones-have-cones].
