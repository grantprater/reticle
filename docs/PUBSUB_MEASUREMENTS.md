# Pub/sub measurements: the baseline and design steps 1 to 4

This document holds every measurement of the [design](PUBSUB_DESIGN.md)'s staged pass: the usage records
from before staging, the equality checks of steps 1 and 2, and steps 3 and 4, the staged pass against the
serial one on `c40d950031bb`, read from the usage and metrics rows of five `scan --check` runs the player
ran. Writing this, I ran no scan and decoded nothing.

## Before staging: the usage-record baseline

`tools/pubsub_baseline.py` reads the store's `scan-usage-1` records in `<store>/notes/usage.jsonl`, up to
its cutoff of 2026-09-27T08:58Z, and writes [`pubsub_baseline.json`](pubsub_baseline.json), whose keys the
design cites; the [baseline](archive/PUBSUB_PERFORMANCE_BASELINE-2026-09-27.md) reads it at length. Usage logging landed in
`89bc726`. Every record but one ran a single reader (`scan --only`), and none a full fused scan.
`composite` estimates one per session from separate records, taking decode from the crop-cache write's
source time and each reader at its lowest recorded cost; ping, roster, lineup, minimap_dark and the
combat report have no record.

- **Where the time goes** (`share_source`, `share_readers`). Crop-cache writes on video are
  decode-bound. The scoreboard on video splits between source and reader; minimap waits on the source on
  std sessions and on its reader on the bigmap one. From the crop cache ally_icon is almost all reader,
  killfeed_portrait is reader and then crop decode, and hud splits evenly between the two. Every
  single-reader pass runs faster than real time.
- **Overlap.** Giving the source its own worker (`gain_overlap_frac_wall`) helps most where source and
  reader balance: hud and killfeed_portrait from the cache, the scoreboard and minimap on video. Only the
  one two-reader record (c62c2b06bcfb) gains more from running its readers at once
  (`gain_parallel_frac_wall`).
- **The dominant reader.** ally_icon is heaviest in the composite on most sessions, the scoreboard on the
  rest (`composite_summary.core.heaviest`). ally_icon costs per pixel, not per call (`per_pixel`); it runs
  on OpenCV's default pool, and its batches ran beside other scans, so contention inflates them. The
  scoreboard converts the whole frame to HSV before it learns the board is closed (design, L5).
- **What the records lack:** CPU time, the decode backend, OpenCV's thread count, the code revision and
  machine load; `concurrent_records` sees only other recorded scans. `scan-usage-2` added the revision,
  CPU and thread counts, not the backend or contention.

**A correction.** The baseline found that decode hid no reader time on three lone scoreboard records
(`same_session_source`) and offered two causes: an OpenCV fallback, or an NVDEC read-ahead too short for
the 2 Hz gap. Answer 5 below rules out the second: on NVDEC the read-ahead hid about half of each gap,
10.1 s over m5's prefix. The records name no backend, so the first cause stays open.

## Equality checks, steps 0 to 2

Step 0 is `tests/test_pipeline.py`, on synthetic readers and a synthetic cache. Steps 1 and 2 read the
crop cache of `c40d950031bb` at code revision `8e9f341`, clean tree, and decoded nothing. Each ran
`scan c40d950031bb --from cache --check` with the flags below and exited 0 with every file byte-equal.
They ran the serial path first, before `--check` put path b first.

| Step | Further flags | Usage a (serial) | Usage b |
|---|---|---|---|
| 1, workers 1 | `--only hud --pipeline staged --workers 1` | `d80a02bb3a184e35ad47bcd138d87fcd` | `dc1a4505a3c444628895d07a8ff70072` |
| 1, workers 0 | `--only hud --pipeline staged --workers 0` | `bb7059832e274dfb9b78fe96fef7f18e` | `c0e5a77d433b4eb3936124b2ed115c62` |
| 2 | `--only ally_icon --ally-hz 15 --pipeline staged --workers 2 --shard ally_icon=2` | `a9bb1e5d129e4a3e844eb96c52634a00` | `e26f78d2cb9e49eeadf220e73ff87dd4` |
| 2a | `--only ally_icon --ally-hz 15 --pipeline serial --cv-threads 1` | `8e5ff11d1a8344af8fe555184d2db684` | `1046bf3706534646a8c250d3a5b3f358` |

Step 1 wrote four files at both worker counts, with sha256 prefixes `792f3a55b3fd`
(`events/killfeed_name`), `901e3629f8e3` (`events/killfeed_portrait`), `1d1d104f7f67`
(`events/killfeed_weapon`) and `cfaa16ad082e` (`l1/hud`). Steps 2 and 2a wrote candidate revision
`abe789d9f253a9ce6cd2dffba23e82e986cf21e229b5dadeb12ebcc9ba5c95e5` (`0b88c7305038`), its decisions
(`6c90539c3c11`) and `events/ally_icon` (`06f53af8cd25`). The store's own copies of all seven files carry
these hashes, so both paths reproduce what the store holds, and the store's session paths matched before
step 1 and after step 2a. The usage rows sit in each check's own stores, outside `<store>`, so no
`metric:` token cites them and this section quotes no time.

## Steps 3 and 4: conditions

- Code `fbc3143`, clean tree (each record's `code_revision`); 2026-09-27, 11:30 to 11:37 local time. One
  process at a time, at Idle priority, with OMP, MKL and OpenBLAS at one thread.
- Each run is a `scan --check`: path b, the staged pass the flags ask for, first; then path a, today's
  serial pass. Path a takes no `--cv-threads`, so every serial row ran on OpenCV's default pool of 12
  threads (`cv12`), every staged row at one worker or more on one thread (`cv1`), and m1's staged row, at
  workers 0, on the pool. No reader in these passes declares its own count (`cv_threads.toggled` is empty).
- m1 to m4 read the crop cache: the HUD set as PNG, the minimap set as FFV1 through `cv2.VideoCapture`.
  m5 decoded the first 180 s of video, 360 sampled frames a path; no record names the decoder (answer 5).
- `tools/pubsub_notes_append.py` copied each path's usage row and `scan_usage` pass row from the check
  stores into `<store>/notes/usage.jsonl` and `notes/metrics.jsonl`: 10 rows each, byte-equal to the
  check stores' rows, each pass row naming its usage `run_id`. No run published a stream into the store.

| Run | Flags after `scan c40d950031bb --check` | Files equal | Usage a (serial) | Usage b (staged) |
|---|---|---|---|---|
| m1 | `--only hud --from cache --pipeline staged --workers 0` | 4 of 4 | `2d6b227969e64a4880d827b32d688d10` | `921108c1adb245eeaa3bf1ab982f1801` |
| m2 | `--only hud --from cache --pipeline staged --workers 1` | 4 of 4 | `9d49200011e6490aa057a431b4976262` | `cf98e5c94cbc498a9d31606849edb4c7` |
| m3 | `--only ally_icon --ally-hz 15 --from cache --pipeline staged --workers 2 --shard ally_icon=2 --cv-threads 1` | 3 of 3 | `5ed78255d8074eca9d89ed00c0e54807` | `09a489d4eeb34375872e42b1332a5db2` |
| m4 | as m3, with `--workers 3 --shard ally_icon=3` | 3 of 3 | `df2f19726d0a45d6a39b80f9919c0a10` | `b1feb3beca2e41c098aacd37c25b6745` |
| m5 | `--only hud scoreboard --from video --until 180 --pipeline staged --workers 1` | 5 of 5 | `4dd06395f7904478a8c23101af4bfbb5` | `5d2e53c974af4c06b5478587ef6de27c` |

Both paths of m3 and m4 wrote candidate revision `abe789d9f253a9ce6cd2dffba23e82e986cf21e229b5dadeb12ebcc9ba5c95e5`.
The check reported open boards in m5's prefix and no killfeed entry, so its three killfeed streams hold no
observation on either path.

**Citations.** A `metric:` token resolves against the latest `pass` row of its series
(`reticle/quoted.py`), whose name carries readers, source, pipeline, workers, shards, OpenCV count and
prefix. Serial and staged rows therefore never share a series, and m3's staged series (`w2/ally_icon=2`)
differs from m4's (`w3/ally_icon=3`). Two runs of one configuration do share one: m1a with m2a, and m3a
with m4a. The tool appended m2a and m4a later, so a token for m1a or m3a would resolve to their rows.
Figures of m1a and m3a, and figures no pass row carries (call counts, each worker's CPU, busy wall and
FIFO depth, a call's maximum), cite the usage row as `U[<run><path>]` with its key; QUOTED checks none.
Ratios and per-call times are arithmetic on the cited figures.

## The pass

| Run, path | pass_s | source_s | cpu_s | Dispatcher CPU | Dispatcher wait | cpu_s / pass_s |
|---|---|---|---|---|---|---|
| m1 a, `U[m1a]` | 22.0 | 8.3 | 46.0 | 21.8 | none | 2.09 |
| m1 b, w0 | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#pass_s=24.2] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#source_s=8.4] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#cpu_s=57.0] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#dispatcher_cpu_s=23.9] | none | 2.35 |
| m2 a | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#pass_s=25.8] | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#source_s=9.2] | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#cpu_s=55.5] | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#dispatcher_cpu_s=24.8] | none | 2.15 |
| m2 b, w1 | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#pass_s=14.3] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#source_s=9.3] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#cpu_s=22.8] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#dispatcher_cpu_s=8.7] | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#dispatcher_wait_s=5.0] | 1.59 |
| m3 a, `U[m3a]` | 59.7 | 8.0 | 177.5 | 57.5 | none | 2.97 |
| m3 b, w2, 2 shards | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#pass_s=57.0] | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#source_s=12.2] | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#cpu_s=140.6] | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#dispatcher_cpu_s=9.8] | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#dispatcher_wait_s=44.3] | 2.47 |
| m4 a | [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#pass_s=48.1] | [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#source_s=6.4] | [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#cpu_s=147.9] | [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#dispatcher_cpu_s=47.3] | none | 3.07 |
| m4 b, w3, 3 shards | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#pass_s=40.3] | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#source_s=9.4] | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#cpu_s=114.5] | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#dispatcher_cpu_s=7.5] | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#dispatcher_wait_s=30.4] | 2.84 |
| m5 a | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#pass_s=25.4] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#source_s=11.6] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#cpu_s=18.8] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#dispatcher_cpu_s=10.8] | none | 0.74 |
| m5 b, w1 | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#pass_s=27.2] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#source_s=21.7] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#cpu_s=15.3] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#dispatcher_cpu_s=1.3] | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#dispatcher_wait_s=5.4] | 0.56 |

## The readers

"Inline" means the reader fed on the dispatcher thread, whose CPU the pass table holds. Calls and the last
column come from the usage rows (`readers.<r>.feed.count`, `readers.<r>.shards`, `readers.<r>.feed.max_ns`).

| Run, path | Reader | feed_s | Calls | ms a call | Thread CPU, s | Each worker: CPU / busy wall, s; max_queued |
|---|---|---|---|---|---|---|
| m1 a, `U[m1a]` | hud; killfeed_portrait | 6.8; 6.5 | 1945 | 3.52; 3.35 | inline | |
| m1 b | hud | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#feed_s_hud=7.7] | 1945 | 3.97 | inline | |
| m1 b | killfeed_portrait | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w0/cv12@c40d950031bb~921108c1adb2#feed_s_killfeed_portrait=7.8] | 1945 | 4.00 | inline | |
| m2 a | hud | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#feed_s_hud=8.0] | 1945 | 4.12 | inline | |
| m2 a | killfeed_portrait | [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#feed_s_killfeed_portrait=8.1] | 1945 | 4.17 | inline | |
| m2 b | hud | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#feed_s_hud=6.6] | 1945 | 3.39 | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_hud=6.8] | one FIFO; 8 |
| m2 b | killfeed_portrait | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#feed_s_killfeed_portrait=7.3] | 1945 | 3.77 | [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_killfeed_portrait=7.4] | one FIFO; 8 |
| m3 a, `U[m3a]` | ally_icon | 50.0 | 7729 | 6.47 | inline | |
| m3 b | ally_icon | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#feed_s_ally_icon=110.8] | 7729 | 14.33 | [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#thread_cpu_s_ally_icon=86.0] | 43.0 / 55.2, 43.0 / 55.7; 8 each |
| m4 a | ally_icon | [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#feed_s_ally_icon=40.3] | 7729 | 5.21 | inline | |
| m4 b | ally_icon | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#feed_s_ally_icon=118.7] | 7729 | 15.36 | [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#thread_cpu_s_ally_icon=75.2] | 25.2 / 39.7, 25.0 / 39.6, 25.1 / 39.5; 8 each |
| m5 a | hud; killfeed_portrait | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_hud=0.81]; [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_killfeed_portrait=0.67] | 360 | 2.24; 1.86 | inline | |
| m5 a | scoreboard | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_scoreboard=12.1] | 360 | 33.66 | inline | slowest call 0.45 s |
| m5 b | hud; killfeed_portrait | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#feed_s_hud=0.84]; [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#feed_s_killfeed_portrait=0.72] | 360 | 2.34; 2.01 | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_hud=0.80]; [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_killfeed_portrait=0.66] | one FIFO each; 8 |
| m5 b | scoreboard | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#feed_s_scoreboard=14.7] | 360 | 40.85 | [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_scoreboard=9.30] | one FIFO; 8; slowest call 2.73 s |

## Answers

**1. The OpenCV count differed, and it confounds m3 and m4.** Serial rows ran on the pool of 12 threads, staged rows at one worker or more on one thread. The serial ally-icon reader took 6.47 ms a call in m3 and 5.21 ms in m4; a shard took 14.33 and 15.36 ms.
The pool is no single thread: the serial ally-icon passes burned 177.5 s (`U[m3a]`) and [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#cpu_s=147.9] s of CPU, 2.97 and 3.07 times their wall. m3 and m4 therefore compare shards at one OpenCV thread with one reader spread over the pool, never with one thread.
The count barely touches m5: without each path's slowest call, the scoreboard took 32.50 ms a call on the pool and 33.36 ms at one thread (([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_scoreboard=12.119] − 0.450) / 359 and ([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#feed_s_scoreboard=14.705] − 2.729) / 359), under 3% apart.
Nor does it move the HUD readers' wall: 3.39 and 3.77 ms a call at one thread (m2b), against 3.52 and 3.35 (`U[m1a]`) and 4.12 and 4.17 (m2a) on the pool. It moves their CPU: at one thread the HUD pass's process CPU equals its three threads' sum to the tick ([metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#dispatcher_cpu_s=8.656] + [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_hud=6.781] + [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_killfeed_portrait=7.375] = [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#cpu_s=22.812] s), so the 24 to 33 s that the pool-bound HUD rows spent off the dispatcher thread (cpu_s less dispatcher CPU) are the pool's.

**2. The GIL, by design step 3's rule.** In m2, at one worker, each reader thread's CPU matched its feed wall ([metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_hud=6.8] against [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#feed_s_hud=6.6] s; [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#thread_cpu_s_killfeed_portrait=7.4] against [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#feed_s_killfeed_portrait=7.3] s): the threads computed through their feeds. The semaphore lets one feed run at a time, and the process ran 1.59 threads, the dispatcher beside one reader.
In m3 the two shards' CPU, [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#thread_cpu_s_ally_icon=86.0] s, was 0.78 of their feed wall, [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#feed_s_ally_icon=110.8] s, and over the [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#pass_s=57.0] s pass they ran 1.51 threads at once. In m4 the three shards' [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#thread_cpu_s_ally_icon=75.2] s was 0.63 of [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#feed_s_ally_icon=118.7] s, and over [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#pass_s=40.3] s they ran 1.87 threads.
The shards ran at once, not in turns, so by the rule ally_icon does not yet move to process shards. But the third shard added 0.36 of a thread and raised each call's waiting share from 22% to 37%. With about three of this machine's 12 threads busy and little else running during m4 (answer 6), the waiting is more likely the GIL than a lack of cores; the records cannot split the two.

**3. m2 gains; m1 cannot.** At workers 0 the staged pass feeds inline on the dispatcher thread in the serial order, so nothing overlaps: m1b's pass is its source plus both feeds plus 0.36 s (`U[m1b].pass_other_ns`), as a serial pass is. It ran 2.2 s slower than m1a, less than the 3.7 s between the two serial runs of one configuration (22.0 s in m1a, [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#pass_s=25.8] s in m2a).
At one worker the dispatcher read crops ([metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#source_s=9.3] s) while one reader thread fed. The readers' sum, 13.9 s, set the pace; the dispatcher blocked on full FIFOs for [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#dispatcher_wait_s=5.0] s; and the [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#pass_s=14.3] s pass came within 0.4 s of the larger of source and reader sum. It fell 1.80 times against m2a (25.8 / 14.3) and 1.54 against m1a (22.0 / 14.3).

**4. Why the shards gain little.** The source is not the floor: the dispatcher blocked on full FIFOs for [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#dispatcher_wait_s=44.3] of [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#pass_s=57.0] s in m3 and [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#dispatcher_wait_s=30.4] of [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#pass_s=40.3] s in m4, every FIFO reached its depth of 8, and the FFV1 reads took [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#source_s=12.2] and [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#source_s=9.4] s.
Nor did the shards split the reader's time. Each shard fed about as long as the whole serial reader: 55.2 and 55.7 s (`U[m3b]`) against 50.0 s (`U[m3a]`), and 39.5 to 39.7 s (`U[m4b]`) against [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#feed_s_ally_icon=40.3] s, because each call took 2.2 and 2.9 times the serial call's wall (answer 1).
The serial reader already ran on about three cores through OpenCV's pool; the shards, at one thread each, brought the process to 2.47 and 2.84. Staging traded parallelism inside a call for parallelism across frames at about the same core count: the pass fell 1.05 times at two shards (59.7 / [metric:scan_usage/ally_icon/cache/staged/w2/ally_icon=2/cv1@c40d950031bb~09a489d4eeb3#pass_s=57.0]) and 1.19 at three ([metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#pass_s=48.1] / [metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#pass_s=40.3]), on 23% less CPU at three ([metric:scan_usage/ally_icon/cache/staged/w3/ally_icon=3/cv1@c40d950031bb~b1feb3beca2e#cpu_s=114.5] against [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#cpu_s=147.9] s).
A shard's call cost 11.1 and 9.7 ms of CPU (86.0 and 75.2 s over 7729 calls). Another 44.8 s (m3b) and 31.8 s (m4b) of process CPU ran on threads no record times (cpu_s less the dispatcher's and the shards'). FFmpeg's FFV1 decoder inside `cv2.VideoCapture` runs its own threads, outside `cv2.setNumThreads`, and is the likely owner; the PNG path of m2b shows none.

**5. m5: decode, the read-ahead and the scoreboard.** The serial path waited [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#source_s=11.6] s on the source over 360 frames, 32.2 ms a frame, and fed its readers 37.8 ms a frame ([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_scoreboard=12.1] + [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_hud=0.81] + [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#feed_s_killfeed_portrait=0.67] s); the staged path waited [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#source_s=21.7] s, 60.3 ms a frame.
The serial path already overlapped decode: while its readers ran, the NVDEC producer decoded up to 16 frames ahead (`_NVDEC_AHEAD`, decode.py:37), which the design reckons at about half the 30-frame gap between 2 Hz samples of a 60 fps capture (L1), and the dispatcher waited out the rest. Freed of readers, the staged dispatcher waited out the whole gap: the read-ahead had hidden 10.1 s (21.7 − 11.6) of decode.
The decode ran on the GPU: outside its timed threads the staged pass spent 3.26 s of CPU on three minutes of capture ([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#cpu_s=15.30] − [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#dispatcher_cpu_s=1.28] − [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_hud=0.80] − [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_killfeed_portrait=0.66] − [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#thread_cpu_s_scoreboard=9.30]), far less than a software decode costs.
Staging moved the readers off the dispatcher, whose CPU fell from [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#dispatcher_cpu_s=10.8] to [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#dispatcher_cpu_s=1.3] s, and added nothing else: source and FIFO blocking ([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#dispatcher_wait_s=5.4] s) make the [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#pass_s=27.2] s pass, 1.9 s over the serial [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#pass_s=25.4] s. The blocking came in bursts: on each path 35 scoreboard calls exceeded 100 ms (`readers.scoreboard.feed.buckets` of `U[m5a]` and `U[m5b]`), and one staged call took 2.73 s.
One OpenCV thread does not explain the loss: it cost the scoreboard 0.9 ms a call (answer 1), 0.3 s in all, while that one call ran 2.3 s past the serial maximum, more than the whole loss. `--check` runs path b first, against cold caches, so the call is likely a first-use setup; the record keeps no call order, and a check with a warm-up call would tell.

**6. Contention.** The listings, taken just before each run, show the six processes with the most CPU since they started: two browser subprocesses, Opera, the terminal, RazerCortex and `claude`, at Normal priority or above wherever the listing reads a class, and so ahead of an Idle-priority scan. A listing ranked by lifetime CPU cannot show a process that started recently, and none follows m5.
Between listings, Opera's CPU grew most across m3, markedly across m2, and hardly across m1 and m4. The serial ally-icon pass took 59.7 s in m3 (`U[m3a]`) against [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#pass_s=48.1] s in m4, 11.6 s or 24% longer, with its source and its reader each slower by 24 to 25%: a uniform slowdown, as a competing process gives, in the run where Opera worked hardest.
The listings fit that account and cannot place Opera's CPU within m3's two paths. The two serial HUD runs differ by 17%, and Opera's other burst fell in m2. On this machine a difference under a fifth between single runs is within the spread.

## m6: both ally-icon paths at one OpenCV thread

After `6aecf78` gave the check's serial path the staged path's `--cv-threads`, I reran m3's flags: `scan c40d950031bb --only ally_icon --ally-hz 15 --from cache --pipeline staged --workers 2 --shard ally_icon=2 --cv-threads 1 --check`, at code `f5a7c81` on a clean tree, 2026-09-28, 15:53 to 15:55 local time, at Idle priority with OMP, MKL and OpenBLAS at one thread. Path a (usage `348617a112374f3aa6240f0d84a0e13c`) and path b (`948305e96e42411287c5d0b778246df2`) both ran at one OpenCV thread and wrote the same three files as m3 and m4, byte for byte (candidate revision `abe789d9…`, decisions `6c90539c3c11`, events `06f53af8cd25`). Both records are `scan-usage-3`: both name the FFV1 cache read through OpenCV, and both saw heavy other load, 0.44 of the 12 logical processors busy with other processes on each path (`U[m6a].contention.other_cpu_ns` / (`pass_ns` × 12), and alike for `U[m6b]`); VALORANT was running when the check began.

Path a's pass row is in the store's metrics notes. Path b's row would share m3b's series (`w2/ally_icon=2/cv1`) and shadow m3b's tokens, so only its usage row was appended; its figures cite `U[m6b]`.

| | pass, s | source, s | process CPU, s | ally_icon feed, s | ms a call | threads |
|---|---|---|---|---|---|---|
| m6 a, serial, cv1 | [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#pass_s=62.2] | [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#source_s=8.7] | [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#cpu_s=89.4] | [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#feed_s_ally_icon=51.4] | 6.66 | 1.44 |
| m6 b, w2, 2 shards, cv1 | 44.2 | 12.7 | 105.7 | 85.4 (two shards) | 11.05 | 2.39 |

- **Staging at equal threads.** The pass fell 1.41 times (62.2 / 44.2). Design step 3's L3 bound for two ally-icon shards asked at least 1.6 and falsified below 1.2: 1.41 neither meets nor falsifies it. The dispatcher still blocked on full FIFOs for 31.2 of 44.2 s (`U[m6b].dispatcher.wait_ns`), so the shards set the pace.
- **A shard's call costs more than the serial call, in CPU too.** A serial call took 6.66 ms of wall at one thread; a shard's call took 11.05 ms of wall and 8.37 ms of its thread's CPU (64.7 s over 7729 calls, `U[m6b].readers.ally_icon`). Waiting alone does not explain the gap: each shard burned more CPU a call than the serial reader spent in wall. Two shards contending for cache and memory bandwidth, or the GIL's handoffs, remain candidates; these records cannot split them.
- **One thread against the pool.** The serial pass at one thread burned [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#cpu_s=89.4] s of CPU against m4a's pool-bound [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#cpu_s=147.9] s, and its reader took 6.66 ms a call against 5.21 (m4a) and 6.47 (`U[m3a]`). The pool therefore bought little wall per call for 1.65 times the CPU; m6 ran under heavier load than m4, so the wall comparison is loose.
- **Unattributed CPU.** Off every timed thread each path spent about 32 s of CPU: 89.4 − [metric:scan_usage/ally_icon/cache/serial/cv1@c40d950031bb~348617a11237#dispatcher_cpu_s=57.6] = 31.8 s on path a, 105.7 − 8.4 − 64.7 = 32.6 s on path b. OpenCV ran at one thread, so the FFV1 decoder's own threads inside `cv2.VideoCapture` are the likely spender; that is an inference.

## Against the predictions

**The plan's four.**

1. *Decode and readers add; a pipeline bounds the pass by the larger.* Held from the crop cache: m2's serial pass is its source plus its feeds, and the staged pass came within 0.4 s of the larger. Refuted on NVDEC video: the read-ahead hid 10.1 s of decode in the serial pass, and the staged pass lost 1.9 s. The baseline outcome that the read-ahead "hides nothing on 2 Hz passes" is wrong: it hides about half of each gap. And on OpenCV's pool no serial pass is one thread.
2. *The gain lives in video passes.* Refuted: the crop-cache HUD pass gained 1.80 times, and the video prefix lost ([metric:scan_usage/hud+killfeed_portrait+scoreboard/video/serial/cv12/until180@c40d950031bb~4dd06395f790#pass_s=25.4] / [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#pass_s=27.2] = 0.93).
3. *One reader dominates at a fixed per-call cost; batch it.* Not tested here. The runs add that ally_icon reaches about three cores on either path, which points at fewer operations per pixel.
4. *The transport is not the cost.* Held: the staged HUD pass at one worker ran 0.4 s past its reader sum over 1945 frames, which bounds threads, queues and handoffs together, and every dispatcher at one worker or more spent less CPU than its source wall.

**The design's ladder.**

- *L1, decode overlaps readers:* lone passes gain 1.979 times from the cache (`G[hud/cache/match/b1].speedup_overlap.median`) and 1.736 on video (`G[scoreboard/video/match/b1].speedup_overlap.median`). From the cache, m2 at one worker isolates overlap: 1.80, a tenth short. On video, refuted: the falsifier needed the staged pass to shrink by at least 5.8 s, half the serial source, the smaller of source and reader sum; it grew by 1.9 s. On NVDEC at 2 Hz decode and readers already overlap by half, so the ladder's L1 row overstates the gain.
  The `_Selector` rule reads the dispatcher's wait, 20% of the pass (5.4 / 27.2), as readers setting the pace, and keeps the selector unbuilt; here decode set the pace for [metric:scan_usage/hud+killfeed_portrait+scoreboard/video/staged/w1/cv1/until180@c40d950031bb~5d2e53c974af#source_s=21.7] s and scoreboard bursts for the rest, which only a deeper queue absorbs. Next lever: on video decode is the floor, 60.3 ms a 2 Hz sample here, so staging pays there only by putting more readers on one decode.
- *L3, readers and shards concurrent:* at least 1.6 times for two ally-icon shards, falsified below 1.2; at least 1.5 for the HUD pair. Two shards gave 1.05 and three 1.19: refuted by its own falsifier, though against the pool rather than one thread (answer 1). The pair at two workers did not run; overlap alone gave 1.80.
  The ladder's shard rows rest on a contended ally-icon figure, and the design gates them on an uncontended serial one: c40d's serial reader now feeds [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#feed_s_ally_icon=40.3] s (m4a) against 74.3 s alone (`R[c40d950031bb 06:34:24Z].readers_s`) and 178.4 s beside five scans (`R[c40d950031bb 02:35:45Z].readers_s`). If a06f's contended figure shrinks alike, the scoreboard (`C[a06f04a0059f].readers.scoreboard.s`) is its floor and shards buy nothing there, as the design warned. Next lever: the one-thread serial run, then fewer operations per pixel in ally_icon; by the rule, process shards are not yet due.
- *The baseline's uncontended c40d records.* ally_icon, 74.3 s at 9.61 ms a call (`R[c40d950031bb 06:34:24Z]`): now [metric:scan_usage/ally_icon/cache/serial/cv12@c40d950031bb~df2f19726d0a#feed_s_ally_icon=40.3] s (m4a) and 50.0 s (`U[m3a]`), 5.21 and 6.47 ms, 33 to 46% less. Code drift, or load the old record never saw; it carries no revision or CPU, so open question 6 stays half open. hud, 8.7 s (`R[c40d950031bb 19:08:23Z].readers_s`), and killfeed_portrait, 8.0 s (`R[c40d950031bb 12:11:54Z].readers_s`): the serial passes fed them 6.8 (`U[m1a]`) to [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#feed_s_hud=8.0] s and 6.5 to [metric:scan_usage/hud+killfeed_portrait/cache/serial/cv12@c40d950031bb~9d49200011e6#feed_s_killfeed_portrait=8.1] s, from 21% below to 1% above. Held.

## Not measured, and what one more run would settle

- A process shard of ally_icon, and a warmed-up `--check` whose path b does not pay the cold start alone: backlog item (1) named both, and neither has run. m6 ran each path once, under other load.
- The HUD pair at two workers (L3 on the pair), whose bound is the source's [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb~cf98e5c94cbc#source_s=9.3] s.
- The producer's decode, conversion and stall timers, the decoder's name, `concurrent_scans` and the priority: design section 3 lists them, and `scan-usage-2` as built records none, so m5's NVDEC is inferred from CPU and open question 1 stays open. CPU on untimed threads is unattributed.
- Order and repetition: `--check` runs path b first, so b pays cold starts, and each configuration ran once, where two identical serial runs differed by up to 24%.
- m5's prefix held no killfeed entry, so on video the killfeed streams were equal and empty.
- A transport beyond the in-process queue, and any run publishing into the store.
