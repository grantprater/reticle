r"""Say what the SELF reader actually locked onto.

    .\.venv\Scripts\python.exe prototypes\label_self_fit.py c40d950031bb --prepare
    .\.venv\Scripts\python.exe prototypes\label_self_fit.py c40d950031bb

Reviewed clips on 2026-09-10 showed the self fit sitting on the spike icon,
drifting through it onto a teammate, and settling on a teammate across a
buy-menu widget absence. The step law cannot catch that -- it rejects
implausible SPEED, and a spike at the player's feet is a fraction of a pixel
away. Nothing in the store witnesses a dropped spike, so there is no channel to
cross-reference and the rate has to be labelled.

The population is the reader's own ACCEPTED fits, not refused frames: the
question is how often an answer is the wrong object. Two strata are sampled and
recorded -- `crowded`, another read icon within 25 px, and `clear` -- so a rate
over all accepted fits can be reweighted afterwards. Sampling only crowded
frames would measure the interesting case and call it the average.

Classes follow `label_dynamic.py`, split where this question needs it: that one
asks whether a blob is a player, this one asks WHICH player, because a fit on a
teammate is the defect.

    1  the LOCAL PLAYER -- you, the camera
    2  a TEAMMATE
    3  an ENEMY
    4  the SPIKE ON THE GROUND -- dropped or planted, a separate object
    9  the SPIKE CARRIED -- the badge that hangs off a player's own icon,
       reported at candidate 17 of the first run as sitting to the BOTTOM LEFT
       of the self icon. Split from `4` because the two are different defects:
       a dropped spike is a second object the reader picks instead, while a
       carried badge is PART OF THE PLAYER'S ICON, so a fit on it is a fixed
       offset rather than a wrong object. The FIRST PASS carries no
       `class_set` at all: the stamp reached this docstring and not the
       writer, so its `spike` rows cannot tell the two apart
    5  an ABILITY icon or area
    6  a DEATH MARK or a LAST-KNOWN marker
    S  the YELLOW SITE PAINT, or a piece of it -- the plantable zone, which is
       drawn in the same yellow family as the self icon. Reported at candidate
       29 of the first run, where the fit bounced between a portion of the site
       and the self icon. Unlike the spike this one HAS a channel already:
       `minimap.site_mask` derives it from the static median map, so it needs
       no decode and cannot move
    8  TWO OR MORE things under the ring that cannot be separated -- the
       player standing on the spike, two portraits exactly stacked. Added at
       candidate 9 of the first run, when the player was on the spike at the
       asked instant and walked off it in the next panel. This is NOT `U`:
       `U` says the labeller could not tell, `8` says there is no single
       answer to give, which is the case the reader fails on
    7  something real that is none of the above -- the escape hatch, because
       `0` is a CLAIM that nothing is there and being forced into it wrongly is
       how a negative class gets poisoned
    0  nothing: map furniture, a viewcone edge, an artefact
    U  unsure -- recorded, and kept OUT of scoring
    A  back one
    Q / ESC  save and quit

Three panels per candidate at -0.5 s, 0 and +0.5 s, each ringing the SAME
place, because a dropped spike does not move and a player does. The ring points
at the thing being asked about: a minimap crop routinely holds several objects.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from reticle import geometry  # noqa: E402
from reticle.decode import sample_windows  # noqa: E402
from reticle.minimap import (floor_mask, minimap_roi_px, slab_mask,  # noqa: E402
                             widget_drawn, widget_scale)
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE, Store  # noqa: E402

KIND = "self_fit"
#: Bumped when the question changes meaning. Set 2 split a carried spike badge
#: from a dropped one; rows with no `class_set` predate it and answered both
#: as `spike`.
CLASS_SET = "self_fit-3"
CLASSES = {"1": "local_player", "2": "teammate", "3": "enemy", "4": "spike",
           "5": "ability", "6": "mark", "7": "other", "0": "nothing",
           "8": "coincident", "9": "spike_carried", "s": "site_paint"}
RING = (70, 240, 250)
CROWD_PX = 25.0


def label_path(store_root: Path, sid: str) -> Path:
    return store_root / "labels" / KIND / f"{sid}.jsonl"


def load(store_root: Path, sid: str) -> dict:
    """Last row for a key wins, so `A`-then-reanswer corrects rather than duplicates."""
    p = label_path(store_root, sid)
    if not p.is_file():
        return {}
    out = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            out[r["key"]] = r
    return out


def candidates(rows: list[dict], n: int, seed: int) -> list[dict]:
    """Accepted fits, stratified by whether another read icon is close."""
    pool = []
    for r in rows:
        if r["self_x"] is None:
            continue
        near = False
        for i in range(4):
            ax, ay = r.get(f"ally{i}_x"), r.get(f"ally{i}_y")
            if ax is not None and np.hypot(ax - r["self_x"],
                                           ay - r["self_y"]) <= CROWD_PX:
                near = True
                break
        pool.append({"t_ms": r["t_ms"], "x": r["self_x"], "y": r["self_y"],
                     "stratum": "crowded" if near else "clear"})
    rng = random.Random(seed)
    out = []
    for stratum in ("crowded", "clear"):
        sub = [c for c in pool if c["stratum"] == stratum]
        rng.shuffle(sub)
        out.extend(sub[:n // 2])
        print(f"  {stratum}: {len(sub)} accepted fits, sampling {min(n // 2, len(sub))}")
    rng.shuffle(out)
    return out


def sheet(frames: list[tuple[float, np.ndarray]], x: float, y: float,
          scale: float, t_asked: float) -> np.ndarray:
    """Three instants, the same place ringed in each, plus a zoom and a scale bar."""
    half, zoom = 34, 5
    panels = []
    asked = min(range(len(frames)), key=lambda i: abs(frames[i][0] - t_asked))
    for idx, (t_ms, crop) in enumerate(frames):
        x0, y0 = max(0, int(x) - half), max(0, int(y) - half)
        x1 = min(crop.shape[1], int(x) + half)
        y1 = min(crop.shape[0], int(y) + half)
        patch = crop[y0:y1, x0:x1].copy()
        big = cv2.resize(patch, (patch.shape[1] * zoom, patch.shape[0] * zoom),
                         interpolation=cv2.INTER_NEAREST)
        cv2.circle(big, (int((x - x0) * zoom), int((y - y0) * zoom)),
                   int(11 * scale * zoom), RING, 2, cv2.LINE_AA)
        is_asked = idx == asked
        if is_asked:
            # The ring marks the CANDIDATE instant in every panel, so on the
            # others it points at where the thing was. Only one panel is the
            # question, and it has to be unmistakable.
            big = cv2.copyMakeBorder(big[3:-3, 3:-3], 3, 3, 3, 3,
                                     cv2.BORDER_CONSTANT, value=RING)
        bar = np.full((26, big.shape[1], 3), 30 if is_asked else 20, np.uint8)
        cv2.putText(bar, f"{t_ms/1000:.2f}s" + ("   <-- ASKED" if is_asked
                                                else "   (context)"),
                    (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    RING if is_asked else (170, 170, 170), 1, cv2.LINE_AA)
        # 10 source pixels, so a magnified crop cannot be mistaken for a native one.
        cv2.line(bar, (big.shape[1] - 10 * zoom - 8, 13),
                 (big.shape[1] - 8, 13), (220, 220, 220), 2)
        cv2.putText(bar, "10px", (big.shape[1] - 10 * zoom - 8, 9),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.32, (220, 220, 220), 1, cv2.LINE_AA)
        panels.append(np.vstack([bar, big]))
    h = max(p.shape[0] for p in panels)
    panels = [cv2.copyMakeBorder(p, 0, h - p.shape[0], 6, 6,
                                 cv2.BORDER_CONSTANT, value=(18, 18, 18))
              for p in panels]
    return np.hstack(panels)


def prepare(args, store: Store, sid: str) -> int:
    manifest = json.loads((Path(args.store) / "manifests" /
                           f"{sid}.json").read_text(encoding="utf-8"))
    src = manifest["source"]
    profile = get_profile(manifest["source_profile"])
    box = minimap_roi_px(profile, int(src["width"]), int(src["height"]))
    date = next(p.parent.parent.name.split("=")[1]
                for p in Path(args.store).glob("l1/minimap/**/*.parquet")
                if sid in str(p))
    rows = sorted(store.read_minimap(sid, date).to_pylist(),
                  key=lambda r: r["t_ms"])
    picks = candidates(rows, args.n, args.seed)
    out_dir = Path(args.store) / "labels" / KIND / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    spans = []
    for c in picks:
        spans.append((max(0.0, c["t_ms"] - 600.0), c["t_ms"] + 600.0))
    x0, y0, x1, y1 = box
    grabbed: list[tuple[float, np.ndarray]] = []
    for _who, smp in sample_windows(src["path"], float(src["fps"]),
                                    {"c": (float(src["fps"]), spans)}):
        grabbed.append((smp.t_ms, smp.frame[y0:y1, x0:x1].copy()))
    grabbed.sort(key=lambda g: g[0])
    times = np.array([g[0] for g in grabbed])
    scale = widget_scale(grabbed[0][1].shape[1]) if grabbed else 1.0

    index = []
    for k, c in enumerate(picks):
        trio = []
        for offset in (-500.0, 0.0, 500.0):
            j = int(np.argmin(np.abs(times - (c["t_ms"] + offset))))
            if abs(times[j] - (c["t_ms"] + offset)) > 200.0:
                continue
            trio.append(grabbed[j])
        if len(trio) < 2:
            continue
        img = sheet(trio, c["x"], c["y"], scale, c["t_ms"])
        name = f"{k:04d}.png"
        cv2.imwrite(str(out_dir / name), img)
        index.append({**c, "key": f"{c['t_ms']:.1f}|{c['x']:.1f}|{c['y']:.1f}",
                      "image": name})
    (out_dir / "index.json").write_text(json.dumps(index, indent=1),
                                        encoding="utf-8")
    print(f"prepared {len(index)} candidates -> {out_dir}")
    return 0


def ask(args, store: Store, sid: str) -> int:
    import base64
    import tkinter as tk

    out_dir = Path(args.store) / "labels" / KIND / sid
    index = json.loads((out_dir / "index.json").read_text(encoding="utf-8"))
    done = load(Path(args.store), sid)
    todo = [c for c in index if c["key"] not in done]
    print(f"{len(index)} candidates, {len(done)} answered, {len(todo)} left")
    if not todo:
        print("nothing left to label")
        return 0

    target = label_path(Path(args.store), sid)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = target.open("a", encoding="utf-8")
    state = {"i": 0}

    root = tk.Tk()
    root.title(f"what did the self reader lock onto -- {sid}")
    canvas = tk.Label(root)
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left")
    status.pack(fill="x")
    keep = {}

    def show():
        if state["i"] >= len(todo):
            root.quit()
            return
        c = todo[state["i"]]
        # base64 through `data=`, the way every other labeller here does it.
        # Tk 8.6 reads PNG natively, so this needs no imaging dependency, and
        # the reference must be kept or the image renders blank.
        raw = (out_dir / c["image"]).read_bytes()
        keep["img"] = tk.PhotoImage(data=base64.b64encode(raw))
        canvas.configure(image=keep["img"])
        status.configure(
            text=f"{state['i'] + 1}/{len(todo)}   t={c['t_ms']/1000:.2f}s   "
                 f"{c['stratum']}\n"
                 "1 you  2 teammate  3 enemy  4 spike  5 ability  6 mark  "
                 "7 other  0 nothing   U unsure   A back   Q quit")

    def answer(name):
        c = todo[state["i"]]
        handle.write(json.dumps({**c, "answer": name, "by": args.by,
                                 "class_set": CLASS_SET}) + "\n")
        handle.flush()          # read the file as it fills
        state["i"] += 1
        show()

    for key, name in CLASSES.items():
        root.bind(key, lambda _e, n=name: answer(n))
    root.bind("S", lambda _e: answer("site_paint"))
    root.bind("u", lambda _e: answer("unsure"))
    root.bind("U", lambda _e: answer("unsure"))
    root.bind("a", lambda _e: (state.update(i=max(0, state["i"] - 1)), show()))
    root.bind("A", lambda _e: (state.update(i=max(0, state["i"] - 1)), show()))
    root.bind("q", lambda _e: root.quit())
    root.bind("<Escape>", lambda _e: root.quit())
    show()
    root.mainloop()
    handle.close()
    print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--store", default=str(DEFAULT_STORE))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--seed", type=int, default=11)
    ap.add_argument("--by", default="player")
    args = ap.parse_args(argv)
    store = Store(args.store)
    if args.prepare:
        return prepare(args, store, args.session)
    return ask(args, store, args.session)


if __name__ == "__main__":
    raise SystemExit(main())
