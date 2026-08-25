"""Hand-label enemy heads on sampled frames, to ground-truth a screen-space
enemy detector.

    .\\.venv\\Scripts\\python.exe prototypes\\label_enemies.py <session> [--n 300]

Controls
--------
    left click   mark an enemy head
    right click  undo the last mark on this frame
    SPACE or D    save this frame and advance
    N            mark the frame as having NO visible enemy, and advance
    A            go back a frame
    Z            toggle 2x zoom around the cursor, for small or distant models
    Q / ESC      save and quit

Labels append to `<store>/labels/enemies/<session>.jsonl`, one row per frame,
and the tool resumes where it left off. Every frame shown is recorded --
including the empty ones, via N -- because a detector needs negatives just as
much as positives, and "no label" cannot be distinguished from "not looked at"
after the fact.

Why frames are sampled the way they are
---------------------------------------
Uniformly random frames are mostly empty, which wastes labelling effort. But
sampling only where an enemy is *likely* -- the seconds before a kill -- builds
a set biased toward enemies that were about to die, i.e. ones already centred
and clearly visible. A detector tuned on those would look excellent and fail on
the hard cases that matter: a sliver of an enemy at the edge of a doorway.

So the default mix is half from the seconds around killfeed events and half
uniform over active play. The uniform half is what the detector should actually
be *scored* on; the killfeed half is there to make labelling worth the time.
Each row records which pool it came from so the two can be kept apart.

This is the project's first hand-labelled data. Everything else has been
validated against something the game itself reported -- the scoreboard, the
killfeed, the match history. On-screen enemies have no such anchor, which is
exactly why this file has to exist.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from reticle.checks import track_entries          # noqa: E402

STORE = Path.home() / "reticle-store"
WIN = "reticle: click enemy heads   [space] next  [N] none  [right-click] undo  [Z] zoom  [Q] quit"


def sample_times(sid: str, n: int) -> list[tuple[float, str]]:
    """Half near killfeed events, half uniform over active play. See module docs."""
    spans = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    active = [(a, b) for a, b, s in zip(spans.column("t_start_ms").to_pylist(),
                                        spans.column("t_end_ms").to_pylist(),
                                        spans.column("state").to_pylist()) if s == "active"]
    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    t = hud.column("t_ms").to_pylist()
    div = lambda c: hud.column(c).to_pylist() if c in hud.column_names else None
    events = [e["t_first"] for e in track_entries(t, hud.column("kf_kill_mask").to_pylist(),
                                                  div("kf_kill_wx")) if e["counted"]]
    events += [e["t_first"] for e in track_entries(t, hud.column("kf_death_mask").to_pylist(),
                                                   div("kf_death_wx")) if e["counted"]]
    rng = random.Random(11)
    out: list[tuple[float, str]] = []
    for e in events:                     # the 2 s before an event, where someone was on screen
        for _ in range(3):
            out.append((e - rng.uniform(200, 2200), "event"))
    total = sum(b - a for a, b in active)
    for _ in range(max(0, n - len(out))):
        x = rng.uniform(0, total)
        for a, b in active:
            if x < b - a:
                out.append((a + x, "uniform"))
                break
            x -= b - a
    rng.shuffle(out)
    return out[:n]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--scale", type=float, default=0.75)
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    out_path = STORE / "labels" / "enemies" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(round(json.loads(line)["t_ms"]))

    times = [(t, k) for t, k in sample_times(args.session, args.n) if round(t) not in done]
    if not times:
        print("every sampled frame for this session is already labelled")
        return 0
    print(f"{len(done)} already labelled, {len(times)} to go")

    cap = cv2.VideoCapture(str(src["path"]))
    state = {"pts": [], "zoom": False, "cursor": (0, 0)}

    def on_mouse(event, x, y, flags, _):
        state["cursor"] = (x, y)
        if event == cv2.EVENT_LBUTTONDOWN:
            state["pts"].append((x, y))
        elif event == cv2.EVENT_RBUTTONDOWN and state["pts"]:
            state["pts"].pop()

    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(WIN, on_mouse)

    i, written = 0, 0
    fh = out_path.open("a", encoding="utf-8")
    while 0 <= i < len(times):
        t_ms, pool = times[i]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            i += 1
            continue
        state["pts"] = []
        while True:
            view = cv2.resize(frame, None, fx=args.scale, fy=args.scale,
                              interpolation=cv2.INTER_AREA)
            for (px, py) in state["pts"]:
                cv2.drawMarker(view, (px, py), (0, 0, 255), cv2.MARKER_CROSS, 18, 2)
                cv2.circle(view, (px, py), 11, (0, 0, 255), 1, cv2.LINE_AA)
            s = int(t_ms) // 1000
            cv2.putText(view, f"{i+1}/{len(times)}  {s//60}:{s%60:02d}  [{pool}]  "
                              f"marks={len(state['pts'])}",
                        (10, 26), cv2.FONT_HERSHEY_SIMPLEX, .7, (0, 255, 255), 2, cv2.LINE_AA)
            if state["zoom"]:
                cx, cy = state["cursor"]
                h, w = view.shape[:2]
                x0, y0 = max(0, cx - 110), max(0, cy - 80)
                patch = view[y0:y0 + 160, x0:x0 + 220]
                if patch.size:
                    big = cv2.resize(patch, None, fx=2, fy=2, interpolation=cv2.INTER_NEAREST)
                    bh, bw = big.shape[:2]
                    view[h - bh:h, w - bw:w] = big
                    cv2.rectangle(view, (w - bw, h - bh), (w - 1, h - 1), (0, 255, 255), 1)
            cv2.imshow(WIN, view)
            k = cv2.waitKey(20) & 0xFF
            if k in (ord(' '), 83, ord('d')):
                rec, adv = True, +1
                break
            if k in (ord('n'), ord('N')):
                state["pts"] = []
                rec, adv = True, +1
                break
            if k in (81, ord('a')):
                rec, adv = False, -1
                break
            if k in (ord('z'), ord('Z')):
                state["zoom"] = not state["zoom"]
            if k in (ord('q'), 27):
                rec, adv = False, 0
                break
        if rec:
            fh.write(json.dumps({
                "session_id": args.session,
                "t_ms": round(t_ms),
                "pool": pool,
                "scale": args.scale,
                # stored in ORIGINAL frame pixels, so the display scale is free to change
                "heads": [[round(px / args.scale), round(py / args.scale)]
                          for px, py in state["pts"]],
            }) + "\n")
            fh.flush()
            written += 1
        if adv == 0:
            break
        i += adv
    fh.close()
    cap.release()
    cv2.destroyAllWindows()
    print(f"wrote {written} labelled frames to {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
