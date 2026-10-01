r"""One crop-cache pass for every caster's minimap abilities.

    .\.venv\Scripts\python.exe -m reticle scan <session> --only ability

Owns [owns:ability-gate].

Why. `ability_shapes` fits a shape on one crop after each of the player's
tray casts. Every caster's drawings, the teammates' and the enemies', need
every sampled crop of a match read
[domain:minimap/ability-drawings-both-sides]. This module holds the readers
that ride one pass over the minimap crop cache (`docs/ABILITY_DETECTION.md`,
section 4). A shared pass is an execution optimisation, not a shared
definition: each reader writes its own stream under its own stamp, and
`minimap_dark` rides the same pass with its code and stamp unchanged.

| Stream | Grid | Work | Stamp |
|---|---|---|---|
| `ability_gate` | 2 Hz, live samples | teal components | `ability_gate_version` |
| `ability_shape_scan` | gated samples | `ability_shapes.ring_candidates`, `widened_beam` | `ability_shape_scan_version`, the `ability_shape_version`, over the gate's |

The grid. Each reader reads the cache on its own grid over the same spans
as `minimap_dark` (`cache_resample`, `roi_cache.grid_times`), so the 2 Hz
times are every other 4 Hz time and the shared read costs nothing extra. A
sample outside the round's live phases (`round_live`, `post_plant`, from
`gametime`, which the command passes as `phase_at`) is stored with reason
`not_live`, and a crop whose widget is not drawn with `widget_not_drawn`, so
unread, unobserved and empty stay apart.

The gate (an opportunity gate, not an outcome). The fits run only where
teal (`ability_shapes.teal` at least GATE_TEAL) forms a connected component
at least GATE_EXTENT_BASE across (a base value, `ability_shapes`' scale
section). It needs no other stream,
so it cannot go stale. Measured in `prototypes/ability_shape_fast.py`: it
passed [metric:ability_shape_fast/marks@tray-object-marks#gate_post=45] of
[metric:ability_shape_fast/marks@tray-object-marks#gate_post_n=45] post-cast
panels and [metric:ability_shape_fast/marks@tray-object-marks#gate_pre=0]
pre-cast panels.

The shapes. A gated sample stores every ring the whole-widget search
proposes (`ring_candidates`, centres on the map's footprint) and the beam
along the longest teal segment on the map (`widened_beam`), each with the
owner's acceptance verdict. The reader names no ability, no caster and no
side: a teal ring may be Regrowth or Recon Bolt, and colour follows the
side [domain:minimap/ability-drawing-colour-by-side]. Those are the
adjudicators' questions, asked from storage.

Not for. Smokes (`minimap_dark`, `adjudication.smokes`); tracks, lifecycles
and names (`adjudication.ability`, `adjudication.phases`, the arbiter).
"""
from __future__ import annotations

import cv2
import numpy as np

from . import ability_shapes as shapes
from .geometry import MapScale
from .minimap import widget_drawn
from .version import ABILITY_GATE_VERSION, ABILITY_SHAPE_VERSION

#: Teal weight a gate pixel needs, and the component extent that opens the
#: fits, a base value set at 0.2 of the 331 px widget radius
#: (`prototypes/ability_shape_fast.py`).
GATE_TEAL, GATE_EXTENT_BASE = 0.25, shapes._b(0.2 * shapes.SET_AT_R)
#: The live phases a sample is read in (`gametime`).
LIVE_PHASES = ("round_live", "post_plant")
#: The 2 Hz grid of the plan: every other 4 Hz `minimap_dark` time.
ABILITY_HZ = 2.0
#: At most this many gate components are stored per sample, largest first.
MAX_COMPONENTS = 8


def teal_gate(tl: np.ndarray, mask: np.ndarray, ms: MapScale = shapes.SET_AT) -> list[list[int]]:
    """The teal components at least GATE_EXTENT_BASE across, largest first, as
    [x, y, w, h, pixels]; an empty list closes the gate."""
    b = ((tl >= GATE_TEAL) & mask).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    ext = ms.px(GATE_EXTENT_BASE)
    keep = [[int(v) for v in st[i, :5]] for i in range(1, n)
            if max(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]) >= ext]
    return sorted(keep, key=lambda c: -c[4])


def _rounded(v, n=4):
    return None if v is None else round(float(v), n)


class AbilityShapeReader:
    """`passes.Reader` writing the `ability_gate` and `ability_shape_scan`
    streams from one read of each 2 Hz sample."""

    #: It reads the cache on its own grid, and records a clip to its rounds.
    cache_resample = True
    records_clip = True

    def __init__(self, floor, sgray, support, box, phase_at=None, hz=ABILITY_HZ,
                 spans=None, name="ability", ms: MapScale | None = shapes.SET_AT):
        self.name, self.hz, self.spans = name, hz, spans
        self.frames_from = "video"
        self.cv_threads = 1
        self.floor, self.sgray, self.support, self.box = floor, sgray, support, box
        self.phase_at = phase_at
        #: The key's transform from base values; None refuses every sample.
        self.ms = ms
        self.gate_rows: list[dict] = []
        self.shape_rows: list[dict] = []

    def feed(self, smp) -> None:
        x0, y0, x1, y1 = self.box
        crop = smp.frame[y0:y1, x0:x1]
        row = {"kind": "frame", "frame_idx": int(smp.frame_idx), "t_ms": float(smp.t_ms)}
        phase = None if self.phase_at is None else self.phase_at(float(smp.t_ms))
        row["phase"] = phase
        if self.phase_at is not None and phase not in LIVE_PHASES:
            self.gate_rows.append({**row, "gate": None, "reason": "not_live"})
            return
        if crop.shape[:2] != self.floor.shape[:2]:
            self.gate_rows.append({**row, "gate": None, "reason": "geometry_size_mismatch"})
            return
        if self.ms is None:
            self.gate_rows.append({**row, "gate": None, "reason": "no_map_scale"})
            return
        if not widget_drawn(crop, self.sgray, self.floor):
            self.gate_rows.append({**row, "gate": None, "reason": "widget_not_drawn"})
            return
        tl = shapes.teal(crop)
        _, mask = shapes.widget(crop.shape)
        ms = self.ms
        comps = teal_gate(tl, mask, ms)
        self.gate_rows.append({**row, "gate": bool(comps), "reason": None,
                               "components": comps[:MAX_COMPONENTS]})
        if not comps:
            return
        rings = shapes.ring_candidates(tl, mask, ms, self.support)
        beam = shapes.widened_beam(tl, mask, ms, self.support)
        self.shape_rows.append({
            **row,
            "rings": [{"score": _rounded(f["score"]), "cx": f["cx"], "cy": f["cy"], "r": f["r"],
                       "coarse": _rounded(f["coarse"]), "accepted": f["accepted"]} for f in rings],
            "beam": None if beam is None else {
                "score": _rounded(beam["score"]), "theta_deg": _rounded(beam["theta_deg"], 1),
                "x0": _rounded(beam["x0"], 1), "y0": _rounded(beam["y0"], 1),
                "x1": _rounded(beam["x1"], 1), "y1": _rounded(beam["y1"], 1),
                "on_map": _rounded(beam.get("on_map"), 3),
                "accepted": shapes.beam_accepted(beam)}})

    def _common(self, session_id, geometry_key, extra) -> dict:
        return {"session_id": session_id, "source": "minimap", "geometry_key": geometry_key,
                **extra}

    def _head(self, common, frames) -> dict:
        head = {**common, "kind": "coverage", "hz": self.hz, "frames": frames,
                "support": None if self.support is None else "art_footprint",
                "frames_from": self.frames_from,
                "map_scale": None if self.ms is None else self.ms.provenance()}
        clip = getattr(self, "spans_clip", None)
        if clip is not None:
            head["spans_clip"] = clip
        return head

    def gate_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_gate_version": ABILITY_GATE_VERSION})
        by = {}
        for r in self.gate_rows:
            k = r["reason"] or ("gated" if r["gate"] else "closed")
            by[k] = by.get(k, 0) + 1
        head = {**self._head(common, len(self.gate_rows)), "by_reason": by,
                "gate_teal": GATE_TEAL, "gate_extent_base": round(GATE_EXTENT_BASE, 4)}
        return [head] + [{**common, **r} for r in self.gate_rows]

    def shape_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_shape_scan_version": ABILITY_SHAPE_VERSION,
                               "ability_shape_version": ABILITY_SHAPE_VERSION,
                               "ability_gate_version": ABILITY_GATE_VERSION})
        head = {**self._head(common, len(self.shape_rows)),
                "rings_accepted": sum(any(f["accepted"] for f in r["rings"])
                                      for r in self.shape_rows),
                "beams_accepted": sum(bool(r["beam"] and r["beam"]["accepted"])
                                      for r in self.shape_rows)}
        return [head] + [{**common, **r} for r in self.shape_rows]


def shape_reader(ctx, spans, phase_at=None, hz: float = ABILITY_HZ,
                 floor=None, sgray=None) -> AbilityShapeReader:
    """The `AbilityShapeReader` `scan` builds for a session
    (`passes.SessionContext`): the baked floor and base map, the key's
    transform (`geometry.map_scale`), the map's art footprint at
    `ability_shapes.support_dilate`, over the profile's minimap ROI."""
    from . import geometry
    from .minimap import minimap_roi_px
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    floor = ctx.floor() if floor is None else floor
    ms = geometry.map_scale_of(ctx.session_id, ctx.store.root)
    support = None if ms is None else geometry.footprint(
        ctx.session_id, ctx.store.root, dilate=shapes.support_dilate(ms), shape=floor.shape[:2])
    return AbilityShapeReader(floor=floor, sgray=ctx.sgray() if sgray is None else sgray,
                              support=support, box=box, phase_at=phase_at, hz=hz, spans=spans,
                              ms=ms)
