r"""Ask the player where his own icon is when the self fit sits on the spike.

    .\.venv\Scripts\python.exe prototypes\label_prior_self.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_prior_self.py

The blind labeller for experiment 2 of docs/PRIOR_DRIVEN_READERS.md
(`prototypes/prior_self.py`, task `prior-self-20260929`). The sheets class
most runs by eye, but three kinds of frame need the player: a guard refusal
while he lives and the track stands at the glyph (did he stand on the spike,
so the refusal cost a real point?), a teardrop the guard took on the glyph
(was that him?), and runs where no icon of his shows anywhere.

About 30 items, pooled over a06f04a0059f, 5822b6646448 and 223d636bf8d2, in
a fixed random order. The stratum each came from stays in the index and never
reaches the screen, and no reader mark is drawn: the spike glyph alone is
ringed, in every panel, because it is the thing asked about.

The screen: three zooms round the glyph at -0.5 s, 0 and +0.5 s (the middle
one asked), and below them the whole widget at the asked instant.

    click   put the marker on YOUR icon in the whole widget (below)
    SPACE   save: my icon is at the marker (D does the same)
    1       my icon is ON the ringed spike: I stand on it
    S       I am dead and spectating: no icon on the widget is mine
    N       my icon is not on the widget, and I am alive (hidden, stacked)
    7       something else (escape hatch)
    U       unsure: recorded, kept out of scoring
    right-click  undo the marker
    A       back one      Q / ESC   save and quit

Answers append to `labels/prior_self/answers.jsonl`; the last row for a key
wins, and a restart skips what is answered.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import prior_self as P  # noqa: E402

KIND = "prior_self"
CLASS_SET = "prior_self-1"
SESSIONS = ("a06f04a0059f", "5822b6646448", "223d636bf8d2")
ITEMS = P.OUT / "label_items"
QUOTA = {"refused_at_glyph": 12, "refused_elsewhere": 5, "confirmed_on_glyph": 6, "run": 8}
HALF, ZOOM, FULL_W = 45, 4, 520
RING = (70, 240, 250)
SEED = 20260929


def label_path() -> Path:
    return P.STORE.root / "labels" / KIND / "answers.jsonl"


def load() -> dict:
    p = label_path()
    out = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def _pool(sid: str) -> dict[str, list[dict]]:
    """Candidate instants per stratum, from the replay and the measure."""
    head, rows = P.load_replay(sid)
    sc = head["widget_scale"]
    stored = P.run_stored(rows, sc, 1000 / 15)
    guarded = P.run_guarded(rows, sc, 1000 / 15)
    dead = P.dead_after(sid)
    m = json.loads((P.OUT / f"{sid}.measure.json").read_text(encoding="utf-8"))
    at_glyph = set(m["points"].get("lost_at_glyph_s") or [])
    out = {k: [] for k in QUOTA}
    for r, a, b in zip(rows, stored, guarded):
        if dead(r["t"]):
            continue
        g = b.get("glyph")
        if a.get("xy") is not None and b.get("xy") is None:
            k = "refused_at_glyph" if round(r["t"] / 1000) in at_glyph else "refused_elsewhere"
            out[k].append({"t_ms": r["t"], "gx": g[0], "gy": g[1]})
        elif b.get("guard") == "confirmed_on_glyph":
            out["confirmed_on_glyph"].append({"t_ms": r["t"], "gx": g[0], "gy": g[1]})
    seen = []
    for key in ("ally_cheb", "l1_owner"):
        for c in m["runs"][key]:
            if c["n"] < 5 or any(abs(c["t0_s"] - s) < 3 for s in seen):
                continue
            seen.append(c["t0_s"])
            t = (c["t0_s"] + c["t1_s"]) / 2 * 1000
            j = min(range(len(rows)), key=lambda i: abs(rows[i]["t"] - t))
            gl = rows[j].get("gl") or []
            if gl:
                out["run"].append({"t_ms": rows[j]["t"], "gx": gl[0][0], "gy": gl[0][1]})
    return out


def _item_image(crop, gx, gy, sc, asked):
    h = int(round(HALF * sc))
    pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=(30, 30, 30))
    x, y = int(round(gx)), int(round(gy))
    win = pad[y:y + 2 * h + 1, x:x + 2 * h + 1]
    z = max(2, int(round(ZOOM / sc)))
    big = cv2.resize(win, (win.shape[1] * z, win.shape[0] * z), interpolation=cv2.INTER_NEAREST)
    c = (int((gx - x + h + 0.5) * z), int((gy - y + h + 0.5) * z))
    cv2.circle(big, c, int(15 * sc * z), RING, 1, cv2.LINE_AA)
    if asked:
        big = cv2.copyMakeBorder(big[3:-3, 3:-3], 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=RING)
    return big


def prepare(n_seed: int = SEED) -> int:
    rng = random.Random(n_seed)
    items = []
    pools = {sid: _pool(sid) for sid in SESSIONS}
    for stratum, q in QUOTA.items():
        allc = [(sid, c) for sid in SESSIONS for c in pools[sid][stratum]]
        # Spread over instants: at most one item per session-second.
        by_sec = {}
        for sid, c in allc:
            by_sec.setdefault((sid, round(c["t_ms"] / 1000)), (sid, c))
        cand = sorted(by_sec.values(), key=lambda v: (v[0], v[1]["t_ms"]))
        take = cand if stratum == "run" else rng.sample(cand, min(q, len(cand)))
        print(f"  {stratum}: {len(allc)} frames, {len(cand)} seconds, taking {len(take)}")
        items += [{"session": sid, "stratum": stratum, **c} for sid, c in take]
    rng.shuffle(items)
    ITEMS.mkdir(parents=True, exist_ok=True)
    index = []
    for k, it in enumerate(items):
        sid = it["session"]
        _man, mm, _ctx = P._open(sid)
        x0, y0, x1, y1 = mm.rect_of("minimap")
        sc = P.widget_scale(x1 - x0)
        held = mm.holds()
        want = [it["t_ms"] - 500, it["t_ms"], it["t_ms"] + 500]
        ts = [min(held, key=lambda t: abs(t - w)) for w in want]
        crops = {float(s.t_ms): s.frame[y0:y1, x0:x1].copy()
                 for s in mm.samples(sorted(set(ts)), rois=["minimap"])}
        panels = [_item_image(crops[t], it["gx"], it["gy"], sc, i == 1) for i, t in enumerate(ts)]
        hh = max(p.shape[0] for p in panels)
        top = np.hstack([cv2.copyMakeBorder(p, 0, hh - p.shape[0], 6, 6, cv2.BORDER_CONSTANT,
                                            value=(18, 18, 18)) for p in panels])
        full = crops[ts[1]]
        k_full = FULL_W / full.shape[1]
        fimg = cv2.resize(full, (FULL_W, int(round(full.shape[0] * k_full))),
                          interpolation=cv2.INTER_NEAREST)
        cv2.circle(fimg, (int(it["gx"] * k_full), int(it["gy"] * k_full)),
                   int(15 * sc * k_full), RING, 1, cv2.LINE_AA)
        bottom = np.full((fimg.shape[0], top.shape[1], 3), 18, np.uint8)
        bottom[:, :fimg.shape[1]] = fimg
        img = np.vstack([top, np.full((8, top.shape[1], 3), 60, np.uint8), bottom])
        name = f"{k:03d}.png"
        cv2.imwrite(str(ITEMS / name), img)
        index.append({**it, "key": f"{sid}|{it['t_ms']:.1f}", "image": name,
                      "full_origin": [0, top.shape[0] + 8], "full_scale": k_full,
                      "widget_scale": sc})
    (ITEMS / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    print(f"prepared {len(index)} items -> {ITEMS}")
    return 0


def ask(by: str) -> int:
    import tkinter as tk

    index = json.loads((ITEMS / "index.json").read_text(encoding="utf-8"))
    done = load()
    todo = [c for c in index if c["key"] not in done]
    print(f"{len(index)} items, {len(done)} answered, {len(todo)} left")
    if not todo:
        return 0
    target = label_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a", encoding="utf-8")
    state = {"i": 0, "mark": None}
    root = tk.Tk()
    root.title("where is YOUR icon? (the spike glyph is ringed)")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left")
    status.pack(fill="x")
    keep = {}

    def show():
        if state["i"] >= len(todo):
            root.quit()
            return
        c = todo[state["i"]]
        keep["img"] = tk.PhotoImage(data=base64.b64encode((ITEMS / c["image"]).read_bytes()))
        canvas.delete("all")
        canvas.configure(width=keep["img"].width(), height=keep["img"].height())
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        state["mark"] = None
        status.configure(text=(
            f"{state['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f}s\n"
            "click your icon in the whole widget, then SPACE    1 on the spike    "
            "S dead/spectating    N not visible (alive)    7 other    U unsure    "
            "right-click undo    A back    Q quit"))

    def click(e):
        c = todo[state["i"]]
        ox, oy = c["full_origin"]
        if e.y < oy:
            return
        state["mark"] = ((e.x - ox) / c["full_scale"], (e.y - oy) / c["full_scale"])
        canvas.delete("mark")
        canvas.create_oval(e.x - 6, e.y - 6, e.x + 6, e.y + 6, outline="magenta", width=2,
                           tags="mark")

    def undo(_e):
        state["mark"] = None
        canvas.delete("mark")

    def answer(name):
        c = todo[state["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"],
               "glyph": [c["gx"], c["gy"]], "answer": name, "by": by,
               "class_set": CLASS_SET}
        if name == "here":
            if state["mark"] is None:
                return
            row["x"], row["y"] = (round(v, 1) for v in state["mark"])
        handle.write(json.dumps(row) + "\n")
        handle.flush()
        state["i"] += 1
        show()

    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    for keys, name in ((("<space>", "d", "D"), "here"), (("1",), "on_spike"),
                       (("s", "S"), "dead_spectating"), (("n", "N"), "not_visible"),
                       (("7",), "other"), (("u", "U"), "unsure")):
        for k in keys:
            root.bind(k, lambda _e, n=name: answer(n))
    for k in ("a", "A"):
        root.bind(k, lambda _e: (state.update(i=max(0, state["i"] - 1)), show()))
    for k in ("q", "Q", "<Escape>"):
        root.bind(k, lambda _e: root.quit())
    show()
    root.mainloop()
    handle.close()
    print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--by", default="player")
    a = ap.parse_args(argv)
    P.idle()
    return prepare() if a.prepare else ask(a.by)


if __name__ == "__main__":
    raise SystemExit(main())
