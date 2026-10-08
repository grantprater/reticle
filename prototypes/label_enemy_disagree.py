r"""Ask the player what is drawn where the enemy reader and T1d disagree, and score who erred.

    .\.venv\Scripts\python.exe prototypes\label_enemy_disagree.py ask
    .\.venv\Scripts\python.exe prototypes\label_enemy_disagree.py score

**Input.** `enemy_error_budget.py sample --tag b1` drew 268 places where the
enemy minimap reader and the replay-truth draw rule T1d disagree
(`<store>/analysis/enemy-error-budget-20261007/label_sample_b1.json`): misses
(T1d draws a living enemy, the reader accepts no icon within 3 m) and extras
(the reader accepts an icon, T1d draws no living enemy within 3 m), one cause
class each, with a reweighting weight (the class's rows in the match over the
items drawn from it).

**Prepare** (`prepare`; `ask` runs it when the panels are missing) renders
one panel per item into `<store>/labels/enemy_disagree_b1/patches/` from the
minimap roi_cache only (`minimap_objects.object_context`, as the budget's eye
crops read it; no decode): the native-resolution window (1x, untouched), the
same window enlarged clean and enlarged with the marks (nearest neighbour,
display only), a strip of the same place from 1 s before to 1 s after (the
nearest cached frame within 70 ms; a grey tile where the cache holds none),
and the whole widget at 1x with the place marked. The marks: four green ticks
pointing at the place from outside an icon's radius and a dashed circle of
the scorer's 3 m hit radius (an icon centred inside it is a hit). Misses and extras get the same marks and the same question, and
the panel never shows the reader's call, T1d's call, the set or the class,
so nothing anchors the answer.

**Ask.** Items come in a fixed order shuffled by a hash of each key (the
classes interleave). The question: at frame 0, what is drawn where the ticks
point (an icon counts if its centre is inside the dashed circle)?

    1 enemy icon      2 red "?" mark     3 X mark
    4 utility or ability glyph           7 other (escape hatch)
    0 no icon, nothing drawn there       U unsure (kept out of scoring)

After 1: `1` one icon, `2` two or more overlapping, `U` unsure of the count.
`A` goes back one item (re-answer; the last row for a key wins); `Q` or
`ESC` saves and quits. Rows append to `<store>/labels/enemy_disagree_b1/
<session>.jsonl`, one file per session, flushed per row; a restart skips
answered keys. Never seed these files: the tool writes only the player's
answers, with `by` and `compared_against_derived: false`.

**Score** (`score`) joins the labels to the sample by key and, per class,
counts whose call the answer contradicts (`ERROR_SIDE`): on a miss an enemy
icon makes the reader wrong and a definite non-icon answer (no icon, "?", X,
glyph) makes T1d wrong; on an extra the reverse. `other` and `unsure` stay
out. It prints the reader-error share per class unweighted with a Wilson 95%
interval and weighted by the sample weights with a Wilson 95% interval at the
Kish effective sample size, and the same pooled per set.

Not wired (`"wire": "no"`): a labelling tool and its scorer over the error
budget's sample; the levers it settles live in `reticle/minimap_objects.py`,
`reticle/teardrop.py` and the T1d rule.

    python prototypes/label_enemy_disagree.py prepare [--idle]
    python prototypes/label_enemy_disagree.py ask [--by player]
    python prototypes/label_enemy_disagree.py score [--out FILE.json]
    # a test run, into scratch directories only:
    python prototypes/label_enemy_disagree.py prepare --patches SCRATCH --limit 3
    python prototypes/label_enemy_disagree.py ask --patches SCRATCH --labels SCRATCH2 \
        --smoke 1,1,0,2 --screenshot SHOT.png
"""
from __future__ import annotations

import os

for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
    os.environ.setdefault(_k, "1")

import argparse  # noqa: E402
import base64  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import zlib  # noqa: E402
from collections import Counter, defaultdict  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import numpy as np  # noqa: E402

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE))

from reticle.store import DEFAULT_STORE  # noqa: E402

TOOL = "label-enemy-disagree-0.1.0"
CLASS_SET = "enemy_disagree-1"
KIND = "enemy_disagree_b1"
STORE = Path(DEFAULT_STORE)
SAMPLE = STORE / "analysis" / "enemy-error-budget-20261007" / "label_sample_b1.json"
CLASSED = STORE / "analysis" / "enemy-error-budget-20261007" / "b1"
CLASSES = {"1": "enemy_icon", "2": "question", "3": "x_mark", "4": "glyph",
           "7": "other", "0": "no_icon"}
COUNTS = {"1": "one", "2": "two_or_more"}
#: Whose call an answer contradicts, per set. None: kept out of scoring.
ERROR_SIDE = {
    "miss": {"enemy_icon": "reader", "no_icon": "t1d", "question": "t1d", "x_mark": "t1d",
             "glyph": "t1d", "other": None, "unsure": None},
    "extra": {"enemy_icon": "t1d", "no_icon": "reader", "question": "reader", "x_mark": "reader",
              "glyph": "reader", "other": None, "unsure": None},
}
STRIP_MS = (-1000.0, -500.0, -250.0, 0.0, 250.0, 500.0, 1000.0)
SNAP_MS = 70.0           # a strip frame is the nearest cached frame within this
ZH, ZF = 20, 10          # the main windows: 41 px at 10x
SH, SF = 14, 5           # each strip frame: 29 px at 5x
SEED = 20261007


# ----------------------------------------------------------------- data

def item_key(it: dict) -> str:
    """The item's identity: session, set, frame and place."""
    x, y = it["widget_xy"]
    return f"{it['session']}|{it['set']}|{it['frame_idx']}|{x:.1f}|{y:.1f}"


def load_sample(path: Path) -> list[dict]:
    """The sample's items, each with its `key`; refuses duplicate keys and
    items without a weight."""
    blob = json.loads(Path(path).read_text(encoding="utf-8"))
    items = blob["items"] if isinstance(blob, dict) else blob
    out, seen = [], set()
    for it in items:
        k = item_key(it)
        if k in seen:
            raise SystemExit(f"duplicate sample key {k}")
        if not it.get("weight") or it["set"] not in ERROR_SIDE:
            raise SystemExit(f"item {k}: no weight or unknown set {it.get('set')!r}")
        seen.add(k)
        out.append({**it, "key": k})
    return out


def ask_order(items: list[dict]) -> list[dict]:
    """A fixed shuffle by a hash of each key, so the classes interleave."""
    return sorted(items, key=lambda it: zlib.crc32(f"{SEED}|{it['key']}".encode()))


def labels_dir(store: Path) -> Path:
    return Path(store) / "labels" / KIND


def load_answers(d: Path) -> dict:
    """Every `*.jsonl` row in the labels directory by key; the last row for
    a key wins (a re-answer after `A`)."""
    done = {}
    d = Path(d)
    if d.is_dir():
        for p in sorted(d.glob("*.jsonl")):
            for line in p.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    r = json.loads(line)
                    done[r["key"]] = r
    return done


# ----------------------------------------------------------------- panels

def _crop_about(crop: np.ndarray, x: float, y: float, h: int) -> np.ndarray:
    import cv2
    pad = cv2.copyMakeBorder(crop, h, h, h, h, cv2.BORDER_CONSTANT, value=(40, 40, 40))
    xi, yi = int(round(x)), int(round(y))
    return pad[yi:yi + 2 * h + 1, xi:xi + 2 * h + 1].copy()


def _enlarge(win: np.ndarray, f: int) -> np.ndarray:
    import cv2
    return cv2.resize(win, None, fx=f, fy=f, interpolation=cv2.INTER_NEAREST)  # display only


def _place_px(x: float, y: float, h: int, f: int) -> tuple[int, int]:
    xi, yi = int(round(x)), int(round(y))
    return int(round((h + 0.5 + x - xi) * f - 0.5)), int(round((h + 0.5 + y - yi) * f - 0.5))


def _draw_place_marks(img: np.ndarray, c: tuple[int, int], r_icon: float, r_near: float, f: float, thick: int = 2):
    """Four green ticks pointing at the place from outside an icon's radius
    (they never cover the icon) and the dashed white circle of the scorer's
    3 m hit radius about it, in pixels of the image at scale `f`."""
    import cv2
    r0, r1 = r_icon * 1.25 * f, r_icon * 1.9 * f
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        cv2.line(img, (int(c[0] + dx * r0), int(c[1] + dy * r0)), (int(c[0] + dx * r1), int(c[1] + dy * r1)),
                 (0, 255, 0), thick)
    R = max(3, int(round(r_near * f)))
    for a in range(0, 360, 20):
        cv2.ellipse(img, c, (R, R), 0, a, a + 10, (255, 255, 255), 1)


def _label(img: np.ndarray, text: str, org=(4, 14), scale=0.45):
    import cv2
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 3)
    cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), 1)


def compose(frames: dict, x: float, y: float, r_icon: float, r_near: float) -> np.ndarray:
    """One panel: native window, clean and marked enlargements, the widget at
    1x, and the time strip. `frames` maps a strip offset (ms) to the minimap
    crop or None; offset 0 must be present."""
    import cv2
    crop = frames[0.0]
    win = _crop_about(crop, x, y, ZH)
    clean = _enlarge(win, ZF)
    marked = clean.copy()
    _draw_place_marks(marked, _place_px(x, y, ZH, ZF), r_icon, r_near, ZF)
    _label(clean, "frame 0, clean")
    _label(marked, "frame 0, marked")
    side = (2 * ZH + 1) * ZF
    native = np.full((side, 2 * ZH + 1 + 16, 3), 18, np.uint8)
    native[8:8 + win.shape[0], 8:8 + win.shape[1]] = win     # 1x, untouched
    top = np.hstack([native, np.full((side, 8, 3), 18, np.uint8), clean,
                     np.full((side, 8, 3), 18, np.uint8), marked])
    tiles = []
    ts = (2 * SH + 1) * SF
    for dt in STRIP_MS:
        fr = frames.get(dt)
        if fr is None:
            tile = np.full((ts, ts, 3), 70, np.uint8)
            _label(tile, "no frame", (4, ts // 2))
        else:
            tile = _enlarge(_crop_about(fr, x, y, SH), SF)
            _draw_place_marks(tile, _place_px(x, y, SH, SF), r_icon, r_near, SF, 1)
        _label(tile, "0 s" if dt == 0 else f"{dt / 1000:+.2f} s")
        if dt == 0:
            cv2.rectangle(tile, (0, 0), (ts - 1, ts - 1), (0, 255, 0), 2)
        tiles.append(tile)
        tiles.append(np.full((ts, 4, 3), 18, np.uint8))
    strip = np.hstack(tiles[:-1])
    ctx = crop.copy()
    _draw_place_marks(ctx, (int(round(x)), int(round(y))), r_icon, r_near, 1.0)
    _label(ctx, "widget, 1x")
    left_w = max(top.shape[1], strip.shape[1])
    left = np.full((top.shape[0] + 8 + strip.shape[0], left_w, 3), 18, np.uint8)
    left[:top.shape[0], :top.shape[1]] = top
    left[top.shape[0] + 8:, :strip.shape[1]] = strip
    H = max(left.shape[0], ctx.shape[0])
    out = np.full((H, left_w + 12 + ctx.shape[1], 3), 18, np.uint8)
    out[:left.shape[0], :left_w] = left
    out[:ctx.shape[0], left_w + 12:] = ctx
    return out


def _session_radii(sid: str) -> tuple[float, float]:
    """The icon disc radius and the 3 m hit radius in widget px, from the
    budget's classed rows (constant per match)."""
    r_disc, near = [], []
    with open(CLASSED / f"classed_{sid}.jsonl", encoding="utf-8") as fh:
        for ln in fh:
            f = json.loads(ln)
            r_disc.append(f["r_disc"])
            near.append(f["near_px"])
    return float(np.median(r_disc)), float(np.median(near))


def _idle():
    if os.name == "nt":
        import ctypes
        k32 = ctypes.windll.kernel32
        k32.SetPriorityClass(k32.GetCurrentProcess(), 0x40)   # IDLE_PRIORITY_CLASS


def prepare(sample: Path, out: Path, limit: int | None = None) -> int:
    """Render one panel per item (in ask order) from the roi_cache; writes
    `patches/NNN.png` and `ask.json` (keys and panel names only)."""
    import cv2

    import enemy_error_budget as eb
    from reticle import minimap_objects as mo
    from reticle.store import Store

    items = ask_order(load_sample(sample))
    if limit:
        items = items[:limit]
    out = Path(out)
    (out / "patches").mkdir(parents=True, exist_ok=True)
    by_sid = defaultdict(list)
    for n, it in enumerate(items):
        by_sid[it["session"]].append((n, it))
    rows = {}
    for sid, its in by_sid.items():
        eb.refuse(sid)
        ctx, why = mo.object_context(Store(STORE), sid)
        if ctx is None:
            raise SystemExit(why)
        x0, y0, x1, y1 = ctx["rect"]
        held = np.sort(np.asarray(ctx["cache"].holds(), float))
        r_icon, r_near = _session_radii(sid)
        want = {}
        for n, it in its:
            snap = {}
            for dt in STRIP_MS:
                tw = it["t_cap_ms"] + dt
                k = int(np.argmin(np.abs(held - tw)))
                if abs(held[k] - tw) <= SNAP_MS:
                    snap[dt] = float(held[k])
            want[n] = snap
        need = sorted({t for s in want.values() for t in s.values()})
        got = {float(s.t_ms): s.frame[y0:y1, x0:x1].copy()
               for s in ctx["cache"].samples(need, rois=["minimap"])}
        for n, it in its:
            frames = {dt: got.get(t) for dt, t in want[n].items()}
            if frames.get(0.0) is None:
                print(f"no cached frame at {it['key']}; left out", flush=True)
                continue
            x, y = it["widget_xy"]
            img = compose(frames, x, y, r_icon, r_near)
            name = f"{n:03d}.png"
            cv2.imwrite(str(out / "patches" / name), img)
            rows[n] = {"key": it["key"], "session": sid, "t_ms": it["t_cap_ms"],
                       "frame_idx": it["frame_idx"], "x": x, "y": y, "patch": name,
                       "strip_ms": {str(dt): t for dt, t in want[n].items()}}
        print(f"{sid}: {len(its)} panels", flush=True)
    (out / "ask.json").write_text(json.dumps({"tool": TOOL, "sample": str(sample),
                                              "items": [rows[n] for n in sorted(rows)]}, indent=1),
                                  encoding="utf-8")
    print(f"{len(rows)} panels in {out / 'patches'}", flush=True)
    return 0


# ----------------------------------------------------------------- ask

def ask(args) -> int:
    import tkinter as tk

    import cv2

    pdir = Path(args.patches)
    if not (pdir / "ask.json").is_file():
        prepare(Path(args.sample), pdir, args.limit)
    items = json.loads((pdir / "ask.json").read_text(encoding="utf-8"))["items"]
    target = Path(args.labels)
    target.mkdir(parents=True, exist_ok=True)
    done = load_answers(target)
    todo = [c for c in items if c["key"] not in done]
    print(f"{len(items)} items, {sum(c['key'] in done for c in items)} answered, {len(todo)} left -> {target}")
    if not todo:
        print("nothing left to label")
        return 0
    handles = {}
    st = {"i": 0, "stage": "class", "answer": None}
    keep = {}
    root = tk.Tk()
    root.title("what is drawn at the ring")
    canvas = tk.Canvas(root, width=1400, height=520, highlightthickness=0, bg="#121212")
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 12), justify="left", anchor="w")
    status.pack(fill="x")

    def show():
        if st["i"] >= len(todo):
            root.quit()
            return
        c = todo[st["i"]]
        img = cv2.imread(str(pdir / "patches" / c["patch"]), cv2.IMREAD_COLOR)
        ok, png = cv2.imencode(".png", img)
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))
        canvas.configure(width=img.shape[1], height=img.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        head = f"{st['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f} s\n"
        if st["stage"] == "class":
            status.configure(text=head + (
                "At frame 0, what is drawn where the green ticks point "
                "(an icon counts if its centre is inside the dashed circle)?\n"
                "1 enemy icon   2 red ? mark   3 X mark   4 utility/ability glyph   7 other   "
                "0 no icon, nothing there\nU unsure   A back   Q/ESC save and quit"))
        else:
            status.configure(text=head + "Enemy icon: one icon, or icons overlapping?\n"
                                         "1 one icon   2 two or more overlapping   U unsure of the count\n"
                                         "A back to the first question")

    def write(answer, count=None):
        c = todo[st["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"], "frame_idx": c["frame_idx"],
               "x": c["x"], "y": c["y"], "answer": answer, "count": count,
               "uncertain": answer == "unsure", "by": args.by, "class_set": CLASS_SET, "tool": TOOL,
               "compared_against_derived": False,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        h = handles.get(c["session"]) or handles.setdefault(
            c["session"], (target / f"{c['session']}.jsonl").open("a", encoding="utf-8"))
        h.write(json.dumps(row) + "\n")
        h.flush()
        st["i"] += 1
        st["stage"] = "class"
        show()

    def key(e):
        k = (e.char or "").lower()
        if k == "q":
            root.quit()
            return
        if st["stage"] == "class":
            if k in CLASSES:
                if CLASSES[k] == "enemy_icon":
                    st["stage"] = "count"
                    show()
                else:
                    write(CLASSES[k])
            elif k == "u":
                write("unsure")
            elif k == "a":
                st["i"] = max(0, st["i"] - 1)
                show()
            return
        if k in COUNTS:
            write("enemy_icon", COUNTS[k])
        elif k == "u":
            write("enemy_icon", "unsure")
        elif k == "a":
            st["stage"] = "class"
            show()

    root.bind("<Key>", key)
    root.bind("<Escape>", lambda _e: root.quit())
    show()
    if args.screenshot:
        def grab():
            from PIL import ImageGrab
            root.lift()
            root.attributes("-topmost", True)
            root.update()
            x0, y0 = root.winfo_rootx(), root.winfo_rooty()
            ImageGrab.grab(bbox=(x0, y0, x0 + root.winfo_width(), y0 + root.winfo_height()),
                           all_screens=True).save(args.screenshot)
            print(f"screenshot -> {args.screenshot}")
        root.after(800, grab)
    if args.smoke:
        # A test run: press the given keys in order, into a scratch directory only.
        class _E:
            def __init__(self, c):
                self.char = c
        ks = args.smoke.split(",")
        for n, c in enumerate(ks):
            root.after(1500 + 400 * n, lambda c=c: key(_E(c)))
        root.after(1500 + 400 * (len(ks) + 1), root.quit)
    root.mainloop()
    root.destroy()
    for h in handles.values():
        h.close()
    print(f"wrote {target}")
    return 0


# ----------------------------------------------------------------- score

def weighted_share(w: np.ndarray, r: np.ndarray) -> tuple[float, float, float, float]:
    """The weighted reader share, the Kish effective sample size
    `(sum w)^2 / sum w^2`, and a Wilson 95% interval at that size
    (deterministic; a resampling interval collapses where a match holds one
    item)."""
    from reticle.metrics import wilson

    share = float((w * r).sum() / w.sum())
    n_eff = float(w.sum() ** 2 / (w * w).sum())
    lo, hi = wilson(share * n_eff, n_eff)
    return share, n_eff, lo, hi


def score(items: list[dict], answers: dict) -> dict:
    """Per (set, class) and pooled per set: the answers, the decided items,
    the reader-error share unweighted (Wilson 95%) and weighted by the sample
    weights (Wilson 95% at the Kish effective size)."""
    from reticle.metrics import wilson

    groups = defaultdict(list)
    for it in items:
        groups[(it["set"], it["cls"])].append(it)
        groups[(it["set"], "ALL")].append(it)
    out = {}
    for (st, cls), its in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1] == "ALL", kv[0][1])):
        ans = Counter()
        count = Counter()
        per = defaultdict(lambda: ([], []))
        for it in its:
            a = answers.get(it["key"])
            if a is None:
                ans["unlabelled"] += 1
                continue
            ans[a["answer"]] += 1
            if a["answer"] == "enemy_icon" and a.get("count"):
                count[a["count"]] += 1
            side = ERROR_SIDE[st].get(a["answer"])
            if side is None:
                continue
            per[it["session"]][0].append(float(it["weight"]))
            per[it["session"]][1].append(1.0 if side == "reader" else 0.0)
        w = np.array([x for v in per.values() for x in v[0]])
        r = np.array([x for v in per.values() for x in v[1]])
        n = len(w)
        k = int(r.sum())
        row = {"n_items": len(its), "answers": dict(ans), "icon_count": dict(count), "decided": n,
               "reader_errors": k, "t1d_errors": n - k}
        if n:
            lo, hi = wilson(k, n)
            sw, n_eff, lw, hw = weighted_share(w, r)
            row.update({"reader_share": round(k / n, 3), "reader_ci": [round(lo, 3), round(hi, 3)],
                        "reader_share_w": round(sw, 3), "n_eff": round(n_eff, 1),
                        "reader_ci_w": [round(lw, 3), round(hw, 3)]})
        out[f"{st}__{cls}"] = row
    return out


def print_score(out: dict) -> None:
    print(f"{'set__class':32s} {'items':>5s} {'dec':>4s} {'rdr':>4s} {'t1d':>4s}  "
          f"{'reader share [95%]':22s} {'weighted [95%, n_eff]':28s} answers")
    for key, r in out.items():
        if key.endswith("__ALL"):
            print("-" * 110)
        s = (f"{r['reader_share']:.2f} [{r['reader_ci'][0]:.2f},{r['reader_ci'][1]:.2f}]"
             if r["decided"] else "-")
        sw = (f"{r['reader_share_w']:.2f} [{r['reader_ci_w'][0]:.2f},{r['reader_ci_w'][1]:.2f}] {r['n_eff']:5.1f}"
              if r["decided"] else "-")
        a = " ".join(f"{k} {v}" for k, v in sorted(r["answers"].items()))
        if r["icon_count"]:
            a += "  | count " + " ".join(f"{k} {v}" for k, v in sorted(r["icon_count"].items()))
        print(f"{key:32s} {r['n_items']:5d} {r['decided']:4d} {r['reader_errors']:4d} {r['t1d_errors']:4d}  "
              f"{s:22s} {sw:28s} {a}")


# ----------------------------------------------------------------- main

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("cmd", choices=("prepare", "ask", "score"))
    ap.add_argument("--sample", default=str(SAMPLE))
    ap.add_argument("--patches", default=None, help="panel directory (default: the store's labels dir)")
    ap.add_argument("--labels", default=None, help="answers directory (default: the store's labels dir)")
    ap.add_argument("--limit", type=int, default=None, help="prepare only the first N items (a test run)")
    ap.add_argument("--by", default="player")
    ap.add_argument("--smoke", help="comma-separated keys to press, with a scratch --labels only")
    ap.add_argument("--screenshot", help="save the window to this PNG shortly after it opens")
    ap.add_argument("--idle", action="store_true", help="run at Idle priority (prepare)")
    ap.add_argument("--out", help="score: write the table as JSON here")
    args = ap.parse_args(argv)
    default = labels_dir(STORE)
    args.patches = args.patches or str(default)
    if args.smoke and (args.labels is None or Path(args.labels).resolve() == default.resolve()):
        raise SystemExit("--smoke writes only to a scratch --labels directory")
    args.labels = args.labels or str(default)
    if args.idle:
        _idle()
    if args.cmd == "prepare":
        return prepare(Path(args.sample), Path(args.patches), args.limit)
    if args.cmd == "ask":
        return ask(args)
    items = load_sample(Path(args.sample))
    answers = load_answers(Path(args.labels))
    unknown = set(answers) - {it["key"] for it in items}
    if unknown:
        print(f"{len(unknown)} label keys are not in the sample; ignored", flush=True)
    out = score(items, answers)
    print_score(out)
    if args.out:
        Path(args.out).write_text(json.dumps({"tool": TOOL, "sample": args.sample, "labels": args.labels,
                                              "error_side": ERROR_SIDE, "classes": out}, indent=1),
                                  encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
