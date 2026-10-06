"""Which frame of stream B stands for each frame of stream A, by time.

Owns [owns:frame-join].

The caller declares which of two kinds B is. A grid stream samples at a
declared rate and owes a frame on every grid point: `grid_join` joins to it
and refuses a short join. A sampled stream reads irregularly (a variable-rate
reader gated on a cue): `sampled_state` gives the latest read at or before
each time, with its age and provenance, and never refuses for a missing frame;
a read older than the caller's `max_age_ms` is null with reason `stale`.

Grid streams
------------
Two stored streams that both sample a capture at a nominal rate need not share
its grid. On c817691bcd15 the ingest's `ally_icon` stream and the session's
15 Hz minimap crop cache step alike (66.7 and 83.3 ms) at a different phase: an
exact join on `frame_idx` or `t_ms` found 56.7% of the scored frames, and two
scorers counted the rest as misses. On 9acf02f98283 and d3dcfb182ab1 the grids
coincide and the exact join found every frame. A scorer cannot tell those
cases apart from its own output, so the join reports its rate and refuses
below `MIN_JOIN_RATE` rather than hand back a short denominator.

Each frame of A takes the frame of B nearest in time if it lies within half a
sample at B's declared rate (inclusive), so a phase shift of up to half a
sample joins and a gap in B borrows no neighbour from across it. Ties go to the
earlier B frame. The join is many-to-one: two frames of A may share one frame
of B. The rate is the share of A's frames joined; the caller chooses A, so
frames it knows B cannot hold (outside a cache's spans) stay out of the
denominator by the caller's hand, never by this module's.

A refusal is a `FrameJoin` whose `refused` names the reason and whose `index`
is None; `require()` raises `JoinRefused` for a caller that cannot go on.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FRAME_JOIN_VERSION = "frame-join-0.1.0"

#: The least share of A's frames that must join for a grid join to stand.
MIN_JOIN_RATE = 0.99

#: Float slack on the tolerance: stored times carry three decimals, so a frame
#: exactly half a sample off (a 33.333 ms tie at 15 Hz) must not fall out by
#: rounding.
_SLACK_MS = 1e-3

#: Reasons a sampled stream's state is null at a time.
STALE = "stale"
NO_READ_YET = "no_read_yet"


class JoinRefused(ValueError):
    """A grid join whose rate fell below its floor, or that had nothing to join."""


@dataclass(frozen=True)
class FrameJoin:
    """A grid join of A onto B. `index[i]` is the position in B (as given) of
    A's frame i, or -1 where none lies within `tol_ms`; `offset_ms[i]` is
    `t_b - t_a` there (NaN where unjoined). Both are None on a refusal."""

    rate: float | None
    tol_ms: float
    n_a: int
    n_joined: int
    index: np.ndarray | None
    offset_ms: np.ndarray | None
    refused: str | None = None
    version: str = FRAME_JOIN_VERSION

    @property
    def joined(self) -> np.ndarray | None:
        """Mask over A of the frames that joined."""
        return None if self.index is None else self.index >= 0

    def require(self) -> "FrameJoin":
        """This join, or `JoinRefused` with the reason."""
        if self.refused is not None:
            raise JoinRefused(self.refused)
        return self

    def stamp(self) -> dict:
        """The join's provenance for a caller's output."""
        return {"frame_join_version": self.version, "rate": self.rate,
                "tol_ms": round(self.tol_ms, 3), "n_a": self.n_a,
                "n_joined": self.n_joined, "refused": self.refused}


def grid_join(t_a, t_b, rate_hz: float, min_rate: float = MIN_JOIN_RATE) -> FrameJoin:
    """Join each time of `t_a` to the nearest time of grid stream `t_b`, which
    samples at the declared `rate_hz`, within half a sample. Refuses when A or
    B is empty or the join rate is below `min_rate`."""
    tol_ms = 500.0 / float(rate_hz)
    a = np.asarray(t_a, float).ravel()
    b = np.asarray(t_b, float).ravel()
    if a.size == 0:
        return FrameJoin(None, tol_ms, 0, 0, None, None, "stream A holds no frames")
    if b.size == 0:
        return FrameJoin(0.0, tol_ms, int(a.size), 0, None, None, "stream B holds no frames")
    order = np.argsort(b, kind="stable")
    bs = b[order]
    hi = np.clip(np.searchsorted(bs, a, side="left"), 0, bs.size - 1)
    lo = np.maximum(hi - 1, 0)
    d_lo, d_hi = np.abs(a - bs[lo]), np.abs(bs[hi] - a)
    pick = np.where(d_hi < d_lo, hi, lo)
    ok = np.minimum(d_lo, d_hi) <= tol_ms + _SLACK_MS
    n_joined = int(ok.sum())
    rate = n_joined / a.size
    if rate < min_rate:
        return FrameJoin(round(rate, 6), tol_ms, int(a.size), n_joined, None, None,
                         f"join rate {rate:.4f} below {min_rate} within {tol_ms:.3f} ms: "
                         f"the streams do not sample one grid")
    return FrameJoin(round(rate, 6), tol_ms, int(a.size), n_joined,
                     np.where(ok, order[pick], -1).astype(np.int64),
                     np.where(ok, bs[pick] - a, np.nan))


@dataclass(frozen=True)
class SampledState:
    """A sampled stream's state at each query time. `index[i]` is the read
    (position in the reads as given) that holds at query i, or -1 where the
    state is null; `age_ms[i]` is the query time less that read's time (NaN
    where null); `carried[i]` says the read carried a prediction rather than
    observed; `reason[i]` is None, `stale` or `no_read_yet`."""

    index: np.ndarray
    age_ms: np.ndarray
    carried: np.ndarray
    reason: list
    max_age_ms: float
    version: str = FRAME_JOIN_VERSION

    @property
    def held(self) -> np.ndarray:
        """Mask over the queries whose state is not null."""
        return self.index >= 0


def sampled_state(t_query, t_reads, max_age_ms: float, carried) -> SampledState:
    """The latest read at or before each query time, from a sampled stream.

    `carried` marks the reads that carry a prediction (a skipped teammate's
    predicted position, which declares `rests_on`), or is None where every
    read observed; a caller wanting observations only passes those reads. A
    state older than `max_age_ms` is null with reason `stale`; a query before
    any read is null with reason `no_read_yet`."""
    q = np.asarray(t_query, float).ravel()
    r = np.asarray(t_reads, float).ravel()
    c = np.zeros(r.shape, bool) if carried is None else np.asarray(carried, bool).ravel()
    if r.size == 0:
        n = q.size
        return SampledState(np.full(n, -1, np.int64), np.full(n, np.nan), np.zeros(n, bool),
                            [NO_READ_YET] * n, float(max_age_ms))
    order = np.argsort(r, kind="stable")
    rs = r[order]
    k = np.searchsorted(rs, q, side="right") - 1
    some = k >= 0
    kk = np.where(some, k, 0)
    age = np.where(some, q - rs[kk], np.nan)
    fresh = some & (age <= float(max_age_ms))
    reason = np.where(fresh, None, np.where(some, STALE, NO_READ_YET)).tolist()
    return SampledState(index=np.where(fresh, order[kk], -1).astype(np.int64),
                        age_ms=np.where(fresh, age, np.nan),
                        carried=fresh & c[order][kk], reason=reason,
                        max_age_ms=float(max_age_ms))
