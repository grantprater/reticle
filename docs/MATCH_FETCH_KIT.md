# Match fetch kit

Status: live, 2026-10-04. The player runs `prototypes/riot_match_fetch.py`
once per account to save the match records in the three accounts' histories
that no capture covers. No agent runs it; no agent contacts Riot.

## Terms of Service exposure

Read this before running the kit.

What the kit does that the texts below reach:

- It reads the Riot client's lockfile and asks the running client for the
  logged-in account's tokens.
- It calls Riot's **undocumented PD endpoints** (`pd.<shard>.a.pvp.net`),
  which Riot does not offer to third parties.
- It presents itself to them as the game client: the game's build string in
  `X-Riot-ClientVersion`, a client platform in `X-Riot-ClientPlatform`, and
  the client's own tokens. Its User-Agent names the kit.

The texts, quoted and dated in `docs/WIN_PROBABILITY_RESEARCH.md` section 2:

- **Terms of Service §7.1** (modified 2024-12-01) bars unauthorised programs
  that "intercept, emulate" or read memory, access to non-public areas, and
  circumventing technological measures. Sending the client's headers and
  tokens from another program is emulation in the plainest reading; the PD
  endpoints are a non-public area.
- **Terms of Service §3.1**, the licence (the research cites it as §3),
  licenses the services for
  "individual, non-commercial, entertainment purposes only" and bars reverse
  engineering. The kit is personal and non-commercial; whether reading the
  client's lockfile and tokens counts as reverse engineering is not read here.
- **General developer policy** (updated 2025-05-29): "Products should use
  supported services from Riot Games for data ingestion". The PD endpoints
  are not a supported service.
- **VALORANT developer policy** lists as unapproved "Apps that are not public
  and are designed for personal use only", and says "Personal Key
  Applications are currently not supported". The kit is exactly a private,
  personal-use app, so no registration route covers it.
- **Third Party Applications article** (updated 2025-02-10): for software
  Riot disallows, "continuing to use it may still result in the loss of your
  account."

What the kit does not change: it reads only the player's own match records,
after the matches, with VALORANT closed, at one PD request per 2.5 seconds.
That lowers the load and has no in-game effect; it does not make the
endpoints supported or the emulation authorised. The exposure falls on each
account the kit runs under. The player approved fetching the records of
these three accounts on 2026-10-04 ("8. Yes, they are mine"); the player
runs the kit, and no agent contacts Riot.

The 22 records already in `external/riot/` were fetched on 2026-10-02 (each
file's `probe.fetched_at`) by a probe that is not in this repository. Its
documented parts match the kit: the PD endpoints, the build string in
`X-Riot-ClientVersion` and a User-Agent naming the tool
(`EXTERNAL_GROUND_TRUTH.md`). How it got its tokens, and which other headers
it sent, is unrecorded.

A shared or distributed Reticle could not rely on this route. The official
route is VAL-MATCH-V1 with a production key, which needs a public,
registered, RSO opt-in product.

## Before the first account

1. Close VALORANT. Start the Riot client and log in to one account.
2. If VALORANT was patched since it last ran, launch it to the main menu once,
   then close it: the kit reads the build string and the shard from
   `%LOCALAPPDATA%\VALORANT\Saved\Logs\ShooterGame.log`, which each launch
   rewrites.
3. From the repository root, check the local files. This sends nothing; it
   reads the lockfile, the game log, the store and the local process table:

   ```powershell
   .\.venv\Scripts\python.exe prototypes\riot_match_fetch.py --account A --check
   ```

   It prints the build string, the shard, how many records the store holds
   (22 on 2026-10-04) and whether the lockfile's Riot client process is
   running. "not running ... a stale lockfile" means the client is closed:
   start it and log in before a fetch.

## Each account

Choose a label per account and keep it: `A`, `B` and `C` serve. The kit binds
a label to the account's PUUID on its first full run and stops if the label
later meets another account, or the account another label. That catches a
forgotten account switch.

For each of the three accounts, in turn:

1. Log the Riot client in to the account (VALORANT stays closed).
2. Preview. This asks the local client for the account's tokens, then lists
   the history from Riot, one PD request per 20 matches (three for a
   47-match history), and prints each match the kit would fetch, oldest
   first. It writes nothing:

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
- **`404` for a match**: logged and skipped; the record is gone. Later runs
  skip it too; `--retry-missing` asks again.
- **"could not reach"**: a refused connection, DNS failure or timeout. For
  the Riot client, start it and log in; otherwise check the network. Rerun;
  it resumes.
- **"Riot client not running"**: the lockfile is stale. Start the client and
  log in.
- **A redirect (3xx)**: the kit follows none, so the tokens went nowhere
  else. Stop and report it; do not work around it.
- **"history reply has an unexpected shape"**: the history page differs from
  the unofficial docs the kit was written from. The page is kept in
  `history/`; stop and report it.
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
