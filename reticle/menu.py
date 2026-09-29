r"""Is the game's menu open over the HUD? One stored witness, read from the crop caches.

    .\.venv\Scripts\python.exe -m reticle menu <session> | --all   (stored crops, no decode)

Owns [owns:menu-open]. The structures are [domain:hud/menu-structure].

Opening the menu dims the whole screen [domain:hud/menu-dims-tray], and the
dim fools every reader that tests a level: the tray reads a fall on every slot
at one instant, `minimap.widget_drawn` still passes the dimmed widget, and the
roster counted the menu's tab strip as three allies (`4f207c0c4e39` at
201.0 s). So the question is asked once, here, of the menu's own opaque
structure, and the readers consult the stored answer instead of each testing
a hue or a level.

Two structures, one per crop cache, because no cache holds both. Each is
SEARCHED for, not read at fixed rows: the corpus shows two layouts, the
`4f207c0c4e39` capture drawing the whole menu smaller and lower than the rest.

* **The tab strip** (`tab_strip`). In a match the menu draws its tabs (MATCH,
  GENERAL, CONTROLS, CROSSHAIR, VIDEO, AUDIO, VIEWING) as one white text line
  across the top of the screen over a dark panel, where the roster bars and
  the scoreline sit in play. The `hud` cache holds the three crops it crosses
  (`hud_roster`, `scoreline`, `hud_roster_enemy`) at 2 Hz. In each crop
  `tab_lines` finds the runs of rows lit at their 90th percentile, TAB_RUN
  rows tall, with dark panel rows just above and below; the strip is open
  when all three crops hold a run at the same rows, since one line crosses
  them. The text sits on y 26-36 in most captures and on y 53-63 in
  `4f207c0c4e39`.
* **The CLOSE SETTINGS button** (`close_button`). The menu draws an opaque
  grey button, centred on the screen, over the ability tray: its fill is
  176 grey, or 232 while the pointer rests on it. The `minimap` cache holds
  the tray crop (`hud_abilities`), and the demo sessions have no `hud` cache,
  so this is their only witness. The fit takes the rows whose central columns
  are one uniform grey, follows each row out to its edges, and asks the edges
  to agree from row to row, the width to be a button's and the columns just
  outside to be dark: a filled rectangle with edges, not a bright scene. A
  flash lights the whole tray and has no edge inside it.

Both are measured at 1920x1080; another size is refused, not scaled.

A reading per sample. `menu_rows` stores, per source, the instants it sampled
(`coverage`) and one `open` row per instant the menu covers, with the fit's
evidence. `MenuWitness.at` answers True, False, or None where no source
sampled near the instant, so "not looked at" stays apart from "no menu".
"""
from __future__ import annotations

from bisect import bisect_left

import numpy as np

#: Screen size the fits are measured at.
WH = (1920, 1080)
#: A tab label's run of lit rows, and the dark panel rows looked at above
#: (EDGE, skipping the one transition row) and below (PANEL) it.
TAB_RUN = (8, 16)
EDGE, PANEL = 2, 4
#: A text row's 90th percentile reaches TEXT_P90 and TEXT_OVER_PANEL times the
#: panel's brightest row, which stays at or below DARK_P90. An unselected
#: tab's label is dimmer than the selected one's: on the menu samples of
#: `4f207c0c4e39` the text rows' least 90th percentile ran 111-214.
TEXT_P90 = 90
TEXT_OVER_PANEL = 2.0
DARK_P90 = 70
#: The runs in the three crops are one line when their rows agree this closely.
SAME_ROWS = 2
#: The button: centred on CENTRE_X, and wider than 2 * CORE_HALF in both
#: layouts (x 810-1109 on y 983-1033; x 850-1069 on y 993-1034 in
#: `4f207c0c4e39`), searched on SEARCH_Y.
CENTRE_X, CORE_HALF = 960, 100
SEARCH_Y = (970, 1046)
#: A fill row: its central columns vary by at most CORE_STD, sit at FILL_MIN
#: grey or more and carry at most FILL_S saturation; a pixel belongs to the
#: fill within FILL_TOL of the row's level.
CORE_STD, FILL_MIN, FILL_S, FILL_TOL = 6.0, 120, 40, 12
#: The text rows are not fill rows, so a button shows 32 of its 50 rows, and
#: 20 or more in the smaller layout.
MIN_FILL_ROWS = 14
#: The button's width, and how many of its fill rows must put both edges
#: within EDGE_PX of their median.
WIDTH = (180, 340)
EDGE_PX, EDGE_AGREE = 2, 0.9
#: The strip beside each edge, and the most of the fill's level its median
#: may reach.
SIDE = (3, 12)
SIDE_FRAC = 0.5
#: The tab-strip crops, in screen order.
TAB_ROIS = ("hud_roster", "scoreline", "hud_roster_enemy")
TRAY_ROI = "hud_abilities"
#: How far a consumer's instant may sit from a sampled one and still take its
#: answer: under half the slowest source's period (the 2 Hz `hud` cache).
MATCH_MS = 260.0


def tab_lines(crop: np.ndarray, y0: int) -> list[tuple[int, int]]:
    """Screen rows (first, past-last) of each tab-label line in one top-band
    crop whose first row is screen row `y0`."""
    import cv2
    p = np.percentile(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), 90, axis=1)
    lit, n, out, i = p >= TEXT_P90, len(p), [], 0
    while i < n:
        if not lit[i]:
            i += 1
            continue
        j = i
        while j < n and lit[j]:
            j += 1
        above, below = p[max(0, i - 1 - EDGE):max(0, i - 1)], p[j + 1:j + 1 + PANEL]
        if TAB_RUN[0] <= j - i <= TAB_RUN[1] and len(above) and len(below) == PANEL:
            panel = max(above.max(), below.max())
            if panel <= DARK_P90 and p[i:j].min() >= TEXT_OVER_PANEL * panel:
                out.append((i + y0, j + y0))
        i = j
    return out


def tab_strip(crops: dict) -> dict:
    """The fit over the three top crops, `{roi: (crop, rect)}`: open when all
    three hold a label line at the same rows."""
    lines = {roi: tab_lines(c, int(r[1])) for roi, (c, r) in crops.items()}
    first, *rest = (lines[roi] for roi in TAB_ROIS)
    for a, b in first:
        if all(any(abs(a2 - a) <= SAME_ROWS and abs(b2 - b) <= SAME_ROWS for a2, b2 in ls)
               for ls in rest):
            return {"open": True, "feature": "tab_strip", "rows": [a, b],
                    "crops_lit": len(TAB_ROIS)}
    return {"open": False, "feature": "tab_strip", "rows": None,
            "crops_lit": sum(bool(ls) for ls in lines.values())}


def close_button(crop: np.ndarray, rect) -> dict:
    """The fit of the CLOSE SETTINGS button in a crop holding the tray."""
    import cv2
    x0, y0, x1, y1 = (int(v) for v in rect)
    if x0 > CENTRE_X - WIDTH[1] // 2 or x1 < CENTRE_X + WIDTH[1] // 2             or y0 > SEARCH_Y[0] or y1 < SEARCH_Y[1]:
        raise ValueError(f"rect {rect} does not hold the button's search box")
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.int16)
    sat = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1]
    c0, c1 = CENTRE_X - CORE_HALF - x0, CENTRE_X + CORE_HALF - x0
    rows, left, right, levels = [], [], [], []
    for y in range(SEARCH_Y[0] - y0, SEARCH_Y[1] - y0):
        core = g[y, c0:c1]
        level = float(np.median(core))
        if core.std() > CORE_STD or level < FILL_MIN or np.median(sat[y, c0:c1]) > FILL_S:
            continue
        fill = np.abs(g[y] - level) <= FILL_TOL
        a = c0
        while a > 0 and fill[a - 1]:
            a -= 1
        b = c1
        while b < len(fill) and fill[b]:
            b += 1
        rows.append(y)
        left.append(a)
        right.append(b)
        levels.append(level)
    fit = {"open": False, "feature": "close_button", "fill_rows": len(rows)}
    if len(rows) < MIN_FILL_ROWS:
        return fit
    a, b, level = int(np.median(left)), int(np.median(right)), float(np.median(levels))
    agree = float(np.mean((np.abs(np.array(left) - a) <= EDGE_PX)
                          & (np.abs(np.array(right) - b) <= EDGE_PX)))
    fit.update(x=[a + x0, b + x0], level=round(level, 1), edges_agree=round(agree, 2))
    if a - SIDE[1] < 0 or b + SIDE[1] > g.shape[1]:
        return fit                                   # no edge inside the crop
    side = float(np.median(np.concatenate([g[rows, a - SIDE[1]:a - SIDE[0]].ravel(),
                                           g[rows, b + SIDE[0]:b + SIDE[1]].ravel()])))
    fit["side"] = round(side, 1)
    fit["open"] = bool(WIDTH[0] <= b - a <= WIDTH[1] and agree >= EDGE_AGREE
                       and side <= SIDE_FRAC * level)
    return fit


def menu_rows(session_id: str, source: str, samples, version: str, cache_version: str) -> list[dict]:
    """Stored rows for one source: a `coverage` row naming every sampled
    instant, and an `open` row per instant a fit found the menu. `samples`
    are `(t_ms, fit)` pairs, the fit None where the sample could not be read."""
    common = {"session_id": session_id, "menu_version": version, "source": source,
              "roi_cache_version": cache_version}
    read = [(float(t), f) for t, f in samples if f is not None]
    rows = [{**common, "kind": "coverage", "samples": len(read),
             "unread": sum(f is None for _t, f in samples),
             "open": sum(bool(f["open"]) for _t, f in read),
             "t_ms": [t for t, _f in read]}]
    rows += [{**common, "kind": "open", "t_ms": t, **f} for t, f in read if f["open"]]
    return rows


class MenuWitness:
    """The stored readings, asked per instant."""

    def __init__(self, rows: list[dict]):
        self.version = next((r.get("menu_version") for r in rows), None)
        self.sources: dict[str, tuple[list[float], set[float]]] = {}
        for r in rows:
            if r.get("kind") == "coverage":
                self.sources[r["source"]] = (sorted(r["t_ms"]), set())
        for r in rows:
            if r.get("kind") == "open" and r["source"] in self.sources:
                self.sources[r["source"]][1].add(float(r["t_ms"]))

    def at(self, t_ms: float, tol_ms: float = MATCH_MS) -> bool | None:
        """Whether the menu covers the screen at `t_ms`: True if any source's
        nearest sample within `tol_ms` found it, False if a source sampled
        there and none found it, None if no source sampled there."""
        seen = False
        for ts, opened in self.sources.values():
            i = bisect_left(ts, t_ms)
            near = [ts[j] for j in (i - 1, i) if 0 <= j < len(ts)]
            if not near:
                continue
            t = min(near, key=lambda x: abs(x - t_ms))
            if abs(t - t_ms) > tol_ms:
                continue
            if t in opened:
                return True
            seen = True
        return False if seen else None

    def open_ms(self) -> list[float]:
        """Every sampled instant the menu covers, over all sources."""
        return sorted({t for _ts, opened in self.sources.values() for t in opened})


def stored_menu(store, session_id: str) -> tuple[MenuWitness | None, str]:
    """The session's current witness, or None and the reason (its stamp when
    current)."""
    from .version import MENU_VERSION
    rows = store.read_events("menu_open", session_id)
    if not rows:
        return None, "no_menu_rows"
    w = MenuWitness(rows)
    if w.version != MENU_VERSION:
        return None, f"stale:{w.version}"
    return w, MENU_VERSION
