"""Name every stored ally icon of a session, and render a sample to check.

    .\\.venv\\Scripts\\python.exe tools/ally_identity_review.py --out DIR
        [--session SID] [--sample 40] [--seed 0]

Reads the session's `ally_icon` events and its board-constrained lineup, asks
`adjudication.identity.claims_from_ally_icons` for one claim per icon, and
adjudicates them. Writes `report.json` (counts, refusals by reason, every
verdict) and `sample.png` + `sample.json`: a seeded random draw of NAMED icons,
cropped from source beside the official art, for a source check. Only the
sample decodes video, and only its frames. Refuses to overwrite `--out`.
"""
from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
import sys

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reticle import metrics
from reticle.adjudication.identity import (AGENT_IDENTITY_VERSION, MINIMAP_SURFACES,
    adjudicate_agent_identity, claims_from_ally_icons, load_identity_gallery)
from reticle.decode import sample_at
from reticle.lineup import load_lineup
from reticle.minimap import minimap_roi_px
from reticle.profiles import get_profile
from reticle.store import Store

TILE = 96


def _art(store, name):
    im = cv2.imread(str(Path(store.root) / "reference" / "assets" / "agents"
                        / f"{name}_minimap_portrait.png"), cv2.IMREAD_UNCHANGED)
    if im is None:
        return np.zeros((TILE, TILE, 3), np.uint8)
    a = im[:, :, 3:4] / 255.0
    out = (im[:, :, :3] * a + 128 * (1 - a)).astype(np.uint8)
    out = cv2.resize(out, (TILE, TILE))
    cv2.putText(out, name, (2, 11), cv2.FONT_HERSHEY_PLAIN, 0.8, (255, 255, 255), 1)
    return out


def sheet(store, manifest, picks, names):
    """Source crops of the picked icons, numbered, under a strip of the art."""
    src = manifest["source"]
    x0, y0, _, _ = minimap_roi_px(get_profile(manifest["source_profile"]),
                                  int(src["width"]), int(src["height"]))
    want = sorted({p["t_ms"] for p in picks})
    frames = {round(s.t_ms, 1): s.frame
              for s in sample_at(src["path"], want, float(src["fps"]))}
    tiles = []
    for i, p in enumerate(picks):
        frame = frames.get(round(p["t_ms"], 1))
        tile = np.zeros((TILE, TILE, 3), np.uint8)
        if frame is not None:
            h = int(p["r"]) + 6
            cx, cy = int(round(p["x"])) + x0, int(round(p["y"])) + y0
            crop = frame[cy - h:cy + h, cx - h:cx + h]
            if crop.size:
                tile = cv2.resize(crop, (TILE, TILE), interpolation=cv2.INTER_NEAREST)
        cv2.putText(tile, f"{i}", (2, 11), cv2.FONT_HERSHEY_PLAIN, 0.9, (0, 0, 255), 1)
        tiles.append(tile)
    per_row = 8
    tiles += [np.zeros((TILE, TILE, 3), np.uint8)] * (-len(tiles) % per_row)
    rows = [np.hstack(tiles[i:i + per_row]) for i in range(0, len(tiles), per_row)]
    art = np.hstack([_art(store, n) for n in names]
                    + [np.zeros((TILE, TILE, 3), np.uint8)] * (per_row - len(names)))
    return np.vstack([art, np.full((6, art.shape[1], 3), 255, np.uint8)] + rows)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="a06f04a0059f")
    ap.add_argument("--out", required=True)
    ap.add_argument("--sample", type=int, default=40)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)
    out = Path(args.out)
    if out.exists():
        raise FileExistsError(f"refusing to overwrite evidence: {out}")

    store = Store()
    manifest = store.read_manifest(args.session)
    events = store.read_events("ally_icon", args.session)
    if not events:
        raise SystemExit(f"no ally_icon events for {args.session} -- "
                         f"run `reticle scan {args.session} --only ally_icon`")
    icons = [e for e in events if e["kind"] == "icon"]
    lineup = load_lineup(args.session, store.root)
    gallery = load_identity_gallery(store.root, MINIMAP_SURFACES)
    claims = claims_from_ally_icons(icons, lineup, gallery=gallery,
                                    session_id=args.session)
    verdicts = adjudicate_agent_identity(claims)

    refused = Counter((c["reason"] or "").split(" ")[0] for c in claims if not c["agent"])
    named = [c for c in claims if c["agent"]]
    described = sum(1 for i in icons if not i.get("reason") and i.get("composition"))
    counts = {"frames": sum(1 for e in events if e["kind"] == "frame"),
              "icons": len(icons), "described": described, "named": len(named),
              "named_of_described": round(len(named) / described, 4) if described else None,
              "by_agent": dict(sorted(Counter(c["agent"] for c in named).items())),
              "refused": dict(sorted(refused.items()))}
    candidates = sorted(named[0]["evidence"]["candidates"]) if named else []

    rng = random.Random(args.seed)
    picks = [{"entity_id": c["entity_id"], "agent": c["agent"],
              "t_ms": c["observed_at_ms"], "x": c["evidence"]["x"],
              "y": c["evidence"]["y"], "r": c["evidence"]["r"],
              "margin": c["evidence"]["margin"]}
             for c in rng.sample(named, min(args.sample, len(named)))]
    picks.sort(key=lambda p: p["t_ms"])

    out.mkdir(parents=True)
    versions = {"ally_icon": store.events_version("ally_icon", args.session),
                "agent_identity": AGENT_IDENTITY_VERSION,
                "lineup": lineup.get("version")}
    (out / "report.json").write_text(json.dumps(
        {"session": args.session, "versions": versions, "counts": counts,
         "verdicts": [{k: v[k] for k in ("entity_id", "agent", "status", "reason")}
                      for v in verdicts]}, indent=1) + "\n", encoding="utf-8")
    (out / "sample.json").write_text(json.dumps(
        [{"i": i, **p} for i, p in enumerate(picks)], indent=1) + "\n", encoding="utf-8")
    cv2.imwrite(str(out / "sample.png"), sheet(store, manifest, picks, candidates))
    metrics.record("ally_identity_review", part="official-art", session=args.session,
                   values={k: v for k, v in counts.items()
                           if isinstance(v, (int, float)) and v is not None},
                   deps={**versions, "gallery": "minimap_portrait art",
                         "margin_min": "SIDE_MARGIN_MIN"},
                   context={"sample": len(picks), "seed": args.seed})
    print(json.dumps(counts, indent=1))
    print(f"sample     {len(picks)} named icons -> {out / 'sample.png'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
