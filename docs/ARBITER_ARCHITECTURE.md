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

The strongest argument against: reopening one verdict at a time is a
greedy repair, not a joint optimum. Two surprises that each need the
other's revision can leave both verdicts wrong where a joint fit would
settle them, and the arbiter grows past names into life and reachability,
so one defect touches every name. The guards: a rerun that raises a new
surprise is stored as an unresolved pair, never chased; the arbiter asks
each constraint's owner and computes none; and each stage keeps its own
stamp, so a fragment change never restamps death names.

**Entity model.** Ten player entities per match, keyed by side and lineup
slot (gap 1 of `docs/ENTITY_EVENTS.md`), each named by the side verdict;
per round, each player's life intervals and the fragments, deaths and
abilities bound to it. Each ability entity has one owner slot or an honest
unknown.

**Stages,** each reading earlier stages' stored verdicts:

1. *Lineup:* `assign_side` over top bar and scoreboard claims.
2. *Deaths and life:* victim and killer names; each slot's life intervals,
   revives from the closed set [domain:rounds/resurrection-mechanics],
   roster counts as an audit.
3. *Fragments* to living slots (section 5).
4. *Ability owners* (section 6).
5. *Objects:* the spike carrier.

**Reopening on surprise.** A surprise in a later stage reopens the one
earlier verdict it contradicts, the general form of widening on surprise
(`AGENTS.md`). That verdict reruns once with the new evidence; the original,
the revision and the surprise are stored together. A verdict reopens at
most once per surprise, the rerun reads the same stored witnesses plus that
surprise, and nothing iterates to a fixed point or becomes a joint fit.
*Prediction:* reopening is a very small minority of decisions. The metric
is the reopened share of verdicts per session and stage
(`arbiter_architecture/reopen`, `reopened_share`); it is falsified if it
exceeds 5% on any of the three sessions of section 7, which would mean the
stage order is wrong, not the rule.

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

The player approved the rule change, and `AGENTS.md` carries it since
2026-09-30: the "Every agent name is decided by `adjudication.identity`"
bullet names the aggregator over one arbiter per channel, the channel
clause and `rests_on`, and "Continue the prior" names reopening as the
general form of widening on surprise. The rule is applied; the plan stays
proposed until its stages are built.

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
   a birth at the frontier predicts an agent not now seen. A different
   enemy's icon is believed to draw over a "?", not erase it
   [domain:minimap/last-known-mark-under-enemy-icon-belief], so an overlap
   keeps the "?" its own; section 7's stage 1 runs that belief's test.
2. **Check cheaply.** The pooled glyph confirms the prediction when its
   margin clears the arbiter's gate. With one candidate left, elimination
   assigns it and `depends_on` the other four slots' bindings and deaths. A
   glyph that favours another candidate is a disagreement; the name is
   withheld.
3. **Widen on surprise.** A glyph favouring a slot a constraint excludes is
   a stored surprise naming the constraint, and it reopens the verdict it
   contradicts (section 2). Dashes and teleports break reachability
   [domain:abilities/movement-abilities-are-dashes-and-teleports]. The
   mechanics sheet holds a *candidate list*, derived from the catalogue's
   wiki function tags and descriptions and not yet confirmed; it names Raze's
   Blast Pack and Phoenix's Run It Back, which `track`'s movement classes
   lack. Until
   the player confirms it, an unreachable binding is a surprise, never a
   veto.

**Decoys.** Yoru's FAKEOUT draws an extra player icon
[domain:abilities/yoru-fakeout-player-icon]. With Yoru in the lineup, an
icon beyond the side's living agents is a candidate FAKEOUT, which stage 4
owns as Yoru's ability entity; stage 3 never makes it a sixth enemy, and its
glyph is no witness of Yoru's place.

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
[domain:minimap/device-dim-on-deactivation]. Cypher's Trapwire and Spycam,
Deadlock's Sonic Sensor, Vyse's Razorvine, Veto's Chokehold, Viper's Poison
Cloud and Toxic Screen and Astra's placed stars persist too
[domain:abilities/cypher-trapwire-persists-after-death]
[domain:abilities/cypher-spycam-persists-after-death]
[domain:abilities/deadlock-sonic-sensor-persists-after-death]
[domain:abilities/vyse-razorvine-persists-after-death]
[domain:abilities/veto-chokehold-persists-after-death]
[domain:abilities/viper-poison-cloud-persists-after-death]
[domain:abilities/viper-toxic-screen-persists-after-death]
[domain:abilities/astra-placed-stars-persist-after-death]; whether they
dim is unasked. Omen's Dark Cover stays active
[domain:abilities/omen-dark-cover]. The set may be incomplete. An ability
seen after its owner's death with no fact is a stored surprise, neither a
new cast nor a bar.

**Activation after death.** Whether a device placed while its owner lived
can be activated by a second press after the owner dies, as Vyse's Arc
Rose placed and then flashed, is unknown; the mechanics sheet asks it per
ability. Until answered, such an activation is a stored surprise.

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
   every split and surprise viewed on a sheet before any claim; the
   reopened share recorded against section 2's prediction, logged first.
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
acceptance follows AGENTS.md, which defers any corpus rerun until
training on the replay data is finished.

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

The player answered this plan's five questions on 2026-09-30, and the
answers stand as the facts cited in sections 5 and 6. What remains is per
ability, on [ABILITY_MECHANICS_SHEET.md](ABILITY_MECHANICS_SHEET.md):
which movement candidates to confirm or strike, which placed devices can be
activated after their owner dies, and which other abilities persist.

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
