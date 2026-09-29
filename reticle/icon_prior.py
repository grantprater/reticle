"""One prior-driven tracker for every agent icon on the minimap, with the spike glyph.

Owns [owns:icon-prior].

The player asked (2026-09-29) for an icon and spike reader that works from
priors, as `AGENTS.md` asks of every reader ("Continue the prior; widen the
search only on surprise"). The last frame predicts this one: an icon moves
within a speed bound, a dropped spike does not move at all, and a carried
spike moves with its carrier. This module holds that prediction for the
readers that fit icons on the minimap crop, one frame at a time, and every
reader asks it rather than keeping its own. It restates no fit: the icon fits
are `minimap`'s, the glyph fits and the carrier geometry are `spike`'s, and
the self association is `minimap.pick_self_declared`.

**One mechanism, per-side priors.** A track's side is a parameter
(`SidePrior`), never a code path. Only two things are team-only: vision
cones, and the carried spike, which is never drawn on an enemy
[domain:minimap/spike-carrier-overlay]. An enemy icon is drawn only while in
the team's vision [domain:minimap/vision-gate] and swaps to a red "?" at its
last place when vision leaves it [domain:minimap/last-known-mark-timing], so
an enemy track continues through the "?" (`lost_mark`) and resumes within
reach. No reader fits enemy icons in `reticle/` yet; `SIDES["enemy"]` is the
seam an enemy reader takes.

**The spike glyph** (`GlyphTrack`). Once a dropped glyph is accepted its
place is fixed, and each later frame checks one template at that place and
state (`spike.verify_glyph`), a fraction of the full search's cost. A glyph
whose check fails before it has passed `CONFIRM_CHECKS` times sets no prior
(`glyph_unconfirmed`). A failed check on a confirmed glyph widens to the full
search (`spike.glyph_fits`): a carried glyph found anywhere is a pickup, a
dropped glyph found elsewhere is a surprise (`glyph_moved_without_carrier`),
and nothing found holds the glyph unverified for `HOLD_UNVERIFIED_MS` (a
portrait over it, a defuse), then drops it as `glyph_lost`. A carried glyph,
or none, is sought by the full search each frame. A planted spike reads as
dropped: base down, on the ground.

**The dropped glyph is masked, not refused.** The glyph is yellow and passes
the self key, so a self fit rings it; the ally fit meets it where a teammate
stands on it. The glyph's footprint (`spike.glyph_footprint`, its template at
its fixed place) is removed from every channel's key before any icon is
fitted (`minimap.icons(veto=...)`), so an icon standing on the spike -- the
player or a teammate planting or defusing, an enemy defusing -- is fitted
from the rest of its ring, and the glyph alone yields no fit. A fit that
overlapped the footprint says so (`glyph_masked`).

**A carried glyph flags its carrier and never rejects him.** The carrier's
icon sits above and to the right of its glyph (`spike.carrier_offset`); that
fit carries `carries_spike`, on a side whose prior allows it, and whoever it
is. Only a fit that rings the carried glyph itself (`spike.on_glyph`) is
refused, as `on_carried_glyph`. Which teammate carries is the roster
marker's and the lineup's question (`adjudication.spike_carrier`).

**What every result declares.** `rests_on` names what chose it: for the
glyph `prior` (checked at its fixed place), `prior_held` (held unverified),
`full_search` or `none`; for an icon track `minimap.SELF_PICK_RULES`
(`near_prior`, `sole_candidate`, `full_search`, `no_candidate`), and
`last_known` where a side's lost mark holds it. A surprise (a track jumping
past its speed bound, a glyph moving without a carrier, a glyph lost) is a
row, never averaged away. A full search blind to every prior and mask runs
on a cadence fixed in advance (`AuditClock`: every `AUDIT_EVERY` frames and
the first frame after a gap) and is stored apart, so the gated rows can be
checked against it.

A prior here comes only from the reader's own earlier frames, never from
another stream (docs/PRIOR_DRIVEN_READERS.md, guard 7). The player's death,
which ends his track, rests on the death owner and so belongs to the
consumers that recompute from storage (`adjudication.spectate`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import spike
from .minimap import pick_self_declared, self_icons

#: A dropped glyph that fails its check is held this long past its last
#: passing check before it is dropped as lost: a portrait over it, or an icon
#: standing on it through a defuse (7 s).
HOLD_UNVERIFIED_MS = 10_000.0
#: A dropped glyph sets the prior only after its check at its place passes
#: this many times: a one-frame accept of the olive site floor on
#: a06f04a0059f at 40.1 s was held ten seconds before this rule.
CONFIRM_CHECKS = 2
#: A gap in the frames longer than this expires every prior: a round
#: boundary or a cache span ends there.
RESET_GAP_MS = 5_000.0
#: The audit's cadence, in the reader's own frames, fixed before any outcome.
AUDIT_EVERY = 15
#: An enemy's "?" holds its place about this long
#: [domain:minimap/last-known-mark-timing].
LAST_KNOWN_MS = 3_100.0


@dataclass(frozen=True)
class SidePrior:
    """What a track on one side may do. `carries_spike`: a carried glyph can
    flag this side's icon. `lost_mark`: the mark the icon swaps to when it
    stops being drawn, which continues the track for `lost_hold_ms`
    instead of ending it. `cones`: the side draws vision cones."""

    side: str
    carries_spike: bool
    lost_mark: str | None = None
    lost_hold_ms: float = 0.0
    cones: bool = True


SIDES = {
    "self": SidePrior("self", carries_spike=True),
    "ally": SidePrior("ally", carries_spike=True),
    "enemy": SidePrior("enemy", carries_spike=False, lost_mark="last_known",
                       lost_hold_ms=LAST_KNOWN_MS, cones=False),
}


def _glyph(g: dict) -> dict:
    return {k: g.get(k) for k in ("cx", "cy", "state", "side", "ncc", "amp")}


class GlyphTrack:
    """The spike glyph on one reader's frames, from its own earlier frames."""

    def __init__(self, rotation: int = 0):
        self.rotation = int(rotation or 0)
        self.reset()

    def reset(self) -> None:
        self.fixed = None          # the dropped glyph, fixed at its drop
        self.verified_t = None
        self.checks = 0            # checks passed at its place since it was fixed
        self.last_t = None

    def step(self, crop: np.ndarray, support: np.ndarray | None, t_ms: float) -> dict:
        """This frame's glyph: `state` ("dropped", "carried" or None), `cx`,
        `cy`, `side`, `ncc`, `amp`, `rests_on`, `reason` and `surprises`."""
        from .minimap import widget_scale

        if self.last_t is not None and t_ms - self.last_t > RESET_GAP_MS:
            self.reset()
        self.last_t = t_ms
        sc = widget_scale(crop.shape[1])
        surprises: list[dict] = []
        none = {"state": None, "cx": None, "cy": None, "side": None, "ncc": None, "amp": None}
        if self.fixed is not None:
            v = spike.verify_glyph(crop, self.fixed, self.rotation)
            if v["reason"] is None and (v["ncc_flip"] is None or v["ncc_flip"] < v["ncc"]):
                self.verified_t, self.checks = t_ms, self.checks + 1
                return {**_glyph(self.fixed), "ncc": v["ncc"], "amp": v["amp"],
                        "rests_on": "prior", "reason": None, "surprises": surprises}
            confirmed = self.checks >= CONFIRM_CHECKS
            fits = spike.accepted(spike.glyph_fits(crop, support, self.rotation))
            carried = [g for g in fits if g["state"] == "carried"]
            dropped = [g for g in fits if g["state"] == "dropped"]
            here = [g for g in dropped if np.hypot(g["cx"] - self.fixed["cx"],
                                                   g["cy"] - self.fixed["cy"]) < spike.NMS_PX * sc]
            if here:
                self.verified_t, self.checks = t_ms, self.checks + 1
                return {**_glyph(self.fixed), "ncc": here[0]["ncc"], "amp": here[0]["amp"],
                        "rests_on": "full_search", "reason": None, "surprises": surprises}
            if not confirmed:
                # Seen, then not repeated at its place and not picked up: the
                # owner's accept was not a glyph that stays, so it sets no
                # prior.
                if not carried:
                    surprises.append({"kind": "glyph_unconfirmed", "t_ms": t_ms,
                                      "at": [self.fixed["cx"], self.fixed["cy"]],
                                      "checks": self.checks})
                self.fixed = None
                return self._fresh(fits, t_ms, surprises)
            if carried:
                self.fixed = None
                return self._fresh(carried, t_ms, surprises)
            if dropped:
                g = max(dropped, key=lambda f: f["ncc"])
                surprises.append({"kind": "glyph_moved_without_carrier", "t_ms": t_ms,
                                  "from": [self.fixed["cx"], self.fixed["cy"]],
                                  "to": [g["cx"], g["cy"]]})
                self.fixed = None
                return self._fresh([g], t_ms, surprises)
            if t_ms - self.verified_t <= HOLD_UNVERIFIED_MS:
                return {**_glyph(self.fixed), "ncc": v["ncc"], "amp": v["amp"],
                        "rests_on": "prior_held", "reason": v["reason"] or "flipped",
                        "surprises": surprises}
            surprises.append({"kind": "glyph_lost", "t_ms": t_ms,
                              "at": [self.fixed["cx"], self.fixed["cy"]],
                              "unverified_ms": t_ms - self.verified_t})
            self.fixed = None
            return {**none, "rests_on": "full_search", "reason": "glyph_lost",
                    "surprises": surprises}
        fits = spike.accepted(spike.glyph_fits(crop, support, self.rotation))
        return self._fresh(fits, t_ms, surprises)

    def _fresh(self, fits: list[dict], t_ms: float, surprises: list[dict]) -> dict:
        """The full search's answer with no prior: the strongest accepted
        glyph. A dropped one is fixed at its place and becomes the prior once
        its check passes `CONFIRM_CHECKS` times."""
        if not fits:
            return {"state": None, "cx": None, "cy": None, "side": None, "ncc": None,
                    "amp": None, "rests_on": "full_search", "reason": None,
                    "surprises": surprises}
        g = max(fits, key=lambda f: f["ncc"])
        if g["state"] == "dropped":
            self.fixed, self.verified_t, self.checks = _glyph(g), t_ms, 0
        return {**_glyph(g), "rests_on": "full_search", "reason": None, "surprises": surprises}


def _as_list(glyphs) -> list[dict]:
    if isinstance(glyphs, dict):
        glyphs = [glyphs]
    return [g for g in glyphs or () if g.get("state") is not None]


def veto_for(shape: tuple, glyphs, sc: float, rotation: int = 0) -> np.ndarray | None:
    """The dropped glyphs' footprints to remove from every key, or None: a
    carried glyph is not masked (its carrier's ring runs under it), a glyph
    held unverified (`prior_held`) is not drawn this frame and masks nothing,
    and no glyph masks nothing. `glyphs` is one glyph or a list.

    The held case matters: on a06f04a0059f every long unverified run viewed
    was the dropped glyph replaced at its place by a yellow "?" that then
    fades [domain:minimap/spike-last-known-mark], not a portrait over it."""
    out = None
    for g in _as_list(glyphs):
        if g["state"] != "dropped" or g.get("rests_on") == "prior_held":
            continue
        m = spike.glyph_footprint(shape, g, sc, rotation)
        out = m if out is None else out | m
    return out


def frame_glyphs(crop: np.ndarray, support: np.ndarray | None, rotation: int = 0) -> list[dict]:
    """The accepted glyphs of one frame by the full search, for a reader
    that holds no state across frames: `AllyIconReader` is split into
    interleaved shards (`pipeline._Shards`), so it cannot keep a
    `GlyphTrack`. Its glyphs rest on the full search."""
    return [{**g, "rests_on": "full_search"}
            for g in spike.accepted(spike.glyph_fits(crop, support, rotation))]


def occluded_fits(centroid: list[dict], surface: list[dict], sc: float) -> list[dict]:
    """The self fits with a veto: the centroid-seeded fit (every self number
    on record) where the veto touches no ring, and the surface-seeded fit
    (`minimap.icons(seed="surface")`) where it does. A ring the glyph covers
    in part is a few arcs whose centroid sits a radius from the centre, out
    of the centroid seed's reach; on the player's on-spike labels the surface
    seed found his ring where the centroid seed found none. One fit per
    `minimap.MIN_ICON_SEPARATION_PX`, the best coverage kept."""
    from .minimap import MIN_ICON_SEPARATION_PX
    cand = ([f for f in centroid if not f.get("veto_share")]
            + [f for f in surface if f.get("veto_share")])
    out: list[dict] = []
    for f in sorted(cand, key=lambda d: -d["cov"]):
        if any(np.hypot(f["cx"] - o["cx"], f["cy"] - o["cy"]) < MIN_ICON_SEPARATION_PX * sc
               for o in out):
            continue
        out.append(f)
    return out


def annotate(fits: list[dict], side: SidePrior, glyphs, sc: float,
             icons=(), rotation: int = 0) -> list[dict]:
    """Each fit with the glyphs' say on it, in place, and returned. `glyphs`
    is the frame's glyph or glyphs (`GlyphTrack.step`, `frame_glyphs`):

    * `glyph_masked`: a masked dropped glyph (`veto_for`) reached into the
      fit's ring -- its centroid within the fit's radius plus the glyph's
      circumradius -- so the fit was made from the rest of the ring;
    * `carries_spike`: a carried glyph sits at this fit's carrier place
      (`spike.carrier_offset` over `icons`, every fit of the frame that may
      carry), on a side that carries; never a refusal;
    * `refused`: `on_carried_glyph` where the fit rings a carried glyph
      itself (`spike.on_glyph` over `icons`), else None."""
    gl = _as_list(glyphs)
    carried = [{**g, "reason": None} for g in gl if g["state"] == "carried"]
    dropped = [g for g in gl if g["state"] == "dropped" and g.get("rests_on") != "prior_held"]
    carriers = []
    if side.carries_spike:
        carriers = [c for c in (spike.carrier_offset(g, list(icons), sc, rotation)
                                for g in carried) if c is not None]
    for f in fits:
        f["glyph_masked"] = any(
            np.hypot(f["cx"] - g["cx"], f["cy"] - g["cy"])
            <= f.get("r", 10.0 * sc) + float(g.get("side") or 21.0) * sc / np.sqrt(3.0)
            for g in dropped)
        f["carries_spike"] = any(c["cx"] == f["cx"] and c["cy"] == f["cy"] for c in carriers)
        f["refused"] = None
        if carried and not f["carries_spike"]:
            if spike.on_glyph(f["cx"], f["cy"], carried, sc, icons=icons, rotation=rotation):
                f["refused"] = "on_carried_glyph"
    return fits


class IconTrack:
    """One icon's track under its side's prior: the previous point within a
    speed bound (`minimap.pick_self_declared`, the self-position owner's
    rule), declared, with a jump past the bound stored as a surprise."""

    def __init__(self, prior: SidePrior, scale: float, step_ms: float):
        self.prior, self.scale, self.step_ms = prior, scale, step_ms
        self.reset()

    def reset(self) -> None:
        self.prev = self.prev_t = None

    def step(self, t_ms: float, fits: list[dict]) -> dict:
        dt = self.step_ms if self.prev_t is None else t_ms - self.prev_t
        p = pick_self_declared(fits, self.prev, dt, self.scale)
        surprises = []
        if p["xy"] is not None:
            if p["widened"]:
                surprises.append({"kind": f"{self.prior.side}_jump", "t_ms": t_ms,
                                  "from": [round(v, 2) for v in self.prev],
                                  "to": [round(v, 2) for v in p["xy"]],
                                  "dt_ms": round(dt, 1)})
            self.prev, self.prev_t = p["xy"], t_ms
        elif (self.prior.lost_mark and self.prev is not None
              and t_ms - self.prev_t <= self.prior.lost_hold_ms):
            p = {**p, "rests_on": self.prior.lost_mark, "held_xy": self.prev}
        return {**p, "surprises": surprises}


class AuditClock:
    """The fixed audit cadence: every `every`-th frame the reader steps, and
    the first frame after a gap longer than `RESET_GAP_MS`. It reads nothing
    the prior or an outcome decides."""

    def __init__(self, every: int = AUDIT_EVERY):
        self.every, self.n, self.last_t = every, 0, None

    def tick(self, t_ms: float) -> bool:
        first = self.last_t is None or t_ms - self.last_t > RESET_GAP_MS
        self.last_t = t_ms
        due = first or self.n % self.every == 0
        self.n += 1
        return due


def audit_row(crop: np.ndarray, floor: np.ndarray, slab: np.ndarray | None,
              t_ms: float, rotation: int = 0) -> dict:
    """The full search, blind to every prior and mask: the best-coverage
    self fit and every accepted glyph."""
    fits = self_icons(crop, floor, require_facing=False, support=slab)
    best = max(fits, key=lambda f: f["cov"]) if fits else None
    glyphs = spike.accepted(spike.glyph_fits(crop, slab, rotation))
    return {"kind": "audit", "t_ms": float(t_ms),
            "self": None if best is None else [round(best["cx"], 2), round(best["cy"], 2)],
            "self_candidates": len(fits),
            "glyphs": [[g["cx"], g["cy"], g["state"]] for g in glyphs]}


class SelfTracker:
    """The self client: the glyph track and the self icon's track, stepped on
    one crop per frame. `_MinimapPass` feeds it; the ally reader composes the
    same parts (`GlyphTrack`, `veto_for`, `annotate`)."""

    def __init__(self, floor, slab, scale: float, step_ms: float, rotation: int = 0):
        self.floor, self.slab, self.scale, self.rotation = floor, slab, scale, int(rotation or 0)
        self.glyph = GlyphTrack(self.rotation)
        self.track = IconTrack(SIDES["self"], scale, step_ms)
        self.clock = AuditClock()
        self.audits: list[dict] = []
        self.surprises: list[dict] = []
        self.last_t = None

    def widget_absent(self, t_ms: float) -> None:
        """A frame without the widget advances the audit clock's gap test and
        nothing else: the priors hold across it by elapsed time."""
        self.last_t = t_ms

    def step(self, crop: np.ndarray, t_ms: float) -> dict:
        """The frame's self point and glyph, as `l1/minimap` columns."""
        if self.last_t is not None and t_ms - self.last_t > RESET_GAP_MS:
            self.track.reset()
        self.last_t = t_ms
        if self.clock.tick(t_ms):
            self.audits.append(audit_row(crop, self.floor, self.slab, t_ms, self.rotation))
        g = self.glyph.step(crop, self.slab, t_ms)
        veto = veto_for(crop.shape, g, self.scale, self.rotation)
        fits = self_icons(crop, self.floor, require_facing=False, support=self.slab, veto=veto)
        if veto is not None:
            fits = occluded_fits(fits, self_icons(crop, self.floor, require_facing=False,
                                                  support=self.slab, veto=veto, seed="surface"),
                                 self.scale)
        annotate(fits, SIDES["self"], g, self.scale, icons=fits, rotation=self.rotation)
        kept = [f for f in fits if f["refused"] is None]
        p = self.track.step(t_ms, kept)
        surprises = g["surprises"] + p["surprises"]
        self.surprises.extend(surprises)
        chosen = kept[p["index"]] if p["index"] is not None else None
        reason = None
        if chosen is None:
            reason = "on_carried_glyph" if fits else "no_candidate"
        return {"self_x": None if chosen is None else chosen["cx"],
                "self_y": None if chosen is None else chosen["cy"],
                "self_rests_on": p["rests_on"] if chosen is not None or not fits else "refused",
                "self_reason": reason,
                "self_carries_spike": None if chosen is None else chosen["carries_spike"],
                "self_glyph_masked": None if chosen is None else chosen["glyph_masked"],
                "spike_state": g["state"],
                "spike_x": None if g["state"] is None else float(g["cx"]),
                "spike_y": None if g["state"] is None else float(g["cy"]),
                "spike_rests_on": g["rests_on"]}
