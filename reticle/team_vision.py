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
    SelfConeReader, IconPoseReader         teardrop       (pixels: centre, facing)
    Tracker                                track
    light_support, distance_agreement      minimap_diagnostics
    Lifecycle                              minimap_lifecycle

**Pixels come from the minimap crop cache, never the capture.** Five stages
read pixels: `widget_drawn`, `ally_icons`, `self_icons`, `lit_mask` and the
teardrop origin. The
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

**Every cone from the teardrop (0.2.0, 0.3.0, 0.5.0, 0.6.0).** The ring fit finds each
icon; the teardrop reads its centre and facing (`teardrop.SelfConeReader`
for the player, `teardrop.IconPoseReader` for teammates, scaled by
`minimap.widget_scale`), and the tracker, the lifecycle and every cone take
those in place of the ring fit's. The ring fit's centre sits 2.8 to 4.4 px
toward the self apex, and E4 of docs/STATISTICAL_ADJUDICATOR.md found the
rays start at the teardrop's centre with no offset
[domain:minimap/cone-origin-near-centre]; the ring fit's facing flips on
about half of the icons the player labelled, self and ally alike, the
teardrop's on almost none (E6). A cone observed this frame faces this
frame's teardrop facing, not the track's windowed mean. Where the teardrop
is unread (`low_ncc`, `ambiguous_facing`, `no_key`), or reads the self icon
under its widget size's facing gate (`teardrop.self_facing_gate`: NCC 0.55
on a 331 px widget, where the player's labels set it, `facing_reason`
`low_ncc_labelled_gate`; `teardrop.SELF_FACING_MIN_NCC` on a size no labels
cover, `low_ncc_unlabelled_scale`; none at 465 px), the icon casts no cone:
`RING_FALLBACK` is off, and with it
on the icon would keep the
ring fit's facing, the light would resolve its lobe (`cone.resolve_lobe`,
which a teardrop facing never enters) and the cone would face the track's
resolved lobe. Each stored icon's `pose` names the `origin` (`teardrop` or
`ring_fit`) and the `facing` (`teardrop`, `track`, or None) its cone used,
with the teardrop's reasons. On a widget drawn turned over the icons' facing
arrows turn with the map [domain:minimap/upright-icons-on-turned-map], so the
teardrop's facing needs no correction in the baked frame.

**Teammates come from the stored `ally_icon` stream (0.7.0).** The ally
reader (`minimap.AllyIconReader`, owner of `ally-candidates`) already fits
every teammate's ring and poses it by its teardrop (`icon-pose`), with the
prior that continues each icon's previous fit; the chain fitting them again
cost about half of `reticle vision`'s time and could publish another pose
for the same icon. `StoredAllyPoses` reads the stream's published teammates
(family `ally`; barriers and stacked-icon members are left out, as the ring
fit here never proposed them) and hands each to `teardrop.posed` with this
chain's own `ring_fallback`, so an unread teardrop casts nothing here
although the stream keeps the ring fit's facing. On a drawn frame the
stream did not read -- one outside the spans the scan asked it for, one its
round-cache clip skipped, or one whose widget it found absent -- the team's
`observable` is refused as `widget` `ally_unread` with the frame's own
cause (`UNREAD_CAUSES`) and no refit; the self icon, which never depended
on the stream, is still tracked and cast, and its cone is stored as
`observable_self` (0.7.1). The lifecycle holds the `ally` role suspended
across such frames, as it holds every role across an absent widget. The
coverage row records the stream's stamp (`inputs.ally_icon`) and the count
per cause, so `plan` stales this product when the ally reader changes. Without `ally_poses` the chain fits
teammates itself, which only `overlay` and the prototypes do; the stored
product never does.

**The yellow icon after the player's death (0.8.0).** Guard 6 of
docs/PRIOR_DRIVEN_READERS.md: while the player is dead the minimap draws the
spectated teammate as the yellow icon [domain:minimap/self-icon-shows-spectated].
Given the player's dead intervals (`dead`, `adjudication.spectate`, which
rests on the death owner), the self track's icon is stored with role
`spectated` after the switch -- a teammate's observation, with `rests_on` the
spectate inference and no name, whose cone is the team's vision -- and with
role `player_dead` before it, casting nothing. It is never stored as the
player's icon there.

**On demand.** `at` computes the rows at chosen instants only, starting the
chain at the last cache gap its tracks and lifecycle expire across, so each
row equals the full run's except for track ids. `reticle vision --check`
compares a computation with the stored product without writing.

**Order against the ability adjudicator.** A smoke blocks the drawn light, and
the drawn light refuses ability candidates, so the two could wait on each
other. The loop is broken by time. This product reads no ability entity
today: its rays stop at the baked geometry's walls and boxes only (`occ`
where the geometry carries it, `cone.passable_from`), so behind a smoke it
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
from .teardrop import IconPoseReader, SelfConeReader, posed
from .minimap import (ally_icons, floor_mask, minimap_roi_px, self_icons, slab_mask,
                      widget_drawn, widget_scale)
from .minimap_diagnostics import DIAGNOSTICS_VERSION, distance_agreement, light_support
from .minimap_lifecycle import LIFECYCLE_VERSION, Lifecycle
from .stalls import STALL_VERSION, stalled_at
from .track import Tracker
from .usage import step as usage_step

#: An icon whose teardrop gives no facing casts from the ring fit along its
#: track's resolved lobe (True), or casts nothing (False). See `TeamVision`.
#: A cone cast the wrong way is worse than none: the stored vision refuses
#: ability candidates, so false light discards real observations. Measured by
#: `prototypes/team_vision_eval.py` (the light joined to the team's icons,
#: placed without a facing): with no fallback the team's precision is at
#: least team-vision-0.3.0's on 5822b6646448, 223d636bf8d2 and c40d950031bb;
#: the fallback adds recall at 465 px but lowers precision on c40d950031bb
#: below 0.3.0's.
RING_FALLBACK = False

#: The ring fit's fields a stored `ally_icon` row carries, which the tracker
#: and the light's lobe resolution read as `ally_icons` returns them.
_RING_FIELDS = ("r", "cov", "inner", "inner_v", "lobe", "area", "map_diff")
#: The teardrop read's fields `teardrop.posed` keeps under `pose`.
_POSE_FIELDS = ("ncc", "reason", "facing_reason", "search", "surprise", "rests_on", "audit")
#: Why a drawn frame's teammates are unread, from the stored stream: it
#: found the widget absent; or it stored no frame, because the frame lies in
#: a span its round-cache clip skipped (`spans_skipped`), in a span it read
#: (`spans_read`), or in no span the scan asked it to read (`spans_asked`:
#: on a06f04a0059f, 3694746e4e54 and bdfdcf009dba every refused frame);
#: `no_frame` where the stream records no clip to place the frame against.
UNREAD_CAUSES = ("widget_absent", "outside_cache_rounds", "outside_live_rounds",
                 "no_frame_in_read_span", "outside_spans_asked", "no_frame")


def _ally_icon_schema():
    """The columns `StoredAllyPoses` reads from an `ally_icon` stream.

    `audit` is `teardrop._audit_view`'s record for the prior and the full
    search; the other `pose` fields are those `teardrop.posed` keeps.
    """
    import pyarrow as pa

    f64, txt = pa.float64(), pa.string()
    view = pa.struct([("x", f64), ("y", f64), ("deg", f64), ("ncc", f64), ("margin", f64),
                      ("read", pa.bool_()), ("reason", txt)])
    pose = pa.struct([("origin", txt), ("ncc", f64), ("reason", txt), ("facing_reason", txt),
                      ("search", txt), ("surprise", txt), ("rests_on", txt),
                      ("audit", pa.struct([("prior", view), ("full", view)]))])
    ring = pa.struct([("cx", f64), ("cy", f64), ("facing", f64)])
    return pa.schema([("kind", txt), ("frame_idx", pa.int64()), ("t_ms", f64),
                      ("widget_drawn", pa.bool_()), ("cx", f64), ("cy", f64), ("facing", f64),
                      ("facing_source", txt), ("family", txt), ("origin", txt),
                      ("ring", ring), ("pose", pose),
                      *[(k, f64) for k in _RING_FIELDS]])


def _spans(v) -> np.ndarray:
    return np.asarray(v if v else [], float).reshape(-1, 2)


def _within(spans: np.ndarray, t: float) -> bool:
    return bool(np.any((spans[:, 0] <= t) & (t <= spans[:, 1])))


def _value(a: np.ndarray, i: int):
    """Element `i` of a column as the stored row held it: None for a null."""
    v = a[i]
    if isinstance(v, (float, np.floating)):
        return None if np.isnan(v) else float(v)
    return v


class StoredAllyPoses:
    """Each frame's teammates as the stored `ally_icon` stream publishes them.

    `at(frame_idx, ring_facing, t_ms)` returns `(detections, None)`, the
    stream's teammates as ring-fit detections posed by their stored teardrop
    read (`teardrop.posed`, with `ring_facing` the caller's), or
    `(None, cause)` where the stream holds no drawn frame there. The cause
    is one of `UNREAD_CAUSES`, read per frame from the stream's own frame
    rows and its head's `spans_clip`; `reason(cause)` words it. Only family
    `ally` rows are teammates here: a `barrier` is furniture and a
    `stack_fit` member has no ring fit (`AllyIconReader._stack`), and the
    ring-fit chain never saw either. Builds no pose of its own.

    The stream is held as columns (`pyarrow`, then numpy) sorted by frame
    once; only the stepped frame's few icons become dicts.
    """

    def __init__(self, table, head: dict | None = None):
        import pyarrow.compute as pc

        head = head or {}
        self.version = head.get("ally_icon_version")
        clip = head.get("spans_clip")
        self.clip = clip if isinstance(clip, dict) else None
        self.spans = {k: _spans((self.clip or {}).get(k))
                      for k in ("spans_asked", "spans_read", "spans_skipped")}
        kind = table.column("kind")
        frames = table.filter(pc.equal(kind, "frame"))
        fidx = frames.column("frame_idx").to_numpy()
        order = np.argsort(fidx, kind="stable")
        self._frame_idx = fidx[order]
        self._drawn = np.asarray(frames.column("widget_drawn").fill_null(False)
                                 .to_numpy(zero_copy_only=False), bool)[order]

        icons = table.filter(pc.equal(kind, "icon"))

        def col(c):
            return np.asarray(c.to_numpy(zero_copy_only=False))

        def num(c):
            return col(c.fill_null(np.nan)).astype(float)

        barrier = col(icons.column("family")) == "barrier"
        stack = ((col(icons.column("origin")) == "stack_fit")
                 | (col(icons.column("facing_source")) == "stack_fit")) & ~barrier
        self.skipped = {"barrier": int(barrier.sum()), "stack_fit": int(stack.sum())}
        keep = np.flatnonzero(~barrier & ~stack)
        keep = keep[np.argsort(col(icons.column("frame_idx"))[keep], kind="stable")]
        icons = icons.take(keep)
        self._icon_frame = col(icons.column("frame_idx")).astype(np.int64)

        self._cx, self._cy = num(icons.column("cx")), num(icons.column("cy"))
        self._facing = num(icons.column("facing"))
        ring = icons.column("ring").combine_chunks()
        has_ring = col(ring.is_valid()).astype(bool)
        # A row without its ring fit keeps its own centre and facing as the ring's.
        self._ring = {k: np.where(has_ring, num(ring.field(k)), own)
                      for k, own in (("cx", self._cx), ("cy", self._cy),
                                     ("facing", self._facing))}
        self._fields = {k: num(icons.column(k)) for k in _RING_FIELDS}
        self._teardrop = col(icons.column("facing_source")) == "teardrop"
        pose = icons.column("pose").combine_chunks()
        self._has_pose = col(pose.is_valid()).astype(bool)
        self._pose = {k: col(pose.field(k)) for k in ("origin", "reason", "facing_reason",
                                                      "search", "surprise", "rests_on")}
        self._pose["ncc"] = num(pose.field("ncc"))
        self._audit = pose.field("audit")
        self._has_audit = col(self._audit.is_valid()).astype(bool)

    @classmethod
    def from_rows(cls, rows: list[dict], head: dict | None = None):
        """From stored `frame` and `icon` rows, as a test writes them."""
        import pyarrow as pa

        return cls(pa.Table.from_pylist(list(rows), schema=_ally_icon_schema()), head)

    @classmethod
    def from_store(cls, store, session_id: str):
        """`(StoredAllyPoses, None)`, or `(None, reason)` with no stream.

        `pyarrow.json` parses the stream's columns on one thread and leaves
        every field this chain does not read.
        """
        import json

        import pyarrow.json as pj

        path = store.events_path("ally_icon", session_id)
        if not path.is_file():
            return None, "no ally_icon stream"
        with open(path, "rb") as f:
            first = f.readline()
        head = json.loads(first) if first.strip() else {}
        if head.get("kind") != "coverage":
            return None, "ally_icon stream has no coverage row"
        table = pj.read_json(
            path, read_options=pj.ReadOptions(use_threads=False, block_size=1 << 24),
            parse_options=pj.ParseOptions(explicit_schema=_ally_icon_schema(),
                                          unexpected_field_behavior="ignore"))
        return cls(table, head), None

    def cause(self, frame_idx: int, t_ms: float | None = None) -> str | None:
        """Why the stream holds no drawn frame at `frame_idx` (`UNREAD_CAUSES`),
        or None where it holds one. A missing frame is placed by `t_ms`
        against the head's `spans_clip`; without a clip or a time it is
        `no_frame`."""
        i = int(np.searchsorted(self._frame_idx, int(frame_idx)))
        if i < self._frame_idx.size and self._frame_idx[i] == int(frame_idx):
            return None if self._drawn[i] else "widget_absent"
        if self.clip is None or t_ms is None:
            return "no_frame"
        # A decode clipped to the live rounds says so (`outside_live_rounds`).
        skipped = self.clip.get("reason") or "outside_cache_rounds"
        if _within(self.spans["spans_skipped"], t_ms):
            return skipped
        if _within(self.spans["spans_read"], t_ms):
            return "no_frame_in_read_span"
        # `spans_asked` None asked for the whole capture, so everything
        # outside `spans_read` is skipped (`roi_cache.clip_record`).
        if self.clip.get("spans_asked") is None:
            return skipped
        if not _within(self.spans["spans_asked"], t_ms):
            return "outside_spans_asked"
        return "no_frame"

    @staticmethod
    def reason(cause: str) -> str:
        """The refusal's words for one of `UNREAD_CAUSES`."""
        if cause == "widget_absent":
            return "ally_icon found the widget absent here (widget_absent)"
        return f"ally_icon stored no frame here ({cause})"

    def at(self, frame_idx: int, ring_facing: bool, t_ms: float | None = None):
        cause = self.cause(frame_idx, t_ms)
        if cause is not None:
            return None, cause
        lo, hi = np.searchsorted(self._icon_frame, [int(frame_idx), int(frame_idx) + 1])
        return [self._posed(i, ring_facing) for i in range(int(lo), int(hi))], None

    def _posed(self, i: int, ring_facing: bool) -> dict:
        d = {"cx": _value(self._ring["cx"], i), "cy": _value(self._ring["cy"], i),
             "facing": _value(self._ring["facing"], i),
             **{k: _value(a, i) for k, a in self._fields.items()}, "barrier": False}
        if self._has_pose[i]:
            p = {"origin": self._pose["origin"][i] or "ring_fit",
                 "ncc": _value(self._pose["ncc"], i),
                 **{k: self._pose[k][i] for k in ("reason", "facing_reason", "search",
                                                   "surprise", "rests_on")}}
            if self._has_audit[i]:
                p["audit"] = self._audit[i].as_py()
        else:
            p = {"origin": "ring_fit"}
        read = {"origin": p["origin"], "x": _value(self._cx, i), "y": _value(self._cy, i),
                "deg": _value(self._facing, i) if self._teardrop[i] else None,
                **{k: p[k] for k in _POSE_FIELDS if k in p}}
        return posed(d, read, ring_facing=ring_facing)


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
    #: The geometry's occluder stamp (`occ_built_by`), or None when it has no
    #: `occ` and the rays stop only at the art's box edges.
    occluders: str | None = None
    #: With `occ`: each box pixel's id, and the grid with the boxes open, for
    #: the per-cone crossing report (`cone.box_crossings`).
    box_id: np.ndarray | None = None
    open_boxes: np.ndarray | None = None
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
            occ = z["occ"] if "occ" in z.files else None
            inputs.passable = cone_mod.passable_from(z["labels"], floor, occ)
            if occ is not None and occ.shape == floor.shape:
                inputs.occluders = str(z["occ_built_by"]) if "occ_built_by" in z.files else "?"
                inputs.box_id = z["box_id"].copy() if "box_id" in z.files else None
                inputs.open_boxes = cone_mod.passable_from(z["labels"], floor, occ,
                                                           boxes_block=False)
                inputs.notes.append("occluders loaded: rays stop at the static's walls and "
                                    "boxes (occ)")
            else:
                inputs.notes.append("geometry labels loaded (a box stops a ray and is not lit); "
                                    "no occluder table, so the art's box edges are the only walls")
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
    #: Per `resolved` entry, where its cone starts: `(x, y, origin)`, origin
    #: `teardrop`, `ring_fit`, or None for a track not observed this frame.
    origins: list = field(default_factory=list)
    #: Per `resolved` entry, its pose record (`TeamVision._posed`'s `pose`
    #: plus `x`, `y`, the `facing` source and the track's `track_deg`), or
    #: None for a track not observed this frame.
    poses: list = field(default_factory=list)
    #: The principal self icon's pose record, or None when it is not
    #: observed this frame.
    self_cone: dict | None = None
    #: Per `resolved` entry, its cast cone (None where the bearing is refused).
    cones: list = field(default_factory=list)
    #: Per `resolved` entry, the ids of the boxes its cone crossed with the
    #: boxes open (`cone.box_crossings`); empty when the geometry has no `occ`.
    crossed: list = field(default_factory=list)
    #: Where the yellow icon is not the player (guard 6): `state`
    #: (`spectated` or `player_dead`) and what it rests on; None while he lives.
    self_state: dict | None = None
    observable_all: np.ndarray | None = None
    observable: np.ndarray | None = None
    #: On an `ally_unread` frame, the self icon's eligible cone alone;
    #: `observable` stays None there, since the team's vision is unread.
    observable_self: np.ndarray | None = None


class TeamVision:
    """The chain, stateful across frames; drive it in time order."""

    def __init__(self, floor, passable, sgray, *, width: int, slab=None, static=None,
                 light=None, stalls=None, origin_events=(), track_self=None,
                 track_ally=None, lifecycle=None, distance_diagnostics=True,
                 box_id=None, open_boxes=None,
                 ring_fallback: bool = RING_FALLBACK,
                 ally_poses: StoredAllyPoses | None = None, dead=None):
        self.floor, self.passable, self.sgray = floor, passable, sgray
        self.box_id, self.open_boxes = box_id, open_boxes
        #: The player's dead intervals (`adjudication.spectate.DeadIndex`),
        #: or None: guard 6 is then not applied, and the stored coverage row
        #: says so.
        self.dead = dead
        self.slab, self.static, self.light = slab, static, light
        self.stalls, self.origin_events = stalls, tuple(origin_events or ())
        self.scale = widget_scale(width)
        # The error term is `track.FIT_ERR_PX`, not restated here.
        self.track_self = track_self if track_self is not None else Tracker("walker", scale=self.scale)
        self.track_ally = track_ally if track_ally is not None else Tracker("walker", scale=self.scale)
        self.lifecycle = lifecycle if lifecycle is not None else Lifecycle(scale=self.scale)
        self.self_cone_reader = SelfConeReader(scale=self.scale)
        self.ally_pose_reader = IconPoseReader("ally", scale=self.scale)
        #: Whether an icon whose teardrop is unread casts from the ring fit's
        #: centre along its track's resolved lobe. `RING_FALLBACK` is the
        #: stored product's; the other value exists to measure the fallback.
        self.ring_fallback = ring_fallback
        #: The stored `ally_icon` teammates (`StoredAllyPoses`), which the
        #: stored product reads in place of fitting them again; None fits
        #: them here (`overlay`, the prototypes), and `step` then needs no
        #: frame index.
        self.ally_poses = ally_poses
        #: `distance_agreement` is a diagnostic `overlay` shows and nothing
        #: stores or decides on; it was 29% of `reticle vision`'s time, and
        #: the stored product runs without it.
        self.distance_diagnostics = distance_diagnostics

    @classmethod
    def from_inputs(cls, inputs: VisionInputs, origin_events=(), **kw):
        x0, _y0, x1, _y1 = inputs.box
        return cls(inputs.floor, inputs.passable, inputs.sgray, width=x1 - x0,
                   slab=inputs.slab, static=inputs.static, light=inputs.light,
                   stalls=inputs.stalls, origin_events=origin_events,
                   box_id=inputs.box_id, open_boxes=inputs.open_boxes, **kw)

    def step(self, crop: np.ndarray, t_ms: float, masks: bool = True,
             frame_idx: int | None = None) -> VisionFrame:
        """Advance the chain one frame.

        `masks=False` advances every stateful stage -- trackers, principal,
        lifecycle -- and casts no union cone: a warm-up frame whose masks
        nobody reads. Such a frame returns `observable` None and is never a
        stored row.

        With `ally_poses`, `frame_idx` names the cache frame whose stored
        teammates the chain reads. **An unread teammate is not an unread
        self.** On a drawn frame the stream holds no teammates for, the self
        icon is read, tracked and cast as on any drawn frame; the ally
        tracker sees no detection and the lifecycle sees the `ally` role
        unread (`Lifecycle.step`'s `unread_roles`). The frame returns
        `widget` `ally_unread` with the stream's cause (`UNREAD_CAUSES`) and
        reason, `observable` None -- the team's vision is unread -- and the
        self cone alone as `observable_self`.
        """
        known_stalls = self.stalls
        # **A frozen source is not an observation.** The stall fact is the
        # source's, read from stored primitives (`stalls`). An ABSENT widget
        # is the more specific fact and is asked first: a static overlay such
        # as the buy panel is unchanging without the capture having stalled.
        drawn = widget_drawn(crop, self.sgray, self.floor)
        stale = stalled_at(known_stalls, t_ms) and drawn
        unread = None
        if self.ally_poses is not None and drawn and not stale:
            if frame_idx is None:
                raise ValueError("TeamVision with ally_poses steps by frame index")
            stored, unread = self.ally_poses.at(frame_idx, ring_facing=self.ring_fallback,
                                                t_ms=t_ms)
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

        # The ring fit FINDS each icon; the teardrop supplies its centre and
        # facing wherever it reads (`teardrop.SelfConeReader`,
        # `teardrop.IconPoseReader`), before the tracker sees either. The
        # stored product takes the teammates `ally_icon` found and posed; where
        # it found none to read, the ally tracker sees no detection.
        if self.ally_poses is not None:
            allies = stored if unread is None else []
            raw_allies = [dict(d) for d in allies]
        else:
            with usage_step("allies"):
                # `require_facing=False` keeps a refused bearing as a
                # detection: the gap is what limits the area, and hiding it
                # hides the limit.
                allies = ally_icons(crop, self.floor, require_facing=False,
                                    support=self.slab, static=self.static)
                raw_allies = [dict(d) for d in allies]
                allies = [self._posed(crop, d, self.ally_pose_reader) for d in allies]
        with usage_step("self"):
            # Every self candidate goes to the tracker, and the TRACK decides
            # (`track.Tracker.principal`).
            selves = self_icons(crop, self.floor, require_facing=False, support=self.slab)
            raw_selves = [dict(d) for d in selves]
            selves = [self._posed(crop, d, self.self_cone_reader) for d in selves]

        # The light settles the ring fit's 180-degree lobe (`cone.resolve_lobe`)
        # on a fallback bearing only; a teardrop points one way.
        lit = None
        if self.light is not None:
            lit = lighting.lit_mask(crop, self.light)
            allies = self._resolve_fallback(lit, allies)
            selves = self._resolve_fallback(lit, selves)

        self.track_self.step(t_ms, selves)
        self.track_ally.step(t_ms, allies)
        principal = self.track_self.principal()
        self_tracks = [principal] if principal is not None else []
        resolved = (self.track_ally.bearings(t_ms)
                    + self.track_self.bearings(t_ms, tracks=self_tracks))
        tracked = ([("ally", tr) for tr in self.track_ally.tracks]
                   + [("self", tr) for tr in self_tracks])

        # Each cone observed this frame starts at its detection's teardrop
        # centre and faces this frame's teardrop facing. Where the teardrop is
        # unread it starts at the ring fit's centre along the track's resolved
        # lobe, if `ring_fallback` and the track resolves one, and each pose
        # record names both sources. A track not observed this frame casts
        # nothing (`track.Tracker.bearings`).
        posed = {"ally": {(d["cx"], d["cy"]): d for d in allies},
                 "self": {(d["cx"], d["cy"]): d for d in selves}}
        origins, poses = [], []
        for i, ((role, tr), (x, y, track_deg, _c)) in enumerate(zip(tracked, resolved)):
            d = posed[role].get((tr.x, tr.y)) if tr.t_ms == t_ms else None
            if d is None:
                origins.append((x, y, None))
                poses.append(None)
                continue
            pose = dict(d["pose"], x=float(x), y=float(y), track_deg=track_deg)
            if d["facing_source"] == "teardrop":
                resolved[i] = (x, y, d["facing"], False)
                pose["facing"] = "teardrop"
            elif d["facing_source"] == "ring_fit":
                pose["facing"] = "track" if track_deg is not None else None
            else:
                # No facing this frame: `bearings` casts nothing for a track
                # whose facing was not observed now, whatever it carries.
                pose["facing"] = None
            origins.append((x, y, pose["origin"]))
            poses.append(pose)
        self_cone = poses[-1] if self_tracks else None

        # Guard 6 (`adjudication.spectate`): after the player's death the
        # yellow icon is not him. After the switch it is the spectated
        # teammate, whose cone is the team's vision; before it the death
        # camera's, which casts nothing.
        self_state = None
        iv = self.dead.at(t_ms) if self.dead is not None else None
        if iv is not None and self_tracks:
            from .adjudication.spectate import SPECTATE_VERSION
            spectated = iv.spectated(t_ms)
            self_state = {"state": "spectated" if spectated else "player_dead",
                          "rests_on": "spectate_switch" if spectated else iv.rests_on,
                          "dead_rests_on": iv.rests_on, "switch_ms": iv.switch_ms,
                          "spectate_version": SPECTATE_VERSION}
            if not spectated:
                x, y, _deg, carried = resolved[-1]
                resolved[-1] = (x, y, None, carried)
                self_cone = None

        # Three-tuples ONLY: `resolved`'s fourth element is `interpolated`,
        # and `observable`'s fourth is a per-icon HALF-ANGLE.
        agg = per_icon = None
        if masks:
            agg, per_icon = cone_mod.observable(
                self.passable, [(ox, oy, deg) for (ox, oy, _s), (_x, _y, deg, _c)
                                in zip(origins, resolved)],
                visible=self.floor)
        # Which boxes each cone would cross if the caster could see over them:
        # the report the drawn light decides a box pass from. Stored, not cast.
        crossed = []
        if masks and self.box_id is not None and self.open_boxes is not None:
            crossed = [None if deg is None else sorted(cone_mod.box_crossings(
                self.open_boxes, self.box_id, ox, oy, deg, visible=self.floor)[1])
                for (ox, oy, _s), (_x, _y, deg, _c) in zip(origins, resolved)]

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
        }
        if unread is not None:
            # A missing teammate observation, not a missing teammate: the
            # lifecycle suspends the role (`Lifecycle.step`).
            diagnostic["unread_roles"] = ["ally"]
        if masks and self.distance_diagnostics:
            diagnostic["distance_agreement"] = distance_agreement(
                agg, lit, known, [(x, y) for x, y, deg, _ in resolved if deg is not None],
                self.scale)
        adjudicated = self.lifecycle.step(diagnostic, self.origin_events)
        diagnostic["lifecycle_version"] = LIFECYCLE_VERSION
        diagnostic["adjudication"] = adjudicated
        eligible = {row["observation_key"] for row in adjudicated if row["eligible"]}
        adjudicated_resolved = [
            (x, y, deg if f"{role}:{tr.tid}" in eligible else None, carried)
            for (role, tr), (x, y, deg, carried) in zip(tracked, resolved)]
        # The eligible cones are a subset of the cones just cast, at the same
        # origins and bearings; their union is taken, not cast again.
        adjudicated_agg = None if not masks else cone_mod.union(
            [m for m, (_x, _y, deg, _c) in zip(per_icon, adjudicated_resolved)
             if deg is not None], self.passable.shape)
        if masks and self.distance_diagnostics:
            diagnostic["adjudicated_distance_agreement"] = distance_agreement(
                adjudicated_agg, lit, known,
                [(x, y) for x, y, deg, _ in adjudicated_resolved if deg is not None],
                self.scale)
        frame = VisionFrame(t_ms, "drawn", diagnostic, allies=allies, selves=selves,
                            principal=principal, resolved=resolved,
                            adjudicated_resolved=adjudicated_resolved, tracked=tracked,
                            eligible=eligible, origins=origins, poses=poses,
                            self_cone=self_cone, cones=per_icon or [], crossed=crossed,
                            observable_all=agg,
                            observable=adjudicated_agg, self_state=self_state)
        if unread is not None:
            # Only the self icon cast: its eligible cone is the self cone, and
            # the team's vision stays unread.
            diagnostic.update(widget="ally_unread", ally_unread_cause=unread,
                              reason=f"ally poses unread: {StoredAllyPoses.reason(unread)}")
            frame.widget, frame.observable_self = "ally_unread", adjudicated_agg
            frame.observable = frame.observable_all = None
        return frame

    def _posed(self, crop: np.ndarray, d: dict, reader) -> dict:
        """The detection `d` posed by its teardrop (`teardrop.posed`). An
        unread teardrop keeps the ring fit's centre and, only with
        `ring_fallback`, its facing for the light to resolve; otherwise the
        detection carries no facing and casts nothing."""
        return posed(d, reader.read(crop, d["cx"], d["cy"]), ring_facing=self.ring_fallback)

    def _resolve_fallback(self, lit, dets: list[dict]) -> list[dict]:
        """`cone.resolve_lobe` on the detections whose facing is the ring fit's."""
        idx = [i for i, d in enumerate(dets) if d["facing_source"] == "ring_fit"]
        if not idx:
            return dets
        out = list(dets)
        for i, e in zip(idx, cone_mod.resolve_lobe(self.passable, lit, [dets[i] for i in idx],
                                                   visible=self.floor)):
            out[i] = e
        return out


def _num(v):
    return None if v is None else float(v)


def frame_row(frame: VisionFrame, frame_idx: int | None = None) -> dict:
    """The stored row for one frame: icons, eligibility and both packed masks.

    Every icon's cone starts at its `x`, `y` along its `facing`. Its `pose`
    says where both came from (`TeamVision._posed`): the `origin`
    (`teardrop` or `ring_fit`), the `facing` source (`teardrop`, `track`,
    or None), the teardrop's NCC and refusal `reason`, and the track's own
    bearing as `track_deg`; None for a track not observed this frame.
    Where the geometry carries boxes, each icon records `boxes_crossed`: the
    boxes its cone crosses with the boxes open (None without a facing).
    An `ally_unread` row stores `observable` None with its `reason` and
    `ally_unread_cause`, and, where the chain cast, the self cone as
    `observable_self` beside the icons.
    """
    row = {"kind": "frame", "t_ms": float(frame.t_ms), "frame_idx": frame_idx,
           "widget": frame.widget}
    partial = frame.widget == "ally_unread" and frame.observable_self is not None
    if frame.observable is None and not partial:
        row.update(observable=None, observable_all=None, icons=[],
                   reason=frame.diagnostic.get("reason"))
        if frame.widget == "ally_unread":
            row["ally_unread_cause"] = frame.diagnostic.get("ally_unread_cause")
        return row
    icons = []
    poses = frame.poses or [None] * len(frame.tracked)
    for i, ((role, tr), (x, y, deg, carried), (_x, _y, adj, _c), pose) in enumerate(zip(
            frame.tracked, frame.resolved, frame.adjudicated_resolved, poses)):
        icon = {"role": role, "track_id": int(tr.tid), "x": _num(x), "y": _num(y),
                "facing": _num(deg), "interpolated": bool(carried),
                "eligible": f"{role}:{tr.tid}" in frame.eligible,
                "casts": adj is not None, "pose": pose}
        if frame.crossed:
            icon["boxes_crossed"] = frame.crossed[i]
        if role == "self" and frame.self_state is not None:
            # Not the player: a spectated teammate's observation, named by
            # nobody here, or the death camera's view.
            icon["role"] = frame.self_state["state"]
            icon["rests_on"] = {k: v for k, v in frame.self_state.items() if k != "state"}
        icons.append(icon)
    if partial:
        # The teammates are unread: the self cone is stored apart, and the
        # team's `observable` stays None with the reason.
        row.update(icons=icons, observable=None, observable_all=None,
                   observable_self=lighting.pack_mask(frame.observable_self),
                   observable_self_px=int(frame.observable_self.sum()),
                   widget_px=int(frame.observable_self.size),
                   reason=frame.diagnostic.get("reason"),
                   ally_unread_cause=frame.diagnostic.get("ally_unread_cause"))
        return row
    floor = int(frame.observable.size)
    row.update(icons=icons,
               observable=lighting.pack_mask(frame.observable),
               observable_all=lighting.pack_mask(frame.observable_all),
               observable_px=int(frame.observable.sum()),
               observable_all_px=int(frame.observable_all.sum()),
               widget_px=floor, reason=None)
    return row



def at_plan(times, instants, warmup_ms: float | None = None, expiry_ms: float = 500.0):
    """The cached frames to step for vision at `instants`, as runs.

    Each instant asks for the cached frames on either side of it, so a reader
    taking the nearest stored frame finds the same one it would find in the
    full product. **The chain starts at the last reset before each frame**: a
    gap in the cache longer than `expiry_ms`, across which every track and
    every lifecycle anchor expires on elapsed time. The lifecycle carries
    eligibility by continuity for as long as an entity is seen, so a shorter
    warm-up is not the full run: on a06f04a0059f a 10 s warm-up missed the
    full run's mask at some candidate frames. `warmup_ms` caps the warm-up
    anyway, for a caller that accepts that.

    Overlapping windows merge into one run. Returns
    `[(frame_times, emit_times)]`, each run in time order; `emit_times` are the
    frames whose rows are wanted.
    """
    T = np.asarray(sorted({float(t) for t in times}), float)
    if not T.size:
        return []
    resets = T[np.r_[True, np.diff(T) > expiry_ms]]
    want = set()
    for t in instants:
        i = int(np.searchsorted(T, float(t)))
        for j in (i - 1, i):
            if 0 <= j < T.size:
                want.add(float(T[j]))
    runs: list[tuple[list, set]] = []
    for f in sorted(want):
        start = float(resets[np.searchsorted(resets, f, side="right") - 1])
        if warmup_ms is not None:
            start = max(start, f - warmup_ms)
        frames = T[(T >= start) & (T <= f)]
        if runs and runs[-1][0][-1] >= frames[0]:
            last, emit = runs[-1]
            last.extend(float(x) for x in frames if x > last[-1])
            emit.add(f)
        else:
            runs.append(([float(x) for x in frames], {f}))
    return runs


def at(cache, inputs, instants, warmup_ms: float | None = None, **kw):
    """Vision rows at `instants` only: `[(frame_idx, VisionFrame)]` in time order.

    The on-demand form of the full run, for an adjudicator that needs a few
    instants. Each run of `at_plan` starts a fresh chain; its warm-up frames
    advance the trackers and the lifecycle and cast no union cone. The reset
    gap is the chain's own expiry, asked of its trackers and lifecycle.

    Two things cross a reset and so differ from the full run: track ids,
    which count from each run's start, and the self tracker's memory of the
    principal's last position (`track.Tracker.principal`), which picks among
    several self tracks after a gap. `--check` counts where either shows.
    """
    x0, y0, x1, y1 = inputs.box
    probe = TeamVision.from_inputs(inputs, **kw)
    expiry = max(probe.track_self.max_gap_ms, probe.track_ally.max_gap_ms,
                 probe.lifecycle.max_gap_ms)
    out = []
    for frames, emit in at_plan(cache.t_ms, instants, warmup_ms, expiry):
        vision = TeamVision.from_inputs(inputs, **kw)
        for smp in cache.samples(frames, rois=["minimap"]):
            got = vision.step(smp.frame[y0:y1, x0:x1], smp.t_ms, masks=smp.t_ms in emit,
                              frame_idx=smp.frame_idx)
            if smp.t_ms in emit:
                out.append((smp.frame_idx, got))
    return out


def compare_rows(computed: list[dict], stored: list[dict]) -> dict:
    """Compare frame rows by time: identical rows, masks, and icons less ids.

    `computed` rows missing from `stored` count as missing; the session and
    version fields are not compared.
    """
    skip = ("session_id", "team_vision_version")
    by_t = {float(r["t_ms"]): r for r in stored if r.get("kind") == "frame"}

    def bare(r):
        return {k: v for k, v in r.items() if k not in skip}

    def icons(r):
        return [{k: v for k, v in i.items() if k != "track_id"} for i in r.get("icons") or []]

    got = {"frames": 0, "missing": 0, "rows_equal": 0, "masks_equal": 0,
           "icons_equal_but_ids": 0, "differ_at_ms": []}
    for r in computed:
        if r.get("kind") != "frame":
            continue
        got["frames"] += 1
        s = by_t.get(float(r["t_ms"]))
        if s is None:
            got["missing"] += 1
            continue
        same_masks = (r.get("observable") == s.get("observable")
                      and r.get("observable_all") == s.get("observable_all"))
        got["rows_equal"] += bare(r) == bare(s)
        got["masks_equal"] += same_masks
        got["icons_equal_but_ids"] += icons(r) == icons(s)
        if not same_masks:
            got["differ_at_ms"].append(float(r["t_ms"]))
    return got
