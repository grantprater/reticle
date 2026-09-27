# Pub/sub model of the pipeline: plan

Branch `pubsub-20260927`, worktree `reticle-worktrees/pubsub`, cut from master.
Nothing here reaches master until the player merges it.

## Goal

Model the pipeline as publishers and subscribers: each stage consumes messages
from the stage before it and publishes what it produces, with the store as the
durable log. The first question is performance: where a scan's time goes today,
and how much a decoupled design recovers. Correctness and architecture findings
found on the way are recorded, not fixed on this branch unless the fix is small
and verified.

The player's constraints: keep decoding to a minimum; test the least that
verifies the change; no changes to master; branches and worktrees only.

## Phases and their evidence

| Phase | Output | Verified by |
|---|---|---|
| Map | `docs/PUBSUB_PIPELINE_MAP.md`: stages, execution model, storage, seams | A second reader checks each stage's file and line against the code |
| Baseline | `docs/PUBSUB_PERFORMANCE_BASELINE.md`: where time goes, from `usage.jsonl` | Numbers cite their usage records; no new scan |
| Design | `docs/PUBSUB_DESIGN.md`: topics, messages, ordering, state, transport | Critique by a separate agent against AGENTS.md and the map |
| Prototype | A staged pipeline behind the existing readers, transport pluggable | Its L1 output equals the current pass on one crop-cache session (`trial`, no decode) |
| Measure | The same session through both paths, timed per stage | One record per path, same source and rates; an acceptance scan only if the crop-cache result warrants it |
| Handoff | `NOTES.md` rewritten in place; `BACKLOG.md` updated; findings filed | `doctor` passes: LAYER, OWNERSHIP, QUOTED, DOMAIN, HANDOFF |

## Predictions to falsify

Stated before the baseline is read, so the baseline can refute them.

1. A scan pass is one thread: it waits for the next decoded frame, then runs
   every attached reader in turn. Decode and reader time therefore add, and a
   pipelined design bounds the pass by the larger of the two rather than
   their sum.
2. On crop-cache passes the source share is small and the readers dominate,
   so pub/sub gains little there; the gain lives in video-source passes.
3. One reader dominates reader time, and its call durations cluster at a
   fixed per-call cost, so batching its calls across frames helps more than
   making each call faster.
4. The transport is not the cost. A message per frame per reader is well
   inside what an in-process queue or a local broker carries; the design
   question is the boundary, not the broker.

### Outcomes against the baseline

Read from `docs/PUBSUB_PERFORMANCE_BASELINE.md` and `docs/pubsub_baseline.json`.

1. Confirmed. `passes.run` fetches a frame, runs every wanting reader, then
   fetches the next. The NVDEC read-ahead hides nothing on 2 Hz passes: its
   queue is shorter than the gap between samples, so the decoder stalls while
   readers run (`same_session_source`).
2. Half right. On crop-cache passes the ally-icon reader dominates, but the
   HUD pass splits evenly between cache reads and the reader, and the largest
   overlap gains are on video-source passes with a heavy reader
   (`composite_summary`).
3. Refuted in its second half. The ally-icon reader dominates, but its cost
   scales with pixels, not calls, so batching calls would save little. The
   scoreboard's cost is a whole-frame colour conversion before it checks
   whether the board is open, which a cheaper gate removes (`per_pixel`).
4. Untested. No record measures a transport; the prototype must.

A fact the predictions missed: no full scan has ever been recorded. Every
usage record is a single-reader pass, and the fused cost is an estimate
built from separate records (`composite`). Scans also ran four at a time,
so the ally-icon records carry contention.

### Outcomes against the measurements

Read from [`PUBSUB_MEASUREMENTS.md`](PUBSUB_MEASUREMENTS.md), design steps 3 and 4.

1. Held from the crop cache; refuted on NVDEC video, where the read-ahead already hides about half
   of each 2 Hz gap and the staged pass ran slower; and on OpenCV's pool no serial pass is one thread.
2. Refuted: the crop-cache HUD pass gained, and the video prefix lost.
3. Not tested; ally_icon reaches about three cores on either path, which points at fewer
   operations per pixel.
4. Held: the staged HUD pass ran close to its reader sum, which bounds threads, queues and
   handoffs together.

## Rules the design must honour

From `AGENTS.md` and `docs/WORKING_MAP.md`:

- A stored timestamp is an observation time. A message carries the frame time
  it was read at, never the time it was processed.
- Every table keeps its own version stamp and provenance. A shared decode
  pass is an execution optimization, not a shared definition; a pub/sub
  stage is the same.
- Recomputable rules do not decode. Adjudication subscribes to L1, never to
  frames.
- Raw media is never copied. A tile message is a lossless crop of a fixed
  reader ROI, the `roi_cache` principle, and lives as long as the cache does.
- SESSION PIXELS DO NOT DEFINE THE MAP. No stage derives static map values
  from a session's frames.
- Names come from `adjudication.identity`; a stage that binds an entity asks
  the arbiter and declares `depends_on`.
- Unknown stays `null` with a reason. A dropped or late message is a refusal
  with a reason, never a silent gap.
- A new module is placed in `architecture.toml`; a new decision has an owner
  in `ownership.toml`; `reticle/` never imports `prototypes/`.

## Decision log

Decisions and their evidence are appended here as the work proceeds.

- 2026-09-27: branch cut from master rather than from `hooks-wired`, so the
  prototype rests on committed code and the other session's uncommitted work
  is not duplicated.
- 2026-09-27, later: re-cut onto `ability-identification-20260926` (a065949),
  which descends from master and is pushed to origin. Master lacked this
  week's tray reader, revive verdicts, `hud-0.15.0` and the audio gate, so a
  map built on it would have missed readers and passes that the store's data
  already carries. The other session asked for this; the evidence was the
  store's `hud-0.15.0` rows against master's `hud-0.12.0` code.
- 2026-09-27, critique: every change the design's critic asked for is applied
  (design, section 6). The staged publish with run records (L6, `publish.py`)
  left the scope, since it exceeds what the plan asks; design finding 1,
  publish in place without a run id, stays filed as open work.
- 2026-09-27, prototype: `scan --check` runs the staged path before the serial
  one, so the staged threads meet the lazily filled module caches (`_ME_CACHE`,
  `_REG`) cold. Steps 1 and 2 ran serial first and so never tested that race
  (prototype, finding 1).
- 2026-09-27, timings: a check's timing rows may be appended to the store's
  `notes/usage.jsonl` and `notes/metrics.jsonl`, because they are notes about
  a run, not derived data. `tools/pubsub_notes_append.py` appends them and
  refuses a run id the store already holds, so a document can cite a check's
  times without the check publishing any stream into the store.
- 2026-09-27, L1 reframed: the staged pipeline, with today's `sample_multi` as
  its source, already moves retrieve and conversion off the reader threads;
  step 4 tests that. The selecting decode producer (`_Selector`) and its
  deeper queue become a further lever, unbuilt.
- 2026-09-27, measurement: the runs of design steps 3 and 4 ran later that
  day, started by the player; the results and their rows are in
  `docs/PUBSUB_MEASUREMENTS.md`. Two of them are confounded, since the
  check's serial path ignores `--cv-threads`, and are filed as open work.
