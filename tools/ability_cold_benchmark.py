"""Verifiable cold minimap ability tracking benchmark.

Evaluates cold temporal ability detection and tracking on spectator sessions
where no ability HUD tray is present (e.g. Cypher spectator clips).
Minimap ability discs are discovered cold, filtered against static map
geometry and local self-icons, clustered temporally into tracks, and
evaluated against ground-truth human annotations.

Cites [domain:minimap/transparency], [domain:capture/session-pixels-are-not-the-map].

Usage:
    .\\.venv\\Scripts\\python.exe tools/ability_cold_benchmark.py [--session SID] [--batch] [--store PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# Ensure reticle is on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import geometry
from reticle.minimap import slab_mask, self_icons, detect_ability_discs, BH_K, BH_MIN
from reticle.profiles import get_profile
from reticle.store import DEFAULT_STORE, Store

BENCHMARK_VERSION = "ability-cold-benchmark-0.1.0"
DEFAULT_SESSION = "d95cfad5693a"
TARGET_SPECTATOR_SESSIONS = [
    "d95cfad5693a",
    "eb10db50b1fb",
    "79a706a7ce4c",
]


def extract_persistent_tracks(
    cap: cv2.VideoCapture,
    fps: float,
    dur_s: float,
    roi_px: tuple[int, int, int, int],
    mask: np.ndarray,
    static_peaks: list[tuple[float, float, float]],
    step_s: float = 0.5,
    bh_min: int = BH_MIN,
    dist_tol_px: float = 18.0,
    track_d_max: float = 12.0,
    track_t_max: float = 2.0,
    persist_span_min: float = 3.0,
    persist_nobs_min: int = 5,
) -> list[dict]:
    """Sample minimap, detect ability discs, cluster into tracks, and filter for persistence."""
    px0, py0, px1, py1 = roi_px
    t = 0.0
    observations = []

    while t <= dur_s:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            break
        crop = frame[py0:py1, px0:px1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        s_icons = self_icons(crop, mask)
        self_xy = (s_icons[0]["cx"], s_icons[0]["cy"]) if s_icons else None

        discs = detect_ability_discs(
            gray, mask,
            static_peaks=static_peaks,
            self_xy=self_xy,
            k=BH_K,
            bh_min=bh_min,
            dist_tol_px=dist_tol_px,
        )
        for d in discs:
            observations.append({
                "t": round(t, 2),
                "x": float(d["cx"]),
                "y": float(d["cy"]),
                "resp": float(d["response"]),
            })
        t += step_s

    # Cluster observations into tracks
    tracks: list[dict] = []
    for obs in sorted(observations, key=lambda o: o["t"]):
        matched = None
        min_d = float("inf")
        for tr in tracks:
            last = tr["points"][-1]
            dt = obs["t"] - last["t"]
            d = np.hypot(obs["x"] - last["x"], obs["y"] - last["y"])
            if dt <= track_t_max and d < track_d_max:
                if d < min_d:
                    min_d = d
                    matched = tr
        if matched:
            matched["points"].append(obs)
        else:
            tracks.append({"points": [obs]})

    persistent = []
    for tr in tracks:
        pts = tr["points"]
        t_first = pts[0]["t"]
        t_last = pts[-1]["t"]
        span = round(t_last - t_first, 2)
        n_obs = len(pts)
        if span >= persist_span_min and n_obs >= persist_nobs_min:
            mean_x = round(float(np.mean([p["x"] for p in pts])), 1)
            mean_y = round(float(np.mean([p["y"] for p in pts])), 1)
            mean_resp = round(float(np.mean([p["resp"] for p in pts])), 1)
            persistent.append({
                "x": mean_x,
                "y": mean_y,
                "t_first": t_first,
                "t_last": t_last,
                "span": span,
                "n_obs": n_obs,
                "mean_response": mean_resp,
                "points": pts,
            })

    return persistent


def collapse_objects(rows: list[dict], collapse_px: int = 8) -> list[dict]:
    """Group close spatial annotations into distinct physical objects."""
    objs: dict = {}
    for r in rows:
        key = (int(r["x"]) // collapse_px, int(r["y"]) // collapse_px)
        objs.setdefault(key, []).append(r)
    collapsed = []
    for g in objs.values():
        rep = dict(g[0])
        rep["all_x"] = [r["x"] for r in g]
        rep["all_y"] = [r["y"] for r in g]
        rep["mean_x"] = round(float(np.mean(rep["all_x"])), 1)
        rep["mean_y"] = round(float(np.mean(rep["all_y"])), 1)
        rep["t_min_s"] = round(min(r["t_ms"] for r in g) / 1000.0, 2)
        rep["t_max_s"] = round(max(r["t_ms"] for r in g) / 1000.0, 2)
        rep["count"] = len(g)
        collapsed.append(rep)
    return collapsed


def score_tracks_against_labels(
    tracks: list[dict],
    labels_path: Path,
    match_radius_px: float = 10.0,
    match_dt: float = 2.5,
) -> dict:
    """Score predicted tracks against ground truth annotations."""
    if not labels_path.is_file():
        return {
            "error": f"labels file not found: {labels_path}",
            "n_pos_labels": 0, "n_neg_labels": 0,
            "tp_tracks": 0, "fp_tracks": 0, "unlabelled_tracks": len(tracks),
            "label_recall": 0.0, "obj_recall": 0.0, "precision": 0.0,
        }

    raw = [json.loads(line) for line in labels_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    labels = [l for l in raw if not l.get("uncertain")]
    uncertain = [l for l in raw if l.get("uncertain")]
    pos_labels = [l for l in labels if not l.get("not_ability")]
    neg_labels = [l for l in labels if l.get("not_ability")]

    pos_objs = collapse_objects(pos_labels)

    # 1. Positive Label Recall (spatial)
    recalled_labels = []
    unrecalled_labels = []
    for l in pos_labels:
        lx, ly = l["x"], l["y"]
        matched_tr = [t for t in tracks if np.hypot(t["x"] - lx, t["y"] - ly) <= match_radius_px]
        if matched_tr:
            recalled_labels.append(l)
        else:
            unrecalled_labels.append(l)

    # 2. Positive Object Recall (spatial)
    recalled_objs = []
    unrecalled_objs = []
    for o in pos_objs:
        ox, oy = o["mean_x"], o["mean_y"]
        matched_tr = [t for t in tracks if np.hypot(t["x"] - ox, t["y"] - oy) <= match_radius_px]
        if matched_tr:
            recalled_objs.append(o)
        else:
            unrecalled_objs.append(o)

    # 3. Track Classification
    # A track is TP if closest label within match_radius is positive.
    # A track is FP if closest label within match_radius is negative (false discovery).
    # A track is Unlabelled if no label exists within match_radius.
    classified_tracks = []
    tp_count = 0
    fp_count = 0
    unlabelled_count = 0

    for t in tracks:
        tx, ty = t["x"], t["y"]
        d_pos = min([np.hypot(l["x"] - tx, l["y"] - ty) for l in pos_labels], default=float("inf"))
        d_neg = min([np.hypot(l["x"] - tx, l["y"] - ty) for l in neg_labels], default=float("inf"))

        classification = "unlabelled"
        closest_label = None
        if d_pos <= match_radius_px and d_pos <= d_neg:
            classification = "TP"
            tp_count += 1
            # Find the closest positive label
            closest_label = min(pos_labels, key=lambda l: np.hypot(l["x"] - tx, l["y"] - ty))
        elif d_neg <= match_radius_px and d_neg < d_pos:
            classification = "FP"
            fp_count += 1
            closest_label = min(neg_labels, key=lambda l: np.hypot(l["x"] - tx, l["y"] - ty))
        else:
            unlabelled_count += 1

        # Also check spatio-temporal label match
        t_s_min = t["t_first"] - match_dt
        t_s_max = t["t_last"] + match_dt
        temporal_pos = [
            l for l in pos_labels
            if np.hypot(l["x"] - tx, l["y"] - ty) <= match_radius_px
            and (t_s_min <= l["t_ms"] / 1000.0 <= t_s_max)
        ]

        classified_tracks.append({
            "track": {
                "x": t["x"], "y": t["y"],
                "t_first": t["t_first"], "t_last": t["t_last"],
                "span": t["span"], "n_obs": t["n_obs"],
                "mean_response": t["mean_response"],
            },
            "classification": classification,
            "dist_to_closest_pos": round(d_pos, 1) if d_pos < float("inf") else None,
            "dist_to_closest_neg": round(d_neg, 1) if d_neg < float("inf") else None,
            "closest_label": closest_label,
            "spatiotemporal_pos_matches": len(temporal_pos),
        })

    label_rec = len(recalled_labels) / len(pos_labels) if pos_labels else 0.0
    obj_rec = len(recalled_objs) / len(pos_objs) if pos_objs else 0.0
    prec = tp_count / (tp_count + fp_count) if (tp_count + fp_count) > 0 else 0.0

    return {
        "n_pos_labels": len(pos_labels),
        "n_neg_labels": len(neg_labels),
        "n_uncertain_labels": len(uncertain),
        "n_pos_objects": len(pos_objs),
        "recalled_pos_labels": len(recalled_labels),
        "recalled_pos_objects": len(recalled_objs),
        "tp_tracks": tp_count,
        "fp_tracks": fp_count,
        "unlabelled_tracks": unlabelled_count,
        "label_recall": round(label_rec, 4),
        "object_recall": round(obj_rec, 4),
        "precision": round(prec, 4),
        "classified_tracks": classified_tracks,
        "recalled_objects": recalled_objs,
        "unrecalled_objects": unrecalled_objs,
    }


def run_benchmark(
    session_id: str = DEFAULT_SESSION,
    store_root: Path = DEFAULT_STORE,
    step_s: float = 0.5,
    bh_min: int = BH_MIN,
    dist_tol_px: float = 18.0,
    match_radius_px: float = 10.0,
) -> dict:
    """Run the cold temporal ability benchmark for a spectator session."""
    store = Store(store_root)
    man_path = store.manifest_path(session_id)
    if not man_path.is_file():
        raise FileNotFoundError(f"Manifest not found for session: {session_id}")

    man = store.read_manifest(session_id)
    src = man["source"]
    fps = float(src["fps"])
    video_path = src["path"]
    profile = get_profile(man["source_profile"])

    mroi = next((r for r in profile.rois if r.name == "minimap"), None)
    if not mroi:
        raise ValueError(f"Profile {profile.name} has no minimap ROI")
    roi_px = mroi.pixels(src["width"], src["height"])

    static = geometry.reference_static(session_id, store_root)
    mask = slab_mask(static)

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video source: {video_path}")

    # Compute static map peaks to prevent terrain false positives
    static_gray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY)
    static_discs = detect_ability_discs(static_gray, mask, k=BH_K, bh_min=80)
    static_peaks = [(d["cx"], d["cy"], d["response"]) for d in static_discs]

    dur_s = float(src["duration_ms"]) / 1000.0

    tracks = extract_persistent_tracks(
        cap, fps, dur_s, roi_px, mask, static_peaks,
        step_s=step_s, bh_min=bh_min, dist_tol_px=dist_tol_px,
    )
    cap.release()

    labels_path = store_root / "labels" / "ability" / f"{session_id}.jsonl"
    eval_res = score_tracks_against_labels(tracks, labels_path, match_radius_px=match_radius_px)

    return {
        "benchmark": BENCHMARK_VERSION,
        "session_id": session_id,
        "profile": profile.name,
        "duration_s": dur_s,
        "tracks": tracks,
        "evaluation": eval_res,
    }


def run_batch(
    sessions: list[str] | None = None,
    store_root: Path = DEFAULT_STORE,
) -> list[dict]:
    """Run benchmark across target spectator sessions."""
    target_sessions = sessions or TARGET_SPECTATOR_SESSIONS
    all_results = []

    print(f"\n=======================================================")
    print(f"Running Cold Ability Tracking Benchmark Batch ({len(target_sessions)} sessions)")
    print(f"=======================================================\n")
    print(f"{'Session':<14s} {'Tracks':<8s} {'TP':<5s} {'FP':<5s} {'Unlab':<7s} {'Obj Rec':<9s} {'Label Rec':<11s} {'Precision':<10s}")
    print(f"{'-'*14} {'-'*8} {'-'*5} {'-'*5} {'-'*7} {'-'*9} {'-'*11} {'-'*10}")

    for sid in target_sessions:
        res = run_benchmark(sid, store_root)
        all_results.append(res)
        ev = res["evaluation"]
        n_tr = len(res["tracks"])
        tp = ev["tp_tracks"]
        fp = ev["fp_tracks"]
        unlab = ev["unlabelled_tracks"]
        obj_r = f"{ev['object_recall']*100:5.1f}%"
        lbl_r = f"{ev['label_recall']*100:5.1f}%"
        prec = f"{ev['precision']*100:5.1f}%" if (tp + fp) > 0 else "N/A"
        print(f"{sid:<14s} {n_tr:<8d} {tp:<5d} {fp:<5d} {unlab:<7d} {obj_r:<9s} {lbl_r:<11s} {prec:<10s}")

    total_tracks = sum(len(r["tracks"]) for r in all_results)
    total_tp = sum(r["evaluation"]["tp_tracks"] for r in all_results)
    total_fp = sum(r["evaluation"]["fp_tracks"] for r in all_results)
    total_unlab = sum(r["evaluation"]["unlabelled_tracks"] for r in all_results)
    total_pos_lbls = sum(r["evaluation"]["n_pos_labels"] for r in all_results)
    total_rec_lbls = sum(r["evaluation"]["recalled_pos_labels"] for r in all_results)
    total_pos_objs = sum(r["evaluation"]["n_pos_objects"] for r in all_results)
    total_rec_objs = sum(r["evaluation"]["recalled_pos_objects"] for r in all_results)

    pooled_lbl_rec = total_rec_lbls / total_pos_lbls if total_pos_lbls > 0 else 0.0
    pooled_obj_rec = total_rec_objs / total_pos_objs if total_pos_objs > 0 else 0.0
    pooled_prec = total_tp / (total_tp + total_fp) if (total_tp + total_fp) > 0 else 0.0

    print(f"{'-'*75}")
    print(f"{'POOLED':<14s} {total_tracks:<8d} {total_tp:<5d} {total_fp:<5d} {total_unlab:<7d} {pooled_obj_rec*100:5.1f}%   {pooled_lbl_rec*100:5.1f}%     {pooled_prec*100:5.1f}%")
    print(f"\nPooled Objects Recalled: {total_rec_objs}/{total_pos_objs} ({pooled_obj_rec*100:.1f}%)")
    print(f"Pooled Labels Recalled:  {total_rec_lbls}/{total_pos_lbls} ({pooled_lbl_rec*100:.1f}%)")
    print(f"Pooled Precision:        {total_tp}/{total_tp + total_fp} ({pooled_prec*100:.1f}%)\n")
    return all_results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=DEFAULT_SESSION,
                        help=f"session ID to benchmark (default: {DEFAULT_SESSION})")
    parser.add_argument("--batch", action="store_true",
                        help="run benchmark across all target spectator sessions")
    parser.add_argument("--store", default=str(DEFAULT_STORE),
                        help="path to reticle-store root")
    parser.add_argument("--out", help="optional output directory to write results")
    args = parser.parse_args(argv)

    store_root = Path(args.store)
    if args.batch:
        results = run_batch(store_root=store_root)
        if args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / "cold_batch_benchmark_result.json"
            out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"Wrote batch benchmark results to {out_path}")
        return 0

    res = run_benchmark(args.session, store_root=store_root)
    ev = res["evaluation"]

    print(f"\n--- Cold Ability Benchmark: {args.session} ({res['profile']}) ---")
    print(f"Persistent tracks found: {len(res['tracks'])}")
    print(f"Ground-truth positive labels:  {ev['n_pos_labels']}")
    print(f"Ground-truth negative labels:  {ev['n_neg_labels']}")
    print(f"Ground-truth positive objects: {ev['n_pos_objects']}")
    print(f"Recalled positive labels:      {ev['recalled_pos_labels']} ({ev['label_recall']*100:.1f}%)")
    print(f"Recalled positive objects:     {ev['recalled_pos_objects']} ({ev['object_recall']*100:.1f}%)")
    print(f"Tracks classified as TP:       {ev['tp_tracks']}")
    print(f"Tracks classified as FP:       {ev['fp_tracks']}")
    print(f"Tracks unlabelled:             {ev['unlabelled_tracks']}")
    prec_str = f"{ev['precision']*100:.1f}%" if (ev['tp_tracks'] + ev['fp_tracks']) > 0 else "N/A"
    print(f"Precision against labels:      {prec_str}\n")

    print("Persistent Tracks Detail:")
    for i, tinfo in enumerate(ev["classified_tracks"], 1):
        tr = tinfo["track"]
        cls = tinfo["classification"]
        d_p = tinfo["dist_to_closest_pos"]
        d_n = tinfo["dist_to_closest_neg"]
        print(f"  Track #{i}: ({tr['x']}, {tr['y']}) t=[{tr['t_first']}s, {tr['t_last']}s] span={tr['span']}s n_obs={tr['n_obs']} -> {cls} (d_pos={d_p}, d_neg={d_n})")

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"cold_benchmark_{args.session}.json"
        out_path.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"\nWrote benchmark results to {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
