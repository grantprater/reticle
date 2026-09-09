r"""Ask which ringed minimap components are one ability entity.

    .\.venv\Scripts\python.exe prototypes\label_grouping.py [--session S] [--limit N]

Milestone C queues 286 review windows and nothing could answer them, so the
grouping alternatives it generates stay alternatives for ever. This is the
labelling pass that settles them, and it is the design's step 1: source review
before any capture request, because footage already on disk may resolve the
largest gaps for zero new recording.

Three question shapes, because the queue holds three
-----------------------------------------------------
* **no component** (28 windows) -- a use claim with nothing observed near it.
  The question is whether the ability draws anything on the minimap at all, and
  a wrong answer here is what makes the null hypothesis unfalsifiable.
* **one component** (85) -- is the ringed thing this ability, or clutter?
* **two or more** (173) -- the actual grouping question. Same digit means same
  physical entity; different digits mean separate entities from one use.

Why a filmstrip and not a single frame
--------------------------------------
The clutter classes the player named are separated by TIME, not appearance. A
minimap crack is static once lit; a ping ripples and dies; an ability arrives.
A single frame cannot distinguish them, so every component is shown as a strip
across its own window, and the ring is drawn in every panel.

Never seeded, append-only, last row for a key wins, and resumable: the pass can
be stopped at any point and the rows already written stay valid.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from reticle.adjudication.ability import _components, _labels  # noqa: E402
from reticle.profiles import get_profile  # noqa: E402
from reticle.store import DEFAULT_STORE  # noqa: E402

STORE = Path(DEFAULT_STORE)
KIND = "ability_grouping"

GROUP_KEYS = {str(d): d for d in range(1, 6)}
CLUTTER_KEYS = {
    "v": "viewcone_fragment",
    "c": "minimap_crack_or_seam",
    "p": "ping_or_spot_marker",
    "i": "player_or_spike_icon",
    "o": "other",          # escape hatch: never force a real thing into a class
}
# An orphan window has no use claim beside it, so "it was already there" is a
# real answer rather than a missing observation.
ORPHAN_EXTRA = {"e": "present_before_this_window"}
# Offsets from the labelled instant. Zero is mandatory and is the whole point:
# an Omen smoke in flight is present for under two seconds, so an evenly spaced
# strip misses it entirely and shows the player bare ground at the one moment the
# object is certain to be there. History is weighted before the label because a
# label marks when the labeller SAW the thing, not when it arrived.
STRIP_OFFSETS_MS = (-8000.0, -3000.0, -800.0, 0.0, 1200.0, 4000.0)
CROP = 34          # half-width of the magnified crop, in ROI pixels
TILE_ZOOM = 3      # magnification of each strip tile
PANEL_H = 690      # keeps the whole window inside a 1080p screen
_IS = "IS the ability: 1-5 group id (same digit = same entity)"
_NOT = "NOT the ability: v viewcone  c crack  p ping  i icon  o other  n nothing there"
_END = "u unsure | click = mark a component we missed | a back | q save+quit"
HELP_GROUP = f"{_IS} | {_NOT} | {_END}"
HELP_ORPHAN = (f"{_IS}, or e = already there before this strip | {_NOT} | {_END}")


def roi_for(root: Path, sid: str) -> tuple[int, int, int, int]:
    """The minimap crop, from the session's PROFILE.

    A label's x/y index this crop -- `ability_series` reads them as
    `crop[y, x]` -- so the origin has to come from the same place the reader
    takes it, not from the `roi` field carried on the label row. The two
    profiles in this store differ: the enlarged widget spans x 15..480 where
    the ordinary one stops at 346, and mixing them puts every ring in the
    wrong place by the difference.
    """
    man = json.loads((root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
    src = man["source"]
    prof = get_profile(man["source_profile"])
    x0, y0, x1, y1 = next(r for r in prof.rois if r.name == "minimap").pixels(
        int(src["width"]), int(src["height"]))
    return x0, y0, x1 - x0, y1 - y0


def ranked_windows(root: Path, session: str | None) -> list[dict]:
    """Deadlock in the two real matches first: that is where the only held-out
    contrast lives, so answers there are the ones that can change a score."""
    rows = []
    path = root / "analysis" / "ability-entities" / "review.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    if session:
        rows = [r for r in rows if r["session_id"] == session]

    def key(row):
        ability = (row.get("ability_id") or "") + " ".join(row.get("named_abilities") or [])
        deadlock = 0 if "deadlock" in ability else 1
        return (deadlock, -len(row["component_ids"]), row["session_id"], row["clip_start_ms"])

    return sorted(rows, key=key)


def _strip_times(window: dict, component: dict | None) -> list[float]:
    """Centre the strip on the component being ASKED, weighted to its past.

    A human label records when the labeller saw the thing, not when it arrived,
    so the evidence that decides "was this here earlier and has it gone" lies
    before the label rather than after it.
    """
    if component is None:
        lo, hi = float(window["clip_start_ms"]), float(window["clip_end_ms"])
        n = len(STRIP_OFFSETS_MS)
        return [lo + (hi - lo) * i / (n - 1) for i in range(n)]
    t = float(component["observed_t_ms"])
    return [max(0.0, t + d) for d in STRIP_OFFSETS_MS]


class Clips:
    """Lazily opened captures, so a pass over one session seeks in one file."""

    def __init__(self, root: Path):
        self.root, self.caps, self.fps = Path(root), {}, {}

    def frames(self, sid: str, times: list[float]):
        if sid not in self.caps:
            man = json.loads((self.root / "manifests" / f"{sid}.json").read_text(encoding="utf-8"))
            self.caps[sid] = cv2.VideoCapture(man["source"]["path"])
            self.fps[sid] = float(man["source"]["fps"])
        cap, out = self.caps[sid], []
        for t in times:
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, int(round(t / 1000.0 * self.fps[sid]))))
            ok, frame = cap.read()
            out.append(frame if ok else None)
        return out

    def release(self):
        for cap in self.caps.values():
            cap.release()


def compose(window: dict, cid: str | None, components: dict, clips: Clips,
            scale: float = 1.6, missing: list | None = None,
            answers: dict | None = None):
    """The panel the player answers from.

    The minimap panel rings every component in the window and highlights the one
    being asked about; the strip below shows that same pixel across the window,
    because the clutter classes are separated by time rather than by appearance.
    Returns ``(image, panel_height, roi_origin)``.
    """
    component = components.get(cid) if cid else None
    rx, ry, rw, rh = roi_for(clips.root, window["session_id"])
    times = _strip_times(window, component)
    raw = [None if f is None else f[ry:ry + rh, rx:rx + rw]
           for f in clips.frames(window["session_id"], times)]
    mid = raw[len(raw) // 2]
    if mid is None:
        return None, 0, (rx, ry)

    scale = PANEL_H / float(rh)
    panel = cv2.resize(mid.copy(), None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_NEAREST)
    members = [components[c] for c in window["component_ids"] if c in components]
    answers = answers or {}
    for m in members:
        px, py = int(float(m["x"]) * scale), int(float(m["y"]) * scale)
        current = m["component_id"] == cid
        given = answers.get(m["component_id"])
        if current:
            colour, mark, thick, rad = (0, 200, 255), "?", 3, 16
        elif given is None:
            colour, mark, thick, rad = (150, 150, 150), "", 1, 12
        elif given.get("group"):
            colour, mark, thick, rad = (80, 255, 80), str(given["group"]), 2, 13
        else:
            colour, mark, thick, rad = (255, 150, 150), given["answer"][:1].upper(), 2, 13
        cv2.circle(panel, (px, py), rad, colour, thick)
        if mark:
            org = (px + rad + 3, py - rad + 4)
            cv2.putText(panel, mark, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 0, 0), 4, cv2.LINE_AA)
            cv2.putText(panel, mark, org, cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        colour, 2, cv2.LINE_AA)
    for (mx, my) in (missing or []):
        cv2.drawMarker(panel, (int(mx * scale), int(my * scale)), (80, 255, 120),
                       cv2.MARKER_CROSS, 18, 2)

    tiles = []
    for frame, t in zip(raw, times):
        if frame is None:
            continue
        if component is not None:
            cx, cy = int(float(component["x"])), int(float(component["y"]))
        else:
            cx, cy = rw // 2, rh // 2
        x0, y0 = max(0, cx - CROP), max(0, cy - CROP)
        tile = frame[y0:y0 + CROP * 2, x0:x0 + CROP * 2].copy()
        if tile.size == 0:
            continue
        tile = cv2.resize(tile, (CROP * 2 * TILE_ZOOM, CROP * 2 * TILE_ZOOM),
                          interpolation=cv2.INTER_NEAREST)
        if component is not None:
            cv2.circle(tile, ((cx - x0) * TILE_ZOOM, (cy - y0) * TILE_ZOOM),
                       20, (60, 230, 255), 2)
        at_label = (component is not None
                    and abs(t - float(component["observed_t_ms"])) < 1.0)
        caption = f"{t / 1000:.1f}s  <-- LABELLED" if at_label else f"{t / 1000:.1f}s"
        cv2.putText(tile, caption, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(tile, caption, (6, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45,
                    (60, 255, 255) if at_label else (230, 230, 230), 1, cv2.LINE_AA)
        tiles.append(tile)
    strip = np.hstack(tiles) if tiles else np.zeros((40, 40, 3), np.uint8)

    width = max(panel.shape[1], strip.shape[1])
    out = np.zeros((panel.shape[0] + strip.shape[0] + 8, width, 3), np.uint8)
    left = (width - panel.shape[1]) // 2
    out[:panel.shape[0], left:left + panel.shape[1]] = panel
    out[panel.shape[0] + 8:, :strip.shape[1]] = strip
    return out, panel.shape[0], (left, scale)


def answers_short(answers: dict, cid: str) -> str:
    given = answers[cid]
    return str(given["group"]) if given.get("group") else given["answer"][:5]


def build_queue(root: Path, session: str | None, redo: bool, limit: int,
                components: dict):
    windows = ranked_windows(root, session)
    done = set()
    out_dir = root / "labels" / KIND
    out_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(out_dir.glob("*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done.add((row["review_id"], row.get("component_id") or ""))
    queue = []
    for window in windows:
        ids = window["component_ids"]
        if not ids:
            if redo or (window["review_id"], "") not in done:
                queue.append((window, None))
            continue
        for cid in ids:
            if cid in components and (redo or (window["review_id"], cid) not in done):
                queue.append((window, cid))
    return (queue[:limit] if limit else queue), done, out_dir


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("--session", help="only this session")
    ap.add_argument("--limit", type=int, default=0, help="stop after N windows")
    ap.add_argument("--scale", type=float, default=1.6, help="minimap panel zoom")
    ap.add_argument("--redo", action="store_true",
                    help="revisit answered components; the file is append-only "
                         "and the last row for a key wins, so nothing is lost")
    args = ap.parse_args()

    root_store = STORE
    components = {c["component_id"]: c for c in _components(root_store, _labels(root_store))}
    queue, done, out_dir = build_queue(root_store, args.session, args.redo,
                                       args.limit, components)
    if not queue:
        print("every queued component is already answered")
        return 0
    print(f"{len(done)} already answered, {len(queue)} questions this run")
    clips = Clips(root_store)

    handles: dict[str, object] = {}
    state = {"i": 0, "img": None, "missing": [], "written": 0, "answers": {}}

    tkroot = tk.Tk()
    tkroot.title("reticle - which components are one entity")
    canvas = tk.Canvas(tkroot, highlightthickness=0, bg="#101014")
    canvas.pack(fill="both", expand=True)
    status = tk.Label(tkroot, anchor="w", font=("Consolas", 10), justify="left")
    status.pack(fill="x")
    helpbar = tk.Label(tkroot, anchor="w", font=("Consolas", 9), fg="#888")
    helpbar.pack(fill="x")

    def show():
        window, cid = queue[state["i"]]
        view, panel_h, roi = compose(window, cid, components, clips,
                                     missing=state["missing"],
                                     answers=state["answers"])
        state["panel_h"], state["roi"] = panel_h, roi
        if view is None:
            advance(+1, write=False)
            return
        ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        handles["img"] = state["img"]

        n = len(window["component_ids"])
        orphan = not window.get("use_claim_id")
        helpbar.config(text=HELP_ORPHAN if orphan else HELP_GROUP)
        if not cid:
            shape = "NO COMPONENT: did this use draw anything on the minimap? n = nothing"
        else:
            where = (f"component {window['component_ids'].index(cid) + 1} of {n}"
                     if n > 1 else "the ringed thing")
            named = window.get("ability_id") or (window.get("named_abilities") or [None])[0]
            claim = ("no use was claimed nearby" if orphan else "a use was claimed nearby")
            shape = (f"{where}: is it {named or 'an ability'}?  ({claim}; "
                     f"press 1 if yes, or say what it is instead)")
        given = [f"{answers_short(state['answers'], c)}"
                 for c in window["component_ids"] if c in state["answers"]]
        sofar = ("  already: " + " ".join(given)) if given else ""
        status.config(text=(
            f"[{state['i'] + 1}/{len(queue)}] {window['session_id']} "
            f"{window.get('ability_id') or window.get('named_abilities') or '?'}  "
            f"{window['clip_start_ms'] / 1000:.1f}-{window['clip_end_ms'] / 1000:.1f}s"
            f"   written {state['written']}\n"
            f"{shape}{sofar}"))

    def write(answer: str, group: int | None = None, unsure: bool = False):
        window, cid = queue[state["i"]]
        component = components.get(cid) if cid else None
        row = {
            "review_id": window["review_id"],
            "session_id": window["session_id"],
            "component_id": cid,
            "ability_id": window.get("ability_id"),
            "answer": answer,
            "group": group,
            "unsure": unsure,
            "missing_marks": [
                {"x": round((mx - state["roi"][0]) / state["roi"][1], 1),
                 "y": round(my / state["roi"][1], 1)}
                for (mx, my) in state["missing"]],
            "by": "human",
        }
        if component is not None:
            row.update({"t_ms": component["observed_t_ms"],
                        "x": component["x"], "y": component["y"]})
        if cid:
            state["answers"][cid] = {"answer": answer, "group": group}
        path = out_dir / f"{window['session_id']}.jsonl"
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
        state["written"] += 1

    def advance(step: int, write_row=None, write: bool = True):
        if write and write_row is not None:
            write_row()
        state["missing"] = []
        state["i"] += step
        if state["i"] >= len(queue):
            finish()
            return
        state["i"] = max(0, state["i"])
        show()

    def answer_group(digit: int):
        advance(+1, lambda: write("same_entity", group=digit))

    def answer_clutter(name: str):
        advance(+1, lambda: write(name))

    def finish():
        clips.release()
        print(f"wrote {state['written']} rows -> {out_dir}")
        tkroot.destroy()

    for key, digit in GROUP_KEYS.items():
        tkroot.bind(key, lambda e, d=digit: answer_group(d))
    for key, name in CLUTTER_KEYS.items():
        tkroot.bind(key, lambda e, n=name: answer_clutter(n))
    for key, name in ORPHAN_EXTRA.items():
        tkroot.bind(key, lambda e, n=name: answer_clutter(n))
    tkroot.bind("u", lambda e: advance(+1, lambda: write("unsure", unsure=True)))
    tkroot.bind("n", lambda e: advance(+1, lambda: write("nothing_there")))
    tkroot.bind("<space>", lambda e: advance(+1, lambda: write("marked_missing_only")))
    tkroot.bind("a", lambda e: advance(-1, write=False))
    tkroot.bind("q", lambda e: finish())
    tkroot.bind("<Escape>", lambda e: finish())
    canvas.bind("<Button-1>", lambda e: (
        e.y < state.get("panel_h", 0) and state["missing"].append(
            ((e.x - state["roi"][0]) / state["roi"][1], e.y / state["roi"][1])), show()))
    canvas.bind("<Button-3>", lambda e: (
        state["missing"] and state["missing"].pop(), show()))

    show()
    tkroot.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
