"""Verifiable first-person POV ability benchmark.

Evaluates circular ability identification (e.g. Omen Dark Cover, Killjoy Alarmbot,
Jett Cloudburst, Viper Poison Cloud, Clove Ruse) by corroborating HUD ability
tray charge drops against minimap disc appearances.
Cites [domain:abilities/omen-dark-cover], [domain:abilities/omen-tray-charges],
[domain:abilities/killjoy-alarmbot], [domain:abilities/killjoy-tray-charges],
[domain:abilities/jett-cloudburst], [domain:abilities/jett-tray-charges],
[domain:abilities/viper-poison-cloud], [domain:abilities/viper-tray-charges],
[domain:abilities/clove-rouse], and [domain:abilities/clove-tray-charges].

Usage:
    .\\.venv\\Scripts\\python.exe tools/ability_pov_benchmark.py [--session SID] [--store PATH] [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

# Ensure reticle and prototypes are on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "prototypes"))

from reticle import geometry
from reticle.minimap import slab_mask, self_icons, detect_ability_discs
from reticle.profiles import get_profile
from reticle.store import DEFAULT_STORE, Store
import ability_hud

BENCHMARK_VERSION = "ability-pov-benchmark-0.1.0"
DEFAULT_SESSION = "b9558488a607"


def detect_born_discs(cap, fps: float, roi_px: tuple[int, int, int, int],
                      mask: np.ndarray, static_peaks: list[tuple],
                      t_start_s: float, t_end_s: float,
                      step_s: float = 0.5, bh_min: int = 120,
                      dist_tol_px: float = 18.0) -> list[dict]:
    """Find discs that are BORN in [t_start_s, t_end_s], not present in pre-frame,
    and not belonging to static map geometry or the player's self icon."""
    px0, py0, px1, py1 = roi_px
    t_pre = max(0.0, t_start_s - 1.0)
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(t_pre * fps))
    ok, frame = cap.read()
    pre_discs = []
    if ok:
        crop = frame[py0:py1, px0:px1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        pre_discs = detect_ability_discs(gray, mask, k=27, bh_min=bh_min)

    born_candidates = []
    t = t_start_s
    while t <= t_end_s:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
        ok, frame = cap.read()
        if not ok:
            break
        crop = frame[py0:py1, px0:px1]
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        s_icons = self_icons(crop, mask)
        self_xy = (s_icons[0]["cx"], s_icons[0]["cy"]) if s_icons else None

        discs = detect_ability_discs(gray, mask, static_peaks=static_peaks,
                                     self_xy=self_xy, k=27, bh_min=bh_min,
                                     dist_tol_px=dist_tol_px)

        for d in discs:
            px_val, py_val, resp = d["cx"], d["cy"], d["response"]
            # Check if this peak was already present in pre-frame
            is_old = any(np.hypot(px_val - float(bp["cx"]), py_val - float(bp["cy"])) < dist_tol_px
                         for bp in pre_discs)
            if not is_old:
                is_recorded = any(np.hypot(px_val - c["x"], py_val - c["y"]) < dist_tol_px
                                  for c in born_candidates)
                if not is_recorded:
                    born_candidates.append({
                        "t_born_s": round(t, 2),
                        "x": round(px_val, 1),
                        "y": round(py_val, 1),
                        "response": round(resp, 1)
                    })
        t += step_s

    return born_candidates



def run_benchmark(session_id: str = DEFAULT_SESSION, store_root: Path = DEFAULT_STORE) -> dict:
    """Run the verifiable POV ability benchmark for the session."""
    store = Store(store_root)
    man_path = store_root / "manifests" / f"{session_id}.json"
    if not man_path.is_file():
        raise FileNotFoundError(f"Manifest not found for session: {session_id}")

    man = json.loads(man_path.read_text(encoding="utf-8"))
    src = man["source"]
    fps = float(src["fps"])
    video_path = src["path"]
    profile = get_profile(man["source_profile"])

    mroi = next((r for r in profile.rois if r.name == "minimap"), None)
    if not mroi:
        raise ValueError(f"Profile {profile.name} has no minimap ROI")
    roi_px = mroi.pixels(src["width"], src["height"])

    # Load baked static geometry and slab mask [domain:minimap/transparency]
    static = geometry.reference_static(session_id, store_root)
    mask = slab_mask(static)

    # 1. Read ability tray charge drops [domain:abilities/omen-tray-charges]
    cast_cache = store_root / "casts" / f"{session_id}.step0.5.84229831.json"
    if cast_cache.is_file():
        raw_casts = json.loads(cast_cache.read_text(encoding="utf-8"))
        # (t, slot, from_fill, to_fill, suspect)
        tray_casts = [
            {"t_s": r[0], "slot": r[1], "from": r[2], "to": r[3], "suspect": r[4]}
            for r in raw_casts if not r[4] and (r[2] - r[3] >= ability_hud.CAST_DROP)
        ]
    else:
        ts, counts, clean = ability_hud.scan(session_id)
        raw_casts = ability_hud.casts(ts, counts, clean)
        tray_casts = [
            {"t_s": r[0], "slot": r[1], "from": r[2], "to": r[3], "suspect": r[4]}
            for r in raw_casts if not r[4]
        ]

    tags = man.get("tags") or []
    agent = next((t for t in tags if t in ["omen", "killjoy", "brimstone", "clove", "cypher", "viper", "jett"]), "omen")

    # Route agent to circular ability slot
    # Omen: E, Killjoy: Q, Brimstone: E, Clove: E, Jett: C (Cloudburst), Viper: Q (Poison Cloud)
    agent_slot_map = {
        "omen": ("E", "omen:dark cover"),
        "killjoy": ("Q", "killjoy:alarmbot"),
        "brimstone": ("E", "brimstone:sky smoke"),
        "clove": ("E", "clove:ruse"),
        "jett": ("C", "jett:cloudburst"),
        "viper": ("Q", "viper:poison cloud"),
    }
    target_slot, ability_name = agent_slot_map.get(agent, ("E", f"{agent}:disc"))
    smoke_casts = [c for c in tray_casts if c["slot"] == target_slot]

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video source: {video_path}")

    # Compute baseline static map peaks to prevent terrain false positives
    static_gray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY)
    static_discs = detect_ability_discs(static_gray, mask, k=27, bh_min=80)
    static_peaks = [(d["cx"], d["cy"], d["response"]) for d in static_discs]

    # 2. Corroborate each cast on minimap within [t_cast, t_cast + 3.5s]
    # [domain:abilities/omen-dark-cover]
    # [domain:abilities/killjoy-alarmbot]
    corroborated_casts = []
    unmatched_casts = []
    harvest_dir = store_root / "analysis" / "ability-harvest"
    harvest_dir.mkdir(parents=True, exist_ok=True)

    for c in smoke_casts:
        t_cast = c["t_s"]
        born = detect_born_discs(cap, fps, roi_px, mask, static_peaks, t_cast, t_cast + 3.5, step_s=0.5)
        if born:
            disc_info = born[0]
            c_copy = dict(c)
            c_copy["minimap_disc"] = disc_info
            c_copy["delay_s"] = round(disc_info["t_born_s"] - t_cast, 2)

            # Harvest visual appearance patch around disc center
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(disc_info["t_born_s"] * fps))
            ok_f, frame = cap.read()
            if ok_f:
                px0, py0, px1, py1 = roi_px
                crop = frame[py0:py1, px0:px1]
                cx, cy = int(round(disc_info["x"])), int(round(disc_info["y"]))
                r_crop = 16
                y_a, y_b = max(0, cy - r_crop), min(crop.shape[0], cy + r_crop)
                x_a, x_b = max(0, cx - r_crop), min(crop.shape[1], cx + r_crop)
                patch = crop[y_a:y_b, x_a:x_b]

                patch_name = f"{session_id}_{int(disc_info['t_born_s']*1000)}_{agent}_{c['slot']}.png"
                patch_path = harvest_dir / patch_name
                cv2.imwrite(str(patch_path), patch)
                c_copy["harvest_patch"] = patch_name

            corroborated_casts.append(c_copy)
        else:
            unmatched_casts.append(c)

    # 3. Negative control check: find earliest cast across all slots to pick clean pre-cast window
    earliest_cast_s = min([c["t_s"] for c in tray_casts], default=15.0)
    neg_start = max(3.0, earliest_cast_s - 4.0)
    neg_end = max(neg_start + 1.0, earliest_cast_s - 1.0)

    spurious_discs = detect_born_discs(cap, fps, roi_px, mask, static_peaks, neg_start, neg_end, step_s=0.5)
    cap.release()

    total_expected = len(smoke_casts)
    matched = len(corroborated_casts)
    recall = matched / total_expected if total_expected > 0 else 0.0
    precision = 1.0 if not spurious_discs else 0.0

    return {
        "benchmark": BENCHMARK_VERSION,
        "session_id": session_id,
        "archetype": "disc",
        "ability": ability_name,
        "summary": {
            "total_tray_casts": total_expected,
            "corroborated_minimap_discs": matched,
            "unmatched_tray_casts": len(unmatched_casts),
            "spurious_discs_negative_window": len(spurious_discs),
            "recall": round(recall, 4),
            "precision_on_negative_control": round(precision, 4)
        },
        "corroborated_casts": corroborated_casts,
        "unmatched_casts": unmatched_casts,
        "spurious_discs": spurious_discs,
        "invariant_violations": []
    }


def run_batch(store_root: Path = DEFAULT_STORE) -> list[dict]:
    """Run benchmark across all circular-archetype demo sessions (excluding spectator and infinite-abilities)."""
    # Exclude brimstone (2ba870ccbd50: infinite-abilities) and cypher spectator sessions
    target_sessions = [
        ("b9558488a607", "omen"),
        ("e78e75b2d191", "omen"),
        ("dae6f33f3f48", "killjoy"),
        ("ff19748eea8c", "jett"),
        ("28f53bfddbbe", "clove"),
    ]
    all_results = []
    print(f"\n=======================================================")
    print(f"Running POV Ability Benchmark Batch ({len(target_sessions)} sessions)")
    print(f"=======================================================\n")
    print(f"{'Session':<14s} {'Agent / Ability':<22s} {'Casts':<7s} {'Discs':<7s} {'Recall':<8s} {'Precision':<10s}")
    print(f"{'-'*14} {'-'*22} {'-'*7} {'-'*7} {'-'*8} {'-'*10}")

    for sid, agent in target_sessions:
        res = run_benchmark(sid, store_root)
        s = res["summary"]
        all_results.append(res)
        ability_str = res["ability"]
        print(f"{sid:<14s} {ability_str:<22s} {s['total_tray_casts']:<7d} {s['corroborated_minimap_discs']:<7d} {s['recall']*100:5.1f}%  {s['precision_on_negative_control']*100:5.1f}%")

    total_casts = sum(r["summary"]["total_tray_casts"] for r in all_results)
    total_discs = sum(r["summary"]["corroborated_minimap_discs"] for r in all_results)
    spurious = sum(r["summary"]["spurious_discs_negative_window"] for r in all_results)
    pooled_recall = total_discs / total_casts if total_casts > 0 else 0.0

    print(f"{'-'*72}")
    print(f"{'TOTAL':<14s} {'5 Sessions Pooled':<22s} {total_casts:<7d} {total_discs:<7d} {pooled_recall*100:5.1f}%  {'100.0%' if spurious==0 else '0.0%'}")
    print(f"\nPooled True Positives: {total_discs}/{total_casts} ({pooled_recall*100:.1f}%)")
    print(f"Total Spurious Negatives: {spurious}\n")
    return all_results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", default=DEFAULT_SESSION,
                        help=f"session ID to benchmark (default: {DEFAULT_SESSION})")
    parser.add_argument("--batch", action="store_true",
                        help="run benchmark across all qualified circular demo sessions")
    parser.add_argument("--store", default=str(DEFAULT_STORE),
                        help="path to reticle-store root")
    parser.add_argument("--cold", action="store_true",
                        help="run cold temporal tracking benchmark on spectator sessions (no HUD tray)")
    parser.add_argument("--out", help="optional output directory to write results")
    args = parser.parse_args(argv)

    if args.cold:
        import ability_cold_benchmark
        cold_args = ["--store", args.store]
        if args.batch:
            cold_args.append("--batch")
        else:
            session = args.session if args.session != DEFAULT_SESSION else ability_cold_benchmark.DEFAULT_SESSION
            cold_args.extend(["--session", session])
        if args.out:
            cold_args.extend(["--out", args.out])
        return ability_cold_benchmark.main(cold_args)

    if args.batch:
        results = run_batch(Path(args.store))
        if args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            json_path = out_dir / "batch_benchmark_result.json"
            json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
            print(f"Wrote batch benchmark results to {json_path}")
        return 0

    results = run_benchmark(args.session, Path(args.store))
    summary = results["summary"]

    print(f"\n--- Ability POV Benchmark: {results['ability']} ({args.session}) ---")
    print(f"Tray casts detected:       {summary['total_tray_casts']}")
    print(f"Minimap discs corroborated: {summary['corroborated_minimap_discs']}")
    print(f"Recall:                    {summary['recall'] * 100:.1f}%")
    print(f"Spurious discs (neg ctrl): {summary['spurious_discs_negative_window']}")
    print(f"Precision on neg control:  {summary['precision_on_negative_control'] * 100:.1f}%\n")

    for i, c in enumerate(results["corroborated_casts"], 1):
        d = c["minimap_disc"]
        print(f"  Cast #{i}: t={c['t_s']}s (slot {c['slot']}) -> Disc at ({d['x']}, {d['y']}) born at t={d['t_born_s']}s (+{c['delay_s']}s)")

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        json_path = out_dir / "benchmark_result.json"
        json_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"\nWrote benchmark results to {json_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
