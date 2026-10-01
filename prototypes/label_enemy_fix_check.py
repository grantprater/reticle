r"""Ask the player what each ringed red thing is, on sessions no label file used, and whether the box holds it.

    .\.venv\Scripts\python.exe prototypes\label_enemy_fix_check.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_enemy_fix_check.py

The held-out check of the two enemy-lane fixes (task
`enemy-fix-check-20260930`). `enemy_lane_bounds.py --check-queue` sampled
drawn cache frames of five match sessions no earlier label file names, froze
both fixes' calls on every red opportunity (`calls.json`, which this tool
never reads) and drew `queue.json`. All sit in the store's
`labels/enemy_fix_check_20260930/`.

**Prepare** writes two panels per queued item into `patches/`: the class
panel of `label_enemy_lane_331.compose` (the place ringed green at 12x, a
strip from 1 s before to 1 s after, the whole widget), and the box panel (the
box fix (a) draws, magenta, beside the same zoom undrawn). Lossless crops of
the cached minimap ROI; neither panel draws the item's stratum or the gate.

**Ask.** First the class of the RINGED thing, with the keys of
`label_enemy_lane_331` plus 8:

    1 enemy icon    2 red X (death mark)   3 red "?" (last known)
    4 danger ping   5 ability glyph        6 red map, barrier or floor
    7 other         8 void (the background seen off the floor, round the map or through a hole)
    0 nothing there
    U unsure (kept out of scoring)

After 1, the box panel: does the MAGENTA circle hold the whole enemy icon,
tip included? `Y` holds it, `N` cuts it, `U` unsure of the box. `A` goes back
one item (re-answer; the last row for a key wins); `Q` or `ESC` saves and
quits. Rows append to the store's `labels/enemy_fix_check_20260930.jsonl`,
flushed per row; a restart skips answered keys. Never seed this file.
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import label_enemy_lane_331 as l331  # noqa: E402

TOOL = "label-enemy-fix-check-0.1.0"
CLASS_SET = "enemy_fix_check-1"
SET = "enemy_fix_check_20260930"
STORE = Path.home() / "reticle-store"
CLASSES = {**l331.CLASSES, "8": "void"}
BOX = {"y": "holds", "n": "cuts"}


def labels_path(store: Path) -> Path:
    return store / "labels" / f"{SET}.jsonl"


def set_dir(store: Path) -> Path:
    return store / "labels" / SET


def box_panel(crop: np.ndarray, bx: float, by: float, br: float) -> np.ndarray:
    """The fix's box (magenta) at 12x beside the same zoom undrawn."""
    drawn, c = l331._zoom(crop, bx, by, l331.ZH, l331.ZF)
    plain = drawn.copy()
    cv2.circle(drawn, c, int(round(br * l331.ZF)), (255, 0, 255), 2)
    gap = np.full((drawn.shape[0], 12, 3), 18, np.uint8)
    return np.hstack([drawn, gap, plain])


def prepare(store: Path) -> int:
    import enemy_lane_score as els
    import icon_portrait_gate as gate_
    from reticle.minimap import widget_scale
    els.below_normal()
    d = set_dir(store)
    index = {it["key"]: it for it in json.loads((d / "index.json").read_text(encoding="utf-8"))["items"]}
    queue = json.loads((d / "queue.json").read_text(encoding="utf-8"))
    # The box is the fix's drawing, shown only after the class answer; nothing else of calls.json is read.
    boxes = {k: c["box"] for k, c in json.loads((d / "calls.json").read_text(encoding="utf-8"))["calls"].items()}
    (d / "patches").mkdir(exist_ok=True)
    lites, out = {}, []
    for n, q in enumerate(queue["items"]):
        it = index[q["key"]]
        sid = it["session"]
        s = lites.get(sid) or lites.setdefault(sid, gate_.Lite(sid))
        T = s.cache_t
        snap = {}
        for dt in l331.STRIP_MS:
            k = int(np.argmin(np.abs(T - (it["t_ms"] + dt))))
            if abs(T[k] - (it["t_ms"] + dt)) <= 70.0:
                snap[dt] = float(T[k])
        got = dict(s.crops(sorted(set(snap.values()))))
        frames = {dt: got[tc] for dt, tc in snap.items() if tc in got}
        if frames.get(0.0) is None:
            print("no frame for", q["key"])
            continue
        frames[it["t_ms"]] = frames[0.0]
        sc = widget_scale(frames[0.0].shape[1])
        name = f"{n:03d}.png"
        cv2.imwrite(str(d / "patches" / name), l331.compose(frames, it["t_ms"], it["x"], it["y"], sc))
        bx = boxes[q["key"]]
        cv2.imwrite(str(d / "patches" / f"{n:03d}_box.png"), box_panel(frames[0.0], bx["x"], bx["y"], bx["r"]))
        out.append({"key": q["key"], "session": sid, "t_ms": it["t_ms"], "x": it["x"], "y": it["y"],
                    "patch": name, "box_patch": f"{n:03d}_box.png"})
    (d / "ask.json").write_text(json.dumps({"items": out}, indent=1), encoding="utf-8")
    print(f"{len(out)} items, {2 * len(out)} panels in {d / 'patches'}")
    return 0


def ask(args, store: Path) -> int:
    import tkinter as tk
    d = set_dir(store)
    items = json.loads((d / "ask.json").read_text(encoding="utf-8"))["items"]
    target = Path(args.labels) if args.labels else labels_path(store)
    done = l331.load_answers(target)
    todo = [c for c in items if c["key"] not in done]
    print(f"{len(items)} items, {len(done)} answered, {len(todo)} left -> {target}")
    if not todo:
        print("nothing left to label")
        return 0
    handle = target.open("a", encoding="utf-8")
    st = {"i": 0, "stage": "class"}
    keep = {}
    root = tk.Tk()
    root.title("what is the ringed red thing")
    canvas = tk.Canvas(root, width=1200, height=720, highlightthickness=0, bg="#121212")
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left", anchor="w")
    status.pack(fill="x")

    def show():
        if st["i"] >= len(todo):
            root.quit()
            return
        c = todo[st["i"]]
        patch = c["patch"] if st["stage"] == "class" else c["box_patch"]
        img = cv2.imread(str(d / "patches" / patch), cv2.IMREAD_COLOR)
        _ok, png = cv2.imencode(".png", img)
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        canvas.configure(width=img.shape[1], height=img.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        head = f"{st['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f}s\n"
        if st["stage"] == "class":
            status.configure(text=head + (
                "What is the RINGED thing?  1 enemy icon  2 red X  3 red ?  4 danger ping  5 ability glyph\n"
                "6 red map/barrier/floor  7 other  8 void (background, off the floor)  0 nothing there   "
                "U unsure   A back   Q/ESC quit"))
        else:
            status.configure(text=head + (
                "Does the MAGENTA circle hold the WHOLE enemy icon, tip included?  (right: the same place undrawn)\n"
                "Y holds it   N cuts it   U unsure of the box   A back to the class"))

    def write(answer, box=None, uncertain=False):
        c = todo[st["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"], "x": c["x"], "y": c["y"],
               "answer": answer, "box": box, "uncertain": uncertain, "by": args.by,
               "class_set": CLASS_SET, "tool": TOOL, "compared_against_derived": box is not None,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        st["i"] += 1
        st["stage"] = "class"
        show()

    def key(e):
        k = (e.char or "").lower()
        if st["stage"] == "class":
            if k in CLASSES:
                if CLASSES[k] == "enemy_icon":
                    st["stage"] = "box"
                    show()
                else:
                    write(CLASSES[k])
            elif k == "u":
                write("unsure", uncertain=True)
            elif k == "a":
                st["i"] = max(0, st["i"] - 1)
                show()
            elif k == "q":
                root.quit()
            return
        if k in BOX:
            write("enemy_icon", BOX[k])
        elif k == "u":
            write("enemy_icon", "unsure")
        elif k == "a":
            st["stage"] = "class"
            show()

    root.bind("<Key>", key)
    root.bind("<Escape>", lambda _e: root.quit())
    show()
    if args.smoke:
        # A test run: press the given keys in order, into a scratch file only.
        class _E:
            def __init__(self, c):
                self.char = c
        presses = args.smoke.split(",")
        for n, c in enumerate(presses):
            root.after(300 * (n + 1), lambda c=c: key(_E(c)))
        root.after(300 * (len(presses) + 2), root.quit)
    root.mainloop()
    root.destroy()
    handle.close()
    print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(STORE))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--labels", help="a scratch answers file, for a test run")
    ap.add_argument("--by", default="player")
    ap.add_argument("--smoke", help="comma-separated keys to press, with --labels only (a test run)")
    args = ap.parse_args(argv)
    if args.smoke and not args.labels:
        raise SystemExit("--smoke writes only to a scratch --labels file")
    store = Path(args.store)
    if args.prepare:
        return prepare(store)
    return ask(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
