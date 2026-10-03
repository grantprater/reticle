r"""The planted-spike graphic in the scoreline's clock field.

    .\.venv\Scripts\python.exe -m reticle plant-graphic <session> | --all   (stored crops, no decode)

Owns [owns:planted-spike-graphic].

What it reads. From the plant to the round's end the game draws a red spike
graphic where the round clock's digits stand
[domain:hud/planted-spike-replaces-clock]. The `hud` crop cache's `scoreline`
crop holds that field. Two soft coverages are scored on each cached frame:

* `red`: the mean over the clock field (`FIELD_X` of the crop's width, full
  height) of `clip((R - max(G, B) - RED_OFFSET) / RED_SPAN, 0, 1)`;
* `ink`: the mean over the digits' box (`INK_X`, `INK_Y`) of
  `clip((min(B, G, R) - INK_OFFSET) / INK_SPAN, 0, 1)`, the near-white ink of
  digits.

The graphic is red with no white ink; the round clock's last seconds draw
white digits on a red plate [domain:hud/low-clock-red-plate], and the
post-round flash tints the whole band red over a white countdown. So the
`score` is `red - INK_WEIGHT * ink`, and one cut, `GRAPHIC_CUT`, decides,
in `shows_graphic`. The coverages are fractions of the crop, so the reading
does not depend on the capture's resolution; no pixel is resampled or
binarised before the cut.

Measured 2026-10-02 on the 21 matches with a Riot match record (cached
scoreline crops at 2 Hz against Riot's plant times aligned to the store
clock): post-plant samples read a median `red` of 0.44; samples of no-plant
rounds whose clock went unread read under 0.04 at the median. A per-round
rule over `score >= GRAPHIC_CUT` (`rounds._plant_graphic`) finds the same
plants for any cut from 0.15 to 0.25; 0.2 sits in the middle.

What it is not. It does not decide that a round was planted: `rounds` owns
that, cross-referencing these rows with the unread clock
and requiring the graphic to persist. Nor does it read the minimap's planted
spike [domain:minimap/spike-planted-icon] or time a defuse.
"""
from __future__ import annotations

import numpy as np

from .version import PLANT_GRAPHIC_VERSION

#: The `hud` cache ROI the graphic is read from.
ROI = "scoreline"
#: The clock field, as fractions of the scoreline crop's width.
FIELD_X = (0.38, 0.62)
#: Red excess over the brighter of green and blue: zero below RED_OFFSET,
#: one at RED_OFFSET + RED_SPAN.
RED_OFFSET = 50.0
RED_SPAN = 80.0
#: The digits' box, as fractions of the crop's width and height.
INK_X = (0.42, 0.58)
INK_Y = (0.2, 0.8)
#: Near-white ink: the darkest channel, zero below INK_OFFSET, one at
#: INK_OFFSET + INK_SPAN.
INK_OFFSET = 170.0
INK_SPAN = 60.0
#: White ink counts against the graphic at this weight.
INK_WEIGHT = 2.0
#: The one cut on `score`.
GRAPHIC_CUT = 0.2


def read_field(crop: np.ndarray | None) -> dict:
    """The soft coverages of one scoreline crop (BGR), or a refusal where
    the crop is missing."""
    if crop is None or crop.size == 0:
        return {"red": None, "ink": None, "score": None, "reason": "no_crop"}
    h, w = crop.shape[:2]
    field = crop[:, int(FIELD_X[0] * w):int(FIELD_X[1] * w)].astype(np.float32)
    b, g, r = field[..., 0], field[..., 1], field[..., 2]
    red = float(np.clip((r - np.maximum(g, b) - RED_OFFSET) / RED_SPAN, 0, 1).mean())
    box = crop[int(INK_Y[0] * h):int(INK_Y[1] * h),
               int(INK_X[0] * w):int(INK_X[1] * w)].astype(np.float32)
    ink = float(np.clip((box.min(axis=2) - INK_OFFSET) / INK_SPAN, 0, 1).mean())
    return {"red": round(red, 4), "ink": round(ink, 4),
            "score": round(red - INK_WEIGHT * ink, 4), "reason": None}


def shows_graphic(row: dict | None) -> bool | None:
    """Whether one stored sample shows the planted-spike graphic; None where
    no sample or no crop was read."""
    if row is None or row.get("score") is None:
        return None
    return bool(row["score"] >= GRAPHIC_CUT)


def graphic_events(session_id: str, reads, rect, roi_cache_version: str) -> list[dict]:
    """A coverage row, then one `sample` row per cached frame.

    `reads` is `(frame_idx, t_ms, read_field(...))` per cached frame, in
    frame order; `rect` is the scoreline crop's frame rectangle."""
    common = {"session_id": session_id, "plant_graphic_version": PLANT_GRAPHIC_VERSION,
              "roi_cache_version": roi_cache_version, "source": "plant_graphic"}
    rows = [{**common, "kind": "sample", "frame_idx": int(f), "t_ms": float(t), **got}
            for f, t, got in reads]
    shown = sum(1 for r in rows if shows_graphic(r))
    coverage = {**common, "kind": "coverage", "roi": ROI, "rect": [int(v) for v in rect],
                "frames": len(rows), "graphic": shown,
                "no_crop": sum(1 for r in rows if r["reason"] == "no_crop"),
                "cut": GRAPHIC_CUT}
    return [coverage] + rows


def stored_reads(store, session_id: str) -> dict[float, dict] | None:
    """The stored samples keyed by `t_ms`, or None where the stream is absent
    or not at the current stamp (a stale reading is not evidence).

    `read_events_kind` also returns the stream's first row, the coverage row,
    for its stamp; only `sample` rows carry a `t_ms`."""
    if store.events_version("plant_graphic", session_id) != PLANT_GRAPHIC_VERSION:
        return None
    return {float(r["t_ms"]): r
            for r in store.read_events_kind("plant_graphic", session_id, "sample")
            if r.get("kind") == "sample"}

