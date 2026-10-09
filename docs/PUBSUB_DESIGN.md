# Pub/sub design: a staged scan over the store as the log

This document designs the staged scan and holds the queue of its open work. The [plan](archive/PUBSUB_PLAN-2026-09-27.md)
ran its six phases on 2026-09-27; its goal and the outcomes of its predictions live here now. The design rests on the
[map](archive/PUBSUB_PIPELINE_MAP-2026-09-27.md) and the [baseline](archive/PUBSUB_PERFORMANCE_BASELINE-2026-09-27.md), two snapshots of the
serial pass, and the [measurements](PUBSUB_MEASUREMENTS.md) time the staged pass against it. Writing
sections 1 to 6, I read the code at `a065949`, ran no scan, opened no media and changed no code.

**Citations.** No metrics row holds a scan's usage record, so QUOTED cannot check these figures; each
names its key in [`pubsub_baseline.json`](pubsub_baseline.json). Shorthand: `C[s]` is session `s`'s
`composite` entry; `S` is `composite_summary.core`; `G[b]` and `B[b]` are `groups[b]` and
`batch_totals[b]`; `R[s t]` is session `s`'s `records.rows` row recorded at `t` on 2026-09-26. Derived
figures show their arithmetic; none comes from a docstring.

## Goal

Model the pipeline as publishers and subscribers: each stage consumes messages from the stage before it
and publishes what it produces, with the store as the durable log. The first question is performance:
where a scan's time goes, and how much a decoupled design recovers. The work records the correctness and
architecture findings it meets (section 4) and fixes one only when the fix is small and verified. The
player set the constraints: keep decoding to a minimum, test the least that verifies a change, and work on
a branch, never on master.

## Status (2026-09-27)

The branch merged to master at `e518f8e`, and `scan` keeps `--pipeline serial` as its default. The
`reticle/pipeline.py` docstring states the rules as built.

**Built.**
- `run_staged`: the dispatcher reads the source and offers each frame read-only, and each reader or shard
  feeds on its own thread behind a FIFO of 8 frames; `--workers` caps the feeds that run at once. This is
  L3, and L1 without its selecting producer.
- `_Shards` and the `shardable` contract, which `AllyIconReader` alone declares.
- `scan --check` (`_scan_check` in `cli.py`, over `pipeline.compare_trees`) and `--check-dir`.
- `scan --until` (`pipeline.limit_to_prefix`), and one OpenCV count per staged pass
  (`STAGED_CV_THREADS`, `--cv-threads`).
- `scan-usage-2` as the `reticle/usage.py` docstring lists it, with process and per-thread CPU, and a
  `scan_usage` pass row per scan in `notes/metrics.jsonl`, so QUOTED can cite a scan (finding 11).
- `tools/pubsub_notes_append.py`, which copies a check's rows into the store's notes, and
  `tests/test_pipeline.py`, step 0.

**Unbuilt.**
- L1's selecting producer (`_Selector`) and its deeper queue, which its own rule keeps unbuilt
  ([measurements](PUBSUB_MEASUREMENTS.md), the design's ladder).
- L2, window conversion; L4, the shared per-frame results; L5, the open-board gate; L7, one scheduler.
- L6, the staged atomic publish: `reticle/publish.py`, run records and the `scan-run` owner. Findings 1
  and 2 stay open with it.
- `_publish_scan`, which section 3 names: `--check` runs today's publish block into each temporary store
  instead.
- The usage fields section 3 proposes and `scan-usage-2` lacks: `transport`, `decode_backend`, the OMP,
  MKL and OpenBLAS counts, `decode_ns`, `convert_ns`, `stall_ns`, each reader's `wait_ns`, `overlap`,
  `stage_ns`, `commit_ns`, `priority` and `concurrent_scans`. Finding 7's backend and contention stay open.

**Open work.**
1. Price the shards against one thread. `--check`'s serial path ignores `--cv-threads` and runs on
   OpenCV's pool: make it honour the flag, rerun ally_icon at one thread on both paths, then judge process
   shards by section 3's rule for the GIL.
2. Warm up `--check`: path b runs first, against cold caches (measurements, answer 5).
3. `--until` gives a whole-capture reader one span from 0, so it drops frames with negative timestamps.
4. Choose among the unbuilt levers. On video at 2 Hz decode sets the floor; from the crop cache, ally_icon
   wants fewer operations per pixel.

## The plan's predictions

The plan stated four predictions before anyone read the baseline. The plan and the baseline document each
recorded outcomes against the usage records, in one commit (`fcede4e`); the measurements, taken later on
the staged pass, recorded a second set.

| # | Prediction | Against the baseline | Against the measurements (later) |
|---|---|---|---|
| 1 | A pass is one thread, so decode and reader time add; a pipeline bounds the pass by the larger | Held on the consumer thread. Both documents read the NVDEC read-ahead as hiding no reader time on 2 Hz passes (`same_session_source`); the baseline document allowed that those records decoded on OpenCV | Held from the crop cache. Refuted on NVDEC video: the read-ahead already hides about half of each 2 Hz gap, and the staged pass ran slower. On OpenCV's pool no serial pass is one thread |
| 2 | Crop-cache passes gain little; the gain lives in video passes | The two disagree. The plan said half right: ally_icon dominates crop-cache passes, the HUD pass splits evenly between cache reads and its reader, and the largest overlap gains lie in video passes with a heavy reader (`composite_summary`). The baseline document said refuted: the gain follows the balance of source and reader time, not the source kind, so hud from the cache gains most and the video crop-cache write little | Refuted: the crop-cache HUD pass gained, and the video prefix lost |
| 3 | One reader dominates at a fixed per-call cost, so batching its calls helps | Its second half fails in both: ally_icon dominates, but its cost scales with pixels, and the scoreboard pays a whole-frame colour conversion before it checks for an open board (`per_pixel`). Batching helps neither | Not tested; ally_icon reaches about three cores on either path, which points at fewer operations per pixel |
| 4 | The transport is not the cost | Untested; `groups.*.retrieved_fps` bounds the message rate | Held: the staged HUD pass ran close to its reader sum, which bounds threads, queues and handoffs together |

The later measurements refute prediction 2 whichever baseline verdict one reads.

## 1. Model

One process per scan: a producer thread decodes (or reads the crop cache), selects and converts frames;
each reader runs on a thread behind its own FIFO; a publisher stages streams and commits the run.

| | A: frame or tile to reader | B: reader to L1 stream | C: L1 to adjudication | D: adjudication to event |
|---|---|---|---|---|
| Topic | `frames/<sid>`: one message per retrieved frame; on video each reader subscribes with its `hz` and `spans`; on the crop cache `want` is `run_cached`'s span filter and nothing thins | `stream/<sid>/<name>`: rows, then one end message | `runs`: one message per committed run | `events/<kind>/<sid>` |
| Partition key | session; a sharded pure reader takes frame i on shard i mod K | (session, stream) | session | (session, kind); `event_id` or `death_key` within |
| Message fields | session_id, content_key, profile, source (`video` or `cache:<version>`), frame_idx, observation t_ms, wanting readers, the read-only BGR frame (for tiles, crops pasted into black), prelude results | an observation row with its key, t_ms, stamp and reasons; the end message carries the coverage head, frames offered and `frames_from` | run_id, session, code revision; per file its stamp, sha256 and rows; the inputs read | `events.Event` (map section 4D) |
| Ordering | increasing t_ms per subscriber; a merge restores producer order after shards and keeps each shard's order within a frame | frame order within a stream; end message last | dependency order: rounds, then deaths, then combat-report identity and round entities; tray before shapes; minimap_dark before smokes | none required; consumers upsert by key |
| Consumer state | the reader's own (map section 2); stateful and accumulating readers keep one FIFO worker | the stager holds a stream whole, since tables are replaced whole | each adjudicator's recorded input stamps | none beyond the key |
| Idempotence | decode is deterministic per content_key and backend; a repeated frame_idx is refused | a retried run stages the same bytes | a run record is immutable and names its files by hash | deterministic keys |
| Durability | memory only; a tile turns durable only as a `roi_cache` entry, a lossless crop of a fixed profile ROI | a staging directory, then an atomic commit into the store | `runs/<run_id>.json` and the append-only `notes/runs.jsonl` | the store's events files |
| Transport | a bounded `queue.Queue` of references; shared-memory tiles if a shard moves to a process | an in-process handoff to the publisher thread | a file consumers read; `plan` reads it too | the store |
| Why | frames are capture pixels: a durable topic would copy raw media and cost more than the decode | a row log adds nothing to a stream that is replaced whole | the record is both the "published at stamp V" notice and the proof that the run finished | keys make delivery order irrelevant |

**No seam warrants Kafka.** Seam A carries at most
`G[killfeed_portrait/cache/match/b1].retrieved_fps.max` 144.2 frames a second within one process, where a
queue of references costs nothing and a broker would copy pixels. Seams B to D have one writer per
session, and their consumers read whole streams after the pass from a durable, replayable store; a broker
would be a second log that can disagree with the first. Three observations would change this: processes
or hosts reading one session's L1 rows during the scan at their own offsets; a consumer that must survive
its restart mid-match without a rescan; run-record polling too slow for a live consumer. The broker would
then sit at seam D's edge, fed from committed runs, outside `reticle/`.

**Stamps and provenance.** The staged pass drives the same reader objects, so every row keeps its stamp
and `frames_from`; no definition moved, so no stamp moves. Execution facts (pipeline, workers, shards,
backend, revision) go to the usage and run records, never into rows or schema metadata. Stream bytes
therefore stay identical, consumers that hash their inputs, such as `lifetimes` (cli.py:1897-1903), see
no change, and acceptance is byte equality of every staged file between the serial and staged paths.

**The cache path does not re-thin.** `cache_for` has already matched every reader's rate to the cache's
(roi_cache.py:143), and `--from cache` has clipped each reader's spans to the cache's rounds
(cli.py:1002-1006); a `next_t` reset at a clipped span's start would pick other frames than the serial
pass. On a cache source `want` is therefore `run_cached`'s rule, the span filter alone
(passes.py:199-208), and the dispatcher never thins. The pipeline sets `frames_from` from the chosen
source before it copies a reader into shards, as `run_cached` sets it (passes.py:197), because the
killfeed reader writes it into three streams (killfeed.py:1996-2046).

**No failure deadlocks.** A full FIFO blocks the dispatcher rather than drop a frame, but never forever:
it puts with a timeout and a stop event, as `_NvdecCapture._produce` does (decode.py:112-131), and checks
between tries that every worker lives. A worker that raises sets the stop event; the dispatcher closes
the source, joins the workers and ends the run with that exception in the usage record's `status`. The
dispatcher counts frames offered per reader against frames fed, and a mismatch fails the run before any
write. A lost message therefore fails the run instead of writing a refusal; the reason lands in `status`.
Each reader or shard has a FIFO of 8 frames. A frame lives while any FIFO or worker holds it, so with T
worker threads, one per reader or shard, at most 1 + 9 T frames live beside the source's own read-ahead
(L1's 32 wanted frames on video, none on the cache path), 6.2 MB each at 1920x1080 (1920 x 1080 x 3
bytes; profiles.py:267-273), and NVDEC holds its 16 device frames on the GPU (decode.py:36-37). Readers
that want the same frame share it.

## 2. Performance model

Today a pass costs decode plus the sum of reader times. With decode on its own thread, reader r in K_r
shards and W cores for readers, a pass takes at least `max(decode, max_r T_r / K_r, sum_r T_r / W)`.

**The ladder on a06f04a0059f** (38.7 min, `C[a06f04a0059f].vod_min`; the five `core` readers; `decode_s`
173.9, `readers.scoreboard.s` 220.8, `readers.ally_icon.s` 391.3):

The last column records what the measurements found on c40d950031bb; nobody reran a06f.

| Step | Pass bound | Speedup | Keys and arithmetic | Outcome |
|---|---|---|---|---|
| Serial today | 848.1 s | 1 | `core.serial_s` | not rerun |
| L1: decode overlaps readers | 674.2 s | 1.258 | `core.overlap_bound_s`, `core.overlap_speedup` | crop cache: 1.80 on the HUD pass at one worker (m2); NVDEC video: refuted, since the read-ahead already hides about half of each 2 Hz gap, so this row overstates the gain |
| L3: a thread per reader, free cores or W = 3 | 391.3 s | 2.168 | `core.parallel_bound_s`, `core.parallel_speedup`; max(391.3, 674.2 / 3) | the HUD pair at two workers did not run |
| + ally_icon in two shards (upper bound) | 224.7 s | at most 3.77 | max(173.9, 220.8, 391.3 / 2, 674.2 / 3) | refuted by its falsifier: 1.05 (m3), against the serial pool rather than one thread |
| + L5, if closed boards cost 40.1 to 158.0 s | 195.6 to 211.4 s | 4.0 to 4.3 | reader sum 516.2 to 634.1 s, over W = 3 | unbuilt |
| + three shards at W = 4 | toward 173.9 s | up to 4.88 | `decode_s`; 2321 s of video in 173.9 s is 13.3x real time | three shards at W = 3 gave 1.19 (m4), against the pool |

The corpus agrees (`S.overlap_speedup.median` 1.269, `S.parallel_speedup.median` 2.168; ally_icon
heaviest on 17 of 19 sessions, `S.heaviest`). Four caveats bound the table. The ally-icon figure ran
beside seven other scans (`C[a06f04a0059f].readers.ally_icon.concurrent`) at 20778 feeds (the sum of
`R[a06f04a0059f 07:10:33Z].heaviest_buckets`), about nine a second over 2321 s, against a default
`ALLY_DESCRIPTOR_HZ` of 2 Hz (minimap.py:1119). The decode figure predates NVDEC
(`G[roi_cache:minimap/video/match/b1].after_nvdec_commit` is `[false]`). Ping, roster, lineup,
minimap_dark and combat_report have no records. W is what the player grants beside his own jobs.

**The shard row rests on a contended figure.** 391.3 s is the lower of two contended a06f records, beside
seven and eight other scans (`R[a06f04a0059f 07:10:33Z]`, `R[a06f04a0059f 02:32:21Z]`); on c40d the
reader cost 9.61 ms a call alone (`R[c40d950031bb 06:34:24Z].heaviest_ms_per_call`) against 23.08
beside five (`R[c40d950031bb 02:35:45Z]`). If uncontended ally_icon halves, the floor is the scoreboard's
220.8 s and two shards buy nothing on a06f. Step 3's serial ally_icon gates step 2's sharding claim.

### L1. Decode overlaps the readers

- **Mechanism.** The staged pipeline, as built, takes the source off the reader threads: its dispatcher
  thread runs today's `sample_multi` (decode.py:461-560), with its selection and `retrieve` (NV12
  download, plane split, swscale; decode.py:165-180), or `RoiCache.samples`, and queues each wanted
  frame into its readers' FIFOs, 8 deep, while they feed on their own threads (section 1). At W = 1 no
  two readers feed at once, so a staged pass at W = 1 against the serial one isolates this overlap from
  L3; step 4 runs that test on video.
- **Prediction.** a06f: 848.1 to 674.2 s. Lone passes gain
  `G[scoreboard/video/match/b1].speedup_overlap.median` 1.736 on video and
  `G[hud/cache/match/b1].speedup_overlap.median` 1.979 from the crop cache.
- **Constraints.** `frame_idx` counts grabs; `next_t` advances only after a successful retrieve
  (decode.py:551-556); one dispatcher feeds every FIFO in producer order.
- **Falsifier, step 4** (at most 180 s of video a path). `scan --only hud scoreboard --from video
  --until S` on c40d950031bb, serial and staged at W = 1: files byte-equal. Falsified if the staged pass
  shrinks by less than half the smaller of the serial source and reader times (the serial path's
  `source_s`, and the sum of its `feed_s_<reader>`). The staged path feeds at one OpenCV thread and the
  serial one on the default pool (L3), so the test errs against L1; a miss is read against step 4's
  one-thread scoreboard figure.
- **A further lever, unbuilt: the `_Selector`.** Move `sample_multi`'s selection into a `_Selector`
  shared with the NVDEC producer thread (decode.py:112). The producer grabs every frame, drops unwanted
  ones on the device, runs `retrieve` on wanted ones and queues `(want, Sample)`: 32 wanted frames cover
  16 s at 2 Hz in about 200 MB, where today's 16 raw frames (`_NVDEC_AHEAD`, decode.py:37) span half the
  30-frame gap between 2 Hz samples of a 60 fps capture. `RoiCache.samples` would move there too. The
  selector must see every grabbed frame in order, and one queue feeds the dispatcher. It takes
  conversion off the dispatcher, so it can shorten only a pass the source paces. **Falsifier, no new
  video:** step 4's staged record. If the dispatcher blocked on full FIFOs for a tenth of the pass or
  more (`dispatcher_wait_s` against `pass_s`), the readers set the pace and the selector stays unbuilt;
  otherwise the producer's timers (open question 1) bound what it can save.

### L2. Convert ROI windows, not the frame

- **Mechanism.** On NVDEC, when every reader wanting a frame declares a `cache_set`, convert only the
  union of their ROIs (`CACHE_SETS`, roi_cache.py:45-55), each window aligned to even coordinates and
  padded past swscale's chroma filter, and paste them into a black frame as `RoiCache.samples` does
  (roi_cache.py:307-316); readers run unchanged under the crop cache's contract. Most retrieved frames
  want only the minimap: on a06f ally_icon took 20778 feeds, the scoreboard 4643
  (`R[a06f04a0059f 09:52:39Z].frames`). Minimap, ping and minimap_dark must first declare the `minimap`
  set (finding 9). Conversion, a pure function of one frame, keeps every ordering.
- **Prediction.** No wall change while L1 hides decode; then less producer CPU and a lower floor once L3
  makes the pass decode-bound, by an unknown amount: usage cannot split conversion from decode wait
  (usage.py:59-67).
- **Falsifier, no video.** Random yuv420p planes through PyAV's reformatter: each padded window must
  equal the same window of the full conversion byte for byte, or L2 is dropped. Time both.
- **Untested on video.** With every default reader the path never fires: the scoreboard, roster,
  lineup, combat_report, minimap, ping and minimap_dark declare no `cache_set` (cli.py:939-977; finding
  9), and step 4's scoreboard wants every frame its HUD readers want, at their rate and span. L2 leaves
  step 4 and rests on its no-video falsifier until those readers declare their sets (section 6).

### L3. Readers run concurrently

- **Mechanism.** Each subscriber gets a thread behind a bounded FIFO; `--workers W` caps concurrent feeds
  with a semaphore, W = 1 exercising queues, shards and merge on one core, W = 0 running inline. A pure
  reader may shard: the pipeline copies it with emptied output lists, feeds frame i to shard i mod K and
  merges each declared list by the frame's producer position at finish, keeping each shard's order
  within a frame. `revision` hashes canonical JSON with lists in order (candidate_evidence.py:26-31),
  and `feed` appends self candidates before ally ones by raw index (minimap.py:1231-1290), so a sort by
  key would change the revision id. This is `shardable`'s contract. Frames are read-only
  (`setflags(write=False)`), so a write into one fails at once. OpenCV's thread count is set once per run
  and recorded; `_feed` toggles a process-wide count per reader (passes.py:221-247), which races under
  threads.
- **Threads or processes.** Threads first: they share frames without a copy, and OpenCV and large numpy
  calls release the GIL. A reader moves to process shards only when its measured GIL share caps its
  shards; then only its ROI tiles cross, through shared memory.

| Reader | Work per call | GIL held | Plan |
|---|---|---|---|
| ally_icon | masks, morphology, components and cvtColor on the minimap crop; a Python loop over components and candidate dicts (minimap.py:909, 1195-1291) | medium | threads, sharded; processes if its GIL share exceeds 1/K |
| scoreboard | whole-frame HSV and numpy masks (scoreboard.py:132-139); a row loop in `_block`; digit templates; cupy portraits | low | thread |
| hud, killfeed_portrait | small OCR crops, template matches, a band loop and descriptors in Python glue (hud_reader.py:70-95, killfeed.py:1938-1971) | high | a thread each; cheap |
| minimap, ping | ring fits and `pick_self` state (cli.py:499-556); HSV, components and a pure-Python `Grouper` (ping.py:311-341, 430-445) | medium to high | one FIFO thread each |
| minimap_dark, combat_report | numpy masks; whole-frame gray and a header search (minimap_dark.py:77-90, combat_report.py:244-254) | low | thread |
| roster, lineup, roi_cache writer | a Laplacian of the bars; the top bar at 0.1 Hz; pipe writes | small | one FIFO thread each |

- **The ally-icon pool.** ally_icon declares no `cv_threads`, so it runs on OpenCV's default pool, where
  contention lands: 7010b3d62460 took 478.6 s alone (`R[7010b3d62460 05:17:10Z].readers_s`) and 715.7 s
  beside eight scans (`R[7010b3d62460 07:05:55Z].readers_s`), and cost follows pixels
  (`per_pixel["ally_icon/cache/match/b3"].reader_ratio` 2.375 against `meta.pixel_ratio_bigmap_over_std`
  2.071). Each shard therefore gets one OpenCV thread; parallelism comes from shards. Every staged
  pass at W >= 1 runs at one OpenCV thread (`STAGED_CV_THREADS`, pipeline.py:91), set once and restored
  after; at W = 0 it keeps `_feed`'s per-reader toggles and the default pool, as the serial pass does.
  The scoreboard and ally_icon were timed on the default pool, and `_feed` reports wall up 0-42% at one
  thread (passes.py:229-235), so this count moves the ladder's T_r. Step 3 measures ally_icon at one
  thread from the crop cache; the scoreboard reads no crop cache, so step 4's staged path measures it.
- **Shared module state.** Two lazily filled module dicts are read across threads: `_ME_CACHE`
  (killfeed.py:766-799) by the hud and portrait threads, and `_REG` (ally_portrait.py:85-92) by every
  ally_icon shard. Each fills with a deterministic value, so a race computes it twice and changes
  nothing.
- **Prediction and constraints.** 391.3 s on a06f with free cores, lower only through shards. Stateful
  readers (minimap, ping, the roi_cache writer) and accumulating ones (lineup, whose float sums depend on
  order) keep one FIFO worker; only pure readers shard.
- **Falsifier, no video.** c40d950031bb from its crop caches, {hud, killfeed_portrait} and {ally_icon},
  serial against staged, bytes equal. Predict at least 1.5x on the pair (its one record bounds it at
  2.8x, `G[hud+killfeed_portrait/cache/match/b1].gain_parallel_frac_wall` 0.646) and 1.6x on ally_icon in
  two shards; falsified below 1.2x. GIL share: two instances in two threads against one.

### L4. Shared per-frame results

- **Mechanism.** A prelude computes a result once per frame, before its consumers see it:
  `killfeed_views` for the HUD (`read_killfeed`, killfeed.py:2085) and the portrait reader
  (killfeed.py:1942); `widget_drawn` for the minimap readers, whose `sgray` and `floor` agree
  (cli.py:516, minimap.py:1199, minimap_dark.py:84, ping.py:435). The killfeed calls agree already:
  `mask_prefix` only caches a cumsum (killfeed.py:686-691), and `EntryView` is frozen (killfeed.py:1075).
- **Prediction.** One `analyse_killfeed` fewer per 2 Hz frame: at most 20.2 s of CPU on a06f
  (`C[a06f04a0059f].readers.hud.s`) and no wall change at the parallel bound, since neither reader is the
  slowest. The widget check saves less; unmeasured.
- **Falsifier, no video.** Time `analyse_killfeed` alone over c40d's cached killfeed crops; the hud table
  and the three killfeed streams stay byte-equal with shared views.

### L5. A cheap open-board gate

- **Mechanism.** `read_scoreboard` builds both slab masks from a whole-frame HSV and three int16 copies
  (scoreboard.py:132-139) before it looks for the ally block (scoreboard.py:228-231). Build green with
  one `cv2.inRange` (the strict integer bounds made inclusive: H 56-99, S 19-255, V 46-255), test
  `_block(green)`, and build red and the highlight only when the ally block exists. The masks stay the
  same and turn lazy; no ordering constraint applies.
- **Prediction.** The a06f scoreboard made 4013 calls of 10-50 ms, 5 of 50-100 ms and 625 of 100 ms or
  more (`R[a06f04a0059f 09:52:39Z].heaviest_buckets`). If the tail is the open board, closed frames cost
  40.1 s (4013 x 10 ms) to 158.0 s (220.8 - 625 x 0.1 - 5 x 0.05), most of which the gate removes.
- **Falsifier.** No video: old and new masks equal on random frames, and the time per closed call. Then
  L1's prefix, chosen from stored rows to hold an open board, keeps its rows byte-equal.

### L6. Streaming, atomic per-run publish

Deferred past step 2 (section 6): `--check` needs two temporary `Store`s and today's writers, not
staging, run records or roll-forward. Finding 1 stays filed.

- **Mechanism.** Each finished stream goes to the publisher thread, which writes it to
  `<store>/staging/<run_id>/` while other readers run. With every stream staged, it writes
  `runs/<run_id>.json` (status `staged`; files, sha256, rows, stamps, inputs, revision, and the hash each
  file replaces), moves each into place with `os.replace`, marks the record `committed` and appends it to
  `notes/runs.jsonl`. A run left `staged` rolls forward at the next start; no rescan overwrites evidence
  silently. Candidates commit first, then decisions, then `ally_icon` events, then the run record.
- **Prediction.** Correctness first. Only the part of the ally-icon chain that can start before the other
  readers end leaves the tail. The chain took 30.9 s on a06f (`R[a06f04a0059f 07:10:33Z].publish_s`) and
  9.7 to 124.5 s across its batch (`G[ally_icon/cache/match/b3].publish_s` min and max); it serializes
  and re-parses the candidate document twice (store.py:52-131, cli.py:1063-1087).
- **Falsifier, no video.** Replay the chain from c40d's stored candidate revision into a temporary store,
  timed per step; a unit test kills the run between stage and commit and checks roll-forward.

### L7. One scheduler, one decode at a time

- **Mechanism.** `scan` over a list of sessions in one process: one producer at a time, one pool of W
  reader threads at Idle priority, shards filling the cores a session's reader mix leaves idle. The next
  producer starts when the current reader queues have room, so its decode overlaps the tail.
- **Evidence.** Two or three concurrent video scans raised the scoreboard's wait per frame from 35.5 to
  59.9 ms (`G[scoreboard/video/match/b1]` and `b2`, `source_ms_per_frame.median`) while its reader cost
  held at 47.6 and 44.3 ms (`heaviest_ms_per_call.median`): decodes contend. Yet concurrency paid in
  throughput (`wall_sum_min` against `elapsed_min`): 179.0 against 48.6 min for
  `B[ally_icon/cache/match/b3]`, 117.1 against 61.2 for `B[scoreboard/video/match/b2]`.
- **Prediction and falsifier.** At W = 4, corpus elapsed no worse than those batches, with uncontended
  records. Without video: three sessions from their crop caches under the scheduler against three
  concurrent `scan` processes, comparing elapsed and per-reader busy time. It loads the CPU, so it waits
  for the player's go-ahead; the decode half needs two demo clips of a few seconds each.

### The real-time budget

A live path must read a second of video in under a second on the cores it holds. On a06f the five
measured readers need 0.365 s per video second in series (1 / `core.x_realtime_serial` 2.737) and 0.169 s
at the parallel bound (1 / `core.x_realtime_parallel_bound` 5.933), but the mean hides the rounds:
ally_icon at 15 x 18.83 ms (`R[a06f04a0059f 07:10:33Z].heaviest_ms_per_call`), minimap at 15 x 7.0 ms
(`G[minimap/video/match/b1].heaviest_ms_per_call.max`) and the scoreboard at 2 x 47.55 ms
(`R[a06f04a0059f 09:52:39Z].heaviest_ms_per_call`) take 0.48 s of one core per live second, before
decode, conversion, hud, the killfeed and the unmeasured ping (10 Hz), minimap_dark (4 Hz), combat_report
(1 Hz, whole frame), roster (2 Hz) and lineup. A 32-frame queue at 15 Hz holds two seconds, so a live
path wants a depth of 8 or less. Finish-time work yields nothing until the end (ping's `Grouper`,
ping.py:447; the lineup verdict, lineup.py:396; the ally-icon decisions, cli.py:1063; every
adjudication), and a live path needs incremental forms this branch does not build.

## 3. Prototype

The largest lever is L3 with shards, and the crop cache tests it cheapest: no decode, the real readers,
and ally_icon, the reader that sets the bound. L1 comes with it, since crop decode moves to the producer.
L1 on video follows on one short prefix; L2 rests on its no-video falsifier.

| Module | Layer (`architecture.toml`) | `ownership.toml` | Role |
|---|---|---|---|
| `reticle/pipeline.py` | orchestration | `[infrastructure]` | topics (a bounded in-process queue behind an interface a shared-memory tile topic can replace), dispatcher, subscriber threads, shards and merge, preludes, read-only frames; `run_staged(ctx, readers, source, workers, shards, usage)` returns each reader's finish result. Readers gain `shardable` and a list of the outputs a merge combines |
| `reticle/publish.py` (deferred, L6) | source | a new entry, `scan-run`: "Which run wrote this stored stream, and did that run finish?"; produces `PUBLISH_VERSION`, `Stager`, `commit`, `recover`, `run_of`; `not_for` staleness (plan's), observations and names | staging, run record, commit, roll-forward |
| `reticle/decode.py` | source | `[infrastructure]`, as now | `_Selector` out of `sample_multi`; the selecting, converting producer; ROI conversion |
| `reticle/usage.py` | foundation | `[infrastructure]`, as now | `scan-usage-2` |
| `reticle/cli.py` | delivery | none | `scan --pipeline {serial,staged} --workers W --shard READER=K --until SECONDS --check`; the publish block (cli.py:1029-1180) becomes `_publish_scan(out_store, ...)`, and the ally-icon chain stays in `cli` as a callback, so `pipeline` imports nothing above its layer. `cmd_scan` reaches both new modules (UNWIRED, UNCALLED); no new name repeats a `prototypes/` one (DUPLICATE) |

**Steps.** Each is one Idle-priority process with OMP, MKL and OpenBLAS at one thread, beside nothing
heavy of ours; W = 1 may keep two threads busy, W = 0 one. Nothing reaches the real store before steps 1,
2 and 4 pass; `serial` stays the default until the player says otherwise.

0. **Unit tests, no store.** `tests/test_pipeline.py`: synthetic readers; staged at W = 0 to 4 equals
   serial; stateful readers see increasing t_ms; the cache path never thins; shard merges equal serial
   lists and keep the revision id; a reader's exception ends the run with it in `status` and no hang; a
   write into a frame raises; the FIFO stays bounded; queue round trips far outpace
   `G[killfeed_portrait/cache/match/b1].retrieved_fps.max` 144.2 a second (the plan's fourth prediction).
   `tests/test_decode.py`: through a mocked capture with a failed retrieve and span resets, `_Selector`
   chooses what `sample_multi` chooses. Accept: the suite passes and `doctor` adds no ERROR.
   `tests/test_publish.py` left with L6.
1. **Crop cache, hud and killfeed_portrait, c40d950031bb** (16.2 min, `C[c40d950031bb].vod_min`; core
   readers but the scoreboard recorded alone, `C[c40d950031bb].readers`):
   `reticle scan c40d950031bb --only hud --from cache --pipeline staged --workers 1 --check`, then W = 0.
   Accept: staged files byte-equal. `--check` implies `--force` and refuses without the stored killfeed
   mask, which `HudReader` would seek to rebuild (hud_reader.py:40-60).
2. **Crop cache, ally_icon, same session:** `--only ally_icon --ally-hz 15 --shard ally_icon=2`. Accept:
   the same candidate revision id (a content address), and byte-equal decisions and events. 2a: five
   minutes of cached crops at OpenCV's default pool and at one thread give equal revision ids, or the
   finding is filed before step 3. Concurrency correctness runs at W = 2 on those five minutes.
3. **Timing from the crop cache, c40d950031bb,** once the player grants cores; W = 3 keeps up to four
   threads busy. The runs, one at a time:

   ```
   reticle scan c40d950031bb --only hud --from cache --pipeline staged --workers 0 --force
   reticle scan c40d950031bb --only hud --from cache --pipeline staged --workers 1 --force
   reticle scan c40d950031bb --only ally_icon --ally-hz 15 --from cache --pipeline serial --cv-threads 1 --force
   reticle scan c40d950031bb --only ally_icon --ally-hz 15 --from cache --pipeline staged --workers 2 --shard ally_icon=2 --force
   reticle scan c40d950031bb --only ally_icon --ally-hz 15 --from cache --pipeline staged --workers 3 --shard ally_icon=3 --check --check-dir DIR
   reticle scan c40d950031bb --only ally_icon --ally-hz 15 --from cache --pipeline staged --workers 3 --shard ally_icon=3 --force
   ```

   The HUD pair, ally_icon at one OpenCV thread and ally_icon in two shards write only files that steps
   1, 2 and 2a found byte-equal to the store's own copies; three shards are unproven, so that
   configuration passes `--check` before it runs in the store. The runs publish into the store because
   QUOTED reads only `<store>/notes/metrics.jsonl`, so the rule above holds them until step 4 passes,
   unless the player lifts it for these files. Compare against lone records `R[c40d950031bb 06:34:24Z]`
   (ally_icon, readers 74.3 s), `R[c40d950031bb 19:08:23Z]` (hud, 8.7 s) and
   `R[c40d950031bb 12:11:54Z]` (killfeed_portrait, 8.0 s). A serial miss measures code drift first. The
   scoreboard at one OpenCV thread needs video, so step 4 measures it.

   **Reading rule for the GIL.** For a staged reader, `thread_cpu_s_<reader>` against `feed_s_<reader>`:
   near equal, its threads computed through their feeds; far below, they waited in `feed`, for the GIL
   or a core. For the pass, `cpu_s` against `pass_s`: near 1 at W >= 2 means the workers took turns, and
   near the count of busy threads means they ran at once; a reader whose added shards leave the pass near
   1 holds the GIL and moves to process shards (L3). A serial pass, or one at W = 0, charges all its CPU
   to the dispatcher (`dispatcher_cpu_s`). Windows counts CPU in clock ticks, so a figure of a few ticks
   says little. The figures stay in the usage and metrics records; this document quotes one only
   through its token, `[metric:scan_usage/<part>@c40d950031bb#<field>=<value>]`, whose part names the
   readers, source, pipeline, workers, shards and OpenCV count (`ally_icon/cache/staged/w2/ally_icon=2/cv1`;
   usage.py).
4. **Video, c40d950031bb:** `--only hud scoreboard` (hud, killfeed_portrait and the scoreboard) over the
   shortest prefix, at most 180 s, that stored tables say holds an open board and a killfeed entry, on
   two paths over the same frames: serial `passes.run`, and staged at W = 1 with today's `sample_multi`
   as its source (L1):

   ```
   reticle scan c40d950031bb --only hud scoreboard --from video --until S --pipeline staged --workers 1 --check --check-dir DIR
   ```

   The scoreboard runs on a prefix as on the whole capture: it keeps no state across frames and has no
   finish (scoreboard.py:535-577), so its rows before the limit are the whole pass's, and it carries L1's
   video prediction. At most 360 s of video in all, on NVDEC when the player's jobs leave it free.
   `--until` takes seconds, refuses to run without `--check` and `--check-dir`, and ends the decode at
   the limit (`pipeline.limit_to_prefix`). Accept: byte-equal files, and each path's usage record with
   its `until_s`. The staged path feeds at one OpenCV thread (L3); critique 6's scoreboard serial at that
   count needs video, so it folds into this prefix instead of a third decode: the staged path's
   `feed_s_scoreboard` against the serial path's, over the same frames, is its cost at one thread, read
   by step 3's rule.

**The equality test.** The design had `--check` build the readers twice against the real store's
inputs, run path A (today's `passes.run` or `run_cached`, untouched) and path B (`pipeline.run_staged`),
publish each through `_publish_scan` into its own temporary `Store`, and compare the trees by relative
path and sha256, printing the first differing observation key or Parquet column, as `trial.diff` and
`trial.diff_table` do. As built, no `_publish_scan` exists (Status); each path runs today's publish block
into its own store:

    python -m reticle scan <session> --only <readers> --from cache \
        --pipeline staged --workers N [--shard NAME=K] --check [--check-dir DIR]

`--check` runs the requested pass into `DIR/b`, then today's serial pass into `DIR/a`, two fresh stores,
and compares every file they write (`pipeline.compare_trees`): bytes, then Parquet rows when bytes
differ, naming the first column and row, or the first JSONL line, where two files part. It exits 0 only
when the paths wrote at least one file and every file is byte-equal. Both paths read the store and write
nothing there, each keeping its usage and metric rows in its own `notes/`. Path a takes no `--cv-threads`
and runs on OpenCV's default pool. The check refuses two paths that are the same serial pass,
`--cache-roi`, and, with no stored killfeed mask, HUD readers, which would decode to measure one. It does
not force `--from cache`; without it both paths decode.

**Usage record `scan-usage-2`, as proposed,** adds `code_revision` (HEAD, dirty flag), `pipeline`,
`transport`, `decode_backend` (`nvdec`, `opencv`, `cache`), `threads` (W, shards, the OpenCV, OMP, MKL and
OpenBLAS counts), `process_cpu_ns`, each thread's `thread_cpu_ns`, the producer's `decode_ns`, `convert_ns` and
`stall_ns`, the dispatcher's `wait_ns`, each reader's `busy_ns` and `wait_ns`, `overlap` (busy over pass
time), each stream's `stage_ns`, `commit_ns`, `priority`, `concurrent_scans` (from a registry of running
scans) and `status`, written on failure too. Each completed scan also appends a `pass` row to
`notes/metrics.jsonl` naming its usage `run_id`, so QUOTED can cite the measure phase. Shipped:
`code_revision`, `pipeline`, the W, shard and OpenCV counts (as `workers`, `shards` and `cv_threads`),
process CPU (as `cpu_ns`), each thread's `thread_cpu_ns`, the dispatcher's `wait_ns`, each shard's
`busy_ns`, `status` with `error`, and the `pass` row. The rest never shipped (Status).

## 4. Findings

| # | Finding | Severity | Evidence | Fix | Prototype |
|---|---|---|---|---|---|
| 1 | Publish writes in place, not atomically, without a run id; a failure mid-publish leaves mixed versions and no usage record | High | `pq.write_table` on the final path (store.py:249, 381, 486, 543) and `open(path, "w")` (store.py:697); cli.py:1054 exits after the HUD and killfeed streams are written; usage is written last (cli.py:1180) and always says `completed` (usage.py:93) | L6 | compares in temporary stores; L6 deferred |
| 2 | A truncated JSONL stream reads as current | High | `write_events` writes the head row first (store.py:697-699); `events_version` trusts that row (store.py:702-717); `scan` skips a stream at the current stamp (cli.py:844-880), and `plan` agrees (plan.py:71-79) | atomic replace; check rows and sha256 against the run record | yes |
| 3 | Readers run in frozenset order, which string-hash salting changes per process | Medium | passes.py:171; harmless only while no reader writes the frame or shares state, and nothing enforces that | declared order; read-only frames | yes |
| 4 | Lineup and ping finish twice | Low | passes.py:176-182, then cli.py:1090 and 1155; the second lineup finish reruns the arbiter (lineup.py:410), billed to `publish_ns` | `run` returns finish results | yes |
| 5 | `plan.stale` knows two derived streams and no lineup | Medium | plan.py:82-130 checks rounds and deaths; `reader_streams` omits the lineup (plan.py:51-68); smokes, combat-report rounds, round entities, tray and shapes check themselves (map section 3) | derived stages declare their inputs; `plan` reads run records | no |
| 6 | `lifetimes` rebuilds rounds from the HUD and hashes too few inputs | Medium | cli.py:1915 calls `build_rounds` without second-life rows (rounds.py:440); the input hash covers lineup, scoreboard and death (cli.py:1897-1903), not the HUD or roster it reads, so their rescan leaves round entities current | read `l2/rounds`; hash every input | no |
| 7 | Usage records lack backend, revision, CPU and contention, and cannot split conversion from decode wait | High for this work | usage.py:59-67, 84-106; `after_nvdec_commit` in every group is an inference; `concurrent_records` sees only recorded scans | `scan-usage-2` and a metrics row | yes |
| 8 | `plan` labels an ally-icon change `decode` | Low | no trial for ally_icon (plan.py:65, 152), yet `scan` feeds it from the minimap cache (cli.py:958-959, roi_cache.py:118) | ask `roi_cache` whether a stored cache fits the channel | no |
| 9 | The roster reader declares no `cache_set`, and an unnarrowed scan adds it and the lineup, so a default reread always decodes; minimap, ping and minimap_dark read only the minimap box yet declare none either | Medium | roster.py:307-333, with its ROIs in `CACHE_SETS["hud"]` (roi_cache.py:49-50); cli.py:833-839; cli.py:499-501, ping.py:430-433, minimap_dark.py:77-79 | declare the `hud` and `minimap` sets after equality checks from those caches | no; step 1's harness can run the checks, and L2 needs them |
| 10 | The lineup reader runs the identity arbiter inside the scan | Medium | lineup.py:396-411; cli.py:1088-1095 stores the verdict beside `scores` | store scores and claims; arbitrate from storage | no |
| 11 | QUOTED cannot cite usage records | Medium | the baseline and this design cite JSON keys that `doctor` never checks | a metrics row per scan, or a usage token | yes (the row) |
| 12 | OpenCV's thread count is process-wide and toggled per reader | Medium | passes.py:221-247; under threads the toggle races, and an output that depends on the count varies by machine | one count per run, recorded, with step 2a's invariance test | yes |
| 13 | The composite mixes rates, backends and contention | Medium | ally_icon at about nine feeds a second (20778, `R[a06f04a0059f 07:10:33Z].heaviest_buckets`) against a 2 Hz default (minimap.py:1119); seven concurrent scans; decode before NVDEC (`G[roi_cache:minimap/video/match/b1].after_nvdec_commit`) | name rate and backend per composite reader; one uncontended fused scan per profile | no |
| 14 | The killfeed mask calibration exists twice; its file is unstamped and written in place | Low | passes.py:96-126 and hud_reader.py:40-60 each seek 40 times; store.py:403-407 | one owner, an atomic write, a stamp | no; `--check` refuses without the mask |
| 15 | The crop cache allocates a full black frame per sample | Low | roi_cache.py:309, 327; crop decode and paste take half of a hud reread (`G[hud/cache/match/b1].share_source.median` 0.502) | a ring of reused frames, as deep as the frames in flight | measured by producer timers |
| 16 | This OpenCV build defaults to 12 threads: serial passes record 12 in `cv_threads`, staged passes at one worker or more record 1, so the two paths compare across counts | Medium | the usage rows of steps 1 and 2; measurements, answer 1 | compare at one count (Status, open work 1) | recorded per pass |
| 17 | Other jobs write `notes/metrics.jsonl`, `notes/usage.jsonl` and a session's `l1/minimap` during the day, so a proof that the store did not change must say whose rows moved | Low | the store's listings before step 1 and after step 2a | name the writer of every moved row | by hand |

## 5. Open questions

| # | Question | Cheapest experiment |
|---|---|---|
| 1 | How much NVDEC source time is conversion, how much wait? | the producer's timers over step 4's prefix |
| 2 | Is the scoreboard's slowest bucket the open board? | its 630 calls of 50 ms or more (`R[a06f04a0059f 09:52:39Z].heaviest_buckets`) against `frames_open` in a06f's stored scoreboard coverage row; no compute |
| 3 | Which parallel framework does this OpenCV build use, and do concurrent `parallel_for` calls serialize? | `cv2.getBuildInformation()`; no compute |
| 4 | Does PyAV release the GIL in `decode` and `reformat`? | the producer alone and beside a pure-Python spinner, over L1's prefix |
| 5 | What is the NVDEC decode floor per match? | frames per second from step 4's timers; a whole-match decode-only pass only if they disagree with `C[a06f04a0059f].decode_s` |
| 6 | How far has code drifted from the lone baselines? | step 3's serial run against `R[c40d950031bb 06:34:24Z]` |
| 7 | Does a padded window convert exactly as the full frame does? | L2's falsifier; no video |
| 8 | What share of each reader's time holds the GIL? | L3's falsifier; no video |
| 9 | Does any reader's output depend on OpenCV's thread count? | step 2a; no video |
| 10 | Where do the ally-icon chain's seconds go? | L6's falsifier; no video, no reader |

## 6. Critique outcomes

A separate critic read this design against the code. The verdict: go for steps 0 to 2 after changes 1,
3, 4, 5 and 7; changes 2 and 6 before steps 3 and 4.

| # | Finding | Change made | When |
|---|---|---|---|
| 1 | The cache path must not re-thin | Section 1: on a cache source `want` is `run_cached`'s span filter; `frames_from` is set before shards are copied | steps 0-2 |
| 2 | Step 4's L2 path never fires; L1's falsifier (60 s) disagrees with step 4 (180 s x 3) | L1, L2 and step 4 marked "to revise before measuring" | deferred to steps 3-4 |
| 3 | L6 exceeds the plan's scope | `publish.py` and `test_publish.py` left out of steps 0-2; finding 1 stays filed | steps 0-2 |
| 4 | A dead worker deadlocks the producer | Section 1: puts with timeout and a stop event, liveness checks, `status`; FIFO depth and live frames stated | steps 0-2 |
| 5 | The shard merge must keep list order | L3: merge by producer position, within-frame order kept; `shardable`'s contract | steps 0-2 |
| 6 | One OpenCV count per run moves the ladder's T_r | L3 states the count (one thread at W >= 1); step 3 adds a scoreboard serial at that count against `R[a06f04a0059f 09:52:39Z]` | deferred to step 3 |
| 7 | The shard row rests on a contended figure | Section 2: the row is an upper bound; step 3's serial ally_icon gates step 2's claim | steps 0-2 (text), step 3 (gate) |
| 8 | `_ME_CACHE` unlisted; a lost message fails the run | L3 lists the shared module dicts; section 1 says the reason lands in `status` | steps 0-2 |

Steps 0 to 2 ran on `c40d950031bb` from the crop cache, and every `--check` found its files equal; the
[measurements](PUBSUB_MEASUREMENTS.md#equality-checks-steps-0-to-2) list the runs, their hashes and their
usage run ids.

Before steps 3 and 4, changes 2 and 6 were made and L1 reframed:

- **Change 2.** Step 4 runs two paths, serial and staged at W = 1, over one prefix of at most 180 s,
  with `--only hud scoreboard`: the scoreboard keeps no state across frames, so it runs on a prefix, and
  it carries L1's video prediction. L1's falsifier is step 4, not a separate 60 s prefix. L2 leaves
  step 4, where no frame would fire it, and rests on its no-video falsifier.
- **Change 6.** L3 states the count: one OpenCV thread at W >= 1; at W = 0, `_feed`'s toggles on the
  default pool. The scoreboard reads no crop cache, so its serial at one thread folds into step 4's
  staged path instead of costing a third decode.
- **L1.** The staged pipeline, with today's `sample_multi` as its source, already takes decode and
  conversion off the reader threads; step 4 tests that. The `_Selector` and its deeper queue become a
  further lever, unbuilt, falsified from step 4's record.
- **Step 3** lists its runs and the reading rule for the GIL. Its runs publish into the store, since
  QUOTED reads only `<store>/notes/metrics.jsonl`; that waits for step 4 unless the player lifts the rule
  for files steps 1, 2 and 2a proved.
- **Section 3's table** gives `--until` in seconds, as built; the flag refuses to run without `--check`
  and `--check-dir`. Section 3's opening and open question 1 follow the reframe.

The measurement phase ran on 2026-09-27 as five `scan --check` runs at `fbc3143`, m1 to m5, each
byte-equal between paths; [`PUBSUB_MEASUREMENTS.md`](PUBSUB_MEASUREMENTS.md) lists their usage run ids and
reads their records, which `tools/pubsub_notes_append.py` copied into `<store>/notes/`. They depart from
section 3's list: each ran as a check into temporary stores, and path a, the serial pass, ran on OpenCV's
default pool, so no serial ally_icon of this phase ran at one thread.
