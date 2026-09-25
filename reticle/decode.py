"""Frame sampling.

Decoding every frame is wasted work: stage 01 only needs enough temporal
resolution to find state boundaries, not to measure mechanics. We sample at a
target rate and skip the rest with grab(), which advances the decoder without
paying for colour conversion.

Timestamps come from the decoder (CAP_PROP_POS_MSEC) rather than
frame_index / fps, because OBS output is frequently variable-rate and the
nominal fps is then wrong.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
import math

import cv2
import numpy as np


@dataclass
class Sample:
    frame_idx: int
    t_ms: float
    frame: np.ndarray  # BGR, full resolution


def _sampling_step(target_hz: float) -> float:
    """Validated time between requested samples.

    A zero/negative/NaN rate used to mean "retrieve every frame" as an
    accidental consequence of the implementation.  That is not a useful
    sampling contract: callers must request a real rate, and native-rate
    windows use ``refine.iter_windows``.
    """
    if isinstance(target_hz, bool) or not isinstance(target_hz, (int, float)):
        raise ValueError("target_hz must be a finite positive number")
    target_hz = float(target_hz)
    if not math.isfinite(target_hz) or target_hz <= 0:
        raise ValueError("target_hz must be a finite positive number")
    return 1000.0 / target_hz


def _sampling_spans(spans_ms):
    """Validate and sort closed sampling spans; preserve empty as no work."""
    if spans_ms is None:
        return None
    spans = []
    for span in spans_ms:
        if len(span) != 2:
            raise ValueError("sampling span must have start and end")
        start, end = map(float, span)
        if (not math.isfinite(start) or not math.isfinite(end)
                or start < 0 or end < start):
            raise ValueError("sampling spans must be finite, nonnegative, and increasing")
        spans.append((start, end))
    return sorted(spans)


def sample_frames(
    path: str,
    target_hz: float,
    nominal_fps: float,
    max_frames: int | None = None,
) -> Iterator[Sample]:
    """Yield frames at approximately `target_hz`.

    `nominal_fps` sets the skip stride. If the container lied about fps we fall
    back to a stride of 1 and simply decode everything, which is slow but
    correct rather than silently sampling at the wrong rate.
    """
    _sampling_step(target_hz)
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    stride = 1
    if nominal_fps > 0:
        stride = max(1, int(round(nominal_fps / target_hz)))

    emitted = 0
    idx = 0
    try:
        while True:
            if max_frames is not None and emitted >= max_frames:
                break

            ok = cap.grab()
            if not ok:
                break

            if idx % stride == 0:
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    idx += 1
                    continue
                t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                if t_ms <= 0 and idx > 0 and nominal_fps > 0:
                    # Some decoders only populate POS_MSEC intermittently.
                    t_ms = idx / nominal_fps * 1000.0
                yield Sample(frame_idx=idx, t_ms=t_ms, frame=frame)
                emitted += 1

            idx += 1
    finally:
        cap.release()


def sample_at(path: str, targets_ms: list[float], nominal_fps: float) -> Iterator[Sample]:
    """Yield the frame at each of `targets_ms`, in ONE forward decode pass.

    Built for the shape every minimap validation prototype needed this session
    (xmark_eval, chokepoint_eval, location_banner_probe): many scattered,
    specific timestamps across a session -- windows around deaths, around
    banner transitions, random baseline windows -- not a uniform stride. Each
    of those scripts called `cap.set(CAP_PROP_POS_FRAMES, ...)` + `read()`
    once per sample instead, which re-finds the nearest keyframe and decodes
    forward from there on EVERY call. Independently, that's cheap; hundreds to
    thousands of times per session, it pinned every core for the better part
    of an hour running three of these scripts back to back.

    `targets_ms` must be sorted ascending (duplicates are fine, out of order is
    not -- construct the full target list and sort it before calling this).
    Cost here is one sequential decode bounded by the LAST target, using
    `grab()` to skip the frames between targets cheaply, the same trick
    `sample_frames` already uses. A target past the end of the video is
    simply never yielded -- callers already have to handle getting fewer
    samples than requested, same as a `cap.read()` that returns `ok=False`.
    """
    if any(b < a for a, b in zip(targets_ms, targets_ms[1:])):
        raise ValueError("targets_ms must be sorted ascending")

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    ti = 0
    idx = 0
    try:
        while ti < len(targets_ms):
            ok = cap.grab()
            if not ok:
                break
            t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if t_ms <= 0 and idx > 0 and nominal_fps > 0:
                t_ms = idx / nominal_fps * 1000.0
            if t_ms >= targets_ms[ti]:
                ok, frame = cap.retrieve()
                while ti < len(targets_ms) and targets_ms[ti] <= t_ms:
                    if ok and frame is not None:
                        yield Sample(frame_idx=idx, t_ms=t_ms, frame=frame)
                    ti += 1
            idx += 1
    finally:
        cap.release()


#: Targets closer than this share one seek: decoding forward through the gap
#: is cheaper than a seek, which lands on a keyframe and decodes forward anyway.
SEEK_GAP_MS = 4000.0


def windows_of(targets_ms: list[float], gap_ms: float = SEEK_GAP_MS) -> list[list[float]]:
    """Sorted targets split into runs wherever two neighbours are over `gap_ms` apart."""
    runs: list[list[float]] = []
    for t in targets_ms:
        if runs and t - runs[-1][-1] <= gap_ms:
            runs[-1].append(t)
        else:
            runs.append([t])
    return runs


def seek_at(path: str, targets_ms: list[float], nominal_fps: float,
            gap_ms: float = SEEK_GAP_MS) -> Iterator[Sample]:
    """`sample_at`'s contract for scattered targets: one seek per run of
    targets (`windows_of`) instead of one decode from the file start.

    Each run seeks to its first target and grabs forward, yielding a frame at
    the first timestamp at or after each target, as `sample_at` does, so a
    target list taken from a stored table returns the frames that table was
    read from. `frame_idx` comes from the decoder's position after the seek;
    a caller holding the stored index should trust that one.
    """
    if any(b < a for a, b in zip(targets_ms, targets_ms[1:])):
        raise ValueError("targets_ms must be sorted ascending")
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")
    try:
        for run in windows_of(targets_ms, gap_ms):
            if not cap.set(cv2.CAP_PROP_POS_MSEC, run[0]):
                raise ValueError("decoder could not seek to requested window")
            ti = 0
            while ti < len(run):
                if not cap.grab():
                    break
                t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                if t_ms < run[ti]:
                    continue
                ok, frame = cap.retrieve()
                idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES)) - 1
                while ti < len(run) and run[ti] <= t_ms:
                    if ok and frame is not None:
                        yield Sample(frame_idx=idx, t_ms=t_ms, frame=frame)
                    ti += 1
    finally:
        cap.release()


def sample_spans(path: str, spans_ms: list[tuple[float, float]], target_hz: float,
                  nominal_fps: float) -> Iterator[Sample]:
    """Yield frames at ~`target_hz` inside `spans_ms`, in ONE sequential pass.

    The uniform-stride counterpart to `sample_at()`: minimap position needs a
    higher, steady sample rate over the *active* portions of a whole session
    (15-20 Hz per the design doc, well above the 2 Hz HUD read), not scattered
    timestamps. A per-sample `cap.set()` seek would pay the same keyframe-seek
    cost `sample_at()` was built to avoid, and there are far more samples here
    than in any validation script that motivated it. `grab()` skips
    out-of-span frames for the price of a demux, not a decode.

    `spans_ms` need not be sorted; gaps between spans reset the stride so a
    span's first frame is never held hostage by the stride phase of the one
    before it.
    """
    spans = _sampling_spans(spans_ms)
    step_ms = _sampling_step(target_hz)
    if not spans:
        return

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    si = 0
    next_t = spans[0][0]
    idx = 0
    try:
        while si < len(spans):
            ok = cap.grab()
            if not ok:
                break
            t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if t_ms <= 0 and idx > 0 and nominal_fps > 0:
                t_ms = idx / nominal_fps * 1000.0
            while si < len(spans) and t_ms > spans[si][1]:
                si += 1
                if si < len(spans):
                    # A NEW SPAN IS A NEW PHASE. `max(next_t, s0)` kept the old
                    # stride whenever it landed past the new span's start, which
                    # is what the docstring above says does not happen and what
                    # `sample_multi` correctly does not do (it sets None). The
                    # two therefore disagreed by up to one frame at every span
                    # boundary, which quietly undercut `scan`'s claim to be
                    # frame-for-frame identical to running both stages.
                    next_t = spans[si][0]
            if si >= len(spans):
                break
            s0, s1 = spans[si]
            if s0 <= t_ms <= s1 and (next_t is None or t_ms >= next_t):
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    yield Sample(frame_idx=idx, t_ms=t_ms, frame=frame)
                next_t = t_ms + step_ms
            idx += 1
    finally:
        cap.release()


def sample_multi(
    path: str,
    nominal_fps: float,
    requests: dict[str, tuple[float, list[tuple[float, float]] | None]],
) -> Iterator[tuple[frozenset[str], Sample]]:
    """One decode, many readers. Yields `(who wants this frame, sample)`.

    `requests` maps a reader's name to `(target_hz, spans_ms | None)`, where
    `None` means the whole capture. A frame is retrieved only when at least one
    reader wants it, and the set says which -- so a caller runs several stages
    over one pass instead of one pass each.

    **Why this is worth having, measured 2026-09-05 on c40d950031bb.** Decoding
    is 93% of the cost of a stage: 300 sampled frames took 13.17 s to decode and
    0.94 s to read through the scoreline, bottom-HUD and killfeed extractors
    together. Nothing in the analysis is worth optimising, and the only lever
    is how many times the file is opened.

    The reason one pass can serve every rate is that **the sample rate is nearly
    free**. `grab()` decodes each frame regardless; only `retrieve()` converts
    and copies it, and that is the cheap half:

        2 minutes at  2 Hz     6.12 s    242 samples
        2 minutes at 15 Hz     8.04 s   1802 samples

    Seven times the frames for 31% more time. So `hud` (2 Hz, whole file) and
    `minimap` (15 Hz, active spans) as separate commands cost ~2 passes, and
    fused they cost ~1.31 -- and a probe that rides along costs almost nothing,
    which matters more than the arithmetic: the reason prototypes here re-decode
    a session each is that riding an existing pass was not expressible.

    Not a scheduler and deliberately not one. It owns no readers and calls no
    analysis; it decides which frames to hand out and nothing else, so a reader
    is an ordinary loop body and can still be run on its own.

    Stride is kept per reader as a next-timestamp, not as a frame count, because
    OBS output is variable-rate -- the same reason timestamps come from the
    decoder. A gap between spans resets that reader's phase so a span's first
    frame is never held hostage by the stride of the one before it.
    """
    state = {}
    for name, (hz, spans) in requests.items():
        checked_spans = _sampling_spans(spans)
        state[name] = {
            "step": _sampling_step(hz),
            "spans": checked_spans,
            "si": 0,
            "next_t": None,
        }
    # ``None`` means unrestricted.  An empty list means this reader has no
    # requested coverage; it must not silently become a full-capture scan.
    state = {name: st for name, st in state.items() if st["spans"] != []}
    if not state:
        return

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")
    # The last moment anyone is interested in: past it there is nothing to do.
    ends = []
    for st in state.values():
        ends.append(st["spans"][-1][1] if st["spans"] is not None else float("inf"))
    stop_after = max(ends) if ends else float("inf")

    idx = 0
    try:
        while True:
            if not cap.grab():
                break
            t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if t_ms <= 0 and idx > 0 and nominal_fps > 0:
                t_ms = idx / nominal_fps * 1000.0
            if t_ms > stop_after:
                break

            want = set()
            for name, st in state.items():
                spans = st["spans"]
                if spans is not None:
                    while st["si"] < len(spans) and t_ms > spans[st["si"]][1]:
                        st["si"] += 1
                        st["next_t"] = None       # new span, new phase
                    if st["si"] >= len(spans):
                        continue
                    s0, s1 = spans[st["si"]]
                    if not (s0 <= t_ms <= s1):
                        continue
                if st["next_t"] is None or t_ms >= st["next_t"]:
                    want.add(name)

            if want:
                ok, frame = cap.retrieve()
                if ok and frame is not None:
                    for name in want:
                        state[name]["next_t"] = t_ms + state[name]["step"]
                    yield frozenset(want), Sample(frame_idx=idx, t_ms=t_ms,
                                                 frame=frame)
            idx += 1
    finally:
        cap.release()


def sample_windows(
    path: str,
    nominal_fps: float,
    requests: dict[str, tuple[float, list[tuple[float, float]] | None]],
) -> Iterator[tuple[frozenset[str], Sample]]:
    """`sample_multi`'s contract, but SEEKING to each window instead of
    grabbing the file from the start. Same yields, different cost law.

    **Measured 2026-09-09 on c40d950031bb, one 10 s window at 850-860 s.**
    `sample_multi` pays for every frame between the file start and the last
    span end, because `grab()` is how it advances:

        sample_multi   60 Hz   601 frames   49.74 s
        sample_multi   15 Hz   141 frames   48.69 s
        sample_multi    2 Hz    21 frames   48.80 s
        this           60 Hz   600 frames    1.85 s

    So under `sample_multi` a 28.6x cut in retrieved frames buys 1.9% of the
    wall clock, and the temporal tier a planner chooses is very nearly free
    either way. The cost is the grab-through, and the only thing that removes
    it is not decoding the part of the file nobody asked about. That is what
    this does, and it is why `acquisition.execute_plan` routes through it: a
    variable-fidelity planner whose transport cost is fixed by the LAST
    timestamp it needs cannot deliver a saving no matter which tier it picks.

    Use `sample_multi` when the requests are unrestricted or cover most of the
    capture -- one sequential pass then beats a seek per span, and a reader
    asking for `spans=None` has no windows to seek to. Use this for the
    bounded trigger/audit windows an evidence request actually names.

    Seeks are coarse: `CAP_PROP_POS_MSEC` lands on or before a keyframe, so
    frames before the span start are decoded and dropped rather than yielded.
    That is the price of the seek and it is already paid inside one window.
    """
    state = {}
    for name, (hz, spans) in requests.items():
        checked = _sampling_spans(spans)
        if checked is None:
            raise ValueError(
                "sample_windows needs explicit spans; use sample_multi for "
                f"unrestricted coverage (reader {name!r} asked for none)"
            )
        state[name] = {"step": _sampling_step(hz), "spans": checked}
    state = {name: st for name, st in state.items() if st["spans"]}
    if not state:
        return

    # One merged decode window per union of interest, so overlapping requests
    # are not seeked to twice. Each reader keeps its own phase inside it.
    from .refine import merge_windows

    windows = merge_windows([span for st in state.values() for span in st["spans"]])

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")
    try:
        for start, end in windows:
            if not cap.set(cv2.CAP_PROP_POS_MSEC, start):
                raise ValueError("decoder could not seek to requested window")
            # A NEW WINDOW IS A NEW PHASE, the same rule `sample_spans` and
            # `sample_multi` follow at a span boundary.
            for st in state.values():
                st["next_t"] = None
            while True:
                if not cap.grab():
                    break
                t_ms = float(cap.get(cv2.CAP_PROP_POS_MSEC))
                if not math.isfinite(t_ms):
                    raise ValueError("decoder returned invalid timestamp")
                if t_ms < start:
                    continue
                if t_ms > end:
                    break
                want = set()
                for name, st in state.items():
                    if not any(s0 <= t_ms <= s1 for s0, s1 in st["spans"]):
                        continue
                    if st["next_t"] is None or t_ms >= st["next_t"]:
                        want.add(name)
                if not want:
                    continue
                ok, frame = cap.retrieve()
                if not ok or frame is None:
                    continue
                idx = cap.get(cv2.CAP_PROP_POS_FRAMES) - 1
                for name in want:
                    state[name]["next_t"] = t_ms + state[name]["step"]
                yield frozenset(want), Sample(frame_idx=int(idx), t_ms=t_ms,
                                              frame=frame)
    finally:
        cap.release()
