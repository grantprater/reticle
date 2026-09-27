"""Operational scan timings, separate from observation and accuracy evidence.

One JSON line records a scan. Source time is shared by all readers; reader
feed times are exclusive. Buckets retain call frequencies without a
per-frame file or unbounded in-memory samples.

`scan-usage-2` adds how the pass ran: `pipeline` (`serial` or `staged`),
`workers`, `shards`, `cv_threads`, `code_revision` (HEAD's short sha and
whether the tree differs from it) and `error`; `status` says `failed` when a
staged pass ended on a reader's exception. `load` reads both versions.
"""

from __future__ import annotations

from bisect import bisect_right
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import threading
from time import perf_counter_ns
from uuid import uuid4


USAGE_VERSION = "scan-usage-2"
#: Versions `load` reads; each later one only adds keys.
USAGE_VERSIONS = ("scan-usage-1", USAGE_VERSION)
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
                                 "feed": CallTimes(), "finish_ns": 0}
                        for r in readers}
        self.frames = CallTimes()
        self.setup_ns = 0
        self.pass_ns = 0
        self.publish_ns = 0
        self.pipeline = "serial"
        self.workers = None
        self.shards: dict[str, int] = {}
        self.cv_threads: dict | None = None
        self.code_revision = code_revision()
        self.status = "completed"
        self.error: str | None = None
        # Shards of one reader share its name, and so its `CallTimes`.
        self._lock = threading.Lock()

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
            "bucket_upper_ns": list(BUCKET_LIMITS_NS),
            "setup_ns": self.setup_ns,
            "pass_ns": self.pass_ns,
            "publish_ns": self.publish_ns,
            "source_calls": self.frames.record(),
            "readers": {name: {"hz": r["hz"], "spans": r["spans"],
                                "feed": r["feed"].record(),
                                "finish_ns": r["finish_ns"]}
                        for name, r in self.readers.items()},
            "pass_other_ns": max(0, self.pass_ns - source_ns - feed_ns - finish_ns),
        }

    def write(self, store_root: Path) -> Path:
        path = Path(store_root) / "notes" / "usage.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as out:
            out.write(json.dumps(self.record(), separators=(",", ":")) + "\n")
        return path

    def write_metric(self, store_root: Path) -> dict:
        """One `pass` row in `notes/metrics.jsonl` naming this record's run_id.

        Timings move from run to run with the machine's load, so the run_id
        is context, not a dependency: two runs of one configuration compare
        as CHANGED, never as BROKEN.
        """
        from . import metrics
        return metrics.record(
            "scan_usage", part="+".join(sorted(self.readers)),
            session=self.manifest["session_id"],
            values={"pass_s": round(self.pass_ns / 1e9, 3),
                    "source_s": round(self.frames.total_ns / 1e9, 3),
                    "frames": self.frames.count},
            deps={"usage_version": USAGE_VERSION, "source": self.source,
                  "pipeline": self.pipeline, "workers": self.workers,
                  "shards": dict(self.shards), "cv_threads": self.cv_threads,
                  "code_revision": self.code_revision},
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

    parts = [f"{row['recorded_at']}  {row['session_id']}  {row['source']}",
             f"  setup {sec(row['setup_ns'])}  pass {sec(row['pass_ns'])}  "
             f"publish {sec(row['publish_ns'])}",
             f"  source {row['source_calls']['count']} frames, "
             f"{sec(row['source_calls']['total_ns'])}  "
             f"other {sec(row['pass_other_ns'])}"]
    for name, reader in sorted(row["readers"].items(),
                               key=lambda item: item[1]["feed"]["total_ns"],
                               reverse=True):
        feed = reader["feed"]
        slow = sum(feed["buckets"][6:])
        parts.append(f"  {name:<16} {feed['count']:>6} calls  "
                     f"feed {sec(feed['total_ns'])}  finish {sec(reader['finish_ns'])}  "
                     f">10ms {slow}  max {sec(feed['max_ns'])}")
    return "\n".join(parts)
