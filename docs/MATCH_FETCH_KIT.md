# Match fetch kit

Status: live, 2026-10-04. The player runs `prototypes/riot_match_fetch.py`
once per account to save the match records in the three accounts' histories
that no capture covers. No agent runs it; no agent contacts Riot.

## Terms of Service exposure

Read this before running the kit.

- The kit reads the Riot client's lockfile, asks the running client for the
  logged-in account's tokens, and calls Riot's **undocumented PD endpoints**
  (`pd.<shard>.a.pvp.net`) with the game's build string in the
  `X-Riot-ClientVersion` header. Riot does not offer these endpoints to third
  parties.
- Riot's developer policy says "Products should use supported services from
  Riot Games for data ingestion". The Terms of Service (§7.1, modified
  2024-12-01) bar unauthorised programs and access to non-public areas of
  Riot's services. Riot's third-party article names "loss of your account" as
  the penalty for software it disallows. The sources and quotes are in
  `docs/WIN_PROBABILITY_RESEARCH.md` section 2 (branch
  `winprob-research-20261004`).
- The kit reads only the player's own match records, after the matches,
  with the game closed, at one request per 2.5 seconds. That lowers the load
  and leaves no in-game effect; it does not make the endpoints supported. The
  exposure is the account's; the player approved the fetch for these three
  accounts on 2026-10-04.
- The 22 records already in the store came the same way on 2026-10-02.
- A shared or distributed Reticle could not rely on this route. The official
  route is VAL-MATCH-V1 with a production key, which needs a public,
  registered, RSO opt-in product.

## Before the first account

1. Close VALORANT. Start the Riot client and log in to one account.
2. If VALORANT was patched since it last ran, launch it to the main menu once,
   then close it: the kit reads the build string and the shard from
   `%LOCALAPPDATA%\VALORANT\Saved\Logs\ShooterGame.log`, which each launch
   rewrites.
3. From the repository root, check the local files. This contacts nothing:

   ```powershell
   .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A --check
   ```

   It prints the build string, the shard and how many records the store holds
   (22 on 2026-10-04).

## Each account

Choose a label per account and keep it: `A`, `B` and `C` serve. The kit binds
a label to the account's PUUID on its first full run and stops if the label
later meets another account, or the account another label. That catches a
forgotten account switch.

For each of the three accounts, in turn:

1. Log the Riot client in to the account (VALORANT stays closed).
2. Preview. This lists the history from Riot and prints each match the kit
   would fetch, oldest first; it writes nothing:

   ```powershell
   .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A --dry-run
   ```

3. Fetch:

   ```powershell
   .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A
   ```

   About 50 matches take about two minutes. Each saved match prints its date.
4. Log out, log in to the next account, and repeat with `--account B`, then
   `--account C`.

## When it stops

- **Interrupted, or `429`**: rerun the same command. It skips every record
  already saved and never overwrites a file.
- **`401` or `403`**: the token expired or the build string is stale. Launch
  VALORANT to the menu, close it, and rerun.
- **`404` for a match**: logged and skipped; the record is gone.
- **"label is bound to another account"**: the client is logged in to a
  different account than the label names. Switch accounts or labels.
- **Several shards**: pass `--shard na` (or the account's region).

## What it writes

Under `<store>/external/riot-pd-v1/`: each record's body byte for byte in
`raw/`, a provenance sidecar in `provenance/` (label, PUUID, fetch time,
endpoint, status, response headers and their `Date`, SHA-256, build string,
shard; never a token), the raw history pages in `history/`, and the
append-only `accounts.jsonl` and `fetch_log.jsonl`. The script's docstring
has the details.

The new records are raw, not wrapped as `{"probe", "match"}` like the 22 in
`external/riot/`, and have no capture; `riot_ground_truth.py` does not read
them yet. Predictions F1 to F4 for the run are in the store's
`notes/predictions.jsonl` (task `match-fetch-kit-20261004`).
