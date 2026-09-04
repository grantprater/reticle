r"""Assemble every detected ability EVENT across the demo corpus, ranked.

    .\.venv\Scripts\python.exe prototypes\ability_corpus.py --out-dir DIR [--max N]

the player asked for "a corpus of what you've detected from the demo sessions,
ideally highlighting the ability icon or region on the minimap, and also
ideally include a confidence interval and go from low to high confidence."

Three things this does, and one it deliberately refuses.

1. CANDIDATES ARE GROUPED INTO EVENTS
   A region fragments into many icon-sized candidates that share an onset and
   sit adjacent -- measured on `c0b63335e635`, where one object produced SEVEN.
   Showing them separately would spend the attention seven times on one
   object, and would make any per-candidate rate count it seven times.
   Grouping is (onset within ONSET_MS, centroid within DIST_PX).

   Known limit, from the description of Tejo's E and X: a PULSING region
   appears, vanishes and returns in place, so each pulse is a fresh onset and
   this grouping splits it. Grouping "same place, repeating" is not done here.

2. EVERY EVENT IS DRAWN IN CONTEXT
   A crop alone cannot be judged. Reading the first contact sheet of this
   corpus, a live object seen through small windows was mistaken for static map
   hatching, and only the whole widget over time settled it. So each panel
   carries a magnified inset at a STATED factor AND the full widget with the
   event ringed.

3. IT REFUSES TO CALL THE SCORE A CONFIDENCE
   A confidence interval needs labels to calibrate against and these candidates
   have none, so any interval printed here would be invented. What the score IS:
   a weighted sum of signals this repo has separately measured, used ONLY to
   order the sheet. It is a ranking, not a probability, and it says so in the
   output. `notes/predictions.jsonl` and `reticle.glance calibration` are where
   calibrated numbers come from, and they need someone's labels first.

The four signals, each with the measurement behind it:

    lifetime      `ability_eval`: gating on n_observations/duration_ms roughly
                  DOUBLED precision at zero recall cost on both widget sizes.
                  The best-evidenced feature available here.
    onset > 0     `ability_eval`: an ability is an event, so it has a birth --
                  no real object in either scored session starts at t_ms == 0.
                  Something present in frame one is scenery or HUD.
    self distance `scan_ability_clip`, 2026-09-02: `self_icon_dist` correctly
                  explained 5 of 6 false positives that were fragments of
                  the player icon, losing no real trapwire. NULL scores
                  NEUTRAL, not good -- it means `self_rings` did not find the
                  player, which is absence of evidence rather than evidence.
    geometry      abilities are placed on FLOOR; BOXEDGE is where this channel's
                  line-work artefacts have always tended to sit.

Weights are round numbers reflecting that ordering of evidence. They are NOT
fitted: fitting them on unlabelled data would be scoring a guess against
itself, which is the `minimap_agent` seeding mistake in another costume.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.profiles import get_profile                              # noqa: E402

STORE = Path.home() / "reticle-store"
CAND = STORE / "labels" / "ability_candidates"

ONSET_MS = 300      # one scan step plus slack: "appeared at the same moment"
DIST_PX = 60        # "pieces of the same object"
SELF_NEAR_PX = 20   # inside this, a candidate is probably the player's own icon
ZOOM = 4            # magnification of the inset, printed on every panel
INSET = 34          # half-width, in source px, of the magnified region


def load_events(sid):
    f = CAND / f"{sid}.jsonl"
    if not f.exists():
        return []
    rows = [json.loads(l) for l in open(f, encoding="utf-8") if l.strip()]
    rows.sort(key=lambda r: r["t_ms"])
    groups: list = []
    for r in rows:
        for g in groups:
            if abs(g["t0"] - r["t_ms"]) <= ONSET_MS and any(
                    (r["x"] - m["x"]) ** 2 + (r["y"] - m["y"]) ** 2 <= DIST_PX ** 2
                    for m in g["rows"]):
                g["rows"].append(r)
                break
        else:
            groups.append({"t0": r["t_ms"], "rows": [r]})
    out = []
    for g in groups:
        rs = g["rows"]
        dists = [r["self_icon_dist"] for r in rs if r.get("self_icon_dist") is not None]
        out.append({
            "sid": sid,
            "t0": g["t0"],
            "n_frag": len(rs),
            "x": int(np.mean([r["x"] for r in rs])),
            "y": int(np.mean([r["y"] for r in rs])),
            "n_obs": max(r.get("n_observations", 0) for r in rs),
            "dur_ms": max(r.get("duration_ms", 0) for r in rs),
            "area": int(sum(r.get("area", 0) for r in rs)),
            "self_dist": min(dists) if dists else None,
            "geo": rs[0].get("geo_label"),
            "colour": next((r.get("colour_local") or r.get("colour") for r in rs
                            if (r.get("colour_local") or r.get("colour"))
                            not in (None, "none")), None),
            "box": [min(r["box"][0] for r in rs), min(r["box"][1] for r in rs),
                    max(r["box"][0] + r["box"][2] for r in rs),
                    max(r["box"][1] + r["box"][3] for r in rs)],
        })
    return out


def score(e):
    """Ranking heuristic. NOT a probability -- see the module docstring."""
    s, why = 0.0, []
    n = e["n_obs"]
    if n >= 20:
        s += 3.0
        why.append("long-lived (n>=20)")
    elif n >= 8:
        s += 2.0
        why.append("persistent (n>=8)")
    elif n >= 3:
        s += 1.0
        why.append("brief (n>=3)")
    else:
        why.append("2 frames only")
    if e["t0"] > 0:
        s += 2.0
        why.append("has an onset")
    else:
        s -= 2.0
        why.append("present from frame 0")
    d = e["self_dist"]
    if d is None:
        why.append("self distance unknown")
    elif d <= SELF_NEAR_PX:
        s -= 3.0
        why.append("%.0fpx from own icon" % d)
    else:
        s += 1.5
        why.append("clear of own icon (%.0fpx)" % d)
    if e["geo"] == "FLOOR":
        s += 0.5
        why.append("on floor")
    elif e["geo"] == "BOXEDGE":
        s -= 1.0
        why.append("on box edge")
    if e["colour"]:
        s += 0.5
        why.append("colour " + str(e["colour"]))
    return s, why


def agent_of(sid):
    man = json.loads((STORE / "manifests" / (sid + ".json")).read_text())
    tags = man.get("tags", [])
    agent = next((x for x in tags if ":" not in x and x not in
                  ("ability-demo", "custom-game", "infinite-abilities")), sid[:8])
    return agent, man


def render(events, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    by_sid: dict = {}
    for e in events:
        by_sid.setdefault(e["sid"], []).append(e)
    made = []
    for sid, evs in by_sid.items():
        agent, man = agent_of(sid)
        src = man["source"]
        fps = float(src["fps"])
        prof = get_profile(man["source_profile"])
        x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(
            int(src["width"]), int(src["height"]))
        cap = cv2.VideoCapture(src["path"])
        for e in evs:
            t_show = e["t0"] + min(e["dur_ms"], 600)
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_show / 1000.0 * fps)))
            ok, fr = cap.read()
            if not ok:
                continue
            wid = fr[y0:y1, x0:x1].copy()
            bx = e["box"]
            cv2.rectangle(wid, (bx[0] - 2, bx[1] - 2), (bx[2] + 2, bx[3] + 2),
                          (0, 235, 255), 2)
            cx, cy = e["x"], e["y"]
            a = max(0, min(cx - INSET, wid.shape[1] - 2 * INSET))
            b = max(0, min(cy - INSET, wid.shape[0] - 2 * INSET))
            patch = wid[b:b + 2 * INSET, a:a + 2 * INSET]
            if patch.size == 0:
                continue
            big = cv2.resize(patch, None, fx=ZOOM, fy=ZOOM,
                             interpolation=cv2.INTER_NEAREST)
            cv2.rectangle(big, (0, 0), (big.shape[1] - 1, big.shape[0] - 1),
                          (0, 235, 255), 2)
            bh = big.shape[0]
            cv2.line(big, (10, bh - 12), (10 + 10 * ZOOM, bh - 12), (255, 255, 255), 3)
            cv2.putText(big, "%dx  10px" % ZOOM, (10, bh - 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
            ws = 200
            wid_s = cv2.resize(wid, (ws, int(ws * wid.shape[0] / wid.shape[1])),
                               interpolation=cv2.INTER_AREA)
            h = max(big.shape[0], wid_s.shape[0])
            panel = np.full((h, big.shape[1] + wid_s.shape[1] + 8, 3), 22, np.uint8)
            panel[:big.shape[0], :big.shape[1]] = big
            panel[:wid_s.shape[0], big.shape[1] + 8:] = wid_s
            # JPEG, not PNG: 147 PNG panels came to 15 MB, and an Artifact
            # embeds these as base64 (+33%) under a 16 MB cap. The magnified
            # inset is 4x INTER_NEAREST, so it is large flat blocks, which JPEG
            # at q=92 carries without visible artefacts -- keeping the
            # magnification matters more than the last few bytes of fidelity.
            name = "%s_%06d.jpg" % (agent, e["t0"])
            cv2.imwrite(str(out_dir / name), panel,
                        [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            e["img"] = name
            e["agent"] = agent
            made.append(e)
        cap.release()
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max", type=int, default=200)
    a = ap.parse_args()
    sids = sorted(p.stem for p in CAND.glob("*.jsonl"))
    events = []
    for sid in sids:
        events.extend(load_events(sid))
    for e in events:
        e["score"], e["why"] = score(e)
    events.sort(key=lambda e: e["score"])
    print("%d sessions, %d events (score %.1f .. %.1f)"
          % (len(sids), len(events), events[0]["score"], events[-1]["score"]))
    if len(events) > a.max:
        step = len(events) / float(a.max)
        events = [events[int(i * step)] for i in range(a.max)]
        print("  sampled %d evenly across RANK order, so the whole range shows"
              % len(events))
    made = render(events, Path(a.out_dir))
    made.sort(key=lambda e: e["score"])
    (Path(a.out_dir) / "events.json").write_text(
        json.dumps(made, indent=1), encoding="utf-8")
    print("rendered %d panels to %s" % (len(made), a.out_dir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
