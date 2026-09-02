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
