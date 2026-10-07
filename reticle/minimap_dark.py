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


def occluded(crop: np.ndarray, floor: np.ndarray, static: np.ndarray,
             scale: float | None = None) -> np.ndarray:
    """Pixels the player's and teammates' icons cover this frame. The ring
    fits read at `scale`, the map's (`geometry.drawn_scale`; None, the
    widget's)."""
    occ = np.zeros(crop.shape[:2], np.uint8)
    for s in self_icons(crop, floor, require_facing=False, scale=scale):
        cv2.circle(occ, (int(s["cx"]), int(s["cy"])), int(s["r"]) + SELF_MARGIN_PX, 1, -1)
    for a in ally_icons(crop, floor, static=static, require_facing=False, scale=scale):
        cv2.circle(occ, (int(a["cx"]), int(a["cy"])), int(a["r"]) + ALLY_MARGIN_PX, 1, -1)
    return occ.astype(bool)


def dark_reader(ctx, spans, hz: float = 4.0, floor=None, sgray=None):
    """The `DarkRegionReader` `scan` builds for a session
    (`passes.SessionContext`), or None where the baked geometry has no
    lighting reference. A pass that already holds the floor and base-map
    grey (`scan`'s minimap reader) passes them."""
    from . import geometry
    from .minimap import minimap_roi_px
    with np.load(geometry.path_of(ctx.session_id, ctx.store.root)) as z:
        ref = lighting.reference(z)
    if ref is None:
        return None
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    return DarkRegionReader(scale=geometry.drawn_scale(ctx.session_id, ctx.store.root,
                                                       box[2] - box[0])[0],floor=ctx.floor() if floor is None else floor,
                            sgray=ctx.sgray() if sgray is None else sgray,
                            static=ctx.map_reference(), ref=ref,
                            box=minimap_roi_px(ctx.profile, *ctx.wh), hz=hz, spans=spans)


class DarkRegionReader:
    """`passes.Reader` storing grey-dark and occluded masks per sampled frame.

    A frame whose widget is not drawn is stored as such, with no masks: it is
    unobserved, which `adjudication.smokes` keeps apart from an empty floor.

    Fed from the 15 Hz minimap crop cache, it reads the cached frames on its
    own 4 Hz grid (`cache_resample`, `roi_cache.grid_times`): the same pixels and the
    same rows at every instant both sources hold, but other instants than a
    decode's stride, which takes every 15th frame of a 60 fps capture where
    the cache holds every 4th or 5th. The coverage row then names the cache in
    `frames_from`; a decode's coverage row carries no such key. A pass
    clipped to a round cache's rounds adds `spans_clip`, the spans it read
    and the spans it left unread (`roi_cache.clip_record`).
    """

    #: A slower rate than the cache's reads the cache on this reader's own grid.
    cache_resample = True
    #: Its coverage row records a clip to a round cache (`spans_clip`).
    records_clip = True

    def __init__(self, floor, sgray, static, ref, box, hz=4.0, spans=None,
                 name="minimap_dark", scale: float | None = None):
        self.name, self.hz, self.spans = name, hz, spans
        #: The map's scale the icon occluders' ring fits read at.
        self.scale = scale
        self.frames_from = "video"
        self.cv_threads = 1        # small crops: see `passes._feed`
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
                          "occluded": lighting.pack_mask(occluded(crop, self.floor, self.static,
                                                                   self.scale))})

    def events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = {"session_id": session_id, "source": "minimap",
                  "minimap_dark_version": MINIMAP_DARK_VERSION,
                  "lighting_version": lighting.LIGHTING_VERSION,
                  "geometry_key": geometry_key}
        drawn = sum(r["widget_drawn"] is True for r in self.rows)
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": len(self.rows),
                "widget_drawn": drawn, "unobserved": len(self.rows) - drawn,
                "scale": None if self.scale is None else round(float(self.scale), 5)}
        if self.frames_from != "video":
            # Only a cache-fed pass adds the key, so a decode's rows keep their bytes.
            head["frames_from"] = self.frames_from
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            # A pass clipped to a round cache's rounds names the spans it left
            # unread (`roi_cache.clip_record`): no row there is not an empty floor.
            head["spans_clip"] = clip
        return [head] + [{**common, **r} for r in self.rows]
