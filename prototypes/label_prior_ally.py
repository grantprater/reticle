r"""Blind labels for the ally track-window re-search: is a teammate under the ring?

    .\.venv\Scripts\python.exe prototypes\label_prior_ally.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_prior_ally.py

`prototypes/ally_prior_search.py` recovers ally icons the reader missed by
searching near each lost teammate's last fit with a relaxed test. Its sheets
show both real teammates and fits on floor, lobes and glyphs; only the
player can say which, so this asks him, blind.

`--prepare` samples three kinds of item, about 60 in all, split over the two
sessions, and shuffles them together:

* ``recovered`` -- fits the re-search recovered (`recovered-<sid>.jsonl` in
  `analysis/prior-ally-20260929/`);
* ``ordinary`` -- icons the reader itself kept (stored `ally_icon` rows at
  ally-icon-0.4.0, barriers excluded), from the same population of frames;
* ``control`` -- a place with no teammate: on a frame whose icon count
  equals the roster's alive allies less one (every teammate is drawn
  elsewhere), where a teammate track stood about two seconds earlier, at
  least `CONTROL_CLEAR_PX` from every icon and the self icon now. An old
  track position looks like the places the re-search searches, so a control
  is not trivially empty floor.

The player never sees which kind an item is: every item draws the same ring,
of the nominal icon radius rather than the fit's, at the asked place in
three panels (-0.5 s, the asked instant, +0.5 s) from the minimap crop cache
(no decode). The kind lives only in `index.json`.

Keys (the repo's labeller orthodoxy):

    1  a TEAMMATE's icon is under the ring (stacked with another counts)
    0  NO teammate under the ring: floor, a lobe, a glyph, the player's own icon
    7  something else worth a note (an enemy, an ability); counted as not a teammate
    U  unsure -- recorded, kept OUT of scoring
    left-click on the middle panel   mark the teammate's centre (optional)
    right-click                      undo the centre mark
    A  back one      Q / ESC  save and quit

Answers append to `labels/prior_ally/<session>.jsonl`, one row per answer;
the last row for a key wins, so `A` then a new answer corrects. Nothing is
seeded: the file holds only what the player answered. The answers are
scored by `prototypes/prior_ally_eval.py`. Unwired (`"wire":
"no"`, task `prior-ally-20260929` in the store's `notes/predictions.jsonl`).
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ[_k] = "1"

import argparse  # noqa: E402
import json  # noqa: E402
import random  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

import cv2  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ally_prior_search as aps  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

KIND = "prior_ally"
CLASS_SET = "prior_ally-1"
BATCH = "blind-20260929"
CLASSES = {"1": "teammate", "0": "not_teammate", "7": "other"}
#: Items per session and kind: 2 x (12 + 9 + 9) = 60.
PER_SESSION = {"recovered": 12, "ordinary": 9, "control": 9}
CONTROL_CLEAR_PX = 30.0
CONTROL_BACK_MS = 2000.0
RING = (70, 240, 250)
HALF, ZOOM = 34, 5
OFFSETS = (-500.0, 0.0, 500.0)


def out_dir(store_root: Path) -> Path:
    return store_root / "labels" / KIND / BATCH


def label_path(store_root: Path, sid: str) -> Path:
    return store_root / "labels" / KIND / f"{sid}.jsonl"


def load_answers(store_root: Path, sids) -> dict:
    """Last row for a key wins."""
    out = {}
    for sid in sids:
        p = label_path(store_root, sid)
        if p.is_file():
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    out[r["key"]] = r
    return out


def _population(s: aps.Session):
    pop, _under = aps.split(s, 1.0)
    return pop


def sample_session(s: aps.Session, rng: random.Random) -> list[dict]:
    sid = s.sid
    items = []
    rec_path = aps.OUT / f"recovered-{sid}.jsonl"
    rec = [json.loads(line) for line in rec_path.read_text(encoding="utf-8").splitlines()
           if line.strip()]
    for r in rng.sample(rec, min(PER_SESSION["recovered"], len(rec))):
        items.append({"session_id": sid, "kind": "recovered", "t_ms": r["t_ms"],
                      "x": r["fit"]["cx"], "y": r["fit"]["cy"],
                      "source": {"entity_id": r["entity_id"], "fit": r["fit"],
                                 "dt_s": r["dt_s"], "rests_on": r["rests_on"]}})
    pop = _population(s)
    frame_of = {f["frame_idx"]: f for f in s.frames}
    with_icons = [p for p in pop if s.icons.get(p["frame_idx"])]
    for p in rng.sample(with_icons, PER_SESSION["ordinary"]):
        i = rng.choice(s.icons[p["frame_idx"]])
        items.append({"session_id": sid, "kind": "ordinary", "t_ms": p["t_ms"],
                      "x": i["cx"], "y": i["cy"],
                      "source": {"observation_key": i["observation_key"]}})
    # Controls: an exact frame, at a teammate's place two seconds before, now clear.
    times = [f["t_ms"] for f in s.frames]
    exact = [p for p in pop if p["icons"] == p["capacity"] and p["capacity"] > 0]
    rng.shuffle(exact)
    got = 0
    for p in exact:
        if got >= PER_SESSION["control"]:
            break
        j = int(np.searchsorted(times, p["t_ms"] - CONTROL_BACK_MS))
        if j >= len(times) or abs(times[j] - (p["t_ms"] - CONTROL_BACK_MS)) > 100:
            continue
        back = s.frames[j]
        if s.round_of(back["t_ms"]) != p["round_no"]:
            continue
        now = s.icons.get(p["frame_idx"], [])
        me = frame_of[p["frame_idx"]]["self"]
        pts = [(i["cx"], i["cy"]) for i in now] + [(me[0], me[1])]
        cands = [i for i in s.icons.get(back["frame_idx"], [])
                 if not aps._near(i["cx"], i["cy"], pts, CONTROL_CLEAR_PX)]
        if not cands:
            continue
        i = rng.choice(cands)
        items.append({"session_id": sid, "kind": "control", "t_ms": p["t_ms"],
                      "x": i["cx"], "y": i["cy"],
                      "source": {"from_observation": i["observation_key"],
                                 "back_ms": CONTROL_BACK_MS}})
        got += 1
    return items


def panel(crop: np.ndarray, x: float, y: float, asked: bool, t_ms: float, sc: float):
    x0, y0 = int(x) - HALF, int(y) - HALF
    pad = cv2.copyMakeBorder(crop, HALF, HALF, HALF, HALF, cv2.BORDER_CONSTANT)
    patch = pad[y0 + HALF:y0 + 3 * HALF, x0 + HALF:x0 + 3 * HALF]
    big = cv2.resize(patch, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
    cv2.circle(big, (int((x - x0) * ZOOM), int((y - y0) * ZOOM)), int(11 * sc * ZOOM),
               RING, 2, cv2.LINE_AA)
    if asked:
        big = cv2.copyMakeBorder(big[3:-3, 3:-3], 3, 3, 3, 3, cv2.BORDER_CONSTANT, value=RING)
    bar = np.full((26, big.shape[1], 3), 30 if asked else 20, np.uint8)
    cv2.putText(bar, ("ASKED" if asked else "context") + f"  {t_ms / 1000:+.1f}s",
                (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                RING if asked else (170, 170, 170), 1, cv2.LINE_AA)
    cv2.line(bar, (big.shape[1] - 10 * ZOOM - 8, 13), (big.shape[1] - 8, 13), (220, 220, 220), 2)
    return np.vstack([bar, big]), (x0, y0)


def prepare(args, store: Store) -> int:
    d = out_dir(store.root)
    if (d / "index.json").is_file() and not args.force:
        raise SystemExit(f"{d / 'index.json'} exists; --force rebuilds it (answers keep their keys)")
    d.mkdir(parents=True, exist_ok=True)
    rng = random.Random(args.seed)
    items = []
    for sid in aps.SESSIONS:
        s = aps.Session(sid, store)
        px = aps.Pixels(s, store)
        mine = sample_session(s, rng)
        want = sorted({it["t_ms"] + o for it in mine for o in OFFSETS})
        crops = {t: c for t, _tc, c in px.crops(want)}
        # Context panels need only be near their instant; the asked one is exact.
        for it in mine:
            panels, layout = [], []
            for o in OFFSETS:
                t = it["t_ms"] + o
                c = crops.get(t)
                if c is None:
                    tc = px.nearest(t)
                    if tc is None and o == 0.0:
                        break
                    if tc is None:
                        continue
                    c = next((cc for _t, _tc, cc in px.crops([tc])), None)
                    if c is None:
                        continue
                img, (x0, y0) = panel(c, it["x"], it["y"], o == 0.0, o, px.sc)
                panels.append(img)
                layout.append({"offset_ms": o, "x0": x0, "y0": y0, "asked": o == 0.0})
            if not any(lay["asked"] for lay in layout):
                continue
            h = max(p.shape[0] for p in panels)
            panels = [cv2.copyMakeBorder(p, 0, h - p.shape[0], 6, 6, cv2.BORDER_CONSTANT,
                                         value=(18, 18, 18)) for p in panels]
            it["image_layout"] = [{**lay, "left": sum(p.shape[1] for p in panels[:k]) + 6,
                                   "top": 26}
                                  for k, lay in enumerate(layout)]
            it["key"] = f"{it['session_id']}|{it['t_ms']:.1f}|{it['x']:.1f}|{it['y']:.1f}"
            items.append({**it, "image_img": np.hstack(panels)})
    rng.shuffle(items)
    index = []
    for k, it in enumerate(items):
        name = f"{k:03d}.png"
        cv2.imwrite(str(d / name), it.pop("image_img"))
        index.append({**it, "image": name, "item": k})
    (d / "index.json").write_text(json.dumps(index, indent=1), encoding="utf-8")
    counts = {}
    for it in index:
        counts[it["kind"]] = counts.get(it["kind"], 0) + 1
    print(f"prepared {len(index)} items {counts} -> {d}")
    return 0


def ask(args, store: Store) -> int:
    import base64
    import tkinter as tk

    d = out_dir(store.root)
    index = json.loads((d / "index.json").read_text(encoding="utf-8"))
    sids = sorted({it["session_id"] for it in index})
    done = load_answers(store.root, sids)
    todo = [it for it in index if it["key"] not in done]
    print(f"{len(index)} items, {len(done)} answered, {len(todo)} left")
    if not todo:
        print("nothing left to label")
        return 0
    handles = {}
    state = {"i": 0, "mark": None}
    root = tk.Tk()
    root.title("is a teammate under the ring?")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left")
    status.pack(fill="x")
    keep = {}

    def asked_panel(it):
        return next(p for p in it["image_layout"] if p["asked"])

    def show():
        if state["i"] >= len(todo):
            root.quit()
            return
        it = todo[state["i"]]
        raw = (d / it["image"]).read_bytes()
        keep["img"] = tk.PhotoImage(data=base64.b64encode(raw))
        canvas.delete("all")
        canvas.configure(width=keep["img"].width(), height=keep["img"].height())
        canvas.create_image(0, 0, image=keep["img"], anchor="nw")
        state["mark"] = None
        status.configure(
            text=f"item {state['i'] + 1}/{len(todo)}   is a TEAMMATE's icon under the ring "
                 f"in the ASKED panel?\n"
                 "1 teammate   0 no teammate   7 other   U unsure   "
                 "click centre (optional)   right-click undo   A back   Q quit")

    def click(ev):
        it = todo[state["i"]]
        p = asked_panel(it)
        w = 2 * HALF * ZOOM
        if not (p["left"] <= ev.x < p["left"] + w and p["top"] <= ev.y < p["top"] + w):
            return
        cx = p["x0"] + (ev.x - p["left"]) / ZOOM
        cy = p["y0"] + (ev.y - p["top"]) / ZOOM
        state["mark"] = (round(cx, 1), round(cy, 1))
        canvas.delete("mark")
        canvas.create_line(ev.x - 9, ev.y, ev.x + 9, ev.y, fill="#ff40ff", width=2, tags="mark")
        canvas.create_line(ev.x, ev.y - 9, ev.x, ev.y + 9, fill="#ff40ff", width=2, tags="mark")

    def undo(_ev):
        state["mark"] = None
        canvas.delete("mark")

    def answer(name):
        it = todo[state["i"]]
        sid = it["session_id"]
        if sid not in handles:
            p = label_path(store.root, sid)
            p.parent.mkdir(parents=True, exist_ok=True)
            handles[sid] = p.open("a", encoding="utf-8")
        mark = state["mark"]
        # The item's kind is not written: the label is the player's answer to
        # the place, and the index says what the place was.
        row = {"key": it["key"], "session_id": sid, "t_ms": it["t_ms"], "x": it["x"],
               "y": it["y"], "answer": name,
               "centre": {"x": mark[0], "y": mark[1]} if mark else None,
               "by": args.by, "class_set": CLASS_SET, "batch": BATCH}
        handles[sid].write(json.dumps(row) + "\n")
        handles[sid].flush()
        state["i"] += 1
        show()

    for key, name in CLASSES.items():
        root.bind(key, lambda _e, n=name: answer(n))
    for key in ("u", "U"):
        root.bind(key, lambda _e: answer("unsure"))
    for key in ("a", "A"):
        root.bind(key, lambda _e: (state.update(i=max(0, state["i"] - 1)), show()))
    for key in ("q", "Q", "<Escape>"):
        root.bind(key, lambda _e: root.quit())
    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    show()
    root.mainloop()
    for h in handles.values():
        h.close()
    print("wrote " + ", ".join(str(label_path(store.root, s)) for s in handles))
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--seed", type=int, default=29)
    ap.add_argument("--by", default="player")
    args = ap.parse_args(argv)
    aps._idle()
    store = Store(args.store)
    return prepare(args, store) if args.prepare else ask(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
