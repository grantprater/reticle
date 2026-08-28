"""Find every distinct thing that appears on the minimap in a short, controlled ability-demo clip.

    .\\.venv\\Scripts\\python.exe prototypes\\scan_ability_clip.py <session> [--step-ms 150]

Then review and name what it found:

    .\\.venv\\Scripts\\python.exe prototypes\\label_ability.py <session>

Why this is a different tool from label_dynamic.py's detection stage
----------------------------------------------------------------------
`label_dynamic.py` samples SPARSELY across a whole match -- a handful of times
per round, stratified over rounds and trimmed to live play -- because a match
is long and the point is to characterise a RATE without spending Grant's time
on every frame. A demo clip Grant records deliberately (one agent, every
ability, on purpose) is the opposite problem: short, near-empty by design, and
the entire point is to catch EVERY placement -- missing one defeats the
exercise. `reticle.rounds.round_bounds` also has nothing to trim to: a clip
with no scoreline has no rounds and no buy phase. So this scans DENSELY, every
`step_ms`, across the WHOLE clip instead, with no notion of match structure at
all.

This produces CANDIDATES, not verified labels, and the file it writes says so.
Every row is `by: "claude", kind: "ability"` -- a guess, not an answer. It
writes to `<store>/labels/ability_candidates/`, never to
`<store>/labels/minimap_dynamic/` -- writing into the human classify-pass
store would make `label_dynamic.py` silently skip these positions as already
done the next time it ran on this session, which is exactly the seeding
mistake `label_icon_agent.py`'s docstring warns against ("provenance decides,
not presence"). `by` says who wrote a row; here it says "not a person yet".

The guess is only ever `ability` because that is what the clip is FOR --
almost everything a dense scan finds on an ability-demo minimap is the
ability itself, or is Grant's own player icon sitting there the whole time.
No attempt is made here to tell those apart algorithmically: `label_ability.py`
already has the correction path for it (`0 = not actually an ability`), and
sorting the two apart by eye costs Grant nothing on a clip this short. That
split -- I propose positions, Grant confirms/rejects and names -- is exactly
what he asked for.

Tracking, not per-frame sampling
----------------------------------
A raw per-frame scan produces one row per frame an object is visible, which is
the same over-counting `label_dynamic.py`'s `diversify()` exists to fix -- an
ability sitting on screen for 8 seconds at 150ms steps is ~53 near-duplicate
detections of ONE thing. This clusters consecutive detections into TRACKS
instead: a detection within `TRACK_PX` of an open track's last position
extends it; a track with no matching detection for more than `TRACK_GAP_MS`
closes (one missed frame should not end a track -- the icon did not vanish,
the detector just missed a frame, the same reasoning `KF_MIN_OBS` and thin-track
handling use elsewhere in this project). Each finished track becomes ONE
candidate row, timestamped at its FIRST observation, carrying `n_observations`
(frames it was seen) and `duration_ms` so a one-frame flicker
(`--persist-min`) can be told from something that was actually placed.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_temporal import usable, drawn                        # noqa: E402

STORE = Path.home() / "reticle-store"

#: Same radius `label_dynamic.py`'s onset check uses for "is this the same object".
TRACK_PX = 10
#: Bridge this much missed detection before closing a track. Generous relative
#: to `step_ms` so one or two dropped frames (occlusion, a brief unreadable
#: frame) do not fracture one placement into several candidates.
TRACK_GAP_MS = 600


def scan(sid, step_ms=150, persist_min=2, colour=None):
    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    ok_area = md.searchable(labels, static=static)
    floor = labels != md.VOID
    lo_gray, hi_gray = md.load_two_state(sid)
    if lo_gray is None:
        print("  no two-state reference in this geometry (built before "
              "2026-08-27) -- falling back to single-reference detection; "
              "border/box-edge false positives are more likely")
    else:
        sgray, hi_gray = lo_gray.astype(np.int16), hi_gray.astype(np.int16)

    cap = cv2.VideoCapture(src["path"])
    n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_ms = n_frames / fps * 1000.0

    open_tracks: list = []
    closed: list = []
    n_unreadable = 0
    t = 0.0
    while t < duration_ms:
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            break
        crop = fr[my0:my1, mx0:mx1]
        dets = []
        if usable(crop, floor) and drawn(crop, sgray, floor):
            dets = [d for d in md.detect(crop, sgray, ok_area, md.DIFF_MIN,
                                         static_gray2=hi_gray)
                    if not colour or d["colour"] == colour]
        else:
            n_unreadable += 1

        matched = set()
        for tr in open_tracks:
            best, best_d = None, TRACK_PX
            for i, d in enumerate(dets):
                if i in matched:
                    continue
                dist = float(np.hypot(d["xy"][0] - tr["x"], d["xy"][1] - tr["y"]))
                if dist <= best_d:
                    best, best_d = i, dist
            if best is not None:
                matched.add(best)
                tr["x"], tr["y"] = dets[best]["xy"]
                tr["t_last"] = t
                tr["n"] += 1

        still_open = []
        for tr in open_tracks:
            (closed if t - tr["t_last"] > TRACK_GAP_MS else still_open).append(tr)
        open_tracks = still_open

        for i, d in enumerate(dets):
            if i not in matched:
                open_tracks.append({"x": d["xy"][0], "y": d["xy"][1],
                                    "t0": t, "t_last": t, "n": 1, "rep": d})
        t += step_ms
    closed += open_tracks
    cap.release()

    if n_unreadable:
        print(f"  {n_unreadable} of {int(duration_ms // step_ms) + 1} sampled frames "
              f"unreadable (minimap not drawn / not usable there)")

    out = []
    for tr in closed:
        if tr["n"] < persist_min:
            continue
        d = tr["rep"]
        bw, bh = d["box"][2], d["box"][3]
        out.append({
            "session_id": sid, "t_ms": round(tr["t0"]),
            "x": int(d["xy"][0]), "y": int(d["xy"][1]),
            "roi": [mx0, my0, mx1, my1],
            "colour": d["colour"], "colour_frac": round(d["colour_frac"], 3),
            "area": d["area"], "box": list(d["box"]),
            "diff_min": md.DIFF_MIN,
            "aspect": round(max(bw, bh) / max(1, min(bw, bh)), 2),
            "n_observations": tr["n"],
            "duration_ms": round(tr["t_last"] - tr["t0"]),
            "kind": "ability",
            "uncertain": False,
            "by": "claude",
        })
    out.sort(key=lambda r: r["t_ms"])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--step-ms", type=int, default=150,
                    help="how densely to sample the clip")
    ap.add_argument("--persist-min", type=int, default=2,
                    help="drop a track seen in fewer than this many sampled frames")
    ap.add_argument("--colour", default=None,
                    help="only keep blobs of this colour, e.g. 'none'; default keeps all, "
                         "since a controlled clip may show a team-coloured controlled ability")
    ap.add_argument("--dry-run", action="store_true",
                    help="scan and report, but do not write the candidate file")
    args = ap.parse_args()

    rows = scan(args.session, step_ms=args.step_ms, persist_min=args.persist_min,
                colour=args.colour)
    print(f"{len(rows)} candidate objects found "
          f"(n_observations {min((r['n_observations'] for r in rows), default=0)}-"
          f"{max((r['n_observations'] for r in rows), default=0)})")
    if args.dry_run:
        return 0

    out_path = STORE / "labels" / "ability_candidates" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
                        encoding="utf-8")
    print(f"wrote {out_path} -- run label_ability.py {args.session} to review and name them")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
