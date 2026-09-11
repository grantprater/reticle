"""Capture stalls: where the SOURCE stopped advancing, from stored primitives.

A stall is the recording freezing while time keeps passing -- the encoder emits
frames, every reader reads them, and each one reports a world it is no longer
observing. It is the most confident-looking data in a capture and it is the
least true, so *stale input must stay distinguishable from a real reading*
(`CLAUDE.md`), and that has to reach EVERY channel rather than the one that
happened to notice.

Why this is a recomputed rule and not an event emitter
------------------------------------------------------
**A stall is a property of the SOURCE FRAME, not of any channel**, so it
belongs where frame properties already live. `l1/primitives` stores a
whole-frame `motion` column per frame at 5 Hz for every session, computed once
on the shared decode pass. Nothing needs measuring again: the fact is already
in the store, and the spans below recompute from it in about a second for the
whole corpus.

An emitter was the alternative considered and it is worse for one concrete
reason: an emitted fact exists only during the run that emitted it, so a later
analysis over stored data cannot see it -- and this project's standing rule is
that a rule recomputable from stored data must not decode video. It also
couples readers to each other (who subscribes, in what order, what happens to a
reader that needs the fact before the emitter has produced it), where a joined
span couples nothing.

Consumers JOIN and decide for themselves. The span states the fact; it does not
say what to do about it. A reader records no observation, a tracker ages
without observing, a metric drops the frames from its denominator -- three
different correct responses to one fact.

The signal
----------
`motion == 0.0` exactly, which is two identical 160x90 thumbnails. Measured on
`96aa1ae9b96f`, whose stalls the player identified independently:

    window                       motion median   p90      min
    stall 1 (407-428 s)             0.0000    0.0000       --
    stall 2 post-plant (706-713)    0.0000    0.0923       --
    death window (259-266)          0.0861    0.1059    0.0100
    100 s of ordinary play          0.0836    0.1416    0.0001
    buy menu open (221-227)         0.0288    0.1687    0.0001

Ordinary play never reaches zero; a stall sits there. **This supersedes the
per-frame minimap-crop check and its clock cross-reference** that shipped
earlier the same day: that measured one ROI on the decode path to answer a
question a stored whole-frame column already answers for every channel at once.

`MERGE_GAP_MS` is the one number that is not free. Zero-motion runs arrive in
~3.6 s pieces separated by a single non-zero sample, which is the encoder's
keyframe interval refreshing a frozen picture -- so the pieces are one stall
and must be joined. `MIN_STALL_MS` then drops the isolated single samples that
occur a few times a session in live play.

A caution the corpus makes obvious: short ability-demo clips report 4-17%
stalled, because a static practice-range scene genuinely repeats a thumbnail
and 2 s is a large share of a 40 s clip. Treat a stall inside a clip as
suspect; the figure means what it says on a full match.

Owns [owns:capture-stall].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

STALL_VERSION = "stalls-0.1.0"

#: Runs separated by less than this are one stall -- the keyframe refresh.
MERGE_GAP_MS = 1000.0
#: Shorter than this is not reported: live play produces isolated zero samples.
MIN_STALL_MS = 1000.0


@dataclass(frozen=True)
class StallConfig:
    merge_gap_ms: float = MERGE_GAP_MS
    min_stall_ms: float = MIN_STALL_MS


def spans(t_ms, motion, cfg: StallConfig = StallConfig()) -> list[dict]:
    """Stalled intervals over one session's primitives. Pure, no I/O.

    Returns `{"t_start_ms", "t_end_ms", "samples"}` per span, in time order.
    A span is CLOSED on both ends: the source is stale at both timestamps.
    """
    t = np.asarray(t_ms, dtype=float)
    m = np.asarray(motion, dtype=float)
    if t.size == 0 or t.size != m.size:
        return []
    order = np.argsort(t)
    t, m = t[order], m[order]
    runs: list[list[float]] = []
    for i in np.nonzero(m == 0.0)[0]:
        if runs and t[i] - runs[-1][1] <= cfg.merge_gap_ms:
            runs[-1][1] = t[i]
            runs[-1][2] += 1
        else:
            runs.append([float(t[i]), float(t[i]), 1])
    return [{"t_start_ms": a, "t_end_ms": b, "samples": int(n)}
            for a, b, n in runs if b - a >= cfg.min_stall_ms]


def for_session(store, session_id: str, date: str,
                cfg: StallConfig = StallConfig()) -> list[dict] | None:
    """The session's stall spans, or None when it has no primitives table.

    None is *unknown*, not *no stalls* -- a caller must keep those apart, which
    is the same rule the rest of this project follows about an unread value.
    """
    if not store.has_primitives(session_id, date):
        return None
    table = store.read_primitives(session_id, date)
    return spans(table["t_ms"], table["motion"], cfg)


def stalled_at(span_list, t_ms: float) -> bool:
    """Is the source stale at this timestamp? `span_list` may be None -> False."""
    if not span_list:
        return False
    starts = [s["t_start_ms"] for s in span_list]
    i = int(np.searchsorted(starts, t_ms, side="right")) - 1
    return i >= 0 and t_ms <= span_list[i]["t_end_ms"]


def total_ms(span_list) -> float:
    return float(sum(s["t_end_ms"] - s["t_start_ms"] for s in (span_list or ())))
