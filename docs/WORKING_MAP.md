# Reticle working map

This map routes by subsystem; the linked source is authoritative.
`reticle ownership` routes by question (*which agent died?*) and names what each
owner is not for.

## Start here

1. `git status --short` — preserve existing work.
2. Read [`AGENTS.md`](../AGENTS.md), then [NOTES.md](../NOTES.md) (the current
   handoff), then the task in [BACKLOG.md](../BACKLOG.md)
3. Run `doctor` and `status` (commands below).
4. Read the owning module docstring and its
   [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) section; read a design plan only for
   its rationale or acceptance boundary.

Dated history lives in [docs/archive/](archive/).

## Module routing

Delivery gates: [PIPELINE_REVIEW.md](PIPELINE_REVIEW.md).

| Need | Read / change first |
|---|---|
| CLI wiring and session selection | `reticle/cli.py`, `reticle/__main__.py` |
| Source identity and decode | `fingerprint.py`, `decode.py`, `passes.py` |
| Persistent schemas and cache rules | `store.py`, `version.py` |
| Frame primitives and spans | `primitives.py`, `segment.py` |
| HUD, killfeed, roster | `ocr.py`, `killfeed.py`, `roster.py` |
| Killfeed icons, new and beside the victim | `adjudication/weapon.py`, `prototypes/killfeed_openset.py`, [KILLFEED_VICTIM_ICON.md](KILLFEED_VICTIM_ICON.md) |
| Rounds and phase boundaries | `rounds.py`, `scoreboard.py` |
| Is the Tab scoreboard open, and its round marks | `scoreboard.py`, `scoreboard_strip.py` (`reticle strip`), `adjudication/scoreboard.py` (`reticle openings`), [SCOREBOARD_PRESENCE.md](SCOREBOARD_PRESENCE.md), [SCOREBOARD_ROUND_MARKS.md](SCOREBOARD_ROUND_MARKS.md) |
| Each side's five agents from the scoreboard | `adjudication/identity.py` (`board_side_sets`, `lineup_with_board`), [SCOREBOARD_LINEUP.md](SCOREBOARD_LINEUP.md) |
| Minimap observations/tracks | `minimap.py`, `track.py`, `ping.py`, `team_vision.py` |
| Which stored minimap fits become icons; the candidate record | `candidate_evidence.py`, `adjudication/minimap_candidates.py`, [MINIMAP_CANDIDATE_CONTRACT.md](MINIMAP_CANDIDATE_CONTRACT.md) |
| Position belief; temporal adjudication design | `belief.py`, `docs/ADJUDICATION_DESIGN.md` |
| Which icon is which: occluders, glyphs, appearance matching | [MINIMAP_APPEARANCE_MATCHING.md](MINIMAP_APPEARANCE_MATCHING.md) |
| Minimap mining critique, minimal-label design, deterministic vs YOLO | [MINIMAP_MINING_REVIEW.md](MINIMAP_MINING_REVIEW.md) |
| What else lives in a colour key | `prototypes/key_collision.py` (label sheets, no decode) |
| Static map geometry and its key | `geometry.py`, `prototypes/minimap_geometry.py`, `prototypes/map_shade.py`, `occluders.py` |
| What is true of the GAME, cited not restated | `domain/*.toml`, `reticle/domain.py`, `reticle domain` |
| Proposed domain knowledge, reviewed over stored evidence | `reticle/domain_learning.py`, `tools/domain_hypothesis.py`, [ENTITY_DOMAIN_LEARNING_DESIGN.md](ENTITY_DOMAIN_LEARNING_DESIGN.md) |
| WHICH MODULE MAY DECIDE A QUESTION | `reticle ownership <question>`, `ownership.toml`, the `reticle/ownership.py` docstring |
| Layers and blessed upward edges | `architecture.toml`, `reticle/architecture.py` |
| A quoted figure and its run | `reticle/quoted.py`, `reticle/metrics.py` |
| Which documents are live, and what reaches them | `documents.toml`, `reticle/documents.py`, `doctor` DOCS |
| VOD scan cost and reader call frequencies | `reticle usage [SESSION]`, `reticle/usage.py` |
| What live analysis costs the game's frame rate | [FRAMETIME_PROTOCOL.md](FRAMETIME_PROTOCOL.md), `prototypes/live_load.py`, `prototypes/frametime_results.py` |
| Cross-channel checks | `reconciliation.py`, `checks.py`, `doctor.py` |
| Riot match records | `prototypes/riot_ground_truth.py SESSION\|--all` |
| Experiments | [EXPERIMENT_PROGRAM.md](EXPERIMENT_PROGRAM.md), [E1_AGREEMENT.md](E1_AGREEMENT.md), `prototypes/e1_agreement.py` |
| The scene model (render-and-compare) | [SCENE_MODEL.md](SCENE_MODEL.md) |
| Events consumers read | [ENTITY_EVENTS.md](ENTITY_EVENTS.md) |
| Ability entity inference and capture plan | `docs/ABILITY_ENTITY_INFERENCE_DESIGN.md` |
| Every caster's minimap abilities | [ABILITY_DETECTION.md](ABILITY_DETECTION.md) |
| What each demo cast draws on the minimap | [DEMO_CAST_CENSUS.md](DEMO_CAST_CENSUS.md) |
| Naming the player's casts from audio | [AUDIO_ABILITY_BANK.md](AUDIO_ABILITY_BANK.md) |
| The audio gate: design, labels, results | [AUDIO_GATE.md](AUDIO_GATE.md) |
| Voice lines: whose ult, when; ult-ready replies; cast lines | `ult_lines.py`, `adjudication/ult_cast.py`, [VOICE_LINES.md](VOICE_LINES.md), [ULT_READY_LINES.md](ULT_READY_LINES.md), [VOICE_LINE_ASSETS.md](VOICE_LINE_ASSETS.md) |
| What each ability does (the player's mechanics sheet) | `docs/ABILITY_MECHANICS_SHEET.md` |
| Each ability's state per slot, and what it conditions | [ABILITY_STATE_MODEL.md](ABILITY_STATE_MODEL.md), `adjudication/ability_state.py` |
| Coaching/review adapter | `coaching.py`, `review.py`, `docs/IMPLEMENTATION_PLAN.md` |
| Economy ledger and prediction design | `economy.py`, `tests/test_economy.py`, `docs/ECONOMY_AND_PREDICTION_DESIGN.md` |
| Dense evidence for selected reviews | `refinement.py`, `refine.py`, `tests/test_refine*.py` |
| Visual debugging | `overlay.py`, `glance.py` |
| Round review from events | `round_view.py`, `view_events.py`, `docs/EVENT_GAPS.md` |
| Contiguous minimap correction and review | `tools/minimap_sequence_summary.py`, `tools/minimap_sequence_review.py` |
| Camera wipes: per-frame vs adjudicated killfeed counts disagree | `tools/wipe_scout.py` |

Module names are relative to `reticle/` unless a directory is shown.

## Commands for a focused handoff

```powershell
.\.venv\Scripts\python.exe -m reticle doctor
.\.venv\Scripts\python.exe -m reticle verify --tier fast   # default sanity check
.\.venv\Scripts\python.exe -m reticle status
.\.venv\Scripts\python.exe -m reticle plan [SESSION]      # stale streams, least work
.\.venv\Scripts\python.exe -m reticle trial SESSION --reader killfeed|hud|scoreboard [--from video]
.\.venv\Scripts\python.exe -m reticle scan SESSION --only roi_cache --cache-roi killfeed
.\.venv\Scripts\python.exe -m reticle scan SESSION --only hud   # killfeed/HUD rewrite from the crop cache (--from video decodes)
.\.venv\Scripts\python.exe -m reticle scan SESSION --only scoreboard --cache-roi scoreboard   # decodes; crops inside the strip gate
.\.venv\Scripts\python.exe -m reticle domain --check
.\.venv\Scripts\python.exe -m reticle ownership [QUESTION] [--module M] [--check]
.\.venv\Scripts\python.exe -m reticle.architecture [--graph]
.\.venv\Scripts\python.exe -m reticle.quoted [--uncited]
.\.venv\Scripts\python.exe -m reticle audit
.\.venv\Scripts\python.exe -m reticle belief SESSION   # stored data only
.\.venv\Scripts\python.exe -m reticle ability-coverage
.\.venv\Scripts\python.exe -m reticle ability-timeline
.\.venv\Scripts\python.exe -m reticle ability-entities
.\.venv\Scripts\python.exe -m reticle ability-gallery
.\.venv\Scripts\python.exe -m reticle ability-capture
.\.venv\Scripts\python.exe -m reticle ability-phases
.\.venv\Scripts\python.exe -m reticle ult-lines SESSION     # decodes the audio stream only
.\.venv\Scripts\python.exe -m reticle ult-cast SESSION      # stored data only
.\.venv\Scripts\python.exe -m reticle ability-state SESSION # stored data only
.\.venv\Scripts\python.exe -m reticle ability-audio-fit --gate-in G.json --eval ROOT  # audio witness params; stored log-mel only
.\.venv\Scripts\python.exe prototypes\audio_open_set.py score --scan DIR  # ungated ability events on the demos; stored detections only
.\.venv\Scripts\python.exe prototypes\audio_open_set.py match-score --match DIR  # the frozen dev choice on the player's matches; stored detections only
.\.venv\Scripts\python.exe -m reticle killstreak SESSION    # numerals vs death stream; stored data only
.\.venv\Scripts\python.exe -m reticle acquisition-plan REQUESTS.json
.\.venv\Scripts\python.exe -m reticle capabilities
.\.venv\Scripts\python.exe -m reticle refine SESSION --review-id ID
.\.venv\Scripts\python.exe -m reticle fidelity-check          # opens media
.\.venv\Scripts\python.exe -m reticle minimap-objects SESSION  # crop cache only
.\.venv\Scripts\python.exe -m reticle enemy-tracks SESSION
.\.venv\Scripts\python.exe -m reticle project SESSION --lane round_entity --lane death --lane spike --lane enemy  # stored data only
.\.venv\Scripts\python.exe -m reticle view SESSION --round N|--gaps  # stored events and lanes
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe tools\wipe_scout.py SESSION   # stored data only
.\.venv\Scripts\python.exe prototypes\minimap_geometry.py --all
.\.venv\Scripts\python.exe prototypes\line_classes.py bake --all
.\.venv\Scripts\python.exe -m reticle occluders --all
```

Geometry is one npz per `<map>__<profile>`, never per session: resolve every
path through `reticle/geometry.py`, never by joining a session id onto
`store/geometry/`. A session with no `map:` tag reaches no geometry; `doctor`
COVERAGE reports it.

For stored-data changes, prefer `segment` or `audit` (both reuse
stored L1), `coach` or `sql`. `scan --only hud` rereads the crop cache
(`roi_cache`) and decodes only with `--from video`. Under the default
`--from auto`, a span reader reads a complete round cache, else decodes
(`roi_cache.clip_record` owns the clip). `hud`, `board` and `overlay` open the
source video. Run a targeted test file, then `verify --tier fast`, then the
full suite across module boundaries.
`refine` previews stored windows; `--execute` reads only their merged intervals
into separate dense evidence. It requires current provenance and a cached
killfeed mask. Repeated `--review-id`s combine windows; limits refuse, never
truncate.

## Rules

[AGENTS.md](../AGENTS.md#global-constraints) holds the global rules. They
protect the pipeline spine `raw observation -> adjudication -> lifecycle event
-> compound episode -> review/coaching hypothesis`, declared as layers in `architecture.toml`.
