# Episodes: round phases, duels, engagements, trades, executes, retakes, rotations, lurks

Status: design, proposed 2026-10-05; implemented by `reticle/episodes.py`
(`episodes-0.1.0`) and `reticle/line_of_sight.py` (`line-of-sight-0.1.0`).
Rules live in [AGENTS.md](../AGENTS.md); commands in
[WORKING_MAP.md](WORKING_MAP.md).

The player agreed on three levels (2026-10-05): (1) a **state timeline**,
every player slot and its ability children with position, facing, life and
loadout at any instant; (2) **events**, the transitions of that state, with
provenance; (3) **episodes**, derived intervals with participants and an
outcome, which clips, win-probability swings and coaching hang off. The
replay layer (`replay_layer`, branch `replay-children-truth-20261005`)
writes level 1 and the replay's own events from each kept replay with
`source = truth`. This document defines level 3 over that schema. A future
vision timeline feeds the same code with `source = vision` (section 5).

## 0. What the repo already defines, and reuse

| Owner or design | What it fixes | Used here as |
|---|---|---|
| `rounds` (`round-bounds`) | round bounds; a kill in the post-round period belongs to the round just decided [domain:rounds/post-round-period] | a round runs from its buy phase to the next round's start |
| `rounds.side_in_round`, [domain:rounds/side-by-round] | the side each team plays per match round | the attacking team per round |
| [COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md) §2, §7 | "dies traded within 5 s" | the trade window's default (Q5) |
| `engagement-reach` (§9 there) | swing 2 m, trade 5 m walking reach, fixed on the captured records | not used yet: reach needs the walk graph (section 6) |
| [SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md) | Weapon-blocking triangles per map from the game's collision; eye and body heights from the game files | the occluders of every sight test |
| [COACHING_ROTATIONS_LURKS.md](COACHING_ROTATIONS_LURKS.md) §1.2 | `team_commit`, `rotation`, `lurk` as events over regions | the execute, rotation and lurk definitions, with replay positions |
| [ECONOMY_AND_PREDICTION_DESIGN.md](ECONOMY_AND_PREDICTION_DESIGN.md) §5 | an episode keeps member ids, interval and uncertainty | the episode row's members and evidence |

`combat-report-round` produces "episodes" of the combat report's panels; the
name collides, the meaning does not. Those are panel spans, not these.

## 1. Input: the state timeline and its events

Episodes read one `Timeline` per match (`episodes.Timeline`):

- `slots`: ten players, each `slot_id` (the replay's subject; a vision
  timeline's `<session>:<team>:slot:<k>`), `team` (a team id, never a side
  [domain:rounds/halftime-side-swap]) and `agent`;
- `sample(t)`: per slot at times `t`, world `x, y, z` (cm; `z` is the
  actor's location, the capsule centre), `yaw` and `pitch` (degrees), and
  `alive`; an unread value is NaN with a standing (`observed`, `inferred`,
  `unknown`);
- `events`: `round_start`, `buy_end`, `round_end` (the round decided),
  `plant` (planter, position), `defuse`, `detonate`, `death` (killer, victim,
  damage type), `damage` (attacker, victim, amount, wall penetration), each
  with its source row as evidence;
- `map`, `source` (`truth` or `vision`) and the input stamps.

The replay supplies every field: positions and yaw at 128 Hz
[domain:replay/vrf-position-stream], round phases from the game mode's
phase changes (`MulticastSetPhase`: 2 round setup, 3 buy, 4 buy end, 5
round end, read off b03fecd3), and per-hit damage (`MulticastNotifyDamage_*`
with instigator, victim, amount and `bIsWallPenetration`). Episodes never
read the parse; they read the replay layer's tables through its API, and an
adapter (`episodes.from_replay_layer`) is the only code that knows them.

## 2. Primitive: sight

**Directed sight** `sees(i, j, t)`, for opposing living players: (a) line
of sight from i's eye to j's body centre or j's eye, unblocked by the map's
Weapon-blocking triangles, and (b) that point inside i's view frustum.

- Eye: actor location plus 77 cm, the standing eye above the capsule centre
  [domain:game_data/character-eye-height]. The replay's `z` sits a median
  100 cm above the table's floor cell under it (20,000 samples of
  b03fecd3), the capsule half-height plus a float. A crouched eye is not
  derivable from the files (same fact); a crouched player's eye is placed at
  the standing offset above his lowered centre.
- Body centre: the actor location [domain:game_data/character-eye-height].
- Occluders: the map's 3D sightline table (`<store>/sightlines/`, the
  version `choice.json` names), its Weapon-channel triangles, cast by
  embree. Doors, breakables, smokes and walls cast by abilities are absent:
  a sight through a smoke counts (section 6).
- Frustum: horizontal field of view `HFOV_DEG`, vertical from it at 16:9
  (the engine keeps the horizontal FOV, `AspectRatio_MaintainXFOV` in
  `DefaultEngine.ini`). The value is unread: Q1.
- Sampled at `SIGHT_HZ` = 16 inside each round's play (buy end to the next
  round's start). A resolution, not a game quantity: onsets carry +-62.5 ms.

**Contact** (pairwise interval): a run of samples where `sees(i, j)` or
`sees(j, i)` holds, runs joined across gaps up to `CONTACT_MERGE_MS` (Q2).
A contact records `first_seer` and whether it was ever `mutual`. Contacts
are stored as their own table, the sight-state transitions of level 2.

## 3. Episode kinds

Every episode row carries `episode_id`, `kind`, `round`, `t_start_ms`,
`t_end_ms` (replay ms; the capture clock comes from the replay layer's
alignment where one exists), `participants` (slot ids with roles),
`outcome`, `members` (the ids of the duels, kills or contacts it rests on),
`evidence` (event ids) and `params` (the parameter values it used). Times are
the timeline's; a bound that rests on a sample carries the sample period.

### 3.1 Round phases

Per round, four intervals that tile it:

| Phase | Start | End |
|---|---|---|
| `buy` | `round_start` (phase 3) | `buy_end` (phase 4) |
| `live` | `buy_end` | the plant, else `round_end` |
| `post_plant` | the plant | `round_end` |
| `round_over` | `round_end` (phase 5) | the next `round_start`, else the match's end |

Outcome on the round's `live` or `post_plant` row: `end_reason` (`defuse`
if a defuse; `detonation` if a detonation; `elimination` if a team has no
living player at `round_end`; else `time`) and `winner` (defuse and time:
defenders; detonation: attackers; elimination: the surviving team). The
attacking team per round comes from `rounds.side_in_round`, the starting side
read from round 1's planter or, without a plant, from which team stands in
the attacker spawn's callout volume at buy end. No parameter.

Cross-check: each `round_end` should follow the deciding event (last death,
defuse, detonation); the lag distribution is reported, never fitted.

### 3.2 Duel

A **duel** is a bout between two opposing players with at least one combat
act between them: a damage event either way, or a kill of one by the other.
Proximity alone never makes one.

- Acts of the pair are split into bouts where two consecutive acts lie more
  than `DUEL_GAP_MS` (Q3) apart and no contact of the pair spans the gap.
- **Start**: the earlier of the bout's first act and the onset of the
  pair's contact that is open at that act or closed at most
  `CONTACT_MERGE_MS` before it.
- **End**: the first death of either player in the bout; else the later of
  the last act and the end of the contact open at it.
- **Outcome**: `killed` (who killed whom), `third_party` (one of them died
  to someone else inside the bout), or `disengaged` (both lived).
- **Fields**: `first_seer`, `first_hitter`, `mutual` (each saw the other
  before the end), `sight_at_kill` (the killer saw the victim within
  `SIGHT_HZ` samples of the kill), `wallbang` (any act flagged wall
  penetration), damage dealt each way, `opening` (the round's first kill).

### 3.3 Engagement

An **engagement** is a connected group of duels. Two duels join when (a) they
share a player and the gap between their intervals is at most
`ENGAGE_JOIN_MS` (Q4), or (b) they overlap in time and a contact links a
player of one to an opposing player of the other inside the overlap.

- Interval: the union of its duels.
- Participants: `combatant` (in a duel), `witness` (an opposing contact with
  a combatant inside the interval, no act).
- Outcome: kills and deaths per team, survivors per team, `winner` (the team
  with more kills; `even` on a tie).

**Every kill belongs to exactly one engagement**, because a kill by an
opponent is an act and so lies in one duel. A death outside every
engagement is listed with its reason: `no_killer` (fall, spike, a killer
the timeline cannot name), `same_team`, or `outside_round`. That list is
part of the stored output.

### 3.4 Trade

A kill K1 (A kills B at t1) is **traded** by K2 when a teammate C of B kills
A at t2 with 0 < t2 - t1 <= `TRADE_WINDOW_MS` (Q5); the first such K2.
Interval [t1, t2]; participants `traded` B, `killer` A, `trader` C; fields
`same_engagement` (K1 and K2 in one engagement), `trader_saw_killer_at_t1`
and `trader_distance_m` at t1. A revived victim is still traded; the revive
is recorded beside it.

### 3.5 Execute (attack)

Per round, the attacking team's **commit**: the first instant at which
`EXECUTE_K` (Q6) living attackers, or all living attackers if fewer, stand in
one site super-region (Q7), or the plant, whichever is first. The execute runs
from that instant to the plant, else to the last attacker's death, else to
`round_end`. Outcome `planted` or `not_planted` (with the reason:
`attackers_eliminated`, `time`). Participants: the attackers in the site at
the commit (`committed`), the rest (`elsewhere`). One per round at most.

### 3.6 Retake (defence)

After a plant, when no living defender stands in the planted site's
super-region at the plant (Q8), the defenders' **retake** runs from the
plant to the defuse, the detonation or the last defender's death. Its
`entry_ms` is the first instant a defender enters the site super-region.
Outcome `defused`, `detonated` or `defenders_eliminated`. A plant with a
defender on site is a `contested_plant`, recorded on the round's
`post_plant` row, not a retake.

### 3.7 Rotation

Per player, during `live` and `post_plant`: a move from one site
super-region to another, directly or through Mid, after at least
`ROTATION_MIN_DWELL_MS` (Q9) in the origin. Start: the last sample in the
origin; end: the first in the destination, or null with `died_en_route` or
`round_ended`. Fields: `from_site`, `to_site`, `path` (super-regions),
`duration_ms`, `cues` (deaths and the plant inside the
`ROTATION_CUE_MS` = `TRADE_WINDOW_MS` before the start; co-occurrence, never
cause).

### 3.8 Lurk

Per attacker, during an execute: the attacker stands outside the execute's
site super-region for at least `LURK_MIN_MS` (Q10) of it. Interval: the
overlap of the attacker's time elsewhere with the execute. Fields: the
super-regions held, his first kill or death, and whether it fell inside an
engagement with a committed teammate.

### Regions

Super-regions come from the map's callout volumes (the game's named
playable regions, stored with each sightline table) labelled by
valorant-api's callout points (`regionName`, `superRegionName`: A, B, C,
Mid, Attacker Side, Defender Side) that lie inside each volume, the
majority label winning; a volume holding no point takes its nearest point's
label. Volume names are not used: five maps name them only by number. A
position outside every volume keeps the last super-region it held.

## 4. Parameters

| Name | Default | Kind | Source |
|---|---|---|---|
| eye above the capsule centre | 77 cm | game file | [domain:game_data/character-eye-height] |
| body target | capsule centre | game file | same fact |
| occluders | Weapon-channel triangles of the map's table | game file | [SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md) |
| `HFOV_DEG` | 103 | **player** (Q1); the files keep it fixed, the value is unread | `DefaultEngine.ini` |
| `SIGHT_HZ` | 16 | resolution, not a game quantity | -- |
| `CONTACT_MERGE_MS` | 500 | **player** (Q2) | -- |
| `DUEL_GAP_MS` | 3000 | **player** (Q3) | -- |
| `ENGAGE_JOIN_MS` | 5000 | **player** (Q4) | -- |
| `TRADE_WINDOW_MS` | 5000 | **player** (Q5); the repo's convention, never asked | COACHING_DECISION_VALUE §2 |
| `EXECUTE_K` | 3 | **player** (Q6) | COACHING_ROTATIONS_LURKS §1.2 proposal |
| site super-region | valorant-api's A, B, C | **player** (Q7) | valorant-api callouts |
| retake gate | no defender on site at the plant | **player** (Q8) | -- |
| `ROTATION_MIN_DWELL_MS` | 3000 | **player** (Q9) | -- |
| `LURK_MIN_MS` | 5000 | **player** (Q10) | -- |

None is fitted. Each could be fitted to the player's labels of episodes,
never to these replays' outcomes, which would make the sanity statistics
their own training set.

## 5. Questions only the player can answer

1. **Field of view.** Is every player's horizontal FOV 103 degrees?
   Default 103.
2. **A break in sight.** How long may two players lose sight of each other
   and still be in the same contact (peeking back after a jiggle)? Default
   0.5 s.
3. **One duel or two.** Two players trade shots, both hide, then re-peek:
   after how long without sight or damage is it a new duel? Default 3 s.
4. **One fight or two.** When does a duel involving a player who just
   fought belong to the same engagement? Default within 5 s, the trade
   window.
5. **Trade window.** A kill avenged within how many seconds is a trade?
   Default 5 s. Should a trade require the trader to have been able to
   see the killer at the first kill? Default no; the field is stored.
6. **Execute.** How many attackers on a site make a commit? Default 3, or
   all living if fewer.
7. **What counts as "on site"** for an execute and a retake: the whole A
   super-region (A Main, A Link and the site), or the site callout alone?
   Default the super-region.
8. **Retake.** Is a plant with a defender still on site a retake?
   Default no (a contested plant).
9. **Rotation.** How long must a player hold one site before leaving counts
   as a rotation? Default 3 s.
10. **Lurk.** How long apart from an execute makes a lurk? Default 5 s.

## 6. Not modelled, and what each needs

- Smokes, walls and blinds cut sight; the replay's ability children (level
  1) carry each smoke's place and life, so a later version subtracts
  smoked segments. Until then contacts over-count; duels do not, since they
  need an act.
- Doors and breakables (left out of the tables); posture (crouch lowers the
  centre only); wallbangs show as acts without sight (`wallbang` field).
- Walking reach (`engagement-reach`'s swing and trade) needs the table's
  walk graph in `reticle`; `trader_distance_m` stands in, a straight line.
- Clutches, entries beyond `opening`, and post-plant holds are not defined.

## 7. A vision timeline

`episodes.derive_episodes(timeline)` reads only `Timeline`. A vision timeline built
by the slot-state owner ([ENTITY_STATE.md](ENTITY_STATE.md)) fills the same
fields with `source = vision`: positions where a slot is observed or
inferred, NaN with `unknown` elsewhere, damage events absent. Each episode
then records the standing of the samples it rests on; a contact over an
`unknown` sample is not formed, so episodes under-report rather than invent,
and the truth episodes of the same match score them.

## 8. Storage and wiring

One JSONL file per match and source, `<store>/episodes/<source>/<key>.jsonl`:
a `header` row (version, source, map, input stamps, parameters), then
`episode`, `contact` and `unassigned_death` rows. `reticle plan` names the
stream `episodes` stale or missing downstream of the replay layer and builds
it with `reticle episodes <match>`; doctor's EPISODES check errors when a
match with a current replay layer lacks current episodes.
