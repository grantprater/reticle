"""Synthetic capture generator, for exercising the pipeline without a VOD.

This is a plumbing fixture, not a simulation. It renders the coarse *signal
structure* the baseline segmenter keys on -- a busy top-left panel that changes
every frame, high-contrast chrome in the bottom corners, and a scene that moves
or holds -- so that ingest, storage, segmentation and inspection can be
verified end to end before any real footage exists.

Do not calibrate thresholds against this. Calibrate against Valorant.
"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from .profiles import DEFAULT_PROFILE, get_profile
from .segment import HUD_CHROME_ROIS

# (state, seconds). Mirrors a plausible match shape: load in, play, sit dead,
# play again, back to a menu.
DEFAULT_SCRIPT = [
    ("off", 6),
    ("active", 20),
    ("idle", 8),
    ("active", 16),
    ("off", 5),
]


def _chrome(frame: np.ndarray, box: tuple[int, int, int, int], n_lines: int = 9) -> None:
    """Fill a ROI with high-contrast line art -- what the *_edge columns measure."""
    x0, y0, x1, y1 = box
    cv2.rectangle(frame, (x0, y0), (x1, y1), (60, 65, 70), -1)
    cv2.rectangle(frame, (x0, y0), (x1, y1), (200, 200, 200), 1)
    step = max(2, (x1 - x0) // n_lines)
    for x in range(x0 + step // 2, x1 - 1, step):
        cv2.line(frame, (x, y0 + 2), (x, y1 - 2), (235, 235, 235), 2)


def _draw(
    state: str,
    t: float,
    w: int,
    h: int,
    rng: np.random.Generator,
    rois: dict[str, tuple[int, int, int, int]],
) -> np.ndarray:
    frame = np.full((h, w, 3), 18, dtype=np.uint8)

    if state == "off":
        # A menu: large flat panels, no minimap, no corner chrome.
        cv2.rectangle(frame, (int(w * 0.2), int(h * 0.25)), (int(w * 0.8), int(h * 0.75)), (42, 40, 38), -1)
        cv2.putText(frame, "MENU", (int(w * 0.42), int(h * 0.52)),
                    cv2.FONT_HERSHEY_SIMPLEX, w / 900.0, (120, 120, 120), 2, cv2.LINE_AA)
        return frame

    # Scene: a moving gradient plus drifting shapes when active, held when idle.
    phase = t if state == "active" else 3.0
    xs = np.linspace(0, 6 * np.pi, w, dtype=np.float32)
    band = (np.sin(xs + phase * 2.2) * 40 + 70).astype(np.uint8)
    frame[:, :, 1] = np.tile(band, (h, 1))
    for k in range(6):
        cx = int((w * 0.5) + np.cos(phase * 1.3 + k) * w * 0.3)
        cy = int((h * 0.5) + np.sin(phase * 0.9 + k) * h * 0.25)
        cv2.circle(frame, (cx, cy), max(6, int(h * 0.03)), (200, 190, 170), -1)

    # Minimap analogue: top-left panel with dots that move every frame, which is
    # what drives minimap_dchange.
    mx0, my0, mx1, my1 = rois["minimap"]
    cv2.rectangle(frame, (mx0, my0), (mx1, my1), (30, 34, 40), -1)
    cv2.rectangle(frame, (mx0, my0), (mx1, my1), (90, 100, 110), 1)
    n_dots = 8 if state == "active" else 2
    for _ in range(n_dots):
        dx = rng.integers(mx0 + 4, mx1 - 4)
        dy = rng.integers(my0 + 4, my1 - 4)
        cv2.circle(frame, (int(dx), int(dy)), max(2, int(h * 0.005)), (240, 240, 240), -1)

    # HUD chrome: high edge density in whichever ROIs the profile treats as
    # chrome, read off the profile rather than hardcoded, so re-measuring a
    # profile against real footage cannot silently desync this fixture.
    for name in HUD_CHROME_ROIS:
        if name in rois:
            _chrome(frame, rois[name])

    # Scoreline.
    if "scoreline" in rois:
        sx0, sy0, sx1, sy1 = rois["scoreline"]
        cv2.putText(frame, "7 1:24 5", (sx0 + 2, sy1 - 4), cv2.FONT_HERSHEY_SIMPLEX,
                    (sx1 - sx0) / 220.0, (225, 225, 225), 2, cv2.LINE_AA)
    return frame


def _open_writer(path: Path, fps: float, w: int, h: int):
    for fourcc, suffix in (("mp4v", ".mp4"), ("MJPG", ".avi")):
        out = path.with_suffix(suffix)
        writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*fourcc), fps, (w, h))
        if writer.isOpened():
            return writer, out
        writer.release()
    raise SystemExit("OpenCV could not open any video writer (tried mp4v and MJPG)")


def generate(
    path: str | Path,
    width: int = 1280,
    height: int = 720,
    fps: float = 30.0,
    script: list[tuple[str, int]] | None = None,
    seed: int = 7,
    profile: str = DEFAULT_PROFILE,
) -> tuple[Path, list[tuple[str, int]]]:
    script = script or DEFAULT_SCRIPT
    rois = {r.name: r.pixels(width, height) for r in get_profile(profile).rois}
    rng = np.random.default_rng(seed)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer, out_path = _open_writer(path, fps, width, height)
    try:
        t = 0.0
        for state, seconds in script:
            for _ in range(int(seconds * fps)):
                writer.write(_draw(state, t, width, height, rng, rois))
                t += 1.0 / fps
    finally:
        writer.release()
    return out_path, script
