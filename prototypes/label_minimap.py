"""Hand-label enemy ICONS on the minimap, to ground-truth the icon finder.

    .\\.venv\\Scripts\\python.exe prototypes\\label_minimap.py <session> [--n 300]

Controls
--------
    left click        mark an ENEMY icon -- the red ring with the facing triangle
    shift+left click  mark a QUESTION-MARK icon -- an enemy last seen there,
                      shown for a while after vision is lost. Its own class on
                      purpose; see below.
    ctrl+left click   mark a red thing that is NOT an enemy at all: an X death
                      mark, a Reyna blind, a Cypher cam, a warning ping. These
                      are the confounders the finder has to reject, and marking
                      them is what turns "it fired" into "it fired on what".
    right click       undo the last mark
    SPACE or D        save and advance
    N                 no enemy icon on this minimap, and advance
    U                 uncertain -- recorded, kept out of scoring
    A                 back a frame
    Q / ESC           save and quit

Why question marks are not just "other red"
-------------------------------------------
A `?` icon is still a red RING -- around a question-mark glyph rather than a
portrait -- so it may well seal, which means the finder will fire on it. Filed
as a confounder every one of those becomes a false positive; filed as an enemy
they inflate recall with enemies nobody can currently see. A separate class
defers that choice to scoring time instead of baking it in at labelling time,
and the choice differs by use: a proof gate wants only enemies visible NOW
(a `?` means vision was LOST, so an on-screen enemy carries a solid icon, not a
`?`), while bearing and exposure work wants the stale position too.

It is also the distinction the project already leans on -- "an enemy visible now,
one seen five seconds ago, and one never seen are three different decisions" --
and the `?` is the only thing in the capture that separates the middle case. One
of the ten adversarial counterexamples to the premise was exactly a `?` for a
revealed-but-not-visible enemy.

The full frame is shown beside the minimap deliberately. The question a
pre-kill frame answers is not only "where is the icon" but "is there one at
all", and that judgement needs to see whether an enemy was actually on screen.

Why the pool is mostly pre-kill
-------------------------------
Grant's call, and it is right for this measurement: at a killfeed kill an enemy
provably existed, so those frames are the only ones where "no icon" is a real
finding rather than an absence of enemies. Everything measured so far foundered
on not having that denominator -- the screen detector was tried as the anchor and
turned out to be firing on Ascent's purple foliage and a magenta weapon skin.

**But a pre-kill-only set cannot be falsified**, which is the same trap recorded
under "the trap is gating on outcome": if every frame contains an enemy, a
detector that always says yes scores 100%. So `--prekill-frac` defaults to 0.70
and the remaining 30% are uniform over active play, as the control. Report both
or neither.

Two known biases in the pre-kill pool, neither fixable here, both worth stating
when the numbers are quoted:

* it is the EASY end. A kill usually means a close, clearly-visible enemy, so
  icon recall measured here is a ceiling, not a typical case;
* the killfeed timestamps when the entry APPEARS, which lags the kill. The
  sampling window is 0-600 ms before that, so it straddles the kill itself --
  some frames will be just after, where the enemy is dead and the icon is gone.
  Those are `N` and are correct as `N`.

A wider window is NOT better here, and the first version got it wrong. At
300-1400 ms most frames landed before the enemy had come into view at all --
Grant, after labelling: the enemy is often only in view 400 ms or less before
the kill. Frames like that are `N` for a reason that has nothing to do with the
minimap, and counting them made the icon look absent when the enemy was.
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
from reticle.checks import track_entries                          # noqa: E402
from reticle.profiles import get_profile                          # noqa: E402

STORE = Path.home() / "reticle-store"


def sample_times(sid: str, n: int, prekill_frac: float) -> list[tuple[float, str]]:
    spans = pq.read_table(next((STORE / "l2" / "spans").rglob(f"session={sid}/spans.parquet")))
    active = [(a, b) for a, b, s in zip(spans.column("t_start_ms").to_pylist(),
                                        spans.column("t_end_ms").to_pylist(),
                                        spans.column("state").to_pylist()) if s == "active"]
    hud = pq.read_table(next((STORE / "l1" / "hud").rglob(f"session={sid}/hud.parquet")))
    t = hud.column("t_ms").to_pylist()
    div = lambda c: hud.column(c).to_pylist() if c in hud.column_names else None
    kills = [e["t_first"] for e in track_entries(t, hud.column("kf_kill_mask").to_pylist(),
                                                 div("kf_kill_wx")) if e["counted"]]
    rng = random.Random(17)
    out: list[tuple[float, str]] = []
    want_pk = int(n * prekill_frac)
    if kills:
        per = max(1, round(want_pk / len(kills)))
        for k in kills:
            for _ in range(per):
                # TIGHT, and close to the entry. The killfeed lags the kill, so
                # this window straddles the kill rather than preceding it.
                #
                # The first version used 300-1400 ms and was too early. Grant,
                # after labelling 96 frames: the enemy is often only in view 400
                # ms or less before the kill. So most of that window held no
                # enemy yet, and the 42% of pre-kill frames with no icon read as
                # premise counterexamples when they were nothing of the kind.
                # A pool meant to guarantee an enemy is present has to sit on
                # the duel, not on the approach to it.
                out.append((k - rng.uniform(0, 600), "prekill"))
    out = out[:want_pk]
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
    import base64
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--zoom", type=float, default=1.9, help="minimap magnification")
    ap.add_argument("--prekill-frac", type=float, default=0.70)
    ap.add_argument("--max-width", type=int, default=1850,
                    help="total window width; the minimap keeps its zoom "
                         "and the context frame takes what is left")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    r = next(x for x in prof.rois if x.name == "minimap")
    MX0, MY0 = int(r.x0 * W), int(r.y0 * H)
    MX1, MY1 = int(r.x1 * W), int(r.y1 * H)

    out_path = STORE / "labels" / "minimap" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        for line in out_path.read_text().splitlines():
            if line.strip():
                done.add(round(json.loads(line)["t_ms"]))

    times = [(t, k) for t, k in sample_times(args.session, args.n, args.prekill_frac)
             if args.redo or round(t) not in done]
    if not times:
        print("every sampled frame for this session is already labelled")
        return 0
    npk = sum(1 for _, k in times if k == "prekill")
    print(f"{len(done)} already labelled, {len(times)} to go "
          f"({npk} prekill, {len(times)-npk} uniform control)")

    cap = cv2.VideoCapture(str(src["path"]))
    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "pts": [], "img": None, "written": 0, "uncertain": False}

    root = tk.Tk()
    root.title("reticle - click enemy icons on the minimap")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")

    def show():
        t_ms, pool = times[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            advance(+1, record_first=False)
            return
        mini = cv2.resize(frame[MY0:MY1, MX0:MX1], None, fx=args.zoom, fy=args.zoom,
                          interpolation=cv2.INTER_NEAREST)
        mh, mw = mini.shape[:2]
        # The context frame gets whatever width is LEFT, not a height matched to
        # the minimap. Matching heights made the window 2520 px wide -- off the
        # side of a 1080p screen -- and the minimap is the panel whose
        # magnification actually matters, so it keeps its zoom and the context
        # shrinks. Top-aligned, padded to the minimap's height.
        avail = max(240, args.max_width - mw)
        fs = min(avail / frame.shape[1], mh / frame.shape[0])
        full = cv2.resize(frame, None, fx=fs, fy=fs, interpolation=cv2.INTER_AREA)
        pane = np.zeros((mh, full.shape[1], 3), np.uint8)
        pane[:full.shape[0]] = full
        view = np.hstack([mini, pane])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        # Only the left panel takes clicks, so say so on the image itself --
        # the right one is context for the "is there an icon at all" call and
        # clicking it does nothing, which reads as broken if unlabelled.
        canvas.create_line(mw, 0, mw, mh, fill="#404040", width=2)
        canvas.create_text(8, 10, anchor="nw", fill="#40ff40",
                           font=("Consolas", 12, "bold"), text="CLICK HERE")
        canvas.create_text(mw + 8, 10, anchor="nw", fill="#808080",
                           font=("Consolas", 12), text="context only - not clickable")
        for (px, py, kind) in state["pts"]:
            col = {"enemy": "#ff2020", "question": "#ffd020"}.get(kind, "#20c0ff")
            canvas.create_oval(px - 13, py - 13, px + 13, py + 13, outline=col, width=2)
        s = int(t_ms) // 1000
        n_e = sum(1 for m in state["pts"] if m[2] == "enemy")
        n_q = sum(1 for m in state["pts"] if m[2] == "question")
        n_o = len(state["pts"]) - n_e - n_q
        status.config(
            text=f"  {state['i']+1}/{len(times)}   {s//60}:{s%60:02d}   [{pool}]   "
                 f"enemy={n_e} question={n_q} other-red={n_o}   "
                 f"click=enemy  shift=question-mark  ctrl=other red  rclick=undo   "
                 f"SPACE=next  N=none  U=unsure  A=back  Q=quit")

    def record():
        t_ms, pool = times[state["i"]]
        fh.write(json.dumps({
            "session_id": args.session,
            "t_ms": round(t_ms),
            "pool": pool,
            "uncertain": bool(state["uncertain"]),
            # Stored in MINIMAP-CROP pixels at original resolution, so the zoom
            # is free to change and the ROI is recorded alongside.
            "roi": [MX0, MY0, MX1, MY1],
            "marks": [{"x": round(px / args.zoom), "y": round(py / args.zoom),
                       "kind": kind} for px, py, kind in state["pts"]],
        }) + chr(10))
        fh.flush()
        state["written"] += 1

    def advance(step, record_first=True):
        if record_first:
            record()
        state["pts"] = []
        state["uncertain"] = False
        state["i"] += step
        if not (0 <= state["i"] < len(times)):
            finish()
            return
        show()

    def finish():
        fh.close()
        cap.release()
        print(f"wrote {state['written']} labelled frames to {out_path}")
        root.destroy()

    def click(e, kind):
        # Clicks only count on the minimap panel; the frame beside it is context.
        if e.x < int((MX1 - MX0) * args.zoom):
            state["pts"].append((e.x, e.y, kind))
            show()

    canvas.bind("<Button-1>", lambda e: click(e, "enemy"))
    canvas.bind("<Shift-Button-1>", lambda e: click(e, "question"))
    canvas.bind("<Control-Button-1>", lambda e: click(e, "other_red"))
    canvas.bind("<Button-3>", lambda e: (state["pts"] and state["pts"].pop(), show()))
    root.bind("<space>", lambda e: advance(+1))
    root.bind("d", lambda e: advance(+1))
    root.bind("n", lambda e: (state["pts"].clear(), advance(+1)))
    root.bind("u", lambda e: (state.__setitem__("uncertain", True), advance(+1)))
    root.bind("a", lambda e: advance(-1, record_first=False))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)

    show()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
