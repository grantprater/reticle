"""Mark EVERY ability object on a frame, so precision becomes measurable at last.

    .\\.venv\\Scripts\\python.exe prototypes\\paint_icons.py <session> [--frames 12]

Controls
--------
    left click       drop an ICON mark (a disc) at the current radius
    [ / ]            disc radius smaller / larger
    shift + drag     brush a REGION of the current class (wall, smoke, ult)
    shift + right    erase from the current region
    right click      undo the last mark on this frame
    1-9              pick the class from the legend (most recently used)
    c                new class by name -- agent, then ability
    SPACE / d        this frame is DONE and exhaustive; save and advance
    n                nothing on this frame at all; save and advance
    u                mark this frame UNSURE -- recorded, kept out of scoring
    a                back one frame
    m                hold to flash the DISC DETECTOR's output, for comparison
    f                cycle backdrop: this frame, then the static map
    - / =            zoom out / in     wheel scrolls, middle-drag pans
    s                save        q / ESC  save and quit

Why this exists, and why it beats the pass we already have
------------------------------------------------------------
the proposal, 2026-09-03, and he is right about the reason. Every ability
label in the store is **candidate-anchored**: `label_ability.py` only ever asks
about positions some detector already proposed. Two things follow, and both have
bitten already:

* **precision cannot be measured.** `ability_disc.py` had to refuse to quote one
  -- a detection where nobody has labelled is unscored, so the best it could
  offer was candidates-per-frame as a proxy;
* **recall is quietly biased.** The label set is a subset of one detector's
  output, so an icon NO detector proposed is invisible to every evaluation. That
  is the population trap this repo has already paid for twice (*0 of 55
  hand-marked icons have aspect >= 2.0* -- true, and about the wrong population).

Marking a frame EXHAUSTIVELY breaks both. Unmarked pixels become true negatives,
so precision and recall are both directly computable, for any detector, without
re-labelling. It is the same move `paint_map.py` made for the searchable mask,
which settled in one pass what five derived rules had failed at and then
transferred to a second map at 92.8% IoU.

It also produces two things nothing else can:

* **the disc radius**, measured rather than assumed. Two attempts to derive it
  from patches failed identically -- Otsu merges the icon with any adjacent dark
  map -- so `ability_disc.BH_K` and its area gates rest on an eyeballed size;
* **ground truth for REGIONS.** Walls, smokes and Brimstone's Orbital Strike have
  never been ground-truthed at all, because a region has no centre to click and
  the candidate stream never proposed one properly.

Design decisions the player made when asked (rather than guessed)
--------------------------------------------------------------
Clicking for discs and brushing for regions: a disc is uniform so a click plus a
radius captures it exactly, while a region needs real extent. Frames are
exhaustive. Classes are NAMED while marking, reusing `label_ability`'s global
category registry so the common ones are one keypress and the identity stage
gets its ground truth from the same pass.

Two conventions worth stating because they are easy to get wrong
-----------------------------------------------------------------
**It starts blank and never seeds.** `m` flashes `ability_disc`'s output for
comparison and the saved row records whether it was ever pressed. Seeding
`minimap_agent` with provisional rows once made the labeller skip them as done
and the number that came back was scoring my own clustering against itself.

**`n` means "nothing here", not "new class"** -- the shared control orthodoxy
every labeller in this repo uses. `label_ability.py` binds `N` to *new
category*, so the muscle memory collides; new class is `c` here and the legend
says so on screen.

One row per FRAME, not one per mark
-------------------------------------
The store convention is append-only, last-write-wins on a key. A row per mark
cannot express a DELETION -- revisiting a frame with `a` and removing a bad mark
would leave the old row winning forever. So a frame's whole answer is one row
keyed by `t_ms`, carrying its icon and region lists, and re-answering a frame
supersedes it wholesale.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).parent))
from reticle.profiles import get_profile                          # noqa: E402
import minimap_dynamic as md                                      # noqa: E402
from minimap_temporal import usable, drawn                        # noqa: E402
import label_dynamic as ld                                        # noqa: E402
import label_ability as la                                        # noqa: E402
from ability_disc import find_discs                               # noqa: E402

STORE = Path.home() / "reticle-store"
OUT_DIR = STORE / "labels" / "ability_paint"

#: Starting disc radius, in minimap pixels. Adjustable with [ ] -- it is a
#: STARTING point and not a measurement; measuring it is one of the reasons
#: this tool exists.
R0 = 7


def load_done(path: Path):
    """Frames already answered, last write winning -- the store convention."""
    if not path.is_file():
        return {}
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            out[d["t_ms"]] = d
    return out


def png_b64(mask):
    ok, buf = cv2.imencode(".png", mask * 255)
    return base64.b64encode(buf.tobytes()).decode("ascii") if ok else ""


def main() -> int:
    import tkinter as tk
    from tkinter import simpledialog

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--frames", type=int, default=12)
    args = ap.parse_args()
    sid = args.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    ok_area = md.searchable(labels, static=static)
    sgray = cv2.cvtColor(static, cv2.COLOR_BGR2GRAY).astype(np.int16)
    floor = labels != md.VOID
    h, w = static.shape[:2]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"{sid}.jsonl"
    done = load_done(out_path)

    print("loading frames...")
    try:
        times = list(ld.live_times(sid, args.frames * 3, seed=11))
    except Exception:
        times = []
    if not times:
        # Short controlled clips have no rounds to stratify over.
        cap0 = cv2.VideoCapture(src["path"])
        n = int(cap0.get(cv2.CAP_PROP_FRAME_COUNT))
        cap0.release()
        dur = n / fps * 1000.0
        times = list(np.linspace(0, max(0, dur - 500), args.frames * 3))
    frames = []
    cap = cv2.VideoCapture(src["path"])
    for t in times:
        if len(frames) >= args.frames:
            break
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        got, fr = cap.read()
        if not got:
            continue
        crop = fr[my0:my1, mx0:mx1]
        # A frame the widget is not readable on must not be ASKED about -- an
        # unreadable frame marked "nothing here" is a false negative forever.
        if crop.shape[:2] != (h, w) or not usable(crop, floor):
            continue
        if not drawn(crop, sgray, floor):
            continue
        frames.append((int(t), crop.copy()))
    cap.release()
    if not frames:
        raise SystemExit(f"{sid}: no usable frames")
    print(f"{len(frames)} frames, {sum(1 for t, _ in frames if t in done)} already answered")

    reg = la.load_categories()
    root = tk.Tk()
    root.title(f"reticle - paint ability objects - {sid}")
    fit = max(1, min(3, (root.winfo_screenheight() - 200) // h))
    canvas = tk.Canvas(root, width=w * fit, height=h * fit, highlightthickness=0,
                       cursor="crosshair")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 10), justify="left")
    status.pack(fill="x")
    legend = tk.Label(root, anchor="w", font=("Consolas", 10), justify="left")
    legend.pack(fill="x")

    st = {"i": 0, "r": R0, "zoom": fit, "bd": 0, "flash": False,
          "used_derived": False, "cat": None, "img": None, "undo": []}
    #: per-frame working state: icons list and class -> region mask
    work: dict = {}

    def cur():
        return frames[st["i"]]

    def wf():
        t, _c = cur()
        if t not in work:
            prev = done.get(t)
            icons = [dict(d) for d in (prev or {}).get("icons", [])]
            regions = {}
            for rg in (prev or {}).get("regions", []):
                m = cv2.imdecode(np.frombuffer(base64.b64decode(rg["mask_png"]),
                                               np.uint8), cv2.IMREAD_GRAYSCALE)
                full = np.zeros((h, w), np.uint8)
                x0, y0, bw, bh = rg["bbox"]
                if m is not None:
                    full[y0:y0 + bh, x0:x0 + bw] = (m > 127).astype(np.uint8)
                regions[rg["category_id"]] = full
            work[t] = {"icons": icons, "regions": regions,
                       "unsure": bool((prev or {}).get("unsure"))}
        return work[t]

    def derived_now():
        _t, c = cur()
        g = cv2.cvtColor(c, cv2.COLOR_BGR2GRAY)
        return find_discs(g, ok_area)

    def compose():
        t, c = cur()
        base = (static.copy() if st["bd"] else c.copy())
        f = wf()
        for cid, m in f["regions"].items():
            if m.any():
                base[m > 0] = (base[m > 0] * 0.5 + np.array([40, 200, 200]) * 0.5
                               ).astype(np.uint8)
        if st["flash"]:
            st["used_derived"] = True
            for x, y, _s, _a, _cc in derived_now():
                cv2.circle(base, (int(x), int(y)), 9, (40, 140, 255), 1)
        for d in f["icons"]:
            cv2.circle(base, (d["x"], d["y"]), d["r"], (60, 230, 60), 1)
            cv2.drawMarker(base, (d["x"], d["y"]), (60, 230, 60),
                           cv2.MARKER_CROSS, 5, 1)
        z = st["zoom"]
        big = cv2.resize(base, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        _o, buf = cv2.imencode(".png", big)
        st["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=st["img"])
        canvas.config(scrollregion=(0, 0, w * z, h * z))
        cat = st["cat"]
        cname = reg["categories"].get(cat, {}) if cat else {}
        status.config(text=(
            f"  frame {st['i'] + 1}/{len(frames)}  t={t / 1000:7.1f}s"
            f"  {'ANSWERED' if t in done else 'new':8s}"
            f"  icons={len(f['icons'])} regions={sum(1 for m in f['regions'].values() if m.any())}"
            f"  r={st['r']}px zoom={z}x"
            f"  class={(cname.get('agent') or '') + ':' + (cname.get('ability') or '-') if cat else 'NONE - press 1-9 or c'}"
            f"{'   << DISC DETECTOR >>' if st['flash'] else ''}"))
        legend.config(text="  " + " | ".join(
            f"{i + 1}:{k[0].split(':')[-1][:12]}" for i, k in enumerate(la.mru(reg)))
            + "\n  SPACE done+next | n nothing | u unsure | a back | c new class"
              " | m compare | f backdrop | right-click undo | q quit")

    def push():
        f = wf()
        st["undo"].append(([dict(d) for d in f["icons"]],
                           {k: v.copy() for k, v in f["regions"].items()}))
        del st["undo"][:-40]

    def xy(ev):
        z = st["zoom"]
        return int(canvas.canvasx(ev.x) / z), int(canvas.canvasy(ev.y) / z)

    def add_icon(ev):
        if not st["cat"]:
            return
        push()
        x, y = xy(ev)
        c = reg["categories"][st["cat"]]
        wf()["icons"].append({"x": x, "y": y, "r": st["r"],
                              "category_id": st["cat"],
                              "agent": c.get("agent", ""), "ability": c.get("ability", "")})
        compose()

    def region_stroke(ev, on):
        if not st["cat"]:
            return
        f = wf()
        m = f["regions"].setdefault(st["cat"], np.zeros((h, w), np.uint8))
        x, y = xy(ev)
        cv2.circle(m, (x, y), st["r"], 1 if on else 0, -1)
        z = st["zoom"]
        rr = max(2, st["r"] * z)
        cx, cy = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        canvas.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline="",
                           fill="#28c8c8" if on else "#1a1a1a")

    def undo(*_a):
        if st["undo"]:
            ic, rg = st["undo"].pop()
            f = wf()
            f["icons"], f["regions"] = ic, rg
            compose()

    def save_frame(t, exhaustive=True):
        f = work.get(t)
        if f is None:
            return
        regions = []
        for cid, m in f["regions"].items():
            if not m.any():
                continue
            ys, xs = np.where(m > 0)
            x0, y0 = int(xs.min()), int(ys.min())
            x1, y1 = int(xs.max()) + 1, int(ys.max()) + 1
            c = reg["categories"].get(cid, {})
            regions.append({"category_id": cid, "agent": c.get("agent", ""),
                            "ability": c.get("ability", ""),
                            "bbox": [x0, y0, x1 - x0, y1 - y0],
                            "mask_png": png_b64(m[y0:y1, x0:x1])})
        row = {"kind": "frame", "session_id": sid, "t_ms": t,
               "roi": [mx0, my0, mx1, my1], "exhaustive": bool(exhaustive),
               "unsure": bool(f["unsure"]), "icons": f["icons"], "regions": regions,
               "by": "human", "compared_against_derived": st["used_derived"]}
        with out_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row) + "\n")
            fh.flush()
        done[t] = row

    def advance(d):
        st["i"] = max(0, min(len(frames) - 1, st["i"] + d))
        st["undo"].clear()
        compose()

    def done_next(*_a):
        save_frame(cur()[0], True)
        advance(+1)

    def nothing(*_a):
        t = cur()[0]
        wf()["icons"].clear()
        wf()["regions"].clear()
        save_frame(t, True)
        advance(+1)

    def unsure(*_a):
        wf()["unsure"] = not wf()["unsure"]
        compose()

    def new_class(*_a):
        a = simpledialog.askstring("class", "AGENT (blank = not agent-specific)",
                                   parent=root)
        if a is None:
            return
        b = simpledialog.askstring("class", "ABILITY", parent=root)
        if not b:
            return
        st["cat"] = la.touch_category(reg, a.strip(), b.strip())
        la.save_categories(reg)
        compose()

    def pick(i):
        m = la.mru(reg)
        if i < len(m):
            st["cat"] = m[i][0]
            compose()

    def radius(d):
        st["r"] = max(2, min(60, st["r"] + d))
        compose()

    def zoom(d):
        st["zoom"] = max(1, min(8, st["zoom"] + d))
        compose()

    def backdrop(*_a):
        st["bd"] = 1 - st["bd"]
        compose()

    def flash(on):
        st["flash"] = on
        compose()

    def finish(*_a):
        save_frame(cur()[0], True)
        print(f"wrote {out_path}  ({len(done)} frames answered)")
        root.destroy()

    canvas.bind("<Button-1>", add_icon)
    canvas.bind("<Shift-Button-1>", lambda e: (push(), region_stroke(e, True)))
    canvas.bind("<Shift-B1-Motion>", lambda e: region_stroke(e, True))
    canvas.bind("<Shift-ButtonRelease-1>", lambda e: compose())
    canvas.bind("<Shift-Button-3>", lambda e: (push(), region_stroke(e, False)))
    canvas.bind("<Shift-B3-Motion>", lambda e: region_stroke(e, False))
    canvas.bind("<Shift-ButtonRelease-3>", lambda e: compose())
    canvas.bind("<Button-3>", undo)
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))
    canvas.bind("<Shift-MouseWheel>",
                lambda e: canvas.xview_scroll(-e.delta // 120, "units"))
    canvas.bind("<Button-2>", lambda e: canvas.scan_mark(e.x, e.y))
    canvas.bind("<B2-Motion>", lambda e: canvas.scan_dragto(e.x, e.y, gain=1))

    # Named keysyms need angle brackets. Bound bare, Tk reads "bracketleft" as a
    # SEQUENCE of eleven keypresses -- that silently broke brush sizing in
    # paint_map.py and the player painted a whole mask at one size.
    for key, fn in (("<bracketleft>", lambda e: radius(-1)),
                    ("<bracketright>", lambda e: radius(+1)),
                    ("<minus>", lambda e: zoom(-1)),
                    ("<equal>", lambda e: zoom(+1)),
                    ("<plus>", lambda e: zoom(+1)),
                    ("<space>", done_next),
                    ("d", done_next),
                    ("n", nothing),
                    ("u", unsure),
                    ("a", lambda e: advance(-1)),
                    ("c", new_class),
                    ("f", backdrop),
                    ("s", lambda e: save_frame(cur()[0], True)),
                    ("q", finish),
                    ("<Escape>", finish)):
        root.bind(key, fn)
    for i in range(9):
        root.bind(str(i + 1), lambda e, i=i: pick(i))
    root.bind("<KeyPress-m>", lambda e: flash(True))
    root.bind("<KeyRelease-m>", lambda e: flash(False))
    root.protocol("WM_DELETE_WINDOW", finish)

    compose()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
