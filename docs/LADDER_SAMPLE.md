# Ladder sample

Status: proposed, 2026-10-04. `prototypes/ladder_fetch.py` fetches a small,
rank-stratified sample of ranked matches through HenrikDev's unofficial API.
It is built and tested on fixtures. It has fetched nothing: no API key
exists, and the crawl waits for the player's approval.

## Use

The records fit win-probability and coaching baselines and priors, and show
what changes up the ladder. They never feed a reader, a reader's threshold,
or anything shown during play. A match that evaluates a fitted model stays
out of its fit: the parsed `matches` table marks the player's captured
matches (`captured`) and a fixed one-in-five hash split (`holdout`), and
`holdout` includes every captured match.

## Source and terms

HenrikDev's API (`https://api.henrikdev.xyz`) relays Riot's match records. It
is not Riot's: "This API isn't endorsed by Riot Games and doesn't reflect the
views or opinions of Riot Games." Unlike the
[match fetch kit](MATCH_FETCH_KIT.md), it uses no Riot client token and no
client emulation.

Quoted from the project's README
(<https://github.com/Henrik-3/unofficial-valorant-api>), read 2026-10-04:

- "All rate limits are the same for every endpoint, so in general you have
  90 requests every minute if you use an "Advanced" API Key, if not it will
  be 30 requests every minute with the "Basic" Key."
- "You can get the "Basic" Key instantly without waiting time or apply for
  an "Enhanced" key".
- Not allowed: "Big analytic projects - Why? Because of data privacy." and
  "TOS breaking stuff - Includes showing hidden names, account checkers for
  selling accounts and other stuff that may sound illegal".
- "Please make sure that the user has given his consent to use his data."

From the documentation (<https://docs.henrikdev.xyz/general/rate-limiting.md>):
"If you exceed a rate limit, the API returns `429 Too Many Requests`", and
"The `Retry-After`/`X-RateLimit-Reset` headers indicate how long to wait
before the next request." Keys come from the dashboard
(<https://docs.henrikdev.xyz/general/auth.md>).

**Open question for the player.** The player's own three accounts are
consented. A snowball reaches strangers, who have not consented, and the
README's first refusal names data privacy. A sample of 500 to 2000 matches,
pseudonymised and never published, is small, but "big analytic project" is
the API owner's call. Ask HenrikDev, through the Discord where keys are
issued, before the crawl goes past the player's own matches.

## The key

1. Join the HenrikDev Discord (linked from the README) and open
   <https://api.henrikdev.xyz/dashboard/>.
2. Choose "API Keys", fill in "Generate New Key", and take the Basic key;
   describe the use as a personal, non-commercial research sample.
3. Save the key, alone on one line, in
   `C:\Users\grant\reticle-store\external\ladder\henrikdev\api_key`, or set
   `HENRIKDEV_API_KEY`. The fetcher sends it only in the `Authorization`
   header and never prints, logs or copies it.
4. Add the third account to `external\ladder\owner_seeds.json` in the store,
   as `[{"label": "C", "puuid": "..."}]`. The fetcher already finds two
   accounts in the store: the recurring accounts `riot_ground_truth.identify_player`
   names, plus any the fetch kit binds in `accounts.jsonl`.

## Politeness

| Setting | Default |
| --- | --- |
| Rate | half the documented limit: 15 a minute on a Basic key, one request per 4 s |
| Daily cap | 250 requests per UTC day |
| Total cap | 250 requests until raised |
| Match cap | 20 stored matches until raised |
| 429 | wait `Retry-After` or `X-RateLimit-Reset`, at least the backoff |
| 429, 5xx, network error | back off 8 s, doubling to 600 s, four retries |
| Stop | three failed requests in a row |
| `X-RateLimit-Remaining: 0` | pause until the reset |
| Queue | `mode=competitive` on every list; the parser keeps `queue.id == "competitive"` |
| Window | since a date (90 days before the first run) and optional season list |

The caps live in the command line, and the counts in `state.json`, so a rerun
resumes. Each player is listed once; a match already stored, or held in
`external/riot/` or `external/riot-pd-v1/`, is never requested by id, and a
list reply's repeats are counted, not parsed twice.

## Requests

One `GET /valorant/v4/by-puuid/matches/{region}/{platform}/{puuid}?mode=competitive&size=10`
returns a player's last ten competitive matches with rounds, kills and
positions, so the snowball spends one request per visited player. The
leaderboard (`/valorant/v3/leaderboard/{region}/{platform}`) seeds the top
tiers. `/valorant/v4/match/{region}/{id}` exists for single matches; the
fetcher does not need it yet. The largest `size` the list accepts is
undocumented.

## Storage

Under `<store>/external/ladder/henrikdev/v4/`: `raw/<seq>-<kind>.json.gz`
(gzip 9, written once, never overwritten), `manifest.jsonl` (endpoint,
fetched_at, status, bytes, gz_bytes, sha256, the match ids a body holds),
`state.json`, `pseudonym_salt`, `measure/last.json`, and
`parsed/ladder-parse-0.1.0/*.parquet` (zstd), rebuilt from raw.

## Schema

Six tables. Every PUUID becomes a keyed BLAKE2b pseudonym; names and tags are
dropped; party ids are pseudonymised.

- `matches`: map, version, season, queue, start, length, rounds, winning
  team, `stratum` (the lower-median ranked player's), `has_owner`,
  `captured`, `holdout`.
- `players`: team, party, agent, tier id and name at match time, stratum,
  account level, score, kills, deaths, assists, AFK rounds.
- `rounds`: winner, result, ceremony, plant time, site, location and
  planter, defuse time, location and defuser.
- `economy`, per round per player: loadout value, remaining, spent (Riot
  only), weapon, armor, score, kills, AFK and penalty flags.
- `kills`: round, time in round and match, killer, victim and their teams,
  assistants, weapon id, name and type, secondary fire, victim location.
- `positions`: every player location listed at a kill, plant or defuse, with
  view angle.

HenrikDev's v4 shape differs from Riot's record, and `riot_to_v4` absorbs the
differences so the captured records parse through the same code:

- every player reference is an object `{puuid, name, tag, team}`, not a bare
  subject id;
- each player carries `tier {id, name}`; Riot carries only
  `competitiveTier`, so captured matches have no stratum;
- per-round economy has no `spent` in the v4 schema;
- the kill weapon is `weapon {id, name, type}`, not `finishingDamage`;
- times are `time_in_round_in_ms` and `time_in_match_in_ms`, not
  `roundTime` and `gameTime`; the start is ISO `started_at`;
- whether v4 round ids count from 0, as Riot's `roundNum` does, and whether
  its `result` strings equal Riot's `roundResultCode`, are unconfirmed.

Riot lists only some players at each kill: the captured records hold
[metric:ladder_fetch/measure#kill_positions=19735] kill positions for
[metric:ladder_fetch/measure#kills=3459] kills, 5.7 a kill, not ten.

## Size

Measured on the 22 captured records carried into the v4 shape (no key, so no
real v4 body yet): [metric:ladder_fetch/measure#raw_bytes_per_match=294877]
bytes a match uncompressed, [metric:ladder_fetch/measure#gz_bytes_per_match=24551]
gzipped, [metric:ladder_fetch/measure#parsed_bytes_per_match=22916] as
parquet. The transcode omits fields v4 carries, so Riot's own record,
[metric:ladder_fetch/measure#riot_gz_bytes_per_match=52409] bytes gzipped,
serves as the upper bracket. `project` prints the table below.

| Matches | Requests | Minutes at 15/min | Days at 250/day | Raw gzip | Parquet |
| --- | --- | --- | --- | --- | --- |
| 500 | 75 to 500 | 5 to 33 | 1 to 2 | 12 to 26 MB | 11 MB |
| 1000 | 150 to 1000 | 10 to 67 | 1 to 4 | 25 to 52 MB | 23 MB |
| 2000 | 300 to 2000 | 20 to 133 | 2 to 8 | 49 to 105 MB | 46 MB |

The low bracket assumes a list yields about seven new in-window matches; the
high one, one request per match. The first real lists settle it.

## Strata

The snowball from the player's matches stays near their rank, because a
lobby is matched by rank. The fetcher records each player's tier at match
time and gives each match the stratum of its lower-median ranked player. It
lists next the frontier player nearest the stratum furthest below its quota,
so the sample drifts outward one lobby at a time; leaderboard players seed
Immortal and Radiant. Proposed shares:

| Iron | Bronze | Silver | Gold | Platinum | Diamond | Ascendant | Immortal | Radiant |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 6% | 10% | 13% | 14% | 14% | 13% | 12% | 12% | 6% |

At 1000 matches that is 60, 100, 130, 140, 140, 130, 120, 120 and 60. The
shares are flatter than the ladder's population so the ends hold enough
matches to compare. Radiant lobbies are rare; if the leaderboard's players
yield too few, merge Immortal and Radiant.

## Commands

`prototypes/ladder_fetch.py` lists them in its docstring: `status`, `window`,
`seed --owners`, `seed --leaderboard`, `dry-run` (the player's accounts only,
at most 20 matches and six requests), `crawl`, `parse`, `measure-riot` and
`project`.

## Not done

- No request has been sent; no key exists.
- No crawl beyond the dry run; raising the caps needs the player's approval.
- No Counter-Strike data; a CS baseline needs its own source and terms.
