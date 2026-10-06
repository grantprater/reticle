# Keeping each match's replay

Status: live, 2026-10-04. A protocol for the player and for the agents that
parse what the player keeps. No reader or reader's threshold reads the
replay and nothing shows it during play; it may fit win-probability and
coaching baselines and priors under the use policy in
[EXTERNAL_GROUND_TRUTH.md](EXTERNAL_GROUND_TRUTH.md).

## Why

One replay so far has a capture beside it, and on that one match the replay
gave: where each mapped projectile, smoke, wall and deployable appeared, when
it opened and closed, and which player cast it
[domain:replay/vrf-ability-actors]; each cast with its slot and time
[domain:replay/vrf-cast-records]; each ult [domain:replay/vrf-ult-active];
and each planted spike [domain:replay/vrf-planted-spike-actor]. The census
mapped [metric:replay_abilities/census#mapped=37] of its
[metric:replay_abilities/census#classes=81] actor classes; the
[metric:replay_abilities/census#unmapped=44] it left are inventory items with
no world position, actors outside an ability folder, and Iso's arena, which
no player owns. Chamber's re-placements stay unresolved, and charges,
cooldowns and per-state truth are not decoded. On that match the truth scored
the player's Recon Bolt rings within a median
[metric:replay_abilities/score#rb_err_px_median=0.96] px of the stuck bolt
(`prototypes/replay_abilities.py`) and
paired [metric:replay_abilities/score#ult_paired_same_label=28] of the stored
ult casts by agent and side. Every preserved replay holds hundreds of ability
actors, but only one of the fifteen has a capture
[domain:replay/vrf-ability-truth-per-replay]. Each new match kept with both
adds one more match of this truth, limited to what the census maps.

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

`reticle replay-keep SESSION` (`reticle/replay_keep.py`) does steps 1 to 3,
and `reticle ingest-passes` runs it at the end of every ingest, so a new
capture keeps its replay unasked. `reticle plan SESSION` names each step a
session lacks.

1. Find the replay whose recording overlaps the capture: the header's
   recording time and length against the capture file's name and duration.
   The file's mtime is the download time, not the match's. Zero or several
   overlapping replays refuse by name.
2. Copy it into `<store>/external/replays/`, byte for byte, comparing
   sha256 of source and copy, and name the capture session
   (`capture_session`, `capture_path`) in `external/replays/manifest.json`,
   after a `.bak` of the manifest.
3. Parse it with vrfkit; wrap the Riot record once the player's fetch kit
   has saved it (without one, the hook says the player's fetch is needed);
   build the replay layer and episodes once the stored deaths exist.
4. By hand: `prototypes/replay_truth.py check MATCH` (the parse against
   Riot's record), then `score SESSION`, except on the held-out match;
   `prototypes/replay_abilities.py census MATCH`, `score SESSION` and
   `survey`, each with `--record`.

Commands live in [the working map](WORKING_MAP.md).
