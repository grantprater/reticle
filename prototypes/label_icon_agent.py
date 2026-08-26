"""Say WHICH agent each already-marked minimap icon is.

    .\\.venv\\Scripts\\python.exe prototypes\\label_icon_agent.py <session> --names sage,yoru,jett,omen,killjoy

Controls
--------
    1 2 3 4 5     the agent, in the order the mined roster strip shows them
    0             a QUESTION-MARK icon -- an enemy last seen here, no portrait
    U             unsure: recorded, and kept out of scoring
    A             back one
    Q / ESC       save and quit

This is a second pass over `label_minimap.py`'s output, not a new sampling.
Every icon Grant already marked `enemy` or `question` is presented in turn,
magnified, with the frame it came from beside it -- so the ones that are too
small to call from the minimap alone can be settled by looking at the screen.

Run `minimap_portrait.py mine <session>` first. The five portraits it mines are
drawn along the bottom as the key, in slot order, and they are what the number
keys refer to -- so there is no need to know the agent names to label, only to
match a face to a face. The `--names` are for the file.

**The mined strip is MIRRORED** and the icons are not (Grant: the enemy side of
the roster flips the art so the teams face each other; the minimap and the Tab
scoreboard hold one orientation always). The key is flipped back before it is
drawn here, so what is on screen is comparable by eye.

Why this exists rather than trusting the clustering
---------------------------------------------------
The first agent labels on `a06f04a0059f` were made by clustering the icons and
reading each cluster by eye -- by me, not by Grant. That measures a matcher
adequately and settles nothing, because the labels and the descriptor share a
failure mode: any two agents the descriptor cannot separate are two agents that
would have landed in one cluster and been labelled once, and the error would be
invisible in the score. Hand labels break that loop. They are also the only way
to find out whether the `?` icons and the ally icons need classes of their own.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
from minimap_icons import floor_mask, red_mask, static_map        # noqa: E402
import minimap_ring_fit as ringfit                                # noqa: E402

STORE = Path.home() / "reticle-store"


def icons_to_label(sid):
    """Every enemy / question mark already on record, one row per icon.

    Reuses the cached ring fits where `minimap_ring_fit` left them, because the
    radius is part of what gets stored -- the descriptor is a fraction of the
    fitted radius, so a label without one cannot be turned into a descriptor
    later without re-deciding the fit.
    """
    lab = STORE / "labels" / "minimap" / f"{sid}.jsonl"
    if not lab.is_file():
        raise SystemExit(f"no minimap labels at {lab} -- run label_minimap.py first")
    rows = {}
    for line in lab.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            rows[r["t_ms"]] = r
    fits_path = STORE / "labels" / "minimap" / f"{sid}.fits.json"
    fits = json.loads(fits_path.read_text())["fits"] if fits_path.is_file() else {}
    out = []
    for t, r in sorted(rows.items()):
        if r.get("uncertain"):
            continue
        for m in r["marks"]:
            if m["kind"] not in ("enemy", "question"):
                continue
            ff = fits.get(str(t), [])
            b = min(ff, key=lambda q: np.hypot(q["cx"] - m["x"], q["cy"] - m["y"]),
                    default=None)
            if b is not None and np.hypot(b["cx"] - m["x"], b["cy"] - m["y"]) <= 16:
                out.append({"t_ms": t, "x": b["cx"], "y": b["cy"], "r": b["r"],
                            "kind": m["kind"]})
            else:
                # No cached fit near the click: keep the icon anyway, with the
                # click as the centre and the measured median radius. Dropping
                # it would quietly bias the set toward icons the finder liked,
                # which is the population the classifier least needs help on.
                out.append({"t_ms": t, "x": m["x"], "y": m["y"], "r": 9,
                            "kind": m["kind"], "unfitted": True})
    return out


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--names", required=True,
                    help="five agent names in mined roster slot order, comma separated")
    ap.add_argument("--zoom", type=int, default=14, help="icon magnification")
    ap.add_argument("--redo", action="store_true")
    args = ap.parse_args()
    names = [s.strip() for s in args.names.split(",")]

    man = json.loads((STORE / "manifests" / f"{args.session}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    MX0, MY0, MX1, MY1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)

    key_path = STORE / "rosters" / f"{args.session}.npz"
    if not key_path.is_file():
        raise SystemExit(f"no mined roster at {key_path} -- run "
                         f"minimap_portrait.py mine {args.session} first")
    z = np.load(key_path)
    # Un-mirror: the enemy side of the roster is flipped and the minimap is not,
    # so the key has to be flipped back or it is a harder comparison than it
    # needs to be.
    key = [z[f"slot{k}"][:, ::-1] for k in range(5)]

    out_path = STORE / "labels" / "minimap_agent" / f"{args.session}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    # An icon counts as done only when a PERSON labelled it. Seeding this file
    # with `claude-provisional` rows once made the labeller skip all 71 of them
    # -- they looked done -- so the only icons that reached Grant were the ones
    # the seeding had missed, and the number that came back was still scoring my
    # own clustering against itself. Provenance decides, not presence.
    done = set()
    if out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("by", "grant") == "grant":
                    done.add((r["t_ms"], r["x"], r["y"]))

    items = [i for i in icons_to_label(args.session)
             if args.redo or (i["t_ms"], i["x"], i["y"]) not in done]
    if not items:
        print("every marked icon in this session already has an agent")
        return 0
    print(f"{len(done)} already done, {len(items)} to go")

    cap = cv2.VideoCapture(src["path"])
    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "img": None, "written": 0}

    root = tk.Tk()
    root.title("reticle - which agent is this icon?")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")

    KEY_H = 88

    def show():
        it = items[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(it["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            step(+1, write=None)
            return
        crop = frame[MY0:MY1, MX0:MX1]
        p = 16
        y0, x0 = max(0, it["y"] - p), max(0, it["x"] - p)
        tile = crop[y0:it["y"] + p, x0:it["x"] + p]
        big = cv2.resize(tile, None, fx=args.zoom, fy=args.zoom,
                         interpolation=cv2.INTER_NEAREST)
        bh, bw = big.shape[:2]
        # The whole frame beside it, at whatever height the tile came out.
        # Same reasoning as label_minimap: the judgement often needs the screen,
        # not just the icon, and the icon is the panel whose zoom matters.
        fs = bh / frame.shape[0]
        full = cv2.resize(frame, None, fx=fs, fy=fs, interpolation=cv2.INTER_AREA)
        # And the minimap around the icon, so an ambiguous portrait can be
        # settled by which icon nearby it is NOT.
        ctx = cv2.resize(crop, None, fx=bh / crop.shape[0], fy=bh / crop.shape[0],
                         interpolation=cv2.INTER_NEAREST)
        view = np.hstack([big, ctx, full])
        strip = np.full((KEY_H, view.shape[1], 3), 25, np.uint8)
        for k, art in enumerate(key):
            a = cv2.resize(art, (KEY_H - 20, KEY_H - 20), interpolation=cv2.INTER_NEAREST)
            x = 10 + k * (KEY_H + 60)
            if x + a.shape[1] < strip.shape[1]:
                strip[6:6 + a.shape[0], x:x + a.shape[1]] = a
        view = np.vstack([view, strip])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        # Ring the icon in the wide minimap panel too, or "which of these is it"
        # is a guess.
        cxs = bw + it["x"] * (bh / crop.shape[0])
        cys = it["y"] * (bh / crop.shape[0])
        rr = max(10, it["r"] * (bh / crop.shape[0]) * 1.8)
        canvas.create_oval(cxs - rr, cys - rr, cxs + rr, cys + rr,
                           outline="#40ff40", width=2)
        for k, nm in enumerate(names):
            x = 10 + k * (KEY_H + 60)
            canvas.create_text(x, view.shape[0] - KEY_H + 6, anchor="nw",
                               fill="#ffd020", font=("Consolas", 13, "bold"),
                               text=f"{k+1}")
            canvas.create_text(x + KEY_H - 14, view.shape[0] - 16, anchor="nw",
                               fill="#c0c0c0", font=("Consolas", 10), text=nm)
        s = int(it["t_ms"]) // 1000
        canvas.create_text(8, 8, anchor="nw", fill="#40ff40",
                           font=("Consolas", 13, "bold"),
                           text="?" if it["kind"] == "question" else "")
        status.config(
            text=f"  {state['i']+1}/{len(items)}   {s//60}:{s%60:02d}   "
                 f"marked '{it['kind']}'   r={it['r']}"
                 f"{'  (no ring fit)' if it.get('unfitted') else ''}   "
                 f"1-5=agent  0=question-mark icon  U=unsure  A=back  Q=quit")

    def step(delta, write):
        if write is not None:
            it = items[state["i"]]
            fh.write(json.dumps({
                "session_id": args.session,
                "t_ms": it["t_ms"],
                # Minimap-crop pixels at original resolution, matching
                # label_minimap's convention, plus the fitted radius the
                # descriptor needs.
                "x": it["x"], "y": it["y"], "r": it["r"],
                "roi": [MX0, MY0, MX1, MY1],
                "marked_kind": it["kind"],
                "agent": write if write not in ("__unsure__",) else None,
                "uncertain": write == "__unsure__",
            }) + chr(10))
            fh.flush()
            state["written"] += 1
        state["i"] += delta
        if not (0 <= state["i"] < len(items)):
            finish()
            return
        show()

    def finish():
        fh.close()
        cap.release()
        print(f"wrote {state['written']} agent labels to {out_path}")
        root.destroy()

    for k in range(5):
        root.bind(str(k + 1), lambda e, k=k: step(+1, names[k]))
    root.bind("0", lambda e: step(+1, "question"))
    root.bind("u", lambda e: step(+1, "__unsure__"))
    root.bind("a", lambda e: step(-1, None))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)

    show()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
