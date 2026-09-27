# Pub/sub design: a staged scan over the store as the log

Design for the [plan](PUBSUB_PLAN.md), built on the [map](PUBSUB_PIPELINE_MAP.md) and the
[baseline](PUBSUB_PERFORMANCE_BASELINE.md). I read the code at `a065949`, ran no scan, opened no media
and changed no code.

**Citations.** No metrics row holds a scan's usage record, so QUOTED cannot check these figures; each
names its key in [`pubsub_baseline.json`](pubsub_baseline.json). Shorthand: `C[s]` is session `s`'s
`composite` entry; `S` is `composite_summary.core`; `G[b]` and `B[b]` are `groups[b]` and
`batch_totals[b]`; `R[s t]` is session `s`'s `records.rows` row recorded at `t` on 2026-09-26. Derived
figures show their arithmetic; none comes from a docstring.

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

| Step | Pass bound | Speedup | Keys and arithmetic |
|---|---|---|---|
| Serial today | 848.1 s | 1 | `core.serial_s` |
| L1: decode overlaps readers | 674.2 s | 1.258 | `core.overlap_bound_s`, `core.overlap_speedup` |
| L3: a thread per reader, free cores or W = 3 | 391.3 s | 2.168 | `core.parallel_bound_s`, `core.parallel_speedup`; max(391.3, 674.2 / 3) |
| + ally_icon in two shards (upper bound) | 224.7 s | at most 3.77 | max(173.9, 220.8, 391.3 / 2, 674.2 / 3) |
| + L5, if closed boards cost 40.1 to 158.0 s | 195.6 to 211.4 s | 4.0 to 4.3 | reader sum 516.2 to 634.1 s, over W = 3 |
| + three shards at W = 4 | toward 173.9 s | up to 4.88 | `decode_s`; 2321 s of video in 173.9 s is 13.3x real time |

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

### L1. The decode thread selects and converts

- **Mechanism.** Move `sample_multi`'s selection (decode.py:461-560) into a `_Selector` shared with the
  producer thread (decode.py:112). The producer grabs every frame, drops unwanted ones on the device,
  runs today's `retrieve` (NV12 download, plane split, swscale; decode.py:165-180) on wanted ones and
  queues `(want, Sample)`. Its queue then holds wanted frames only: 32 cover 16 s at 2 Hz in about 200
  MB. Today's 16 raw frames (`_NVDEC_AHEAD`, decode.py:37) span half the 30-frame gap between 2 Hz
  samples of a 60 fps capture, so the decoder stalls while readers run. `RoiCache.samples` moves there
  too.
- **Prediction.** a06f: 848.1 to 674.2 s. Lone passes gain
  `G[scoreboard/video/match/b1].speedup_overlap.median` 1.736 on video and
  `G[hud/cache/match/b1].speedup_overlap.median` 1.979 from the crop cache.
- **Constraints.** The selector sees every grabbed frame in order; `frame_idx` counts grabs; `next_t`
  advances only after a successful retrieve (decode.py:551-556); one FIFO feeds the dispatcher.
- **Falsifier, 120 s of video** (to revise before measuring: reconcile with step 4's 180 s x 3, section
  6). `scan --only scoreboard` over a 60 s prefix of c40d950031bb, serial and
  staged: rows byte-equal, and the dispatcher's wait under a tenth of the serial source time. Falsified
  if the pass shrinks by less than half the smaller of the serial source and reader times.

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
- **To revise before measuring.** With every default reader the path never fires: the scoreboard,
  roster, lineup, combat_report, minimap, ping and minimap_dark declare no `cache_set` (cli.py:939-977;
  finding 9), so step 4's third path is its second plus 180 s of decode. Run L2 as `--only hud` over the
  prefix, or drop it and rest on the no-video falsifier (section 6).

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
  pass at W >= 1 runs at one OpenCV thread, set once. The scoreboard and ally_icon were timed on the
  default pool, and `_feed` reports wall up 0-42% at one thread (passes.py:229-235), so this count moves
  the ladder's T_r; step 3 measures it (to revise before measuring, section 6).
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
L1 and L2 on video follow on one short prefix.

| Module | Layer (`architecture.toml`) | `ownership.toml` | Role |
|---|---|---|---|
| `reticle/pipeline.py` | orchestration | `[infrastructure]` | topics (a bounded in-process queue behind an interface a shared-memory tile topic can replace), dispatcher, subscriber threads, shards and merge, preludes, read-only frames; `run_staged(ctx, readers, source, workers, shards, usage)` returns each reader's finish result. Readers gain `shardable` and a list of the outputs a merge combines |
| `reticle/publish.py` (deferred, L6) | source | a new entry, `scan-run`: "Which run wrote this stored stream, and did that run finish?"; produces `PUBLISH_VERSION`, `Stager`, `commit`, `recover`, `run_of`; `not_for` staleness (plan's), observations and names | staging, run record, commit, roll-forward |
| `reticle/decode.py` | source | `[infrastructure]`, as now | `_Selector` out of `sample_multi`; the selecting, converting producer; ROI conversion |
| `reticle/usage.py` | foundation | `[infrastructure]`, as now | `scan-usage-2` |
| `reticle/cli.py` | delivery | none | `scan --pipeline {serial,staged} --workers W --shard READER=K --until MS --check`; the publish block (cli.py:1029-1180) becomes `_publish_scan(out_store, ...)`, and the ally-icon chain stays in `cli` as a callback, so `pipeline` imports nothing above its layer. `cmd_scan` reaches both new modules (UNWIRED, UNCALLED); no new name repeats a `prototypes/` one (DUPLICATE) |

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
3. **Timing** (to revise before measuring, section 6), once the player grants cores: steps 1 and 2 at
   W = 1 to 4, against lone records `R[c40d950031bb 06:34:24Z]` (ally_icon, readers 74.3 s),
   `R[c40d950031bb 19:08:23Z]` (hud, 8.7 s) and `R[c40d950031bb 12:11:54Z]` (killfeed_portrait, 8.0 s).
   A serial miss measures code drift first.
4. **Video, c40d950031bb** (to revise before measuring, section 6): every default reader over the
   shortest prefix (`--until`, at most 180 s) that stored tables say holds an open board, a killfeed
   entry and an active span, on three paths: serial `passes.run`, staged with the selecting producer
   (L1), and staged with ROI conversion (L2). At most 540 s of video in all, on NVDEC when the player's
   jobs leave it free. Accept: byte-equal files across the three, and producer timings in each record.

**The equality test.** `--check` builds the readers twice against the real store's inputs, runs path A
(today's `passes.run` or `run_cached`, untouched) and path B (`pipeline.run_staged`), publishes each
through `_publish_scan` into its own temporary `Store`, and compares the trees by relative path and
sha256. On a difference it prints the first differing observation key or Parquet column, as `trial.diff`
and `trial.diff_table` do, and exits non-zero. It writes nothing into the store: each path's usage
record goes to its own temporary store.

**Usage record `scan-usage-2`** adds `code_revision` (HEAD, dirty flag), `pipeline`, `transport`,
`decode_backend` (`nvdec`, `opencv`, `cache`), `threads` (W, shards, the OpenCV, OMP, MKL and OpenBLAS
counts), `process_cpu_ns`, each thread's `thread_cpu_ns`, the producer's `decode_ns`, `convert_ns` and
`stall_ns`, the dispatcher's `wait_ns`, each reader's `busy_ns` and `wait_ns`, `overlap` (busy over pass
time), each stream's `stage_ns`, `commit_ns`, `priority`, `concurrent_scans` (from a registry of running
scans) and `status`, written on failure too. Each completed scan also appends a `pass` row to
`notes/metrics.jsonl` naming its usage `run_id`, so QUOTED can cite the measure phase.

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

## 5. Open questions

| # | Question | Cheapest experiment |
|---|---|---|
| 1 | How much NVDEC source time is conversion, how much wait? | the producer's timers over L1's 60 s prefix |
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

Steps 0 to 2 ran on `c40d950031bb` from the crop cache, and every `--check` found its files equal
(`docs/PUBSUB_PROTOTYPE.md`). Usage run ids, path a (serial) then path b: step 1 at workers 1
`d80a02bb3a184e35ad47bcd138d87fcd`, `dc1a4505a3c444628895d07a8ff70072`; step 1 at workers 0
`bb7059832e274dfb9b78fe96fef7f18e`, `c0e5a77d433b4eb3936124b2ed115c62`; step 2 (two ally_icon
shards) `a9bb1e5d129e4a3e844eb96c52634a00`, `e26f78d2cb9e49eeadf220e73ff87dd4`; step 2a (one OpenCV
thread) `8e5ff11d1a8344af8fe555184d2db684`, `1046bf3706534646a8c250d3a5b3f358`. The records sit in
each check's own stores, outside `<store>`, so no `metric:` token cites them.
