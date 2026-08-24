"""Stage 00: fingerprint a source file into a stable identity.

Design doc SS3 stage 00 and SS7: raw media never moves and never gets copied
into the store. All we keep is a manifest pointing at where it lives, keyed by
a content digest so re-ingesting the same file is recognised as the same
session.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, asdict
from pathlib import Path

import cv2

# Sampled-digest parameters. Hashing a 20 GB capture end to end costs minutes
# and buys nothing here -- size plus three windows is ample to distinguish
# recordings while staying effectively instant.
_CHUNK = 8 * 1024 * 1024


@dataclass
class SourceFingerprint:
    path: str
    filename: str
    size_bytes: int
    content_key: str
    session_id: str
    width: int
    height: int
    fps: float
    frame_count: int
    duration_ms: float
    aspect: str

    def as_dict(self) -> dict:
        return asdict(self)


def content_key(path: Path) -> str:
    """Sampled digest of a media file.

    Reads the head, midpoint and tail rather than the whole file. This is an
    identity key, not an integrity check -- it will not detect a corrupted
    middle, and is not meant to.
    """
    size = path.stat().st_size
    h = hashlib.blake2b(digest_size=16)
    h.update(str(size).encode())
    with path.open("rb") as fh:
        for offset in (0, max(0, size // 2 - _CHUNK // 2), max(0, size - _CHUNK)):
            fh.seek(offset)
            h.update(fh.read(_CHUNK))
    return h.hexdigest()


def _aspect(width: int, height: int) -> str:
    if height <= 0:
        return "unknown"
    ratio = width / height
    for label, value in (("16:9", 16 / 9), ("16:10", 16 / 10), ("21:9", 21 / 9), ("4:3", 4 / 3)):
        if abs(ratio - value) < 0.02:
            return label
    return f"{ratio:.3f}:1"


def fingerprint(path: str | os.PathLike) -> SourceFingerprint:
    """Probe container metadata and derive a deterministic session id."""
    p = Path(path).resolve()
    if not p.is_file():
        raise SystemExit(f"not a file: {p}")

    cap = cv2.VideoCapture(str(p))
    if not cap.isOpened():
        raise SystemExit(
            f"could not open {p.name} -- OpenCV has no decoder for this container/codec"
        )
    try:
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS)) or 0.0
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    finally:
        cap.release()

    if width <= 0 or height <= 0:
        raise SystemExit(f"{p.name}: decoder reported no frame dimensions")

    # Container metadata lies often enough to be worth guarding. A missing or
    # absurd fps is reported rather than silently propagated into timestamps.
    if not (1.0 <= fps <= 480.0):
        fps = 0.0
    duration_ms = (frame_count / fps * 1000.0) if (fps and frame_count > 0) else 0.0

    key = content_key(p)
    return SourceFingerprint(
        path=str(p),
        filename=p.name,
        size_bytes=p.stat().st_size,
        content_key=key,
        session_id=key[:12],
        width=width,
        height=height,
        fps=fps,
        frame_count=max(0, frame_count),
        duration_ms=duration_ms,
        aspect=_aspect(width, height),
    )
