"""Summarize/replay stored sequence evidence; never decodes source media.

Numbers describe detector consistency and association churn, not accuracy.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.track import Tracker
from reticle.minimap import widget_scale


def summarize(path):
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    provenance, frames = rows[0], rows[1:]
    if provenance.get("type") != "provenance":
        raise ValueError("missing provenance")
    result = {"session": provenance["session"], "frames": len(frames),
              "widget_unavailable": sum(r["widget"] != "drawn" for r in frames),
              "association_replay": {}, "distance_bins": []}
    scale = widget_scale(provenance["widget_width"])
    for error in (0, 2 ** -0.5):
        counts = {}
        for role in ("self", "allies"):
            tracker = Tracker(position_error_px=error, scale=scale)
            ids = set()
            for row in frames:
                ids.update(t.tid for t in tracker.step(row["t_ms"], row.get("raw_" + role, [])))
            counts[role] = len(ids)
        result["association_replay"][str(error)] = counts
    for i in range(5):
        bins = [r["distance_agreement"]["bins"][i] for r in frames
                if r.get("distance_agreement", {}).get("bins")]
        if bins:
            row = {k: sum(b[k] for b in bins) for k in
                   ("known", "predicted", "lit", "overlap", "predicted_only", "lit_only")}
            row.update(from_px=bins[0]["from_px"], to_px=bins[0]["to_px"])
            result["distance_bins"].append(row)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.sidecar), indent=2))
