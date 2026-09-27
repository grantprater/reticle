# Pub/sub performance baseline

Where a scan's time goes today, and how much a decoupled, pipelined pass could
recover, read from the scan usage log (`<store>/notes/usage.jsonl`,
`scan-usage-1`; [USAGE.md](USAGE.md)) on 2026-09-27 for
[PUBSUB_PLAN.md](PUBSUB_PLAN.md). No scan ran and no media was opened.

**The figures live in [`pubsub_baseline.json`](pubsub_baseline.json).** QUOTED
resolves a `[metric:...]` citation only against `pass` rows in
`<store>/notes/metrics.jsonl`. No tool copies a match scan's usage record there;
`demo_cast_census` does so only for demo crop-cache writes. This baseline could
not add rows to a read-only store, so the prose names each figure by its JSON
key and quotes only figures that metrics rows already hold. Each JSON record's
`session` and `recorded_at` name its usage record.

## The records

Usage logging landed in commit 89bc726; `meta` gives the cutoff. Every record
but one ran a single reader (`scan --only`), and nobody has recorded a full
fused scan. The records fall into batches (`groups`):

| Batch | Frame source | Clips | Concurrency (`concurrent_records`) |
|---|---|---|---|
| `roi_cache:minimap/video/match/b1` | decode | matches | one at a time |
| `ally_icon/cache/match/b1`, `b3` | minimap crop cache | matches | several scans at once |
| `ally_icon/cache/match/b2` | minimap crop cache | 7010b3d62460 | alone |
| `scoreboard/video/match/b1` | decode | matches | one at a time |
| `scoreboard/video/match/b2` | decode | matches | two or three at once |
| `killfeed_portrait/cache/match/b1` | killfeed crop cache | matches | one at a time |
| `hud/cache/match/b1` | hud crop cache | matches | one at a time |
| `hud+killfeed_portrait/cache/match/b1` | hud crop cache | c62c2b06bcfb | alone |
| `roi_cache:minimap/video/demo/b1`, `b2` | decode on NVDEC | demo clips | one at a time |
| `minimap/video/match/b1` | decode | matches | one at a time, beside other jobs |

Only the demo batches name their decoder: their `demo_cast_census/cache`
metrics rows declare `decode: nvdec` and link each usage `run_id`.

## 1. Where the time goes

Wall time splits into source (waiting for the next frame or crop), readers
(`feed` plus `finish`) and the rest (`share_source`, `share_readers`, `share_rest`).

| Batch | What dominates |
|---|---|
| crop-cache write, video | source; the writer is cheap, so the pass is decode-bound |
| scoreboard, video | source and reader share the pass; the reader leads when alone |
| minimap, video | source on std sessions; the reader on the bigmap one |
| demo crop-cache writes, video | source; setup shows because the clips are short |
| ally_icon, crop cache | the reader, by far; publication after the pass shows too |
| killfeed_portrait, crop cache | the reader, then crop decode |
| hud, crop cache | crop decode and the reader, evenly |

Every single-reader pass runs faster than real time (`x_realtime`); the
scoreboard is the slowest video pass, ally_icon the slowest crop-cache pass, and
hud and killfeed rereads from the crop cache the fastest passes in the log.

## 2. The pass is sequential; the bound on overlapping it

`passes.run` and `passes.run_cached` pull a frame, feed every reader that wants
it in turn, and only then pull the next; `ScanUsage.timed_frames` times the
pull. Nothing overlaps on that thread, so a record's pass equals its source,
reader and other time by construction. Beneath the pull, sources differ:

- The crop cache decodes crops on the consumer thread (`RoiCache.samples`),
  in series with the readers.
- `_NvdecCapture` decodes ahead on its own thread, `_NVDEC_AHEAD` frames deep;
  its source time is the wait the queue failed to hide.
- OpenCV decodes inside `grab()`, in series. Under `RETICLE_DECODE=auto`,
  `open_capture` falls back to it silently, and the record names neither.

Two bounds per record assume free cores: `gain_overlap_frac_wall` gives the
source its own worker, so the pass shrinks to the larger of source and reader
time; `gain_parallel_frac_wall` also runs readers concurrently, so the slowest
replaces their sum.

| Batch | Overlap bound | Why |
|---|---|---|
| crop-cache write, video | small | decode dwarfs the writer |
| ally_icon, crop cache | small | the reader dwarfs crop decode |
| minimap, video | large | reader time is a real share |
| scoreboard, video | large | source and reader balance |
| killfeed_portrait, crop cache | large | crop decode is a real share |
| hud, crop cache | largest | crop decode and reader balance |

The single two-reader record (c62c2b06bcfb, 2026-09-26T19:09:19Z) is the only
one where the parallel bound exceeds the overlap bound: running its readers
concurrently lifts the gain well above overlap alone.

**Decode hid no reader time where it could be checked.** Three scoreboard
records ran alone on sessions that also have a crop-cache write (043bafca271a
at 09:58:01Z, a06f04a0059f at 09:52:39Z, 7010b3d62460 at 09:46:09Z, all
2026-09-26, after NVDEC landed in 8002303). Their source time stays close to
the crop-cache write's decode of the same file (`same_session_source`), though
the scoreboard added reader time comparable to that decode. Either they decoded
on OpenCV, or the queue ran dry: at 2 Hz the sampler grabs more frames between
samples than `_NVDEC_AHEAD` holds, so each reader call overlaps at most one
queue of decode. The record cannot tell which.

**A full scan, composed.** `composite` estimates a fused scan per session from
separate records: decode is the crop-cache write's source time, each reader
its lowest recorded cost. It is not a measured scan; ping, roster, lineup,
minimap_dark and combat report have no record, and minimap enters only
`core_plus_minimap`. Over the five readers recorded on nearly every match
(`composite_summary.core`), decode is the minority of the serial time, so
overlapping decode alone buys a modest gain. Running readers concurrently buys
more, capped by the slowest reader, usually ally_icon. Either way the composed
scan runs faster than real time.

## 3. The dominant reader, and the shape of its calls

ally_icon is the heaviest reader in the composite on most sessions, the
scoreboard on the rest (`composite_summary.core.heaviest`).

- **ally_icon costs per pixel, not per call.** Most calls fall in the
  tens-of-milliseconds bucket, few in the sub-millisecond ones, and the
  distribution has one mode (`groups.*.heaviest_bucket_frac`). The bigmap
  profile's minimap ROI holds more pixels than the std one
  (`pixel_ratio_bigmap_over_std`, from `profiles.py`), and ally_icon's cost per
  call rises with it in both contended batches (`per_pixel`), and more steeply
  between the lone records of 7010b3d62460 and c40d950031bb. The minimap
  reader's one bigmap record tracks the pixel ratio; hud, killfeed_portrait and
  the scoreboard read the same ROI in both profiles and cost the same. Batching
  calls would amortize little; parallel work or fewer operations per pixel would.
- **Contention inflates ally_icon.** It declares no `cv_threads`, so it runs on
  OpenCV's default pool, unlike `minimap` and `minimap_dark`; its batches ran
  several scans at once. c40d950031bb's lone record (2026-09-26T06:34:24Z)
  cost far less than its contended one (02:35:45Z); 7010b3d62460's two lone
  records (01:59:40Z, 05:17:10Z) agree with each other. A code change between
  batches would also move the cost, and the record carries no code revision or
  CPU time, so the uncontended cost of most sessions is unknown.
- **The scoreboard pays a full-frame floor on every call.** No call falls
  below the 10 ms bucket bound, and a separate tail sits at the top bucket.
  `scoreboard._slabs` converts the whole frame to HSV and builds its masks
  before `read_scoreboard` learns the board is closed. That floor is per-pixel
  work over a fixed full frame. A cheaper open-board gate would cut it;
  batching would not.

## 4. What a rerun after a reader change costs

`reticle plan` finds nothing stale on a06f04a0059f, 043bafca271a or
5822b6646448, so it prices no rerun today; its routing (`plan.reader_streams`)
says what a change would cost. A stale hud or killfeed stream is checked with
`trial --from cache`, then reread from the crop cache. Plan labels an ally_icon
change `decode`, since that reader has no trial, yet `scan` feeds it from the
minimap crop cache (`roi_cache.cache_for`). The minimap, roster, ping,
minimap_dark, combat report and scoreboard readers have no cache set and
decode. Rounds and deaths rerun from storage.

`scan_tiers` timed a killfeed recheck on a06f04a0059f before NVDEC landed:

| Route | Wall seconds |
|---|---|
| `scan --only hud --force`: one decode, the whole HUD pass | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#current_s=184.0] |
| `plan` | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#plan_s=0.4] |
| `plan`, then `trial --from video` on stored windows | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#tier2_s=84.0] |
| `plan`, then `trial --from cache` on stored windows | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#tier3_s=17.8] |
| cache trial over the whole timeline | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#all_cache_s=29.5] |
| building the crop cache, once per session | [metric:scan_tiers/killfeed-recheck@a06f04a0059f#cache_build_s=154.6] |

The usage records agree: a hud or killfeed_portrait reread from the crop cache
waits far less per frame than the scoreboard's decode of the same 2 Hz
timestamps (`groups.*.source_ms_per_frame`). The cache removes decode and
nothing else, so an ally_icon reread still costs the reader. `batch_totals`
gives each corpus rerun's time. Standalone commands log no usage, so the
storage-only adjudications go unmeasured. On NVDEC, the demo crop-cache writes read
[metric:demo_cast_census/cache@demos#capture_s=1485.5] seconds of capture in
[metric:demo_cast_census/cache@demos#pass_s=212.5] seconds of pass.

## 5. What the records say about the machine

| The records carry | The records lack |
|---|---|
| wall time of setup, pass and publication | CPU time, per process or per reader |
| source wait and each reader's call times | the decode backend, NVDEC or OpenCV |
| call-duration buckets per reader | OpenCV's thread count per reader |
| reader rates and span counts | GPU use or NVDEC load |
| frame source: video, or the cache version | machine load and other processes |
| profile, session and content key | the code revision and reader versions |
| completion time, from which overlap between recorded scans follows | failed scans, cache hits, `trial` and standalone commands |

`concurrent_records` comes from timestamps alone: it sees recorded scans that
overlapped one another, never other processes, such as the GPU job that ran
beside the minimap records of 2026-09-27.

## The plan's predictions

| Prediction in PUBSUB_PLAN.md | Verdict |
|---|---|
| 1. A pass is one thread; decode and readers add | Holds on the consumer thread. NVDEC can decode ahead on a second thread, yet decode hid no reader time where it could be checked, and the record names no backend. |
| 2. Crop-cache passes gain little; the gain lives in video passes | Refuted. The gain follows the balance of source and reader time, not the source kind: hud from the cache gains the most, the video crop-cache write little. |
| 3. One reader dominates, at a fixed per-call cost, so batching helps | Half holds. ally_icon dominates, but its cost scales with pixels; the scoreboard's floor is full-frame pixel work. Batching helps neither. |
| 4. The transport is not the cost | Untested here. `groups.*.retrieved_fps` bounds the message rate a transport would carry. |

## What would make the next baseline citable

- `scan` records a metrics row per completed scan, with the usage `run_id` as
  context, as `demo_cast_census` does.
- The usage record gains the decode backend, OpenCV thread counts, process CPU
  time and the code revision.
- One uncontended full fused scan per profile checks the composite.
