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
| `charges` | 0..`max_charges`, or an interval `[lo, hi]` when unobserved | `max_charges` per ability from `domain/abilities.toml` (`*-tray-charges`) and the mechanics sheet; no ability has more than two today [domain:hud/ability-tray-charge-segments] |
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
