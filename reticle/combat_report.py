"""The combat report panel: what it reads, per sampled frame, and nothing more.

A reader in the shared pass. The panel [domain:combat_report/panel-layout] is
the one surface that states, per enemy engaged, the damage each way, the
head/body/legs hit split and the KILLED / KILLED YOU / ASSIST flags. The game
shows it at each of the player's deaths [domain:combat_report/appears-on-death]
and as a round summary in the next buy phase [domain:combat_report/round-summary].
This module stores what each sampled frame shows; which panel a frame belongs
to, which round it summarises and what it says about kills and deaths is
`adjudication.combat_report`, recomputed from these rows without decoding video.

How it reads, with no labels
----------------------------
* **Locator.** The COMBAT REPORT header is fixed UI text, matched by one crop
  mined from footage (`templates/valorant-16x9-combat-report.npz`, which records
  its source frame). The panel moves with its row count and grows at the round's
  end [domain:combat_report/frozen-after-death], so every field is placed
  relative to the header, never at a fixed screen position. Measured on
  `a06f04a0059f` and `3694746e4e54`: no frame scores between 0.5 and 0.9.
* **Damage digits** use the scoreline's mined templates (`ocr.Templates`).
* **Hit counts.** The panel draws a zero count grey and any other count white,
  so a blob's peak decides zero and only white blobs are template-matched.
* **Flags** are matched against mined crops of each word; the stored value is
  every word's correlation, so the threshold stays an adjudication choice.

Offsets are measured at 1080p. Another frame size is refused per frame with a
reason rather than scaled on a guess.

Promoted on 2026-09-24 from `prototypes/combat_report.py`, which remains the
experiment record (predictions under `combat-report`).

Owns [owns:combat-report-read].
"""
from __future__ import annotations

import base64
import json
from pathlib import Path

import cv2
import numpy as np

from . import ocr
from .version import COMBAT_REPORT_VERSION

TEMPLATE_FILE = Path(__file__).resolve().parent / "templates" / "valorant-16x9-combat-report.npz"

#: The frame size the offsets below were measured at.
FRAME_WH = (1920, 1080)
#: Region searched for the header: x0, y0, x1, y1.
SEARCH = (1300, 120, 1920, 960)

#: Offsets from the header's top-left (hx, hy), measured on `a06f04a0059f` 187 s.
ROW0, PITCH, MAX_ROWS = 25, 58, 5
OUT_NUM = (-121, 6, -55, 42)             # x0, y0, x1, y1 within a row
IN_NUM = (199, 6, 262, 42)
OUT_HITS = (-53, 3, -37, 55)
IN_HITS = (180, 3, 196, 55)
OUT_FLAG = (-121, 43, -55, 56)
IN_FLAG = (195, 43, 262, 56)
FLAG_PAD = 3
#: The row portrait inside its chevron edge, and the thumbnail it is stored at.
#: Thumbnails of one player's art correlate at r >= 0.8 across panels; on the
#: player's labels of `a06f04a0059f` that groups 50 rows into 7 clusters, none
#: mixed (`prototypes/combat_report.py witnesses`).
ROW_PORTRAIT = (-6, 2, 34, 56)
THUMB_WH = (20, 27)
#: The row's name field, right of the portrait. An ALLY row is drawn on a
#: green band [domain:combat_report/ally-damage-row]; its median BGR is stored
#: and the adjudication decides. On `a06f04a0059f` 1430 s and `3694746e4e54`
#: 719 s the two ally rows read G - R of 18 and 15, the six enemy rows <= 5.
ROW_BAND = (40, 3, 175, 55)

BIG_H = (18, 40)                         # damage digit height band, px
SMALL_H = (6, 14)                        # hit-count digit height band, px
#: Zero hit counts and the flags are drawn grey (~150-200); the panel
#: background sits near 40.
DIM = 110

#: Header correlation at which rows are read. Stored scores let the
#: adjudication apply its own threshold; this one only saves reading rows of
#: frames with no panel.
READ_MIN = 0.5

FLAG_WORDS = {"KILLED": "flag_killed", "KILLED YOU": "flag_killed_you",
              "ASSIST": "flag_assist"}


def load_templates(path: Path = TEMPLATE_FILE) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    with np.load(path, allow_pickle=False) as z:
        return z["header"], {w: z[k] for w, k in FLAG_WORDS.items()}


def provenance(path: Path = TEMPLATE_FILE) -> dict:
    with np.load(path, allow_pickle=False) as z:
        return json.loads(str(z["provenance"]))


def locate(gray: np.ndarray, header: np.ndarray) -> tuple[float, int, int]:
    """Best header correlation and the header's top-left in the frame."""
    x0, y0, x1, y1 = SEARCH
    r = cv2.matchTemplate(gray[y0:y1, x0:x1], header, cv2.TM_CCOEFF_NORMED)
    _, mx, _, loc = cv2.minMaxLoc(r)
    return float(mx), x0 + loc[0], y0 + loc[1]


def field_at(gray, hx, hy, box, dy=0):
    """The pixels of `box`, an offset from the header at (hx, hy), in row `dy`."""
    x0, y0, x1, y1 = box
    return gray[max(0, hy + dy + y0): max(0, hy + dy + y1), max(0, hx + x0): max(0, hx + x1)]


def _labelled(glyphs, tpl) -> dict:
    text, score, margin = "", 1.0, 1.0
    for g in glyphs:
        lab, s, m = tpl.match(g)
        text += lab
        score, margin = min(score, s), min(margin, m)
    return {"text": text, "score": round(score, 3), "margin": round(margin, 3)}


def read_number(patch: np.ndarray, tpl: ocr.Templates) -> dict:
    """A damage number: digits left to right, or null text with a reason."""
    if patch.size == 0:
        return {"text": None, "reason": "off-frame"}
    binary, raw = ocr._raw_components(patch, ocr.THRESHOLD)
    lo, hi = BIG_H
    glyphs = [ocr.Glyph(x=x, y=y, w=w, h=h, bitmap=ocr.normalise(binary[y:y + h, x:x + w]))
              for x, y, w, h, _a in sorted(raw) if lo <= h <= hi and w <= h]
    if not glyphs:
        return {"text": None, "reason": "no-glyph"}
    return _labelled(glyphs, tpl)


def read_hits(patch: np.ndarray, tpl: ocr.Templates) -> dict:
    """Three stacked hit counts, head to legs, one blob per count."""
    if patch.size == 0:
        return {"text": None, "reason": "off-frame"}
    _binary, raw = ocr._raw_components(patch, DIM)
    lo, hi = SMALL_H
    blobs = sorted((b for b in raw if lo <= b[3] <= hi), key=lambda b: b[1])
    if len(blobs) != 3:
        return {"text": None, "reason": f"{len(blobs)}-blobs"}
    text, score, margin = "", 1.0, 1.0
    for x, y, w, h, _a in blobs:
        cell = patch[y:y + h, x:x + w]
        if cell.max() < ocr.THRESHOLD:
            text += "0"
            continue
        wb = (cell >= ocr.THRESHOLD).astype(np.uint8)
        ys, xs = np.nonzero(wb)
        wb = wb[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
        lab, s, m = tpl.match(ocr.Glyph(x=x, y=y, w=wb.shape[1], h=wb.shape[0],
                                        bitmap=ocr.normalise(wb)))
        text += lab
        score, margin = min(score, s), min(margin, m)
    return {"text": text, "score": round(score, 3), "margin": round(margin, 3)}


def read_flag(gray, hx, hy, box, dy, words: dict[str, np.ndarray]) -> dict[str, float]:
    """Each flag word's best correlation inside the padded flag field. A flat
    field (no flag drawn) scores zero for every word."""
    x0, y0, x1, y1 = box
    cell = field_at(gray, hx, hy, (x0 - FLAG_PAD, y0 - FLAG_PAD, x1 + FLAG_PAD, y1 + FLAG_PAD), dy)
    if cell.size == 0 or cell.std() < 5:
        return {w: 0.0 for w in words}
    out = {}
    for w, t in words.items():
        if t.shape[0] > cell.shape[0] or t.shape[1] > cell.shape[1]:
            out[w] = 0.0
        else:
            out[w] = round(float(cv2.matchTemplate(cell, t, cv2.TM_CCOEFF_NORMED).max()), 3)
    return out


def thumbnail(frame, hx, hy, dy) -> str | None:
    """The row portrait as a base64 BGR thumbnail, or None off-frame."""
    crop = field_at(frame, hx, hy, ROW_PORTRAIT, dy)
    if crop.shape[0] < 10 or crop.shape[1] < 10:
        return None
    small = cv2.resize(crop, THUMB_WH, interpolation=cv2.INTER_AREA)
    return base64.b64encode(np.ascontiguousarray(small).tobytes()).decode("ascii")


def band(frame, hx, hy, dy) -> list[int] | None:
    """The row band's median BGR, or None off-frame."""
    cell = field_at(frame, hx, hy, ROW_BAND, dy)
    if cell.shape[0] < 10 or cell.shape[1] < 10:
        return None
    return [int(v) for v in np.median(cell.reshape(-1, 3), axis=0)]


def thumbnail_array(encoded: str) -> np.ndarray:
    w, h = THUMB_WH
    return np.frombuffer(base64.b64decode(encoded), np.uint8).reshape(h, w, 3)


def read_rows(gray, hx, hy, tpl: ocr.Templates, words, frame=None) -> list[dict]:
    """Rows below the header until one shows neither damage number."""
    rows = []
    for k in range(MAX_ROWS):
        dy = ROW0 + k * PITCH
        out = read_number(field_at(gray, hx, hy, OUT_NUM, dy), tpl)
        inc = read_number(field_at(gray, hx, hy, IN_NUM, dy), tpl)
        if out["text"] is None and inc["text"] is None:
            break
        rows.append({
            "out": out, "in": inc,
            "out_hits": read_hits(field_at(gray, hx, hy, OUT_HITS, dy), tpl),
            "in_hits": read_hits(field_at(gray, hx, hy, IN_HITS, dy), tpl),
            "out_word": read_flag(gray, hx, hy, OUT_FLAG, dy, words),
            "in_word": read_flag(gray, hx, hy, IN_FLAG, dy, words),
            "portrait": thumbnail(frame, hx, hy, dy) if frame is not None else None,
            "band": band(frame, hx, hy, dy) if frame is not None else None,
        })
    return rows


class CombatReportReader:
    """`passes.Reader` storing the header score and, where a panel may be up,
    every row's reads. It decides nothing."""

    def __init__(self, digits: ocr.Templates, hz: float = 1.0, spans=None,
                 name: str = "combat_report"):
        self.name, self.hz, self.spans = name, hz, spans
        self.digits = digits
        self.header, self.words = load_templates()
        self.rows: list[dict] = []

    def feed(self, smp) -> None:
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms)}
        h, w = smp.frame.shape[:2]
        if (w, h) != FRAME_WH:
            self.rows.append({**row, "header": None, "reason": f"frame_size_{w}x{h}"})
            return
        gray = cv2.cvtColor(smp.frame, cv2.COLOR_BGR2GRAY)
        score, hx, hy = locate(gray, self.header)
        row.update({"header": round(score, 3), "hx": hx, "hy": hy, "reason": None})
        if score >= READ_MIN:
            row["rows"] = read_rows(gray, hx, hy, self.digits, self.words, smp.frame)
        self.rows.append(row)

    def events(self, session_id: str) -> list[dict]:
        common = {"session_id": session_id, "source": "combat_report",
                  "combat_report_version": COMBAT_REPORT_VERSION}
        read = sum("rows" in r for r in self.rows)
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": len(self.rows),
                "rows_read": read, "templates": provenance()}
        return [head] + [{**common, **r} for r in self.rows]
