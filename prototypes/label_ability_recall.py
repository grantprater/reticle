r"""Mark every ability-made thing on the minimap: the truth for ability recall.

    .\.venv\Scripts\python.exe prototypes\label_ability_recall.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_ability_recall.py --block 1

Stage 4 of `docs/ABILITY_DETECTION.md` (section 10). The frames are fixed in
advance by `tools\ability_recall.py --select` (every 20th live 2 Hz sample of
two matches per widget size, in blocks). This tool asks the player to mark
EVERY ability-made thing on each frame: icons, rings, beams and lines, areas
and smokes, of both sides. `tools\ability_recall.py` scores the stored
streams against the answers.

**The player never sees a proposal.** Recall measured against what we showed
would be recall of our own proposals, so the frame is the raw minimap crop
from the crop cache, nearest-neighbour zoomed, with nothing drawn on it but
the player's own marks (`H` hides those too). No stream is read.

**Prepare** (`--prepare`) writes each selected frame's crop, and the cached
crops nearest 0.5 s before and after it, as lossless PNGs of the minimap ROI
into the store's `labels/ability_recall_20260930/crops/<sid>/`. It reads the
minimap crop cache and decodes no capture.

Controls
--------
    1-6          the kind the next clicks mark (sticky; shown below):
                 1 icon   2 ring   3 line or beam   4 area   5 smoke   6 unsure
    left click   mark one thing of the current kind: an icon, ring or area
                 at its CENTRE, a line anywhere along it
    right click  undo the last mark
    T            type a free-text name for the last mark (optional)
    SPACE / D    save the marks and advance (needs at least one mark)
    N            nothing here: no ability-made thing on this frame, advance
                 (a claim, never a default; refused while marks are placed)
    U            unsure of the whole frame: recorded, kept out of scoring
    A            back one frame (its saved marks come back to edit)
    , and .      show the crop 0.5 s before / after (marks are refused there)
    /            back to the frame itself
    = and -      zoom in / out
    H            hide or show your own marks
    Q / ESC      quit (the frame on screen is not saved unless answered)

Rows append to the store's `labels/ability_recall_20260930/<sid>.jsonl`,
flushed per row; the last row for a time wins, and a restart resumes at the
first unanswered frame. Marks are in minimap-crop pixels (the profile's
minimap ROI), the coordinates the ability streams store. Never seed this
file.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.ability_recall import (KINDS, SESSIONS, SET, load_answers,  # noqa: E402
                                  load_selection, set_dir)

TOOL = "label-ability-recall-0.1.0"
STORE = Path.home() / "reticle-store"
#: The neighbours shown on `,` and `.`, ms from the frame; a cached crop
#: within NEIGHBOUR_TOL of the asked time serves.
NEIGHBOURS = {"m": -500.0, "p": 500.0}
NEIGHBOUR_TOL = 70.0
COLOURS = {"icon": "#ffe040", "ring": "#40e0ff", "line": "#ff40ff", "area": "#ff9020",
           "smoke": "#e0e0e0", "unsure": "#ff3030"}


def crop_path(store: Path, sid: str, index: int, which: str = "0") -> Path:
    return set_dir(store) / "crops" / sid / f"{index:03d}_{which}.png"


def prepare(store: Path) -> int:
    from reticle.minimap import minimap_roi_px
    from reticle.profiles import get_profile
    from reticle.roi_cache import RoiCache
    from reticle.store import Store
    st = Store(str(store))
    for w, ss in SESSIONS.items():
        for sid, _blk in ss:
            sel = load_selection(store, sid)
            if sel is None:
                print(f"{sid}: no selection; run tools\\ability_recall.py --select")
                continue
            man = st.read_manifest(sid)
            profile = get_profile(man["source_profile"])
            wh = (int(man["source"]["width"]), int(man["source"]["height"]))
            box = minimap_roi_px(profile, *wh)
            if [int(v) for v in box] != sel["roi"]:
                raise SystemExit(f"{sid}: the minimap ROI moved since the selection")
            cache, why = RoiCache.load(store, man, profile, "minimap")
            if cache is None:
                raise SystemExit(f"{sid}: no minimap crop cache ({why}); never decode")
            held = np.asarray(cache.holds(), float)
            want = {}
            for f in sel["frames"]:
                want[(f["index"], "0")] = float(f["t_ms"])
                for k, dt in NEIGHBOURS.items():
                    j = int(np.argmin(np.abs(held - (f["t_ms"] + dt))))
                    if abs(held[j] - (f["t_ms"] + dt)) <= NEIGHBOUR_TOL:
                        want[(f["index"], k)] = float(held[j])
            times = sorted(set(want.values()))
            got = {}
            x0, y0, x1, y1 = box
            for smp in cache.samples(times, rois=("minimap",)):
                got[float(smp.t_ms)] = smp.frame[y0:y1, x0:x1].copy()
            d = crop_path(store, sid, 0).parent
            d.mkdir(parents=True, exist_ok=True)
            n = 0
            for (i, k), t in want.items():
                if t in got:
                    cv2.imwrite(str(crop_path(store, sid, i, k)), got[t])
                    n += 1
            miss = [i for (i, k), t in want.items() if k == "0" and t not in got]
            print(f"{sid}: {n} crops -> {d}" + (f"; frames missing: {miss}" if miss else ""))
    return 0


def queue(store: Path, block: int, only: str | None) -> list[dict]:
    out = []
    for w, ss in SESSIONS.items():
        for sid, blk in ss:
            if blk != block or (only and sid != only):
                continue
            sel = load_selection(store, sid)
            if sel is None:
                continue
            for f in sel["frames"]:
                out.append({**f, "session_id": sid, "widget_px": sel["widget_px"],
                            "roi": sel["roi"], "block": blk})
    return out


def ask(args, store: Path) -> int:
    import tkinter as tk
    from tkinter import simpledialog
    items = queue(store, args.block, args.session)
    if not items:
        print(f"no selected frames for block {args.block}")
        return 1
    labels_dir = Path(args.labels) if args.labels else set_dir(store)
    labels_dir.mkdir(parents=True, exist_ok=True)
    answers = {sid: load_answers(labels_dir / f"{sid}.jsonl")
               for sid in {it["session_id"] for it in items}}
    done = lambda it: float(it["t_ms"]) in answers[it["session_id"]]
    start = next((i for i, it in enumerate(items) if not done(it)), None)
    n_done = sum(done(it) for it in items)
    print(f"block {args.block}: {len(items)} frames, {n_done} answered -> {labels_dir}")
    if start is None:
        print("every frame of this block is answered")
        return 0
    handles = {}
    st = {"i": start, "marks": [], "kind": "icon", "zoom": float(args.zoom), "view": "0",
          "hide": False, "msg": ""}
    keep = {}
    root = tk.Tk()
    root.title("mark every ability-made thing on the minimap")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#101010", cursor="tcross")
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left", anchor="w")
    status.pack(fill="x")

    def item():
        return items[st["i"]]

    def load_marks():
        a = answers[item()["session_id"]].get(float(item()["t_ms"]))
        st["marks"] = [dict(m) for m in (a.get("marks") or ())] if a else []

    def show():
        it = item()
        p = crop_path(store, it["session_id"], it["index"], st["view"])
        img = cv2.imread(str(p), cv2.IMREAD_COLOR)
        if img is None:
            if st["view"] != "0":
                st["msg"] = "no cached crop there"
                st["view"] = "0"
                return show()
            raise SystemExit(f"missing crop {p}; run --prepare")
        z = st["zoom"]
        big = cv2.resize(img, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        ok, png = cv2.imencode(".png", big)
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        canvas.configure(width=big.shape[1], height=big.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        if not st["hide"]:
            for n, m in enumerate(st["marks"]):
                cx, cy = (m["x"] + 0.5) * z, (m["y"] + 0.5) * z
                col = COLOURS[m["kind"]]
                canvas.create_oval(cx - 7, cy - 7, cx + 7, cy + 7, outline=col, width=2)
                canvas.create_text(cx + 10, cy - 10, anchor="sw", fill=col,
                                   font=("Consolas", 9, "bold"),
                                   text=f"{n + 1}{m['kind'][0]}" + (f" {m['name']}" if m.get("name") else ""))
        if st["view"] != "0":
            canvas.create_text(8, 8, anchor="nw", fill="#ff4040", font=("Consolas", 12, "bold"),
                               text=f"{'-' if st['view'] == 'm' else '+'}0.5 s  (press / to mark)")
        a = answers[it["session_id"]].get(float(it["t_ms"]))
        prev = "" if a is None else f"   saved: {a['answer']}"
        counts = " ".join(f"{k}={sum(m['kind'] == k for m in st['marks'])}" for k in KINDS
                          if any(m["kind"] == k for m in st["marks"]))
        s = int(it["t_ms"]) // 1000
        status.configure(text=(
            f"{st['i'] + 1}/{len(items)}  {it['session_id']} ({it['widget_px']} px)  "
            f"round {it['round_no']}  {s // 60}:{s % 60:02d}{prev}\n"
            f"KIND: {st['kind'].upper():7s}  marks: {len(st['marks'])} {counts}   {st['msg']}\n"
            "1 icon  2 ring  3 line/beam  4 area  5 smoke  6 unsure   click=mark (centre; a line "
            "anywhere)  rclick=undo  T=name last\n"
            "SPACE/D save+next  N nothing here  U unsure frame  A back  , . -/+0.5 s  / frame  "
            "= - zoom  H hide marks  Q/ESC quit"))
        st["msg"] = ""

    def write(answer):
        it = item()
        sid = it["session_id"]
        row = {"session_id": sid, "t_ms": it["t_ms"], "index": it["index"],
               "round_no": it["round_no"], "block": it["block"], "widget_px": it["widget_px"],
               "roi": it["roi"], "answer": answer,
               "marks": st["marks"] if answer == "marks" else [],
               "by": args.by, "tool": TOOL, "set": SET,
               "shown": "raw minimap crop from the crop cache, nearest-neighbour zoom, no proposals",
               "compared_against_derived": False,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if sid not in handles:
            handles[sid] = (labels_dir / f"{sid}.jsonl").open("a", encoding="utf-8")
        handles[sid].write(json.dumps(row) + "\n")
        handles[sid].flush()
        answers[sid][float(it["t_ms"])] = row
        go(+1)

    def go(step):
        st["i"] += step
        st["view"] = "0"
        if st["i"] >= len(items):
            print("end of block")
            root.quit()
            return
        st["i"] = max(0, st["i"])
        load_marks()
        show()

    def click(e):
        if st["view"] != "0":
            st["msg"] = "marks go on the frame itself: press /"
            return show()
        z = st["zoom"]
        st["marks"].append({"x": round(e.x / z - 0.5, 1), "y": round(e.y / z - 0.5, 1),
                            "kind": st["kind"], "name": None})
        show()

    def undo(_e):
        if st["marks"]:
            st["marks"].pop()
        show()

    digits = {str(i + 1): k for i, k in enumerate(KINDS)}

    def key(e):
        k = (e.char or "").lower()
        if k in digits:
            st["kind"] = digits[k]
        elif k in (" ", "d"):
            if not st["marks"]:
                st["msg"] = "no marks: press N if nothing is here"
            else:
                return write("marks")
        elif k == "n":
            if st["marks"]:
                st["msg"] = "marks are placed: undo them first, or SPACE to save"
            else:
                return write("nothing")
        elif k == "u":
            return write("unsure")
        elif k == "a":
            return go(-1)
        elif k == "t":
            if st["marks"]:
                name = simpledialog.askstring("name", "name for the last mark (blank for none)",
                                              parent=root)
                st["marks"][-1]["name"] = (name or "").strip() or None
        elif k == ",":
            st["view"] = "m"
        elif k == ".":
            st["view"] = "p"
        elif k == "/":
            st["view"] = "0"
        elif k in ("=", "+"):
            st["zoom"] = min(4.0, st["zoom"] + 0.5)
        elif k == "-":
            st["zoom"] = max(1.0, st["zoom"] - 0.5)
        elif k == "h":
            st["hide"] = not st["hide"]
        elif k == "q":
            return root.quit()
        show()

    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    root.bind("<Key>", key)
    root.bind("<Escape>", lambda _e: root.quit())
    root.protocol("WM_DELETE_WINDOW", root.quit)
    load_marks()
    show()
    if args.smoke:
        # A test run into a scratch --labels directory: keys, or c:X,Y clicks
        # in crop pixels, separated by ';'.
        class _E:
            def __init__(self, c="", x=0, y=0):
                self.char, self.x, self.y = c, x, y
        steps = args.smoke.split(";")
        for n, s in enumerate(steps):
            if s.startswith("c:"):
                x, y = (float(v) for v in s[2:].split(","))
                ev = lambda x=x, y=y: click(_E(x=(x + 0.5) * st["zoom"], y=(y + 0.5) * st["zoom"]))
            else:
                ev = lambda s=s: key(_E(c=s))
            root.after(200 * (n + 1), ev)
        root.after(200 * (len(steps) + 2), root.quit)
    root.mainloop()
    root.destroy()
    for h in handles.values():
        h.close()
    print(f"answers in {labels_dir}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--block", type=int, default=1, help="which block to label (1, then 2)")
    ap.add_argument("--session", help="label one session of the block only")
    ap.add_argument("--zoom", type=float, default=2.0)
    ap.add_argument("--by", default="player")
    ap.add_argument("--labels", help="a scratch answers directory, for a test run")
    ap.add_argument("--smoke", help="';'-separated keys and c:X,Y clicks, with --labels only")
    args = ap.parse_args(argv)
    if args.smoke and not args.labels:
        raise SystemExit("--smoke writes only to a scratch --labels directory")
    store = Path(args.store)
    if args.prepare:
        return prepare(store)
    return ask(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
