# Episodes: round phases, duels, engagements, trades, executes, retakes, rotations, lurks

Status: design, proposed 2026-10-05; implemented by `reticle/episodes.py`
(`episodes-0.2.1`), `reticle/line_of_sight.py` (`line-of-sight-0.1.0`) and
`reticle/map_regions.py` (`map-regions-0.2.0`). Rules live in
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
fewer, stand on one site proper (the callout volume valorant-api names
`<X> Site`; Q7), else the plant. A site's super-region also holds its lobby
and main, where attackers stand at barrier drop; counting it, episodes-0.1.0
started 262 of 332 executes within 1 s of barrier drop. The
execute runs from that instant to the plant, else to the last attacker's
death, else to `round_end`. Outcome `planted`, or `not_planted` with
`attackers_eliminated` or `time_or_round_end`; participants `committed`
(on the site proper at the commit) and `elsewhere`; `trigger` (`presence` or
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
site super-region held as long; whatever lies between, a site crossed in
passing included, is the path. A `Link` volume (valorant-api's connector
callouts) holds no site: it belongs to one site's super-region and touches
another's. Start: the last sample in the origin; end: the first in the
destination. Fields
`from_site`, `to_site`, `path`, `duration_ms`, `cues` (deaths and the plant
within `TRADE_WINDOW_MS` before the start; co-occurrence, never cause).

### 3.8 Lurk

Per attacker alive at an execute's commit (`trigger` `presence`) who stands
outside both the executed site's super-region and the attackers' side
(valorant-api's `Attacker Side`): his run outside the two around the commit,
if it lasts at least `LURK_MIN_MS` (Q10). A player still on the attackers'
side lags; he does not lurk. Fields: the super-regions held, his first kill
or death in the run, and whether it fell in an engagement with a committed
teammate.

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
`nearest` rule. Two site super-regions touch where a connector is not
named `Link` (Lotus's B Main and C Door) and at Bind's teleporters, so a
rotation can last under a second; Q9 asks whether a teleport counts.

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
| on site (execute) | the callout volume named `<X> Site` | **player** (Q7) | valorant-api callouts |
| site area (retake, rotation, lurk) | valorant-api's A, B, C super-regions; `Link` volumes hold no site for a rotation | **player** (Q7, Q9) | valorant-api callouts |
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
7. **What counts as "on site"** for an execute: the site callout alone, the
   whole super-region (lobby and main included), or the plantable zone?
   Default the site callout: the super-region fires at barrier drop. The
   site callout misses plantable ground on seven maps (section 9), and the
   plantable zone needs geometry no table holds yet (the minimap's site
   paint, or the game's plant volumes). For a retake: default the
   super-region.
8. **Retake.** Is a plant with a defender still on site a retake?
   Default no (a contested plant).
9. **Rotation.** How long must a player hold one site, and then the other,
   for a move to count as a rotation? Default 3 s each; a stay under 1 s is
   a step over a boundary, no move. Is a Bind teleport a rotation? Default
   yes. Does a `Link` callout belong to a site? Default no.
10. **Lurk.** Who lurks: an attacker away from the hit at its commit, or
    anyone away from the team before it? How long apart? Default the first,
    for 5 s, never counting the attackers' side.
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

`tools/episodes_sanity.py --record` over episodes-0.2.1 of the 17 parsed
replays, held-out bd7efa02 excluded before any row was read:
[metric:episodes/sanity/pooled#matches=17] matches,
[metric:episodes/sanity/pooled#rounds=346] rounds,
[metric:episodes/sanity/pooled#kills=2592] kills. The development matches
are b03fecd3, 60c7f1e0 and 16a475cb; the rest are unlinked replays.

**Checks.**

- Kills: 2579 lie in exactly one engagement
  ([metric:episodes/sanity/pooled#kills_in_exactly_one_engagement=0.995]),
  none in two; the other 13 are listed as `unassigned_death`, every one
  `same_team` ([metric:episodes/sanity/pooled#unassigned_share=0.005]).
- Round phases take their boundaries from the replay's own round start,
  barrier drop, plant, defuse and round end, so they agree by
  construction; d6928558's last round has no barrier drop and no live
  phase. The independent check is Riot's match record: end reason and
  winner agree on 24 of 24 rounds of b03fecd3 and 28 of 28 of 60c7f1e0,
  the two replays with a record. The deciding event (last death, defuse)
  precedes the replay's round end by a median
  [metric:episodes/sanity/pooled#end_lag_ms.elimination.p50=25.0] ms
  (p95 [metric:episodes/sanity/pooled#end_lag_ms.elimination.p95=34.55] ms)
  after an elimination and
  [metric:episodes/sanity/pooled#end_lag_ms.defuse.p50=19.0] ms after a
  defuse.
- Sight: the killer saw his victim within 1 s before
  [metric:episodes/sanity/pooled#sight_at_kill=0.957] of kill duels;
  [metric:episodes/sanity/pooled#mutual_kill_duels=0.8736] were mutual.
  Kills end [metric:episodes/sanity/pooled#duel_kill_share=0.7796] of
  duels; [metric:episodes/sanity/pooled#traded_share=0.1842] of kills were
  traded, every trade inside one engagement
  ([metric:episodes/sanity/pooled#same_engagement_trades=1.0]);
  [metric:episodes/sanity/pooled#engagements_3plus=0.4067] of engagements
  hold three or more combatants.
- Executes: [metric:episodes/sanity/pooled#rounds_with_execute=0.7254] of
  rounds hold one; [metric:episodes/sanity/pooled#executes_planted=0.8207]
  end in a plant. Retakes follow
  [metric:episodes/sanity/pooled#retake_share_of_plants=0.2524] of plants.

Per match (`map` is the replay's codename: Duality Bind, Jam Lotus, Pitt
Pearl, Juliett Sunset, Bonsai Split, Port Icebox, Foxtrot Breeze, Rook
Corrode, Triad Haven):

| match | map (codename) | rounds | duels | engagements | trades | executes | retakes | rotations | lurks | killer saw victim |
|---|---|---|---|---|---|---|---|---|---|---|
| 05c76cb6 | Duality | 23 | 229 | 119 | 37 | 19 | 3 | 62 | 3 | [metric:episodes/sanity/05c76cb6#sight_at_kill=0.9611] |
| 1256eed3 | Juliett | 18 | 161 | 99 | 24 | 12 | 4 | 23 | 8 | [metric:episodes/sanity/1256eed3#sight_at_kill=0.9847] |
| 16a475cb | Jam | 20 | 191 | 96 | 28 | 16 | 2 | 109 | 3 | [metric:episodes/sanity/16a475cb#sight_at_kill=0.953] |
| 18585a5d | Pitt | 21 | 208 | 95 | 37 | 17 | 2 | 44 | 3 | [metric:episodes/sanity/18585a5d#sight_at_kill=0.9745] |
| 1a4c4618 | Duality | 24 | 207 | 125 | 20 | 18 | 2 | 78 | 1 | [metric:episodes/sanity/1a4c4618#sight_at_kill=0.9529] |
| 2c387cb6 | Duality | 25 | 219 | 122 | 34 | 16 | 3 | 64 | 0 | [metric:episodes/sanity/2c387cb6#sight_at_kill=0.9728] |
| 30e82ae0 | Bonsai | 15 | 136 | 75 | 15 | 8 | 2 | 33 | 2 | [metric:episodes/sanity/30e82ae0#sight_at_kill=0.9252] |
| 493b1eca | Port | 9 | 100 | 45 | 17 | 7 | 0 | 18 | 0 | [metric:episodes/sanity/493b1eca#sight_at_kill=0.9577] |
| 590a5d1b | Foxtrot | 23 | 199 | 109 | 33 | 18 | 4 | 38 | 4 | [metric:episodes/sanity/590a5d1b#sight_at_kill=0.9762] |
| 60c7f1e0 | Ascent | 28 | 273 | 150 | 32 | 18 | 4 | 49 | 3 | [metric:episodes/sanity/60c7f1e0#sight_at_kill=0.9552] |
| 6da71b0e | Foxtrot | 22 | 224 | 131 | 24 | 15 | 7 | 23 | 4 | [metric:episodes/sanity/6da71b0e#sight_at_kill=0.9822] |
| 7498df5e | Bonsai | 16 | 161 | 81 | 20 | 12 | 1 | 43 | 2 | [metric:episodes/sanity/7498df5e#sight_at_kill=0.9204] |
| 75111fd9 | Pitt | 24 | 246 | 125 | 30 | 20 | 2 | 74 | 5 | [metric:episodes/sanity/75111fd9#sight_at_kill=0.9402] |
| 75a5e757 | Rook | 23 | 229 | 111 | 51 | 17 | 3 | 39 | 1 | [metric:episodes/sanity/75a5e757#sight_at_kill=0.9508] |
| b03fecd3 | Ascent | 24 | 232 | 121 | 33 | 16 | 5 | 36 | 1 | [metric:episodes/sanity/b03fecd3#sight_at_kill=0.9278] |
| d6928558 | Triad | 9 | 74 | 36 | 10 | 6 | 2 | 21 | 1 | [metric:episodes/sanity/d6928558#sight_at_kill=0.9508] |
| dabcf7e5 | Rook | 22 | 219 | 118 | 30 | 16 | 6 | 55 | 1 | [metric:episodes/sanity/dabcf7e5#sight_at_kill=0.9649] |

Pooled per round, and durations:

| kind | per round | duration p10 / p50 / p90 (s) |
|---|---|---|
| duel | [metric:episodes/sanity/pooled#per_round.duel=9.561] | 0.3 / [metric:episodes/sanity/pooled#dur_s.duel.p50=0.82] / 2.44 |
| remote damage | [metric:episodes/sanity/pooled#per_round.remote_damage=0.405] | 0.0 / [metric:episodes/sanity/pooled#dur_s.remote_damage.p50=0.0] / 0.7 |
| engagement | [metric:episodes/sanity/pooled#per_round.engagement=5.081] | 0.34 / [metric:episodes/sanity/pooled#dur_s.engagement.p50=1.28] / 8.06 |
| trade | [metric:episodes/sanity/pooled#per_round.trade=1.373] | 0.3 / [metric:episodes/sanity/pooled#dur_s.trade.p50=2.05] / 4.27 |
| execute | [metric:episodes/sanity/pooled#per_round.execute=0.725] | 0.0 / [metric:episodes/sanity/pooled#dur_s.execute.p50=6.1] / 20.18 |
| lurk | [metric:episodes/sanity/pooled#per_round.lurk=0.121] | 13.6 / [metric:episodes/sanity/pooled#dur_s.lurk.p50=28.0] / 44.62 |
| retake | [metric:episodes/sanity/pooled#per_round.retake=0.15] | 8.32 / [metric:episodes/sanity/pooled#dur_s.retake.p50=28.47] / 43.54 |
| contested plant | [metric:episodes/sanity/pooled#per_round.contested_plant=0.442] | instant |
| rotation | [metric:episodes/sanity/pooled#per_round.rotation=2.338] | 0.25 / [metric:episodes/sanity/pooled#dur_s.rotation.p50=9.5] / 20.8 |
| post-plant phase | [metric:episodes/sanity/pooled#per_round.phase_post_plant=0.595] | 8.77 / [metric:episodes/sanity/pooled#dur_s.phase_post_plant.p50=24.98] / 40.58 |
| buy phase | -- | 29.79 / [metric:episodes/sanity/pooled#dur_s.phase_buy.p50=29.85] / 44.73 |
| live phase | -- | 22.4 / [metric:episodes/sanity/pooled#dur_s.phase_live.p50=36.9] / 73.93 |
| round over | -- | 7.1 / [metric:episodes/sanity/pooled#dur_s.phase_round_over.p50=7.14] / 7.21 |
| contact | [metric:episodes/sanity/pooled#contacts_per_round=19.61] | 0.12 / [metric:episodes/sanity/pooled#dur_s.contact.p50=0.69] / 2.25 |

**Three examples** to check in the in-client replay. Times are the round
clock (1:40 at barrier drop) or the spike's remaining time.

1. **Trade.** 60c7f1e0 (Ascent, session c817691bcd15), round 1, clock
   0:59 (40.1 s after barrier drop): Sage (Blue) kills Cypher (Red); Jett
   (Red) kills Sage 0.27 s later from 30.8 m. Blue wins the round by
   elimination.
2. **Retake.** 60c7f1e0, round 6: Red plants B with no Blue defender on B.
   Sage, KAY/O, Omen and Phoenix (Blue) retake; the first enters B 13.1 s
   after the plant; the defuse lands with about 1 s on the spike. Blue
   wins by defuse.
3. **Post-plant engagement.** 16a475cb (Lotus), round 1: team A plants C
   22.4 s after barrier drop. From 43 s to 35 s on the spike Jett (A)
   kills Clove, Sage and Neon (B), with Reyna and Chamber (A) in sight and
   no shot of theirs landing. A wins by elimination.

**Predictions** (`notes/predictions.jsonl`, task
`replay-episodes-20261005`). EP1-EP14 were written before the corpus run,
after development runs on b03fecd3 alone; EP15-EP22 test the definition
changes made after it, and test only whether those changes do what they
claim.

| ref | prediction | result | verdict |
|---|---|---|---|
| EP1 | killer saw victim 0.88-0.96 pooled, at least 0.80 per match | 0.957; lowest match 0.920 | held |
| EP2 | at most 2% of deaths outside engagements | 0.5%, all same-team | held |
| EP3 | 7-12 duels per round | 9.56 | held |
| EP4 | kills end 0.65-0.85 of duels | 0.78 | held |
| EP5 | 0.14-0.28 of kills traded | 0.184 | held |
| EP6 | every trade inside one engagement | 1.0; 0.0 in the first run, from a bug that keyed trades by a tail hit | held after the fix |
| EP7 | end lag median under 100 ms, p95 under 1000 ms | 25 ms, 35 ms | held |
| EP8 | spawn side agrees with the halftime rule on 99% of rounds; Riot end reason and winner on 95% | Riot 52 of 52; side 339 of 345 (98.3%) | half failed: the rule is wrong, not the spawn read. 493b1eca's 45 s buy phases at rounds 1, 5 and 9 mark four-round halves; 2c387cb6 disagrees in overtime round 25 |
| EP9 | 0.75-0.90 of kill duels mutual | 0.874 | held |
| EP10 | 3-6 engagements per round, 0.25-0.50 with three or more combatants | 5.08, 0.41 | held |
| EP11 | execute in 85% of rounds, 50% of executes planted | episodes-0.1.0: 0.96, 0.62 | held, hollowly: 262 of 332 executes began within 1 s of barrier drop, attackers counted on site from the lobby |
| EP12 | retakes follow 0.20-0.60 of plants | 0.25 | held |
| EP13 | 1.0-2.5 rotations per round | episodes-0.1.0: 2.86 | failed: borders between sites' super-regions |
| EP14 | contact median 0.4-1.0 s | 0.69 s | held |
| EP15 | at most 10% of executes start within 1 s of barrier drop | 0 of 251 | held; the execute's 0.0 s p10 duration is the plant fallback |
| EP16 | rounds with an execute 0.60-0.92; 70% planted | 0.725, 0.821 | held |
| EP17 | 0.8-2.0 rotations per round, at most 10% under 2 s | episodes-0.2.0: 2.63 | failed |
| EP18 | 0.8-1.8 lurks per round | episodes-0.2.0: 0.15 | failed: the lurk was bounded by the now-short execute |
| EP19 | other kinds unchanged | unchanged | held |
| EP20 | 1.0-2.2 rotations per round, under 10% shorter than 2 s | 2.34; 112 of 809 (13.8%) under 2 s | failed |
| EP21 | 0.3-1.2 lurks per round | 0.121 | failed |
| EP22 | other kinds unchanged | unchanged | held |

**What the run shows.**

- Sight, duels, engagements, trades and round phases behave as predicted
  on every match; they rest on the replay's positions, its kill and damage
  events and the game's geometry.
- Executes, retakes, rotations and lurks rest on callout labels, and the
  labels decide them. The site callout misses plantable ground: 60 of 214
  plants lie outside the volume named `<X> Site` (Breeze's A Pyramids,
  Pearl's B Hall, Corrode's A Crane, Sunset's A Alley, Lotus's C Bend and
  A Hut, Icebox's B Yellow, and one Ascent plant outside every volume), so
  29 executes fall back to the plant with no attacker counted on site.
  The plantable zone is the witness these need (Q7).
- Rotations stay frequent on Bind, Lotus and Corrode: Bind's teleporters
  (rotations under Q9's default), Lotus's B Main and C Door, and Corrode's
  labels on the `nearest` rule. A move under 2 s is no rotation a player
  would name; a walk-graph distance between the two holds would test one.
- Lurks are rare because the commit comes late, when most attackers stand
  on or beside the site. Q10 decides whether a lurk should be read earlier.
- A four-round half (493b1eca) and overtime (2c387cb6, round 25) break a
  twelve-round halftime rule; the attacking team is read from spawn, so no
  episode used the rule.
