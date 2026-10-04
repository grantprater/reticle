# Reticle working map

A routing index; the linked source is authoritative. It routes by
SUBSYSTEM; to route
by the question itself -- *which agent died*, *where is the player* -- ask
`reticle ownership`, which also says what the owner it names is NOT for.

## Start here

1. `git status --short` — preserve existing work.
2. Read the eager root [`AGENTS.md`](../AGENTS.md), which `CLAUDE.md` imports,
   then [NOTES.md](../NOTES.md), then the task in [BACKLOG.md](../BACKLOG.md).
3. Run `.\.venv\Scripts\python.exe -m reticle doctor` and inspect status
   with `.\.venv\Scripts\python.exe -m reticle status`.
4. Read the owning module docstring and the relevant
   [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) section; read a design plan only when
   the task needs its rationale or acceptance boundary.

`NOTES.md` holds current execution state and `BACKLOG.md` orders work.
Historical handoffs, completed arguments and the retired task contracts live in
[docs/archive/](archive/).

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
| Minimap observations/tracks | `minimap.py`, `track.py`, `ping.py`, `team_vision.py` |
| Which stored minimap fits become icons, and what a candidate record carries | `candidate_evidence.py`, `adjudication/minimap_candidates.py`, [MINIMAP_CANDIDATE_CONTRACT.md](MINIMAP_CANDIDATE_CONTRACT.md) |
| Position belief and its evidence | `belief.py`, `docs/ADJUDICATION_DESIGN.md` |
| Which icon is which: occluders, glyphs, appearance matching | [MINIMAP_APPEARANCE_MATCHING.md](MINIMAP_APPEARANCE_MATCHING.md) |
| Current mining critique, minimal-label extraction design, and deterministic/YOLO comparison | [MINIMAP_MINING_REVIEW.md](MINIMAP_MINING_REVIEW.md) |
| What else lives in a colour key | `prototypes/key_collision.py`, off existing label sheets, no decode |
| Static map geometry and its key | `geometry.py`, `prototypes/minimap_geometry.py`, `prototypes/map_shade.py`, `occluders.py` |
| What is true of the GAME, cited not restated | `domain/*.toml`, `reticle/domain.py`, `reticle domain` |
| Review proposed domain knowledge over stored evidence | `reticle/domain_learning.py`, `tools/domain_hypothesis.py`, [ENTITY_DOMAIN_LEARNING_DESIGN.md](ENTITY_DOMAIN_LEARNING_DESIGN.md) |
| WHICH MODULE MAY DECIDE A QUESTION, and what it is not for | `reticle ownership <question>`, `ownership.toml`, the `reticle/ownership.py` docstring |
| The layering, and which upward edges are blessed | `architecture.toml`, `reticle/architecture.py` |
| A figure quoted in prose, and the run behind it | `reticle/quoted.py`, `reticle/metrics.py` |
| Which documents are live, their status, and what reaches them | `documents.toml`, `reticle/documents.py`, `doctor` DOCS |
| VOD scan cost and reader call frequencies | `reticle usage [SESSION]`, `reticle/usage.py` |
| Cross-channel checks | `reconciliation.py`, `checks.py`, `doctor.py` |
| Riot match records | `prototypes/riot_ground_truth.py SESSION\|--all` |
| Experiments | [EXPERIMENT_PROGRAM.md](EXPERIMENT_PROGRAM.md), [E1_AGREEMENT.md](E1_AGREEMENT.md), `prototypes/e1_agreement.py` |
| Full temporal adjudication design | `docs/ADJUDICATION_DESIGN.md` |
| The scene model: render-and-compare, all channels | [SCENE_MODEL.md](SCENE_MODEL.md) |
| Events consumers read | [ENTITY_EVENTS.md](ENTITY_EVENTS.md) |
| Ability entity inference and minimal capture plan | `docs/ABILITY_ENTITY_INFERENCE_DESIGN.md` |
| Every caster's minimap abilities: the unified crop-cache pass, its cost, recall, stages | [ABILITY_DETECTION.md](ABILITY_DETECTION.md) |
| What each demo cast draws on the minimap (census, player questions) | [DEMO_CAST_CENSUS.md](DEMO_CAST_CENSUS.md) |
| Naming the player's casts from audio (demo bank, transfer) | [AUDIO_ABILITY_BANK.md](AUDIO_ABILITY_BANK.md) |
| The audio gate: design, mined labels, formulations, predictions, results | [AUDIO_GATE.md](AUDIO_GATE.md) |
| Voice lines: whose ult, which side, when; ult-ready replies; wiki cast lines | `ult_lines.py`, `adjudication/ult_cast.py`, [VOICE_LINES.md](VOICE_LINES.md), [ULT_READY_LINES.md](ULT_READY_LINES.md), [VOICE_LINE_ASSETS.md](VOICE_LINE_ASSETS.md) |
| What each ability does: inputs, minimap drawing, overlay, duration (the player's sheet) | `docs/ABILITY_MECHANICS_SHEET.md` |
| Each ability's state per slot, and the detectors it conditions | [ABILITY_STATE_MODEL.md](ABILITY_STATE_MODEL.md), `adjudication/ability_state.py` |
| Coaching/review adapter | `coaching.py`, `review.py`, `docs/IMPLEMENTATION_PLAN.md` |
| Economy ledger and prediction design | `economy.py`, `tests/test_economy.py`, `docs/ECONOMY_AND_PREDICTION_DESIGN.md` |
| Dense evidence for selected reviews | `refinement.py`, `refine.py`, `tests/test_refine*.py` |
| Visual debugging | `overlay.py`, `glance.py`, `refine.py` |
| Round review from events | `round_view.py`, `view_events.py`, `docs/EVENT_GAPS.md` |

Contiguous minimap correction and review: `tools/minimap_sequence_summary.py`
and `tools/minimap_sequence_review.py`.

`tools/wipe_scout.py` finds a new session's camera wipes for a frozen
evaluation window where the per-frame and adjudicated killfeed counts
disagree, without opening the video.

Module names above are relative to `reticle/` unless a directory is shown.

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
.\.venv\Scripts\python.exe -m reticle killstreak SESSION    # numerals vs death stream; stored data only
.\.venv\Scripts\python.exe -m reticle weapon-whiten [--scale 1.0 0.667]  # killfeed weapon whitening fit; stored data only
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
path through `reticle/geometry.py` rather than joining a session id onto
`store/geometry/`. A session with no `map:` tag reaches no geometry, and
`doctor`'s COVERAGE check reports it.

For stored-data changes, prefer `segment`, `audit`, `coach`, or `sql`
as appropriate. `segment`/`audit` reuse stored L1. `scan --only hud` rereads
the crop cache (`roi_cache`) and decodes only with `--from video`; under
the default `--from auto` a span reader (`minimap`, `minimap_dark`, `ally_icon`) reads a
round cache's rounds only, without the buy phase, when that cache holds every
live round, and decodes otherwise; its stream records the unread spans as
`spans_clip`; `hud`,
`board` and `overlay` open the source video. Run a targeted test file,
then `verify --tier fast`, then the full suite across module boundaries.
`refine` previews stored windows; `--execute` reads only their merged intervals
and writes separate dense evidence. It requires current provenance and a cached
killfeed mask. Repeat `--review-id` to combine windows; limits refuse, not truncate.

## Rules

The global rules live in AGENTS.md under
[Global constraints](../AGENTS.md#global-constraints), and this map does not
restate them. They protect the pipeline spine `raw observation -> adjudication
-> lifecycle event -> compound episode -> review/coaching hypothesis`, which
`architecture.toml` declares as layers.
