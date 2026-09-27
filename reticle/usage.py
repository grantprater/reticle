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
capture. `load` reads both versions.

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

**Citing a scan.** `write_metric` appends a `scan_usage` pass row whose part
names the readers and then how the pass ran (`series_part`), so each
configuration is its own series: QUOTED compares a citation with the latest
pass row of its series and ignores `deps`, and a serial rerun must not
become the row a staged figure is checked against. A document cites the
pass time of a staged HUD pass from the crop cache at one worker as

    [metric:scan_usage/hud+killfeed_portrait/cache/staged/w1/cv1@c40d950031bb#pass_s=<seconds>]

with `<seconds>` the row's `pass_s` at the precision the prose states. The
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
from contextlib import contextmanager
import json
from pathlib import Path
import re
import subprocess
import threading
from time import perf_counter_ns, process_time_ns, thread_time_ns
from uuid import uuid4


USAGE_VERSION = "scan-usage-2"
#: Versions `load` reads; each later one only adds keys.
USAGE_VERSIONS = ("scan-usage-1", USAGE_VERSION)
#: Why a reader's own thread CPU is null when it fed on the dispatcher thread.
INLINE_REASON = "fed on the dispatcher thread; see dispatcher.thread_cpu_ns"
BUCKET_LIMITS_NS = (100_000, 500_000, 1_000_000, 2_000_000,
                    5_000_000, 10_000_000, 50_000_000, 100_000_000)


class CallTimes:
    def __init__(self):
        self.count = 0
        self.total_ns = 0
        self.max_ns = 0
        self.buckets = [0] * (len(BUCKET_LIMITS_NS) + 1)

    def add(self, elapsed_ns: int) -> None:
        self.count += 1
        self.total_ns += elapsed_ns
        self.max_ns = max(self.max_ns, elapsed_ns)
        self.buckets[bisect_right(BUCKET_LIMITS_NS, elapsed_ns)] += 1

    def record(self) -> dict:
        return {"count": self.count, "total_ns": self.total_ns,
                "max_ns": self.max_ns, "buckets": self.buckets}


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
        self.cv_threads: dict | None = None
        self.wait_ns: int | None = None
        self.until_s: float | None = None
        self.cpu_ns: int | None = None
        self.dispatcher_cpu_ns: int | None = None
        self.code_revision = code_revision()
        self.status = "completed"
        self.error: str | None = None
        # Shards of one reader share its name, and so its `CallTimes`.
        self._lock = threading.Lock()

    @contextmanager
    def timed_pass(self):
        """Time the pass on the calling thread, the dispatcher.

        Sets `pass_ns` (wall), `cpu_ns` (the process's CPU) and the
        dispatcher's `thread_cpu_ns` over the same span, on failure too.
        """
        wall, cpu, own = perf_counter_ns(), process_time_ns(), thread_time_ns()
        try:
            yield self
        finally:
            self.pass_ns = perf_counter_ns() - wall
            self.cpu_ns = process_time_ns() - cpu
            self.dispatcher_cpu_ns = thread_time_ns() - own

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
        start = perf_counter_ns()
        try:
            reader.feed(sample)
        finally:
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
                                "shards": [dict(u) for u in r["shards"]]}
                        for name, r in self.readers.items()},
            "pass_other_ns": max(0, self.pass_ns - source_ns - feed_ns - finish_ns),
        }

    def write(self, store_root: Path) -> Path:
        path = Path(store_root) / "notes" / "usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(self.record(), separators=(",", ":")) + "\n")
        return path

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
        for name, r in sorted(self.readers.items()):
            field = re.sub(r"\W", "_", name)
            values[f"feed_s_{field}"] = s(r["feed"].total_ns)
            if r["thread_cpu_ns"] is not None:
                values[f"thread_cpu_s_{field}"] = s(r["thread_cpu_ns"])
        return values

    def write_metric(self, store_root: Path) -> dict:
        """One `pass` row in `notes/metrics.jsonl` naming this record's run_id.

        Timings move from run to run with the machine's load, so the run_id
        is context, not a dependency: two runs of one configuration compare
        as CHANGED, never as BROKEN.
        """
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


def load(store_root: Path, session_id: str | None = None) -> list[dict]:
    path = Path(store_root) / "notes" / "usage.jsonl"
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as source:
        rows = [json.loads(line) for line in source if line.strip()]
    return [row for row in rows if row.get("version") in USAGE_VERSIONS
            and (session_id is None or row.get("session_id") == session_id)]


def format_usage(row: dict) -> str:
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
    return "\n".join(parts)
