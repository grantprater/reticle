r"""The ally pass's per-frame opportunity gate [owns:ally-read-gate].

`minimap.AllyIconReader` declares a `"frame"` gate (`ratchets.Gate`); this
module holds the runtime gate the hook in `passes` asks before each frame
of the reader's 15 Hz grid is decoded or fetched from the crop cache. It
decides when the ally pass reads, never what a read means.

The rule (ally-gate-0.3.0; 0.1.0 was fixed before its evaluation)
-----------------------------------------------------------------
The gate reads the slot belief the gated reads themselves built
(`slot_state.GateBelief`: the reach law, the open teammate count from the
round table and the death owner's verdicts) and two cues from other
channels' stored rows. At each instant of the grid, in order:

1. `no_open_teammate` refuses: every teammate slot is closed.
2. `unanchored` opens: no read yet in this round, or since a gap in the
   offered frames longer than `RESET_GAP_MS` (the pose prior's gap,
   `teardrop.PRIOR_GAP_MS`), where the belief restarts.
3. A cue opens a read every `CUE_PERIOD_MS` (200 ms) while it holds:
   `cue:death`, a death verdict of either side within the last
   `CUE_HOLD_MS`; `cue:enemy_near`, a stored enemy icon (`minimap_object`)
   within `LOCAL_M` of a teammate icon of the last read, within the last
   `CUE_HOLD_MS`. Both cues are causal: they look back, never ahead.
4. `reach_exceeds_tolerance` opens when the belief's radius exceeds
   `TOL_M` (an unfixed slot's radius is infinite) and the last read lies at
   least the time the reach takes to grow from `r_fit` to `TOL_M` back;
   otherwise `retry_wait`, `cue_wait` or `within_tolerance` refuses.

0.2.0 keeps the pose prior alive across the gate's gaps, in its owner:
the cue period falls from 200 ms to 133 ms, below `teardrop.PRIOR_GAP_MS`
on the real 66.7/83.3 ms grid (at 200 ms the grid put cue reads 216-250 ms
apart, past the prior's reach), and the gate hands the reader its reach
speed (`reach_px_per_s`, `v_max / m_per_px`), with which
`teardrop.IconPoseReader` continues a teammate's prior up to
`teardrop.PRIOR_GAP_MAX_MS` over a window widened by the reach law instead
of a full search. On the 0.1.0 reread of cadaadeb2d8b 77% of pose searches
ran the full grid (21% at 15 Hz), at 166 ms per read frame.

0.3.0 returns the cue period to 200 ms and keeps the reach-widened prior:
the 0.2.0 reread searched the full grid on 45% of pose reads, at 149 ms per
read frame, but the shorter period added 528 reads and 406 s of CPU against
0.1.0's 370 s. With the prior continued to `teardrop.PRIOR_GAP_MAX_MS`, the
216-250 ms cue gaps no longer lose it.

The declared audit cadence (`AUDIT`, applied by the hook) reads every grid
frame in a 2 s window each 120 s of each span, stored apart.

No replay input, ever: the replay layer is evaluation truth only. Reach is
the Euclidean disc; walk reach waits for a walk graph baked into the
geometry (BACKLOG item 3), so the gate opens early where walls would have
held a teammate, never late.
"""
from __future__ import annotations

import numpy as np

from .ratchets import Audit
from .teardrop import PRIOR_GAP_MS

#: ally-gate-0.1.0 (2026-10-09): the first frame gate (gate-hook-20261009).
#: 0.2.0: the cue period under the pose prior's gap, and the reach speed
#: handed to the pose prior (`POSE_REACH`). 0.3.0: the cue period back at
#: 200 ms; the pose prior's reach carries the gaps.
ALLY_GATE_VERSION = "ally-gate-0.3.0"
#: The question's tolerance in metres: a teammate's region wider than this
#: is worth a read.
TOL_M = 15.0
#: Inside a cue, one read per this many milliseconds: three steps of the
#: 15 Hz grid; the reach-widened prior (`POSE_REACH`) spans the gap.
CUE_PERIOD_MS = 200.0
#: Hand the reader the reach speed, so its pose prior survives the gaps.
POSE_REACH = True
#: A cue holds this long after its last instant.
CUE_HOLD_MS = 1000.0
#: An enemy icon this near a teammate icon of the last read is a cue.
LOCAL_M = 20.0
#: A gap in the offered frames longer than this restarts the belief.
RESET_GAP_MS = PRIOR_GAP_MS
#: The audit cadence, fixed in advance: 2 s of each 120 s of a span, from
#: 30 s after its start.
AUDIT = Audit(every_ms=120_000.0, window_ms=2_000.0, phase_ms=30_000.0)
#: A millisecond's slack on the grid's spacing comparisons.
_EPS_MS = 1.0


class AllyGate:
    """The runtime gate: `wants(t_ms)` -> `(read, reason, rests_on)`, which
    the hook makes a `passes.GateDecision`; `observed(t_ms, fits_px)` feeds a
    read the gate opened back into the belief.

    `sources` maps each prior the gate may read to its name and stamp:
    `belief` (the `slot_state.GateBelief`, whose lifecycle reads the death
    verdicts), `death` (the death verdicts' times, a cue) and `enemy` (the
    stored enemy icons, a cue). Each answer's `rests_on` names the keys it
    read, so every read and refusal carries its own priors; `rests_on` (the
    instance's) lists them all as `key: name`.

    `belief` is a `slot_state.GateBelief` (built by the CLI, which may read
    the adjudication layer this module may not import); `deaths_t` the death
    verdicts' times; `enemy` `(t_ms, x, y)` arrays of stored enemy icons in
    widget pixels, sorted by time, or None where no stream is stored."""

    def __init__(self, belief, deaths_t=(), enemy=None, sources: dict | None = None):
        self.belief = belief
        self.deaths_t = np.sort(np.asarray(list(deaths_t), float))
        self.has_enemy = enemy is not None
        if enemy is None:
            enemy = (np.zeros(0), np.zeros(0), np.zeros(0))
        self.et, self.ex, self.ey = (np.asarray(a, float) for a in enemy)
        self.sources = dict(sources or {"belief": "GateBelief (unstamped)"})
        self.rests_on = tuple(f"{k}: {v}" for k, v in self.sources.items())
        self.version = ALLY_GATE_VERSION
        self.retry_ms = belief.age_for(TOL_M) * 1000.0
        #: The reach law in widget pixels per second, for the pose prior.
        self.reach_px_per_s = (belief.v_max / belief.m_per_px) if POSE_REACH else None
        self.local_px = LOCAL_M / belief.m_per_px
        self._t_prev = None
        self._cued = ("belief", "death") + (("enemy",) if self.has_enemy else ())

    def _cue(self, t: float, fix_px: np.ndarray) -> str | None:
        lo = t - CUE_HOLD_MS
        a, b = np.searchsorted(self.deaths_t, [lo, t], side="right")
        if b > a:
            return "cue:death"
        if len(fix_px) and self.et.size:
            i, j = np.searchsorted(self.et, [lo, t], side="right")
            if j > i:
                d = np.hypot(self.ex[i:j, None] - fix_px[None, :, 0],
                             self.ey[i:j, None] - fix_px[None, :, 1])
                if (d <= self.local_px).any():
                    return "cue:enemy_near"
        return None

    def wants(self, t_ms: float) -> tuple[bool, str, tuple]:
        t = float(t_ms)
        if self._t_prev is not None and t - self._t_prev > RESET_GAP_MS:
            self.belief.reset()
        self._t_prev = t
        b = self.belief.at(t)
        if b["n_open"] <= 0:
            return (False, "no_open_teammate", ("belief",))
        if b["t_read"] is None:
            return (True, "unanchored", ("belief",))
        since = t - b["t_read"]
        cue = self._cue(t, b["fix_px"])
        on = self._cued
        if cue is not None and since >= CUE_PERIOD_MS - _EPS_MS:
            return (True, cue, on)
        if b["radius_m"] > TOL_M:
            if since >= self.retry_ms - _EPS_MS:
                return (True, "reach_exceeds_tolerance", on)
            return (False, "cue_wait" if cue else "retry_wait", on)
        return (False, "cue_wait" if cue else "within_tolerance", on)

    def observed(self, t_ms: float, fits_px) -> None:
        self.belief.observe(t_ms, fits_px)

    def params(self) -> dict:
        return {"tol_m": TOL_M, "cue_period_ms": CUE_PERIOD_MS, "cue_hold_ms": CUE_HOLD_MS,
                "local_m": LOCAL_M, "reset_gap_ms": RESET_GAP_MS,
                "retry_ms": round(self.retry_ms, 1), "audit": AUDIT.stamp(),
                "pose_reach_px_per_s": (None if self.reach_px_per_s is None
                                        else round(self.reach_px_per_s, 3))}


def teammate_fits(icons) -> list[tuple[float, float]]:
    """The teammate icons a read found, as the gate counts them: ring fits
    whose interior is not the map (`interior_is_map` is a barrier) and no
    stacked-icon member (the reader publishes those through adjudication
    only)."""
    return [(float(d["cx"]), float(d["cy"])) for d in icons
            if d.get("reason") != "interior_is_map" and d.get("origin") != "stack_fit"]
