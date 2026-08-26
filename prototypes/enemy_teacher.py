"""TEACHER: recover the enemy from the TRACK, not from the frame.

    .\\.venv\\Scripts\\python.exe prototypes\\enemy_teacher.py <session> [--n 0]

The shipped detector answers "is this blob an enemy" from one frame, forward
only. Nothing in this project runs alongside the game -- the whole fifteen-
session library is under three hours at 23.6 ms/frame -- so it is paying the
hardest version of the problem for no reason. An enemy that is a 21 px sliver at
*t* was a 400 px unambiguous body somewhere in its own track.

So: propose at a deliberately permissive point (`PERMISSIVE`: area 8, no shape
gates, no fragmentation cut, ~5% precision on its own), link the proposals into
tracks, and decide per TRACK. A track containing one shipped-quality detection
is an enemy for its whole life, including the frames where it is six pixels of
gun barrel. That is evidence the frame does not have and it costs nothing at
detection time, because it is only ever run offline.

This directly targets the largest adjudicated recall class -- the six Lotus
misses that survive every colour gate with 6-76 pixels and then fail
`AREA >= 120`. Lowering that floor globally floods false positives, which is why
the README's version of this step needs a safety net. Conditioning it on a
confident sibling in the same track is the safety net.

Evaluation window
-----------------
Every hand label is an ISOLATED frame, so a track cannot exist at one. Each
label is therefore scored inside a window decoded around it (+/-250 ms at 50 ms,
the same window the persistence measurement used), and only the CENTRE frame's
detections are scored. That keeps the numbers directly comparable to the shipped
91.3% / 41.2% and 76.2% / 42.5%, which were measured on those centre frames.

It also means these numbers are a floor rather than the teacher's real ceiling:
over a continuously decoded session a track runs for as long as the enemy is on
screen, not for eleven frames.

What this is FOR
----------------
Pseudo-labels. The two hand corpora are 454 frames and 111 enemies, which cannot
demonstrate 99% of anything; the teacher's job is to label all fifteen sessions
so a cheap student can be fitted on millions of blobs instead of 46 enemies. It
is not a shippable detector -- it decodes windows and costs multiples of
`detect()`.

Deliberately NOT here
---------------------
* **Relative motion as evidence.** Five attempts are recorded in
  `enemy_detect_eval.py` and all failed on the same defect: a broken rim's
  bounding box is mostly the scenery it encloses, so flow measures background
  against background (TP 24.8 px/s against FP 24.8). Track *existence* is used;
  track velocity is not.
* **A "near-static and long-lived means scenery" rule.** It is the obvious
  second gate and it is not applied, because the camera-compensated position of
  a fragmentary rim wanders on its own (FP median 227 px/s where static scenery
  must be ~0). Measure it before trusting it.
"""
import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import enemy_features as ef                                    # noqa: E402

STORE = Path.home() / "reticle-store"
# The window each isolated label is scored inside. Matches the persistence
# measurement so the two are comparable.
HALF_MS, STEP_MS = 250, 50
MINTRACK, TRACK_GAP, TRACK_GATE = 3, 2, 90.0
# Known-bad ground truth, per session. Keyed by session: an unqualified set
# would silently drop a legitimate frame at the same timestamp in another
# capture.
BAD_BY_SESSION = {"9acf02f98283": {29 * 60 + 54}}


def body_box(px, py):
    """The region a head click implies. Identical to the reference's, on
    purpose -- if these two ever diverge the numbers stop being comparable to
    the shipped 91.3% / 41.2%, which is the only reason to have them."""
    return (px - 55, py - 25, px + 55, py + 135)


def hits(px, py, x, y, bw, bh):
    bx0, by0, bx1, by1 = body_box(px, py)
    return not (x > bx1 or x + bw < bx0 or y > by1 or y + bh < by0)


def _world_grey(fr):
    """Grey patch for camera-motion estimation: world only.

    The HUD does not move with the camera, so including it drags the estimate
    toward zero. Which patch of world barely matters -- a wide one and a tight
    one around the crosshair gave the same answer.
    """
    h, w = fr.shape[:2]
    g = cv2.cvtColor(fr[int(0.20 * h):int(0.75 * h), int(0.15 * w):int(0.85 * w)],
                     cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, (g.shape[1] // 4, g.shape[0] // 4), interpolation=cv2.INTER_AREA)
    return np.float32(g) * cv2.createHanningWindow((g.shape[1], g.shape[0]), cv2.CV_32F)


def build_tracks(frames, per_frame):
    """Link proposals across a sequence. Returns tracks, not a filtered list.

    This is `enemy_detect_eval.track_filter()` with the filtering removed so the
    tracks themselves can be scored. Both of its load-bearing details are kept,
    and both were bugs first:

    * **gap tolerance** -- the detector fires on a real enemy in a median of 9 of
      11 samples but NOT contiguously, so extending tracks only from the
      immediately previous sample shreds one enemy into several short tracks;
    * **the camera shift is ADDED** to the prediction. Subtracting it doubles the
      error during fast pans and flattens the signal to a diagonal -- 86% of
      enemies against 84.9% of false positives, i.e. nothing at all.
    """
    greys = [_world_grey(f) for f in frames]
    shifts = [cv2.phaseCorrelate(greys[i], greys[i + 1])[0]
              for i in range(len(greys) - 1)]
    tracks = []
    for i, cur in enumerate(per_frame):
        cents = [(f["cx"], f["cy"]) for f in cur]
        taken = set()
        for t in tracks:
            last = t["pts"][-1][0]
            gap = i - last
            if gap <= 0 or gap > TRACK_GAP + 1:
                continue
            px, py = t["pts"][-1][1], t["pts"][-1][2]
            dx = sum(shifts[k][0] for k in range(last, i)) * 4
            dy = sum(shifts[k][1] for k in range(last, i)) * 4
            best, bd = None, TRACK_GATE * gap
            for j, (cx, cy) in enumerate(cents):
                if j in taken:
                    continue
                d = np.hypot(cx - (px + dx), cy - (py + dy))
                if d < bd:
                    best, bd = j, d
            if best is not None:
                taken.add(best)
                t["pts"].append((i, *cents[best]))
                t["idx"][i] = best
        for j, c in enumerate(cents):
            if j not in taken:
                tracks.append({"pts": [(i, *c)], "idx": {i: j}})
    return tracks


def teach(frames, cfg=ef.PERMISSIVE, mintrack=MINTRACK):
    """Per-frame accepted detections, decided at track level.

    A track is an enemy if ANY member passes the shipped gates. Every member is
    then accepted, which is the whole mechanism: it back-fills the frames where
    the enemy is a sliver from the frame where it plainly is not.
    """
    per_frame = [ef.propose(f, cfg) for f in frames]
    tracks = build_tracks(frames, per_frame)
    keep = [set() for _ in per_frame]
    for t in tracks:
        if len(t["pts"]) < mintrack:
            continue
        if any(ef.gate(per_frame[i][j], ef.SHIPPED) for i, j in t["idx"].items()):
            for i, j in t["idx"].items():
                keep[i].add(j)
    return [[f for j, f in enumerate(fs) if j in keep[i]]
            for i, fs in enumerate(per_frame)], per_frame


def _window_record(row, frames, per_frame, centre):
    """One labelled window, with every track and every member's features.

    Written so rule changes can be swept WITHOUT re-decoding the video -- the
    same reason `segment` recomputes spans from stored L1. A full pass is 85
    seconds per corpus, which is enough to make sweeping in-place a bad habit.

    Only the centre frame is ever scored, but the whole track is stored, because
    the entire point of the teacher is that the decision uses the other frames.
    """
    tracks = build_tracks(frames, per_frame)
    out = []
    for t in tracks:
        members = []
        for i, j in sorted(t["idx"].items()):
            f = per_frame[i][j]
            members.append({"i": i, "gated": bool(ef.gate(f, ef.SHIPPED)),
                            "box": list(f["box"]),
                            **{k: round(float(f[k]), 4)
                               for k in (*ef.FEATURES, "cx", "cy", "r_cross")}})
        out.append({"len": len(t["pts"]), "members": members,
                    "at_centre": t["idx"].get(centre)})
    return {"t_ms": row["t_ms"], "pool": row["pool"], "centre": centre,
            "marks": [{"x": m["x"], "y": m["y"], "kind": m["kind"]}
                      for m in row.get("marks", [])],
            "tracks": out}


def _score(rows, get_dets, label):
    """Recall/precision against the hand labels, scored exactly as the
    reference does: on LABELS, so a label hit by two detections survives losing
    one, and non-target marks (corpse, deployable, revealed) are consumed rather
    than counted either way."""
    st = {p: dict(tp=0, fn=0, fp=0, nt=0) for p in ("uniform", "event")}
    for r in rows:
        dets = get_dets(r)
        if dets is None:
            continue
        pool = st[r["pool"]]
        players = [(m["x"], m["y"]) for m in r.get("marks", []) if m["kind"] == "player"]
        others = [(m["x"], m["y"]) for m in r.get("marks", [])
                  if m["kind"] in ("corpse", "deployable", "revealed")]
        used = set()
        for (px, py) in players:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, *d["box"][:4])), None)
            if j is None:
                pool["fn"] += 1
            else:
                pool["tp"] += 1
                used.add(j)
        for (px, py) in others:
            j = next((j for j, d in enumerate(dets)
                      if j not in used and hits(px, py, *d["box"][:4])), None)
            if j is not None:
                used.add(j)
                pool["nt"] += 1
        pool["fp"] += len(dets) - len(used)
    t = {k: sum(s[k] for s in st.values()) for k in ("tp", "fn", "fp", "nt")}
    rec = t["tp"] / max(t["tp"] + t["fn"], 1)
    pre = t["tp"] / max(t["tp"] + t["fp"], 1)
    print(f"  {label:22s} TP {t['tp']:3d}  FN {t['fn']:3d}  FP {t['fp']:4d}  "
          f"nt {t['nt']:2d}   recall {rec*100:5.1f}%  precision {pre*100:5.1f}%")
    return rec, pre


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=0, help="limit labelled frames (0 = all)")
    ap.add_argument("--dump", help="write per-window tracks here, for rule sweeps")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    bad = BAD_BY_SESSION.get(args.session, set())
    rows = {}
    for line in (STORE / "labels" / "enemies" / f"{args.session}.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["t_ms"]] = r
    rows = [r for r in rows.values()
            if not r.get("uncertain") and r["t_ms"] // 1000 not in bad]
    rows.sort(key=lambda r: r["t_ms"])
    if args.n:
        rows = rows[:args.n]

    offs = list(range(-HALF_MS, HALF_MS + 1, STEP_MS))
    centre = offs.index(0)
    cap = cv2.VideoCapture(str(src["path"]))
    got, dumped = {}, []
    # Seek ONCE per window and read the span contiguously, taking every Nth
    # frame. Seeking is expensive in H.264 and contiguous decoding is cheap --
    # eleven seeks per label would dominate the whole run.
    step_f = max(1, int(round(STEP_MS / 1000.0 * fps)))
    span_f = step_f * (len(offs) - 1) + 1
    for n, r in enumerate(rows):
        start = int(round((r["t_ms"] - HALF_MS) / 1000.0 * fps))
        if start < 0:
            continue
        cap.set(cv2.CAP_PROP_POS_FRAMES, start)
        seq = []
        for _ in range(span_f):
            ok, fr = cap.read()
            if not ok:
                break
            seq.append(fr)
        if len(seq) < span_f:
            continue
        frames = seq[::step_f]
        kept, raw = teach(frames)
        got[r["t_ms"]] = {
            "teacher": kept[centre],
            "shipped": [f for f in raw[centre] if ef.gate(f, ef.SHIPPED)],
            "permissive": raw[centre],
        }
        if args.dump is not None:
            dumped.append(_window_record(r, frames, raw, centre))
        if (n + 1) % 25 == 0:
            print(f"  ... {n+1}/{len(rows)} frames", flush=True)
    cap.release()

    if args.dump is not None:
        with open(args.dump, "w", encoding="utf-8") as fh:
            for rec in dumped:
                fh.write(json.dumps(rec) + "\n")
        print(f"wrote {len(dumped)} windows to {args.dump}")

    tag = man["tags"][0][4:] if man.get("tags") else "?"
    print(f"\n{args.session} ({tag}): {len(got)} of {len(rows)} labelled frames, "
          f"window +/-{HALF_MS}ms at {STEP_MS}ms")
    _score(rows, lambda r: got.get(r["t_ms"], {}).get("permissive"), "propose PERMISSIVE")
    _score(rows, lambda r: got.get(r["t_ms"], {}).get("shipped"), "gate SHIPPED")
    _score(rows, lambda r: got.get(r["t_ms"], {}).get("teacher"), "TEACHER (track)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
