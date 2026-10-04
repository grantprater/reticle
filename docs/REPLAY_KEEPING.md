# Keeping each match's replay

Status: live, 2026-10-04. A protocol for the player and for the agents that
parse what the player keeps. The replay is evaluation truth only: no reader
reads it, no prior rests on it, nothing shows it during play.

## Why

A replay holds every ability the server spawned: where each projectile,
smoke, wall and deployable appeared, when it opened and closed, and which
player cast it [domain:replay/vrf-ability-actors]; every cast with its slot
and time [domain:replay/vrf-cast-records]; every ult
[domain:replay/vrf-ult-active]; and every planted spike
[domain:replay/vrf-planted-spike-actor]. On the one match kept with both its
replay and its capture, that truth scored the player's Recon Bolt rings
within [metric:replay_abilities/score#rb_err_px_median=0.96] px
[domain:replay/vrf-sova-recon-bolt-actors] and paired
[metric:replay_abilities/score#ult_paired_same_label=28] of the stored ult
casts by agent and side. Every preserved replay holds hundreds of ability
actors, but only one of the fifteen has a capture
[domain:replay/vrf-ability-truth-per-replay]. Each new match kept with both
brings full truth for every ability in it.

## What the player does, in the client

The game must be open for these steps; agents never open it.

1. Record the match as usual.
2. After the match, open it in the client's match history and download its
   replay. The client writes the `.vrf` file to
   `%LOCALAPPDATA%\VALORANT\Saved\Demos` and rotates that folder, so older
   files disappear.
3. Download before the next game patch. A replay belongs to its build, and
   vrfkit reads only builds whose per-patch constants it carries
   [domain:replay/vrf-values-scrambled-per-patch]; a match left until after a
   patch may never be kept.
4. Tell an agent the match is downloaded, or leave a note naming the capture.

## What an agent does next

1. Copy the new `.vrf` files from the Demos folder into
   `<store>/external/replays/`, byte for byte, comparing sha256 of source and
   copy, and add them to `external/replays/manifest.json` with the capture
   session they belong to (`capture_session`).
2. `prototypes/replay_truth.py parse` and `check` (the parse against Riot's
   record), then `score SESSION`.
3. `prototypes/replay_abilities.py census MATCH`, `score SESSION` and
   `survey`, each with `--record`.

Commands live in [the working map](WORKING_MAP.md).
