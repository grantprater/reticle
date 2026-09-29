"""A staged scan pass: each reader behind its own FIFO and worker thread.

`passes.run` and `passes.run_cached` feed every wanting reader in turn, one
frame at a time, so a pass costs the source plus the sum of its readers.
`run_staged` drives the same reader objects over the same source, but the
dispatcher (the calling thread) only reads the source and offers each frame;
each reader, or each shard of a shardable reader, calls `feed` on its own
worker thread behind a bounded FIFO. Readers keep their state, stamps and
`frames_from`, so every stream the publish block writes afterwards is the
serial pass's, byte for byte, and `scan --check` tests exactly that. No
definition moves, so no stamp moves (docs/PUBSUB_DESIGN.md, section 1).

**Which frames: the source's rule, never a second one.** On video
`decode.sample_multi` decides from each reader's `hz` and `spans`, as `run`
does. On the crop cache `want` is `passes.cache_feed`, the rule `run_cached`
uses: `roi_cache.cache_for` has matched every reader's rate to the cache's or
let a `cache_resample` reader read its own grid, and `--from cache` has
clipped spans to the cache's rounds, so a second thinning would pick other
frames than the serial pass. `frames_from` is set
from the chosen source before any reader is copied into shards, because the
killfeed reader writes it into three streams.

**Read-only frames.** Every offered frame has `writeable` cleared, so a reader
that writes into a frame other readers may be reading raises at once instead
of changing their pixels.

**FIFO depth and memory.** Each reader or shard has a FIFO of `FIFO_DEPTH`
(8) frames, and its worker holds at most one more. The dispatcher blocks on a
full FIFO, so with T worker threads at most 1 + (8 + 1) T frames are alive at
once, and readers that want the same frame share one array. A 1920x1080 BGR
frame is 1920 x 1080 x 3 = 6,220,800 bytes: the HUD pass's two readers, or
ally_icon in two shards, hold at most 19 frames, 118 MB. The cache path reads
no further ahead; on video NVDEC decodes `decode._NVDEC_AHEAD` (16) device
frames ahead on the GPU.

**No failure deadlocks.** The dispatcher puts with a timeout and checks a
stop event between tries, as `decode._NvdecCapture._produce` does, and at
every timeout checks that each worker thread lives. A worker that raises
records its exception and sets the stop event; the dispatcher closes the
source, stops and joins every worker, and returns a `StagedRun` whose
`status` is "failed" with that exception. Frames offered and frames fed are
counted per reader, and a mismatch fails the run too. A lost frame therefore
fails the run rather than writing a refusal; the reason lands in `status`.

**OpenCV threads, one rule.** OpenCV's thread count is process-wide, and
`passes._feed` sets it around each reader that declares `cv_threads`. Under
threads that toggle races, so a staged pass with `workers >= 1` sets the
count once for the pass -- one thread unless the caller names another --
restores it afterwards, and refuses a reader that declares a different count.
`workers=0` feeds inline through `passes._feed`, toggles included, in the
serial path's order: list order on the cache, as `run_cached` feeds, and the
order of the frozenset `sample_multi` yields on video, as `passes.run` feeds.
It therefore reproduces the serial path exactly on either source.

**Workers.** `workers` caps how many feeds run at once, through a semaphore;
every reader or shard still gets its own thread and FIFO, so `workers=1`
exercises the queues, shards and merge on one core while the source overlaps
them. `workers=0` runs inline, with no thread and no queue.

**Shards:** see `_Shards`, whose docstring is the `shardable` contract.

**A prefix:** `limit_to_prefix` limits either pass, serial or staged, on
either source, to the frames observed before a time (`scan --until`).

Infrastructure: it hands frames to readers and decides nothing about what any
reader reads or what a stored row means.
"""

from __future__ import annotations

import copy
import hashlib
import math
import queue
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .passes import _cache_rois, _feed, cache_backend, cache_feed

#: Frames each reader's or shard's FIFO holds; see the module docstring.
FIFO_DEPTH = 8
#: How long a blocked put or get waits before it checks the stop event and
#: the workers' liveness.
POLL_S = 0.1
#: OpenCV's thread count for a staged pass with workers, unless the caller
#: names another.
STAGED_CV_THREADS = 1

_END = object()


class _Stopped(Exception):
    """The stop event fired while the dispatcher waited."""


@dataclass
class StagedRun:
    """What a staged pass did: frames, per-reader counts, status and results.

    `status` is "completed" or "failed"; on failure `error` names the reader
    and exception, `exception` holds it, and no reader was finished, so the
    caller publishes nothing. `finished` maps each reader with a `finish` to
    what it returned. `units` lists each worker's FIFO, one per reader or
    shard: its `label`, `reader`, frames `fed`, `max_queued`, `busy_ns` (the
    wall its feeds took) and `thread_cpu_ns` (its thread's CPU, read inside
    the thread at start and end). With `workers` 0 nothing queues and no
    thread starts, so `max_queued` and `thread_cpu_ns` are None.
    """

    frames: int = 0
    status: str = "completed"
    error: str | None = None
    exception: BaseException | None = None
    offered: dict[str, int] = field(default_factory=dict)
    fed: dict[str, int] = field(default_factory=dict)
    finished: dict[str, object] = field(default_factory=dict)
    workers: int = 0
    shards: dict[str, int] = field(default_factory=dict)
    cv_threads: dict = field(default_factory=dict)
    wait_ns: int = 0
    max_queued: dict[str, int] = field(default_factory=dict)
    units: list[dict] = field(default_factory=list)

    def raise_for_status(self) -> None:
        if self.exception is not None:
            raise self.exception
        if self.status != "completed":
            raise RuntimeError(self.error or self.status)


class _Shards:
    """A shardable reader split K ways, and the merge that puts it back.

    **The contract.** A reader declares `shardable`: the names of the list
    attributes its `feed` appends to (`AllyIconReader`: `frames`, `icons`,
    `candidates`). Declaring it promises that `feed` reads no state an
    earlier frame wrote and changes nothing but those lists, so a copy fed any
    subset of the frames produces exactly those frames' entries.

    The pipeline copies the reader K times after `frames_from` is set, each
    copy with its declared lists emptied; the i-th frame offered to the reader
    goes to shard i mod K. Each shard records, per frame, the producer
    position (the frame's index in the source) and the slice of each list that
    the frame appended. The merge concatenates those slices in producer
    order, keeping each slice's own order -- the order `feed` appended within
    the frame. The merged lists therefore equal the serial lists element for
    element, and anything hashed from them in order keeps its hash: the
    candidate revision is `candidate_evidence.revision`, a SHA-256 of
    canonical JSON with lists in order. A sort by key would change it, since
    `feed` appends a frame's self candidates before its ally ones, each by raw
    index. A shard that rebinds any other attribute, or appends outside
    `feed`, breaks the promise, and the merge raises. The copies share every
    other attribute, so an in-place write escapes that check: every ndarray
    the reader holds (`AllyIconReader`'s `floor`, `slab`, `static`) turns
    read-only for the pass, and a write into one raises at once; `release`
    restores the flags it cleared. A dict, set or undeclared list mutated in
    place stays invisible to the merge; the contract forbids it.
    `finish`, if the reader has one, runs once, on the merged original.
    """

    def __init__(self, reader, k: int):
        names = tuple(getattr(reader, "shardable", None) or ())
        if not names:
            raise ValueError(f"{reader.name} declares no `shardable` outputs")
        for name in names:
            if not isinstance(getattr(reader, name, None), list):
                raise ValueError(f"{reader.name}.{name} is not a list")
        self.reader, self.names = reader, names
        self.copies = []
        for _ in range(k):
            shard = copy.copy(reader)
            for name in names:
                setattr(shard, name, [])
            self.copies.append(shard)
        # Per shard: (producer position, list lengths before, lengths after).
        self.marks: list[list[tuple[int, tuple, tuple]]] = [[] for _ in range(k)]
        self.offered = 0
        self.frozen: list[np.ndarray] = []
        for value in vars(reader).values():
            if isinstance(value, np.ndarray) and value.flags.writeable:
                value.setflags(write=False)
                self.frozen.append(value)

    def release(self) -> None:
        """Make writeable again the arrays `__init__` made read-only."""
        for value in self.frozen:
            value.setflags(write=True)
        self.frozen = []

    def route(self) -> int:
        k = self.offered % len(self.copies)
        self.offered += 1
        return k

    def feed(self, k: int, pos: int, feed) -> None:
        shard = self.copies[k]
        before = tuple(len(getattr(shard, n)) for n in self.names)
        feed(shard)
        self.marks[k].append((pos, before, tuple(len(getattr(shard, n)) for n in self.names)))

    def merge(self) -> None:
        own = vars(self.reader)
        for k, shard in enumerate(self.copies):
            for attr, value in vars(shard).items():
                if attr not in self.names and value is not own.get(attr):
                    raise ValueError(f"shard {k} of {self.reader.name} rebound "
                                     f"`{attr}`, which `shardable` does not declare")
        for j, name in enumerate(self.names):
            pieces = []
            for k, shard in enumerate(self.copies):
                got = getattr(shard, name)
                marks = self.marks[k]
                if sum(after[j] - before[j] for _, before, after in marks) != len(got):
                    raise ValueError(f"shard {k} of {self.reader.name} appended to "
                                     f"`{name}` outside `feed`")
                pieces += [(pos, got[before[j]:after[j]]) for pos, before, after in marks]
            pieces.sort(key=lambda p: p[0])       # positions are unique across shards
            merged = getattr(self.reader, name)
            for _, piece in pieces:
                merged.extend(piece)


class _Unit:
    """One worker's FIFO and thread: a reader, or one shard of it."""

    def __init__(self, label: str, reader, shards: _Shards | None, k: int, depth: int):
        self.label, self.reader, self.shards, self.k = label, reader, shards, k
        self.fifo: queue.Queue = queue.Queue(maxsize=depth)
        self.thread: threading.Thread | None = None
        self.fed = 0
        self.max_queued = 0
        self.ended = False
        self.busy_ns = 0
        self.thread_cpu_ns: int | None = None


class PrefixCache:
    """A crop cache seen up to a limit: only its frames observed before `until_ms`.

    `samples` asks the cache for those timestamps alone, so reading stops at
    the limit. `record` is the cache's, with a version that names the limit;
    the runner copies that version into each reader's `frames_from`.
    """

    def __init__(self, cache, until_ms: float):
        self.cache, self.until_ms = cache, float(until_ms)
        self.record = {**cache.record,
                       "version": f"{cache.record['version']}, t < {until_ms:g} ms"}
        self.t_ms = cache.t_ms[cache.t_ms < self.until_ms]

    def samples(self, targets_ms, rois=None):
        return self.cache.samples([t for t in targets_ms if t < self.until_ms], rois=rois)


def limit_to_prefix(readers: list, until_ms: float, cache=None):
    """Offer the pass only frames observed before `until_ms`; returns its source.

    Call it where spans are chosen, after `roi_cache.cache_for` has chosen
    the source: a whole-capture reader given a span would make `cache_for`
    refuse a whole-capture cache. Each reader's spans are cut at the limit,
    and a whole-capture reader gets one span open at its start, from
    `-inf`, as new lists, since readers share their span lists. Spans are
    closed, so each ends at the float just below the limit, and a frame
    observed at the limit itself is not offered. Inside the prefix the
    readers get the frames a whole pass gives them: the open span keeps a
    first frame observed before 0 ms, which a span from 0 dropped, shifting
    every later sample's phase; a cut span keeps its phase.

    **Video.** `decode.sample_multi` stops, not skips: past every reader's
    last span end it breaks out of its loop and releases the capture
    (decode.py:519-523, 533-534, 559-560). It grabs one frame at or past the
    limit to learn its time and retrieves nothing past it; NVDEC may have
    decoded up to `decode._NVDEC_AHEAD` (16) frames further on the GPU, which
    `release` stops. `frames_from` gains the limit here: `video, t < 7000 ms`.

    **Crop cache.** The returned `PrefixCache` holds only the timestamps
    below the limit, so the cache stops reading there, while `run_cached`'s
    span filter still decides who gets each frame and thins nothing.
    Returns None for a decode, else the `PrefixCache` to pass instead of
    `cache`.
    """
    end = math.nextafter(float(until_ms), -math.inf)
    for r in readers:
        spans = getattr(r, "spans", None)
        r.spans = ([(-math.inf, end)] if spans is None
                   else [(float(a), min(float(b), end)) for a, b in spans if a <= end])
        if cache is None and hasattr(r, "frames_from"):
            r.frames_from = f"{r.frames_from}, t < {until_ms:g} ms"
    return None if cache is None else PrefixCache(cache, until_ms)


def _source_items(ctx, readers: list, source, usage=None):
    """The chosen source's items, and its rule for who wants each one.

    `source` None decodes the capture through `sample_multi`; anything else
    is a crop cache (`roi_cache.RoiCache`), fed under `run_cached`'s rule.
    """
    if source is None:
        from .decode import sample_multi
        req = {r.name: (r.hz, r.spans) for r in readers}
        by_name = {r.name: r for r in readers}
        backend = {}
        if usage is not None:
            usage.decode_backend = backend      # filled when the capture opens
        items = sample_multi(str(ctx.media), ctx.fps, req, info=backend)
        # `passes.run`'s order: the frozenset's, not the list's.
        return items, lambda item: (item[1], [by_name[name] for name in item[0]])
    rois = sorted({roi for r in readers for roi in _cache_rois(r)})
    for r in readers:
        r.frames_from = source.record["version"]
    if usage is not None:
        usage.decode_backend = cache_backend(source)
    # `run_cached`'s rule: spans, and a resampling reader's own grid.
    times, wants = cache_feed(readers, source)
    items = source.samples(times, rois=rois)
    return items, lambda smp: (smp, wants(smp))


def _read_only(smp) -> None:
    frame = getattr(smp, "frame", None)
    if frame is not None and hasattr(frame, "setflags"):
        frame.setflags(write=False)


def run_staged(ctx, readers: list, source=None, workers: int = 1,
               shards: dict[str, int] | None = None, usage=None, progress=None,
               cv_threads: int | None = None, depth: int = FIFO_DEPTH) -> StagedRun:
    """Drive `readers` over one source through per-reader FIFOs and threads.

    `source` is None for a decode, or the `RoiCache` `roi_cache.cache_for`
    chose. `shards` maps a reader's name to K > 1 for a reader that declares
    `shardable`. `usage` is the scan's `ScanUsage`, timed as the serial
    passes time it. `cv_threads` overrides OpenCV's count for the pass (see
    the module docstring). Returns a `StagedRun`; on failure its `status` says
    why, and no reader is finished.
    """
    import cv2

    names = [r.name for r in readers]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise ValueError(f"reader names must be unique: {', '.join(duplicates)}")
    shards = {name: int(k) for name, k in (shards or {}).items() if int(k) > 1}
    unknown = sorted(set(shards) - set(names))
    if unknown:
        raise ValueError(f"--shard names no reader in this pass: {', '.join(unknown)}")
    if workers < 0:
        raise ValueError("workers must be 0 or more")
    inline = workers == 0
    declared = {r.name: r.cv_threads for r in readers
                if getattr(r, "cv_threads", None) is not None}
    pass_threads = cv_threads
    if not inline:
        pass_threads = STAGED_CV_THREADS if cv_threads is None else cv_threads
        other = {n: c for n, c in declared.items() if c != pass_threads}
        if other:
            raise ValueError(f"readers declare other OpenCV counts than the pass's "
                             f"{pass_threads}: {other}")

    result = StagedRun(workers=workers, shards=dict(shards))
    items, split = _source_items(ctx, readers, source, usage)
    sharded: dict[str, _Shards] = {}
    units: dict[str, list[_Unit]] = {}
    every: list[_Unit] = []
    offered: Counter = Counter()
    stop = threading.Event()
    errors: list[tuple[str, BaseException]] = []
    sem = threading.BoundedSemaphore(max(1, workers))

    def feed_unit(unit: _Unit, pos: int, smp) -> None:
        start = time.perf_counter_ns()

        def call(reader):
            if inline:
                _feed(reader, smp, usage)
            elif usage is None:
                reader.feed(smp)
            else:
                usage.feed(reader, smp)
        if unit.shards is None:
            call(unit.reader)
        else:
            unit.shards.feed(unit.k, pos, call)
        unit.fed += 1
        unit.busy_ns += time.perf_counter_ns() - start

    def work(unit: _Unit) -> None:
        own = time.thread_time_ns()
        try:
            while True:
                try:
                    item = unit.fifo.get(timeout=POLL_S)
                except queue.Empty:
                    if stop.is_set():
                        return
                    continue
                if item is _END or stop.is_set():
                    return
                pos, smp = item
                with sem:
                    feed_unit(unit, pos, smp)
        except BaseException as exc:          # handed to the dispatcher, not lost
            errors.append((unit.label, exc))
            stop.set()
        finally:
            unit.thread_cpu_ns = time.thread_time_ns() - own

    def put(unit: _Unit, item) -> None:
        start = time.perf_counter_ns()
        try:
            while True:
                if stop.is_set():
                    raise _Stopped
                try:
                    unit.fifo.put(item, timeout=POLL_S)
                    unit.max_queued = max(unit.max_queued, unit.fifo.qsize())
                    return
                except queue.Full:
                    dead = [u for u in every if not u.ended and u.thread is not None
                            and not u.thread.is_alive()]
                    if dead:
                        if not errors:
                            errors.append((dead[0].label, RuntimeError(
                                f"worker {dead[0].label} ended without an exception")))
                        stop.set()
                        raise _Stopped
        finally:
            result.wait_ns += time.perf_counter_ns() - start

    before_threads = cv2.getNumThreads()
    timed = None
    n = 0
    try:
        # Setup sits inside the try: an exception or an interrupt here still
        # stops and joins the workers started so far, releases the shards'
        # arrays and restores the OpenCV count. Shards are copied only now,
        # after `_source_items` has set `frames_from`.
        for r in readers:
            if r.name in shards:
                sharded[r.name] = _Shards(r, shards[r.name])
            s = sharded.get(r.name)
            units[r.name] = ([_Unit(f"{r.name}#{k}", r, s, k, depth)
                              for k in range(len(s.copies))]
                             if s is not None else [_Unit(r.name, r, None, 0, depth)])
        every.extend(u for us in units.values() for u in us)
        if pass_threads is not None:
            cv2.setNumThreads(pass_threads)
        result.cv_threads = {"pass": cv2.getNumThreads(),
                             "toggled": sorted(declared) if inline else []}
        if not inline:
            for u in every:
                u.thread = threading.Thread(target=work, args=(u,), daemon=True,
                                            name=f"reader:{u.label}")
                u.thread.start()
        timed = usage.timed_frames(items) if usage is not None else items
        try:
            for item in timed:
                smp, wanting = split(item)
                pos = n
                n += 1
                if wanting:
                    _read_only(smp)
                for r in wanting:
                    us = units[r.name]
                    unit = us[sharded[r.name].route()] if r.name in sharded else us[0]
                    offered[r.name] += 1
                    if inline:
                        try:
                            feed_unit(unit, pos, smp)
                        except Exception as exc:
                            errors.append((unit.label, exc))
                            stop.set()
                            raise _Stopped from exc
                    else:
                        put(unit, (pos, smp))
                if progress is not None:
                    progress(n, smp)
                if stop.is_set():
                    break
            if not inline:
                for u in every:
                    put(u, _END)
                    u.ended = True
        except _Stopped:
            pass
        except Exception as exc:              # the source raised
            errors.append(("source", exc))
            stop.set()
    finally:
        for it in (timed, items):
            close = getattr(it, "close", None)
            if callable(close):
                close()
        if not inline:
            # Workers not sent their end marker (a failure, or an interrupt
            # here) stop at their next poll instead of waiting for it.
            if not all(u.ended for u in every):
                stop.set()
            for u in every:
                if u.thread is not None:
                    u.thread.join()
        for s in sharded.values():
            s.release()
        cv2.setNumThreads(before_threads)

    result.frames = n
    result.offered = dict(offered)
    result.fed = {name: sum(u.fed for u in us) for name, us in units.items()}
    result.max_queued = {u.label: u.max_queued for u in every}
    result.units = [{"label": u.label, "reader": u.reader.name, "fed": u.fed,
                     "max_queued": None if inline else u.max_queued,
                     "busy_ns": u.busy_ns, "thread_cpu_ns": u.thread_cpu_ns}
                    for u in every]
    lost = {name: (offered.get(name, 0), result.fed[name]) for name in units
            if offered.get(name, 0) != result.fed[name]}
    if errors:
        label, exc = errors[0]
        result.status, result.exception = "failed", exc
        result.error = f"{label}: {type(exc).__name__}: {exc}"
        return result
    if lost:
        result.status = "failed"
        result.error = "frames offered and fed differ: " + ", ".join(
            f"{name} {a} offered, {b} fed" for name, (a, b) in sorted(lost.items()))
        return result
    for s in sharded.values():
        s.merge()
    for r in readers:
        fin = getattr(r, "finish", None)
        if callable(fin):
            if usage is None:
                result.finished[r.name] = fin()
            else:
                got = []
                usage.finish(r, lambda: got.append(fin()))
                result.finished[r.name] = got[0] if got else None
    return result


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _table_difference(a: Path, b: Path) -> str | None:
    """None when two Parquet files hold the same rows, else where they part."""
    import pyarrow.parquet as pq

    ta, tb = pq.read_table(a), pq.read_table(b)
    if ta.schema.remove_metadata() != tb.schema.remove_metadata():
        return "schemas differ"
    if ta.num_rows != tb.num_rows:
        return f"{ta.num_rows} rows against {tb.num_rows}"
    for name in ta.column_names:
        ca, cb = ta.column(name).to_pylist(), tb.column(name).to_pylist()
        for i, (x, y) in enumerate(zip(ca, cb)):
            if x != y and not (x != x and y != y):     # NaN equals NaN here
                return f"column {name} row {i}: {x!r} against {y!r}"
    return None


def _text_difference(a: Path, b: Path) -> str:
    la = a.read_text(encoding="utf-8").splitlines()
    lb = b.read_text(encoding="utf-8").splitlines()
    for i, (x, y) in enumerate(zip(la, lb)):
        if x != y:
            return f"line {i + 1} differs"
    return f"{len(la)} lines against {len(lb)}"


def compare_trees(a: Path, b: Path, skip: tuple[str, ...] = ("notes/",)) -> list[dict]:
    """Every file under either root, by relative path, compared byte for byte.

    Each entry has `path`, `verdict` ("equal", "differs", "only in a" or
    "only in b"), `rows_differ` and `detail`. Where Parquet bytes differ the
    tables are compared row for row, so a difference in metadata alone reads
    as bytes only. Paths under `skip` (each run's own usage and metrics
    records) are left out.
    """
    a, b = Path(a), Path(b)
    rels = sorted({p.relative_to(root).as_posix()
                   for root in (a, b) if root.is_dir()
                   for p in root.rglob("*") if p.is_file()})
    out = []
    for rel in rels:
        if any(rel.startswith(s) for s in skip):
            continue
        fa, fb = a / rel, b / rel
        if not fa.is_file() or not fb.is_file():
            out.append({"path": rel, "verdict": "only in a" if fa.is_file() else "only in b",
                        "rows_differ": True, "detail": ""})
            continue
        ha, hb = _file_sha256(fa), _file_sha256(fb)
        if ha == hb:
            out.append({"path": rel, "verdict": "equal", "rows_differ": False,
                        "detail": f"sha256 {ha[:12]}"})
        elif rel.endswith(".parquet"):
            why = _table_difference(fa, fb)
            out.append({"path": rel, "verdict": "differs", "rows_differ": why is not None,
                        "detail": why or "bytes only: the rows are equal, the metadata is not"})
        else:
            out.append({"path": rel, "verdict": "differs", "rows_differ": True,
                        "detail": _text_difference(fa, fb)})
    return out
