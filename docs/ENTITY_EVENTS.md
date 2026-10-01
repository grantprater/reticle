# Entity events

A plan, proposed 2026-09-30. The player decided that event extraction ends
in emitted events: whatever statistics and cross-checks produce them,
analytics, clips and overlays read those events and nothing else, and each
event carries what a consumer needs -- time, location, orientation and the
entity's own state, such as disabled, armed or activated. He then set the
end state for uncertainty: consumer events should need no uncertainty
field, because cross-channel checks should make every relevant event
certain; the only residue should be events such as an enemy cast barely in
audio range, outside every vision range and masked by other sounds, and
those drop from the final output. Uncertainty stays for now.

The player answered the plan's three questions the same day; section 8
records the answers, and sections 2 to 6 carry them: the viewer draws the
ledger apart, a per-family rule says what a track shows between
observations, and minimap lanes come before audio lanes.

This plan designs the one layer that serves as that interface: a pure,
versioned projection over stored adjudicated streams. It writes two
outputs per session. The **consumer output** holds only events every owner
resolved, with no uncertainty field. The **ledger** holds everything
withheld -- ambiguous, abstained, refused, not observed, stale or
disputed -- with reasons, alternatives and the owner each question goes
back to. Rules live in `AGENTS.md`; this plan cites them.
[ARBITER_ARCHITECTURE.md](ARBITER_ARCHITECTURE.md) (proposed 2026-09-30)
names the owners this projection copies: one arbiter per channel and
`adjudication.identity` as the aggregator; the projection stays a copy.

Values quoted from rows below are identifiers and row fields, not
measurements; only stage 1's record in section 6 cites a measured run.

## 1. Inventory

### How it was sampled

Two to four rows of each row kind per stream, from the first 4,000 lines
and the last three of each file, on `bfad2778a372` (Split, `valorant-16x9`)
and `a06f04a0059f` (Ascent, `valorant-16x9-bigmap`). Streams absent from
`bfad2778a372` -- `smoke`, `smoke_owner`, `smoke_owner_identity`,
`tray_kit`, `tray_kit_identity`, `minimap_dark`, `ability_light` -- come
from `a06f04a0059f` alone; `ability` exists on six other sessions and was
sampled on `6ab7a9e99235`. No file was read whole beyond the few small
enough to count row kinds with one `grep`. The round table
(`l2/rounds/.../rounds.parquet`, owner `rounds`) is an input too and is
listed last.

### The table

Pos: position. Orient: orientation. Unc: how the stream says it is unsure.
Ev: links to source observations. "px" means the baked widget frame of the
session's `(map, profile)`: `widget_frame` resamples every session into it.

| Stream | Owner (entry) | Entity key | Time base | Pos | Orient | State | Identity | Unc | Ev |
|---|---|---|---|---|---|---|---|---|---|
| `ability` | `prototypes/ability_cast.py`; no entry, `built_by` a commit, no version key | none: `t_ms` + `slot` | media ms | `x,y` in frame `map`, often null with `position_from` | `bearing`, `bearing_state` | none | `agent` from the tray, not the arbiter | `confidence`, `position_ambiguous` | candidate list, no ids |
| `ability_light` | `lighting` via `cli` (`drawn-light`) | none: frame `t_ms` | media ms | lit and dark masks, px | none | lit/dark | none | `reason` | `geometry_key`, `lighting_version` |
| `ability_shape` | `ability_shapes` (`ability-shape`) | `cast_t_ms` + `slot` | media ms | `cx,cy,r` px | none | `shape`, `found` | session's player agent | `found`, `score`, `reason` | seed, tray and cast versions |
| `ability_state` | `adjudication.ability_state` (`ability-state`) | `slot` + `agent_entity_id` (`<sid>:ally:slot:0`) | claims: `observed_at_ms` + `interval_ms`; states: `t_first_ms`..`t_last_ms` | none | none | typed: level, charges, mode, equipped, castable, pips, owner alive, transitions | arbiter verdict in the coverage row | `*_reason`, `no-fact:` reasons, `surprise` | `claim_id`, `agreed`/`disagreed`, `depends_on`, `source_version` |
| `ally_icon` | `minimap` (`ally-candidates`) | `observation_key` per frame; no track | media ms, 15 Hz, `frame_idx` | `cx,cy,r` px | `facing` (reader's own) | `family` ally or barrier | descriptors only | `reason` (`interior_is_map`, `interior_too_thin`) | `observation_key`, `candidate_key` |
| `combat_report` | `combat_report` (`combat-report-read`) | frame | media ms, 1 Hz | screen px | none | header score | none | `reason` | templates |
| `combat_report_round` | `adjudication.combat_report` (`combat-report-round`) | `round_no`, panel `start_ms` | media ms | none | none | kills, deaths, assists | row portraits | `*_agree`, `reason` | `rows`, `verdict_source` |
| `combat_report_rows` | `adjudication.combat_report` | `combat_report:<sid>:portrait:<n>` | `panel_start_ms` | none | none | none | binding to `death_entity` | none | death key |
| `combat_report_identity` | arbiter for `adjudication.combat_report` | `identity:combat_report:...` | `t_ms` 0.0: not an observation time | none | none | none | distribution + status | `metadata.status`, `reason` | `evidence_refs` empty; `depends_on` deaths |
| `death` | `adjudication.death` (`death-victim`) | `death:<sid>:<t>:<n>`, killer `...:killer` | `t_ms` first killfeed sample, `t_last_ms` | `location`, `killer_location`: null in every sampled row | none | cause, weapon, side, second life, revive | victim and killer arbiter verdicts in `metadata` | `status` resolved/abstained/contested/disagreement, `reason` | `witnesses` with observation keys and versions |
| `death_identity` | `adjudication.death` through the arbiter; `events-0.1.0` | `death:...` (`entity_deleted`), `identity:death:...` | killfeed `t_ms` | none | none | `deletion_reason` | distribution | `metadata.status` | `evidence_refs` empty |
| `killfeed_name` | `killfeed` (`killfeed-name-descriptor`) | `<sid>:<frame>:<slot>:<role>` | media ms, 2 Hz | screen band | none | `me`, `gray` | none | `reason` | `observation_key` |
| `killfeed_portrait` | `killfeed` (`killfeed-portrait`) | same | media ms, 2 Hz | screen band | none | second-life badge rows | descriptors only | `reason` | `observation_key` |
| `killfeed_weapon` | `killfeed` (`killfeed-weapon-descriptor`) | `frame_idx` + `slot`; no key | media ms, 2 Hz | screen band | none | `verdict` | none | `reason` | none |
| `menu_open` | `menu` (`menu-open`) | none | media ms, 2 Hz | none | none | `open`, `feature` | none | `unread` count | none |
| `minimap_dark` | `minimap_dark` (`minimap-dark`) | frame | media ms, 4 Hz | masks, px | none | dark, occluded | none | `reason`, `unobserved` | `geometry_key` |
| `ping` | `ping` (`ping-event`) | none | `t_ms` first sighting; `lifetime_s` | `x,y` frame `widget` | `drivers.bearing` absent | `kind`: standard, danger, on my way, need help | no pinger | none; no coverage row | none |
| `round_entity` | `round_entities` (`round-entity-session`); stored 0.8.0, code 0.9.0 | `<sid>:R<n>:E<k>/P<m>`, `segment_id`, `teammate_key` `<sid>:teammate:<Agent>` | media ms, 15 Hz; `first_seen`, `last_seen`, `end_ms`, `right_censored_at_ms`, `origin_ms` | `x,y` px per observation | none | observation `state`, `end_reason`, `class_history` | `agent` via `assign_ally_pieces`, stamped `agent-identity-0.8.0`; self named `you` | `identity_status`, `alternatives`, `origin_reason`, `acquisition` | `observation_key` to `ally_icon`, `death_id`, association components |
| `scoreboard` | `scoreboard` (`scoreboard-row`) | `<sid>:<frame>:<row>` | media ms, 2 Hz, while open | screen px | none | kills, deaths, assists, credits | portrait scores, not names | `*_reason`, confidence, margin | `observation_key` |
| `scoreboard_presence` | `adjudication.scoreboard` (`scoreboard-presence`) | sample | media ms, 2 Hz | none | none | `present`, `witness` | none | `*_reason` | versions of both readers |
| `scoreboard_strip` | `scoreboard_strip` (`scoreboard-strip`) | sample | media ms, 2 Hz | none | none | `verdict` | none | `reason` | none |
| `self_icon` | `self_icon` (`self-icon-portrait`); keyed `session`, not `session_id` | grid `t_ms` | media ms, 1 Hz | `cx,cy,r` px | none | none | art scores, not names | `reason` | `cache_span` |
| `smoke` | `adjudication.smokes` (`minimap-smoke`) | `track` number | `first_ms`, `last_ms`, `end_bound_ms` | `cx,cy,r` px | none | `life_s` | none | `onset_status`, `end_status`, unobserved samples | `geometry_key`, dark version |
| `smoke_owner` | `adjudication.smoke_owner` (`smoke-owner`) | `<sid>:smoke:<first_ms>:<track>` | as `smoke` | `cx,cy` px | none | none | `agent`, `identity_status`, `rules`, `candidates` | `reason`, `by_channel` | `evidence`, `depends_on` slot keys |
| `smoke_owner_identity` | arbiter | `identity:<sid>:smoke:...` | smoke `first_ms` | none | none | none | distribution | status | `evidence_refs` empty |
| `spike` | `spike` (`spike-observation`) | grid frame | media ms, 1 Hz | glyph fits, px | none | glyph dropped/carried; roster marker slot | none | `reason` | `roster_t_ms` |
| `spike_carrier` | `adjudication.spike_carrier` (`spike-carrier`) | none; `slot` is the roster's packed position | `t_ms`, `last_marked_ms`; round `plant_t_ms` copied from `rounds` | none | none | round `spike_planted`, `carrier_lost`, disagreement rows; no carrier spans | `depends_on: agent-from-slot`, no name | disagreement rows | none |
| `team_vision` | `team_vision` (`team-vision`) | frame; icons by team vision's own `track_id` | media ms, 15 Hz | icon `x,y` px; observable masks | icon `facing` | widget drawn, `interpolated`, `eligible`, `casts` | none | `reason` | versions of every composed owner |
| `tray_drop` | `tray` (`tray-drop`) | `t_ms` + `slot` | media ms, 2 Hz grid | none | none | `from`, `to`, `player_cast` | none | `reason`, `suspect` | none |
| `tray_kit` | `adjudication.tray_kit` (`tray-kit`) | `<sid>:tray:kit:<t>` span | `t_first_ms`..`t_last_ms` | none | none | kit change, kit return, `own` | `agent`, `identity_status` | `identity_reason` | `depends_on` slot keys |
| `tray_kit_identity` | arbiter | `identity:<sid>:tray:kit:<t>` | span start | none | none | none | distribution | status | `evidence_refs` empty |
| `ult_cast` | `adjudication.ult_cast` (`ult-cast`) | `<sid>:ult_cast:<t>:<template>` | `t_ms` of the audio peak, plus `t_s` | none | none | `class` own/possible/impossible, `side`, `player_cast` | `agent`, `identity_status` | refusal and missed-line rows with reasons | template, score, floor |
| `ult_cast_identity` | arbiter | `identity:<sid>:ult_cast:...` | cast `t_ms` | none | none | none | distribution | status | `evidence_refs` empty |
| `ult_line` | `ult_lines` (`ult-line`) | none | `t_s` in seconds, audio hop | none | none | none | template agent and variant, candidates | `score` over `floor` | `content_key` |
| `rounds.parquet` | `rounds` (`round-bounds`) | `round_no` | `t_start_ms`, `t_end_ms`, `t_close_ms` | none | none | won, score, player side, `spike_planted`, `plant_t_ms` | none | `side_agrees`, `side_separation` | `start_source`, `end_source` |

### What the inventory shows

- **No stream holds the ten players.** Owners name players four ways: the
  arbiter's slot key `<sid>:ally:slot:<n>` (`ability_state`,
  `smoke_owner`, `tray_kit`), a key built from a name
  `<sid>:teammate:Jett` (`round_entity`), a death key
  `death:<sid>:<t>:<n>`, and the roster's packed position
  (`spike_carrier`), which ownership already warns is no player. The
  arbiter's side verdict is recomputed in memory by each owner and stored
  by none. The stored top-bar read (`lineups/bfad2778a372.json`,
  `lineup-0.3.0`) names ally slot 2 Sova, while every ally victim the death
  owner names in that session is Skye, Jett, Chamber, Fade or Miks.
- **A spectated icon is named as the player.** In `bfad2778a372` round 1,
  `death:bfad2778a372:177000:0` names Skye, the player, as the victim.
  `round_entity`'s self entity `bfad2778a372:R1:E0004`, named `you` and
  agent Skye, keeps observations until 204,467 ms and ends bound to
  `death:bfad2778a372:205000:0`, whose victim the death owner names
  Chamber. After 177,000 ms the self icon was a spectated teammate
  [domain:hud/tray-after-player-death].
- **Enemy icons are stored in `minimap_object`** (`reticle/minimap_objects.py`),
  read from the crop cache with the teardrop box and the baked-slab gate, both
  on by default after a held-out check
  ([metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK4_n=14]
  icons boxed whole, the gate dropping
  [metric:enemy_lane_score/fix-check@587c15b07779+a1a995e6b19b+96aa1ae9b96f+b3b9defb6fd7+75a55a296d3b#CK1_n=0]
  player-named marks). Enemies are drawn only inside team vision
  [domain:minimap/vision-gate]; `enemy_tracks` joins them per round and the
  `enemy` lane projects them.
- **Positions sit in the baked `(map, profile)` frame.** Every minimap
  coordinate is widget px of one profile; the ping row says `widget`, the
  ability row says `map`, and no owner publishes a transform into one
  frame per map [domain:capture/minimap-size-settings].
- **Orientation is stored where the entity key is not.** `round_entity`
  carries no facing. `team_vision` stores facings under its own track ids,
  and `ally_icon` stores the reader's facing rather than the icon-pose
  owner's (`teardrop`).
- **Deaths have no place.** `location` and `killer_location` exist on every
  death verdict and are null in every sampled row.
- **The spike has no carrier spans.** `spike_carrier` stores losses,
  disagreements and a copy of the round table's plant time, with the
  planter slot null in the sampled rounds.
- **Pings have no key, no round, no coverage row and no pinger**, so a
  missing ping cannot be told from an unread one.
- **Identity events lose time and evidence.** Every sampled `events-0.1.0`
  row has empty `evidence_refs`; `combat_report_identity` stamps `t_ms`
  0.0; identity streams carry their stamp in `producer_version`, not the
  store's `<kind>_version` key.
- **Uncertainty speaks many dialects**: `identity_status` provisional,
  resolved or abstained; death `status` contested or disagreement; reader
  `reason` strings; `onset_status`; refusal rows; and not-observed as
  `widget_not_drawn`, `tray_not_drawn`, `menu_open`,
  `kit_frozen:after_player_death` or a stall
  [domain:capture/stalled-capture].
- **Inputs are stale.** `round_entity` holds `round-entity-0.8.0` over
  `agent-identity-0.8.0`; the code is at 0.9.0 for both.

## 2. The schema

The schema lives in one foundation module, `entity_contract`, stamped
`entity-contract-0.1.0`, beside `events` (`events-0.1.0`). `events-0.1.0`
stays the wire format producers already write for identity and lifecycle
rows; it is an input to the projection, not the consumer contract.

### Two outputs

| | Consumer output | Ledger |
|---|---|---|
| Stream | `entity_<lane>` | `entity_<lane>_ledger` |
| Holds | entities, events and coverage every owner resolved | every projected row withheld, with standing, reason, alternatives and `returns_to` |
| Uncertainty field | none | `standing` per row and per field |
| Readers | every consumer | review tools, audits, the resolution metric |

A consumer row is certain or absent. A field no channel read stays `null`
with a reason; that is coverage, not doubt.

### Entities

```json
{"row": "entity", "entity_id": "bfad2778a372:R1:E0001/P0",
 "family": "icon_track", "kind": "ally", "side": "ally", "round": 1,
 "lifetime": {"first_observed_ms": 153000.0, "last_observed_ms": 167266.7,
              "began": null, "began_reason": "not_read: origin not independently observed",
              "ended": null, "ended_reason": "not_read: right_censored",
              "censored_at_ms": 167266.7},
 "identity": {"agent": "Jett", "ref": "<arbiter verdict id>",
              "arbiter": "agent-identity-0.9.0"},
 "player": null, "player_reason": "not_read: unbound: round_entities publishes a name-built key",
 "producer": {"owner": "round-entity-session", "version": "round-entity-0.9.0"},
 "lane": "round_entity", "contract": "entity-contract-0.1.0"}
```

- **`entity_id` is the owner's key, verbatim.** The projection invents no
  key, as the arbiter invents none.
- **`family`**: `player` (match-scoped, one per side and lineup slot),
  `icon_track` (a round's minimap track piece), `ability_object` (a smoke,
  a device, a drawn area), `spike` (one per round), `ping`, `mark` (death
  and last-known marks), `furniture` (buy-phase barriers
  [domain:rounds/buy-phase-barriers]). `kind` refines it: `ally`, `enemy`,
  `self`, `spectated`; an ability's catalogue id; a ping's kind.
- **`side`** is `ally` or `enemy`; halftime swaps attack and defence, not
  these [domain:rounds/halftime-side-swap].
- **`round`** is the round table's number, looked up from `rounds`; a
  `player` has none.
- **`lifetime`** keeps observed bounds (`first_observed_ms`,
  `last_observed_ms`) apart from inferred ones (`began`, `ended`), each
  inferred bound with its owner's basis.
- **`identity`** copies a name only from a resolved arbiter verdict and
  carries the verdict's id and version. A row with an `agent` and no `ref`
  fails validation. `player` binds a track, death, cast or smoke to a
  player entity only where the binding owner stored the slot key.

### Entity events

```json
{"row": "event", "event_id": "<lane>:<owner row id>", "entity_id": "...",
 "kind": "death", "round": 1,
 "observed_ms": 177000.0, "observed_last_ms": 181500.0,
 "occurred": null, "occurred_reason": "not_read: no_owner_bound",
 "position": {"frame": "baked:split__valorant-16x9", "x": 0.0, "y": 0.0},
 "orientation": {"deg": 0.0, "convention": "<icon-pose owner's>"},
 "state": {"...": "per-kind vocabulary"},
 "participants": {"killer": {"entity_id": "...", "identity": {"...": "..."}}},
 "evidence": [{"stream": "death", "id": "death:bfad2778a372:177000:0",
               "version": "death-adjudication-0.20.0"}],
 "producer": {"owner": "death-victim", "version": "death-adjudication-0.20.0"},
 "lane": "death", "contract": "entity-contract-0.1.0"}
```

- **Times.** `observed_ms` is media time of the first observation that
  shows the event; `observed_last_ms` the last. `occurred` is an inferred
  interval `{lo_ms, hi_ms, basis, evidence}` and comes only from an owner;
  the projection never widens a sample into an interval itself. The round
  clock is `gametime`'s mapping, carried as `round_ms` when that owner
  stores it.
- **Position** is in a declared `frame`. The target is `map:<map>`, one
  frame per map across profiles, from a transform `geometry` publishes;
  until it does, positions carry `baked:<map>__<profile>`. The projection
  converts nothing.
- **Orientation** is degrees in the same frame, in the one convention the
  contract names; the icon-pose owner states which convention it stores,
  and a mismatch fails validation.
- **State** is typed per kind from a declared vocabulary; a value outside
  it fails validation.
- **Evidence** names source rows by stream, id and the stream's version.
  Owner rows that cite observation keys (`witnesses`, `observation_key`,
  `claims`) pass those keys through.
- **Producer** names the ownership id and version that decided the event;
  `lane` and `contract` name the projection.

### Per-kind state vocabularies

| Kind | Vocabulary | Source |
|---|---|---|
| `pose` (icon track sample) | none beyond position and orientation | `round_entity`, a pose owner |
| `estimate` (unobserved icon track) | `basis`: the observations and rule the owner used | the estimate owner of the family; the per-family rule below |
| `last_known` (enemy mark) | none beyond position | the owner that reads the red "?" [domain:minimap/last-known-mark] |
| `death` | `cause` gun/ability/environmental/melee/other (the death owner's), `weapon`, `second_life`, `revive` | `adjudication.death`; [domain:rounds/resurrection-mechanics] |
| `spike` | `phase`: `dropped`, `carried`, `planted`, `detonated`, `last_known`, each citing its fact in `entity_contract.SPIKE_STATES`; `defused` joins when a fact shows it | [domain:minimap/spike-inversion], [domain:minimap/spike-carrier-overlay], [domain:minimap/spike-planted-icon], [domain:killfeed/environmental-self-entry], [domain:minimap/enemy-spike-ground-vision]; `rounds` owns the plant; defuse and detonation have no owner |
| `ping` | `ping`: `standard`, `danger`, `on_my_way`, `need_help`, `watching_here` (the ping owner's), and `lifetime_s` | `ping` |
| `slot_state` (the player's own tray slot) | level, charges, equipped, castable, pips | `adjudication.ability_state` |
| `cast` | the ability's catalogue id and slot | `ult_cast`, `ability_timeline` |
| ability object lifecycle | per ability, from its lifecycle fact | `domain/abilities.toml` |

**An ability's states come from its own fact, never by analogy**
[domain:abilities/ability-rules-are-unique]. The contract reads each
ability's vocabulary from a `states` list on its lifecycle facts in
`domain/abilities.toml` -- placed then activated for the devices that take
a second press [domain:abilities/placed-then-activated], two drawn phases
for a Dark Cover [domain:abilities/omen-dark-cover-minimap-phases],
reclaimed or expired for a Wingman
[domain:abilities/gekko-wingman-reclaim-or-expire], live then dim for a
deactivated device [domain:minimap/device-dim-on-deactivation]. An ability
whose facts name no lifecycle gets only `observed` and a
`no-fact:<agent>:<slot>:lifecycle` reason, the form `ability_state`
already uses; its questions go to the mechanics sheet.

### Unread values

Every field the contract lists is present. An unread value is `null`, and
a sibling `<field>_reason` says why, in one of four forms:

| Reason | Meaning | Example |
|---|---|---|
| `not_applicable` | the kind has no such field | orientation of a death |
| `not_read: <owner reason>` | the owner stored no value, with its reason | `location` on every sampled death |
| `not_observed: <cause>` | no channel could see it | widget absent, menu open, stall, kit frozen after death |
| `withheld: <ledger id>` | an owner answered but not certainly; the ledger holds the alternatives | an optional field the ledger disputes |

Coverage rows say what each lane read: per round, the intervals its owners
observed and the unobserved ones with the cause. "No smoke in round 3" and
"round 3 unread" then differ in the consumer output itself.

### Between observations: a rule per family

What a track shows while nothing observes it depends on whether its object
is expected to go unobserved. The contract declares one rule per family and
kind; a consumer never chooses.

| Family, kind | While unobserved | Ends |
|---|---|---|
| `icon_track`, `ally` (alive) | `estimate` events: the owner's position estimate, the same as for crowded or overlapping icons | at a death event |
| `icon_track`, `self` (alive) | `estimate` events from `position-belief`, the player's own belief owner | at the player's death; a spectated icon is its own entity (gap 2) |
| `icon_track`, `enemy` | `estimate` events until the icon becomes the red "?" [domain:minimap/last-known-mark] | the track becomes a `last_known` event at the mark's place and time; no estimate follows it |
| `mark`, `last_known` | nothing: the mark is the event | when the mark leaves the widget |
| every other family | `not_observed` coverage, no estimate | -- |

An `estimate` is a distinct event kind, not an observation with doubt
attached: it carries the owner's position, its `basis` (the observations
and rule it rests on) and the owner's version, and it reaches the consumer
output under the drop rule like any other row. The projection interpolates
nothing. Where no owner stores an estimate for a family whose rule calls
for one, the gap shows as `not_observed` coverage with reason
`no_estimate_owner` and counts as debt. Today `position-belief` covers the
player alone; allies and enemies need an owner (gap 3a). The rule for the
last row grows one family at a time, from the player's answer or a fact,
never by analogy.

### The ledger row

```json
{"row": "withheld", "ledger_id": "...", "lane": "round_entity",
 "subject": {"row": "entity", "entity_id": "bfad2778a372:R1:E0004"},
 "standing": "disputed",
 "reason": "binding: round_entity binds death:bfad2778a372:205000:0 to an entity named Skye; the death owner names its victim Chamber",
 "fields": {"identity": {"standing": "disputed",
   "alternatives": [
     {"value": "Skye", "owner": "round-entity-session", "evidence": ["round_entity:bfad2778a372:R1:E0004"]},
     {"value": "Chamber", "owner": "death-victim", "evidence": ["death:bfad2778a372:205000:0"]}]}},
 "returns_to": ["round-entity-session"],
 "residual": false}
```

`standing` is one of `resolved`, `ambiguous`, `abstained`, `refused`,
`not_observed`, `disputed` or `stale`. The owner's own reason string stays
verbatim; the standing is a declared translation per input stream (the
arbiter's `disagreement` and `contested` are `ambiguous`; `round_entity`'s
`provisional` is `abstained`; a reader refusal is `refused`), so nothing
the owner said is lost. `returns_to` names the owner `reticle ownership`
routes the question to.

### Raw observations stay apart

The projection reads adjudicated streams and passes reader observation keys
through as evidence; it copies no pixel descriptor, and consumer rows never
become inputs to a reader or an adjudicator. Nothing stores a projected
event back as an observation. A late answer from any owner rebuilds the
lane from storage; it never becomes an event's inferred origin.

### Examples from stored rows

**A death** (`bfad2778a372`, round 1), consumer output:

```json
{"row": "event", "event_id": "death:death:bfad2778a372:177000:0",
 "entity_id": "death:bfad2778a372:177000:0", "kind": "death", "round": 1,
 "observed_ms": 177000.0, "observed_last_ms": 181500.0,
 "occurred": null, "occurred_reason": "not_read: no_owner_bound",
 "position": null, "position_reason": "not_read: location null",
 "orientation": null, "orientation_reason": "not_applicable",
 "state": {"cause": "gun", "weapon": "Ghost", "second_life": false, "revive": false},
 "identity": {"agent": "Skye", "ref": "identity:death:bfad2778a372:177000:0",
              "arbiter": "agent-identity-0.9.0"},
 "player": null, "player_reason": "not_read: unbound: the death owner publishes no slot key",
 "participants": {"killer": {"entity_id": "death:bfad2778a372:177000:0:killer",
   "identity": {"agent": "Phoenix", "ref": "<killer verdict id>", "arbiter": "agent-identity-0.9.0"}}},
 "evidence": [{"stream": "death", "id": "death:bfad2778a372:177000:0", "version": "death-adjudication-0.20.0"},
              {"stream": "killfeed_portrait", "id": "bfad2778a372:10620:0:victim", "version": "killfeed-portrait-0.9.0"}],
 "producer": {"owner": "death-victim", "version": "death-adjudication-0.20.0"},
 "lane": "death", "contract": "entity-contract-0.1.0"}
```

**A smoke with its owner** (`a06f04a0059f`): an `ability_object` entity
`a06f04a0059f:smoke:97450:0`, kind `smoke`, with `identity` Miks from
`identity:a06f04a0059f:smoke:97450:0`; two events, `drawn` observed at
97,450 ms and `gone` observed last at 115,450 ms with
`occurred: {"lo_ms": 115450, "hi_ms": 116450, "basis": "smoke end_bound_ms"}`,
position `baked:ascent__valorant-16x9-bigmap` at (155.8, 201.8). The
vocabulary is the disc's two steps [domain:abilities/miks-smoke-minimap-disc];
the owner question is `smoke-owner`'s [domain:abilities/smoke-attribution].

**An ally icon track** (`bfad2778a372`, round 1): the entity above,
`bfad2778a372:R1:E0001/P0`, named Jett; one `pose` event per observation,
the first `bfad2778a372:R1:O000001` at 153,000 ms, (38, 153), evidence
`ally_icon:bfad2778a372:9180:0`. Its orientation is `null`,
`orientation_reason: "not_read: no pose owner keys a facing by this observation"`:
`team_vision` holds a facing for an icon at the same place and frame under
its own track id, and joining the two is a binding the projection may not
make.

**A spike plant** (`bfad2778a372`, round 2): event kind `spike`, state
`planted`, `observed_ms` 313,500 from `rounds` (`round-0.7.0`), the owner of
the plant; `spike_carrier`'s copy is evidence, not a second witness.
`position` null with `not_read: rounds stores no plant site`; `planter`
null with `not_read: planter_slot null`. Its `entity_id` waits for an owner
to publish a per-round spike key.

**A ping** (`bfad2778a372`): kind `ping`, state `standard`, `observed_ms`
114,916, position `baked:split__valorant-16x9` at (158, 69), `lifetime_s`
7.9 as the owner measured it, `pinger` null with
`not_read: ping stores no pinger`. It waits for an owner key; until then the
lane withholds it with `standing: "refused"`, reason `no_owner_key`.

**An ult cast** (`bfad2778a372`, round 4): kind `cast`, entity
`bfad2778a372:ult_cast:523740:Deadlock_ult_enemy`, side `enemy`, identity
Deadlock from its arbiter verdict, slot X by the catalogue
[domain:abilities/deadlock-slots], `observed_ms` 523,740 at the audio peak,
position null with `not_applicable: an audio line carries no place`
[domain:abilities/ult-lines-heard-by-both-teams]. The refusal
`a06f04a0059f:ult_cast:1093540:Chamber_ult_enemy`
(`agent_not_on_complete_enemy_side`) goes to the ledger as `refused`, with
`returns_to: ["ult-cast"]`.

## 3. The projection

### Pure

`project(store, session, lane)` reads stored streams and the round table,
and writes one consumer file and one ledger file. It decodes nothing,
imports no reader and calls no owner that reads pixels. It decides nothing:
it copies owner answers into the schema, translates each owner's standing
through a declared table, and applies the drop rule below, which reads only
standings owners stored. Two runs over the same inputs write identical
bytes.

### Lanes

A lane is one slice of the output with a declared list of input streams.
Each lane writes its own pair of files, so a change to one input rebuilds
only the lanes that read it.

Lanes are ordered by the channel that observes their events. The player
expects events the minimap observes to reach the consumer output within a
few iterations, while audio detection barely works yet; so minimap and
screen lanes come first, and audio lanes come last.

| Order | Lane | Channel | Inputs |
|---|---|---|---|
| 1 | `round_entity` | minimap | `round_entity`, `rounds`; later a pose owner and estimate owners |
| 1 | `death` | killfeed, HUD, scoreboard | `death`, `death_identity`, `rounds` |
| 1 | `spike` | minimap, round table | `rounds`, `spike_carrier` |
| 2 | `players` | arbiter over every channel | the arbiter's stored side verdict (gap 1), `rounds` |
| 2 | `smoke` | minimap | `smoke`, `smoke_owner`, `smoke_owner_identity`, `rounds` |
| 2 | `ping` | minimap | `ping`, `rounds` |
| 2 | `enemy` | minimap | `enemy_track`, `enemy_track_identity`, `rounds`, `death`, `death_identity` |
| 3 | `slot_state` | tray | `ability_state`, `tray_kit`, `tray_kit_identity` |
| 4 | `ult_cast` | audio | `ult_cast`, `ult_cast_identity`, `rounds` |
| 4 | audio casts | audio | the sound bank, once an owner wires it |
| -- | `disagreement` | every channel | `reconciliation`'s stored disagreements, `spike_carrier` disagreement rows |

### The drop rule

A projected row reaches the consumer output only when all four hold:

1. its owner accepted it: not a refusal row, not an abstention;
2. every field the contract marks required for its kind is `resolved` by
   that field's owner, and every name comes from a resolved arbiter
   verdict;
3. no stored disagreement names it, and no two owners give different
   resolved values under one shared key -- the one comparison the
   projection makes, an equality with no tolerance;
4. every input it rests on is current, or current by a declared waiver
   (`version.STAMP_WAIVERS`).

Anything else goes to the ledger. An optional field that fails (2) or (3)
leaves the row in the consumer output with the field `null` and
`withheld: <ledger id>`.

**The target the cross-checks must reach.** Every ledger row is either
*residual* or *debt*. A residual row names a reason the contract declares
residual, and each declared reason cites the domain fact that makes the
event unobservable to every other channel. The first residual reason is the
player's own class: an event whose only witness is one audio match below
its owner's floor, with no vision, killfeed or HUD witness at its time. Every
other ledger row is debt. The target, per session and kind: **debt share
zero**. A new residual reason needs the player's approval and a fact.

The residual class is the end state, not today's drop list. While audio
detection barely works, most audio-only events stay in the ledger as debt,
and that is expected. The target therefore applies by channel in the lane
order above: minimap lanes are held to zero debt first, and audio lanes
record their debt without being held to the target until their owners can
reach it.

**Measuring progress.** Each projection run records a `reticle.metrics`
series `entity_events/resolution` per session and lane: per kind, consumer
rows, ledger rows by standing, residual rows, the resolved share
(consumer over consumer plus ledger) and the debt share. Prose cites it with
`metric:` tokens. A resolved share bought by owners resolving wrongly is a
regression, so every kind with player labels also records the
resolved-and-wrong share through `adjudication.reliability`; the resolved
share counts only while that stays flat. The fast tier (a fixed handful of
sessions) runs it on every change; the corpus runs it for acceptance.

### When owners disagree

The projection never chooses. Both answers go to the ledger with their
owners and evidence; the event is withheld, and `returns_to` names the owner
that must answer -- the arbiter for any name, the binding owner for any
binding. A disagreement that needs a tolerance, a margin or a window to see
is `reconciliation`'s question (`channel-disagreement`); the projection
reads its stored rows. The self-track conflict in section 1 is the model
case: `round_entity`'s end binding and the death owner's victim disagree on
one key, the track is withheld, and the question goes back to
`round-entity-session`, which needs a spectate witness (gap 2).

### Version stamp and staleness

Each lane file opens with a stamp row:

```json
{"row": "stamp", "entity_death_version": "entity-death-0.1.0",
 "contract": "entity-contract-0.1.0",
 "inputs": {"death": "death-adjudication-0.20.0",
            "death_identity": "agent-identity-0.9.0",
            "rounds": "round-0.7.0"}}
```

The key follows the store's `<kind>_version` convention, so
`store.events_version` and `plan` read it unchanged. `plan` calls a lane
stale when its code version changed, when the contract changed, when any
input's stored stamp differs from the one the lane recorded, or when an
input is itself stale. A lane that is not stale keeps its stamp and its
bytes; a `smoke_owner` change rebuilds `smoke` alone. An arbiter change
rebuilds every lane that copies a name, because every such lane rests on
it. A contract change rebuilds every lane by design: it reaches every
consumer. The rebuild is `reticle project <session> --lane <lane>`, from
storage.

### Placement

- `architecture.toml`: `entity_contract` joins `foundation` beside
  `events`, so `store.write_events` validates `entity_*` rows the way it
  validates `events-0.1.0` rows today. `entity_events`, the projection and
  the read API, joins `entities` beside `round_entities`. Consumers sit in
  the `consumers` layer, above `entities`. No upward edge is needed.
- `ownership.toml`: `entity_contract` joins `[infrastructure]`, as
  `events` has. `entity_events` owns one entry:

```toml
[[entry]]
id = "entity-event"
question = "What did each entity do, in the one schema every consumer reads?"
owner = "entity_events"
role = ["lifecycle"]
status = "partial"
names_agents = true
produces = ["ENTITY_LANES", "project_lane", "EntityEvents"]
defers_to = ["agent-identity", "round-bounds", "channel-disagreement"]
not_for = """
Deciding anything. It copies what each owner stored into one schema and
invents no key, name, time or position; a threshold, a margin or a vote
belongs to an owner. Two owners that disagree are stored side by side in
the ledger and the question goes back to the owner `reticle ownership`
names. Nor is a projected event an observation: nothing stores it back as
evidence.
"""
consumers = ["overlay", "coaching", "review", "clipserve", "cli"]
evidence = "tests/test_entity_events.py"
```

  Each input's entry adds `entity_events` to its `stored_consumers`.
  `names_agents = true` with `agent-identity` in `defers_to` is what
  OWNERSHIP requires of an output that carries a name.

## 4. Consumer contract

### Read API

```python
from reticle.entity_events import EntityEvents

ee = EntityEvents(store, session)       # raises StaleLanes naming each stale lane
ee.rounds()                             # round numbers, bounds, coverage
ee.entities(round=None, family=None, side=None)
ee.entity(entity_id)
ee.events(round=None, entity_id=None, kinds=None, t0_ms=None, t1_ms=None)
ee.latest(t_ms, families=None)          # last event per entity at or before t, with its age
ee.coverage(round, lane=None)
```

`events` returns rows ordered by `observed_ms`. `latest` interpolates
nothing; it reports how old each row is. `EntityEvents.ledger(...)`, the
same queries over the ledger, exists for review tools only.

### Who reads what

| Consumer | Reads | Today |
|---|---|---|
| round viewer | consumer output, and ledger rows drawn apart in amber as an overview; declared in `review` | being built |
| `overlay` | consumer output | reruns readers; its reader drawing moves to a reader debug view, declared no consumer |
| clips (`clipserve`) | consumer output; an event's time locates a clip, a higher-fidelity pass bounds it | -- |
| `coach` (`coaching`) | consumer output | reads stored streams |
| `sql` | DuckDB views over `entity_*` consumer files only | views over L1 parquet |

### A doctor check: CONSUMER

`architecture.toml` gains a `[consumers]` table: `modules`, the declared
consumers, and `review`, the subset that may call `ledger`. CONSUMER
reports an ERROR when a declared consumer module imports any module of the
`primitives`, `readers`, `orchestration` or `adjudication` layers, calls
`Store.read_events`, `read_events_kind`, `read_hud`, `read_minimap`,
`read_rounds` or a parquet reader, or opens a path under `events/` other
than through `entity_events`; and when a module outside `review` calls
`ledger`. The `sql` and `coach` command bodies move into modules so the
check can see them. The list grows one consumer per migration stage, so
the check passes at every stage.

Stage 0 declared the round viewer (`view_events`, `round_view`) with the
check, in `review`, because it already sat in the `consumers` layer, with
three dated exemptions. Stage 1 ended two: the round table and the widget's
placement now come through `entity_events` (`round_rows`,
`widget_placement`). One remains, dated in `architecture.toml`:
`view_events` opens the files (`events_path`) of the layers no lane
projects yet, and the `--gaps` census measures the owners' own streams. An
exemption names one use, so a new one fails now, and a stale one is
reported.

## 5. Gaps, by value to the annotated match

Each owner adds fields; the projection adds none of them itself.

1. **The ten players.** `adjudication.identity` stores its side verdict --
   per slot key, the agent, status and version -- as a stream, and exposes
   the slot key for a resolved (side, agent). Every binding owner then
   publishes that key: `round_entities` in place of the name-built
   `teammate_key`; `adjudication.death` for victim and killer;
   `adjudication.spike_carrier` for the carrier, through
   `agent-from-slot`, never the packed position; `adjudication.ult_cast`
   and `adjudication.smoke_owner` for the caster.
2. **Spectate state.** Whose view the capture shows is an unowned question;
   `tray_kit`'s own and other spans are its first witness
   [domain:hud/tray-after-player-death]. `round_entities` reads it and names
   the self icon `spectated` with the watched player's key after the
   player's death: the self icon marks the spectated player
   [domain:minimap/self-icon-shows-spectated].
3. **Enemy icons as entities.** A reader for enemy icons inside team vision
   [domain:minimap/vision-gate], the icon-pose owner's enemy class
   [domain:minimap/enemy-lobe-translucent], an `enemy` family in
   `round_lifetimes`, and arbiter claims against the enemy side's five.
   Every icon mechanism applies to any agent icon; only the priors differ.
   The same lane needs an owner that reads the red "?" and ends the enemy
   track in a `last_known` event [domain:minimap/last-known-mark].

   **3a. Estimate owners.** The per-family rule in section 2 calls for an
   estimate for every alive ally and for an enemy until its mark. An owner
   stores each estimate with its basis -- the crowded and overlapping icon
   work is its first source -- keyed by the track it continues;
   `position-belief` covers the player alone today.
4. **Orientation per observation.** The icon-pose owner (`teardrop`, through
   `team_vision` or its own stream) stores each pose under the
   `ally_icon` observation key that `round_entity` cites.
5. **One map frame.** `geometry` publishes, per `(map, profile)`, the
   transform into one frame per map, measured on baked geometry, never on a
   session [domain:capture/session-pixels-are-not-the-map].
6. **Death place and time.** `adjudication.death` fills `location` and
   `killer_location` (the death-mark witnesses in
   `docs/MINIMAP_OBJECTS_DESIGN.md`) and stores `occurred` bounds from the
   killfeed's sampling.
7. **Spike.** `adjudication.spike_carrier` stores carrier spans with the
   carrier's slot key and a per-round spike key; `rounds` or a new owner
   stores the planter and the site; defuse and detonation stay unowned.
8. **Ability vocabularies and objects.** `domain/abilities.toml` lifecycle
   facts gain `states` lists, filled from the player's answers through the
   mechanics sheet; the `ability` stream gets an owner, a version stamp and
   entity keys; `ability-owner` stays unowned until an ability entity
   exists to attribute.
9. **Pings.** `ping` stores a coverage row, a reason per refusal, an entity
   key and, where a channel shows one, the pinger.
10. **Identity rows.** Arbiter events carry the observation time of the
    evidence they name and fill `evidence_refs`; identity streams write a
    `<kind>_version` key.
11. **Reason vocabularies.** Each owner declares its reason strings in its
    module, so the projection's standing tables are checked against them.
12. **Residual reasons.** Audio owners (`adjudication.ult_cast`, the sound
    bank when wired) emit the residual reason with the channels that had an
    opportunity, so residual and debt are counted, not guessed. This comes
    last with the audio lanes: until audio detection works, audio-only
    events are debt whatever their reason.

## 6. Migration

Each stage is one `BACKLOG.md` item.

**Stage 0: the contract and the check. Done 2026-09-30.** `entity_contract` with the schema,
standings, frames and vocabularies; its validator in `store.write_events`;
CONSUMER with an empty list; the placement and the ownership entry.
Acceptance: `.\.venv\Scripts\python.exe -m pytest tests/test_entity_contract.py`
and `.\.venv\Scripts\python.exe -m reticle doctor` report 0 errors.
Evidence: the validator rejects a consumer row carrying `standing`, a name
without a `ref`, a position without a `frame`, a state outside its
vocabulary and a `null` without a reason; each rejection is a test.

What stage 0 built, and where it differs from the text above:

- `reticle/entity_contract.py` (foundation, `entity-contract-0.1.0`) holds
  the schema, the reason forms, the ledger row, the per-family rule
  (`between_observations`) and `validate_lane`, which `store.write_events`
  runs on every `entity_*` stream. It also rejects an undeclared time key,
  an `estimate` with an observation time, an observation time with no
  evidence and an inferred interval with no basis. It names no orientation
  convention and no residual reason yet, so it rejects any orientation and
  any residual row until an owner and the player supply one.
- `domain` facts gain an optional `states` list, allowed on lifecycle facts
  with a subject; no fact carries one yet, so every ability object is
  `observed` with its `no-fact` reason until gap 8.
- CONSUMER (`architecture.verify_consumers`) does not start empty: the
  viewer is declared with three dated exemptions (section 4).
- `reticle/entity_events.py` (entities) is a stub that owns `entity-event`
  and declares `ENTITY_LANES`. OWNERSHIP checks that an owner defines what it
  `produces` and imports what it `defers_to`, so the entry lists only
  `ENTITY_LANES` and `NAME_ARBITER` and defers only to `agent-identity`;
  stage 1 adds the rest as it builds them. The standing translations per
  input stream come with the lanes in stage 1.

**Stage 1: the first slice. Built and accepted 2026-09-30.** Lanes `round_entity`, `death` and `spike` for
`bfad2778a372` (`C:\Users\grant\Videos\2026-08-24 14-45-35.mp4`), and the
round viewer reading them. `round_entity` is stale first: rerun
`reticle lifetimes` from storage, which decodes nothing.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan bfad2778a372` names
no stale input of the three lanes; `.\.venv\Scripts\python.exe -m reticle project bfad2778a372 --lane round_entity --lane death --lane spike`
writes six files; `.\.venv\Scripts\python.exe -m pytest tests/test_entity_events.py`
passes; `.\.venv\Scripts\python.exe -m reticle doctor` reports 0 errors with
the viewer in `[consumers]` and in its `review` list.
Evidence: known rows checked first -- the consumer death lane holds
`death:bfad2778a372:177000:0` (Skye by Phoenix, Ghost) and
`death:bfad2778a372:205000:0` (Chamber); the round 1 self track sits in the
ledger as disputed, returned to `round-entity-session`, unless the rerun
changes it, in which case the change is recorded. A second run writes
identical bytes; restamping only `spike_carrier` marks only `entity_spike`
stale in `plan`. The resolution metric is recorded for the session.
Predictions go to `notes/predictions.jsonl` first; the player views round 1
in the viewer against the capture and marks each drawn item right or wrong;
the viewer draws consumer events and amber ledger rows together.

What stage 1 built, and where it differs from the text above:

- `reticle project SESSION --lane ...` (`entity_events.project_lane`)
  writes `entity_<lane>` and `entity_<lane>_ledger` per lane and records
  `entity_events/resolution/<lane>`. `EntityEvents` is the read API;
  `lane_status` and `rebuild_reason` tell `plan` which lanes to rebuild.
- Each lane's stamp row records every input as `<stamp>@<sha256 prefix>` of
  the stored file, so a rerun that keeps its stamp still shows.
- The round_entity lane reads `death` and `death_identity` too: its one
  shared key with the death owner is the death a track's end binds, and the
  equality check of rule 3 needs both answers.
- `plan` names a lane **held** when it is current as projected but rests on
  an input that is itself stale; its rows wait in the ledger as `stale`
  until the input and then the lane are rebuilt.
- A ledger row withheld whole carries the projected row as its `subject`,
  so the viewer draws it; `fields` holds only the fields in question.
- `plan` now checks every stamped stream, with its command and whether the
  command reads storage, the crop cache or the capture, and names
  `team_vision` stale when its stored occluder stamp differs from the
  geometry's `occ_built_by`.
- The viewer draws the three layers from the lanes: consumer rows as
  before, ledger rows as amber squares and `ledger <standing>` panel lines.
  The spike layer no longer draws the spike reader's glyph frames; the
  lane holds the round table's plants and the carrier owner's losses.

The first run on `bfad2778a372`: the death lane holds 162 consumer events
[metric:entity_events/resolution/death@bfad2778a372#consumer_events=162]
with resolved share
[metric:entity_events/resolution/death@bfad2778a372#resolved_share=0.8482];
the spike lane
[metric:entity_events/resolution/spike@bfad2778a372#resolved_share=0.4444];
the first run held every round_entity row in the ledger, most of them
stale, because `round_entity` rested on `ally_icon` rows at
`ally-icon-0.4.0` under code at `ally-icon-0.6.0`. After the `ally_icon`
reread from the crop cache, `reticle vision`, `reticle lifetimes` and
`reticle project`, the lane holds
[metric:entity_events/resolution/round_entity@bfad2778a372~2026-09-30T20:23:51#consumer_rows=48490]
consumer rows with resolved share
[metric:entity_events/resolution/round_entity@bfad2778a372~2026-09-30T20:23:51#resolved_share=0.8966];
most of the ledger is disputed
([metric:entity_events/resolution/round_entity@bfad2778a372~2026-09-30T20:23:51#ledger_disputed=4810]
rows). Round 1's self track `E0004` stays disputed,
returned to `round-entity-session`: the track names Skye, and the death
owner names the victim of `death:bfad2778a372:205000:0` Chamber. Ten other
entities hold the same kind of dispute.

The item that failed at first, `plan bfad2778a372` holding the round_entity
lane on `round_entity` stale through `ally_icon`, passes after that refresh:
`plan` reports nothing stale on bfad. The other items passed on the first run.


**Stage 2: players, bindings and the minimap lanes.** Gap 1, then lanes
`players`, `smoke`, `ping` and, once gaps 3 and 3a have owners, `enemy` and
the track estimates. No audio lane joins here.
Acceptance: `.\.venv\Scripts\python.exe -m reticle project <session>` on
the fast tier, then `.\.venv\Scripts\python.exe -m reticle verify --tier fast`.
Evidence: every consumer row with a name carries a `ref` that resolves to a
resolved verdict; no two lanes bind one slot key to two agents; the
resolution metric per kind before and after.

**Stage 3: consumers move.** `overlay`, `clipserve`, `coach` and `sql` read
`EntityEvents`, one per item, each joining `[consumers]`.
Acceptance: `.\.venv\Scripts\python.exe -m reticle doctor` reports 0 errors
with all of them declared; `.\.venv\Scripts\python.exe -m reticle overlay bfad2778a372`
draws round 1 from the lanes alone.
Evidence: each consumer's output before and after, with every difference
traced to a ledger row or an owner change; the player views one rendered
round.

**Stage 4: the gaps.** Gaps 2 to 11 in order, each an owner item; each
bumps the owner's version and rebuilds only its lanes.
Acceptance: `.\.venv\Scripts\python.exe -m reticle plan` names no stale
lane after each.
Evidence: the resolution metric per kind, with the resolved-and-wrong share
on the player's labels flat or falling.

**Stage 5: the minimap target.** Debt share zero for every minimap lane on
the fast tier, then the corpus; the player expects this within a few
iterations.
Acceptance: the `entity_events/resolution` series shows debt share zero for
the lanes of order 1 and 2 on every fast-tier session.
Evidence: each remaining minimap ledger row is residual with its declared
reason, or a named disagreement the player has reviewed.

**Stage 6: the audio lanes.** Lanes `ult_cast` and audio casts, and gap 12.
Their debt is recorded from the first run and held to the target only when
their owners can reach it.
Acceptance: `.\.venv\Scripts\python.exe -m reticle project <session> --lane ult_cast`
on the fast tier records the resolution metric.
Evidence: debt share per audio kind falls run over run, with the
resolved-and-wrong share flat; the player reviews a sample of residual rows.

## 7. The scene model

The scene model's joint fit is a reader: it reads the crop cache with the
predicted state as its prior and stores its fits as observations with
`rests_on` ([SCENE_MODEL.md](SCENE_MODEL.md), sections 2 and 3).
Adjudication weighs them once, and its portrait comparisons reach names
only as arbiter claims. The fit's outputs are therefore stored owner
answers, and they enter the projection the way every owner's do: the
`round_entity` lane's inputs change from `round_entity` and a pose owner to
the scene model's adjudicated poses, the lane's version bumps, and the
contract does not change. Consumers see more rows reach the output and
nothing else.

Two rules keep the mesh from folding back on itself. The scene model's
prior is its own stored fit, never a consumer event; reading entity events
as evidence would count each observation twice. And the scene model's state
(section 1 of that plan) is held by adjudication; the projection copies
the answers it stores and holds no state of its own. Its per-field
standings translate into the ledger's standings, so its refusals count as
debt or residual like any owner's.

## 8. The player's answers

The plan asked three questions no fact or note answered. The player
answered them on 2026-09-30; this section paraphrases him.

1. **What the annotated match shows.** For now the viewer draws both the
   consumer events and the ledger rows, the ledger apart in amber, as a
   convenient overview. The viewer is therefore a `review` consumer
   (section 4).
2. **Between observations.** It depends on whether the object is expected
   to be unobserved. An alive ally always shows a position estimate, as the
   crowded and overlapping icon work does; an enemy shows one too, until its
   icon becomes the red "?", after which the event is the last-known mark.
   Section 2 makes this a per-family rule; an estimate is an owner's output
   with its basis, and the projection interpolates nothing.
3. **What drops.** The residual class is the end state, not the only thing
   that drops for now. Audio detection barely works, so many audio-only
   events will be debt, while minimap-observable events should reach the
   consumer output within a few iterations. The lane order (section 3) and
   stages 5 and 6 follow from this.

The open question the rule leaves is what an unobserved object of any other
family shows -- a smoke under a menu, a ping behind the scoreboard. Until
the player or a fact answers per family, those gaps are `not_observed`.

## What this plan does not settle

- No projection exists; every example row above is a design over stored
  rows, not an output.
- The map frame's transform is not measured: whether profiles of one map
  differ by scale and offset alone is `geometry`'s to show.
- The orientation convention is named by the contract only once the
  icon-pose owner states what it stores.
- The residual rule's opportunity test needs owners to store which channels
  could have witnessed an event; none stores it yet.
- The round viewer's own field gaps, which its builder is reporting, are
  not merged here.
