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
under `external/riot/` (a store path, not the repository): 22 files, 3,532
kills in all. Each file names its session in `probe.session_id`; the store is
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

**In-game replays.** Wiped each patch; they cannot be exported.

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
  minimap tracks and teardrop facings at that frame.

Store disagreements beside agreements. The record is evidence about the match,
never a reader's prior: a result it shaped declares `rests_on`.

The records label killfeed portraits offline in
[KILLFEED_PORTRAIT_SEPARABILITY.md](KILLFEED_PORTRAIT_SEPARABILITY.md).

## Next step

Align each record to its capture by fitting one offset from the
record's kill times to the stored killfeed reads. Then score the stored deaths
and killfeed entries against its kills, and the minimap ally positions and
facings against `playerLocations` at each kill through valorant-api.com's map
transform. 4f207c0c4e39 is the backlog's KAY/O capture and has no death stream
and no lineup player, so its record is its only independent witness.
