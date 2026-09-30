# Event gaps: what a consumer cannot read from the stored events

`reticle view` draws a round from emitted events alone
(`reticle/view_events.py` loads, `reticle/round_view.py` draws). Building it
showed, stream by stream, which fields a consumer needs and no event carries.
This page records that census on `bfad2778a372`
(`C:/Users/grant/Videos/2026-08-24 14-45-35.mp4`, Split) for the design of a
unified entity-event layer. The rule it serves is in `AGENTS.md`: a missing
field goes into the owning event, never into a recomputing consumer.

Regenerate the measured table, with row counts, versions and the fraction of
rows that carry each field, with:

```powershell
.\.venv\Scripts\python.exe -m reticle view SESSION --gaps   # stored data only
```

The declarations behind it (owner, time base, entity key, identity handling,
and the path of every field in each row) are `view_events.STREAMS`; change the
declaration there and this page together.

## The fields the architecture needs

Every stream is scored against one field list: `event_id`, `version`, `t_ms`,
`t_end`, `entity_id`, `entity_kind`, `identity`, `identity_status`,
`alternatives`, `position`, `orientation`, `state`, `uncertainty`,
`evidence`. "Has" means most rows carry the field; "partial" means some do;
"lacks" means no row does, or the field is declared and null everywhere.

## Per stream

### round_entity (owner `round-entity-session`, `round_entities`)

- **Time base:** capture ms of the stored `ally_icon` frame (the 15 Hz crop cache).
- **Entity key:** `entity_id` `<sid>:R<n>:E<k>/P<j>`, scoped to the round. Entity rows join on `id`.
- **Identity:** the observation's `name` is a placeholder (`ally 3`, `you`). The agent sits on the entity row (`agent`, `teammate_key`), and the viewer joins it by `entity_id`.
- **Has:** event_id (`observation_id`), version, t_ms, entity_kind, identity_status, position, state, evidence.
- **Partial:** entity_id (refused observations have none), identity, alternatives.
- **Lacks:** t_end, orientation, uncertainty.
- **Note:** there is no facing, radius or position uncertainty. `state` holds the association state (continuation, refit), not the game state (alive, dead). The stream covers self, ally and barrier only. Spectated icons are still named `you`, a known defect.

### team_vision (owner `team-vision`, `team_vision`)

- **Time base:** capture ms of the crop-cache minimap frame.
- **Entity key:** a per-icon `track_id`, a tracker association id in its own key space. Nothing links it to round_entity's `entity_id`.
- **Identity:** none. Icons carry a role (self, ally) and no agent.
- **Has:** version, t_ms, entity_kind, position, state, evidence.
- **Partial:** orientation (an icon whose facing is not read casts no cone).
- **Lacks:** event_id, t_end, entity_id, identity, identity_status, alternatives, uncertainty.
- **Note:** cones are stored only as the frame's union mask (`observable`). No per-icon cone, event id or facing uncertainty exists. The viewer can cite a frame only by its line number.

### death (owner `death-victim`, `adjudication.death`)

- **Time base:** capture ms of the killfeed entry's first sample (2 Hz).
- **Entity key:** `death_id` `death:<sid>:<t>:<slot>`. Victim and killer are agent names with no minimap entity id.
- **Identity:** victim and killer by name. The arbiter's distribution is in `death_identity`.
- **Has:** event_id, version, t_ms, entity_id, entity_kind, identity_status, alternatives, state, evidence.
- **Partial:** identity (abstained verdicts carry no victim).
- **Lacks:** t_end, position (declared as `location` and null on every row), orientation, uncertainty.

### death_identity (owner `agent-identity`, `adjudication.identity`)

- **Time base:** the death's `t_ms`.
- **Entity key:** `subject_entity_id`, which is the death's `death_id`.
- **Identity:** a distribution over agents for each death.
- **Has:** event_id, version, t_ms, entity_id, entity_kind, identity, uncertainty.
- **Lacks:** t_end, identity_status, and alternatives, position, orientation, state and evidence (all declared by the event contract, and empty).
- **Note:** the file holds two producers: `identity_distribution` rows from the arbiter and `entity_deleted` rows stamped by death adjudication.

### ability_state (owner `ability-state`, `adjudication.ability_state`)

- **Time base:** state rows are intervals `t_first_ms..t_last_ms` over tray samples (2 Hz). Verdicts sit at `t_ms`.
- **Entity key:** a slot letter plus `agent_entity_id` `<sid>:ally:slot:0`, a third key space.
- **Identity:** the player's agent only.
- **Has:** version, t_ms, entity_kind, state.
- **Partial:** t_end, entity_id, identity, uncertainty, evidence (state rows carry them, verdict rows do not).
- **Lacks:** event_id, identity_status, alternatives, position, orientation.
- **Note:** this is the player's own kit. No stream holds an ability entity, position or owner for a teammate or an enemy.

### ability_shape (owner `ability-shape`, `ability_shapes`)

- **Time base:** the player's cast time.
- **Entity key:** none; rows are keyed by `cast_t_ms` and slot.
- **Has:** version, t_ms, entity_kind, identity, position, state, uncertainty.
- **Lacks:** event_id, t_end, entity_id, identity_status, alternatives, orientation, evidence.
- **Note:** one fit per player cast, with no lifetime and no end.

### smoke and smoke_owner_identity (owners `minimap-smoke` and `agent-identity`)

This session has neither stream, so the census shows the declared schema,
unmeasured. The viewer's smoke drawing is untested on real rows.

- **Time base:** the track interval `first_ms..last_ms`. The owner identity sits at `first_ms`.
- **Entity key:** a `track` index. The smoke row carries no entity id string; `smoke_owner` builds `<sid>:smoke:<first_ms>:<track>` itself, and the viewer rebuilds the same key to join the two. That rebuild is a restated rule, and the smoke row should carry the key.
- **Identity:** the owner's distribution is in `smoke_owner_identity`.
- **Smoke lacks:** event_id, entity_kind, identity, identity_status, alternatives, orientation, evidence. It stores one position per track.

### ult_cast and ult_cast_identity (owners `ult-cast` and `agent-identity`)

- **Time base:** the voice line's audio peak.
- **Entity key:** `entity_id` `<sid>:ult_cast:<t>:<template>`. The identity row's `subject_entity_id` names it.
- **Identity:** agent and side from the voice line; the distribution is in `ult_cast_identity`.
- **ult_cast has:** version and t_ms on every row. Event rows also carry event_id, entity_id, entity_kind, identity, identity_status, state and uncertainty; the `coverage` row and the `missed_line` rows do not, so a missed line has no id to cite.
- **ult_cast lacks:** t_end, alternatives, position, orientation, evidence. The cast is heard, not seen: no caster entity on the minimap.
- **ult_cast_identity lacks:** t_end, entity_kind, identity_status, alternatives, state, and position, orientation and evidence (declared, empty).

### spike (owner `spike-observation`, `spike`)

- **Time base:** capture ms of the 1 Hz grid.
- **Entity key:** none. The carrier is a roster `marker.slot`.
- **Identity:** none.
- **Has:** version, t_ms, entity_kind, position, state, uncertainty, evidence.
- **Lacks:** event_id, t_end, entity_id, identity, identity_status, alternatives, orientation.
- **Note:** the spike has no entity id, and a planted spike's position is not stored.

### spike_carrier (owner `spike-carrier`, `adjudication.spike_carrier`)

- **Time base:** `carrier_lost` and `disagreement` rows at `t_ms`; round rows once per round.
- **Entity key:** a roster `slot`, marked `depends_on: agent-from-slot`.
- **Identity:** none; a slot, not an agent.
- **Has:** version, state. **Partial:** t_ms, evidence.
- **Lacks:** event_id, t_end, entity_id, entity_kind, identity, identity_status, alternatives, position, orientation, uncertainty.

### ping (owner `ping-event`, `ping`)

- **Time base:** the ping's first sighting, shown for its stored `lifetime_s`.
- **Entity key:** none. **Identity:** none; who pinged is not stored.
- **Has:** version, t_ms, t_end, entity_kind, position, orientation.
- **Lacks:** event_id, entity_id, identity, identity_status, alternatives, state, uncertainty, evidence.

### killfeed_name, killfeed_portrait, killfeed_weapon (owners `killfeed-name-descriptor`, `killfeed-portrait`, `killfeed-weapon-descriptor`, all `killfeed`)

- **Time base:** capture ms of the 2 Hz crop cache.
- **Entity key:** `observation_key` `<sid>:<frame>:<slot>:<role>` for names and portraits; the weapon rows have only `frame_idx` and slot.
- **Identity:** none. Names are descriptors resolved in `adjudication.killfeed_names`; portraits are composition vectors named in death witnesses.
- **Has:** version, t_ms, position, state, evidence; names and portraits also event_id and entity_kind, and portraits uncertainty.
- **Lacks:** t_end, entity_id, identity, identity_status, alternatives, orientation. The weapon rows also lack event_id, entity_kind and uncertainty.
- **Note:** these are per-sample observations. No entry id binds a sample to its death.

## What no stream stores

| Need | Owner to extend | Gap |
|---|---|---|
| Enemy icons | `ally-candidates` (`minimap`) | No stream stores an enemy icon's position, facing or name; `round_entity` covers self, ally and barrier. |
| Per-icon cones | `team-vision` | The union mask cannot say whose cone saw what. |
| Teammate and enemy abilities | `ability-detection`, `ability-owner` | `ability_state` is the player's tray; `ability-owner` has no owner module. |
| One row for an icon's facing and identity | `round-entity-session`, `team-vision` | The entity id and the track id live in separate key spaces, so facing and identity never meet. |
| Death position | `death-victim` | `location` and `killer_location` are declared and null. |
| The killfeed entry | `killfeed-event` | The per-frame kill and death verdict lives in the L1 hud table, not in an event stream. |

## Across streams

- **Five key spaces.** Round entities, team-vision tracks, ability slots, roster slots and death ids name the same players with no shared key. A consumer can join them only by recomputing an association, which the rule forbids.
- **Ids are missing on most sampled streams.** team_vision, ability_state, spike, spike_carrier, ping and killfeed_weapon rows carry no event id; the viewer cites them as `<stream>@<line>`, which a rewrite of the file breaks.
- **Intervals are rare.** Only ability_state, smoke and ping store an end. The viewer holds every other sample until the next or until a fixed staleness, and that hold is a display choice, not an event fact.
- **Orientation** is measured on team_vision icons and ping only; round_entity, which carries the identity, has none.
- **Refusal is readable** wherever it is stored: round_entity's `identity_status` and `state`, death's `status` and `reason`, and team_vision's `widget`. The viewer draws these amber with the stored reason.
