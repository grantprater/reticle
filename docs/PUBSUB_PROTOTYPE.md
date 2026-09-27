# Pub/sub prototype: the staged pass

Steps 0 to 2 of `docs/PUBSUB_DESIGN.md`, section 3, on branch
`pubsub-20260927`. Every run read the crop cache of `c40d950031bb`; none
decoded video. The critique's changes are in the design, section 6.

## What exists

| File | What it holds |
|---|---|
| `reticle/pipeline.py` | `run_staged`, `_Shards`, `compare_trees` |
| `reticle/usage.py` | `scan-usage-2` adds `pipeline`, `workers`, `shards`, `cv_threads`, `code_revision`, `error`; a staged pass adds per reader the frames `offered` and `fed`, each FIFO's `fed` and `max_queued`, and the dispatcher's `wait_ns`; `write_metric` writes a `scan_usage` pass row naming the `run_id`, in a series per configuration |
| `reticle/cli.py` | `scan --pipeline`, `--workers`, `--shard`, `--cv-threads`, `--check`, `--check-dir` |
| `reticle/minimap.py` | `AllyIconReader.shardable`: the lists its shards append to |
| `tests/test_pipeline.py` | Step 0, on synthetic readers and a synthetic cache |

The dispatcher, the calling thread, reads the source and offers each frame
read-only; each reader, or each shard of one, feeds on its own thread behind a
FIFO of 8 frames. `--workers N` caps the feeds that run at once; `--workers 0`
feeds inline through `passes._feed`, in the serial pass's order on either
source (`run_cached`'s list order, `passes.run`'s frozenset order on video). On
the cache the only filter is `run_cached`'s span filter, so the staged pass
sees the serial pass's frames. A staged pass at one worker or more sets OpenCV
to one thread and restores the count after; `--cv-threads` overrides it on
either path. A reader that raises stops the pass: the usage record says
`failed` with the error, and the scan publishes nothing.

A reader may shard only if it declares `shardable`: its `feed` reads no state
an earlier frame wrote and only appends to the named lists. Frame n goes to
shard n mod K. The merge puts every appended item back in frame order,
keeping the order within a frame, so `candidate_evidence.revision`, which
hashes the lists in order, cannot move. A shard that rebinds any other
attribute fails the merge, and a write into an ndarray the reader holds
raises, since sharding makes them read-only for the pass. A dict, set or
undeclared list changed in place goes unseen; the contract forbids it.

## How to run it

    python -m reticle scan <session> --only <readers> --from cache \
        --pipeline staged --workers N [--shard NAME=K] --check [--check-dir DIR]

`--check` runs the requested pass into `DIR/b`, then today's serial pass into
`DIR/a`, two fresh stores, and compares every file they write: bytes, then
Parquet rows when bytes differ, to say where two tables part. It exits 0 only
when the paths wrote at least one file and every file is byte-equal. Both paths
read the store and write nothing there, each keeping its usage and metric rows
in its own `notes/`. It refuses a check whose two paths are the same serial
pass, `--cache-roi`, and, with no stored killfeed mask, HUD readers, which
would decode to measure one. It does not force `--from cache`; without it both
paths decode. The runs below predate that order and that exit rule: they ran
serial first, and every file was byte-equal, so either rule passes them.

Each run below also carried `--check-dir <scratch>/<check directory>`, ran at
Idle priority, and set the OMP, MKL and OpenBLAS thread counts to 1.

## Step 1: the HUD pass, staged

    scan c40d950031bb --only hud --from cache --pipeline staged --workers 1 --check
    scan c40d950031bb --only hud --from cache --pipeline staged --workers 0 --check

Both exited 0 and printed the same five lines, the last trimmed here of the
usage ids and check directory it also names (see Runs):

    equal      events/killfeed_name/c40d950031bb.jsonl  sha256 792f3a55b3fd
    equal      events/killfeed_portrait/c40d950031bb.jsonl  sha256 901e3629f8e3
    equal      events/killfeed_weapon/c40d950031bb.jsonl  sha256 1d1d104f7f67
    equal      l1/hud/date=2026-08-25/session=c40d950031bb/hud.parquet  sha256 cfaa16ad082e
    check      4 files, 4 equal, 0 with row differences

## Step 2: ally_icon in two shards

    scan c40d950031bb --only ally_icon --ally-hz 15 --from cache \
        --pipeline staged --workers 2 --shard ally_icon=2 --check

Exit 0; both paths wrote candidate revision
`abe789d9f253a9ce6cd2dffba23e82e986cf21e229b5dadeb12ebcc9ba5c95e5` (the
summary line trimmed as in step 1):

    equal      candidates/ally_icon/c40d950031bb/<revision>.json  sha256 0b88c7305038
    equal      decisions/ally_icon/c40d950031bb/<revision>__minimap-icon-...json  sha256 6c90539c3c11
    equal      events/ally_icon/c40d950031bb.jsonl  sha256 06f53af8cd25
    check      3 files, 3 equal, 0 with row differences

Step 2a ran the serial path at one OpenCV thread against the default pool
(`--pipeline serial --cv-threads 1 --check`): exit 0, the same three file lines,
the same revision. The store's own copies of all seven files carry these hashes,
so both paths reproduce what the store holds.

## Runs

All eight ran at code revision `8e9f341`, clean tree.

| Step | Check directory | a: serial | b |
|---|---|---|---|
| 1, workers 1 | `check-step1-w1` | `d80a02bb3a184e35ad47bcd138d87fcd` | `dc1a4505a3c444628895d07a8ff70072` |
| 1, workers 0 | `check-step1-w0` | `bb7059832e274dfb9b78fe96fef7f18e` | `c0e5a77d433b4eb3936124b2ed115c62` |
| 2 | `check-step2` | `a9bb1e5d129e4a3e844eb96c52634a00` | `e26f78d2cb9e49eeadf220e73ff87dd4` |
| 2a | `check-step2a` | `8e5ff11d1a8344af8fe555184d2db684` | `1046bf3706534646a8c250d3a5b3f358` |

Wall times live in each path's `notes/usage.jsonl` (`pass_ns`, reader `feed`
buckets) and `notes/metrics.jsonl` (`scan_usage`, `pass_s`) under its check
directory. Those rows are outside the store, so no `metric:` token can cite
them, and this document quotes no time. Step 3 measures time, in the store.

The store did not change. Its session paths (L1, events, candidates,
decisions, masks, lineups), listed with sizes and times before step 1 and
after step 2a, matched; `notes/metrics.jsonl` gained two rows from another
job, and none of the eight run ids appears in the store's `notes/`.

## Findings

1. Two lazily filled module dicts cross threads: `_ME_CACHE` (killfeed), read
   by the hud and portrait threads, and `_REG` (ally portrait), read by both
   ally_icon shards. The code says the race is harmless: `_ME_CACHE` is keyed
   by the profile's name and `_REG` by a crop side and radius, constant
   within a pass; each entry is computed from its key alone, and nothing
   writes into an entry once stored (killfeed.py:782-799,
   ally_portrait.py:85-145), so a race computes an entry twice and changes
   nothing (design, L3). Steps 1 and 2 are no evidence for it: they ran the
   serial path first, which filled both dicts before the staged threads
   started. `--check` now runs the staged path first, so a later check meets
   them cold.
2. This OpenCV build defaults to 12 threads. Serial passes record 12 in
   `cv_threads`, staged passes at one worker or more record 1.
3. Other jobs write `notes/metrics.jsonl`, `notes/usage.jsonl` and this
   session's `l1/minimap` during the day. A store-unchanged proof must say
   whose rows moved.

## Not done

No `publish.py` or L6, no `_Selector`, no look-ahead (L1, L2), no `--until`,
no timing (step 3), no transport (step 4). One session only; the whole cached
session, not five minutes.
