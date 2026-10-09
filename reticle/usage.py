"""Operational scan timings, separate from observation and accuracy evidence.

One JSON line records a scan. Source time is shared by all readers. In a
serial pass the source and every reader's feed run one after another on one
thread, so their times exclude each other and sum to at most the pass. In a
staged pass the readers feed on their own threads while the source reads, so
their times overlap it and each other, may sum past the pass, and
`pass_other_ns` clamps to 0. Buckets retain call frequencies without a
per-frame file or unbounded in-memory samples.

`scan-usage-2` adds how the pass ran: `pipeline` (`serial` or `staged`),
`workers`, `shards`, `cv_threads`, `code_revision` (HEAD's short sha and
whether the tree differs from it) and `error`; `status` says `failed` when a
staged pass ended on a reader's exception. A staged pass also records what
it did rather than what was asked: per reader the frames `offered` and
`fed`, and under `shards` each worker's FIFO (one per reader, or one per
shard) with its frames `fed` and `max_queued`; `dispatcher.wait_ns` is the
time the dispatcher blocked on full FIFOs. A serial pass records `offered`
and `fed` as its feed count, no `shards` and a null `wait_ns`: nothing
queues. `until_s` is the prefix limit of `scan --until`, null for the whole
capture. `load` reads every version.

`scan-usage-3` adds what decoded the pass and what else ran beside it.
`decode_backend` is `decode.capture_backend`'s answer for a decode
(`nvdec` or `opencv`, `RETICLE_DECODE`'s mode, and in `auto` the NVDEC
failure that made it fall back) or `passes.cache_backend`'s for the crop
cache (OpenCV and the cache's codec); null when nothing opened.
`contention` covers the same span as `cpu_ns`: `system_cpu_ns` is the
busy CPU of every logical processor, `other_cpu_ns` that less this
process's `cpu_ns`, the load of everything else, `logical_cpus` the
count, and `priority` this process's class; a platform without a system
counter leaves the two CPU figures null with a `reason`. Other load,
spread over the logical processors, is `other_cpu_ns / (pass_ns *
logical_cpus)`.

**CPU time.** `cpu_ns` is the process's user and system CPU over `pass_ns`
(`time.process_time_ns`). `dispatcher.thread_cpu_ns` is the CPU of the
thread that ran the pass, the one that reads the source, and each worker
thread measures its own (`time.thread_time_ns`, read in the thread at its
start and end) under `readers[<name>].shards`; `readers[<name>].thread_cpu_ns`
sums a reader's shards. A serial pass, and a staged one at `workers` 0,
feeds on the dispatcher thread, so that thread's CPU covers source and
readers together and each reader's `thread_cpu_ns` is null with a
`thread_cpu_reason`. Each shard's `busy_ns` is the wall its feeds took on
that thread. A worker whose CPU is close to its `busy_ns` computed while it
fed; one far below waited inside `feed`, for the GIL or for a core. Across
workers, CPU summing to about the workers' walls means they ran in
parallel, and CPU summing to one thread's wall means one ran at a time.
Windows counts thread and process CPU in clock ticks of about 15.6 ms, so a
figure under a few ticks says little.

`scan-usage-4` adds each reader's `steps`: the time its `feed` spent in
the named steps the reader marks with `step("name")`, one `CallTimes`
record per step (`count`, `total_ns`, `max_ns`, `buckets`) keyed by its
path. A step entered inside another is keyed `outer/inner` and its time is
part of its parent's. `other` is each feed call's wall less its top-level
steps, so the top-level steps and `other` sum to the reader's `feed`
total, and its `count` is the feed calls. A reader that marks no step
records `{}`. Each thread keeps its own accumulator per reader, so the
step path takes no lock, and `record` merges them: a staged pass's workers
and shards sum as their `feed` does. A step outside any timed feed (a
test, a prototype) costs one thread-local lookup and records nothing.
Timing is operational: it changes no reader output and no version stamp.
`reticle usage` prints the steps under each reader; `reticle trial` prints
them for its reader.

**The switch.** `RETICLE_USAGE` sets how much the profiler does, read when a
record starts: `steps` (the default) records the line and its steps; `record`
writes the per-scan or per-command line only, with `steps` as `{}`, and times
no step; `off` writes no record, runs no `git`, reads no system counter and
times no step, so a `step` costs one thread-local lookup and `write` and
`write_metric` return None. The older `RETICLE_USAGE_STEPS=0` is a deprecated
alias for `record`; `RETICLE_USAGE` wins when both are set. Anything that
reads `notes/usage.jsonl` must tolerate its absence: `load` returns `[]`.

`command-usage-1` records a stored-data command, one line beside the scan
lines in `notes/usage.jsonl` with `kind: "command"`: `command`, `arguments`,
`session_id`, `recorded_at`, `wall_ns`, `cpu_ns`, `contention` (as in a scan),
`code_revision`, `status` (`completed`, or `failed` with `error` when the
command raised; the exception propagates), `exit_code` and `steps`. The
command is the one reader, so every `step` inside its call tree records, on
the calling thread only. The set is `plan.rerun_commands()`, the commands the
plan names as rerunning a derived stream from storage or the crop cache,
plus `rounds`; `scan` writes its own record and a command that decodes is
not in it. `cli.main` wraps them once. `Store`'s read paths time themselves
as `read:<stream>` steps (`read:killfeed_portrait`, `read:hud`; a version
probe is `read:<stream>:version`), with the file's `bytes` where the method
reads the whole file; a read inside a step keys `outer/read:x`. With no
sink active a read costs one thread-local lookup. `reticle usage` prints
each command's steps, then `reads`: per stream the calls, seconds and bytes
across every path.

**Citing a scan.** `write_metric` appends a `scan_usage` pass row whose part
names the readers and then how the pass ran (`series_part`), so each
configuration is its own series: QUOTED compares a citation with the latest
pass row of its series and ignores `deps`, and a serial rerun must not
become the row a staged figure is checked against. A document cites the
pass time of a staged HUD pass from the crop cache at one worker as

    [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb#pass_s=<seconds>]

with `<seconds>` the row's `pass_s` at the precision the prose states.
Every scan of the session appends a row to the series, so a figure that
describes one run pins it with the first characters of the row's
`usage_run_id`, as `...cv1@c40d950031bb~cf98e5c94cbc#pass_s=<seconds>`, and
QUOTED checks it against that run rather than the latest. The
row's other fields cite the same way: `source_s`, `cpu_s`,
`dispatcher_cpu_s`, `dispatcher_wait_s` (staged at one worker or more), and
per reader `feed_s_<reader>` and, when known, `thread_cpu_s_<reader>`, the
reader's name with every character outside `[A-Za-z0-9_]` made `_`. The
serial pass of the same readers is the series
`scan_usage/hud+killfeed_portrait/cache/serial/cv12` on this machine's
OpenCV pool. `reticle/quoted.py` lists this module in `EXAMPLE_ONLY`, so
the example above is not read as a citation.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
from functools import wraps
from contextlib import contextmanager
import json
import os
from pathlib import Path
import re
import subprocess
import threading
from time import perf_counter_ns, process_time_ns, thread_time_ns
from uuid import uuid4


USAGE_VERSION = "scan-usage-4"
COMMAND_VERSION = "command-usage-1"
#: Versions `load` reads; each later one only adds keys.
USAGE_VERSIONS = ("scan-usage-1", "scan-usage-2", "scan-usage-3", USAGE_VERSION,
                  COMMAND_VERSION)
LEVELS = ("off", "record", "steps")
#: Why a reader's own thread CPU is null when it fed on the dispatcher thread.
INLINE_REASON = "fed on the dispatcher thread; see dispatcher.thread_cpu_ns"
BUCKET_LIMITS_NS = (100_000, 500_000, 1_000_000, 2_000_000,
                    5_000_000, 10_000_000, 50_000_000, 100_000_000)


class CallTimes:
    def __init__(self):
        self.count = 0
        self.total_ns = 0
        self.max_ns = 0
        self.bytes = 0
        self.buckets = [0] * (len(BUCKET_LIMITS_NS) + 1)

    def add(self, elapsed_ns: int) -> None:
        self.count += 1
        self.total_ns += elapsed_ns
        self.max_ns = max(self.max_ns, elapsed_ns)
        self.buckets[bisect_right(BUCKET_LIMITS_NS, elapsed_ns)] += 1

    def record(self) -> dict:
        row = {"count": self.count, "total_ns": self.total_ns,
               "max_ns": self.max_ns, "buckets": self.buckets}
        if self.bytes:
            row["bytes"] = self.bytes
        return row

    def merge(self, other: "CallTimes") -> None:
        self.count += other.count
        self.total_ns += other.total_ns
        self.max_ns = max(self.max_ns, other.max_ns)
        self.bytes += other.bytes
        self.buckets = [a + b for a, b in zip(self.buckets, other.buckets)]


def usage_level() -> str:
    """`off`, `record` or `steps`: `RETICLE_USAGE`, else `record` under the
    deprecated `RETICLE_USAGE_STEPS=0`, else `steps`; see the module docstring."""
    level = os.environ.get("RETICLE_USAGE", "").strip().lower()
    if not level:
        return "record" if os.environ.get("RETICLE_USAGE_STEPS", "1") == "0" else "steps"
    if level not in LEVELS:
        raise ValueError(f"RETICLE_USAGE={level!r}: expected one of {', '.join(LEVELS)}")
    return level


#: The step that holds a feed's time outside its top-level steps.
OTHER_STEP = "other"
_LOCAL = threading.local()


class _Sink:
    """One thread's step times for one reader; the active one sits on `_LOCAL`."""
    __slots__ = ("steps", "stack", "top_ns")

    def __init__(self):
        self.steps: dict[str, CallTimes] = {}
        self.stack: list[str] = []
        self.top_ns = 0


class step:
    """Time a named step of the reader feeding on this thread.

    `with step("grid"): ...`, one object per use. A step inside another is
    keyed by its path (`pose/grid`). With no feed timed on this thread it
    records nothing.
    """
    __slots__ = ("name", "sink", "path", "t0", "bytes")

    def __init__(self, name: str):
        self.name = name
        self.sink = None
        self.bytes = 0

    def __enter__(self):
        sink = getattr(_LOCAL, "sink", None)
        if sink is not None:
            stack = sink.stack
            self.path = f"{stack[-1]}/{self.name}" if stack else self.name
            stack.append(self.path)
            self.sink = sink
            self.t0 = perf_counter_ns()
        return self

    def __exit__(self, *exc) -> bool:
        sink = self.sink
        if sink is None:
            return False
        elapsed = perf_counter_ns() - self.t0
        stack = sink.stack
        stack.pop()
        if not stack:
            sink.top_ns += elapsed
        times = sink.steps.get(self.path)
        if times is None:
            times = sink.steps[self.path] = CallTimes()
        times.add(elapsed)
        times.bytes += self.bytes
        return False


def timed_read(locate):
    """Decorate a `Store` read method to time itself as a `read:<stream>` step.

    `locate(self, *args, **kwargs)` returns `(stream, path)`; `path` is the
    file read whole, whose size is recorded as `bytes`, or None. With no sink
    on this thread the wrapper makes one thread-local lookup and calls the
    method.
    """
    def decorate(fn):
        @wraps(fn)
        def wrapper(self, *args, **kwargs):
            if getattr(_LOCAL, "sink", None) is None:
                return fn(self, *args, **kwargs)
            stream, path = locate(self, *args, **kwargs)
            with step(f"read:{stream}") as timed:
                if path is not None:
                    try:
                        timed.bytes = path.stat().st_size
                    except OSError:
                        pass
                return fn(self, *args, **kwargs)
        return wrapper
    return decorate


class StepRecorder:
    """Feed calls' steps per reader, accumulated per thread.

    `feed(name, fn, sample)` runs `fn(sample)` with this thread's sink for
    `name` active and returns the call's wall in ns; `steps(name)` merges
    every thread's steps for the reader. `ScanUsage` and `trial` share it.
    """

    def __init__(self, enabled: bool | None = None):
        self.enabled = (usage_level() == "steps") if enabled is None else enabled
        self._sinks: dict[tuple[int, str], _Sink] = {}
        self._lock = threading.Lock()

    def _sink(self, name: str) -> _Sink:
        key = (threading.get_ident(), name)
        sink = self._sinks.get(key)
        if sink is None:
            with self._lock:
                sink = self._sinks.setdefault(key, _Sink())
        return sink

    def feed(self, name: str, fn, sample) -> int:
        if not self.enabled:
            start = perf_counter_ns()
            fn(sample)
            return perf_counter_ns() - start
        sink = self._sink(name)
        outer = getattr(_LOCAL, "sink", None)
        sink.stack.clear()
        sink.top_ns = 0
        _LOCAL.sink = sink
        start = perf_counter_ns()
        try:
            fn(sample)
        finally:
            elapsed = perf_counter_ns() - start
            _LOCAL.sink = outer
            times = sink.steps.get(OTHER_STEP)
            if times is None:
                times = sink.steps[OTHER_STEP] = CallTimes()
            times.add(max(0, elapsed - sink.top_ns))
        return elapsed

    def steps(self, name: str) -> dict:
        """`{path: CallTimes.record()}` over every thread; `{}` when the
        reader marked no step."""
        with self._lock:
            sinks = [s for (_, n), s in self._sinks.items() if n == name]
        merged: dict[str, CallTimes] = {}
        for sink in sinks:
            for path, times in list(sink.steps.items()):
                merged.setdefault(path, CallTimes()).merge(times)
        if set(merged) <= {OTHER_STEP}:
            return {}
        return {path: merged[path].record() for path in sorted(merged)}


def code_revision(root: Path | None = None) -> dict:
    """HEAD's short sha and whether the working tree differs from it.

    Null with a reason when git cannot say, never a guess.
    """
    root = Path(root) if root else Path(__file__).resolve().parent.parent
    try:
        sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root,
                             capture_output=True, text=True, timeout=30, check=True)
        status = subprocess.run(["git", "status", "--porcelain"], cwd=root,
                                capture_output=True, text=True, timeout=30, check=True)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"sha": None, "dirty": None, "reason": f"git failed: {type(exc).__name__}"}
    return {"sha": sha.stdout.strip(), "dirty": bool(status.stdout.strip())}


class ScanUsage:
    """Collect scan costs without retaining pixels or individual call traces."""

    def __init__(self, manifest: dict, profile: str, readers: list,
                 source: str):
        self.manifest = manifest
        self.run_id = uuid4().hex
        self.profile = profile
        self.source = source
        self.readers = {r.name: {"hz": r.hz,
                                 "spans": len(r.spans) if r.spans is not None else None,
                                 "feed": CallTimes(), "finish_ns": 0,
                                 "offered": None, "fed": None, "shards": [],
                                 "thread_cpu_ns": None, "thread_cpu_reason": INLINE_REASON}
                        for r in readers}
        self.frames = CallTimes()
        self.setup_ns = 0
        self.pass_ns = 0
        self.publish_ns = 0
        self.pipeline = "serial"
        self.workers = None
        self.shards: dict[str, int] = {}
        #: A reader fed in child processes (`process_shards`): what each cost.
        self.processes: dict[str, dict] = {}
        self.child_cpu_ns = 0
        self.cv_threads: dict | None = None
        self.wait_ns: int | None = None
        self.until_s: float | None = None
        self.cpu_ns: int | None = None
        self.dispatcher_cpu_ns: int | None = None
        self.level = usage_level()
        self.code_revision = code_revision() if self.level != "off" else None
        self.status = "completed"
        self.error: str | None = None
        self.decode_backend: dict | None = None
        self.system_cpu_ns: int | None = None
        # Shards of one reader share its name, and so its `CallTimes`.
        self._lock = threading.Lock()
        self.step_times = StepRecorder(self.level == "steps")

    @property
    def enabled(self) -> bool:
        return self.level != "off"

    @contextmanager
    def timed_pass(self):
        """Time the pass on the calling thread, the dispatcher.

        Sets `pass_ns` (wall), `cpu_ns` (the process's CPU) and the
        dispatcher's `thread_cpu_ns` over the same span, on failure too.
        """
        system = system_cpu_ns() if self.enabled else None
        wall, cpu, own = perf_counter_ns(), process_time_ns(), thread_time_ns()
        try:
            yield self
        finally:
            self.pass_ns = perf_counter_ns() - wall
            self.cpu_ns = process_time_ns() - cpu + self.child_cpu_ns
            self.dispatcher_cpu_ns = thread_time_ns() - own
            after = system_cpu_ns() if self.enabled else None
            self.system_cpu_ns = (after - system if None not in (system, after) else None)

    def contention(self) -> dict:
        """What else ran during the pass; see the module docstring."""
        return contention(self.system_cpu_ns, self.cpu_ns)

    def timed_frames(self, frames):
        iterator = iter(frames)
        while True:
            start = perf_counter_ns()
            try:
                frame = next(iterator)
            except StopIteration:
                break
            self.frames.add(perf_counter_ns() - start)
            yield frame

    def feed(self, reader, sample) -> None:
        elapsed = None
        start = perf_counter_ns()
        try:
            elapsed = self.step_times.feed(reader.name, reader.feed, sample)
        finally:
            if elapsed is None:     # the feed raised
                elapsed = perf_counter_ns() - start
            with self._lock:
                self.readers[reader.name]["feed"].add(elapsed)

    def finish(self, reader, finish) -> None:
        start = perf_counter_ns()
        try:
            finish()
        finally:
            self.readers[reader.name]["finish_ns"] += perf_counter_ns() - start

    def staged_run(self, run) -> None:
        """Copy what a staged pass did, a `pipeline.StagedRun`, into the record.

        The workers, shards and OpenCV count that ran, frames offered and fed
        per reader, each FIFO's count and depth, each worker thread's CPU and
        busy wall, the dispatcher's wait, and the status. `workers` 0 queues
        nothing and starts no thread, so its wait and its readers' thread
        CPU stay null.
        """
        self.pipeline = "staged"
        self.workers = run.workers
        self.shards = dict(run.shards)
        self.cv_threads = run.cv_threads
        self.wait_ns = run.wait_ns if run.workers else None
        for name, r in self.readers.items():
            r["offered"] = run.offered.get(name, 0)
            r["fed"] = run.fed.get(name, 0)
            r["shards"] = [{"label": u["label"], "fed": u["fed"],
                            "max_queued": u["max_queued"],
                            "thread_cpu_ns": u.get("thread_cpu_ns"),
                            "busy_ns": u.get("busy_ns")}
                           for u in run.units if u["reader"] == name]
            cpus = [u["thread_cpu_ns"] for u in r["shards"]]
            if not run.workers:
                r["thread_cpu_ns"], r["thread_cpu_reason"] = None, INLINE_REASON
            elif not cpus or None in cpus:
                r["thread_cpu_ns"] = None
                r["thread_cpu_reason"] = "a worker thread of this reader never ran"
            else:
                r["thread_cpu_ns"], r["thread_cpu_reason"] = sum(cpus), None
        if run.status != "completed":
            self.status, self.error = "failed", run.error

    def process_run(self, name: str, cost: dict) -> None:
        """Record a reader fed in child processes (`process_shards.ProcessRun.
        merge`): its frames, and their CPU, which `timed_pass` adds to this
        process's own in `cpu_ns`."""
        self.processes[name] = {k: v for k, v in cost.items() if k != "cpu_ns"}
        r = self.readers[name]
        # A gated reader's children feed fewer frames than they are offered.
        r["offered"] = sum(cost["frames"])
        r["fed"] = sum(cost.get("fed", cost["frames"]))
        r["thread_cpu_ns"] = cost["cpu_ns"]
        r["thread_cpu_reason"] = None
        self.child_cpu_ns += cost["cpu_ns"]

    def series_part(self) -> str:
        """The metrics part: readers, source, pipeline, workers, shards, OpenCV
        count, prefix.

        `hud+killfeed_portrait/cache/staged/w1/cv1`; a serial pass names no
        workers, a pass with shards names each as `READER=K`, and a prefix
        ends the part with `until<seconds>`.
        """
        source = "cache" if self.source.startswith("cache:") else self.source
        bits = ["+".join(sorted(self.readers)), source, self.pipeline]
        if self.pipeline == "staged":
            bits.append(f"w{1 if self.workers is None else self.workers}")
        bits += [f"{name}={k}" for name, k in sorted(self.shards.items())]
        bits += [f"{name}=p{p['processes']}" for name, p in sorted(self.processes.items())]
        count = (self.cv_threads or {}).get("pass")
        if count is not None:
            bits.append(f"cv{count}")
        if self.until_s is not None:
            bits.append(f"until{self.until_s:g}")
        return "/".join(bits)

    def record(self) -> dict:
        feed_ns = sum(r["feed"].total_ns for r in self.readers.values())
        finish_ns = sum(r["finish_ns"] for r in self.readers.values())
        source_ns = self.frames.total_ns
        return {
            "version": USAGE_VERSION,
            "run_id": self.run_id,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "kind": "vod_scan",
            "status": self.status,
            "error": self.error,
            "pipeline": self.pipeline,
            "workers": self.workers,
            "shards": dict(self.shards),
            "processes": dict(self.processes),
            "cv_threads": self.cv_threads,
            "code_revision": self.code_revision,
            "session_id": self.manifest["session_id"],
            "content_key": self.manifest["source"].get("content_key"),
            "profile": self.profile,
            "source": self.source,
            "until_s": self.until_s,
            "bucket_upper_ns": list(BUCKET_LIMITS_NS),
            "setup_ns": self.setup_ns,
            "pass_ns": self.pass_ns,
            "publish_ns": self.publish_ns,
            "source_calls": self.frames.record(),
            "cpu_ns": self.cpu_ns,
            "contention": self.contention(),
            "decode_backend": self.decode_backend or None,   # {} : never opened
            "dispatcher": {"thread_cpu_ns": self.dispatcher_cpu_ns, "wait_ns": self.wait_ns},
            # Serial: every frame offered is fed inline, one feed call each.
            "readers": {name: {"hz": r["hz"], "spans": r["spans"],
                                "feed": r["feed"].record(),
                                "finish_ns": r["finish_ns"],
                                "offered": (r["feed"].count if r["offered"] is None
                                            else r["offered"]),
                                "fed": r["feed"].count if r["fed"] is None else r["fed"],
                                "thread_cpu_ns": r["thread_cpu_ns"],
                                "thread_cpu_reason": r["thread_cpu_reason"],
                                "shards": [dict(u) for u in r["shards"]],
                                "steps": self.step_times.steps(name)}
                        for name, r in self.readers.items()},
            "pass_other_ns": max(0, self.pass_ns - source_ns - feed_ns - finish_ns),
        }

    def write(self, store_root: Path) -> Path | None:
        """Append the record; None, writing nothing, at `RETICLE_USAGE=off`."""
        return append_record(store_root, self.record()) if self.enabled else None

    def metric_values(self) -> dict:
        """The `pass` row's values, in seconds; see the module docstring.

        A value the record holds as null is left out, so no citation can
        quote it.
        """
        def s(ns):
            return round(ns / 1e9, 3)
        values = {"pass_s": s(self.pass_ns), "source_s": s(self.frames.total_ns),
                  "frames": self.frames.count}
        if self.cpu_ns is not None:
            values["cpu_s"] = s(self.cpu_ns)
        if self.dispatcher_cpu_ns is not None:
            values["dispatcher_cpu_s"] = s(self.dispatcher_cpu_ns)
        if self.wait_ns is not None:
            values["dispatcher_wait_s"] = s(self.wait_ns)
        other = self.contention()["other_cpu_ns"]
        if other is not None:
            values["other_cpu_s"] = s(other)
        for name, r in sorted(self.readers.items()):
            field = re.sub(r"\W", "_", name)
            values[f"feed_s_{field}"] = s(r["feed"].total_ns)
            if r["thread_cpu_ns"] is not None:
                values[f"thread_cpu_s_{field}"] = s(r["thread_cpu_ns"])
        return values

    def write_metric(self, store_root: Path) -> dict | None:
        """One `pass` row in `notes/metrics.jsonl` naming this record's run_id.

        Timings move from run to run with the machine's load, so the run_id
        is context, not a dependency: two runs of one configuration compare
        as CHANGED, never as BROKEN. None, writing nothing, at `off`.
        """
        if not self.enabled:
            return None
        from . import metrics
        return metrics.record(
            "scan_usage", part=self.series_part(),
            session=self.manifest["session_id"],
            values=self.metric_values(),
            deps={"usage_version": USAGE_VERSION, "source": self.source,
                  "pipeline": self.pipeline, "workers": self.workers,
                  "shards": dict(self.shards), "cv_threads": self.cv_threads,
                  "until_s": self.until_s, "code_revision": self.code_revision},
            context={"usage_run_id": self.run_id},
            log_path=Path(store_root) / "notes" / "metrics.jsonl",
            usage_run_id=self.run_id)


def append_record(store_root: Path, row: dict) -> Path:
    path = Path(store_root) / "notes" / "usage.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as out:
        out.write(json.dumps(row, separators=(",", ":"), default=str) + "\n")
    return path


def contention(system_ns: int | None, cpu_ns: int | None) -> dict:
    """What else ran over a span; see the module docstring."""
    other = (max(0, system_ns - cpu_ns)
             if None not in (system_ns, cpu_ns) else None)
    return {"system_cpu_ns": system_ns, "other_cpu_ns": other,
            "logical_cpus": os.cpu_count(), "priority": process_priority(),
            "reason": (None if other is not None
                       else "no system CPU counter on this platform")}


class CommandUsage:
    """One stored-data command's cost, `command-usage-1`; see the module docstring.

    `run(fn)` calls `fn()` with the command as the one reader of a
    `StepRecorder`, records wall, CPU and the outcome, and re-raises what
    `fn` raises. At `RETICLE_USAGE=off` it only calls `fn`.
    """

    def __init__(self, command: str, arguments: dict | None = None,
                 session_id: str | None = None, level: str | None = None):
        self.level = usage_level() if level is None else level
        self.run_id = uuid4().hex
        self.command = command
        self.arguments = json.loads(json.dumps(arguments or {}, default=str))
        self.session_id = session_id
        self.recorded_at = datetime.now(timezone.utc).isoformat()
        self.step_times = StepRecorder(self.level == "steps")
        self.wall_ns = self.cpu_ns = self.system_cpu_ns = None
        self.status, self.error, self.exit_code = "completed", None, None
        self.code_revision = None

    @property
    def enabled(self) -> bool:
        return self.level != "off"

    def run(self, fn):
        if not self.enabled:
            return fn()
        self.code_revision = code_revision()
        system = system_cpu_ns()
        wall, cpu = perf_counter_ns(), process_time_ns()
        result = []
        try:
            self.step_times.feed(self.command, lambda _: result.append(fn()), None)
        except BaseException as exc:
            self.status, self.error = "failed", f"{type(exc).__name__}: {exc}"
            if isinstance(exc, SystemExit):
                self.exit_code = exc.code
            raise
        finally:
            self.wall_ns = perf_counter_ns() - wall
            self.cpu_ns = process_time_ns() - cpu
            after = system_cpu_ns()
            self.system_cpu_ns = (after - system if None not in (system, after) else None)
        if isinstance(result[0], int):
            self.exit_code = result[0]
        return result[0]

    def record(self) -> dict:
        return {"version": COMMAND_VERSION, "run_id": self.run_id,
                "recorded_at": self.recorded_at, "kind": "command",
                "command": self.command, "arguments": self.arguments,
                "session_id": self.session_id, "status": self.status,
                "error": self.error, "exit_code": self.exit_code,
                "code_revision": self.code_revision,
                "wall_ns": self.wall_ns, "cpu_ns": self.cpu_ns,
                "contention": contention(self.system_cpu_ns, self.cpu_ns),
                "steps": self.step_times.steps(self.command)}

    def write(self, store_root: Path) -> Path | None:
        """Append the record; None, writing nothing, at `off` or before `run`."""
        if not self.enabled or self.wall_ns is None:
            return None
        return append_record(store_root, self.record())


def system_cpu_ns() -> int | None:
    """Busy CPU of every logical processor since boot, in ns, or None.

    Windows: `GetSystemTimes`, whose kernel time includes idle. Linux:
    `/proc/stat`'s first line, in clock ticks. Elsewhere None.
    """
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        idle, kernel, user = (wintypes.FILETIME(), wintypes.FILETIME(), wintypes.FILETIME())
        if not ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
            return None

        def ft(t):
            return (t.dwHighDateTime << 32) | t.dwLowDateTime
        return (ft(kernel) + ft(user) - ft(idle)) * 100
    try:
        with open("/proc/stat", encoding="ascii") as f:
            fields = [int(x) for x in f.readline().split()[1:]]
    except (OSError, ValueError):
        return None
    busy = sum(fields) - fields[3] - (fields[4] if len(fields) > 4 else 0)
    return busy * 1_000_000_000 // os.sysconf("SC_CLK_TCK")


def process_priority() -> str | int | None:
    """This process's priority: its Windows class by name, else its nice."""
    if os.name == "nt":
        import ctypes
        classes = {0x40: "idle", 0x4000: "below_normal", 0x20: "normal",
                   0x8000: "above_normal", 0x80: "high", 0x100: "realtime"}
        k = ctypes.windll.kernel32
        k.GetCurrentProcess.restype = ctypes.c_void_p
        k.GetPriorityClass.argtypes = [ctypes.c_void_p]
        return classes.get(k.GetPriorityClass(k.GetCurrentProcess()))
    try:
        return os.getpriority(os.PRIO_PROCESS, 0)
    except (AttributeError, OSError):
        return None


def load(store_root: Path, session_id: str | None = None) -> list[dict]:
    path = Path(store_root) / "notes" / "usage.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    return [row for row in rows if row.get("version") in USAGE_VERSIONS
            and (session_id is None or row.get("session_id") == session_id)]


def format_usage(row: dict) -> str:
    if row.get("kind") == "command":
        return format_command(row)

    def sec(ns):
        return f"{ns / 1e9:.3f}s"

    status = row.get("status", "completed")
    parts = [f"{row['recorded_at']}  {row['session_id']}  {row['source']}"
             + (f"  {row.get('pipeline')}" if row.get("pipeline") else "")
             + (f"  {status}: {row.get('error')}" if status != "completed" else ""),
             f"  setup {sec(row['setup_ns'])}  pass {sec(row['pass_ns'])}  "
             f"publish {sec(row['publish_ns'])}",
             f"  source {row['source_calls']['count']} frames, "
             f"{sec(row['source_calls']['total_ns'])}  "
             f"other {sec(row['pass_other_ns'])}"]
    if row.get("cpu_ns") is not None:
        own = (row.get("dispatcher") or {}).get("thread_cpu_ns")
        parts.append(f"  cpu {sec(row['cpu_ns'])}"
                     + (f"  dispatcher thread {sec(own)}" if own is not None else ""))
    for name, reader in sorted(row["readers"].items(),
                               key=lambda item: item[1]["feed"]["total_ns"],
                               reverse=True):
        feed = reader["feed"]
        slow = sum(feed["buckets"][6:])
        own = reader.get("thread_cpu_ns")
        parts.append(f"  {name:<16} {feed['count']:>6} calls  "
                     f"feed {sec(feed['total_ns'])}  finish {sec(reader['finish_ns'])}  "
                     f">10ms {slow}  max {sec(feed['max_ns'])}"
                     + (f"  thread cpu {sec(own)}" if own is not None else ""))
        parts += format_steps(reader.get("steps") or {}, feed["total_ns"])
    return "\n".join(parts)


def stream_reads(steps: dict) -> dict[str, dict]:
    """Per `read:<stream>` step name, over every path: calls, ns and bytes."""
    out: dict[str, dict] = {}
    for path, t in steps.items():
        name = path.rpartition("/")[2]
        if name.startswith("read:"):
            r = out.setdefault(name, {"count": 0, "total_ns": 0, "bytes": 0})
            r["count"] += t["count"]
            r["total_ns"] += t["total_ns"]
            r["bytes"] += t.get("bytes", 0)
    return out


def format_command(row: dict) -> str:
    wall, steps = row.get("wall_ns"), row.get("steps") or {}
    args = " ".join(f"{k}={v}" for k, v in (row.get("arguments") or {}).items()
                    if v not in (None, False, [], "") and k not in ("session", "cmd"))
    status = row.get("status", "completed")
    lines = [f"{row['recorded_at']}  {row.get('session_id')}  command {row['command']}"
             + (f"  {args}" if args else "")
             + (f"  {status}: {row.get('error')}" if status != "completed" else ""),
             f"  wall {wall / 1e9:.3f}s  cpu {row['cpu_ns'] / 1e9:.3f}s"
             f"  priority {(row.get('contention') or {}).get('priority')}"]
    lines += format_steps(steps, wall or 0, of="wall")
    reads = stream_reads(steps)
    if reads:
        lines.append("  reads")
        for name, r in sorted(reads.items(), key=lambda kv: -kv[1]["total_ns"]):
            lines.append(f"    {name:<34} {r['total_ns'] / 1e9:8.3f}s {r['count']:>5} calls"
                         + (f"  {r['bytes'] / 1e6:8.1f} MB" if r["bytes"] else ""))
    return "\n".join(lines)


def format_steps(steps: dict, feed_ns: int, indent: str = "    ",
                 of: str = "feed") -> list[str]:
    """One line per step under its reader: seconds, calls, ms per call,
    share of the feed and the slowest call. A step's children follow it,
    indented, then `(rest)`, its time outside them; `other` comes last."""
    if not steps:
        return []
    children: dict[str, list[str]] = {}
    for path in steps:
        children.setdefault(path.rpartition("/")[0], []).append(path)

    def line(label, depth, ns, calls, max_ns=None):
        share = f"{100.0 * ns / feed_ns:5.1f}%" if feed_ns else "    -"
        per = f"{ns / calls / 1e6:8.3f} ms/call" if calls else " " * 16
        return (f"{indent}{'  ' * depth}{label:<{max(1, 20 - 2 * depth)}} "
                f"{ns / 1e9:9.3f}s {calls:>8} calls {per}  {share} of {of}"
                + (f"  max {max_ns / 1e6:.1f} ms" if max_ns is not None else ""))

    out: list[str] = []

    def walk(parent, depth):
        for path in sorted(children.get(parent, ()),
                           key=lambda p: (p == OTHER_STEP, -steps[p]["total_ns"])):
            t = steps[path]
            out.append(line(path.rpartition("/")[2], depth, t["total_ns"], t["count"],
                            t["max_ns"]))
            if path in children:
                walk(path, depth + 1)
                rest = t["total_ns"] - sum(steps[c]["total_ns"] for c in children[path])
                out.append(line("(rest)", depth + 1, max(0, rest), 0))
    walk("", 0)
    return out
