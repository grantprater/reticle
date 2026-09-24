r"""Score the drawn light as a gate on ability candidates, against player labels.

    .\.venv\Scripts\python.exe prototypes\ability_light_gate.py

The candidate generator in `ability_corpus.py` flags whatever differs from the
static map, and a lit viewcone is exactly that: a bright wedge from the self
icon, cut off by a wall. The player called 19 of 44 answered components in
e78e75b2d191 viewcone fragments. `lighting.lit_mask` already observes the same
pixels, so it is asked first, before any tuning of the generator.

For every `labels/ability_grouping` row with a position, this reads the source
frame at the component's time, computes `lit_mask` with the (map, profile)
geometry reference, and reports the lit fraction of the component's box by
player answer. It decodes video; it writes nothing but its report.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle import geometry, lighting, metrics  # noqa: E402
from reticle.adjudication.ability import _components, _labels  # noqa: E402
from reticle.minimap import minimap_roi_px  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
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


def main() -> int:
    comps = {c["component_id"]: c for c in _components(STORE, _labels(STORE))}
    rows = [r for r in answers().values()
            if r.get("component_id") in comps and r.get("t_ms") is not None
            and not r.get("unsure")]
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session_id"]].append(r)
    results = []
    for sid, rs in sorted(by_session.items()):
        man = geometry.manifest(sid, STORE)
        z = np.load(geometry.require(sid, STORE))
        ref = lighting.reference(z)
        if ref is None:
            print(f"{sid}: geometry has no lighting reference -- skipped")
            continue
        src = man["source"]
        x0, y0, x1, y1 = minimap_roi_px(get_profile(man["source_profile"]),
                                        int(src["width"]), int(src["height"]))
        cap = cv2.VideoCapture(src["path"])
        for r in rs:
            cap.set(cv2.CAP_PROP_POS_MSEC, float(r["t_ms"]))
            ok, frame = cap.read()
            if not ok:
                results.append({**r, "lit_frac": None, "why": "unreadable frame"})
                continue
            crop = frame[y0:y1, x0:x1]
            if crop.shape[:2] != ref.known.shape:
                results.append({**r, "lit_frac": None, "why": "geometry size mismatch"})
                continue
            lit = lighting.lit_mask(crop, ref)
            bx, by, bw, bh = comps[r["component_id"]]["box"] or [r["x"] - 6, r["y"] - 6, 12, 12]
            win = (slice(max(0, by), by + bh), slice(max(0, bx), bx + bw))
            known = ref.known[win]
            frac = float(lit[win][known].mean()) if known.any() else None
            results.append({**r, "lit_frac": frac,
                            "why": None if frac is not None else "box off known floor"})
        cap.release()

    def group(r):
        return ("ability" if r["answer"] in ABILITY else
                "viewcone" if r["answer"] == "viewcone_fragment" else "other")

    out = defaultdict(list)
    for r in results:
        out[group(r)].append(r)
    for g in ("viewcone", "ability", "other"):
        vals = [r["lit_frac"] for r in out[g] if r["lit_frac"] is not None]
        refused = len(out[g]) - len(vals)
        if not out[g]:
            continue
        print(f"{g:9s} n={len(out[g]):3d} refused={refused:2d} "
              f">=0.60 lit {sum(v >= 0.6 for v in vals):3d}  "
              f"<0.30 lit {sum(v < 0.3 for v in vals):3d}  "
              f"median {np.median(vals) if vals else float('nan'):.2f}")
    for r in sorted(results, key=lambda r: (group(r), r["lit_frac"] or -1)):
        lit = "-" if r["lit_frac"] is None else f"{r['lit_frac']:.2f}"
        why = f"  {r['why']}" if r["why"] else ""
        print(f"  {group(r):9s} {r['answer']:28s} {r['session_id']} "
              f"{r['t_ms'] / 1000:7.1f}s ({r['x']},{r['y']}) lit={lit}{why}")
    vals = {g: [r["lit_frac"] for r in out[g] if r["lit_frac"] is not None]
            for g in ("viewcone", "ability")}
    metrics.record("ability_light_gate", part="grouping-labels", session="all-labelled",
                   values={"viewcone_n": len(out["viewcone"]),
                           "viewcone_lit_ge_060": sum(v >= 0.6 for v in vals["viewcone"]),
                           "ability_n": len(out["ability"]),
                           "ability_lit_lt_030": sum(v < 0.3 for v in vals["ability"])},
                   deps={"lighting": lighting.LIGHTING_VERSION,
                         "labels": "labels/ability_grouping last row per key, unsure excluded"},
                   context={"sessions": sorted(by_session)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
