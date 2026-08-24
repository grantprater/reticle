"""L1 primitives: cheap per-frame measurements (design doc SS3 stage 02, SS7).

Nothing here is a model. Every column is a deterministic function of pixels,
which is what makes L1 recomputable, auditable, and cheap enough to run over a
whole capture on the client.

These are the columns stage 01 segmentation consumes. They are deliberately
generic -- motion, luminance, edge density, and per-ROI perceptual hashes --
because they are the signals that survive a HUD restyle, and because they are
the inputs a trained state classifier would take later.
"""

from __future__ import annotations

import numpy as np

import cv2

from .profiles import Profile

# Working resolution for whole-frame statistics. Small enough to be free,
# large enough that motion and edge density stay meaningful.
_THUMB = (160, 90)


def _dhash(gray: np.ndarray, size: int = 8) -> int:
    """64-bit difference hash: compares each pixel to its right neighbour."""
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    bits = 0
    for bit in diff.flatten():
        bits = (bits << 1) | int(bit)
    return bits


def hamming(a: int, b: int) -> int:
    return int(bin(a ^ b).count("1"))


def frame_columns(profile: Profile) -> list[str]:
    """Column names produced per sampled frame, in write order."""
    cols = ["frame_idx", "t_ms", "motion", "luma_mean", "luma_std", "edge_density"]
    for name in profile.roi_names:
        cols += [f"{name}_luma", f"{name}_std", f"{name}_edge", f"{name}_dhash", f"{name}_dchange"]
    return cols


class PrimitiveExtractor:
    """Stateful across frames -- motion and dhash deltas need the previous sample."""

    def __init__(self, profile: Profile, width: int, height: int):
        self.profile = profile
        self._roi_px = {r.name: r.pixels(width, height) for r in profile.rois}
        self._prev_thumb: np.ndarray | None = None
        self._prev_dhash: dict[str, int] = {}

    def process(self, frame: np.ndarray, frame_idx: int, t_ms: float) -> dict:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        thumb = cv2.resize(gray, _THUMB, interpolation=cv2.INTER_AREA)
        thumb_f = thumb.astype(np.float32)

        if self._prev_thumb is None:
            motion = 0.0
        else:
            motion = float(np.abs(thumb_f - self._prev_thumb).mean() / 255.0)
        self._prev_thumb = thumb_f

        edges = cv2.Canny(thumb, 60, 160)

        row: dict = {
            "frame_idx": int(frame_idx),
            "t_ms": float(t_ms),
            "motion": motion,
            "luma_mean": float(thumb_f.mean() / 255.0),
            "luma_std": float(thumb_f.std() / 255.0),
            "edge_density": float((edges > 0).mean()),
        }

        for name, (x0, y0, x1, y1) in self._roi_px.items():
            crop = gray[y0:y1, x0:x1]
            crop_edges = cv2.Canny(crop, 60, 160)
            h = _dhash(crop)
            prev = self._prev_dhash.get(name)
            row[f"{name}_luma"] = float(crop.mean() / 255.0)
            row[f"{name}_std"] = float(crop.std() / 255.0)
            row[f"{name}_edge"] = float((crop_edges > 0).mean())
            row[f"{name}_dhash"] = h
            # 0 on the first frame means "no change measured yet", not "static".
            row[f"{name}_dchange"] = 0 if prev is None else hamming(h, prev)
            self._prev_dhash[name] = h

        return row
