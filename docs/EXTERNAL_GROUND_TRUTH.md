# External ground truth

Status: proposed, 2026-10-02. A survey of sources outside the capture that
record what happened in a match. None is wired; nothing here is a domain fact
until an alignment confirms it.

## Why

Every channel Reticle checks today is read from the same pixels. An outside
record of the match would be an independent witness: it can score killfeed
timing, the roster, round boundaries, and minimap positions and facing at kill
instants without resting on any reader's output.

## Sources

**Riot's official match API (VAL-MATCH-V1).** It needs a production key;
Riot offers no personal key for VALORANT.

**The Riot client's own endpoints.** The client's PD endpoints, documented
unofficially at valapidocs.techchrism.me, serve
`match-details/v1/matches/{matchID}`. Per kill it carries `gameTime`,
`roundTime`, `victimLocation`, `playerLocations` with `viewRadians`, and
`finishingDamage`; per round, plant and defuse times and locations. Positions
exist only at kills, plants and defuses, never continuously.

A read-only probe of the player's own match history
(`match-history/v1/history/{puuid}`) first returned HTTP 403. The request
caused it, not a lockdown: the PD API answered once the client-version header
carried the game's own build string, read from the `CI server version:` line
of `%LOCALAPPDATA%\VALORANT\Saved\Logs\ShooterGame.log` (form
`release-13.06-shipping-18-5590001`), and the request sent a non-default
User-Agent naming the tool. A build hash from the local product session was
rejected. The probe is not in this repository.

Three accounts' histories were read. The first held 18 matches, 2026-09-13 to
2026-10-01 (Total 18); the second 47, 2026-09-03 to 2026-09-11 (Total 47). On
both the oldest match was about 30 days old, which suggested a 30-day
retention window. The third account falsified it: Total 33, 2026-08-23 to
2026-09-12, oldest 40 days, with a match ID for every one of the 18 August
match captures (0f08b3dc3777 through c62c2b06bcfb). The history returns at
least 40 days, possibly an account's whole history, perhaps capped by count;
the earlier spans were each account's play. Retention is unknown, so pull each
new capture's record promptly.

All 22 match captures have their match-details record saved in the store
under `external/riot/` (a store path, not the repository): 22 files,
[metric:riot_economy/team_rounds#kills=3459] kill events in all, [metric:riot_economy/team_rounds#spike_kills=12] of them spike deaths (an earlier count here,
3,532, does not reproduce). [metric:riot_economy/team_rounds#competitive_matches=20] are competitive and
[metric:riot_economy/team_rounds#unrated_matches=2] unrated (0f08b3dc3777 and b3b9defb6fd7). Each file names its session in `probe.session_id`; the store is
the index, and match IDs stay out of this repository.

4f207c0c4e39's record, for one, is Split (`/Game/Maps/Bonsai/Bonsai`), 10
players, 22 rounds, 182 kills. Each kill carries `gameTime`, `roundTime`, `round`,
`killer`, `victim`, `assistants`, `finishingDamage`, `victimLocation` and
`playerLocations` (`subject`, `viewRadians`, `location`); each round carries
plant and defuse round times, sites, locations and player locations;
`matchInfo` carries `gameStartMillis` and `gameLengthMillis`. The first kill's
`roundTime` is 1693 ms, so `roundTime` probably counts from the barrier drop,
not the buy phase; unconfirmed until aligned.

**Overwolf game events.** Live only: `kill_feed`, roster, scoreboard (alive,
ult points), `round_phase`, and the player's own health and abilities. No
positions and no in-round time; `spike_planted` was removed on 2025-01-30.

**In-game Replays.** They are local files: 15 `.vrf` files sit in
`%LOCALAPPDATA%\VALORANT\Saved\Demos` (counted 2026-10-04). They are
readable: the payloads are compressed, not encrypted, and uncompressed event
chunks carry deaths, plants, defuses and round starts. In b03fecd3 the
replay's 180 deaths pair one to one, in time order, with Riot's 180 kills. The
evidence is the store's `notes/predictions.jsonl` outcome rows for
`replay-vrf-probe-20261004` and `replay-vrf-verify-20261004`; the format's
facts belong in `domain/*.toml`.

**HenrikDev's unofficial API.** It mirrors Riot's match schema. Whether it
still serves the corpus's past matches is unconfirmed.

## Coordinates

valorant-api.com's map records give `xMultiplier`, `yMultiplier`,
`xScalarToAdd` and `yScalarToAdd`, which carry game coordinates to minimap
fractions. Whether the axes swap is unconfirmed; check it against one kill
location the minimap reader already places.

## Use

Treat a match-details record as one more channel, gated and scored like any
other:

- killfeed timing: each kill's `gameTime` against the stored entry's onset;
- roster: the match's ten agents and sides against the lineup reader;
- round boundaries: round count, plant and defuse times against `rounds`;
- positions and facing at kill instants: `playerLocations` against the
  minimap tracks and teardrop facings at that frame;
- credits: every round's `playerEconomies` against `economy.EconomyTracker`,
  replayed by `prototypes/riot_economy.py`; the rules it measured are domain
  facts [domain:rounds/credit-ledger-rules].

Store disagreements beside agreements. The record is evidence about the match,
never a reader's prior: a result it shaped declares `rests_on`.

The records label killfeed portraits offline in
[KILLFEED_PORTRAIT_SEPARABILITY.md](KILLFEED_PORTRAIT_SEPARABILITY.md).

## Chamber's ultimate count

A property of Riot's records, not a game fact: a player's
`stats.abilityCasts.ultimateCasts` undercounts Chamber's Tour De Force equips.
The game spends the ultimate on the equip
[domain:abilities/chamber-tour-de-force-equip-spends-ult], his allies hear its
line then [domain:abilities/chamber-tour-de-force-ally-line-at-equip], and an
equip does not carry into the next round
[domain:abilities/chamber-tour-de-force-not-kept-next-round], so each round
with a Tour De Force kill holds an equip. Riot's count never exceeds those
rounds and falls below them for most Chamber players; it records some equips,
not none.

A recount of the raw Riot files, per Chamber player, as (Riot count, Tour De
Force kill rounds): five players at 0 with at least one such round; three at
(1, 1), `bfad2778a372`, `c40d950031bb` and `59c70f1ef720`; two at (1, 2),
`e37fdeca944f` and `223d636bf8d2`; one at (2, 4), `a1a995e6b19b`.

Evidence, `prototypes/riot_ground_truth.py` (riot-truth-0.5.1) over the 21
scored matches: Riot counts
[metric:riot_truth/ult#chamber_line_riot_casts=7] Chamber ults for the
[metric:riot_truth/ult#chamber_line_players=12] Chamber players, where the
store holds [metric:riot_truth/ult#chamber_line_stored=27] Chamber lines.
Riot's own kills contradict its count: its count falls below that player's
Tour De Force kill rounds for
[metric:riot_truth/ult#chamber_tdf_riot_below_tdf_rounds=8] players, and is
zero for [metric:riot_truth/ult#chamber_tdf_riot_zero_with_tdf_kill=5] who
killed with Tour De Force. Of the
[metric:riot_truth/ult#chamber_line_tdf_rounds=16] rounds with a Tour De Force
kill, [metric:riot_truth/ult#chamber_line_tdf_rounds_held=15] hold a stored
Chamber line from that side. All of the ult pool's
[metric:riot_truth/ult#excess_rows=20] excess rows are Chamber's: without him
the stored rows hold [metric:riot_truth/ult#apart_excess_rows=0].

The older `chamber_tdf` count score compares each Chamber player's line count
with a lower bound, max(Riot's count, his Tour De Force kill rounds). Its
count recall
[metric:riot_truth/ult#chamber_tdf_count_recall_vs_lower_bound=1.0] says
every player holds at least that many lines, not that every kill round holds
one; the round that holds none belongs to a player with lines in other
rounds. Its [metric:riot_truth/ult#chamber_tdf_count_above_lower_bound=11]
lines above the bound are one fewer than the
[metric:riot_truth/ult#chamber_line_lines_unverifiable=12] lines outside a
kill round: the count lets one line outside a kill round stand in for the
kill round that holds none. No figure there is false; the per-round figures
are `chamber_line`'s.

So the scorer scores Chamber apart: the per-match count without him, and his
lines against Tour De Force kill rounds, counting a line outside one
unverifiable, not false. Whether Riot's count holds other uncounted
activations is unknown.

## Next step

Align each record to its capture by fitting one offset from the
record's kill times to the stored killfeed reads. Then score the stored deaths
and killfeed entries against its kills, and the minimap ally positions and
facings against `playerLocations` at each kill through valorant-api.com's map
transform. 4f207c0c4e39 is the backlog's KAY/O capture and has no death stream
and no lineup player, so its record is its only independent witness.
