"""Stage 05: rounds, derived from stored L1 (design doc SS3).

Why the round is the unit
-------------------------
Grant's framing, and it is the reason this table exists: a round is very nearly
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
  is also the player's kill he took it; if it is his death he was traded out
  first. No new extractor and no name reading;
* **which side of the scoreline is the player's** -- see `infer_player_side`.
  Eleven sessions infer "left" independently and unanimously, so the player's
  team is on the left; the two that abstain are the shortest matches in the set.

**`spike_planted` is unreliable and should not be used yet.** The post-plant
timer is a fixed 45 s (confirmed by Grant), so a plant is a discontinuity in the
round clock -- but catching a one-sample jump needs two readable clock values
straddling it, and the clock reads at only ~50% at 2 Hz. It finds 6 plants in
262 rounds where the true figure is many times that. The fix is not a better
threshold: a plant leaves a *persistent* state on screen for those 45 s, and a
state that lasts 90 samples is trivial to catch where a single transition is
not. Read the planted indicator instead of inferring the jump.

The plant is a **phase boundary**, not just a fact (Grant). Pre-plant and
post-plant are different games -- attackers switch to holding, defenders must
retake -- so a round splits into two phases, and the *state at the transition*
(players alive each side, whether the player is alive, time left) is a covariate
for everything that follows it. That is the shape the next version wants, and it
is another reason `spike_planted` has to become reliable before it is used.

Two ways in, both better than the clock jump: Grant reports a **spike icon at
the top of the screen** once planted, which persists for the whole 45 s, and an
**audio cue**, which this pipeline has never touched but which is a far cheaper
signal than pixels for an event with a fixed duration.

**A round ends exactly three ways** (Grant): team wipe, spike defused, spike
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
different too, and the side swaps at halftime -- also not yet known.

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
"""

from __future__ import annotations

import numpy as np

from .checks import KF_MIN_OBS, track_entries
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


def round_bounds(t, score_left, score_right) -> list[dict]:
    """Rounds read off the scoreline: one ends when the total climbs by one.

    Guarded against the scoreline's known misreads. `ocr.py` drops a transient
    extra digit (1 -> 11 -> 1 on 9acf02f98283), so an increment is only believed
    when the total rises by exactly one *and* neither side's score falls -- a
    spurious digit fails both tests.
    """
    out: list[dict] = []
    prev = None
    start = float(t[0]) if len(t) else 0.0
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
            })
            start = float(t[i])
        if (a, b) != prev:
            prev = (a, b)
    return out


def _tracks(t, masks, dividers):
    return [a for a in track_entries(t, masks, dividers) if a["counted"]]


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
    them -- but the player trades better in rounds his team wins, so his kills
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


def build_rounds(table) -> list[dict]:
    """One row per round, from a session's stored HUD reads."""
    names = set(table.column_names)
    t = table.column("t_ms").to_pylist()
    clock = table.column("clock_ms").to_pylist()
    div = lambda c: table.column(c).to_pylist() if c in names else None

    rounds = round_bounds(t, table.column("score_left").to_pylist(),
                          table.column("score_right").to_pylist())
    kills = _tracks(t, table.column("kf_kill_mask").to_pylist(), div("kf_kill_wx"))
    deaths = _tracks(t, table.column("kf_death_mask").to_pylist(), div("kf_death_wx"))
    entries = _tracks(t, table.column("kf_entry_mask").to_pylist(), div("kf_entry_wx"))

    for idx, r in enumerate(rounds, start=1):
        a, z = r["t_start_ms"], r["t_end_ms"]
        in_round = lambda seq: [e for e in seq if a <= e["t_first"] < z]
        rk, rd, re_ = in_round(kills), in_round(deaths), in_round(entries)
        r["round_no"] = idx
        r["player_kills"] = len(rk)
        r["player_deaths"] = len(rd)
        r["multikill"] = len(rk)

        # First blood: the earliest entry of the round, whoever it belonged to.
        first = min(re_, key=lambda e: e["t_first"], default=None)
        r["first_event"] = "none"
        if first is not None:
            near = lambda seq: any(abs(e["t_first"] - first["t_first"]) <= FIRST_BLOOD_TOL_MS
                                   for e in seq)
            r["first_event"] = ("player_kill" if near(rk)
                                else "player_death" if near(rd) else "other")

        # A plant resets the clock to 45 s well inside the round.
        planted = False
        prev_c = None
        for i in range(len(t)):
            if not (a <= t[i] < z) or clock[i] is None:
                continue
            c = clock[i]
            if (prev_c is not None
                    and abs(c - SPIKE_MS) <= SPIKE_TOL_MS
                    and abs(prev_c - SPIKE_MS) >= SPIKE_STEP_MIN_MS
                    and t[i] - a >= SPIKE_MIN_ELAPSED_MS):
                planted = True
                break
            prev_c = c
        r["spike_planted"] = planted

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
