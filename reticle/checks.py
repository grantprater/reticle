"""Domain invariants over stored HUD reads (design doc SS3, stage 05).

The design doc calls these a *label-free error detector*: the clock counts down,
scores never fall, and the two scores sum to rounds played. Nobody has to label
a frame for those to be checkable, and a violation localises the extraction
fault in time.

This module computes; it does not print. `reticle verify` renders the result,
and the dashboard reads the same structure, so there is one implementation of
what counts as a fault.

Owns [owns:hud-invariant].
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
# holds its position until an entry above it expires, then rises
# [domain:killfeed/stack-order].
#
# Both bars below are stated in SAMPLES as well as milliseconds, because a bar
# in milliseconds alone means different things at different rates: 2500 ms is
# five samples at 2 Hz and 150 frames at 60. Every stored session was read at
# 2 Hz, so the millisecond figures are the ones the K/D scoring validated;
# the sample figures are what carries them to another rate.
KF_TRACK_GAP_MS = 2_500     # unseen for longer than this and the entry is gone
# ...and unseen for this many samples, whichever is SHORTER. At 2 Hz the
# millisecond cap binds and nothing changes. At native rate it is the sample
# count that binds, and it has to: with the 2500 ms cap alone, one track on
# c40d950031bb ran 503.5-511.5 s, absorbing seven scattered camera-wipe bands
# in four different slots and then the real entry that followed them 1.8 s
# later. The bar has to clear the reader's own dropouts, which are longer than
# one frame -- a real entry at 185.6-186.2 s vanishes for 583 ms and returns
# with the same divider column -- so it is set well above that and below the
# gap that laundered the wipe.
KF_TRACK_GAP_STEPS = 40
KF_MIN_OBS = 2              # a single-frame detection is noise, not an entry
# An entry that never persists is not an entry. A killfeed row lives about five
# seconds; a camera wipe paints plate colour across the tray for a frame or
# two. Over the six frozen P3 windows at native rate the two classes do not
# overlap or come close: eleven real entries span 4733-8017 ms and eleven wipe
# tracks span 0-667 ms.
#
# Written as a LIFE rather than a span so a low rate is not asked for
# resolution it does not have: a track qualifies when it could have been on
# screen this long, `span + 2*step`, since a sampler at interval d observes an
# entry of life L over at least L - 2d. 1500 ms is what 614 player entries at
# 2 Hz across seventeen scoreboard-scored sessions allow -- the shortest of
# them spans one sample interval, 500 ms = 1500 - 2*500 -- and scoring those
# sessions against `KNOWN_KD` is unchanged by it at every value up to 1500.
KF_ENTRY_MIN_LIFE_MS = 1_500
# How far an entry's divider column may move before it is a *different* entry.
# An entry's divider does not move at all while it is on screen -- the feed is
# right-aligned, so the victim's name width fixes the column -- and measured
# across sessions it wanders by at most 3 px. Two different entries sharing a
# slot are tens of pixels apart. 6 px sits well clear of both.
KF_SIG_TOL = 6

# Scoreboard K/D read off the end-of-match screen, keyed by session. This is the
# only external ground truth in the project -- everything else here is a
# label-free invariant -- so it is the one number that can say whether killfeed
# attribution is actually right rather than merely self-consistent. Transcribed
# off the end screens as each capture was ingested, then checked in full against
# the match history on 2026-08-25.
KNOWN_KD = {
    # In play order, with the map. the player read the whole run off the match
    # history on 2026-08-25 and every one of these agreed with what had already
    # been transcribed off the end screens -- so this table now has two
    # independent sources behind it, which is worth more than either alone.
    #
    # 2026-08-23.
    "0f08b3dc3777": (19, 12),   # 16-51-47  Summit, cropped capture
    "b3b9defb6fd7": (14, 18),   # 18-24-15  Summit
    "bdfdcf009dba": (17, 14),   # 19-25-23  Lotus
    "223d636bf8d2": (25, 15),   # 20-09-01  Haven
    # 2026-08-24. Recorded with the shooting-error readout switched off, so
    # their killfeed ROI is clear of overlays.
    "9acf02f98283": (13, 16),   # 11-55-34  Ascent
    "b7d24102a6f6": (10, 12),   # 12-37-04  Split
    "75a55a296d3b": (5, 5),     # 13-34-38  Abyss, a short match
    "59c70f1ef720": (15, 16),   # 13-58-11  Ascent
    # 19/15 confirmed by the player off the end screen. The killfeed reads 20 kills
    # and all 20 are read correctly; the extra one is a kill on an *enemy
    # Phoenix inside Run It Back*, which the scoreboard does not credit. Same
    # rule as ff636d173b07's uncounted deaths, seen from the other side.
    #
    #   `board` agrees at all ~50 openings, ending 18/14 at 39:27, and the
    #   killfeed also holds exactly 18 by then. Two more follow before the match
    #   ends -- both "Me (Vandal) BiGDonut101", eight seconds apart, with the
    #   victim taking a kill in between because Run It Back returned the player. The
    #   first carries the Phoenix ult mark.
    "bfad2778a372": (19, 15),   # 14-45-35  Split
    # Ingested long before it had a K/D, so it was never scored and never used
    # to tune anything. Given ground truth for the first time on 2026-08-25 it
    # came out *exact* -- the only genuinely out-of-sample number in the table.
    "96aa1ae9b96f": (16, 10),   # 17-51-06  Haven
    # A low-event match: with only two real kills, a single false positive shows
    # up as a 50% error, so this is the sharpest precision test in the set.
    "c40d950031bb": (2, 7),     # 18-27-17  Ascent
    # the player played Phoenix here. A death inside Run It Back is *not* counted on
    # the scoreboard (nor is Kayo's), while a Sage or Clove revive death is --
    # so the two behave oppositely, and only the Phoenix/Kayo case can leave a
    # killfeed entry with no scoreboard death behind it.
    #
    # At hud-0.8.1 this is fully accounted for. The killfeed holds 24 deaths,
    # all read correctly, and exactly four carry the Phoenix ult mark -- 13:21,
    # 20:00, 29:13 and 38:20. 24 - 4 = 20, the recorded figure. Checked by
    # rendering every tracked death entry into one contact sheet and counting
    # the marks; see the note in CLAUDE.md.
    "ff636d173b07": (27, 20),   # 18-47-51  Summit
    # 2026-08-25.
    "e37fdeca944f": (16, 19),   # 13-17-45  Sunset, a map not seen before
    "043bafca271a": (11, 15),   # 13-59-44  Haven
    "3694746e4e54": (14, 17),   # 14-42-25  Ascent
    # 2026-08-26. The first capture with the ENLARGED MINIMAP, ingested under
    # `valorant-16x9-bigmap`. Fully out-of-sample: nothing has been tuned
    # against it, and it is the first session recorded after the minimap size
    # change, so it also tests that the change cost the killfeed nothing.
    "a06f04a0059f": (19, 19),   # 09-56-37  Ascent
    # Two more on the enlarged minimap the same afternoon, on maps never seen
    # at this widget size. Confirmed `valorant-16x9-bigmap` before ingest: the
    # floor slab reaches x 452 / 458 against the old widget's 346.
    "5822b6646448": (13, 21),   # 12-38-38  Lotus
    "c62c2b06bcfb": (13, 15),   # 13-18-48  Split
}

#: Divergences that are READ CORRECTLY and that the game does not count, so
#: they must be subtracted before a residue is called a read error. Every entry
#: needs a verified cause written beside it -- this table is an allowance, and
#: an allowance with no reason is just a way of hiding a defect.
#:
#: the rule (CLAUDE.md): **Sage and Clove revive after a real death and
#: that death counts; Phoenix and Kayo grant the second life BEFORE the fact,
#: and those never counted.** Both entries below are the Phoenix case, seen
#: from opposite sides, and both were confirmed entry by entry.
KNOWN_DIVERGENCE: dict[str, tuple[int, int]] = {
    # +4 deaths: all 24 tracked deaths read correctly and exactly four carry
    # the Phoenix ult mark (13:21, 20:00, 29:13, 38:20). the deaths
    # inside Run It Back. 24 - 4 = 20, the recorded figure.
    "ff636d173b07": (0, 4),
    # +1 kill: the same rule from the other side -- a kill on an ENEMY Phoenix
    # inside Run It Back. 19/15 confirmed off the end screen; `board` agrees at
    # all ~50 openings.
    "bfad2778a372": (1, 0),
}


def _slots(mask) -> list[int]:
    if mask is None:
        return []
    m = int(mask)
    return [s for s in range(6) if m & (1 << s)]


def _side_at(pair, slot: int) -> str | None:
    """The victim plate's side in `slot` from one `(ally_mask, enemy_mask[, same])`
    pair: "ally", "enemy", or None when unread (neither bit, both, no pair)."""
    if pair is None:
        return None
    ally, enemy = (bool((m or 0) & (1 << slot)) for m in pair[:2])
    return "ally" if ally and not enemy else "enemy" if enemy and not ally else None


def _same_at(pair, slot: int) -> bool:
    """Whether the optional third mask of a `sides` entry flags `slot`."""
    return bool(pair is not None and len(pair) > 2 and (pair[2] or 0) & (1 << slot))


def sample_step_ms(times, default: float = 500.0) -> float:
    """The sampler's own interval, as the median gap between reads.

    Every bar below that is stated in samples needs this, and it has to be
    measured rather than declared: a run is asked for a rate and delivers
    another one, and a session with stalled capture has gaps no nominal rate
    predicts. The median ignores both.
    """
    t = np.asarray(list(times), dtype=np.float64)
    if t.size < 3:
        return float(default)
    d = np.diff(t)
    d = d[d > 0]
    return float(np.median(d)) if d.size else float(default)


def track_entries(times, masks, dividers=None, flags=None, sides=None) -> list[dict]:
    """Follow each entry across frames; one dict per distinct entry.

    Returns every track, including the ones the bars refuse, with `counted`
    saying whether it met them and `refused` naming the first bar it failed.
    Callers that only want the number use `player_events`; a review needs the
    timestamps as well, and both must come from the same walk or they can
    disagree.

    `dividers` is the parallel column of packed divider positions written by
    `killfeed.divider_of_ys`. Given it, a detection is only allowed to extend a
    track whose divider sits within KF_SIG_TOL of it, which is what separates
    two entries occupying the same slot in turn from one entry that stayed put.
    Pass None and the walk falls back to slot and time alone, which is what
    every stored session before hud-0.8.0 has.

    `flags`, a {name: column of slot masks} parallel to `times`, counts per
    track how many of its observations carried each flag in the slot it held
    then (`flag_hits`); `n_obs` is the denominator.

    `sides`, a column of `(ally_mask, enemy_mask)` pairs parallel to `times`
    (the stored `kf_ally_mask` / `kf_enemy_mask`, the victim plate's side per
    slot), keeps a detection off a track whose last read victim plate was the
    other side: one entry's victim never changes team, so a flip is a new entry
    in the same slot. At 59c70f1ef720 slot 0 an enemy-victim entry read
    1619.5-1624.0 s, the slot missed one sample, and an ally-victim entry
    followed at 1625.0 s, dividers 250 against 253, inside KF_SIG_TOL and the
    track gap; the walk without sides held both as one track keyed at 1619.5 s,
    and the player's death took that key and the enemy side. An unread side
    rules nothing out, and a sample the slot missed in between does not hide
    the flip. Each track then carries `side`, its last read victim side, and
    `one_colour`. None keeps the walk that ignores plate side.
    A pair may carry a third mask, the stored `kf_same_side_mask`: a track
    that has read a one-colour banner never splits on side, because a revive's
    victim plate reads ally and enemy by turns (bdfdcf009dba 1884-1886 s,
    divider 328, alternates `As` and `E`) and would otherwise shed a phantom
    entry at each flicker.

    **This is where a band that appears for three frames and never again is
    refused, and it is the right place for it.** `read_killfeed` sees one frame
    and must keep reporting what that frame held; only a walk across frames can
    say that a plate-coloured band never persisted and so was never an entry.
    Measured over the frozen P3 windows at native rate, the two bars together
    leave eleven tracks -- the same eleven the stored 2 Hz read finds -- and
    refuse eleven camera-wipe tracks, taking the confuser false-positive
    instants from eleven to zero without costing one instant of recall.

    **An entry rises only into a slot its occupant vacated**
    [domain:killfeed/stack-order]. So when the nearest track did not read in
    the previous sample and a track from lower down did, and nothing in the
    lower track's own slot now could still be it, the detection is that lower
    entry risen, not the expired one returning. Without this the
    nearest slot won, and a risen entry whose divider and victim side agreed
    with the entry that expired above it joined that entry's track:
    [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#welded_entries=45]
    of [metric:killfeed_stack_order/weld@stored-hud~stack-order-20260929#entries=3310]
    stored entries, among them the player's death at 043bafca271a
    1506.5 s, whose track ended a sample after it began while the entry above
    ran on to 1511.0 s. Each track's `assigned` lists `(t, slot, rule)` per
    detection, the rule `new`, `nearest` or `stack_rise`, so the walk can say
    why a detection joined the track it did; the track whose slot a risen
    entry took ends there and carries `ended_by = "stack_rise"`.
    """
    active: list[dict] = []
    done: list[dict] = []
    times = list(times)
    step = sample_step_ms(times)
    gap = min(KF_TRACK_GAP_MS, KF_TRACK_GAP_STEPS * step)
    if dividers is None:
        dividers = [None] * len(times)
    flags = flags or {}
    use_sides = sides is not None
    if not use_sides:
        sides = [None] * len(times)
    for i, (t, mask, packed, pair) in enumerate(zip(times, masks, dividers, sides)):
        flagged = lambda slot: {k: int(bool((col[i] or 0) & (1 << slot)))
                                for k, col in flags.items()}
        prev_t = times[i - 1] if i else None
        keep = []
        for a in active:
            (keep if t - a["t_last"] <= gap else done).append(a)
        active = keep
        used: set[int] = set()
        retired: set[int] = set()
        here = _slots(mask)

        def fits(a, sig, side) -> bool:
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
            if sig is not None and a["sig"] is not None and abs(a["sig"] - sig) > KF_SIG_TOL:
                return False
            # The victim plate's side rules a match out the same way, unless
            # the track has read a one-colour banner (see the docstring).
            return not (side is not None and a.get("side") is not None
                        and a["side"] != side and not a.get("one_colour"))

        def stayed(a) -> bool:
            """Whether a detection in the track's own slot now could be it and
            is not the entry below it risen. Entries rise together and keep
            their order, so a read in the slot is the lower neighbour's when
            that neighbour read last sample and has left its own slot
            (9acf02f98283 1232.0 s: two entries rise at once and the upper
            one's slot holds the lower one)."""
            s = a["slot"]
            det = (wx_at(packed, s), _side_at(pair, s))
            if s not in here or not fits(a, *det):
                return False
            below = [b for bi_, b in enumerate(active) if bi_ not in used and b["slot"] > s
                     and b["t_last"] == prev_t]
            if not below:
                return True
            b = min(below, key=lambda b: b["slot"])
            return not (fits(b, *det) and not stayed(b))

        for slot in here:
            sig = wx_at(packed, slot)
            side = _side_at(pair, slot)
            one_colour = _same_at(pair, slot)
            cands = [ai for ai, a in enumerate(active)
                     # an entry never moves down the stack
                     if ai not in used and slot <= a["slot"] and fits(a, sig, side)]
            # The nearest slot wins, unless the stack says otherwise:
            #
            #   merge  -- an entry expires and the one below rises into the
            #             slot it vacated. Where their dividers and victim sides
            #             agree, the nearest slot gives the risen detection to
            #             the dead entry's track. The stack rule below keeps it.
            #   split  -- preferring the most recently seen track outright
            #             shatters a genuine double (b3b9defb6fd7 27:12/27:14)
            #             and scores worse, since an entry's own dropout makes
            #             the track below it look fresher. So the lower track
            #             is preferred only when its own slot is empty of it.
            near = lambda ai: active[ai]["slot"] - slot
            bi = min(cands, key=near) if cands else None
            rule = "new" if bi is None else "nearest"
            if bi is not None and prev_t is not None and active[bi]["t_last"] != prev_t:
                # The nearest track did not read last sample, so its entry
                # may have expired. A track below that did read, and is not
                # still in its own slot, is the entry that rose into it.
                risen = [ai for ai in cands if active[ai]["t_last"] == prev_t
                         and active[ai]["slot"] > active[bi]["slot"]
                         and not stayed(active[ai])]
                if risen:
                    # The entry whose slot was taken has expired, so its
                    # track ends here; left open, it took the risen entry's
                    # next read back as the nearer of two tracks in one slot
                    # (bdfdcf009dba 1949.5 s).
                    if active[bi]["slot"] == slot:
                        active[bi]["ended_by"] = "stack_rise"
                        used.add(bi)
                        retired.add(bi)
                    bi = min(risen, key=near)
                    rule = "stack_rise"
            if bi is None:
                active.append({"t_first": t, "t_last": t, "slot": slot, "slot_first": slot,
                               "n_obs": 1, "sig": sig, "flag_hits": flagged(slot),
                               "assigned": [(t, slot, rule)]})
                if use_sides:
                    active[-1]["side"] = side
                    active[-1]["one_colour"] = one_colour
                used.add(len(active) - 1)
            else:
                active[bi]["assigned"].append((t, slot, rule))
                hits = active[bi]["flag_hits"]
                for k, v in flagged(slot).items():
                    hits[k] = hits.get(k, 0) + v
                active[bi].update(t_last=t, slot=slot, sig=sig or active[bi]["sig"],
                                  n_obs=active[bi]["n_obs"] + 1)
                if use_sides and side is not None:
                    active[bi]["side"] = side
                if use_sides and one_colour:
                    active[bi]["one_colour"] = True
                used.add(bi)
        if retired:
            done.extend(active[ai] for ai in sorted(retired))
            active = [a for ai, a in enumerate(active) if ai not in retired]
    done.extend(active)
    done.sort(key=lambda a: a["t_first"])
    for a in done:
        a["span_ms"] = a["t_last"] - a["t_first"]
        # `span + 2*step` is the longest life this track is consistent with,
        # so a sampler is never refused for resolution it does not have.
        a["life_ms"] = a["span_ms"] + 2 * step
        a["refused"] = (
            "single_frame" if a["n_obs"] < KF_MIN_OBS
            else "no_persistence" if a["life_ms"] < KF_ENTRY_MIN_LIFE_MS
            else None
        )
        a["counted"] = a["refused"] is None
    return done


def entry_presence(times, masks, dividers=None) -> list[dict]:
    """Adjudicated entry count at each sampled instant.

    The count of record, and not the same thing as `kf_entries`: that column is
    what one frame held, which on a wiped frame is a guess dressed as a count.
    Here an instant carries an entry when a track that PERSISTED covers it, so
    a wash that paints the tray for two frames contributes nothing and a real
    entry contributes over its whole life, including the frames its own plate
    dropped out of.
    """
    times = list(times)
    live = [(a["t_first"], a["t_last"])
            for a in track_entries(times, masks, dividers) if a["counted"]]
    return [{"t_ms": t, "entries": sum(1 for a, b in live if a <= t <= b)}
            for t in times]


#: The longest a real entry was seen on screen (8017 ms over the frozen P3
#: windows, above): two tracks spanning more than this are two entries.
KF_ENTRY_MAX_LIFE_MS = 8_000


def merge_split_tracks(tracks: list[dict]) -> list[dict]:
    """Join a player's kill or death tracks that are one entry split in two.

    The entry stays on screen while its ATTRIBUTION drops out -- `a06f04a0059f`
    shows one Me->Deebo entry in slot 0 from 106.5 to 111.0 s with the kill
    verdict lost for 3 s, longer than `KF_TRACK_GAP_MS` -- or it rises a slot
    across the gap. A later track is the same entry when its divider column
    matches within `KF_SIG_TOL`, it starts after the earlier one ends, it sits
    in the same or a higher slot (entries only rise), and the two span no more
    than one entry can live. Found against the combat report; over the 17
    `KNOWN_KD` sessions this merges exactly those two and no other track.
    """
    out: list[dict] = []
    for tr in sorted(tracks, key=lambda x: x["t_first"]):
        prev = next((p for p in reversed(out)
                     if p.get("sig") and tr.get("sig")
                     and abs(p["sig"] - tr["sig"]) <= KF_SIG_TOL
                     and tr["t_first"] > p["t_last"] and tr["slot"] <= p["slot"]
                     and tr["t_last"] - p["t_first"] <= KF_ENTRY_MAX_LIFE_MS), None)
        if prev is None:
            out.append(dict(tr))
            continue
        prev["t_last"] = max(prev["t_last"], tr["t_last"])
        prev["slot"] = tr["slot"]
        prev["n_obs"] = prev.get("n_obs", 0) + tr.get("n_obs", 0)
        prev["merged"] = prev.get("merged", 0) + 1
    return out


def _count(times, masks, dividers=None) -> int:
    return len(merge_split_tracks(
        [a for a in track_entries(times, masks, dividers) if a["counted"]]))


def player_events(times, kill_masks, death_masks,
                  kill_dividers=None, death_dividers=None, second_life=None) -> dict:
    """Distinct killfeed entries the local player was in, kills and deaths.

    `second_life` is the stored `second_life_observation` rows; given them,
    `adjudication.death.split_second_lives` moves Run It Back deaths to
    `second_lives`, as `rounds` does. Without them every death counts and
    `second_lives` is None.
    """
    from .adjudication.death import split_second_lives

    t = list(times)
    div = lambda d: None if d is None else list(d)
    deaths, lives = split_second_lives(
        merge_split_tracks([a for a in track_entries(t, list(death_masks), div(death_dividers))
                            if a["counted"]]), second_life)
    return {
        "kills": _count(t, list(kill_masks), div(kill_dividers)),
        "deaths": len(deaths),
        "second_lives": None if second_life is None else len(lives),
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
        ev["allowed"] = KNOWN_DIVERGENCE.get(sid)
        if ev["known"]:
            ak, ad = ev["allowed"] or (0, 0)
            ev["read_error"] = (ev["kills"] - ev["known"][0] - ak,
                                ev["deaths"] - ev["known"][1] - ad)
        out["killfeed"] = ev

    # The scoreboard delta COUNTS. It used to be computed here and left out of
    # this sum, which made the one check that compares against something
    # outside the pipeline unable to fail: `a06f04a0059f` is off by five events
    # and `verify` would have printed "OK no invariant violations" but for an
    # unrelated scoreline blip. CLAUDE.md calls KNOWN_KD "the only checks that
    # compare against something outside the pipeline"; it was the only signal
    # excluded from the verdict.
    #
    # `KNOWN_DIVERGENCE` is what keeps this honest in the OTHER direction. Per
    # the call, a Run It Back event is read correctly and simply not
    # counted by the game -- it must be LABELLED, not eliminated, or the next
    # person tunes the extractor until a real duel disappears. So an allowed
    # divergence is subtracted before the residue is called a fault, and the
    # residue is what "read error" has always meant in the docs.
    kf = out.get("killfeed") or {}
    read_err = kf.get("read_error")
    out["violations"] = (drift + len(left_drops) + len(right_drops)
                         + len(sum_jumps)
                         + (abs(read_err[0]) + abs(read_err[1]) if read_err else 0))
    return out
