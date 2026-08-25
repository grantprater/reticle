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

from .killfeed import wx_at

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
# How far an entry's divider column may move before it is a *different* entry.
# An entry's divider does not move at all while it is on screen -- the feed is
# right-aligned, so the victim's name width fixes the column -- and measured
# across sessions it wanders by at most 3 px. Two different entries sharing a
# slot are tens of pixels apart. 6 px sits well clear of both.
KF_SIG_TOL = 6

# Scoreboard K/D read off the end-of-match screen, keyed by session. This is the
# only external ground truth in the project -- everything else here is a
# label-free invariant -- so it is the one number that can say whether killfeed
# attribution is actually right rather than merely self-consistent. Recorded by
# Grant on 2026-08-24 for the four captures of 2026-08-23, in play order.
KNOWN_KD = {
    # 2026-08-23, in play order.
    "0f08b3dc3777": (19, 12),   # 16-51-47, cropped capture
    "b3b9defb6fd7": (14, 18),   # 18-24-15
    "bdfdcf009dba": (17, 14),   # 19-25-23
    "223d636bf8d2": (25, 15),   # 20-09-01
    # 2026-08-24, new maps. Recorded with the shooting-error readout switched
    # off, so their killfeed ROI is clear of overlays.
    "9acf02f98283": (13, 16),   # 11-55-34
    "b7d24102a6f6": (10, 12),   # 12-37-04
    "75a55a296d3b": (5, 5),     # 13-34-38, a short match
    "59c70f1ef720": (15, 16),   # 13-58-11
    # 19/15 confirmed by Grant off the end screen. The killfeed reads 20 kills
    # and all 20 are read correctly; the extra one is a kill on an *enemy
    # Phoenix inside Run It Back*, which the scoreboard does not credit. Same
    # rule as ff636d173b07's uncounted deaths, seen from the other side.
    #
    #   `board` agrees at all ~50 openings, ending 18/14 at 39:27, and the
    #   killfeed also holds exactly 18 by then. Two more follow before the match
    #   ends -- both "Me (Vandal) BiGDonut101", eight seconds apart, with the
    #   victim taking a kill in between because Run It Back returned him. The
    #   first carries the Phoenix ult mark.
    "bfad2778a372": (19, 15),   # 14-45-35
    # A low-event match: with only two real kills, a single false positive shows
    # up as a 50% error, so this is the sharpest precision test in the set.
    "c40d950031bb": (2, 7),     # 18-27-17
    # Grant played Phoenix here. A death inside Run It Back is *not* counted on
    # the scoreboard (nor is Kayo's), while a Sage or Clove revive death is --
    # so the two behave oppositely, and only the Phoenix/Kayo case can leave a
    # killfeed entry with no scoreboard death behind it.
    #
    # At hud-0.8.1 this is fully accounted for. The killfeed holds 24 deaths,
    # all read correctly, and exactly four carry the Phoenix ult mark -- 13:21,
    # 20:00, 29:13 and 38:20. 24 - 4 = 20, the recorded figure. Checked by
    # rendering every tracked death entry into one contact sheet and counting
    # the marks; see the note in CLAUDE.md.
    "ff636d173b07": (27, 20),   # 18-47-51
}


def _slots(mask) -> list[int]:
    if mask is None:
        return []
    m = int(mask)
    return [s for s in range(6) if m & (1 << s)]


def track_entries(times, masks, dividers=None) -> list[dict]:
    """Follow each entry across frames; one dict per distinct entry.

    Returns every track, including the short ones below KF_MIN_OBS, with
    `counted` saying whether it met the bar. Callers that only want the number
    use `player_events`; a review needs the timestamps as well, and both must
    come from the same walk or they can disagree.

    `dividers` is the parallel column of packed divider positions written by
    `killfeed.divider_of_ys`. Given it, a detection is only allowed to extend a
    track whose divider sits within KF_SIG_TOL of it, which is what separates
    two entries occupying the same slot in turn from one entry that stayed put.
    Pass None and the walk falls back to slot and time alone, which is what
    every stored session before hud-0.8.0 has.
    """
    active: list[dict] = []
    done: list[dict] = []
    if dividers is None:
        dividers = [None] * len(list(times))
    for t, mask, packed in zip(times, masks, dividers):
        keep = []
        for a in active:
            (keep if t - a["t_last"] <= KF_TRACK_GAP_MS else done).append(a)
        active = keep
        used: set[int] = set()
        for slot in _slots(mask):
            sig = wx_at(packed, slot)
            best = bi = None
            for ai, a in enumerate(active):
                if ai in used or slot > a["slot"]:
                    continue          # an entry never moves down the stack
                # The divider settles it when both sides recorded one. An
                # entry's divider column is fixed for its whole life on screen,
                # so a detection whose divider has moved is a *different entry*
                # however plausible its slot -- which is the one thing slot and
                # time could never say. This is what splits the two kills at
                # 223d636bf8d2 32:06, dividers 30 px apart, that were held as a
                # single track for 18 observations.
                #
                # It only ever rules a match *out*. Two entries with the same
                # killer, victim and weapon render at the same column, so equal
                # dividers are no evidence of anything; see `divider_of_ys`.
                if sig is not None and a["sig"] is not None                         and abs(a["sig"] - sig) > KF_SIG_TOL:
                    continue
                # Otherwise the nearest slot wins, which is imperfect in two
                # opposite ways and was the whole rule before the divider:
                #
                #   merge  -- an entry expires and the one below rises into the
                #             slot it vacated, so the detection joins the dead
                #             entry's track.
                #   split  -- preferring the most recently seen track instead
                #             fixes that, but shatters a genuine double
                #             (b3b9defb6fd7 27:12/27:14) and scores worse.
                #
                # Both survive here only for entries whose divider went
                # unrecorded -- an unparsed band, or a session stored before
                # hud-0.8.0.
                d = a["slot"] - slot
                if best is None or d < best:
                    best, bi = d, ai
            if bi is None:
                active.append({"t_first": t, "t_last": t, "slot": slot,
                               "n_obs": 1, "sig": sig})
                used.add(len(active) - 1)
            else:
                active[bi].update(t_last=t, slot=slot, sig=sig or active[bi]["sig"],
                                  n_obs=active[bi]["n_obs"] + 1)
                used.add(bi)
    done.extend(active)
    done.sort(key=lambda a: a["t_first"])
    for a in done:
        a["counted"] = a["n_obs"] >= KF_MIN_OBS
    return done


def _count(times, masks, dividers=None) -> int:
    return sum(1 for a in track_entries(times, masks, dividers) if a["counted"])


def player_events(times, kill_masks, death_masks,
                  kill_dividers=None, death_dividers=None) -> dict:
    """Distinct killfeed entries the local player was in, kills and deaths."""
    t = list(times)
    return {
        "kills": _count(t, list(kill_masks),
                        None if kill_dividers is None else list(kill_dividers)),
        "deaths": _count(t, list(death_masks),
                         None if death_dividers is None else list(death_dividers)),
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
        # Divider columns land from hud-0.8.0 on; older stored sessions have
        # no such column and fall back to slot-and-time matching.
        div = lambda c: table.column(c).to_pylist() if c in names else None
        ev = player_events(
            t,
            table.column("kf_kill_mask").to_pylist(),
            table.column("kf_death_mask").to_pylist(),
            div("kf_kill_wx"),
            div("kf_death_wx"),
        )
        sid = table.column("session_id")[0].as_py() if "session_id" in names else None
        ev["known"] = KNOWN_KD.get(sid)
        out["killfeed"] = ev

    out["violations"] = drift + len(left_drops) + len(right_drops) + len(sum_jumps)
    return out
