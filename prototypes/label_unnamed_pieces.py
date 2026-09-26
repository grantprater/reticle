r"""Ask the player what the ally minimap pieces the arbiter cannot name show.

    .\.venv\Scripts\python.exe prototypes\label_unnamed_pieces.py label
    .\.venv\Scripts\python.exe prototypes\label_unnamed_pieces.py score

Why. About 2900 of 7900 stored ally round-entity pieces carry no name, only
an `identity_reason`. Claude labelled a blind sample of them
(`prototypes/unnamed_piece_grids.py`, task `unnamed-ally-pieces`) as mostly
floor fits, spike glyphs, devices and X marks, but matched only 3 of the 9
named control pieces it decided, so its answers on this population cannot
steer the ally icon detector. This asks the player.

Sample. `unnamed_piece_grids.pick_pieces`, unchanged: 30 unnamed pieces from
each refusal family and 20 named controls, shuffled together by a hash, so a
control looks like any other item.

What it shows. The piece's middle observation, cut as
`label_death_icons.Crops.get` cuts it (lossless minimap cache, no decode, 4x,
the detected icon ringed), with the match's four teammates' minimap portrait
art beneath it (`claude_icon_labels._ref_row`). The question is about the
ringed thing, not the tile. Nothing is seeded: the arbiter's name, the
refusal reason and whether the item is a control are never shown.

Classes (the player's, 2026-09-26): 1-4 the four teammates in alphabetical
order, 5 another agent's portrait, 6 bare map (nothing drawn), 7 spike,
8 ability object or device, 9 X death mark, 0 other, U unsure (kept out of
scoring). A back, Q or Esc save and quit.

Labels go to `<store>/labels/unnamed_piece/<session>.jsonl`, one row per
answer, the last row for a key winning; the tool resumes where it stopped.
Predictions and outcome: `unnamed-piece-labels` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import claude_icon_labels as C  # noqa: E402
import label_death_icons as L  # noqa: E402
import unnamed_piece_grids as G  # noqa: E402

KIND = "unnamed_piece"
#: Keys 5-9 and 0, after the four teammates on 1-4.
CLASSES = {5: "other_agent", 6: "bare_map", 7: "spike", 8: "ability_object",
           9: "x_mark", 0: "other"}


def _label_dir() -> Path:
    d = L.STORE.root / "labels" / KIND
    d.mkdir(parents=True, exist_ok=True)
    return d


def _labels() -> dict:
    out = {}
    for p in _label_dir().glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


def _tile(big: np.ndarray, mates: list[str]) -> np.ndarray:
    """The ringed crop over the teammates' portrait art."""
    return np.vstack([big, C._ref_row(mates, big.shape[1])])


def label() -> int:
    import tkinter as tk

    items = G.pick_pieces()
    done = _labels()
    order = [i for i, p in enumerate(items) if p["piece"] not in done]
    print(f"{len(items)} items, {len(items) - len(order)} already answered", flush=True)
    if not order:
        return 0
    # Cut every crop before the window opens, one session at a time: opening a
    # session's cache takes seconds, and per keypress it froze the window.
    crops, ready = L.Crops(), {}
    for i in sorted(order, key=lambda i: items[i]["sid"]):
        big, key, t = G._middle_icon_crop(crops, items[i])
        if big is not None:
            ready[i] = (_tile(big, items[i]["mates"]), key, t)
        print(f"\rprepared {len(ready)}/{len(order)}", end="", flush=True)
    print(flush=True)
    order = [i for i in order if i in ready]
    names = {s: Path(L.STORE.read_manifest(s)["source"]["path"]).name
             for s in {items[i]["sid"] for i in order}}
    root = tk.Tk()
    root.title("What is the ringed thing?")
    panel = tk.Label(root)
    panel.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None}

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        p = items[order[state["k"]]]
        tile, _key, t = ready[order[state["k"]]]
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", tile)[1].tobytes()))
        state["img"] = img                       # keep a reference, or Tk blanks it
        panel.configure(image=img)
        s = t / 1000
        info.configure(text=(
            f"{state['k'] + 1}/{len(order)}   {names[p['sid']]}   {int(s // 60)}:{s % 60:04.1f}\n"
            + "   ".join(f"{j + 1} {a}" for j, a in enumerate(p["mates"]))
            + "\n5 other agent   6 bare map   7 spike   8 ability object   9 X mark   0 other"
            + "\nU unsure   A back   Q quit"))

    def write(answer, cls):
        p = items[order[state["k"]]]
        _tile_img, key, t = ready[order[state["k"]]]
        row = {"key": p["piece"], "session_id": p["sid"], "piece": p["piece"],
               "round_no": p["round"], "observation_key": key, "t_ms": t,
               "class": cls, "answer": answer, "uncertain": cls == "unsure",
               "teammates": p["mates"], "family": p["family"],
               "round_entity_version": p["version"], "by": "player",
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(_label_dir() / f"{p['sid']}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        state["k"] += 1
        show()

    def digit(i):
        four = items[order[state["k"]]]["mates"]
        if 1 <= i <= len(four):
            write(four[i - 1], "agent")
        elif i in CLASSES:
            write(None, CLASSES[i])

    for i in range(10):
        root.bind(str(i), lambda e, i=i: digit(i))
    root.bind("u", lambda e: write(None, "unsure"))
    root.bind("a", lambda e: (state.update(k=max(0, state["k"] - 1)), show()))
    root.bind("q", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    root.mainloop()
    return 0


def score() -> dict:
    """The player's classes per refusal family, and whether each named
    control's teammate answer matches the arbiter's name."""
    labs = _labels()
    names = {}
    for sid in {r["session_id"] for r in labs.values()}:
        for e in L.STORE.read_events("round_entity", sid):
            if e.get("kind") == "entity" and e.get("family") == "ally":
                names[e["id"]] = e.get("agent")
    by, control = defaultdict(Counter), Counter()
    for r in labs.values():
        cls = "teammate" if r["class"] == "agent" else r["class"]
        by[r["family"]][cls] += 1
        if r["family"] == "NAMED" and r["class"] == "agent":
            control["match" if r["answer"] == names.get(r["piece"]) else "differ"] += 1
        elif r["family"] == "NAMED":
            control[cls] += 1
    out = {"answered": len(labs), "by_family": {f: dict(c) for f, c in sorted(by.items())},
           "named_control": dict(control)}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["label", "score"])
    a = ap.parse_args()
    raise SystemExit(label() if a.cmd == "label" else (score() and 0))
