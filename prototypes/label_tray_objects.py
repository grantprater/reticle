r"""Ask the player which minimap object each of their own ability casts made.

    .\.venv\Scripts\python.exe prototypes\label_tray_objects.py label [--n 120]
    .\.venv\Scripts\python.exe prototypes\label_tray_objects.py score

Why. Minimap ability references cannot be mined from tray casts
automatically: binding a cast to the nearest new blob picked up enemy icons,
question marks, site letters and bare map (task `tray-cast-minimap-abilities`,
refuted). The cast itself is sound evidence of WHICH ability and WHEN; what the
binding lacked is WHERE. The player supplies that with a click.

Sample. The player's own tray drops (`ability_hud.casts` via
`prototypes/tray_suspect_reasons.py`'s work cache, no decode) that the death
gate keeps: live phase, before the player's death in that round, and not
suspect once suspicion is recomputed among the surviving drops (`gated`). A
suppressed tray [domain:hud/suppression-indicators] or a spectated kit
[domain:hud/tray-after-player-death] is what the gate is there to keep out.
Round-robin over (agent, slot) so one agent's signature does not swamp the
rest, in a fixed hashed order; `--n` caps it.

What it shows. The whole minimap at native size in a 2x2 grid, from the
lossless 15 Hz minimap cache: 1.0 s before the tray drop, at it, 1.5 s and
3.0 s after. The whole map, not a crop round the player, because some
objects are placed from a map view far from the caster
[domain:abilities/clove-ruse-targeting-view]. The drop is sampled every
0.5 s, so the cast lies in the half second before it. The legend names the
agent, the slot and the ability; nothing about any detector's answer is shown.

Controls (click tool orthodoxy):
    left click     mark the object this cast made, in any panel. The player
                   (2026-09-26) traced each shape with several marks: the
                   inner edge of an area (Regrowth, Recon Bolt) or along a
                   line (one Hunter's Fury blast per panel). So marks are edge
                   points, not one mark per object; a consumer fits a shape
                   per panel (`tray-object-labels` outcome)
    right click    undo the last mark
    SPACE / D      save the marks and advance
    N              nothing this cast made appears on the minimap
    0              not a cast of mine (the tray misread; suppression can empty
                   it and pass the gate, a1a995e6b19b 1805.5 s), advance
    U              unsure, kept out of scoring
    A              back one      Q / ESC   save and quit

Labels go to `<store>/labels/tray_object/<session>.jsonl`, one row per
answer, the last row for a key winning; marks are minimap pixels with the
panel's time. The tool resumes where it stopped. Predictions and outcome:
`tray-object-labels` in the store's `notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pickle
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import ability_mined_references as amr  # noqa: E402
import tray_suspect_reasons as tsr  # noqa: E402
from reticle.adjudication.weapon import ABILITY_CANONICAL_NAMES  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
KIND = "tray_object"
SLOTS = ("C", "Q", "E", "X")
#: The tray's slots in order, as the ability stems name them.
STEMS = ("Grenade", "Ability1", "Ability2", "Ultimate")
PANELS_S = (-1.0, 0.0, 1.5, 3.0)
#: The 2x2 grid of native minimaps is 970 px tall; scaled to fit a 1080p screen.
DISPLAY_SCALE = 0.85


def _label_dir() -> Path:
    d = STORE.root / "labels" / KIND
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


def _player_agent(sid: str) -> str | None:
    """The lineup owner's stored answer; `load_lineup` re-adjudicates slowly."""
    p = STORE.root / "lineups" / f"{sid}.json"
    if not p.exists():
        return None
    return (json.loads(p.read_text(encoding="utf-8")).get("player") or {}).get("agent")


def ability_name(agent: str | None, slot: str) -> str:
    """The ability in tray slot `slot` (a letter of `SLOTS`) of `agent`'s kit."""
    if agent is None:
        return f"slot {slot}"
    stem = f"{agent.replace('/', '_')}_{STEMS[SLOTS.index(slot)]}"
    return ABILITY_CANONICAL_NAMES.get(stem, f"{agent} {slot}")


def sample(n: int, work: Path = tsr.WORK) -> list[dict]:
    """Clean live casts before the player's death, round-robin over (agent, slot)."""
    by = defaultdict(list)
    for f in sorted(work.glob("*.pkl")):
        d = pickle.loads(f.read_bytes())
        agent = _player_agent(d["sid"])
        rows = [dict(r, sid=d["sid"]) for r in tsr.drops(d)]
        for r in tsr.gated(rows, live_only=True):
            if r["phase"] != "live" or r["suspect_gated"]:
                continue
            key = f"{d['sid']}:{int(round(r['t'] * 1000))}:{r['slot']}"
            by[(agent, r["slot"])].append({"key": key, "sid": d["sid"], "t": r["t"],
                                            "slot": r["slot"], "from": r["from"], "to": r["to"],
                                            "agent": agent,
                                            "ability": ability_name(agent, r["slot"])})
    for k in by:
        by[k].sort(key=lambda c: hashlib.sha1(c["key"].encode()).hexdigest())
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by.values()):
        for k in sorted(by, key=lambda k: (str(k[0]), k[1])):
            if i < len(by[k]) and len(out) < n:
                out.append(by[k][i])
        i += 1
    return out


class Panels:
    """Whole-minimap panels from the lossless cache, one session open at a time."""

    def __init__(self):
        self.sid = None

    def get(self, sid: str, t_s: float) -> tuple[np.ndarray, list[float], tuple[int, int]]:
        if sid != self.sid:
            _man, self.cache = amr.open_cache(sid)
            self.t = np.unique(np.asarray(self.cache.t_ms, float))
            self.sid = sid
        want = [self.t[np.abs(self.t - (t_s + dt) * 1000.0).argmin()] for dt in PANELS_S]
        x0, y0, x1, y1 = self.cache.rect_of("minimap")
        got = {s.t_ms: s.frame[y0:y1, x0:x1].copy()
               for s in self.cache.samples(sorted(set(want)), rois=["minimap"])}
        tiles = []
        for dt, t in zip(PANELS_S, want):
            im = got.get(float(t), np.zeros((y1 - y0, x1 - x0, 3), np.uint8))
            cv2.putText(im, f"{dt:+.1f} s", (6, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                        (255, 255, 255), 2)
            tiles.append(im)
        grid = np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])
        return grid, [float(t) for t in want], (x1 - x0, y1 - y0)


def label(n: int) -> int:
    import tkinter as tk

    items = sample(n)
    done = _labels()
    order = [i for i, c in enumerate(items) if c["key"] not in done]
    print(f"{len(items)} casts, {len(items) - len(order)} already answered; "
          f"{dict(Counter(c['ability'] for c in items))}", flush=True)
    if not order:
        return 0
    # Cut every panel set before the window opens, one session at a time.
    panels, ready = Panels(), {}
    for i in sorted(order, key=lambda i: items[i]["sid"]):
        ready[i] = panels.get(items[i]["sid"], items[i]["t"])
        print(f"\rprepared {len(ready)}/{len(order)}", end="", flush=True)
    print(flush=True)
    names = {s: Path(STORE.read_manifest(s)["source"]["path"]).name
             for s in {items[i]["sid"] for i in order}}
    root = tk.Tk()
    root.title("Click the object this cast made")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None, "marks": []}

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        c = items[order[state["k"]]]
        grid, _times, _wh = ready[order[state["k"]]]
        grid = cv2.resize(grid, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE,
                          interpolation=cv2.INTER_AREA)
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", grid)[1].tobytes()))
        state["img"], state["marks"] = img, []   # keep a reference, or Tk blanks it
        canvas.configure(width=grid.shape[1], height=grid.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, image=img, anchor="nw")
        m, s = divmod(c["t"], 60)
        info.configure(text=(
            f"{state['k'] + 1}/{len(order)}   {names[c['sid']]}   {int(m)}:{s:04.1f}   "
            f"{c['agent']}  {c['slot']}  {c['ability']}\n"
            "click the object   right-click undo   SPACE save   N nothing on the map   "
            "0 not my cast   U unsure   A back   Q quit"))

    def click(e):
        grid, times, (w, h) = ready[order[state["k"]]]
        ex, ey = e.x / DISPLAY_SCALE, e.y / DISPLAY_SCALE    # back to minimap pixels
        col, row = int(ex // w), int(ey // h)
        p = int(row * 2 + col)
        if not (0 <= col < 2 and 0 <= row < 2):
            return
        x, y = ex - col * w, ey - row * h
        oval = canvas.create_oval(e.x - 9, e.y - 9, e.x + 9, e.y + 9, outline="#ff00ff", width=2)
        state["marks"].append({"panel": p, "dt_s": PANELS_S[p], "t_ms": times[p],
                               "x": int(x), "y": int(y), "_oval": oval})

    def undo(_e):
        if state["marks"]:
            canvas.delete(state["marks"].pop()["_oval"])

    def write(cls):
        c = items[order[state["k"]]]
        marks = [{k: v for k, v in m.items() if k != "_oval"} for m in state["marks"]]
        if cls == "object" and not marks:
            return                                   # SPACE with no mark says nothing
        row = {"key": c["key"], "session_id": c["sid"], "t_drop_s": c["t"],
               "slot": c["slot"], "agent": c["agent"], "ability": c["ability"],
               "charges": [c["from"], c["to"]], "class": cls,
               "marks": marks if cls == "object" else [], "uncertain": cls == "unsure",
               "coords": "minimap roi pixels", "by": "player",
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(_label_dir() / f"{c['sid']}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        state["k"] += 1
        show()

    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    root.bind("<space>", lambda e: write("object"))
    root.bind("d", lambda e: write("object"))
    root.bind("n", lambda e: write("nothing_on_minimap"))
    root.bind("0", lambda e: write("not_my_cast"))
    root.bind("u", lambda e: write("unsure"))
    root.bind("a", lambda e: (state.update(k=max(0, state["k"] - 1)), show()))
    root.bind("q", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    root.mainloop()
    return 0


def score() -> dict:
    """What the player's casts made, per ability."""
    labs = _labels()
    per = defaultdict(Counter)
    for r in labs.values():
        per[r["ability"]][r["class"]] += 1
    out = {"answered": len(labs), "by_ability": {a: dict(c) for a, c in sorted(per.items())}}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["label", "score"])
    ap.add_argument("--n", type=int, default=120)
    a = ap.parse_args()
    raise SystemExit(label(a.n) if a.cmd == "label" else (score() and 0))
