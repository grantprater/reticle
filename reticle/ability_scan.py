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
| `ability_fit` | gated samples; live drawn samples an own-gate candidate opens | `ability_shapes.fit_shape` per ring and beam candidate | `ability_fit_version`, the shape, candidate and values stamps |
| `ability_wall` | live drawn samples with a wall component | `fit_shape` per segments and curve candidate | `ability_wall_version`, the same |
| `ability_shape_scan` | gated samples no candidate explains | `ring_candidates`, `widened_beam` (the surprise path) | `ability_shape_scan_version`, the `ability_shape_version`, over the gate's |
| `ability_shape_audit` | every AUDIT_EVERY-th gated sample | the same full search | `ability_shape_audit_version`, the same |

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

The candidates (0.4.0). `scan` passes the session's candidate supply
(`ability_candidates.for_session`, built from the stored lineup, deaths,
rounds and self track) as data; this module imports no adjudicator. At each
sample the supply names the descriptors its context allows and why it left
the rest out. A gated sample fits every ring and beam candidate
(`ability_fit`, one row per sample holding every fit with its descriptor id,
score, alternatives and the candidate's `rests_on`). A ring or beam
candidate whose hue band misses the teal gate's (`own_gate`; today the enemy
Lockdown's yellow ring [domain:abilities/killjoy-lockdown-enemy-minimap-ring])
is fit on every live drawn sample where its own colour forms a component the
teal gate would accept, with `gate: "own_colour"`; it never spares a sample
the surprise path, which searches teal. Every live drawn sample
fits every wall candidate, because a wall need not be teal (`ability_wall`,
stored only where a component of the drawn width exists). A fit names the
descriptor it was scored against, never the caster: who drew it stays the
arbiter's (`adjudication.identity`).

The surprise path. Where no ring or beam candidate is accepted on a gated
sample, or no supply exists (its reason in the head), the whole-widget
search of 0.3.0 runs (`ring_candidates`, centres on the map's footprint, and
`widened_beam` along the longest teal segment) and goes to
`ability_shape_scan` with the reason. Every AUDIT_EVERY-th gated sample,
counted from the first and fixed in advance, runs the same search whatever
the candidates found and goes to `ability_shape_audit`: a surprise-triggered
search is no audit sample (AGENTS.md, "Continue the prior"). The surprise
rows name no ability, caster or side: colour follows the side
[domain:minimap/ability-drawing-colour-by-side].

Not for. Smokes (`minimap_dark`, `adjudication.smokes`); tracks, lifecycles
and names (`adjudication.ability`, `adjudication.phases`, the arbiter).
"""
from __future__ import annotations

import cv2
import numpy as np

from . import ability_shapes as shapes
from .geometry import MapScale
from .minimap import widget_drawn
from .version import (ABILITY_CANDIDATES_VERSION, ABILITY_FIT_VERSION, ABILITY_GATE_VERSION,
                      ABILITY_SHAPE_VERSION, ABILITY_WALL_VERSION)

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
#: Every AUDIT_EVERY-th gated sample, from the first, runs the full search
#: (`ability_shape_audit`); fixed before any run.
AUDIT_EVERY = 10
#: The candidate shapes each stream fits.
FIT_SHAPES, WALL_SHAPES = ("ring", "beam"), ("segments", "curve")


def teal_gate(tl: np.ndarray, mask: np.ndarray, ms: MapScale = shapes.SET_AT) -> list[list[int]]:
    """The teal components at least GATE_EXTENT_BASE across, largest first, as
    [x, y, w, h, pixels]; an empty list closes the gate."""
    b = ((tl >= GATE_TEAL) & mask).astype(np.uint8)
    n, _, st, _ = cv2.connectedComponentsWithStats(b, connectivity=8)
    ext = ms.px(GATE_EXTENT_BASE)
    keep = [[int(v) for v in st[i, :5]] for i in range(1, n)
            if max(st[i, cv2.CC_STAT_WIDTH], st[i, cv2.CC_STAT_HEIGHT]) >= ext]
    return sorted(keep, key=lambda c: -c[4])


def own_gate(d: dict) -> bool:
    """Whether a ring or beam candidate opens its own gate: its colour model's
    hue band misses the teal gate's (`ability_shapes.TEAL_H`), so the teal
    gate says nothing of whether it is drawn."""
    lo, hi = d["colour"]["hue"]
    return hi < shapes.TEAL_H[0] or lo > shapes.TEAL_H[1]


def _rounded(v, n=4):
    return None if v is None else round(float(v), n)


_DROP = object()


def _plain(v, n=3):
    """A fit's value as stored: floats rounded; arrays and objects dropped."""
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        return round(float(v), n)
    if isinstance(v, dict):
        return {k: p for k, p in ((k, _plain(x, n)) for k, x in v.items()) if p is not _DROP}
    if isinstance(v, (list, tuple)):
        return [p for p in (_plain(x, n) for x in v) if p is not _DROP]
    if v is None or isinstance(v, str):
        return v
    return _DROP


def fit_row(f: dict, d: dict) -> dict:
    """One candidate's fit as stored: the fit's scalars, the descriptor by id
    (the head holds it whole), and what the candidate rests on."""
    row = _plain({k: v for k, v in f.items()
                  if k not in ("descriptor", "map_scale", "ability_shape_version")})
    row.update({"descriptor": d.get("id"), "selected": d.get("selected"),
                "caster_alive": d.get("caster_alive"),
                "seed": None if d.get("seed") is None else [round(float(c), 1) for c in d["seed"]],
                "rests_on": d.get("rests_on")})
    return row


def full_search(tl: np.ndarray, mask: np.ndarray, ms: MapScale, support) -> dict:
    """The surprise path's whole-widget search on one sample, as stored."""
    rings = shapes.ring_candidates(tl, mask, ms, support)
    beam = shapes.widened_beam(tl, mask, ms, support)
    return {
        "rings": [{"score": _rounded(f["score"]), "cx": f["cx"], "cy": f["cy"], "r": f["r"],
                   "coarse": _rounded(f["coarse"]), "accepted": f["accepted"]} for f in rings],
        "beam": None if beam is None else {
            "score": _rounded(beam["score"]), "theta_deg": _rounded(beam["theta_deg"], 1),
            "x0": _rounded(beam["x0"], 1), "y0": _rounded(beam["y0"], 1),
            "x1": _rounded(beam["x1"], 1), "y1": _rounded(beam["y1"], 1),
            "on_map": _rounded(beam.get("on_map"), 3),
            "accepted": shapes.beam_accepted(beam)}}


class AbilityShapeReader:
    """`passes.Reader` writing the `ability_gate`, `ability_fit`,
    `ability_wall`, `ability_shape_scan` and `ability_shape_audit` streams
    from one read of each 2 Hz sample.

    `supply` is the session's `ability_candidates.CandidateSupply` (anything
    with `at(t_ms)` and `stamp`), or None with `supply_reason`; then every
    gated sample takes the surprise path."""

    #: It reads the cache on its own grid, and records a clip to its rounds.
    cache_resample = True
    records_clip = True

    def __init__(self, floor, sgray, support, box, phase_at=None, hz=ABILITY_HZ,
                 spans=None, name="ability", ms: MapScale | None = shapes.SET_AT,
                 supply=None, supply_reason: str | None = "no_supply",
                 audit_every: int = AUDIT_EVERY, values: str | None = None):
        self.name, self.hz, self.spans = name, hz, spans
        self.frames_from = "video"
        self.cv_threads = 1
        self.floor, self.sgray, self.support, self.box = floor, sgray, support, box
        self.phase_at = phase_at
        #: The key's transform from base values; None refuses every sample.
        self.ms = ms
        self.supply = supply
        self.supply_reason = None if supply is not None else supply_reason
        #: `ability_candidates.values_digest` of the descriptors' facts.
        self.values = values
        self.audit_every = audit_every
        self.gate_rows: list[dict] = []
        self.fit_rows: list[dict] = []
        self.wall_rows: list[dict] = []
        self.shape_rows: list[dict] = []
        self.audit_rows: list[dict] = []
        self.descriptors: dict = {}
        self.excluded: dict = {}
        self.n_gated = 0

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
        cands, excl = [], []
        if self.supply is not None:
            got = self.supply.at(float(smp.t_ms))
            cands, excl = got["candidates"], got["excluded"]
            for d in cands:
                self.descriptors.setdefault(d["id"], _plain(shapes.descriptor_ref(d)))
            for e in excl:
                k = f"{e['ability']}:{e['side']}:{e['reason'].split(':')[0]}"
                self.excluded[k] = self.excluded.get(k, 0) + 1
        walls = [fit_row(f, d) for d, f in
                 ((d, shapes.fit_shape(crop, d, None, self.support, ms))
                  for d in cands if d["shape"] in WALL_SHAPES)
                 if f.get("reason") != "no_component"]
        if walls:
            self.wall_rows.append({**row, "walls": walls})
        # Candidates the teal gate cannot see open their own gate.
        own = [{**fit_row(shapes.fit_shape(crop, d, d.get("seed"), self.support, ms), d),
                "gate": "own_colour"}
               for d in cands if d["shape"] in FIT_SHAPES and own_gate(d)
               and teal_gate(shapes.colour_weight(crop, d["colour"]), mask, ms)]
        comps = teal_gate(tl, mask, ms)
        self.gate_rows.append({**row, "gate": bool(comps), "reason": None,
                               "components": comps[:MAX_COMPONENTS]})
        kept = [{k: e[k] for k in ("ability", "side", "reason")}
                for e in excl if e["reason"] != "not_in_lineup"]
        if not comps:
            if own:
                self.fit_rows.append({**row, "teal_gate": False, "fits": own, "excluded": kept})
            return
        self.n_gated += 1
        fits = [fit_row(shapes.fit_shape(crop, d, d.get("seed"), self.support, ms), d)
                for d in cands if d["shape"] in FIT_SHAPES and not own_gate(d)]
        if self.supply is not None:
            # Every exclusion but the constant `not_in_lineup` can change
            # within a match, so each gated sample keeps its own.
            self.fit_rows.append({**row, "teal_gate": True, "fits": fits + own, "excluded": kept})
        accepted = any(f.get("found") for f in fits)
        audit = (self.n_gated - 1) % self.audit_every == 0
        if accepted and not audit:
            return
        full = full_search(tl, mask, ms, self.support)
        if not accepted:
            why = (self.supply_reason if self.supply is None else
                   "no_candidate" if not fits else "none_accepted")
            self.shape_rows.append({**row, "path": "surprise", "surprise_reason": why, **full})
        if audit:
            self.audit_rows.append({**row, "path": "audit", "audit_n": self.n_gated,
                                    "candidate_accepted": accepted, **full})

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

    def _supply_stamp(self) -> dict:
        """What a candidate stream records of the supply it was fed."""
        if self.supply is None:
            return {"ability_candidates_version": None, "supply": None,
                    "supply_reason": self.supply_reason, "appearance_values": self.values}
        st = dict(self.supply.stamp)
        return {"ability_candidates_version": st.pop("ability_candidates_version",
                                                    ABILITY_CANDIDATES_VERSION),
                "supply": st, "supply_reason": None, "appearance_values": self.values}

    def _rate(self) -> float | None:
        return round(len(self.shape_rows) / self.n_gated, 4) if self.n_gated else None

    @staticmethod
    def _accepted(rows) -> dict:
        return {"rings_accepted": sum(any(f["accepted"] for f in r["rings"]) for r in rows),
                "beams_accepted": sum(bool(r["beam"] and r["beam"]["accepted"]) for r in rows)}

    def shape_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_shape_scan_version": ABILITY_SHAPE_VERSION,
                               "ability_shape_version": ABILITY_SHAPE_VERSION,
                               "ability_gate_version": ABILITY_GATE_VERSION})
        by: dict = {}
        for r in self.shape_rows:
            by[r["surprise_reason"]] = by.get(r["surprise_reason"], 0) + 1
        head = {**self._head(common, len(self.shape_rows)), **self._accepted(self.shape_rows),
                "path": "surprise", "gated": self.n_gated, "by_reason": by,
                "surprise_rate": self._rate(), "supply_reason": self.supply_reason}
        return [head] + [{**common, **r} for r in self.shape_rows]

    def audit_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_shape_audit_version": ABILITY_SHAPE_VERSION,
                               "ability_shape_version": ABILITY_SHAPE_VERSION,
                               "ability_gate_version": ABILITY_GATE_VERSION,
                               "ability_fit_version": ABILITY_FIT_VERSION})
        head = {**self._head(common, len(self.audit_rows)), **self._accepted(self.audit_rows),
                "path": "audit", "audit_every": self.audit_every, "gated": self.n_gated,
                "candidate_accepted": sum(r["candidate_accepted"] for r in self.audit_rows)}
        return [head] + [{**common, **r} for r in self.audit_rows]

    def fit_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_fit_version": ABILITY_FIT_VERSION,
                               "ability_shape_version": ABILITY_SHAPE_VERSION,
                               "ability_gate_version": ABILITY_GATE_VERSION,
                               **self._supply_stamp()})
        found: dict = {}
        for r in self.fit_rows:
            for f in r["fits"]:
                c = found.setdefault(f["descriptor"], {"fits": 0, "found": 0})
                c["fits"] += 1
                c["found"] += bool(f.get("found"))
        head = {**self._head(common, len(self.fit_rows)), "gated": self.n_gated,
                "descriptors": {k: v for k, v in self.descriptors.items()
                                if v.get("shape") in FIT_SHAPES},
                "by_descriptor": found, "excluded": self.excluded,
                "own_colour_rows": sum(r.get("teal_gate") is False for r in self.fit_rows),
                "surprise": len(self.shape_rows), "surprise_rate": self._rate()}
        return [head] + [{**common, **r} for r in self.fit_rows]

    def wall_events(self, session_id: str, geometry_key: str | None) -> list[dict]:
        common = self._common(session_id, geometry_key,
                              {"ability_wall_version": ABILITY_WALL_VERSION,
                               "ability_shape_version": ABILITY_SHAPE_VERSION,
                               **self._supply_stamp()})
        found: dict = {}
        for r in self.wall_rows:
            for f in r["walls"]:
                c = found.setdefault(f["descriptor"], {"rows": 0, "found": 0, "piece": 0})
                c["rows"] += 1
                c["found"] += bool(f.get("found"))
                c["piece"] += f.get("reason") == "piece_only"
        head = {**self._head(common, len(self.wall_rows)),
                "descriptors": {k: v for k, v in self.descriptors.items()
                                if v.get("shape") in WALL_SHAPES},
                "by_descriptor": found}
        return [head] + [{**common, **r} for r in self.wall_rows]


def shape_reader(ctx, spans, phase_at=None, hz: float = ABILITY_HZ,
                 floor=None, sgray=None, supply=None, supply_reason: str | None = "no_supply",
                 values: str | None = None) -> AbilityShapeReader:
    """The `AbilityShapeReader` `scan` builds for a session
    (`passes.SessionContext`): the baked floor and base map, the key's
    transform (`geometry.map_scale`), the map's art footprint at
    `ability_shapes.support_dilate`, over the profile's minimap ROI, and the
    candidate supply the caller built (None: the surprise path alone)."""
    from . import geometry
    from .minimap import minimap_roi_px
    box = minimap_roi_px(ctx.profile, *ctx.wh)
    floor = ctx.floor() if floor is None else floor
    ms = geometry.map_scale_of(ctx.session_id, ctx.store.root)
    support = None if ms is None else geometry.footprint(
        ctx.session_id, ctx.store.root, dilate=shapes.support_dilate(ms), shape=floor.shape[:2])
    return AbilityShapeReader(floor=floor, sgray=ctx.sgray() if sgray is None else sgray,
                              support=support, box=box, phase_at=phase_at, hz=hz, spans=spans,
                              ms=ms, supply=supply, supply_reason=supply_reason, values=values)
