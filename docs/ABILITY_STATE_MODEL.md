# Ability state: one model of every ability's state, and the detectors it conditions

Design sketch, 2026-09-27, from the player's framing: the missing piece is a
detector that takes in the game state, including a state machine per ability
(charges, equipped, deployed), and reads each channel conditioned on it.
Companion designs: [entity phases](ABILITY_ENTITY_INFERENCE_DESIGN.md#entity-phases-an-ability-transforms-and-stays-itself)
(a deployed entity transforms and stays itself), [temporal adjudication](ADJUDICATION_DESIGN.md)
(claims, invariants, revision), [behaviour dynamics](BEHAVIOUR_MODEL_DESIGN.md)
(predict-update-smooth at three timescales). This document adds the layer
between them: the state of every ability slot of every player, as a belief
that the witnesses update and the detectors consult.

## Why a state, not more refusals

`ability_timeline.player_tray_casts` (owner `ability-cast`) decides what a tray
drop is with an ordered list of refusals: out of round, after the player's
death, co-occurring, forced, `partial_charge`, and next `equip_release` and
`pips_lit`. Each refusal is a fragment of a state machine written as an
exception. `partial_charge` says the ult slot was not in the state *castable*;
`equip_release` says the slot left the state *equipped* without a cast;
`after_player_death` says the tray no longer shows the player's kit
[domain:hud/tray-after-player-death]. The list grows by one rule per surprise
and never says what state the slot is in, so nothing downstream can ask
"could this ability be cast now?", and every detector runs against the full
set of things that might happen. The model below names the states, and the
refusals become transitions with witnesses.

The reader already sees the state's shadow. A two-charge slot reads 1.0, 0.5
and 0 [domain:hud/ability-tray-charge-segments]; an equipped ability adds
teal above 1.0 and releases back to the full level
([metric:tray/segments@all-sessions#full_after=68] of 493 accepted drops);
the X bar lights only when the ult is castable
[domain:abilities/ult-slot-lights-when-castable], and a cast empties the pips
[domain:abilities/ult-charge-pips]. Those are observations of `charges`,
`equipped` and `castable`, stored today as fills.

## The state of one ability

One record per (match, side, agent, slot). The slot is the unit because the
tray, the timer bar and the description all speak per slot
[domain:abilities/signature-on-e].

| Variable | Values | Source of the parameters |
|---|---|---|
| `charges` | 0..`max_charges`, or an interval `[lo, hi]` when unobserved | `max_charges` per ability from `domain/abilities.toml` (`*-tray-charges`) and the mechanics sheet; two charges draw two segments, and a count above two is kept while its drawing is unobserved [domain:hud/ability-tray-charge-segments] |
| `mode` | `idle`, `equipped`, `casting`, `active`, `cooldown`, `unreadable` | the ability's kind from its description verbs [domain:abilities/ability-description-verbs]: fire-and-forget, channelled, placed-then-activated [domain:abilities/placed-then-activated], toggled by fuel [domain:abilities/viper-fuel-toggle], piloted, self-triggering |
| `entities` | the ids of live world entities this slot owns, each with its own phases | the entity-phase model; a cast is 1:N (a wall is several segments, a Regrowth ring is one) |
| `until_ms` | when `casting`, `active` or `cooldown` ends, with uncertainty | durations and cooldowns per ability (`phoenix-blaze-duration`, `omen-dark-cover-restock` [domain:abilities/omen-dark-cover-restock]); `null` with a reason when no fact exists |
| `pips`, `castable` | ult slot only: 0..cost, and whether the bar is lit | [domain:abilities/ult-charge-pips], [domain:abilities/ult-slot-lights-when-castable] |
| `owner_alive` | the kit belongs to a living player, a second life, or is frozen | death verdicts, Run it Back and revive rows, as the gate uses them today |
| `readable` | which witnesses can see this slot now | local player: tray, timer bar, audio, minimap; ally: audio, minimap, ready lines; enemy: audio, minimap, killfeed |

Every rule is per ability [domain:abilities/ability-rules-are-unique]. The
model holds no defaults by category: a slot whose ability has no fact for a
parameter carries `null` and the reason `no-fact:<ability>:<parameter>`, and
the mechanics sheet is the place the player fills it. Regrowth has no tray
drop [domain:abilities/skye-regrowth-no-tray-drop]; Deadlock's ult drops at
equip [domain:abilities/deadlock-ult-tray-drop-at-equip]; Run it Back's pips
fall at expiry [domain:abilities/phoenix-run-it-back-expiry-flash]. Each is a
per-ability transition table, not a special case in a shared rule.

## Transitions and their witnesses

A transition is a claim with an observation time, an uncertainty, the witness
that made it and the evidence it rests on. The set is closed; an observed
change that matches no allowed transition is stored as a surprise, never
silently absorbed or averaged away.

| Transition | What changes | Witnesses that can see it | Invariant it must obey |
|---|---|---|---|
| equip | `mode` idle to equipped | tray teal above the full level (Sova's bow, Blaze's glow), hand animation, equip sound | the slot has a charge, or is the ult with the bar lit |
| unequip | equipped to idle, nothing spent | tray teal falls to the full level (`equip_release`) | `charges` unchanged |
| cast | `charges` down one segment, or `pips` to zero; `mode` to casting or active; entities born | tray fall to a lower segment level, cast voice line, cast sound, minimap birth, timer bar start | `charges` was above 0; ult `castable` was true; owner alive; in round; one cast per ability per range round [domain:abilities/range-one-cast-per-round] |
| channel end | casting to idle or cooldown | timer bar end, key release, sound | duration within the ability's bound |
| activate, reuse | a placed entity changes phase; a toggle consumes fuel [domain:abilities/viper-poison-cloud-toggle] | minimap phase change, sound, fuel meter | the entity exists and belongs to this slot |
| expire, destroy | an entity ends; `mode` may return to idle | minimap death, destroyed-device sound [domain:abilities/device-destroyed-sounds], timer bar end | lifetime spans every phase; a phase change never creates a second entity |
| recharge | `charges` up one segment | a tray segment relights, a cooldown counter reaching zero, a kill for kill-refreshed signatures, round start | never above `max_charges` |
| buy | `charges` up in the buy phase | tray in the buy phase, the economy ledger | buy phase only |
| ult charge | `pips` up one; `castable` when full | orb pickups, kills, round results; the ready line when full [domain:abilities/ult-ready-line-is-a-radio-reply] | `pips` never exceeds the cost |
| owner death, second life, revive | `owner_alive`; the tray switches to a spectated kit [domain:hud/tray-after-player-death] | killfeed, badge, revive entries | the kit's charges freeze; a second life keeps them |
| unreadable | the tray is not the player's or not drawn | menu dim [domain:hud/menu-dims-tray], the Trailblazer view [domain:hud/controlled-entity-view-tint], death camera | `charges` becomes an interval, never a guess |

The tray's contribution is exactly what `reticle tray` stores today (fills,
drops, refusals) read as level changes: a fall to a lower segment level is a
cast, a fall to the same level is an unequip, a rise is a recharge or a buy.
The reader keeps its one job [owns:tray-drop]; the meaning moves here.

## Whose abilities

The local player's four slots are the fully observed case: the tray gives
`charges`, `equipped` and `castable` at 5 Hz, the timer bar gives channel and
active ends [domain:hud/ability-timer-bar], own audio gives casts and the ult
line [domain:abilities/caster-hears-own-ult-line], and the minimap gives the
entities. This is where the model is built and scored first.

Allies have no tray. Their casts come from cast lines and cast sounds, their
entities from the minimap (ally abilities draw), their ult readiness from the
ready line teammates hear [domain:abilities/ult-ready-line-is-a-radio-reply],
and their deaths from the killfeed. `charges` is an interval: it starts each
round at what the round reset allows, drops when a cast is witnessed, and
widens when a witness was unavailable (a cast the audio could not hear). The
interval is the honest state; a point value there is a guess.

Enemies are observed by both teams' channels only: the ult line
[domain:abilities/ult-lines-heard-by-both-teams], cast sounds within earshot,
minimap objects their abilities draw, and the killfeed. Their ult pips are
unknown until the cast; their `charges` interval rarely narrows. The value of
the enemy record is negative evidence: an enemy who cast Dark Cover twice this
round has none left, and a third smoke has another owner.

Names are never decided here. A witness that binds a cast to a player
publishes an `identity_claim` and asks `adjudication.identity`, with
`depends_on` when the binding rests on another entity's verdict; the record's
agent field is that arbiter's verdict. The unowned `ability-owner` question
(which player owns an ability entity) is answered by this record once the
entity is bound to a slot.

## Modal detection: the state conditions the detectors

The state is the prior the readers start from, and the surprise path is the
widened search:

- **Templates.** A cast template for ability A on side S is scored only while
  some player on S holds A with `charges > 0`, or the ult with `castable`
  true, and the owner alive. The lineup already reduces 58 ult templates to
  the match's ten agents; the state reduces those to the ults that are ready.
  The full set runs only as the surprise path, when a detection above the
  threshold matches no allowed cast, and its result is stored as a
  disagreement with the state, never as a cast.
- **Shapes and entities.** The minimap fitters run in the window after a cast
  claim, seeded by the caster's position, as `ability_shapes` does; a birth
  with no cast claim is a surprise that asks the audio and the tray again
  before it becomes an entity of unknown origin.
- **The tray.** The reader's `CAST_DROP` and `FULL_MIN` become predictions
  from the state: from `charges = 2` the next fall lands at 0.5; from an
  equipped slot the next fall lands at the full level unless a cast witness
  also fired. Disagreement between the predicted level and the read one is
  stored per drop and is the reader's calibration set.
- **Expensive passes.** Any pass that decodes (dense minimap reads, the shape
  fitters, a future audio bank) is gated by a state transition or by the
  audio gate's "something other than footsteps and gunfire", never by a
  fixed cadence.

Agreement is consistency, not accuracy. Two witnesses of one transition are
corroboration; the reliability table (`adjudication.reliability`) weighs
them as it weighs identity channels, and a channel's own output is never its
own evidence.

## Storage and recomputation

`events/ability_state/<sid>.jsonl`, written whole by `Store.write_events`
like every stream:

- **claim rows**: witness, slot key, transition, `observed_at_ms`, the
  uncertainty, `source_version`, `evidence` (a pointer into the witness's
  stored rows), `depends_on`. Raw observations, kept apart from verdicts.
- **verdict rows**: slot key, the state before and after, the transition, the
  witnesses that agreed, the ones that disagreed, `reason` when the model
  refused the transition, and a `surprise` flag when a claim matched no
  allowed transition.
- **a coverage row**: the version of every input stream (`tray`,
  `player_cast`, `ult_line`, `ult_cast`, `minimap`, `death-adjudication`,
  `hud`), so `reticle plan` can stale it, and its own `ABILITY_STATE_VERSION`.

The model recomputes from stored claims and decodes nothing. A witness
version change restamps the stream; the ledger records each restamp's
predicted and observed counts, as the tray gate's G-series does today.

## Ownership and layers

- A new entry `ability-state` in `ownership.toml`: question "What state is
  each player's ability in, and which transition did this observation
  witness?"; owner `adjudication.ability_state`; produces the claim, verdict
  and coverage rows and `allowed_transitions(slot, t)` for the detectors;
  `not_for` a name (defers to `agent-identity`), a pixel or an audio
  detection (those are witnesses), an entity's position or phases
  (`ability-phase`). Placed in the `adjudication` layer beside
  `adjudication.ult_cast` and `adjudication.phases`.
- `ability-cast` becomes a witness: `player_tray_casts` publishes tray
  transitions and their refusals as claims; its reason list is retired one
  reason at a time as the model takes over, and its stored verdicts are the
  regression set for the handover.
- `ult-cast` asks `allowed_transitions` for the ult templates to score and
  keeps binding lines to X casts; `ability-shape` keeps fitting shapes after
  cast claims; `minimap-smoke` supplies smoke births and deaths as entity
  transitions.
- The per-ability parameters stay domain facts in `domain/abilities.toml`;
  the model reads them through `reticle domain`, never restates them, and
  the mechanics sheet is the intake for missing ones.

## Invariants and evaluation

The north star is the full-round event stream: every cast, entity and ending
identified and localised, obeying the game's invariants. The invariants the
model asserts, each a test and a stored count:

1. `charges` stays within `[0, max_charges]`; a cast needs a charge.
2. An ult casts only from a lit bar, and its cast empties the pips.
3. A slot in `equipped` that returns to `idle` with the same level spent nothing.
4. An entity has one owning slot; a phase change never creates a second entity; a lifetime spans every phase.
5. A frozen kit (owner dead) changes only by revive, second life or round reset.
6. One cast per ability per range round.

Scoring, in order: the player's 120 tray-cast labels and 170 piece labels
already stored; the demo census answers; a leave-one-session-out check of any
fitted weight; then the same full-round stream on a session the player
labels blind. Every count is predicted before the run and written to
`notes/predictions.jsonl`; the first perceptual failure builds the tool that
asks the player, as the tray labeller did.

## Build order

1. **The local kit from the tray alone.** `adjudication.ability_state` over
   stored `tray_drop` rows: `charges` from segment levels, `equipped` from
   teal above the level, `castable` from the lit X bar, `owner_alive` from
   the death rows. Acceptance: reproduces every kept cast of
   `player-cast-0.4.0` on the 19 lineup sessions, names the state each
   refusal stood for, and passes the 120 labels at least as well as the gate
   ([metric:tray/port@tray-work-cache#labelled_casts_passing=119] of 120).
2. **Own audio and the timer bar as witnesses.** The ult line binds to the
   `cast` transition instead of to a drop; the timer bar reader (new, from a
   fixed ROI in the shared decode pass) dates channel and active ends for
   Run it Back and Regrowth, the two casts the tray misses.
3. **Entities join.** Shape fits and smoke tracks attach to the slot that
   cast them, 1:N, with the entity-phase records inside the state rather
   than beside it; simultaneous smoke births are one bulk cast
   [domain:abilities/smoke-bulk-confirm], one transition with several
   entities.
4. **Allies.** Cast lines and minimap births drive interval charges per
   teammate; ready lines set `castable`; scored on sessions where the player
   labels teammates' casts from the VOD.
5. **Enemies.** The same with both-team channels only; the measure is the
   negative evidence it supplies to smoke and ability attribution.
6. **Modal gating measured.** Cast templates scored only for allowed
   transitions on a full game-only match, against the lineup-impossible rate
   of the ungated run.

## Hazards

- **Restating an owner.** Every parameter and rule is a domain fact or an
  owner's output; the model composes them. A restated rule compiles and
  drifts.
- **Analogy across abilities.** No default per category; `null` with
  `no-fact` until the sheet or the player answers.
- **The tray's reference.** Fills are relative to a session's p90, which
  hides absolute levels; store the segment levels the model inferred beside
  the fills so a mis-normalised session shows as a level disagreement.
- **Unreadable spells.** Menus, the death camera and controlled-entity views
  make the state an interval; a model that keeps a point value through them
  guesses.
- **Grading its own homework.** A detector gated by the state cannot score
  the state; the score comes from labels, held-out sessions and the ungated
  surprise path.
- **The witnesses' own errors.** A surprise may be a tool error; the ledger
  records which instrument was checked before the belief moved.

## Questions for the player

Per ability, through the mechanics sheet: max charges, recharge kind and
time, whether the slot glows when equipped, whether the cooldown counter
prints digits, which abilities show the timer bar, and what ends each
entity. The sheet has 116 rows and none is complete; the model's `no-fact`
reasons are the queue.

## Step 1, built (2026-09-27)

`reticle ability-state [--all | SESSION] [--record]` stores
`events/ability_state/<sid>.jsonl` (`adjudication.ability_state`, owner
`ability-state`, `ability-state-0.1.0`). It reads the stored `tray_drop`
rows, reruns the gate on them from storage, reads the deaths and phases the
gate reads, takes the player's agent from the arbiter's verdict in the
lineup, and rereads the tray's fills from the stored `hud_abilities` crops on
the grid `reticle tray` sampled. The drops carry only the two fills around
each fall; the fills carry the level between drops, the teal of an equip, a
lit X bar and every rise. It decodes nothing. The gate keeps its behaviour:
step 1 turns each of its verdicts into a transition and names what each
refusal stood for.

The rows follow "Storage and recomputation": one `coverage` row (input
stamps, the agent's provenance, the kit and the facts behind its parameters,
thresholds, counts, reproduction checks and invariant counts); `claim` rows
(`tray_drop`, the gate's `player_cast` that depends on it, `tray_fill`,
`kit_end`, `undone_death`), each with its observation time, the interval it
happened in, its source stamp and its evidence; `verdict` rows with the
transition, the state before and after, the witnesses that agreed and
disagreed, the gate's reason and what it stood for, and a surprise with its
reason; and `state` rows, one per run of samples a slot spends in one state,
carrying `charges`, `charges_range`, `level`, `mode`, `castable`, `pips`,
`owner_alive`, `readable` and `until_ms`, each null with a reason when unread.

**Instruments.** The reread reproduces the stored drops on all
[metric:ability_state/step1@all-sessions-before-e-facts#sessions=20] sessions
([metric:ability_state/step1@all-sessions-before-e-facts#drops_reread_mismatch=0]
mismatches over [metric:ability_state/step1@all-sessions-before-e-facts#drops=3228] drops).
The gate, refactored to publish `kit_windows` and `round_window_of`,
reproduces every stored verdict
([metric:ability_state/step1@all-sessions-before-e-facts#gate_stored_mismatch=0]
mismatches), and each of its
[metric:ability_state/step1@all-sessions-before-e-facts#transition_cast=493] kept casts is a
`cast` transition.

**Levels.** The first run read C, Q and E as full at the gate's
`FULL_AFTER_MIN` and the X bar as lit at `FULL_MIN`. Those thresholds test a
drop's ends and sit on the low tails of the full and lit levels: the X bar
went dark without a drop
[metric:ability_state/level-edges@all-sessions#x_unlit_without_a_drop=26]
times, [metric:ability_state/level-edges@all-sessions#x_unlit_without_a_drop_to_0_5_0_8=24]
of them to a fill of 0.5-0.8. The state now reads at the fills' density
minima (`LEVEL_FULL_MIN`, `X_LIT_MIN`); surprises fell from
[metric:ability_state/step1-scores@all-sessions#first_run_invariant_surprises=111]
to [metric:ability_state/step1@all-sessions-before-e-facts#invariant_surprises=78] and the
dark flickers to
[metric:ability_state/step1@all-sessions-before-e-facts#surprise_x_bar_went_dark_without_a_drop=2].
An equip reads from `EQUIP_MIN`, where
[metric:ability_state/step1@all-sessions-before-e-facts#release_from_at_equip_min=120] of
[metric:ability_state/step1@all-sessions-before-e-facts#release_drops=121] stored releases
start.

**Readability.** [metric:ability_state/step1@all-sessions-before-e-facts#unreadable_fraction=0.4213]
of [metric:ability_state/step1@all-sessions-before-e-facts#slot_samples=222368]
slot-samples are unreadable: after the player's death
([metric:ability_state/step1-scores@all-sessions#unreadable_kit_frozen_fraction=0.3564]),
in the round-end and inter-round phases
([metric:ability_state/step1-scores@all-sessions#unreadable_phase_fraction=0.0259]),
and with the tray undrawn or its guard rows flooded
([metric:ability_state/step1-scores@all-sessions#unreadable_undrawn_or_flooded_fraction=0.0371]).

**Whose kit.** A match with no killfeed death left the spectated kit's bars
read as the player's: on the Iso match `4f207c0c4e39`
[metric:ability_state/step1@4f207c0c4e39-before-kit-witness#invariant_1_level_outside_the_segments=433]
samples showed a half level on a one-charge slot. The tray kit witness
([TRAY_KIT_WITNESS.md](TRAY_KIT_WITNESS.md)) reads the slot icons, and the
state now marks another agent's kit `kit:spectating:<agent>` and the rest of
the witnessed death `owner_dead:kit_witness`; the half levels fall to
[metric:ability_state/step1@4f207c0c4e39#invariant_1_level_outside_the_segments=0].

**Charges.** Among the played agents, facts give a count only for Blaze
[domain:abilities/phoenix-tray-charges] and Ruse
[domain:abilities/clove-tray-charges]. Sova's C, Q and E, Skye's C, Q and
E, Phoenix's Q and E and Clove's C and Q have none, so
[metric:ability_state/step1-scores@all-sessions#no_fact_fraction_of_readable_cqe=0.671]
of [metric:ability_state/step1-scores@all-sessions#readable_cqe_slot_samples=96507]
readable C, Q and E slot-samples store `charges` null with a `no-fact`
reason and keep only the range the level bounds. `c62c2b06bcfb` has no
lineup, so its agent is null and
[metric:ability_state/step1@all-sessions-before-e-facts#charges_unread_no_player_agent=3528]
slot-samples carry `no_player_agent`. A half bar need not be one charge of
two: Sova's Recon Bolt, one charge in the official reference
(`reference/abilities.json`), reads half for a stretch after a cast on
`c40d950031bb` (595 s, 912 s). The reference's `charges` field is not a
domain fact, and step 1 does not read it.

**Labels.** Of the player's tray-cast labels the gate accepts,
[metric:ability_state/step1@all-sessions-before-e-facts#labels_cast_held_before=89] of
[metric:ability_state/step1@all-sessions-before-e-facts#labels_cast=94]
([metric:ability_state/step1@all-sessions-before-e-facts#a1_held_fraction=0.9468]) held a
charge or a lit bar just before. The five others fell from a half bar on a
slot with no fact (Phoenix E twice, Skye E twice, Sova E once), which the
model will not call one charge. The other labels become `unequip`, `none` or
`unresolved`, as the gate's reasons stand for.

**Invariants.** Every testable count is zero in all
[metric:ability_state/step1-scores@all-sessions#sessions_invariants_all_zero=20]
sessions: a cast without a charge, an X cast from an unlit bar or leaving it
lit, a release that lowered the level, a frozen kit that changed, and a half
bar on a one-charge slot.
[metric:ability_state/step1@all-sessions-before-e-facts#invariant_1_cast_charge_unconfirmed=44]
casts leave the charge unconfirmed: a half bar on a slot with no fact.
Entities (invariant 4) and range rounds (invariant 6) wait for later steps.
The surprises left are
[metric:ability_state/step1@all-sessions-before-e-facts#surprise_level_fell_without_a_cast=60]
refused drops whose level fell, co-occurrence and buy-phase refusals where a
state-deciding model and the gate would first disagree, and
[metric:ability_state/step1@all-sessions-before-e-facts#surprise_level_fell_without_a_drop=16]
level falls the reader stored no drop for.

**Cost.** [metric:ability_state/step1-scores@all-sessions#run_wall_s=1266.8] s
wall at Idle priority for all sessions, of which reading the crop cache took
[metric:ability_state/step1-scores@all-sessions#cache_read_s_sum=1177.4] s.
The predictions and outcomes are in the store's ledger, task
`ability-state`.

### What step 2 needs

- Charge facts for the seven slots still without one (the ten above less
  Sova's, Phoenix's and Skye's E), and each ability's recharge kind
  [domain:abilities/recharge-kinds], from the mechanics sheet; until then a
  half bar reads `[0, 2]`.
- A pip reader for the X slot: the tray counts teal, not pips, so `pips`
  stays null and `castable` is the only ult reading.
- The timer bar reader, to date `until_ms`. Step 1 dates an active span only
  from a duration fact and from the cast
  ([domain:abilities/phoenix-blaze-duration],
  [domain:abilities/clove-ruse-minimap-duration]).
- Own audio bound to the `cast` transition rather than to a drop.
- Labels for the refused drops whose level fell, scored before the model
  decides casts in place of the gate.

### Rerun with the E-slot charge facts (2026-09-27)

The player confirmed one Recon Bolt charge
[domain:abilities/sova-recon-bolt-charges] and two each of Curveball and
Guiding Light [domain:abilities/phoenix-curveball-charges]
[domain:abilities/skye-guiding-light-charges], and named the two restock
kinds, a timer or kills, per ability [domain:abilities/recharge-kinds]. The
first run's rows are relabelled `all-sessions-before-e-facts` and this run's
`all-sessions-three-e-facts`.

Before the rerun the five A1 misses were read in the crops. The two on
`c40d950031bb` (595 s, 912 s) follow Sova's deaths at 592.5 s and 908.5 s:
the tray then shows the spectated teammate's kit, Phoenix's Curveball at one
charge of two, and the gate had forced the drops `after_player_death`. The
one on `59c70f1ef720` (2429.0 s) is the bow's glow over the E slot while
Recon Bolt restocks (countdown 33 to 13 s) after Hunter's Fury at 2425 s: the
glow read as a fill of 0.42 and its passing as a drop the gate accepted as a
cast; the player's label there is `nothing_on_minimap`. A half bar on a
one-charge slot is the instrument, and the tray's icons say whose kit is
shown, a witness for deaths the killfeed misses.

With the facts, [metric:ability_state/step1@all-sessions-three-e-facts#labels_cast_held_before=93] of 94 labelled
casts held a charge or a lit bar before (S1 asked 93: the two Phoenix and two
Skye E casts read one charge of two, and the Sova E drop is not confirmed);
[metric:ability_state/step1@all-sessions-three-e-facts#invariant_1_cast_charge_unconfirmed=9] casts are
unconfirmed (S3 asked at most 20, from 44), a level outside the segments on
[metric:ability_state/step1@all-sessions-three-e-facts#invariant_1_level_outside_the_segments=2] readings (S2
asked 1 to 39; `59c70f1ef720` 2429 s is the glow, `9acf02f98283` 210 s is the whole tray dimmed in a buy phase, every slot at 0.6 of full), and
[metric:ability_state/step1@all-sessions-three-e-facts#invariant_surprises=78] surprises
([metric:ability_state/step1@all-sessions-three-e-facts#surprise_level_fell_without_a_cast=60] refused drops
whose level fell). The run records no `step1-scores` row; the first run's
scores stand. S1 to S3 held (ledger). Seven slots have no charge fact: Sova and Skye C and Q, Phoenix Q,
Clove C and Q; Iso's kit joins when `4f207c0c4e39` is ingested.

### Rerun with the seven remaining counts (2026-09-27, late)

The player gave the seven counts left: Owl Drone one
[domain:abilities/sova-owl-drone-charges], Shock Bolt two
[domain:abilities/sova-shock-bolt-charges], Trailblazer one
[domain:abilities/skye-trailblazer-charges], Hot Hands one
[domain:abilities/phoenix-hot-hands-charges], Pick-me-up one, castable only
within 10 s of a kill or damaging assist
[domain:abilities/clove-pick-me-up-charges], Meddle one
[domain:abilities/clove-meddle-charges], none recharging within a round.
Regrowth is a pool drawn as a resource bar, not charges
[domain:abilities/skye-regrowth-resource-bar], so Skye's C stays a no-fact
slot until the model reads a pool; Viper's fuel is one bar two abilities
drain, refilled at a constant rate while idle
[domain:abilities/viper-fuel-bar-recharges]. The rerun recorded under
`all-sessions`, relabelled `all-sessions-seven-facts` when the catalogue run
below took that label: [metric:ability_state/step1@all-sessions-seven-facts#labels_cast_held_before=93] of 94 labelled
casts held a charge before,
[metric:ability_state/step1@all-sessions-seven-facts#invariant_1_cast_charge_unconfirmed=9] unconfirmed
(five on `c62c2b06bcfb`, which had no lineup then, so no fact named its agent; four whose one-charge slot read half, fill 0.355 to 0.429, just before the labelled cast: Sova E `59c70f1ef720` 2429.0 s, Sova C `9acf02f98283` 610.1 s, Phoenix Q `a06f04a0059f` 1412.6 s, Skye Q `b7d24102a6f6` 650.0 s), a level outside the segments on
[metric:ability_state/step1@all-sessions-seven-facts#invariant_1_level_outside_the_segments=14] readings
(Phoenix:Q 1, Skye:Q 1, Sova:C 10, Sova:E 2), [metric:ability_state/step1@all-sessions-seven-facts#invariant_surprises=78] surprises
([metric:ability_state/step1@all-sessions-seven-facts#surprise_level_fell_without_a_cast=60] refused drops
whose level fell). S4 failed; S5 held (ledger).

### The catalogue as the charge prior (2026-09-27)

The player asked that the ability facts already pulled from the wiki be used.
The harvest (`reference/abilities.json`, built by
`prototypes/ability_reference.py` on 2026-09-04, a prior and never an oracle)
now gives a slot's charge count where no domain fact does (`charge_priors`,
`ability-state-0.2.0`). The command reads it from the store and stamps its
harvest date among the inputs; without the file there is no prior and the
command says so. The harvest's `Grenade`, `Ability1`, `Ability2` and
`Ultimate` are C, Q, E and X, and its count applies only where it names the
kit's ability in that slot.

A domain fact outranks the catalogue. Where both give a count and differ, the
fact's count stands and the slot records the `conflict` with both values. A
fact that makes a slot a pool [domain:abilities/skye-regrowth-resource-bar],
or bounds every slot at two charges [domain:hud/ability-tray-charge-segments],
refuses the catalogue's count the same way. A catalogue string that is not a
count (the ult table's function names, Reyna's "2 (shared charges)") or an
empty field leaves the slot without one, with the reason. Every state row
whose charges rest on a count names its `charges_source`; the coverage row
lists the conflicts, the slots still without a count, and the half readings
against each count (`segments`): a half bar agrees with a two-charge count and
disagrees with a one-charge count, and the reading stands either way.

Over the whole harvest (`ability_state/catalogue-prior`), the catalogue agrees
with every one of the
[metric:ability_state/catalogue-prior@reference-2026-09-04#cqe_source_player=23]
C, Q and E counts the facts give
([metric:ability_state/catalogue-prior@reference-2026-09-04#conflicts_count=0]
count conflicts) and supplies
[metric:ability_state/catalogue-prior@reference-2026-09-04#cqe_source_catalogue=57]
more. Of the
[metric:ability_state/catalogue-prior@reference-2026-09-04#cqe_without_count=7]
slots left without a count, Skye's C is a pool by the player's fact against
the catalogue's one, Brimstone's E (three) and Chamber's Q (eight) exceed the
two-charge bound, Reyna's Q reads "2 (shared charges)", and Astra's Q and E
and Reyna's E carry no count. The three refusals, and every count the
catalogue alone gives, are questions for the player, who has confirmed none
of them.

The rerun covers
[metric:ability_state/step1@all-sessions#sessions=21] sessions: the twenty
above, with `c62c2b06bcfb` now naming Skye from its new lineup, and the Iso
capture `4f207c0c4e39`. It changed no reading. Every played agent's C, Q and
E slots already had a domain count except Skye's C, which the pool fact bars
from the catalogue's one, so
[metric:ability_state/step1@all-sessions#charges_source_catalogue=0]
readable slot-samples rest on the catalogue and
[metric:ability_state/step1@all-sessions#charges_source_player=93137] on a
fact; [metric:ability_state/step1@all-sessions#charge_conflicts=1] conflict
(Skye's C) and [metric:ability_state/step1@all-sessions#slots_without_count=1]
slot without a count (the same) remain, and the unread `no-fact` samples, all
on Skye's C, did not fall (C1 in the ledger). The half readings agree with the
two-charge counts on
[metric:ability_state/step1@all-sessions#segments_agree=6300] slot-samples
(Clove E, Phoenix E, Skye E, Sova Q) and disagree with a one-charge count on
[metric:ability_state/step1@all-sessions#segments_disagree=447], the same
samples invariant 1 counts outside the segments; Iso's capture holds
[metric:ability_state/step1@all-sessions#invariant_1_level_outside_the_segments_4f207c0c4e39=433]
of them, half bars on all three of his one-charge slots. Casts left
unconfirmed number
[metric:ability_state/step1@all-sessions#invariant_1_cast_charge_unconfirmed=9],
[metric:ability_state/step1@all-sessions#invariant_1_cast_charge_unconfirmed_4f207c0c4e39=5]
of them Iso's; the four others are the casts above whose one-charge slot read
half, which no count can confirm, and the lineup, not the prior, confirmed the
five on `c62c2b06bcfb`. Surprises number
[metric:ability_state/step1@all-sessions#invariant_surprises=167],
[metric:ability_state/step1@all-sessions#invariant_surprises_4f207c0c4e39=89]
on the Iso capture; the other twenty keep the
[metric:ability_state/step1@all-sessions-seven-facts#invariant_surprises=78] above.
[metric:ability_state/step1@all-sessions#labels_cast_held_before=93] of
[metric:ability_state/step1@all-sessions#labels_cast=94] labelled casts
held a charge before. C1 to C5 held (ledger); C4's premise called the four
slots empty, and they read half.

### Counts above two and Astra's stars (2026-09-28)

The player confirmed the harvest's C, Q and E counts
[domain:abilities/catalogue-charge-counts-confirmed] and answered two of the
[metric:ability_state/catalogue-prior@reference-2026-09-04#cqe_without_count=7]
slots the section above left without a count: Brimstone's Sky Smoke holds
three charges [domain:abilities/brimstone-sky-smoke-charges] and Chamber's
Headhunter eight [domain:abilities/chamber-headhunter-charges]. That
falsified the claim that no ability holds more than two, and the segment fact
now keeps only its appearance: two charges draw two segments, and how the
tray draws three or more is unobserved
[domain:hud/ability-tray-charge-segments]. Astra's C, Q and E expend one pool
of stars that the three slots share [domain:abilities/astra-stars-shared].

`charge_priors` changes in three ways. A harvest count of the confirmed date
takes the source `catalogue-confirmed` with the confirming fact's key and
keeps its harvest entry; a distinct source, rather than `player`, keeps a bulk
confirmation apart from a per-ability fact, and a harvest of another date
falls back to `catalogue`. A per-ability fact still outranks it, and a pool
still refuses it: Skye's Regrowth remains a `resource_bar` conflict against
the harvest's one. A shared-pool fact (`shared_pool_facts`) leaves Astra's C,
Q and E without a count, with the reason `shared_pool` and a conflict against
the harvest's one Gravity Well. The bound of two no longer refuses a count:
`MAX_SEGMENTS_READ` bounds the segments the reader interprets, not the
charges. A count above it stands, unclamped, as the slot's `max_charges`; its
full and half bars store `charges` null with the reason
`segments_unobserved_above_two` and a range up to the count, and its half
readings stay unscored in `segments`.

No stored row changes: the lineups name no Brimstone, Chamber or Astra as the
player, and every played agent's C, Q and E count already came from a
per-ability fact, so the version stays `ability-state-0.3.0`. The range of a
slot without a count still tops out at two segments; Astra's stars test that
assumption the first time a session plays her.

## Own-cast residuals against Riot (2026-10-05)

`prototypes/own_cast_residuals.py` (`own-cast-residuals-0.2.0`, series
`own_cast/residuals@riot-21`) explains the gap `prototypes/tray_gold_eval.py`
scores: own casts covered [metric:own_cast/residuals@riot-21#covered=525] of [metric:own_cast/residuals@riot-21#riot_casts=610], with [metric:own_cast/residuals@riot-21#beyond=8] beyond
Riot's counts. Riot's records hold per-match totals only, so each residual
belongs to a (session, ability) slot, and its round is the round of the
evidence that places it. Each missing cast takes one class from stored
evidence; the module docstring gives the order.

The gate's death test reads two inputs short. It reads second lives only
from a current `killfeed_portrait` stream, and every Phoenix session stores
`killfeed-portrait-0.18.0` against the code's 0.19.0, so no Run it Back
death is undone. It undoes a death for Phoenix's second life and Clove's own
revive only, so a teammate Sage's Resurrection of the player
[domain:rounds/resurrection-mechanics] still ends the kit; the stored
`death_verdict` rows name [metric:own_cast/residuals@riot-21#cf_teammate_revives_revived_deaths=3] such revives,
on `b3b9defb6fd7` (844.5 s and 1287.0 s) and `b7d24102a6f6` (1864.5 s). The
prototype reruns the gate with both inputs (`rejudge_inputs`): a drop the
stored gate refused as `after_player_death` that the rerun judges otherwise
carries the input that changed it as its root, and the candidate tests judge
it by the rerun's reason.

| Class | Casts | By ability |
|---|---|---|
| 1 no tray drop | [metric:own_cast/residuals@riot-21#class1=15] | Clove E [metric:own_cast/residuals@riot-21#class1_Clove_E=12], Skye Q [metric:own_cast/residuals@riot-21#class1_Skye_Q=2], Sova E [metric:own_cast/residuals@riot-21#class1_Sova_E=1] |
| 2 witness refused | 0 | |
| 3 gate refused, a second life the gate did not read | [metric:own_cast/residuals@riot-21#class3_root_second_life_unread=20] | Phoenix X [metric:own_cast/residuals@riot-21#class3_root_second_life_unread_Phoenix_X=12], C [metric:own_cast/residuals@riot-21#class3_root_second_life_unread_Phoenix_C=3], E [metric:own_cast/residuals@riot-21#class3_root_second_life_unread_Phoenix_E=3], Q [metric:own_cast/residuals@riot-21#class3_root_second_life_unread_Phoenix_Q=2] |
| 3 gate refused, a teammate's revive of the player | [metric:own_cast/residuals@riot-21#class3_root_teammate_revive=4] | Skye Q [metric:own_cast/residuals@riot-21#class3_root_teammate_revive_Skye_Q=2], E [metric:own_cast/residuals@riot-21#class3_root_teammate_revive_Skye_E=1], X [metric:own_cast/residuals@riot-21#class3_root_teammate_revive_Skye_X=1] |
| 3 gate refused, its own rules | [metric:own_cast/residuals@riot-21#class3_root_none=40] | Sova E [metric:own_cast/residuals@riot-21#class3_root_none_Sova_E=10], Sova Q [metric:own_cast/residuals@riot-21#class3_root_none_Sova_Q=6], Iso X [metric:own_cast/residuals@riot-21#class3_root_none_Iso_X=5], Phoenix X [metric:own_cast/residuals@riot-21#class3_root_none_Phoenix_X=2], eleven others with one or two each |
| 4 wrong slot | 0 | |
| 5 Riot-side | 0 | |
| 6 excess | [metric:own_cast/residuals@riot-21#class6=8] | Skye C [metric:own_cast/residuals@riot-21#class6_Skye_C=2], one each on Sova C, Phoenix E and Q, Skye Q, E and X |
| 7 unexplained | [metric:own_cast/residuals@riot-21#class7=6] | Sova E [metric:own_cast/residuals@riot-21#class7_Sova_E=3], Clove E [metric:own_cast/residuals@riot-21#class7_Clove_E=2], Clove Q [metric:own_cast/residuals@riot-21#class7_Clove_Q=1] |

Class 3 holds [metric:own_cast/residuals@riot-21#class3=64] in all.

**The gate's reasons.** Of the class 3 casts, the death test refused
[metric:own_cast/residuals@riot-21#gate_after_player_death=28], co-occurrence [metric:own_cast/residuals@riot-21#gate_cooccur_among_casts=30], a drop
onto an undrawn tray [metric:own_cast/residuals@riot-21#gate_forced=4], the round's end [metric:own_cast/residuals@riot-21#gate_phase_round_end=1]
and the full-level test [metric:own_cast/residuals@riot-21#gate_equip_release=1]. An own ult line places
[metric:own_cast/residuals@riot-21#class3_by_line=20] of them; a restock numeral, the slot icon or the audio saw
[metric:own_cast/residuals@riot-21#class3_witnessed=37] more; neither saw [metric:own_cast/residuals@riot-21#class3_unwitnessed=7].

**The death inputs, rejudged.** With the stored second lives the rerun gate
passes [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None=13] of the
[metric:own_cast/residuals@riot-21#class3_root_second_life_unread=20] second-life casts: Phoenix X
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_X=8], C
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_C=2], Q
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_Q=2] and E
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_E=1]. It refuses the rest on
another test: co-occurrence
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__cooccur_among_casts=4], a forced drop
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__forced=2] and a partial charge
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__partial_charge=1]. With the teammate
revives it passes all [metric:own_cast/residuals@riot-21#class3_rejudged_teammate_revive__None=4] revive casts.
Of the [metric:own_cast/residuals@riot-21#class3_gate_after_player_death_Phoenix_X=14] Phoenix X misses, all
refused by the death test and placed by his own lines, the second lives
recover [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_X=8] and the rest
stay missing: co-occurrence
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__cooccur_among_casts_Phoenix_X=2], a
forced drop after a second life
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__forced_Phoenix_X=1], a partial charge
[metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__partial_charge_Phoenix_X=1], and
[metric:own_cast/residuals@riot-21#class3_root_none_Phoenix_X=2] forced drops 1 to 3 s after a death that no
stored badge calls a second life (`5822b6646448` 1415.5 s, `587c15b07779`
1551.5 s). So the forced-drop rule explains only the forced ones among
them, not every one.

Per slot, against Riot, the gate fed the stored second lives covers
[metric:own_cast/residuals@riot-21#cf_second_lives_covered=538] and holds [metric:own_cast/residuals@riot-21#cf_second_lives_beyond=8] beyond, reading
[metric:own_cast/residuals@riot-21#cf_second_lives_second_lives=13] second lives:

| Session | Slot | Covered gained | Beyond gained |
|---|---|---|---|
| `5822b6646448` | Phoenix Q | [metric:own_cast/residuals@riot-21#cf_second_lives_5822b6646448_Q_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_5822b6646448_Q_beyond_gain=0] |
| `5822b6646448` | Phoenix X | [metric:own_cast/residuals@riot-21#cf_second_lives_5822b6646448_X_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_5822b6646448_X_beyond_gain=0] |
| `7010b3d62460` | Phoenix C | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_C_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_C_beyond_gain=0] |
| `7010b3d62460` | Phoenix Q | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_Q_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_Q_beyond_gain=0] |
| `7010b3d62460` | Phoenix X | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_X_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_7010b3d62460_X_beyond_gain=0] |
| `a06f04a0059f` | Phoenix X | [metric:own_cast/residuals@riot-21#cf_second_lives_a06f04a0059f_X_covered_gain=2] | [metric:own_cast/residuals@riot-21#cf_second_lives_a06f04a0059f_X_beyond_gain=0] |
| `ff636d173b07` | Phoenix C | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_C_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_C_beyond_gain=0] |
| `ff636d173b07` | Phoenix E | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_E_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_E_beyond_gain=0] |
| `ff636d173b07` | Phoenix X | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_X_covered_gain=4] | [metric:own_cast/residuals@riot-21#cf_second_lives_ff636d173b07_X_beyond_gain=0] |

The gate fed the teammate revives covers [metric:own_cast/residuals@riot-21#cf_teammate_revives_covered=529] and
holds [metric:own_cast/residuals@riot-21#cf_teammate_revives_beyond=9] beyond. The kit ends at the death and
resumes at the revive, so the rerun keeps the stored rows from
`tray.SUSPECT_S` before the death's lead to the revive; without that window
the death screen's drops, let through, tainted the Trailblazer `b7d24102a6f6`
spent at 1857.0 s:

| Session | Slot | Covered gained | Beyond gained |
|---|---|---|---|
| `b3b9defb6fd7` | Skye Q | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b3b9defb6fd7_Q_covered_gain=2] | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b3b9defb6fd7_Q_beyond_gain=0] |
| `b7d24102a6f6` | Skye E | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_E_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_E_beyond_gain=0] |
| `b7d24102a6f6` | Skye X | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_X_covered_gain=1] | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_X_beyond_gain=0] |
| `b7d24102a6f6` | Skye Q | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_Q_covered_gain=0] | [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_Q_beyond_gain=1] |

The new Skye Q cast on `b7d24102a6f6` is a false drop at 1866.5 s: by eye the
Q bar is grey from 1857.0 s to 1868.0 s, and the revive's cyan flash over
the tray at 1864.5 s is the only change. Both inputs together cover
[metric:own_cast/residuals@riot-21#cf_both_covered=542], beyond [metric:own_cast/residuals@riot-21#cf_both_beyond=9].

**Checks.** On `9acf02f98283` (`C:\Users\grant\Videos\2026-08-24
11-55-34.mp4`), the one match with a replay, both missing casts the
prototype names are the replay's own cast records
[domain:replay/vrf-cast-records]: the Shock Bolt at 967.5 s (picked
968.0 s) and the Recon Bolt at 2194.2 s (picked 2194.0 s). By eye on the
tray strips: every class 3 pick viewed is a spend (Iso's Kill Contract
empties X a second before the arena darkens the tray; Sova's bow glow lifts
a neighbour bar; a Recon Bolt draws its numeral under the glow; Run it
Back's pips and Blaze's bar empty after the second life; a revived Skye's Q
bar empties at 857.5 s on `b3b9defb6fd7`), and the candidate rules exclude
what the eye refuted (blank samples, buy-phase and round-end dims, death
screens, full bars under a passing glow). The rules were refined on those
viewed cases, so the class 3 and class 7 counts are in-sample. Of the
[metric:own_cast/residuals@riot-21#class6=8] excess casts, the eye (`EXCESS_EYE`) calls
[metric:own_cast/residuals@riot-21#class6_eye_flash_streak_or_tint=3] a flash, a streak or a tint crossing a
bar, [metric:own_cast/residuals@riot-21#class6_eye_regrowth_pool=2] a Regrowth pool counting to 00
[domain:abilities/skye-regrowth-resource-bar], and
[metric:own_cast/residuals@riot-21#class6_eye_real_spend=3] real spends: `b7d24102a6f6` Q, `e37fdeca944f` E and
`043bafca271a` C at 1774.0 s, an Owl Drone whose bar is teal to 1773.5 s and
grey with no refill to the round's end. Those [metric:own_cast/residuals@riot-21#extra_unplaced=3] slots' extra
casts stay unplaced. Of the ten deaths at which Clove held a Ruse charge,
the minimap drew a ring at the death marker or a large circle
[domain:abilities/clove-dead-smoke-range-circle] after four, vanished
within seconds after two, showed only a disc of unknown age after one, and
showed nothing after three; so the [metric:own_cast/residuals@riot-21#class1_Clove_E=12] class 1 Clove casts are
a bound from the charges, not each one seen.

**Fixes, by casts recovered per unit of risk.**

1. Rerun `killfeed_portrait` from the crop cache on the Phoenix sessions,
   then the tray gate (owner `killfeed-portrait`, read through
   `adjudication.death.stored_second_life`; the gate, `ability-cast`, is
   unchanged). It recovers [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None=13]
   casts with no new excess (covered [metric:own_cast/residuals@riot-21#cf_second_lives_covered=538], beyond
   [metric:own_cast/residuals@riot-21#cf_second_lives_beyond=8]): Phoenix X
   [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_X=8], C
   [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_C=2], Q
   [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_Q=2] and E
   [metric:own_cast/residuals@riot-21#class3_rejudged_second_life_unread__None_Phoenix_E=1], per the table
   above. Witness: Phoenix's own ult
   line. Risk: a rerun, no rule.
2. Undo a death that a teammate's revive follows (`ability-cast`, through
   `stored_gate_inputs`): take the stored `death_verdict` revives whose
   victim is the player's agent on the ally side, from any reviver, and end
   the kit at the death and resume it at the revive, as the gate does for
   Clove's own revive. It recovers
   [metric:own_cast/residuals@riot-21#class3_rejudged_teammate_revive__None=4] casts and adds
   [metric:own_cast/residuals@riot-21#cf_teammate_revives_b7d24102a6f6_Q_beyond_gain=1] false drop (covered
   [metric:own_cast/residuals@riot-21#cf_teammate_revives_covered=529], beyond [metric:own_cast/residuals@riot-21#cf_teammate_revives_beyond=9]); a
   drop in the second after the revive's flash wants the numeral or the
   audio. Witness: the death adjudication. Risk: a new gate input with a
   stored witness.
3. Let a co-occurring drop pass on a second channel (`ability-cast`,
   asking `tray.gold_witness`'s numeral and `ability-audio` at the drop).
   Passing every one with a numeral or the audio covers
   [metric:own_cast/residuals@riot-21#cf_witnessed_cooccur_covered=552] but holds [metric:own_cast/residuals@riot-21#cf_witnessed_cooccur_beyond=14]
   beyond Riot; a numeral alone, or the numeral with the audio, should trade
   back the new excess. It also takes the Phoenix casts that fixes 1 and 2
   leave co-occurring. Iso's Kill Contract needs its own rule: X empties
   while the tray is drawn and C and Q fall onto the dark tray after it.
4. Count Clove's charges held at a death against the minimap's dead-Clove
   circle and Ruse discs [domain:abilities/clove-ruse-minimap-duration]
   (`ability-state` for the charges; a minimap reader from
   `prototypes/clove_circle.py`, unwired). Up to [metric:own_cast/residuals@riot-21#class1_Clove_E=12] casts; a
   new reader.
5. Pass a forced or death-lead drop that a later own ult line or a numeral
   witnesses (`ability-cast`): Not Dead Yet's X empties on the death screen
   before its line, and Phoenix X misses include forced drops after a
   second life and at deaths no stored badge calls a second life. Few casts, low risk.
6. Bridge a refused run longer than `GAP_S` when the slot's numeral appears
   or its icon dims across it (`tray-drop`), and read Trailblazer's tinted
   view [domain:hud/controlled-entity-view-tint] by the Q icon turning red.
7. For the excess: a gold drain on Skye's Regrowth is no spend
   (`ability-cast`, by its resource-bar fact), and a fall with no numeral,
   no icon change and no sound beside teal crossing the bar is no drop
   (`tray-drop`). Together they remove the [metric:own_cast/residuals@riot-21#class6_eye_regrowth_pool=2]
   Regrowth picks and the [metric:own_cast/residuals@riot-21#class6_eye_flash_streak_or_tint=3] crossing ones
   of the [metric:own_cast/residuals@riot-21#class6=8] excess casts; the other [metric:own_cast/residuals@riot-21#class6_eye_real_spend=3] are real
   spends whose slots' extra casts no pick explains.

Class 7 has no candidate and no time; the audio owner scores only drops the
gate passes, so no channel looks for a cast the tray missed. Riot-side
counting (class 5) holds no rule: no domain fact says Riot counts a cast the
tray cannot show, and ability rules are not inferred by analogy
[domain:abilities/ability-rules-are-unique].

## The cast gate against Riot's counts (2026-10-05)

Riot's match records count the player's casts per ability, which scores the
gate's own casts on the 21 Riot-paired matches: covered is the lesser of
ours and Riot's per session and ability, beyond is ours over Riot's.
Riot's counts are evaluation truth only. A dev half was fixed before
measuring (sha1 of `own-cast-gate:` and the session, even = dev), and
`prototypes/own_cast_gate_eval.py` scores each half apart.

Two rules first released here were chosen on the held half, against that
plan, and `player-cast-0.13.0` withdrew both. The pool rule (`0.11.0`) was
aimed at two Regrowth excess casts on the held matches `b7d24102a6f6` and
`e37fdeca944f`; dev held no such drop. It also reasoned a Regrowth mechanic
from the gold of other abilities, which the domain leaves to the player
[domain:hud/ability-tray-restocked-charge-gold]. A clause of the revive rule
ran a revive's dead span on past the revive for a bridged drop, chosen from
a held eye check at `b7d24102a6f6` 1866.5 s; the one dev drop it reached the
gate refuses anyway. The figures this section first printed for the held
half rested on both, and are not clean held figures. `player-cast-0.14.0`
refuses the same two Regrowth drops as `pool_rest`, on the player's answer
of 2026-10-05 [domain:abilities/skye-regrowth-gold-bar-partly-spent], not on
the held measurement.

At `player-cast-0.8.0` the gate covered
[metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_dev_covered=239] of
[metric:tray/own-cast-gate@riot-21#dev_riot=300] dev casts with
[metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_dev_beyond=2] beyond, and
[metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_held_covered=286] of
[metric:tray/own-cast-gate@riot-21#held_riot=310] held casts with
[metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#baseline_held_beyond=6] beyond.
The rules that stand at `player-cast-0.14.0`, each a transition the state
model names:

- *revived* (`0.9.0`): a teammate Sage's Resurrection of the player undoes
  the death before it, as Clove's own Not Dead Yet did
  [domain:killfeed/revive-entries]; the player stays dead until the revive.
  Since `0.14.0` a NULL/cmd stabilisation of a KAY/O player counts too: he
  gets his kit back as before the down
  [domain:abilities/kayo-null-cmd-stabilise-restores-kit]. The stored
  corpus holds no NULL/cmd revive, so no verdict moved.
- *a line witnesses the ult* (`0.10.0`, `0.12.0`): the player's own ult
  line [domain:abilities/caster-hears-own-ult-line] passes an X drop the
  tray dates badly, on a dark tray, at the death that ends the kit (Run It
  Back's pips fall at its end
  [domain:abilities/phoenix-run-it-back-expiry-flash]) or beside another
  slot's drop. The passed drop rests on the line, and `ult_cast` never binds
  it as that line's witness.
- *a numeral witnesses a spend* (`0.12.0`): a co-occurring drop of Recon
  Bolt or Guiding Light passes where its restock numeral appeared or
  restarted [domain:hud/ability-tray-restock-countdown].
- *the rest of a pool* (`0.14.0`): a gold-only drop of Skye's Regrowth
  spends the rest of a pool the gate counted at its opening, and is
  refused as `pool_rest` [domain:abilities/skye-regrowth-gold-bar-partly-spent].

With them the gate covers
[metric:tray/own-cast-gate@riot-21#gate_dev_covered=259] dev casts with
[metric:tray/own-cast-gate@riot-21#gate_dev_beyond=2] beyond, and
[metric:tray/own-cast-gate@riot-21#gate_held_covered=300] held casts with
[metric:tray/own-cast-gate@riot-21#gate_held_beyond=6] beyond. Without the
own lines, dev falls to
[metric:tray/own-cast-gate@riot-21#no_lines_dev_covered=246] and held to
[metric:tray/own-cast-gate@riot-21#no_lines_held_covered=296]. At
`player-cast-0.13.0` held was
[metric:tray/own-cast-gate@riot-21~2026-10-05T06:25:44#gate_held_beyond=8]
beyond; the two that `pool_rest` removed were the Regrowth drops at
`b7d24102a6f6` 375.1 s and `e37fdeca944f` 1714.0 s. Of the held excess
left, one is the bridged Q drop at `b7d24102a6f6` 1866.5 s, and one is a
Recon Bolt at `59c70f1ef720` 2544.5 s that is real by eye, so that slot's
extra cast lies elsewhere. The other four were beyond at
`player-cast-0.8.0`.

The stored `killfeed_portrait` streams are a version behind, so the gate
reads no second life anywhere. Re-read at the current version from the crop
cache (`own_cast_gate_eval.py --reread-second-lives`), they gave
[metric:tray/own-cast-gate@riot-21~2026-10-05T05:53:07#b_second_lives=13]
second lives on the five Phoenix matches. Fed to the gate, they raise dev to
[metric:tray/own-cast-gate@riot-21#reread_dev_covered=263] with
[metric:tray/own-cast-gate@riot-21#reread_dev_beyond=2] beyond and held to
[metric:tray/own-cast-gate@riot-21#reread_held_covered=301] with
[metric:tray/own-cast-gate@riot-21#reread_held_beyond=6] beyond, once a
corpus refresh stores those streams.
