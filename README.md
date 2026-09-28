# Reticle — VOD analysis

Stages 00–02 of the pipeline in the design doc (linked at the top of
[PROJECT_GUIDE.md](PROJECT_GUIDE.md)): fingerprint a capture, decode it
into L1 primitives, gate it into spans, read the scoreline off the HUD, and
write the whole thing to a Parquet event store you can query with DuckDB.

Stage 02 includes scoreline, ammo, HP/shield, attributed killfeed, roster and
minimap readers. Coverage and validation vary; use `status` and `doctor` rather
than assuming every session is current. The pure economy ledger is implemented
and the scoreboard reader stores credit reads; reliable POV and phase detection
remain missing. The coaching layer now extracts player kill/death observations
from stored reads and evaluates an exploratory state-probability baseline when
enough independent sessions are available.

[BACKLOG.md](BACKLOG.md) orders the work. [docs/WORKING_MAP.md](docs/WORKING_MAP.md)
routes a task to its code and holds the command list, and [AGENTS.md](AGENTS.md)
holds the rules every change follows.

The first economy slice accepts explicit adjudicated facts and writes or prints
a versioned ledger; it does not decode footage or infer missing purchases:

```
.\.venv\Scripts\python.exe -m reticle economy facts.json --out ledger.json
```

The input has `teams` (two mappings of stable player IDs) and ordered
`operations`. Supported operation kinds are `reset`, `spend`,
`balance_observation`, and `round`; a round explicitly supplies winner,
attacking team, plant/detonation state, every player's kill count, and every
losing player's survival state. Counts may be `[minimum, maximum]` and uncertain
booleans are `null`. See `tests/test_economy.py` for an executable example.

## Event repository and review queue

```
.\.venv\Scripts\python.exe -m reticle coach
.\.venv\Scripts\python.exe -m reticle coach c40d950031bb
.\.venv\Scripts\python.exe -m reticle audit
.\.venv\Scripts\python.exe -m reticle scan 587c15b07779 --only roster
```

`coach` uses existing L1 only; it does not decode footage. The default bundle is
`~/reticle-store/analysis/coaching/` (a session subdirectory when selecting one):

- `events.jsonl`: deduplicated player kill/death observations, round association,
  quality flags, source hashes, and coarse review windows.
- `states.jsonl`: eligible contemporaneous roster/clock observations.
- `predictions.jsonl`: held-out-session landmark predictions, when supported.
- `report.json`: input/code fingerprints, exclusions, evaluation and limitations.
- `review.md`: one linked source window per observed round for manual review.

The model needs at least three eligible sessions, and at least 30 training rounds
with both outcomes in each fold. These are minimum execution gates, not proof of
adequate data. It excludes stale inputs, unconfirmed/terminal roster states,
missing clocks and uncertain boundaries. It uses no inferred plant timestamp,
economy, side or POV. Estimates are exploratory; state changes are not causal
effects or player credit. When coverage is insufficient, probabilities stay null
and events remain available for review. Clips are not exported; `refine` writes
dense evidence for selected review windows.

`audit` compares score transitions and roster changes with killfeed observations
from stored data, reporting exact disagreement windows without changing rounds.
Agreement is channel consistency, not measured detector accuracy. `scan --only
roster` fills missing saved roster coverage through the existing shared pass,
without constructing minimap geometry or rereading current HUD data. It does
decode the source video. Multiple readers can be selected after `--only`.

The current event adapter contains killfeed observations only. It does not yet
consume the minimap entity model or emit compound contact/exposure episodes;
their intended integration is specified in the implementation plan.

## Setup

```
cd path\to\reticle
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Run everything as `.\.venv\Scripts\python.exe -m reticle <command>`.

## Quickstart

```
.\.venv\Scripts\python.exe -m reticle doctor
.\.venv\Scripts\python.exe -m reticle status
.\.venv\Scripts\python.exe -m reticle plan [SESSION]
.\.venv\Scripts\python.exe -m reticle scan SESSION --only hud
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
```

The working map's
[commands for a focused handoff](docs/WORKING_MAP.md#commands-for-a-focused-handoff)
list the rest.

## Try it without a VOD

```
.\.venv\Scripts\python.exe -m reticle synth --out .\fixtures\synthetic_capture
.\.venv\Scripts\python.exe -m reticle --store .\teststore ingest .\fixtures\synthetic_capture.mp4
.\.venv\Scripts\python.exe -m reticle --store .\teststore inspect --spans 10
```

`synth` renders a clip that carries the *signal structure* the segmenter keys
on — a busy top-left panel, high-contrast corner chrome, a scene that moves or
holds. It exists to prove the plumbing, not to stand in for Valorant. Do not
calibrate thresholds against it.

## With a real VOD

**1 — Check the ROI boxes.** `valorant-16x9` was measured against real
1920x1080 footage on 2026-08-23. Re-check after any HUD restyle, resolution
change, or HUD layout-setting change.

```
.\.venv\Scripts\python.exe -m reticle probe "D:\vods\match.mp4" --n 8
```

That writes annotated frames. Open them. If `minimap` isn't on the minimap,
edit the fractions in `profiles.py` and run it again. Everything downstream is
wrong until this is right.

Before ingesting a new capture, work through the pre-ingest checklist in
[PROJECT_GUIDE.md](PROJECT_GUIDE.md#before-ingesting-any-new-capture): the
crosshair position (a cropped frame loses HUD), the minimap settings, which
`probe` prints and `ingest --minimap-mode` records in the manifest, and the
rest of the capture settings.

**2 — Ingest.**

```
.\.venv\Scripts\python.exe -m reticle ingest "D:\vods\match.mp4"
```

Decodes at 5 Hz by default and writes L1 + spans. Re-running the same file is a
cache hit — pass `--force` to re-decode. Use `--max-frames 2000` for a quick
look at a long capture before committing to a full pass.

**3 — Calibrate the thresholds.**

```
.\.venv\Scripts\python.exe -m reticle segment --all --show-signals
```

This recomputes spans **from stored L1 without touching the video** — the point
of the L0/L1 split in §7. It's milliseconds, so you can sweep thresholds freely:

```
.\.venv\Scripts\python.exe -m reticle segment --minimap-dchange 4 --active-motion 0.02
```

`--show-signals` prints percentiles for each column the classifier thresholds
on. You're looking for a bimodal split; put the threshold in the valley.

**4 — Read the HUD (stage 02).**

```
.\.venv\Scripts\python.exe -m reticle hud
.\.venv\Scripts\python.exe -m reticle verify
```

`hud` re-opens the source the manifest points at and reads the top-centre
scoreline off each sampled frame, writing L1 HUD reads. It needs pixels, so
unlike `segment` it cannot recompute from stored L1. Once a session has a crop
cache, `scan SESSION --only hud` rereads the HUD from it without decoding
(`--from video` forces a decode).

Stage 02 is deterministic and leaves an unread field null rather than guessed;
[AGENTS.md](AGENTS.md#global-constraints) states both rules, and PROJECT_GUIDE.md's
conventions give the method.

`verify` checks the result against domain invariants — the clock tracks real
time, scores never fall, resets coincide with a score change. No labels are
needed for any of that, and a violation localises the extraction fault in time.

**Digit templates.** These are mined from your own footage rather than a font
file, because what matters is how this build renders at this resolution:

```
.\.venv\Scripts\python.exe -m reticle glyphs "D:\vods\match.mp4"          # writes a montage
.\.venv\Scripts\python.exe -m reticle glyphs "D:\vods\match.mp4" --label "0131..."
```

Open the montage, read the clusters left to right, and pass one character per
cluster. The result is committed as a small `.npz` keyed by profile name.
Templates ship for `valorant-16x9` only — `valorant-16x9-crop75` stores a
2560x1440 render at 1:1, so its glyphs are a third larger and both the templates
and the geometry constants in `ocr.py` would need re-deriving.

**5 — Check the result against reality.**

```
.\.venv\Scripts\python.exe -m reticle frames --every 30
```

Dumps frames named with the label the baseline assigned. Skim them. The ones
labelled wrong are your first correction set, and that's what a trained stage-01
classifier eventually gets fitted on.

## Querying

```
.\.venv\Scripts\python.exe -m reticle sql                          # list views and columns
.\.venv\Scripts\python.exe -m reticle sql "SELECT state, round(sum(duration_ms)/1000,1) secs
                       FROM spans GROUP BY state"
```

Views `primitives` (L1) and `spans` (L2) over the whole store.

## What the segmenter actually claims

The design doc calls for a small *trained* classifier over buy / in-round /
post-round / menu / spectate. There's no labelled data yet, so this ships a
rule-based baseline making a deliberately coarser claim:

| state | meaning |
|---|---|
| `off` | no HUD — loading, agent select, alt-tabbed |
| `idle` | HUD present, scene static — death cam, mid-match menu, AFK |
| `active` | HUD present, scene moving |

It keys on three signals: sustained perceptual change in the minimap ROI (a
live minimap redraws constantly), edge density in the bottom-corner HUD ROIs,
and whole-frame motion. All three are thresholded, smoothed with a rolling
median, and short spans get absorbed into their neighbours.

On the synthetic fixture it recovers the script exactly. On Valorant it is
unverified.

## Scan usage

`reticle scan` appends one record per completed scan to
`<store>/notes/usage.jsonl`. `reticle usage [SESSION]` shows recent records,
and `--json` adds the full timing buckets. A record names the session, source,
profile, frame source, reader rates and active spans, and counts the frames and
each reader's `feed` calls. Source time is the shared wait for the next decoded
frame or cached crop; it belongs to the pass, so count it once when comparing
readers. Reader time covers each `feed` and `finish` call, setup and publication
bracket the pass, and the rest of the pass is dispatch, progress display and
instrumentation. The buckets store call-duration frequencies, with boundaries in
nanoseconds under `bucket_upper_ns`; a call on a boundary enters the next
bucket, and no per-frame timing or pixel is kept. Cache hits, standalone
commands and `trial` write no record. Compare records with similar source,
rates, spans and reader sets, since disk cache and machine load also move wall
time. This measures the VOD scan, not an LLM session; the `reticle/usage.py`
docstring defines each field.

## Store layout

```
<store>/manifests/<session>.json                               L0 pointer
<store>/l1/primitives/date=<d>/session=<s>/primitives.parquet   L1
<store>/l2/spans/date=<d>/session=<s>/spans.parquet             L2
```

Default store is `~/reticle-store`; override with `--store`.

The store's conventions are in the `reticle/store.py` docstring, and the version
stamps that drive recompute are in PROJECT_GUIDE.md's conventions.

## Known gaps

- ROI fractions are guesses until `probe` says otherwise.
- Segmentation is a baseline, not the trained classifier the doc specifies.
- `content_key` is a sampled digest (size + head/mid/tail), not a full hash. It
  identifies files; it does not detect corruption.
- 16:9 only. Other aspect ratios need their own profile.
- Single process. A staged `scan` feeds readers on worker threads
  (`pipeline.run_staged`); the usage log records how each pass ran.

## Cost check

`inspect` prints the stage-01 funnel with your capture's real numbers, so you
can see what fraction of a match survives gating before anything expensive
runs; PROJECT_GUIDE.md's conventions state the cost rule.
