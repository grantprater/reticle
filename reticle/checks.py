"""Domain invariants over stored HUD reads (design doc SS3, stage 05).

The design doc calls these a *label-free error detector*: the clock counts down,
scores never fall, and the two scores sum to rounds played. Nobody has to label
a frame for those to be checkable, and a violation localises the extraction
fault in time.

This module computes; it does not print. `reticle verify` renders the result,
and the dashboard reads the same structure, so there is one implementation of
what counts as a fault.
"""

from __future__ import annotations

import numpy as np

# Valorant only ever restarts the round clock at a handful of values. A jump
# that lands on one of these is a phase change; a jump that lands anywhere else
# had a digit misread.
PHASE_STARTS_MS = (
    100_000,  # round timer, 1:40
    45_000,   # spike countdown, and the first buy phase
    30_000,   # buy phase
    7_000,    # inter-round countdown after an early round end
)
PHASE_TOL_MS = 3_000

# 1s clock granularity plus sampling slack.
STEP_TOL_MS = 1_500
# Two reads further apart than this do not constrain each other.
MAX_GAP_MS = 3_000

# ---- killfeed entry tracking --------------------------------------------------
# One killfeed entry stays on screen for several seconds, so a per-frame flag
# counts the same kill many times over. Counting *entries* means following each
# one across frames, which works because an entry never moves down the stack: it
# holds its position until an entry above it expires, then rises.
KF_TRACK_GAP_MS = 2_500     # unseen for longer than this and the entry is gone
KF_MIN_OBS = 2              # a single-frame detection is noise, not an entry

# Scoreboard K/D read off the end-of-match screen, keyed by session. This is the
# only external ground truth in the project -- everything else here is a
# label-free invariant -- so it is the one number that can say whether killfeed
# attribution is actually right rather than merely self-consistent. Recorded by
# Grant on 2026-08-24 for the four captures of 2026-08-23, in play order.
KNOWN_KD = {
    "0f08b3dc3777": (19, 12),   # 16-51-47, cropped capture
    "b3b9defb6fd7": (14, 18),   # 18-24-15
    "bdfdcf009dba": (17, 14),   # 19-25-23
    "223d636bf8d2": (25, 15),   # 20-09-01
}


def _slots(mask) -> list[int]:
    if mask is None:
        return []
    m = int(mask)
    return [s for s in range(6) if m & (1 << s)]


def _count(times, masks) -> int:
    """Follow each entry across frames and count how many distinct ones there were."""
    active: list[list] = []      # [last_t, last_slot, n_obs]
    done: list[list] = []
    for t, mask in zip(times, masks):
        keep = []
        for a in active:
            (keep if t - a[0] <= KF_TRACK_GAP_MS else done).append(a)
        active = keep
        used: set[int] = set()
        for slot in _slots(mask):
            best = bi = None
            for ai, a in enumerate(active):
                if ai in used or slot > a[1]:
                    continue          # an entry never moves down the stack
                d = a[1] - slot
                if best is None or d < best:
                    best, bi = d, ai
            if bi is None:
                active.append([t, slot, 1])
                used.add(len(active) - 1)
            else:
                active[bi] = [t, slot, active[bi][2] + 1]
                used.add(bi)
    done.extend(active)
    return sum(1 for a in done if a[2] >= KF_MIN_OBS)


def player_events(times, kill_masks, death_masks) -> dict:
    """Distinct killfeed entries the local player was in, kills and deaths."""
    return {
        "kills": _count(list(times), list(kill_masks)),
        "deaths": _count(list(times), list(death_masks)),
    }


def check_hud(table) -> dict:
    """Run every invariant over one session's HUD reads.

    `table` is the pyarrow table written by `Store.write_hud`.
    """
    t = np.asarray(table.column("t_ms").to_numpy(zero_copy_only=False), dtype=np.float64)
    clock = table.column("clock_ms").to_pylist()
    sl = table.column("score_left").to_pylist()
    sr = table.column("score_right").to_pylist()
    conf = np.asarray(
        table.column("confidence").to_numpy(zero_copy_only=False), dtype=np.float64
    )
    n = len(t)

    out: dict = {
        "rows": n,
        "t_start_ms": float(t[0]) if n else 0.0,
        "t_end_ms": float(t[-1]) if n else 0.0,
        "read_clock": sum(1 for v in clock if v is not None),
        "read_scores": sum(1 for a, b in zip(sl, sr) if a is not None and b is not None),
    }

    live = conf[conf > 0]
    out["confidence"] = (
        {
            "min": float(live.min()),
            "p05": float(np.percentile(live, 5)),
            "median": float(np.percentile(live, 50)),
        }
        if live.size
        else None
    )

    # Times at which either score changed, used to corroborate a clock reset.
    change_times: list[float] = []
    for values in (sl, sr):
        prev = None
        for i in range(n):
            if values[i] is None:
                continue
            if prev is not None and values[i] != prev:
                change_times.append(t[i])
            prev = values[i]
    changes = np.sort(np.array(change_times)) if change_times else np.zeros(0)

    def near_change(ts: float, window: float = 6000.0) -> bool:
        if changes.size == 0:
            return False
        j = int(np.searchsorted(changes, ts))
        for k in (j - 1, j):
            if 0 <= k < changes.size and abs(changes[k] - ts) <= window:
                return True
        return False

    def is_phase_start(ms: int) -> bool:
        return any(abs(ms - p) <= PHASE_TOL_MS for p in PHASE_STARTS_MS)

    # ---- invariant 1: the clock tracks real time between resets -------------
    steps = drift = resets = 0
    worst: list[dict] = []
    prev_i = None
    for i in range(n):
        if clock[i] is None:
            continue
        if prev_i is not None:
            dt = t[i] - t[prev_i]
            if 0 < dt <= MAX_GAP_MS:
                steps += 1
                err = abs((clock[i] - clock[prev_i]) - (-dt))
                if err > STEP_TOL_MS:
                    if is_phase_start(clock[i]) or near_change(t[i]):
                        resets += 1
                    else:
                        drift += 1
                        worst.append(
                            {
                                "t_ms": float(t[i]),
                                "err_ms": float(err),
                                "from_ms": int(clock[prev_i]),
                                "to_ms": int(clock[i]),
                            }
                        )
        prev_i = i
    worst.sort(key=lambda d: -d["err_ms"])
    out["clock"] = {
        "steps": steps,
        "in_step": steps - drift - resets,
        "resets": resets,
        "drift": drift,
        "worst": worst[:5],
    }

    # ---- invariant 2: scores never fall -------------------------------------
    def drops(values: list) -> list[dict]:
        found: list[dict] = []
        prev = None
        for i in range(n):
            v = values[i]
            if v is None:
                continue
            if prev is not None and v < prev:
                found.append({"t_ms": float(t[i]), "from": int(prev), "to": int(v)})
            prev = v
        return found

    left_drops, right_drops = drops(sl), drops(sr)
    out["score_left_drops"] = left_drops
    out["score_right_drops"] = right_drops

    # ---- invariant 3: the pair advances one round at a time -----------------
    # Monotonicity alone cannot catch a *sustained* misread that happens to stay
    # non-decreasing. The sum can: a round awards exactly one point to exactly
    # one side, so between two reads taken moments apart the sum moves by 0 or 1
    # and never by more. Reads far apart are not constrained -- the scoreline can
    # be unreadable across a whole round -- so only closely-spaced pairs count.
    sum_jumps: list[dict] = []
    prev_pair = None
    for i in range(n):
        if sl[i] is None or sr[i] is None:
            continue
        total = sl[i] + sr[i]
        if prev_pair is not None:
            dt = t[i] - prev_pair[0]
            delta = total - prev_pair[1]
            if dt <= 5000 and delta not in (0, 1):
                sum_jumps.append(
                    {"t_ms": float(t[i]), "from": int(prev_pair[1]), "to": int(total),
                     "gap_ms": float(dt)}
                )
        prev_pair = (t[i], total)
    out["sum_jumps"] = sum_jumps

    # ---- invariant 4: the pair is consistent with a real match --------------
    # The furthest-advanced pair, not the last one read. Scores only ever climb,
    # so the maximum is the final score -- whereas the last populated read can
    # land on a post-match frame where a stray pair got through, which is what
    # happens at full sample rate.
    finals = [(a, b) for a, b in zip(sl, sr) if a is not None and b is not None]
    if finals:
        fa, fb = max(finals, key=lambda p: p[0] + p[1])
        out["final"] = {"left": int(fa), "right": int(fb), "sum": int(fa + fb)}
        out["reached_match_point"] = max(fa, fb) >= 13
    else:
        out["final"] = None
        out["reached_match_point"] = False

    # ---- killfeed: entries the player was in, against the scoreboard --------
    names = set(table.column_names)
    if {"kf_kill_mask", "kf_death_mask"} <= names:
        ev = player_events(
            t,
            table.column("kf_kill_mask").to_pylist(),
            table.column("kf_death_mask").to_pylist(),
        )
        sid = table.column("session_id")[0].as_py() if "session_id" in names else None
        ev["known"] = KNOWN_KD.get(sid)
        out["killfeed"] = ev

    out["violations"] = drift + len(left_drops) + len(right_drops) + len(sum_jumps)
    return out
