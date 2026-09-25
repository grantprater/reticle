"""Say WHICH weapon, ability or environmental death each killfeed icon group is.

    .\\.venv\\Scripts\\python.exe prototypes\\label_weapon_icons.py [--min 2]

Controls
--------
    click a button   the icon's name: one of the 19 guns, Melee, Ability,
                     Environmental (a fall, a door, the spike) or Other
    M                mixed: the six icons shown are not all one thing
    U                unsure: recorded, and kept out of scoring
    A                back one
    Q / ESC          save and quit

`prototypes/weapon_icons.py` groups every mined killfeed icon without labels.
Each group is shown once, largest first: its founding icon top left and five
members spread across its similarity range, each on its own plate and
magnified. The answer names the founding icon and, unless marked mixed, the
group. No machine name is shown -- the ammo-pair names are what these labels
check, so showing them would grade the naming against itself.

Labels go to `<store>/labels/weapon_icon/<session of the founding icon>.jsonl`,
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
from reticle.adjudication.weapon import WEAPON_ADJUDICATION_VERSION  # noqa: E402
from reticle.store import Store  # noqa: E402

import weapon_icons as proto  # noqa: E402

KIND = "weapon_icon"
SHOWN = 6
ZOOM = 3
CLASSES = [
    ("Sidearm", ["Classic", "Shorty", "Frenzy", "Ghost", "Bandit", "Sheriff"]),
    ("SMG", ["Stinger", "Spectre"]),
    ("Shotgun", ["Bucky", "Judge"]),
    ("Rifle", ["Bulldog", "Guardian", "Phantom", "Vandal"]),
    ("Sniper", ["Marshal", "Outlaw", "Operator"]),
    ("Machine gun", ["Ares", "Odin"]),
    ("Not a gun", ["Melee", "Ability", "Environmental", "Other"]),
]


icon_key = proto.icon_key


def groups_to_label(min_n: int) -> tuple[list[dict], np.ndarray]:
    rows, bms, crops = proto.load_all()
    have = proto.cluster(rows, bms)
    by: dict[int, list[dict]] = {}
    for r in have:
        by.setdefault(r["cluster"], []).append(r)
    out = []
    for c, rs in sorted(by.items(), key=lambda kv: -len(kv[1])):
        if len(rs) < min_n:
            continue
        lead = next(r for r in rs if r.get("leader"))
        rest = sorted((r for r in rs if r is not lead), key=lambda r: -r["leader_iou"])
        pick = [rest[int(k)] for k in np.linspace(0, len(rest) - 1, min(SHOWN - 1, len(rest)))]
        out.append({"cluster": c, "n": len(rs), "lead": lead, "members": pick})
    return out, crops


def tile(crop: np.ndarray, r: dict) -> np.ndarray:
    icon = crop[:r["band_h"], :r["box_w"]]
    big = cv2.resize(icon, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_CUBIC)
    cell = np.full((proto.CROP[0] * ZOOM + 16, proto.CROP[1] * ZOOM + 16, 3), 25, np.uint8)
    cell[8:8 + big.shape[0], 8:8 + big.shape[1]] = big
    return cell


def main() -> int:
    import tkinter as tk

    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=2, help="smallest group to ask about")
    args = ap.parse_args()
    root_dir = Store().root / "labels" / KIND
    root_dir.mkdir(parents=True, exist_ok=True)
    done = set()
    for p in root_dir.glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(json.loads(line)["key"])
    items, crops = groups_to_label(args.min)
    items = [g for g in items if icon_key(g["lead"]) not in done]
    if not items:
        print("every group already has a label")
        return 0
    print(f"{len(done)} already done, {len(items)} groups to go")

    handles: dict[str, object] = {}
    state = {"i": 0, "img": None, "written": 0}
    root = tk.Tk()
    root.title("reticle - which weapon is this killfeed icon?")
    canvas = tk.Canvas(root, highlightthickness=0, bg="#191919")
    canvas.pack()
    status = tk.Label(root, anchor="w", font=("Consolas", 11))
    status.pack(fill="x")
    pad = tk.Frame(root)
    pad.pack(fill="x", padx=6, pady=6)

    def show():
        g = items[state["i"]]
        cells = [tile(crops[r["icon"]], r) for r in [g["lead"]] + g["members"]]
        cells += [np.full_like(cells[0], 25)] * (SHOWN - len(cells))
        view = np.vstack([np.hstack(cells[k:k + 3]) for k in (0, 3)])
        cv2.rectangle(view, (2, 2), (cells[0].shape[1] - 3, cells[0].shape[0] - 3),
                      (64, 255, 64), 2)
        _ok, buf = cv2.imencode(".png", view)
        state["img"] = tk.PhotoImage(data=base64.b64encode(buf.tobytes()))
        canvas.config(width=view.shape[1], height=view.shape[0])
        canvas.delete("all")
        canvas.create_image(0, 0, anchor="nw", image=state["img"])
        status.config(text=f"  group {state['i'] + 1}/{len(items)}   {g['n']} icons   "
                           f"outlined: the founding icon   M mixed  U unsure  A back  Q quit")

    def handle(r: dict, session: str):
        if session not in handles:
            handles[session] = (root_dir / f"{session}.jsonl").open("a", encoding="utf-8")
        return handles[session]

    def step(delta, answer):
        if answer is not None:
            g = items[state["i"]]
            lead = g["lead"]
            cls = next((c for c, ns in CLASSES if answer in ns), None)
            row = {"key": icon_key(lead), "session_id": lead["session_id"],
                   "t_ms": lead["t_ms"], "t_first": lead["t_first"], "slot": lead["slot"],
                   "answer": answer if answer not in ("__unsure__", "__mixed__") else None,
                   "class": cls, "uncertain": answer == "__unsure__",
                   "mixed": answer == "__mixed__", "group_size": g["n"],
                   "members_shown": [icon_key(r) for r in g["members"]],
                   "group_rule": {"same_icon": proto.SAME_ICON, "aspect_tol": proto.ASPECT_TOL,
                                  "mask": WEAPON_ADJUDICATION_VERSION, "mine": proto.VERSION},
                   "by": "player"}
            fh = handle(lead, lead["session_id"])
            fh.write(json.dumps(row) + "\n")
            fh.flush()
            state["written"] += 1
        state["i"] += delta
        if not (0 <= state["i"] < len(items)):
            finish()
            return
        show()

    def finish():
        for fh in handles.values():
            fh.close()
        print(f"wrote {state['written']} labels under {root_dir}")
        root.destroy()

    for row_i, (cls, names) in enumerate(CLASSES):
        tk.Label(pad, text=cls, width=12, anchor="e", font=("Consolas", 10)).grid(
            row=row_i, column=0, sticky="e")
        for col, nm in enumerate(names):
            tk.Button(pad, text=nm, width=13, command=lambda nm=nm: step(+1, nm)).grid(
                row=row_i, column=col + 1, padx=2, pady=1)
    root.bind("m", lambda e: step(+1, "__mixed__"))
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
