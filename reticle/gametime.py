"""In-game simulation time transformation and capture discontinuity adjudication.

Media time (`t_ms`) is capture provenance -- the container PTS of recorded video.
In-game time is simulation reality -- the round number, match phase, and authoritative
countdown clock (100s -> 0s) governing physics, abilities, and eliminations.

During capture errors (encoder stalls, dropped frames, video freezes):
- Media time either repeats static frames or skips ahead unevenly.
- In-game simulation continues on the dedicated server.
- The duration of the blackout in IN-GAME time defines the physical bounds
  of what could have occurred causally (kinematic reachability, unobserved eliminations).

Post-plant:
The round clock digits are replaced by the spike graphic, so OCR clock readings
are absent (`clock_ms is None`). Freeze identification in post-plant relies on
source pixel motion (`stalls`), anchored at the plant transition timestamp and bounded
by the 45.0s spike detonation fuse.

Owns [owns:in-game-time].
"""

from __future__ import annotations

from dataclasses import dataclass, field
import bisect
from typing import Optional, Sequence
import numpy as np

from . import rounds
from .stalls import StallConfig, spans as stall_spans

GAMETIME_VERSION = "gametime-0.1.0"

# Clock parameters in ms
ROUND_LIVE_CLOCK_MS = 100_000
SPIKE_FUSE_MS = 45_000
CLOCK_SLACK_MS = 1_500.0
MIN_FREEZE_MS = 1_000.0


@dataclass(frozen=True)
class GameTime:
    """In-game simulation coordinate corresponding to a media timestamp."""
    round_no: int                      # 1-indexed round number (0 for pre-match)
    phase: str                         # "buy_phase", "round_live", "post_plant", "round_end", "inter_round"
    round_elapsed_ms: float            # Monotonic ms since round live start (barriers drop)
    clock_ms: Optional[int] = None     # HUD countdown clock (e.g. 100000 -> 0), None in post-plant
    is_stalled: bool = False           # True if inside an identified capture freeze/stall
    t_media_ms: float = 0.0            # Corresponding raw media container timestamp


@dataclass(frozen=True)
class TimeDiscontinuity:
    """An interval where media capture diverged from in-game simulation time."""
    kind: str                          # "stall_freeze", "frame_drop", "clock_jump"
    t_media_start: float               # Media timestamp where discontinuity began
    t_media_end: float                 # Media timestamp where discontinuity ended
    media_duration_ms: float           # Duration in media container time
    game_duration_ms: float            # Duration in authoritative game simulation time
    drift_ms: float                    # game_duration_ms - media_duration_ms
    round_no: Optional[int] = None
    phase: str = "unknown"
    game_clock_start: Optional[int] = None
    game_clock_end: Optional[int] = None


@dataclass
class RoundTimeSchedule:
    """Schedule of game phase boundaries for a single round."""
    round_no: int
    t_start_ms: float                  # Media start of round (buy phase start)
    t_end_ms: float                    # Media end of round (score increment)
    t_live_ms: float                   # Media instant barriers drop (clock -> 100s)
    spike_planted: bool = False
    plant_t_ms: Optional[float] = None # Media instant spike was planted
    post_plant_ms: Optional[float] = None
    won_left: Optional[bool] = None


def get_phase(t_media_ms: float, sched: Optional[RoundTimeSchedule]) -> str:
    """Classify the exact in-game phase for a timestamp within a round schedule."""
    if sched is None:
        return "inter_round"
    if t_media_ms < sched.t_live_ms:
        return "buy_phase"
    if sched.spike_planted and sched.plant_t_ms is not None and t_media_ms >= sched.plant_t_ms:
        if t_media_ms <= sched.t_end_ms:
            return "post_plant"
        return "round_end"
    if t_media_ms <= sched.t_end_ms:
        return "round_live"
    return "round_end"


def _schedule_at(schedules: list[RoundTimeSchedule], t_media_ms: float) -> Optional[RoundTimeSchedule]:
    """Find the round schedule covering a media timestamp, or None."""
    if not schedules:
        return None
    starts = [s.t_start_ms for s in schedules]
    idx = bisect.bisect_right(starts, t_media_ms) - 1
    if 0 <= idx < len(schedules):
        sched = schedules[idx]
        if sched.t_start_ms <= t_media_ms <= sched.t_end_ms + 10_000.0:
            return sched
    return None


class SessionGameTime:
    """Session-wide in-game time mapper and discontinuity index."""

    def __init__(
        self,
        session_id: str,
        schedules: list[RoundTimeSchedule],
        discontinuities: list[TimeDiscontinuity],
        stalls: list[dict],
    ):
        self.session_id = session_id
        self.schedules = sorted(schedules, key=lambda s: s.t_start_ms)
        self.discontinuities = sorted(discontinuities, key=lambda d: d.t_media_start)
        self.stalls = sorted(stalls, key=lambda s: s["t_start_ms"])
        self._round_starts = [s.t_start_ms for s in self.schedules]
        self._stall_starts = [s["t_start_ms"] for s in self.stalls]
        self._disc_starts = [d.t_media_start for d in self.discontinuities]

    def is_stalled_at(self, t_media_ms: float) -> bool:
        """Whether a media timestamp falls inside an identified capture freeze."""
        if not self.stalls:
            return False
        idx = bisect.bisect_right(self._stall_starts, t_media_ms) - 1
        if 0 <= idx < len(self.stalls):
            st = self.stalls[idx]
            if st["t_start_ms"] <= t_media_ms <= st["t_end_ms"]:
                return True
        return False

    def discontinuity_at(self, t_media_ms: float) -> Optional[TimeDiscontinuity]:
        """Return the TimeDiscontinuity covering t_media_ms, if any."""
        if not self.discontinuities:
            return None
        idx = bisect.bisect_right(self._disc_starts, t_media_ms) - 1
        if 0 <= idx < len(self.discontinuities):
            d = self.discontinuities[idx]
            if d.t_media_start <= t_media_ms <= d.t_media_end:
                return d
        return None

    def game_time_at(self, t_media_ms: float, clock_read_ms: Optional[int] = None) -> GameTime:
        """Map a raw media timestamp into authoritative In-Game Time."""
        is_stalled = self.is_stalled_at(t_media_ms)
        sched = _schedule_at(self.schedules, t_media_ms)
        phase = get_phase(t_media_ms, sched)

        if sched is None:
            return GameTime(
                round_no=0,
                phase="inter_round",
                round_elapsed_ms=0.0,
                clock_ms=clock_read_ms,
                is_stalled=is_stalled,
                t_media_ms=t_media_ms,
            )

        if phase == "buy_phase":
            return GameTime(
                round_no=sched.round_no,
                phase="buy_phase",
                round_elapsed_ms=0.0,
                clock_ms=clock_read_ms,
                is_stalled=is_stalled,
                t_media_ms=t_media_ms,
            )

        if phase == "post_plant":
            live_to_plant = max(0.0, sched.plant_t_ms - sched.t_live_ms) if sched.plant_t_ms else 0.0
            post_plant_elapsed = max(0.0, t_media_ms - (sched.plant_t_ms or t_media_ms))
            return GameTime(
                round_no=sched.round_no,
                phase="post_plant",
                round_elapsed_ms=live_to_plant + post_plant_elapsed,
                clock_ms=None,  # strictly None: spike icon replaces digits
                is_stalled=is_stalled,
                t_media_ms=t_media_ms,
            )

        if phase == "round_live":
            round_elapsed = max(0.0, t_media_ms - sched.t_live_ms)
            inferred_clock = clock_read_ms
            if inferred_clock is None:
                inferred_clock = max(0, int(ROUND_LIVE_CLOCK_MS - round_elapsed))
            return GameTime(
                round_no=sched.round_no,
                phase="round_live",
                round_elapsed_ms=round_elapsed,
                clock_ms=inferred_clock,
                is_stalled=is_stalled,
                t_media_ms=t_media_ms,
            )

        # round_end
        round_elapsed = max(0.0, sched.t_end_ms - sched.t_live_ms)
        return GameTime(
            round_no=sched.round_no,
            phase="round_end",
            round_elapsed_ms=round_elapsed,
            clock_ms=clock_read_ms,
            is_stalled=is_stalled,
            t_media_ms=t_media_ms,
        )

    def elapsed_game_duration_ms(self, t_start_media: float, t_end_media: float) -> float:
        """Calculate true elapsed game simulation time between two media points.

        Respects round and phase boundaries:
        - Within live play: authoritative clock delta (c_start - c_end).
        - Within post-plant: elapsed post-plant duration clamped to 45.0s spike fuse.
        - Cross-boundary: sums game duration across each phase segment.
        """
        if t_end_media <= t_start_media:
            return 0.0

        sched_start = _schedule_at(self.schedules, t_start_media)
        sched_end = _schedule_at(self.schedules, t_end_media)

        # Same round
        if (
            sched_start is not None
            and sched_end is not None
            and sched_start.round_no == sched_end.round_no
        ):
            gt_start = self.game_time_at(t_start_media)
            gt_end = self.game_time_at(t_end_media)
            # If both within round_live with valid clocks
            if (
                gt_start.phase == "round_live"
                and gt_end.phase == "round_live"
                and gt_start.clock_ms is not None
                and gt_end.clock_ms is not None
            ):
                cd = gt_start.clock_ms - gt_end.clock_ms
                if cd >= 0:
                    return float(cd)
            return max(0.0, gt_end.round_elapsed_ms - gt_start.round_elapsed_ms)

        # Across rounds, compute raw media delta minus inter-round dead time
        return max(0.0, t_end_media - t_start_media)


def build_session_gametime(
    session_id: str,
    hud_table,
    rounds: list[dict],
    primitives_table=None,
    stall_list: Optional[list[dict]] = None,
) -> SessionGameTime:
    """Build authoritative in-game time mapping and detect discontinuities.

    Pure over stored HUD reads, round boundaries, and optional primitives/stalls.
    Strictly respects round boundaries and phase resets (buy phase, active round, post-plant).
    """
    t_hud = np.asarray(hud_table.column("t_ms").to_numpy(zero_copy_only=False), dtype=float)
    clock_hud = hud_table.column("clock_ms").to_pylist()
    n_hud = len(t_hud)

    # 1. Stalls: from provided list, or primitives table, or empty
    stalls: list[dict] = []
    if stall_list is not None:
        stalls = list(stall_list)
    elif primitives_table is not None:
        t_prim = primitives_table.column("t_ms").to_numpy(zero_copy_only=False)
        motion = primitives_table.column("motion").to_numpy(zero_copy_only=False)
        stalls = stall_spans(t_prim, motion)

    # 2. Build Round Schedules and detect live barrier drop time (clock -> 100s)
    schedules: list[RoundTimeSchedule] = []
    for r in rounds:
        r_no = r["round_no"]
        t_s, t_e = float(r["t_start_ms"]), float(r["t_end_ms"])
        planted = bool(r.get("spike_planted", False))
        plant_t = float(r["plant_t_ms"]) if r.get("plant_t_ms") is not None else None
        post_plant = float(r["post_plant_ms"]) if r.get("post_plant_ms") is not None else None
        won_left = r.get("won_left")

        # Find barrier drop:
        # Priority 1: From live clock read (> 45s, since buy phase is <= 45s): t_live = t_i - (100000 - c)
        # Priority 2: From buy phase clock read (<= 45s): t_live = t_i + c
        t_live = None
        for i in range(n_hud):
            if t_s <= t_hud[i] < t_e:
                c = clock_hud[i]
                if c is not None and c > 45_000:
                    elapsed_since_drop = (ROUND_LIVE_CLOCK_MS - c)
                    t_live = max(t_s, float(t_hud[i] - elapsed_since_drop))
                    break

        if t_live is None:
            for i in range(n_hud):
                if t_s <= t_hud[i] < t_e:
                    c = clock_hud[i]
                    if c is not None and c <= 45_000:
                        t_live = min(t_e, float(t_hud[i] + c))
                        break

        if t_live is None:
            t_live = t_s

        schedules.append(RoundTimeSchedule(
            round_no=r_no,
            t_start_ms=t_s,
            t_end_ms=t_e,
            t_live_ms=t_live,
            spike_planted=planted,
            plant_t_ms=plant_t,
            post_plant_ms=post_plant,
            won_left=won_left,
        ))

    schedules.sort(key=lambda s: s.t_start_ms)

    # 3. Detect Time Discontinuities (Freezes, Frame Drops, Clock Jumps)
    discontinuities: list[TimeDiscontinuity] = []

    # 3a. Discontinuities from source stalls (frozen pixels)
    for st in stalls:
        t0, t1 = float(st["t_start_ms"]), float(st["t_end_ms"])
        media_dur = t1 - t0
        idx0 = int(np.searchsorted(t_hud, t0))
        idx1 = min(n_hud - 1, int(np.searchsorted(t_hud, t1)))

        c0 = clock_hud[idx0] if 0 <= idx0 < n_hud else None
        c1 = clock_hud[idx1] if 0 <= idx1 < n_hud else None

        sched0 = _schedule_at(schedules, t0)
        sched1 = _schedule_at(schedules, t1)
        phase0 = get_phase(t0, sched0)
        phase1 = get_phase(t1, sched1)

        # Calculate true game duration respecting round boundaries and phase resets
        if sched0 is not None and sched1 is not None and sched0.round_no == sched1.round_no:
            r_no = sched0.round_no
            if phase0 == "round_live" and phase1 == "round_live" and c0 is not None and c1 is not None and c0 >= c1:
                game_dur = float(c0 - c1)
            elif phase0 == "post_plant" or phase1 == "post_plant":
                # In post-plant, no clock exists: game time advances with media, clamped by spike fuse
                game_dur = min(float(SPIKE_FUSE_MS), media_dur)
            else:
                game_dur = media_dur
        else:
            # Stall crossed round boundary: game duration is media duration
            r_no = sched0.round_no if sched0 else None
            game_dur = media_dur

        drift = game_dur - media_dur
        discontinuities.append(TimeDiscontinuity(
            kind="stall_freeze",
            t_media_start=t0,
            t_media_end=t1,
            media_duration_ms=media_dur,
            game_duration_ms=game_dur,
            drift_ms=drift,
            round_no=r_no,
            phase=phase0,
            game_clock_start=c0,
            game_clock_end=c1,
        ))

    # 3b. Discontinuities from clock skips / dropped frames
    # STRICT GUARD: Only compare consecutive clock reads within the EXACT SAME round and phase!
    prev_i = None
    for i in range(n_hud):
        c = clock_hud[i]
        if c is None:
            continue
        t_curr = t_hud[i]
        sched_curr = _schedule_at(schedules, t_curr)
        phase_curr = get_phase(t_curr, sched_curr)

        if prev_i is not None:
            t_prev = t_hud[prev_i]
            c_prev = clock_hud[prev_i]
            sched_prev = _schedule_at(schedules, t_prev)
            phase_prev = get_phase(t_prev, sched_prev)

            # ONLY compare if in the same round, same phase, and both in a phase with a countdown clock
            if (
                sched_curr is not None
                and sched_prev is not None
                and sched_curr.round_no == sched_prev.round_no
                and phase_curr == phase_prev
                and phase_curr in ("round_live", "buy_phase")
            ):
                dt = t_curr - t_prev
                if 0 < dt <= 5000.0 and c_prev is not None:
                    # Ignore normal clock resets (e.g. barrier drop reset to 100s, buy reset to 30s)
                    if c_prev >= c:
                        clock_drop = c_prev - c
                        drift = clock_drop - dt
                        if drift > CLOCK_SLACK_MS:
                            # Clock skipped ahead faster than media elapsed -> dropped frames!
                            discontinuities.append(TimeDiscontinuity(
                                kind="frame_drop",
                                t_media_start=float(t_prev),
                                t_media_end=float(t_curr),
                                media_duration_ms=float(dt),
                                game_duration_ms=float(clock_drop),
                                drift_ms=float(drift),
                                round_no=sched_curr.round_no,
                                phase=phase_curr,
                                game_clock_start=c_prev,
                                game_clock_end=c,
                            ))
                        elif dt >= MIN_FREEZE_MS and clock_drop == 0 and c > 0:
                            # Clock stayed completely frozen while media advanced
                            already_covered = any(
                                st["t_start_ms"] <= t_prev and t_curr <= st["t_end_ms"]
                                for st in stalls
                            )
                            if not already_covered:
                                discontinuities.append(TimeDiscontinuity(
                                    kind="clock_jump",
                                    t_media_start=float(t_prev),
                                    t_media_end=float(t_curr),
                                    media_duration_ms=float(dt),
                                    game_duration_ms=0.0,
                                    drift_ms=-float(dt),
                                    round_no=sched_curr.round_no,
                                    phase=phase_curr,
                                    game_clock_start=c_prev,
                                    game_clock_end=c,
                                ))
        prev_i = i

    return SessionGameTime(
        session_id=session_id,
        schedules=schedules,
        discontinuities=discontinuities,
        stalls=stalls,
    )
