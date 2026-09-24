"""Deterministic glyph and appearance classification benchmark across ability archetypes.

Evaluates recognition and contrast across:
1. Circular Smokes: Omen Dark Cover, Clove Ruse, Jett Cloudburst, Viper Poison Cloud;
2. Circular Deployables: Killjoy Alarmbot, Killjoy Nanoswarm, Cypher Spycam;
3. Linear Walls: Phoenix Blaze, Viper Toxic Screen, Neon Fast Lane.

Usage:
    .\\.venv\\Scripts\\python.exe tools/ability_glyph_benchmark.py [--store PATH] [--out FILE] [--integrate]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

# Ensure reticle is on path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle.adjudication.gallery import (
    classify_ability_glyph,
    extract_glyph_features,
    integrate_crop_gallery,
    load_harvested_gallery,
)
from reticle.store import DEFAULT_STORE

BENCHMARK_VERSION = "ability-glyph-benchmark-0.1.0"


def format_confusion_matrix(classes: list[str],
                            matrix: dict[str, dict[str, int]]) -> str:
    """Format a 2D confusion matrix into a readable ASCII table."""
    col_w = max(10, max(len(c.split(":")[-1]) for c in classes) + 2)
    header = f"{'True \\ Pred':<22s} " + "".join(
        f"{c.split(':')[-1]:>{col_w}s}" for c in classes
    )
    lines = [header, "-" * len(header)]
    for r in classes:
        short_r = r.split(":")[-1]
        row_str = f"{short_r:<22s} " + "".join(
            f"{matrix[r].get(c, 0):>{col_w}d}" for c in classes
        )
        lines.append(row_str)
    return "\n".join(lines)


def run_benchmark(store_root: Path | str = DEFAULT_STORE) -> dict:
    """Execute glyph benchmark across all harvested and verified ability crops."""
    store_root = Path(store_root)
    crops = load_harvested_gallery(store_root)
    if not crops:
        raise RuntimeError(
            f"No ability crops found under {store_root / 'analysis' / 'ability-harvest'}"
        )

    by_archetype: dict[str, list[dict]] = defaultdict(list)
    for c in crops:
        by_archetype[c["archetype"]].append(c)

    results = {
        "benchmark": BENCHMARK_VERSION,
        "store_root": str(store_root),
        "total_crops": len(crops),
        "archetypes": {},
    }

    archetype_order = ["smoke", "deployable", "wall"]

    print("=========================================================================")
    print("           RETICLE ABILITY GLYPH & APPEARANCE BENCHMARK                  ")
    print(f"  Evaluating {len(crops)} crops across circular and linear ability archetypes")
    print("=========================================================================\n")

    overall_correct = 0
    overall_total = 0

    for arch in archetype_order:
        items = by_archetype.get(arch, [])
        if not items:
            continue

        classes = sorted({c["ability_id"] for c in items})
        confusion: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        arch_results = []
        correct = 0

        title = f"ARCHETYPE: {arch.upper()}S ({len(items)} samples, {len(classes)} classes)"
        print(title)
        print("-" * len(title))
        col_hdr = f"{'Filename':<38s} {'Ground Truth':<22s} {'Predicted':<22s} {'Conf':<6s} {'Status':<6s}"
        print(col_hdr)
        print("-" * len(col_hdr))

        for item in items:
            p = Path(item["path"])
            im = cv2.imread(str(p))
            res = classify_ability_glyph(im, archetype=arch)
            pred_id = res["ability_id"]
            true_id = item["ability_id"]
            conf = res["confidence"]
            match = pred_id == true_id
            correct += int(match)
            confusion[true_id][pred_id] += 1

            status = "PASS" if match else "FAIL"
            print(f"{p.name:<38s} {true_id:<22s} {pred_id:<22s} {conf:<6.2f} {status:<6s}")

            arch_results.append({
                "filename": p.name,
                "ground_truth": true_id,
                "predicted": pred_id,
                "confidence": conf,
                "correct": match,
                "features": res["features"],
                "scores": res["scores"],
            })

        acc = correct / len(items) if items else 0.0
        overall_correct += correct
        overall_total += len(items)

        print(f"\n{arch.capitalize()} Accuracy: {correct}/{len(items)} ({acc * 100:.1f}%)")
        print("\nConfusion Matrix:")
        c_mat_str = format_confusion_matrix(classes, confusion)
        print(c_mat_str)
        print("\n" + "=" * 73 + "\n")

        results["archetypes"][arch] = {
            "total": len(items),
            "correct": correct,
            "accuracy": round(acc, 4),
            "classes": classes,
            "confusion_matrix": {r: dict(confusion[r]) for r in classes},
            "evaluations": arch_results,
        }

    total_acc = overall_correct / overall_total if overall_total else 0.0
    results["summary"] = {
        "overall_total": overall_total,
        "overall_correct": overall_correct,
        "overall_accuracy": round(total_acc, 4),
    }

    print(f"OVERALL BENCHMARK ACCURACY: {overall_correct}/{overall_total} ({total_acc * 100:.1f}%)")
    print("=========================================================================\n")
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store", default=str(DEFAULT_STORE),
                        help=f"path to reticle-store root (default: {DEFAULT_STORE})")
    parser.add_argument("--out", help="optional output path to write JSON benchmark results")
    parser.add_argument("--integrate", action="store_true",
                        help="integrate crops into reference assets gallery directory")
    args = parser.parse_args(argv)

    store_root = Path(args.store)
    if args.integrate:
        manifest = integrate_crop_gallery(store_root)
        print(f"Integrated {manifest['total_crops']} crops into {store_root / 'reference' / 'assets' / 'ability_gallery'}")

    res = run_benchmark(store_root)

    if args.out:
        out_p = Path(args.out)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(res, indent=2), encoding="utf-8")
        print(f"Wrote benchmark results to {out_p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
