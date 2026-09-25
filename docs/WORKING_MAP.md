# Reticle working map

Use this as a routing index when picking up work. It is intentionally short;
the linked source is authoritative for detail. It routes by SUBSYSTEM; to route
by the question itself -- *which agent died*, *where is the player* -- ask
`reticle ownership`, which also says what the owner it names is NOT for.

## Start here

1. `git status --short` — preserve existing work and avoid overwriting it.
2. Read the eager root [`AGENTS.md`](../AGENTS.md) (or equivalent `CLAUDE.md`),
   [NOTES.md](../NOTES.md), and the selected active task in
   [BACKLOG.md](../BACKLOG.md). Its single executable definition is in
   [tasks.json](tasks.json).
3. Run `.\.venv\Scripts\python.exe -m reticle doctor` and inspect status
   with `.\.venv\Scripts\python.exe -m reticle status`.
4. Follow the selected contract's `reads`, the owning module docstring, and the
   relevant [PROJECT_GUIDE.md](../PROJECT_GUIDE.md) section. Read design plans
   only when that task needs their rationale or acceptance boundary.

`NOTES.md` holds current execution state; `BACKLOG.md` orders work; contracts
specify commands and evidence requirements. Historical handoffs and completed
arguments live in [docs/archive/](archive/). The product and architecture plans
retain design rationale, not a competing live queue.

For the next three bounded tasks, record accepted or blocked outcome, selected
required reading volume, measured corrections, and whether the real output was
reviewed. Leave unmeasured time and token claims unknown.

## Module routing

Current cross-pipeline review and delivery gates:
[PIPELINE_REVIEW.md](PIPELINE_REVIEW.md). It distinguishes implemented foundations
from proposed semantics, acquisition policy and acceptance requirements.

| Need | Read / change first |
|---|---|
| CLI wiring and session selection | `reticle/cli.py`, `reticle/__main__.py` |
| Source identity and decode | `fingerprint.py`, `decode.py`, `passes.py` |
| Persistent schemas and cache rules | `store.py`, `version.py` |
| Frame primitives and spans | `primitives.py`, `segment.py` |
| HUD, killfeed, roster | `ocr.py`, `killfeed.py`, `roster.py` |
| Rounds and phase boundaries | `rounds.py`, `scoreboard.py` |
| Minimap observations/tracks | `minimap.py`, `track.py`, `ping.py` |
| Position belief and its evidence | `belief.py`, `docs/ADJUDICATION_DESIGN.md` |
| Which icon is which: the occluder inventory, the glyph track G1-G5, and portrait/shape/region/animation matching | [MINIMAP_APPEARANCE_MATCHING.md](MINIMAP_APPEARANCE_MATCHING.md) |
| Current mining critique, minimal-label extraction design, and deterministic/YOLO comparison | [MINIMAP_MINING_REVIEW.md](MINIMAP_MINING_REVIEW.md) |
| What else lives in a colour key | `prototypes/key_collision.py`, off existing label sheets, no decode |
| Static map geometry and its key | `geometry.py`, `prototypes/minimap_geometry.py`, `prototypes/map_shade.py` |
| What is true of the GAME, cited not restated | `domain/*.toml`, `reticle/domain.py`, `reticle domain` |
| First entity/domain loop after scan fixes | [ENTITY_DOMAIN_LOOP_PILOT.md](ENTITY_DOMAIN_LOOP_PILOT.md) (prepared; waits for readiness) |
| Review proposed domain knowledge over stored evidence | `reticle/domain_learning.py`, `tools/domain_hypothesis.py`, [ENTITY_DOMAIN_LEARNING_DESIGN.md](ENTITY_DOMAIN_LEARNING_DESIGN.md) |
| WHICH MODULE MAY DECIDE A QUESTION, and what it is not for | `reticle ownership <question>`, `ownership.toml`, [OWNERSHIP_INDEX.md](OWNERSHIP_INDEX.md) |
| The layering, and which upward edges are blessed | `architecture.toml`, `reticle/architecture.py` |
| A figure quoted in prose, and the run behind it | `reticle/quoted.py`, `reticle/metrics.py` |
| Cross-channel checks | `reconciliation.py`, `checks.py`, `doctor.py` |
| Full temporal adjudication design | `docs/ADJUDICATION_DESIGN.md` |
| Ability entity inference and minimal capture plan | `docs/ABILITY_ENTITY_INFERENCE_DESIGN.md` |
| Coaching/review adapter | `coaching.py`, `review.py`, `docs/IMPLEMENTATION_PLAN.md` |
| Economy ledger and prediction design | `economy.py`, `tests/test_economy.py`, `docs/ECONOMY_AND_PREDICTION_DESIGN.md` |
| Dense evidence for selected reviews | `refinement.py`, `refine.py`, `tests/test_refine*.py` |
| Visual debugging | `overlay.py`, `glance.py`, `refine.py` |

Contiguous minimap correction and review: [MINIMAP_DETECTION_PLAN.md](MINIMAP_DETECTION_PLAN.md),
`tools/minimap_sequence_summary.py`, and `tools/minimap_sequence_review.py`.

Cutting a frozen evaluation window on a new session starts at
`tools/wipe_scout.py`: it locates the instants where the per-frame killfeed
count and the adjudicated one disagree, which is where a camera wipe is,
without opening the video.

Module names above are relative to `reticle/` unless a directory is shown.
Minimap work also requires `prototypes/CLAUDE.md` and the domain notes kept
outside this public repository. Do not recreate attribution or private quotes
in repository files. The root `CLAUDE.md` explains the private notes location.

## Commands for a focused handoff

Always use the repository venv:

```powershell
.\.venv\Scripts\python.exe -m reticle doctor
.\.venv\Scripts\python.exe -m reticle status
.\.venv\Scripts\python.exe -m reticle plan [SESSION]      # stale streams, least work
.\.venv\Scripts\python.exe -m reticle trial SESSION --reader killfeed [--from video]
.\.venv\Scripts\python.exe -m reticle scan SESSION --only roi_cache --cache-roi killfeed
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
.\.venv\Scripts\python.exe -m reticle acquisition-plan REQUESTS.json
.\.venv\Scripts\python.exe -m reticle capabilities
.\.venv\Scripts\python.exe -m reticle refine SESSION --review-id ID
.\.venv\Scripts\python.exe -m reticle fidelity-check          # opens media
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
.\.venv\Scripts\python.exe tools\wipe_scout.py SESSION   # stored data only
.\.venv\Scripts\python.exe prototypes\minimap_geometry.py --all
```

Geometry is one npz per `<map>__<profile>`, never per session: resolve every
path through `reticle/geometry.py` rather than joining a session id onto
`store/geometry/`. A session with no `map:` tag reaches no geometry, and
`doctor`'s COVERAGE check reports it.

For stored-data changes, prefer `segment`, `audit`, `coach`, or `sql`
as appropriate. `segment`/`audit` reuse stored L1; `hud`,
`scan`, `board`, and `overlay` need source pixels. Run a targeted test file
first, then the full suite when the change crosses module boundaries.
`refine` previews stored windows; `--execute` reads only their merged intervals
and writes separate dense evidence. It requires current provenance and a cached
killfeed mask. Repeat `--review-id` to combine windows; limits refuse, not truncate.

## Rules that protect comparability

- Separate raw observations from pure adjudication. Store what a detector read,
  when and where it read it, quality/refusal, producer version, and provenance;
  derive entities, intervals, and coaching hypotheses in later versioned steps.
- If a rule can be recomputed from stored data, do not decode video. Keep its
  own stamp and dependency boundary; unrelated detector changes must not
  restamp it.
- Give each independent detector or observation table its own version stamp.
  A shared decode pass is an execution optimization, not a shared definition.
- Unknown stays `null` with a reason. Refusal, missing widget, stale input, and
  terminal state must remain distinguishable from a real zero.
- Record evidence and disagreements before promoting an inference. Agreement
  between channels is consistency, not proof of detector accuracy.
- Fix a bad detection by cross-referencing another channel before tuning the
  one that produced it; see the global constraint in the root `CLAUDE.md`.
- Stored timestamps are observation times. A delayed detector answer must not
  silently become the event's inferred origin.
- Never use stored-data bounds or a model's own output as independent evidence;
  inspect source windows for unresolved cases.
- Keep private attribution outside this repository and never put session URLs in
  files or commits.

## Small architecture recommendations

Keep the pipeline as `raw observation -> adjudication -> lifecycle event ->
compound episode -> review/coaching hypothesis`. Make adjudication pure over
stored observations wherever possible, with explicit alternatives and evidence
links. This permits cheap threshold/rule experiments and correction rebuilds.

Use task-local notes or small focused docs linked from this map. Do not grow a
single eagerly loaded context file with measured results, transient status, or
duplicated detector prose; those belong beside the owning module or in the
implementation plan/backlog.

Treat review windows as pointers into source media plus provenance, not exported
clips or conclusions. Keep no-contact opportunities and unresolved cases so
coverage does not collapse to only dramatic outcomes.
