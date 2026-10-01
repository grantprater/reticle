r"""Ask the player what each ringed red thing is on a 331 px minimap, and which enemy.

    .\.venv\Scripts\python.exe prototypes\label_enemy_lane_331.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_enemy_lane_331.py

No "?", X or enemy-identity labels exist at 331 px. `enemy_lane_score.py
--queue331` sampled drawn frames of c40d950031bb, 223d636bf8d2 and
bfad2778a372 uniformly (crop cache, no decode), took every red opportunity,
froze every prototype's call on it (`calls.json`, which this tool never
reads) and drew the queue (`queue.json`): a uniform stratum plus one stratum
per call. All three files sit in the store's `labels/enemy_lane_331_20260930/`.

**Prepare** writes one panel per queued item into `patches/`: the thing
ringed at 12x, a strip of the same place from 1 s before to 1 s after (a "?"
follows an icon, an X stays), and the whole widget with the place ringed.
Lossless crops of the cached minimap ROI; the item's stratum is not drawn.

**Ask.** First the class of the RINGED thing:

    1 enemy icon    2 red X (death mark)   3 red "?" (last known)
    4 danger ping   5 ability glyph        6 red map, barrier or floor
    7 other         0 nothing there        U unsure (kept out of scoring)

After 1, which enemy: the digit of one of that match's enemy five, listed
from the stored lineup (`reticle.lineup.load_lineup`), `9` another agent,
`U` unsure of the agent. `A` goes back one item (re-answer; the last row for
a key wins); `Q` or `ESC` saves and quits. Rows append to the store's
`labels/enemy_lane_331_20260930.jsonl`, flushed per row; a restart skips
answered keys. Never seed this file.
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

TOOL = "label-enemy-lane-331-0.1.0"
CLASS_SET = "enemy_lane_331-1"
SET = "enemy_lane_331_20260930"
STORE = Path.home() / "reticle-store"
CLASSES = {"1": "enemy_icon", "2": "x_mark", "3": "question", "4": "danger_ping",
           "5": "ability_glyph", "6": "red_map", "7": "other", "0": "nothing"}
STRIP_MS = (-1000.0, -500.0, 0.0, 500.0, 1000.0)
ZH, ZF = 20, 12          # the main panel: 41 px at 12x
SH, SF = 16, 5           # each strip frame: 33 px at 5x
CF = 1.4                 # the context panel's zoom


def labels_path(store: Path) -> Path:
    return store / "labels" / f"{SET}.jsonl"


def set_dir(store: Path) -> Path:
    return store / "labels" / SET


def load_answers(p: Path) -> dict:
    done = {}
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done[r["key"]] = r
    return done


def _zoom(crop, x, y, h, f):
    pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT)
    xi, yi = int(round(x)), int(round(y))
    t = cv2.resize(pad[yi:yi + 2 * h + 1, xi:xi + 2 * h + 1], None, fx=f, fy=f,
                   interpolation=cv2.INTER_NEAREST)
    c = (int((h + 0.5 + x - xi) * f), int((h + 0.5 + y - yi) * f))
    return t, c


def compose(frames: dict, t: float, x: float, y: float, sc: float) -> np.ndarray:
    """Main zoom, the time strip and the context, one image; the ring marks the place."""
    ring = 11.0 * sc
    main, c = _zoom(frames[t], x, y, ZH, ZF)
    cv2.circle(main, c, int(ring * ZF), (0, 255, 0), 2)
    strip = []
    for dt in STRIP_MS:
        fr = frames.get(dt)
        if fr is None:
            tile = np.zeros(((2 * SH + 1) * SF, (2 * SH + 1) * SF, 3), np.uint8)
        else:
            tile, cc = _zoom(fr, x, y, SH, SF)
            cv2.circle(tile, cc, int(ring * SF), (0, 255, 0), 1)
        cv2.putText(tile, f"{dt / 1000:+.1f}s", (3, 14), 0, 0.45, (0, 0, 0), 3)
        cv2.putText(tile, f"{dt / 1000:+.1f}s", (3, 14), 0, 0.45, (255, 255, 255), 1)
        strip.append(tile)
    strip = np.hstack(strip)
    ctx = cv2.resize(frames[t], None, fx=CF, fy=CF, interpolation=cv2.INTER_AREA)
    cv2.circle(ctx, (int(x * CF), int(y * CF)), int(ring * CF * 1.6), (0, 255, 0), 2)
    left_h = main.shape[0] + strip.shape[0]
    left_w = max(main.shape[1], strip.shape[1])
    left = np.zeros((left_h, left_w, 3), np.uint8)
    left[:main.shape[0], :main.shape[1]] = main
    left[main.shape[0]:, :strip.shape[1]] = strip
    H = max(left_h, ctx.shape[0])
    out = np.full((H, left_w + 12 + ctx.shape[1], 3), 18, np.uint8)
    out[:left_h, :left_w] = left
    out[:ctx.shape[0], left_w + 12:] = ctx
    return out


def prepare(store: Path) -> int:
    import icon_portrait_gate as gate_
    from reticle.minimap import widget_scale
    d = set_dir(store)
    index = {it["key"]: it for it in json.loads((d / "index.json").read_text(encoding="utf-8"))["items"]}
    queue = json.loads((d / "queue.json").read_text(encoding="utf-8"))
    (d / "patches").mkdir(exist_ok=True)
    lites = {}
    out = []
    for n, q in enumerate(queue["items"]):
        it = index[q["key"]]
        sid = it["session"]
        s = lites.get(sid) or lites.setdefault(sid, gate_.Lite(sid))
        want = {dt: it["t_ms"] + dt for dt in STRIP_MS}
        T = s.cache_t
        snap = {}
        for dt, tw in want.items():
            k = int(np.argmin(np.abs(T - tw)))
            if abs(T[k] - tw) <= 70.0:
                snap[dt] = float(T[k])
        got = dict(s.crops(sorted(set(snap.values()))))
        frames = {dt: got[tc] for dt, tc in snap.items() if tc in got}
        frames[it["t_ms"]] = frames.get(0.0)
        if frames[it["t_ms"]] is None:
            print("no frame for", q["key"])
            continue
        img = compose(frames, it["t_ms"], it["x"], it["y"], widget_scale(frames[0.0].shape[1]))
        name = f"{n:03d}.png"
        cv2.imwrite(str(d / "patches" / name), img)
        out.append({"key": q["key"], "session": sid, "t_ms": it["t_ms"], "x": it["x"], "y": it["y"],
                    "patch": name})
    lineups = queue["enemy_lineups"]
    (d / "ask.json").write_text(json.dumps({"items": out, "enemy_lineups": lineups}, indent=1),
                                encoding="utf-8")
    print(f"{len(out)} panels in {d / 'patches'}")
    return 0


def ask(args, store: Path) -> int:
    import tkinter as tk
    d = set_dir(store)
    blob = json.loads((d / "ask.json").read_text(encoding="utf-8"))
    items, lineups = blob["items"], blob["enemy_lineups"]
    target = Path(args.labels) if args.labels else labels_path(store)
    done = load_answers(target)
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

    def names(c):
        lu = lineups.get(c["session"]) or {}
        return sorted(set(lu.get("named", [])) | set(lu.get("rivals", [])))

    def show():
        if st["i"] >= len(todo):
            root.quit()
            return
        c = todo[st["i"]]
        img = cv2.imread(str(d / "patches" / c["patch"]), cv2.IMREAD_COLOR)
        ok, png = cv2.imencode(".png", img)
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        canvas.configure(width=img.shape[1], height=img.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        head = f"{st['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f}s\n"
        if st["stage"] == "class":
            status.configure(text=head + (
                "What is the RINGED thing?  1 enemy icon  2 red X  3 red ?  4 danger ping  "
                "5 ability glyph\n6 red map/barrier/floor  7 other  0 nothing there   "
                "U unsure   A back   Q/ESC quit"))
        else:
            opts = "  ".join(f"{i + 1} {n}" for i, n in enumerate(names(c)))
            status.configure(text=head + f"Which enemy?  {opts}\n9 another agent   U unsure of the agent   "
                                         "A back to the class")

    def write(answer, agent=None, agent_answer=None, uncertain=False):
        c = todo[st["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"], "x": c["x"], "y": c["y"],
               "answer": answer, "agent": agent, "agent_answer": agent_answer,
               "uncertain": uncertain, "by": args.by, "class_set": CLASS_SET, "tool": TOOL,
               "compared_against_derived": False,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        st["i"] += 1
        st["stage"] = "class"
        show()

    def key(e):
        k = e.char
        if st["stage"] == "class":
            if k in CLASSES:
                if CLASSES[k] == "enemy_icon":
                    st["stage"] = "agent"
                    show()
                else:
                    write(CLASSES[k])
            elif k in ("u", "U"):
                write("unsure", uncertain=True)
            elif k in ("a", "A"):
                st["i"] = max(0, st["i"] - 1)
                show()
            elif k in ("q", "Q"):
                root.quit()
            return
        ns = names(todo[st["i"]])
        if k.isdigit() and 1 <= int(k) <= len(ns):
            write("enemy_icon", ns[int(k) - 1], "named")
        elif k == "9":
            write("enemy_icon", None, "not_listed")
        elif k in ("u", "U"):
            write("enemy_icon", None, "unsure")
        elif k in ("a", "A"):
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
        for n, c in enumerate(args.smoke.split(",")):
            root.after(300 * (n + 1), lambda c=c: key(_E(c)))
        root.after(300 * (len(args.smoke.split(",")) + 2), root.quit)
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
