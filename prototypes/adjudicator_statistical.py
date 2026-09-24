r"""Evaluate candidate formulations of the statistical adjudicator on grouping labels.

    .\.venv\Scripts\python.exe prototypes\adjudicator_statistical.py

Tests whether plausible measurement error (self icon position uncertainty +-2 px,
facing uncertainty +-10 deg, bimodal lobe choice, and 1-px wall edge uncertainty)
explains marginal observations (such as cone slivers) without falsely classifying
true ability entities.
"""
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import cone, geometry, lighting, metrics, minimap, profiles  # noqa: E402
from reticle.adjudication.ability import _components, _labels  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

STORE = Path(DEFAULT_STORE)
ABILITY = {"same_entity", "other_ability"}


def answers() -> dict[tuple, dict]:
    """Last row per key wins, as the labeller writes them."""
    out = {}
    for path in sorted((STORE / "labels" / "ability_grouping").glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[(row["review_id"], row.get("component_id") or "")] = row
    return out


def group(r: dict) -> str:
    ans = r.get("answer")
    if ans in ABILITY:
        return "ability"
    if ans == "viewcone_fragment":
        return "viewcone"
    return "other"


def main() -> int:
    comps = {c["component_id"]: c for c in _components(STORE, _labels(STORE))}
    rows = [r for r in answers().values()
            if r.get("component_id") in comps and r.get("t_ms") is not None
            and not r.get("unsure")]

    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session_id"]].append(r)

    results = []

    # 1-px wall relaxation structuring element
    k1 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    for sid, rs in sorted(by_session.items()):
        geo_p = geometry.path_of(sid, STORE)
        if not geo_p or not geo_p.is_file():
            print(f"{sid}: no geometry -- skipped")
            continue
        with np.load(geo_p) as z:
            labels = z["labels"]
            floor = (labels == minimap.FLOOR) | (labels == minimap.PLANT)
            ref = lighting.reference(z)
        if ref is None:
            print(f"{sid}: geometry has no lighting reference -- skipped")
            continue

        passable = cone.passable_from(labels, floor)
        passable_relaxed = cv2.dilate(passable.astype(np.uint8), k1).astype(bool)

        # Load series for self icon tracking
        series_p = STORE / "series" / f"{sid}.npz"
        series = np.load(series_p) if series_p.is_file() else None

        # Load stored ability_light events if available
        ev_p = STORE / "events" / "ability_light" / f"{sid}.jsonl"
        events = {}
        if ev_p.is_file():
            for l in ev_p.read_text(encoding="utf-8").splitlines():
                if l.strip():
                    item = json.loads(l)
                    if item.get("kind") == "frame":
                        events[float(item["t_ms"])] = item

        for r in rs:
            t = float(r["t_ms"])
            cid = r["component_id"]
            c = comps[cid]
            bx, by, bw, bh = c.get("box") or [int(r["x"]) - 6, int(r["y"]) - 6, 12, 12]
            win = (slice(max(0, by), by + bh), slice(max(0, bx), bx + bw))
            known = ref.known[win]

            if not known.any():
                results.append({**r, "status": "box_off_known_floor"})
                continue

            # Decode crop for accurate intensity inspection and dark drop check
            man = geometry.manifest(sid, STORE)
            src = man["source"]
            x0, y0, x1, y1 = minimap.minimap_roi_px(
                profiles.get_profile(man["source_profile"]),
                int(src["width"]), int(src["height"]))
            cap = cv2.VideoCapture(src["path"])
            cap.set(cv2.CAP_PROP_POS_MSEC, t)
            ok, frame = cap.read()
            cap.release()
            if not ok:
                results.append({**r, "status": "unreadable_frame"})
                continue
            crop = frame[y0:y1, x0:x1]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            raw = lighting.raw_lit(crop, ref)

            # An illuminated cone pixel is brighter than unlit floor; an ability object has dark pixels
            dark_drop = float((ref.lo[win][known] - gray[win][known]).max())
            is_dark_object = dark_drop >= 15.0

            clean = lighting.clean_lit(raw, ref)
            raw_share = float(raw[win][known].mean())
            clean_share = float(clean[win][known].mean())

            # Formulation A: Baseline Hard Adjudicator
            form_a = clean_share >= 0.60

            # Get self icon estimate
            sx, sy, sd = None, None, None
            if series is not None:
                t_ms_arr = series["t_ms"]
                idx = int(np.argmin(np.abs(t_ms_arr - t)))
                if np.abs(t_ms_arr[idx] - t) <= 100:
                    sx = float(series["self_x"][0, idx])
                    sy = float(series["self_y"][0, idx])
                    sd = float(series["self_d"][0, idx])

            form_b = form_a
            form_c = form_a
            form_d = form_a

            best_cone_cov_c = 0.0
            best_cone_cov_d = 0.0

            if not is_dark_object and sx is not None and sy is not None and sd is not None and not np.isnan(sd):
                lobes = [sd, (sd + 180.0) % 360.0]

                # Formulation B: Track-Informed Lobe Selection + Raw Lit Support
                for lobe in lobes:
                    cmask = cone.raycast(passable, sx, sy, lobe)
                    cov = float(cmask[win].mean())
                    if cov >= 0.15 and raw_share >= 0.35:
                        form_b = True

                # Formulation C: Plausible Measurement Error Budget
                for lobe in lobes:
                    for dx in (-2.0, 0.0, 2.0):
                        for dy in (-2.0, 0.0, 2.0):
                            for d_deg in (-10.0, 0.0, 10.0):
                                cmask = cone.raycast(passable, sx + dx, sy + dy, (lobe + d_deg) % 360.0)
                                cov = float(cmask[win].mean())
                                if cov > best_cone_cov_c:
                                    best_cone_cov_c = cov
                                if cov >= 0.20 and raw_share >= 0.35:
                                    form_c = True

                # Formulation D: Joint Geometry Edge Uncertainty (1px wall edge relaxation)
                for lobe in lobes:
                    for dx in (-2.0, 0.0, 2.0):
                        for dy in (-2.0, 0.0, 2.0):
                            for d_deg in (-10.0, 0.0, 10.0):
                                cmask = cone.raycast(passable_relaxed, sx + dx, sy + dy, (lobe + d_deg) % 360.0)
                                cov = float(cmask[win].mean())
                                if cov > best_cone_cov_d:
                                    best_cone_cov_d = cov
                                if cov >= 0.20 and raw_share >= 0.35:
                                    form_d = True

            results.append({
                **r,
                "raw_share": raw_share,
                "clean_share": clean_share,
                "form_a": form_a,
                "form_b": form_b,
                "form_c": form_c,
                "form_d": form_d,
                "best_cov_c": best_cone_cov_c,
                "best_cov_d": best_cone_cov_d,
            })

    # Summary report
    by_grp = defaultdict(list)
    for r in results:
        by_grp[group(r)].append(r)

    print("\n=== Statistical Adjudicator Formulations Evaluation ===\n")
    print(f"{'Group':12s} {'Total':5s} | {'Form A (Baseline)':18s} | {'Form B (Lobe/Raw)':18s} | {'Form C (Meas Error)':18s} | {'Form D (Wall Relax)':18s}")
    print("-" * 105)
    for g in ("viewcone", "ability", "other"):
        items = by_grp[g]
        nA = sum(1 for r in items if r.get("form_a"))
        nB = sum(1 for r in items if r.get("form_b"))
        nC = sum(1 for r in items if r.get("form_c"))
        nD = sum(1 for r in items if r.get("form_d"))
        tot = len(items)
        print(f"{g:12s} {tot:5d} | {nA:3d}/{tot:2d} ({nA/tot*100:5.1f}%)    | {nB:3d}/{tot:2d} ({nB/tot*100:5.1f}%)    | {nC:3d}/{tot:2d} ({nC/tot*100:5.1f}%)    | {nD:3d}/{tot:2d} ({nD/tot*100:5.1f}%)")

    print("\n--- Detailed Status on the Three Sliver Cases in e78e75b2d191 ---")
    for r in results:
        if r.get("session_id") == "e78e75b2d191" and r.get("t_ms") in (36900.0, 40650.0, 43350.0):
            t_s = r["t_ms"] / 1000.0
            print(f"  t={t_s:4.1f}s ({r['x']},{r['y']}) raw_lit={r['raw_share']:.2f} clean_lit={r['clean_share']:.2f} | "
                  f"Form A: {r['form_a']} | Form B: {r['form_b']} | Form C: {r['form_c']} (cov={r['best_cov_c']:.2f}) | "
                  f"Form D: {r['form_d']} (cov={r['best_cov_d']:.2f})")

    # Record metrics
    metrics.record("adjudicator_statistical", part="grouping-labels", session="all-labelled",
                   values={
                       "viewcone_n": len(by_grp["viewcone"]),
                       "viewcone_form_a": sum(1 for r in by_grp["viewcone"] if r.get("form_a")),
                       "viewcone_form_b": sum(1 for r in by_grp["viewcone"] if r.get("form_b")),
                       "viewcone_form_c": sum(1 for r in by_grp["viewcone"] if r.get("form_c")),
                       "viewcone_form_d": sum(1 for r in by_grp["viewcone"] if r.get("form_d")),
                       "ability_n": len(by_grp["ability"]),
                       "ability_false_refusal_form_a": sum(1 for r in by_grp["ability"] if r.get("form_a")),
                       "ability_false_refusal_form_b": sum(1 for r in by_grp["ability"] if r.get("form_b")),
                       "ability_false_refusal_form_c": sum(1 for r in by_grp["ability"] if r.get("form_c")),
                       "ability_false_refusal_form_d": sum(1 for r in by_grp["ability"] if r.get("form_d")),
                   },
                   deps={"formulation": "adjudicator-statistical-0.2.0",
                         "lighting": lighting.LIGHTING_VERSION,
                         "cone": cone.CONE_HALF_ANGLE_DEG,
                         "labels": "labels/ability_grouping last row per key, unsure excluded"},
                   context={"tested_formulations": ["form_a", "form_b", "form_c", "form_d"]})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
