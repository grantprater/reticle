r"""Inspect the luma evidence Step 2 must use when the self ring fit refuses.

    .\.venv\Scripts\python.exe prototypes\minimap_self_appearance.py \
        c40d950031bb --out C:\Users\grant\reticle-store\notes\self-appearance.png

This is the source-inspection half of
``docs/MINIMAP_APPEARANCE_MATCHING.md`` Step 2. It does not classify or change
the shipped reader. It renders accepted ring fits beside refused frames whose
centre is bounded by native-rate fits immediately before and after them. Those
brackets are diagnostic correspondences, not labels or detector accuracy.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.fidelity import FROZEN_WINDOWS, load_windows  # noqa: E402
from reticle.minimap import (FIT_ERR_PX, RUN_PX, floor_mask, minimap_roi_px,
                             pick_self, self_icons, self_mask, slab_mask,
                             widget_drawn, widget_scale)  # noqa: E402
from prototypes.minimap_appearance import (JOINT_RESIDUAL_SCORE_MIN,
                                           MIN_CONTRAST,
                                           RECENT_RESIDUAL_SCORE_MIN,
                                           RecentAppearanceRecovery, describe,
                                           match_near)  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402


def _patch(crop: np.ndarray, x: float, y: float, half: int = 15) -> np.ndarray | None:
    xi, yi = int(round(x)), int(round(y))
    if yi - half < 0 or xi - half < 0:
        return None
    p = crop[yi - half:yi + half, xi - half:xi + half]
    return p.copy() if p.shape[:2] == (2 * half, 2 * half) else None


def _cell(patch: np.ndarray, label: str, colour: tuple[int, int, int]) -> np.ndarray:
    scale, label_h = 5, 22
    view = cv2.resize(patch, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_NEAREST)
    out = np.full((view.shape[0] + label_h, view.shape[1], 3), 18, np.uint8)
    out[:view.shape[0]] = view
    cv2.drawMarker(out, (view.shape[1] // 2, view.shape[0] // 2), colour,
                   cv2.MARKER_CROSS, 13, 1)
    cv2.putText(out, label, (3, view.shape[0] + 15),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, colour, 1, cv2.LINE_AA)
    return out


def _bracketed(rows: list[dict], max_gap_ms: float = 55.0) -> list[dict]:
    """Refusals bounded by close fitted centres on each side."""
    accepted = [i for i, r in enumerate(rows) if r.get("fit") is not None]
    out = []
    for i, row in enumerate(rows):
        if row.get("fit") is not None or not row.get("drawn"):
            continue
        before = next((j for j in reversed(accepted) if j < i), None)
        after = next((j for j in accepted if j > i), None)
        if before is None or after is None:
            continue
        a, b = rows[before], rows[after]
        if row["t_ms"] - a["t_ms"] > max_gap_ms or b["t_ms"] - row["t_ms"] > max_gap_ms:
            continue
        af, bf = a["fit"], b["fit"]
        if np.hypot(af["cx"] - bf["cx"], af["cy"] - bf["cy"]) > 6.0:
            continue
        q = (row["t_ms"] - a["t_ms"]) / (b["t_ms"] - a["t_ms"])
        out.append({**row,
                    "cx": af["cx"] + q * (bf["cx"] - af["cx"]),
                    "cy": af["cy"] + q * (bf["cy"] - af["cy"])})
    return out


def _proposals(crop: np.ndarray, floor: np.ndarray, slab: np.ndarray,
               separation_px: float | None) -> list[dict]:
    """Every permissive current-frame self-key ring fit.

    The shape gate is removed, not lowered: cov_min=0 and inner_max=1 keep the
    fragments `pick_self` refused. These are PROPOSALS -- places the frame
    itself put self-coloured ring evidence -- and not detections.
    """
    return self_icons(crop, floor, cov_min=0.0, inner_max=1.0,
                      require_facing=False, support=slab,
                      separation_px=separation_px)


def _nearest(points, target) -> float | None:
    """Distance from the closest offered point to the bracketed centre."""
    if not points:
        return None
    return float(min(np.hypot(x - target[0], y - target[1])
                     for x, y in points))


def _joint(rows: list[dict], truth: dict[int, tuple[float, float, str]],
           lo: np.ndarray, hi: np.ndarray, floor: np.ndarray, slab: np.ndarray,
           scale: float, *, separation_px: float | None = None,
           locked: bool = False) -> list[dict]:
    """Score appearance only at current-frame proposals, one record per refusal.

    `locked=False` reports every ungated query so a development interval can
    choose the gate; it advances the position prior on ring fits alone, so the
    records do not depend on the gate being selected from them. `locked=True`
    runs the selected rule the way a fed reader would, letting an accepted
    answer carry the prior forward.
    """
    recovery = RecentAppearanceRecovery(lo, hi, slab, scale=scale,
                                        run_px=RUN_PX, fit_error_px=FIT_ERR_PX)
    previous = None
    previous_t = None
    records = []
    for row in rows:
        if not row["drawn"]:
            recovery.unavailable()
            continue
        dt_ms = (1000.0 / 60.0 if previous_t is None
                 else row["t_ms"] - previous_t)
        pick = pick_self(row["fits"], previous, dt_ms, scale)
        mask = self_mask(row["crop"])
        if pick is not None:
            selected = min(row["fits"], key=lambda fit:
                           np.hypot(fit["cx"] - pick[0], fit["cy"] - pick[1]))
            recovery.fitted(row["crop"], mask, selected, row["t_ms"])
            previous, previous_t = pick, row["t_ms"]
            continue
        proposals = _proposals(row["crop"], floor, slab, separation_px)
        admissible = recovery.admissible(proposals, row["t_ms"])
        if locked:
            got = recovery.proposed(row["crop"], mask, proposals, row["t_ms"])
        else:
            got = recovery.query_at(row["crop"], mask, proposals, row["t_ms"])
            recovery.refusal()
        target = truth.get(row["frame_idx"])
        record = {"frame_idx": row["frame_idx"], "t_ms": row["t_ms"],
                  "proposals": len(proposals), "admissible": len(admissible),
                  "opportunity": target is not None,
                  "offered": [(float(p["cx"]), float(p["cy"]))
                              for p in proposals]}
        if target is not None:
            record["ceiling_px"] = _nearest(record["offered"], target)
            record["admissible_ceiling_px"] = _nearest(admissible, target)
        if got is not None:
            record.update({"score": got.score, "margin": got.margin,
                           "contrast": got.contrast, "x": got.x, "y": got.y})
            if target is not None:
                record["error_px"] = float(np.hypot(got.x - target[0],
                                                    got.y - target[1]))
            if locked:
                previous, previous_t = (got.x, got.y), row["t_ms"]
        records.append(record)
    return records


def _joint_report(records: list[dict], label: str) -> dict:
    """Separate what geometry could offer from what appearance then chose."""
    chances = [r for r in records if r["opportunity"]]
    scored = [r for r in chances if "error_px" in r]
    offered = [r for r in chances if r["proposals"]]
    ceiling = [r for r in chances if (r.get("ceiling_px") or 1e9) <= 3.0]
    admitted = [r for r in chances
                if (r.get("admissible_ceiling_px") or 1e9) <= 3.0]
    report = {
        "label": label,
        "refusals": len(records),
        "opportunities": len(chances),
        # Bracketed opportunities are only the MEASURABLE refusals. The share
        # of every refusal this path can answer at all is what bounds the
        # eligible-coverage gain, whether or not truth exists there.
        "refusals_with_anchor": sum(r["admissible"] > 0 for r in records),
        "refusals_answered": sum("score" in r for r in records),
        "with_any_proposal": len(offered),
        "median_proposals": (float(np.median([r["proposals"] for r in chances]))
                             if chances else None),
        "ceiling_within_3px": len(ceiling) / len(chances) if chances else None,
        "admissible_ceiling_within_3px": (len(admitted) / len(chances)
                                          if chances else None),
        "queries": len(scored),
        "ungated_within_3px": (float(np.mean([r["error_px"] <= 3.0
                                              for r in scored]))
                               if scored else None),
        "median_error_px": (float(np.median([r["error_px"] for r in scored]))
                            if scored else None),
        "gates": [],
        "rows": [{k: r[k] for k in
                  ("t_ms", "proposals", "admissible", "ceiling_px",
                   "admissible_ceiling_px", "score", "contrast", "error_px")
                  if k in r} for r in chances],
    }
    reachable = [r["ceiling_px"] for r in chances if r.get("ceiling_px")
                 is not None]
    if reachable:
        report["ceiling_px_quantiles"] = {
            str(q): float(np.quantile(reachable, q))
            for q in (0.25, 0.5, 0.75, 0.9)}
        # A near miss says the fragment is displaced; a far miss says the
        # proposal belongs to a different icon.
        report["ceiling_px_bands"] = {
            "within_3": sum(v <= 3.0 for v in reachable),
            "3_to_6": sum(3.0 < v <= 6.0 for v in reachable),
            "6_to_12": sum(6.0 < v <= 12.0 for v in reachable),
            "beyond_12": sum(v > 12.0 for v in reachable),
        }
    usable = [r for r in scored if r["contrast"] >= MIN_CONTRAST]
    for quantile in (0.0, 0.2, 0.4, 0.6, 0.8):
        if not usable:
            break
        threshold = float(np.quantile([r["score"] for r in usable], quantile))
        keep = [r for r in usable if r["score"] >= threshold]
        report["gates"].append({
            "score_min": threshold,
            "answered": len(keep),
            "answer_fraction_of_opportunities": (len(keep) / len(chances)
                                                 if chances else None),
            "within_3px": (float(np.mean([r["error_px"] <= 3.0 for r in keep]))
                           if keep else None),
        })
    return report


def _joint_cell(crop: np.ndarray, target: tuple[float, float], record: dict,
                label: str) -> np.ndarray | None:
    """One refused frame: the bracketed centre, what was offered, what won."""
    half, scale = 15, 5
    patch = _patch(crop, target[0], target[1], half)
    if patch is None:
        return None
    view = cv2.resize(patch, None, fx=scale, fy=scale,
                      interpolation=cv2.INTER_NEAREST)
    out = np.full((view.shape[0] + 22, view.shape[1], 3), 18, np.uint8)
    out[:view.shape[0]] = view

    def place(x, y):
        return (int(round((x - target[0] + half) * scale + scale // 2)),
                int(round((y - target[1] + half) * scale + scale // 2)))

    for px, py in record["offered"]:
        cv2.circle(out, place(px, py), 7, (200, 200, 60), 1, cv2.LINE_AA)
    cv2.drawMarker(out, place(*target), (80, 180, 255), cv2.MARKER_CROSS, 13, 1)
    if "x" in record:
        cv2.drawMarker(out, place(record["x"], record["y"]), (80, 240, 80),
                       cv2.MARKER_TILTED_CROSS, 11, 1)
    cv2.putText(out, label, (3, view.shape[0] + 15), cv2.FONT_HERSHEY_SIMPLEX,
                0.38, (200, 200, 200), 1, cv2.LINE_AA)
    return out


def _tier_recovery(rows: list[dict], truth: dict[int, tuple[float, float, str]],
                   lo: np.ndarray, hi: np.ndarray, slab: np.ndarray,
                   scale: float) -> dict:
    """Run the locked recovery exactly as a fed production reader would."""
    recovery = RecentAppearanceRecovery(lo, hi, slab, scale=scale,
                                         run_px=RUN_PX,
                                         fit_error_px=FIT_ERR_PX)
    previous = None
    previous_t = None
    opportunities = answers = hits = 0
    errors = []
    scores = []
    for row in rows:
        if not row["drawn"]:
            recovery.unavailable()
            continue
        dt_ms = (1000.0 / 60.0 if previous_t is None
                 else row["t_ms"] - previous_t)
        pick = pick_self(row["fits"], previous, dt_ms, scale)
        mask = self_mask(row["crop"])
        if pick is not None:
            selected = min(row["fits"], key=lambda fit:
                           np.hypot(fit["cx"] - pick[0], fit["cy"] - pick[1]))
            recovery.fitted(row["crop"], mask, selected, row["t_ms"])
            previous, previous_t = pick, row["t_ms"]
            continue
        target = truth.get(row["frame_idx"])
        if target is not None:
            opportunities += 1
        got = recovery.refused(row["crop"], mask, row["t_ms"])
        if got is None:
            continue
        previous, previous_t = (got.x, got.y), row["t_ms"]
        if target is None:
            continue
        answers += 1
        error = float(np.hypot(got.x - target[0], got.y - target[1]))
        errors.append(error)
        scores.append(got.score)
        hits += error <= 3.0
    return {
        "samples": len(rows), "opportunities": opportunities,
        "answered": answers,
        "answer_fraction": answers / opportunities if opportunities else None,
        "within_3px": hits / answers if answers else None,
        "median_error_px": float(np.median(errors)) if errors else None,
        "p95_error_px": float(np.percentile(errors, 95)) if errors else None,
        "score_min_observed": min(scores) if scores else None,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--windows", default=str(FROZEN_WINDOWS))
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep", type=int, default=16)
    ap.add_argument("--from-s", type=float, default=None,
                    help="development interval start in seconds; bypasses frozen windows")
    ap.add_argument("--to-s", type=float, default=None,
                    help="development interval end in seconds")
    ap.add_argument("--evaluate", action="store_true",
                    help="score causal luma matching against fitted/bracket centres")
    ap.add_argument("--tiers", action="store_true",
                    help="also evaluate the locked rule at actual 15/10/5/2 Hz samples")
    ap.add_argument("--joint", action="store_true",
                    help="score appearance only at permissive current-frame ring proposals")
    args = ap.parse_args(argv)

    store = Store(args.store)
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{args.session}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    box = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    med = store.read_static_map(args.session)
    if med is None:
        raise SystemExit("no cached static map; run `reticle minimap` first")
    sd = geometry.stability(args.session, store.root, med.shape[:2])
    floor, slab = floor_mask(med, sd=sd), slab_mask(med, sd=sd)
    sgray = cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64)

    if args.from_s is not None or args.to_s is not None:
        if args.from_s is None or args.to_s is None or args.to_s <= args.from_s:
            raise SystemExit("--from-s and --to-s must name an increasing interval")
        spans = [(args.from_s * 1000.0, args.to_s * 1000.0)]
    else:
        frozen = load_windows(args.windows)
        if frozen["session_id"] != args.session:
            raise SystemExit("window contract and requested session differ")
        spans = [(float(w["t0_ms"]), float(w["t1_ms"])) for w in frozen["windows"]]
    native_name = "native"
    request = {native_name: (float(src["fps"]) * 4.0, spans)}
    if args.tiers:
        request.update({f"{hz:g}hz": (hz, spans) for hz in (15.0, 10.0, 5.0, 2.0)})
    x0, y0, x1, y1 = box
    rows_by_tier = {name: [] for name in request}
    for who, sample in sample_windows(src["path"], float(src["fps"]), request):
        crop = sample.frame[y0:y1, x0:x1]
        drawn = widget_drawn(crop, sgray, floor)
        fits = (self_icons(crop, floor, require_facing=False, support=slab)
                if drawn else [])
        row = {"frame_idx": sample.frame_idx, "t_ms": sample.t_ms,
               "crop": crop.copy(), "drawn": drawn, "fits": fits,
               "fit": max(fits, key=lambda d: d["cov"]) if fits else None}
        for name in who:
            rows_by_tier[name].append(row)

    rows = rows_by_tier[native_name]

    accepted = [r for r in rows if r.get("fit") is not None]
    refused = _bracketed(rows)
    # Spread inspection across time instead of taking one visually redundant run.
    def spread(items):
        if len(items) <= args.keep:
            return items
        return [items[i] for i in np.linspace(0, len(items) - 1, args.keep).astype(int)]

    cells = []
    for row in spread(accepted):
        fit = row["fit"]
        p = _patch(row["crop"], fit["cx"], fit["cy"])
        if p is not None:
            cells.append(_cell(p, f"fit {row['t_ms']/1000:.2f}s", (80, 240, 80)))
    for row in spread(refused):
        p = _patch(row["crop"], row["cx"], row["cy"])
        if p is not None:
            cells.append(_cell(p, f"refuse {row['t_ms']/1000:.2f}s", (80, 180, 255)))
    if not cells:
        raise SystemExit("no inspectable accepted or bracketed-refused crops")
    cols = min(args.keep, 8)
    blank = np.full_like(cells[0], 18)
    cells.extend([blank] * ((-len(cells)) % cols))
    sheet = np.vstack([np.hstack(cells[i:i + cols])
                       for i in range(0, len(cells), cols)])
    target_path = Path(args.out)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(target_path), sheet):
        raise SystemExit(f"could not write {target_path}")
    print(f"frames {len(rows)}; accepted {len(accepted)}; refused {len(rows)-len(accepted)}; "
          f"bracketed refusals {len(refused)}")
    print(target_path)
    truth = {r["frame_idx"]: (r["cx"], r["cy"], "bracket") for r in refused}
    scale = widget_scale(rows[0]["crop"].shape[1])
    if args.evaluate or args.joint:
        with np.load(geometry.require(args.session, store.root)) as z:
            lo, hi = z["lo_gray"].copy(), z["hi_gray"].copy()

    if args.joint:
        report = {"session_id": args.session, "spans_ms": spans,
                  "proposal_families": {}}
        # The shipped separation keeps the best ARC per neighbourhood; 0 keeps
        # every fragment. Both are measured because the ceiling difference is
        # what says whether deduplication, and not appearance, is the limit.
        for family, separation in (("deduped", None), ("fragments", 0.0)):
            records = _joint(rows, truth, lo, hi, floor, slab, scale,
                             separation_px=separation)
            summary = _joint_report(records, family)
            report["proposal_families"][family] = summary
            gates = summary.pop("gates")
            rows_dump = summary.pop("rows")
            print(json.dumps(summary, sort_keys=True))
            for gate in gates:
                print(f"  score>={gate['score_min']:.4f} "
                      f"answer={gate['answer_fraction_of_opportunities']:.3f} "
                      f"<=3px={gate['within_3px']}")
            summary["gates"] = gates
            summary["rows"] = rows_dump
            if family == "fragments":
                fragment_records = records
        by_index = {row["frame_idx"]: row for row in rows}
        cells = []
        chances = [r for r in fragment_records if r["opportunity"]]
        if chances:
            picked = [chances[i] for i in
                      np.linspace(0, len(chances) - 1,
                                  min(args.keep, len(chances))).astype(int)]
            for record in picked:
                target = truth[record["frame_idx"]]
                cell = _joint_cell(by_index[record["frame_idx"]]["crop"],
                                   (target[0], target[1]), record,
                                   f"{record['t_ms']/1000:.2f}s "
                                   f"n={record['proposals']}")
                if cell is not None:
                    cells.append(cell)
        if cells:
            cols = min(args.keep, 8)
            blank = np.full_like(cells[0], 18)
            cells.extend([blank] * ((-len(cells)) % cols))
            sheet = np.vstack([np.hstack(cells[i:i + cols])
                               for i in range(0, len(cells), cols)])
            proposal_sheet = target_path.with_name(
                target_path.stem + "-proposals" + target_path.suffix)
            if not cv2.imwrite(str(proposal_sheet), sheet):
                raise SystemExit(f"could not write {proposal_sheet}")
            print(proposal_sheet)
        if args.tiers:
            if JOINT_RESIDUAL_SCORE_MIN is None:
                raise SystemExit("select the joint gate on a development "
                                 "interval before running the tiers")
            tiers = {}
            for name, tier_rows in rows_by_tier.items():
                if name == native_name:
                    continue
                locked = _joint(tier_rows, truth, lo, hi, floor, slab, scale,
                                separation_px=0.0, locked=True)
                tiers[name] = _joint_report(locked, name)
                tiers[name].pop("gates")
                rows_dump = tiers[name].pop("rows")
                print(f"tier {name:5s} "
                      + json.dumps(tiers[name], sort_keys=True))
                tiers[name]["rows"] = rows_dump
            report["tier_joint"] = tiers
        sidecar = target_path.with_name(target_path.stem + "-joint.json")
        sidecar.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      allow_nan=False), encoding="utf-8")
        print(sidecar)

    if args.evaluate:
        gallery = []
        previous_fit = None
        last_added_t = -1e12
        result = {mode: [] for mode in
                  ("luma", "residual", "mean",
                   "luma_recent", "residual_recent", "mean_recent")}
        for row in rows:
            fit = row.get("fit")
            # Query before adding this frame, so an accepted frame cannot match itself.
            # Step 2 targets only ring-refused frames. Scoring every accepted
            # frame made prototype cost dwarf the detector while answering a
            # question Step 1 already measured.
            target_xy = truth.get(row["frame_idx"])
            if (target_xy is not None and gallery and previous_fit is not None
                    and row["t_ms"] - previous_fit["t_ms"] <= 250.0):
                dt = row["t_ms"] - previous_fit["t_ms"]
                search = max(2 * FIT_ERR_PX,
                             RUN_PX * (dt / 1000.0) * 2.0)
                mask = self_mask(row["crop"])
                for result_mode in result:
                    recent = result_mode.endswith("_recent")
                    mode = result_mode.removesuffix("_recent")
                    exemplars = ([previous_fit["descriptor"]]
                                 if recent and previous_fit.get("trusted")
                                 and previous_fit.get("descriptor") is not None
                                 else gallery if not recent else [])
                    got = match_near(row["crop"], mask, lo, hi, exemplars,
                                     (previous_fit["cx"], previous_fit["cy"]),
                                     previous_fit["r"], search, mode=mode,
                                     support=slab)
                    if got is not None:
                        error = float(np.hypot(got.x - target_xy[0],
                                               got.y - target_xy[1]))
                        result[result_mode].append((error, got.score, got.margin,
                                                    got.contrast, target_xy[2]))
            if fit is not None:
                # Two adjacent, physically compatible fits force the association.
                adjacent = (previous_fit is not None
                            and row["frame_idx"] == previous_fit["frame_idx"] + 1
                            and np.hypot(fit["cx"] - previous_fit["cx"],
                                         fit["cy"] - previous_fit["cy"]) <= 6.0)
                d = describe(row["crop"], self_mask(row["crop"]),
                             fit["cx"], fit["cy"], fit["r"], lo, hi)
                if adjacent and row["t_ms"] - last_added_t >= 500.0:
                    if d is not None:
                        gallery.append(d)
                        gallery = gallery[-64:]
                        last_added_t = row["t_ms"]
                previous_fit = {**fit, "frame_idx": row["frame_idx"],
                                "t_ms": row["t_ms"], "descriptor": d,
                                "trusted": adjacent and d is not None}
        print(f"gallery {len(gallery)} causally mined exemplars")
        report = {"session_id": args.session, "spans_ms": spans,
                  "gallery_exemplars": len(gallery), "modes": {}}
        for mode, values in result.items():
            if not values:
                print(f"{mode:8s} no scored queries")
                continue
            errors = np.array([v[0] for v in values])
            scores = np.array([v[1] for v in values])
            margins = np.array([v[2] for v in values])
            contrasts = np.array([v[3] for v in values])
            bracket = np.array([v[0] for v in values if v[4] == "bracket"])
            print(f"{mode:8s} n={len(values)} <=3px={(errors <= 3).mean():.4f} "
                  f"median={np.median(errors):.2f}px p95={np.percentile(errors,95):.2f}px "
                  f"bracket_n={len(bracket)} "
                  f"bracket<=3px={((bracket <= 3).mean() if len(bracket) else float('nan')):.4f}")
            mode_report = {
                "n": len(values), "within_3px": float((errors <= 3).mean()),
                "median_error_px": float(np.median(errors)),
                "p95_error_px": float(np.percentile(errors, 95)), "gates": []}
            usable = contrasts >= 10.0
            for feature_name, feature in (("score", scores), ("margin", margins)):
                for quantile in (0.0, 0.2, 0.4, 0.6, 0.8):
                    threshold = float(np.quantile(feature[usable], quantile))
                    keep = usable & (feature >= threshold)
                    answered = int(keep.sum())
                    precision = float((errors[keep] <= 3).mean()) if answered else None
                    row = {"feature": feature_name, "threshold": threshold,
                           "answered": answered,
                           "answer_fraction": answered / len(values),
                           "within_3px": precision}
                    mode_report["gates"].append(row)
                    print(f"  {feature_name}>={threshold:.4f} q={quantile:.1f} "
                          f"answer={answered/len(values):.3f} <=3px={precision:.4f}")
            report["modes"][mode] = mode_report
        selected_values = result["residual_recent"]
        selected = [v for v in selected_values
                    if v[1] >= RECENT_RESIDUAL_SCORE_MIN
                    and v[3] >= MIN_CONTRAST]
        selected_hits = sum(v[0] <= 3.0 for v in selected)
        selected_report = {
            "mode": "residual_recent",
            "score_min": RECENT_RESIDUAL_SCORE_MIN,
            "contrast_min": MIN_CONTRAST,
            "opportunities": len(refused),
            "queries": len(selected_values),
            "answered": len(selected),
            "answer_fraction_of_opportunities": len(selected) / len(refused) if refused else None,
            "within_3px": selected_hits / len(selected) if selected else None,
        }
        report["selected_rule"] = selected_report
        print("selected", json.dumps(selected_report, sort_keys=True))
        if args.tiers:
            tier_report = {name: _tier_recovery(tier_rows, truth, lo, hi,
                                                 slab, scale)
                           for name, tier_rows in rows_by_tier.items()
                           if name != native_name}
            report["tier_recovery"] = tier_report
            for name, values in tier_report.items():
                print(f"tier {name:4s} " + json.dumps(values, sort_keys=True))
        sidecar = target_path.with_suffix(".json")
        sidecar.write_text(json.dumps(report, indent=2, sort_keys=True,
                                      allow_nan=False), encoding="utf-8")
        print(sidecar)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
