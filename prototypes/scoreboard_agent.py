"""Which agent is in each scoreboard row, from the row's own portrait art.

Prototype for `death-scoreboard-binding`. The scoreboard portrait is the
official square `agent_icon` drawing at row height, so this matches pixels on
the SAME drawing rather than colour histograms across surfaces. The box is
`[table_x0, table_x0 + row_h]`, read from source: the stored `portrait_x0`
lands 9-41 px right of it and moves between openings on one table.

Per-row mean/std normalisation (TM_CCOEFF_NORMED) is what lets a dimmed dead
row still be read; the dimming itself is measured separately as relative
brightness within one opening.

    python prototypes/scoreboard_agent.py [SESSION T0 T1]
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reticle.store import Store

SCALES = range(30, 42, 2)
PAD = 5


def load_icons(store: Store) -> dict[str, tuple[list, list]]:
    """Each agent's `agent_icon` resized to every search scale, with its alpha."""
    out = {}
    for f in sorted(glob.glob(str(store.root / "reference/assets/agents/*_agent_icon.png"))):
        name = os.path.basename(f)[: -len("_agent_icon.png")]
        im = cv2.imread(f, cv2.IMREAD_UNCHANGED)
        ims, masks = [], []
        for s in SCALES:
            r = cv2.resize(im, (s, s), interpolation=cv2.INTER_AREA)
            ims.append(r[:, :, :3].copy())
            masks.append(np.repeat((r[:, :, 3:4] > 200).astype(np.uint8), 3, 2))
        out[name] = (ims, masks)
    return out


def portrait_box(row: dict) -> tuple[int, int, int, int]:
    h = row["row_y1"] - row["row_y0"]
    return row["table_x0"], row["row_y0"], row["table_x0"] + h, row["row_y1"]


def score_row(frame, row, icons) -> dict:
    x0, y0, x1, y1 = portrait_box(row)
    win = frame[max(0, y0 - PAD):y1 + PAD, max(0, x0 - PAD):x1 + PAD]
    scores, where = {}, {}
    for name, (ims, masks) in icons.items():
        best = (-1.0, None)
        for i, (t, m) in enumerate(zip(ims, masks)):
            if t.shape[0] > win.shape[0] or t.shape[1] > win.shape[1]:
                continue
            r = cv2.matchTemplate(win, t, cv2.TM_CCOEFF_NORMED, mask=m)
            r = np.nan_to_num(r, nan=-1.0, posinf=-1.0, neginf=-1.0)
            _, v, _, loc = cv2.minMaxLoc(r)
            if v > best[0]:
                best = (float(v), (i, loc))
        scores[name], where[name] = best
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    return {"best": ranked[0][0], "score": round(ranked[0][1], 4),
            "second": ranked[1][0], "margin": round(ranked[0][1] - ranked[1][1], 4),
            "gain": gain(win, icons[ranked[0][0]], where[ranked[0][0]])}


def gain(win, icon, at) -> float | None:
    """Least-squares slope of the row's pixels on the matched art's pixels.

    A dimmed portrait is the same drawing at lower contrast, so the slope falls
    while the correlation stays; a naturally dark agent keeps slope near one.
    """
    if at is None:
        return None
    i, (x, y) = at
    t, m = icon[0][i], icon[1][i][:, :, 0] > 0
    c = win[y:y + t.shape[0], x:x + t.shape[1]]
    a = t[m].astype(float).ravel()
    b = c[m].astype(float).ravel()
    return round(float(np.polyfit(a, b, 1)[0]), 3)


def main(session="a06f04a0059f", t0=232000.0, t1=351000.0):
    store = Store()
    icons = load_icons(store)
    rows = [r for r in store.read_events("scoreboard", session)
            if r.get("kind") == "row_observation" and t0 <= r["t_ms"] <= t1]
    cap = cv2.VideoCapture(store.read_manifest(session)["source"]["path"])
    out = []
    for t in sorted({r["t_ms"] for r in rows}):
        q = sorted((r for r in rows if r["t_ms"] == t), key=lambda r: r["display_row"])
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(q[0]["frame_idx"]))
        ok, frame = cap.read()
        if not ok:
            continue
        for r in q:
            got = {"t_ms": t, "display_row": r["display_row"], "team": r["team"],
                   "observation_key": r["observation_key"], **score_row(frame, r, icons)}
            out.append(got)
            print(json.dumps(got))
    cap.release()
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    main(*(a[:1] + [float(x) for x in a[1:3]])) if a else main()
