"""What the model believes about a position, and on what standing.

A reader refusing a frame is not a hole in the pipeline. The reader is right to
refuse -- an unread value is `null` with a reason -- but the player was still
somewhere, and the model is entitled to say where and how tightly. That belief
belongs here rather than in `minimap`, because forming it means taking
everything relevant into account: the motion law, the rounds, the map's own
geometry, and later the channels listed in
`docs/ADJUDICATION_DESIGN.md`'s *position belief: a full accounting*.

**Evidence arrives as arguments.** This module fetches nothing. A reader module
reaching sideways into rounds, geometry and roster inverts the dependency and
hides which evidence an answer rested on; passing it in keeps both visible.

**A `Fix` is never evidence.** It must not seed a template, feed a detector's
prior, or count toward observed coverage. Observed and believed coverage are
reported separately and never summed.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .minimap import FIT_ERR_PX, GAP_MS, RUN_PX, admit_steps, crosses

#: Bumped from 0.1.0, which lived in `minimap` and consulted the self reads and
#: the step law alone. Voids and reachability change the answer, so a stored
#: belief from the old rule cannot read as current.
BELIEF_VERSION = "belief-0.2.0"

OBSERVED = "observed"
INTERPOLATED = "interpolated"
HELD = "held"
UNRESOLVED = "unresolved"


@dataclass(frozen=True)
class Fix:
    """Where the player is believed to be at one sampled instant.

    `source` separates a read from an inference, which is the distinction
    `docs/ADJUDICATION_DESIGN.md` requires and a bare `(t, x, y)` tuple loses:

        observed      the reader answered here and the step law admitted it
        interpolated  bracketed by two admitted reads close enough in time
        held          carried forward from the last read; nothing closes it yet
        unresolved    no belief -- `x`/`y` are None and `reason` says why

    `radius_px` is a physical bound, not a calibrated confidence: the fit error
    plus how far a running player could have travelled since the evidence,
    bounded by the nearer endpoint when the instant is bracketed. It is an
    UPPER bound and a generous one, because it is a disk: the reachable set is
    smaller wherever the map has walls, and expressing that is still owed.

    `rests_on` names the observation instants the belief was drawn from, so a
    later adjudication can link back to the raw reads rather than re-deriving
    which ones it used. An observed fix rests on itself; an unresolved one on
    nothing.
    """

    t_ms: float
    x: float | None
    y: float | None
    source: str
    radius_px: float | None
    reason: str | None = None
    rests_on: tuple[float, ...] = ()

    @property
    def observed(self) -> bool:
        return self.source == OBSERVED


def absent_instants(rows: list[dict]) -> list[float]:
    """The instants a stored L1 row cannot show the widget was drawn.

    **`minimap-0.6.0` answers this directly.** The reader refuses a frame on
    exactly the widget test and now records the answer, so a row carrying
    `widget_drawn` is authoritative: false means nobody was looking, true means
    the reader looked and refused. Only the first forbids a belief; the second
    is a detection failure and the layer may interpolate across it.

    **Older rows do not carry the column, and its absence is UNKNOWN rather
    than false.** For those this falls back to the ally cross-reference, which
    reads the same widget: an ally icon at that instant proves the widget was
    drawn, whatever the self reader did. That rule is sufficient and not
    necessary -- a drawn widget with no visible teammate still lands here -- so
    it OVER-reports absence and keeps the belief conservative where it cannot
    tell. On `c40d950031bb` it recovered 2016 of 2676 unread instants as
    plainly drawn. The two paths are kept apart deliberately: mixing a measured
    flag with a proxy would make a stale table look like a fresh one.
    """
    out: list[float] = []
    for r in rows:
        if r.get("self_x") is not None:
            continue
        drawn = r.get("widget_drawn")
        if drawn is None:                      # pre-0.6.0 row: use the proxy
            drawn = bool(r.get("n_allies"))
        if not drawn:
            out.append(r["t_ms"])
    return sorted(out)


def round_voids(rounds: list[dict]) -> list[float]:
    """Round starts and ends, as instants no belief may be carried across.

    A round start returns every player to spawn, so a position from the
    previous round says nothing about this one. Passed as `voids` rather than
    read here, because this module models no round semantics.
    """
    out: list[float] = []
    for r in rounds:
        out.extend((float(r["t_start_ms"]), float(r["t_end_ms"])))
    return sorted(out)


def _on(mask: np.ndarray | None, x: float, y: float) -> bool:
    """Is a believed centre somewhere the player could stand."""
    if mask is None:
        return True
    xi, yi = int(round(x)), int(round(y))
    if yi < 0 or xi < 0 or yi >= mask.shape[0] or xi >= mask.shape[1]:
        return False
    return bool(mask[yi, xi])


def resolve(found: list[tuple[float, float, float]], step_ms: float,
            scale: float = 1.0, motion=None, absent_t=None, voids=None,
            reachable: np.ndarray | None = None) -> list[Fix]:
    """One belief per sampled instant, carrying its source and its bound.

    Shares `minimap.admit_steps` with `filter_track`, so the two cannot
    disagree about which observations the motion law admitted. Unlike
    `filter_track` this answers at every instant the caller sampled, because a
    refused frame is a position the model still needs and `unresolved` states
    plainly where none exists.

    `absent_t` names the instants the widget was NOT drawn. Nothing is
    interpolated or held across one, because the player may have died or opened
    the full map there, and inventing a path through the only frames that state
    nobody was looking is the fault `filter_track` was fixed for. `None` means
    the caller cannot tell, and then EVERY unread instant is treated as
    unobservable -- the conservative reading, and why `absent_instants` exists.

    `voids` names instants that destroy the prior outright: round boundaries,
    and later deaths and camera wipes. Crossing one is not a long gap to be
    held through, it is a different situation about which the earlier read says
    nothing.

    `reachable` is a boolean mask in the same pixel frame as the positions. A
    believed centre off it is refused, because the map states outright that
    nobody stands there. Build it with the fit error admitted either side --
    `art_floor(kind, dilate=5)` holds 99.6% of the reader's own accepted
    centres on `c40d950031bb` against 98.6% undilated. Observed reads are never
    gated on it: they are evidence, and evidence is not discarded for
    disagreeing with a mask.
    """
    keep, jumps, _ = admit_steps(found, scale, motion)
    if absent_t is None:
        blind = sorted(p[0] for p in found if p[1] is None or p[2] is None)
    else:
        blind = sorted(float(t) for t in absent_t)
    dead = sorted(float(t) for t in (voids or ()))
    kept_t = [k[0] for k in keep]
    kept_at = {k[0]: k for k in keep}
    jump_after = {kept_t[i] for i in jumps if i < len(kept_t)}
    fit_err = FIT_ERR_PX * scale
    reach = RUN_PX * scale
    unobservable = set(blind)

    out: list[Fix] = []
    for t_ms, _x, _y in found:
        # The instant itself may be the one nobody was looking at, which is a
        # different answer from a gap BETWEEN two such instants.
        if t_ms in unobservable and t_ms not in kept_at:
            out.append(Fix(t_ms, None, None, UNRESOLVED, None, "widget_absent"))
            continue
        hit = kept_at.get(t_ms)
        if hit is not None:
            out.append(Fix(t_ms, hit[1], hit[2], OBSERVED, fit_err,
                           rests_on=(t_ms,)))
            continue
        # A read the step law rejected is not evidence, but the instant still
        # needs a belief; `reason` keeps the rejection visible.
        rejected = _x is not None and _y is not None
        i = int(np.searchsorted(kept_t, t_ms, side="left"))
        before = kept_at[kept_t[i - 1]] if i > 0 else None
        after = kept_at[kept_t[i]] if i < len(kept_t) else None
        reason = "rejected_step" if rejected else None
        voided = False
        if before is not None and crosses(dead, before[0], t_ms):
            before, voided = None, True
        if before is not None and crosses(blind, before[0], t_ms):
            before = None
            reason = "widget_absent"
        if after is not None and (crosses(dead, t_ms, after[0])
                                  or crosses(blind, t_ms, after[0])):
            after = None
        candidate = None
        if (before is not None and after is not None
                and before[0] not in jump_after
                and after[0] - before[0] <= GAP_MS):
            span = after[0] - before[0]
            f = (t_ms - before[0]) / span
            nearer = min(t_ms - before[0], after[0] - t_ms) / 1000.0
            candidate = Fix(t_ms,
                            before[1] + (after[1] - before[1]) * f,
                            before[2] + (after[2] - before[2]) * f,
                            INTERPOLATED, fit_err + reach * nearer, reason,
                            rests_on=(before[0], after[0]))
        elif (before is not None and before[0] not in jump_after
                and t_ms - before[0] <= GAP_MS):
            held = (t_ms - before[0]) / 1000.0
            candidate = Fix(t_ms, before[1], before[2], HELD,
                            fit_err + reach * held, reason,
                            rests_on=(before[0],))
        if candidate is not None:
            if _on(reachable, candidate.x, candidate.y):
                out.append(candidate)
                continue
            # Geometry contradicts the motion model. The straight line between
            # two reads is an assumption; the map's footprint is not.
            reason = "off_floor"
        if reason is None or reason == "rejected_step":
            if voided:
                reason = "void"
            elif before is not None and before[0] in jump_after:
                reason = "teleport"
            elif reason is None:
                reason = "stale"
        out.append(Fix(t_ms, None, None, UNRESOLVED, None, reason))
    return out
