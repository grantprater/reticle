# Ability cast-line voice assets

Date: 2026-09-27. Status: harvested. Prototype:
[`prototypes/voice_line_harvest.py`](../prototypes/voice_line_harvest.py).
Outputs: the store's `reference/assets/voicelines/casts/` (one MP3 per line
take) and `reference/assets/voicelines/casts/index.json` (one record per
file). Nothing here is committed to the repository; the store is local and
`reticle/` does not import this prototype.

## What this fetches

Each agent's wiki Quotes page (`<Agent>/Quotes`, `KAYO/Quotes` for KAY/O)
lists an "Abilities" section with one heading per ability and, under it, the
lines the agent speaks casting, activating, deactivating, or recalling it,
plus the ally- and enemy-heard variants of an ultimate cast. The harvest
downloads the audio for exactly those lines. It leaves reactions to an
ability's own outcome nested under the same heading (a kill, a kill assist,
a deployable destroyed, a trap detaining someone) and every top-level
match-start, round, ping, radio, and unused/removed-lines section beside
"Abilities" -- none of that is casting, equipping, or ending an ability, and
none of it is downloaded. A subpage some ultimates push their real content
to (`<Agent>/Quotes/<Subpage>`, reached by a "Main article:" link) is
followed and parsed the same way; a line already recorded by its source URL
is never re-fetched, so a second run only pulls what a first run missed.

Direct `https://valorant.fandom.com/wiki/<page>` fetches return HTTP 403 from
this network; the MediaWiki parse API on the same host
(`api.php?action=parse&prop=text`) answers normally and serves the same
rendered HTML, so every page fetch goes through it. Audio downloads are
unaffected and hit the CDN directly. One request per second throughout, with
backoff and retry on 429 and 5xx.

## Coverage

29 of 29 agents have at least one ability-use line. 115 abilities carry
audio; the count below is per agent, and the three columns are the number of
DISTINCT lines an ability has (by text, not by audio-file count -- a wiki
line often has two recorded takes of identical text, which is one line, two
files).

| Agent | Abilities covered | Min lines | Median | Max |
|---|---|---|---|---|
| Reyna | 4 | 1 | 1.5 | 4 |
| Clove | 4 | 2 | 2.0 | 4 |
| Sova | 4 | 2 | 2.0 | 4 |
| Phoenix | 4 | 1 | 1.5 | 3 |
| Miks | 4 | 2 | 2.0 | 3 |
| Jett | 4 | 1 | 1.0 | 3 |
| Sage | 4 | 1 | 2.0 | 3 |
| Omen | 4 | 1 | 2.0 | 2 |
| Skye | 4 | 1 | 1.5 | 4 |
| Raze | 4 | 1 | 1.5 | 3 |
| Breach | 4 | 2 | 2.0 | 2 |
| Chamber | 3 | 2 | 3.0 | 3 |
| Waylay | 4 | 1 | 2.5 | 9 |
| Neon | 4 | 3 | 3.0 | 3 |
| Yoru | 4 | 1 | 1.5 | 6 |
| Deadlock | 4 | 2 | 2.5 | 4 |
| Gekko | 4 | 3 | 5.0 | 8 |
| Fade | 4 | 1 | 2.0 | 2 |
| Iso | 4 | 2 | 2.0 | 2 |
| Killjoy | 4 | 2 | 2.5 | 4 |
| Cypher | 4 | 1 | 2.5 | 4 |
| KAY/O | 4 | 2 | 2.5 | 4 |
| Tejo | 4 | 2 | 2.0 | 3 |
| Astra | 5 | 1 | 6.0 | 7 |
| Brimstone | 4 | 1 | 2.0 | 3 |
| Harbor | 4 | 2 | 2.0 | 4 |
| Veto | 4 | 2 | 3.0 | 4 |
| Viper | 3 | 1 | 2.0 | 4 |
| Vyse | 4 | 2 | 6.0 | 6 |

Totals: 528 files, 18,983,702 bytes, 115 abilities with audio, 93 of them
with more than one distinct cast line and 22 with exactly one.

## No audio

- **Chamber -- Headhunter.** The wiki lists only a "Kill" line for this
  ability; it has no cast/equip line to fetch.
- **Viper -- Fuel.** A passive resource gauge, not a cast ability; its two
  wiki sections are "Out of fuel" and "Consumption shut down by Suppression",
  both reactions, not a cast line.

Every other ability in the 29-agent roster has at least one cast-line file.

## Rerun

```
cd reticle-worktrees/voice-line-harvest
PYTHONPATH=. C:/Users/grant/reticle/.venv/Scripts/python.exe prototypes/voice_line_harvest.py harvest
PYTHONPATH=. C:/Users/grant/reticle/.venv/Scripts/python.exe prototypes/voice_line_harvest.py report
```

`--agents A,B` restricts a run to a comma-separated subset (wiki spelling,
e.g. `KAY/O`); `--dry-run` lists what would be fetched without downloading.
A rerun only pulls lines missing from `index.json` -- the wiki adding a line
to an existing ability is the one case it will fetch again under the same
ability/section, since only the source URL is deduplicated.

## What the counts say

The wiki lists more than one distinct cast line for 60 of the 81 abilities
with a cast section, median 2 and up to 7 [domain:abilities/cast-lines-vary],
so a template set for an ability holds every listed line and a match on any
of them names the ability.
