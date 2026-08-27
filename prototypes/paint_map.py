"""Paint the map mask by hand: where is this widget actually SEARCHABLE?

    .\\.venv\\Scripts\\python.exe prototypes\\paint_map.py <session>

Controls
--------
    left drag        paint -- this is opaque map, a detection here is real
    right drag       erase -- this is see-through, or not map at all
    [ / ]            brush smaller / larger
    - / =            zoom out / in       wheel scrolls, middle-drag pans
    f                cycle the backdrop: static map, then live frames
    m                hold to flash the CURRENT DERIVED mask, for comparison
    u                undo the last stroke
    s                save        q / ESC  save and quit

Why this exists
---------------
Five times in one session Grant looked at a candidate and named a defect in the
searchable area that measurement had not caught: the dilation fringe at the
map's rim, the interior box edges the slab-only rule cut through, the bomb sites
sitting 93% in VOID, the enclosed void pockets `exterior` cannot reach, and the
drop shadow under a border -- white, then light grey, then darker grey on the
BOTTOM edge and plain white on the top, so no symmetric guard can fit it. Each
fix was right and each was found by eye, after I had already convinced myself
with numbers. The pattern is clear enough to act on: **he can see the map and
the derivation cannot.**

So this asks for the mask directly rather than inferring it a defect at a time.
What comes back is ground truth for one session, and the derivation's job
changes from "be right" to "reproduce this, then transfer to a map nobody has
painted" -- which is checkable, unlike the five rules it replaces.

It starts BLANK, deliberately. Seeding it with the derived mask would make
correcting cheaper and the result worthless: the whole reason to ask is that the
derived mask has blind spots, and a seeded canvas invites agreeing with them.
`m` flashes the derived mask on demand so it can still be compared, and the
saved metadata records whether that was ever pressed.

The backdrop cycles through live frames as well as the static map, because
transparency is the thing being judged and it cannot be seen in one frame --
what gives a void away is the world moving behind it.
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
from minimap_temporal import usable                               # noqa: E402
import label_dynamic as ld                                        # noqa: E402

STORE = Path.home() / "reticle-store"


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--frames", type=int, default=6, help="live frames to cycle")
    args = ap.parse_args()
    sid = args.session

    man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
    src = man["source"]
    fps = float(src["fps"])
    prof = get_profile(man["source_profile"])
    W, H = int(src["width"]), int(src["height"])
    mx0, my0, mx1, my1 = next(r for r in prof.rois if r.name == "minimap").pixels(W, H)
    labels, static = md.load_geometry(sid)
    derived = md.searchable(labels, static=static)
    h, w = static.shape[:2]

    print("loading backdrop frames...")
    floor = labels != md.VOID
    backdrops = [("static map", static)]
    cap = cv2.VideoCapture(src["path"])
    for t in ld.active_times(sid, args.frames, seed=11):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(t / 1000.0 * fps)))
        ok, fr = cap.read()
        if not ok:
            continue
        crop = fr[my0:my1, mx0:mx1]
        if usable(crop, floor):
            backdrops.append((f"live {int(t) // 60000}:{int(t) // 1000 % 60:02d}", crop))
    cap.release()

    out_path = STORE / "labels" / "map_mask" / f"{sid}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    mask_u8 = np.zeros((h, w), np.uint8)
    if out_path.is_file():
        mask_u8 = (cv2.imread(str(out_path), cv2.IMREAD_GRAYSCALE) > 127).astype(np.uint8)
        print(f"resuming {out_path}, {mask_u8.mean() * 100:.1f}% painted")

    root = tk.Tk()
    root.title(f"reticle - paint the map mask - {sid}")
    fit = max(1, min(3, (root.winfo_screenheight() - 170) // h))
    vw, vh = w * fit, h * fit
    canvas = tk.Canvas(root, width=vw, height=vh, highlightthickness=0,
                       cursor="crosshair")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")

    st = {"brush": 9, "bd": 0, "img": None, "undo": [], "flash": False,
          "used_derived": False, "zoom": fit}

    def compose():
        base = backdrops[st["bd"]][1].copy()
        show = derived if st["flash"] else mask_u8.astype(bool)
        tint = np.array([255, 140, 40]) if st["flash"] else np.array([60, 200, 60])
        base[show] = (base[show] * 0.55 + tint * 0.45).astype(np.uint8)
        rim = cv2.dilate(show.astype(np.uint8), np.ones((3, 3), np.uint8)) - show
        base[rim > 0] = (255, 255, 255)
        z = st["zoom"]
        big = cv2.resize(base, None, fx=z, fy=z, interpolation=cv2.INTER_NEAREST)
        _ok, buf = cv2.imencode(".png", big)
        st["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=st["img"])
        canvas.config(scrollregion=(0, 0, w * z, h * z))
        status.config(
            text=f"  backdrop={backdrops[st['bd']][0]}   brush={st['brush']}px"
                 f"   zoom={z}x"
                 f"   painted={mask_u8.mean() * 100:5.1f}%"
                 f"   {'<< DERIVED MASK >>' if st['flash'] else ''}"
                 f"   [ ] brush | f backdrop | m compare | u undo | s save | q quit")

    def stroke(ev, value):
        z = st["zoom"]
        x = int(canvas.canvasx(ev.x) / z)
        y = int(canvas.canvasy(ev.y) / z)
        cv2.circle(mask_u8, (x, y), st["brush"], 1 if value else 0, -1)
        # Immediate feedback without re-encoding the whole image on every motion
        # event; the true composite is redrawn on release.
        r = max(2, st["brush"] * z)
        cx, cy = canvas.canvasx(ev.x), canvas.canvasy(ev.y)
        canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                           outline="", fill="#3cc83c" if value else "#1a1a1a")

    def push():
        st["undo"].append(mask_u8.copy())
        del st["undo"][:-30]

    canvas.bind("<Button-1>", lambda e: (push(), stroke(e, True)))
    canvas.bind("<B1-Motion>", lambda e: stroke(e, True))
    canvas.bind("<ButtonRelease-1>", lambda e: compose())
    canvas.bind("<Button-3>", lambda e: (push(), stroke(e, False)))
    canvas.bind("<B3-Motion>", lambda e: stroke(e, False))
    canvas.bind("<ButtonRelease-3>", lambda e: compose())

    def brush(d):
        st["brush"] = max(1, min(40, st["brush"] + d))
        compose()

    def backdrop():
        st["bd"] = (st["bd"] + 1) % len(backdrops)
        compose()

    def flash(on):
        st["flash"] = on
        if on:
            st["used_derived"] = True
        compose()

    def undo():
        if st["undo"]:
            np.copyto(mask_u8, st["undo"].pop())
            compose()

    def save():
        cv2.imwrite(str(out_path), mask_u8 * 255)
        out_path.with_suffix(".json").write_text(json.dumps({
            "session_id": sid, "roi": [mx0, my0, mx1, my1], "by": "grant",
            "painted_frac": round(float(mask_u8.mean()), 4),
            "compared_against_derived": st["used_derived"],
        }, indent=2), encoding="utf-8")
        print(f"wrote {out_path}  ({mask_u8.mean() * 100:.1f}% painted)")

    def finish(*_a):
        save()
        root.destroy()

    def setzoom(d):
        st["zoom"] = max(1, min(8, st["zoom"] + d))
        compose()

    # These were bound as bare "bracketleft"/"bracketright" first time round,
    # which Tk reads as a SEQUENCE of eleven ordinary keypresses -- so the brush
    # keys silently did nothing and Grant painted the whole mask at one size.
    # A named keysym has to be in angle brackets; a single character does not.
    for key, fn in (("<bracketleft>", lambda e: brush(-2)),
                    ("<bracketright>", lambda e: brush(+2)),
                    ("<minus>", lambda e: setzoom(-1)),
                    ("<equal>", lambda e: setzoom(+1)),
                    ("<plus>", lambda e: setzoom(+1)),
                    ("f", lambda e: backdrop()),
                    ("u", lambda e: undo()),
                    ("s", lambda e: save()),
                    ("q", finish),
                    ("<Escape>", finish)):
        root.bind(key, fn)
    canvas.bind("<MouseWheel>", lambda e: canvas.yview_scroll(-e.delta // 120, "units"))
    canvas.bind("<Shift-MouseWheel>",
                lambda e: canvas.xview_scroll(-e.delta // 120, "units"))
    canvas.bind("<Button-2>", lambda e: canvas.scan_mark(e.x, e.y))
    canvas.bind("<B2-Motion>", lambda e: canvas.scan_dragto(e.x, e.y, gain=1))
    root.bind("<KeyPress-m>", lambda e: flash(True))
    root.bind("<KeyRelease-m>", lambda e: flash(False))
    root.protocol("WM_DELETE_WINDOW", finish)

    compose()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
