"""Montage the roster panel's own NAME TEXT per row, across every session.

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

CORRECTED 2026-09-03: the agent name is NOT on the Tab scoreboard
------------------------------------------------------------------
NOTES.md said the Tab scoreboard prints the agent name as a grey second line.
Rendered, it does not. The two-line rows are on the **Esc / social panel** --
the one carrying "ADD FRIEND", "MUTE ALL ENEMY TEXT CHAT" and "SURRENDER".
`read_scoreboard` detects it because both screens draw the two teams as the
same five-row coloured slab, which is why an earlier session found the names
and attributed them to Tab. Frame 111702 of `a06f04a0059f`, the frame NOTES
cites, is this panel; frame 5033 is a real Tab opening and carries no agent
name at all.

Two consequences, and the second is the expensive one:

* an open board is NOT enough -- `is_roster_panel()` gates on the ally rows actually
  carrying a second text line, or the sheet fills with Tab openings
  that cannot answer the question;
* **the player opens Esc far less often than Tab.** He is asked to open Tab once a
  round; nothing has ever asked for the social panel. So this read may simply
  be unavailable on a given match. That is a capture-side fact to add to the
  checklist, not a detector to improve.

Observed while rendering, NOT fixed here and NOT this tool's job: on the
**Tab** view the five ENEMY row bands sit about half a row high, because the
enemy slab `read_scoreboard` divides into five also contains the DEF/ATK
scoreline header. Ally bands, and both teams' bands on the Esc panel, are
correct. Anything reading ENEMY K/D off Tab should check this first; the local
player is on the ally side, so `reticle board` is unaffected.
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
        crop = frame[r.y0:r.y1, tx0:min(frame.shape[1], tx0 + NAME_W)]
        if crop.shape[0] > 4 and crop.shape[1] > 4:
            out.append((r.team, crop.copy()))
    return out


TEXT_FRAC = 0.15      # of the row's own peak edge energy
TEXT_MIN_RUN = 3      # pixel rows, so a single noisy row is not a "line"


def text_line_count(crop) -> int:
    """How many TEXT LINES this row band carries.

    Text has strong VERTICAL edges; the slab it sits on is a smooth horizontal
    gradient and has almost none. So the mean |Sobel_x| per pixel row peaks on
    a line of text and collapses between lines. Measured on the two frames
    whose answer is known by eye (`a06f04a0059f` 111702 Esc panel, 5033 Tab):

        between lines      2-7%  of the row's own peak
        a second text line 25-73% of it

    `TEXT_FRAC` sits in that gap. It is normalised by the row's OWN peak, so it
    is relative rather than an absolute level tested against a HUD composited
    over live scenery -- CLAUDE.md's one never-wrong rule. Honest limit: the
    gap is wide but it was read off two frames, so treat the constant as
    provisional and re-check it if a capture's HUD scale ever changes.
    """
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    if g.shape[0] < 10:
        return 0
    prof = np.abs(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)).mean(1)
    mx = float(prof.max())
    if mx <= 0:
        return 0
    lines, run = 0, 0
    for v in prof > TEXT_FRAC * mx:
        if v:
            run += 1
            if run == TEXT_MIN_RUN:
                lines += 1
        else:
            run = 0
    return lines


def is_roster_panel(crops) -> bool:
    """True for the Esc roster panel, False for a Tab opening.

    Decided on the ALLY rows only, and that is not a convenience. On the Tab
    view `read_scoreboard`'s five ENEMY bands sit about half a row high (the
    enemy slab it divides also contains the DEF/ATK scoreline header), so an
    enemy band straddles the bottom of one player's name and the top of the
    next and shows TWO text lines for a screen that has one per row. The ally
    bands are correct on both screens, so they are the ones that can answer.
    The panel this selects has all ten bands aligned anyway.
    """
    ally = [c for t, c in crops if t == "ally"]
    if len(ally) < 5:
        return False
    return sum(text_line_count(c) >= 2 for c in ally) >= 4


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--n-probe", type=int, default=250)
    ap.add_argument("--sessions", nargs="*", default=None,
                    help="session ids to scan; default every manifest")
    a = ap.parse_args()

    sessions = a.sessions or sorted(p.stem for p in (STORE / "manifests").glob("*.json"))
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
            if len(crops) == 10 and is_roster_panel(crops):
                found = crops
                print(f"{sid}: scoreboard open at frame {i}")
                break
        cap.release()
        if found is None:
            print(f"{sid}: no Esc roster panel in {a.n_probe} probes "
                  f"(Tab openings carry no agent line)")
            continue
        blocks.append((sid, found))

    if not blocks:
        raise SystemExit("nothing decoded")

    cw = max(c.shape[1] for _s, crops in blocks for _t, c in crops) * ZOOM
    ch = max(c.shape[0] for _s, crops in blocks for _t, c in crops) * ZOOM
    pad, label_h, side_w = 4, 16, 52
    row_h = ch + pad
    n_rows = max(len(crops) for _s, crops in blocks)
    sheet = np.full((len(blocks) * (n_rows * row_h + label_h + pad) + pad,
                     cw + side_w + 2 * pad, 3), 255, dtype=np.uint8)
    y = pad
    for sid, crops in blocks:
        cv2.putText(sheet, sid, (pad, y + 12), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 0), 1,
                    cv2.LINE_AA)
        y += label_h
        for team, crop in crops:
            big = cv2.resize(crop, (cw, ch), interpolation=cv2.INTER_CUBIC)
            sheet[y:y + ch, pad + side_w:pad + side_w + cw] = big
            cv2.putText(sheet, team, (pad, y + ch // 2 + 4), cv2.FONT_HERSHEY_SIMPLEX,
                        0.38, (0, 128, 0) if team == "ally" else (0, 0, 200), 1, cv2.LINE_AA)
            y += row_h

    out = Path(a.out) if a.out else Path.cwd() / "roster_names.png"
    cv2.imwrite(str(out), sheet)
    print(f"\nwrote {out}  ({len(blocks)} sessions x 10 rows, {ZOOM}x)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
