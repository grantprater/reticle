"""Say WHICH agent each combat report row's portrait is.

    .\\.venv\\Scripts\\python.exe prototypes\\label_report_portraits.py <session>

Controls
--------
    1 2 3 4 5     an enemy agent, in the order the key strip shows them
    6 7 8 9       an ally agent (the ALLY rows: damage to a teammate)
    0             none of these: not a portrait, or an agent not in the lineup
    U             unsure: recorded, and kept out of scoring
    A             back one
    Q / ESC       save and quit

Every row of every panel `adjudication.combat_report` found is shown once, in
time order: the portrait magnified on the left, the panel beside it with the
row outlined. The key strip along the bottom is the official killfeed portrait
art of each lineup agent, so a label is a face matched to a face. No machine
guess is shown -- the gallery match and the portrait clusters are what these
labels score, so showing either would grade them against themselves.

Why this exists
---------------
Naming report rows by the official art failed on dark and red-tinted portraits
(`combat-report-identity` in the store's predictions): they fall to one agent
at low scores. Rows grouped by direct thumbnail correlation look like one group
per player, but that grouping is my own. These labels are the ground truth both
are scored on. Labels go to `<store>/labels/combat_report_portrait/<session>.jsonl`,
append-only, last row per key wins; the run is resumable.
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
from reticle.combat_report import PITCH, ROW0  # noqa: E402
from reticle.lineup import load_lineup  # noqa: E402
from reticle.store import Store  # noqa: E402

import combat_report as proto  # noqa: E402

KIND = "combat_report_portrait"
PANEL = (-128, -10, 272, 0)       # panel crop around the rows: x0, y0 above ROW0, x1, extra below


def items_to_label(sid: str) -> list[dict]:
    """One item per row of each panel, at a frame that shows its modal read."""
    frames = proto._frames(sid)
    out = []
    for p in proto._panels(sid):
        want = tuple(tuple(row[f] for f in proto.adj.FIELDS) for row in p["rows"])
        shown = [r for r in frames if p["start_ms"] <= r["t_ms"] <= p["end_ms"]
                 and "rows" in r and (r.get("header") or 0) >= proto.adj.HEADER_MIN
                 and proto.adj.frame_read(r) == want]
        if not shown:
            continue
        r = shown[len(shown) // 2]
        for k in range(len(p["rows"])):
            out.append({"t_ms": r["t_ms"], "panel_start_ms": p["start_ms"], "row": k,
                        "rows": len(p["rows"]), "hx": r["hx"], "hy": r["hy"],
                        "kind": p["kind"]})
    return out


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("session")
    ap.add_argument("--zoom", type=int, default=5)
    args = ap.parse_args()
    sid = args.session
    store = Store()
    lineup = load_lineup(sid, store.root)
    player = (lineup.get("player") or {}).get("agent")
    enemy = [r.get("agent") or r.get("best_guess") for r in lineup["sides"]["enemy"]]
    allies = [a for a in (r.get("agent") or r.get("best_guess") for r in lineup["sides"]["ally"])
              if a and a != player][:4]
    names = enemy + allies
    art_dir = store.root / "reference" / "assets" / "agents"
    key = []
    for n in names:
        img = cv2.imread(str(art_dir / f"{n}_killfeed_portrait.png"), cv2.IMREAD_UNCHANGED)
        if img is None:
            img = np.zeros((64, 128, 4), np.uint8)
        if img.shape[2] == 4:
            alpha = img[:, :, 3:4] / 255.0
            img = (img[:, :, :3] * alpha + 25 * (1 - alpha)).astype(np.uint8)
        key.append(img)

    out_path = store.root / "labels" / KIND / f"{sid}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.is_file():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                if r.get("by", "human") == "human":
                    done.add((r["panel_start_ms"], r["row"]))
    items = [i for i in items_to_label(sid) if (i["panel_start_ms"], i["row"]) not in done]
    if not items:
        print("every report row in this session already has a label")
        return 0
    print(f"{len(done)} already done, {len(items)} to go")

    src = store.read_manifest(sid)["source"]
    fps = float(src["fps"])
    cap = cv2.VideoCapture(src["path"])
    fh = out_path.open("a", encoding="utf-8")
    state = {"i": 0, "img": None, "written": 0}

    root = tk.Tk()
    root.title("reticle - which agent is this report row?")
    canvas = tk.Canvas(root, highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")
    KEY_W, KEY_H = 150, 75

    def show():
        it = items[state["i"]]
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(round(it["t_ms"] / 1000.0 * fps)))
        ok, frame = cap.read()
        if not ok:
            step(+1, None)
            return
        hx, hy = it["hx"], it["hy"]
        y_row = hy + ROW0 + it["row"] * PITCH
        portrait = frame[y_row - 2:y_row + PITCH, hx - 30:hx + 45]
        big = cv2.resize(portrait, None, fx=args.zoom, fy=args.zoom,
                         interpolation=cv2.INTER_CUBIC)
        py0 = hy + ROW0 + PANEL[1]
        py1 = hy + ROW0 + it["rows"] * PITCH + 4
        panel = frame[py0:py1, hx + PANEL[0]:hx + PANEL[2]].copy()
        ry = ROW0 + it["row"] * PITCH - (ROW0 + PANEL[1])
        cv2.rectangle(panel, (1, ry), (panel.shape[1] - 2, ry + PITCH), (64, 255, 64), 2)
        s = big.shape[0] / max(1, panel.shape[0])
        panel = cv2.resize(panel, None, fx=min(s, 2.0), fy=min(s, 2.0),
                           interpolation=cv2.INTER_CUBIC)
        h = max(big.shape[0], panel.shape[0])
        pad = lambda im: np.vstack([im, np.full((h - im.shape[0], im.shape[1], 3), 25, np.uint8)])
        view = np.hstack([pad(big), np.full((h, 12, 3), 25, np.uint8), pad(panel)])
        strip_w = max(view.shape[1], len(key) * (KEY_W + 10) + 10)
        if view.shape[1] < strip_w:
            view = np.hstack([view, np.full((h, strip_w - view.shape[1], 3), 25, np.uint8)])
        strip = np.full((KEY_H + 40, strip_w, 3), 25, np.uint8)
        for k, art in enumerate(key):
            a = cv2.resize(art, (KEY_W, KEY_H), interpolation=cv2.INTER_AREA)
            x = 10 + k * (KEY_W + 10)
            strip[6:6 + KEY_H, x:x + KEY_W] = a
        view = np.vstack([view, strip])
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        for k, nm in enumerate(names):
            x = 10 + k * (KEY_W + 10)
            side = "enemy" if k < len(enemy) else "ally"
            canvas.create_text(x + 4, view.shape[0] - KEY_H - 32, anchor="nw",
                               fill="#ffd020" if side == "enemy" else "#40c0ff",
                               font=("Consolas", 14, "bold"), text=f"{k + 1 if k < 9 else ''}")
            canvas.create_text(x, view.shape[0] - 26, anchor="nw", fill="#c0c0c0",
                               font=("Consolas", 10), text=f"{nm} ({side})")
        t = int(it["t_ms"]) // 1000
        status.config(text=f"  {state['i'] + 1}/{len(items)}   {t // 60}:{t % 60:02d}   "
                           f"{it['kind']} panel, row {it['row'] + 1} of {it['rows']}   "
                           f"1-5 enemy  6-9 ally  0 none of these  U unsure  A back  Q quit")

    def step(delta, write):
        if write is not None:
            it = items[state["i"]]
            fh.write(json.dumps({
                "session_id": sid, "t_ms": it["t_ms"], "panel_start_ms": it["panel_start_ms"],
                "row": it["row"], "hx": it["hx"], "hy": it["hy"], "panel_kind": it["kind"],
                "agent": write if write not in ("__unsure__", "__none__") else None,
                "none_of_these": write == "__none__", "uncertain": write == "__unsure__",
                "by": "human", "lineup": names}) + chr(10))
            fh.flush()
            state["written"] += 1
        state["i"] += delta
        if not (0 <= state["i"] < len(items)):
            finish()
            return
        show()

    def finish():
        fh.close()
        cap.release()
        print(f"wrote {state['written']} labels to {out_path}")
        root.destroy()

    for k, nm in enumerate(names[:9]):
        root.bind(str(k + 1), lambda e, nm=nm: step(+1, nm))
    root.bind("0", lambda e: step(+1, "__none__"))
    root.bind("u", lambda e: step(+1, "__unsure__"))
    root.bind("a", lambda e: step(-1, None))
    root.bind("q", lambda e: finish())
    root.bind("<Escape>", lambda e: finish())
    root.protocol("WM_DELETE_WINDOW", finish)
    show()
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
