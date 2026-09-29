"""The team's adjudicated vision, per frame, as a stored product.

The chain the player built -- `cone.resolve_lobe` per frame against the drawn
light, `track` resolved facing, `minimap_lifecycle` eligibility, and the
`cone.observable` union of the eligible cones -- ran only inside `overlay` and
stored nothing, so no adjudicator could consume it. This module holds that
chain once. `overlay` draws from it and `reticle vision` stores it; neither
restates a stage, and every stage is its owner's call:

    widget_drawn, ally_icons, self_icons   minimap        (pixels)
    stalled_at                             stalls         (stored primitives)
    lit_mask                               lighting       (pixels)
    resolve_lobe, observable               cone
    Tracker                                track
    light_support, distance_agreement      minimap_diagnostics
    Lifecycle                              minimap_lifecycle

**Pixels come from the minimap crop cache, never the capture.** Four stages
read pixels: `widget_drawn`, `ally_icons`, `self_icons` and `lit_mask`. The
stored L1 minimap rows carry positions but no bearing and no light, so the
command reads the lossless `roi_cache` minimap crops (`roi-cache-0.1.0`) at
the cache's own 15 Hz, in time order, because the trackers and the lifecycle
hold state across frames. Frames outside the cache's spans are not in the
product; a reader asking for one gets no row, never a guessed area.

**What is stored.** One `frame` row per cached frame: the widget state, every
tracked icon with its resolved bearing and lifecycle eligibility, and two
masks packed with `lighting.pack_mask` -- `observable`, the union of the
ELIGIBLE cones (the adjudicated vision), and `observable_all`, the union of
every tracked bearing (what `overlay` tints without `--minimap-lifecycle`).
A stale or absent widget stores no mask and says which.

**Order against the ability adjudicator.** A smoke blocks the drawn light, and
the drawn light refuses ability candidates, so the two could wait on each
other. The loop is broken by time. This product reads no ability entity
today: its rays stop at the baked geometry's boxes only, so behind a smoke it
over-claims, which the ability rule tolerates because a sliver must also be
lit to be refused. When smokes enter the rays, the vision at frame t may
consume only entities accepted at frames before t -- the previous frame's
accepted entities -- and the ability adjudicator at t reads the vision at t.
Nothing ever iterates to a fixed point.

Owns [owns:team-vision].
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import cone as cone_mod
from . import geometry, lighting
from .minimap import (ally_icons, floor_mask, minimap_roi_px, self_icons, slab_mask,
                      widget_drawn, widget_scale)
from .minimap_diagnostics import DIAGNOSTICS_VERSION, distance_agreement, light_support
from .minimap_lifecycle import LIFECYCLE_VERSION, Lifecycle
from .stalls import STALL_VERSION, stalled_at
from .track import Tracker


@dataclass
class VisionInputs:
    """Everything the chain needs that does not change frame to frame.

    Every map pixel comes from the baked `(map, profile)` geometry; the session
    supplies only the widget's box.
    """

    box: tuple
    floor: np.ndarray
    passable: np.ndarray
    sgray: np.ndarray
    slab: np.ndarray | None = None
    static: np.ndarray | None = None
    light: object = None
    stalls: list | None = None
    geometry_key: str | None = None
    notes: list = field(default_factory=list)


def load_inputs(store_root, session_id: str, profile, width: int, height: int):
    """The chain's inputs for one session, or `(None, reason)`."""
    import cv2

    geo = geometry.path_of(session_id, store_root)
    if geo is None or not geo.is_file():
        return None, "no_geometry"
    med = geometry.reference_static(session_id, store_root)
    sd = geometry.stability(session_id, store_root, med.shape[:2])
    floor = floor_mask(med, sd=sd)
    inputs = VisionInputs(box=minimap_roi_px(profile, width, height), floor=floor,
                          passable=floor, slab=slab_mask(med, sd=sd),
                          sgray=cv2.cvtColor(med, cv2.COLOR_BGR2GRAY).astype(np.float64),
                          static=med, geometry_key=geometry.key_of(session_id, store_root))
    with np.load(geo) as z:
        if "labels" in z.files and z["labels"].shape == floor.shape:
            inputs.passable = cone_mod.passable_from(z["labels"], floor)
            inputs.notes.append("geometry labels loaded (a box stops a ray and is not lit)")
            # The lighting reference rides along with the labels: the same npz
            # and key. Without it a bearing keeps its lobe ambiguity.
            inputs.light = lighting.reference(z)
            inputs.notes.append(
                "lighting reference loaded, lobes resolved against the drawn light "
                f"({lighting.LIGHTING_VERSION})" if inputs.light is not None else
                "geometry predates the two-state reference -- bearings keep their lobe ambiguity")
        else:
            inputs.notes.append("geometry present but unusable -- floor only, which under-claims")
    return inputs, None


@dataclass
class VisionFrame:
    """One frame of the chain. `observable` is None when the widget is not read."""

    t_ms: float
    widget: str
    diagnostic: dict
    allies: list = field(default_factory=list)
    selves: list = field(default_factory=list)
    principal: object = None
    resolved: list = field(default_factory=list)
    adjudicated_resolved: list = field(default_factory=list)
    tracked: list = field(default_factory=list)
    eligible: set = field(default_factory=set)
    observable_all: np.ndarray | None = None
    observable: np.ndarray | None = None


class TeamVision:
    """The chain, stateful across frames; drive it in time order."""

    def __init__(self, floor, passable, sgray, *, width: int, slab=None, static=None,
                 light=None, stalls=None, origin_events=(), track_self=None,
                 track_ally=None, lifecycle=None):
        self.floor, self.passable, self.sgray = floor, passable, sgray
        self.slab, self.static, self.light = slab, static, light
        self.stalls, self.origin_events = stalls, tuple(origin_events or ())
        self.scale = widget_scale(width)
        # The error term is `track.FIT_ERR_PX`, not restated here.
        self.track_self = track_self if track_self is not None else Tracker("walker", scale=self.scale)
        self.track_ally = track_ally if track_ally is not None else Tracker("walker", scale=self.scale)
        self.lifecycle = lifecycle if lifecycle is not None else Lifecycle(scale=self.scale)

    @classmethod
    def from_inputs(cls, inputs: VisionInputs, origin_events=()):
        x0, _y0, x1, _y1 = inputs.box
        return cls(inputs.floor, inputs.passable, inputs.sgray, width=x1 - x0,
                   slab=inputs.slab, static=inputs.static, light=inputs.light,
                   stalls=inputs.stalls, origin_events=origin_events)

    def step(self, crop: np.ndarray, t_ms: float) -> VisionFrame:
        known_stalls = self.stalls
        # **A frozen source is not an observation.** The stall fact is the
        # source's, read from stored primitives (`stalls`). An ABSENT widget
        # is the more specific fact and is asked first: a static overlay such
        # as the buy panel is unchanging without the capture having stalled.
        drawn = widget_drawn(crop, self.sgray, self.floor)
        stale = stalled_at(known_stalls, t_ms) and drawn
        if stale or not drawn:
            self.track_self.step(t_ms, [])
            self.track_ally.step(t_ms, [])
            diagnostic = {"version": DIAGNOSTICS_VERSION, "t_ms": t_ms,
                          "widget": "stale" if stale else "not_drawn",
                          "observations": [], "stall_version": STALL_VERSION,
                          "stalls_known": known_stalls is not None,
                          "reason": ("source not advancing (l1/primitives motion)"
                                     if stale else "widget unavailable")}
            self.lifecycle.step(diagnostic)
            return VisionFrame(t_ms, diagnostic["widget"], diagnostic)

        # `require_facing=False` keeps a refused bearing as a detection: the
        # gap is what limits the area, and hiding it hides the limit.
        allies = ally_icons(crop, self.floor, require_facing=False,
                            support=self.slab, static=self.static)
        # Every self candidate goes to the tracker, and the TRACK decides
        # (`track.Tracker.principal`).
        selves = self_icons(crop, self.floor, require_facing=False, support=self.slab)
        raw_allies, raw_selves = [dict(d) for d in allies], [dict(d) for d in selves]

        # The light settles the ring fit's 180-degree lobe before the tracker
        # sees the bearing (`cone.resolve_lobe`).
        lit = None
        if self.light is not None:
            lit = lighting.lit_mask(crop, self.light)
            allies = cone_mod.resolve_lobe(self.passable, lit, allies, visible=self.floor)
            selves = cone_mod.resolve_lobe(self.passable, lit, selves, visible=self.floor)

        # Bearings come from the TRACKS, not from this frame's fit
        # (`track.Track.resolved_facing`).
        self.track_self.step(t_ms, selves)
        self.track_ally.step(t_ms, allies)
        principal = self.track_self.principal()
        self_tracks = [principal] if principal is not None else []
        resolved = (self.track_ally.bearings(t_ms)
                    + self.track_self.bearings(t_ms, tracks=self_tracks))

        # Three-tuples ONLY: `resolved`'s fourth element is `interpolated`,
        # and `observable`'s fourth is a per-icon HALF-ANGLE.
        agg, _per = cone_mod.observable(
            self.passable, [(bx, by, deg) for bx, by, deg, _ in resolved], visible=self.floor)

        by_pos = {(round(bx), round(by)): deg for bx, by, deg, _ in resolved}
        known = self.light.known if self.light is not None else None
        observations = []
        for role, tracks in (("ally", self.track_ally.tracks), ("self", self_tracks)):
            for tr in tracks:
                fresh = tr.t_ms == t_ms
                support = light_support(tr.x, tr.y, lit, known, self.scale) if fresh else None
                observations.append({"role": role, "track_id": tr.tid,
                                     "x": tr.x, "y": tr.y, "r": tr.r,
                                     "observed_t_ms": tr.t_ms,
                                     "position_state": "observed" if fresh else "carried",
                                     "gap_ms": t_ms - tr.t_ms, "light_support": support,
                                     "facing": by_pos.get((round(tr.x), round(tr.y)))})
        diagnostic = {
            "version": DIAGNOSTICS_VERSION, "t_ms": t_ms, "widget": "drawn",
            "stall_version": STALL_VERSION,
            "stalls_known": known_stalls is not None, "observations": observations,
            "raw_allies": raw_allies, "raw_self": raw_selves,
            "light_budget": {"lit": int(lit.sum()) if lit is not None else None,
                             "known": int(known.sum()) if known is not None else None},
            "distance_agreement": distance_agreement(
                agg, lit, known, [(x, y) for x, y, deg, _ in resolved if deg is not None],
                self.scale)}
        adjudicated = self.lifecycle.step(diagnostic, self.origin_events)
        diagnostic["lifecycle_version"] = LIFECYCLE_VERSION
        diagnostic["adjudication"] = adjudicated
        eligible = {row["observation_key"] for row in adjudicated if row["eligible"]}
        tracked = ([("ally", tr) for tr in self.track_ally.tracks]
                   + [("self", tr) for tr in self_tracks])
        adjudicated_resolved = [
            (x, y, deg if f"{role}:{tr.tid}" in eligible else None, carried)
            for (role, tr), (x, y, deg, carried) in zip(tracked, resolved)]
        adjudicated_agg, _ = cone_mod.observable(
            self.passable, [(x, y, deg) for x, y, deg, _ in adjudicated_resolved],
            visible=self.floor)
        diagnostic["adjudicated_distance_agreement"] = distance_agreement(
            adjudicated_agg, lit, known,
            [(x, y) for x, y, deg, _ in adjudicated_resolved if deg is not None], self.scale)
        return VisionFrame(t_ms, "drawn", diagnostic, allies=allies, selves=selves,
                           principal=principal, resolved=resolved,
                           adjudicated_resolved=adjudicated_resolved, tracked=tracked,
                           eligible=eligible, observable_all=agg,
                           observable=adjudicated_agg)


def _num(v):
    return None if v is None else float(v)


def frame_row(frame: VisionFrame, frame_idx: int | None = None) -> dict:
    """The stored row for one frame: icons, eligibility and both packed masks."""
    row = {"kind": "frame", "t_ms": float(frame.t_ms), "frame_idx": frame_idx,
           "widget": frame.widget}
    if frame.observable is None:
        row.update(observable=None, observable_all=None, icons=[],
                   reason=frame.diagnostic.get("reason"))
        return row
    icons = []
    for (role, tr), (x, y, deg, carried), (_x, _y, adj, _c) in zip(
            frame.tracked, frame.resolved, frame.adjudicated_resolved):
        icons.append({"role": role, "track_id": int(tr.tid), "x": _num(x), "y": _num(y),
                      "facing": _num(deg), "interpolated": bool(carried),
                      "eligible": f"{role}:{tr.tid}" in frame.eligible,
                      "casts": adj is not None})
    floor = int(frame.observable.size)
    row.update(icons=icons,
               observable=lighting.pack_mask(frame.observable),
               observable_all=lighting.pack_mask(frame.observable_all),
               observable_px=int(frame.observable.sum()),
               observable_all_px=int(frame.observable_all.sum()),
               widget_px=floor, reason=None)
    return row

