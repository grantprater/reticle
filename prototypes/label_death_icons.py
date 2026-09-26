r"""Ask the player which teammate a death-bound minimap icon shows.

    .\.venv\Scripts\python.exe prototypes\label_death_icons.py label [--n 150]
    .\.venv\Scripts\python.exe prototypes\label_death_icons.py score

Why. Minimap ally identity was scored against killfeed deaths: the one ally
segment that alone ends at a teammate's death was taken to be that teammate
(`prototypes/minimap_identity_calibration.py`). An audit by eye
(`prototypes/ally_icon_separability.py`, task `ally-icon-separability`) found
the rule often binds a neighbour's segment, an ability glyph or a map patch:
5 of 11 Deadlock build segments and none of 4 held-out ones showed Deadlock.
Every accuracy measured against those labels mixes the reader's error with
the binding's. This asks the player.

What it shows. One icon per death-bound segment -- the middle of its last
2 s, the span the binding labels -- cut from the lossless minimap cache
(`roi_cache`, set `minimap`; no decode) at 4x, the detected icon ringed. The
tile can hold more than one thing; the question is about the ringed one.

Classes (the player's, 2026-09-25): 1-4 the match's four teammates in
alphabetical order, 5 not a portrait (ability glyph, disc, map patch), 6 a
portrait but none of the four, U unsure (kept out of scoring). A back, Q or
Esc save and quit. Nothing is seeded: the victim and the reader's guess are
never shown, and the order of the four says nothing.

Sample. Death-bound segments across the 19 sessions with a lineup
(`label_units`), round-robin over victim agents so rare agents are not
swamped, in a fixed order; `--n` caps it.

Labels go to `<store>/labels/death_icon/<session>.jsonl`, one row per answer,
the last row for a key winning; the tool resumes where it stopped.
Predictions and outcome: `death-icon-labels` in the store's
`notes/predictions.jsonl`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import minimap_identity_calibration as mic  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.roi_cache import RoiCache  # noqa: E402
from reticle.store import Store  # noqa: E402

STORE = Store()
KIND = "death_icon"
ZOOM = 4
HALF = 20                      # crop half-width in minimap pixels
OTHER, NOT_PORTRAIT = "other_agent", "not_portrait"


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


def _teammates(sid: str) -> list[str]:
    lineup = load_lineup(sid, STORE.root)
    player = (lineup.get("player") or {}).get("agent")
    return sorted({r.get("agent") for r in lineup["sides"]["ally"]} - {player, None})


def sample(n: int) -> list[dict]:
    """Death-bound units, round-robin over victim agents, in a fixed order."""
    sids = sorted(p.stem for p in mic.WORK.glob("*.pkl"))
    sessions = mic.load_sessions(sids, mic.WORK)
    by_agent = defaultdict(list)
    for sid, data in sessions.items():
        for u in mic.label_units(data, Counter()):
            keys = u["keys_last"]
            u["key"] = f"{sid}:{u['segment']}:{u['death_id']}"
            u["show"] = keys[len(keys) // 2]
            # The teammates the reader scored: the lineup's allies less the
            # player. `load_lineup` re-adjudicates and takes ~27 s a call.
            u["mates"] = list(data["candidates"])
            by_agent[u["victim"]].append(u)
    for a in by_agent:
        by_agent[a].sort(key=lambda u: hashlib.sha1(u["key"].encode()).hexdigest())
    out, i = [], 0
    while len(out) < n and any(i < len(v) for v in by_agent.values()):
        for a in sorted(by_agent):
            if i < len(by_agent[a]) and len(out) < n:
                out.append(by_agent[a][i])
        i += 1
    return out


class Crops:
    """Icon crops from the minimap cache, one session open at a time."""

    def __init__(self):
        self.sid = None

    def get(self, sid: str, key: str) -> tuple[np.ndarray, dict]:
        if sid != self.sid:
            man = STORE.read_manifest(sid)
            self.cache, _ = RoiCache.load(STORE.root, man, get_profile(man["source_profile"]), "minimap")
            self.icons = {e["observation_key"]: e for e in STORE.read_events("ally_icon", sid)
                          if e.get("kind") == "icon"}
            self.sid = sid
        ic = self.icons[key]
        smp = next(iter(self.cache.samples([float(ic["t_ms"])], rois=["minimap"])))
        x0, y0, x1, y1 = self.cache.rect_of("minimap")
        mm = smp.frame[y0:y1, x0:x1]
        cx, cy, r = int(ic["cx"]), int(ic["cy"]), int(ic["r"])
        pad = cv2.copyMakeBorder(mm, HALF, HALF, HALF, HALF, cv2.BORDER_CONSTANT, value=(0, 0, 0))
        tile = pad[cy:cy + 2 * HALF + 1, cx:cx + 2 * HALF + 1]
        big = cv2.resize(tile, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
        c = (HALF * ZOOM + ZOOM // 2,) * 2
        cv2.circle(big, c, int((r + 4) * ZOOM), (255, 0, 255), 1)
        return big, ic


def label(n: int) -> int:
    import base64
    import tkinter as tk

    items = sample(n)
    done = _labels()
    order = [i for i, u in enumerate(items) if u["key"] not in done]
    print(f"{len(items)} items, {len(items) - len(order)} already answered", flush=True)
    if not order:
        return 0
    # Cut every crop before the window opens, one session at a time: loading a
    # session's icons and cache takes seconds, and the sample alternates
    # sessions, so doing it per keypress froze the window.
    crops, ready, mates = Crops(), {}, {}
    for i in sorted(order, key=lambda i: items[i]["sid"]):
        u = items[i]
        ready[i] = crops.get(u["sid"], u["show"])
        mates.setdefault(u["sid"], u["mates"])
        print(f"\rprepared {len(ready)}/{len(order)}", end="", flush=True)
    print(flush=True)
    names = {sid: Path(STORE.read_manifest(sid)["source"]["path"]).name for sid in mates}
    root = tk.Tk()
    root.title("Which teammate is the ringed icon?")
    panel = tk.Label(root)
    panel.pack()
    info = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    info.pack(fill="x")
    state = {"k": 0, "img": None}

    def show():
        if state["k"] >= len(order):
            root.destroy()
            return
        u = items[order[state["k"]]]
        big, ic = ready[order[state["k"]]]
        img = tk.PhotoImage(data=base64.b64encode(cv2.imencode(".png", big)[1].tobytes()))
        state["img"] = img                       # keep a reference, or Tk blanks it
        panel.configure(image=img)
        t = float(ic["t_ms"]) / 1000
        info.configure(text=(f"{state['k'] + 1}/{len(order)}   {names[u['sid']]}   {int(t // 60)}:{t % 60:04.1f}\n"
                             + "   ".join(f"{i + 1} {a}" for i, a in enumerate(mates[u["sid"]]))
                             + "\n5 not a portrait   6 other agent   U unsure   A back   Q quit"))

    def write(answer, cls):
        u = items[order[state["k"]]]
        ic = ready[order[state["k"]]][1]
        row = {"key": u["key"], "session_id": u["sid"], "segment": u["segment"],
               "death_id": u["death_id"], "observation_key": u["show"],
               "t_ms": ic["t_ms"], "cx": ic["cx"], "cy": ic["cy"], "r": ic["r"],
               "class": cls, "answer": answer, "uncertain": cls == "unsure",
               "teammates": mates[u["sid"]], "by": "player",
               "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with open(_label_dir() / f"{u['sid']}.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
        state["k"] += 1
        show()

    def digit(i):
        four = mates[items[order[state["k"]]]["sid"]]
        if i <= len(four):
            write(four[i - 1], "agent")
        elif i == 5:
            write(None, NOT_PORTRAIT)
        elif i == 6:
            write(None, OTHER)

    for i in range(1, 7):
        root.bind(str(i), lambda e, i=i: digit(i))
    root.bind("u", lambda e: write(None, "unsure"))
    root.bind("a", lambda e: (state.update(k=max(0, state["k"] - 1)), show()))
    root.bind("q", lambda e: root.destroy())
    root.bind("<Escape>", lambda e: root.destroy())
    show()
    root.mainloop()
    return 0


def score() -> dict:
    """How often the death binding named the teammate the player saw, and how
    often the reader's per-icon guess did, on the answered, certain items."""
    labs = [r for r in _labels().values() if not r["uncertain"]]
    sids = sorted({r["session_id"] for r in labs})
    sessions = mic.load_sessions(sids, mic.WORK)
    units = {f"{sid}:{u['segment']}:{u['death_id']}": u
             for sid, d in sessions.items() for u in mic.label_units(d, Counter())}
    bind, read, per = Counter(), Counter(), defaultdict(Counter)
    for r in labs:
        u = units.get(r["key"])
        if u is None:
            continue
        victim = u["victim"]
        seen = r["answer"] if r["class"] == "agent" else r["class"]
        ok = seen == victim
        bind["binding right" if ok else f"binding wrong: {r['class']}"] += 1
        per[victim]["right" if ok else "wrong"] += 1
        if r["class"] == "agent":
            best = sessions[r["session_id"]]["icons"].get(r["observation_key"], {}).get("best")
            read["reader right" if best == r["answer"] else "reader wrong"] += 1
    out = {"answered": len(labs), "binding": dict(bind), "reader_on_portraits": dict(read),
           "binding_by_victim": {a: dict(c) for a, c in sorted(per.items())}}
    print(json.dumps(out, indent=1))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=("label", "score"))
    ap.add_argument("--n", type=int, default=150)
    a = ap.parse_args()
    sys.exit(label(a.n) if a.cmd == "label" else (score() and 0))
