# Episodes: round phases, duels, engagements, trades, executes, retakes, rotations, lurks

Status: design, proposed 2026-10-05; implemented by `reticle/episodes.py`
(`episodes-0.1.0`), `reticle/line_of_sight.py` (`line-of-sight-0.1.0`) and
`reticle/map_regions.py` (`map-regions-0.1.0`). Rules live in
[AGENTS.md](../AGENTS.md); commands in [WORKING_MAP.md](WORKING_MAP.md).

The player agreed on three levels (2026-10-05): (1) a **state timeline**,
every player slot and its ability children with position, facing, life and
loadout at any instant; (2) **events**, the transitions of that state, with
provenance; (3) **episodes**, derived intervals with participants and an
outcome, which clips, win-probability swings and coaching hang off. The
replay layer ([REPLAY_LAYER.md](REPLAY_LAYER.md)) writes levels 1 and 2
from each kept replay with `source = truth`. This document defines level 3
over that schema. A vision timeline feeds the same code with
`source = vision` (section 7).

## 0. What the repo already defines, and reuse

| Owner or design | What it fixes | Used here as |
|---|---|---|
| `rounds` (`round-bounds`) | a kill in the post-round period belongs to the round just decided [domain:rounds/post-round-period]; a post-round plant decides nothing [domain:rounds/post-round-plant-no-graphic] | a round runs from its buy phase to the next round's start; a late plant is kept apart |
| `rounds.side_in_round`, [domain:rounds/side-by-round] | the side each team plays per match round | a check on the attacking team read from spawns |
| [COACHING_DECISION_VALUE.md](COACHING_DECISION_VALUE.md) §2, §7 | "dies traded within 5 s" | the trade window's default (Q5) |
| `engagement-reach` (§9 there) | swing 2 m, trade 5 m walking reach | not used yet: reach needs the walk graph (section 6) |
| [SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md) | Weapon-blocking triangles per map from the game's collision; eye and body heights from the game files | the occluders of every sight test |
| [COACHING_ROTATIONS_LURKS.md](COACHING_ROTATIONS_LURKS.md) §1.2 | `team_commit`, `rotation`, `lurk` over regions | the execute, rotation and lurk definitions, on replay positions |
| [ECONOMY_AND_PREDICTION_DESIGN.md](ECONOMY_AND_PREDICTION_DESIGN.md) §5 | an episode keeps member ids, interval and uncertainty | the episode row's members and evidence |

`combat-report-round` produces "episodes" of the combat report's panels; the
word collides, the meaning does not.

## 1. Input: the state timeline and its events

Episodes read one `Timeline` per match (`episodes.Timeline`):

- `slots`: ten players, each `slot_id` (the replay's subject; a vision
  timeline's `<session>:<team>:slot:<k>`) and `team` (a team id, never a
  side [domain:rounds/halftime-side-swap]). Rows carry slot ids, never an
  agent name;
- `sample(t)`: per slot at times `t`, world `x, y, z` (cm; `z` is the
  actor's location, the capsule centre), `yaw` and `pitch` (degrees, pitch
  up positive, stored wrapped to 0-360), and `alive`; an unread value is
  NaN;
- `events`: `round_start`, `buy_end`, `round_end` (the round decided),
  `plant` (position), `defuse`, `detonate` where the source has one,
  `death` (killer, victim), `damage` (attacker, victim, amount, wall
  penetration, damage type) and `revive`, each with its source row's id;
- `map`, `source` (`truth` or `vision`) and the input stamps.

`episodes.from_replay_layer` is the only code that knows the layer's
tables: ticks for position and view, `lives` for life (revives included),
`rounds` for phases (`MulticastSetPhase` 3, 4 and 5), `kill`, `damage`,
`plant`, `defuse` and `revive` events, and the planted spike's spawn
(`TimedBomb_C`) for the plant's place; the layer names no planter or
defuser. Times are the replay's clock; the header keeps the layer's capture
offset `a_ms`. Rounds are numbered from 1 (the layer's round + 1), as the
in-client replay counts them.

## 2. Primitive: sight

**Directed sight** `sees(i, j, t)`, for opposing living players: (a) the
segment from i's eye to j's body centre or to j's eye crosses no
Weapon-blocking triangle, and (b) that point lies inside i's view frustum.

- Eye: actor location plus 77 cm, the standing eye above the capsule centre
  [domain:game_data/character-eye-height]. On 20,000 samples of b03fecd3 the
  replay's `z` sits about one capsule half-height above the table's floor
  cell under it. A crouched eye is not derivable from the files (same fact);
  a crouched player's eye stands at the standing offset above his lowered
  centre.
- Occluders: the map's 3D sightline table (`<store>/sightlines/`, the
  version `choice.json` names), its Weapon-channel triangles, cast by
  embree. Doors, breakables, smokes and ability walls are absent: a sight
  through a smoke counts (section 6). The tables are built from
  release-13.06; replays from older builds use the newer map.
- Frustum: horizontal field of view `HFOV_DEG`, vertical from it at 16:9
  (the engine keeps the horizontal FOV, `AspectRatio_MaintainXFOV` in
  `DefaultEngine.ini`); the value is unread: Q1. At the replay's kills the
  killer's yaw and pitch point at the victim (b03fecd3: yaw within a
  median 0.4 degrees, pitch correlated 0.92 with the elevation to the
  victim's eye), which fixes the conventions.
- Sampled at `SIGHT_HZ` = 16 from each round's buy end to the next round's
  start. A resolution, not a game quantity: onsets carry +-62.5 ms.

**Contact** (pairwise interval): a run of samples where `sees(i, j)` or
`sees(j, i)` holds, runs joined across gaps up to `CONTACT_MERGE_MS` (Q2).
A contact records `first_seer` and whether it was ever `mutual`. Contacts
are stored as their own rows: the sight-state transitions of level 2.

## 3. Episode kinds

Every episode row carries `episode_id`, `kind`, `round`, `t_start_ms`,
`t_end_ms`, `participants` (slot ids by role), `outcome`, `members` (the
event or episode ids it rests on) and kind-specific fields. The header row
carries the parameters and each one's kind.

### 3.1 Round phases

Per round, four intervals that tile it:

| Phase | Start | End |
|---|---|---|
| `phase_buy` | `round_start` (buy phase opens) | `buy_end` (phase 4) |
| `phase_live` | `buy_end` | the plant, else `round_end` |
| `phase_post_plant` | the plant | `round_end` |
| `phase_round_over` | `round_end` (phase 5) | the next `round_start`, else the match's end |

A plant at or after `round_end` is `post_round_plant`, outside the phases.
The outcome sits on the round's last play phase: `end_reason` and `winner`.
Before a plant, a team with nobody alive just after `round_end` (life from
the timeline, which carries revives) loses by `elimination`; with both teams
standing the defenders win on `time`. After a plant a defuse wins for the
defenders; otherwise every defender dead is `elimination`, else
`detonation`. `decisive_ms` is the defuse or the eliminated team's last
death, and `end_lag_ms` the round end after it.

**Attacking team.** The team whose living players, over the second half of
the buy phase (held behind their barrier), stand nearer valorant-api's
attackers' `Spawn` callout than the defenders' attacks; a planter, where the
timeline names one, is a second witness. `rounds.side_in_round` checks
every round against round 1's side and stores each disagreement as a note;
it fills no round.

### 3.2 Duel

A **duel** is a bout between two opposing players with at least one combat
act between them (a damage event either way, or a kill of one by the other)
and either a kill or sight between them. Proximity alone never makes one.

- The pair's acts split into bouts where two consecutive acts lie more than
  `DUEL_GAP_MS` (Q3) apart and no contact of the pair spans the gap.
- A kill ends its bout. The pair's acts within `DUEL_GAP_MS` after the kill
  stay in it: the killing hit is logged a few ms after the kill, and a dead
  player's utility keeps dealing damage.
- **Start**: the earlier of the bout's first act and the onset of the
  pair's contact open at that act or closed at most `CONTACT_MERGE_MS`
  before it. **End**: the kill; else the later of the last act and the end
  of the contact open at it; cut at a death of either to a third player.
- **Outcome**: `killed` (killer, victim, `kill_event`), `third_party`, or
  `disengaged`.
- **Fields**: `first_seer`, `first_hitter`, `mutual`, `sight`,
  `sight_at_kill` (the killer saw the victim within the last
  `SIGHT_AT_KILL_MS` = 1 s, a report window), `wallbang`, damage each way,
  `hits`, `opening` (the round's first kill).

A bout with no kill whose pair never saw each other is **remote damage**
(`remote_damage`: utility, a spray through a wall) and joins no engagement.

### 3.3 Engagement

A connected group of duels. Two duels join when (a) they share a player and
the gap between their intervals is at most `ENGAGE_JOIN_MS` (Q4), or (b)
they overlap in time and a contact links a player of one to an opposing
player of the other inside the overlap.

- Interval: the union of its duels. Participants: `combatants`, and
  `witnesses` (an opposing contact with a combatant inside the interval,
  no act).
- Outcome: kills, deaths and surviving combatants per team; `winner`, the
  team with more kills, or `even`. `kill_events` lists its kills.

**Every kill belongs to exactly one engagement**: a kill by an opponent is
an act, so it lies in exactly one duel. A death outside every engagement is
an `unassigned_death` row with its reason: `no_killer` (fall, spike, a
killer the layer cannot name), `same_team`, or `outside_round`.

### 3.4 Trade

A kill K1 (A kills B at t1) is **traded** by the first K2 in which a
teammate C of B kills A at t2, 0 < t2 - t1 <= `TRADE_WINDOW_MS` (Q5).
Interval [t1, t2]; participants `traded` B, `killer` A, `trader` C; fields
`same_engagement`, `trader_saw_killer_at_t1`, `trader_distance_m`
(straight line at t1) and `traded_revived`.

### 3.5 Execute (attack)

Per round, the attacking team's commit: the first instant before the plant
at which `EXECUTE_K` (Q6) living attackers, or all living attackers if
fewer, stand in one site super-region (A, B or C; Q7), else the plant. The
execute runs from that instant to the plant, else to the last attacker's
death, else to `round_end`. Outcome `planted`, or `not_planted` with
`attackers_eliminated` or `time_or_round_end`; participants `committed`
(in the site at the commit) and `elsewhere`; `trigger` (`presence` or
`plant`); `site_same_as_plant`.

### 3.6 Retake (defence)

After a plant with no living defender in the plant's super-region (Q8), the
**retake** runs from the plant to the defuse, the detonation (the round's
end) or the last defender's death. `entry_ms` is the first instant a
defender enters the super-region. Outcome `defused`, `detonated`,
`defenders_eliminated` or `unresolved`. A plant with a defender on site is
a `contested_plant` row (instant, `on_site` defenders), not a retake.

### 3.7 Rotation

Per player, from buy end to `round_end`: alive throughout, a site
super-region held at least `ROTATION_MIN_DWELL_MS` (Q9), then a different
site super-region, through any non-site super-regions. Start: the last
sample in the origin; end: the first in the destination. Fields
`from_site`, `to_site`, `path`, `duration_ms`, `cues` (deaths and the plant
within `TRADE_WINDOW_MS` before the start; co-occurrence, never cause).

### 3.8 Lurk

Per attacker, during an execute: a run of at least `LURK_MIN_MS` (Q10)
alive outside the execute's site super-region. Fields: the super-regions
held, his first kill or death in the run, and whether it fell in an
engagement with a committed teammate.

### Regions

Super-regions come from the map's callout volumes (the game's named
playable regions, stored with each sightline table). The boxes of one actor
are one region, labelled by valorant-api's callout points (`regionName`,
`superRegionName`) inside them, the most points winning and a tie going to
the point nearest the volume's centre; an actor holding none takes the
points over or under it in plan (`plan`), else the point nearest its centre
(`nearest`). Volume names are not labels: five maps name them only by
number. A position outside every volume keeps the last super-region held,
and a super-region entered for less than `REGION_HOLD_MS` (Q9) keeps the
one before it, so a step over a boundary is no move.

Label quality varies by map. Ascent, Bind, Haven and Split label every
volume `inside`; Breeze, Corrode and Pearl leave four to five actors on the
`nearest` rule. Where two site super-regions touch (Bind's A and B links and
teleporters, the B site of Haven and Lotus between the A and C links), a
short move is a rotation by this definition.

## 4. Parameters

| Name | Default | Kind | Source |
|---|---|---|---|
| eye above the capsule centre | 77 cm | game file | [domain:game_data/character-eye-height] |
| body target | capsule centre | game file | same fact |
| occluders | Weapon-channel triangles of the map's table | game file | [SIGHTLINES_3D_PROBE.md](SIGHTLINES_3D_PROBE.md) |
| `HFOV_DEG` | 103 | **player** (Q1); the files fix the axis, not the value | `DefaultEngine.ini` |
| `SIGHT_HZ`, `REGION_HZ` | 16, 4 | resolution | -- |
| `SIGHT_AT_KILL_MS` | 1000 | report window | -- |
| `CONTACT_MERGE_MS` | 500 | **player** (Q2) | -- |
| `DUEL_GAP_MS` | 3000 | **player** (Q3) | -- |
| `ENGAGE_JOIN_MS` | 5000 | **player** (Q4) | -- |
| `TRADE_WINDOW_MS` | 5000 | **player** (Q5); the repo's convention, never asked | COACHING_DECISION_VALUE §2 |
| `EXECUTE_K` | 3 | **player** (Q6) | COACHING_ROTATIONS_LURKS §1.2 proposal |
| site super-region | valorant-api's A, B, C | **player** (Q7) | valorant-api callouts |
| retake gate | no defender on site at the plant | **player** (Q8) | -- |
| `ROTATION_MIN_DWELL_MS`, `REGION_HOLD_MS` | 3000, 1000 | **player** (Q9) | -- |
| `LURK_MIN_MS` | 5000 | **player** (Q10) | -- |

None is fitted. Each could be fitted to the player's labels of episodes,
never to these replays' outcomes, which would make the sanity statistics
their own training set.

## 5. Questions only the player can answer

1. **Field of view.** Is every player's horizontal FOV 103 degrees?
   Default 103.
2. **A break in sight.** How long may two players lose sight of each other
   and stay in one contact (a jiggle peek)? Default 0.5 s.
3. **One duel or two.** Two players trade shots, both hide, then re-peek:
   after how long without sight or damage is it a new duel? Default 3 s.
4. **One fight or two.** When does a duel of a player who just fought belong
   to the same engagement? Default within 5 s, the trade window.
5. **Trade window.** A kill avenged within how many seconds is a trade?
   Default 5 s. Must the trader have been able to see the killer at the
   first kill? Default no; the field is stored.
6. **Execute.** How many attackers on a site make a commit? Default 3, or
   all living if fewer.
7. **What counts as "on site"** for an execute and a retake: the whole A
   super-region (A Main, A Link and the site), or the site callout alone?
   Default the super-region. On Bind, Haven and Lotus this decides most
   short rotations and most contested plants.
8. **Retake.** Is a plant with a defender still on site a retake?
   Default no (a contested plant).
9. **Rotation.** How long must a player hold one site before leaving counts
   as a rotation, and how long in a new area before he is there? Default
   3 s and 1 s. Is a Bind teleport a rotation? Default yes.
10. **Lurk.** How long apart from an execute makes a lurk? Default 5 s.
11. **Remote damage.** Is utility damage on an unseen opponent part of a
    fight? Default no: it is `remote_damage`, outside engagements.

## 6. Not modelled, and what each needs

- Smokes, walls and blinds cut sight; the layer's ability children carry
  each smoke's place and life, so a later version subtracts smoked
  segments. Until then contacts over-count; duels need an act and do not.
- Doors and breakables (left out of the tables); posture beyond the
  lowered centre; wallbangs show as acts without sight (`wallbang`).
- Walking reach (`engagement-reach`'s swing and trade) needs the table's
  walk graph in `reticle`; `trader_distance_m` stands in, a straight line.
- Clutches, entries beyond `opening`, post-plant holds and enemy-side
  information (who could know what) are not defined.

## 7. A vision timeline

`episodes.derive_episodes(timeline)` reads only `Timeline`. A vision
timeline built by the slot-state owner ([ENTITY_STATE.md](ENTITY_STATE.md))
fills the same fields with `source = vision`: positions where a slot is
observed or inferred, NaN where unknown, no damage events. A sample with an
unread position is not alive for sight, so contacts form only over
observed or inferred samples and episodes under-report rather than invent;
duels then rest on kills and sight alone (`first_hitter` null with
`no_damage_events`). The truth episodes of the same match score them,
episode for episode. Vision episodes would be stored under
`analysis/episodes/vision/`; the stored output then needs each episode's
standing (the share of its samples observed, inferred or unknown), which
this version does not write.

## 8. Storage and wiring

One JSONL file per match and source,
`<store>/analysis/episodes/<source>/<match>.jsonl`: a `header` row (version,
source, map, parameters, input stamps), then `episode`, `contact`,
`unassigned_death` and `note` rows. `reticle episodes MATCH|SESSION`, or
`--all`, builds them; `--status` says which are current. `reticle plan
SESSION` names `episodes` absent or stale for a session whose kept replay
names it, downstream of `replay_layer`; doctor's EPISODES check errors on
every match whose replay layer is current and whose episodes are not.
`tools/episodes_sanity.py` writes the sanity report below.

## 9. Sanity run

Pending.
