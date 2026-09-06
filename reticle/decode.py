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

import cv2
import numpy as np


@dataclass
class Sample:
    frame_idx: int
    t_ms: float
    frame: np.ndarray  # BGR, full resolution


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
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    stride = 1
    if nominal_fps > 0 and target_hz > 0:
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
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    spans = sorted(spans_ms)
    step_ms = 1000.0 / target_hz if target_hz > 0 else 0.0
    si = 0
    next_t = spans[0][0] if spans else None
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
                    next_t = max(next_t if next_t is not None else 0.0, spans[si][0])
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
    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")

    state = {}
    for name, (hz, spans) in requests.items():
        state[name] = {
            "step": 1000.0 / hz if hz > 0 else 0.0,
            "spans": sorted(spans) if spans else None,
            "si": 0,
            "next_t": None,
        }
    # The last moment anyone is interested in: past it there is nothing to do.
    ends = []
    for st in state.values():
        ends.append(st["spans"][-1][1] if st["spans"] else float("inf"))
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
