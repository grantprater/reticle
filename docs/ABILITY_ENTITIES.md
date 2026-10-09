# Ability entities: one model for every ability instance and its effects

A plan, proposed 2026-10-09. The player asked that ally and enemy abilities
become first-class entities beside the players, ending the fragmentation.
Rules live in [AGENTS.md](../AGENTS.md); this plan cites them and restates
none. It builds on [ENTITY_STATE.md](ENTITY_STATE.md) section 9 (ability
children), amends it where noted, and takes the place of the ability
sections of the plans in section 1.5. The player answered its six questions
on 2026-10-09 (section 6); the model below carries the answers.

State of the work it builds on, on master 4a8298d:

- **B1 has landed.** `reticle/slot_state.py` is the one belief owner for
  every slot, keyed `(kind, id)` (`EntityRow`, with `side`, `owner` and
  `slot`), with `stack_entities` joining per-kind blocks and `region_at`
  answering one instant. Section 5 names what the child and effect kinds
  still need from it.
- **Harness step 9 has merged**: `replay_abilities score` is folded into
  `prototypes/question_acceptance.py`. The harness core (`truth_under` and
  its join) is being promoted into `reticle/` now, which gives
  `replay-truth-under` an owner.
- **The doctor ratchets** (`reticle/ratchets.py`: the `Gate` declaration,
  CONVERT, ROUNDSCOPE and the strict PROMOTE) live on a branch that is being
  fixed. The ABILITY ratchet of section 4 joins that module once it lands.

## 0. Summary

An ability instance is a **child entity** of the slot model, and what it
does to players is an **effect entity**. `slot_state` owns both, as it owns
the player slots: one key scheme, one lifecycle machine, one belief law, one
identity path through `adjudication.identity`, one lane, one scorer. A child
opens at the first witness of a cast, joins later witnesses of the same
instance, and ends by evidence, by its ability's own facts, or at the round
barrier, which nothing crosses [domain:rounds/no-ability-crosses-round-barrier].
An effect opens when a child or a cast acts on a target set (a buff, a
reveal, a blind, a kill or an assist) and ends by its own facts or at the
same barrier. Readers and channel owners keep their jobs; each becomes a
declared input of the child owner. A doctor ratchet, ABILITY, lists every
fragment that has not yet become an input and errors on any new one.

The migration runs in eight steps: clear the ground, enforce, the player's
own children, the team's children and `ability-owner`, the enemy's children,
kits for every slot, gates, and close.

## 1. Inventory of the fragmentation

Taken on master 9bacd17 from the code, `ownership.toml`, `plan.py`,
`architecture.toml`, `documents.toml` and `reticle doctor` (0 errors), and
updated on 4a8298d where step 0 or merged work changed a row. "Fate" names
what each fragment becomes in section 3.

### 1.1 Readers: pixels or audio in, observations out (`reticle/`)

| Fragment | Produces | Consumers | Stamp | Answers | Fate |
|---|---|---|---|---|---|
| `tray` | `tray_drop` (drops, fills, segment classes) | `ability_timeline`, `adjudication.ability_state` | `tray-0.4.0` (fill `tray-0.1.0`, segment `tray-segment-0.1.0`) | `tray-drop` | reader of the kit owner |
| `tray_icons` | per-slot catalogue icon scores | `adjudication.tray_kit` | catalogue digest only | `tray-icon` | reader of the kit owner |
| `tray_countdown` | `tray_countdown` numerals | nothing reads it yet | `tray-countdown-0.1.0` | `tray-restock-countdown` | reader of the kit owner |
| `ult_lines` | `ult_line` peaks | `adjudication.ult_cast` | `ult-line-0.2.0` | `ult-line` | reader |
| `minimap_dark` | `minimap_dark` grey masks, 4 Hz | `adjudication.smokes` | `minimap-dark-0.2.0` | `minimap-dark` | reader; CONVERT legacy; its rebuild is declared since step 0 (1.6) |
| `ability_scan` | `ability_gate`, `ability_fit`, `ability_wall`, `ability_shape_scan`, `ability_shape_audit`, 2 Hz | prototypes only | `ability-gate-0.2.0`, `ability-fit-0.2.0`, `ability-wall-0.1.0`, `ability-shape-0.4.0` | `ability-gate` | reader; no owner reads its fits (gap) |
| `ability_shapes` (`reticle ability-shapes`) | `ability_shape`, fits after each of the player's casts | `view_events`, `question_acceptance` | `ability-shape-0.4.0` | `ability-shape` | reader; merges with `ability_fit` under the gate (step 6) |
| `ability_candidates` | descriptor supply per crop | `ability_scan` through `cli` | `ability-candidates-0.2.0` | `ability-candidates` (`names_agents`) | the per-ability geometry table (ENTITY_STATE section 11) |
| `ability_icons` | `ability_icon` dark-disc proposals and verify rows, 2 Hz | `minimap_glyph`, `adjudication.ability.disc_tracks` | `icon-proposer-0.3.0` | `ability-icon` | reader |
| `minimap_glyph` | `ability_glyph` texture scores, 2 Hz | `disc_tracks`, `adjudication.ability_glyph`, harness step 7 | `ability-glyph-0.5.0` and the glyph bank stamp | `ability-glyph` | reader |
| `clove_circle` | `clove_circle` rim fits in a dead Clove's windows | `adjudication.smoke_owner` | `clove-circle-0.4.0` | `clove-circle` | reader; already gated by spans |
| `lighting` (`reticle ability-light`) | `ability_light` lit and dark masks at ability candidates' instants | `adjudication.ability.light_refusals` | `ability-light-0.2.0` | `drawn-light` | kept until its consumer retires in step 3 (see step 0) |
| `killfeed` weapon descriptor | `killfeed_weapon` | `adjudication.weapon` | killfeed weapon stamp | `killfeed-weapon-descriptor` | reader of an effect witness |
| `killfeed_assist` | assist panel portraits and icons | `adjudication.assist` | `killfeed-assist-0.6.1` | `killfeed-assist-panel` | reader of an effect witness |
| `minimap.detect_ability_discs`, `detect_ability_walls`, `detect_trapwire_anchors` | nothing stored | nothing (doctor UNCALLED) | `minimap-0.9.0` | `ability-detection` | retire; `ability_icons` and `ability_shapes` replaced them |

### 1.2 Channel owners: one channel's continuity and verdicts (`reticle/`)

| Fragment | Produces | Consumers | Stamp | Answers | Fate |
|---|---|---|---|---|---|
| `ability_timeline.player_tray_casts` | the player's cast verdict on each drop (`tray_drop.player_cast`) | `ability_state`, `ult_cast`, `smoke_owner` | `player-cast-0.14.0` | `ability-cast` (`partial` since step 0) | the tray channel's cast witness; its decision moves into the kit owner |
| `ability_timeline.build_timeline` | the `ability-timeline` analysis bundle over demos | `adjudication.ability.build_entities` | `ability-timeline-0.1.0` | `ability-cast` | retire with milestone C; step 0 dropped its `--materialize` option, the module's only import of `prototypes/` |
| `ability_timeline.dead_ruse_casts` | `dead_ruse_cast` | `plan`, `prototypes/own_cast_gate_eval.py` | `dead-ruse-0.2.0` | `ability-cast` | becomes a query over the player's Ruse children |
| `adjudication.ability_state` | `ability_state`: the player's four slots, charges, equipped, castable | `cli`, `view_events`, `question_acceptance` | `ability-state-0.10.0` | `ability-state` | the **kit owner**, kept; extended to every slot (step 5) |
| `adjudication.tray_kit` | `tray_kit` spans and `tray_kit_identity` | `ability_timeline`, `ability_state`, `ability_glyph` | `tray-kit-0.1.0` | `tray-kit` | channel owner; feeds kits and the spectated teammate's children |
| `adjudication.ability_audio`, `ability_audio_fit` | kit scores on the player's drops | `ability_timeline` | `ability-audio-0.6.0`, params `ability-audio-params-0.2.8` | `ability-audio` | witness of a child's kind |
| `adjudication.ult_cast` | `ult_cast` and `ult_cast_identity`; binds own lines to X drops | `ability_state`, `view_events` | `ult-cast-0.6.0` | `ult-cast` | channel arbiter; its line-to-drop binding moves to the child owner |
| `adjudication.smokes` | `smoke` disc tracks | `smoke_owner`, harness step 6 | `smoke-0.5.0` | `minimap-smoke` | channel continuity; tracks become observations of children |
| `adjudication.smoke_owner` | `smoke_owner`, `smoke_owner_identity`, `cast_links` | `view_events`, harness step 6 | `smoke-owner-0.3.0` | `smoke-owner` | channel arbiter; `cast_links` moves to the child owner |
| `adjudication.ability.disc_tracks` | `ability_disc_track` | `adjudication.ability_glyph` | `ability-disc-track-0.1.0` | `ability-disc-track` | channel continuity |
| `adjudication.ability_glyph` | `ability_glyph_name`, `ability_glyph_identity`, `glyph_placement` | `round_lifetimes.detection_reality`, `enemy_tracks`, harness step 7 | `ability-glyph-name-0.3.0` | `ability-glyph-name` | channel arbiter; `glyph_placement`'s callers move to the child owner |
| `adjudication.weapon` | an ability named as a kill's weapon | `adjudication.death` | `weapon-adjudication-1.9.0` | `killfeed-weapon` | witness of a kill effect, and an opener |
| `adjudication.assist` | assister and ability icon per kill | `cli` | `assist-adjudication-0.4.0` | `kill-assists` | witness of an assist effect, and an opener |
| `adjudication.ability` milestone C: `build_entities`, `onset_groups`, `persistence_groups`, `bearing_groups`, `light_refusals`, `predict_ability_births` | the `ability-entities` analysis bundle from labelled demo components | `adjudication.gallery` | `ability-entities-0.3.1`, `ability-light-refusal-0.3.0` | `ability-hypothesis` | retire (step 3) |
| `adjudication.phases` | the `ability-phases` bundle from series contrast | the `ability-phases` adapter only | `ability-phases-0.3.0` | `ability-phase` | retire the code; its two structural rules become the child owner's tests |
| `adjudication.gallery` | the `ability-gallery` bundle | nothing in the pipeline; its classifier is UNCALLED | `ability-gallery-0.2.0` | `ability-appearance` | retire the classifier; the game-texture glyph reader replaced it |
| `adjudication.capture`, `ability_coverage` | demo capture queue; evidence inventory | `cli` | `ability-capture-0.1.0`, `ability-coverage-0.1.0` | `capture-queue`, `ability-evidence` | development tools, kept; `not_for` gains children |
| adapters `ability_entities`, `ability_phases`, `ability_gallery`, `ability_capture` | CLI over the above | the player | none | infrastructure | the first two retire with their owners |

### 1.3 Entity level, lanes and consumers (`reticle/`)

| Fragment | State on 4a8298d | Fate |
|---|---|---|
| `ownership.toml` `ability-owner` | unowned; doctor reports it; `blocked_by` an ability_icon lane | owned by `slot_state` (step 3) |
| `ownership.toml` `replay-truth-under` | unowned | owned by the promoted harness core (in flight) |
| `entity_events` lanes `smoke`, `ult_cast` | declared in `ENTITY_LANES`, never projected: `LANE_VERSIONS` holds only `round_entity`, `death`, `spike`, `enemy` | fold into one `ability` lane; never built apart |
| `entity_events` lane `ability_tray` | declared, never projected; renamed from `slot_state` before this plan, which first proposed `kit` | **`ability_tray` stands**; this plan calls the kit owner's lane by that name |
| `entity_contract` | families admit `ability_object`; kinds `cast` and `ability_object`; `STATE_VOCABULARY` already keys `ability_tray`; no ability fact carries `states` | gains the child and effect kinds (section 2.8) |
| `view_events` layer 4 | reads `ability_state`, `ability_shape`, `smoke`, `smoke_owner`, `smoke_owner_identity`, `ult_cast`, `ult_cast_identity` through the CONSUMER exemption; draws no glyph track | reads the `ability` and `ability_tray` lanes (step 3) |
| `round_lifetimes.detection_reality` | refuses an enemy track lying on a glyph the glyph owner places | asks the child owner, so any child of any channel can explain a find |
| `team_vision` | reads no ability entity; tolerates smokes by the order rule in its docstring | reads smoke children once they exist (not in this plan) |

### 1.4 Prototypes and scorers

| Fragment | What it holds | Stamp | Fate |
|---|---|---|---|
| `prototypes/ability_cast.py` | wrote the `ability` stream on demo sessions with no version key; nothing reads it | none | stream retired in step 0; `--emit` refuses; `tray_casts` stays a prototype |
| `prototypes/entity_state.py` | the slot model's prototype | `entity-state-0.3.0` | promoted to `reticle/slot_state.py` (B1); children and effects join it |
| `prototypes/coaching_belief.py`, the reach in `real_reader_schedule.py` | two more belief laws | -- | `slot_state` replaces both |
| `prototypes/question_acceptance.py` | the harness; since step 9 it holds `replay_abilities score`; steps 6 and 7 score smoke and glyph finds one channel at a time | `0.7.0` | one class-aware score over children and effects |
| `prototypes/ability_xchannel.py` | which channels witness others' casts; the opens-or-joins sketch | `ability-xchannel-proto-0.2.0` | its sketch becomes the witness table (2.3) |
| `prototypes/audio_others.py` | others' casts by sound | `audio-others-proto-0.2.0` | a joins-only witness, wired later |
| `prototypes/ult_ready_lines.py` | ally ult readiness | -- | a kit witness (castable), wired later |
| `prototypes/ability_states_gamedata.py` | each ability's states from game files, `wire: no` | `ability-states-gamedata-0.2.0` | the draft source of each ability's `states` list, for the mechanics-sheet pass (question 4) |
| `replay_actors`, `replay_layer`, `episodes.ChildTable` | truth children: owner, class, open, close, spawn, ticks | `replay-actors-0.1.0` | truth only, unchanged |

### 1.5 Plans

| Plan | Owner it proposes | Lane it proposes | Fate |
|---|---|---|---|
| [ABILITY_ENTITY_INFERENCE_DESIGN.md](ABILITY_ENTITY_INFERENCE_DESIGN.md) | `adjudication.ability` hypotheses | none | superseded by this plan |
| [ABILITY_DETECTION.md](ABILITY_DETECTION.md) sections 13-15 | a new `adjudication.ability_owner` over `ability_track` | `ability` | sections 13-15 superseded; sections 1-12 stay the readers' record |
| [MINIMAP_GLYPH_CHANNEL.md](MINIMAP_GLYPH_CHANNEL.md) "The event and its consumers" | the glyph track is the entity | `ability_icon` | that section superseded; the channel stays |
| [ENTITY_STATE.md](ENTITY_STATE.md) sections 9 and 11 | "new, beside `slot_state`" | `entity_ability` | amended: the owner is `slot_state`, the key changes (2.2), effects become entities (2.5) |
| [ARBITER_ARCHITECTURE.md](ARBITER_ARCHITECTURE.md) section 6 | the aggregator's ability-owner stage | none | its rules become the child owner's claim rules |
| [ENTITY_EVENTS.md](ENTITY_EVENTS.md) gap 8 and the lane table | `ability-owner` once an entity exists | `smoke`, `ability_tray`, `ult_cast` | the lane table and gap 8 point here |
| [ABILITY_STATE_MODEL.md](ABILITY_STATE_MODEL.md) step 3 | entities inside the kit record | the tray lane | step 3 points here; steps 4-5 become step 5 below |

### 1.6 Duplicates and conflicts

**Duplicates.**

- *Entity keys for one kind.* Smokes key `<sid>:smoke:<first_ms>:<track>`,
  ult casts `<sid>:ult_cast:<t>:<template>`, glyph tracks their track
  number, shapes `cast_t_ms` and slot. No two can say they saw the same
  instance.
- *Binding one cast across channels.* `smoke_owner.cast_links`,
  `ult_cast`'s line-to-drop binding, `predict_ability_births` and
  `dead_ruse_casts` each join two witnesses of one instance; none joins
  three.
- *Caster naming.* `smoke_owner`, `ability_glyph`, `ult_cast` and
  `tray_kit` each publish claims on their own entity, so a smoke the glyph
  reader also names gets two verdicts.
- *Shape fits.* `ability_shape` (after the player's casts) and `ability_fit`
  (every sample past the teal gate) fit the same shapes on two schedules.
- *Lifecycles.* `adjudication.phases`, `adjudication.smokes`' censored ends,
  `disc_tracks`' `TRACK_ENDS` and ENTITY_STATE's lifecycle classes each
  define an ending.
- *Beliefs.* `slot_state` (which absorbed `belief.py` in B1),
  `coaching_belief.py` and `real_reader_schedule.py` each hold a reach law.
- *Scorers.* The folded `replay_abilities score` and harness steps 6 and 7
  score ability finds apart.

**Conflicts.**

- `predict_ability_births` gates candidates by category ("local devices,
  area smokes, extending walls"), a rule by analogy that
  [domain:abilities/ability-rules-are-unique] forbids.
- ENTITY_STATE's child key holds the parent slot, which an enemy child's
  opening witness rarely knows (2.2).
- The cited gate `Vgate` rests on a truth-sight clause that cannot run in
  production; the ability gate (2.10) uses no truth.
- `minimap_dark`: `ability_scan`'s docstring says it rides the ability
  crop-cache pass, while `plan` called its rebuild a decode and named it
  nowhere when never run. Step 0 settled this (section 3).

**Gaps.** Nothing owns `ability-owner`. No owner reads `ability_fit` or
`ability_wall`. No ability fact carries `states`, `lifecycle_class`,
`ends_on` or `effect_query`. Most game-data facts carry a life value
(`domain/game_data.toml`), which answers most durations ENTITY_STATE
section 9 listed as missing.

## 2. The entity model

### 2.1 Where it lives

`slot_state` owns ability children and effects as it owns player slots. One
module holds the key scheme, the lifecycle machine, the belief law, the
round partition and the storage for every kind; each kind has its own rule
table and its own stamp (`ability-child-0.1.0`, `ability-effect-0.1.0`), so
a change to an ability rule restamps children and never the player slots,
as AGENTS.md requires of every independent table. If the module outgrows a
file, it becomes a package whose kind modules are its declared
infrastructure, one owner with one `[owns:...]` set; it never becomes a
second owner.

`slot_state` sits in the `adjudication` layer (`architecture.toml`). It
imports the owners it reads (`adjudication.ability_state`,
`adjudication.identity`, the channel owners) and none of them imports it.
Readers reach its beliefs only as gate windows a command hands them, as
`clove_circle` takes its windows, or as the `region_at` callable its
docstring prescribes for a per-frame gate.

Two owners stay apart, with one interface:

- **The kit** (`adjudication.ability_state`, [owns:ability-state]): per
  player slot and tray slot, charges, equipped, castable, owner alive.
- **The children and effects** (`slot_state`): per instance, open, kind,
  side, parent, place, phase, end; per effect, its source, targets and
  lifetime.

The child owner asks the kit owner's supply rules (`charge_facts`,
`charge_priors`, `slot_parameters`, the restock and pickup facts) for the
bound on opens, and counts opens itself. For the player, the kit owner's
cast transitions open children. For every other slot, the kit owner reads
the stored children as its cast witnesses (step 5). The loop breaks by
order: the player's kit, then children and effects, then the other kits.

### 2.2 Keys, kinds, parents and sides

Three kinds share the `(kind, id)` scheme of `EntityRow`:

| Kind | Id | Parent (`owner`) |
|---|---|---|
| `player` | `<sid>:<team>:slot:<k>` (B1) | none |
| `ability` | `<sid>:child:R<round>:<n>` | the casting slot, a revisable binding |
| `effect` | `<sid>:effect:R<round>:<n>` | the child that acts, or the cast itself for an instant buff with no child |

- **Ids**: the round table's number and the open's ordinal in the round.
  The owner mints an id at the open and never changes it. ENTITY_STATE
  section 9 put the parent slot in the key; an enemy glyph or a red ring
  opens with its caster unknown, and a key that holds a revisable verdict
  breaks every evidence link when the verdict moves. The parent is therefore
  a binding field, never part of the key.
- **Ability kind**: the ability, spelt as its facts' `subject`
  (`sova:recon bolt`), or `unknown`. The owner pools the kind each channel's
  owner decided (the glyph verdict's key, the shape descriptor, the tray
  slot of the player's kit, the ult template's class, the audio verdict, the
  smoke rule), stores every alternative, and decides once. A kind names a
  kit, and a kit names an agent, so a kind decision never writes an agent:
  it publishes an `identity_claim` on the child key.
- **Agent**: the arbiter's verdict on the child key, nothing else. The owner
  re-keys each bound channel claim to the child, as `enemy_tracks` re-keys
  icon claims to its tracks; a claim that took its entity from the child
  owner's binding declares `binding_from`, and every claim resting on the
  lineup declares `depends_on` its slots.
- **Parent**: the player slot key the lineup's verdict gives for (side,
  agent); a team fields each agent once [domain:rounds/agent-uniqueness].
  The binding `depends_on` the child's verdict and the slot's, and moves
  when either moves. The player's tray cast binds the self slot at the
  open; a spectated kit's drop binds the spectated teammate
  [domain:hud/tray-after-player-death].
- **Side**: from the opening witness where it says (a tray drop is the
  player's team; an ult line's variant names the side
  [domain:abilities/ult-lines-heard-by-both-teams]; a drawn smoke is the
  team's [domain:abilities/enemy-smokes-not-on-minimap]), else from the
  drawing's colour where the ability's own fact records one
  [domain:minimap/ability-drawing-colour-by-side], else `null` with its
  reason. An effect's side is its source's.

### 2.2a The tree (player, 2026-10-09)

Ability entities form a tree, not one level: slot, then ability instance,
then spawned objects nested to any depth, then effects. A spawned object can
be the child of another, and an effect is the child of whatever produced it:
Cypher's tracking dart is a child of his Spycam, and the dart ends at
Cypher's death while the camera persists. Each node is its own entity with
its own lifecycle and its own `ends_on`. A node's `parent` may be any entity
key (a slot, an instance, a spawned object), and the binding stays
revisable, as for a glyph whose caster is unknown at the open. Where the
table above says "parent slot", read "parent key". The `CHANNELS` table's
`parent` column names what each witness binds a new node to, and the
validator requires every ability and effect entity to name its parent or
null it with a reason (step 1).

### 2.2b Slot modes and placement (player, 2026-10-09)

**Slot modes.** A mode is a state on the player's own slot entity, with an
enter event and an exit event; it is never a child. Astral Form is Astra's
mode: she enters it at any time and from it places stars and activates her
abilities [domain:abilities/astra-astral-form-any-time]; her body stays where
she entered, visible and vulnerable, so her slot's position belief holds
that point through the mode [domain:abilities/astra-astral-form-body-stays].
Her own screen shows the astral-form map
[domain:abilities/astra-astral-form-screen-map], a witness of enter and exit
on her capture. Omen's Dark Cover aim is a phase of his slot while he holds
the ability, and he does not move during it
[domain:abilities/omen-dark-cover-aim-still].

**Placement per ability.** A child's placement is body-relative or global,
taken from that ability's own fact, never by analogy
[domain:abilities/ability-rules-are-unique]. A child with global placement
keeps its parent binding to the caster, but the slot belief's reach rule
(2.6) never ties its position to the caster's region: `cast_region` does not
apply, and an undrawn global child has no region until a witness places it.
The mechanics sheet's `placement` column asks each ability; it drafts Gravity
Well and Nova Pulse as global from the star's facts
[domain:abilities/astra-gravity-well-global-placement]
[domain:abilities/astra-nova-pulse-global-placement], for the player to
confirm.

**Placement radius.** A body-relative child opens within its range of the
caster's region at the cast, the `cast_region` of 2.6, never anywhere on the
map. Omen's Dark Cover opens within 80 m of Omen's region
[domain:abilities/omen-dark-cover-body-relative-placement]; the player first
called it global and corrected that on 2026-10-09.

**The star.** A star is one entity. Placing it opens it and picking it up
closes it, freely, while it is unspent
[domain:abilities/astra-stars-placed-and-picked-up]. Turning it into Nova
Pulse, Nebula or Gravity Well is a one-way change of its kind that keeps its
key; from then it runs that ability's own lifetime, and its effects are its
children [domain:abilities/astra-star-spent-is-final]. Cosmic Divide is its
own child of Astra's slot, not a turned star. A star turned into Nova Pulse
becomes an instant charge-up and then ends; it leaves no object, and each
player hit gets a concuss effect child that carries the only lasting
lifetime [domain:abilities/astra-nova-pulse-charge-then-concuss].

**The kit count.** The limit of stars deployed at once and its recharge are
a count on Astra's kit, the `ability_tray` lane, not a field of any star:
5 stars, recharging in 15.0 s
[domain:abilities/astra-star-limit-and-recharge].

**Open.** Whether Astra's minimap icon changes in Astral Form is unknown
[domain:abilities/astra-astral-form-screen-map].

### 2.3 Opening at a cast: the witness table

The child owner declares one table, `CHANNELS`, naming every input stream
and what it may do. The table is the anti-fragmentation contract: the
ABILITY ratchet (section 4) errors on an ability stream it does not list.

| Witness (owner) | Opens | Joins | Ends | Kind | Agent claim | Position |
|---|---|---|---|---|---|---|
| the player's tray cast (`ability-cast`, through the kit owner) | yes | | | tray slot of the player's kit | `depends_on` the self slot | the self slot's belief at the cast |
| a spectated teammate's tray drop (`tray-kit`) | yes | | | the spectated kit's slot | channel `tray_kit` | that slot's belief |
| an ult line (`ult-cast`) | yes, an X child of either side | yes | | template class | channel `ult_line` | none: an audio line carries no place |
| a smoke track (`minimap-smoke`, claims from `smoke-owner`) | yes, team only | yes | an observed end | the smoke rule's agent and slot | channel `smoke_owner` | the disc |
| a glyph track (`ability-glyph-name`) | yes | yes | the verify's loss where the disc would show | the verdict key | channel `minimap_glyph` | the track |
| a shape fit (`ability_fit`, `ability_wall`, `ability_shape`) | yes | yes | the fit's absence where it would show | the descriptor | none until a shape owner publishes one | the fit |
| a dead Clove's circle (`clove-circle`, via `smoke-owner`) | | yes, a Ruse child | | | channel `dead_clove_circle` | the circle's centre bounds the disc |
| a killfeed ability kill (`killfeed-weapon`) | yes, if no child of the killer's ability is live | yes | | the weapon verdict | `depends_on` the killer verdict | none |
| an assist icon (`kill-assists`, [domain:killfeed/assist-panel]) | yes, team only, if none is live | yes | | the icon's ability | `depends_on` the assister verdict | none |
| own ability audio (`ability-audio`) | | yes | | the scored slot | | |
| a device-destroyed sound or announcement ([domain:abilities/device-destroyed-sounds], unwired) | | yes | destroyed by the enemy | | | |
| others' ability audio (`audio_others`, unwired) | | yes only: at its precision it would open more false children than true (ENTITY_STATE section 9) | | the class | | |

A witness that may only join and finds no live child stays a stored
`candidate` that a later opener or the charge bound can promote; it never
opens a child. Opening takes the first witness; its time is an interval,
since a drawing follows the cast.

### 2.4 Lifecycle, per ability

Each ability's lifecycle comes from its own facts, never by analogy
[domain:abilities/ability-rules-are-unique]; quantities from the game files
first [domain:abilities/game-files-outrank-player-quantities].

| Field | Source | With no source |
|---|---|---|
| lifetime | the ability's `*-game-data` fact's `life` values | `no-fact:<agent>:<slot>:duration` |
| `ends_on`, a set | per ability: the mechanics-sheet pass and the per-ability facts, drawn from {lifetime expiry, destroyed by the enemy, owner death (disabled), round end, recall or reactivation} [domain:abilities/deployed-ability-ends] | `{round end}` alone, with `no-fact:<agent>:<slot>:ends_on` |
| states | a `states` list on its lifecycle fact, drafted from `ability-states-gamedata-0.2.0` and confirmed by the player in the mechanics-sheet pass | only `observed`, as `entity_contract.ability_states` returns today |
| lifecycle class: `deployed`, `instant`, `self_buff`, `team_buff`, `equipped`, `movement` | the mechanics-sheet pass, per ability | the end is refused with an interval |
| what owner death does | the class rule: a deployed ability is disabled [domain:abilities/deployed-ability-ends]; the per-ability facts ([domain:abilities/chamber-trademark-persists-after-death], [domain:abilities/deadlock-sonic-sensor-persists-after-death] and their siblings) say the object stays | a sighting after the death is the same child, never a new cast |
| cast while dead | [domain:abilities/no-cast-while-dead], [domain:abilities/clove-smokes-after-death] | -- |
| pickup or recall returns a charge | [domain:abilities/deployed-pickup-returns-charge] and the per-agent facts | no return transition |
| destruction restocks | the per-ability game-file facts (CooldownOnDestroy, DestroyedCooldown: [domain:abilities/killjoy-turret-recall-cooldown], [domain:abilities/cypher-spycam-pickup-cooldown]) | no restock transition |
| dims, not ends | [domain:minimap/device-dim-on-deactivation] | -- |

Three rules hold for every kind, as tests the retired `adjudication.phases`
asserted: a phase change never creates a child; a lifetime never ends at a
phase boundary; the charge bound never drops evidence. Opening a child
spends a charge of its parent's slot; evidence past the bound still opens a
child, flagged `over_bound`, and the surprise is stored (ENTITY_STATE
section 9).

**Ends are a set.** Each child stores `ends_on`, the causes its ability's
facts admit, drawn from lifetime expiry, destroyed by the enemy, owner
death, round end, and recall or reactivation; round end is always a member
[domain:abilities/deployed-ability-ends]. A deployed ability with no
explicit lifetime lasts until the enemy destroys it or the round ends; one
with a lifetime may also be destroyable. The per-ability facts and the
mechanics-sheet pass decide each set; one ability's set never extends to
another by analogy [domain:abilities/ability-rules-are-unique].

- **Destroyed by the enemy** is an end event, witnessed by the destruction
  sound or announcement [domain:abilities/device-destroyed-sounds] and by
  the drawing's disappearance where it would show. A child whose set lacks
  this member and whose drawing vanishes is a stored surprise.
- **Owner death** is a state change, not an end. The child keeps its key,
  its state goes to `disabled`, and it binds to its parent slot's death
  event, the death owner's verdict as its witness through `depends_on`.
  The minimap may draw it dim [domain:minimap/device-dim-on-deactivation].
- **Lifetime expiry** ends it at the lifetime fact; **recall or
  reactivation** at the kit owner's witnessed transition.
- **Round end** ends every child and effect
  [domain:rounds/no-ability-crosses-round-barrier]. A child alive through
  the post-round period [domain:rounds/post-round-period] closes at the
  next buy phase with basis `round_barrier`.

Between sightings no member has fired, so a deployed child stays
`live_assumed` at its placement, whether the team sees it or not.

### 2.5 Effects

An effect is an entity of its own, kind `effect`: what a child or a cast
does to players. Buffs (a self-buff, a buff on chosen allies, a buff on the
whole team), reveals, blinds, kills and assists all fall in this one kind.

- **Source**: the child that acts, or the cast itself for an instant buff
  that leaves no object; stored as the `owner` binding, with `depends_on`
  the source's verdict.
- **Targets**: the player slots it acts on, each with its witness or
  `null` with why. A self-buff targets its caster; a team buff its team; a
  reveal, blind, kill or assist the players it hit. Which set an ability's
  effect targets comes from that ability's facts, never by analogy.
- **Lifetime**: from the effect's own fact, else an interval with
  `no-fact:<agent>:<slot>:effect-duration`; a kill or assist is an instant.
  Every effect ends at the round barrier
  [domain:rounds/no-ability-crosses-round-barrier].
- **Witnesses**: the kill and assist verdicts (`adjudication.death`,
  `adjudication.assist`) today; reveal and blind witnesses (a revealed
  enemy's icon, a blinded player's screen) join the `CHANNELS` table as they
  are built. An effect computed from an `effect_query` fact (ENTITY_STATE
  section 9) is a prediction, stored apart from a witnessed one.

### 2.6 Position and region

`slot_state`'s one belief law serves children as it serves players, in
world metres with walk reach. Its kinds for a child:

- `fit`: the drawing's fit (a ring centre, a segment, a curve, a glyph
  track's position), with the reader's error as its radius.
- `placed`: a static child last fitted; the region stays the fit's disc,
  since a placed object does not move.
- `reach`: a moving child (a drone, a dog, a bot) unseen, grown at its own
  speed fact from the game files; with no speed fact, its parent slot's
  region at the same instant bounds it, and failing that no region
  (`position_unbounded: no_speed_fact`).
- `cast_region`: an undrawn child, the parent's belief at the open dilated
  by the ability's placement range fact; with no range fact, the parent's
  region alone (`anchor_unread: no_range_fact`).
- `none`: an audio-only open whose parent is unbound, an effect with no
  place (`not_applicable`).

**Out of sight.** An enemy child that leaves the team's vision keeps its
timeline (open, phases, observed end or `live_assumed`) and an approximate
location: its last `placed` fit, or for a moving or undrawn child the
region above, which is the slot model's region belief (`region_at`) for its
parent where the child's own facts give nothing tighter. The match shows
that region, never a point.

The child stores the shape it placed (kind and sizes from the geometry
table `ability_candidates` owns), so a consumer draws it without
recomputing.

### 2.7 Round scope

A child or effect lives inside one round, and nothing crosses a round
[domain:rounds/no-ability-crosses-round-barrier]. The owner partitions its
state by round, clears it at the barrier, and searches for a join only among
the same round's live children whose kind admits the witness. Nothing
compares children across rounds, as the player required of every entity
comparison on 2026-10-07. ROUNDSCOPE may assume this: any child or effect
state that survives a barrier is an error, with no exception list.

### 2.8 What a reader reports, and what the owner decides

| Reports, with scores and reasons | Decides |
|---|---|
| Readers: a fill, a texture score per key, a fit per descriptor, a grey mask, a rim fit, an audio peak; each with its refusal reason | nothing |
| Channel owners: one channel's continuity (a smoke track, a disc track) and its verdict (a glyph key, an ult class, a smoke rule), each with alternatives; identity claims on their own entity | that channel's verdict only |
| -- | `slot_state`: which channel products are one instance, its kind, side, parent, place, phase, end; each effect's source, targets and lifetime; the charge bound's surprises |
| -- | `adjudication.identity`: the agent on the child key |
| -- | `adjudication.ability_state`: the kit |

A reader's prior is the child owner's stored belief, handed in as a gate
window or a seed, never a copy the reader keeps.

### 2.9 Events, schema, lane and viewer

`slot_state` writes `ability_child` (one `child` row per instance, with its
witnesses, alternatives and refusals), `ability_effect` (one row per
effect), and `ability_child_identity` (the arbiter's verdicts on child
keys). Moving children's per-frame beliefs sit on `slot_state`'s entity
axis through its keyed API.

The `ability` lane projects children and effects; the `ability_tray` lane
projects `ability_state`. The `smoke` and `ult_cast` lanes are never built.

- **Entity rows**: a child is family `ability_object`, kind its ability's
  subject or `unknown`, with `side`, `round`, `lifetime` (observed bounds;
  `began` the open interval; `ended` with its basis), `identity` (agent,
  `ref` `identity:<child key>`, arbiter) and `player` (the parent slot key,
  or null with why). An effect is family `ability_effect`, with its source
  key, its targets, `round` and `lifetime`.
- **Events**: `cast` (exists: ability, slot) at the open; `ability_object`
  (exists: ability, slot, phase) at each observed state; `estimate` for an
  unseen child, carrying its region (2.6); `effect` at each effect's open,
  its targets as participants, citing the witness verdict;
  `ability_disabled` at an owner death, citing the death; and `ability_end`
  (basis: destroyed, lifetime expiry, recall, round barrier). `state`
  carries the placed `shape` and `ends_on`.
- **Contract changes**: the validator rejects an `ability_object` or
  `ability_effect` entity outside lane `ability`, one whose producer is not
  `slot_state`, and one whose `identity.ref` is not its own key's verdict.
  `BETWEEN_OBSERVATIONS` gains an `ability_object` rule: between sightings
  an enemy child carries its timeline and region (question 3).
- **The viewer** (`reticle view`) reads the two lanes alone: each child at
  its position or region with its placed shape, its ability and agent, `?`
  for an unknown kind, its phase; each effect on its targets; ledger
  children in amber; each slot's kit beside its player. The CONSUMER
  exemption loses every ability stream.

### 2.10 Scoring against the replay's children

Children and effects are scored in the one harness, on the promoted core's
`truth_under`, as a subcommand of the harness; no new scorer. Each child is
a find; it joins every replay entity under it, of every class: the `child:`
entities of `episodes.ChildTable` (owner, class, open, close, spawn, ticks)
and, for casts that open no world actor, the cast records
[domain:replay/vrf-cast-records].

- **Pairing**: same owner agent, same ability, open within the class's
  window of the child's open interval, one to one, nearest first.
- **Outcomes**, in the harness's vocabulary: `right_entity` (kind right or
  wrong, agent right or wrong, unnamed), `other_entity:<class>` (a find on
  a player, the spike or another ability), `nothing_there`, `undrawn_truth`
  (a truth child the drawing facts say the team cannot see
  [domain:minimap/ability-drawings-both-sides]), and `coverage_gap:<class>`
  for each unmapped actor class [domain:replay/vrf-ability-actors], named
  every run.
- **Per class and side**: open recall and precision; open and end time
  error; life overlap, `live_assumed` apart; truth anchor inside the region,
  and the region's area, out of sight included; kind and agent accuracy;
  effect source and target agreement. Round bootstrap intervals.
- **Per question**, the bar: the coaching utility questions,
  `detection_reality` (an enemy find on a drone), the draw rule's smokes,
  and effects. Each question's tolerance comes from degrading truth
  children (open delay, anchor jitter, dropped classes), as
  QUESTION_ACCEPTANCE section 7 does for slots.
- **Sets**: the development matches 9acf02f98283, c817691bcd15 and
  d3dcfb182ab1 on stored rows, each stale stamp named; cadaadeb2d8b,
  066741deafe5 and 9912c382130b; the held-out cea8ecbc94ab once per
  version.

### 2.11 The opportunity gate

`slot_state` writes `ability_opportunity`: per round, windows with their
reason and region, built from stored witnesses only, never from replay
truth.

- `cast_window`: after each non-minimap opener (a tray drop, an ult line, a
  killfeed ability kill, an assist icon), over the parent's walk-reach
  region, for the ability's drawing delay, with the candidate set the
  parent's kit allows.
- `continue`: each live drawn child at its place, at the cadence its
  questions' tolerance sets, denser before its lifetime fact ends it.
- `vision_entry`: where the team's vision meets an enemy slot's walk-reach
  region, for enemy drawings inside vision; everywhere for the abilities
  whose facts say they always show
  ([domain:abilities/reyna-leer-global-minimap],
  [domain:abilities/fade-haunt-global-minimap]).
- `cue`: a cheap teal or red change on the crop, the surprise path for a
  cast no other channel witnessed.
- `audit`: samples at a cadence fixed in advance, stored apart, never
  updating the gate.

Each ability reader declares `Gate(opportunity=..., source="ability_opportunity
(slot_state)", kind="spans")`, read before the pass as Clove's windows are;
once the per-frame hook lands, `kind="frame"` and `wants(t_ms)` return the
window and its region, so the reader reads that region only. The harness
measures, per class, the gate's open-at-onset share against truth onsets;
the audit stream measures what the cue misses.

## 3. Migration

Compute rules for every step: stored data first; no corpus rerun; a crop
cache reread only on cadaadeb2d8b, 066741deafe5 and 9912c382130b, each asked
first; one heavy process at a time, single-threaded, at idle priority.

**Step 0. Clear the ground.** Done on branch
`ability-entities-step0-20261009`, one commit per item:

- *The LAYER allowance ended.* `reticle ability-timeline --materialize`
  drove `prototypes/ability_cast.tray_casts`, which re-decodes each demo
  clip; promoting a decoding prototype reader into `reticle/` would have
  added a decode path, so the option went instead. `trees.allow` is empty
  and `ability-cast` is `partial`.
- *`minimap_dark`'s rebuild is declared.* `plan` owes it wherever the
  `minimap` pass ran (`NEVER_RUN_READERS`) and, where the stored minimap
  crop cache holds its ROI, proposes `reticle scan <sid> --only minimap_dark
  --from cache`, which decodes nothing and refuses rather than decode
  (`CACHE_FED_READERS`); with no such cache it proposes the plain `scan`,
  labelled decode. `WORKING_MAP.md` names the command. Whether the cache-fed
  reread rewrites stored rows identically is untested.
- *The unstamped `ability` stream is retired.* Nothing read it; its two
  questions have stamped owners (`tray_drop.player_cast` for when,
  `ability_shape` for where); `prototypes/ability_cast.py --emit` refuses,
  and `plan.RETIRED_STREAMS` names the stored rows, which stay.
- *`ability_light` is kept.* Its consumer, `light_refusals`, retires only
  in step 3, and the stream holds rows nothing else replaces. The defect the
  first draft cited, `plan` proposing it on sessions with no ability
  candidate, is fixed instead: `adjudication.ability.light_applies` marks
  those sessions not applicable. `ability_light` and `reticle ability-light`
  retire with milestone C in step 3.
- *The tray lane* is `ability_tray`, renamed before this plan; no rename.
- *Deferred to the ratchet branch*: anything in `reticle/doctor.py` or
  `reticle/ratchets.py`. Step 1 adds them.

Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`, then `.\.venv\Scripts\python.exe -m reticle plan cadaadeb2d8b`.
Evidence: no LAYER finding for `ability_timeline`; `plan` names a runnable
`minimap_dark` command where the stream is stale or never run, and no
`ability_light` work on a session without candidates; the plan and tray
tests pass.

**Step 1. Enforce first.** Declarations and the ratchet, no new code that
decides. Done on branch `ability-entities-step1-20261009`:

- `reticle/slot_state.py` declares `CHANNELS` (2.3 as code, stamped
  `ability-channels-0.1.0`): per witness its `parent`, `owners`,
  `readers`, `streams`, `feeds` and what it may do (`opens`, `joins`,
  `ends`, `kind`, `agent_claim`, `position`, `effect`); and
  `ABILITY_LANES` (`ability`, `ability_tray`).
- `ownership.toml`: `ability-child` (instances and nested spawned objects,
  each with its parent) and `ability-effect` (an effect is a child of what
  produced it), and `ability-owner`, all owned by `slot_state` as `partial`
  with `names_agents = true` deferring to `agent-identity`; the limit and
  the building step (2, or 3 for `ability-owner`) are in each entry. Every
  entry that reads, joins or names ability evidence carries `entity_kind =
  "ability"`, and each `CHANNELS` owner `feeds = ["ability-child"]` (with
  `ability-effect` for kills and assists).
- `reticle/ratchets.py`: ABILITY (`ability_findings`) and its shrink-only
  `ABILITY_LEGACY` with the frozen `ABILITY_SEED`: 19 entries (5 streams, 2
  lanes, 6 entries, 6 functions), each with its fate and step. Fragments
  come from `plan`'s stream registry, `entity_events.ENTITY_LANES` and the
  tagged entries; three entries stay apart by design (`ABILITY_APART`:
  `capture-queue`, `ability-evidence`, `replay-ability-actors`). `reticle
  status` prints the ability line. ROUNDSCOPE needs no ability exception,
  since no child state exists yet.
- `reticle/doctor.py` registers ABILITY (`check_ability`).
- `entity_contract.check_ability_row`: the rejections of 2.9, with
  `depends_on` for a name from another key's verdict (a parent's included),
  and a required `parent` on every ability and effect entity.
- `documents.toml`: section 1.5's plans amended.
- Not done: predictions for steps 2 to 4 in `notes/predictions.jsonl`.

Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`, then `.\.venv\Scripts\python.exe -m pytest tests\test_ratchets.py tests\test_entity_contract.py`.
Evidence: 0 errors; one ABILITY warning per `ABILITY_LEGACY` entry; a test
that adds an undeclared ability stream gets an ERROR, and one that deletes a
listed fragment gets the stale-entry ERROR.

**Step 2 (done). The player's own children and effects.** `slot_state` gains the
`ability` and `effect` kinds and owns `ability-child` and `ability-effect`.
Openers: the player's tray casts and own ult lines. Joiners: `ability_shape`
fits, smoke tracks, glyph tracks, Clove's circle, own audio. Effects: the
player's self-buffs and team buffs where the ability's facts name them, and
the player's ability kills and assists. Lifecycles by facts, with every
missing field a `no-fact` reason; the charge bound against the kit owner.
The `ability` lane and the viewer read them. Retire
`smoke_owner.cast_links`, `dead_ruse_cast` (a query now), and `ult_cast`'s
line-to-drop binding, each after the children reproduce it.

Acceptance: `.\.venv\Scripts\python.exe -m reticle project SESSION --lane ability` on each of the six sessions, then the harness's ability subcommand with `--side self` on them, then `reticle view SESSION --round N`.
Evidence: every kept player cast opens exactly one child; the stored
`dead_ruse_cast`, `cast_links` and ult bindings reproduce or each difference
is classed; per class, open recall and precision against the replay's own
casts with round intervals; the player marks one round's children and
effects right or wrong in the viewer.

Step 2 done (2026-10-09, branch `ability-entities-step2-20261009`):

- `slot_state.build_abilities` builds the player's children
  (`ability_child`, `ability-child-0.1.0`) and effects (`ability_effect`,
  `ability-effect-0.1.0`) from stored rows; `reticle ability-children
  SESSION --write` writes both. Openers: the kit's cast transitions, own ult
  lines, a dead Clove's smokes (`dead_ruse_casts`). Joiners: shape fits,
  smoke tracks (one cast, one smoke, the rule `cast_links` held), glyph
  tracks, Clove's circle, own audio. Effects: ability kills, ability
  assists, and the effects an ability's `effects` fact predicts.
  `ability_lifecycle` reads each field from the ability's own facts or
  stores a `no-fact` reason.
- The `ability` lane (`entity-ability-0.1.0`) projects them; no contract
  bump. `reticle view` draws the lane.
- Retired: `smoke_owner.cast_links` (smoke-owner-0.4.0; no stored link
  existed on any session) and the `dead_ruse_cast` stream (`plan.RETIRED_STREAMS`).
  ABILITY legacy 19 to 17; the seed stays, so `status` counts the clears.
- Scored by `reticle acceptance ability-lane --side self` on
  the six sessions: recall [metric:question_acceptance/ability_lane/step2b@066741deafe5+9912c382130b+9acf02f98283+c817691bcd15+cadaadeb2d8b+d3dcfb182ab1#all_recall=0.8523], false-open share
  [metric:question_acceptance/ability_lane/step2b@066741deafe5+9912c382130b+9acf02f98283+c817691bcd15+cadaadeb2d8b+d3dcfb182ab1#all_false_open_share=0.0241], end-cause agreement
  [metric:question_acceptance/ability_lane/step2b@066741deafe5+9912c382130b+9acf02f98283+c817691bcd15+cadaadeb2d8b+d3dcfb182ab1#all_end_cause_agreement=0.6014]. Prediction
  `ability-entities-step2-20261009-A1` passed on its pre-registered run.
- Not done: `ult_cast`'s line-to-drop binding (`player_x_drops`) moves to
  step 3, since `tray_x_cast` still selects peaks through it; a spawned
  object joins its instance as a witness, not as a node; positions come only
  from shape fits and smokes; no reveal or blind witness; lifetimes are
  missing for Curveball, Recon Bolt, FRAG/ment, Rendezvous, Headhunter and
  the ults, and Chamber's Trademark `life` names the slow field, not the
  trap; Rendezvous and Headhunter casts sit in unmapped replay slots; the
  dev matches' lanes stay held stale until their `smoke_owner` is rebuilt;
  the player's viewer check is owed.

**Step 3. The team's children, and `ability-owner`.** Openers add ally
smokes, glyph tracks, shape fits and walls, ally ult lines, spectated kit
drops, killfeed ability kills and assist icons; allies' effects bind.
Channel claims re-key to children; `ability_child_identity` is written;
`slot_state` owns `ability-owner` (`names_agents = true`, deferring to
`agent-identity`). The viewer drops its direct reads of `smoke`,
`smoke_owner`, `ult_cast` and their identity streams. Retire milestone C
(`build_entities`, the three grouping rules, `light_refusals` with
`ability_light` and `reticle ability-light`, `predict_ability_births`, the
`ability-entities` command, the `ability-hypothesis` entry),
`adjudication.phases` and `reticle ability-phases` (its two rules kept as
tests), the `minimap.detect_ability_*` functions and the gallery's
classifier.

Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`, then the harness's ability subcommand with `--side ally` on the six sessions.
Evidence: doctor no longer reports `ability-owner`; per ally class,
outcomes summing to the finds, kind and agent accuracy with intervals,
beside harness steps 6 and 7's channel scores as the control; every
unmapped class named.

**Step 4. The enemy's children.** Openers add enemy ult lines, enemy glyph
and drone tracks inside vision, the always-visible set, the enemy Lockdown
ring [domain:abilities/killjoy-lockdown-enemy-minimap-ring], and enemy
ability kills. Out of sight, each enemy child keeps its timeline and region
(2.6). `round_lifetimes.detection_reality` asks `slot_state` whether a
child lies under a find, in place of `glyph_placement`, so a drone from any
channel explains an enemy false accept.

Acceptance: `.\.venv\Scripts\python.exe prototypes\question_acceptance.py lane --tag pgb --reality paired` on the development matches, then the harness's ability subcommand with `--side enemy`.
Evidence: the enemy lane's 0.3.0 control reproduces; the paired difference
in presence precision with its interval; per enemy class, recall over the
truth children the drawing facts say the team sees, `undrawn_truth` counted
apart; for children out of sight, the share of truth anchors inside the
region, with the region's area.

**Step 5. Kits for every slot.** `adjudication.ability_state` reads stored
children as cast witnesses for allies and enemies and holds their charges
as intervals (ABILITY_STATE_MODEL steps 4 and 5); the `ability_tray` lane
carries every slot.

Acceptance: `.\.venv\Scripts\python.exe -m reticle ability-state SESSION --record`, then `reticle project SESSION --lane ability_tray`.
Evidence: the player's kit rows byte-identical to step 2's; for other
slots, the share of rounds whose truth cast count lies inside the interval,
and the interval's width, per class.

**Step 6. Gates.** `AbilityShapeReader`, `AbilityIconReader`,
`AbilityGlyphReader` and `DarkRegionReader` declare their gates on
`ability_opportunity`; the per-cast `ability_shape` reads merge into the
gated fits. Rereads on the three 2026-10-07 sessions only, after asking.

Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor` (CONVERT), then the harness's ability subcommand on the gated arm beside the 2 Hz arm.
Evidence: per question and class, the loss with its interval, gated against
2 Hz; read share and CPU per session from `reticle usage`; the gate's
open-at-onset share per class; four entries fewer in `CONVERT_LEGACY`.

**Step 7. Close.** `ABILITY_LEGACY` is empty; the superseded plans move to
`docs/archive/` with dates; `WORKING_MAP.md`'s ability rows collapse to one.

Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`.
Evidence: no ABILITY, LAYER or CONSUMER finding on an ability stream; DOCS
clean.

## 4. Ratchets

| Check | Errors on | Shrink-only list |
|---|---|---|
| ABILITY (new) | an ability-tagged entry or stream that `CHANNELS` does not list and `ABILITY_LEGACY` does not excuse; a `CHANNELS` row naming a stream that does not exist; a legacy entry whose fragment is gone | `ABILITY_LEGACY` |
| the event validator | an `ability_object` or `ability_effect` entity outside lane `ability`, from another producer, or named by a verdict on another key | -- |
| OWNERSHIP | `ability-owner` unowned (as today), then an `entity_kind = "ability"` entry that names agents without deferring to `agent-identity` | -- |
| CONSUMER | `view_events` opening an ability stream's file | the exemption's `uses`, narrowed |
| CONVERT | an ability reader with no gate, or a gate whose source is not `ability_opportunity` | `CONVERT_LEGACY` |
| ROUNDSCOPE | child or effect state that outlives a round, or a join search beyond the round's live children; no exception, since nothing crosses a round | -- for ability state |
| LAYER | any module in `trees.allow` | `trees.allow`, empty since step 0 |
| DOCS | a superseded ability plan still `live` | -- |

## 5. What the merged slot model gives, and what the new kinds need

B1's `reticle/slot_state.py` gives the scheme this plan builds on: rows
keyed `(kind, id)`, an `owner` field for a parent, a `side`, a per-frame
belief law that assumes no kind, a round reset at `seg_start`,
`stack_entities` to join per-kind blocks, and `region_at` for one
instant's regions. The ability and effect kinds still need from it:

- **A key with no parent, and a parent that can change.** The key holds no
  parent, as 2.2 requires, but `EntityRow` is frozen and its `owner` is set
  once. A child's parent is a binding that moves when the arbiter's verdict
  moves; it needs a binding over time with its `depends_on`, beside the row.
- **A stamp per kind.** The module carries `slot-state-0.1.0` and
  `entity-binding-0.1.1`; `ability-child-0.1.0` and `ability-effect-0.1.0`
  must restamp only their own rows.
- **A child axis.** The belief arrays are (entities, frames) on the slot
  frame grid. Children live for seconds inside one round and open in
  numbers no lineup bounds; they need a sparse block per round, or an axis
  whose rows hold only their own frames, so a round's children cost what
  they live.
- **A lifecycle builder and a binder per kind**, the two extension points
  the module docstring names, and none built yet.
- **Effects** need a row with a target set, which `EntityRow` has no field
  for.

Other work in flight:

- **The harness core** moving into `reticle/` gives `truth_under` the owner
  2.10 scores on; steps 2 to 6 extend the harness's ability subcommand.
- **The ratchet branch** holds ABILITY, ROUNDSCOPE and the `Gate` the gates
  use. Whether a cheap cue at a fixed cadence (2.11) passes CONVERT is its
  owner's call; without one, no surprise path exists.
- **The mechanics-sheet pass** (question 4) is a dependency: another agent
  builds the pre-filled pass; this plan reads its answers and does not edit
  the sheet.
- **ENTITY_EVENTS stage 2**: the declared `smoke` and `ult_cast` lanes
  should not be built; an agent building them now duplicates step 3.

## 6. The player's answers (2026-10-09)

Each question was checked against `domain/*.toml` first. All six are
closed.

1. **Round end.** No ability object carries across the round barrier
   [domain:rounds/no-ability-crosses-round-barrier]. The model ends every
   child and effect at the barrier (2.4, 2.7), and ROUNDSCOPE assumes it.
2. **Self-buffs and team buffs.** They are entities of their own, of kind
   `effect` (2.5): a buff on the caster, on chosen allies, or on the whole
   team, each with its target set.
3. **An enemy ability out of sight.** The match shows its timeline and an
   approximate location, the slot model's region belief where nothing
   tighter is known (2.6, step 4).
4. **Lifecycle class, ends-on and states, per ability.** Yes, as a
   pre-filled mechanics-sheet pass for the player to confirm. Another agent
   builds it; this plan depends on its answers (2.4, section 5) and leaves
   the sheet alone.
5. **The deployed rule.** A deployed ability with no explicit lifetime
   lasts until the enemy destroys it or the round ends; some abilities with
   a lifetime can also be destroyed; a deployed ability is disabled when its
   owner dies; all of it holds for enemy devices too
   [domain:abilities/deployed-ability-ends]. The model stores `ends_on` as
   a set, owner death as a `disabled` state bound to the death, and
   destruction as an end event (2.4). Each ability's members come from its
   own facts and the mechanics-sheet pass.
6. **Effects.** Reveals and blinds are effects, as kills, assists and buffs
   are; every effect is an entity (2.5).

## 7. What this plan does not settle

- Whether Astra's minimap icon changes in Astral Form (2.2b).
- No step is measured: every number of section 3 is to be predicted first.
- The cue's cost and its miss rate on enemy casts no other channel
  witnesses.
- Whether a replay holds every actor the server spawned
  [domain:replay/vrf-ability-actors], and whether it records effects
  (buffs, reveals, blinds) at all; an effect class the replay lacks is a
  `coverage_gap`.
- The witnesses of reveals and blinds: none is built.
- `team_vision`'s use of smoke children.
- Where a child's region lies on a map without map constants: with no world
  frame, `slot_state` stores pixels only and every region test drops the
  child.
