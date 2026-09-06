r"""Decide on a WINDOW, not on the frame that happened to be sampled.

the player, 2026-09-06:

> we're only detecting things that show up on the 2hz schedule, but only things
> that we actually detect. Is there a way to improve accuracy by looking at
> somewhat nearby frames that may be more easily detectable on regions that are
> edge cases?

There is, and this repo has already measured that it works -- once, in one
place, and never generalised. `self_icon_dist` was computed at each track's
BIRTH frame and inherited that frame's failures (58% null on Astra); sampling
the whole track and taking the median took it from 3 of 5 real trapwires to 5
of 5 at an unchanged gate.

**The bias has a direction, which is what makes this more than a refinement.**
A candidate is disproportionately born in a frame where something is covering
the widget -- an ability, a flash, an overlay -- so the single sample is taken
at the moment it is LEAST likely to succeed. That is worse than random
sampling, not equivalent to it. Any per-detection feature measured at one frame
carries the same defect.

Sample cheaply, decide expensively
-----------------------------------
The two are currently the same instant and need not be:

    2 Hz proposes    cheap, whole capture, deliberately permissive
    a window decides read +/- N seconds at NATIVE rate and aggregate

The cost stays inside the design doc's own rule -- if the expensive layer sees
more than ~1% of frames, the gate is wrong -- because proposals are few.

**Sequential, not seeks, and that is the opposite of `plant_spike`.** The rule
is the shape of the demand, not a preference: `plant_spike` wants a handful of
scattered coarse instants, where seeking wins; a window wants every frame in a
short contiguous stretch, where `decode.py`'s warning applies in full and one
forward decode of the window is right. Both live in this repo now and each
cites the other so the choice stays legible.

What a window can answer that a run cannot
--------------------------------------------
The motivating case is the ping detector's 26% precision on match footage,
whose dominant false positive is an ALLY ICON: 13 of 31. The existing gate
looks only INSIDE the object's own run, and a teammate who stands still for
seven seconds is, within that run, indistinguishable from a ping.

Outside the run they are not. **A ping appears from nothing and vanishes to
nothing** -- that is what a 7.0 s lifetime means. A stationary ally was
generally already standing there a second earlier and is still there a second
later. So the question that separates them is not about the run at all, it is
about its EDGES, and answering it costs two short windows either side.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2


@dataclass
class Window:
    """Frames of one contiguous stretch, decoded once, kept as measurements.

    Holds what a `probe` returned per frame rather than the frames themselves;
    a window at native rate over a few seconds is hundreds of frames and the
    reason `PingReader` is one-phase is that holding those does not scale.
    """

    t_ms: list[float]
    value: list


def read_window(path: str, t0_ms: float, t1_ms: float, probe,
                fps: float = 60.0, max_frames: int = 2000) -> Window:
    """Run `probe(frame)` over every frame in [t0, t1]. ONE forward decode.

    Seeks once to the start -- coarse, which is all a window boundary needs --
    then decodes forward. `max_frames` is a guard rather than a parameter to
    tune: a window that wants thousands of frames is not a window, and silently
    reading one would put this back in the cost class it exists to avoid.
    """
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise SystemExit(f"could not open {path}")
    ts: list[float] = []
    vals: list = []
    try:
        cap.set(cv2.CAP_PROP_POS_MSEC, float(max(0.0, t0_ms)))
        n = 0
        while n < max_frames:
            ok, fr = cap.read()
            if not ok:
                break
            t = float(cap.get(cv2.CAP_PROP_POS_MSEC))
            if t > t1_ms:
                break
            ts.append(t)
            vals.append(probe(fr))
            n += 1
    finally:
        cap.release()
    return Window(ts, vals)


def present_fraction(w: Window) -> float | None:
    """How much of the window the probe answered TRUE. None if never read.

    A fraction rather than a vote because the interesting readings are the
    middling ones -- a candidate present in 40% of a window is a different
    object from one present in 5% or 95%, and collapsing that to a boolean at
    this stage throws away the thing the window was decoded for.
    """
    if not w.value:
        return None
    return sum(1 for v in w.value if v) / float(len(w.value))


def edges(path: str, t0_ms: float, t1_ms: float, probe, pad_ms: float,
          fps: float = 60.0, guard_ms: float = 500.0):
    """Presence in the windows BEFORE and AFTER a run. See the module docstring.

    Returns `(before, after)` as fractions, either of which may be None when
    the window falls outside the capture -- which is a refusal, not a zero. A
    run at the very start of a file has no `before`, and reporting 0.0 there
    would assert the object appeared from nothing on no evidence at all.

    **`guard_ms` is not a tuning knob, it is a correctness fix.** The first
    version butted the after-window against `t1` and every real ping scored
    0.32-0.43 there -- looking like an object that persists. The cause is that
    `t1` is the run's MEASURED end, which at a 10 Hz sample lands up to a
    sample period early and, for a truncated run, much earlier than that. The
    window was therefore reading the ping's own tail and reporting it as
    evidence against itself. The guard steps past the boundary before asking
    the question.
    """
    before = read_window(path, t0_ms - guard_ms - pad_ms, t0_ms - guard_ms,
                         probe, fps)
    after = read_window(path, t1_ms + guard_ms, t1_ms + guard_ms + pad_ms,
                        probe, fps)
    return present_fraction(before), present_fraction(after)
