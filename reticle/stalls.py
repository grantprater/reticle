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

The frozen clock (0.2.0)
------------------------
Exact zero motion finds a stall's core, not its edges: the encoder repaints a
frozen picture with noise. At `bfad2778a372` the round clock reads 0:55 from
2328.0 s to past 2346 s while motion sits between 1e-7 and 1e-4, and only
2337.6-2340.6 s reads exactly zero; two of Riot's kills fall in the part
the motion test missed. Rather than guess a motion epsilon, the span is
cross-referenced with a second channel that observes the same fact: the
game clock, which ticks once a second while the game runs. `spans` given the
stored HUD clock extends each zero-motion span over every run of one clock
value lasting longer than `FROZEN_CLOCK_MS` that touches it. The clock
alone never makes a span -- a run of one clock value needs a zero-motion
seed -- so a clock the HUD legitimately holds is not a stall. The frozen
value's first read may still be live: the clock shows each value for one
tick. An extended span therefore starts one tick (`CLOCK_TICK_MS`) after
that read, where the clock is proven stale (a06f04a0059f: 35 s is first read
at 691.5 s, motion is live to 692.2 s, zero from 692.6 s); it carries
`clock = {"t_first_ms", "t_last_ms", "clock_ms"}` naming the run.

Owns [owns:capture-stall].
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# 0.2.0 (2026-10-03): a zero-motion span extends over the frozen game clock
# that touches it (`frozen_clock_runs`); bfad2778a372 2337.6-2340.6 s becomes
# 2329.0-2358.5 s.
STALL_VERSION = "stalls-0.2.0"

#: Runs separated by less than this are one stall -- the keyframe refresh.
MERGE_GAP_MS = 1000.0
#: Shorter than this is not reported: live play produces isolated zero samples.
MIN_STALL_MS = 1000.0
#: One clock value read over longer than this is a frozen clock: the round
#: clock ticks every second, so a running game shows one value for at most
#: 1000 ms, and two ticks' worth leaves room for the 2 Hz sampler.
FROZEN_CLOCK_MS = 2000.0
#: The round clock's tick: a value first read at t was drawn live until at
#: most t + one tick.
CLOCK_TICK_MS = 1000.0


@dataclass(frozen=True)
class StallConfig:
    merge_gap_ms: float = MERGE_GAP_MS
    min_stall_ms: float = MIN_STALL_MS
    frozen_clock_ms: float = FROZEN_CLOCK_MS


def frozen_clock_runs(t_ms, clock_ms, cfg: StallConfig = StallConfig()) -> list[dict]:
    """Runs of one game-clock value read over longer than `frozen_clock_ms`:
    `{"t_first_ms", "t_last_ms", "clock_ms"}`, in time order. Unread reads
    (None) are skipped and break nothing. Pure, no I/O."""
    t = np.asarray(t_ms, dtype=float)
    c = np.array(list(clock_ms), dtype=float)  # None reads as NaN
    if t.size == 0 or t.size != c.size:
        return []
    keep = ~np.isnan(c)
    t, c = t[keep], c[keep]
    if t.size == 0:
        return []
    order = np.argsort(t, kind="stable")
    t, c = t[order], c[order]
    starts = np.flatnonzero(np.r_[True, c[1:] != c[:-1]])
    ends = np.r_[starts[1:], t.size] - 1
    long = (t[ends] - t[starts]) > cfg.frozen_clock_ms
    return [{"t_first_ms": float(t[a]), "t_last_ms": float(t[b]), "clock_ms": int(c[a])}
            for a, b in zip(starts[long], ends[long])]


def spans(t_ms, motion, cfg: StallConfig = StallConfig(), clock=None) -> list[dict]:
    """Stalled intervals over one session's primitives. Pure, no I/O.

    Returns `{"t_start_ms", "t_end_ms", "samples"}` per span, in time order.
    A zero-motion span is CLOSED on both ends: the source is stale at both
    timestamps.

    `clock`, the stored HUD's `(t_ms, clock_ms)` columns, extends each span
    over every frozen clock run (`frozen_clock_runs`) that overlaps it or
    lies within `merge_gap_ms` of it, from one tick after the run's first
    read to its last; such a span carries `clock`, the run.
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
    out = [{"t_start_ms": a, "t_end_ms": b, "samples": int(n)}
           for a, b, n in runs if b - a >= cfg.min_stall_ms]
    if clock is None or not out:
        return out
    frozen = frozen_clock_runs(clock[0], clock[1], cfg)
    for s in out:
        touch = [r for r in frozen if r["t_first_ms"] <= s["t_end_ms"] + cfg.merge_gap_ms
                 and r["t_last_ms"] >= s["t_start_ms"] - cfg.merge_gap_ms]
        if not touch:
            continue
        a = min(min(r["t_first_ms"] + CLOCK_TICK_MS, r["t_last_ms"]) for r in touch)
        b = max(r["t_last_ms"] for r in touch)
        lo, hi = min(a, s["t_start_ms"]), max(b, s["t_end_ms"])
        s.update(t_start_ms=lo, t_end_ms=hi,
                 samples=int(np.count_nonzero((t >= lo) & (t <= hi))),
                 clock=[dict(r) for r in touch])
    # Two seeds one frozen run covers become one span.
    merged: list[dict] = []
    for s in out:
        if merged and s["t_start_ms"] <= merged[-1]["t_end_ms"]:
            p = merged[-1]
            p["t_end_ms"] = max(p["t_end_ms"], s["t_end_ms"])
            p["samples"] = int(np.count_nonzero((t >= p["t_start_ms"]) & (t <= p["t_end_ms"])))
            if s.get("clock"):
                p["clock"] = p.get("clock", []) + [r for r in s["clock"]
                                                   if r not in p.get("clock", [])]
        else:
            merged.append(s)
    return merged


def for_session(store, session_id: str, date: str,
                cfg: StallConfig = StallConfig()) -> list[dict] | None:
    """The session's stall spans, or None when it has no primitives table.

    None is *unknown*, not *no stalls* -- a caller must keep those apart, which
    is the same rule the rest of this project follows about an unread value.
    The stored HUD's clock, where the session has one, extends each span
    (`spans`); without it the spans are the zero-motion runs alone.
    """
    if not store.has_primitives(session_id, date):
        return None
    table = store.read_primitives(session_id, date)
    clock = None
    if store.has_hud(session_id, date):
        hud = store.read_hud(session_id, date)
        if "clock_ms" in hud.column_names:
            clock = (hud.column("t_ms").to_pylist(), hud.column("clock_ms").to_pylist())
    return spans(table["t_ms"], table["motion"], cfg, clock=clock)


def stalled_at(span_list, t_ms: float) -> bool:
    """Is the source stale at this timestamp? `span_list` may be None -> False."""
    if not span_list:
        return False
    starts = [s["t_start_ms"] for s in span_list]
    i = int(np.searchsorted(starts, t_ms, side="right")) - 1
    return i >= 0 and t_ms <= span_list[i]["t_end_ms"]


def total_ms(span_list) -> float:
    return float(sum(s["t_end_ms"] - s["t_start_ms"] for s in (span_list or ())))
