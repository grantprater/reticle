# Reticle working map

Use this as a routing index when picking up work. It is intentionally short;
the linked source is authoritative for detail.

## Start here

1. `git status --short` — preserve existing work and avoid overwriting it.
2. Read [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md) for product direction,
   acceptance gates, and current milestone boundaries.
3. Read [NOTES.md](../NOTES.md) for the live handoff, then the relevant
   [BACKLOG.md](../BACKLOG.md) heading before choosing a task; the backlog is
   the queue and records superseded arguments.
4. Read the eager root [`CLAUDE.md`](../CLAUDE.md), then the relevant section
   of [`PROJECT_GUIDE.md`](../PROJECT_GUIDE.md); the guide retains the full
   design documents, operating rules, pipeline state, and known defects.
5. Read [ARCHITECTURE_PLAN.md](ARCHITECTURE_PLAN.md) for architecture direction
   and acceptance boundaries.
6. Run `.\.venv\Scripts\python.exe -m reticle doctor` and inspect status
   with `.\.venv\Scripts\python.exe -m reticle status`.

## Module routing

| Need | Read / change first |
|---|---|
| CLI wiring and session selection | `reticle/cli.py`, `reticle/__main__.py` |
| Source identity and decode | `fingerprint.py`, `decode.py`, `passes.py` |
| Persistent schemas and cache rules | `store.py`, `version.py` |
| Frame primitives and spans | `primitives.py`, `segment.py` |
| HUD, killfeed, roster | `ocr.py`, `killfeed.py`, `roster.py` |
| Rounds and phase boundaries | `rounds.py`, `scoreboard.py` |
| Minimap observations/tracks | `minimap.py`, `track.py`, `ping.py` |
| Static map geometry and its key | `geometry.py`, `prototypes/minimap_geometry.py`, `prototypes/map_shade.py` |
| Cross-channel checks | `reconciliation.py`, `checks.py`, `doctor.py` |
| Coaching/review adapter | `coaching.py`, `review.py`, `docs/IMPLEMENTATION_PLAN.md` |
| Dense evidence for selected reviews | `refinement.py`, `refine.py`, `tests/test_refine*.py` |
| Visual debugging | `overlay.py`, `glance.py`, `refine.py` |

Module names above are relative to `reticle/` unless a directory is shown.
Minimap work also requires `prototypes/CLAUDE.md` and the domain notes kept
outside this public repository. Do not recreate attribution or private quotes
in repository files. The root `CLAUDE.md` explains the private notes location.

## Commands for a focused handoff

Always use the repository venv:

```powershell
.\.venv\Scripts\python.exe -m reticle doctor
.\.venv\Scripts\python.exe -m reticle status
.\.venv\Scripts\python.exe -m reticle audit
.\.venv\Scripts\python.exe -m reticle refine SESSION --review-id ID
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
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
