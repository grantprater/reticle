# The replay layer

Status: live, 2026-10-05. The schema of a match's state as its kept replay
holds it, and the read API. The owner is `reticle/replay_layer.py`
(`reticle ownership replay tables`); the use policy is
[EXTERNAL_GROUND_TRUTH.md](EXTERNAL_GROUND_TRUTH.md)'s; the entity model it
serves is [ENTITY_STATE.md](ENTITY_STATE.md)'s (sections 1 and 9).

## Why one layer

Every consumer of a replay re-derived the same joins: net guids to players,
the replay clock to the capture clock, interpolation, world units to minimap
pixels, actors to abilities and casters. The layer does them once per match,
versioned, so the slot model, the scorers, the overlay and the episode
builder read one schema and never open vrfkit's export.

## Where, and how it is built

`<store>/analysis/replay-layer/<match>/`: `layer.json` (the head) and one
Parquet file per table. `reticle replay-layer MATCH|SESSION`, `--all`, or
`--status`. It reads stored data only: the vrfkit parse, and for a captured
match the Riot record, the stored deaths, the baked geometry, the `ally_icon`
frame grid and self track, and the lineup. `reticle plan SESSION` names it absent or stale
for every session whose kept replay names it; `doctor` (REPLAY_LAYER) errors
while one is. `l2/` holds the pipeline's observation tables, served by
`Store` to readers and consumers; truth there would sit one call from a
reader, so the layer lives with the other evaluation truth in `analysis/`.

The held-out match (`replay_layer.HELD_OUT`) is built so `plan` is complete;
its head carries no summary, and no command prints its contents.

## Clocks, units, sources

- `t_rep`: the replay's server clock, ms.
- `t_cap` (`tcap_*` in `rounds` and `lives`): the capture's clock, ms,
  `t_rep + a_ms`; `a_ms` is fitted on the stored deaths
  (`replay_source.capture_replay_context`). Null without a capture.
- The capturing player (`is_me`, `side_rel`): Riot's where its record names
  him, else the replay player whose path the stored `ally_icon` self track
  follows (`reticle ownership` `replay-self`, `replay_source.decide_player`).
  The head's `capture.self_identity` holds that pick and, with Riot, its
  agreement; `capture.rests_on` is `ally_icon.self` where the pick decided,
  and `capture.self_refused` names a refused pick, which leaves the clock and
  the map frame standing.
- Positions: world units (cm). `px`, `py`, `facing_px`: baked-widget pixels
  through `MapFrame` of the geometry the head names, null without a capture.
  Both baked maps are north-up, so `facing_px` equals world `yaw` to
  rounding; it is kept so a rotated geometry stays correct.
  `--geometry NPZ` builds on another baked geometry and records it.
- `source`: `truth` for every row this layer writes. `observed`, `inferred`
  and `unknown` are reserved for the vision pipeline's estimates of the same
  fields, so a truth row and the estimate it scores share one schema. An
  `inferred` position carries a belief region in place of a point, in
  ENTITY_STATE.md section 2's form: `region_kind` (`disc`, `cells`),
  `region` (a disc's centre and radius in world cm, or a cell list on the
  baked grid) and `region_basis` (`fit`, `reach`, `spawn`); a `truth` row
  leaves them null. These columns are reserved, not yet written.

## Tables

`entities` (one row per entity; `e` in other tables is the row index):

- players: `entity_id` (`player:<subject>`), `subject`, `agent` (playerLoadouts
  through valorant-api; external truth, never an identity claim),
  `character_id`, `team` (Riot's `teamId` with a record, else spawn group
  `A`/`B`) and `team_basis`, `side_rel` (`ally`/`enemy` to the capturing
  player), `is_me`, `slot_key` (the lineup slot whose resolved verdict names
  the same agent on the same side) and `slot_key_basis`, `guid`/`guids`
  (pawn net guids).
- children (every ability actor with a world position, the ult orbs, the
  planted spike; never the replay controller or other character-folder
  infrastructure): `entity_id` (`child:<guid>`), `guid`, `class`, `class_path`,
  `role`, `code`, `folder`, `ability`, `mapped`/`unmapped_reason`
  (`replay_actors`'s three-part mapping), `tray_key` (the kit slot whose name
  the ability's display name is, `lineup.abilities_for`), `subject`/`agent`/
  `team`/`side_rel` of the owner, `owner_path` (JSON: each actor walked, by
  `Instigator` then `Owner`), `owner_resolved`, `owner_ref_guid`/
  `owner_ref_class` (the actor's own `Owner`), `parent_guid` and
  `parent_basis` (`Owner` naming another child: a wall's segment, a smoke's
  projectile), `predecessor_guid` (a projectile the game object follows,
  `replay_actors.handoff_pairs`), `co_open_guids` (children of the same owner
  and folder opened at the same replay ms: a trapwire's two anchors),
  `t_open_rep`/`t_close_rep`/`t_open_cap`/`t_close_cap`, `close_basis`,
  `round`, `spawn_x`/`y`/`z`/`yaw`, `spawn_px`/`py`, `undecoded` (JSON list of
  `group:field` payloads vrfkit left undecoded on the actor). `t_close_rep`
  is the actor channel's close; the object's end is `t_end_rep`/`t_end_cap`
  (see "Child ends"), with `end_marker`, `end_reason`,
  `t_live_until_rep`/`_cap`, `channel_close_ms` (the channel's close again,
  replay ms), `channel_close_kind`, `end_markers_seen` (JSON) and
  `t_disabled_rep`/`_cap` with `disabled_marker`.

### Child ends

An actor's channel can outlive the object's end as the scorers read it, or
close only at the round's cleanup, 100-250 ms before the next round starts,
or never. Since replay-layer 0.3.1 each child's end is the earliest marker
its class admits (`replay_layer.END_MARKERS`), read class by class on the
development matches, never by analogy:

- `killed`: a damage call on the actor with `bDamageKilledTarget`;
- `destroy_effect`: a one-shot `*Destroy*` effect on the actor;
- `channel_close`: the channel's close, where it lies mid-round;
- `round_cleanup`: a cleanup close with no earlier marker, for the eight
  classes of deployed utility with no expiration (Trademark, Rendezvous,
  Trapwire's two wires, Spycam, Cage, Alarmbot, Turret, Nanoswarm): they stay
  in the world after their owner dies, disabled and drawn dimmer
  [domain:abilities/deployed-utility-disabled-drawn-dimmer];
- `unknown`: no marker holds; `t_end_rep` is null, `end_reason` says why and
  `t_live_until_rep` holds the actor's last own row before its cleanup.

Every other class ends at a mid-round channel close, else `unknown`.

`t_disabled_rep`/`_cap` with `disabled_marker = disabled_at_owner_death`
records a state change, never an end: the actor's own `*Disabled*`
continuous effect within 100 ms of its owner's death, on every class that
shows it. 0.3.0 read it as an end; the player's answer of 2026-10-09
corrected that, for the drawn objects
[domain:abilities/chamber-rendezvous-drawing-lasts-with-object]
[domain:abilities/chamber-trademark-drawing-lasts-with-object]
[domain:abilities/cypher-trapwire-drawing-lasts-with-object]
[domain:abilities/cypher-spycam-camera-drawing-lasts-with-object] and the
Cage [domain:abilities/cypher-cyber-cage-persists-after-death] alike.

`ticks` (the primary state table): `e`, `t_rep`, `t_cap`, `x`, `y`, `z`,
`yaw`, `pitch`, `alive`, `px`, `py`, `facing_px`, `sample` (`movement` at the
server tick, `rep_movement` from `ReplicatedMovement`, `spawn` at a child's
open), `source`. A static child has one `spawn` row; its position holds
until it closes.

`frames` (captured matches): every player at each stored `ally_icon` frame,
at the replay time the frame shows (`frames_to_replay` with the minimap lag):
`frame_idx`, `t_cap`, `t_rep`, `e`, `x`, `y`, `z`, `yaw`, `alive`, `px`,
`py`, `facing_px`, `round`, `source`.

`events` (transitions, each with `provenance`): `kind` in `round_start`,
`buy_end`, `round_end`, `kill`, `plant`, `defuse`, `switch_teams`,
`ult_used`, `ult_on`, `ult_off`, `cast` (slot byte in `value_num`, ability
folder in `value_str` where `slot_map` maps it), `revive`, `damage`
(damager `e`, damaged `e2`, causer `guid`, damaged actor `guid2`, origin
`x`/`y`/`z`, damage taken in `value_num`, equippable in `value_str`, and in
`detail` the damage type, kill flag, impact, and each life change with its
component, delta and result: health and armor), `effect` (one-shot effect
RPCs: container path in `value_str`, alliance filter in `value_num`, owner
in `e`); plus `t_rep`, `t_cap`, `round`, `e2`, `guid2`, `detail` (JSON) and
`source`.

`state` (sparse changes per player): `field` in `money`, `ult_points`,
`equipped` (the equippable's class), `region` (the callout region's path),
`crouch`, `charges:<ability item class>`, `armor` (the armor item worn);
`value_num`, `value_str`, `t_rep`, `t_cap`, `round`, `provenance`, `source`.

`rounds`: `round`, `t_start` (`roundStarted`, the buy phase's start
[domain:replay/vrf-round-started-opens-buy-phase]), `t_buy_end` and `t_end`
(`MulticastSetPhase` 4 and 5; 5 as round end is this module's reading, and
the head's `round_end_check` measures it against each round's last death or
defuse), `t_next_start`, `t_plant`, `t_defuse`, and `tcap_*`.

`lives`: `e`, `subject`, `round`, `t_open`, `t_open_lo`, `open_basis`
(`round_start`, `second_death`, `own_activity`), `t_close`, `close_basis`
(`death`, or `next_round_start`: play continues through the post-round
period [domain:rounds/post-round-period]), `killer`, `evidence`, `tcap_*`. A
revive is read only where the replay shows the player alive again: a second
death in the round, or damage he deals with a held gun or knife more than
`REVIVE_QUIET_MS` after his death. His body's movement is not evidence: the
death throws it about 3 m within half a second.

## Read API

```python
from reticle.replay_layer import load
L = load("c817691bcd15")            # a session, a match id or a prefix
L.head, L.entities, L.ticks, L.frames, L.events, L.state, L.rounds, L.lives
L.players()                          # entity rows of the ten players
L.rows("ticks")                      # row count (len(L.ticks) counts columns)
L.entity(e); L.track(e)              # one entity's row; its ticks in time order
L.state_at(t, clock="capture")       # every entity alive or open at t
L.alive_at(e, t, clock="capture")
L.round_at(t, clock="capture")
L.intervals("lives" | "rounds" | "buy" | "children")
L.events_of("kill")
```

`clock="replay"` takes `t_rep`. Each table is a dict of numpy columns, so
`len(L.ticks)` counts columns; `L.rows("ticks")` counts rows. `state_at`
interpolates position, z, pitch, px and py linearly between ticks no more
than `MAX_GAP_MS` apart (`position_basis` `interpolated`) and takes yaw and
`facing_px` from the nearer tick. Across a longer gap (a round's
post-round period, a static child) it holds the last tick at or before `t`
(`held`, with `held_from_tick_ms`); before the first tick the position is
null (`before_first_tick`). A player's `alive` comes from `lives`, so a dead
player carries his last position with `alive` False. Players also carry
their latest `state` values as `state:<field>`.

## Decoded, and not

Decoded: positions and view (yaw, pitch) per tick; deaths, plants, defuses,
round phases, casts, ult state; every ability actor's owner, open, close and
spawn; damage calls with their life changes; one-shot effects' containers;
credits, ult points, held equippable, callout region, crouch, ability
charges, worn armor. Health and armor are not replicated as fields; they
come only from damage calls' life changes. Among the effects, footsteps
(`FXC_Footstep_C`), jumps and landings, grenade and bounce audio, spike
beeps, death pings and many ability containers are named. Gunfire is not
a one-shot effect; it is likely `MulticastPlayContinuousEffectFromClient`
on gun actors, which the layer does not decode. Not decoded: `movement_state` (zero throughout on
60c7f1e0), `AssignedTeamState` (null), the effect containers' meaning beyond
their asset path, and each actor's `undecoded` payloads. The replay holds no
audio; its damage, equip and effect calls are the causes of most sounds, and
label the capture's audio offline under the held-out policy.

## Follow-up: the scorers read the layer

`prototypes/replay_truth.py score` and `prototypes/replay_abilities.py score`
still join the replay themselves through `replay_source`. Moving them onto
the layer replaces, in `replay_truth`: `truth_px` and `_frames_to_replay`
(with `frames` rows), `Replay.alive` (with `lives`, which adds revives),
`session_context` (with the head); in `replay_abilities`: `class_census`,
`slot_map`, the `owner_subject` loops in `score`, `_bolt_truth` and the
per-class `instances` calls (with `entities` and `ticks`), `Export.casts`
and `ult_intervals` (with `events`). The checks that remain theirs are the
scoring itself.
