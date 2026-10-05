# Ladder sample

Status: proposed, 2026-10-04. `prototypes/ladder_fetch.py` fetches a small,
rank-stratified sample of ranked matches through HenrikDev's unofficial API.
The player approved one dry run on their own accounts, and it ran on
2026-10-04 (see "Dry run"). The crawl past the player's own matches waits for
the player's decision on the open question below.

> **Open question for the player: strangers' match histories.** The
> project's README lists "Big analytic projects" under "What is not
> allowed?", with the note "Why? Because of data privacy." It asks: "Please
> make sure that the user has given his consent to use his data." and warns
> that "Analytic services where the user haven't giving his consent are not
> supported and will be banned if found out". The player's own accounts are
> consented, and their matches are fetched. A snowball reaches the other
> players in those lobbies, who have not consented. A sample of 500 to 2000
> matches, pseudonymised and never published, is small, but whether it is a
> "big analytic project" is HenrikDev's call. The fetcher stays on the
> player's own accounts until the player decides, for example after asking
> HenrikDev through the Discord where keys are issued.

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
- "Please make sure that the user has given his consent to use his data.
  Analytic services where the user haven't giving his consent are not
  supported and will be banned if found out, same stuff for store checkers
  if they are public"
- Under "What is not allowed?", each item and its note as separate lines:
  - "Big analytic projects"
  - "Why? Because of data privacy."
  - "TOS breaking stuff"
  - "Includes showing hidden names, account checkers for selling accounts
    and other stuff that may sound illegal (please do some thinking before
    executing)"
- "As stated above, the API is developed with higher request counts in mind
  since version 4, but still not intended to be used within big projects."

From the documentation (<https://docs.henrikdev.xyz/general/rate-limiting.md>),
read 2026-10-04: "If you exceed a rate limit, the API returns `429 Too Many
Requests`"; "The `Retry-After`/`X-RateLimit-Reset` headers indicate how long
to wait before the next request"; "Starting with v4.0.0, the rate limit
counts both the call to the HenrikDev API and any Riot requests made in the
background to build the response"; "If the requested data is already cached
or stored locally, no background Riot request is needed, so only the API call
is counted." `X-RateLimit-Limit` is the "Total requests in the shortest
window", `X-RateLimit-Remaining` the "Requests remaining in that window",
and `X-RateLimit-Reset` the "Seconds until the shortest window resets". Keys
come from the dashboard (<https://docs.henrikdev.xyz/general/auth.md>).

## The key

1. Join the HenrikDev Discord (linked from the README) and open
   <https://api.henrikdev.xyz/dashboard/>.
2. Choose "API Keys", fill in "Generate New Key", and take the Basic key;
   describe the use as a personal, non-commercial research sample.
3. The player keeps the key as `HENRIK_API_KEY=...` in the repository's
   `.env`, which `.gitignore` excludes; a worktree reads the main
   checkout's. The fetcher also takes `HENRIKDEV_API_KEY` or
   `HENRIK_API_KEY` from the environment, or the key alone on one line in
   `C:\Users\grant\reticle-store\external\ladder\henrikdev\api_key`. It
   sends the key only in the `Authorization` header and never prints, logs
   or copies it.
4. Add the third account to `external\ladder\owner_seeds.json` in the store,
   as `[{"label": "C", "puuid": "..."}]`. The fetcher finds two accounts in
   the store: the recurring accounts `riot_ground_truth.identify_player`
   names, plus any the fetch kit binds in `accounts.jsonl`.

## Politeness

The quota counts units, not calls: a v4 call costs one unit plus one for each
Riot request HenrikDev makes to build the reply, so a list of uncached
matches costs several units. The limiter reads `X-RateLimit-Limit`,
`X-RateLimit-Remaining` and `X-RateLimit-Reset` on every reply. It sends a
call only when the remaining quota, less the call's predicted cost, stays at
or above half the limit, and when the units it spent in the last 60 s plus
the prediction stay within the other half. A call's cost is the drop in
`Remaining` since the previous reply in the same window, or `Limit -
Remaining` in a fresh window, which charges the call any use of the key from
elsewhere. The largest cost per match measured so far predicts the next
call, and a list is shortened until its prediction fits one minute's budget.
A prediction can fall short; the reply then shows `Remaining` under the
reserve, and the next call waits for the reset.

| Setting | Default |
| --- | --- |
| Rate | half the key's limit: at most 15 units a minute on the Basic key (30), one call per 4 s at most |
| Daily caps | 250 calls and 2500 units per UTC day |
| Total caps | 250 calls and 2500 units until raised |
| Match cap | 20 stored matches until raised |
| 429 | wait `Retry-After` or `X-RateLimit-Reset`, at least the backoff |
| 429, 5xx, network error | back off 8 s, doubling to 600 s, four retries |
| Stop | three failed requests in a row |
| A new run | waits out the minute after the last call |
| Queue | `mode=competitive` on every list; the parser keeps `queue.id == "competitive"` |
| Window | since a date (90 days before the first run) and optional season list |

The caps are command-line defaults (`--daily-cap`, `--total-cap`,
`--daily-unit-cap`, `--total-unit-cap`, `--max-matches`); only the counts
persist, in `state.json`, so a rerun resumes. Each player is listed once; a
match already stored, or held in `external/riot/` or `external/riot-pd-v1/`,
is never requested by id, and a list reply's repeats are counted, not parsed
twice. The manifest row of each call keeps its rate-limit headers, its units
and how they were found.

## Requests

One `GET /valorant/v4/by-puuid/matches/{region}/{platform}/{puuid}?mode=competitive&size=10`
returns a player's last ten competitive matches with rounds, kills and
positions, so the snowball spends one call per visited player, but that call
costs about one unit per uncached match. `start` pages deeper. The leaderboard
(`/valorant/v3/leaderboard/{region}/{platform}`) seeds the top tiers.
`/valorant/v4/match/{region}/{id}` exists for single matches; the fetcher
does not need it yet. The largest `size` the list accepts is undocumented.

## Storage

Under `<store>/external/ladder/henrikdev/v4/`: `raw/<seq>-<kind>.json.gz`
(gzip 9, written once, never overwritten), `manifest.jsonl` (endpoint,
fetched_at, status, bytes, gz_bytes, sha256, the match ids a body holds),
`state.json`, `pseudonym_salt`, `measure/last.json` (the Riot transcode),
`measure/v4.json` (the stored v4 replies), and
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
- v4 round ids count from 0, as Riot's `roundNum` does (seen in the dry
  run); its `result` strings (`Elimination`, `Defuse`) read like Riot's
  `roundResultCode`, but no captured match has both records to compare.

Both list only some players at each kill. The captured Riot records hold
[metric:ladder_fetch/measure#kill_positions=19735] kill positions for
[metric:ladder_fetch/measure#kills=3459] kills, 5.7 a kill; the dry run's v4
records hold [metric:ladder_fetch/measure_v4#kill_positions=17451] for
[metric:ladder_fetch/measure_v4#kills=3063] kills,
[metric:ladder_fetch/measure_v4#kill_positions_per_kill=5.7] a kill.

## Dry run

The player approved one dry run on their own accounts; it ran on 2026-10-04
against the two accounts the store holds (the third is not recorded), with a
budget of 20 match records. Each account got one list of 6 and then one-match
paging probes (`start` 20, 40, 80, 160, then halving) that find where its
competitive list ends.

- Calls and units: [metric:ladder_fetch/dry_run#calls=20] calls spent
  [metric:ladder_fetch/dry_run#units=39] units, every one measured from the
  headers; `X-RateLimit-Limit` read [metric:ladder_fetch/dry_run#rate_limit=30],
  and `Remaining` never fell below [metric:ladder_fetch/dry_run#min_remaining=17].
- Unit costs: a list of 6 cost [metric:ladder_fetch/dry_run#list_units_max=9]
  units; an empty page [metric:ladder_fetch/measure_v4#units_per_empty_call=1.0];
  a match record [metric:ladder_fetch/measure_v4#units_per_record=1.0] unit
  beyond that on average and [metric:ladder_fetch/measure_v4#units_per_record_max=1.33]
  at most (in a list). Some one-match probes cost one unit in all, so
  HenrikDev had those matches cached.
- Records: [metric:ladder_fetch/dry_run#records_built=19] match records
  came back; [metric:ladder_fetch/dry_run#matches_in_sample=12] fall inside
  the 90-day window and form the sample, and
  [metric:ladder_fetch/dry_run#out_of_window=7] older probe matches stay in
  raw only.
- History depth: the competitive list pages exactly
  [metric:ladder_fetch/dry_run#history_depth_a=82] matches deep for one
  account and [metric:ladder_fetch/dry_run#history_depth_b=42] for the other,
  [metric:ladder_fetch/dry_run#history_depth_sum=124] in all, reaching back
  about two years; the newest is three weeks old. Fewer fall in the 90-day
  window: the probe at `start` 20 already returned a match from March on
  both accounts. One account's captured Riot records hold 16 competitive
  matches from late August, yet its list reaches March by index 20, so the
  list may skip matches; HenrikDev's stored-matches guide warns of holes.
- Every match sits in the player's own Silver and Gold lobbies. The player's
  own history alone gives about 124 matches at that rank, past the 90-day
  window; listing it costs about one unit a match.

## Size

Measured on the dry run's v4 records:
[metric:ladder_fetch/measure_v4#raw_bytes_per_match=420660] bytes a match
uncompressed, [metric:ladder_fetch/measure_v4#gz_bytes_per_match=30368]
gzipped, [metric:ladder_fetch/measure_v4#parsed_bytes_per_match=24530] as
parquet. The earlier estimate from the captured records carried into the v4
shape ([metric:ladder_fetch/measure#gz_bytes_per_match=24551] gzipped) ran
low, and Riot's own record
([metric:ladder_fetch/measure#riot_gz_bytes_per_match=52409]) high.

`project` prints the table below for lists of 10 at 15 units a minute. Low:
nine of ten records are new, a repeat is cached and free, a record costs the
mean measured unit. High: five of ten are new, and every record costs the
largest measured
[metric:ladder_fetch/measure_v4#units_per_record_max=1.33] units. The second
high column assumes a stranger's record costs 2 units, since two lists of the
player's own matches are a small sample of cost.

| Matches | Units, measured | Hours at 15/min | Units, 2 a record | Hours | Raw gzip | Parquet |
| --- | --- | --- | --- | --- | --- | --- |
| 500 | [metric:ladder_fetch/project_v4#units_lo_500=556] to [metric:ladder_fetch/project_v4#units_hi_500=1433] | [metric:ladder_fetch/project_v4#hours_lo_500=0.6] to [metric:ladder_fetch/project_v4#hours_hi_500=1.6] | up to [metric:ladder_fetch/project_v4#units_hi_500_u2=2100] | up to [metric:ladder_fetch/project_v4#hours_hi_500_u2=2.3] | [metric:ladder_fetch/project_v4#gz_MB_500=15.2] MB | [metric:ladder_fetch/project_v4#parquet_MB_500=12.3] MB |
| 1000 | [metric:ladder_fetch/project_v4#units_lo_1000=1111] to [metric:ladder_fetch/project_v4#units_hi_1000=2867] | [metric:ladder_fetch/project_v4#hours_lo_1000=1.2] to [metric:ladder_fetch/project_v4#hours_hi_1000=3.2] | up to [metric:ladder_fetch/project_v4#units_hi_1000_u2=4200] | up to [metric:ladder_fetch/project_v4#hours_hi_1000_u2=4.7] | [metric:ladder_fetch/project_v4#gz_MB_1000=30.4] MB | [metric:ladder_fetch/project_v4#parquet_MB_1000=24.5] MB |
| 2000 | [metric:ladder_fetch/project_v4#units_lo_2000=2222] to [metric:ladder_fetch/project_v4#units_hi_2000=5733] | [metric:ladder_fetch/project_v4#hours_lo_2000=2.5] to [metric:ladder_fetch/project_v4#hours_hi_2000=6.4] | up to [metric:ladder_fetch/project_v4#units_hi_2000_u2=8400] | up to [metric:ladder_fetch/project_v4#hours_hi_2000_u2=9.3] | [metric:ladder_fetch/project_v4#gz_MB_2000=60.7] MB | [metric:ladder_fetch/project_v4#parquet_MB_2000=49.1] MB |

At the default 2500 units a day, 2000 matches take one to four days. The
new-record shares are guesses until a crawl runs past the player's accounts.

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
at most 20 match records, 24 calls and 120 units), `crawl`, `parse`,
`measure-riot`, `measure-v4 [--record]` and `project [--units-per-record U]`.

## Not done

- No crawl past the player's own accounts: it waits for the player's
  decision on the open question above.
- The third account is not in the store, so the dry run covered two.
- The player's full own history (about 124 matches) is not fetched; the dry
  run's 20-record budget stopped it.
- No Counter-Strike data; a CS baseline needs its own source and terms.
