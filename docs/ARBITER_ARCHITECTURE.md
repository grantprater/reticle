# Arbiter architecture

A plan, proposed 2026-09-30. It builds nothing. Rules live in `AGENTS.md`;
this plan cites them.

The player set three directions. An unnamed enemy track is a fragment,
and tracking an enemy means assigning each sighting to one of the lineup's
living five; the glyph confirms a name rather than carrying it. Every
ability belongs to an agent in the match. Each channel gets one arbiter,
and one aggregator over them emits the finalized events. Today enemy names
rest on per-frame glyph claims alone, the death victim only vetoes, and some
tracks chain two enemies.

## 1. Channel arbiters

A channel's readings share pixels and failure modes, so they are pooled
inside the channel first. Each channel has one **arbiter**, the single owner
that publishes to the aggregator; its other owners stay as parts with their
own entries and stamps. Per entity it publishes the channel's events, its
pooled `identity_claim`s (one witness, however many frames saw it), its
internal checks and its surprises.

| Channel | Arbiter | Identity claims |
|---|---|---|
| Minimap | `round_entities` | glyph claims pooled per fragment; X and "?" bindings by place and time |
| Killfeed | `adjudication.death` | killer and victim portraits; name clusters |
| Top bar | `lineup` | slot agents; alive counts carry no name [owns:alive-count] |
| Scoreboard | `adjudication.scoreboard` | row agents; a dimmed row is dead [domain:rounds/scoreboard-dim-is-dead] |
| Tray | `adjudication.tray_kit` | whose kit shows [domain:hud/tray-after-player-death] |
| Centre of screen | `adjudication.combat_report` | combat report rows |
| Audio | `adjudication.ult_cast` | ult line agents |

**The rule between channels.** A channel arbiter may take from another
channel only a *candidate set*, a *window* in time or place, or a *gate*
(alive, menu open, widget drawn), and only from stored verdicts of an
earlier stage (section 2). It never takes another channel's verdict on the
same entity as evidence. A result so shaped declares it: a claim
`depends_on` the entities whose verdicts set its candidates, an observation
`rests_on` the stream, version and instants of its prior, and a binding
keyed by another channel declares `binding_from`. The aggregator counts a
claim as independent only for questions its priors leave untouched:
`docs/PRIOR_DRIVEN_READERS.md`'s guards 1-4, applied between channels.

## 2. The aggregator

**Decision: the aggregator is `adjudication.identity`, generalised from
naming entities to assigning every round entity to one of the ten agents;
`entity_events` stays the only emitter.** The arbiter already holds the two
constraints that matter most, five distinct agents per side
[domain:rounds/agent-uniqueness] and dead teammates barred from minimap
pieces (`assign_ally_pieces`), and the `depends_on` and `binding_from`
machinery that weighing once needs. A new universal adjudicator would
repeat the never-built graph solver of
[ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md). Deciding inside `reticle
project` would break the premise that every consumer row is an owner's
answer ([ENTITY_EVENTS.md](ENTITY_EVENTS.md), section 3).

The strongest argument against: the arbiter grows past names into life and
reachability, and one defect touches every name. The guard: it asks each
constraint's owner and computes none, and each stage keeps its own stamp, so
a fragment change never restamps death names.

**Entity model.** Ten player entities per match, keyed by side and lineup
slot (gap 1 of `docs/ENTITY_EVENTS.md`), each named by the side verdict;
per round, each player's life intervals and the fragments, deaths and
abilities bound to it. Each ability entity has one owner slot or an honest
unknown.

**Stages,** each reading only earlier stages' stored verdicts; nothing
iterates to a fixed point:

1. *Lineup:* `assign_side` over top bar and scoreboard claims.
2. *Deaths and life:* victim and killer names; each slot's life intervals,
   revives from the closed set [domain:rounds/resurrection-mechanics],
   roster counts as an audit.
3. *Fragments* to living slots (section 5).
4. *Ability owners* (section 6).
5. *Objects:* the spike carrier.

**Constraints.** One icon per agent per frame; no icon after the death mark
[domain:minimap/death-icon-becomes-mark]; reachability from the last-known
place, licensed by `track` [owns:teleport-licence]; elimination; no cast
while dead [domain:abilities/no-cast-while-dead]. An unknown prerequisite
yields `unknown`, never a veto.

**Disagreements and surprises.** A claim a constraint excludes, or two
channels naming different agents, is one stored row: entity, both values,
witness versions, the constraint's owner and `returns_to`. The name is
withheld and the row goes to the ledger. Audit rows are stored apart;
agreements are counted, never scored.

## 3. The identity-arbiter rule

The proposal keeps the rule, with the arbiter as the aggregator, and adds
the channel clause. The draft replaces the bullet and adds a few lines
to an `AGENTS.md` already over its budget. Not applied; the player
decides.

> - **Every agent name is decided by `adjudication.identity`**, the
>   aggregator over one arbiter per channel, per entity and per side. Each
>   channel pools its own readings and publishes `identity_claim`s through
>   its arbiter; from another channel it takes only a candidate set, a
>   window or a gate, never that channel's verdict on the same entity.
>   Owners that bind a death, track, row or ability to a witness supply the
>   entity key and ask the arbiter. A claim that rests on another entity's
>   verdict declares `depends_on`; an observation a prior placed declares
>   `rests_on`. An ownership entry whose output carries a name declares
>   `names_agents = true` and defers to `agent-identity`. OWNERSHIP makes an
>   undeclared name producer, or an identity event built outside the
>   arbiter, an ERROR, and the event validator rejects the event.

## 4. Ownership

Every current question, by its owner's place. A new `channel` key on each
entry names its arbiter; OWNERSHIP enforces one arbiter per channel. No new
layer is needed in `architecture.toml`.

| Place | Questions | Moves |
|---|---|---|
| Minimap | round-entity-session, widget-drawn, self-position, ally-candidates, minimap-icon-disposition, ally-portrait-features, self-icon-portrait, enemy-icon, last-known-mark, enemy-track-session, round-entity, minimap-origin, icon-pose, self-cone-origin, viewcone, drawn-light, team-vision, light-support, minimap-dark, minimap-smoke, smoke-owner, ping-event, spike-observation, map-furniture, position-belief, ability-detection, ability-shape, ability-gate, ability-icon, ability-hypothesis, ability-phase, ability-appearance | `enemy_tracks` folds into `round_entities`; vote-change splits go to `round-entity` |
| Killfeed | death-victim, killfeed-event, killfeed-portrait, killfeed-weapon-descriptor, killfeed-name-descriptor, killfeed-name-continuity, killfeed-second-life-badge, killfeed-weapon | its roster and scoreboard claims name their channels |
| Top bar | agent-from-slot, alive-count, scoreline, hud-invariant | `lineup` leaves `transitional` by its stated exit |
| Scoreboard | scoreboard-row-agent, scoreboard-row, scoreboard-strip, scoreboard-presence | none |
| Tray | tray-kit, tray-drop, tray-icon, ability-state, ability-cast | none |
| Centre | combat-report-round, combat-report-read, screen-outline, menu-open | `menu-open` is a gate any channel may read |
| Audio | ult-cast, ult-line | none |
| Aggregator | agent-identity, identity-channel-reliability, channel-disagreement, spike-carrier, player-agent, ability-owner | new `agent-alive`; `player-agent` moves from `lineup`; `ability-owner` gets `adjudication.ability_owner` as binding owner; reliability per arbiter |
| Projection | entity-event | none |
| Shared | source-identity, extraction-profile, map-geometry, map-occluders, minimap-widget-frame, domain-fact, domain-hypothesis, fact-subject, frame-primitive, evidence-span, capture-stall, hud-scan, portrait-descriptor, track-continuation, teleport-licence, round-bounds, in-game-time, review-question, reader-capability, evidence-plan, capture-queue, ability-evidence, credit-ledger, coaching-state | the aggregator asks `track` for reachability |

## 5. Enemy entities as the living five

The minimap arbiter publishes **fragments**: runs of enemy icons that
`round_lifetimes` joins, with pooled glyph claims over the side's five, the
birth's class against the light (I2 of
[ENEMY_VISION_COUPLING.md](ENEMY_VISION_COUPLING.md)), "?" marks (I3), and
the X bound by place and time, with no name.

Stage 3 walks each round's fragments in time order:

1. **Predict.** Candidates are the slots alive at the fragment's birth, less
   those bound to a fragment in the same frame. A birth deep in old light
   beside a fragment that just ended, or at a "?" before it fades
   [domain:minimap/last-known-mark-timing], predicts that fragment's agent;
   a birth at the frontier predicts an agent not now seen.
2. **Check cheaply.** The pooled glyph confirms the prediction when its
   margin clears the arbiter's gate. With one candidate left, elimination
   assigns it and `depends_on` the other four slots' bindings and deaths. A
   glyph that favours another candidate is a disagreement; the name is
   withheld.
3. **Widen on surprise.** A glyph favouring a slot a constraint excludes is
   a stored surprise naming the constraint, and it reopens the round's
   assignments back to the last anchor (a bound death or a confirmed name).
   Movement abilities can break reachability
   [domain:abilities/minimap-dash-or-teleport-trace], so until they are
   recorded an unreachable binding is a surprise, never a veto.

**Honest unknowns.** A fragment with several candidates and no margin
survives as an `enemy` entity with `agent: null`, its candidates and its
reason; the projection withholds the name, not the track.

**Splits.** A fragment whose glyph votes change with a margin splits only
where a swap could happen: an observation gap, or another enemy within
stacking distance. Otherwise the change is a stored glyph surprise.

**The death victim as a witness.** An X bound by place and time makes the
killfeed victim a claim on the fragment, `binding_from` that binding, so the
glyph and the victim meet as two channels. Where the victim's verdict used
that fragment's glyph, stage 3 uses it only if it resolves with that claim
left out, as [IDENTITY_EXEMPLAR_LOOP.md](IDENTITY_EXEMPLAR_LOOP.md) leaves
out an entry's own portraits.

**The circularity guard.** A binding made because of a name never counts
again as evidence for that name. Each assignment stores `rests_on` (lineup
slots, deaths, co-observed bindings, the X binding, the glyph), and the
aggregator and `adjudication.reliability` drop from a name's witnesses every
row that rests on it. Elimination and continuity names are scored apart.

**The audit.** On a cadence fixed in advance, a fragment is also assigned
with no prior, stored apart, to measure what the prior hides.

## 6. Abilities as owned entities

An ability's owner candidates are its side's slots
[domain:minimap/ability-drawing-colour-by-side] whose kit holds it, alive at
the cast: no ability but Clove's is cast while its owner is dead
[domain:abilities/no-cast-while-dead], and a dead Clove places Ruse smokes
[domain:abilities/clove-smokes-after-death]. Witnesses: a birth at a bound
fragment [domain:abilities/minimap-thrown-ability-icon], which `depends_on`
that binding; an ult line; the player's tray drop while the player lives
[domain:hud/tray-after-player-death].

**Persistence after the owner's death** is a fact per ability. Chamber's
Rendezvous and Trademark and Killjoy's Turret, Alarmbot and Nanoswarm
persist deactivated [domain:abilities/chamber-rendezvous-persists-after-death]
[domain:abilities/chamber-trademark-persists-after-death]
[domain:abilities/killjoy-turret-persists-after-death]
[domain:abilities/killjoy-alarmbot-persists-after-death]
[domain:abilities/killjoy-nanoswarm-persists-after-death], drawn dim
[domain:minimap/device-dim-on-deactivation]; Omen's Dark Cover stays active
[domain:abilities/omen-dark-cover]. The set may be incomplete. An ability
seen after its owner's death with no fact is a stored surprise, neither a
new cast nor a bar.

## 7. Staging

Predictions are logged first; scores use only player labels no parameter
was fitted on. a06f04a0059f
(`C:\Users\grant\Videos\2026-08-26 09-56-37.mp4`) holds
[metric:arbiter_architecture/enemy-name-labels@a06f04a0059f#player_named_enemy_icons=78],
seen by earlier glyph work, so it is the development set; bfad2778a372
(`C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`) holds
[metric:arbiter_architecture/enemy-name-labels@bfad2778a372#player_named_enemy_icons=4];
5822b6646448 (`C:\Users\grant\Videos\2026-08-26 12-38-38.mp4`) holds
[metric:arbiter_architecture/enemy-name-labels@5822b6646448#player_named_enemy_icons=0]
among
[metric:arbiter_architecture/enemy-name-labels@5822b6646448#unnamed_enemy_marks=207]
marked enemies. So a held-out pass comes first: the player names the 5822
marks (`prototypes/label_icon_agent.py`) and a uniform sample of bfad
fragments.

0. **Baseline:** `enemy-track-0.2.0`'s names on those labels. Acceptance:
   `.\.venv\Scripts\python.exe prototypes\enemy_assign.py a06f04a0059f
   bfad2778a372 5822b6646448 --baseline --record`. Evidence: right, wrong
   and unnamed shares per session with Wilson bounds.
1. **Assignment to the living five** from stored rows, in that prototype.
   Acceptance: the same command with `--score --record`. Evidence: on the
   held-out labels the right share rises over stage 0 and the wrong share's
   upper bound does not; elimination and continuity names scored apart;
   every split and surprise viewed on a sheet before any claim.
2. **Wire** into `adjudication.identity` and `round_entities` at new
   stamps, with the `enemy` lane. Acceptance: `.\.venv\Scripts\python.exe -m
   reticle project <session> --lane enemy` on the three sessions, then
   `.\.venv\Scripts\python.exe -m reticle verify --tier fast`. Evidence:
   stage 1's scores reproduced; ledger debt counted per reason.
3. **Channel arbiters:** the `channel` key, pooling, reliability per
   arbiter. Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor`, 0
   errors. Evidence: every name change on the three sessions listed and
   explained by pooling.
4. **Ability owners**, as [ABILITY_DETECTION.md](ABILITY_DETECTION.md) stage
   7. Acceptance: `.\.venv\Scripts\python.exe -m reticle project <session>
   --lane ability`. Evidence: owners scored on the ability recall labels.
5. **Allies** through the same assignment, against `assign_ally_pieces` on
   the ally labels.

**The corpus.** No stage decodes. Each change runs on the three sessions;
the corpus gets one storage rerun of the streams `reticle plan` names,
folded into the player's next unified corpus run.

## 8. Risks and falsifiers

- **Cascade:** a wrong death name spreads by elimination. Falsifier:
  elimination names wrong more often than glyph names on held-out labels.
- **Lock-in:** the prior keeps an early mistake. Falsifier: the audit
  disagrees with the prior more often than the glyph errs.
- **Over-splitting.** Falsifier: fragments per labelled life rise with no
  gain in right names.
- **A wrong X binding** carries a wrong victim. Falsifier: the death
  witness flips a labelled-right glyph name.
- **The arbiter outgrows names.** Falsifier: a stage must read a reader
  stream rather than an owner's verdict.

## 9. Questions for the player

`domain/*.toml` answers none of these.

1. When a different enemy appears at a red "?"'s place, does the "?"
   vanish? [domain:minimap/last-known-mark-timing] measured the "?" ending
   when an icon returns, not whose.
2. Does any ability draw an extra player icon, such as a decoy, on the
   other team's minimap?
3. Per ability, does it move its agent farther than running would? A new
   mechanics-sheet column.
4. Does a second press on a device placed while alive count as a cast
   [domain:abilities/no-cast-while-dead]?
5. Do these persist after their owner's death: Cypher's Trapwire and
   Spycam, Deadlock's Sonic Sensor, Vyse's Razorvine, Veto's Chokehold,
   Viper's Poison Cloud and Toxic Screen, Astra's placed stars?

## 10. What the existing documents become

| Document | Kept | Replaced |
|---|---|---|
| [ADJUDICATION_DESIGN.md](ADJUDICATION_DESIGN.md) | objective, contracts, invariants, revision, validation, position belief | graph solver and `reticle adjudicate` |
| [STATISTICAL_ADJUDICATOR.md](STATISTICAL_ADJUDICATOR.md) | the minimap's error model | nothing |
| [ENTITY_EVENTS.md](ENTITY_EVENTS.md) | the projection as sole emitter; gap 1's slot keys | nothing |
| [SCENE_MODEL.md](SCENE_MODEL.md) | stages 1-4, the minimap's reader | section 1's state and stage 5's mesh, by the aggregator |
| [ABILITY_ENTITY_INFERENCE_DESIGN.md](ABILITY_ENTITY_INFERENCE_DESIGN.md) | entity model, phases | owner alternatives, by stage 4 |
| [ALLY_MINIMAP_IDENTITY.md](ALLY_MINIMAP_IDENTITY.md) | findings | its open track key, by pooling |
| [IDENTITY_EXEMPLAR_LOOP.md](IDENTITY_EXEMPLAR_LOOP.md) | findings; leave-one-out | nothing |
| [ENEMY_VISION_COUPLING.md](ENEMY_VISION_COUPLING.md) | invariants and adjudicator, in the minimap arbiter | nothing; I2 and I3 also feed stage 3 |
| [ABILITY_DETECTION.md](ABILITY_DETECTION.md) | every stage | section 14's owner, by stage 4 |
| [PRIOR_DRIVEN_READERS.md](PRIOR_DRIVEN_READERS.md) | the pattern; guards 1-4 | nothing |

No plan is superseded whole, so none moves to `docs/archive/`.
