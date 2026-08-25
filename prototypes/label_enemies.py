"""Hand-label enemy heads on sampled frames, to ground-truth a screen-space
enemy detector.

    .\\.venv\\Scripts\\python.exe prototypes\\label_enemies.py <session> [--n 300]

Controls
--------
    left click        mark a VISIBLE enemy player's head
    ctrl+left click   mark a REVEALED enemy -- outlined through map geometry by
                      Sova recon, Fade, Skye and the like
    middle click      mark a CORPSE -- a dead body, which stays outlined
    alt+left click    mark a MUZZLE FLASH or tracer from an unseen enemy
    shift+left click  mark an enemy DEPLOYABLE (KJ turret, Cypher cage, drone)
    right click       undo the last mark on this frame
    SPACE or D   save this frame and advance
    N            mark the frame as having NO outlined enemy, and advance
    U            mark the frame UNCERTAIN and advance -- recorded, but kept out
                 of scoring. Use it whenever a call is a coin flip.
    A            go back a frame
    Q / ESC      save and quit

Muzzle flashes are recorded but are **not** part of this detector's scoring set.
A flash or tracer from an enemy you cannot see is not an outline, so the outline
detector structurally cannot find it, and counting it as a miss would penalise
the detector for something invisible to it. It is here because the frames are
being reviewed anyway and a second labelling pass costs more than a keybinding.

It is worth its own extractor later, and possibly a valuable one. A flash from a
position with no visible model is *direct evidence of an angle the player did
not account for* -- which is what the dA/ds geometry work tries to infer
indirectly. Paired with an HP drop it gives "shot from an unseen angle", about as
coachable an event as this project can produce, and it is observable in a way
enemy position is not: with nobody on the team seeing them, they are on neither
the screen nor the minimap, yet their position is inferable from the flash.

Corpses stay outlined, so they are a fourth class. Same reasoning as the others
-- the detector will find one whether or not we ask, so an unlabelled body is a
correct detection scored as a false positive -- but the consequence is sharper
here, because a corpse is a *plausible* target rather than an obvious non-target.
Crosshair placement on a body would count as target acquisition and inflate
every aim statistic, and unlike a turret it is exactly where a real enemy was a
moment ago, so the error would look reasonable.

They are worth keeping rather than merely excluding: a body marks where a death
happened, which is spatial data the killfeed has no way to give.

The rule at the moment of a kill: if the model is still standing or animating
as alive, it is an enemy; once it is ragdolling or on the ground, it is a
corpse; mid-fall is a coin flip and takes U. The killfeed timestamps can sharpen
this afterwards -- a body within a second or two of a tracked kill is certainly
a corpse -- so a few ambiguous calls here are recoverable.

**Mark the visible part, not the head.** A partly-occluded enemy -- a gun poking
out of a smoke, a shoulder past a corner -- often has no head on screen at all.
The label answers "should the detector fire here", not "where is the head", so
click whatever is actually outlined. Head-specific aim analysis needs a separate,
smaller labelling pass later, on frames where the whole model is visible; mixing
the two here would give a detector set full of phantom heads.

Only mark what is **outlined**. The detector keys on the enemy outline, so an
un-outlined object is something it structurally cannot see, and labelling one
manufactures a false negative against an impossible detection. An ability in
flight with no outline -- a Reyna blind, say -- is correctly left unmarked even
though a human can see it perfectly well.

Ambiguous frames get U, not a guess. A coin-flip label is worse than no label:
it does not average out, it moves precision or recall in whichever direction the
guess went, and nothing downstream can tell it from a confident one. Marking a
frame uncertain keeps it in the record -- so it is still distinguishable from
"not looked at" -- while excluding it from the scoring set. Expect to use this
on distant models, heavy smoke, and anything where team colour is unclear.

Revealed enemies are their own class, and they may be the most valuable of the
three. Grant's framing is that only two things change a round's shape: economy,
and what each side has learned. A recon-revealed enemy is a direct measurement
of the second -- it is what the player *knew* at the moment of a decision, and
nothing else in this pipeline can see that. A wide swing into a spot just darted
is a different decision from a blind one, and only this distinguishes them.

They must stay out of aim statistics, though: an enemy outlined through a wall
is not shootable, so counting crosshair placement on one as target acquisition
would be measuring an impossible shot. Detect, separate, use for decision
quality rather than mechanics.

There should be a visual handle on the difference. A visible enemy is a full
agent model inside its outline; a revealed one is a flat silhouette drawn over
the geometry in front of it. That is an interior-texture test -- the same shape
as every other structural test here -- but it is unproven, which is exactly why
the two get labelled apart rather than assumed separable.

Deployables are labelled, not skipped. Valorant outlines enemy *objects* in the
same colour as enemy players -- a Killjoy turret, a Cypher cage, a Sova drone --
so a detector will find them whether or not we asked it to. Leaving them
unlabelled would score a correct detection as a false positive and push the
tuning toward suppressing something the detector is right about.

They are a different class rather than the same one because they are a different
thing: a turret is a threat and a source of information, but it is not a duel
opponent, and an aim metric that counts crosshair placement on a turret as
target acquisition would be measuring nonsense. They are also easy to tell
apart once labelled -- a turret does not move, and a human silhouette is tall
and narrow where a deployable is not.

Built on tkinter rather than cv2.imshow: the project pins
opencv-python-headless, which is correct for a pipeline that never wants a
window, and swapping it for the GUI build to run one labelling tool would be the
tail wagging the dog. tkinter ships with Python and reads PNG bytes directly.

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

**The damage vignette is the confounder to watch.** Taking damage reddens the
screen edges, which is a large red region that is not an enemy -- exactly the
failure mode this codebase keeps hitting with absolute colour tests. Three
defences: it lives at the border, so a margin excludes it; it is a broad diffuse
gradient rather than a thin contour, so shape and compactness reject it; and HP
is already in L1, so the frames where it can occur are known in advance and need
no new extraction. Label those frames normally -- the detector has to cope, and
labels showing it coping or not are the point.

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
    import base64
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--scale", type=float, default=0.75)
    ap.add_argument("--redo", action="store_true",
                    help="revisit frames already labelled, to correct them. The "
                         "file is append-only and the LAST row for a timestamp "
                         "wins, so nothing is lost by relabelling.")
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

    times = [(t, k) for t, k in sample_times(args.session, args.n)
             if args.redo or round(t) not in done]
    if not times:
        print("every sampled frame for this session is already labelled")
        return 0
    print(f"{len(done)} already labelled, {len(times)} to go")

    cap = cv2.VideoCapture(str(src["path"]))
    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "pts": [], "img": None, "written": 0}

    root = tk.Tk()
    root.title("reticle - click enemy heads")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")

    def show():
        t_ms, pool = times[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t_ms / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            advance(+1, record=False)
            return
        view = cv2.resize(frame, None, fx=args.scale, fy=args.scale,
                          interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        h, w = view.shape[:2]
        canvas.config(width=w, height=h)
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        for (px, py, kind) in state["pts"]:
            col = {"player": "#ff2020", "revealed": "#ffd020",
                   "corpse": "#a060ff", "flash": "#ffffff"}.get(kind, "#20c0ff")
            canvas.create_oval(px - 11, py - 11, px + 11, py + 11, outline=col, width=2)
            canvas.create_line(px - 16, py, px + 16, py, fill=col, width=1)
            canvas.create_line(px, py - 16, px, py + 16, fill=col, width=1)
        s = int(t_ms) // 1000
        status.config(text=f"  {state['i']+1}/{len(times)}   {s//60}:{s%60:02d}   [{pool}]   "
                           f"vis={sum(1 for m in state['pts'] if m[2] == 'player')} "
                           f"rev={sum(1 for m in state['pts'] if m[2] == 'revealed')} "
                           f"dep={sum(1 for m in state['pts'] if m[2] == 'deployable')} "
                           f"corpse={sum(1 for m in state['pts'] if m[2] == 'corpse')} "
                           f"flash={sum(1 for m in state['pts'] if m[2] == 'flash')}   "
                           f"click=visible  ctrl=revealed  shift=deployable   "
                           f"mclick=corpse  alt=flash  rclick=undo  U=unsure   "
                           f"SPACE=next  N=none  A=back  Q=quit")

    def record():
        t_ms, pool = times[state["i"]]
        fh.write(json.dumps({
            "session_id": args.session,
            "t_ms": round(t_ms),
            "pool": pool,
            # stored in ORIGINAL frame pixels, so the display scale is free to change
            # kind: "player" or "deployable"; see the module docstring
            # uncertain frames stay in the record but out of any scoring set
            "uncertain": bool(state.get("uncertain")),
            "marks": [{"x": round(px / args.scale), "y": round(py / args.scale),
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

    canvas.bind("<Button-1>", lambda e: (state["pts"].append((e.x, e.y, "player")), show()))
    canvas.bind("<Shift-Button-1>",
                lambda e: (state["pts"].append((e.x, e.y, "deployable")), show()))
    canvas.bind("<Control-Button-1>",
                lambda e: (state["pts"].append((e.x, e.y, "revealed")), show()))
    canvas.bind("<Button-2>", lambda e: (state["pts"].append((e.x, e.y, "corpse")), show()))
    canvas.bind("<Alt-Button-1>", lambda e: (state["pts"].append((e.x, e.y, "flash")), show()))
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
