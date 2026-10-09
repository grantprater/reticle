"""One reader's crop-cache pass split by time over separate processes.

Threads do not speed up `AllyIconReader`: two thread shards ran 1.05x one on
a06f04a0059f (docs/PUBSUB_DESIGN.md, the ladder), since its Python holds the
GIL. Separate processes do: three read 3.17x the frames of one, CPU per frame
flat (`prototypes/ally_cost_parallel.py`, ally-cost-diag-0.1.0). So a pass
fed from the minimap crop cache may run `ally_icon` in K processes
(`scan --ally-processes K`; `ingest-passes` defaults K to 3).

**The split.** The parent asks the pass's own rule which cached times the
reader reads (`passes.cache_feed`, the rule `run_cached` uses), then cuts
that list into K contiguous runs, only where two consecutive times lie more
than `teardrop.PRIOR_GAP_MS` apart (`split_at_gaps`). The reader is not
pure: `teardrop.IconPoseReader` continues each icon's fit on the previous
image, and a prior seen longer ago than `PRIOR_GAP_MS` is no prior. After
such a gap a serial reader's state reaches its next image only as "some image
was read before" (surprise `gap`, not `no_prior`); every other field it
carries is overwritten or unused before it is read. So each child after the
first starts `AllyIconReader.after_gap` at the time before its run, and the
parent checks that seed against what the earlier runs read (`check_seeds`):
where a channel read nothing before the cut, the serial reader would have
said `no_prior`, and the parent refuses the merge rather than store a
different row. Round caches leave the buy phase between runs, so the cuts
fall between rounds.

**A frame gate.** A reader the hook gates (`passes.frame_gated`) is split on
its ungated times, and each child asks the gate before each crop fetch
(`passes.gated_times`), feeding each read the gate opened back to it. The
parent pickles the bound gate for the children, each child starts from that
fresh gate, and the parent appends the children's `gate_log`s in run order.
A gate whose belief restarts at a gap in the offered times longer than
`teardrop.PRIOR_GAP_MS` (`ally_gate.RESET_GAP_MS`) answers each run as the
serial pass would, since every cut lies at such a gap.

**The merge.** Each child rebuilds the reader as `scan` does
(`minimap.ally_icon_reader`), takes the parent's spans, clip and source, feeds
its times through `passes._feed` and writes the reader's `shardable` lists.
The parent concatenates them in run order, which is producer order, so the
lists equal a serial pass's element for element and the candidate revision
(a SHA-256 of the lists in order) is the serial one; `scan` then publishes
as it would have. Nothing here decides what a reader reads or what a row
means.

**Compute.** Each child runs at Idle priority (`IDLE_PRIORITY_CLASS`) with
OpenMP, MKL, OpenBLAS and OpenCV at one thread, the machine's rule while the
player's own jobs share the CPU.
"""
from __future__ import annotations

import json
import os
import pickle
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

#: Environment every child runs under: one BLAS/OpenMP thread.
SINGLE_THREAD_ENV = {"OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1",
                     "OPENBLAS_NUM_THREADS": "1"}
#: The readers a child can rebuild, by name.
READERS = ("ally_icon",)


class SeedMismatch(RuntimeError):
    """A run's seed disagrees with what the runs before it read."""


def split_at_gaps(times, k: int, gap_ms: float) -> list[list[float]]:
    """`times` (sorted) cut into at most `k` contiguous runs of near-equal
    length, only between two times more than `gap_ms` apart. Fewer runs come
    back where fewer cuts exist; an empty list gives none."""
    t = np.asarray(sorted(float(x) for x in times), float)
    if not len(t):
        return []
    cuts = np.flatnonzero(np.diff(t) > gap_ms) + 1      # a run may start at these
    chosen: list[int] = []
    for j in range(1, k):
        target = len(t) * j / k
        free = [c for c in cuts if c not in chosen and (not chosen or c > chosen[-1])]
        if not free:
            break
        chosen.append(int(min(free, key=lambda c: abs(c - target))))
    bounds = [0, *chosen, len(t)]
    return [t[a:b].tolist() for a, b in zip(bounds, bounds[1:]) if b > a]


def wanted_times(reader, cache) -> list[float]:
    """The cached times a serial pass feeds `reader` (`passes.cache_feed`)."""
    from types import SimpleNamespace

    from .passes import cache_feed
    every, want = cache_feed([reader], cache)
    return [float(t) for t in every if want(SimpleNamespace(t_ms=float(t)))]


def _pose_reads(candidates: list[dict]) -> set[str]:
    """The channels whose fits a prior-driven pose read touched."""
    return {c["channel"] for c in candidates
            if "search" in (c.get("pose") or {})}


def check_seeds(runs: list[dict]) -> None:
    """Raise `SeedMismatch` where a seeded run's first read on a channel took
    the seed as an earlier image (surprise `gap`) though no earlier run read
    that channel: a serial reader would have said `no_prior` there."""
    seen: set[str] = set()
    for i, run in enumerate(runs):
        if i:
            first: dict[str, dict] = {}
            for c in run["candidates"]:
                if "search" in (c.get("pose") or {}):
                    first.setdefault(c["channel"], c)
            for ch, c in first.items():
                if ch not in seen and c["pose"].get("surprise") == "gap":
                    raise SeedMismatch(f"run {i}: channel {ch} read nothing before "
                                       f"{c['t_ms']} ms, so its first read is no_prior "
                                       f"serially, not gap")
        seen |= _pose_reads(run["candidates"])


class ProcessRun:
    """`reader`'s cached times fed in up to `k` child processes, started on
    construction; `merge` waits for them and extends the reader's lists.

    `reader` is the parent's, its spans, `spans_clip` and `frames_from` set
    as the pass set them. The parent may run its other readers meanwhile."""

    def __init__(self, store_root: Path, sid: str, reader, cache, k: int, log=print):
        from .teardrop import PRIOR_GAP_MS
        if reader.name not in READERS:
            raise ValueError(f"{reader.name} has no process builder ({READERS})")
        self.reader, self.k = reader, int(k)
        self.runs = split_at_gaps(wanted_times(reader, cache), self.k, PRIOR_GAP_MS)
        self.tmp = Path(tempfile.mkdtemp(prefix=f"reticle-{sid}-{reader.name}-"))
        env = {**os.environ, **SINGLE_THREAD_ENV}
        flags = getattr(subprocess, "IDLE_PRIORITY_CLASS", 0)
        self.procs = []
        before = None
        self.t0 = time.perf_counter()
        for i, chunk in enumerate(self.runs):
            spec = {"store": str(store_root), "session": sid, "reader": reader.name,
                    "hz": float(reader.hz), "spans": reader.spans,
                    "spans_clip": getattr(reader, "spans_clip", None),
                    "frames_from": reader.frames_from, "times": chunk,
                    "seed_t_ms": before, "out": str(self.tmp / f"run{i}.pkl"),
                    "gate": self._gate_spec(reader)}
            before = chunk[-1]
            sp = self.tmp / f"run{i}.json"
            sp.write_text(json.dumps(spec), encoding="utf-8")
            log(f"processes  {reader.name} run {i}: {len(chunk)} frames, "
                f"{chunk[0] / 1000:.1f}-{chunk[-1] / 1000:.1f} s")
            self.procs.append((subprocess.Popen(
                [sys.executable, "-m", "reticle.process_shards", str(sp)],
                env=env, creationflags=flags), spec))

    def _gate_spec(self, reader) -> str | None:
        """The bound frame gate pickled once for every child, or None."""
        from .passes import frame_gated
        if not frame_gated(reader):
            return None
        path = self.tmp / "gate.pkl"
        if not path.is_file():
            with open(path, "wb") as f:
                pickle.dump(reader.frame_gate, f, protocol=pickle.HIGHEST_PROTOCOL)
        return str(path)

    @property
    def frames(self) -> int:
        """The frames the runs read: every offered frame, or after a gated
        reader's merge the frames its gate or audit opened."""
        read = getattr(self, "_gated_reads", None)
        return sum(len(r) for r in self.runs) if read is None else read

    def merge(self) -> dict:
        """Wait, check the seeds, extend the reader's `shardable` lists in run
        order; what each child cost. Raises `SeedMismatch` or RuntimeError
        with nothing merged."""
        import shutil
        codes = [p.wait() for p, _ in self.procs]
        wall = time.perf_counter() - self.t0
        if any(codes):
            raise RuntimeError(f"{self.reader.name} process runs exited {codes}; nothing "
                               f"merged (specs under {self.tmp})")
        got = []
        for _, spec in self.procs:
            with open(spec["out"], "rb") as f:
                got.append(pickle.load(f))
        check_seeds(got)
        for name in self.reader.shardable:
            merged = getattr(self.reader, name)
            for g in got:
                merged.extend(g["lists"][name])
        if any(g.get("gate_log") is not None for g in got):
            from .passes import GateLog
            from .ratchets import declared_gate
            log = self.reader.gate_log = GateLog(
                declared_gate(self.reader), getattr(self.reader.frame_gate, "sources", None))
            for g in got:
                if g.get("gate_log") is not None:
                    log.extend(g["gate_log"])
            self._gated_reads = len(set(log.read_t) | set(log.audit_t))
        shutil.rmtree(self.tmp, ignore_errors=True)
        return {"processes": len(self.runs), "asked": self.k,
                "frames": [len(r) for r in self.runs],
                "fed": [g.get("fed", len(r)) for g, r in zip(got, self.runs)],
                "wall_s": round(wall, 3),
                "child_wall_s": [round(g["wall_ns"] / 1e9, 3) for g in got],
                "child_cpu_s": [round(g["cpu_ns"] / 1e9, 3) for g in got],
                "child_fetch_cpu_s": [round(g.get("fetch_cpu_ns", 0) / 1e9, 3) for g in got],
                "cpu_ns": sum(g["cpu_ns"] for g in got)}


def _timed(frames, total: list):
    """`frames`, adding the process CPU each fetch takes to `total[0]`: the
    crop decode and, on a gated pass, the gate's questions before it."""
    it = iter(frames)
    while True:
        c0 = time.process_time_ns()
        smp = next(it, None)
        total[0] += time.process_time_ns() - c0
        if smp is None:
            return
        yield smp


def _child(spec_path: str) -> int:
    """One run: rebuild the reader as `scan` does, feed its times, write its lists."""
    import cv2

    from .minimap import ally_icon_reader
    from .passes import SessionContext, _cache_rois, _feed, gate_after, gated_times
    from .profiles import get_profile
    from .roi_cache import cache_for, declare_set
    from .store import Store

    cv2.setNumThreads(1)
    spec = json.loads(Path(spec_path).read_text(encoding="utf-8"))
    store = Store(spec["store"])
    manifest = store.read_manifest(spec["session"])
    profile = get_profile(manifest["source_profile"])
    spans = None if spec["spans"] is None else [tuple(s) for s in spec["spans"]]
    ctx = SessionContext(store=store, manifest=manifest, profile=profile, spans=spans or [])
    reader = ally_icon_reader(ctx, hz=spec["hz"], spans=spans)
    declare_set(reader, "minimap", profile, ctx.wh)
    if spec["spans_clip"] is not None:
        reader.spans_clip = spec["spans_clip"]
    cache, why = cache_for(store.root, manifest, profile, [reader], gated_ok=True)
    if cache is None:
        raise SystemExit(f"process run: no cache feeds {reader.name}: {why}")
    reader.frames_from = spec["frames_from"]
    if spec.get("gate"):
        with open(spec["gate"], "rb") as f:
            reader.bind_gate(pickle.load(f))
    if spec["seed_t_ms"] is not None:
        reader.after_gap(float(spec["seed_t_ms"]))
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    fed = 0
    fetch = [0]
    if spec.get("gate"):
        # The hook's rule, as `passes.run_cached` applies it: a gated
        # reader's gate is asked before each crop fetch.
        lazy, pending = gated_times([reader], spec["times"], lambda t: [reader])
        for smp in _timed(cache.samples(lazy, rois=_cache_rois(reader)), fetch):
            for r, d in pending.pop(float(smp.t_ms), ()):
                _feed(r, smp, None)
                fed += 1
                if d is not None:
                    gate_after(r, smp.t_ms, d)
    else:
        for smp in _timed(cache.samples(spec["times"], rois=_cache_rois(reader)), fetch):
            _feed(reader, smp, None)
            fed += 1
    out = {"lists": {n: getattr(reader, n) for n in reader.shardable},
           "candidates": reader.candidates, "gate_log": getattr(reader, "gate_log", None),
           "fed": fed, "fetch_cpu_ns": fetch[0],
           "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - cpu}
    with open(spec["out"], "wb") as f:
        pickle.dump(out, f, protocol=pickle.HIGHEST_PROTOCOL)
    return 0


if __name__ == "__main__":
    raise SystemExit(_child(sys.argv[1]))
