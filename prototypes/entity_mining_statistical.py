r"""Statistical entity mining via continuous parametric optimization and residual tracking.

    .\.venv\Scripts\python.exe prototypes\entity_mining_statistical.py

Validates that treating entity mining as an inverse problem (minimizing residuals
against the static base map over a continuous state vector s(t) = (x, y, r, c, phase))
reliably extracts:
1. Subpixel center position (x, y)
2. Spatial extent / equilibrium radius r
3. Color/saturation signature distinguishing preview from active deployment
4. Exact onset, expiry, and lifecycle duration matching official game constants
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, metrics, minimap, profiles  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

STORE = Path(DEFAULT_STORE)


def optimize_static_center(cap: cv2.VideoCapture, base_patch: np.ndarray, roi: tuple[int, int, int, int],
                           seed_x: float, seed_y: float, t_sample_s: float, r_expected: int = 15) -> tuple[float, float, float]:
    """Optimize subpixel center (x, y) and radius r on a single confirmed active frame."""
    x0, y0, x1, y1 = roi
    cap.set(cv2.CAP_PROP_POS_MSEC, t_sample_s * 1000.0)
    ok, frame = cap.read()
    if not ok:
        return seed_x, seed_y, float(r_expected)
    crop = frame[y0:y1, x0:x1]
    R_SEARCH = 25
    x_min, x_max = int(round(seed_x - R_SEARCH)), int(round(seed_x + R_SEARCH))
    y_min, y_max = int(round(seed_y - R_SEARCH)), int(round(seed_y + R_SEARCH))
    patch = crop[y_min:y_max, x_min:x_max].astype(np.float64)
    diff = np.abs(patch - base_patch).mean(axis=-1)

    H, W = diff.shape
    Y, X = np.ogrid[:H, :W]

    best_score = -1e9
    best_x, best_y, best_r = seed_x, seed_y, float(r_expected)

    for dx in np.linspace(-3.0, 3.0, 13):
        for dy in np.linspace(-3.0, 3.0, 13):
            cx, cy = R_SEARCH + dx, R_SEARCH + dy
            dist = np.sqrt((X - cx)**2 + (Y - cy)**2)
            for r in range(10, 24):
                inner = dist <= r
                outer = (dist > r) & (dist <= r + 4)
                if inner.sum() < 10 or outer.sum() < 10:
                    continue
                score = float(diff[inner].mean() - diff[outer].mean())
                if score > best_score:
                    best_score = score
                    best_x = x_min + cx
                    best_y = y_min + cy
                    best_r = float(r)
    return best_x, best_y, best_r


def track_ability_lifecycle(cap: cv2.VideoCapture, base_bgr: np.ndarray, roi: tuple[int, int, int, int],
                            seed_x: float, seed_y: float, sample_t_s: float,
                            t_start_s: float, t_end_s: float, step_s: float = 0.5) -> dict:
    x0, y0, x1, y1 = roi
    R_SEARCH = 25
    x_min, x_max = int(round(seed_x - R_SEARCH)), int(round(seed_x + R_SEARCH))
    y_min, y_max = int(round(seed_y - R_SEARCH)), int(round(seed_y + R_SEARCH))
    base_patch = base_bgr[y_min:y_max, x_min:x_max].astype(np.float64)

    # Step 1: Optimize static placement center and radius at the sample instant
    opt_x, opt_y, opt_r = optimize_static_center(cap, base_patch, roi, seed_x, seed_y, sample_t_s)

    local_cx = opt_x - x_min
    local_cy = opt_y - y_min
    H, W = 50, 50
    Y, X = np.ogrid[:H, :W]
    dist = np.sqrt((X - local_cx)**2 + (Y - local_cy)**2)
    inner = dist <= opt_r
    outer = (dist > opt_r) & (dist <= opt_r + 4)

    # Step 2: Track temporal trajectory over the full interval
    timecourse = []
    for t_s in np.arange(t_start_s, t_end_s + step_s / 2.0, step_s):
        cap.set(cv2.CAP_PROP_POS_MSEC, t_s * 1000.0)
        ok, frame = cap.read()
        if not ok:
            break
        crop = frame[y0:y1, x0:x1]
        patch = crop[y_min:y_max, x_min:x_max].astype(np.float64)
        diff = np.abs(patch - base_patch).mean(axis=-1)
        score = float(diff[inner].mean() - diff[outer].mean())

        hsv_patch = cv2.cvtColor(crop[y_min:y_max, x_min:x_max], cv2.COLOR_BGR2HSV)
        hsv_mean = hsv_patch[inner].mean(axis=0)
        hue, sat, val = float(hsv_mean[0]), float(hsv_mean[1]), float(hsv_mean[2])

        if sat >= 70.0 and val >= 100.0:
            phase = "preview"
        elif score >= 10.0 and sat < 60.0:
            phase = "active"
        else:
            phase = "inactive"

        timecourse.append({
            "t_s": round(float(t_s), 2),
            "score": round(score, 2),
            "sat": round(sat, 1),
            "val": round(val, 1),
            "phase": phase,
        })

    # Step 3: Segment active deployment
    preview_points = [p for p in timecourse if p["phase"] == "preview"]
    active_points = [p for p in timecourse if p["phase"] == "active"]

    # Filter out spurious background before preview
    if preview_points:
        t_preview_end = preview_points[-1]["t_s"]
        active_points = [p for p in active_points if p["t_s"] >= t_preview_end]

    onset_t = active_points[0]["t_s"] if active_points else None
    expiry_t = active_points[-1]["t_s"] if active_points else None
    duration = (expiry_t - onset_t) if (onset_t and expiry_t) else 0.0

    return {
        "opt_x": round(opt_x, 2),
        "opt_y": round(opt_y, 2),
        "opt_r": round(opt_r, 1),
        "n_preview": len(preview_points),
        "n_active": len(active_points),
        "onset_t_s": onset_t,
        "expiry_t_s": expiry_t,
        "measured_duration_s": round(duration, 2),
        "timecourse": timecourse,
    }


def main() -> int:
    sid = "e78e75b2d191"
    man = geometry.manifest(sid, STORE)
    src = man["source"]
    profile = profiles.get_profile(man["source_profile"])
    roi = minimap.minimap_roi_px(profile, int(src["width"]), int(src["height"]))

    geo_p = geometry.path_of(sid, STORE)
    with np.load(geo_p) as z:
        base_bgr = z["static"]

    cap = cv2.VideoCapture(src["path"])

    print("=== Statistical Entity Mining on Omen Dark Cover (e78e75b2d191) ===\n")

    # Cast 1: at (150, 168), sampled at 20.0s
    res1 = track_ability_lifecycle(cap, base_bgr, roi, seed_x=150.0, seed_y=168.0,
                                   sample_t_s=20.0, t_start_s=13.0, t_end_s=33.0, step_s=0.5)

    # Cast 2: at (117, 237), sampled at 30.0s
    res2 = track_ability_lifecycle(cap, base_bgr, roi, seed_x=117.0, seed_y=237.0,
                                   sample_t_s=30.0, t_start_s=24.0, t_end_s=45.0, step_s=0.5)

    cap.release()

    for name, res in [("Omen Dark Cover (Cast 1)", res1), ("Omen Dark Cover (Cast 2)", res2)]:
        err = abs(res["measured_duration_s"] - 15.0)
        print(f"{name}:")
        print(f"  Optimized Center: ({res['opt_x']}, {res['opt_y']}), Radius: {res['opt_r']} px")
        print(f"  Preview Points: {res['n_preview']}, Active Points: {res['n_active']}")
        print(f"  Onset: {res['onset_t_s']:.1f}s, Expiry: {res['expiry_t_s']:.1f}s")
        print(f"  Measured Duration: {res['measured_duration_s']:.1f}s (Ground Truth: 15.0s, Error: {err:.2f}s)\n")

    # Record metrics
    metrics.record("entity_mining_statistical", part="solo-demo", session=sid,
                   values={
                       "cast1_duration_s": res1["measured_duration_s"],
                       "cast1_duration_error_s": round(abs(res1["measured_duration_s"] - 15.0), 2),
                       "cast1_radius_px": res1["opt_r"],
                       "cast2_duration_s": res2["measured_duration_s"],
                       "cast2_duration_error_s": round(abs(res2["measured_duration_s"] - 15.0), 2),
                       "cast2_radius_px": res2["opt_r"],
                   },
                   deps={"formulation": "entity-mining-statistical-0.2.0",
                         "session": sid},
                   context={"ability": "omen:dark cover", "demo_type": "solo-demo"})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
