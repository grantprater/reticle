"""When the yellow self icon stops being the player: his death, and the spectate switch.

Owns [owns:player-dead].

While the player is dead and spectating, the minimap draws the spectated
teammate as the yellow self icon [domain:minimap/spectated-self-icon]; the
switch waits for spectating to begin, after a death-camera period
[domain:minimap/death-camera-period]. So a self track read after his death
follows a teammate, or whatever the reader latched onto, and a consumer that
takes it for the player draws him walking a teammate's route.

**Guard 6** (docs/PRIOR_DRIVEN_READERS.md, section 2): the self track ends at
the player's death and resumes at the next round's start. The death is the
death owner's (`adjudication.death`): a stored `death_verdict` the killfeed
marks as the player's (`kf_player_death`), less a second life
(`is_second_life`) and a revive entry (`is_revive`)
[domain:rounds/resurrection-mechanics]. A later revive verdict naming the same
victim ends the interval early. This module restates none of that owner's
rules; it turns its verdicts into intervals.

**The spectate switch, a fallback witness.** Where the death owner stores no
death of the player in a round, the yellow icon jumping onto a teammate's
place and moving with that teammate says spectating began
(`switch_after`). The interval then starts at the switch, never earlier: the
death itself was not observed, and the death-camera period is a measured
distribution, not a constant to subtract. It is the one self-only rule here.
The switch alone is not taken: a fall in the roster's alive count must come
first (`ROSTER_DROP_MS`). Without that cross-reference the rule fired in 1, 4
and 7 rounds with no stored death on a06f04a0059f, 5822b6646448 and
223d636bf8d2, mostly a self track leaving a misfit beside a teammate; with it,
in 0, 2 and 1, and each one viewed is a death the killfeed missed
(prototypes/spectate_switch.py). The fallback anchors a jump only on a point
within `ANCHOR_GAP_MS`, so it misses a switch that follows a hole in the
yellow icon; the killfeed case anchors on his last point before the death.

**What a consumer does with an interval.** It removes the self points inside
it from the player's track (they are not his) and stores the yellow icon
after the switch as a spectated teammate's observation, with `rests_on` this
inference and no name: which teammate it is, identity decides. Before the
switch the yellow icon is the death camera's view of the player's own place,
which is not a live position either.

Pure over what the caller passes: death rows, round bounds, the stored self
track and the stored teammate fits. `stored_intervals` reads them from a
store for the consumers.
"""
from __future__ import annotations

import bisect
from dataclasses import dataclass

import numpy as np

#: 0.1.0 (2026-09-29): killfeed deaths through the death owner, and the
#: spectate switch where it stores none.
SPECTATE_VERSION = "spectate-0.1.0"

#: A jump this far (scale-1.0 px) from the previous self point is no run: a
#: player covers `minimap.RUN_PX` in a second. The switches measured jump
#: 31-275 px (prototypes/spectate_switch.py).
JUMP_PX = 30.0
#: The yellow icon sits on a teammate's fit within this (scale-1.0 px): about
#: one icon radius. Measured switches sat 0-12 px from a teammate fit.
TEAMMATE_PX = 12.0
#: A teammate fit pairs with a self point from this many ms before it to
#: `PAIR_MS` after: the yellow icon draws over the spectated teammate's own
#: icon, so the ally reader sees that teammate before the switch and seldom
#: under it.
LAND_MS = 1000.0
PAIR_MS = 200.0
#: After a switch the yellow icon must stay away from the place it left for
#: this long, on this share of its points: a self fit that lands on a
#: teammate for a frame and returns is a misfit, not a spectated view.
HOLD_MS = 1000.0
HOLD_FRAC = 0.8
#: A self point older than this cannot anchor a jump (`minimap.GAP_MS`).
ANCHOR_GAP_MS = 1000.0
#: The fallback takes a switch only where the roster's alive count of the
#: player's side fell within this many ms before it: his death removes him
#: from the bar. The death-camera periods measured reach about 9 s
#: [domain:minimap/death-camera-period].
ROSTER_DROP_MS = 10000.0


@dataclass(frozen=True)
class DeadInterval:
    """The player is not the yellow icon in `[t0_ms, t1_ms)`.

    `rests_on` is `killfeed_death` (the death owner's verdict) or
    `spectate_switch` (the fallback). `switch_ms` is where the yellow icon
    became a spectated teammate, None where no switch was found; before it
    the icon is the death camera's. `t1_why` says what ends the interval.
    """

    round_no: int | None
    t0_ms: float
    t1_ms: float
    rests_on: str
    death_id: str | None
    switch_ms: float | None
    t1_why: str

    def holds(self, t_ms: float) -> bool:
        return self.t0_ms <= t_ms < self.t1_ms

    def spectated(self, t_ms: float) -> bool:
        """The yellow icon shows a spectated teammate at `t_ms`."""
        return self.switch_ms is not None and self.switch_ms <= t_ms < self.t1_ms

    def row(self) -> dict:
        return {"round_no": self.round_no, "t0_ms": self.t0_ms, "t1_ms": self.t1_ms,
                "rests_on": self.rests_on, "death_id": self.death_id,
                "switch_ms": self.switch_ms, "t1_why": self.t1_why,
                "spectate_version": SPECTATE_VERSION}


class Teammates:
    """Stored teammate fits by time, for the switch test."""

    def __init__(self, fits):
        by: dict[float, list] = {}
        for t, x, y in fits:
            by.setdefault(float(t), []).append((float(x), float(y)))
        self.t = sorted(by)
        self.xy = [np.asarray(by[t], float) for t in self.t]

    def nearest(self, t_ms: float, x: float, y: float) -> float | None:
        """Distance from (x, y) to the nearest teammate fit from `LAND_MS`
        before `t_ms` to `PAIR_MS` after it."""
        a = bisect.bisect_left(self.t, t_ms - LAND_MS)
        b = bisect.bisect_right(self.t, t_ms + PAIR_MS)
        best = None
        for k in range(a, b):
            d = float(np.min(np.hypot(self.xy[k][:, 0] - x, self.xy[k][:, 1] - y)))
            best = d if best is None or d < best else best
        return best


def switch_after(t_from: float, t_to: float, selves, teammates: Teammates,
                 scale: float = 1.0) -> dict | None:
    """The first instant in `(t_from, t_to)` the yellow icon jumps onto a
    teammate's place and stays away from the place it left, or None.

    `selves` are the stored self points `(t_ms, x, y)` in time order, None
    positions allowed. A point is a switch when it lies more than `JUMP_PX`
    from the previous point (within `ANCHOR_GAP_MS`, or the last point at or
    before `t_from` however old), within `TEAMMATE_PX` of a teammate fit
    (`Teammates.nearest`), and the points of the next `HOLD_MS` lie more than
    `JUMP_PX` from that previous point on at least `HOLD_FRAC` of them.
    Returns `t_ms`, `x`, `y`, `jump_px`, `teammate_px` (scale-1.0 px) and
    `hold` (the share)."""
    pts = [(float(t), float(x), float(y)) for t, x, y in selves
           if x is not None and y is not None]
    T = [p[0] for p in pts]
    k0 = bisect.bisect_right(T, t_from)
    prev = pts[k0 - 1] if k0 > 0 else None
    jump, near = JUMP_PX * scale, TEAMMATE_PX * scale
    for k in range(k0, len(pts)):
        t, x, y = pts[k]
        if t >= t_to:
            break
        anchor = prev
        prev = pts[k]
        if anchor is None:
            continue
        if k > k0 and t - anchor[0] > ANCHOR_GAP_MS:
            continue
        j = float(np.hypot(x - anchor[1], y - anchor[2]))
        if j <= jump:
            continue
        d = teammates.nearest(t, x, y)
        if d is None or d > near:
            continue
        win = [p for p in pts[k:] if p[0] < min(t + HOLD_MS, t_to)]
        share = sum(np.hypot(p[1] - anchor[1], p[2] - anchor[2]) > jump for p in win) / len(win)
        if share >= HOLD_FRAC:
            return {"t_ms": t, "x": x, "y": y, "jump_px": round(j / scale, 1),
                    "teammate_px": round(d / scale, 1), "hold": round(share, 3)}
    return None


def player_deaths(deaths) -> list[dict]:
    """The death owner's verdicts that the killfeed marks as the player's,
    less second lives and revive entries, in time order."""
    out = [d for d in deaths or () if d.get("kind") == "death_verdict"
           and d.get("kf_player_death") and not d.get("is_second_life")
           and not d.get("is_revive")]
    return sorted(out, key=lambda d: float(d["t_ms"]))


def roster_drops(roster) -> list[float]:
    """The instants the stored alive count of the player's side fell:
    `roster` is `(t_ms list, alive_ally list)`, None reads skipped."""
    if not roster:
        return []
    out, last = [], None
    for t, a in zip(*roster):
        if a is None:
            continue
        if last is not None and a < last:
            out.append(float(t))
        last = a
    return out


def player_dead_intervals(deaths, rounds, selves=None, teammates: Teammates | None = None,
                          scale: float = 1.0, roster=None) -> list[DeadInterval]:
    """Where the yellow icon is not the player, round by round.

    `deaths` are `events/death` rows, `rounds` the rounds table's rows
    (`round_no`, `t_start_ms`, `t_end_ms`). An interval runs from the
    player's killfeed death to the next round's start (the capture's end
    after the last round), or to a later revive verdict naming the same
    victim. With `selves` and `teammates`, each interval records the switch;
    with `roster` too (`(t_ms, alive_ally)`, owner `alive-count`), a round
    with no death of his gains one from a switch that follows a fall in his
    side's alive count within `ROSTER_DROP_MS`. The switch alone is not
    enough: a self track that leaves a misfit for the player's own icon
    beside a teammate jumps as far."""
    rs = sorted(rounds or (), key=lambda r: float(r["t_start_ms"]))
    starts = [float(r["t_start_ms"]) for r in rs]
    revives = [d for d in deaths or () if d.get("kind") == "death_verdict" and d.get("is_revive")]
    can_switch = selves is not None and teammates is not None

    def round_of(t):
        k = bisect.bisect_right(starts, t) - 1
        return rs[k] if k >= 0 else None

    def next_start(t):
        k = bisect.bisect_right(starts, t)
        return (starts[k], "next_round_start") if k < len(starts) else (float("inf"), "capture_end")

    out: list[DeadInterval] = []
    done_rounds = set()
    for d in player_deaths(deaths):
        t0 = float(d["t_ms"])
        rd = round_of(t0)
        t1, why = next_start(t0)
        for rv in revives:
            tr = float(rv["t_ms"])
            if t0 < tr < t1 and rv.get("victim") and rv.get("victim") == d.get("victim"):
                t1, why = tr, "revive_verdict"
        sw = switch_after(t0, t1, selves, teammates, scale) if can_switch else None
        out.append(DeadInterval(None if rd is None else rd["round_no"], t0, t1,
                                "killfeed_death", d.get("death_id"),
                                None if sw is None else sw["t_ms"], why))
        if rd is not None:
            done_rounds.add(rd["round_no"])
    drops = roster_drops(roster)
    if can_switch and drops:
        for i, rd in enumerate(rs):
            if rd["round_no"] in done_rounds:
                continue
            t_a = float(rd["t_start_ms"])
            t_b = starts[i + 1] if i + 1 < len(rs) else float("inf")
            sw, t_from = None, t_a
            while True:
                sw = switch_after(t_from, t_b, selves, teammates, scale)
                if sw is None:
                    break
                k = bisect.bisect_right(drops, sw["t_ms"])
                if k > 0 and sw["t_ms"] - drops[k - 1] <= ROSTER_DROP_MS \
                        and drops[k - 1] >= t_a:
                    break
                t_from = sw["t_ms"]
            if sw is not None:
                out.append(DeadInterval(rd["round_no"], sw["t_ms"], t_b, "spectate_switch",
                                        None, sw["t_ms"],
                                        "next_round_start" if i + 1 < len(rs) else "capture_end"))
    return sorted(out, key=lambda iv: iv.t0_ms)


class DeadIndex:
    """`player_dead_intervals` asked by instant."""

    def __init__(self, intervals: list[DeadInterval]):
        self.iv = sorted(intervals, key=lambda iv: iv.t0_ms)
        self.t0 = [iv.t0_ms for iv in self.iv]

    def at(self, t_ms: float) -> DeadInterval | None:
        k = bisect.bisect_right(self.t0, t_ms) - 1
        if k >= 0 and self.iv[k].holds(t_ms):
            return self.iv[k]
        return None


def stored_teammates(store, session_id: str) -> Teammates:
    """The accepted teammate fits of the stored `ally_icon` rows."""
    fits = [(r["t_ms"], r["cx"], r["cy"]) for r in store.read_events("ally_icon", session_id)
            if r.get("kind") == "icon" and r.get("family", "ally") == "ally"
            and not r.get("reason")]
    return Teammates(fits)


def stored_roster(store, session_id: str, date: str):
    """`(t_ms, alive_ally)` from the stored roster table, or None."""
    try:
        tb = store.read_roster(session_id, date)
    except SystemExit:
        return None
    return tb.column("t_ms").to_pylist(), tb.column("alive_ally").to_pylist()


def stored_intervals(store, session_id: str, date: str, scale: float,
                     selves=None) -> tuple[list[DeadInterval], dict]:
    """`player_dead_intervals` from a store: its death rows, rounds, the
    roster, the `l1/minimap` self track (unless `selves` is passed) and the
    `ally_icon` teammate fits. Returns the intervals and the inputs' stamps."""
    deaths = store.read_events("death", session_id)
    try:
        rounds = store.read_rounds(session_id, date).to_pylist()
    except Exception:
        rounds = []
    roster = stored_roster(store, session_id, date)
    stamps = {"spectate": SPECTATE_VERSION,
              "death": next((r.get("death_adjudication_version") for r in deaths), None)}
    if selves is None:
        tb = store.read_minimap(session_id, date)
        stamps["minimap"] = (tb.schema.metadata or {}).get(b"minimap_version", b"").decode()
        selves = sorted(zip(tb.column("t_ms").to_pylist(), tb.column("self_x").to_pylist(),
                            tb.column("self_y").to_pylist()))
    mates = stored_teammates(store, session_id)
    return player_dead_intervals(deaths, rounds, selves, mates, scale, roster), stamps
