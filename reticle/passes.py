"""Readers that ride one decode, and the session context they share.

Decode is the cost of this pipeline. Measured 2026-09-05 on c40d950031bb: 300
sampled frames take 13.17 s to decode and 0.94 s to run the scoreline, bottom
HUD and killfeed extractors over -- 93% and 7%. For the minimap at 15 Hz the
split is 66/34, because ring fitting is real work, but decode still dominates.
So the question that decides how long anything here takes is not how fast a
reader is, it is **how many times the file is opened**.

Before `decode.sample_multi` there was no way to express "run alongside a pass
that is already happening", so every stage and every prototype opened the file
for itself: `hud`, `minimap`, `xmark_eval`, `chokepoint_eval`, `ping_scan`,
`reader_census`. Fusing just the two shipped stages saved 45%. This module is
the other half -- a reader is an object with a rate, a span filter and a
`feed`, so a probe can join a scan instead of costing another full decode.

**Deliberately thin, and it stays that way.** It owns no analysis, decides
nothing about what a reader does with a frame, and every reader here can still
be driven by an ordinary loop -- which is what keeps `hud` and `minimap` honest
as standalone commands. What it centralises is the SESSION CONTEXT: the
manifest, profile and ROIs; the per-session killfeed overlay mask; and access to
immutable baked minimap geometry. Session frames never define the map.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import NamedTuple, Protocol

import numpy as np


class Reader(Protocol):
    """What `run` needs of a reader. `hz` and `spans` decide which frames.

    **`finish` is part of the contract, not an extra.** It was left out of the
    first version and that is a way for a reader to be silently inert: a
    two-phase reader like `ping.PingReader` has no results at all until it is
    called, while `_HudPass` and `_MinimapPass` accumulate into `.rows` and need
    nothing. A fourth reader of the first kind, added to a `readers` list, would
    have been fed every frame and produced nothing, with no error anywhere.
    `run` now calls it on every reader that has one, so the failure cannot
    happen -- and calling it twice is not an error, because the two-phase
    readers here are idempotent by construction (`finish` recomputes from
    accumulated state rather than consuming it).
    """

    name: str
    hz: float
    spans: list[tuple[float, float]] | None

    def feed(self, sample) -> None: ...


@dataclass
class SessionContext:
    """Everything a reader needs about a session, derived at most once.

    The two cached fields are the point. `kf_mask` costs 40 seeks and
    `static_map` costs 120; between them they were being paid separately by the
    shipped stages and by every prototype that touched the same session.
    """

    store: object
    manifest: dict
    profile: object
    spans: list[tuple[float, float]] = field(default_factory=list)

    @property
    def src(self) -> dict:
        return self.manifest["source"]

    @property
    def session_id(self) -> str:
        return self.manifest["session_id"]

    @property
    def wh(self) -> tuple[int, int]:
        return int(self.src["width"]), int(self.src["height"])

    @property
    def fps(self) -> float:
        return float(self.src["fps"])

    @property
    def media(self) -> Path:
        p = Path(self.src["path"])
        if not p.is_file():
            raise SystemExit(
                f"source media has moved: {p}\n"
                "the manifest records where it was at ingest time"
            )
        return p

    def kf_mask(self):
        """The killfeed overlay mask, from cache or measured once."""
        from .killfeed import killfeed_roi, overlay_mask

        import cv2

        got = self.store.read_kf_mask(self.session_id)
        if got is not None:
            return got
        roi = killfeed_roi(self.profile)
        if roi is None:
            return None
        w, h = self.wh
        cap = cv2.VideoCapture(str(self.media))
        cal = []
        try:
            dur = int(self.src["duration_ms"] or 0)
            step = max(1, dur // 40)
            for ms in range(0, dur, step):
                cap.set(cv2.CAP_PROP_POS_MSEC, ms)
                ok, fr = cap.read()
                if ok:
                    cal.append(fr)
        finally:
            cap.release()
        if not cal:
            return None
        m = overlay_mask(cal, roi, w, h)
        self.store.write_kf_mask(self.session_id, m)
        return m

    def map_reference(self):
        """The baked base map for this session's (map, profile) geometry key.

        Session frames must never enter this value.  Session-specific minimap
        data is limited to the ROI dimensions/placement supplied by `profile`.
        """
        from . import geometry

        return geometry.reference_static(self.session_id, self.store.root)

    def floor(self) -> np.ndarray:
        from . import geometry
        from .minimap import floor_mask

        med = self.map_reference()
        return floor_mask(med, sd=geometry.stability(self.session_id,
                                                     self.store.root,
                                                     med.shape[:2]))

    def sgray(self) -> np.ndarray:
        import cv2

        return cv2.cvtColor(self.map_reference(), cv2.COLOR_BGR2GRAY).astype(np.float64)


# ---------------------------------------------------------------------------
# The per-frame gate hook (BACKLOG item 1)
# ---------------------------------------------------------------------------

class GateDecision(NamedTuple):
    """One gate answer at one grid instant.

    `read`: the gate opened; `reason` says why it opened or refused;
    `rests_on`: the keys of the priors this answer read (the gate's
    `sources`); `audit`: the instant lies in the declared audit cadence
    (`ratchets.Audit`), so it is read whatever `read` says and stored apart.
    """

    read: bool
    reason: str
    audit: bool = False
    rests_on: tuple = ()


class GateLog:
    """What a frame gate decided over a pass, kept on the reader as
    `gate_log` for its owner to publish.

    Every offered instant gets exactly one answer in the gated stream: a
    read the gate opened (`reads[t]`: its reason and the priors it rests
    on), or a NON-READ with its refusal reason -- never a null observation,
    never "absent" -- even where the audit read that instant. Refusals are
    kept as runs of consecutive offered instants sharing a reason and its
    priors (`runs`: `[t_first, t_last, reason, n, rests_on]`). The audit
    instants (`audit_t`, opened or not) are kept whole, so the owner stores
    the audit rows apart. `sources` maps each `rests_on` key to the prior it
    names, with its stamp.
    """

    def __init__(self, gate, sources: dict | None = None):
        self.version = gate.version
        self.rests_on = list(gate.rests_on)
        self.sources = dict(sources or {})
        self.audit = gate.audit.stamp() if gate.audit is not None else None
        self.opened: Counter = Counter()
        self.refused: Counter = Counter()
        self.reads: dict[float, tuple] = {}
        self.audit_t: list[float] = []
        self.runs: list[list] = []
        self._open_run = False

    @property
    def read_t(self) -> list[float]:
        return list(self.reads)

    def record(self, t_ms: float, d: GateDecision) -> None:
        t = float(t_ms)
        if d.audit:
            self.audit_t.append(t)
        if d.read:
            self.opened[d.reason] += 1
            self.reads[t] = (d.reason, tuple(d.rests_on))
            self._open_run = False
            return
        self.refused[d.reason] += 1
        key = tuple(d.rests_on)
        if self._open_run and self.runs[-1][2] == d.reason and self.runs[-1][4] == key:
            self.runs[-1][1] = t
            self.runs[-1][3] += 1
        else:
            self.runs.append([t, t, d.reason, 1, key])
        self._open_run = True

    def extend(self, other: "GateLog") -> None:
        """Append a later run's log (`process_shards` merges in run order)."""
        self.opened.update(other.opened)
        self.refused.update(other.refused)
        self.reads.update(other.reads)
        self.audit_t += other.audit_t
        self.runs += [list(r) for r in other.runs]
        self.sources.update(other.sources)
        self._open_run = False

    def summary(self) -> dict:
        """The gate's block for its stream's coverage row."""
        audit_only = len(set(self.audit_t) - set(self.reads))
        refused = int(sum(self.refused.values()))
        return {"version": self.version, "rests_on": self.rests_on, "sources": self.sources,
                "audit": self.audit, "offered": len(self.reads) + refused,
                "read": len(self.reads), "audit_frames": len(self.audit_t),
                "audit_only": audit_only, "refused": refused,
                "opened_reasons": dict(sorted(self.opened.items())),
                "refused_reasons": dict(sorted(self.refused.items()))}

    def unread_rows(self) -> list[dict]:
        """One row per refused run: the instants the gate did not read, why,
        and the priors that answer rests on (an audit may have read some)."""
        return [{"kind": "unread", "t_ms": a, "t_last_ms": b, "reason": why, "frames": int(n),
                 "rests_on": list(key), "gate_version": self.version}
                for a, b, why, n, key in self.runs]


def frame_gated(reader) -> bool:
    """Does the hook gate `reader`? A `"frame"` gate declared
    (`ratchets.declared_gate`), a `wants` method and a bound runtime gate
    (`frame_gate`); a reader whose gate is not bound reads its grid."""
    from .ratchets import declared_gate
    g = declared_gate(reader)
    return (g is not None and g.kind == "frame" and callable(getattr(reader, "wants", None))
            and getattr(reader, "frame_gate", None) is not None)


def gate_decide(reader, t_ms: float) -> GateDecision:
    """Ask `reader`'s gate about one instant -- `wants(t_ms)` returns a
    `GateDecision`, a `(read, reason[, rests_on])` tuple or a bool -- and
    record the answer in its `gate_log` (made on first use from the
    declared gate and the runtime gate's `sources`). The audit cadence is
    the declaration's, applied here, so no gate can skip it."""
    from .ratchets import declared_gate
    g = declared_gate(reader)
    log = getattr(reader, "gate_log", None)
    if log is None:
        log = reader.gate_log = GateLog(g, getattr(reader.frame_gate, "sources", None))
    d = reader.wants(float(t_ms))
    if isinstance(d, tuple) and not isinstance(d, GateDecision):
        d = GateDecision(bool(d[0]), str(d[1]), False, tuple(d[2]) if len(d) > 2 else ())
    elif not isinstance(d, GateDecision):
        d = GateDecision(bool(d), "open" if d else "closed")
    audit = g.audit is not None and g.audit.covers(t_ms, _span_start(reader, t_ms))
    d = d._replace(audit=bool(audit))
    log.record(t_ms, d)
    return d


def _span_index(reader) -> tuple:
    """`(starts, ends)` of the reader's spans (sorted, disjoint), built once
    per spans object; None spans are one span from 0 ms."""
    spans = getattr(reader, "spans", None)
    got = getattr(reader, "_gate_span_index", None)
    if got is None or got[0] is not spans:
        arr = (np.array([[0.0, np.inf]]) if spans is None
               else np.asarray(spans, float).reshape(-1, 2))
        got = reader._gate_span_index = (spans, arr[:, 0].copy(), arr[:, 1].copy())
    return got[1], got[2]


def _span_start(reader, t_ms: float) -> float | None:
    """The start of the reader's span holding `t_ms`, or None."""
    # The index is built once per spans object (`_span_index`); one lookup.
    starts, ends = _span_index(reader)
    i = np.searchsorted(starts, float(t_ms), side="right") - 1
    return float(starts[i]) if i >= 0 and float(t_ms) <= ends[i] else None


def gate_after(reader, t_ms: float, d: GateDecision) -> None:
    """After a gated reader read `t_ms`: a read the gate opened feeds the
    gate's belief back (`observed`); an audit-only read does not, so the
    gate's belief never rests on its own audit."""
    if d.read:
        fn = getattr(reader, "observed", None)
        if callable(fn):
            fn(float(t_ms))


def gated_times(readers: list, times, want):
    """`times` (each a candidate instant) filtered lazily by the readers'
    gates: yields each instant somebody reads, once `pending[t]` holds who
    and with which decision (None for an ungated reader). `want(t)` names
    the readers whose grid takes `t`. A generator, so each gate is asked
    only after the caller fed every earlier sample."""
    pending: dict[float, list] = {}
    gated = {id(r) for r in readers if frame_gated(r)}

    def gen():
        for t in times:
            t = float(t)
            keep = []
            for r in want(t):
                if id(r) in gated:
                    d = gate_decide(r, t)
                    if d.read or d.audit:
                        keep.append((r, d))
                else:
                    keep.append((r, None))
            if keep:
                pending[t] = keep
                yield t
    return gen(), pending


def run(ctx: SessionContext, readers: list, progress=None, usage=None) -> int:
    """Drive every reader over ONE decode. Returns frames retrieved.

    A reader is fed only the frames it asked for -- `decode.sample_multi`
    decides that from each one's `hz` and `spans` -- so adding a slow reader
    over a narrow window costs that window, not another pass over the file.

    A frame-gated reader (`frame_gated`) is asked `wants(t_ms)` at each
    instant of its grid before the retrieve (`gate_decide`); a refusal is
    recorded in its `gate_log` and the frame is neither retrieved for it
    nor fed. After a read the gate opened, the reader's `observed` feeds its
    gate's belief (`gate_after`).
    """
    from .decode import sample_multi

    names = [r.name for r in readers]
    if len(names) != len(set(names)):
        duplicates = sorted({name for name in names if names.count(name) > 1})
        raise ValueError(f"reader names must be unique: {', '.join(duplicates)}")
    req = {r.name: (r.hz, r.spans) for r in readers}
    n = 0
    backend = {}
    if usage is not None:
        usage.decode_backend = backend      # filled when the capture opens
    decided: dict[str, GateDecision] = {}

    def gate_of(r):
        def ask(t_ms):
            d = decided[r.name] = gate_decide(r, t_ms)
            return d.read or d.audit
        return ask
    gates = {r.name: gate_of(r) for r in readers if frame_gated(r)}
    frames = sample_multi(str(ctx.media), ctx.fps, req, info=backend,
                          **({"gates": gates} if gates else {}))
    for who, smp in (usage.timed_frames(frames) if usage is not None else frames):
        n += 1
        # In the readers' order, as `run_cached` feeds them: a reader may read
        # the row an earlier one wrote for the same sample
        # (`minimap_glyph.LiveIcons`); `who` is a set.
        for r in readers:
            if r.name in who:
                _feed(r, smp, usage)
                if r.name in gates:
                    gate_after(r, smp.t_ms, decided[r.name])
        if progress is not None:
            progress(n, smp)
    for r in readers:
        fin = getattr(r, "finish", None)
        if callable(fin):
            if usage is None:
                fin()
            else:
                usage.finish(r, fin)
    return n


def cache_backend(cache) -> dict:
    """What decodes a crop cache's pass, for the usage record: an FFV1 cache
    reads through OpenCV and PyAV, chosen per read by the gap
    (`roi_cache._Ffv1Rect`); a PNG one through OpenCV's `cv2.imdecode`."""
    codec = cache.record.get("codec")
    return {"backend": "opencv+pyav" if codec == "ffv1" else "opencv", "codec": codec,
            "source": "cache"}


def run_cached(ctx: SessionContext, readers: list, cache, progress=None,
               usage=None) -> int:
    """Drive every reader over the ROI crop cache instead of a decode.

    The caller has checked, through `roi_cache.cache_for`, that each reader's
    reads stay inside a cached set, that it wants the whole capture, and that
    the cache was written at its rate -- so the cache's timestamps are the
    frames `run` would have fed it, and each frame holds those pixels bit for
    bit. A `cache_resample` reader slower than the cache reads its own grid
    of cached times instead (`cache_feed`). A frame-gated reader's gate is
    asked at each of its cached times before the crop is fetched
    (`gated_times`), so a refused time costs no crop decode. Returns frames
    fed.
    """
    rois = sorted({roi for r in readers for roi in _cache_rois(r)})
    for r in readers:
        r.frames_from = cache.record["version"]
    if usage is not None:
        usage.decode_backend = cache_backend(cache)
    n = 0
    times, want = cache_feed(readers, cache)
    if any(frame_gated(r) for r in readers):
        lazy, pending = gated_times(readers, times, lambda t: want(SimpleNamespace(t_ms=t)))
        frames = cache.samples(lazy, rois=rois)
        who = lambda smp: pending.pop(float(smp.t_ms), ())  # noqa: E731
    else:
        frames = cache.samples(times, rois=rois)
        who = lambda smp: [(r, None) for r in want(smp)]  # noqa: E731
    for smp in (usage.timed_frames(frames) if usage is not None else frames):
        n += 1
        for r, d in who(smp):
            _feed(r, smp, usage)
            if d is not None:
                gate_after(r, smp.t_ms, d)
        if progress is not None:
            progress(n, smp)
    for r in readers:
        fin = getattr(r, "finish", None)
        if callable(fin):
            if usage is None:
                fin()
            else:
                usage.finish(r, fin)
    return n


def cache_feed(readers: list, cache):
    """The cached times a pass reads, and who wants each frame.

    A reader at the cache's rate wants every cached frame inside its spans: a
    cache over wider spans than it asked for holds frames it would not have
    been fed. A reader that `roi_cache.resamples` wants only the first cached
    time at or after each point of its own grid, restarted at each of its
    spans (`roi_cache.grid_times`); one that declares `cache_resample =
    "nearest"` wants the cached time nearest each point of the decode's grid,
    phased at the spans it asked for before any clip (`roi_cache.nearest_times`).
    The pass reads only the times somebody wants.
    """
    from .roi_cache import grid_times, nearest_times, resamples
    t = cache.t_ms
    hz = cache.record.get("hz")
    picks: dict[int, set[float] | None] = {}
    for r in readers:
        if hz is None or not resamples(r, hz):
            picks[id(r)] = None
            continue
        spans = getattr(r, "spans", None)
        whole = [(0.0, float(np.max(t)))] if len(t) else []
        if getattr(r, "cache_resample", None) == "nearest":
            # The decode's phase: the spans asked for, before a clip to the
            # cache's rounds; a whole-capture decode starts at 0 ms.
            clip = getattr(r, "spans_clip", None)
            asked = clip["spans_asked"] if clip is not None else spans
            picks[id(r)] = set(nearest_times(t, whole if asked is None else asked,
                                             whole if spans is None else spans,
                                             1.0 / float(r.hz)))
            continue
        if spans is None:
            spans = [(float(np.min(t)), float(np.max(t)))] if len(t) else []
        picks[id(r)] = {x for a, b in spans for x in grid_times(t, float(a), float(b), 1.0 / float(r.hz))}
    every = sorted(set(np.asarray(t, float).tolist()))
    if all(p is not None for p in picks.values()):
        every = sorted(set().union(*picks.values())) if picks else []

    def want(smp) -> list:
        out = []
        for r in readers:
            p = picks[id(r)]
            if p is not None:
                if float(smp.t_ms) in p:
                    out.append(r)
                continue
            spans = getattr(r, "spans", None)
            if spans is None or any(a <= smp.t_ms <= b for a, b in spans):
                out.append(r)
        return out
    return every, want


def _feed(reader, smp, usage) -> None:
    """Feed one reader, under the OpenCV thread count it declares.

    A reader whose OpenCV calls work on small crops declares `cv_threads = 1`:
    OpenCV's pool spends more CPU starting threads on a minimap crop than the
    work costs. Measured 2026-09-26 over every cached round frame, CPU per
    frame with OpenCV's pool against one thread, reader state identical:

        session        frames   minimap          minimap_dark
        7010b3d62460   15705    24.5 -> 14.0 ms  39.2 -> 25.7 ms
        a06f04a0059f   20778    23.7 -> 12.8 ms  31.4 -> 23.6 ms
        043bafca271a   14629    14.1 ->  8.5 ms  24.7 -> 13.7 ms

    Wall per frame rose by 0-11% on five of the six, and 42% (11.5 -> 16.3
    ms) on a06f04a0059f's minimap_dark. The count is process-wide in OpenCV, so it is set around this reader's feed
    and restored for the next reader; a toggle costs about a microsecond.
    """
    threads = getattr(reader, "cv_threads", None)
    if threads is not None:
        import cv2
        before = cv2.getNumThreads()
        cv2.setNumThreads(threads)
    try:
        if usage is None:
            reader.feed(smp)
        else:
            usage.feed(reader, smp)
    finally:
        if threads is not None:
            cv2.setNumThreads(before)


def _cache_rois(reader) -> tuple[str, ...]:
    """The crops a pass decodes for `reader`: the ROIs it declares it reads
    (`roi_cache.declare_set`), else its whole cache set."""
    from .roi_cache import CACHE_SETS
    return tuple(getattr(reader, "cache_rois", None) or CACHE_SETS[reader.cache_set])
