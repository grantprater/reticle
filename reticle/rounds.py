"""Stage 05: rounds, derived from stored L1 (design doc SS3).

Why the round is the unit
-------------------------
the framing, and it is the reason this table exists: a round is very nearly
a controlled experiment. Same map, same start, same objective, same ten players,
every time. The only things that change its shape are **economy** -- guns,
armour, abilities, ult points -- and **information**, what each side learned from
the rounds before. Everything else is held constant by the game itself.

That makes "win rate given X" a far stronger question here than it would be in a
sport with continuous play, because the confounders are enumerable rather than
endless. It also says exactly what to record next: economy is not extracted yet,
and until it is, any relationship this table turns up is confounded by it.

Mechanical questions -- duels, peeks, aim -- do not belong here. They are
*engagement* scoped and nest inside a round; `round_no` is the key they will
hang off when that table lands.

Everything is recomputed from stored L1, so this never opens the video. Adding a
new fact means rebuilding a few hundred rows in milliseconds rather than
re-reading fourteen captures, which is the whole point of the L0/L1/L2 split.

What is derivable now, and what is not
--------------------------------------
Free from what is already stored:

* **round bounds and the winner** -- the scoreline total climbs by one at the
  end of every round, and which side climbed says who took it;
* **the player's kills and deaths** -- the killfeed, at one read error in 372
  events across fourteen sessions;
* **first blood** -- `kf_entry_mask` records *every* entry, not just the
  player's, so the earliest entry of a round is that round's first blood. If it
  is also the player's kill the player took it; if it is the death the player was traded out
  first. No new extractor and no name reading;
* **which side of the scoreline is the player's** -- `PLAYER_SIDE`, structural
  since 2026-08-27. The top HUD band is COLOURED BY TEAM (green ally left, red
  enemy right), so the scoreline states it outright; `infer_player_side` is kept
  only as a check. It used to decide, and abstained on 3 sessions, leaving `won`
  NULL for 43 rounds -- all 23 of Lotus among them.

**`spike_planted` reads the planted-spike graphic as of round-0.8.0
(2026-10-02).** The graphic stands where the clock's digits go, so a plant is
that graphic (`plant_graphic`, from the hud crop cache) on two consecutive
samples whose clock reads nothing. It replaced a rule that took any unread-clock
run of 7 s reaching the round's end, which missed plants in rounds won by
elimination seconds after the plant and could not tell a washed-out clock from
the graphic. `spike_planted` is null, with `plant_reason`, where the evidence is
absent or too short; False means the graphic was looked for and not seen. A
plant after the score increment is outside the field's meaning: the scoreline
keeps its post-round countdown then. See the PLANT_* block.

`plant_t_ms` is the first graphic sample: within about half a second of
Riot's recorded plant on the 21 Riot-scored matches, the cache's 2 Hz.

The plant is a **phase boundary**, not just a fact (recorded). Pre-plant and
post-plant are different games -- attackers switch to holding, defenders must
retake -- so a round splits into two phases, and the *state at the transition*
(players alive each side, whether the player is alive, time left) is a covariate
for everything that follows it. That is the shape the next version wants, and it
is another reason `spike_planted` has to become reliable before it is used.

**Audio is the way to sharpen it, and it is still untouched.** Recorded 2026-08-27: :
*the spike beeping speeds up at standard intervals, so that's the main way
players tell how much time is left in postplant.* That makes audio not merely a
cheaper plant flag but **a post-plant CLOCK** -- and post-plant is the one window
where the pixels have no digits at all, by construction. The exact-boundary
alternative is a red-fraction test on the scoreline centre, which is trivial but
costs a `hud` re-run over every capture.

**A round ends exactly three ways** (recorded): team wipe, spike defused, spike
detonated -- plus time expiring with no plant, which the defenders take. And the
plant changes the rule rather than adding to it: **once the spike is down the
defenders must defuse or they lose, however many attackers they kill.** Wiping
the attacking team post-plant does not win the round.

That is not a footnote, it changes what several facts here *mean*. "Player
survived" reads as a proxy for winning the fight, but post-plant an attacker can
survive, win every duel, and still lose to the defuse; a defender can wipe the
enemy team and lose to the timer. Any model that treats survival or man
advantage as uniformly good is wrong on exactly the rounds where the stakes are
highest. Phase has to be a covariate, not a column.

The outcome type is derivable once the plant is: a plant plus the 45 s running
out is a detonation, a plant plus the round ending early is a defuse, and no
plant at all is a wipe or the timer. Attack and defence are structurally
different too, and the sides swap [domain:rounds/halftime-side-swap] -- also
not yet known.

The other thing missing for phase analysis is **alive counts**, and those are
closer than they look. Every killfeed entry is a death, and the victim's plate
colour already says which team -- `_plate_masks` computes it and
`analyse_killfeed` knows where the divider is, so recording `victim_is_ally` per
entry would give both sides' alive counts through the round. That single field
unlocks man advantage, clutch detection, and the "how many enemies are alive"
conditioner the peek work needs. It is probably the highest-value field left.

Round boundaries are ~98% complete (281 found against 287 expected across
fourteen sessions) but their *timing* is loose. The scoreline only climbs once
a round has ended and it reads at 33-60%, so a boundary can be detected seconds
late and leak the next round's opening kills backwards into this one. Deaths per
side peak at 4 and 5 as they should, with 13% of side-rounds above 5 -- part
revives, part that slop. Snapping boundaries to the round clock's reset to 100 s
would sharpen them, and is the obvious next improvement here.

**Do not use deaths-per-round as an invariant.** A revive lets a player die
twice in a round, so more than five deaths on a side is legitimate -- Sage and
Clove both produce it. This is stated in CLAUDE.md's conventions and was
promptly rediscovered the hard way, by writing exactly that check and reporting
its failure as a defect.

Not derivable, and deliberately absent rather than guessed: who planted,
assists, and economy of any kind -- which, per the note above, is the one
confounder that actually varies between rounds.

Owns [owns:round-bounds].
"""

from __future__ import annotations

import numpy as np

from .checks import KF_MIN_OBS, merge_split_tracks, track_entries
from .killfeed import wx_at  # noqa: F401  (kept so callers can unpack dividers)

# The spike countdown. A mid-round reset to this is a plant; `checks` uses the
# same constant to tell a phase change from a misread digit.
SPIKE_MS = 45_000
SPIKE_TOL_MS = 3_000
# A plant cannot happen in the opening seconds, and the first buy phase also
# starts at 45 s -- so ignore resets near the round's start.
SPIKE_MIN_ELAPSED_MS = 15_000
# How far the clock must move for a reading of 45 s to be a *reset* rather than
# the round timer passing through 45 s on its way down. The plant can land on
# either side of it: planting with 60 s left drops the clock, planting with 20 s
# left raises it, and only the size of the step tells a reset from normal decay.
SPIKE_STEP_MIN_MS = 6_000
# The killfeed entry that opened a round, and the player's own entry, are the
# same event when their track starts within this of each other.
FIRST_BLOOD_TOL_MS = 1_500

# --- the plant, read as a PERSISTENT state (2026-08-27) --------------------
# The spike graphic replaces the round timer for the whole post-plant, so a
# planted round has no clock to read and `clock_ms` is already None in L1. That
# makes the plant free to detect with no new ROI and no video re-read:
#
#     a plant is the longest run of unreadable clock inside a round, when that
#     run is long enough and reaches the round's end.
#
# Validated against pixels on 9acf02f98283 via `prototypes/plant_probe.py`:
# 20 frames, 6 of them controls (a READABLE clock proves the graphic is absent,
# since they occupy the same pixels -- truth from `ocr.py`, not from this rule),
# sheet VALID at 6/6. On the 14 open frames: **recall 100%, precision 88%.**
# Rate 145 of 349 rounds (42%) at PLANT_MIN_MS=7s, against the 6 in 262 the old
# clock-jump rule found. Held-out recheck below.
#
# **The boundary is only good to about +/-5 s.** The single false positive was a
# frame whose clock reads `1:14` to the eye while `ocr.py` returned None, so an
# OCR drop can start the run before the plant. Good enough to SPLIT a round into
# phases, not good enough to time one. Two ways to sharpen it, both out of scope
# here: a red-fraction test on the scoreline centre (exact, but needs `hud`
# re-run), or audio -- the player reports the spike's beep speeds up at standard
# intervals, which encodes the remaining time and is the only channel that still
# has a clock after the digits are gone.
# The TAIL is the discriminator, not the length: a post-plant run always reaches
# the round's end, an OCR dropout mid-round does not. Over 349 rounds the
# trailing-run histogram is 200 rounds at 0-4 s (the end-of-round animation),
# a sparse 5-19 s band, then a broad 20-45 s plateau that stops exactly at the
# spike's 45 s fuse. So the floor is set by a GAME RULE rather than fitted:
# **a defuse takes 7 s**, so no post-plant can be shorter than that. 20_000 was
# the first guess and it cost 2 of 5 plants on 223d636bf8d2 -- both real, at
# 18.5 s and 16.0 s, fast defuses missed by seconds.
#
# **Superseded 2026-10-02 (round-0.8.0) as the deciding rule**; it now runs
# only where no current `plant_graphic` stream exists, and marks plants there
# but never a non-plant. Against Riot's match records over 21 matches it missed
# 68 of 280 plants: 66 were rounds won by elimination a median 3.4 s after the
# plant, a post-plant shorter than a defuse. The floor assumed the post-plant
# lasts at least a defuse; an elimination ends it sooner. And the unread-clock
# run is not the plant's own evidence: a washed-out clock over a bright sky, or
# the last fifteen seconds' red plate, leaves the digits unread for as long.
PLANT_MIN_MS = 7_000
PLANT_TAIL_MS = 2_500
PLANT_MIN_ELAPSED_MS = 15_000

# --- the plant, read as the planted-spike GRAPHIC (round-0.8.0) -------------
# The graphic stands where the digits go [domain:hud/planted-spike-replaces-clock],
# so a plant has two witnesses on one sample: `plant_graphic` sees the graphic,
# and the scoreline reads no clock. A sample is a graphic sample when both hold;
# a read clock refutes the graphic. The graphic is a persistent state, so a
# plant needs PLANT_MIN_SAMPLES consecutive graphic samples; a single one is too
# short to tell from a red flash and stores null. A plant after the score
# increment shows no graphic [domain:rounds/post-round-plant-no-graphic], so
# the window ends at the round's end and `spike_planted` means planted before
# the round was decided. It opens at the round's first live clock reading
# (above BUY_CLOCK_MAX_MS): the graphic replaces a running round clock, and a
# round opened at the capture's start may hold menus before it.
PLANT_MIN_SAMPLES = 2


def _plant_graphic(t, clock, a: float, z: float,
                   graphic: dict[float, dict]) -> tuple[bool | None, float | None, str | None]:
    """(planted, plant time, reason) from the graphic over the round's live
    play: from its first live clock reading to its end `z`.

    True at the first sample of the first run of PLANT_MIN_SAMPLES graphic
    samples; None with `no_live_clock` where no live clock was read,
    `graphic_single_sample` where the graphic never held longer, or
    `no_plant_graphic_rows` where no sample of the window was read; False
    otherwise."""
    from .plant_graphic import shows_graphic
    live = next((t[i] for i in range(len(t)) if a <= t[i] <= z and clock[i] is not None
                 and clock[i] > BUY_CLOCK_MAX_MS), None)
    if live is None:
        return None, None, "no_live_clock"
    runs, cur, read = [], [], 0
    for i in range(len(t)):
        if not (live <= t[i] <= z):
            continue
        seen = shows_graphic(graphic.get(float(t[i])))
        read += seen is not None
        if seen and clock[i] is None:
            cur.append(float(t[i]))
            continue
        if cur:
            runs.append(cur)
        cur = []
    if cur:
        runs.append(cur)
    held = [r for r in runs if len(r) >= PLANT_MIN_SAMPLES]
    if held:
        return True, held[0][0], None
    if runs:
        return None, None, "graphic_single_sample"
    if not read:
        return None, None, "no_plant_graphic_rows"
    return False, None, None


def plant_state(t, clock, a: float, z: float, graphic: dict[float, dict] | None) -> dict:
    """The round's plant fields: `spike_planted` (True, False, or None with
    `plant_reason`), `plant_t_ms`, `post_plant_ms` and `plant_source`.

    `graphic` is the stored `plant_graphic` samples by time
    (`plant_graphic.stored_reads`); None where the stream is absent or stale.
    Without it the clock-run rule may mark a plant, but its silence is no
    evidence of none: every other round is null, `plant_graphic_absent`."""
    if graphic is not None:
        planted, tp, why = _plant_graphic(t, clock, a, z, graphic)
        source = "plant_graphic"
    else:
        ok, tp = _plant(t, clock, a, z)
        planted, why, source = (True, None, "clock_run") if ok else (None, "plant_graphic_absent",
                                                                    "clock_run")
    return {"spike_planted": planted, "plant_t_ms": tp,
            "post_plant_ms": (z - tp) if tp is not None else None,
            "plant_source": source, "plant_reason": why}


def _plant(t, clock, a: float, z: float) -> tuple[bool, float | None]:
    """Longest unreadable-clock run in [a, z), and whether it is a plant by
    the superseded run rule (see the PLANT_* block)."""
    best, cur, cstart = (0.0, None, None), 0, None
    for i in range(len(t)):
        if not (a <= t[i] < z):
            continue
        if clock[i] is None:
            if cur == 0:
                cstart = t[i]
            cur += 1
            if t[i] - cstart > best[0]:
                best = (t[i] - cstart, cstart, t[i])
        else:
            cur = 0
    span, s0, s1 = best
    ok = bool(s0 is not None and span >= PLANT_MIN_MS
              and (z - s1) <= PLANT_TAIL_MS and (s0 - a) >= PLANT_MIN_ELAPSED_MS)
    return ok, (s0 if ok else None)


#: A clock RESET raises the reading by at least this. The countdown falls by
#: one second per second, so nothing but a reset moves it up by ten.
ROUND_START_JUMP_MS = 10_000
#: How far past a score increment to look for the reset before giving up.
#: The measured gap is ~7 s; this is six times that.
ROUND_START_WINDOW_MS = 45_000
#: A buy-phase clock never exceeds this. It separates the FIRST reset (buy,
#: ~30 s) from the second (the round proper, ~100 s); taking the wrong one
#: would put the start ~30 s late.
BUY_CLOCK_MAX_MS = 45_000


def _clock_reset_after(t, clock, after_ms):
    """The first upward clock JUMP after `after_ms` -- the buy-phase reset.

    Detected as a JUMP rather than as a value in a band, because the band is
    not reliably observed: on `587c15b07779` the round ending at 157.5 s has
    its buy-phase clock first read at **16 s**, the earlier part of it lost to
    a frozen frame. The jump is present either way.
    """
    prev = None
    for i in range(len(t)):
        if t[i] <= after_ms:
            if clock[i] is not None:
                prev = clock[i]
            continue
        if t[i] - after_ms > ROUND_START_WINDOW_MS:
            break
        c = clock[i]
        if c is None:
            continue
        if (prev is not None and c > prev + ROUND_START_JUMP_MS
                and c <= BUY_CLOCK_MAX_MS):
            return float(t[i])
        prev = c
    return None


def round_bounds(t, score_left, score_right, clock_ms=None):
    """Rounds read off the scoreline: one ends when the total climbs by one.

    Guarded against the scoreline's known misreads. `ocr.py` drops a transient
    extra digit (1 -> 11 -> 1 on 9acf02f98283), so an increment is only believed
    when the total rises by exactly one *and* neither side's score falls -- a
    spurious digit fails both tests.

    THE END IS THE SCORE INCREMENT; THE START IS THE CLOCK RESET
    --------------------------------------------------------------
    **Corrected 2026-09-07, and only the START moved.** Rounds used to be
    contiguous -- each began where the last ended -- which put the start at the
    score increment, the instant the round was DECIDED rather than the instant
    the next one began. Measured against two independent channels:

        clock at the old round start   median 6.0 s over 281 rounds on all 18
                                       sessions; the median is 6.0 s on 17 of
                                       them and 5.0 s on the eighteenth, and
                                       95% read under 15 s -- the PREVIOUS
                                       round's dying seconds
        roster, 26 rounds on the two sessions that have one:
            wipe onset - old round END       median +0.0 s
            both teams back to 5 - old END   median +7.0 s (p10 +4.5, p90 +7.5)
            clock when both are back to 5    median 28.0 s -- the buy phase

    A round does not begin with six seconds on the clock. The END is well
    placed and was left exactly where it was, so rounds are no longer
    contiguous: the gap between one end and the next start is the post-round
    period, which is correct rather than missing.

    `clock_ms` is optional so a caller holding only a scoreline still works.
    **Without it the old contiguous definition is used**, and every round says
    which rule produced it in `start_source` rather than being silently
    indistinguishable. That field also carries the fallback taken when no reset
    is found, which must stay countable rather than disappear into the total.
    """
    out = []
    prev = None
    start = float(t[0]) if len(t) else 0.0
    # Round 1 opens at the capture's first sample whatever the clock says: it
    # may hold a menu or a partial capture, a known limit rather than a reset.
    source = "capture_start"
    for i in range(len(t)):
        a, b = score_left[i], score_right[i]
        if a is None or b is None:
            continue
        if prev is None:
            prev = (a, b)
            continue
        pa, pb = prev
        if a >= pa and b >= pb and (a + b) == (pa + pb) + 1:
            out.append({
                "t_start_ms": start,
                "t_end_ms": float(t[i]),
                "left_before": int(pa), "right_before": int(pb),
                "won_left": bool(a == pa + 1),
                "start_source": source,
            })
            reset = (_clock_reset_after(t, clock_ms, float(t[i]))
                     if clock_ms is not None else None)
            start = reset if reset is not None else float(t[i])
            source = "clock_reset" if reset is not None else "score_increment"
        if (a, b) != prev:
            prev = (a, b)
    return out


def match_over(left: int, right: int) -> bool:
    """Whether a score ends the match [domain:rounds/match-end]: 13 against 11
    or fewer, or two ahead in overtime -- one test, since winning both rounds
    of an overtime cycle is leading a tie by two."""
    return max(left, right) >= 13 and abs(left - right) >= 2


#: Rounds in each half of regulation [domain:rounds/side-by-round].
HALF_ROUNDS = 12
#: The sides a team plays: its starting side and the other one.
SIDES = ("attack", "defence")


def match_round(r: dict) -> int | None:
    """A round's number in the MATCH, counted from 1: one more than the score
    before it. `round_no` counts the capture's rounds instead, and differs
    wherever a capture opens after the match's first round. None where the
    score before the round went unread."""
    us, them = r.get("score_us"), r.get("score_them")
    if us is None or them is None:
        us, them = r.get("left_before"), r.get("right_before")
    return None if us is None or them is None else int(us) + int(them) + 1


def side_in_round(match_round_no: int | None,
                  starting_side: str | None) -> tuple[str | None, str | None]:
    """(side, reason): the side, `attack` or `defence`, a team plays in match
    round `match_round_no` (`match_round`) given the side it started on.

    The rule [domain:rounds/side-by-round]: rounds 1-12 on the starting side,
    13-24 on the other after the halftime swap [domain:rounds/halftime-side-swap]
    (round 13 is the second pistol round [domain:rounds/pistol-round-bank]),
    and in overtime [domain:rounds/match-end] each cycle of two rounds opens
    on the starting side and closes on the other. The side is null with a
    reason where the starting side or the round number is unread; it is
    never defaulted."""
    if starting_side not in SIDES:
        return None, "starting_side_unread"
    if match_round_no is None or match_round_no < 1:
        return None, "match_round_unread"
    regulation = 2 * HALF_ROUNDS
    swapped = (HALF_ROUNDS < match_round_no <= regulation
               or (match_round_no > regulation and (match_round_no - regulation) % 2 == 0))
    other = SIDES[1] if starting_side == SIDES[0] else SIDES[0]
    return (other if swapped else starting_side), None



def starting_side(rounds: list[dict], spike_rows: list[dict] | None,
                  carrier_rows: list[dict] | None) -> dict:
    """The side the player's team started the match on, read from stored
    evidence only the attacking side produces, never defaulted.

    Two channels, each a vote that the player's team ATTACKS a round:

    * `carrier`: a stored `spike` frame inside the round (`t_start_ms` to
      `t_end_ms`, the span `spike_carrier` uses) on which our roster marker
      and a carried glyph on our minimap agree (`spike_carrier.frame_state`).
      Only the attackers hold the spike, and only our own carrier is drawn
      [domain:minimap/spike-carrier-overlay] [domain:hud/spike-carrier-marker].
      A frame where one of the two says carried is `spike_carrier`'s stored
      disagreement and votes nothing.
    * `planter`: the round's stored `spike_carrier` row names a planter slot,
      our marker read before a plant the scoreline graphic timed. It rests on
      the marker channel (`rests_on`), so it adds the plant's time, not an
      independent carrier witness.

    Each vote implies a starting side through `side_in_round` at the round's
    `match_round`; a vote whose match round is unread implies nothing. One
    implied side is the answer. Implications on both sides refuse
    `starting_side_conflict`; no vote refuses `no_attack_evidence`; absent
    streams refuse `spike_unread`. `disagreements` stores the rounds behind a
    conflict and the cross-channel disagreements: `planter_without_agreed_carrier`
    (a planter slot, no agreed carrier frame) and `carrier_without_planter`
    (an agreed carrier and a plant, no planter slot).

    Returns `{"starting_side", "reason", "votes", "disagreements"}`."""
    out = {"starting_side": None, "reason": None, "votes": [], "disagreements": []}
    if not spike_rows or not carrier_rows:
        out["reason"] = "spike_unread"
        return out
    from .adjudication.spike_carrier import frame_state
    head = spike_rows[0]
    sc = float(head.get("widget_scale") or 1.0)
    agreed = np.asarray(sorted(
        st["t_ms"] for st in (frame_state(r, sc) for r in spike_rows[1:]
                              if r.get("kind") == "frame")
        if st["slot"] is not None and st["glyph"] == "carried"), float)
    planters = {c.get("round_no"): c for c in carrier_rows if c.get("kind") == "round"}
    implied: dict[str, list[int]] = {s: [] for s in SIDES}
    for r in rounds:
        a, z = r.get("t_start_ms"), r.get("t_end_ms")
        if a is None or z is None:
            continue
        n = match_round(r)
        frames = int(np.count_nonzero((agreed >= a) & (agreed <= z)))
        crow = planters.get(r.get("round_no")) or {}
        planter = crow.get("planter_slot") is not None
        if planter and not frames:
            out["disagreements"].append({"round_no": r.get("round_no"),
                                         "check": "planter_without_agreed_carrier"})
        if frames and crow.get("spike_planted") and not planter:
            out["disagreements"].append({"round_no": r.get("round_no"),
                                         "check": "carrier_without_planter"})
        for channel, voted in (("carrier", frames > 0), ("planter", planter)):
            if not voted:
                continue
            # Attacking in a round played on the starting side means the
            # team started on attack; otherwise it started on defence.
            start, why = side_in_round(n, "attack")
            vote = {"round_no": r.get("round_no"), "match_round": n, "channel": channel,
                    "implies": start, "reason": why}
            if channel == "carrier":
                vote["frames"] = frames
            else:
                vote["rests_on"] = "carrier"
            out["votes"].append(vote)
            if start is not None:
                implied[start].append(r.get("round_no"))
    sides = [s for s in SIDES if implied[s]]
    if len(sides) == 1:
        out["starting_side"] = sides[0]
    elif sides:
        out["reason"] = "starting_side_conflict"
        out["disagreements"].append({"check": "starting_side_conflict",
                                     "rounds": {s: sorted(set(v)) for s, v in implied.items()}})
    else:
        out["reason"] = "no_attack_evidence"
    return out


def final_round(t, score_left, score_right, clock_ms, rounds: list[dict]) -> dict | None:
    """The match's last round when the scoreline never showed its result.

    The score increment ends every other round, but at match end the scoreline
    gives way to the end screen, so the deciding increment is often never read
    and the final round vanished with the events in it. When the last read
    score does not end the match, exactly one result of one more round does
    [domain:rounds/match-end]; that names the winner. The round needs its own
    evidence of starting -- a buy-phase clock reset after the last end -- and
    ends at the last sample where the scoreline was read. None where either is
    missing, or where no single result ends the match (a capture cut short).
    """
    if not rounds:
        return None
    last = rounds[-1]
    left = last["left_before"] + int(last["won_left"])
    right = last["right_before"] + int(not last["won_left"])
    if match_over(left, right):
        return None
    ending = [won_left for won_left, (a, b) in ((True, (left + 1, right)),
                                                (False, (left, right + 1)))
              if match_over(a, b)]
    if len(ending) != 1 or clock_ms is None:
        return None
    start = _clock_reset_after(t, clock_ms, last["t_end_ms"])
    if start is None:
        return None
    read = [float(t[i]) for i in range(len(t))
            if t[i] > start and score_left[i] is not None and score_right[i] is not None]
    if not read:
        return None
    return {"t_start_ms": start, "t_end_ms": read[-1], "left_before": left,
            "right_before": right, "won_left": ending[0], "start_source": "clock_reset",
            "end_source": "match_end_rule"}


def _tracks(t, masks, dividers):
    return [a for a in track_entries(t, masks, dividers) if a["counted"]]


def _death_tracks(table) -> list[dict]:
    names = set(table.column_names)
    div = table.column("kf_death_wx").to_pylist() if "kf_death_wx" in names else None
    return merge_split_tracks(_tracks(
        table.column("t_ms").to_pylist(), table.column("kf_death_mask").to_pylist(), div))


def player_death_times(table) -> list[float]:
    """First-seen time of each counted killfeed entry for the player's death,
    the same tracks `build_rounds` counts, for readers that need the instants
    rather than a per-round count."""
    return sorted(e["t_first"] for e in _death_tracks(table))


def player_second_life_times(table, second_life: list[dict] | None) -> list[float]:
    """The instants among `player_death_times` that
    `adjudication.death.split_second_lives` calls second lives over the stored
    badge reads `second_life`, as `build_rounds` splits its count; none where
    `second_life` is None."""
    from .adjudication.death import split_second_lives
    return sorted(e["t_first"] for e in split_second_lives(_death_tracks(table), second_life)[1])


#: The player's team is drawn on the LEFT of the scoreline. Structural, not
#: inferred, and settled 2026-08-27 by three independent lines:
#:
#: * **direct**: the top HUD band on `5822b6646448` at t=2206s shows the GREEN
#:   ally bar left with score 11 and the RED enemy bar right with 12. The
#:   scoreline is coloured by team, so it says which side is ours outright;
#: * **statistical**: `infer_player_side` resolves LEFT on 14 sessions and RIGHT
#:   on none, abstaining on 3. Under a coin flip that is p ~ 6e-5;
#: * **structural**: the roster bars are green-left / red-right (see "The top HUD
#:   says more than it looks like"), in the same order as the scoreline.
#:
#: This matters because abstaining left `won` NULL for every round of the
#: abstaining sessions -- 43 rounds, including all 23 of Lotus, the session
#: queued for labelling. The old comment was right that a coin flip here would
#: corrupt every win rate downstream; the answer is not to flip a coin but to
#: stop guessing at something the pixels state directly.
PLAYER_SIDE = "left"


def infer_player_side(rounds: list[dict]) -> tuple[str | None, float]:
    """Which side of the scoreline is the player's team, and how sure.

    **Demoted 2026-08-27 to a CHECK.** `PLAYER_SIDE` decides; this is kept
    because a disagreement is a real finding -- either a session where the
    player traded unusually, or a capture whose scoreline is mirrored -- and it
    is free to keep computing. `build_rounds` records the verdict per round as
    `side_inferred` / `side_agrees` and never lets it override.

    Nothing on screen says it -- the scoreline is left and right, not us and
    them -- but the player trades better in rounds the team wins, so the kills
    minus deaths separates the two outcomes. Returns ("left"|"right",
    separation) as the gap in mean differential.

    Returns None when the data did not decide, which a lopsided match makes
    common: 13-4 leaves four rounds on one side and no amount of arithmetic
    rescues that. An unresolved side leaves `won` null rather than guessed --
    a coin flip here would silently corrupt every win-rate downstream.
    """
    diff = lambda r: r["player_kills"] - r["player_deaths"]
    left = [diff(r) for r in rounds if r["won_left"]]
    right = [diff(r) for r in rounds if not r["won_left"]]
    if len(left) < 4 or len(right) < 4:
        return None, 0.0
    ml, mr = float(np.mean(left)), float(np.mean(right))
    if abs(ml - mr) < 0.15:
        return None, abs(ml - mr)
    return ("left" if ml > mr else "right"), abs(ml - mr)


def in_round_window(seq: list[dict], a: float, z: float, close: float,
                    ends: set[float]) -> list[dict]:
    """The events of `seq` that belong to the round that starts at `a`, is
    decided at `z` and closes at `close`, the next round's buy-phase snap.

    Two rules, each found against the combat report (`adjudication.combat_report`):

    * **The post-round period is part of the round.** Kills stay legal and count
      until the snap to the next buy phase [domain:rounds/post-round-period], so
      an event after the score increment belongs to the round just decided.
      Until `round-0.4.0` those events belonged to no round.
    * **The decisive event is the round's own.** The score increments on the
      sample where the last player dies, so that killfeed entry shares `z`.
      Where rounds touch (`z` is the next round's start) the shared instant
      belongs to the round it ends, never to both. `a <= t < z` dropped it and
      over the 17 `KNOWN_KD` sessions lost 25 of the player's deaths.
    """
    return [e for e in seq
            if a <= e["t_first"] and (e["t_first"] < close or e["t_first"] == z)
            and not (e["t_first"] == a and a in ends and a != z)]


def round_containing(t_ms: float, rounds: list[dict]) -> dict | None:
    """The round of `rounds` (`build_rounds` rows, which carry `t_close_ms`)
    an instant belongs to by `in_round_window`, or None outside every round."""
    ends = {r["t_end_ms"] for r in rounds}
    e = [{"t_first": t_ms}]
    return next((r for r in rounds if in_round_window(
        e, r["t_start_ms"], r["t_end_ms"], r["t_close_ms"], ends)), None)


def place_unread_starts(rounds: list[dict]) -> list[dict]:
    """Start each round whose buy-phase reset went unread one median post-round
    gap after the previous round's end, and label it `post_round_gap`.

    Without a reset, `round_bounds` starts the next round AT the score
    increment, so its close (`round_closes`) is the end itself and every event
    of the post-round period [domain:rounds/post-round-period] fell into the
    NEXT round. Against Riot's records over the 21 scored matches, all 7
    post-round deaths stamped with the wrong round followed such a start, and
    none followed a read reset; with this rule those 7 deaths move to their own
    round [metric:round_no_post_round/riot-21#changed=7], no post-round death
    is wrong [metric:round_no_post_round/riot-21#post_wrong=0] and no other
    death moves [metric:round_no_post_round/riot-21#changed_not_post_fix=0].

    The gap is the session's median over rounds whose reset was read (the
    estimate `round_closes` already uses for the last round's tail); a session
    with no read reset keeps the score-increment start. The start never passes
    the round's own end. Edits `rounds` in place and returns it.
    """
    gaps = [n["t_start_ms"] - p["t_end_ms"] for p, n in zip(rounds, rounds[1:])
            if n.get("start_source") == "clock_reset" and n["t_start_ms"] > p["t_end_ms"]]
    if not gaps:
        return rounds
    gap = float(np.median(gaps))
    for p, n in zip(rounds, rounds[1:]):
        if n.get("start_source") == "score_increment":
            n["t_start_ms"] = min(p["t_end_ms"] + gap, n["t_end_ms"])
            n["start_source"] = "post_round_gap"
    return rounds


def round_closes(rounds: list[dict]) -> list[float]:
    """Each round's close: the next round's start, and for the last round one
    median post-round gap after its end (its own end where no gap is seen)."""
    starts = [r["t_start_ms"] for r in rounds]
    gaps = [n - r["t_end_ms"] for r, n in zip(rounds, starts[1:]) if n > r["t_end_ms"]]
    tail = float(np.median(gaps)) if gaps else 0.0
    return [max(n, r["t_end_ms"]) for r, n in zip(rounds, starts[1:])] + (
        [rounds[-1]["t_end_ms"] + tail] if rounds else [])


def build_rounds(table, second_life: list[dict] | None = None,
                 plant_graphic: dict[float, dict] | None = None) -> list[dict]:
    """One row per round, from a session's stored HUD reads.

    `second_life` is the stored `second_life_observation` rows. Given them, a
    player death that `adjudication.death.second_life_death` calls a second
    life (Run It Back) is counted in `player_second_lives`, not as a death;
    without them every death is counted, as before.

    `plant_graphic` is the stored planted-spike graphic samples by time
    (`plant_graphic.stored_reads`); without them a round's plant is null
    unless the superseded clock-run rule marks one (`plant_state`).
    """
    names = set(table.column_names)
    t = table.column("t_ms").to_pylist()
    clock = table.column("clock_ms").to_pylist()
    div = lambda c: table.column(c).to_pylist() if c in names else None

    sl, sr = table.column("score_left").to_pylist(), table.column("score_right").to_pylist()
    rounds = round_bounds(t, sl, sr, clock)
    for r in rounds:
        r["end_source"] = "score_increment"
    last = final_round(t, sl, sr, clock, rounds)
    if last is not None:
        rounds.append(last)
    place_unread_starts(rounds)
    kills = merge_split_tracks(_tracks(t, table.column("kf_kill_mask").to_pylist(), div("kf_kill_wx")))
    deaths = merge_split_tracks(_tracks(t, table.column("kf_death_mask").to_pylist(), div("kf_death_wx")))
    from .adjudication.death import split_second_lives
    deaths, lives = split_second_lives(deaths, second_life)
    entries = _tracks(t, table.column("kf_entry_mask").to_pylist(), div("kf_entry_wx"))

    ends = {r["t_end_ms"] for r in rounds}
    closes = round_closes(rounds)
    for idx, (r, c) in enumerate(zip(rounds, closes), start=1):
        a, z = r["t_start_ms"], r["t_end_ms"]
        r["t_close_ms"] = c
        in_round = lambda seq: in_round_window(seq, a, z, c, ends)
        rk, rd, re_ = in_round(kills), in_round(deaths), in_round(entries)
        r["round_no"] = idx
        r["player_kills"] = len(rk)
        r["player_deaths"] = len(rd)
        r["player_second_lives"] = len(in_round(lives)) if second_life is not None else None
        r["multikill"] = len(rk)

        # First blood: the earliest entry of the round, whoever it belonged to.
        first = min(re_, key=lambda e: e["t_first"], default=None)
        r["first_event"] = "none"
        if first is not None:
            near = lambda seq: any(abs(e["t_first"] - first["t_first"]) <= FIRST_BLOOD_TOL_MS
                                   for e in seq)
            r["first_event"] = ("player_kill" if near(rk)
                                else "player_death" if near(rd) else "other")

        # The plant is the spike graphic standing where the digits are, a
        # persistent state, not a one-sample clock jump. See `plant_state`.
        r.update(plant_state(t, clock, a, z, plant_graphic))

    # PLAYER_SIDE decides; the inference is carried alongside as a check whose
    # disagreement is worth looking at, never as the answer.
    inferred, sep = infer_player_side(rounds)
    side = PLAYER_SIDE
    for r in rounds:
        r["player_side"] = side
        r["side_inferred"] = inferred or "abstain"
        r["side_separation"] = round(sep, 3)
        r["side_agrees"] = bool(inferred is None or inferred == side)
        r["won"] = bool(r["won_left"] == (side == "left"))
        r["score_us"] = r["left_before"] if side == "left" else r["right_before"]
        r["score_them"] = r["right_before"] if side == "left" else r["left_before"]
    return rounds


def summarise(rounds: list[dict]) -> dict:
    """Win rate overall and conditioned on each round fact.

    Reported as lift against the baseline with a Wilson interval and an explicit
    n, never as a p-value. With a dozen facts and six maps the multiple-
    comparisons problem is not a risk, it is a certainty -- so the output is
    framed as hypotheses to check against more data, and a cell of four rounds
    is meant to look like a cell of four rounds.
    """
    scored = [r for r in rounds if r["won"] is not None]
    n = len(scored)
    base = sum(r["won"] for r in scored) / n if n else 0.0
    facts = {
        "first blood (player)": lambda r: r["first_event"] == "player_kill",
        "first death (player)": lambda r: r["first_event"] == "player_death",
        "first blood (neither)": lambda r: r["first_event"] == "other",
        "player got 2k+": lambda r: r["multikill"] >= 2,
        "player got 3k+": lambda r: r["multikill"] >= 3,
        "player died": lambda r: r["player_deaths"] >= 1,
        "player survived": lambda r: r["player_deaths"] == 0,
        "spike planted": lambda r: r["spike_planted"],
    }
    out = {"n_rounds": n, "baseline": base, "facts": []}
    for label, f in facts.items():
        sel = [r for r in scored if f(r)]
        if not sel:
            continue
        k, m = sum(r["won"] for r in sel), len(sel)
        out["facts"].append({"fact": label, "n": m, "wins": k,
                             "rate": k / m, "lift": k / m - base,
                             "lo": _wilson(k, m)[0], "hi": _wilson(k, m)[1]})
    out["facts"].sort(key=lambda d: -abs(d["lift"]))
    return out


def _wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return max(0.0, (c - half) / d), min(1.0, (c + half) / d)


def round_events(rounds: list[dict], session_id: str) -> list[dict]:
    """Convert round records from build_rounds into formal SESSION_BOUNDARY events.

    Each round produces:
    - boundary_type="round_start" at t_start_ms
    - boundary_type="round_end" at t_end_ms
    """
    from .events import session_boundary_event, SourceChannel
    from .version import ROUND_VERSION

    events = []
    for r in rounds:
        r_no = r.get("round_no")
        events.append(session_boundary_event(
            session_id=session_id,
            t_ms=float(r["t_start_ms"]),
            boundary_type="round_start",
            source_channel=SourceChannel.ROUNDS,
            producer_version=ROUND_VERSION,
            round_no=r_no,
            metadata={
                "start_source": r.get("start_source"),
            },
        ).to_dict())

        events.append(session_boundary_event(
            session_id=session_id,
            t_ms=float(r["t_end_ms"]),
            boundary_type="round_end",
            source_channel=SourceChannel.ROUNDS,
            producer_version=ROUND_VERSION,
            round_no=r_no,
            metadata={
                "won_left": r.get("won_left"),
                "left_before": r.get("left_before"),
                "right_before": r.get("right_before"),
                "spike_planted": r.get("spike_planted"),
                "plant_t_ms": r.get("plant_t_ms"),
                "plant_source": r.get("plant_source"),
                "plant_reason": r.get("plant_reason"),
            },
        ).to_dict())
    return events

