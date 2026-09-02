"""Montage the scoreboard's own NAME TEXT per row, across every session.

    .\\.venv\\Scripts\\python.exe prototypes\\roster_names_scan.py [--out sheet.png]

the player, 2026-09-02, correctly pushed back on eyeballing minimap-style portraits
to find a session with an ally Cypher: this repo's own history says **read the
names, never the portraits** (NOTES.md, 2026-08-27) -- the Tab scoreboard
prints the agent name as literal text on a second grey line, a closed
25-string vocabulary, which settled the Ascent lineup in one look where two
rounds of portrait-reading could not. `minimap_portrait.mine_scoreboard()` +
`scoreboard_portraits()` already locate the portrait precisely (via the
GAP between portrait and text, not a fixed offset -- see that module); this
just crops the region one portrait-width further right, which is the name +
agent text, instead of the portrait itself.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from reticle.ocr import Templates                                  # noqa: E402
from reticle.scoreboard import read_scoreboard                     # noqa: E402
import minimap_portrait as mp                                      # noqa: E402

STORE = Path.home() / "reticle-store"
ZOOM = 3
NAME_W = 230  # generous: player name + agent name, short of the K/D/A columns


def name_text_crops(frame, sb):
    """Same GAP-finding as `scoreboard_portraits`, one portrait-width further right."""
    if not sb.open_ or not sb.rows:
        return []
    h = sb.rows[0].y1 - sb.rows[0].y0
    w = max(4, int(round(h * mp.SB_PORTRAIT_ASPECT)))
    lo = max(0, sb.x0 - 2 * h)
    hi = min(frame.shape[1], sb.x0 + 3 * h)
    if hi - lo < w + 4:
        return []
    prof = np.zeros(hi - lo, np.float32)
    for r in sb.rows:
        band = cv2.cvtColor(frame[r.y0 + 1:r.y1 - 1, lo:hi], cv2.COLOR_BGR2GRAY)
        prof += np.abs(cv2.Sobel(band.astype(np.float32), cv2.CV_32F, 0, 1, ksize=3)).mean(0)
    prof /= max(1, len(sb.rows))
    prof = np.convolve(prof, np.ones(3) / 3, "same")
    a = max(0, sb.x0 - lo + int(0.6 * w))
    b = min(len(prof), sb.x0 + 2 * h - lo)
    if b - a < 6:
        return []
    gap = a + int(np.argmin(prof[a:b]))
    x0 = max(lo, lo + gap - w)
    tx0 = x0 + w
    out = []
    for r in sb.rows:
        if not r.team == "ally":
            continue
        crop = frame[r.y0:r.y1, tx0:min(frame.shape[1], tx0 + NAME_W)]
        if crop.shape[0] > 4 and crop.shape[1] > 4:
            out.append(crop.copy())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--n-probe", type=int, default=250)
    a = ap.parse_args()

    sessions = sorted(p.stem for p in (STORE / "manifests").glob("*.json"))
    blocks = []
    for sid in sessions:
        man = json.loads((STORE / "manifests" / f"{sid}.json").read_text())
        src = man["source"]
        media = Path(src["path"])
        if not media.is_file():
            print(f"{sid}: source missing")
            continue
        try:
            templates = Templates.load(man["source_profile"])
        except SystemExit as ex:
            print(f"{sid}: {ex}")
            continue
        cap = cv2.VideoCapture(str(media))
        found = None
        tot = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        for i in np.linspace(tot * 0.02, tot * 0.98, a.n_probe).astype(int):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(i))
            ok, fr = cap.read()
            if not ok:
                continue
            sb = read_scoreboard(fr, templates)
            if not sb.open_ or len(sb.rows) < 10:
                continue
            crops = name_text_crops(fr, sb)
            if len(crops) == 5:
                found = crops
                print(f"{sid}: scoreboard open at frame {i}")
                break
        cap.release()
        if found is None:
            print(f"{sid}: no full scoreboard opening found in {a.n_probe} probes")
            continue
        blocks.append((sid, found))

    if not blocks:
        raise SystemExit("nothing decoded")

    cw = max(c.shape[1] for _s, crops in blocks for c in crops) * ZOOM
    ch = max(c.shape[0] for _s, crops in blocks for c in crops) * ZOOM
    pad, label_h = 4, 16
    row_h = ch + pad
    sheet = np.full((len(blocks) * (5 * row_h + label_h + pad) + pad, cw + 2 * pad, 3),
                    255, dtype=np.uint8)
    y = pad
    for sid, crops in blocks:
        cv2.putText(sheet, sid, (pad, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1,
                    cv2.LINE_AA)
        y += label_h
        for crop in crops:
            big = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_CUBIC)
            sheet[y:y + ch, pad:pad + cw] = big
            y += row_h

    out = Path(a.out) if a.out else Path.cwd() / "roster_names.png"
    cv2.imwrite(str(out), sheet)
    print(f"\nwrote {out}  ({len(blocks)} sessions x 5 ally rows, {ZOOM}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
