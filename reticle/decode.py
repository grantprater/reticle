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
