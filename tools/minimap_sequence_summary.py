"""Summarize/replay stored sequence evidence; never decodes source media.

Numbers describe detector consistency and association churn, not accuracy --
with ONE exception, and it is the useful one. `overlay --minimap-diagnostics`
stores `raw_allies` and `raw_self` per frame, so the whole temporal chain
(`track.Tracker`, then `minimap_lifecycle.Lifecycle`) re-runs here without
touching the video.

**FORCED CORRESPONDENCES are the exception.** When a role has exactly one
detection in frame t-1 and exactly one in frame t, the correspondence between
them is not a hypothesis -- there is nothing else either could be. A new id
across that pair is a track broken that could not have been broken, and no
threshold was fitted to say so. In the 2 s Ascent and Lotus windows the self
icon is detected in all 120 frames, so its id count is a pure defect count:
anything above 1 is fragmentation. That is what `forced_breaks` counts, and
`ally` is reported beside it WITHOUT the same claim -- a lone ally detection
in two frames may be two different allies, and in the Ascent window it is
something else again (see the plan's note on the two fit modes).
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.track import FIT_ERR_PX, Tracker
from reticle.minimap import widget_scale
from reticle.minimap_lifecycle import Lifecycle


def summarize(path):
    rows = [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]
    provenance, frames = rows[0], rows[1:]
    if provenance.get("type") != "provenance":
        raise ValueError("missing provenance")
    result = {"session": provenance["session"], "frames": len(frames),
              "widget_unavailable": sum(r["widget"] != "drawn" for r in frames),
              "association_replay": {}, "distance_bins": []}
    scale = widget_scale(provenance["widget_width"])
    # 0 and sqrt(0.5) are kept for comparability with the sidecars produced
    # before `FIT_ERR_PX` was measured -- sqrt(0.5) is integer quantization,
    # which is a floor on the fit's centre error rather than a measurement of
    # it, and is what the stored windows were tracked at.
    for error in (0, 2 ** -0.5, FIT_ERR_PX):
        result["association_replay"][str(round(error, 4))] = _replay(
            frames, scale, error, provenance.get("origin_events") or ())
    for i in range(5):
        bins = [r["distance_agreement"]["bins"][i] for r in frames
                if r.get("distance_agreement", {}).get("bins")]
        if bins:
            row = {k: sum(b[k] for b in bins) for k in
                   ("known", "predicted", "lit", "overlap", "predicted_only", "lit_only")}
            row.update(from_px=bins[0]["from_px"], to_px=bins[0]["to_px"])
            result["distance_bins"].append(row)
    return result


def _replay(frames, scale, error, events):
    """One pass of the whole chain at one error term. See the module docstring."""
    trackers = {r: Tracker(position_error_px=error, scale=scale)
                for r in ("self", "allies")}
    life = Lifecycle(scale=scale)
    ids = {r: set() for r in trackers}
    forced = {r: 0 for r in trackers}
    previous = {r: (0, None) for r in trackers}    # (n detections, the lone id)
    states = {}
    for row in frames:
        t_ms = row["t_ms"]
        if row["widget"] != "drawn":
            for tracker in trackers.values():
                tracker.step(t_ms, [])
            life.step({"t_ms": t_ms, "widget": "not_drawn", "observations": []}, events)
            previous = {r: (0, None) for r in trackers}
            continue
        observations = []
        for role, tracker in trackers.items():
            dets = row.get("raw_" + role) or []
            fresh = [t for t in tracker.step(t_ms, dets) if t.t_ms == t_ms]
            ids[role].update(t.tid for t in fresh)
            n_before, lone = previous[role]
            if len(dets) == 1 and n_before == 1 and len(fresh) == 1:
                if lone is not None and fresh[0].tid != lone:
                    forced[role] += 1
            previous[role] = (len(dets),
                              fresh[0].tid if len(dets) == 1 and len(fresh) == 1 else None)
            for t in fresh:
                observations.append(
                    {"role": "self" if role == "self" else "ally",
                     "track_id": t.tid, "x": t.x, "y": t.y, "r": t.r,
                     "position_state": "observed",
                     "light_support": _stored_support(row, t, role)})
        for adjudicated in life.step({"t_ms": t_ms, "widget": "drawn",
                                      "observations": observations,
                                      "light_budget": row.get("light_budget")}, events):
            states[adjudicated["state"]] = states.get(adjudicated["state"], 0) + 1
    return {"ids": {r: len(v) for r, v in ids.items()},
            "forced_breaks": forced, "lifecycle_states": states}


def _stored_support(row, track, role):
    """The light support the sidecar recorded at this position, never recomputed."""
    want = "self" if role == "self" else "ally"
    for o in row.get("observations", ()):
        if o["role"] == want and o["x"] == track.x and o["y"] == track.y:
            return o.get("light_support")
    return {"known": None, "lit": None, "reason": "not stored for this position"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar", type=Path)
    args = parser.parse_args()
    print(json.dumps(summarize(args.sidecar), indent=2))
