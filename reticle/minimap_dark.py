"""Grey dark regions on the minimap: floor something opaque and uncoloured covers.

A reader in the shared minimap pass. It stores, per sampled frame, which floor
pixels are darker than their unlit level AND achromatic, and which pixels an
icon covers so that nothing can be read beneath it. It decides nothing: births,
tracks and lifetimes are `adjudication.smokes`, recomputed from these rows
without decoding video.

Why these two tests, each measured on `a06f04a0059f` on 2026-09-24
--------------------------------------------------------------------
* **Below the unlit level, not below the previous frame.** Lit floor turning
  unlit is a vision change, not an object; `lighting.raw_dark` compares
  against the unlit baseline and so never fires on a viewcone.
* **Grey.** A smoke's dark pixels measured saturation median 0 on two clean
  discs; merged blue death marks measured 162, and enemy icons are ringed in
  red. The gate removed every non-smoke track in four match rounds without an
  icon or death-mark rule, which a reader in this layer could not call.

Self and ally icons draw over the floor, so their discs are stored as
occluded: a smoke under a teammate is unobserved there, not gone. Enemy smokes
are not drawn at all [domain:abilities/enemy-smokes-not-on-minimap]; they show
only as missing cone light [domain:minimap/enemy-smokes-block-cones], which
this does not read.

Promoted on 2026-09-24 from `prototypes/entity_mining_rounds.py`, which grew out
of `prototypes/entity_mining_residual.py`; both remain the experiment record.

Owns [owns:minimap-dark].
"""
from __future__ import annotations

import cv2
import numpy as np

from . import lighting
from .minimap import ally_icons, self_icons, widget_drawn
from .version import MINIMAP_DARK_VERSION

#: Saturation below which a dark pixel is grey. Smoke dark pixels measured
#: median 0 and p90 <= 12; blue death marks 162, so 60 sits well between.
SMOKE_SAT_MAX = 60
#: Margins added to a fitted icon radius when marking what it covers.
SELF_MARGIN_PX = 6
ALLY_MARGIN_PX = 4


def grey_dark(crop: np.ndarray, ref: lighting.Lighting) -> np.ndarray:
    """Floor below its unlit level and achromatic: the smoke evidence."""
    sat = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)[..., 1]
    return lighting.raw_dark(crop, ref) & (sat < SMOKE_SAT_MAX)


def occluded(crop: np.ndarray, floor: np.ndarray, static: np.ndarray) -> np.ndarray:
    """Pixels the player's and teammates' icons cover this frame."""
    occ = np.zeros(crop.shape[:2], np.uint8)
    for s in self_icons(crop, floor, require_facing=False):
        cv2.circle(occ, (int(s["cx"]), int(s["cy"])), int(s["r"]) + SELF_MARGIN_PX, 1, -1)
    for a in ally_icons(crop, floor, static=static, require_facing=False):
        cv2.circle(occ, (int(a["cx"]), int(a["cy"])), int(a["r"]) + ALLY_MARGIN_PX, 1, -1)
    return occ.astype(bool)


class DarkRegionReader:
    """`passes.Reader` storing grey-dark and occluded masks per sampled frame.

    A frame whose widget is not drawn is stored as such, with no masks: it is
    unobserved, which `adjudication.smokes` keeps apart from an empty floor.
    """

    def __init__(self, floor, sgray, static, ref, box, hz=4.0, spans=None,
                 name="minimap_dark"):
        self.name, self.hz, self.spans = name, hz, spans
        self.floor, self.sgray, self.static, self.ref, self.box = floor, sgray, static, ref, box
        self.rows: list[dict] = []

    def feed(self, smp) -> None:
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms)}
        if crop.shape[:2] != self.ref.known.shape:
            self.rows.append({**row, "widget_drawn": None, "reason": "geometry_size_mismatch"})
            return
        if not widget_drawn(crop, self.sgray, self.floor):
            self.rows.append({**row, "widget_drawn": False, "reason": "widget_not_drawn"})
            return
        self.rows.append({**row, "widget_drawn": True, "reason": None,
                          "grey_dark": lighting.pack_mask(grey_dark(crop, self.ref)),
                          "occluded": lighting.pack_mask(occluded(crop, self.floor, self.static))})

    def events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = {"session_id": session_id, "source": "minimap",
                  "minimap_dark_version": MINIMAP_DARK_VERSION,
                  "lighting_version": lighting.LIGHTING_VERSION,
                  "geometry_key": geometry_key}
        drawn = sum(r["widget_drawn"] is True for r in self.rows)
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": len(self.rows),
                "widget_drawn": drawn, "unobserved": len(self.rows) - drawn}
        return [head] + [{**common, **r} for r in self.rows]
