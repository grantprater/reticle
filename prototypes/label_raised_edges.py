r"""Ask the player what each drawn line of the baked Ascent static is.

    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py label --key ascent__valorant-16x9
    .\.venv\Scripts\python.exe prototypes\label_raised_edges.py score

Why. `raised_edges.py` splits the static's lines by what lies directly beyond
them: void on one side (a wall) or plain floor on both (a raised edge, which
the player says marks a ramp or elevation change that does not affect vision
[domain:minimap/raised-edge-lines]). The rule is the player's rule of thumb,
checked at four named places only. This asks the player about every piece, so
the rule can be scored.

Sample. Every wall and raised-edge piece `raised_edges.classify` finds on the
key (default the 465 px `ascent__valorant-16x9-bigmap`), shuffled by a hash of
its signature. Nothing is seeded.

What it shows. Left: the baked static round the piece, native pixels at an
integer zoom (about 540 px across), the piece ringed by one yellow box for
every piece whatever its class, with a margin, so the line and what lies
beyond it both show. Right: the whole map at 1.5x with the same box, for
place. The derived class, the shade rungs and the shade-heaven candidates are
never shown; the candidates the piece touches are written into its row
(`heavens`, from `raised_edges.shade_heavens`) for scoring only.

Classes: 1 wall (blocks vision), 2 ramp or elevation line (vision crosses),
3 box outline, 4 heaven edge (a platform's edge), 5 other drawn mark,
0 other, U unsure (kept out of scoring). A back, Q or Esc save and quit.

Labels go to `<store>/labels/raised_edge/<key>.jsonl`, one row per answer,
the last row for a piece winning; the tool resumes where it stopped.
Predictions and outcome: `drawn-areas-edges-20260930` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import raised_edges as RE  # noqa: E402

KIND = "raised_edge"
CLASSES = {1: "wall", 2: "ramp_or_elevation_line", 3: "box_outline", 4: "heaven_edge",
           5: "other_mark", 0: "other"}
#: The left tile is about TILE_PX wide: a window of at least WINDOW_MIN px (scale 1.0) round the
#: piece, MARGIN px clear of it, at an integer zoom of at least 3 (native pixels, nearest).
TILE_PX, WINDOW_MIN, MARGIN, CTX_ZOOM = 540, 60, 14, 1.5
#: The ring's colour says nothing about the class: every piece gets the same ring.
RING = (0, 230, 255)


def _label_path(key: str) -> Path:
    d = RE.STORE / "labels" / KIND
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{key}.jsonl"


def _labels(key: str) -> dict:
    p = _label_path(key)
    out = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["piece"]] = r
    return out


def signature(key: str, p: dict) -> str:
    """A piece's stable name: its key and bounding box (the baked static does not move)."""
    return f"{key}:{p['x']},{p['y']},{p['w']},{p['h']}"


def _items(key: str) -> tuple[dict, list[dict]]:
    r = RE.classify(key)
    heavens = RE.shade_heavens(r)
    RE.annotate_pieces(r, heavens)
    items = [dict(p, piece=signature(key, p)) for p in r["pieces"] if p["cls"] in ("wall", "raised_edge")]
    items.sort(key=lambda p: hashlib.sha1(p["piece"].encode()).hexdigest())
    return r, items


def _tile(r: dict, p: dict) -> np.ndarray:
    st = r["_static"]
    h, w = st.shape[:2]
    m = int(round(MARGIN * r["scale"]))
    side = max(p["w"], p["h"]) + 2 * m
    side = max(side, int(round(WINDOW_MIN * r["scale"])))
    cx, cy = p["x"] + p["w"] // 2, p["y"] + p["h"] // 2
    x0, y0 = max(0, cx - side // 2), max(0, cy - side // 2)
    x1, y1 = min(w, x0 + side), min(h, y0 + side)
    z = max(3, TILE_PX // side)
    big = cv2.resize(st[y0:y1, x0:x1], None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
    bx0, by0 = (p["x"] - x0) * z - 5, (p["y"] - y0) * z - 5
    bx1, by1 = (p["x"] + p["w"] - x0) * z + 4, (p["y"] + p["h"] - y0) * z + 4
    cv2.rectangle(big, (bx0, by0), (bx1, by1), RING, 2)
    ctx = cv2.resize(st, None, fx=CTX_ZOOM, fy=CTX_ZOOM, interpolation=cv2.INTER_AREA)
    cv2.rectangle(ctx, (int(x0 * CTX_ZOOM), int(y0 * CTX_ZOOM)), (int(x1 * CTX_ZOOM), int(y1 * CTX_ZOOM)), RING, 2)
    H = max(big.shape[0], ctx.shape[0])
    pad = lambda a: np.vstack([a, np.zeros((H - a.shape[0], a.shape[1], 3), np.uint8)])  # noqa: E731
    return np.hstack([pad(big), np.zeros((H, 8, 3), np.uint8), pad(ctx)])


def label(key: str) -> int:
    import tkinter as tk

    r, items = _items(key)
    done = _labels(key)
    order = [p for p in items if p["piece"] not in done]
    print(f"{len(items)} pieces on {key}, {len(items) - len(order)} already answered", flush=True)
    if not order:
        return 0
    root = tk.Tk()
    root.title("What is the line in the grey box?")
    panel = tk.Label(root)
    panel.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None}

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        p = order[state["k"]]
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", _tile(r, p))[1].tobytes()))
        state["img"] = img                       # keep a reference, or Tk blanks it
        panel.configure(image=img)
        info.configure(text=(
            f"{state['k'] + 1}/{len(order)}   {key}   the line inside the grey box\n"
            "1 wall (blocks vision)   2 ramp or elevation line (vision crosses)   3 box outline\n"
            "4 heaven edge   5 other drawn mark   0 other   U unsure   A back   Q quit"))

    def write(cls):
        p = order[state["k"]]
        row = {"key": p["piece"], "piece": p["piece"], "geometry_key": key, "class": cls,
               "uncertain": cls == "unsure", "x": p["x"], "y": p["y"], "w": p["w"], "h": p["h"],
               "px": p["px"], "derived_class": p["cls"], "heavens": p["heavens"],
               "ramp_near_share": p["ramp_near_share"], "compared_against_derived": False,
               "version": RE.VERSION, "by": "player", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(_label_path(key), "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        state["k"] += 1
        show()

    for i, cls in CLASSES.items():
        root.bind(str(i), lambda e, cls=cls: write(cls))
    root.bind("u", lambda e: write("unsure"))
    root.bind("a", lambda e: (state.update(k=max(0, state["k"] - 1)), show()))
    root.bind("q", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    root.mainloop()
    return 0


def score(key: str) -> dict:
    """The player's classes against the derived wall / raised-edge split, and against touching a
    shade-heaven candidate."""
    labs = [v for v in _labels(key).values() if v["class"] != "unsure"]
    conf = defaultdict(Counter)
    heaven = defaultdict(Counter)
    for v in labs:
        conf[v["derived_class"]][v["class"]] += 1
        heaven["touches_candidate" if v["heavens"] else "no_candidate"][v["class"]] += 1
    out = {"key": key, "answered": len(labs), "derived_vs_player": {k: dict(c) for k, c in conf.items()},
           "shade_heaven_vs_player": {k: dict(c) for k, c in heaven.items()}}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["label", "score", "preview"])
    ap.add_argument("--key", default=RE.KEYS[0])
    a = ap.parse_args()
    if a.cmd == "preview":                     # write the first three tiles, for checking the page
        r, items = _items(a.key)
        RE.OUT.mkdir(parents=True, exist_ok=True)
        for p in items[:3]:
            cv2.imwrite(str(RE.OUT / f"label_preview_{p['id']}.png"), _tile(r, p))
        print(len(items), "pieces; previews in", RE.OUT)
        raise SystemExit(0)
    raise SystemExit(label(a.key) if a.cmd == "label" else (score(a.key) and 0))
