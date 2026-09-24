r"""Statistical entity mining of directional / trajectory ability (Hunter's Fury).

    .\.venv\Scripts\python.exe prototypes\beam_mining_statistical.py

Validates inverse rendering and continuous parametric optimization for directional
trajectory entities:
    beam(x0, y0, theta, L, w)
originating from the casting agent's icon position on the minimap.

Recovers:
1. Continuous firing angle theta for each distinct blast pulse
2. Separation between aiming preview and active energy blast pulses
3. Complete active instance lifecycle span matching domain constants (6.0s duration)
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


def optimize_beam_angle(vx: np.ndarray, vy: np.ndarray,
                        diff: np.ndarray, cyan: np.ndarray,
                        map_mask: np.ndarray,
                        L: float = 240.0, w: float = 16.0,
                        collar_w: float = 8.0) -> tuple[float, float, float]:
    """Optimize beam angle theta continuously via coarse-to-fine residual optimization.

    Returns:
        (best_theta_deg, best_cyan_score, best_diff_score)
    """
    # 1. Coarse sweep 0 to 360 degrees (step 2 deg)
    thetas_coarse = np.arange(0, 360, 2.0)
    best_c_score = -1e9
    best_th = 0.0

    for th in thetas_coarse:
        rad = np.radians(th)
        cos_t = np.cos(rad)
        sin_t = np.sin(rad)
        l_proj = vx * cos_t + vy * sin_t
        d_perp = np.abs(-vx * sin_t + vy * cos_t)

        beam_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp <= w / 2.0) & map_mask
        collar_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp > w / 2.0) & (d_perp <= w / 2.0 + collar_w) & map_mask

        if beam_mask.sum() < 20 or collar_mask.sum() < 20:
            continue
        sc = float(cyan[beam_mask].mean() - cyan[collar_mask].mean())
        if sc > best_c_score:
            best_c_score = sc
            best_th = th

    # 2. Fine sub-degree optimization (+/- 3.0 deg around best_th, step 0.2 deg)
    fine_thetas = np.arange(best_th - 3.0, best_th + 3.1, 0.2)
    best_fine_score = best_c_score
    best_fine_th = best_th

    for th in fine_thetas:
        rad = np.radians(th)
        cos_t = np.cos(rad)
        sin_t = np.sin(rad)
        l_proj = vx * cos_t + vy * sin_t
        d_perp = np.abs(-vx * sin_t + vy * cos_t)

        beam_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp <= w / 2.0) & map_mask
        collar_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp > w / 2.0) & (d_perp <= w / 2.0 + collar_w) & map_mask

        if beam_mask.sum() < 20 or collar_mask.sum() < 20:
            continue
        sc = float(cyan[beam_mask].mean() - cyan[collar_mask].mean())
        if sc > best_fine_score:
            best_fine_score = sc
            best_fine_th = th

    # 3. Compute diff score on the optimal beam
    rad = np.radians(best_fine_th)
    cos_t = np.cos(rad)
    sin_t = np.sin(rad)
    l_proj = vx * cos_t + vy * sin_t
    d_perp = np.abs(-vx * sin_t + vy * cos_t)
    beam_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp <= w / 2.0) & map_mask
    collar_mask = (l_proj >= 15.0) & (l_proj <= L) & (d_perp > w / 2.0) & (d_perp <= w / 2.0 + collar_w) & map_mask
    diff_sc = float(diff[beam_mask].mean() - diff[collar_mask].mean()) if beam_mask.sum() >= 20 else 0.0

    return float(best_fine_th % 360.0), float(best_fine_score), float(diff_sc)


def track_beam_lifecycle(sid: str = "02cf738b1c8f",
                         t_start_s: float = 28.0,
                         t_end_s: float = 35.5,
                         step_s: float = 0.1) -> dict:
    """Track parametric beam across the Hunter's Fury window and segment pulses."""
    man = geometry.manifest(sid, STORE)
    profile = profiles.get_profile(man["source_profile"])
    roi = minimap.minimap_roi_px(profile, 1920, 1080)
    x0, y0, x1, y1 = roi

    geo_p = geometry.path_of(sid, STORE)
    with np.load(geo_p) as z:
        base_bgr = z["static"]

    series_p = STORE / "series" / f"{sid}.npz"
    series = np.load(series_p)
    t_ms_arr = series["t_ms"]
    self_xs = series["self_x"][0]
    self_ys = series["self_y"][0]

    video_path = man["source"]["path"]
    cap = cv2.VideoCapture(video_path)

    H, W, _ = base_bgr.shape
    Y, X = np.ogrid[:H, :W]
    dist_from_center = np.sqrt((X - 232.5)**2 + (Y - 242.5)**2)
    map_mask = dist_from_center <= 215.0

    timecourse = []
    t_samples = np.arange(t_start_s, t_end_s + step_s / 2.0, step_s)

    for t_s in t_samples:
        t_ms = t_s * 1000.0
        idx = int(np.argmin(np.abs(t_ms_arr - t_ms)))
        sx, sy = float(self_xs[idx]), float(self_ys[idx])

        cap.set(cv2.CAP_PROP_POS_MSEC, t_ms)
        ok, frame = cap.read()
        if not ok:
            continue
        crop = frame[y0:y1, x0:x1]

        diff = np.abs(crop.astype(np.float32) - base_bgr.astype(np.float32)).mean(axis=-1)
        hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
        cyan = ((hsv[..., 0] >= 75) & (hsv[..., 0] <= 105) & (hsv[..., 1] >= 70)).astype(np.float32) * (hsv[..., 2] / 255.0)
        cyan_map_count = int(((hsv[..., 0] >= 75) & (hsv[..., 0] <= 105) & (hsv[..., 1] >= 80) & (hsv[..., 2] >= 120) & map_mask).sum())
        cyan_count = int(((hsv[..., 0] >= 75) & (hsv[..., 0] <= 105) & (hsv[..., 1] >= 80) & (hsv[..., 2] >= 120)).sum())

        vx = X - sx
        vy = Y - sy

        best_th, c_score, d_score = optimize_beam_angle(vx, vy, diff, cyan, map_mask)

        # Pulse state classification: elevated energy and coherent beam contrast
        if cyan_map_count >= 3200 and c_score >= 0.35:
            state = "blast"
        elif cyan_map_count >= 1800:
            state = "aiming"
        else:
            state = "idle"

        timecourse.append({
            "t_s": round(float(t_s), 2),
            "self_pos": (round(sx, 1), round(sy, 1)),
            "theta": round(best_th, 1),
            "cyan_score": round(c_score, 3),
            "diff_score": round(d_score, 2),
            "cyan_px": cyan_count,
            "cyan_map_px": cyan_map_count,
            "state": state,
        })

    cap.release()

    # Segment active blast pulses with temporal gap closing (max gap <= 0.35s)
    raw_blast_frames = [p for p in timecourse if p["state"] == "blast"]
    pulses = []
    current_pulse = []

    for p in raw_blast_frames:
        if not current_pulse:
            current_pulse.append(p)
        else:
            dt = p["t_s"] - current_pulse[-1]["t_s"]
            if dt <= 0.35:
                current_pulse.append(p)
            else:
                if len(current_pulse) >= 2:
                    pulses.append(current_pulse)
                current_pulse = [p]
    if current_pulse and len(current_pulse) >= 2:
        pulses.append(current_pulse)

    # Summarize pulses
    pulse_summaries = []
    for i, pulse in enumerate(pulses, start=1):
        onset_t = pulse[0]["t_s"]
        offset_t = pulse[-1]["t_s"]
        peak_frame = max(pulse, key=lambda x: x["cyan_px"])
        # Circular mean or weighted median of theta across pulse
        thetas = [f["theta"] for f in pulse]
        pulse_summaries.append({
            "pulse_id": i,
            "onset_t_s": onset_t,
            "offset_t_s": offset_t,
            "duration_s": round(offset_t - onset_t + step_s, 2),
            "peak_t_s": peak_frame["t_s"],
            "peak_theta_deg": peak_frame["theta"],
            "mean_theta_deg": round(float(np.mean(thetas)), 1),
            "peak_cyan_px": peak_frame["cyan_px"],
            "peak_cyan_score": peak_frame["cyan_score"],
            "peak_diff_score": peak_frame["diff_score"],
        })

    # Overall ability lifecycle
    active_frames = [p for p in timecourse if p["state"] in ("aiming", "blast")]
    cast_onset_t = active_frames[0]["t_s"] if active_frames else None
    cast_expiry_t = active_frames[-1]["t_s"] if active_frames else None

    # First blast to last blast
    first_blast_onset = pulse_summaries[0]["onset_t_s"] if pulse_summaries else None
    last_blast_offset = pulse_summaries[-1]["offset_t_s"] if pulse_summaries else None
    blast_span_s = round(last_blast_offset - first_blast_onset, 2) if (first_blast_onset and last_blast_offset) else 0.0
    total_cast_span_s = round(last_blast_offset - cast_onset_t, 2) if (cast_onset_t and last_blast_offset) else 0.0

    return {
        "session_id": sid,
        "n_frames": len(timecourse),
        "n_pulses_recovered": len(pulse_summaries),
        "pulses": pulse_summaries,
        "first_blast_onset_s": first_blast_onset,
        "last_blast_offset_s": last_blast_offset,
        "blast_span_s": blast_span_s,
        "cast_onset_s": cast_onset_t,
        "cast_expiry_s": cast_expiry_t,
        "total_cast_span_s": total_cast_span_s,
        "timecourse": timecourse,
    }


def main() -> int:
    sid = "02cf738b1c8f"
    print(f"=== Statistical Beam Mining on Sova Hunter's Fury ({sid}) ===\n")

    res = track_beam_lifecycle(sid, t_start_s=28.0, t_end_s=35.5, step_s=0.1)

    print(f"Total Evaluated Frames: {res['n_frames']}")
    print(f"Cast Onset (Windup): {res['cast_onset_s']:.2f}s, Ability Expiry: {res['cast_expiry_s']:.2f}s")
    print(f"Distinct Blast Pulses Recovered: {res['n_pulses_recovered']}\n")

    for p in res["pulses"]:
        print(f"Pulse {p['pulse_id']}:")
        print(f"  Window: {p['onset_t_s']:.2f}s - {p['offset_t_s']:.2f}s (Duration: {p['duration_s']:.2f}s)")
        print(f"  Peak Instant: t = {p['peak_t_s']:.2f}s")
        print(f"  Firing Angle (Theta): {p['peak_theta_deg']:.1f} deg (Mean: {p['mean_theta_deg']:.1f} deg)")
        print(f"  Peak Beam Energy: {p['peak_cyan_px']} cyan px")
        print(f"  Residual Contrast Score: {p['peak_cyan_score']:.3f} (diff: {p['peak_diff_score']:.2f})\n")

    print(f"First Blast Onset -> Last Blast Offset Span: {res['blast_span_s']:.2f}s")
    print(f"Windup Onset -> Last Blast Offset Span: {res['total_cast_span_s']:.2f}s (Domain target: 6.0s)\n")

    # Record metrics
    metrics.record(
        "beam_mining_statistical",
        part="solo-demo",
        session=sid,
        values={
            "n_pulses_recovered": res["n_pulses_recovered"],
            "pulse1_theta_deg": res["pulses"][0]["peak_theta_deg"],
            "pulse2_theta_deg": res["pulses"][1]["peak_theta_deg"],
            "pulse3_theta_deg": res["pulses"][2]["peak_theta_deg"],
            "blast_span_s": res["blast_span_s"],
            "total_cast_span_s": res["total_cast_span_s"],
            "duration_error_s": round(abs(res["total_cast_span_s"] - 6.0), 2),
        },
        deps={
            "formulation": "beam-mining-statistical-0.1.0",
            "session": sid,
        },
        context={
            "ability": "sova:hunter's fury",
            "demo_type": "solo-demo",
            "map": "ascent",
        },
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
