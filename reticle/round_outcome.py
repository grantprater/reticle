r"""The round-end icons on the Tab scoreboard's round-history strip, cell by cell.

    .\.venv\Scripts\python.exe -m reticle round-outcome <session> | --all   (stored crops, no decode)

Owns [owns:round-outcome-cell].

What it reads. The Tab board draws one column per round between its ally
and enemy blocks [domain:hud/scoreboard-round-history-strip]: two marker
lines, the upper the player's team, the lower the enemy. When a round ends
the game puts its outcome icon on the winner's line, tinted teal for the
player's team and red for the enemy, and a dot on the other line; an
unplayed round shows a dot on both. The icon is one of four textures
(`ICONS`, from the build's `MatchOutcomes` folder): elimination, defuse,
detonation and time. A win and a loss texture of one reason share their
alpha and differ only in tint, so the alpha is the template and the tint
is read from the pixels.

Geometry (`layout_from_game_files`, `fit_columns`). The cell sizes come
from the build's widget JSON, scaled by the capture's height over 1080 (at
1080p a widget unit is one capture pixel): each icon slot is `ICON_UNITS`
square (`ScoreboardRound`'s TopIcon and BottomIcon), centred on the
strip's marker lines (`scoreboard_strip.ROW_Y`, the dots' measured centres,
which are the same image slots), and the strip starts `HISTORY_INSET_UNITS`
inside the board (`scoreAndHistory`'s padding on `roundHistoryBase`). The
columns themselves fill the board's width and a side-switch divider sits
between halves, so their x centres are measured, not assumed: the strip
witness's own marks (`scoreboard_strip.strip_marks`, dots and icons on the
two lines) over a sample of Tab frames, pooled per column. Column k counted
from the left is round k. The fit stores where the layout puts column 1
(`table_columns` left edge plus the inset plus half a pitch) beside the
measurement, and refuses the session when they part by more than
`LAYOUT_TOL_PX`, since every round index would then be suspect.

Rule (`read_cells`). On a frame the strip witness reads `present` (the
board open: an opportunity, not an outcome), each column's two cells are
scored against the four alphas: soft colourfulness (max minus min channel
over 255, a tinted icon over a grey plate) against each alpha template
resized `INTER_AREA` to the icon slot, `TM_CCOEFF_NORMED` over a search of
`SEARCH_PX` either way. Nothing is binarised; one cut, at the decision. A
column reads `icon` when its better line's best score reaches `ICON_MIN`
and beats the other line's by `LINE_MARGIN`, and the colourfulness under
the matched alpha (its ink) reaches `INK_MIN`; it reads `empty` when
neither line reaches `EMPTY_MAX` or the ink stays under `EMPTY_INK`;
otherwise it refuses with its reason. The normalised score alone rises on
a dot's faint texture; ink separates the two (59c70f1ef720 and
4f207c0c4e39: icons in played columns p1 0.23, false icons in unplayed
columns median 0.05 to 0.09). An `icon`
cell names its reason (best template), the runner-up and the margin, the
line (`ally` upper, `enemy` lower) and the tint under the matched alpha
(`teal`, `red`, or None when the hue is unread). A reason whose margin is
under `REASON_MARGIN` stays a reading with `reason: null` and
`refusal: "reason_margin"`.

What it is not. One frame's cells, raw. Combining a round's readings
across frames, deciding its outcome and storing disagreements is
`adjudication.round_outcome`'s; which round of the capture a column is
belongs to that pooling too, against the stored rounds.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

from .scoreboard_strip import PITCH_RANGE, ROW_Y, strip_marks
from .version import ROUND_OUTCOME_VERSION

#: The game build whose widget JSON and icons the constants come from.
GAME_BUILD = "release-13.06-shipping-18-5590001"
#: Outcome reason -> the `MatchOutcomes` texture whose alpha is its template.
#: The `...loss1` twin of each has the same alpha (checked by `load_outcome_icons`).
ICONS = {"elimination": "eliminationwin1", "defuse": "diffusewin1",
         "detonation": "explosionwin1", "time": "timewin1"}
REASONS = tuple(ICONS)
ICON_DIR = "round-end/ShooterGame/Content/UI/Screens/Shared/Icons/MatchOutcomes"
LAYOUT_DIR = "hud-layout/ShooterGame/Content/UI/InGame/TacticalTabAndScoreboard"

#: From the build's widget JSON (`layout_from_game_files` reads them and a
#: test holds them equal): the icon slot's side and the strip's inset from
#: the board's edge, in widget units (one capture pixel at 1080p).
ICON_UNITS = 19.0
HISTORY_INSET_UNITS = 85.0
UNITS_REF_HEIGHT = 1080

#: The search either way around a column's fitted centre, px.
SEARCH_PX = 2
#: Decision cuts on TM_CCOEFF_NORMED of soft colourfulness against the alpha.
ICON_MIN = 0.55
EMPTY_MAX = 0.45
LINE_MARGIN = 0.15
REASON_MARGIN = 0.05
#: Alpha-weighted mean colourfulness under the matched icon: a tinted icon
#: reaches INK_MIN; under EMPTY_INK the cell holds a dot or the plate. The
#: normalised score alone rises on a dot's faint texture.
INK_MIN = 0.22
EMPTY_INK = 0.15
#: Mean G - R under the alpha, in 8-bit units, that names a tint.
TINT_MIN = 20.0
#: Column fit: frames sampled, mark support per column, and how far column 1
#: may sit from where the layout puts it.
FIT_FRAMES = 60
COLUMN_SUPPORT = 0.5
COLUMN_TOL_PX = 2.0
LAYOUT_TOL_PX = 6.0
#: The band read either side of the marker lines.
BAND_PAD = 14


def units_scale(height: int) -> float:
    """Capture pixels per widget unit."""
    return float(height) / UNITS_REF_HEIGHT


def icon_px(height: int) -> int:
    """The icon slot's side in capture pixels, odd so it has a centre."""
    n = int(round(ICON_UNITS * units_scale(height)))
    return n if n % 2 else n + 1


def _slot_size(objs: list[dict], content: str) -> tuple[float, float] | None:
    for o in objs:
        p = o.get("Properties") or {}
        if content in json.dumps(p.get("Content") or {}) and "LayoutData" in p:
            off = p["LayoutData"].get("Offsets") or {}
            return float(off.get("Right", 0.0)), float(off.get("Bottom", 0.0))
    return None


def layout_from_game_files(build_dir: Path) -> dict:
    """The strip's widget dimensions from one build's exported widget JSON:
    `icon_units` (the TopIcon and BottomIcon slots' side) and
    `history_inset_units` (the round history's padding inside the board).
    Raises when the files do not hold them."""
    d = Path(build_dir) / LAYOUT_DIR
    rnd = json.loads((d / "ScoreboardRound.json").read_text(encoding="utf-8"))
    top, bottom = _slot_size(rnd, "TopIcon"), _slot_size(rnd, "BottomIcon")
    if top is None or bottom is None or top != bottom or top[0] != top[1]:
        raise ValueError(f"ScoreboardRound icon slots unread or unequal: {top} {bottom}")
    sah = json.loads((d / "scoreAndHistory.json").read_text(encoding="utf-8"))
    pad = None
    for o in sah:
        p = o.get("Properties") or {}
        if "roundHistoryBase" in json.dumps(p.get("Content") or {}):
            pad = p.get("Padding") or {}
    if not pad or pad.get("Left") != pad.get("Right"):
        raise ValueError(f"scoreAndHistory round-history padding unread: {pad}")
    return {"icon_units": top[0], "history_inset_units": float(pad["Left"])}


def _alpha_template(alpha: np.ndarray, side: int) -> np.ndarray:
    """The whole texture's alpha, shrunk INTER_AREA to the slot's side."""
    a = alpha.astype(np.float32) / 255.0
    return cv2.resize(a, (side, side), interpolation=cv2.INTER_AREA)


def load_outcome_icons(store_root: Path, height: int, build: str = GAME_BUILD) -> dict:
    """{reason: float32 alpha template at the capture's icon size}.

    Raises if a texture is missing or its loss twin's alpha differs, which
    would make the tint, not the alpha, the reason's witness; and, where the
    build's widget JSON is exported beside it, if that JSON's slot or inset
    is not `ICON_UNITS` and `HISTORY_INSET_UNITS`."""
    build_dir = Path(store_root) / "reference" / "game-files" / build
    if (build_dir / LAYOUT_DIR / "ScoreboardRound.json").is_file():
        got = layout_from_game_files(build_dir)
        if got != {"icon_units": ICON_UNITS, "history_inset_units": HISTORY_INSET_UNITS}:
            raise ValueError(f"{build} widget layout {got} is not the module's constants")
    d = build_dir / ICON_DIR
    side = icon_px(height)
    out = {}
    for reason, name in ICONS.items():
        win = cv2.imread(str(d / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        loss = cv2.imread(str(d / f"{name.replace('win', 'loss')}.png"), cv2.IMREAD_UNCHANGED)
        if win is None or loss is None or win.ndim != 3 or win.shape[2] != 4:
            raise FileNotFoundError(f"{reason}: {d / name}.png and its loss twin with alpha")
        if not np.array_equal(win[..., 3], loss[..., 3]):
            raise ValueError(f"{reason}: win and loss alphas differ")
        out[reason] = _alpha_template(win[..., 3], side)
    return out


def colourfulness(bgr: np.ndarray) -> np.ndarray:
    """Max minus min channel over 255: soft, a tinted icon over a grey plate."""
    return (bgr.max(axis=2).astype(np.float32) - bgr.min(axis=2).astype(np.float32)) / 255.0


def history_box(table: tuple[float, float], height: int) -> tuple[float, float]:
    """The round history's frame columns: the board's `table` columns
    (`scoreboard.table_columns`) less the widget's inset on each side."""
    inset = HISTORY_INSET_UNITS * units_scale(height)
    return table[0] + inset, table[1] - inset


def fit_columns(frames, rows=ROW_Y, *, box: tuple[float, float] | None = None,
                height: int = UNITS_REF_HEIGHT) -> dict:
    """The strip's column centres from the strip witness's marks over a sample
    of board-present frames.

    `frames` are `(x0, band)` pairs: a BGR crop of frame columns `x0..`
    holding both marker lines at frame rows `rows` (`band` rows are frame
    rows from `rows[0] - BAND_PAD`). `box`, the history's frame columns
    (`history_box`), bounds the search, so the side labels and scores beside
    the strip never count. Columns are taken densest first: the marks within
    `COLUMN_TOL_PX` of a mark, at least `COLUMN_SUPPORT` per line per frame,
    and no nearer than half the least pitch to a column already taken; each
    centre is the mean of its marks. The check: column 1 against the box's
    left edge plus half the fitted pitch, refused past `LAYOUT_TOL_PX`.
    Returns `{"columns", "pitch", "frames", "support", "layout_x1",
    "layout_dx", "refusal"}`."""
    xs, n = [], 0
    pad = BAND_PAD
    for x0, band in frames:
        n += 1
        got = strip_marks(band, (pad, pad + rows[1] - rows[0]))
        xs.extend(x0 + x for _line, x, _kind in got)
    out = {"columns": [], "pitch": None, "frames": n, "support": [], "layout_x1": None,
           "layout_dx": None, "refusal": None}
    xs = np.sort(np.asarray(xs, dtype=np.float64))
    if box is not None:
        xs = xs[(xs >= box[0]) & (xs <= box[1])]
    if n == 0 or not xs.size:
        out["refusal"] = "no_marks" if n else "no_present_frames"
        return out
    tol = COLUMN_TOL_PX * units_scale(height)
    lo = np.searchsorted(xs, xs - tol, side="left")
    hi = np.searchsorted(xs, xs + tol, side="right")
    count = hi - lo
    need = COLUMN_SUPPORT * 2 * n            # a column marks both lines each frame
    taken: list[tuple[float, float]] = []
    gap = PITCH_RANGE[0] / 2 * units_scale(height)
    for i in np.argsort(-count, kind="stable"):
        if count[i] < need:
            break
        c = float(xs[lo[i]:hi[i]].mean())
        if all(abs(c - t) >= gap for t, _ in taken):
            taken.append((c, float(count[i]) / (2 * n)))
    taken.sort()
    cols = [c for c, _ in taken]
    out["columns"] = [round(c, 2) for c in cols]
    out["support"] = [round(s, 2) for _, s in taken]
    if len(cols) >= 2:
        out["pitch"] = round(float(np.median(np.diff(cols))), 2)
    if not cols:
        out["refusal"] = "no_supported_column"
        return out
    if box is not None and out["pitch"] is not None:
        x1 = box[0] + out["pitch"] / 2
        out["layout_x1"] = round(x1, 2)
        out["layout_dx"] = round(cols[0] - x1, 2)
        if abs(cols[0] - x1) > LAYOUT_TOL_PX * units_scale(height):
            out["refusal"] = "layout_disagrees"
    return out


def _line_maps(band: np.ndarray, c: np.ndarray, line_y: int, icons: dict):
    """For one marker line: per template, the TM_CCOEFF_NORMED map of soft
    colourfulness, the alpha-weighted mean colourfulness (`ink`) and the
    alpha-weighted mean G - R (`g_r`), each over the strip of rows the search
    covers; or None when the band does not hold them."""
    side = next(iter(icons.values())).shape[0]
    h, s = side // 2, SEARCH_PX
    top = line_y - h - s
    if top < 0 or line_y + h + s + 1 > c.shape[0]:
        return None
    rows = slice(top, line_y + h + s + 1)
    strip = np.ascontiguousarray(c[rows])
    g_r = band[rows, :, 1].astype(np.float32) - band[rows, :, 2].astype(np.float32)
    out = []
    for t in icons.values():
        w = (t / max(float(t.sum()), 1e-6)).astype(np.float32)
        r = cv2.matchTemplate(strip, t, cv2.TM_CCOEFF_NORMED)
        out.append((np.nan_to_num(r, nan=-1.0, posinf=-1.0, neginf=-1.0),
                    cv2.matchTemplate(strip, w, cv2.TM_CCORR),
                    cv2.matchTemplate(g_r, w, cv2.TM_CCORR)))
    return out


def _gather(maps, columns_x, x0: int, side: int):
    """Per column and template: the best score within the search window,
    and the ink and G - R at that place. Arrays of shape (columns, templates);
    NaN where a column's window leaves the band."""
    h, s = side // 2, SEARCH_PX
    cx = np.rint(np.asarray(columns_x, dtype=np.float64) - x0).astype(int)
    k = len(maps)
    score = np.full((len(cx), k), np.nan, np.float32)
    ink = np.full_like(score, np.nan)
    g_r = np.full_like(score, np.nan)
    if not len(cx):
        return score, ink, g_r
    width = maps[0][0].shape[1]
    idx = cx[:, None] - h - s + np.arange(2 * s + 1)[None, :]       # (cols, 2s+1)
    ok = (idx[:, 0] >= 0) & (idx[:, -1] < width)
    idx = np.clip(idx, 0, width - 1)
    rows = np.arange(len(cx))
    for j, (r, ink_map, gr_map) in enumerate(maps):
        win = r[:, idx]                                              # (2s+1, cols, 2s+1)
        flat = win.transpose(1, 0, 2).reshape(len(cx), -1)
        best = flat.argmax(axis=1)
        yy, xx = np.divmod(best, 2 * s + 1)
        col = idx[rows, xx]
        score[:, j] = np.where(ok, flat[rows, best], np.nan)
        ink[:, j] = np.where(ok, ink_map[yy, col], np.nan)
        g_r[:, j] = np.where(ok, gr_map[yy, col], np.nan)
    return score, ink, g_r


def read_cells(band: np.ndarray, x0: int, columns_x, icons: dict,
               rows=ROW_Y, pad: int = BAND_PAD) -> list[dict]:
    """One frame's strip cells: per column (round index from 1), what it shows.

    `band` is the BGR crop holding both marker lines, frame column `x0` at
    its column 0 and frame row `rows[0] - pad` at its row 0. Each cell is
    `{"round", "verdict", "score", "other_line", "ink", "refusal"}` and, for
    an `icon`, `"line", "reason", "best", "runner", "margin", "scores",
    "tint", "g_r"`; see the module docstring for the verdicts. The scoring
    is vectorised over columns; the loop only assembles rows."""
    names = list(icons)
    n = len(columns_x)
    if not n:
        return []
    side = next(iter(icons.values())).shape[0]
    c = colourfulness(band)
    lines = (pad, pad + rows[1] - rows[0])
    maps = [_line_maps(band, c, y, icons) for y in lines]
    if maps[0] is None or maps[1] is None:
        return [{"round": j + 1, "verdict": "unread", "refusal": "band_outside_crop"}
                for j in range(n)]
    got = [_gather(m, columns_x, x0, side) for m in maps]          # per line: score, ink, g_r
    sc = np.stack([g[0] for g in got])                              # (2, cols, k)
    unread = np.isnan(sc).any(axis=(0, 2))
    sc = np.nan_to_num(sc, nan=-1.0)
    k_best = sc.argmax(axis=2)                                      # (2, cols)
    line_best = np.take_along_axis(sc, k_best[..., None], axis=2)[..., 0]
    li = (line_best[1] > line_best[0]).astype(int)                  # 0 ally (upper), 1 enemy
    cols = np.arange(n)
    hi, lo = line_best[li, cols], line_best[1 - li, cols]
    on = sc[li, cols]                                               # (cols, k)
    order = np.argsort(-on, axis=1)
    k0, k1 = order[:, 0], order[:, 1]
    margin = on[cols, k0] - on[cols, k1]
    ink = np.nan_to_num(np.stack([g[1] for g in got])[li, cols, k0], nan=0.0)
    g_r = np.nan_to_num(np.stack([g[2] for g in got])[li, cols, k0], nan=0.0)
    cells = []
    for j in range(n):                                              # row assembly only
        cell = {"round": j + 1, "score": round(float(hi[j]), 3),
                "other_line": round(float(lo[j]), 3), "ink": round(float(ink[j]), 3)}
        if unread[j]:
            cells.append({"round": j + 1, "verdict": "unread", "refusal": "column_outside_crop"})
        elif hi[j] < EMPTY_MAX or ink[j] < EMPTY_INK:
            cells.append({**cell, "verdict": "empty", "refusal": None})
        elif hi[j] < ICON_MIN or ink[j] < INK_MIN:
            cells.append({**cell, "verdict": "unread", "refusal": "weak_icon"})
        elif hi[j] - lo[j] < LINE_MARGIN:
            cells.append({**cell, "verdict": "unread", "refusal": "both_lines"})
        else:
            gr = float(g_r[j])
            tint = "teal" if gr >= TINT_MIN else "red" if gr <= -TINT_MIN else None
            sure = margin[j] >= REASON_MARGIN
            cells.append({**cell, "verdict": "icon", "line": ("ally", "enemy")[li[j]],
                          "reason": names[k0[j]] if sure else None,
                          "best": names[k0[j]], "runner": names[k1[j]],
                          "margin": round(float(margin[j]), 3),
                          "scores": {nm: round(float(v), 3) for nm, v in zip(names, on[j])},
                          "tint": tint, "g_r": round(gr, 1),
                          "refusal": None if sure else "reason_margin"})
    return cells


def outcome_events(session_id: str, reads, geometry: dict, roi_cache_version: str,
                   strip_version: str | None, build: str = GAME_BUILD) -> list[dict]:
    """A coverage row with the column fit, then one `frame` row per read frame.

    `reads` is `(frame_idx, t_ms, cells)` per board-present frame; cells
    whose verdict is `empty` are counted, not listed."""
    common = {"session_id": session_id, "round_outcome_version": ROUND_OUTCOME_VERSION,
              "roi_cache_version": roi_cache_version, "scoreboard_strip_version": strip_version,
              "game_build": build, "source": "round_outcome"}
    rows, verdicts, refusals = [], Counter(), Counter()
    for f, t, cells in reads:
        listed = [c for c in cells if c["verdict"] != "empty"]
        for c in cells:
            verdicts[c["verdict"]] += 1
            if c.get("refusal"):
                refusals[c["refusal"]] += 1
        rows.append({**common, "kind": "frame", "frame_idx": int(f), "t_ms": float(t),
                     "empty": len(cells) - len(listed), "cells": listed})
    coverage = {**common, "kind": "coverage", "frames": len(rows), "geometry": geometry,
                "cells": dict(sorted(verdicts.items())), "refusals": dict(sorted(refusals.items())),
                "constants": {"ICON_MIN": ICON_MIN, "EMPTY_MAX": EMPTY_MAX,
                              "LINE_MARGIN": LINE_MARGIN, "REASON_MARGIN": REASON_MARGIN,
                              "SEARCH_PX": SEARCH_PX, "TINT_MIN": TINT_MIN,
                              "INK_MIN": INK_MIN, "EMPTY_INK": EMPTY_INK}}
    return [coverage] + rows
