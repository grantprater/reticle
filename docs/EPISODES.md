# Episodes: round phases, duels, engagements, trades, executes, retakes, rotations, lurks

Status: design, proposed 2026-10-05; implemented by `reticle/episodes.py`
(`episodes-0.3.0`), `reticle/line_of_sight.py` (`line-of-sight-0.1.0`),
`reticle/map_regions.py` (`map-regions-0.2.0`), `reticle/wall_penetration.py`
(`wall-penetration-0.1.0`) and `reticle/equippables.py`
(`equippables-0.1.0`). Rules live in
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

### 2.1 What reached the target

A gun kill needs a line of sight; a wallbang and an ability kill need none
[domain:weapons/kill-line-of-sight]. Every damage and kill act between
opponents takes one class from the replay's own damage record, its
equippable class and its `wall_penetration` flag; the map's table only
tests it.

| Class | Rule | The table's test |
|---|---|---|
| `gun_sight` | a gun (`equippables.equippable_kind`: the class lies under `Equippables/Guns/`), no penetration flag | the line from the shooter's eye to the hit (`impact`, else the victim's body or eye) is clear |
| `gun_wallbang` | a gun, `wall_penetration` true | `wall_penetration.Penetration` lists what lies on the line: placements, solid runs, penetration classes, any Impenetrable or unread surface |
| `gun_blocked` | a gun, no flag, and the table blocks the line | none: the replay and the table disagree (a table error, a crouched eye, a moved position); each one is listed |
| `ability` | the class lies under an agent's `Characters/` folder | none needed; `line_clear` is stored |
| `melee`, `other`, `unread` | the knife; another class (the spike); a class the build's index lacks, or an unread position | -- |

A kill takes the class of its killing hit: the damage record marked
`killed` on the same victim within 500 ms. A kill with none is `unread`.
`act` rows store every kill, every killing hit and every `gun_wallbang`
and `gun_blocked` hit; the header counts every class.

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
and a kill, sight between them, or a `gun_wallbang` or `ability` act, which
needs none (section 2.1). Proximity alone never makes one.

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
  `hits`, `opening` (the round's first kill), `kill_class` and
  `act_classes` (section 2.1).

A bout with no kill, no sight and only gun hits the replay does not mark as
penetrating is **remote damage** (`remote_damage`): the replay and the
table disagree, or the sight samples missed a glimpse. It joins no
engagement.

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

An execute is a **site attempt**, graded rather than gated: a solo entry
nobody follows is an execute of commitment 1
[domain:rounds/execute-is-a-site-attempt].

- **Commit.** An attacker commits to a site when, before the plant, he
  stands on its site callout (the volume valorant-api names `<X> Site`;
  Q7) and stays `COMMIT_DWELL_MS` (Q6), gains a contact with a defender,
  trades an act with one, or plants there. His attempt opens at his entry;
  `trigger` names what confirmed it.
- **Join.** An attacker who commits to the same site while a committed
  attacker holds it, or within `ATTEMPT_HOLD_MS` (Q6) of the last committed
  presence, joins the attempt. Later than that, he opens a new one. A round
  can hold several attempts, on one site or two.
- **Close and outcome.** `planted` at a plant on the site; `wiped` when no
  attacker lives; `cleared` when no defender lives; `timed_out` when the
  round ends with the attempt open; else `abandoned`, at the last committed
  presence: the committed are dead or gone and nobody took their place. A
  plant no attempt covers (the planter never on the site callout) opens a
  `plant` attempt of the attackers in the site's super-region.
- **Commitment.** `committed` (how many joined), `alive_at_open`, `share`,
  `join_ms` (each join after the opening), `entry_spread_ms` and `spread_m`
  (the widest pair of the committed at the last join); the outcome also
  counts `committed_dead`. `peak_ms` is the last join.

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

Per attacker alive at an attempt's peak (its last join; no `plant`
attempt) who stands outside both the attempted site's super-region and the
attackers' side (valorant-api's `Attacker Side`): his run outside the two
around the peak,
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
| `COMMIT_DWELL_MS` | 2000 | **player** (Q6) | -- |
| `ATTEMPT_HOLD_MS` | 5000 | **player** (Q6) | -- |
| killing-hit match | 500 ms | resolution | the replay logs a kill a few ms from its hit |
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
6. **Execute.** Answered in part (2026-10-05): an execute is a graded site
   attempt, and one attacker suffices
   [domain:rounds/execute-is-a-site-attempt]. Open: how long on the site
   commits an attacker who meets nobody (default 2 s), and how long a site
   may stand empty before a newcomer opens a new attempt (default 5 s)?
7. **What counts as "on site"** for an execute: the site callout alone, the
   whole super-region (lobby and main included), or the plantable zone?
   Default the site callout: the super-region fires at barrier drop. The
   site callout misses plantable ground on seven maps (section 9), and the
   plantable zone needs geometry no table holds yet (the minimap's site
   paint, or the game's plant volumes; the gameplay levels place one
   outline mesh per site [domain:rounds/bomb-site-outline], not yet
   exported). For a retake: default the super-region.
8. **Retake.** Is a plant with a defender still on site a retake?
   Default no (a contested plant).
9. **Rotation.** How long must a player hold one site, and then the other,
   for a move to count as a rotation? Default 3 s each; a stay under 1 s is
   a step over a boundary, no move. Is a Bind teleport a rotation? Default
   yes. Does a `Link` callout belong to a site? Default no.
10. **Lurk.** Who lurks: an attacker away from an attempt at its peak, or
    anyone away from the team before it? How long apart? Default the first,
    for 5 s, never counting the attackers' side.
11. **Remote damage.** Answered for kills (2026-10-05): wallbangs and
    ability kills need no sight [domain:weapons/kill-line-of-sight]. This
    version extends it to every ability or wallbang hit, which now makes a
    duel and joins engagements. Is a chip of utility on an unseen opponent
    across the map a fight? Default yes, as the kill rule implies.

## 6. Not modelled, and what each needs

- Smokes, walls and blinds cut sight; the layer's ability children carry
  each smoke's place and life, so a later version subtracts smoked
  segments. Until then contacts over-count; duels need an act and do not.
- Doors, breakables and ability walls (left out of the tables): a
  wallbang through one crosses nothing the table holds (section 9);
  posture beyond the lowered centre.
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
source, map, parameters, input stamps, act counts), then `episode`, `act`,
`contact`, `unassigned_death` and `note` rows. `reticle episodes
MATCH|SESSION`, or `--all`, builds them; `--status` says which are current;
`--out DIR` writes and reads them under another root, so a branch's
experiment never rewrites the shared store's files. `reticle plan
SESSION` names `episodes` absent or stale for a session whose kept replay
names it, downstream of `replay_layer`; doctor's EPISODES check errors on
every match whose replay layer is current and whose episodes are not.
`tools/episodes_sanity.py` writes the sanity report below.

## 9. Sanity run

`tools/episodes_sanity.py --record` over episodes-0.3.0 of the 17 parsed
replays, held-out bd7efa02 excluded before any row was read:
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#matches=17] matches, [metric:episodes/sanity/pooled~2026-10-05T22:26:19#rounds=346] rounds, [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kills=2592]
kills. The figures cite the run of 2026-10-05 22:26 by its time: a later run
of an older version records over the same series. The development matches
are b03fecd3, 60c7f1e0 and 16a475cb; the rest are unlinked replays.

**Checks.**

- Kills: 2579 lie in exactly one engagement
  ([metric:episodes/sanity/pooled~2026-10-05T22:26:19#kills_in_exactly_one_engagement=0.995]), none in two; the other 13
  are `unassigned_death` rows, every one `same_team`
  ([metric:episodes/sanity/pooled~2026-10-05T22:26:19#unassigned_share=0.005]).
- Round phases take their boundaries from the replay's own round start,
  barrier drop, plant, defuse and round end; d6928558's last round has no
  barrier drop and no live phase. Against Riot's match record, end reason
  and winner agree on 24 of 24 rounds of b03fecd3 and 28 of 28 of
  60c7f1e0. The deciding event precedes the round end by a median
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#end_lag_ms.elimination.p50=25.0] ms after an elimination (p95
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#end_lag_ms.elimination.p95=34.55] ms) and
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#end_lag_ms.defuse.p50=19.0] ms after a defuse.
- Sight: the killer saw his victim within 1 s before
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill=0.957] of kill duels, [metric:episodes/sanity/pooled~2026-10-05T22:26:19#mutual_kill_duels=0.8736]
  mutually; kills end [metric:episodes/sanity/pooled~2026-10-05T22:26:19#duel_kill_share=0.753] of duels;
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#traded_share=0.1842] of kills were traded, every trade inside one
  engagement ([metric:episodes/sanity/pooled~2026-10-05T22:26:19#same_engagement_trades=1.0]).

**Kill classes** (section 2.1). Gun kills with sight dominate; wallbangs and
ability kills are each about one kill in twenty-three, and the killer saw his
victim in the last second before most of them anyway:

| match | map (codename) | rounds | duels | engagements | trades | executes | lurks | rotations | killer saw victim |
|---|---|---|---|---|---|---|---|---|---|
| 05c76cb6 | Duality | 23 | 237 | 119 | 37 | 25 | 5 | 62 | [metric:episodes/sanity/05c76cb6~2026-10-05T22:26:19#sight_at_kill=0.9611] |
| 1256eed3 | Juliett | 18 | 170 | 99 | 24 | 18 | 21 | 23 | [metric:episodes/sanity/1256eed3~2026-10-05T22:26:19#sight_at_kill=0.9847] |
| 16a475cb | Jam | 20 | 197 | 98 | 28 | 24 | 22 | 109 | [metric:episodes/sanity/16a475cb~2026-10-05T22:26:19#sight_at_kill=0.953] |
| 18585a5d | Pitt | 21 | 216 | 96 | 37 | 22 | 12 | 44 | [metric:episodes/sanity/18585a5d~2026-10-05T22:26:19#sight_at_kill=0.9745] |
| 1a4c4618 | Duality | 24 | 220 | 131 | 20 | 28 | 6 | 78 | [metric:episodes/sanity/1a4c4618~2026-10-05T22:26:19#sight_at_kill=0.9529] |
| 2c387cb6 | Duality | 25 | 222 | 121 | 34 | 27 | 10 | 64 | [metric:episodes/sanity/2c387cb6~2026-10-05T22:26:19#sight_at_kill=0.9728] |
| 30e82ae0 | Bonsai | 15 | 139 | 72 | 15 | 14 | 8 | 33 | [metric:episodes/sanity/30e82ae0~2026-10-05T22:26:19#sight_at_kill=0.9252] |
| 493b1eca | Port | 9 | 101 | 45 | 17 | 10 | 0 | 18 | [metric:episodes/sanity/493b1eca~2026-10-05T22:26:19#sight_at_kill=0.9577] |
| 590a5d1b | Foxtrot | 23 | 207 | 113 | 33 | 27 | 27 | 38 | [metric:episodes/sanity/590a5d1b~2026-10-05T22:26:19#sight_at_kill=0.9762] |
| 60c7f1e0 | Ascent | 28 | 293 | 156 | 32 | 31 | 11 | 49 | [metric:episodes/sanity/60c7f1e0~2026-10-05T22:26:19#sight_at_kill=0.9552] |
| 6da71b0e | Foxtrot | 22 | 227 | 129 | 24 | 26 | 17 | 23 | [metric:episodes/sanity/6da71b0e~2026-10-05T22:26:19#sight_at_kill=0.9822] |
| 7498df5e | Bonsai | 16 | 166 | 82 | 20 | 16 | 6 | 43 | [metric:episodes/sanity/7498df5e~2026-10-05T22:26:19#sight_at_kill=0.9204] |
| 75111fd9 | Pitt | 24 | 251 | 127 | 30 | 26 | 13 | 74 | [metric:episodes/sanity/75111fd9~2026-10-05T22:26:19#sight_at_kill=0.9402] |
| 75a5e757 | Rook | 23 | 230 | 112 | 51 | 23 | 9 | 39 | [metric:episodes/sanity/75a5e757~2026-10-05T22:26:19#sight_at_kill=0.9508] |
| b03fecd3 | Ascent | 24 | 248 | 125 | 33 | 26 | 19 | 36 | [metric:episodes/sanity/b03fecd3~2026-10-05T22:26:19#sight_at_kill=0.9278] |
| d6928558 | Triad | 9 | 77 | 35 | 10 | 10 | 13 | 21 | [metric:episodes/sanity/d6928558~2026-10-05T22:26:19#sight_at_kill=0.9508] |
| dabcf7e5 | Rook | 22 | 224 | 120 | 30 | 29 | 8 | 55 | [metric:episodes/sanity/dabcf7e5~2026-10-05T22:26:19#sight_at_kill=0.9649] |

Pooled per round, and durations:

| kind | per round | duration p10 / p50 / p90 (s) |
|---|---|---|
| duel | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.duel=9.899] | 0.27 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.duel.p50=0.81] / 2.4 |
| remote damage | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.remote_damage=0.066] | 0.0 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.remote_damage.p50=0.0] / 0.59 |
| engagement | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.engagement=5.145] | 0.32 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.engagement.p50=1.27] / 8.24 |
| trade | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.trade=1.373] | 0.3 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.trade.p50=2.05] / 4.27 |
| execute | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.execute=1.104] | 1.25 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.execute.p50=8.53] / 18.44 |
| lurk | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.lurk=0.598] | 16.35 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.lurk.p50=33.75] / 60.05 |
| retake | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.retake=0.15] | 8.32 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.retake.p50=28.47] / 43.54 |
| contested plant | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.contested_plant=0.442] | instant |
| rotation | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.rotation=2.338] | 0.25 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.rotation.p50=9.5] / 20.8 |
| post-plant phase | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#per_round.phase_post_plant=0.595] | 8.77 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.phase_post_plant.p50=24.98] / 40.58 |
| buy phase | -- | 29.79 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.phase_buy.p50=29.85] / 44.73 |
| live phase | -- | 22.4 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.phase_live.p50=36.9] / 73.93 |
| round over | -- | 7.1 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.phase_round_over.p50=7.14] / 7.21 |
| contact | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#contacts_per_round=19.61] | 0.12 / [metric:episodes/sanity/pooled~2026-10-05T22:26:19#dur_s.contact.p50=0.69] / 2.25 |

Kills by class:

| class | kills | share | killer saw victim within 1 s |
|---|---|---|---|
| `gun_sight` | 2336 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.gun_sight=0.9058] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.gun_sight=0.9739] |
| `gun_wallbang` | 111 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.gun_wallbang=0.043] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.gun_wallbang=0.7748] |
| `ability` | 115 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.ability=0.0446] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.ability=0.887] |
| `melee` | 2 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.melee=0.0008] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.melee=1.0] |
| `gun_blocked` | 2 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.gun_blocked=0.0008] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.gun_blocked=0.5] |
| `other` | 4 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.other=0.0016] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.other=0.5] |
| `unread` | 9 | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#kill_class_share.unread=0.0035] | [metric:episodes/sanity/pooled~2026-10-05T22:26:19#sight_at_kill_by_class.unread=0.0] |

The 9 `unread` kills have no killing record within 500 ms. Five gun hits
are `gun_blocked` (of 8,371 classed gun hits; two of them killed); each
crosses a thin prop the replay does not mark as penetrated (a wooden crate, scaffold planks, a
news stand, a truck's trim, an antechamber wall): table or position errors,
listed by the sanity tool.

**What a wallbang crosses.** [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.n=762] damage records
the replay flags as penetrating, eye to hit:

- one placement on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.placements_1=0.6562], two on
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.placements_2=0.1417], three on
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.placements_3=0.0171], four or more on 0.0131;
- one solid run on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.solids_1=0.7795], two on
  [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.solids_2=0.0394], three or more on 0.0052. Two
  placements usually bound one solid: a wall's outer and inner shells are
  separate meshes (Ascent's Switchhouse exterior and interior);
- nothing the table holds on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.clear_line=0.1719]: the
  bullet went through something the table leaves out (a door, a
  breakable, an ability wall) or from a crouched eye;
- an Impenetrable surface on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.impenetrable=0.0]; an
  unread surface on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#wallbang_lines.unread=0.0039]. Classes met:
  High 453 crossings, Moderate 160, VeryHigh 43, VeryLow 3, Low 2.

So the player's "maybe multiple" holds rarely: one penetrable object stands
between shooter and victim on almost every wallbang the table can see, two
solid objects on about one in twenty-five.

**Executes as site attempts.** [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.per_round=1.104]
per round, in [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.rounds_with=0.8728] of rounds.
Commitment: one attacker on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.committed_1=0.3613] of
attempts, two on [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.committed_2=0.1832], three on
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.committed_3=0.2251], four on
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.committed_4=0.1178], five on
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.committed_5=0.1126]; median share of the living
attackers [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.share_p50=0.6]. Outcomes: planted
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.result_planted=0.5366], abandoned
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.result_abandoned=0.3377], timed out
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.result_timed_out=0.0576], wiped
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.result_wiped=0.0419], cleared
[metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.result_cleared=0.0262]; a plant no attempt covered
opened [metric:episodes/sanity/pooled~2026-10-05T22:26:19#execute_attempts.trigger_plant=0.0759]. Commitment tracks
the outcome: 85 of 138 solo attempts were abandoned and 34 planted; 70 of
88 five- and four-attacker attempts planted.

**Three examples** to check in the in-client replay. Times are the round
clock (1:40 at barrier drop) or the spike's remaining time; all three are
from 60c7f1e0 (Ascent, session c817691bcd15).

1. **Wallbang through two shells.** Round 6, 26 s on the spike: KAY/O
   (Blue) kills Omen (Red) with a Vandal through the Switchhouse wall,
   whose exterior and interior meshes bound one 25 cm solid (High).
2. **Ability kill without sight.** Round 8, 33 s on the spike: Raze
   (Blue)'s Showstopper kills Cypher (Red); no clear line at the hit, and
   Raze did not see Cypher in the last second.
3. **Solo attempt, abandoned.** Round 2, clock 1:17 (23.0 s after barrier
   drop): Cypher (Red) steps onto B alone and meets a defender; he dies by
   1:09, nobody follows within 5 s, and Red loses the round by elimination.
   An execute of commitment 1.

**Predictions** (`notes/predictions.jsonl`). EP1-EP22 (task
`replay-episodes-20261005`) scored episodes-0.1.0 to 0.2.1; their verdicts
stand in that file's outcome row. EP23-EP31 (task
`replay-episodes-2-20261005`) were written after one instrument run on
b03fecd3:

| ref | prediction | result | verdict |
|---|---|---|---|
| EP23 | kill classes: gun_sight 0.80-0.90, ability 0.06-0.12, wallbang 0.03-0.08, melee under 0.01, unread at most 0.03 | 0.906, 0.045, 0.043, 0.001, 0.004 | failed: fewer ability kills than b03fecd3 suggested |
| EP24 | killer saw victim: gun_sight 0.93+, wallbang 0.50-0.90, ability 0.60-0.90 | 0.974, 0.775, 0.887 | held |
| EP25 | wallbang lines: one placement 0.55-0.80, two 0.15-0.35, three or more at most 0.10; one solid 0.80+; no crossing at most 0.10 | 0.656, 0.142, 0.030; 0.780; 0.172 | failed: a sixth of flagged lines cross nothing the table holds |
| EP26 | Impenetrable at most 3%, unread at most 25% of wallbang lines | 0.0, 0.004 | held |
| EP27 | gun_blocked at most 2% of gun hits | 0.06% | held |
| EP28 | 1.0-1.6 executes per round; commitment 1 on 0.30-0.55; planted 0.35-0.60; abandoned 0.25-0.50 | 1.104; 0.361; 0.537; 0.338 | held |
| EP29 | an execute in 90% of rounds | 0.873 | failed |
| EP30 | 9.6-10.2 duels per round, remote damage at most 0.10 | 9.899, 0.066 | held |
| EP31 | 0.4-1.2 lurks per round | 0.598 | held |

**What the run shows.**

- Every kill classes from the replay's own records; 9 of 2592 lack a
  killing record. The table agrees with the replay's penetration flag on
  all but 5 gun hits, all at thin props.
- A wallbang crosses one penetrable object nearly always, never an
  Impenetrable surface; a sixth of the replay's penetrations cross nothing
  the table holds, which the doors and ability walls the table leaves out
  would explain, unmeasured.
- An execute is now an attempt with a grade: a third are one attacker,
  most of them abandoned, and the more attackers commit the likelier the
  plant. In the rounds with no attempt (0.13) no attacker committed to a
  site callout and no plant fell; why (early eliminations, holds that never
  hit) is unchecked.
- Rotations, untouched here, keep episodes-0.2.1's defects (Bind
  teleporters, Lotus's B Main and C Door, Corrode's labels).
- A four-round half (493b1eca) and overtime (2c387cb6, round 25) break a
  twelve-round halftime rule; the attacking team is read from spawn, so no
  episode used the rule.
