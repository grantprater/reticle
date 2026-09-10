r"""Audit the color-free minimap proposer on exhaustive painted frames.

    .\.venv\Scripts\python.exe prototypes\proposal_audit.py SESSION...

This evaluates candidate ACQUISITION, before description or clustering.  It
uses only `ability_paint` frames declared exhaustive and not unsure.  Those
frames mark ability icons, non-ability minimap icons, and regions; therefore an
unmarked proposal is a real false positive on the scope the painting covers.

The audit deliberately disables `mine_icons`' interval-frequency subtraction.
A hand-selected label set is not an independent background sample, and using
its occupancy to erase pixels would leak targets into the proposer.  The
first-run subtraction removed only 14 pixels, while its replacement remains a
separate design question.

No thresholds are selected here.  The tool evaluates the proposer's recorded
margin and area band, attributes misses to the earliest observable acquisition
failure, and records a versioned metrics row.  It creates no labels and changes
no production reader.
"""
from __future__ import annotations

import argparse
import base64
from collections import Counter
import json
from pathlib import Path
import sys

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from reticle import geometry, metrics                              # noqa: E402
from reticle.minimap import minimap_roi_px, slab_mask, widget_scale  # noqa: E402
from reticle.profiles import get_profile                           # noqa: E402
from reticle.store import DEFAULT_STORE, Store                     # noqa: E402
from mine_icons import (ICON_AREA_REF, MARGIN, proposal_components)  # noqa: E402
from paint_icons import OUT_DIR, load_done                          # noqa: E402

AUDIT_VERSION = "proposal-audit-0.2.0"
MATCH_SLACK_PX = 4.0


def _region_mask(row: dict, shape: tuple[int, int]) -> np.ndarray:
    out = np.zeros(shape, bool)
    for region in row.get("regions", []):
        x0, y0, width, height = region["bbox"]
        raw = base64.b64decode(region["mask_png"])
        sub = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_GRAYSCALE)
        if sub is not None:
            out[y0:y0 + height, x0:x0 + width] |= sub > 127
    return out


def _maximum_matching(icons: list[dict], proposals: list[dict],
                      slack: float = MATCH_SLACK_PX) -> dict[int, int]:
    """Maximum-cardinality icon-to-proposal assignment within painted radii."""
    edges = []
    for icon in icons:
        radius = float(icon.get("r", 7)) + slack
        near = []
        for pi, proposal in enumerate(proposals):
            distance = float(np.hypot(proposal["cx"] - icon["x"],
                                      proposal["cy"] - icon["y"]))
            if distance <= radius:
                near.append((distance, pi))
        edges.append([pi for _distance, pi in sorted(near)])

    proposal_owner: dict[int, int] = {}

    def claim(icon_i: int, seen: set[int]) -> bool:
        for proposal_i in edges[icon_i]:
            if proposal_i in seen:
                continue
            seen.add(proposal_i)
            owner = proposal_owner.get(proposal_i)
            if owner is None or claim(owner, seen):
                proposal_owner[proposal_i] = icon_i
                return True
        return False

    for icon_i in sorted(range(len(icons)), key=lambda i: len(edges[i])):
        claim(icon_i, set())
    return {icon_i: proposal_i for proposal_i, icon_i in proposal_owner.items()}


def diagnose(icons: list[dict], components: list[dict], labels: np.ndarray,
             lo_area: int, hi_area: int,
             slack: float = MATCH_SLACK_PX) -> dict:
    """Score one frame and expose why every unmatched painted icon was missed."""
    accepted = [c for c in components if lo_area <= c["area"] <= hi_area]
    matched = _maximum_matching(icons, accepted, slack)
    accepted_ids = {c["id"] for c in accepted}
    failures = Counter()
    failures_by_category: dict[str, Counter] = {}
    fragmentation = 0
    errors = []

    yy, xx = np.ogrid[:labels.shape[0], :labels.shape[1]]
    for icon_i, icon in enumerate(icons):
        if icon_i in matched:
            proposal = accepted[matched[icon_i]]
            errors.append(float(np.hypot(proposal["cx"] - icon["x"],
                                         proposal["cy"] - icon["y"])))
            continue
        radius = float(icon.get("r", 7)) + slack
        disc = (xx - icon["x"]) ** 2 + (yy - icon["y"]) ** 2 <= radius ** 2
        ids = sorted(int(i) for i in np.unique(labels[disc]) if i)
        if len(ids) > 1:
            fragmentation += 1
        overlapping = [components[i - 1] for i in ids]
        reason = None
        if not overlapping:
            reason = "no_residual_support"
        elif any(c["id"] in accepted_ids for c in overlapping):
            reason = "accepted_component_miscentered_or_claimed"
        elif any(c["area"] > hi_area for c in overlapping):
            reason = "component_too_large"
        elif all(c["area"] < lo_area for c in overlapping):
            reason = "components_too_small"
        else:
            reason = "mixed_rejected_support"
        failures[reason] += 1
        category = icon.get("category_id") or "unknown"
        failures_by_category.setdefault(category, Counter())[reason] += 1

    return {
        "accepted": accepted,
        "matched": matched,
        "failures": failures,
        "failures_by_category": failures_by_category,
        "fragmented_targets": fragmentation,
        "center_errors": errors,
    }


def audit_session(session: str, store_root: Path) -> dict | None:
    store = Store(store_root)
    manifest_path = store_root / "manifests" / f"{session}.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    source = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    x0, y0, x1, y1 = minimap_roi_px(
        profile, int(source["width"]), int(source["height"]))
    geometry_path = geometry.require(session, store.root)
    with np.load(geometry_path) as data:
        static_map = data["static"].copy()
        lo = data["lo_gray"].astype(np.float32)
        hi = data["hi_gray"].astype(np.float32)
    stability = geometry.stability(session, store.root, static_map.shape[:2])
    slab = slab_mask(static_map, sd=stability)

    scale = widget_scale(static_map.shape[1])
    lo_area = max(4, int(round(ICON_AREA_REF[0] * scale * scale)))
    hi_area = int(round(ICON_AREA_REF[1] * scale * scale))
    rows = load_done(OUT_DIR / f"{session}.jsonl")
    rows = {t: row for t, row in rows.items()
            if row.get("exhaustive") and not row.get("unsure")}
    if not rows:
        return None

    cap = cv2.VideoCapture(source["path"])
    fps = float(source["fps"])
    totals = Counter()
    failures = Counter()
    failures_by_category: dict[str, Counter] = {}
    center_errors: list[float] = []
    categories = Counter()
    decoded = 0
    static_none = np.zeros(slab.shape, bool)
    for t_ms, row in sorted(rows.items()):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            totals["decode_failures"] += 1
            continue
        crop = frame[y0:y1, x0:x1]
        if crop.shape[:2] != slab.shape:
            totals["shape_failures"] += 1
            continue
        decoded += 1
        grey = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
        components, _foreign, labels = proposal_components(
            grey, lo, hi, slab, static_none)
        icons = list(row.get("icons", []))
        result = diagnose(icons, components, labels, lo_area, hi_area)
        accepted = result["accepted"]
        matched_proposals = set(result["matched"].values())
        region = _region_mask(row, slab.shape)
        in_region = 0
        for pi, proposal in enumerate(accepted):
            if pi in matched_proposals:
                continue
            px = min(slab.shape[1] - 1, max(0, int(round(proposal["cx"]))))
            py = min(slab.shape[0] - 1, max(0, int(round(proposal["cy"]))))
            if region[py, px]:
                in_region += 1
        totals.update({
            "frames": 1,
            "icons": len(icons),
            "proposals": len(accepted),
            "tp": len(result["matched"]),
            "fp": len(accepted) - len(result["matched"]) - in_region,
            "in_region": in_region,
            "fragmented_targets": result["fragmented_targets"],
        })
        failures.update(result["failures"])
        for category, counts in result["failures_by_category"].items():
            failures_by_category.setdefault(category, Counter()).update(counts)
        center_errors.extend(result["center_errors"])
        for icon in icons:
            categories[icon.get("category_id") or "unknown"] += 1
    cap.release()

    tp, fp, n_icons = totals["tp"], totals["fp"], totals["icons"]
    values = dict(totals)
    values.update({
        "fn": n_icons - tp,
        "recall": round(tp / n_icons, 4) if n_icons else None,
        "precision": round(tp / (tp + fp), 4) if tp + fp else None,
        "median_center_error_px": (round(float(np.median(center_errors)), 3)
                                   if center_errors else None),
        "p90_center_error_px": (round(float(np.percentile(center_errors, 90)), 3)
                                if center_errors else None),
        "failures": dict(sorted(failures.items())),
        "failures_by_category": {
            category: dict(sorted(counts.items()))
            for category, counts in sorted(failures_by_category.items())
        },
        "categories": dict(sorted(categories.items())),
        "background_source": "baked_map_profile_geometry",
    })
    values["decoded_frames"] = decoded
    return values


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("sessions", nargs="+")
    parser.add_argument("--store", default=str(DEFAULT_STORE))
    args = parser.parse_args(argv)
    store_root = Path(args.store)
    any_scored = False
    for session in args.sessions:
        values = audit_session(session, store_root)
        if values is None:
            print(f"{session}: no exhaustive painted frames -- cannot answer")
            metrics.record(
                "proposal_audit", part="acquisition", session=session,
                status=metrics.CANNOT_ANSWER, note="no exhaustive painted frames",
                deps={"audit_version": AUDIT_VERSION,
                      "truth": "ability_paint/exhaustive"}, context={})
            continue
        any_scored = True
        print(f"{session}: {values['frames']} frames, {values['icons']} icons, "
              f"{values['proposals']} proposals")
        print(f"  TP {values['tp']}  FP {values['fp']}  FN {values['fn']}  "
              f"in-region {values['in_region']}  recall {values['recall']:.1%}  "
              f"precision {values['precision']:.1%}")
        print(f"  center error median {values['median_center_error_px']} px, "
              f"p90 {values['p90_center_error_px']} px")
        print(f"  miss reasons {values['failures']}; "
              f"fragmented targets {values['fragmented_targets']}")
        if values["failures_by_category"]:
            print(f"  misses by category {values['failures_by_category']}")
        metrics.record(
            "proposal_audit", part="acquisition", session=session, values=values,
            deps={
                "audit_version": AUDIT_VERSION,
                "proposer": metrics.fingerprint(
                    proposal_components, MARGIN=MARGIN,
                    ICON_AREA_REF=ICON_AREA_REF, MATCH_SLACK_PX=MATCH_SLACK_PX),
                "truth": "ability_paint/exhaustive",
                "static_subtraction": "disabled-no-independent-background-sample",
            },
            context={"frames": values["frames"], "icons": values["icons"],
                     "categories": values["categories"],
                     "background_source": values["background_source"]},
        )
    return 0 if any_scored else 1


if __name__ == "__main__":
    raise SystemExit(main())
