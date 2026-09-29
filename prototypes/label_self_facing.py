r"""Ask the player which way the self icon points, to score the teardrop facing.

    .\.venv\Scripts\python.exe prototypes\label_self_facing.py --prepare
    .\.venv\Scripts\python.exe prototypes\label_self_facing.py

E4 of [the statistical adjudicator](../docs/STATISTICAL_ADJUDICATOR.md) left
the teardrop facing (`teardrop_tip.py`) unconfirmed on a second map. On
5822b6646448 (Lotus, C:\Users\grant\Videos\2026-08-26 12-38-38.mp4) it reads
steadily but agrees with the drawn light only to a median 10.8 degrees with 9%
flipped, and no light witness separates a reader error from walls and stacked
teammates. The drawn light cannot judge it there; the player can.
`self_facing_eval.py` scores the answers.

**Prepare** reads the minimap crop cache (no decode) every `STRIDE`-th frame,
runs the self detector, the teardrop fit, the ring fit and E4's light-fitted
facing (`cone_origin.light_facing` on the joined light), and draws about fifty
items in six strata, each at least `GAP_MS` from the others (`CONTROL_GAP_MS`
on the 48 s control clip):

    flip      the teardrop and the light-fitted facing differ by over 90
              degrees (11% of lit read frames on Lotus)
    disagree  they differ by 20 to 90 degrees (`MID_DEG`)
    agree     they differ by at most `AGREE_DEG`
    refused   the detector found a self candidate the teardrop refuses
              (E4 saw these lock on a yellow ability icon in a stack)
    random    read frames drawn with no regard to the light, so a rate over
              all read frames can be estimated without the strata's bias
    control   read frames of e78e75b2d191 (Ascent), where the light agreed
              to 1.9 degrees

`index.json` holds each item and why it was chosen; `readings.json` holds every
pooled frame's readings. The labeller shows neither: it rings the candidate at
the teardrop's centre (the portrait's centre, which carries no facing) or, where
the teardrop refuses, at the detector's centre, and asks blind.

**Ask.** Two panels: the icon at 10x and the map round it at 3x, the same place
ringed in both. Click in either panel.

    left-click   first the CENTRE of the portrait, then the TIP it points to
    right-click  undo the last mark
    SPACE / D    save and advance (needs both marks)
    U            can't tell -- recorded, kept OUT of scoring
    N            the ringed thing is NOT the self icon
    A            back one (re-answer; the last row for a key wins)
    Q / ESC      save and quit

Answers append to `labels/self_facing_lotus_20260928.jsonl`, keyed by session
and time, flushed per row; a restart skips answered keys. Rows hold the clicks
in crop pixels and the facing in image degrees (y down), as `teardrop_tip`
reports it, and no reader value. Never seed this file.
"""
from __future__ import annotations

import argparse
import base64
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sliver_error_model as sem  # noqa: E402  (sets thread limits first)

VERSION = "label-self-facing-0.1.0"
CLASS_SET = "self_facing-1"
NAME = "self_facing_lotus_20260928"
LOTUS, CONTROL = "5822b6646448", sem.DEMO
STRIDE = 10                  # every 10th cached frame, about one a second on Lotus
GAP_MS = 5000.0              # items at least this far apart within a session
CONTROL_GAP_MS = 3000.0      # the Ascent control clip lasts 48 s
AGREE_DEG = 5.0
MID_DEG = (20.0, 90.0)
QUOTA = {"flip": 8, "disagree": 7, "agree": 12, "refused": 10, "random": 5, "control": 8}
SEED = 20260928
CTX = 90                     # patch half-width, crop px
ZH, ZF = 26, 10              # zoom panel: half-width and factor
CF = 3                       # context panel factor
RING_R = 23.0                # ring radius, crop px: outside the 18 px apex
RING = (255, 0, 255)
GAP_PX = 10


def items_dir(store: Path) -> Path:
    return store / "labels" / NAME


def labels_path(store: Path) -> Path:
    return store / "labels" / f"{NAME}.jsonl"


def item_key(sid: str, t_ms: float) -> str:
    return f"{sid}|{float(t_ms):.1f}"


def load_answers(path: Path) -> dict:
    """Last row for a key wins, so `A`-then-reanswer corrects rather than duplicates."""
    out = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                out[r["key"]] = r
    return out


# ---------------------------------------------------------------- prepare

def read_pool(s, times) -> list[dict]:
    """The self detector, the teardrop, the ring fit and the light on `times`."""
    import cone_origin as co
    import teardrop_tip as tt
    from reticle import lighting
    pool, prev = [], None
    for t, crop in s.crops(times):
        det = tt.self_start(crop, s.floor)
        if det is None:
            continue
        tf = tt.fit(crop, det["cx"], det["cy"])
        row = {"session": s.sid, "t_ms": float(t), "det_x": float(det["cx"]), "det_y": float(det["cy"]),
               "ring_deg": det.get("facing"), "read": bool(tf.get("read")),
               "reason": tf.get("reason"), "ncc": tf.get("ncc")}
        if "x" in tf:
            row.update(tip_x=tf["x"], tip_y=tf["y"], tip_deg=tf["deg"])
        # The minimap repeats an image across cached frames; keep one of each.
        k = (round(row["det_x"], 2), round(row["det_y"], 2), round(row.get("tip_deg") or 0.0, 2))
        if k == prev:
            continue
        prev = k
        if row["read"]:
            raw = lighting.raw_lit(crop, s.ref)
            reg = co.region_of(s, tf)
            wit = co.joined(raw, reg, tf)
            row["lit_px"] = int(wit.sum())
            if row["lit_px"] >= co.MIN_LIT:
                lf, pl = co.light_facing(s, tf, wit, reg)
                if lf is not None:
                    row["light_deg"] = lf
                    row["light_plateau_deg"] = int(pl.sum())
                    row["tip_vs_light_deg"] = float(abs(sem._signed_deg(tf["deg"] - lf)))
        pool.append(row)
    return pool


def spaced(cands, n, taken, rng=None, gap=GAP_MS):
    """Up to `n` of `cands` in order (shuffled first when `rng`), each `gap` from every taken item."""
    cands = list(cands)
    if rng is not None:
        rng.shuffle(cands)
    out = []
    for c in cands:
        if len(out) >= n:
            break
        if all(c["session"] != o["session"] or abs(c["t_ms"] - o["t_ms"]) >= gap for o in taken + out):
            out.append(c)
    return out


def select(pool_b, pool_a) -> list[dict]:
    rng = random.Random(SEED)
    taken: list[dict] = []
    lit = [r for r in pool_b if r["read"] and "tip_vs_light_deg" in r]
    flip = spaced([r for r in lit if r["tip_vs_light_deg"] > 90.0], QUOTA["flip"], taken, rng)
    for r in flip:
        r["stratum"] = "flip"
        r["why"] = f"teardrop and light-fitted facing differ by {r['tip_vs_light_deg']:.0f} deg (over 90)"
    taken += flip
    lo, hi = MID_DEG
    dis = spaced([r for r in lit if lo < r["tip_vs_light_deg"] <= hi], QUOTA["disagree"], taken, rng)
    for r in dis:
        r["stratum"] = "disagree"
        r["why"] = f"teardrop and light-fitted facing differ by {r['tip_vs_light_deg']:.0f} deg ({lo:.0f}-{hi:.0f})"
    taken += dis
    agr = spaced([r for r in lit if r["tip_vs_light_deg"] <= AGREE_DEG], QUOTA["agree"], taken, rng)
    for r in agr:
        r["stratum"] = "agree"
        r["why"] = f"teardrop and light-fitted facing within {AGREE_DEG:.0f} deg ({r['tip_vs_light_deg']:.1f})"
    taken += agr
    ref = spaced([r for r in pool_b if not r["read"]], QUOTA["refused"], taken, rng)
    for r in ref:
        r["stratum"] = "refused"
        r["why"] = f"self detection the teardrop refuses ({r['reason']}, ncc {r['ncc'] if r['ncc'] is not None else 'n/a'})"
    taken += ref
    rnd = spaced([r for r in pool_b if r["read"]], QUOTA["random"], taken, rng)
    for r in rnd:
        r["stratum"] = "random"
        r["why"] = "read frame drawn uniformly, light ignored"
    taken += rnd
    ctl = spaced([r for r in pool_a if r["read"]], QUOTA["control"], taken, rng, CONTROL_GAP_MS)
    for r in ctl:
        r["stratum"] = "control"
        r["why"] = "read frame of the Ascent control session, drawn uniformly"
    taken += ctl
    rng.shuffle(taken)
    return taken


def patch_of(crop: np.ndarray, cx: float, cy: float):
    """A (2*CTX+1)^2 lossless patch round (cx, cy), black past the crop; its origin in crop px."""
    x0, y0 = int(round(cx)) - CTX, int(round(cy)) - CTX
    pad = cv2.copyMakeBorder(crop, CTX, CTX, CTX, CTX, cv2.BORDER_CONSTANT)
    return pad[y0 + CTX:y0 + 3 * CTX + 1, x0 + CTX:x0 + 3 * CTX + 1].copy(), x0, y0


def prepare(store: Path, reuse: Path | None = None) -> int:
    sem._below_normal()
    out = items_dir(store)
    if (out / "index.json").is_file():
        raise SystemExit(f"{out / 'index.json'} exists; a new item set needs a new NAME")
    (out / "patches").mkdir(parents=True, exist_ok=True)
    sessions = {}
    pools = {}
    if reuse is not None:
        # The readings are deterministic in the code and the cache; a pool read
        # by this version at this stride need not be read again.
        old = json.loads(reuse.read_text(encoding="utf-8"))
        if old["meta"]["version"] != VERSION or old["meta"]["stride"] != STRIDE:
            raise SystemExit(f"{reuse}: read by {old['meta']['version']} at stride {old['meta']['stride']}")
    for sid in (LOTUS, CONTROL):
        s = sem.Session(sid)
        sessions[sid] = s
        if reuse is not None:
            pools[sid] = old["pool"][sid]
            print(f"{sid}: {len(pools[sid])} distinct detections from {reuse}", flush=True)
            continue
        T = np.unique(np.asarray(s.cache_t, float))
        times = T[::STRIDE]
        if sid == CONTROL:
            times = [t for t in times if all(abs(t - h) > sem.HOLDOUT_MS for h in sem.SLIVERS)]
        print(f"{sid}: reading {len(times)} of {len(T)} cached frames", flush=True)
        pools[sid] = read_pool(s, times)
        p = pools[sid]
        print(f"  {len(p)} distinct detections, {sum(r['read'] for r in p)} read, "
              f"{sum('light_deg' in r for r in p)} with a light-fitted facing", flush=True)
    items = select(pools[LOTUS], pools[CONTROL])
    index = []
    for sid in (LOTUS, CONTROL):
        mine = sorted((r for r in items if r["session"] == sid), key=lambda r: r["t_ms"])
        s = sessions[sid]
        for r, (t, crop) in zip(mine, s.crops([r["t_ms"] for r in mine])):
            assert abs(t - r["t_ms"]) < 1e-6, (t, r["t_ms"])
            # The ring sits on the portrait's centre where the teardrop reads,
            # the detector's where it refuses: neither carries a facing.
            cx, cy = (r["tip_x"], r["tip_y"]) if r["read"] else (r["det_x"], r["det_y"])
            patch, x0, y0 = patch_of(crop, cx, cy)
            name = f"{sid}_{int(round(t))}.png"
            cv2.imwrite(str(out / "patches" / name), patch)
            r.update(key=item_key(sid, t), ring_x=cx, ring_y=cy, patch=name, patch_x0=x0, patch_y0=y0)
    for r in items:
        index.append({k: r[k] for k in ("key", "session", "t_ms", "ring_x", "ring_y", "patch",
                                        "patch_x0", "patch_y0", "stratum", "why")})
    meta = {"version": VERSION, "class_set": CLASS_SET, "stride": STRIDE, "gap_ms": GAP_MS,
            "control_gap_ms": CONTROL_GAP_MS, "agree_deg": AGREE_DEG, "mid_deg": MID_DEG, "quota": QUOTA, "seed": SEED,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    (out / "index.json").write_text(json.dumps({"meta": meta, "items": index}, indent=1), encoding="utf-8")
    (out / "readings.json").write_text(json.dumps({"meta": meta, "pool": pools}, indent=0), encoding="utf-8")
    counts = {k: sum(r["stratum"] == k for r in index) for k in QUOTA}
    print(f"prepared {len(index)} items -> {out}  {counts}")
    return 0


# ---------------------------------------------------------------- ask

def compose(patch: np.ndarray) -> np.ndarray:
    """The zoom panel and the context panel side by side, the candidate ringed in both."""
    c = CTX
    z = patch[c - ZH:c + ZH + 1, c - ZH:c + ZH + 1]
    zoom = cv2.resize(z, None, fx=ZF, fy=ZF, interpolation=cv2.INTER_NEAREST)
    ctx = cv2.resize(patch, None, fx=CF, fy=CF, interpolation=cv2.INTER_NEAREST)
    zc = int((ZH + 0.5) * ZF)
    cv2.circle(zoom, (zc, zc), int(RING_R * ZF), RING, 1, cv2.LINE_AA)
    cc = int((c + 0.5) * CF)
    cv2.circle(ctx, (cc, cc), int(RING_R * CF), RING, 1, cv2.LINE_AA)
    # A 10-crop-pixel bar, so the magnification cannot be mistaken.
    cv2.line(zoom, (8, zoom.shape[0] - 10), (8 + 10 * ZF, zoom.shape[0] - 10), (230, 230, 230), 2)
    h = max(zoom.shape[0], ctx.shape[0])
    pad = lambda im: cv2.copyMakeBorder(im, 0, h - im.shape[0], 0, 0, cv2.BORDER_CONSTANT, value=(18, 18, 18))
    gap = np.full((h, GAP_PX, 3), 18, np.uint8)
    return np.hstack([pad(zoom), gap, pad(ctx)])


def screen_to_patch(sx: float, sy: float):
    """A click on the composite, in patch px (pixel centres at integers), or None."""
    zw = (2 * ZH + 1) * ZF
    if sx < zw:
        return sx / ZF - 0.5 + (CTX - ZH), sy / ZF - 0.5 + (CTX - ZH)
    sx -= zw + GAP_PX
    if 0 <= sx < (2 * CTX + 1) * CF:
        return sx / CF - 0.5, sy / CF - 0.5
    return None


def patch_to_screens(px: float, py: float):
    zw = (2 * ZH + 1) * ZF
    out = [((px - (CTX - ZH) + 0.5) * ZF, (py - (CTX - ZH) + 0.5) * ZF)]
    out.append(((px + 0.5) * CF + zw + GAP_PX, (py + 0.5) * CF))
    return out


def grab(root, path: Path) -> None:
    """Save the window's own pixels with PrintWindow, so a window on top of it
    (the player may be working) does not end up in the picture."""
    import ctypes
    from ctypes import wintypes
    root.update()
    u, g = ctypes.windll.user32, ctypes.windll.gdi32
    hwnd = u.GetParent(root.winfo_id()) or root.winfo_id()
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    hdc = u.GetWindowDC(hwnd)
    mdc = g.CreateCompatibleDC(hdc)
    bmp = g.CreateCompatibleBitmap(hdc, w, h)
    g.SelectObject(mdc, bmp)
    u.PrintWindow(hwnd, mdc, 2)                      # PW_RENDERFULLCONTENT
    info = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
    buf = (ctypes.c_ubyte * (w * h * 4))()
    g.GetDIBits(mdc, bmp, 0, h, buf, info, 0)
    g.DeleteObject(bmp)
    g.DeleteDC(mdc)
    u.ReleaseDC(hwnd, hdc)
    img = np.frombuffer(buf, np.uint8).reshape(h, w, 4)[..., :3]
    cv2.imwrite(str(path), img)


def ask(args, store: Path) -> int:
    import tkinter as tk
    idir = items_dir(store)
    index = json.loads((idir / "index.json").read_text(encoding="utf-8"))["items"]
    target = Path(args.labels) if args.labels else labels_path(store)
    done = load_answers(target)
    todo = [c for c in index if c["key"] not in done]
    print(f"{len(index)} items, {len(done)} answered, {len(todo)} left -> {target}")
    if not todo:
        print("nothing left to label")
        return 0
    handle = None if args.screenshot else target.open("a", encoding="utf-8")
    st = {"i": 0, "marks": []}
    keep = {}

    root = tk.Tk()
    root.title("which way does the self icon point")
    zw = (2 * ZH + 1) * ZF
    W = zw + GAP_PX + (2 * CTX + 1) * CF
    H = max(zw, (2 * CTX + 1) * CF)
    canvas = tk.Canvas(root, width=W, height=H, highlightthickness=0, bg="#121212", cursor="crosshair")
    canvas.pack()
    status = tk.Label(root, font=("Consolas", 11), justify="left", anchor="w")
    status.pack(fill="x")

    def draw_marks():
        canvas.delete("mark")
        pts = [patch_to_screens(*m) for m in st["marks"]]
        for panel in (0, 1):
            if len(pts) == 2:
                (x1, y1), (x2, y2) = pts[0][panel], pts[1][panel]
                canvas.create_line(x1, y1, x2, y2, fill="#00ff66", width=2, arrow="last", tags="mark")
            for j, p in enumerate(pts):
                x, y = p[panel]
                r = 6 if panel == 0 else 4
                canvas.create_oval(x - r, y - r, x + r, y + r, outline="#00ffff" if j == 0 else "#ff3030",
                                   width=2, tags="mark")
        c = todo[st["i"]]
        marks = ("click the CENTRE of the portrait" if not st["marks"] else
                 "click the TIP it points to" if len(st["marks"]) == 1 else "SPACE to save")
        status.configure(text=(
            f"{st['i'] + 1}/{len(todo)}   {c['session']}  t={c['t_ms'] / 1000:.2f}s   -- {marks}\n"
            "Is the ringed thing your own (self) icon? Click its centre, then its tip.  right-click undo\n"
            "SPACE/D save   U can't tell   N not the self icon   A back   Q/ESC quit"))

    def show():
        if st["i"] >= len(todo):
            root.quit()
            return
        c = todo[st["i"]]
        patch = cv2.imread(str(idir / "patches" / c["patch"]), cv2.IMREAD_COLOR)
        ok, png = cv2.imencode(".png", compose(patch))
        keep["img"] = tk.PhotoImage(data=base64.b64encode(png.tobytes()))   # keep the reference
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=keep["img"])
        st["marks"] = []
        draw_marks()

    def write(answer, extra=None):
        c = todo[st["i"]]
        row = {"key": c["key"], "session": c["session"], "t_ms": c["t_ms"],
               "ring_x": c["ring_x"], "ring_y": c["ring_y"], "answer": answer, **(extra or {}),
               "by": args.by, "class_set": CLASS_SET, "tool": VERSION,
               "compared_against_derived": False,
               "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        if handle is not None:
            handle.write(json.dumps(row) + "\n")
            handle.flush()          # read the file as it fills
        st["i"] += 1
        show()

    def click(e):
        p = screen_to_patch(e.x, e.y)
        if p is None:
            return
        if len(st["marks"]) < 2:
            st["marks"].append(p)
        else:
            st["marks"][1] = p
        draw_marks()

    def undo(_e):
        if st["marks"]:
            st["marks"].pop()
            draw_marks()

    def save(_e):
        if len(st["marks"]) < 2:
            root.bell()
            return
        c = todo[st["i"]]
        (px, py), (qx, qy) = st["marks"]
        cx, cy = px + c["patch_x0"], py + c["patch_y0"]
        tx, ty = qx + c["patch_x0"], qy + c["patch_y0"]
        if math.hypot(tx - cx, ty - cy) < 1.0:
            root.bell()
            return
        write("facing", {"centre_x": round(cx, 2), "centre_y": round(cy, 2),
                         "tip_x": round(tx, 2), "tip_y": round(ty, 2),
                         "facing_deg": round(math.degrees(math.atan2(ty - cy, tx - cx)), 2)})

    def back(_e):
        st["i"] = max(0, st["i"] - 1)
        show()

    canvas.bind("<Button-1>", click)
    canvas.bind("<Button-3>", undo)
    for k in ("<space>", "d", "D"):
        root.bind(k, save)
    for k in ("u", "U"):
        root.bind(k, lambda _e: write("cant_tell"))
    for k in ("n", "N"):
        root.bind(k, lambda _e: write("not_self"))
    for k in ("a", "A"):
        root.bind(k, back)
    for k in ("q", "Q", "<Escape>"):
        root.bind(k, lambda _e: root.quit())
    show()
    if args.screenshot:
        # Two arbitrary marks, only to show how they draw; nothing is written.
        root.after(400, lambda: (st["marks"].extend([(CTX - 3.0, CTX + 2.0), (CTX + 14.0, CTX - 9.0)]),
                                 draw_marks()))
        root.after(1200, lambda: (grab(root, Path(args.screenshot)), root.quit()))
    root.mainloop()
    root.destroy()
    if handle is not None:
        handle.close()
        print(f"wrote {target}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--store", default=str(sem.STORE))
    ap.add_argument("--prepare", action="store_true")
    ap.add_argument("--labels", help="answers file (default: the store's labels/" + NAME + ".jsonl)")
    ap.add_argument("--screenshot", help="render the first item, save the window as PNG, write nothing")
    ap.add_argument("--reuse-readings", type=Path, help="prepare from a readings.json this version wrote")
    ap.add_argument("--by", default="player")
    args = ap.parse_args(argv)
    store = Path(args.store)
    if args.prepare:
        return prepare(store, args.reuse_readings)
    return ask(args, store)


if __name__ == "__main__":
    raise SystemExit(main())
